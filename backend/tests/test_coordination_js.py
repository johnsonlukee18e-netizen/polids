"""COORDINATION we frontendzie (frontend/js/agreements.js, tabs/coordination.js, docs.js) w Node, bez DOM: adres,
dokument z adresu, filtr słowami, wybór stanowiska (ta sama kolejność przejmowania co backend), HTML z esc()."""
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import ROOT_DIR
from backend.app.services import coordination as cs

FRONTEND = ROOT_DIR / "frontend"

SCRIPT = r"""
import { readFileSync } from "node:fs";
const A = await import(process.argv[2]);
const tab = await import(process.argv[3]);
const docsMod = await import(process.argv[4]);
const data = JSON.parse(readFileSync(process.argv[5], "utf-8"));
const cases = JSON.parse(readFileSync(process.argv[6], "utf-8"));
const ids = (v) => [...v.out, ...v.in].map((r) => r.id);
const out = {};
out.args = {
  none: A.parseArg(""), agr: A.parseArg("agreements"), pos: A.parseArg("agreements/epww_dbt_ctr/ALUKA EPKS"),
  all: A.parseArg("agreements/ALL"), slash: A.parseArg("agreements/ALL/a/b"), doc: A.parseArg("docs/LOA/x y.pdf"),
  docs: A.parseArg("docs"), other: A.parseArg("phraseology"),
  a1: A.agreementsArg(undefined, ""), a2: A.agreementsArg("", ""), a3: A.agreementsArg("EPWW_D_CTR", " ALUKA "),
  a4: A.agreementsArg(undefined, "BODLA"), d1: A.docsArg(""), d2: A.docsArg("loa-edmm"),
};
const ref = (r) => A.docRef(data.documents, r)?.id ?? null;
out.refs = { id: ref("loa-edmm"), fir: ref("EDUU"), lower: ref("lkaa"), file: ref(data.documents[2].file), epww: ref("EPWW"),
  none: ref("XXXX"), empty: ref("") };
out.defpos = [A.defaultPosition(data.positions, "EPWW_DBT_CTR"), A.defaultPosition(data.positions, "epww_dbt_ctr"),
  A.defaultPosition(data.positions, "EPWA_TWR"), A.defaultPosition(data.positions, null)];
// kolejność przejmowania: te same wyniki co backend
out.owned = cases.map(([pos, online]) => A.ownedKeys(data.chains, pos, new Set(online)));
const v = (o) => A.view(data, o);
const all = v({});
const aluka = v({ q: "aluka" });
out.view = {
  total: all.total, shown: all.shown, out: all.out.length, in: all.in.length,
  aluka: ids(aluka), alukaFirst: [aluka.out[0]?.cop_key, aluka.in[0]?.cop_key],
  alukaHit: aluka.out.concat(aluka.in).filter((r) => A.copHit(r, aluka.toks)).map((r) => r.fir),
  arsapEppo: ids(v({ q: "ARSAP  EPPO" })),
  bod: ids(v({ q: "BOD" })).length, bodFirstHit: v({ q: "BOD" }).out.concat(v({ q: "BOD" }).in).some((r) => A.copHit(r, ["BOD"])),
  dbf: [...new Set(ids(v({ pos: "EPWW_DBF_CTR" })).map((i) => i.split("-")[0]))].sort(),
  dbfOnline: v({ pos: "EPWW_DBF_CTR", online: new Set(["EPWW_DBT_CTR"]) }).owned,
  noEdww: ids(v({ off: new Set(["EDWW"]) })).filter((i) => i.startsWith("EDWW")).length,
  noLoa: v({ typesOff: new Set(["LOA"]) }).shown,
};
const row = data.agreements.find((r) => r.fir === "LKAA");
const evil = { ...data.agreements[0], cop: "<b>X", cop_key: "", traffic: "<i>t</i>", adep: [], ades: [], conditions: "<script>",
  level_text: "<u>FL1</u>", level: 1, ep: "<s>", nb: "<q>", ep_unknown: false, doc: "nope" };
out.html = {
  hit: A.rowHtml(data.agreements.find((r) => r.cop_key === "ALUKA"), data, { toks: ["ALUKA"] }),
  unk: A.rowHtml(row, data, {}),
  owner: A.rowHtml(data.agreements.find((r) => r.ep === "B LOW"), data, { online: new Set(["EPWW_DBT_CTR"]), freq: () => "127.025" }),
  // wybrane stanowisko jest pierwsze w kolejności B LOW: sektor jego, bez podpisu N
  ownerSel: A.rowHtml(data.agreements.find((r) => r.ep === "B LOW"), data, { online: new Set(["EPWW_N_CTR"]), pos: "EPWW_DBT_CTR" }),
  ownerOther: A.rowHtml(data.agreements.find((r) => r.ep === "B LOW"), data, { online: new Set(["EPWW_DBT_CTR"]), pos: "EPWW_DBF_CTR" }),
  evil: A.rowHtml(evil, data, {}),
  block: A.blockHtml("in", [], data, {}),
  notes: A.notesHtml(data, ["EDWW", "XXXX"]),
  options: A.positionOptions(data.positions, "EPWW_DBT_CTR"),
  card: A.docCardHtml(data.documents[0], { selected: true, airac: data.current_airac }),
  cardCur: A.docCardHtml({ ...data.documents[0], current: true }, {}),
  cardEvil: A.docCardHtml({ ...data.documents[0], name: "<img src=x>", url: "javascript:alert(1)", positions: ["<b>"] }, {}),
  cardMissing: A.docCardHtml({ ...data.documents[0], exists: false }, {}),
};
out.level = [A.levelHtml({ level_text: "↑ FL230-FL270", level: 230, transfer: "C" }),
  A.levelHtml({ level_text: "uzgodniony z EPWW", level: null, transfer: null })];
out.docFilter = [A.docFilter(data.documents, { fir: "EDUU" }).map((d) => d.id), A.docFilter(data.documents, { type: "LOP" }).length];
out.tab = typeof tab.default.mount;
out.other = docsMod.otherDocs([{ category: "LOA" }, { category: "lop" }, { category: "ICAO" }, { category: "INNE" }]).map((d) => d.category);
console.log(JSON.stringify(out));
"""

