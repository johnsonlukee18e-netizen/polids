"""RADIO jako jedna strona (runda 10): GET /api/radio/board, część stała z radioboard.py i czyste funkcje
frontend/js/radioboard.js (Node)."""
import itertools
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
from backend.app.services import radioboard as rb  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

FRONTEND = ROOT_DIR / "frontend"
FEED = {"general": {"update_timestamp": "2026-10-12T12:00:00Z"}, "pilots": [],
        "controllers": [
            {"callsign": "EPWW_N_CTR", "frequency": "130.675", "name": "Radar Północ", "cid": 11},
            {"callsign": "EPWA_APP", "frequency": "128.805", "name": "Okęcie", "cid": 12},
            {"callsign": "EDWW_FLG_CTR", "frequency": "136.450", "name": "Bremen", "cid": 13},
            {"callsign": "EPKK_OBS", "frequency": "199.998", "name": "Obserwator", "cid": 14}],
        "atis": [
            {"callsign": "EPWA_ATIS", "frequency": "120.455", "name": "Atis", "cid": 15, "atis_code": "K",
             "text_atis": ["WARSAW INFORMATION K"]},
            {"callsign": "EPWA_D_ATIS", "frequency": "121.130", "name": "Odloty", "cid": 16, "atis_code": "D"}]}
ONLINE = {"EPWW_N_CTR", "EPWA_APP", "EDWW_FLG_CTR"}


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    async def feed():
        return FEED

    async def no_metar(icaos):  # BERLIN bez ATIS: METAR z sieci (testy bez sieci)
        return {}

    async def no_tvs(prefix=None, now=None):  # czerwone tło: sektory vIFF z sieci
        return {"sectors": []}

    monkeypatch_module.setattr(vatsim_api, "get_feed", feed)
    monkeypatch_module.setattr(radio_router, "get_metars", no_metar)
    monkeypatch_module.setattr(radio_router, "viff_sectors", no_tvs)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="module")
def board(client):
    r = client.get("/api/radio/board")
    assert r.status_code == 200
    return r.json()


def test_board_sectors_and_owners(board):
    own = json.loads((ROOT_DIR / "data" / "seed" / "ownership.json").read_text("utf-8"))
    expected = {ly[0] + letter for letter, by in own["sectors"].items() for ly in ("LOW", "MID", "HIGH") if by.get(ly)}
    ids = [s["id"] for s in board["sectors"]]
    assert set(ids) == expected and len(ids) == len(expected) == 30
    assert all(re.fullmatch(r"[LMH][A-Z]", i) for i in ids)  # litera warstwy + litera sektora, bez numerów
    for s in board["sectors"]:
        assert s["nominal"] == s["chain"][0] and s["layer"][0] + s["letter"] == s["id"]
        # właściciel = pierwsze stanowisko kolejności, które jest online; nikt → null (strona: samo ID sektora)
        assert s["owner"] == next((cs for cs in s["chain"] if cs in ONLINE), None)
    by = {s["id"]: s for s in board["sectors"]}
    assert by["HB"]["owner"] == "EPWW_N_CTR"
    assert any(s["owner"] is None for s in board["sectors"])
    assert board["layers"]["LOW"]["lower_ft"] < board["layers"]["MID"]["lower_ft"] < board["layers"]["HIGH"]["lower_ft"]
    # częstotliwości wszystkich stanowisk z kolejności są w pos
    assert all(cs in board["pos"] for s in board["sectors"] for cs in s["chain"])
    assert board["pos"]["EPWW_N_CTR"]["frequency"] == "130.675"
    assert board["net"] == {"ok": True, "error": None, "updated": "2026-10-12T12:00:00Z"}
    assert "geo" not in board and "source" not in board  # bez opisu źródła kolejności (runda 15)


def test_board_overlays(board):
    tma = {g["id"]: g for g in board["tma"]}
    wa = "TMA Warszawa · EPWA_APP"
    # TMA Warszawa: APP online jako właściciel lokalny; TMA bez nikogo z APP: top-down ACC tylko w polu topdown
    assert tma[wa]["nominal"] == "EPWA_APP" and tma[wa]["owners"] == ["EPWA_APP"]
    assert tma[wa]["topdown"] is None
    assert all(not any(o.startswith("EPWW_") for o in g["owners"]) for g in board["tma"] + board["twr"] + board["fis"])
    assert any(g["topdown"] == "EPWW_N_CTR" for g in board["tma"])
    assert all(g["at"] and 48 < g["at"][0] < 56 and 13 < g["at"][1] < 25 for g in board["tma"] + board["twr"] + board["fis"])
    twr = {g["icao"]: g for g in board["twr"]}
    assert twr["EPWA"]["nominal"].startswith("EPWA_") and twr["EPWA"]["nominal"].endswith("TWR")
    assert twr["EPWA"]["atis"] == "EPWA_ATIS" and twr["EPKK"]["atis"] == "EPKK_ATIS"
    assert board["fis"] and all("FIS" in g["id"] for g in board["fis"])


def test_board_tma_parts(board):
    """Warstwa APP (runda 11, Marek): TMA podzielone na części wg stanowiska części (WA APP, WA N APP, WA S APP),
    TMA proceduralne z wieżą lotniska, EPRZ domyślnie KK RZ APP; dyrektor (WA DIR, KK DIR, KT DIR) nie jest częścią."""
    tma = {g["id"]: g for g in board["tma"]}
    assert len(tma) == len(board["tma"])  # id bez powtórek
    parts = {}
    for g in board["tma"]:
        parts.setdefault(g["tma"], []).append(g["nominal"])
        assert g["id"] == (g["tma"] if len([x for x in board["tma"] if x["tma"] == g["tma"]]) == 1
                           else f'{g["tma"]} · {g["nominal"]}')
        # punkt etykiety w ramce części, ramka [lon0, lat0, lon1, lat1]
        lon0, lat0, lon1, lat1 = g["box"]
        assert lat0 <= g["at"][0] <= lat1 and lon0 <= g["at"][1] <= lon1, g["id"]
        assert g["lo"] < g["hi"] and g["chains"] and g["nominal"] in g["chains"][0]
    assert sorted(parts["TMA Warszawa"]) == ["EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"]
    assert sorted(parts["TMA Kraków"]) == ["EPKK_APP", "EPKK_E_APP"]
    assert sorted(parts["TMA Gdańsk"]) == ["EPGD_APP", "EPGD_L_APP"]
    # każde APP z pliku ma swoją część albo należy do części (dyrektor: w jej kolejnościach, online – w "Now:")
    noms = {g["nominal"] for g in board["tma"]}
    assert {"EPPO_N_APP", "EPPO_S_APP", "EPKK_RZ_APP", "EPDE_APP"} <= noms
    assert not noms & {"EPWA_F_APP", "EPKK_KK_APP", "EPKK_KT_APP"}
    wa, kt = tma["TMA Warszawa · EPWA_APP"]["chains"], tma["TMA Katowice · EPKK_APP"]["chains"]
    assert any("EPWA_F_APP" in ch for ch in wa) and any("EPKK_KT_APP" in ch for ch in kt)
    # bez listy APP części do dymku (runda 15: bez kolejności przejmowania)
    assert all("apps" not in g for g in board["tma"])
    # TMA proceduralne: wieża lotniska, bez APP
    for key, cs in (("TMA Szczecin", "EPSC_TWR"), ("TMA Lublin", "EPLB_TWR"), ("TMA Olsztyn-Mazury", "EPSY_TWR")):
        assert tma[key]["nominal"] == cs and tma[key]["owners"] == [], key
        assert not any(rb.facility(c) in rb.APP_TYPES for ch in tma[key]["chains"] for c in rb._local(ch)), key
    # EPRZ: KK RZ APP, a po APP Krakowa wieża Rzeszów (kolejność z .ese)
    rz = tma["TMA Rzeszów"]
    assert rz["nominal"] == "EPKK_RZ_APP" and rz["icao"] == "EPRZ"
    ch = rz["chains"][0]
    assert ch.index("EPKK_RZ_APP") < ch.index("EPKK_APP") < ch.index("EPRZ_TWR")
    # WA APP online przejmuje WA N i WA S (części) oraz TMA Łódź i Radom
    for key in ("TMA Warszawa · EPWA_N_APP", "TMA Warszawa · EPWA_S_APP", "TMA Łódź", "TMA Radom"):
        assert tma[key]["owners"] == ["EPWA_APP"], key


def test_board_tma_parts_online(client, monkeypatch):
    """Inny zestaw online: sam WA N APP, wieża TMA proceduralnej, EPRZ_TWR bez APP Krakowa,
    UMMV_CTR obsługuje okienko ACC Mińska (kafelki UMMV N i W, kolejność z plików sektorów)."""
    feed = {**FEED, "controllers": [
        {"callsign": "EPWA_N_APP", "frequency": "125.055", "name": "N", "cid": 21},
        {"callsign": "EPSC_TWR", "frequency": "121.255", "name": "SC", "cid": 22},
        {"callsign": "EPRZ_TWR", "frequency": "126.805", "name": "RZ", "cid": 23},
        {"callsign": "UMMV_CTR", "frequency": "135.700", "name": "Minsk", "cid": 24}], "atis": []}

    async def other():
        return feed

    monkeypatch.setattr(vatsim_api, "get_feed", other)
    d = client.get("/api/radio/board").json()
    tma = {g["id"]: g for g in d["tma"]}
    # sam WA N APP przejmuje całą TMA Warszawa (WA APP › WA S › WA N w kolejności części WA APP)
    for part in ("EPWA_N_APP", "EPWA_APP", "EPWA_S_APP"):
        assert tma[f"TMA Warszawa · {part}"]["owners"] == ["EPWA_N_APP"], part
    assert tma["TMA Szczecin"]["owners"] == ["EPSC_TWR"]
    assert tma["TMA Rzeszów"]["owners"] == ["EPRZ_TWR"] and tma["TMA Rzeszów"]["nominal"] == "EPKK_RZ_APP"
    (ummv,) = next(f for f in d["firs"] if f["fir"] == "UMMV")["boxes"]
    assert (ummv["label"], ummv["owner"], ummv["frequency"]) == ("ACC", "UMMV_CTR", "135.700")
    assert {"UMMV_N_CTR", "UMMV_W_CTR"} <= set(ummv["chain"])
    # za UMMV_CTR to, co pliki sektorów stawiają za nim w UMMV N (RU-WRC_FSS)
    assert ummv["chain"][ummv["chain"].index("UMMV_CTR") + 1:], ummv["chain"]


def test_board_tma_director_online(client, monkeypatch):
    """Dyrektor online (WA DIR = EPWA_F_APP) jest w "Now:" swojej części TMA (owners), choć nie ma własnej części."""
    feed = {**FEED, "controllers": [
        {"callsign": "EPWA_APP", "frequency": "128.805", "name": "WA", "cid": 31},
        {"callsign": "EPWA_F_APP", "frequency": "129.380", "name": "DIR", "cid": 32}], "atis": []}

    async def other():
        return feed

    monkeypatch.setattr(vatsim_api, "get_feed", other)
    tma = {g["id"]: g for g in client.get("/api/radio/board").json()["tma"]}
    assert set(tma["TMA Warszawa · EPWA_APP"]["owners"]) == {"EPWA_APP", "EPWA_F_APP"}
    assert tma["TMA Warszawa · EPWA_N_APP"]["owners"] == ["EPWA_APP"]


def test_board_atis(board):
    atis = {a["callsign"]: a for a in board["atis"]}
    assert atis["EPWA_ATIS"]["online"] and not atis["EPKK_ATIS"]["online"]
    assert board["online"]["EPWA_ATIS"]["atis_code"] == "K"
    # zalogowany ATIS spoza pliku .ese też jest na pasku, z częstotliwością z sieci
    assert atis["EPWA_D_ATIS"]["extra"] and board["pos"]["EPWA_D_ATIS"]["frequency"] == "121.130"
    assert board["online"]["EPWA_D_ATIS"]["atis_code"] == "D"
    assert [a["icao"] for a in board["atis"]] == sorted(a["icao"] for a in board["atis"])
    assert "EPKK_OBS" not in board["online"]  # tylko stanowiska z tablicy


def test_board_neighbour_firs(board):
    """Okienka sąsiadów (0.13.0, szkic): FIR-y w kolejności z radio_layout.json (te same co rb.STACKS), okienka z kafelków profilu ACC_EPWW (sektory
    graniczące z EPWW) bez FMP; właściciel okienka = pierwsze stanowisko online z jego kolejności, nikt → null (strona:
    bez częstotliwości, ADVISORY). Stosów (`stacks`) już nie ma."""
    assert "stacks" not in board
    vacs = json.loads((ROOT_DIR / "data" / "seed" / "vacs_epww.json").read_text("utf-8"))["neighbours"]
    fmp = {n["label"] for n in vacs if n["fmp"]}
    lay = json.loads((ROOT_DIR / "data" / "seed" / "radio_layout.json").read_text("utf-8"))
    assert [f["fir"] for f in board["firs"]] == [f["fir"] for f in lay["firs"]]
    assert {f["fir"] for f in board["firs"]} == {s["fir"] for s in rb.STACKS}
    # 0.13.2 (issue #27): bez stron i miejsc stosów – każdy FIR stoi w komórkach szkicu (kod: name, miejsce na nazwę
    # i ADVISORY obok kodu: room, okienka: boxes)
    assert all(set(s) == {"fir", "title"} for s in rb.STACKS)
    assert all(set(f) == {"fir", "title", "name", "room", "merge", "staffed", "advisory", "online", "boxes"} for f in board["firs"])
    heads = {f["fir"]: (f["name"]["col"], f["name"]["row"], f["name"]["cols"]) for f in board["firs"]}
    assert heads == {"EDWW": (2, 4, 1), "EDUU": (3, 6, 1), "EDMM": (2, 14, 1), "ESAA": (5, 4, 2), "LKAA": (5, 18, 2),
                     "UMKK": (10, 4, 1), "LZBB": (10, 18, 1), "EYVL": (13, 3, 1), "UMMV": (13, 9, 1), "UKLV": (13, 15, 1)}
    lkaa = next(f for f in board["firs"] if f["fir"] == "LKAA")
    assert {(b["col"], b["row"]) for m in lkaa["boxes"] for b in m["members"]} == {(5, 19), (6, 19), (5, 20), (6, 20), (6, 21)}
    assert not any(t in fmp for f in lay["firs"] for b in f["boxes"] for t in b["tiles"])
    st = {f["fir"]: f for f in board["firs"]}
    for f in board["firs"]:
        assert f["boxes"] and f["title"], f["fir"]
        for b in f["boxes"]:
            assert b["owner"] is None or b["owner"] in ONLINE, (f["fir"], b["id"])
            if not b["merged"]:
                assert b["owner"] == next((cs for cs in b["chain"] if cs in ONLINE), None), (f["fir"], b["id"])
            assert (b["frequency"] is not None) == (b["owner"] is not None), (f["fir"], b["id"])
    edww = {b["id"]: b for b in st["EDWW"]["boxes"]}
    assert edww["FLG"]["owner"] == "EDWW_FLG_CTR" and edww["MRZ"]["owner"] is None
    assert edww["FLG"]["frequency"] == "136.450" and not st["EDWW"]["advisory"]
    # EDWW FLG obsługuje też HVL2 i HVL1 Rhein (jest w ich kolejności): jedno okienko na obu komórkach, nazwa ze
    # środka znaku właściciela (FLG); OSE nie
    eduu = {b["id"]: b for b in st["EDUU"]["boxes"]}
    hvl = eduu["HVL2+HVL1"]
    assert (hvl["label"], hvl["owner"], hvl["merged"], hvl["rows"]) == ("FLG", "EDWW_FLG_CTR", True, 2)
    assert [m["id"] for m in hvl["members"]] == ["HVL2", "HVL1"] and (hvl["upper"], hvl["lower"]) == (660, 285)
    assert eduu["OSE2"]["owner"] is None and not eduu["OSE2"]["merged"]
    # nikt z Wilna ani Pragi online: żadne okienko EYVL i LKAA nie ma właściciela (strona: ADVISORY)
    for fir in ("EYVL", "LKAA"):
        assert all(b["owner"] is None for b in st[fir]["boxes"]) and st[fir]["advisory"], fir
    # znaki z kolejności okienek są w pos (nazwa, częstotliwość) i w online, gdy ktoś jest zalogowany
    assert all(cs in board["pos"] for f in board["firs"] for b in f["boxes"] for cs in b["chain"])
    assert "EDWW_FLG_CTR" in board["online"]


def test_board_geo(client):
    """0.13.2 (issue #27, Marek: "mapy całe czarne"): geometria bez sąsiadów (bez sektorów ACC, TMA i CTR sąsiadów –
    granice FIR-ów sąsiadów zostają jako cienkie linie); kształty TMA/CTA, CTR i FIS FIR EPWW do granic stanowisk
    online (id, nazwa, geometria; TMA z kluczem TMA, CTR z grupą CTR), bez kolejności przejmowania."""
    d = client.get("/api/radio/board?geo=1").json()
    g = d["geo"]
    assert set(g) == {"border", "firs", "acc", "tma", "ctr", "fis"}
    assert g["border"]["type"] == "MultiPolygon" and g["border"]["coordinates"]
    assert {f["id"] for f in g["firs"]} >= {"EDWW", "EDMM", "LKAA", "LZBB", "UKLV", "UMMV", "EYVL", "UMKK", "ESAA"}
    assert all("-" not in f["id"] and f["id"] != "EPWW" for f in g["firs"])
    letters = {s["letter"] for s in d["sectors"]}
    assert {a["letter"] for a in g["acc"]} == letters
    assert all(a["lo"] < a["hi"] and a["geometry"]["coordinates"] and a["name"].startswith("EPWW") for a in g["acc"])
    for key, pre, extra in (("tma", "t", {"tma"}), ("ctr", "c", {"ctr"}), ("fis", "f", set())):
        assert g[key], key
        assert [a["id"] for a in g[key]] == [f"{pre}{i}" for i in range(len(g[key]))], key
        assert all(set(a) == {"id", "name", "geometry"} | extra and a["geometry"]["coordinates"] for a in g[key]), key
    assert {a["tma"] for a in g["tma"]} >= {"TMA Warszawa", "TMA Kraków", "TMA Gdańsk"}
    assert {a["ctr"] for a in g["ctr"]} == {t["id"] for t in d["twr"]}
    # nic z FIR-ów sąsiadów (TMA Ostrawy i Berlina, CTR sąsiadów, sektory sąsiadów: do 0.13.1 w geo.nb)
    names = [a["name"] for k in ("acc", "tma", "ctr", "fis") for a in g[k]]
    assert not any(n.startswith(("LK", "ED", "LZ", "UK", "UM", "EY", "ES")) for n in names)
    assert len(json.dumps(g)) < 400_000  # raz na sesję, ale bez przesady
    # geometria zakodowana raz (część stała) i wklejona do odpowiedzi: poza nią ta sama treść co bez geo=1
    r = client.get("/api/radio/board?geo=1")
    assert r.headers["content-type"] == "application/json" and r.json()["geo"] == g
    assert set(d) - {"geo"} == set(client.get("/api/radio/board").json())


def test_board_areas_and_page(client, board):
    """0.13.2 (issue #27): bez stanu obsady sąsiadów (nb); kto obsługuje kształty TMA/CTA i FIS (areas: stanowisko online
    → id kształtów, APP tylko stanowiska APP), skróty stanowisk ACC do plakietek (acc_short) i siatka strony (grid)."""
    assert "nb" not in board
    d = client.get("/api/radio/board?geo=1").json()
    tma = {a["id"]: a for a in d["geo"]["tma"]}
    app = board["areas"]["app"]
    # FEED: WA APP online – obsługuje części TMA Warszawa (wszystkie trzy), Łódź i Radom; nikt inny z APP
    assert set(app) == {"EPWA_APP"}
    assert {tma[i]["tma"] for i in app["EPWA_APP"]} >= {"TMA Warszawa", "TMA Łódź", "TMA Radom"}
    assert board["areas"]["fis"] == {}  # nikt z FIS online
    assert board["acc_short"]["EPWW_ALL_CTR"] == "ALL" and board["acc_short"]["EPWW_N_CTR"] == "N"
    grid = board["grid"]
    assert (grid["cols"], grid["rows"], grid["top"]) == (13, 21, 2)
    assert grid["tracks"] == ["box", "box", "box", "map", "box", "box", "map", "btn", "map", "box", "map", "box", "name"]
    assert grid["buttons"] == {"col": 8, "rows": {"atis": 5, "low": 6, "mid": 6, "high": 6, "app": 8, "twr": 10, "twra": 12, "fis": 14}}
    assert grid["maps"] == {"low": {"col": 4, "row": 8, "cols": 4, "rows": 10}, "high": {"col": 9, "row": 6, "cols": 3, "rows": 12},
                            "mid": {"col": 8, "row": 16, "cols": 1, "rows": 6}}
    assert grid["status"] == {"col": 8, "row": 15, "cols": 1, "rows": 1}
    assert grid["legend"] == {"col": 1, "row": 18, "cols": 3, "rows": 4}
    assert grid["berlin"] == {"col": 1, "row": 6, "cols": 1, "rows": 1, "box": {"col": 1, "row": 7, "cols": 2, "rows": 1}}


