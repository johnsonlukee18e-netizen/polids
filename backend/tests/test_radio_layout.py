"""RADIO 0.13.0 (issue #23, szkic Marka): okienka FIR-ów sąsiednich w siatce (data/seed/radio_layout.json), łączenie
okienek jednego stanowiska, wskaźniki u góry, BERLIN WEST/EAST, czerwone tło przy ograniczeniach przepływu i plakietki
APP/TWR tylko dla zalogowanych (GET /api/radio/board i czyste funkcje radioboard.py)."""
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

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
from backend.app.services.viff import restriction_active  # noqa: E402

SEED = ROOT_DIR / "data" / "seed" / "radio_layout.json"
EMPTY = {"general": {"update_timestamp": "2026-10-28T12:00:00Z"}, "pilots": [], "controllers": [], "atis": []}
SIDE = {"feed": EMPTY, "metar": {}, "tvs": [], "metar_calls": 0}


def ctl(cs, fq, name=None):
    return {"callsign": cs, "frequency": fq, "name": name or cs.split("_")[0].title(), "cid": abs(hash(cs)) % 10 ** 7}


def atis(cs, letter, lines, fq="123.180"):
    return {"callsign": cs, "frequency": fq, "name": "Atis", "cid": 99, "atis_code": letter, "text_atis": lines}


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()

    async def feed():
        if isinstance(SIDE["feed"], Exception):
            raise SIDE["feed"]
        return SIDE["feed"]

    async def metars(icaos):
        SIDE["metar_calls"] += 1
        if isinstance(SIDE["metar"], Exception):
            raise SIDE["metar"]
        return SIDE["metar"]

    async def tvs(prefix=None, now=None):
        if isinstance(SIDE["tvs"], Exception):
            raise SIDE["tvs"]
        return {"prefix": prefix, "sectors": SIDE["tvs"], "scenarios": []}

    mp.setattr(vatsim_api, "get_feed", feed)
    mp.setattr(radio_router, "get_metars", metars)
    mp.setattr(radio_router, "viff_sectors", tvs)
    with TestClient(main.app) as c:
        yield c
    mp.undo()


@pytest.fixture(autouse=True)
def fresh_side():
    """Każdy test: pusty feed, bez METAR i vIFF, bez pamięci błędów dodatków."""
    SIDE.update(feed=EMPTY, metar={}, tvs=[], metar_calls=0)
    radio_router._SIDE_FAILED.clear()
    yield
    radio_router._SIDE_FAILED.clear()


def get(client, controllers=(), atis_=(), metar=None, tvs=None):
    SIDE["feed"] = {**EMPTY, "controllers": list(controllers), "atis": list(atis_)}
    SIDE["metar"] = {} if metar is None else metar
    SIDE["tvs"] = [] if tvs is None else tvs
    r = client.get("/api/radio/board")
    assert r.status_code == 200
    return r.json()


def boxes(d, fir):
    return next(f for f in d["firs"] if f["fir"] == fir)["boxes"]


def short(b):
    return (b["label"], b["upper"], b["lower"], b["col"], b["row"], b["cols"], b["rows"], b["owner"])


# --- seed układu
def test_layout_seed_matches_sketch():
    """Okienka, nazwy i granice jak na szkicu Marka (ESSA = ESAA), w kolumnach A..M (1..13)."""
    lay = json.loads(SEED.read_text("utf-8"))
    got = {f["fir"]: [(b["id"], b["upper"], b["lower"], b["col"], b["row"]) for b in f["boxes"]] for f in lay["firs"]}
    assert got == {
        "EDWW": [("MRZ", 285, 0, 2, 5), ("MAR", 285, 0, 2, 9), ("FLG", 285, 0, 2, 11)],
        "EDUU": [("OSE2", 660, 365, 3, 7), ("OSE1", 365, 285, 3, 8), ("HVL2", 660, 365, 3, 11), ("HVL1", 365, 285, 3, 12),
                 ("SPE1", 660, 315, 3, 15)],
        "EDMM": [("MEI", 315, 165, 2, 15), ("SAS", 165, 0, 2, 16)],
        "ESAA": [("9", 660, 365, 5, 5), ("6", 660, 365, 6, 5), ("8", 365, 195, 5, 6), ("7", 365, 0, 6, 6), ("L", 195, 0, 5, 7)],
        "LKAA": [("NU", 660, 305, 5, 19), ("SU", 660, 305, 6, 19), ("NL", 305, 125, 5, 20), ("SL", 305, 125, 6, 20),
                 ("MT", 125, 0, 6, 21)],
        "UMKK": [("ACC", 999, 0, 10, 5)], "LZBB": [("U", 660, 305, 10, 19), ("BB", 305, 80, 10, 20)],
        "EYVL": [("U", 660, 365, 12, 3), ("M", 365, 335, 12, 4), ("L", 335, 225, 12, 5), ("E", 225, 95, 12, 6)],
        "UMMV": [("ACC", 660, 75, 12, 9)], "UKLV": [("RLV", 660, 55, 12, 15)]}
    # łączenie tylko EDUU, EDMM, ESAA, EYVL, LZBB, LKAA; nigdy EDWW
    assert {f["fir"] for f in lay["firs"] if f["merge"]} == rb.MERGE_FIRS == {"EDUU", "EDMM", "ESAA", "EYVL", "LZBB", "LKAA"}
    assert [(i["id"], i["col"], i["row"]) for i in lay["indicators"]] == [
        ("ACC GAT", 1, 1), ("APP GD", 2, 1), ("APP WA", 3, 1), ("APP KK", 4, 1), ("APP PO", 5, 1)]
    assert (lay["berlin"]["col"], lay["berlin"]["row"], lay["berlin"]["box"]) == (1, 6, {"col": 1, "row": 7, "cols": 2})
    for f in lay["firs"]:
        for b in f["boxes"]:
            assert b["upper"] > b["lower"] >= 0 and 1 <= b["col"] <= 13 and 1 <= b["row"] <= 21, (f["fir"], b["id"])


