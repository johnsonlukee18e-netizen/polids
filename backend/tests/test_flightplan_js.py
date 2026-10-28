"""OTHER › FLIGHT PLAN i FMP (0.13.0, issue #23) w Node: fplHtml (escapowanie tekstów z sieci, N0450 / F370 / EET H:MM,
pola 18 rozbite na wskaźniki, PREFILED, brak planu, brak godzin), pomocnicze formatowanie, fmpRows / fmpHtml (godzina
bieżąca zamiast hours[0], brak przepustowości, aktywne na szarym tle, kolejność) oraz zasady plików: napisy bez źródeł
danych, po angielsku, bez pogrubień, ostre krawędzie, bez cieni."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
JS = FRONTEND / "js"

NODE_SCRIPT = r"""
const fp = await import(process.argv[2]);
const v = await import(process.argv[3]);
const fmp = await import(process.argv[4]);
const plan = { rules: "I", aircraft_icao: "B38M/M-SDE2E3FGHIJ1RWXY/LB1", aircraft: "B38M", aircraft_faa: "H/B38M/L", wake: "M",
  departure: "EPWA", deptime: "1530", tas: "450", altitude: "37000", route: "OLILA <script>alert(1)</script> L621 RILAB",
  arrival: "EPGD", enroute_time: "0045", alternate: "EPPO", fuel_time: "0230",
  remarks: "PBN/A1B1 DOF/261028 REG/SPLKA RMK/TCAS <img src=x onerror=alert(1)> /V/", revision_id: 3, assigned_squawk: "4521" };
const online = { callsign: "LOT3827", status: "online", pid: 1234567, name: 'Jan "Kowalski" <EPKK>', first_name: "Jan",
  last_name: "Kowalski<i>", pilot_rating: { id: 1, short: "PPL", long: "Private Pilot License" },
  hours: { pilot: 812.44, atc: 0 }, hours_error: null, flight_plan: plan,
  position: { lat: 52.1, lon: 20.9, altitude: 3500.4, groundspeed: 210, heading: 360, squawk: "4521" } };
const prefiled = { callsign: "LOT45", status: "prefiled", pid: 7654321, name: "Anna Maria Nowak", first_name: "Anna",
  last_name: "Maria Nowak", pilot_rating: null, hours: null, hours_error: "Hours unavailable",
  flight_plan: { ...plan, route: "DCT", remarks: null, tas: "N0280", altitude: "3500", enroute_time: "130", fuel_time: "x",
    revision_id: null, assigned_squawk: null }, position: null };
const noplan = { ...online, callsign: "SPKAT", flight_plan: null, name: null, first_name: null, last_name: null };
const pending = { ...prefiled, callsign: "LOT46", hours_error: null, hours_pending: true,
  flight_plan: { ...prefiled.flight_plan, remarks: "RMK/NEW PILOT /T/" } };
