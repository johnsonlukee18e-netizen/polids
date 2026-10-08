"""MAP: rodzaje przestrzeni z nazw wycinków .ese, warstwy wg poziomu i właściciele TMA (runda 8)."""
import json

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.config import DATA_DIR
from backend.app.database import Base
from backend.app.importers.ese import parse_ese
from backend.app.importers.sct import read_text
from backend.app.models import AtcPosition, Sector
from backend.app.routers.nav import group_label, slice_kind, slice_label, slices

SQUARE = json.dumps({"type": "Polygon", "coordinates": [[[20, 52], [21, 52], [21, 53], [20, 53], [20, 52]]]})


@pytest.mark.parametrize("fir,name,expected", [
    # TMA Warszawa w pliku .ese to wycinki EPWA_APP_* i EPWA_DIR* (błąd z rundy 7: TMA nie podświetlała się przy EPWA_APP)
    ("EPWW", "EPWA_APP_N_A", ("tma", "EPWA")), ("EPWW", "EPWA_APP_S_G_CTA08", ("tma", "EPWA")),
    ("EPWW", "EPWA_DIR11_A", ("tma", "EPWA")), ("EPWW", "EPKK_LTMA_E_B_MID", ("tma", "EPKK")),
    ("EPWW", "EPKK_DEP07", ("tma", "EPKK")), ("EPWW", "EPKT_DIR08_S", ("tma", "EPKT")),
    ("EPWW", "EPGD_UTMA", ("tma", "EPGD")), ("EPWW", "EPDE_MTMA", ("tma", "EPDE")),
    ("EPWW", "EPPO_EPGD_TMA-CMN", ("tma", "EPPO")), ("EPWW", "EPBY_TMA_A", ("tma", "EPBY")),
    ("EPWW", "EPWA_CTR", ("ctr", "EPWA")), ("EPWW", "EPKK_CTR07", ("ctr", "EPKK")), ("EPWW", "EPDE_MCTR", ("ctr", "EPDE")),
    ("EPWW", "EPWWB", ("acc", "B")), ("EPWW", "EPWWR-N", ("acc", "R")), ("EPWW", "EPWW-MIDSEA", ("fis", "GDN")),
    ("EPWW", "FIS_WAW_C_WA1", ("fis", "WAW")), ("EPWW", "WAW_FIS_E_LB5", ("fis", "WAW")),
    ("EPWW", "CTA01_ABV_CTA03", ("cta", "CTA01")), ("EPWW", "EPBA_ATZ", ("atz", "EPBA")), ("EPWW", "EPTR38A", ("atz", "EPTR38A")),
    ("EDWW", "EDWWFLG1", ("nb", "EDWW")), ("LZBB", "CTR", ("nb", "LZBB")),
    ("ESAA", "TECH ESMM IS", None), ("EKDK", "T-DENMIL-RN", None),
])
def test_slice_kind(fir, name, expected):
    assert slice_kind(fir, name) == expected


def test_labels():
    assert group_label("tma", "EPWA") == "TMA Warszawa" and group_label("ctr", "EPKK") == "CTR Kraków"
    assert group_label("acc", "B") == "Sektor B" and group_label("fis", "GDN") == "FIS Gdańsk"
    assert group_label("atz", "EPTR28") == "TRA EPTR28" and group_label("nb", "EDWW") == "EDWW Bremen"
    assert slice_label("LZBB", "CTR") == "LZBB CTR" and slice_label("EDWW", "EDWWFLG1") == "EDWWFLG1"
    # TMA Poznań N i S osobno (klucze tma_topdown w ownership.json), wspólna część z Gdańskiem jako TMA Poznań
    assert group_label("tma", "EPPO", "EPPO_TMA_N_A") == "TMA Poznań N" and group_label("tma", "EPPO", "EPPO_TMA_S_G") == "TMA Poznań S"
    assert group_label("tma", "EPPO", "EPPO_EPGD_TMA-CMN") == "TMA Poznań" and group_label("tma", "EPKK", "EPKK_TMA_E") == "TMA Kraków"
    assert group_label("cta", "CTA02") == "CTA 02"


