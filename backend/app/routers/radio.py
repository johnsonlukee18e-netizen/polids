import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Aerodrome, AtcPosition, NavPoint, Sector
from ..services.http_cache import UpstreamError
from ..services.neighbours import covered_firs, nb_owners, nb_sectors, owners_of
from ..services.positions import all_positions
from ..services.radio import (Station, neighbour_tab, position_range, radio_names, sector_group, sector_kind,
                              seed_json)
from ..services.vatsim import bookings_by_callsign, controller_info, fir_boundaries, match_positions, online_firs
# data feed i rezerwacje przez moduł /api/vatsim: jeden cache i jedno miejsce podmiany (testy, serwer demo)
from . import vatsim as vatsim_api

router = APIRouter(prefix="/api/radio", tags=["radio"])
log = logging.getLogger("polids.radio")


def _seed_or_empty(name: str) -> dict:
    """Plik z data/seed do uzupełnienia listy stanowisk; brak albo błąd pliku nie psuje listy (tylko wpis w logu)."""
    try:
        data = seed_json(settings.seed_dir / name)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("RADIO: pomijam data/seed/%s (%s)", name, exc)
        return {}


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
    (granica VATSpy, okrąg wokół lotniska albo punkt lotniska). `nb_tab`: zakładka sąsiada (None = Polska).
    `radio`, `sector`: znak radiowy i nazwa sektora sąsiada (baza wiedzy VATSIM Germany, LOA, plik .ese)."""
    merged = all_positions(db)
    coords = _coords(db, {p["callsign"].split("_")[0] for p in merged})
    firs = fir_boundaries()
    for p in merged:
        lat, lon = coords.get(p["callsign"].split("_")[0], (None, None))
        p["range"] = position_range(p["callsign"], firs, lat, lon, p.get("prefix"))
        p["nb_tab"] = neighbour_tab(p)
    return radio_names(merged, _seed_or_empty("names_de.json").get("positions") or {},
                       _seed_or_empty("loa.json").get("firs") or {})


@router.get("/loa")
def loa():
    """Wyciąg z LOA EPWW z sąsiadami (data/seed/loa.json, PDF-y w DOCS › LOA): klucz = FIR zakładki sąsiada
    (EDWW, EDUU, EDMM, LKAA, LZBB, UKLV, EYVL, ESAA), w każdym tytuł, wersja, PDF, stanowiska, przekazania
    (dir out = EPWW → sąsiad, in = sąsiad → EPWW) i zasady (silent, vfr, other)."""
    try:
        data = seed_json(settings.seed_dir / "loa.json")
    except FileNotFoundError as exc:
        raise HTTPException(404, "LOA: brak pliku data/seed/loa.json") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"LOA: nie da się odczytać pliku data/seed/loa.json ({exc})") from exc
    firs = data.get("firs") if isinstance(data, dict) else None
    if not isinstance(firs, dict):
        raise HTTPException(500, "LOA: plik data/seed/loa.json nie ma sekcji firs")
    return {"firs": {k: v for k, v in firs.items() if isinstance(v, dict)}, "source": data.get("_zrodlo", "")}


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
