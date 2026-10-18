"""0.12.5 (issue #18, AIRCRAFT): "czemu jest tyle typów A300 … Wykorzystaj tylko dane z pliku ICAO Aircraft json".
Lista typów = jeden rekord na oznaczenie typu z data/import/ICAO_Aircraft.json i nic poza nim; osiągi, których plik nie
ma (silniki, MLW, pułap, Vmo, Mmo), z wersji typu w data/seed/aircraft.csv jako zakres od–do w tym samym rekordzie.
Baza zbudowana od nowa i baza sprzed 0.12.5 (wiele wersji na typ, plik json w ImportLog) kończą z tą samą listą."""
import csv
import json
import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select, text, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import DATA_DIR, settings  # noqa: E402
from backend.app.database import Base  # noqa: E402
from backend.app.importers import seed  # noqa: E402
from backend.app.importers.aircraft_json import BOUNDS, parse_icao_aircraft, performance, plausible  # noqa: E402
from backend.app.importers.sct import read_text  # noqa: E402
from backend.app.models import AircraftType, ImportLog  # noqa: E402
from backend.app.services.photos import photo_query  # noqa: E402

ICAO_JSON = DATA_DIR / "import" / "ICAO_Aircraft.json"
DESIGNATORS = {r["ICAO"].strip().upper() for r in json.loads(read_text(ICAO_JSON))}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def icaos(client, **params):
    return [a["icao"] for a in client.get("/api/aircraft", params={"limit": 2000, **params}).json()]


def test_list_is_exactly_the_icao_json(client):
    # wszystkie oznaczenia z pliku, każde raz, i żadnych typów spoza pliku (np. szybowce z aircraft.csv)
    assert client.get("/api/status").json()["counts"]["aircraft_types"] == len(DESIGNATORS) == 2821
    every = [c for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in icaos(client, prefix=letter)]
    assert len(every) == len(set(every)) == len(DESIGNATORS) and set(every) == DESIGNATORS
    csv_only = {r["icao"] for r in csv.DictReader(open(settings.seed_dir / "aircraft.csv", encoding="utf-8"))}
    assert {"AS21", "DG80", "LS8"} <= csv_only - DESIGNATORS
    assert not {"AS21", "DG80", "LS8"} & set(every)


def test_a300_is_one_record_per_designator_with_ranges(client):
    # dawniej 14 wersji A300 (B1, B2-100, B4-600R…); teraz A306 i A30B po razie, nazwy i wymiary z pliku ICAO
    a30 = client.get("/api/aircraft", params={"q": "A30"}).json()
    codes = [a["icao"] for a in a30]
    assert codes[:2] == ["A306", "A30B"] and len(codes) == len(set(codes))  # kod od "A30" przed np. PA30
    assert codes.index("PA30") > codes.index("A30B")
    a306 = a30[0]
    assert (a306["manufacturer"], a306["model"], a306["description"]) == ("AIRBUS", "A-300(B4/C4/F4)-600", "L2J")
    assert (a306["wtc"], a306["wtg"], a306["recat"], a306["iata"]) == ("H", "C", "C", "AB6")
    assert (a306["wingspan"], a306["length"], a306["mtow"]) == (44.84, 54.1, 171700)
    # osiągi spoza pliku: MLW wersji -600 / -600R jako zakres, reszta wspólna dla wersji
    assert (a306["mlw"], a306["mlw_max"], a306["ceiling_ft"], a306["ceiling_ft_max"]) == (138000, 140000, 40000, None)
    assert (a306["engine_count"], a306["engine_type"], a306["vmo_kt"], a306["mmo"]) == (2, "turbofan", 335, 0.82)
    a30b = a30[1]
    assert (a30b["vmo_kt"], a30b["vmo_kt_max"], a30b["mmo"], a30b["mmo_max"]) == (345, 360, 0.82, 0.86)
    # "A300" (bez myślnika) znajduje nazwy ICAO "A-300…"; dokładny kod ICAO zawsze pierwszy
    assert {"A306", "A30B", "A3ST"} <= set(icaos(client, q="A300"))
    assert icaos(client, q="b738")[0] == "B738" and {"A320", "A20N"} <= set(icaos(client, q="airbus a320"))


