"""OTHER › FLIGHT PLAN (0.13.0, issue #23): plan lotu po znaku (pilot online, potem najnowszy prefile), imię
i nazwisko z nazwy w sieci, rating, godziny pilota i ATC z API członków (cache, przerwa po 404 i po błędzie,
ograniczony czas czekania, starsze dane przy awarii) i endpoint /api/vatsim/flightplan/{callsign}.
Oraz wspólna reguła "regulacja obowiązuje teraz" (viff.restriction_active) i flaga restricted w sektorach (FMP)."""
import asyncio
import json
import re
import time
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import settings
from backend.app.routers import vatsim as vatsim_router
from backend.app.services import flightplan, http_cache, viff
from backend.app.services.http_cache import UpstreamError

FP = {"flight_rules": "I", "aircraft": "B38M/M-SDE2E3FGHIJ1RWXY/LB1", "aircraft_faa": "H/B38M/L",
      "aircraft_short": "B38M", "departure": "EPWA", "arrival": "EPGD", "alternate": "EPPO", "cruise_tas": "450",
      "altitude": "37000", "deptime": "1530", "enroute_time": "0045", "fuel_time": "0230",
      "remarks": "PBN/A1B1 DOF/261028 REG/SPLKA RMK/TCAS /V/", "route": "OLILA L621 RILAB", "revision_id": 3,
      "assigned_transponder": "4521"}
PILOT = {"cid": 1234567, "name": "Jan Kowalski EPKK", "callsign": "LOT3827", "server": "GERMANY", "pilot_rating": 1,
         "military_rating": 0, "latitude": 52.1, "longitude": 20.9, "altitude": 3500, "groundspeed": 210, "heading": 290,
         "transponder": "4521", "flight_plan": FP, "logon_time": "2026-10-28T10:00:00Z",
         "last_updated": "2026-10-28T11:00:00Z"}


def feed(pilots=(), prefiles=()):
    return {"general": {"update_timestamp": "2026-10-28T11:00:05Z"}, "pilots": list(pilots), "prefiles": list(prefiles),
            "pilot_ratings": [{"id": 1, "short_name": "PPL", "long_name": "Private Pilot License"}]}


def prefile(cs, updated, cid=7654321, name="Anna Maria Nowak", **fp):
    return {"cid": cid, "name": name, "callsign": cs, "flight_plan": {**FP, **fp}, "last_updated": updated}


@pytest.fixture(autouse=True)
def clean_hours():
    flightplan.reset_hours()
    http_cache.clear_cache()
    yield
    flightplan.reset_hours()
    http_cache.clear_cache()


# --- wyszukiwanie planu

def test_online_pilot_beats_prefile():
    f = feed([PILOT], [prefile("LOT3827", "2026-10-28T11:30:00Z", altitude="24000")])
    d = flightplan.find_flight_plan(f, "lot3827")      # bez względu na wielkość liter
    assert d["status"] == "online" and d["callsign"] == "LOT3827" and d["pid"] == 1234567
    assert d["flight_plan"]["altitude"] == "37000"     # plan pilota online, nie prefile
    assert d["position"] == {"lat": 52.1, "lon": 20.9, "altitude": 3500, "groundspeed": 210, "heading": 290,
                             "squawk": "4521"}
    assert d["updated"] == "2026-10-28T11:00:05Z" and d["logon_time"] == "2026-10-28T10:00:00Z"
    assert d["pilot_rating"] == {"id": 1, "short": "PPL", "long": "Private Pilot License"}
    # wszystkie standardowe pola planu
    assert d["flight_plan"] == {
        "rules": "I", "aircraft_icao": "B38M/M-SDE2E3FGHIJ1RWXY/LB1", "aircraft": "B38M", "aircraft_faa": "H/B38M/L",
        "wake": "M", "departure": "EPWA", "deptime": "1530", "tas": "450", "altitude": "37000",
        "route": "OLILA L621 RILAB", "arrival": "EPGD", "enroute_time": "0045", "alternate": "EPPO",
        "fuel_time": "0230", "remarks": "PBN/A1B1 DOF/261028 REG/SPLKA RMK/TCAS /V/", "revision_id": 3,
        "assigned_squawk": "4521"}
    # nazwa: surowa zawsze, imię i nazwisko bez końcówki z lotniskiem
    assert (d["name"], d["first_name"], d["last_name"]) == ("Jan Kowalski EPKK", "Jan", "Kowalski")


