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
// airspace.js (importowany przez fmp.js) rozszerza klasę Leafleta przy wczytaniu; w przeglądarce L jest globalny
globalThis.L = { CircleMarker: { extend: (o) => o } };
const fp = await import(process.argv[2]);
const v = await import(process.argv[3]);
const fmp = await import(process.argv[4]);
const xl = await import(process.argv[5]);
const plan = { rules: "I", aircraft_icao: "B38M/M-SDE2E3FGHIJ1RWXY/LB1", aircraft: "B38M", aircraft_faa: "H/B38M/L", wake: "M",
  departure: "EPWA", deptime: "1530", tas: "450", altitude: "37000", route: "OLILA <script>alert(1)</script> L621 RILAB",
  arrival: "EPGD", enroute_time: "0045", alternate: "EPPO", fuel_time: "0230",
  remarks: "PBN/A1B1 DOF/261028 REG/SPLKA RMK/TCAS <img src=x onerror=alert(1)> /V/", revision_id: 3, assigned_squawk: "4521" };
const online = { callsign: "LOT3827", status: "online", pid: 1234567, name: 'Jan "Kowalski" <EPKK>', first_name: "Jan",
  last_name: "Kowalski<i>", pilot_rating: { id: 1, short: "PPL", long: "Private Pilot License" },
  hours: { pilot: 812.44, atc: 0 }, hours_error: null, flight_plan: plan, telephony: "POLLOT 3827",
  position: { lat: 52.1, lon: 20.9, altitude: 3500.4, groundspeed: 210, heading: 360, squawk: "4521", vv_fpm: 1300, track: 96,
    turn_rate: 0 },
  label: { route_ahead: ["RILAB", "BIMPA"], fir_exit: { point: "SOXER", level: 340 }, proc: { kind: "STAR", name: "BIMPA6U", runway: "33" },
    next_freq: "134.875" } };
const prefiled = { callsign: "LOT45", status: "prefiled", pid: 7654321, name: "Anna Maria Nowak", first_name: "Anna",
  last_name: "Maria Nowak", pilot_rating: null, hours: null, hours_error: "Hours unavailable",
  flight_plan: { ...plan, route: "DCT", remarks: null, tas: "N0280", altitude: "3500", enroute_time: "130", fuel_time: "x",
    revision_id: null, assigned_squawk: null }, position: null };
const noplan = { ...online, callsign: "SPKAT", flight_plan: null, name: null, first_name: null, last_name: null, telephony: null,
  label: { route_ahead: null, fir_exit: null, proc: null, next_freq: null } };
const pending = { ...prefiled, callsign: "LOT46", hours_error: null, hours_pending: true,
  flight_plan: { ...prefiled.flight_plan, remarks: "RMK/NEW PILOT /T/" } };
const receive = { ...online, flight_plan: { ...plan, remarks: "/r/ RMK/X" }, position: { ...online.position, heading: 0 } };
// 0.14.2: okno EXTENDED LABEL dla różnych lotów (prefile z kodem, VFR bez RVSM, STATE, sam zapis FAA, grupa, długie pola)
const pre2 = { callsign: "SPKAT", status: "prefiled", flight_plan: { ...plan, assigned_squawk: "7001", route: "SOXER L621 RILAB DCT BIMPA" },
  position: null, label: null };
const vfr = { callsign: "SPABC", status: "online", flight_plan: { rules: "V", aircraft_icao: "C172/L-SDFGY/S", aircraft: "C172",
  wake: "L", aircraft_faa: "C172/G", departure: "EPMO", arrival: "EPMO", altitude: "VFR", route: "VFR CIRCUITS RWY 26",
  remarks: "STS/NONRVSM" }, position: { altitude: 1500, groundspeed: 0, heading: 0, squawk: "7000" } };
const state = { callsign: "PLF101", status: "online", flight_plan: { rules: "I", aircraft_icao: "C295/M-SDFGUY/C",
  aircraft: "C295", altitude: "FL200", remarks: "STS/STATE RVR/300" }, position: { squawk: "1234", heading: 45.4, groundspeed: 250,
  vv_fpm: -820, track: 359.6, turn_rate: -2.6 } };
