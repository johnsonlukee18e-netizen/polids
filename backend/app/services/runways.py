"""Składowe wiatru i wybór pasa preferowanego.

Zasada jak w vatiris (minsulander/vatiris, stores/wind.ts): pas z największą składową czołową; przy słabym wietrze
(poniżej progu, domyślnie 5 kt) pas preferowany z konfiguracji lotniska. Dodatkowo bierzemy pod uwagę wyposażenie
pasów (ILS z pakietu sektorowego) i widzialność: przy LVP / przygotowaniu LVP / IMC wybieramy pas z ILS,
o ile składowa w plecy nie przekracza limitu."""

import json
import math
import re
from functools import lru_cache

from ..config import DATA_DIR, settings


def runway_heading(designator: str, heading_true: float | None) -> float:
    """Kurs pasa: rzeczywisty z bazy, chyba że wyraźnie nie pasuje do numeru pasa (błąd danych, np. EPKR 16/34 z kursem 16°)."""
    m = re.match(r"\d+", designator or "")
    by_number = ((int(m.group()) * 10) % 360 or 360) if m else None
    if heading_true is not None and (by_number is None or abs((heading_true - by_number + 180) % 360 - 180) <= 30):
        return heading_true
    if by_number is None:
        raise ValueError(f"Nieznany kurs pasa {designator!r}")
    return by_number


def wind_components(wind_dir: int | None, wind_speed: int | None, rwy_heading: float):
    """Zwraca (wiatr czołowy, boczny) w kt. Czołowy < 0 oznacza wiatr w plecy.
    Boczny > 0 z prawej strony, < 0 z lewej."""
    if wind_speed is None or wind_dir is None:
        return None, None
    angle = math.radians(wind_dir - rwy_heading)
    return round(wind_speed * math.cos(angle), 1), round(wind_speed * math.sin(angle), 1)


@lru_cache(maxsize=1)
def runway_equipment() -> dict[str, dict[str, list[str]]]:
    """Rodzaje podejść na każdy kierunek pasa, wyczytane z nazw procedur (STAR/APP) w plikach .ese.

    Np. "STAR:EPWA:33:ILS-Y:..." -> {"EPWA": {"33": ["ILS"]}}. Wynik uzupełnia data/seed/runway_config.json."""
    kinds = ("ILS", "LOC", "RNP", "RNAV", "VOR", "NDB", "GLS", "PAR")
    out: dict[str, dict[str, set]] = {}
    for f in sorted((DATA_DIR / "import").glob("*.ese")):
        for line in f.read_text("utf-8", errors="replace").splitlines():
            if not line.startswith("STAR:"):
                continue
            parts = line.split(":")
            if len(parts) < 4:
                continue
            ad, rwy, name = parts[1].strip(), parts[2].strip(), parts[3].upper()
            for k in kinds:
                if k in name:
                    out.setdefault(ad, {}).setdefault(rwy, set()).add(k)
    return {ad: {r: sorted(k) for r, k in rw.items()} for ad, rw in out.items()}


def runway_config(icao: str) -> dict:
    """Ustawienia pasów lotniska z data/seed/runway_config.json (arr, dep, never, limit, ils_cat, equipment)."""
    try:
        cfg = json.loads((settings.seed_dir / "runway_config.json").read_text("utf-8"))
    except FileNotFoundError:
        return {}
    return {**cfg.get("DEFAULT", {}), **cfg.get(icao.upper(), {})}


def equipment_for(icao: str, cfg: dict | None = None) -> dict[str, list[str]]:
    cfg = runway_config(icao) if cfg is None else cfg
    eq = {r: list(k) for r, k in runway_equipment().get(icao.upper(), {}).items()}
    for r, k in (cfg.get("equipment") or {}).items():
        eq[r] = sorted(set(k))
    return eq


def select_runways(runways: list[dict], wind_dir: int | None, wind_speed: int | None, *,
                   equipment: dict[str, list[str]] | None = None, low_vis: str | None = None,
                   config: dict | None = None, max_tailwind_kt: float = 5.0) -> dict:
    """Pas preferowany do lądowania (arr) i startu (dep) z uzasadnieniem.

    `runways`: słowniki z kluczami designator, heading (i opcjonalnie preferred). `low_vis`: "LVP", "PREP" albo
    "IMC", gdy warunki wymagają podejścia precyzyjnego."""
    if not runways:
        return {"arr": None, "dep": None, "reason": "Brak danych o pasach"}
    cfg = config or {}
    eq = equipment or {}
    limit = cfg.get("limit", 5)
    never = set(cfg.get("never", []))
    rows = []
    for r in runways:
        if r["designator"] in never:
            continue
        head, cross = wind_components(wind_dir, wind_speed, r["heading"])
        rows.append({**r, "headwind": head, "crosswind": cross, "ils": "ILS" in eq.get(r["designator"], [])})
    rows = rows or [{**r, "headwind": None, "crosswind": None, "ils": False} for r in runways]
    by = {r["designator"]: r for r in rows}
    tail_ok = [r for r in rows if r["headwind"] is None or r["headwind"] >= -max_tailwind_kt]
    known = wind_dir is not None and wind_speed is not None
    calm = not known or wind_speed < limit
    head = lambda r: r["headwind"] if r["headwind"] is not None else 0  # noqa: E731
    pick = lambda arr, dep, why: {"arr": arr, "dep": dep or arr, "reason": why}  # noqa: E731

    if low_vis:
        ils = [r for r in tail_ok if r["ils"]]
        if ils:
            best = max(ils, key=head)["designator"]
            label = {"LVP": "LVP w mocy", "PREP": "Przygotowanie LVP", "IMC": "Warunki IMC"}.get(low_vis, low_vis)
            return pick(best, best, f"{label}: kierunek z ILS (wiatr w plecy ≤ {max_tailwind_kt:g} kt)")
    if calm:
        pref_arr = cfg.get("arr") or next((r["designator"] for r in rows if r.get("preferred")), None)
        pref_dep = cfg.get("dep") or pref_arr
        if pref_arr in by and by[pref_arr] in tail_ok:
            dep = pref_dep if pref_dep in by and by[pref_dep] in tail_ok else pref_arr
            return pick(pref_arr, dep, f"Wiatr < {limit} kt: konfiguracja preferowana lotniska")
        ils = [r for r in tail_ok if r["ils"]]
        if ils:
            best = max(ils, key=head)["designator"]
            return pick(best, best, f"Wiatr < {limit} kt: kierunek wyposażony w ILS")
    if not known:
        return pick(rows[0]["designator"], None, "Brak danych o wietrze: pierwszy pas z listy")
    best = max(rows, key=lambda r: (head(r), -abs(r["crosswind"] or 0), r["ils"]))["designator"]
    return pick(best, best, "Największa składowa czołowa")


def suggest_runway(runways: list[dict], wind_dir: int | None, wind_speed: int | None,
                   calm_threshold_kt: int = 5, max_tailwind_kt: float = 5.0):
    """Zgodność wstecz: (wiersz pasa do lądowania, uzasadnienie)."""
    res = select_runways(runways, wind_dir, wind_speed, config={"limit": calm_threshold_kt},
                         max_tailwind_kt=max_tailwind_kt)
    best = next((r for r in runways if r["designator"] == res["arr"]), None)
    return best, res["reason"]