def test_prefile_only_and_newest_wins():
    old = prefile("SPABC", "2026-10-28T09:00:00Z", altitude="5000")
    new = prefile("SPABC", "2026-10-28T10:30:00Z", altitude="6500")
    bad = prefile("SPABC", None, altitude="1000")           # bez czasu = najstarszy
    for order in ([old, new, bad], [new, bad, old], [bad, old, new]):
        d = flightplan.find_flight_plan(feed([], order), "SPABC")
        assert d["status"] == "prefiled" and d["flight_plan"]["altitude"] == "6500", order
    d = flightplan.find_flight_plan(feed([], [new]), " spabc ")
    assert d["position"] is None and d["logon_time"] is None and d["pilot_rating"] is None
    assert (d["first_name"], d["last_name"], d["pid"]) == ("Anna", "Maria Nowak", 7654321)


def test_online_without_plan_and_not_found():
    d = flightplan.find_flight_plan(feed([PILOT | {"callsign": "SPKAT", "flight_plan": None}]), "SPKAT")
    assert d["status"] == "online" and d["flight_plan"] is None and d["position"]["squawk"] == "4521"
    assert flightplan.find_flight_plan(feed([PILOT]), "LOT382") is None      # dokładne dopasowanie, nie prefiks
    assert flightplan.find_flight_plan(feed([PILOT]), "") is None
    assert flightplan.find_flight_plan({}, "LOT3827") is None


def test_plan_fields_empty_values():
    fp = flightplan.plan_fields({"flight_rules": "V", "aircraft": "C172/L-SDFGY/S", "aircraft_faa": "", "remarks": " ",
                                 "assigned_transponder": "0000", "revision_id": "x", "alternate": ""})
    assert fp["rules"] == "V" and fp["wake"] == "L" and fp["aircraft_faa"] is None and fp["remarks"] is None
    assert fp["assigned_squawk"] is None and fp["revision_id"] is None and fp["alternate"] is None
    assert flightplan.plan_fields(None) is None and flightplan.plan_fields({}) is None


@pytest.mark.parametrize("name, cid, expected", [
    ("Jan Kowalski", 1, ("Jan", "Kowalski")),
    ("Jan Kowalski EPKK", 1, ("Jan", "Kowalski")),
    ("Jan Kowalski (EPKK)", 1, ("Jan", "Kowalski")),
    ("Jan Kowalski - EPKK", 1, ("Jan", "Kowalski")),
    ("  Jan   Kowalski  ", 1, ("Jan", "Kowalski")),
    ("Jan", 1, ("Jan", None)),
    ("Jan EPWA", 1, ("Jan", None)),
    ("JAN NOWA", 1, ("JAN", "NOWA")),            # same wielkie litery: NOWA to raczej nazwisko
    ("JAN KOWALSKI EPKK", 1, ("JAN", "KOWALSKI")),
    ("Anna Maria Nowak", 1, ("Anna", "Maria Nowak")),
    ("jan van der Berg", 1, ("jan", "van der Berg")),
    ("Łukasz Żółw EPGD", 1, ("Łukasz", "Żółw")),
    ("1234567", 1234567, (None, None)),         # CID zamiast nazwy
    ("7654321", 1, (None, None)),               # same cyfry
    ("", 1, (None, None)),
    (None, 1, (None, None)),
])
def test_split_name(name, cid, expected):
    assert flightplan.split_name(name, cid) == expected


KNOWN = {"EPKK", "EPWA", "EPGD", "EGLL", "KANE"}


