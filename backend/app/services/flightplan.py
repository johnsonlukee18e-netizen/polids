"""OTHER › FLIGHT PLAN (0.13.0, issue #23): plan lotu po znaku wywoławczym z data feed VATSIM (pilot online albo
prefile) z danymi pilota: imię i nazwisko z nazwy w sieci, PID (= CID), rating pilota i godziny pilota i ATC
z API członków VATSIM (/v2/members/{cid}/stats).

API członków pytamy tylko o jednego pilota na jedno wyszukanie (nigdy hurtowo, np. dla wszystkich samolotów na mapie):
ma limity zapytań. Godziny zmieniają się powoli, więc cache jest długi; członka bez statystyk (404) albo po błędzie
nie pytamy ponownie przez chwilę, a na odpowiedź czekamy najwyżej HOURS_WAIT_S: wolne API nie opóźnia planu lotu.
Nazw pilotów (dane osobowe) nie zapisujemy w logu."""

import asyncio
import json
import logging
import math
import re
import time
from datetime import datetime, timezone

import httpx

from ..config import settings
from .http_cache import UpstreamError, describe, fetch_text, forget, peek
from .vatsim import assigned_squawk, fp_wake, parse_time

log = logging.getLogger("polids.flightplan")

# komunikat w interfejsie, gdy godzin nie ma (bez nazwy źródła; szczegóły błędu tylko w logu)
HOURS_DOWN = "Hours unavailable"
# zły znak w adresie (ten sam tekst co w polu FLIGHT PLAN)
CALLSIGN_BAD = "Callsign must be 2–12 letters or digits"
HOURS_TTL_S = 12 * 3600
HOURS_WAIT_S = 1.5
HOURS_MISS_S = 3600     # 404 albo odpowiedź bez godzin: członek bez statystyk
HOURS_FAIL_S = 600      # inny błąd (sieć, 5xx, nie JSON)

# ratingi pilota VATSIM (pole pilot_rating), gdy data feed nie poda własnej listy pilot_ratings
PILOT_RATINGS = {0: ("NEW", "Basic Member"), 1: ("PPL", "Private Pilot License"), 3: ("IR", "Instrument Rating"),
                 7: ("CMEL", "Commercial Multi-Engine License"), 15: ("ATPL", "Airline Transport Pilot License"),
                 31: ("FI", "Flight Instructor"), 63: ("FE", "Flight Examiner")}

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
# końcówka nazwy jak kod ICAO lotniska macierzystego ("Jan Kowalski EPKK", "Jan Kowalski (EPKK)", "[EPKK]",
# "-EPKK", "EPKK.", "EPKK/EPWA"): kody bez nawiasów i znaków przestankowych wokół
_CODE = re.compile(r"[A-Za-z]{4}")
_WRAP = "()[]{}<>-–|,.;:"
_PUNCT = re.compile(r"[-–|/,.]+")


def _s(value) -> str | None:
    """Wartość planu lotu jako napis bez spacji na brzegach; pusty → None (feed podaje wszystko jako napisy)."""
    s = str(value).strip() if value is not None else ""
    return s or None


def _home_base(word: str, known) -> list[str] | None:
    """Kody lotnisk z ostatniego słowa nazwy ("(EPKK)" → ["EPKK"], "EPKK/EPWA" → ["EPKK", "EPWA"]) albo None.
    known(kod) → czy to lotnisko (baza punktów AD); bez known każde 4 wielkie litery (bez bazy, np. testy)."""
    core = word.strip(_WRAP)
    codes = core.split("/") if core else []
    if not codes or not all(_CODE.fullmatch(c) for c in codes):
        return None
    if known is None:
        return codes if all(c.isupper() for c in codes) else None
    return codes if all(known(c.upper()) for c in codes) else None


