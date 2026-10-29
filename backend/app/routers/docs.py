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
    if icao not in eaip.AD2_AERODROMES:
        raise HTTPException(404, f"Aerodrome charts: no charts for {icao}")
    return await eaip.aerodrome_charts(icao)


# 0.13.1 (issue #25): AD CIV / AD MIL / AD VFR w jednym adresie; /charts/<ICAO> zostaje jako AD CIV (IFR)
AIP_OF = {"ifr": "aip_ifr", "mil": "aip_mil", "vfr": "aip_vfr"}


@router.get("/charts/{aip}/{icao}")
async def package_charts(aip: str, icao: str):
    """Mapy lotniska z bieżącej poprawki eAIP IFR (AD 2.24), MIL (AD 4.24) albo VFR (AD 4.13), odpowiedź jak
    /charts/<ICAO>. Tylko lotniska z listy pakietu (eaip.AERODROMES): inny kod EPxx nie trafia do PAŻP."""
    link = AIP_OF.get(aip.strip().lower())
    if link is None:
        raise HTTPException(404, "Aerodrome charts: unknown AIP (ifr, mil or vfr)")
    icao = icao.strip().upper()
    if not EP_ICAO.fullmatch(icao):
        raise HTTPException(400, "Aerodrome charts: ICAO code of a Polish aerodrome (EP + 2 letters)")
    if icao not in eaip.AERODROMES[link]:
        raise HTTPException(404, f"Aerodrome charts: no charts for {icao}")
    return await eaip.aerodrome_charts(icao, link=link)
