import logging

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..services.radio import seed_json
from ..services.squawk import lookup, normalize, valid_code

# SQUAWK (0.12.3): pule kodów SSR z EUROCONTROL CAL (FIR EPWW, CCAMS, NATO, EUR-E) i kody specjalne
router = APIRouter(prefix="/api/squawk", tags=["squawk"])
log = logging.getLogger(__name__)


def _data() -> dict:
    """data/seed/squawk.json z pamięci, dopóki plik się nie zmieni (po imporcie CAL bez restartu serwera). Błąd dla
    użytkownika bez nazwy pliku (0.12.6, issue #21: bez dopisków skąd dane), szczegóły w logu serwera."""
    path = settings.seed_dir / "squawk.json"
    try:
        return normalize(seed_json(path))
    except FileNotFoundError as exc:
        log.warning("SQUAWK: brak pliku %s", path)
        raise HTTPException(404, "SQUAWK: no data") from exc
    except (OSError, ValueError) as exc:
        log.warning("SQUAWK: nie da się odczytać %s: %s", path, exc)
        raise HTTPException(500, "SQUAWK: data unavailable") from exc


@router.get("")
def squawk():
    """Pule kodów SSR z arkusza EUROCONTROL CAL (importers/squawk_cal.py) i kody specjalne.

    `pools`: [{from, to, count, category, pa, unit, civ_mil, app, assigned_by, ar, destination, via, protection,
    remarks, ver, sheet, row}] posortowane po kategorii (epww, ccams, nato, eur-e) i kodzie. `special`: [{code,
    label}] (sam tytuł, np. 0001 LPR). `meta`: źródło, wydanie CAL, data importu, obszary uczestniczące
    (participating_areas), liczba pul w kategoriach (counts). `note`: opis pliku."""
    return _data()


@router.get("/lookup")
def squawk_lookup(code: str = Query(..., description="SSR code: 4 octal digits, e.g. 7700")):
    """Znaczenie kodu: kody specjalne o tym numerze i wszystkie pule (każdej kategorii), w których leży."""
    code = code.strip()
    if not valid_code(code):
        hint = " (8 and 9 do not occur)" if any(c in "89" for c in code) else ""
        raise HTTPException(422, f"An SSR code is 4 octal digits 0–7, e.g. 7700{hint}")
    return lookup(_data(), code)
