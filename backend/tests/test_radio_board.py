"""RADIO jako jedna strona (runda 10): GET /api/radio/board, część stała z radioboard.py i czyste funkcje
frontend/js/radioboard.js (Node)."""
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
    assert all(set(s) == {"fir", "title"} for s in rb.STACKS)
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
    d = client.get("/api/radio/board?geo=1").json()
    g = d["geo"]
    assert set(g) == {"border", "firs", "acc", "tma", "ctr", "fis", "nb"}
    assert g["border"]["type"] == "MultiPolygon" and g["border"]["coordinates"]
    assert {f["id"] for f in g["firs"]} >= {"EDWW", "EDMM", "LKAA", "LZBB", "UKLV", "UMMV", "EYVL", "UMKK", "ESAA"}
    assert all("-" not in f["id"] and f["id"] != "EPWW" for f in g["firs"])
    letters = {s["letter"] for s in d["sectors"]}
    assert {a["letter"] for a in g["acc"]} == letters
    assert all(a["lo"] < a["hi"] and a["geometry"]["coordinates"] for a in g["acc"])
    assert g["tma"] and g["ctr"] and g["fis"]
    assert len(json.dumps(g)) < 400_000  # raz na sesję, ale bez przesady
    # geometria zakodowana raz (część stała) i wklejona do odpowiedzi: poza nią ta sama treść co bez geo=1
    r = client.get("/api/radio/board?geo=1")
    assert r.headers["content-type"] == "application/json" and r.json()["geo"] == g
    assert set(d) - {"geo"} == set(client.get("/api/radio/board").json())


def test_board_neighbour_areas(client):
    """0.12.5 (Marek): na podglądach sektory ACC sąsiadów (wg poziomu podglądu, jak EPWW) i TMA/CTR lotnisk sąsiadów
    przy granicy FIR EPWW (LZTT, LKMT, EDDB); obsadzone wg pierwszego stanowiska online z listy OWNER (d.nb)."""
    d = client.get("/api/radio/board?geo=1").json()
    nb = d["geo"]["nb"]
    assert nb and len({a["id"] for a in nb}) == len(nb)
    assert {a["kind"] for a in nb} == {"acc", "app", "twr"}
    for a in nb:
        assert set(a) == {"id", "fir", "name", "kind", "lo", "hi", "geometry"} and a["lo"] < a["hi"] <= rb.TOP_FT
        assert a["geometry"]["type"] == "MultiPolygon" and a["geometry"]["coordinates"], a["name"]
    acc_firs = {a["fir"] for a in nb if a["kind"] == "acc" and a["lo"] <= 30000 < a["hi"]}
    assert {"EDWW", "EDMM", "ESAA", "LKAA", "LZBB", "EYVL", "UMKK", "UKLV", "UMMV"} <= acc_firs  # UMMV z pliku EPWW
    names = {a["name"] for a in nb if a["kind"] != "acc"}
    # Poprad (TWR z TMA), Ostrawa (APP), Berlin (APP przy granicy), Lwów (APP), Kaliningrad (APP)
    assert {"LZTT_CTR", "LZTT_TMA3", "LKMT_TMA1", "LKMT_CTR", "EDWWDBAN1", "EDWWDBAS1", "UKLL_TMA",
            "KALININGRAD TMA L"} <= names
    # w głąb kraju nie: CTR Berlina i Pragi, TMA Pragi z dala od granicy
    assert not names & {"EDDBTWRN", "EDDBTWRS", "LKPR24_TMA1_ARR_P1"}
    assert not any(a["name"].startswith(("TECH ", "T-")) for a in nb)
    # obsadzone: EDWW_FLG_CTR online (FEED) obsługuje wycinki, w których jest pierwszym stanowiskiem online
    assert d["nb"] and all(o == "EDWW_FLG_CTR" for o in d["nb"].values())
    flg = {a["id"] for a in nb if a["name"].startswith("EDWWFLG")}
    assert flg and flg <= set(d["nb"])
    assert "nb" in client.get("/api/radio/board").json()  # stan obsady przy każdym odświeżeniu, geometria raz


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
const bounds = rb.cutBounds([{ lo: 9500, hi: 19500 }, { lo: 19500, hi: 28500 }, { lo: 28500, hi: 33500 }, { lo: 33500, hi: 36500 }],
  { lower_ft: 9500, upper_ft: 33500 });
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
  ids: rb.LAYER_IDS, labels: rb.LAYERS.map((l) => l.label), defaults: rb.DEFAULT_LAYERS, cut: rb.DEFAULT_CUT,
  args: [rb.argOf(L(["high", "atis", "low", "mid"]), 300), rb.argOf(L([]), 250), rb.argOf(L(["fis", "xx", "twra"]), 300)],
  parsed: ["atis,low,mid,high/fl300", "none/fl250", "app,bogus", "", "bogus/flx", "twr/FL95"].map((a) => {
    const p = rb.parseArg(a); return { layers: p.layers ? [...p.layers] : null, cut: p.cut };
  }),
  fl: [rb.flNum(29500), rb.flText(9500), rb.flText(0)],
  bounds, bands: [rb.cutBand(bounds, 300), rb.cutBand(bounds, 50), rb.cutBand(bounds, 400)],
  range: [rb.cutRange({ lower_ft: 9500, upper_ft: 33500 }), rb.cutRange(null), rb.cutRange({ lower_ft: 9500, upper_ft: 9500 })],
  cutAt: [300, 302, 303, 50, 340, "x", 95].map((c) => rb.cutAt(c, rb.cutRange({ lower_ft: 9500, upper_ft: 33500 }))),
  sliceAt: rb.sliceAt([{ lo: 0, hi: 100 }, { lo: 100, hi: 200 }], 100),
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
  // siatka strony: szerokości kolumn wg rodzaju, miejsca w siatce, wiersze przycisków warstw
  tracks: [rb.gridTracks(["box", "btn", "name", "map", "bogus"]), rb.gridTracks(null)],
  areas: [rb.gridArea({ col: 3, row: 7, cols: 1, rows: 2 }), rb.gridArea({ col: 8, row: 16, rows: 6 }), rb.gridArea(null),
    rb.gridArea({ col: "4", row: 0.4, cols: -2, rows: "x" })],
  brows: [rb.buttonRows({ col: 8, rows: { fis: 14, twra: 12, high: 6, low: 6, mid: 6, atis: 5, app: 8, twr: 10, bogus: 3 } }),
    rb.buttonRows({ col: 8, rows: { low: 6, atis: 0 } }), rb.buttonRows(null)],
  // napis okienka: ID i granice jak na szkicu; połączone – nazwa połączonego; dymek: od dolnej do górnej
  boxText: [rb.boxText({ id: "OSE2", label: "OSE2", upper: 660, lower: 365 }), rb.boxText({ id: "ACC", upper: 999, lower: 0 }),
    rb.boxText({ id: "U+M+L+E", label: "L", upper: 660, lower: 95 }), rb.boxText(null)],
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
    assert js["defaults"] == ["atis", "low", "mid", "high"] and js["cut"] == 300
    # stała kolejność warstw w adresie, "none" = żadna, nieznane pomijane
    assert js["args"] == ["atis,low,mid,high/fl300", "none/fl250", "twra,fis/fl300"]
    assert js["parsed"] == [
        {"layers": ["atis", "low", "mid", "high"], "cut": 300}, {"layers": [], "cut": 250},
        {"layers": ["app"], "cut": None}, {"layers": None, "cut": None}, {"layers": None, "cut": None},
        {"layers": ["twr"], "cut": 95}]
    assert js["fl"] == ["295", "FL095", "FL000"]


