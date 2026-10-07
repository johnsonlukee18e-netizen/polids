import json
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, settings
from ..database import get_db
from ..importers.ese import parse_vfr_points
from ..importers.sct import parse_line_groups, read_text, sections
from ..models import AirwaySegment, AtcPosition, NavPoint, Sector
from ..services.http_cache import UpstreamError
from ..services.route import RouteResolver
from ..services.vatsim import get_feed, match_positions

router = APIRouter(prefix="/api/nav", tags=["map"])

# Granice TMA i CTR z pliku .sct, tak jak rysuje je EuroScope: TMA = "EPxx TMA OUT/IN" z [ARTCC] i [ARTCC LOW],
# CTR = "ZZ_CTR ALL" z [ARTCC LOW].
AIRSPACE_KINDS = {
    "tma": lambda name: " TMA " in f" {name} " or "MTMA" in name,
    "ctr": lambda name: "CTR" in name.split()[0] and not name.startswith("AoR"),
}


@lru_cache(maxsize=1)
def sct_line_groups() -> dict[str, list]:
    out: dict[str, list] = {}
    for f in sorted((DATA_DIR / "import").glob("*.sct")):
        secs = sections(read_text(f))
        for key in ("[ARTCC]", "[ARTCC LOW]"):
            for name, segs in parse_line_groups(secs.get(key, [])).items():
                out.setdefault(name, []).extend(segs)
    return out


@router.get("/airspace")
def airspace(kind: str = Query("tma", pattern="^(tma|ctr)$")):
    """Linie granic TMA albo CTR z pliku .sct jako GeoJSON (MultiLineString, współrzędne lon/lat).

    `inner` = linie wewnętrzne podziału TMA (np. "EPBY TMA IN"), rysowane cieniej."""
    feats = []
    for name, segs in sct_line_groups().items():
        if not AIRSPACE_KINDS[kind](name):
            continue
        feats.append({"type": "Feature", "properties": {"name": name, "inner": name.endswith(" IN")},
                      "geometry": {"type": "MultiLineString",
                                   "coordinates": [[[a[1], a[0]], [b[1], b[0]]] for a, b in segs]}})
    return {"type": "FeatureCollection", "features": feats}


@router.get("/route")
def route(route: str = Query(..., min_length=3), db: Session = Depends(get_db)):
    return RouteResolver(db).resolve(route)


