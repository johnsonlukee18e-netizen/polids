"""OTHER › FMP: konfiguracje sektorów ACC EPWW (0.14.0, właściciel projektu: "Zedytuj zakładkę FMP aby użytkownik mógł wybrać dane
konfiguracje", tabela 1X … 5X) i przycisk FMP na RADIO ("Zrób mały przycisk na stronie radio z tytułem FMP który
przenosi do zakładki OTHER/FMP").
Backend: tabela w data/seed/fmp_configs.json dokładnie jak u właściciela projektu, warstwy sektorów stanowisk konfiguracji z kolejności
przejmowania (ta sama zasada co RADIO dla zalogowanych – porównanie z /api/radio/board), konfiguracja teraz po
częstotliwości jak na RADIO (199.998 się nie liczy, EPWW_DBF_CTR na 127.025 to DBT), GET /api/radio/configs z atrapą
sieci (błąd sieci = nie wiadomo, kto jest online), geometria podglądów (geo, have) i fmp w /api/radio/board.
Frontend w Node: adres (cleanCfg, parseFmpArg, fmpArg, pamięć przeglądarki), pasek CONFIGURATION, panel konfiguracji,
podglądy LOW/MID/HIGH (z polygon-clipping i bez), grupy w tabeli i cel przycisku FMP na RADIO.
0.14.2 (issue #35): widok SCENARIOS – adres z "scenarios" (cleanScn), warunki stanowisk scenariusza przy konfiguracji
(scnMatch na prawdziwych konfiguracjach), lista scenariuszy, podgląd scenariusza (przepustowość ze scenariusza,
grupy stanowisk, NOW) i jego mapy na prawdziwej geometrii."""
import json
import os
import re
import shutil
import subprocess
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR  # noqa: E402
from backend.app.routers import radio as radio_router  # noqa: E402
from backend.app.routers import vatsim as vatsim_api  # noqa: E402
from backend.app.services import fmpconfig  # noqa: E402
from backend.app.services import radioboard as rb  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

SEED = ROOT_DIR / "data" / "seed"
FRONTEND = ROOT_DIR / "frontend"
OWN = json.loads((SEED / "ownership.json").read_text("utf-8"))
DATA = json.loads((SEED / "fmp_configs.json").read_text("utf-8"))
# tabela właściciela projektu (20.11.2026) słowo w słowo
TABLE = [("1X", "ALL"), ("1S", "SFIR"), ("1N", "NFIR"), ("1E", "EFIR"), ("1D", "DTC"),
         ("2X", "NFIR+SFIR"), ("2N", "ALL+NFIR"), ("2S", "ALL+SFIR"), ("2E", "ALL+EFIR"), ("2D", "ALL+DTC"),
         ("2G", "ALL+DBFG"), ("2J", "ALL+JR"), ("2U", "ALL+ALH"),
         ("3E", "NFIR+SFIR+EFIR"), ("3W", "NFIR+SFIR+DTC"), ("3G", "ALL+DTC+DBFG"), ("3F", "ALL+FG+DBT"),
         ("3T", "EFIR+DBFG+TCJ"), ("4X", "NFIR+DTC+JR+NE"), ("5X", "DBT+FG+NE+JR+TCJ")]
NAMES = {"ALL": "EPWW_ALL_CTR", "SFIR": "EPWW_S_CTR", "NFIR": "EPWW_N_CTR", "EFIR": "EPWW_E_CTR", "DTC": "EPWW_DTC_CTR",
         "DBFG": "EPWW_DBF_CTR", "JR": "EPWW_JR_CTR", "ALH": "EPWW_ALH_CTR", "FG": "EPWW_FG_CTR", "DBT": "EPWW_DBT_CTR",
         "TCJ": "EPWW_TCJ_CTR", "NE": "EPWW_NE_CTR"}
FREQ = {cs: v["frequency"] for cs, v in OWN["acc_positions"].items()}
STATE = {"feed": None}


def ctl(cs, fq=None, cid=1):
    return {"callsign": cs, "frequency": fq or FREQ[cs], "name": f"Controller {cid}", "cid": cid}


def feed_of(*ctrls):
    return {"general": {"update_timestamp": "2026-11-20T12:00:00Z"}, "pilots": [], "atis": [], "controllers": list(ctrls)}


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()

    async def feed():
        if isinstance(STATE["feed"], Exception):
            raise STATE["feed"]
        return STATE["feed"]

    async def no_metar(icaos):
        return {}

    async def no_tvs(prefix=None, now=None):
        return {"sectors": []}

    mp.setattr(vatsim_api, "get_feed", feed)
    mp.setattr(radio_router, "get_metars", no_metar)
    mp.setattr(radio_router, "viff_sectors", no_tvs)
    with TestClient(main.app) as c:
        yield c
    mp.undo()


def configs(client, *ctrls, query=""):
    STATE["feed"] = feed_of(*ctrls)
    r = client.get("/api/radio/configs" + query)
    assert r.status_code == 200
    return r.json()


# --- dane

def test_table_data_exactly_as_owner():
    assert [(c["code"], c["label"]) for c in DATA["configs"]] == TABLE
    assert DATA["positions"] == NAMES
    assert set(NAMES.values()) <= set(OWN["acc_positions"])
    for c in DATA["configs"]:
        # napis = stanowiska po kolei, cyfra kodu = liczba stanowisk, bez powtórek
        assert c["label"] == "+".join(c["positions"]) and int(c["code"][0]) == len(c["positions"]) == len(set(c["positions"]))
        assert set(c) == {"code", "label", "positions"}
    assert DATA["note"] and "ownership.json" in DATA["note"]


def test_configs_layers_from_takeover_order():
    cfgs = fmpconfig.configs(DATA, OWN)
    by = {c["code"]: c for c in cfgs}
    assert [c["code"] for c in cfgs] == [code for code, _ in TABLE]
    assert [c["size"] for c in cfgs] == [int(code[0]) for code, _ in TABLE]
    sec = lambda code: {p["name"]: {ly: "".join(v) for ly, v in p["sectors"].items()} for p in by[code]["positions"]}  # noqa: E731
    all3 = lambda s: {"LOW": s, "MID": s, "HIGH": s}  # noqa: E731
    assert sec("1X") == {"ALL": all3("BCDEFGJNRT")}
    assert sec("2N") == {"ALL": all3("JRT"), "NFIR": all3("BCDEFGN")}
    # ALH obsługuje górę: w 2U ALL zostaje cały LOW i T MID (w kolejności T MID nie ma ALH)
    assert sec("2U") == {"ALL": {"LOW": "BCDEFGJNRT", "MID": "T", "HIGH": ""}, "ALH": {"LOW": "", "MID": "BCDEFGJNR", "HIGH": "BCDEFGJNRT"}}
    assert sec("3T")["TCJ"] == {"LOW": "CJT", "MID": "CJT", "HIGH": "CT"} and sec("3T")["EFIR"]["HIGH"] == "EJNR"
    assert sec("5X") == {"DBT": all3("BD"), "FG": all3("FG"), "NE": all3("EN"), "JR": all3("JR"), "TCJ": all3("CT")}
    # pojedyncze stanowisko nie zawsze obejmuje cały FIR: reszta to "free" (warstwy bez nikogo w tej konfiguracji)
    assert {ly: "".join(v) for ly, v in by["1S"]["free"].items()} == all3("BDFGN")
    assert {ly: "".join(v) for ly, v in by["1D"]["free"].items()} == all3("BEFGJNR")
    every = {(s["letter"], s["layer"]) for s in rb.acc_sectors(OWN)}
    for c in cfgs:
        got = [(x, ly) for p in c["positions"] for ly, xs in p["sectors"].items() for x in xs]
        free = [(x, ly) for ly, xs in c["free"].items() for x in xs]
        # każda warstwa sektora dokładnie raz: u jednego stanowiska albo bez nikogo
        assert sorted(got + free) == sorted(every), c["code"]
        assert [(p["name"], p["callsign"], p["frequency"]) for p in c["positions"]] == [
            (n, NAMES[n], FREQ[NAMES[n]]) for n in c["label"].split("+")]
        assert all(p["short"] == OWN["acc_positions"][p["callsign"]]["short"] for p in c["positions"])
    assert next(p for p in by["2G"]["positions"] if p["name"] == "DBFG")["short"] == "DBF"


def test_configs_skip_bad_entries(caplog):
    data = {"positions": {**NAMES, "XX": "EPWW_XX_CTR"}, "configs": [
        {"code": "2n", "label": "ALL+NFIR", "positions": ["ALL", "NFIR"]},
        {"code": "2N", "label": "dup", "positions": ["ALL"]},
        {"code": "22", "positions": ["ALL"]}, {"code": "1Q", "positions": ["XX"]}, {"code": "1Z", "positions": []},
        {"code": "2Z", "positions": ["ALL", "ALL"]}, "x", {"code": "1A", "positions": ["DTC"]}]}
    cfgs = fmpconfig.configs(data, OWN)
    # kod wielkimi literami; powtórzony kod, zły kod, nieznane stanowisko (spoza ownership.json), pusta lista
    # i powtórzone stanowisko pominięte; brak napisu = stanowiska po kolei
    assert [(c["code"], c["label"]) for c in cfgs] == [("2N", "ALL+NFIR"), ("1A", "DTC")]
    assert fmpconfig.table_names(data, OWN) == NAMES
    assert "pomijam" in caplog.text