const faa = { callsign: "AAL100", status: "online", flight_plan: { rules: "I", aircraft_icao: "H/B738/L", aircraft: "B738",
  aircraft_faa: "H/B738/L", altitude: "35000" }, position: { squawk: "2200", groundspeed: 451, heading: 90 } };
const group = { callsign: "VIPER1", status: "online", flight_plan: { rules: "I", aircraft_icao: "2/F16/M-SG/C", aircraft: "F16",
  altitude: "FL250" }, position: { squawk: "2201" } };
const big = { callsign: "UAE180ABCDEF", status: "online", telephony: "EMIRATES 180ABCDEFGHIJKLMNOPQRSTUVWXYZ",
  flight_plan: { rules: "I", aircraft_icao: "B77W/H-SADE1E2E3FGHIJ1J3J4J5M1P2RWXYZ/LB1D1", aircraft: "B77W", wake: "H",
    departure: "OMDB", arrival: "EPWA", alternate: "EPMO", altitude: "38000",
    route: "N0490F380 TOMRA1A TOMRA L732 LOGDA LOGDA2W DCT 5230N02000E ABCDE FGHIJ KLMNO PQRST UVWXY",
    remarks: "STS/HOSP MEDEVAC FFR HUM SAR ATFMX PBN/A1B1C1D1L1O1S2T1 ALTN/EPLL EPKK ZZZZ RVR/75 RMK/<script>x</script> TCAS EQUIPPED VERY LONG REMARK" },
  position: { squawk: "2000", heading: 331, groundspeed: 487.4 }, label: { route_ahead: null } };
