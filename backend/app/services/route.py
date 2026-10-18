"""Rozwijanie trasy z planu lotu (np. "EPWA SOXER N871 BAMSO DCT EPKK") do listy punktów
z uwzględnieniem dróg lotniczych zaimportowanych z pliku sektorowego."""

import math
import re
from collections import defaultdict, deque
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Aerodrome, AirwaySegment, NavPoint

SPEED_LEVEL = re.compile(r"^(?:[NKM]\d{3,4})(?:[FAMS]\d{3,4}|VFR)$")
COORD = re.compile(r"^(\d{2})(\d{2})?([NS])(\d{3})(\d{2})?([EW])$")


def dist_nm(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(h))


def _coord_token(tok: str):
    m = COORD.match(tok)
    if not m:
        return None
    lat = int(m[1]) + int(m[2] or 0) / 60
    lon = int(m[4]) + int(m[5] or 0) / 60
    return (-lat if m[3] == "S" else lat, -lon if m[6] == "W" else lon)


def _airway_graph(segs: list) -> tuple[dict, dict] | None:
    """Odcinki drogi lotniczej → (sąsiedzi każdego punktu, współrzędne punktów); bez odcinków None."""
    if not segs:
        return None
    graph = defaultdict(list)
    pos = {}
    for s in segs:
        if s.from_ident and s.to_ident:
            graph[s.from_ident].append(s.to_ident)
            graph[s.to_ident].append(s.from_ident)
            pos[s.from_ident] = (s.from_lat, s.from_lon)
            pos[s.to_ident] = (s.to_lat, s.to_lon)
    return graph, pos


class RouteResolver:
    def __init__(self, db: Session):
        self.db = db
        # pamięć na czas życia obiektu (jedno zapytanie API): MAP rozpisuje naraz wiele tras z tymi samymi punktami
        # i drogami lotniczymi (services/eptraffic.py)
        self._cands: dict[str, list[dict]] = {}
        self._graphs: dict[str, tuple[dict, dict] | None] = {}

    @staticmethod
    def _tokens(route: str) -> list[str]:
        tokens = [t.split("/")[0] for t in route.upper().split() if t]
        return [t for t in tokens if t and t != "DCT" and not SPEED_LEVEL.match(t)]

    def prefetch(self, routes: Iterable[str], chunk: int = 500) -> None:
        """Punkty i drogi lotnicze wielu tras naraz: kilka zapytań do bazy zamiast kilku na każdy punkt każdej trasy
        (MAP rozpisuje po starcie serwera setki tras). Wynik jak przy pojedynczych zapytaniach w _point i _graph."""
        toks = {t for r in routes for t in self._tokens(r)}
        idents = sorted(t for t in toks if t not in self._cands and not _coord_token(t))
        for i in range(0, len(idents), chunk):
            part = idents[i:i + chunk]
            cands: dict[str, list[dict]] = {t: [] for t in part}
            for ad in self.db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(part))):
                cands[ad.icao].append({"ident": ad.icao, "kind": "AD", "lat": ad.lat, "lon": ad.lon})
            for p in self.db.scalars(select(NavPoint).where(NavPoint.ident.in_(part)).order_by(NavPoint.id)):
                cands[p.ident].append({"ident": p.ident, "kind": p.kind, "lat": p.lat, "lon": p.lon})
            self._cands.update(cands)
        ways = sorted(t for t in toks if t not in self._graphs)  # każde słowo trasy może być drogą (resolve pyta o nie)
        for i in range(0, len(ways), chunk):
            part = ways[i:i + chunk]
            segs = defaultdict(list)
            for s in self.db.scalars(select(AirwaySegment).where(AirwaySegment.airway.in_(part))
                                     .order_by(AirwaySegment.id)):
                segs[s.airway].append(s)
            self._graphs.update({t: _airway_graph(segs.get(t, [])) for t in part})

    def _point(self, ident: str, near: tuple[float, float] | None):
        if c := _coord_token(ident):
            return {"ident": ident, "kind": "COORD", "lat": c[0], "lon": c[1]}
        if (cands := self._cands.get(ident)) is None:
            cands = []
            if ad := self.db.get(Aerodrome, ident):
                cands.append({"ident": ident, "kind": "AD", "lat": ad.lat, "lon": ad.lon})
            for p in self.db.scalars(select(NavPoint).where(NavPoint.ident == ident).order_by(NavPoint.id)):
                cands.append({"ident": ident, "kind": p.kind, "lat": p.lat, "lon": p.lon})
            self._cands[ident] = cands
        if not cands:
            return None
        if near and len(cands) > 1:
            return dict(min(cands, key=lambda c: dist_nm(near, (c["lat"], c["lon"]))))
        return dict(cands[0])

    def _graph(self, airway: str) -> tuple[dict, dict] | None:
        """Droga lotnicza jako graf sąsiedztwa punktów i ich współrzędne (None = nie ma takiej drogi)."""
        if airway not in self._graphs:
            self._graphs[airway] = _airway_graph(self.db.scalars(
                select(AirwaySegment).where(AirwaySegment.airway == airway).order_by(AirwaySegment.id)).all())
        return self._graphs[airway]

    def _airway_path(self, airway: str, start: str, end: str):
        if not (g := self._graph(airway)):
            return None
        graph, pos = g
        if start not in graph or end not in graph:
            return None
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == end:
                break
            for nxt in graph[cur]:
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        if end not in prev:
            return None
        path = []
        cur = end
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return [{"ident": i, "kind": "FIX", "lat": pos[i][0], "lon": pos[i][1], "via": airway} for i in path]

    def resolve(self, route: str) -> dict:
        tokens = self._tokens(route)
        points, warnings = [], []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            near = (points[-1]["lat"], points[-1]["lon"]) if points else None
            is_airway = points and i + 1 < len(tokens) and self._graph(tok) is not None
            if is_airway:
                path = self._airway_path(tok, points[-1]["ident"], tokens[i + 1])
                if path:
                    points.extend(path[1:])
                    i += 2
                    continue
                warnings.append(f"Could not expand airway {tok} between {points[-1]['ident']} and {tokens[i + 1]}")
                i += 1
                continue
            p = self._point(tok, near)
            if p:
                points.append(p)
            else:
                warnings.append(f"Unknown point or procedure: {tok}")
            i += 1
        total = sum(dist_nm((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(points, points[1:]))
        return {"points": points, "distance_nm": round(total, 1), "warnings": warnings}
