"""0.12.3: CALLSIGN › ALL („Wszystkie rekordy”) pobiera najwyżej LIMIT znaków wywoławczych (w bazie ~7000). Obcięta lista
nie może udawać pełnej: licznik mówi „first N shown” i podpowiada literę albo wyszukiwanie, jak AIRCRAFT.
Zakładka montowana w Node z zastępczym api.js (h, api, letterMenu, touchKeyboard), bez przeglądarki.
0.13.1 (issue #25): klawiatura dotykowa (przycisk "()" pod ALL, do 0.13.2 KEYBOARD) na końcu panelu, przewija się
tylko lista (.cs-list)."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

SRC = (ROOT_DIR / "frontend" / "js" / "tabs" / "callsign.js").read_text("utf-8")

# zastępczy api.js: h() daje „element” z polami .q/.cat/.count/tbody, api() odpowiada jak /api/callsigns – tyle
# wierszy, ile jest w „bazie” (TOTAL), ale nie więcej niż limit z adresu
STUB = r"""
export const calls = [];
export let TOTAL = 0;
export const setTotal = (n) => { TOTAL = n; };
const el = () => ({ textContent: "", innerHTML: "", value: "", addEventListener() {}, focus() {} });
const parts = { ".q": el(), ".cat": el(), ".count": el(), "tbody": el() };
export const appended = [];
export const pane = { querySelector: (s) => parts[s], append: (x) => appended.push(x) };
export const h = () => pane;
export const esc = (s) => String(s ?? "");
export const debounce = (f) => f;
// przycisk "()" z letterMenu i klawiatura: zapis wywołań (pole, przycisk) i sync()
export const KBD = { name: "kbd-button" };
export const letterMenu = () => ({ set() {}, kbd: KBD });
export const keyboards = [];
export const touchKeyboard = (input, button) => {
  const k = { el: { name: "tkbd" }, syncs: 0, sync() { k.syncs++; } };
  keyboards.push({ inputIsQ: input === parts[".q"], buttonIsKbd: button === KBD, k });
  return k;
};
// 0.14.0 (issue #28): wiersze z prawdziwymi polami (operator, kraj, kategoria) zamiast pustych
export let ROWS = null;
export const setRows = (r) => { ROWS = r; };
export async function api(url) {
  calls.push(url);
  if (ROWS) return ROWS;
  const limit = Number(new URL(url, "http://x").searchParams.get("limit"));
  const n = Math.min(TOTAL, limit || 200);
  return Array.from({ length: n }, (_, i) => ({ icao: `C${i}`, name: "", telephony: "", country: "", category: "" }));
}
"""

NODE_SCRIPT = r"""
const stub = await import(process.argv[2]);
const tab = (await import(process.argv[3])).default;
const root = { append() {} };
const tick = () => new Promise((r) => setTimeout(r, 0));
const out = {};
for (const total of [6969, 1000, 999, 3]) {
  stub.setTotal(total);
  tab.mount(root);
  await tick(); await tick();
  out[total] = stub.pane.querySelector(".count").textContent;
}
out.calls = stub.calls;
const tab2 = tab.mount(root);
tab2.activate(undefined);
out.keyboards = stub.keyboards.map(({ inputIsQ, buttonIsKbd, k }) => ({ inputIsQ, buttonIsKbd, syncs: k.syncs }));
out.appended = stub.appended.map((x) => x.name);
stub.setRows([{ icao: "LOT", name: "LOT POLISH AIRLINES", telephony: "POLLOT", country: "POLAND", category: "" },
  { icao: "PLF", name: "POLISH AIR FORCE", telephony: "POLISH AIRFORCE", country: "POLAND", category: "MIL" }]);