const xlFlat = (d, o) => xl.extLabel(d).map((ln) => ({ line: ln.line, gap: ln.gap, nr: ln.nr, f: ln.f.map((f) => ({
  k: f.k, l: f.l, w: f.w, max: f.max, right: f.right, t: f.parts ? f.parts.map((p) => p.t).join("") : null,
  cls: f.parts ? f.parts.map((p) => p.cls) : null, full: f.full, tip: f.tip, cut: f.cut })) }));
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
  fmpSel: fmp.fmpHtml(sectors, "EP-BH"),
  pair: [[18, 45], [null, 45], [18, null], [null, null], [0, 0]].map(([a, b]) => v.pairText(a, b)),
  capOf: [[45, null], [null, 30], [45, 30], [30, 45], [null, null]].map(([a, b]) => v.capOf(a, b)),
  now: v.tvNow(sectors.sectors[3], "1430"),
  exports: [typeof fp.mountFlightPlan, typeof fmp.mountFmp],
  eqGroup: fp.equipment("2/F16/M-SG/C"), eqFaaFull: fp.equipment("H/B738/L"),
  xl: Object.fromEntries(Object.entries({ online, prefiled, noplan, pre2, vfr, state, faa, group, big }).map(([k, d]) => [k, xlFlat(d)])),
  xlHtml: { online: xl.xlHtml(online), key: xl.xlHtml(online, { key: true }), big: xl.xlHtml(big), noplan: xl.xlHtml(noplan) },
  fplKey: fp.fplHtml(online, { key: true }),
  rvsm: [["SDFGRWY", "", ""], ["SDFGY", "STATE", ""], ["SDFGY", "NONRVSM", ""], ["SDFGY", "NONRVSM STATE", ""],
    [null, "", "H/B738/L"], [null, "", "B738/W"], [null, "", "B738/Z"], [null, "", "B738/G"], ["SDFGY", "", "H/B738/L"],
    [null, "STATE", "C172/G"], [null, null, null], ["SDFGY", "STATEX", ""]].map(([n, s, f]) => xl.rvsmClass(n, s, f)),
  vhf: ["SDFGY", "SDFGU", "SDFGUY", "SDFG", "", null].map(xl.vhf833Class),
  xpdr: ["LB1", "S", "E", "H", "I", "P", "X", "C", "A", "B1", "", null, "CB1"].map(xl.xpdrType),
  route: [
    xl.routePoints({ departure: "EPWA", arrival: "EPGD", route: "EPWA SOXER7G SOXER L621 RILAB N0450F370 DCT BIMPA BIMPA6U EPGD" }),
    xl.routePoints({ route: "VFR CIRCUITS RWY 26 RWY26 29L LOCAL OVER CITY" }),
    xl.routePoints({ route: "A B CD EFGHIJ 5230N02000E 52N020E DCT/N0450F370 KOLOM KOLOM" }),
    xl.routePoints({ route: "P1A P2B AAA BBB CCC DDD EEE FFF GGG HHH" }),
    xl.routePoints({}),
  ],
  fit: [xl.fitPoints(["AAAAA", "BBBBB"], 41), xl.fitPoints(Array(9).fill("ABCDE"), 41), xl.fitPoints(["ABCDE", "FGHIJ", "KLMNO"], 11)],
  clip: [xl.clip([{ t: "ABCDEFGHIJ", cls: "g" }], 7), xl.clip([{ t: "W", cls: "g" }, { t: "Y", cls: "r" }], 2),
    xl.clip([{ t: "AB ", cls: "" }, { t: "CDEF", cls: "y" }], 5)],
  fmt: { fl3: ["F370", "A035", "VFR", "", null, "M082"].map(xl.fl3), deg3: [0, 360, 45.4, 359.6, -10, null, "90"].map(xl.deg3),
    sh: [1300, -820, 20, -40, 0, null, 51].map(xl.signedHundreds), pad3: [5, 487.4, null].map(xl.pad3) },
  width: xl.XL_WIDTH,
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("fpljs")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    # 0.14.0: fmp.js importuje też airspace.js (kolory stanowisk), dissolve.js i radioboard.js (podglądy konfiguracji)
    for name in ("flightplan", "xlabel", "viffchart", "fmp", "airspace", "dissolve", "radioboard"):
        src = (JS / f"{name}.js").read_text("utf-8")
        (d / f"{name}.mjs").write_text(re.sub(r'"\./([a-z]+)\.js"', r'"./\1.mjs"', src), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), *((d / f"{n}.mjs").as_uri() for n in ("flightplan", "viffchart", "fmp", "xlabel"))],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _box(html, label):
    """Wartość kratki o etykiecie `label` (pierwszej takiej)."""
    m = re.search(r'<span class="fpb-k">' + re.escape(label) + r'</span><span class="fpb-v">(.*?)</span>', html)
    return m.group(1) if m else None


def _xl(html, key):
    """Tekst pola `key` okna EXTENDED LABEL (bez nazwy pola z KEY i bez znaczników; encje zostają)."""
    m = re.search(r'<span class="xl-f[^"]*" data-f="' + re.escape(key) + r'"[^>]*>(.*?)(?=<span class="xl-f|</div>)', html, re.S)
    if not m:
        return None
    return re.sub(r"<[^>]+>", "", re.sub(r'<span class="xl-k">.*?</span>', "", m.group(1)))


def _vals(js, name):
    """{klucz pola: tekst w oknie} dla lotu `name` z extLabel (None = puste pole)."""
    return {f["k"]: f["t"] for ln in js["xl"][name] for f in ln["f"]}


