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
const apiDocs = JSON.parse(readFileSync(process.argv[7], "utf-8"));   // GET /api/docs (OTHER › DOCS)
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
// kilka punktów naraz: pełne nazwy COP to alternatywy, reszta słów AND; przecinek i średnik też rozdzielają
const cnt = (q) => v({ q }).shown;
const multi = v({ q: "ALUKA BODLA EPKS" });
out.multi = {
  tokens: A.tokens(" aluka, bodla;epks  "),
  aluka: cnt("ALUKA"), bodla: cnt("BODLA"), both: cnt("ALUKA BODLA"), comma: cnt("ALUKA, BODLA"), semi: cnt("aluka;bodla"),
  tomti: cnt("TOMTI"), lagar: cnt("LAGAR"), tomtiLagar: cnt("TOMTI LAGAR"),
  withAd: [...multi.out, ...multi.in].map((r) => [r.cop_key, r.traffic]),
  withAdHit: [...multi.out, ...multi.in].every((r) => A.copHit(r, multi.toks)),
  part: cnt("ALUKA BOD"),   // "BOD" to nie pełna nazwa COP: AND jak dotąd
};
// karta dokumentu → POROZUMIENIA: stanowisko bez sektorów z tego LOA → wszystkie, z sektorami → zostaje; zawsze wiersze
const focus = (doc, pos) => A.docFocus(data, doc, { pos, typesOff: new Set(["LOA"]) });
const f1 = focus("loa-uklv", "EPWW_DBT_CTR"), f2 = focus("loa-edww-eduu", "EPWW_DBT_CTR");
const empty = [];
for (const d of data.documents.filter((x) => x.count)) {
  for (const p of ["", ...data.positions.map((x) => x.callsign)]) {
    const f = focus(d.id, p);
    const rows = [...A.view(data, { ...f }).out, ...A.view(data, { ...f }).in];
    if (!rows.length || !rows.every((r) => r.doc === d.id)) empty.push([d.id, p]);
  }
}
out.focus = { uklv: { ...f1, off: [...f1.off].sort(), typesOff: [...f1.typesOff] }, edww: { pos: f2.pos, q: f2.q, off: [...f2.off].length },
  empty };
const sum = (o) => A.sumHtml(all, { firs: data.firs, ...o });
out.sum = {
  none: sum({}), one: sum({ off: new Set(["EDWW"]) }), only: sum({ off: f1.off, pos: "EPWW_DBT_CTR" }),
  allOff: sum({ off: new Set(data.firs) }), types: sum({ typesOff: new Set(["LOA"]) }),
  evil: A.sumHtml({ ...all, toks: ["<B>"] }, { pos: "<i>", firs: ["<X>", "EDWW"], off: new Set(["<X>"]) }),
};
const unreg = { ...data.documents[0], id: "plik-loa-x", registered: false, count: 0, note: "no entry in data/seed/coordination.json",
  name: "LOA EPWW UMMV Minsk" };
out.cards = { unreg: A.docCardHtml(unreg, {}), reg: A.docCardHtml(data.documents[0], {}) };
out.coordFile = ["LOA/x.pdf", "lop/a/b.pdf", "LOA", "LOA/", "ICAO/doc.pdf", "", null, "LOAX/x.pdf"].map(docsMod.isCoordFile);
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
out.docFilter = [A.docFilter(data.documents, { fir: "EDUU" }).map((d) => d.id), A.docFilter(data.documents, { type: "LOP" }).map((d) => d.id),
  A.docFilter(data.documents, { type: "LOA" }).length, A.docFilter(data.documents, { fir: "EPWW", type: "LOP" }).length];