def test_js_cut_bands(js):
    assert js["bounds"] == [9500, 19500, 28500, 33500]  # wycinek MID (33500–36500) poza warstwą LOW
    assert js["bands"] == [{"i": 2, "lo": 28500, "hi": 33500, "n": 3}, {"i": 0, "lo": 9500, "hi": 19500, "n": 3},
                           {"i": 2, "lo": 28500, "hi": 33500, "n": 3}]
    # suwak LOW: od dolnej granicy warstwy do 500 ft pod górną, co 500 ft; poziom spoza zakresu albo między krokami
    # wyrównany (adres #radio/…/fl302, stara pamięć przeglądarki)
    assert js["range"] == [{"min": 95, "max": 330, "step": 5}, {"min": 95, "max": 330, "step": 5},
                           {"min": 95, "max": 95, "step": 5}]
    assert js["cutAt"] == [300, 300, 305, 95, 330, 95, 95]
    assert js["sliceAt"] == [{"lo": 100, "hi": 200}]  # dolna granica włącznie, górna nie


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
    # kolumny siatki: okienka, przyciski i nazwy FIR-ów stałej szerokości (zmiana danych nie przesuwa strony), podglądy
    # dzielą resztę; nieznany rodzaj = podgląd
    assert js["tracks"] == ["var(--rb-bw) var(--rb-hw) var(--rb-nw) minmax(0, 1fr) minmax(0, 1fr)", ""]
    assert js["areas"] == ["7 / 3 / span 2 / span 1", "16 / 8 / span 6 / span 1", "1 / 1 / span 1 / span 1",
                           "1 / 4 / span 1 / span 1"]
    # przyciski warstw: wiersze z seedu, w wierszu kolejność LAYER_IDS (LOW MID HIGH), bez wiersza i nieznane pominięte
    assert js["brows"][0] == [{"col": 8, "row": 5, "ids": ["atis"]}, {"col": 8, "row": 6, "ids": ["low", "mid", "high"]},
                              {"col": 8, "row": 8, "ids": ["app"]}, {"col": 8, "row": 10, "ids": ["twr"]},
                              {"col": 8, "row": 12, "ids": ["twra"]}, {"col": 8, "row": 14, "ids": ["fis"]}]
    assert js["brows"][1] == [{"col": 8, "row": 6, "ids": ["low"]}] and js["brows"][2] == []
    assert js["boxText"] == ["OSE2 660-365", "ACC 999-0", "L 660-95", " 0-0"]
    assert js["limTip"] == ["FL365–FL660", "GND–UNL", "GND–FL285", "FL055–FL125"]
    a, b, box = js["proj"]["a"], js["proj"]["b"], js["proj"]["box"]
    assert a == pytest.approx([box["x"], box["y"]]) and b == pytest.approx([box["x"] + box["w"], box["y"] + box["h"]])
    assert 10 <= box["x"] and box["x"] + box["w"] <= 310 and 20 <= box["y"] and box["y"] + box["h"] <= 320
    assert js["bottom"]["y"] + js["bottom"]["h"] == pytest.approx(400)  # MID przy dolnej krawędzi
    assert js["path"] == "M0.0,0.0L10.0,0.0L10.0,10.0Z"
    assert js["bbox"] == [-1, 0, 2, 5]



