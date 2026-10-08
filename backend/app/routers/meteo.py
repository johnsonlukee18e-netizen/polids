import json
import math
import re
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, settings
from ..database import get_db
from ..importers.sct import parse_line_groups, read_text, sections
from ..models import Aerodrome, NavPoint, Sector
from ..services import upperwind
from ..services.http_cache import UpstreamError
from ..services.metar import parse_metar
from ..services.runways import wind_components
from ..services.weather import get_metars, get_tafs
from .nav import sct_line_groups

router = APIRouter(prefix="/api/meteo", tags=["meteo"])


def _ids(ids: str) -> list[str]:
    # idą dalej w URL do metar.vatsim.net / AWC, więc tylko litery i cyfry
    out = list(dict.fromkeys(i.strip().upper() for i in ids.replace(" ", ",").split(",") if i.strip()))
    if not out or len(out) > 50:
        raise HTTPException(400, "Podaj od 1 do 50 kodów ICAO")
    bad = [i for i in out if not re.fullmatch(r"[A-Z0-9]{3,4}", i)]
    if bad:
        raise HTTPException(400, f"Niepoprawny kod ICAO: {bad[0][:10]}")
    return out


@router.get("/metar")
async def metar(ids: str = Query(..., description="Kody ICAO rozdzielone przecinkami")):
    icaos = _ids(ids)
    try:
        raw = await get_metars(icaos)
    except UpstreamError as exc:
        raise HTTPException(502, f"Źródło METAR niedostępne: {exc}") from exc
    return [{"icao": i, "raw": raw.get(i), "parsed": parse_metar(raw[i]).to_dict() if raw.get(i) else None}
            for i in icaos]


@router.get("/taf")
async def taf(ids: str = Query(...)):
    icaos = _ids(ids)
    try:
        raw = await get_tafs(icaos)
    except UpstreamError as exc:
        raise HTTPException(502, f"Źródło TAF niedostępne: {exc}") from exc
    return [{"icao": i, "raw": raw.get(i)} for i in icaos]


# --- mapa QNH regionalnego (jak mapa rejonów QNH z AIP Polska) ---
_Seg = list[list[float]]


def _chains(segs: list[_Seg]) -> list[list[tuple]]:
    """Odcinki [[lat, lon], [lat, lon]] sklejone w łamane (mniej danych niż osobne odcinki)."""
    adj: dict[tuple, list[int]] = {}
    for i, (a, b) in enumerate(segs):
        adj.setdefault(tuple(a), []).append(i)
        adj.setdefault(tuple(b), []).append(i)
    used = [False] * len(segs)

    def grow(line: list[tuple]) -> None:
        while len(adj[line[-1]]) == 2:
            nxt = next((j for j in adj[line[-1]] if not used[j]), None)
            if nxt is None:
                return
            used[nxt] = True
            a, b = map(tuple, segs[nxt])
            line.append(b if a == line[-1] else a)

    out = []
    for i, (a, b) in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        line = [tuple(a), tuple(b)]
        grow(line)
        line.reverse()
        grow(line)
        out.append(line)
    return out


def _faces(segs: list[_Seg]) -> list[list[tuple]]:
    """Obszary ograniczone odcinkami (ściany grafu planarnego), np. wnętrze granicy "EPGD TMA OUT".

    Obchodzimy każdą krawędź skierowaną, skręcając w każdym węźle w pierwszą krawędź zgodnie z ruchem
    wskazówek zegara; ściany o dodatnim polu (obchodzone przeciwnie do ruchu wskazówek) to obszary zamknięte."""
    nbr: dict[tuple, set] = {}
    for a, b in segs:
        a, b = tuple(a), tuple(b)
        if a != b:
            nbr.setdefault(a, set()).add(b)
            nbr.setdefault(b, set()).add(a)
    order = {p: sorted(ns, key=lambda q, p=p: math.atan2(q[0] - p[0], (q[1] - p[1]) * math.cos(math.radians(p[0]))))
             for p, ns in nbr.items()}
    seen: set = set()
    out = []
    for u in order:
        for v in order[u]:
            if (u, v) in seen:
                continue
            ring, a, b = [u], u, v
            while (a, b) not in seen and len(ring) < 10000:
                seen.add((a, b))
                ring.append(b)
                ns = order[b]
                a, b = b, ns[ns.index(a) - 1]
            k = math.cos(math.radians(ring[0][0]))
            area = sum((p[1] * q[0] - q[1] * p[0]) * k for p, q in zip(ring, ring[1:])) / 2
            if area > 1e-5:
                out.append(ring)
    return out