def test_board_fis_warszawa_information(client, monkeypatch):
    """0.13.2 (przegląd): informacja Warszawa (EPWW_I_CTR, EPWW_IE_CTR) ma znak jak sektor ACC, ale to stanowisko FIS –
    obsługuje obszary FIS (areas.fis: granica i plakietka na LOW z warstwą FIS), a nie znika z kolejności FIS jak
    sektory radarowe (dawniej areas.fis było puste, a na stronie nic nie mówiło, że ktoś obsługuje FIS)."""
    geo = {a["id"]: a["name"] for a in client.get("/api/radio/board?geo=1").json()["geo"]["fis"]}
    out = {}
    for name, css in (("i", ["EPWW_I_CTR"]), ("ie", ["EPWW_IE_CTR"]), ("both", ["EPWW_I_CTR", "EPWW_IE_CTR"])):
        feed = {**FEED, "controllers": [{"callsign": cs, "frequency": fq, "name": "Info", "cid": 70 + i}
                                        for i, (cs, fq) in enumerate(zip(css, ("128.325", "127.660")))], "atis": []}

        async def get(feed=feed):
            return feed

        monkeypatch.setattr(vatsim_api, "get_feed", get)
        out[name] = client.get("/api/radio/board").json()
    fis_i = out["i"]["areas"]["fis"]
    # EPWW_I_CTR w kolejności prawie wszystkich obszarów FIS (także EPWW-MIDSEA i Gdańsk), z sektorów radarowych nikt
    assert set(fis_i) == {"EPWW_I_CTR"} and len(fis_i["EPWW_I_CTR"]) >= 0.9 * len(geo) and "f0" in fis_i["EPWW_I_CTR"]
    assert out["i"]["areas"]["app"] == {} and all(g["owners"] == ["EPWW_I_CTR"] for g in out["i"]["fis"] if g["owners"])
    assert out["i"]["pos"]["EPWW_I_CTR"]["frequency"] and "EPWW_I_CTR" in out["i"]["online"]
    # EPWW_IE_CTR: obszary FIS Warszawa; obaj online – IE Warszawę, I resztę
    ie = out["ie"]["areas"]["fis"]["EPWW_IE_CTR"]
    assert ie and all(geo[i].startswith(("FIS_WAW", "WAW_FIS")) for i in ie)
    both = out["both"]["areas"]["fis"]
    assert set(both) == {"EPWW_I_CTR", "EPWW_IE_CTR"} and sorted(both["EPWW_IE_CTR"]) == sorted(ie)
    assert not set(both["EPWW_I_CTR"]) & set(ie)


def test_area_shapes_and_owners():
    """0.13.2: area_shapes – każdy kształt raz (ten sam na kilku wysokościach: jeden, z kolejnościami obu wycinków),
    id z prefiksem; area_owners – stanowisko → kształty, w których jest pierwsze online (keep: tylko APP)."""
    def sl(name, owners, x=18.0, lo=0):
        sq = [[[x, 50.0], [x + 0.2, 50.0], [x + 0.2, 50.2], [x, 50.2], [x, 50.0]]]
        return {"fir": "EPWW", "name": name, "lo": lo, "hi": lo + 2000, "owners": owners, "geom": {"type": "Polygon", "coordinates": sq}}

    shapes = rb.area_shapes([sl("A", ["EPWA_APP", "EPWW_N_CTR"]), sl("A", ["EPWA_N_APP", "EPWA_APP"], lo=2000),
                             sl("B", ["EPLL_TWR"], x=19.0)], "t", lambda s: s["owners"], tma=lambda s: "TMA " + s["name"])
    assert [(a["id"], a["name"], a["tma"]) for a in shapes] == [("t0", "A", "TMA A"), ("t1", "B", "TMA B")]
    assert shapes[0]["chains"] == [["EPWA_APP", "EPWW_N_CTR"], ["EPWA_N_APP", "EPWA_APP"]]
    on = {"EPWA_N_APP": {}, "EPWA_APP": {}, "EPLL_TWR": {}}
    assert rb.area_owners(shapes, on) == {"EPWA_APP": ["t0"], "EPWA_N_APP": ["t0"], "EPLL_TWR": ["t1"]}
    app = rb.area_owners(shapes, on, lambda cs: rb.facility(cs) in rb.APP_TYPES)
    assert app == {"EPWA_APP": ["t0"], "EPWA_N_APP": ["t0"]}
    assert rb.area_owners(shapes, {}) == {}


def test_board_version_and_reimport(client):
    """Import kasuje tabelę sektorów i wstawia ją od nowa (te same id): część stała i geometria muszą się odświeżyć,
    a strona dostaje nową wersję (`ver`) i nową geometrię przy `have=<stara wersja>`."""
    from sqlalchemy import delete, select

    from backend.app.database import SessionLocal
    from backend.app.models import Sector

    d1 = client.get("/api/radio/board").json()
    ver = d1["ver"]
    assert ver and "geo" not in d1
    assert "geo" not in client.get(f"/api/radio/board?have={ver}").json()  # ta sama wersja: bez geometrii
    with SessionLocal() as db:
        cols = [c.name for c in Sector.__table__.columns if c.name != "id"]
        rows = [{c: getattr(s, c) for c in cols} for s in db.scalars(select(Sector).order_by(Sector.id))]
        target = next(r for r in rows if r["fir"] == "EPWW" and r["name"].startswith("EPWWB"))
        old_geom = target["geometry"]
        try:
            db.execute(delete(Sector))
            for r in rows:
                db.add(Sector(**{**r, "geometry": '{"type":"Polygon","coordinates":[[[16,52],[17,52],[17,53],[16,52]]]}'
                                 if r is target else r["geometry"]}))
            db.commit()
            d2 = client.get(f"/api/radio/board?have={ver}").json()
            assert d2["ver"] != ver and "geo" in d2
            geo_b = [a["geometry"] for a in d2["geo"]["acc"] if a["name"] == target["name"]]
            assert geo_b and geo_b[0]["coordinates"][0][0][0] == [16, 52]
        finally:
            db.execute(delete(Sector))
            for r in rows:
                db.add(Sector(**r))
            db.commit()
    d3 = client.get(f"/api/radio/board?have={d2['ver']}").json()
    assert d3["ver"] == ver and "geo" in d3 and old_geom


def test_board_upstream_error(client, monkeypatch):
    async def broken():
        raise UpstreamError("timeout")

    monkeypatch.setattr(vatsim_api, "get_feed", broken)
    r = client.get("/api/radio/board")
    assert r.status_code == 200
    d = r.json()
    # komunikat bez nazwy dostawcy danych i bez szczegółów błędu (runda 15)
    assert d["net"]["ok"] is False and d["net"]["error"] == "Network data unavailable"
    assert all(s["owner"] is None for s in d["sectors"]) and d["online"] == {}
    assert all(b["owner"] is None and not b["staffed"] for f in d["firs"] for b in f["boxes"])
    assert not any(f["advisory"] for f in d["firs"]) and "stacks" not in d
    assert len(d["sectors"]) == 30 and all(a["online"] is False for a in d["atis"])


def test_existing_radio_endpoints_kept(client):
    for path in ("/api/radio/positions", "/api/radio/online", "/api/radio/sectors", "/api/radio/loa"):
        assert client.get(path).status_code == 200, path


def test_every_loa_has_a_fir(client, board):
    """Panel LOA otwiera się z żółtej nazwy FIR-u sąsiada: każde LOA z loa.json ma swoją nazwę na stronie RADIO
    (UMKK i UMMV bez LOA: panel mówi, że go nie ma)."""
    loa = client.get("/api/radio/loa").json()["firs"]
    firs = {f["fir"] for f in board["firs"]}
    assert set(loa) <= firs and firs - set(loa) == {"UMKK", "UMMV"}
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    assert 'api("/api/radio/loa")' in radio and 'navigate("coordination", "docs/"' in radio


# --- czyste funkcje radioboard.py
OWN = {"tma_topdown": {"TMA Test": {"ese_prefixes": ["EPXX_TMA"], "chain": ["EPWW_A_CTR", "EPWW_B_CTR"]}}}


def test_air_chain():
    # lokalne przed pierwszym ACC, potem ACC z tabeli top-down (gdy prefiks pasuje), potem reszta z pliku
    assert rb.air_chain("EPXX_TMA_1", ["EPXX_APP", "EPWW_C_CTR", "EPYY_APP"], OWN) == \
        ["EPXX_APP", "EPWW_A_CTR", "EPWW_B_CTR", "EPYY_APP"]
    assert rb.air_chain("EPZZ_CTR", ["EPZZ_TWR", "EPZZ_APP", "EPWW_C_CTR", "EPWW_C_CTR"], OWN) == \
        ["EPZZ_TWR", "EPZZ_APP", "EPWW_C_CTR"]
    assert rb.air_chain("X", ["", "EPXX_TWR"], {}) == ["EPXX_TWR"]


def test_first_online_and_owners():
    on = {"EPWA_ATIS": {}, "EPWA_APP": {}, "EPWW_N_CTR": {}}
    assert rb.first_online(["EPWA_ATIS", "EPWA_TWR", "EPWA_APP"], on) == "EPWA_APP"  # ATIS nie przejmuje
    assert rb.first_online(["EPKK_APP"], on) is None
    chains = [["EPWW_N_CTR"], ["EPKK_APP", "EPWA_APP"], ["EPWA_APP"], ["EPKK_APP"]]
    assert rb.owners_of_chains(chains, on) == ["EPWA_APP", "EPWW_N_CTR"]


def test_acc_sectors():
    assert rb.acc_sectors({"sectors": {"B": {"LOW": ["EPWW_N_CTR"], "HIGH": ["EPWW_C_CTR", "EPWW_N_CTR"]}}}) == [
        {"id": "LB", "letter": "B", "layer": "LOW", "chain": ["EPWW_N_CTR"], "nominal": "EPWW_N_CTR"},
        {"id": "HB", "letter": "B", "layer": "HIGH", "chain": ["EPWW_C_CTR", "EPWW_N_CTR"], "nominal": "EPWW_C_CTR"}]


def test_alt_range_and_stack_key():
    assert rb.alt_range("+365") == (36500, rb.TOP_FT) and rb.alt_range("-165") == (0, 16500)
    assert rb.alt_range("285-365") == (28500, 36500) and rb.alt_range(" 95-125 ") == (9500, 12500)
    assert rb.alt_range(None) is None and rb.alt_range("") is None and rb.alt_range("FL365") is None
    assert [rb.stack_key(x) for x in ("EYVL U", "EDDB N APP", "ESMM L", "LKMT APP", "UMBB TWR", "UKR CTR", "LZTT TWR",
                                      "EDUU OSE22", "EDMM SAS", "EKDK X", "", None)] == [
        "EYVL", "EDWW", "ESAA", "LKAA", "UMMV", "UKLV", "LZBB", "EDUU", "EDMM", None, None, None]


def test_stack_tiles():
    def n(label, alt, by, fmp=False, cs=None):
        return {"label": label, "alt": alt, "station": label, "controlled_by": by, "callsign": cs or (by[0] if by else None),
                "fmp": fmp}

    items = [n("EYVL FMP", None, [], fmp=True), n("EYVL E", "-225", ["EYVL_E_CTR", "EYVL_CTR"]),
             n("EYVL U", "+365", ["EYVL_U_CTR", "EYVL_CTR"]), n("EYVL U", "+365", ["EYVL_U_CTR", "EYVL_CTR"]),
             n("UKLL APP", None, ["UKLL_APP"]), n("UKLV", None, [], cs="UKLV_CTR"), n("EKDK X", None, ["EKDK_CTR"]),
             n("EYVL M", "335-365", ["EYVL_M_CTR", "EYVL_CTR"]), n("UMKK TMU", None, ["UMKK_TMU"], fmp=True), "x"]
    out = rb.stack_tiles(items)
    assert set(out) == {"EYVL", "UKLV"}  # FMP/TMU i FIR-y bez stosu pominięte
    assert [t["label"] for t in out["EYVL"]] == ["EYVL U", "EYVL M", "EYVL E"]  # od najwyższego, bez powtórek
    assert out["EYVL"][0] == {"label": "EYVL U", "alt": "+365", "lo": 36500, "hi": rb.TOP_FT, "callsign": "EYVL_U_CTR",
                              "chain": ["EYVL_U_CTR", "EYVL_CTR"]}
    # bez wysokości: CTR przed APP; pusta kolejność = samo stanowisko kafelka
    assert [(t["label"], t["chain"], t["lo"]) for t in out["UKLV"]] == [("UKLV", ["UKLV_CTR"], None),
                                                                       ("UKLL APP", ["UKLL_APP"], None)]
    assert rb.stack_tiles(None) == {}


def test_tma_parts_helpers():
    sl = [{"name": "EPWA_DIR11_A", "chain": ["EPWA_F_APP", "EPWA_APP", "EPWW_C_CTR"]},
          {"name": "EPWAN_TMA", "chain": ["EPWA_N_APP", "EPWA_APP", "EPWW_C_CTR"]},
          {"name": "EPWA_TMA", "chain": ["EPWA_I_APP", "EPWA_APP", "EPWW_C_CTR"]},
          {"name": "EPSC_TMA", "chain": ["EPSC_TWR", "EPWW_DBT_CTR"]},
          {"name": "EPKK_DIR07", "chain": ["EPKK_KK_APP", "EPKK_APP"]}, {"name": "EPKK_TMA", "chain": ["EPKK_KK_APP", "EPKK_APP"]}]
    # dyrektor: pierwszy tylko w wycinkach EPxx_DIRnn (KK_KK_APP jest też pierwszy w zwykłym wycinku → nie dyrektor)
    dirs = rb.directors(sl)
    assert dirs == {"EPWA_F_APP"}
    assert [rb.part_owner(s["chain"], dirs) for s in sl] == ["EPWA_APP", "EPWA_N_APP", "EPWA_APP", "EPSC_TWR",
                                                              "EPKK_KK_APP", "EPKK_KK_APP"]
    assert rb.part_owner(["EPWW_C_CTR"], dirs) is None
    # punkt etykiety części: w jej własnym obszarze (bez miejsca, które zajmuje druga część), z dala od krawędzi
    own = [{"geom": _sq(20, 52, 21, 53)}]
    other = [{"geom": _sq(20, 52, 20.5, 53)}]
    lat, lon = rb.part_anchor(own, other)
    assert 52.3 < lat < 52.7 and 20.6 < lon < 20.9
    lat, lon = rb.part_anchor(own, [])
    assert 52.4 < lat < 52.6 and 20.4 < lon < 20.6
    assert rb.part_anchor([], []) is None


def test_neighbour_tile_chains():
    """Kafelki VACS bez CTR w controlled_by (UMMV N/W, UKLV, EDDB APP): dalej lista OWNER z .ese wycinka stanowiska
    albo główny CTR FIR-u; kolejność VACS zostaje pierwsza."""
    ese = rb.first_chains([["UMMV_W_CTR", "UMMV_CTR"], ["UMMV_W_CTR", "UMMV_CTR"], ["UMMV_W_CTR", "UMBB_APP"],
                           ["EDDB_N_APP", "EDDB_S_APP", "EDWW_FLG_CTR", "EDWW_CTR"], ["", "X_CTR"], []])
    assert ese == {"UMMV_W_CTR": ["UMMV_W_CTR", "UMMV_CTR"], "EDDB_N_APP": ["EDDB_N_APP", "EDDB_S_APP", "EDWW_FLG_CTR",
                                                                           "EDWW_CTR"], "X_CTR": ["X_CTR"]}
    assert rb.tile_chain(["UMMV_W_CTR"], "UMMV_W_CTR", ese, "UMMV_CTR") == ["UMMV_W_CTR", "UMMV_CTR"]
    assert rb.tile_chain(["EDDB_N_APP", "EDDB_S_APP"], "EDDB_N_APP", ese, None) == [
        "EDDB_N_APP", "EDDB_S_APP", "EDWW_FLG_CTR", "EDWW_CTR"]
    # bez wycinka w .ese: APP/TWR przejmuje główny CTR, CTR bez niczego zostaje sam
    assert rb.tile_chain(["UKLL_APP"], "UKLL_APP", {}, "UKLV_CTR") == ["UKLL_APP", "UKLV_CTR"]
    assert rb.tile_chain(["UKR_CTR"], "UKR_CTR", {}, "UKLV_CTR") == ["UKR_CTR"]
    # controlled_by z innym CTR: bez zmian
    assert rb.tile_chain(["EYVL_U_CTR", "EYVL_CTR"], "EYVL_U_CTR", ese, "EYVL_CTR") == ["EYVL_U_CTR", "EYVL_CTR"]
    out = rb.stack_tiles([{"label": "UMMV W", "alt": None, "controlled_by": ["UMMV_W_CTR"], "callsign": "UMMV_W_CTR"},
                          {"label": "UMBB TWR", "alt": None, "controlled_by": ["UMBB_TWR"], "callsign": "UMBB_TWR"}],
                         ese, {"UMMV_CTR"})
    assert [t["chain"] for t in out["UMMV"]] == [["UMMV_W_CTR", "UMMV_CTR"], ["UMBB_TWR", "UMMV_CTR"]]
    # top-down dalej niż do głównego CTR: ogon list OWNER za stanowiskiem (UMMV_CTR → RU-WRC_FSS z wycinka UMMV N,
    # choć w wycinkach UMMV W jest ostatni); bez CTR innych stosów (UKR_CTR → LZBB_CTR z jednego wycinka przy granicy)
    nb = [["UMMV_W_CTR", "UMMV_CTR"]] * 5 + [["UMMV_N_CTR", "UMMV_CTR", "RU-WRC_FSS"], ["UMBB_TWR", "UMMV_CTR"],
                                            ["UKLV_CTR", "UKR_CTR"], ["UKLU_TWR", "UKLV_CTR", "UKR_CTR", "LZBB_CTR"]]
    ese, tails = rb.first_chains(nb), rb.chain_tails(nb)
    assert tails["UMMV_CTR"] == ["RU-WRC_FSS"] and tails["UMMV_W_CTR"] == ["UMMV_CTR"] and "RU-WRC_FSS" not in tails
    assert tails["UKR_CTR"] == ["LZBB_CTR"]
    vacs = [{"label": lb, "alt": None, "controlled_by": [cs], "callsign": cs}
            for lb, cs in (("UMMV N", "UMMV_N_CTR"), ("UMMV W", "UMMV_W_CTR"), ("UMBB TWR", "UMBB_TWR"), ("UMMV", "UMMV_CTR"),
                           ("UKR CTR", "UKR_CTR"), ("UKLV", "UKLV_CTR"))]
    out = rb.stack_tiles(vacs, ese, {"UMMV_CTR", "UKLV_CTR"}, tails)
    assert {t["label"]: t["chain"] for t in out["UMMV"]} == {
        "UMMV N": ["UMMV_N_CTR", "UMMV_CTR", "RU-WRC_FSS"], "UMMV W": ["UMMV_W_CTR", "UMMV_CTR", "RU-WRC_FSS"],
        "UMBB TWR": ["UMBB_TWR", "UMMV_CTR", "RU-WRC_FSS"], "UMMV": ["UMMV_CTR", "RU-WRC_FSS"]}
    assert {t["label"]: t["chain"] for t in out["UKLV"]} == {"UKR CTR": ["UKR_CTR"], "UKLV": ["UKLV_CTR", "UKR_CTR"]}
    # VACS z innym CTR i bez głównego CTR na końcu: bez zmian (EDMM MEI › GER › HOF nie idzie dalej ogonem HOF)
    assert rb.tile_chain(["EDMM_MEI_CTR", "EDMM_GER_CTR", "EDMM_HOF_CTR"], "EDMM_MEI_CTR", {}, None,
                         {"EDMM_HOF_CTR": ["EDMM_RDG_CTR"]}, "EDMM") == ["EDMM_MEI_CTR", "EDMM_GER_CTR", "EDMM_HOF_CTR"]


