"""Wiatr na podejściu: punkt FAF/IF każdego pasa i wiatr z modelu (Open-Meteo) przy ziemi i na 3000 ft AMSL.

Punkt podejścia: ostatni punkt STAR z przejściem do podejścia (np. "AGAVA6NxILS·Z: ... GOSIT WA409" -> WA409) z pliku
.ese, jeśli leży 2,5–15 NM od progu i najwyżej 15° od kursu podejścia końcowego. W przeciwnym razie punkt na przedłużeniu
osi pasa, w którym ścieżka 3° osiąga 3000 ft AMSL (wysokość progu = wysokość lotniska).

Pasy: tylko kierunki z procedurą podejścia albo z twardą nawierzchnią, współrzędnymi progu i długością od 1200 m
(bez trawiastych i pasów awaryjnych, np. EPRZ 08L/26R, 09ES/27ES); lądowisko bez takiego pasa ma wszystkie kierunki.

Wiatr: prognoza Open-Meteo (bez klucza) na bieżącą godzinę: 10 m oraz poziomy ciśnienia 1000–850 hPa z wysokością
geopotencjalną, interpolowane (składowe u/v) do 914 m AMSL. Wszystkie punkty lotniska w jednym zapytaniu."""

import json
import math
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Aerodrome, NavPoint
from .http_cache import UpstreamError, fetch_text
from .procedures import procedures
from .runways import equipment_for, runway_heading

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 600
ALT_FT = 3000
ALT_M = ALT_FT * 0.3048
LEVELS = (1000, 975, 950, 925, 900, 850)
GLIDE_DEG = 3.0
FT_PER_NM = 6076.12 * math.tan(math.radians(GLIDE_DEG))  # ok. 318 ft/NM na ścieżce 3°
# FAF bywa tuż przed 3 NM (EPZG RWY 06: ZG463 2,99 NM), stąd dolna granica 2,5 NM
MIN_NM, MAX_NM, MAX_OFF_DEG = 2.5, 15.0, 15.0
MIN_RWY_M = 1200
# nawierzchnia miękka albo pas awaryjny ("GRASS", "Grass", "GRS", "GRE", "G", "grassy", "GRS Emergency Strip")
SOFT_SURFACE = re.compile(r"gras|grs|\bgre\b|grv|gravel|turf|emergency|^g$", re.I)
EARTH_NM = 3440.065
METHOD_LABEL = {"procedure": "FAF z procedury", "centreline": "na przedłużeniu osi, 3°"}


# --- geometria na kuli