def test_group_labels_match_tma_topdown():
    """Każda TMA z tabeli top-down (ownership.json) to na MAP osobna grupa: różne klucze tabeli nie dzielą nazwy grupy,
    a TMA Poznań N i S nazywają się jak w tabeli."""
    own = json.loads((DATA_DIR / "seed" / "ownership.json").read_text("utf-8"))
    labels = {}
    for key, t in own["tma_topdown"].items():
        for pre in t["ese_prefixes"]:
            # prefiksy konfiguracji pasów (EPWA_DIR, EPKK_DEP/DIR) sprawdzamy na prawdziwych nazwach wycinków
            name = {"EPWA_DIR": "EPWA_DIR11_A", "EPKK_DEP": "EPKK_DEP25", "EPKK_DIR": "EPKK_DIR07"}.get(
                pre, pre if pre.endswith("_") else pre + "_A")
            kind, group = slice_kind("EPWW", name)
            assert kind == "tma", pre
            labels.setdefault(group_label(kind, group, name), set()).add(key)
    assert all(len(keys) == 1 for keys in labels.values()), labels
    assert labels["TMA Poznań N"] == {"TMA Poznań N"} and labels["TMA Poznań S"] == {"TMA Poznań S"}


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def _fill(db):
    pos = [("EPWA_APP", "AWA", "128.805"), ("EPWA_N_APP", "ANWA", "125.055"), ("EPWW_C_CTR", "CL", "133.475"),
           ("EDWW_FLG_CTR", "EDWF", "136.450")]
    db.execute(insert(AtcPosition), [{"callsign": c, "name": c, "frequency": f, "position_id": i, "prefix": c.split("_")[0]}
                                     for c, i, f in pos])
    sec = [("EPWW", "EPWA_APP_N_A", 2000, 9500, "ANWA:AWA:CL"), ("EPWW", "EPWA_APP_S_A", 12500, 22500, "AWA:CL"),
           ("EPWW", "EPWWC", 28500, 33500, "CL"), ("EDWW", "EDWWFLG1", 16500, 28500, "EDWF"),
           ("EPWW", "EPPO_TMA_N_A", 1600, 4500, "CL"),
           ("ESAA", "TECH ESMM IS", 99800, 99900, "ESIS")]
    db.execute(insert(Sector), [{"fir": f, "name": n, "lower_ft": lo, "upper_ft": up, "owners": o, "geometry": SQUARE}
                                for f, n, lo, up, o in sec])
    db.commit()


def test_slices_by_level(db):
    assert slices(level_ft=None, db=db)["note"]  # bez pliku .ese: pusta lista z wyjaśnieniem
    _fill(db)
    names = lambda lvl: [f["properties"]["name"] for f in slices(level_ft=lvl, db=db)["features"]]  # noqa: E731
    # TMA Warszawa nie sięga FL300; na FL300 tylko sektor ACC, na 5000 ft tylko dolna TMA
    assert names(30000) == ["EPWWC"] and names(5000) == ["EPWA_APP_N_A"] and names(20000) == ["EPWA_APP_S_A", "EDWWFLG1"]
    assert names(3000) == ["EPWA_APP_N_A", "EPPO_TMA_N_A"]
    allf = slices(level_ft=None, db=db)["features"]
    assert "TECH ESMM IS" not in [f["properties"]["name"] for f in allf]  # wycinków technicznych nie rysujemy
    tma = allf[0]["properties"]
    assert tma["kind"] == "tma" and tma["group"] == "EPWA" and tma["group_label"] == "TMA Warszawa"
    # lista OWNER z .ese jako znaki stanowisk: EPWA_APP online = TMA obsadzona przez APP
    assert tma["owner_callsigns"] == ["EPWA_N_APP", "EPWA_APP", "EPWW_C_CTR"] and tma["callsign"] == "EPWA_N_APP"
    assert next(f["properties"] for f in allf if f["properties"]["name"] == "EPPO_TMA_N_A")["group_label"] == "TMA Poznań N"
    nb = next(f["properties"] for f in allf if f["properties"]["fir"] == "EDWW")
    assert nb["kind"] == "nb" and nb["owner_callsigns"] == ["EDWW_FLG_CTR"]


def test_real_ese_tma_warszawa():
    """Plik sektorowy z repozytorium: wszystkie wycinki EPWA_APP_* i EPWA_DIR* to TMA Warszawa, każdy ma EPWA_APP
    (AWA) na liście OWNER i żaden nie sięga ponad FL245."""
    path = DATA_DIR / "import" / "EPWW-Sector.ese"
    if not path.exists():
        pytest.skip("brak pliku .ese")
    data = parse_ese(read_text(path))
    wa = [s for s in data["sectors"] if s["name"].startswith(("EPWA_APP_", "EPWA_DIR"))]
    assert len(wa) > 10
    for s in wa:
        assert slice_kind(s["fir"], s["name"]) == ("tma", "EPWA")
        assert "AWA" in s["owners"].split(":") and s["upper_ft"] <= 24500
    kinds = {slice_kind(s["fir"], s["name"]) for s in data["sectors"]}
    assert ("oth", "EPWW") not in kinds and not any(k and k[0] == "oth" for k in kinds)
