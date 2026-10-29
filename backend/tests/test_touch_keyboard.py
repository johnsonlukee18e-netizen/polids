"""0.13.1 (issue #25): "AIRCRAFT i CALLSIGN dodaj podzakładkę () która będzie klawiaturą dotykową. Rozmiar powinien być
jednakowy jak ALL i być pod przyciskiem ALL." Przycisk KEYBOARD pod ALL przełącza klawiaturę dotykową na dole panelu
(cyfry, QWERTY, "-", CLEAR / SPACE / BACKSPACE): klawisz wpisuje w polu wyszukiwania w miejscu kursora i wysyła zdarzenie
input, więc działa zwykłe wyszukiwanie z debounce. Funkcje api.js (KEYBOARD_ROWS, keyboardHtml, applyKey, touchKeyboard)
uruchamiane w Node z atrapą DOM; wygląd keyboard.css sprawdzany w arkuszu."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
API = (FRONTEND / "js" / "api.js").read_text("utf-8")
INDEX = (FRONTEND / "index.html").read_text("utf-8")
KCSS = (FRONTEND / "css" / "keyboard.css").read_text("utf-8")

# atrapa DOM: h() z api.js robi <template>, więc document.createElement("template") daje element z HTML-em
# klawiatury; pole wyszukiwania i przycisk KEYBOARD to te same atrapy (zdarzenia, klasy, atrybuty, zaznaczenie)
NODE_SCRIPT = r"""
class El {
  constructor(tag) { this.tag = tag; this.on = {}; this.attrs = {}; this.cls = new Set(); this.dataset = {}; this.hidden = false;
    this.value = ""; this.selectionStart = 0; this.selectionEnd = 0; this.events = []; this.focusOpts = [];
    this.classList = { toggle: (c, on) => (on ? this.cls.add(c) : this.cls.delete(c)), contains: (c) => this.cls.has(c) }; }
  addEventListener(t, f) { (this.on[t] ||= []).push(f); }
  fire(t, ev) { (this.on[t] || []).forEach((f) => f(ev)); }
  dispatchEvent(ev) { this.events.push([ev.type, ev.bubbles]); this.fire(ev.type, ev); return true; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  set inputMode(v) { this.attrs.inputmode = v; }
  get inputMode() { return this.attrs.inputmode ?? ""; }
  focus(opts) { this.focusOpts.push(opts); globalThis.document.activeElement = this; }
  setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b; }
  closest(sel) { return this.tag === "button" && (sel === "button" || (sel === "button[data-k]" && "k" in this.dataset)) ? this : null; }
}
globalThis.document = { activeElement: null, createElement() {
  const t = { innerHTML: "" };
  Object.defineProperty(t, "content", { get() { const e = new El("div"); e.html = t.innerHTML; return { firstElementChild: e }; } });
  return t; } };
const url = process.argv[2];
const api = await import(url);
const key = (k) => { const b = new El("button"); b.dataset.k = k; return b; };
// stuknięcie klawisza: pointerdown (bez domyślnej akcji = fokus zostaje w polu), potem click
const tap = (kb, k) => { const t = key(k); let prevented = false;
  kb.el.fire("pointerdown", { target: t, preventDefault() { prevented = true; } }); kb.el.fire("click", { target: t }); return prevented; };
const st = (kb, input, button) => ({ hidden: kb.el.hidden, active: button.classList.contains("active"), pressed: button.getAttribute("aria-pressed"),
  im: input.getAttribute("inputmode"), value: input.value, caret: [input.selectionStart, input.selectionEnd], events: input.events.length,
  focused: document.activeElement === input, stored: api.choiceGet(api.KEYBOARD_KEY) });
const out = { rows: api.KEYBOARD_ROWS, html: api.keyboardHtml(), key: api.KEYBOARD_KEY };
const cases = [["", null, null, "B"], ["B", null, null, "7"], ["B738", 1, 1, "X"], ["B738", 1, 3, "X"], ["B738", 0, 0, "BACKSPACE"],
  ["B738", 4, 4, "BACKSPACE"], ["B738", 1, 3, "BACKSPACE"], ["B738", null, null, "BACKSPACE"], ["AIRBUS", 6, 6, "SPACE"],
  ["B738", 2, 2, "CLEAR"], ["", 0, 0, "CLEAR"], ["B738", 3, 1, "X"], ["B738", -5, 99, "X"], ["B738", 99, null, "-"],
  ["B738", 2, null, "X"], ["B738", 1.7, 1.2, "X"], ["", 0, 0, "BACKSPACE"], [null, undefined, undefined, "1"]];
