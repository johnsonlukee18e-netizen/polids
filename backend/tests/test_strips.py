"""Paski postępu lotu (STRIP): SID/STAR z .ese, kategoria turbulencji, przydzielony SSR, kolejność pasków;
okno lotu po kliknięciu paska (układ "Extended Label", strips.js) uruchamiane w Node."""

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from backend.app.config import ROOT_DIR
from backend.app.services.procedures import (first_fix, match_sid, match_star, parse_procedures, route_points,
                                             strip_board)
from backend.app.services.vatsim import airport_traffic, assigned_squawk, fp_wake, level_ft, pilot_info

ESE = "\n".join([
    "[SIDSSTARS]",
    "SID:EPWA:29:SOXER7G:WA901 WA902 WA903 MAKUS SOXER",
    "SID:EPWA:29:EVINA7G:WA901 WA921 EVDEX NIPUS EVINA",
    "SID:EPWA:33:SOXER5K:WA801 WA802 MAKUS SOXER",
    "SID:EPWA:29:OMNI:WA901",  # nazwa spoza wzorca: pomijamy
    "STAR:EPWA:33:BIMPA6UxRNP:BIMPA KEWLU MENCI WA529",
    "STAR:EPWA:33:BIMPA6UxILS\xb7Z:BIMPA KEWLU MENCI WA534 WA529",
    "STAR:EPWA:33:LOGDA6UxILS\xb7Z:LOGDA WA821 EMCEL WA529",
    "STAR:EPWA:33:ILS\xb7Z:WA534 WA529",  # samo podejście: pomijamy
    "STAR:EPWA:11:BIMPA7NxRNP:BIMPA KEWLU INZUB WA409",
])
PROCS = parse_procedures(ESE)


def test_parse_procedures():
    sids = PROCS["EPWA"]["sid"]
    assert [p["name"] for p in sids["29"]] == ["SOXER7G", "EVINA7G"]
    stars = PROCS["EPWA"]["star"]["33"]
    assert [p["name"] for p in stars] == ["BIMPA6U", "LOGDA6U"]
    assert stars[0]["approaches"] == ["RNP", "ILS Z"] and stars[0]["fixes"][0] == "BIMPA"


def test_route_points():
    assert route_points("N0450F370 SOXER7G SOXER/N0450F360 UL29 DCT BOKSU EPWA", ("EPWA",)) == [
        "SOXER7G", "SOXER", "UL29", "BOKSU"]
    assert first_fix("SOXER7G SOXER UL29", "EPWA") == "SOXER"
    assert first_fix("UL29 BOKSU", "EPWA") is None
    assert first_fix("ARTIP UL980 SORIX", "EPWA", last=True) == "SORIX"


def test_match_sid_by_first_fix_and_runway():
    s = match_sid("EPWA", "29", "SOXER UL29 BOKSU", PROCS)
    assert (s["name"], s["source"], s["fix"], s["runway"]) == ("SOXER7G", "fix", "SOXER", "29")
    assert match_sid("EPWA", "33", "SOXER UL29 BOKSU", PROCS)["name"] == "SOXER5K"
    # SID z trasy w wersji nieistniejącej dla pasa: bierzemy punkt z nazwy i dobieramy SID pasa w użyciu
    assert match_sid("EPWA", "29", "N0450F370 SOXER2G SOXER UL29", PROCS)["name"] == "SOXER7G"
    named = match_sid("EPWA", "29", "EVINA7G EVINA L29", PROCS)
    assert (named["name"], named["source"]) == ("EVINA7G", "route")
    assert match_sid("EPWA", "29", "OLILA L621 RILAB", PROCS) is None
    assert match_sid("EPWA", None, "SOXER UL29", PROCS) is None
    assert match_sid("EPWA", "29", "DCT", PROCS) is None and match_sid("EPWA", "29", None, PROCS) is None


def test_match_star_by_last_fix():
    s = match_star("EPWA", "33", "SOBRA Y180 RUDNO DCT BIMPA", PROCS)
    assert (s["name"], s["source"], s["fix"]) == ("BIMPA6U", "fix", "BIMPA")
    assert match_star("EPWA", "33", "ODINA L603 LOGDA LOGDA6U", PROCS)["source"] == "route"
    assert match_star("EPWA", "11", "RUDNO BIMPA", PROCS)["name"] == "BIMPA7N"
    assert match_star("EPWA", "33", "RUDNO NEPOX", PROCS) is None
    assert match_star("EPKK", "25", "RUDNO BIMPA", PROCS) is None


def test_wake_and_assigned_squawk_from_flight_plan():
    assert fp_wake("B738/M-SDE2E3FGHIRWXY/LB1") == "M"
    assert fp_wake("A388/J-SADE2E3FGHIJ3J4J5M1M2RWXYZ/LB1D1") == "J"
    assert fp_wake("c172/l-sdfgy/s") == "L"
    assert fp_wake("B738/L") is None  # format FAA: L to wyposażenie, nie turbulencja
    assert fp_wake("B738") is None and fp_wake(None) is None
    assert assigned_squawk({"assigned_transponder": "4613"}) == "4613"
    assert assigned_squawk({"assigned_transponder": "0000"}) is None
    assert assigned_squawk({"assigned_transponder": "1288"}) is None  # 8 nie jest cyfrą ósemkową
    assert assigned_squawk({}) is None and assigned_squawk(None) is None
    assert (level_ft("37000"), level_ft("FL370"), level_ft("F240"), level_ft("A045"), level_ft("350")) == (
        37000, 37000, 24000, 4500, 35000)
    assert level_ft("VFR") is None and level_ft(None) is None


