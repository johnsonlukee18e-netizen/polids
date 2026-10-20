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

def test_tl_from_qnh_table():
    """Zasada (Marek, 08.10.2026): 995 hPa i mniej na którymkolwiek lotnisku → FL090, inaczej FL080. Nic więcej."""
    assert tl.from_qnh(1013)["fl"] == 80 and tl.from_qnh(996)["fl"] == 80 and tl.from_qnh(995.5)["fl"] == 80
    assert tl.from_qnh(995)["fl"] == 90 and tl.from_qnh(994)["fl"] == 90
    # także przy skrajnie niskim ciśnieniu zostaje FL090 (bez podnoszenia poziomu)
    assert tl.from_qnh(950)["fl"] == 90 and tl.from_qnh(930)["fl"] == 90
    assert tl.from_qnh(None)["fl"] is None and "no QNH" in tl.from_qnh(None)["rule"]
    assert "FL090" in tl.from_qnh(995)["rule"] and "FL080" in tl.from_qnh(1013)["rule"]
    assert (tl.fl_text(80), tl.fl_text(90), tl.fl_text(None)) == ("FL080", "FL090", "–")


def test_tl_fir_level():
    qnhs = {"EPWA": 1009, "EPKK": 995, "EPGD": 1012, "EPRZ": 994, "EPSC": None}
    fir = tl.fir_level(qnhs)
    assert (fir["fl"], fir["text"], fir["qnh_min"], fir["qnh_icao"]) == (90, "FL090", 994, "EPRZ")
    assert fir["low"] == ["EPKK", "EPRZ"] and fir["stations"] == 4 and fir["missing"] == ["EPSC"]
    assert fir["ta_ft"] == 6500 and "source" not in fir and "source_url" not in fir
    ok = tl.fir_level({"EPWA": 1009, "EPKK": 996})
    assert (ok["fl"], ok["text"], ok["low"], ok["missing"], ok["uncertain"]) == (80, "FL080", [], [], False)
    assert (ok["threshold_hpa"], ok["normal"], ok["raised"]) == (995, "FL080", "FL090")
    # FL080 przy brakującym QNH nie jest pewne: opis mówi, ilu lotnisk brakuje
    part = tl.fir_level({"EPWA": 1009, "EPKK": None, "EPRZ": None})
    assert part["fl"] == 80 and part["uncertain"] and part["missing"] == ["EPKK", "EPRZ"]
    assert "1 of 3" in part["rule"] and "EPKK, EPRZ" in part["rule"]
    # FL090 jest pewne bez względu na brakujące QNH
    assert tl.fir_level({"EPWA": 990, "EPKK": None})["uncertain"] is False
    # równe minimum: wybór stały (alfabetycznie), żeby opis nie skakał między odświeżeniami
    assert tl.fir_level({"EPWA": 1001, "EPKK": 1001})["qnh_icao"] == "EPKK"
    none = tl.fir_level({"EPWA": None})
    assert none["fl"] is None and none["text"] == "–" and none["qnh_icao"] is None and none["missing"] == ["EPWA"]
    # nie ma już osobnego TL dla lotnisk ani poziomu z ATIS
    assert not hasattr(tl, "levels") and not hasattr(tl, "from_atis")


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
    assert m["type_label"] == "minimum departure interval" and m["value_text"] == "every 3 min"
    assert m["adep"] == ["EPWA", "EPMO"] and m["ades"] == ["EGLL"] and m["levels"] == ["below level 245"]
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
    assert out["source"] == "vIFF" and out["error"] is None  # 0.12.6: dane z zapasu bez dopisku, skąd są
    assert m["value"] == 180 and m["value_text"] == "every 3 min" and m["state"] == "active"
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
    # zegar stały: dane testowe (NOTAM-y, środki ECFMP) mają daty z 08.10.2026, a router woła overview() bez now
    real = overview.overview
    monkeypatch_module.setattr(overview, "overview",
                               lambda db, position=None, now=None, **kw: real(db, position, now or NOW, **kw))
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
    assert (d["tl"]["fl"], d["tl"]["text"], d["tl"]["ta_ft"]) == (80, "FL080", 6500)
    wa = next(a for a in d["aerodromes"] if a["icao"] == "EPWA")
    assert wa["lvp"]["state"] == "LVP" and wa["parsed"]["qnh"] == 1009
    # jeden TL dla kraju: lotniska nie mają własnego
    assert all("tl" not in a for a in d["aerodromes"])
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
    assert d["tl"]["stations"] + len(d["tl"]["missing"]) == len(overview.AERODROMES) and d["tl"]["stations"] == 2
    # filtr bez METAR-ów (EPKK, EPKT, EPRZ): poziom przejściowy i tak z QNH EPWA/EPMO spoza filtra
    kk = client.get("/api/overview?position=EPKK_APP").json()
    assert kk["airports"] == ["EPKK", "EPKT", "EPRZ"]
    assert (kk["tl"]["fl"], kk["tl"]["qnh_icao"], kk["tl"]["stations"]) == (80, "EPWA", 2)
    # wieża: zamiast filtra podpowiedź skoku do PRZEGLĄDU lotniska
    twr = client.get("/api/overview?position=EPKK_TWR").json()
    assert twr["position"]["goto"] == "EPKK" and twr["airports"] == ["EPKK"]
    # nieznane stanowisko: pokazujemy całe FIR zamiast błędu
    other = client.get("/api/overview?position=EPXX_APP").json()
    assert other["airports"] == overview.AERODROMES and other["position"]["known"] is False
    assert client.get("/api/overview?position=zły znak").status_code == 400


