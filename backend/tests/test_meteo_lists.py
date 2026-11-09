"""METEO › METAR PL i TAF PL (0.13.2, issue #27): "METAR PL - wyświetlaj domyślnie wszystkie lotniska IFR, tak samo
w TAF. Nie dawaj wyszukiwarki w METAR i TAF PL, bo w realnym nie ma takich rzeczy". Obie listy zawsze pokazują wszystkie
lotniska IFR z listy AD CIV (AD2 w frontend/js/tabs/aip.js = eaip.AD2_AERODROMES), bez pola stacji i bez Show; zostają
COLOURED / MONO, odświeżanie co 2 min i czas pobrania. Dawny wybór stacji zapisany w przeglądarce (meteo.metar.pl,
meteo.taf.pl) nie zawęża listy i jest usuwany; lotnisko bez komunikatu zostaje na liście (NIL). METAR MIL, METAR INTL
i TAF INTL bez zmian: pole stacji (lista zapamiętana) i Show.

Prawdziwe wxList() z meteo.js i AD2 z aip.js uruchamiane w Node z atrapą api.js (h() oddaje napis HTML, querySelector
szuka klasy w tym napisie, localStorage w Map) i atrapą metarfmt.js (wxTable() oddaje kody stacji w kolejności)."""
import json
import os
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR
from backend.app.services.eaip import AD2_AERODROMES

FRONTEND = ROOT_DIR / "frontend"
METEO = (FRONTEND / "js" / "tabs" / "meteo.js").read_text("utf-8")
AIP = (FRONTEND / "js" / "tabs" / "aip.js").read_text("utf-8")
CSS = (FRONTEND / "css" / "metar.css").read_text("utf-8")
STYLE = (FRONTEND / "css" / "style.css").read_text("utf-8")

# wybór stacji zapisany przez 0.13.1 (pole w METAR PL i TAF PL) i lista METAR MIL, która ma zostać
STORED = {"meteo.metar.pl": "EPWA", "meteo.taf.pl": "EPKK EPWA", "meteo.metar.mil": "EPKS EPLK"}

API_STUB = r"""
// atrapa api.js dla meteo.js i aip.js
export const log = { api: [], set: [], del: [] };
export const store = new Map(Object.entries(JSON.parse(process.env.LS_INIT || "{}")));
export const ONLINE_EVENT = "polids-online";
export const BASEMAPS = {};
export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");
export const frameGo = () => {};
export const splitTaf = (raw) => [raw];
export const iframeWithFallback = () => {};
export const remember = () => {};
export const lsGet = (k) => (store.has(k) ? store.get(k) : null);
export const lsSet = (k, v) => { log.set.push([k, v]); store.set(k, v); };
export const lsDel = (k) => { log.del.push(k); store.delete(k); };
export const tabs = [];
export const subtabs = (root, list) => { tabs.push(...list); };
// serwer: każdy zapytany kod w odpowiedzi (odwrotnie, lista i tak jest sortowana), EPZG i LZIB bez komunikatu
export const api = async (url) => {
  log.api.push(url);
  const ids = decodeURIComponent(url.split("ids=")[1]).split(",");
  const nil = ["EPZG", "LZIB"];
  return ids.reverse().map((icao) => ({ icao, raw: nil.includes(icao) ? null : `${icao} 091130Z 24008KT` }));
};
export const h = (html) => ({ html });
"""

METARFMT_STUB = r"""
export const MODE_KEY = "meteo.wx.mode";
export const wxMode = (m) => m || "coloured";
export const wxTable = (kind, rows) => JSON.stringify({ kind, icao: rows.map((r) => r.icao),
  nil: rows.filter((r) => !r.raw).map((r) => r.icao) });
"""

