"""OTHER › FLIGHT PLAN (0.14.2, issue #35): dane okna EXTENDED LABEL (SDD 2014, rozdz. 2.1.2.3, Table 2-13), których nie
ma w samym planie lotu. Wynik extras() trafia do odpowiedzi /api/vatsim/flightplan/{znak} jako "label":

- route_ahead: punkty trasy wpisane w plan (bez punktów dróg lotniczych dopisanych przy rozpisywaniu i bez lotnisk),
  których samolot jeszcze nie minął (rzut pozycji na najbliższy odcinek rozpisanej trasy), najwyżej ROUTE_MAX; tylko
  pilot online w powietrzu (GS ≥ AIRBORNE_KT). None = nie wiadomo (okno pokazuje wtedy pierwsze punkty z planu),
  [] = wszystkie punkty za samolotem.
- fir_exit: {"point", "level"}: nazwany punkt, przez który trasa ostatni raz opuszcza FIR EPWW (ten sam co etykieta
  tranzytu na MAP, eptraffic.Plan), i poziom wyjścia z LOA (loa.json, przekazanie "out" przez ten punkt dla lotniska
  odlotu albo docelowego), najwyżej RFL. Poziomu nie zgadujemy: brak pasującego wiersza LOA albo kilka różnych
  poziomów (np. zależnie od pasa u sąsiada) = level None. Lot do lotniska EP**: bez punktu wyjścia.
- proc: {"kind": "STAR"|"SID", "name", "runway", "aerodrome"}: STAR na lotnisku docelowym EP** (lot w powietrzu albo
  z lotniska spoza Polski), a SID na lotnisku odlotu EP** (prefile i samolot na ziemi). Pas w użyciu jak w OVERVIEW
  (ATIS, bez pasa z ATIS pas preferowany z METAR), procedura z pliku .ese jak na paskach AERODROME › TRAFFIC.
- next_freq: zawsze None. Sieć nie podaje, kto prowadzi lot ani komu go przekaże (handoff), więc częstotliwość
  następnego sektora byłaby zgadywaniem: pole w oknie zostaje puste.

Każda część osobno: błąd (baza nawigacyjna w trakcie importu, METAR, plik LOA) daje tylko puste pole (None) i krótką
linijkę w logu z nazwą wyjątku (bez nazwy pilota i bez treści błędu)."""

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool

from ..config import settings
from ..models import Aerodrome
from .coordination import cop_key, parse_level, parse_traffic
from .eptraffic import Plan, epww_outline
from .lvp import evaluate as evaluate_lvp
from .metar import parse_metar
from .positions import known_stations
from .procedures import match_sid, match_star
from .radio import seed_json
from .route import RouteResolver
from .runways import runway_now
from .vatsim import level_ft, on_frequency
from .weather import get_metars

log = logging.getLogger("polids.flightplan")

EP_AD = re.compile(r"^EP[A-Z]{2}$")
AIRBORNE_KT = 50        # GS od tylu węzłów: samolot w powietrzu (punkty przed nim, STAR zamiast SID)
ROUTE_MAX = 12          # punktów trasy przed samolotem w odpowiedzi (okno pokazuje do 7)
GEO_TTL_S = 300         # rozpisana trasa w pamięci (odświeżenie FLIGHT PLAN co 30 s nie pyta bazy za każdym razem)
GEO_MAX = 200
METAR_WAIT_S = 2.0      # METAR do pasa w użyciu: dłużej nie czekamy (pas z ATIS albo bez pasa)

_geo: dict[tuple, tuple[float, dict]] = {}


class _Once:
    """RouteResolver, który tę samą trasę rozpisuje raz (punkty trasy i punkt wyjścia z FIR-u z jednego wyniku)."""

    def __init__(self, resolver):
        self._r, self._memo = resolver, {}

    def resolve(self, text: str) -> dict:
        if text not in self._memo:
            self._memo[text] = self._r.resolve(text)
        return self._memo[text]