@pytest.mark.parametrize("name, cid, expected", [
    ("Jan Kowalski EPKK", 1, ("Jan", "Kowalski")),
    ("John KING", 1, ("John", "KING")),                 # KING nie jest lotniskiem: nazwisko zostaje
    ("Jean ROUX", 1, ("Jean", "ROUX")),
    ("Anna Maria ROSS", 1, ("Anna", "Maria ROSS")),
    ("Adam ROSS EGLL", 1, ("Adam", "ROSS")),
    ("Jan Kowalski [EPKK]", 1, ("Jan", "Kowalski")),
    ("Jan Kowalski -EPKK", 1, ("Jan", "Kowalski")),
    ("Jan Kowalski EPKK.", 1, ("Jan", "Kowalski")),
    ("Nowak Jan EPKK/EPWA", 1, ("Nowak", "Jan")),
    ("jan kowalski epkk", 1, ("jan", "kowalski")),      # znane lotnisko także małymi literami
    ("JAN NOWA", 1, ("JAN", "NOWA")),
    ("JAN KOWALSKI EPKK", 1, ("JAN", "KOWALSKI")),
    ("1234567 EPKK", 1234567, (None, None)),            # sam CID z lotniskiem macierzystym
    ("1234567 (EPKK)", 1, (None, None)),
    ("Kowalski, Jan", 1, ("Kowalski", "Jan")),          # bez przecinka w imieniu
    ("Jan EPWA", 1, ("Jan", None)),
])
def test_split_name_known_aerodromes(name, cid, expected):
    """Router podaje known(kod) z bazy punktów AD: odpada tylko końcówka, która jest lotniskiem."""
    assert flightplan.split_name(name, cid, KNOWN.__contains__) == expected
    # find_flight_plan przekazuje known do split_name
    f = feed([PILOT | {"name": name, "cid": cid}])
    d = flightplan.find_flight_plan(f, "LOT3827", KNOWN.__contains__)
    assert (d["first_name"], d["last_name"]) == expected


def test_rating_fallback():
    assert flightplan.rating(3) == {"id": 3, "short": "IR", "long": "Instrument Rating"}
    assert flightplan.rating(0, {"pilot_ratings": []})["short"] == "NEW"
    assert flightplan.rating(99) == {"id": 99, "short": None, "long": None}
    assert flightplan.rating(None) is None and flightplan.rating(True) is None


# --- godziny z API członków

def test_parse_member_hours():
    assert flightplan.parse_member_hours({"id": 1, "atc": 1234.56, "pilot": 678.94, "s1": 1.0}) == \
        {"pilot": 678.9, "atc": 1234.6}
    assert flightplan.parse_member_hours({"pilot": "12.5", "atc": 0}) == {"pilot": 12.5, "atc": 0.0}
    assert flightplan.parse_member_hours({"pilot": -1, "atc": True}) is None
    assert flightplan.parse_member_hours({"pilot": "n/a", "atc": None, "x": 5}) is None
    assert flightplan.parse_member_hours({"pilot": float("nan"), "atc": 3}) == {"pilot": None, "atc": 3.0}
    assert flightplan.parse_member_hours([1, 2]) is None and flightplan.parse_member_hours(None) is None


