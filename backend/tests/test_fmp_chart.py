"""OTHER › FMP (0.13.1, issue #25): wykresy ENTRY i OCC wybranego sektora. Backend: loty jednego traffic volume
z całodobowych /etfms/airspaces (tv_flights), regulacje jako przedziały minut (reg_spans), szeregi wykresów
(sector_series: szczyt tylko z rysowanych minut, zgodność z liczeniem wprost), sector_chart z atrapą vIFF, jutrzejsza
doba jako dodatek także o 23Z (sectors() i wykres) i endpoint GET /api/viff/sectors/{tv} (400 / 404 / 502 / 200).
Frontend w Node: entrySvg / occSvg / fmpChartHtml (klasy obciążenia, przygaszona przeszłość, linia "teraz",
przepustowość i regulacja, dymki, oś przez północ, escapowanie), cleanTv, fmpHtml z wybranym wierszem i zachowanie
mountFmp na atrapie DOM (wybór z adresu, klik, drugi klik, ✕, spóźniona odpowiedź, błąd odświeżenia, destroy)."""
import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR  # noqa: E402
from backend.app.services import viff  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

JS = ROOT_DIR / "frontend" / "js"
NOW = datetime(2026, 10, 5, 13, 10, tzinfo=timezone.utc)

# całodobowe /etfms/airspaces dla EP-BH: lot przez pełną godzinę w dwóch koszykach (BBB2), same czasy planowane
# (AAA1), wyliczone wejście z planowanym wyjściem przed nim (MIX = minuta), złe krotki
DAY = {"EP-BH": [
    {"hour": "12", "entriesCapacity": 40, "peakCapacity": 14, "entriesCount": 3, "peakCount": 2,
     "flights": [["AAA1", "1200", "1210", "", "", True], ["BBB2", "1250", "1305", "1255", "1310", True],
                 "x", ["ZZZ"], ["YYY", "", "1300"]]},
    {"hour": "13", "entriesCapacity": 999, "entriesCount": 2, "peakCount": 1,
     "flights": [["BBB2", "1250", "1305", "1255", "1310", True], ["CCC3", "1330", "1345", "1332", "1350", False]]},
    {"hour": "14", "entriesCapacity": 50, "flights": [["DDD4", "1400", "1420", "1400", "1420", False],
                                                       ["FFF6", "1405", "1430", "1405", "1430", True]]},
    {"hour": "15", "flights": [["EEE5", "1500", "1515", "1500", "", False]]},
    {"hour": "16", "flights": [["MIX", "1600", "1601", "1610", "", False]]},
]}
RESTR = [{"type": "ENR-ENTRIES", "value": 30, "start": "1400", "end": "1600"},
         {"type": "enr-entries", "value": "25", "start": "1500", "end": "1530"},
         {"type": "ENR-OCCUPANCY", "value": True, "start": "1200", "end": "1300"},
         {"type": "ENR-OCCUPANCY", "value": 0, "start": "1200", "end": "1300"},
         {"type": "ENR-OCCUPANCY", "value": [1], "start": "1200", "end": "1300"},
         {"type": "ENR-OCCUPANCY", "value": 8, "start": "1230", "end": "1300"},
         {"type": "OTHER", "value": 5, "start": "1200", "end": "1700"}, "x"]
ROW = {"id": "EP-BH", "entries_cap": 45, "occupancy_cap": 14, "restrictions": RESTR, "active": True}
# tuż po północy: lot 2350-0010 we wczorajszym koszyku 23 i w dzisiejszym 00 (jeden wpis)
YESTERDAY = {"EP-BH": [{"hour": "23", "flights": [["NIGHT1", "2350", "0010", "2350", "0010", True],
                                                  ["LATE", "2300", "2305", "", "", False]]}]}
TODAY_0 = {"EP-BH": [{"hour": "00", "flights": [["NIGHT1", "2350", "0010", "2350", "0010", True],
                                                ["EARLY", "0030", "0040", "0031", "0041", False]]}]}
TVS = [{"id": "EP-BH", "volumes": "EPWW-BH", "status": 1, "entries": 45, "occupancy": 14, "restrictions": RESTR},
       {"id": "EP-DM", "volumes": "EPWW-DM", "status": 0, "entries": 30, "occupancy": 12, "restrictions": []}]


def run(coro):
    return asyncio.run(coro)


def at(h, m=10, day=5):
    return datetime(2026, 10, day, h, m, tzinfo=timezone.utc)


# --- czyste funkcje backendu

