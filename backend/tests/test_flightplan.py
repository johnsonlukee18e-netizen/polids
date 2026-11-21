"""OTHER › FLIGHT PLAN (0.13.0, issue #23): plan lotu po znaku (pilot online, potem najnowszy prefile), imię
i nazwisko z nazwy w sieci, rating, godziny pilota i ATC z API członków (cache, przerwa po 404 i po błędzie,
ograniczony czas czekania, starsze dane przy awarii) i endpoint /api/vatsim/flightplan/{callsign}.
0.14.2 (issue #35): dane okna EXTENDED LABEL: pełny znak radiowy, ruch z dwóch odczytów sieci (motion.py), punkty trasy
przed samolotem, punkt i poziom wyjścia z FIR (LOA), STAR/SID z pasem (fplabel.py); błąd części = puste pole.
Oraz wspólna reguła "regulacja obowiązuje teraz" (viff.restriction_active) i flaga restricted w sektorach (FMP)."""
import asyncio
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import settings
from backend.app.routers import vatsim as vatsim_router
from backend.app.database import SessionLocal
from backend.app.services import flightplan, fplabel, http_cache, motion, viff, weather
from backend.app.services.http_cache import UpstreamError
from backend.app.services.procedures import parse_procedures

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
def clean_hours(monkeypatch):
    """Bez godzin, odczytów ruchu i tras z poprzednich testów; METAR do pasa w oknie EXTENDED LABEL bez sieci."""
    async def no_metars(icaos):
        return {}

    monkeypatch.setattr(fplabel, "get_metars", no_metars)
    flightplan.reset_hours()
    http_cache.clear_cache()
    motion.reset()
    fplabel.reset()
    yield
    flightplan.reset_hours()
    http_cache.clear_cache()
    motion.reset()
    fplabel.reset()


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
    # 0.14.2: pełny znak radiowy z telefonii linii (baza), ruch dopiero z drugiego odczytu, dane okna EXTENDED LABEL
    assert d["telephony"] == "LOT 3827"
    assert d["position"] == {"lat": 52.1, "lon": 20.9, "altitude": 3500, "groundspeed": 210, "heading": 290, "squawk": "4521",
                             "vv_fpm": None, "track": None, "turn_rate": None}
    assert set(d["label"]) == {"route_ahead", "fir_exit", "proc", "next_freq"} and d["label"]["next_freq"] is None
    # w powietrzu do EPGD: STAR na lotnisku docelowym; do EP** bez punktu wyjścia z FIR
    assert d["label"]["proc"]["kind"] == "STAR" and d["label"]["proc"]["aerodrome"] == "EPGD" and d["label"]["fir_exit"] is None
    assert isinstance(d["label"]["route_ahead"], list)
    d = client.get("/api/vatsim/flightplan/LOT45").json()
    assert d["status"] == "prefiled" and d["hours"] is None and d["hours_error"] == "Hours unavailable"
    assert d["hours_pending"] is False
    assert not SOURCES.search(d["hours_error"])
    d = client.get("/api/vatsim/flightplan/SPKAT").json()
    assert d["flight_plan"] is None and d["status"] == "online"
    assert d["telephony"] is None and d["label"] == {"route_ahead": None, "fir_exit": None, "proc": None, "next_freq": None}
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


def test_endpoint_hours_arrive_during_label(client, monkeypatch, members):
    """Godziny nie zdążyły w HOURS_WAIT_S, ale doszły w tle, zanim policzyły się dane okna EXTENDED LABEL (wolny
    METAR): godziny z cache, bez "Hours unavailable" i bez "w drodze"."""
    async def fake_feed():
        return feed([PILOT])

    async def slow_metars(icaos):
        await asyncio.sleep(0.6)
        return {}

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    monkeypatch.setattr(fplabel, "get_metars", slow_metars)
    monkeypatch.setattr(flightplan, "HOURS_WAIT_S", 0.1)
    members["mode"], members["delay"] = "slow", 0.3
    d = client.get("/api/vatsim/flightplan/LOT3827").json()
    assert d["hours"] == {"pilot": 812.4, "atc": 50.2} and d["hours_error"] is None and d["hours_pending"] is False
    assert len(members["calls"]) == 1
    # to samo, ale API członków nie ma statystyk (404): po zapytaniu w tle cache pusty, więc "Hours unavailable"
    flightplan.reset_hours()
    http_cache.clear_cache()

    async def slow_404(request):
        await asyncio.sleep(0.3)
        return httpx.Response(404, text="error", request=request)

    real = httpx.AsyncClient
    monkeypatch.setattr(http_cache.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(slow_404), **kw))
    d = client.get("/api/vatsim/flightplan/LOT3827").json()
    assert d["hours"] is None and d["hours_error"] == "Hours unavailable" and d["hours_pending"] is False