def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def destination(lat: float, lon: float, brg: float, nm: float) -> tuple[float, float]:
    p1, l1, t, d = math.radians(lat), math.radians(lon), math.radians(brg), nm / EARTH_NM
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(t))
    l2 = l1 + math.atan2(math.sin(t) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def glide_distance_nm(elev_ft: float | None, alt_ft: float = ALT_FT) -> float:
    """Odległość od progu, w której ścieżka 3° osiąga alt_ft AMSL (co najmniej MIN_NM)."""
    return max(MIN_NM, (alt_ft - (elev_ft or 0)) / FT_PER_NM)


# --- punkty podejścia

def star_end_fixes(icao: str, runway: str, procs: dict | None = None) -> dict[str, dict]:
    """Ostatnie punkty STAR z przejściem do podejścia: {punkt: {"stars": [...], "approaches": [...]}}."""
    out: dict[str, dict] = {}
    for p in (procs if procs is not None else procedures()).get(icao.upper(), {}).get("star", {}).get(runway, []):
        if not p.get("approaches") or not p.get("fixes"):
            continue
        hit = out.setdefault(p["fixes"][-1], {"stars": [], "approaches": []})
        hit["stars"].append(p["name"])
        hit["approaches"] += [a for a in p["approaches"] if a not in hit["approaches"]]
    return out


def approach_point(icao: str, elev_ft: float | None, runway: dict, fix_pos: dict[str, list[tuple]],
                   procs: dict | None = None) -> dict:
    """Punkt podejścia jednego kierunku pasa. `runway`: designator, heading, lat, lon (próg).
    `fix_pos`: {nazwa punktu: [(lat, lon), ...]} (nazwy bywają powtórzone na świecie, bierzemy najbliższy)."""
    des, hdg = runway["designator"], runway["heading"]
    thr_lat, thr_lon = runway["lat"], runway["lon"]
    glide = glide_distance_nm(elev_ft)
    cands, rejected = [], []
    for fix, info in star_end_fixes(icao, des, procs).items():
        pos = [(distance_nm(thr_lat, thr_lon, la, lo), la, lo) for la, lo in fix_pos.get(fix, [])]
        if not pos:
            rejected.append(f"{fix}: brak współrzędnych")
            continue
        dist, la, lo = min(pos)
        off = angle_diff(bearing(la, lo, thr_lat, thr_lon), hdg)
        if dist < MIN_NM:
            rejected.append(f"{fix}: {dist:.2f} NM od progu (< {MIN_NM:g} NM)")
        elif dist > MAX_NM:
            rejected.append(f"{fix}: {dist:.1f} NM od progu (> {MAX_NM:g} NM)")
        elif off > MAX_OFF_DEG:
            rejected.append(f"{fix}: {off:.0f}° od kursu podejścia")
        else:
            cands.append((-len(info["stars"]), abs(dist - glide), fix, la, lo, dist, info))
    base = {"designator": des, "heading": hdg, "threshold": [round(thr_lat, 5), round(thr_lon, 5)],
            "rejected": rejected}
    if cands:
        _, _, fix, la, lo, dist, info = min(cands)
        return {**base, "method": "procedure", "method_label": METHOD_LABEL["procedure"], "fix": fix,
                "lat": round(la, 5), "lon": round(lo, 5), "dist_nm": round(dist, 1),
                "path_ft": round((elev_ft or 0) + dist * FT_PER_NM, -1),
                "stars": sorted(info["stars"]), "approaches": info["approaches"]}
    la, lo = destination(thr_lat, thr_lon, (hdg + 180) % 360, glide)
    return {**base, "method": "centreline", "method_label": METHOD_LABEL["centreline"], "fix": None,
            "lat": round(la, 5), "lon": round(lo, 5), "dist_nm": round(glide, 1),
            "path_ft": round((elev_ft or 0) + glide * FT_PER_NM, -1), "stars": [], "approaches": []}


def soft_runway(surface: str | None, designator: str) -> bool:
    """Pas trawiasty, żwirowy albo awaryjny (np. EPRZ 09ES "GRS Emergency Strip")."""
    return designator.upper().endswith("ES") or bool(SOFT_SURFACE.search((surface or "").strip()))


def approach_runways(runways: list, has_procedure) -> list:
    """Kierunki pasów do wiatru na podejściu: z procedurą podejścia (has_procedure(designator)) albo z twardą
    nawierzchnią, współrzędnymi progu i długością od MIN_RWY_M. Bez takiego pasa (lądowisko) wszystkie kierunki,
    z równoległych (08L/08R) tylko lepszy: ze współrzędnymi progu, twardy, dłuższy (inaczej dwa razy ten sam punkt)."""
    keep = [r for r in runways if has_procedure(r.designator) or (
        r.lat is not None and r.lon is not None and not soft_runway(r.surface, r.designator)
        and (r.length_m or 0) >= MIN_RWY_M)]
    if keep:
        return sorted(keep, key=lambda r: r.designator)

    def rank(r):
        return r.lat is not None, not soft_runway(r.surface, r.designator), r.length_m or 0

    seen, out = set(), []
    for r in sorted(runways, key=rank, reverse=True):
        key = re.match(r"\d*", r.designator).group()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return sorted(out, key=lambda r: r.designator)


def approach_points(db: Session, icao: str | None = None) -> list[dict]:
    """Punkty podejścia pasów lotnisk z bazy (albo jednego lotniska); pasy wg approach_runways()."""
    stmt = select(Aerodrome).options(selectinload(Aerodrome.runways)).order_by(Aerodrome.icao)
    if icao:
        stmt = stmt.where(Aerodrome.icao == icao.upper())
    ads = [a for a in db.scalars(stmt) if a.runways]
    procs = procedures()
    names = {f for a in ads for r in a.runways for f in star_end_fixes(a.icao, r.designator, procs)}
    fix_pos: dict[str, list[tuple]] = {}
    if names:
        for p in db.scalars(select(NavPoint).where(NavPoint.ident.in_(names), NavPoint.kind != "AD")):
            fix_pos.setdefault(p.ident, []).append((p.lat, p.lon))
    out = []
    for a in ads:
        rwys = []
        eq = equipment_for(a.icao)

        def has_proc(des: str, ad: str = a.icao, eq: dict = eq) -> bool:
            return bool(eq.get(des) or star_end_fixes(ad, des, procs))

        for r in approach_runways(a.runways, has_proc):
            thr = {"designator": r.designator, "heading": runway_heading(r.designator, r.heading_true),
                   "lat": r.lat if r.lat is not None else a.lat, "lon": r.lon if r.lon is not None else a.lon}
            rwys.append(approach_point(a.icao, a.elevation_ft, thr, fix_pos, procs))
        out.append({"icao": a.icao, "name": a.name, "lat": a.lat, "lon": a.lon, "elevation_ft": a.elevation_ft,
                    "runways": rwys})
    return out


# --- wiatr z modelu

def _uv(direction: float, speed: float) -> tuple[float, float]:
    """Składowe wiatru (u na wschód, v na północ); kierunek = skąd wieje."""
    r = math.radians(direction)
    return -speed * math.sin(r), -speed * math.cos(r)


def _from_uv(u: float, v: float) -> tuple[int, int]:
    speed = math.hypot(u, v)
    direction = math.degrees(math.atan2(-u, -v)) % 360
    return (round(direction) % 360 or 360) if speed >= 0.5 else 0, round(speed)


def interpolate_wind(levels: list[tuple], target_m: float = ALT_M) -> dict | None:
    """Wiatr na wysokości target_m AMSL z poziomów ciśnienia [(hPa, wysokość m, prędkość kt, kierunek °)].
    Liniowo w wysokości po składowych u/v; poza zakresem najbliższy poziom."""
    lv = sorted((x for x in levels if None not in x), key=lambda x: x[1])
    if not lv:
        return None
    lo = max((x for x in lv if x[1] <= target_m), default=lv[0], key=lambda x: x[1])
    hi = min((x for x in lv if x[1] >= target_m), default=lv[-1], key=lambda x: x[1])
    u1, v1 = _uv(lo[3], lo[2])
    u2, v2 = _uv(hi[3], hi[2])
    k = 0.0 if hi[1] == lo[1] else (target_m - lo[1]) / (hi[1] - lo[1])
    k = min(1.0, max(0.0, k))
    d, s = _from_uv(u1 + (u2 - u1) * k, v1 + (v2 - v1) * k)
    return {"dir": d, "speed": s, "levels_hpa": sorted({lo[0], hi[0]}, reverse=True)}


def hourly_variables() -> list[str]:
    return ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"] + [
        f"{v}_{p}hPa" for p in LEVELS for v in ("wind_speed", "wind_direction", "geopotential_height")]


