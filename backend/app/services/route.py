"""Rozwijanie trasy z planu lotu (np. "EPWA SOXER N871 BAMSO DCT EPKK") do listy punktów
z uwzględnieniem dróg lotniczych zaimportowanych z pliku sektorowego."""

import math
import re
from collections import defaultdict, deque

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


class RouteResolver:
    def __init__(self, db: Session):
        self.db = db

    def _point(self, ident: str, near: tuple[float, float] | None):
        if c := _coord_token(ident):
            return {"ident": ident, "kind": "COORD", "lat": c[0], "lon": c[1]}
        cands = []
        if ad := self.db.get(Aerodrome, ident):
            cands.append({"ident": ident, "kind": "AD", "lat": ad.lat, "lon": ad.lon})
        for p in self.db.scalars(select(NavPoint).where(NavPoint.ident == ident)):
            cands.append({"ident": ident, "kind": p.kind, "lat": p.lat, "lon": p.lon})
        if not cands:
            return None
        if near and len(cands) > 1:
            cands.sort(key=lambda c: dist_nm(near, (c["lat"], c["lon"])))
        return cands[0]

    def _airway_path(self, airway: str, start: str, end: str):
        segs = self.db.scalars(select(AirwaySegment).where(AirwaySegment.airway == airway)).all()
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
        tokens = [t.split("/")[0] for t in route.upper().split() if t]
        tokens = [t for t in tokens if t and t != "DCT" and not SPEED_LEVEL.match(t)]
        points, warnings = [], []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            near = (points[-1]["lat"], points[-1]["lon"]) if points else None
            is_airway = (
                points and i + 1 < len(tokens)
                and self.db.scalar(select(AirwaySegment.id).where(AirwaySegment.airway == tok).limit(1)) is not None
            )
            if is_airway:
                path = self._airway_path(tok, points[-1]["ident"], tokens[i + 1])
                if path:
                    points.extend(path[1:])
                    i += 2
                    continue
                warnings.append(f"Nie udało się rozwinąć drogi {tok} między {points[-1]['ident']} a {tokens[i + 1]}")
                i += 1
                continue
            p = self._point(tok, near)
            if p:
                points.append(p)
            else:
                warnings.append(f"Nieznany punkt lub procedura: {tok}")
            i += 1
        total = sum(dist_nm((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(points, points[1:]))
        return {"points": points, "distance_nm": round(total, 1), "warnings": warnings}
