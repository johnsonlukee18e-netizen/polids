from fastapi import APIRouter, HTTPException

from ..services.http_cache import UpstreamError
from ..services.notam import get_notams, notam_url

router = APIRouter(prefix="/api/notam", tags=["notam"])


@router.get("/{icao}")
async def notams(icao: str):
    if len(icao) != 4 or not icao.isalpha():
        raise HTTPException(400, "Kod ICAO musi mieć 4 litery")
    try:
        return await get_notams(icao)
    except UpstreamError as exc:
        raise HTTPException(502, f"Serwer NOTAM niedostępny ({notam_url(icao)}): {exc}") from exc