def test_tv_flights():
    fl = viff.tv_flights("EP-BH", {0: DAY})
    by = {f["callsign"]: (f["entry"], f["exit"]) for f in fl}
    # wyliczone czasy przed planowanymi; lot z dwóch koszyków raz; złe krotki pominięte
    assert [f["callsign"] for f in fl] == ["AAA1", "BBB2", "CCC3", "DDD4", "FFF6", "EEE5", "MIX"]
    assert by["AAA1"] == (720, 730) and by["BBB2"] == (775, 790) and by["CCC3"] == (812, 830)
    # wyliczone wejście, planowane wyjście: 1500-1515; wyjście "przed" wejściem (mieszanka czasów) = minuta w sektorze
    assert by["EEE5"] == (900, 915) and by["MIX"] == (970, 971)
    assert fl[0]["airborne"] is True and fl[2]["airborne"] is False
    # 2355 w koszyku 00 dzisiejszej doby = to samo co koszyk 23 wczoraj (minuta -5); wyjście po północy
    night = viff.tv_flights("EP-BH", {-1: YESTERDAY, 0: TODAY_0})
    assert [(f["callsign"], f["entry"], f["exit"]) for f in night] == [("LATE", -60, -55), ("NIGHT1", -10, 10), ("EARLY", 31, 41)]
    same = viff.tv_flights("EP-BH", {0: {"EP-BH": [{"hour": "00", "flights": [["X1", "2355", "0005", "", "", True]]}]}})
    assert [(f["entry"], f["exit"]) for f in same] == [(-5, 5)]
    # inny TV, brak danych, zły kształt odpowiedzi
    assert viff.tv_flights("EP-DM", {0: DAY}) == [] and viff.tv_flights("EP-BH", {0: None, 1: []}) == []
    assert viff.tv_flights("EP-BH", {0: {"EP-BH": "x"}}) == [] and viff.tv_flights("EP-BH", {0: {"EP-BH": ["x", {}]}}) == []


def test_reg_spans():
    # 1400-1600 w oknie 1200-1700: od 120 do 241 (koniec włącznie jak restriction_active); "25" jako napis przyjęte
    ent = viff.reg_spans(RESTR, "entries", 720, 1020)
    assert ent == [{"from": 120, "to": 241, "value": 30, "start": "1400", "end": "1600"},
                   {"from": 180, "to": 211, "value": 25, "start": "1500", "end": "1530"}]
    # True, 0, lista i inne rodzaje pominięte
    assert viff.reg_spans(RESTR, "occupancy", 720, 1020) == [{"from": 30, "to": 61, "value": 8, "start": "1230", "end": "1300"}]
    # przez północ: 2200-0200 o 00:30 (okno 2300-0400) = od początku okna do 0200 włącznie
    night = [{"type": "ENR-OCCUPANCY", "value": 9, "start": "2200", "end": "0200"}]
    assert viff.reg_spans(night, "occupancy", -60, 240) == [{"from": 0, "to": 181, "value": 9, "start": "2200", "end": "0200"}]
    # cała doba: odcinki wczoraj / dziś przycięte do okna
    allday = [{"type": "ENR-ENTRIES", "value": 20, "start": "0000", "end": "2359"}]
    assert [(s["from"], s["to"]) for s in viff.reg_spans(allday, "entries", -60, 240)] == [(0, 60), (60, 300)]
    # najniższa z obowiązujących
    assert [viff.reg_at(ent, m) for m in (119, 120, 180, 210, 211, 240, 241)] == [None, 30, 25, 25, 30, 30, None]
    assert viff.reg_spans(None, "entries", 0, 300) == [] and viff.reg_spans([{"type": "ENR-ENTRIES", "value": 5}], "entries", 0, 300) == []


def test_sector_series():
    c = viff.sector_series("EP-BH", {0: DAY}, NOW, ROW)
    assert (c["start"], c["now"], c["minutes"], c["now_at"], c["step"], c["span"]) == ("1200", "1310", 300, 70, 20, 60)
    occ = c["occupancy"]
    assert len(occ) == 301
    # minuta wejścia liczona, minuta wyjścia już nie
    assert [occ[m] for m in (0, 9, 10, 55, 69, 70, 92, 110, 120, 125, 139, 140, 150, 180, 250, 251)] == \
        [1, 1, 0, 1, 1, 0, 1, 0, 1, 2, 2, 1, 0, 1, 1, 0]
    ent = c["entries"]
    assert [e["time"] for e in ent][:4] == ["1200", "1220", "1240", "1300"] and len(ent) == 15
    # wejścia w kolejnych 60 min co 20 min (lot dokładnie po 60 min już nie)
    assert [e["count"] for e in ent] == [2, 1, 2, 1, 3, 2, 2, 1, 1, 1, 1, 1, 1, 0, 0]
    # przepustowość z koszyka godziny (999 = bez limitu → z definicji TV), bez koszyka: z definicji
    assert [e["cap"] for e in ent] == [40, 40, 40, 45, 45, 45, 50, 50, 50, 45, 45, 45, 45, 45, 45]
    assert [e["reg"] for e in ent] == [None] * 6 + [30, 30, 30, 25, 25, 30, 30, None, None]
    assert [e["from"] for e in ent] == list(range(0, 300, 20))
    assert c["hours"][0] == {"hour": "12", "entries": 3, "entries_cap": 40, "peak": 2, "peak_cap": 14}
    assert [h["hour"] for h in c["hours"]] == ["12", "13", "14", "15", "16"] and c["hours"][1]["entries_cap"] is None
    assert c["entries_reg"][0]["value"] == 30 and c["occupancy_reg"] == [{"from": 30, "to": 61, "value": 8, "start": "1230", "end": "1300"}]
    # szczyt od teraz do końca okna (wcześniejsze minuty się nie liczą)
    assert (c["peak"], c["peak_at"], c["flights"]) == (2, "1405", 7)
    assert (c["entries_cap"], c["occupancy_cap"]) == (45, 14)
    # 00:10: okno od 2300 wczoraj, dane z dwóch dób
    n = viff.sector_series("EP-BH", {-1: YESTERDAY, 0: TODAY_0}, at(0, 10, 6), {**ROW, "restrictions": []})
    assert (n["start"], n["now_at"], n["now"]) == ("2300", 70, "0010")
    assert [n["occupancy"][m] for m in (0, 5, 50, 69, 70, 91)] == [1, 0, 1, 1, 0, 1]
    assert n["entries"][0]["count"] == 2 and n["entries"][3] == {"from": 60, "time": "0000", "count": 1, "cap": 45, "reg": None}
    # pusta doba: zera, szczyt 0
    e = viff.sector_series("EP-BH", {0: {}}, NOW, ROW)
    assert not any(e["occupancy"]) and e["peak"] == 0 and e["peak_at"] == "1310" and e["flights"] == 0


