"""OTHER (0.12.6, issue #21): CHECKLIST jako podzakładka OTHER (adresy, przekierowania, checklisty w drugim podmenu),
nowa checklista TIPS FOR CONTROLLERS (punkty bez "...AKCJA", numerowane) i napisy bez źródeł danych w OTHER,
EMERGENCY i na stronie offline. 0.13.0 (issue #23): 18 podzakładek alfabetycznie (tabela stron w other.js), domyślnie
DOCS, zaślepki, SQUAWK, FLIGHT PLAN i FMP w OTHER z adresami #other/<id>[/<stan>]."""
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
                                  "js/squawk.js", "js/regcause.js", "js/vfrminima.js",
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
    for name in ("js/tabs/other.js", "js/checklist.js", "js/phraseology.js", "js/tabs/emergency.js", "sw.js",
                 "js/squawk.js", "js/regcause.js", "js/vfrminima.js"):
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

// --- OTHER: podzakładki i adresy (podmenu, DOCS, PHRASEOLOGY, CHECKLIST, SQUAWK, FLIGHT PLAN, FMP, REGCAUSE i
// VFR MINIMA zastąpione atrapami)
const root = {};
const view = other.mount(root, { config: { links: {} } });
const sub = globalThis.__sub;
const initial = { sub: sub.current(), tabs: globalThis.__tabs, docs: globalThis.__docs.map((d) => d.start) };
const steps = [];
const page = (kind) => globalThis.__pages.filter((x) => x.kind === kind)
  .map((x) => ({ start: x.opts?.start ?? null, calls: [...x.calls], dead: x.dead }));
const step = (name, fn) => { log.length = 0; fn(); steps.push({ name, sub: sub.current(), log: [...log],
  mounts: globalThis.__chk.map((c) => ({ start: c.opts.start, picks: [...c.picks], dead: c.dead })),
  docs: globalThis.__docs.map((d) => ({ start: d.start, picks: [...d.picks] })),
  squawk: page("squawk"), fp: page("fp"), fmp: page("fmp"), regcause: page("regcause"), vfr: page("vfr"),
  pane: globalThis.__pane.items.join("") }); };
