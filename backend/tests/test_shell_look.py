"""0.13.0 (issue #23): wygląd PANDORY w powłoce. Wąski pasek u góry na całą szerokość (Reload | Brighter | Darker),
cała aplikacja czcionką bezszeryfową zwykłej grubości (decyzja właściciela: "cały program", także --mono), SYT OP
jasnozielony. 0.13.1 (issue #25): każdy przycisk menu i podmenu 137 x 28 px z marginesem 1,5 px (litery AIRCRAFT /
CALLSIGN pół szerokości), rzędy podmenu na wysokości rzędów menu, w niskim oknie jedna wysokość --btn-h dla obu kolumn.
Logika paska (topbar.js) uruchamiana w Node z atrapą DOM."""
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


def _media_blocks(css, prefix="@media (max-height"):
    """Treść każdego bloku @media zaczynającego się od prefix (lista, w kolejności w arkuszu)."""
    out, i = [], css.find(prefix)
    while i >= 0:
        depth, j = 0, css.index("{", i)
        for k in range(j, len(css)):
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            if not depth:
                out.append(css[j + 1:k])
                break
        i = css.find(prefix, k)
    return out


def _rules(css):
    """Wszystkie reguły (selektor, treść) bez komentarzy, także te w blokach @media (najbardziej wewnętrzne)."""
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _nocomments(css))]


def _px(text):
    return float(re.fullmatch(r"([\d.]+)px", text.strip()).group(1))


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
const vals = ["-2", "-1", "0", "1", "2", "-3", "3", "-4", "4", "5", "-5", "2.5", "abc", "", " 3 ", null];
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
    # zakres -2..+2 (Marek 28.10.2026): -3, +3, -4, +4 (zapisane przy dawnym zakresie -4..+4) = bez filtra
    assert [x[1] for x in res["out"]][:9] == ["brightness(0.76)", "brightness(0.88)", "", "brightness(1.12)",
                                             "brightness(1.24)", "", "", "", ""]
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
out.of = ["2", "-2", "-1", "0", "3", "-3", "2.5", "abc", "", " 1 ", null, undefined].map(tb.brightOf);
out.clamp = [-9, -2, -1, 0, 1, 2, 9, NaN].map(tb.clampBright);
out.filter = [-2, -1, 0, 1, 2].map(tb.brightFilter);
out.pct = [-2, 0, 1, 2].map(tb.brightPct);
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
// pasek z atrapą DOM: zapisana jasność 1, kliknięcia, granice zakresu, Reload
store.set(tb.BRIGHT_KEY, "1");
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
out.zero = click("brighter", 2);
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
store.set(tb.BRIGHT_KEY, "1");
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
    # zapisana wartość tylko jako liczba całkowita -2..2 (Marek 28.10.2026; inaczej 0 = bez filtra, także -4..+4
    # z dawnego zakresu); krok 12 %, 76-124 %
    assert js["of"] == [2, -2, -1, 0, 0, 0, 0, 0, 0, 1, 0, 0]
    assert js["clamp"] == [-2, -2, -1, 0, 1, 2, 2, 0]
    assert js["filter"] == ["brightness(0.76)", "brightness(0.88)", "", "brightness(1.12)", "brightness(1.24)"]
    assert js["pct"] == [76, 100, 112, 124]


def test_reload_marker(js):
    # jeden odczyt: drugi start (F5, nowe okno) znów otwiera HOME; pusty adres = HOME; zablokowany storage bez błędu
    assert js["take"] == ["#aerodrome/EPWA/dman", None]
    assert js["empty"] == "#home"
    assert js["broken"] == [None, None]
    assert js["target"] == [{"tab": "aerodrome", "arg": "EPWA/dman"}, None, None, None, None, None,
                            {"tab": "meteo", "arg": ""}, {"tab": "other", "arg": "checklist/a"}]


