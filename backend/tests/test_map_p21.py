"""MAP (0.12.5): etykieta samolotu jak w PEGASUS_21 (airspace.js p21Lines, aircraftMarker) i symbol lotniska jako
zamknięty wielokąt (SYMBOLS, symbolSvg, rysowanie na kanwie z closePath). 0.12.6: etykieta w trzech linijkach (bez
"h  s  r" i RFL) i tylko w okienku po najechaniu na samolot (acLabelSpot), bez stałych etykiet i białego dymka."""
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
const dom = { callsign: "DOM004", groundspeed: 248, altitude: 5300, vs: 400, aircraft: "DC10", wake: "H", arrival: "EPWA", rfl: "24000", heading: 90 };
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
  // RFL z planu lotu nie zmienia etykiety (linijka 4 odpadła w 0.12.6)
  rflAny: ["FL080", "35000", "A045", "VFR", null].map((r) => as.p21Lines({ ...tra, rfl: r }, { exit: "MIXAT" })),
  marker: as.aircraftMarker(dom, { cls: "arr sel" }),
  markerPlain: as.aircraftMarker(tra),
  html: as.p21Html(dom), htmlExit: as.p21Html(tra, { exit: "MIXAT" }), htmlNoGs: as.p21Html({ ...dom, groundspeed: null }),
  htmlNoL3: as.p21Html({ callsign: "SPABC", groundspeed: 90, altitude: 1500 }),
  htmlLong: as.p21Html({ callsign: "LOT3913AB", groundspeed: 85, altitude: 9000 }),
  htmlEsc: as.p21Html({ callsign: "<X&>", groundspeed: 5 }),
  size: as.aircraftMarker(dom).icon.iconSize,
  // okienko etykiety (90 × 40 px) obok samolotu na mapie 800 × 600: z prawej, przy prawym brzegu z lewej, przy górnej
  // i dolnej krawędzi przesunięte w granice mapy, za szerokie na obie strony: tam, gdzie więcej miejsca
  spot: [[400, 300], [760, 300], [400, 5], [400, 598], [30, 10], [790, 590], [20, 300], [60, 300]]
    .map(([x, y]) => as.acLabelSpot(x, y, 90, 40, 800, 600)),
  spotWide: [as.acLabelSpot(50, 300, 760, 40, 800, 600), as.acLabelSpot(750, 300, 760, 40, 800, 600)],
  spotEdge: [690, 691].map((x) => as.acLabelSpot(x, 300, 90, 40, 800, 600).dir),
  gap: as.AC_LABEL_GAP,
  // nakładki Leafleta [lewo, góra, prawo, dół]: panel lotu z prawej na wysokości samolotu, wykres TV tuż pod samolotem,
  // przyciski zoomu nad samolotem, nakładka z boku bez wpływu, obie strony zasłonięte (jak bez nakładek)
  spotObst: [
    [440, 150, [[500, 10, 790, 276]]], [300, 463, [[10, 471, 560, 590]]], [20, 75, [[10, 10, 44, 70]]],
    [300, 300, [[600, 0, 800, 600]]], [400, 300, [[100, 200, 700, 400]]], [760, 150, [[500, 10, 790, 276]]],
  ].map(([x, y, obst]) => ({ x, y, obst, s: as.acLabelSpot(x, y, 90, 40, 800, 600, { obst }) })),
  exports: Object.keys(as).sort(),
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
    # DOM004 z P21: poniżej TL (FL080) "A" i setki stóp ze strzałką wznoszenia; typ + kategoria turbulencji, cel.
    # 0.12.6 (Marek): trzy linijki, bez "h  s  r" i RFL
    assert js["dom"] == ["DOM004   248", "A 53↑", "DC10H EPWA"]
    # TRA005: FL trzema cyframi, lot poziomy bez strzałki, tranzyt z punktem wyjścia z FIR-u zamiast celu
    assert js["tra"] == ["TRA005   431", "270", "B737M MIXAT"]


