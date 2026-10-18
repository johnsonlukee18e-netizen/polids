"""Ruch EP na MAP: samoloty, które odlatują z lotniska EP**, przylatują na EP** albo przelatują przez FIR EPWW.

Tranzyt (trn): samolot jest teraz w FIR EPWW albo pozostała część trasy z planu lotu (od bieżącej pozycji do lotniska
docelowego) wchodzi w FIR EPWW. Samolot, który już z FIR-u wyleciał i do niego nie wróci, albo którego trasa
FIR-u nie dotyka, nie ma relacji (None). Bez planu lotu liczy się tylko pozycja w FIR EPWW.

Granica FIR EPWW: obrys wszystkich wycinków EPWW z data/seed/sectors.geojson, czyli tych samych sektorów z pliku .ese,
które MAP rysuje jako ACC EPWW, TMA, CTR, FIS (/api/nav/slices). Obejmuje też przestrzeń nad Bałtykiem delegowaną
do EPWW (EPWW-MIDSEA, część sektora B), której nie ma w obrysie FIR-u EPWW z VATSpy (MAP go zresztą nie rysuje:
drawFirs pomija EPWW).

Trasa (lotnisko odlotu, pole 15, lotnisko docelowe) rozpisana przez RouteResolver jak w /api/vatsim/pilots/{znak}/route;
odcinki to łuki koła wielkiego zagęszczone co ok. 20 NM, a każdy krótki odcinek sprawdzamy na rastrze FIR-u (komórka
0,02°, ok. 1 NM), więc liczy się też przecięcie samego rogu FIR-u. Gdy z trasy nie zostaje żaden punkt (brak pola 15,
samo DCT, same nieznane punkty), liczy się łuk od bieżącej pozycji do lotniska docelowego. Punkty daleko poza elipsą
wokół lotnisk odlotu i celu (punkt albo droga o tej samej nazwie na innym kontynencie) pomijamy. Rozpisana trasa zostaje
w pamięci (klucz: znak, lotniska, trasa), więc przy odświeżaniu co 30 s liczy się tylko, czy reszta trasy od bieżącej
pozycji wchodzi w FIR. Gdy trasy nie da się rozpisać (błąd bazy nawigacyjnej, np. w trakcie importu), lot ma relację
tylko z lotnisk i pozycji, a trasę rozpisujemy przy następnym odświeżeniu.

Punkt wyjścia z FIR-u (etykieta tranzytu i odlotu z EP** za granicę na MAP, trzecia linijka jak w PEGASUS_21;
przylot i lot krajowy pokazują lotnisko docelowe): nazwany punkt trasy najbliżej miejsca, w którym trasa ostatni raz
opuszcza FIR EPWW (do EXIT_NM od niego); bez takiego punktu (długi odcinek DCT przez granicę, trasa nierozpisana,
łuk do lotniska docelowego) MAP pokazuje lotnisko docelowe."""

import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable, Iterable

from ..config import settings

EP_AD = re.compile(r"^EP[A-Z]{2}$")
STEP_NM = 20  # zagęszczenie łuków koła wielkiego
CELL = 0.02  # komórka rastra FIR-u w stopniach
KEEP_S = 900  # trasa lotu, którego nie ma w feedzie od tylu sekund, wypada z pamięci
# punkt trasy dalej od lotnisk niż elipsa: odległość odlot–punkt–cel ≤ 1,5 × odlot–cel + 250 NM, to pomyłka;
# co najmniej 600 NM (lot po kręgu z powrotem na lotnisko startu, krótki lot z objazdem: do ok. 300 NM od lotnisk)
CORRIDOR, CORRIDOR_NM, CORRIDOR_MIN = 1.5, 250, 600
EXIT_NM = 30  # punkt wyjścia z FIR-u: nazwany punkt trasy najdalej tyle od miejsca, w którym trasa opuszcza FIR
NAMED = re.compile(r"^[A-Z]{2,5}$")  # punkt nawigacyjny z nazwą (bez współrzędnych 5230N01500E i kodów lotnisk)
log = logging.getLogger("polids.eptraffic")

