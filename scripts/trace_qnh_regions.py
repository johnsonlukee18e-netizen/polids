"""Granice rejonów QNH regionalnego (1–14) i pasów awaryjnych (15–17) do data/seed/qnh_regions.json.

Źródło: mapa rejonów QNH z AIP Polska (PAŻP), zrzut ekranu 3840x2160 dostarczony przez Marka 2026-10-08
(siatka 14°–25°E, 49°–55°N w odwzorowaniu stożkowym). Linie rejonów odrysowane w pikselach zrzutu (wierzchołki
w LINES poniżej: punkty załamania zielonych linii, wspólne węzły rejonów), przeliczone na współrzędne przez
odwzorowanie stożkowe wiernokątne Lamberta dopasowane do siatki mapy (średni błąd ok. 1,5 px ≈ 0,5 km; kontrola:
symbole lotnisk wypadają średnio 0,2 px od współrzędnych z airports.csv, pomarańczowe linie dokładnie na 53°N i 51°N).
Granica zewnętrzna = granica FIR EPWW z pliku sektorowego (data/import/EPWW-Sector.sct, grupa "FIR border 0 - EPWW"),
która na zrzucie pokrywa się z granicą FIR z mapy PAŻP (także nad Bałtykiem). Rejony powstają z podziału FIR liniami
(shapely.polygonize), więc wspólne granice sąsiadów są identyczne, a rejony pokrywają FIR bez dziur i nakładania.
Pasy 15–17 (wartości awaryjne podawane, gdy nie działa model IMGW) = FIR podzielony równoleżnikami 53°N i 51°N.
Z --image także obszary "BELOW TMA/MTMA QNH FROM EPxx" (liliowe wypełnienie zrzutu dzielone pogrubionymi liniami,
funkcja trace_tma) zapisywane jako 'aip' przy TMA; bez --image dotychczasowe 'aip' zostają w pliku.

Użycie (z katalogu głównego repozytorium):
    python scripts/trace_qnh_regions.py                          # zapis rejonów i FIR do data/seed/qnh_regions.json
    python scripts/trace_qnh_regions.py --image data/import/qnh_pansa.png --overlay kontrola.png
                                                                 # jak wyżej + obszary TMA "BELOW … QNH FROM" ze zrzutu
                                                                 # ('aip' w "tmas") i nakładka granic na zrzucie
    python scripts/trace_qnh_regions.py --image data/import/qnh_pansa.png --fit
                                                                 # ponowne dopasowanie odwzorowania do siatki zrzutu

Wymaga: numpy i shapely, dla --image także Pillow (pip install numpy shapely pillow).
"""

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
OUT = SEED / "qnh_regions.json"

# odwzorowanie Lamberta dopasowane do siatki zrzutu (--fit): piksel bieguna (xp, yp), stała stożka n,
# ln skali C (promień równoleżnika = C * t(φ)^n, elipsoida GRS80) i południk środkowy lon0
LCC = {"xp": 1880.394, "yp": -12592.290, "n": 0.7981264, "lnC": 10.3826669, "lon0": 19.002774}
E = 0.0818191910428  # mimośród GRS80

