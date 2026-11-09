"""0.13.2 (issue #27): VMC / IMC w CTR lotniska z METAR (metar.ctr_conditions), jedna reguła dla AWOS i wyboru pasa,
pole VMC w AWOS bez własnej reguły (awos.js, Node), najnowszy METAR lotniska ze wszystkich zapytań (weather.newest)
i napis "()" przycisku OVERVIEW w AERODROME."""
import asyncio
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from backend.app.config import ROOT_DIR, settings
from backend.app.services import weather
from backend.app.services.metar import ctr_conditions, parse_metar

JS = ROOT_DIR / "frontend" / "js"


@pytest.mark.parametrize("body, state", [
    # zgłoszenie z issue #27: BKN009 przy widzialności 10 km to IMC (ceiling 900 ft < 1500 ft)
    ("9999 BKN009 08/06 Q1012 NOSIG", "IMC"),
    ("9999 OVC014 08/06 Q1012", "IMC"),             # MVFR, ale poniżej 1500 ft
    ("9999 BKN015 08/06 Q1012", "VMC"),             # dokładnie 1500 ft
    ("9999 SCT009 BKN040 08/06 Q1012", "VMC"),      # SCT to nie ceiling
    ("9999 FEW005 08/06 Q1012", "VMC"),
    ("9999 SCT008CB BKN020 08/06 Q1012", "VMC"),    # CB / TCU nie zmieniają reguły
    ("9999 BKN009TCU 08/06 Q1012", "IMC"),
    ("0200 FG VV002 03/03 Q1020", "IMC"),
    ("0100 FG VV/// 03/03 Q1020", "IMC"),
    ("9999 VV/// 03/03 Q1020", "IMC"),              # zakryte niebo bez wartości: nie da się mieć VMC
    ("4000 BR SCT030 08/06 Q1012", "IMC"),          # widzialność < 5 km
    ("4999 SCT030 08/06 Q1012", "IMC"),
    ("5000 SCT030 08/06 Q1012", "VMC"),
    ("CAVOK 08/06 Q1012", "VMC"),
    ("9999 NSC 08/06 Q1012", "VMC"),
    ("9999 NCD 08/06 Q1012", "VMC"),
    ("R33/0400N FG VV001 03/03 Q1020", "IMC"),      # tylko RVR, bez widzialności (dotąd w AWOS kreska)
    ("R33/0400N FG 03/03 Q1020", "IMC"),
    ("BKN009 08/06 Q1012", "IMC"),                  # brak widzialności, ale ceiling rozstrzyga
    ("BKN020 08/06 Q1012", None),                   # brak widzialności: VMC nie do potwierdzenia (dotąd VMC)
    ("9999 08/06 Q1012", None),                     # brak informacji o chmurach (dotąd VMC)
    ("9999 SCT020 BKN025 08/06 Q1012 TEMPO BKN009", "VMC"),   # tendencja nie zmienia stanu obserwacji
    ("9999 BKN009 08/06 Q1012 BECMG SCT030", "IMC"),
])
def test_ctr_conditions(body, state):
    m = parse_metar(f"EPWA 091200Z 24008KT {body}")
    assert m.vmc == state, (body, m.vmc_reason)
    assert m.vmc_reason and (m.vmc, m.vmc_reason) == ctr_conditions(m)


@pytest.mark.parametrize("raw, state", [
    ("EPLL 091130Z AUTO 24008KT 9999 ////// 08/06 Q1012", None),       # stacja AUTO: chmur nie zaobserwowano
    ("EPLL 091130Z AUTO 24008KT 9999 //////CB 08/06 Q1012", None),
    ("EPLL 091130Z AUTO 24008KT 9999 ///012 08/06 Q1012", None),       # warstwa nieznanej ilości poniżej 1500 ft
    ("EPLL 091130Z AUTO 24008KT 9999 ///045 08/06 Q1012", "VMC"),
    ("EPLL 091130Z AUTO 24008KT 9999 BKN/// 08/06 Q1012", None),       # BKN bez podstawy
    ("EPLL 091130Z AUTO 24008KT 9999 BKN009/// 08/06 Q1012", "IMC"),
    ("EPLL 091130Z AUTO 24008KT 3000 BR ////// 08/06 Q1012", "IMC"),   # widzialność rozstrzyga mimo braku chmur
    ("EPLL 091130Z AUTO 24008KT //// BKN030 08/06 Q1012", None),       # widzialność ////
    ("EPLL 091130Z AUTO 24008KT 9999NDV NCD 08/06 Q1012", "VMC"),
    ("METAR COR EPWA 091200Z 24008KT 9999 BKN009 08/06 Q1012", "IMC"),
    ("SPECI EPWA 091210Z 24008KT 9999 BKN009 08/06 Q1012", "IMC"),
    ("EPWA 091200Z COR 24008KT 9999 BKN009 08/06 Q1012", "IMC"),
])
def test_ctr_conditions_auto_and_prefixes(raw, state):
    assert parse_metar(raw).vmc == state, raw


