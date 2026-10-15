"""COORDINATION (0.12.3): parsowanie przekazań z LOA, etykiety polskich sektorów → kolejność przejmowania, wybór
stanowiska (kto obsługuje sektor) i GET /api/coordination."""
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import settings
from backend.app.services import coordination as cs


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="module")
def own():
    return json.loads((settings.seed_dir / "ownership.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def aliases():
    return json.loads((settings.seed_dir / "coordination.json").read_text("utf-8"))["ep_sectors"]


# --- parsowanie
@pytest.mark.parametrize("text, adep, ades", [
    ("ARR EPKS, EPPW", [], ["EPKS", "EPPW"]),
    ("DEP EDDC, EDAB, EDDP", ["EDDC", "EDAB", "EDDP"], []),
    ("DEP EPRZ, ARR UKLL", ["EPRZ"], ["UKLL"]),
    ("DEP UKLL, ARR EPRZ", ["UKLL"], ["EPRZ"]),
    ("ARR pozostałe LKAA", [], []),          # nie kody ICAO: tylko tekst
    ("ARR LKCS, pozostałe", [], ["LKCS"]),
    ("EPWA", [], []),                         # bez ARR/DEP nie wiadomo, co to za lotnisko
    ("", [], []),
    (None, [], []),
])
def test_parse_traffic(text, adep, ades):
    assert cs.parse_traffic(text) == (adep, ades)


@pytest.mark.parametrize("text, level, transfer", [
    ("FL250", 250, None),
    ("FL090", 90, None),
    ("↑ FL230-FL270", 230, "C"),
    ("↓ FL220, FL260B", 220, "D"),
    ("↓ FL270, przelot COP/trawersu FL280B", 270, "D"),
    ("FL340B", 340, None),
    ("max. FL350", 350, None),
    ("FL330 lub RFL, jeśli niższy", 330, None),
    ("uzgodniony z EPWW", None, None),
    ("", None, None),
])
def test_parse_level(text, level, transfer):
    assert cs.parse_level(text) == (level, transfer)


def test_cop_key():
    assert cs.cop_key("ALUKA") == "ALUKA" and cs.cop_key(" aluka ") == "ALUKA"
    assert cs.cop_key("-") == cs.cop_key("") == cs.cop_key("wszystkie COP") == cs.cop_key(None) == ""


# --- etykiety sektorów
def test_resolve_label(aliases, own):
    b_low = own["sectors"]["B"]["LOW"]
    assert cs.resolve_label("B LOW", aliases, own) == ("B LOW", {"B LOW": b_low})
    assert cs.resolve_label("B LOW (BWW)", aliases, own) == ("B LOW", {"B LOW": b_low})
    assert cs.resolve_label("EPWW J LOW", aliases, own)[1] == {"J LOW": own["sectors"]["J"]["LOW"]}
    assert cs.resolve_label("N LOW (EPWWNL)", aliases, own)[0] == "N LOW"
    # stare nazwy z LOA UKLV 2022 → dzisiejszy sektor R
    assert cs.resolve_label("SWW", aliases, own) == ("SWW", {"R LOW": own["sectors"]["R"]["LOW"],
                                                             "R MID": own["sectors"]["R"]["MID"]})
    assert cs.resolve_label("Warszawa R (RWW)", aliases, own)[0] == "RWW"
    # TMA: najpierw stanowisko APP/TWR, potem ACC top-down
    lab, ch = cs.resolve_label("EPSC TMA", aliases, own)
    assert ch["EPSC TMA"] == ["EPSC_TWR"] + own["tma_topdown"]["TMA Szczecin"]["chain"]
    assert cs.resolve_label("Rzeszów Tower (TRZ)", aliases, own)[1]["TRZ"][-5:] == \
        own["tma_topdown"]["TMA Rzeszów"]["chain"][-5:]
    assert cs.resolve_label("Gdańsk Approach (AGD)", aliases, own)[1]["AGD"][0] == "EPGD_APP"
    assert cs.resolve_label("TMA Kraków", {}, own) == ("TMA Kraków", {"TMA Kraków": own["tma_topdown"]["TMA Kraków"]["chain"]})
    for label in ("", "FIS (VFR)", "X LOW", "MAR", "Warszawa R"):
        assert cs.resolve_label(label, aliases, own) is None, label


def test_register_reuses_alias_chain_but_keeps_acc_sectors():
    chains = {}
    assert cs.register(chains, {"EPPO S": ["EPPO_S_APP", "EPWW_TM_CTR"]}) == ["EPPO S"]
    assert cs.register(chains, {"EPPO-S": ["EPPO_S_APP", "EPWW_TM_CTR"]}) == ["EPPO S"]
    # N MID i N HIGH: ta sama kolejność, dwa różne sektory
    assert cs.register(chains, {"N MID": ["EPWW_NE_CTR"], "N HIGH": ["EPWW_NE_CTR"]}) == ["N MID", "N HIGH"]
    assert set(chains) == {"EPPO S", "N MID", "N HIGH"}


def test_owns():
    chain = ["EPWW_DBT_CTR", "EPWW_DBF_CTR", "EPWW_N_CTR", "EPWW_ALL_CTR"]
    # nikt online: wybrane stanowisko samo obsługuje każdy sektor, w którego kolejności jest
    assert cs.owns(chain, "EPWW_N_CTR", set())
    assert not cs.owns(chain, "EPWW_D_CTR", set())
    # ktoś wyżej w kolejności online: sektor jest jego
    assert not cs.owns(chain, "EPWW_N_CTR", {"EPWW_DBT_CTR"})
    # online niżej w kolejności albo poza nią – bez wpływu
    assert cs.owns(chain, "EPWW_DBF_CTR", {"EPWW_N_CTR", "EPWW_D_CTR"})
    # samo wybrane stanowisko online
    assert cs.owns(chain, "EPWW_DBT_CTR", {"EPWW_DBT_CTR"})


# --- budowa odpowiedzi na danych testowych
OWN = {"sectors": {"B": {"LOW": ["EPWW_DBT_CTR", "EPWW_N_CTR"], "MID": ["EPWW_DBT_CTR", "EPWW_N_CTR"]},
                   "J": {"LOW": ["EPWW_J_CTR", "EPWW_S_CTR"]}},
       "tma_topdown": {"TMA Warszawa": {"chain": ["EPWW_C_CTR", "EPWW_N_CTR"]}},
       "acc_positions": {"EPWW_DBT_CTR": {"short": "DBT", "frequency": "127.025"}}}
COORD = {
    "documents": [
        {"id": "loa-x", "type": "LOA", "name": "Warszawa ACC – X ACC", "file": "LOA/x.pdf", "firs": ["EPWW", "EDWW"],
         "positions": [], "airac": "2610", "effective": "2026-10-01", "version": "1.0", "loa": ["EDWW", "ZZZZ"],
         "agreements": [], "note": ""},
        {"id": "lop-epwa", "type": "LOP", "name": "LOP Warszawa APP – ACC", "file": "LOP/epwa.pdf", "firs": ["EPWW"],
         "positions": [], "airac": "2602", "effective": "", "version": "", "loa": [], "note": "",
         "agreements": [{"dir": "out", "traffic": "DEP EPWA", "cop": "SOXER", "level": "↑ FL150", "from": "EPWA APP",
                         "to": "J LOW", "conditions": "zwolniony do wznoszenia"},
                        {"dir": "sideways", "traffic": "", "cop": "", "level": "", "from": "", "to": "", "conditions": ""}]},
    ],
    "ep_sectors": {"EPWA APP": {"refs": ["TMA Warszawa"], "local": ["EPWA_APP"]}},
}
LOA = {"firs": {
    "EDWW": {"title": "LOA EPWW – EDWW", "version": "rev 1", "pdf": "/files/docs/LOA/x.pdf",
             "positions": [{"side": "EP", "callsign": "", "sector": "B LOW (BWW)"},
                           {"side": "EP", "callsign": "EPKK_I_APP", "sector": "FIS (VFR)", "radio": "Krakow Information"}],
             "transfers": [{"dir": "in", "traffic": "ARR EPKS, EPPW", "cop": "ALUKA", "level": "FL250", "from": "MAR",
                            "to": "B LOW", "conditions": ""},
                           {"dir": "out", "traffic": "DEP EPPO", "cop": "RASAN", "level": "FL340", "from": "",
                            "to": "", "conditions": ""},
                           {"dir": "out", "traffic": "DEP EPSC", "cop": "BINKA", "level": "FL240", "from": "Q LOW",
                            "to": "MRZ", "conditions": ""}],
             "silent": ["Transfer of control na granicy AoR."], "vfr": [], "other": ["inne"]},
}}


@pytest.fixture
def built():
    return cs.build(COORD, LOA, OWN, airac="2610", names={"EPWA_APP": {"name": "Warszawa Approach", "frequency": "128.805"}},
                    file_exists=lambda f: f == "LOA/x.pdf")


def test_build_documents(built):
    x, lop = built["documents"]
    assert x["url"] == "/files/docs/LOA/x.pdf" and x["current"] and x["exists"] and x["count"] == 3
    assert not lop["current"] and not lop["exists"] and lop["count"] == 1   # zły kierunek pominięty
    assert built["errors"][0] == "loa-x: brak FIR ZZZZ w loa.json"
    assert built["current_airac"] == "2610" and built["firs"] == ["EPWW", "EDWW"]
    assert built["notes"]["EDWW"]["silent"] == ["Transfer of control na granicy AoR."]
    assert built["cops"] == ["ALUKA", "BINKA", "RASAN", "SOXER"]


def test_build_unregistered_pdf():
    """PDF w data/docs/LOA|LOP bez wpisu w coordination.json: karta z nazwą pliku i uwaga w errors (OTHER › DOCS
    już go nie pokazuje, więc bez karty zniknąłby z aplikacji); plik z wpisem nie dostaje drugiej karty."""
    d = cs.build(COORD, LOA, OWN, airac="2610", files=["LOA/x.pdf", "LOA/LOA EPWW UMMV Minsk (AIRAC 2611).pdf",
                                                         "LOP/nowy lop.PDF"])
    ids = [x["id"] for x in d["documents"]]
    assert ids == ["loa-x", "lop-epwa", "plik-loa-loa-epww-ummv-minsk-airac-2611-pdf", "plik-lop-nowy-lop-pdf"]
    x, lop, ummv, new = d["documents"]
    assert x["registered"] and lop["registered"]
    assert (ummv["type"], ummv["name"], ummv["file"], ummv["firs"], ummv["count"], ummv["registered"], ummv["exists"]) == \
        ("LOA", "LOA EPWW UMMV Minsk (AIRAC 2611)", "LOA/LOA EPWW UMMV Minsk (AIRAC 2611).pdf", ["EPWW"], 0, False, True)
    assert ummv["url"] == "/files/docs/LOA/LOA EPWW UMMV Minsk (AIRAC 2611).pdf" and not ummv["current"]
    assert (new["type"], new["name"]) == ("LOP", "nowy lop")
    assert any(e.startswith("LOA/LOA EPWW UMMV Minsk (AIRAC 2611).pdf: PDF bez wpisu") for e in d["errors"])
    assert not any(e.startswith("LOA/x.pdf") for e in d["errors"])
    # ten sam id już zajęty: kolejny numer
    assert cs.unregistered_doc("LOA/a.pdf", {"plik-loa-a-pdf"})["id"] == "plik-loa-a-pdf-2"


def test_build_rows(built):
    rows = {r["id"]: r for r in built["agreements"]}
    lop = rows["lop-epwa-0"]
    assert (lop["type"], lop["fir"], lop["doc"], lop["adep"], lop["level"], lop["transfer"]) == \
        ("LOP", "EPWW", "lop-epwa", ["EPWA"], 150, "C")
    assert lop["ep"] == "EPWA APP" and lop["nb"] == "J LOW" and lop["ep_chains"] == ["EPWA APP", "J LOW"]  # LOP: obie strony
    arr = rows["EDWW-0"]
    assert (arr["dir"], arr["ep"], arr["nb"], arr["ades"], arr["level"], arr["doc"]) == \
        ("in", "B LOW", "MAR", ["EPKS", "EPPW"], 250, "loa-x")
    assert arr["ep_chains"] == ["B LOW"] and not arr["ep_unknown"]
    # pusta strona polska: zakres z sektorów EP wymienionych w LOA, z adnotacją
    unk = rows["EDWW-1"]
    assert unk["ep_unknown"] and unk["ep_chains"] == ["B LOW"] and unk["scope"] == ["B LOW"]
    # nieznana etykieta: błąd do poprawienia w tabeli
    bad = rows["EDWW-2"]
    assert bad["ep_unmapped"] and bad["ep_chains"] == []
    assert any("EDWW-2" in e and "Q LOW" in e for e in built["errors"])


def test_build_positions(built):
    ps = {p["callsign"]: p for p in built["positions"]}
    assert [p["kind"] for p in built["positions"]] == sorted((p["kind"] for p in built["positions"]),
                                                            key=["ACC", "APP", "TWR"].index)
    assert ps["EPWA_APP"]["kind"] == "APP" and ps["EPWA_APP"]["frequency"] == "128.805"
    assert ps["EPWW_DBT_CTR"]["frequency"] == "127.025" and ps["EPWW_DBT_CTR"]["short"] == "DBT"
    assert ps["EPWW_N_CTR"]["sectors"] == ["B LOW", "EPWA APP"]


def test_for_position(built):
    d = cs.for_position(built, "EPWW_DBT_CTR", set())
    applies = {r["id"]: r["applies"] for r in d["agreements"]}
    assert applies == {"lop-epwa-0": False, "EDWW-0": True, "EDWW-1": True, "EDWW-2": True}
    assert d["selected"] == {"position": "EPWW_DBT_CTR", "online": [], "owned": ["B LOW"]}
    # DBT online: N nie obsługuje B LOW, ale obsługuje TMA Warszawa (EPWA_APP offline, C offline)
    d = cs.for_position(built, "EPWW_N_CTR", {"EPWW_DBT_CTR"})
    assert d["selected"]["owned"] == ["EPWA APP"]
    applies = {r["id"]: r["applies"] for r in d["agreements"]}
    assert applies["lop-epwa-0"] and not applies["EDWW-0"] and not applies["EDWW-1"]
    # wiersz bez sektorów (nieznana etykieta) dotyczy każdego ACC, ale nie APP
    assert applies["EDWW-2"]
    assert not {r["id"]: r["applies"] for r in cs.for_position(built, "EPWA_APP", set())["agreements"]}["EDWW-2"]


# --- endpoint na prawdziwych danych
def test_endpoint(client):
    d = client.get("/api/coordination").json()
    assert d["errors"] == []
    assert len(d["documents"]) == 7 and all(x["exists"] and x["type"] == "LOA" and x["registered"] for x in d["documents"])
    assert all(x["count"] > 0 for x in d["documents"])
    loa = json.loads((settings.seed_dir / "loa.json").read_text("utf-8"))["firs"]
    assert len(d["agreements"]) == sum(len(f["transfers"]) for f in loa.values())
    assert set(d["firs"]) == set(loa) and set(d["notes"]) == set(loa)
    assert all(r["doc"] for r in d["agreements"]) and not any(r["ep_unmapped"] for r in d["agreements"])
    # wiersze z pustą stroną polską (LKAA, LZBB): adnotacja i sektory z LOA
    lkaa = [r for r in d["agreements"] if r["fir"] == "LKAA"]
    assert all(r["ep_unknown"] and "J LOW" in r["ep_chains"] and "T LOW" in r["ep_chains"] for r in lkaa)
    assert d["unknown_label"] == "sektor nieokreślony w LOA"
    assert {"ALUKA", "ARSAP", "DIBED", "RASAN"} <= set(d["cops"]) and "-" not in d["cops"]
    ps = {p["callsign"]: p for p in d["positions"]}
    assert {"EPWW_DBT_CTR", "EPWW_ALL_CTR", "EPSC_TWR", "EPGD_APP", "EPPO_S_APP"} <= set(ps)
    assert ps["EPSC_TWR"]["kind"] == "TWR" and ps["EPWW_DBT_CTR"]["kind"] == "ACC"
    edww = next(x for x in d["documents"] if x["id"] == "loa-edww-eduu")
    assert client.get(edww["url"]).status_code == 200   # PDF przez /files/docs
    assert edww["current"] is (edww["airac"] == d["current_airac"])


def test_endpoint_position(client):
    d = client.get("/api/coordination?position=epww_dbf_ctr").json()
    assert d["selected"]["position"] == "EPWW_DBF_CTR" and "B LOW" in d["selected"]["owned"]
    on = {(r["fir"], r["ep"]) for r in d["agreements"] if r["applies"]}
    assert ("EDWW", "B LOW") in on and ("EDWW", "EPSC TMA") in on and ("ESAA", "") in on
    assert not any(f in ("LKAA", "LZBB", "UKLV") for f, _ in on)   # Praha, Bratysława i Lwów: sektory J, R, T
    # DBT sam przejmuje też T (jest w kolejności T LOW): widzi LOA z Pragą
    d = client.get("/api/coordination?position=EPWW_DBT_CTR").json()
    assert "T LOW" in d["selected"]["owned"] and any(r["applies"] and r["fir"] == "LKAA" for r in d["agreements"])
    # TM online: T LOW należy do TM, DBT nie widzi już Pragi
    d = client.get("/api/coordination?position=EPWW_DBT_CTR&online=EPWW_TM_CTR").json()
    assert not any(r["applies"] and r["fir"] == "LKAA" for r in d["agreements"])
    # D online: D LOW należy do D, ale D MID (DBT pierwszy w kolejności) zostaje
    d = client.get("/api/coordination?position=EPWW_DBT_CTR&online=EPWW_D_CTR").json()
    assert "D LOW" not in d["selected"]["owned"] and "D MID" in d["selected"]["owned"]
    assert d["selected"]["online"] == ["EPWW_D_CTR"]


def test_endpoint_krakow_tma_west(client):
    """LOA LKAA wymienia „TMA Kraków”: przy Czechach to TMA Kraków West (lista OWNER EPKK_TMA_W: tylko EPKK_APP).
    Przy obu APP Kraków online przekazania z Pragą ma EPKK_APP, nie EPKK_E_APP."""
    lkaa = lambda d: [r for r in d["agreements"] if r["fir"] == "LKAA" and r["applies"]]  # noqa: E731
    d = client.get("/api/coordination?position=EPKK_APP&online=EPKK_E_APP").json()
    assert lkaa(d) and "TMA Kraków" in d["selected"]["owned"]
    d = client.get("/api/coordination?position=EPKK_E_APP&online=EPKK_APP").json()
    assert not lkaa(d) and "TMA Kraków" not in d["selected"]["owned"]
    # TMA Kraków East (LOA LZBB) zostaje przy EPKK_E_APP
    assert any(r["applies"] and r["fir"] == "LZBB" for r in d["agreements"])


def test_endpoint_unregistered_pdf(client, monkeypatch, tmp_path):
    """Nowy PDF wrzucony do data/docs/LOA (bez wpisu w coordination.json) jest w COORDINATION › DOKUMENTY i w errors."""
    docs = tmp_path / "docs"
    shutil.copytree(settings.docs_dir, docs)
    (docs / "LOA" / "LOA EPWW UMMV Minsk (AIRAC 2611).pdf").write_bytes(b"%PDF-1.4\n")
    (docs / "ICAO" / "inny.pdf").parent.mkdir(exist_ok=True)
    (docs / "ICAO" / "inny.pdf").write_bytes(b"%PDF-1.4\n")   # spoza LOA/LOP: zostaje w OTHER › DOCS
    monkeypatch.setattr(settings, "docs_dir", docs)
    d = client.get("/api/coordination").json()
    extra = [x for x in d["documents"] if not x["registered"]]
    assert [x["file"] for x in extra] == ["LOA/LOA EPWW UMMV Minsk (AIRAC 2611).pdf"]
    assert extra[0]["exists"] and extra[0]["type"] == "LOA" and extra[0]["name"] == "LOA EPWW UMMV Minsk (AIRAC 2611)"
    assert d["errors"] == ["LOA/LOA EPWW UMMV Minsk (AIRAC 2611).pdf: PDF bez wpisu w data/seed/coordination.json "
                           "(dopisz nazwę, FIR-y i AIRAC)"]


def test_endpoint_errors(client, monkeypatch, tmp_path):
    assert client.get("/api/coordination?position=EPWW%20CTR").status_code == 400
    assert client.get("/api/coordination?position=EPWW_D_CTR&online=a;b").status_code == 400
    monkeypatch.setattr(settings, "seed_dir", tmp_path)
    r = client.get("/api/coordination")
    assert r.status_code == 404 and "coordination.json" in r.json()["detail"]
    (tmp_path / "coordination.json").write_text("{zepsuty", "utf-8")
    assert client.get("/api/coordination").status_code == 500
    # bez loa.json i ownership.json: dokumenty są, przekazań brak (bez folderu data/docs: bez kart z samych PDF-ów)
    monkeypatch.setattr(settings, "docs_dir", tmp_path / "brak")
    (tmp_path / "coordination.json").write_text(json.dumps(COORD), "utf-8")
    d = client.get("/api/coordination").json()
    assert [x["id"] for x in d["documents"]] == ["loa-x", "lop-epwa"] and not d["documents"][0]["exists"]
    assert [r["id"] for r in d["agreements"]] == ["lop-epwa-0"] and d["positions"] == []
