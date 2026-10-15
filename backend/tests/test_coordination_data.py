"""Rejestr dokumentów COORDINATION (data/seed/coordination.json): pliki, identyfikatory, AIRAC, powiązanie z loa.json
i tabela etykiet polskich sektorów (ep_sectors)."""
import itertools
import json
import re
from datetime import date

import pytest

from backend.app.config import DATA_DIR
from backend.app.importers.ese import ese_sections, parse_positions, read_airspace, read_text
from backend.app.services import coordination as cs
from backend.app.services.airac import current_airac

SEED = DATA_DIR / "seed"
DOCS = DATA_DIR / "docs"
FIELDS = {"id", "type", "name", "file", "firs", "positions", "airac", "effective", "version", "loa", "agreements", "note"}
TRANSFER = {"dir", "traffic", "cop", "level", "from", "to", "conditions"}


@pytest.fixture(scope="module")
def coord():
    return json.loads((SEED / "coordination.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def loa():
    return json.loads((SEED / "loa.json").read_text("utf-8"))["firs"]


@pytest.fixture(scope="module")
def own():
    return json.loads((SEED / "ownership.json").read_text("utf-8"))


def test_format_described(coord):
    f = coord["_format"]
    assert isinstance(f, dict) and f["opis"]
    for k in FIELDS | {"ep_sectors"}:
        assert isinstance(f.get(k), str) and f[k].strip(), k


def test_documents_fields(coord):
    docs = coord["documents"]
    assert docs and isinstance(docs, list)
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids)), "powtórzony id"
    for d in docs:
        assert set(d) == FIELDS, d["id"]
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", d["id"]), d["id"]
        assert d["type"] in ("LOA", "LOP"), d["id"]
        assert isinstance(d["name"], str) and d["name"].strip() and not d["name"].endswith(".pdf"), d["id"]
        for k in ("firs", "positions", "loa", "agreements"):
            assert isinstance(d[k], list), (d["id"], k)
        for k in ("airac", "effective", "version", "note"):
            assert isinstance(d[k], str), (d["id"], k)
        assert d["firs"] and "EPWW" in d["firs"] and all(re.fullmatch(r"[A-Z]{4}", f) for f in d["firs"]), d["id"]
        assert all(isinstance(p, str) and p.strip() for p in d["positions"]), d["id"]
        if d["type"] == "LOP":
            assert d["firs"] == ["EPWW"], d["id"]


def test_files_exist_and_every_pdf_registered(coord):
    files = set()
    for d in coord["documents"]:
        f = d["file"]
        assert f.startswith(d["type"] + "/") and f.endswith(".pdf") and ".." not in f, d["id"]
        # nazwa bez "_" i "-": OTHER › DOCS robi z nich spacje (a stare odnośniki prowadzą do tych samych plików)
        assert "_" not in f and "-" not in f, d["id"]
        assert (DOCS / f).is_file(), f"{d['id']}: brak pliku data/docs/{f}"
        files.add(f)
    on_disk = {p.relative_to(DOCS).as_posix() for sub in ("LOA", "LOP") for p in (DOCS / sub).glob("*.pdf")}
    assert on_disk == files, "PDF w data/docs/LOA|LOP bez wpisu w coordination.json (albo odwrotnie)"


def test_airac_and_dates(coord):
    for d in coord["documents"]:
        if d["airac"]:
            assert re.fullmatch(r"\d{2}(0[1-9]|1[0-4])", d["airac"]), d["id"]
        if d["effective"]:
            day = date.fromisoformat(d["effective"])
            # AIRAC zgodny z datą wejścia w życie (cykl, w którym ta data wypada)
            if d["airac"]:
                assert current_airac(day)["ident"] == d["airac"], d["id"]
    edww = next(d for d in coord["documents"] if "EDWW" in d["loa"])
    assert (edww["airac"], edww["effective"], edww["version"]) == ("2602", "2026-02-19", "rev. 4.0")


