"""MAP: ruch EP (odloty z EP**, przyloty na EP**, tranzyt przez FIR EPWW) liczony na serwerze (services/eptraffic.py)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from backend.app.services.eptraffic import EpTraffic, Outline, Plan, densify, dist_nm, epww_outline, path_hits

AD = {"EDDF": (50.033, 8.570), "EYVI": (54.637, 25.288), "LOWW": (48.110, 16.570), "EPWA": (52.166, 20.967),
      "EGLL": (51.471, -0.461), "EPKK": (50.078, 19.785), "EPGD": (54.378, 18.466), "EDDB": (52.362, 13.501),
      "LKPR": (50.101, 14.260), "UHPP": (53.168, 158.454), "PADK": (51.878, -176.646)}
# punkty tras na niby: P1, P2 w Polsce, P3 i TANNE w Niemczech, ALPEN w Austrii
FIX = {"P1": (53.0, 21.0), "P2": (52.3, 17.0), "P3": (51.5, 12.0), "TANNE": (50.0, 12.0), "ALPEN": (48.5, 14.0),
       "NORIL": (69.3, 88.2)}  # NORIL: punkt o tej samej nazwie na Syberii (pomyłka w trasie)


class FakeResolver:
    """RouteResolver bez bazy: znane identyfikatory z AD i FIX, reszta pominięta (jak nieznany punkt)."""

    def __init__(self):
        self.resolved, self.prefetched = [], []

    def prefetch(self, texts):
        self.prefetched.append(sorted(texts))

    def resolve(self, text):
        self.resolved.append(text)
        pts = [{"ident": t, "kind": "AD" if t in AD else "FIX", "lat": (AD | FIX)[t][0], "lon": (AD | FIX)[t][1]}
               for t in text.split() if t in AD or t in FIX]
        return {"points": pts, "warnings": []}


def pilot(cs, lat, lon, dep=None, arr=None, route=None):
    return {"callsign": cs, "lat": lat, "lon": lon, "departure": dep, "arrival": arr, "route": route}


@pytest.fixture(scope="module")
def outline():
    return epww_outline()


@pytest.fixture
def traffic(outline):
    return EpTraffic(lambda: outline)


def test_outline_is_epww_from_ese(outline):
    assert outline.contains(*AD["EPWA"]) and outline.contains(52.2, 15.5)
    assert not outline.contains(52.5, 13.4) and not outline.contains(*AD["EDDF"])  # Berlin, Frankfurt
    # przestrzeń nad Bałtykiem delegowana do EPWW (EPWW-MIDSEA) jest w obrysie; Bornholm (ESMM) nie
    assert outline.contains(55.5, 17.5) and not outline.contains(55.1, 14.9)
    # granica na Odrze przy 52,25° N: ok. 14,7° E
    assert not outline.contains(52.25, 14.6) and outline.contains(52.25, 14.8)


def test_densify_and_corner_clip():
    pts = densify([AD["EDDF"], AD["EYVI"]])
    assert pts[0] == AD["EDDF"] and pts[-1] == AD["EYVI"]
    assert max(dist_nm(a, b) for a, b in zip(pts, pts[1:])) <= 20.01
    square = Outline([[(20, 52), (21, 52), (21, 53), (20, 53)]])
    assert square.contains(52.5, 20.5) and not square.contains(52.5, 19.9)
    # oba końce poza kwadratem, środek odcinka ścina róg
    a, b = (52.1, 19.95), (51.95, 20.1)
    assert not square.contains(*a) and not square.contains(*b) and square.touches(a, b)
    assert path_hits([(51.0, 19.0), a, b, (51.0, 21.5)], square) == [False, True, False, False]


def test_ep_departures_and_arrivals(traffic):
    fr = FakeResolver()
    rels = traffic.relations([pilot("LOT1", 51.0, -0.2, "EPWA", "EGLL", "DCT"), pilot("BAW2", 51.4, -0.4, "EGLL", "EPWA"),
                              pilot("LOT3", 52.0, 19.6, "EPKK", "EPGD")], fr)
    # lot krajowy: serwer mówi "dep", odlot / przylot rozstrzyga przeglądarka (relation() w map.js)
    assert rels == ["dep", "arr", "dep"] and fr.resolved == []


def test_overflight_over_poland_is_transit(traffic):
    fr = FakeResolver()
    route = pilot("DLH1", 50.3, 10.0, "EDDF", "EYVI", "N0450F360 TANNE DCT P3 DCT P2 DCT P1")
    gc = pilot("DLH2", 50.3, 10.0, "EDDF", "EYVI", "DCT")  # bez punktów trasy: łuk od pozycji do EYVI przez Polskę
    assert traffic.relations([route, gc], fr) == ["trn", "trn"]


def test_route_away_from_poland_is_dropped(traffic):
    fr = FakeResolver()
    rels = traffic.relations([pilot("AUA1", 49.0, 12.0, "EDDF", "LOWW", "TANNE DCT ALPEN"),
                              pilot("AUA2", 49.0, 12.0, "EDDF", "LOWW", "")], fr)
    assert rels == [None, None]


def test_far_off_route_point_is_ignored(traffic, outline):
    # bez filtra odcinek TANNE → NORIL szedłby nad Polską
    assert any(path_hits(densify([FIX["TANNE"], FIX["NORIL"]]), outline))
    fr = FakeResolver()
    assert traffic.relations([pilot("AUA3", 49.0, 12.0, "EDDF", "LOWW", "TANNE DCT NORIL DCT ALPEN")], fr) == [None]


def test_already_exited_and_about_to_enter(traffic):
    fr = FakeResolver()
    west = "P1 DCT P2 DCT P3"  # EYVI → EDDF przez Polskę
    rels = traffic.relations([
        pilot("BTI1", 52.0, 13.5, "EYVI", "EDDF", west),    # nad Niemcami, Polska za nim
        pilot("BTI2", 52.25, 14.3, "EYVI", "EDDF", west),   # ok. 15 NM za granicą na Odrze
        pilot("BTI3", 52.2, 15.5, "EYVI", "EDDF", west),    # jeszcze w FIR EPWW
        pilot("BTI4", 52.25, 14.3, "EDDF", "EYVI", "P3 DCT P2 DCT P1"),  # to samo miejsce, ale leci na wschód
    ], fr)
    assert rels == [None, None, "trn", "trn"]


def test_without_flight_plan_only_inside(traffic):
    fr = FakeResolver()
    assert traffic.relations([pilot("SPABC", 52.0, 19.0), pilot("DEXYZ", 48.5, 11.0)], fr) == ["trn", None]
    assert fr.resolved == []


def test_unresolvable_route_falls_back_to_great_circle(traffic):
    fr = FakeResolver()
    rels = traffic.relations([
        pilot("RYR1", 50.3, 10.0, "EDDF", "EYVI", "XXXXX UN999 YYYYY"),  # nieznane punkty: łuk do EYVI przez Polskę
        pilot("RYR2", 49.0, 12.0, "EDDF", "LOWW", "XXXXX"),              # łuk do LOWW omija Polskę
        pilot("RYR3", 49.0, 12.0, "ZZZZ", "QQQQ", "XXXXX"),              # nic nie wiadomo: bez relacji
    ], fr)
    assert rels == ["trn", None, None]


def test_plan_cache(traffic):
    fr = FakeResolver()
    p = pilot("DLH9", 50.3, 10.0, "EDDF", "EYVI", "TANNE DCT P3 DCT P2 DCT P1")
    assert traffic.relations([p], fr) == ["trn"]
    assert fr.resolved == ["EDDF TANNE DCT P3 DCT P2 DCT P1 EYVI"] and fr.prefetched == [[fr.resolved[0]]]
    # nowa pozycja: bez ponownego rozpisywania trasy, liczy się tylko reszta trasy
    for lat, lon, rel in ((51.0, 11.5, "trn"), (52.5, 17.0, "trn"), (54.0, 23.5, None)):
        assert traffic.relations([p | {"lat": lat, "lon": lon}], fr) == [rel]
    assert len(fr.resolved) == 1 and len(fr.prefetched) == 1
    # zmieniony plan (inne lotnisko docelowe i trasa): rozpisany od nowa
    assert traffic.relations([p | {"arrival": "LOWW", "route": "TANNE DCT ALPEN"}], fr) == [None]
    assert len(fr.resolved) == 2 and traffic.cached() == 1


def test_plan_build_fallback_marks(outline):
    fr = FakeResolver()
    assert Plan.build("EDDF", "DCT", "EYVI", fr, outline).pts is None
    plan = Plan.build("EDDF", "P2", "EYVI", fr, outline)
    assert plan.pts and plan.last >= 0 and plan.dest == AD["EYVI"]


def test_round_trip_keeps_route_points(traffic):
    """Lot po kręgu (ADEP = ADES): elipsa wokół lotnisk to koło o promieniu co najmniej 300 NM, a nie 125 NM."""
    fr = FakeResolver()
    rels = traffic.relations([pilot("OKABC", *AD["LKPR"], "LKPR", "LKPR", "DCT EPKK DCT"),   # ok. 210 NM od LKPR
                              pilot("DEABC", *AD["EDDB"], "EDDB", "EDDB", "DCT EPWA DCT"),   # ok. 285 NM od EDDB
                              pilot("DEXYZ", *AD["EDDB"], "EDDB", "EDDB", "DCT TANNE DCT")], fr)
    assert rels == ["trn", "trn", None]


def test_antimeridian_leg_does_not_touch_poland(traffic, outline):
    """Odcinek przez południk 180° nie jest próbkowany wzdłuż 360° długości (przez Polskę)."""
    a, b = (52.34, 179.67), (52.28, -179.80)
    assert not outline.touches(a, b) and not any(path_hits([a, b], outline))
    fr = FakeResolver()
    assert traffic.relations([pilot("PAC2", 53.0, 165.0, "UHPP", "PADK", "DCT")], fr) == [None]


class BrokenResolver(FakeResolver):
    """Baza nawigacyjna niedostępna (np. zablokowana w trakcie importu danych)."""

    def __init__(self, prefetch_fails=True):
        super().__init__()
        self.prefetch_fails = prefetch_fails

    def prefetch(self, texts):
        if self.prefetch_fails:
            raise OperationalError("SELECT", {}, Exception("database is locked"))

    def resolve(self, text):
        self.resolved.append(text)
        raise OperationalError("SELECT", {}, Exception("database is locked"))


def test_nav_db_failure_is_soft(traffic):
    """Błąd bazy przy rozpisywaniu trasy: relacja z lotnisk i pozycji, trasa nie zostaje w pamięci (następnym razem
    rozpisana), a po pierwszym błędzie nie pytamy bazy o kolejne trasy (każde zapytanie to czekanie na blokadę)."""
    flights = [pilot("LOT1", 52.1, 20.9, "EPWA", "EPKK"), pilot("SPABC", 52.0, 19.0),
               pilot("DLH1", 50.3, 10.0, "EDDF", "EYVI", "TANNE DCT P3"), pilot("DLH2", 50.3, 10.0, "EDDF", "EYVI", "P2")]
    for broken in (BrokenResolver(), BrokenResolver(prefetch_fails=False)):
        assert traffic.relations(flights, broken) == ["dep", "trn", None, None]
        assert traffic.cached() == 0 and len(broken.resolved) <= 1
    assert traffic.relations(flights, FakeResolver()) == ["dep", "trn", "trn", "trn"] and traffic.cached() == 2


NODE_VS = r"""
globalThis.L = { CircleMarker: { extend: (o) => o } };
const { climbRates } = await import(process.argv[2]);
const out = [];
let hist = new Map();
for (const [t, list] of JSON.parse(process.argv[3])) {
  hist = climbRates(list, hist, t);
  out.push(Object.fromEntries(list.map((p) => [p.callsign, p.vs])));
}
console.log(JSON.stringify(out));
"""


def test_climb_rates_ignore_quick_reloads(tmp_path):
    """MAP (airspace.js climbRates): wczytanie ruchu kilka sekund po poprzednim (wybór lotu, wykres vIFF) dostaje
    z serwera ten sam feed; vs liczy się tylko względem odczytu sprzed co najmniej 25 s, inaczej zostaje poprzednie."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    js = Path(__file__).resolve().parents[2] / "frontend" / "js"
    (tmp_path / "api.mjs").write_text((js / "api.js").read_text("utf-8"), "utf-8")
    (tmp_path / "airspace.mjs").write_text((js / "airspace.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'),
                                           "utf-8")
    (tmp_path / "run.mjs").write_text(NODE_VS, "utf-8")

    def dom(alt):
        return {"callsign": "DOM1", "altitude": alt}

    steps = [(0, [dom(6000)]), (30000, [dom(4500)]), (35000, [dom(4500), {"callsign": "NEW1", "altitude": 3000}]),
             (40000, [dom(4500), {"callsign": "NEW1", "altitude": 3000}]), (60000, [dom(3000)]),
             (65000, [dom(None)]), (95000, [dom(2000)])]
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "airspace.mjs").as_uri(), json.dumps(steps)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        {"DOM1": None}, {"DOM1": -1500},
        {"DOM1": -1500, "NEW1": None},   # 5 s po odczycie: poprzednie vs, a nie 0 (feed sprzed 5 s)
        {"DOM1": -1500, "NEW1": None},
        {"DOM1": -1500},                 # 30 s po odczycie z 30000: 4500 → 3000
        {"DOM1": -1500},                 # 5 s później (bez wysokości): poprzednie vs
        {"DOM1": -1000}]                 # względem odczytu z 60000
