"""0.12.3 (issue #13): AD CIV z podmenu: "eAIP" (cała przeglądarka) i przycisk dla każdego lotniska AD 2, który otwiera
w tej samej ramce stronę AD 2 lotniska z tej samej poprawki AIRAC co skonfigurowany link (adres "#adciv/EPWA").
0.12.5 (issue #18): przycisk lotniska otwiera listę map lotniska (AD 2.24, GET /api/docs/charts/<ICAO>) z PDF-em obok
zamiast opisu tekstowego; adres "#adciv/EPWA/2-1" = wybrana mapa; strona AD 2 zostaje jako przycisk "AD 2 TEXT ↗".
0.13.1 (issue #25): AD MIL i AD VFR tak samo (jedna fabryka aipTab, tabela AIP): 15 lotnisk wojskowych i 69 lotnisk VFR
z części AD 4 swojego pakietu, mapy z AD 4.24 / AD 4.13 (GET /api/docs/charts/<ifr|mil|vfr>/<ICAO>), przycisk
"AD 4 TEXT ↗", adresy "#admil/EPKS/12-5", "#advfr/EPBC"; wybrany przycisk przewijany do widoku w długim podmenu."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
AIP = (FRONTEND / "js" / "tabs" / "aip.js").read_text("utf-8")
BASE = "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html"

NODE_SCRIPT = r"""
const aip = await import(process.argv[2]);
const base = process.argv[3];
const pdf = (id) => `https://x.test/AD_2_EPZG_${id}.pdf`;
const charts = [
  { id: "2-1", page: "AD 2 EPZG 2-1", title: "AERODROME", full: "AERODROME CHART - ICAO", kind: "ADC", url: pdf("2-1") },
  { id: "12-1", page: "AD 2 EPZG 12-1", title: "RWY 24 ILS Z", full: "INSTRUMENT APPROACH CHART - ICAO (ILS z) RWY 24", kind: "IAC", url: pdf("12-1") },
  { id: "12-3", page: "AD 2 EPZG 12-3", title: 'APPROACH <b>"x" & y</b>', kind: "IAC", url: pdf("12-3") },
  { id: "10-1", page: "AD 2 EPZG 10-1", title: "STANDARD ARRIVAL CHART", kind: "STAR", url: pdf("10-1") },
];
console.log(JSON.stringify({
  ad2: aip.AD2,
  urls: aip.AD2.map(([icao]) => aip.aeroPageUrl(base, icao)),
  dir: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2011-26_2026_10_29", "EPKK"),
  slash: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/", "EPKK"),
  spaces: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipifr/AIRAC AMDT 11-26_2026_10_29/index-v2.html?x=1#top", "EPGD"),
  bad: [undefined, "", "nie adres", null].map((b) => aip.aeroPageUrl(b, "EPWA")),
  args: ["EPWA", "epkk", " EPGD ", "", undefined, "EPXX", "EPWA/x", "eaip", "EPWA/2-1"].map(aip.aeroOf),
  full: ["EPWA/2-1", " epzg/12-13 ", "EPWA/x", "EPXX/2-1", "eaip/2-1", "EPWA/123-1", "EPSY/08-1", "EPKK/"].map(aip.adcivArg),
  section: aip.chartsSectionUrl("https://x.test/eAIP/AD%202%20EPZG%201-en-GB.html", "EPZG"),
  sectionEmpty: aip.chartsSectionUrl("", "EPZG"),
  kinds: aip.kindButtons(charts, "IAC"),
  kindsAll: aip.kindButtons(charts, ""),
  rows: aip.chartRows(charts, { kind: "IAC", selected: "12-1" }),
  rowsAll: aip.chartRows(charts),
  rowsNone: aip.chartRows(charts, { kind: "SID" }),
  kindIds: aip.KINDS.map(([k]) => k),
  // filtr po wyborze mapy spoza filtra: [filtr, id mapy]
  picks: [["IAC", "12-3"], ["IAC", "2-1"], ["", "2-1"], ["STAR", ""], ["ADC", ""], ["ADC", "99-9"], ["STAR", "10-1"], ["SID", "12-1"]]
    .map(([k, id]) => aip.kindAfterPick(charts, k, id)),
  pickEmpty: aip.kindAfterPick([], "ADC", "2-1"),
  tips: charts.map(aip.chartTip),
  // 0.13.1: AD MIL i AD VFR
  mil: aip.AD_MIL,
  vfr: aip.AD_VFR,
  pkgs: Object.fromEntries(Object.entries(aip.AIP).map(([k, p]) => [k, { link: p.link, api: p.api, part: p.part,
    charts: p.charts, text: p.text, n: p.list.length, whole: p.whole }])),
  lists: [aip.AIP.adciv.list === aip.AD2, aip.AIP.admil.list === aip.AD_MIL, aip.AIP.advfr.list === aip.AD_VFR],
  vfrPage: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipvfr/AIRAC%20AMDT%20VFR%2011-26_2026_10_29/index-v2.html", "EPBC", 4),
  milPage: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29", "EPKS", 4),
  vfrSection: aip.chartsSectionUrl("https://x.test/eAIP/AD%204%20EPBC%201-en-GB.html", "EPBC", "4.13"),
  milArgs: ["epks/12-5", "EPKS", "EPWA", "EPBC", " EPDE/2-1 ", ""].map((a) => aip.aipArg(aip.AD_MIL, a)),
  vfrArgs: [" EPBC ", "epzw/3-1", "EPKS", "EPWA/2-1"].map((a) => aip.aipArg(aip.AD_VFR, a)),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    src = (FRONTEND / "js" / "tabs" / "aip.js").read_text("utf-8")
    (d / "aip.mjs").write_text(src.replace('"../api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "aip.mjs").as_uri(), BASE],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_aerodrome_list(js):
    icaos = [i for i, _ in js["ad2"]]
    assert icaos == ["EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY", "EPWA",
                     "EPWR", "EPZG"]
    # 15 lotnisk AD 2 (do 0.12.6 te same co w zakładce STRIP, usuniętej w 0.13.0); każde z nazwą do dymka
    assert all(name for _, name in js["ad2"])
    assert dict(js["ad2"])["EPWA"] == "LOTNISKO CHOPINA W WARSZAWIE"


def test_aerodrome_page_urls(js):
    pkg = "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/"
    assert js["urls"][12] == pkg + "eAIP/AD%202%20EPWA%201-en-GB.html"
    assert all(u == f"{pkg}eAIP/AD%202%20{i}%201-en-GB.html" for u, (i, _) in zip(js["urls"], js["ad2"]))
    # katalog poprawki bez "/" na końcu (wpis w .env) i ze "/": ten sam wynik; spacje → %20, bez ?query i #
    amdt11 = "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/eAIP/AD%202%20EPKK%201-en-GB.html"
    assert js["dir"] == amdt11 and js["slash"] == amdt11
    assert js["spaces"] == "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/eAIP/AD%202%20EPGD%201-en-GB.html"
    assert js["bad"] == ["", "", "", ""]


def test_address_arg(js):
    # lotnisko z adresu; mapa za "/" nie zmienia lotniska ("EPWA/x" → EPWA, zła mapa = pierwsza na liście)
    assert js["args"] == ["EPWA", "EPKK", "EPGD", "", "", "", "EPWA", "", "EPWA"]
    assert js["full"] == [{"icao": "EPWA", "chart": "2-1"}, {"icao": "EPZG", "chart": "12-13"}, {"icao": "EPWA", "chart": ""},
                          {"icao": "", "chart": ""}, {"icao": "", "chart": ""}, {"icao": "EPWA", "chart": ""},
                          {"icao": "EPSY", "chart": "08-1"}, {"icao": "EPKK", "chart": ""}]


def test_chart_list(js):
    # sekcja AD 2.24 na stronie AD 2 (fragment tekstowy) dla przycisku przy braku listy
    assert js["section"] == "https://x.test/eAIP/AD%202%20EPZG%201-en-GB.html#:~:text=EPZG%20AD%202.24"
    assert js["sectionEmpty"] == ""
    # 0.12.6: mapa lotniska (ADC) i mapy postojowe (APDC) osobno
    assert js["kindIds"] == ["ADC", "APDC", "SID", "STAR", "IAC", "VFR", "OBST", "OTHER"]
    # przyciski rodzajów: ALL z liczbą wszystkich map i tylko rodzaje obecne na liście, z liczbą map; wybrany ma "on"
    kinds = re.findall(r'data-kind="([A-Z]*)"[^>]*>([A-Z]+) <small>(\d+)</small>', js["kinds"])
    assert kinds == [("", "ALL", "4"), ("ADC", "ADC", "1"), ("STAR", "STAR", "1"), ("IAC", "IAC", "2")]
    assert re.findall(r'class="gbtn chl-kind on" data-kind="([A-Z]*)"', js["kinds"]) == ["IAC"]
    assert re.findall(r'class="gbtn chl-kind on" data-kind="([A-Z]*)"', js["kindsAll"]) == [""]
    assert 'title="Instrument approach charts"' in js["kinds"]
    # wiersze: filtr rodzaju, zaznaczona mapa, PDF w nowej karcie, tytuł escapowany
    assert re.findall(r'data-chart="([\d-]+)"', js["rows"]) == ["12-1", "12-3"]
    assert re.findall(r'class="chl-row on" data-chart="([\d-]+)"', js["rows"]) == ["12-1"]
    assert re.findall(r'data-chart="([\d-]+)"', js["rowsAll"]) == ["2-1", "12-1", "12-3", "10-1"]
    assert 'class="chl-row on"' not in js["rowsAll"]
    assert '<a class="chl-pdf" href="https://x.test/AD_2_EPZG_12-1.pdf" target="_blank" rel="noopener"' in js["rows"]
    assert "APPROACH &lt;b&gt;&quot;x&quot; &amp; y&lt;/b&gt;" in js["rows"] and "<b>" not in js["rows"]
    assert js["rowsNone"] == '<p class="hint">No charts of this type.</p>'
    # 0.12.6: na liście krótka nazwa mapy, pełny tytuł w dymku (bez pełnego tytułu: nazwa)
    assert '<span class="chl-tt">RWY 24 ILS Z</span>' in js["rows"]
    assert 'title="AD 2 EPZG 12-1: INSTRUMENT APPROACH CHART - ICAO (ILS z) RWY 24"' in js["rows"]
    assert js["tips"] == ["AD 2 EPZG 2-1: AERODROME CHART - ICAO", "AD 2 EPZG 12-1: INSTRUMENT APPROACH CHART - ICAO (ILS z) RWY 24",
                          'AD 2 EPZG 12-3: APPROACH <b>"x" & y</b>', "AD 2 EPZG 10-1: STANDARD ARRIVAL CHART"]


def test_tabs_wiring():
    # AD CIV / AD MIL / AD VFR (0.13.1): jedna fabryka, podmenu (subtabs) z eAIP, odstępem i lotniskami pakietu, adres
    # przez activate + remember zakładki
    for tab in ("adciv", "admil", "advfr"):
        assert f'export const {tab} = aipTab("{tab}");' in AIP
    assert "const frame = " not in AIP and "frame(" not in AIP
    assert 'remember(tab, cur === EAIP ? "" : charts?.current() ? `${cur}/${charts.current()}` : cur);' in AIP
    assert '{ id: EAIP, label: "eAIP", fill: true, render: page(base) },' in AIP and "{ sep: true }," in AIP
    assert "...pkg.list.map(([icao]) => ({ id: icao, label: icao, fill: true, render: chartsPage(icao) }))," in AIP
    assert "const base = ctx.config.links[pkg.link];" in AIP and "const a = aipArg(pkg.list, arg);" in AIP
    # 0.12.5: przycisk lotniska = lista map z backendu (0.13.1: z pakietem w adresie), nie strona AD 2 z opisem
    assert "render: chartsPage(icao)" in AIP and "render: page(aeroPageUrl(base, icao))" not in AIP
    assert "api(`/api/docs/charts/${pkg.api}/${icao}`)" in AIP and "onPick: (id) => remember(tab, `${icao}/${id}`)" in AIP
    assert "const text = aeroPageUrl(base, icao, pkg.part);" in AIP and ">AD ${pkg.part} TEXT \\u2197</a>" in AIP
    # pamięć list map osobno dla pakietu (ten sam kod lotniska w dwóch pakietach nie dzieli listy)
    assert "const key = `${pkg.api}/${icao}`;" in AIP and "cache.get(key)" in AIP and "cache.get(icao)" not in AIP
    assert "${esc(icao)} \\u00b7 CHARTS</h4>" in AIP
    # długie podmenu AD VFR (69 lotnisk): wybrany przycisk przewijany do widoku przy każdym activate
    act = AIP[AIP.index("activate(arg) {"):AIP.index("export const adciv = ")]
    assert "          reveal();\n" in act and 'b?.scrollIntoView({ block: "nearest" });' in AIP
    css = (FRONTEND / "css" / "coordination.css").read_text("utf-8")
    assert ".chl-row {" in css and ".chl-list {" in css
    assert ('.view:is([data-tab="adciv"], [data-tab="admil"], [data-tab="advfr"]) :is(.btn, .gbtn, .field, .ms-card, '
            '.ms-card h4, .chl-row,\n  .chl-kd) { border-radius: 0; }') in css
    # inop.js (i do 0.13.0 phraseology.js) biorą pasek nad ramką stąd
    assert "export function embedBar(pane)" in AIP


def test_packages(js):
    """0.13.1: tabela AIP: link w /api/config, pakiet w adresie listy map, część AIP, sekcja map, lista lotnisk."""
    assert js["pkgs"] == {
        "adciv": {"link": "aip_ifr", "api": "ifr", "part": 2, "charts": "2.24", "text": "2.1–AD 2.25", "n": 15,
                  "whole": "The whole eAIP IFR (table of contents)"},
        "admil": {"link": "aip_mil", "api": "mil", "part": 4, "charts": "4.24", "text": "4.1–AD 4.25", "n": 15,
                  "whole": "The whole eAIP MIL (table of contents)"},
        "advfr": {"link": "aip_vfr", "api": "vfr", "part": 4, "charts": "4.13", "text": "4.1–AD 4.13", "n": 69,
                  "whole": "The whole eAIP VFR (table of contents)"},
    }
    assert js["lists"] == [True, True, True]
    mil, vfr = dict(js["mil"]), dict(js["vfr"])
    assert list(mil) == sorted(mil) and list(vfr) == sorted(vfr) and len(mil) == 15 and len(vfr) == 69
    assert mil["EPKS"] == "POZNAŃ/Krzesiny" and mil["EPLY"] == "ŁĘCZYCA" and vfr["EPBC"] == "WARSZAWA - BABICE"
    assert vfr["EPJS"] == "JEŻÓW SUDECKI k/Jeleniej Góry" and all(mil.values()) and all(vfr.values())
    assert not set(mil) & set(vfr) and not (set(mil) | set(vfr)) & {i for i, _ in js["ad2"]}


def test_mil_vfr_pages_and_args(js):
    assert js["vfrPage"] == ("https://docs.pansa.pl/ais/eaipvfr/AIRAC%20AMDT%20VFR%2011-26_2026_10_29/eAIP/"
                             "AD%204%20EPBC%201-en-GB.html")
    assert js["milPage"] == ("https://docs.pansa.pl/ais/eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/eAIP/"
                             "AD%204%20EPKS%201-en-GB.html")
    assert js["vfrSection"] == "https://x.test/eAIP/AD%204%20EPBC%201-en-GB.html#:~:text=EPBC%20AD%204.13"
    none = {"icao": "", "chart": ""}
    # lotnisko z listy zakładki; lotnisko innego pakietu = cały eAIP
    assert js["milArgs"] == [{"icao": "EPKS", "chart": "12-5"}, {"icao": "EPKS", "chart": ""}, none, none,
                             {"icao": "EPDE", "chart": "2-1"}, none]
    assert js["vfrArgs"] == [{"icao": "EPBC", "chart": ""}, {"icao": "EPZW", "chart": "3-1"}, none, none]


def test_kind_filter_survives_redraw(js):
    """Runda 14 (przegląd): draw() wyłączał filtr, gdy wybrana mapa (domyślnie pierwsza, AD) była innego rodzaju, więc
    kliknięcie SID / STAR / IAC nic nie robiło. Filtr wyłącza tylko wybór mapy spoza filtra (adres, historia ←, pierwsze
    wczytanie z mapą w adresie) i tylko wtedy, gdy ta mapa jest ukryta filtrem."""
    assert js["picks"] == ["IAC", "", "", "", "ADC", "ADC", "STAR", ""]
    assert js["pickEmpty"] == "ADC"   # bez listy map filtr bez zmian
    draw = AIP[AIP.index("  const draw = () => {"):AIP.index('  el.addEventListener("click"')]
    assert "kind =" not in draw and "kindAfterPick" not in draw
    # przycisk filtra: sam filtr i rysowanie; pick() i pierwsze wczytanie: kindAfterPick dla wybranej mapy
    assert "if (k) { kind = k.dataset.kind; draw(); return; }" in AIP
    assert "const picked = (id) => { if (data?.charts?.length) kind = kindAfterPick(data.charts, kind, id); };" in AIP
    assert "picked(sel); draw(); };" in AIP and "pick(id) { sel = id; picked(id); draw(); }" in AIP
    assert AIP.count("kindAfterPick(") == 2   # definicja i picked()


def test_no_provenance_notes():
    """0.12.6 (issue #21): bez dopisków, skąd jest lista map (eAIP, PANSA, AIRAC), i bez nazwy serwera w komunikatach."""
    code = "\n".join(line for line in AIP.splitlines() if not line.lstrip().startswith("//"))
    for text in ("PANSA", "Charts from AD 2.24", "from eAIP", "in eAIP", "AIRAC amendment", "chl-src", "(AD 2.24)`"):
        assert text not in code, text
    assert "Loading the chart list\\u2026" in AIP and "Chart list unavailable: " in AIP
    assert ">AD ${pkg.charts} \\u2197</a>" in AIP and ">AD ${pkg.part} TEXT \\u2197</a>" in AIP
    assert 'title="Aerodrome charts section (AD ${pkg.charts})"' in AIP


def test_aip_js_ascii_code():
    """0.13.1: w kodzie tabs/aip.js (poza komentarzami w osobnych linijkach) tylko ASCII: nazwy lotnisk i znaki
    typograficzne jako \\u0141, \\u2013, \\u2197 itd."""
    bad = [line.strip() for line in AIP.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
    assert not bad, bad


# --- 0.13.1: zakładki z fabryki aipTab na atrapie api.js (subtabs, api, remember, h): który pakiet, który adres listy
# map, co trafia do historii, przewinięcie podmenu do wybranego lotniska, pamięć list osobno dla pakietu
STUB_API = r"""
export const log = { api: [], remember: [], frames: [], pages: [], scrolled: [] };
export const RESP = {};
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const part = (sel) => ({ sel, innerHTML: "", hidden: true, href: "", title: "", textContent: "", attrs: {},
  getAttribute(k) { return this.attrs[k] ?? null; }, scrollIntoView() {} });
export function h(html) {
  const parts = {};
  return { html, querySelector: (s) => (parts[s] ??= part(s)), addEventListener() {} };
}
export function frameGo(frame, url) { frame.attrs.src = url; log.frames.push(url); return frame; }
export function iframeWithFallback(pane, url) { log.pages.push(url); }
export function remember(tab, arg) { log.remember.push([tab, arg]); }
export function api(url) { log.api.push(url); return Promise.resolve(RESP[url] ?? { page: "", charts: [], error: "HTTP 404" }); }
export const newPane = () => {
  const pane = { classes: [], classList: { add: (c) => pane.classes.push(c) }, append(el) { pane.el = el; },
    querySelector: () => ({ classList: { add() {} }, querySelectorAll: () => [] }) };
  return pane;
};
export function subtabs(root, tabs, opts = {}) {
  const buttons = tabs.filter((t) => !t.sep).map((t) => ({ dataset: { id: t.id }, title: "", active: false,
    scrollIntoView(o) { log.scrolled.push([t.id, o]); } }));
  const nav = { buttons, seps: tabs.filter((t) => t.sep).length, querySelectorAll: () => buttons,
    querySelector: (s) => (s === "button.active" ? buttons.find((b) => b.active) ?? null : s === "button" ? buttons[0] : null) };
  let cur = null, page = null;
  const show = (id) => {
    page?.destroy?.();
    const t = tabs.find((x) => !x.sep && x.id === id) || tabs[0];
    cur = t.id;
    buttons.forEach((b) => { b.active = b.dataset.id === cur; });
    root.pane = newPane();
    page = t.render(root.pane) || null;
  };
  root.nav = nav;
  root.arg = opts.arg;
  show(tabs[0].id);
  return { nav, pane: {}, show, current: () => cur };
}
"""

TAB_SCRIPT = r"""
const stub = await import(process.argv[2]);
const aip = await import(process.argv[3]);
const { log, RESP } = stub;
const tick = () => new Promise((r) => setTimeout(r, 0));
const reset = () => Object.values(log).forEach((a) => a.splice(0));
const chart = (pkg, icao, id, kind) => ({ id, page: `AD 4 ${icao} ${id}`, title: id, full: id, kind,
  url: `https://x.test/${pkg}/AD_4_${icao}_${id}.pdf` });
RESP["/api/docs/charts/mil/EPKS"] = { icao: "EPKS", page: "https://x.test/mil/eAIP/AD%204%20EPKS%201-en-GB.html",
  error: null, charts: [chart("mil", "EPKS", "2-1", "ADC"), chart("mil", "EPKS", "12-5", "IAC")] };
RESP["/api/docs/charts/mil/EPZZ"] = { icao: "EPZZ", page: "", error: null, charts: [chart("mil", "EPZZ", "2-1", "ADC")] };
RESP["/api/docs/charts/vfr/EPZZ"] = { icao: "EPZZ", page: "", error: null, charts: [chart("vfr", "EPZZ", "3-1", "VFR")] };
const links = { aip_ifr: "https://x.test/ifr/index-v2.html", aip_mil: "https://x.test/mil/index-v2.html",
  aip_vfr: "https://x.test/vfr/index-v2.html" };
const ctx = { config: { links } };
const el = (root) => root.pane.el;
const out = {};

// AD MIL: start na całym eAIP MIL, lotnisko i mapa z adresu, zmiana mapy, lotnisko spoza listy, powrót z pamięci
const mil = {};
const tm = aip.admil.mount(mil, ctx);
out.milStart = { pages: [...log.pages], ids: mil.nav.buttons.map((b) => b.dataset.id), seps: mil.nav.seps,
  titles: [mil.nav.buttons[0].title, mil.nav.buttons.find((b) => b.dataset.id === "EPKS").title],
  args: ["eaip", "EPKS"].map(mil.arg) };
reset();
tm.activate("epks/12-5");
await tick();
out.milEpks = { api: [...log.api], remember: [...log.remember], scrolled: [...log.scrolled], classes: mil.pane.classes,
  open: el(mil).querySelector(".chl-open").textContent, viewer: el(mil).querySelector(".viewer").attrs.src,
  html: el(mil).html };
reset();
tm.activate("EPKS/2-1");
out.milPick = { api: [...log.api], remember: [...log.remember], viewer: el(mil).querySelector(".viewer").attrs.src };
reset();
tm.activate("EPWA");
mil.nav.scrollTop = 500;
tm.activate("EPWA");
out.milForeign = { pages: [...log.pages], remember: [...log.remember], active: mil.nav.querySelector("button.active").dataset.id,
  top: mil.nav.scrollTop, scrolled: [...log.scrolled] };
reset();
tm.activate("EPKS");
out.milBack = { api: [...log.api], remember: [...log.remember], viewer: el(mil).querySelector(".viewer").attrs.src };
reset();
tm.activate("EPDE");
await tick();
out.milError = { api: [...log.api], list: el(mil).querySelector(".chl-list").innerHTML,
  viewer: el(mil).querySelector(".viewer").attrs.src };

// AD VFR: 69 lotnisk, lotnisko z dołu listy przewijane do widoku
reset();
const vfr = {};
const tv = aip.advfr.mount(vfr, ctx);
out.vfrStart = { pages: [...log.pages], n: vfr.nav.buttons.length, last: vfr.nav.buttons.at(-1).dataset.id };
reset();
tv.activate("EPZW");
await tick();
out.vfrEpzw = { api: [...log.api], remember: [...log.remember], scrolled: [...log.scrolled], html: el(vfr).html };

// AD CIV bez zmian w zachowaniu: lista z IFR, AD 2 TEXT
reset();
const civ = {};
const tc = aip.adciv.mount(civ, ctx);
out.civStart = { pages: [...log.pages], n: civ.nav.buttons.length };
tc.activate("EPWA/2-1");
out.civEpwa = { api: [...log.api], remember: [...log.remember], html: el(civ).html };

// pamięć list map: klucz pakiet/ICAO
reset();
const p = () => stub.newPane();
const a = p(), b = p(), c = p();
aip.mountCharts(a, { icao: "EPZZ", name: "x", base: links.aip_mil, pkg: aip.AIP.admil });
await tick();
aip.mountCharts(b, { icao: "EPZZ", name: "x", base: links.aip_vfr, pkg: aip.AIP.advfr });
await tick();
aip.mountCharts(c, { icao: "EPZZ", name: "x", base: links.aip_mil, pkg: aip.AIP.admil });
out.cache = { api: [...log.api], viewers: [a, b, c].map((x) => x.el.querySelector(".viewer").attrs.src) };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def tabs(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("tabs")
    (d / "api.mjs").write_text(STUB_API, "utf-8")
    (d / "aip.mjs").write_text(AIP.replace('"../api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(TAB_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "api.mjs").as_uri(), (d / "aip.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_admil_tab(tabs):
    start = tabs["milStart"]
    # start: cały eAIP MIL, potem odstęp i 15 lotnisk wojskowych w kolejności AD 1.3; dymki z nazwą lotniska
    assert start["pages"] == ["https://x.test/mil/index-v2.html"] and start["seps"] == 1
    assert start["ids"][:3] == ["eaip", "EPCE", "EPDA"] and len(start["ids"]) == 16 and start["ids"][-1] == "EPTM"
    assert start["titles"] == ["The whole eAIP MIL (table of contents)", "POZNAŃ/Krzesiny – charts"]
    assert start["args"] == ["", "EPKS"]
    # "#admil/EPKS/12-5": lista z /api/docs/charts/mil/EPKS, mapa 12-5 w podglądzie, krok historii zakładki admil
    e = tabs["milEpks"]
    assert e["api"] == ["/api/docs/charts/mil/EPKS"] and e["remember"] == [["admil", "EPKS/12-5"]]
    assert e["scrolled"] == [["EPKS", {"block": "nearest"}]] and e["classes"] == ["chl-pane"]
    assert e["open"] == "AD 4 EPKS 12-5 PDF ↗" and e["viewer"] == "https://x.test/mil/AD_4_EPKS_12-5.pdf"
    assert ">AD 4 TEXT ↗</a>" in e["html"] and "(AD 4.1–AD 4.25)" in e["html"] and "EPKS · CHARTS" in e["html"]
    assert 'href="https://x.test/mil/eAIP/AD%204%20EPKS%201-en-GB.html"' in e["html"] and "POZNAŃ/Krzesiny" in e["html"]
    # inna mapa tego lotniska: bez ponownego pobrania listy
    assert tabs["milPick"] == {"api": [], "remember": [["admil", "EPKS/2-1"]], "viewer": "https://x.test/mil/AD_4_EPKS_2-1.pdf"}
    # lotnisko spoza AD MIL (EPWA): cały eAIP MIL
    # (podmenu na samą górę: przycisk eAIP z odstępem nad nim; drugie activate tego samego adresu bez nowej strony)
    assert tabs["milForeign"] == {"pages": ["https://x.test/mil/index-v2.html"], "remember": [["admil", ""], ["admil", ""]],
                                  "active": "eaip", "top": 0, "scrolled": []}
    # powrót do EPKS: lista z pamięci, pierwsza mapa
    assert tabs["milBack"] == {"api": [], "remember": [["admil", "EPKS/2-1"]], "viewer": "https://x.test/mil/AD_4_EPKS_2-1.pdf"}
    # brak listy: komunikat, przycisk sekcji AD 4.24 i strona AD 4 lotniska w podglądzie
    err = tabs["milError"]
    page = "https://x.test/mil/eAIP/AD%204%20EPDE%201-en-GB.html"
    assert err["api"] == ["/api/docs/charts/mil/EPDE"] and err["viewer"] == page
    assert "Chart list unavailable: HTTP 404." in err["list"] and ">AD 4.24 ↗</a>" in err["list"]
    assert f'href="{page}#:~:text=EPDE%20AD%204.24"' in err["list"]


def test_advfr_tab(tabs):
    start = tabs["vfrStart"]
    assert start == {"pages": ["https://x.test/vfr/index-v2.html"], "n": 70, "last": "EPZW"}
    e = tabs["vfrEpzw"]
    # ostatnie z 69 lotnisk VFR: przycisk przewinięty do widoku, lista z /api/docs/charts/vfr/EPZW
    assert e["api"] == ["/api/docs/charts/vfr/EPZW"] and e["remember"] == [["advfr", "EPZW"]]
    assert e["scrolled"] == [["EPZW", {"block": "nearest"}]]
    assert ">AD 4 TEXT ↗</a>" in e["html"] and "(AD 4.1–AD 4.13)" in e["html"] and "ZAWISZYN" in e["html"]


def test_adciv_tab_unchanged(tabs):
    assert tabs["civStart"] == {"pages": ["https://x.test/ifr/index-v2.html"], "n": 16}
    e = tabs["civEpwa"]
    assert e["api"] == ["/api/docs/charts/ifr/EPWA"] and e["remember"] == [["adciv", "EPWA/2-1"]]
    assert ">AD 2 TEXT ↗</a>" in e["html"] and "(AD 2.1–AD 2.25)" in e["html"]
    assert 'href="https://x.test/ifr/eAIP/AD%202%20EPWA%201-en-GB.html"' in e["html"]


def test_chart_cache_per_package(tabs):
    # ten sam kod lotniska w AD MIL i AD VFR: dwie listy; drugie otwarcie w AD MIL z pamięci
    assert tabs["cache"] == {"api": ["/api/docs/charts/mil/EPZZ", "/api/docs/charts/vfr/EPZZ"],
                             "viewers": ["https://x.test/mil/AD_4_EPZZ_2-1.pdf", "https://x.test/vfr/AD_4_EPZZ_3-1.pdf",
                                         "https://x.test/mil/AD_4_EPZZ_2-1.pdf"]}