def test_loa_keys(coord, loa):
    """Każdy FIR z loa.json należy do dokładnie jednego dokumentu, a PDF w loa.json (panel LOA w RADIO) to ten sam plik."""
    owner = {}
    for d in coord["documents"]:
        for key in d["loa"]:
            assert key in loa, f"{d['id']}: brak {key} w loa.json"
            assert key not in owner, f"{key} w dwóch dokumentach"
            owner[key] = d
            assert loa[key]["pdf"] == "/files/docs/" + d["file"], key
            assert key in d["firs"], d["id"]
    assert set(owner) == set(loa)
    assert {k for k, d in owner.items() if d["id"] == owner["EDWW"]["id"]} == {"EDWW", "EDUU"}


def test_inline_agreements_schema(coord):
    for d in coord["documents"]:
        for t in d["agreements"]:
            assert TRANSFER <= set(t) <= TRANSFER | {"fir"}, d["id"]
            assert t["dir"] in ("in", "out") and all(isinstance(v, str) for v in t.values()), d["id"]


def test_ep_sectors_table(coord, own):
    """Tabela etykiet: odwołania do istniejących sektorów ACC i TMA z ownership.json, stanowiska APP/TWR."""
    tab = coord["ep_sectors"]
    assert tab
    for label, e in tab.items():
        assert e["refs"] and set(e) <= {"refs", "local", "note"}, label
        for ref in e["refs"]:
            assert cs.ref_chain(ref, own), f"{label}: nieznany sektor {ref}"
        assert all(re.fullmatch(r"EP[A-Z]{2}_[A-Z0-9_]+", c) for c in e.get("local", [])), label


def test_every_ep_label_in_loa_resolves(coord, loa, own):
    """Każda etykieta polskiego sektora z przekazań w loa.json ma kolejność przejmowania (inaczej wiersz dotyczyłby
    każdego stanowiska ACC)."""
    labels = {(t["from"] if t["dir"] == "out" else t["to"]) for f in loa.values() for t in f["transfers"]}
    for label in sorted(labels - {""}):
        assert cs.resolve_label(label, coord["ep_sectors"], own), label


# etykieta z tabeli ep_sectors → wycinek z pliku .ese EPWW przy sąsiedzie z LOA, którego listę OWNER odwzorowuje "local"
ESE_SECTOR = {"EPSC TMA": "EPSC_TMA_D", "EPGD APP": "EPGD_UTMA", "AGD": "EPGD_UTMA", "EPPO S": "EPPO_TMA_S_G",
              "EPPO-S": "EPPO_TMA_S_G", "TRZ": "EPRZ_TMA_D",
              # LOA LKAA (Praha): część TMA przy granicy z Czechami, tylko EPKK_APP; LOA LZBB rozróżnia West i East
              "TMA Kraków": "EPKK_TMA_W", "TMA Kraków West": "EPKK_TMA_W", "TMA Kraków East": "EPKK_TMA_E"}


def test_ep_sectors_local_matches_ese_owner(coord):
    """local = stanowiska z listy OWNER wycinka w pliku .ese przed pierwszym sektorem ACC, w tej samej kolejności.
    Inaczej przy dwóch zalogowanych APP Kraków przekazania z Pragą dostałby EPKK_E_APP zamiast EPKK_APP."""
    secs = ese_sections(read_text(DATA_DIR / "import" / "EPWW-Sector.ese"))
    ids = {}
    for p in parse_positions(secs.get("[POSITIONS]", [])):
        ids.setdefault(p["position_id"], p["callsign"])
    owners = {}
    for s in read_airspace(secs.get("[AIRSPACE]", []))[1]:
        if s["fir"] == "EPWW":
            owners.setdefault(s["name"], [ids.get(x, x) for x in s["owners"].split(":") if x])
    tab = coord["ep_sectors"]
    assert {k for k, e in tab.items() if e.get("local")} == set(ESE_SECTOR)
    for label, name in ESE_SECTOR.items():
        lead = list(itertools.takewhile(lambda c: not cs.ACC_CS.match(c), owners[name]))
        assert lead and tab[label]["local"] == lead, (label, name, lead)