CASES = [["EPWW_DBT_CTR", []], ["EPWW_DBT_CTR", ["EPWW_D_CTR"]], ["EPWW_DBT_CTR", ["EPWW_TM_CTR", "EPWW_D_CTR"]],
         ["EPWW_ALL_CTR", ["EPWW_N_CTR"]], ["EPSC_TWR", []], ["EPWW_N_CTR", ["EPSC_TWR", "EPWW_DBT_CTR"]],
         ["EPKK_APP", ["EPKK_E_APP"]], ["EPWA_APP", []]]


@pytest.fixture(scope="module")
def data():
    with TestClient(main.app) as c:
        return c.get("/api/coordination").json()


@pytest.fixture(scope="module")
def out(data, tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    tmp = tmp_path_factory.mktemp("coordjs")
    d = tmp / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    (tmp / "data.json").write_text(json.dumps(data), "utf-8")
    (tmp / "cases.json").write_text(json.dumps(CASES), "utf-8")
    script = tmp / "run.mjs"
    script.write_text(SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "agreements.js").as_uri(), (d / "tabs" / "coordination.js").as_uri(),
                        (d / "docs.js").as_uri(), str(tmp / "data.json"), str(tmp / "cases.json")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_address(out):
    a = out["args"]
    assert a["none"] == {} and a["other"] == {} and a["agr"] == {"sub": "agreements"}
    assert a["pos"] == {"sub": "agreements", "pos": "EPWW_DBT_CTR", "q": "ALUKA EPKS"}
    assert a["all"] == {"sub": "agreements", "pos": "", "q": ""} and a["slash"]["q"] == "a/b"
    assert a["doc"] == {"sub": "docs", "doc": "LOA/x y.pdf"} and a["docs"] == {"sub": "docs", "doc": ""}
    assert (a["a1"], a["a2"], a["a3"], a["a4"]) == ("agreements", "agreements/ALL", "agreements/EPWW_D_CTR/ALUKA",
                                                    "agreements/ALL/BODLA")
    assert (a["d1"], a["d2"]) == ("docs", "docs/loa-edmm")


def test_doc_ref_and_default_position(out, data):
    r = out["refs"]
    assert r["id"] == "loa-edmm" and r["fir"] == "loa-edww-eduu" and r["lower"] == "loa-lkaa"
    assert r["file"] == data["documents"][2]["id"]
    assert r["epww"] is None and r["none"] is None and r["empty"] is None
    assert out["defpos"] == ["EPWW_DBT_CTR", "EPWW_DBT_CTR", "", ""]


def test_ownership_same_as_backend(out, data):
    for (pos, online), got in zip(CASES, out["owned"]):
        assert got == cs.owned_keys(data["chains"], pos, set(online)), (pos, online)
    assert out["owned"][-1] == []   # stanowisko spoza kolejności


def test_view_filter_and_order(out, data):
    v = out["view"]
    assert v["total"] == v["shown"] == len(data["agreements"]) == v["out"] + v["in"]
    rows = {r["id"]: r for r in data["agreements"]}
    assert v["aluka"] and all("ALUKA" in json.dumps(rows[i]).upper() for i in v["aluka"])
    # COP wpisany w całości: te wiersze na górze obu tabel, z obu FIR-ów (EDWW i EDUU)
    assert v["alukaFirst"] == ["ALUKA", "ALUKA"] and set(v["alukaHit"]) == {"EDWW", "EDUU"}
    # słowa łączone przez AND
    assert v["arsapEppo"] and all(rows[i]["cop_key"] == "ARSAP" and "EPPO" in rows[i]["traffic"] for i in v["arsapEppo"])
    assert v["bod"] > 0 and not v["bodFirstHit"]   # część nazwy: filtruje, ale bez wyróżnienia
    # stanowisko DBF (samo: sektory B, D, F i TMA Szczecin): Bremen/Karlsruhe, München (D LOW), Szwecja;
    # bez Pragi, Bratysławy i Lwowa (J, R, T)
    assert v["dbf"] == ["EDMM", "EDUU", "EDWW", "ESAA"]
    assert "B LOW" not in v["dbfOnline"] and "F LOW" in v["dbfOnline"]
    assert v["noEdww"] == 0 and v["noLoa"] == 0


def test_html(out):
    h = out["html"]
    assert 'class="cr-cop hit">ALUKA</b>' in h["hit"] and 'data-doc="loa-edww-eduu"' in h["hit"]
    assert "sektor nieokreślony w LOA" in h["unk"] and 'class="unk"' in h["unk"] and "J LOW" in h["unk"]
    ev = h["evil"]
    for bad in ("<b>X", "<i>t", "<script>", "<u>FL1", "<s>", "<q>"):
        assert bad not in ev, bad
    assert "cr-doc" not in ev   # nieznany dokument: bez przycisku
    assert "Brak przekazań dla tych ustawień." in h["block"] and "COPN" in h["block"]
    assert "Przekazanie kontroli i łączności" in h["notes"] and "XXXX" not in h["notes"]
    assert h["options"].startswith('<option value="">Wszystkie</option>') and 'value="EPWW_DBT_CTR" selected' in h["options"]
    assert '<optgroup label="ACC / FIR">' in h["options"] and '<optgroup label="TWR / lotnisko">' in h["options"]
    assert 'class="cd-card on"' in h["card"] and "AIRAC 2602" in h["card"] and "PDF ↗" in h["card"]
    assert 'href="/files/docs/LOA/LOA%20EPWW%20EDWW%20Bremen,%20EDUU%20Karlsruhe%20(AIRAC%202602).pdf"' in h["card"]
    assert 'class="cd-tag airac cur"' in h["cardCur"] and 'class="cd-tag airac cur"' not in h["card"]
    assert "<img" not in h["cardEvil"] and "javascript:" not in h["cardEvil"] and "<b>" not in h["cardEvil"]
    assert "brak pliku" in h["cardMissing"] and "href=" not in h["cardMissing"]
    up, indiv = out["level"]
    assert 'class="cr-c"' in up and "<b>FL230-FL270</b>" in up and "↑ FL" not in up
    assert 'class="cr-indiv"' in indiv and "uzgodniony z EPWW" in indiv


def test_owner_shown(out):
    # B LOW z DBT online (127.025): kto teraz obsługuje sektor po stronie EPWW
    assert '<span class="cr-by" title="obsługuje teraz">DBT 127.025</span>' in out["html"]["owner"]
    assert "cr-by" not in out["html"]["ownerSel"]
    assert '<span class="cr-by" title="obsługuje teraz">DBT</span>' in out["html"]["ownerOther"]


def test_documents_and_other_docs(out):
    assert out["docFilter"] == [["loa-edww-eduu"], 0]
    assert out["tab"] == "function"
    # OTHER › DOCS: bez LOA i LOP (są w COORDINATION)
    assert out["other"] == ["ICAO", "INNE"]
