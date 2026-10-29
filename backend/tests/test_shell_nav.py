"""Powłoka aplikacji (runda 10): kolejność menu jak w PANDORZE, przycisk ← (powrót), HOME z powitaniem, ABOUT,
nowe zakładki i adres ekranu "#zakładka/arg" (arg = wszystko po pierwszym "/")."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
INDEX = (FRONTEND / "index.html").read_text("utf-8")
APP = (FRONTEND / "js" / "app.js").read_text("utf-8")

# INOP pod AD VFR, DOCS w OTHER (runda 11); 0.12.3 (issue #13): COORDINATION i CONVERSION po MAP, SQUAWK po STRIP,
# PHRASEOLOGY w OTHER; 0.12.6 (issue #21): CHECKLIST w OTHER; 0.13.0 (issue #23): bez STRIP, AWALON po METEO,
# SQUAWK w OTHER
MENU = ["home", "radio", "meteo", "awalon", "aerodrome", "adciv", "admil", "advfr", "inop", "callsign", "aircraft", "map",
        "coordination", "conversion", "sytop", "aup", "other", "about", "emergency", "admin"]
LABELS = ["?", "RADIO", "METEO", "AWALON", "AERODROME", "AD CIV", "AD MIL", "AD VFR", "INOP", "CALLSIGN", "AIRCRAFT", "MAP",
          "COORDINATION", "CONVERSION", "SYT OP", "AUP", "OTHER", "ABOUT", "EMERGENCY", "ADMIN"]
# 0.13.0 (issue #23): podmenu OTHER alfabetycznie jak w PANDORZE (id = adres #other/<id>); 0.13.1 (issue #25): bez
# PHRASEOLOGY
OTHER_SUBS = [("4p", "4P"), ("aftn", "AFTN"), ("bomb-phone", "BOMB PHONE"), ("braking-action", "BRAKING ACTION"),
              ("checklist", "CHECKLIST"), ("docs", "DOCS"), ("flight-plan", "FLIGHT PLAN"), ("fmp", "FMP"),
              ("holding", "HOLDING"), ("ia", "IA"), ("light-gun", "LIGHT GUN"), ("meteo", "METEO"),
              ("nato-weather", "NATO WEATHER"), ("position", "POSITION"),
              ("regcause", "REGCAUSE"), ("squawk", "SQUAWK"), ("vfr-minima", "VFR MINIMA")]
# stare adresy zakładek przeniesionych do podmenu OTHER (słownik MOVED w app.js, kilka linijek)
MOVED_SRC = re.search(r"^const MOVED = \{\n.*?^\};$", APP, re.M | re.S).group(0)


def _menu_buttons():
    nav = INDEX[INDEX.index('<nav id="tabs">'):INDEX.index("</nav>")]
    return re.findall(r"<button([^>]*)>([^<]*)</button>", nav)


def test_menu_order():
    buttons = _menu_buttons()
    # ← na samej górze, potem zakładki w kolejności z PANDORY; EMERGENCY na czerwono na dole, ADMIN ukryty
    assert 'id="nav-back"' in buttons[0][0] and buttons[0][1] == "←" and "disabled" in buttons[0][0]
    tabs = [(re.search(r'data-tab="([^"]+)"', a).group(1), label) for a, label in buttons[1:]]
    assert [t for t, _ in tabs] == MENU
    assert [label for _, label in tabs] == LABELS
    assert 'class="red"' in buttons[-2][0] and "hidden" in buttons[-1][0]
    assert 'class="brand" href="#home"' in INDEX


def test_every_tab_has_module():
    keys = re.search(r"const TABS = \{([^}]+)\}", APP).group(1)
    keys = [k.strip() for k in keys.split(",") if k.strip()]
    assert sorted(keys) == sorted(MENU)
    for key in MENU:
        if key in ("adciv", "admil", "advfr"):
            continue  # jeden moduł tabs/aip.js
        assert re.search(rf'^import {key} from "\./tabs/{key}\.js";$', APP, re.M), key
        assert (FRONTEND / "js" / "tabs" / f"{key}.js").is_file()
    # po uruchomieniu zawsze HOME
    assert 'open("home");' in APP and 'open("about");' not in APP


def test_docs_moved_to_other():
    """DOCS nie ma już w menu: to domyślna podzakładka OTHER (#other/docs/<plik>; 0.13.0: w podmenu alfabetycznie, ale
    OTHER dalej otwiera się na DOCS); stare adresy #docs i #docs/<plik> app.js przekierowuje na OTHER › DOCS (link #docs
    bez arg zostawia otwarty dokument), a przycisk COORDINATION › w panelu LOA w RADIO otwiera LOA w COORDINATION ›
    DOKUMENTY."""
    assert not (FRONTEND / "js" / "tabs" / "docs.js").exists() and "docs" not in MENU
    assert '  docs: (arg) => ["other", arg === undefined ? undefined : arg ? "docs/" + arg : "docs"],' in MOVED_SRC
    assert '  phraseology: () => ["other", undefined],' in MOVED_SRC
    assert "if (Object.hasOwn(MOVED, tab)) [tab, arg] = MOVED[tab](arg);" in APP
    other = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    assert 'import { isCoordFile, mountDocs } from "../docs.js";' in other and "soon(" not in other
    subs = re.findall(r'\{ id: "([^"]+)", label: "([^"]+)"', other)
    assert subs == OTHER_SUBS
    assert 'remember("other", argOf())' in other and "activate(arg)" in other and "SUBS" not in other
    # tabela stron zamiast łańcucha if/else; domyślna podzakładka przez ogólną opcję first w subtabs()
    assert "const PAGES = [" in other and 'const DEFAULT = "docs";' in other and "first: DEFAULT" in other
    api_src = (FRONTEND / "js" / "api.js").read_text("utf-8")
    assert "tabs.find((x) => !x.sep && x.id === opts.first)" in api_src
    docs = (FRONTEND / "js" / "docs.js").read_text("utf-8")
    assert "export function mountDocs(" in docs and "remember(" not in docs and "frameGo(" in docs
    # plik spoza listy (wpisany ręcznie, stary odnośnik) = pierwszy dokument, nigdy pusty podgląd
    assert "docs.find((x) => argOf(x.url) === arg) || docs[0];" in docs
    # 0.12.3: stary adres z plikiem LOA/LOP (#docs/LOA/<plik>, #other/docs/LOA/<plik>) otwiera COORDINATION › DOKUMENTY,
    # a przekierowanie z activate() dziedziczy krok historii (Wstecz nie wraca na przekierowanie)
    assert 'if (isCoordFile(f)) return navigate("coordination", "docs/" + f);' in other
    assert "if (activating) push = activating.push;" in APP and "const me = { tab, push };" in APP
    radio = (FRONTEND / "js" / "tabs" / "radio.js").read_text("utf-8")
    # 0.12.3: LOA z panelu RADIO otwiera się w COORDINATION › DOKUMENTY (OTHER › DOCS pokazuje pozostałe dokumenty)
    assert 'navigate("coordination", "docs/" + doc.dataset.coord)' in radio and 'navigate("docs"' not in radio
    assert 'navigate("other"' not in radio


def _code(src):
    """Kod JS bez komentarzy (/* */ i // od początku linii albo po spacji)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M)


def test_phraseology_removed():
    """0.13.1 (issue #25): PHRASEOLOGY usunięta (do 0.13.0 podzakładka OTHER, do 0.12.2 osobna zakładka): bez modułu,
    bez podzakładki, bez adresu w /api/config i bez sprawdzania osadzania. Stary adres #phraseology otwiera OTHER
    w jego stanie (MOVED bez podzakładki), #other/phraseology to nieznane id (DOCS)."""
    assert "phraseology" not in MENU and not (FRONTEND / "js" / "phraseology.js").exists()
    assert not (FRONTEND / "js" / "tabs" / "phraseology.js").exists()
    other = _code((FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8"))
    assert "phraseology" not in other.lower()
    for path in (FRONTEND / "js").rglob("*.js"):
        code = _code(path.read_text("utf-8"))
        assert "embed-check/phraseology" not in code and "links.phraseology" not in code, path.name
    assert "phraseology_url" not in (ROOT_DIR / "backend" / "app" / "config.py").read_text("utf-8")
    system = (ROOT_DIR / "backend" / "app" / "routers" / "system.py").read_text("utf-8")
    assert '"phraseology"' not in system and "phraseology_url" not in system
    assert '  phraseology: () => ["other", undefined],' in MOVED_SRC


def test_checklist_moved_to_other():
    """0.12.6 (issue #21): CHECKLIST nie jest już w menu, tylko podzakładką OTHER po PHRASEOLOGY (#other/checklist/<id>,
    checklisty w drugim podmenu). Stare adresy #checklist i #checklist/<id> przekierowuje app.js, kafelek w ABOUT
    (ctx.open("checklist")) też. Zaznaczenia pod tym samym kluczem co w dawnej zakładce (zapisany postęp zostaje),
    a AERODROME › OVERVIEW dalej bierze renderChecklist z checklist.js."""
    assert "checklist" not in MENU and not (FRONTEND / "js" / "tabs" / "checklist.js").exists()
    assert 'data-tab="checklist"' not in INDEX and "checklist" not in re.search(r"const TABS = \{([^}]+)\}", APP).group(1)
    assert '  checklist: (arg) => ["other", arg ? "checklist/" + arg : "checklist"],' in MOVED_SRC
    chk = (FRONTEND / "js" / "checklist.js").read_text("utf-8")
    assert "export function renderChecklist(el, chk, key)" in chk and "export function mountChecklists(pane, " in chk
    assert "`checklist.tab.${c.id}`" in chk and "{ remember: false }" in chk
    other = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    assert 'import { mountChecklists } from "../checklist.js";' in other
    overview = (FRONTEND / "js" / "overview.js").read_text("utf-8")
    assert 'import { renderChecklist } from "./checklist.js";' in overview
    # żaden odnośnik w aplikacji nie prowadzi już wprost do zakładki checklist (poza przekierowaniem)
    for path in (FRONTEND / "js").rglob("*.js"):
        src = path.read_text("utf-8")
        assert not re.search(r"""navigate\(\s*["']checklist["']|href=["']#checklist""", src), path.name


def test_strip_removed():
    """0.13.0 (issue #23): zakładki STRIP nie ma (paski EFES, tabs/strip.js, strips.js, strips.css). Stary adres
    #strip/<ICAO> otwiera AERODROME › <ICAO> › TRAFFIC (DMAN/AMAN, najbliższy widok), samo #strip AERODROME.
    Reguły ze strips.css używane w AERODROME › INFO (próbki .lg w karcie Traffic, .aero-ruch) są w style.css.
    Endpoint /api/aerodromes/{icao}/strips i strip_board zostają: to dane DMAN (test_dman.py)."""
    assert "strip" not in MENU and 'data-tab="strip"' not in INDEX and "css/strips.css" not in INDEX
    for path in ("js/tabs/strip.js", "js/strips.js", "css/strips.css"):
        assert not (FRONTEND / path).exists(), path
    assert "strip" not in [k.strip() for k in re.search(r"const TABS = \{([^}]+)\}", APP).group(1).split(",")]
    assert "tabs/strip.js" not in APP
    assert '  strip: (arg) => ["aerodrome", /^[A-Za-z]{4}$/.test(arg || "") ? arg.toUpperCase() + "/dman" : arg],' in MOVED_SRC
    for path in (FRONTEND / "js").rglob("*.js"):
        src = path.read_text("utf-8")
        assert not re.search(r"""navigate\(\s*["']strip["']|href=["']#strip|tabs/strip\.js|strips\.js|mountStrips\(|"""
                             r"""open\(\s*["']strip["']|data-open=["']strip""", src), path.name
    # bez martwych reguł pasków (.sx-bar, .sx-bay ze strips.js) w pozostałych arkuszach
    for path in (FRONTEND / "css").glob("*.css"):
        assert not re.search(r"\.sx-(bar|bay)\b", path.read_text("utf-8")), path.name
    css = (FRONTEND / "css" / "style.css").read_text("utf-8")
    for rule in (".lg.dep {", ".lg.arr {", ".lg.loc {", ".lg.plan {", ".aero-col > .card.aero-ruch {", ".aero-ruch .ruch-line {"):
        assert rule in css, rule
    aero = (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    assert '<s class="lg dep"></s>' in aero and 'class="card aero-ruch"' in aero


def test_squawk_moved_to_other():
    """0.13.0 (issue #23): SQUAWK nie jest już w menu, tylko podzakładką OTHER (#other/squawk/<kod>). Stare adresy
    #squawk i #squawk/<kod> przekierowuje app.js (jedna linijka w MOVED); ABOUT opisuje SQUAWK w kafelku OTHER.
    Moduł poza tabs/ (jak checklist.js i phraseology.js), arkusz squawk.css zaczepiony o panel, nie o zakładkę."""
    assert "squawk" not in MENU and not (FRONTEND / "js" / "tabs" / "squawk.js").exists()
    assert 'data-tab="squawk"' not in INDEX and "squawk" not in re.search(r"const TABS = \{([^}]+)\}", APP).group(1)
    assert "squawk" not in re.findall(r"^import (\w+) from", APP, re.M)
    assert '  squawk: (arg) => ["other", arg ? "squawk/" + arg : "squawk"],' in MOVED_SRC
    sq = (FRONTEND / "js" / "squawk.js").read_text("utf-8")
    # 0.13.0: addr (kod w adresie) i onInput (tekst pola wraca po innej podzakładce)
    assert "export function mountSquawk(pane, { start = \"\", addr: startAddr, onCode = () => {}, onInput = () => {} } = {})" in sq
    assert 'import { api, esc, h, ONLINE_EVENT } from "./api.js";' in sq and "remember(" not in sq
    other = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    assert 'import { mountSquawk } from "../squawk.js";' in other
    css = (FRONTEND / "css" / "squawk.css").read_text("utf-8")
    assert 'data-tab="squawk"' not in css and ".sq-pane :is(.btn, .field, .card, .card h3, input, .tag) { border-radius: 0; }" in css
    # żaden odnośnik w aplikacji nie prowadzi już wprost do zakładki squawk (poza przekierowaniem)
    for path in (FRONTEND / "js").rglob("*.js"):
        src = path.read_text("utf-8")
        assert not re.search(r"""navigate\(\s*["']squawk["']|href=["']#squawk""", src), path.name


def test_about_tiles_open_current_tabs():
    """Kafelki ABOUT (ctx.open(<zakładka>) bez arg) prowadzą tylko do zakładek z menu, nigdy przez przekierowanie MOVED:
    0.13.0 bez kafelka STRIP (prowadził do AERODROME w dowolnym stanie, pasków już nie ma) i SQUAWK (podzakładka OTHER,
    opisana w kafelku OTHER), z kafelkiem AWALON po METEO."""
    about = (FRONTEND / "js" / "tabs" / "about.js").read_text("utf-8")
    block = about[about.index("const TILES = ["):]
    block = block[:block.index("];") + 2]
    tiles = re.findall(r'^  \["([a-z]+)", "([^"]+)", "([^"]+)"\],$', block, re.M)
    assert len(tiles) == block.count("\n  [")
    ids = [t[0] for t in tiles]
    tabs = [k.strip() for k in re.search(r"const TABS = \{([^}]+)\}", APP).group(1).split(",")]
    moved = re.findall(r"^  (\w+): ", MOVED_SRC, re.M)
    assert "strip" in moved and "squawk" in moved
    for tab in ids:
        assert tab in tabs and tab in MENU and tab not in moved, tab
    assert "strip" not in ids and "squawk" not in ids and ids.index("awalon") == ids.index("meteo") + 1
    text = {t[0]: t[2] for t in tiles}
    assert "SQUAWK" in text["other"] and "REGCAUSE" in text["other"] and "FMP" in text["other"]
    assert "10 000 ft" in text["awalon"] and "approach wind" not in text["meteo"]
    assert not re.search(r"strip|EFES|extended label", block, re.I)


def test_hidden_menu_button_takes_no_space():
    """display:block przycisków menu przykrywał [hidden]: ADMIN był widoczny dla każdego."""
    css = (FRONTEND / "css" / "style.css").read_text("utf-8")
    assert ".menu nav button[hidden] { display: none; }" in css


def test_all_css_linked():
    """Każdy arkusz z frontend/css jest podpięty w index.html (zakładki rundy 10 dopisują style bez zmian index.html)."""
    linked = re.findall(r'href="/static/css/([^"]+\.css)"', INDEX)
    files = sorted(p.name for p in (FRONTEND / "css").glob("*.css"))
    assert sorted(linked) == files
    for name in ("home.css", "aerolist.css", "dman.css", "sytop.css", "meteoimg.css"):
        assert name in linked


NODE_SCRIPT = r"""
const api = await import(process.argv[2]);
const home = await import(process.argv[3]);
const moved = await import(process.argv[4]);
const hashes = ["#aerodrome/fir/ED", "#aerodrome/EPWA", "#meteo", "#home", "", "#", "#docs/LOA/LOA%20EPWW%20EDMM%20(AIRAC%202602).pdf",
  "#map/%E2%82%AC%", "#checklist/a/a2"];
const roundtrip = [["aerodrome", "fir/ED"], ["map", "LOT 3 #1 100%"], ["other", "docs/LOA/LOA EPWW ESAA Szwecja (v2.3, 19.02.2026).pdf"],
  ["meteo", ""], ["aircraft", "maker/airbus"]];
console.log(JSON.stringify({
  parsed: hashes.map((h) => api.parseHash(h)),
  built: roundtrip.map(([t, a]) => api.hashOf(t, a)),
  back: roundtrip.map(([t, a]) => api.parseHash(new URL("http://x/" + api.hashOf(t, a)).hash)),
  hello: [null, { user: null }, { user: { cid: "1234567", name: "Jan Kowalski" } }, { user: { cid: "1234567", name: null } },
    { user: { cid: 7, name: "<b>X</b>" } }].map(home.greeting),
  // bez routera (app.js) navigate i remember nic nie robią
  noop: [api.navigate("meteo", "qnh"), api.remember("meteo", "qnh"), api.stash("aerodrome", { q: "BER" }), api.stashed("aerodrome")],
  // stare adresy #docs: przycisk/link bez arg, "#docs", "#docs/<plik>" (undefined w JSON = null)
  moved: [undefined, "", "LOA/LOA EPWW EDMM (AIRAC 2602).pdf"].map((a) => moved.MOVED.docs(a)),
  phraseology: moved.MOVED.phraseology(),
  // kafelek ABOUT / link #checklist bez arg, "#checklist", "#checklist/<id>"
  checklist: [undefined, "", "close-position"].map((a) => moved.MOVED.checklist(a)),
  // 0.13.0: stare #strip, #strip/<ICAO> (także małymi literami) i adres, który nie jest kodem lotniska
  strip: [undefined, "", "EPWA", "epkk", "x", "EPWA/1"].map((a) => moved.MOVED.strip(a)),
  // kafelek ABOUT / link #squawk bez arg, "#squawk", "#squawk/7700"
  squawk: [undefined, "", "7700"].map((a) => moved.MOVED.squawk(a)),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "home.mjs").write_text((FRONTEND / "js" / "tabs" / "home.js").read_text("utf-8").replace('"../api.js"', '"./api.mjs"'), "utf-8")
    # MOVED z app.js (całego app.js Node nie wczyta: DOM)
    (d / "moved.mjs").write_text("export " + MOVED_SRC + "\n", "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "api.mjs").as_uri(), (d / "home.mjs").as_uri(), (d / "moved.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_parse_hash(js):
    # arg = wszystko po pierwszym "/", odkodowane; zły zapis %-owy zostaje jak jest
    assert js["parsed"] == [
        {"tab": "aerodrome", "arg": "fir/ED"}, {"tab": "aerodrome", "arg": "EPWA"}, {"tab": "meteo", "arg": ""},
        {"tab": "home", "arg": ""}, {"tab": "", "arg": ""}, {"tab": "", "arg": ""},
        {"tab": "docs", "arg": "LOA/LOA EPWW EDMM (AIRAC 2602).pdf"}, {"tab": "map", "arg": "%E2%82%AC%"},
        {"tab": "checklist", "arg": "a/a2"}]


def test_hash_roundtrip(js):
    assert js["built"][0] == "#aerodrome/fir/ED" and js["built"][3] == "#meteo" and js["built"][4] == "#aircraft/maker/airbus"
    assert "#" not in js["built"][1][1:] and " " not in js["built"][2]
    # adres zbudowany przez hashOf, przepuszczony przez przeglądarkowy URL, wraca jako ten sam arg
    assert [x["arg"] for x in js["back"]] == ["fir/ED", "LOT 3 #1 100%", "docs/LOA/LOA EPWW ESAA Szwecja (v2.3, 19.02.2026).pdf",
                                              "", "maker/airbus"]


def test_moved_docs(js):
    # bez arg OTHER zostaje w swoim stanie (otwarty dokument), "" = pierwszy dokument, plik = ten PDF
    assert js["moved"] == [["other", None], ["other", "docs"], ["other", "docs/LOA/LOA EPWW EDMM (AIRAC 2602).pdf"]]
    # 0.13.1: bez PHRASEOLOGY stary adres otwiera OTHER w jego stanie (undefined w JSON = null)
    assert js["phraseology"] == ["other", None]
    # CHECKLIST: bez arg i "" = pierwsza checklista w OTHER › CHECKLIST, id = ta checklista
    assert js["checklist"] == [["other", "checklist"], ["other", "checklist"], ["other", "checklist/close-position"]]
    # STRIP: bez arg AERODROME w swoim stanie, "" = domyślny ekran, ICAO = TRAFFIC (DMAN/AMAN) tego lotniska, reszta
    # jak wpisany adres AERODROME (zły kod: OVERVIEW)
    assert js["strip"] == [["aerodrome", None], ["aerodrome", ""], ["aerodrome", "EPWA/dman"], ["aerodrome", "EPKK/dman"],
                           ["aerodrome", "x"], ["aerodrome", "EPWA/1"]]
    # SQUAWK: bez arg i "" = OTHER › SQUAWK, kod = ten kod w polu
    assert js["squawk"] == [["other", "squawk"], ["other", "squawk"], ["other", "squawk/7700"]]


def test_home_greeting(js):
    assert js["hello"] == ["Welcome", "Welcome", "Welcome, Jan Kowalski (1234567)", "Welcome, 1234567", "Welcome, <b>X</b> (7)"]
    # HOME pokazuje powitanie przez esc() (imię z VATSIM to dane z zewnątrz)
    assert "${esc(greeting(ctx.me))}" in (FRONTEND / "js" / "tabs" / "home.js").read_text("utf-8")
    assert js["noop"] == [None, None, None, None]


def test_aerodrome_uses_navigation_api():
    """Podzakładka (0, listy FIR-ów) i wybór lotniska to kroki do cofnięcia (remember), RUCH idzie przez dman.js."""
    src = (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    assert "history.replaceState" not in src and 'remember("aerodrome", a)' in src
    assert "mountDman(" in src and "mountStrips(" not in src
    assert "export function mountDman(" in (FRONTEND / "js" / "dman.js").read_text("utf-8")


SHELL_JS = ["js/app.js", "js/api.js", "js/tabs/home.js", "js/tabs/admin.js", "js/tabs/soon.js", "sw.js"]
POLISH = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def test_shell_in_english():
    """0.12.5 (issue #18): cała aplikacja po angielsku. Strony powłoki z lang="en", a w kodzie powłoki (bez komentarzy
    i logów konsoli) żadnych polskich napisów; komentarze w kodzie zostają po polsku."""
    for name in ("index.html", "login.html", "offline.html"):
        html = (FRONTEND / name).read_text("utf-8")
        assert '<html lang="en">' in html, name
        text = re.sub(r"<!--.*?-->|/\*.*?\*/", "", html, flags=re.S)
        assert not POLISH.search(text), name
    for name in SHELL_JS:
        src = re.sub(r"/\*.*?\*/", "", (FRONTEND / name).read_text("utf-8"), flags=re.S)
        src = re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M)
        bad = [line.strip() for line in src.splitlines() if POLISH.search(line) and "console." not in line]
        assert not bad, f"{name}: {bad}"
    home = (FRONTEND / "js" / "tabs" / "home.js").read_text("utf-8")
    assert "PREPARE SESSION → AERODROME" in home and "<h3>Position</h3>" in home


def test_sharp_edges():
    """0.12.5 (issue #18): ostre krawędzie jak w PANDORZE: w style.css i na stronach logowania / offline żadnych
    zaokrągleń (border-radius tylko 0); kontrolki i dymki Leafleta też bez zaokrągleń z leaflet.css."""
    for name in ("css/style.css", "login.html", "offline.html"):
        text = re.sub(r"/\*.*?\*/", "", (FRONTEND / name).read_text("utf-8"), flags=re.S)
        radii = re.findall(r"border(?:-[a-z]+)*-radius:\s*([^;}]+)", text)
        assert radii and all(r.strip() == "0" for r in radii), (name, radii)
    css = (FRONTEND / "css" / "style.css").read_text("utf-8")
    assert ".leaflet-bar, .leaflet-control-layers, .leaflet-tooltip, .leaflet-popup-content-wrapper," in css
    # przełącznik .sw: kwadratowy tor i kwadratowa gałka
    assert re.search(r"\.sw input \{[^}]*border-radius: 0;", css)
    assert re.search(r"\.sw input::after \{[^}]*border-radius: 0;", css)


def test_square_native_controls_and_no_drop_shadows():
    """Runda 14 (przegląd): natywne pola wyboru i suwak HORIZON (AMAN) Chromium rysuje z zaokrągleniami mimo
    border-radius 0, więc jeden globalny kwadratowy checkbox (appearance: none, jak .sw) i suwak jak .rb-cut w RADIO.
    Dymki i okienka Leafleta, dymki [data-tip] i panele bez cieni (płasko jak w PANDORZE)."""
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "style.css").read_text("utf-8"), flags=re.S)
    base = re.search(r"(?m)^input\[type=checkbox\] \{([^}]*)\}", css)
    assert base and "appearance: none" in base.group(1) and "border-radius: 0" in base.group(1)
    assert re.search(r"input\[type=checkbox\]:checked::after \{", css)
    assert re.search(r"input\[type=checkbox\]:indeterminate::after \{", css)
    # przełącznik .sw (ta sama waga selektora, później w pliku) zeruje obramowanie i ptaszek z reguły globalnej
    assert css.index("input[type=checkbox] {") < css.index(".sw input {")
    assert re.search(r"\.sw input \{[^}]*border: 0;", css) and re.search(r"\.sw input::after \{[^}]*transform: none;", css)
    dman = (FRONTEND / "css" / "dman.css").read_text("utf-8")
    assert re.search(r"\.am-hor input \{[^}]*appearance: none;", dman)
    for part in ("-webkit-slider-runnable-track", "-webkit-slider-thumb", "-moz-range-track", "-moz-range-thumb"):
        assert re.search(r"\.am-hor input::" + part + r" \{[^}]*border-radius: 0;", dman), part
    # accent-color przy appearance: none nic nie daje (zostaje tylko przy polach radio w pasku narzędzi)
    for name in ("style.css", "map.css", "dman.css"):
        text = (FRONTEND / "css" / name).read_text("utf-8")
        assert not re.search(r"(checkbox\]|\.chk-row > input|\.am-hor input) \{[^}]*accent-color", text), name
    # cienie: tylko none, wewnętrzne (inset) albo obrys bez rozmycia (0 0 0 Npx)
    for name in ("style.css", "map.css", "dman.css", "radio.css"):
        text = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / name).read_text("utf-8"), flags=re.S)
        bad = [v.strip() for v in re.findall(r"box-shadow:\s*([^;}]+)", text)
               if not (v.strip() == "none" or v.strip().startswith("inset") or re.match(r"0 0 0 \d+px", v.strip()))]
        assert not bad, (name, bad)
    assert ".leaflet-tooltip, .leaflet-popup-content-wrapper, .leaflet-popup-tip, .leaflet-bar, .leaflet-control-layers { box-shadow: none; }" in css


def test_menu_fits_low_windows():
    """Runda 14 (audyt): przy 1366x657 (laptop 1366x768) lewe menu się przewijało, a EMERGENCY chował się do połowy pod
    zegarem. 0.13.1 (issue #25): przyciski 137 x 28 px z marginesem 1,5 px (rząd co 31 px), a gdy 21 rzędów menu
    (← … EMERGENCY, ADMIN) z zegarem, logo i użytkownikiem się nie mieści, jedna wysokość --btn-h (na body) zmniejsza
    po równo przyciski menu i każdego podmenu (najmniej 16 px), więc rzędy obu kolumn dalej stoją na jednej wysokości.
    Budżet zawsze liczy 21 rzędów (także bez ADMIN), pasek u góry (18 px) i stałe wysokości zegara, logo i użytkownika
    (Playwright: 1366x768 z użytkownikiem 25,33 px, 1366x657 23,19 / 20,05 px, bez przewijania menu)."""
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "style.css").read_text("utf-8"), flags=re.S)

    def px(pattern):
        return float(re.search(pattern, css).group(1))

    rows = int(re.search(r"--menu-rows: (\d+);", css).group(1))
    assert rows == len(_menu_buttons()) == 21
    assert ("--btn-h: clamp(16px, calc((var(--view-h) - var(--topbar-h) - 2 * var(--col-pad) - var(--foot-h)) / var(--menu-rows)"
            " - 2 * var(--btn-m)), var(--btn-h-max)); }") in css
    # --btn-h na body, tam gdzie zalogowany użytkownik zmienia --foot-h (na :root byłaby liczona ze stałą --foot-h)
    assert re.search(r"(?m)^body \{ --view-h: 100vh; --foot-h: 80px;\s+--btn-h: clamp", css)
    # runda 17 (przegląd): wysokość z widocznej części okna, nie z samego 100vh. W Chrome na Androidzie (i innych
    # przeglądarkach z paskiem adresu) 100vh to okno bez paska, a strona się nie przewija, więc pasek zostaje: 1280x800
    # z paskiem (widać 744 px) dawało 26,84 px zamiast 24,19 i EMERGENCY / ADMIN wychodziły pod zegar. Osobna zmienna:
    # 100vh dla przeglądarek bez svh, 100svh (okno z paskiem, tyle co html, body { height: 100% }) w @supports; drugie
    # --btn-h z svh obok pierwszego wygrywałoby zawsze, także tam, gdzie svh jest nieznane
    assert "@supports (height: 100svh) { body { --view-h: 100svh; } }" in css
    assert css.count("--btn-h:") == 1 and "100vh" not in css.replace("--view-h: 100vh;", "", 1)
    assert "html, body { height: 100%; margin: 0; }" in css
    assert "body:has(#userbox:not([hidden])) { --foot-h: 146px; }" in css
    assert ".menu nav { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; }" in css
    # stałe wysokości dołu menu: zegar z AIRAC + logo = --foot-h bez użytkownika, + użytkownik = z użytkownikiem
    clock = px(r"(?m)^\.clockbox \{[^}]*?(?<![-\w])height: ([\d.]+)px;")
    brand = px(r"(?m)^\.menu \.brand \{[^}]*?(?<![-\w])height: ([\d.]+)px;")
    user = px(r"(?m)^\.userbox \{[^}]*?(?<![-\w])height: ([\d.]+)px;")
    assert (clock, brand, user) == (46, 34, 66) and clock + brand == 80 and clock + brand + user == 146
    # treść mieści się w tych wysokościach: ramka + padding 3 + zegar 24 + AIRAC 16; ramka + 4 + logo 26 + 3
    assert ".clock { font: 20px/24px var(--mono); color: #fff; }" in css and ".clockbox .hint { line-height: 16px; }" in css
    assert 1 + 3 + 24 + 16 <= clock and 1 + 4 + 26 + 3 <= brand
    assert ".menu .brand img { display: block; width: 100%; height: 26px; object-fit: contain; }" in css
    topbar = px(r"--topbar-h: ([\d.]+)px;")
    pad, m, h_max, h_min = px(r"--col-pad: ([\d.]+)px;"), px(r"--btn-m: ([\d.]+)px;"), px(r"--btn-h-max: ([\d.]+)px;"), 16

    def btn_h(vh, foot):
        return min(max(h_min, (vh - topbar - 2 * pad - foot) / rows - 2 * m), h_max)

    def fits(view, foot, h):   # pasek, padding, 21 rzędów i dół menu w widocznej części okna
        return topbar + 2 * pad + rows * (h + 2 * m) + foot <= view + 1e-9

    for vh in (560, 600, 657, 768, 900):
        for foot in (80, 146):
            h = btn_h(vh, foot)
            assert h >= h_min
            if h > h_min:   # mieści się bez przewijania
                assert fits(vh, foot, h), (vh, foot, h)
    assert btn_h(900, 80) == btn_h(900, 146) == btn_h(768, 80) == 28
    assert 25 < btn_h(768, 146) < 26 and btn_h(600, 146) >= 16 and btn_h(657, 146) > 20
    # tablet 1280x800 z paskiem adresu: widać 744 px (svh), 100vh = 800. Z widocznej wysokości menu się mieści, z 100vh
    # nie (26,84 px, 56 px za dużo)
    assert 24.1 < btn_h(744, 146) < 24.2 and fits(744, 146, btn_h(744, 146))
    assert 26.8 < btn_h(800, 146) < 26.9 and not fits(744, 146, btn_h(800, 146))


def test_logo_at_bottom_above_user():
    """0.13.1 (issue #25): "Przenieś logo aplikacji na sam dół bocznego paska, nad informacjami użytkownika." Kolejność
    w menu: przyciski, zegar z AIRAC, logo, użytkownik; bez zalogowanego użytkownika logo jest ostatnie. Odnośnik do HOME
    bez zmian."""
    menu = INDEX[INDEX.index('<aside class="menu">'):INDEX.index("</aside>")]
    order = [menu.index(x) for x in ('<nav id="tabs">', "</nav>", '<div class="clockbox">', '<a class="brand" href="#home"',
                                     '<div id="userbox" class="userbox" hidden></div>')]
    assert order == sorted(order) and menu.count('class="brand"') == 1
    assert re.search(r'<a class="brand" href="#home"[^>]*><img src="/static/icons/polids-logo-bez-podpisu.svg" alt="PolIDS"></a>\s*'
                     r'<div id="userbox"', menu)
