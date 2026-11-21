"""0.14.0 (issue #28, MAP): dymek przestrzeni jako prosta podziałka wysokości (frontend/js/mapatc.js: altScale,
altScaleHtml) zamiast długich wierszy z rodzajem, nazwą, ID, zakresem, częstotliwością i "since", oraz plakietki CTR
FIR-u EPWW bez dublowania z etykietą obszaru stanowiska (ctrBadges). 0.14.2 (issue #35): wieża we własnym CTR / ATZ
bez etykiety obszaru, gdy jest już T na plakietce lotniska (towerBadges, towerOnBadge). Funkcje wykonane w Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"

NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const pt = await import(process.argv[3]);
const ctl = (cs, name, o = {}) => ({ key: cs, id: cs.replace(/_CTR$|_/g, (x) => (x === "_" ? " " : "")), name, ...o });
const DBF = ctl("EPWW_DBF_CTR", "Petr Trojan", { color: "#fd8c7b", freq: "133.180" });
const ALL = ctl("EPWW_ALL_CTR", "Petr Hruza", { color: "#4fcc92", freq: "125.450" });
const TWR = ctl("EPPO_TWR", "Jan Kowalski"), APP = ctl("EPWA_APP", "Anna Nowak"), DIR = ctl("EPWA_DIR", "Ewa Lis");
const out = {};
// obraz z issue: sektor D nad TMA Poznań N, ALL w środku (FL195-FL365), DBF nad i pod nim (TMA top-down)
out.ref = m.altScale([
  { lo: 36500, hi: 66000, size: 20, who: [DBF] },
  { lo: 19500, hi: 36500, size: 20, who: [ALL] },
  { lo: 9500, hi: 19500, size: 5, who: [DBF] },
]);
out.refHtml = m.altScaleHtml(out.ref);
out.refLv = m.altScaleHtml(out.ref, { lv: 30000 });
// sąsiednie pasma tego samego kontrolera razem (sektor D w dwóch warstwach i TMA pod nim: jedno pasmo FL660-FL095)
out.merged = m.altScale([
  { lo: 28500, hi: 66000, size: 20, who: [DBF] }, { lo: 19500, hi: 28500, size: 20, who: [DBF] },
  { lo: 9500, hi: 19500, size: 5, who: [DBF] },
]);
// nakładanie: mały CTR z TWR w dużym FIS bez obsady (TWR), TMA i FIS bez obsady (jedno pasmo "-"), ACC nad nimi
out.mixed = m.altScale([
  { lo: 0, hi: 2500, size: 1, who: [TWR] }, { lo: 0, hi: 9500, size: 100, who: [] },
  { lo: 6500, hi: 19500, size: 10, who: [] }, { lo: 19500, hi: 66000, size: 30, who: [DBF] },
]);
out.mixedHtml = m.altScaleHtml(out.mixed);
// przerwa: TMA od 6500 ft do FL095 i CTR do 2500 ft, między nimi nic (dwie granice bez pasma)
out.gap = m.altScale([{ lo: 6500, hi: 9500, size: 5, who: [APP] }, { lo: 0, hi: 2500, size: 1, who: [TWR] }]);
// dwie konfiguracje TMA w tym samym paśmie z różnymi stanowiskami: oba, od mniejszego obszaru; ten sam kontroler raz
out.two = m.altScale([{ lo: 2500, hi: 9500, size: 5, who: [DIR] }, { lo: 2500, hi: 9500, size: 3, who: [APP] },
  { lo: 2500, hi: 9500, size: 4, who: [APP] }]);
out.twoHtml = m.altScaleHtml(out.two);
// złe wycinki pominięte; pusta kolumna = pusty dymek
out.bad = m.altScale([{ lo: 5000, hi: 5000, who: [APP] }, { lo: NaN, hi: 9000, who: [APP] }, null, { lo: 0, hi: "x" }]);
out.badHtml = m.altScaleHtml(out.bad);
// escapowanie, symulacja, kolor tylko jako #hex, własny zapis granicy
out.esc = m.altScaleHtml(m.altScale([
  { lo: 0, hi: 3000, size: 1, who: [{ key: "X", id: "EP<X>", name: "A & <B>", color: "red;background:url(x)" }] },
  { lo: 3000, hi: 9500, size: 1, who: [{ key: "EPWW_N_CTR", id: "EPWW N", name: "simulation", sim: true, color: "#40f5ec" }] },
]), { alt: (ft) => `A${ft}` });

// plakietki CTR: bez kontrolerów z etykietą obszaru i bez tych na ich częstotliwości, każdy raz, tylko EPWW
const S = { callsign: "EPWW_S_CTR", frequency: "123.625", name: "Ola" };
const D = { callsign: "EPWW_DBF_CTR", frequency: "133.180", name: "Petr Trojan" };
const DI = { callsign: "EPWW_DBF_I_CTR", frequency: "133.180", name: "Instructor" };
const A = { callsign: "EPWW_ALL_CTR", frequency: "125.450", name: "Petr Hruza" };
const U = { callsign: "EUC-EN_CTR", frequency: "135.000", name: "Uir" };
const firs = { "EPWW-S": [S], "EPWW-DBF": [D, DI], "EPWW": [A, U], "EPWW-C": [U], "EPWW-D": [U], "EDWW-BOR": [{ callsign: "EDWW_BOR_CTR" }],
  "EPWW-N": [], "EPWW-J": "x" };
out.badges = m.ctrBadges(firs, [S, D]);
out.badgesAll = m.ctrBadges(firs, []);
out.badgesNone = [m.ctrBadges(null, [S]), m.ctrBadges({}, null), m.ctrBadges({ "EPWW-S": [S] }, [S, A, D])];
// symulowane ACC (sekcja Pozycje): plakietka CTR z zestawu aktywnego, a z etykietą obszaru już bez niej
const vatspy = { features: [{ properties: { id: "EPWW", prefixes: ["EPWW", "EPWW_ALL"] } }, { properties: { id: "EPWW-N", prefixes: ["EPWW_N"] } }] };
const act = pt.activeOnline({ positions: {}, firs: {}, controllers: [] }, { base: "online", ovr: { EPWW_N_CTR: true } },
  { posOf: (cs) => (cs === "EPWW_N_CTR" ? { frequency: "130.675" } : null), firOf: (cs) => pt.firsOf(cs, vatspy) });
out.simBadge = m.ctrBadges(act.firs, []);
out.simLabelled = m.ctrBadges(act.firs, [act.positions.EPWW_N_CTR]);

// 0.14.2 (issue #35): etykieta obszaru wieży tylko, gdy nie ma jej T na plakietce lotniska albo ma też TMA / CTA
const pr = (kind, group) => ({ kind, group });
const KK = { callsign: "EPKK_TWR", frequency: "118.100" };
const badged = m.towerBadges([{ icao: "EPKK", facilities: { TWR: [KK], GND: [{ callsign: "EPKK_GND" }] } },
  { icao: "ESGG", facilities: { TWR: [{ callsign: "ESGG_TWR" }] } }, { icao: "EPWA", facilities: { APP: [{ callsign: "EPWA_APP" }] } },
  null, { icao: "EPGD" }]);
const T = {};
T.badged = [...badged].sort();
T.badgedNone = [[...m.towerBadges(null)], [...m.towerBadges([])]];
T.kk = m.towerOnBadge(KK, [pr("ctr", "EPKK"), pr("ctr", "EPKK")], badged);
T.kkNoBadge = [m.towerOnBadge(KK, [pr("ctr", "EPKK")], new Set()), m.towerOnBadge(KK, [pr("ctr", "EPKK")], null)];
T.lbTma = m.towerOnBadge({ callsign: "EPLB_TWR" }, [pr("ctr", "EPLB"), pr("tma", "EPLB")], new Set(["EPLB_TWR"]));
T.llCta = m.towerOnBadge({ callsign: "EPLL_TWR" }, [pr("ctr", "EPLL"), pr("cta", "CTA03")], new Set(["EPLL_TWR"]));
T.baAtz = m.towerOnBadge({ callsign: "EPBA_R_TWR" }, [pr("atz", "EPBA")], new Set(["EPBA_R_TWR"]));
T.tra = m.towerOnBadge({ callsign: "EPKI_R_TWR" }, [pr("atz", "EPTR28")], new Set(["EPKI_R_TWR"]));
T.app = m.towerOnBadge({ callsign: "EPKK_APP" }, [pr("ctr", "EPKK")], new Set(["EPKK_APP"]));
T.other = m.towerOnBadge(KK, [pr("ctr", "EPKK")], new Set(["EPKT_TWR"]));
T.otherCtr = m.towerOnBadge({ callsign: "EPKT_TWR" }, [pr("ctr", "EPKK")], new Set(["EPKT_TWR"]));
T.foreign = m.towerOnBadge({ callsign: "ESGG_TWR" }, [pr("nb", "ESAA")], new Set(["ESGG_TWR"]));
T.empty = [m.towerOnBadge(null, [pr("ctr", "EPKK")], badged), m.towerOnBadge(KK, [], badged), m.towerOnBadge(KK, null, badged)];
// symulowana wieża (sekcja Pozycje): plakietka lotniska z zestawu aktywnego, więc bez etykiety; ukryta: bez plakietki
const posOf = (cs) => (cs === "EPKK_TWR" ? { frequency: "118.100" } : null);
const kkAd = { EPKK: { name: "x", lat: 50, lon: 19.8 } };
const simAct = pt.activeOnline({ positions: {}, firs: {}, controllers: [] }, { base: "online", ovr: { EPKK_TWR: true } }, { posOf });
const simBadged = m.towerBadges(pt.activeAtc({ airports: [] }, simAct, kkAd).airports);
T.sim = [...simBadged];
T.simOn = m.towerOnBadge(simAct.positions.EPKK_TWR, [pr("ctr", "EPKK")], simBadged);
const on = { positions: { EPKK_TWR: KK }, firs: {}, controllers: [KK] };
const atc = { airports: [{ icao: "EPKK", name: "x", lat: 50, lon: 19.8, facilities: { TWR: [KK] } }] };
T.live = [...m.towerBadges(pt.activeAtc(atc, pt.activeOnline(on, { base: "online", ovr: {} }, { posOf }), kkAd).airports)];
T.hidden = [...m.towerBadges(pt.activeAtc(atc, pt.activeOnline(on, { base: "online", ovr: { EPKK_TWR: false } }, { posOf }), kkAd).airports)];
out.tower = T;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("mapscale")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    for name in ("mapatc", "postree"):
        (d / f"{name}.mjs").write_text((JS / f"{name}.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "mapatc.mjs").as_uri(), (d / "postree.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _who(rows):
    """Wiersze podziałki skrócone: granica jako liczba, pasmo jako lista znaków (pusta = nieobsadzone)."""
    return [r["alt"] if "alt" in r else [w["key"] for w in r["who"]] for r in rows]


def _lines(html):
    """Linijki dymka jako tekst: granice i "stanowisko | imię i nazwisko"."""
    rows = re.findall(r"<tr class=\"([^\"]*)\">(.*?)</tr>", html)
    return [(cls, " | ".join(re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", body))) for cls, body in rows]


def test_reference_scale(js):
    """Obraz map3 z issue: FL660 / DBF / FL365 / ALL / FL195 / DBF / FL095, z częstotliwością, imieniem i nazwiskiem."""
    assert _who(js["ref"]) == [66000, ["EPWW_DBF_CTR"], 36500, ["EPWW_ALL_CTR"], 19500, ["EPWW_DBF_CTR"], 9500]
    assert _lines(js["refHtml"]) == [
        ("sc-a", "FL660"), ("sc-b", "EPWW DBF | 133.180 | Petr Trojan"), ("sc-a", "FL365"),
        ("sc-b", "EPWW ALL | 125.450 | Petr Hruza"), ("sc-a", "FL195"), ("sc-b", "EPWW DBF | 133.180 | Petr Trojan"),
        ("sc-a", "FL095")]
    html = js["refHtml"]
    assert html.startswith('<table class="as-scale">') and "border-left-color:#fd8c7b" in html
    # krótko: bez rodzaju i nazwy przestrzeni, "since", pogrubień (częstotliwość jest, jak w panelu Positions z obrazka)
    for gone in ("ACC", "TMA", "since", "<b", "<strong", "airspaces here", "top-down"):
        assert gone not in html, gone
    # rysowany poziom FL300: wyróżnione pasmo ALL (FL195-FL365)
    assert [c for c, _ in _lines(js["refLv"])] == ["sc-a", "sc-b", "sc-a", "sc-b at", "sc-a", "sc-b", "sc-a"]


def test_scale_merges_and_overlaps(js):
    assert _who(js["merged"]) == [66000, ["EPWW_DBF_CTR"], 9500]
    # TWR w CTR wygrywa z nieobsadzonym FIS; TMA i FIS bez obsady razem jako jedno pasmo "-"
    assert _who(js["mixed"]) == [66000, ["EPWW_DBF_CTR"], 19500, [], 2500, ["EPPO_TWR"], 0]
    assert _lines(js["mixedHtml"]) == [("sc-a", "FL660"), ("sc-b", "EPWW DBF | 133.180 | Petr Trojan"),
                                       ("sc-a", "FL195"), ("sc-b none", "– |  | "), ("sc-a", "2500 ft"),
                                       ("sc-b", "EPPO TWR |  | Jan Kowalski"),
                                       ("sc-a", "GND")]
    # przerwa: dwie granice bez pasma między nimi
    assert _who(js["gap"]) == [9500, ["EPWA_APP"], 6500, 2500, ["EPPO_TWR"], 0]
    # dwa stanowiska w jednym paśmie: oba (mniejszy obszar pierwszy), ten sam kontroler raz
    assert _who(js["two"]) == [9500, ["EPWA_APP", "EPWA_DIR"], 2500]
    assert [t for _, t in _lines(js["twoHtml"])] == ["FL095", "EPWA APP |  | Anna Nowak", "EPWA DIR |  | Ewa Lis", "2500 ft"]
    assert js["bad"] == [] and js["badHtml"] == ""


def test_scale_escaping(js):
    h = js["esc"]
    assert "EP&lt;X&gt;" in h and "A &amp; &lt;B&gt;" in h and "<X>" not in h and "<B>" not in h
    assert "url(x)" not in h and "border-left-color:#40f5ec" in h
    assert '<span class="pos-sim">SYM</span>' in h and "simulation" not in h
    assert [t for c, t in _lines(h) if c == "sc-a"] == ["A9500", "A3000", "A0"]


def test_ctr_badges(js):
    """Podwójna tabliczka (obraz map1: "EPWW S 123.625" i "CTR EPWW-S"): kontroler z etykietą obszaru nie ma plakietki
    CTR, uczeń i instruktor na jednej częstotliwości też nie; UIR raz (na całym FIR-ze); FIR-y spoza EPWW pomijane."""
    assert js["badges"] == {"EPWW": [{"callsign": "EPWW_ALL_CTR", "frequency": "125.450", "name": "Petr Hruza"},
                                     {"callsign": "EUC-EN_CTR", "frequency": "135.000", "name": "Uir"}]}
    # bez etykiet (obsada wyłączona, warstwa ACC wyłączona, inny poziom): plakietki jak dotąd, UIR tylko na EPWW
    assert sorted(js["badgesAll"]) == ["EPWW", "EPWW-DBF", "EPWW-S"]
    assert [c["callsign"] for c in js["badgesAll"]["EPWW-DBF"]] == ["EPWW_DBF_CTR", "EPWW_DBF_I_CTR"]
    assert js["badgesNone"] == [{}, {}, {}]
    # symulacja ACC: plakietka (zestaw aktywny), po narysowaniu etykiety obszaru już nie
    assert list(js["simBadge"]) == ["EPWW-N"] and js["simBadge"]["EPWW-N"][0]["sim"] is True
    assert js["simLabelled"] == {}


def test_map_uses_scale_and_badges():
    """map.js: dymek z altScale / altScaleHtml, plakietki CTR EPWW po etykietach obszarów (drawCtr w drawAirspace,
    ctrBadges z lblCtl), kontury FIR-ów bez plakietek; karta etykiety z innymi na tej samej częstotliwości."""
    src = (JS / "tabs" / "map.js").read_text("utf-8")
    assert 'import { altScale, altScaleHtml, ctrBadges, towerBadges, towerOnBadge } from "../mapatc.js";' in src
    draw = src.split("function drawAirspace() {")[1].split("\n  }\n")[0]
    assert draw.index("drawOwned(all)") < draw.rindex("drawCtr();") < draw.index("declutter();")
    assert "if (!slices) { drawCtr();" in draw
    assert "drawFirs(layers.firs, net.firs, {}, { panes })" in src
    assert "const on = ctrBadges(net.act?.firs, lblCtl);" in src
    assert "drawFirs(layers.firCtr, { features: feats }, on, { panes })" in src
    assert "[layers.atc, layers.firs, layers.firCtr].forEach" in src
    card = src.split("const ctlCard = (c) => {")[1].split("\n  };")[0]
    assert "x.frequency === c.frequency" in card and "same.map((x) => controllerRows(x))" in card


def test_tower_label_on_badge(js):
    """Issue #35: wieża we własnym CTR (EPKK_TWR) albo ATZ (EPBA_R_TWR) z T na plakietce lotniska bez etykiety obszaru;
    z TMA / CTA top-down, w cudzej TRA, bez plakietki (warstwa ATC wyłączona, ukryta) i APP etykieta zostaje."""
    t = js["tower"]
    # tylko TWR lotnisk EP z plakietki (ESGG, GND i APP pominięte)
    assert t["badged"] == ["EPKK_TWR"] and t["badgedNone"] == [[], []]
    assert t["kk"] is True and t["baAtz"] is True
    assert t["kkNoBadge"] == [False, False]
    assert t["lbTma"] is False and t["llCta"] is False and t["tra"] is False
    assert t["app"] is False and t["other"] is False and t["otherCtr"] is False and t["foreign"] is False
    assert t["empty"] == [False, False, False]
    # symulacja z sekcji Pozycje: plakietka z przerywaną ramką, więc też bez etykiety; ukryta wieża: bez plakietki
    assert t["sim"] == ["EPKK_TWR"] and t["simOn"] is True
    assert t["live"] == ["EPKK_TWR"] and t["hidden"] == []


def test_map_tower_label_wiring():
    """map.js: drawOwned pomija etykietę wieży z T na plakietce (po kolorze, przed lbl), drawAtc zbiera wieże
    z narysowanych plakietek i przerysowuje przestrzeń, gdy zestaw się zmienił; legenda."""
    src = (JS / "tabs" / "map.js").read_text("utf-8")
    own = src.split("function drawOwned(all) {")[1].split("\n  }\n")[0]
    assert "labelTwr = twrKey();" in own
    skip = "if (towerOnBadge(g.c, g.vs.map((v) => v.pr), badgeTwr)) return;"
    assert own.index("ownColor.set(g.c.callsign, g.color);") < own.index(skip) < own.index("lbl(at,")
    atc = src.split("function drawAtc() {")[1].split("\n  }\n")[0]
    assert "badgeTwr = towerBadges(shown);" in atc
    assert "if (net.useOnline && slices && twrKey() !== labelTwr) drawAirspace();" in atc
    assert atc.index("atcAds = new Set(") < atc.index("badgeTwr = towerBadges(shown);")
    assert atc.index("drawAds();") < atc.index("drawAirspace();")
    # deklaracje przed pierwszym użyciem (drawAtc wołane asynchronicznie, ale bez TDZ w mainMap)
    assert src.index("let badgeTwr = new Set(), labelTwr = \"\";") < src.index("function drawOwned(all) {")
    assert "a TWR in its own CTR only as T on the aerodrome badge" in src


def test_new_module_rules():
    """mapatc.js: polskie i inne znaki spoza ASCII tylko w komentarzach w osobnych linijkach; bez <b>; CSS podziałki
    bez pogrubień, zaokrągleń i cieni."""
    src = (JS / "mapatc.js").read_text("utf-8")
    bad = [line.strip() for line in src.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
    assert not bad, bad
    assert not re.search(r"<(b|strong)[\s>]", src)
    css = (JS.parent / "css" / "map.css").read_text("utf-8")
    scale = "\n".join(line for line in css.splitlines() if ".as-scale" in line)
    assert scale and "bold" not in scale and "radius" not in scale and "shadow" not in scale
    # przegląd: dymek jest ciemny także na jasnym podkładzie, więc SYM w podziałce zostaje jasnożółty
    assert ".map.light .as-scale .pos-sim { color: var(--yellow); border-color: var(--yellow); }" in css