def test_ctr_conditions_reasons_and_fields():
    m = parse_metar("EPWA 091200Z 24008KT 9999 BKN009 08/06 Q1012 NOSIG")
    assert (m.ceiling_ft, m.flight_category, m.vmc, m.vmc_reason) == (900, "IFR", "IMC", "ceiling 900 ft < 1500 ft")
    assert parse_metar("EPWA 091200Z 24008KT 3000 BR OVC004 08/06 Q1012").vmc_reason == \
        "visibility 3000 m < 5000 m; ceiling 400 ft < 1500 ft"
    assert parse_metar("EPWA 091200Z 24008KT 9999 SCT020 BKN040 08/06 Q1012").vmc_reason == \
        "visibility 10 km or more, ceiling 4000 ft"
    assert parse_metar("EPWA 091200Z 24008KT 8000 FEW020 08/06 Q1012").vmc_reason == "visibility 8000 m, no ceiling"
    assert parse_metar("EPWA 091200Z 24008KT CAVOK 08/06 Q1012").vmc_reason == "CAVOK"
    assert parse_metar("EPWA 091200Z 24008KT BKN020 08/06 Q1012").vmc_reason == "visibility not reported"
    assert parse_metar("EPLL 091130Z AUTO 24008KT 9999 ////// 08/06 Q1012").vmc_reason == "cloud amount not reported"
    # NSC / NCD zapamiętane (AERODROME i AWOS pokazują je zamiast stałego "NSC"), ////// jako warstwa nieznanej ilości
    assert parse_metar("EPLL 091130Z AUTO 24008KT 9999 NCD 08/06 Q1012").sky == "NCD"
    assert parse_metar("EPLL 091130Z AUTO 24008KT 9999 ////// 08/06 Q1012").clouds == [
        {"cover": "///", "base_ft": None, "type": None}]
    d = parse_metar("EPWA 091200Z 24008KT 9999 BKN009 08/06 Q1012").to_dict()
    assert d["vmc"] == "IMC" and d["vmc_reason"] == "ceiling 900 ft < 1500 ft" and d["sky"] is None


def test_runway_choice_uses_ctr_imc():
    """Wybór pasa: "IMC conditions" przy tym samym stanie co pole IMC w AWOS (ceiling 1000–1400 ft też), nie tylko przy
    kategorii IFR / LIFR jak do 0.13.1."""
    from types import SimpleNamespace

    from backend.app.services.runways import runway_state
    rw = [SimpleNamespace(designator=d, heading_true=h, preferred=False, length_m=2550, width_m=60, surface="ASPH")
          for d, h in (("07", 78.0), ("25", 258.0))]
    ad = SimpleNamespace(icao="EPKK", runways=rw)
    for cloud, imc in (("BKN009", True), ("OVC012", True), ("BKN015", False), ("SCT009", False)):
        m = parse_metar(f"EPKK 091200Z 07004KT 9999 {cloud} 08/06 Q1012")
        reason = runway_state(ad, m, {"state": None})["preferred"]["reason"]
        assert reason.startswith("IMC conditions") is imc, (cloud, reason)


# --- weather.newest: jeden (najnowszy) METAR lotniska w całej aplikacji ------------------------------------------