def test_current_matching():
    cfgs = fmpconfig.configs(DATA, OWN)
    cur = lambda *cs: fmpconfig.current({c: {"callsign": c} for c in cs}, OWN, cfgs, DATA)  # noqa: E731
    assert cur("EPWW_N_CTR", "EPWW_ALL_CTR") == {"positions": ["EPWW_ALL_CTR", "EPWW_N_CTR"], "names": ["ALL", "NFIR"], "code": "2N"}
    assert cur("EPWW_TCJ_CTR", "EPWW_NE_CTR", "EPWW_JR_CTR", "EPWW_FG_CTR", "EPWW_DBT_CTR")["code"] == "5X"
    # stanowisko spoza tabeli (C): skrót z ownership.json, bez konfiguracji; nikt: bez konfiguracji
    assert cur("EPWW_ALL_CTR", "EPWW_C_CTR") == {"positions": ["EPWW_ALL_CTR", "EPWW_C_CTR"], "names": ["ALL", "C"], "code": None}
    assert cur() == {"positions": [], "names": [], "code": None}
    # ATIS-y, TMA i sąsiedzi się nie liczą; za mało stanowisk to inna konfiguracja
    assert cur("EPWW_ALL_CTR", "EPWA_APP", "EDWW_FLG_CTR")["code"] == "1X"
    assert cur("EPWW_N_CTR", "EPWW_S_CTR", "EPWW_E_CTR")["code"] == "3E"


# --- endpoint

def test_configs_endpoint(client):
    d = configs(client, ctl("EPWW_ALL_CTR", cid=1), ctl("EPWW_N_CTR", cid=2), ctl("EPWA_APP", "128.805", cid=3))
    assert set(d) == {"layers", "configs", "current", "ver"}
    assert d["layers"] == OWN["layers"] and d["configs"] == fmpconfig.configs(DATA, OWN)
    assert d["current"] == {"ok": True, "error": None, "updated": "2026-11-20T12:00:00Z",
                            "positions": ["EPWW_ALL_CTR", "EPWW_N_CTR"], "names": ["ALL", "NFIR"], "code": "2N"}
    # bez nazwisk kontrolerów w odpowiedzi
    assert "Controller" not in json.dumps(d)


def test_configs_by_frequency_like_radio(client):
    # 0.13.6: 199.998 = jakby go nie było; S na swojej częstotliwości liczy się
    d = configs(client, ctl("EPWW_ALL_CTR"), ctl("EPWW_S_CTR", "199.998", cid=2))
    assert d["current"]["positions"] == ["EPWW_ALL_CTR"] and d["current"]["code"] == "1X"
    assert configs(client, ctl("EPWW_ALL_CTR"), ctl("EPWW_S_CTR", cid=2))["current"]["code"] == "2S"
    # 0.13.5: rozstrzyga częstotliwość, nie znak – EPWW_DBF_CTR na 127.025 obsługuje DBT, EPWW_DBT_CTR na 133.180 DBF
    d = configs(client, ctl("EPWW_ALL_CTR"), ctl("EPWW_DBF_CTR", FREQ["EPWW_DBT_CTR"], 2), ctl("EPWW_FG_CTR", cid=3))
    assert d["current"]["names"] == ["ALL", "FG", "DBT"] and d["current"]["code"] == "3F"
    # zestaw spoza tabeli: co jest otwarte, bez kodu
    d = configs(client, ctl("EPWW_ALL_CTR"), ctl("EPWW_C_CTR", cid=2))
    assert d["current"]["names"] == ["ALL", "C"] and d["current"]["code"] is None
    d = configs(client)
    assert d["current"]["ok"] is True and d["current"]["positions"] == [] and d["current"]["code"] is None


def test_configs_network_error(client):
    """Błąd sieci nie psuje odpowiedzi: konfiguracje są, a kto jest online – nie wiadomo."""
    for err in (UpstreamError("timeout"), ValueError("bad json")):
        STATE["feed"] = err
        r = client.get("/api/radio/configs")
        assert r.status_code == 200
        d = r.json()
        assert d["current"] == {"ok": False, "error": "Network data unavailable", "updated": None, "positions": None,
                                "names": None, "code": None}
        assert len(d["configs"]) == 20
    # zepsuty feed (lista zamiast obiektu) to też brak danych, nie błąd 500
    STATE["feed"] = []
    assert client.get("/api/radio/configs").json()["current"]["ok"] is False


def test_configs_geometry(client):
    d = configs(client, query="?geo=1")
    board = client.get("/api/radio/board?geo=1").json()
    # ta sama wersja i geometria co podglądy RADIO (granica FIR EPWW i wycinki ACC)
    assert d["ver"] == board["ver"] and d["geo"] == {"border": board["geo"]["border"], "acc": board["geo"]["acc"]}
    assert d["geo"]["acc"] and all(set(a) == {"letter", "name", "lo", "hi", "geometry"} for a in d["geo"]["acc"])
    assert "geo" not in configs(client, query=f"?have={d['ver']}") and "geo" not in configs(client)
    assert "geo" in configs(client, query="?have=old")


def test_configs_missing_table(client, monkeypatch):
    def missing():
        raise FileNotFoundError(2, "No such file", "fmp_configs.json")

    def broken():
        raise ValueError("Expecting value")

    STATE["feed"] = feed_of(ctl("EPWW_ALL_CTR"))
    monkeypatch.setattr(radio_router, "_fmp_tables", missing)
    r = client.get("/api/radio/configs")
    assert r.status_code == 404 and r.json()["detail"] == "FMP configurations unavailable"
    # tablica RADIO działa dalej, tylko bez konfiguracji
    b = client.get("/api/radio/board")
    assert b.status_code == 200 and b.json()["fmp"] == {"code": None, "label": None}
    monkeypatch.setattr(radio_router, "_fmp_tables", broken)
    assert client.get("/api/radio/configs").status_code == 500
    assert client.get("/api/radio/board").json()["fmp"] == {"code": None, "label": None}


def test_board_fmp_and_same_rule_as_radio(client):
    """Przycisk FMP: /api/radio/board podaje konfigurację zalogowanych. Warstwy stanowisk konfiguracji to dokładnie
    właściciele sektorów na RADIO, gdy online są stanowiska tej konfiguracji."""
    by = {c["code"]: c for c in fmpconfig.configs(DATA, OWN)}
    for code in ("2N", "2U", "3T", "4X", "5X", "1S"):
        STATE["feed"] = feed_of(*(ctl(p["callsign"], cid=i) for i, p in enumerate(by[code]["positions"])))
        b = client.get("/api/radio/board").json()
        assert b["fmp"] == {"code": code, "label": by[code]["label"]}, code
        radio = {(s["letter"], s["layer"]): s["owner"] for s in b["sectors"]}
        cfg = {(x, ly): p["callsign"] for p in by[code]["positions"] for ly, xs in p["sectors"].items() for x in xs}
        cfg.update({(x, ly): None for ly, xs in by[code]["free"].items() for x in xs})
        assert radio == cfg, code
    STATE["feed"] = feed_of(ctl("EPWW_ALL_CTR"), ctl("EPWW_C_CTR", cid=2))
    assert client.get("/api/radio/board").json()["fmp"] == {"code": None, "label": None}
    STATE["feed"] = UpstreamError("timeout")
    assert client.get("/api/radio/board").json()["fmp"] == {"code": None, "label": None}


def test_board_acc_indicator_shows_config_code(client):
    """0.14.2 (właściciel projektu: "use here the config name so 2N in this case"): ACC GAT pokazuje kod konfiguracji
    z tabeli FMP, a litery sektorów są w dymku (note); zestaw spoza tabeli i brak danych – jak dotąd."""
    by = {c["code"]: c for c in fmpconfig.configs(DATA, OWN)}

    def acc(b):
        return next(i for i in b["indicators"] if i["id"] == "ACC GAT")
    for code in ("2N", "1X", "3T", "5X"):
        STATE["feed"] = feed_of(*(ctl(p["callsign"], cid=i) for i, p in enumerate(by[code]["positions"])))
        b = client.get("/api/radio/board").json()
        i = acc(b)
        assert i["value"] == code, code
        assert i["note"].startswith(f"Configuration {code}: {' + '.join(by[code]['label'].split('+'))} (sectors ") and i["note"].endswith(")"), i["note"]
        assert {p["callsign"] for p in i["positions"]} == {p["callsign"] for p in by[code]["positions"]}, code
        # pozostałe wskaźniki bez zmian i bez notki
        assert all(not x["note"] for x in b["indicators"] if x["id"] != "ACC GAT")
    STATE["feed"] = feed_of(ctl("EPWW_N_CTR"), ctl("EPWW_ALL_CTR", cid=2))
    assert acc(client.get("/api/radio/board").json())["value"] == "2N"
    # zestaw spoza tabeli: litery sektorów, bez notki
    STATE["feed"] = feed_of(ctl("EPWW_ALL_CTR"), ctl("EPWW_C_CTR", cid=2))
    i = acc(client.get("/api/radio/board").json())
    assert i["value"] != "" and "+" in i["value"] and i["note"] == ""
    STATE["feed"] = feed_of()
    i = acc(client.get("/api/radio/board").json())
    assert i["value"] == "0" and i["note"] == ""
    STATE["feed"] = UpstreamError("timeout")
    i = acc(client.get("/api/radio/board").json())
    assert i["note"] == ""


