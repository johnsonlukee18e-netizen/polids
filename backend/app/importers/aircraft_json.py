"""Import pliku ICAO_Aircraft.json (format jak w vatiris: ICAO, Description, WTC, RECAT-EU,
Wingspan, Length, Height, MTOW, Use, Manufacturer, Model). Nadpisuje kategorie i wymiary
w typach z bazy startowej, a brakujące typy dodaje."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AircraftType
from .sct import read_text


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def import_aircraft_json(db: Session, path: Path) -> dict:
    data = json.loads(read_text(path))
    updated = added = 0
    for row in data:
        icao = (row.get("ICAO") or "").strip().upper()
        if not icao:
            continue
        values = {
            "wtc": row.get("WTC") or None,
            "recat": row.get("RECAT-EU") or None,
            "wingspan": _f(row.get("Wingspan")),
            "length": _f(row.get("Length")),
            "height": _f(row.get("Height")),
            "mtow": _f(row.get("MTOW")),
            "description": row.get("Description") or None,
            "use": row.get("Use") or None,
        }
        existing = db.scalars(select(AircraftType).where(AircraftType.icao == icao)).all()
        if existing:
            for ac in existing:
                for k, v in values.items():
                    if v is not None:
                        setattr(ac, k, v)
            updated += 1
        else:
            db.add(AircraftType(icao=icao, iata=row.get("IATA") or None,
                                manufacturer=(row.get("Manufacturer") or "").title() or None,
                                model=row.get("Model") or icao, source="ICAO_Aircraft.json", **values))
            added += 1
    db.commit()
    return {"updated_types": updated, "added_types": added}