def split_name(name, cid=None, known=None) -> tuple[str | None, str | None]:
    """Imię i nazwisko z nazwy pilota w sieci (heurystyka: to nazwa wyświetlana, nie dane weryfikowane).

    Najpierw odpada jedna końcowa część jak kod ICAO lotniska macierzystego ("EPKK", "(EPKK)", "[EPKK]", "-EPKK"),
    jeśli to znane lotnisko (known(kod), router pyta bazę punktów AD; bez known: 4 wielkie litery) i zostaje więcej
    niż jedno słowo, nazwa ma małe litery, kod jest w nawiasach albo reszta to sam CID (w "JAN NOWA" NOWA to raczej
    nazwisko, w "John KING" KING nie jest lotniskiem). Potem: pusta nazwa, same cyfry albo CID (członek ukrywa
    nazwisko) → (None, None). Imię = pierwsze słowo (bez przecinka z "Kowalski, Jan"), nazwisko = reszta
    ("Anna Maria Nowak" → "Anna" / "Maria Nowak", "Jan van der Berg" → "Jan" / "van der Berg")."""
    s = " ".join(str(name or "").split())
    words = s.split(" ") if s else []
    if len(words) > 1 and _home_base(words[-1], known):
        rest = words[:-1]
        while len(rest) > 1 and _PUNCT.fullmatch(rest[-1]):   # "Jan Kowalski - EPKK"
            rest = rest[:-1]
        text = " ".join(rest)
        marked = words[-1].strip(_WRAP) != words[-1]
        if len(rest) > 1 or text != text.upper() or marked or text.isdigit():
            words = rest
    s = " ".join(words)
    if not s or s.replace(" ", "").isdigit() or (cid is not None and s == str(cid)):
        return None, None
    first, last = words[0].rstrip(","), " ".join(words[1:])
    return first or None, last or None


def rating(value, feed: dict | None = None) -> dict | None:
    """Rating pilota: {"id", "short", "long"} z listy pilot_ratings w feedzie albo z tabeli PILOT_RATINGS."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    for r in (feed or {}).get("pilot_ratings") or []:
        if isinstance(r, dict) and r.get("id") == value:
            return {"id": value, "short": _s(r.get("short_name")), "long": _s(r.get("long_name"))}
    short, long = PILOT_RATINGS.get(value, (None, None))
    return {"id": value, "short": short, "long": long}


def plan_fields(fp: dict | None) -> dict | None:
    """Wszystkie standardowe pola planu lotu VATSIM (napisy, puste → None); None bez planu."""
    if not isinstance(fp, dict) or not fp:
        return None
    rev = fp.get("revision_id")
    return {
        "rules": _s(fp.get("flight_rules")),
        "aircraft_icao": _s(fp.get("aircraft")), "aircraft": _s(fp.get("aircraft_short")),
        "aircraft_faa": _s(fp.get("aircraft_faa")), "wake": fp_wake(fp.get("aircraft")),
        "departure": _s(fp.get("departure")), "deptime": _s(fp.get("deptime")),
        "tas": _s(fp.get("cruise_tas")), "altitude": _s(fp.get("altitude")), "route": _s(fp.get("route")),
        "arrival": _s(fp.get("arrival")), "enroute_time": _s(fp.get("enroute_time")),
        "alternate": _s(fp.get("alternate")), "fuel_time": _s(fp.get("fuel_time")), "remarks": _s(fp.get("remarks")),
        "revision_id": rev if isinstance(rev, int) and not isinstance(rev, bool) else None,
        "assigned_squawk": assigned_squawk(fp),
    }


def _same(p, cs: str) -> bool:
    return isinstance(p, dict) and str(p.get("callsign") or "").strip().upper() == cs


def find_flight_plan(feed: dict, callsign: str, known=None) -> dict | None:
    """Plan lotu po znaku (dokładnie, bez względu na wielkość liter): najpierw pilot online, potem prefile
    (kilka prefile z tym samym znakiem: najnowszy last_updated). None = nie ma ani pilota, ani prefile.
    Pilot online bez planu: flight_plan = None. Godziny (hours) dokłada router. known: jak w split_name."""
    cs = str(callsign or "").strip().upper()
    if not cs:
        return None
    pilot = next((p for p in feed.get("pilots") or [] if _same(p, cs)), None)
    if pilot is not None:
        status, p = "online", pilot
    else:
        pre = [p for p in feed.get("prefiles") or [] if _same(p, cs)]
        if not pre:
            return None
        status, p = "prefiled", max(pre, key=lambda x: parse_time(x.get("last_updated")) or _EPOCH)
    first, last = split_name(p.get("name"), p.get("cid"), known)
    cid = p.get("cid") if isinstance(p.get("cid"), int) and not isinstance(p.get("cid"), bool) else None
    pos = None
    if status == "online":
        pos = {"lat": p.get("latitude"), "lon": p.get("longitude"), "altitude": p.get("altitude"),
               "groundspeed": p.get("groundspeed"), "heading": p.get("heading"), "squawk": _s(p.get("transponder"))}
    return {"callsign": cs, "status": status, "updated": (feed.get("general") or {}).get("update_timestamp"),
            "last_updated": p.get("last_updated"), "logon_time": p.get("logon_time") if status == "online" else None,
            "pid": cid, "name": _s(p.get("name")), "first_name": first, "last_name": last,
            "pilot_rating": rating(p.get("pilot_rating"), feed) if status == "online" else None,
            "flight_plan": plan_fields(p.get("flight_plan")), "position": pos}


# --- godziny pilota i ATC z API członków VATSIM

def stats_url(cid: int) -> str:
    return f"{settings.vatsim_api_url.rstrip('/')}/v2/members/{int(cid)}/stats"


def _hours(value) -> float | None:
    """Liczba godzin (float albo napis z liczbą); ujemne, NaN, bool i inne typy → None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        x = float(value)
    elif isinstance(value, str) and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value):
        x = float(value)
    else:
        return None
    return round(x, 1) if math.isfinite(x) and x >= 0 else None


