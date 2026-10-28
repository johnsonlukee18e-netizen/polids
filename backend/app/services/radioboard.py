"""RADIO jako jedna strona, jak w systemie PANDORA (GET /api/radio/board).

Trzy podglądy FIR EPWW: sektory ACC w warstwach LOW, MID i HIGH (data/seed/ownership.json), a do tego warstwy
APP (TMA), TWR (CTR lotnisk), FIS i pasek ATIS. Każda etykieta ma kolejność przejmowania (chain); właściciel to
pierwsze stanowisko z tej kolejności, które jest teraz online (dopasowanie z /api/radio/online, z aliasami sąsiadów).
Sąsiedzi (0.13.0): okienka FIR-ów sąsiednich w siatce strony wg szkicu Marka (data/seed/radio_layout.json); kolejność
przejmowania okienka z kafelków sektorów graniczących z FIR EPWW jak w VACS (profil ACC_EPWW z data/seed/vacs_epww.json,
bez FMP); okienko obsługuje pierwsze stanowisko online z tej kolejności (controlled_by), okienka jednego stanowiska
łączymy (merge_boxes).

Część zależna tylko od danych z importu (wycinki, kafelki, punkty etykiet, geometria) jest liczona raz i trzymana
w pamięci do zmiany bazy, ownership.json albo vacs_epww.json; przy każdym odświeżeniu liczymy tylko, kto jest online."""

import json
import math
import re
from collections import Counter
from fnmatch import fnmatchcase
from itertools import combinations

from .metar import parse_metar
from .radio import facility, sector_group, sector_kind
from .runways import atis_state, wind_components

LAYERS = ("LOW", "MID", "HIGH")
TOP_FT = 66000  # FL660: górna granica podglądów (Kaliningrad ma w pliku 99900)

# FIR-y sąsiednie na stronie RADIO (okienka wg szkicu, radio_layout.json): kod i nazwa do dymku i panelu LOA.
# Kafelki sąsiadów (stack_tiles) dają okienkom kolejność przejmowania; stosów jako takich strona już nie rysuje (0.13.0).
STACKS = (
    {"fir": "ESAA", "title": "SVERIGE"},
    {"fir": "EDWW", "title": "BREMEN"},
    {"fir": "EDUU", "title": "RHEIN"},
    {"fir": "EDMM", "title": "MÜNCHEN"},
    {"fir": "LKAA", "title": "PRAHA"},
    {"fir": "UMKK", "title": "KALININGRAD"},
    {"fir": "EYVL", "title": "VILNIUS"},
    {"fir": "UMMV", "title": "MINSK"},
    {"fir": "UKLV", "title": "LVIV"},
    {"fir": "LZBB", "title": "BRATISLAVA"},
)
STACK_FIRS = {s["fir"] for s in STACKS}
# kafelek VACS → stos: pierwszy człon etykiety (EYVL U → EYVL); lotniska i FIR-y bez własnego stosu do stosu obok
STACK_ALIAS = {"EDDB": "EDWW", "ESMM": "ESAA", "LKMT": "LKAA", "UMBB": "UMMV", "UKR": "UKLV", "UKLU": "UKLV",
               "UKLL": "UKLV", "LZTT": "LZBB"}
ALT = re.compile(r"^(?:\+(\d{2,3})|-(\d{2,3})|(\d{2,3})-(\d{2,3}))$")  # wysokość kafelka VACS: +365, -165, 285-365
APP_TYPES = {"APP", "DEP"}
INFO = re.compile(r"_(?:I|IE|IW|IS|IN|FIS)_[A-Z]+$")  # stanowiska informacji (EPWA_I_APP, EPGD_IE_APP)
DIR_SLICE = re.compile(r"^EP[A-Z]{2}_DIR\d")  # wycinki dyrektora przy pasie (EPWA_DIR11_A, EPKK_DIR07)
ACC_CS = re.compile(r"^EPWW_[A-Z0-9_]*(?:CTR|FSS)$")
FIS_NAME = re.compile(r"^FIS_|^[A-Z]{3}_FIS_|^EPWW-MIDSEA$")
EP_ICAO = re.compile(r"EP[A-Z]{2}")


# --- kolejność przejmowania (jak frontend/js/chains.js)
def tma_topdown(name: str, own: dict) -> dict | None:
    for key, v in (own.get("tma_topdown") or {}).items():
        if any(name.startswith(p) for p in v.get("ese_prefixes") or ()):
            return {"name": key, **v}
    return None


def air_chain(name: str, owners: list[str], own: dict) -> list[str]:
    """Kolejność dla wycinka spoza sektorów ACC: stanowiska z listy OWNER przed pierwszym ACC, potem ACC – dla TMA
    z tabeli top-down om.plvacc.pl (tma_topdown), gdy prefiks wycinka pasuje – i to, co plik stawia za ACC."""
    lst = [o for o in owners if o]
    first = next((i for i, cs in enumerate(lst) if ACC_CS.match(cs)), len(lst))
    local, rest = lst[:first], lst[first:]
    tail = [cs for cs in rest if not ACC_CS.match(cs)]
    t = tma_topdown(name, own)
    acc_part = t["chain"] if t and t.get("chain") else [cs for cs in rest if ACC_CS.match(cs)]
    out = list(local)
    for cs in [*acc_part, *tail]:
        if cs not in out:
            out.append(cs)
    return out


def is_on(cs: str, online: dict) -> bool:
    return cs in online and facility(cs) != "ATIS"


def first_online(chain, online: dict) -> str | None:
    return next((cs for cs in chain if is_on(cs, online)), None)


def owners_of_chains(chains, online: dict) -> list[str]:
    """Właściciele kilku wycinków jednej etykiety: różne pierwsze stanowiska online, od najczęstszego."""
    cnt = Counter(o for ch in chains if (o := first_online(ch, online)))
    return [cs for cs, _ in cnt.most_common()]


# --- geometria
def rings(geom: dict) -> list[list]:
    """Zewnętrzne pierścienie Polygon/MultiPolygon."""
    if not geom:
        return []
    if geom.get("type") == "Polygon":
        return [geom["coordinates"][0]] if geom.get("coordinates") else []
    if geom.get("type") == "MultiPolygon":
        return [p[0] for p in geom.get("coordinates") or [] if p]
    return []


def ring_area(ring) -> float:
    if len(ring) < 3:
        return 0.0
    k = math.cos(math.radians(ring[0][1]))
    s = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))
    return abs(s) * k / 2


def geom_area(geom: dict) -> float:
    return sum(ring_area(r) for r in rings(geom))


def label_point(geom: dict, n: int = 22) -> list[float] | None:
    """[lat, lon] wewnątrz wielokąta, możliwie daleko od krawędzi (próbki na siatce, jak labelPoint w coverage.js)."""
    best, best_d = None, -1.0
    for ring in rings(geom):
        if len(ring) < 3:
            continue
        k = math.cos(math.radians(ring[0][1]))
        pts = [(x * k, y) for x, y in ring]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        for i in range(n):
            for j in range(n):
                x, y = x0 + (x1 - x0) * (i + 0.5) / n, y0 + (y1 - y0) * (j + 0.5) / n
                inside, d = False, math.inf
                for a in range(len(pts)):
                    ax, ay = pts[a]
                    bx, by = pts[a - 1]
                    if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                        inside = not inside
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy
                    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2)) if l2 else 0.0
                    d = min(d, math.hypot(x - ax - t * dx, y - ay - t * dy))
                if inside and d > best_d:
                    best_d, best = d, [round(y, 4), round(x / k, 4)]
    return best


def simplify(geom: dict, tol: float = 0.003, nd: int = 3) -> dict:
    """Uproszczona geometria do rysowania podglądów (Douglas–Peucker, zaokrąglenie do ~100 m)."""
    def dp(pts):
        if len(pts) < 3:
            return pts
        keep = [False] * len(pts)
        keep[0] = keep[-1] = True
        stack = [(0, len(pts) - 1)]
        while stack:
            a, b = stack.pop()
            (ax, ay), (bx, by) = pts[a], pts[b]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            best, bi = -1.0, -1
            for i in range(a + 1, b):
                px, py = pts[i]
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2)) if l2 else 0.0
                d = math.hypot(px - ax - t * dx, py - ay - t * dy)
                if d > best:
                    best, bi = d, i
            if best > tol:
                keep[bi] = True
                stack += [(a, bi), (bi, b)]
        return [p for p, k in zip(pts, keep) if k]

    out = []
    for ring in rings(geom):
        r = dp([[round(x, nd), round(y, nd)] for x, y in ring])
        if len(r) >= 3:
            out.append([r])
    return {"type": "MultiPolygon", "coordinates": out}


# --- część stała: z bazy po imporcie i z ownership.json
def make_slice(fir: str, name: str, lo: int, hi: int, owners: list[str], geom: dict) -> dict:
    return {"fir": fir, "name": name, "lo": lo, "hi": min(hi, TOP_FT), "owners": owners, "geom": geom}


