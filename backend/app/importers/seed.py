"""Wypełnianie bazy: dane startowe z data/seed/ (wersjonowane w repo) oraz pliki
z data/import/ (pliki sektorowe i navdata EuroScope). Sektory EPWW i sąsiadów (tabele sectors, nb_sectors)
z data/seed/sectors.geojson (generator: python -m backend.app.importers.sectors_geojson), stanowiska z plików .ese.

Uruchamiane automatycznie przy starcie aplikacji. Ręcznie:
    python -m backend.app.importers.seed            # import nowych/zmienionych plików
    python -m backend.app.importers.seed --force    # wszystko od nowa
"""

import csv
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import delete, func, inspect, or_, select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, settings
from ..database import SCHEMA_VERSION, Base, SessionLocal, engine
from ..models import (AircraftType, Aerodrome, Callsign, Document, Frequency, ImportLog, NavPoint, NbPosition, NbSector,
                      Runway, Sector)
from .aircraft_json import build_aircraft
from .callsigns import import_gr_operator_info, import_icao_airlines
from .ese import import_ese
from .neighbours import import_nb_ese, source_key
from .sectors_geojson import COMMAND, FILENAME, geojson_path, import_sectors_geojson, stale
from .navdata import import_airways, import_icao_airports, import_isec
from .sct import import_sct

log = logging.getLogger("polids.seed")
IMPORT_DIR = DATA_DIR / "import"
NB_DIR = IMPORT_DIR / "neighbours"  # pliki .ese FIR-ów sąsiednich (osobny import, nie nadpisują EPWW)

# (dopasowanie końcówki nazwy pliku, funkcja importu); kolejność ma znaczenie
IMPORTERS = [
    ("isec.txt", import_isec),
    ("icao.txt", import_icao_airports),
    ("airway.txt", import_airways),
    (".sct", import_sct),
    (".sct2", import_sct),
    (".ese", import_ese),
    ("icao_airlines.txt", import_icao_airlines),
    ("grpluginoperatorinfo.txt", import_gr_operator_info),
]
AIRCRAFT_JSON = "icao_aircraft.json"  # typy AIRCRAFT (import_aircraft, razem z data/seed/aircraft.csv)


def _csv(name: str):
    path = settings.seed_dir / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if not next(iter(r.values()), "").startswith("#")]


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def seed_aerodromes(db: Session):
    """Lotniska (airports.csv z OurAirports, elewacja z AIP albo z lotniska.dlapilota.pl), pasy i częstotliwości z AIP
    (runways.csv w metrach, frequencies.csv z godzinami i uwagą, ze źródłem w każdym wierszu) oraz pomoce nawigacyjne
    (navaids.csv). Pasy i częstotliwości lotniska, którego nie ma w airports.csv (np. po aktualizacji z OurAirports),
    pomijamy z ostrzeżeniem: klucz obcy nie może zatrzymać startu aplikacji."""
    known = set()
    for a in _csv("airports.csv"):
        db.add(Aerodrome(icao=a["ident"], name=a["name"], kind=a["type"], lat=float(a["latitude_deg"]),
                         lon=float(a["longitude_deg"]), elevation_ft=_f(a["elevation_ft"]),
                         city=a["municipality"] or None, iata=a["iata_code"] or None))
        known.add(a["ident"])
    db.flush()

    def orphan(name: str, r: dict) -> bool:
        if r["airport_ident"] in known:
            return False
        log.warning("%s: lotniska %s nie ma w airports.csv, pomijam wiersz", name, r["airport_ident"])
        return True

    for r in _csv("runways.csv"):
        if orphan("runways.csv", r):
            continue
        common = {"aerodrome_icao": r["airport_ident"], "surface": r["surface"] or None,
                  "length_m": _f(r["length_m"]), "width_m": _f(r["width_m"])}
        for end, other in (("le", "he"), ("he", "le")):
            if r[f"{end}_ident"]:
                db.add(Runway(designator=r[f"{end}_ident"], opposite=r[f"{other}_ident"] or None,
                              heading_true=_f(r[f"{end}_heading_degT"]), lat=_f(r[f"{end}_latitude_deg"]),
                              lon=_f(r[f"{end}_longitude_deg"]), **common))
    for fq in _csv("frequencies.csv"):
        if orphan("frequencies.csv", fq):
            continue
        db.add(Frequency(aerodrome_icao=fq["airport_ident"], kind=fq["service"], description=fq["callsign"] or None,
                         mhz=fq["frequency_mhz"], hours=fq["hours"] or None, note=fq.get("note") or None,
                         source=fq["source"] or None))
    for n in _csv("navaids.csv"):
        khz = _f(n["frequency_khz"])
        freq = None if khz is None else (f"{khz / 1000:.3f}" if n["type"] in ("VOR", "VOR-DME", "VORTAC", "DME")
                                         else f"{khz:g}")
        db.add(NavPoint(ident=n["ident"], kind=n["type"], name=n["name"], frequency=freq,
                        lat=float(n["latitude_deg"]), lon=float(n["longitude_deg"]), source="ourairports"))


