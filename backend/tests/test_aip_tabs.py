"""0.12.3 (issue #13): AD CIV z podmenu: "eAIP" (cała przeglądarka) i przycisk dla każdego lotniska AD 2, który otwiera
w tej samej ramce stronę AD 2 lotniska z tej samej poprawki AIRAC co skonfigurowany link (adres "#adciv/EPWA").
0.12.5 (issue #18): przycisk lotniska otwiera listę map lotniska (AD 2.24, GET /api/docs/charts/<ICAO>) z PDF-em obok
zamiast opisu tekstowego; adres "#adciv/EPWA/2-1" = wybrana mapa; strona AD 2 zostaje jako przycisk "AD 2 TEXT ↗"."""
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
    # AD CIV: podmenu (subtabs) z eAIP, odstępem i lotniskami, adres przez activate + remember; MIL i VFR bez zmian
    assert "export const adciv = {" in AIP
    assert 'remember("adciv", cur === EAIP ? "" : charts?.current() ? `${cur}/${charts.current()}` : cur);' in AIP
    assert '{ id: EAIP, label: "eAIP", fill: true, render: page(base) },' in AIP and "{ sep: true }," in AIP
    assert 'export const admil = frame("aip_mil");' in AIP and 'export const advfr = frame("aip_vfr");' in AIP
    assert "ctx.config.links.aip_ifr" in AIP
    # 0.12.5: przycisk lotniska = lista map (AD 2.24) z backendu, nie strona AD 2 z opisem tekstowym
    assert "render: chartsPage(icao)" in AIP and "render: page(aeroPageUrl(base, icao))" not in AIP
    assert "api(`/api/docs/charts/${icao}`)" in AIP and 'onPick: (id) => remember("adciv", `${icao}/${id}`)' in AIP
    assert "const text = aeroPageUrl(base, icao);" in AIP and ">AD 2 TEXT ↗</a>" in AIP
    assert "${esc(icao)} · CHARTS</h4>" in AIP
    css = (FRONTEND / "css" / "coordination.css").read_text("utf-8")
    assert ".chl-row {" in css and ".chl-list {" in css
    assert '.view[data-tab="adciv"] :is(.btn, .gbtn, .field, .ms-card, .ms-card h4, .chl-row, .chl-kd) { border-radius: 0; }' in css
    # inop.js i phraseology.js biorą pasek nad ramką stąd
    assert "export function embedBar(pane)" in AIP


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
    assert "Loading the chart list…" in AIP and "Chart list unavailable: " in AIP
    assert ">AD 2.24 ↗</a>" in AIP and ">AD 2 TEXT ↗</a>" in AIP
