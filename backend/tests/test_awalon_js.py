"""AWALON (0.13.0, issue #23) w przeglądarce: wspólne funkcje wiatru w frontend/js/wind.js (przeniesione z METEO ›
WIND i nowe: klasy prędkości, osie, groty, macierz ALL) i czyste funkcje tabs/awalon.js (model wykresu, panel pasów),
uruchamiane w Node; do tego kod zakładki: menu, podmenu, napisy po angielsku, bez nazw dostawców i bez pogrubień."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR
from backend.app.services.eaip import AD2_AERODROMES

FRONTEND = ROOT_DIR / "frontend"
WIND = (FRONTEND / "js" / "wind.js").read_text("utf-8")
AWALON = (FRONTEND / "js" / "tabs" / "awalon.js").read_text("utf-8")
CSS = (FRONTEND / "css" / "awalon.css").read_text("utf-8")
WIND_CSS = (FRONTEND / "css" / "wind.css").read_text("utf-8")
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")

NODE_SCRIPT = r"""
const w = await import(process.argv[2]);
const a = await import(process.argv[3]);
const row = (alt, kind, status, dir, speed, extra = {}) => ({ alt_ft: alt, kind, status, dir, speed, gust: null, variable: false, ...extra });
const prof = [row(0, "sfc", "METAR", 310, 14, { gust: 26 }), row(1000, "gnd", "GND", null, null), row(2000, "air", "FCST", 270, 20),
              row(3000, "air", "FCST", 90, 47), row(4000, "air", "N/A", null, null), row(5000, "sfc", "METAR", null, 2, { variable: true })];
const data = { alts_ft: [0, 1000, 2000], aerodromes: [
  { icao: "EPKT", profile: [row(0, "sfc", "METAR", 300, 10), row(1000, "gnd", "GND", null, null), row(2000, "air", "FCST", 304, 22)] },
  { icao: "EPWA", profile: [row(0, "sfc", "METAR", 310, 14), row(1000, "air", "FCST", 294, 15)] }] };
const m = a.chartModel(prof);
const aw = { runways: [
  { designator: "29", fix: "WA728", method: "procedure", method_label: "FAF", dist_nm: 7, path_ft: 2590, approaches: ["RNP"],
    c_metar: { hw: 13.6, xw: -4.2 }, c_model: { hw: 9, xw: 1 }, w3000: { dir: 306, speed: 22 }, c3000: { hw: 21.7, xw: 4.4 } },
  { designator: "11", fix: null, method: "centreline", method_label: "extended centreline, 3°", dist_nm: 8.1, path_ft: 2940,
    c_metar: { hw: -13.6, xw: 4.2 }, c_model: { hw: null, xw: null }, w3000: null, c3000: { hw: null, xw: null } }],
  metar_wind: { dir: 310, speed: 14, gust: 26 }, model_surface: { dir: 289, speed: 9, gust: 18 }, valid: "2026-10-28T16:00Z",
  fetched: "16:25Z", model_error: null, metar_error: "METAR unavailable: no connection" };
