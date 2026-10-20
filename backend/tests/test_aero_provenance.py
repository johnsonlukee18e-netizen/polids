"""AERODROME bez notek o pochodzeniu danych w tekstach widocznych dla użytkownika (0.12.6): dymki LVP, powody wyboru
pasa, AWOS, DMAN / AMAN, lista lotnisk i karta lotniska. Dane, jednostki, ważność i krótkie wskazówki zostają."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from backend.app.config import settings
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


def test_lvp_without_source_and_neutral_notes():
    cfg = json.loads((settings.seed_dir / "lvp.json").read_text("utf-8"))
    for icao in [k for k in cfg if not k.startswith("_")]:
        e = lvp.evaluate(None, icao)
        assert "source" not in e, icao
        for text in [e["reason"] or "", e["note"] or "", *e.get("rules", [])]:
            assert not re.search(r"\bAIP\b|\bAMDT\b|\bpara\b|taken as|reconstructed", text), (icao, text)
        if not e["applies"]:
            assert e["reason"] == "No LVP at this aerodrome"
    # uwagi operacyjne zostają, o odczytaniu AIP nie
    assert lvp.evaluate(None, "EPWA")["note"] == ("ILS CAT IIIA RWY 33, CAT II RWY 11, take-offs from RWY 29 or 15; "
                                                  "no take-offs with RVR < 125 m")
    assert lvp.evaluate(None, "EPMO")["note"] is None
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
