"""AIRCRAFT: przyciski producentów (?maker=) z dopasowaniem różnych zapisów nazwy producenta.
0.13.1 (issue #25): "na górze wyświetlaj AIRBUS, BOEING, BOMBARDIER, EMBRAER, GA (czyli Pilatusy, Diamondy, Cessny, Piper,
AT3, Robinson, Bell, Tecnam)". Pięć kluczy; dawne mcdonnell, atr i cessna to 400 (Cessna jest w GA)."""
import os
import tempfile
from collections import Counter

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.routers.aircraft import MAKERS, maker_matches  # noqa: E402


@pytest.mark.parametrize("key, manufacturer, model, icao", [
    ("airbus", "Airbus", "A320neo", "A20N"),
    ("airbus", "AIRBUS INDUSTRIE", "A300B4", "A30B"),
    ("airbus", "Airbus Helicopters", "EC135 / H135", "EC35"),
    ("airbus", "AIRBUS", "A-220-300", "BCS3"),               # A220 (dawniej Bombardier CSeries) zostaje w AIRBUS
    ("boeing", "The Boeing Company", "737-800", "B738"),
    ("boeing", "Boeing Defense, Space & Security", "P-8 Poseidon", "P8"),
    ("boeing", "BELL-BOEING", "V-22 Osprey", "V22"),
    ("embraer", "EMBRAER S.A.", "ERJ-190-200", "E195"),
    # Bombardier z Canadairem, Learjetem (też Gates Learjet) i Dash 8 (w bazie De Havilland Canada, po kodzie ICAO)
    ("bombardier", "BOMBARDIER", "BD-700 Global 6000", "GL6T"),
    ("bombardier", "Bombardier Aerospace", "Challenger 350", "CL35"),
    ("bombardier", "CANADAIR", "CL-600 Regional Jet CRJ-900", "CRJ9"),
    ("bombardier", "LEARJET", "45", "LJ45"),
    ("bombardier", "GATES LEARJET", "35", "LJ35"),
    ("bombardier", "DE HAVILLAND CANADA", "DHC-8-400 Dash 8", "DH8D"),
    ("bombardier", "DE HAVILLAND CANADA", "DHC-8-100 Dash 8", "DH8A"),
    # GA: Pilatus, Diamond, Cessna, Piper, Aero AT-3 (kod AAT3), Robinson, Bell, Tecnam
    ("ga", "PILATUS", "PC-12", "PC12"),
    ("ga", "DIAMOND", "DA-40 Diamond Star", "DA40"),
    ("ga", "Diamond Aircraft Industries", "DA-42 Twin Star", "DA42"),
    ("ga", "CESSNA", "172 Cutlass/Skyhawk", "C172"),
    ("ga", "Reims-Cessna", "F406 Caravan II", "F406"),
    ("ga", "Textron Aviation", "Citation Latitude", "C68A"),
    ("ga", "Textron Aviation", "Cessna 208 Caravan", "C208"),
    ("ga", "PIPER", "PA-28-140/150/151/160/161/180 Cherokee", "P28A"),
    ("ga", "AERO", "AT-3", "AAT3"),
    ("ga", "ROBINSON", "R-44 Astro/Raven/Clipper", "R44"),
    ("ga", "BELL", "206 JetRanger", "B06"),
    ("ga", "Bell Helicopter Textron", "407", "B407"),
    ("ga", "TECNAM", "P-2002 Sierra", "SIRA"),
])
def test_maker_variants_match(key, manufacturer, model, icao):
    assert maker_matches(key, manufacturer, model, icao)


@pytest.mark.parametrize("key, manufacturer, model, icao", [
    ("airbus", "Bombardier", "CRJ-900", "CRJ9"),
    ("boeing", "Boeingx", "?", "ZZZZ"),
    ("embraer", None, None, None),
    # nie Bombardier: inne typy De Havilland Canada, A220 w bazie jako AIRBUS
    ("bombardier", "DE HAVILLAND CANADA", "DHC-6 Twin Otter", "DHC6"),
    ("bombardier", "DE HAVILLAND", "DH-104 Dove", "DOVE"),
    ("bombardier", "AIRBUS", "A-220-300", "BCS3"),
    # nie GA: "AT3" w bazie to wojskowy AIDC AT-3, AT3P / AT3T to Air Tractor, inne typy producenta AERO
    ("ga", "AIDC", "AT-3 Tzu-Chung", "AT3"),
    ("ga", "AIR TRACTOR", "AT-302/400/402", "AT3T"),
    ("ga", "AIR TRACTOR", "AT-301/302", "AT3P"),
    ("ga", "AERO", "L-39/139 Albatros", "L39"),
    ("ga", "AERO COMMANDER", "500", "AC50"),
    ("ga", "AERO-ASTRA", "?", "ZZZZ"),
    # Bell tylko sam BELL: Bell-Boeing (V-22, w BOEING), Bell-Agusta i Bellanca poza GA
    ("ga", "BELL-BOEING", "V-22 Osprey", "V22"),
    ("ga", "BELL-AGUSTA", "AB-139", "A139"),
    ("ga", "BELLANCA", "7GCBC Citabria", "CH7B"),
    # Diamond tylko po producencie
    ("ga", "MITSUBISHI", "MU-300 Diamond", "MU30"),
    ("ga", "Piperx", "?", "ZZZZ"),
    ("ga", None, None, None),
])
def test_maker_lookalikes_do_not_match(key, manufacturer, model, icao):
    assert not maker_matches(key, manufacturer, model, icao)


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_five_makers_in_button_order():
    assert list(MAKERS) == ["airbus", "boeing", "bombardier", "embraer", "ga"]


