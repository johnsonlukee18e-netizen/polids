"""Mapa QNH regionalnego: plik data/seed/qnh_regions.json, services/qnh.py i endpoint /api/meteo/qnh-regions."""
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import DATA_DIR, settings  # noqa: E402
from backend.app.importers.sct import parse_line_groups, read_text, sections  # noqa: E402
from backend.app.importers.sectors_geojson import epww_features  # noqa: E402
from backend.app.routers import meteo  # noqa: E402
from backend.app.services import qnh  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

ROOT = DATA_DIR.parent
FRONT = ROOT / "frontend"
CFG = json.loads((settings.seed_dir / "qnh_regions.json").read_text("utf-8"))
SCT, ESE = DATA_DIR / "import" / "EPWW-Sector.sct", DATA_DIR / "import" / "EPWW-Sector.ese"
SCRIPT = ROOT / "scripts" / "trace_qnh_regions.py"
# obszary "BELOW TMA/MTMA QNH FROM EPxx" z mapy rejonów QNH z AIP Polska
TMA_ICAOS = {"EPGD", "EPSN", "EPSC", "EPMI", "EPBY", "EPSY", "EPPO", "EPPW", "EPZG", "EPWA", "EPMM", "EPLL", "EPLK",
             "EPRA", "EPLB", "EPWR", "EPKT", "EPKK", "EPRZ", "EPMB", "EPDE"}
# MTMA, których nie ma w plikach sektorowych (obrys z mapy PAŻP)
MIL = {"EPMB", "EPSN", "EPMI", "EPPW", "EPMM", "EPLK"}
BANDS = {15: (53, 90), 16: (51, 53), 17: (-90, 51)}   # pasy awaryjne: FIR podzielony równoleżnikami 53°N i 51°N
LOW_FT = 9500   # warstwy TMA z pliku .ese poniżej FL095
CAP_KM = 45     # środek opisu BELOW … QNH FROM najwyżej tyle km od obszaru (opis ma ok. 85 km szerokości)
POLISH = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


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


def _lonlat(p):
    """[lon, lat] w okolicy Polski (liczby, także całkowite wpisane ręcznie)."""
    return (len(p) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)
            and 13 < p[0] < 26 and 48 < p[1] < 56)


def _inside(lon, lat, ring):
    """Punkt w wielokącie (promień w prawo)."""
    out = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            out = not out
    return out


def _in_area(p, g) -> bool:
    """Punkt w obszarze (Polygon / MultiPolygon z dziurami: liczba przecięć po wszystkich pierścieniach)."""
    return sum(_inside(*p, ring) for ring in _rings(g)) % 2 == 1


def _km_to_area(p, g):
    """Odległość punktu od obszaru w km (0 w środku); lokalnie płaskie odwzorowanie wokół punktu."""
    if _in_area(p, g):
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


def _interior(ring):
    """Punkt we wnętrzu wielokąta: środek najdłuższego odcinka poziomej linii przez środek wysokości."""
    lat = (min(y for _, y in ring) + max(y for _, y in ring)) / 2 + 1e-7
    xs = sorted(x1 + (lat - y1) * (x2 - x1) / (y2 - y1) for (x1, y1), (x2, y2) in zip(ring, ring[1:])
                if (y1 > lat) != (y2 > lat))
    a, b = max(zip(xs[::2], xs[1::2]), key=lambda s: s[1] - s[0])
    return ((a + b) / 2, lat)


def _area(ring):
    """Pole wielokąta (wzór Gaussa) w stopniach² z poprawką cos(52°) na długość - do porównań wystarczy."""
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2 * 0.6157