def test_pilot_info_keeps_old_keys_and_adds_new():
    p = {"callsign": "LOT3827", "transponder": "2000", "latitude": 52.17, "longitude": 20.97, "groundspeed": 0,
         "flight_plan": {"aircraft_short": "B38M", "aircraft": "B38M/M-SDE2E3FGHIJ1RWXY/LB1", "departure": "EPWA",
                         "arrival": "EPGD", "route": "OLILA L621", "altitude": "22000", "flight_rules": "I",
                         "deptime": "1230", "assigned_transponder": "4613", "remarks": "/V/"}}
    info = pilot_info(p)
    for k in ("callsign", "cid", "name", "lat", "lon", "altitude", "groundspeed", "heading", "squawk", "aircraft",
              "departure", "arrival", "route", "rfl", "rules"):
        assert k in info
    assert (info["squawk"], info["assigned_squawk"], info["wake"], info["deptime"]) == ("2000", "4613", "M", "1230")


def _pilot(cs, dep, arr, route, lat=52.166, lon=20.967, gs=0, alt=360, **fp):
    return {"callsign": cs, "latitude": lat, "longitude": lon, "groundspeed": gs, "altitude": alt, "transponder": "2000",
            "flight_plan": {"aircraft_short": fp.pop("type", "A320"), "departure": dep, "arrival": arr, "route": route,
                            "altitude": "36000", "flight_rules": fp.pop("rules", "I"), **fp}}


def test_strip_board_groups_and_order():
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    feed = {"pilots": [
        _pilot("LATE", "EPWA", "EGLL", "SOXER UL29", deptime="1240"),
        _pilot("EARLY", "EPWA", "EDDF", "SOXER UL29", deptime="1210"),
        _pilot("AIRB", "EPWA", "EDDB", "DCT", gs=300, alt=12000, lat=51.9, lon=20.2),
        _pilot("CIRC", "EPWA", "EPWA", "VFR CIRCUITS", gs=85, alt=1300, rules="V", type="C172"),
        _pilot("FAR", "EDDF", "EPWA", "RUDNO BIMPA", gs=420, alt=24000, lat=52.2, lon=18.5),
        _pilot("NEAR", "EHAM", "EPWA", "ARTIP LOGDA", gs=300, alt=9000, lat=52.3, lon=20.5),
    ], "prefiles": [{"callsign": "PRE1", "flight_plan": {"aircraft_short": "E75L", "departure": "EPWA",
                                                         "arrival": "EPGD", "deptime": "1400", "route": "OLILA"}}]}
    traffic = airport_traffic(feed, "EPWA", 52.166, 20.967)
    viff = {"flights": [
        {"callsign": "LATE", "eobt": "1240", "tsat": "1205", "dep_info": "29/EVINA7G", "state": "FI"},
        {"callsign": "VONLY", "arrival": "ESSA", "eobt": "1300", "state": "SU"},
        {"callsign": "GONE", "arrival": "LOWW", "eobt": "1100", "atot": "1115", "state": "TA"},
    ]}
    runway = {"arr": "33", "dep": "29", "source": "ATIS"}
    b = strip_board("EPWA", traffic, viff, runway, {"A320": "M"}, now, PROCS)
    # LATE ma TSAT 1205 (wcześniej niż EOBT 1210 lotu EARLY), więc jest pierwszy; w powietrzu na końcu
    assert [s["callsign"] for s in b["departures"]] == ["LATE", "EARLY", "AIRB"]
    late = b["departures"][0]
    assert (late["runway"], late["runway_source"], late["proc"]["name"], late["proc"]["source"]) == (
        "29", "CDM", "EVINA7G", "CDM")
    assert late["proc"]["fixes"][-1] == "EVINA"  # punkty SID-u z CDM uzupełnione z .ese
    assert late["eobt"] == "1240" and late["eobt_source"] == "vIFF" and late["wake"] == "M"
    early = b["departures"][1]
    assert (early["proc"]["name"], early["eobt_source"], early["viff"]) == ("SOXER7G", "FPL", None)
    assert [s["callsign"] for s in b["local"]] == ["CIRC"] and b["local"][0]["proc"] is None
    assert [s["callsign"] for s in b["arrivals"]] == ["NEAR", "FAR"]
    assert b["arrivals"][0]["proc"]["name"] == "LOGDA6U" and b["arrivals"][1]["proc"]["name"] == "BIMPA6U"
    assert b["arrivals"][0]["eta"] is not None and b["arrivals"][0]["runway"] == "33"
    # planowane: prefile i lot znany tylko z vIFF; lot z ATOT bez połączenia pomijamy
    assert [(s["callsign"], s["planned"]) for s in b["planned"]] == [("VONLY", "viff"), ("PRE1", "prefile")]


def test_strip_board_ground_far_from_airport_goes_last():
    """Na ziemi daleko od lotniska: przylot jeszcze na lotnisku odlotu, odlot już po przylocie (plan bez zmian)."""
    now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    feed = {"pilots": [
        _pilot("GATE", "EPWA", "EDDF", "SOXER UL29", deptime="1210"),
        _pilot("LANDED", "EPWA", "EGLL", "SOXER UL29", deptime="0900", lat=51.47, lon=-0.45),
        _pilot("AIRB", "EPWA", "EDDB", "DCT", gs=300, alt=12000, lat=51.9, lon=20.2),
        _pilot("ATADEP", "EDDF", "EPWA", "RUDNO BIMPA", lat=50.03, lon=8.57),
        _pilot("TAXIIN", "EHAM", "EPWA", "ARTIP LOGDA", gs=15),
        _pilot("INBOUND", "EHAM", "EPWA", "ARTIP LOGDA", gs=300, alt=9000, lat=52.3, lon=20.5),
    ], "prefiles": []}
    traffic = airport_traffic(feed, "EPWA", 52.166, 20.967)
    b = strip_board("EPWA", traffic, None, {"arr": "33", "dep": "29", "source": "ATIS"}, {}, now, PROCS)
    assert [(s["callsign"], s["away"]) for s in b["departures"]] == [("GATE", False), ("AIRB", False), ("LANDED", True)]
    assert [(s["callsign"], s["away"]) for s in b["arrivals"]] == [("TAXIIN", False), ("INBOUND", False), ("ATADEP", True)]
    assert b["arrivals"][2]["eta"] is None and b["arrivals"][2]["dist_nm"] > 300