Point = tuple[float, float]  # (lat, lon)


class Outline:
    """Obszar (suma wielokątów lon/lat) jako raster: komórka należy do obszaru, gdy jej środek leży w którymś
    z wielokątów. Na granicy błąd do pół komórki (0,01° ≈ 0,6 NM), w środku żadnego."""

    def __init__(self, rings: Iterable[list], cell: float = CELL):
        rings = [[(float(p[0]), float(p[1])) for p in r] for r in rings]
        rings = [r for r in rings if len(r) >= 3]
        self.cell = cell
        if not rings:
            self.x0 = self.y0 = self.x1 = self.y1 = 0.0
            self.nx = self.ny = 0
            self.bits = bytearray()
            return
        self.x0, self.y0 = min(x for r in rings for x, _ in r), min(y for r in rings for _, y in r)
        self.x1, self.y1 = max(x for r in rings for x, _ in r), max(y for r in rings for _, y in r)
        self.nx = int((self.x1 - self.x0) / cell) + 1
        self.ny = int((self.y1 - self.y0) / cell) + 1
        self.bits = bytearray(self.nx * self.ny)
        for r in rings:
            self._fill(r)

    def _fill(self, ring: list[tuple[float, float]]) -> None:
        """Linia po linii (środki komórek): odcinki między kolejnymi przecięciami z krawędziami są w wielokącie."""
        c, x0, y0, nx = self.cell, self.x0, self.y0, self.nx
        edges = list(zip(ring, ring[1:] + ring[:1]))
        ys = [y for _, y in ring]
        for j in range(max(0, int((min(ys) - y0) / c - 0.5)), min(self.ny, int((max(ys) - y0) / c + 0.5) + 1)):
            y = y0 + (j + 0.5) * c
            xs = sorted(xa + (y - ya) * (xb - xa) / (yb - ya) for (xa, ya), (xb, yb) in edges if (ya > y) != (yb > y))
            row = j * nx
            for a, b in zip(xs[::2], xs[1::2]):
                lo, hi = max(0, math.ceil((a - x0) / c - 0.5)), min(nx - 1, math.floor((b - x0) / c - 0.5))
                if lo <= hi:
                    self.bits[row + lo:row + hi + 1] = b"\x01" * (hi - lo + 1)

    def contains(self, lat: float, lon: float) -> bool:
        i, j = int((lon - self.x0) / self.cell), int((lat - self.y0) / self.cell)
        return 0 <= i < self.nx and 0 <= j < self.ny and lon >= self.x0 and lat >= self.y0 and bool(self.bits[j * self.nx + i])

    def near(self, lat: float, lon: float, margin: float) -> bool:
        """Punkt w prostokącie obszaru powiększonym o `margin` stopni."""
        return self.x0 - margin <= lon <= self.x1 + margin and self.y0 - margin <= lat <= self.y1 + margin

    def touches(self, a: Point, b: Point) -> bool:
        """Krótki odcinek a-b (do ok. 20 NM, prosty w lon/lat) ma punkt w obszarze: próbki co ok. 0,7 komórki.
        Odcinek przez południk 180° (skok długości o ponad 180°) jest po drugiej stronie Ziemi, obszaru nie dotyka."""
        (la1, lo1), (la2, lo2) = a, b
        if abs(lo2 - lo1) > 180:
            return False
        if max(lo1, lo2) < self.x0 or min(lo1, lo2) > self.x1 or max(la1, la2) < self.y0 or min(la1, la2) > self.y1:
            return False
        n = int(max(abs(lo2 - lo1), abs(la2 - la1)) / (self.cell * 0.7)) + 1
        return any(self.contains(la1 + (la2 - la1) * k / n, lo1 + (lo2 - lo1) * k / n) for k in range(n + 1))


def _xyz(p: Point) -> tuple[float, float, float]:
    la, lo = math.radians(p[0]), math.radians(p[1])
    return math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)


def dist_nm(a: Point, b: Point) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(h)))


