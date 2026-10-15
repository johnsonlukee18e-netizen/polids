"""METEO › SUN w przeglądarce (frontend/js/solar.js): położenie słońca, punkt podsłoneczny i granica dnia i nocy na mapie.
Te same wzory co backend (services/sun.py), więc wyniki porównujemy z nim; punkty podsłoneczne jak w test_sun.py
(wzorzec PyEphem 4.2.1)."""
import json
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from backend.app.config import ROOT_DIR
from backend.app.services import sun

SOLAR = (ROOT_DIR / "frontend" / "js" / "solar.js").read_text("utf-8")
TIMES = [datetime(2026, 6, 21, 8, 24), datetime(2026, 3, 20, 14, 46), datetime(2026, 11, 3, 12, 0),
         datetime(2026, 12, 21, 20, 50), datetime(2026, 10, 15, 22, 0), datetime(2026, 9, 23, 0, 5)]
MS = [int(t.replace(tzinfo=timezone.utc).timestamp() * 1000) for t in TIMES]

NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const MS = JSON.parse(process.argv[3]);
// punkt w wielokącie na płaszczyźnie lon/lat (jak wielokąt Leafleta przed rzutowaniem)
const inRing = (ring, lat, lon) => {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [yi, xi] = ring[i], [yj, xj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};
const inRings = (rings, lat, lon) => rings.some((r) => inRing(r, lat, lon));
// punkty kontrolne: [lat, lon] na całym świecie co 10° (bez samych biegunów)
const grid = [];
for (let lat = -80; lat <= 80; lat += 10) for (let lon = -180; lon < 180; lon += 10) grid.push([lat, lon]);
const out = MS.map((t) => {
  const s = m.subsolarPoint(t), p = m.solarPosition(t);
  const rings = { sr: m.nightRings(t, m.SR_ALT), civil: m.nightRings(t, m.CIVIL_ALT) };
  // wielokąt nocy zgadza się z wysokością słońca w każdym punkcie siatki (poza pasem 0,5° przy samej granicy)
  const wrong = {};
  for (const [k, alt] of [["sr", m.SR_ALT], ["civil", m.CIVIL_ALT]]) {
    wrong[k] = grid.filter(([la, lo]) => {
      const e = m.sunElevation(la, lo, t);
      return Math.abs(e - alt) > 0.5 && inRings(rings[k], la, lo) !== e < alt;
    }).length;
    // także po przewinięciu mapy o pełny obrót (kopie przesunięte o 360°)
    wrong[k] += grid.filter(([la, lo]) => {
      const e = m.sunElevation(la, lo, t);
      return Math.abs(e - alt) > 0.5 && (inRings(rings[k], la, lo + 360) !== e < alt || inRings(rings[k], la, lo - 360) !== e < alt);
    }).length;
  }
  const cap = m.capRing(-s.lat, m.wrapLon(s.lon + 180), 90 + m.SR_ALT);
  const dist = cap.ring.map(([la, lo]) => m.angDist(la, lo, -s.lat, s.lon + 180));
  return { lat: s.lat, lon: s.lon, decl: p.decl, eqt: p.eqt, wrong, pole: cap.pole,
           rings: [rings.sr.length, rings.civil.length], distMin: Math.min(...dist), distMax: Math.max(...dist),
           span: [Math.min(...rings.sr.flat().map((q) => q[1])), Math.max(...rings.sr.flat().map((q) => q[1]))] };
});
console.log(JSON.stringify({
  out,
  elev: m.sunElevation(52.1657, 20.9671, Date.UTC(2026, 9, 15, 12, 0)),
  states: [m.sunState(10), m.sunState(-0.5), m.sunState(-3), m.sunState(-6.5)],
  wrap: [m.wrapLon(190), m.wrapLon(-190), m.wrapLon(540), m.wrapLon(0)],
  txt: [m.latLonTxt(52.1657, 20.9671), m.latLonTxt(-33.393, -70.7858), m.latLonTxt(0.9999, 359.99)],
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("solar")
    (d / "solar.mjs").write_text(SOLAR, "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "solar.mjs").as_uri(), json.dumps(MS)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_subsolar_point(js):
    o = js["out"]
    # przesilenie czerwcowe: zwrotnik Raka; równonoc marcowa i wrześniowa: równik
    assert abs(o[0]["lat"] - 23.44) < 0.01 and abs(o[0]["lon"] - 54.45) < 0.05
    assert abs(o[1]["lat"]) < 0.01 and abs(o[1]["lon"] + 39.65) < 0.05
    assert abs(o[5]["lat"]) < 0.01 and abs(o[5]["lon"] - 176.89) < 0.05
    # 12:00 UTC: długość = 0° minus równanie czasu (w stopniach: min / 4)
    assert abs(o[2]["eqt"] - 16.49) < 0.1 and abs(o[2]["lon"] + o[2]["eqt"] / 4) < 1e-9
    assert abs(o[3]["lat"] + 23.437) < 0.01 and abs(o[3]["lon"] + 132.938) < 0.05


def test_same_as_backend(js):
    for t, o in zip(TIMES, js["out"]):
        lat, lon = sun.subsolar_point(t.replace(tzinfo=timezone.utc))
        decl, eqt = sun.solar_position(t.replace(tzinfo=timezone.utc))
        assert abs(o["lat"] - lat) < 1e-6 and abs(o["lon"] - lon) < 1e-6 and abs(o["eqt"] - eqt) < 1e-6, t
    assert abs(js["elev"] - sun.elevation(52.1657, 20.9671, datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc))) < 1e-6


def test_night_polygon(js):
    for t, o in zip(TIMES, js["out"]):
        # każdy punkt siatki co 10° po właściwej stronie granicy (noc / zmierzch cywilny), także w kopiach ±360°
        assert o["wrong"] == {"sr": 0, "civil": 0}, t
        # granica: okrąg 89,17° od punktu przeciwsłonecznego
        assert abs(o["distMin"] - 89.167) < 1e-6 and abs(o["distMax"] - 89.167) < 1e-6
        # cień sięga od -540° do 540° (mapa przewinięta za linię zmiany daty)
        assert o["span"][0] <= -540 and o["span"][1] >= 540
    # czerwiec i grudzień: noc obejmuje biegun (jeden pierścień bez szwów); przy równonocy pięć rozłącznych kopii
    assert js["out"][0]["pole"] == -1 and js["out"][3]["pole"] == 1 and js["out"][0]["rings"] == [1, 1]
    assert js["out"][1]["pole"] == 0 and js["out"][1]["rings"][0] == 5


def test_helpers(js):
    assert abs(js["elev"] - 25.674) < 0.02   # Warszawa 15.10 12:00 UTC, środek tarczy (PyEphem: 25,674°)
    # wschód / zachód przy -0,833° (górny brzeg z refrakcją), zmierzch cywilny do -6°
    assert js["states"] == ["day", "day", "civil", "night"]
    assert js["wrap"] == [-170, 170, 180 - 360, 0]
    assert js["txt"] == ["52°10′N 020°58′E", "33°24′S 070°47′W", "01°00′N 000°01′W"]