@pytest.fixture
def members(monkeypatch):
    """Prawdziwy fetch_text (z cache) z podstawionym serwerem: stan["mode"] = "ok" | 404 | 500 | "slow" | "text"
    | "timeout" (po `delay` s brak odpowiedzi)."""
    state = {"mode": "ok", "calls": [], "delay": 0.4}
    real = httpx.AsyncClient

    async def handler(request):
        state["calls"].append(request.url.path)
        mode = state["mode"]
        if mode in ("slow", "timeout"):
            await asyncio.sleep(state["delay"])
        if mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if isinstance(mode, int):
            return httpx.Response(mode, text="error", request=request)
        if mode == "text":
            return httpx.Response(200, text="<html>maintenance</html>", request=request)
        return httpx.Response(200, json={"id": 1234567, "atc": 50.25, "pilot": 812.4}, request=request)

    monkeypatch.setattr(http_cache.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


def test_member_hours_cached(members):
    async def run():
        a = await flightplan.member_hours(1234567)
        b = await flightplan.member_hours("1234567")
        return a, b
    a, b = asyncio.run(run())
    assert a == b == {"pilot": 812.4, "atc": 50.2}
    assert members["calls"] == ["/v2/members/1234567/stats"]            # drugi raz z cache
    assert flightplan.stats_url(42) == settings.vatsim_api_url.rstrip("/") + "/v2/members/42/stats"
    # bez CID albo z czymś dziwnym zamiast CID: bez zapytania
    assert asyncio.run(flightplan.member_hours(None)) is None and asyncio.run(flightplan.member_hours("1/../x")) is None
    assert asyncio.run(flightplan.member_hours(0)) is None and asyncio.run(flightplan.member_hours(True)) is None
    assert len(members["calls"]) == 1


@pytest.mark.parametrize("mode, pause", [(404, flightplan.HOURS_MISS_S), (500, flightplan.HOURS_FAIL_S),
                                         ("text", flightplan.HOURS_FAIL_S)])
def test_member_hours_negative_cache(members, mode, pause):
    members["mode"] = mode
    assert asyncio.run(flightplan.member_hours(1234567)) is None
    members["mode"] = "ok"
    assert asyncio.run(flightplan.member_hours(1234567)) is None       # w przerwie bez pytania
    assert len(members["calls"]) == 1
    until = flightplan._miss[1234567] - time.monotonic()
    assert pause - 5 < until <= pause
    flightplan._miss[1234567] = time.monotonic() - 1                    # po przerwie pytamy znowu
    assert asyncio.run(flightplan.member_hours(1234567)) == {"pilot": 812.4, "atc": 50.2}
    assert len(members["calls"]) == 2 and 1234567 not in flightplan._miss


def test_member_hours_bounded_wait(members):
    """Wolne API: odpowiedź bez godzin po `wait`, zapytanie kończy się w tle i następne wyszukanie ma godziny."""
    members["mode"] = "slow"

    async def run():
        t0 = time.monotonic()
        first = await flightplan.member_hours(1234567, wait=0.05)
        took = time.monotonic() - t0
        second = await flightplan.member_hours(1234567, wait=0.05)     # to samo zapytanie w toku, nie drugie
        await asyncio.sleep(members["delay"] + 0.2)
        third = await flightplan.member_hours(1234567, wait=0.05)
        return first, took, second, third
    first, took, second, third = asyncio.run(run())
    assert first is None and second is None and took < 0.3
    assert third == {"pilot": 812.4, "atc": 50.2}
    assert len(members["calls"]) == 1 and 1234567 not in flightplan._miss


def _age_cache():
    for key, (t0, text) in list(http_cache._cache.items()):
        http_cache._cache[key] = (t0 - flightplan.HOURS_TTL_S - 60, text)


def test_member_hours_stale_on_error(members):
    """Po TTL i awarii API: starsze godziny z cache zamiast błędu (fetch_text), potem krótka przerwa, w której
    godziny nadal są (z cache), a API nie jest pytane przy każdym wyszukaniu."""
    assert asyncio.run(flightplan.member_hours(1234567)) == {"pilot": 812.4, "atc": 50.2}
    _age_cache()
    members["mode"] = 503
    assert asyncio.run(flightplan.member_hours(1234567)) == {"pilot": 812.4, "atc": 50.2}
    assert len(members["calls"]) == 2
    until = flightplan._miss[1234567] - time.monotonic()
    assert flightplan.HOURS_FAIL_S - 5 < until <= flightplan.HOURS_FAIL_S
    assert asyncio.run(flightplan.member_hours(1234567)) == {"pilot": 812.4, "atc": 50.2}   # w przerwie z cache
    assert len(members["calls"]) == 2


def test_member_hours_stale_slow_failure(members):
    """Po TTL API odpowiada wolniej niż `wait` i w końcu nie odpowiada: od razu starsze godziny z cache (nie
    "brak godzin"), a po nieudanym zapytaniu w tle przerwa, więc kolejne wyszukania nie pytają API."""
    assert asyncio.run(flightplan.member_hours(1234567)) == {"pilot": 812.4, "atc": 50.2}
    _age_cache()
    members["mode"], members["delay"] = "timeout", 0.3

    async def run():
        first = await flightplan.member_hours(1234567, wait=0.05)
        pending = flightplan.hours_pending(1234567)
        await asyncio.sleep(members["delay"] + 0.2)
        later = [await flightplan.member_hours(1234567, wait=0.05) for _ in range(3)]
        return first, pending, later
    first, pending, later = asyncio.run(run())
    assert first == {"pilot": 812.4, "atc": 50.2} and pending
    assert later == [{"pilot": 812.4, "atc": 50.2}] * 3
    assert len(members["calls"]) == 2 and 1234567 in flightplan._miss       # jedno zapytanie po TTL, potem przerwa


# --- endpoint

@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


SOURCES = re.compile(r"vatsim|vIFF|api\.|https?:|member|stats|source", re.I)


def test_endpoint(client, monkeypatch):
    async def fake_feed():
        return feed([PILOT, PILOT | {"callsign": "SPKAT", "flight_plan": None, "cid": 99}],
                    [prefile("LOT45", "2026-10-28T10:00:00Z"), prefile("SPKING", "2026-10-28T10:00:00Z", name="John KING")])
    asked = []

    async def fake_hours(cid, wait=None):
        asked.append(cid)
        return {"pilot": 812.4, "atc": 0.0} if cid == 1234567 else None

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    monkeypatch.setattr(vatsim_router, "member_hours", fake_hours)
    d = client.get("/api/vatsim/flightplan/lot3827").json()
    assert d["callsign"] == "LOT3827" and d["status"] == "online" and d["pid"] == 1234567
    assert d["hours"] == {"pilot": 812.4, "atc": 0.0} and d["hours_error"] is None
    d = client.get("/api/vatsim/flightplan/LOT45").json()
    assert d["status"] == "prefiled" and d["hours"] is None and d["hours_error"] == "Hours unavailable"
    assert d["hours_pending"] is False
    assert not SOURCES.search(d["hours_error"])
    d = client.get("/api/vatsim/flightplan/SPKAT").json()
    assert d["flight_plan"] is None and d["status"] == "online"
    assert (d["first_name"], d["last_name"]) == ("Jan", "Kowalski")      # EPKK z bazy lotnisk odpada
    assert asked == [1234567, 7654321, 99]                     # jedno zapytanie o godziny na jedno wyszukanie
    d = client.get("/api/vatsim/flightplan/SPKING").json()
    assert (d["first_name"], d["last_name"]) == ("John", "KING")         # KING to nie lotnisko
    asked.pop()
    r = client.get("/api/vatsim/flightplan/XYZ123")
    assert r.status_code == 404 and r.json()["detail"] == "No flight plan for XYZ123"
    for bad in ("A", "LOT-1", "LOT_1", "ABCDEFGHIJKLM", "%C5%81OT1"):
        r = client.get(f"/api/vatsim/flightplan/{bad}")
        assert r.status_code == 400 and r.json()["detail"] == "Callsign must be 2–12 letters or digits", bad
    assert len(asked) == 3


def test_endpoint_feed_down(client, monkeypatch):
    async def down():
        raise UpstreamError("data.vatsim.net: timeout")

    monkeypatch.setattr(vatsim_router, "get_feed", down)
    r = client.get("/api/vatsim/flightplan/LOT3827")
    assert r.status_code == 502 and r.json()["detail"] == "Network data unavailable"
    assert not SOURCES.search(r.json()["detail"])


def test_endpoint_slow_member_api(client, monkeypatch, members):
    """Wolne API członków nie opóźnia planu lotu: hours null, hours_pending bez komunikatu o błędzie, plan jest."""
    async def fake_feed():
        return feed([PILOT])

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    monkeypatch.setattr(flightplan, "HOURS_WAIT_S", 0.1)
    members["mode"], members["delay"] = "slow", 0.5
    t0 = time.monotonic()
    r = client.get("/api/vatsim/flightplan/LOT3827")
    took = time.monotonic() - t0
    assert r.status_code == 200 and took < 0.45
    d = r.json()
    assert d["hours"] is None and d["flight_plan"]["route"] == "OLILA L621 RILAB"
    # zapytanie trwa: FLIGHT PLAN zapyta wcześniej; bez "Hours unavailable", godziny są dopiero w drodze
    assert d["hours_pending"] is True and d["hours_error"] is None
    time.sleep(0.7)                                             # zapytanie kończy się w tle (pętla TestClient)
    d = client.get("/api/vatsim/flightplan/LOT3827").json()
    assert d["hours"] == {"pilot": 812.4, "atc": 50.2} and d["hours_error"] is None and d["hours_pending"] is False
    assert len(members["calls"]) == 1
    assert not SOURCES.search(json.dumps({k: v for k, v in d.items() if k not in ("name", "flight_plan")}))


def test_names_not_logged(client, monkeypatch, members, caplog):
    async def fake_feed():
        return feed([PILOT])

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    members["mode"] = 500
    with caplog.at_level("DEBUG"):
        d = client.get("/api/vatsim/flightplan/LOT3827").json()
    assert d["hours_error"] == "Hours unavailable" and d["hours_pending"] is False
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("polids"))
    assert "member stats: HTTP 500" in ours and "1234567" not in ours
    assert "Kowalski" not in caplog.text and "Jan " not in caplog.text