def densify(points: list[Point], step_nm: float = STEP_NM) -> list[Point]:
    """Łamana z punktami na łukach koła wielkiego co najwyżej co `step_nm`."""
    out = list(points[:1])
    for a, b in zip(points, points[1:]):
        n = int(dist_nm(a, b) / step_nm)
        if n:
            (xa, ya, za), (xb, yb, zb) = _xyz(a), _xyz(b)
            d = math.acos(max(-1.0, min(1.0, xa * xb + ya * yb + za * zb)))
            if d > 1e-9:
                for k in range(1, n + 1):
                    f = k / (n + 1)
                    s, t = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
                    x, y, z = s * xa + t * xb, s * ya + t * yb, s * za + t * zb
                    out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
        out.append(b)
    return out


def path_hits(pts: list[Point], outline: Outline) -> list[bool]:
    """hits[i]: punkt i w obszarze albo odcinek i → i+1 go dotyka."""
    out = [outline.contains(*p) for p in pts]
    for i in range(len(pts) - 1):
        if not out[i] and outline.touches(pts[i], pts[i + 1]):
            out[i] = True
    return out


def exit_point(pts: list[Point], last: int, named: list[tuple[str, Point]], outline: Outline) -> str | None:
    """Nazwany punkt trasy najbliżej miejsca, w którym trasa (punkty co ok. 20 NM) ostatni raz opuszcza obszar:
    odcinek pts[last] → pts[last + 1] (pts[last] to ostatni punkt, od którego trasa jeszcze dotyka obszaru) próbkowany
    co ok. 0,5 NM. Trasa kończy się w obszarze albo go nie dotyka: None."""
    if last < 0 or last + 1 >= len(pts) or not named:
        return None
    (la1, lo1), (la2, lo2) = pts[last], pts[last + 1]
    n = max(1, int(dist_nm(pts[last], pts[last + 1]) * 2))
    k = max((i for i in range(n + 1) if outline.contains(la1 + (la2 - la1) * i / n, lo1 + (lo2 - lo1) * i / n)), default=0)
    cross = (la1 + (la2 - la1) * k / n, lo1 + (lo2 - lo1) * k / n)
    d, ident = min((dist_nm(cross, p), ident) for ident, p in named)
    return ident if d <= EXIT_NM else None


