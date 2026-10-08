"""AERODROME › OVERVIEW: jeden ekran dla całego FIR EPWW (coś jak self-checkin przed otwarciem stanowiska).

Składamy w jednym zapytaniu to, co kontroler sprawdza przed objęciem stanowiska:
1. poziom przejściowy (services/tl.py) – z ATIS, a gdy lotnisko nie nadaje, wyliczony z QNH,
2. METAR + TAF wszystkich kontrolowanych lotnisk ze stanem LVP (services/lvp.py),
3. NOTAM-y obowiązujące teraz (services/notam.py, pola B)/C) ),
4. restrykcje ECFMP dla FIR EPWW (services/ecfmp.py) i regulacje vIFF na sektorach EP,
5. Airport Monitor vIFF: przepustowość i ruch z vIFF oraz liczby odlotów/przylotów z sieci VATSIM.

Filtr stanowiska: wybór np. EPWA_APP zawęża panele do lotnisk tego APP (EPWA, EPMO, EPLL, EPRA). Przypisanie
lotnisk bierzemy z pliku .ese: kolejność przejmowania (lista OWNER) wycinków CTR/TMA danego lotniska. Stanowiska
przed pierwszym sektorem ACC EPWW to "miejscowe" (TWR, APP) – lotnisko trafia pod każde z nich; sektory ACC z dalszej
części listy przejmują lotnisko top-down, więc dostają je do swojego zestawu. Nazwy wycinków i listy OWNER są
w pliku sektorowym, więc zestawy zmieniają się razem z nim, bez tabel w kodzie.

Każdy panel ma swój komunikat błędu: awaria jednego źródła (np. serwera NOTAM) nie psuje pozostałych."""

import asyncio
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Aerodrome, AtcPosition, Sector
from . import ecfmp as ecfmp_service
from . import tl as tl_service
from . import viff as viff_service
from .http_cache import UpstreamError
from .lvp import evaluate as evaluate_lvp
from .metar import parse_metar
from .notam import get_notams
from .vatsim import FACILITY_TYPES, controller_info, parse_atis
from .weather import get_metars, get_tafs

# Lotniska kontrolowane w FIR EPWW – ta sama lista co w podmenu AERODROME (frontend/js/tabs/aerodrome.js)
AERODROMES = ["EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY",
              "EPWA", "EPWR", "EPZG"]
# wycinki przestrzeni lotniska: CTR/MCTR, TMA (też L/U), oraz wycinki podejścia i odlotu z pliku .ese
# (bez granicy słowa na końcu: w pliku są nazwy z numerem pasa, np. EPKK_CTR07, EPKT_DEP08, EPWA_DIR11_A)
_SLICE = re.compile(r"^(EP[A-Z]{2})_(?:M?CTR|[LU]?TMA|APP|DEP|DIR)", re.I)
_ACC = re.compile(r"^EPWW_[A-Z0-9_]*(?:CTR|FSS)$")
_FIS = re.compile(r"information", re.I)       # FIS ma własne sektory, nie lotniska – pomijamy w filtrze
TOWER_SUFFIXES = ("TWR", "GND", "DEL", "RMP")
GROUPS = [("ACC", "ACC / FIR"), ("APP", "APP / zbliżanie"), ("TWR", "TWR / lotnisko")]


def _kind(callsign: str, name: str) -> str | None:
    """Rodzaj stanowiska do filtra: "ACC" (sektory EPWW), "APP" (zbliżanie), "TWR" (wieża, GND, DEL)."""
    cs = callsign.upper()
    suffix = cs.split("_")[-1]
    if _FIS.search(name or ""):
        return None
    if _ACC.match(cs):
        return "ACC"
    if suffix in ("APP", "DEP"):
        return "APP"
    if suffix in TOWER_SUFFIXES:
        return "TWR"
    return None


def chains(db: Session) -> dict[str, list[list[str]]]:
    """Kolejność przejmowania wycinków każdego lotniska: {ICAO: [[znaki stanowisk], ...]} z pliku .ese EPWW."""
    by_id = {p.position_id: p.callsign for p in db.scalars(select(AtcPosition))}
    out: dict[str, list[list[str]]] = {}
    for s in db.scalars(select(Sector).where(Sector.fir == "EPWW").order_by(Sector.name)):
        m = _SLICE.match(s.name)
        if not m or m.group(1).upper() not in AERODROMES:
            continue
        owners = [by_id[o] for o in s.owners.split(":") if o in by_id]
        if owners:
            out.setdefault(m.group(1).upper(), []).append(owners)
    return out


