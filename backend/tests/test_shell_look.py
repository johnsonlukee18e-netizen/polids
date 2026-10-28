"""0.13.0 (issue #23): wygląd PANDORY w powłoce. Wąski pasek u góry na całą szerokość (Reload | Brighter | Darker),
cała aplikacja czcionką bezszeryfową zwykłej grubości (decyzja właściciela: "cały program", także --mono), menu
ciasno z tym samym odstępem (EMERGENCY i ADMIN też), SYT OP jasnozielony, podmenu 140 px z napisami w dwóch linijkach
i zmniejszaniem w niskim oknie. Logika paska (topbar.js) uruchamiana w Node z atrapą DOM."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
INDEX = (FRONTEND / "index.html").read_text("utf-8")
APP = (FRONTEND / "js" / "app.js").read_text("utf-8")
TOPBAR = (FRONTEND / "js" / "topbar.js").read_text("utf-8")
STYLE = (FRONTEND / "css" / "style.css").read_text("utf-8")
SANS = 'Arial, "Liberation Sans", "Helvetica Neue", Helvetica, sans-serif'
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def _nocomments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rule(css, selector):
    """Treść pierwszej reguły o dokładnie tym selektorze (bez komentarzy)."""
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", _nocomments(css))
    assert m, selector
    return m.group(1)


def _media(css, query):
    """Treść wszystkich bloków @media o tym warunku (style.css ma ich kilka: menu, podmenu), sklejona."""
    out, head = [], f"@media ({query}) {{"
    i = css.find(head)
    assert i >= 0, query
    while i >= 0:
        depth, j = 0, css.index("{", i)
        for k in range(j, len(css)):
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            if not depth:
                out.append(css[j + 1:k])
                break
        i = css.find(head, k)
    return "\n".join(out)


# --- pasek u góry ---------------------------------------------------------------------------------------------------

def test_topbar_markup():
    """Pasek jest pierwszym dzieckiem <body>, przed menu i zakładkami: trzy przyciski od lewej Reload, Brighter, Darker
    (wielką literą tylko na początku jak w PANDORZE), dymki po angielsku, bez nazw źródeł danych."""
    body = INDEX[INDEX.index("<body>") + len("<body>"):]
    # bez role="toolbar": pasek nie ma nawigacji strzałkami, której czytnik ekranu oczekuje od paska narzędzi
    assert body.lstrip().startswith('<header id="topbar" class="topbar" aria-label="Screen">')
    bar = body[:body.index("</header>")]
    assert body.index("</header>") < body.index('<aside class="menu">') < body.index('<main id="views">')
    buttons = re.findall(r'<button type="button" data-act="([a-z]+)" title="([^"]+)">([^<]+)</button>', bar)
    assert [(a, label) for a, _, label in buttons] == [("reload", "Reload"), ("brighter", "Brighter"), ("darker", "Darker")]
    assert bar.count("<button") == 3
    for _, title, _ in buttons:
        assert not POLISH.search(title) and not re.search(r"VATSIM|vIFF|source|based on", title, re.I), title
    assert buttons[0][1] == "Reload the application and come back to this screen"


def test_topbar_layout_css():
    """body to siatka: pasek (18 px) na całą szerokość nad menu i main; trzy równe pola, napis zwykłej grubości."""
    body = _rule(STYLE, "body")
    assert "display: grid;" in body and "grid-template-columns: auto minmax(0, 1fr);" in body
    assert "grid-template-rows: var(--topbar-h) minmax(0, 1fr);" in body and "display: flex" not in body
    assert "--topbar-h: 18px;" in STYLE
    bar = _rule(STYLE, ".topbar")
    assert "grid-column: 1 / -1;" in bar and "display: flex;" in bar and "gap: 2px;" in bar
    btn = _rule(STYLE, ".topbar button")
    assert "flex: 1 1 0;" in btn and "height: var(--topbar-h);" in btn and "border-radius: 0;" in btn
    assert re.search(r"font: 12px/18px var\(--ui\);", btn) and "linear-gradient(#45a832, #2f8a22)" in btn
    assert ".topbar button:disabled { opacity: .45; cursor: default; }" in STYLE


def test_brightness_filter_only_on_root():
    """Filtr jasności tylko na <html>: filtr na main/#views zrobiłby z nich blok zawierający dla position: fixed
    (dymki RADIO, pasek offline przesunięte o menu i pasek). DMAN nie ma już własnej jasności."""
    assert "root ??= document.documentElement;" in TOPBAR and "root.style.filter = brightFilter(bright);" in TOPBAR
    for path in (FRONTEND / "js").rglob("*.js"):
        src = path.read_text("utf-8")
        if path.name == "topbar.js":
            continue
        assert "brightness(" not in src, path.name
    for path in (FRONTEND / "css").glob("*.css"):
        css = _nocomments(path.read_text("utf-8"))
        for sel in re.findall(r"([^{}]+)\{[^}]*\bfilter:\s*brightness", css):
            assert not re.search(r"(^|[\s,])(main|#views|\.view|body|html)\s*$", sel.strip()), (path.name, sel)


def test_app_wires_topbar_and_reload_marker():
    """Pasek uruchamia sam topbar.js, osobny moduł w index.html przed app.js: Reload, Brighter i Darker działają też
    wtedy, gdy nie wczyta się któraś zakładka (moduł z błędem zatrzymuje cały app.js). app.js tylko czyta znacznik
    Reload: po starcie zawsze HOME (n = 0), a jednorazowy znacznik otwiera potem tamten ekran jako krok po HOME."""
    assert 'import { reloadTarget, takeReload } from "./topbar.js";' in APP and "mountTopbar(" not in APP
    assert 'if (typeof document !== "undefined") mountTopbar(document.getElementById("topbar"));' in TOPBAR
    assert TOPBAR.count('from "./api.js"') == 1 and len(re.findall(r"^import ", TOPBAR, re.M)) == 1
    mods = re.findall(r'<script type="module" src="([^"]+)"></script>', INDEX)
    assert mods == ["/static/js/topbar.js", "/static/js/app.js"]
    boot = APP[APP.index("depth = 0;\n  open(\"home\");"):APP.index("ready = true;")]
    assert boot.index('open("home");') < boot.index("const again = reloadTarget(takeReload());")
    assert "if (again) open(again.tab, again.arg, true);" in boot
    # takeReload czyta i usuwa znacznik (jedno uruchomienie), Reload zapisuje bieżący adres i wczytuje stronę
    assert "store?.removeItem(RELOAD_KEY);" in TOPBAR and "markReload(here()," in TOPBAR and "reload();" in TOPBAR
    assert 'export const RELOAD_KEY = "shell.reload";' in TOPBAR and 'export const BRIGHT_KEY = "shell.bright";' in TOPBAR
    assert "window.sessionStorage" in TOPBAR and "lsSet(BRIGHT_KEY, String(bright));" in TOPBAR


EARLY_SCRIPT = r"""
const store = new Map();
const out = [];
const vals = ["-4", "-3", "-1", "0", "1", "2", "4", "5", "-5", "2.5", "abc", "", " 3 ", null];
const src = process.argv[3];
const tb = await import(process.argv[2]);
for (const v of vals) {
  const doc = { documentElement: { style: { filter: "" } } };
  const ls = { getItem: () => v };
  new Function("document", "localStorage", src)(doc, ls);
  out.push([v, doc.documentElement.style.filter, tb.brightFilter(tb.brightOf(v))]);
}
const blocked = { documentElement: { style: { filter: "" } } };
new Function("document", "localStorage", src)(blocked, { getItem() { throw new Error("blocked"); } });
console.log(JSON.stringify({ out, blocked: blocked.documentElement.style.filter }));
"""


def test_saved_brightness_before_first_paint(tmp_path):
    """Zapisana jasność już w <head> (klasyczny skrypt przed arkuszami i przed <body>): F5 i Reload bez błysku 100 %
    przed wczytaniem modułów (Playwright przed poprawką: 8-10 klatek menu bez filtra przy -4). Skrypt daje dokładnie
    ten sam filtr co brightFilter(brightOf()) z topbar.js, a zablokowany localStorage nie zatrzymuje strony."""
    head = INDEX[:INDEX.index("</head>")]
    m = re.search(r"\n  <script>(.*?)</script>\n", head)
    assert m and head.index("<script>") < head.index('<link rel="stylesheet"')
    early = m.group(1)
    assert not re.search(r"[^\x00-\x7f]", early) and '"shell.bright"' in early and "document.documentElement.style.filter" in early
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (tmp_path / "topbar.mjs").write_text(TOPBAR.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(EARLY_SCRIPT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "topbar.mjs").as_uri(), early],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    for v, got, want in res["out"]:
        assert got == want, v
    assert [x[1] for x in res["out"]][:7] == ["brightness(0.52)", "brightness(0.64)", "brightness(0.88)", "",
                                             "brightness(1.12)", "brightness(1.24)", "brightness(1.48)"]
    assert res["blocked"] == ""


def test_topbar_js_english_and_ascii_code():
    """Napisy po angielsku; polskie znaki tylko w samodzielnych linijkach komentarza (zasada plików JS)."""
    for i, line in enumerate(TOPBAR.splitlines(), 1):
        if re.search(r"[^\x00-\x7f]", line):
            assert line.strip().startswith("//"), (i, line)
    titles = re.findall(r"title = `([^`]+)`", TOPBAR)
    assert titles == ["Brighter screen (now ${pct}%${bright >= BRIGHT_MAX ? \", the brightest\" : \"\"})",
                      "Darker screen (now ${pct}%${bright <= BRIGHT_MIN ? \", the darkest\" : \"\"})"]


NODE_SCRIPT = r"""
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
const tb = await import(process.argv[2]);
const fakeStore = () => { const m = new Map(); return { m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v),
  removeItem: (k) => m.delete(k) }; };
