"""OTHER (0.12.6, issue #21): CHECKLIST jako podzakładka OTHER (adresy, przekierowania, checklisty w drugim podmenu),
nowa checklista TIPS FOR CONTROLLERS (punkty bez "...AKCJA", numerowane) i napisy bez źródeł danych w OTHER,
EMERGENCY i na stronie offline."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
SEED = ROOT_DIR / "data" / "seed"
TIPS = ["Frequency changes should be kept separate from other instructions",
        "Avoid issuing more than two instructions in one transmission",
        "If it is urgent – sound urgent",
        "Avoid distractions – especially the telephone",
        "If you are unsure, always check"]


def _code(path):
    """Kod bez komentarzy (/* */, // od początku linii albo po spacji), do sprawdzania napisów w interfejsie."""
    src = re.sub(r"/\*.*?\*/", "", path.read_text("utf-8"), flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M)


def test_tips_checklist_data():
    data = json.loads((SEED / "checklists.json").read_text("utf-8"))
    ids = [c["id"] for c in data["checklists"]]
    # TIPS na końcu podmenu, otwarcie stanowiska dalej pierwsze (i w AERODROME › OVERVIEW)
    assert ids == ["open-position", "close-position", "handover-takeover", "rwy-change", "controller-tips"]
    assert data["aerodrome"] == "open-position"
    tips = data["checklists"][-1]
    assert tips["label"] == "TIPS" and tips["title"] == "Tips for controllers" and tips["numbered"] is True
    # dokładnie pięć wskazówek dla kontrolerów, bez "...AKCJA", bez nagłówków, opisu i źródła
    assert tips["items"] == TIPS and not any("..." in t for t in tips["items"])
    assert set(tips) == {"id", "label", "title", "numbered", "items"}
    for c in data["checklists"]:
        assert set(c) <= {"id", "label", "title", "preDescription", "sections", "items", "numbered"}, c["id"]
        # tekst jest escapowany przy rysowaniu: encje HTML w pliku byłyby widoczne dosłownie ("&lt;station&gt;")
        assert not re.search(r"&(lt|gt|amp|quot);", json.dumps(c, ensure_ascii=False)), c["id"]


def test_emergency_without_sources():
    """Źródło procedur (dokument EUROCONTROL) tylko w uwadze dla opiekunów danych, nie w procedurach i nie na ekranie."""
    data = json.loads((SEED / "emergency.json").read_text("utf-8"))
    procs = data["procedures"]
    assert len(procs) == 18 and not any("source" in p for p in procs)
    assert "HRS/TSP-004-GUI-05" in data["_uwaga"]
    rcf = next(p for p in procs if p["id"] == "RCF")
    assert rcf["subtitle"] == "Radio Communication Failure – EUR Region"
    text = json.dumps(procs, ensure_ascii=False)
    assert "Doc 7030" not in text and "EUROCONTROL" not in text and "Annex" not in text
    em = _code(FRONTEND / "js" / "tabs" / "emergency.js")
    assert "Source" not in em and "p.source" not in em


# napisy z nazwą źródła albo opisem pochodzenia danych, których nie ma już w interfejsie tych plików
PROVENANCE = re.compile(r"Source:|source:|vatiris|minsulander|data/seed|Learning Zone|EUROCONTROL|VATSIM|vIFF|METAR,|"
                        r"\bfrom eAIP|PANSA|according to|based on", re.I)


@pytest.mark.parametrize("name", ["js/tabs/other.js", "js/checklist.js", "js/phraseology.js", "js/tabs/emergency.js",
                                  "offline.html", "index.html", "login.html"])
def test_no_provenance_in_ui(name):
    path = FRONTEND / name
    text = _code(path) if path.suffix == ".js" else re.sub(r"<!--.*?-->|/\*.*?\*/", "", path.read_text("utf-8"), flags=re.S)
    # importy modułów i podpięte arkusze / skrypty (np. viff.css) to nie napisy interfejsu
    text = "\n".join(line for line in text.splitlines()
                     if not line.startswith("import ") and not re.match(r"\s*<(link|script) ", line))
    assert not PROVENANCE.search(text), (name, PROVENANCE.search(text).group(0))


def test_lvp_tip_without_source():
    api = _code(FRONTEND / "js" / "api.js")
    body = api[api.index("export function lvpTip("):api.index("export function splitAtis(")]
    assert "source" not in body and "Source" not in body and "AIP does not provide" not in body


def test_other_files_in_english():
    """Napisy po angielsku; polskie znaki tylko w komentarzach w osobnych linijkach (nie po kodzie)."""
    polish = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
    for name in ("js/tabs/other.js", "js/checklist.js", "js/phraseology.js", "js/tabs/emergency.js", "sw.js"):
        src = (FRONTEND / name).read_text("utf-8")
        bad = [line.strip() for line in src.splitlines() if polish.search(line) and not line.strip().startswith("//")]
        assert not bad, (name, bad)


def test_offline_page_cache_bumped():
    """Nowa treść strony offline: nowa nazwa pamięci podręcznej, żeby przeglądarki nie pokazywały starej."""
    sw = (FRONTEND / "sw.js").read_text("utf-8")
    assert 'const CACHE = "offline-v4";' in sw   # 0.13.0: strona offline w Arialu bez pogrubień
    assert "(weather, traffic and flow data are live)" in (FRONTEND / "offline.html").read_text("utf-8")


NODE_SCRIPT = r"""
const chk = await import(process.argv[2]);
const other = (await import(process.argv[3])).default;
const log = globalThis.__log;

// --- checklistHtml: wskazówki (numerowane, bez kropek i akcji), punkty z akcją, pole INPUT, nagłówki, stan
const tips = { id: "t", items: ["If it is urgent – sound urgent", "Avoid <b>x</b> & <script>"], numbered: true };
const proc = { id: "p", sections: { 0: "Preparation" }, preDescription: "Plan <i>ahead</i>",
  items: ["Weather and NOTAMs...CHECK", "Last arrival...INPUT:NOTE", "Traffic in sector - <tt>.contactme</tt>",
    "Voice & text announcement: <i><station> now closed</i>...TRANSMIT"] };
const html = {
  tips: chk.checklistHtml(tips),
  tipsDone: chk.checklistHtml(tips, { 1: true }),
  proc: chk.checklistHtml(proc, { n1: "DLH1 \"x\"" }),
};

// --- OTHER: podzakładki i adresy (podmenu, DOCS, PHRASEOLOGY i CHECKLIST zastąpione atrapami)
const root = {};
const view = other.mount(root, { config: { links: {} } });
const sub = globalThis.__sub;
const steps = [];
const step = (name, fn) => { log.length = 0; fn(); steps.push({ name, sub: sub.current(), log: [...log],
  mounts: globalThis.__chk.map((c) => ({ start: c.opts.start, picks: c.picks, dead: c.dead })) }); };
step("first", () => view.activate("checklist/close-position"));
step("again", () => view.activate("checklist/rwy-change"));
step("click", () => globalThis.__chk.at(-1).opts.onPick("handover-takeover"));
step("fix", () => globalThis.__chk.at(-1).opts.onPick("open-position", true));
step("docs", () => view.activate("docs"));
step("menu", () => view.activate(undefined));
step("subtab", () => sub.click("checklist"));
step("bare", () => view.activate("checklist"));
step("phraseology", () => view.activate("phraseology"));
step("loa", () => view.activate("docs/LOA/x.pdf"));
console.log(JSON.stringify({ html, steps }));
"""

API_STUB = r"""
globalThis.__log = [];
export const navigate = (tab, arg) => globalThis.__log.push(["navigate", tab, arg]);
export const remember = (tab, arg, opts = {}) => globalThis.__log.push(["remember", tab, arg, !!opts.replace]);
// podmenu jak subtabs w api.js: pierwsza podzakładka od razu, show() niszczy poprzednią (destroy), klik = show + remember(arg)
export function subtabs(root, tabs, opts = {}) {
  let cur = null, id = null;
  const show = (x) => { cur?.destroy?.(); const t = tabs.find((y) => y.id === x) || tabs[0]; id = t.id; cur = t.render({}) || null; };
  const ctl = { show, current: () => id, click: (x) => { show(x); remember("other", opts.arg(id)); } };
  globalThis.__sub = ctl;
  show(tabs[0].id);
  return ctl;
}
"""
CHK_STUB = r"""
globalThis.__chk = [];
export function mountChecklists(pane, opts) {
  const o = { opts, picks: [], dead: false, pick(id) { this.picks.push(id); }, destroy() { this.dead = true; } };
  globalThis.__chk.push(o);
  return o;
}
"""
DOCS_STUB = r"""
export const isCoordFile = (f) => /^(LOA|LOP)\//i.test(f);
export function mountDocs() { return { pick() {} }; }
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("otherjs")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "checklist.mjs").write_text((FRONTEND / "js" / "checklist.js").read_text("utf-8")
                                     .replace('"./api.js"', '"./api.mjs"'), "utf-8")
    stubs = d / "stubs"
    stubs.mkdir()
    (stubs / "api.mjs").write_text(API_STUB, "utf-8")
    (stubs / "checklist.mjs").write_text(CHK_STUB, "utf-8")
    (stubs / "docs.mjs").write_text(DOCS_STUB, "utf-8")
    (stubs / "phraseology.mjs").write_text("export function mountPhraseology() {}\n", "utf-8")
    src = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    for mod in ("api", "checklist", "docs", "phraseology"):
        src = src.replace(f'"../{mod}.js"', f'"./stubs/{mod}.mjs"')
    (d / "other.mjs").write_text(src, "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "checklist.mjs").as_uri(), (d / "other.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_tips_rendering(js):
    tips = js["html"]["tips"]
    # numer przed tekstem, bez kropek prowadzących i bez pustej akcji; tekst escapowany poza <b> <i> <tt>
    assert '<span class="chk-what"><b class="chk-num">1.</b> If it is urgent – sound urgent</span></span></label>' in tips
    assert '<b class="chk-num">2.</b> Avoid <b>x</b> &amp; &lt;script&gt;' in tips
    assert "chk-dots" not in tips and "chk-action" not in tips and "chk-section" not in tips and "chk-pre" not in tips
    assert tips.count('type="checkbox"') == 2 and 'class="btn reset"' in tips and "chk-count" in tips
    done = js["html"]["tipsDone"]
    assert done.count("chk-row done") == 1 and done.count("checked") == 1


def test_procedure_rendering(js):
    proc = js["html"]["proc"]
    # bez numbered: bez numerów; akcja po kropkach, INPUT jako pole z zapisaną notatką, punkt bez akcji jak w HANDOVER
    assert "chk-num" not in proc
    assert '<div class="chk-section">Preparation</div>' in proc and '<p class="chk-pre">Plan <i>ahead</i></p>' in proc
    assert '<span class="chk-what">Weather and NOTAMs</span><span class="chk-dots"></span><b class="chk-action">CHECK</b>' in proc
    assert 'placeholder="NOTE" value="DLH1 &quot;x&quot;"' in proc
    assert '<span class="chk-what">Traffic in sector - <tt>.contactme</tt></span></span></label>' in proc
    # znacznik <i> przepuszczony, <station> wewnątrz pokazany jako tekst (raz escapowany)
    assert "Voice &amp; text announcement: <i>&lt;station&gt; now closed</i></span>" in proc


def _step(js, name):
    return next(s for s in js["steps"] if s["name"] == name)


def test_other_checklist_addresses(js):
    first = _step(js, "first")
    # "#other/checklist/close-position" (także po przekierowaniu z #checklist/close-position): CHECKLIST z tą checklistą
    assert first["sub"] == "checklist" and first["mounts"][-1]["start"] == "close-position"
    assert first["log"] == [["remember", "other", "checklist/close-position", False]]
    # druga checklista w otwartym CHECKLIST: wybór w podmenu, bez ponownego wczytania
    again = _step(js, "again")
    assert len(again["mounts"]) == len(first["mounts"]) and again["mounts"][-1]["picks"] == ["rwy-change"]
    assert again["log"] == [["remember", "other", "checklist/rwy-change", False]]
    # klik w podmenu checklist: nowy krok historii; nieznana checklista z adresu: poprawa adresu bez kroku
    assert _step(js, "click")["log"] == [["remember", "other", "checklist/handover-takeover", False]]
    assert _step(js, "fix")["log"] == [["remember", "other", "checklist/open-position", True]]


def test_other_subtab_switching(js):
    docs = _step(js, "docs")
    # przejście do DOCS niszczy CHECKLIST (spóźnione dane nic nie rysują)
    assert docs["sub"] == "docs" and docs["mounts"][-1]["dead"] is True
    assert docs["log"] == [["remember", "other", "docs", False]]
    # przycisk OTHER w menu: stan bez zmian
    assert _step(js, "menu")["sub"] == "docs" and _step(js, "menu")["log"] == [["remember", "other", "docs", False]]
    # powrót do CHECKLIST przyciskiem podmenu: ostatnio wybrana checklista
    subtab = _step(js, "subtab")
    assert subtab["sub"] == "checklist" and subtab["mounts"][-1]["start"] == "open-position"
    assert subtab["log"] == [["remember", "other", "checklist/open-position", False]]
    # "#other/checklist" bez id: pierwsza checklista
    bare = _step(js, "bare")
    assert bare["mounts"][-1]["picks"] == [""] and bare["log"] == [["remember", "other", "checklist", False]]
    phr = _step(js, "phraseology")
    assert phr["sub"] == "phraseology" and phr["mounts"][-1]["dead"] is True
    assert phr["log"] == [["remember", "other", "phraseology", False]]
    # LOA z dawnego adresu DOCS dalej do COORDINATION
    assert _step(js, "loa")["log"] == [["navigate", "coordination", "docs/LOA/x.pdf"]]


FRAME_SCRIPT = r"""
// atrapa document dla h() z api.js: <template> oddaje napis HTML zamiast węzła
globalThis.document = { createElement: () => ({ set innerHTML(v) { this.html = v; },
  get content() { return { firstElementChild: { html: this.html } }; } }) };
const api = await import(process.argv[2]);
const bar = (...args) => { const pane = { items: [], append(x) { this.items.push(x.html); } };
  api.iframeWithFallback(pane, ...args); return pane.items; };
console.log(JSON.stringify({ plain: bar("https://example.test/a?b=1&c=2", "Note"),
  hidden: bar("https://example.test/a?b=1&c=2") }));
"""


def test_frame_bar_without_url(tmp_path):
    """Pasek nad ramką (INOP, AD CIV/MIL/VFR, PHRASEOLOGY) bez adresu strony (adres mówi tylko, skąd jest strona),
    przycisk ↗ i uwaga zostają."""
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(FRAME_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (tmp_path / "api.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    url = "https://example.test/a?b=1&amp;c=2"
    plain_bar, plain_frame = out["plain"]
    assert '<span class="hint">Note</span>' in plain_bar and "hint mono" not in plain_bar
    hidden_bar, hidden_frame = out["hidden"]
    assert "hint mono" not in hidden_bar and "example.test" not in hidden_bar.replace(f'href="{url}"', "")
    assert f'<a class="btn" href="{url}" target="_blank" rel="noopener">Open in new tab ↗</a>' in hidden_bar
    assert hidden_frame == plain_frame and f'src="{url}"' in hidden_frame
    assert "example.test" not in plain_bar.replace(f'href="{url}"', "")