def position_airports(db: Session) -> dict[str, list[str]]:
    """Lotniska przypisane do stanowiska: {znak: [ICAO]}.

    Stanowiska miejscowe (przed pierwszym sektorem ACC na liście OWNER) dostają swoje lotnisko, sektory ACC z dalszej
    części listy – wszystkie lotniska, które przejmują top-down. Każde stanowisko APP/TWR dostaje też lotnisko
    swojego prefiksu (np. EPPO_S_APP – sektor południowy Poznania – zawsze obejmuje EPPO)."""
    out: dict[str, set[str]] = {}
    for icao, slices in chains(db).items():
        for owners in slices:
            for cs in owners:
                out.setdefault(cs, set()).add(icao)
    for p in db.scalars(select(AtcPosition)):
        cs = p.callsign.upper()
        prefix = cs.split("_")[0]
        if _kind(cs, p.name) in ("APP", "TWR") and prefix in AERODROMES:
            out.setdefault(cs, set()).add(prefix)
    return {cs: sorted(ads) for cs, ads in out.items()}


def positions(db: Session) -> dict:
    """Lista stanowisk do filtra OVERVIEW, pogrupowana ACC / APP / TWR, z lotniskami każdego stanowiska."""
    ads = position_airports(db)
    names = {a.icao: a.name for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(AERODROMES)))}
    rows: dict[str, list[dict]] = {k: [] for k, _ in GROUPS}
    for p in db.scalars(select(AtcPosition).order_by(AtcPosition.callsign)):
        kind = _kind(p.callsign, p.name)
        if kind is None:
            continue
        icao = p.callsign.split("_")[0].upper()
        if kind == "TWR" and (icao not in AERODROMES or not p.callsign.upper().endswith("_TWR")):
            continue      # w filtrze zostawiamy po jednej wieży na lotnisko (GND/DEL prowadzą tam samo)
        airports = ads.get(p.callsign.upper(), [])
        if kind in ("ACC", "APP") and not airports:
            continue      # sektor bez lotnisk (np. stanowisko wojskowe) nie zawęża niczego
        rows[kind].append({"callsign": p.callsign, "name": p.name, "frequency": p.frequency,
                           "kind": kind, "airports": airports,
                           # TWR/GND/DEL: zamiast filtra skok do PRZEGLĄDU lotniska
                           "goto": icao if kind == "TWR" else None})
    return {"groups": [{"kind": k, "label": label, "positions": rows[k]} for k, label in GROUPS],
            "aerodromes": [{"icao": i, "name": names.get(i, i)} for i in AERODROMES]}


def airports_for(db: Session, position: str | None) -> tuple[list[str], dict | None]:
    """Lotniska do pokazania i opis wybranego stanowiska. Bez filtra: wszystkie lotniska z listy."""
    if not position:
        return list(AERODROMES), None
    cs = position.upper()
    pos = db.get(AtcPosition, cs)
    kind = _kind(cs, pos.name if pos else "")
    icao = cs.split("_")[0]
    airports = position_airports(db).get(cs, [])
    info = {"callsign": cs, "name": pos.name if pos else None, "frequency": pos.frequency if pos else None,
            "kind": kind, "airports": airports, "goto": icao if kind == "TWR" and icao in AERODROMES else None,
            "known": pos is not None}
    return (airports or list(AERODROMES)), info


# --- panele -----------------------------------------------------------------------------------------------------

async def _weather(icaos: list[str]) -> tuple[dict, dict, list[str]]:
    """METAR i TAF jednym zapytaniem na wszystkie lotniska; komunikaty błędów osobno dla METAR i TAF."""
    errors: list[str] = []

    async def one(fn, label):
        try:
            return await fn(icaos)
        except (UpstreamError, ValueError, KeyError, TypeError) as exc:   # Key/TypeError: inny kształt JSON z AWC
            errors.append(f"{label}: {exc}")
            return {}

    metars, tafs = await asyncio.gather(one(get_metars, "METAR"), one(get_tafs, "TAF"))
    return metars, tafs, errors


