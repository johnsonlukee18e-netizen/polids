"""0.15.0: zdjęcia samolotów po rejestracji (Planespotters) i zdjęcia typów wrzucane przez adminów."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..config import settings
from ..database import get_db
from ..models import AircraftType
from ..services import photos, planespotters
from ..services.http_cache import UpstreamError

router = APIRouter(prefix="/api/photos", tags=["photos"])
log = logging.getLogger("polids.photos")

REG = r"^[A-Za-z0-9-]{2,10}$"
ICAO = r"^[A-Za-z0-9]{2,4}$"


@router.get("/registration/{reg}")
async def registration(reg: str = Path(pattern=REG)):
    """Zdjęcie samolotu o tej rejestracji z Planespotters.net: {registration, photo: {thumbnail, thumbnail_large,
    width, height, link, photographer} albo null}. Adresy bez zmian – miniaturę pobiera przeglądarka, a pod nią
    muszą być autor i odnośnik do strony zdjęcia (warunki API). 404: zdjęcia po rejestracji wyłączone."""
    if not settings.planespotters_url.strip():
        raise HTTPException(404, "Registration photos are off")
    try:
        return await planespotters.by_registration(reg)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except UpstreamError as exc:
        log.warning("Planespotters: %s niedostępne (%s)", reg, exc)
        raise HTTPException(502, planespotters.PHOTOS_DOWN) from exc


def _type(db: Session, icao: str) -> AircraftType:
    a = db.scalars(select(AircraftType).where(AircraftType.icao == icao.upper())).first()
    if not a:
        raise HTTPException(404, f"No aircraft type {icao.upper()}")
    return a


@router.post("/type/{icao}", dependencies=[Depends(require_admin)])
async def upload_type_photo(icao: str = Path(pattern=ICAO), file: UploadFile = File(...),
                            author: str = Form("", max_length=200), db: Session = Depends(get_db)):
    """Admin: zdjęcie typu (JPEG, PNG albo WebP, najwyżej POLIDS_PHOTO_UPLOAD_MAX_BYTES) z autorem w podpisie;
    zastępuje wcześniej wrzucone i ma pierwszeństwo przed zdjęciami z data/photos-manual/ i z Wikipedii."""
    a = _type(db, icao)
    data = await file.read(settings.photo_upload_max_bytes + 1)
    try:
        return photos.save_upload(a.icao, data, author)
    except photos.UploadError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/type/{icao}", status_code=204, dependencies=[Depends(require_admin)])
def delete_type_photo(icao: str = Path(pattern=ICAO), db: Session = Depends(get_db)):
    """Admin: usuwa wrzucone zdjęcie typu (wraca zdjęcie z data/photos-manual/ albo z Wikipedii)."""
    a = _type(db, icao)
    if not photos.delete_upload(a.icao):
        raise HTTPException(404, f"No uploaded photo of {a.icao}")
    return Response(status_code=204)
