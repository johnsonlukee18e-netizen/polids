"""OTHER › FLIGHT PLAN (0.14.2, issue #35): dane okna EXTENDED LABEL (SDD 2014, rozdz. 2.1.2.3, Table 2-13), których nie
ma w samym planie lotu. Wynik extras() trafia do odpowiedzi /api/vatsim/flightplan/{znak} jako "label":

- route_ahead: punkty trasy wpisane w plan (bez punktów dróg lotniczych dopisanych przy rozpisywaniu i bez lotnisk),
  których samolot jeszcze nie minął (rzut pozycji na najbliższy odcinek rozpisanej trasy), najwyżej ROUTE_MAX; tylko
  pilot online w powietrzu (GS ≥ AIRBORNE_KT). None = nie wiadomo (okno pokazuje wtedy pierwsze punkty z planu),
  także gdy żaden punkt wpisany w trasę nie jest w bazie nawigacyjnej; [] = wszystkie znane punkty za samolotem.
  Lot lokalny (ADEP = ADES): lotnisko na końcu trasy liczy się w miejscu lotniska na początku, więc tuż po starcie
  najbliższy jest początek trasy.
- fir_exit: {"point", "level"}: nazwany punkt, przez który trasa ostatni raz opuszcza FIR EPWW (ten sam co etykieta
  tranzytu na MAP, eptraffic.Plan), i poziom wyjścia z LOA (loa.json, przekazanie "out" przez ten punkt, którego
  warunki DEP / ARR z pola traffic spełnia lot; wiersz "DEP X, ARR Y" tylko dla lotu z X do Y), najwyżej RFL.
  Wygrywają najbardziej szczegółowe pasujące wiersze (DEP i ARR przed samym DEP albo ARR). Poziomu nie zgadujemy:
  brak pasującego wiersza LOA, kilka różnych poziomów (np. zależnie od pasa u sąsiada) albo wiersz bez FL
  (koordynacja indywidualna) wśród nich = level None. Lot do lotniska EP**: bez punktu wyjścia.
- proc: {"kind": "STAR"|"SID", "name", "runway", "aerodrome"}: STAR na lotnisku docelowym EP** (lot w powietrzu albo
  z lotniska spoza Polski), a SID na lotnisku odlotu EP** (prefile i samolot na ziemi). Pas w użyciu jak w OVERVIEW
  (ATIS, bez pasa z ATIS pas preferowany z METAR), procedura z pliku .ese jak na paskach AERODROME › TRAFFIC; lot VFR
  (reguły V) jak tam: pas bez procedury. METAR, który nie zdążył w METAR_WAIT_S, kończy się w tle i trafia do cache
  (następne odświeżenie FLIGHT PLAN ma już pas z wiatru).
- next_freq: zawsze None. Sieć nie podaje, kto prowadzi lot ani komu go przekaże (handoff), więc częstotliwość
  następnego sektora byłaby zgadywaniem: pole w oknie zostaje puste.

Każda część osobno: błąd (baza nawigacyjna w trakcie importu, METAR, plik LOA) daje tylko puste pole (None) i krótką
linijkę w logu z nazwą wyjątku (bez nazwy pilota i bez treści błędu)."""

