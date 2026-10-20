"""AERODROME › OVERVIEW we froncie (frontend/js/overview.js): pas w użyciu i przełącznik MINE / ALL (0.12.6).

Czyste funkcje sprawdzamy w Node (overview.js bez METEO i checklisty, jak w test_home.py)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
OVERVIEW_JS = FRONTEND / "js" / "overview.js"
OVERVIEW_CSS = FRONTEND / "css" / "overview.css"

NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const ads = [
  { icao: "EPKK", covered_by: null }, { icao: "EPWA", covered_by: "EPWA_APP" },
  { icao: "EPGD", covered_by: "EPWW_N_CTR" }, { icao: "EPRZ", covered_by: null },
];
const d = { position: { callsign: "EPWW_ALL_CTR", kind: "ACC" }, airports: ["EPKK", "EPWA", "EPGD", "EPRZ"], aerodromes: ads,
  notams: [{ icao: "EPWA", id: "A1/26" }, { icao: "EPKK", id: "A2/26" }, { icao: "EPGD", id: "A3/26" }] };
const pick = (x) => ({ ads: x.aerodromes.map((a) => a.icao), notams: x.notams.map((n) => n.id), airports: x.airports, hidden: x.hidden });
const out = {
  scopeOf: ["mine", "all", "", null, "ALL", "x"].map(m.scopeOf),
  hasScope: [{ kind: "ACC" }, { kind: "APP" }, { kind: "TWR" }, null, { kind: null }].map(m.hasScope),
  mine: pick(m.scoped(d, "mine")),
  all: pick(m.scoped(d, "all")),
  bad: pick(m.scoped(d, undefined)),
  none: pick(m.scoped({ ...d, aerodromes: ads.map((a) => ({ ...a, covered_by: null })) }, "mine")),
  note: [m.hiddenNote(m.scoped(d, "mine").hidden), m.hiddenNote([])],
  empty: [
    m.emptyNote(0, [{ icao: "EPLL", by: "EPWA_APP" }, { icao: "EPWA", by: "EPWA_APP" }, { icao: "EPPO", by: "EPWW_DTC_CTR" }]),
    m.emptyNote(0, [{ icao: "EPWA", by: "EPWA_APP" }]),
    m.emptyNote(2, [{ icao: "EPWA", by: "EPWA_APP" }]),
    m.emptyNote(0, []),
  ],
  tipUp: [
    m.tipUp({ top: 100, bottom: 120 }, { top: 90, bottom: 500 }),
    m.tipUp({ top: 460, bottom: 480 }, { top: 90, bottom: 500 }),
    m.tipUp({ top: 270, bottom: 290 }, { top: 90, bottom: 500 }),
  ],
  rwy: {
    atis: m.runwayChip({ arr: "33", dep: "29", source: "ATIS", letter: "K" }, { callsign: "EPWA_ATIS" }),
    atisSame: m.runwayChip({ arr: "29", dep: "29", source: "ATIS", letter: "B" }),
    pref: m.runwayChip({ arr: "26", dep: "26", source: "SUGGESTED", letter: null, reason: "Largest headwind" }),
    prefSplit: m.runwayChip({ arr: "11", dep: "15", source: "SUGGESTED", reason: "ARR 11 <x>" }),
    none: [m.runwayChip(null), m.runwayChip({ arr: null, source: "SUGGESTED" })],
  },
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("ovjs")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "meteo.mjs").write_text("export const colorize = (x) => x; export const wxLines = (k, x) => x;\n", "utf-8")
    (d / "checklist.mjs").write_text("export const renderChecklist = () => {};\n", "utf-8")
    (d / "overview.mjs").write_text(OVERVIEW_JS.read_text("utf-8")
                                    .replace('"./api.js"', '"./api.mjs"').replace('"./tabs/meteo.js"', '"./meteo.mjs"')
                                    .replace('"./checklist.js"', '"./checklist.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "overview.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_scope_values(js):
    # domyślnie MINE; przełącznik tylko przy stanowisku ACC / APP
    assert js["scopeOf"] == ["mine", "all", "mine", "mine", "mine", "mine"]
    assert js["hasScope"] == [True, True, False, False, False]


def test_scoped_hides_covered_aerodromes(js):
    assert js["mine"] == {"ads": ["EPKK", "EPRZ"], "notams": ["A2/26"], "airports": ["EPKK", "EPRZ"],
                          "hidden": [{"icao": "EPWA", "by": "EPWA_APP"}, {"icao": "EPGD", "by": "EPWW_N_CTR"}]}
    assert js["all"]["ads"] == ["EPKK", "EPWA", "EPGD", "EPRZ"] and js["all"]["hidden"] == []
    assert js["all"]["notams"] == ["A1/26", "A2/26", "A3/26"]
    # nieznana wartość zakresu = MINE; bez innych kontrolerów MINE i ALL pokazują to samo
    assert js["bad"] == js["mine"]
    assert js["none"]["ads"] == js["all"]["ads"] and js["none"]["hidden"] == []
    assert js["note"] == [{"text": "2 hidden", "tip": "EPWA: EPWA_APP\nEPGD: EPWW_N_CTR"}, {"text": "", "tip": ""}]


def test_runway_chip(js):
    r = js["rwy"]
    # z ATIS: pełna ramka z literą ATIS; różne pasy zwięźle "33/29" (ARR, potem DEP, w kolorach ról), role w dymku
    assert 'class="ov-rwy atis"' in r["atis"] and '<i class="src">ATIS K</i>' in r["atis"]
    assert '<b><span class="arr">33</span>/<span class="dep">29</span></b>' in r["atis"]
    assert 'data-tip="Runway in use · ATIS K\nARR 33 · DEP 29\nEPWA_ATIS"' in r["atis"]
    assert "<b>29</b>" in r["atisSame"] and "ATIS B" in r["atisSame"] and "ARR/DEP 29" in r["atisSame"]
    assert "RWY" not in r["atisSame"] and 'class="arr"' not in r["atisSame"]
    # preferowany: ramka kreskowana (klasa pref), PREF i powód wyboru w dymku
    assert 'class="ov-rwy pref"' in r["pref"] and '<i class="src">PREF</i>' in r["pref"] and "<b>26</b>" in r["pref"]
    assert 'data-tip="Preferred runway\nARR/DEP 26\nLargest headwind"' in r["pref"]
    assert '<span class="arr">11</span>/<span class="dep">15</span>' in r["prefSplit"]
    assert "&lt;x&gt;" in r["prefSplit"] and "<x>" not in r["prefSplit"]
    assert r["none"] == ["", ""]


def test_empty_mine_and_tooltips(js):
    # MINE ukrył wszystkie lotniska: informacja zamiast pustych paneli, każdy obsługujący raz
    assert js["empty"][0] == "All 3 aerodromes of this position are covered now by EPWA_APP, EPWW_DTC_CTR. ALL shows them."
    assert js["empty"][1] == "EPWA is covered now by EPWA_APP. ALL shows it."
    assert js["empty"][2:] == ["", ""]
    # dymek w górę tylko w dolnej połowie przewijanego panelu
    assert js["tipUp"] == [False, True, False]


def _code(src):
    """Kod bez komentarzy (komentarze w projekcie są po polsku)."""
    out = []
    for line in src.splitlines():
        s = line.strip()
        if s.startswith(("//", "/*", "*")):
            continue
        out.append(re.split(r"\s//\s", line)[0])
    return "\n".join(out)


def test_overview_js_english_without_provenance():
    code = _code(OVERVIEW_JS.read_text("utf-8"))
    assert not re.search(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", code)
    # bez nazw źródeł danych w napisach (nagłówki kart, dymki, podpisy)
    for word in ("Airport Monitor vIFF", "vIFF arrivals", "ECFMP ·", "in vIFF", "VATSIM network", ">VATSIM<",
                 "data/seed", "source_url", "t.source"):
        assert word not in code, word
    for word in ("Airport monitor", "Flow restrictions", "Flow measures · FIR EPWW", "EP sector regulations", "MINE", "ALL"):
        assert word in code, word
    # przełącznik zapamiętany w tej przeglądarce (lsGet / lsSet), jak inne ustawienia PRZEGLĄDU
    assert 'const SCOPE_KEY = "overview.scope";' in code and "lsSet(SCOPE_KEY, scope)" in code


def test_overview_css_look():
    css = re.sub(r"/\*.*?\*/", "", OVERVIEW_CSS.read_text("utf-8"), flags=re.S)
    assert all(r.strip() == "0" for r in re.findall(r"border-radius:\s*([^;}]+)", css))
    assert "text-shadow" not in css and "box-shadow" not in css and "glow" not in css
    assert ".ov-rwy.pref" in css and "dashed" in css[css.index(".ov-rwy.pref"):][:120]
    # pasek PRZEGLĄDU w jednej linii (skraca się opis stanowiska), dymki w dolnej połowie panelu METAR w górę
    assert ".ov > .toolbar.ov-bar { margin: 0 0 6px; flex-wrap: nowrap; }" in css
    assert ".ov-wx-body [data-tip].tip-up:hover::after { top: auto; bottom: 100%; }" in css
    assert "@container (max-width: 480px)" in css
    # nazwy klas, których blokery reklam nie ukrywają
    assert not re.search(r"\.(?:[\w-]*ad-|ads?\b|advert|banner|sponsor|promo)", css.replace(".ov-", ""))