def _warn(exc: Exception) -> None:
    log.warning("FLIGHT PLAN extras: %s", type(exc).__name__)


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def airborne(found: dict) -> bool:
    """Pilot online z GS ≥ AIRBORNE_KT (prefile i samolot na ziemi: False)."""
    gs = _num((found.get("position") or {}).get("groundspeed"))
    return found.get("status") == "online" and gs is not None and gs >= AIRBORNE_KT


def route_geo(resolver, dep: str, route: str, arr: str) -> dict:
    """Trasa rozpisana raz: współrzędne i nazwy wszystkich punktów (z lotniskami i punktami dróg lotniczych),
    indeksy punktów wpisanych w trasę (filed) i punkt wyjścia z FIR EPWW (exit, tylko lot do lotniska spoza EP**)."""
    once = _Once(resolver)
    text = " ".join(x for x in (dep, route, arr) if x)
    pts = once.resolve(text)["points"] if text else []
    tokens = {t.split("/")[0] for t in route.split()}
    filed = [i for i, p in enumerate(pts)
             if p["ident"] in tokens and p["ident"] not in (dep, arr) and p.get("kind") != "AD"]
    exit_point = None
    if filed and arr and not EP_AD.match(arr):
        exit_point = Plan.build(dep, route, arr, once, epww_outline()).exit
    return {"points": [(p["lat"], p["lon"]) for p in pts], "idents": [p["ident"] for p in pts], "filed": filed,
            "exit": exit_point}