def test_names_not_logged(client, monkeypatch, members, caplog):
    async def fake_feed():
        return feed([PILOT])

    async def metar_down(icaos):
        raise UpstreamError("metar: timeout")

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    monkeypatch.setattr(fplabel, "get_metars", metar_down)
    members["mode"] = 500
    with caplog.at_level("DEBUG"):
        d = client.get("/api/vatsim/flightplan/LOT3827").json()
    assert d["hours_error"] == "Hours unavailable" and d["hours_pending"] is False
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("polids"))
    assert "member stats: HTTP 500" in ours and "1234567" not in ours
    # 0.14.2: METAR do pasa w oknie EXTENDED LABEL zawiódł: jedna linijka z nazwą wyjątku, pas i tak (bez METAR)
    assert "FLIGHT PLAN extras: UpstreamError" in ours and d["label"]["proc"]["kind"] == "STAR"
    assert "Kowalski" not in caplog.text and "Jan " not in caplog.text


def test_label_extras_failures_are_null(client, monkeypatch, caplog):
    """Baza nawigacyjna i pas w użyciu zawodzą: plan lotu jest (200), pola okna puste, w logu bez nazwy pilota."""
    async def fake_feed():
        return feed([PILOT | {"flight_plan": {**FP, "arrival": "EGLL"}}])

    def boom(*a, **kw):
        raise RuntimeError("Jan Kowalski database is locked")

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    monkeypatch.setattr(fplabel.RouteResolver, "resolve", boom)
    monkeypatch.setattr(fplabel, "runway_now", boom)
    monkeypatch.setattr(fplabel, "get_metars", boom)
    with caplog.at_level("DEBUG"):
        r = client.get("/api/vatsim/flightplan/LOT3827")
    assert r.status_code == 200 and r.json()["flight_plan"]["route"] == "OLILA L621 RILAB"
    # z lotniska EP** za granicę w powietrzu: ani STAR, ani SID; reszta pusta przez błędy
    assert r.json()["label"] == {"route_ahead": None, "fir_exit": None, "proc": None, "next_freq": None}
    ours = [x.getMessage() for x in caplog.records if x.name.startswith("polids")]
    assert "FLIGHT PLAN extras: RuntimeError" in ours
    assert "Kowalski" not in caplog.text and "Jan " not in caplog.text and "locked" not in caplog.text
    # samolot na ziemi w EPWA: SID, ale pas w użyciu zawodzi = proc null
    async def ground_feed():
        return feed([PILOT | {"groundspeed": 0}])

    monkeypatch.setattr(vatsim_router, "get_feed", ground_feed)
    assert client.get("/api/vatsim/flightplan/LOT3827").json()["label"]["proc"] is None


# --- 0.14.2: ruch z dwóch odczytów sieci (wiersze Mode S okna EXTENDED LABEL)

def _pf(stamp, t, alt=10000, lat=52.0, lon=20.0, hdg=88, cs="LOT3827"):
    return {"general": {"update_timestamp": stamp},
            "pilots": [{"callsign": cs, "last_updated": t, "altitude": alt, "latitude": lat, "longitude": lon, "heading": hdg}]}


NONE = {"vv_fpm": None, "track": None, "turn_rate": None}