# węzły wspólne kilku linii (piksele zrzutu); "F…" = koniec na granicy FIR (linia przedłużana do przecięcia z FIR),
# "@ICAO" = wierzchołek w punkcie lotniska (linie na mapie PAŻP przechodzą przez środek symbolu lotniska)
NODES = {
    "J1-2-3": (1604.5, 582.8), "J1-3-4": (1444.8, 863.1), "J2-3-7-8": (1953.2, 865.2), "J3-4-8-9": (1904.2, 1049.9),
    "J8-9-10": (2452.7, 1257.3), "J9-10-11-13": (2206.4, 1571.5), "J4-5-9": "@EPLK", "J5-9-11": (1932.8, 1579.9),
    "J11-12-13-14": (2150.5, 1861.2),
    "F1-2": (1279.5, 330.6), "F2-7": (2043.5, 494.9), "F7-8": (2786.1, 838.9), "F8-10": (2773.4, 1203.5),
    "F10-13": (2880.0, 1618.8), "F13-14": (2700.9, 1891.6), "F12-14": (2219.6, 2067.8), "F11-12": (1788.0, 1907.3),
    "F5-11": (1628.5, 1786.8), "F5-6s": (1475.9, 1741.2), "F5-6w": (1096.7, 1484.1), "F4-5": (1055.8, 1228.9),
    "F1-4": (1048.2, 1049.0),
}
# granice między rejonami: kolejne wierzchołki (nazwa węzła, "@ICAO" albo piksel zrzutu)
LINES = {
    "1/2": ["F1-2", "J1-2-3"],
    "2/3": ["J1-2-3", (1869.0, 799.0), "J2-3-7-8"],
    "1/3": ["J1-2-3", (1461.6, 700.6), "J1-3-4"],
    "1/4": ["F1-4", "J1-3-4"],
    "2/7": ["F2-7", "J2-3-7-8"],
    "3/4": ["J1-3-4", (1635.8, 947.8), "J3-4-8-9"],
    "3/8": ["J2-3-7-8", "J3-4-8-9"],
    "7/8": ["J2-3-7-8", (2236.5, 933.2), "@EPGY", (2682.3, 860.0), "F7-8"],
    "8/9": ["J3-4-8-9", (2011.4, 1088.2), (2191.3, 1175.2), (2196.1, 1177.1), "@EPBC", (2264.3, 1170.8),
            (2295.7, 1206.2), (2309.2, 1251.4), "J8-9-10"],
    "8/10": ["J8-9-10", (2535.0, 1260.6), "F8-10"],
    "9/10": ["J8-9-10", (2398.6, 1322.2), (2375.2, 1371.7), (2344.7, 1391.5), (2274.8, 1537.7), "J9-10-11-13"],
    "4/9": ["J3-4-8-9", "@EPLY", "J4-5-9"],
    "5/9": ["J4-5-9", "J5-9-11"],
    "4/5": ["F4-5", "J4-5-9"],
    "9/11": ["J5-9-11", (2044.0, 1576.5), "J9-10-11-13"],
    "10/13": ["J9-10-11-13", (2427.0, 1632.9), (2496.4, 1647.6), "F10-13"],
    "5/6": ["F5-6w", (1356.9, 1574.0), (1541.5, 1657.0), "F5-6s"],
    "5/11": ["J5-9-11", (1760.3, 1608.5), "F5-11"],
    "11/13": ["J9-10-11-13", "J11-12-13-14"],
    "11/12": ["F11-12", "J11-12-13-14"],
    "12/14": ["J11-12-13-14", "F12-14"],
    "13/14": ["J11-12-13-14", (2200.5, 1890.6), (2282.1, 1858.8), "F13-14"],
}
# środki numerów rejonów (piksele zrzutu: zielone 1–14, pomarańczowe 15–17); jak na mapie PAŻP, kilka lekko przesuniętych,
# żeby w aplikacji nie nachodziły na etykiety i opisy BELOW (każdy numer musi leżeć w swoim rejonie)
NUM = {1: (1483, 578), 2: (1507, 369), 3: (1606, 744), 4: (1228, 1041), 5: (1730, 1500), 6: (1421, 1696),
       7: (2568, 730), 8: (2388, 1052), 9: (2194, 1303), 10: (2703, 1302), 11: (1695, 1800), 12: (2041, 2011),
       13: (2274, 1766), 14: (2336, 1980), 15: (2745, 812), 16: (2653, 1040), 17: (2745, 1723)}
# etykieta "SEKTOR n" z QNH rejonu (piksele zrzutu; miejsca dobrane na mapie aplikacji 1600x900 tak, żeby nie zasłaniały
# lotnisk, numerów ani opisów BELOW); pasy 15–17 bez etykiet
LABEL = {1: (1371, 568), 2: (1507, 291), 3: (1572, 822), 4: (1150, 1177), 5: (1423, 1364), 6: (1367, 1774),
         7: (2456, 740), 8: (2500, 1038), 9: (1993, 1168), 10: (2557, 1307), 11: (2065, 1790), 12: (2080, 1934),
         13: (2342, 1688), 14: (2541, 2025)}