def test_topbar_buttons_clamp_and_storage(js):
    s = js["start"]
    assert s["level"] == 1 and s["filter"] == "brightness(1.12)" and s["saved"] == "1"
    assert s["up"] is False and s["down"] is False
    assert s["upTitle"] == "Brighter screen (now 112%)" and s["downTitle"] == "Darker screen (now 112%)"
    # na granicy zakresu przycisk wyłączony, kolejne kliknięcia nic nie zmieniają; wartość zapisana w localStorage
    m = js["max"]
    assert m["level"] == 2 and m["filter"] == "brightness(1.24)" and m["saved"] == "2" and m["up"] is True and m["down"] is False
    assert m["upTitle"] == "Brighter screen (now 124%, the brightest)"
    n = js["min"]
    assert n["level"] == -2 and n["filter"] == "brightness(0.76)" and n["saved"] == "-2" and n["down"] is True and n["up"] is False
    assert n["downTitle"] == "Darker screen (now 76%, the darkest)"
    z = js["zero"]
    assert z["level"] == 0 and z["filter"] == "" and z["saved"] == "0"
    assert z["upTitle"] == "Brighter screen (now 100%)"
    # Reload: adres bieżącego ekranu w sessionStorage, potem wczytanie strony; jasność bez zmian
    assert js["reload"] == [0, 1, "#radio"]
    assert js["none"] is None and js["again"] is True


def test_topbar_focus_and_other_windows(js):
    # Enter na Brighter przy +1 daje +2 i wyłącza przycisk: fokus na Darker (nie na <body>); tak samo przy -2
    assert js["focusMax"] == [2, True, "darker"]
    assert js["focusMin"] == [-2, True, "brighter"]
    assert js["mouse"] is None
    # drugie okno PolIDS: zmiana jasności od razu, bez F5 (-2 to dół zakresu: Darker wyłączony)
    assert js["foreign"] == [-1, "brightness(0.88)"]
    assert js["synced"] == [-2, "brightness(0.76)", True, "Brighter screen (now 76%)"]
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
    """Przeglądarka sama pogrubia b, strong, th, h1-h6 i optgroup (grupy w polach Position): jedna reguła zwykłej
    grubości w style.css. leaflet.css pogrubia +/- (font: bold 18px): reguła Leafleta w style.css zdejmuje i to
    (Playwright: przed poprawką optgroup i +/- na MAP, METEO › QNH i SUN miały 700)."""
    assert "b, strong, th, h1, h2, h3, h4, h5, h6, optgroup { font-weight: normal; }" in STYLE
    leaflet = (FRONTEND / "vendor" / "leaflet" / "leaflet.css").read_text("utf-8")
    assert re.search(r"\.leaflet-control-zoom-in,\s*\.leaflet-control-zoom-out \{\s*font: bold", leaflet)
    rule = _rule(STYLE, ".leaflet-control-zoom a, .leaflet-container a.leaflet-popup-close-button")
    assert "font-family: var(--mono);" in rule and "font-weight: normal;" in rule


BOLD = re.compile(r"font-weight:\s*(?:[6-9]00|bold|bolder)\b|font:[^;}]*?(?<![\w.-])(?:[6-9]00|bold|bolder)\s")


def test_no_bold_in_css():
    """0.13.0 (issue #23): napisy zwykłej grubości jak w PANDORZE; wyróżnienie kolorem, nie pogrubieniem."""
    checked = []
    for path in sorted((FRONTEND / "css").glob("*.css")):
        bad = [m.group(0) for m in BOLD.finditer(_nocomments(path.read_text("utf-8")))]
        assert not bad, (path.name, bad)
        checked.append(path.name)
    assert "style.css" in checked and "dman.css" in checked and "radio.css" in checked and len(checked) >= 14
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
    """Wszystkie przyciski menu z tym samym odstępem (0.13.1: margines 1,5 px z każdej strony, 3 px między przyciskami),
    EMERGENCY i ADMIN bez dodatkowego odstępu i bez własnej wielkości."""
    css = _nocomments(STYLE)
    assert "margin-top" not in _rule(STYLE, ".menu nav button.red")
    assert "margin-top" not in _rule(STYLE, ".menu nav button.admin")
    assert not re.search(r"#tabs button", css)
    shared = _rule(STYLE, ".menu nav button, .submenu button")
    assert "margin: var(--btn-m);" in shared and "margin-bottom" not in shared
    # wspólna reguła po regule bazowej (.gbtn, …: margin 0 0 3px) o tej samej szczegółowości, więc to ona obowiązuje
    assert css.index(".menu nav button, .submenu button {") > css.index(".gbtn, .menu nav button, .submenu button {")