// DOKUMENTY: dokument i filtr (zmiana filtra / dokument z adresu, RADIO, znacznika w POROZUMIENIACH = reveal)
const sel = (ref, f, o) => { const r = A.docSelect(data.documents, ref, f, o); return [r.doc?.id ?? null, r.fir, r.type]; };
out.select = {
  keepIn: sel("loa-edmm", { type: "LOA" }), filterHides: sel("loa-edww-eduu", { type: "LOP" }),
  revealType: sel("loa-edww-eduu", { type: "LOP" }, { reveal: true }), emptyKeeps: sel("lop-twr-epwa", { fir: "EDWW", type: "LOP" }),
  revealFir: sel("lop-twr-epwa", { fir: "EDWW", type: "LOP" }, { reveal: true }),
  revealBoth: sel("lop-twr-epwa", { fir: "EDWW", type: "LOA" }, { reveal: true }), byFir: sel("EDUU", { type: "LOP" }, { reveal: true }),
  byFile: sel("LOP/LOP TWR/LOP TWR Łódź.pdf", { fir: "EPWW", type: "LOA" }, { reveal: true }),
  none: sel("", { type: "LOP" }), unknown: sel("XXXX", { fir: "EDMM" }), empty: A.docSelect([], "x").doc,
};
// LOP-y z data/docs/LOP/<podfolder>/ (spacje, polskie litery): karta, adres, stary adres OTHER › DOCS, OTHER › DOCS bez nich
const lopFile = "LOP/LOP TWR/LOP TWR Okęcie.pdf";
const lop = data.documents.find((d) => d.file === lopFile);
out.lop = {
  card: A.docCardHtml(lop, { airac: data.current_airac }), acc: A.docCardHtml(data.documents.find((d) => d.id === "lop-acc-epww"), {}),
  refFile: ref(lopFile), refId: ref("lop-app-epkk"), arg: A.parseArg("docs/" + lopFile), docsArg: A.docsArg(lop.id),
  coordFile: [lopFile, "LOP/LOP APP/LOP APP Kraków.pdf", "lop/lop twr/x.pdf"].map(docsMod.isCoordFile),
  cards: data.documents.filter((d) => d.type === "LOP").map((d) => A.docCardHtml(d, {})),
  other: docsMod.otherDocs(apiDocs).map((d) => d.url),
};
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
def api_docs():
    with TestClient(main.app) as c:
        return c.get("/api/docs").json()


@pytest.fixture(scope="module")
def out(data, api_docs, tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    tmp = tmp_path_factory.mktemp("coordjs")
    d = tmp / "js"
    shutil.copytree(FRONTEND / "js", d)
    (d / "package.json").write_text('{"type": "module"}', "utf-8")
    (tmp / "data.json").write_text(json.dumps(data), "utf-8")
    (tmp / "cases.json").write_text(json.dumps(CASES), "utf-8")
    (tmp / "docs.json").write_text(json.dumps(api_docs), "utf-8")
    script = tmp / "run.mjs"
    script.write_text(SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "agreements.js").as_uri(), (d / "tabs" / "coordination.js").as_uri(),
                        (d / "docs.js").as_uri(), str(tmp / "data.json"), str(tmp / "cases.json"),
                        str(tmp / "docs.json")],
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


def test_multi_point_filter(out):
    """Kilka punktów naraz (issue #13: „wpisywać punkty by sprawdzić jakie ustalenia obowiązują”): pełne nazwy COP
    to alternatywy, bo wiersz ma jeden COP; pozostałe słowa zawężają (AND)."""
    m = out["multi"]
    assert m["tokens"] == ["ALUKA", "BODLA", "EPKS"]
    assert m["aluka"] == 10 and m["bodla"] == 11
    assert m["both"] == m["comma"] == m["semi"] == m["aluka"] + m["bodla"] == 21
    assert m["tomti"] and m["lagar"] and m["tomtiLagar"] == m["tomti"] + m["lagar"]
    assert m["withAd"] and all(c in ("ALUKA", "BODLA") and "EPKS" in t for c, t in m["withAd"]) and m["withAdHit"]
    assert m["part"] <= m["aluka"]


def test_document_card_to_agreements(out, data):
    """POROZUMIENIA › na karcie: tylko FIR-y dokumentu, bez filtra słów; stanowisko bez sektorów z tego LOA (DBT
    a Lwów) → wszystkie stanowiska. Dla każdego dokumentu i każdego stanowiska tabela ma wiersze tego dokumentu."""
    f = out["focus"]
    assert f["uklv"]["pos"] == "" and f["uklv"]["q"] == "" and f["uklv"]["typesOff"] == []
    assert f["uklv"]["off"] == sorted(x for x in data["firs"] if x != "UKLV")
    assert f["edww"]["pos"] == "EPWW_DBT_CTR" and f["edww"]["off"] == len(data["firs"]) - 2   # EDWW i EDUU włączone
    assert f["empty"] == []


def test_summary_says_what_is_hidden(out, data):
    s = out["sum"]
    assert "hidden" not in s["none"] and "only FIR" not in s["none"] and "all positions" in s["none"]
    assert "hidden FIRs <b>EDWW</b>" in s["one"]
    assert "only FIR <b>UKLV</b>" in s["only"] and "position <b>EPWW_DBT_CTR</b>" in s["only"]
    assert "all FIRs off" in s["allOff"]
    assert "hidden <b>LOA</b>" in s["types"]
    assert "<B>" not in s["evil"] and "<i>" not in s["evil"] and "<X>" not in s["evil"] and "&lt;X&gt;" in s["evil"]