class Plan:
    """Trasa z planu lotu rozpisana i sprawdzona raz: punkty co ok. 20 NM i ostatni punkt, od którego trasa jeszcze
    dotyka FIR-u. Bez punktów trasy (`pts` None) liczy się łuk od pozycji do lotniska docelowego (`dest`).
    exit: nazwany punkt trasy, przez który trasa ostatni raz opuszcza FIR (exit_point), albo None."""

    __slots__ = ("pts", "last", "dest", "seen", "exit")

    def __init__(self, pts: list[Point] | None, dest: Point | None, outline: Outline,
                 named: list[tuple[str, Point]] | None = None):
        self.pts, self.dest, self.seen = pts, dest, time.monotonic()
        hits = path_hits(pts, outline) if pts else []
        self.last = max((i for i, h in enumerate(hits) if h), default=-1)
        self.exit = exit_point(pts, self.last, named or [], outline) if pts else None

    @classmethod
    def build(cls, dep: str, route: str, arr: str, resolver, outline: Outline) -> "Plan":
        pts = resolver.resolve(" ".join(x for x in (dep, route, arr) if x))["points"] if dep or route or arr else []
        dest = next(((p["lat"], p["lon"]) for p in reversed(pts) if arr and p["ident"] == arr), None)
        orig = next(((p["lat"], p["lon"]) for p in pts if dep and p["ident"] == dep), None)
        if orig and dest:
            # punkt daleko poza elipsą wokół odcinka odlot–cel to pomyłka (punkt albo droga o tej samej nazwie na innym
            # kontynencie, np. A502 w Ameryce Środkowej), a nie objazd: pomijamy go
            limit = max(CORRIDOR * dist_nm(orig, dest) + CORRIDOR_NM, CORRIDOR_MIN)
            pts = [p for p in pts if dist_nm(orig, (p["lat"], p["lon"])) + dist_nm((p["lat"], p["lon"]), dest) <= limit]
        if not any(p["ident"] not in (dep, arr) for p in pts):
            return cls(None, dest, outline)  # nic poza lotniskami: łuk od bieżącej pozycji do lotniska docelowego
        named = [(p["ident"], (p["lat"], p["lon"])) for p in pts
                 if p.get("kind") != "AD" and p["ident"] not in (dep, arr) and NAMED.match(p["ident"])]
        return cls(densify([(p["lat"], p["lon"]) for p in pts]), dest, outline, named)

    def enters(self, pos: Point, outline: Outline) -> bool:
        """Czy reszta trasy od pozycji `pos` (poza obszarem) wchodzi w obszar."""
        if self.pts is None:
            return self.dest is not None and any(path_hits(densify([pos, self.dest]), outline))
        if self.last < 0 and not outline.near(*pos, 1.0):
            return False  # trasa FIR-u nie dotyka, a samolot jest daleko od FIR-u (nie zboczył z niej w jego stronę)
        # najbliższy punkt trasy (rzut równoodległościowy); reszta trasy zaczyna się od następnego punktu za rzutem
        # pozycji na odcinek przy nim: samolot tuż za granicą (wyleciał) nie jest już tranzytem
        k = math.cos(math.radians(pos[0]))
        d = [((la - pos[0]) ** 2 + ((lo - pos[1]) * k) ** 2) for la, lo in self.pts]
        m = min(range(len(d)), key=d.__getitem__)
        j = m
        if m + 1 < len(self.pts):
            (la0, lo0), (la1, lo1) = self.pts[m], self.pts[m + 1]
            if (pos[0] - la0) * (la1 - la0) + (pos[1] - lo0) * (lo1 - lo0) * k * k > 0:
                j = m + 1
        if j <= self.last:
            return True
        return any(path_hits(densify([pos, self.pts[j]]), outline))


def _first(exc: Exception) -> str:
    """Pierwsza linijka błędu (SQLAlchemy dokłada treść zapytania i parametry)."""
    return str(exc).split("\n", 1)[0]


