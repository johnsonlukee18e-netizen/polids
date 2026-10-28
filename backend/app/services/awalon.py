"""AWALON: profil wiatru nad lotniskami IFR (część AD 2 eAIP, eaip.AD2_AERODROMES) od 0 do 10 000 ft AMSL co 1000 ft.

Wiersz 0 ft to wiatr przy ziemi: METAR (z porywem i sektorem zmienności), a bez METAR-u (albo bez grupy wiatru)
prognoza 10 m. Wiersze od 1000 ft: prognoza na poziomach 1000–600 hPa (upperwind.PROFILE_LEVELS) w punkcie lotniska,
liniowo w wysokości po składowych u/v (upperwind.interpolate_wind), od dołu zakotwiczona wiatrem 10 m na wysokości
10 m nad lotniskiem. Poziomy ciśnienia na tej wysokości i niżej (wartości ekstrapolowane pod ziemię) odpadają przed
interpolacją, a wiersze na wysokości lotniska i niżej (EPKT 1008 ft: wiersz 1000 ft) to wiersze ziemi bez danych.

Min/max kierunku i prędkości z godziny poprzedniej, bieżącej i następnej (ta sama odpowiedź obejmuje całą dobę UTC),
dla METAR-u sektor zmienności (poryw osobno, nie w max prędkości). Kopia prognozy z innej doby UTC (serwer nie
odpowiada od północy, cache oddaje starszą odpowiedź) to błąd prognozy, nie wczorajsza 23:00 jako bieżąca godzina. Jedno zapytanie o prognozę i jedno o METAR-y dla wszystkich lotnisk; przy
awarii jednego z nich reszta zostaje, a krótki powód idzie do odpowiedzi (pełny z adresem tylko do logu)."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Aerodrome
from . import upperwind
from .eaip import AD2_AERODROMES
from .http_cache import UpstreamError, describe
from .metar import parse_metar

ALTS_FT = tuple(range(0, 10001, 1000))
FT_M = 0.3048
SFC_M = 10   # wiatr przy ziemi z prognozy: 10 m nad lotniskiem
# ten sam logger co routers/meteo.py: błędy pobrania METEO w jednym miejscu logu
log = logging.getLogger("polids.meteo")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(alt_ft: int, kind: str, status: str, **values) -> dict:
    """Wiersz profilu; kind: sfc (0 ft), gnd (na wysokości lotniska i niżej), air (nad lotniskiem)."""
    return {"alt_ft": alt_ft, "kind": kind, "status": status, "dir": None, "speed": None, "gust": None,
            "variable": False, "min_dir": None, "max_dir": None, "min_speed": None, "max_speed": None, "samples": 0,
            "levels_hpa": [], **values}


def dir_range(dirs: list[int], ref: int) -> tuple[int, int]:
    """Najmniejszy i największy kierunek względem kierunku ref, po kole (350, 360, 10 -> 350..10, nie 10..360)."""
    dev = [(d - ref + 180) % 360 - 180 for d in dirs]
    return (ref + min(dev)) % 360 or 360, (ref + max(dev)) % 360 or 360


def spread(winds: list[dict | None], cur: dict | None) -> dict:
    """Min/max kierunku i prędkości z wiatrów kolejnych godzin; cisza (kierunek 0) bez kierunku. samples = liczba
    godzin z wiatrem."""
    ok = [w for w in winds if w and w.get("speed") is not None]
    if not ok or not cur:
        return {"min_dir": None, "max_dir": None, "min_speed": None, "max_speed": None, "samples": 0}
    dirs = [w["dir"] for w in ok if w.get("dir")]
    ref = cur["dir"] if cur.get("dir") else (dirs[0] if dirs else None)
    lo, hi = dir_range(dirs, ref) if dirs else (None, None)
    speeds = [w["speed"] for w in ok]
    return {"min_dir": lo, "max_dir": hi, "min_speed": min(speeds), "max_speed": max(speeds), "samples": len(ok)}


def usable_levels(levels: list[tuple], sfc: dict | None, elev_ft: float | None) -> list[tuple]:
    """Poziomy ciśnienia nad ziemią (wyżej niż 10 m nad lotniskiem) i wiatr 10 m jako najniższy poziom (hPa None)."""
    base = (elev_ft or 0) * FT_M + SFC_M
    out = [x for x in levels if None not in x[1:] and x[1] > base]
    if sfc and sfc.get("speed") is not None and sfc.get("dir") is not None:
        out.append((None, base, sfc["speed"], sfc["dir"]))
    return out


def metar_wind(raw: str | None) -> dict | None:
    """Wiatr z METAR-u jak w /api/meteo/approach-wind; None bez METAR-u."""
    if not raw:
        return None
    p = parse_metar(raw)
    return {"dir": p.wind_dir, "speed": p.wind_speed, "gust": p.wind_gust, "variable": p.wind_variable,
            "var_from": p.wind_var_from, "var_to": p.wind_var_to, "time": p.time}


def surface_row(mw: dict | None, sfc_win: list[dict | None], cur: dict | None) -> dict:
    """Wiersz 0 ft: METAR z porywem i sektorem zmienności (min/max kierunku), bez wiatru w METAR-ze prognoza 10 m
    (min/max ±1 h). Min/max prędkości bez porywu w obu przypadkach."""
    if mw and mw.get("speed") is not None:
        d, spd, gust = mw["dir"], mw["speed"], mw["gust"]
        if mw.get("var_from") is not None and mw.get("var_to") is not None:
            lo, hi = mw["var_from"] or 360, mw["var_to"] or 360
        else:
            lo = hi = d or None
        # Min/Max Spd to zawsze średni wiatr (jak w wierszach prognozy i w wierszu SFC z prognozy), poryw ma swoją kolumnę
        return _row(0, "sfc", "METAR", dir=d, speed=spd, gust=gust, variable=bool(mw.get("variable")), min_dir=lo,
                    max_dir=hi, min_speed=spd, max_speed=spd, samples=1)
    if cur:
        return _row(0, "sfc", "FCST", dir=cur["dir"], speed=cur["speed"], gust=cur.get("gust"),
                    **spread(sfc_win, cur))
    return _row(0, "sfc", "N/A")


def profile(hours: list[dict] | None, i: int, elev_ft: float | None, mw: dict | None) -> list[dict]:
    """Wiersze ALTS_FT jednego lotniska z godzin doby (upperwind.parse_profiles) dla bieżącej godziny i."""
    js = [j for j in (i - 1, i, i + 1) if 0 <= j < len(hours or [])]
    win = [hours[j] for j in js]
    ci = js.index(i) if i in js else None   # bieżąca godzina w oknie (o 00Z pierwsza)
    cur_sfc = win[ci]["surface"] if ci is not None else None
    # dolny punkt interpolacji: wiatr 10 m bez zaokrąglenia (anchor), bez niego (testy, starsze dane) ten do pokazania
    lvs = [usable_levels(h["levels"], h.get("anchor") or h["surface"], elev_ft) for h in win]
    rows = [surface_row(mw, [h["surface"] for h in win], cur_sfc)]
    for alt in ALTS_FT[1:]:
        if alt <= (elev_ft or 0):
            rows.append(_row(alt, "gnd", "GND"))
            continue
        winds = [upperwind.interpolate_wind(lv, alt * FT_M) for lv in lvs]
        cur = winds[ci] if ci is not None else None
        if not cur:
            rows.append(_row(alt, "air", "N/A"))
            continue
        rows.append(_row(alt, "air", "FCST", dir=cur["dir"], speed=cur["speed"], levels_hpa=cur["levels_hpa"],
                         **spread(winds, cur)))
    return rows


async def wind_profile(db: Session, get_metars, now: datetime | None = None) -> dict:
    """Profile wszystkich lotnisk AD 2 z bazy (kolejność alfabetyczna jak AD2_AERODROMES). get_metars z routera
    (ten sam, który podmieniają testy i demo)."""
    now = now or _now()
    found = {a.icao: a for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(AD2_AERODROMES)))}
    ads = [found[i] for i in AD2_AERODROMES if i in found and found[i].lat is not None and found[i].lon is not None]
    metars, metar_error = {}, None
    try:
        # ta sama lista i kolejność co OVERVIEW (overview.AERODROMES): jeden wpis w cache METAR-ów
        metars = await get_metars(list(AD2_AERODROMES))
    except UpstreamError as exc:
        log.warning("AWALON, METAR: %s", exc)
        metar_error = f"METAR unavailable: {describe(exc)}"
    model, model_error = None, None
    try:
        model = await upperwind.model_profiles([(a.lat, a.lon) for a in ads], now)
    except UpstreamError as exc:
        # w exc krótki powód (upperwind._fetch), pełny komunikat z adresem w exc.__cause__
        log.warning("AWALON, prognoza: %s", f"{exc} ({exc.__cause__})" if exc.__cause__ else exc)
        model_error = f"Wind forecast unavailable: {describe(exc)}"
    first = model[0] if model else None
    if first and upperwind.outdated(first[upperwind.hour_index([h["time"] for h in first], now)]["time"], now):
        # serwer nie odpowiada od poprzedniej doby UTC: kopia z cache to wczorajsze godziny, nie bieżąca prognoza
        log.warning("AWALON, prognoza: kopia z cache z doby %s", first[0]["time"][:10])
        model, model_error = None, f"Wind forecast unavailable: {upperwind.OUTDATED}"
    valid, out = None, []
    for k, a in enumerate(ads):
        hours = model[k] if model else None
        i = upperwind.hour_index([h["time"] for h in hours], now) if hours else 0
        if hours and valid is None:
            valid = hours[i]["time"] + "Z"
        raw = metars.get(a.icao)
        mw = metar_wind(raw)
        out.append({"icao": a.icao, "name": a.name, "lat": a.lat, "lon": a.lon,
                    "elevation_ft": round(a.elevation_ft) if a.elevation_ft is not None else None,
                    "metar": raw, "metar_wind": mw, "model_surface": hours[i]["surface"] if hours else None,
                    "profile": profile(hours, i, a.elevation_ft, mw)})
    return {"alts_ft": list(ALTS_FT), "valid": valid, "fetched": now.strftime("%H:%MZ"),
            "model_error": model_error, "metar_error": metar_error, "aerodromes": out}