def _lonlat(line) -> list[list[float]]:
    return [[round(p[1], 4), round(p[0], 4)] for p in line]


@lru_cache(maxsize=1)
def _coast() -> list[_Seg]:
    """Linia brzegowa z sekcji [GEO] pliku .sct (grupa "... Coastlines"), rysowana szarym kolorem jak na mapie AIP."""
    for f in sorted((DATA_DIR / "import").glob("*.sct")):
        for name, segs in parse_line_groups(sections(read_text(f)).get("[GEO]", [])).items():
            if "coast" in name.lower():
                return segs
    return []


@lru_cache(maxsize=1)
def _fir_epww() -> dict | None:
    fc = json.loads((settings.seed_dir / "vatspy_firs.geojson").read_text("utf-8"))
    return next((f["geometry"] for f in fc["features"] if f["properties"].get("id") == "EPWW"), None)


def _tma_geometry(t: dict, low: list[Sector]) -> dict:
    """Obszar TMA jak na mapie AIP: "area" = obszar "BELOW ... QNH FROM" odrysowany z mapy AIP ("aip" w pliku rejonów),
    "layers" = dolne warstwy (poniżej FL95) z pliku .ese, sektory o nazwach zaczynających się od "ese" (cienkie linie
    podziału w środku obszaru). Bez "aip" obszarem są warstwy .ese, bez nich obszar zamknięty liniami grup "sct"
    z pliku .sct, a gdy linie się nie zamykają, same linie ("outline")."""
    layers: list = []
    for s in low:
        if t.get("ese") and s.name.startswith(tuple(t["ese"])):
            g = json.loads(s.geometry)
            for poly in [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]:
                layers.append([[[round(x, 4), round(y, 4)] for x, y in ring] for ring in poly])
    segs = [s for n in t.get("sct", []) for s in sct_line_groups().get(n, [])]
    if not layers:
        layers = [[_lonlat(r)] for r in _faces(segs)]
    multi = lambda c: {"type": "MultiPolygon", "coordinates": c} if c else None  # noqa: E731
    outline = {"type": "MultiLineString", "coordinates": [_lonlat(c) for c in _chains(segs)]} if segs and not layers else None
    if t.get("aip"):
        return {"area": t["aip"], "layers": multi(layers), "outline": outline}
    return {"area": multi(layers), "layers": None, "outline": outline}


@router.get("/qnh-regions")
async def qnh_regions(db: Session = Depends(get_db)):
    """Rejony QNH i TMA/MTMA (data/seed/qnh_regions.json).

    QNH rejonu = najniższe QNH z lotnisk rejonu ("airports"; w pasach awaryjnych 15–17 wszystkie lotniska pasa),
    QNH TMA = QNH z METAR-u lotniska "icao" (pod TMA obowiązuje QNH tego lotniska). Do mapy: granica FIR EPWW,
    linia brzegowa, obszary TMA z mapy AIP z warstwami z plików sektorowych, wszystkie lotniska EP i układ napisów
    z pliku rejonów: ramki SEKTOR n ("label" rejonu), ramki TMA ("box", "short"), opisy BELOW ("cap", "join")
    i szare oznaczenia TMA/CTR z mapy AIP ("chart_labels")."""
    cfg = json.loads((settings.seed_dir / "qnh_regions.json").read_text("utf-8"))
    tmas = cfg.get("tmas", [])
    icaos = sorted({a for r in cfg["regions"] for a in r["airports"]} | {t["icao"] for t in tmas})
    error = None
    try:
        raw = await get_metars(icaos)
    except UpstreamError as exc:
        raw, error = {}, f"Źródło METAR niedostępne: {exc}"
    qnh = {i: parse_metar(m).qnh for i, m in raw.items() if m}
    ads = db.scalars(select(Aerodrome).where(Aerodrome.icao.like("EP%"))).all()
    pos = {a.icao: (a.lat, a.lon) for a in ads}
    for p in db.scalars(select(NavPoint).where(NavPoint.kind == "AD", NavPoint.ident.in_(icaos))):
        pos.setdefault(p.ident, (p.lat, p.lon))
    for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(icaos))):
        pos.setdefault(a.icao, (a.lat, a.lon))
    at = lambda i: dict(zip(("lat", "lon"), pos.get(i, (None, None))))  # noqa: E731
    regions = []
    for r in cfg["regions"]:
        vals = [qnh[a] for a in r["airports"] if qnh.get(a)]
        regions.append({**r, "qnh": min(vals) if vals else None, "max": max(vals) if vals else None,
                        "stations": [{"icao": a, "qnh": qnh.get(a), **at(a)} for a in r["airports"]]})
    low = db.scalars(select(Sector).where(Sector.fir == "EPWW", Sector.lower_ft < 9500).order_by(Sector.name)).all()
    out_tmas = [{**{k: v for k, v in t.items() if k not in ("sct", "ese", "aip")}, "qnh": qnh.get(t["icao"]), **at(t["icao"]),
                 **_tma_geometry(t, low)} for t in tmas]
    coast = _coast()
    # granica FIR z pliku rejonów (z pliku sektorowego, jak na mapie AIP), bez niej z VATSpy
    return {"note": cfg.get("note"), "regions": regions, "tmas": out_tmas, "error": error, "fir": cfg.get("fir") or _fir_epww(),
            "chart_labels": cfg.get("chart_labels", []),
            "coast": {"type": "MultiLineString", "coordinates": [_lonlat(c) for c in _chains(coast)]} if coast else None,
            "aerodromes": [{"icao": a.icao, "lat": a.lat, "lon": a.lon, "metar": a.icao in icaos}
                           for a in sorted(ads, key=lambda a: a.icao)]}