LAYOUT_SCRIPT = r"""
// podgląd LOW (FL300) jak na ekranie 1366×768, 1600×900 i 1920×1080: etykiety ACC, plakietki APP i TWR (tylko
// zalogowani, plates z /api/radio/board) i FIS zbudowane funkcją strony previewItems i ułożone przez placeLabels
// z labelOpts; znaczniki (linie, kropki) z marksSvg. Rozmiary odmian z tekstu (znak 0,6 em: bezszeryfowa zwykła
// mieści się w tym z zapasem), panel, wolne pole i tytuł zmierzone w przeglądarce (0.13.0, siatka wg szkicu).
// Sektory ACC (runda 12): jedna etykieta na stanowisko (accGroups, suma wycinków polygon-clipping z vendor/)
import fs from "fs";
import { createRequire } from "module";
globalThis.polygonClipping = createRequire(import.meta.url)(process.argv[6]);
const rb = await import(process.argv[2]);
const { boards, geo } = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const radio = await import(process.argv[4]);
const { posName } = await import(process.argv[5]);
console.warn = () => {};
// panel LOW: W, H, wolne pole (projekcja) i tytuł z suwakiem [x, y, w, h]; f, fa = --rb-f plakietek APP/TWR/FIS
// i sektorów ACC
const SCREENS = {
  1366: { W: 339, H: 346, free: [5, 25, 331, 318], title: [4, 3, 277, 20], f: 10, fa: 13.2 },
  1600: { W: 406, H: 407, free: [5, 25, 398, 379], title: [4, 3, 297, 20], f: 11.2, fa: 15.8 },
  1920: { W: 497, H: 492, free: [5, 25, 489, 464], title: [4, 3, 324, 20], f: 13, fa: 18 },
};
const SETS = { twr: ["low", "twr"], apptwr: ["low", "app", "twr"], all: ["low", "app", "twra", "fis"] };
const shortId = (id) => String(id).replace(/ (?:APP|DEP|TWR|FIS)$/, "");
// rozmiar odmiany v (px) jak w radio.css: ramka 1 px (APP/TWR/FIS z lewej 3 px); pełna: padding 4 px, ID nad
// linijkami; skrócona i samo ID: padding 3 px, w jednej linii z odstępem 4 px (litera ATIS w żółtym polu)
function sizeOf(lb, v, scr) {
  const f = lb.cls === "acc" ? scr.fa : scr.f, side = lb.cls === "acc" ? 2 : 4;
  const tw = (s, px, sp = 0) => [...String(s)].length * (0.6 * px + sp);
  const byF = Math.max(8, f - 3), idF = Math.max(lb.cls === "acc" ? 9 : 8, f - 3), cmpF = Math.max(9, f - 2), l0 = lb.ls[0] || {};
  if (v > 0) {
    const b0 = String(l0.by || "").replace(/^↑/, ""), by = v === 1 && b0 ? `↑${l0.fq ? shortId(b0) : b0}` : "";
    const fq = v === 1 ? l0.fq || "" : "", code = v === 1 && lb.code ? 4 + 6 + tw(lb.code, Math.max(8, f - 4)) : 0;
    return { w: Math.ceil(side + 6 + tw(l0.fq ? shortId(lb.id) : lb.id, cmpF, 0.2) + (by ? 4 + tw(by, byF) : 0) + (fq ? 4 + tw(fq, f) : 0) + code),
      h: Math.ceil(2 + (fq ? f * 1.12 : cmpF * 1.15)) };
  }
  const ls = lb.ls.filter((l) => l.fq || l.by);
  const ws = ls.map((l) => (l.by ? tw(l.by, byF) : 0) + (l.by && l.fq ? 4 : 0) + (l.fq ? tw(l.fq, f) : 0)), hs = ls.map((l) => (l.fq ? f * 1.12 : byF));
  const at = /rb-fq">([^<]*)<\/span>(?:<b class="rb-code">([^<]*)<\/b>)?/.exec(lb.extra || "");
  if (at) { ws.push(tw("ATIS", byF) + 4 + tw(at[1], f) + (at[2] ? 13 + tw(at[2], Math.max(8, f - 4)) : 0)); hs.push(f * 1.12); }
  return { w: Math.ceil(side + 8 + Math.max(tw(lb.id, idF, 0.2), ...ws)), h: Math.ceil(3 + idF * 1.15 + hs.reduce((a, b) => a + b, 0) + (lb.more ? 10 : 0)) };
}
const FQ = /\d{3}\.\d{3}/;
function layout(bd, set, scr) {
  const ly = new Set(SETS[set]), twrOn = ly.has("twra") || ly.has("twr");
  const x = { freq: (cs) => bd.online?.[cs]?.frequency || bd.pos[cs]?.frequency || "", nm: posName, dn: posName,
    on: (cs) => bd.online?.[cs] || null, who: (cs) => (bd.online?.[cs] ? `${cs} online` : ""), pos: (cs) => cs, net: true };
  const groups = radio.accGroups(rb.sliceAt(geo.acc, 30000), bd.sectors, "LOW", "layout");
  const items = radio.previewItems(bd, "LOW", ly, groups, x);
  const { W, H } = scr, [fx, fy, fw, fh] = scr.free;
  const { P } = rb.projection(rb.bboxOrDefault(rb.bboxOf(geo.border)) || rb.EPWW_BBOX, { x: fx, y: fy, w: fw, h: fh }, 0.03);
  const shapes = [...(ly.has("app") ? geo.tma : []), ...(twrOn ? geo.ctr : [])], shapeKind = !shapes.length ? "" : twrOn ? "twr" : "app";
  items.forEach((it) => {
    it.prio = radio.lblPrio(it.kind, it.lb);
    it.vs = radio.lblVariants(it.lb, it.kind !== "acc");
    it.sz = it.vs.map((v) => sizeOf(it.lb, v, scr));
    [it.x, it.y] = P([it.at[1], it.at[0]]);
  });
  items.sort((a, b) => a.prio - b.prio).forEach((it) => Object.assign(it, it.sz[0], { alts: it.sz.slice(1) },
    rb.labelOpts(it.kind, { on: it.lb.state !== "off", fq: !!it.lb.ls[0]?.fq, shapes: shapeKind })));
  const cover = shapes.length ? rb.coverGrid(shapes.flatMap((s) => rb.ringsOf(s.geometry).map((r) => r.map(P))), W, H) : null;
  const [ox, oy, ow, oh] = scr.title, obstacles = [{ x0: ox - 2, y0: oy - 2, x1: ox + ow + 2, y1: oy + oh + 2 }];
  const mv = rb.placeLabels(items, { x: 2, y: 2, w: W - 4, h: H - 4 }, { obstacles, cover, near: cover ? 40 : 26 });
  const sizes = items.map((it, i) => it.sz[mv[i].v]);
  const rects = items.map((it, i) => { const s = sizes[i];
    return { x0: it.x + mv[i].dx - s.w / 2, y0: it.y + mv[i].dy - s.h / 2, x1: it.x + mv[i].dx + s.w / 2, y1: it.y + mv[i].dy + s.h / 2 }; });
  // co widać na etykiecie (odmiana z układu, bez dymku i bez linii ATIS)
  const shown = items.map((it, i) => radio.lblHtml({ ...it.lb, rt: "" }, it.vs[mv[i].v]).replace(/<span class="rb-ln rb-atl">.*(?=<\/div>$)/, ""));
  // odległość punktu plakietki od jej krawędzi (0 = punkt pod plakietką) i od środka plakietki
  const gap = (i) => Math.hypot(Math.max(0, Math.abs(mv[i].dx) - sizes[i].w / 2), Math.max(0, Math.abs(mv[i].dy) - sizes[i].h / 2));
  const plates = items.map((it, i) => ({ it, i })).filter(({ it }) => it.kind === "app" || it.kind === "twr");
  const marks = radio.marksSvg(items, mv, sizes, items.map((it) => [it.x, it.y]));
  const leadFrom = [...marks.matchAll(/class="rb-lead" d="M([\d.-]+),([\d.-]+)L/g)].map((m) => [Number(m[1]), Number(m[2])]);
  return {
    n: items.length, app: plates.filter(({ it }) => it.kind === "app").map(({ it }) => it.name).sort(),
    twr: plates.filter(({ it }) => it.kind === "twr").map(({ it }) => it.name).sort(),
    // plakietka w środku swojej przestrzeni: najwyżej lekko odsunięta; punkt części TMA albo CTR (plates.at)
    gap: Math.round(Math.max(0, ...plates.map(({ i }) => gap(i)))),
    centre: Object.fromEntries(plates.map(({ it, i }) => [it.name, Math.round(Math.hypot(mv[i].dx, mv[i].dy))])),
    at: Object.fromEntries(plates.filter(({ it }) => it.kind === "app").map(({ it }) => [it.name, it.at])),
    small: items.filter((it, i) => mv[i].v > 0).map((it) => it.name),
    overlaps: rects.flatMap((a, i) => rects.slice(i + 1).map((b, j) => (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1 ? `${items[i].name}/${items[i + 1 + j].name}` : "")))
      .filter(Boolean),
    hits: mv.filter((m) => m.hit).length,
    // plakietka i obsadzona etykieta zawsze z częstotliwością; bez nikogo (FIS) bez niej
    noFq: items.filter((it, i) => it.lb.state !== "off" && !FQ.test(shown[i])).map((it) => it.name),
    fqOff: items.filter((it, i) => it.lb.state === "off" && it.kind === "fis" && FQ.test(shown[i])).map((it) => it.name),
    // linie prowadzące i kropki tylko od etykiet ACC i FIS
    leadPlates: leadFrom.filter(([px, py]) => plates.some(({ it }) => Math.abs(it.x - px) < 0.06 && Math.abs(it.y - py) < 0.06)).length,
    dots: (marks.match(/rb-dot/g) || []).length, fis: items.filter((it) => it.kind === "fis").length,
  };
}
const res = {};
for (const [bn, bd] of Object.entries(boards)) for (const set of Object.keys(SETS)) for (const [sn, scr] of Object.entries(SCREENS)) {
  res[`${bn}-${set}-${sn}`] = layout(bd, set, scr);
}
// marksSvg: plakietka APP/TWR odsunięta daleko – bez linii i kropki; ACC – linia, FIS – kropka i linia
const far = [{ dx: 80, dy: 0 }];
res.marks = ["app", "twr", "acc", "fis"].map((kind) => radio.marksSvg([{ kind, dot: kind === "fis" ? "fis" : undefined }], far, [{ w: 40, h: 20 }], [[100, 100]]));
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


def test_js_twr_layout(client, board, tmp_path, monkeypatch):
    """0.13.0 (Marek: "jak nikt nie siedzi, nie pokazuj tysiąca plakietek APP i TWR"): na podglądzie LOW plakietki APP
    i TWR tylko dla zalogowanych – jedna na stanowisko APP w środku obsługiwanych części TMA (WA APP + WA N + WA S:
    trzy; dyrektor bez plakietki), wieża w środku CTR (TWR/A także sam ATIS), bez linii do punktu i bez kropki, najwyżej
    lekko odsunięta. Geometria z /api/radio/board, etykiety i układ funkcjami strony (previewItems, placeLabels,
    marksSvg) na 1366×768, 1600×900 i 1920×1080; bez nakładania się, obsadzona zawsze z częstotliwością."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    geo = client.get("/api/radio/board?geo=1").json()["geo"]
    boards = {"board": board}
    for name, feed in (("alt", ALT_FEED), ("split", SPLIT_FEED), ("empty", EMPTY_FEED)):
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
    marks = res.pop("marks")
    if os.environ.get("RB_DUMP"):
        open(os.environ["RB_DUMP"], "w").write(json.dumps(res))
    assert len(res) == 36
    # nikt online: ani jednej plakietki APP i TWR (także TWR/A: bez ATIS-ów)
    for key in ("empty-twr-1366", "empty-apptwr-1600", "empty-all-1920"):
        assert res[key]["app"] == [] and res[key]["twr"] == [], key
    # FEED: WA APP (przejmuje WA N, WA S, Łódź i Radom – jedna plakietka), żadnej wieży; na TWR/A sam ATIS EPWA
    assert res["board-apptwr-1366"]["app"] == ["EPWA_APP"] and res["board-apptwr-1366"]["twr"] == []
    assert res["board-all-1366"]["twr"] == ["EPWA"]
    # ALT: WA S APP i GD APP (informacja WA I APP bez plakietki), wieże WA i SY
    assert res["alt-apptwr-1600"]["app"] == ["EPGD_APP", "EPWA_S_APP"] and res["alt-twr-1600"]["twr"] == ["EPSY", "EPWA"]
    # APP podzielone: trzy plakietki WA i dwie KK, dyrektorzy (WA F, KK KK) bez plakietki; każda w punkcie swojej części
    sp = res["split-apptwr-1366"]
    assert sp["app"] == ["EPKK_APP", "EPKK_E_APP", "EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"] and sp["twr"] == ["EPKK", "EPWA"]
    parts = {g["nominal"]: g["at"] for g in boards["split"]["tma"] if g["tma"] in ("TMA Warszawa", "TMA Kraków")}
    assert all(sp["at"][cs] == parts[cs] for cs in sp["app"]), (sp["at"], parts)
    for key, out in res.items():
        # plakietka w środku: punkt pod nią albo najwyżej lekko obok (PLATE_MAX × 1,5 w tłoku), bez linii do punktu
        assert out["gap"] <= 30 and out["leadPlates"] == 0, (key, out["gap"], out["centre"])
        assert out["noFq"] == [] and out["fqOff"] == [], (key, out["noFq"], out["fqOff"])
        assert out["dots"] <= out["fis"], key  # kropki tylko FIS
        if key.endswith("-all-1366") and key.startswith("split"):
            continue  # pięć APP, dwie wieże z ATIS i dziesięć FIS na 339 px: tylko zasady wyżej
        assert out["overlaps"] == [] and out["hits"] == 0, (key, out["overlaps"])
    # APP podzielone: plakietka WA, WA N, WA S, KK i KK E najwyżej 40 px od punktu swojej części (w tłoku wokół
    # Warszawy plakietki odsuwają się od siebie i od wieży WA)
    for key in ("split-apptwr-1366", "split-apptwr-1600", "split-apptwr-1920", "split-all-1600"):
        assert max(v for k, v in res[key]["centre"].items() if k in res[key]["app"]) <= 40, (key, res[key]["centre"])
    assert marks[0] == "" and marks[1] == "" and "rb-lead" in marks[2] and "rb-dot fis" in marks[3] and "rb-lead" in marks[3]


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
for (const [layer, ft] of [["LOW", 30000], ["MID", 35000], ["HIGH", 40000]]) out[layer] = sum(radio.accGroups(rb.sliceAt(geo.acc, ft), board.sectors, layer, "t"));
out.letters = [...new Set(rb.sliceAt(geo.acc, 30000).map((s) => s.letter))].sort();
// każdy sektor obsadzony przez własne stanowisko; nikt online; bez biblioteki (same wycinki, etykieta w największym)
out.all = sum(radio.accGroups(rb.sliceAt(geo.acc, 30000), board.sectors.map((s) => ({ ...s, owner: s.nominal })), "LOW", "t"));
out.none = radio.accGroups(rb.sliceAt(geo.acc, 30000), board.sectors.map((s) => ({ ...s, owner: null })), "LOW", "t").length;
const lib = globalThis.polygonClipping;
globalThis.polygonClipping = undefined;
out.nolib = sum(radio.accGroups(rb.sliceAt(geo.acc, 30000), board.sectors, "LOW", "nolib"));
globalThis.polygonClipping = lib;
out.path = rb.pathAll({ type: "Polygon", coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]] }, (c) => c);
console.log(JSON.stringify(out));
"""


def test_js_acc_groups(client, board, tmp_path):
    """Runda 12 (Marek): na podglądach LOW/MID/HIGH sektory ACC jednego stanowiska to jeden obszar z jedną etykietą
    (accGroups), sektorów bez nikogo nie rysujemy; po błędzie sumy same wycinki."""
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
    # ścieżka SVG z dziurą (wypełnienie evenodd w radio.css)
    assert out["path"].count("M") == 2 and out["path"].endswith("ZM2.0,2.0L4.0,2.0L4.0,4.0L2.0,4.0L2.0,2.0Z")


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
const FQ = { EYVL_CTR: "133.305", EYVL_U_CTR: "132.280", EDUU_O22_CTR: "135.255", UMMV_W_CTR: "135.700" };
const x = { who: (cs) => `${cs} ${FQ[cs]} – Jonas`, pos: (cs) => `${cs} ${FQ[cs] || ""}`.trim(), freq: (cs) => FQ[cs] || "",
  sel: "EYVL", net: true };
const box = (id, upper, lower, col, row, cs, owner = null, o = {}) => ({ id, label: id, col, row, cols: 1, rows: 1, upper, lower,
  callsign: cs, chain: [cs], owner, staffed: !!owner, frequency: owner ? FQ[owner] : null,
  members: [{ id, upper, lower, callsign: cs }], merged: false, ...o });
const eyvl = (boxes, o = {}) => ({ fir: "EYVL", title: "VILNIUS", name: { col: 13, row: 3, cols: 1, rows: 1 }, merge: true,
  staffed: boxes.some((b) => b.owner), advisory: !boxes.some((b) => b.owner), online: [], boxes, ...o });
const U = box("U", 660, 365, 12, 3, "EYVL_U_CTR"), M = box("M", 365, 335, 12, 4, "EYVL_M_CTR");
const L = box("L", 335, 225, 12, 5, "EYVL_CTR"), E = box("E", 225, 95, 12, 6, "EYVL_E_CTR");
const merged = { id: "U+M+L+E", label: "L", col: 12, row: 3, cols: 1, rows: 4, upper: 660, lower: 95, callsign: "EYVL_CTR",
  chain: ["EYVL_CTR"], owner: "EYVL_CTR", staffed: true, frequency: "133.305", merged: true,
  members: [U, M, L, E].map((b) => b.members[0]) };
const on = [{ callsign: "EYVL_CTR", position: "EYVL_CTR", frequency: "133.305", name: "Jonas" }];
const eduu = { fir: "EDUU", title: "RHEIN", name: { col: 3, row: 6, cols: 1, rows: 1 }, merge: true, staffed: true,
  advisory: false, online: [{ callsign: "EDUU_O22_CTR", position: "EDUU_O22_CTR", frequency: "135.255", name: "Max" }],
  boxes: [box("OSE2", 660, 365, 3, 7, "EDUU_O22_CTR", "EDUU_O22_CTR"), box("OSE1", 365, 285, 3, 8, "EDUU_O12_CTR")] };
const ummv = { fir: "UMMV", title: "MINSK", name: { col: 13, row: 9, cols: 1, rows: 1 }, merge: false, staffed: true,
  advisory: false, online: [{ callsign: "UMBB_TWR", position: "UMBB_TWR", frequency: "118.500", name: "Ivan" },
    { callsign: "UMMV_W_CTR", position: "UMMV_W_CTR", frequency: "135.700", name: "Olga" }],
  boxes: [box("ACC", 660, 75, 12, 9, "UMMV_CTR", "UMMV_W_CTR", { label: "ACC" })] };
const ind = { id: "APP WA", tip: "Warszawa APP online: H = radar positions, L = director", col: 3, row: 1, value: "2H+L",
  positions: [{ callsign: "EPWA_APP", position: "EPWA_APP", frequency: "128.805", name: "Ala" }] };
const ber = { col: 1, row: 6, box: { col: 1, row: 7, cols: 2 }, config: "EAST", preferred: false, tip: "ATIS EDDB: RWY 06L/06R" };
const evil = { fir: "<b>", title: "<i>t</i>", name: { col: 1, row: 1 }, advisory: false, online: [{ callsign: "<u>", frequency: "1", name: "<s>x</s>" }],
  boxes: [box("<img src=x>", 660, 0, 1, 2, "A_CTR", "A_CTR", { frequency: "<s>1</s>" })] };
console.log(JSON.stringify({
  off: radio.firHtml(eyvl([U, M, L, E]), x),
  part: radio.firHtml(eyvl([U, M, L, E].map((b) => (b === U ? { ...U, owner: "EYVL_U_CTR", staffed: true, frequency: "132.280" } : b)),
    { online: [{ callsign: "EYVL_U_CTR", position: "EYVL_U_CTR", frequency: "132.280", name: "Ona" }] }), { ...x, sel: null }),
  merged: radio.firHtml(eyvl([merged], { online: on }), x),
  eduu: radio.firHtml(eduu, { ...x, sel: null }),
  ummv: radio.firHtml(ummv, { ...x, sel: null }),
  nonet: radio.firHtml(eyvl([U, M, L, E], { advisory: false }), { ...x, net: false }),
  side: [eyvl([U]), eduu, ummv, { name: { col: 5, row: 4, cols: 2 }, boxes: [box("6", 660, 365, 6, 5, "X")] }, {}].map(radio.nameSide),
  ind: radio.indicatorHtml(ind, x), indNone: radio.indicatorHtml({ ...ind, value: "0", positions: [] }, x),
  indNet: radio.indicatorHtml({ ...ind, value: "0", positions: [] }, { ...x, net: false }),
  ber: radio.berlinHtml(ber), berPref: radio.berlinHtml({ ...ber, config: "WEST", preferred: true, tip: "" }),
  berNone: radio.berlinHtml({ col: 1, row: 6 }),
  berNet: radio.berlinHtml({ ...ber, config: "EAST", preferred: true, tip: "" }, { ...x, net: false }),
  berUnknown: radio.berlinHtml({ ...ber, config: null, source: "UNKNOWN", preferred: false, tip: "ATIS unknown: no network data" }),
  evil: radio.firHtml(evil, { ...x, sel: null }) + radio.indicatorHtml({ id: "<b>", tip: "<i>", col: 1, row: 1, value: "<s>",
    positions: [] }, x) + radio.berlinHtml({ col: 1, row: 6, config: "<b>", tip: "<i>" }),
}));
"""


