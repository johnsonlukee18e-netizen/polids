import re
import unicodedata

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


# Przyciski producentów u góry AIRCRAFT (?maker=). Nazwy producenta w bazie bywają różne: "Airbus Industrie",
# "McDonnell-Douglas", "Mcdonnell Douglas", "Aérospatiale/Alenia (ATR)", "Reims-Cessna"... Dlatego najpierw zgrubnie
# w SQL (LIKE po producencie i modelu), potem dokładnie wyrażeniem na nazwie bez diakrytyków i znaków przestankowych.
# like: fragmenty do LIKE; maker / model: wyrażenia dla producenta / modelu; icao: kody typów pewne niezależnie od nazwy.
MAKERS = {
    "airbus": {"like": ["airbus"], "maker": r"\bairbus\b"},
    "boeing": {"like": ["boeing"], "maker": r"\bboeing\b"},
    "embraer": {"like": ["embraer"], "maker": r"\bembraer\b"},
    # McDonnell Douglas razem z Douglas (DC-3…DC-9) i McDonnell (F-4) sprzed połączenia
    "mcdonnell": {"like": ["donnell", "douglas"], "maker": r"\bmc ?donnell\b|\bdouglas\b"},
    # ATR: także "Avions de Transport Régional", "Aerospatiale/Alenia", model "ATR 72-600" i kody ATR 42 / ATR 72
    "atr": {"like": ["atr", "alenia", "transport regional"],
            "maker": r"\batr\b|avions de transport regional|aerospatiale.*alenia|alenia.*aerospatiale",
            "model": r"^atr( |\d|$)", "icao": {"AT43", "AT44", "AT45", "AT46", "AT72", "AT73", "AT75", "AT76"}},
    # Cessna: także Reims-Cessna i Textron Aviation z modelem "Cessna …" / "Citation …"
    "cessna": {"like": ["cessna", "citation"], "maker": r"\bcessna\b", "model": r"\b(cessna|citation)\b"},
}


def _norm(text: str | None) -> str:
    """Małe litery bez diakrytyków, znaki przestankowe jako spacje: "Aérospatiale/Alenia" -> "aerospatiale alenia"."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def maker_matches(key: str, manufacturer: str | None, model: str | None, icao: str | None) -> bool:
    m = MAKERS[key]
    return ((icao or "").upper() in m.get("icao", ())
            or bool(re.search(m["maker"], _norm(manufacturer)))
            or bool(m.get("model") and re.search(m["model"], _norm(model))))


@router.get("")
def search(q: str = "", prefix: str = "", wtc: str = "", recat: str = "", maker: str = "",
           limit: int = Query(200, ge=1, le=2000),
           db: Session = Depends(get_db)):
    maker = maker.strip().lower()
    if maker and maker not in MAKERS:
        raise HTTPException(400, f"Nieznany producent: {maker} (dostępne: {', '.join(MAKERS)})")
    limit = min(limit, 2000)
    stmt = select(AircraftType).order_by(AircraftType.icao, AircraftType.model)
    if not maker:
        stmt = stmt.limit(limit)
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
    if not maker:
        return [_dict(a) for a in db.scalars(stmt)]
    m = MAKERS[maker]
    rough = [col.ilike(f"%{w}%") for w in m["like"] for col in (AircraftType.manufacturer, AircraftType.model)]
    if m.get("icao"):
        rough.append(AircraftType.icao.in_(m["icao"]))
    rows = [a for a in db.scalars(stmt.where(or_(*rough))) if maker_matches(maker, a.manufacturer, a.model, a.icao)]
    return [_dict(a) for a in rows[:limit]]


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