def _cls(js, name):
    return {f["k"]: f["cls"] for ln in js["xl"][name] for f in ln["f"]}


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
    # teraz (0.14.2): sama wysokość; SSR, GS i kurs (360 jak w ATC, nie 000) pokazuje okno EXTENDED LABEL
    assert _box(h, "Altitude") == "3500 ft" and _box(h, "GS") is None and _box(h, "HDG") is None
    now = re.search(r'<section class="fpl-group fpl-now">.*?</section>', h, re.S).group(0)
    assert now.count('<div class="fpb') == 1
    assert _xl(h, "hdg") == "360" and _xl(h, "gs") == "210" and _xl(h, "xpdr") == "S/4521"
    assert "revision 3" in h
    # układ: okno, obok pilot i teraz, pod spodem cały plan lotu
    assert h.index('class="fpl-xl"') < h.index('class="fpl-side"') < h.index("fpl-pilot") < h.index("fpl-now") \
        < h.index("fpl-plan")


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
    assert _box(r, "Voice") == "RECEIVE ONLY" and "voice-limited" in r and _xl(r, "hdg") == "360"
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
    assert js["eq"] == {"count": None, "type": "B38M", "wake": "M", "navcom": "SDE2E3FGHIJ1RWXY", "surv": "LB1"}
    assert js["eqFaa"] == {"count": None, "type": "B738", "wake": "L", "navcom": None, "surv": None}
    # 0.14.2: lot w grupie ("2/F16/M-SG/C": dwa samoloty); pełny zapis FAA z kategorią przed typem nie jest polem 10
    assert js["eqGroup"] == {"count": 2, "type": "F16", "wake": "M", "navcom": "SG", "surv": "C"}
    assert js["eqFaaFull"] == {"count": None, "type": None, "wake": None, "navcom": None, "surv": None}
    assert js["exports"] == ["function", "function"]


# --- 0.14.2 (issue #35): okno EXTENDED LABEL WINDOW (SDD 2014, Figure 2-6, Table 2-13)

LINES = [["cs", "wy", "tel", "xpdr"], ["num", "type", "sts", "orcam"], ["adep", "ades", "altn", "proc", "rwy", "nfq"],
         ["rules", "route", "xfl"], ["cfl", "rfl", "rate", "free", "rvr", "coord"], ["navcom", "surv", "pbn"],
         ["addr", "sel", "hdg", "ias", "mach", "tas"], ["gs", "ivv", "bvv", "tar", "roll", "trk"]]
# szerokości pól w znakach z Table 2-13 (znak: kolumna 7, limit 10)
WIDTHS = {"cs": (7, 10), "wy": 2, "tel": 28, "xpdr": 6, "num": 2, "type": 6, "sts": 20, "orcam": 4, "adep": 4, "ades": 4,
          "altn": 11, "proc": 7, "rwy": 6, "nfq": 7, "rules": 1, "route": 41, "xfl": 4, "cfl": 3, "rfl": 3, "rate": 10,
          "free": 20, "rvr": 6, "coord": 6, "navcom": 18, "surv": 15, "pbn": 16, "addr": 6, "sel": 3, "hdg": 3, "ias": 4,
          "mach": 3, "tas": 4, "gs": 4, "ivv": 4, "bvv": 4, "tar": 3, "roll": 3, "trk": 3}
RIGHT = {"xpdr", "orcam", "nfq", "xfl", "coord", "pbn"}


def test_xl_lines_follow_sdd(js):
    for name, lines in js["xl"].items():
        assert [[f["k"] for f in ln["f"]] for ln in lines] == LINES, name
        assert [ln["gap"] for ln in lines] == [False, False, True, False, False, False, True, False]
        assert [ln["nr"] for ln in lines] == [False] * 6 + [True, True]
    h = js["xlHtml"]["online"]
    assert h.startswith('<section class="fpl-xl" aria-label="Extended label"><div class="xl-head">'
                        '<span class="xl-t">EXTENDED LABEL WINDOW</span>')
    assert re.findall(r'<div class="xl-ln[^"]*" data-ln="(\d)">', h) == [str(i) for i in range(1, 9)]
    # wiersz 2 bez wcięcia: w Figure 2-6 wcięcie to pusta kolumna NUM (2 znaki i odstęp) przed typem
    assert '<div class="xl-ln gap" data-ln="3">' in h and '<div class="xl-ln" data-ln="2"><span class="xl-f nil" data-f="num"' in h
    assert '<div class="xl-ln gap nr" data-ln="7">' in h and '<div class="xl-ln nr" data-ln="8">' in h
    assert h.count('<span class="xl-f') == sum(map(len, LINES))