def _sq(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def test_label_point_simplify():
    # punkt etykiety w wielokącie wklęsłym (L) leży w środku, z dala od krawędzi
    ell = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4], [0, 0]]]}
    lat, lon = rb.label_point(ell)
    assert 0 < lon < 4 and 0 < lat < 4 and (lon < 1 or lat < 1)
    assert rb.label_point({"type": "Point", "coordinates": [1, 2]}) is None
    wiggly = {"type": "Polygon", "coordinates": [[[i / 100, 0.0001 * (i % 2)] for i in range(101)] + [[1, 1], [0, 1]]]}
    s = rb.simplify(wiggly, 0.003, 3)
    assert s["type"] == "MultiPolygon" and len(s["coordinates"][0][0]) < 10
    assert rb.geom_area(_sq(0, 0, 2, 1)) == pytest.approx(2.0)


# --- frontend: radioboard.js (Node) i porządki po starym RADIO
NODE_SCRIPT = r"""
const rb = await import(process.argv[2]);
const L = (a) => new Set(a);
const items = Array.from({ length: 12 }, (_, i) => ({ x: 100 + (i % 3) * 4, y: 100 + Math.floor(i / 3) * 3, w: 60, h: 20 }));
const moves = rb.placeLabels(items, { x: 0, y: 0, w: 400, h: 400 });
const rects = items.map((it, i) => [it.x + moves[i].dx - it.w / 2, it.y + moves[i].dy - it.h / 2, it.w, it.h]);
let overlaps = 0;
rects.forEach((a, i) => rects.slice(i + 1).forEach((b) => {
  if (a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3]) overlaps++;
}));
// przeszkody (tytuł podglądu) i mniejsze odmiany etykiet, gdy pełna nie mieści się przy punkcie
const obst = { x0: 0, y0: 0, x1: 90, y1: 400 };
const crowd = Array.from({ length: 20 }, (_, i) => ({ x: 120 + (i % 4) * 3, y: 150 + Math.floor(i / 4) * 3, w: 70, h: 24,
  alts: [{ w: 50, h: 12 }, { w: 16, h: 10 }] }));
const cm = rb.placeLabels(crowd, { x: 0, y: 0, w: 400, h: 400 }, { obstacles: [obst] });
const crects = crowd.map((it, i) => {
  const s = cm[i].v ? it.alts[cm[i].v - 1] : it;
  return { x0: it.x + cm[i].dx - s.w / 2, y0: it.y + cm[i].dy - s.h / 2, x1: it.x + cm[i].dx + s.w / 2, y1: it.y + cm[i].dy + s.h / 2 };
});
const hit = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
let crowdOverlaps = 0;
crects.forEach((a, i) => crects.slice(i + 1).forEach((b) => { if (hit(a, b)) crowdOverlaps++; }));
const pj = rb.projection([14, 49, 24, 55], { x: 10, y: 20, w: 300, h: 300 });
console.log(JSON.stringify({
  ids: rb.LAYER_IDS, labels: rb.LAYERS.map((l) => l.label), defaults: rb.DEFAULT_LAYERS, levels: rb.LEVEL_FT,
  gone: ["DEFAULT_CUT", "cutAt", "cutRange", "cutBand", "cutBounds", "CUT_STEP"].filter((k) => k in rb),
  args: [rb.argOf(L(["high", "atis", "low", "mid"])), rb.argOf(L([])), rb.argOf(L(["fis", "xx", "twra"]))],
  parsed: ["atis,low,mid,high/fl300", "none/fl250", "app,bogus", "", "bogus/flx", "twr/FL95", "atis,low,mid,high"].map((a) => {
    const p = rb.parseArg(a); return { layers: p.layers ? [...p.layers] : null, keys: Object.keys(p) };
  }),
  fl: [rb.flNum(29500), rb.flText(9500), rb.flText(0)],
  sliceAt: rb.sliceAt([{ lo: 0, hi: 100 }, { lo: 100, hi: 200 }], 100),
  // plakietki bez linii prowadzących (0.13.2): ta sama gromada jak wyżej, lines: false – bez nakładania się, lekko
  // odsunięte (najwyżej max × STRETCH od punktu)
  plates: (() => {
    const its = Array.from({ length: 6 }, (_, i) => ({ x: 150 + (i % 2) * 6, y: 150 + Math.floor(i / 2) * 4, w: 70, h: 29, ...rb.labelOpts("acc") }));
    const ms = rb.placeLabels(its, { x: 0, y: 0, w: 400, h: 400 }, { lines: false });
    const rs = its.map((it, i) => ({ x0: it.x + ms[i].dx - 35, y0: it.y + ms[i].dy - 14.5, x1: it.x + ms[i].dx + 35, y1: it.y + ms[i].dy + 14.5 }));
    let ov = 0;
    rs.forEach((a, i) => rs.slice(i + 1).forEach((b) => { if (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) ov++; }));
    const far = Math.max(...its.map((it, i) => Math.hypot(Math.max(0, Math.abs(ms[i].dx) - 35), Math.max(0, Math.abs(ms[i].dy) - 14.5))));
    return { ov, far, hits: ms.filter((m) => m.hit).length, first: ms[0], opts: ["acc", "app", "twr", "fis"].map(rb.labelOpts) };
  })(),
  // nazwa plakietki ACC (0.13.2): jeden sektor warstwy – litera i warstwa, kilka – skrót stanowiska, bez skrótu – nazwa
  accNames: [
    [{ owner: "EPWW_DBT_CTR", sectors: [{ letter: "B" }] }, "LOW"],
    [{ owner: "EPWW_N_CTR", sectors: [{ letter: "B" }, { letter: "C" }] }, "HIGH"],
    [{ owner: "EPWW_ALL_CTR", sectors: [{ letter: "B" }, { letter: "C" }, { letter: "D" }] }, "MID"],
    [{ owner: "EPWW_X_CTR", sectors: [{ letter: "B" }, { letter: "C" }] }, "LOW"],
  ].map(([g, k]) => rb.accPlateName(g, k, { EPWW_N_CTR: "N", EPWW_ALL_CTR: "ALL", EPWW_DBT_CTR: "DBT" }, (cs) => `name ${cs}`)),
  // siatka strony wg szkicu (0.13.2): tory kolumn z grid.tracks, wiersze szkicu po dwa tory (liczby, kafelek)
  page: (() => {
    const grid = { cols: 4, rows: 6, top: 2, tracks: ["box", "map", "btn", "name"] };
    const B = (id, col, row, upper, lower) => ({ id, col, row, cols: 1, rows: 1, upper, lower });
    const firs = [{ fir: "A", boxes: [B("A1", 1, 3, 660, 365), B("A2", 1, 4, 285, 0)] }, { fir: "B", boxes: [B("B1", 4, 5, 999, 0)] }];
    const pg = rb.pageGrid(grid, firs);
    return { cols: pg.cols, rows: pg.rows, top: pg.top,
      tiles: pg.stacks.map((s) => s.g.tiles.map((t) => [t.b.id, t.gc, t.gr])), marks: pg.stacks.map((s) => s.g.marks.map((k) => [k.gc, k.gr, k.at, ...k.n])),
      tracks: [3, 4, 6].map((r) => [rb.levelTrack(r, 2), rb.tileTrack(r, 2)]),
      areas: [rb.cellArea({ col: 4, row: 8, cols: 4, rows: 10 }, 2), rb.cellArea({ col: 8, row: 15 }, 2, { above: 1, below: 1 }),
        rb.cellArea({ col: 1, row: 3 }, 2, { above: 3 })],
      empty: rb.pageGrid({ cols: 2, rows: 3, top: 2 }, null) };
  })(),
  overlaps, first: moves[0],
  cover: (() => {
    // obrys CTR 20×20 px wokół punktu (100, 100): etykieta 30×10 odchodzi poza obrys, z kształtem tylko liczonym
    const ring = [[90, 90], [110, 90], [110, 110], [90, 110]];
    const gr = rb.coverGrid([ring], 300, 300, { points: [[200, 200]] });
    const it = { x: 100, y: 100, w: 30, h: 10 };
    const [m] = rb.placeLabels([it], { x: 0, y: 0, w: 300, h: 300 }, { cover: gr, near: 40 });
    const [m0] = rb.placeLabels([it], { x: 0, y: 0, w: 300, h: 300 });
    const r = { x0: 100 + m.dx - 15, y0: 100 + m.dy - 5, x1: 100 + m.dx + 15, y1: 100 + m.dy + 5 };
    // obsadzona (wv) zostaje pełna, gdy nieobsadzona przy tym samym tłoku traci częstotliwość
    const lines = Array.from({ length: 10 }, (_, i) => [[10, 2 + 32 * i], [290, 2 + 32 * i]]);  // pełna zawsze na linii
    const sq = (wv) => rb.placeLabels([{ x: 150, y: 50, w: 40, h: 30, alts: [{ w: 30, h: 12 }, { w: 12, h: 12 }], wv, max: 60 }],
      { x: 0, y: 0, w: 300, h: 300 }, { cover: rb.coverGrid(lines, 300, 300) })[0].v;
    // etykieta bez pin (sektor ACC, FIS) też nie staje na kropce lotniska ani TMA, choć jej punkt leży tuż obok
    const pinned = rb.placeLabels([{ x: 150, y: 150, w: 20, h: 8, pin: true }, { x: 152, y: 150, w: 30, h: 10, max: 70 }],
      { x: 0, y: 0, w: 300, h: 300 })[1];
    const onDot = Math.abs(152 + pinned.dx - 150) < 15 + 3 && Math.abs(150 + pinned.dy - 150) < 5 + 3;
    return { m, m0, inner: rb.coverOf(gr, { x0: 95, y0: 95, x1: 105, y1: 105 }), edge: rb.coverOf(gr, { x0: 80, y0: 95, x1: 100, y1: 105 }),
      point: rb.coverOf(gr, { x0: 195, y0: 195, x1: 205, y1: 205 }), none: rb.coverOf(null, r),
      clear: rb.coverOf(gr, r), v: [sq(1), sq(4)], onDot, pinned };
  })(),
  crowd: { overlaps: crowdOverlaps, onObstacle: crects.filter((r) => hit(r, obst)).length, hits: cm.filter((m) => m.hit).length,
    variants: [...new Set(cm.map((m) => m.v))].sort(), first: cm[0] },
  hhmm: ["2026-10-12T12:00:43.0000000Z", "2026-10-12T09:05:00Z", "not a date", null].map(rb.utcHhmm),
  counted: rb.controllersOn({ EPWW_N_CTR: { callsign: "EPWW_N_CTR" }, EKDK_UN_CTR: { callsign: "EKDK_CTR", alias_of: "EKDK_CTR" },
    EKDK_CTR: { callsign: "EKDK_CTR" }, EPWA_ATIS: { callsign: "EPWA_ATIS" }, EPWA_APP: { callsign: "EPWA_APP" } }),
  bboxes: [rb.bboxOrDefault(rb.bboxOf({ type: "MultiPolygon", coordinates: [] })), rb.bboxOrDefault([14, 49, 24, 55]), rb.EPWW_BBOX],
  advisory: rb.ADVISORY_FQ,
  // stos okienek sąsiada (0.13.1): kolumny i wiersze szkicu, wysokości między kafelkami (stackGrid)
  stacks: (() => {
    const B = (id, col, row, upper, lower, o = {}) => ({ id, col, row, cols: 1, rows: 1, upper, lower, ...o });
    const sg = (f) => { const g = rb.stackGrid(f);
      return { ...g, tiles: g.tiles.map((t) => [t.b.id, t.gc, t.gr]), marks: g.marks.map((x) => [x.gc, x.gr, ...x.n]), at: g.marks.map((x) => x.at) }; };
    const eduu = [B("OSE2", 3, 7, 660, 365), B("OSE1", 3, 8, 365, 285), B("HVL2", 3, 11, 660, 365), B("HVL1", 3, 12, 365, 285)];
    const lkaa = [B("NU", 5, 19, 660, 305), B("SU", 6, 19, 660, 305), B("NL", 5, 20, 305, 125), B("SL", 6, 20, 305, 125),
      B("MT", 6, 21, 125, 0)];
    return {
      edww: sg({ cols: [2], rows: [5, 9, 11], boxes: [B("MRZ", 2, 5, 285, 0), B("MAR", 2, 9, 285, 0), B("FLG", 2, 11, 285, 0)] }),
      eduu: sg({ cols: [3], rows: [7, 8, 11, 12], boxes: eduu }),
      // jedno stanowisko w ciągu okienek EDUU (EDUU_H12_CTR we wszystkich czterech; OSE1 + HVL2 i ciągi z nimi): połączone
      // okienko jak z merge_boxes – prostokąt przez puste wiersze szkicu 9 i 10, granice od najwyższej do najniższej
      eduuMerged: [[0, 1, 2, 3], [1, 2], [0, 1, 2], [1, 2, 3]].map((ix) => {
        const ms = ix.map((i) => eduu[i]), r0 = ms[0].row, r1 = ms[ms.length - 1].row;
        const mg = B(ms.map((b) => b.id).join("+"), 3, r0, Math.max(...ms.map((b) => b.upper)), Math.min(...ms.map((b) => b.lower)),
          { rows: r1 - r0 + 1, merged: true, members: ms });
        return sg({ cols: [3], rows: [7, 8, 11, 12], boxes: [...eduu.filter((b) => b.row < r0), mg, ...eduu.filter((b) => b.row > r1)] });
      }),
      // HVL2 + HVL1 jednego stanowiska: jedno okienko na dwa wiersze, rozmiar stosu bez zmian
      hvl: sg({ cols: [3], rows: [7, 8, 11, 12], boxes: [eduu[0], eduu[1],
        B("HVL2+HVL1", 3, 11, 660, 285, { rows: 2, merged: true, members: [eduu[2], eduu[3]] })] }),
      esaa: sg({ cols: [5, 6], rows: [5, 6], boxes: [B("9", 5, 5, 660, 365), B("6", 6, 5, 660, 365), B("8", 5, 6, 365, 195),
        B("7", 6, 6, 365, 0)] }),
      // LKAA_CTR wszędzie: prostokąt 2 × 3 (z pustą komórką pod NL), wysokość rzędów liczb jak bez łączenia
      lkaa: sg({ cols: [5, 6], rows: [19, 20, 21], boxes: [B("LKAA", 5, 19, 660, 0, { cols: 2, rows: 3, merged: true, members: lkaa })] }),
      lkaa0: sg({ cols: [5, 6], rows: [19, 20, 21], boxes: lkaa }),
      edmm: sg({ cols: [2, 3], rows: [15], boxes: [B("MEI", 2, 15, 315, 165), B("SPE1", 3, 15, 660, 315)] }),
      // 0.13.2 (przegląd): połączone okienko na dwie kolumny – w drugiej kolumnie granica jej członka, gdy inna niż obok
      // (ESMM_7_CTR na 9+6+8+7 nad L: 0 pod 7; EDMM MEI+SPE1 nad SAS: 660 nad SPE1 i 315 pod nim)
      esaaL: (() => {
        const e = [B("9", 5, 5, 660, 365), B("6", 6, 5, 660, 365), B("8", 5, 6, 365, 195), B("7", 6, 6, 365, 0)], L = B("L", 5, 7, 195, 0);
        return [sg({ cols: [5, 6], rows: [5, 6, 7], boxes: [...e, L] }),
          sg({ cols: [5, 6], rows: [5, 6, 7], boxes: [B("7", 5, 5, 660, 0, { cols: 2, rows: 2, merged: true, members: e }), L] })];
      })(),
      edmmSas: (() => {
        const e = [B("MEI", 2, 15, 315, 165), B("SPE1", 3, 15, 660, 315)], sas = B("SAS", 2, 16, 165, 0);
        return [sg({ cols: [2, 3], rows: [15, 16], boxes: [...e, sas] }),
          sg({ cols: [2, 3], rows: [15, 16], boxes: [B("MEI", 2, 15, 660, 165, { cols: 2, merged: true, members: e }), sas] })];
      })(),
      lkaaNs: sg({ cols: [5, 6], rows: [19, 20, 21], boxes: [B("NU", 5, 19, 660, 305, { cols: 2, merged: true, members: lkaa.slice(0, 2) }),
        ...lkaa.slice(2)] }),
      // bez cols/rows z /api/radio/board (stara część stała): z okienek; złe wartości → 1
      fallback: sg({ boxes: [{ id: "A", col: 1, row: 1, upper: 200, lower: 100 }, { id: "B", col: "1", row: 3, upper: 100, lower: 0 },
        { id: "C", col: -4, row: "x", upper: 50, lower: 0 }] }),
      empty: [sg({ boxes: [] }), sg(null)],
    };
  })(),
  // granice okienka jak na szkicu (górna-dolna; połączone – suma granic); dymek: od dolnej do górnej
  limText: [{ upper: 660, lower: 365 }, { upper: 999, lower: 0 }, { upper: 660, lower: 95 }, null].map(rb.limText),
  limTip: [{ upper: 660, lower: 365 }, { upper: 999, lower: 0 }, { upper: 285, lower: 0 }, { upper: 125, lower: 55 }].map(rb.limTip),
  proj: { a: pj.P([14, 55]), b: pj.P([24, 49]), box: pj.box },
  bottom: rb.projection([0, 0, 1, 1], { x: 0, y: 0, w: 100, h: 400 }, 0, "bottom").box,
  path: rb.pathOf({ type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1]]] }, ([x, y]) => [x * 10, y * 10]),
  bbox: rb.bboxOf({ type: "MultiPolygon", coordinates: [[[[0, 1], [2, 3], [1, 5]]], [[[-1, 0], [0, 0], [0, 1]]]] }),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("rbjs")
    (d / "radioboard.mjs").write_text((FRONTEND / "js" / "radioboard.js").read_text("utf-8"), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "radioboard.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_js_layers_and_address(js):
    assert js["ids"] == ["atis", "low", "mid", "high", "app", "twr", "twra", "fis"]
    # przyciski środkowej kolumny jak na szkicu: TWR/A = wieże z ATIS lotnisk
    assert js["labels"] == ["ATIS", "LOW", "MID", "HIGH", "APP", "TWR", "TWR/A", "FIS"]
    assert js["defaults"] == ["atis", "low", "mid", "high"]
    # 0.13.2 (issue #27): stałe przekroje (LOW FL330, MID FL350, HIGH FL400), bez suwaka i jego pomocników
    assert js["levels"] == {"LOW": 33000, "MID": 35000, "HIGH": 40000} and js["gone"] == []
    # stała kolejność warstw w adresie, "none" = żadna, nieznane pomijane; bez części /fl
    assert js["args"] == ["atis,low,mid,high", "none", "twra,fis"]
    # stary adres z przekrojem LOW (#radio/atis,low/fl300, do 0.13.1) otwiera te same warstwy, przekrój pomijany
    assert js["parsed"] == [
        {"layers": ["atis", "low", "mid", "high"], "keys": ["layers"]}, {"layers": [], "keys": ["layers"]},
        {"layers": ["app"], "keys": ["layers"]}, {"layers": None, "keys": ["layers"]}, {"layers": None, "keys": ["layers"]},
        {"layers": ["twr"], "keys": ["layers"]}, {"layers": ["atis", "low", "mid", "high"], "keys": ["layers"]}]
    assert js["fl"] == ["295", "FL095", "FL000"]
    assert js["sliceAt"] == [{"lo": 100, "hi": 200}]  # dolna granica włącznie, górna nie


def test_js_plates_and_page_grid(js):
    """0.13.2 (issue #27): plakietki bez linii prowadzących (placeLabels lines: false – bez nakładania się, lekko
    odsunięte), nazwa plakietki ACC (jeden sektor: "B LOW", kilka: skrót stanowiska) i siatka strony wg szkicu."""
    p = js["plates"]
    assert p["ov"] == 0 and p["hits"] == 0 and p["first"] == {"dx": 0, "dy": 0, "v": 0, "hit": False}
    assert p["far"] <= 3 * 20 * 1.5  # ACC: najwyżej max × STRETCH od punktu
    assert p["opts"] == [{"max": 60, "wc": 0.4}, {"max": 20, "wc": 0.2}, {"max": 30, "wc": 2}, {"max": 60, "wc": 0.4}]
    assert js["accNames"] == ["B LOW", "N", "ALL", "name EPWW_X_CTR"]
    pg = js["page"]
    assert pg["cols"] == ["var(--rb-tw)", "minmax(0, 1fr)", "var(--rb-hw)", "var(--rb-nw)"] and pg["top"] == 2
    # wiersze szkicu 3–6: rząd liczb i kafelek na przemian, ostatni rząd liczb zamyka siatkę; rząd liczb jak najwyższy
    # z FIR-ów (A: 365 między A1 i A2 – jedna liczba; nad wierszem 5 nic)
    lv1, lv0, t = "minmax(var(--rb-lv1), 1fr)", "minmax(var(--rb-lv0), 1fr)", "var(--rb-th)"
    assert pg["rows"] == [lv1, t, "minmax(var(--rb-lv2), 1fr)", t, lv1, t, lv1, t, lv0]
    assert pg["tiles"] == [[["A1", "1 / 2", "2 / 3"], ["A2", "1 / 2", "4 / 5"]], [["B1", "4 / 5", "6 / 7"]]]
    # liczby przy swoich kafelkach: górna granica kafelka pod spodem (up), dolna nad nią (dn), dwie (two)
    assert pg["marks"] == [[["1", "1", "up", 660], ["1", "3", "two", 365, 285], ["1", "5", "dn", 0]],
                           [["4", "5", "up", 999], ["4", "7", "dn", 0]]]
    assert pg["tracks"] == [[1, 2], [3, 4], [7, 8]]
    assert pg["areas"] == [{"gc": "4 / span 4", "gr": "12 / 31"}, {"gc": "8 / span 1", "gr": "25 / 28"},
                           {"gc": "1 / span 1", "gr": "1 / 3"}]
    assert pg["empty"]["stacks"] == [] and len(pg["empty"]["rows"]) == 3 and pg["empty"]["cols"] == ["var(--rb-tw)"] * 2


def test_js_layout_helpers(js):
    # pierwsza (najważniejsza) zostaje w miejscu
    assert js["overlaps"] == 0 and js["first"] == {"dx": 0, "dy": 0, "v": 0, "hit": False}
    # obrysy CTR/TMA (coverGrid): sam obrys i kropki punktów, nie wnętrze; etykieta odchodzi poza obrys
    cv = js["cover"]
    assert cv["inner"] == 0 and cv["edge"] > 0 and cv["point"] > 0 and cv["none"] == 0
    assert cv["m0"]["dx"] == 0 and cv["m0"]["dy"] == 0 and cv["clear"] == 0 and (cv["m"]["dx"], cv["m"]["dy"]) != (0, 0)
    assert cv["v"][0] > 0 and cv["v"][1] == 0  # wv: obsadzona etykieta zachowuje częstotliwość
    assert cv["onDot"] is False and cv["pinned"]["hit"] is False, cv["pinned"]  # kropka z pin zostaje widoczna
    # tłok: bez nakładania się i bez wchodzenia na przeszkody (tytuł podglądu); część etykiet w mniejszej odmianie
    c = js["crowd"]
    assert c["overlaps"] == 0 and c["onObstacle"] == 0 and c["hits"] == 0, c
    assert c["first"]["v"] == 0 and len(c["variants"]) > 1
    assert js["hhmm"] == ["12:00Z", "09:05Z", "–", "–"]  # 7 cyfr ułamka z VATSIM, zły czas nie psuje strony
    assert js["counted"] == 3  # alias_of (EKDK) liczony raz, ATIS nie
    assert js["bboxes"][0] is None and js["bboxes"][1] == [14, 49, 24, 55] and len(js["bboxes"][2]) == 4
    assert js["advisory"] == "122.800"
    # 0.13.1 stos sąsiada (stackGrid): kolumna stosu = kolumna szkicu, na przemian rząd liczb i rząd kafelków;
    # wysokości między kafelkami (liczby jak na szkicu), ten sam zakres sąsiadów – bez liczby między nimi
    st = js["stacks"]
    e = st["edww"]
    assert (e["ncols"], e["nrows"], e["cols"], e["rows"]) == (1, 7, ["t"], ["l1", "t", "l0", "t", "l0", "t", "l1"])
    assert e["tiles"] == [["MRZ", "1 / 2", "2 / 3"], ["MAR", "1 / 2", "4 / 5"], ["FLG", "1 / 2", "6 / 7"]]
    assert e["marks"] == [["1", "1", 285], ["1", "7", 0]]
    # EDUU: wspólna granica jedną liczbą, nowy ciąg (285 pod OSE1, 660 nad HVL2) dwiema
    u = st["eduu"]
    assert u["rows"] == ["l1", "t", "l1", "t", "l2", "t", "l1", "t", "l1"]
    assert u["marks"] == [["1", "1", 660], ["1", "3", 365], ["1", "5", 285, 660], ["1", "7", 365], ["1", "9", 285]]
    # połączone HVL2 + HVL1: jeden kafelek na dwa wiersze, bez liczby w środku, rzędy liczb bez zmian
    h = st["hvl"]
    assert h["rows"] == u["rows"] and h["tiles"][2] == ["HVL2+HVL1", "1 / 2", "6 / 9"]
    assert h["marks"] == [["1", "1", 660], ["1", "3", 365], ["1", "5", 285, 660], ["1", "9", 285]]
    # EDUU_H12_CTR we wszystkich czterech: jeden kafelek przez puste wiersze szkicu 9 i 10 – te same tory stosu co bez
    # łączenia (dawniej 13 zamiast 9, stos o dwa rzędy kafelków wyższy); OSE1 + HVL2 i ciągi z nimi: nad i pod połączonym
    # granica jego członka przy krawędzi (365), nie dwie liczby (365/660, 285/365) w rzędzie na jedną
    full, ose_hvl, ose3, hvl3 = em = st["eduuMerged"]
    for g in em:
        assert (g["ncols"], g["nrows"], g["cols"], g["rows"]) == (u["ncols"], u["nrows"], u["cols"], u["rows"]), g
    assert full["tiles"] == [["OSE2+OSE1+HVL2+HVL1", "1 / 2", "2 / 9"]] and full["marks"] == [["1", "1", 660], ["1", "9", 285]]
    assert ose_hvl["tiles"] == [["OSE2", "1 / 2", "2 / 3"], ["OSE1+HVL2", "1 / 2", "4 / 7"], ["HVL1", "1 / 2", "8 / 9"]]
    assert ose_hvl["marks"] == [["1", "1", 660], ["1", "3", 365], ["1", "7", 365], ["1", "9", 285]]
    assert ose3["tiles"][0] == ["OSE2+OSE1+HVL2", "1 / 2", "2 / 7"] and ose3["marks"] == [["1", "1", 660], ["1", "7", 365],
                                                                                          ["1", "9", 285]]
    assert hvl3["tiles"][1] == ["OSE1+HVL2+HVL1", "1 / 2", "4 / 9"] and hvl3["marks"] == [["1", "1", 660], ["1", "3", 365],
                                                                                          ["1", "9", 285]]
    # ESAA: dwie kolumny, liczby osobno w każdej (do lewej w swojej kolumnie)
    assert st["esaa"]["marks"] == [["1", "1", 660], ["2", "1", 660], ["1", "3", 365], ["2", "3", 365], ["1", "5", 195],
                                   ["2", "5", 0]]
    # LKAA bez łączenia (jak na zdjęciu PANDORY): MT pod SL (ta sama granica 125), pod NL jego dolna granica, 0 pod MT
    l0 = st["lkaa0"]
    assert l0["marks"] == [["1", "1", 660], ["2", "1", 660], ["1", "3", 305], ["2", "3", 305], ["1", "5", 125],
                           ["2", "5", 125], ["2", "7", 0]]
    # LKAA_CTR: jeden kafelek 2 × 3, liczby tylko nad nim i pod nim w pierwszej kolumnie, stos tego samego rozmiaru
    lk = st["lkaa"]
    assert lk["tiles"] == [["LKAA", "1 / 3", "2 / 7"]] and lk["marks"] == [["1", "1", 660], ["1", "7", 0]]
    assert (lk["ncols"], lk["nrows"], lk["rows"]) == (l0["ncols"], l0["nrows"], l0["rows"]) == (2, 7, ["l1", "t", "l1", "t", "l1", "t", "l1"])
    # EDMM: MEI i SPE1 w jednym wierszu
    assert st["edmm"]["marks"] == [["1", "1", 315], ["2", "1", 660], ["1", "3", 165], ["2", "3", 315]]
    # 0.13.2 (przegląd): połączone okienko na dwie kolumny pokazuje w drugiej kolumnie granicę jej członka, gdy jest inna
    # niż w pierwszej – ESAA 9+6+8+7 nad L: 195 pod 8 (wspólna z L) i 0 pod 7 (dawniej 660-195, choć 7 sięga ziemi),
    # bez drugiego 660 nad 6; EDMM MEI+SPE1 nad SAS: 315 i 660 nad nim, 165 i 315 pod nim (dawniej 315-165)
    e0, e1 = st["esaaL"]
    assert e0["marks"] == [["1", "1", 660], ["2", "1", 660], ["1", "3", 365], ["2", "3", 365], ["1", "5", 195], ["2", "5", 0],
                           ["1", "7", 0]]
    assert e1["tiles"] == [["7", "1 / 3", "2 / 5"], ["L", "1 / 2", "6 / 7"]]
    assert e1["marks"] == [["1", "1", 660], ["1", "5", 195], ["2", "5", 0], ["1", "7", 0]] and e1["at"][1:3] == ["sh", "dn"]
    m0, m1 = st["edmmSas"]
    assert m0["marks"] == m1["marks"] == [["1", "1", 315], ["2", "1", 660], ["1", "3", 165], ["2", "3", 315], ["1", "5", 0]]
    assert (e1["rows"], m1["rows"]) == (e0["rows"], m0["rows"])  # rzędy liczb jak bez łączenia
    # LKAA NU+SU nad NL i SL: 660 raz (ta sama granica w obu kolumnach), pod nim 305 w obu kolumnach jak dotąd
    assert st["lkaaNs"]["marks"] == [["1", "1", 660], ["1", "3", 305], ["2", "3", 305], ["1", "5", 125], ["2", "5", 125], ["2", "7", 0]]
    fb = st["fallback"]
    assert (fb["ncols"], fb["nrows"]) == (1, 5) and fb["tiles"][0] == ["A", "1 / 2", "2 / 3"]
    assert fb["tiles"][1] == ["B", "1 / 2", "4 / 5"] and fb["tiles"][2] == ["C", "1 / 2", "2 / 3"]
    assert st["empty"] == [{"ncols": 0, "nrows": 1, "cols": [], "rows": ["l0"], "tiles": [], "marks": [], "at": []}] * 2
    # 0.13.2: przy czym stoi liczba (rząd liczb strony bywa wyższy): up – nad kafelkiem, dn – pod nim, sh – wspólna,
    # two – dwie
    assert e["at"] == ["up", "dn"] and u["at"] == ["up", "sh", "two", "sh", "dn"]
    assert st["lkaa0"]["at"] == ["up", "up", "sh", "sh", "dn", "sh", "dn"]
    assert js["limText"] == ["660-365", "999-0", "660-95", "0-0"]
    assert js["limTip"] == ["FL365–FL660", "GND–UNL", "GND–FL285", "FL055–FL125"]
    a, b, box = js["proj"]["a"], js["proj"]["b"], js["proj"]["box"]
    assert a == pytest.approx([box["x"], box["y"]]) and b == pytest.approx([box["x"] + box["w"], box["y"] + box["h"]])
    assert 10 <= box["x"] and box["x"] + box["w"] <= 310 and 20 <= box["y"] and box["y"] + box["h"] <= 320
    assert js["bottom"]["y"] + js["bottom"]["h"] == pytest.approx(400)  # MID przy dolnej krawędzi
    assert js["path"] == "M0.0,0.0L10.0,0.0L10.0,10.0Z"
    assert js["bbox"] == [-1, 0, 2, 5]


STACK_ALL_SCRIPT = r"""
import fs from "fs";
const rb = await import(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(cases.map((c) => {
  const g = rb.stackGrid(c);
  return { fir: c.fir, on: c.on, cols: g.cols, rows: g.rows, tiles: g.tiles.map((t) => [t.b.id, t.gr]),
    over: g.marks.filter((k) => k.n.length > Number(g.rows[Number(k.gr) - 1].slice(1))).map((k) => [k.gc, k.gr, ...k.n]),
    marks: g.marks.map((k) => [k.gc, k.gr, ...k.n]) };
})));
"""


def test_js_stack_size_fixed_all_merges(tmp_path):
    """0.13.1: stos sąsiada nie zmienia rozmiaru przy żadnym łączeniu okienek – merge_boxes na okienkach z seeda (każde
    okienko FIR-u z łączeniem bez nikogo albo u jednego z dwóch stanowisk) i stackGrid strony: te same tory co bez
    nikogo, żadna liczba poza swoim rzędem. EDUU_H12_CTR we wszystkich czterech okienkach EDUU łączy je przez puste
    wiersze szkicu 9 i 10 (dawniej stos o dwa rzędy kafelków wyższy, strona skakała przy logowaniu). 0.13.2 (issue #27):
    stackGrid na wszystkich kolumnach i wierszach siatki strony (jak pageGrid), więc tory są torami strony."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    lay = rb.layout_static(json.loads((ROOT_DIR / "data" / "seed" / "radio_layout.json").read_text("utf-8")), {})
    grid = lay["grid"]
    cols, rows = list(range(1, grid["cols"] + 1)), list(range(grid["top"] + 1, grid["rows"] + 1))
    cases = []
    for f in lay["firs"]:
        if not (f["merge"] and f["fir"] in rb.MERGE_FIRS):
            continue
        for own in itertools.product((None, "A_CTR", "B_CTR"), repeat=len(f["boxes"])):
            bs = [{**b, "owner": o, "staffed": bool(o), "frequency": None, "key": o and f"cs:{o}"}
                  for b, o in zip(f["boxes"], own)]
            cases.append({"fir": f["fir"], "on": [f"{b['id']}={b['owner']}" for b in bs if b["owner"]], "cols": cols,
                          "rows": rows, "boxes": rb.merge_boxes(bs, lay["occupied"], f["fir"])})
    data = tmp_path / "cases.json"
    data.write_text(json.dumps(cases), "utf-8")
    (tmp_path / "radioboard.mjs").write_text((FRONTEND / "js" / "radioboard.js").read_text("utf-8"), "utf-8")
    script = tmp_path / "all.mjs"
    script.write_text(STACK_ALL_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (tmp_path / "radioboard.mjs").as_uri(), str(data)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    base = {g["fir"]: g for g in out if not g["on"]}
    assert set(base) == set(rb.MERGE_FIRS) and len(out) == len(cases) > 400
    # łączenie naprawdę zachodzi (także przez puste wiersze szkicu EDUU), a stos zawsze ma tory jak bez nikogo
    assert sum(any(b["merged"] for b in c["boxes"]) for c in cases) > 200
    full = next(g for g in out if g["fir"] == "EDUU" and g["on"] == ["OSE2=A_CTR", "OSE1=A_CTR", "HVL2=A_CTR", "HVL1=A_CTR"])
    assert full["tiles"] == [["OSE2+OSE1+HVL2+HVL1", "10 / 21"]] and full["rows"] == base["EDUU"]["rows"]
    assert len(full["rows"]) == 2 * len(rows) + 1 and full["cols"] == ["t"] * 13
    # dwa połączone okienka o tym samym zakresie (660-285): na stronie między nimi puste wiersze szkicu 9 i 10, więc
    # każde ma swoje granice nad i pod sobą (w kolumnie C, rzędy liczb wierszy 7, 9, 11 i 13 szkicu)
    pair = next(g for g in out if g["fir"] == "EDUU" and g["on"] == ["OSE2=A_CTR", "OSE1=A_CTR", "HVL2=B_CTR", "HVL1=B_CTR"])
    assert [t[0] for t in pair["tiles"]] == ["OSE2+OSE1", "HVL2+HVL1"] and pair["rows"] == base["EDUU"]["rows"]
    assert pair["marks"] == [["3", "9", 660], ["3", "13", 285], ["3", "17", 660], ["3", "21", 285]], pair["marks"]
    changed = [f"{g['fir']} {g['on']}" for g in out if (g["cols"], g["rows"]) != (base[g["fir"]]["cols"], base[g["fir"]]["rows"])]
    assert changed == []
    assert [(g["fir"], g["on"], g["over"]) for g in out if g["over"]] == []



LAYOUT_SCRIPT = r"""
// podgląd LOW (FL330) jak na ekranie 1366×768, 1600×900 i 1920×1080 (0.13.2, issue #27): granice i plakietki
// stanowisk online zbudowane funkcją strony previewItems (ACC warstwy, APP, TWR, TWR/A, FIS – tylko zalogowani)
// i ułożone przez placeLabels z labelOpts, bez linii prowadzących. Plakietka jak kafelek: najmniej rozmiar kafelka
// (tw × th), szersza tylko przy dłuższym ID; podgląd LOW, tytuł i kafelek zmierzone w przeglądarce (demo,
// siatka szkicu, #radio/atis,low,mid,high). Sektory ACC: jeden obszar na stanowisko (accGroups, suma wycinków
// polygon-clipping z vendor/)
import fs from "fs";
import { createRequire } from "module";
globalThis.polygonClipping = createRequire(import.meta.url)(process.argv[6]);
const rb = await import(process.argv[2]);
const { boards, geo } = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const radio = await import(process.argv[4]);
const { posName } = await import(process.argv[5]);
console.warn = () => {};
// podgląd LOW: W, H, tytuł [x, y, w, h], kafelek tw × th, f = częstotliwość, lf = ID (px)
const SCREENS = {
  1366: { W: 371, H: 350, title: [2, 1, 70, 17], tw: 61.7, th: 22.6, f: 12, lf: 9 },
  1600: { W: 452, H: 417, title: [2, 1, 70, 17], tw: 70.2, th: 29.4, f: 13.8, lf: 9.8 },
  1920: { W: 568, H: 504, title: [2, 1, 70, 17], tw: 80.5, th: 33.3, f: 16, lf: 12 },
};
const SETS = { twr: ["low", "twr"], apptwr: ["low", "app", "twr"], all: ["low", "app", "twra", "fis"], nolow: ["app", "twr"] };
// rozmiar plakietki jak w radio.css: najmniej kafelek, szersza przy dłuższym ID (z literą ATIS) albo częstotliwości
const tw = (s, px) => [...String(s || "")].length * 0.6 * px;
const sizeOf = (p, scr) => ({ w: Math.ceil(Math.max(scr.tw, 10 + Math.max(tw(p.id, scr.lf) + (p.code ? 3 + 4 + tw(p.code, scr.lf) : 0), tw(p.fq, scr.f)))),
  h: scr.th });
const FQ = /^\d{3}\.\d{3}$/;
function layout(bd, set, scr) {
  const ly = new Set(SETS[set]);
  const x = { freq: (cs) => bd.online?.[cs]?.frequency || bd.pos[cs]?.frequency || "", nm: posName, dn: posName,
    on: (cs) => bd.online?.[cs] || null, who: (cs) => (bd.online?.[cs] ? `${cs} online` : ""), pos: (cs) => cs, net: true };
  const groups = radio.accGroups(rb.sliceAt(geo.acc, rb.LEVEL_FT.LOW), bd.sectors, "LOW", "layout", geo.border);
  const { lines, plates } = radio.previewItems(bd, geo, "LOW", ly, groups, x, "layout");
  const { W, H } = scr;
  const { P } = rb.projection(rb.bboxOrDefault(rb.bboxOf(geo.border)) || rb.EPWW_BBOX, { x: 0, y: 0, w: W, h: H }, 0.03);
  const items = plates.map((p) => { const [px, py] = P([p.at[1], p.at[0]]); return { x: px, y: py, ...sizeOf(p, scr), ...rb.labelOpts(p.kind) }; });
  const cover = lines.length ? rb.coverGrid(lines.flatMap((l) => (l.geom ? [l.geom] : l.shapes).flatMap((g) => rb.ringsOf(g).map((r) => r.map(P)))), W, H) : null;
  const [ox, oy, ow, oh] = scr.title, obstacles = [{ x0: ox - 2, y0: oy - 2, x1: ox + ow + 2, y1: oy + oh + 2 }];
  const mv = rb.placeLabels(items, { x: 2, y: 2, w: W - 4, h: H - 4 }, { obstacles, cover, lines: false });
  const rects = items.map((it, i) => ({ x0: it.x + mv[i].dx - it.w / 2, y0: it.y + mv[i].dy - it.h / 2, x1: it.x + mv[i].dx + it.w / 2, y1: it.y + mv[i].dy + it.h / 2 }));
  // odległość punktu plakietki od jej krawędzi (0 = punkt pod plakietką) i od środka plakietki
  const gap = (i) => Math.hypot(Math.max(0, Math.abs(mv[i].dx) - items[i].w / 2), Math.max(0, Math.abs(mv[i].dy) - items[i].h / 2));
  const of = (kind) => plates.map((p, i) => ({ p, i })).filter(({ p }) => p.kind === kind);
  const tw0 = [...of("app"), ...of("twr")];
  return {
    n: plates.length, order: plates.map((p) => p.kind), app: of("app").map(({ p }) => p.k).sort(), twr: of("twr").map(({ p }) => p.k).sort(),
    acc: of("acc").map(({ p }) => p.id).sort(), fis: of("fis").map(({ p }) => p.k).sort(),
    atisOnly: of("twr").filter(({ p }) => p.atis).map(({ p }) => [p.k, p.state, FQ.test(p.fq)]),
    lines: lines.map((l) => `${l.kind}:${l.k}`).sort(),
    // plakietka w środku swojej przestrzeni: najwyżej lekko odsunięta; punkt części TMA albo CTR (plates.at)
    gap: Math.round(Math.max(0, ...tw0.map(({ i }) => gap(i)))), gapAll: Math.round(Math.max(0, ...plates.map((_, i) => gap(i)))),
    centre: Object.fromEntries(tw0.map(({ p, i }) => [p.k, Math.round(Math.hypot(mv[i].dx, mv[i].dy))])),
    at: Object.fromEntries(of("app").map(({ p }) => [p.k, p.at])),
    overlaps: rects.flatMap((a, i) => rects.slice(i + 1).map((b, j) => (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1 ? `${plates[i].k}/${plates[i + 1 + j].k}` : "")))
      .filter(Boolean),
    hits: mv.filter((m) => m.hit).length,
    // każda plakietka z częstotliwością (tylko zalogowani; sam ATIS – częstotliwość ATIS)
    noFq: plates.filter((p) => !FQ.test(p.fq)).map((p) => p.k),
    html: plates.map(radio.plateHtml),
    // 0.13.2 (przegląd): każdy obrys w granicy FIR EPWW, więc w ramce podglądu (dawniej FIS Gdańsk z EPWW-MIDSEA
    // ok. 40 px nad górną krawędzią LOW); APP, TWR i FIS – sam obrys zewnętrzny (tyle "M", ile części)
    outside: lines.flatMap((l) => (l.geom ? [l.geom] : l.shapes).flatMap((g) => rb.ringsOf(g)).flat().map(P))
      .filter(([px, py]) => px < -0.5 || py < -0.5 || px > W + 0.5 || py > H + 0.5).length,
    holes: lines.filter((l) => l.kind !== "acc" && l.geom && (radio.linesSvg([l], P).match(/M/g) || []).length !== rb.ringsOf(l.geom).length)
      .map((l) => l.k),
  };
}
const res = {};
for (const [bn, bd] of Object.entries(boards)) for (const set of Object.keys(SETS)) for (const [sn, scr] of Object.entries(SCREENS)) {
  res[`${bn}-${set}-${sn}`] = layout(bd, set, scr);
}
console.log(JSON.stringify(res));
"""

ALT_FEED = {**FEED, "controllers": [
    {"callsign": cs, "frequency": fq, "name": "Alt", "cid": 30 + i} for i, (cs, fq) in enumerate((
        ("EPWA_S_APP", "135.930"), ("EPWA_TWR", "118.305"), ("EPGD_APP", "127.280"), ("EPWA_I_APP", "123.975"),
        ("EPWW_J_CTR", "124.625"), ("EPSY_TWR", "118.030"), ("EPWW_C_CTR", "133.475"), ("EPWW_DTC_CTR", "125.340")))]}
# APP podzielone (0.13.0, Marek): WA APP + WA N + WA S + dyrektor WA F, KK APP + KK E + dyrektor KK KK, wieże WA i KK
SPLIT_FEED = {**FEED, "controllers": [
    {"callsign": cs, "frequency": fq, "name": "Split", "cid": 50 + i} for i, (cs, fq) in enumerate((
        ("EPWA_APP", "128.805"), ("EPWA_N_APP", "125.055"), ("EPWA_S_APP", "135.930"), ("EPWA_F_APP", "129.380"),
        ("EPKK_APP", "121.075"), ("EPKK_E_APP", "126.975"), ("EPKK_KK_APP", "126.530"), ("EPKK_TWR", "123.255"),
        ("EPWA_TWR", "118.305"), ("EPWW_ALL_CTR", "125.450")))]}
EMPTY_FEED = {**FEED, "controllers": [], "atis": []}
# 0.13.2 (przegląd): same informacje FIS (Gdańsk z EPWW-MIDSEA nad Bałtykiem) i wieże; informacja Warszawa
FIS_FEED = {**FEED, "controllers": [
    {"callsign": cs, "frequency": fq, "name": "Fis", "cid": 80 + i} for i, (cs, fq) in enumerate((
        ("EPGD_I_APP", "129.850"), ("EPKK_I_APP", "119.275"), ("EPPO_I_APP", "122.525"), ("EPWA_I_APP", "123.975"),
        ("EPSC_TWR", "121.255"), ("EPKK_TWR", "123.255")))], "atis": []}
INFO_FEED = {**FEED, "controllers": [
    {"callsign": cs, "frequency": fq, "name": "Info", "cid": 90 + i} for i, (cs, fq) in enumerate((
        ("EPWW_I_CTR", "128.325"), ("EPWW_IE_CTR", "127.660")))], "atis": []}


def test_js_twr_layout(client, board, tmp_path, monkeypatch):
    """0.13.0 (Marek: "jak nikt nie siedzi, nie pokazuj tysiąca plakietek APP i TWR"), 0.13.2 (issue #27): na podglądzie
    LOW granice i plakietki tylko stanowisk online – APP: jedna plakietka na stanowisko APP w środku obsługiwanych części
    TMA (WA APP + WA N + WA S: trzy; dyrektor bez plakietki) i granatowa granica tych części, wieża online: granica CTR
    i plakietka, TWR/A także sam ATIS (ciemna plakietka z częstotliwością ATIS, bez granicy), FIS online: granica jego
    obszarów i jedna plakietka; bez nikogo – nic (bez samych ID). Bez linii prowadzących, najwyżej lekko odsunięte.
    Geometria z /api/radio/board, granice i plakietki funkcjami strony (previewItems, placeLabels, plateHtml) na
    1366×768, 1600×900 i 1920×1080; bez nakładania się, każda plakietka z częstotliwością."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    geo = client.get("/api/radio/board?geo=1").json()["geo"]
    boards = {"board": board}
    for name, feed in (("alt", ALT_FEED), ("split", SPLIT_FEED), ("empty", EMPTY_FEED), ("fis", FIS_FEED), ("info", INFO_FEED)):
        async def get(feed=feed):
            return feed

        monkeypatch.setattr(vatsim_api, "get_feed", get)
        boards[name] = client.get("/api/radio/board").json()
    assert boards["alt"]["online"].keys() >= {"EPWA_S_APP", "EPWA_TWR", "EPWA_I_APP"}
    data = tmp_path / "board.json"
    data.write_text(json.dumps({"boards": boards, "geo": geo}), "utf-8")
    script = tmp_path / "layout.mjs"
    script.write_text(LAYOUT_SCRIPT, "utf-8")
    pc = tmp_path / "pc.cjs"
    pc.write_text((FRONTEND / "vendor" / "polygon-clipping" / "polygon-clipping.umd.min.js").read_text("utf-8"), "utf-8")
    r = subprocess.run([node, str(script), (d / "radioboard.js").as_uri(), str(data), (d / "tabs" / "radio.js").as_uri(),
                        (d / "posname.js").as_uri(), str(pc)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    if os.environ.get("RB_DUMP"):
        open(os.environ["RB_DUMP"], "w").write(json.dumps(res))
    assert len(res) == 72
    # nikt online: ani jednej granicy i plakietki (ACC, APP, TWR, TWR/A bez ATIS-ów, FIS: bez samych ID)
    for key in ("empty-twr-1366", "empty-apptwr-1600", "empty-all-1920"):
        assert res[key]["n"] == 0 and res[key]["lines"] == [], key
    # FEED: N online na całym LOW (jedna plakietka "N"), WA APP (przejmuje WA N, WA S, Łódź i Radom – jedna plakietka
    # i jedna granica), żadnej wieży; na TWR/A sam ATIS EPWA (ciemna plakietka z częstotliwością ATIS, bez granicy CTR)
    b = res["board-apptwr-1366"]
    assert b["app"] == ["EPWA_APP"] and b["twr"] == [] and b["acc"] == ["N"]
    assert b["lines"] == ["acc:EPWW_N_CTR", "app:EPWA_APP"]
    ba = res["board-all-1366"]
    assert ba["twr"] == ["EPWA"] and ba["atisOnly"] == [["EPWA", "off", True]] and "twr:EPWA" not in ba["lines"]
    assert ba["fis"] == [] and not any(x.startswith("fis:") for x in ba["lines"])
    # LOW wyłączony: bez granic i plakietek ACC (APP i TWR dalej, gdy ich warstwy są włączone)
    nl = res["board-nolow-1600"]
    assert nl["acc"] == [] and nl["app"] == ["EPWA_APP"] and nl["lines"] == ["app:EPWA_APP"]
    # ALT: WA S APP i GD APP (informacja WA I APP bez plakietki APP – jest na FIS), wieże WA i SY z granicami CTR
    assert res["alt-apptwr-1600"]["app"] == ["EPGD_APP", "EPWA_S_APP"] and res["alt-twr-1600"]["twr"] == ["EPSY", "EPWA"]
    assert {"twr:EPSY", "twr:EPWA"} <= set(res["alt-twr-1600"]["lines"])
    assert res["alt-all-1600"]["fis"] == ["EPWA_I_APP"] and "fis:EPWA_I_APP" in res["alt-all-1600"]["lines"]
    # nazwy plakietek ACC (jeden sektor warstwy: litera i warstwa, kilka: skrót stanowiska)
    assert set(res["alt-twr-1600"]["acc"]) <= {"J", "C", "DTC"} | {f"{c} LOW" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    assert res["split-twr-1600"]["acc"] == ["ALL"]
    # APP podzielone: trzy plakietki WA i dwie KK, dyrektorzy (WA F, KK KK) bez plakietki; każda w punkcie swojej części
    sp = res["split-apptwr-1366"]
    assert sp["app"] == ["EPKK_APP", "EPKK_E_APP", "EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"] and sp["twr"] == ["EPKK", "EPWA"]
    assert {f"app:{cs}" for cs in sp["app"]} | {"twr:EPKK", "twr:EPWA"} <= set(sp["lines"])
    parts = {g["nominal"]: g["at"] for g in boards["split"]["tma"] if g["tma"] in ("TMA Warszawa", "TMA Kraków")}
    assert all(sp["at"][cs] == parts[cs] for cs in sp["app"]), (sp["at"], parts)
    # 0.13.2 (przegląd): FIS Gdańsk (z EPWW-MIDSEA) i reszta informacji: granice w ramce podglądu, bez pętli wokół CTR;
    # informacja Warszawa (EPWW_I_CTR, EPWW_IE_CTR) z granicą i plakietką jak inne stanowiska FIS
    fa = res["fis-all-1920"]
    assert fa["fis"] == ["EPGD_I_APP", "EPKK_I_APP", "EPPO_I_APP", "EPWA_I_APP"] and fa["twr"] == ["EPKK", "EPSC"]
    assert {"fis:EPGD_I_APP", "twr:EPSC"} <= set(fa["lines"])
    for sn in ("1366", "1600", "1920"):
        assert res[f"info-all-{sn}"]["fis"] == ["EPWW_IE_CTR", "EPWW_I_CTR"], sn
        assert {"fis:EPWW_IE_CTR", "fis:EPWW_I_CTR"} <= set(res[f"info-all-{sn}"]["lines"]), sn
        # plakietka z dopiskiem FIS (znak jak sektor ACC: sama nazwa "I" wyglądałaby jak plakietka ACC)
        assert all('class="rb-id">EPWW I' in h and ' FIS</span>' in h for h in res[f"info-all-{sn}"]["html"]), sn
    for key, out in res.items():
        assert out["outside"] == 0 and out["holes"] == [], (key, out["outside"], out["holes"])
        # kolejność układania: APP, TWR, ACC, FIS
        assert out["order"] == sorted(out["order"], key=["app", "twr", "acc", "fis"].index), key
        # plakietka w środku: punkt pod nią albo najwyżej lekko obok (PLATE_MAX × 1,5 w tłoku); ACC i FIS dalej
        assert out["gap"] <= 45 and out["gapAll"] <= 90, (key, out["gap"], out["centre"])
        assert out["noFq"] == [], (key, out["noFq"])
        assert all('class="rb-pl ' in h and "rb-lead" not in h for h in out["html"]), key
        assert out["overlaps"] == [] and out["hits"] == 0, (key, out["overlaps"])
    # APP podzielone: plakietka WA, WA N, WA S, KK i KK E najwyżej 45 px od punktu swojej części (w tłoku wokół
    # Warszawy plakietki odsuwają się od siebie i od wieży WA)
    for key in ("split-apptwr-1600", "split-apptwr-1920", "split-all-1600"):
        assert max(v for k, v in res[key]["centre"].items() if k in res[key]["app"]) <= 60, (key, res[key]["centre"])


ACC_SCRIPT = r"""
// sektory ACC podglądów wg stanowiska (runda 12): accGroups na geometrii i tablicy z /api/radio/board
import fs from "fs";
import { createRequire } from "module";
globalThis.polygonClipping = createRequire(import.meta.url)(process.argv[4]);
const radio = await import(process.argv[2]);
const rb = await import(process.argv[3]);
const { board, geo } = JSON.parse(fs.readFileSync(process.argv[5], "utf8"));
console.warn = () => {};
const inRing = (r, x, y) => { let c = false; for (let a = 0, b = r.length - 1; a < r.length; b = a++) {
  if ((r[a][1] > y) !== (r[b][1] > y) && x < ((r[b][0] - r[a][0]) * (y - r[a][1])) / (r[b][1] - r[a][1]) + r[a][0]) c = !c; } return c; };
const inside = (g, [lat, lon]) => (g.type === "Polygon" ? [g.coordinates] : g.coordinates)
  .some(([outer, ...holes]) => inRing(outer, lon, lat) && !holes.some((h) => inRing(h, lon, lat)));
const sum = (gs) => gs.map((g) => ({ owner: g.owner, ids: g.sectors.map((s) => s.id), slices: g.slices.length,
  parts: g.geom ? g.geom.coordinates.length : null, holes: g.geom ? g.geom.coordinates.reduce((a, p) => a + p.length - 1, 0) : null,
  inside: !!g.at && (g.geom ? inside(g.geom, g.at) : g.slices.some((sl) => inside(sl.geometry, g.at))) }));
const out = {};
for (const [layer, ft] of Object.entries(rb.LEVEL_FT)) out[layer] = sum(radio.accGroups(rb.sliceAt(geo.acc, ft), board.sectors, layer, "t"));
out.letters = [...new Set(rb.sliceAt(geo.acc, rb.LEVEL_FT.LOW).map((s) => s.letter))].sort();
// każdy sektor obsadzony przez własne stanowisko; nikt online; bez biblioteki (same wycinki, etykieta w największym)
out.all = sum(radio.accGroups(rb.sliceAt(geo.acc, rb.LEVEL_FT.LOW), board.sectors.map((s) => ({ ...s, owner: s.nominal })), "LOW", "t"));
out.none = radio.accGroups(rb.sliceAt(geo.acc, rb.LEVEL_FT.LOW), board.sectors.map((s) => ({ ...s, owner: null })), "LOW", "t").length;
const lib = globalThis.polygonClipping;
globalThis.polygonClipping = undefined;
out.nolib = sum(radio.accGroups(rb.sliceAt(geo.acc, rb.LEVEL_FT.LOW), board.sectors, "LOW", "nolib"));
globalThis.polygonClipping = lib;
// szare pole (0.13.2): tylko wycinki sektorów warstwy bez obsługującego, jeden obszar; wszystko obsadzone – nic
const low = rb.sliceAt(geo.acc, rb.LEVEL_FT.LOW);
const fr = (secs, v) => { const f = radio.freeArea(low, secs, "LOW", v); return f && { n: f.shapes.length, geom: !!f.geom }; };
out.free = { board: fr(board.sectors, "fb"), all: fr(board.sectors.map((s) => ({ ...s, owner: s.nominal })), "fa"),
  none: fr(board.sectors.map((s) => ({ ...s, owner: null })), "fn"), slices: low.length,
  unowned: low.filter((sl) => !board.sectors.some((s) => s.layer === "LOW" && s.owner && s.letter === sl.letter)).length };
out.path = rb.pathAll({ type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]] }, (c) => c);
// 0.13.2 (przegląd): szare pole, obszary ACC i granice tylko w granicy FIR EPWW (pola w km², rzut jak na podglądzie)
const km2 = (r) => Math.abs(r.reduce((a, [x1, y1], i) => { const [x2, y2] = r[(i + 1) % r.length]; return a + x1 * y2 - x2 * y1; }, 0)) / 2
  * Math.cos((52 * Math.PI) / 180) * 111.32 * 111.32;