# --- regulacje sektorów: wspólna reguła i flaga restricted (FMP, RADIO)

NOW = datetime(2026, 10, 28, 15, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("start, end, at, active", [
    ("1500", "1700", "1530", True), ("1500", "1700", "1700", True), ("1500", "1700", "1701", False),
    ("2200", "0200", "2330", True), ("2200", "0200", "0130", True), ("2200", "0200", "1530", False),
    ("", "1700", "1530", False), (None, None, "1530", False),
])
def test_restriction_active(start, end, at, active):
    now = NOW.replace(hour=int(at[:2]), minute=int(at[2:]))
    assert viff.restriction_active({"start": start, "end": end}, now) is active
    assert viff.restriction_active("x", now) is False


def test_sectors_restricted_flag(monkeypatch):
    tvs = [{"id": "EP-BH", "status": 1, "entries": 30, "occupancy": 12,
            "restrictions": [{"start": "1500", "end": "1600", "value": 20, "type": "ENR-ENTRIES"}]},
           {"id": "EP-WATMA", "status": 0, "entries": 999, "occupancy": 20,
            "restrictions": [{"start": "1800", "end": "2000", "value": 15, "type": "ENR-OCCUPANCY"}]},
           {"id": "EP-KKTMA", "status": 0, "entries": 30, "occupancy": 12, "restrictions": "?"}]

    async def fake_get(path, params=None, ttl=None):
        return {"/etfms/trafficVolumes": tvs, "/etfms/airspaces": {}, "/etfms/scenarios": []}[path]

    monkeypatch.setattr(viff, "_get", fake_get)
    d = asyncio.run(viff.sectors("EP", NOW))
    by_id = {s["id"]: s for s in d["sectors"]}
    assert [s["id"] for s in d["sectors"]] == ["EP-BH", "EP-KKTMA", "EP-WATMA"]     # kolejność bez zmian
    assert by_id["EP-BH"]["restricted"] is True and by_id["EP-WATMA"]["restricted"] is False
    assert by_id["EP-KKTMA"]["restricted"] is False
    assert by_id["EP-BH"]["restrictions"] == tvs[0]["restrictions"]                 # surowa lista zostaje
    # wartości regulacji obowiązujących teraz (FMP liczy z nich przepustowość); WATMA: regulacja dopiero o 18
    assert by_id["EP-BH"]["regulated"] == {"entries": 20, "occupancy": None}
    assert by_id["EP-WATMA"]["regulated"] == by_id["EP-KKTMA"]["regulated"] == {"entries": None, "occupancy": None}


def test_regulated_caps():
    rs = [{"type": "ENR-ENTRIES", "value": 30, "start": "1500", "end": "1700"},
          {"type": "ENR-ENTRIES", "value": "24", "start": "1400", "end": "1600"},
          {"type": "ENR-OCCUPANCY", "value": 12, "start": "1500", "end": "1600"},
          {"type": "ENR-OCCUPANCY", "value": 5, "start": "1800", "end": "1900"},      # jeszcze nie obowiązuje
          {"type": "ENR-ENTRIES", "value": 0, "start": "1500", "end": "1600"},        # bez sensownej wartości
          {"type": "AD-DEP", "value": 3, "start": "1500", "end": "1600"}, "x", None]
    assert viff.regulated_caps(rs, NOW) == {"entries": 24, "occupancy": 12}
    assert viff.regulated_caps("?", NOW) == viff.regulated_caps([], NOW) == {"entries": None, "occupancy": None}