def test_sytop_label_light_green():
    assert "--menu-lime: #ccff66;" in _rule(STYLE, ":root")
    # nieaktywny SYT OP jasnozielonym napisem; aktywny ma ciemny napis jak każdy aktywny przycisk
    assert '.menu nav button[data-tab="sytop"]:not(.active) { color: var(--menu-lime); }' in STYLE
    assert '<button data-tab="sytop">SYT OP</button>' in INDEX


def test_one_button_size_everywhere():
    """0.13.1 (issue #25): "Rozmiar wszystkich przycisków powinien wynosić 137 x 28 wraz z marginem 1.5 dla każdego
    przycisku. Rozmiary mają być JEDNAKOWE." Jedna reguła dla menu i każdego podmenu: 137 x --btn-h (28 px, w niskim
    oknie mniej, po równo w obu kolumnach), margines 1,5 px z każdej strony, napis w jednej linijce na środku. Obie
    kolumny po 150 px z paddingiem 4,5 px, więc pierwszy przycisk podmenu stoi na wysokości pierwszego przycisku menu
    (Playwright, check_align.py: 0 problemów przy 1600x900, 1366x768 i 1366x657, z użytkownikiem i bez)."""
    css = _nocomments(STYLE)
    root = _rule(STYLE, ":root")
    for decl in ("--btn-w: 137px;", "--btn-h-max: 28px;", "--btn-m: 1.5px;", "--col-pad: 4.5px;",
                 "--col-w: calc(var(--btn-w) + 2 * var(--btn-m) + 2 * var(--col-pad) + 1px);"):
        assert decl in root, decl
    tok = {k: _px(v) for k, v in re.findall(r"(--btn-w|--btn-h-max|--btn-m|--col-pad): ([\d.]+px);", root)}
    col_w = tok["--btn-w"] + 2 * tok["--btn-m"] + 2 * tok["--col-pad"] + 1   # + prawa ramka kolumny
    assert col_w == 150 and tok["--btn-w"] == 137 and tok["--btn-h-max"] == 28
    # odstęp między przyciskami 3 px (marginesy w kolumnie flex się nie łączą), rząd co 31 px
    assert 2 * tok["--btn-m"] == 3 and tok["--btn-h-max"] + 2 * tok["--btn-m"] == 31
    shared = _rule(STYLE, ".menu nav button, .submenu button")
    for decl in ("flex: none;", "width: var(--btn-w);", "height: var(--btn-h);", "margin: var(--btn-m);", "padding: 0 4px;",
                 "line-height: calc(var(--btn-h) - 2px);"):
        assert decl in shared, decl
    for sel in (".menu", ".submenu"):
        rule = _rule(STYLE, sel)
        assert "width: var(--col-w);" in rule and "padding: var(--col-pad);" in rule, sel
        assert re.search(r"display: flex;\s+flex-direction: column;", rule), sel
    assert "display: flex; flex-direction: column;" in _rule(STYLE, ".menu nav")
    # bez dawnych wyjątków: żadnego @media (max-height) dla menu, podmenu, zegara i użytkownika, bez dwóch linijek
    for block in _media_blocks(css):
        assert not re.search(r"#tabs|\.menu|\.submenu|\.clockbox|\.userbox|\.brand", block), block
    assert "pre-line" not in css and "34.9px" not in css and "140px" not in css
    # w style.css wielkość przycisków menu i podmenu ustawiają tylko te reguły (wspólna po bazowej .gbtn, …)
    size = re.compile(r"(?<![\w-])(?:(?:min-|max-)?(?:width|height)|margin(?:-[a-z]+)?|padding(?:-[a-z]+)?|line-height|font-size|font)\s*:")
    shell = re.compile(r"#tabs|\.menu nav|\.submenu")
    sized = {sel for sel, body in _rules(STYLE) if shell.search(sel) and size.search(body)}
    assert sized == {".gbtn, .menu nav button, .submenu button", ".menu nav button, .submenu button", ".menu nav",
                     ".menu nav button.back", ".submenu", ".submenu.letters button", ".submenu .sep", LONG}, sized
    assert _rule(STYLE, ".menu nav button.back").strip() == "font-size: 22px;"
    # inne arkusze nie zmieniają wielkości przycisków menu ani podmenu (coordination.css: tylko letter-spacing i rogi)
    for path in sorted((FRONTEND / "css").glob("*.css")):
        if path.name == "style.css":
            continue
        bad = [sel for sel, body in _rules(path.read_text("utf-8")) if shell.search(sel) and size.search(body)]
        assert not bad, (path.name, bad)