def test_xl_widths_table_2_13(js):
    fields = [f for ln in js["xl"]["online"] for f in ln["f"]]
    for f in fields:
        w, mx = WIDTHS[f["k"]] if isinstance(WIDTHS[f["k"]], tuple) else (WIDTHS[f["k"]],) * 2
        assert (f["w"], f["max"], f["right"]) == (w, mx, f["k"] in RIGHT), f["k"]
    # każdy wiersz (kolumny i odstępy) mieści się w szerokości okna, także ze znakiem 10-znakowym
    for ln in js["xl"]["online"]:
        assert sum(f["max"] for f in ln["f"]) + len(ln["f"]) - 1 <= js["width"] == 54
    # wartości nie dłuższe niż limit pola (z "…")
    for name, lines in js["xl"].items():
        for f in (f for ln in lines for f in ln["f"] if f["t"] is not None):
            assert len(f["t"]) <= f["max"], (name, f)
    h = js["xlHtml"]["online"]
    assert 'data-f="route" style="--w:41"' in h and 'data-f="cs" style="--w:7"' in h


def test_xl_values_online(js):
    v = _vals(js, "online")
    assert (v["cs"], v["wy"], v["tel"], v["xpdr"]) == ("LOT3827", "WY", "POLLOT 3827", "S/4521")
    # ORCAM tylko, gdy kod przydzielony różni się od nadawanego
    assert (v["num"], v["type"], v["sts"], v["orcam"]) == (None, "B38M/M", None, None)
    assert (v["adep"], v["ades"], v["altn"], v["proc"], v["rwy"], v["nfq"]) == ("EPWA", "EPGD", "(EPPO)", "BIMPA6U", "RWY33",
                                                                               "134.875")
    # trasa: punkty przed samolotem z serwera, poziom wyjścia z FIR "/" + 3 cyfry
    assert (v["rules"], v["route"], v["xfl"]) == ("I", "RILAB BIMPA", "/340")
    assert (v["cfl"], v["rfl"], v["rate"], v["rvr"], v["coord"]) == (None, "370", None, None, None)
    assert v["free"] == "TCAS <IMG SRC=X ONE\u2026"
    assert (v["navcom"], v["surv"], v["pbn"]) == ("SDE2E3FGHIJ1RWXY", "LB1", "A1B1")
    assert [v[k] for k in LINES[6]] == [None, None, "360", None, None, None]
    assert [v[k] for k in LINES[7]] == ["210", "+13", None, "0", None, "096"]
    f = {f["k"]: f for ln in js["xl"]["online"] for f in ln["f"]}
    assert f["xfl"]["tip"] == "/340 at SOXER" and f["ivv"]["tip"] == "+1300 ft/min" and f["proc"]["l"] == "STAR"
    assert f["wy"]["tip"] == "RVSM equipped, 8.33 equipped"
    h = js["xlHtml"]["online"]
    assert 'title="FIR exit level: /340 at SOXER"' in h and 'title="Arrival procedure: BIMPA6U"' in h
    assert 'title="Cleared flight level"' in h        # puste pole: sama nazwa w dymku


