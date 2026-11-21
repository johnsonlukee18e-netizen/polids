"""0.14.1 (właściciel projektu: "Fix graphs when selecting TV on FMP page"): vIFF podaje w krotkach lotów
/etfms/airspaces czasy ISO z datą ("2026-11-21T00:11:00.000Z", wyliczone z milisekundami), a hhmm() brało z nich rok
("2026" = 20:26). Wszystkie loty sektora wpadały wtedy w jedną minutę i wykresy ENTRY/OCC (OTHER › FMP i MAP)
pokazywały same linie przepustowości. Kształt odpowiedzi jak w żywych danych z 21.11.2026: koszyk {hour: "00",
entriesCapacity, peakCapacity, entriesCount, peakCount, active, flights: [[znak, wejście plan., wyjście plan.,
wejście wylicz., wyjście wylicz., flaga]]}."""
import asyncio
import os
import tempfile
from datetime import date, datetime, timezone

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

from backend.app.services import viff  # noqa: E402

TODAY = date(2026, 11, 21)
NOW = datetime(2026, 11, 21, 13, 10, tzinfo=timezone.utc)


def iso(d, hm, ms=False):
    return f"2026-11-{d:02d}T{hm[:2]}:{hm[2:]}:{'02.226' if ms else '00.000'}Z"


# lot przez północ (pierwsza krotka z żywych danych), lot w godzinie 13 obecny w dwóch koszykach, lot z samymi
# czasami planowanymi (wyliczone puste) i lot jutro po północy w danych jutrzejszej doby
DAY = {"EP-DH": [
    {"hour": "00", "entriesCapacity": 999, "peakCapacity": 26, "entriesCount": 1, "peakCount": 1, "active": False,
     "flights": [["RYR8704", "2026-11-20T23:43:00.000Z", "2026-11-21T00:11:00.000Z", "2026-11-20T23:37:02.226Z",
                  "2026-11-21T00:04:01.933Z", True]]},
    {"hour": "12", "entriesCapacity": 44, "peakCapacity": 15, "entriesCount": 2, "peakCount": 2, "active": True,
     "flights": [["LOT1", iso(21, "1250"), iso(21, "1315"), iso(21, "1252", True), iso(21, "1318", True), True],
                 ["PLAN", iso(21, "1220"), iso(21, "1240"), "", "", False]]},
    {"hour": "13", "entriesCapacity": 44, "peakCapacity": 15, "entriesCount": 2, "peakCount": 2, "active": True,
     "flights": [["LOT1", iso(21, "1250"), iso(21, "1315"), iso(21, "1252", True), iso(21, "1318", True), True],
                 ["WZZ2", iso(21, "1330"), iso(21, "1355"), iso(21, "1331"), iso(21, "1356"), False],
                 ["EZY3", iso(21, "1345"), iso(21, "1410"), iso(21, "1347"), iso(21, "1409"), False]]},
    {"hour": "14", "entriesCapacity": 44, "flights": [["EZY3", iso(21, "1345"), iso(21, "1410"), iso(21, "1347"),
                                                       iso(21, "1409"), False],
                                                      ["DLH4", iso(21, "1420"), iso(21, "1450"), iso(21, "1421"),
                                                       iso(21, "1452"), False]]},
]}
TVS = [{"id": "EP-DH", "volumes": "EPWW-DH", "status": 1, "entries": 44, "occupancy": 15, "restrictions": []}]


def run(coro):
    return asyncio.run(coro)


def test_hhmm_reads_iso_times():
    assert viff.hhmm("2026-11-21T00:11:00.000Z") == "0011"
    assert viff.hhmm("2026-11-20T23:37:02.226Z") == "2337"
    assert viff.hhmm("2026-11-21T15:20") == "1520"
    # strefa inna niż UTC przeliczona na UTC
    assert viff.hhmm("2026-11-21T01:30:00+01:00") == "0030"
    # stare postacie bez zmian
    assert viff.hhmm("1520") == "1520" and viff.hhmm("152000") == "1520" and viff.hhmm(1520) == "1520"
    # sama data i śmieci = brak godziny (wcześniej "2026")
    for v in ("2026-10-05", "", None, "abc", "12"):
        assert viff.hhmm(v) is None, v


