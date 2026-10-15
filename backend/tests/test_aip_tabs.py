"""0.12.3 (issue #13): AD CIV z podmenu: "eAIP" (cała przeglądarka) i przycisk dla każdego lotniska AD 2, który otwiera
w tej samej ramce stronę AD 2 lotniska z tej samej poprawki AIRAC co skonfigurowany link (adres "#adciv/EPWA")."""
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
const strip = await import(process.argv[3]);
const base = process.argv[4];
console.log(JSON.stringify({
  ad2: aip.AD2,
  strip: strip.STRIP_AIRPORTS,
  urls: aip.AD2.map(([icao]) => aip.aeroPageUrl(base, icao)),
  dir: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2011-26_2026_10_29", "EPKK"),
  slash: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/", "EPKK"),
  spaces: aip.aeroPageUrl("https://docs.pansa.pl/ais/eaipifr/AIRAC AMDT 11-26_2026_10_29/index-v2.html?x=1#top", "EPGD"),
  bad: [undefined, "", "nie adres", null].map((b) => aip.aeroPageUrl(b, "EPWA")),
  args: ["EPWA", "epkk", " EPGD ", "", undefined, "EPXX", "EPWA/x", "eaip"].map(aip.aeroOf),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    for name in ("aip", "strip"):
        src = (FRONTEND / "js" / "tabs" / f"{name}.js").read_text("utf-8")
        (d / f"{name}.mjs").write_text(src.replace('"../api.js"', '"./api.mjs"').replace('"../strips.js"', '"./strips.mjs"'),
                                       "utf-8")
    (d / "strips.mjs").write_text("export const mountStrips = () => null;\n", "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "aip.mjs").as_uri(), (d / "strip.mjs").as_uri(), BASE],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_aerodrome_list(js):
    icaos = [i for i, _ in js["ad2"]]
    assert icaos == ["EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY", "EPWA",
                     "EPWR", "EPZG"]
    # te same 15 lotnisk AD 2 co w STRIP; każde z nazwą do dymka
    assert icaos == js["strip"] and all(name for _, name in js["ad2"])
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
    assert js["args"] == ["EPWA", "EPKK", "EPGD", "", "", "", "", ""]


def test_tabs_wiring():
    # AD CIV: podmenu (subtabs) z eAIP, odstępem i lotniskami, adres przez activate + remember; MIL i VFR bez zmian
    assert "export const adciv = {" in AIP and 'remember("adciv", argOf(sub.current()))' in AIP
    assert '{ id: EAIP, label: "eAIP", fill: true, render: page(base) },' in AIP and "{ sep: true }," in AIP
    assert 'export const admil = frame("aip_mil");' in AIP and 'export const advfr = frame("aip_vfr");' in AIP
    assert "ctx.config.links.aip_ifr" in AIP and re.search(r"render: page\(aeroPageUrl\(base, icao\)\)", AIP)
    # inop.js i phraseology.js biorą pasek nad ramką stąd
    assert "export function embedBar(pane)" in AIP