def test_p21_level_arrow_and_edge_cases(js):
    assert js["down"] == "A 53↓" and js["level"] == "A 53" and js["first"] == "A 53"  # pierwszy odczyt: bez strzałki
    assert js["ground"] == ["SPKAT    000", "A  4", "C172L EPWA"]
    assert js["noplan"] == ["SPABC    090", "A 15", ""]  # bez planu lotu: pusta trzecia linijka
    assert js["long"] == "LOT3913AB 085"
    # RFL z planu lotu nie ma już na etykiecie: zawsze te same trzy linijki
    assert all(x == ["TRA005   431", "270", "B737M MIXAT"] for x in js["rflAny"])
    assert "rflFeet" not in js["exports"]


def _text(html):
    return re.sub(r"<[^>]+>", "", html)


def test_aircraft_marker_without_label(js):
    """0.12.6 (Marek): samolot na mapie bez stałej etykiety: sama sylwetka obrócona wg kursu; klasa relacji i wyboru
    na ikonie, etykieta tylko w okienku po najechaniu (dymek Leafleta w MAP)."""
    for m in (js["marker"], js["markerPlain"]):
        html = m["icon"]["html"]
        assert "p21" not in html and "<span" not in html and "<i " not in html and "DOM004" not in html
        assert html.startswith('<div class="ac"><svg viewBox="-10 -10 20 20"') and html.endswith("</svg></div>")
    assert "rotate(90deg)" in js["marker"]["icon"]["html"]
    assert js["marker"]["icon"]["className"] == "acicon arr sel" and js["markerPlain"]["icon"]["className"] == "acicon"
    assert js["size"] == [14, 14]  # ikona mniejsza niż do 0.12.4 (20 px)


def test_p21_html(js):
    assert js["html"] == ('<i class="l1"><b class="cs">DOM004</b>   <b class="gs">248</b></i><i class="l2">A 53↑</i>'
                          '<i class="l3">DC10H EPWA</i>')
    lines = re.findall(r'<i class="l(\d)">(.*?)</i>', js["htmlExit"])
    assert [n for n, _ in lines] == ["1", "2", "3"]
    assert [_text(x) for _, x in lines] == ["TRA005   431", "270", "B737M MIXAT"]
    assert lines[0][1] == '<b class="cs">TRA005</b>   <b class="gs">431</b>'
    # bez planu lotu: dwie linijki (pusta trzecia odpada), nigdy czwarta
    assert 'class="l3"' not in js["htmlNoL3"] and 'class="l4"' not in js["htmlNoL3"] and js["htmlNoL3"].count("<i ") == 2
    # bez prędkości: sam znak; długi znak (9 znaków): jedna spacja przed prędkością
    assert js["htmlNoGs"].startswith('<i class="l1"><b class="cs">DOM004</b></i><i class="l2">')
    assert js["htmlLong"].startswith('<i class="l1"><b class="cs">LOT3913AB</b> <b class="gs">085</b></i>')
    assert js["htmlEsc"].startswith('<i class="l1"><b class="cs">&lt;X&amp;&gt;</b>     <b class="gs">005</b></i>')


def _box(x, y, spot, w=90, h=40):
    """Okienko na stronie: przesunięcie dymka to cały odstęp (map.css zeruje margines Leafleta, .ac-lbl margin: 0)."""
    left = x + spot["off"][0] if spot["dir"] == "right" else x - w + spot["off"][0]
    top = y - h / 2 + spot["off"][1]
    return left, top, left + w, top + h