def test_abs_minutes_iso_exact_and_hhmm_by_bucket():
    assert viff.abs_minutes("2026-11-20T23:37:02.226Z", 0, 0, TODAY) == -23
    assert viff.abs_minutes("2026-11-22T00:20:00.000Z", 1, 0, TODAY) == 1440 + 20
    assert viff.abs_minutes("2026-11-21T13:31:00.000Z", 0, 13, TODAY) == 13 * 60 + 31
    # 'HHMM' bez daty: najbliżej godziny koszyka (2355 w koszyku 00 = wczoraj)
    assert viff.abs_minutes("2355", 0, 0) == -5 and viff.abs_minutes("0010", 0, 0) == 10
    assert viff.abs_minutes("", 0, 0, TODAY) is None


def test_tv_flights_iso():
    fl = {f["callsign"]: f for f in viff.tv_flights("EP-DH", {0: DAY}, TODAY)}
    # przez północ: wejście wczoraj 23:37, wyjście dziś 00:04 (nie 20:26 z roku "2026")
    assert (fl["RYR8704"]["entry"], fl["RYR8704"]["exit"]) == (-23, 4)
    # lot w dwóch koszykach = jeden wpis, czasy wyliczone (13:18:02 = minuta 13:18)
    assert (fl["LOT1"]["entry"], fl["LOT1"]["exit"]) == (12 * 60 + 52, 13 * 60 + 18)
    # bez czasów wyliczonych: planowane
    assert (fl["PLAN"]["entry"], fl["PLAN"]["exit"]) == (12 * 60 + 20, 12 * 60 + 40)
    assert (fl["EZY3"]["entry"], fl["EZY3"]["exit"]) == (13 * 60 + 47, 14 * 60 + 9)
    assert len(fl) == 6
    # nic nie wpada w minutę 20:26
    assert all(f["entry"] != 20 * 60 + 26 for f in fl.values())


def test_sector_series_iso_draws_bars():
    row = {"id": "EP-DH", "entries_cap": 44, "occupancy_cap": 15, "restrictions": []}
    c = viff.sector_series("EP-DH", {0: DAY}, NOW, row)
    assert c["start"] == "1200" and c["now"] == "1310"
    counts = {e["time"]: e["count"] for e in c["entries"]}
    # wejścia w 60 min od 12:00: PLAN 12:20, LOT1 12:52 = 2; od 12:20 tak samo; od 13:00: WZZ2 13:31, EZY3 13:47;
    # od 13:40: EZY3 i DLH4 14:21; od 14:00: DLH4
    assert [counts[k] for k in ("1200", "1220", "1300", "1340", "1400", "1440")] == [2, 2, 2, 2, 1, 0]
    # zajętość: 12:55 LOT1, 13:50 WZZ2 i EZY3, 14:30 DLH4
    occ = c["occupancy"]
    assert occ[55] == 1 and occ[110] == 2 and occ[150] == 1 and max(occ) == 2
    assert c["flights"] == 5   # RYR8704 przed oknem


def test_sector_load_iso():
    load = viff.sector_load("EP-DH", DAY["EP-DH"], NOW)
    names = [f["callsign"] for f in load["flights"]]
    # +60 min od 13:10: DLH4 (14:21) poza oknem
    assert names == ["LOT1", "WZZ2", "EZY3"]
    lot = load["flights"][0]
    assert (lot["entry"], lot["exit"]) == ("1252", "1318")
    assert load["entries_60"] == 2 and load["peak_60"] == 2


def test_flight_profile_iso():
    prof = viff.flight_profile("EZY3", [DAY], NOW)
    assert len(prof) == 1
    p = prof[0]
    assert (p["tv"], p["entry"], p["exit"], p["planned_entry"], p["state"]) == ("EP-DH", "1347", "1409", "1345", "next")
    night = viff.flight_profile("RYR8704", [DAY], NOW)
    assert [(n["entry"], n["exit"], n["state"]) for n in night] == [("2337", "0004", "past")]


def test_sector_chart_endpoint_data_iso():
    calls = []

    async def get(path, params=None, ttl=None):
        if path == "/etfms/trafficVolumes":
            return TVS
        if path == "/etfms/scenarios":
            return []
        if path == "/etfms/airspaces":
            calls.append(params["date"])
            return DAY if params["date"] == "2026-11-21" else {}
        raise ValueError(path)

    old = viff._get
    viff._get = get
    try:
        c = run(viff.sector_chart("EP-DH", NOW))
    finally:
        viff._get = old
    assert c is not None and sum(e["count"] for e in c["entries"]) > 0 and max(c["occupancy"]) == 2
