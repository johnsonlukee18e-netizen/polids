"""vIFF: scenariusze, szczegóły lotu (/ifps/callsign) i wejścia lotu w sektory."""
import asyncio
import os
import tempfile
from datetime import datetime, timezone

import httpx

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.services import viff  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

NOW = datetime(2026, 10, 5, 21, 10, tzinfo=timezone.utc)

SCENARIOS = [
    {"_id": "a", "id": "EP-ALLFIR", "active": False, "isActive": False, "start": "0000", "end": "2359", "positions": "EPWW_ALL_CTR",
     "nopositions": "EPWW_S_CTR,EPWW_J_CTR,EPWW_N_CTR", "anypositions": "", "trafficVolumes": [["EP-ALLFIR", 20, 52]],
     "useBookedPositions": False, "times": [], "airports": [], "description": ""},
    {"_id": "b", "id": "EP-KKTMA", "active": False, "isActive": False, "anypositions": "EPKK_APP", "positions": "", "nopositions": "",
     "trafficVolumes": [["EP-KKTMA", 17, 999], ["EP-KKTMAD", 8, 999]], "useBookedPositions": True, "times": [], "oneTimes": [],
     "description": "test"},
    {"_id": "c", "id": "EP-WATMA", "isActive": True, "anypositions": "EPWA_APP", "trafficVolumes": [["EP-WATMA", 20, 999], ["EP-WATMAD", 15, 999]],
     "times": [[1, [], "1800", "2000"]], "useBookedPositions": True},
]

FLIGHT = {
    "callsign": "LOT3827", "cid": "1234567", "departure": "EPWA", "arrival": "EPGD", "eobt": "2055", "tobt": "", "obt": "", "reqTobt": "",
    "taxi": 10, "ctot": "2120", "aobt": "2056", "atot": "2108", "eta": "2152", "mostPenalizingAirspace": "EP-GDTMA", "cdmSts": "AIRB",
    "isCdm": True, "informed": True, "latestRevisedCtot": "", "atfcmStatus": "ATC_ACTIV",
    "history": "2026-10-05 19:58 -> Flight processed (EPWA - EPGD) EOBT: 2055. ITEM15: OLILA L621 RILAB DCT OSLOG|"
               "2026-10-05 20:56 -> Detected in movement. AOBT: 2056|2026-10-05 21:08 -> Airborne. ATOT: 2108|",
    "actualAirspace": "EP-GDTMA", "atfcmData": {"mostPenalisingRegulation": "EPGDA21", "isRea": False},
    "flightPlanning": {"cruise_altitude": "22000", "cruise_tas": "406", "route": "", "enrTime": 44, "isValid": True, "aircraft_short": "B38M"},
    "onTime": "+5", "landed": False, "cdmData": {"tobt": "205500", "tsat": "205600", "ttot": "210600", "ctot": "", "reason": "", "depInfo": "29/OLI1G"},
    "timeStamp": "2026-10-05T21:09:00Z",
}

# całodobowe /etfms/airspaces: lot przez pełną godzinę jest w dwóch koszykach (duplikat do usunięcia)
DAY = {
    "EP-WATMA": [{"hour": "21", "flights": [["LOT3827", "2105", "2116", "2106", "2117", True], ["RYR1", "2110", "2120", "", "", False]]}],
    "EP-WATMAD": [{"hour": "21", "flights": [["LOT3827", "2100", "2108", "2101", "2108", True]]}],
    "EP-BH": [{"hour": "21", "flights": [["LOT3827", "2130", "2142", "2131", "2149", True]]}],
    "EP-BM": [{"hour": "21", "flights": [["LOT3827", "2112", "2131", "2116", "2131", True]]}],
    "EP-GDTMA": [{"hour": "21", "flights": [["LOT3827", "2140", "2155", "2148", "2203", True]]},
                 {"hour": "22", "flights": [["LOT3827", "2140", "2155", "2148", "2203", True]]}],
}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client():
    viff_get = viff._get
    yield TestClient(main.app)  # bez lifespan: router vIFF nie potrzebuje bazy
    viff._get = viff_get