const receive = { ...online, flight_plan: { ...plan, remarks: "/r/ RMK/X" }, position: { ...online.position, heading: 0 } };
const tv = (id, o) => ({ id, hours: [], occupancy: [], peak_60: 0, entries_cap: null, occupancy_cap: null, restrictions: [], ...o });
const sectors = { prefix: "EP", now: "1430", sectors: [
  tv("EP-CL", { active: false, entries_cap: 40, hours: [{ hour: "15", entries: 3, entries_cap: 40 }] }),
  tv("EP-ALLFIR", { active: false, restricted: true, entries_cap: 52, occupancy_cap: 20, occupancy: [4, 5], peak_60: 7,
    hours: [{ hour: "14", entries: 1, entries_cap: 52 }], regulated: { entries: 30, occupancy: null },
    restrictions: [{ type: "ENR-ENTRIES", value: 30, start: "1400", end: "1600" }, { type: "OTHER", value: 5, start: "1800", end: "1900" }] }),
  tv("EP-WATMA", { active: true, occupancy_cap: 20, occupancy: [21, 20], peak_60: 23, hours: [{ hour: "14", entries: 25, entries_cap: null }] }),
  tv("EP-BH", { active: true, entries_cap: 44, occupancy_cap: 14, occupancy: [9, 9, 10], peak_60: 12,
    hours: [{ hour: "15", entries: 30, entries_cap: 45 }, { hour: "14", entries: 18, entries_cap: 45 }] }),
  tv("EP-DM", { status: 1, entries_cap: 45, hours: [{ hour: "14", entries: 41, entries_cap: 45 }], occupancy: [1] }),
  tv("EP-<X>", { active: false }),
  tv("EP-WATMAD", { active: true, restricted: true, entries_cap: 30, occupancy_cap: 15, occupancy: [14], regulated: { entries: 40, occupancy: 12 },
    hours: [{ hour: "14", entries: 29, entries_cap: 30 }] }),
  tv("EP-NFIR", { active: false }), tv("EP-BL", { active: false }), tv("EP-BM", { active: false }), tv("EP-KKTMA", { active: false }),
] };
console.log(JSON.stringify({
  html: { online: fp.fplHtml(online), prefiled: fp.fplHtml(prefiled), noplan: fp.fplHtml(noplan), pending: fp.fplHtml(pending),
    receive: fp.fplHtml(receive) },
  voice: ["PBN/A1 /V/", "/R/", "RMK/TEXT /t/", "/V/ /T/", "RMK/VOICE", "", null].map(fp.voiceType),
  bad: fp.CALLSIGN_BAD,
  speed: ["450", "85", "N0450", "K0830", "M078", "", "0", "abc", null].map(fp.speedText),
  level: ["37000", "FL370", "F370", "370", "3500", "A045", "6500", "VFR", "", "0", null].map(fp.levelText),
  dur: ["0130", "0045", "45", "130", "2359", "1260", "abc", null].map(fp.durationText),
  clock: ["1530", "930", "2400", "1260", "x"].map(fp.clockText),
  hours: [812.44, 0, null, "5"].map(fp.hoursText),
  clean: ["sp-abc 1", "lot3827", " Łot1 ", "ABCDEFGHIJKLMNOP"].map(fp.cleanCallsign),
  valid: ["LOT1", "A", "ABCDEFGHIJKL", "ABCDEFGHIJKLM"].map((s) => fp.CALLSIGN_RE.test(s)),
  f18: fp.field18(plan.remarks), eq: fp.equipment(plan.aircraft_icao), eqFaa: fp.equipment("B738/L"),
  rows: v.fmpRows(sectors), empty: v.fmpRows({ prefix: "EP", now: "1430", sectors: [] }),
  fmpHtml: fmp.fmpHtml(sectors), fmpEmpty: fmp.fmpHtml({ sectors: [] }), info: fmp.fmpInfo(sectors),
  pair: [[18, 45], [null, 45], [18, null], [null, null], [0, 0]].map(([a, b]) => v.pairText(a, b)),
  capOf: [[45, null], [null, 30], [45, 30], [30, 45], [null, null]].map(([a, b]) => v.capOf(a, b)),
  now: v.tvNow(sectors.sectors[3], "1430"),
  exports: [typeof fp.mountFlightPlan, typeof fmp.mountFmp],
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("fpljs")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    for name in ("flightplan", "viffchart", "fmp"):
        src = (JS / f"{name}.js").read_text("utf-8")
        (d / f"{name}.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"').replace('"./viffchart.js"', '"./viffchart.mjs"'),
                                       "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), *((d / f"{n}.mjs").as_uri() for n in ("flightplan", "viffchart", "fmp"))],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _box(html, label):
    """Wartość kratki o etykiecie `label` (pierwszej takiej)."""
    m = re.search(r'<span class="fpb-k">' + re.escape(label) + r'</span><span class="fpb-v">(.*?)</span>', html)
    return m.group(1) if m else None


def test_fpl_online(js):
    h = js["html"]["online"]
    assert '<span class="fpl-cs">LOT3827</span>' in h and ">ONLINE</span>" in h and "PREFILED" not in h
    assert '<a class="fpl-map" href="#map/LOT3827"' in h and "MAP \u203a" in h
    # pola planu w kolejności ICAO, wartości w formacie planu
    order = [int(n) for n in re.findall(r'<span class="fpl-n" title="Item (\d+):', h)]
    assert order == [7, 8, 9, 10, 13, 15, 16, 18, 19]
    assert _box(h, "Speed") == "N0450" and _box(h, "Level") == "F370" and _box(h, "EET") == "0:45"
    assert _box(h, "Endurance") == "2:30" and _box(h, "EOBT") == "1530" and _box(h, "SSR") == "4521"
    assert _box(h, "Rules") == "I" and _box(h, "Type") == "B38M" and _box(h, "Wake") == "M"
    assert _box(h, "Equipment") == "SDE2E3FGHIJ1RWXY" and _box(h, "Surveillance") == "LB1"
    assert _box(h, "ADEP") == "EPWA" and _box(h, "ADES") == "EPGD" and _box(h, "ALTN") == "EPPO"
    # pole 18 rozbite na wskaźniki; /V/ nie w uwagach, tylko jako łączność głosowa w polu 10
    assert _box(h, "PBN") == "A1B1" and _box(h, "DOF") == "261028" and _box(h, "REG") == "SPLKA"
    assert _box(h, "RMK") == "TCAS &lt;IMG SRC=X ONERROR=ALERT(1)&gt;" and "/V/" not in h
    assert _box(h, "Voice") == "VOICE" and 'title="Full voice"' in h and "voice-limited" not in h
    # pilot: imię i nazwisko z pełną nazwą w dymku, PID, godziny, rating
    assert _box(h, "First name") == "Jan" and _box(h, "Last name") == "Kowalski&lt;i&gt;"
    assert 'title="Name as entered: Jan &quot;Kowalski&quot; &lt;EPKK&gt;"' in h
    assert _box(h, "PID") == "1234567" and _box(h, "Pilot hours") == "812.4" and _box(h, "ATC hours") == "0.0"
    assert _box(h, "Rating") == "PPL" and 'title="Private Pilot License"' in h and "fpl-note" not in h
    # teraz: wysokość, GS, kurs 360 jak w ATC (nie 000)
    assert _box(h, "Altitude") == "3500 ft" and _box(h, "GS") == "210 kt" and _box(h, "HDG") == "360"
    assert "revision 3" in h


def test_fpl_escapes_feed_text(js):
    for h in js["html"].values():
        assert "<script" not in h and "<img" not in h and "<EPKK>" not in h and "<i>" not in h
    assert "OLILA &lt;script&gt;alert(1)&lt;/script&gt; L621 RILAB" in js["html"]["online"]


def test_fpl_prefiled_and_no_plan(js):
    h = js["html"]["prefiled"]
    assert ">PREFILED</span>" in h and ">ONLINE<" not in h and "fpl-now" not in h
    # lotu przed połączeniem nie ma na mapie: bez MAP ›
    assert "fpl-map" not in h and "#map/" not in h
    assert _box(h, "Voice") == "\u2013" and 'title="No voice type in the remarks"' in h
    assert _box(h, "Speed") == "N0280" and _box(h, "Level") == "A035" and _box(h, "EET") == "1:30"
    assert _box(h, "Endurance") == "–" and _box(h, "SSR") == "–" and _box(h, "Other information") == "–"
    assert _box(h, "Pilot hours") == "–" and _box(h, "ATC hours") == "–" and _box(h, "Rating") == "–"
    assert '<p class="fpl-note">Hours unavailable</p>' in h and "revision" not in h
    assert (_box(h, "First name"), _box(h, "Last name")) == ("Anna", "Maria Nowak")
    n = js["html"]["noplan"]
    assert "No flight plan filed." in n and "fpl-item" not in n and 'title="No name entered"' in n
    assert _box(n, "First name") == "–" and ">ONLINE</span>" in n


def test_fpl_hours_pending_and_voice(js):
    """Godziny w drodze (hours_pending): "Loading hours…" zamiast "Hours unavailable"; /T/ i /R/ wyróżnione."""
    h = js["html"]["pending"]
    assert '<p class="fpl-note pending">Loading hours\u2026</p>' in h and "Hours unavailable" not in h
    assert _box(h, "Pilot hours") == "\u2013" and 'title="Loading hours"' in h
    assert _box(h, "Voice") == "TEXT ONLY" and 'class="fpb voice-limited" title="Text only, no voice"' in h
    assert _box(h, "RMK") == "NEW PILOT"
    r = js["html"]["receive"]
    assert _box(r, "Voice") == "RECEIVE ONLY" and "voice-limited" in r and _box(r, "HDG") == "360"
    assert js["voice"] == ["V", "R", "T", "T", None, None, None]
    assert js["bad"] == "Callsign must be 2\u201312 letters or digits"


def test_fpl_helpers(js):
    assert js["speed"] == ["N0450", "N0085", "N0450", "K0830", "M078", None, None, None, None]
    assert js["level"] == ["F370", "F370", "F370", "F370", "A035", "A045", "F065", "VFR", None, None, None]
    assert js["dur"] == ["1:30", "0:45", "0:45", "1:30", "23:59", None, None, None]
    assert js["clock"] == ["1530", "0930", None, None, None]
    assert js["hours"] == ["812.4", "0.0", None, None]
    assert js["clean"] == ["SPABC1", "LOT3827", "OT1", "ABCDEFGHIJKL"]
    assert js["valid"] == [True, False, True, False]
    assert js["f18"] == {"PBN": "A1B1", "DOF": "261028", "REG": "SPLKA", "RMK": "TCAS <IMG SRC=X ONERROR=ALERT(1)>"}
    assert js["eq"] == {"type": "B38M", "wake": "M", "navcom": "SDE2E3FGHIJ1RWXY", "surv": "LB1"}
    assert js["eqFaa"] == {"type": "B738", "wake": "L", "navcom": None, "surv": None}
    assert js["exports"] == ["function", "function"]


def test_fmp_rows(js):
    rows = js["rows"]
    # aktywne na początku (active albo status 1), potem jak w PANDORZE: sektory po literze (L, M, H), kombinacje,
    # TMA, części FIR
    assert [r["id"] for r in rows] == ["EP-BH", "EP-DM", "EP-WATMA", "EP-WATMAD", "EP-BL", "EP-BM", "EP-CL", "EP-<X>",
                                       "EP-KKTMA", "EP-ALLFIR", "EP-NFIR"]
    assert [r["active"] for r in rows] == [True] * 4 + [False] * 7
    by = {r["id"]: r for r in rows}
    bh = by["EP-BH"]
    # bieżąca godzina (14) po godzinie, nie hours[0] (15)
    assert (bh["code"], bh["capacity"], bh["occupancyText"]) == ("BH", "18 (45)", "9 (14)")
    assert bh["capacityTip"] == "18 entries this hour, capacity 45"
    assert bh["occupancyTip"] == "9 aircraft in the sector now, capacity 14 · peak 12 within the hour"
    assert bh["sectorTip"] == "EP-BH: sector B upper · active" and bh["label"] == "sector B upper"
    assert js["now"] == {"entries": 18, "entriesCap": 45, "entriesReg": None, "occupancy": 9, "occupancyCap": 14,
                         "occupancyReg": None, "peak": 12}
    assert not bh["capacityReg"] and not bh["occupancyReg"] and (bh["entriesMax"], bh["occupancyMax"]) == (45, 14)
    wa = by["EP-WATMA"]
    assert (wa["capacity"], wa["occupancyText"], wa["occupancyCls"], wa["entriesCls"]) == ("25 (–)", "21 (20)", "over", "nolim")
    assert wa["capacityTip"] == "25 entries this hour, no limit"
    # tylko następna godzina: liczby wejść brak, przepustowość z definicji; bez zajętości i limitu samo "–"
    cl = by["EP-CL"]
    assert (cl["capacity"], cl["occupancyText"]) == ("– (40)", "–")
    assert cl["capacityTip"] == "No entry count this hour, capacity 40"
    assert cl["occupancyTip"] == "No occupancy data, no limit · peak 0 within the hour"
    assert by["EP-DM"]["entriesCls"] == "near" and by["EP-BH"]["entriesCls"] == "ok"
    al = by["EP-ALLFIR"]
    # regulacja wejść 30 obowiązuje teraz: przepustowość 30 (niższa od deklarowanej 52), obie w dymku
    assert al["restricted"] and al["capacity"] == "1 (30)" and al["capacityReg"] and not al["occupancyReg"]
    assert al["capacityTip"] == "1 entry this hour, regulated 30, declared 52"
    assert al["occupancyTip"] == "4 aircraft in the sector now, capacity 20 \u00b7 peak 7 within the hour"
    # regulacja bez limitu deklarowanego, wyższa od deklarowanej (bez wpływu) i niższa (obciążenie z niej)
    wd = by["EP-WATMAD"]
    assert (wd["capacity"], wd["capacityReg"], wd["entriesCls"]) == ("29 (30)", False, "near")
    assert wd["capacityTip"] == "29 entries this hour, regulated 40, declared 30"
    assert (wd["occupancyText"], wd["occupancyReg"], wd["occupancyCls"]) == ("14 (12)", True, "over")
    assert wd["occupancyTip"].startswith("14 aircraft in the sector now, regulated 12, declared 15")
    assert js["capOf"] == [45, 30, 30, 30, None]
    assert al["sectorTip"] == ("EP-ALLFIR: whole FIR · inactive · regulated now · regulations: entries 30 1400–1600, "
                               "other 5 1800–1900")
    assert js["empty"] == [] and js["pair"] == ["18 (45)", "– (45)", "18 (–)", "–", "0 (0)"]


def test_fmp_html(js):
    h = js["fmpHtml"]
    assert re.findall(r"<th[^>]*>([A-Z ()]+)</th>", h) == ["SECTOR", "CAPACITY (ENTRIES)", "OCCUPANCY"]
    trs = re.findall(r'<tr class="(on|off)" data-tv="([^"]+)">', h)
    assert trs[:4] == [("on", "EP-BH"), ("on", "EP-DM"), ("on", "EP-WATMA"), ("on", "EP-WATMAD")]
    assert ("off", "EP-&lt;X&gt;") in trs and len(trs) == 11
    # przepustowość z regulacji: liczba w nawiasie czerwona
    assert 'title="1 entry this hour, regulated 30, declared 52">1 (<span class="fmp-regcap">30</span>)</td>' in h
    assert '>14 (<span class="fmp-regcap">12</span>)</td>' in h and h.count("fmp-regcap") == 2
    assert '<td class="fmp-sec" title="EP-BH: sector B upper · active">BH</td>' in h
    assert 'title="18 entries this hour, capacity 45">18 (45)</td>' in h
    assert '<td class="fmp-num over" title="21 aircraft in the sector now' in h and '<td class="fmp-num near"' in h
    assert '<td class="fmp-sec reg"' in h and ">&lt;X&gt;</td>" in h and "<X>" not in h
    assert js["fmpEmpty"] == '<p class="hint fmp-empty">No sectors.</p>'
    assert js["info"] == "1430Z \u00b7 4 of 11 active (grey rows)"


# --- zasady plików

NEW_JS = ["flightplan.js", "fmp.js"]
NEW_CSS = ["flightplan.css", "fmp.css"]
# nazwy źródeł i opisy pochodzenia danych (jak test_other_tab.PROVENANCE, plus nazwy usług i przepisów)
# (nazwy z wielkimi literami dokładnie: pole aircraft_icao i adres /api/viff/ to nie napisy interfejsu)
_NAMES = r"VATSIM|vIFF|EUROCONTROL|PANSA|PAŻP|\bSERA\b|\bULC\b|\bEASA\b|\bICAO\b|Doc 4444"
_PHRASES = r"(?i:source:|according to|based on|api\.vatsim|viffsys|data feed|member api)"
PROVENANCE = re.compile(_NAMES + "|" + _PHRASES)


def _code(path):
    src = re.sub(r"/\*.*?\*/", "", path.read_text("utf-8"), flags=re.S)
    return "\n".join(line for line in re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M).splitlines()
                     if not line.startswith("import "))


@pytest.mark.parametrize("name", NEW_JS)
def test_new_modules_without_provenance(name):
    code = _code(JS / name)
    assert not PROVENANCE.search(code), PROVENANCE.search(code).group(0)
    if name == "flightplan.js":
        assert '"Pilot hours"' in code and '"ATC hours"' in code


def test_fmp_helpers_without_provenance():
    src = (JS / "viffchart.js").read_text("utf-8")
    part = _code(JS / "viffchart.js")[_code(JS / "viffchart.js").index("const num = "):]
    assert "export function fmpRows(data)" in src and "export function tvNow(tv, now)" in src
    assert not PROVENANCE.search(part), PROVENANCE.search(part).group(0)


@pytest.mark.parametrize("name", NEW_JS + ["viffchart.js"])
def test_new_modules_english_no_bold(name):
    """Polskie znaki tylko w komentarzach w osobnych linijkach; bez <b>/<strong> (cała aplikacja bez pogrubień)."""
    src = (JS / name).read_text("utf-8")
    polish = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
    bad = [line.strip() for line in src.splitlines() if polish.search(line) and not line.strip().startswith("//")]
    assert not bad, bad
    if name != "viffchart.js":       # wykres MAP (inny obszar) ma jeszcze <b>
        assert not re.search(r"<(b|strong)[\s>]", src)


@pytest.mark.parametrize("name", NEW_CSS)
def test_new_css_rules(name):
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / name).read_text("utf-8"), flags=re.S)
    assert all(r.strip() == "0" for r in re.findall(r"border(?:-[a-z]+)*-radius:\s*([^;}]+)", css))
    assert "text-shadow" not in css and "glow" not in css
    assert all(v.strip() in ("none",) or v.strip().startswith(("inset", "0 0 0 "))
               for v in re.findall(r"box-shadow:\s*([^;}]+)", css))
    assert not re.search(r"font-weight:\s*(bold|[6-9]00)|font:\s*(bold|[6-9]00)\b", css)
    assert not re.search(r"[.#](?:ad|ads|banner|promo|sponsor)\b", css)
    index = (FRONTEND / "index.html").read_text("utf-8")
    assert f'href="/static/css/{name}"' in index


def test_contract_exports():
    fp = (JS / "flightplan.js").read_text("utf-8")
    assert 'export function mountFlightPlan(pane, { start = "", onLookup = () => {} } = {})' in fp
    assert "activate(arg)" in fp and "focus," in fp and "destroy()" in fp and "export function fplHtml(d)" in fp
    assert 'from "./strips.js"' not in fp and "removeEventListener(ONLINE_EVENT" in fp and "clearInterval" in fp
    fmp = (JS / "fmp.js").read_text("utf-8")
    assert "export function mountFmp(pane)" in fmp and "activate()" in fmp and "destroy()" in fmp
    assert "removeEventListener(ONLINE_EVENT" in fmp and "clearInterval(timer)" in fmp
    assert 'api("/api/viff/sectors")' in fmp


# --- zachowanie strony (atrapa DOM w Node): odświeżenie, 404, zły znak, fokus

FP_API_STUB = r"""
// atrapa elementu: pola, nasłuchy (on), querySelector zwraca stały element potomny; innerHTML liczy zapisy
const makeEl = () => ({ value: "", _html: "", writes: 0, textContent: "", className: "", kids: {}, on: {},
  isConnected: true, offsetParent: {},
  get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; this.writes += 1; },
  addEventListener(t, f) { (this.on[t] ||= []).push(f); },
  focus() { globalThis.__focus += 1; }, select() {},
  querySelector(sel) { return (this.kids[sel] ||= makeEl()); } });
export const ONLINE_EVENT = "polids:online";
export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
export const h = () => makeEl();
export const api = (url) => new Promise((res, rej) => globalThis.__pending.push({ url, res, rej }));
"""

FP_MOUNT_SCRIPT = r"""
globalThis.__focus = 0;
globalThis.__pending = [];
const timers = [];
globalThis.setInterval = (f) => { timers.push(f); return timers.length; };
globalThis.clearInterval = () => {};
globalThis.setTimeout = (f) => { timers.push(f); return timers.length; };
globalThis.clearTimeout = () => {};
globalThis.window = { addEventListener() {}, removeEventListener() {} };
const fp = await import(process.argv[2]);
const tick = () => new Promise((r) => setImmediate(r));
const pane = { append(x) { this.root = x; } };
const looked = [];
const d = { callsign: "LOT3827", status: "online", pid: 1, first_name: "Jan", last_name: "K", hours: { pilot: 1, atc: 2 },
  hours_error: null, flight_plan: null, position: { altitude: 1000, groundspeed: 100, heading: 90, squawk: "2000" } };
const fail = (msg, status) => Object.assign(new Error(msg), { status });
const page = fp.mountFlightPlan(pane, { start: "LOT3827", onLookup: (cs) => looked.push(cs) });
const root = pane.root, input = root.querySelector(".fpl-q"), out = root.querySelector(".fpl-out"), msg = root.querySelector(".fpl-msg");
const o = { focusAfterMount: globalThis.__focus, requests: globalThis.__pending.map((p) => p.url) };
globalThis.__pending.shift().res(d);
await tick();
o.shown = out.innerHTML.includes(">ONLINE<");
const writes = out.writes;
// odświeżenie z tymi samymi danymi: bez rysowania od nowa (zaznaczenie zostaje)
timers[0]();
globalThis.__pending.shift().res(structuredClone(d));
await tick();
o.sameWrites = out.writes - writes;
// odświeżenie z błędem serwera: plan zostaje, komunikat nad nim
timers[0]();
globalThis.__pending.shift().rej(fail("Network data unavailable", 502));
await tick();
o.after502 = [out.innerHTML.includes(">ONLINE<"), msg.textContent];
// odświeżenie z 404: pilot rozłączony, plan znika (bez ONLINE i Now)
timers[0]();
globalThis.__pending.shift().rej(fail("No flight plan for LOT3827", 404));
await tick();
o.after404 = [out.innerHTML.includes(">ONLINE<"), out.innerHTML.includes("fpl-now"), out.innerHTML, msg.textContent];
// wraca: następne odświeżenie znowu pokazuje plan
timers[0]();
globalThis.__pending.shift().res(d);
await tick();
o.back = out.innerHTML.includes(">ONLINE<");
// zły znak z pola: plan i adres bez zmian, tylko komunikat
const enter = () => input.on.keydown.forEach((f) => f({ key: "Enter", preventDefault() {} }));
input.value = "X";
enter();
o.invalid = [out.innerHTML.includes(">ONLINE<"), msg.textContent, globalThis.__pending.length, [...looked]];
// pusty znak z pola przy pokazanym planie: pusty formularz i onLookup("") (adres bez znaku)
input.value = "";
enter();
o.cleared = [out.innerHTML.includes("Type a callsign"), [...looked]];
input.value = "sp-kat";
enter();
o.lookup = [[...looked], globalThis.__pending.map((p) => p.url)];
page.destroy();
console.log(JSON.stringify(o));
"""


def test_flightplan_page_behaviour(tmp_path):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    (tmp_path / "api.mjs").write_text(FP_API_STUB, "utf-8")
    src = (JS / "flightplan.js").read_text("utf-8")
    (tmp_path / "flightplan.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(FP_MOUNT_SCRIPT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "flightplan.mjs").as_uri()], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["focusAfterMount"] >= 1                            # kliknięcie FLIGHT PLAN: od razu można pisać
    assert o["requests"] == ["/api/vatsim/flightplan/LOT3827"] and o["shown"]
    assert o["sameWrites"] == 0
    assert o["after502"] == [True, "Not refreshed: Network data unavailable"]
    online, now, html, note = o["after404"]
    assert not online and not now and "No flight plan for LOT3827" in html and note == ""
    assert o["back"]
    assert o["invalid"] == [True, "Callsign must be 2–12 letters or digits", 0, []]
    assert o["cleared"] == [True, [""]]
    assert o["lookup"] == [["", "SPKAT"], ["/api/vatsim/flightplan/SPKAT"]]


def test_fmp_and_flightplan_ascii_code():
    """Kod FLIGHT PLAN, FMP i części FMP w viffchart.js tylko w ASCII (znaki typograficzne jako \\u2013, \\u00b7,
    \\u2026, \\u203a); polskie i inne znaki tylko w komentarzach w osobnych linijkach."""
    vc = (JS / "viffchart.js").read_text("utf-8")
    parts = {"flightplan.js": (JS / "flightplan.js").read_text("utf-8"), "fmp.js": (JS / "fmp.js").read_text("utf-8"),
             "viffchart.js FMP": vc[vc.index("// --- OTHER"):]}
    for name, src in parts.items():
        bad = [line.strip() for line in src.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
        assert not bad, (name, bad)
