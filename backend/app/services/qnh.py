"""Mapa QNH regionalnego (METEO › QNH) jak mapa rejonów QNH z AIP Polska (PAŻP): data/seed/qnh_regions.json.

Plik rejonów generuje scripts/trace_qnh_regions.py: rejony 1–14 i pasy awaryjne 15–17, obszary TMA/MTMA
"BELOW … QNH FROM EPxx" z cienkimi liniami części TMA, CTR/MCTR i granica FIR z plików sektorowych (MTMA/MCTR,
których w nich nie ma, z mapy PAŻP) oraz ręczny układ napisów. Tu: QNH z METAR-ów, lotniska z bazy, linia brzegowa
z pliku .sct i model rozmiarów napisów (qnhmap.js, qnh.css) do testu nakładania i skryptu (--layout)."""

import json
import math
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, settings
from ..importers.sct import parse_line_groups, read_text, sections
from ..models import Aerodrome, NavPoint
from .http_cache import UpstreamError
from .metar import parse_metar

_Seg = list[list[float]]


def config() -> dict:
    return json.loads((settings.seed_dir / "qnh_regions.json").read_text("utf-8"))


def _chains(segs: list[_Seg]) -> list[list[tuple]]:
    """Odcinki [[lat, lon], [lat, lon]] sklejone w łamane (mniej danych niż osobne odcinki)."""
    adj: dict[tuple, list[int]] = {}
    for i, (a, b) in enumerate(segs):
        adj.setdefault(tuple(a), []).append(i)
        adj.setdefault(tuple(b), []).append(i)
    used = [False] * len(segs)

    def grow(line: list[tuple]) -> None:
        while len(adj[line[-1]]) == 2:
            nxt = next((j for j in adj[line[-1]] if not used[j]), None)
            if nxt is None:
                return
            used[nxt] = True
            a, b = map(tuple, segs[nxt])
            line.append(b if a == line[-1] else a)

    out = []
    for i, (a, b) in enumerate(segs):
        if used[i]:
            continue
        used[i] = True
        line = [tuple(a), tuple(b)]
        grow(line)
        line.reverse()
        grow(line)
        out.append(line)
    return out


def _lonlat(line) -> list[list[float]]:
    return [[round(p[1], 4), round(p[0], 4)] for p in line]


@lru_cache(maxsize=1)
def coast() -> dict | None:
    """Linia brzegowa z sekcji [GEO] pliku .sct (grupa "... Coastlines"), rysowana szarym kolorem jak na mapie AIP."""
    for f in sorted((DATA_DIR / "import").glob("*.sct")):
        for name, segs in parse_line_groups(sections(read_text(f)).get("[GEO]", [])).items():
            if "coast" in name.lower():
                return {"type": "MultiLineString", "coordinates": [_lonlat(c) for c in _chains(segs)]}
    return None


# lądowiska w miejscu lotniska z METAR-em (np. EPSW = EPLB, EPIN obok EPIR) pomijamy, żeby kody się nie nakładały
NEAR_LAT, NEAR_LON = 0.04, 0.06


def drawn_aerodromes(ads: list[dict], metar: set[str], sides: dict[str, str]) -> list[dict]:
    """Lotniska na mapie: {icao, lat, lon, metar (symbol lotniska kontrolowanego), label (strona kodu ICAO)}."""
    main = [a for a in ads if a["icao"] in metar]
    dup = lambda a: a["icao"] not in metar and any(  # noqa: E731
        abs(m["lat"] - a["lat"]) < NEAR_LAT and abs(m["lon"] - a["lon"]) < NEAR_LON for m in main)
    return [{"icao": a["icao"], "lat": a["lat"], "lon": a["lon"], "metar": a["icao"] in metar,
             "label": sides.get(a["icao"], "e")} for a in sorted(ads, key=lambda a: a["icao"]) if not dup(a)]