def test_label_spot_inside_map(js):
    """Okienko etykiety (90 × 40) obok samolotu w granicach mapy 800 × 600 (margines 4 px, odstęp 16 px od środka)."""
    g = js["gap"]
    assert g == 16
    pts = [[400, 300], [760, 300], [400, 5], [400, 598], [30, 10], [790, 590], [20, 300], [60, 300]]
    assert [s["dir"] for s in js["spot"]] == ["right", "left", "right", "right", "right", "left", "right", "right"]
    assert js["spot"][0] == {"dir": "right", "off": [g, 0]} and js["spot"][1] == {"dir": "left", "off": [-g, 0]}
    for (x, y), s in zip(pts, js["spot"]):
        x0, y0, x1, y1 = _box(x, y, s)
        assert x0 >= 4 and y0 >= 4 and x1 <= 796 and y1 <= 596, ((x, y), s)
        # okienko nie zasłania samolotu: cała szerokość po jednej stronie, co najmniej odstęp od środka
        assert x0 >= x + g or x1 <= x - g, ((x, y), s)
    # przy prawym brzegu: z prawej tylko, gdy mieści się z marginesem 4 px (796 - 16 - 90 = 690)
    assert js["spotEdge"] == ["right", "left"]
    # za szerokie na obie strony: tam, gdzie więcej miejsca
    assert js["spotWide"][0]["dir"] == "right" and js["spotWide"][1]["dir"] == "left"


def test_label_spot_beside_overlays(js):
    """Przegląd 0.12.6: okienko wybranego lotu wchodziło pod panel szczegółów lotu, a okienko nad wykresem TV pod jego
    tytuł. Nakładki Leafleta to przeszkody: strona z nakładką na wysokości samolotu odpada, nakładka pod albo nad
    samolotem przesuwa okienko w pionie; gdy obie strony zasłonięte, jak bez nakładek (w granicach mapy)."""
    g = js["gap"]
    res = {(c["x"], c["y"]): c["s"] for c in js["spotObst"]}
    assert res[(440, 150)] == {"dir": "left", "off": [-g, 0]}  # panel lotu z prawej
    assert res[(300, 463)] == {"dir": "right", "off": [g, -16]}  # nad wykresem: dół okienka 4 px nad wykresem
    assert res[(20, 75)] == {"dir": "right", "off": [g, 19]}  # pod przyciskami zoomu: góra okienka 4 px pod nimi
    assert res[(300, 300)] == {"dir": "right", "off": [g, 0]}  # nakładka daleko z boku: bez zmian
    assert res[(400, 300)] == {"dir": "right", "off": [g, 0]}  # obie strony zasłonięte: jak bez nakładek
    assert res[(760, 150)] == {"dir": "left", "off": [-g, 0]}  # samolot pod panelem: jak bez nakładek (z lewej)
    for c in js["spotObst"]:
        if (c["x"], c["y"]) == (400, 300):
            continue
        x0, y0, x1, y1 = _box(c["x"], c["y"], c["s"])
        assert x0 >= 4 and y0 >= 4 and x1 <= 796 and y1 <= 596, c
        for ol, ot, orr, ob in c["obst"]:
            if (c["x"], c["y"]) == (760, 150):
                continue  # samolot pod panelem: okienko z lewej też na panelu (od x = 500)
            assert x1 <= ol or x0 >= orr or y1 <= ot - 4 or y0 >= ob + 4, c


