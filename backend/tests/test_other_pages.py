"""OTHER (0.13.0, issue #23): REGCAUSE (kody przyczyn regulacji z data/seed/regcause.json przez /api/regcause, jedna
przewijana lista z zielonymi paskami kategorii) i VFR MINIMA (stałe tabele: minima VMC, VFR w nocy, specjalne VFR,
HEMS LPR jak w tabeli z dokumentu LPR). 0.13.2 (issue #27): HOLDING (ściąga FLIRT, frazeologia, rysunek holdingu,
sektory i wejścia, prędkości) i BOMB PHONE (checklista rozmowy z groźbą bombową, 112, stan tylko w sessionStorage).
Napisy po angielsku, bez źródeł i numerów przepisów, bez pogrubień, ostre krawędzie."""
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
# wiersze ze zdjęcia PANDORY (kod, opis, opis IATA); PANDORA ma tekst z wydania 2017, stąd "accident /incident."
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
# tabela z ATFCM Users Manual 27.0 (aneks D, s. 106-108): litera przyczyny, nazwa kategorii, kody miejsca i numery IATA
MANUAL = [
    ("A", "Accident / incident", ["AD 89", "AA 83"]),
    ("C", "ATC capacity", ["CD 89", "CE 81", "CA 83"]),
    ("E", "Aerodrome Services", ["ED 99", "EA 99"]),
    ("G", "Aerodrome capacity", ["GD 89", "GA 83"]),
    ("I", "ATC industrial action", ["ID 89", "IE 82", "IA 83"]),
    ("M", "Airspace management", ["MD 89", "ME 82", "MA 83"]),
    ("N", "Industrial action NON-ATC", ["ND 98", "NA 98"]),
    ("O", "Other", ["OD 89", "OE 81", "OA 83"]),
    ("P", "Special event", ["PD 89", "PE 82", "PA 83"]),
    ("R", "ATC routeings", ["RE 81"]),
    ("S", "ATC staffing", ["SD 89", "SE 82", "SA 83"]),
    ("T", "ATC equipment", ["TD 89", "TE 82", "TA 83"]),
    ("V", "Environmental issue", ["VD 89", "VE 81", "VA 83"]),
    ("W", "Weather", ["WD 89", "WE 81", "WA 84"]),
]
# opisy numerów IATA z tej tabeli
IATA = {"81": "ATFM due to ATC ENROUTE DEMAND / CAPACITY", "82": "ATFM due to ATC STAFF / EQUIPMENT ENROUTE",
        "83": "ATFM due to RESTRICTION AT DESTINATION AIRPORT", "84": "ATFM due to WEATHER AT DESTINATION",
        "89": "RESTRICTIONS AT AIRPORT OF DEPARTURE", "98": "INDUSTRIAL ACTION OUTSIDE OWN AIRLINE", "99": "OTHER"}
# słowa źródeł, nazw dokumentów i numerów przepisów, których nie ma w napisach tych stron
PROVENANCE = re.compile(r"Source|source:|EUROCONTROL|VATSIM|vIFF|PANSA|SERA|EASA|\bULC\b|\bAIP\b|ICAO|\bENR\b|Annex|"
                        r"Regulation|923/2012|Manual|according to|based on|data/seed|\bCODA\b|jetway", re.I)


def _rows():
    return [r for c in SEED["categories"] for r in c["rows"]]


