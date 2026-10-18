"""MAP (0.12.5): etykieta samolotu jak w PEGASUS_21 (airspace.js p21Lines, aircraftMarker) i symbol lotniska jako
zamknięty wielokąt (SYMBOLS, symbolSvg, rysowanie na kanwie z closePath)."""
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"

NODE_SCRIPT = r"""
// airspace.js przy imporcie rozszerza L.CircleMarker; aircraftMarker potrzebuje L.marker i L.divIcon
globalThis.L = { CircleMarker: { extend: (o) => o }, divIcon: (o) => o, marker: (ll, o) => ({ ll, ...o }) };
const as = await import(process.argv[2]);
const dom = { callsign: "DOM004", groundspeed: 248, altitude: 5300, vs: 400, aircraft: "DC10", wake: "H", arrival: "EPWA", rfl: "24000" };
const tra = { callsign: "TRA005", groundspeed: 431, altitude: 27010, vs: 20, aircraft: "B737", wake: "M", arrival: "EHAM", rfl: "FL270" };
// kanwa na niby: zapis wywołań rysowania symbolu lotniska
const calls = [];
const ctx = new Proxy({}, { get: (_, k) => (...a) => calls.push([k, ...a.map((x) => Math.round(x * 10) / 10)]) });
const mk = Object.assign(Object.create(as.SymbolMarker), { options: { ...as.SymbolMarker.options, symbol: "aerodrome", scale: 1 },
  _point: { x: 100, y: 50 }, _empty: () => false, _renderer: { _ctx: ctx, _drawing: true, _fillStroke: () => calls.push(["stroke"]) } });
mk._updatePath();
const out = {
  dom: as.p21Lines(dom), tra: as.p21Lines(tra, { exit: "MIXAT" }),
  down: as.p21Lines({ ...dom, vs: -250 })[1], level: as.p21Lines({ ...dom, vs: 60 })[1], first: as.p21Lines({ ...dom, vs: null })[1],
  ground: as.p21Lines({ callsign: "SPKAT", groundspeed: 0, altitude: 362, aircraft: "C172", wake: "L", arrival: "EPWA", rfl: "1500" }),
  noplan: as.p21Lines({ callsign: "SPABC", groundspeed: 90, altitude: 1500, vs: null }),
  long: as.p21Lines({ callsign: "LOT3913AB", groundspeed: 85, altitude: 9000 })[0],
  rfl: ["35000", "FL350", "F350", "350", "A045", "FL365", "VFR", "", null, "S1130"].map(as.rflFeet),
  rfl365: as.p21Lines({ ...tra, rfl: "FL365" })[3],
  // linijka 4 dla RFL: dziesiątki FL dwiema cyframi, poniżej TL jak linijka 2
  rflL4: ["FL080", "FL090", "8000", "FL085", "FL350", "35000", "FL100", "A045", "4500", "A005", "FL070", "VFR"]
    .map((r) => as.p21Lines({ ...tra, rfl: r })[3]),
  short: as.aircraftMarker(dom, { label: true }).icon.html,
  full: as.aircraftMarker(tra, { label: true, detail: true, exit: "MIXAT" }).icon.html,
  noL3: as.aircraftMarker({ callsign: "SPABC", groundspeed: 90, altitude: 1500 }, { detail: true }).icon.html,
  size: as.aircraftMarker(dom).icon.iconSize,
  ad: as.SYMBOLS.aerodrome, half: ["aerodrome", "vor", "ndb", "vfr", "fix"].map(as.symbolHalf),
  svg: as.symbolSvg("aerodrome", "#fff"), svgFix: as.symbolSvg("fix", "#fff"),
  svgs: Object.fromEntries(["aerodrome", "vor", "ndb", "vfr", "fix"].map((n) => [n, [as.symbolSvg(n, "#fff"), as.symbolSvg(n, "#fff", 12)]])),
  syms: as.SYMBOLS,
  calls,
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    (d / "airspace.mjs").write_text((JS / "airspace.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "airspace.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_p21_lines_like_reference(js):
    # DOM004 z P21: poniżej TL (FL080) "A" i setki stóp ze strzałką wznoszenia; typ + kategoria turbulencji, cel;
    # h s r i RFL w dziesiątkach FL (VATSIM nie ma poziomu z zezwolenia)
    assert js["dom"] == ["DOM004   248", "A 53↑", "DC10H EPWA", "h  s  r 24"]
    # TRA005: FL trzema cyframi, lot poziomy bez strzałki, tranzyt z punktem wyjścia z FIR-u zamiast celu
    assert js["tra"] == ["TRA005   431", "270", "B737M MIXAT", "h  s  r 27"]


def test_p21_level_arrow_and_edge_cases(js):
    assert js["down"] == "A 53↓" and js["level"] == "A 53" and js["first"] == "A 53"  # pierwszy odczyt: bez strzałki
    assert js["ground"] == ["SPKAT    000", "A  4", "C172L EPWA", "h  s  r A 15"]  # RFL poniżej TL jak linijka 2
    assert js["noplan"] == ["SPABC    090", "A 15", "", "h  s  r"]  # bez planu lotu: pusta trzecia linijka
    assert js["long"] == "LOT3913AB 085"
    assert js["rfl"] == [35000, 35000, 35000, 35000, 4500, 36500, None, None, None, None]
    assert js["rfl365"] == "h  s  r 365"  # poziom niepodzielny przez 10: trzy cyfry


def test_p21_rfl_two_digit_tens_and_below_tl(js):
    """Runda 14 (przegląd): FL080 / FL090 dawały jedną cyfrę ("r 8"), a RFL poniżej TL "A45" zamiast "A 45" jak w linijce 2
    (DOM004 z P21: "A 53"). Dziesiątki FL zawsze dwiema cyframi, poniżej TL "A" i setki stóp na trzech znakach."""
    assert js["rflL4"] == ["h  s  r 08", "h  s  r 09", "h  s  r 08", "h  s  r 085", "h  s  r 35", "h  s  r 35", "h  s  r 10",
                           "h  s  r A 45", "h  s  r A 45", "h  s  r A  5", "h  s  r A 70", "h  s  r"]


def test_aircraft_marker_label(js):
    # bez szczegółów sam znak; ze szczegółami cztery linijki (pierwsza zielona w map.css), bez <br> i bez tła w HTML
    assert '<span class="p21"><i class="l1">DOM004</i></span>' in js["short"]
    full = js["full"]
    assert ['<i class="l1">TRA005   431</i>', '<i class="l2">270</i>', '<i class="l3">B737M MIXAT</i>', '<i class="l4">h  s  r 27</i>'] == \
        [x for x in (f'<i class="l{i}">' + full.split(f'<i class="l{i}">')[1].split("</i>")[0] + "</i>" for i in range(1, 5))]
    assert 'class="l3"' not in js["noL3"] and 'class="l4"' in js["noL3"]
    assert js["size"] == [14, 14]  # ikona mniejsza niż do 0.12.4 (20 px)


def test_aerodrome_symbol_is_closed_polygon(js):
    ring = js["ad"][0]
    assert len(js["ad"]) == 1 and ring[0] == ring[-1] and len(ring) == 7
    assert sorted(x for x, _ in ring[:-1]) == [-6, -3, -3, 3, 3, 6]  # symetryczny: lewy wierzchołek jak prawy
    assert js["half"] == [6, 4, 2, 3, 4]
    # SVG: jeden <polygon> (zamknięty), bez <polyline> z rozłączeniem
    assert js["svg"].count("<polygon") == 1 and "<polyline" not in js["svg"] and "-6,0" in js["svg"]
    assert "<circle" in js["svgFix"]
    # kanwa: jedno moveTo, pięć lineTo i closePath (narożnik startowy połączony), potem obrys
    names = [c[0] for c in js["calls"]]
    assert names == ["beginPath", "moveTo", "lineTo", "lineTo", "lineTo", "lineTo", "lineTo", "closePath", "stroke"]
    assert js["calls"][1] == ["moveTo", 97, 47] and js["calls"][6] == ["lineTo", 94, 50]


def _miter_reach(ring, w, closed=True):
    """Największe |x| / |y| symbolu z obrysem w: wierzchołki ± w/2 i ostrza narożników (miter, limit 4)."""
    r = max(max(abs(x), abs(y)) + w / 2 for x, y in ring)
    n = len(ring)
    for i, (x, y) in enumerate(ring):
        if not closed and i in (0, n - 1):
            continue
        (ax, ay), (bx, by) = ring[i - 1], ring[(i + 1) % n]
        u1 = ((ax - x) / math.hypot(ax - x, ay - y), (ay - y) / math.hypot(ax - x, ay - y))
        u2 = ((bx - x) / math.hypot(bx - x, by - y), (by - y) / math.hypot(bx - x, by - y))
        half = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))) / 2
        if half < 1e-9 or 1 / math.sin(half) > 4:
            continue
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        lb = math.hypot(*bis)
        if lb < 1e-9:
            continue
        d = w / 2 / math.sin(half)
        r = max(r, abs(x - bis[0] / lb * d), abs(y - bis[1] / lb * d))
    return r


def test_symbol_icons_fit_viewbox(js):
    """Runda 14 (przegląd): ikona lotniska w legendzie i przełączniku warstw miała ucięte lewy i prawy wierzchołek
    (viewBox ±5,83, sześciokąt do ±6 z obrysem i ostrzem narożnika). Każdy symbol z obrysem mieści się w viewBox,
    a obrys na ekranie ma ok. 1,3 px."""
    for name, svgs in js["svgs"].items():
        for svg in svgs:
            size = float(re.search(r'width="([\d.]+)"', svg).group(1))
            x0, y0, vw, vh = map(float, re.search(r'viewBox="([^"]+)"', svg).group(1).split())
            assert x0 == y0 == -vw / 2 and vw == vh, (name, svg)
            w = float(re.search(r'stroke-width="([\d.]+)"', svg).group(1))
            assert w * size / vw == pytest.approx(1.3, abs=0.01), (name, svg)
            sym = js["syms"][name]
            if "circle" in sym:
                reach = sym["circle"] + w / 2
            else:
                reach = max(_miter_reach(line[:-1] if line[0] == line[-1] else line, w, line[0] == line[-1]) for line in sym)
            assert reach <= -x0, (name, size, reach, -x0)
    # lotnisko cały (ze szpicami ±6) i nadal czytelne: co najmniej ok. 1 px na jednostkę
    x0 = float(re.search(r'viewBox="([^"]+)"', js["svgs"]["aerodrome"][0]).group(1).split()[0])
    assert 6.7 < -x0 < 7.3