def feed_info(feed: dict, icaos: list[str]) -> dict[str, dict]:
    """Z jednego data feedu VATSIM: ATIS, zalogowane stanowiska i liczby odlotów/przylotów dla każdego lotniska."""
    out = {i: {"atis": None, "atc": [], "departures": 0, "arrivals": 0, "prefiles": 0} for i in icaos}
    wanted = set(icaos)
    for c in feed.get("controllers", []) + feed.get("atis", []):
        cs = (c.get("callsign") or "").upper()
        icao = cs.split("_")[0]
        if icao not in wanted:
            continue
        if cs.endswith("_ATIS"):
            info = out[icao]["atis"]
            lines = c.get("text_atis") or []
            if info is None:
                out[icao]["atis"] = {"callsign": cs, "letter": c.get("atis_code") or parse_atis(lines)["letter"],
                                     "lines": list(lines)}
            else:   # ATIS odlotowy i przylotowy osobno (np. EPWA_A_ATIS i EPWA_D_ATIS)
                info["callsign"] += " / " + cs
                info["letter"] = " / ".join(x for x in (info["letter"], c.get("atis_code")) if x)
                info["lines"] += list(lines)
        elif cs.split("_")[-1] in FACILITY_TYPES:   # obserwator (EPWA_OBS) to nie stanowisko ATC
            out[icao]["atc"].append(controller_info(c))
    for p in feed.get("pilots", []):
        fp = p.get("flight_plan") or {}
        dep, arr = (fp.get("departure") or "").upper(), (fp.get("arrival") or "").upper()
        if dep in wanted:
            out[dep]["departures"] += 1
        if arr in wanted and arr != dep:
            out[arr]["arrivals"] += 1
    for p in feed.get("prefiles", []):
        fp = p.get("flight_plan") or {}
        dep = (fp.get("departure") or "").upper()
        if dep in wanted:
            out[dep]["prefiles"] += 1
    for info in out.values():
        info["atc"].sort(key=lambda c: c["callsign"])
    return out


def notam_active(n: dict, now: datetime) -> bool:
    """NOTAM obowiązujący teraz: zaczął się (pole B) i jeszcze się nie skończył (pole C albo PERM)."""
    start = datetime.fromisoformat(n["start"]) if n.get("start") else None
    end = datetime.fromisoformat(n["end"]) if n.get("end") else None
    if start and start > now:
        return False
    return not (end and end < now and not n.get("perm"))


def notam_text(n: dict) -> str:
    """Treść NOTAM-u do zwartej tabeli: pole E) w jednej linii, a gdy go nie ma – cały wpis."""
    body = (n.get("fields") or {}).get("E") or n.get("raw") or ""
    return re.sub(r"\s+", " ", body).strip()


async def _notams(icaos: list[str], now: datetime) -> dict:
    """NOTAM-y obowiązujące teraz dla pokazanych lotnisk; błąd jednego lotniska nie zabiera pozostałych."""
    async def one(icao):
        try:
            return icao, await get_notams(icao), None
        except (UpstreamError, ValueError) as exc:
            # UpstreamError zaczyna się od adresu z kodem lotniska: bez niego ten sam błąd skleja się w jedną linię
            return icao, None, str(exc).split(": ", 1)[-1] if str(exc).startswith("http") else str(exc)

    items, errors = [], {}
    for icao, data, error in await asyncio.gather(*(one(i) for i in icaos)):
        if error is not None:
            errors.setdefault(error, []).append(icao)
            continue
        for n in data["notams"]:
            if notam_active(n, now):
                items.append({"icao": icao, "id": n.get("id"), "text": notam_text(n), "start": n.get("start"),
                              "end": n.get("end"), "perm": n.get("perm"), "est": n.get("est"),
                              "schedule": n.get("schedule"), "raw": n.get("raw")})
    items.sort(key=lambda n: (n["icao"], n["id"] or ""))
    error = "; ".join(f"{', '.join(ads)}: {msg}" for msg, ads in errors.items())
    return {"notams": items, "error": f"Serwer NOTAM: {error}" if errors else None}


