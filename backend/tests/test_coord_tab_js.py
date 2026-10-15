"""COORDINATION (frontend/js/tabs/coordination.js) zamontowana w Node: zastępczy DOM i router (remember = adres), reszta
api.js i agreements.js prawdziwa. Sprawdza zachowanie zakładki, nie tylko czyste funkcje:
- nieznany dokument w adresie przy otwartych DOKUMENTACH: zostaje pokazany dokument i adres wraca do niego (link do
  skopiowania zgadza się z ekranem); przed danymi i z POROZUMIEŃ: pierwszy dokument, adres za nim;
- stanowisko domyślne z wyboru tego okna (choiceGet, jak HOME i OVERVIEW), nie z localStorage, który mógł nadpisać
  wybór w drugim oknie PolIDS albo jest niedostępny (tryb prywatny)."""
import json
import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"

# api.js w teście: wszystko z prawdziwego (api.real.js), podmienione tylko DOM, podzakładki, router i zapytania
STUB = r"""
import { readFileSync } from "node:fs";
export * from "./api.real.js";
const DATA = JSON.parse(readFileSync(process.env.COORD_DATA, "utf-8"));
export const els = [];
let address = null;
export const addr = () => address;
export const setAddr = (a) => { address = a; };
export function remember(tab, arg) { if (tab === "coordination") address = String(arg ?? ""); }
export const stash = () => {};
export const stashed = () => undefined;
export const api = async (url) => { if (url === "/api/coordination") return DATA; throw new Error(`nieoczekiwane ${url}`); };
export const vatsimOnline = async () => ({ positions: {} });
export function frameGo(frame, url) { frame.attrs.src = url; return frame; }

function classes(init = []) {
  const s = new Set(init);
  return { contains: (c) => s.has(c), add: (c) => s.add(c), remove: (c) => s.delete(c),
    toggle: (c, on = !s.has(c)) => { if (on) s.add(c); else s.delete(c); return on; } };
}
// element: querySelector(s) daje dla każdego selektora ten sam element; innerHTML z kartami .cd-card → karty z
// dataset.doc i klasą "on" (tak jak rysuje je docCardHtml)
function el(html = "") {
  const parts = new Map();
  let inner = "", cards = [];
  const e = {
    html, attrs: {}, dataset: {}, value: "", textContent: "", hidden: false, open: false, scrollTop: 0, classList: classes(),
    get innerHTML() { return inner; },
    set innerHTML(v) {
      inner = String(v);
      cards = [...inner.matchAll(/<div class="cd-card( on)?" data-doc="([^"]*)"/g)].map((m) => {
        const c = el();
        c.dataset.doc = m[2];
        if (m[1]) c.classList.add("on");
        return c;
      });
    },
    querySelector(sel) {
      if (sel === ".cd-card.on") return cards.find((c) => c.classList.contains("on")) || null;
      if (!parts.has(sel)) parts.set(sel, el());
      return parts.get(sel);
    },
    querySelectorAll(sel) { return sel === ".cd-card" ? cards : []; },
    getAttribute(n) { return e.attrs[n] ?? null; },
    removeAttribute(n) { delete e.attrs[n]; },
    cloneNode() { return el(); },
    replaceWith() {}, append() {}, addEventListener() {}, scrollIntoView() {}, focus() {},
  };
  return e;
}
export function h(html) { const e = el(html); els.push(e); return e; }
// podzakładki: pierwsza od razu (jak subtabs w api.js), show() niszczy poprzednią
export function subtabs(root, tabs) {
  let cur = null, curId = null;
  const show = (id) => { cur?.destroy?.(); curId = id; cur = tabs.find((t) => t.id === id).render(el()) || null; };
  show(tabs.find((t) => !t.sep).id);
  return { show, current: () => curId };
}
"""