def test_motion_two_feeds():
    motion.observe(_pf("s1", "2026-10-28T11:00:00.1234567Z"))
    assert motion.motion("LOT3827") == NONE                                  # jeden odczyt: nic
    motion.observe(_pf("s2", "2026-10-28T11:00:30.1234567Z", alt=10650, lon=20.1, hdg=94))
    assert motion.motion("lot3827") == {"vv_fpm": 1300, "track": 90, "turn_rate": 0.2}
    # ten sam feed (ta sama update_timestamp) drugi raz: bez zmian, nawet z innymi danymi
    motion.observe(_pf("s2", "2026-10-28T11:01:00Z", alt=0))
    assert motion.motion("LOT3827")["vv_fpm"] == 1300
    # nowy feed, ale pilot nieodświeżony (ten sam last_updated): para odczytów zostaje
    motion.observe(_pf("s3", "2026-10-28T11:00:30.1234567Z", alt=10650, lon=20.1, hdg=94))
    assert motion.motion("LOT3827")["vv_fpm"] == 1300
    # przez północ kursu: 350 → 10 w 20 s = +1,0°/s; postój (< 0,3 NM) bez kąta drogi; zniżanie
    motion.reset()
    motion.observe(_pf("a", "2026-10-28T11:00:00Z", alt=5000, hdg=350))
    motion.observe(_pf("b", "2026-10-28T11:00:20Z", alt=4700, lon=20.001, hdg=10))
    assert motion.motion("LOT3827") == {"vv_fpm": -900, "track": None, "turn_rate": 1.0}
    motion.observe(_pf("c", "2026-10-28T11:00:40Z", alt=4700, lon=20.001, hdg=0))
    assert motion.motion("LOT3827") == {"vv_fpm": 0, "track": None, "turn_rate": -0.5}