def tv_restrictions(volumes, now: datetime) -> list[dict]:
    """Regulacje vIFF na sektorach (traffic volumes) EP: ograniczenia wejść/zajętości z godzinami obowiązywania."""
    out = []
    hhmm = now.strftime("%H%M")
    for tv in volumes if isinstance(volumes, list) else []:
        if not isinstance(tv, dict) or not tv.get("id"):
            continue
        for r in tv.get("restrictions") or []:
            if not isinstance(r, dict):
                continue
            start, end = str(r.get("start") or ""), str(r.get("end") or "")
            active = bool(start and end and (start <= hhmm <= end if start <= end else not end < hhmm < start))
            out.append({"tv": tv["id"], "label": viff_service.tv_label(tv["id"]), "type": r.get("type"),
                        "value": r.get("value"), "start": start, "end": end, "reason": r.get("reason") or "",
                        "active": active})
    out.sort(key=lambda r: (not r["active"], r["tv"], r["start"]))
    return out


async def _flow(airports: list[str], now: datetime) -> dict:
    """Restrykcje ECFMP dla EPWW i regulacje vIFF na sektorach EP (każde źródło z własnym komunikatem błędu)."""
    async def viff_tvs():
        try:
            data = await viff_service._get("/etfms/trafficVolumes",
                                           {"filter": "EP", "active": "false", "activeAndDisabled": "true"}, ttl=300)
            return tv_restrictions(data, now), None
        except Exception as exc:  # noqa: BLE001 - vIFF nie ma dokumentacji błędów, panel pokazuje treść wyjątku
            return [], f"vIFF niedostępny: {exc}"

    measures, (restrictions, viff_error) = await asyncio.gather(
        ecfmp_service.measures(airports, now), viff_tvs())
    return {**measures, "restrictions": restrictions, "viff_error": viff_error}


def monitor_hours(buckets, now: datetime) -> dict:
    """Z całodobowych danych vIFF (/etfms/airports) bierzemy bieżącą i następną godzinę."""
    rows = {str(b.get("hour")): b for b in (buckets if isinstance(buckets, list) else []) if isinstance(b, dict)}
    cur, nxt = rows.get(f"{now.hour:02d}"), rows.get(f"{(now.hour + 1) % 24:02d}")
    # jak w vIFF: 999 albo wartość ujemna = bez limitu
    cap = lambda b: (v if isinstance(v := (b or {}).get("entriesCapacity"), int) and 0 < v < 999 else None)  # noqa: E731
    pick = lambda b: {"entries": (b or {}).get("entriesCount"), "cap": cap(b)} if b else {"entries": None, "cap": None}  # noqa: E731
    return {"hour": f"{now.hour:02d}", "now": pick(cur), "next": pick(nxt)}


def _delay(ctot: str | None, etot: str | None) -> int | None:
    """Opóźnienie ATFM w minutach: CTOT − ETOT (jak kolumna Delay w liście lotów NM)."""
    ctot, etot = viff_service.hhmm(ctot), viff_service.hhmm(etot)   # '1621', '162100' albo liczba → '1621'
    if not (ctot and etot):
        return None
    mins = lambda t: int(t[:2]) * 60 + int(t[2:])  # noqa: E731
    return (mins(ctot) - mins(etot) + 720) % 1440 - 720