def test_radio_layout_fmp_button(client):
    """Przycisk FMP w wolnej komórce kolumny przycisków (H3, nad ATIS): nic się nie przesuwa, połączone okienka i nazwy
    FIR-ów jej nie zajmują."""
    lay = json.loads((SEED / "radio_layout.json").read_text("utf-8"))
    assert lay["fmp"] == {"col": 8, "row": 3} and lay["buttons"]["col"] == 8
    STATE["feed"] = feed_of()
    g = client.get("/api/radio/board").json()["grid"]
    assert g["fmp"] == {"col": 8, "row": 3, "cols": 1, "rows": 1}
    assert rb.layout_static(lay, {})["occupied"][(8, 3)] == "fmp"
    # kolumna H zostaje kolumną przycisków; inne miejsca bez zmian
    assert g["tracks"][7] == "btn" and g["status"] == {"col": 8, "row": 15, "cols": 1, "rows": 1}
    assert min(g["buttons"]["rows"].values()) == 5


# --- frontend w Node

NODE_SCRIPT = r"""
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k) };
// airspace.js (kolory stanowisk) rozszerza klasę Leafleta przy wczytaniu; w przeglądarce L jest globalny
globalThis.L = { CircleMarker: { extend: (o) => o } };
const fs = await import("node:fs");
const fmp = await import(process.argv[2]);
const rb = await import(process.argv[3]);
const data = JSON.parse(fs.readFileSync(process.argv[5], "utf-8"));
const o = {};
o.clean = ["2n", " 5X ", "2NN", "22", "0X", "", null, "EP-BH"].map(fmp.cleanCfg);
o.parse = ["2N", "2n/ep-bh", "EP-BH", "ep-watmad", "x y", "", "2N/", "2N/x y", "9z/EP-BH/X", "ED-EDWW-ALR", undefined].map(fmp.parseFmpArg);
o.arg = [["2N", "EP-BH"], ["2n", ""], ["", "ep-bh"], ["", ""], ["xx", "x y"]].map(([c, t]) => fmp.fmpArg(c, t));
o.saved0 = fmp.savedCfg();
fmp.saveCfg("3e");
o.saved1 = [fmp.savedCfg(), store.get(fmp.LS_CFG)];
fmp.saveCfg("");
o.saved2 = fmp.savedCfg();
store.set(fmp.LS_CFG, "<x>");
o.saved3 = fmp.savedCfg();
o.lsKey = [fmp.LS_CFG, rb.FMP_LS];
const cd = data.cd, cfgs = cd.configs, by = Object.fromEntries(cfgs.map((c) => [c.code, c]));
o.groups = fmp.cfgGroups(cfgs).map((g) => [g.size, g.items.map((c) => c.code)]);
o.tip = fmp.cfgTip(by["2N"]);
o.tipNow = fmp.cfgTip(by["2N"], true);
o.now = [fmp.cfgNowText(cd.current), fmp.cfgNowText({ ok: true, names: ["ALL", "SFIR"], code: null }),
  fmp.cfgNowText({ ok: true, names: [], code: null }), fmp.cfgNowText({ ok: false, error: "Network data unavailable" }), fmp.cfgNowText(null)];
o.bar = fmp.cfgBarHtml(cd, "3E");
o.barNone = fmp.cfgBarHtml({ ...cd, current: { ok: true, positions: ["EPWW_ALL_CTR", "EPWW_S_CTR"], names: ["ALL", "SFIR"], code: null } }, "");
o.barLoading = fmp.cfgBarHtml(null);
o.barErr = fmp.cfgBarHtml(null, "", "Server <down>");
o.barStale = fmp.cfgBarHtml(cd, "", "timeout");
o.panel = fmp.cfgPanelHtml(by["2N"], cd.current, cd.layers);
o.panel1S = fmp.cfgPanelHtml(by["1S"], { ok: false }, cd.layers);
o.panel3E = fmp.cfgPanelHtml(by["3E"], cd.current, cd.layers);
o.color = rb.LEVEL_FT && (await import(process.argv[4])).colorFor("EPWW_ALL_CTR");
// podglądy: bez biblioteki same wycinki, z biblioteką jeden obszar na stanowisko
o.pvNoLib = ["LOW", "MID", "HIGH"].map((ly) => fmp.cfgPreviewSvg(cd.geo, by["2U"], ly, "v1"));
// 0.14.2: mapy scenariusza bez biblioteki (wycinki osobno), prawdziwe id traffic volumes
const vc = await import(process.argv[7]);
const scnRows = (ids) => ids.map((id) => vc.fmpRows(data.real).find((r) => r.id === id));
const SCN_TVS = ["EP-NE", "EP-JRLMH", "EP-ALLFIR", "EP-WATMA"];
o.scnPvNoLib = ["LOW", "MID", "HIGH"].map((ly) => fmp.scnPreviewSvg(cd.geo, scnRows(SCN_TVS), ly, "v1", "EP-X"));
const req = (await import("node:module")).createRequire(import.meta.url);
globalThis.polygonClipping = req(process.argv[6]);
o.pv = ["LOW", "MID", "HIGH"].map((ly) => fmp.cfgPreviewSvg(cd.geo, by["2U"], ly, "v1"));
o.pv5 = fmp.cfgPreviewSvg(cd.geo, by["5X"], "LOW", "v1");
o.pv1S = fmp.cfgPreviewSvg(cd.geo, by["1S"], "LOW", "v1");
o.pvs = fmp.cfgPreviewsHtml(cd.geo, by["2N"], "v1", cd.layers);
o.pvsNone = fmp.cfgPreviewsHtml(null, by["2N"]);
o.slot = ["EP-BH", "EP-TL", "EP-JM", "EP-WATMA", "EP-ALLFIR", "EP-BHX", "ED-BH"].map(fmp.tvSlot);
const sectors = data.sectors;
const rows = (await import(process.argv[7])).fmpRows(sectors);
o.grp = Object.fromEntries(["2N", "1S", "2U"].map((c) => [c, fmp.cfgGroupRows(rows, by[c]).map((g) => [g.p ? g.p.name : g.kind, g.rows.map((r) => r.id)])]));
// 0.14.1: prawdziwe id vIFF (kombinacje) grupowane po wolumenach EPWW-<litera><warstwa>
const realRows = (await import(process.argv[7])).fmpRows(data.real);
o.slotsReal = data.real.sectors.map((t) => fmp.tvSlots(realRows.find((r) => r.id === t.id)).map((x) => x.letter + x.layer[0]).join(","));
o.grpReal = Object.fromEntries(["2N", "1S"].map((c) => [c, fmp.cfgGroupRows(realRows, by[c]).map((g) => [g.p ? g.p.name : g.kind, g.rows.map((r) => r.id)])]));
o.html = fmp.fmpHtml(sectors, "EP-BH");
o.htmlNull = fmp.fmpHtml(sectors, "EP-BH", null);
o.html2N = fmp.fmpHtml(sectors, "EP-BH", by["2N"]);
o.html1S = fmp.fmpHtml(sectors, "", by["1S"]);
o.target = [rb.fmpTarget({ code: "2N" }, "3E"), rb.fmpTarget({ code: null }, "3e"), rb.fmpTarget(null, ""), rb.fmpTarget({ code: "x" }, "bad"),
  rb.fmpTarget(undefined, undefined)];
o.fmpTip = [rb.fmpTip({ code: "2N", label: "ALL+NFIR" }), rb.fmpTip({ code: null, label: null }), rb.fmpTip(undefined)];
// --- 0.14.2 (issue #35): widok SCENARIOS
o.cleanScn = ["ep_dbfg", " EP-ALLFIR ", "x y", "", null, "A".repeat(41), "EP/1", "_X", "EP-<X>",
  // przegląd 0.14.2: wolny tekst vIFF do 64 znaków bez "/" i znaków sterujących
  "ep-kk.tma", " EP WAA1 ", "A".repeat(64), "A".repeat(65), "EP\tX", "EP\u0001X", "EP\u007fX", "/EP", "   "].map(fmp.cleanScn);
o.parseScn = ["scenarios", "SCENARIOS/ep_nfir", "2n/scenarios/EP_NFIR/ep-bh", "scenarios//EP-BH", "scenarios/EP-WATMA",
  "2N/scenarios", "scenarios/x y/EP-BH", "9z/scenarios/EP_ALL", "scenarios/EP_ALL/x y", "EP-BH/scenarios",
  "scenarios/ep-kk.tma/ep-kktma", "2N/scenarios/EP WAA1"].map(fmp.parseFmpArg);
o.argScn = [["", "", "scenarios", ""], ["2n", "", "scenarios", "ep_nfir"], ["2N", "ep-bh", "scenarios", "EP_NFIR"],
  ["", "EP-BH", "scenarios", ""], ["", "EP-BH", "", "EP_NFIR"], ["xx", "", "scenarios", "x y"], ["", "", "scenarios", "EP/1"]].map((a) => fmp.fmpArg(...a));
o.roundTrip = ["scenarios", "scenarios/EP_NFIR", "scenarios/EP_NFIR/EP-BH", "2N/scenarios/EP_NFIR/EP-BH", "2N/scenarios",
  "2N/EP-BH", "EP-BH", "2N", "", "scenarios/EP-KK.TMA/EP-KKTMA", "2N/scenarios/EP WAA1"].map((a) => { const p = fmp.parseFmpArg(a); return fmp.fmpArg(p.cfg, p.tv, p.view, p.scn); });
// przegląd 0.14.2: id spoza dawnego wzorca w liście da się kliknąć (data-scn = id wielkimi literami)
o.listOdd = fmp.scnListHtml({ prefix: "EP", scenarios_ok: true, scenarios: [
  { id: "EP-KK.TMA", active: true, tvs: [], positions: [], anypositions: [], nopositions: [], times: [] },
  { id: "ep waa1", active: false, tvs: [], positions: [], anypositions: [], nopositions: [], times: [] },
  { id: "EP/1", active: false, tvs: [], positions: [], anypositions: [], nopositions: [], times: [] }] }, "EP-KK.TMA");
// przegląd 0.14.2: komórka TIME: kawałki bez zawijania, przerwy tylko między słowami i po półpauzie przed datą końca
o.timeHtml = ["H24", "2026-11-21 1900\u20132100", "0600\u20131200, 2026-10-18 1800\u20132000", "2026-11-21 1900\u20132026-11-23 2100", "<x>", ""]
  .map(fmp.timeHtml);
const scn = data.scn, S = Object.fromEntries(scn.scenarios.map((x) => [x.id, x]));
o.match = [["EP_DBFG", "2G"], ["EP_DBFG", "2N"], ["EP-ALLFIR", "1X"], ["EP-ALLFIR", "2N"], ["EP-ALLFIR", "2D"],
  ["EP-KKTMA", "2N"], ["EP-NONE", "2N"], ["EP-ANY", "1X"], ["EP-ANY", "2N"]].map(([id, c]) => fmp.scnMatch(S[id], by[c]));
o.matchNull = fmp.scnMatch(S.EP_DBFG, null);
o.list = fmp.scnListHtml(scn, "EP_DBFG");
o.list2N = fmp.scnListHtml(scn, "", by["2N"]);
o.listBad = fmp.scnListHtml({ ...scn, scenarios: [], scenarios_ok: false });
o.listNone = [fmp.scnListHtml({ ...scn, scenarios: [] }), fmp.scnListHtml({ prefix: "EP" })];
o.listNoActive = fmp.scnListHtml({ ...scn, scenarios: scn.scenarios.filter((x) => !x.active) });
o.scnInfo = [fmp.scnInfo(scn), fmp.scnInfo({ ...scn, scenarios: [S.EP_DBFG] }), fmp.scnInfo({ ...scn, scenarios: [] }),
  fmp.scnInfo({ ...scn, scenarios_ok: false })];
o.tvRows = fmp.scnTvRows(scn, S.EP_DBFG).map((r) => [r.id, r.capacity, r.occupancyText, r.entriesCls, r.occupancyCls,
  r.capacityReg, r.nowEntries, r.nowOccupancy, r.nowKnown]);
o.preview = fmp.scnPreviewHtml(scn, S.EP_DBFG, { geo: cd.geo, ver: "v1", layers: cd.layers });
o.preview2N = fmp.scnPreviewHtml(scn, S.EP_DBFG, { cfg: by["2N"], sel: "EP-DM" });
o.previewKK = fmp.scnPreviewHtml(scn, S["EP-KKTMA"], { geo: cd.geo, ver: "v1", sel: "EP-KKTMA", err: "No <data>" });
o.previewNone = fmp.scnPreviewHtml(scn, S["EP-NONE"], { cfg: by["1X"] });
o.scnPick = fmp.scnPickHtml();
o.views = [fmp.viewBarHtml(""), fmp.viewBarHtml("scenarios")];
o.cover = data.real.sectors.map((t) => fmp.tvCover(vc.fmpRows(data.real).find((r) => r.id === t.id)).length);
o.scnPv = ["LOW", "MID", "HIGH"].map((ly) => fmp.scnPreviewSvg(cd.geo, scnRows(SCN_TVS), ly, "v1", "EP-X", "EP-NE"));
o.scnPvs = fmp.scnPreviewsHtml(cd.geo, scnRows(SCN_TVS), "v1", cd.layers, "EP-X");
o.scnPvsNone = fmp.scnPreviewsHtml(null, scnRows(["EP-WATMA", "EP-NE"]));
// podglądy konfiguracji bez zmian po dodaniu map scenariusza
o.pvAfter = fmp.cfgPreviewSvg(cd.geo, by["2U"], "LOW", "v1");
console.log(JSON.stringify(o));
"""