def test_xl_values_prefiled(js):
    """Prefile: bez kodu transpondera i danych Mode S; ORCAM = kod przydzielony; trasa = pierwsze punkty planu."""
    for name in ("prefiled", "pre2"):
        v = _vals(js, name)
        assert v["xpdr"] is None and all(v[k] is None for k in LINES[6] + LINES[7]), name
        assert v["cs"] and v["rfl"] and v["nfq"] is None and v["proc"] is None
    assert _vals(js, "prefiled")["route"] is None and _vals(js, "prefiled")["orcam"] is None   # trasa "DCT"
    v = _vals(js, "pre2")
    assert v["orcam"] == "7001" and _cls(js, "pre2")["orcam"] == ["y"] and v["route"] == "SOXER RILAB BIMPA"
    # bez planu: znak, W/Y czerwone, kod transpondera bez typu, Mode S
    n = _vals(js, "noplan")
    assert (n["cs"], n["wy"], n["xpdr"], n["hdg"], n["gs"]) == ("SPKAT", "WY", "4521", "360", "210")
    assert _cls(js, "noplan")["wy"] == ["r", "r"]
    assert all(n[k] is None for k in LINES[2] + LINES[3] + LINES[4] + LINES[5])
    # grupa, zapis FAA, STATE
    g = _vals(js, "group")
    assert (g["num"], g["type"], g["navcom"], g["xpdr"]) == ("2", "F16/M", "SG", "C/2201")
    a = _vals(js, "faa")
    assert (a["type"], a["navcom"], a["xpdr"], a["gs"], a["hdg"]) == ("B738", None, "2200", "451", "090")
    st = _vals(js, "state")
    assert (st["sts"], st["rvr"], st["rfl"], st["hdg"], st["ivv"], st["tar"], st["trk"]) == (
        "STATE", "300", "200", "045", "-8", "-3", "360")
    vfr = _vals(js, "vfr")
    assert (vfr["rules"], vfr["rfl"], vfr["route"], vfr["gs"], vfr["hdg"], vfr["sts"]) == ("V", "VFR", None, "000", "360",
                                                                                         "NONRVSM")


def test_xl_colours(js):
    c = _cls(js, "online")
    assert (c["cs"], c["wy"], c["tel"], c["rules"], c["rfl"]) == (["g"], ["g", "g"], ["g"], ["y"], ["y"])
    assert c["xpdr"] == [""] and c["nfq"] == [""] and c["route"] == [""] and c["navcom"] == [""]
    # W: zielone z W w polu 10a (bez pola 10a z sufiksu FAA), żółte tylko z STS/STATE; NONRVSM bez STATE czerwone
    assert _cls(js, "vfr")["wy"] == ["r", "g"] and _cls(js, "state")["wy"] == ["y", "g"]
    assert _cls(js, "faa")["wy"] == ["g", "r"] and _cls(js, "group")["wy"] == ["r", "r"]
    assert _cls(js, "state")["rvr"] == ["y"] and _cls(js, "big")["rvr"] == ["y"]
    assert js["rvsm"] == ["g", "y", "r", "y", "g", "g", "g", "r", "r", "y", "r", "r"]
    assert js["vhf"] == ["g", "y", "g", "r", "r", "r"]
    assert js["xpdr"] == ["S/", "S/", "S/", "S/", "S/", "S/", "S/", "C/", "A/", "", "", "", "C/"]
    h = js["xlHtml"]["online"]
    assert '<span class="xl-v"><span class="g">W</span><span class="g">Y</span></span>' in h
    assert '<span class="xl-v"><span class="y">370</span></span>' in h