# --- 0.12.5: okno lotu po kliknięciu paska (układ "Extended Label"), angielskie napisy, ostre krawędzie ---------------

STRIPS_JS = ROOT_DIR / "frontend" / "js" / "strips.js"
STRIP_TAB_JS = ROOT_DIR / "frontend" / "js" / "tabs" / "strip.js"
STRIPS_CSS = ROOT_DIR / "frontend" / "css" / "strips.css"
PL = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")

NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const d = { icao: "EPWA", atis: { letter: "K" }, network_error: null, states: {} };
const dep = { kind: "dep", callsign: "LOT3827", telephony: "LOT 3827", aircraft: "B38M", wake: "M", rules: "I",
  aircraft_icao: "B38M/M-SDE2E3FGHIJ1RWXY/LB1", departure: "EPWA", arrival: "EPGD", alternate: "EPKK", rfl_ft: 22000,
  state: "ground", altitude: 362, groundspeed: 0, heading: 290, squawk: "2000", assigned_squawk: "4613", runway: "29",
  runway_source: "CDM", route: "N0450F220 OLILA6G OLILA L621 BOKSU DCT GRUDA",
  remarks: "PBN/A1B1C1D1L1O1S1S2 DOF/261018 REG/SPLVA STS/HOSP RVR/200 RMK/TCAS SIMBRIEF EXTRA TEXT /V/",
  proc: { name: "OLILA6G", fixes: ["WA901", "OLILA"], approaches: [] }, viff: null };
const arr = { kind: "arr", callsign: "DLH1612", telephony: null, aircraft: "A20N", wake: "M", rules: "I",
  aircraft_icao: "A20N/M-SDE3FGHIJ1RY/H", departure: "EDDF", arrival: "EPWA", rfl_ft: 37000, state: "air", altitude: 11000,
  groundspeed: 330, heading: 87, squawk: "4615", assigned_squawk: "4615", runway: "33", proc: { name: "BIMPA6U", fixes: [] },
  route: "ANEKI Y163 NATOR UN850 TOSTU DCT ERNAS T720 SUI DCT KOPAG DCT 5230N02000E DCT BIMPA BIMPA6U", remarks: "/v/ NEW PILOT" };
const loc = { kind: "local", callsign: "SPKAT", aircraft: "C172", wake: "L", rules: "V", aircraft_icao: "C172",
  departure: "EPWA", arrival: "EPWA", state: "air", altitude: 1300, groundspeed: 85, heading: 120, squawk: "6201",
  route: "VFR CIRCUITS", remarks: "STS/NONRVSM" };
const pln = { kind: "dep", planned: "viff", callsign: "SAS1748", departure: "EPWA", arrival: "ESSA", state: "offline",
  squawk: null, groundspeed: null, viff: { state: "SU", suspension: "FLS-NRA" } };
const out = {};
const flat = (lines) => Object.fromEntries(lines.flatMap((ln) => ln.f.map((f) => [f.k, { ...f, line: ln.line,
  t: f.parts ? f.parts.map((p) => p.t).join("") : null, cls: f.parts ? f.parts.map((p) => p.cls).join(",") : null }])));
out.dep = flat(m.extLabel(dep, d, { vv: 0 }));
out.arr = flat(m.extLabel(arr, d, { vv: -840 }));
out.loc = flat(m.extLabel(loc, d, { vv: 1260 }));
out.pln = flat(m.extLabel(pln, d));
out.lines = m.extLabel(dep, d).map((ln) => ({ keys: ln.f.map((f) => f.k), gap: ln.gap, indent: ln.indent }));
out.width = m.XL_WIDTH;
out.eq = ["B738/M-SDE2E3FGHIJ1RWXY/LB1D1", "C172/L-G/C", "A320", "H/B738/L", "", null].map((v) => m.equipment(v));
out.f18 = ["PBN/A1B1C1D1L1O1S1 DOF/261018 REG/SPLVA EET/EPWW0010 RMK/TCAS SIMBRIEF /V/", "/v/ NEW PILOT",
  "STS/HOSP MEDEVAC RMK/MEDICAL FLIGHT", "", null].map((v) => m.field18(v));
out.pts = {
  dep: m.routePoints({ kind: "dep", departure: "EPWA", arrival: "EGLL",
    route: "N0450F350 SOXER3G SOXER DCT ABUDA L621 LOGDA/N0440F360 UL613 MOBRU DCT 5230N02000E DCT EGLL" }),
  long: m.routePoints({ kind: "dep", route: "AAA BBB CCC DDD EEE FFF GGG HHH III" }),
  arr: m.routePoints({ kind: "arr", route: "AAA BBB CCC DDD EEE FFF GGG HHH III" }),
};
// długie pola planu: UAE180 z przeglądu (NAV/COM 26 znaków + PBN) i lot ze skrajnymi wartościami w każdym polu
const uae = { kind: "dep", callsign: "UAE180", aircraft: "A388", wake: "J", rules: "I", departure: "EPWA", arrival: "OMDB",
  aircraft_icao: "A388/J-SADE2E3FGHIJ3J4J5M1M2RWXYZ/LB1D1", rfl_ft: 39000, state: "ground", groundspeed: 0, squawk: "2000",
  route: "N0490F390 SOXER7G SOXER DCT ABUDA L621 LOGDA", remarks: "PBN/A1B1C1D1L1O1S2 DOF/261018 RMK/TCAS" };
const big = { kind: "dep", callsign: "UAE180XYZW1", telephony: "EMIRATES ONE EIGHT ZERO HEAVY EXTRA", aircraft: "A388",
  wake: "J", rules: "I", aircraft_icao: "A388/J-SADE2E3FGHIJ3J4J5M1M2RWXYZ/LB1B2D1G1U1U2V1V2", departure: "EPWA",
  arrival: "OMDB", alternate: "OMAA", rfl_ft: 39000, state: "air", altitude: 23000, groundspeed: 1015, heading: 145,
  squawk: "2000", assigned_squawk: "4621", runway: "29", proc: { name: "SOXER7GLONG" },
  route: "5230N02000E 5200N02100E 5130N02200E 5100N02300E 5030N02400E 5000N02500E 4930N02600E",
  remarks: "PBN/A1B1C1D1L1O1S2T1T2 STS/HOSP MEDEVAC STATE ATFMX ALTN/OMAL RVR/1200750 RMK/TCAS EQUIPPED SIMBRIEF LONG REMARK TEXT" };
