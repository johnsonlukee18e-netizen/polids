"""MAP (runda 9): ATIS linijka po linijce (element text_atis = linijka) i dymki kontrolerów (plakietki, etykiety stanowisk)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.services.vatsim import airport_atc, controller_info, match_positions

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"
ATIS = ["EKCH ARR ATIS B", "0950Z", "EXPECT ILS APP", "RWY IN USE 22L", "TRL 65"]
FEED = [{"callsign": "EKCH_A_ATIS", "frequency": "122.755", "name": "Piet Burdorf", "cid": 1, "atis_code": "B", "text_atis": ATIS},
        {"callsign": "ESGG_GND", "frequency": "121.705", "name": "Johan Lindqvist", "cid": 2, "rating": 2,
         "logon_time": "2026-10-08T12:00:00Z", "text_atis": ["Goteborg Ground", "Charts: www.lfv.se"]},
        {"callsign": "ESSA_TWR", "frequency": "118.505", "name": "Sara Berg", "cid": 3, "text_atis": None}]


def test_backend_keeps_atis_lines():
    """Backend nie skleja linijek ATIS: /api/vatsim/atc i /api/vatsim/online podają tablicę jak w feedzie VATSIM."""
    assert controller_info(FEED[0])["text_atis"] == ATIS
    groups = airport_atc(FEED)
    assert groups["EKCH"]["ATIS"][0]["text_atis"] == ATIS and groups["EKCH"]["ATIS"][0]["atis_code"] == "B"
    # GND / TWR u sąsiadów też trafiają do plakietek lotnisk (ESGG G, ESSA T); brak tekstu zostaje None
    assert groups["ESGG"]["GND"][0]["logon_time"] == "2026-10-08T12:00:00Z" and groups["ESSA"]["TWR"][0]["text_atis"] is None
    station = type("S", (), {"callsign": "ESGG_GND", "prefix": "ESGG", "frequency": "121.705"})
    assert match_positions(FEED, [station])["ESGG_GND"]["text_atis"] == ["Goteborg Ground", "Charts: www.lfv.se"]


NODE_SCRIPT = r"""
globalThis.L = { CircleMarker: { extend: (o) => o } };  // airspace.js przy imporcie rozszerza L.CircleMarker
const api = await import(process.argv[2]);
const as = await import(process.argv[3]);
const feed = JSON.parse(process.argv[4]);
const out = {
  split: api.splitAtis(["A1  ", "", "B2\nC3", null, "  "]),
  none: api.splitAtis(null), str: api.splitAtis("X\r\nY"),
  html: api.atisHtml(["RWY <22L>", "TRL 65"]), empty: api.atisHtml(undefined),
  atis: as.atcRows([feed[0]], "ATIS", "A"),
  gnd: as.controllerRows(feed[1], { info: true }), gndPlain: as.controllerRows(feed[1]),
  twr: as.controllerRows(feed[2], { info: true }),
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    """Moduły frontendu wykonane w Node (kopie .mjs, żeby działały na każdej wersji Node bez package.json)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    (d / "airspace.mjs").write_text((JS / "airspace.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "api.mjs").as_uri(), (d / "airspace.mjs").as_uri(), json.dumps(FEED)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_split_atis(js):
    # każdy element tablicy osobno, własne znaki nowej linii też dzielą, puste linijki i null pomijamy
    assert js["split"] == ["A1", "B2", "C3"] and js["none"] == [] and js["str"] == ["X", "Y"]
    assert js["html"] == '<div class="atl">RWY &lt;22L&gt;</div><div class="atl">TRL 65</div>' and js["empty"] == ""


def test_atc_rows_atis_line_by_line(js):
    # dymek plakietki: INFO B, potem każda linijka ATIS w osobnym wierszu (a nie jeden ciągły tekst)
    assert "<b>INFO B</b>" in js["atis"]
    assert js["atis"].count('<div class="atl">') == len(ATIS) and '<div class="atl">RWY IN USE 22L</div>' in js["atis"]
    assert "EKCH ARR ATIS B 0950Z" not in js["atis"]


def test_controller_rows(js):
    # etykieta stanowiska: rodzaj ze znaku (ESGG_GND → G), dane kontrolera i jego opis linijka po linijce
    g = js["gnd"]
    assert 'class="ab ab-gnd">G<' in g and "ESGG_GND" in g and "121.705" in g and "Johan Lindqvist" in g and "S1" in g
    assert "od 12:00Z" in g and '<div class="atl">Charts: www.lfv.se</div>' in g and 'class="atis ci"' in g
    assert "Charts" not in js["gndPlain"]  # bez info: sam wiersz kontrolera
    assert 'class="ab ab-twr">T<' in js["twr"] and "atis ci" not in js["twr"]  # text_atis = null: bez wiersza opisu
