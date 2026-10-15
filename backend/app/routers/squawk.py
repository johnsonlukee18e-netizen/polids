from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..services.radio import seed_json
from ..services.squawk import lookup, normalize, valid_code

# SQUAWK (0.12.3): pule kodów SSR z EUROCONTROL CAL (FIR EPWW, CCAMS, NATO, EUR-E) i kody specjalne
router = APIRouter(prefix="/api/squawk", tags=["squawk"])


def _data() -> dict:
    """data/seed/squawk.json z pamięci, dopóki plik się nie zmieni (po imporcie CAL bez restartu serwera)."""
    try:
        return normalize(seed_json(settings.seed_dir / "squawk.json"))
    except FileNotFoundError as exc:
        raise HTTPException(404, "SQUAWK: brak pliku data/seed/squawk.json") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"SQUAWK: nie da się odczytać pliku data/seed/squawk.json ({exc})") from exc


@router.get("")
def squawk():
    """Pule kodów SSR z arkusza EUROCONTROL CAL (importers/squawk_cal.py) i kody specjalne.

    `pools`: [{from, to, count, category, pa, unit, civ_mil, app, assigned_by, ar, destination, via, protection,
    remarks, ver, sheet, row}] posortowane po kategorii (epww, ccams, nato, eur-e) i kodzie. `special`: [{code,
    label, meaning, source, note?, excluded?}]. `meta`: źródło, wydanie CAL, data importu, obszary uczestniczące
    (participating_areas), liczba pul w kategoriach (counts). `note`: opis pliku."""
    return _data()


@router.get("/lookup")
def squawk_lookup(code: str = Query(..., description="kod SSR: 4 cyfry ósemkowe, np. 7700")):
    """Znaczenie kodu: kody specjalne o tym numerze i wszystkie pule (każdej kategorii), w których leży."""
    code = code.strip()
    if not valid_code(code):
        hint = " (8 i 9 nie występują)" if any(c in "89" for c in code) else ""
        raise HTTPException(422, f"Kod SSR to 4 cyfry ósemkowe 0–7, np. 7700{hint}")
    return lookup(_data(), code)