def test_performance_from_variants():
    desc = {"A30B": "L2J", "EC35": "H2T", "GLID": None, "C08T": "LCT"}
    rows = [
        {"icao": "A30B", "aircraft_type": "airplane", "engine_type": "turbofan", "engine_count": "2", "mlw": "122000",
         "ceiling_ft": "40000", "vmo_kt": "360", "mmo": "0.86"},
        {"icao": "A30B", "aircraft_type": "airplane", "engine_type": "turbofan", "engine_count": "2", "mlw": "136000",
         "ceiling_ft": "40000", "vmo_kt": "345", "mmo": ""},
        # ten sam kod ICAO w aircraft-database.com, ale inny statek (EC-135 = Boeing C-135): nie pasuje do opisu H2T
        {"icao": "EC35", "aircraft_type": "airplane", "engine_type": "turbofan", "engine_count": "4"},
        {"icao": "EC35", "aircraft_type": "helicopter", "engine_type": "turboshaft", "engine_count": "1",
         "ceiling_ft": "20000"},
        {"icao": "GLID", "aircraft_type": "glider", "engine_type": "none", "mlw": "500"},  # oznaczenie zbiorcze
        {"icao": "XXXX", "aircraft_type": "airplane", "mlw": "1"},  # typ spoza pliku json
    ]
    p = performance(rows, desc)
    assert p["A30B"] == {"mlw": 122000, "mlw_max": 136000, "ceiling_ft": 40000, "vmo_kt": 345, "vmo_kt_max": 360,
                         "mmo": 0.86, "engine_type": "turbofan", "engine_count": 2}
    assert p["EC35"] == {"ceiling_ft": 20000, "engine_type": "turboshaft", "engine_count": 1}
    assert set(p) == {"A30B", "EC35"}


def test_performance_skips_implausible_values():
    """Runda 14 (przegląd): 737-200C w aircraft.csv miał Vmo 0 i Mmo 350, więc B732 pokazywał "M0.82–350", a C408
    "M240". Liczby spoza granic wiarygodności (BOUNDS; MLW także względem MTOW wiersza) pomijamy."""
    desc = {"B732": "L2J", "C408": "L2T", "GA8": "L1P"}
    jet = {"icao": "B732", "aircraft_type": "airplane", "engine_type": "turbofan", "engine_count": "2", "mtow": "58105"}
    rows = [
        jet | {"mlw": "48534", "ceiling_ft": "37000", "vmo_kt": "350", "mmo": "0.82"},
        jet | {"mlw": "48534", "ceiling_ft": "37000", "vmo_kt": "0", "mmo": "350"},       # kolumny zamienione
        jet | {"mlw": "48534", "ceiling_ft": "120", "vmo_kt": "800", "mmo": "0.05"},      # pułap, Vmo, Mmo bez sensu
        {"icao": "C408", "aircraft_type": "airplane", "engine_type": "turboprop", "mtow": "8618", "mlw": "8437",
         "vmo_kt": "210", "mmo": "240"},
        {"icao": "GA8", "aircraft_type": "airplane", "engine_type": "piston", "mtow": "1814", "mlw": "114"},
    ]
    p = performance(rows, desc)
    assert p["B732"] == {"mlw": 48534, "ceiling_ft": 37000, "vmo_kt": 350, "mmo": 0.82, "engine_type": "turbofan",
                         "engine_count": 2}
    assert p["C408"] == {"mlw": 8437, "vmo_kt": 210, "engine_type": "turboprop"}
    assert "mlw" not in p["GA8"]
    assert plausible("mmo", 0.82) and not plausible("mmo", 350) and not plausible("vmo_kt", 0.82)
    assert plausible("mlw", 60781, {"mtow": "57153"}) and not plausible("mlw", 114, {"mtow": "1814"})


def test_aircraft_csv_values_are_plausible():
    """data/seed/aircraft.csv poprawiony (B732 737-200C, C408, B230, GA8): każda liczba osiągów w granicach."""
    bad = [(r["icao"], r["model"], k, r[k]) for r in csv.DictReader(open(settings.seed_dir / "aircraft.csv", encoding="utf-8"))
           for k in BOUNDS if r.get(k) and float(r[k]) > 0 and not plausible(k, float(r[k]), r)]
    assert bad == []