# lotniska z METAR-em, z których bierzemy najniższe QNH rejonu: leżące w rejonie, a leżące na granicy (EPLY, EPLK, EPBC
# w wierzchołkach linii) we wszystkich stykających się rejonach; rejony 6, 12 i 14 nie mają własnego lotniska
# z METAR-em, więc biorą najbliższe (EPWR, EPKK, EPRZ); pasy 15–17 = wszystkie lotniska z METAR-em leżące w pasie
AIRPORTS = {
    1: ["EPSC", "EPSN", "EPMI", "EPDA"],
    2: ["EPGD", "EPOK", "EPPR", "EPCE", "EPMB"],
    3: ["EPBY"],
    4: ["EPPO", "EPKS", "EPPW", "EPZG", "EPIR", "EPLY", "EPLK"],
    5: ["EPWR", "EPLK"],
    6: ["EPWR"],
    7: ["EPSY"],
    8: ["EPMO", "EPMM", "EPBC"],
    9: ["EPWA", "EPLL", "EPTM", "EPRA", "EPLY", "EPLK", "EPBC"],
    10: ["EPLB", "EPDE"],
    11: ["EPKT", "EPKK"],
    12: ["EPKK"],
    13: ["EPRZ"],
    14: ["EPRZ"],
}
METAR = ("EPBC EPBY EPCE EPDA EPDE EPGD EPIR EPKK EPKS EPKT EPLB EPLK EPLL EPLY EPMB EPMI EPMM EPMO EPOK EPPO EPPR "
         "EPPW EPRA EPRZ EPSC EPSN EPSY EPTM EPWA EPWR EPZG").split()
BANDS = {15: (53.0, 90.0), 16: (51.0, 53.0), 17: (-90.0, 51.0)}

# obszary "BELOW TMA/MTMA QNH FROM EPxx" z mapy AIP (tylko z --image): liliowe wypełnienie TMA/MTMA/CTR dzielą pogrubione
# czarne linie; obszar lotniska = części wypełnienia osiągalne z punktów startowych (piksele zrzutu) bez przekraczania
# pogrubionej linii. TMA_CUTS = pogrubione linie przerwane napisem albo zlewające się z zieloną granicą rejonu.
# Pasek między TMA Poznań a MTMA Powidz (bez własnego opisu) dołączony do EPPW, bo opis "BELOW MTMA QNH FROM EPPW"
# stoi tuż pod nim.
TMA_SEEDS = {
    "EPGD": [(1748, 531)], "EPMB": [(1947, 671), (1872, 634)], "EPSC": [(1100, 765)], "EPSN": [(1300, 670)],
    "EPMI": [(1344, 815)], "EPBY": [(1700, 880)], "EPSY": [(2192, 773)], "EPPO": [(1469, 1140)],
    "EPPW": [(1696, 1154), (1595, 1190)], "EPZG": [(1273, 1188)], "EPWA": [(2194, 1208)],
    "EPMM": [(2507, 1146), (2402, 1168)], "EPLL": [(1982, 1313)], "EPLK": [(1905, 1432)],
    "EPRA": [(2391, 1461), (2225, 1462)], "EPDE": [(2469, 1377)], "EPLB": [(2578, 1504)], "EPWR": [(1480, 1530)],
    "EPKT": [(1877, 1732)], "EPKK": [(2058, 1836)], "EPRZ": [(2470, 1850)],
}
TMA_CUTS = [
    [(2083, 1320), (2067, 1350), (2066, 1397)],                                          # EPLL | EPWA (napis EPTM)
    [(2452.7, 1257.3), (2398.6, 1322.2), (2375.2, 1371.7), (2344.7, 1391.5)],             # EPWA | EPDE (granica 9/10)
    [(2128, 1439), (2147, 1414)],                                                        # EPWA | EPRA (napis MCTR EPTM)
    [(2243, 1412), (2277, 1397), (2300, 1391), (2346, 1391)],                            # EPWA | EPRA (EPRP)
    [(2016, 1626), (2015, 1710), (2005, 1785), (1975, 1815), (1920, 1835), (1795, 1839)],  # EPKT | EPKK
    [(1926.7, 581.7), (1880, 586.7), (1853.3, 615), (1826.7, 620), (1826.7, 678.3)],     # EPGD | EPMB
]

