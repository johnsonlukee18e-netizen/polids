import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Aerodrome, AtcPosition, NavPoint, Sector
from ..services.http_cache import UpstreamError
from ..services.neighbours import covered_firs, nb_owners, nb_sectors, owners_of
from ..services.positions import all_positions
from ..services.radio import Station, position_range, sector_group, sector_kind
from ..services.vatsim import bookings_by_callsign, controller_info, fir_boundaries, match_positions, online_firs
# data feed i rezerwacje przez moduł /api/vatsim: jeden cache i jedno miejsce podmiany (testy, serwer demo)
from . import vatsim as vatsim_api

router = APIRouter(prefix="/api/radio", tags=["radio"])


def _coords(db: Session, icaos: set[str]) -> dict[str, tuple[float, float]]:
    """Współrzędne lotnisk: najpierw baza lotnisk, potem punkty AD z navdata (lotniska zagraniczne)."""
    out = {a.icao: (a.lat, a.lon) for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(icaos)))}
    for p in db.scalars(select(NavPoint).where(NavPoint.kind == "AD", NavPoint.ident.in_(icaos - set(out)))):
        out.setdefault(p.ident, (p.lat, p.lon))
    return out


@router.get("/positions")
def positions(db: Session = Depends(get_db)):
    """Stanowiska do RADIO: plik .ese + wszystkie stanowiska sąsiednich FIR-ów z vacs-data (bez FMP/TMU).

    `in_ese=false`: stanowisko tylko z vacs-data (bez nazwy, pokazujemy `fir_name`). `range`: zasięg na mapie
    (granica VATSpy, okrąg wokół lotniska albo punkt lotniska)."""
    merged = all_positions(db)
    coords = _coords(db, {p["callsign"].split("_")[0] for p in merged})
    firs = fir_boundaries()
    for p in merged:
        lat, lon = coords.get(p["callsign"].split("_")[0], (None, None))
        p["range"] = position_range(p["callsign"], firs, lat, lon, p.get("prefix"))
    return merged


async def _feed() -> dict:
    try:
        return await vatsim_api.get_feed()
    except (UpstreamError, ValueError) as exc:
        raise HTTPException(502, f"VATSIM data feed niedostępny: {exc}") from exc


@router.get("/online")
async def online(db: Session = Depends(get_db)):
    """Zalogowani kontrolerzy dopasowani do stanowisk RADIO (plik .ese i vacs-data): najpierw dokładny znak,
    potem jak w EuroScope (prefiks, typ i częstotliwość). `controllers`: wszyscy zalogowani z EP** i z prefiksów
    znanych stanowisk (także ci, których nie udało się dopasować)."""
    data = await _feed()
    ctrls = data.get("controllers", []) + data.get("atis", [])
    merged = all_positions(db)
    stations = [Station(p["callsign"], p["prefix"], p["frequency"] or "") for p in merged]
    prefixes = {p["callsign"].split("_")[0] for p in merged}
    near = [c for c in ctrls if (cs := c.get("callsign", "")).split("_")[0] in prefixes or cs.startswith("EP")]
    return {"positions": match_positions(ctrls, stations, nb_owners(db)), "firs": online_firs(ctrls),
            "controllers": [controller_info(c) for c in near if not c.get("callsign", "").endswith("_OBS")],
            "updated": data.get("general", {}).get("update_timestamp")}


@router.get("/bookings")
async def bookings(db: Session = Depends(get_db)):
    """Rezerwacje (atc-bookings.vatsim.net) stanowisk RADIO: EP** i znane stanowiska sąsiadów, trwające i dzisiejsze."""
    try:
        data = await vatsim_api.get_bookings()
    except (UpstreamError, ValueError) as exc:
        raise HTTPException(502, f"VATSIM ATC bookings niedostępne: {exc}") from exc
    known = {p["callsign"] for p in all_positions(db)}
    result = {cs: b for cs, b in bookings_by_callsign(data).items() if cs in known or cs.startswith("EP")}
    try:
        feed = await vatsim_api.get_feed()
        names = {c.get("cid"): c.get("name") for c in feed.get("controllers", []) + feed.get("pilots", [])}
    except (UpstreamError, ValueError):
        names = {}
    for lst in result.values():
        for b in lst:
            b["name"] = names.get(b["cid"])
    return result


@router.get("/sectors")
def sectors(db: Session = Depends(get_db)):
    """Wszystkie wycinki sektorów z pliku .ese (EPWW i sąsiedzi) do mapy zasięgu: rodzaj (acc/tma/ctr/fis/nb),
    nazwa zbiorcza i lista OWNER przełożona na znaki stanowisk (kolejność przejmowania)."""
    by_id = {p.position_id: p.callsign for p in db.scalars(select(AtcPosition))}
    covered = covered_firs(db)
    feats = []
    for s in db.scalars(select(Sector).order_by(Sector.id)):
        kind = sector_kind(s.fir, s.name)
        if not kind or s.lower_ft >= 66000 or (kind == "nb" and s.fir.upper() in covered):
            continue
        ids = [o for o in s.owners.split(":") if o]
        feats.append({"type": "Feature", "geometry": json.loads(s.geometry), "properties": {
            "fir": s.fir, "name": s.name, "kind": kind, "group": sector_group(s.fir, s.name, kind),
            "lower_ft": s.lower_ft, "upper_ft": s.upper_ft, "owners": [by_id[o] for o in ids if o in by_id],
            "owner_ids": ids, "source": "EPWW"}})
    # sąsiedzi z ich własnych plików .ese (bez wycinków technicznych i powyżej FL660 – pominięte przy imporcie)
    for s in nb_sectors(db):
        fir = s.fir.upper()
        feats.append({"type": "Feature", "geometry": json.loads(s.geometry), "properties": {
            "fir": fir, "name": s.name, "kind": "nb", "group": sector_group(fir, s.name, "nb"),
            "lower_ft": s.lower_ft, "upper_ft": s.upper_ft, "owners": owners_of(s), "owner_ids": [],
            "source": s.source}})
    return {"type": "FeatureCollection", "features": feats,
            "note": None if feats else "Brak sektorów: zaimportuj plik .ese (data/import)."}
