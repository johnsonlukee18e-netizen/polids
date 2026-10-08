"""AIRCRAFT: przyciski producentów (?maker=) z dopasowaniem różnych zapisów nazwy producenta."""
import os
import tempfile

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
    ("boeing", "The Boeing Company", "737-800", "B738"),
    ("boeing", "Boeing Defense, Space & Security", "P-8 Poseidon", "P8"),
    ("embraer", "EMBRAER S.A.", "ERJ-190-200", "E195"),
    ("mcdonnell", "McDonnell-Douglas", "MD-11", "MD11"),
    ("mcdonnell", "Mcdonnell Douglas", "MD-82", "MD82"),
    ("mcdonnell", "Mc Donnell Douglas", "DC-10", "DC10"),
    ("mcdonnell", "Douglas", "DC-3", "DC3"),
    ("atr", "ATR", "72-600 (72-212A)", "AT76"),
    ("atr", "Aerospatiale/Alenia (ATR)", "42-500", "AT45"),
    ("atr", "Aérospatiale-Alenia", "ATR 72", "XXXX"),
    ("atr", "Avions de Transport Régional", "72-500", "XXXX"),
    ("atr", "", "ATR72-600", "XXXX"),
    ("atr", "Aerospatiale", "ATR-42", "XXXX"),
    ("atr", "Aerospatiale", "42-300", "AT43"),  # sam kod ICAO wystarcza
    ("cessna", "Cessna", "172 Skyhawk", "C172"),
    ("cessna", "Reims-Cessna", "F406 Caravan II", "F406"),
    ("cessna", "Textron Aviation", "Citation Latitude", "C68A"),
    ("cessna", "Textron Aviation", "Cessna 208 Caravan", "C208"),
])
def test_maker_variants_match(key, manufacturer, model, icao):
    assert maker_matches(key, manufacturer, model, icao)


@pytest.mark.parametrize("key, manufacturer, model, icao", [
    ("atr", "Matra", "Matra-Moynet Jupiter", "M360"),       # "atr" w środku słowa
    ("atr", "Air Tractor", "AT-802", "AT8T"),              # podobny kod ICAO, inny producent
    ("atr", "Aerosamara", "Katran", "KATR"),
    ("atr", "Aerospatiale", "SA330 Puma", "PUMA"),         # Aerospatiale bez Alenii to nie ATR
    ("airbus", "Bombardier", "CRJ-900", "CRJ9"),
    ("boeing", "Boeingx", "?", "ZZZZ"),
    ("mcdonnell", "Donnelly", "?", "ZZZZ"),
    ("cessna", "Piper", "PA-28 Cherokee", "P28A"),
    ("embraer", None, None, None),
])
def test_maker_lookalikes_do_not_match(key, manufacturer, model, icao):
    assert not maker_matches(key, manufacturer, model, icao)


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_maker_filter_endpoint(client):
    assert set(MAKERS) == {"airbus", "boeing", "embraer", "mcdonnell", "atr", "cessna"}
    airbus = client.get("/api/aircraft?maker=airbus&limit=500").json()
    icaos = {a["icao"] for a in airbus}
    assert {"A320", "A20N", "A359", "BCS3"} <= icaos and all("airbus" in a["manufacturer"].lower() for a in airbus)
    assert [a["icao"] for a in airbus] == sorted(a["icao"] for a in airbus)

    atr = client.get("/api/aircraft?maker=ATR").json()
    assert {"AT45", "AT76"} <= {a["icao"] for a in atr}
    assert not any(a["manufacturer"] in ("Air Tractor", "Matra") for a in atr)

    mcd = {a["icao"] for a in client.get("/api/aircraft?maker=mcdonnell&limit=500").json()}
    assert {"MD11", "MD82", "DC10", "DC93", "F4"} <= mcd

    cessna = client.get("/api/aircraft?maker=cessna&limit=500").json()
    assert {"C172", "C208"} <= {a["icao"] for a in cessna}
    assert all("cessna" in a["manufacturer"].lower() for a in cessna)

    # producent łączy się z pozostałymi filtrami i limitem
    heavy = client.get("/api/aircraft?maker=boeing&wtc=H").json()
    assert heavy and all(a["wtc"] == "H" for a in heavy) and "B744" in {a["icao"] for a in heavy}
    assert {a["icao"] for a in client.get("/api/aircraft?maker=embraer&q=E19").json()} >= {"E190", "E195"}
    assert len(client.get("/api/aircraft?maker=boeing&limit=5").json()) == 5

    r = client.get("/api/aircraft?maker=fokker")
    assert r.status_code == 400 and "Nieznany producent" in r.json()["detail"]
