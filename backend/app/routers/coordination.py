import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import AtcPosition
from ..services import coordination as coord_service
from ..services.radio import seed_json

# COORDINATION (0.12.3): porozumienia LOA i LOP
router = APIRouter(prefix="/api/coordination", tags=["coordination"])
log = logging.getLogger("polids.coordination")
CALLSIGN = re.compile(r"[A-Za-z0-9_]{3,20}")


def _seed(name: str, required: bool = False) -> dict:
    """Plik z data/seed; brak albo błąd pliku pomocniczego (loa.json, ownership.json) nie psuje zakładki."""
    path = settings.seed_dir / name
    try:
        data = seed_json(path)
    except FileNotFoundError as exc:
        if required:
            raise HTTPException(404, f"COORDINATION: brak pliku data/seed/{name}") from exc
        log.warning("COORDINATION: brak pliku data/seed/%s", name)
        return {}
    except (OSError, ValueError) as exc:
        if required:
            raise HTTPException(500, f"COORDINATION: nie da się odczytać pliku data/seed/{name} ({exc})") from exc
        log.warning("COORDINATION: pomijam data/seed/%s (%s)", name, exc)
        return {}
    if not isinstance(data, dict):
        if required:
            raise HTTPException(500, f"COORDINATION: plik data/seed/{name} nie jest obiektem JSON")
        return {}
    return data


def _exists(rel: str) -> bool:
    """PDF w data/docs (bez wychodzenia poza folder)."""
    base = settings.docs_dir.resolve()
    p = (base / rel).resolve()
    return p.is_relative_to(base) and p.is_file()


def _files() -> list[str]:
    """PDF-y z podfolderów LOA i LOP w data/docs (też zagnieżdżone; kategoria = pierwszy folder, jak w OTHER › DOCS)."""
    base = settings.docs_dir
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and d.name.upper() in coord_service.TYPES:
            out += sorted(p.relative_to(base).as_posix() for p in d.glob("**/*.pdf") if p.is_file())
    return out


@router.get("")
def coordination(position: str = Query("", description="Znak stanowiska EPWW, np. EPWW_DBT_CTR (puste = wszystkie)"),
                 online: str = Query("", description="Stanowiska online po przecinku (kolejność przejmowania)"),
                 db: Session = Depends(get_db)):
    """Wszystko do zakładki COORDINATION: dokumenty LOA/LOP z data/seed/coordination.json (nazwa, PDF, FIR-y,
    sektory, AIRAC – `current`, gdy to bieżący cykl), przekazania z loa.json i z dokumentów jako wiersze (COP,
    ADEP/ADES, FL, kierunek out = EPWW → sąsiad, in = sąsiad → EPWW, sektor polski `ep` i sąsiada `nb`), kolejności
    przejmowania polskich sektorów (`chains`), stanowiska do wyboru i zasady z LOA (`notes`). PDF z data/docs/LOA|LOP
    bez wpisu w coordination.json: karta z nazwą pliku (`registered: false`) i uwaga w `errors`.
    `position` (+ `online`): sektory obsługiwane przez stanowisko i przy każdym wierszu `applies`."""
    if position and not CALLSIGN.fullmatch(position):
        raise HTTPException(400, "Znak stanowiska to litery, cyfry i podkreślenia (np. EPWW_DBT_CTR)")
    on = {cs.strip().upper() for cs in online.split(",") if cs.strip()}
    if any(not CALLSIGN.fullmatch(cs) for cs in on):
        raise HTTPException(400, "online: znaki stanowisk po przecinku (litery, cyfry i podkreślenia)")
    coord = _seed("coordination.json", required=True)
    names = {p.callsign: {"name": p.name, "frequency": p.frequency} for p in db.scalars(select(AtcPosition))}
    data = coord_service.build(coord, _seed("loa.json"), _seed("ownership.json"), names=names, file_exists=_exists,
                               files=_files())
    return coord_service.for_position(data, position.upper(), on) if position else data