def fake(responses: dict):
    async def get(path, params=None, ttl=None):
        r = responses[path]
        if isinstance(r, Exception):
            raise r
        return r(params) if callable(r) else r
    return get


def test_scenario_normalisation_and_label():
    s = [viff.scenario(x) for x in SCENARIOS]
    assert s[0]["tvs"] == [{"id": "EP-ALLFIR", "occupancy_cap": 20, "entries_cap": 52}]
    assert s[0]["positions"] == ["EPWW_ALL_CTR"] and s[0]["nopositions"] == ["EPWW_S_CTR", "EPWW_J_CTR", "EPWW_N_CTR"]
    assert (s[0]["start"], s[0]["end"], s[0]["active"], s[0]["booked"]) == ("0000", "2359", False, False)
    assert s[1]["tvs"][1] == {"id": "EP-KKTMAD", "occupancy_cap": 8, "entries_cap": None}  # 999 = bez limitu
    assert s[1]["anypositions"] == ["EPKK_APP"] and s[1]["booked"] and s[1]["description"] == "test"
    assert s[2]["active"] and s[2]["times"] == [{"from": "1800", "to": "2000", "date": None}] and s[2]["start"] is None
    assert viff._times([["2026-10-07", "0600", "0900"]]) == [{"from": "0600", "to": "0900", "date": "2026-10-07"}]
    assert [viff.tv_label(t) for t in ("EP-BH", "EP-WATMA", "EP-KKTMAD", "EP-ALLFIR", "EP-SFIR2", "EP-XYZ")] == [
        "sektor B górny", "TMA EPWA", "TMA EPKK (D)", "cały FIR", "FIR południe 2", "kombinacja sektorów"]


def test_history_level_and_profile():
    h = viff.history(FLIGHT["history"])
    assert len(h) == 3 and h[1] == {"time": "2026-10-05 20:56", "text": "Detected in movement. AOBT: 2056"}
    assert viff.history("") == [] and viff.history(None) == []
    assert (viff._level("22000"), viff._level("F350"), viff._level("4500"), viff._level("")) == ("FL220", "FL350", "4500 ft", None)
    assert (viff._duration(44), viff._duration("0115"), viff._duration("x")) == (44, 75, None)
    p = viff.flight_profile("LOT3827", [DAY], NOW)
    assert [x["tv"] for x in p] == ["EP-WATMAD", "EP-WATMA", "EP-BM", "EP-BH", "EP-GDTMA"]  # wg wejścia wyliczonego, bez duplikatu
    assert p[1] == {"tv": "EP-WATMA", "label": "TMA EPWA", "planned_entry": "2105", "planned_exit": "2116", "entry": "2106",
                    "exit": "2117", "state": "now"}
    assert [x["state"] for x in p] == ["past", "now", "next", "next", "next"]
    # brak czasów wyliczonych → planowane
    assert viff.flight_profile("RYR1", [DAY], NOW)[0]["entry"] == "2110"
    # o 23Z także jutro (tylko wejścia przed 12Z), wyjście po północy
    late = datetime(2026, 10, 5, 23, 50, tzinfo=timezone.utc)
    today = {"EP-BH": [{"hour": "23", "flights": [["X1", "2355", "0010", "2355", "0012", True]]}]}
    tomorrow = {"EP-BH": [{"hour": "00", "flights": [["X1", "2355", "0010", "2355", "0012", True]]}],
                "EP-BM": [{"hour": "00", "flights": [["X1", "0012", "0030", "", "", True]]}],
                "EP-DH": [{"hour": "20", "flights": [["X1", "2000", "2030", "", "", False]]}]}
    p = viff.flight_profile("X1", [today, tomorrow], late)
    assert [(x["tv"], x["entry"], x["state"]) for x in p] == [("EP-BH", "2355", "next"), ("EP-BM", "0012", "next")]