def test_letters_half_width_and_rows():
    """Jedyny wyjątek z issue #25: litery AIRCRAFT / CALLSIGN pół szerokości przycisku i tej samej wysokości. ALL
    i KEYBOARD na całą szerokość (137 px), pod nimi litery parami; odstęp .sep w podmenu (METEO, AWALON, AD CIV) to
    jeden pusty rząd, żeby przyciski pod nim dalej stały na wysokości przycisków menu."""
    letters = _rule(STYLE, ".submenu.letters")
    assert "display: grid;" in letters and "grid-template-columns: 1fr 1fr;" in letters
    # bez własnej szerokości i bez gap: kolumna jak każde podmenu (150 px), odstęp 3 px dają marginesy przycisków
    assert "width" not in letters and "gap" not in letters
    assert _rule(STYLE, ".submenu.letters button").strip() == "width: auto;"
    assert "grid-column: 1 / -1;" in _rule(STYLE, ".submenu.letters button.all, .submenu.letters button.kbd")
    root = _rule(STYLE, ":root")
    tok = {k: _px(v) for k, v in re.findall(r"(--btn-w|--btn-m|--col-pad): ([\d.]+px);", root)}
    col_w = 150
    letter = (col_w - 1 - 2 * tok["--col-pad"]) / 2 - 2 * tok["--btn-m"]
    assert letter == 67 and 2 * letter + 2 * tok["--btn-m"] == tok["--btn-w"] == 137
    assert ".submenu .sep { flex: none; height: calc(var(--btn-h) + 2 * var(--btn-m)); }" in _nocomments(STYLE)


# podmenu dłuższe niż menu (AD VFR): selektor z style.css
LONG = ".submenu:not(.letters):has(> :nth-child(22))"


def test_submenus_without_scrollbars():
    """Runda 17: AD VFR (69 lotnisk i eAIP, jedyne przewijane podmenu) w przeglądarce z klasycznymi paskami (Chromium
    bez --hide-scrollbars, 1600x900, #advfr/EPPZ) miało pasek pionowy i poziomy, a przyciski 137 px były ucięte z boku
    (clientWidth 134 przy 149 px treści). Menu i podmenu bez widocznych pasków (scrollbar-width i ::-webkit-scrollbar dla
    Safari i starszego Chrome), bez przewijania w poziomie; kółko myszy i palec przewijają dalej (overflow-y: auto)."""
    css = _nocomments(STYLE)
    assert ".menu nav, .submenu { overflow-x: hidden; scrollbar-width: none; }" in css
    assert ".menu nav::-webkit-scrollbar, .submenu::-webkit-scrollbar { display: none; }" in css
    assert "overflow-y: auto;" in _rule(STYLE, ".submenu") and "overflow-y: auto;" in _rule(STYLE, ".menu nav")
    # żadna inna reguła dla samych kolumn nie przywraca paska ani nie wyłącza przewijania
    columns = {".menu nav", ".submenu", ".submenu.letters", LONG}
    for sel, body in _rules(STYLE):
        if columns & {part.strip() for part in sel.split(",")}:
            assert not re.search(r"scrollbar-width: (?!none)|overflow(-y)?: (hidden|visible|scroll)", body), (sel, body)


