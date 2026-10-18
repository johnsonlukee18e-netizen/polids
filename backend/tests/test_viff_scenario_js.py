"""Runda 14 (przegląd, 0.12.5): wiersz scenariusza vIFF w MAP miał w dymku opis scenariusza z vIFF (wolny tekst po
polsku, np. "podział FIR północ / południe"). Dymek po angielsku z danych scenariusza (viffchart.js scnTip: id,
traffic volumes z opisem jak tvLabel, warunki jak scnCond), opisu z vIFF nie pokazujemy."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

JS = ROOT_DIR / "frontend" / "js"
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")

NODE_SCRIPT = r"""
const v = await import(process.argv[2]);
const nsfir = { id: "EP-NSFIR", active: false, description: "podział FIR północ / południe",
  tvs: [{ id: "EP-NFIR" }, { id: "EP-SFIR" }], positions: ["EPWW_N_CTR", "EPWW_S_CTR"], anypositions: [], nopositions: [],
  start: "0000", end: "2359", times: [], booked: false };
const full = { id: "EP-<X>", active: true, description: "opis", tvs: [{ id: "EP-BH" }, { id: "EP-WATMA" }, { id: "EP-ALLFIR2" }],
  positions: [], anypositions: ["EPWA_APP", "EPWA_W_APP"], nopositions: ["EPWW_CTR"], start: "0600", end: "1200",
  times: [{ from: "1800", to: "2000", date: "2026-10-18" }, { from: "0100", to: "0200", date: null }], booked: true };
const bare = { id: "EP-EMPTY", active: false, description: "", tvs: [], positions: [], anypositions: [], nopositions: [],
  start: null, end: null, times: [], booked: false };
console.log(JSON.stringify({
  tips: [nsfir, full, bare].map(v.scnTip),
  cond: [nsfir, full, bare].map((s) => v.scnCond(s)),
  condHtml: [nsfir, full, bare].map((s) => v.scnCond(s, { html: true })),
  // pola, których starszy backend nie podaje
  partial: v.scnTip({ id: "EP-OLD", tvs: [{ id: "EP-KTTMA" }] }),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    (d / "viffchart.mjs").write_text((JS / "viffchart.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "viffchart.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_scenario_tooltip_english_from_data(js):
    assert js["tips"] == [
        "Scenario EP-NSFIR: traffic volumes EP-NFIR (FIR north), EP-SFIR (FIR south) · when online: EPWW_N_CTR + EPWW_S_CTR",
        "Scenario EP-<X>: traffic volumes EP-BH (sector B upper), EP-WATMA (TMA EPWA), EP-ALLFIR2 (whole FIR 2) · "
        "when online: EPWA_APP or EPWA_W_APP · and offline: EPWW_CTR · bookings count too · time 0600–1200 · "
        "2026-10-18 time 1800–2000 · time 0100–0200",
        "Scenario EP-EMPTY: no traffic volumes · no conditions",
    ]
    assert js["partial"] == "Scenario EP-OLD: traffic volumes EP-KTTMA (TMA EPKT) · no conditions"
    # nigdy opis z vIFF i nigdy polskie litery
    for tip in js["tips"]:
        assert "podział" not in tip and "opis" not in tip and not POLISH.search(tip)


def test_scenario_conditions(js):
    # tekst warunków w dymku = tekst wiersza bez <b>
    assert [re.sub(r"</?b>", "", h) for h in js["condHtml"]] == [c.replace("<X>", "&lt;X&gt;") for c in js["cond"]]
    assert js["condHtml"][0] == "when online: <b>EPWW_N_CTR</b> + <b>EPWW_S_CTR</b>"
    assert "time <b>0600–1200</b>" in js["condHtml"][1] and "2026-10-18 time <b>1800–2000</b>" in js["condHtml"][1]
    assert js["cond"][2] == js["condHtml"][2] == "no conditions"


def test_map_row_uses_tooltip_not_description():
    src = (JS / "tabs" / "map.js").read_text("utf-8")
    assert "s.description" not in src and "description" not in src.split("const scnHtml")[1].split("\n")[0]
    assert 'const scnHtml = (s, byId) => `<div class="vs-scn ${s.active ? "on" : ""}" title="${esc(scnTip(s))}">' in src
    assert '<div class="vs-cond">${scnCond(s, { html: true })}</div>' in src