def test_profile_after_midnight():
    # 00:10Z: w koszyku 00 dzisiejszych danych jest wejście 2355 z poprzedniej doby (lot jest teraz w sektorze)
    early = datetime(2026, 10, 6, 0, 10, tzinfo=timezone.utc)
    day = {"EP-BH": [{"hour": "00", "flights": [["X1", "2350", "0015", "2355", "0020", True]]}],
           "EP-CH": [{"hour": "00", "flights": [["X1", "0020", "0035", "", "", True]]}],
           "EP-DH": [{"hour": 0, "flights": [["X1", "2340", "2352", "2340", "2353", True]]}]}
    p = viff.flight_profile("X1", [day], early)
    assert [(x["tv"], x["entry"], x["exit"], x["state"]) for x in p] == [
        ("EP-DH", "2340", "2353", "past"), ("EP-BH", "2355", "0020", "now"), ("EP-CH", "0020", "0035", "next")]
    # wczorajsze dane: sektory sprzed północy (bez duplikatów), ale nie poranny lot o tym samym znaku
    yesterday = {"EP-JH": [{"hour": "23", "flights": [["X1", "2320", "2340", "2321", "2340", True]]}],
                 "EP-BH": [{"hour": "23", "flights": [["X1", "2350", "0015", "2355", "0020", True]]}],
                 "EP-GH": [{"hour": "09", "flights": [["X1", "0900", "0930", "", "", True]]}]}
    p = viff.flight_profile("X1", [day], early, yesterday)
    assert [(x["tv"], x["state"]) for x in p] == [("EP-JH", "past"), ("EP-DH", "past"), ("EP-BH", "now"), ("EP-CH", "next")]
    calls = []

    def airspaces(params):
        calls.append(params["date"])
        return day if params["date"] == "2026-10-06" else yesterday

    viff_get = viff._get
    try:  # o 00Z serwis pobiera też wczoraj
        viff._get = fake({"/ifps/callsign": {**FLIGHT, "callsign": "X1"}, "/etfms/airspaces": airspaces})
        f = run(viff.flight("X1", early))
        assert calls == ["2026-10-06", "2026-10-05"] and [x["tv"] for x in f["sectors"]] == ["EP-JH", "EP-DH", "EP-BH", "EP-CH"]
    finally:
        viff._get = viff_get


def test_flight_other_callsign_is_unknown():
    viff_get = viff._get
    try:  # vIFF zwraca inny lot (np. dopasowanie częściowe): to nie jest szukany lot
        viff._get = fake({"/ifps/callsign": {**FLIGHT, "callsign": "LOT3827A"}, "/etfms/airspaces": DAY})
        assert run(viff.flight("LOT3827", NOW)) is None
    finally:
        viff._get = viff_get


def test_flight_service():
    calls = []

    def day(params):
        calls.append(params["date"])
        return DAY

    viff_get = viff._get
    try:
        viff._get = fake({"/ifps/callsign": FLIGHT, "/etfms/airspaces": day})
        f = run(viff.flight("lot3827", NOW))
        assert (f["callsign"], f["departure"], f["arrival"], f["aircraft"], f["rfl"], f["tas"]) == ("LOT3827", "EPWA", "EPGD", "B38M", "FL220", 406)
        assert f["route"] == "OLILA L621 RILAB DCT OSLOG"  # pusta trasa w planie → ITEM15 z historii
        assert (f["state"], f["eta"], f["on_time"], f["enroute_min"], f["actual_airspace"], f["is_cdm"]) == ("AA", "2152", "+5", 44, "EP-GDTMA", True)
        assert (f["tobt"], f["tsat"], f["aobt"], f["atot"], f["ctot"], f["delay"], f["regulation"]) == ("2055", "2056", "2056", "2108", "2120", 15, "EPGDA21")
        assert len(f["history"]) == 3 and len(f["sectors"]) == 5 and f["sectors_error"] is None and calls == ["2026-10-05"]
        run(viff.flight("LOT3827", datetime(2026, 10, 5, 23, 5, tzinfo=timezone.utc)))
        assert calls[-2:] == ["2026-10-05", "2026-10-06"]
        # nieznany lot: null, {}, [] albo tekst zamiast JSON-u
        for empty in (None, {}, [], ValueError("not json")):
            viff._get = fake({"/ifps/callsign": empty, "/etfms/airspaces": DAY})
            assert run(viff.flight("XXX1", NOW)) is None
        # lista lotów: wybieramy pasujący znak
        viff._get = fake({"/ifps/callsign": [{"callsign": "ABC"}, FLIGHT], "/etfms/airspaces": DAY})
        assert run(viff.flight("LOT3827", NOW))["callsign"] == "LOT3827"
        # brak danych sektorów nie psuje szczegółów lotu
        viff._get = fake({"/ifps/callsign": FLIGHT, "/etfms/airspaces": UpstreamError("timeout")})
        f = run(viff.flight("LOT3827", NOW))
        assert f["sectors"] == [] and "timeout" in f["sectors_error"]
    finally:
        viff._get = viff_get