async def regions(db: Session, get_metars) -> dict:
    """Rejony QNH i TMA/MTMA z QNH (data/seed/qnh_regions.json); get_metars: funkcja pobierająca METAR-y.

    QNH rejonu = najniższe QNH z lotnisk rejonu ("airports"; w pasach awaryjnych 15–17 wszystkie lotniska pasa),
    QNH TMA = QNH z METAR-u lotniska "icao" (pod TMA obowiązuje QNH tego lotniska). Do mapy: granica FIR EPWW,
    linia brzegowa, obszary TMA, CTR/MCTR, wszystkie lotniska EP i układ napisów z pliku rejonów."""
    cfg = config()
    tmas = cfg.get("tmas", [])
    icaos = sorted({a for r in cfg["regions"] for a in r["airports"]} | {t["icao"] for t in tmas})
    error = None
    try:
        raw = await get_metars(icaos)
    except UpstreamError as exc:
        raw, error = {}, f"METAR source unavailable: {exc}"
    qnh = {i: parse_metar(m).qnh for i, m in raw.items() if m}
    ads = db.scalars(select(Aerodrome).where(Aerodrome.icao.like("EP%"))).all()
    pos = {a.icao: (a.lat, a.lon) for a in ads}
    for p in db.scalars(select(NavPoint).where(NavPoint.kind == "AD", NavPoint.ident.in_(icaos))):
        pos.setdefault(p.ident, (p.lat, p.lon))
    for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(icaos))):
        pos.setdefault(a.icao, (a.lat, a.lon))
    at = lambda i: dict(zip(("lat", "lon"), pos.get(i, (None, None))))  # noqa: E731
    out_regions = []
    for r in cfg["regions"]:
        vals = [qnh[a] for a in r["airports"] if qnh.get(a)]
        out_regions.append({**r, "qnh": min(vals) if vals else None, "max": max(vals) if vals else None,
                            "stations": [{"icao": a, "qnh": qnh.get(a), **at(a)} for a in r["airports"]]})
    out_tmas = [{**{k: v for k, v in t.items() if k != "ese"}, "qnh": qnh.get(t["icao"]), **at(t["icao"])}
                for t in tmas]
    rows = [{"icao": a.icao, "lat": a.lat, "lon": a.lon} for a in ads]
    return {"note": cfg.get("note"), "regions": out_regions, "tmas": out_tmas, "error": error, "fir": cfg.get("fir"),
            "ctrs": cfg.get("ctrs", []), "overlaps": cfg.get("overlaps"), "chart_labels": cfg.get("chart_labels", []),
            "coast": coast(), "aerodromes": drawn_aerodromes(rows, set(icaos), cfg.get("aero_labels", {}))}


# --- model napisów mapy (qnhmap.js, qnh.css) do testu nakładania (test_qnh.py) i skryptu (--layout)
# Odwzorowanie jak lccCrs() w qnhmap.js: stożkowe Lamberta na kuli R, stała stożka 0,798, południk 19°E,
# r0 na 52°N, skala jak w EPSG:3857 (256 px na obwód przy zoomie 0).
LCC_R, LCC_N = 6378137, 0.798
# zoom domyślnego widoku (cały FIR) przy oknie 1600x900 i 1366x768; skala napisów jak labelScale() w qnhmap.js
# (--k w CSS: 2^(zoom − 7,5), nie mniej niż 80%, poniżej QR_FAR 70%); odstęp między napisami w px
VIEWS = {"1600x900": 7.5, "1366x768": 7.2}
QR_ZOOM, QR_FAR, QR_MIN, QR_MIN_FAR = 7.5, 7.15, 0.8, 0.7
GAP = 1.0
# czcionka o stałej szerokości: Consolas 0,55 em, zastępcze Liberation Mono / DejaVu Sans Mono 0,6 em (model bierze
# szerszą, więc w Consolas odstępy tylko rosną)
CH = 0.6
# rozmiary z qnh.css przy skali 1: (czcionka px, wysokość wiersza px)
NUM = (28, 20)             # numer rejonu
QBOX = (11, 13)            # ramka QNH przy numerze: + 2 px obwódki, + 2x2 px wcięcia
CAP = (9, 11)              # opis BELOW … QNH FROM (ramka QNH w wierszu: + 2 px obwódki, + 2x1 px wcięcia)
DES = (7.5, 8)             # szare oznaczenia TMA/CTR
AERO = (8, 9)              # kod ICAO lotniska
SYM = 9                    # symbol lotniska (romb / kółko z kropką), px
SIDE_GAP = 2               # odstęp kodu ICAO od symbolu i ramki QNH od numeru
SIDES = ("e", "w", "n", "s", "ne", "nw", "se", "sw")


def px(lon: float, lat: float, zoom: float) -> tuple[float, float]:
    """Piksele mapy (x w prawo, y w dół) przy zoomie jak w Leaflecie z lccCrs()."""
    d = math.pi / 180
    tn = lambda phi: math.tan(math.pi / 4 + phi / 2) ** LCC_N   # noqa: E731
    f = math.cos(math.asin(LCC_N)) * tn(math.asin(LCC_N)) / LCC_N
    r, t = LCC_R * f / tn(lat * d), LCC_N * (lon - 19) * d
    s = 0.5 / (math.pi * LCC_R) * 256 * 2 ** zoom
    return r * math.sin(t) * s, -(LCC_R * f / tn(52 * d) - r * math.cos(t)) * s


def scale(zoom: float) -> float:
    """Skala napisów jak labelScale() w qnhmap.js."""
    return min(1.0, max(QR_MIN_FAR if zoom < QR_FAR else QR_MIN, 2 ** (zoom - QR_ZOOM)))


