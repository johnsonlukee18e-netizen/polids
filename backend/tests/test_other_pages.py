"""OTHER (0.13.0, issue #23): REGCAUSE (kody przyczyn regulacji z data/seed/regcause.json przez /api/regcause, jedna
przewijana lista z zielonymi paskami kategorii) i VFR MINIMA (stałe tabele: minima VMC, VFR w nocy, specjalne VFR,
HEMS LPR jak w tabeli z dokumentu LPR). Napisy po angielsku, bez źródeł i numerów przepisów, bez pogrubień, ostre
krawędzie."""
import json
import os
import re
import shutil
import subprocess
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR  # noqa: E402

FRONTEND = ROOT_DIR / "frontend"
SEED = json.loads((ROOT_DIR / "data" / "seed" / "regcause.json").read_text("utf-8"))
# litery przyczyn w kolejności ekranu (jak na zdjęciu PANDORY: A, C, E, potem dalej po literze)
LETTERS = ["A", "C", "E", "G", "I", "M", "N", "O", "P", "R", "S", "T", "V", "W"]
# wiersze ze zdjęcia PANDORY (kod, opis, opis IATA)
PHOTO = [
    ("AD 89", "Reduction of expected ATC capacity due to an aircraft accident /incident.", "RESTRICTIONS AT AIRPORT OF DEPARTURE"),
    ("AA 83", "Reduction of expected ATC capacity due to an aircraft accident /incident.",
     "ATFM due to RESTRICTION AT DESTINATION AIRPORT"),
    ("CD 89", "Demand exceeds declared or expected ATC capacity.", "RESTRICTIONS AT AIRPORT OF DEPARTURE"),
    ("CE 81", "Demand exceeds or complexity reduces declared or expected ATC capacity.",
     "ATFM due to ATC ENROUTE DEMAND / CAPACITY"),
    ("CA 83", "Demand exceeds declared or expected ATC capacity.", "ATFM due to RESTRICTION AT DESTINATION AIRPORT"),
    ("ED 99", "Reduced capacity due to the degradation or non-availability of support equipment at an airport e.g. Fire "
              "Service, De-icing / snow removal equipment or other ground handling equipment.", "OTHER"),
    ("EA 99", "Reduced capacity due to the degradation or non-availability of support equipment at an airport e.g. Fire "
              "Service, De-icing / snow removal equipment or other ground handling equipment.", "OTHER"),
]
# słowa źródeł, nazw dokumentów i numerów przepisów, których nie ma w napisach tych stron
PROVENANCE = re.compile(r"Source|source:|EUROCONTROL|VATSIM|vIFF|PANSA|SERA|EASA|\bULC\b|\bAIP\b|ICAO|\bENR\b|Annex|"
                        r"Regulation|923/2012|Manual|according to|based on|data/seed|\bCODA\b|jetway", re.I)


def _rows():
    return [r for c in SEED["categories"] for r in c["rows"]]


def test_regcause_seed_shape():
    cats = SEED["categories"]
    assert set(SEED) == {"_uwaga", "categories"} and len(cats) == 14 and len(_rows()) == 35
    assert [c["rows"][0]["code"][0] for c in cats] == LETTERS
    # "Accident / incident" jak na zdjęciu PANDORY, "ATC Capacity" jak w zgłoszeniu
    assert [c["name"] for c in cats[:3]] == ["Accident / incident", "ATC Capacity", "Aerodrome Services"]
    # każdy opis kończy się kropką (jak na zdjęciu)
    assert all(r["description"].endswith(".") for r in _rows()), [r["code"] for r in _rows() if not r["description"].endswith(".")]
    for c in cats:
        assert set(c) == {"name", "rows"} and c["name"] and c["rows"], c
        # jedna litera przyczyny w kategorii; miejsce w kolejności D (odlot), E (trasa), A (przylot) jak na zdjęciu
        assert len({r["code"][0] for r in c["rows"]}) == 1, c["name"]
        where = [r["code"][1] for r in c["rows"]]
        assert where == sorted(where, key="DEA".index), c["name"]
        for r in c["rows"]:
            assert set(r) == {"code", "description", "iata"}, r
            assert re.fullmatch(r"[A-Z][DEA] \d{2}", r["code"]), r["code"]
            assert r["description"].strip() and r["iata"] and r["iata"].strip(), r["code"]
    codes = [r["code"] for r in _rows()]
    assert len(codes) == len(set(codes))
    # brakujące w źródłach numery IATA uzupełnione (GD 89, GA 83, WE 81), żaden wiersz bez opisu IATA
    assert {"GD 89", "GA 83", "WE 81"} <= set(codes) and not any(r["iata"] is None for r in _rows())
    # ten sam numer IATA = ten sam opis
    by_num = {}
    for r in _rows():
        assert by_num.setdefault(r["code"][-2:], r["iata"]) == r["iata"], r["code"]
    assert [(r["code"], r["description"], r["iata"]) for r in _rows()[:7]] == PHOTO


