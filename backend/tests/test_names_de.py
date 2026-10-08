"""Nazwy sektorów i znaki radiowe niemieckich stanowisk (data/seed/names_de.json, baza wiedzy VATSIM Germany)."""
import json
import re

import pytest

from backend.app.config import DATA_DIR

PATH = DATA_DIR / "seed" / "names_de.json"
FIRS = {"EDWW", "EDMM", "EDUU", "EDYY", "EDGG"}
LOGIN = re.compile(r"^ED[A-Z]{2}(?:_[A-Z0-9]{1,5})?_(?:CTR|APP|DEP)$")
FREQ = re.compile(r"^1\d\d\.\d{3}$")
KB = "https://knowledgebase.vatsim-germany.org/"


@pytest.fixture(scope="module")
def doc() -> dict:
    return json.loads(PATH.read_text("utf-8"))


@pytest.fixture(scope="module")
def positions(doc) -> dict:
    return doc["positions"]


def test_plik_i_zrodlo(doc, positions):
    assert KB in doc["_zrodlo"] and "2026-10-08" in doc["_zrodlo"]
    assert len(positions) >= 50


def test_kazde_stanowisko(positions):
    for login, p in positions.items():
        assert LOGIN.match(login), login
        assert p["radio"].strip() and p["radio"] == p["radio"].strip(), login
        assert FREQ.match(p["freq"]), (login, p["freq"])
        assert 118.0 <= float(p["freq"]) < 137.0, (login, p["freq"])
        assert p["fir"] in FIRS, (login, p["fir"])
        assert p["sector"].strip(), login
        assert p["url"].startswith(KB + "books/"), login
        for key in ("limits", "covers", "uwaga"):
            assert key not in p or (isinstance(p[key], str) and p[key].strip()), (login, key)


def test_znak_radiowy_pasuje_do_fir(positions):
    # stanowiska EDUU/EDYY zawsze jako Rhein/Maastricht Radar, niezależnie od FIR-u pod spodem
    radio = {"EDWW": "Bremen Radar", "EDMM": "München Radar", "EDUU": "Rhein Radar", "EDYY": "Maastricht Radar",
             "EDGG": "Langen Radar"}
    for login, p in positions.items():
        assert p["radio"] == radio[p["fir"]], login
        if login[:4] in ("EDUU", "EDYY"):
            assert p["fir"] == login[:4], login


def test_aliasy(positions):
    seen = set()
    for login, p in positions.items():
        for a in p.get("aliases", []):
            assert LOGIN.match(a) and a not in positions and a not in seen, (login, a)
            seen.add(a)
    assert positions["EDWW_ALR_CTR"]["aliases"] == ["EDWW_AL1_CTR", "EDWW_AL2_CTR"]


def test_stanowiska_przy_polsce(positions):
    """Stanowiska graniczące z EPWW lub nad nim: muszą być w pliku, z częstotliwością jak w pakiecie sektorów."""
    expect = {"EDWW_MRZ_CTR": "124.175", "EDWW_MAR_CTR": "136.050", "EDWW_FLG_CTR": "136.450",
              "EDWW_BOR_CTR": "123.225", "EDDB_N_APP": "119.630", "EDDB_S_DEP": "120.630",
              "EDMM_MEI_CTR": "124.960", "EDMM_HOF_CTR": "133.565", "EDMM_GER_CTR": "133.230",
              "EDDC_SAS_APP": "125.875", "EDDP_TRS_APP": "126.175", "EDUU_O12_CTR": "133.035",
              "EDUU_O22_CTR": "126.785", "EDUU_H12_CTR": "128.235", "EDUU_SPE_CTR": "133.285",
              "EDUU_SAL_CTR": "133.860"}
    for login, freq in expect.items():
        assert positions[login]["freq"] == freq, login
    assert positions["EDWW_MRZ_CTR"]["sector"] == "Müritz (MRZ)"
    assert positions["EDUU_SPE_CTR"]["sector"] == "Spree (SPE)"
