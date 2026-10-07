"""Mapa QNH regionalnego: plik data/seed/qnh_regions.json i endpoint /api/meteo/qnh-regions."""
import json
import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import DATA_DIR, settings  # noqa: E402
from backend.app.routers import meteo  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

CFG = json.loads((settings.seed_dir / "qnh_regions.json").read_text("utf-8"))
# TMA/MTMA z mapy vAWOS (plus opisy BELOW TMA dla EPMB i EPDE)
TMA_ICAOS = {"EPGD", "EPSN", "EPSC", "EPMI", "EPBY", "EPSY", "EPPO", "EPPW", "EPZG", "EPWA", "EPMM", "EPLL", "EPLK",
             "EPRA", "EPLB", "EPWR", "EPKT", "EPKK", "EPRZ", "EPMB", "EPDE"}


def fake_qnh(icao: str) -> int:
    """Różne, powtarzalne QNH dla każdego lotniska (1000–1029 hPa)."""
    return 1000 + sum(map(ord, icao)) % 30


async def fake_metars(icaos):
    return {i: f"{i} 051630Z 28015KT 9999 FEW030 12/05 Q{fake_qnh(i)} NOSIG" for i in icaos if i != "EPBY"}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def _rings(g):
    assert g["type"] in ("Polygon", "MultiPolygon")
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    return [ring for poly in polys for ring in poly]


def test_json_valid():
    regions, tmas = CFG["regions"], CFG["tmas"]
    assert [r["id"] for r in regions] == list(range(1, 18))
    for r in regions:
        assert r["airports"] and all(len(a) == 4 and a.isupper() for a in r["airports"])
        assert len(r["num"]) == 2 and ("label" in r or r.get("band"))
        for ring in _rings(r["geometry"]):
            assert len(ring) >= 4 and ring[0] == ring[-1]
            assert all(13 < lon < 26 and 48 < lat < 56 for lon, lat in ring)
    assert {t["icao"] for t in tmas} == TMA_ICAOS and len(tmas) == len(TMA_ICAOS)
    for t in tmas:
        assert t["name"].startswith(("TMA ", "MTMA ")) and t["below"] in ("TMA", "MTMA", "TMA/MTMA")
        for k in ("off", "cap"):
            assert k not in t or (len(t[k]) == 2 and all(isinstance(v, int) and abs(v) <= 160 for v in t[k]))
        # bez etykiety (EPMB, EPDE jak w vAWOS) musi zostać chociaż opis BELOW
        assert t.get("box", True) or t.get("cap")
    # objaśnienie dla użytkownika bez nazw kluczy JSON (te są w "_uwaga")
    assert CFG["note"] and "'" not in CFG["note"]


def _inside(lon, lat, ring):
    """Punkt w wielokącie (promień w prawo)."""
    out = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            out = not out
    return out


def test_regions_tile_fir():
    """Rejony 1-14 dzielą FIR EPWW bez dziur i nakładania; pasy 15-17 leżą przy granicy wschodniej (jak w PANDORZE),
    podzielone na 53°N i 51°N (tak jak pomarańczowe linie w vAWOS)."""
    fc = json.loads((settings.seed_dir / "vatspy_firs.geojson").read_text("utf-8"))
    fir = _rings(next(f["geometry"] for f in fc["features"] if f["properties"].get("id") == "EPWW"))
    rings = {r["id"]: _rings(r["geometry"]) for r in CFG["regions"]}
    for i in range(141):
        for j in range(91):
            lon, lat = 13.5137 + i * 0.0731, 48.8113 + j * 0.0719
            n = sum(any(_inside(lon, lat, ring) for ring in rings[k]) for k in range(1, 15))
            assert n == any(_inside(lon, lat, ring) for ring in fir), (lon, lat, n)
    for k, (south, north) in {15: (53, 55), 16: (51, 53), 17: (49, 51)}.items():
        pts = [p for ring in rings[k] for p in ring]
        assert min(lon for lon, _ in pts) > 23.4 and max(lon for lon, _ in pts) < 25.5
        assert abs(min(lat for _, lat in pts) - south) < 0.1 and abs(max(lat for _, lat in pts) - north) < 0.1


def test_endpoint_regions_and_tmas(client, monkeypatch):
    monkeypatch.setattr(meteo, "get_metars", fake_metars)
    q = client.get("/api/meteo/qnh-regions").json()
    assert q["error"] is None and q["fir"]["type"] in ("Polygon", "MultiPolygon") and q["note"] == CFG["note"]
    assert len(q["regions"]) == 17
    for r in q["regions"]:
        vals = [fake_qnh(a) for a in r["airports"] if a != "EPBY"]
        # QNH rejonu = najniższe QNH z lotnisk rejonu
        assert r["qnh"] == (min(vals) if vals else None) and r["max"] == (max(vals) if vals else None)
        assert [s["icao"] for s in r["stations"]] == r["airports"]
    assert next(r for r in q["regions"] if r["id"] == 3)["qnh"] is None   # tylko EPBY, bez METAR-u
    assert len(q["tmas"]) == len(TMA_ICAOS)
    for t in q["tmas"]:
        assert t["name"] and t["icao"] in TMA_ICAOS and "sct" not in t and "ese" not in t
        assert t["qnh"] == (None if t["icao"] == "EPBY" else fake_qnh(t["icao"]))
        assert "area" in t and "outline" in t and "lat" in t and "lon" in t
    ads = {a["icao"]: a for a in q["aerodromes"]}
    assert ads and all(a["metar"] for i, a in ads.items() if i in TMA_ICAOS)
    tma = {t["icao"]: t for t in q["tmas"]}
    assert tma["EPWA"]["lat"] == pytest.approx(52.17, abs=0.05)
    if list((DATA_DIR / "import").glob("*.sct")):
        # granice TMA z plików sektorowych: obszar albo linie, MTMA bez danych tylko z etykietą przy lotnisku
        for i in ("EPGD", "EPWA", "EPKK", "EPRZ"):
            assert tma[i]["area"] or tma[i]["outline"]
        for ring in _rings(tma["EPWA"]["area"] or {"type": "MultiPolygon", "coordinates": []}):
            assert all(19 < lon < 23 and 51 < lat < 53.5 for lon, lat in ring)
        assert tma["EPMM"]["area"] is None and tma["EPMM"]["outline"] is None
        # Katowice: własny obszar (sektory odlotowe EPKT) do podświetlenia, rysowany w obrębie TMA Kraków
        for ring in _rings(tma["EPKT"]["area"]):
            assert all(18.3 < lon < 19.8 and 50.2 < lat < 50.8 for lon, lat in ring)


def test_endpoint_without_metar(client, monkeypatch):
    async def down(icaos):
        raise UpstreamError("brak sieci")

    monkeypatch.setattr(meteo, "get_metars", down)
    q = client.get("/api/meteo/qnh-regions").json()
    assert "brak sieci" in q["error"]
    assert all(r["qnh"] is None for r in q["regions"]) and all(t["qnh"] is None for t in q["tmas"])


def test_faces_and_chains():
    sq = [[0, 0], [0, 1], [1, 1], [1, 0]]
    segs = [[sq[i], sq[(i + 1) % 4]] for i in range(4)] + [[[1, 1], [2, 2]]]   # kwadrat i "ogonek"
    faces = meteo._faces(segs)
    assert len(faces) == 1 and set(faces[0]) == {tuple(p) for p in sq}
    chains = meteo._chains(segs)
    assert sorted(len(c) for c in chains) in ([2, 5], [6])
    assert sum(len(c) - 1 for c in chains) == len(segs)