def import_aircraft(db: Session, force: bool = False) -> list[dict]:
    """AIRCRAFT od nowa: jeden rekord na oznaczenie typu z data/import/ICAO_Aircraft.json, osiągi z wersji typu
    w data/seed/aircraft.csv (aircraft_json.build_aircraft). Przebudowa, gdy zmienił się któryś z tych plików (ImportLog
    "aircraft/<plik>"), tabela jest pusta albo force. Baza sprzed 0.12.5 (typy z aircraft.csv jako osobne wersje i plik
    json w ImportLog pod własną nazwą) nie ma kluczy "aircraft/", więc przebudowuje się przy pierwszym starcie."""
    files = sorted(p for p in IMPORT_DIR.iterdir() if p.is_file() and p.name.lower().endswith(AIRCRAFT_JSON)) \
        if IMPORT_DIR.is_dir() else []
    if not files:
        log.warning("Brak pliku ICAO_Aircraft.json w %s: lista AIRCRAFT bez zmian", IMPORT_DIR)
        return []
    perf = settings.seed_dir / "aircraft.csv"
    stamps = {f"aircraft/{p.name}": p.stat().st_mtime for p in files}
    stamps["aircraft/aircraft.csv"] = perf.stat().st_mtime if perf.exists() else 0.0
    logged = {i.filename: i.mtime for i in db.scalars(select(ImportLog).where(ImportLog.filename.like("aircraft/%")))}
    if logged == stamps and not force and db.scalar(select(func.count()).select_from(AircraftType)):
        return []
    t0 = time.time()
    try:
        res = build_aircraft(db, files, _csv("aircraft.csv"))
    except Exception as exc:  # zły plik nie może zablokować startu aplikacji: zostaje poprzednia lista
        db.rollback()
        log.exception("Import typów AIRCRAFT nieudany")
        res = {"error": str(exc)}
    log.info("Import AIRCRAFT %s: %s (%.1fs)", ", ".join(stamps), res, time.time() - t0)
    # wpisy dawnego importu pliku json (pod nazwą pliku) i plików, których już nie ma
    db.execute(delete(ImportLog).where(or_(ImportLog.filename.like("aircraft/%"),
                                           func.lower(ImportLog.filename).like(f"%{AIRCRAFT_JSON}"))))
    # nieudany import zapisujemy z mtime=0, żeby przy kolejnym starcie spróbować ponownie
    for name, mtime in stamps.items():
        db.add(ImportLog(filename=name, mtime=0 if "error" in res else mtime, result=str(res)))
    db.commit()
    return [{"file": ", ".join(p.name for p in files), **res}]


def _upgrade_aircraft_table():
    """Tabela typów z innymi kolumnami (sprzed 0.12.5: wiele wersji na typ, bez WTG i zakresów osiągów) jest tworzona
    od nowa, a import_aircraft wypełnia ją z ICAO_Aircraft.json. Reszta bazy zostaje."""
    insp = inspect(engine)
    if not insp.has_table(AircraftType.__tablename__):
        return
    have = {c["name"] for c in insp.get_columns(AircraftType.__tablename__)}
    if have != set(AircraftType.__table__.columns.keys()):
        log.info("Nowa struktura tabeli %s: lista AIRCRAFT od nowa", AircraftType.__tablename__)
        AircraftType.__table__.drop(engine)


def seed_callsigns(db: Session):
    for r in _csv("callsigns.csv"):
        db.merge(Callsign(source="seed", **r))


def register_docs(db: Session):
    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    known = set(db.scalars(select(Document.filename)))
    for p in sorted(settings.docs_dir.glob("**/*.pdf")):
        rel = p.relative_to(settings.docs_dir).as_posix()
        if rel in known:
            continue
        stem = p.stem.upper()
        cat = "ICAO" if stem.startswith(("DOC", "ICAO")) else ("EUROCONTROL" if "EUROCONTROL" in stem else "INNE")
        if "/" in rel:
            cat = rel.split("/")[0].upper()
        db.add(Document(title=p.stem.replace("_", " ").replace("-", " "), category=cat, filename=rel))
    # usuń wpisy, których pliki zniknęły
    for d in db.scalars(select(Document)).all():
        if not (settings.docs_dir / d.filename).exists():
            db.delete(d)
    db.commit()


