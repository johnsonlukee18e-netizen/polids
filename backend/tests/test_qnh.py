"""Mapa QNH regionalnego: plik data/seed/qnh_regions.json i endpoint /api/meteo/qnh-regions."""
import csv
import json
import math
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import DATA_DIR, settings  # noqa: E402
from backend.app.routers import meteo  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

CFG = json.loads((settings.seed_dir / "qnh_regions.json").read_text("utf-8"))
# obszary "BELOW TMA/MTMA QNH FROM EPxx" z mapy rejonów QNH z AIP Polska
TMA_ICAOS = {"EPGD", "EPSN", "EPSC", "EPMI", "EPBY", "EPSY", "EPPO", "EPPW", "EPZG", "EPWA", "EPMM", "EPLL", "EPLK",
             "EPRA", "EPLB", "EPWR", "EPKT", "EPKK", "EPRZ", "EPMB", "EPDE"}
BANDS = {15: (53, 90), 16: (51, 53), 17: (-90, 51)}   # pasy awaryjne: FIR podzielony równoleżnikami 53°N i 51°N
BOX_KM = 30   # ramka TMA najwyżej tyle km od swojego obszaru (gdy w obszarze nie ma miejsca)


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
        # rejony 1-14 z etykietą SEKTOR n, pasy 15-17 bez etykiety
        assert len(r["num"]) == 2 and bool(r.get("band")) == (r["id"] in BANDS) and ("label" in r) != bool(r.get("band"))
        for ring in _rings(r["geometry"]):
            assert len(ring) >= 4 and ring[0] == ring[-1]
            assert all(13 < lon < 26 and 48 < lat < 56 for lon, lat in ring)
        # numer i etykieta leżą w swoim rejonie; rejon 6 (Kłodzko) jest za wąski na ramkę, więc SEKTOR 6 stoi jak
        # w vAWOS za granicą FIR, tuż obok rejonu
        for pt in [r["num"]] + ([r["label"]] if "label" in r and r["id"] != 6 else []):
            assert any(_inside(*pt, ring) for ring in _rings(r["geometry"])), (r["id"], pt)
        if r["id"] == 6:
            assert not _inside(*r["label"], CFG["fir"]["coordinates"][0]), r["label"]
            assert _km_to_area(r["label"], r["geometry"]) < 30, r["label"]
    assert CFG["fir"]["type"] == "Polygon" and len(CFG["fir"]["coordinates"][0]) > 100
    assert {t["icao"] for t in tmas} == TMA_ICAOS and len(tmas) == len(TMA_ICAOS)
    joined = {i for t in tmas for i in t.get("join", [])}
    assert joined <= TMA_ICAOS
    for t in tmas:
        assert t["name"].startswith(("TMA ", "MTMA ")) and t["below"] in ("TMA", "MTMA", "TMA/MTMA")
        # nazwa w ramce (krótka "short" jak w vAWOS, gdy pełna jest za długa) mieści się w ramce
        assert "short" not in t or t["short"].split()[0] == t["name"].split()[0], t["icao"]
        assert len(t.get("short", t["name"])) <= 14, t["icao"]
        # opis BELOW ... QNH FROM własny albo wspólny z innym lotniskiem ("join"), nigdy oba; pozycja [lon, lat]
        assert ("cap" in t) != (t["icao"] in joined), t["icao"]
        assert "cap" not in t or _lonlat(t["cap"]), (t["icao"], t["cap"])
        # obszar odrysowany z mapy AIP: wielokąty w Polsce
        assert t["aip"]["type"] == "MultiPolygon"
        for ring in _rings(t["aip"]):
            assert len(ring) >= 4 and ring[0] == ring[-1] and all(14 < lon < 24.2 and 49 < lat < 55 for lon, lat in ring)
        # ramka TMA + QNH (każda TMA ma własną, także Katowice ze wspólnym opisem BELOW) w swoim obszarze albo tuż
        # obok, gdy w obszarze nie ma miejsca; MTMA Malbork i Dęblin (bez ramki w vAWOS) - w swoim obszarze
        assert _lonlat(t["box"]), (t["icao"], t["box"])
        km = _km_to_area(t["box"], t["aip"])
        assert km == 0 if t["icao"] in ("EPMB", "EPDE") else km < BOX_KM, (t["icao"], km)
    # szare oznaczenia TMA/CTR z mapy AIP: 1-3 wiersze tekstu w punkcie [lon, lat]
    labels = CFG["chart_labels"]
    assert len(labels) > 30
    for c in labels:
        assert set(c) == {"lines", "lonlat"} and _lonlat(c["lonlat"]), c
        assert 1 <= len(c["lines"]) <= 3 and all(isinstance(s, str) and s.strip() for s in c["lines"])
    assert {"TMA EPWA", "CTR EPKK"} <= {" ".join(c["lines"]) for c in labels}
    # objaśnienie dla użytkownika bez nazw kluczy JSON (te są w "_uwaga")
    assert CFG["note"] and "'" not in CFG["note"]


