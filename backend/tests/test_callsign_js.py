"""0.12.3: CALLSIGN › ALL („Wszystkie rekordy”) pobiera najwyżej LIMIT znaków wywoławczych (w bazie ~7000). Obcięta lista
nie może udawać pełnej: licznik mówi „pokazano pierwsze N” i podpowiada literę albo wyszukiwanie, jak AIRCRAFT.
Zakładka montowana w Node z zastępczym api.js (h, api, letterMenu), bez przeglądarki."""
import json
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
export const pane = { querySelector: (s) => parts[s] };
export const h = () => pane;
export const esc = (s) => String(s ?? "");
export const debounce = (f) => f;
export const letterMenu = () => ({ set() {} });
export async function api(url) {
  calls.push(url);
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
    assert js["6969"] == "1000 wyników (pokazano pierwsze 1000 – wybierz literę lub wpisz szukany kod)"
    # dokładnie 1000 też może być obcięte (API nie podaje sumy), więc też z podpowiedzią
    assert js["1000"].startswith("1000 wyników (pokazano pierwsze 1000")


def test_short_list_has_plain_count(js):
    assert js["999"] == "999 wyników" and "pokazano" not in js["3"]


def test_limit_in_request_matches_hint(js):
    # ta sama stała w zapytaniu i w podpowiedzi; serwer przyjmuje do 2000 (routers/callsigns.py)
    assert js["calls"] and all("&limit=1000" in u and u.startswith("/api/callsigns?") for u in js["calls"])
    assert "const LIMIT = 1000;" in SRC and "&limit=${LIMIT}" in SRC