def _bbox(bbox: str):
    try:
        s, w, n, e = (float(x) for x in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(400, "bbox = poludnie,zachod,polnoc,wschod") from exc
    if (n - s) * (e - w) > 400:
        raise HTTPException(400, "Za duży obszar, przybliż mapę")
    return s, w, n, e


@lru_cache(maxsize=1)
def vfr_points() -> list[dict]:
    out = []
    for f in sorted((DATA_DIR / "import").glob("*.ese")):
        out += parse_vfr_points(read_text(f))
    return out


@router.get("/points")
def points(bbox: str, kinds: str = "VOR,NDB,VOR-DME,DME,VORTAC,NDB-DME,FIX", limit: int = Query(3000, ge=1, le=20000),
           db: Session = Depends(get_db)):
    """Punkty nawigacyjne w obszarze. Rodzaj VFR = punkty meldowania VFR z pliku .ese (sekcja FREETEXT)."""
    s, w, n, e = _bbox(bbox)
    if "VFR" in kinds.split(","):
        vfr = [p for p in vfr_points() if s <= p["lat"] <= n and w <= p["lon"] <= e]
        rest = ",".join(k for k in kinds.split(",") if k != "VFR")
        return vfr + (points(bbox, rest, limit, db) if rest else [])
    stmt = (select(NavPoint)
            .where(NavPoint.lat.between(s, n), NavPoint.lon.between(w, e), NavPoint.kind.in_(kinds.split(",")))
            .limit(limit))
    # Ten sam punkt bywa w kilku źródłach (np. NDB "NO" z pliku .sct i "N" z OurAirports w tym samym miejscu).
    # Pierwszeństwo ma plik sektorowy (aktualny AIRAC), brakującą nazwę/częstotliwość bierzemy z OurAirports.
    prio = {"sct": 0, "ourairports": 1}
    family = lambda k: "NDB" if "NDB" in k else "VOR" if k in ("VOR", "VOR-DME", "DME", "VORTAC") else k  # noqa: E731
    seen: dict[tuple, dict] = {}
    out = []
    for p in sorted(db.scalars(stmt), key=lambda p: prio.get(p.source, 2)):
        keys = [(p.ident, round(p.lat, 1), round(p.lon, 1))]
        if family(p.kind) in ("VOR", "NDB"):
            keys.append((family(p.kind), round(p.lat, 2), round(p.lon, 2)))
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit:
            hit["name"] = hit["name"] or p.name
            hit["frequency"] = hit["frequency"] or p.frequency
            continue
        item = {"ident": p.ident, "kind": p.kind, "name": p.name, "frequency": p.frequency, "lat": p.lat, "lon": p.lon}
        for k in keys:
            seen[k] = item
        out.append(item)
    return out


@router.get("/airways")
def airways(bbox: str, limit: int = Query(5000, ge=1, le=20000), db: Session = Depends(get_db)):
    s, w, n, e = _bbox(bbox)
    stmt = (select(AirwaySegment)
            .where(AirwaySegment.from_lat.between(s, n), AirwaySegment.from_lon.between(w, e))
            .limit(limit))
    return [{"airway": a.airway, "level": a.level, "from": a.from_ident, "to": a.to_ident,
             "coords": [[a.from_lat, a.from_lon], [a.to_lat, a.to_lon]]} for a in db.scalars(stmt)]


def _positions(db: Session) -> dict[str, AtcPosition]:
    return {p.position_id: p for p in db.scalars(select(AtcPosition))}


@router.get("/positions")
def positions(db: Session = Depends(get_db)):
    """Stanowiska ATC z pliku .ese (zakładka RADIO)."""
    return [{"callsign": p.callsign, "name": p.name, "frequency": p.frequency, "position_id": p.position_id,
             "prefix": p.prefix} for p in db.scalars(select(AtcPosition).order_by(AtcPosition.callsign))]


@router.get("/sectors")
def sectors(fir: str = "EPWW", level_ft: int | None = Query(None, ge=-2000, le=100000), db: Session = Depends(get_db)):
    """Sektory z pliku .ese jako GeoJSON. Bez zaimportowanego .ese zwraca plik data/seed/sectors.geojson."""
    stmt = select(Sector).where(Sector.fir == fir.upper())
    if level_ft is not None:
        stmt = stmt.where(Sector.lower_ft <= level_ft, Sector.upper_ft > level_ft)
    rows = db.scalars(stmt).all()
    if not rows:
        return json.loads((settings.seed_dir / "sectors.geojson").read_text("utf-8"))
    pos = _positions(db)
    feats = []
    for s in rows:
        owners = [o for o in s.owners.split(":") if o]
        first = pos.get(owners[0]) if owners else None
        feats.append({"type": "Feature", "geometry": json.loads(s.geometry), "properties": {
            "name": s.name, "lower_ft": s.lower_ft, "upper_ft": s.upper_ft, "owners": owners,
            "callsign": first.callsign if first else None, "frequency": first.frequency if first else None,
        }})
    return {"type": "FeatureCollection", "features": feats}


@lru_cache(maxsize=1)
def _vacs() -> dict:
    return json.loads((settings.seed_dir / "vacs_epww.json").read_text("utf-8"))


@router.get("/vacs")
def vacs():
    """Wyciąg z vacs-data (CC BY-NC-SA 4.0): łańcuchy dziedziczenia sektorów EPWW w warstwach LOW/MID/HIGH,
    stanowiska ACC i etykiety stanowisk sąsiadów z profilu ACC_EPWW."""
    return _vacs()


@router.get("/sectors/online")
async def sectors_online(fir: str = "EPWW", db: Session = Depends(get_db)):
    """Aktualna sektoryzacja: dla każdego sektora pierwsze zalogowane stanowisko z listy OWNER."""
    try:
        data = await get_feed()
    except (UpstreamError, ValueError) as exc:
        raise HTTPException(502, f"VATSIM data feed niedostępny: {exc}") from exc
    positions = db.scalars(select(AtcPosition)).all()
    online = match_positions(data.get("controllers", []), positions)
    by_id = {p.position_id: online[p.callsign] | {"position": p.callsign}
             for p in positions if p.callsign in online}
    result = {}
    for s in db.scalars(select(Sector).where(Sector.fir == fir.upper())):
        for o in s.owners.split(":"):
            if o in by_id:
                result[s.name] = {"position_id": o, **by_id[o]}
                break
    return {"online_positions": list(by_id.values()), "sector_owner": result,
            "updated": data.get("general", {}).get("update_timestamp")}