def _script():
    """Moduł scripts/trace_qnh_regions.py (stałe; shapely importuje dopiero w funkcjach)."""
    spec = importlib.util.spec_from_file_location("trace_qnh_regions", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _drawn():
    """Lotniska na mapie jak w endpoincie (tabela aerodromes = airports.csv), ze stronami kodów z pliku rejonów."""
    with open(settings.seed_dir / "airports.csv", encoding="utf-8") as f:
        rows = [{"icao": r["ident"], "lat": float(r["latitude_deg"]), "lon": float(r["longitude_deg"])}
                for r in csv.DictReader(f) if r["ident"].startswith("EP")]
    metar = {a for r in CFG["regions"] for a in r["airports"]} | {t["icao"] for t in CFG["tmas"]}
    return qnh.drawn_aerodromes(rows, metar, CFG.get("aero_labels", {}))


def test_json_valid():
    regions, tmas = CFG["regions"], CFG["tmas"]
    assert [r["id"] for r in regions] == list(range(1, 18))
    for r in regions:
        assert r["airports"] and all(len(a) == 4 and a.isupper() for a in r["airports"])
        # duży numer z QNH w ramce obok (strona 'qnh_at'); bez dawnych ramek "SEKTOR n"
        assert _lonlat(r["num"]) and r.get("qnh_at", "e") in qnh.SIDES and "label" not in r
        assert bool(r.get("band")) == (r["id"] in BANDS)
        for ring in _rings(r["geometry"]):
            assert len(ring) >= 4 and ring[0] == ring[-1]
            assert all(13 < lon < 26 and 48 < lat < 56 for lon, lat in ring)
        # numer leży w swoim rejonie
        assert _in_area(r["num"], r["geometry"]), (r["id"], r["num"])
    assert CFG["fir"]["type"] == "Polygon" and len(CFG["fir"]["coordinates"][0]) > 100
    assert {t["icao"] for t in tmas} == TMA_ICAOS and len(tmas) == len(TMA_ICAOS)
    joined = {i for t in tmas for i in t.get("join", [])}
    assert joined <= TMA_ICAOS
    for t in tmas:
        assert t["name"].startswith(("TMA ", "MTMA ")) and t["below"] in ("TMA", "MTMA", "TMA/MTMA")
        # dawne pola (obszar odrysowany z mapy, ramki vAWOS) zastąpione geometrią z plików sektorowych
        assert not {"aip", "sct", "box", "short", "label"} & set(t), t["icao"]
        # TMA cywilna z warstw pliku .ese ('ese' = przedrostki nazw sektorów), MTMA z mapy PAŻP ('mil')
        assert bool(t.get("mil")) == (t["icao"] in MIL) and bool(t.get("ese")) != bool(t.get("mil")), t["icao"]
        assert all(isinstance(p, str) and p.startswith("EP") for p in t.get("ese", []))
        assert t["area"]["type"] == "MultiPolygon"
        for ring in _rings(t["area"]):
            assert len(ring) >= 4 and ring[0] == ring[-1] and all(14 < lon < 24.2 and 49 < lat < 55 for lon, lat in ring)
        # opis BELOW … QNH FROM własny albo wspólny z innym lotniskiem ("join"); przy wspólnym opisie kody z QNH są
        # osobnymi napisami 'code' w części każdego lotniska
        assert ("cap" in t) != (t["icao"] in joined), t["icao"]
        assert "cap" not in t or _lonlat(t["cap"]), (t["icao"], t["cap"])
        if t["icao"] in joined or t.get("join"):
            assert _lonlat(t["code"]) and _in_area(t["code"], t["area"]), t["icao"]
        assert "cap" not in t or _km_to_area(t["cap"], t["area"]) < CAP_KM, t["icao"]
        if t.get("parts"):
            assert t["parts"]["type"] == "MultiLineString"
    # CTR/MCTR: z pliku .ese albo (MCTR wojskowe) z mapy PAŻP
    assert len(CFG["ctrs"]) > 25
    for c in CFG["ctrs"]:
        assert c["name"].split()[0] in ("CTR", "MCTR", "CTR/MCTR") and c["src"] in ("ese", "chart")
        assert all(len(r) >= 4 and r[0] == r[-1] for r in _rings(c["geometry"]))
    assert {"CTR EPWA", "CTR EPKK", "MCTR EPMM"} <= {c["name"] for c in CFG["ctrs"]}
    # MCTR z mapy PAŻP odrysowane wierzchołkami jak na mapie (nie okręgi wokół lotniska, np. wydłużony MCTR EPIR)
    for c in CFG["ctrs"]:
        if c["src"] == "chart":
            assert all(4 <= len(r) - 1 <= 12 for r in _rings(c["geometry"])), c["name"]
    # lotniska, przez których symbol przechodzi linia rejonów na mapie PAŻP, są w obu (wszystkich) rejonach
    reg = {r["id"]: r["airports"] for r in CFG["regions"]}
    for icao, ids in {"EPIR": (3, 4), "EPLY": (4, 9), "EPLK": (4, 5, 9), "EPBC": (8, 9)}.items():
        assert all(icao in reg[i] for i in ids), icao
    # szare oznaczenia TMA/CTR z mapy AIP: 1-3 wiersze tekstu w punkcie [lon, lat]
    labels = CFG["chart_labels"]
    assert len(labels) > 30
    for c in labels:
        assert set(c) == {"lines", "lonlat"} and _lonlat(c["lonlat"]), c
        assert 1 <= len(c["lines"]) <= 3 and all(isinstance(s, str) and s.strip() for s in c["lines"])
    assert {"TMA EPWA", "CTR EPKK"} <= {" ".join(c["lines"]) for c in labels}
    assert all(len(k) == 4 and k.startswith("EP") and v in qnh.SIDES for k, v in CFG["aero_labels"].items())
    # objaśnienie dla użytkownika po angielsku, bez nazw kluczy JSON (te są w "_uwaga")
    assert CFG["note"] and not re.search(r"'\w+'", CFG["note"]) and not POLISH & set(CFG["note"])


def test_sources_current():
    """Plik rejonów zrobiony z obecnych plików sektorowych (po ich podmianie: python scripts/trace_qnh_regions.py)."""
    assert set(CFG["sources"]) == {"data/import/EPWW-Sector.sct", "data/import/EPWW-Sector.ese"}
    for path, sha in CFG["sources"].items():
        f = ROOT / path
        if f.exists():
            assert _sha256(f) == sha, f"{path} zmieniony: uruchom python scripts/trace_qnh_regions.py"


@pytest.mark.skipif(not SCT.exists(), reason="brak pliku .sct")
def test_fir_from_sector_file():
    """Granica FIR = grupa "FIR border 0 - EPWW" pliku .sct (każdy wierzchołek jest punktem pliku sektorowego),
    a rejony 1-14 i pasy 15-17 biegną granicą FIR dokładnie (każdy wierzchołek FIR jest wierzchołkiem rejonu)."""
    segs = parse_line_groups(sections(read_text(SCT)).get("[ARTCC HIGH]", []))["FIR border 0 - EPWW"]
    pts = {(round(p[1], 5), round(p[0], 5)) for s in segs for p in s}
    fir = {tuple(p) for p in CFG["fir"]["coordinates"][0]}
    assert fir <= pts
    for ids in GROUPS.values():
        verts = {tuple(p) for r in CFG["regions"] if r["id"] in ids for ring in _rings(r["geometry"]) for p in ring}
        assert fir <= verts


@pytest.mark.skipif(not ESE.exists(), reason="brak pliku .ese")
def test_tma_areas_from_sector_file():
    """Obszar TMA cywilnej = suma warstw pliku .ese poniżej FL095 o przedrostkach 'ese': środek każdej warstwy leży
    w obszarze (TMA Kraków podzielona na części Katowic i Krakowa: w jednej z nich), a obszar nie wychodzi poza
    warstwy (TMA z częścią spoza pliku .ese, SCT_FILL w skrypcie: poza warstwy i obrys TMA z pliku .sct); cienkie
    linie części TMA leżą w swoim obszarze."""
    secs = [f for f in epww_features(ESE) if f["properties"]["fir"] == "EPWW"]
    tmas = {t["icao"]: t for t in CFG["tmas"]}
    fill = _script().SCT_FILL
    groups = parse_line_groups(sections(read_text(SCT)).get("[ARTCC]", [])) if fill and SCT.exists() else {}
    for t in CFG["tmas"]:
        if not t.get("ese"):
            continue
        layers = [f["geometry"] for f in secs
                  if f["properties"]["name"].startswith(tuple(t["ese"])) and f["properties"]["lower_ft"] < LOW_FT]
        assert layers, t["icao"]
        areas = [tmas[i]["area"] for i in ({"EPKT", "EPKK"} if t["icao"] in ("EPKT", "EPKK") else {t["icao"]})]
        pts = [p for g in layers for ring in _rings(g) for p in ring]
        pts += [(p[1], p[0]) for seg in groups.get(fill.get(t["icao"]), []) for p in seg]
        lo = (min(x for x, _ in pts) - 1e-4, min(y for _, y in pts) - 1e-4)
        hi = (max(x for x, _ in pts) + 1e-4, max(y for _, y in pts) + 1e-4)
        for g in layers:
            p = _interior(_rings(g)[0])
            assert any(_in_area(p, a) for a in areas), (t["icao"], p)
        for ring in _rings(t["area"]):
            assert all(lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] for x, y in ring), t["icao"]
        for line in (t.get("parts") or {}).get("coordinates", []):
            for a, b in zip(line, line[1:]):
                assert _in_area(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), t["area"]), t["icao"]
    # części wspólne dwóch obszarów (rysowane ciemniej) leżą w co najmniej dwóch obszarach
    for poly in CFG["overlaps"]["coordinates"]:
        p = _interior(poly[0])
        assert sum(_in_area(p, t["area"]) for t in CFG["tmas"]) >= 2, p


