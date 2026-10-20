"""AERODROME bez notek o pochodzeniu danych w tekstach widocznych dla użytkownika (0.12.6): dymki LVP, powody wyboru
pasa, AWOS, DMAN / AMAN, lista lotnisk i karta lotniska. Dane, jednostki, ważność i krótkie wskazówki zostają."""

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from backend.app.config import settings
from backend.app.database import SCHEMA_VERSION
from backend.app.services import lvp
from backend.app.services.metar import parse_metar
from backend.app.services.runways import runway_config, select_runways

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "js"
FILES = ["overview.js", "tabs/aerodrome.js", "aerolist.js", "awos.js", "dman.js", "aman.js", "dmancore.js"]
WORDS = r"VATSIM|vIFF\)|from vIFF|in vIFF|ECFMP|\bAIP\b|eAIP|navdata|OurAirports|Open-Meteo|\.ese\b|PolIDS data|data/seed|" \
        r"[Ss]ource:|per AIP|from METAR|based on|SERA\.5005"


def _code(src: str) -> str:
    """Kod bez komentarzy (komentarze w projekcie są po polsku i mogą mówić o źródłach)."""
    out = []
    for line in src.splitlines():
        if line.strip().startswith(("//", "/*", "*")):
            continue
        out.append(re.split(r"\s//\s", line)[0])
    return "\n".join(out)


def test_frontend_texts_without_provenance():
    for name in FILES:
        code = _code((FRONTEND / name).read_text("utf-8"))
        # identyfikatory i klucze danych (eldt_source === "vIFF", s.viff) to nie tekst widoczny
        code = re.sub(r'"vIFF"|\bviff\w*|\bvIFF:|\.vIFF\b', "", code)
        hits = [m.group(0) for m in re.finditer(WORDS, code)]
        assert not hits, (name, hits)


def test_neutral_messages():
    awos = _code((FRONTEND / "awos.js").read_text("utf-8"))
    assert '"No ATIS online now."' in awos and "VATSIM has no wind" not in awos
    assert 'const SYM = "simulated instantaneous wind";' in awos and "<b>SYM</b> simulated" in awos
    for name in ("dman.js", "aman.js"):
        assert '"Network data unavailable"' in (FRONTEND / name).read_text("utf-8"), name
    # wiatr w punktach podejścia (INFO): błędy prognozy i METAR bez treści z serwera (tam bywa nazwa dostawcy)
    aero = _code((FRONTEND / "tabs/aerodrome.js").read_text("utf-8"))
    assert 'aw.model_error && "Forecast unavailable"' in aero and 'aw.metar_error && "METAR unavailable"' in aero
    assert "[aw.model_error, aw.metar_error]" not in aero


def test_lvp_without_source_and_neutral_notes():
    cfg = json.loads((settings.seed_dir / "lvp.json").read_text("utf-8"))
    for icao in [k for k in cfg if not k.startswith("_")]:
        e = lvp.evaluate(None, icao)
        assert "source" not in e, icao
        for text in [e["reason"] or "", e["note"] or "", *e.get("rules", [])]:
            assert not re.search(r"\bAIP\b|\bAMDT\b|\bpara\b|taken as|reconstructed", text), (icao, text)
        if not e["applies"]:
            assert e["reason"].startswith("No LVP at this aerodrome"), icao
    # dopisek operacyjny w nawiasie zostaje, nawias o pochodzeniu nie
    assert lvp.evaluate(None, "EPOK")["reason"] == "No LVP at this aerodrome (only IFR helicopter take-off minima from a taxiway)"
    assert lvp.evaluate(None, "EPRA")["reason"] == lvp.evaluate(None, "EPZG")["reason"] == "No LVP at this aerodrome"
    # uwagi operacyjne zostają (także warunki stojące obok odczytania AIP), o odczytaniu AIP nie
    assert lvp.evaluate(None, "EPWA")["note"] == ("cancellation with a trend to further improvement; ILS CAT IIIA RWY 33, "
                                                  "CAT II RWY 11, take-offs from RWY 29 or 15; no take-offs with RVR < 125 m")
    assert lvp.evaluate(None, "EPMO")["note"] == lvp.evaluate(None, "EPGD")["note"] == \
        "cancellation with further improvement expected"
    assert lvp.evaluate(None, "EPPO")["note"].startswith("preparation also on a decreasing RVR trend, TAF forecast or "
                                                         "aerodrome warning")
    assert "cancellation with a sustained improving trend" in lvp.evaluate(None, "EPPO")["note"]
    assert lvp.evaluate(None, "EPSY")["note"] is None and lvp.evaluate(None, "EPWR")["note"] is None
    assert lvp.rules(lvp.thresholds("EPKK"))[0] == "Preparation: none"
    # brak wartości w METAR: "not reported", bez nazwy źródła
    m = parse_metar("EPKT 140700Z 26004KT 0400 FG 08/08 Q1012")
    e = lvp.evaluate(m, "EPKT", now=datetime(2026, 10, 14, 7, 2, tzinfo=UTC))
    assert not any("METAR" in r for r in e["reasons"])