NODE_SCRIPT = r"""
const api = await import(process.argv[2]);
const m = await import(process.argv[3]);
const timers = [];
globalThis.setInterval = (f, ms) => { timers.push({ f, ms }); return timers.length; };
globalThis.clearInterval = () => {};
globalThis.window = { addEventListener() {}, removeEventListener() {} };
// panel podzakładki: append() bierze napis HTML, querySelector(".x") oddaje element, gdy klasa x jest w napisie
const fakePane = () => {
  const els = new Map();
  const pane = { html: "", append(x) { this.html += x.html; } };
  pane.querySelector = (sel) => {
    if (els.has(sel)) return els.get(sel);
    const cls = sel.split(" ").pop().slice(1);
    const at = pane.html.search(new RegExp(`class="([^"]* )?${cls}( [^"]*)?"`));
    if (at < 0 || sel.includes(" ")) return null;
    const tag = pane.html.slice(at, pane.html.indexOf(">", at));
    const value = /value="([^"]*)"/.exec(tag)?.[1] ?? "";
    const el = { value, checked: /checked/.test(tag), innerHTML: "", textContent: "", on: {},
      classList: { toggle() {} }, querySelectorAll: () => [], addEventListener(t, f) { this.on[t] = f; } };
    els.set(sel, el);
    return el;
  };
  return pane;
};
const settle = () => new Promise((r) => setTimeout(r, 10));
m.default.mount({}, {});
const byId = Object.fromEntries(api.tabs.filter((t) => t.id).map((t) => [t.id, t]));
const run = async (id, act) => {
  const n0 = api.log.api.length, t0 = timers.length;
  const pane = fakePane();
  const page = byId[id].render(pane);
  await settle();
  if (act) { act(pane); await settle(); }
  // odświeżanie co 2 min (pole "refresh every 2 min" zaznaczone)
  const timer = timers[t0];
  timer.f();
  await settle();
  const $ = pane.querySelector;
  const out = { html: pane.html, urls: api.log.api.slice(n0).map((u) => decodeURIComponent(u)),
    list: JSON.parse($(".mtr-list").innerHTML), upd: $(".upd").textContent, ids: $(".ids")?.value ?? null,
    go: !!$(".go"), timer: timer.ms };
  page.destroy();
  return out;
};
const out = { PL_IFR: m.PL_IFR, ad2: (await import(process.argv[4])).AD2.map(([i]) => i) };
out.metarPl = await run("metar-pl");
out.tafPl = await run("taf-pl");
out.metarMil = await run("metar-mil");
// METAR INTL bez zapisanej listy: lista domyślna; zmiana pola i Show zapisuje nową listę (jak dotąd)
out.metarIntl = await run("metar-intl", (pane) => {
  pane.querySelector(".ids").value = "lkpr, eddb";
  pane.querySelector(".go").on.click();
});
out.tafIntl = await run("taf-intl");
out.log = { set: api.log.set, del: api.log.del };
out.store = Object.fromEntries(api.store);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("meteo_lists")
    (d / "api.mjs").write_text(API_STUB, "utf-8")
    (d / "solar.mjs").write_text("export const CIVIL_ALT = -6, SR_ALT = -0.833; export const latLonTxt = () => '', "
                                 "nightRings = () => [], subsolarPoint = () => ({}), sunElevation = () => 0, "
                                 "sunState = () => '', wrapLon = (x) => x;\n", "utf-8")
    (d / "qnhmap.mjs").write_text("export const qnhMap = () => ({ destroy() {} });\n", "utf-8")
    (d / "metarfmt.mjs").write_text(METARFMT_STUB, "utf-8")
    (d / "aip.mjs").write_text(AIP.replace('"../api.js"', '"./api.mjs"'), "utf-8")
    src = METEO
    for a, b in (("../api.js", "./api.mjs"), ("../solar.js", "./solar.mjs"), ("../qnhmap.js", "./qnhmap.mjs"),
                 ("../metarfmt.js", "./metarfmt.mjs"), ("./aip.js", "./aip.mjs")):
        src = src.replace(f'"{a}"', f'"{b}"')
    (d / "meteo.mjs").write_text(src, "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    args = [(d / n).as_uri() for n in ("api.mjs", "meteo.mjs", "aip.mjs")]
    r = subprocess.run([node, str(script), *args], capture_output=True, text=True, timeout=60, check=False,
                       env={**os.environ, "LS_INIT": json.dumps(STORED)})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


IFR = list(AD2_AERODROMES)


def test_pl_list_is_ad_civ():
    """Jedno źródło: lista AD CIV (AD2 w aip.js, sprawdzana z eaip.AD2_AERODROMES w test_eaip_links.py), bez własnej
    kopii kodów w meteo.js (0.13.1: PL_CIV)."""
    assert 'import { AD2 } from "./aip.js";' in METEO
    assert 'export const PL_IFR = AD2.map(([icao]) => icao).sort().join(" ");' in METEO
    assert "PL_CIV" not in METEO and "EPBY EPGD" not in METEO
    mount = METEO[METEO.index("export default {"):]
    assert ('{ id: "metar-pl", label: "METAR PL", render: wxList("metar", PL_IFR, "meteo.metar.pl", { fixed: true }) },'
            in mount)
    assert '{ id: "taf-pl", label: "TAF PL", render: wxList("taf", PL_IFR, "meteo.taf.pl", { fixed: true }) },' in mount
    # pozostałe trzy listy z polem stacji jak dotąd
    for line in ('wxList("metar", PL_MIL, "meteo.metar.mil") },', 'wxList("metar", INTL, "meteo.metar.intl") },',
                 'wxList("taf", INTL, "meteo.taf.intl") },'):
        assert line in mount, line
    assert len(IFR) == 15 and IFR == sorted(IFR)


def test_pl_ifr_from_aip(js):
    assert js["ad2"] == IFR
    assert js["PL_IFR"] == " ".join(IFR)


@pytest.mark.parametrize("key,kind,old", [("metarPl", "metar", "meteo.metar.pl"), ("tafPl", "taf", "meteo.taf.pl")])
def test_pl_lists_all_ifr_without_field(js, key, kind, old):
    """METAR PL i TAF PL: zapytanie zawsze o wszystkie 15 lotnisk IFR (także przy odświeżaniu co 2 min), mimo zapisanej
    w 0.13.1 listy jednej stacji; bez pola stacji i Show, pasek: COLOURED / MONO, odświeżanie i czas. Lotnisko bez
    komunikatu (EPZG) zostaje na liście (NIL w metarfmt.js wxRow)."""
    o = js[key]
    want = f"/api/meteo/{kind}?ids=" + ",".join(IFR)
    assert o["urls"] == [want, want] and o["timer"] == 120000
    assert o["list"] == {"kind": kind, "icao": IFR, "nil": ["EPZG"]}
    assert o["ids"] is None and o["go"] is False
    assert 'class="ids"' not in o["html"] and ">Show</button>" not in o["html"] and 'type="text"' not in o["html"]
    assert '<div class="mtr fixed">' in o["html"]
    bar = o["html"][o["html"].index('<div class="toolbar mtr-bar">'):o["html"].index('<div class="mtr-list">')]
    order = [bar.index(x) for x in (">COLOURED</button>", ">MONO</button>", "refresh every 2 min", 'class="hint upd"')]
    assert order == sorted(order) and 'class="auto" checked' in bar
    assert o["upd"].startswith("Updated ") and o["upd"].endswith("Z")
    # dawny wybór usunięty i nie zapisywany od nowa
    assert old in js["log"]["del"] and old not in js["store"]
    assert all(k != old for k, _ in js["log"]["set"])


def test_other_lists_keep_field(js):
    """METAR MIL, METAR INTL i TAF INTL bez zmian: pole z listą zapamiętaną (albo domyślną), Show, zapis listy."""
    mil = js["metarMil"]
    assert mil["urls"] == ["/api/meteo/metar?ids=EPKS,EPLK"] * 2 and mil["list"]["icao"] == ["EPKS", "EPLK"]
    assert 'class="ids" value="EPKS EPLK"' in mil["html"] and ">Show</button>" in mil["html"] and mil["go"] is True
    assert '<div class="mtr">' in mil["html"]
    intl = js["metarIntl"]
    default = "EDDB EDDF EDDM EKCH ESSA EVRA EYVI LKPR LOWW LZIB UKLL"
    assert f'class="ids" value="{default}"' in intl["html"]
    assert intl["urls"] == ["/api/meteo/metar?ids=" + default.replace(" ", ","), "/api/meteo/metar?ids=EDDB,LKPR",
                            "/api/meteo/metar?ids=EDDB,LKPR"]
    assert intl["ids"] == "EDDB LKPR" and js["store"]["meteo.metar.intl"] == "EDDB LKPR"
    taf = js["tafIntl"]
    assert taf["list"] == {"kind": "taf", "icao": default.split(), "nil": ["LZIB"]} and taf["go"] is True
    assert js["store"]["meteo.metar.mil"] == "EPKS EPLK" and "meteo.metar.mil" not in js["log"]["del"]
    assert sorted(js["log"]["del"]) == ["meteo.metar.pl", "meteo.taf.pl"]


def test_ls_del_helper():
    """lsDel w api.js jak lsGet / lsSet: localStorage w try (tryb prywatny)."""
    api = (FRONTEND / "js" / "api.js").read_text("utf-8")
    assert ("export function lsDel(key) {\n  try { localStorage.removeItem(key); } catch { /* tryb prywatny */ }\n}"
            in api)
    assert "lsDel, lsGet, lsSet" in METEO.splitlines()[0]


def test_fixed_bar_height_like_field():
    """Pasek bez pola ma wysokość pola stacji, więc tabela zaczyna się w pięciu listach na tej samej wysokości (w demie
    1600x900: pasek 28,2 px w każdej liście): wiersz pola 13px/1.4 (font body, pola dziedziczą font), padding 4 px
    i ramka 1 px, czyli 1,4em + 10 px."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)
    assert ".mtr.fixed .mtr-bar { min-height: calc(1.4em + 10px); }" in css
    style = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.DOTALL)
    assert "font: 13px/1.4 var(--sans);" in style
    assert "button, input, select, textarea { font: inherit; color: inherit; }" in style
    assert re.search(r"\.toolbar input, \.toolbar select, input\.field, textarea\.field, select\.field \{\s*"
                     r"background: #0d110d; color: var\(--text\); border: 1px solid #2f3a2f; padding: 4px 8px;", style)
    # bez pogrubień, cieni i zaokrągleń w nowej regule
    rule = css[css.index(".mtr.fixed .mtr-bar"):]
    rule = rule[:rule.index("}")]
    assert not re.search(r"font-weight|shadow|radius", rule)
