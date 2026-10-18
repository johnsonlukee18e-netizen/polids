"""Mapa QNH regionalnego: plik data/seed/qnh_regions.json, services/qnh.py i endpoint /api/meteo/qnh-regions."""
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
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
    warstwy; cienkie linie części TMA leżą w swoim obszarze."""
    secs = [f for f in epww_features(ESE) if f["properties"]["fir"] == "EPWW"]
    tmas = {t["icao"]: t for t in CFG["tmas"]}
    for t in CFG["tmas"]:
        if not t.get("ese"):
            continue
        layers = [f["geometry"] for f in secs
                  if f["properties"]["name"].startswith(tuple(t["ese"])) and f["properties"]["lower_ft"] < LOW_FT]
        assert layers, t["icao"]
        areas = [tmas[i]["area"] for i in ({"EPKT", "EPKK"} if t["icao"] in ("EPKT", "EPKK") else {t["icao"]})]
        pts = [p for g in layers for ring in _rings(g) for p in ring]
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
    symbole i kody lotnisk) nie nachodzą na siebie w obu domyślnych widokach. Miejsca poprawia się ręcznie
    w qnh_regions.json albo skryptem (python scripts/trace_qnh_regions.py --layout); ten test pilnuje układu."""
    boxes = qnh.label_boxes(CFG, _drawn(), qnh.VIEWS[view])
    kinds = {k for k, _, _ in boxes}
    assert kinds == {"num", "qnh", "cap", "code", "des", "sym", "aero"}
    assert qnh.overlaps(boxes) == []


def test_label_model():
    """Model napisów: skala jak labelScale() w qnhmap.js, ramki po stronach numeru / symbolu, kolizje."""
    assert qnh.scale(7.5) == 1 and qnh.scale(8.5) == 1
    assert qnh.scale(7.2) == pytest.approx(2 ** -0.3) and qnh.scale(7.16) == qnh.QR_MIN
    assert qnh.scale(7.0) == pytest.approx(2 ** -0.5) and qnh.scale(5.5) == qnh.QR_MIN_FAR
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
    m = re.search(r"const QR_ZOOM = ([\d.]+), QR_FAR = ([\d.]+), QR_MIN = ([\d.]+), QR_MIN_FAR = ([\d.]+);", js)
    assert m and tuple(map(float, m.groups())) == (qnh.QR_ZOOM, qnh.QR_FAR, qnh.QR_MIN, qnh.QR_MIN_FAR)


QNHMAP_SCRIPT = r"""
const m = await import(process.argv[2]);
const t = { icao: "EPGD", below: "TMA", qnh: 1012 };
console.log(JSON.stringify({
  scale: [7.5, 8.5, 7.2, 7.16, 7.0, 5.5].map(m.labelScale),
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
    assert out["scale"] == pytest.approx([qnh.scale(z) for z in (7.5, 8.5, 7.2, 7.16, 7.0, 5.5)])
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
    assert next(r for r in q["regions"] if r["id"] == 3)["qnh"] is None   # tylko EPBY, bez METAR-u
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