@pytest.mark.parametrize("gap_s", [5, 151, 600])
def test_motion_outside_window(gap_s):
    motion.observe(_pf("a", "2026-10-28T11:00:00Z"))
    t = datetime(2026, 10, 28, 11, 0, 0, tzinfo=timezone.utc).timestamp() + gap_s
    motion.observe(_pf("b", datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z"), alt=12000, lon=20.5))
    assert motion.motion("LOT3827") == NONE


def test_motion_prunes_and_survives_bad_feeds():
    motion.observe(_pf("a", "2026-10-28T11:00:00Z"))
    motion.observe(_pf("b", "2026-10-28T11:00:30Z", alt=11000))
    motion.observe({"general": {"update_timestamp": "c"}, "pilots": []})      # pilot się rozłączył: wypada
    assert motion.motion("LOT3827") == NONE and "LOT3827" not in motion._cur and "LOT3827" not in motion._prev
    for bad in (None, [], {"general": None}, {"general": {"update_timestamp": "d"}, "pilots": "x"},
                {"general": {"update_timestamp": "e"}, "pilots": [None, {"callsign": "X", "last_updated": "nope"},
                                                                  {"callsign": "Y", "last_updated": "2026-10-28T11:00:00Z",
                                                                   "altitude": "high", "heading": True}]}):
        motion.observe(bad)
    assert motion.motion("Y") == NONE and motion._cur["Y"][1] is None and motion._cur["Y"][4] is None


def test_endpoint_motion(client, monkeypatch):
    """Endpoint zapamiętuje odczyt sam (feed podmieniony omija vatsim.get_feed): drugi odczyt daje ruch."""
    feeds = [feed([PILOT]), {**feed([PILOT | {"last_updated": "2026-10-28T11:00:30Z", "altitude": 4150, "longitude": 20.8,
                                             "heading": 280}]), "general": {"update_timestamp": "2026-10-28T11:00:35Z"}}]

    async def fake_feed():
        return feeds[0]

    monkeypatch.setattr(vatsim_router, "get_feed", fake_feed)
    assert client.get("/api/vatsim/flightplan/LOT3827").json()["position"]["vv_fpm"] is None
    feeds.pop(0)
    p = client.get("/api/vatsim/flightplan/LOT3827").json()["position"]
    assert (p["vv_fpm"], p["track"], p["turn_rate"]) == (1300, 270, -0.3)


# --- 0.14.2: trasa przed samolotem, wyjście z FIR, STAR/SID

class FakeResolver:
    def __init__(self, pts):
        self.pts, self.calls = pts, []

    def resolve(self, text):
        self.calls.append(text)
        return {"points": [dict(p) for p in self.pts]}


def _pt(ident, lat, lon, kind="FIX", via=None):
    return {"ident": ident, "kind": kind, "lat": lat, "lon": lon} | ({"via": via} if via else {})


ROUTE_PTS = [_pt("EPWA", 52.17, 20.97, "AD"), _pt("AAA", 52.5, 19.0), _pt("MID", 52.6, 18.0, via="L1"),
             _pt("BBB", 52.7, 17.0, via="L1"), _pt("CCC", 52.8, 16.0), _pt("EGLL", 51.47, -0.45, "AD")]


def test_route_ahead_projection():
    r = FakeResolver(ROUTE_PTS)
    geo = fplabel.route_geo(r, "EPWA", "AAA L1 BBB DCT CCC", "EGLL")
    # punkty wpisane w trasę (bez lotnisk i punktu MID dopisanego z drogi L1); punkt wyjścia z tej samej rozpiski
    assert geo["filed"] == [1, 3, 4] and r.calls == ["EPWA AAA L1 BBB DCT CCC EGLL"]
    assert geo["exit"] in (None, "AAA", "BBB", "CCC")
    assert fplabel.route_ahead(geo, 52.3, 20.0) == ["AAA", "BBB", "CCC"]     # jeszcze przed AAA
    assert fplabel.route_ahead(geo, 52.58, 18.2) == ["BBB", "CCC"]           # między AAA a BBB, przy MID
    assert fplabel.route_ahead(geo, 52.7, 16.9) == ["CCC"]                   # tuż za BBB
    assert fplabel.route_ahead(geo, 51.5, -0.3) == []                        # przy lotnisku docelowym: nic przed nim
    same = {"points": [(0, 0), (0, 1), (0, 2)], "idents": ["X", "X", "Y"], "filed": [0, 1, 2]}
    assert fplabel.route_ahead(same, 0, -1) == ["X", "Y"]
    many = {"points": [(0, i) for i in range(20)], "idents": [f"P{i}" for i in range(20)], "filed": list(range(20))}
    assert len(fplabel.route_ahead(many, 0, -1)) == fplabel.ROUTE_MAX == 12
    # do lotniska EP**: bez punktu wyjścia (Plan.build niewołany)
    r2 = FakeResolver(ROUTE_PTS[:-1] + [_pt("EPGD", 54.38, 18.47, "AD")])
    assert fplabel.route_geo(r2, "EPWA", "AAA L1 BBB DCT CCC", "EPGD")["exit"] is None and len(r2.calls) == 1


def test_route_ahead_local_flight():
    """Lot lokalny: lotnisko na końcu trasy rozpisane z innej bazy (kilka metrów dalej) nie wygrywa z początkiem trasy
    tuż po starcie."""
    r = FakeResolver([_pt("EPKK", 50.077702, 19.7848, "AD"), _pt("OFGOK", 50.168778, 19.786278),
                      _pt("EPKK", 50.077778, 19.784722, "AD")])
    geo = fplabel.route_geo(r, "EPKK", "OFGOK", "EPKK")
    assert geo["points"][0] == geo["points"][-1] and geo["filed"] == [1]
    assert fplabel.route_ahead(geo, 50.10, 19.7855) == ["OFGOK"]
    r = FakeResolver([_pt("EPMO", 52.451099, 20.6518, "AD"), _pt("MO", 52.40, 20.60), _pt("EPMO", 52.451111, 20.651944, "AD")])
    assert fplabel.route_ahead(fplabel.route_geo(r, "EPMO", "MO VFR", "EPMO"), 52.48, 20.70) == ["MO"]
    # inny lot (ADEP różne od ADES): współrzędne bez zmian
    pts = [_pt("EPKK", 50.08, 19.78, "AD"), _pt("OFGOK", 50.17, 19.79), _pt("EPWA", 52.17, 20.97, "AD")]
    assert fplabel.route_geo(FakeResolver(pts), "EPKK", "OFGOK", "EPWA")["points"][-1] == (52.17, 20.97)


def test_route_ahead_unknown_points(monkeypatch):
    """W powietrzu, ale żaden punkt trasy nie jest w bazie nawigacyjnej (albo tylko lotniska): route_ahead None (okno
    pokazuje wtedy punkty z planu), nie [] ("wszystkie za samolotem")."""
    found = {"status": "online", "flight_plan": {"departure": "EGLL", "arrival": "EPWA", "route": "SUBIX DCT CELWO DCT DOSIX",
                                                 "altitude": "37000", "rules": "I"},
             "position": {"lat": 52.3, "lon": 15.0, "groundspeed": 450}}
    for pts in ([], [_pt("EGLL", 51.47, -0.45, "AD"), _pt("EPWA", 52.17, 20.97, "AD")]):
        fplabel.reset()
        monkeypatch.setattr(fplabel.RouteResolver, "resolve", lambda self, text, pts=pts: {"points": [dict(p) for p in pts],
                                                                                           "distance_nm": 0, "warnings": []})
        with SessionLocal() as db:
            lab = asyncio.run(fplabel.extras(found, {}, db, NOW))
        assert lab["route_ahead"] is None and lab["fir_exit"] is None, pts
    assert fplabel.route_ahead({"points": [], "idents": [], "filed": []}, 52.3, 15.0) is None


def test_route_geo_cached(monkeypatch):
    made = []

    class Counting(FakeResolver):
        def __init__(self, db):
            super().__init__(ROUTE_PTS)
            made.append(self)

    monkeypatch.setattr(fplabel, "RouteResolver", Counting)
    a = fplabel._cached_geo(None, "EPWA", "AAA L1 BBB DCT CCC", "EGLL")
    b = fplabel._cached_geo(None, "EPWA", "AAA L1 BBB DCT CCC", "EGLL")
    assert a is b and len(made) == 1                                         # odświeżenie co 30 s bez bazy
    fplabel._geo[("EPWA", "AAA L1 BBB DCT CCC", "EGLL")] = (time.monotonic() - fplabel.GEO_TTL_S - 1, a)
    fplabel._cached_geo(None, "EPWA", "AAA L1 BBB DCT CCC", "EGLL")
    assert len(made) == 2


def test_route_geo_cache_threads(monkeypatch):
    """_cached_geo z kilku wątków puli naraz przy pełnym cache (usuwanie starych tras): bez błędów słownika."""
    monkeypatch.setattr(fplabel, "RouteResolver", lambda db: None)
    monkeypatch.setattr(fplabel, "route_geo", lambda r, dep, route, arr: {"points": [], "idents": [], "filed": [],
                                                                          "exit": None})
    errors = []

    def work(n):
        try:
            for i in range(1500):
                fplabel._cached_geo(None, "EPWA", f"R{n} {i}", "EGLL")
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)                     # częste przełączanie wątków: wyścig widać od razu
    try:
        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)
    assert errors == [] and len(fplabel._geo) <= fplabel.GEO_MAX


