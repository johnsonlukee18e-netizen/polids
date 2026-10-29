"""0.12.3 (issue #13): podmenu liter w CALLSIGN i AIRCRAFT: zamiast "∗" przycisk ALL na obie kolumny, pod nim 26 liter
symetrycznie w dwóch kolumnach (13 rzędów: A B, C D … Y Z). Adresy bez zmian: "" = wszystkie, "A".."Z" = litera.
0.13.1 (issue #25): pod ALL przycisk KEYBOARD tej samej wielkości (klawiatura dotykowa, test_touch_keyboard.py)."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
API = (FRONTEND / "js" / "api.js").read_text("utf-8")
CSS = (FRONTEND / "css" / "style.css").read_text("utf-8")

NODE_SCRIPT = r"""
const api = await import(process.argv[2]);
console.log(JSON.stringify({ html: api.letterButtons(), letters: api.LETTERS }));
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


def test_all_button_first_then_letters(js):
    buttons = re.findall(r"<button([^>]*)>([^<]*)</button>", js["html"])
    assert len(buttons) == 28
    attrs, label = buttons[0]
    # ALL: wszystkie rekordy, data-l="" (ten sam arg adresu co dawniej "∗"), klasa all = cała szerokość
    assert label == "ALL" and 'class="all"' in attrs and 'data-l=""' in attrs
    # 0.13.1: KEYBOARD pod ALL (klasa kbd = cała szerokość jak ALL), przełącznik bez data-l: nie filtruje i nie jest
    # krokiem do cofnięcia (klik w letterMenu szuka button[data-l])
    attrs, label = buttons[1]
    assert label == "KEYBOARD" and 'class="kbd"' in attrs and 'data-kbd=""' in attrs and "data-l" not in attrs
    assert 'title="Touch keyboard for the search field"' in attrs
    assert [lbl for _, lbl in buttons[2:]] == list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") == js["letters"]
    assert all(re.fullmatch(rf' data-l="{lbl}"', a) for a, lbl in buttons[2:])
    assert "∗" not in API and '"*"' not in API


def test_two_symmetric_columns(js):
    # siatka dwóch kolumn; ALL zajmuje cały pierwszy rząd, więc litery z letterButtons() to pełne rzędy po dwie
    # (układ na ekranie sprawdzany w demie: ALL na górze, A B … Y Z w 13 rzędach)
    assert ".submenu.letters { display: grid; grid-template-columns: 1fr 1fr;" in CSS
    assert ".submenu.letters button.all, .submenu.letters button.kbd { grid-column: 1 / -1; }" in CSS
    letters = re.findall(r'<button data-l="[A-Z]">', js["html"])
    assert len(letters) == 26 and len(letters) % 2 == 0
    # żadna inna reguła nie zmienia siatki menu liter ani miejsca przycisków (np. grid-column dla liter); reguły
    # z .letters tylko w :not(.letters) (niskie okno w 0.13.0: inne podmenu w kolumnie flex) liter nie dotyczą
    rules = [r for r in re.findall(r"^([^{}\n]*\.letters[^{}]*)\{", CSS, re.M)
             if ".letters" in r.replace(":not(.letters)", "")]
    assert [r.strip() for r in rules] == [".submenu.letters", ".submenu.letters button",
                                          ".submenu.letters button.all, .submenu.letters button.kbd"]


def test_letter_menu_contract():
    # klik: zaznaczenie, onPick z literą ("" dla ALL) i krok do cofnięcia z tym samym arg; set("") / set() = ALL
    body = API[API.index("export function letterMenu("):]
    body = body[:body.index("\n}\n")]
    assert "onPick(b.dataset.l);" in body and "remember(tab, b.dataset.l);" in body
    assert 'b.dataset.l === (l || "")' in body and 'set("");' in body
    # set() zaznacza tylko litery i ALL (KEYBOARD zostaje zaznaczony, gdy klawiatura jest otwarta); kbd dla touchKeyboard
    assert 'nav.querySelectorAll("button[data-l]").forEach' in body
    assert 'return { set, kbd: nav.querySelector("button.kbd") };' in body
    # wywołujący bez zmian: "" = wszystkie; AIRCRAFT: producent zdejmuje zaznaczenie liter (także ALL), nie KEYBOARD
    callsign = (FRONTEND / "js" / "tabs" / "callsign.js").read_text("utf-8")
    aircraft = (FRONTEND / "js" / "tabs" / "aircraft.js").read_text("utf-8")
    assert "letterMenu(root, (l) => { prefix = l; load(); })" in callsign and "letters.set(arg)" in callsign
    assert "letterMenu(root, (l) => { prefix = l; setMaker(\"\"); load(); })" in aircraft
    assert 'root.querySelectorAll(".submenu.letters button[data-l].active")' in aircraft and 'letters.set("")' in aircraft
    assert '".submenu.letters button.active"' not in aircraft