def _tv(tid, active=False):
    return {"id": tid, "status": 1 if active else 0, "active": active, "hours": [], "occupancy": [0], "peak_60": 0,
            "entries_cap": 40, "occupancy_cap": 12, "restrictions": []}


SECTORS = {"prefix": "EP", "now": "1210", "sectors": [
    _tv("EP-BH", True), _tv("EP-BL"), _tv("EP-JL", True), _tv("EP-TM"), _tv("EP-NH"), _tv("EP-WATMA", True),
    _tv("EP-ALLFIR"), _tv("EP-CH"), _tv("EP-XH"), _tv("EP-BDH")]}


def _rtv(tid, vols):
    return {**_tv(tid), "volumes": vols}


# prawdziwe id traffic volumes vIFF (lista z 21.11.2026) z wolumenami jak w /api/viff/sectors
_V = lambda xs, ls: [f"EPWW-{x}{ly}" for x in xs for ly in ls]  # noqa: E731
REAL = {"prefix": "EP", "now": "1210", "sectors": [
    _rtv("EP-NE", _V("NE", "H")), _rtv("EP-JR", _V("JR", "H")), _rtv("EP-JRLMH", _V("JR", "HML")),
    _rtv("EP-DTC3W", _V("DTC", "HML")), _rtv("EP-ALLFIR", _V("BCDEFGJNRT", "HML") + ["EPWA-TMA"]),
    _rtv("EP-WATMA", ["EPWA-TMA"]), _rtv("EP-BL", []), _rtv("EP-FG", [])]}


def _stv(tid, active, entries, cap, occ, ocap, reg=None):
    """Wiersz /api/viff/sectors z ruchem w bieżącej godzinie (12Z) i przepustowością z definicji TV."""
    return {"id": tid, "status": 1 if active else 0, "active": active, "volumes": [f"EPWW-{tid[3:]}"] if len(tid) == 5 else [],
            "hours": [{"hour": "12", "entries": entries, "entries_cap": cap, "peak": occ, "peak_cap": ocap}],
            "occupancy": [occ], "peak_60": occ, "entries_cap": cap, "occupancy_cap": ocap, "restrictions": [],
            "restricted": bool(reg), "regulated": {"entries": reg, "occupancy": None}}


def _scn(sid, active, tvs, **kw):
    base = {"id": sid, "active": active, "enabled": active, "tvs": [{"id": t, "occupancy_cap": o, "entries_cap": e} for t, o, e in tvs],
            "positions": [], "anypositions": [], "nopositions": [], "start": "0000", "end": "2359", "times": [],
            "description": "", "booked": False}
    return {**base, **kw}


# 0.14.2 (issue #35): odpowiedź /api/viff/sectors ze scenariuszami jak u vIFF (EP-ALLFIR, EP-KKTMA z żywych danych
# 21.11.2026: wzorzec EPWW_D*_CTR, okno z activationPeriods; przegląd 0.14.2: EP-KKTMA włączony, ale nieobowiązujący
# teraz: active=false, enabled=true); EP-DM zadeklarowany 40/14, w scenariuszu 44/15; EP-DH z regulacją wejść 30; EP-BM
# bez wiersza (scenariusz zna TV, którego lista nie ma)
SCN = {"prefix": "EP", "now": "1210", "scenarios_ok": True, "sectors": [
    _stv("EP-DH", True, 40, 44, 15, 15, reg=30), _stv("EP-DM", True, 40, 40, 13, 14), _stv("EP-BH", False, 10, 44, 2, 15),
    _stv("EP-ALLFIR", False, 50, 120, 30, 40), _stv("EP-KKTMA", True, 9, None, 3, 17)],
    "scenarios": [
        _scn("EP-ALLFIR", False, [("EP-ALLFIR", 21, 52)], positions=["EPWW_ALL_CTR"],
             nopositions=["EPWW_S_CTR", "EPWW_J_CTR", "EPWW_N_CTR", "EPWW_D*_CTR"], booked=True, description="ALLFIR SOLO"),
        _scn("EP_DBFG", True, [("EP-DH", 15, 44), ("EP-DM", 15, 44), ("EP-BH", 15, 44), ("EP-BM", 15, 44)],
             positions=["EPWW_DBF_CTR"], description="DBFG open"),
        _scn("EP-KKTMA", False, [("EP-KKTMA", 17, None), ("EP-KKTMAD", 8, None)], anypositions=["EPKK_APP"], start=None, end=None,
             times=[{"from": "1900", "to": "2100", "date": "2026-11-21"}], booked=True, description="podział FIR", enabled=True),
        _scn("EP-NONE", False, []),
        _scn("EP-ANY", False, [("EP-BH", 15, 44)], anypositions=["EPWW_N_CTR", "EPWW_S_CTR"]),
        _scn("EP-<X>", False, [("EP-<X>", 1, 2)], start="1600", end="2200", times=[{"from": "1600", "to": "2200", "date": None}]),
    ]}