def test_overview_tl_niskie_qnh_poza_filtrem(client, monkeypatch):
    """QNH 995 hPa na jednym lotnisku (EPRZ, poza filtrem EPWA_APP) daje FL090 w całym kraju, także w widoku EPWA APP."""
    async def metars(icaos):
        low = {**METARS, "EPRZ": "EPRZ 081530Z 24008KT 9999 FEW030 12/05 Q0995"}
        return {i: low[i] for i in icaos if i in low}

    monkeypatch.setattr(overview, "get_metars", metars)
    d = client.get("/api/overview?position=EPWA_APP").json()
    assert "EPRZ" not in d["airports"]
    assert (d["tl"]["fl"], d["tl"]["text"], d["tl"]["qnh_icao"], d["tl"]["low"]) == (90, "FL090", "EPRZ", ["EPRZ"])
    assert d["tl"]["stations"] == 3 and "995" in d["tl"]["rule"]


def test_overview_awaria_zrodel(client, monkeypatch):
    """Awaria vIFF, ECFMP i METAR-u nie psuje reszty: każdy panel ma swój komunikat (bez nazwy źródła danych)."""
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
    assert d["wx_error"] == "METAR unavailable" and d["monitor_error"] == "Data unavailable"
    assert d["flow"]["error"] == "Flow measures unavailable" and d["flow"]["measures"] == []
    assert d["flow"]["viff_error"] == "Sector regulations unavailable"
    # komunikaty bez adresów serwerów i nazw dostawców
    errs = " ".join(str(d[k]) for k in ("wx_error", "monitor_error")) + d["flow"]["error"] + d["flow"]["viff_error"]
    assert not any(x in errs for x in ("vIFF", "ECFMP", "viffsys", "timeout", "http"))
    # bez METAR-ów nie ma poziomu przejściowego (ATIS go nie zastępuje)
    assert d["tl"]["fl"] is None and "no QNH" in d["tl"]["rule"] and d["tl"]["text"] == "–"
    # NOTAM-y i ATIS działają dalej
    wa = next(a for a in d["aerodromes"] if a["icao"] == "EPWA")
    assert wa["atis"]["letter"] == "K"
    assert [n["id"] for n in d["notams"]] == ["A1234/26"]