def test_unregistered_card_and_old_doc_addresses(out):
    c = out["cards"]
    assert 'class="cd-new"' in c["unreg"] and "no entry in data/seed/coordination.json" in c["unreg"]
    assert "cd-agr" not in c["unreg"] and "cd-agr" in c["reg"] and "cd-new" not in c["reg"]
    # stary adres OTHER › DOCS z plikiem LOA/LOP → COORDINATION
    assert out["coordFile"] == [True, True, False, False, False, False, False, False]


def test_html(out):
    h = out["html"]
    assert 'class="cr-cop hit">ALUKA</b>' in h["hit"] and 'data-doc="loa-edww-eduu"' in h["hit"]
    assert "sector not specified in LOA" in h["unk"] and 'class="unk"' in h["unk"] and "J LOW" in h["unk"]
    ev = h["evil"]
    for bad in ("<b>X", "<i>t", "<script>", "<u>FL1", "<s>", "<q>"):
        assert bad not in ev, bad
    assert "cr-doc" not in ev   # nieznany dokument: bez przycisku
    assert "No transfers for these settings." in h["block"] and "COPN" in h["block"]
    assert "Transfer of control and communication" in h["notes"] and "XXXX" not in h["notes"]
    assert h["options"].startswith('<option value="">All</option>') and 'value="EPWW_DBT_CTR" selected' in h["options"]
    assert '<optgroup label="ACC / FIR">' in h["options"] and '<optgroup label="TWR / aerodrome">' in h["options"]
    assert 'class="cd-card on"' in h["card"] and "AIRAC 2602" in h["card"] and "PDF ↗" in h["card"]
    assert 'href="/files/docs/LOA/LOA%20EPWW%20EDWW%20Bremen,%20EDUU%20Karlsruhe%20(AIRAC%202602).pdf"' in h["card"]
    assert 'class="cd-tag airac cur"' in h["cardCur"] and 'class="cd-tag airac cur"' not in h["card"]
    assert "<img" not in h["cardEvil"] and "javascript:" not in h["cardEvil"] and "<b>" not in h["cardEvil"]
    assert "file missing" in h["cardMissing"] and "href=" not in h["cardMissing"]
    up, indiv = out["level"]
    assert 'class="cr-c"' in up and "<b>FL230-FL270</b>" in up and "↑ FL" not in up
    assert 'class="cr-indiv"' in indiv and "uzgodniony z EPWW" in indiv


def test_owner_shown(out):
    # B LOW z DBT online (127.025): kto teraz obsługuje sektor po stronie EPWW
    assert '<span class="cr-by" title="covered now by">DBT 127.025</span>' in out["html"]["owner"]
    assert "cr-by" not in out["html"]["ownerSel"]
    assert '<span class="cr-by" title="covered now by">DBT</span>' in out["html"]["ownerOther"]


def test_documents_and_other_docs(out, data):
    lops = [d["id"] for d in data["documents"] if d["type"] == "LOP"]
    assert len(lops) == 20 and out["docFilter"] == [["loa-edww-eduu"], lops, 7, 20]
    assert out["tab"] == "function"
    # OTHER › DOCS: bez LOA i LOP (są w COORDINATION)
    assert out["other"] == ["ICAO", "INNE"]


def test_tab_wiring():
    """tabs/coordination.js (DOM, bez testu w Node): karta → porozumienia przez docFocus bez zapisu przełączników FIR
    w localStorage; przewinięcie tabel we wpisie historii (← z DOKUMENTY wraca do tego samego wiersza)."""
    src = (FRONTEND / "js" / "tabs" / "coordination.js").read_text("utf-8")
    fn = src[src.index("function showAgreementsOf("):src.index("const refreshAll")]
    assert "docFocus(data, d.id," in fn and "lsSet(" not in fn
    assert 'stash("coordination", { top: main.scrollTop })' in src and 'const s = stashed("coordination");' in src
    assert "main.scrollTop = wantTop" in src
    assert "sumHtml(v, { pos: st.pos" in src and "data.errors" in src
    # 0.12.5 (issue #18): podmenu "LoA" i "DOCUMENTS" zamiast POROZUMIENIA i DOKUMENTY, przycisk na karcie "LoA ›"
    assert '{ id: "agreements", label: "LoA", fill: true,' in src and '{ id: "docs", label: "DOCUMENTS", fill: true,' in src
    assert "POROZUMIENIA" not in src and "DOKUMENTY" not in src
    agr = (FRONTEND / "js" / "agreements.js").read_text("utf-8")
    assert ">LoA ›</button>" in agr and "POROZUMIENIA" not in agr