# układ ramek na mapie METEO › QNH (meteo.js, qnh.css): odwzorowanie stożkowe Lamberta jak lccCrs() (kula R, stała
# stożka 0,798, południk 19°E, r0 na 52°N), piksele przy zoomie domyślnym okna 1600x900 (7,5) i 1366x768 (7,2: ramki
# zmniejszone do 85%, numery do 86%). Ramka SEKTOR n 72x27 px, ramka TMA 88x27 px albo szersza przy długiej nazwie
# (do 6 px na znak w zastępczej czcionce bez Consolas), cyfry numeru rejonu 16,5 px na cyfrę x 20 px, środek 1,5 px
# nad punktem (zmierzone w przeglądarce w tej samej czcionce; Consolas jest węższa, więc odstępy tylko rosną).
LCC_R, LCC_N = 6378137, 0.798
# zoom, skala ramek, skala numerów, odstęp ramka-ramka i ramka-numer w px
LAYOUT = {"1600x900": (7.5, 1.0, 1.0, 4, 1), "1366x768": (7.2, 0.85, 0.86, 2, 0)}


def _px(lon, lat, zoom):
    d = math.pi / 180
    tn = lambda phi: math.tan(math.pi / 4 + phi / 2) ** LCC_N   # noqa: E731
    f = math.cos(math.asin(LCC_N)) * tn(math.asin(LCC_N)) / LCC_N
    r, t = LCC_R * f / tn(lat * d), LCC_N * (lon - 19) * d
    s = 0.5 / (math.pi * LCC_R) * 256 * 2 ** zoom
    return r * math.sin(t) * s, -(LCC_R * f / tn(52 * d) - r * math.cos(t)) * s


def _rect(p, w, h, zoom, k, dy=0.0):
    x, y = _px(*p, zoom)
    return (x - w * k / 2, y + dy * k - h * k / 2, x + w * k / 2, y + dy * k + h * k / 2)


def _hit(a, b, gap):
    """Prostokąty nachodzą na siebie albo są bliżej niż gap px."""
    return min(a[2], b[2]) - max(a[0], b[0]) > -gap and min(a[3], b[3]) - max(a[1], b[1]) > -gap


@pytest.mark.parametrize("view", LAYOUT)
def test_box_layout(view):
    """Ramki SEKTOR n i TMA nie nachodzą na siebie (przy 1600x900 co najmniej 4 px odstępu) ani na numery rejonów,
    w obu domyślnych widokach. Miejsca ramek poprawia się ręcznie w qnh_regions.json; ten test pilnuje układu."""
    zoom, kb, kn, gap, gap_num = LAYOUT[view]
    boxes = [(f"SEKTOR {r['id']}", _rect(r["label"], 72, 27, zoom, kb)) for r in CFG["regions"] if "label" in r]
    boxes += [(t["icao"], _rect(t["box"], max(88, 6 * len(t.get("short", t["name"])) + 10), 27, zoom, kb))
              for t in CFG["tmas"]]
    nums = [(f"numer {r['id']}", _rect(r["num"], 16.5 * len(str(r["id"])), 20, zoom, kn, -1.5)) for r in CFG["regions"]]
    for i, (a, ra) in enumerate(boxes):
        for b, rb in boxes[i + 1:]:
            assert not _hit(ra, rb, gap), (view, a, b)
        for b, rb in nums:
            assert not _hit(ra, rb, gap_num), (view, a, b)


def _lonlat(p):
    """[lon, lat] w okolicy Polski (liczby, także całkowite wpisane ręcznie)."""
    return (len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)
            and 13 < p[0] < 26 and 48 < p[1] < 56)


def _km_to_area(p, g):
    """Odległość punktu od obszaru w km (0 w środku); lokalnie płaskie odwzorowanie wokół punktu."""
    if any(_inside(*p, ring) for ring in _rings(g)):
        return 0.0
    kx, ky = 111.2 * math.cos(math.radians(p[1])), 111.2
    best = math.inf
    for ring in _rings(g):
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            ax, ay = (x1 - p[0]) * kx, (y1 - p[1]) * ky
            bx, by = (x2 - p[0]) * kx, (y2 - p[1]) * ky
            dx, dy = bx - ax, by - ay
            u = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy or 1)))
            best = min(best, math.hypot(ax + u * dx, ay + u * dy))
    return best