out.uae = flat(m.extLabel(uae, d));
out.big = flat(m.extLabel(big, d, { vv: -60000 }));
out.bigArr = flat(m.extLabel({ ...big, kind: "arr" }, d));
out.html = [false, true].map((key) => m.winHtml(big, d, "strip note", { vv: -60000, xf: "navcom" }, key));
// nic nieskrócone: zostaje opis pola paska
out.htmlNote = m.winHtml(loc, d, "strip note", { xf: "navcom" });
out.htmlAll = [dep, arr, loc, pln, uae, big].flatMap((s) => [false, true].map((key) => m.winHtml(s, d, "", { vv: 1260 }, key)));
out.spec = m.XL_LINES.map((ln) => ({ indent: ln.indent || 0, f: ln.f.map((f) => ({ k: f.k, w: f.w, max: f.max || f.w,
  l: typeof f.l === "function" ? f.l({ kind: "dep" }) : f.l })) }));
out.clip = [
  m.clip([{ t: "ABCDEFGH", cls: "g" }], 5), m.clip([{ t: "W", cls: "g" }, { t: "Y", cls: "r" }], 2),
  m.clip([{ t: "AB ", cls: "" }, { t: "CD", cls: "y" }], 4), m.clip([{ t: "AB", cls: "" }], 1),
];
const ll = ["5230N02000E", "5200N02100E", "5130N02200E", "5100N02300E", "5030N02400E", "5000N02500E", "4930N02600E"];
out.fit = [m.fitPoints(["SOXER", "ABUDA"], 41), m.fitPoints(ll, 41), m.fitPoints(ll, 41, true),
  m.fitPoints(["AAAAA", "BBBBB", "CCCCC", "DDDDD", "EEEEE", "FFFFF", "GGGGG"], 41)];
// trasy VFR / lotów lokalnych: słowa i pasy nie są punktami, prawdziwe punkty (też NDB 2-literowe) zostają
const vfr = (route, kind = "local") => m.routePoints({ kind, departure: "EPWA", arrival: "EPWA", route });
out.vfr = [vfr("VFR CIRCUITS RWY 29"), vfr("VFR CIRCUITS"), vfr("LOCAL TRAINING OVER CITY AREA STAY IN CTR HOLD AT WAR"),
  vfr("VFR EPWA RWY29 SOXER BACK TO EPWA"), vfr("N0100VFR WAR R29 29L RW11 RWY11 OKC"), vfr("AY NO OR NE NW"),
  vfr("TOUCH AND GO LOW PASS RWY 33 FULL STOP", "dep")];

