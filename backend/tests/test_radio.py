import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.routers import vatsim as vatsim_api  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402
from backend.app.services.radio import merge_positions, position_range, sector_group, sector_kind  # noqa: E402
from backend.app.services.vatsim import fir_boundaries  # noqa: E402

FEED = {"general": {"update_timestamp": "2026-10-06T12:00:00Z"}, "pilots": [], "atis": [],
        "controllers": [
            {"callsign": "EDWW_EMS_CTR", "frequency": "125.025", "name": "Tylko VACS", "cid": 1},  # brak w .ese
            {"callsign": "EDDB_TWR", "frequency": "120.030", "name": "Jak w EuroScope", "cid": 2},  # → EDDB_N_TWR
            {"callsign": "EPWA_APP", "frequency": "128.805", "name": "Jan", "cid": 3},
            {"callsign": "EPKK_OBS", "frequency": "199.998", "name": "Obserwator", "cid": 4},
            {"callsign": "KZNY_CTR", "frequency": "125.000", "name": "Daleko", "cid": 5}]}


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    async def feed():
        return FEED

    async def bookings():
        return [{"callsign": "EDWW_EMS_CTR", "cid": 1, "type": "booking", "start": "2000-01-01 10:00:00",
                 "end": "2100-01-01 12:00:00"},
                {"callsign": "KZNY_CTR", "cid": 5, "start": "2000-01-01 10:00:00", "end": "2100-01-01 12:00:00"}]

    monkeypatch_module.setattr(vatsim_api, "get_feed", feed)
    monkeypatch_module.setattr(vatsim_api, "get_bookings", bookings)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_merge_positions_adds_vacs_only():
    ese = [{"callsign": "EDWW_FLG_CTR", "name": "Bremen Radar", "frequency": "136.450", "position_id": "EDWF",
            "prefix": "EDWW"}]
    vacs = [{"id": "EDWW_FLG_CTR", "fir_dir": "EDWW", "prefixes": ["EDWW"], "frequency": "136.450",
             "facility_type": "CTR"},
            {"id": "EDDH_TWR", "fir_dir": "EDWW", "prefixes": ["EDDH"], "frequency": "126.855", "facility_type": "TWR"},
            {"id": "EDWW_FMP", "fir_dir": "EDWW", "prefixes": ["EDWW"], "frequency": "199.998", "facility_type": "FMP"}]
    out = {p["callsign"]: p for p in merge_positions(ese, vacs)}
    assert set(out) == {"EDWW_FLG_CTR", "EDDH_TWR"}  # FMP pominięte
    assert out["EDWW_FLG_CTR"]["in_ese"] and out["EDWW_FLG_CTR"]["in_vacs"] and out["EDWW_FLG_CTR"]["name"]
    assert out["EDDH_TWR"] == {**out["EDDH_TWR"], "name": None, "in_ese": False, "fir": "EDWW", "fir_name": "FIR Bremen",
                               "prefix": "EDDH", "facility": "TWR", "position_id": None}


def test_position_range():
    firs = fir_boundaries()
    assert position_range("EDWW_FLG_CTR", firs) == {"kind": "vatspy", "ids": ["EDWW-FLG"], "exact": True}
    assert position_range("ESMM_7_CTR", firs)["ids"] == ["ESMM-7"]
    assert position_range("EYVL_E_CTR", firs)["ids"] == ["EYVL-E"]
    # bez własnego sektora w VATSpy: cały FIR jako przybliżenie
    assert position_range("ESMM_6_CTR", firs) == {"kind": "vatspy", "ids": ["ESMM"], "exact": False}
    assert position_range("LKAA_CTR", firs) == {"kind": "vatspy", "ids": ["LKAA"], "exact": True}
    assert position_range("RU-NWC_FSS", firs)["ids"] == ["ULLL", "UMKK"]  # UIR → jego FIR-y
    # bez granicy w VATSpy: prefiks z vacs-data albo FIR-y z NB_ALIAS (zawsze przybliżenie)
    assert position_range("EDYY_BB_CTR", firs) == {"kind": "vatspy", "ids": ["EDWW"], "exact": False}
    assert position_range("EDUU_ALP_CTR", firs, prefix="EDUU") == {"kind": "vatspy", "ids": ["EDGG", "EDMM"],
                                                                 "exact": False}
    assert position_range("EKCH_FW_CTR", firs, prefix="EKDK") == {"kind": "vatspy", "ids": ["EKDK"], "exact": False}
    assert position_range("ESCR_CTR", firs, prefix="ESCR")["ids"] == ["ESAA"]
    assert position_range("ESDK_CTR", firs)["ids"] == ["ESAA"]
    assert position_range("XXXX_CTR", firs, prefix="XXXX") is None
    assert position_range("EDDH_TWR", firs, 53.6, 10.0) == {"kind": "circle", "nm": 10, "lat": 53.6, "lon": 10.0}
    assert position_range("EDDH_APP", firs, 53.6, 10.0)["nm"] == 30
    assert position_range("EDDB_DEL", firs, 52.4, 13.5)["kind"] == "point"
    assert position_range("ESMM_IS_APP", firs) == {"kind": "vatspy", "ids": ["ESMM"], "exact": False}