def test_loa_exit_level():
    assert fplabel.loa_exit_level("NAROX", "EPWR", "LGAV") == 280               # DEP EPWR przez NAROX
    assert fplabel.loa_exit_level("NAROX", "EPWR", "LGAV", 24000) == 240        # najwyżej RFL
    assert fplabel.loa_exit_level("NAROX", "EPKK", "LGAV") is None              # inne lotnisko odlotu
    assert fplabel.loa_exit_level("PESEL", "EPWA", "EDDB") is None              # dwa poziomy (zależnie od pasa)
    assert fplabel.loa_exit_level(None, "EPWR", "LGAV") is None and fplabel.loa_exit_level("-", "EPWR", "X") is None
    # wiersz "DEP EPRZ, ARR UKLL" (FL110) tylko dla lotu z EPRZ do UKLL i wygrywa z ogólnym "ARR UKLL" (FL160)
    assert fplabel.loa_exit_level("DIBED", "EPRZ", "UKLL") == 110
    assert fplabel.loa_exit_level("DIBED", "EPWA", "UKLL") == 160
    assert fplabel.loa_exit_level("DIBED", "EPRZ", "UKKK") is None
    loa = {"firs": {"XX": {"transfers": [
        {"dir": "out", "traffic": "ARR EDDB, EDDC", "cop": "ABCDE", "level": "\u2193 FL230-FL270"},
        {"dir": "in", "traffic": "DEP EPWA", "cop": "ABCDE", "level": "FL100"},
        {"dir": "out", "traffic": "ARR other XX", "cop": "ABCDE", "level": "FL150"},
        {"dir": "out", "traffic": "DEP EPWA", "cop": "ABCDE", "level": "agreed with EPWW"}, "x"]}, "YY": "x"}}
    assert fplabel.loa_exit_level("ABCDE", "EPKK", "EDDC", loa=loa) == 230
    # z EPWA do EDDC pasują dwa wiersze, a jeden z nich bez FL (koordynacja indywidualna): poziomu nie zgadujemy
    assert fplabel.loa_exit_level("ABCDE", "EPWA", "EDDC", loa=loa) is None
    assert fplabel.loa_exit_level("ABCDE", "EPWA", "LKPR", loa=loa) is None
    both = {"firs": {"XX": {"transfers": [
        {"dir": "out", "traffic": "ARR EDDB", "cop": "FGHIJ", "level": "FL240"},
        {"dir": "out", "traffic": "DEP EPWA", "cop": "FGHIJ", "level": "FL200"},
        {"dir": "out", "traffic": "DEP EPWA, EPMO, ARR EDDB, EDDC", "cop": "FGHIJ", "level": "FL180"},
        {"dir": "out", "traffic": "DEP EPKK, ARR EDDB", "cop": "FGHIJ", "level": "agreed with EPWW"}]}}}
    assert fplabel.loa_exit_level("FGHIJ", "EPMO", "EDDC", loa=both) == 180       # DEP i ARR przed jednostronnymi
    assert fplabel.loa_exit_level("FGHIJ", "EPWA", "EDDB", loa=both) == 180
    assert fplabel.loa_exit_level("FGHIJ", "EPWA", "EDDC", loa=both) == 180
    assert fplabel.loa_exit_level("FGHIJ", "EPWA", "LKPR", loa=both) == 200       # sam DEP
    assert fplabel.loa_exit_level("FGHIJ", "EPGD", "EDDB", loa=both) == 240       # sam ARR
    assert fplabel.loa_exit_level("FGHIJ", "EPWA", "EDDF", loa=both) == 200
    assert fplabel.loa_exit_level("FGHIJ", "EPGD", "EDDC", loa=both) is None      # wiersz z DEP i ARR wymaga obu
    # najbardziej szczegółowy wiersz bez FL: None, nie poziom z ogólniejszego "ARR EDDB"
    assert fplabel.loa_exit_level("FGHIJ", "EPKK", "EDDB", loa=both) is None
    # dwa jednostronne wiersze z różnymi poziomami (DEP EPWA FL200, ARR EDDB FL240) bez wiersza z obu: None
    two = {"firs": {"XX": {"transfers": [t for t in both["firs"]["XX"]["transfers"] if "," not in t["traffic"]]}}}
    assert fplabel.loa_exit_level("FGHIJ", "EPWA", "EDDB", loa=two) is None