def test_geometry_valid():
    """Wielokąty pliku rejonów są poprawne po zaokrągleniu współrzędnych (bez kolców i samoprzecięć), a części wspólne
    obszarów TMA/MTMA to zakładki z mapy PAŻP, nie drzazgi wzdłuż wspólnej granicy (np. MTMA Łask przy TMA Łódź C)."""
    pytest.importorskip("shapely")
    from shapely.geometry import shape

    geoms = {**{t["icao"]: t["area"] for t in CFG["tmas"]}, **{c["name"]: c["geometry"] for c in CFG["ctrs"]},
             **{f"region {r['id']}": r["geometry"] for r in CFG["regions"]}, "fir": CFG["fir"]}
    assert [k for k, g in geoms.items() if not shape(g).is_valid] == []
    assert all(not p.buffer(-0.002).is_empty for p in shape(CFG["overlaps"]).geoms)


# obrysy TMA z pliku .sct ([ARTCC] "… OUT") -> obszary BELOW TMA z pliku rejonów
SCT_OUT = {"EPBY TMA OUT": ("EPBY",), "EPDE MTMA OUT": ("EPDE",), "EPGD TMA OUT": ("EPGD",),
           "EPKK TMA OUT": ("EPKT", "EPKK"), "EPLB TMA OUT": ("EPLB",), "EPLL TMA OUT": ("EPLL",),
           "EPPO TMA N OUT": ("EPPO",), "EPPO TMA S OUT": ("EPWR",), "EPRA TMA OUT": ("EPRA",),
           "EPRZ TMA OUT": ("EPRZ",), "EPSC TMA OUT": ("EPSC",), "EPSY TMA OUT": ("EPSY",), "EPWA TMA OUT": ("EPWA",),
           "EPZG TMA OUT": ("EPZG",)}


