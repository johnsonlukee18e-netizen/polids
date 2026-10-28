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
# PHRASEOLOGY w OTHER; 0.12.6 (issue #21): CHECKLIST w OTHER; 0.13.0 (issue #23): AWALON po METEO
MENU = ["home", "radio", "meteo", "awalon", "aerodrome", "adciv", "admil", "advfr", "inop", "callsign", "aircraft", "map",
        "coordination", "conversion", "sytop", "aup", "strip", "squawk", "other", "about", "emergency", "admin"]
LABELS = ["?", "RADIO", "METEO", "AWALON", "AERODROME", "AD CIV", "AD MIL", "AD VFR", "INOP", "CALLSIGN", "AIRCRAFT", "MAP",
          "COORDINATION", "CONVERSION", "SYT OP", "AUP", "STRIP", "SQUAWK", "OTHER", "ABOUT", "EMERGENCY", "ADMIN"]
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
    """DOCS nie ma już w menu: to pierwsza podzakładka OTHER (#other/docs/<plik>); stare adresy #docs i #docs/<plik>
    app.js przekierowuje na OTHER › DOCS (link #docs bez arg zostawia otwarty dokument), a przycisk COORDINATION ›
    w panelu LOA w RADIO otwiera LOA w COORDINATION › DOKUMENTY."""
    assert not (FRONTEND / "js" / "tabs" / "docs.js").exists() and "docs" not in MENU
    assert '  docs: (arg) => ["other", arg === undefined ? undefined : arg ? "docs/" + arg : "docs"],' in MOVED_SRC
    assert '  phraseology: () => ["other", "phraseology"],' in MOVED_SRC
    assert "if (Object.hasOwn(MOVED, tab)) [tab, arg] = MOVED[tab](arg);" in APP
    other = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    assert 'import { isCoordFile, mountDocs } from "../docs.js";' in other and "soon(" not in other
    subs = re.findall(r'\{ id: "([^"]+)", label: "([^"]+)"', other)
    assert subs == [("docs", "DOCS"), ("phraseology", "PHRASEOLOGY"), ("checklist", "CHECKLIST")]
    assert 'remember("other", argOf())' in other and "activate(arg)" in other and "SUBS" not in other
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


def test_phraseology_moved_to_other():
    """0.12.3: PHRASEOLOGY nie jest już w menu, tylko podzakładką OTHER po DOCS (#other/phraseology); stary adres
    #phraseology przekierowuje app.js."""
    assert "phraseology" not in MENU and not (FRONTEND / "js" / "tabs" / "phraseology.js").exists()
    phr = (FRONTEND / "js" / "phraseology.js").read_text("utf-8")
    assert "export function mountPhraseology(pane, ctx)" in phr and "/api/embed-check/phraseology" in phr
    other = (FRONTEND / "js" / "tabs" / "other.js").read_text("utf-8")
    assert 'import { mountPhraseology } from "../phraseology.js";' in other


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
    assert js["phraseology"] == ["other", "phraseology"]
    # CHECKLIST: bez arg i "" = pierwsza checklista w OTHER › CHECKLIST, id = ta checklista
    assert js["checklist"] == [["other", "checklist"], ["other", "checklist"], ["other", "checklist/close-position"]]


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


def _media(css, query):
    """Treść bloku @media (query) { ... } (jeden poziom zagnieżdżenia)."""
    i = css.index(f"@media ({query}) {{")
    depth, j = 0, css.index("{", i)
    for k in range(j, len(css)):
        depth += {"{": 1, "}": -1}.get(css[k], 0)
        if not depth:
            return css[j + 1:k]
    raise AssertionError(query)


def test_menu_fits_low_windows():
    """Runda 14 (audyt): przy 1366x657 (laptop 1366x768) lewe menu się przewijało, a EMERGENCY chował się do połowy pod
    zegarem. Poniżej 900 px przyciski menu są w kolumnie flex i zmniejszają się po równo (do min-height), więc wszystkie
    przyciski z EMERGENCY i ADMIN oraz zegar z AIRAC mieszczą się bez przewijania do 600 px wysokości, także z
    zalogowanym użytkownikiem (Playwright: 1366x600 → 20,5 px na przycisk, z użytkownikiem 17,6 px). Od 900 px wygląd
    bez zmian (reguły bez @media nietknięte). 0.12.6: bez CHECKLIST (w OTHER) jeden przycisk mniej."""
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "style.css").read_text("utf-8"), flags=re.S)
    low, lower = _media(css, "max-height: 899px"), _media(css, "max-height: 820px")
    assert ".menu nav { display: flex; flex-direction: column; }" in low
    btn = re.search(r"#tabs button \{([^}]*)\}", low).group(1)
    assert "flex: 0 1 auto" in btn and "padding-top: 0; padding-bottom: 0" in btn
    height = float(re.search(r"(?<![-\w])height: ([\d.]+)px", btn).group(1))
    min_h = float(re.search(r"min-height: ([\d.]+)px", btn).group(1))
    line = float(re.search(r"line-height: ([\d.]+)px", btn).group(1))
    # wysokość bez ściskania jak przy paddingu 5 px (od 900 px), linia mieści się w najniższym przycisku (tekst na środku)
    assert height == 5 + 14 * 1.2 + 5 + 2 and line <= min_h - 2
    assert re.search(r"#tabs button \{ height: 24\.8px; margin-bottom: 1px; \}", lower)   # 3 + 16,8 + 3 + ramka
    # w flex marginesy się nie łączą: odstęp nad EMERGENCY / ADMIN jak w układzie blokowym (10 px, od 820 px 6 px)
    assert "#tabs button.red, #tabs button.admin { margin-top: 8px; }" in low
    assert "#tabs button.red, #tabs button.admin { margin-top: 5px; }" in lower
    assert ".menu nav button { padding: 5px 6px; margin-bottom: 2px; line-height: 1.2; }" in css
    assert ".menu nav { flex: 1; overflow-y: auto; }" in css
    # budżet 600 px (pomiary Playwright przy 1366x600): logo z paddingiem menu 45,5 px, zegar z AIRAC 49,8 px,
    # użytkownik z wylogowaniem 66 px; 23 przyciski (← ... EMERGENCY, ADMIN, od 0.13.0 z AWALON) w najniższym wariancie
    n = len(_menu_buttons())
    assert n == 23
    margins = n * 1 + 5 + 5
    for user in (0, 66):
        nav = 600 - 45.5 - 49.8 - user - 6
        assert n * min_h + margins <= nav, (user, nav)
    # kolejność: niskie okno przed 820 px (te same selektory, niższe okno nadpisuje)
    assert css.index("@media (max-height: 899px)") < css.index("@media (max-height: 820px)")