async def _monitor(icaos: list[str], now: datetime) -> dict:
    """Airport Monitor vIFF: przepustowość i ruch godzinowy (/etfms/airports), dane A-CDM (/etfms/getCadAirports)
    i loty z regulacją (/etfms/restricted) – trzy zapytania na wszystkie lotniska, bez pytania o każde osobno."""
    async def grab(path, params=None, ttl=None):
        try:
            return await viff_service._get(path, params, ttl=ttl), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{path}: {exc}"

    (load, e1), (cad, e2), (restricted, e3) = await asyncio.gather(
        grab("/etfms/airports", {"filter": "EP", "date": now.date().isoformat()}),
        grab("/etfms/getCadAirports", ttl=3600),
        grab("/etfms/restricted", {"day": now.date().isoformat()}, ttl=60))
    cdm = {str(a.get("icao") or "").upper(): a for a in (cad if isinstance(cad, list) else []) if isinstance(a, dict)}
    flights: dict[str, list[dict]] = {}
    for f in restricted if isinstance(restricted, list) else []:
        if not isinstance(f, dict):
            continue
        dep, arr = str(f.get("departure") or "").upper(), str(f.get("arrival") or "").upper()
        hm = viff_service.hhmm      # godziny zawsze jako 'HHMM' albo None (sortowanie po CTOT, opóźnienie)
        item = {"callsign": f.get("callsign"), "departure": dep, "arrival": arr, "ctot": hm(f.get("ctot")),
                "etot": hm(f.get("etot")), "atot": hm(f.get("atot")), "tto": hm(f.get("tto")),
                "regulation": f.get("mostPenalisingRegulation") or None,
                "delay": _delay(f.get("ctot"), f.get("etot")), "role": None}
        for icao, role in ((dep, "DEP"), (arr, "ARR")):
            if icao in icaos:
                flights.setdefault(icao, []).append({**item, "role": role})
    out = {}
    for icao in icaos:
        info = cdm.get(icao, {})
        regs = sorted(flights.get(icao, []), key=lambda f: (f["ctot"] or "9999", f["callsign"] or ""))
        delays = [f["delay"] for f in regs if f["delay"]]
        out[icao] = {**monitor_hours((load if isinstance(load, dict) else {}).get(icao), now),
                     "rate": info.get("rate"), "taxi_min": info.get("taxiTime"), "cdm": bool(info.get("isCdm")),
                     "config": info.get("config") or info.get("atis_config") or None,
                     "known": bool(info), "regulated": regs,
                     "avg_delay": round(sum(delays) / len(delays)) if delays else None}
    errors = [e for e in (e1, e2, e3) if e]
    return {"airports": out, "error": "vIFF niedostępny: " + "; ".join(errors) if errors else None}


async def overview(db: Session, position: str | None = None, now: datetime | None = None) -> dict:
    """Wszystko do widoku OVERVIEW w jednym zapytaniu; panele pobierane równolegle, każdy ze swoim błędem."""
    now = now or datetime.now(timezone.utc)
    shown, pos = airports_for(db, position)
    names = {a.icao: a.name for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(AERODROMES)))}
    # QNH liczymy ze wszystkich kontrolowanych lotnisk (zasada TL dotyczy całego FIR-u), nawet przy filtrze
    (metars, tafs, wx_errors), feed, notams, flow, monitor = await asyncio.gather(
        _weather(AERODROMES), _feed(), _notams(shown, now), _flow(shown, now), _monitor(shown, now))
    info = feed_info(feed["feed"], AERODROMES)
    parsed = {i: parse_metar(m) for i, m in metars.items() if m}
    qnhs = {i: (p.qnh if p else None) for i, p in parsed.items()}
    tl = tl_service.levels({i: qnhs.get(i) for i in AERODROMES},
                           {i: (info[i]["atis"] or {}).get("lines") for i in AERODROMES})
    aerodromes = []
    for icao in shown:
        p = parsed.get(icao)
        atis = info.get(icao, {}).get("atis")
        aerodromes.append({
            "icao": icao, "name": names.get(icao, icao),
            "metar": metars.get(icao), "parsed": p.to_dict() if p else None, "taf": tafs.get(icao),
            "lvp": evaluate_lvp(p, icao), "tl": tl["aerodromes"].get(icao),
            "atis": {"callsign": atis["callsign"], "letter": atis["letter"], "lines": atis["lines"]} if atis else None,
            "atc": info.get(icao, {}).get("atc", []),
            "traffic": {k: info.get(icao, {}).get(k, 0) for k in ("departures", "arrivals", "prefiles")},
            "monitor": monitor["airports"].get(icao),
        })
    return {"now": now.isoformat(timespec="seconds"), "position": pos, "airports": shown,
            "all_airports": list(AERODROMES), "aerodromes": aerodromes,
            "tl": tl, "wx_error": "; ".join(wx_errors) or None, "network_error": feed["error"],
            "notams": notams["notams"], "notam_error": notams["error"], "flow": flow, "monitor_error": monitor["error"]}


async def _feed() -> dict:
    """Data feed VATSIM; przy awarii puste dane i komunikat (panele pokazują je bez ATIS i bez ruchu)."""
    from ..routers import vatsim as vatsim_api   # ten sam cache i to samo miejsce podmiany w testach i demo
    try:
        return {"feed": await vatsim_api.get_feed(), "error": None}
    except (UpstreamError, ValueError) as exc:
        return {"feed": {}, "error": f"VATSIM: {exc}"}