const last = (kind) => globalThis.__pages.filter((x) => x.kind === kind).at(-1);
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
step("squawk", () => view.activate("squawk/7700"));
step("squawk-again", () => view.activate("squawk/7600"));
step("squawk-code", () => last("squawk").opts.onCode("7500"));
step("squawk-menu", () => view.activate(undefined));
step("fp", () => view.activate("flight-plan/lot1"));
step("fp-lookup", () => last("fp").opts.onLookup("dlh2"));
step("fp-again", () => view.activate("flight-plan/LOT1"));
step("fp-menu", () => view.activate(undefined));
step("squawk-return", () => sub.click("squawk"));
step("squawk-bare", () => view.activate("squawk"));
step("fmp", () => view.activate("fmp"));
step("fmp-menu", () => view.activate(undefined));
step("fp-return", () => sub.click("flight-plan"));
step("regcause", () => view.activate("regcause"));
step("vfr", () => view.activate("vfr-minima"));
step("4p", () => view.activate("4p"));
step("click-bomb", () => sub.click("bomb-phone"));
step("aftn", () => view.activate("aftn"));
step("unknown", () => view.activate("nope/x"));
step("vfr-again", () => view.activate("vfr-minima"));
step("vfr-same", () => view.activate("vfr-minima"));
step("empty", () => view.activate(""));
console.log(JSON.stringify({ html, initial, steps, future: globalThis.__future }));
"""

API_STUB = r"""
globalThis.__log = [];
export const h = (html) => ({ html });
export const navigate = (tab, arg) => globalThis.__log.push(["navigate", tab, arg]);
export const remember = (tab, arg, opts = {}) => globalThis.__log.push(["remember", tab, arg, !!opts.replace]);
// podmenu jak subtabs w api.js: podzakładka domyślna (opts.first, inaczej pierwsza) od razu, show() niszczy poprzednią
// (destroy), klik = show + remember(arg); panel zapisuje wstawione napisy HTML
export function subtabs(root, tabs, opts = {}) {
  let cur = null, id = null;
  const first = (tabs.find((y) => y.id === opts.first) || tabs[0]).id;
  globalThis.__tabs = tabs.map((t) => [t.id, t.label, !!t.fill]);
  const show = (x) => {
    cur?.destroy?.();
    const t = tabs.find((y) => y.id === x) || tabs.find((y) => y.id === first);
    id = t.id;
    globalThis.__pane = { items: [], append(...xs) { this.items.push(...xs.map((v) => v.html)); } };
    cur = t.render(globalThis.__pane) || null;
  };
  const ctl = { show, current: () => id, click: (x) => { show(x); remember("other", opts.arg(id)); } };
  globalThis.__sub = ctl;
  show(first);
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
globalThis.__docs = [];
export const isCoordFile = (f) => /^(LOA|LOP)\//i.test(f);
export function mountDocs(pane, ctx, opts) {
  const o = { start: opts.start, picks: [], pick(f) { this.picks.push(f); } };
  globalThis.__docs.push(o);
  return o;
}
"""
# atrapy stron: zapis montowania (opts), wywołań (activate/focus; undefined = "<menu>") i destroy
PAGE_STUB = r"""
globalThis.__pages ||= [];
const arg = (a) => (a === undefined ? "<menu>" : a);
export function %(fn)s(pane, opts) {
  const o = { kind: "%(kind)s", opts, calls: [], dead: false, activate(a) { this.calls.push(["activate", arg(a)]); },
    focus() { this.calls.push(["focus"]); }, destroy() { this.dead = true; } };
  globalThis.__pages.push(o);
  return o;
}
"""
PAGES = {"squawk": ("mountSquawk", "squawk"), "flightplan": ("mountFlightPlan", "fp"), "fmp": ("mountFmp", "fmp"),
         "regcause": ("mountRegcause", "regcause"), "vfrminima": ("mountVfrMinima", "vfr")}


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
    for mod, (fn, kind) in PAGES.items():
        (stubs / f"{mod}.mjs").write_text(PAGE_STUB % {"fn": fn, "kind": kind}, "utf-8")
    src = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    for mod in ("api", "checklist", "docs", "phraseology", *PAGES):
        assert f'"../{mod}.js"' in src, mod
        src = src.replace(f'"../{mod}.js"', f'"./stubs/{mod}.mjs"')
    (d / "other.mjs").write_text(src + '\nglobalThis.__future = FUTURE;\n', "utf-8")
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


OTHER_LABELS = ["4P", "AFTN", "BOMB PHONE", "BRAKING ACTION", "CHECKLIST", "DOCS", "FLIGHT PLAN", "FMP", "HOLDING", "IA",
                "LIGHT GUN", "METEO", "NATO WEATHER", "PHRASEOLOGY", "POSITION", "REGCAUSE", "SQUAWK", "VFR MINIMA"]
PLACEHOLDERS = ["4p", "aftn", "bomb-phone", "braking-action", "holding", "ia", "light-gun", "meteo", "nato-weather",
                "position"]
FUTURE = "This function will be available in the future."


def test_other_submenu_order_and_default(js):
    """0.13.0 (issue #23): 18 podzakładek alfabetycznie jak w PANDORZE (BRAKING, nie BREAKING), każda na całą
    wysokość; OTHER bez adresu otwiera się na DOCS (jak do 0.12.6), nie na pierwszej w kolumnie (4P)."""
    tabs = js["initial"]["tabs"]
    assert OTHER_LABELS == sorted(OTHER_LABELS)
    # dwa słowa w dwóch linijkach jak w podmenu PANDORY (przycisk z white-space: pre-line), jedno słowo bez zmian
    assert [label for _, label, _ in tabs] == [x.replace(" ", "\n") for x in OTHER_LABELS]
    assert [label for _, label, _ in tabs if "\n" in label] == ["BOMB\nPHONE", "BRAKING\nACTION", "FLIGHT\nPLAN",
                                                                "LIGHT\nGUN", "NATO\nWEATHER", "VFR\nMINIMA"]
    assert [i for i, _, _ in tabs] == ["4p", "aftn", "bomb-phone", "braking-action", "checklist", "docs", "flight-plan",
                                        "fmp", "holding", "ia", "light-gun", "meteo", "nato-weather", "phraseology",
                                        "position", "regcause", "squawk", "vfr-minima"]
    assert all(fill for _, _, fill in tabs)
    assert js["initial"]["sub"] == "docs" and js["initial"]["docs"] == [""]


def test_other_placeholders(js):
    assert js["future"] == FUTURE
    four = _step(js, "4p")
    assert four["sub"] == "4p" and four["log"] == [["remember", "other", "4p", False]]
    assert four["pane"] == f'<div class="pane ot-future"><p>{FUTURE}</p></div>'
    # klik w podmenu: krok historii z id zaślepki; adres #other/aftn
    bomb = _step(js, "click-bomb")
    assert bomb["sub"] == "bomb-phone" and bomb["log"] == [["remember", "other", "bomb-phone", False]] and FUTURE in bomb["pane"]
    assert _step(js, "aftn")["log"] == [["remember", "other", "aftn", False]] and FUTURE in _step(js, "aftn")["pane"]
    other = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    pages = re.findall(r'\{ id: "([^"]+)", label: "[^"]+" \}', other)
    assert pages == PLACEHOLDERS


def test_other_squawk_addresses(js):
    sq = _step(js, "squawk")
    # "#other/squawk/7700" (także po przekierowaniu z #squawk/7700): SQUAWK od razu z tym kodem
    assert sq["sub"] == "squawk" and sq["squawk"][-1]["start"] == "7700" and sq["mounts"][-1]["dead"] is True
    assert sq["log"] == [["remember", "other", "squawk/7700", False]]
    # inny kod przy otwartym SQUAWK: kod do pola, bez ponownego rysowania
    again = _step(js, "squawk-again")
    assert len(again["squawk"]) == 1 and again["squawk"][0]["calls"] == [["activate", "7600"]]
    assert again["log"] == [["remember", "other", "squawk/7600", False]]
    # wpisany pełny kod = krok historii (remember bez replace)
    assert _step(js, "squawk-code")["log"] == [["remember", "other", "squawk/7500", False]]
    # przycisk menu: fokus i świeże dane (activate bez adresu), adres bez zmian
    menu = _step(js, "squawk-menu")
    assert menu["squawk"][0]["calls"][-1] == ["activate", "<menu>"] and menu["log"] == [["remember", "other", "squawk/7500", False]]
    # przejście do FLIGHT PLAN niszczy SQUAWK (nasłuch i spóźnione dane), powrót: ostatni kod
    assert _step(js, "fp")["squawk"][0]["dead"] is True
    ret = _step(js, "squawk-return")
    assert ret["squawk"][-1]["start"] == "7500" and ret["log"] == [["remember", "other", "squawk/7500", False]]
    bare = _step(js, "squawk-bare")
    assert bare["squawk"][-1]["calls"] == [["activate", ""]] and bare["log"] == [["remember", "other", "squawk", False]]


def test_other_flight_plan_and_fmp_addresses(js):
    fp = _step(js, "fp")
    # znak z adresu wielkimi literami; każde wyszukanie (onLookup) to krok historii #other/flight-plan/<ZNAK>
    assert fp["sub"] == "flight-plan" and fp["fp"][-1]["start"] == "LOT1"
    assert fp["log"] == [["remember", "other", "flight-plan/LOT1", False]]
    assert _step(js, "fp-lookup")["log"] == [["remember", "other", "flight-plan/DLH2", False]]
    again = _step(js, "fp-again")
    assert len(again["fp"]) == 1 and again["fp"][0]["calls"] == [["activate", "LOT1"]]
    assert again["log"] == [["remember", "other", "flight-plan/LOT1", False]]
    assert _step(js, "fp-menu")["fp"][0]["calls"][-1] == ["focus"]
    fmp = _step(js, "fmp")
    assert fmp["sub"] == "fmp" and len(fmp["fmp"]) == 1 and fmp["log"] == [["remember", "other", "fmp", False]]
    menu = _step(js, "fmp-menu")
    assert menu["fmp"][0]["calls"] == [["activate", "<menu>"]] and menu["log"] == [["remember", "other", "fmp", False]]
    # powrót do FLIGHT PLAN: FMP zniszczone, ostatni znak
    ret = _step(js, "fp-return")
    assert ret["fmp"][0]["dead"] is True and ret["fp"][-1]["start"] == "LOT1"
    assert ret["log"] == [["remember", "other", "flight-plan/LOT1", False]]


def test_other_static_pages_and_unknown(js):
    reg = _step(js, "regcause")
    assert reg["sub"] == "regcause" and len(reg["regcause"]) == 1 and reg["log"] == [["remember", "other", "regcause", False]]
    assert reg["fp"][-1]["dead"] is True
    vfr = _step(js, "vfr")
    assert vfr["sub"] == "vfr-minima" and vfr["log"] == [["remember", "other", "vfr-minima", False]]
    assert vfr["regcause"][0]["dead"] is True
    # nieznane id i pusty adres: DOCS (pierwszy dokument)
    unknown = _step(js, "unknown")
    assert unknown["sub"] == "docs" and unknown["log"] == [["remember", "other", "docs", False]]
    assert unknown["docs"][-1]["start"] == ""
    # VFR MINIMA z innej podzakładki rysuje się od nowa; przy otwartej ten sam adres nie rysuje jej drugi raz
    n = len(_step(js, "vfr-again")["vfr"])
    assert n == len(_step(js, "unknown")["vfr"]) + 1 and _step(js, "vfr-again")["sub"] == "vfr-minima"
    same = _step(js, "vfr-same")
    assert len(same["vfr"]) == n and same["log"] == [["remember", "other", "vfr-minima", False]]
    empty = _step(js, "empty")
    assert empty["sub"] == "docs" and empty["log"] == [["remember", "other", "docs", False]]


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
