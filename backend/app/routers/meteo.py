import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Aerodrome
from ..services import gamet as gamet_svc
from ..services import qnh as qnh_svc
from ..services import sun as sun_svc
from ..services import upperwind
from ..services.aerolist import airport_entry
from ..services.http_cache import UpstreamError
from ..services.metar import parse_metar
from ..services.runways import wind_components
from ..services.weather import get_metars, get_tafs

router = APIRouter(prefix="/api/meteo", tags=["meteo"])


def _ids(ids: str) -> list[str]:
    # idą dalej w URL do metar.vatsim.net / AWC, więc tylko litery i cyfry
    out = list(dict.fromkeys(i.strip().upper() for i in ids.replace(" ", ",").split(",") if i.strip()))
    if not out or len(out) > 50:
        raise HTTPException(400, "Enter 1 to 50 ICAO codes")
    bad = [i for i in out if not re.fullmatch(r"[A-Z0-9]{3,4}", i)]
    if bad:
        raise HTTPException(400, f"Invalid ICAO code: {bad[0][:10]}")
    return out


@router.get("/metar")
async def metar(ids: str = Query(..., description="Comma-separated ICAO codes")):
    icaos = _ids(ids)
    try:
        raw = await get_metars(icaos)
    except UpstreamError as exc:
        raise HTTPException(502, f"METAR source unavailable: {exc}") from exc
    return [{"icao": i, "raw": raw.get(i), "parsed": parse_metar(raw[i]).to_dict() if raw.get(i) else None}
            for i in icaos]


@router.get("/taf")
async def taf(ids: str = Query(...)):
    icaos = _ids(ids)
    try:
        raw = await get_tafs(icaos)
    except UpstreamError as exc:
        raise HTTPException(502, f"TAF source unavailable: {exc}") from exc
    return [{"icao": i, "raw": raw.get(i)} for i in icaos]


# --- mapa QNH regionalnego (jak mapa rejonów QNH z AIP Polska): services/qnh.py

@router.get("/qnh-regions")
async def qnh_regions(db: Session = Depends(get_db)):
    """Rejony QNH i TMA/MTMA z QNH z METAR-ów oraz geometria i układ napisów mapy (services/qnh.py)."""
    return await qnh_svc.regions(db, get_metars)


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
        raise HTTPException(404, f"No runway data for aerodrome {ad.icao}" if ad else f"Unknown aerodrome {icao}")
    ad = found[0]
    metar, metar_error = None, None
    try:
        metar = (await get_metars([ad["icao"]])).get(ad["icao"])
    except UpstreamError as exc:
        metar_error = f"METAR unavailable: {exc}"
    p = parse_metar(metar) if metar else None
    metar_wind = {"dir": p.wind_dir, "speed": p.wind_speed, "gust": p.wind_gust, "variable": p.wind_variable,
                  "var_from": p.wind_var_from, "var_to": p.wind_var_to, "time": p.time} if p else None
    model, model_error = None, None
    try:
        model = await upperwind.model_winds([(ad["lat"], ad["lon"])] + [(r["lat"], r["lon"]) for r in ad["runways"]])
    except UpstreamError as exc:
        model_error = f"Open-Meteo forecast unavailable: {exc}"
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


# --- SUN: słońce nad lotniskiem albo punktem mapy (METEO › SUN)

@router.get("/sun")
def sun(icao: str | None = Query(None, description="Aerodrome ICAO code"),
        lat: float | None = Query(None, ge=-90, le=90), lon: float | None = Query(None, ge=-180, le=180),
        db: Session = Depends(get_db)):
    """Wschód i zachód słońca, zmierzch cywilny (BMCT/EECT) dziś i jutro (UTC) oraz słońce teraz: dla lotniska
    (listy FIR-ów, navdata, airports.csv) albo punktu (lat, lon). Lotniska EP mają też czas polski (CET/CEST)."""
    if icao:
        code = icao.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3,4}", code):
            raise HTTPException(400, f"Invalid ICAO code: {code[:10]}")
        ad = airport_entry(db, code)
        if not ad or ad.get("lat") is None or ad.get("lon") is None:
            raise HTTPException(404, f"Unknown aerodrome {code}")
        place = {"icao": ad["icao"], "name": ad["name"], "lat": ad["lat"], "lon": ad["lon"]}
    elif lat is not None and lon is not None:
        place = {"icao": None, "name": None, "lat": lat, "lon": lon}
    else:
        raise HTTPException(400, "Enter an aerodrome ICAO code or coordinates (lat, lon)")
    polish = bool(place["icao"] and place["icao"].startswith("EP"))
    return {**place, "polish": polish, **sun_svc.report(place["lat"], place["lon"], polish=polish)}


# --- GAMET: prognoza obszarowa IMGW dla rejonów A1–A5 FIR EPWW (METEO › GAMET)

@router.get("/gamet")
async def gamet():
    """GAMET z serwisu lotniczego IMGW (tekst rejonów A1–A5, ważność, pułap BLW FLnnn). Bez wyjątku przy awarii
    źródła: "error" z opisem, a interfejs pokazuje odnośnik do awiacja.imgw.pl."""
    return await gamet_svc.get_gamet()