def parse_member_hours(data) -> dict | None:
    """{"pilot": godziny, "atc": godziny} z odpowiedzi /stats ({"id", "atc", "pilot", "s1", ...}); None bez obu."""
    if not isinstance(data, dict):
        return None
    out = {"pilot": _hours(data.get("pilot")), "atc": _hours(data.get("atc"))}
    return out if out["pilot"] is not None or out["atc"] is not None else None


_miss: dict[int, float] = {}          # cid → do kiedy (monotonic) nie pytamy ponownie
_tasks: dict[int, asyncio.Task] = {}  # zapytania w toku (także te, które nie zdążyły w HOURS_WAIT_S)


def _not_found(exc: UpstreamError) -> bool:
    cause = exc.__cause__
    return isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 404


async def _load_hours(cid: int) -> dict | None:
    url = stats_url(cid)
    drop = False
    try:
        hours = parse_member_hours(json.loads(await fetch_text(url, HOURS_TTL_S)))
        hit = peek(url)
        if hours is None:
            miss, drop = HOURS_MISS_S, True
        elif hit and hit[0] >= HOURS_TTL_S:
            # serwer nie odpowiedział, fetch_text oddał starsze godziny: krótka przerwa (w niej godziny z cache),
            # inaczej każde wyszukanie znowu czekałoby na niedziałające API
            miss = HOURS_FAIL_S
        else:
            miss = 0
    except UpstreamError as exc:
        log.warning("member stats: %s", describe(exc))
        hours, miss, drop = None, HOURS_MISS_S if _not_found(exc) else HOURS_FAIL_S, True
    except Exception as exc:  # noqa: BLE001 - odpowiedź nie-JSON albo nieoczekiwany kształt
        log.warning("member stats: %s", type(exc).__name__)
        hours, miss, drop = None, HOURS_FAIL_S, True
    if miss:
        _miss[cid] = time.monotonic() + miss
    else:
        _miss.pop(cid, None)
    if drop:
        forget(url)   # po przerwie pytamy serwer, nie cache z nieczytelną odpowiedzią
    return hours


def _cached_hours(cid: int) -> dict | None:
    """Godziny z ostatniej odpowiedzi w cache, także starszej niż HOURS_TTL_S (None = brak albo nieczytelna)."""
    hit = peek(stats_url(cid))
    if not hit:
        return None
    try:
        return parse_member_hours(json.loads(hit[1]))
    except ValueError:
        return None


async def member_hours(cid, wait: float | None = None) -> dict | None:
    """Godziny członka albo None (brak statystyk, błąd bez starszych danych albo brak odpowiedzi w `wait` s,
    domyślnie HOURS_WAIT_S). Zapytanie, które nie zdążyło, kończy się w tle i trafia do cache: następne
    odświeżenie pokaże godziny. W przerwie po błędzie i gdy odpowiedź nie zdążyła: starsze godziny z cache."""
    if isinstance(cid, bool):
        return None
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return None
    if cid <= 0:
        return None
    now = time.monotonic()
    for k in [k for k, until in _miss.items() if until <= now]:
        del _miss[k]
    if cid in _miss:
        return _cached_hours(cid)
    task = _tasks.get(cid)
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = _tasks[cid] = asyncio.ensure_future(_load_hours(cid))
        task.add_done_callback(lambda t, c=cid: _tasks.pop(c) if _tasks.get(c) is t else None)
    done, _pending = await asyncio.wait({task}, timeout=HOURS_WAIT_S if wait is None else wait)
    return task.result() if done else _cached_hours(cid)


def hours_pending(cid) -> bool:
    """Zapytanie o godziny tego członka jeszcze trwa (nie zdążyło w HOURS_WAIT_S): FLIGHT PLAN zapyta wcześniej."""
    try:
        task = _tasks.get(int(cid))
    except (TypeError, ValueError):
        return False
    return bool(task and not task.done())


def reset_hours():
    """Testy: bez przerw po błędach i bez zapytań w toku."""
    _miss.clear()
    _tasks.clear()