def test_no_merged_record_has_implausible_speeds(client):
    """Lista AIRCRAFT z bazy (seed): żaden rekord nie ma Mmo poza 0,1–1,0 ani Vmo poza 40–700 kt (także *_max)."""
    every = [a for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
             for a in client.get("/api/aircraft", params={"limit": 2000, "prefix": letter}).json()]
    assert len(every) == len(DESIGNATORS)
    bad = [(a["icao"], k, a[k]) for a in every for k in ("mmo", "mmo_max", "vmo_kt", "vmo_kt_max", "ceiling_ft",
                                                        "ceiling_ft_max", "mlw", "mlw_max")
           if a.get(k) is not None and not BOUNDS[k.removesuffix("_max")][0] <= a[k] <= BOUNDS[k.removesuffix("_max")][1]]
    assert bad == []
    rec = {a["icao"]: a for a in every}
    assert (rec["B732"]["vmo_kt"], rec["B732"]["mmo"], rec["B732"]["mmo_max"]) == (350, 0.82, None)
    assert rec["C408"]["mmo"] is None and rec["C408"]["vmo_kt"] == 210


def test_parse_icao_aircraft_fields():
    data = [{"ICAO": " a306 ", "Description": "L2J", "WTC": "H", "WTG": "C", "RECAT-EU": "C", "Wingspan": 44.84,
             "MTOW": 171700, "Use": "A", "IATA": "AB6", "IATA_cargo": "ABY", "Manufacturer": "Airbus", "Model": "A-300"},
            {"ICAO": "C08T", "Description": "LCT", "MTOW": 0, "Manufacturer": "SOLOY", "Model": "208"},
            {"ICAO": "GLID", "Description": "---", "Manufacturer": "(any manufacturer)", "Model": "Glider"},
            {"ICAO": "", "Model": "?"}, {"ICAO": "TOOLONG", "Model": "?"}]
    t = parse_icao_aircraft(json.dumps(data))
    assert list(t) == ["A306", "C08T", "GLID"]
    assert t["A306"] == {"icao": "A306", "iata": "AB6", "manufacturer": "AIRBUS", "model": "A-300", "description": "L2J",
                         "wtc": "H", "wtg": "C", "recat": "C", "wingspan": 44.84, "length": None, "height": None,
                         "mtow": 171700, "use": "A"}
    assert t["C08T"]["mtow"] is None and t["GLID"]["description"] is None  # MTOW 0 i opis "---" = brak danych


def test_photo_query_from_icao_names():
    assert photo_query("AIRBUS", "A-300(B4/C4/F4)-600") == "AIRBUS A-300-600"
    assert photo_query("BOEING", "737-800, BBJ2") == "BOEING 737-800"
    assert photo_query("CESSNA", "208 Caravan 1/(Super) Cargomaster/Grand Caravan, C-98, U-27") == "CESSNA 208 Caravan 1"


OLD_TABLE = """CREATE TABLE aircraft_types (id INTEGER PRIMARY KEY, icao VARCHAR(4), iata VARCHAR(3),
    manufacturer VARCHAR(120), model VARCHAR(120), aircraft_type VARCHAR(30), engine_type VARCHAR(30),
    engine_count INTEGER, wtc VARCHAR(1), recat VARCHAR(1), wingspan FLOAT, length FLOAT, height FLOAT, mtow FLOAT,
    mlw FLOAT, ceiling_ft FLOAT, vmo_kt FLOAT, mmo FLOAT, description VARCHAR(4), use VARCHAR(2), remarks TEXT,
    source VARCHAR(40))"""