PROCS = parse_procedures("\n".join([
    "SID:EPWA:29:SOXER7G:WA901 WA902 WA903 MAKUS SOXER",
    "SID:EPWA:33:SOXER5K:WA801 WA802 MAKUS SOXER",
    "STAR:EPWA:33:BIMPA6UxRNP:BIMPA KEWLU MENCI WA529",
    "STAR:EPWA:11:BIMPA7NxRNP:BIMPA KEWLU INZUB WA409",
]))
ATIS = {"callsign": "EPWA_ATIS", "frequency": "120.455", "atis_code": "K",
        "text_atis": ["WARSAW CHOPIN INFORMATION K", "LANDING RWY 33 DEPARTURE RWY 29"]}


@pytest.mark.parametrize("rules, status, dep, arr, route, gs, expected", [
    ("I", "online", "EPGD", "EPWA", "RILAB DCT BIMPA", 300, ("STAR", "BIMPA6U", "33", "EPWA")),
    ("I", "prefiled", "EGLL", "EPWA", "RUDNO BIMPA", None, ("STAR", "BIMPA6U", "33", "EPWA")),
    ("I", "online", "EGLL", "EPWA", "RUDNO BIMPA", 0, ("STAR", "BIMPA6U", "33", "EPWA")),     # z zagranicy: STAR od razu
    ("I", "prefiled", "EPWA", "EGLL", "SOXER UL29 BOKSU", None, ("SID", "SOXER7G", "29", "EPWA")),
    ("I", "online", "EPWA", "EPKK", "SOXER DCT", 5, ("SID", "SOXER7G", "29", "EPWA")),          # krajowy na ziemi: SID
    ("I", "online", "EPWA", "EPKK", "NEPOX DCT", 5, ("SID", None, "29", "EPWA")),             # pas bez procedury
    ("I", "online", "EPWA", "EGLL", "SOXER UL29", 400, None),                                # odlot już w powietrzu
    ("I", "online", "EGLL", "EDDF", "X", 400, None),
    # VFR jak na paskach AERODROME: pas, ale bez SID i STAR (także gdy trasa nazywa punkt procedury); Y = najpierw IFR
    ("V", "online", "EPWA", "EPKK", "VFR SOXER", 5, ("SID", None, "29", "EPWA")),
    ("V", "prefiled", "EPWA", "EPMO", "SOXER", None, ("SID", None, "29", "EPWA")),
    ("V", "online", "EGLL", "EPWA", "VFR BIMPA", 120, ("STAR", None, "33", "EPWA")),
    ("Y", "online", "EPWA", "EPKK", "SOXER VFR", 5, ("SID", "SOXER7G", "29", "EPWA")),
])
def test_proc_star_and_sid(monkeypatch, rules, status, dep, arr, route, gs, expected):
    seen = []

    def on_freq(conns, known):
        seen.append([c["callsign"] for c in conns])
        return [c for c in conns if c.get("frequency") != "199.998"]

    monkeypatch.setattr(fplabel, "known_stations", lambda db: [])
    monkeypatch.setattr(fplabel, "on_frequency", on_freq)
    found = {"callsign": "X1", "status": status, "flight_plan": {"departure": dep, "arrival": arr, "route": route, "rules": rules},
             "position": {"groundspeed": gs, "lat": None, "lon": None} if status == "online" else None}
    f = {"controllers": [{"callsign": "EPKK_TWR", "frequency": "118.105"}, {**ATIS, "callsign": "EPWA_X_ATIS", "frequency": "199.998",
                                                                              "text_atis": ["RWY 11"]}],
         "atis": [ATIS]}
    with SessionLocal() as db:
        lab = asyncio.run(fplabel.extras(found, f, db, NOW, PROCS))
    p = lab["proc"]
    assert (None if p is None else (p["kind"], p["name"], p["runway"], p["aerodrome"])) == expected
    if expected:
        assert seen == [["EPWA_X_ATIS", "EPWA_ATIS"]]                 # tylko stanowiska tego lotniska, przez filtr