console.log(JSON.stringify({
  bands: w.SPEED_BANDS.map((b) => b.label), noData: w.NO_DATA.label,
  bandOf: [0, 9.9, 10, 14.9, 15, 19, 20, 29, 30, 39, 40, 59, 60, 60.5, 61, 120, null, undefined, "x"].map(w.bandOf),
  axisMax: [0, 23, 40, 41, 47, 60, 61, null].map(w.axisMax),
  ticks: [w.axisTicks(40), w.axisTicks(50), w.axisTicks(60)],
  alt: [0, 1000, 5000, 10000].map(w.altLabel), rowl: [0, 1000, 10000].map(w.rowLabel),
  rot: [w.arrowRot(270, 20), w.arrowRot(360, 5), w.arrowRot(90, 5), w.arrowRot(180, 5), w.arrowRot(45, 5), w.arrowRot(null, 5),
        w.arrowRot(0, 0), w.arrowRot(310, 0)],
  tip: [w.windTip(prof[0]), w.windTip(prof[2]), w.windTip(prof[5]), w.windTip(prof[1]), w.windTip(null), w.windTip(row(0, "sfc", "METAR", 0, 0))],
  dir: [w.dirTxt(prof[0]), w.dirTxt(prof[5]), w.dirTxt(prof[1]), w.dirTxt(row(0, "sfc", "METAR", 0, 0)), w.dirTxt(row(0, "air", "FCST", 5, 3))],
  angle: [w.angleTxt(5), w.angleTxt(340), w.angleTxt(null)], speed: [w.speedTxt(0), w.speedTxt(14), w.speedTxt(null)],
  matrix: w.matrixRows(data).map((r) => [r.alt_ft, r.cells.map((c) => (c ? `${c.status}:${c.dir}/${c.speed}` : null))]),
  matrixEmpty: w.matrixRows(null),
  maxSpeed: [w.maxSpeed(prof), w.maxSpeed([]), w.maxSpeed(null)],
  forecastFor: [w.forecastFor("2026-10-28T16:00Z", Date.UTC(2026, 9, 28, 16, 25)), w.forecastFor("2026-10-27T23:00Z", Date.UTC(2026, 9, 28, 0, 10)),
                w.forecastFor(null)],
  // przeniesione z METEO › WIND (te same oczekiwania co wcześniej w test_meteo_img.py)
  vec: [w.windVec({ dir: 310, speed: 14, gust: 26 }), w.windVec({ dir: 5, speed: 3 }), w.windVec({ variable: true, dir: null, speed: 2 }),
        w.windVec({ dir: 300, speed: null }), w.windVec(null)],
  hw: [w.hwTxt(13.5), w.hwTxt(-13.5), w.hwTxt(-0.4), w.hwTxt(null)], xw: [w.xwTxt(4.6), w.xwTxt(-4.6), w.xwTxt(0.3), w.xwTxt(undefined)],
  kt: [w.kt(-13.5), w.kt(13.4)], valid: [w.validTxt("2026-10-06T18:00Z"), w.validTxt(null)],
  note: [w.forecastNote({ valid: "2026-10-12T12:00Z", fetched: "12:04Z" }),
         w.forecastNote({ valid: null, model_error: "Wind forecast unavailable: no connection" }),
         w.forecastNote({ valid: null }), w.forecastNote(null)],
  pointTip: w.pointTip({ designator: "29", fix: "WA728", method_label: "FAF", dist_nm: 7, path_ft: 2590,
                         approaches: ["RNP"], rejected: ["XX702: 2.30 NM from THR (< 2.5 NM)"] }),
  cl3: w.CL3, nm: [w.nm(3), w.nm(null)],
  // tabs/awalon.js
  ads: a.AWALON_AD, refresh: a.REFRESH, chart: a.CHART,
  model: { max: m.max, ticks: m.ticks, alts: m.alts, bands: m.bands },
  big: a.chartModel([row(0, "sfc", "FCST", 250, 63)]).max, empty: a.chartModel([]).max,
  y: [a.yOf(10500), a.yOf(-500), a.yOf(0), a.yOf(10000)], x: [a.xOf(0, 40), a.xOf(20, 40), a.xOf(40, 40), a.xOf(55, 40), a.xOf(-3, 40)],
  cell: [a.cellTxt(prof[0]), a.cellTxt(prof[1]), a.cellTxt(prof[4]), a.cellTxt(prof[5]), a.cellTxt(null)],
  rwyAtis: a.rwyPanel(aw, { arr: "29", dep: "29", source: "ATIS", letter: "K" }, ""),
  rwyPref: a.rwyPanel(aw, { arr: "11", dep: "29", source: "preferred" }, ""),
  rwyNone: a.rwyPanel(aw, null, ""), rwyLoading: a.rwyPanel(null, null, ""), rwyErr: a.rwyPanel(null, null, "Unknown aerodrome EPXX"),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("awalon")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "wind.mjs").write_text(WIND, "utf-8")
    (d / "awalon.mjs").write_text(AWALON.replace('"../api.js"', '"./api.mjs"').replace('"../wind.js"', '"./wind.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "wind.mjs").as_uri(), (d / "awalon.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _code(src: str) -> str:
    """Kod bez komentarzy (całych linii i końcówek po " //")."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())


def test_speed_bands_and_edges(js):
    # legenda od najsilniejszego jak w PANDORZE; dolna granica należy do klasy, "> 60" bez samego 60 kt
    assert js["bands"] == [">60", "40-60", "30-40", "20-30", "15-20", "10-15", "0-10"] and js["noData"] == "No data"
    assert js["bandOf"] == ["s0", "s0", "s10", "s10", "s15", "s15", "s20", "s20", "s30", "s30", "s40", "s40", "s40", "s60",
                            "s60", "s60", "none", "none", "none"]


def test_band_colours_from_pandora():
    """Kolory klas z wykresu PANDORY (10–15 kt turkusowy, 15–20 kt błękitny), jako zmienne w awalon.css."""
    tokens = dict(re.findall(r"--awl-(s\d+):\s*(#[0-9a-f]{6})", CSS))
    assert tokens == {"s60": "#b35ae8", "s40": "#e48ff2", "s30": "#ffb3ab", "s20": "#c8f2a4", "s15": "#7cd4f8",
                      "s10": "#92eaf0", "s0": "#a9b1be"}
    for b in tokens:
        assert f".awl-band.{b}" in CSS and f".awl-mx td.{b}" in CSS or b == "s0"
        assert f".awl-sw.{b}" in CSS or b == "s0"
    assert ".awl-sw.none" in CSS and ".awl-band.none { fill: transparent; }" in CSS


def test_axes_labels_and_arrows(js):
    # oś prędkości: co najmniej 40 kt, wyżej pełne dziesiątki; 7 podziałek co 1/6 w pełnych węzłach (0 6 13 20 26 33 40)
    assert js["axisMax"] == [40, 40, 40, 50, 50, 60, 70, 40]
    assert js["ticks"] == [[0, 6, 13, 20, 26, 33, 40], [0, 8, 16, 25, 33, 41, 50], [0, 10, 20, 30, 40, 50, 60]]
    assert js["alt"] == ["0", "1K", "5K", "10K"] and js["rowl"] == ["SFC", "1K", "10K"]
    # grot rysowany w stronę północy obrócony z wiatrem: wiatr z 270 (zachód) -> grot na wschód (90°); bez kierunku bez grotu
    assert js["rot"] == [90, 180, 270, 0, 225, None, None, None]
    assert js["tip"] == ["310°/14 kt G26", "270°/20 kt", "VRB/2 kt", "No data", "No data", "CALM/0 kt"]
    assert js["dir"] == ["310°", "VRB", "–", "CALM", "005°"]
    assert js["angle"] == ["005°", "340°", "–"] and js["speed"] == ["0 kt", "14 kt", "–"]


def test_matrix_order(js):
    """ALL: wiersze od 10K u góry do SFC na dole, komórki w kolejności lotnisk; brak wiersza = null."""
    assert js["matrix"] == [[2000, ["FCST:304/22", None]], [1000, ["GND:null/null", "FCST:294/15"]],
                            [0, ["METAR:300/10", "METAR:310/14"]]]
    assert js["matrixEmpty"] == [] and js["maxSpeed"] == [47, 0, 0]
    assert js["forecastFor"] == ["Today, 16:00 UTC", "27.10, 23:00 UTC", "–"]
    assert js["cell"] == ["310/14G26", "GND", "–", "VRB/02", "–"]


def test_moved_wind_helpers(js):
    """Funkcje z METEO › WIND (AERODROME i AWALON) z tymi samymi wynikami co wcześniej."""
    assert js["vec"] == ["310/14G26", "005/03", "VRB/02", "–", "–"]
    assert js["hw"] == ['H14', '<span class="tw">T14</span>', "H0", "–"] and js["xw"] == ["5R", "5L", "0", "–"]
    assert js["kt"] == [14, 13] and js["valid"] == ["18:00Z 06.10", "–"]
    assert js["note"] == ["Forecast for 12:00Z 12.10, fetched 12:04Z.", "", "Forecast unavailable.", "Forecast unavailable."]
    # podpowiedź punktu podejścia bez opisu odrzuconych punktów
    assert js["pointTip"] == "RWY 29: WA728, FAF, 7.0 NM from THR, 3° path ≈ 2590 ft\nApproaches: RNP"
    assert js["cl3"] == "CL 3°" and js["nm"] == ["3.0", "–"]
    for name in ("windVec", "kt", "hwTxt", "xwTxt", "validTxt", "forecastNote", "pointTip"):
        assert re.search(rf"^export const {name} = ", WIND, re.M), name
    # moduł bez DOM i bez zapytań
    assert "import " not in _code(WIND) and "document" not in _code(WIND) and "api(" not in _code(WIND)


def test_chart_model(js):
    c = js["chart"]
    pw, ph = c["w"] - c["l"] - c["r"], c["h"] - c["t"] - c["b"]
    m = js["model"]
    # oś prędkości do 47 kt -> 50 kt
    assert m["max"] == 50 and [t["v"] for t in m["ticks"]] == [0, 8, 16, 25, 33, 41, 50]
    assert m["ticks"][0]["x"] == c["l"] and m["ticks"][-1]["x"] == c["l"] + pw
    # wysokość: pas ±500 ft wokół wiersza, 0 ft na dole, 10 000 ft u góry (oś od -500 do 10 500 ft)
    assert js["y"] == [c["t"], c["t"] + ph, pytest.approx(c["t"] + ph * 10.5 / 11), pytest.approx(c["t"] + ph * 0.5 / 11)]
    assert js["x"] == [c["l"], c["l"] + pw / 2, c["l"] + pw, c["l"] + pw, c["l"]]
    b = {x["ft"]: x for x in m["bands"]}
    assert (b[0]["cls"], b[1000]["cls"], b[2000]["cls"], b[3000]["cls"], b[4000]["cls"]) == ("s10", "none", "s20", "s40", "none")
    assert b[2000]["rot"] == 90 and b[2000]["x"] == pytest.approx(c["l"] + pw * 20 / 50, abs=0.1)
    assert b[3000]["rot"] == 270 and b[1000]["rot"] is None and b[1000]["x"] is None and b[1000]["kind"] == "gnd"
    # VRB: bez grotu, kółko w miejscu prędkości
    assert b[5000]["rot"] is None and b[5000]["vrb"] is True and b[2000]["vrb"] is False
    assert b[0]["tip"] == "SFC: 310°/14 kt G26 · METAR" and b[2000]["tip"] == "2000 ft: 270°/20 kt · FCST"
    assert all(x["h"] == pytest.approx(ph / 11, abs=0.1) for x in m["bands"])
    assert b[2000]["y"] == pytest.approx(c["t"] + ph * (10500 - 2500) / 11000, abs=0.1)
    assert [a["label"] for a in m["alts"]] == ["0", "1K", "2K", "3K", "4K", "5K"]
    assert js["big"] == 70 and js["empty"] == 40


def test_runway_panel(js):
    """Panel pasów z METEO › WIND: wiatr przy ziemi (METAR, prognoza 10 m), składowe pasów przy ziemi i na 3000 ft w punkcie
    podejścia, ARR/DEP z ATIS (litera ATIS) albo pas preferowany ("?"), legenda H/T/L/R."""
    atis, pref, none = js["rwyAtis"], js["rwyPref"], js["rwyNone"]
    assert '<span class="awl-tag arr">ARR</span><span class="awl-tag dep">DEP</span>' in atis
    assert "ARR/DEP: RWY in use · ATIS K." in atis and "preferred runway" not in atis
    assert '<span class="awl-tag arr">ARR?</span>' in pref and '<span class="awl-tag dep">DEP?</span>' in pref
    assert "ARR?/DEP?: preferred runway." in pref and "ATIS" not in pref.split("H = headwind")[1]
    assert "ARR" not in none.split("<tbody>")[1].split("</tbody>")[0] and '<span class="awl-tags"></span>' in none
    for html in (atis, pref, none):
        assert "H = headwind, T = tailwind, L/R = crosswind from the left/right, kt." in html
        assert "Forecast for 16:00Z 28.10, fetched 16:25Z." in html and "METAR unavailable: no connection" in html
        assert "310/14G26" in html and "289/09G18" in html and "306/22" in html
        assert '<td class="num">H14</td><td class="num">4L</td>' in html and '<span class="tw">T14</span>' in html
        assert "WA728 <small>7.0 NM</small>" in html and "CL 3° <small>8.1 NM</small>" in html
        assert 'title="RWY 29: WA728, FAF, 7.0 NM from THR, 3° path ≈ 2590 ft\nApproaches: RNP"' in html
        assert "model" not in html.lower()
    assert '<tr class="arr dep"' in atis and '<tr class="arr"' in pref and '<tr class="dep"' in pref
    assert js["rwyLoading"] == '<p class="hint">Loading…</p>' and js["rwyErr"] == '<p class="error">Unknown aerodrome EPXX</p>'


def test_tab_wiring():
    """Zakładka po METEO, podmenu ALL (domyślnie) i 15 lotnisk AD 2 alfabetycznie, adres #awalon/<ICAO>, jedno
    zapytanie o wszystkie lotniska wspólne dla podzakładek, odświeżanie co 10 min tylko na ekranie."""
    assert tuple(re.findall(r'"(EP[A-Z]{2})"', AWALON[AWALON.index("export const AWALON_AD"):AWALON.index("];")])) == AD2_AERODROMES
    mount = AWALON[AWALON.index("export default {"):]
    assert '{ id: "all", label: "ALL", render: allView(store, open) },' in mount and "{ sep: true }," in mount
    assert "...AWALON_AD.map((i) => ({ id: i, label: i, render: aeroView(store, i) }))" in mount
    assert mount.index('id: "all"') < mount.index("AWALON_AD.map")
    assert AWALON.count('api("/api/meteo/wind-profile")') == 1 and 'remember("awalon", icao)' in AWALON
    assert "root.offsetParent !== null" in mount and "!document.hidden" in mount and "ONLINE_EVENT" in mount
    view = AWALON[AWALON.index("function aeroView("):AWALON.index("export default {")]
    assert "/api/meteo/approach-wind/${icao}" in view and "/api/aerodromes/${icao}/status" in view
    assert "clearInterval(timer)" in view and "removeEventListener(ONLINE_EVENT, online)" in view and "off()" in view
    assert "Wind Profile Chart for Aerodrome ${icao}" in view and "Forecast for: " in view
    allv = AWALON[AWALON.index("function allView("):AWALON.index("// --- strona lotniska")]
    assert "matrixRows(data)" in allv and 'closest("[data-icao]")' in allv and "open(c.dataset.icao)" in allv
    # przełącznik kolorów jak w PANDORZE, wybór zapamiętany
    assert '<span>Show colors</span>' in AWALON and 'lsGet(COLORS_KEY) !== "0"' in AWALON and '"awalon.colors"' in AWALON
    # nagłówki tabeli profilu
    for th in ("Altitude", "Dir", "Speed", "Status", "Min Angle", "Max Angle", "Min Spd", "Max Spd"):
        assert th + "<" in AWALON or f'mm("{th}")' in AWALON, th


def test_english_without_provenance_and_bold():
    """Napisy po angielsku (polskie litery tylko w komentarzach), bez nazw dostawców i opisów źródła wartości, bez
    pogrubień w AWALON i w wind.css (wyróżnienie kolorem), ostre krawędzie."""
    for name, src in (("awalon.js", AWALON), ("wind.js", WIND)):
        code = _code(src)
        assert not [line for line in code.splitlines() if POLISH.search(line)], name
        # polskie litery tylko w samodzielnych liniach komentarza
        for line in src.splitlines():
            if POLISH.search(line):
                assert line.strip().startswith("//"), (name, line)
        low = re.sub(r"https://[^\s\"`]*", "", code).lower()
        for word in ("open-meteo", "ecmwf", "vatsim", "viff", "windy", "model", "based on", "source:", "interpolated",
                     "computed", "<b>", "<strong>", "font-weight"):
            assert word not in low.replace("chartmodel", "").replace("model_surface", "").replace("model_error", "")\
                .replace("c_model", ""), (name, word)
    for name, css in (("awalon.css", CSS), ("wind.css", WIND_CSS)):
        rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        assert not re.search(r"font-weight:\s*(?:bold|[6-9]00)|font:\s*(?:bold|[6-9]00)\b", rules), name
        assert "text-shadow" not in rules and "glow" not in rules
        for val in re.findall(r"border-radius:\s*([^;}]+)", rules):
            assert val.strip() == "0", (name, val)
        for val in re.findall(r"box-shadow:\s*([^;}]+)", rules):
            assert all(p.strip().startswith(("inset", "none", "0 0 0 ")) for p in val.split(",")), (name, val)
    # nagłówki i tytuły z domyślnym pogrubieniem przeglądarki (h2, h3, th) w AWALON wprost normalne
    for sel in (".awl-title { margin: 0; font: 400", ".card.awl-rwy h3 { font-weight: 400; }", "table.data.awl-prof th { font-weight: 400; }",
                "table.data.awl-rt th { padding: 2px 4px; text-align: center; font-weight: 400; }"):
        assert sel in CSS, sel
    assert re.search(r"\.awl-mx thead th \{[^}]*font-weight: 400", CSS) and re.search(r"\.awl-mx th\.ft, \.awl-mx tbody th \{[^}]*font-weight: 400", CSS)
    # karta i uwaga zostają dla METEO › SUN, reguł dawnego METEO › WIND nie ma
    assert ".wnd-card {" in WIND_CSS and ".wnd-note {" in WIND_CSS
    for sel in (".wnd-bar", ".wnd-seg", ".wnd-side", ".wnd-tab", ".wnd-sfc", ".wnd-tag", ".wnd-aero", ".wnd-frame"):
        assert sel not in re.sub(r"/\*.*?\*/", "", WIND_CSS, flags=re.S), sel