PERF_CSV = """icao,iata,manufacturer,model,aircraft_type,engine_type,engine_count,wtc,recat,wingspan,length,height,mtow,mlw,ceiling_ft,vmo_kt,mmo
A30B,,Airbus,A300 B2-100,airplane,turbofan,2,H,C,44.83,53.61,16.72,137000,127500,40000,360,0.86
A30B,,Airbus,A300 B4-200,airplane,turbofan,2,H,C,44.83,53.61,16.72,165000,134000,40000,345,0.82
AS21,,Alexander Schleicher,ASK 21,glider,none,,L,F,17,8.35,1.55,600,600,,,
"""
JSON = [{"ICAO": "A30B", "Description": "L2J", "WTC": "H", "WTG": "C", "RECAT-EU": "C", "Wingspan": 44.8,
         "MTOW": 165000, "Manufacturer": "AIRBUS", "Model": "A-300(B2/B4/C4/F4)"},
        {"ICAO": "B738", "Description": "L2J", "WTC": "M", "WTG": "D", "RECAT-EU": "D", "Manufacturer": "BOEING",
         "Model": "737-800, BBJ2"}]


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    """Baza sprzed 0.12.5: tabela typów ze starymi kolumnami, kilka wersji A300, plik json w ImportLog pod nazwą."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[t for t in Base.metadata.sorted_tables if t.name != "aircraft_types"])
    imp, seed_dir = tmp_path / "import", tmp_path / "seed"
    imp.mkdir()
    seed_dir.mkdir()
    (imp / "ICAO_Aircraft.json").write_text("﻿" + json.dumps(JSON), encoding="utf-8")
    (seed_dir / "aircraft.csv").write_text(PERF_CSV, encoding="utf-8")
    with eng.begin() as conn:
        conn.execute(text(OLD_TABLE))
        for model in ("A300 B1", "A300 B2-100", "A300 B4-200"):
            conn.execute(text("INSERT INTO aircraft_types (icao, model, source) VALUES ('A30B', :m, 'x')"), {"m": model})
        conn.execute(text("INSERT INTO import_log (filename, mtime, result) VALUES ('ICAO_Aircraft.json', :t, '')"),
                     {"t": (imp / "ICAO_Aircraft.json").stat().st_mtime})
    monkeypatch.setattr(seed, "engine", eng)
    monkeypatch.setattr(seed, "IMPORT_DIR", imp)
    monkeypatch.setattr(settings, "seed_dir", seed_dir)
    return eng, imp, seed_dir


def test_old_database_gets_the_new_list(old_db):
    eng, imp, seed_dir = old_db
    seed._upgrade_aircraft_table()
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        assert db.scalar(select(func.count()).select_from(AircraftType)) == 0  # tabela od nowa (nowe kolumny)
        res = seed.import_aircraft(db)
        assert res == [{"file": "ICAO_Aircraft.json", "aircraft_types": 2, "with_performance": 1}]
        rows = {a.icao: a for a in db.scalars(select(AircraftType))}
        assert set(rows) == {"A30B", "B738"}  # bez wersji i bez szybowca AS21 spoza pliku json
        a = rows["A30B"]
        assert (a.model, a.mtow, a.wtg, a.mlw, a.mlw_max, a.vmo_kt, a.vmo_kt_max) == (
            "A-300(B2/B4/C4/F4)", 165000, "C", 127500, 134000, 345, 360)
        assert rows["B738"].engine_count == 2 and rows["B738"].mlw is None
        # dawny wpis pliku json zastąpiony kluczami "aircraft/"; drugi start bez zmian plików: bez importu
        assert db.get(ImportLog, "ICAO_Aircraft.json") is None
        assert {i.filename for i in db.scalars(select(ImportLog))} == {"aircraft/ICAO_Aircraft.json",
                                                                       "aircraft/aircraft.csv"}
        assert seed.import_aircraft(db) == []
        # zmiana aircraft.csv przebudowuje listę (osiągi), force też
        rows["A30B"].model = "edited"
        db.commit()
        os.utime(seed_dir / "aircraft.csv", (0, (seed_dir / "aircraft.csv").stat().st_mtime + 5))
        assert seed.import_aircraft(db)[0]["aircraft_types"] == 2
        assert db.scalar(select(AircraftType.model).where(AircraftType.icao == "A30B")) == "A-300(B2/B4/C4/F4)"
        db.execute(update(AircraftType).values(model="edited"))
        assert seed.import_aircraft(db) == [] and seed.import_aircraft(db, force=True)
        assert db.scalars(select(AircraftType.model).order_by(AircraftType.icao)).all() == [
            "A-300(B2/B4/C4/F4)", "737-800, BBJ2"]


def test_broken_json_keeps_the_previous_list(old_db):
    eng, imp, _ = old_db
    seed._upgrade_aircraft_table()
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        seed.import_aircraft(db)
        (imp / "ICAO_Aircraft.json").write_text("[{]", encoding="utf-8")
        os.utime(imp / "ICAO_Aircraft.json", (0, (imp / "ICAO_Aircraft.json").stat().st_mtime + 5))
        assert "error" in seed.import_aircraft(db)[0]
        assert db.scalar(select(func.count()).select_from(AircraftType)) == 2
        # nieudany import: mtime 0, przy następnym starcie kolejna próba
        assert db.get(ImportLog, "aircraft/ICAO_Aircraft.json").mtime == 0
        (imp / "ICAO_Aircraft.json").write_text("[]", encoding="utf-8")  # pusty plik też nie kasuje listy
        assert "error" in seed.import_aircraft(db)[0]
        assert db.scalar(select(func.count()).select_from(AircraftType)) == 2
