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
from .http_cache import UpstreamError, describe, fetch_text, forget
from .vatsim import assigned_squawk, fp_wake, parse_time

log = logging.getLogger("polids.flightplan")

# komunikat w interfejsie, gdy godzin nie ma (bez nazwy źródła; szczegóły błędu tylko w logu)
HOURS_DOWN = "Hours unavailable"
HOURS_TTL_S = 12 * 3600
HOURS_WAIT_S = 1.5
HOURS_MISS_S = 3600     # 404 albo odpowiedź bez godzin: członek bez statystyk
HOURS_FAIL_S = 600      # inny błąd (sieć, 5xx, nie JSON)

# ratingi pilota VATSIM (pole pilot_rating), gdy data feed nie poda własnej listy pilot_ratings
PILOT_RATINGS = {0: ("NEW", "Basic Member"), 1: ("PPL", "Private Pilot License"), 3: ("IR", "Instrument Rating"),
                 7: ("CMEL", "Commercial Multi-Engine License"), 15: ("ATPL", "Airline Transport Pilot License"),
                 31: ("FI", "Flight Instructor"), 63: ("FE", "Flight Examiner")}

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
# końcówka nazwy jak kod ICAO lotniska macierzystego ("Jan Kowalski EPKK", "Jan Kowalski (EPKK)")
_HOME_BASE = re.compile(r"\(?[A-Z]{4}\)?")
_PUNCT = re.compile(r"[-–|/,.]+")


def _s(value) -> str | None:
    """Wartość planu lotu jako napis bez spacji na brzegach; pusty → None (feed podaje wszystko jako napisy)."""
    s = str(value).strip() if value is not None else ""
    return s or None


def split_name(name, cid=None) -> tuple[str | None, str | None]:
    """Imię i nazwisko z nazwy pilota w sieci (heurystyka: to nazwa wyświetlana, nie dane weryfikowane).

    Pusta nazwa, same cyfry albo CID (członek ukrywa nazwisko) → (None, None). Jedna końcowa część jak kod ICAO
    lotniska macierzystego ("EPKK") jest odrzucana, jeśli zostaje więcej niż jedno słowo albo nazwa ma małe litery
    (w "JAN NOWA" NOWA to raczej nazwisko). Imię = pierwsze słowo, nazwisko = reszta ("Anna Maria Nowak" →
    "Anna" / "Maria Nowak", "Jan van der Berg" → "Jan" / "van der Berg")."""
    s = " ".join(str(name or "").split())
    if not s or s.replace(" ", "").isdigit() or (cid is not None and s == str(cid)):
        return None, None
    words = s.split(" ")
    if len(words) > 1 and _HOME_BASE.fullmatch(words[-1]) and (len(words) > 2 or s != s.upper()):
        words = words[:-1]
        while len(words) > 1 and _PUNCT.fullmatch(words[-1]):   # "Jan Kowalski - EPKK"
            words = words[:-1]
    first, last = words[0], " ".join(words[1:])
    return first, last or None


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


def find_flight_plan(feed: dict, callsign: str) -> dict | None:
    """Plan lotu po znaku (dokładnie, bez względu na wielkość liter): najpierw pilot online, potem prefile
    (kilka prefile z tym samym znakiem: najnowszy last_updated). None = nie ma ani pilota, ani prefile.
    Pilot online bez planu: flight_plan = None. Godziny (hours) dokłada router."""
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
    first, last = split_name(p.get("name"), p.get("cid"))
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
    try:
        hours = parse_member_hours(json.loads(await fetch_text(stats_url(cid), HOURS_TTL_S)))
        miss = HOURS_MISS_S if hours is None else 0
    except UpstreamError as exc:
        log.warning("member stats: %s", describe(exc))
        hours, miss = None, HOURS_MISS_S if _not_found(exc) else HOURS_FAIL_S
    except Exception as exc:  # noqa: BLE001 - odpowiedź nie-JSON albo nieoczekiwany kształt
        log.warning("member stats: %s", type(exc).__name__)
        hours, miss = None, HOURS_FAIL_S
    if miss:
        _miss[cid] = time.monotonic() + miss
        forget(stats_url(cid))   # po przerwie pytamy serwer, nie cache z nieczytelną odpowiedzią
    else:
        _miss.pop(cid, None)
    return hours


async def member_hours(cid, wait: float | None = None) -> dict | None:
    """Godziny członka albo None (brak statystyk, błąd, przerwa po błędzie albo brak odpowiedzi w `wait` s,
    domyślnie HOURS_WAIT_S). Zapytanie, które nie zdążyło, kończy się w tle i trafia do cache: następne
    odświeżenie pokaże godziny."""
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
        return None
    task = _tasks.get(cid)
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = _tasks[cid] = asyncio.ensure_future(_load_hours(cid))
        task.add_done_callback(lambda t, c=cid: _tasks.pop(c) if _tasks.get(c) is t else None)
    done, _pending = await asyncio.wait({task}, timeout=HOURS_WAIT_S if wait is None else wait)
    return task.result() if done else None


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