def acc_sectors(own: dict) -> list[dict]:
    """Sektory ACC × warstwy: id jak w PANDORZE bez numeru (litera warstwy + litera sektora: LB, MC, HN),
    nominal = pierwsze stanowisko kolejności (stanowisko sektora)."""
    out = []
    for letter in sorted(own.get("sectors") or {}):
        for ly in LAYERS:
            chain = (own["sectors"][letter] or {}).get(ly) or []
            if chain:
                out.append({"id": ly[0] + letter, "letter": letter, "layer": ly, "chain": chain, "nominal": chain[0]})
    return out


def _icao_of(names: list[str]) -> str | None:
    cnt = Counter(m.group() for n in names if (m := EP_ICAO.match(n)))
    return cnt.most_common(1)[0][0] if cnt else None


def _largest(slices: list[dict]) -> dict:
    return max(slices, key=lambda s: geom_area(s["geom"]))


def _local(chain: list[str]) -> list[str]:
    """Stanowiska z kolejności przed pierwszym sektorem ACC, bez informacji (EPWA_I_APP)."""
    out = []
    for cs in chain:
        if ACC_CS.match(cs):
            break
        if not INFO.search(cs):
            out.append(cs)
    return out


def directors(slices: list[dict]) -> set[str]:
    """Stanowiska dyrektora (WA DIR = EPWA_F_APP, KK DIR, KT DIR): pierwsze tylko w wycinkach EPxx_DIRnn. To nie są
    sektory podejścia – ich wycinki należą do części TMA następnego APP z kolejności."""
    first: dict[str, set[bool]] = {}
    for s in slices:
        if loc := _local(s["chain"]):
            first.setdefault(loc[0], set()).add(bool(DIR_SLICE.search(s["name"])))
    return {cs for cs, k in first.items() if k == {True} and facility(cs) in APP_TYPES}


def part_owner(chain: list[str], dirs: set[str]) -> str | None:
    """Stanowisko części TMA: pierwsze APP z kolejności (bez dyrektora i informacji); TMA proceduralna (bez APP,
    np. Szczecin: EPSC_TWR, potem ACC) – pierwsze stanowisko, czyli wieża lotniska."""
    loc = _local(chain)
    return next((cs for cs in loc if facility(cs) in APP_TYPES and cs not in dirs), loc[0] if loc else None)


# siatka do punktu etykiety części TMA (stopnie: ok. 3,3 km × 3,4 km w rejonie Polski)
GRID_LAT, GRID_LON = 0.03, 0.05


def _cells(geoms: list[dict], box: tuple[float, float, float, float]) -> set[tuple[int, int]]:
    """Komórki siatki w ramce box (lon0, lat0, lon1, lat1), których środek leży w którymś z wielokątów."""
    x0, y0 = box[0], box[1]
    out: set[tuple[int, int]] = set()
    for g in geoms:
        for ring in rings(g):
            lats = [p[1] for p in ring]
            for j in range(max(0, int((min(lats) - y0) / GRID_LAT) - 1), int((max(lats) - y0) / GRID_LAT) + 1):
                y = y0 + (j + 0.5) * GRID_LAT
                xs = sorted(ax + (y - ay) * (bx - ax) / (by - ay)
                            for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]) if (ay > y) != (by > y))
                for a, b in zip(xs[::2], xs[1::2]):
                    out.update((i, j) for i in range(math.ceil((a - x0) / GRID_LON - 0.5),
                                                     math.floor((b - x0) / GRID_LON - 0.5) + 1))
    return out


def part_anchor(own: list[dict], other: list[dict]) -> list[float] | None:
    """[lat, lon] punktu etykiety części TMA: najdalej od krawędzi jej własnego obszaru w rzucie (bez miejsc, które
    zajmuje też inna część tej TMA, np. górne wycinki WA N nad WA APP); bez własnego obszaru – cała część."""
    pts = [p for s in own + other for r in rings(s["geom"]) for p in r]
    if not pts:
        return None
    box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    mine = _cells([s["geom"] for s in own], box)
    area = (mine - _cells([s["geom"] for s in other], box)) or mine
    if not area:
        return label_point(_largest(own)["geom"])
    # odległość od krawędzi obszaru: mapa odległości (chamfer, dwa przejścia) na siatce z marginesem 1 komórki
    k = math.cos(math.radians((box[1] + box[3]) / 2)) * GRID_LON / GRID_LAT  # komórka: szerokość / wysokość
    i0, j0 = min(i for i, _ in area) - 1, min(j for _, j in area) - 1
    nx, ny = max(i for i, _ in area) - i0 + 2, max(j for _, j in area) - j0 + 2
    d = [[math.inf if (i + i0, j + j0) in area else 0.0 for i in range(nx)] for j in range(ny)]
    steps = ((-1, 0, k), (0, -1, 1.0), (-1, -1, math.hypot(k, 1)), (1, -1, math.hypot(k, 1)))
    for sgn, js, is_ in ((1, range(ny), range(nx)), (-1, range(ny - 1, -1, -1), range(nx - 1, -1, -1))):
        for j in js:
            row = d[j]
            for i in is_:
                if row[i]:
                    for di, dj, w in steps:
                        a, b = i + sgn * di, j + sgn * dj
                        if 0 <= a < nx and 0 <= b < ny and d[b][a] + w < row[i]:
                            row[i] = d[b][a] + w
    cx = sum(i for i, _ in area) / len(area) - i0
    cy = sum(j for _, j in area) / len(area) - j0
    # najdalej od krawędzi; przy równych bliżej środka obszaru
    _, _, i, j = max((d[j][i], -math.hypot((i - cx) * k, j - cy), i, j) for j in range(ny) for i in range(nx) if d[j][i])
    return [round(box[1] + (j + j0 + 0.5) * GRID_LAT, 4), round(box[0] + (i + i0 + 0.5) * GRID_LON, 4)]


def _box(sl: list[dict]) -> list[float]:
    pts = [p for s in sl for r in rings(s["geom"]) for p in r]
    return [round(min(p[0] for p in pts), 3), round(min(p[1] for p in pts), 3),
            round(max(p[0] for p in pts), 3), round(max(p[1] for p in pts), 3)] if pts else []


def tma_parts(slices: list[dict], own: dict) -> tuple[dict[str, tuple[str | None, dict[str, list[dict]]]], set[str]]:
    """Wycinki TMA w częściach: {TMA: (ICAO, {stanowisko części: [wycinki z kolejnością]})} i stanowiska dyrektora.
    Wspólne części kilku TMA (EPPO_EPGD_…) i CTA pomijamy (tylko je rysujemy)."""
    by: dict[str, list[dict]] = {}
    for s in slices:
        if len(set(EP_ICAO.findall(s["name"]))) > 1 or s["name"].startswith("CTA"):
            continue
        t = tma_topdown(s["name"], own)
        group = sector_group("EPWW", s["name"], "tma")
        key = t["name"] if t and t["name"].replace("TMA ", "") not in group else group
        by.setdefault(key, []).append({**s, "chain": air_chain(s["name"], s["owners"], own)})
    dirs = directors([s for sl in by.values() for s in sl])
    out = {}
    for key, sl in by.items():
        parts: dict[str, list[dict]] = {}
        for s in sl:
            if owner := part_owner(s["chain"], dirs):
                parts.setdefault(owner, []).append(s)
        out[key] = (_icao_of([s["name"] for s in sl]), parts)
    return out, dirs


def tma_groups(slices: list[dict], own: dict) -> list[dict]:
    """Warstwa APP: TMA podzielone na części wg stanowiska części (part_owner): TMA Warszawa = WA APP, WA N APP
    i WA S APP, TMA Kraków = KK APP i KK E APP, TMA Gdańsk = GD L APP (TMA) i GD APP (UTMA); TMA proceduralne
    (Szczecin, Lublin, Mazury) z wieżą lotniska. Jedna etykieta na część: punkt w jej własnym obszarze, ramka
    (box) do odsunięcia etykiety poza TMA. Wspólne części kilku TMA (EPPO_EPGD_…) i CTA tylko rysujemy."""
    out = []
    for key, (icao, parts) in tma_parts(slices, own)[0].items():
        for nominal, psl in parts.items():
            other = [s for cs, p in parts.items() if cs != nominal for s in p]
            out.append({"id": key if len(parts) == 1 else f"{key} · {nominal}", "tma": key, "icao": icao,
                        "at": part_anchor(psl, other), "box": _box(psl), "nominal": nominal,
                        "chains": _uniq_chains(psl),
                        "lo": min(s["lo"] for s in psl), "hi": max(s["hi"] for s in psl)})
    return sorted(out, key=lambda g: g["id"])


def _uniq_chains(sl: list[dict]) -> list[list[str]]:
    """Różne kolejności wycinków, od najczęstszej."""
    cnt = Counter(tuple(s["chain"]) for s in sl)
    return [list(c) for c, _ in cnt.most_common()]