def test_p21_label_css_and_legend():
    """Runda 14 (przegląd): na etykiecie DOM004 z P21 zielony jest tylko znak wywoławczy, prędkość (248) jest biała jak
    linijki 2-3. 0.12.6: etykieta w nieprzezroczystym okienku (czarne tło, cienka ramka, bez cienia i zaokrągleń,
    czytelne na każdym podkładzie), wybrany lot: znak i ramka na pomarańczowo; legenda z tego samego p21Html."""
    css = (JS.parent / "css" / "map.css").read_text("utf-8")
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    box = re.search(r"\.leaflet-tooltip\.ac-lbl \{([^}]*)\}", rules).group(1)
    assert "background: #000" in box and "border: 1px solid" in box and "border-radius: 0" in box and "box-shadow: none" in box
    assert "var(--mono)" in box
    # bez marginesu, który Leaflet dodaje dymkom z boku (6 px): odstęp od samolotu to samo przesunięcie z acLabelSpot,
    # inaczej okienko przy prawym brzegu wystawało do 2 px poza mapę
    assert box.lstrip().startswith("margin: 0;")
    assert ".leaflet-tooltip.ac-lbl::before { display: none; }" in rules  # bez strzałki dymka
    assert ".ac-lbl b.cs, .p21-sample b.cs { color: #00ff00; }" in rules
    assert ".ac-lbl.sel b.cs { color: #ff9f1a; }" in rules and ".leaflet-tooltip.ac-lbl.sel { border-color: #ff9f1a; }" in rules
    # linijka 1 ani prędkość nie mają własnego koloru: biorą kolor linijek (i) jak linijki 2-3
    assert "i.l1" not in rules and "b.gs" not in rules
    assert ".ac-lbl b, .p21-sample b { font-weight: inherit; }" in rules
    # stara etykieta w ikonie samolotu (span.p21) zniknęła, także z jasnych podkładów
    assert "span.p21" not in rules and ".acicon span" not in rules
    style = re.sub(r"/\*.*?\*/", "", (JS.parent / "css" / "style.css").read_text("utf-8"), flags=re.S)
    assert ".acicon span" not in style
    src = (JS / "tabs" / "map.js").read_text("utf-8")
    assert "const P21_SAMPLE = p21Html({" in src and '<span class="p21-sample">${P21_SAMPLE}</span>' in src
    assert "rfl:" not in src.split("const P21_SAMPLE")[1].split(");")[0]


def test_map_hover_label_wiring():
    """MAP: samolot dostaje okienko etykiety (dymek Leafleta na własnej warstwie acLbl nad plakietkami, pod kartami
    lotnisk), stałe tylko u wybranego lotu; bez białego dymka "znak typ ADEP→ADES FL · arrival to …", bez przełącznika
    etykiet P21 i progów zoomu."""
    src = (JS / "tabs" / "map.js").read_text("utf-8")
    code = re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M)
    draw = code.split("const drawTraffic = () => {")[1].split("\n  };")[0]
    assert "aircraftMarker(p, { cls: rel + (sel ? \" sel\" : \"\") })" in draw
    assert "bindTooltip(p21Html(p, { exit })" in draw and 'pane: "acLbl"' in draw and "permanent: sel" in draw
    assert "offset: [AC_LABEL_GAP, 0]" in draw
    assert '"ac-lbl" + (sel ? " sel" : "")' in draw and "opacity: 1" in draw
    assert 'on("tooltipopen", (e) => placeLabel(e.target))' in draw
    assert "getZoom" not in draw and "detail" not in draw and "label:" not in draw
    assert 'map.createPane("acLbl").style.zIndex = 690;' in code
    for gone in ("traffic-detail", "P21 labels", "REL_TEXT", "arrival to ${", "→${esc(p.arrival"):
        assert gone not in code, gone
    # warstwa okienka: nad plakietkami lotnisk (atcAd 660) i FIR (655), pod kartami lotnisk (atcTip 700)
    air = (JS / "airspace.js").read_text("utf-8")
    assert '["atcFirName", 585], ["atcFir", 655], ["atcAd", 660], ["atcTip", 700]' in air
    # okienko obok nakładek Leafleta (panel lotu, wykres TV, przyciski), także po ich zmianie bez ruchu mapy (relabel)
    place = code.split("const placeLabel = (m) => {")[1].split("\n  };")[0]
    assert 'querySelectorAll(".leaflet-control")' in place
    assert "acLabelSpot(p.x, p.y, el.offsetWidth, el.offsetHeight, W, H, { obst })" in place
    assert "declutter(); placeLabels(); });" in code
    assert "const placeLabels = () => { if (mapEl.offsetWidth) layers.traffic.eachLayer(placeLabel); };" in code


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