def test_regcause_endpoint():
    """/api/regcause oddaje tylko pola widoczne na ekranie (bez uwagi dla opiekunów danych, statusu i źródeł)."""
    r = TestClient(main.app).get("/api/regcause")
    assert r.status_code == 200
    data = r.json()
    assert data == {"categories": SEED["categories"]}
    text = json.dumps(data, ensure_ascii=False)
    assert "_uwaga" not in text and not re.search(r'"(status|note|source|verified_from|letter)"', text)
    assert not PROVENANCE.search(text), PROVENANCE.search(text).group(0)


NODE_SCRIPT = r"""
const rc = await import(process.argv[2]);
const vfr = await import(process.argv[3]);
const data = JSON.parse(process.argv[4]);
console.log(JSON.stringify({
  list: rc.regcauseHtml(data),
  empty: [rc.regcauseHtml(null), rc.regcauseHtml({ categories: [] }), rc.regcauseHtml({ categories: [{ name: "X", rows: [] }] })],
  evil: rc.regcauseHtml({ categories: [{ name: "<i>A</i>", rows: [{ code: "AD 89", description: "a & <b>", iata: "\"x\"" }] }] }),
  vfr: vfr.vfrHtml(),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("otherpages")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    src = (FRONTEND / "js" / "regcause.js").read_text("utf-8")
    assert '"./api.js"' in src
    (d / "regcause.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    vsrc = (FRONTEND / "js" / "vfrminima.js").read_text("utf-8")
    assert "import " not in vsrc   # strona bez danych z serwera
    (d / "vfrminima.mjs").write_text(vsrc, "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    data = json.dumps({"categories": SEED["categories"]})
    r = subprocess.run([node, str(d / "run.mjs"), (d / "regcause.mjs").as_uri(), (d / "vfrminima.mjs").as_uri(), data],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_regcause_list(js):
    html = js["list"]
    # pasek kategorii na kategorię, wiersz na kod: kod | opis | IATA, w kolejności z pliku; bez stopki i nagłówka kolumn
    assert html.count('<h3 class="rc-bar">') == 14 and html.count('<div class="rc-row">') == 35
    assert re.findall(r'<h3 class="rc-bar">([^<]+)</h3>', html) == [c["name"] for c in SEED["categories"]]
    assert re.findall(r'<span class="rc-code">([^<]+)</span>', html) == [r["code"] for r in _rows()]
    assert ('<div class="rc-row"><span class="rc-code">CD 89</span><span class="rc-text">Demand exceeds declared or expected '
            'ATC capacity.</span><span class="rc-iata">RESTRICTIONS AT AIRPORT OF DEPARTURE</span></div>') in html
    assert "<th" not in html and "<footer" not in html and not PROVENANCE.search(_text(html))
    assert all(e == '<p class="hint rc-empty">No codes.</p>' for e in js["empty"])
    evil = js["evil"]
    assert "&lt;i&gt;A&lt;/i&gt;" in evil and "a &amp; &lt;b&gt;" in evil and "&quot;x&quot;" in evil and "<b>" not in evil
    src = (FRONTEND / "js" / "regcause.js").read_text("utf-8")
    assert 'api("/api/regcause")' in src and "window.removeEventListener(ONLINE_EVENT, online)" in src


def test_vfr_minima_sections(js):
    html = js["vfr"]
    assert re.findall(r'<h3 class="vfr-bar">([^<]+)</h3>', html) == ["VMC minima", "Night VFR", "Special VFR", "HEMS (LPR)"]
    text = _text(html)
    assert not PROVENANCE.search(text), PROVENANCE.search(text).group(0)
    assert not re.search(r"\b\d{4}/\d{2,4}\b|SERA\.|ENR \d", text)   # bez numerów przepisów i punktów AIP
    # VMC: klasy C, D, G; górne pasmo od FL100; klasa G nisko: bez chmur z widocznością ziemi i zmniejszona widzialność
    assert "At and above FL100 C 8 km 1500 m horizontally 300 m (1000 ft) vertically" in text
    assert "Below FL100 and above 900 m (3000 ft) AMSL or 300 m (1000 ft) above terrain, whichever is the higher C D G 5 km" in text
    assert "C D 5 km" in text and "G 5 km * Clear of cloud and with the surface in sight" in text
    # klasy A, B, E i F nie są używane w FIR Warszawa
    assert re.findall(r'<td class="vfr-cls">([^<]+)</td>', html) == ["C", "C D G", "C D", "G"]
    assert "Not less than 1500 m" in text and "At 140 kt IAS or less" in text
    # śmigłowce: "not less than 800 m" (angielski tekst ma błąd tłumaczenia "in less than 800 m")
    assert "Helicopters: not less than 800 m" in text and "in less than 800 m" not in text
    # noc: podstawa chmur, bez zmniejszonej widzialności, ciągła widoczność ziemi nisko, poziomy minimalne
    assert "Ceiling Not less than 450 m (1500 ft)" in text and "Reduced flight visibility in class G * Does not apply" in text
    assert "Continuous sight of the surface" in text and "600 m (2000 ft) above the highest obstacle within 8 km" in text
    assert "300 m (1000 ft) above the highest obstacle within 8 km" in text and "30 min after sunset" in text
    # specjalne VFR: tylko w dzień, warunki pilota i kiedy ATC nie daje zgody
    assert "day only" in text and "Flight visibility Not less than 1500 m Helicopters: not less than 800 m" in text
    assert "Speed 140 kt IAS or less" in text
    assert "Ground visibility Less than 1500 m Helicopters: less than 800 m Ceiling Less than 180 m (600 ft)" in text
    assert "Ceiling Less than 450 m (1500 ft) Ground visibility Less than 5 km" in text
    # poniżej tych wartości VFR na lotnisku w strefie kontrolowanej tylko ze zgodą na specjalne VFR (nie "zgoda ATC",
    # bo VFR w strefie kontrolowanej zawsze jej potrzebuje)
    assert ("Without a special VFR clearance, VFR flights may not take off or land at an aerodrome within a control zone, "
            "or enter its aerodrome traffic zone or circuit, when reported: Ceiling Less than 450 m") in text
    assert "needs an ATC clearance" not in text
    # minimalne wysokości VFR (w dzień i w nocy) w sekcji VMC
    vmc = _text(html[html.index('<section class="vfr-sec vfr-vmc">'):html.index('<section class="vfr-sec vfr-night">')])
    assert ("Minimum heights, day and night, except when necessary for take-off or landing: Over congested areas of cities, "
            "towns or settlements or over an open-air assembly of persons 300 m (1000 ft) above the highest obstacle within "
            "600 m of the aircraft Elsewhere 150 m (500 ft) above the ground or water, or 150 m (500 ft) above the highest "
            "obstacle within 150 m (500 ft) of the aircraft") in vmc
    # przypis "*" nie spada sam do nowej linii (twarda spacja przed nim)
    assert "class G\u00a0*" in html and "5 km\u00a0*" in html and "G *<" not in html


def test_vfr_minima_hems_table(js):
    """HEMS (LPR) dokładnie jak w tabeli z dokumentu LPR: DAY i NIGHT nad parami kolumn, trzy wiersze dnia, noc
    w komórkach scalonych na wszystkie trzy wiersze."""
    html = js["vfr"]
    hems = html[html.index('<section class="vfr-sec vfr-hems">'):]
    assert "Meteorological minimums for HEMS flights" in hems
    assert '<th colspan="2" class="vfr-period">DAY</th><th colspan="2" class="vfr-period">NIGHT</th>' in hems
    assert "<tr><th>Cloud base</th><th>Visibility</th><th>Cloud base</th><th>Visibility</th></tr>" in hems
    body = hems[hems.index("<tbody>"):hems.index("</tbody>")]
    rows = re.findall(r"<tr>(.*?)</tr>", body)
    assert [re.findall(r"<td[^>]*>([^<]*)</td>", r) for r in rows] == [
        ["300 - 400 ft", "3 km", "> 1500 ft", "> 5 km"], ["410 - 500 ft", "2 km"], ["> 500 ft", "1500 m"]]
    assert body.count('rowspan="3"') == 2


def test_other_pages_style():
    """Arkusze OTHER i SQUAWK: bez pogrubień (0.13.0), ostre krawędzie, bez poświaty i cieni pod tekstem; strony OTHER
    bez <b>/<strong>; podmenu OTHER bez własnych reguł rozmiaru (ogólne reguły podmenu w style.css)."""
    for name in ("other.css", "squawk.css"):
        css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / name).read_text("utf-8"), flags=re.S)
        assert not re.search(r"font-weight:\s*(bold|[6-9]00)|font:\s*(bold|[6-9]00)\b", css), name
        assert all(r.strip() == "0" for r in re.findall(r"border(?:-[a-z]+)*-radius:\s*([^;}]+)", css)), name
        assert "text-shadow" not in css and "glow" not in css, name
        bad = [v.strip() for v in re.findall(r"box-shadow:\s*([^;}]+)", css)
               if not (v.strip() == "none" or v.strip().startswith("inset") or re.match(r"0 0 0 \d+px", v.strip()))]
        assert not bad, (name, bad)
        assert ".submenu" not in css and 'data-tab="other"' not in css, name
    for name in ("tabs/other.js", "squawk.js", "regcause.js", "vfrminima.js", "flightplan.js", "fmp.js"):
        src = (FRONTEND / "js" / name).read_text("utf-8")
        code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("//"))
        assert not re.search(r"<(b|strong)[\s>]", code), name
    assert 'href="/static/css/other.css"' in (FRONTEND / "index.html").read_text("utf-8")


RC_STUB = r"""
const makeEl = () => ({ innerHTML: "" });
export const ONLINE_EVENT = "polids:online";
export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
export const h = (html) => Object.assign(makeEl(), { innerHTML: html });
export const api = (url) => new Promise((res, rej) => globalThis.__pending.push({ url, res, rej }));
"""
RC_MOUNT = r"""
globalThis.__pending = [];
globalThis.__l = [];
globalThis.window = { addEventListener(t, f) { globalThis.__l.push([t, f]); },
  removeEventListener(t, f) { globalThis.__l = globalThis.__l.filter(([a, b]) => !(a === t && b === f)); } };