@pytest.mark.skipif(not (SCT.exists() and ESE.exists()), reason="brak plików sektorowych")
def test_tma_covers_sct_outline():
    """Obszary BELOW TMA pokrywają obrysy TMA z pliku .sct ("… TMA OUT") co najmniej w 99% wszędzie tam, gdzie plik
    .ese ma pod obrysem przestrzeń kontrolowaną poniżej FL095 (TMA, CTR, CTA; bez FIS, ATZ i TRA): obrys obejmuje też
    górne części TMA (np. EPGD_UTMA od FL095), których mapa PAŻP nie zalicza do BELOW TMA. TMA, której cały obrys leży
    poniżej FL095 (np. TMA Łódź z częścią C, której nie ma w pliku .ese), pokrywa go własnym obszarem."""
    pytest.importorskip("shapely")
    from shapely.geometry import LineString, Polygon, shape
    from shapely.ops import polygonize, unary_union

    def solid(g):
        g = g.buffer(0)
        return unary_union([Polygon(p.exterior) for p in getattr(g, "geoms", [g])])

    groups = parse_line_groups(sections(read_text(SCT)).get("[ARTCC]", []))
    assert {n for n in groups if n.endswith(" OUT")} == set(SCT_OUT)
    low = unary_union([solid(shape(f["geometry"])) for f in epww_features(ESE)
                       if f["properties"]["fir"] == "EPWW" and f["properties"]["lower_ft"] < LOW_FT
                       and not re.match(r"(FIS|WAW_FIS|EPWW|EPTR)", f["properties"]["name"])
                       and "_ATZ" not in f["properties"]["name"]])
    tmas = {t["icao"]: shape(t["area"]) for t in CFG["tmas"]}
    every = unary_union(list(tmas.values()))
    for name, icaos in SCT_OUT.items():
        lines = [LineString([(a[1], a[0]), (b[1], b[0])]) for a, b in groups[name] if a != b]
        out = solid(unary_union(list(polygonize(unary_union(lines)))))
        need = out.intersection(low)
        assert need.intersection(every).area / need.area > 0.99, name
        if need.area / out.area > 0.99:
            own = unary_union([tmas[i] for i in icaos])
            assert out.intersection(own).area / out.area > 0.99, name


# pola z geometrią (porównywane polem różnicy symetrycznej, nie bajtami: inna wersja GEOS może zacząć pierścień
# w innym wierzchołku)
GEOM = {"geometry", "area", "parts", "overlaps", "fir"}


def _run_script(tmp_path, *args) -> dict:
    out = tmp_path / ("qnh" + "".join(args) + ".json")
    r = subprocess.run([sys.executable, str(SCRIPT), "--out", str(out), *args], capture_output=True, text=True,
                       timeout=600, cwd=ROOT)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return json.loads(out.read_text("utf-8"))