const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("x"); } };
const out = {};
out.of = ["2", "-4", "4", "0", "5", "-5", "2.5", "abc", "", " 3 ", null, undefined].map(tb.brightOf);
out.clamp = [-9, -4, -1, 0, 3, 4, 9, NaN].map(tb.clampBright);
out.filter = [-4, -1, 0, 1, 4].map(tb.brightFilter);
out.pct = [-4, 0, 1, 4].map(tb.brightPct);
// znacznik Reload: zapis, jednorazowy odczyt, zablokowany i brakujący sessionStorage
const s = fakeStore();
tb.markReload("#aerodrome/EPWA/dman", s);
out.take = [tb.takeReload(s), tb.takeReload(s)];
tb.markReload("", s);
out.empty = tb.takeReload(s);
tb.markReload("#meteo", broken);
tb.markReload("#meteo", null);
out.broken = [tb.takeReload(broken), tb.takeReload(null)];
out.target = ["#aerodrome/EPWA/dman", "#home", "#home/x", "", null, "#", "#meteo", "#other/checklist/a"].map(tb.reloadTarget);
// pasek z atrapą DOM: zapisana jasność 2, kliknięcia, granice zakresu, Reload
store.set(tb.BRIGHT_KEY, "2");
const mk = (act) => ({ dataset: { act }, disabled: null, title: "", closest() { return this; } });
const btns = { reload: mk("reload"), brighter: mk("brighter"), darker: mk("darker") };
let handler = null;
const bar = { querySelector: (sel) => btns[/data-act="(\w+)"/.exec(sel)[1]], addEventListener: (t, fn) => { if (t === "click") handler = fn; } };
const root = { style: { filter: "stale" } };
let reloads = 0;
const sess = fakeStore();
const api = tb.mountTopbar(bar, { root, here: () => "#radio", reload: () => { reloads += 1; }, store: sess });
const snap = () => ({ level: api.level(), filter: root.style.filter, saved: store.get(tb.BRIGHT_KEY) ?? null,
  up: btns.brighter.disabled, down: btns.darker.disabled, upTitle: btns.brighter.title, downTitle: btns.darker.title });