NOTE = ("QNH rejonu = najniższe aktualne QNH z lotnisk rejonu (METAR); oficjalne QNH regionalne liczy IMGW z modelu "
        "(najniższe ciśnienie w rejonie minus 3 hPa), więc może być niższe. Rejony 15–17 (pasy 53°N i 51°N) to "
        "wartości awaryjne, podawane tylko przy awarii modelu IMGW. Pod TMA/MTMA obowiązuje QNH lotniska z opisu "
        "„BELOW … QNH FROM”. Granice rejonów i obszary TMA/MTMA odrysowane z mapy AIP Polska (PAŻP) – orientacyjnie, "
        "do celów symulacji.")
UWAGA = ("Rejony 1-14 odrysowane z mapy rejonów QNH z AIP Polska (zrzut mapy PAŻP dostarczony przez Marka 2026-10-08) "
         "skryptem scripts/trace_qnh_regions.py (wierzchołki w pikselach zrzutu, odwzorowanie Lamberta dopasowane do "
         "siatki mapy), granica zewnętrzna 'fir' = FIR EPWW z pliku sektorowego (pokrywa się z mapą PAŻP). Plik "
         "generuje skrypt: zmiany granic, numerów, etykiet i list lotnisk rejonów wprowadzać w skrypcie. Rejony 15-17 "
         "(band) = pasy awaryjne: FIR podzielony równoleżnikami 53°N i 51°N (pomarańczowe linie na mapie PAŻP), QNH = "
         "najniższe z lotnisk z METAR-em w pasie. QNH rejonu = najniższe aktualne QNH z lotnisk w 'airports'. TMA: QNH z "
         "METAR-u lotniska 'icao' (pod TMA obowiązuje QNH tego lotniska); obszar 'aip' = obszar BELOW ... QNH FROM odrysowany "
         "z tego samego zrzutu (skrypt z --image), cienkie linie w środku = dolne warstwy .ese ('ese'), bez nich linie .sct "
         "('sct'). 'cap' = środek opisu BELOW (z ramką QNH lotniska) w pikselach względem lotniska przy zoomie domyślnym "
         "(jak na mapie PAŻP, kilka przesuniętych, żeby nie nachodziły na kody lotnisk), 'join' = lotniska dopisane do "
         "wspólnego opisu (EPKT w opisie EPKK). 'label'/'num' rejonów = [lon, lat] etykiety SEKTOR n i numeru. 'note' = "
         "objaśnienie pod tabelami.")


def _t(phi: float) -> float:
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - E * s) / (1 + E * s)) ** (E / 2)


def to_px(lon: float, lat: float, p: dict = LCC) -> tuple[float, float]:
    r = math.exp(p["lnC"]) * _t(math.radians(lat)) ** p["n"]
    th = math.radians(lon - p["lon0"]) * p["n"]
    return p["xp"] + r * math.sin(th), p["yp"] + r * math.cos(th)


def to_lonlat(x: float, y: float, p: dict = LCC) -> tuple[float, float]:
    r = math.hypot(x - p["xp"], y - p["yp"])
    lon = p["lon0"] + math.degrees(math.atan2(x - p["xp"], y - p["yp"]) / p["n"])
    t = (r / math.exp(p["lnC"])) ** (1 / p["n"])
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(8):
        s = math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(t * ((1 - E * s) / (1 + E * s)) ** (E / 2))
    return lon, math.degrees(phi)


def airports() -> dict[str, tuple[float, float]]:
    with open(SEED / "airports.csv", encoding="utf-8") as f:
        return {r["ident"]: (float(r["longitude_deg"]), float(r["latitude_deg"])) for r in csv.DictReader(f)}