def _same(a, b, path="") -> None:
    """Ten sam plik rejonów: pola bez geometrii równe, geometria ta sama (różnica symetryczna ~0)."""
    from shapely.geometry import shape

    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), path
        for k in a:
            if k in GEOM and a[k] is not None and b[k] is not None:
                ga, gb = shape(a[k]), shape(b[k])
                assert ga.symmetric_difference(gb).length < 1e-6 if ga.area == 0 else \
                    ga.symmetric_difference(gb).area < 1e-9, f"{path}.{k}"
            else:
                _same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _same(x, y, f"{path}[{i}]")
    else:
        assert a == b, path


@pytest.mark.skipif(not (SCT.exists() and ESE.exists()), reason="brak plików sektorowych")
def test_script_reproduces_seed(tmp_path):
    """Skrypt odtwarza zapisany plik rejonów (zmiany geometrii tylko przez skrypt), a --layout na zapisanym pliku nic
    nie zmienia: przesuwa tylko napisy, które na coś nachodzą, a w zapisanym pliku żadne nie nachodzą."""
    pytest.importorskip("shapely")
    plain = _run_script(tmp_path)
    _same(plain, CFG)
    assert _run_script(tmp_path, "--layout") == plain


def test_region_lines_follow_tma():
    """Tam, gdzie linia rejonu na mapie PAŻP biegnie granicą TMA/CTR, granica rejonów ma wierzchołki tej TMA/CTR."""
    reg = {r["id"]: {tuple(p) for ring in _rings(r["geometry"]) for p in ring} for r in CFG["regions"]}
    geo = {t["icao"]: t["area"] for t in CFG["tmas"]} | {c["name"]: c["geometry"] for c in CFG["ctrs"]}
    for (a, b), name in {(2, 3): "EPGD", (8, 9): "CTR EPWA", (9, 10): "EPWA", (5, 6): "EPWR"}.items():
        verts = {tuple(p) for ring in _rings(geo[name]) for p in ring}
        assert len(reg[a] & reg[b] & verts) >= 2, (a, b, name)


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


# --- układ napisów (qnhmap.js, qnh.css): model rozmiarów w services/qnh.py

@pytest.mark.parametrize("view", qnh.VIEWS)
def test_label_layout(view):
    """Napisy mapy (numery rejonów z ramką QNH, opisy BELOW … QNH FROM z QNH, kody 'code', szare oznaczenia,
    symbole i kody lotnisk) nie nachodzą na siebie w każdym domyślnym widoku (także przy oknie przeglądarki
    1366x657 i 1600x789, czyli ekranie 1366x768 i 1600x900 z paskami przeglądarki). Miejsca poprawia się ręcznie
    w qnh_regions.json albo skryptem (python scripts/trace_qnh_regions.py --layout); ten test pilnuje układu."""
    zoom = qnh.VIEWS[view]
    assert not qnh.far(zoom, zoom)   # domyślny widok ma wszystkie napisy
    boxes = qnh.label_boxes(CFG, _drawn(), zoom)
    kinds = {k for k, _, _ in boxes}
    assert kinds == {"num", "qnh", "cap", "code", "des", "sym", "aero"}
    assert qnh.overlaps(boxes) == []
    # numer rejonu i ramka z QNH rejonu w swoim rejonie (ramka po drugiej stronie linii czytałaby się jako QNH
    # sąsiedniego rejonu): środek i co najmniej 3 narożniki prostokąta w rejonie
    for r in CFG["regions"]:
        rings = [[qnh.px(*c, zoom) for c in ring] for ring in _rings(r["geometry"])]
        for k, n, (x0, y0, x1, y1) in boxes:
            if n == str(r["id"]) and k in ("num", "qnh"):
                pts = [((x0 + x1) / 2, (y0 + y1) / 2), (x0, y0), (x1, y0), (x0, y1), (x1, y1)]
                inside = [sum(_inside(x, y, ring) for ring in rings) % 2 == 1 for x, y in pts]
                assert inside[0] and sum(inside[1:]) >= 3, (view, r["id"], k)
    # wspólny opis (TMA Kraków: BELOW TMA / QNH FROM) nad kodami z QNH: każdy kod w całości pod opisem, żeby
    # nie czytał się w jednym wierszu z "QNH FROM" (jak EPKT / EPKK pod opisem na mapie PAŻP)
    caps = {n: r for k, n, r in boxes if k == "cap"}
    for t in CFG["tmas"]:
        for code in [t["icao"], *t.get("join", [])] if t.get("join") else []:
            r = next(r for k, n, r in boxes if k == "code" and n == code)
            assert r[1] >= caps[t["icao"]][3], (view, code)


