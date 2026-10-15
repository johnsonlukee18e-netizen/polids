"""0.12.3 (issue #13): podmenu liter w CALLSIGN i AIRCRAFT: zamiast "∗" przycisk ALL na obie kolumny, pod nim 26 liter
symetrycznie w dwóch kolumnach (13 rzędów: A B, C D … Y Z). Adresy bez zmian: "" = wszystkie, "A".."Z" = litera."""
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
    assert len(buttons) == 27
    attrs, label = buttons[0]
    # ALL: wszystkie rekordy, data-l="" (ten sam arg adresu co dawniej "∗"), klasa all = cała szerokość
    assert label == "ALL" and 'class="all"' in attrs and 'data-l=""' in attrs
    assert [lbl for _, lbl in buttons[1:]] == list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") == js["letters"]
    assert all(re.fullmatch(rf' data-l="{lbl}"', a) for a, lbl in buttons[1:])
    assert "∗" not in API and '"*"' not in API


def test_two_symmetric_columns():
    # siatka dwóch kolumn; ALL zajmuje cały pierwszy rząd, więc 26 liter to 13 pełnych rzędów
    assert ".submenu.letters { display: grid; grid-template-columns: 1fr 1fr;" in CSS
    assert ".submenu.letters button.all { grid-column: 1 / -1; }" in CSS
    assert len("ABCDEFGHIJKLMNOPQRSTUVWXYZ") % 2 == 0


def test_letter_menu_contract():
    # klik: zaznaczenie, onPick z literą ("" dla ALL) i krok do cofnięcia z tym samym arg; set("") / set() = ALL
    body = API[API.index("export function letterMenu("):]
    body = body[:body.index("\n}\n")]
    assert "onPick(b.dataset.l);" in body and "remember(tab, b.dataset.l);" in body
    assert 'b.dataset.l === (l || "")' in body and 'set("");' in body and "return { set };" in body
    # wywołujący bez zmian: "" = wszystkie; AIRCRAFT: producent zdejmuje zaznaczenie liter (także ALL)
    callsign = (FRONTEND / "js" / "tabs" / "callsign.js").read_text("utf-8")
    aircraft = (FRONTEND / "js" / "tabs" / "aircraft.js").read_text("utf-8")
    assert "letterMenu(root, (l) => { prefix = l; load(); })" in callsign and "letters.set(arg)" in callsign
    assert "letterMenu(root, (l) => { prefix = l; setMaker(\"\"); load(); })" in aircraft
    assert 'root.querySelectorAll(".submenu.letters button.active")' in aircraft and 'letters.set("")' in aircraft
