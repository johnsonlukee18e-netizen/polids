"""METEO › METAR i TAF jak strona METAR w PANDORZE (0.13.1, zdjęcie Marka): kolory grup, opis zjawisk [EN / PL],
COLOURED / MONO. Czyste funkcje z frontend/js/metarfmt.js uruchamiane w Node, pasek i arkusz sprawdzane w tekście."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
SRC = FRONTEND / "js" / "metarfmt.js"
CSS_SRC = FRONTEND / "css" / "metar.css"
METEO = (FRONTEND / "js" / "tabs" / "meteo.js").read_text("utf-8")

# METAR-y ze zdjęcia PANDORY (kolejność alfabetyczna jak na zdjęciu)
PHOTO = [
    "EPBY 121030Z 23011KT 9999 OVC013 05/03 Q1009",
    "EPGD 121030Z 25012KT 210V280 9999 -RA BKN008 03/03 Q1004",
    "EPLB 121030Z 27017G27KT 9999 SCT027 BKN045 04/00 Q1012",
    "EPRA 121000Z 29014KT 9999 BKN030 05/M00 Q1013 RMK 045 072 5/5",
    "EPWA 121030Z 27017KT 9999 SCT017 BKN036 05/01 Q1011 BECMG BKN015",
]
CODES = ["-RA", "RA", "+RA", "-DZ", "+SN", "RASN", "SNRA", "-RADZ", "BR", "HZ", "FG", "BCFG", "MIFG", "PRFG", "FZFG", "VCFG",
         "TS", "VCTS", "-TSRA", "+TSRAGR", "TSGS", "-SHSN", "SHGS", "-SHRASN", "VCSH", "-FZDZ", "FZRA", "BLSN", "DRSN", "+BLSN",
         "SQ", "+FC", "FC", "PO", "SS", "+DS", "VA", "FU", "DU", "SA", "IC", "PL", "UP", "SG", "GR", "RERA", "RETSRA",
         "RESHSN", "NSW",
         # nie zjawiska: kolory wojskowe, stacja, trend, CAVOK, brak obserwacji, same przedrostki
         "GRN", "BLU", "WHT", "RED", "AMB", "EPWA", "TEMPO", "CAVOK", "NOSIG", "//", "VC", "RE", "FZ", "CB", "WS"]
GROUPS = ["121030Z", "27017G27KT", "210V280", "9999", "-RA", "OVC013", "05/M00", "Q1009", "BECMG", "BKN015CB", "R29/0350N",
          "R11/P2000U", "VRB03KT", "CAVOK", "NOSIG", "FM1200", "1212/1312", "TX12/1214Z", "NIL", "AUTO", "0800NE", "VV001",
          "NSC", "A2992"]

NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const input = JSON.parse(process.argv[3]);
console.log(JSON.stringify({
  phrase: Object.fromEntries(input.codes.map((c) => [c, m.wxPhrase(c)])),
  parts: Object.fromEntries(input.groups.map((g) => [g, m.groupParts(g, {})])),
  rmk: (() => { const st = {}; return ["RMK", "RA", "BKN010", "BLU"].map((t) => m.groupParts(t, st)); })(),
  photo: input.photo.map((r) => m.wxRow("metar", { icao: r.slice(0, 4), raw: r })),
  plain: m.wxBody("metar", input.photo[1], "EPGD", { decode: false }),
  nil: m.wxRow("metar", { icao: "EPZG", raw: null }),
  prefixed: m.wxLinesOf("metar", "METAR COR EPGD 121030Z 25012KT 9999 FEW010 03/03 Q1004=", "EPGD"),
  taf: m.wxLinesOf("taf", "TAF AMD EPWA 121100Z 1212/1312 27010KT CAVOK BECMG 1214/1216 BKN012 PROB30 TEMPO 1218/1222 -SHRA", "EPWA"),
  tafHtml: m.wxBody("taf", "TAF EPKK 121100Z 1212/1312 24008KT CAVOK TEMPO 1300/1306 0800 FG", "EPKK"),
  escaped: m.wxBody("metar", "EPWA 121030Z <img src=x>", "EPWA"),
  table: m.wxTable("metar", [{ icao: "EPBY", raw: input.photo[0] }]).startsWith('<table class="mt-tab"><tbody><tr><td class="mt-st">EPBY</td>'),
  mode: [m.wxMode("mono"), m.wxMode("coloured"), m.wxMode("colour"), m.wxMode("x"), m.wxMode(null), m.MODE_KEY],
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("metarfmt")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "metarfmt.mjs").write_text(SRC.read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    arg = json.dumps({"codes": CODES, "groups": GROUPS, "photo": PHOTO})
    r = subprocess.run([node, str(script), (d / "metarfmt.mjs").as_uri(), arg], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_weather_phrases_en_pl(js):
    """Opis zjawiska jak na zdjęciu ("-RA[LIGHT RAIN / LEKKI DESZCZ]"): intensywność, deskryptor, opady, zjawiska
    zaciemniające i inne, VC, RE; polski z rodzajem i narzędnikiem. Małymi literami: wielkie litery robi CSS."""
    p = {k: (v and f"{v['en']} / {v['pl']}") for k, v in js["phrase"].items()}
    assert p["-RA"] == "light rain / lekki deszcz"
    assert p["RA"] == "rain / deszcz" and p["+RA"] == "heavy rain / silny deszcz"
    assert p["-DZ"] == "light drizzle / lekka mżawka" and p["+SN"] == "heavy snow / silny śnieg"
    assert p["RASN"] == "rain and snow / deszcz ze śniegiem" and p["SNRA"] == "snow and rain / śnieg z deszczem"
    assert p["-RADZ"] == "light rain and drizzle / lekki deszcz z mżawką"
    assert p["BR"] == "mist / zamglenie" and p["HZ"] == "haze / zmętnienie" and p["FG"] == "fog / mgła"
    assert p["BCFG"] == "fog patches / płaty mgły" and p["MIFG"] == "shallow fog / płytka mgła"
    assert p["PRFG"] == "partial fog / częściowa mgła" and p["FZFG"] == "freezing fog / marznąca mgła"
    assert p["VCFG"] == "fog in the vicinity / mgła w pobliżu"
    assert p["TS"] == "thunderstorm / burza" and p["VCTS"] == "thunderstorm in the vicinity / burza w pobliżu"
    assert p["-TSRA"] == "thunderstorm with light rain / burza z lekkim deszczem"
    assert p["+TSRAGR"] == "thunderstorm with heavy rain and hail / burza z silnym deszczem i gradem"
    assert p["TSGS"] == "thunderstorm with small hail / burza z krupą"
    assert p["-SHSN"] == "light snow showers / lekki przelotny śnieg" and p["SHGS"] == "small hail showers / przelotna krupa"
    assert p["-SHRASN"] == "light rain and snow showers / lekki przelotny deszcz ze śniegiem"
    assert p["VCSH"] == "showers in the vicinity / opady przelotne w pobliżu"
    assert p["-FZDZ"] == "light freezing drizzle / lekka marznąca mżawka" and p["FZRA"] == "freezing rain / marznący deszcz"
    assert p["BLSN"] == "blowing snow / zamieć śnieżna wysoka" and p["DRSN"] == "low drifting snow / zamieć śnieżna niska"
    assert p["+BLSN"] == "heavy blowing snow / silna zamieć śnieżna wysoka"
    assert p["SQ"] == "squalls / szkwał" and p["+FC"] == "tornado or waterspout / trąba powietrzna lub wodna"
    assert p["FC"] == "funnel cloud / chmura lejkowa" and p["PO"] == "dust whirls / wiry pyłowe"
    assert p["SS"] == "sandstorm / burza piaskowa" and p["+DS"] == "heavy duststorm / silna burza pyłowa"
    assert p["VA"] == "volcanic ash / popiół wulkaniczny" and p["FU"] == "smoke / dym" and p["DU"] == "widespread dust / pył"
    assert p["SA"] == "sand / piasek" and p["IC"] == "ice crystals / igły lodowe" and p["PL"] == "ice pellets / ziarna lodowe"
    assert p["UP"] == "unknown precipitation / nieznany opad" and p["SG"] == "snow grains / śnieg ziarnisty"
    assert p["GR"] == "hail / grad" and p["RERA"] == "recent rain / niedawny deszcz"
    assert p["RETSRA"] == "recent thunderstorm with rain / niedawna burza z deszczem"
    assert p["RESHSN"] == "recent snow showers / niedawny przelotny śnieg"
    assert p["NSW"] == "no significant weather / brak istotnych zjawisk"
    for code in ("GRN", "BLU", "WHT", "RED", "AMB", "EPWA", "TEMPO", "CAVOK", "NOSIG", "//", "VC", "RE", "FZ", "CB", "WS"):
        assert p[code] is None, code


def test_group_colours_like_photo(js):
    """Kolory ze zdjęcia: dzień, kierunek, zjawisko, RMK zielone (mt-key); godzina, prędkość, poryw, widzialność,
    podstawa chmur, wartość QNH jasnozielone (mt-val); ilość chmur ciemnozielona (mt-cov); BECMG niebieski (mt-trend);
    Z, KT, G, V, Q i temperatura białe (bez klasy)."""
    parts = {k: v["parts"] for k, v in js["parts"].items()}
    assert parts["121030Z"] == [["mt-key", "12"], ["mt-val", "1030"], ["", "Z"]]
    assert parts["27017G27KT"] == [["mt-key", "270"], ["mt-val", "17"], ["", "G"], ["mt-val", "27"], ["", "KT"]]
    assert parts["210V280"] == [["mt-key", "210"], ["", "V"], ["mt-key", "280"]]
    assert parts["9999"] == [["mt-val", "9999"]] and parts["CAVOK"] == [["mt-val", "CAVOK"]]
    assert parts["-RA"] == [["mt-key", "-RA"]] and js["parts"]["-RA"]["dec"] == {"en": "light rain", "pl": "lekki deszcz"}
    assert parts["OVC013"] == [["mt-cov", "OVC"], ["mt-val", "013"]]
    assert parts["BKN015CB"] == [["mt-cov", "BKN"], ["mt-val", "015"], ["mt-key", "CB"]]
    assert parts["05/M00"] == [["", "05/M00"]] and parts["Q1009"] == [["", "Q"], ["mt-val", "1009"]]
    assert parts["BECMG"] == [["mt-trend", "BECMG"]] and parts["NOSIG"] == [["mt-trend", "NOSIG"]]
    assert parts["FM1200"] == [["mt-trend", "FM"], ["mt-val", "1200"]]
    assert parts["R29/0350N"] == [["", "R"], ["mt-key", "29"], ["", "/"], ["mt-val", "0350"], ["", "N"]]
    assert parts["R11/P2000U"] == [["", "R"], ["mt-key", "11"], ["", "/P"], ["mt-val", "2000"], ["", "U"]]
    assert parts["VRB03KT"] == [["mt-key", "VRB"], ["mt-val", "03"], ["", "KT"]]
    assert parts["1212/1312"] == [["mt-key", "12"], ["mt-val", "12"], ["", "/"], ["mt-key", "13"], ["mt-val", "12"]]
    assert parts["TX12/1214Z"] == [["", "TX12/"], ["mt-key", "12"], ["mt-val", "14"], ["", "Z"]]
    assert parts["NIL"] == [["mt-nil", "NIL"]] and parts["AUTO"] == [["", "AUTO"]]
    assert parts["0800NE"] == [["mt-val", "0800"], ["", "NE"]] and parts["VV001"] == [["mt-cov", "VV"], ["mt-val", "001"]]
    assert parts["NSC"] == [["mt-cov", "NSC"]] and parts["A2992"] == [["", "A"], ["mt-val", "2992"]]
    # po RMK wszystko białe i bez opisu (zdjęcie: "RMK 045 072 5/5")
    assert [g["parts"] for g in js["rmk"]] == [[["mt-key", "RMK"]], [["", "RA"]], [["", "BKN010"]], [["", "BLU"]]]
    assert all("dec" not in g for g in js["rmk"])


def test_rows_like_photo(js):
    """Wiersz: stacja w osobnej kolumnie, treść bez kodu stacji; opis zjawiska tuż za grupą, bez spacji, w tej samej
    grupie (nie łamie się w środku); bez opisu (decode false) sama grupa; NIL na czerwono."""
    by, gd, lb, ra, wa = js["photo"]
    assert by.startswith('<tr><td class="mt-st">EPBY</td><td class="mt-tx"><div class="mt-ln"><span class="mt-g">'
                         '<span class="mt-key">12</span><span class="mt-val">1030</span>Z</span> ')
    assert ">EPBY<" in by and by.count("EPBY") == 1
    assert '<span class="mt-g"><span class="mt-key">-RA</span><span class="mt-dec">[light rain / lekki deszcz]</span></span>' in gd
    assert '<span class="mt-key">210</span>V<span class="mt-key">280</span>' in gd
    assert '<span class="mt-key">270</span><span class="mt-val">17</span>G<span class="mt-val">27</span>KT' in lb
    assert '<span class="mt-key">RMK</span></span> <span class="mt-g">045</span> <span class="mt-g">072</span>' in ra
    assert '<span class="mt-g">05/M00</span>' in ra
    assert '<span class="mt-trend">BECMG</span></span> <span class="mt-g"><span class="mt-cov">BKN</span><span class="mt-val">015</span>' in wa
    assert "mt-dec" not in js["plain"] and '<span class="mt-key">-RA</span></span>' in js["plain"]
    assert js["nil"] == '<tr><td class="mt-st">EPZG</td><td class="mt-tx"><div class="mt-ln"><span class="mt-nil">NIL</span></div></td></tr>'
    assert js["table"] is True
    assert "&lt;img" in js["escaped"] and "<img" not in js["escaped"]


def test_lines_without_prefix_and_station(js):
    """Bez "METAR"/"TAF" i kodu stacji (kolumna obok); SPECI/COR/AMD zostają; TAF: grupa zmian w nowej linii
    (wcięta, mt-cont), PROB30 TEMPO razem."""
    assert js["prefixed"] == [["COR", "121030Z", "25012KT", "9999", "FEW010", "03/03", "Q1004="]]
    assert js["taf"] == [["AMD", "121100Z", "1212/1312", "27010KT", "CAVOK"], ["BECMG", "1214/1216", "BKN012"],
                         ["PROB30", "TEMPO", "1218/1222", "-SHRA"]]
    assert js["tafHtml"].count('<div class="mt-ln mt-cont">') == 1 and "[fog / mgła]" in js["tafHtml"]


def test_mode_key(js):
    """Domyślnie COLOURED; MONO tylko po wyborze (wartość spoza listy, np. pusta pamięć, daje COLOURED)."""
    assert js["mode"] == ["mono", "coloured", "coloured", "coloured", "coloured", "meteo.wx.mode"]


def test_ascii_code():
    """W kodzie tylko ASCII (polskie litery opisów jako \\u017c itd.), poza komentarzami w osobnych linijkach."""
    src = SRC.read_text("utf-8")
    bad = [line.strip() for line in src.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
    assert not bad, bad


def test_css_look():
    """Arkusz METAR: bez pogrubień i poświaty, ostre krawędzie, opis kapitalikami, MONO jednym kolorem, wiersze na
    przemian czarne i ciemnoszare jak na zdjęciu."""
    css = re.sub(r"/\*.*?\*/", "", CSS_SRC.read_text("utf-8"), flags=re.S)
    assert not re.search(r"font-weight:\s*(?:bold|[6-9]00)|font:\s*(?:bold|[6-9]00)\b", css)
    assert "text-shadow" not in css and "glow" not in css
    assert all(v.strip() == "0" for v in re.findall(r"border-radius:\s*([^;}]+)", css))
    assert ".mt-tab .mt-dec { font-size: .8em; font-variant: small-caps; text-transform: capitalize; }" in css
    assert ".mtr.mono .mt-tab span { color: inherit; }" in css
    assert "table.mt-tab tr:nth-child(even) td { background: var(--mt-alt); }" in css


def test_css_font_sans():
    """Czcionka jak w całym programie (bezszeryfowa, zwykła grubość), nigdy o stałej szerokości: METAR w var(--mono),
    a --mono to od 0.13.0 Arial."""
    css = re.sub(r"/\*.*?\*/", "", CSS_SRC.read_text("utf-8"), flags=re.S)
    assert not re.search(r"monospace|courier|consolas|menlo|monaco|dejavu sans mono|liberation mono", css, re.I)
    assert "table.mt-tab { border-collapse: collapse; width: 100%; font: 18px/1.45 var(--mono); color: #fff; }" in css
    style = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "style.css").read_text("utf-8"), flags=re.S)
    mono = re.search(r"--mono:\s*([^;]+);", style).group(1)
    assert mono.startswith("Arial") and "monospace" not in mono


def test_toolbar_switch_first():
    """Pasek METAR/TAF: COLOURED / MONO jako pierwszy (lewy górny róg jak na zdjęciu), potem pole stacji, Show,
    odświeżanie i czas; wybór we wspólnym kluczu meteo.wx.mode (lsGet/lsSet), lista jako tabela z metarfmt.js."""
    body = METEO[METEO.index("function wxList("):METEO.index("// --- RADAR")]
    bar = body[body.index('<div class="toolbar mtr-bar">'):body.index('<div class="mtr-list">')]
    order = [bar.index(x) for x in ('data-mode="coloured"', ">COLOURED</button>", 'data-mode="mono"', ">MONO</button>",
                                    'class="ids"', ">Show</button>", "refresh every 2 min", 'class="hint upd"')]
    assert order == sorted(order)
    assert "setMode(wxMode(lsGet(MODE_KEY)))" in body and "lsSet(MODE_KEY, b.dataset.mode)" in body
    assert 'wrap.classList.toggle("mono", m === "mono")' in body
    assert '$(".mtr-list").innerHTML = wxTable(kind, rows, { decode: true })' in body
    assert 'import { MODE_KEY, wxMode, wxTable } from "../metarfmt.js";' in METEO
    # AERODROME, OVERVIEW, AWOS i karta lotniska zagranicznego zostają przy dawnym colorize()/wxLines()
    assert "export function colorize(raw)" in METEO and "export function wxLines(kind, raw)" in METEO


def test_css_linked_after_meteoimg():
    html = (FRONTEND / "index.html").read_text("utf-8")
    assert ('<link rel="stylesheet" href="/static/css/meteoimg.css">\n  <link rel="stylesheet" href="/static/css/metar.css">'
            in html)