def test_long_submenu_scrolls_whole_rows():
    """Runda 17: przewinięte AD VFR wychodziło z siatki 31 px menu (issue #25: każdy rząd podmenu na wysokości rzędu
    menu obok). Podmenu dłuższe niż --menu-rows rzędów (22 = 21 + 1 elementów kolumny; litery mają po dwa w rzędzie)
    pokazuje tylko całe rzędy: margines zamiast paddingu u góry i u dołu (w paddingu widać było 3 px przycisków spoza
    widoku), wysokość do ostatniego całego rzędu nad dołem okna (mod(); bez mod() 21 rzędów), przewijanie zatrzymuje się
    na początku rzędu (scroll-snap), aip.js przewija o całe rzędy. Pod ostatnim rzędem kolumnę (tło, kreska z prawej)
    rysuje zakładka. Playwright (scrolltest.py, prawdziwe paski): kółko, dotyk i adres przy 1600x900, 1366x768,
    1366x657 z użytkownikiem i bez: bez paska, bez ułamków przycisków w widoku, przewinięcie w całych rzędach."""
    css = _nocomments(STYLE)
    rows = int(re.search(r"--menu-rows: (\d+);", css).group(1))
    assert LONG == f".submenu:not(.letters):has(> :nth-child({rows + 1}))"
    long = _rule(STYLE, LONG)
    pitch = "var(--btn-h) + 2 * var(--btn-m)"
    assert f"max-height: calc(var(--menu-rows) * ({pitch}));" in long
    assert "margin-block: var(--col-pad);" in long and "padding-block: 0;" in long
    assert "scroll-snap-type: y mandatory;" in long and "scroll-padding" not in long
    full = "var(--view-h) - var(--topbar-h) - 2 * var(--col-pad)"
    assert (f"@supports (height: mod(5px, 3px)) {{\n  {LONG} {{ max-height: calc({full}\n    - mod({full}, {pitch})); }}\n}}"
            in css)
    # początek rzędu: margines nad przyciskiem (1,5 px) i odstęp (.sep) bez marginesu
    assert f"{LONG} > * {{ scroll-snap-align: start; }}" in css
    assert f"{LONG} > button {{ scroll-margin-top: var(--btn-m); }}" in css
    # kolumna pod ostatnim rzędem jak .submenu: to samo tło i ta sama kreska z prawej (1 px z --col-w)
    sub = _rule(STYLE, ".submenu")
    assert "background: #050605;" in sub and "border-right: 1px solid var(--line);" in sub
    view = _rule(STYLE, ".view:has(> .submenu:not(.letters) > :nth-child(22))")
    assert ("background: linear-gradient(to right, #050605 calc(var(--col-w) - 1px), var(--line) 0 var(--col-w), "
            "transparent 0);") in view
    # widać całe rzędy: R x 31 px przy 28 px; w oknie 1366x657 (rząd 26,1875 px) do ostatniego całego rzędu
    for view_h, pitch_px in ((900, 31), (768, 31), (657, 26.1875)):
        col = view_h - 18 - 9
        visible = col - col % pitch_px
        assert abs(visible / pitch_px - round(visible / pitch_px)) < 1e-9 and col - visible < pitch_px

