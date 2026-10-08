"""AERODROME › OVERVIEW: poziom przejściowy, przypisanie lotnisk do stanowisk, ECFMP/vIFF i jedno zapytanie /api/overview.

Wszystkie źródła zewnętrzne (METAR/TAF, VATSIM, NOTAM, ECFMP, vIFF) są podstawione, żeby testy działały bez sieci."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.routers import vatsim as vatsim_api  # noqa: E402
from backend.app.services import ecfmp, overview, tl, viff  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

NOW = datetime(2026, 10, 8, 15, 30, tzinfo=timezone.utc)


# --- poziom przejściowy -----------------------------------------------------------------------------------------

def test_tl_from_atis():
    assert tl.from_atis(["WARSAW CHOPIN INFORMATION K", "TRANSITION LEVEL 80"]) == 80
    assert tl.from_atis(["RWY IN USE 22L", "TRL 65"]) == 65
    assert tl.from_atis(["TL70 QNH 1001"]) == 70
    assert tl.from_atis(["TRANSITION LEVEL FL 90"]) == 90
    assert tl.from_atis("TRANSITION LEVEL IS 100") == 100
    # ATIS bez poziomu i brak ATIS; "TL1200" z TAF-a (grupa czasu) nie jest poziomem
    assert tl.from_atis(["RWY 29 IN USE, QNH 1013"]) is None
    assert tl.from_atis(None) is None and tl.from_atis([]) is None
    assert tl.from_atis(["BECMG TL1200 27010KT"]) is None


def test_tl_from_qnh_table():
    """Zasada OM PL vACC: poniżej 995 hPa FL90, od 995 hPa FL80."""
    assert tl.from_qnh(1013)["fl"] == 80 and tl.from_qnh(995)["fl"] == 80
    assert tl.from_qnh(994)["fl"] == 90 and tl.from_qnh(980)["fl"] == 90
    assert tl.from_qnh(None)["fl"] is None
    assert not tl.from_qnh(1013)["computed"]
    # skrajnie niskie ciśnienie: FL90 nie daje już 1000 ft nad TA 6500 ft, więc podnosimy poziom
    low = tl.from_qnh(950)
    assert low["fl"] == 95 and low["computed"] and "FL95" in low["rule"]
    assert tl.altitude_ft(80, 1013.25) == pytest.approx(8000)


def test_tl_fir_and_aerodromes():
    qnhs = {"EPWA": 1009, "EPKK": 993, "EPGD": 1012, "EPSC": None}
    fir = tl.fir_level(qnhs)
    assert (fir["fl"], fir["qnh_min"], fir["qnh_icao"], fir["stations"]) == (90, 993, "EPKK", 3)
    assert fir["ta_ft"] == 6500 and "om.plvacc.pl" in fir["source_url"]
    out = tl.levels(qnhs, {"EPWA": ["TRANSITION LEVEL 80"], "EPKK": None, "EPGD": None, "EPSC": None})
    # ATIS EPWA mówi FL80, a z QNH wychodzi FL90 (gdzieś w FIR jest niskie ciśnienie): pokazujemy ATIS i oznaczamy różnicę
    assert out["aerodromes"]["EPWA"] == {"fl": 80, "source": "ATIS", "qnh": 1009, "fir_fl": 90, "differs": True}
    assert out["aerodromes"]["EPKK"]["fl"] == 90 and out["aerodromes"]["EPKK"]["source"] == "QNH"
    assert out["aerodromes"]["EPSC"]["fl"] == 90 and not out["aerodromes"]["EPSC"]["differs"]


# --- ECFMP ------------------------------------------------------------------------------------------------------

ECFMP_FIRS = [{"id": 29, "identifier": "EPWW", "name": "Warszawa"}, {"id": 19, "identifier": "ESAA", "name": "Sweden"},
              {"id": 32, "identifier": "EHAA", "name": "Amsterdam"}]
ECFMP_MEASURES = [
    {"id": 1, "ident": "EPWW10A", "reason": "Staffing", "starttime": "2026-10-08T14:30:00Z",
     "endtime": "2026-10-08T17:30:00Z", "measure": {"type": "minimum_departure_interval", "value": 180},
     "filters": [{"type": "ADEP", "value": ["EPWA", "EPMO"]}, {"type": "ADES", "value": ["EGLL"]},
                 {"type": "level_below", "value": 245}],
     "notified_flight_information_regions": [29], "withdrawn_at": None},
    {"id": 2, "ident": "ESAA07A", "reason": "Enroute separation", "starttime": "2026-10-08T16:30:00Z",
     "endtime": "2026-10-08T18:30:00Z", "measure": {"type": "ground_stop", "value": None},
     "filters": [{"type": "ADEP", "value": ["ESGG"]}, {"type": "ADES", "value": ["EHRD"]}],
     "notified_flight_information_regions": [19, 32], "withdrawn_at": None},
    {"id": 3, "ident": "EPWW09Z", "reason": "Stare", "starttime": "2026-10-08T10:00:00Z",
     "endtime": "2026-10-08T12:00:00Z", "measure": {"type": "per_hour", "value": 20}, "filters": [],
     "notified_flight_information_regions": [29], "withdrawn_at": None},
    {"id": 4, "ident": "EHAA01B", "reason": "Wycofana", "starttime": "2026-10-08T15:00:00Z",
     "endtime": "2026-10-08T19:00:00Z", "measure": {"type": "prohibit", "value": None},
     "filters": [{"type": "ADES", "value": ["EPWA"]}], "notified_flight_information_regions": [32],
     "withdrawn_at": "2026-10-08T14:00:00Z"},
]


def test_ecfmp_measure_po_polsku():
    firs = {f["id"]: f["identifier"] for f in ECFMP_FIRS}
    m = ecfmp.measure(ECFMP_MEASURES[0], firs, NOW)
    assert m["type_label"] == "minimalny odstęp między startami" and m["value_text"] == "co 3 min"
    assert m["adep"] == ["EPWA", "EPMO"] and m["ades"] == ["EGLL"] and m["levels"] == ["poniżej poziomu 245"]
    assert m["firs"] == ["EPWW"] and m["state"] == "active" and m["source"] == "ECFMP"
    assert ecfmp.measure(ECFMP_MEASURES[1], firs, NOW)["state"] == "notified"
    assert ecfmp.measure(ECFMP_MEASURES[2], firs, NOW)["state"] == "finished"
    assert ecfmp.value_text("per_hour", 20) == "20/h" and ecfmp.value_text("miles_in_trail", 15) == "15 NM"
    assert ecfmp.value_text("ground_stop", None) == ""


def test_ecfmp_relevant():
    ads = set(overview.AERODROMES)
    mk = lambda **kw: {"firs": [], "ident": "", "adep": [], "ades": [], **kw}  # noqa: E731
    assert ecfmp.relevant(mk(firs=["EPWW"]), ads)
    assert ecfmp.relevant(mk(firs=["EDGG"], ades=["EPKK"]), ads)          # regulacja niemiecka na ruch do Krakowa
    assert ecfmp.relevant(mk(ident="EPWW10A"), ads)
    assert not ecfmp.relevant(mk(firs=["ESAA", "EHAA"], adep=["ESGG"], ades=["EHRD"]), ads)


def test_ecfmp_measures_filtruje_i_sortuje(monkeypatch):
    async def fake(url, ttl, params=None, headers=None):
        return __import__("json").dumps(ECFMP_FIRS if url.endswith("flight-information-region") else ECFMP_MEASURES)

    monkeypatch.setattr(ecfmp, "fetch_text", fake)
    out = __import__("asyncio").run(ecfmp.measures(overview.AERODROMES, NOW))
    # zostają tylko restrykcje dotyczące EPWW, nie zakończone i nie wycofane; obowiązujące przed zgłoszonymi
    assert [m["ident"] for m in out["measures"]] == ["EPWW10A"] and out["source"] == "ECFMP" and out["all"] == 4


def test_ecfmp_zapas_z_viff(monkeypatch):
    """Gdy ECFMP nie odpowiada, bierzemy te same restrykcje z vIFF (/etfms/ecfmp)."""
    async def boom(url, ttl, params=None, headers=None):
        raise UpstreamError(f"{url}: timeout")

    async def viff_get(path, params=None, ttl=None):
        assert path == "/etfms/ecfmp"
        return [{"id": 1, "ident": "EPWW10A", "reason": "Staffing", "valid_time": "1430/1730", "valid_date": "08/10",
                 "type": "minimum_departure_interval", "value": 3, "ADEP": ["EPWA"], "ADES": ["EGLL"],
                 "waypoints": [], "levelRestrictions": [], "notified_firs": ["EPWW"]}]

    monkeypatch.setattr(ecfmp, "fetch_text", boom)
    monkeypatch.setattr(viff, "_get", viff_get)
    out = __import__("asyncio").run(ecfmp.measures(overview.AERODROMES, NOW))
    m = out["measures"][0]
    assert out["source"] == "vIFF" and "ECFMP niedostępny" in out["error"]
    assert m["value"] == 180 and m["value_text"] == "co 3 min" and m["state"] == "active"
    assert m["start"] == "2026-10-08T14:30:00+00:00" and m["end"] == "2026-10-08T17:30:00+00:00"


# --- drobne funkcje widoku --------------------------------------------------------------------------------------

def test_feed_info_liczy_ruch_i_skleja_atis():
    feed = {"controllers": [{"callsign": "EPWA_TWR", "frequency": "118.305", "name": "Ola", "cid": 1},
                            {"callsign": "EDDB_TWR", "frequency": "120.030", "name": "Hans", "cid": 2},
                            {"callsign": "EPWA_OBS", "frequency": "199.998", "name": "Gość", "cid": 3}],
            "atis": [{"callsign": "EPWA_A_ATIS", "atis_code": "K", "text_atis": ["ARR 33", "TRANSITION LEVEL 80"]},
                     {"callsign": "EPWA_D_ATIS", "atis_code": "L", "text_atis": ["DEP 29"]}],
            "pilots": [{"flight_plan": {"departure": "EPWA", "arrival": "EPKK"}},
                       {"flight_plan": {"departure": "EPKK", "arrival": "EPWA"}},
                       {"flight_plan": {"departure": "EPWA", "arrival": "EPWA"}},   # lokalny: tylko jako odlot
                       {"flight_plan": None}],
            "prefiles": [{"flight_plan": {"departure": "EPWA", "arrival": "EGLL"}}]}
    info = overview.feed_info(feed, ["EPWA", "EPKK"])
    assert (info["EPWA"]["departures"], info["EPWA"]["arrivals"], info["EPWA"]["prefiles"]) == (2, 1, 1)
    assert (info["EPKK"]["departures"], info["EPKK"]["arrivals"]) == (1, 1)
    assert info["EPWA"]["atis"]["letter"] == "K / L" and len(info["EPWA"]["atis"]["lines"]) == 3
    # EDDB_TWR to nie nasze lotnisko, a EPWA_OBS to obserwator, nie stanowisko ATC
    assert [c["callsign"] for c in info["EPWA"]["atc"]] == ["EPWA_TWR"]


def test_notam_aktywne_teraz():
    iso = lambda h: (NOW + timedelta(hours=h)).isoformat()  # noqa: E731
    now_n = {"start": iso(-2), "end": iso(2), "fields": {"E": "RWY 11/29 CLSD\nDUE TO WIP"}, "raw": "x"}
    assert overview.notam_active(now_n, NOW) and overview.notam_text(now_n) == "RWY 11/29 CLSD DUE TO WIP"
    assert not overview.notam_active({"start": iso(2), "end": iso(4)}, NOW)       # dopiero będzie
    assert not overview.notam_active({"start": iso(-4), "end": iso(-2)}, NOW)     # już wygasł
    assert overview.notam_active({"start": iso(-40), "end": None, "perm": True}, NOW)
    assert overview.notam_active({}, NOW)                                         # bez pól B)/C) pokazujemy
    assert overview.notam_text({"fields": {}, "raw": "A1234/26  NOTAMN\n E) coś"}) == "A1234/26 NOTAMN E) coś"


def test_regulacje_sektorow_viff():
    tvs = [{"id": "EP-WATMA", "restrictions": [{"start": "1500", "end": "1700", "value": 20, "type": "ENR-OCCUPANCY",
                                                "reason": "EP-WATMA"},
                                               {"start": "2200", "end": "0400", "value": 10, "type": "ENR-ENTRIES",
                                                "reason": "noc"}]},
            {"id": "EP-KKTMA", "restrictions": []}]
    out = overview.tv_restrictions(tvs, NOW)
    assert [(r["tv"], r["active"]) for r in out] == [("EP-WATMA", True), ("EP-WATMA", False)]
    assert out[0]["label"] == "TMA EPWA" and out[0]["value"] == 20
    # okno przez północ obowiązuje o 23:00
    assert overview.tv_restrictions(tvs, NOW.replace(hour=23))[0]["start"] == "2200"
    assert overview.tv_restrictions([], NOW) == []


def test_monitor_godziny_i_opoznienie():
    buckets = [{"hour": "15", "entriesCapacity": 34, "entriesCount": 26},
               {"hour": "16", "entriesCapacity": 34, "entriesCount": 31}]
    assert overview.monitor_hours(buckets, NOW) == {"hour": "15", "now": {"entries": 26, "cap": 34},
                                                    "next": {"entries": 31, "cap": 34}}
    assert overview.monitor_hours([], NOW)["now"] == {"entries": None, "cap": None}
    assert overview._delay("1621", "1609") == 12 and overview._delay("0010", "2350") == 20
    assert overview._delay("", "1609") is None and overview._delay(None, None) is None
    # vIFF podaje też godziny z sekundami albo jako liczbę
    assert overview._delay("162100", "160900") == 12 and overview._delay(1621, 1609) == 12
    # inny kształt danych niż lista godzin: puste wartości zamiast błędu
    assert overview.monitor_hours({"15": {}}, NOW)["now"] == {"entries": None, "cap": None}
    assert overview.monitor_hours(None, NOW)["next"] == {"entries": None, "cap": None}


# --- całe zapytanie /api/overview (z bazą zbudowaną z plików .ese) -----------------------------------------------

METARS = {"EPWA": "EPWA 081530Z 31014G26KT 0400 R29/0350N FG BKN002 11/10 Q1009 NOSIG",
          "EPMO": "EPMO 081530Z 30010KT 9999 SCT030 10/05 Q1011"}
ATIS_LINES = ["WARSAW CHOPIN INFORMATION K", "RWY IN USE 33", "TRANSITION LEVEL 80"]
FEED = {"general": {"update_timestamp": "2026-10-08T15:30:00Z"},
        "controllers": [{"callsign": "EPWA_APP", "frequency": "128.805", "name": "Jan", "cid": 1}],
        "atis": [{"callsign": "EPWA_ATIS", "frequency": "120.455", "atis_code": "K", "text_atis": ATIS_LINES}],
        "pilots": [{"flight_plan": {"departure": "EPWA", "arrival": "EPGD"}}], "prefiles": []}
NOTAMS = {"EPWA": [{"id": "A1234/26", "raw": "(A1234/26 ...)", "fields": {"E": "RWY 11/29 CLSD"},
                    "start": "2026-10-01T00:00:00+00:00", "end": None, "perm": True, "est": False, "schedule": None},
                   {"id": "A9999/26", "raw": "(A9999/26 ...)", "fields": {"E": "STARY"},
                    "start": "2020-01-01T00:00:00+00:00", "end": "2020-01-02T00:00:00+00:00", "perm": False,
                    "est": False, "schedule": None}]}
VIFF_AIRPORTS = {"EPWA": [{"hour": f"{h:02d}", "entriesCapacity": 34, "entriesCount": 26 if h else 0,
                           "peakCapacity": -1, "peakCount": -1, "active": True, "flights": []} for h in range(24)]}
VIFF_CAD = [{"icao": "EPWA", "rate": 34, "taxiTime": 15, "isCdm": True, "config": "", "atis_config": "11",
             "restrictions": []}]
VIFF_RESTRICTED = [{"callsign": "WZZ1AB", "departure": "EPWA", "arrival": "EGGW", "ctot": "1621", "etot": "1609",
                    "atot": "", "tto": "1634", "mostPenalisingRegulation": "EDGGB10M", "isCdm": True}]


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    async def metars(icaos):
        return {i: METARS[i] for i in icaos if i in METARS}

    async def tafs(icaos):
        return {i: f"TAF {i} 081400Z 0815/0915 27010KT CAVOK" for i in icaos if i in METARS}

    async def feed():
        return FEED

    async def notams(icao):
        return {"icao": icao, "source": "demo", "notams": NOTAMS.get(icao, []), "other": 0}

    async def viff_get(path, params=None, ttl=None):
        return {"/etfms/airports": VIFF_AIRPORTS, "/etfms/getCadAirports": VIFF_CAD,
                "/etfms/restricted": VIFF_RESTRICTED, "/etfms/trafficVolumes": []}[path]

    async def ecfmp_fetch(url, ttl, params=None, headers=None):
        return __import__("json").dumps(ECFMP_FIRS if url.endswith("flight-information-region") else ECFMP_MEASURES)

    monkeypatch_module.setattr(overview, "get_metars", metars)
    monkeypatch_module.setattr(overview, "get_tafs", tafs)
    monkeypatch_module.setattr(overview, "get_notams", notams)
    monkeypatch_module.setattr(vatsim_api, "get_feed", feed)
    monkeypatch_module.setattr(viff, "_get", viff_get)
    monkeypatch_module.setattr(ecfmp, "fetch_text", ecfmp_fetch)
    with TestClient(main.app) as c:
        yield c


def test_positions_grupy_i_lotniska(client):
    data = client.get("/api/overview/positions").json()
    groups = {g["kind"]: {p["callsign"]: p for p in g["positions"]} for g in data["groups"]}
    # przykład Marka: EPWA APP obejmuje EPWA, EPMO, EPLL i EPRA (z kolejności przejmowania w pliku .ese)
    assert groups["APP"]["EPWA_APP"]["airports"] == ["EPLL", "EPMO", "EPRA", "EPWA"]
    assert groups["APP"]["EPKK_APP"]["airports"] == ["EPKK", "EPKT", "EPRZ"]
    assert groups["APP"]["EPGD_APP"]["airports"] == ["EPBY", "EPGD"]
    assert groups["ACC"]["EPWW_C_CTR"]["airports"] == ["EPLL", "EPMO", "EPRA", "EPWA"]
    assert len(groups["ACC"]["EPWW_ALH_CTR"]["airports"]) == len(overview.AERODROMES)
    # wieże: po jednej na lotnisko, z przeskokiem do PRZEGLĄDU
    assert groups["TWR"]["EPKK_TWR"]["goto"] == "EPKK" and len(groups["TWR"]) == len(overview.AERODROMES)
    # FIS (informacja powietrzna) nie zawęża lotnisk, więc nie ma go w filtrze
    assert "EPWA_I_APP" not in groups["APP"] and "EPWW_I_CTR" not in groups["ACC"]
    assert [a["icao"] for a in data["aerodromes"]] == overview.AERODROMES


def test_overview_bez_filtra(client):
    d = client.get("/api/overview").json()
    assert d["airports"] == overview.AERODROMES and d["position"] is None
    assert d["tl"]["fir"]["fl"] == 80 and d["tl"]["fir"]["ta_ft"] == 6500
    wa = next(a for a in d["aerodromes"] if a["icao"] == "EPWA")
    assert wa["lvp"]["state"] == "LVP" and wa["parsed"]["qnh"] == 1009
    assert wa["tl"] == {"fl": 80, "source": "ATIS", "qnh": 1009, "fir_fl": 80, "differs": False}
    assert wa["atis"]["letter"] == "K" and wa["atis"]["lines"] == ATIS_LINES
    assert wa["traffic"]["departures"] == 1 and wa["monitor"]["cdm"] and wa["monitor"]["rate"] == 34
    assert wa["monitor"]["regulated"][0]["delay"] == 12 and wa["monitor"]["avg_delay"] == 12
    # lotnisko bez METAR-u nie psuje widoku: zostaje w tabeli z pustymi danymi
    assert next(a for a in d["aerodromes"] if a["icao"] == "EPZG")["parsed"] is None
    assert [n["id"] for n in d["notams"]] == ["A1234/26"]     # wygasły NOTAM odpada
    assert [m["ident"] for m in d["flow"]["measures"]] == ["EPWW10A"]
    assert d["wx_error"] is None and d["network_error"] is None and d["notam_error"] is None


def test_overview_filtr_stanowiska(client):
    d = client.get("/api/overview?position=EPWA_APP").json()
    assert d["airports"] == ["EPLL", "EPMO", "EPRA", "EPWA"] and d["position"]["kind"] == "APP"
    assert [a["icao"] for a in d["aerodromes"]] == ["EPLL", "EPMO", "EPRA", "EPWA"]
    # poziom przejściowy liczymy z QNH wszystkich lotnisk FIR-u, nie tylko pokazanych
    assert d["tl"]["fir"]["stations"] == 2 and set(d["tl"]["aerodromes"]) == set(overview.AERODROMES)
    # filtr bez METAR-ów (EPKK, EPKT, EPRZ): poziom przejściowy i tak z QNH EPWA/EPMO spoza filtra
    kk = client.get("/api/overview?position=EPKK_APP").json()
    assert kk["airports"] == ["EPKK", "EPKT", "EPRZ"]
    assert (kk["tl"]["fir"]["fl"], kk["tl"]["fir"]["qnh_icao"], kk["tl"]["fir"]["stations"]) == (80, "EPWA", 2)
    # wieża: zamiast filtra podpowiedź skoku do PRZEGLĄDU lotniska
    twr = client.get("/api/overview?position=EPKK_TWR").json()
    assert twr["position"]["goto"] == "EPKK" and twr["airports"] == ["EPKK"]
    # nieznane stanowisko: pokazujemy całe FIR zamiast błędu
    other = client.get("/api/overview?position=EPXX_APP").json()
    assert other["airports"] == overview.AERODROMES and other["position"]["known"] is False
    assert client.get("/api/overview?position=zły znak").status_code == 400


def test_overview_awaria_zrodel(client, monkeypatch):
    """Awaria vIFF, ECFMP i METAR-u nie psuje reszty: każdy panel ma swój komunikat po polsku."""
    async def boom_wx(icaos):
        raise UpstreamError("metar.vatsim.net: timeout")

    async def boom_viff(path, params=None, ttl=None):
        raise UpstreamError("api.viffsys.com: timeout")

    async def boom_ecfmp(url, ttl, params=None, headers=None):
        raise UpstreamError(f"{url}: timeout")

    monkeypatch.setattr(overview, "get_metars", boom_wx)
    monkeypatch.setattr(viff, "_get", boom_viff)
    monkeypatch.setattr(ecfmp, "fetch_text", boom_ecfmp)
    d = client.get("/api/overview?position=EPWA_APP").json()
    assert "METAR" in d["wx_error"] and "vIFF" in d["monitor_error"]
    assert "ECFMP niedostępny" in d["flow"]["error"] and d["flow"]["measures"] == []
    assert "vIFF" in d["flow"]["viff_error"]
    assert d["tl"]["fir"]["fl"] is None and "brak QNH" in d["tl"]["fir"]["rule"]
    # NOTAM-y i ATIS (poziom przejściowy z ATIS) działają dalej
    wa = next(a for a in d["aerodromes"] if a["icao"] == "EPWA")
    assert wa["tl"]["source"] == "ATIS" and wa["tl"]["fl"] == 80
    assert [n["id"] for n in d["notams"]] == ["A1234/26"]


def test_overview_awaria_notam_vatsim_taf(client, monkeypatch):
    """Awaria serwera NOTAM, data feedu VATSIM i TAF-ów: odpowiedź 200, komunikaty po polsku, jeden błąd NOTAM
    dla wszystkich lotnisk zamiast osobnej linii na każde."""
    async def boom_notam(icao):
        raise UpstreamError(f"https://cv.plvacc.pl/notam/get-icao-format?icao={icao}&read=true: timeout")

    async def boom_feed():
        raise UpstreamError("https://data.vatsim.net/v3/vatsim-data.json: timeout")

    async def bad_taf(icaos):
        raise KeyError("icaoId")          # AWC zwróciło JSON w innym kształcie

    monkeypatch.setattr(overview, "get_notams", boom_notam)
    monkeypatch.setattr(vatsim_api, "get_feed", boom_feed)
    monkeypatch.setattr(overview, "get_tafs", bad_taf)
    r = client.get("/api/overview?position=EPWA_APP")
    assert r.status_code == 200
    d = r.json()
    assert d["notams"] == [] and d["notam_error"] == "Serwer NOTAM: EPLL, EPMO, EPRA, EPWA: timeout"
    assert "VATSIM" in d["network_error"] and "TAF" in d["wx_error"]
    wa = next(a for a in d["aerodromes"] if a["icao"] == "EPWA")
    assert wa["atis"] is None and wa["tl"]["source"] == "QNH" and wa["metar"] and wa["taf"] is None


def test_overview_viff_inny_ksztalt(client, monkeypatch):
    """vIFF zwraca dane w nieoczekiwanym kształcie (lista zamiast słownika, godziny jako liczby): bez błędu 500."""
    async def odd_viff(path, params=None, ttl=None):
        return {"/etfms/airports": [{"EPWA": 1}], "/etfms/getCadAirports": {"error": "x"},
                "/etfms/restricted": [{"callsign": "LOT1", "departure": "EPWA", "arrival": "EPGD", "ctot": 1621,
                                       "etot": 1609}, "śmieci"],
                "/etfms/trafficVolumes": {"error": "x"}}[path]

    monkeypatch.setattr(viff, "_get", odd_viff)
    r = client.get("/api/overview?position=EPWA_APP")
    assert r.status_code == 200
    wa = next(a for a in r.json()["aerodromes"] if a["icao"] == "EPWA")["monitor"]
    assert wa["now"] == {"entries": None, "cap": None} and wa["rate"] is None
    assert wa["regulated"][0]["ctot"] == "1621" and wa["regulated"][0]["delay"] == 12
