import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import overview as overview_service

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("/positions")
def positions(db: Session = Depends(get_db)):
    """Stanowiska do filtra OVERVIEW, pogrupowane ACC / APP / TWR, z lotniskami przypisanymi do każdego z nich
    (z kolejności przejmowania wycinków CTR/TMA w pliku .ese). TWR/GND/DEL mają `goto` – skok do PRZEGLĄDU lotniska."""
    return overview_service.positions(db)


@router.get("")
async def overview(position: str = Query("", description="Znak stanowiska, np. EPWA_APP (puste = cały FIR)"),
                   db: Session = Depends(get_db)):
    """Wszystko do widoku AERODROME › OVERVIEW: poziom przejściowy, METAR/TAF z LVP, obowiązujące NOTAM-y,
    restrykcje ECFMP i vIFF oraz Airport Monitor vIFF dla lotnisk wybranego stanowiska."""
    if position and not re.fullmatch(r"[A-Za-z0-9_]{3,20}", position):
        raise HTTPException(400, "Znak stanowiska to litery, cyfry i podkreślenia (np. EPWA_APP)")
    return await overview_service.overview(db, position or None)
