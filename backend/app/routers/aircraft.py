import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AircraftType
from ..services.photos import fetch_photo, local_photo

router = APIRouter(prefix="/api/aircraft", tags=["aircraft"])

FIELDS = ["id", "icao", "iata", "manufacturer", "model", "aircraft_type", "engine_type", "engine_count",
          "description", "wtc", "recat", "wingspan", "length", "height", "mtow", "mlw", "ceiling_ft",
          "vmo_kt", "mmo", "use", "remarks", "source"]


def _dict(a: AircraftType) -> dict:
    return {k: getattr(a, k) for k in FIELDS}


@router.get("")
def search(q: str = "", prefix: str = "", wtc: str = "", recat: str = "", limit: int = Query(200, ge=1, le=2000),
           db: Session = Depends(get_db)):
    stmt = select(AircraftType).order_by(AircraftType.icao, AircraftType.model).limit(min(limit, 2000))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AircraftType.icao.ilike(like), AircraftType.model.ilike(like),
                              AircraftType.manufacturer.ilike(like), AircraftType.iata.ilike(like)))
    if prefix:
        stmt = stmt.where(AircraftType.icao.startswith(prefix.upper()))
    if wtc:
        stmt = stmt.where(AircraftType.wtc == wtc.upper())
    if recat:
        stmt = stmt.where(AircraftType.recat == recat.upper())
    return [_dict(a) for a in db.scalars(stmt)]


@router.get("/{aircraft_id}/photo")
async def photo(aircraft_id: int = Path(ge=1, le=2**31 - 1), db: Session = Depends(get_db)):
    """Zdjęcie typu z data/photos/; przy pierwszym wywołaniu pobierane z Wikipedii i zapisywane lokalnie."""
    a = db.get(AircraftType, aircraft_id)
    if not a:
        raise HTTPException(404, "Nie ma takiego typu")
    if found := local_photo(a.icao):
        return found
    try:
        found = await fetch_photo(a.icao, f"{a.manufacturer or ''} {a.model}".strip())
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Nie udało się pobrać zdjęcia z Wikipedii: {exc}") from exc
    if not found:
        raise HTTPException(404, "Brak zdjęcia tego typu")
    return found


@router.get("/{aircraft_id}")
def get_one(aircraft_id: int = Path(ge=1, le=2**31 - 1), db: Session = Depends(get_db)):
    a = db.get(AircraftType, aircraft_id)
    if not a:
        raise HTTPException(404, "Nie ma takiego typu")
    return _dict(a)
