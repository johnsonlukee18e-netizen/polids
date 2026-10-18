import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document
from ..services import eaip

router = APIRouter(prefix="/api/docs", tags=["docs"])
EP_ICAO = re.compile(r"EP[A-Z]{2}")


def _dict(d: Document):
    return {"id": d.id, "title": d.title, "category": d.category, "description": d.description,
            "url": f"/files/docs/{d.filename}"}


@router.get("")
def list_docs(db: Session = Depends(get_db)):
    """Dokumenty PDF z folderu data/docs/ (podfolder = kategoria). Folder skanowany przy starcie i przez /api/import."""
    return [_dict(d) for d in db.scalars(select(Document).order_by(Document.category, Document.title))]


@router.get("/charts/{icao}")
async def aerodrome_charts(icao: str):
    """AD CIV (0.12.5): mapy lotniska z AD 2.24 eAIP IFR bieżącej poprawki AIRAC: {icao, page (strona AD 2 w eAIP),
    charts: [{id, page, title, kind, url (PDF u PAŻP)}], error (opis, gdy strony nie udało się pobrać)}."""
    icao = icao.strip().upper()
    if not EP_ICAO.fullmatch(icao):
        raise HTTPException(400, "Aerodrome charts: ICAO code of a Polish aerodrome (EP + 2 letters)")
    return await eaip.aerodrome_charts(icao)