def test_metar_slow_finishes_in_background(monkeypatch, caplog):
    """METAR wolniejszy niż METAR_WAIT_S: teraz pas bez wiatru, ale pobieranie nie jest przerywane (kończy się w tle
    i trafia do cache), więc następne odświeżenie ma pas z wiatru; odświeżenie w tym czasie czeka na to samo
    pobieranie, a przekroczenie czasu nie jest błędem w logu."""
    calls = []
    real = httpx.AsyncClient

    async def handler(request):
        calls.append(request.url.path)
        await asyncio.sleep(0.5)
        return httpx.Response(200, text="EPWA 281500Z 15015KT CAVOK 10/02 Q1020\n", request=request)

    monkeypatch.setattr(http_cache.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "metar_source", "vatsim")
    monkeypatch.setattr(fplabel, "get_metars", weather.get_metars)
    monkeypatch.setattr(fplabel, "METAR_WAIT_S", 0.05)
    found = {"status": "prefiled", "flight_plan": {"departure": "EPWA", "arrival": "EGLL", "route": "SOXER", "rules": "I"},
             "position": None}

    async def run(db):
        first = await fplabel.extras(found, {}, db, NOW)
        second = await fplabel.extras(found, {}, db, NOW)
        await asyncio.sleep(0.7)
        third = await fplabel.extras(found, {}, db, NOW)
        return [lab["proc"]["runway"] for lab in (first, second, third)]

    with SessionLocal() as db, caplog.at_level("DEBUG"):
        runways = asyncio.run(run(db))
    # bez METAR pas 29 (preferowany), z wiatrem 150/15 pas 15 (METAR z cache); jedno zapytanie do serwera
    assert runways == ["29", "29", "15"]
    assert calls == ["/EPWA"]
    assert "FLIGHT PLAN extras" not in caplog.text and not fplabel._metar_tasks


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
