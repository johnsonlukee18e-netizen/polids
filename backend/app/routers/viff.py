import logging
import re

from fastapi import APIRouter, HTTPException, Query

from ..services import viff
from ..services.http_cache import UpstreamError

router = APIRouter(prefix="/api/viff", tags=["viff"])
log = logging.getLogger("polids.viff")


async def _call(coro):
    # komunikat w interfejsie bez nazwy i adresu źródła (0.12.6); szczegóły błędu tylko w logu
    try:
        return await coro
    except (UpstreamError, ValueError) as exc:
        log.warning("vIFF: %s", exc)
        raise HTTPException(502, "Flow data unavailable") from exc


@router.get("/departures/{icao}")
async def departures(icao: str):
    """Odloty z vIFF: EOBT, CTOT, status lotu (jak w liście lotów NM), a na lotniskach z A-CDM także TOBT, TSAT, AOBT, TTOT."""
    if not re.fullmatch(r"[A-Za-z]{4}", icao):
        raise HTTPException(400, "Aerodrome ICAO code = 4 letters")
    return await _call(viff.departures(icao))


@router.get("/sectors")
async def sectors(prefix: str = Query("", pattern="^[A-Za-z]{0,2}$")):
    """Sektory (traffic volumes) vIFF: przepustowość i ruch od teraz do +60 min, oraz scenariusze (aktywne na początku)."""
    return await _call(viff.sectors(prefix or None))


@router.get("/flight/{callsign}")
async def flight(callsign: str):
    """Jeden lot z vIFF (jak szczegóły lotu w NM UI): EOBT/TOBT/TSAT/CTOT, regulacja, status CDM, trasa,
    historia i wejścia w sektory (traffic volumes) z całodobowych danych ETFMS."""
    if not re.fullmatch(r"[A-Za-z0-9]{2,10}", callsign):
        raise HTTPException(400, "Callsign = 2–10 letters and digits")
    f = await _call(viff.flight(callsign))
    if f is None:
        raise HTTPException(404, f"No flow data for flight {callsign.upper()}")
    return f