# --- wiatr przy ziemi i na 3000 ft na podejściu (METEO › WIND, AERODROME › PRZEGLĄD)

def _components(wind: dict | None, heading: float) -> dict:
    """Składowe wiatru względem pasa: hw (czołowy, < 0 w plecy), xw (boczny, > 0 z prawej)."""
    if not wind or wind.get("dir") is None or wind.get("speed") is None:
        return {"hw": None, "xw": None}
    hw, xw = wind_components(wind["dir"], wind["speed"], heading)
    return {"hw": hw, "xw": xw}


@router.get("/approach-points")
def approach_points(db: Session = Depends(get_db)):
    """Punkty podejścia pasów lotnisk z bazy: FAF/IF z procedur .ese albo punkt na przedłużeniu osi, w którym ścieżka
    3° osiąga 3000 ft AMSL (bez wiatru, do list wyboru). Bez pasów trawiastych, awaryjnych, krótkich i bez współrzędnych
    progu, chyba że mają procedurę podejścia (upperwind.approach_runways)."""
    return {"alt_ft": upperwind.ALT_FT, "aerodromes": upperwind.approach_points(db)}


@router.get("/approach-wind/{icao}")
async def approach_wind(icao: str, db: Session = Depends(get_db)):
    """Wiatr lotniska: przy ziemi (METAR i model 10 m w punkcie lotniska) oraz na 3000 ft AMSL w punkcie podejścia
    każdego pasa (Open-Meteo, bieżąca godzina), ze składowymi czołową/w plecy i boczną."""
    found = upperwind.approach_points(db, icao)
    if not found:
        ad = db.get(Aerodrome, icao.upper())
        raise HTTPException(404, f"Brak danych o pasach lotniska {ad.icao}" if ad else f"Nie znam lotniska {icao}")
    ad = found[0]
    metar, metar_error = None, None
    try:
        metar = (await get_metars([ad["icao"]])).get(ad["icao"])
    except UpstreamError as exc:
        metar_error = f"METAR niedostępny: {exc}"
    p = parse_metar(metar) if metar else None
    metar_wind = {"dir": p.wind_dir, "speed": p.wind_speed, "gust": p.wind_gust, "variable": p.wind_variable,
                  "var_from": p.wind_var_from, "var_to": p.wind_var_to, "time": p.time} if p else None
    model, model_error = None, None
    try:
        model = await upperwind.model_winds([(ad["lat"], ad["lon"])] + [(r["lat"], r["lon"]) for r in ad["runways"]])
    except UpstreamError as exc:
        model_error = f"Prognoza Open-Meteo niedostępna: {exc}"
    surface_model = model[0]["surface"] if model else None
    runways = []
    for i, r in enumerate(ad["runways"]):
        w = model[i + 1]["w3000"] if model else None
        runways.append({**r, "w3000": w, "c3000": _components(w, r["heading"]),
                        "c_metar": _components(metar_wind, r["heading"]),
                        "c_model": _components(surface_model, r["heading"])})
    return {"icao": ad["icao"], "name": ad["name"], "lat": ad["lat"], "lon": ad["lon"],
            "elevation_ft": ad["elevation_ft"], "alt_ft": upperwind.ALT_FT,
            "source": "Open-Meteo", "source_url": "https://open-meteo.com", "model": "best_match",
            "valid": model[0]["valid"] if model else None,
            "fetched": datetime.now(timezone.utc).strftime("%H:%MZ"),
            "metar": metar, "metar_wind": metar_wind, "model_surface": surface_model, "runways": runways,
            "metar_error": metar_error, "model_error": model_error}