def test_maker_filter_endpoint(client):
    airbus = client.get("/api/aircraft?maker=airbus&limit=500").json()
    icaos = {a["icao"] for a in airbus}
    assert {"A320", "A20N", "A359", "BCS3"} <= icaos and all("airbus" in a["manufacturer"].lower() for a in airbus)
    assert [a["icao"] for a in airbus] == sorted(a["icao"] for a in airbus)

    # producent łączy się z pozostałymi filtrami i limitem
    heavy = client.get("/api/aircraft?maker=boeing&wtc=H").json()
    assert heavy and all(a["wtc"] == "H" for a in heavy) and "B744" in {a["icao"] for a in heavy}
    assert {a["icao"] for a in client.get("/api/aircraft?maker=embraer&q=E19").json()} >= {"E190", "E195"}
    assert len(client.get("/api/aircraft?maker=boeing&limit=5").json()) == 5


def test_bombardier_endpoint(client):
    rows = client.get("/api/aircraft?maker=bombardier&limit=500").json()
    icaos = [a["icao"] for a in rows]
    assert icaos == sorted(icaos)
    assert {"CRJ9", "CRJX", "CL60", "GL7T", "LJ45", "LJ35", "DH8A", "DH8D"} <= set(icaos)
    # A220 w AIRBUS, Twin Otter to nie Dash 8
    assert "BCS3" not in icaos and "BCS1" not in icaos and "DHC6" not in icaos
    assert set(Counter(a["manufacturer"] for a in rows)) == {"BOMBARDIER", "CANADAIR", "LEARJET", "GATES LEARJET",
                                                             "DE HAVILLAND CANADA"}
    assert {a["icao"] for a in rows if a["manufacturer"] == "DE HAVILLAND CANADA"} == {"DH8A", "DH8B", "DH8C", "DH8D"}


def test_ga_endpoint(client):
    rows = client.get("/api/aircraft?maker=ga&limit=2000").json()
    icaos = [a["icao"] for a in rows]
    assert icaos == sorted(icaos)
    by = Counter(a["manufacturer"] for a in rows)
    assert set(by) == {"PILATUS", "DIAMOND", "CESSNA", "PIPER", "AERO", "ROBINSON", "BELL", "TECNAM"}
    # z producenta AERO tylko Aero AT-3
    assert [a["icao"] for a in rows if a["manufacturer"] == "AERO"] == ["AAT3"]
    assert {"C172", "C208", "C68A", "P28A", "PC12", "DA40", "R44", "B06", "SIRA", "AAT3"} <= set(icaos)
    assert not {"AT3", "AT3P", "AT3T", "V22", "A139", "MU30", "L39"} & set(icaos)
    # pełne grupy producentów: wszystkie typy CESSNA, PIPER… z bazy
    for name in ("PILATUS", "DIAMOND", "CESSNA", "PIPER", "ROBINSON", "BELL", "TECNAM"):
        found = client.get("/api/aircraft", params={"q": name, "limit": 2000}).json()
        assert by[name] == sum(a["manufacturer"] == name for a in found) > 0, name
    assert len(rows) == sum(by.values()) and by["CESSNA"] > 50 and by["PIPER"] > 20
    # wyszukiwanie w obrębie GA
    assert {a["icao"] for a in client.get("/api/aircraft?maker=ga&q=C17").json()} >= {"C170", "C172", "C177"}


@pytest.mark.parametrize("old", ["mcdonnell", "atr", "cessna", "fokker"])
def test_removed_and_unknown_makers_are_400(client, old):
    r = client.get(f"/api/aircraft?maker={old}")
    assert r.status_code == 400 and "Unknown manufacturer" in r.json()["detail"]
    assert "airbus, boeing, bombardier, embraer, ga" in r.json()["detail"]