def test_layout_boxes_map_to_known_callsigns(client):
    """Każde okienko ma kafelek sąsiada i kolejność ze znanych stanowisk; komórki siatki się nie nakładają."""
    d = get(client)
    vacs = json.loads((ROOT_DIR / "data" / "seed" / "vacs_epww.json").read_text("utf-8"))["neighbours"]
    labels = {n["label"] for n in vacs if not n.get("fmp")}
    lay = json.loads(SEED.read_text("utf-8"))
    for f in lay["firs"]:
        assert set(sum((b["tiles"] for b in f["boxes"]), [])) <= labels, f["fir"]
    cells: dict[tuple[int, int], str] = {}

    def take(tag, col, row, cols=1, rows=1):
        for x in range(col, col + cols):
            for y in range(row, row + rows):
                assert (x, y) not in cells, (tag, cells.get((x, y)))
                cells[(x, y)] = tag

    for f in d["firs"]:
        take(f"name {f['fir']}", **f["name"])
        assert len(f["boxes"]) == len(next(x for x in lay["firs"] if x["fir"] == f["fir"])["boxes"])
        for b in f["boxes"]:
            take(f"{f['fir']} {b['id']}", b["col"], b["row"], b["cols"], b["rows"])
            assert b["chain"] and b["callsign"] in b["chain"], (f["fir"], b["id"])
            assert b["callsign"] in d["pos"] and all(cs in d["pos"] for cs in b["chain"]), (f["fir"], b["id"])
            assert set(b) == {"id", "label", "col", "row", "cols", "rows", "upper", "lower", "callsign", "chain", "owner",
                              "staffed", "frequency", "members", "merged"}
    for i in d["indicators"]:
        take(i["id"], i["col"], i["row"], rows=2)  # nazwa i wartość pod nią
    take("berlin", d["berlin"]["col"], d["berlin"]["row"])
    take("berlin box", **d["berlin"]["box"])
    for row in set(d["grid"]["buttons"]["rows"].values()):
        take("buttons", d["grid"]["buttons"]["col"], row)
    # 0.13.0 etap 2: podglądy LOW (lewo od środka), HIGH (prawo) i MID (dół środka), stan danych i legenda też mają
    # stałe miejsca w siatce, bez nakładania się na okienka, wskaźniki i przyciski
    g = d["grid"]
    assert set(g["maps"]) == {"low", "high", "mid"}
    for k, c in g["maps"].items():
        take(f"map {k}", **c)
    take("status", **g["status"])
    take("legend", **g["legend"])
    btn = g["buttons"]["col"]
    assert g["maps"]["low"]["col"] + g["maps"]["low"]["cols"] == btn == g["maps"]["mid"]["col"] < g["maps"]["high"]["col"]
    assert g["maps"]["mid"]["row"] + g["maps"]["mid"]["rows"] - 1 == g["rows"]  # MID przy dolnej krawędzi
    assert max(x for x, _ in cells) <= d["grid"]["cols"] == 13 and max(y for _, y in cells) <= d["grid"]["rows"] == 21
    # kolumny siatki wg tego, co w nich stoi (stała szerokość okienek, przycisków i nazw; podglądy dzielą resztę)
    assert g["tracks"] == ["box"] * 6 + ["map", "btn", "map", "box", "map", "box", "name"]
    assert rb.col_kinds({(1, 1): "box:X", (2, 1): "name:X", (2, 2): "ind:A", (4, 1): "map:low"}, 5, 3) == [
        "box", "box", "btn", "map", "map"]
    assert all(i["tip"] and set(i) >= {"id", "tip", "col", "row", "value", "positions"} for i in d["indicators"])
    # HVL2: w plikach sektorów nie ma osobnego stanowiska HVL2, obsługuje je OSE2 (EDUU_O22_CTR)
    eduu = {b["id"]: b for b in boxes(d, "EDUU")}
    assert eduu["HVL2"]["chain"][0] == "EDUU_O22_CTR" and eduu["HVL1"]["chain"][0] == "EDUU_H12_CTR"