def test_runway_reasons_without_aip():
    rwys = [{"designator": "11", "heading": 110}, {"designator": "29", "heading": 290},
            {"designator": "15", "heading": 150}, {"designator": "33", "heading": 330}]
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    cfg = runway_config("EPWA")
    for metar in ("EPWA 141200Z 31008KT 9999 FEW030 10/05 Q1012", "EPWA 141200Z 11008KT 0300 R33/0350N FG VV001 08/08 Q1012",
                  "EPWA 141200Z 29004KT 9999 TSRA BKN030CB 18/12 Q1012"):
        p = parse_metar(metar)
        for low in (None, "LVP"):
            r = select_runways(rwys, p.wind_dir, p.wind_speed, config=cfg, metar=p, now=now, low_vis=low,
                               equipment={"33": ["ILS"], "11": ["ILS"]})
            assert "AIP" not in r["reason"], (metar, low, r["reason"])


def test_dman_aman_tooltips_without_formulas():
    """Issue #21: dymki DMAN / AMAN mówią, co to za wartość i jak pewna (CDM, POS, szacunek), bez wzorów i bez tego,
    skąd ją wzięto (odległość po ortodromie, ETOT = off-block + kołowanie, STA = max(...), punkty trasy)."""
    dm = (FRONTEND / "dman.js").read_text("utf-8")
    am = (FRONTEND / "aman.js").read_text("utf-8")
    code = "\n".join(_code((FRONTEND / n).read_text("utf-8")) for n in ("dman.js", "aman.js", "dmancore.js"))
    for word in ("great-circle", "STA = max", "= off-block", "+ taxi time", "ETOT = ", "FLOW/140", "FLOW / 140", "APPROACH_KT}",
                 "TTOT − TSAT", "STA − ETA", "from position", "route point", "first STAR point", "approximation",
                 "10 min assumed", "Default taxi time", "ACC window", "(A-CDM)\"", "system suggestion", "no ATIS",
                 "from ATIS"):
        assert word not in code, word
    # znaczniki CDM / POS i szacunek (est) zostają
    assert 'vIFF: "CDM", POS: "estimate"' in dm and '"ETA (estimate)"' in dm and '" est"' in dm
    assert '"Landing time in the AMAN sequence"' in dm and '"Time the aircraft has to lose"' in dm
    assert "`Estimated take-off time${" in dm and 'R("DIST", s.dist_nm !== null && s.dist_nm !== undefined ? `${s.dist_nm} NM` : "")' in dm
    assert 'title="Preferred runway">PREF</div>' in dm
    assert 'const SEQ_HINT = "Arrival sequence by STA. FLOW = spacing between landings in NM; click FLOW to change it. "' in am
    assert '"Preferred landing runway"' in am and 'eldt_source === "vIFF" ? "CDM" : "estimate"' in am


def test_runway_in_use_wording_like_overview():
    """Pas w użyciu wszędzie jak w OVERVIEW: z ATIS litera ATIS ("ATIS K"), bez niego pas preferowany ("PREF",
    "preferred runway"); bez "system suggestion" i "no runway from ATIS"."""
    for name in ("strips.js", "dman.js", "aman.js", "awos.js", "tabs/meteo.js", "tabs/aerodrome.js", "overview.js"):
        code = _code((FRONTEND / name).read_text("utf-8"))
        for word in ("system suggestion", "suggested, no ATIS", "suggestion, no ATIS", "from ATIS", ">suggested<"):
            assert word not in code, (name, word)
    awos = (FRONTEND / "awos.js").read_text("utf-8")
    assert '`ATIS ${st.atis?.letter || ""}`.trim() : "PREF"' in awos
    met = (FRONTEND / "tabs/meteo.js").read_text("utf-8")
    assert '"ARR?/DEP?: preferred runway."' in met and "letter: x.atis?.letter" in met
    aero = (FRONTEND / "tabs/aerodrome.js").read_text("utf-8")
    assert "ARR? / DEP? = preferred runway" in aero and '<i class="sw-hatch"></i>preferred</span>' in aero


def test_frequency_hours_and_notes_without_aip_tags():
    """AERODROME › INFO: godziny i uwagi częstotliwości bez odnośników do rozdziałów AIP (czasy i warunki zostają);
    SCHEMA_VERSION 11 przebudowuje starą bazę, bo częstotliwości wczytuje się tylko do pustej tabeli."""
    with (settings.seed_dir / "frequencies.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    tag = re.compile(r"\((?:AD|ENR|GEN) \d|\b(?:AD|ENR|GEN) \d+(?:\.\d+)+|\bAIP\b|\bAMDT\b")
    for r in rows:
        for k in ("hours", "note"):
            assert not tag.search(r[k] or ""), (r["airport_ident"], r["service"], r[k])
    by = {(r["airport_ident"], r["service"], r["frequency_mhz"]): r for r in rows}
    assert by[("EPRZ", "APP", "133.030")]["hours"] == "only when CTA09 is delegated"
    assert by[("EPKK", "DEL", "121.980")]["hours"] == "H24 1000-2100 (0900-2000); peak 0600-2200 (0500-2100)"
    assert by[("EPPT", "RADIO", "119.305")]["hours"].startswith("H24; AD: TUE-SUN 0700-1500 (0600-1400)")
    assert by[("EPRJ", "TWR", "126.805")]["note"].endswith("flights from EPRJ subject to RZESZÓW TWR approval")
    assert SCHEMA_VERSION >= 11