def fir_ring() -> list[tuple[float, float]]:
    """Granica FIR EPWW z pliku sektorowego jako zamknięty pierścień (lon, lat)."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    sys.path.insert(0, str(ROOT))
    from backend.app.importers.sct import parse_line_groups, read_text, sections

    sct = sorted((ROOT / "data" / "import").glob("EPWW*.sct"))
    if not sct:
        sys.exit("Brak pliku data/import/EPWW-Sector.sct (granica FIR)")
    segs = parse_line_groups(sections(read_text(sct[0])).get("[ARTCC HIGH]", []))["FIR border 0 - EPWW"]
    polys = list(polygonize(unary_union([LineString([(a[1], a[0]), (b[1], b[0])]) for a, b in segs if a != b])))
    return list(max(polys, key=lambda p: p.area).exterior.coords)


def vertex(v, ads) -> tuple[float, float]:
    """Wierzchołek jako (lon, lat): węzeł, lotnisko albo piksel zrzutu."""
    if isinstance(v, str) and v in NODES:
        v = NODES[v]
    if isinstance(v, str) and v.startswith("@"):
        return ads[v[1:]]
    return to_lonlat(*v)


def build(fir: list) -> tuple[list[dict], dict]:
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import polygonize, unary_union

    ads = airports()
    firp = Polygon(fir)
    edge = firp.exterior
    lines = []
    for name, seq in LINES.items():
        pts = [vertex(v, ads) for v in seq]
        # koniec na granicy FIR: odcinek przedłużony do pierwszego przecięcia z granicą (punkt FIR, gdy bliżej niż ~50 m);
        # pierwsze, a nie najbliższe końcowi, żeby linia nie wychodziła poza FIR przy narożniku granicy
        for end, prev in ((0, 1), (-1, -2)):
            if isinstance(seq[end], str) and seq[end].startswith("F"):
                (x0, y0), (x1, y1) = pts[prev], pts[end]
                far = LineString([(x0, y0), (x1 + (x1 - x0) * 0.5, y1 + (y1 - y0) * 0.5)])
                hit = far.intersection(edge)
                cand = [hit] if hit.geom_type == "Point" else list(getattr(hit, "geoms", []))
                if not cand:
                    sys.exit(f"Linia {name}: koniec {seq[end]} nie przecina granicy FIR")
                p = min(cand, key=lambda q: q.distance(Point(x0, y0)))
                near = min(fir, key=lambda c: math.dist(c, (p.x, p.y)))
                pts[end] = near if math.dist(near, (p.x, p.y)) < 0.0005 else (p.x, p.y)
                # minimalnie za granicę, żeby polygonize na pewno połączyło linię z granicą FIR
                (x0, y0), (x1, y1) = pts[prev], pts[end]
                k = 0.0002 / math.dist((x0, y0), (x1, y1))
                pts[end] = (x1 + (x1 - x0) * k, y1 + (y1 - y0) * k)
        lines.append(LineString(pts))
    faces = [f for f in polygonize(unary_union([edge] + lines)) if firp.contains(f.representative_point())]
    regions = []
    for rid, (x, y) in sorted(NUM.items()):
        lon, lat = to_lonlat(x, y)
        reg = {"id": rid}
        if rid in BANDS:
            s, n = BANDS[rid]
            geom = firp.intersection(box(13, max(s, 48), 26, min(n, 56)))
            inside = [a for a in METAR if geom.contains(Point(ads[a]))]
            reg.update({"airports": inside, "band": True})
        else:
            hit = [f for f in faces if f.contains(Point(lon, lat))]
            if len(hit) != 1:
                sys.exit(f"Rejon {rid}: numer w {len(hit)} obszarach")
            geom = hit[0]
            reg.update({"airports": AIRPORTS[rid], "label": _r(to_lonlat(*LABEL[rid]), 3)})
        reg["num"] = _r((lon, lat), 3)
        if geom.geom_type == "MultiPolygon":   # pas 17: także "worek turoszowski" na zachód od Bogatyni
            parts = sorted(geom.geoms, key=lambda q: -q.area)
            reg["geometry"] = {"type": "MultiPolygon", "coordinates": [[_ring(q, True)] for q in parts]}
        else:
            reg["geometry"] = {"type": "Polygon", "coordinates": [_ring(geom, rid in BANDS)]}
        regions.append(reg)
    if len(faces) != 14:
        sys.exit(f"Podział FIR dał {len(faces)} obszarów zamiast 14")
    return regions, {"type": "Polygon", "coordinates": [[_r(c) for c in fir]]}


def _r(c, nd: int = 5) -> list[float]:
    return [round(c[0], nd), round(c[1], nd)]


def _ring(geom, band: bool) -> list[list[float]]:
    """Zewnętrzny pierścień (lon, lat) w kierunku przeciwnym do wskazówek zegara; w pasach odcinki wzdłuż równoleżnika
    zagęszczone co 0,1°, żeby w odwzorowaniu stożkowym biegły łukiem jak na mapie."""
    from shapely.geometry.polygon import orient

    pts = list(orient(geom, 1.0).exterior.coords)
    out = []
    for a, b in zip(pts, pts[1:]):
        out.append(_r(a))
        if band and abs(a[1] - b[1]) < 1e-9 and abs(a[1] - round(a[1])) < 1e-9:
            k = int(abs(b[0] - a[0]) / 0.1)
            out += [_r((a[0] + (b[0] - a[0]) * i / (k + 1), a[1])) for i in range(1, k + 1)]
    out.append(out[0])
    return out


def check(regions: list[dict], fir: dict) -> None:
    """Rejony 1–14 i pasy 15–17 pokrywają FIR bez dziur i nakładania; lotniska rejonów leżą w swoich rejonach."""
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union

    firp = shape(fir)
    ads = airports()
    for group in ([r for r in regions if not r.get("band")], [r for r in regions if r.get("band")]):
        polys = [shape(r["geometry"]) for r in group]
        union = unary_union(polys)
        over = sum(a.intersection(b).area for i, a in enumerate(polys) for b in polys[i + 1:])
        print(f"rejony {group[0]['id']}–{group[-1]['id']}: różnica z FIR {union.symmetric_difference(firp).area:.2e} "
              f"st.², nakładanie {over:.2e} st.²")
    for r in regions:
        g = shape(r["geometry"])
        inside = [a for a in METAR if g.buffer(0.002).contains(Point(ads[a]))]   # także na granicy rejonu
        out = [a for a in r["airports"] if a not in inside]
        print(f"{r['id']:>2}: lotniska z METAR-em w rejonie {' '.join(inside) or '–'}"
              f"{'; spoza rejonu: ' + ' '.join(out) if out else ''}")


def overlay(image: str, out: str, regions: list[dict], tma: dict | None = None) -> None:
    """Granice z pliku narysowane z powrotem na zrzucie (rejony magenta, pasy pomarańczowe, obszary TMA niebieskie,
    numery w kółkach, etykiety w prostokątach) – do kontroli wzrokowej."""
    from PIL import Image, ImageDraw

    im = Image.open(image).convert("RGB")
    d = ImageDraw.Draw(im)
    for g in (tma or {}).values():
        for poly in g["coordinates"]:
            d.line([to_px(*c) for c in poly[0]], fill=(0, 90, 255), width=2)
    for r in regions:
        g = r["geometry"]
        for poly in [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]:
            d.line([to_px(*c) for c in poly[0]], fill=(255, 140, 0) if r.get("band") else (230, 0, 230),
                   width=2 if r.get("band") else 3)
    for r in regions:
        x, y = to_px(*r["num"])
        d.ellipse((x - 6, y - 6, x + 6, y + 6), outline=(0, 0, 255), width=2)
        if "label" in r:   # etykieta SEKTOR n (ok. 68x30 px w aplikacji przy zoomie domyślnym = 165x73 px zrzutu)
            x, y = to_px(*r["label"])
            d.rectangle((x - 82, y - 36, x + 82, y + 36), outline=(0, 0, 255), width=2)
    im.save(out)
    print(f"nakładka: {out}")


def _grow(mask, k: int):
    """Dylatacja (k > 0) albo erozja (k < 0) maski kwadratem (2|k|+1) px."""
    import numpy as np
    from PIL import Image, ImageFilter

    im = Image.fromarray(mask.astype(np.uint8) * 255)
    f = ImageFilter.MaxFilter(2 * k + 1) if k > 0 else ImageFilter.MinFilter(-2 * k + 1)
    return np.asarray(im.filter(f)) > 127


def _polygon(mask, x0: int, y0: int):
    """Maska (wycinek od x0, y0) jako wielokąt shapely w pikselach zrzutu: suma prostokątów z odcinków wierszy."""
    import numpy as np
    from shapely.geometry import box
    from shapely.ops import unary_union

    boxes = []
    for y, row in enumerate(mask):
        d = np.diff(np.r_[0, row.astype(np.int8), 0])
        boxes += [box(x0 + a, y0 + y, x0 + b, y0 + y + 1) for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0])]
    return unary_union(boxes)


def trace_tma(image: str) -> dict[str, dict]:
    """Obszary "BELOW … QNH FROM" lotnisk z liliowego wypełnienia zrzutu (MultiPolygon lon/lat dla każdego lotniska)."""
    import numpy as np
    from PIL import Image, ImageDraw

    a = np.asarray(Image.open(image).convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gray = (r + g + b) / 3
    purple = (b > g + 8) & (r > g + 2) & (gray > 150) & (gray < 245)
    purple[:, :905] = purple[:, 2936:] = False
    # zielone/pomarańczowe linie i niebieska otoczka przecinające TMA należą do wypełnienia
    col = ((g > r + 50) & (g > b + 40) & (g > 100)) | ((r > 170) & (g > 80) & (g < 175) & (b < 90) & (r > g + 50)) \
        | ((abs(r - 194) < 25) & (abs(g - 217) < 20) & (abs(b - 236) < 20) & (b > r + 25))
    fill = _grow(_grow(purple | (col & _grow(purple, 8)), 3), -3)
    # pogrubione linie: ciemne piksele, których czterej sąsiedzi też są ciemni (linia >= 3 px), z powrotem poszerzone
    dark = gray < 110
    core = dark.copy()
    core[1:] &= dark[:-1]
    core[:-1] &= dark[1:]
    core[:, 1:] &= dark[:, :-1]
    core[:, :-1] &= dark[:, 1:]
    bold = _grow(core, 2) & dark
    cut = Image.new("L", (a.shape[1], a.shape[0]), 0)
    for c in TMA_CUTS:
        ImageDraw.Draw(cut).line(c, fill=255, width=5)
    cells = fill & ~_grow(bold, 1) & ~(np.asarray(cut) > 0)
    canvas = Image.fromarray(cells.astype(np.uint8) * 255)
    out = {}
    for icao, seeds in TMA_SEEDS.items():
        work = canvas.copy()
        for sx, sy in seeds:
            # punkt startowy na najbliższym pikselu wypełnienia (napisy i symbole wycinają dziury)
            ys, xs = np.nonzero(cells[sy - 15:sy + 16, sx - 15:sx + 16])
            k = int(np.argmin((xs - 15) ** 2 + (ys - 15) ** 2))
            ImageDraw.floodfill(work, (int(sx - 15 + xs[k]), int(sy - 15 + ys[k])), 128, thresh=0)
        m = np.asarray(work) == 128
        ys, xs = np.nonzero(m)
        y0, y1, x0, x1 = ys.min() - 12, ys.max() + 13, xs.min() - 12, xs.max() + 13
        sub = m[y0:y1, x0:x1]
        # domknięcie (cienkie linie i napisy w środku), wypełnienie dziur, poszerzenie do osi pogrubionej linii
        sub = _grow(_grow(sub, 4), -4)
        bg = Image.fromarray((~sub).astype(np.uint8) * 255).copy()   # kopia: obraz z tablicy jest tylko do odczytu
        ImageDraw.floodfill(bg, (0, 0), 128, thresh=0)
        sub = _grow(np.asarray(bg) != 128, 2)
        poly = _polygon(sub, x0, y0).simplify(1.5)
        parts = sorted(getattr(poly, "geoms", [poly]), key=lambda q: -q.area)
        parts = [q for q in parts if q.area > 300]
        out[icao] = {"type": "MultiPolygon", "coordinates": [
            [[_r(to_lonlat(x, y), 4) for x, y in q.exterior.coords]] for q in parts]}
        print(f"{icao}: {len(parts)} część/i, {sum(len(q.exterior.coords) for q in parts)} wierzchołków")
    return out


def fit(image: str) -> None:
    """Dopasowanie odwzorowania do siatki zrzutu: szare piksele południków 14–24°E i równoleżników 50–55°N."""
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(image).convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    grey = (abs(r - g) < 10) & (abs(g - b) < 10) & (r > 110) & (r < 225)
    ys, xs = np.nonzero(grey[45:2150, 905:2936])
    ys, xs = ys + 45.0, xs + 905.0
    p0 = np.array([LCC["xp"], LCC["yp"], LCC["n"], LCC["lnC"], LCC["lon0"]])

    def inv(p, x, y):
        rr = np.hypot(x - p[0], y - p[1])
        lon = p[4] + np.degrees(np.arctan2(x - p[0], y - p[1]) / p[2])
        t = (rr / np.exp(p[3])) ** (1 / p[2])
        phi = np.pi / 2 - 2 * np.arctan(t)
        for _ in range(6):
            s = np.sin(phi)
            phi = np.pi / 2 - 2 * np.arctan(t * ((1 - E * s) / (1 + E * s)) ** (E / 2))
        return lon, np.degrees(phi)

    # punkty siatki: piksele leżące (wg bieżącego odwzorowania) blisko pełnego stopnia długości albo szerokości
    lon, lat = inv(p0, xs, ys)
    dlon, dlat = lon - np.round(lon), lat - np.round(lat)
    mer = (np.abs(dlon) * 200 < 2) & (np.round(lon) >= 14) & (np.round(lon) <= 24)
    par = (np.abs(dlat) * 313 < 2) & (np.round(lat) >= 50) & (np.round(lat) <= 55) & ~mer
    P = np.r_[np.c_[xs[mer], ys[mer], np.zeros(mer.sum()), np.round(lon[mer])],
              np.c_[xs[par], ys[par], np.ones(par.sum()), np.round(lat[par])]]

    def res(p):
        lo, la = inv(p, P[:, 0], P[:, 1])
        return np.where(P[:, 2] == 0, (lo - P[:, 3]) * 200, (la - P[:, 3]) * 313)

    p = p0.copy()
    for _ in range(20):
        r0 = res(p)
        jac = np.stack([(res(p + np.eye(5)[k] * 1e-6 * max(1, abs(p[k]))) - r0) / (1e-6 * max(1, abs(p[k])))
                        for k in range(5)], 1)
        p = p + np.linalg.lstsq(jac, -r0, rcond=None)[0]
    r0 = res(p)
    print(f"punkty siatki: {len(P)}, błąd średni {np.sqrt((r0 ** 2).mean()):.2f} px")
    print("LCC =", {k: round(float(v), 7) for k, v in zip(("xp", "yp", "n", "lnC", "lon0"), p)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--image", help="zrzut mapy PAŻP (3840x2160) do --overlay i --fit")
    ap.add_argument("--overlay", help="zapisz nakładkę granic na zrzucie do tego pliku PNG")
    ap.add_argument("--fit", action="store_true", help="dopasuj odwzorowanie do siatki zrzutu i wypisz parametry")
    ap.add_argument("--dry-run", action="store_true", help="bez zapisu pliku JSON")
    args = ap.parse_args()
    if args.fit:
        if not args.image:
            sys.exit("--fit wymaga --image")
        fit(args.image)
        return
    if args.overlay and not args.image:
        sys.exit("--overlay wymaga --image")
    regions, fir = build(fir_ring())
    check(regions, fir)
    tma = trace_tma(args.image) if args.image else None
    if args.overlay:
        overlay(args.image, args.overlay, regions, tma)
    if args.dry_run:
        return
    cfg = json.loads(OUT.read_text("utf-8"))
    cfg.update({"_uwaga": UWAGA, "note": NOTE, "fir": fir, "regions": regions})
    for t in cfg.get("tmas", []) if tma else []:
        if t["icao"] in tma:
            t["aip"] = tma[t["icao"]]
    order = ["_uwaga", "note", "regions", "tmas", "fir"]
    cfg = {k: cfg[k] for k in order + [k for k in cfg if k not in order] if k in cfg}
    # jeden rejon / jedna TMA w wierszu, jak w ręcznie pisanym pliku
    def dump(k, v):
        sep = (", ", ": ") if k == "tmas" else (",", ":")
        if isinstance(v, list):
            return "[\n" + ",\n".join(json.dumps(x, ensure_ascii=False, separators=sep) for x in v) + "\n]"
        return json.dumps(v, ensure_ascii=False, separators=(", ", ": ") if isinstance(v, str) else sep)

    body = ",\n".join(f'"{k}": {dump(k, v)}' for k, v in cfg.items())
    OUT.write_text("{" + body + "}\n", "utf-8")
    print(f"zapisano {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