out.apply = cases.map(([v, s, e, k]) => api.applyKey(v, s, e, k));
// zakładka: pole i KEYBOARD; nic nie zapisano i wskaźnik nie dotykowy, więc zamknięta
const input = new El("input"), button = new El("button");
const kb = api.touchKeyboard(input, button);
out.start = st(kb, input, button);
out.kbdHtml = kb.el.html;
button.fire("click", {});
out.opened = st(kb, input, button);
out.openFocus = input.focusOpts.at(-1);
document.activeElement = null;           // pole bez fokusu: klawisz dopisuje na końcu
out.prevented = ["B", "7", "3", "8"].map((k) => tap(kb, k));
out.typed = st(kb, input, button);
out.inputEvents = [...input.events];
input.setSelectionRange(1, 1);          // fokus w polu (ostatni klawisz go przywrócił), kursor po B
tap(kb, "X");
out.insert = st(kb, input, button);
input.setSelectionRange(0, 0);
tap(kb, "BACKSPACE");                   // na początku: bez zmian i bez zdarzenia input
out.bsStart = st(kb, input, button);
tap(kb, "CLEAR");
out.clear = st(kb, input, button);
tap(kb, "CLEAR");                       // puste pole: bez zdarzenia
out.clearAgain = st(kb, input, button);
kb.el.fire("click", { target: new El("div") });   // klik obok klawiszy
out.miss = st(kb, input, button);
// druga zakładka: ten sam zapisany wybór (otwarta); zamknięcie w niej, sync() w pierwszej zamyka i tutaj
const input2 = new El("input"), button2 = new El("button");
const kb2 = api.touchKeyboard(input2, button2);
out.second = st(kb2, input2, button2);
button2.fire("click", {});
out.secondClosed = st(kb2, input2, button2);
out.firstBeforeSync = st(kb, input, button);
kb.sync();
out.firstSynced = st(kb, input, button);
// bez przycisku (null) też działa
const kb3 = api.touchKeyboard(new El("input"), null);
out.noButton = kb3.el.hidden;
// świeży moduł (nic nie zapisano) przy dotykowym wskaźniku: otwarta od razu
globalThis.matchMedia = (q) => ({ matches: q === "(pointer: coarse)" });
const fresh = await import(url + "?coarse");
const i4 = new El("input"), b4 = new El("button");
const kb4 = fresh.touchKeyboard(i4, b4);
out.coarse = { hidden: kb4.el.hidden, active: b4.classList.contains("active"), im: i4.getAttribute("inputmode") };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text(API, "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "api.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_keyboard_layout(js):
    """Pięć rzędów: cyfry, QWERTY, ASDF…, ZXCV… z "-" (EC-135), na dole CLEAR, SPACE i BACKSPACE (2 + 5 + 3 szerokości
    klawisza = rząd cyfr). Bez ENTER (wyszukiwanie na bieżąco), bez shift i bez polskich liter (wielkość liter bez
    znaczenia w wyszukiwaniu)."""
    assert js["rows"] == [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL"), list("ZXCVBNM-"),
                          ["CLEAR", "SPACE", "BACKSPACE"]]
    rows = re.findall(r'<div class="tk-row">(.*?)</div>', js["html"])
    assert len(rows) == 5 and js["html"].count("<button") == 40
    units = {"w2": 2, "w3": 3, "w5": 5}
    widths = []
    for row, keys in zip(rows, js["rows"]):
        buttons = re.findall(r'<button type="button" class="gbtn tk( w\d)?" data-k="([^"]+)">([^<]+)</button>', row)
        assert [k for _, k, _ in buttons] == keys == [lbl for _, _, lbl in buttons]
        widths.append(sum(units.get(w.strip(), 1) for w, _, _ in buttons))
        assert all(k.isascii() for k in keys)
    assert widths == [10, 10, 9, 8, 10]
    assert re.search(r'class="gbtn tk w2" data-k="CLEAR"', js["html"]) and re.search(r'class="gbtn tk w5" data-k="SPACE"', js["html"])
    assert re.search(r'class="gbtn tk w3" data-k="BACKSPACE"', js["html"])
    assert not re.search(r"ENTER|SHIFT|[ąćęłńóśźż]", js["html"], re.I)


def test_apply_key(js):
    """Czysta funkcja: klawisz na tekście z zaznaczeniem [start, end) daje nowy tekst i kursor."""
    got = [(r["value"], r["caret"]) for r in js["apply"]]
    assert got == [
        ("B", 1), ("B7", 2),                       # bez kursora (null): na końcu
        ("BX738", 2), ("BX8", 2),                  # w miejscu kursora; zaznaczenie (73) zastąpione
        ("B738", 0), ("B73", 3), ("B8", 1),        # BACKSPACE: na początku bez zmian, znak przed kursorem, zaznaczenie
        ("B73", 3),                                # BACKSPACE bez kursora: ostatni znak
        ("AIRBUS ", 7),                            # SPACE to spacja
        ("", 0), ("", 0),                          # CLEAR
        ("BX8", 2),                                # start > end: zamienione (zaznaczenie 1..3)
        ("X", 1),                                  # poza zakresem: przycięte do całego tekstu
        ("B738-", 5),                              # 99 przycięte do końca
        ("B7X38", 3),                              # end null: bez zaznaczenia (end = start)
        ("BX738", 2),                              # ułamki obcięte
        ("", 0), ("1", 1),                         # puste pole, value null
    ]


def test_touch_keyboard_toggle_and_typing(js):
    """KEYBOARD przełącza klawiaturę (zaznaczony, gdy otwarta; aria-pressed), wybór zapisany w choiceSet pod jednym kluczem
    dla AIRCRAFT i CALLSIGN. Otwarta: inputmode=none (bez klawiatury systemu na tablecie), zamknięta: atrybut usunięty.
    Klawisz: pointerdown bez domyślnej akcji (fokus zostaje w polu), tekst w miejscu kursora, fokus w polu, kursor za
    wpisanym znakiem i zdarzenie input (bubbles) tylko, gdy tekst się zmienił."""
    assert js["key"] == "letters.keyboard"
    assert 'class="tkbd" role="group" aria-label="Touch keyboard" hidden>' in js["kbdHtml"]
    start = js["start"]
    assert start["hidden"] is True and start["active"] is False and start["pressed"] == "false" and start["im"] is None
    assert start["stored"] == "" and start["events"] == 0
    opened = js["opened"]
    assert opened["hidden"] is False and opened["active"] is True and opened["pressed"] == "true" and opened["im"] == "none"
    assert opened["stored"] == "1" and opened["focused"] is True and js["openFocus"] == {"preventScroll": True}
    assert js["prevented"] == [True] * 4
    typed = js["typed"]
    assert typed["value"] == "B738" and typed["caret"] == [4, 4] and typed["focused"] is True and typed["events"] == 4
    assert js["inputEvents"] == [["input", True]] * 4
    assert js["insert"]["value"] == "BX738" and js["insert"]["caret"] == [2, 2] and js["insert"]["events"] == 5
    assert js["bsStart"]["value"] == "BX738" and js["bsStart"]["events"] == 5
    assert js["clear"]["value"] == "" and js["clear"]["caret"] == [0, 0] and js["clear"]["events"] == 6
    assert js["clearAgain"]["events"] == 6 and js["miss"]["events"] == 6
    # wspólny wybór: druga zakładka otwarta od razu; zamknięta w niej, po sync() zamknięta i w pierwszej
    assert js["second"]["hidden"] is False and js["second"]["active"] is True and js["second"]["im"] == "none"
    assert js["secondClosed"]["hidden"] is True and js["secondClosed"]["im"] is None and js["secondClosed"]["stored"] == "0"
    assert js["firstBeforeSync"]["hidden"] is False
    synced = js["firstSynced"]
    assert synced["hidden"] is True and synced["active"] is False and synced["im"] is None
    assert js["noButton"] is True
    # nic nie zapisano: otwarta tylko przy dotykowym wskaźniku (pointer: coarse)
    assert js["coarse"] == {"hidden": False, "active": True, "im": "none"}


def test_touch_keyboard_contract():
    """Kod touchKeyboard: przełączanie bez kroku w historii (bez remember), pole bez fokusu = dopisanie na końcu,
    zdarzenie input jak przy pisaniu (debounce zakładki), api.js dalej bez importów."""
    body = API[API.index("export function touchKeyboard("):]
    body = body[:body.index("\n}\n")]
    assert 'el.addEventListener("pointerdown", (e) => { if (e.target.closest("button")) e.preventDefault(); });' in body
    assert 'input.dispatchEvent(new Event("input", { bubbles: true }))' in body
    assert 'input.inputMode = "none"' in body and 'input.removeAttribute("inputmode")' in body
    assert "choiceSet(KEYBOARD_KEY" in body and "choiceGet(KEYBOARD_KEY)" in body and '"(pointer: coarse)"' in body
    assert "document.activeElement === input" in body and "input.setSelectionRange(r.caret, r.caret)" in body
    assert "remember(" not in body and "navigate(" not in body
    assert "return { el, sync: () => show(wanted()) };" in body
    assert not re.search(r"(?m)^import ", API)
    # kod tylko ASCII (polskie znaki tylko w samodzielnych komentarzach)
    for n, line in enumerate(API.splitlines(), 1):
        if "KEYBOARD" in line or "touchKeyboard" in line or "applyKey" in line or "tk-row" in line:
            assert line.lstrip().startswith("//") or line.isascii(), (n, line)


def test_keyboard_css_look():
    """Zielone klawisze PANDORY (.gbtn), ostre krawędzie, bez cieni i poświaty; klawisz co najmniej 40 px wysokości
    (cel dotyku), 44 px w wysokim oknie; :hover tylko przy myszy; [hidden] naprawdę chowa (display: flex go przykrywał)."""
    assert '<link rel="stylesheet" href="/static/css/keyboard.css">' in INDEX
    assert INDEX.index("/static/css/aircraft.css") < INDEX.index("/static/css/keyboard.css")
    css = re.sub(r"/\*.*?\*/", "", KCSS, flags=re.S)
    assert ".tkbd[hidden] { display: none; }" in css
    assert css.index("display: flex; flex-direction: column;") < css.index(".tkbd[hidden] { display: none; }")
    assert all(v.strip() == "0" for v in re.findall(r"border-radius:\s*([^;}]+)", css))
    assert not re.search(r"box-shadow|text-shadow|drop-shadow|filter\s*:|glow|font-weight|bold", css)
    assert not re.search(r"monospace|Consolas|Courier", css)
    key = re.search(r"\.tkbd \.tk \{([^}]*)\}", css).group(1)
    for decl in ("width: var(--tk-w);", "height: var(--tk-h);", "margin: 0;", "padding: 0;", "border-radius: 0;",
                 "font: 18px/1 var(--ui);", "touch-action: manipulation;", "user-select: none;",
                 "-webkit-tap-highlight-color: transparent;"):
        assert decl in key, decl
    heights = [float(v) for v in re.findall(r"--tk-h: ([\d.]+)px;", css)]
    widths = [float(v) for v in re.findall(r"--tk-w: ([\d.]+)px;", css)]
    assert heights == [44, 40] and widths == [56] and min(heights) >= 40
    assert re.search(r"@media \(max-height: 820px\) \{\s*\.tkbd \{ --tk-h: 40px; \}\s*\}", css)
    assert ".tkbd .tk.w2 { width: calc(2 * var(--tk-w) + var(--tk-gap));" in css
    assert ".tkbd .tk.w3 { width: calc(3 * var(--tk-w) + 2 * var(--tk-gap));" in css
    assert ".tkbd .tk.w5 { width: calc(5 * var(--tk-w) + 4 * var(--tk-gap));" in css
    # :hover tylko w @media (hover: hover): po stuknięciu palcem klawisz nie zostaje podświetlony
    hover = re.search(r"@media \(hover: hover\) \{(.*?)\n\}", css, re.S).group(1)
    assert ".tkbd .tk:hover" in hover and css.count(":hover") == 1
    assert ".tkbd .tk:active { background: linear-gradient(#8cff5a, #5fd23a); color: #0b2a06; }" in css
    # klawiatura mieści się w panelu przy każdej szerokości (tablet pionowo: panel węższy niż 601 px): safe center
    # zamiast center (nadmiar nigdy w lewo pod podmenu), najwyżej szerokość panelu, klawisze węższe wg cqw panelu
    kbd = re.search(r"(?m)^\.tkbd \{([^}]*)\}", css).group(1)
    assert "align-self: safe center;" in kbd and "max-width: 100%;" in kbd and "align-self: center" not in kbd
    assert ".ac-pane, .cs-pane { container-type: inline-size; }" in css
    fit = re.search(r"(?m)^\.ac-pane > \.tkbd, \.cs-pane > \.tkbd \{ --tk-w: min\((\d+)px, "
                    r"calc\(\(100cqw - (\d+)px\) / 10\)\); \}", css)
    assert fit, "--tk-w wg szerokości panelu"
    # 10 klawiszy + stała = cała klawiatura: 9 odstępów, padding i ramka z obu stron (z reguły .tkbd)
    gap = float(re.search(r"--tk-gap: ([\d.]+)px;", kbd).group(1))
    pad = float(re.search(r"(?<![-\w])padding: ([\d.]+)px;", kbd).group(1))
    border = float(re.search(r"(?<![-\w])border: ([\d.]+)px solid", kbd).group(1))
    assert float(fit.group(1)) == widths[0] and float(fit.group(2)) == 9 * gap + 2 * pad + 2 * border == 41
    # zielony klawisz z reguły .gbtn (ten sam gradient i ramka co przyciski menu)
    assert re.search(r"(?m)^\.gbtn, \.menu nav button, \.submenu button \{[^}]*linear-gradient\(#45a832, #2f8a22\)",
                     (FRONTEND / "css" / "style.css").read_text("utf-8"))