def test_label_model():
    """Model napisów: skala jak labelScale() w qnhmap.js, ramki po stronach numeru / symbolu, kolizje."""
    assert qnh.scale(7.5) == 1 and qnh.scale(8.5) == 1
    assert qnh.scale(7.2) == pytest.approx(2 ** -0.3) and qnh.scale(7.0) == pytest.approx(2 ** -0.5)
    assert qnh.scale(6.9) == qnh.QR_MIN == 0.7 and qnh.scale(5.5) == qnh.QR_MIN
    # widok "z daleka" względem zoomu dopasowanego do okna (nie wyżej niż 7,5): przy 1366x657 (zoom 7,0) domyślny
    # widok ma napisy, jedno "−" (0,5) już nie; na dużym ekranie (7,7) dopiero poniżej 7,2
    assert not qnh.far(7.0, 7.0) and qnh.far(6.5, 7.0) and not qnh.far(6.75, 7.0)
    assert not qnh.far(7.2, 7.5) and qnh.far(7.0, 7.5)
    assert not qnh.far(7.4, 7.7) and not qnh.far(7.2, 7.7) and qnh.far(7.1, 7.7)
    x0, y0, x1, y1 = qnh._side(0, 0, 10, 5, 30, 12, "e", 2)
    assert (x0, y0, x1, y1) == (12, -6, 42, 6)
    assert qnh._side(0, 0, 10, 5, 30, 12, "n", 2) == (-15, -19, 15, -7)
    assert qnh._side(0, 0, 10, 5, 30, 12, "sw", 2) == (-42, 0, -12, 12)   # górny brzeg na wysokości środka
    t = {"icao": "EPGD", "below": "TMA"}
    assert qnh.caption_lines(t) == (["BELOW TMA", "QNH FROM EPGD 1013"], True)
    assert qnh.caption_lines({**t, "stack": True}) == (["BELOW TMA", "QNH FROM EPGD", "1013"], True)
    assert qnh.caption_lines({**t, "code": [19, 50]}) == (["BELOW TMA", "QNH FROM"], False)
    # ramka QNH (+4 px) tylko przy ostatnim wierszu; wysokość: wiersze + 2 px obwódki
    assert qnh.text_box(["BELOW TMA", "1013"], (10, 12), 1, 4, 2, True) == (pytest.approx(54), 26)
    a, b = ("cap", "EPGD", (0, 0, 10, 10)), ("des", "TMA EPGD", (10.5, 0, 20, 10))
    assert qnh.clash(a, b) and not qnh.clash(a, ("des", "x", (11.5, 0, 20, 10)))
    assert not qnh.clash(("sym", "EPKK", (0, 0, 9, 9)), ("sym", "EPKP", (5, 5, 14, 14)))
    assert not qnh.clash(("sym", "EPKK", (0, 0, 9, 9)), ("aero", "EPKK", (5, 0, 20, 9)))
    assert qnh.clash(("sym", "EPKK", (0, 0, 9, 9)), ("aero", "EPKP", (5, 0, 20, 9)))
    assert qnh.overlaps([a, b]) == [(("cap", "EPGD"), ("des", "TMA EPGD"))]


def test_label_model_matches_css():
    """Rozmiary z modelu services/qnh.py są tymi z qnh.css, a skala tą z qnhmap.js (inaczej test układu kłamie)."""
    css = (FRONT / "css" / "qnh.css").read_text("utf-8")

    def font(sel):
        m = re.search(re.escape(sel) + r"\s*\{[^}]*?font:\s*(?:\d+\s+)?([\d.]+)px/([\d.]+)px", css)
        assert m, sel
        return float(m[1]), float(m[2])

    assert font(".qr-num") == qnh.NUM and font(".qr-num .q") == qnh.QBOX
    assert font(".qr-cap") == qnh.CAP and font(".qr-des") == qnh.DES and font(".qr-aero span") == qnh.AERO
    assert "padding: 0 2px" in re.search(r"\.qr-num \.q \{[^}]*\}", css)[0]
    assert re.search(r"\.qr-aero\.ctl i \{[^}]*width: 9px; height: 9px", css) and qnh.SYM == 9
    assert ".qr-aero.s-e span, .qr-aero.s-ne span, .qr-aero.s-se span { left: 6.5px; }" in css   # 4,5 + 2 px
    js = (FRONT / "js" / "qnhmap.js").read_text("utf-8")
    m = re.search(r"const QR_ZOOM = ([\d.]+), QR_FAR = ([\d.]+), QR_MIN = ([\d.]+);", js)
    assert m and tuple(map(float, m.groups())) == (qnh.QR_ZOOM, qnh.QR_FAR, qnh.QR_MIN)