const click = (act, n = 1) => { for (let i = 0; i < n; i++) handler({ target: btns[act] }); return snap(); };
out.start = snap();
out.max = click("brighter", 5);
out.min = click("darker", 12);
out.zero = click("brighter", 4);
out.reload = [click("reload").level, reloads, sess.m.get(tb.RELOAD_KEY)];
out.none = tb.mountTopbar(null);
// drugie wywołanie dla tego samego paska: ten sam obiekt, bez drugiego nasłuchu kliknięć
out.again = tb.mountTopbar(bar, { root }) === api;
// fokus z klawiatury na przycisku, który na granicy zakresu się wyłącza: przechodzi na drugi przycisk jasności;
// atrapa jak Chromium: wyłączenie przycisku z fokusem od razu zdejmuje z niego fokus
const doc = { activeElement: null };
const mk2 = (act) => {
  const o = { dataset: { act }, title: "", ownerDocument: doc, closest() { return this; }, focus() { doc.activeElement = this; } };
  let dis = null;
  Object.defineProperty(o, "disabled", { get: () => dis, set: (v) => { dis = v; if (v && doc.activeElement === o) doc.activeElement = null; } });
  return o;
};
const b2 = { reload: mk2("reload"), brighter: mk2("brighter"), darker: mk2("darker") };
let h2 = null, onStorage = null;
const bar2 = { querySelector: (sel) => b2[/data-act="(\w+)"/.exec(sel)[1]], addEventListener: (t, fn) => { if (t === "click") h2 = fn; } };
const win = { addEventListener: (t, fn) => { if (t === "storage") onStorage = fn; } };
const root2 = { style: { filter: "" } };
store.set(tb.BRIGHT_KEY, "3");
const api2 = tb.mountTopbar(bar2, { root: root2, win });
doc.activeElement = b2.brighter;
h2({ target: b2.brighter });
out.focusMax = [api2.level(), b2.brighter.disabled, doc.activeElement.dataset.act];
doc.activeElement = b2.darker;
for (let i = 0; i < 8; i++) h2({ target: b2.darker });
out.focusMin = [api2.level(), b2.darker.disabled, doc.activeElement.dataset.act];
// mysz (fokus gdzie indziej): fokus zostaje, gdzie był
doc.activeElement = null;
h2({ target: b2.brighter });
out.mouse = doc.activeElement;
// inne okno zmieniło jasność (zdarzenie storage): filtr i przyciski od razu; inne klucze bez zmian
store.set(tb.BRIGHT_KEY, "-2");
onStorage({ key: "other.key" });
out.foreign = [api2.level(), root2.style.filter];
onStorage({ key: tb.BRIGHT_KEY, newValue: "-2" });
out.synced = [api2.level(), root2.style.filter, b2.darker.disabled, b2.brighter.title];
store.delete(tb.BRIGHT_KEY);
onStorage({ key: null });
out.cleared = [api2.level(), root2.style.filter];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("topbar")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "topbar.mjs").write_text(TOPBAR.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "topbar.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_brightness_values(js):
    # zapisana wartość tylko jako liczba całkowita -4..4 (inaczej 0 = bez filtra); krok 12 %, 52-148 %
    assert js["of"] == [2, -4, 4, 0, 0, 0, 0, 0, 0, 3, 0, 0]
    assert js["clamp"] == [-4, -4, -1, 0, 3, 4, 4, 0]
    assert js["filter"] == ["brightness(0.52)", "brightness(0.88)", "", "brightness(1.12)", "brightness(1.48)"]
    assert js["pct"] == [52, 100, 112, 148]


def test_reload_marker(js):
    # jeden odczyt: drugi start (F5, nowe okno) znów otwiera HOME; pusty adres = HOME; zablokowany storage bez błędu
    assert js["take"] == ["#aerodrome/EPWA/dman", None]
    assert js["empty"] == "#home"
    assert js["broken"] == [None, None]
    assert js["target"] == [{"tab": "aerodrome", "arg": "EPWA/dman"}, None, None, None, None, None,
                            {"tab": "meteo", "arg": ""}, {"tab": "other", "arg": "checklist/a"}]


def test_topbar_buttons_clamp_and_storage(js):
    s = js["start"]
    assert s["level"] == 2 and s["filter"] == "brightness(1.24)" and s["saved"] == "2"
    assert s["up"] is False and s["down"] is False
    assert s["upTitle"] == "Brighter screen (now 124%)" and s["downTitle"] == "Darker screen (now 124%)"
    # na granicy zakresu przycisk wyłączony, kolejne kliknięcia nic nie zmieniają; wartość zapisana w localStorage
    m = js["max"]
    assert m["level"] == 4 and m["filter"] == "brightness(1.48)" and m["saved"] == "4" and m["up"] is True and m["down"] is False
    assert m["upTitle"] == "Brighter screen (now 148%, the brightest)"
    n = js["min"]
    assert n["level"] == -4 and n["filter"] == "brightness(0.52)" and n["saved"] == "-4" and n["down"] is True and n["up"] is False
    assert n["downTitle"] == "Darker screen (now 52%, the darkest)"
    z = js["zero"]
    assert z["level"] == 0 and z["filter"] == "" and z["saved"] == "0"
    assert z["upTitle"] == "Brighter screen (now 100%)"
    # Reload: adres bieżącego ekranu w sessionStorage, potem wczytanie strony; jasność bez zmian
    assert js["reload"] == [0, 1, "#radio"]
    assert js["none"] is None and js["again"] is True


def test_topbar_focus_and_other_windows(js):
    # Enter na Brighter przy +3 daje +4 i wyłącza przycisk: fokus na Darker (nie na <body>); tak samo przy -4
    assert js["focusMax"] == [4, True, "darker"]
    assert js["focusMin"] == [-4, True, "brighter"]
    assert js["mouse"] is None
    # drugie okno PolIDS: zmiana jasności od razu, bez F5
    assert js["foreign"] == [-3, "brightness(0.64)"]
    assert js["synced"] == [-2, "brightness(0.76)", False, "Brighter screen (now 76%)"]
    assert js["cleared"] == [0, ""]


# --- czcionka i grubość ---------------------------------------------------------------------------------------------

def test_sans_tokens_whole_app():
    """Decyzja właściciela (0.13.0): cały program czcionką bezszeryfową, także --mono (dane, METAR, kody)."""
    root = _rule(STYLE, ":root")
    for token in ("--mono", "--ui", "--sans"):
        assert f"{token}: {SANS};" in root, token
    assert "font: 13px/1.4 var(--sans);" in _rule(STYLE, "body")
    # nigdzie w arkuszach, na stronach logowania i offline ani w SVG róży wiatrów nie zostaje czcionka o stałej szerokości
    for path in [*(FRONTEND / "css").glob("*.css"), FRONTEND / "login.html", FRONTEND / "offline.html"]:
        text = _nocomments(path.read_text("utf-8"))
        assert not re.search(r"Consolas|Liberation Mono|DejaVu Sans Mono|monospace", text), path.name
    assert "Consolas" not in (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    for name in ("login.html", "offline.html"):
        assert SANS in (FRONTEND / name).read_text("utf-8"), name


def test_base_rule_normal_weight():
    """Przeglądarka sama pogrubia b, strong, th i h1-h6: jedna reguła zwykłej grubości w style.css."""
    assert "b, strong, th, h1, h2, h3, h4, h5, h6 { font-weight: normal; }" in STYLE


# radio.css przechodzi na zwykłą grubość w obszarze RADIO rundy 16 (zbiór znika po scaleniu)
BOLD_PENDING = {"radio.css"}
BOLD = re.compile(r"font-weight:\s*(?:[6-9]00|bold|bolder)\b|font:[^;}]*?(?<![\w.-])(?:[6-9]00|bold|bolder)\s")


def test_no_bold_in_css():
    """0.13.0 (issue #23): napisy zwykłej grubości jak w PANDORZE; wyróżnienie kolorem, nie pogrubieniem."""
    checked = []
    for path in sorted((FRONTEND / "css").glob("*.css")):
        if path.name in BOLD_PENDING:
            continue
        bad = [m.group(0) for m in BOLD.finditer(_nocomments(path.read_text("utf-8")))]
        assert not bad, (path.name, bad)
        checked.append(path.name)
    assert "style.css" in checked and "dman.css" in checked and len(checked) >= 14
    for name in ("login.html", "offline.html"):
        assert not BOLD.search(_nocomments((FRONTEND / name).read_text("utf-8"))), name
    # wzorzec łapie zarówno font-weight, jak i skrót font z grubością (próbka)
    assert BOLD.search(".x { font: 700 14px var(--ui); }") and BOLD.search(".x { font-weight: bold; }")
    assert BOLD.search(".x { font: italic 600 12px/1.2 var(--mono); }") and not BOLD.search(".x { font: 14px/1.35 var(--ui); }")
    assert not BOLD.search(".x { font: 11px/1.700 var(--ui); }")


def test_windrose_svg_text_normal_weight():
    aero = (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    assert 'font-weight="700"' not in aero and "font-weight:600" not in aero


def test_text_columns_measured_not_ch():
    """W Arialu litery mają różną szerokość, więc kolumny na najdłuższy tekst listy (AERODROME: znaki i nazwy stacji,
    listy lotnisk FIR) są mierzone w czcionce elementu (textWidth w api.js), a nie liczone w ch z liczby znaków."""
    api = (FRONTEND / "js" / "api.js").read_text("utf-8")
    aero = (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    alist = (FRONTEND / "js" / "aerolist.js").read_text("utf-8")
    assert "export function textWidth(texts, el)" in api and "measureText" in api
    assert '"--nm-w", `${textWidth(names, nm)}px`' in aero and '"--cs-w", `${textWidth(' in aero
    assert '"--nmw", `${Math.max(textWidth(' in alist and "}ch`" not in alist
    assert ".freqs .radio-row .cs { width: var(--cs-w, 7.4em); flex: none; }" in STYLE
    aerolist_css = (FRONTEND / "css" / "aerolist.css").read_text("utf-8")
    assert re.search(r"\.alist-row \{[^}]*grid-template-columns: 3\.3em minmax\(0, var\(--nmw, 30ch\)\)", aerolist_css)


# --- menu i podmenu --------------------------------------------------------------------------------------------------

def test_menu_labels_uppercase_normal_weight():
    """Przyciski menu, podmenu i .gbtn: wielkie litery zwykłej grubości, bez kapitalików (jak PANDORA)."""
    shared = _rule(STYLE, ".gbtn, .menu nav button, .submenu button")
    assert "font: 14px/1.35 var(--ui);" in shared and "text-transform: uppercase;" in shared
    assert "small-caps" not in shared and "700" not in shared


def test_menu_equal_gaps():
    """Wszystkie przyciski menu ciasno z tym samym odstępem (2 px, od 820 px w dół 1 px), EMERGENCY i ADMIN bez
    dodatkowego odstępu (Playwright: odstępy {2} i {1} przy 1600x900, 1366x768, 657, 600 i 1280x560)."""
    css = _nocomments(STYLE)
    assert "margin-top" not in _rule(STYLE, ".menu nav button.red")
    assert "margin-top" not in _rule(STYLE, ".menu nav button.admin")
    assert not re.search(r"#tabs button\.(red|admin)", css)
    assert ".menu nav button { padding: 5px 6px; margin-bottom: 2px; line-height: 1.2; }" in css
    assert "#tabs button { height: 24.8px; margin-bottom: 1px; }" in _media(css, "max-height: 820px")


def test_sytop_label_light_green():
    assert "--menu-lime: #ccff66;" in _rule(STYLE, ":root")
    # nieaktywny SYT OP jasnozielonym napisem; aktywny ma ciemny napis jak każdy aktywny przycisk
    assert '.menu nav button[data-tab="sytop"]:not(.active) { color: var(--menu-lime); }' in STYLE
    assert '<button data-tab="sytop">SYT OP</button>' in INDEX


def test_submenu_fits_long_labels_and_low_windows():
    """Podmenu 140 px: PHRASEOLOGY mieści się w Arialu (110,7 px przy 117 px treści), dłuższe dwa słowa schodzą do
    drugiej linijki (BRAKING / ACTION) w tej samej wysokości przycisku. W niskim oknie długie podmenu (OTHER 18,
    EMERGENCY 18, METEO 15) zmniejszają się jak menu główne: Playwright 18 przycisków przy 1366x600 po 29,7 px bez
    przewijania; siatka liter i odstępy .sep bez zmian."""
    css = _nocomments(STYLE)
    sub = _rule(STYLE, ".submenu")
    assert "width: 140px;" in sub and "overflow-y: auto;" in sub
    btn = _rule(STYLE, ".submenu button")
    height = float(re.search(r"height: ([\d.]+)px;", btn).group(1))
    line = float(re.search(r"line-height: ([\d.]+)px;", btn).group(1))
    assert "white-space: pre-line;" in btn and "padding: 0 4px;" in btn and height >= 2 * line + 2
    assert "display: grid;" in _rule(STYLE, ".submenu.letters") and ".submenu .sep { height: 10px; }" in css
    low = _media(css, "max-height: 899px")
    assert ".submenu:not(.letters) { display: flex; flex-direction: column; }" in low
    m = re.search(r"\.submenu:not\(\.letters\) > button \{([^}]*)\}", low).group(1)
    min_h = float(re.search(r"min-height: ([\d.]+)px;", m).group(1))
    low_line = float(re.search(r"line-height: ([\d.]+)px;", m).group(1))
    gap = float(re.search(r"margin-bottom: ([\d.]+)px;", m).group(1))
    assert "flex: 0 1 auto;" in m and min_h >= 2 * low_line + 2
    assert ".submenu:not(.letters) > .sep { flex: none; }" in low
    # 18 przycisków (OTHER po 0.13.0) w najniższym wariancie mieszczą się w 1366x600 pod paskiem u góry
    topbar = float(re.search(r"--topbar-h: ([\d.]+)px;", css).group(1))
    assert 18 * (min_h + gap) <= 600 - topbar - 12