const rc = await import(process.argv[2]);
const tick = () => new Promise((r) => setImmediate(r));
const count = () => globalThis.__l.filter(([t]) => t === "polids:online").length;
const online = () => globalThis.__l.forEach(([t, f]) => t === "polids:online" && f());
const data = { categories: [{ name: "ATC Capacity", rows: [{ code: "CD 89", description: "Demand.", iata: "X" }] }] };
const pane = { append(x) { this.list = x; } };
// A: błąd, potem serwer wraca (ONLINE_EVENT) i lista się rysuje; po narysowaniu ONLINE_EVENT nic nie pyta
const a = rc.mountRegcause(pane);
const listA = pane.list;
const o = { loading: listA.innerHTML, afterMount: count(), requests: globalThis.__pending.map((p) => p.url) };
globalThis.__pending.shift().rej(new Error("no connection to the PolIDS server"));
await tick();
o.error = listA.innerHTML;
online();
globalThis.__pending.shift().res(data);
await tick();
o.drawn = listA.innerHTML.includes('<h3 class="rc-bar">ATC Capacity</h3>');
online();
o.afterDone = globalThis.__pending.length;
// B: zniszczona przed odpowiedzią: nasłuch zdjęty, spóźniona odpowiedź nic nie rysuje
const b = rc.mountRegcause(pane);
const listB = pane.list;
o.twoMounted = count();
b.destroy();
o.afterDestroy = count();
globalThis.__pending.shift().res(data);
await tick();
o.lateB = listB.innerHTML;
a.destroy();
o.allGone = count();
console.log(JSON.stringify(o));
"""


def test_regcause_mount_and_destroy(tmp_path):
    """REGCAUSE rysuje się od nowa przy każdym kliknięciu w podmenu: destroy() zdejmuje nasłuch ONLINE_EVENT, spóźniona
    odpowiedź nic nie rysuje; po błędzie lista wczytuje się sama, gdy serwer wraca, a narysowana nie pyta ponownie."""
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text(RC_STUB, "utf-8")
    src = (FRONTEND / "js" / "regcause.js").read_text("utf-8")
    (tmp_path / "regcause.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(RC_MOUNT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "regcause.mjs").as_uri()], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["loading"] == '<div class="rc-list"><p class="hint rc-empty">Loading…</p></div>'
    assert o["afterMount"] == 1 and o["requests"] == ["/api/regcause"]
    assert o["error"] == '<p class="error rc-empty">no connection to the PolIDS server</p>'
    assert o["drawn"] is True and o["afterDone"] == 0
    assert o["twoMounted"] == 2 and o["afterDestroy"] == 1 and o["allGone"] == 0
    assert o["lateB"].startswith('<div class="rc-list">') and "rc-bar" not in o["lateB"]


def test_other_area_js_ascii_code():
    """W kodzie (poza komentarzami w osobnych linijkach) tylko ASCII: znaki typograficzne jako \\u2013, \\u2026 itd."""
    for name in ("tabs/other.js", "squawk.js", "regcause.js", "vfrminima.js", "flightplan.js", "fmp.js"):
        src = (FRONTEND / "js" / name).read_text("utf-8")
        bad = [line.strip() for line in src.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
        assert not bad, (name, bad)