def test_js_neighbour_boxes(tmp_path):
    """Okienka sąsiadów, wskaźniki i BERLIN w RADIO (tabs/radio.js firHtml, indicatorHtml, berlinHtml): napis okienka
    jak na szkicu ("OSE2 660-365"), częstotliwość tylko w obsadzonym; połączone okienko na swoich komórkach z nazwą
    połączonego; cały FIR bez nikogo → ADVISORY 122.800 pod nazwą FIR-u; błąd sieci → bez ADVISORY i bez zer; dane
    przez esc()."""
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
    off = out["off"]
    # nikt z EYVL online: ADVISORY raz pod nazwą, żadnej innej częstotliwości, okienka z ID i granicami
    assert shown["off"].count("ADVISORY 122.800") == 1 and '<span class="rb-unfq">ADVISORY 122.800</span>' in off
    assert freqs.findall(shown["off"]) == ["122.800"]
    assert off.count('class="rb-box off"') == 4 and 'class="rb-fq"' not in off
    assert '<span class="rb-bt"><span class="rb-id">U</span> <span class="rb-lim">660-365</span></span>' in off
    assert re.findall(r'class="rb-lim">([^<]+)<', off) == ["660-365", "365-335", "335-225", "225-95"]
    # nazwa FIR-u: żółta, obok okienek (side), zaznaczona przy otwartym LOA, klawiatura i data-fir do panelu LOA
    assert 'class="rb-fir side sel" role="button" tabindex="0" data-fir="EYVL" data-title="VILNIUS"' in off
    assert 'style="grid-area: 3 / 13 / span 1 / span 1"' in off and 'data-box="E" style="grid-area: 6 / 12 / span 1 / span 1"' in off
    assert "Nobody online – ADVISORY 122.800" in off and "Click: LOA EPWW – EYVL" in off
    assert off.count("Now: unstaffed – ADVISORY 122.800") == 4
    assert "EYVL U · FL365–FL660\nPosition: EYVL_U_CTR 132.280\nNow: unstaffed – ADVISORY 122.800" in off
    # część obsadzona: częstotliwość tylko w tym okienku, bez ADVISORY, w pozostałych samo "Now: unstaffed"
    part = out["part"]
    assert "ADVISORY" not in part and part.count('class="rb-box on"') == 1 and part.count('class="rb-fq"') == 1
    assert '<span class="rb-fq">132.280</span>' in part and part.count("Now: unstaffed") == 3
    assert "Online: EYVL_U_CTR 132.280 – Ona" in part and 'class="rb-fir side"' in part
    # połączone: jedno okienko na czterech komórkach, nazwa połączonego (L) i suma granic, w dymku okienka w środku
    mg = out["merged"]
    assert mg.count('class="rb-box') == 1 and 'class="rb-box on mrg"' in mg and 'data-box="U+M+L+E"' in mg
    assert 'style="grid-area: 3 / 12 / span 4 / span 1"' in mg
    assert re.search(r'<span class="rb-id">L</span> <span class="rb-lim">660-95</span>', mg)
    assert '<span class="rb-fq">133.305</span>' in mg and "Now: EYVL_CTR 133.305 – Jonas" in mg
    assert "Merged: U 660-365, M 365-335, L 335-225, E 225-95" in mg and "Position:" not in mg
    assert "EYVL L · FL095–FL660" in mg
    # EDUU: nazwa nad okienkami; OSE2 obsadzone, OSE1 nie (bez ADVISORY: ktoś z FIR-u jest)
    ed = out["eduu"]
    assert 'class="rb-fir" role="button"' in ed and "<span>OSE2</span>" not in ed
    assert re.search(r'<span class="rb-id">OSE2</span> <span class="rb-lim">660-365</span></span><span class="rb-fq">135.255</span>', ed)
    assert "OSE1" in ed and ed.count('class="rb-fq"') == 1 and "ADVISORY" not in ed
    assert "Also online" not in ed  # tylko okienko na cały FIR wymienia pozostałych zalogowanych
    # UMMV: jedno okienko na FIR – w dymku także wieża (UMBB TWR), która go nie obsługuje
    um = out["ummv"]
    assert '<span class="rb-fq">135.700</span>' in um and "Also online: UMBB_TWR 118.500 – Ivan" in um
    assert "Also online: UMMV_W_CTR" not in um and "Online: UMBB_TWR 118.500 – Ivan" in um
    # błąd sieci: nie wiadomo, czy ktoś jest online – bez ADVISORY, bez częstotliwości
    nn = out["nonet"]
    assert "ADVISORY" not in nn and 'class="rb-fq"' not in nn and nn.count("Now: no data") == 4 and "Online: no data" in nn
    assert out["side"] == [True, False, True, False, True]
    # wskaźnik: żółta nazwa w swojej komórce, szare pole z wartością pod nią; w dymku znaczenie i zalogowani
    ind = out["ind"]
    assert '<div class="rb-ind" style="grid-area: 1 / 3 / span 1 / span 1"' in ind and ">APP WA</div>" in ind
    # wartość w rb-indt: za długa (ACC GAT) od początku z wielokropkiem na końcu, nie ucięta z obu stron
    assert '<div class="rb-indv" style="grid-area: 2 / 3 / span 1 / span 1"' in ind and '<span class="rb-indt">2H+L</span></div>' in ind
    assert "APP WA: Warszawa APP online: H = radar positions, L = director\nEPWA_APP 128.805 – Ala" in ind
    assert ">0</span></div>" in out["indNone"] and "Nobody online" in out["indNone"]
    assert ">–</span></div>" in out["indNet"] and ">0</span></div>" not in out["indNet"] and "Now: no data" in out["indNet"]
    # BERLIN: szare pole z konfiguracją; czerwony napis (pref), gdy z ATIS nie wiadomo, który pas
    ber, pref = out["ber"], out["berPref"]
    assert '<div class="rb-blbl" style="grid-area: 6 / 1 / span 1 / span 1"' in ber and ">BERLIN</div>" in ber
    assert '<div class="rb-bln" style="grid-area: 7 / 1 / span 1 / span 2"' in ber and ">EAST</div>" in ber
    assert "ATIS EDDB: RWY 06L/06R" in ber and "Red text" not in ber
    assert 'class="rb-bln pref"' in pref and ">WEST</div>" in pref and "Red text: preferred configuration" in pref
    assert 'class="rb-bln" style="grid-area: 7 / 1 / span 1 / span 2"' in out["berNone"] and ">–</div>" in out["berNone"]
    # bez danych o zalogowanych: kreska jak we wskaźnikach, nie czerwona konfiguracja z wiatru
    for k in ("berNet", "berUnknown"):
        assert 'class="rb-bln" style=' in out[k] and ">–</div>" in out[k] and "Red text" not in out[k], k
        assert "ATIS unknown: no network data" in out[k], k
    # dymki mówią, co to jest, nie skąd są dane
    for key, h in out.items():
        assert not re.search(r"Coverage order|coverage order|VACS|VATSIM|VATSpy|\.ese|›", str(h)), key
    ev = out["evil"]
    assert "<img" not in ev and "<i>" not in ev and "<s>" not in ev and "<u>" not in ev and "<b>" not in ev
    assert "&lt;img src=x&gt;" in ev and "&lt;b&gt;" in ev