def test_fir_line_and_band_count_css():
    """Granica FIR jedną linią w kolorze z mapy PAŻP (bez zielonego rdzenia i pomarańczowej podkładki), a w tabeli
    pasów 15-17 "of N AD" w jednym wierszu (bez samego "AD" w drugim)."""
    css = (FRONT / "css" / "qnh.css").read_text("utf-8")
    js = (FRONT / "js" / "qnhmap.js").read_text("utf-8")
    assert "qr-fcase" not in css + js and "qr-fcore" not in css + js
    assert re.search(r"--qr-fir: #[0-9a-f]{6};", css)
    assert re.search(r"\.qrmap path\.qr-fir \{ stroke: var\(--qr-fir\);[^}]*\}", css)
    assert 'geo(data.fir, "qfir", "qr-fir", layers.base, { fill: false });' in js
    assert '<span class="nil of">of ${r.stations.length} AD</span>' in js
    assert re.search(r"\.qrside td\.sta \.of \{ white-space: nowrap; \}", css)


QNHMAP_SCRIPT = r"""
const m = await import(process.argv[2]);
const t = { icao: "EPGD", below: "TMA", qnh: 1012 };
console.log(JSON.stringify({
  scale: [7.5, 8.5, 7.2, 7.0, 6.9, 5.5].map(m.labelScale),
  far: [[7.0, 7.0], [6.5, 7.0], [6.75, 7.0], [7.2, 7.5], [7.0, 7.5], [7.4, 7.7], [7.1, 7.7]].map(([z, f]) => m.isFar(z, f)),
  cap: [m.captionHtml(t), m.captionHtml({ ...t, qnh: null, stack: true }), m.captionHtml({ ...t, code: [19, 50] })],
  code: m.codeHtml({ icao: "EPKT", qnh: 1013 }),
}));
"""