def test_overview_awaria_notam_vatsim_taf(client, monkeypatch):
    """Awaria serwera NOTAM, data feedu VATSIM i TAF-ów: odpowiedź 200, komunikaty bez nazwy źródła, jeden błąd NOTAM
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
    assert d["notams"] == [] and d["notam_error"] == "NOTAMs unavailable: EPLL, EPMO, EPRA, EPWA"
    assert d["network_error"] == "Network data unavailable" and d["wx_error"] == "TAF unavailable"
    wa = next(a for a in d["aerodromes"] if a["icao"] == "EPWA")
    assert wa["atis"] is None and wa["metar"] and wa["taf"] is None and d["tl"]["fl"] == 80


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


# --- pas w użyciu i MINE / ALL (0.12.6) ---------------------------------------------------------------------------

def test_covered_by_pierwszy_online_od_app():
    """Lotnisko jest moje, gdy w kolejności przejmowania jestem pierwszy online albo nikt inny z niej nie jest online."""
    wa = [["EPWA_APP", "EPWA_N_APP", "EPWW_C_CTR", "EPWW_S_CTR", "EPWW_ALL_CTR"]]
    assert overview.covered_by(wa, "EPWW_ALL_CTR", set()) is None
    assert overview.covered_by(wa, "EPWW_ALL_CTR", {"EPWW_S_CTR"}) == "EPWW_S_CTR"
    assert overview.covered_by(wa, "EPWW_ALL_CTR", {"EPWW_S_CTR", "EPWA_APP"}) == "EPWA_APP"
    # stanowisko dalej w kolejności niż ja nie zabiera lotniska
    assert overview.covered_by(wa, "EPWW_C_CTR", {"EPWW_S_CTR", "EPWW_ALL_CTR"}) is None
    # mnie nie ma w kolejności: lotnisko obsługuje każdy, kto z niej jest online
    assert overview.covered_by(wa, "EPPO_S_APP", {"EPWW_ALL_CTR"}) == "EPWW_ALL_CTR"
    assert overview.covered_by(wa, "EPPO_S_APP", {"EPKK_APP"}) is None
    # kilka kolejności (EPKK_CTR07 / EPKK_CTR25): wystarczy, że w jednej jestem pierwszy
    kk = [["EPKK_APP", "EPWW_J_CTR"], ["EPKK_E_APP", "EPKK_APP", "EPWW_J_CTR"]]
    assert overview.covered_by(kk, "EPKK_E_APP", {"EPKK_APP"}) is None
    assert overview.covered_by(kk, "EPWW_J_CTR", {"EPKK_E_APP"}) is None
    assert overview.covered_by(kk, "EPWW_J_CTR", {"EPKK_APP"}) == "EPKK_APP"
    assert overview.covered_by([], "EPWW_J_CTR", {"EPKK_APP"}) is None


def test_coverage_orders_z_pliku_ese(client):
    from backend.app.database import SessionLocal
    with SessionLocal() as db:
        orders = overview.coverage_orders(db)
        dirs = overview.directors(overview._slices(db))
    assert set(orders) == set(overview.AERODROMES)
    assert {"EPWA_F_APP", "EPKK_KK_APP"} <= dirs and not dirs & {"EPWA_APP", "EPKK_APP", "EPKK_E_APP", "EPGD_APP"}
    # od poziomu APP w górę: bez wieży, GND i DEL lotniska i bez dyrektora (EPWA_F_APP, EPKK_KK_APP)
    assert orders["EPWA"][0][:4] == ["EPWA_APP", "EPWA_N_APP", "EPWA_S_APP", "EPWW_C_CTR"]
    assert all(not cs.startswith(("EPWA_TWR", "EPWA_GND", "EPWA_DEL", "EPWA_F_")) for o in orders["EPWA"] for cs in o)
    assert len(orders["EPKK"]) == 2 and all(o[-2:] == ["EPWW_ALL_CTR", "EPWW_ALH_CTR"] for o in orders["EPKK"])
    assert not any("EPKK_KK_APP" in o for o in orders["EPKK"])
    # lotnisko bez APP: od razu sektory ACC
    assert orders["EPSC"] == [["EPWW_DBT_CTR", "EPWW_DBF_CTR", "EPWW_N_CTR", "EPWW_ALL_CTR", "EPWW_ALH_CTR"]]


def test_online_others(client):
    from backend.app.database import SessionLocal
    from backend.app.models import AtcPosition
    feed = {"controllers": [{"callsign": "EPWW_S_CTR", "frequency": "123.625", "cid": 11},
                            {"callsign": "EPWW_CTR", "frequency": "125.450", "cid": 12},       # ALL na częstotliwości
                            {"callsign": "EPWA_APP", "frequency": "128.805", "cid": 13},
                            {"callsign": "EPWA_OBS", "frequency": "199.998", "cid": 14},
                            {"callsign": "EPKK_ATIS", "frequency": "118.800", "cid": 15}],
            "atis": [{"callsign": "EPWA_ATIS", "frequency": "120.455", "cid": 16}]}
    with SessionLocal() as db:
        positions = list(db.scalars(__import__("sqlalchemy").select(AtcPosition)))
    # dopasowanie jak w EuroScope: EPWW_CTR na 125.450 to EPWW_ALL_CTR, czyli moje stanowisko
    assert overview.online_others(feed, positions, "EPWW_ALL_CTR") == {"EPWW_S_CTR", "EPWA_APP"}
    # moje połączenie (CID) się nie liczy, nawet na innym stanowisku
    assert overview.online_others(feed, positions, "EPWW_ALL_CTR", cid="11") == {"EPWA_APP"}
    assert overview.online_others({}, positions, "EPWW_ALL_CTR") == set()


def test_overview_mine_all(client, monkeypatch):
    """EPWW_ALL_CTR przy EPWW_S_CTR i EPWA_APP online: lotniska, które obsługują oni, mają covered_by (MINE je ukrywa)."""
    feed = {**FEED, "controllers": FEED["controllers"] + [
        {"callsign": "EPWW_S_CTR", "frequency": "123.625", "name": "Ola", "cid": 2}]}

    async def fake_feed():
        return feed

    monkeypatch.setattr(vatsim_api, "get_feed", fake_feed)
    d = client.get("/api/overview?position=EPWW_ALL_CTR").json()
    by = {a["icao"]: a["covered_by"] for a in d["aerodromes"]}
    assert d["airports"] == overview.AERODROMES        # serwer zwraca wszystkie, przełącznik jest we froncie
    assert {i for i, cs in by.items() if cs == "EPWA_APP"} == {"EPLL", "EPMO", "EPRA", "EPWA"}
    assert by["EPKK"] == by["EPRZ"] == by["EPLB"] == "EPWW_S_CTR"
    # S CTR nie ma w kolejności EPGD, EPSC i EPSY przed ALL: zostają moje
    assert by["EPGD"] is None and by["EPSC"] is None and by["EPSY"] is None
    # EPWA_APP widzi swoje lotniska (EPWW_S_CTR jest dalej w kolejności)
    app = client.get("/api/overview?position=EPWA_APP").json()
    assert [a["covered_by"] for a in app["aerodromes"]] == [None] * 4
    # dyrektor pracuje przy pasie razem z APP: EPWA_APP online nie zabiera mu EPWA (MINE nie jest puste)
    f = client.get("/api/overview?position=EPWA_F_APP").json()
    assert [(a["icao"], a["covered_by"]) for a in f["aerodromes"]] == [("EPWA", None)]
    # bez stanowiska i przy wieży nie liczymy
    assert all(a["covered_by"] is None for a in client.get("/api/overview").json()["aerodromes"])
    assert client.get("/api/overview?position=EPKK_TWR").json()["aerodromes"][0]["covered_by"] is None


def test_overview_mine_moj_cid(client, monkeypatch):
    """Zalogowany użytkownik online jako EPWW_S_CTR, który wybrał EPWW_ALL_CTR: jego połączenie nie zabiera lotnisk."""
    feed = {**FEED, "controllers": [{"callsign": "EPWW_S_CTR", "frequency": "123.625", "name": "Ja", "cid": 7}]}

    async def fake_feed():
        return feed

    monkeypatch.setattr(vatsim_api, "get_feed", fake_feed)
    from backend.app.database import SessionLocal
    with SessionLocal() as db:
        mine = __import__("asyncio").run(overview.overview(db, "EPWW_ALL_CTR", NOW, cid="7"))
        other = __import__("asyncio").run(overview.overview(db, "EPWW_ALL_CTR", NOW, cid="8"))
    assert all(a["covered_by"] is None for a in mine["aerodromes"])
    assert next(a for a in other["aerodromes"] if a["icao"] == "EPKK")["covered_by"] == "EPWW_S_CTR"


def test_overview_pas_w_uzyciu_jak_aerodrome(client, monkeypatch):
    """Pas w użyciu w OVERVIEW: z ATIS (litera), a bez ATIS pas preferowany – te same wartości co AERODROME › INFO."""
    from backend.app.routers import aerodromes

    async def feed():
        return FEED

    async def metars(icaos):
        return {i: METARS[i] for i in icaos if i in METARS}

    async def tafs(icaos):
        return {}

    monkeypatch.setattr(aerodromes, "get_feed", feed)
    monkeypatch.setattr(aerodromes, "get_metars", metars)
    monkeypatch.setattr(aerodromes, "get_tafs", tafs)
    d = client.get("/api/overview?position=EPWA_APP").json()
    rw = {a["icao"]: a["runway"] for a in d["aerodromes"]}
    # EPWA: ATIS K "RWY IN USE 33"
    assert (rw["EPWA"]["arr"], rw["EPWA"]["dep"], rw["EPWA"]["source"], rw["EPWA"]["letter"]) == ("33", "33", "ATIS", "K")
    # EPMO bez ATIS: pas preferowany z powodem wyboru, ten sam co w AERODROME
    assert rw["EPMO"]["source"] == "SUGGESTED" and rw["EPMO"]["letter"] is None and rw["EPMO"]["reason"]
    for icao in ("EPWA", "EPMO", "EPLL"):
        st = client.get(f"/api/aerodromes/{icao}/status").json()["runway_in_use"]
        assert (rw[icao]["arr"], rw[icao]["dep"], rw[icao]["source"]) == (st["arr"], st["dep"], st["source"]), icao