LBL_SCRIPT = r"""
const radio = await import(process.argv[2]);
const lb = (o) => ({ cls: "twr", state: "off", id: "SY TWR", ls: [], rt: "SY TWR · EPSY", k: "EPSY", icao: "EPSY", ...o });
const html = (x, small = true) => ({ v: radio.lblVariants(x, small), prio: radio.lblPrio(x.cls, x),
  html: radio.lblVariants(x, small).map((v) => radio.lblHtml(x, v)) });
// linijki i plakietki z tablicy: częstotliwość online albo z tablicy, nazwa stanowiska, kontroler online, kto, opis
const FQ = { EPWA_APP: "128.805", EPWA_S_APP: "135.930", EPWA_N_APP: "125.055", EPWA_TWR: "118.305", EPWA_ATIS: "120.455" };
const ctx = (online) => ({ freq: (cs) => online[cs]?.frequency || FQ[cs] || "", nm: (cs) => cs.replace(/^EP/, "").replace(/_/g, " "),
  on: (cs) => online[cs] || null, who: (cs) => (online[cs] ? `${cs} ${online[cs].frequency} – Jan` : ""),
  pos: (cs, fq = "") => `${cs} · pos${fq ? ` ${fq}` : ""}`, net: true });
const ON = (...cs) => Object.fromEntries(cs.map((c) => [c, { callsign: c, frequency: FQ[c], atis_code: /_ATIS$/.test(c) ? "K" : null }]));
const TMA = [["TMA Warszawa · EPWA_APP", "EPWA_APP", 0, 9500], ["TMA Warszawa · EPWA_N_APP", "EPWA_N_APP", 2500, 9500],
  ["TMA Warszawa · EPWA_S_APP", "EPWA_S_APP", 2500, 9500], ["TMA Radom", "EPWA_S_APP", 3500, 9500]]
  .map(([id, nominal, lo, hi]) => ({ id, nominal, lo, hi, tma: id.split(" · ")[0], icao: "EPWA", owners: [] }));
const flow = { tma: { "TMA Warszawa": [{ tip: ["Flow restriction: max occupancy 20 until 18:00"] }], "TMA Radom": [{ tip: ["Occupancy 9 of 10"] }] } };
const plate = (owner, covers, at = [52.1, 21.0]) => ({ owner, tma: "TMA Warszawa", icao: "EPWA", at, frequency: FQ[owner], covers,
  parts: covers.filter((c) => c.startsWith("TMA Warszawa")).map((c) => c.split(" · ")[1]) });
const ctr = { id: "CTR Warszawa", nominal: "EPWA_TWR", atis: "EPWA_ATIS", owners: [] };
const twrP = (twr, atis) => ({ id: "CTR Warszawa", icao: "EPWA", at: [52.17, 20.92], twr, atis, frequency: twr.length ? FQ[twr[0]] : null });
const out = [];
out.push(JSON.stringify({
  off: html(lb({})),
  accOn: html({ ...radio.accLabel({ owner: "EPWW_N_CTR" }, "EPWW N", ctx({ EPWW_N_CTR: { callsign: "EPWW_N_CTR", frequency: "130.675" } })),
    rt: "EPWW N" }, false),
  on: html(lb({ state: "on", id: "WA TWR", ls: [{ fq: "118.305", by: "" }] })),
  fis: [html({ cls: "fis", state: "on", id: "WA E FIS", ls: [{ fq: "123.975", by: "WA C FIS" }], rt: "" }), html({ cls: "fis", state: "off", id: "GD FIS", ls: [], rt: "" })],
  evil: html(lb({ id: "<img src=x>", rt: '"><b>x</b>' })),
  lines: [radio.lblLines("EPWA_APP", [], ctx({})), radio.lblLines("EPWA_APP", ["EPWA_APP"], ctx(ON("EPWA_APP"))),
    radio.lblLines("EPWA_S_APP", ["EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"], ctx(ON("EPWA_APP", "EPWA_N_APP", "EPWA_S_APP")))],
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
}));
const o = JSON.parse(out.pop());
o.atisV = radio.lblVariants(o.atisOnly.lb);
o.twrCmp = radio.lblHtml({ ...o.twrOn[1].lb, rt: "" }, 1);
console.log(JSON.stringify(o));
"""


