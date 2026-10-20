import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..database import get_db
from ..services import overview as overview_service

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("/positions")
def positions(db: Session = Depends(get_db)):
    """Stanowiska do filtra OVERVIEW, pogrupowane ACC / APP / TWR, z lotniskami przypisanymi do każdego z nich
    (z kolejności przejmowania wycinków CTR/TMA w pliku .ese). TWR/GND/DEL mają `goto` – skok do PRZEGLĄDU lotniska."""
    return overview_service.positions(db)


@router.get("")
async def overview(request: Request,
                   position: str = Query("", description="Position callsign, e.g. EPWA_APP (empty = whole FIR)"),
                   db: Session = Depends(get_db)):
    """Wszystko do widoku AERODROME › OVERVIEW: poziom przejściowy, METAR/TAF z LVP i pasem w użyciu, obowiązujące
    NOTAM-y, restrykcje ECFMP i vIFF oraz Airport Monitor vIFF dla lotnisk wybranego stanowiska; przy stanowisku
    ACC / APP także `covered_by` lotnisk obsługiwanych teraz przez innych (CID zalogowanego użytkownika z sesji: jego
    połączenia się nie liczą)."""
    if position and not re.fullmatch(r"[A-Za-z0-9_]{3,20}", position):
        raise HTTPException(400, "Position callsign: letters, digits and underscores only (e.g. EPWA_APP)")
    user = current_user(request) if settings.auth_mode != "none" else None
    cid = str(user["cid"]) if user and user.get("cid") else None
    return await overview_service.overview(db, position or None, cid=cid)
