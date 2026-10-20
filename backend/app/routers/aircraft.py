import logging
import re
import unicodedata

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AircraftType
from ..services.photos import fetch_photo, local_photo, photo_query

router = APIRouter(prefix="/api/aircraft", tags=["aircraft"])
log = logging.getLogger("polids.aircraft")

# jeden rekord na oznaczenie typu z ICAO_Aircraft.json; *_max: górna granica osiągów, gdy wersje typu się różnią.
# Kolumna source (pliki, z których zbudowano rekord) zostaje w bazie, do interfejsu nie idzie.
FIELDS = ["id", "icao", "iata", "manufacturer", "model", "description", "wtc", "wtg", "recat", "wingspan", "length",
          "height", "mtow", "use", "engine_count", "engine_type", "mlw", "mlw_max", "ceiling_ft", "ceiling_ft_max",
          "vmo_kt", "vmo_kt_max", "mmo", "mmo_max"]


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


def _squash(col):
    """Kolumna bez myślników, spacji, kropek i ukośników (w SQL), do porównania z _key()."""
    for ch in "- ./":
        col = func.replace(col, ch, "")
    return col


def _key(text: str) -> str:
    """Szukany tekst bez znaków przestankowych: "A300" i "a 300" znajdują model "A-300(B4/C4/F4)-600"."""
    return re.sub(r"[^A-Za-z0-9]+", "", text)


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
        raise HTTPException(400, f"Unknown manufacturer: {maker} (available: {', '.join(MAKERS)})")
    limit = min(limit, 2000)
    stmt = select(AircraftType)
    if not maker:
        stmt = stmt.limit(limit)
    q = q.strip()
    if q:
        like = f"%{q}%"
        found = [AircraftType.icao.ilike(like), AircraftType.model.ilike(like), AircraftType.manufacturer.ilike(like),
                 AircraftType.iata.ilike(like)]
        if key := _key(q):  # "A300" -> "A-300…"
            found.append(_squash(AircraftType.model).ilike(f"%{key}%"))
            if " " in q:  # "airbus a320" -> "AIRBUS" + "A-320"
                found.append(_squash(func.coalesce(AircraftType.manufacturer, "") + AircraftType.model)
                             .ilike(f"%{key}%"))
        # najpierw dokładny kod ICAO, potem kody od szukanego tekstu ("A30": A306, A30B przed PA30), dalej wg kodu
        code = q.upper()
        stmt = stmt.where(or_(*found)).order_by(
            case((AircraftType.icao == code, 0), (AircraftType.icao.startswith(code, autoescape=True), 1), else_=2),
            AircraftType.icao)
    else:
        stmt = stmt.order_by(AircraftType.icao)
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
        raise HTTPException(404, "No such aircraft type")
    if found := local_photo(a.icao):
        return found
    try:
        found = await fetch_photo(a.icao, photo_query(a.manufacturer, a.model))
    except (httpx.HTTPError, ValueError) as exc:
        # przyczyna w logu serwera; w interfejsie sam komunikat
        log.warning("AIRCRAFT: zdjęcie %s niedostępne (%s)", a.icao, exc)
        raise HTTPException(502, "Photo unavailable") from exc
    if not found:
        raise HTTPException(404, "No photo of this type")
    return found


@router.get("/{aircraft_id}")
def get_one(aircraft_id: int = Path(ge=1, le=2**31 - 1), db: Session = Depends(get_db)):
    a = db.get(AircraftType, aircraft_id)
    if not a:
        raise HTTPException(404, "No such aircraft type")
    return _dict(a)