def _hour(h, *flights):
    return {"hour": h, "flights": [[cs, a, b, a, b, True] for cs, a, b in flights]}


def test_sector_series_peak_drawn_minutes():
    # szczyt tylko z rysowanych minut [teraz, 1700): pięć wejść dokładnie o 1700 (minuta końca okna, poza wykresem)
    # nie ustawia peak / peak_at, choć punkt occupancy[300] nadal jest w odpowiedzi
    late = {"EP-BH": [_hour("13", ("ONE", "1315", "1320")),
                      _hour("17", *[(f"END{i}", "1700", "1710") for i in range(5)])]}
    c = viff.sector_series("EP-BH", {0: late}, NOW, ROW)
    occ = c["occupancy"]
    assert len(occ) == 301 and occ[300] == 5 and max(occ[:300]) == 1
    assert (c["peak"], c["peak_at"], c["flights"]) == (1, "1315", 1)
    # ostatnia rysowana minuta (1659) liczy się do szczytu
    edge = {"EP-BH": [_hour("16", *[(f"E{i}", "1659", "1710") for i in range(3)])]}
    c = viff.sector_series("EP-BH", {0: edge}, NOW, ROW)
    assert (c["peak"], c["peak_at"], c["occupancy"][299], c["flights"]) == (3, "1659", 3, 3)


def _slow_series(tv, days, now):
    """Wzorzec: zajętość, słupki E60/20, liczba lotów i szczyt liczone wprost, minuta po minucie po wszystkich lotach."""
    start = (now.hour - viff.CHART_HOURS_BEFORE) * 60
    minutes = viff.CHART_HOURS * 60
    end = start + minutes
    fl = viff.tv_flights(tv, days)
    occ = [sum(1 for f in fl if f["entry"] <= start + m < f["exit"]) for m in range(minutes + 1)]
    counts = [sum(1 for f in fl if t <= f["entry"] < t + viff.CHART_SPAN) for t in range(start, end, viff.CHART_STEP)]
    ahead = occ[now.hour * 60 + now.minute - start:minutes]
    return occ, counts, sum(1 for f in fl if f["exit"] > start and f["entry"] < end), max(ahead), ahead.index(max(ahead))