def ctr_groups(slices: list[dict], own: dict, coords: dict, positions: dict) -> list[dict]:
    """Warstwa TWR: CTR lotnisk (wieża = pierwsze stanowisko TWR z listy OWNER), ATIS lotniska do TWR/ATIS; ramka CTR
    (box) do odsunięcia etykiety obok CTR; centre = środek CTR (najdalej od krawędzi) na plakietkę wieży (0.13.0)."""
    by: dict[str, list[dict]] = {}
    for s in slices:
        by.setdefault(sector_group("EPWW", s["name"], "ctr"), []).append({**s, "chain": air_chain(s["name"], s["owners"], own)})
    out = []
    for key, sl in by.items():
        icao = _icao_of([s["name"] for s in sl])
        chains = _uniq_chains(sl)
        nominal = next((cs for ch in chains for cs in ch if facility(cs) == "TWR"), chains[0][0] if chains[0] else None)
        if not nominal:
            continue
        at = list(coords[icao]) if icao in coords else label_point(_largest(sl)["geom"])
        atis = f"{icao}_ATIS" if f"{icao}_ATIS" in positions else None
        out.append({"id": key, "icao": icao, "at": at, "box": _box(sl), "nominal": nominal, "chains": chains,
                    "atis": atis, "hi": max(s["hi"] for s in sl), "centre": part_anchor(sl, []) or at})
    return sorted(out, key=lambda g: g["id"])


def fis_groups(slices: list[dict], own: dict) -> list[dict]:
    """Warstwa FIS: rejony FIS (wycinki FIS_…, MIDSEA) wg stanowiska, które jest w nich pierwsze."""
    by: dict[str, list[dict]] = {}
    for s in slices:
        if not FIS_NAME.match(s["name"]) or not s["owners"]:
            continue
        by.setdefault(s["owners"][0], []).append({**s, "chain": air_chain(s["name"], s["owners"], own)})
    out = []
    for nominal, sl in by.items():
        big = _largest(sl)
        out.append({"id": sector_group("EPWW", big["name"], "fis"), "nominal": nominal, "at": label_point(big["geom"]),
                    "chains": _uniq_chains(sl), "hi": max(s["hi"] for s in sl)})
    return sorted(out, key=lambda g: (g["id"], g["nominal"]))


def alt_range(alt) -> tuple[int, int] | None:
    """Wysokość kafelka VACS w stopach (dolna, górna): "+365" → (36500, TOP_FT), "285-365" → (28500, 36500),
    "-165" → (0, 16500); brak albo nieczytelna → None (kafelek bez wysokości, np. EDWW MRZ, UMKK)."""
    m = ALT.match(str(alt or "").strip())
    if not m:
        return None
    up, down, lo, hi = (int(x) * 100 if x else None for x in m.groups())
    return (up, TOP_FT) if up is not None else (0, down) if down is not None else (lo, hi)


def stack_key(label: str) -> str | None:
    first = str(label or "").split(" ")[0].upper()
    first = STACK_ALIAS.get(first, first)
    return first if first in STACK_FIRS else None


_RANK = {"CTR": 0, "FSS": 0, "APP": 1, "DEP": 1, "TWR": 2}
RADAR = ("CTR", "FSS")


def first_chains(chains) -> dict[str, list[str]]:
    """Kolejność z plików .ese dla stanowiska: najczęstsza lista OWNER wycinków, w których to stanowisko jest pierwsze."""
    cnt: dict[str, Counter] = {}
    for ch in chains or ():
        if ch := [cs for cs in ch if cs]:
            cnt.setdefault(ch[0], Counter())[tuple(ch)] += 1
    return {cs: list(c.most_common(1)[0][0]) for cs, c in cnt.items()}


def chain_tails(chains) -> dict[str, list[str]]:
    """Kto dalej przejmuje stanowisko wg plików .ese: najczęstszy niepusty ogon list OWNER za nim (UMMV_CTR → RU-WRC_FSS
    z wycinka UMMV N, choć w wycinkach UMMV W jest ostatni)."""
    cnt: dict[str, Counter] = {}
    for ch in chains or ():
        ch = [cs for cs in ch if cs]
        for i, cs in enumerate(ch[:-1]):
            cnt.setdefault(cs, Counter())[tuple(ch[i + 1:])] += 1
    return {cs: list(c.most_common(1)[0][0]) for cs, c in cnt.items()}


def _same_stack(cs: str, key: str | None) -> bool:
    """Stanowisko tego stosu (EDDB_N_APP → EDWW) albo regionalne bez kodu ICAO (RU-WRC_FSS); nie CTR innego FIR-u."""
    first = cs.split("_")[0]
    return "-" in first or stack_key(first) == key


def tile_chain(chain: list[str], own: str, ese: dict[str, list[str]], main: str | None,
               tails: dict[str, list[str]] | None = None, key: str | None = None) -> list[str]:
    """Kolejność kafelka: controlled_by z VACS, a gdy nie ma w niej żadnego CTR poza samym kafelkiem (UMMV N, UKLV,
    EDDB N APP), dalej lista OWNER z pliku .ese wycinka tego stanowiska (UMMV_W_CTR → UMMV_CTR, EDDB_N_APP → EDWW_…_CTR),
    bez takiego wycinka – to, co pliki .ese stawiają za nim (tails: UMMV_CTR → RU-WRC_FSS), a kafelek APP/TWR bez
    niczego przejmuje główny CTR FIR-u (main). Kolejność kończąca się na głównym CTR idzie dalej jego ogonem z .ese
    (UMMV W, UMBB TWR: … › UMMV_CTR › RU-WRC_FSS, jak UMMV N); bez CTR innych stosów (key = stos kafelka). Kolejność
    VACS zostaje pierwsza."""
    def tail(cs: str) -> list[str]:
        return [x for x in (tails or {}).get(cs, ()) if x not in chain and _same_stack(x, key)]

    if not any(facility(cs) in RADAR and cs != own for cs in chain):
        extra = ese.get(own) or tail(own) or ([main] if main and facility(own) not in RADAR else [])
        chain = chain + [cs for cs in extra if cs not in chain]
    if main and chain[-1] == main:
        chain = chain + tail(main)
    return chain


def stack_tiles(items: list[dict], ese: dict[str, list[str]] | None = None, known=(),
                tails: dict[str, list[str]] | None = None) -> dict[str, list[dict]]:
    """Kafelki stosów sąsiadów z profilu VACS ACC_EPWW (vacs_epww.json, klucz neighbours): tylko sektory graniczące
    z EPWW, bez FMP. Kafelek: etykieta i wysokość z VACS, stanowisko kafelka (callsign) i kolejność przejmowania
    (chain = controlled_by, uzupełniona top-down z plików .ese: tile_chain; ese = first_chains, tails = chain_tails,
    known = znane znaki do głównego CTR FIR-u). W stosie od najwyższego zakresu; bez wysokości jak do FL660 od ziemi,
    CTR przed APP i TWR."""
    out: dict[str, list[dict]] = {}
    seen = set()
    for n in items or ():
        if not isinstance(n, dict) or n.get("fmp"):
            continue
        key = stack_key(n.get("label"))
        chain = [cs for cs in n.get("controlled_by") or () if cs] or ([n["callsign"]] if n.get("callsign") else [])
        uid = (n.get("label"), n.get("alt"), n.get("station"), n.get("callsign"))
        if not key or not chain or uid in seen:
            continue
        seen.add(uid)
        rng = alt_range(n.get("alt"))
        own = n.get("callsign") or chain[0]
        main = f"{key}_CTR" if f"{key}_CTR" in known else None
        out.setdefault(key, []).append({"label": n["label"], "alt": n.get("alt") if rng else None,
                                        "lo": rng[0] if rng else None, "hi": rng[1] if rng else None,
                                        "callsign": own, "chain": tile_chain(chain, own, ese or {}, main, tails, key)})
    for tiles in out.values():
        tiles.sort(key=lambda t: (-(t["hi"] or TOP_FT), -(t["lo"] or 0), _RANK.get(facility(t["callsign"]), 3)))
    return out


# --- sąsiedzi na podglądach (0.12.5, Marek): sektory ACC FIR-ów sąsiednich (podgląd pokazuje te na swoim poziomie,
# jak sektory EPWW) oraz TMA i CTR lotnisk sąsiadów przy granicy FIR EPWW (warstwy APP i TWR, jak TMA/CTR EPWW)
NB_NEAR_KM = 15  # wycinek APP/TWR sąsiada „przy granicy”: dotyka granicy FIR EPWW albo leży najwyżej tyle od niej
NB_FAR_KM = 50   # reszta wycinków tego samego stanowiska (cała TMA Ostrawa), ale nie w głąb kraju (TMA Praga)
NB_INFO = re.compile(r"_(?:I|IE|IW|IS|IN|FIS|FIC|INFO)_[A-Z]+$")  # informacja (EYKA_I_APP): to nie APP ani ACC
NB_LOCAL = ("APP", "DEP", "TWR")
_KM_LAT = 111.2