SCRIPT = r"""
const store = {};
globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
globalThis.setInterval = () => 0;   // odświeżanie VATSIM co minutę: nie w teście
const S = await import(process.argv[2]);
const tab = (await import(process.argv[3])).default;
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0)); };
const docsEl = () => [...S.els].reverse().find((e) => e.html.includes("cd-wrap"));
const agrEl = () => [...S.els].reverse().find((e) => e.html.includes("cr-wrap"));
const on = () => docsEl().querySelector(".cd-list").querySelectorAll(".cd-card").filter((c) => c.classList.contains("on"))
  .map((c) => c.dataset.doc);
const mount = () => { const t = tab.mount({ classList: { contains: () => true } }); S.setAddr(null); return t; };
// adres wpisany / z linku: arg z "#coordination/<arg>"; wynik: adres po activate() i wczytaniu oraz karty .on
const go = async (t, arg) => { S.setAddr(arg); t.activate(arg); await settle(); return { addr: S.addr(), on: on() }; };
const out = {};

let t = mount();
out.known = await go(t, "docs/loa-edmm");
out.unknown = await go(t, "docs/nonexistent-doc");
out.fir = await go(t, "docs/EDUU");
out.unknownAgain = await go(t, "docs/nonexistent-doc");
await go(t, "agreements");
out.fromAgreements = await go(t, "docs/nonexistent-doc");
t = mount();
out.beforeData = await go(t, "docs/nonexistent-doc");

// stanowisko: okno A wybrało EPKK_APP (choiceSet: pamięć okna i localStorage), potem okno B zapisało EPGD_APP
// w localStorage; COORDINATION okna A ma EPKK_APP
S.choiceSet(S.POS_KEY, "EPKK_APP");
store[S.POS_KEY] = "EPGD_APP";
t = mount();
await go(t, "agreements");
out.pos = { addr: S.addr(), select: agrEl().querySelector(".cr-pos").value, key: S.POS_KEY };
console.log(JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def data():
    with TestClient(main.app) as c:
        return c.get("/api/coordination").json()


@pytest.fixture(scope="module")
def out(data, tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    tmp = tmp_path_factory.mktemp("coordtab")
    d = tmp / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    (d / "api.js").rename(d / "api.real.js")
    (d / "api.js").write_text(STUB, "utf-8")
    (tmp / "data.json").write_text(json.dumps(data), "utf-8")
    script = tmp / "run.mjs"
    script.write_text(SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "api.js").as_uri(), (d / "tabs" / "coordination.js").as_uri()],
                       capture_output=True, text=True, timeout=60, env={**os.environ, "COORD_DATA": str(tmp / "data.json")})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_known_document_from_address(out, data):
    assert out["known"] == {"addr": "docs/loa-edmm", "on": ["loa-edmm"]}
    eduu = next(d["id"] for d in data["documents"] if "EDUU" in d["firs"])
    assert out["fir"] == {"addr": f"docs/{eduu}", "on": [eduu]}


def test_unknown_document_keeps_the_shown_one_and_its_address(out, data):
    # #coordination/docs/loa-edmm → #coordination/docs/nonexistent-doc: na ekranie dalej EDMM, adres też EDMM
    assert out["unknown"] == {"addr": "docs/loa-edmm", "on": ["loa-edmm"]}
    eduu = next(d["id"] for d in data["documents"] if "EDUU" in d["firs"])
    assert out["unknownAgain"] == {"addr": f"docs/{eduu}", "on": [eduu]}


def test_unknown_document_without_list_on_screen_opens_the_first(out, data):
    first = data["documents"][0]["id"]
    assert out["fromAgreements"] == {"addr": f"docs/{first}", "on": [first]}
    assert out["beforeData"] == {"addr": f"docs/{first}", "on": [first]}


def test_position_from_this_window_choice(out, data):
    assert out["pos"]["key"] == "overview.position"
    assert {"EPKK_APP", "EPGD_APP"} <= {p["callsign"] for p in data["positions"]}
    assert out["pos"]["select"] == "EPKK_APP" and out["pos"]["addr"] == "agreements/EPKK_APP"