const polys = (g) => (g?.type === "Polygon" ? [g.coordinates] : g?.coordinates || []);
const areaOf = (g) => polys(g).reduce((a, [o, ...hs]) => a + km2(o) - hs.reduce((h, r) => h + km2(r), 0), 0);
const bRing = polys(geo.border)[0][0];
const near = (p) => bRing.some(([x1, y1], i) => { const [x2, y2] = bRing[(i + 1) % bRing.length], dx = x2 - x1, dy = y2 - y1;
  const t = Math.max(0, Math.min(1, ((p[0] - x1) * dx + (p[1] - y1) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - x1 - t * dx, p[1] - y1 - t * dy) < 1e-6; });
// wierzchołki poza granicą FIR-u (na samej granicy się nie liczą)
const outside = (g) => polys(g).flat().flat().filter((p) => !inRing(bRing, p[0], p[1]) && !near(p)).length;
const grey = (secs, v) => radio.freeArea(low, secs, "LOW", v, geo.border);
const gNone = grey(board.sectors.map((s) => ({ ...s, owner: null })), "gn"), gBoard = grey(board.sectors, "gb");
const grp = radio.accGroups(low, board.sectors, "LOW", "gb", geo.border);
out.grey = { border: Math.round(areaOf(geo.border)), none: Math.round(areaOf(gNone.geom)), noneOut: outside(gNone.geom),
  board: Math.round(areaOf(gBoard.geom)), boardOut: outside(gBoard.geom), group: Math.round(areaOf(grp[0].geom)), groupOut: outside(grp[0].geom),
  // bez granicy FIR-u (stara geometria): jak dotąd suma wycinków bez nikogo
  noBorder: Math.round(areaOf(radio.freeArea(low, board.sectors, "LOW", "gx").geom)),
  slices: Math.round(areaOf(radio.freeArea(low, board.sectors, "LOW", "gx2", { type: "MultiPolygon", coordinates: [] }).geom)),
  all: radio.freeArea(low, board.sectors.map((s) => ({ ...s, owner: s.nominal })), "LOW", "ga", geo.border) };
const raw = radio.accGroups(low, board.sectors, "LOW", "graw")[0];
out.grey.groupRawOut = outside(raw.geom);
// obrysy: dziury tylko w obszarze ACC (FIS, APP, TWR – sam obrys zewnętrzny); kwadrat z dziurą
const hole = { type: "MultiPolygon", coordinates: [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]],
  [[[20, 0], [30, 0], [30, 10], [20, 0]]]] };