def nb_kind(name: str, owners: list[str]) -> str | None:
    """Rodzaj wycinka sąsiada wg pierwszego stanowiska z listy OWNER: acc (CTR/FSS), app (TMA: APP/DEP, TMA wieży
    jak LZTT_TMA), twr (CTR lotniska: nazwa z CTR albo wieża bez TMA, np. EDAH); None = informacja (FIS), ziemia
    (GND/DEL) albo wycinek bez stanowisk – nie rysujemy."""
    first = owners[0] if owners else ""
    if not first or NB_INFO.search(first):
        return None
    fac = facility(first)
    if fac in RADAR:
        return "acc"
    if fac not in NB_LOCAL:
        return None
    n = name.upper()
    return "twr" if "CTR" in n or (fac == "TWR" and "TMA" not in n) else "app"


def _km(lon: float, lat: float) -> tuple[float, float]:
    """Punkt w kilometrach (rzut lokalny: długość × cos szerokości) – do odległości rzędu kilkudziesięciu km."""
    return lon * _KM_LAT * math.cos(math.radians(lat)), lat * _KM_LAT


class _Border:
    """Odcinki granicy FIR EPWW w km w siatce (komórka CELL km) do szybkiego szukania najbliższego odcinka."""
    CELL = 20.0

    def __init__(self, geom: dict):
        self.grid: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
        for ring in rings(geom):
            pts = [_km(x, y) for x, y in ring]
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
                c = self.CELL
                for i in range(math.floor(min(ax, bx) / c), math.floor(max(ax, bx) / c) + 1):
                    for j in range(math.floor(min(ay, by) / c), math.floor(max(ay, by) / c) + 1):
                        self.grid.setdefault((i, j), []).append((ax, ay, bx, by))

    def dist(self, x: float, y: float, cap: float) -> float:
        """Odległość punktu (km) od granicy; dalej niż cap → inf."""
        c, n, best = self.CELL, math.ceil(cap / self.CELL), math.inf
        ci, cj = math.floor(x / c), math.floor(y / c)
        for i in range(ci - n, ci + n + 1):
            for j in range(cj - n, cj + n + 1):
                for ax, ay, bx, by in self.grid.get((i, j), ()):
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy
                    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2)) if l2 else 0.0
                    best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
        return best if best <= cap else math.inf

    def to_geom(self, geom: dict, cap: float, step: float = 4.0) -> float:
        """Najmniejsza odległość obrysu wielokąta od granicy (km, do cap): wierzchołki i punkty co `step` km na
        bokach – bok przecinający granicę daje punkt najwyżej step/2 od niej."""
        best = math.inf
        for ring in rings(geom):
            pts = [_km(x, y) for x, y in ring]
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
                k = max(1, math.ceil(math.hypot(bx - ax, by - ay) / step))
                for t in range(k):
                    best = min(best, self.dist(ax + (bx - ax) * t / k, ay + (by - ay) * t / k, cap))
                    if best < step / 2:
                        return best
        return best


def nb_areas(slices: list[dict], border_geom: dict) -> list[dict]:
    """Wycinki sąsiadów na podglądy: wszystkie sektory ACC (wycinki z plików .ese sąsiadów są już tylko z rejonu
    Polski) oraz TMA/CTR stanowisk APP/TWR, które mają wycinek przy granicy FIR EPWW (NB_NEAR_KM), z ich wycinkami
    do NB_FAR_KM od granicy. slices: [{fir, name, lo, hi, owners (znaki), geom}]. Wynik:
    [{id, fir, name, kind (acc/app/twr), lo, hi, chain, geom}] (id: n0, n1… w kolejności wejścia)."""
    border = _Border(border_geom)
    out, local = [], []
    for s in slices:
        kind = nb_kind(s["name"], s["owners"])
        if not kind or s["lo"] >= TOP_FT:
            continue
        a = {"fir": s["fir"], "name": s["name"], "kind": kind, "lo": s["lo"], "hi": min(s["hi"], TOP_FT),
             "chain": list(s["owners"]), "geom": s["geom"]}
        if kind == "acc":
            out.append(a)
        else:
            local.append((a, border.to_geom(s["geom"], NB_FAR_KM)))
    near = {a["chain"][0] for a, d in local if d <= NB_NEAR_KM}
    out += [a for a, d in local if a["chain"][0] in near and d <= NB_FAR_KM]
    return [{"id": f"n{i}", **a} for i, a in enumerate(out)]


# --- układ strony wg szkicu (0.13.0, issue #23): okienka FIR-ów sąsiednich w siatce, łączenie okienek jednego
# stanowiska, wskaźniki u góry (ACC GAT, APP GD, APP WA, APP KK, APP PO), BERLIN, czerwone tło przy ograniczeniach
# przepływu i plakietki APP/TWR tylko dla zalogowanych. Siatka, id, granice i reguły: data/seed/radio_layout.json.
MERGE_FIRS = frozenset({"EDUU", "EDMM", "ESAA", "EYVL", "LZBB", "LKAA"})  # EDWW nigdy (Marek)
FREQ = re.compile(r"^1[1-3]\d\.\d{2,3}$")
OBS_FREQ = "199.998"


def _cell(c: dict, col: int = 0, row: int = 0) -> dict:
    """Komórka albo prostokąt siatki z seeda: {col, row, cols, rows} (cols/rows domyślnie 1)."""
    return {"col": int(c.get("col") or col), "row": int(c.get("row") or row),
            "cols": int(c.get("cols") or 1), "rows": int(c.get("rows") or 1)}


def _cells_of(c: dict) -> set[tuple[int, int]]:
    return {(x, y) for x in range(c["col"], c["col"] + c["cols"]) for y in range(c["row"], c["row"] + c["rows"])}


def _tile_for(tiles: list[dict], label: str, callsign: str | None) -> dict | None:
    """Kafelek stosu o tej etykiecie; dwa o tej samej (LKAA N górny i dolny) rozróżnia stanowisko okienka."""
    same = [t for t in tiles if t["label"] == label]
    return next((t for t in same if t["callsign"] == callsign), same[0] if same else None)


def layout_static(layout: dict, tiles: dict[str, list[dict]]) -> dict:
    """Część stała układu z radio_layout.json: okienka FIR-ów z kolejnością przejmowania z kafelków stosów (tiles:
    stack_tiles; kilka kafelków = ich stanowiska, potem ich kolejności, bez powtórek), stanowiska FIR-u do dymku (area: stanowiska
    kafelków tego FIR-u i z ich kolejności o prefiksie tego FIR-u, także z kafelków, których szkic nie ma), zajęte
    komórki siatki (occupied: do łączenia okienek tylko przez puste komórki)."""
    title = {s["fir"]: s["title"] for s in STACKS}
    occupied: dict[tuple[int, int], str] = {}
    firs = []
    for f in layout.get("firs") or ():
        fir = f["fir"]
        mine = tiles.get(fir, [])
        name = _cell(f.get("name") or {})
        occupied.update(dict.fromkeys(_cells_of(name), f"name:{fir}"))
        boxes = []
        for b in f.get("boxes") or ():
            # kilka kafelków (ACC UMMV): najpierw ich stanowiska po kolei, potem reszta ich kolejności
            found = [t for label in b.get("tiles") or () if (t := _tile_for(mine, label, b.get("callsign")))]
            chain: list[str] = []
            for cs in [t["callsign"] for t in found] + [cs for t in found for cs in t["chain"]]:
                if cs not in chain:
                    chain.append(cs)
            box = {"id": str(b["id"]), **_cell(b), "upper": b["upper"], "lower": b["lower"],
                   "callsign": b.get("callsign") or (chain[0] if chain else None), "tiles": list(b.get("tiles") or ()),
                   "chain": chain}
            occupied.update(dict.fromkeys(_cells_of(box), f"box:{fir}:{box['id']}"))
            boxes.append(box)
        area = sorted({t["callsign"] for t in mine} | {cs for t in mine for cs in t["chain"] if _same_stack(cs, fir)})
        firs.append({"fir": fir, "title": title.get(fir, ""), "name": name, "merge": bool(f.get("merge")),
                     "boxes": boxes, "area": area})
    inds = []
    for i in layout.get("indicators") or ():
        c = _cell(i)
        occupied.update(dict.fromkeys(_cells_of({**c, "rows": 2}), f"ind:{i['id']}"))  # nazwa i pod nią wartość
        inds.append({**i, **c})
    berlin = layout.get("berlin") or {}
    if berlin:
        berlin = {**_cell(berlin), "box": _cell(berlin.get("box") or {}, berlin.get("col", 1), berlin.get("row", 1) + 1)}
        occupied.update(dict.fromkeys(_cells_of(berlin) | _cells_of(berlin["box"]), "berlin"))
    buttons = layout.get("buttons") or {}
    for row in (buttons.get("rows") or {}).values():
        occupied[(int(buttons.get("col") or 0), int(row))] = "buttons"
    # podglądy (prostokąty LOW, HIGH, MID), stan danych i legenda: stałe miejsca, połączone okienko ich nie zajmie
    maps = {k: _cell(v) for k, v in (layout.get("maps") or {}).items()}
    for k, c in maps.items():
        occupied.update(dict.fromkeys(_cells_of(c), f"map:{k}"))
    places = {k: _cell(layout[k]) for k in ("status", "legend") if layout.get(k)}
    for k, c in places.items():
        occupied.update(dict.fromkeys(_cells_of(c), k))
    grid = layout.get("grid") or {}
    return {"grid": grid, "buttons": buttons, "maps": maps, **places,
            "tracks": col_kinds(occupied, int(grid.get("cols") or 0), int(buttons.get("col") or 0)),
            "indicators": inds, "berlin": berlin, "firs": firs, "occupied": occupied}