def _inside(lon, lat, ring):
    """Punkt w wielokącie (promień w prawo)."""
    out = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            out = not out
    return out


def _area(ring):
    """Pole wielokąta (wzór Gaussa) w stopniach² z poprawką cos(52°) na długość - do porównań wystarczy."""
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2 * 0.6157


GROUPS = {"rejony 1-14": range(1, 15), "pasy 15-17": range(15, 18)}


@pytest.mark.parametrize("group", GROUPS)
def test_regions_tile_fir(group):
    """Rejony 1-14 (i osobno pasy 15-17) pokrywają FIR EPWW bez dziur i bez nakładania: suma pól rejonów = pole FIR
    (więc nakładanie ≈ 0, bo suma pól = pole sumy + nakładanie), a każdy punkt siatki próbnej w FIR leży dokładnie
    w jednym rejonie (suma rejonów ≈ FIR, bez dziur), poza FIR w żadnym."""
    fir = CFG["fir"]["coordinates"][0]
    rings = {r["id"]: _rings(r["geometry"]) for r in CFG["regions"] if r["id"] in GROUPS[group]}
    total = sum(_area(ring) for rr in rings.values() for ring in rr)
    assert abs(total - _area(fir)) / _area(fir) < 1e-5, (total, _area(fir))
    for i in range(141):
        for j in range(91):
            lon, lat = 13.5137 + i * 0.0731, 48.8113 + j * 0.0719
            n = sum(any(_inside(lon, lat, ring) for ring in rr) for rr in rings.values())
            assert n == _inside(lon, lat, fir), (lon, lat, n)


def test_regions_share_boundaries():
    """Wspólne granice sąsiednich rejonów są identyczne: każdy wierzchołek rejonu, który nie jest wierzchołkiem FIR,
    należy do co najmniej dwóch rejonów (węzły linii podziału), więc między rejonami nie ma szczelin ani zakładek."""
    fir = {tuple(p) for p in CFG["fir"]["coordinates"][0]}
    for ids in GROUPS.values():
        count: dict = {}
        for r in CFG["regions"]:
            if r["id"] in ids:
                for p in {tuple(p) for ring in _rings(r["geometry"]) for p in ring}:
                    count[p] = count.get(p, 0) + 1
        assert not [p for p, n in count.items() if n < 2 and p not in fir]


def test_bands_split_at_parallels():
    """Pasy 15-17 = FIR podzielony równoleżnikami 53°N i 51°N (pomarańczowe linie na mapie AIP)."""
    for r in CFG["regions"]:
        if r["id"] in BANDS:
            south, north = BANDS[r["id"]]
            pts = [p for ring in _rings(r["geometry"]) for p in ring]
            assert all(south - 1e-6 <= lat <= north + 1e-6 for _, lat in pts)
            for edge in (south, north):
                if 48 < edge < 56:
                    assert sum(abs(lat - edge) < 1e-6 for _, lat in pts) > 10   # odcinek wzdłuż równoleżnika (zagęszczony)
    # pas 17 ma dwie części: główną i "worek turoszowski" na zachód od Bogatyni
    assert CFG["regions"][16]["geometry"]["type"] == "MultiPolygon"