def test_newest_metar_wins_across_requests(monkeypatch):
    """OVERVIEW / METEO (wiele lotnisk) mają już METAR 12:00 z BKN009, AWOS (jedno lotnisko, osobny adres i osobna
    pamięć podręczna) dostaje jeszcze 11:30: oddajemy 12:00, więc AWOS nie pokazuje VMC ze starszego METAR."""
    old = "EPWA 091130Z 24008KT 9999 SCT020 08/06 Q1012 NOSIG"
    new = "EPWA 091200Z 24008KT 9999 BKN009 08/06 Q1012 NOSIG"
    replies = {"EPWA,EPKK": f"{new}\nEPKK 091200Z 24008KT CAVOK 08/06 Q1012", "EPWA": old, "EPGD": ""}

    async def fetch(url, ttl, params=None, headers=None):
        return replies[url.rsplit("/", 1)[1]]

    monkeypatch.setattr(settings, "metar_source", "vatsim")
    monkeypatch.setattr(weather, "fetch_text", fetch)

    def run(ids):
        return asyncio.run(weather.get_metars(ids))
    assert run(["EPWA"]) == {"EPWA": old}                    # nic nowszego jeszcze nie ma
    assert run(["EPWA", "EPKK"])["EPWA"] == new
    assert run(["EPWA"]) == {"EPWA": new} and parse_metar(run(["EPWA"])["EPWA"]).vmc == "IMC"
    assert run(["EPGD"]) == {}                               # lotnisko bez METAR w odpowiedzi zostaje bez METAR
    # ten sam czas obserwacji (np. poprawka COR): wygrywa świeża odpowiedź
    replies["EPWA"] = cor = "EPWA 091200Z COR 24008KT 9999 BKN008 08/06 Q1012 NOSIG"
    assert run(["EPWA"]) == {"EPWA": cor}


def test_newest_metar_awc_source_and_reset(monkeypatch):
    rows = {"a": [{"icaoId": "EPKK", "rawOb": "EPKK 091200Z 24008KT 9999 BKN009 08/06 Q1012"}],
            "b": [{"icaoId": "EPKK", "rawOb": "EPKK 091130Z 24008KT CAVOK 08/06 Q1012"}]}
    which = {"k": "a"}

    async def fetch(url, ttl, params=None, headers=None):
        return json.dumps(rows[which["k"]])

    monkeypatch.setattr(settings, "metar_source", "awc")
    monkeypatch.setattr(weather, "fetch_text", fetch)
    assert asyncio.run(weather.get_metars(["EPKK"]))["EPKK"].startswith("EPKK 091200Z")
    which["k"] = "b"
    assert asyncio.run(weather.get_metars(["EPKK"]))["EPKK"].startswith("EPKK 091200Z")
    weather.reset_newest()
    assert asyncio.run(weather.get_metars(["EPKK"]))["EPKK"].startswith("EPKK 091130Z")


def test_newest_metar_month_change_and_pruning():
    now = datetime(2026, 11, 1, 0, 10, tzinfo=timezone.utc)
    # 31.10 23:30 i 01.11 00:00: późniejsza obserwacja z nowego miesiąca wygrywa
    weather.newest({"EPWA": "EPWA 010000Z 24008KT 9999 BKN009 08/06 Q1012"}, now)
    assert weather.newest({"EPWA": "EPWA 312330Z 24008KT CAVOK 08/06 Q1012"}, now)["EPWA"].startswith("EPWA 010000Z")
    # METAR bez czasu obserwacji zostaje bez zmian i nie trafia do pamięci
    assert weather.newest({"EPKK": "EPKK NIL"}, now) == {"EPKK": "EPKK NIL"} and "EPKK" not in weather._newest
    weather.reset_newest()
    for i in range(weather.NEWEST_MAX + 1):
        weather.newest({f"X{i:03d}": "X 300000Z 24008KT CAVOK 08/06 Q1012"}, now)    # sprzed 2 dni
    assert len(weather._newest) == 0


# --- AWOS: pole VMC / IMC tylko ze stanu z serwera (Node) --------------------------------------------------------