def test_js_label_variants(tmp_path):
    """Etykiety i plakietki podglądów (tabs/radio.js): bez nikogo (FIS) jedna odmiana – samo ID, bez częstotliwości;
    obsadzona zawsze z częstotliwością, nigdy samo ID. 0.13.0: plakietka APP na zalogowane stanowisko APP (appPlate:
    ID stanowiska i jego częstotliwość, w dymku TMA, części, inne obsługiwane TMA i alarmy przepływu), plakietka TWR
    (twrPlate: wieża online, na TWR/A z linią ATIS; sam ATIS – tylko pełna odmiana, żeby nie zgubić ATIS-u);
    plakietki układane przed sektorami ACC (lblPrio)."""
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
    freqs = re.compile(r"\d{3}\.\d{3}")

    def shown(h):  # bez dymku: to, co widać na etykiecie
        return re.sub(r'data-rt="[^"]*"', "", h)
    # bez nikogo: samo pełne ID, bez częstotliwości i bez "—"
    for key, x in (("off", out["off"]), ("fisOff", out["fis"][1])):
        assert x["v"] == [2], key
        (h,) = x["html"]
        assert not freqs.search(shown(h)) and "rb-fq" not in h and "—" not in h, key
    assert out["off"]["html"][0].endswith('<b class="rb-id">SY TWR</b></div>') and 'class="rb-lbl twr off cmp"' in out["off"]["html"][0]
    # obsadzone: częstotliwość w pełnej i skróconej; sektory ACC stanowiska (runda 12): nazwa stanowiska
    # i częstotliwość, tylko pełna, data-k = znak (podświetlenie obszaru stanowiska)
    acc = out["accOn"]["html"][0]
    assert out["accOn"]["v"] == [0] and '<b class="rb-id">EPWW N</b>' in acc and '<span class="rb-fq">130.675</span>' in acc
    assert 'data-k="EPWW_N_CTR"' in acc and 'class="rb-lbl acc on"' in acc
    v, h = out["on"]["v"], out["on"]["html"]
    assert v == [0, 1] and all('<span class="rb-fq">118.305</span>' in x for x in h) and '<b class="rb-id">WA</b>' in h[1]
    assert out["fis"][0]["v"] == [0, 1] and all("123.975" in x for x in out["fis"][0]["html"])
    # kolejność układania: plakietki (APP, TWR) przed sektorami ACC, potem FIS, na końcu samo ID
    assert out["on"]["prio"] < out["accOn"]["prio"] < out["fis"][0]["prio"] < min(out["off"]["prio"], out["fis"][1]["prio"])
    ev = out["evil"]["html"][0]
    assert "<img" not in ev and "<b>x" not in ev and "&lt;img src=x&gt;" in ev
    # linijki: nikt → żadnej; własne stanowisko bez skrótu; najwyżej dwaj właściciele, cudzy ze swoją nazwą
    ln = out["lines"]
    assert ln[0] == [] and ln[1] == [{"fq": "128.805", "by": ""}]
    assert ln[2] == [{"fq": "128.805", "by": "WA APP"}, {"fq": "125.055", "by": "WA N APP"}]
    # plakietka APP: ID i częstotliwość stanowiska, w punkcie z tablicy; dymek bez kolejności przejmowania
    a = out["appAll"]
    assert (a["kind"], a["name"], a["at"]) == ("app", "EPWA_APP", [52.1, 21.0])
    assert a["lb"]["id"] == "WA APP" and a["lb"]["ls"] == [{"fq": "128.805", "by": ""}] and a["lb"]["state"] == "on"
    assert a["lb"]["rt"].split("\n") == ["TMA Warszawa – all parts (GND–FL095)", "Position: EPWA_APP · pos",
                                         "Now: EPWA_APP 128.805 – Jan", "Also covers: TMA Radom",
                                         "Flow restriction: max occupancy 20 until 18:00", "TMA Radom: Occupancy 9 of 10"]
    assert out["appS"]["lb"]["rt"].split("\n")[0] == "TMA Warszawa – part WA S APP (FL025–FL095)"
    # plakietka TWR: wieża online; linia ATIS z literą tylko na TWR/A (skrócona: litera za częstotliwością wieży)
    t0, t1 = out["twrOn"]
    assert t0["lb"]["state"] == "on" and t0["lb"]["ls"] == [{"fq": "118.305", "by": ""}] and t0["lb"]["extra"] == ""
    assert '<span class="rb-fq">120.455</span><b class="rb-code">K</b>' in t1["lb"]["extra"] and t1["lb"]["code"] == "K"
    assert t1["lb"]["icao"] == "EPWA" and t1["lb"]["rt"].split("\n")[-1] == "Click: AERODROME"
    assert "ATIS: EPWA_ATIS · pos 120.455 – online, information K" in t1["lb"]["rt"]
    af = out["atisFq"]["lb"]
    assert '<span class="rb-fq">121.080</span>' in af["extra"] and "ATIS: EPWA_ATIS · pos 121.080 – online, information K" in af["rt"]
    assert "ATIS: EPWA_ATIS · pos – offline" in out["atisOff"]["lb"]["rt"]  # offline: opis z listy stanowisk
    # sam ATIS (wieża offline, TWR/A): ID wieży i linia ATIS, tylko pełna odmiana; w dymku, kto przejmuje wieżę
    ao = out["atisOnly"]["lb"]
    assert ao["state"] == "off" and ao["ls"] == [] and "120.455" in ao["extra"]
    assert "Tower offline – covered by EPWA_APP 128.805 – Jan" in ao["rt"] and out["atisV"] == [0]
    assert '<span class="rb-fq">118.305</span><b class="rb-code">K</b></div>' in out["twrCmp"]


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
    tma: { "TMA Warszawa": [{ tip: ["Flow restriction: max occupancy 20 until 18:00"] }], "TMA Nowhere": [{ tip: ["x"] }] } },
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
    assert lib["HIGH"]["areas"][0]["rt"].split("\n") == ["Sector HB · HIGH", "Now: unstaffed", "Occupancy 12 of 14"]
    assert lib["LOW"]["areas"][0]["rt"].split("\n") == ["TMA Warszawa", "Now: EPWA_APP online",
                                                          "Flow restriction: max occupancy 20 until 18:00"]
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
    """Runda 14 (przegląd): "TWR/ATIS" w jednej trzeciej rzędu LOW MID HIGH był ucięty przy 1280–1600 px. 0.13.0: każdy
    rząd środkowej kolumny (ATIS / LOW MID HIGH / APP / TWR / TWR/A / FIS) w swojej komórce siatki; przycisk szeroki na
    jedną trzecią kolumny, ale nie mniej niż napis z odstępem po bokach (sprawdzone w przeglądarce: scrollWidth ≤
    clientWidth przy 1366×768, 1600×900, 1920×1080 i 1366×600). Włączona warstwa – kolorem, bez pogrubienia."""
    css = (FRONTEND / "css" / "radio.css").read_text("utf-8")
    body = re.search(r"\.rb-brow button \{([^}]*)\}", css).group(1)
    assert "flex: 0 0 calc((100% - 8px) / 3)" in body and "min-width: max-content" in body
    assert re.search(r"padding: \d+px [1-9]\d*px", body)  # odstęp po bokach napisu
    assert "border-radius: 0" in body and "font: 400 " in body
    on = re.search(r"\.rb-brow button\.on \{([^}]*)\}", css).group(1)
    assert "background:" in on and "color:" in on and "font-weight" not in on
    # cała strona RADIO zwykłą grubością, czcionką bezszeryfową (układ nie zależy od czcionki o stałej szerokości)
    assert not re.search(r"font-weight:\s*(?:bold|[5-9]00)|font:\s*(?:bold|[5-9]00)\b|var\(--mono\)", css)
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    assert "font-weight" not in radio and re.search(r"\.rb b, \.rb strong[^{]*\{ font-weight: 400; \}", css)  # <b> też zwykłą
    # ATIS: pasek stałej wysokości, wyłączony chowa tylko treść (podglądy nie zmieniają rozmiaru)
    assert re.search(r"\.rb-atis \{[^}]*height: calc\(", css) and ".rb-atis.off .rb-atis-in { visibility: hidden; }" in css
    assert "noatis" not in css and "noatis" not in radio