@pytest.fixture(scope="module")
def js(client, tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("fmpcfg")
    jsd = d / "js"
    shutil.copytree(FRONTEND / "js", jsd)
    (jsd / "package.json").write_text('{"type": "module"}', "utf-8")
    pc = d / "pc.cjs"
    pc.write_text((FRONTEND / "vendor" / "polygon-clipping" / "polygon-clipping.umd.min.js").read_text("utf-8"), "utf-8")
    cd = configs(client, ctl("EPWW_ALL_CTR"), ctl("EPWW_N_CTR", cid=2), query="?geo=1")
    data = d / "data.json"
    data.write_text(json.dumps({"cd": cd, "sectors": SECTORS, "real": REAL, "scn": SCN}), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (jsd / "fmp.js").as_uri(), (jsd / "radioboard.js").as_uri(),
                        (jsd / "airspace.js").as_uri(), str(data), str(pc), (jsd / "viffchart.js").as_uri()],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_js_address_and_memory(js):
    assert js["clean"] == ["2N", "5X", "", "", "", "", "", ""]
    p = [(x["cfg"], x["tv"]) for x in js["parse"]]
    # "#other/fmp/EP-BH" (do 0.13.6) dalej: sam sektor bez konfiguracji
    assert p == [("2N", ""), ("2N", "EP-BH"), ("", "EP-BH"), ("", "EP-WATMAD"), ("", ""), ("", ""), ("2N", ""), ("2N", ""),
                 ("9Z", ""), ("", "ED-EDWW-ALR"), ("", "")]
    assert js["arg"] == ["2N/EP-BH", "2N", "EP-BH", "", ""]
    # pamięć przeglądarki: kod oczyszczony; pusty = bez konfiguracji; śmieci = bez konfiguracji
    assert js["saved0"] == "" and js["saved1"] == ["3E", "3E"] and js["saved2"] == "" and js["saved3"] == ""
    assert js["lsKey"] == ["fmp.config", "fmp.config"]


def test_js_configuration_bar(js):
    assert js["groups"] == [[1, ["1X", "1S", "1N", "1E", "1D"]], [2, ["2X", "2N", "2S", "2E", "2D", "2G", "2J", "2U"]],
                            [3, ["3E", "3W", "3G", "3F", "3T"]], [4, ["4X"]], [5, ["5X"]]]
    assert js["tip"] == "2N: ALL + NFIR\nALL EPWW_ALL_CTR 125.450\nNFIR EPWW_N_CTR 130.675"
    assert js["tipNow"].endswith("\nControllers online now")
    # online ALL + N = 2N: znak NOW na przycisku, bez linii; inaczej linia z tym, co jest otwarte
    assert js["now"] == ["", "Now: ALL+SFIR, not in the table", "Now: no EPWW ACC position online",
                         "Now: unknown (Network data unavailable)", ""]
    bar = js["bar"]
    assert bar.startswith('<span class="fmp-cfg-t"') and ">CONFIGURATION</span>" in bar
    assert bar.count('<button type="button" class="fmp-cb') == 20 and bar.count('class="fmp-cfg-g"') == 5
    assert '<button type="button" class="fmp-cb now" data-cfg="2N" aria-pressed="false" title="2N: ALL + NFIR' in bar
    assert '2N<span class="fmp-cb-now">NOW</span></button>' in bar and bar.count("fmp-cb-now") == 1
    assert '<button type="button" class="fmp-cb on" data-cfg="3E" aria-pressed="true"' in bar
    assert '<span class="fmp-cfg-n" title="1 position">1</span>' in bar and 'title="5 positions">5</span>' in bar
    assert "fmp-cfg-now" not in bar
    none = js["barNone"]
    assert "fmp-cb-now" not in none and '<span class="fmp-cfg-now">Now: ALL+SFIR, not in the table</span>' in none
    assert "Loading…" in js["barLoading"] and '<span class="fmp-cfg-msg error">Server &lt;down&gt;</span>' in js["barErr"]
    assert '<span class="fmp-cfg-msg error">Not refreshed: timeout</span>' in js["barStale"]
    for html in (bar, none, js["panel"], js["html2N"]):
        assert "<b>" not in html and "<strong" not in html


def test_js_configuration_panel(js):
    p = js["panel"]
    assert '<span class="fmp-cp-code">2N</span><span class="fmp-cp-lbl">ALL + NFIR</span><span class="fmp-cp-now"' in p
    # stanowisko: kolor jak na MAP, nazwa z tabeli, znak, częstotliwość, online, warstwy sektorów
    assert js["color"] == "#4fcc92"
    assert ('<tr><td class="fmp-cp-pos"><i class="fmp-sw" style="background:#4fcc92"></i>ALL</td><td class="fmp-cp-cs">EPWW_ALL_CTR</td>'
            '<td class="fmp-cp-fq">125.450</td><td class="fmp-cp-st online">online</td><td class="fmp-cp-ly">J R T</td>'
            '<td class="fmp-cp-ly">J R T</td><td class="fmp-cp-ly">J R T</td></tr>') in p
    assert '<td class="fmp-cp-ly">B C D E F G N</td>' in p and "fmp-cp-free" not in p
    assert '<th title="LOW: FL095–FL335">LOW</th>' in p
    # bez danych sieci: nie wiadomo; 1S: wiersz warstw bez nikogo
    s = js["panel1S"]
    assert '<td class="fmp-cp-st unknown">unknown</td>' in s and "fmp-cp-now" not in s
    assert '<tr class="fmp-cp-free"' in s and '<td colspan="4">Not covered</td><td class="fmp-cp-ly">B D F G N</td>' in s
    assert '<td class="fmp-cp-st offline">offline</td>' in js["panel3E"] and '<td class="fmp-cp-st online">online</td>' in js["panel3E"]


def test_js_previews(js):
    import re
    labels = lambda svg: re.findall(r'<text class="fmp-pv-l" x="[\d.]+" y="[\d.]+">([^<]+)</text>', svg)  # noqa: E731
    # 2U: na LOW tylko ALL, na MID ALH i ALL (T), na HIGH tylko ALH; kolory stanowisk, granica FIR na wierzchu
    assert [labels(s) for s in js["pv"]] == [["ALL"], ["ALL", "ALH"], ["ALH"]] or \
        [sorted(labels(s)) for s in js["pv"]] == [["ALL"], ["ALH", "ALL"], ["ALH"]]
    low, mid, high = js["pv"]
    assert low.count('class="fmp-pv-a"') == 1 and 'fill="#4fcc92" stroke="#4fcc92"' in low and "fmp-pv-free" not in low
    assert high.count('class="fmp-pv-a"') == 1 and 'fill="#4ed227"' in high
    assert mid.count('class="fmp-pv-a"') == 2 and low.count('class="fmp-pv-b"') == 1
    assert low.startswith('<svg class="fmp-pv-svg" viewBox="0 0 160 150" role="img" aria-label="LOW sectors of configuration 2U">')
    assert low.index("fmp-pv-a") < low.index("fmp-pv-b") < low.index("fmp-pv-l")
    # bez biblioteki: każdy wycinek osobno (bez konturów), etykiety te same
    nolib = js["pvNoLib"]
    assert "fmp-pv-a" not in nolib[0] and nolib[0].count('class="fmp-pv-s"') > 1
    assert [sorted(labels(s)) for s in nolib] == [sorted(labels(s)) for s in js["pv"]]
    assert sorted(labels(js["pv5"])) == ["DBT", "FG", "JR", "NE", "TCJ"] and js["pv5"].count('class="fmp-pv-a"') == 5
    # 1S: warstwy bez nikogo szare
    assert labels(js["pv1S"]) == ["SFIR"] and "fmp-pv-free" in js["pv1S"]
    pvs = js["pvs"]
    assert pvs.count('<figure class="fmp-pv">') == 3 and "LOW <span>FL330</span>" in pvs and "HIGH <span>FL400</span>" in pvs
    assert 'title="MID (FL335–FL365): sectors at FL350"' in pvs
    assert js["pvsNone"] == '<p class="hint fmp-pv-none">No sector geometry.</p>'


def test_js_grouped_table(js):
    assert js["slot"] == [{"letter": "B", "layer": "HIGH"}, {"letter": "T", "layer": "LOW"}, {"letter": "J", "layer": "MID"},
                          None, None, None, None]
    # 2N: sektory pod stanowiskiem, które obsługuje tę warstwę; TMA, FIR, kombinacje i nieznane litery w OTHER
    assert js["grp"]["2N"] == [["ALL", ["EP-JL", "EP-TM"]], ["NFIR", ["EP-BH", "EP-BL", "EP-CH", "EP-NH"]],
                               ["other", ["EP-WATMA", "EP-XH", "EP-BDH", "EP-ALLFIR"]]]
    # 1S: warstwy bez stanowiska konfiguracji w NOT COVERED
    assert js["grp"]["1S"] == [["SFIR", ["EP-JL", "EP-CH", "EP-TM"]], ["free", ["EP-BH", "EP-BL", "EP-NH"]],
                               ["other", ["EP-WATMA", "EP-XH", "EP-BDH", "EP-ALLFIR"]]]
    assert js["grp"]["2U"][0] == ["ALL", ["EP-JL", "EP-BL", "EP-TM"]] and js["grp"]["2U"][1] == ["ALH", ["EP-BH", "EP-CH", "EP-NH"]]
    # 0.14.1: prawdziwe id vIFF to kombinacje; warstwy z wolumenów EPWW-<litera><warstwa>, bez wolumenów z id
    assert js["slotsReal"] == ["NH,EH", "JH,RH", "JH,JM,JL,RH,RM,RL", "DH,DM,DL,TH,TM,TL,CH,CM,CL", "", "", "BL", ""]
    # kombinacja w grupie stanowiska, które obsługuje wszystkie jej warstwy; kilku stanowisk, TMA i FIR w OTHER
    assert js["grpReal"]["2N"] == [["ALL", ["EP-JR", "EP-JRLMH"]], ["NFIR", ["EP-BL", "EP-NE"]],
                                   ["other", ["EP-DTC3W", "EP-FG", "EP-WATMA", "EP-ALLFIR"]]]
    # 1S: NE częściowo SFIR, częściowo bez stanowiska = OTHER
    assert js["grpReal"]["1S"] == [["SFIR", ["EP-JR", "EP-JRLMH"]], ["free", ["EP-BL"]],
                                   ["other", ["EP-DTC3W", "EP-FG", "EP-NE", "EP-WATMA", "EP-ALLFIR"]]]
    # bez konfiguracji tabela jak dotąd
    assert js["html"] == js["htmlNull"] and '<table class="fmp-table">' in js["html"] and "fmp-grp" not in js["html"]
    g = js["html2N"]
    assert '<table class="fmp-table grouped">' in g and g.count('<tr class="fmp-grp') == 3
    assert ('<tr class="fmp-grp"><td colspan="3" title="ALL: EPWW_ALL_CTR 125.450"><i class="fmp-sw" style="background:#4fcc92"></i>'
            'ALL<span class="fmp-grp-sub">EPWW_ALL_CTR 125.450</span></td></tr>') in g
    assert '<tr class="fmp-grp other"><td colspan="3" title="TMA, FIR-wide traffic volumes and combinations across positions">OTHER</td></tr>' in g
    # wiersze z tymi samymi klasami i wyborem co bez konfiguracji (klik w wiersz, wykresy ENTRY i OCC)
    assert g.count("<tr class=\"on sel\" data-tv=\"EP-BH\">") == 1 and g.count("data-tv=") == 10
    assert g.index(">ALL<") < g.index('data-tv="EP-JL"') < g.index(">NFIR<") < g.index('data-tv="EP-BH"') < g.index(">OTHER<")
    assert '<tr class="fmp-grp free"><td colspan="3" title="Sector layers with no position of this configuration">NOT COVERED</td></tr>' in js["html1S"]


def test_js_radio_fmp_button(js):
    # zalogowani w tabeli: ich konfiguracja; inaczej ostatnio wybrana w FMP; bez obu samo OTHER › FMP
    assert js["target"] == ["fmp/2N", "fmp/3E", "fmp", "fmp", "fmp"]
    assert js["fmpTip"] == ["OTHER › FMP: sector configurations and capacity\nConfiguration now: 2N: ALL + NFIR",
                            "OTHER › FMP: sector configurations and capacity", "OTHER › FMP: sector configurations and capacity"]


def test_radio_fmp_button_source():
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    # przycisk w komórce grid.fmp, ten sam wygląd co przyciski warstw (.rb-btns button), bez aria-pressed (nie włącza
    # warstwy); klik = OTHER › FMP
    assert '<button type="button" data-go="fmp" data-rt="${esc(fmpTip(d?.fmp))}">FMP</button>' in radio
    assert 'navigate("other", fmpTarget(d?.fmp, lsGet(FMP_LS)))' in radio
    assert "renderButtonCells(grid.buttons, top, grid.fmp)" in radio
    # RADIO nie importuje fmp.js (ten ciągnie airspace.js z Leafletem); klucz pamięci wspólny przez radioboard.js
    assert '"../fmp.js"' not in radio
    assert "export const LS_CFG = FMP_LS;" in (FRONTEND / "js" / "fmp.js").read_text("utf-8")


def test_fmp_files_conventions():
    import re
    src = (FRONTEND / "js" / "fmp.js").read_text("utf-8")
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "fmp.css").read_text("utf-8"), flags=re.S)
    assert not re.search(r"border-radius:\s*[1-9]|text-shadow|box-shadow:\s*0 0 [1-9]|drop-shadow|glow", css)
    # przegląd 0.14.0: niskie albo wąskie okno – tabela co najmniej 300 px, a przewija się cały obszar FMP; lista
    # stanowisk panelu przewija się w poziomie zamiast ucinać kolumny warstw
    assert ".pane.fill > .fmp { overflow-y: auto; }" in css and ".pane.fill > .fmp > .fmp-main { min-height: 300px; }" in css
    assert ".fmp-cp-list { min-width: 0; max-width: 100%; overflow-x: auto; }" in css
    assert "0.14.0 (właściciel projektu)" in src and "0.14.0 (właściciel projektu)" in (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    # nazwy klas bez słów, po których blokery reklam chowają elementy
    names = set(re.findall(r"\.(fmp-[a-z0-9-]+)", css)) | set(re.findall(r'class="([a-z0-9 -]+)"', src))
    assert names and not any(re.search(r"(^|[\s-])(ad|ads|advert|banner|sponsor|promo)", n) for n in names)


# --- 0.14.2 (issue #35): widok SCENARIOS

def test_js_scenario_address(js):
    # przegląd 0.14.2: id scenariusza to wolny tekst vIFF: każdy napis do 64 znaków bez "/" i znaków sterujących
    assert js["cleanScn"] == ["EP_DBFG", "EP-ALLFIR", "X Y", "", "", "A" * 41, "", "_X", "EP-<X>",
                              "EP-KK.TMA", "EP WAA1", "A" * 64, "", "", "", "", "", ""]
    p = [(x["cfg"], x["tv"], x["view"], x["scn"]) for x in js["parseScn"]]
    assert p == [("", "", "scenarios", ""), ("", "", "scenarios", "EP_NFIR"), ("2N", "EP-BH", "scenarios", "EP_NFIR"),
                 ("", "", "scenarios", ""), ("", "", "scenarios", "EP-WATMA"), ("2N", "", "scenarios", ""),
                 # zły scenariusz: bez scenariusza i bez sektora; zły sektor przy scenariuszu: sam scenariusz
                 ("", "EP-BH", "scenarios", "X Y"), ("9Z", "", "scenarios", "EP_ALL"), ("", "", "scenarios", "EP_ALL"),
                 # "scenarios" tylko na początku (po konfiguracji); inaczej to (zły) sektor jak dotąd
                 ("", "", "", ""),
                 # przegląd 0.14.2: id z kropką albo spacją (router koduje adres sam)
                 ("", "EP-KKTMA", "scenarios", "EP-KK.TMA"), ("2N", "", "scenarios", "EP WAA1")]
    # stare adresy: te same {cfg, tv} co do 0.14.1, bez widoku
    assert all(x["view"] == "" and x["scn"] == "" for x in js["parse"])
    assert js["argScn"] == ["scenarios", "2N/scenarios/EP_NFIR", "2N/scenarios/EP_NFIR/EP-BH", "scenarios", "EP-BH",
                            "scenarios/X Y", "scenarios"]
    assert js["roundTrip"] == ["scenarios", "scenarios/EP_NFIR", "scenarios/EP_NFIR/EP-BH", "2N/scenarios/EP_NFIR/EP-BH",
                               "2N/scenarios", "2N/EP-BH", "EP-BH", "2N", "", "scenarios/EP-KK.TMA/EP-KKTMA", "2N/scenarios/EP WAA1"]
    # wiersz z takim id ma data-scn do kliknięcia i zaznaczenia (wcześniej data-scn="": wiersz nic nie robił)
    assert re.findall(r'<tr class="([a-z ]+)" data-scn="([^"]*)">', js["listOdd"]) == [("on sel", "EP-KK.TMA"), ("off", "EP WAA1")]
    # id, którego adres nie uniesie ("/"): wiersz bez data-scn, nie wygląda na klikalny (CSS), dymek "No preview"
    rows = re.findall(r'<tr class="([a-z -]+)"( data-scn="[^"]*")?><td class="fmp-sec" title="([^"]*)">([^<]*)</td>', js["listOdd"])
    assert [r[3] for r in rows] == ["EP-KK.TMA", "EP/1", "ep waa1"] and rows[1] == (
        "off fmp-scn-nopv", "", "Scenario EP/1: no traffic volumes · no conditions\n"
        "No preview: this scenario id cannot be used in the page address.", "EP/1")
    assert js["listOdd"].count("fmp-scn-nopv") == 1 and js["listOdd"].count("No preview") == 1


def test_js_scenario_match_with_real_configurations(js):
    st = [m["state"] for m in js["match"]]
    # DBFG z 2G (ALL + DBFG) tak, z 2N nie; ALLFIR solo z 1X tak, z 2N nie (N otwarte), z 2D nie (DTC pasuje do
    # wzorca EPWW_D*_CTR); KKTMA zależy od APP; bez warunków tak; "jedno z" N/S: 1X nie, 2N tak
    assert st == ["yes", "no", "yes", "no", "no", "unknown", "yes", "no", "yes"]
    t = [m["text"] for m in js["match"]]
    assert t[0] == "With 2G (ALL + DBFG): the position conditions are met"
    assert t[1] == "With 2N (ALL + NFIR): not met (EPWW_DBF_CTR not open)"
    assert t[3] == "With 2N (ALL + NFIR): not met (EPWW_N_CTR open)" and t[4] == "With 2D (ALL + DTC): not met (EPWW_D*_CTR open)"
    assert t[5] == "With 2N (ALL + NFIR): depends on other positions (EPKK_APP)"
    assert t[7] == "With 1X (ALL): not met (none of EPWW_N_CTR, EPWW_S_CTR open)"
    assert js["matchNull"] is None


def test_js_scenario_list(js):
    h = js["list"]
    assert h.startswith('<table class="fmp-table fmp-scn-table">')
    # przegląd 0.14.2: ACTIVE = obowiązuje teraz; EP-KKTMA (włączony, okno 1900–2100 jeszcze przed nami) w INACTIVE
    assert [m for m in re.findall(r'<tr class="fmp-grp"><td colspan="(\d)"[^>]*>([A-Z]+)<span class="fmp-grp-sub">(\d+)</span>', h)] == [
        ("4", "ACTIVE", "1"), ("4", "INACTIVE", "5")]
    # aktywne na początku, potem po id (jak backend: "-" przed "_"); wybrany wiersz zielony (sel), nieaktywne czarne;
    # przegląd 0.14.2: id spoza dawnego wzorca adresu (EP-<X>) też z data-scn (escapowanym) do kliknięcia
    assert re.findall(r'<tr class="([a-z ]+)" data-scn="([^"]*)">', h) == [
        ("on sel", "EP_DBFG"), ("off", "EP-&lt;X&gt;"), ("off", "EP-ALLFIR"), ("off", "EP-ANY"), ("off", "EP-KKTMA"), ("off", "EP-NONE")]
    # dymek włączonego, ale nieobowiązującego scenariusza
    assert '<td class="fmp-sec" title="Scenario EP-KKTMA (enabled, not active now): traffic volumes EP-KKTMA (TMA EPKK)' in h
    assert h.count("(enabled, not active now)") == 1
    # warunki bez okien czasu, okna w TIME (bez powtórek, bez okna H24; kawałki bez zawijania), kody TV bez "EP-"
    # z przepustowością w dymku
    assert '<td class="fmp-scn-cond">when online: EPWW_DBF_CTR</td><td class="fmp-scn-time"><span>H24</span></td>' in h
    assert ('<td class="fmp-scn-tvs" title="EP-DH: 44 entries/h, 15 aircraft at once\nEP-DM: 44 entries/h, 15 aircraft at once\n'
            'EP-BH: 44 entries/h, 15 aircraft at once\nEP-BM: 44 entries/h, 15 aircraft at once">DH DM BH BM</td>') in h
    assert ('<td class="fmp-scn-cond">when online: EPKK_APP · bookings count too</td><td class="fmp-scn-time"><span>2026-11-21</span> '
            '<span>1900–2100</span></td>'
            '<td class="fmp-scn-tvs" title="EP-KKTMA: no entry limit, 17 aircraft at once\nEP-KKTMAD: no entry limit, 8 aircraft at once">'
            'KKTMA KKTMAD</td>') in h
    assert ('<td class="fmp-scn-cond">when online: EPWW_ALL_CTR · and offline: EPWW_S_CTR, EPWW_J_CTR, EPWW_N_CTR, EPWW_D*_CTR'
            ' · bookings count too</td>') in h
    assert ('<td class="fmp-scn-cond">no position conditions</td><td class="fmp-scn-time"><span>H24</span></td>'
            '<td class="fmp-scn-tvs" title="No traffic volumes">–</td>') in h
    # id escapowane (dymek i komórka), okno podane dwa razy raz
    assert '>EP-&lt;X&gt;</td>' in h and "<X>" not in h and '<td class="fmp-scn-time"><span>1600–2200</span></td>' in h
    assert '<td class="fmp-sec" title="Scenario EP_DBFG: traffic volumes EP-DH (sector D upper)' in h
    # bez konfiguracji bez kolumny konfiguracji
    assert "fmp-scn-m" not in h and "<th" in h and h.count("<th ") == 4
    g = js["list2N"]
    assert re.findall(r'<td class="fmp-scn-m (\w+)" title="[^"]*">([^<]+)</td>', g) == [
        ("no", "no"), ("yes", "yes"), ("no", "no"), ("yes", "yes"), ("unknown", "?"), ("yes", "yes")]
    assert ('<td class="fmp-scn-m no" title="With 2N (ALL + NFIR): not met (EPWW_DBF_CTR not open). '
            'Time windows and bookings are not checked.">no</td>') in g
    assert '>2N</th>' in g and "Time windows and bookings are not checked." in g.split("</thead>")[0]
    assert g.count('<td colspan="5"') == 2
    # brak listy (błąd) i pusta lista; bez aktywnych: zdanie w grupie ACTIVE
    assert js["listBad"] == '<p class="error fmp-empty">Scenarios unavailable.</p>'
    assert js["listNone"] == ['<p class="hint fmp-empty">No scenarios.</p>'] * 2
    na = js["listNoActive"]
    assert '<tr class="fmp-none"><td colspan="4">No scenario is active now</td></tr>' in na and 'data-scn="EP_DBFG"' not in na
    assert js["scnInfo"] == ["1210Z · 1 of 6 scenarios active (grey rows)", "1210Z · 1 of 1 scenario active (grey rows)", "", ""]
    # przegląd 0.14.2: komórka TIME
    assert js["timeHtml"] == ["<span>H24</span>", "<span>2026-11-21</span> <span>1900–2100</span>",
                              "<span>0600–1200,</span> <span>2026-10-18</span> <span>1800–2000</span>",
                              "<span>2026-11-21</span> <span>1900–</span><wbr><span>2026-11-23</span> <span>2100</span>",
                              "<span>&lt;x&gt;</span>", "<span></span>"]
    for html in (h, g, na):
        # bez opisu scenariusza (wolny tekst), bez pogrubień i bez nazwy źródła
        assert "DBFG open" not in html and "podział" not in html and "SOLO" not in html
        assert "<b>" not in html and "<strong" not in html and "viff" not in html.lower()


def test_js_scenario_preview(js):
    rows = {r[0]: r[1:] for r in js["tvRows"]}
    # przepustowość ze scenariusza (DM: 44 zamiast zadeklarowanych 40, więc 40 wejść = 90 %), regulacja TV zostaje
    # (DH: 30 z regulacji, czerwona), CAPACITY NOW = przepustowość teraz; BM bez wiersza w liście: same przepustowości
    assert rows["EP-DM"] == ["40 (44)", "13 (15)", "near", "ok", False, 40, 14, True]
    assert rows["EP-DH"] == ["40 (30)", "15 (15)", "over", "near", True, 30, 15, True]
    assert rows["EP-BH"] == ["10 (44)", "2 (15)", "ok", "ok", False, 44, 15, True]
    assert rows["EP-BM"] == ["– (44)", "– (15)", "nolim", "nolim", False, None, None, False]
    assert [r[0] for r in js["tvRows"]] == ["EP-DH", "EP-DM", "EP-BH", "EP-BM"]   # kolejność scenariusza
    p = js["preview"]
    assert p.startswith('<div class="fmc fmp-sp"><div class="fmc-head"><span class="fmc-code" title="Scenario EP_DBFG: ')
    assert ('>EP_DBFG</span><span class="fmc-desc">scenario preview</span><span class="fmc-chip on" title="Active now">ACTIVE</span>'
            '<button type="button" class="fmp-sp-close" title="Close the preview" aria-label="Close the preview">✕</button></div>') in p
    assert '<div class="fmc-meta">when online: EPWW_DBF_CTR</div>' in p and "fmp-sp-cfg" not in p
    assert '<p class="hint fmp-sp-note">Preview only: nothing is activated. Capacities as set in the scenario, traffic now.</p>' in p
    assert '<table class="fmp-table fmp-sp-tab"><thead><tr><th title="Traffic volume of the scenario">SECTOR</th>' in p
    assert '<td class="fmp-num near" title="40 entries this hour, capacity 44">40 (44)</td>' in p
    assert '<td class="fmp-sp-now" title="capacity now: 40 entries/h, 14 aircraft at once">40 / 14</td></tr>' in p
    assert '<th title="Capacity in force now: entries per hour / aircraft at once">CAPACITY NOW</th></tr></thead>' in p
    assert '40 (<span class="fmp-regcap">30</span>)' in p and '<td class="fmp-sec reg"' in p
    assert '<td class="fmp-sp-now" title="Not in the traffic volume list now">– / –</td>' in p
    # mapy: HIGH z DH i BH, MID z DM i BM (BM bez wolumenów: warstwa z id), LOW bez obszarów scenariusza
    assert p.count('<figure class="fmp-pv">') == 3 and 'aria-label="HIGH traffic volumes of scenario EP_DBFG"' in p
    svgs = re.findall(r"<svg .*?</svg>", p)
    labels = [sorted(re.findall(r'class="fmp-pv-l" [^>]*>([^<]+)<', x)) for x in svgs]
    assert labels == [[], ["BM", "DM"], ["BH", "DH"]] and "fmp-pv-on" not in svgs[0] and "fmp-sp-off" not in p
    assert "fmp-sp-chart" not in p and "fmc-close" not in p
    g = js["preview2N"]
    # konfiguracja: linia warunków, tabela w grupach stanowisk (4 kolumny), wybrany TV z wykresem (jeszcze "Loading")
    assert '<div class="fmp-sp-cfg no" title="Time windows and bookings are not checked.">With 2N (ALL + NFIR): not met (EPWW_DBF_CTR not open)</div>' in g
    assert '<table class="fmp-table fmp-sp-tab grouped">' in g and '<tr class="fmp-grp"><td colspan="4" title="ALL: EPWW_ALL_CTR 125.450">' in g
    assert '<tr class="fmp-none"><td colspan="4">No traffic volumes</td></tr>' in g and 'colspan="3"' not in g
    assert g.index(">NFIR<") < g.index('data-tv="EP-DH"') and '<tr class="on sel" data-tv="EP-DM">' in g
    chart = g.split('<div class="fmp-sp-chart">')[1]
    assert 'title="EP-DM">DM</span>' in chart and "Loading…" in chart and 'class="fmc-close"' in chart
    assert '<p class="hint fmp-pv-none">No sector geometry.</p>' in g
    kk = js["previewKK"]
    # TMA: poza mapami; błąd wykresu w panelu; okno czasu z datą w warunkach; nieaktywny / aktywny wg scenariusza
    assert '<p class="hint fmp-sp-off">Not on the maps: KKTMA, KKTMAD</p>' in kk and '<p class="error fmc-err">No &lt;data&gt;</p>' in kk
    # przegląd 0.14.2: włączony, ale nieobowiązujący teraz: INACTIVE z dymkiem (znak i kod w nagłówku)
    assert '<span class="fmc-chip" title="Enabled, not active now">INACTIVE</span>' in kk
    assert '<span class="fmc-code" title="Scenario EP-KKTMA (enabled, not active now): ' in kk
    assert "when online: EPKK_APP · bookings count too · 2026-11-21 time 1900–2100" in kk and "podział" not in kk
    nn = js["previewNone"]
    assert '<span class="fmc-chip" title="Not active now">INACTIVE</span>' in nn and '<div class="fmp-sp-cfg yes"' in nn
    assert "enabled" not in nn and "enabled" not in p
    assert '<tr class="fmp-none"><td colspan="4">No traffic volumes</td></tr>' in nn and "fmp-grp" not in nn
    assert js["scnPick"] == '<p class="hint fmp-pick">Click a scenario to preview its traffic volumes and capacities.</p>'
    v0, v1 = js["views"]
    assert v0.startswith('<button type="button" class="fmp-cb fmp-vb on" data-view="sectors" aria-pressed="true"') and ">SECTORS</button>" in v0
    assert '<button type="button" class="fmp-cb fmp-vb" data-view="scenarios" aria-pressed="false"' in v0
    assert '<button type="button" class="fmp-cb fmp-vb on" data-view="scenarios" aria-pressed="true"' in v1 and ">SCENARIOS</button>" in v1
    for html in (p, g, kk, nn, v0, v1):
        assert "<b>" not in html and "<strong" not in html and "viff" not in html.lower() and "DBFG open" not in html


def test_js_scenario_maps_real_geometry(js):
    lab = lambda svg: sorted(re.findall(r'<text class="fmp-pv-l" x="[\d.]+" y="[\d.]+">([^<]+)</text>', svg))  # noqa: E731
    low, mid, high = js["scnPv"]
    # NE tylko na HIGH (wolumeny NH, EH); JRLMH na wszystkich; ALLFIR mimo wolumenu EPWA-TMA (tvCover, nie tvSlots)
    assert lab(high) == ["ALLFIR", "JRLMH", "NE"] and lab(low) == ["ALLFIR", "JRLMH"] and lab(mid) == ["ALLFIR", "JRLMH"]
    assert js["cover"] == [2, 2, 6, 9, 30, 0, 1, 0]
    # ALLFIR obejmuje cały FIR: bez szarych wycinków; granica na wierzchu, etykiety na końcu; wybrany NE jaśniej
    assert "fmp-pv-free" not in low and low.index("fmp-pv-on") < low.index("fmp-pv-b") < low.index("fmp-pv-l")
    assert high.count('<path class="fmp-pv-on sel"') == 1 and "fmp-pv-on sel" not in low
    assert low.startswith('<svg class="fmp-pv-svg" viewBox="0 0 160 150" role="img" aria-label="LOW traffic volumes of scenario EP-X">')
    assert low.count('<path class="fmp-pv-on') == 2 and "fill=" not in low   # kolor z CSS, nie kolory stanowisk
    # bez biblioteki: wycinki osobno, te same etykiety
    nolib = js["scnPvNoLib"]
    assert all("fmp-pv-s fmp-pv-on" in x for x in nolib) and [lab(x) for x in nolib] == [lab(x) for x in js["scnPv"]]
    pvs = js["scnPvs"]
    assert pvs.startswith('<div class="fmp-pvs"><figure class="fmp-pv">') and pvs.count("<figure") == 3
    assert pvs.endswith('</div><p class="hint fmp-sp-off">Not on the maps: WATMA</p>')
    assert js["scnPvsNone"] == '<p class="hint fmp-pv-none">No sector geometry.</p><p class="hint fmp-sp-off">Not on the maps: WATMA</p>'
    # podgląd konfiguracji (0.14.0) bez zmian
    assert js["pvAfter"] == js["pv"][0]


def test_scenario_list_and_preview_css():
    """Przegląd 0.14.2: lista scenariuszy mieści się w 424 px jak tabela SECTORS (okno 1280 i 1366 px, także z kolumną
    konfiguracji; sprawdzone w przeglądarce: scrollWidth = clientWidth): węższe odstępy w komórkach listy, TIME zawijany
    tylko między kawałkami bez zawijania (timeHtml), szerokość TIME tylko preferowana. Nagłówek tabeli podglądu przyklejony
    do górnej krawędzi panelu (.fmp-side ma 6 px górnego odstępu), w wąskim oknie (przewija się .fmp-main) bez przesunięcia."""
    import re
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "fmp.css").read_text("utf-8"), flags=re.S)
    assert "table.fmp-scn-table th, table.fmp-scn-table td { padding-left: 6px; padding-right: 6px; }" in css
    assert "table.fmp-scn-table td.fmp-scn-time { width: 158px; white-space: normal; font-size: 14px; }" in css
    assert "table.fmp-scn-table td.fmp-scn-time span { white-space: nowrap; }" in css
    # scenariusz bez podglądu: bez rączki i bez podświetlenia wiersza
    assert "table.fmp-scn-table tbody tr.fmp-scn-nopv { cursor: default; }" in css
    assert "table.fmp-scn-table tr.fmp-scn-nopv.on:hover td { background: #484848; }" in css
    assert "table.fmp-scn-table tr.fmp-scn-nopv.off:hover td { background: #000; }" in css
    assert "table.fmp-table tr.on td { background: #484848; }" in css and "table.fmp-table tr.off td { background: #000; }" in css
    # nagłówki grup i wiersz "brak" zostają z odstępami tabeli (bardziej szczegółowe reguły)
    assert "table.fmp-table tr.fmp-grp td { padding: 7px 12px 2px;" in css and "table.fmp-table tr.fmp-none td { padding: 2px 12px 2px 28px;" in css
    side_pad_top = int(re.search(r"\.fmp-side \{[^}]*padding: (\d+)px", css).group(1))
    assert f"table.fmp-sp-tab th {{ top: -{side_pad_top}px; }}" in css
    narrow = re.search(r"@container fmp \(max-width: (\d+)px\) \{ table\.fmp-sp-tab th \{ top: 0; \} \}", css)
    assert narrow and narrow.group(1) == re.search(r"@container fmp \(max-width: (\d+)px\) \{\n", css).group(1)