def _import_file(db: Session, p: Path, fn, name: str, force: bool) -> dict | None:
    """Import jednego pliku, jeśli zmienił się od ostatniego razu (ImportLog wg nazwy `name`)."""
    mtime = p.stat().st_mtime
    logged = db.get(ImportLog, name)
    if logged and logged.mtime == mtime and not force:
        return None
    t0 = time.time()
    try:
        res = fn(db, p)
    except Exception as exc:  # jeden zły plik nie może zablokować startu aplikacji
        db.rollback()
        log.exception("Import %s nieudany", name)
        res = {"error": str(exc)}
    log.info("Import %s: %s (%.1fs)", name, res, time.time() - t0)
    # nieudany import zapisujemy z mtime=0, żeby przy kolejnym starcie spróbować ponownie
    db.merge(ImportLog(filename=name, mtime=0 if "error" in res else mtime, result=str(res)))
    db.commit()
    return {"file": name, **res}


def import_neighbours(db: Session, force: bool = False) -> list[dict]:
    """Stanowiska z plików .ese sąsiadów z data/import/neighbours/; stanowiska pakietów, których pliku już nie ma,
    usuwamy (ich sektory zostają w sectors.geojson do ponownego uruchomienia generatora)."""
    files = sorted(p for p in NB_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".ese") if NB_DIR.is_dir() else []
    results = [r for p in files if (r := _import_file(db, p, import_nb_ese, f"neighbours/{p.name}", force))]
    keys = {k for p in files if (k := source_key(p))}
    db.execute(delete(NbPosition).where(NbPosition.source.not_in(keys)))
    # zapomnij usunięte pliki: przywrócony plik (z tą samą datą modyfikacji) wczyta się ponownie
    db.execute(delete(ImportLog).where(ImportLog.filename.like("neighbours/%"),
                                       ImportLog.filename.not_in([f"neighbours/{p.name}" for p in files])))
    db.commit()
    return results


def import_sectors(db: Session, force: bool = False) -> list[dict]:
    """Sektory z data/seed/sectors.geojson, gdy plik się zmienił (też po ręcznej poprawce). Bez pliku: bez sektorów."""
    path, name = geojson_path(), f"seed/{FILENAME}"
    if not path.is_file():
        log.warning("Brak pliku %s: sektory EPWW i sąsiadów puste", path)
        db.execute(delete(Sector))
        db.execute(delete(NbSector))
        db.execute(delete(ImportLog).where(ImportLog.filename == name))
        db.commit()
        return []
    res = _import_file(db, path, import_sectors_geojson, name, force)
    # nowy plik .ese bez ponownego wygenerowania: stanowiska byłyby już z nowego pliku, a sektory (i ID stanowisk
    # w ich OWNER) ze starego; build obrazu Dockera przerywa wtedy --check, tu zostaje ostrzeżenie w logu
    if problems := stale(path):
        log.warning("%s nie pasuje do plików .ese albo generatora (%s): uruchom %s", FILENAME, "; ".join(problems),
                    COMMAND)
    return [res] if res else []


def import_user_files(db: Session, force: bool = False) -> list[dict]:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    files = [p for p in IMPORT_DIR.iterdir() if p.is_file()]
    for suffix, fn in IMPORTERS:
        for p in sorted(files):
            if not p.name.lower().endswith(suffix):
                continue
            if suffix == ".sct" and p.name.lower().endswith(".sct2"):
                continue
            if res := _import_file(db, p, fn, p.name, force):
                results.append(res)
    return results + import_aircraft(db, force) + import_sectors(db, force) + import_neighbours(db, force)


def _check_schema():
    """Baza ze starszej wersji aplikacji (inne kolumny) jest usuwana i budowana od nowa."""
    with engine.connect() as conn:
        version = conn.exec_driver_sql("PRAGMA user_version").scalar() if engine.dialect.name == "sqlite" else None
    if version is not None and version != SCHEMA_VERSION:
        if version:
            log.info("Zmiana struktury bazy (%s -> %s): przebudowa bazy", version, SCHEMA_VERSION)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")


def init_db(force: bool = False) -> list[dict]:
    _check_schema()
    _upgrade_aircraft_table()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if force:
            for model in (Runway, Frequency, Aerodrome, AircraftType, Callsign, ImportLog):
                db.execute(delete(model))
            db.execute(delete(NavPoint).where(NavPoint.source == "ourairports"))
            db.commit()
        if not db.scalar(select(func.count()).select_from(Aerodrome)):
            seed_aerodromes(db)
        if not db.scalar(select(func.count()).select_from(Callsign)):
            seed_callsigns(db)
        db.commit()
        results = import_user_files(db, force=force)
        register_docs(db)
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for r in init_db(force="--force" in sys.argv):
        print(r)