NODE_SCRIPT = r"""
const { awosSim: m } = await import(process.argv[2]);
const p = (o) => ({ clouds: [], cavok: false, sky: null, trend: null, flight_category: null, ...o });
console.log(JSON.stringify({
  imc: m.vmcBox(p({ vmc: "IMC", vmc_reason: "ceiling 900 ft < 1500 ft", flight_category: "IFR", trend: "NOSIG" })),
  vmc: m.vmcBox(p({ vmc: "VMC", vmc_reason: "visibility 10 km or more, ceiling 2500 ft", flight_category: "MVFR",
    trend: "TEMPO BKN009" })),
  unknown: m.vmcBox(p({ vmc: null, vmc_reason: "visibility not reported", flight_category: "MVFR" })),
  // bez pola vmc (np. stary serwer): kreska, nie własna reguła z kategorii lotu
  legacy: m.vmcBox(p({ flight_category: "VFR", visibility_m: 9999, ceiling_ft: 900 })),
  none: m.vmcBox(null),
  clouds: [m.cloudList(p({ sky: "NCD" })), m.cloudList(p({ cavok: true })), m.cloudList(p({})),
    m.cloudList(p({ clouds: [{ cover: "VV", base_ft: null, type: null }] })),
    m.cloudList(p({ clouds: [{ cover: "///", base_ft: null, type: "CB" }, { cover: "BKN", base_ft: 900, type: null }] }))],
}));
"""


@pytest.fixture(scope="module")
def awos_box(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("vmc")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    (d / "meteo.mjs").write_text("export const colorize = (x) => x; export const wxLines = (k, x) => x;\n", "utf-8")
    src = (JS / "awos.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"')
    src = src.replace('"./tabs/meteo.js"', '"./meteo.mjs"')
    (d / "awos.mjs").write_text(src, "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "awos.mjs").as_uri()], capture_output=True, text=True,
                       timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_awos_box_from_server_state(awos_box):
    imc = awos_box["imc"]
    assert (imc["text"], imc["cls"], imc["cat"]) == ("IMC", "imc", "IFR")
    assert imc["tip"].split("\n") == ["IMC: ceiling 900 ft < 1500 ft",
                                      "VMC in the CTR: visibility ≥ 5 km and cloud ceiling ≥ 1500 ft",
                                      "Flight category: IFR"]
    vmc = awos_box["vmc"]
    assert (vmc["text"], vmc["cls"], vmc["cat"]) == ("VMC", "vmc", "MVFR")
    assert "Trend (not included): TEMPO BKN009" in vmc["tip"].split("\n")
    for k in ("unknown", "legacy", "none"):
        assert (awos_box[k]["text"], awos_box[k]["cls"]) == ("–", ""), k
    assert awos_box["unknown"]["tip"].startswith("VMC / IMC unknown: visibility not reported")
    assert awos_box["none"]["tip"].startswith("VMC / IMC unknown: no METAR") and awos_box["none"]["cat"] == ""
    assert awos_box["clouds"] == [["NCD"], ["CAVOK"], ["–"], ["VV /// FT"], ["////// CB", "BKN 900 FT"]]


def test_awos_has_no_own_vmc_rule():
    src = (JS / "awos.js").read_text("utf-8")
    body = re.search(r"function vmcBox\(p\) \{.*?\n\}", src, re.DOTALL).group(0)
    # progi tylko w tekście dymku, bez porównań z widzialnością, podstawą chmur ani kategorią lotu
    assert not re.search(r"visibility_m|ceiling_ft|IFR|LIFR|[<>]=?\s*\d", body)
    assert "function vmc(" not in src and "vmcBox(p)" in src
    assert all(ln.lstrip().startswith("//") or ln.isascii() for ln in body.splitlines())


# --- AERODROME: przycisk OVERVIEW "()" -----------------------------------------------------------------------------

def test_overview_button_label():
    src = (JS / "tabs" / "aerodrome.js").read_text("utf-8")
    assert '<button data-fir="0" title="OVERVIEW: whole FIR EPWW">()</button>' in src
    assert '">0</button>' not in src
    # identyfikator i adres bez zmian: #aerodrome/0, kliknięcie przycisku i zapisany ostatni ekran
    assert 'goto(b.dataset.fir === "0" ? "0" : "fir/" + b.dataset.fir' in src
    assert 'if (a === "0") showOverview();' in src