class EpTraffic:
    """Relacja samolotów z ruchem EP; rozpisane trasy w pamięci między odświeżeniami MAP."""

    def __init__(self, outline: Callable[[], Outline]):
        self._outline = outline
        self._plans: dict[str, tuple[tuple, Plan]] = {}
        self._lock = threading.Lock()
        self._pruned = time.monotonic()

    def relations(self, pilots: list[dict], resolver) -> list[str | None]:
        """Dla każdego pilota (kształt pilot_info): "dep", "arr", "trn" albo None (bez relacji z Polską).

        resolver: RouteResolver (resolve(tekst) → {"points": [...]}, prefetch(teksty) = punkty i drogi wszystkich
        nowych tras naraz)."""
        return [rel for rel, _ in self.classify(pilots, resolver)]

    def classify(self, pilots: list[dict], resolver) -> list[tuple[str | None, str | None]]:
        """Jak relations, z punktem wyjścia z FIR-u tranzytu i odlotu z EP** za granicę: [(relacja, punkt wyjścia
        albo None)]. Tranzyt w FIR-ze z planem lotu i odlot za granicę też mają rozpisaną trasę (tylko po punkt
        wyjścia; relacja zostaje "trn" albo "dep"). Lot krajowy i przylot: bez punktu wyjścia."""
        outline = self._outline()
        with self._lock:
            out: list[tuple[str | None, str | None]] = []
            todo = []  # (indeks, znak, klucz planu, pozycja, relacja bez trasy): loty z trasą do rozpisania
            for p in pilots:
                rel, key = self._quick(p, outline)
                if key:
                    todo.append((len(out), p.get("callsign") or "", key, (p["lat"], p["lon"]), rel))
                out.append((rel, None))
            new = {key for _, cs, key, _, _ in todo if (self._plans.get(cs) or (None,))[0] != key}
            broken = False  # baza nawigacyjna zawiodła: nowych tras w tym odświeżeniu już nie rozpisujemy
            if new and hasattr(resolver, "prefetch"):
                try:
                    resolver.prefetch(" ".join(x for x in key if x) for key in new)
                except Exception as exc:  # np. "database is locked" w trakcie importu danych
                    broken = True
                    log.warning("MAP, ruch EP: trasy nierozpisane (%s), relacja tylko z lotnisk i pozycji", _first(exc))
            now = time.monotonic()
            for i, cs, key, pos, rel in todo:
                hit = self._plans.get(cs)
                if not hit or hit[0] != key:
                    if broken:
                        continue  # relacja z _quick (None: poza FIR-em, lotniska spoza EP); trasa przy następnym razie
                    try:
                        plan = Plan.build(*key, resolver, outline)
                    except Exception as exc:
                        broken = True
                        log.warning("MAP, ruch EP: trasa %s nierozpisana (%s)", cs, _first(exc))
                        continue
                    hit = self._plans[cs] = (key, plan)
                hit[1].seen = now
                if rel is None:
                    rel = "trn" if hit[1].enters(pos, outline) else None
                out[i] = (rel, hit[1].exit if rel in ("trn", "dep") else None)
            if now - self._pruned > 60:
                self._pruned = now
                self._plans = {cs: v for cs, v in self._plans.items() if now - v[1].seen < KEEP_S}
            return out

    @staticmethod
    def _quick(p: dict, outline: Outline) -> tuple[str | None, tuple | None]:
        """Relacja bez trasy albo klucz planu (lotnisko odlotu, trasa, lotnisko docelowe), gdy decyduje trasa
        (w FIR-ze: relacja "trn" i klucz planu do punktu wyjścia z FIR-u; odlot z EP** za granicę: relacja "dep"
        i klucz planu do punktu wyjścia)."""
        dep, arr = (p.get("departure") or "").upper(), (p.get("arrival") or "").upper()
        if EP_AD.match(dep):
            # odlot za granicę opuszcza FIR EPWW jak tranzyt: trasa tylko po punkt wyjścia (etykieta na MAP);
            # lot krajowy (EP → EP) i bez lotniska docelowego: bez trasy
            return "dep", ((dep, (p.get("route") or "").upper(), arr) if arr and not EP_AD.match(arr) else None)
        if EP_AD.match(arr):
            return "arr", None
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            return None, None
        if outline.contains(lat, lon):
            # w FIR-ze to zawsze tranzyt; trasa z planu lotu tylko po punkt wyjścia z FIR-u (etykieta na MAP)
            return "trn", ((dep, (p.get("route") or "").upper(), arr) if dep or arr else None)
        if not dep and not arr:
            return None, None  # bez planu lotu liczy się tylko pozycja w FIR EPWW
        return None, (dep, (p.get("route") or "").upper(), arr)

    def cached(self) -> int:
        return len(self._plans)


def outline_from_geojson(fc: dict, fir: str = "EPWW") -> Outline:
    """Obrys FIR-u z wycinków sectors.geojson (source i fir = `fir`); powtórzone wycinki (te same granice na innych
    poziomach) liczą się raz."""
    rings = {tuple(map(tuple, f["geometry"]["coordinates"][0])) for f in fc.get("features", [])
             if f.get("properties", {}).get("fir") == fir and f.get("properties", {}).get("source", fir) == fir
             and (f.get("geometry") or {}).get("type") == "Polygon" and f["geometry"].get("coordinates")}
    return Outline(sorted(rings))


_outline: tuple[float, Outline] | None = None


def epww_outline() -> Outline:
    """Obrys FIR EPWW z data/seed/sectors.geojson, liczony od nowa po zmianie pliku (jak tabele sektorów)."""
    global _outline
    path = settings.seed_dir / "sectors.geojson"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    if not _outline or _outline[0] != mtime:
        try:
            fc = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            fc = {}
        _outline = (mtime, outline_from_geojson(fc))
    return _outline[1]


ep_traffic = EpTraffic(epww_outline)