def col_kinds(occupied: dict, cols: int, button_col: int) -> list[str]:
    """Rodzaj każdej kolumny siatki do jej szerokości na stronie (stała, niezależna od tego, kto jest online): btn =
    przyciski warstw, box = okienka, wskaźniki, BERLIN i legenda, name = same nazwy FIR-ów (EYVL, UMMV, UKLV z prawej),
    map = reszta (podglądy LOW i HIGH; dzielą wolne miejsce)."""
    tags: dict[int, set[str]] = {}
    for (x, _), tag in occupied.items():
        tags.setdefault(x, set()).add(tag.split(":")[0])
    out = []
    for x in range(1, max([cols, *tags]) + 1 if tags or cols else 1):
        t = tags.get(x, set())
        out.append("btn" if x == button_col else "box" if t & {"box", "ind", "berlin", "legend"}
                   else "name" if "name" in t else "map")
    return out


def freq_of(cs: str | None, online: dict, positions: dict | None = None) -> str | None:
    """Częstotliwość stanowiska: z sieci (zalogowany), inaczej z listy stanowisk."""
    if not cs:
        return None
    return (online.get(cs) or {}).get("frequency") or ((positions or {}).get(cs) or {}).get("frequency") or None


def merge_key(cs: str | None, online: dict) -> str | None:
    """Klucz łączenia okienek: częstotliwość zalogowanego (dwa znaki na jednej częstotliwości to jedno okienko),
    bez poprawnej częstotliwości (obserwator 199.998) – jego znak w sieci."""
    if not cs or cs not in online:
        return None
    on = online[cs]
    fq = str(on.get("frequency") or "")
    return f"fq:{fq}" if FREQ.match(fq) and fq != OBS_FREQ else f"cs:{on.get('callsign') or cs}"


def _member(b: dict) -> dict:
    return {"id": b["id"], "upper": b["upper"], "lower": b["lower"], "callsign": b["callsign"]}


def _single(b: dict) -> dict:
    return {**{k: b[k] for k in ("id", "col", "row", "cols", "rows", "upper", "lower", "callsign", "chain", "owner",
                                 "staffed", "frequency")}, "label": b["id"], "members": [_member(b)], "merged": False}


def merged_label(members: list[dict], owner: str, fir: str) -> str:
    """Nazwa połączonego okienka: okienko, którego stanowiskiem jest właściciel (EYVL_CTR → L); bez takiego albo przy
    kilku (LKAA_U_CTR w NU i SU) – środek znaku właściciela (LKAA_U_CTR → U), a bez środka – kod FIR-u (ESAA_CTR)."""
    own = [m for m in members if m["callsign"] == owner]
    if len(own) == 1:
        return own[0]["id"]
    parts = owner.split("_")
    return " ".join(parts[1:-1]) if len(parts) > 2 else fir


def _merged(members: list[dict], fir: str) -> dict:
    members = sorted(members, key=lambda b: (b["row"], b["col"]))
    owner = Counter(b["owner"] for b in members).most_common(1)[0][0]
    label = merged_label(members, owner, fir)
    head = next((b for b in members if b["id"] == label), None)
    c0, c1 = min(b["col"] for b in members), max(b["col"] + b["cols"] - 1 for b in members)
    r0, r1 = min(b["row"] for b in members), max(b["row"] + b["rows"] - 1 for b in members)
    return {"id": "+".join(b["id"] for b in members), "label": label, "col": c0, "row": r0, "cols": c1 - c0 + 1,
            "rows": r1 - r0 + 1, "upper": max(b["upper"] for b in members), "lower": min(b["lower"] for b in members),
            "callsign": head["callsign"] if head else owner, "chain": head["chain"] if head else [], "owner": owner,
            "staffed": True, "frequency": next((b["frequency"] for b in members if b["owner"] == owner), None),
            "members": [_member(b) for b in members], "merged": True}


def merge_boxes(boxes: list[dict], occupied: dict, fir: str) -> list[dict]:
    """Łączenie okienek jednego FIR-u, które teraz obsługuje to samo stanowisko (merge_key: ten sam znak albo ta sama
    częstotliwość); nieobsadzonych nie łączymy. Jedno okienko na prostokąt komórek wszystkich takich okienek, gdy
    w prostokącie są tylko one i puste komórki (ESAA 9, 6, 8, 7 i pusta obok L; LKAA NU i SU obok siebie), inaczej
    tylko ciągi jedno pod drugim w kolumnie (bez innego okienka między nimi: EDUU OSE2 i HVL2 rozdziela OSE1).
    Połączone: granice od najwyższej górnej do najniższej dolnej, nazwa – merged_label, members – okienka w środku.
    boxes: [{id, col, row, cols, rows, upper, lower, callsign, chain, owner, staffed, frequency, key}]."""
    groups: dict[str, list[dict]] = {}
    for b in boxes:
        if b.get("key") and b.get("owner"):
            groups.setdefault(b["key"], []).append(b)
    taken: set[tuple[int, int]] = set()
    done: set[str] = set()
    out = []

    def free(cells: set, mine: set) -> bool:
        return not cells & taken and all(c in mine or c not in occupied for c in cells)

    def accept(members: list[dict]):
        m = _merged(members, fir)
        taken.update(_cells_of(m))
        done.update(b["id"] for b in members)
        out.append(m)

    for members in groups.values():
        if len(members) < 2:
            continue
        mine = set().union(*(_cells_of(b) for b in members))
        c0, c1 = min(x for x, _ in mine), max(x for x, _ in mine)
        r0, r1 = min(y for _, y in mine), max(y for _, y in mine)
        if free({(x, y) for x in range(c0, c1 + 1) for y in range(r0, r1 + 1)}, mine):
            accept(members)
            continue
        for col in sorted({b["col"] for b in members if b["cols"] == 1}):
            run: list[dict] = []
            for b in sorted((b for b in members if b["col"] == col and b["cols"] == 1), key=lambda b: b["row"]):
                gap = {(col, y) for y in range(run[-1]["row"] + run[-1]["rows"], b["row"])} if run else set()
                if run and not free(gap | _cells_of(b), mine):
                    if len(run) > 1:
                        accept(run)
                    run = []
                run.append(b)
            if len(run) > 1:
                accept(run)
    out += [_single(b) for b in boxes if b["id"] not in done]
    return sorted(out, key=lambda b: (b["row"], b["col"]))


def _who(cs: str, online: dict) -> dict:
    """Zalogowany do dymku: znak w sieci, stanowisko, częstotliwość, imię i nazwisko."""
    on = online.get(cs) or {}
    return {"callsign": on.get("callsign") or cs, "position": cs, "frequency": on.get("frequency") or "",
            "name": on.get("name")}


def fir_blocks(lay: dict, online: dict, positions: dict | None = None, net_ok: bool = True) -> list[dict]:
    """Okienka FIR-ów sąsiednich: właściciel = pierwsze stanowisko online z kolejności okienka, łączenie (tylko
    MERGE_FIRS z merge=true w seedzie). advisory: cały FIR bez nikogo (strona: ADVISORY 122.800 pod nazwą FIR-u;
    przy błędzie sieci nie wiadomo, więc bez). online: zalogowani tego FIR-u do dymku."""
    out = []
    for f in lay.get("firs") or ():
        boxes = []
        for b in f["boxes"]:
            o = first_online(b["chain"], online)
            boxes.append({**b, "owner": o, "staffed": bool(o), "frequency": freq_of(o, online, positions),
                          "key": merge_key(o, online)})
        rendered = merge_boxes(boxes, lay.get("occupied") or {}, f["fir"]) \
            if f["merge"] and f["fir"] in MERGE_FIRS else [_single(b) for b in boxes]
        staffed = any(b["staffed"] for b in boxes)
        who, seen = [], set()
        for cs in [*(b["owner"] for b in boxes if b["owner"]), *f["area"]]:
            if is_on(cs, online) and (real := (online[cs].get("callsign") or cs)) not in seen:
                seen.add(real)
                who.append(_who(cs, online))
        out.append({"fir": f["fir"], "title": f["title"], "name": f["name"], "merge": f["merge"], "staffed": staffed,
                    "advisory": net_ok and not staffed, "online": sorted(who, key=lambda w: w["callsign"]),
                    "boxes": rendered})
    return out


