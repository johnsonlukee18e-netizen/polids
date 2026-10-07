import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..config import VERSION, settings
from ..database import get_db
from ..importers.seed import init_db
from ..models import (AircraftType, Aerodrome, AirwaySegment, AtcPosition, Callsign, Document, ImportLog,
                      NavPoint, Sector)
from ..services import embed
from ..services.airac import current_airac

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/config")
def config():
    return {
        "name": settings.name, "tagline": settings.tagline, "version": VERSION, "auth_mode": settings.auth_mode,
        "airac": current_airac(),
        "default_aerodrome": settings.default_aerodrome,
        "links": {
            "aip_ifr": settings.aip_ifr_url, "aip_vfr": settings.aip_vfr_url, "aip_mil": settings.aip_mil_url,
            "inop": settings.inop_url, "imgw": settings.imgw_url, "sectors": settings.sectors_url,
            "phraseology": settings.phraseology_url, "performance_db": settings.performance_db_url,
        },
        "openaip_api_key": settings.openaip_api_key,
        "carto_api_key": settings.carto_api_key.strip(),
        "metar_source": settings.metar_source,
    }


EMBED_LINKS = {"phraseology": "phraseology_url", "inop": "inop_url", "aip_ifr": "aip_ifr_url", "aip_vfr": "aip_vfr_url",
               "aip_mil": "aip_mil_url", "performance_db": "performance_db_url"}


@router.get("/embed-check/{link}")
async def embed_check(link: str):
    """Czy strona z linków aplikacji pozwala wyświetlić się w ramce (X-Frame-Options / CSP frame-ancestors)."""
    if link not in EMBED_LINKS:
        raise HTTPException(404, f"Nieznany link: {link}")
    return await embed.check(getattr(settings, EMBED_LINKS[link]))


@router.get("/emergency")
def emergency():
    return json.loads((settings.seed_dir / "emergency.json").read_text("utf-8"))


@router.get("/checklists")
def checklists():
    """Checklisty stanowiska (otwarcie, zamknięcie, przekazanie, zmiana pasa) w formacie vatiris."""
    return json.loads((settings.seed_dir / "checklists.json").read_text("utf-8"))


@router.get("/status")
def status(db: Session = Depends(get_db)):
    count = lambda m: db.scalar(select(func.count()).select_from(m))  # noqa: E731
    return {
        "counts": {"aerodromes": count(Aerodrome), "aircraft_types": count(AircraftType),
                   "callsigns": count(Callsign), "nav_points": count(NavPoint), "airway_segments": count(AirwaySegment),
                   "atc_positions": count(AtcPosition), "sectors": count(Sector), "documents": count(Document)},
        "imports": [{"file": i.filename, "result": i.result} for i in db.scalars(select(ImportLog))],
    }


@router.post("/import", dependencies=[Depends(require_admin)])
def run_import(force: bool = False):
    """Ponownie wczytuje pliki z data/import/ i rejestruje PDF-y z data/docs/ (tylko admin)."""
    return {"results": init_db(force=force)}