import asyncio
import logging
import math
import re
import threading
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
# _cached_geo działa w wątkach puli (run_in_threadpool): odczyt, usuwanie starych i wpis pod blokadą
_geo_lock = threading.Lock()
# pobieranie METAR lotniska w toku (także to, które nie zdążyło w METAR_WAIT_S i kończy się w tle)
_metar_tasks: dict[str, asyncio.Future] = {}


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
    if len(pts) > 1 and dep and dep == arr and pts[0]["ident"] == pts[-1]["ident"] == dep:
        # lot lokalny: lotnisko na końcu w tym samym miejscu co na początku (lotnisko z bazy lotnisk i punkt AD z pliku
        # sektorowego różnią się o metry); przy remisie min() w route_ahead wybiera początek trasy, nie jej koniec
        pts[-1] = {**pts[-1], "lat": pts[0]["lat"], "lon": pts[0]["lon"]}
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
    with _geo_lock:
        hit = _geo.get(key)
        if hit and time.monotonic() - hit[0] < GEO_TTL_S:
            return hit[1]
    # rozpisanie trasy (zapytania do bazy) poza blokadą: inne wątki w tym czasie czytają i zapisują swoje trasy
    geo = route_geo(RouteResolver(db), dep, route, arr)
    with _geo_lock:
        now = time.monotonic()
        if len(_geo) >= GEO_MAX:
            for k in [k for k, (t, _) in _geo.items() if now - t >= GEO_TTL_S] or list(_geo)[:GEO_MAX // 4]:
                del _geo[k]
        _geo[key] = (now, geo)
    return geo


def route_ahead(geo: dict, lat: float, lon: float) -> list[str] | None:
    """Punkty wpisane w trasę, których samolot w (lat, lon) jeszcze nie minął: najbliższy punkt rozpisanej trasy
    (rzut równoodległościowy), a gdy pozycja jest już za nim (rzut na odcinek do następnego punktu), od następnego.
    Kolejne powtórzenia tego samego punktu raz; najwyżej ROUTE_MAX. None, gdy żaden punkt wpisany w trasę nie jest
    w bazie nawigacyjnej (nie wiadomo, co przed samolotem; [] znaczy tylko "wszystkie znane punkty za nim")."""
    pts = geo["points"]
    if not pts or not geo["filed"]:
        return None
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
    """Poziom wyjścia z FIR (FL, liczba) z przekazań "out" w LOA przez punkt `point`; najwyżej RFL.

    Wiersz pasuje, gdy lot spełnia wszystkie jego warunki z pola traffic: "DEP X" = odlot z X, "ARR Y" = przylot do Y,
    "DEP X, ARR Y" = lot z X do Y (oba naraz). Wiersz bez kodu lotniska ("ARR other LKAA") nie pasuje: nie wiemy,
    których lotnisk dotyczy. Z pasujących wygrywają najbardziej szczegółowe (DEP i ARR przed samym DEP albo ARR).
    Poziomu nie zgadujemy: bez pasującego wiersza, przy różnych poziomach albo gdy któryś z wygrywających wierszy
    nie ma FL (koordynacja indywidualna): None."""
    cop = cop_key(point or "")
    if not cop:
        return None
    data = loa if loa is not None else seed_json(settings.seed_dir / "loa.json")
    best, levels = 0, set()
    for fir in (data.get("firs") or {}).values():
        for t in (fir.get("transfers") or []) if isinstance(fir, dict) else []:
            if not isinstance(t, dict) or t.get("dir") != "out" or cop_key(t.get("cop")) != cop:
                continue
            adep, ades = parse_traffic(t.get("traffic"))
            # pusta lista = bez warunku po tej stronie; wiersz bez żadnego warunku pomijamy
            if not (adep or ades) or (adep and dep not in adep) or (ades and arr not in ades):
                continue
            spec = bool(adep) + bool(ades)
            if spec > best:
                best, levels = spec, set()
            if spec == best:
                levels.add(parse_level(t.get("level"))[0])
    if len(levels) != 1 or None in levels:
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


def _metar_done(icao: str, t: asyncio.Future) -> None:
    if _metar_tasks.get(icao) is t:
        del _metar_tasks[icao]
    if not t.cancelled():
        t.exception()   # błąd pobierania w tle bez "Task exception was never retrieved" (zgłasza go ten, kto czekał)


async def _metar(icao: str) -> str | None:
    """METAR lotniska albo None, gdy nie zdążył w METAR_WAIT_S. Pobieranie nie jest przerywane: kończy się w tle
    i trafia do cache (następne odświeżenie FLIGHT PLAN bierze METAR z cache, jak godziny w member_hours); kilka
    odświeżeń w tym czasie czeka na to samo pobieranie. Błąd pobierania (nie przekroczenie czasu) idzie wyżej."""
    task = _metar_tasks.get(icao)
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = _metar_tasks[icao] = asyncio.ensure_future(get_metars([icao]))
        task.add_done_callback(lambda t, k=icao: _metar_done(k, t))
    done, _ = await asyncio.wait({task}, timeout=METAR_WAIT_S)
    return task.result().get(icao) if done else None


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
        metar = await _metar(icao)
    except Exception as exc:  # noqa: BLE001 - bez METAR pas z ATIS albo z konfiguracji lotniska
        _warn(exc)
        metar = None
    parsed = parse_metar(metar) if metar else None
    use = runway_now(ad, parsed, evaluate_lvp(parsed, icao), stations, now) or {}
    rwy = use.get("arr") if kind == "STAR" else use.get("dep")
    fp = found.get("flight_plan") or {}
    # jak procedures.make_strip: lot VFR bez SID i STAR (pas zostaje)
    vfr = str(fp.get("rules") or "").upper()[:1] == "V"
    hit = None if vfr or not rwy else (match_star if kind == "STAR" else match_sid)(icao, rwy, fp.get("route"), procs)
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
    """Testy: bez tras w pamięci i bez pobierania METAR w toku."""
    with _geo_lock:
        _geo.clear()
    _metar_tasks.clear()