def online_matching(patterns, online: dict) -> list[str]:
    """Zalogowane stanowiska pasujące do wzorców (znak albo wzorzec z *, np. EPPO_*_APP), bez informacji i ATIS;
    ten sam kontroler pod dwoma stanowiskami raz. Kolejność wzorców, potem znaków."""
    out, seen = [], set()
    for p in patterns or ():
        for cs in sorted(online):
            real = online[cs].get("callsign") or cs
            if fnmatchcase(cs, p) and is_on(cs, online) and not INFO.search(cs) and cs not in out and real not in seen:
                seen.add(real)
                out.append(cs)
    return out


def indicator_value(rule: dict, online: dict, sectors: list[dict], acc_short: dict[str, str]) -> tuple[str, list[str]]:
    """Wartość wskaźnika u góry strony i liczone stanowiska; nikt → "0".
    acc: skróty zalogowanych ACC EPWW, od tego, który ma najwięcej sektorów (szkic: ALL+S);
    count: liczba zalogowanych (APP GD, APP PO); hl: H = APP radar, L = dyrektor (APP WA: H, 2H, 2H+L, L);
    ab: a-b, a = APP, b = dyrektorzy (APP KK: 1-0)."""
    kind = rule.get("rule")
    if kind == "acc":
        cnt = Counter(s["owner"] for s in sectors if s.get("owner"))
        on = sorted((cs for cs in acc_short if is_on(cs, online)), key=lambda cs: (-cnt[cs], acc_short[cs]))
        return "+".join(acc_short[cs] for cs in on) or "0", on
    if kind == "hl":
        h, lo = online_matching(rule.get("h"), online), online_matching(rule.get("l"), online)
        hp = ("H" if len(h) == 1 else f"{len(h)}H") if h else ""
        lp = ("L" if len(lo) == 1 else f"{len(lo)}L") if lo else ""
        return ("+".join(x for x in (hp, lp) if x) or "0"), h + lo
    if kind == "ab":
        a, b = online_matching(rule.get("a"), online), online_matching(rule.get("b"), online)
        return (f"{len(a)}-{len(b)}" if a or b else "0"), a + b
    n = online_matching(rule.get("count"), online)
    return str(len(n)), n


def indicators(lay: dict, online: dict, sectors: list[dict], acc_short: dict[str, str]) -> list[dict]:
    out = []
    for r in lay.get("indicators") or ():
        value, counted = indicator_value(r, online, sectors, acc_short)
        out.append({"id": r["id"], **{k: r[k] for k in ("col", "row", "cols", "rows")}, "tip": r.get("tip") or "",
                    "value": value, "positions": [_who(cs, online) for cs in counted]})
    return out


# BERLIN (Marek): konfiguracja pasów EDDB z ATIS (24/25 = WEST, 06/07 = EAST; numery sprzed 2024 też), bez ATIS
# preferowana wg wiatru z METAR: WEST, chyba że wiatr w plecy na 24 przekracza 5 kt; bez METAR – WEST (domyślna)
EDDB_RWYS = ("06L", "06R", "24L", "24R", "07L", "07R", "25L", "25R")
EDDB_WEST_HDG = 246
BERLIN_TAIL_KT = 5
_RWY_TOKEN = re.compile(r"\b(0[67]|2[45])([LR])\b")


def _side(rwy: str) -> str:
    return "EAST" if rwy[:2] in ("06", "07") else "WEST"


def wind_text(m) -> str:
    """Wiatr z METAR do dymku: 090/12, 250/15G25, VRB/03, calm."""
    if not m.wind_speed:
        return "calm"
    gust = f"G{m.wind_gust:02d}" if m.wind_gust else ""
    return f"{'VRB' if m.wind_variable or m.wind_dir is None else f'{m.wind_dir:03d}'}/{m.wind_speed:02d}{gust}"


def berlin_config(stations: list[dict], metar_raw: str | None = None) -> dict:
    """Konfiguracja BERLIN: {config: WEST|EAST, source: ATIS|WIND|DEFAULT, preferred (bez ATIS: strona czerwonym
    tekstem), letter, runways (pasy z ATIS tego kierunku), wind, tip}. stations: data feed (controllers + atis)."""
    atis = atis_state(stations, "EDDB", list(EDDB_RWYS))
    letter = (atis or {}).get("letter")
    if atis and (rwy := atis.get("arr") or atis.get("dep")):
        cfg = _side(rwy)
        text = " ".join(str(x) for x in atis.get("lines") or ()).upper()
        rws = []
        for r in [atis.get("arr"), atis.get("dep"), *("".join(m) for m in _RWY_TOKEN.findall(text))]:
            if r and _side(r) == cfg and r not in rws:
                rws.append(r)
        return {"config": cfg, "source": "ATIS", "preferred": False, "letter": letter, "runways": rws, "wind": None,
                "tip": f"ATIS{f' {letter}' if letter else ''}: {' '.join(rws)}"}
    head = f"ATIS{f' {letter}' if letter else ''} without runway" if atis else "No ATIS"
    m = None
    try:
        m = parse_metar(metar_raw) if metar_raw else None
    except Exception:  # noqa: BLE001 - nieczytelny METAR = jak brak METAR
        m = None
    if m is None or m.wind_speed is None:
        return {"config": "WEST", "source": "DEFAULT", "preferred": True, "letter": letter, "runways": [],
                "wind": None, "tip": f"{head}: default"}
    wind = wind_text(m)
    head_kt, _ = wind_components(m.wind_dir, m.wind_speed, EDDB_WEST_HDG) if not m.wind_variable else (None, None)
    cfg = "EAST" if head_kt is not None and -head_kt > BERLIN_TAIL_KT else "WEST"
    return {"config": cfg, "source": "WIND", "preferred": True, "letter": letter, "runways": [], "wind": wind,
            "tip": f"{head}: preferred by wind {wind}"}


# Czerwone tło (Marek): ograniczenie przepływu teraz albo ruch ponad 80 % dopuszczalnej zajętości. Traffic volumes:
# EP-BH = sektor B górny (HB), EP-WATMA(D) = TMA EPWA, złożone przez swoje wolumeny EPWW-BH,EPWW-CH (gdy każdy
# jednoznaczny), całe FIR-y (EP-ALLFIR, EP-NFIR, EP-SFIR) pomijamy
OCC_ALERT = 0.8
TV_FIR_WIDE = re.compile(r"^EP-(?:ALLFIR|NFIR|SFIR)")
TV_SECTOR = re.compile(r"^EP-([A-Z])([HML])$")
TV_TMA = re.compile(r"^EP-([A-Z]{2})TMAD?$")
VOL_SECTOR = re.compile(r"^EPWW-([A-Z])([HML])$")
VOL_TMA = re.compile(r"^EP([A-Z]{2})-TMA[A-Z]*$")


def window_on(start, end, hhmm: str) -> bool:
    """Okno HHMM–HHMM obejmuje teraz (także przez północ: 2200–0200), jak ograniczenia w OVERVIEW."""
    start, end = str(start or ""), str(end or "")
    return bool(start and end and (start <= hhmm <= end if start <= end else not end < hhmm < start))


def tv_targets(tv: dict, sector_ids, tma_by_icao: dict[str, list[str]]) -> tuple[list[str], list[str], bool]:
    """Sektory tablicy (HB) i TMA (klucz grupy TMA), których dotyczy traffic volume; trzeci element: TV złożony."""
    tid = str(tv.get("id") or "")
    if TV_FIR_WIDE.match(tid):
        return [], [], False
    if m := TV_SECTOR.match(tid):
        sid = m[2] + m[1]
        return ([sid] if sid in sector_ids else []), [], False
    if m := TV_TMA.match(tid):
        return [], list(tma_by_icao.get("EP" + m[1], ())), False
    secs, tmas = [], []
    vols = [v for v in tv.get("volumes") or () if v]
    for v in vols:
        if (m := VOL_SECTOR.match(v)) and m[2] + m[1] in sector_ids:
            secs.append(m[2] + m[1])
        elif (m := VOL_TMA.match(v)) and tma_by_icao.get("EP" + m[1]):
            tmas += tma_by_icao["EP" + m[1]]
        else:
            return [], [], True  # wolumen bez jednoznacznego miejsca na tablicy: cały TV pomijamy
    return sorted(set(secs)), sorted(set(tmas)), True