def test_lop_cards_and_addresses(out, api_docs):
    """LOP-y z data/docs/LOP/LOP ACC|APP|TWR/ (spacje i polskie litery w ścieżce): karta z tagami LOP i EPWW, PDF pod
    adresem zakodowanym jak w przeglądarce, bez POROZUMIENIA › (0 przekazań); dokument z adresu po id i po pliku
    (stary adres OTHER › DOCS); OTHER › DOCS ich nie pokazuje."""
    lop = out["lop"]
    c = lop["card"]
    assert 'data-doc="lop-twr-epwa"' in c and ">LOP TWR Warszawa Chopin (EPWA)<" in c
    assert '<span class="cd-tag ty">LOP</span><span class="cd-tag fir">EPWW</span>' in c and "AIRAC" not in c
    assert '<div class="cd-pos"><span>EPWA TWR</span></div>' in c and "0 transfers" in c and "content in preparation" in c
    assert 'href="/files/docs/LOP/LOP%20TWR/LOP%20TWR%20Ok%C4%99cie.pdf"' in c and 'title="LOP/LOP TWR/LOP TWR Okęcie.pdf"' in c
    assert "file missing" not in c and "cd-new" not in c
    # 30 sektorów ACC: każda etykieta bez łamania w środku („B LOW”), łamanie tylko na „ · ”
    assert "<span>B LOW</span> · <span>B MID</span> · <span>B HIGH</span>" in lop["acc"] and "<span>T HIGH</span></div>" in lop["acc"]
    assert len(lop["cards"]) == 20 and not any("cd-agr" in x or "LoA ›" in x for x in lop["cards"])
    assert all('href="/files/docs/LOP/LOP%20' in x for x in lop["cards"])
    assert lop["refFile"] == "lop-twr-epwa" and lop["refId"] == "lop-app-epkk" and lop["docsArg"] == "docs/lop-twr-epwa"
    assert lop["arg"] == {"sub": "docs", "doc": "LOP/LOP TWR/LOP TWR Okęcie.pdf"}
    assert lop["coordFile"] == [True, True, True]
    # /api/docs: kategoria LOP także dla zagnieżdżonych (pierwszy folder), więc OTHER › DOCS je pomija
    nested = [d for d in api_docs if d["url"].startswith("/files/docs/LOP/")]
    assert len(nested) == 20 and {d["category"] for d in nested} == {"LOP"}
    assert lop["other"] and not any(u.startswith(("/files/docs/LOP/", "/files/docs/LOA/")) for u in lop["other"])


def test_doc_select(out):
    """Filtr „LOP” przy pokazanym LOA: pierwszy LOP z listy (obok nie zostaje PDF spoza listy, karta podświetlona);
    dokument z adresu, RADIO albo znacznika w POROZUMIENIACH: zdejmowany jest tylko filtr, który go ukrywa."""
    s = out["select"]
    assert s["keepIn"] == ["loa-edmm", "", "LOA"]
    assert s["filterHides"] == ["lop-acc-epww", "", "LOP"] and s["none"] == ["lop-acc-epww", "", "LOP"]
    assert s["revealType"] == ["loa-edww-eduu", "", ""] and s["byFir"] == ["loa-edww-eduu", "", ""]
    assert s["emptyKeeps"] == ["lop-twr-epwa", "EDWW", "LOP"]   # pusta lista: dokument zostaje
    assert s["revealFir"] == ["lop-twr-epwa", "", "LOP"] and s["revealBoth"] == ["lop-twr-epwa", "", ""]
    assert s["byFile"] == ["lop-twr-epll", "EPWW", ""]
    assert s["unknown"] == ["loa-edmm", "EDMM", ""] and s["empty"] is None
    src = (FRONTEND / "js" / "tabs" / "coordination.js").read_text("utf-8")
    fn = src[src.index("function mountDocuments("):src.index("function openDoc(")]
    assert "docSelect(data.documents, st.doc, { fir: st.dfir, type: st.dtype }, { reveal })" in fn
    assert "let reveal = true;" in fn and "reveal = false;" in fn and "reveal = true; refresh();" in fn
    assert 'remember("coordination", argOf(), { replace: true })' in fn