def _random_day(rng, n):
    hm = lambda m: f"{m % 1440 // 60:02d}{m % 60:02d}"  # noqa: E731
    buckets = {}
    for i in range(n):
        e = rng.randrange(1440)
        x = e + rng.choice([rng.randrange(1, 90), rng.randrange(1, 400), 0, 800])   # także wyjście "przed" wejściem
        t = [f"R{i % (n // 2 + 1)}", hm(e), hm(x), *([hm(e), hm(x)] if rng.random() < .8 else ["", ""]), True]
        for h in {e // 60, x // 60 if x < 1440 else e // 60}:
            buckets.setdefault(h, []).append(t)
    return {"EP-BH": [{"hour": f"{h:02d}", "flights": f} for h, f in sorted(buckets.items())]}


def test_sector_series_matches_direct_count():
    # zawężenie lotów do okna, tablica różnic i bisekcja dają to samo co liczenie wprost po całych dobach
    rng = random.Random(25)
    for _ in range(40):
        now = at(rng.randrange(24), rng.randrange(60))
        days = {d: _random_day(rng, rng.choice([0, 5, 40, 120])) for d in (-1, 0, 1) if d == 0 or rng.random() < .6}
        c = viff.sector_series("EP-BH", days, now, ROW)
        occ, counts, flights, peak, peak_from_now = _slow_series("EP-BH", days, now)
        assert c["occupancy"] == occ and [e["count"] for e in c["entries"]] == counts and c["flights"] == flights, now
        assert c["peak"] == peak and c["peak_at"] == viff._abs_hhmm(now.hour * 60 + now.minute + peak_from_now), now


def _fake(calls, fail=(), days=None, load=None, exc=UpstreamError):
    days = days or {"2026-10-05": DAY}

    async def get(path, params=None, ttl=None):
        if path == "/etfms/trafficVolumes":
            return TVS
        if path == "/etfms/scenarios":
            return []
        if path == "/etfms/airspaces":
            if "fromNow" in params:   # sectors(): bieżąca doba od teraz
                return load or {}
            calls.append(params["date"])
            if params["date"] in fail:
                raise exc("timeout")
            return days.get(params["date"], {})
        raise ValueError(path)
    return get


def test_sector_chart_service():
    viff_get = viff._get
    try:
        calls = []
        viff._get = _fake(calls)
        c = run(viff.sector_chart("ep-bh", NOW))
        assert calls == ["2026-10-05"] and c["id"] == "EP-BH" and c["label"] == "sector B upper" and c["prefix"] == "EP"
        # aktywność, przepustowość i regulacje jak wiersz tabeli FMP (sectors())
        row = next(s for s in run(viff.sectors("EP", NOW))["sectors"] if s["id"] == "EP-BH")
        for k in ("active", "entries_cap", "occupancy_cap", "restricted", "regulated", "scenarios", "volumes"):
            assert c[k] == row[k], k
        assert c["active"] is True and (c["entries_cap"], c["occupancy_cap"]) == (45, 14)
        assert [e["count"] for e in c["entries"]][:5] == [2, 1, 2, 1, 3] and len(c["occupancy"]) == 301
        # doby potrzebne dla okna: 00:10 wczoraj i dziś, 19:10 dziś, 20:10 i 21:10 dziś i jutro
        for when, dates in ((at(0, 10, 6), ["2026-10-05", "2026-10-06"]), (at(19), ["2026-10-05"]),
                            (at(20), ["2026-10-05", "2026-10-06"]), (at(21), ["2026-10-05", "2026-10-06"])):
            calls.clear()
            assert run(viff.sector_chart("EP-BH", when)) is not None and calls == dates, when
        # nieznany TV
        assert run(viff.sector_chart("EP-XX", NOW)) is None
        # błąd wczoraj: wykres z dzisiejszych danych
        viff._get = _fake(calls, fail=("2026-10-05",), days={"2026-10-06": TODAY_0})
        c = run(viff.sector_chart("EP-BH", at(0, 10, 6)))
        assert c["start"] == "2300" and c["flights"] == 2 and c["occupancy"][0] == 0
        # błąd jutrzejszej doby także o 23Z (sectors() pobiera ją dla następnej godziny): wykres z dzisiejszych danych
        for exc in (UpstreamError, ValueError):
            for h in (21, 23):
                calls.clear()
                viff._get = _fake(calls, fail=("2026-10-06",), exc=exc)
                c = run(viff.sector_chart("EP-BH", at(h)))
                assert c is not None and c["start"] == f"{h - 1}00", (exc, h)
                assert calls == (["2026-10-06"] if h == 23 else []) + ["2026-10-05", "2026-10-06"], (exc, h)
        # błąd dzisiejszej doby: UpstreamError (router: 502)
        viff._get = _fake(calls, fail=("2026-10-05",))
        with pytest.raises(UpstreamError):
            run(viff.sector_chart("EP-BH", NOW))
    finally:
        viff._get = viff_get


def test_sectors_tomorrow_optional():
    # o 23Z następna godzina tabeli FMP jest z jutrzejszej doby; jej błąd = pusta następna godzina, nie błąd całej tabeli
    load = {"EP-BH": [{"hour": "23", "entriesCount": 4, "flights": [["A1", "2320", "2330", "2320", "2330", True]]}]}
    nxt = {"EP-BH": [{"hour": "00", "entriesCount": 7, "flights": [["B2", "0005", "0015", "0005", "0015", False]]}]}
    viff_get = viff._get
    try:
        calls = []
        viff._get = _fake(calls, days={"2026-10-06": nxt}, load=load)
        row = next(s for s in run(viff.sectors("EP", at(23)))["sectors"] if s["id"] == "EP-BH")
        assert calls == ["2026-10-06"] and [h["entries"] for h in row["hours"]] == [4, 7]
        for exc in (UpstreamError, ValueError):
            viff._get = _fake(calls, fail=("2026-10-06",), days={"2026-10-06": nxt}, load=load, exc=exc)
            d = run(viff.sectors("EP", at(23)))
            row = next(s for s in d["sectors"] if s["id"] == "EP-BH")
            assert {s["id"] for s in d["sectors"]} == {"EP-BH", "EP-DM"} and [h["entries"] for h in row["hours"]] == [4], exc
            assert [f["callsign"] for f in row["flights"]] == ["A1"] and row["active"] is True, exc
        # przed 23Z jutrzejsza doba nie jest potrzebna
        calls.clear()
        run(viff.sectors("EP", at(22)))
        assert calls == []
    finally:
        viff._get = viff_get


@pytest.fixture
def client():
    viff_get = viff._get
    yield TestClient(main.app)  # bez lifespan: router vIFF nie potrzebuje bazy
    viff._get = viff_get


def test_sector_endpoint(client):
    viff._get = _fake([], days={})
    r = client.get("/api/viff/sectors/EP-BH")
    assert r.status_code == 200
    c = r.json()
    assert c["id"] == "EP-BH" and len(c["occupancy"]) == 301 and len(c["entries"]) == 15 and c["minutes"] == 300
    assert client.get("/api/viff/sectors/ep-bh").json()["id"] == "EP-BH"
    # 0.12.6: komunikaty bez nazwy źródła
    r = client.get("/api/viff/sectors/EP-XX")
    assert r.status_code == 404 and r.json()["detail"] == "No flow data for sector EP-XX"
    for bad in ("EPBH", "EP%20BH", "E-1", "EP-", "EP-" + "A" * 22, "EP-B_H"):
        assert client.get(f"/api/viff/sectors/{bad}").status_code == 400, bad
    # lista sektorów nadal pod /api/viff/sectors
    d = client.get("/api/viff/sectors").json()
    assert {s["id"] for s in d["sectors"]} == {"EP-BH", "EP-DM"}

    async def down(path, params=None, ttl=None):
        raise UpstreamError("api.example: timeout")
    viff._get = down
    r = client.get("/api/viff/sectors/EP-BH")
    assert r.status_code == 502 and r.json()["detail"] == "Flow data unavailable"


def test_sector_endpoints_at_23z_without_tomorrow(client, monkeypatch):
    # 23:10, jutrzejsza doba niedostępna: tabela FMP i wykres odpowiadają 200 (bez lotów po północy), nie 502
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at(23)
    monkeypatch.setattr(viff, "datetime", Clock)
    viff._get = _fake([], fail=("2026-10-06",))
    r = client.get("/api/viff/sectors/EP-BH")
    assert r.status_code == 200 and (r.json()["start"], r.json()["now"]) == ("2200", "2310")
    r = client.get("/api/viff/sectors")
    assert r.status_code == 200 and r.json()["now"] == "2310" and {s["id"] for s in r.json()["sectors"]} == {"EP-BH", "EP-DM"}


# --- frontend w Node

NODE_SCRIPT = r"""
const fmp = await import(process.argv[2]);
const series = JSON.parse((await import("node:fs")).readFileSync(process.argv[3], "utf-8"));
const zeros = (n) => Array.from({ length: n }, () => 0);
const occ = zeros(301);
for (let m = 10; m < 20; m += 1) occ[m] = 2;
for (let m = 100; m < 105; m += 1) occ[m] = 5;
occ[150] = 4;
const counts = [20, 39, 44, 10, 20];
const c = { id: "EP-<X>", label: "sector <X>", now: "1310", start: "1200", minutes: 300, now_at: 70, step: 20, span: 60,
  active: false, restricted: true, entries_cap: 43, occupancy_cap: 4,
  entries: Array.from({ length: 15 }, (_, i) => ({ from: i * 20, time: "", count: counts[i] ?? 0, cap: i === 3 ? null : 43,
    reg: i === 4 ? 30 : null })),
  occupancy: occ, entries_reg: [{ from: 80, to: 100, value: 30, start: "1320", end: "1339" }],
  occupancy_reg: [{ from: 200, to: 241, value: 3, start: "1520", end: "1600" }, { from: 0, to: 10, value: 9, start: "1200", end: "1209" }],
  peak: 5, peak_at: "1340" };
const empty = { ...c, id: "EP-BH", restricted: false, active: true, entries: c.entries.map((e) => ({ ...e, count: 0 })), occupancy: zeros(301),
  entries_reg: [], occupancy_reg: [], peak: 0, peak_at: "1310" };
const night = { ...c, start: "2300" };
console.log(JSON.stringify({
  entry: fmp.entrySvg(c), occ: fmp.occSvg(c), html: fmp.fmpChartHtml(c), emptyHtml: fmp.fmpChartHtml(empty),
  nightEntry: fmp.entrySvg(night), withRow: fmp.fmpChartHtml(empty, { code: "BH", label: "sector B upper", active: true }, "Not refreshed: x"),
  real: fmp.fmpChartHtml(series), pick: fmp.fmpPickHtml(), wait: fmp.fmpWaitHtml("EP-DM"), err: fmp.fmpWaitHtml("EP-DM", null, "Flow <data>"),
  clean: ["ep-bh", " EP-WATMA ", "EP BH", "X", "", null, undefined, "ED-EDWW-ALR", "EP-" + "A".repeat(21), "EP-B_H"].map(fmp.cleanTv),
}));
"""

API_STUB = r"""
// atrapa DOM: elementy z innerHTML, nasłuchami i classList; wiersze tabeli (tr[data-tv]) z ostatniego innerHTML
const classes = (init = "") => { const set = new Set(init.split(/\s+/).filter(Boolean));
  return { toggle(c, on) { if (on) set.add(c); else set.delete(c); }, contains: (c) => set.has(c), list: () => [...set].sort() }; };
const row = (tv, cls) => ({ dataset: { tv }, classList: classes(cls), scrollIntoView() { globalThis.__scrolled.push(tv); } });
const makeEl = () => ({ _html: "", kids: {}, on: {}, rows: [], isConnected: true, offsetParent: {}, scrollTop: 0, textContent: "",
  classList: classes(),
  get innerHTML() { return this._html; },
  set innerHTML(v) { this._html = v; this.rows = [...v.matchAll(/<tr class="([^"]*)" data-tv="([^"]*)">/g)].map((m) => row(m[2], m[1])); },
  addEventListener(t, f) { (this.on[t] ||= []).push(f); },
  querySelector(sel) { return sel === "tr.sel" ? this.rows.find((r) => r.classList.contains("sel")) || null : (this.kids[sel] ||= makeEl()); },
  querySelectorAll(sel) { return sel === "tr[data-tv]" ? this.rows : []; } });
export const ONLINE_EVENT = "polids:online";
export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
export const h = () => makeEl();
export const api = (url) => new Promise((res, rej) => globalThis.__pending.push({ url, res, rej }));
"""

MOUNT_SCRIPT = r"""
globalThis.__pending = [];
globalThis.__scrolled = [];
const timers = [], cleared = [], listeners = {};
globalThis.setInterval = (f) => { timers.push(f); return timers.length; };
globalThis.clearInterval = (id) => cleared.push(id);
globalThis.window = { addEventListener(t, f) { (listeners[t] ||= []).push(f); },
  removeEventListener(t, f) { listeners[t] = (listeners[t] || []).filter((x) => x !== f); } };
const fmp = await import(process.argv[2]);
const tick = () => new Promise((r) => setImmediate(r));
const tv = (id, o) => ({ id, hours: [], occupancy: [], peak_60: 0, entries_cap: 40, occupancy_cap: 14, restrictions: [], ...o });
const sectors = { prefix: "EP", now: "1310", sectors: [tv("EP-BH", { active: true }), tv("EP-DM", { active: true }),
  tv("EP-WATMA", { active: false, restricted: true })] };
const chart = (id) => ({ id, label: "x", now: "1310", start: "1200", minutes: 300, now_at: 70, step: 20, span: 60, active: true,
  restricted: false, entries_cap: 40, occupancy_cap: 14, entries: [{ from: 0, count: 3, cap: 40, reg: null }],
  occupancy: [1, 2, 3], entries_reg: [], occupancy_reg: [], peak: 3, peak_at: "1312" });
const picks = [];
const pane = { append(x) { this.root = x; } };
const page = fmp.mountFmp(pane, { start: "ep-dm", onPick: (id) => picks.push(id) });
const root = pane.root, box = root.querySelector(".fmp-scroll"), side = root.querySelector(".fmp-side");
const main = root.querySelector(".fmp-main");
const urls = () => globalThis.__pending.map((p) => p.url);
const take = (url) => { const i = globalThis.__pending.findIndex((p) => p.url === url); return globalThis.__pending.splice(i, 1)[0]; };
const sel = () => box.rows.filter((r) => r.classList.contains("sel")).map((r) => r.dataset.tv);
const head = () => (/class="fmc-code[^"]*" title="([^"]+)"/.exec(side.innerHTML) || [])[1] || null;
const clickRow = (id) => box.on.click.forEach((f) => f({ target: { closest: (s) => (s === "tr[data-tv]" ? { dataset: { tv: id } } : null) } }));
const clickClose = () => side.on.click.forEach((f) => f({ target: { closest: (s) => (s === ".fmc-close" ? {} : null) } }));
const o = {};
// adres z sektorem: tabela i wykres od razu, panel "Loading" z kodem sektora, wiersz zaznaczony i przewinięty do widoku
o.start = [urls(), side.innerHTML.includes("Loading") && head(), main.classList.contains("open")];
take("/api/viff/sectors").res(sectors);
await tick();
o.table = [sel(), [...globalThis.__scrolled], box.innerHTML.includes('class="on sel" data-tv="EP-DM"')];
take("/api/viff/sectors/EP-DM").res(chart("EP-DM"));
await tick();
o.chart = [head(), side.innerHTML.includes("fmc-svg"), picks.length];
// klik w inny wiersz: krok historii (onPick), zaznaczenie bez rysowania tabeli od nowa, wykres nowego sektora
const html = box.innerHTML;
clickRow("EP-BH");
o.click = [[...picks], sel(), urls(), box.innerHTML === html, head(), side.innerHTML.includes("Loading")];
// szybki drugi wybór: spóźniona odpowiedź dla EP-BH nic nie rysuje
clickRow("EP-WATMA");
take("/api/viff/sectors/EP-WATMA").res(chart("EP-WATMA"));
await tick();
take("/api/viff/sectors/EP-BH").res(chart("EP-BH"));
await tick();
o.late = [head(), [...picks], sel()];
// drugi klik w ten sam wiersz: wykresy zamknięte, podpowiedź, bez zapytania
clickRow("EP-WATMA");
o.toggle = [[...picks], sel(), side.innerHTML, main.classList.contains("open"), urls()];
// sektor z adresu (Wstecz / Dalej): bez onPick, wiersz przewinięty do widoku
page.activate("EP-DM");
take("/api/viff/sectors/EP-DM").res(chart("EP-DM"));
await tick();
o.addr = [[...picks], sel(), head(), [...globalThis.__scrolled]];
// odświeżenie co 60 s: tabela i wykres; błąd wykresu zostawia wykres z komunikatem
timers[0]();
o.refreshUrls = urls();
take("/api/viff/sectors").res(sectors);
take("/api/viff/sectors/EP-DM").rej(Object.assign(new Error("Flow data unavailable"), { status: 502 }));
await tick();
o.refreshErr = [head(), side.innerHTML.includes("fmc-svg"), side.innerHTML.includes("Not refreshed: Flow data unavailable")];
// ✕: wykresy zamknięte, krok historii z pustym sektorem; potem odświeżenie bez zapytania o wykres
clickClose();
o.close = [[...picks], sel(), side.innerHTML.includes("Click a sector")];
timers[0]();
o.idleUrls = urls();
take("/api/viff/sectors").res(sectors);
await tick();
// zły sektor z adresu = nic nie wybrane (bez zapytania); nieznany: komunikat w panelu z ✕
page.activate("x y");
o.bad = urls();
page.activate("EP-XX");
take("/api/viff/sectors/EP-XX").rej(Object.assign(new Error("No flow data for sector EP-XX"), { status: 404 }));
await tick();
o.unknown = [head(), side.innerHTML.includes("No flow data for sector EP-XX"), side.innerHTML.includes("fmc-close"), [...picks]];
// ONLINE_EVENT: od razu tabela i wykres; destroy(): bez timera i nasłuchu, spóźnione dane nic nie rysują
listeners["polids:online"].forEach((f) => f());
o.online = urls();
const before = side.innerHTML;
page.destroy();
take("/api/viff/sectors/EP-XX").res(chart("EP-XX"));
await tick();
o.destroyed = [cleared, (listeners["polids:online"] || []).length, side.innerHTML === before];
console.log(JSON.stringify(o));
"""


def _node():
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    return node


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = _node()
    d = tmp_path_factory.mktemp("fmpchart")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    for name in ("viffchart", "fmp"):
        src = (JS / f"{name}.js").read_text("utf-8")
        (d / f"{name}.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"').replace('"./viffchart.js"', '"./viffchart.mjs"'), "utf-8")
    # szereg z backendu (sector_series) jako dane wykresu: ten sam kontrakt co GET /api/viff/sectors/{tv}
    c = viff.sector_series("EP-BH", {0: DAY}, NOW, ROW)
    c.update({"label": "sector B upper", "active": True, "restricted": False})
    (d / "series.json").write_text(json.dumps(c), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "fmp.mjs").as_uri(), str(d / "series.json")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _rects(svg):
    return re.findall(r'<rect [^>]*class="([^"]+)"><title>([^<]*)</title>', svg)


def test_entry_chart(js):
    bars = _rects(js["entry"])
    assert len(bars) == 15
    # obciążenie wobec niższej z przepustowości deklarowanej i regulowanej; słupki, których 20 min minęło, przygaszone
    assert [b[0] for b in bars[:6]] == ["fmc-ok past", "fmc-near past", "fmc-over past", "fmc-nolim", "fmc-ok", "fmc-ok"]
    assert sum("past" in b[0] for b in bars) == 3
    assert bars[4][1] == "1320–1420Z: 20 entries in 60 min, regulated 30, declared 43"
    assert bars[3][1] == "1300–1400Z: 10 entries in 60 min, no limit"
    assert bars[0][1] == "1200–1300Z: 20 entries in 60 min, capacity 43"
    # liczby nad niezerowymi słupkami, oś czasu co godzinę, jedna linia "teraz"
    assert re.findall(r'class="fmc-val">(\d+)<', js["entry"]) == ["20", "39", "44", "10", "20"]
    assert re.findall(r'class="fmc-ax">(\d{4})<', js["entry"]) == ["1200", "1300", "1400", "1500", "1600", "1700"]
    assert re.findall(r'class="fmc-ax">(\d{4})<', js["nightEntry"]) == ["2300", "0000", "0100", "0200", "0300", "0400"]
    now = re.findall(r'<line x1="([\d.]+)" x2="([\d.]+)"[^>]*class="fmc-now"', js["entry"])
    assert now == [("159.1", "159.1")]
    # przepustowość deklarowana schodkami (przerwa przy słupku bez limitu), regulacja tylko nad regulowanym słupkiem
    assert js["entry"].count('class="fmc-cap"') == 2 and js["entry"].count('class="fmc-reg"') == 1
    assert 'class="fmc-capt">43<' in js["entry"]


def test_occ_chart(js):
    cols = _rects(js["occ"])
    # kolumny tej samej wartości złączone; przeszłość przygaszona; 5 przy progu 4 = ponad, 4 = 90-100 %
    assert cols == [("fmc-ok past", "1210–1219Z: 2 aircraft, capacity 4"),
                    ("fmc-over", "1340–1344Z: 5 aircraft, capacity 4"),
                    ("fmc-near", "1430Z: 4 aircraft, capacity 4")]
    # próg przerywany przez całe okno; regulacja czerwona tylko tam, gdzie jest niższa od progu (3, nie 9)
    assert js["occ"].count('class="fmc-cap"') == 1 and js["occ"].count('class="fmc-reg"') == 1
    reg = re.search(r'<line x1="([\d.]+)" x2="([\d.]+)"[^>]*class="fmc-reg"', js["occ"])
    assert (reg.group(1), reg.group(2)) == ("391.3", "464.6")
    assert js["occ"].count('class="fmc-now"') == 1 and 'class="fmc-capt">4<' in js["occ"]


def test_chart_panel(js):
    h = js["html"]
    # nagłówek: kod escapowany, czerwony przy regulacji, INACTIVE, ✕; przepustowość i regulacje
    assert '<span class="fmc-code reg" title="EP-&lt;X&gt;">&lt;X&gt;</span>' in h and "<X>" not in h
    assert '<span class="fmc-desc">sector &lt;X&gt;</span>' in h and '<span class="fmc-chip">INACTIVE</span>' in h
    assert 'class="fmc-close" title="Close the charts"' in h and ">✕</button>" in h
    assert "capacity: 43 entries/h \u00b7 4 aircraft at once" in h
    assert ('<span class="fmc-regtxt"> · regulated: entries 30 1320–1339, occupancy 3 1520–1600, '
            'occupancy 9 1200–1209</span>') in h
    assert "ENTRY <span>entries in 60 min, every 20 min</span>" in h and "OCC <span>aircraft in the sector, per minute</span>" in h
    assert "1310Z · peak 5 at 1340Z" in h and "No traffic" not in h
    for label in ("below 90 %", "90–100 %", "over capacity", "no limit", "capacity", "regulated"):
        assert f"</i>{label}</span>" in h, label
    # bez ruchu: osie i progi zostają, jedno zdanie; kod z wiersza tabeli, komunikat odświeżenia w nagłówku
    e = js["emptyHtml"]
    assert "No traffic in this period." in e and e.count('class="fmc-cap"') == 3 and "peak" not in e and "fmc-regtxt" not in e
    w = js["withRow"]
    assert '<span class="fmc-code" title="EP-BH">BH</span>' in w and '<span class="fmc-chip on">ACTIVE</span>' in w
    assert '<span class="fmc-msg error">Not refreshed: x</span>' in w
    # szereg z backendu rysuje się bez błędów: 15 słupków, regulacje wejść, próg zajętości z regulacją 8 < 14
    real = js["real"]
    assert len(_rects(real.split("OCC <span>")[0])) == 15 and real.count('class="fmc-reg"') >= 2
    assert "regulated: entries 30 1400–1600, entries 25 1500–1530, occupancy 8 1230–1300" in real
    for html in (h, e, w, real, js["wait"], js["err"]):
        assert "<b>" not in html and "<b " not in html and "<strong" not in html
    assert js["pick"] == '<p class="hint fmp-pick">Click a sector to see its ENTRY and OCC charts.</p>'
    assert 'title="EP-DM">DM</span>' in js["wait"] and "Loading…" in js["wait"] and "fmc-close" in js["wait"]
    assert '<p class="error fmc-err">Flow &lt;data&gt;</p>' in js["err"]


def test_clean_tv(js):
    assert js["clean"] == ["EP-BH", "EP-WATMA", "", "", "", "", "", "ED-EDWW-ALR", "", ""]


def test_fmp_page_behaviour(tmp_path):
    node = _node()
    (tmp_path / "api.mjs").write_text(API_STUB, "utf-8")
    (tmp_path / "viffchart.mjs").write_text((JS / "viffchart.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    src = (JS / "fmp.js").read_text("utf-8")
    (tmp_path / "fmp.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"').replace('"./viffchart.js"', '"./viffchart.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(MOUNT_SCRIPT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "fmp.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["start"] == [["/api/viff/sectors", "/api/viff/sectors/EP-DM"], "EP-DM", True]
    assert o["table"] == [["EP-DM"], ["EP-DM"], True]
    assert o["chart"] == ["EP-DM", True, 0]
    picks, sel, urls, same, head, loading = o["click"]
    assert picks == ["EP-BH"] and sel == ["EP-BH"] and urls == ["/api/viff/sectors/EP-BH"] and same and head == "EP-BH" and loading
    assert o["late"] == ["EP-WATMA", ["EP-BH", "EP-WATMA"], ["EP-WATMA"]]
    picks, sel, side, open_, urls = o["toggle"]
    assert picks == ["EP-BH", "EP-WATMA", ""] and sel == [] and "Click a sector" in side and not open_ and urls == []
    # przewinięcia do wiersza: tabela z adresu, pierwszy wykres każdego nowego wyboru (EP-DM, EP-WATMA; spóźniony EP-BH
    # nic nie rysuje), wybór z adresu i jego wykres; scrollIntoView({block: "nearest"}) przy widocznym wierszu nic nie robi
    assert o["addr"] == [["EP-BH", "EP-WATMA", ""], ["EP-DM"], "EP-DM", ["EP-DM", "EP-DM", "EP-WATMA", "EP-DM", "EP-DM"]]
    assert o["refreshUrls"] == ["/api/viff/sectors", "/api/viff/sectors/EP-DM"]
    assert o["refreshErr"] == ["EP-DM", True, True]
    assert o["close"] == [["EP-BH", "EP-WATMA", "", ""], [], True]
    assert o["idleUrls"] == ["/api/viff/sectors"]
    assert o["bad"] == []
    assert o["unknown"] == ["EP-XX", True, True, ["EP-BH", "EP-WATMA", "", ""]]
    assert o["online"] == ["/api/viff/sectors", "/api/viff/sectors/EP-XX"]
    assert o["destroyed"] == [[1], 0, True]