def test_flight_endpoint(client):
    viff._get = fake({"/ifps/callsign": lambda p: FLIGHT if p["callsign"] == "LOT3827" else None, "/etfms/airspaces": DAY})
    r = client.get("/api/viff/flight/lot3827")
    assert r.status_code == 200 and r.json()["callsign"] == "LOT3827" and r.json()["states"]["AA"].startswith("AA")
    r = client.get("/api/viff/flight/ABC123")
    assert r.status_code == 404 and "vIFF nie zna lotu ABC123" in r.json()["detail"]
    for bad in ("X", "LOT-1", "ABCDEFGHIJK"):
        assert client.get(f"/api/viff/flight/{bad}").status_code == 400
    viff._get = fake({"/ifps/callsign": UpstreamError("timeout")})
    r = client.get("/api/viff/flight/LOT3827")
    assert r.status_code == 502 and "vIFF" in r.json()["detail"]
    # HTTP 404 z vIFF = nieznany lot, nie awaria
    resp = httpx.Response(404, request=httpx.Request("GET", "https://api.viffsys.com/ifps/callsign"))
    err = UpstreamError("404")
    err.__cause__ = httpx.HTTPStatusError("404", request=resp.request, response=resp)
    viff._get = fake({"/ifps/callsign": err})
    assert client.get("/api/viff/flight/LOT3827").status_code == 404


def test_sectors_with_scenarios(client):
    tvs = [{"id": "EP-BH", "volumes": "EPWW-BH", "status": 1, "entries": 30, "occupancy": 12},
           {"id": "EP-WATMA", "volumes": "EPWA-TMA", "status": 0, "entries": 999, "occupancy": 20}]
    viff._get = fake({"/etfms/trafficVolumes": tvs, "/etfms/airspaces": {}, "/etfms/scenarios": SCENARIOS})
    d = client.get("/api/viff/sectors").json()
    assert [s["id"] for s in d["scenarios"]] == ["EP-WATMA", "EP-ALLFIR", "EP-KKTMA"]  # aktywne na początku
    by_id = {s["id"]: s for s in d["sectors"]}
    # TV ze scenariuszy są na liście, nawet bez definicji i ruchu
    assert {"EP-ALLFIR", "EP-KKTMA", "EP-KKTMAD", "EP-WATMAD"} <= set(by_id)
    assert by_id["EP-WATMA"]["active"] and by_id["EP-WATMAD"]["active"] and by_id["EP-BH"]["active"]  # status 1 albo aktywny scenariusz
    assert not by_id["EP-KKTMA"]["active"] and by_id["EP-KKTMA"]["scenarios"] == ["EP-KKTMA"]
    assert (by_id["EP-ALLFIR"]["entries_cap"], by_id["EP-ALLFIR"]["occupancy_cap"]) == (52, 20)  # przepustowość ze scenariusza
    assert [s["id"] for s in d["sectors"]][:4] == ["EP-BH", "EP-WATMA", "EP-WATMAD", "EP-ALLFIR"]
    # awaria /etfms/scenarios: sektory nadal działają
    viff._get = fake({"/etfms/trafficVolumes": tvs, "/etfms/airspaces": {}, "/etfms/scenarios": UpstreamError("timeout")})
    d = client.get("/api/viff/sectors").json()
    assert d["scenarios"] == [] and len(d["sectors"]) == 2