def test_region_airports_inside():
    """Lotniska z METAR-em rejonu leżą w rejonie albo na jego granicy (EPLY, EPLK, EPBC są węzłami linii podziału);
    wyjątki: rejony 6, 12 i 14 bez własnego lotniska z METAR-em biorą najbliższe (EPWR, EPKK, EPRZ)."""
    pos = {}
    with open(settings.seed_dir / "airports.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pos[row["ident"]] = (float(row["longitude_deg"]), float(row["latitude_deg"]))
    near = {6: {"EPWR"}, 12: {"EPKK"}, 14: {"EPRZ"}}
    for r in CFG["regions"]:
        for a in r["airports"]:
            lon, lat = pos[a]
            hit = any(_inside(lon + dx, lat + dy, ring) for ring in _rings(r["geometry"])
                      for dx in (-0.002, 0, 0.002) for dy in (-0.002, 0, 0.002))
            assert hit or a in near.get(r["id"], ()), (r["id"], a)


def test_endpoint_regions_and_tmas(client, monkeypatch):
    monkeypatch.setattr(meteo, "get_metars", fake_metars)
    q = client.get("/api/meteo/qnh-regions").json()
    assert q["error"] is None and q["note"] == CFG["note"]
    # granica FIR z pliku rejonów (z pliku sektorowego, jak na mapie AIP)
    assert q["fir"] == CFG["fir"]
    assert len(q["regions"]) == 17
    for r in q["regions"]:
        vals = [fake_qnh(a) for a in r["airports"] if a != "EPBY"]
        # QNH rejonu = najniższe QNH z lotnisk rejonu
        assert r["qnh"] == (min(vals) if vals else None) and r["max"] == (max(vals) if vals else None)
        assert [s["icao"] for s in r["stations"]] == r["airports"]
    assert next(r for r in q["regions"] if r["id"] == 3)["qnh"] is None   # tylko EPBY, bez METAR-u
    assert len(q["tmas"]) == len(TMA_ICAOS)
    for t in q["tmas"]:
        assert t["name"] and t["icao"] in TMA_ICAOS and not {"sct", "ese", "aip"} & set(t)
        assert t["qnh"] == (None if t["icao"] == "EPBY" else fake_qnh(t["icao"]))
        assert {"area", "layers", "outline", "lat", "lon"} <= set(t)
        # obszar BELOW ... QNH FROM = obszar odrysowany z mapy AIP
        assert t["area"] == next(c["aip"] for c in CFG["tmas"] if c["icao"] == t["icao"])
    ads = {a["icao"]: a for a in q["aerodromes"]}
    assert ads and all(a["metar"] for i, a in ads.items() if i in TMA_ICAOS)
    tma = {t["icao"]: t for t in q["tmas"]}
    assert tma["EPWA"]["lat"] == pytest.approx(52.17, abs=0.05)
    assert tma["EPKK"]["join"] == ["EPKT"] and "cap" not in tma["EPKT"]
    # układ napisów z pliku rejonów: ramki SEKTOR n i TMA, krótkie nazwy, opisy BELOW, szare oznaczenia AIP
    cfg_tma = {t["icao"]: t for t in CFG["tmas"]}
    for i, t in tma.items():
        assert t["box"] == cfg_tma[i]["box"] and t.get("short") == cfg_tma[i].get("short")
        assert t.get("cap") == cfg_tma[i].get("cap")
    assert tma["EPMI"]["short"] == "MTMA MIROSŁAW." and tma["EPKT"]["box"]
    assert [r.get("label") for r in q["regions"]] == [r.get("label") for r in CFG["regions"]]
    assert q["chart_labels"] == CFG["chart_labels"] and q["chart_labels"]
    for ring in _rings(tma["EPWA"]["area"]):
        assert all(19 < lon < 23 and 51 < lat < 53.5 for lon, lat in ring)
    # Katowice: własny obszar (zachodnia część TMA Kraków na mapie AIP)
    for ring in _rings(tma["EPKT"]["area"]):
        assert all(18 < lon < 19.8 and 50 < lat < 50.9 for lon, lat in ring)
    # MTMA bez danych w plikach sektorowych: obszar z mapy AIP, bez cienkich linii warstw
    assert tma["EPMM"]["area"] and tma["EPMM"]["layers"] is None and tma["EPMM"]["outline"] is None
    if list((DATA_DIR / "import").glob("*.ese")):
        # warstwy TMA z pliku sektorowego (cienkie linie w środku obszaru)
        for i in ("EPGD", "EPKK", "EPRZ"):
            assert tma[i]["layers"]


def test_tma_geometry_fallback():
    """Bez obszaru z mapy AIP ("aip") obszarem są warstwy .ese, a gdy ich brak - linie .sct."""
    out = meteo._tma_geometry({"icao": "EPXX"}, [])
    assert out == {"area": None, "layers": None, "outline": None}
    aip = {"type": "MultiPolygon", "coordinates": [[[[20, 52], [21, 52], [21, 53], [20, 52]]]]}
    out = meteo._tma_geometry({"icao": "EPXX", "aip": aip}, [])
    assert out["area"] == aip and out["layers"] is None
    # warstwa .ese (sektor o nazwie z prefiksem "ese"): bez "aip" jest obszarem, z "aip" cienkimi liniami w środku
    ring = [[20.5, 52.2], [20.8, 52.2], [20.8, 52.6], [20.5, 52.2]]
    sec = SimpleNamespace(name="EPXX_TMA_A", geometry=json.dumps({"type": "Polygon", "coordinates": [ring]}))
    other = SimpleNamespace(name="EPYY_TMA_A", geometry=sec.geometry)
    out = meteo._tma_geometry({"icao": "EPXX", "ese": ["EPXX_TMA_"]}, [sec, other])
    assert out == {"area": {"type": "MultiPolygon", "coordinates": [[ring]]}, "layers": None, "outline": None}
    out = meteo._tma_geometry({"icao": "EPXX", "ese": ["EPXX_TMA_"], "aip": aip}, [sec, other])
    assert out == {"area": aip, "layers": {"type": "MultiPolygon", "coordinates": [[ring]]}, "outline": None}


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