def test_regcause_seed_shape():
    cats = SEED["categories"]
    assert set(SEED) == {"_uwaga", "categories"} and len(cats) == 14 and len(_rows()) == 36
    assert [c["rows"][0]["code"][0] for c in cats] == LETTERS
    # cała tabela z podręcznika: nazwy kategorii jak w nim (i na zdjęciu PANDORY), wszystkie kody, w tym PE 82 i VE 81
    assert [(c["rows"][0]["code"][0], c["name"], [r["code"] for r in c["rows"]]) for c in cats] == MANUAL
    assert all(r["iata"] == IATA[r["code"][-2:]] for r in _rows())
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
    # w kategorii jeden opis, poza ATC capacity: E trasa, D i A lotnisko (w podręczniku "En Route:" i "Airport:")
    for c in cats:
        assert len({r["description"] for r in c["rows"]}) == (2 if c["name"] == "ATC capacity" else 1), c["name"]
    # zgodnie ze zdjęciem PANDORY (ukośnik ze spacjami jak w wydaniu 27.0)
    slash = lambda t: re.sub(r"\s*/\s*", " / ", t)  # noqa: E731
    assert [(r["code"], r["description"], r["iata"]) for r in _rows()[:7]] == [(c, slash(d), i) for c, d, i in PHOTO]


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
    assert html.count('<h3 class="rc-bar">') == 14 and html.count('<div class="rc-row">') == 36
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
    for name in ("tabs/other.js", "squawk.js", "regcause.js", "vfrminima.js", "flightplan.js", "fmp.js", "holding.js",
                 "bombphone.js"):
        src = (FRONTEND / "js" / name).read_text("utf-8")
        code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("//"))
        assert not re.search(r"<(b|strong)[\s>]", code), name
        # 0.13.2: także bez pogrubień w SVG (font-weight w atrybutach albo stylach w kodzie)
        assert not re.search(r"font-weight[=:]\s*\"?(bold|[6-9]00)", code), name
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
    for name in ("tabs/other.js", "squawk.js", "regcause.js", "vfrminima.js", "flightplan.js", "fmp.js", "holding.js",
                 "bombphone.js"):
        src = (FRONTEND / "js" / name).read_text("utf-8")
        bad = [line.strip() for line in src.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
        assert not bad, (name, bad)



# --- 0.13.2 (issue #27): HOLDING i BOMB PHONE

HB_SCRIPT = r"""
const hold = await import(process.argv[2]);
const bomb = await import(process.argv[3]);
const store = (v) => ({ getItem: () => v, setItem() {}, removeItem() {} });
const evil = { words: "<script>x</script> & \"q\"", "q-when": "at <b>noon</b>", "v-calm": true, "b-music": true,
  "l-well-spoken": true, "s-male": true, "c-number": "+48 \"600\"" };
console.log(JSON.stringify({
  html: hold.holdingHtml(), pattern: hold.patternSvg(), sectors: hold.sectorsSvg(), entries: hold.entriesSvg(),
  paths: hold.ENTRY_PATHS, bounds: hold.BOUNDS, sectorSizes: hold.SECTORS, flirt: hold.FLIRT, expect: hold.EXPECT,
  speeds: hold.SPEEDS,
  bomb: bomb.bombHtml(), bombEvil: bomb.bombHtml(evil), keys: [...bomb.KEYS],
  voice: bomb.VOICE, background: bomb.BACKGROUND, language: bomb.LANGUAGE, questions: bomb.QUESTIONS,
  load: {
    ok: bomb.loadForm(store(JSON.stringify({ "q-when": "noon", "v-calm": true, junk: "x", "v-loud": "yes", words: 5,
      "q-why": "" }))),
    bad: [bomb.loadForm(store("not json")), bomb.loadForm(store("[1,2]")), bomb.loadForm(store("null")),
      bomb.loadForm(null), bomb.loadForm({ getItem() { throw new Error("blocked"); } })],
  },
  dur: [bomb.durationOf("12:00:00", "12:02:35"), bomb.durationOf("23:59", "00:01"), bomb.durationOf("12:00", "12:00"),
    bomb.durationOf("", "12:00"), bomb.durationOf("25:00", "12:00"), bomb.durationOf("12:00:00", "x"),
    bomb.durationOf("12:00:02", "12:00:00"), bomb.durationOf("12:00", "00:00"), bomb.durationOf("20:00", "08:00")],
  time: [bomb.utcTime(new Date(Date.UTC(2026, 10, 9, 7, 5, 3))), bomb.utcDate(new Date(Date.UTC(2026, 10, 9, 7, 5, 3)))],
  slug: [bomb.slug("v", "Clearing throat"), bomb.slug("l", "Foul / profane"), bomb.slug("b", "PA system")],
}));
"""

HB_API = r"""
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const h = (html) => globalThis.__makeEl(html);
"""


@pytest.fixture(scope="module")
def hb(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("holdbomb")
    hsrc = (FRONTEND / "js" / "holding.js").read_text("utf-8")
    assert "import " not in hsrc   # strona bez danych z serwera
    (d / "holding.mjs").write_text(hsrc, "utf-8")
    (d / "api.mjs").write_text(HB_API, "utf-8")
    bsrc = (FRONTEND / "js" / "bombphone.js").read_text("utf-8")
    assert bsrc.startswith('import { esc, h } from "./api.js";\n')
    (d / "bombphone.mjs").write_text(bsrc.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (d / "run.mjs").write_text(HB_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "holding.mjs").as_uri(), (d / "bombphone.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_holding_sections_and_flirt(hb):
    html = hb["html"]
    assert re.findall(r'<h3 class="hold-bar">([^<]+)</h3>', html) == [
        "Holding clearance (FLIRT)", "Phraseology", "Maximum holding speeds (IAS)", "Holding pattern", "Entry sectors",
        "Entries"]
    text = _text(html)
    assert not PROVENANCE.search(text), PROVENANCE.search(text).group(0)
    assert not re.search(r"Doc \d{4}|PANS|SKYbrary|IVAO|FAA", text)
    # FLIRT: Fix, Level, Inbound track, Right/left turns, Time; na końcu EXPECT ... AT (time)
    assert [(f[0], f[1]) for f in hb["flirt"]] == [("F", "Fix"), ("L", "Level"), ("I", "Inbound track"),
                                                 ("R", "Right or left turns"), ("T", "Time outbound")]
    assert "".join(f[0] for f in hb["flirt"]) == "FLIRT"
    assert hb["expect"][2] == "EXPECT FURTHER CLEARANCE (or APPROACH CLEARANCE) AT (time)"
    letters = re.findall(r'<td class="hold-letter">([^<]+)</td>', html)
    assert letters == ["F", "L", "I", "R", "T", "+"]
    assert "HOLD INBOUND TRACK" in text and "RIGHT (or LEFT) HAND PATTERN" in text and "OUTBOUND TIME" in text
    # przykład w kolejności FLIRT, z czasem EFC na końcu
    ex = re.search(r'<p class="hold-example">([^<]+)</p>', html).group(1)
    order = [ex.index(w) for w in ("CLEARED TO", "MAINTAIN", "INBOUND TRACK", "RIGHT HAND PATTERN", "OUTBOUND TIME",
                                   "EXPECT FURTHER CLEARANCE AT")]
    assert order == sorted(order) and ex.endswith("EXPECT FURTHER CLEARANCE AT 1435")
    # frazeologia: published, DME, prośba pilota, opóźnienia
    for phrase in ("HOLD AS PUBLISHED", "REQUEST HOLDING INSTRUCTIONS", "NO DELAY EXPECTED", "EXPECTED APPROACH TIME",
                   "REVISED EXPECTED APPROACH TIME", "DELAY NOT DETERMINED", "HOLD BETWEEN"):
        assert phrase in text, phrase
    assert "Delay of 10 minutes or more: give an expected approach time." in text
    # miejsca do wstawienia wyróżnione kolorem
    assert '<span class="hold-ph">(fix)</span>' in html and '<span class="hold-ph">(time)</span>' in html


def test_holding_speeds_and_timing(hb):
    """Maksymalne prędkości holdingu (IAS) i czas odcinka: 1 min do FL140 włącznie, 1,5 min wyżej."""
    assert hb["speeds"] == [
        ["At or below FL140", "230 kt", "280 kt"],
        ["Above FL140 to FL200", "240 kt", "280 kt or M0.80, whichever is less"],
        ["Above FL200 to FL340", "265 kt", "280 kt or M0.80, whichever is less"],
        ["Above FL340", "M0.83", "M0.83"],
    ]
    text = _text(hb["html"])
    assert "category A and B aircraft only: 170 kt at or below FL140" in text
    assert "Turbulence speeds only after ATC clearance" in text
    assert "1 min at or below FL140, 1.5 min above FL140" in text
    assert "over or abeam the fix, whichever is later" in text
    assert "25° bank or 3° per second, whichever needs the lesser bank" in text


def test_holding_drawings(hb):
    """Trzy rysunki SVG: holding (fix, odcinki, zakręty, trawers, strony), sektory wejścia (linia 70°, ±5°) i wejścia."""
    html = hb["html"]
    assert html.count("<svg ") == 3 and html.count('role="img"') == 3
    pat = _text(hb["pattern"])
    for label in ("HOLDING FIX", "INBOUND LEG", "OUTBOUND LEG", "ABEAM", "OUTBOUND TURN", "INBOUND TURN", "HOLDING SIDE",
                  "NON-HOLDING SIDE", "1 min at or below FL140, 1.5 min above"):
        assert label in pat, label
    # zakręty w prawo: oba łuki pętli zgodnie z ruchem wskazówek zegara (sweep 1)
    loop = re.search(r'<path class="hold-track" d="([^"]+)"', hb["pattern"]).group(1)
    assert re.findall(r"A\d+,\d+ 0 0 (\d)", loop) == ["1", "1"]
    # sektory: granice 20°, 90° i 200° od fixu (linia 70° i przedłużenie odcinka dolotowego), rozmiary 110/70/180
    assert hb["bounds"] == [20, 90, 200]
    sizes = {name: deg for _, name, deg in hb["sectorSizes"]}
    assert sizes == {"PARALLEL": 110, "OFFSET": 70, "DIRECT": 180} and sum(sizes.values()) == 360
    b = hb["bounds"]
    assert (b[2] - b[1], b[1] - b[0], 360 - (b[2] - b[0])) == (110, 70, 180)
    # linia 70° tworzy z odcinkiem dolotowym (270° od fixu) kąt 70°
    assert 270 - b[2] == 70 and (b[0] + 180) == b[2]
    sec = hb["sectors"]
    assert sec.count('class="hold-flex"') == 3 and sec.count('class="hold-bound"') == 3
    st = _text(sec)
    for label in ("1 PARALLEL", "110°", "2 OFFSET", "70°", "3 DIRECT", "180°", "70° LINE", "FIX"):
        assert label in st, label
    assert "±5° flexibility" in _text(html)
    # wejścia: trzy panele z nazwami, ścieżki na zielono
    ent = _text(hb["entries"])
    assert ent == "1 PARALLEL 30\u00b0 2 OFFSET 3 DIRECT" and hb["entries"].count('class="hold-entry"') == 3


def _pts(d):
    return [tuple(map(float, p)) for p in re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", d)]


def test_holding_entry_paths_geometry(hb):
    """Ścieżki wejść zgodne z opisem: fix (128, 64), odcinek dolotowy na wschód, strona holdingu pod nim (y > 64).
    PARALLEL: po fixie na zachód po stronie przeciwnej (y < 64), zakręt w lewo (sweep 0) ponad 180°, powrót do fixu.
    OFFSET: tor 30° od odwrotności odcinka dolotowego na stronę holdingu, zakręt w prawo (sweep 1) do odcinka.
    DIRECT: nad fixem w prawo i dalej po pętli (odcinek odlotowy y = 112)."""
    import math
    par, off, dirc = (p["d"] for p in hb["paths"])
    assert [p["name"] for p in hb["paths"]] == ["PARALLEL", "OFFSET", "DIRECT"]
    # dolot z sektora 1 (z południowego wschodu: kurs od fixu 90-200)
    x0, y0 = _pts(par)[0]
    brg = math.degrees(math.atan2(x0 - 128, -(y0 - 64))) % 360
    assert 90 < brg < 200
    assert "L52,57" in par and re.search(r"A20,20 0 1 0 ", par) and par.endswith("L128,64")
    # dolot z sektora 2 (kurs od fixu 20-90), odcinek odlotowy pod kątem 30° do odcinka dolotowego, na stronę holdingu
    x0, y0 = _pts(off)[0]
    brg = math.degrees(math.atan2(x0 - 128, -(y0 - 64))) % 360
    assert 20 < brg < 90
    (fx, fy), (ex, ey) = _pts(off)[1:3]
    assert (fx, fy) == (128, 64) and ey > fy
    assert abs(math.degrees(math.atan2(ey - fy, fx - ex)) - 30) < 0.5
    assert re.search(r"A16\.6,16\.6 0 1 1 ", off) and off.endswith("L128,64")
    # dolot z sektora 3 (kurs od fixu 200-20 przez zachód)
    x0, y0 = _pts(dirc)[0]
    brg = math.degrees(math.atan2(x0 - 128, -(y0 - 64))) % 360
    assert brg > 200 or brg < 20
    assert "L60,112" in dirc


def test_bomb_phone_content(hb):
    html = hb["bomb"]
    text = _text(html)
    assert not PROVENANCE.search(text), PROVENANCE.search(text).group(0)
    assert not re.search(r"CISA|ProtectUK|NaCTSO|DHS|police\.uk|cisa\.gov", text)
    # polski numer alarmowy duży u góry i jeszcze raz po rozmowie; Policja 997 mniejsza
    assert re.findall(r'<span class="bp-sos-num">(\d+)</span>', html) == ["112", "997"]
    assert '<span class="bp-call-num">112</span>' in html and "Report immediately 112 Police 997" in text
    assert html.index(">112<") < html.index(">997<")
    assert re.findall(r'<h3 class="bp-bar">([^<]+)</h3>', html) == [
        "During the call", "Questions to ask", "Exact words of the threat", "Call details", "Caller", "Remarks",
        "Caller's voice", "Background sounds", "Threat language", "After the call"]
    for s in ("Stay calm", "Keep the caller talking", "Do not hang up, even if the caller does.",
              "Signal a colleague", "Note the number shown on the display.", "Write down the exact words of the threat.",
              "Inform the supervisor and follow local procedures.", "Do not discuss the threat"):
        assert s in text, s
    qs = [q for _, q, _ in hb["questions"]]
    assert len(qs) == 12 and qs[:2] == ["When will it explode?", "Where is it right now?"]
    for q in ("What does it look like?", "What kind of bomb is it?", "What will cause it to explode?",
              "Did you place the bomb?", "Why?", "Where are you calling from?", "What is your name?",
              "What is your address?"):
        assert q in qs, q
    # pola wyboru z listy w zgłoszeniu
    voice = {v.lower() for v in hb["voice"]}
    for v in ("calm", "angry", "excited", "slow", "rapid", "soft", "loud", "laughter", "crying", "normal", "distinct",
              "slurred", "nasal", "stutter", "lisp", "raspy", "deep", "ragged", "clearing throat", "deep breathing",
              "cracking voice", "disguised", "accent", "familiar", "whispered"):
        assert v in voice, v
    assert hb["voice"] == sorted(hb["voice"]) and hb["background"] == sorted(hb["background"])
    assert {"Street noises", "Office machinery", "PA system", "Static", "Music", "Voices"} <= set(hb["background"])
    assert {"Well spoken", "Incoherent", "Irrational", "Taped message", "Message read"} <= set(hb["language"])
    boxes = re.findall(r'<input type="checkbox" data-k="([^"]+)">', html)
    assert len(boxes) == 2 + len(hb["voice"]) + len(hb["background"]) + len(hb["language"]) and len(set(boxes)) == len(boxes)
    # dane rozmowy: data i czasy UTC (NOW przy obu czasach), czas trwania, numer na wyświetlaczu, imię i stanowisko
    for label in ("Date (UTC)", "Time of call (UTC)", "Caller hung up (UTC)", "Duration", "Number displayed", "Your name",
                  "Your position"):
        assert f'<span class="bp-lbl">{label}</span>' in html, label
    assert re.findall(r'data-act="now" data-for="([^"]+)"', html) == ["c-start", "c-end"]
    assert html.count('data-act="clear"') == 1 and ">CLEAR</button>" in html
    assert '<textarea class="field bp-area" data-k="words"' in html
    # wszystkie pola mają klucz ze zbioru KEYS (zapis formularza tylko znanych pól)
    ks = re.findall(r'data-k="([^"]+)"', html)
    assert set(ks) == set(hb["keys"]) and len(ks) == len(hb["keys"])


def test_bomb_phone_state_rendering(hb):
    """Stan formularza w HTML: wartości escapowane, zaznaczone pola wyboru; zły zapis = pusty formularz."""
    html = hb["bombEvil"]
    assert "&lt;script&gt;x&lt;/script&gt; &amp; &quot;q&quot;</textarea>" in html and "<script>" not in html
    assert 'data-k="q-when" value="at &lt;b&gt;noon&lt;/b&gt;"' in html
    assert 'data-k="c-number" value="+48 &quot;600&quot;"' in html
    checked = re.findall(r'data-k="([^"]+)" checked>', html)
    assert checked == ["s-male", "v-calm", "b-music", "l-well-spoken"]
    # zapis: tylko znane klucze, pola wyboru tylko true, tekst tylko niepusty napis
    assert hb["load"]["ok"] == {"q-when": "noon", "v-calm": True}
    assert hb["load"]["bad"] == [{}, {}, {}, {}, {}]
    # koniec przed początkiem (przerwa ponad 12 h) bez czasu trwania, nie prawie 24 h; przez północ do 12 h
    assert hb["dur"] == ["2 min 35 s", "2 min 00 s", "0 min 00 s", "", "", "", "", "720 min 00 s", "720 min 00 s"]
    assert hb["time"] == ["07:05:03", "2026-11-09"]
    assert hb["slug"] == ["v-clearing-throat", "l-foul-profane", "b-pa-system"]


def test_bomb_phone_stays_local():
    """Formularz nigdzie nie jest wysyłany: bez api(), fetch, XHR, sendBeacon i bez localStorage (tylko sessionStorage
    tej karty albo pamięć strony)."""
    src = (FRONTEND / "js" / "bombphone.js").read_text("utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("//"))
    for bad in ("api(", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "lsSet(", "navigator."):
        assert bad not in code, bad
    assert "window.sessionStorage" in code and 'export const STORE_KEY = "bombphone.form";' in code


BOMB_MOUNT = r"""
// atrapa DOM: element z innerHTML, pola z data-k tworzone na żądanie (value / checked), nasłuchy zdarzeń
const fields = new Map();
globalThis.__makeEl = (html) => {
  const el = { innerHTML: "", on: new Map(),
    addEventListener(t, f) { this.on.set(t, f); }, removeEventListener(t, f) { if (this.on.get(t) === f) this.on.delete(t); },
    querySelector(sel) { const k = /data-k="([^"]+)"/.exec(sel)?.[1]; if (!fields.has(k)) fields.set(k, { value: "", dataset: { k } }); return fields.get(k); } };
  globalThis.__root = el;
  return el;
};
const bomb = await import(process.argv[2]);
const saved = new Map();
const store = { getItem: (k) => saved.get(k) ?? null, setItem: (k, v) => saved.set(k, v), removeItem: (k) => saved.delete(k) };
store.setItem(bomb.STORE_KEY, JSON.stringify({ "q-why": "revenge" }));
let asked = 0, answer = false;
const pane = { items: [], append(x) { this.items.push(x); } };
const view = bomb.mountBombPhone(pane, { store, ask: () => { asked++; return answer; },
  now: () => new Date(Date.UTC(2026, 10, 9, 13, 2, 3)) });
const root = globalThis.__root;
const o = { appended: pane.items.length === 1 && pane.items[0] === root, start: root.innerHTML.includes('value="revenge"'),
  events: [...root.on.keys()].sort() };
const fire = (t, target) => root.on.get(t)({ target });
fire("input", { dataset: { k: "words" }, type: "textarea", value: "bomb at noon" });
fire("change", { dataset: { k: "v-calm" }, type: "checkbox", checked: true });
fire("change", { dataset: { k: "v-loud" }, type: "checkbox", checked: true });
fire("change", { dataset: { k: "v-loud" }, type: "checkbox", checked: false });
fire("input", { dataset: { k: "nope" }, type: "text", value: "x" });
fire("input", { dataset: {}, type: "text", value: "x" });
o.afterFields = JSON.parse(saved.get(bomb.STORE_KEY));
const btn = (ds) => ({ closest: () => ({ dataset: ds }) });
fire("click", btn({ act: "now", for: "c-start" }));
o.afterStart = JSON.parse(saved.get(bomb.STORE_KEY));
fire("click", btn({ act: "now", for: "c-end" }));
o.afterEnd = JSON.parse(saved.get(bomb.STORE_KEY));
o.fieldValues = ["c-start", "c-end", "c-date", "c-dur"].map((k) => fields.get(k)?.value);
fire("click", { closest: () => null });
// CLEAR: odmowa zostawia formularz, zgoda czyści zapis i rysuje pusty formularz
fire("click", btn({ act: "clear" }));
o.refused = [asked, saved.has(bomb.STORE_KEY)];
answer = true;
fire("click", btn({ act: "clear" }));
o.cleared = [asked, saved.has(bomb.STORE_KEY), root.innerHTML.includes('value="revenge"'), root.innerHTML.includes("bomb at noon")];
// pusty formularz: CLEAR bez pytania
fire("click", btn({ act: "clear" }));
o.emptyClear = asked;
view.destroy();
o.afterDestroy = root.on.size;
console.log(JSON.stringify(o));
"""


def test_bomb_phone_mount_clear_and_now(tmp_path):
    """BOMB PHONE: formularz z zapisu karty, każda zmiana pola zapisana (odznaczone pole wyboru usunięte, obce klucze
    pominięte), NOW wpisuje czas UTC, pustą datę i czas trwania, CLEAR pyta przy wypełnionym formularzu i czyści zapis,
    destroy() zdejmuje nasłuchy."""
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text(HB_API, "utf-8")
    src = (FRONTEND / "js" / "bombphone.js").read_text("utf-8")
    (tmp_path / "bombphone.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(BOMB_MOUNT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "bombphone.mjs").as_uri()], capture_output=True,
                       text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["appended"] is True and o["start"] is True and o["events"] == ["change", "click", "input"]
    assert o["afterFields"] == {"q-why": "revenge", "words": "bomb at noon", "v-calm": True}
    assert o["afterStart"] == {**o["afterFields"], "c-start": "13:02:03", "c-date": "2026-11-09"}
    # ten sam czas: czas trwania 0 min 00 s
    assert o["afterEnd"] == {**o["afterStart"], "c-end": "13:02:03", "c-dur": "0 min 00 s"}
    assert o["fieldValues"] == ["13:02:03", "13:02:03", "2026-11-09", "0 min 00 s"]
    assert o["refused"] == [1, True]
    assert o["cleared"] == [2, False, False, False]
    assert o["emptyClear"] == 2 and o["afterDestroy"] == 0


# 0.13.2 (przegląd): czas trwania liczony po każdym NOW i każdej zmianie czasu, aż do ręcznego wpisu
BOMB_DUR = r"""
const fields = new Map();
globalThis.__makeEl = (html) => {
  const el = { innerHTML: "", on: new Map(),
    addEventListener(t, f) { this.on.set(t, f); }, removeEventListener(t, f) { if (this.on.get(t) === f) this.on.delete(t); },
    querySelector(sel) { const k = /data-k="([^"]+)"/.exec(sel)?.[1]; if (!fields.has(k)) fields.set(k, { value: "", dataset: { k } }); return fields.get(k); } };
  globalThis.__root = el;
  return el;
};
const bomb = await import(process.argv[2]);
const saved = new Map();
const store = { getItem: (k) => saved.get(k) ?? null, setItem: (k, v) => saved.set(k, v), removeItem: (k) => saved.delete(k) };
let t = Date.UTC(2026, 10, 9, 13, 46, 40);
const mount = () => { fields.clear(); return bomb.mountBombPhone({ append() {} }, { store, ask: () => true, now: () => new Date(t) }); };
let view = mount();
const fire = (type, target) => globalThis.__root.on.get(type)({ target });
const now = (k) => fire("click", { closest: () => ({ dataset: { act: "now", for: k } }) });
// wpis z klawiatury: wartość w polu i zdarzenie input z tego pola
const type = (k, v) => { const el = globalThis.__root.querySelector(`[data-k="${k}"]`); el.value = v; fire("input", el); };
const form = () => JSON.parse(saved.get(bomb.STORE_KEY) || "{}");
// pole w atrapie: wartość ustawiona przez kod, inaczej wartość z narysowanego HTML (jak w przeglądarce)
const shown = (k) => fields.has(k) ? fields.get(k).value
  : new RegExp(`data-k="${k}" value="([^"]*)"`).exec(globalThis.__root.innerHTML)?.[1];
const snap = () => { const f = form(); return [f["c-start"], f["c-end"], f["c-dur"], shown("c-dur")]; };
const clear = () => fire("click", { closest: () => ({ dataset: { act: "clear" } }) });
const o = {};
// powtórne NOW przy końcu (dzwoniący naprawdę się rozłączył): czas trwania poprawiony
now("c-start"); t += 1000; now("c-end"); o.firstEnd = snap();
t += 3000; now("c-end"); o.againEnd = snap();
// NOW przy początku po NOW przy końcu: początek później niż koniec, czas trwania pusty (nie 1439 min)
clear(); now("c-end"); t += 2000; now("c-start"); o.endFirst = snap();
// kolejne NOW przy końcu daje już poprawny czas trwania
t += 5000; now("c-end"); o.endAfter = snap();
// czasy wpisane ręcznie: czas trwania liczony przy każdej zmianie, zły czas w trakcie pisania czyści pole
clear(); type("c-start", "12:00:00"); o.typedStart = snap();
type("c-end", "12:03"); o.typedPartial = snap();
type("c-end", "12:03:1"); o.typedBad = snap();
type("c-end", "12:03:10"); o.typedEnd = snap();
type("c-start", "11:59:10"); o.typedFix = snap();
// po Reload (nowy mount z zapisu) czas trwania z obu czasów dalej liczony sam
view.destroy(); view = mount(); type("c-end", "12:05:10"); o.reloadAuto = snap();
// czas trwania wpisany ręcznie zostaje przy NOW, zmianie czasu i po Reload
type("c-dur", "about 6 min"); t += 60000; now("c-end"); type("c-start", "11:00:00"); o.manual = snap();
view.destroy(); view = mount(); now("c-start"); o.manualReload = snap();
// pole wyczyszczone ręcznie: czas trwania znów liczony sam
type("c-dur", ""); type("c-start", "13:46:00"); o.manualCleared = snap();
// CLEAR zaczyna od nowa: NOW start i NOW koniec znów liczą czas trwania
clear(); now("c-start"); t += 75000; now("c-end"); o.afterClear = snap();
console.log(JSON.stringify(o));
"""


def test_bomb_phone_duration_follows_times(tmp_path):
    """BOMB PHONE: czas trwania liczony z obu czasów po każdym NOW i każdej ręcznej zmianie czasu (powtórne NOW przy
    końcu go poprawia), koniec przed początkiem daje puste pole, czas trwania wpisany ręcznie zostaje (też po Reload),
    wyczyszczony znów liczony sam."""
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text(HB_API, "utf-8")
    src = (FRONTEND / "js" / "bombphone.js").read_text("utf-8")
    (tmp_path / "bombphone.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(BOMB_DUR, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "bombphone.mjs").as_uri()], capture_output=True,
                       text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    # [c-start, c-end, c-dur w zapisie, c-dur w polu]
    assert o["firstEnd"] == ["13:46:40", "13:46:41", "0 min 01 s", "0 min 01 s"]
    assert o["againEnd"] == ["13:46:40", "13:46:44", "0 min 04 s", "0 min 04 s"]
    assert o["endFirst"] == ["13:46:46", "13:46:44", None, ""]
    assert o["endAfter"] == ["13:46:46", "13:46:51", "0 min 05 s", "0 min 05 s"]
    assert o["typedStart"] == ["12:00:00", None, None, ""]
    assert o["typedPartial"] == ["12:00:00", "12:03", "3 min 00 s", "3 min 00 s"]
    assert o["typedBad"] == ["12:00:00", "12:03:1", None, ""]
    assert o["typedEnd"] == ["12:00:00", "12:03:10", "3 min 10 s", "3 min 10 s"]
    assert o["typedFix"] == ["11:59:10", "12:03:10", "4 min 00 s", "4 min 00 s"]
    assert o["reloadAuto"] == ["11:59:10", "12:05:10", "6 min 00 s", "6 min 00 s"]
    assert o["manual"] == ["11:00:00", "13:47:51", "about 6 min", "about 6 min"]
    assert o["manualReload"] == ["13:47:51", "13:47:51", "about 6 min", "about 6 min"]
    assert o["manualCleared"] == ["13:46:00", "13:47:51", "1 min 51 s", "1 min 51 s"]
    assert o["afterClear"] == ["13:47:51", "13:49:06", "1 min 15 s", "1 min 15 s"]