tab.mount(root);
await tick(); await tick();
out.rows = stub.pane.querySelector("tbody").innerHTML;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text(STUB, "utf-8")
    (d / "callsign.mjs").write_text(SRC.replace('"../api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "api.mjs").as_uri(), (d / "callsign.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_all_says_when_the_list_is_cut(js):
    # 6969 w bazie, pobrane 1000: licznik nie udaje pełnej listy
    assert js["6969"] == "1000 results (first 1000 shown – pick a letter or type a code)"
    # dokładnie 1000 też może być obcięte (API nie podaje sumy), więc też z podpowiedzią
    assert js["1000"].startswith("1000 results (first 1000 shown")


def test_short_list_has_plain_count(js):
    assert js["999"] == "999 results" and js["3"] == "3 results" and "shown" not in js["3"]


def test_limit_in_request_matches_hint(js):
    # ta sama stała w zapytaniu i w podpowiedzi; serwer przyjmuje do 2000 (routers/callsigns.py)
    assert js["calls"] and all("&limit=1000" in u and u.startswith("/api/callsigns?") for u in js["calls"])
    assert "const LIMIT = 1000;" in SRC and "&limit=${LIMIT}" in SRC


def test_touch_keyboard_last_in_pane(js):
    """Jedna klawiatura na montowanie, dla pola wyszukiwania i przycisku "()", dołączona na końcu panelu (po liście);
    activate() ustawia jej stan wg wspólnego wyboru (sync) przed fokusem w polu."""
    assert len(js["keyboards"]) == 5 and all(k["inputIsQ"] and k["buttonIsKbd"] for k in js["keyboards"])
    assert js["appended"] == ["tkbd"] * 5
    assert [k["syncs"] for k in js["keyboards"]] == [0, 0, 0, 0, 1]
    assert 'import { api, debounce, esc, h, letterMenu, touchKeyboard } from "../api.js";' in SRC
    assert '<div class="pane cs-pane">' in SRC
    assert '<div class="cs-list"><table class="data callsigns">' in SRC and "</tbody></table></div>\n    </div>`);" in SRC
    assert "const kbd = touchKeyboard(q, letters.kbd);\n    pane.append(kbd.el);" in SRC
    assert "kbd.sync();\n      q.focus();" in SRC


STYLE = (ROOT_DIR / "frontend" / "css" / "style.css").read_text("utf-8")


def test_operator_and_country_like_icao(js):
    """0.14.0 (issue #28): "Nazwa operatora oraz kraj pochodzenia powinny być w tej samej czcionce i w tym samym
    rozmiarze. Możesz zostawić kolorowanie callsignu". Operator (op) i kraj (ctry) w swoich klasach, bez dawnej minor
    (12 px, szary); kolumna Info z tagiem bez zmian."""
    rows = re.sub(r"\s+", " ", js["rows"])
    assert ('<tr><td class="icao">LOT</td><td class="tel">POLLOT</td> <td class="op">LOT POLISH AIRLINES</td>'
            '<td class="ctry">POLAND</td> <td></td></tr>') in rows
    assert '<td class="op">POLISH AIR FORCE</td><td class="ctry">POLAND</td> <td><span class="tag mil">MILITARY</span></td>' in rows
    assert "minor" not in SRC and "minor" not in rows


def test_callsign_table_one_font():
    """ICAO, callsign, operator i kraj: 20 px var(--mono); ICAO, operator i kraj białe, callsign żółty; komórki wiersza
    wyrównane do pierwszej linii. Tabela mieści się w panelu: długa nazwa łamie się w komórce, słowo dłuższe niż kolumna
    także w środku, ale kolumny operatora i kraju nie węższe niż min-width (sprawdzone w Chrome na danych
    ICAO_Airlines.txt: bez przewijania w bok od 692 px, jak dawniej z operatorem i krajem 12 px). Bez pogrubień, cieni
    i zaokrągleń w tych regułach; bez nowrap (nazwy muszą się łamać)."""
    css = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
    assert "table.callsigns td.icao { font: 20px var(--mono); color: #fff; width: 90px; }" in css
    assert "table.callsigns td.tel { font: 20px var(--mono); color: var(--yellow); }" in css
    assert ("table.callsigns td.op, table.callsigns td.ctry { font: 20px var(--mono); color: #fff; overflow-wrap: anywhere; }"
            in css)
    assert "table.callsigns td.op { min-width: 9em; }" in css and "table.callsigns td.ctry { min-width: 6em; }" in css
    assert "table.callsigns td { vertical-align: baseline; }" in css
    assert "td.minor" not in css
    rules = [line for line in css.splitlines() if "callsigns" in line]
    assert len(rules) == 6 and not any(re.search(r"bold|[6-9]00|shadow|radius|white-space", r) for r in rules)
    # tag kategorii (Info) jak dotąd
    assert ".tag { display: inline-block; padding: 1px 8px; font: 12px var(--mono); border: 1px solid; }" in css
