"""Import globalnych danych nawigacyjnych EuroScope (pakiet GNG): isec.txt (punkty),
airway.txt (drogi lotnicze) i icao.txt (lotniska). Pliki leżą w data/import/."""

from pathlib import Path

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from ..models import AirwaySegment, NavPoint
from .sct import read_text

BATCH = 20000


def _rows(text: str):
    for line in text.splitlines():
        if line and not line.startswith(";"):
            yield line.split("\t")


def _bulk(db: Session, model, rows):
    buf = []
    n = 0
    for r in rows:
        buf.append(r)
        if len(buf) >= BATCH:
            db.execute(insert(model), buf)
            n += len(buf)
            buf = []
    if buf:
        db.execute(insert(model), buf)
        n += len(buf)
    return n


def import_isec(db: Session, path: Path) -> dict:
    def gen():
        for p in _rows(read_text(path)):
            if len(p) >= 3:
                try:
                    yield {"ident": p[0].strip(), "kind": "FIX", "lat": float(p[1]), "lon": float(p[2]),
                           "source": "isec"}
                except ValueError:
                    continue

    db.execute(delete(NavPoint).where(NavPoint.source == "isec"))
    n = _bulk(db, NavPoint, gen())
    db.commit()
    return {"points": n}


def import_icao_airports(db: Session, path: Path) -> dict:
    def gen():
        for p in _rows(read_text(path)):
            if len(p) >= 3:
                try:
                    yield {"ident": p[0].strip(), "kind": "AD", "lat": float(p[1]), "lon": float(p[2]),
                           "name": p[3].strip() if len(p) > 3 else None, "source": "icao"}
                except ValueError:
                    continue

    db.execute(delete(NavPoint).where(NavPoint.source == "icao"))
    n = _bulk(db, NavPoint, gen())
    db.commit()
    return {"airports": n}


def parse_airways(text: str):
    """Wiersz (TAB): FIX lat lon 14 DROGA poziom POPRZEDNI lat lon minalt Y/N NASTĘPNY lat lon minalt Y/N.
    Zwraca unikalne odcinki (do poprzedniego i następnego punktu) z współrzędnymi obu końców."""
    seen = set()
    for p in _rows(text):
        if len(p) < 14:
            continue
        fix, airway = p[0].strip(), p[4].strip()
        for idx in (6, 11):
            other = p[idx].strip()
            if not other:
                continue
            key = (airway, *sorted((fix, other)))
            if key in seen:
                continue
            try:
                seg = {"airway": airway, "level": p[5].strip() or None, "from_ident": fix, "to_ident": other,
                       "from_lat": float(p[1]), "from_lon": float(p[2]),
                       "to_lat": float(p[idx + 1]), "to_lon": float(p[idx + 2])}
            except ValueError:
                continue
            seen.add(key)
            yield seg


def import_airways(db: Session, path: Path) -> dict:
    db.execute(delete(AirwaySegment))
    n = _bulk(db, AirwaySegment, parse_airways(read_text(path)))
    db.commit()
    return {"segments": n}
