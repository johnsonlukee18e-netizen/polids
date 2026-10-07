"""Import pliku .ese EuroScope: stanowiska ATC ([POSITIONS]) i sektory ([AIRSPACE]).

Sektor składa się z linii granicznych (SECTORLINE) wymienionych w BORDER; łączymy je w wielokąt.
Właścicielem sektora jest pierwsze zalogowane stanowisko z listy OWNER."""

import json
import re
from pathlib import Path

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from ..models import AtcPosition, Sector
from .sct import parse_coord, read_text


def parse_positions(lines: list[str]) -> list[dict]:
    out = {}
    for line in lines:
        p = line.split(":")
        if len(p) < 7 or not p[0]:
            continue
        out[p[0]] = {"callsign": p[0], "name": p[1], "frequency": p[2], "position_id": p[3],
                     "suffix": p[4] or None, "prefix": p[5] or None}
    return list(out.values())


def _chain(lines: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """Łączy linie graniczne w zamknięty pierścień, odwracając je w razie potrzeby."""
    lines = [ln for ln in lines if ln]
    if not lines:
        return []
    ring = list(lines.pop(0))
    close = lambda a, b: abs(a[0] - b[0]) < 1e-4 and abs(a[1] - b[1]) < 1e-4  # noqa: E731
    while lines:
        end = ring[-1]
        for i, ln in enumerate(lines):
            if close(ln[0], end):
                ring.extend(ln[1:])
                break
            if close(ln[-1], end):
                ring.extend(list(reversed(ln))[1:])
                break
        else:
            # brak styku: dołącz najbliższą linię, żeby nie zgubić geometrii
            ln = min(lines, key=lambda ln: min(abs(ln[0][0] - end[0]) + abs(ln[0][1] - end[1]),
                                               abs(ln[-1][0] - end[0]) + abs(ln[-1][1] - end[1])))
            i = lines.index(ln)
            if abs(ln[-1][0] - end[0]) + abs(ln[-1][1] - end[1]) < abs(ln[0][0] - end[0]) + abs(ln[0][1] - end[1]):
                ln = list(reversed(ln))
            ring.extend(ln)
        lines.pop(i)
    if not close(ring[0], ring[-1]):
        ring.append(ring[0])
    return ring


def parse_airspace(lines: list[str]) -> list[dict]:
    sectorlines: dict[str, list[tuple[float, float]]] = {}
    sectors = []
    cur_line = None
    cur_sector = None
    for line in lines:
        key, _, rest = line.partition(":")
        if key == "SECTORLINE":
            cur_line = rest.strip()
            sectorlines[cur_line] = []
            cur_sector = None
        elif key == "COORD" and cur_line is not None:
            lat_s, _, lon_s = rest.partition(":")
            lat, lon = parse_coord(lat_s), parse_coord(lon_s)
            if lat is not None and lon is not None:
                sectorlines[cur_line].append((lat, lon))
        elif key == "SECTOR":
            cur_line = None
            name, lower, upper = (rest.split(":") + ["0", "0"])[:3]
            parts = [x.strip() for x in re.split(r"[\u00a7\u00b7]", name)]
            cur_sector = {"fir": parts[0], "name": parts[1] if len(parts) > 1 else name,
                          "lower_ft": int(lower or 0), "upper_ft": int(upper or 0), "owners": "", "border": []}
            sectors.append(cur_sector)
        elif key == "OWNER" and cur_sector:
            cur_sector["owners"] = rest.strip()
        elif key == "BORDER" and cur_sector:
            cur_sector["border"] = [b for b in rest.strip().split(":") if b]

    out = []
    for s in sectors:
        ring = _chain([sectorlines.get(b, []) for b in s.pop("border")])
        if len(ring) < 4:
            continue
        s["geometry"] = json.dumps({"type": "Polygon", "coordinates": [[[round(lon, 5), round(lat, 5)]
                                                                        for lat, lon in ring]]})
        out.append(s)
    return out


def parse_ese(text: str) -> dict:
    secs: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith(";"):
            continue
        line = line.rstrip()
        if line.startswith("["):
            current = line.strip().upper()
            secs.setdefault(current, [])
        elif current and line:
            secs[current].append(line)
    return {"positions": parse_positions(secs.get("[POSITIONS]", [])),
            "sectors": parse_airspace(secs.get("[AIRSPACE]", []))}


def import_ese(db: Session, path: Path) -> dict:
    data = parse_ese(read_text(path))
    db.execute(delete(AtcPosition))
    db.execute(delete(Sector))
    if data["positions"]:
        db.execute(insert(AtcPosition), data["positions"])
    if data["sectors"]:
        db.execute(insert(Sector), data["sectors"])
    db.commit()
    return {"positions": len(data["positions"]), "sectors": len(data["sectors"])}


def parse_vfr_points(text: str) -> list[dict]:
    """Punkty VFR z sekcji [FREETEXT] (grupy "EPWA VFR", "EPKK VFR"…): N052.03.47.000:E020.44.35.000:EPBC VFR:A"""
    out, in_ft = [], False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_ft = line.upper() == "[FREETEXT]"
            continue
        if not in_ft or not line or line.startswith(";"):
            continue
        parts = line.split(":")
        if len(parts) < 4 or not parts[2].upper().endswith(" VFR"):
            continue
        lat, lon = parse_coord(parts[0]), parse_coord(parts[1])
        if lat is None or lon is None:
            continue
        ad = parts[2].split()[0].upper()
        out.append({"ident": parts[3].strip(), "kind": "VFR", "name": f"{ad} VFR", "frequency": None,
                    "lat": lat, "lon": lon})
    return out