def _restriction_tip(r: dict) -> str:
    """Linia dymku aktywnego teraz ograniczenia: wartość i do kiedy (koniec okna HHMM jako HH:MM)."""
    kind, value, end = str(r.get("type") or "").upper(), r.get("value"), str(r.get("end") or "")
    until = f" until {end[:2]}:{end[2:4]}" if re.fullmatch(r"\d{4}", end) else ""
    if kind == "ENR-OCCUPANCY":
        return f"Flow restriction: max occupancy {value}{until}"
    if kind == "ENR-ENTRIES":
        return f"Flow restriction: max {value} entries per hour{until}"
    return f"Flow restriction: {value}{until}"


def flow_alerts(tvs, now, sector_ids, tma_groups_: list[dict]) -> dict:
    """{sectors: {HB: [alert]}, tma: {TMA Warszawa: [alert]}}; alert = {tv, restrictions (aktywne teraz), occupancy,
    capacity, busy (zajętość teraz > 80 % dopuszczalnej, tylko aktywny TV), tip: [linie dymku]}.
    tvs: viff.sectors(...)["sectors"]; now: datetime UTC."""
    hhmm = now.strftime("%H%M")
    tma_by_icao: dict[str, list[str]] = {}
    for g in tma_groups_:
        if g.get("icao") and g["tma"] not in tma_by_icao.get(g["icao"], []):
            tma_by_icao.setdefault(g["icao"], []).append(g["tma"])
    ids = set(sector_ids)
    out: dict[str, dict[str, list[dict]]] = {"sectors": {}, "tma": {}}
    for tv in tvs if isinstance(tvs, list) else ():
        if not isinstance(tv, dict) or not tv.get("id"):
            continue
        secs, tmas, combined = tv_targets(tv, ids, tma_by_icao)
        if not secs and not tmas:
            continue
        restr = [{k: r.get(k) for k in ("type", "value", "start", "end")} for r in tv.get("restrictions") or ()
                 if isinstance(r, dict) and window_on(r.get("start"), r.get("end"), hhmm)]
        occ = (tv.get("occupancy") or [None])[0]
        cap = tv.get("occupancy_cap")
        busy = bool(tv.get("active")) and isinstance(occ, int) and isinstance(cap, int) and cap > 0 \
            and occ > OCC_ALERT * cap
        if not restr and not busy:
            continue
        pre = f"{tv['id']}: " if combined else ""
        tip = [pre + _restriction_tip(r) for r in restr] + ([f"{pre}Occupancy {occ} of {cap}"] if busy else [])
        alert = {"tv": tv["id"], "restrictions": restr, "occupancy": occ, "capacity": cap, "busy": busy, "tip": tip}
        for sid in secs:
            out["sectors"].setdefault(sid, []).append(alert)
        for key in tmas:
            out["tma"].setdefault(key, []).append(alert)
    return out


def tma_plate_static(slices: list[dict], own: dict) -> dict:
    """Część stała plakietek APP: punkt plakietki dla każdego zestawu kilku części TMA, które może obsługiwać jedno
    stanowisko (anchors: {TMA: {"EPWA_APP+EPWA_N_APP": [lat, lon]}}, części po nazwie posortowane; jedna część ma punkt
    swojej etykiety `at`), dyrektorzy i TMA „domowe” stanowisk APP (home: TMA, w których stanowisko ma swoją część;
    przy kilku – ta z ICAO z jego znaku: EPWA_S_APP → TMA Warszawa, nie Radom i Łódź)."""
    parts_by, dirs = tma_parts(slices, own)
    anchors: dict[str, dict[str, list[float] | None]] = {}
    home: dict[str, list[str]] = {}
    for key, (icao, parts) in parts_by.items():
        names = sorted(parts)
        # do 4 części każdy zestaw (najwyżej 11), więcej – tylko całość
        sets = [c for n in range(2, len(names) + 1) for c in combinations(names, n)] if len(names) <= 4 \
            else [tuple(names)]
        anchors[key] = {}
        for c in sets:
            mine = [s for cs in c for s in parts[cs]]
            other = [s for cs in names if cs not in c for s in parts[cs]]
            anchors[key]["+".join(c)] = part_anchor(mine, other) if mine else None
        for cs in names:
            home.setdefault(cs, []).append(key)
    icao_of = {key: icao for key, (icao, _) in parts_by.items()}
    for cs, keys in home.items():
        same = [k for k in keys if icao_of.get(k) == cs[:4]]
        home[cs] = same or keys
    return {"anchors": anchors, "home": home, "directors": sorted(dirs)}


def app_plates(static: dict, online: dict, positions: dict | None = None) -> list[dict]:
    """Plakietki APP tylko dla zalogowanych (Marek): jedna na stanowisko APP (bez dyrektora i informacji), w środku
    części TMA, które teraz obsługuje w swojej TMA (sam EPWA_APP: cała TMA Warszawa, jedna plakietka; WA APP, WA N
    i WA S: trzy). covers: wszystkie części i TMA, które obsługuje (np. TMA Radom), do dymku. Wieża TMA proceduralnej
    (EPSC_TWR) ma plakietkę TWR, nie APP."""
    plates = static.get("plates") or {}
    dirs, radar = set(plates.get("directors") or ()), set(static.get("acc_positions") or ())
    groups = {g["id"]: g for g in static["tma"]}
    covered: dict[str, list[str]] = {}
    for g in static["tma"]:
        chains = [[cs for cs in ch if cs not in radar and cs not in dirs and not ACC_CS.match(cs) and not INFO.search(cs)]
                  for ch in g["chains"]]
        if own := owners_of_chains(chains, online):
            covered.setdefault(own[0], []).append(g["id"])
    out = []
    for cs, gids in covered.items():
        if facility(cs) not in APP_TYPES:
            continue
        home = plates.get("home", {}).get(cs) or [groups[gids[0]]["tma"]]
        for tma in home:
            parts = sorted(groups[g]["nominal"] for g in gids if groups[g]["tma"] == tma)
            if not parts:
                continue
            at = (plates.get("anchors", {}).get(tma) or {}).get("+".join(parts)) \
                or next(groups[g]["at"] for g in gids if groups[g]["tma"] == tma)
            icao = next((groups[g]["icao"] for g in gids if groups[g]["tma"] == tma), None)
            out.append({"owner": cs, "tma": tma, "icao": icao, "parts": parts, "at": at,
                        "frequency": freq_of(cs, online, positions), "covers": sorted(gids)})
    return sorted(out, key=lambda p: (p["tma"], p["owner"]))


def twr_plates(static: dict, online: dict, atis: list[dict], positions: dict | None = None) -> list[dict]:
    """Plakietki TWR tylko dla zalogowanych: w środku CTR, gdy wieża lotniska jest online (warstwy TWR i TWR/A),
    albo sam ATIS lotniska (tylko TWR/A). twr: zalogowane wieże tego lotniska, atis: zalogowane ATIS."""
    on_atis: dict[str, list[str]] = {}
    for a in atis:
        if a.get("online"):
            on_atis.setdefault(a["icao"], []).append(a["callsign"])
    out = []
    for g in static["twr"]:
        icao = g.get("icao")
        if not icao:
            continue
        order = [cs for ch in g["chains"] for cs in ch]
        twr = sorted((cs for cs in online if cs.split("_")[0] == icao and facility(cs) == "TWR" and is_on(cs, online)),
                     key=lambda cs: (order.index(cs) if cs in order else len(order), cs))
        at = on_atis.get(icao, [])
        if twr or at:
            out.append({"id": g["id"], "icao": icao, "at": g.get("centre") or g["at"], "twr": twr, "atis": at,
                        "frequency": freq_of(twr[0], online, positions) if twr else None,
                        "layers": ["twr", "twra"] if twr else ["twra"]})
    return out