def test_xl_clip_long_fields(js):
    f = {f["k"]: f for ln in js["xl"]["big"] for f in ln["f"]}
    assert (f["cs"]["t"], f["cs"]["full"], f["cs"]["cut"], f["cs"]["cls"]) == ("UAE180ABC\u2026", "UAE180ABCDEF", True,
                                                                               ["g", "more"])
    assert f["tel"]["t"] == "EMIRATES 180ABCDEFGHIJKLMNO\u2026" and len(f["tel"]["t"]) == 28
    assert f["sts"]["t"] == "HOSP MEDEVAC FFR HU\u2026" and f["sts"]["full"] == "HOSP MEDEVAC FFR HUM SAR ATFMX"
    assert f["navcom"]["t"] == "SADE1E2E3FGHIJ1J3\u2026" and f["pbn"]["t"] == "A1B1C1D1L1O1S2T1" and not f["pbn"]["cut"]
    assert f["altn"]["t"] == "(EPMO EPLL)" and f["rvr"]["t"] == "75" and f["gs"]["t"] == "487"
    # trasa: bez cięcia nazw, do 7 punktów i 41 znaków, "…" osobno; w dymku wszystkie punkty
    assert f["route"]["t"] == "TOMRA LOGDA 5230N02000E ABCDE FGHIJ \u2026" and f["route"]["cls"] == ["", "more"]
    assert f["route"]["tip"] == "TOMRA LOGDA 5230N02000E ABCDE FGHIJ KLMNO PQRST UVWXY" and f["route"]["cut"]
    assert not f["type"]["cut"] and f["type"]["t"] == "B77W/H"
    h = js["xlHtml"]["big"]
    assert '<span class="xl-f cut" data-f="cs" style="--w:7" title="Callsign: UAE180ABCDEF">' in h
    assert 'title="Route: TOMRA LOGDA 5230N02000E ABCDE FGHIJ KLMNO PQRST UVWXY"' in h
    assert js["route"] == [["SOXER", "RILAB", "BIMPA"], [], ["CD", "5230N02000E", "52N020E", "KOLOM"],
                           ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"], []]
    assert js["fit"] == ["AAAAA BBBBB", "ABCDE ABCDE ABCDE ABCDE ABCDE ABCDE \u2026", "ABCDE \u2026"]
    assert js["clip"] == [[{"t": "ABCDEF", "cls": "g"}, {"t": "\u2026", "cls": "more"}], [{"t": "W", "cls": "g"}, {"t": "Y", "cls": "r"}],
                          [{"t": "AB ", "cls": ""}, {"t": "C", "cls": "y"}, {"t": "\u2026", "cls": "more"}]]
    assert js["fmt"] == {"fl3": ["370", "035", "VFR", None, None, "M082"],
                         "deg3": ["360", "360", "045", "360", "350", None, None],
                         "sh": ["+13", "-8", "0", "0", "0", None, "+1"], "pad3": ["005", "487", None]}


def test_xl_escapes(js):
    h = js["xlHtml"]["big"]
    assert "<script" not in h.lower() and '&lt;SCRIPT&gt;X&lt;/SCRIPT&gt;<span class="more">\u2026</span>' in h
    assert 'title="Remarks: &lt;SCRIPT&gt;X&lt;/SCRIPT&gt; TCAS EQUIPPED VERY LONG REMARK"' in h
    o = js["xlHtml"]["online"]
    assert "<img" not in o.lower() and 'TCAS &lt;IMG SRC=X ONE<span class="more">\u2026</span>' in o
    assert "<img" not in js["html"]["online"].lower() and "<script" not in js["fplKey"].lower()


def test_xl_key_mode(js):
    off, on = js["xlHtml"]["online"], js["xlHtml"]["key"]
    assert 'class="xl-k"' not in off and 'aria-pressed="false"' in off and '<div class="xl-body">' in off
    assert 'class="btn xl-key" aria-pressed="false"' in off and ">KEY</button>" in off
    assert 'class="btn xl-key on" aria-pressed="true"' in on and '<div class="xl-body key">' in on
    keys = re.findall(r'<span class="xl-k">([^<]*)</span>', on)
    assert len(keys) == sum(map(len, LINES)) and keys[:4] == ["CALLSIGN", "W Y", "FULL CALLSIGN", "XPDR"]
    assert {"STAR", "RWY", "NEXT FREQ", "FIR EXIT", "ORCAM", "ADDR", "IVV", "TRK"} <= set(keys)
    assert _xl(on, "cs") == "LOT3827" and _xl(on, "hdg") == "360"
    # prefile z lotniska EP (SID): nazwa pola SID
    assert [f["l"] for ln in js["xl"]["online"] for f in ln["f"] if f["k"] == "proc"] == ["STAR"]
    assert 'class="xl-body key"' in js["fplKey"] and 'class="xl-body key"' not in js["html"]["online"]


def test_xl_no_provenance_words(js):
    for name, h in js["xlHtml"].items():
        text = " ".join(re.findall(r'title="([^"]*)"', h) + re.findall(r">([^<]+)<", h))
        assert not PROVENANCE.search(text), (name, PROVENANCE.search(text).group(0))
        assert not re.search(r"<(b|i|strong)[\s>]", h), name


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
    # 0.13.1: wybrany sektor (wykresy po prawej) = wiersz z klasą sel, reszta bez zmian
    sel = js["fmpSel"]
    assert sel.count(' sel"') == 1 and '<tr class="on sel" data-tv="EP-BH">' in sel
    assert re.findall(r'<tr class="(on|off)" data-tv="([^"]+)">', sel) == trs[1:]
    assert js["info"] == "1430Z \u00b7 4 of 11 active (grey rows)"


# --- zasady plików

NEW_JS = ["flightplan.js", "xlabel.js", "fmp.js"]
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
    assert "activate(arg)" in fp and "focus," in fp and "destroy()" in fp and "export function fplHtml(d, opts = {})" in fp
    assert 'from "./strips.js"' not in fp and "removeEventListener(ONLINE_EVENT" in fp and "clearInterval" in fp
    fmp = (JS / "fmp.js").read_text("utf-8")
    assert 'export function mountFmp(pane, { start = "", onPick = () => {} } = {})' in fmp
    assert "activate(arg)" in fmp and "destroy()" in fmp
    assert "removeEventListener(ONLINE_EVENT" in fmp and "clearInterval(timer)" in fmp
    # 0.13.1: tabela z /api/viff/sectors, wykresy wybranego sektora z /api/viff/sectors/<TV>
    assert 'api("/api/viff/sectors")' in fmp and "api(`/api/viff/sectors/${encodeURIComponent(id)}`)" in fmp


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
// pamięć przeglądarki (KEY w oknie EXTENDED LABEL)
globalThis.__store = {};
globalThis.localStorage = { getItem: (k) => globalThis.__store[k] ?? null, setItem: (k, v) => { globalThis.__store[k] = String(v); } };
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
// 0.14.2: KEY w belce okna (kliknięcie gdzie indziej nic nie rysuje); stan zostaje przy odświeżeniu i w pamięci
const w0 = out.writes;
out.on.click.forEach((f) => f({ target: { closest: () => null } }));
o.otherClick = out.writes - w0;
out.on.click.forEach((f) => f({ target: { closest: (sel) => (sel === ".xl-key" ? {} : null) } }));
o.keyOn = [out.writes - w0, out.innerHTML.includes('<div class="xl-body key">'), globalThis.__store["polids.xlKey"]];
const w1 = out.writes;
timers[0]();
globalThis.__pending.shift().res(structuredClone(d));
await tick();
o.keyKept = [out.writes - w1, out.innerHTML.includes('<div class="xl-body key">')];
out.on.click.forEach((f) => f({ target: { closest: (sel) => (sel === ".xl-key" ? {} : null) } }));
o.keyOff = [out.innerHTML.includes('<div class="xl-body">'), globalThis.__store["polids.xlKey"]];
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
    (tmp_path / "flightplan.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"').replace('"./xlabel.js"', '"./xlabel.mjs"'),
                                             "utf-8")
    (tmp_path / "xlabel.mjs").write_text((JS / "xlabel.js").read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    (tmp_path / "run.mjs").write_text(FP_MOUNT_SCRIPT, "utf-8")
    r = subprocess.run([node, str(tmp_path / "run.mjs"), (tmp_path / "flightplan.mjs").as_uri()], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["focusAfterMount"] >= 1                            # kliknięcie FLIGHT PLAN: od razu można pisać
    assert o["requests"] == ["/api/vatsim/flightplan/LOT3827"] and o["shown"]
    assert o["sameWrites"] == 0
    assert o["otherClick"] == 0 and o["keyOn"] == [1, True, "1"] and o["keyKept"] == [0, True]
    assert o["keyOff"] == [True, "0"]
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
             "xlabel.js": (JS / "xlabel.js").read_text("utf-8"), "viffchart.js FMP": vc[vc.index("// --- OTHER"):]}
    for name, src in parts.items():
        bad = [line.strip() for line in src.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
        assert not bad, (name, bad)