def _cached_geo(db, dep: str, route: str, arr: str) -> dict:
    key = (dep, route, arr)
    now = time.monotonic()
    hit = _geo.get(key)
    if hit and now - hit[0] < GEO_TTL_S:
        return hit[1]
    geo = route_geo(RouteResolver(db), dep, route, arr)
    if len(_geo) >= GEO_MAX:
        for k in [k for k, (t, _) in _geo.items() if now - t >= GEO_TTL_S] or list(_geo)[:GEO_MAX // 4]:
            del _geo[k]
    _geo[key] = (now, geo)
    return geo


def route_ahead(geo: dict, lat: float, lon: float) -> list[str]:
    """Punkty wpisane w trasę, których samolot w (lat, lon) jeszcze nie minął: najbliższy punkt rozpisanej trasy
    (rzut równoodległościowy), a gdy pozycja jest już za nim (rzut na odcinek do następnego punktu), od następnego.
    Kolejne powtórzenia tego samego punktu raz; najwyżej ROUTE_MAX."""
    pts = geo["points"]
    if not pts:
        return []
    k = math.cos(math.radians(lat))
    d = [(la - lat) ** 2 + ((lo - lon) * k) ** 2 for la, lo in pts]
    m = min(range(len(d)), key=d.__getitem__)
    j = m
    if m + 1 < len(pts):
        (la0, lo0), (la1, lo1) = pts[m], pts[m + 1]
        if (lat - la0) * (la1 - la0) + (lon - lo0) * (lo1 - lo0) * k * k > 0:
            j = m + 1
    out: list[str] = []
    for i in geo["filed"]:
        if i >= j and (not out or out[-1] != geo["idents"][i]):
            out.append(geo["idents"][i])
    return out[:ROUTE_MAX]


def loa_exit_level(point: str | None, dep: str, arr: str, rfl_ft: int | None = None, loa: dict | None = None) -> int | None:
    """Poziom wyjścia z FIR (FL, liczba) z przekazań "out" w LOA przez punkt `point` dla lotniska odlotu (DEP) albo
    docelowego (ARR) z pola traffic; najwyżej RFL. Bez pasującego wiersza albo przy kilku różnych poziomach: None."""
    cop = cop_key(point or "")
    if not cop:
        return None
    data = loa if loa is not None else seed_json(settings.seed_dir / "loa.json")
    levels = set()
    for fir in (data.get("firs") or {}).values():
        for t in (fir.get("transfers") or []) if isinstance(fir, dict) else []:
            if not isinstance(t, dict) or t.get("dir") != "out" or cop_key(t.get("cop")) != cop:
                continue
            adep, ades = parse_traffic(t.get("traffic"))
            if (dep and dep in adep) or (arr and arr in ades):
                lvl, _ = parse_level(t.get("level"))
                if lvl:
                    levels.add(lvl)
    if len(levels) != 1:
        return None
    lvl = levels.pop()
    return min(lvl, rfl_ft // 100) if rfl_ft else lvl


def proc_target(found: dict) -> tuple[str, str] | None:
    """("STAR", lotnisko docelowe) albo ("SID", lotnisko odlotu) albo None (lot poza polskimi lotniskami, odlot z EP**
    za granicę już w powietrzu)."""
    fp = found.get("flight_plan") or {}
    dep, arr = str(fp.get("departure") or "").upper(), str(fp.get("arrival") or "").upper()
    air = airborne(found)
    if EP_AD.match(arr) and (air or not EP_AD.match(dep)):
        return "STAR", arr
    if EP_AD.match(dep) and not air:
        return "SID", dep
    return None


async def _proc(found: dict, feed: dict, db, now: datetime, procs: dict | None) -> dict | None:
    target = proc_target(found)
    if target is None:
        return None
    kind, icao = target
    ad = db.get(Aerodrome, icao)
    if ad is None or not ad.runways:
        return None
    conns = [c for c in (feed.get("controllers") or []) + (feed.get("atis") or [])
             if isinstance(c, dict) and str(c.get("callsign") or "").startswith(icao + "_")]
    stations = on_frequency(conns, known_stations(db))
    try:
        metar = (await asyncio.wait_for(get_metars([icao]), METAR_WAIT_S)).get(icao)
    except Exception as exc:  # noqa: BLE001 - bez METAR pas z ATIS albo z konfiguracji lotniska
        _warn(exc)
        metar = None
    parsed = parse_metar(metar) if metar else None
    use = runway_now(ad, parsed, evaluate_lvp(parsed, icao), stations, now) or {}
    rwy = use.get("arr") if kind == "STAR" else use.get("dep")
    route = (found.get("flight_plan") or {}).get("route")
    hit = (match_star if kind == "STAR" else match_sid)(icao, rwy, route, procs) if rwy else None
    return {"kind": kind, "name": hit["name"] if hit else None, "runway": rwy, "aerodrome": icao}


async def extras(found: dict, feed: dict, db, now: datetime | None = None, procs: dict | None = None) -> dict:
    """Dane okna EXTENDED LABEL dla wyniku find_flight_plan (opis modułu); bez planu lotu same None."""
    out = {"route_ahead": None, "fir_exit": None, "proc": None, "next_freq": None}
    fp = found.get("flight_plan")
    if not fp:
        return out
    dep, arr = str(fp.get("departure") or "").upper(), str(fp.get("arrival") or "").upper()
    route = " ".join(str(fp.get("route") or "").upper().split())
    geo = None
    if route:
        try:
            geo = await run_in_threadpool(_cached_geo, db, dep, route, arr)
        except Exception as exc:  # noqa: BLE001 - np. baza nawigacyjna zablokowana w trakcie importu
            _warn(exc)
    if geo is not None:
        try:
            pos = found.get("position") or {}
            lat, lon = _num(pos.get("lat")), _num(pos.get("lon"))
            if airborne(found) and lat is not None and lon is not None:
                out["route_ahead"] = route_ahead(geo, lat, lon)
        except Exception as exc:  # noqa: BLE001
            _warn(exc)
        try:
            if geo["exit"]:
                out["fir_exit"] = {"point": geo["exit"],
                                   "level": loa_exit_level(geo["exit"], dep, arr, level_ft(fp.get("altitude")))}
        except Exception as exc:  # noqa: BLE001 - np. uszkodzony loa.json
            _warn(exc)
    try:
        out["proc"] = await _proc(found, feed, db, now or datetime.now(timezone.utc), procs)
    except Exception as exc:  # noqa: BLE001
        _warn(exc)
    return out


def reset() -> None:
    """Testy: bez tras w pamięci."""
    _geo.clear()