def build_static(*, own: dict, epww_slices: list[dict], vacs_tiles: list[dict], positions: dict, coords: dict,
                 border_geom: dict, firs_geo: list[dict], nb_chains=(), nb_slices=(), layout: dict | None = None) -> dict:
    """Wszystko, co nie zależy od tego, kto jest online.

    epww_slices: wycinki z pliku EPWW ({fir, name, lo, hi, owners (znaki), geom}); vacs_tiles: kafelki sąsiadów
    z profilu VACS (vacs_epww.json, neighbours); positions: znak → {frequency, name, ...}; coords: ICAO → (lat, lon);
    border_geom: granica FIR EPWW (VATSpy); firs_geo: [{id, geometry}] do tła; nb_chains: listy OWNER (znaki)
    wycinków sąsiadów z plików .ese – do kolejności kafelków bez CTR w controlled_by (tile_chain); nb_slices: wycinki
    sąsiadów ({fir, name, lo, hi, owners, geom}: pliki .ese sąsiadów i Białoruś z pliku EPWW) – nb_areas; layout:
    data/seed/radio_layout.json (okienka FIR-ów, wskaźniki, BERLIN – layout_static)."""
    kinds: dict[str, list[dict]] = {"acc": [], "tma": [], "ctr": [], "fis": []}
    for s in epww_slices:
        k = sector_kind(s["fir"], s["name"])
        if s["fir"].upper() == "EPWW" and k in kinds:
            kinds[k].append(s)
    tiles = stack_tiles(vacs_tiles, first_chains(nb_chains), positions, chain_tails(nb_chains))
    acc_geo, seen = [], set()
    for s in kinds["acc"]:
        m = re.match(r"^EPWW([A-Z])", s["name"])
        if m and (own.get("sectors") or {}).get(m.group(1)):
            acc_geo.append({"letter": m.group(1), "name": s["name"], "lo": s["lo"], "hi": s["hi"],
                            "geometry": simplify(s["geom"], 0.002, 4)})

    def outlines(sl, **extra):
        out, mine = [], {}
        for s in sl:
            g = simplify(s["geom"])
            key = json.dumps(g["coordinates"])
            if key not in seen:
                seen.add(key)
                mine[key] = {"name": s["name"], "geometry": g, **{k: f(s) for k, f in extra.items()}}
                out.append(mine[key])
            elif key in mine:
                # ten sam kształt drugi raz (inna wysokość): brakujące dodatki z kolejnego wycinka (np. klucz TMA)
                for k, f in extra.items():
                    if mine[key][k] is None:
                        mine[key][k] = f(s)
        return out

    fis_sl = [s for s in kinds["fis"] if FIS_NAME.match(s["name"])]
    # kształt TMA → klucz TMA (jak tma[].tma i flow.tma): czerwone tło TMA z alarmem przepływu na podglądzie LOW;
    # wspólne części kilku TMA i CTA bez klucza (tylko obrys)
    tma_key = {s["name"]: key for key, (_, parts) in tma_parts(kinds["tma"], own)[0].items()
               for sl in parts.values() for s in sl}
    # sąsiedzi: ten sam kształt na tej samej wysokości (kopie z dwóch plików) raz
    nb, nb_seen = [], set()
    for a in nb_areas(list(nb_slices), border_geom):
        g = simplify(a["geom"], 0.008, 2)  # tło podglądu: ok. 1 km wystarczy (0,01° to niecały piksel)
        key = (a["kind"], a["lo"], a["hi"], json.dumps(g["coordinates"]))
        if g["coordinates"] and key not in nb_seen:
            nb_seen.add(key)
            nb.append({**{k: v for k, v in a.items() if k != "geom"}, "geometry": g})
    geo = {"border": simplify(border_geom, 0.002), "firs": [{"id": f["id"], "geometry": simplify(f["geometry"], 0.02, 2)}
                                                           for f in firs_geo],
           "acc": acc_geo, "tma": outlines(kinds["tma"], tma=lambda s: tma_key.get(s["name"])), "ctr": outlines(kinds["ctr"]),
           "fis": outlines(fis_sl, owner=lambda s: s["owners"][0] if s["owners"] else None),
           "nb": [{k: a[k] for k in ("id", "fir", "name", "kind", "lo", "hi", "geometry")} for a in nb]}
    atis = sorted(cs for cs in positions if cs.startswith("EP") and facility(cs) == "ATIS")
    acc_pos = own.get("acc_positions") or {}
    return {"layers": own.get("layers") or {}, "acc_positions": sorted(acc_pos),
            "acc_short": {cs: (v or {}).get("short") or cs for cs, v in acc_pos.items()},
            "sectors": acc_sectors(own), "tma": tma_groups(kinds["tma"], own),
            "twr": ctr_groups(kinds["ctr"], own, coords, positions), "fis": fis_groups(fis_sl, own),
            "atis": atis, "nb": [{"id": a["id"], "chain": a["chain"]} for a in nb], "geo": geo,
            "layout": layout_static(layout or {}, tiles), "plates": tma_plate_static(kinds["tma"], own)}


# --- część zmienna: kto jest online
def _referenced(static: dict) -> set[str]:
    refs: set[str] = set(static["atis"])
    for s in static["sectors"]:
        refs.update(s["chain"])
    for g in static["tma"] + static["twr"] + static["fis"]:
        refs.add(g["nominal"])
        refs.update(cs for ch in g["chains"] for cs in ch)
        if g.get("atis"):
            refs.add(g["atis"])
    for f in (static.get("layout") or {}).get("firs") or ():
        refs.update(f["area"])
        for b in f["boxes"]:
            refs.update(b["chain"])
            if b["callsign"]:
                refs.add(b["callsign"])
    return refs


def board(static: dict, online: dict, positions: dict, feed_atis: list[dict] = (), net_ok: bool = True,
          berlin: dict | None = None, flow: dict | None = None) -> dict:
    """Stan tablicy dla zestawu zalogowanych (online: znak stanowiska → kontroler, jak /api/radio/online).
    Od 0.13.0 także układ wg szkicu: grid, firs (okienka FIR-ów sąsiednich po łączeniu), indicators, plates (APP i TWR
    tylko dla zalogowanych), berlin (berlin_config z feedu i METAR, liczy endpoint) z miejscem w siatce i flow
    (flow_alerts z vIFF, liczy endpoint; None = brak danych). Stosów sąsiadów już nie ma (okienka firs)."""
    sectors = [{**s, "owner": first_online(s["chain"], online)} for s in static["sectors"]]
    # APP, TWR, FIS: właściciel spośród stanowisk tej przestrzeni (APP, TWR, informacja); sektor ACC, który przejmuje
    # ją top-down, osobno (topdown) – ACC widać już na podglądach LOW/MID/HIGH
    radar = set(static.get("acc_positions") or ())

    def local(g: dict) -> dict:
        own_ = owners_of_chains([[cs for cs in ch if cs not in radar] for ch in g["chains"]], online)
        top = None if own_ else first_online(g["chains"][0] if g["chains"] else [], online)
        return {**g, "owners": own_, "topdown": top}

    tma = [local(g) for g in static["tma"]]
    twr = [local(g) for g in static["twr"]]
    fis = [local(g) for g in static["fis"]]
    # ATIS: polskie stanowiska ATIS z pliku .ese oraz zalogowane EP**_ATIS spoza niego (np. EPWA_D_ATIS)
    atis = [{"callsign": cs, "icao": cs[:4], "online": cs in online} for cs in static["atis"]]
    known = {online[a["callsign"]]["callsign"] for a in atis if a["online"]}
    extra = {}
    for c in feed_atis:
        cs = str(c.get("callsign") or "").upper()
        if cs.startswith("EP") and cs.endswith("_ATIS") and cs not in known and cs not in static["atis"]:
            extra[cs] = {"callsign": cs, "icao": cs[:4], "online": True, "extra": True}
    atis = sorted(atis + list(extra.values()), key=lambda a: (a["icao"], a["callsign"]))
    refs = _referenced(static) | set(extra)
    pos = {}
    for cs in sorted(refs):
        p = positions.get(cs) or {}
        pos[cs] = {"frequency": p.get("frequency") or "", "name": p.get("radio") or p.get("name")}
    for cs, a in extra.items():
        info = next((c for c in feed_atis if str(c.get("callsign") or "").upper() == cs), {})
        pos[cs]["frequency"] = info.get("frequency") or ""
        online = {**online, cs: {"callsign": cs, "frequency": info.get("frequency"), "name": info.get("name"),
                                 "cid": info.get("cid"), "logon_time": info.get("logon_time"),
                                 "atis_code": info.get("atis_code"), "text_atis": info.get("text_atis")}}
    # wycinki sąsiadów na podglądach: obsadzone (id → pierwsze stanowisko online z listy OWNER); reszta nieobsadzona
    nb = {a["id"]: o for a in static.get("nb") or () if (o := first_online(a["chain"], online))}
    lay = static.get("layout") or {}
    grid = {"cols": (lay.get("grid") or {}).get("cols"), "rows": (lay.get("grid") or {}).get("rows"),
            "buttons": lay.get("buttons") or {}, "maps": lay.get("maps") or {}, "tracks": lay.get("tracks") or [],
            **{k: lay[k] for k in ("status", "legend") if lay.get(k)}}
    flow = flow or {}
    return {"layers": static["layers"], "sectors": sectors, "tma": tma, "twr": twr,
            "fis": fis, "atis": atis, "nb": nb, "pos": pos,
            "online": {cs: v for cs, v in online.items() if cs in refs or cs in extra},
            "grid": grid, "firs": fir_blocks(lay, online, positions, net_ok),
            "indicators": indicators(lay, online, sectors, static.get("acc_short") or {}),
            "plates": {"app": app_plates(static, online, positions), "twr": twr_plates(static, online, atis, positions)},
            "berlin": {**(lay.get("berlin") or {}), **(berlin or berlin_config([]))},
            "flow": {"ok": bool(flow.get("ok")), "sectors": flow.get("sectors") or {}, "tma": flow.get("tma") or {}}}
