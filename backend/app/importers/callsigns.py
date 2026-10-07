"""Import callsignów z pliku ICAO_Airlines.txt dołączanego do pakietów sektorowych EuroScope
(format: ICAO<TAB>NAZWA<TAB>TELEFONIA<TAB>KRAJ). Plik leży w data/import/."""

from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Callsign
from .sct import read_text


def parse_icao_airlines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(";"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3 or not (2 <= len(parts[0]) <= 4):
            continue
        out.append({"icao": parts[0].upper(), "name": parts[1], "telephony": parts[2] or None,
                    "country": parts[3] if len(parts) > 3 else None})
    return out


def import_icao_airlines(db: Session, path: Path) -> dict:
    text = read_text(path)
    rows = parse_icao_airlines(text)
    if not rows and len(text.strip().splitlines()) == 1:
        # w pakiecie sektorowym ICAO_Airlines.txt bywa tylko odnośnikiem do ../../ICAO/ICAO_Airlines.txt
        raise ValueError(f"Plik zawiera tylko ścieżkę '{text.strip()}'. Skopiuj prawdziwy plik z folderu ICAO pakietu.")
    for r in rows:
        db.merge(Callsign(source="sector-file", **r))
    db.commit()
    return {"callsigns": len(rows)}


def parse_gr_operator_info(text: str) -> dict[str, str]:
    """GRpluginOperatorInfo.txt (Ground Radar plugin): ICAO<TAB>C (cargo) albo Mil (wojsko)."""
    kinds = {"C": "CARGO", "MIL": "MIL"}
    out = {}
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[1].strip().upper() in kinds:
            out[parts[0].strip().upper()] = kinds[parts[1].strip().upper()]
    return out


def import_gr_operator_info(db: Session, path: Path) -> dict:
    info = parse_gr_operator_info(read_text(path))
    found = 0
    for icao, cat in info.items():
        cs = db.get(Callsign, icao)
        if cs:
            cs.category = cat
            found += 1
    db.commit()
    return {"categories": len(info), "matched": found}