def test_qnhmap_js(tmp_path):
    """qnhmap.js w Node: skala napisów jak w modelu services/qnh.py, opisy BELOW … QNH FROM z QNH w ramce."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text((FRONT / "js" / "api.js").read_text("utf-8"), "utf-8")
    (tmp_path / "qnhmap.mjs").write_text((FRONT / "js" / "qnhmap.js").read_text("utf-8")
                                         .replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(QNHMAP_SCRIPT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "qnhmap.mjs").as_uri()], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["scale"] == pytest.approx([qnh.scale(z) for z in (7.5, 8.5, 7.2, 7.0, 6.9, 5.5)])
    far = [(7.0, 7.0), (6.5, 7.0), (6.75, 7.0), (7.2, 7.5), (7.0, 7.5), (7.4, 7.7), (7.1, 7.7)]
    assert out["far"] == [qnh.far(z, f) for z, f in far] == [False, True, False, False, True, False, True]
    assert out["cap"] == ['<span>BELOW TMA</span><span>QNH FROM EPGD <b class="q">1012</b></span>',
                          '<span>BELOW TMA</span><span>QNH FROM EPGD</span><span><b class="q nil">----</b></span>',
                          "<span>BELOW TMA</span><span>QNH FROM</span>"]
    assert out["code"] == '<span>EPKT <b class="q">1013</b></span>'


def test_drawn_aerodromes():
    ads = [{"icao": "EPLB", "lat": 51.24, "lon": 22.71}, {"icao": "EPSW", "lat": 51.25, "lon": 22.73},
           {"icao": "EPZA", "lat": 50.70, "lon": 23.20}]
    out = qnh.drawn_aerodromes(ads, {"EPLB"}, {"EPZA": "w"})
    # lądowisko w miejscu lotniska z METAR-em pominięte; strona kodu z pliku (domyślnie e)
    assert [(a["icao"], a["metar"], a["label"]) for a in out] == [("EPLB", True, "e"), ("EPZA", False, "w")]
    drawn = _drawn()
    assert len(drawn) > 80 and {a["icao"] for a in drawn if a["metar"]} >= TMA_ICAOS


def test_chains():
    sq = [[0, 0], [0, 1], [1, 1], [1, 0]]
    segs = [[sq[i], sq[(i + 1) % 4]] for i in range(4)] + [[[1, 1], [2, 2]]]   # kwadrat i "ogonek"
    chains = qnh._chains(segs)
    assert sorted(len(c) for c in chains) in ([2, 5], [6])
    assert sum(len(c) - 1 for c in chains) == len(segs)


def test_endpoint_regions_and_tmas(client, monkeypatch):
    monkeypatch.setattr(meteo, "get_metars", fake_metars)
    q = client.get("/api/meteo/qnh-regions").json()
    assert q["error"] is None and q["note"] == CFG["note"]
    # granica FIR, CTR/MCTR, części wspólne TMA i szare oznaczenia z pliku rejonów
    assert q["fir"] == CFG["fir"] and q["ctrs"] == CFG["ctrs"] and q["overlaps"] == CFG["overlaps"]
    assert q["chart_labels"] == CFG["chart_labels"] and q["chart_labels"]
    assert len(q["regions"]) == 17
    for r in q["regions"]:
        vals = [fake_qnh(a) for a in r["airports"] if a != "EPBY"]
        # QNH rejonu = najniższe QNH z lotnisk rejonu
        assert r["qnh"] == (min(vals) if vals else None) and r["max"] == (max(vals) if vals else None)
        assert [s["icao"] for s in r["stations"]] == r["airports"]
        assert r["num"] and r.get("qnh_at", "e") in qnh.SIDES
    # rejon 3: EPBY bez METAR-u, więc QNH z EPIR (na linii 3/4)
    assert next(r for r in q["regions"] if r["id"] == 3)["qnh"] == fake_qnh("EPIR")
    # pasy awaryjne: najniższe QNH wszystkich lotnisk pasa
    band = next(r for r in q["regions"] if r["id"] == 16)
    assert band["band"] and band["qnh"] == min(fake_qnh(a) for a in band["airports"] if a != "EPBY")
    assert len(q["tmas"]) == len(TMA_ICAOS)
    cfg_tma = {t["icao"]: t for t in CFG["tmas"]}
    for t in q["tmas"]:
        assert t["name"] and t["icao"] in TMA_ICAOS and "ese" not in t
        assert t["qnh"] == (None if t["icao"] == "EPBY" else fake_qnh(t["icao"]))
        assert {"area", "parts", "lat", "lon"} <= set(t)
        # obszar, cienkie linie i układ napisów z pliku rejonów
        for k in ("area", "parts", "cap", "code", "stack", "join"):
            assert t.get(k) == cfg_tma[t["icao"]].get(k), (t["icao"], k)
    tma = {t["icao"]: t for t in q["tmas"]}
    assert tma["EPWA"]["lat"] == pytest.approx(52.17, abs=0.05)
    assert tma["EPKK"]["join"] == ["EPKT"] and "cap" not in tma["EPKT"] and tma["EPKT"]["code"]
    for ring in _rings(tma["EPWA"]["area"]):
        assert all(19 < lon < 23 and 51 < lat < 53.5 for lon, lat in ring)
    # Katowice: zachodnia część TMA Kraków (podział jak na mapie AIP)
    for ring in _rings(tma["EPKT"]["area"]):
        assert all(18 < lon < 19.8 and 49.8 < lat < 50.9 for lon, lat in ring)
    # MTMA wojskowe: obszar z mapy PAŻP, bez cienkich linii; TMA z kilku części: cienkie linie
    assert tma["EPMM"]["area"] and tma["EPMM"]["parts"] is None
    for i in ("EPGD", "EPKK", "EPRZ", "EPWA"):
        assert tma[i]["parts"]["coordinates"]
    # lotniska: wszystkie z METAR-em (kółko z kropką) i pozostałe (romb) z bazy, strona kodu z pliku rejonów
    ads = {a["icao"]: a for a in q["aerodromes"]}
    assert len(ads) > 80 and all(ads[i]["metar"] for i in TMA_ICAOS)
    assert all(a["label"] == CFG["aero_labels"].get(i, "e") for i, a in ads.items())
    assert q["coast"] is None or q["coast"]["type"] == "MultiLineString"


def test_endpoint_without_metar(client, monkeypatch):
    async def down(icaos):
        raise UpstreamError("no network")

    monkeypatch.setattr(meteo, "get_metars", down)
    q = client.get("/api/meteo/qnh-regions").json()
    assert q["error"] == "METAR source unavailable: no network"
    assert all(r["qnh"] is None for r in q["regions"]) and all(t["qnh"] is None for t in q["tmas"])