def test_sector_kind_and_group():
    cases = {("EPWW", "EPWWB"): ("acc", "Sektor B"), ("EPWW", "EPWWR-N"): ("acc", "Sektor R"),
             ("EPWW", "EPWA_APP_N_A"): ("tma", "TMA Warszawa"), ("EPWW", "EPWA_DIR11_A"): ("tma", "TMA Warszawa"),
             ("EPWW", "EPKK_DEP07"): ("tma", "TMA Kraków"), ("EPWW", "CTA01_N"): ("tma", "CTA 01"),
             ("EPWW", "EPPO_TMA_N_A"): ("tma", "TMA Poznań N"), ("EPWW", "EPPO_TMA_S_G"): ("tma", "TMA Poznań S"),
             ("EPWW", "EPPO_EPGD_TMA-CMN"): ("tma", "TMA Poznań"),
             ("EPWW", "WAW_FIS_E_LB5"): ("fis", "FIS Warszawa"),
             ("EPWW", "EPKK_CTR07"): ("ctr", "CTR Kraków"), ("EPWW", "EPDE_MCTR"): ("ctr", "CTR Dęblin"),
             ("EPWW", "FIS_GDN_W"): ("fis", "FIS Gdańsk"), ("EPWW", "EPBA_ATZ"): ("fis", "ATZ EPBA"),
             ("EPWW", "EPWW-MIDSEA"): ("fis", "FIS Gdańsk (MIDSEA)"), ("EDWW", "EDWWFLG1"): ("nb", "EDWWFLG"),
             ("ESAA", "ESMM 8-3"): ("nb", "ESMM 8"), ("LZBB", "CTR"): ("nb", "LZBB CTR"),
             ("EDMM", "EDUUSPE12"): ("nb", "EDUUSPE12")}
    for (fir, name), want in cases.items():
        assert (sector_kind(fir, name), sector_group(fir, name)) == want, name
    assert sector_kind("ESAA", "TECH ESMM IS") is None


def test_radio_positions(client):
    ps = {p["callsign"]: p for p in client.get("/api/radio/positions").json()}
    assert ps["EPWA_APP"]["name"] == "Warszawa Approach" and ps["EPWA_APP"]["in_ese"]
    ems = ps["EDWW_EMS_CTR"]  # tylko w vacs-data
    assert not ems["in_ese"] and ems["name"] is None and ems["fir_name"] == "FIR Bremen"
    assert ems["range"] == {"kind": "vatspy", "ids": ["EDWW-EMS"], "exact": True}
    assert ps["EDDH_TWR"]["range"]["kind"] == "circle" and ps["EDDH_TWR"]["range"]["lat"] > 53
    assert not any(p["facility"] in ("FMP", "TMU") for p in ps.values())
    # stanowiska sąsiadów bez granicy w VATSpy: przybliżenie z prefiksu vacs-data / NB_ALIAS
    assert ps["EKCH_FW_CTR"]["range"] == {"kind": "vatspy", "ids": ["EKDK"], "exact": False}
    assert ps["EDUU_SPE_CTR"]["range"]["ids"] == ["EDGG", "EDMM"] and ps["EDYY_BB_CTR"]["range"]["ids"] == ["EDWW"]
    no_range = [cs for cs, p in ps.items() if not p["range"] and p["facility"] in ("CTR", "FSS")]
    assert not no_range, no_range
    assert len(ps) > 500  # 199 z .ese + ponad 300 sąsiadów tylko z vacs-data


def test_radio_online_matches_vacs_positions(client):
    on = client.get("/api/radio/online").json()
    assert on["positions"]["EDWW_EMS_CTR"]["name"] == "Tylko VACS"  # dokładny znak
    assert on["positions"]["EDDB_N_TWR"]["callsign"] == "EDDB_TWR"  # prefiks + typ + częstotliwość
    assert on["positions"]["EPWA_APP"]["cid"] == 3
    cs = {c["callsign"] for c in on["controllers"]}
    assert "EDDB_TWR" in cs and "EPKK_OBS" not in cs and "KZNY_CTR" not in cs
    assert on["firs"]["EDWW-EMS"][0]["name"] == "Tylko VACS"


def test_radio_online_upstream_error(client, monkeypatch):
    async def down():
        raise UpstreamError("timeout")

    monkeypatch.setattr(vatsim_api, "get_feed", down)
    r = client.get("/api/radio/online")
    assert r.status_code == 502 and "VATSIM" in r.json()["detail"]


def test_radio_bookings_only_known_positions(client):
    b = client.get("/api/radio/bookings").json()
    assert list(b) == ["EDWW_EMS_CTR"] and b["EDWW_EMS_CTR"][0]["name"] == "Tylko VACS"


def test_radio_sectors(client):
    gj = client.get("/api/radio/sectors").json()
    by = {(f["properties"]["fir"], f["properties"]["name"]): f["properties"] for f in gj["features"]}
    flg = by[("EDWW", "EDWWFLG1")]
    assert flg["kind"] == "nb" and flg["owners"][0] == "EDWW_FLG_CTR"
    assert by[("EPWW", "EPWWB")]["kind"] == "acc" and by[("EPWW", "EPWA_CTR")]["owners"][0] == "EPWA_TWR"
    assert by[("EPWW", "EPWA_APP_N_A")]["group"] == "TMA Warszawa"
    assert by[("EPWW", "EPPO_TMA_N_A")]["group"] == "TMA Poznań N"
    assert not any(f["properties"]["name"].startswith("TECH ") for f in gj["features"])
