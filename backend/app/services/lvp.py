"""Wskaźnik LVP (Low Visibility Procedures) liczony z METAR według progów z data/seed/lvp.json."""

import json
import re

from ..config import settings
from .metar import Metar


def thresholds(icao: str) -> dict:
    cfg = json.loads((settings.seed_dir / "lvp.json").read_text("utf-8"))
    return cfg.get(icao.upper(), cfg["DEFAULT"])


def rvr_value(v: str) -> int | None:
    """'P2000' -> 2000, 'M0050' -> 50, '0550V0800' -> 550 (bierzemy wartość najmniejszą)."""
    nums = [int(x) for x in re.findall(r"\d{4}", v or "")]
    return min(nums) if nums else None


def evaluate(m: Metar | None, icao: str) -> dict:
    """Zwraca {"state": "LVP" | "PREP" | None, "reasons": [...], "thresholds": {...}}."""
    th = thresholds(icao)
    if m is None:
        return {"state": None, "reasons": [], "thresholds": th}
    rvrs = [(r["runway"], rvr_value(r["value"])) for r in m.rvr if rvr_value(r["value"]) is not None]
    for state in ("lvp", "prep"):
        t = th[state]
        reasons = []
        for rwy, val in rvrs:
            if val < t["rvr_m"]:
                reasons.append(f"RVR {rwy} {val} m < {t['rvr_m']} m")
        if not rvrs and m.visibility_m is not None and m.visibility_m < t["rvr_m"]:
            reasons.append(f"widzialność {m.visibility_m} m < {t['rvr_m']} m")
        if m.ceiling_ft is not None and m.ceiling_ft <= t["ceiling_ft"]:
            reasons.append(f"podstawa chmur {m.ceiling_ft} ft ≤ {t['ceiling_ft']} ft")
        if reasons:
            return {"state": state.upper(), "reasons": reasons, "thresholds": th}
    return {"state": None, "reasons": [], "thresholds": th}