out.lines = Object.fromEntries(["acc", "fis", "app", "twr"].map((k) => [k, (radio.linesSvg([{ kind: k, k: "X", geom: hole }], (c) => c).match(/M/g) || []).length]));
// fokus przy odświeżaniu: selektor tego samego kodu FIR-u, plakietki TWR, ATIS-u; inny element – null
const fake = (cls, attr, v) => ({ matches: (q) => q === `${cls}[data-${attr}]`, getAttribute: (a) => (a === `data-${attr}` ? v : null) });
out.focus = [fake(".rb-fh", "fir", "EDWW"), fake(".rb-pl", "icao", "EPWA"), fake(".rb-at", "icao", 'E"X'), fake(".rb-box", "fir", "EDWW"), null]
  .map(radio.focusSel);
console.log(JSON.stringify(out));
"""


def test_js_acc_groups(client, board, tmp_path):
    """Runda 12 (Marek): na podglądach LOW/MID/HIGH sektory ACC jednego stanowiska to jeden obszar z jedną plakietką
    (accGroups); po błędzie sumy same wycinki. 0.13.2 (issue #27): stałe przekroje (LOW FL330), sektory bez nikogo
    jako jedno szare pole bez granic (freeArea)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    pc = tmp_path / "pc.cjs"
    pc.write_text((FRONTEND / "vendor" / "polygon-clipping" / "polygon-clipping.umd.min.js").read_text("utf-8"), "utf-8")
    data = tmp_path / "board.json"
    data.write_text(json.dumps({"board": board, "geo": client.get("/api/radio/board?geo=1").json()["geo"]}), "utf-8")
    script = tmp_path / "acc.mjs"
    script.write_text(ACC_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "tabs" / "radio.js").as_uri(), (d / "radioboard.js").as_uri(), str(pc), str(data)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    for layer in ("LOW", "MID", "HIGH"):
        # FEED: z ACC tylko EPWW N – jeden obszar z sektorami, w których kolejności jest N; J, R i T bez nikogo
        owner = {s["letter"]: s["owner"] for s in board["sectors"] if s["layer"] == layer}
        (g,) = out[layer]
        assert g["owner"] == "EPWW_N_CTR" and g["inside"], layer
        ids = {i[1] for i in g["ids"]}
        assert ids == {k for k, v in owner.items() if v} & set(out["letters"]) and not ids & {"J", "R", "T"}, (layer, ids)
        assert g["parts"] is not None and g["parts"] <= g["slices"], layer
    # każdy sektor ze swoim stanowiskiem: tyle obszarów, ile stanowisk, etykieta zawsze w obszarze
    nominal = {s["letter"]: s["nominal"] for s in board["sectors"] if s["layer"] == "LOW"}
    assert sorted(g["owner"] for g in out["all"]) == sorted({nominal[x] for x in out["letters"]})
    assert all(g["inside"] for g in out["all"]) and out["none"] == 0
    # bez polygon-clipping: wycinki osobno (rysowane bez konturów), etykieta w jednym z nich
    (n,) = out["nolib"]
    assert n["parts"] is None and n["inside"] and n["ids"] == out["LOW"][0]["ids"]
    # szare pole tylko dla sektorów bez nikogo (FEED: N obsługuje część LOW, reszta szara); wszystko obsadzone –
    # bez szarego, nikt – cały FIR szary
    fr = out["free"]
    assert fr["board"] == {"n": fr["unowned"], "geom": True} and 0 < fr["unowned"] < fr["slices"]
    assert fr["all"] is None and fr["none"] == {"n": fr["slices"], "geom": True}
    # ścieżka SVG z dziurą (wypełnienie evenodd w radio.css)
    assert out["path"].count("M") == 2 and out["path"].endswith("ZM2.0,2.0L4.0,2.0L4.0,4.0L2.0,4.0L2.0,2.0Z")
    # 0.13.2 (przegląd): szare pole tylko w granicy FIR EPWW i do samej granicy – bez nikogo cały FIR (dawniej szare
    # kliny za granicą przy Opawie i Gubinie, czarne szczeliny w środku, np. cypel kłodzki); N online: szare + obszar N
    # to cały FIR, nic poza granicą; obszar ACC przycięty do granicy (bez granicy wierzchołki N wychodzą poza nią)
    g = out["grey"]
    assert g["none"] == pytest.approx(g["border"], rel=1e-4) and g["noneOut"] == 0
    assert g["boardOut"] == 0 and g["groupOut"] == 0 and g["groupRawOut"] > 0
    assert g["board"] + g["group"] == pytest.approx(g["border"], rel=0.003) and 0 < g["group"] < g["border"]
    assert g["all"] is None  # wszystko obsadzone – bez szarego
    assert g["noBorder"] == g["slices"] and g["noBorder"] != g["board"]  # bez granicy FIR-u jak w 0.13.2 przed przeglądem
    # dziury tylko w obszarze ACC: FIS, APP i TWR sam obrys zewnętrzny każdej części (pętla wokół CTR wieży offline
    # wyglądała jak granica wieży online)
    assert out["lines"] == {"acc": 3, "fis": 2, "app": 2, "twr": 2}
    assert out["focus"] == ['.rb-fh[data-fir="EDWW"]', '.rb-pl[data-icao="EPWA"]', '.rb-at[data-icao="E\\"X"]', None, None]


LOA_SCRIPT = r"""
const radio = await import(process.argv[2]);
const firs = JSON.parse(process.argv[3]);
const radioOf = (cs) => (cs === "EDDB_N_APP" ? "Bremen Radar" : "");
const evil = { title: "<img src=x onerror=alert(1)>", version: "v<1>", pdf: "javascript:alert(1)",
  transfers: [{ dir: "out", traffic: "<b>X</b>", cop: "C\"OP", level: "FL100", from: "", to: "", conditions: "&" }],
  silent: ["<i>s</i>"], vfr: [], other: [], positions: [{ callsign: "EDDB_N_APP", radio: "", sector: "<s>", frequency: "1", side: "NB", note: "" }] };
console.log(JSON.stringify({
  edww: radio.loaHtml("EDWW", "BREMEN", firs.EDWW, radioOf),
  none: radio.loaHtml("UMKK", "KALININGRAD", null, radioOf),
  loading: radio.loaHtml("EDWW", "BREMEN", null, radioOf, { loading: true }),
  error: radio.loaHtml("EDWW", "BREMEN", null, radioOf, { msg: "LOA: <zły plik>" }),
  evil: radio.loaHtml("EDWW", "BREMEN", evil, radioOf),
}));
"""


def test_js_loa_panel(tmp_path):
    """Panel LOA w RADIO (tabs/radio.js loaHtml): tabele przekazań w obie strony, zasady, stanowiska, LOA
    w COORDINATION › DOKUMENTY i PDF w nowej karcie; brak LOA, wczytywanie i błąd; dane z loa.json zawsze przez esc()."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    script = tmp_path / "loa.mjs"
    script.write_text(LOA_SCRIPT, "utf-8")
    firs = json.loads((ROOT_DIR / "data" / "seed" / "loa.json").read_text("utf-8"))["firs"]
    r = subprocess.run([node, str(script), (d / "tabs" / "radio.js").as_uri(), json.dumps(firs)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    e, f = out["edww"], firs["EDWW"]
    n_out = sum(t["dir"] == "out" for t in f["transfers"])
    assert f"transfers: {n_out} from EPWW · {len(f['transfers']) - n_out} to EPWW" in e
    assert "EPWW → EDWW" in e and "EDWW → EPWW" in e and "Positions and sectors <small>" in e
    # bez dopisków, skąd są dane (runda 15): ani "PDF extract", ani nazwy pliku
    assert "PDF extract" not in e and "loa.json" not in e and "per LOA" not in e
    rows = len(f["transfers"]) + len(f["positions"]) + sum(len(f[k]) for k in ("silent", "vfr", "other"))
    assert e.count("data-f=") == rows
    assert 'data-coord="EDWW"' in e and "COORDINATION ›" in e
    assert 'href="/files/docs/LOA/LOA%20EPWW%20EDWW%20Bremen,%20EDUU%20Karlsruhe%20(AIRAC%202602).pdf"' in e
    assert "<td>Bremen Radar</td>" in e  # znak radiowy z tablicy RADIO, gdy LOA go nie podaje
    assert "No EPWW LOA with UMKK" in out["none"] and "data-coord" not in out["none"] and "KALININGRAD" in out["none"]
    assert "Loading LOA…" in out["loading"]
    assert 'class="error">LOA: &lt;zły plik&gt;' in out["error"]
    ev = out["evil"]
    assert "<img" not in ev and "<b>X" not in ev and "<i>s" not in ev and "<s>" not in ev and 'C"OP' not in ev
    assert "javascript:" not in ev and "data-coord" not in ev  # PDF tylko z /files/docs/


NB_SCRIPT = r"""
const radio = await import(process.argv[2]);
const rb = await import(new URL("../radioboard.js", process.argv[2]));
const FQ = { EYVL_CTR: "133.305", EYVL_U_CTR: "132.280", EDUU_O22_CTR: "135.255", UMMV_W_CTR: "135.700" };
const x = { who: (cs) => `${cs} ${FQ[cs]} – Jonas`, pos: (cs) => `${cs} ${FQ[cs] || ""}`.trim(), freq: (cs) => FQ[cs] || "",
  sel: "EYVL", net: true };
// siatka strony jak z /api/radio/board (0.13.2: 13 kolumn szkicu, wiersze 3–21)
const GRID = { cols: 13, rows: 21, top: 2, tracks: ["box", "box", "box", "map", "box", "box", "map", "btn", "map", "box", "map", "box", "name"],
  berlin: { col: 1, row: 6, cols: 1, rows: 1, box: { col: 1, row: 7, cols: 2, rows: 1 } } };
const cell = (col, row, cols = 1, rows = 1) => ({ col, row, cols, rows });
const box = (id, upper, lower, col, row, cs, owner = null, o = {}) => ({ id, label: id, col, row, cols: 1, rows: 1, upper, lower,
  callsign: cs, chain: [cs], owner, staffed: !!owner, frequency: owner ? FQ[owner] : null,
  members: [{ id, upper, lower, callsign: cs, col, row, cols: 1, rows: 1 }], merged: false, ...o });
const eyvl = (boxes, o = {}) => ({ fir: "EYVL", title: "VILNIUS", name: cell(13, 3), room: cell(13, 3, 1, 2), merge: true,
  staffed: boxes.some((b) => b.owner), advisory: !boxes.some((b) => b.owner), online: [], boxes, ...o });
const U = box("U", 660, 365, 12, 3, "EYVL_U_CTR"), M = box("M", 365, 335, 12, 4, "EYVL_M_CTR");
const L = box("L", 335, 225, 12, 5, "EYVL_CTR"), E = box("E", 225, 95, 12, 6, "EYVL_E_CTR");
const merged = { id: "U+M+L+E", label: "L", col: 12, row: 3, cols: 1, rows: 4, upper: 660, lower: 95, callsign: "EYVL_CTR",
  chain: ["EYVL_CTR"], owner: "EYVL_CTR", staffed: true, frequency: "133.305", merged: true,
  members: [U, M, L, E].map((b) => b.members[0]) };
const on = [{ callsign: "EYVL_CTR", position: "EYVL_CTR", frequency: "133.305", name: "Jonas" }];
const eduu = { fir: "EDUU", title: "RHEIN", name: cell(3, 6), room: cell(3, 6, 2, 1), merge: true, staffed: true,
  advisory: false, online: [{ callsign: "EDUU_O22_CTR", position: "EDUU_O22_CTR", frequency: "135.255", name: "Max" }],
  boxes: [box("OSE2", 660, 365, 3, 7, "EDUU_O22_CTR", "EDUU_O22_CTR"), box("OSE1", 365, 285, 3, 8, "EDUU_O12_CTR")] };
const ummv = { fir: "UMMV", title: "MINSK", name: cell(13, 9), room: cell(13, 9, 1, 2), merge: false, staffed: true,
  advisory: false, online: [{ callsign: "UMBB_TWR", position: "UMBB_TWR", frequency: "118.500", name: "Ivan" },
    { callsign: "UMMV_W_CTR", position: "UMMV_W_CTR", frequency: "135.700", name: "Olga" }],
  boxes: [box("ACC", 660, 75, 12, 9, "UMMV_CTR", "UMMV_W_CTR", { label: "ACC" })] };
const ind = { id: "APP WA", tip: "Warszawa APP configuration: HL = one APP, H+L = two (with N APP), 2H+L = three (with S APP), +D = director (F APP)", value: "2H+L",
  positions: [{ callsign: "EPWA_APP", position: "EPWA_APP", frequency: "128.805", name: "Ala" }] };
const ber = { config: "EAST", preferred: false, tip: "ATIS EDDB: RWY 06L/06R" };
const evil = { fir: "<b>", title: "<i>t</i>", name: cell(1, 3), advisory: false, online: [{ callsign: "<u>", frequency: "1", name: "<s>x</s>" }],
  boxes: [box("<img src=x>", 660, 0, 1, 4, "A_CTR", "A_CTR", { frequency: "<s>1</s>" })] };
// jeden FIR na stronie: kod, liczby i kafelki w torach siatki strony (pageGrid + pageHtml, bez BERLIN)
const one = (f, xx) => radio.pageHtml(rb.pageGrid(GRID, [f]), { ...GRID, berlin: null }, {}, xx);
const rowsOf = (f) => rb.pageGrid(GRID, [f]).rows.join(" ");
console.log(JSON.stringify({
  off: one(eyvl([U, M, L, E]), x),
  part: one(eyvl([U, M, L, E].map((b) => (b === U ? { ...U, owner: "EYVL_U_CTR", staffed: true, frequency: "132.280" } : b)),
    { online: [{ callsign: "EYVL_U_CTR", position: "EYVL_U_CTR", frequency: "132.280", name: "Ona" }] }), { ...x, sel: null }),
  merged: one(eyvl([merged], { online: on }), x),
  eduu: one(eduu, { ...x, sel: null }),
  ummv: one(ummv, { ...x, sel: null }),
  nonet: one(eyvl([U, M, L, E], { advisory: false }), { ...x, net: false }),
  rowsOff: rowsOf(eyvl([U, M, L, E])), rowsMerged: rowsOf(eyvl([merged])),
  page: radio.pageHtml(rb.pageGrid(GRID, [eduu]), GRID, { berlin: ber }, { ...x, sel: null }),
  marks: [{ gc: "1", gr: "5", n: [285, 660], at: "two" }, { gc: "2", gr: "1", n: [999], at: "up" }, { gc: "1", gr: "7", n: [0], at: "dn" }].map(radio.markHtml),
  ind: radio.indicatorHtml(ind, x), indNone: radio.indicatorHtml({ ...ind, value: "0", positions: [] }, x),
  indNet: radio.indicatorHtml({ ...ind, value: "0", positions: [] }, { ...x, net: false }),
  ber: radio.berlinHtml(ber), berPref: radio.berlinHtml({ ...ber, config: "WEST", preferred: true, tip: "" }),
  berNone: radio.berlinHtml({}),
  berNet: radio.berlinHtml({ ...ber, config: "EAST", preferred: true, tip: "" }, { ...x, net: false }),
  berUnknown: radio.berlinHtml({ ...ber, config: null, source: "UNKNOWN", preferred: false, tip: "ATIS unknown: no network data" }),
  // dymki wskaźnika i BERLIN: tekst, którego zwykły kod strony nigdy nie ma (<em>), z wyjściem z atrybutu (">)
  evil: one(evil, { ...x, sel: null })
    + radio.indicatorHtml({ id: "<b>", tip: '"><em>x</em>', value: "<s>", positions: [{ callsign: '"><em>c', name: "<em>n" }] }, x)
    + radio.berlinHtml({ config: "<b>", tip: '"><em>y</em>' }),
}));
"""


def test_js_neighbour_boxes(tmp_path):
    """Kody FIR-ów sąsiadów, kafelki, wskaźniki i BERLIN w RADIO (tabs/radio.js firHeadHtml, tileHtml, markHtml, pageHtml,
    indicatorHtml, berlinHtml). 0.13.1 (issue #25): kafelek to samo ID w rogu i częstotliwość (tylko obsadzony),
    wysokości między kafelkami (liczby jak na szkicu); połączone okienko na swoich komórkach; błąd sieci → bez ADVISORY
    i bez zer; dane przez esc(). 0.13.2 (issue #27): wszystko w torach siatki strony (kolumny szkicu, wiersz szkicu r:
    rząd liczb 2(r-3)+1 i kafelek 2(r-3)+2), żółty kod FIR-u w swojej komórce, nazwa i ADVISORY 122.800 (gdy w całym
    FIR-ze nikogo) w miejscu obok kodu – bez osobnej linii, nic nie przesuwa kafelków; BERLIN w swoich komórkach."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    script = tmp_path / "nb.mjs"
    script.write_text(NB_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "tabs" / "radio.js").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    freqs = re.compile(r"\d{3}\.\d{3}")
    shown = {k: re.sub(r'data-rt="[^"]*"', "", h) for k, h in out.items() if isinstance(h, str)}  # bez dymków

    def marks(h):
        return re.findall(r'<div class="rb-bd (?:up|dn|sh|two)" style="grid-column: (\d+); grid-row: (\d+)"[^>]*><i>(\d+)</i>'
                          r'(?:<span class="rb-sep"></span><i>(\d+)</i>)?</div>', h)

    off = out["off"]
    # nikt z EYVL online: ADVISORY raz obok kodu, żadnej innej częstotliwości, kafelki z samym ID, bez granic
    assert shown["off"].count("ADVISORY 122.800") == 1 and '<span class="rb-fs">ADVISORY 122.800</span></div>' in off
    assert freqs.findall(shown["off"]) == ["122.800"]
    assert off.count('class="rb-box off"') == 4 and 'class="rb-fq"' not in off
    assert '<span class="rb-id">U</span></div>' in off and "660-365" not in shown["off"] and "rb-lim" not in off
    # wysokości między kafelkami w kolumnie L szkicu (12): jedna liczba na wspólnej granicy, nad pierwszym górna, pod
    # ostatnim dolna; rzędy liczb wierszy 3–7 szkicu (tory 1, 3, 5, 7, 9)
    assert marks(off) == [("12", "1", "660", ""), ("12", "3", "365", ""), ("12", "5", "335", ""), ("12", "7", "225", ""),
                          ("12", "9", "95", "")]
    assert re.findall(r'class="rb-bd (\w+)"', off) == ["up", "sh", "sh", "sh", "dn"]
    assert 'data-fir="EYVL" data-box="U" style="grid-column: 12 / 13; grid-row: 2 / 3"' in off
    assert 'data-box="E" style="grid-column: 12 / 13; grid-row: 8 / 9"' in off
    # kod FIR-u w swojej komórce (kolumna M, wiersze 3–4 szkicu: tory 2–4), zaznaczony przy otwartym LOA, klawiatura
    # i data-fir do panelu LOA; przy prawej krawędzi (down) ADVISORY pod kodem
    assert ('<div class="rb-fh down sel" data-fir="EYVL" data-title="VILNIUS" role="button" tabindex="0"'
            ' style="grid-column: 13 / span 1; grid-row: 2 / 5"') in off
    assert '<span class="rb-fc">EYVL</span><span class="rb-fn">VILNIUS</span><span class="rb-fs">' in off
    assert "Nobody online – ADVISORY 122.800" in off and "Click: LOA EPWW – EYVL" in off
    assert "Numbers between the boxes: vertical limits (FL)" in off
    assert off.count("Now: unstaffed – ADVISORY 122.800") == 4
    assert "EYVL U · FL365–FL660\nPosition: EYVL_U_CTR 132.280\nNow: unstaffed – ADVISORY 122.800" in off
    # część obsadzona: częstotliwość tylko w tym kafelku, bez ADVISORY (nic się nie przesuwa: ADVISORY w miejscu obok kodu)
    part = out["part"]
    assert "ADVISORY" not in part and 'class="rb-fs"' not in part
    assert part.count('class="rb-box on"') == 1 and part.count('class="rb-fq"') == 1
    assert '<span class="rb-id">U</span><span class="rb-fq">132.280</span>' in part and part.count("Now: unstaffed") == 3
    assert "Online: EYVL_U_CTR 132.280 – Ona" in part and 'class="rb-fh down" data-fir="EYVL"' in part
    # połączone: jeden kafelek na czterech wierszach, ID połączonego (L), granice tylko nad nim i pod nim i w dymku;
    # tory strony te same co bez łączenia
    mg = out["merged"]
    assert mg.count('class="rb-box') == 1 and 'class="rb-box on mrg"' in mg and 'data-box="U+M+L+E"' in mg
    assert 'style="grid-column: 12 / 13; grid-row: 2 / 9"' in mg and out["rowsMerged"] == out["rowsOff"]
    assert '<span class="rb-id">L</span><span class="rb-fq">133.305</span>' in mg and "Now: EYVL_CTR 133.305 – Jonas" in mg
    assert "Merged: U 660-365, M 365-335, L 335-225, E 225-95" in mg and "Position:" not in mg
    assert "EYVL L · FL095–FL660" in mg and marks(mg) == [("12", "1", "660", ""), ("12", "9", "95", "")]
    # EDUU: OSE2 obsadzone, OSE1 nie (bez ADVISORY: ktoś z FIR-u jest); kod w wierszu 6 szkicu, nazwa obok
    ed = out["eduu"]
    assert '<span class="rb-id">OSE2</span><span class="rb-fq">135.255</span>' in ed and '<span class="rb-id">OSE1</span></div>' in ed
    assert ed.count('class="rb-fq"') == 1 and "ADVISORY" not in ed
    assert marks(ed) == [("3", "9", "660", ""), ("3", "11", "365", ""), ("3", "13", "285", "")]
    assert 'style="grid-column: 3 / span 2; grid-row: 8 / 9"' in ed and 'class="rb-fh" data-fir="EDUU"' in ed
    assert "Also online" not in ed  # tylko okienko na cały FIR wymienia pozostałych zalogowanych
    # UMMV: jedno okienko na FIR – w dymku także wieża (UMBB TWR), która go nie obsługuje
    um = out["ummv"]
    assert '<span class="rb-fq">135.700</span>' in um and "Also online: UMBB_TWR 118.500 – Ivan" in um
    assert "Also online: UMMV_W_CTR" not in um and "Online: UMBB_TWR 118.500 – Ivan" in um
    # błąd sieci: nie wiadomo, czy ktoś jest online – bez ADVISORY, bez częstotliwości
    nn = out["nonet"]
    assert "ADVISORY" not in nn and 'class="rb-fq"' not in nn and nn.count("Now: no data") == 4 and "Online: no data" in nn
    # BERLIN na stronie: napis w swojej komórce (A6: tor 8), pole WEST/EAST na dwie kolumny (A7–B7: tor 10)
    pg = out["page"]
    assert '<div class="rb-blbl" style="grid-column: 1 / span 1; grid-row: 8 / 9" data-rt="BERLIN: ' in pg
    assert re.search(r'<div class="rb-bln" style="grid-column: 1 / span 2; grid-row: 10 / 11" data-rt="[^"]*">EAST</div>$', pg)
    # dwie liczby z kreską (nowy ciąg okienek), UNL i GND w dymku liczby; przy czym stoi liczba (klasa)
    m2, m999, m0 = out["marks"]
    assert m2 == ('<div class="rb-bd two" style="grid-column: 1; grid-row: 5" data-rt="FL285: lower limit of the box above\n'
                  'FL660: upper limit of the box below"><i>285</i><span class="rb-sep"></span><i>660</i></div>')
    assert 'data-rt="UNL"><i>999</i></div>' in m999 and 'class="rb-bd up" style="grid-column: 2; grid-row: 1"' in m999
    assert 'class="rb-bd dn"' in m0 and 'data-rt="GND"><i>0</i></div>' in m0
    # wskaźnik: mała żółta nazwa nad małym szarym polem z wartością, bez miejsca w siatce; w dymku znaczenie i zalogowani
    ind = out["ind"]
    assert ind.startswith('<div class="rb-indc" data-rt="APP WA: ') and "grid-area" not in ind
    # wartość w rb-indt: za długa (ACC GAT) od początku z wielokropkiem na końcu, nie ucięta z obu stron
    assert '<div class="rb-ind">APP WA</div><div class="rb-indv"><span class="rb-indt">2H+L</span></div></div>' in ind
    assert "APP WA: Warszawa APP configuration: HL = one APP, H+L = two (with N APP), 2H+L = three (with S APP), +D = director (F APP)\nEPWA_APP 128.805 – Ala" in ind
    assert ">0</span></div>" in out["indNone"] and "Nobody online" in out["indNone"]
    assert ">–</span></div>" in out["indNet"] and ">0</span></div>" not in out["indNet"] and "Now: no data" in out["indNet"]
    # BERLIN: żółty napis i szare pole; czerwony napis (pref), gdy z ATIS nie wiadomo, który pas
    ber, pref = out["ber"], out["berPref"]
    assert ber.startswith('<div class="rb-blbl" data-rt="BERLIN: ') and re.search(r'<div class="rb-bln" data-rt="[^"]*">EAST</div>$', ber)
    assert "ATIS EDDB: RWY 06L/06R" in ber and "Red text" not in ber
    assert re.search(r'<div class="rb-bln pref" data-rt="[^"]*">WEST</div>$', pref) and "Red text: preferred configuration" in pref
    assert re.search(r'<div class="rb-bln" data-rt="[^"]*">–</div>$', out["berNone"])
    # bez danych o zalogowanych: kreska jak we wskaźnikach, nie czerwona konfiguracja z wiatru
    for k in ("berNet", "berUnknown"):
        assert re.search(r'<div class="rb-bln" data-rt="[^"]*">–</div>$', out[k]) and "Red text" not in out[k], k
        assert "ATIS unknown: no network data" in out[k], k
    # dymki mówią, co to jest, nie skąd są dane
    for key, h in out.items():
        assert not re.search(r"Coverage order|coverage order|VACS|VATSIM|VATSpy|\.ese|›", str(h)), key
    ev = out["evil"]
    assert "<img" not in ev and "<i>t" not in ev and "<s>" not in ev and "<u>" not in ev and "<b>" not in ev
    assert "&lt;img src=x&gt;" in ev and "&lt;b&gt;" in ev
    # dymek wskaźnika i BERLIN (tekst z ATIS EDDB z sieci): tip i zalogowani tylko jako tekst w data-rt, bez wyjścia
    # z atrybutu; <em> – nie z <i> liczb między kafelkami (markHtml)
    assert "<em" not in ev and '"><em' not in ev
    assert ('<div class="rb-indc" data-rt="&lt;b&gt;: &quot;&gt;&lt;em&gt;x&lt;/em&gt;\n&quot;&gt;&lt;em&gt;c'
            ' – &lt;em&gt;n"><div class="rb-ind">&lt;b&gt;</div>') in ev
    assert re.search(r'<div class="rb-blbl" data-rt="BERLIN: [^"<>]*\n&quot;&gt;&lt;em&gt;y&lt;/em&gt;">BERLIN</div>'
                     r'<div class="rb-bln" data-rt="[^"<>]*">&lt;b&gt;</div>$', ev)


LBL_SCRIPT = r"""
const radio = await import(process.argv[2]);
// plakietki z tablicy: częstotliwość online albo z tablicy, nazwa stanowiska, kontroler online, kto, opis
const FQ = { EPWA_APP: "128.805", EPWA_S_APP: "135.930", EPWA_N_APP: "125.055", EPWA_TWR: "118.305", EPWA_ATIS: "120.455",
  EPWW_N_CTR: "130.675", EPWW_DBT_CTR: "134.225", EPWA_I_APP: "123.975" };
const ctx = (online) => ({ freq: (cs) => online[cs]?.frequency || FQ[cs] || "", nm: (cs) => cs.replace(/^EP/, "").replace(/_/g, " "),
  dn: (cs) => `name ${cs}`, on: (cs) => online[cs] || null, who: (cs) => (online[cs] ? `${cs} ${online[cs].frequency} – Jan` : ""),
  pos: (cs, fq = "") => `${cs} · pos${fq ? ` ${fq}` : ""}`, net: true });
const ON = (...cs) => Object.fromEntries(cs.map((c) => [c, { callsign: c, frequency: FQ[c], atis_code: /_ATIS$/.test(c) ? "K" : null }]));
const TMA = [["TMA Warszawa · EPWA_APP", "EPWA_APP", 0, 9500], ["TMA Warszawa · EPWA_N_APP", "EPWA_N_APP", 2500, 9500],
  ["TMA Warszawa · EPWA_S_APP", "EPWA_S_APP", 2500, 9500], ["TMA Radom", "EPWA_S_APP", 3500, 9500]]
  .map(([id, nominal, lo, hi]) => ({ id, nominal, lo, hi, tma: id.split(" · ")[0], icao: "EPWA", owners: [] }));
const flow = { tma: { "TMA Warszawa": [{ tip: ["Flow restriction: max occupancy 20 until 18:00Z"] }], "TMA Radom": [{ tip: ["Occupancy 9 of 10"] }] } };
const plate = (owner, covers, at = [52.1, 21.0]) => ({ owner, tma: "TMA Warszawa", icao: "EPWA", at, frequency: FQ[owner], covers,
  parts: covers.filter((c) => c.startsWith("TMA Warszawa")).map((c) => c.split(" · ")[1]) });
const ctr = { id: "CTR Warszawa", nominal: "EPWA_TWR", atis: "EPWA_ATIS", owners: [] };
const twrP = (twr, atis) => ({ id: "CTR Warszawa", icao: "EPWA", at: [52.17, 20.92], twr, atis, frequency: twr.length ? FQ[twr[0]] : null });
const sec = (letter) => ({ id: `L${letter}`, letter, nominal: "EPWW_DBT_CTR", chain: ["EPWW_DBT_CTR", "EPWW_N_CTR"] });
const bd = { acc_short: { EPWW_N_CTR: "N", EPWW_DBT_CTR: "DBT" }, flow: { sectors: { LG: [{ tip: ["Occupancy 12 of 14"] }] } } };
const FIS = [{ id: "FIS Warszawa", hi: 9500, owners: ["EPWA_I_APP"], at: [52.5, 21.5] }, { id: "FIS Warszawa", hi: 9500, owners: ["EPWA_I_APP"], at: [52.6, 20.5] },
  { id: "FIS Kraków", hi: 9500, owners: [], at: [50.1, 20.0] }];
const o = {
  // plakietki APP: sam WA APP na całą TMA Warszawa (i TMA Radom), WA S APP na swoją część i TMA Radom
  appAll: radio.appPlate(plate("EPWA_APP", TMA.map((g) => g.id)), ctx(ON("EPWA_APP")), TMA, flow),
  appS: radio.appPlate(plate("EPWA_S_APP", ["TMA Warszawa · EPWA_S_APP", "TMA Radom"]), ctx(ON("EPWA_S_APP")), TMA, null),
  // plakietki TWR: wieża online (TWR i TWR/A z ATIS), sam ATIS na TWR/A
  twrOn: [false, true].map((twra) => radio.twrPlate(twrP(["EPWA_TWR"], ["EPWA_ATIS"]), ctr, ctx(ON("EPWA_TWR", "EPWA_ATIS")), twra)),
  atisOnly: radio.twrPlate(twrP([], ["EPWA_ATIS"]), { ...ctr, owners: ["EPWA_APP"] }, ctx(ON("EPWA_ATIS", "EPWA_APP")), true),
  // ATIS online na innej częstotliwości niż z listy stanowisk: w dymku ta z sieci, jak na plakietce
  atisFq: radio.twrPlate(twrP(["EPWA_TWR"], ["EPWA_ATIS"]), ctr,
    ctx({ ...ON("EPWA_TWR"), EPWA_ATIS: { callsign: "EPWA_ATIS", frequency: "121.080", atis_code: "K" } }), true),
  atisOff: radio.twrPlate(twrP(["EPWA_TWR"], []), ctr, ctx(ON("EPWA_TWR")), true),
  // ACC: kilka sektorów warstwy – skrót stanowiska, jeden – litera i warstwa
  acc: radio.accPlate({ owner: "EPWW_N_CTR", sectors: [sec("B"), sec("G")], at: [52, 19] }, "LOW", ctx(ON("EPWW_N_CTR")), bd),
  accOne: radio.accPlate({ owner: "EPWW_DBT_CTR", sectors: [sec("B")], at: [53, 16] }, "HIGH", ctx(ON("EPWW_DBT_CTR")), bd),
  fis: radio.fisPlate("EPWA_I_APP", [52.4, 21.0], ctx(ON("EPWA_I_APP")), FIS),
  fisAt: radio.fisPlate("EPWA_I_APP", null, ctx(ON("EPWA_I_APP")), FIS).at,
  evil: radio.plateHtml({ kind: "app", k: '"><b>k', id: "<img src=x>", fq: "<s>1</s>", code: "<i>", rt: '"><b>x</b>' }),
};
o.html = Object.fromEntries(["appAll", "acc", "accOne", "fis", "atisOnly"].map((k) => [k, radio.plateHtml(o[k])]));
o.html.twr = o.twrOn.map(radio.plateHtml);
console.log(JSON.stringify(o));
"""


def test_js_plates(tmp_path):
    """Plakietki podglądów (tabs/radio.js, 0.13.2 – issue #27: jak kafelki – jasne pole, częstotliwość, małe ID w prawym
    górnym rogu, tylko stanowiska online): ACC (accPlate: jeden sektor warstwy – "B HIGH", kilka – skrót stanowiska),
    APP (appPlate: ID stanowiska i jego częstotliwość, w dymku TMA, części, inne obsługiwane TMA i alarmy przepływu),
    TWR (twrPlate: wieża online, na TWR/A z żółtą literą ATIS obok ID; sam ATIS – ciemna plakietka z częstotliwością
    ATIS), FIS (fisPlate: jedna na stanowisko, w dymku jego obszary). Każda z częstotliwością, dane przez esc()."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    script = tmp_path / "lbl.mjs"
    script.write_text(LBL_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "tabs" / "radio.js").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # plakietka APP: ID i częstotliwość stanowiska, w punkcie z tablicy; dymek bez kolejności przejmowania
    a = out["appAll"]
    assert {k: a[k] for k in ("at", "kind", "k", "id", "fq", "state")} == {
        "at": [52.1, 21.0], "kind": "app", "k": "EPWA_APP", "id": "WA APP", "fq": "128.805", "state": "on"}
    assert a["rt"].split("\n") == ["TMA Warszawa – all parts (GND–FL095)", "Position: EPWA_APP · pos",
                                   "Now: EPWA_APP 128.805 – Jan", "Also covers: TMA Radom",
                                   "Flow restriction: max occupancy 20 until 18:00Z", "TMA Radom: Occupancy 9 of 10"]
    assert out["appS"]["rt"].split("\n")[0] == "TMA Warszawa – part WA S APP (FL025–FL095)"
    # wygląd kafelka: ID w prawym górnym rogu (rb-tr), pod nim częstotliwość; data-k = granica stanowiska na podglądzie
    assert out["html"]["appAll"] == ('<div class="rb-pl app on" data-k="EPWA_APP" data-rt="' + a["rt"].replace("\n", "\n")
                                     + '"><span class="rb-tr"><span class="rb-id">WA APP</span></span><span class="rb-fq">128.805</span></div>')
    # plakietka TWR: wieża online; litera ATIS tylko na TWR/A (żółte pole obok ID); kliknięcie: AERODROME
    t0, t1 = out["twrOn"]
    assert (t0["state"], t0["fq"], t0["code"], t0["atis"]) == ("on", "118.305", "", False) and t1["code"] == "K"
    h0, h1 = out["html"]["twr"]
    assert '<span class="rb-tr"><span class="rb-id">WA TWR</span></span><span class="rb-fq">118.305</span>' in h0
    assert '<span class="rb-tr"><b class="rb-code">K</b><span class="rb-id">WA TWR</span></span><span class="rb-fq">118.305</span>' in h1
    assert 'class="rb-pl twr on" data-k="EPWA" data-icao="EPWA" tabindex="0" role="button"' in h1
    assert t1["icao"] == "EPWA" and t1["rt"].split("\n")[-1] == "Click: AERODROME"
    assert "ATIS: EPWA_ATIS · pos 120.455 – online, information K" in t1["rt"]
    assert "ATIS: EPWA_ATIS · pos 121.080 – online, information K" in out["atisFq"]["rt"]
    assert "ATIS: EPWA_ATIS · pos – offline" in out["atisOff"]["rt"] and out["atisOff"]["code"] == ""
    # sam ATIS (wieża offline, TWR/A): ciemna plakietka z częstotliwością ATIS (jasnofioletowa: klasa atis), w dymku,
    # kto przejmuje wieżę
    ao = out["atisOnly"]
    assert (ao["state"], ao["atis"], ao["id"], ao["fq"], ao["code"]) == ("off", True, "WA ATIS", "120.455", "K")
    assert out["html"]["atisOnly"].startswith('<div class="rb-pl twr off atis" data-k="EPWA" data-icao="EPWA"')
    assert "Tower offline – covered by EPWA_APP 128.805 – Jan" in ao["rt"]
    # ACC: nazwa wg liczby sektorów warstwy, częstotliwość stanowiska, w dymku warstwa z przekrojem i alarmy przepływu
    acc, one = out["acc"], out["accOne"]
    assert (acc["kind"], acc["k"], acc["id"], acc["fq"]) == ("acc", "EPWW_N_CTR", "N", "130.675")
    assert acc["rt"].split("\n") == ["name EPWW_N_CTR · LOW FL330", "Now: EPWW_N_CTR 130.675 – Jan", "Sectors: LB, LG",
                                     "LG: Occupancy 12 of 14"]
    assert (one["id"], one["fq"]) == ("B HIGH", "134.225") and one["rt"].startswith("name EPWW_DBT_CTR · HIGH FL400")
    assert '<span class="rb-id">B HIGH</span></span><span class="rb-fq">134.225</span>' in out["html"]["accOne"]
    # FIS: jedna plakietka na stanowisko, w dymku jego obszary (bez powtórek); punkt z sumy obszarów, bez niej – obszar
    f = out["fis"]
    assert (f["kind"], f["k"], f["id"], f["fq"], f["at"]) == ("fis", "EPWA_I_APP", "WA I APP", "123.975", [52.4, 21.0])
    assert f["rt"].split("\n") == ["FIS Warszawa (up to FL095)", "Position: EPWA_I_APP · pos", "Now: EPWA_I_APP 123.975 – Jan"]
    assert out["fisAt"] == [52.5, 21.5]
    ev = out["evil"]
    assert "<img" not in ev and "<b>" not in ev and "<s>" not in ev and "<i>" not in ev and "&lt;img src=x&gt;" in ev
    assert 'data-k="&quot;&gt;&lt;b&gt;k"' in ev


TIP_SCRIPT = r"""
const radio = await import(process.argv[2]);
const WHO = { EPWW_N_CTR: "EPWW_N_CTR 130.675 – Tomasz (CID 11)", EPWA_APP: "EPWA_APP 128.805 – Jan (CID 12)" };
const x = (net = true) => ({ who: (cs) => WHO[cs] || "", pos: (cs) => `${cs} · Warszawa Approach 128.805`, net });
const ch = ["EPRA_TWR", "EPWA_S_APP", "EPWA_APP", "EPWW_C_CTR", "EPWW_N_CTR"];
const acc = { owner: "EPWW_N_CTR", sectors: [{ id: "LB", nominal: "EPWW_DBT_CTR", chain: ["EPWW_DBT_CTR", "EPWW_N_CTR"] },
  { id: "LG", nominal: "EPWW_G_CTR", chain: ["EPWW_G_CTR", "EPWW_N_CTR"] }] };
const tma = (owners, topdown = null) => ({ nominal: "EPWA_S_APP", owners, topdown, chains: [ch] });
console.log(JSON.stringify({
  acc: radio.accTip(acc, "EPWW N · LOW FL095–FL335", x()),
  app: radio.groupTip(tma(["EPWA_APP"]), "TMA Radom (FL035–FL095)", x()),
  proc: radio.groupTip(tma([]), "TMA Szczecin (GND–FL095)", x(), ["Procedural TMA (no APP): tower frequency SC TWR"]),
  top: radio.groupTip(tma([], "EPWW_N_CTR"), "TMA Radom (FL035–FL095)", x()),
  none: radio.groupTip(tma([]), "TMA Radom (FL035–FL095)", x()),
  nonet: radio.groupTip(tma([]), "TMA Radom (FL035–FL095)", x(false)),
  cov: radio.groupTip(tma(["EPWA_APP"]), "CTR Radom · EPRA", x(), ["Click: AERODROME"], "Tower offline – covered by EPWA_APP"),
  now: [radio.nowText([], x()), radio.nowText([], x(false)), radio.nowText(["EPWA_APP", "EPWW_N_CTR"], x())],
  accFlow: radio.accTip(acc, "EPWW N · LOW FL095–FL335", x(), { sectors: { LG: [{ tip: ["Occupancy 12 of 14"] }] } }),
}));
"""


def test_js_preview_tooltips(tmp_path):
    """Dymki podglądów (tabs/radio.js accTip, groupTip, nowText; runda 15, Marek: "wywal hierarchię dziedziczenia"):
    przestrzeń, stanowisko i kto ją teraz obsługuje – bez kolejności przejmowania (Coverage order, ›) i bez stanowiska
    sektora z kolejnością; bez danych o zalogowanych "Now: no data" bez nazwy dostawcy."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    script = tmp_path / "tip.mjs"
    script.write_text(TIP_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "tabs" / "radio.js").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["acc"].split("\n") == ["EPWW N · LOW FL095–FL335", "Now: EPWW_N_CTR 130.675 – Tomasz (CID 11)", "Sectors: LB, LG"]
    pos = "Position: EPWA_S_APP · Warszawa Approach 128.805"
    assert out["app"].split("\n") == ["TMA Radom (FL035–FL095)", pos, "Now: EPWA_APP 128.805 – Jan (CID 12)"]
    assert out["proc"].split("\n")[3:] == ["Procedural TMA (no APP): tower frequency SC TWR"]
    assert out["top"].split("\n")[2] == "Now top-down: EPWW_N_CTR 130.675 – Tomasz (CID 11)"
    assert out["none"].split("\n") == ["TMA Radom (FL035–FL095)", pos, "Now: unstaffed"]
    assert out["nonet"].split("\n")[2] == "Now: no data"
    assert out["cov"].split("\n") == ["CTR Radom · EPRA", pos, "Tower offline – covered by EPWA_APP", "Click: AERODROME"]
    assert out["now"] == ["Now: unstaffed", "Now: no data",
                          "Now: EPWA_APP 128.805 – Jan (CID 12)\nNow: EPWW_N_CTR 130.675 – Tomasz (CID 11)"]
    # alarm przepływu sektora w obszarze stanowiska: sektor i powód
    assert out["accFlow"].split("\n")[3:] == ["LG: Occupancy 12 of 14"]
    for key, t in out.items():
        assert not re.search(r"Coverage order|coverage order|sector position|›|VATSIM|VACS", json.dumps(t)), key
        assert "EPRA_TWR" not in json.dumps(t) and "EPWW_C_CTR" not in json.dumps(t), key  # nic z kolejności


FLOW_SCRIPT = r"""
// czerwone tło alarmów przepływu (flowAreas, flowSvg) i miejsce dymku (tipPos)
import { createRequire } from "module";
const radio = await import(process.argv[2]);
const rb = await import(process.argv[3]);
console.warn = () => {};
const sq = (x0, y0, d = 1) => ({ type: "Polygon", coordinates: [[[x0, y0], [x0 + d, y0], [x0 + d, y0 + d], [x0, y0 + d], [x0, y0]]] });
const bd = {
  sectors: [{ id: "HB", layer: "HIGH", letter: "B", owner: null }, { id: "LB", layer: "LOW", letter: "B", owner: "EPWW_N_CTR" },
    { id: "LC", layer: "LOW", letter: "C", owner: "EPWW_N_CTR" }],
  tma: [{ tma: "TMA Warszawa", owners: ["EPWA_APP"] }, { tma: "TMA Warszawa", owners: [] }],
  flow: { ok: true, sectors: { HB: [{ tip: ["Occupancy 12 of 14"] }], LC: [] },
    tma: { "TMA Warszawa": [{ tip: ["Flow restriction: max occupancy 20 until 18:00Z"] }], "TMA Nowhere": [{ tip: ["x"] }] } },
};
const slices = [{ letter: "B", name: "EPWWB", lo: 36500, geometry: sq(20, 52) }, { letter: "C", name: "EPWWC", lo: 9500, geometry: sq(18, 52) }];
const tmaGeo = [{ name: "EPWA_TMA_A", tma: "TMA Warszawa", geometry: sq(20.5, 52, 0.4) }, { name: "EPWA_TMA_B", tma: "TMA Warszawa", geometry: sq(20.7, 52.1, 0.4) },
  { name: "CTA01", tma: null, geometry: sq(10, 50) }];
const x = { who: (cs) => `${cs} online`, net: true };
const P = ([lon, lat]) => [lon * 10, (60 - lat) * 10];
const out = {};
for (const lib of [true, false]) {
  globalThis.polygonClipping = lib ? createRequire(import.meta.url)(process.argv[4]) : undefined;
  const k = lib ? "lib" : "nolib";
  out[k] = Object.fromEntries(["LOW", "MID", "HIGH"].map((key) => {
    const a = radio.flowAreas(bd, key, slices, tmaGeo, x, k);
    return [key, { areas: a.map((v) => ({ id: v.id, kind: v.kind, union: !!v.geom, rt: v.rt })), svg: radio.flowSvg(a, P) }];
  }));
}
out.empty = radio.flowSvg(radio.flowAreas({ sectors: bd.sectors, flow: { ok: false, sectors: {}, tma: {} } }, "HIGH", slices, tmaGeo, x), P);
// 0.13.2 (przegląd): czerwone tło tylko w granicy FIR EPWW (sektor B wychodzi za granicę – zostaje część w niej)
globalThis.polygonClipping = createRequire(import.meta.url)(process.argv[4]);
out.clip = ["HIGH", "LOW"].map((key) => radio.flowAreas(bd, key, slices, tmaGeo, x, "clip", sq(17.5, 51.5, 3)).map((a) => rb.bboxOf(a.geom)));
const V = [1366, 768], W = 360;
out.tip = {
  mid: rb.tipPos(600, 300, W, 120, ...V), right: rb.tipPos(1300, 300, W, 120, ...V),
  edge: [rb.tipPos(V[0] - 12 - 14 - W, 300, W, 120, ...V), rb.tipPos(V[0] - 12 - 14 - W + 1, 300, W, 120, ...V)],
  bottom: rb.tipPos(600, 700, W, 200, ...V), corner: rb.tipPos(1350, 760, W, 200, ...V),
  narrow: rb.tipPos(150, 300, W, 120, 300, 768), tall: rb.tipPos(600, 100, W, 900, ...V), gap: rb.TIP_GAP,
  // dymek, który mieści się w oknie (radio.css: najwyżej okno bez dwóch odstępów), nigdy nie wychodzi poza dolną krawędź
  fits: [120, 300, 700, V[1] - 24].flatMap((h) => [0, 10, 100, 384, 600, 760, V[1] - 1].map((cy) => {
    const p = rb.tipPos(600, cy, W, h, ...V);
    return p.top >= 12 && p.top + h <= V[1] - 12;
  })),
};
// panel LOA: po stronie FIR-u z większym miejscem i nie szerszy niż ono (siatka 1210 px; FIR przy lewej krawędzi, blisko
// środka z lewej i z prawej, wąska strona)
out.loa = [rb.loaPlace(80, 240, 1210), rb.loaPlace(500, 660, 1210), rb.loaPlace(850, 930, 1210), rb.loaPlace(300, 500, 700)];
console.log(JSON.stringify(out));
"""


def test_js_flow_and_tip_position(tmp_path):
    """0.13.0 (Marek): czerwone tło przestrzeni z ograniczeniem przepływu albo zajętością ponad 80 % – sektor ACC na
    podglądzie swojej warstwy, TMA na LOW (jeden obrys sumy jej kształtów), także bez nikogo, w dymku powód; dymek
    stałej szerokości, na prawo od kursora, przy prawej krawędzi okna na lewo (12 px od brzegu), przy dolnej nad
    kursorem; szerokość nigdy nie maleje (radio.css)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    pc = tmp_path / "pc.cjs"
    pc.write_text((FRONTEND / "vendor" / "polygon-clipping" / "polygon-clipping.umd.min.js").read_text("utf-8"), "utf-8")
    script = tmp_path / "flow.mjs"
    script.write_text(FLOW_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "tabs" / "radio.js").as_uri(), (d / "radioboard.js").as_uri(), str(pc)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    lib = out["lib"]
    # HIGH: sektor HB (bez nikogo) czerwony; LOW: TMA Warszawa (LB bez alarmu, LC z pustą listą, TMA bez kształtów
    # i CTA bez klucza pominięte); MID: nic
    assert [(a["id"], a["kind"], a["union"]) for a in lib["HIGH"]["areas"]] == [("HB", "acc", True)]
    assert [(a["id"], a["kind"], a["union"]) for a in lib["LOW"]["areas"]] == [("TMA Warszawa", "tma", True)]
    assert lib["MID"]["areas"] == [] and lib["MID"]["svg"] == "" and out["empty"] == ""
    # z granicą FIR EPWW (kwadrat 17,5–20,5 E, 51,5–54,5 N): sektor HB (20–21 E) i TMA (do 21,1 E) przycięte do granicy
    assert out["clip"] == [[[20, 52, 20.5, 53]], []]  # TMA (20,5–21,1 E) cała za granicą: bez tła
    assert lib["HIGH"]["areas"][0]["rt"].split("\n") == ["Sector HB · HIGH", "Now: unstaffed", "Occupancy 12 of 14"]
    assert lib["LOW"]["areas"][0]["rt"].split("\n") == ["TMA Warszawa", "Now: EPWA_APP online",
                                                          "Flow restriction: max occupancy 20 until 18:00Z"]
    # klasa flow na ścieżce przestrzeni, jeden obrys TMA (suma dwóch kształtów), dymek z powodem
    hb, wa = lib["HIGH"]["svg"], lib["LOW"]["svg"]
    assert hb.startswith('<g class="rb-flow"><path class="flow acc" data-rt="Sector HB') and "Occupancy 12 of 14" in hb
    assert '<path class="flow tma" data-rt="TMA Warszawa' in wa and re.search(r' d="M[^M"]+Z"', wa)
    # bez biblioteki sumy: same wypełnienia kształtów (fb), bez granicy
    nolib = out["nolib"]["LOW"]["svg"]
    assert '<path class="flow tma fb"' in nolib and re.search(r' d="([^"]*)"', nolib).group(1).count("M") == 2
    t, g = out["tip"], out["tip"]["gap"]
    assert g == 12
    assert t["mid"] == {"left": 614, "top": 316, "flipX": False, "flipY": False}
    # przy prawej krawędzi: na lewo od kursora, pełna szerokość i co najmniej 12 px od brzegu
    assert t["right"]["flipX"] and t["right"]["left"] == 1300 - 14 - 360 and t["right"]["left"] + 360 <= 1366 - g
    assert not t["edge"][0]["flipX"] and t["edge"][0]["left"] + 360 == 1366 - g and t["edge"][1]["flipX"]
    # przy dolnej krawędzi nad kursorem; w rogu w obie strony; wąskie okno i wysoki dymek – 12 px od brzegu
    assert t["bottom"]["flipY"] and t["bottom"]["top"] == 700 - 10 - 200 and not t["bottom"]["flipX"]
    assert t["corner"]["flipX"] and t["corner"]["flipY"] and t["corner"]["top"] + 200 <= 768 - g
    assert t["narrow"]["left"] == g and t["tall"]["top"] == g
    assert all(t["fits"]), t["fits"]
    # LOA: FIR z lewej – panel z prawej w pełnej szerokości; ESAA/LKAA blisko środka – z prawej, nie dalej niż do ich
    # okienek; LZBB/UMKK – z lewej; za mało miejsca – co najmniej LOA_MIN
    assert out["loa"] == [{"left": False, "width": 871}, {"left": False, "width": 542}, {"left": True, "width": 842},
                          {"left": True, "width": 420}]
    css = (FRONTEND / "css" / "radio.css").read_text("utf-8")
    tip = re.search(r"\.rb-tip \{([^}]*)\}", css).group(1)
    assert "width: 360px" in tip and "box-sizing: border-box" in tip and "max-width: 480px" not in tip and "white-space: pre-wrap" in tip
    assert "max-height: calc(100vh - 24px)" in tip and "overflow: hidden" in tip  # wysoki dymek nie wychodzi poza okno
    flow = re.search(r"\.rb-flow path \{([^}]*)\}", css).group(1)
    assert "fill: var(--rb-flow)" in flow and re.search(r"--rb-flow: #[0-9a-f]{6}", css)
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    assert "tipPos(e.clientX, e.clientY, tip.offsetWidth, tip.offsetHeight, window.innerWidth, window.innerHeight)" in radio


def test_radio_page_without_provenance_notes():
    """Runda 15 (Marek): na stronie RADIO bez kolejności przejmowania i bez dopisków, skąd jest wartość, opis albo układ
    (VACS, VATSpy, plik .ese/sektora, om.plvacc.pl, VATSIM jako źródło) – w kodzie strony poza komentarzami."""
    for name in ("tabs/radio.js", "radioboard.js"):
        lines = (FRONTEND / "js" / name).read_text("utf-8").splitlines()
        code = "\n".join(re.sub(r"\s//\s.*$", "", ln) for ln in lines if not ln.lstrip().startswith("//"))
        for bad in ("Coverage order", "coverage order", "sector position", "VACS", "VATSpy", ".ese", "sector file",
                    "om.plvacc", "VATSIM", "PDF extract", "per LOA", "chainText", "in this part", "g.apps"):
            assert bad not in code, (name, bad)



def test_radio_files_ascii_and_no_source_names():
    """Konwencja: w JS strony RADIO znaki spoza ASCII tylko w samodzielnych liniach komentarza (w kodzie, napisach i
    komentarzach na końcu linii escape \\u); w plikach RADIO, także w komentarzach i w radio.css, bez nazw źródeł danych."""
    for name in ("tabs/radio.js", "radioboard.js"):
        for n, ln in enumerate((FRONTEND / "js" / name).read_text("utf-8").splitlines(), 1):
            assert ln.lstrip().startswith("//") or ln.isascii(), (name, n, ln)
    for f in (FRONTEND / "js" / "tabs" / "radio.js", FRONTEND / "js" / "radioboard.js", FRONTEND / "css" / "radio.css"):
        text = f.read_text("utf-8").lower()
        for bad in ("euroscope", "plik sektora", "pliku sektora", ".sct", "vacs", "vatspy", "vatsim", ".ese", "viff"):
            assert bad not in text, (f.name, bad)


def test_radio_keyboard_mid_title_and_small_plates():
    """0.13.2 (przegląd): Esc zamyka panel LOA z każdego miejsca strony (nasłuch na dokumencie, gdy RADIO jest widoczne,
    zdjęty w destroy – fokus znika z kodu FIR-u przy odświeżaniu i po kliknięciu w tekst panelu); fokus z klawiatury
    wraca po odświeżeniu na ten sam kod FIR-u, plakietkę TWR albo ATIS (focusSel); mały MID pod swoim tytułem (czarne
    tło tytułu zasłaniało róg granicy FIR-u na 1600×900 i 1366×768); na 1366×768 litera ATIS na plakietce TWR/A tej
    samej wysokości co ID (częstotliwość siedziała na dolnej krawędzi)."""
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    css = (FRONTEND / "css" / "radio.css").read_text("utf-8")
    assert radio.count('"Escape"') == 1 and 'e.key !== "Escape" || loaBox.hidden || !visible()' in radio
    assert 'document.addEventListener("keydown", onKey)' in radio and 'document.removeEventListener("keydown", onKey)' in radio
    body = re.search(r"function renderAll\(\) \{(.*?)\n    \}\n", radio, re.S).group(1)
    assert "focusSel(a)" in body and "focus({ preventScroll: true })" in body and body.index("renderPage") < body.rindex("focus(")
    mp = re.search(r"function renderMap\(m\) \{(.*?)\n    \}\n", radio, re.S).group(1)
    assert mp.index("renderTitle(m)") < mp.index("projection(") and 'm.key === "MID" ? "bottom" : "middle"' in mp
    assert 'm.key === "MID" && t?.offsetHeight ? t.offsetTop + t.offsetHeight + 2 : 0' in mp
    small = re.search(r"@media \(max-height: 820px\) \{(.*?)\n\}", css, re.S).group(1)
    assert re.search(r"\.rb-pl \.rb-fq, \.rb-pl \.rb-code, \.rb-bd \{ line-height: 1; \}", small)


def test_frontend_imports_resolve():
    # stare moduły RADIO usunięte: nic ich nie importuje, każdy import względny wskazuje istniejący plik
    js_dir = FRONTEND / "js"
    gone = {"radiostate.js", "geo.js", "sectorsplit.js"}
    assert not any((js_dir / g).exists() for g in gone)
    for f in js_dir.rglob("*.js"):
        for spec in re.findall(r"""(?:from|import)\s*\(?\s*["'](\.{1,2}/[^"']+)["']""", f.read_text("utf-8")):
            assert (f.parent / spec).resolve().is_file(), f"{f.relative_to(FRONTEND)}: {spec}"
    index = (FRONTEND / "index.html").read_text("utf-8")
    assert "sectors.css" not in index and not (FRONTEND / "css" / "sectors.css").exists()
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    assert "subtabs(" not in radio and "text-shadow" not in (FRONTEND / "css" / "radio.css").read_text("utf-8")


def test_layer_column_buttons_fit_label():
    """Runda 14 (przegląd): "TWR/ATIS" w jednej trzeciej rzędu LOW MID HIGH był ucięty przy 1280–1600 px. 0.13.1
    (issue #25): przyciski 137 × 28 z marginesem 1,5 px (liczby w radio.css). 0.13.2 (issue #27): przyciski w kolumnie H
    siatki szkicu (--rb-hw), LOW MID HIGH w jednym wierszu – szerokie na jedną trzecią kolumny (najwyżej 137 px), ale
    nie mniej niż napis z odstępem po bokach, wysokość 28 px, najwyżej wysokość kafelka (sprawdzone w przeglądarce przy
    1366×768, 1600×900 i 1920×1080). Włączona warstwa – kolorem, bez pogrubienia."""
    css = (FRONTEND / "css" / "radio.css").read_text("utf-8")
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    body = re.search(r"\.rb-btns button \{([^}]*)\}", css).group(1)
    assert "width: calc(min(137px + 3px, var(--rb-hw) / 3) - 3px)" in body and "min-width: max-content" in body
    assert "height: 28px" in body and "max-height: calc(100% - 3px)" in body and "margin: 1.5px" in body
    assert re.search(r"padding: 0 [1-9]\d*px", body)  # odstęp po bokach napisu
    assert "border-radius: 0" in body and "font: 400 " in body
    on = re.search(r"\.rb-btns button\.on \{([^}]*)\}", css).group(1)
    assert "background:" in on and "color:" in on and "font-weight" not in on
    assert re.search(r"\.rb-bt \{[^}]*display: flex;[^}]*justify-content: center", css)
    assert "--rb-hw: clamp(200px, 15vw, 330px)" in css
    # cała strona RADIO zwykłą grubością, czcionką bezszeryfową (układ nie zależy od czcionki o stałej szerokości)
    assert not re.search(r"font-weight:\s*(?:bold|[5-9]00)|font:\s*(?:bold|[5-9]00)\b|var\(--mono\)", css)
    assert "font-weight" not in radio and re.search(r"\.rb b, \.rb strong[^{]*\{ font-weight: 400; \}", css)  # <b> też zwykłą
    # bez zaokrągleń, poświaty i cieni
    assert not re.search(r"border-radius: [1-9]|box-shadow|text-shadow|drop-shadow|filter:", css)
    # ATIS (0.13.1): bez osobnego paska – w górnym rzędzie na prawo od wskaźników, stałej wysokości; wyłączony chowa
    # tylko treść (wskaźniki i siatka się nie przesuwają)
    assert re.search(r"\.rb-atis \{[^}]*flex: 1 1 auto;[^}]*height: \d+px", css)
    assert ".rb-atis.off .rb-atis-in { visibility: hidden; }" in css
    assert '<div class="rb-cfg"><div class="rb-inds"></div><div class="rb-atis"' in radio
    # wskaźniki dużo mniejsze niż w 0.13.0 (93 × 38): pole 60 × 20; kafelek stałego rozmiaru bez granic na nim
    ind = re.search(r"\.rb-indv \{([^}]*)\}", css).group(1)
    assert "width: 60px" in ind and "height: 20px" in ind
    assert "--rb-tw: calc(var(--rb-f) * 4.7 + 10px)" in css and "--rb-th: calc(var(--rb-f) * 1.75 + 7px)" in css
    # plakietka podglądu jak kafelek (ten sam wygląd, najmniej jego rozmiar)
    assert ".rb-box, .rb-pl {" in css and ".rb-box.on, .rb-pl.on {" in css
    assert re.search(r"\.rb-pl \{[^}]*min-width: var\(--rb-tw\); height: var\(--rb-th\)", css)
    # siatka strony: tory z radio.js (pageGrid), kody, kafelki i przyciski w tej samej siatce
    assert re.search(r"\.rb-page \{[^}]*display: grid", css) and ".rb-nbs, .rb-btns { display: contents; }" in css
    assert "page.style.gridTemplateRows = pg.rows.join" in radio and "page.style.gridTemplateColumns = pg.cols.join" in radio
    # liczby przy swoich kafelkach w rozciągniętym rzędzie liczb
    for at, rule in (("up", "align-self: end"), ("dn", "align-self: start"), ("two", "justify-content: space-between")):
        assert re.search(rf"\.rb-bd\.{at} \{{[^}}]*{rule}", css), at
    # podglądy (0.13.2, Marek): czarne, kolory jako zmienne – granatowa granica stanowiska online, szare sektory bez
    # nikogo, cienkie granice FIR-ów
    assert "--rb-navy: #2f45c8" in css and re.search(r"\.rb-own path \{[^}]*stroke: var\(--rb-navy\); stroke-width: 2", css)
    assert re.search(r"\.rb-free path \{[^}]*fill: var\(--rb-free\)", css) and ".rb-land { fill: #000; }" in css
    assert re.search(r"\.rb-firs path \{[^}]*stroke: var\(--rb-line\)", css) and re.search(r"\.rb-map \{[^}]*background: #000", css)
    # bez suwaka wysokości, linii prowadzących, kropek i sąsiadów na podglądach (do 0.13.1)
    assert not re.search(r"rb-cut|rb-lvl|rb-ticks|rb-lead|rb-dot|rb-marks|rb-nbacc|rb-tmag|rb-ctrg|rb-fisg|rb-nb\b|rb-nbh|rb-unicom"
                         r"|rb-frame", css + radio)
    assert 'type="range"' not in radio and "radio.cut" not in radio.replace("stary wpis radio.cut", "")
    assert "LS_CUT" not in radio and "marksSvg" not in radio and "nbStackHtml" not in radio
    assert not re.search(r"rb-lim|rb-brow|rb-cells|rb-fir\b|\.laid|container-type", css)
    # bez nazw jak z reklam (blokery chowają takie elementy)
    assert not re.search(r"[\"' .](?:ad-|ads\b|banner|sponsor)", css + radio)
    assert "noatis" not in css and "noatis" not in radio
