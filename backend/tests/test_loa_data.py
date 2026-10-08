"""Dane LOA z sąsiadami (data/seed/loa.json) i ich PDF-y w data/docs/LOA."""
import json

import pytest

from backend.app.config import DATA_DIR

LOA_JSON = DATA_DIR / "seed" / "loa.json"
LOA_DIR = DATA_DIR / "docs" / "LOA"
PDF_PREFIX = "/files/docs/LOA/"
# klucze zakładek sąsiadów w RADIO, dla których są LOA
EXPECTED = {"EDWW", "EDUU", "EDMM", "LKAA", "LZBB", "UKLV", "EYVL", "ESAA"}
LISTS = ("positions", "transfers", "silent", "vfr", "other")


@pytest.fixture(scope="module")
def firs():
    data = json.loads(LOA_JSON.read_text(encoding="utf-8"))
    assert data["_zrodlo"]
    return data["firs"]


def test_all_neighbours_present(firs):
    assert EXPECTED <= set(firs)


def test_fir_header_and_lists(firs):
    for key, fir in firs.items():
        for f in ("title", "version", "pdf"):
            assert isinstance(fir.get(f), str) and fir[f].strip(), f"{key}: brak {f}"
        for f in LISTS:
            assert isinstance(fir.get(f), list), f"{key}: {f} nie jest listą"
        assert fir["transfers"], f"{key}: brak przekazań"
        for f in ("silent", "vfr", "other"):
            assert all(isinstance(s, str) and s.strip() for s in fir[f]), f"{key}: pusty tekst w {f}"


def test_pdf_exists(firs):
    for key, fir in firs.items():
        assert fir["pdf"].startswith(PDF_PREFIX), key
        name = fir["pdf"][len(PDF_PREFIX):]
        assert "/" not in name and (LOA_DIR / name).is_file(), f"{key}: brak pliku {name}"


def test_every_pdf_used_and_titled_cleanly(firs):
    """Każdy PDF z data/docs/LOA ma swój FIR; nazwa bez "_" i "-", bo DOCS robi z nich spacje w tytule."""
    used = {fir["pdf"][len(PDF_PREFIX):] for fir in firs.values()}
    on_disk = {p.name for p in LOA_DIR.glob("*.pdf")}
    assert on_disk == used
    assert all("_" not in n and "-" not in n for n in on_disk)


def test_transfers(firs):
    fields = {"dir", "traffic", "cop", "level", "from", "to", "conditions"}
    for key, fir in firs.items():
        for t in fir["transfers"]:
            assert set(t) == fields, f"{key}: {t}"
            assert t["dir"] in {"in", "out"}, f"{key}: {t}"
            assert t["cop"].strip() or t["traffic"].strip(), f"{key}: {t}"
            assert t["level"].strip(), f"{key}: brak poziomu w {t}"
            assert all(isinstance(v, str) for v in t.values()), f"{key}: {t}"


def test_positions(firs):
    fields = {"callsign", "radio", "sector", "frequency", "side", "note"}
    for key, fir in firs.items():
        for p in fir["positions"]:
            assert set(p) == fields, f"{key}: {p}"
            assert p["side"] in {"NB", "EP"}, f"{key}: {p}"
            assert p["callsign"] or p["sector"], f"{key}: {p}"
            # częstotliwość pusta (LOA jej nie podaje) albo w formacie 1xx.xxx
            f = p["frequency"]
            assert not f or (len(f) == 7 and f[3] == "." and f.replace(".", "").isdigit()), f"{key}: {p}"


def test_both_directions_where_loa_has_them(firs):
    """Kontrola przepisania tabel: przekazania w obie strony i znane wiersze z PDF-ów."""
    for key, fir in firs.items():
        dirs = {t["dir"] for t in fir["transfers"]}
        assert dirs == {"in", "out"}, key
    edww = {(t["dir"], t["traffic"], t["cop"], t["level"], t["to"]) for t in firs["EDWW"]["transfers"]}
    assert ("out", "ARR EDDB", "GOVEN", "FL120", "DBAS") in edww
    lkaa = {(t["dir"], t["traffic"], t["cop"], t["level"]) for t in firs["LKAA"]["transfers"]}
    assert ("in", "ARR EPKK", "NETIR", "↓ FL150, FL190B") in lkaa