def _side(cx: float, cy: float, hw: float, hh: float, w: float, h: float, side: str, gap: float) -> tuple:
    """Prostokąt w x h przy prostokącie o środku (cx, cy) i połowach boków hw, hh po stronie side."""
    dx = {"e": 1, "w": -1, "n": 0, "s": 0, "ne": 1, "nw": -1, "se": 1, "sw": -1}[side]
    dy = {"e": 0, "w": 0, "n": -1, "s": 1, "ne": -1, "nw": -1, "se": 1, "sw": 1}[side]
    x = cx + dx * (hw + gap + w / 2) if dx else cx
    y = cy + dy * (hh + gap + h / 2) if dy else cy
    if dx and dy:   # w narożniku: dolny / górny brzeg ramki na wysokości środka
        y = cy + dy * (h / 2)
    return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def text_box(lines: list[str], size: tuple, k: float, extra_w: float = 0, extra_h: float = 0,
             boxed: bool = False) -> tuple[float, float]:
    """Szerokość i wysokość bloku tekstu (wiersze wyśrodkowane) przy skali k; boxed: ostatni wiersz kończy się
    ramką QNH (extra_w tylko do niego)."""
    fs, lh = size
    widths = [len(s) * CH * fs for s in lines]
    if boxed:
        widths[-1] += extra_w
    else:
        widths = [w + extra_w for w in widths]
    return max(widths) * k, (len(lines) * lh + extra_h) * k


def caption_lines(t: dict) -> tuple[list[str], bool]:
    """Wiersze opisu TMA i czy ostatni kończy się ramką QNH: "BELOW TMA" / "QNH FROM EPxx 1013"; z 'stack' QNH
    w trzecim wierszu (węższy opis), z 'code' bez kodu i bez QNH (są w osobnym napisie)."""
    if t.get("code"):
        return [f"BELOW {t['below']}", "QNH FROM"], False
    if t.get("stack"):
        return [f"BELOW {t['below']}", f"QNH FROM {t['icao']}", "1013"], True
    return [f"BELOW {t['below']}", f"QNH FROM {t['icao']} 1013"], True


def label_boxes(cfg: dict, aerodromes: list[dict], zoom: float) -> list[tuple[str, str, tuple]]:
    """Prostokąty napisów mapy w pikselach przy zoomie: (rodzaj, nazwa, (x0, y0, x1, y1)); rodzaje: num, qnh, cap,
    code, des, sym (symbol lotniska), aero (kod lotniska)."""
    out = []
    k = scale(zoom)
    for r in cfg["regions"]:
        x, y = px(*r["num"], zoom)
        w, h = text_box([str(r["id"])], NUM, k)
        out.append(("num", str(r["id"]), (x - w / 2, y - h / 2, x + w / 2, y + h / 2)))
        qw, qh = text_box(["1013"], QBOX, k, 6, 2, True)
        out.append(("qnh", str(r["id"]), _side(x, y, w / 2, h / 2, qw, qh, r.get("qnh_at", "e"), SIDE_GAP * k)))
    for t in cfg["tmas"]:
        if t.get("cap"):
            lines, boxed = caption_lines(t)
            w, h = text_box(lines, CAP, k, 4 if boxed else 0, 2 if boxed else 0, boxed)
            x, y = px(*t["cap"], zoom)
            out.append(("cap", t["icao"], (x - w / 2, y - h / 2, x + w / 2, y + h / 2)))
        if t.get("code"):
            w, h = text_box([f"{t['icao']} 1013"], CAP, k, 4, 2, True)
            x, y = px(*t["code"], zoom)
            out.append(("code", t["icao"], (x - w / 2, y - h / 2, x + w / 2, y + h / 2)))
    for c in cfg.get("chart_labels", []):
        w, h = text_box(c["lines"], DES, k)
        x, y = px(*c["lonlat"], zoom)
        out.append(("des", " ".join(c["lines"]), (x - w / 2, y - h / 2, x + w / 2, y + h / 2)))
    for a in aerodromes:
        x, y = px(a["lon"], a["lat"], zoom)
        s = SYM * k / 2
        out.append(("sym", a["icao"], (x - s, y - s, x + s, y + s)))
        w, h = text_box([a["icao"]], AERO, k)
        out.append(("aero", a["icao"], _side(x, y, s, s, w, h, a.get("label", "e"), SIDE_GAP * k)))
    return out


def clash(a: tuple, b: tuple, gap: float = GAP) -> bool:
    """Czy dwa napisy (rodzaj, nazwa, prostokąt) nachodzą na siebie (bliżej niż gap px); symbole lotnisk mogą się
    stykać, a kod lotniska i ramka QNH rejonu przylegają do własnego symbolu / numeru."""
    (ka, na, ra), (kb, nb, rb) = a, b
    if ka == kb == "sym" or (na == nb and {ka, kb} in ({"sym", "aero"}, {"num", "qnh"})):
        return False
    return min(ra[2], rb[2]) - max(ra[0], rb[0]) > -gap and min(ra[3], rb[3]) - max(ra[1], rb[1]) > -gap


def overlaps(boxes: list[tuple[str, str, tuple]], gap: float = GAP) -> list[tuple]:
    """Pary nachodzących na siebie napisów (clash)."""
    return [((a[0], a[1]), (b[0], b[1])) for i, a in enumerate(boxes) for b in boxes[i + 1:] if clash(a, b, gap)]