def parse_forecast(text: str, now: datetime | None = None) -> list[dict]:
    """Odpowiedź Open-Meteo (obiekt dla jednego punktu, lista dla kilku) -> wiatr 10 m i na 3000 ft dla bieżącej
    godziny UTC w każdym punkcie, w kolejności zapytania."""
    data = json.loads(text)
    if isinstance(data, dict) and data.get("error"):
        raise UpstreamError(f"Open-Meteo: {data.get('reason') or 'błąd'}")
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:00")
    out = []
    for item in data if isinstance(data, list) else [data]:
        hr = item.get("hourly") or {}
        times = hr.get("time") or []
        if not times:
            out.append({"valid": None, "surface": None, "w3000": None})
            continue
        i = max((j for j, t in enumerate(times) if t <= stamp), default=0)
        at = lambda k: (hr.get(k) or [None] * len(times))[i]  # noqa: E731
        sfc = None
        if at("wind_speed_10m") is not None and at("wind_direction_10m") is not None:
            d, s = _from_uv(*_uv(at("wind_direction_10m"), at("wind_speed_10m")))
            gust = at("wind_gusts_10m")
            sfc = {"dir": d, "speed": s, "gust": round(gust) if gust is not None else None}
        levels = [(p, at(f"geopotential_height_{p}hPa"), at(f"wind_speed_{p}hPa"), at(f"wind_direction_{p}hPa"))
                  for p in LEVELS]
        out.append({"valid": times[i] + "Z", "surface": sfc, "w3000": interpolate_wind(levels)})
    return out


def upstream_reason(exc: UpstreamError) -> str:
    """Krótki powód błędu Open-Meteo do UI: bez adresu z długą listą parametrów; przy HTTP 4xx/5xx "reason" z JSON."""
    resp = getattr(exc.__cause__, "response", None)
    if resp is not None:
        try:
            body = resp.json()
        except ValueError:
            body = None
        reason = body.get("reason") if isinstance(body, dict) else None
        return f"HTTP {resp.status_code}" + (f": {reason}" if reason else f" {resp.reason_phrase}".rstrip())
    msg = str(exc)
    return msg[len(OPEN_METEO_URL) + 2:] if msg.startswith(OPEN_METEO_URL + ": ") else msg


async def model_winds(points: list[tuple[float, float]]) -> list[dict]:
    """Wiatr z modelu dla punktów [(lat, lon)] jednym zapytaniem (cache 10 min)."""
    if not points:
        return []
    params = {"latitude": ",".join(f"{la:.4f}" for la, _ in points),
              "longitude": ",".join(f"{lo:.4f}" for _, lo in points),
              "hourly": ",".join(hourly_variables()), "wind_speed_unit": "kn", "timezone": "GMT",
              "forecast_days": "1"}
    try:
        text = await fetch_text(OPEN_METEO_URL, CACHE_SECONDS, params)
    except UpstreamError as exc:
        raise UpstreamError(upstream_reason(exc)) from exc
    try:
        res = parse_forecast(text)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise UpstreamError(f"Open-Meteo: nieczytelna odpowiedź ({exc})") from exc
    if len(res) != len(points):
        raise UpstreamError(f"Open-Meteo: {len(res)} punktów w odpowiedzi zamiast {len(points)}")
    return res