def test_layout_in_board_stamp(client):
    """Zmiana radio_layout.json = nowa wersja części stałej (strona dostaje nowy układ)."""
    ver = get(client)["ver"]
    st = SEED.stat()
    try:
        os.utime(SEED, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        assert client.get("/api/radio/board").json()["ver"] != ver
    finally:
        os.utime(SEED, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert client.get("/api/radio/board").json()["ver"] == ver


# --- łączenie okienek
def test_nobody_online_no_merge_advisory(client):
    d = get(client)
    for f in d["firs"]:
        assert f["advisory"] and not f["staffed"] and f["online"] == [], f["fir"]
        assert all(not b["merged"] and b["owner"] is None and b["frequency"] is None and b["label"] == b["id"]
                   for b in f["boxes"]), f["fir"]
    assert [b["label"] for b in boxes(d, "EYVL")] == ["U", "M", "L", "E"]


def test_merge_eyvl_alone(client):
    d = get(client, [ctl("EYVL_CTR", "133.305", "Vilnius")])
    (b,) = boxes(d, "EYVL")
    assert short(b) == ("L", 660, 95, 12, 3, 1, 4, "EYVL_CTR") and b["merged"] and b["frequency"] == "133.305"
    assert [m["id"] for m in b["members"]] == ["U", "M", "L", "E"]
    f = next(f for f in d["firs"] if f["fir"] == "EYVL")
    assert f["staffed"] and not f["advisory"]
    assert f["online"] == [{"callsign": "EYVL_CTR", "position": "EYVL_CTR", "frequency": "133.305", "name": "Vilnius"}]


def test_merge_lkaa(client):
    # LKAA_U_CTR: NU i SU obok siebie (jedno stanowisko w obu) → jedno okienko U na dwie kolumny
    d = get(client, [ctl("LKAA_U_CTR", "124.775")])
    lk = boxes(d, "LKAA")
    assert short(lk[0]) == ("U", 660, 305, 5, 19, 2, 1, "LKAA_U_CTR")
    assert [(b["label"], b["merged"], b["owner"]) for b in lk[1:]] == [("NL", False, None), ("SL", False, None),
                                                                       ("MT", False, None)]
    # LKAA_CTR wszędzie: jedno okienko na prostokąt z pustą komórką pod NL
    (b,) = boxes(get(client, [ctl("LKAA_CTR", "127.125")]), "LKAA")
    assert short(b) == ("LKAA", 660, 0, 5, 19, 2, 3, "LKAA_CTR")
    assert sorted(m["id"] for m in b["members"]) == ["MT", "NL", "NU", "SL", "SU"]


def test_merge_esaa(client):
    # ESAA_CTR obsługuje wszystkie: prostokąt 2 × 3 z pustą komórką obok L
    (b,) = boxes(get(client, [ctl("ESAA_CTR", "128.180")]), "ESAA")
    assert short(b) == ("ESAA", 660, 0, 5, 5, 2, 3, "ESAA_CTR") and len(b["members"]) == 5
    # ESMM_6 i ESMM_9: 6 obsługuje 6, 8, 7 – prostokąt z 9 w środku nie, więc tylko ciąg 6 + 7 w kolumnie F
    es = {b["label"]: b for b in boxes(get(client, [ctl("ESMM_6_CTR", "135.805"), ctl("ESMM_9_CTR", "135.985")]), "ESAA")}
    assert short(es["6"]) == ("6", 660, 0, 6, 5, 1, 2, "ESMM_6_CTR") and es["6"]["id"] == "6+7"
    assert short(es["8"]) == ("8", 365, 195, 5, 6, 1, 1, "ESMM_6_CTR") and not es["8"]["merged"]
    assert es["9"]["owner"] == "ESMM_9_CTR" and es["L"]["owner"] is None


def test_merge_never_edww(client):
    d = get(client, [ctl("EDWW_CTR", "129.050")])
    assert [(b["label"], b["owner"], b["merged"]) for b in boxes(d, "EDWW")] == [
        ("MRZ", "EDWW_CTR", False), ("MAR", "EDWW_CTR", False), ("FLG", "EDWW_CTR", False)]


def test_merge_eduu_runs(client):
    # OSE2 i HVL2 to jedno stanowisko (EDUU_O22_CTR), ale między nimi OSE1 (nieobsadzone): osobno
    ed = {b["label"]: b for b in boxes(get(client, [ctl("EDUU_O22_CTR", "126.785")]), "EDUU")}
    assert set(ed) == {"OSE2", "OSE1", "HVL2", "HVL1", "SPE1"}
    assert ed["OSE2"]["owner"] == ed["HVL2"]["owner"] == "EDUU_O22_CTR" and ed["OSE1"]["owner"] is None
    assert not any(b["merged"] for b in ed.values())
    # EDUU_H12_CTR obsługuje całe EDUU: jedno okienko na kolumnę C (puste komórki między nimi)
    (b,) = boxes(get(client, [ctl("EDUU_H12_CTR", "128.235")]), "EDUU")
    assert short(b) == ("HVL1", 660, 285, 3, 7, 1, 9, "EDUU_H12_CTR")


def test_merge_same_frequency(client):
    # dwa znaki na jednej częstotliwości to jedno okienko (nazwa wg najczęstszego właściciela)
    (b,) = boxes(get(client, [ctl("EYVL_U_CTR", "133.305"), ctl("EYVL_CTR", "133.305")]), "EYVL")
    assert short(b) == ("L", 660, 95, 12, 3, 1, 4, "EYVL_CTR")
    # różne częstotliwości: osobno
    ey = boxes(get(client, [ctl("EYVL_U_CTR", "132.280"), ctl("EYVL_CTR", "133.305")]), "EYVL")
    assert [short(b) for b in ey] == [("U", 660, 365, 12, 3, 1, 1, "EYVL_U_CTR"), ("L", 365, 95, 12, 4, 1, 3, "EYVL_CTR")]


def test_merge_pure():
    occ = {(1, 1): "a", (2, 1): "b", (1, 2): "c", (1, 3): "d"}

    def bx(i, col, row, owner, key=None):
        return {"id": i, "col": col, "row": row, "cols": 1, "rows": 1, "upper": 100 * (4 - row), "lower": 100 * (3 - row),
                "callsign": f"X_{i}_CTR", "chain": [f"X_{i}_CTR"], "owner": owner, "staffed": bool(owner),
                "frequency": None, "key": key or (owner and f"cs:{owner}")}

    # a i d w jednej kolumnie, c (inny) między nimi → osobno; nieobsadzone b nie łączy się z niczym
    out = rb.merge_boxes([bx("a", 1, 1, "X_a_CTR"), bx("b", 2, 1, None), bx("c", 1, 2, "Y_CTR"), bx("d", 1, 3, "X_a_CTR")],
                         occ, "XXXX")
    assert [(b["id"], b["merged"]) for b in out] == [("a", False), ("b", False), ("c", False), ("d", False)]
    out = rb.merge_boxes([bx("a", 1, 1, "X_a_CTR"), bx("c", 1, 2, "X_a_CTR"), bx("d", 1, 3, "X_a_CTR")], occ, "XXXX")
    assert [(b["id"], b["label"], b["rows"], b["upper"], b["lower"]) for b in out] == [("a+c+d", "a", 3, 300, 0)]
    assert rb.merged_label([{"id": "NU", "callsign": "LKAA_U_CTR"}, {"id": "SU", "callsign": "LKAA_U_CTR"}],
                           "LKAA_U_CTR", "LKAA") == "U"
    assert rb.merged_label([{"id": "9", "callsign": "ESMM_9_CTR"}], "ESAA_CTR", "ESAA") == "ESAA"
    assert rb.merged_label([{"id": "U", "callsign": "EYVL_U_CTR"}], "EDWW_MRZ_CTR", "EYVL") == "MRZ"
    assert rb.merge_key("EYVL_CTR", {"EYVL_CTR": {"callsign": "EYVL_CTR", "frequency": "133.305"}}) == "fq:133.305"
    assert rb.merge_key("EYVL_CTR", {"EYVL_CTR": {"callsign": "EYVL_CTR", "frequency": "199.998"}}) == "cs:EYVL_CTR"
    assert rb.merge_key(None, {}) is None and rb.merge_key("X", {}) is None


def test_fir_box_owner_and_tooltip(client):
    """Okienko FIR-u z kilku kafelków (ACC UMMV): pierwsze stanowisko online z ich kolejności; wieża (UMBB TWR) nie
    obsługuje okienka ACC, ale jest w dymku FIR-u."""
    d = get(client, [ctl("UMBB_TWR", "118.500")])
    (b,) = boxes(d, "UMMV")
    f = next(f for f in d["firs"] if f["fir"] == "UMMV")
    assert b["owner"] is None and f["advisory"] and [w["callsign"] for w in f["online"]] == ["UMBB_TWR"]
    d = get(client, [ctl("UMMV_W_CTR", "135.700"), ctl("UMBB_TWR", "118.500")])
    (b,) = boxes(d, "UMMV")
    f = next(f for f in d["firs"] if f["fir"] == "UMMV")
    assert (b["label"], b["owner"], b["frequency"]) == ("ACC", "UMMV_W_CTR", "135.700") and not f["advisory"]
    assert [w["callsign"] for w in f["online"]] == ["UMBB_TWR", "UMMV_W_CTR"]
    (b,) = boxes(get(client, [ctl("UMKK_APP", "126.000")]), "UMKK")
    assert (b["label"], b["upper"], b["lower"], b["owner"]) == ("ACC", 999, 0, "UMKK_APP")


def test_net_error_no_advisory(client):
    SIDE["feed"] = UpstreamError("timeout")
    d = client.get("/api/radio/board").json()
    assert d["net"]["ok"] is False
    assert all(not f["advisory"] and not f["staffed"] for f in d["firs"])
    assert all(i["value"] == "0" for i in d["indicators"]) and d["plates"] == {"app": [], "twr": []}
    # BERLIN: bez danych o zalogowanych nie wiadomo, czy jest ATIS – bez konfiguracji (strona: kreska), nie czerwone
    # „No ATIS” (dawniej WEST domyślny)
    assert (d["berlin"]["config"], d["berlin"]["source"], d["berlin"]["preferred"]) == (None, "UNKNOWN", False)
    assert d["berlin"]["tip"] == "ATIS unknown: no network data"


# --- wskaźniki u góry
def test_indicators_sketch_example(client):
    d = get(client, [ctl("EPWW_ALL_CTR", "125.450", "Anna"), ctl("EPWW_S_CTR", "123.625", "Bartek"),
                     ctl("EPGD_APP", "127.280"), ctl("EPWA_APP", "128.805"), ctl("EPWA_N_APP", "125.055"),
                     ctl("EPWA_F_APP", "129.380"), ctl("EPKK_APP", "121.075"), ctl("EPPO_I_APP", "126.300")])
    ind = {i["id"]: i for i in d["indicators"]}
    assert {k: i["value"] for k, i in ind.items()} == {"ACC GAT": "ALL+S", "APP GD": "1", "APP WA": "2H+L",
                                                       "APP KK": "1-0", "APP PO": "0"}  # informacja się nie liczy
    assert ind["ACC GAT"]["positions"] == [
        {"callsign": "EPWW_ALL_CTR", "position": "EPWW_ALL_CTR", "frequency": "125.450", "name": "Anna"},
        {"callsign": "EPWW_S_CTR", "position": "EPWW_S_CTR", "frequency": "123.625", "name": "Bartek"}]
    assert [p["callsign"] for p in ind["APP WA"]["positions"]] == ["EPWA_APP", "EPWA_N_APP", "EPWA_F_APP"]
    assert [(i["col"], i["row"]) for i in d["indicators"]] == [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]
    nobody = get(client)
    assert [i["value"] for i in nobody["indicators"]] == ["0"] * 5 and all(not i["positions"] for i in nobody["indicators"])


def test_indicator_rules_pure():
    on = lambda *cs: {c: {"callsign": c, "frequency": "1", "name": None} for c in cs}  # noqa: E731
    hl = {"rule": "hl", "h": ["EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"], "l": ["EPWA_F_APP"]}
    assert rb.indicator_value(hl, on("EPWA_APP", "EPWA_F_APP"), [], {})[0] == "H+L"  # PANDORA
    assert rb.indicator_value(hl, on("EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"), [], {})[0] == "3H"
    assert rb.indicator_value(hl, on("EPWA_F_APP"), [], {})[0] == "L"
    assert rb.indicator_value(hl, on("EPWA_ATIS"), [], {})[0] == "0"
    ab = {"rule": "ab", "a": ["EPKK_APP", "EPKK_E_APP"], "b": ["EPKK_KK_APP", "EPKK_KT_APP"]}
    assert rb.indicator_value(ab, on("EPKK_APP", "EPKK_E_APP"), [], {})[0] == "2-0"
    assert rb.indicator_value(ab, on("EPKK_KT_APP"), [], {})[0] == "0-1"
    po = {"rule": "count", "count": ["EPPO_*_APP"]}
    assert rb.indicator_value(po, on("EPPO_N_APP", "EPPO_S_APP", "EPPO_I_APP", "EPPO_IS_APP"), [], {}) == (
        "2", ["EPPO_N_APP", "EPPO_S_APP"])
    # ten sam kontroler pod dwoma stanowiskami liczy się raz
    twin = {"EPPO_N_APP": {"callsign": "EPPO_APP"}, "EPPO_S_APP": {"callsign": "EPPO_APP"}}
    assert rb.indicator_value(po, twin, [], {})[0] == "1"
    acc = {"rule": "acc"}
    sec = [{"owner": "EPWW_S_CTR"}, {"owner": "EPWW_N_CTR"}, {"owner": "EPWW_N_CTR"}]
    short_ = {"EPWW_N_CTR": "N", "EPWW_S_CTR": "S", "EPWW_E_CTR": "E"}
    assert rb.indicator_value(acc, on("EPWW_S_CTR", "EPWW_N_CTR", "EPWW_E_CTR"), sec, short_)[0] == "N+S+E"
    assert rb.indicator_value(acc, {}, sec, short_) == ("0", [])


# --- BERLIN
def test_berlin_pure():
    st = lambda *lines, letter="C": [atis("EDDB_ATIS", letter, list(lines))]  # noqa: E731
    b = rb.berlin_config(st("BERLIN BRANDENBURG INFORMATION C", "RWY 25R 25L"))
    assert (b["config"], b["source"], b["preferred"], b["runways"], b["tip"]) == (
        "WEST", "ATIS", False, ["25R", "25L"], "ATIS C: 25R 25L")
    b = rb.berlin_config(st("RWY 07L IN USE", letter="D"))
    assert (b["config"], b["source"], b["tip"]) == ("EAST", "ATIS", "ATIS D: 07L")
    assert rb.berlin_config(st("ARR RWY 06R DEP RWY 06L"))["config"] == "EAST"
    assert rb.berlin_config(st("RUNWAYS 24R AND 24L IN USE"))["runways"] == ["24R", "24L"]
    # bez ATIS: wiatr z METAR (WEST, chyba że w plecy na 24 ponad 5 kt), czerwonym tekstem na stronie
    b = rb.berlin_config([], "EDDB 281220Z 09012KT 9999 FEW030 12/05 Q1012")
    assert (b["config"], b["source"], b["preferred"], b["wind"], b["tip"]) == (
        "EAST", "WIND", True, "090/12", "No ATIS: preferred by wind 090/12")
    b = rb.berlin_config([], "EDDB 281220Z 00000KT CAVOK 12/05 Q1012")
    assert (b["config"], b["source"], b["tip"]) == ("WEST", "WIND", "No ATIS: preferred by wind calm")
    assert rb.berlin_config([], "EDDB 281220Z 07005KT CAVOK 12/05 Q1012")["config"] == "WEST"  # 5 kt w plecy: jeszcze WEST
    assert rb.berlin_config([], "EDDB 281220Z 25025G35KT 9999 12/05 Q1012")["config"] == "WEST"
    assert rb.berlin_config([], "EDDB 281220Z VRB03KT CAVOK 12/05 Q1012")["config"] == "WEST"
    b = rb.berlin_config([])
    assert (b["config"], b["source"], b["preferred"], b["tip"]) == ("WEST", "DEFAULT", True, "No ATIS: default")
    assert rb.berlin_config([], "GARBAGE")["source"] == "DEFAULT"
    # ATIS bez pasa: jak bez ATIS (wiatr), z literą
    b = rb.berlin_config(st("BERLIN INFORMATION A", letter="A"), "EDDB 281220Z 09012KT 9999 12/05 Q1012")
    assert (b["config"], b["source"], b["tip"]) == ("EAST", "WIND", "ATIS A without runway: preferred by wind 090/12")
    # inne lotniska nie mylą Berlina
    assert rb.berlin_config([atis("EDDT_ATIS", "B", ["RWY 08L"])])["source"] == "DEFAULT"
    # pas zamknięty z uwag ATIS nie trafia do dymku jako pas w użyciu
    b = rb.berlin_config(st("BERLIN INFORMATION C", "RUNWAY IN USE 25R. RUNWAY 25L CLOSED DUE TO WORK IN PROGRESS"))
    assert (b["config"], b["runways"], b["tip"]) == ("WEST", ["25R"], "ATIS C: 25R")
    # nieczytelny ATIS (w tekście nie napis): jak ATIS bez pasa, bez błędu
    b = rb.berlin_config([atis("EDDB_ATIS", "C", ["INFO C", 5])], "EDDB 281220Z 09012KT 9999 12/05 Q1012")
    assert (b["config"], b["source"], b["tip"]) == ("EAST", "WIND", "ATIS unreadable: preferred by wind 090/12")
    # bez danych o zalogowanych: nie wiadomo, czy ATIS jest – bez konfiguracji, wiatr tylko w dymku
    b = rb.berlin_config([], "EDDB 281220Z 09012KT 9999 12/05 Q1012", net_ok=False)
    assert (b["config"], b["source"], b["preferred"], b["wind"], b["tip"]) == (
        None, "UNKNOWN", False, "090/12", "ATIS unknown: no network data; preferred by wind 090/12: EAST")


def test_berlin_board(client):
    d = get(client, atis_=[atis("EDDB_ATIS", "C", ["BERLIN BRANDENBURG INFORMATION C", "RWY 25R 25L"])])
    assert {k: d["berlin"][k] for k in ("config", "source", "tip", "col", "row")} == {
        "config": "WEST", "source": "ATIS", "tip": "ATIS C: 25R 25L", "col": 1, "row": 6}
    assert d["berlin"]["box"] == {"col": 1, "row": 7, "cols": 2, "rows": 1}
    assert SIDE["metar_calls"] == 0  # z ATIS bez METAR
    d = get(client, metar={"EDDB": "EDDB 281220Z 09012KT 9999 FEW030 12/05 Q1012"})
    assert (d["berlin"]["config"], d["berlin"]["source"]) == ("EAST", "WIND") and SIDE["metar_calls"] == 1
    assert get(client)["berlin"]["source"] == "DEFAULT"


def test_berlin_error_safe(client, monkeypatch):
    """Błąd przy liczeniu BERLIN psuje tylko BERLIN (kreska), nie całą tablicę (dawniej HTTP 500 i pusta strona)."""
    d = get(client, atis_=[atis("EDDB_ATIS", "C", ["INFO C", 5])])
    assert (d["berlin"]["config"], d["berlin"]["source"]) == ("WEST", "DEFAULT") and SIDE["metar_calls"] == 1

    def boom(*a, **k):
        raise ValueError("bad atis")

    monkeypatch.setattr(rb, "berlin_config", boom)
    d = get(client, atis_=[atis("EDDB_ATIS", "C", ["RWY 25R"])])
    assert {k: d["berlin"][k] for k in ("config", "source", "preferred", "col", "row")} == {
        "config": None, "source": "UNKNOWN", "preferred": False, "col": 1, "row": 6}
    assert len(d["firs"]) == 10 and len(d["indicators"]) == 5


def test_berlin_net_error_unknown(client):
    """Błąd danych o zalogowanych: BERLIN nie twierdzi „No ATIS”; wiatr z METAR tylko w dymku."""
    SIDE["feed"] = UpstreamError("timeout")
    SIDE["metar"] = {"EDDB": "EDDB 281220Z 09012KT 9999 FEW030 12/05 Q1012"}
    d = client.get("/api/radio/board").json()
    assert d["net"]["ok"] is False
    assert {k: d["berlin"][k] for k in ("config", "source", "preferred", "wind", "tip")} == {
        "config": None, "source": "UNKNOWN", "preferred": False, "wind": "090/12",
        "tip": "ATIS unknown: no network data; preferred by wind 090/12: EAST"}


def test_berlin_upstream_failure_safe(client, monkeypatch):
    SIDE["metar"] = UpstreamError("metar down")
    SIDE["feed"] = EMPTY
    r = client.get("/api/radio/board")
    assert r.status_code == 200 and r.json()["berlin"]["source"] == "DEFAULT"
    calls = SIDE["metar_calls"]
    client.get("/api/radio/board")
    assert SIDE["metar_calls"] == calls  # po błędzie przerwa (SIDE_MISS_S), bez pytania przy każdym odświeżeniu
    # za długo: tablica nie czeka dłużej niż SIDE_WAIT_S
    radio_router._SIDE_FAILED.clear()
    monkeypatch.setattr(radio_router, "SIDE_WAIT_S", 0.05)

    async def slow(icaos):
        await asyncio.sleep(2)
        return {}

    monkeypatch.setattr(radio_router, "get_metars", slow)
    r = client.get("/api/radio/board")
    assert r.status_code == 200 and r.json()["berlin"]["source"] == "DEFAULT"
    assert "metar" in radio_router._SIDE_FAILED


# --- czerwone tło: ograniczenia przepływu i zajętość
NOW = datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc)
SECTORS = ["LB", "MB", "HB", "LC", "HC", "LD"]
TMAS = [{"tma": "TMA Warszawa", "icao": "EPWA"}, {"tma": "TMA Warszawa", "icao": "EPWA"},
        {"tma": "TMA Poznań N", "icao": "EPPO"}, {"tma": "TMA Poznań S", "icao": "EPPO"}]


def tv(i, active=False, occ=0, cap=None, restrictions=(), volumes=()):
    return {"id": i, "active": active, "occupancy": [occ, occ], "occupancy_cap": cap, "restrictions": list(restrictions),
            "volumes": list(volumes)}


def restr(start, end, value=20, kind="ENR-OCCUPANCY"):
    return {"start": start, "end": end, "value": value, "type": kind, "reason": "x"}


def test_flow_alerts_pure():
    out = rb.flow_alerts([
        tv("EP-BH", restrictions=[restr("2300", "2359", 30, "ENR-ENTRIES")]),     # ograniczenie teraz
        tv("EP-CH", restrictions=[restr("2200", "0200")]),                         # przez północ
        tv("EP-BL", active=True, occ=12, cap=14),                                  # 12 z 14 > 80 %
        tv("EP-CL", active=False, occ=12, cap=14),                                 # nieaktywny bez ograniczenia
        tv("EP-DL", active=True, occ=11, cap=14),                                  # 78 %: jeszcze nie
        tv("EP-BM", restrictions=[restr("1000", "1200")]),                         # ograniczenie nie teraz
        tv("EP-ALLFIR", active=True, occ=30, cap=20, restrictions=[restr("0000", "2359")]),  # cały FIR: pomijamy
        tv("EP-WATMAD", restrictions=[restr("2300", "0100")]),
        tv("EP-POTMA", active=True, occ=9, cap=10),
        tv("EP-XYZ", active=True, occ=9, cap=10, volumes=["EPWW-BH", "EPWW-CH"]),  # złożony: przez wolumeny
        tv("EP-QQ", active=True, occ=9, cap=10, volumes=["EPWW-BH", "EPWW-Q"]),    # niejednoznaczny: pomijamy
    ], NOW, SECTORS, TMAS)
    assert set(out["sectors"]) == {"HB", "HC", "LB"} and set(out["tma"]) == {"TMA Warszawa", "TMA Poznań N",
                                                                             "TMA Poznań S"}
    hb = {a["tv"]: a for a in out["sectors"]["HB"]}
    assert set(hb) == {"EP-BH", "EP-XYZ"}
    assert hb["EP-BH"]["tip"] == ["Flow restriction: max 30 entries per hour until 23:59"] and not hb["EP-BH"]["busy"]
    assert hb["EP-XYZ"]["tip"] == ["EP-XYZ: Occupancy 9 of 10"]
    assert out["sectors"]["HC"][0]["tip"][0] == "Flow restriction: max occupancy 20 until 02:00"
    lb = out["sectors"]["LB"][0]
    assert (lb["busy"], lb["occupancy"], lb["capacity"], lb["tip"]) == (True, 12, 14, ["Occupancy 12 of 14"])
    assert out["tma"]["TMA Warszawa"][0]["tv"] == "EP-WATMAD"
    # okno przez północ: po północy też, w dzień nie (wspólna reguła viff.restriction_active, jak OVERVIEW i FMP)
    def at(hm):
        return datetime(2026, 10, 28, int(hm[:2]), int(hm[2:]), tzinfo=timezone.utc)
    win = {"start": "2200", "end": "0200"}
    assert restriction_active(win, at("0100")) and restriction_active(win, at("2330"))
    assert not restriction_active(win, at("1200")) and not restriction_active({"start": "", "end": "0200"}, at("0100"))
    assert rb.flow_alerts(None, NOW, SECTORS, TMAS) == {"sectors": {}, "tma": {}}


def test_flow_board(client):
    d = get(client, tvs=[tv("EP-BH", active=True, occ=12, cap=14), tv("EP-WATMA", restrictions=[restr("0000", "2359")]),
                         tv("EP-NFIR", active=True, occ=40, cap=10)])
    assert d["flow"]["ok"] is True and set(d["flow"]["sectors"]) == {"HB"}
    assert d["flow"]["sectors"]["HB"][0]["tip"] == ["Occupancy 12 of 14"]
    assert set(d["flow"]["tma"]) == {"TMA Warszawa"}
    assert get(client)["flow"] == {"ok": True, "sectors": {}, "tma": {}}


def test_flow_tma_shapes_keyed(client):
    """Czerwone tło TMA na podglądzie LOW (0.13.0): kształty TMA w geo mają klucz TMA jak tma[].tma i flow.tma;
    wspólne części kilku TMA bez własnego kształtu – bez klucza (tylko obrys)."""
    d = client.get("/api/radio/board?geo=1").json()
    keys = {t["tma"] for t in d["geo"]["tma"]}
    assert {g["tma"] for g in d["tma"]} <= keys and None in keys
    assert all(set(t) == {"name", "geometry", "tma"} for t in d["geo"]["tma"])
    wa = [t["name"] for t in d["geo"]["tma"] if t["tma"] == "TMA Warszawa"]
    assert wa and all(n.startswith("EPWA_") for n in wa)


def test_flow_viff_failure_safe(client):
    SIDE["tvs"] = UpstreamError("viff down")
    SIDE["feed"] = EMPTY
    r = client.get("/api/radio/board")
    assert r.status_code == 200
    assert r.json()["flow"] == {"ok": False, "sectors": {}, "tma": {}} and len(r.json()["sectors"]) == 30
    SIDE["tvs"] = ValueError("bad json")
    radio_router._SIDE_FAILED.clear()
    assert client.get("/api/radio/board").json()["flow"]["ok"] is False


# --- plakietki APP i TWR tylko dla zalogowanych
def test_plates_nobody(client):
    assert get(client)["plates"] == {"app": [], "twr": []}


def test_plates_app_split(client):
    d = get(client, [ctl("EPWA_APP", "128.805"), ctl("EPWA_N_APP", "125.055"), ctl("EPWA_S_APP", "135.930")])
    wa = [p for p in d["plates"]["app"] if p["tma"] == "TMA Warszawa"]
    assert [(p["owner"], p["parts"]) for p in wa] == [("EPWA_APP", ["EPWA_APP"]), ("EPWA_N_APP", ["EPWA_N_APP"]),
                                                       ("EPWA_S_APP", ["EPWA_S_APP"])]
    assert len({tuple(p["at"]) for p in wa}) == 3 and all(p["icao"] == "EPWA" for p in wa)
    tma = {g["id"]: g for g in d["tma"]}
    for p in wa:  # w swojej części TMA
        lon0, lat0, lon1, lat1 = tma[f"TMA Warszawa · {p['owner']}"]["box"]
        assert lat0 <= p["at"][0] <= lat1 and lon0 <= p["at"][1] <= lon1
    assert {p["owner"] for p in d["plates"]["app"]} == {"EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"}  # jedna na stanowisko
    s = next(p for p in wa if p["owner"] == "EPWA_S_APP")
    assert {"TMA Radom", "TMA Łódź"} <= set(s["covers"]) and s["frequency"] == "135.930"


def test_plates_app_alone_and_directors(client):
    d = get(client, [ctl("EPWA_APP", "128.805"), ctl("EPWA_F_APP", "129.380")])
    (p,) = d["plates"]["app"]
    assert (p["owner"], p["tma"], p["parts"]) == ("EPWA_APP", "TMA Warszawa", ["EPWA_APP", "EPWA_N_APP", "EPWA_S_APP"])
    assert {"TMA Warszawa · EPWA_APP", "TMA Warszawa · EPWA_N_APP", "TMA Warszawa · EPWA_S_APP"} <= set(p["covers"])
    # sam dyrektor: bez plakietki (nie jest sektorem podejścia)
    assert get(client, [ctl("EPWA_F_APP", "129.380")])["plates"]["app"] == []
    # KK APP: TMA Kraków (obie części) – jedna plakietka, choć obsługuje też TMA Katowice
    (p,) = get(client, [ctl("EPKK_APP", "121.075"), ctl("EPKK_KK_APP", "126.530")])["plates"]["app"]
    assert (p["owner"], p["tma"], p["parts"]) == ("EPKK_APP", "TMA Kraków", ["EPKK_APP", "EPKK_E_APP"])
    assert "TMA Katowice · EPKK_APP" in p["covers"]
    # ACC i wieża TMA proceduralnej nie dają plakietki APP
    assert get(client, [ctl("EPWW_N_CTR", "130.675"), ctl("EPSC_TWR", "121.255")])["plates"]["app"] == []


def test_plates_twr(client):
    d = get(client, [ctl("EPKK_TWR", "123.255")], [atis("EPGD_ATIS", "A", ["GDANSK INFO A"], "136.000")])
    twr = {p["icao"]: p for p in d["plates"]["twr"]}
    assert set(twr) == {"EPKK", "EPGD"}
    assert (twr["EPKK"]["twr"], twr["EPKK"]["frequency"], twr["EPKK"]["layers"]) == (["EPKK_TWR"], "123.255",
                                                                                    ["twr", "twra"])
    # sam ATIS: plakietka tylko na warstwie TWR/A
    assert (twr["EPGD"]["twr"], twr["EPGD"]["atis"], twr["EPGD"]["layers"]) == ([], ["EPGD_ATIS"], ["twra"])
    ctr = {g["icao"]: g for g in d["twr"]}
    lon0, lat0, lon1, lat1 = ctr["EPKK"]["box"]
    assert lat0 <= twr["EPKK"]["at"][0] <= lat1 and lon0 <= twr["EPKK"]["at"][1] <= lon1  # w środku CTR
    # APP obsługujący CTR z góry to nie wieża: bez plakietki TWR
    assert get(client, [ctl("EPGD_APP", "127.280")])["plates"]["twr"] == []