// atrapa DOM do focusSpot / restoreFocus: element = klasy, data-*, rodzic; root szuka po "A B.c" (potomek z klasami)
const board = (keys, cut, open = true) => {
  const all = [];
  const match = (e, part) => part.split(".").filter(Boolean).every((c) => e.classList.contains(c));
  const mk = (cls, ds, parent) => {
    const set = new Set(cls.split(" "));
    const e = { cls, dataset: ds || {}, parent, focused: null, classList: { contains: (c) => set.has(c) },
      closest: (q) => { for (let x = e; x; x = x.parent) if (match(x, q)) return x; return null; },
      focus: (o) => { e.focused = o; } };
    all.push(e);
    return e;
  };
  const root = mk("strips", {}, null);
  const list = mk("sx-list", {}, root);
  keys.forEach((k) => mk("strip dep", { k }, list));
  const win = mk("sx-win", {}, root);
  // okno zamknięte = puste .sx-win
  if (open) {
    mk("xw-key", {}, win);
    mk("xw-x", {}, win);
    const body = mk("xw-body", {}, win);
    ["navcom", "surv", "pbn"].forEach((f) => mk(cut.includes(f) ? "xw-f cut" : "xw-f", { f }, body));
  }
  const sel = (q) => all.filter((e) => {
    const p = q.split(" ");
    return match(e, p[p.length - 1]) && (p.length === 1 || !!e.parent?.closest(p[0]));
  });
  root.contains = (x) => { for (let e = x; e; e = e.parent) if (e === root) return true; return false; };
  root.querySelectorAll = sel;
  root.querySelector = (q) => sel(q)[0] || null;
  return { root, q: (q) => root.querySelector(q), strip: (k) => sel(".strip").find((e) => e.dataset.k === k), all };
};
const b1 = board(["dep:LOT3827", "arr:DLH1612"], ["navcom"]);
const away = board(["dep:X"], []);
const spots = {
  strip: m.focusSpot(b1.strip("arr:DLH1612"), b1.root), x: m.focusSpot(b1.q(".sx-win .xw-x"), b1.root),
  key: m.focusSpot(b1.q(".sx-win .xw-key"), b1.root), field: m.focusSpot(b1.q(".sx-win .xw-f.cut"), b1.root),
  body: m.focusSpot(b1.q(".sx-win .xw-body"), b1.root), list: m.focusSpot(b1.q(".sx-list"), b1.root),
  root: m.focusSpot(b1.root, b1.root), outside: m.focusSpot(away.strip("dep:X"), b1.root), none: m.focusSpot(null, b1.root),
};
// po odświeżeniu: nowe elementy (b2 ma navcom skrócone, b3 już nie, b4 bez okna i bez paska DLH1612)
const b2 = board(["arr:DLH1612", "dep:LOT3827"], ["navcom"]);
const b3 = board(["dep:LOT3827", "arr:DLH1612"], []);
const b4 = board(["dep:LOT3827"], [], false);
const desc = (e, b) => (e ? { cls: e.cls, k: e.dataset.k || e.dataset.f || null, opts: e.focused, fresh: b.all.includes(e) } : null);
out.focus = { spots, restored: {
  strip: desc(m.restoreFocus(spots.strip, b2.root), b2), x: desc(m.restoreFocus(spots.x, b2.root), b2),
  key: desc(m.restoreFocus(spots.key, b2.root), b2), field: desc(m.restoreFocus(spots.field, b2.root), b2),
  fieldGone: desc(m.restoreFocus(spots.field, b3.root), b3), stripGone: desc(m.restoreFocus(spots.strip, b4.root), b4),
  winGone: desc(m.restoreFocus(spots.x, b4.root), b4), none: m.restoreFocus(null, b2.root),
} };
// pasek 1000..1046 px, okno 432 x 400, ekran 1600 x 900
out.place = {
  below: m.placeWin({ x: 600, top: 200, bottom: 246 }, 432, 400, 1600, 900),
  above: m.placeWin({ x: 600, top: 700, bottom: 746 }, 432, 400, 1600, 900),
  right: m.placeWin({ x: 1500, top: 200, bottom: 246 }, 432, 400, 1600, 900),
  left: m.placeWin({ x: -40, top: 200, bottom: 246 }, 432, 400, 1600, 900),
  tall: m.placeWin({ x: 600, top: 300, bottom: 346 }, 432, 700, 1600, 768),
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def xl(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("strips")
    (d / "api.mjs").write_text('export const api = async () => ({});\n'
                               'export const esc = (s) => String(s ?? "");\n', "utf-8")
    (d / "strips.mjs").write_text(STRIPS_JS.read_text("utf-8").replace('"./api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "strips.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_extended_label_lines_follow_sdd(xl):
    # SDD 2014 Figure 2-6 / Table 2-13: osiem wierszy, odstęp nad wierszem 3 i nad danymi Mode S, wcięcie wiersza 2
    assert [ln["keys"] for ln in xl["lines"]] == [
        ["cs", "wy", "tel", "xpdr"], ["type", "sts", "orcam"], ["adep", "ades", "altn", "proc", "rwy", "nfq"],
        ["rules", "route", "xfl"], ["cfl", "rfl", "free", "rvr"], ["navcom", "surv", "pbn"],
        ["addr", "sel", "hdg", "ias", "mach", "tas"], ["gs", "vv"]]
    assert [ln["gap"] for ln in xl["lines"]] == [False, False, True, False, False, False, True, False]
    assert xl["lines"][1]["indent"] == 3 and xl["width"] >= 44


def test_extended_label_values_departure(xl):
    f = xl["dep"]
    assert (f["cs"]["t"], f["cs"]["cls"]) == ("LOT3827", "g")
    assert (f["wy"]["t"], f["wy"]["cls"]) == ("WY", "g,g")             # W i Y w NAV/COM: RVSM i 8.33
    assert (f["tel"]["t"], f["xpdr"]["t"]) == ("LOT 3827", "S/2000")  # L w dozorowaniu = Mode S, kod nadawany
    assert (f["orcam"]["t"], f["orcam"]["cls"]) == ("4613", "y")         # przydzielony inny niż nadawany
    assert (f["type"]["t"], f["sts"]["t"]) == ("B38M/M", "HOSP")
    assert (f["adep"]["t"], f["ades"]["t"], f["altn"]["t"], f["proc"]["l"], f["proc"]["t"], f["rwy"]["t"]) == (
        "EPWA", "EPGD", "(EPKK)", "SID", "OLILA6G", "RWY29")
    assert (f["rules"]["t"], f["rules"]["cls"], f["route"]["t"]) == ("I", "y", "OLILA BOKSU GRUDA")
    assert (f["cfl"]["t"], f["rfl"]["t"], f["rfl"]["cls"]) == (None, "220", "y")
    # tekst RMK najwyżej 20 znaków: skrócony z "…", pełny w "full"
    assert (f["free"]["t"], f["free"]["full"], f["rvr"]["t"]) == ("TCAS SIMBRIEF EXTRA…", "TCAS SIMBRIEF EXTRA TEXT", "200")
    # NEXT FREQ i FIR EXIT: VATSIM nie zna następnego sektora ani skoordynowanego poziomu wyjścia, puste jak CFL
    assert (f["nfq"]["t"], f["nfq"]["w"], f["nfq"]["line"], f["xfl"]["t"], f["xfl"]["w"], f["xfl"]["line"]) == (
        None, 7, 3, None, 4, 4)
    assert f["xfl"]["right"] and f["nfq"]["l"] == "NEXT FREQ" and f["xfl"]["l"] == "FIR EXIT"
    assert (f["navcom"]["t"], f["surv"]["t"], f["pbn"]["t"]) == ("SDE2E3FGHIJ1RWXY", "LB1", "A1B1C1D1L1O1S1S2")
    # na ziemi: bez HDG; GS i VV z sieci
    assert (f["hdg"]["t"], f["gs"]["t"], f["vv"]["t"]) == (None, "000", "0")
    assert all(f[k]["t"] is None for k in ("addr", "sel", "ias", "mach", "tas"))


def test_extended_label_values_other_kinds(xl):
    a, loc, pln = xl["arr"], xl["loc"], xl["pln"]
    assert a["orcam"]["t"] is None and a["tel"]["t"] is None and a["xpdr"]["t"] == "S/4615"   # H = Mode S
    assert (a["proc"]["l"], a["rfl"]["t"], a["free"]["t"], a["hdg"]["t"], a["vv"]["t"]) == ("STAR", "370", "NEW PILOT", "087", "-8")
    # przylot: 7 ostatnich punktów; z punktem współrzędnych nie mieszczą się w 41 znakach, więc pierwszy odpada z "…"
    assert a["route"]["full"] == "NATOR TOSTU ERNAS SUI KOPAG 5230N02000E BIMPA"
    assert a["route"]["t"] == "… TOSTU ERNAS SUI KOPAG 5230N02000E BIMPA" and len(a["route"]["t"]) <= 41
    # VFR bez wyposażenia w planie: W żółte (STS/NONRVSM), Y czerwone, transponder bez typu
    assert (loc["wy"]["cls"], loc["xpdr"]["t"], loc["type"]["t"], loc["vv"]["t"]) == ("y,r", "6201", "C172/L", "+13")
    assert loc["route"]["t"] is None and loc["altn"]["t"] is None        # "VFR CIRCUITS": brak punktów znaczących
    assert xl["dep"]["route"]["full"] is None                            # trasa zmieściła się w całości
    # lot planowany (vIFF, pilot niepołączony): bez transpondera i danych Mode S
    assert all(pln[k]["t"] is None for k in ("xpdr", "orcam", "hdg", "gs", "vv", "tel", "type"))
    assert (pln["cs"]["t"], pln["adep"]["t"], pln["ades"]["t"]) == ("SAS1748", "EPWA", "ESSA")


def test_extended_label_flight_plan_parsers(xl):
    eq = xl["eq"]
    assert eq[0] == {"type": "B738", "wake": "M", "navcom": "SDE2E3FGHIJ1RWXY", "surv": "LB1D1"}
    assert eq[1] == {"type": "C172", "wake": "L", "navcom": "G", "surv": "C"}
    assert eq[2] == {"type": "A320", "wake": None, "navcom": None, "surv": None}
    assert all(e == {"type": None, "wake": None, "navcom": None, "surv": None} for e in eq[3:])
    f = xl["f18"]
    assert (f[0]["PBN"], f[0]["REG"], f[0]["RMK"], f[0]["EET"]) == ("A1B1C1D1L1O1S1", "SPLVA", "TCAS SIMBRIEF", "EPWW0010")
    assert f[1] == {"RMK": "NEW PILOT"} and f[2] == {"STS": "HOSP MEDEVAC", "RMK": "MEDICAL FLIGHT"} and f[3] == {} == f[4]
    p = xl["pts"]
    assert p["dep"] == ["SOXER", "ABUDA", "LOGDA", "MOBRU", "5230N02000E"]
    assert p["long"] == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"] and p["arr"] == ["CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III"]


LN_RE = re.compile(r'<div class="xw-ln[^"]*"(?: style="padding-left:(\d+)ch")?>(.*?)</div>', re.S)
F_RE = re.compile(r'<span class="xw-f([^"]*)" data-f="(\w+)" style="min-width:(\d+)ch"([^>]*)>(?:<i>([^<]*)</i>)?<b>(.*?)</b></span>',
                  re.S)
KEY_CH = 0.7   # nazwa pola w KEY: 9 px przy 14 px wartości (0,64 znaku) plus odstęp liter


def _line_chars(html, key):
    """Szerokość każdego wiersza okna w znakach (14 px): wcięcie, pola (min-width, wartość, nazwa w KEY), odstępy 1ch."""
    out = []
    for indent, body in LN_RE.findall(html):
        fields = F_RE.findall(body)
        assert fields, body
        width = int(indent or 0) + len(fields) - 1
        for _cls, _k, minw, _attrs, label, val in fields:
            text = re.sub(r"<[^>]+>", "", val)
            width += max(int(minw), len(text), -(-len(label) * 7 // 10) if key else 0)
        out.append(width)
    return out


def test_extended_label_lines_fit_window(xl):
    # każdy wiersz w XL_WIDTH dla każdej wartości: limity pól (Table 2-13) + odstępy, także z nazwami pól (KEY)
    for ln in xl["spec"]:
        chars = ln["indent"] + len(ln["f"]) - 1 + sum(max(f["max"], -(-len(f["l"]) * 7 // 10)) for f in ln["f"])
        assert chars <= xl["width"], (ln, chars)
    w = {f["k"]: (f["w"], f["max"]) for ln in xl["spec"] for f in ln["f"]}
    # szerokości z SDD 2014 Table 2-13
    assert (w["cs"], w["tel"], w["xpdr"], w["type"], w["sts"], w["orcam"]) == ((7, 10), (28, 28), (6, 6), (6, 6), (20, 20), (4, 4))
    assert (w["adep"], w["ades"], w["altn"], w["proc"], w["rwy"], w["nfq"]) == ((4, 4), (4, 4), (11, 11), (7, 7), (6, 6), (7, 7))
    assert (w["route"], w["xfl"], w["cfl"], w["rfl"], w["free"], w["rvr"]) == ((41, 41), (4, 4), (3, 3), (3, 3), (20, 20), (6, 6))
    assert (w["navcom"], w["surv"], w["pbn"]) == ((18, 18), (15, 15), (16, 16))
    # Mode S: adres 6, SEL 3, IAS / TAS 0..1023 i Mach "0,99" po 4 znaki, GS 0..1023 i VV ze znakiem po 4
    assert (w["addr"], w["sel"], w["ias"], w["mach"], w["tas"], w["gs"], w["vv"]) == (
        (6, 6), (3, 3), (4, 4), (4, 4), (4, 4), (4, 4), (4, 4))
    # wyrenderowane okna (6 lotów, z KEY i bez): 8 wierszy, żaden szerszy niż XL_WIDTH, żadna wartość ponad limit pola
    assert len(xl["htmlAll"]) == 12
    for i, html in enumerate(xl["htmlAll"]):
        chars = _line_chars(html, key=i % 2 == 1)
        assert len(chars) == 8 and max(chars) <= xl["width"], (i, chars)
        for _cls, k, _minw, _attrs, _label, val in F_RE.findall(html):
            assert len(re.sub(r"<[^>]+>", "", val)) <= w[k][1], (i, k, val)


def test_extended_label_long_flight_plan_fields(xl):
    # UAE180 z przeglądu: NAV/COM 26 znaków skrócone do 18, PBN widoczne w całości
    u = xl["uae"]
    assert (u["navcom"]["t"], u["navcom"]["full"]) == ("SADE2E3FGHIJ3J4J5…", "SADE2E3FGHIJ3J4J5M1M2RWXYZ")
    assert u["navcom"]["cls"].endswith("more") and len(u["navcom"]["t"]) == 18
    assert (u["surv"]["t"], u["surv"]["full"], u["pbn"]["t"], u["pbn"]["full"]) == ("LB1D1", None, "A1B1C1D1L1O1S2", None)
    assert u["wy"]["t"] == "WY" and u["wy"]["cls"] == "g,g"     # W i Y liczone z pełnego NAV/COM
    # skrajne wartości: każde pole w swoim limicie, pełna wartość w "full"
    b = xl["big"]
    expect = {
        "cs": ("UAE180XYZ…", "UAE180XYZW1"), "tel": ("EMIRATES ONE EIGHT ZERO HEA…", "EMIRATES ONE EIGHT ZERO HEAVY EXTRA"),
        "sts": ("HOSP MEDEVAC STATE…", "HOSP MEDEVAC STATE ATFMX"), "proc": ("SOXER7…", "SOXER7GLONG"),
        "navcom": ("SADE2E3FGHIJ3J4J5…", "SADE2E3FGHIJ3J4J5M1M2RWXYZ"), "surv": ("LB1B2D1G1U1U2V…", "LB1B2D1G1U1U2V1V2"),
        "pbn": ("A1B1C1D1L1O1S2T…", "A1B1C1D1L1O1S2T1T2"), "free": ("TCAS EQUIPPED SIMBR…", "TCAS EQUIPPED SIMBRIEF LONG REMARK TEXT"),
        "rvr": ("12007…", "1200750"),
        "route": ("5230N02000E 5200N02100E 5130N02200E …",
                  "5230N02000E 5200N02100E 5130N02200E 5100N02300E 5030N02400E 5000N02500E 4930N02600E"),
    }
    for k, (t, full) in expect.items():
        assert (b[k]["t"], b[k]["full"]) == (t, full), k
        assert len(b[k]["t"]) <= b[k]["max"], k
    assert xl["bigArr"]["route"]["t"] == "… 5030N02400E 5000N02500E 4930N02600E"   # przylot: ostatnie punkty
    assert (b["altn"]["t"], b["altn"]["full"], b["gs"]["t"], b["vv"]["t"], b["type"]["t"]) == ("(OMAA OMAL)", None, "1015", "-600", "A388/J")
    assert all(b[k]["full"] is None for k in ("adep", "ades", "rwy", "xpdr", "orcam", "hdg", "gs", "vv", "rfl"))
    # okno: skrócone pola z pełną wartością w title i fokusem; xf = pole z pełną wartością pod oknem zamiast opisu paska
    for html in xl["html"]:
        assert 'class="xw-f cut" data-f="navcom" style="min-width:18ch" title="NAV/COM: SADE2E3FGHIJ3J4J5M1M2RWXYZ" tabindex="0" role="button"' in html
        assert '<div class="xw-note full"><i>NAV/COM</i><span>SADE2E3FGHIJ3J4J5M1M2RWXYZ</span></div>' in html
        assert "strip note" not in html and "Click a field ending in … for its full value." in html
        assert 'data-f="adep" style="min-width:4ch">' in html     # pole nieskrócone: bez title i tabindex
        assert html.count('tabindex="0"') == sum(1 for k in b if b[k]["full"] is not None)
    assert '<div class="xw-note"><i>FIELD</i><span>strip note</span></div>' in xl["htmlNote"]
    assert "Click a field ending in" not in xl["htmlNote"]


def test_extended_label_clip_and_fit_helpers(xl):
    c = xl["clip"]
    assert c[0] == [{"t": "ABCD", "cls": "g"}, {"t": "…", "cls": "more"}]
    assert c[1] == [{"t": "W", "cls": "g"}, {"t": "Y", "cls": "r"}]          # mieści się: bez zmian
    assert c[2] == [{"t": "AB", "cls": ""}, {"t": "…", "cls": "more"}]       # bez spacji przed "…"
    assert c[3] == [{"t": "…", "cls": "more"}]
    f = xl["fit"]
    assert f[0] == "SOXER ABUDA"
    assert f[1] == "5230N02000E 5200N02100E 5130N02200E …" and f[2] == "… 5030N02400E 5000N02500E 4930N02600E"
    assert f[3] == "AAAAA BBBBB CCCCC DDDDD EEEEE FFFFF GGGGG" and len(f[3]) == 41   # 7 punktów 5-literowych = 41 znaków


def test_route_points_skip_vfr_words_and_runways(xl):
    v = xl["vfr"]
    assert v[0] == [] and v[1] == []                                   # "VFR CIRCUITS RWY 29" nie daje "RWY"
    assert v[2] == ["WAR"]                                             # słowa opisowe odpadają, VOR WAR zostaje
    assert v[3] == ["SOXER"]                                           # pas RWY29 i ADEP/ADES odpadają
    assert v[4] == ["WAR", "OKC"]                                      # R29, 29L, RW11, RWY11: pasy, nie punkty
    assert v[5] == ["AY", "NO", "OR", "NE", "NW"]                      # polskie NDB 2-literowe zostają
    assert v[6] == []


def test_strip_focus_survives_refresh(xl):
    sp, r = xl["focus"]["spots"], xl["focus"]["restored"]
    assert sp["strip"] == {"strip": "arr:DLH1612"} and sp["x"] == {"btn": "xw-x"} and sp["key"] == {"btn": "xw-key"}
    assert sp["field"] == {"field": "navcom"}
    # fokus poza STRIP albo na elemencie bez fokusu: nic nie zapamiętujemy, odświeżenie go nie rusza
    assert all(sp[k] is None for k in ("body", "list", "root", "outside", "none"))
    # po przerysowaniu: nowy element w tym samym miejscu, focus({ preventScroll: true })
    assert r["strip"] == {"cls": "strip dep", "k": "arr:DLH1612", "opts": {"preventScroll": True}, "fresh": True}
    assert r["x"] == {"cls": "xw-x", "k": None, "opts": {"preventScroll": True}, "fresh": True}
    assert r["key"]["cls"] == "xw-key" and r["field"] == {"cls": "xw-f cut", "k": "navcom", "opts": {"preventScroll": True},
                                                         "fresh": True}
    assert r["fieldGone"]["cls"] == "xw-x"                          # pole już nieskrócone: fokus na ×
    assert r["stripGone"] is None and r["winGone"] is None and r["none"] is None


def test_extended_label_window_stays_in_viewport(xl):
    p = xl["place"]
    assert p["below"] == {"left": 600, "top": 249}            # pod paskiem, od miejsca kliknięcia
    assert p["above"] == {"left": 600, "top": 297}            # brak miejsca pod paskiem: nad nim
    assert p["right"] == {"left": 1600 - 432 - 6, "top": 249}
    assert p["left"]["left"] == 6
    assert p["tall"]["top"] == 768 - 700 - 6 and p["tall"]["top"] >= 6


def test_radio_callsign_from_airline_telephony():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.database import Base
    from backend.app.models import Callsign
    from backend.app.routers.aerodromes import _radio_callsigns

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        db.add_all([Callsign(icao="LOT", name="LOT - POLSKIE LINIE LOTNICZE", telephony="lot "),
                    Callsign(icao="XXX", name="No telephony", telephony="")])
        db.commit()
        board = {"departures": [{"callsign": "LOT3PC"}, {"callsign": "SPKAT"}], "arrivals": [{"callsign": "XXX123"}],
                 "local": [], "planned": [{"callsign": "LOT1"}]}
        _radio_callsigns(db, board)
    assert [s["telephony"] for s in board["departures"] + board["arrivals"] + board["planned"]] == [
        "LOT 3PC", None, None, "LOT 1"]


def _code(src):
    """Kod bez komentarzy (komentarze w projekcie są po polsku)."""
    out = []
    for line in src.splitlines():
        s = line.strip()
        if s.startswith(("//", "/*", "*")):
            continue
        out.append(re.split(r"\s//\s", line)[0])
    return "\n".join(out)


def test_strips_click_window_not_hover_and_english():
    js = STRIPS_JS.read_text("utf-8")
    # 0.12.5: najechanie na pasek niczego nie otwiera; kliknięcie otwiera okno, Esc / × / klik obok zamyka
    assert "mousemove" not in js and "sx-tip" not in js and "mouseleave" not in js
    assert 'root.addEventListener("click"' in js and 'e.key === "Escape"' in js and 'class="xw-x"' in js
    # klawiatura: pasek ma fokus i otwiera okno Enterem / spacją; notatka pola po stałym kluczu data-f, nie po indeksie
    assert 'tabindex="0" role="button"' in js and 'e.key !== "Enter"' in js and "EXTENDED LABEL WINDOW" in js
    tags = re.findall(r"<[^<>]*data-h=[^<>]*>", js)
    assert len(tags) == js.count("data-h=") and all('data-f="' in t for t in tags), [t for t in tags if 'data-f="' not in t]
    assert 'querySelectorAll("[data-h]")[' not in js
    assert 'document.addEventListener("click", onDocClick)' in js and 'document.removeEventListener("click", onDocClick)' in js
    assert "if (open) drawWin();" in js   # odświeżenie: nowe dane w oknie albo zamknięcie, gdy lotu już nie ma
    # odświeżenie co 30 s: fokus (pasek, przycisk okna, skrócone pole) wraca po przerysowaniu; okno bez zmian zostaje
    render = js[js.index("const render = () => {"):js.index("const refresh = async")]
    assert render.index("focusSpot(document.activeElement, root)") < render.index('.innerHTML = bar(d)')
    assert render.index("if (open) drawWin();") < render.index("restoreFocus(spot, root)")
    assert "html !== drawn" in js and "const REFRESH_MS = 30000;" in js
    for src in (js, STRIP_TAB_JS.read_text("utf-8")):
        assert not PL.search(_code(src)), PL.findall(_code(src))
    for word in ("Odloty", "Przyloty", "Planowane", "Lokalne", "KOŁUJE", "POSTÓJ", "W POW.", "NA ZIEMI", "najedź", "Aktualizacja"):
        assert word not in _code(js) and word not in _code(STRIP_TAB_JS.read_text("utf-8")), word
    for word in ("Departures", "Arrivals", "Planned", "Local", "TAXIING", "PARKED", "AIRBORNE", "ON GROUND", "Updated"):
        assert word in js + STRIP_TAB_JS.read_text("utf-8"), word


def test_strips_css_sharp_edges():
    css = re.sub(r"/\*.*?\*/", "", STRIPS_CSS.read_text("utf-8"), flags=re.S)
    radii = re.findall(r"border-radius:\s*([^;}]+)", css)
    assert radii and all(r.strip() in ("0", "50%") for r in radii), radii
    assert "text-shadow" not in css and "box-shadow" not in css


def test_strips_no_provenance_text():
    """Issue #21: opisy pól paska i belki bez dopisków, skąd pochodzi wartość (vIFF, VATSIM, plik .ese, EuroScope,
    baza typów, plan lotu VATSIM, IFPS); same dane, czasy i stany zostają."""
    for src in (STRIPS_JS.read_text("utf-8"), STRIP_TAB_JS.read_text("utf-8")):
        code = _code(src)
        for word in ("vIFF", "VATSIM", ".ese", "EuroScope", "type database", "IFPS)", "deptime", "from the network",
                     "Flight not in", "not in VATSIM"):
            assert word not in code, word
    js = STRIPS_JS.read_text("utf-8")
    for txt in ("ATOT: actual take-off time.", "CTOT: ATFM slot", "TTOT: target take-off time (A-CDM), no slot.",
                "CFL field: RFL (requested flight level).", "click: flight details · double-click: map · CFL = RFL<"):
        assert txt in js, txt
