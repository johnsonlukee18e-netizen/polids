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
const dep = { kind: "dep", callsign: "LOT3827", aircraft: "B38M", wake: "M", rules: "I", registration: "SPLVA",
  departure: "EPWA", arrival: "EPGD", rfl_ft: 22000, state: "ground", altitude: 362, groundspeed: 0, squawk: "2000",
  assigned_squawk: "4613", runway: "29", runway_source: "CDM", eobt: "1023", eobt_source: "vIFF", route: "OLILA L621",
  remarks: "/V/", proc: { name: "OLILA6G", fixes: ["WA901", "OLILA"], approaches: [] },
  viff: { state: "SI", ctot: "1043", delay: 20, regulation: "EPWA29A", tobt: "1025", tsat: "1025", ttot: "1039" } };
const arr = { kind: "arr", callsign: "DLH1612", aircraft: "A20N", wake: "M", rules: "I", departure: "EDDF", arrival: "EPWA",
  rfl_ft: 37000, state: "air", altitude: 11000, groundspeed: 330, dist_nm: 38, eta: "1018", eldt: "1022", eta_min: 7,
  runway: "33", runway_source: "ATIS", proc: { name: "BIMPA6U", fixes: ["BIMPA", "WA529"], approaches: ["RNP", "ILS Z"] },
  entry_fix: { fix: "BIMPA" }, viff: null, route: "SOBRA Y180 BIMPA" };
const loc = { kind: "local", callsign: "SPKAT", aircraft: "C172", wake: "L", rules: "V", departure: "EPWA", arrival: "EPWA",
  state: "air", altitude: 1300, groundspeed: 85, squawk: "6201", viff: null, route: "VFR CIRCUITS" };
const pln = { kind: "dep", planned: "viff", callsign: "SAS1748", departure: "EPWA", arrival: "ESSA", state: "offline",
  eobt: "0941", viff: { state: "SU", suspension: "FLS-NRA" } };
const out = {};
for (const [k, s] of Object.entries({ dep, arr, loc, pln })) out[k] = m.extLabel(s, d);
out.cols = m.XL_COLS;
out.fields = m.XL_FIELDS.map((f) => ({ k: f.k, row: f.row, col: f.col, span: f.span || 1 }));
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


def _by_key(fields):
    return {f["k"]: f for f in fields}


def test_extended_label_layout_is_data_driven(xl):
    # jedna tablica pól: każde pole ma wiersz i kolumnę w siatce XL_COLS, bez nakładania się pól tego samego rodzaju lotu
    cols = xl["cols"]
    assert cols == 4
    for f in xl["fields"]:
        assert 1 <= f["col"] and f["col"] + f["span"] - 1 <= cols, f
    for kind in ("dep", "arr", "loc", "pln"):
        cells = set()
        rows = sorted({f["row"] for f in xl[kind]})
        assert rows == list(range(1, len(rows) + 1)), kind   # wiersze bez pól znikają, numeracja ciągła
        for f in xl[kind]:
            for c in range(f["col"], f["col"] + f["span"]):
                assert (f["row"], c) not in cells, (kind, f)
                cells.add((f["row"], c))


def test_extended_label_fields_per_flight_kind(xl):
    dep, arr, loc, pln = (_by_key(xl[k]) for k in ("dep", "arr", "loc", "pln"))
    assert (dep["ssr"]["t"], dep["ssr"]["sub"]) == ("4613", "XPDR 2000")
    assert (dep["type"]["t"], dep["rules"]["t"], dep["reg"]["t"]) == ("B38M/M", "IFR", "SPLVA")
    assert (dep["adep"]["t"], dep["ades"]["t"], dep["rfl"]["t"], dep["lvl"]["t"]) == ("EPWA", "EPGD", "F220", "GND")
    assert (dep["proc"]["l"], dep["proc"]["t"], dep["rwy"]["t"], dep["rwy"]["sub"]) == ("SID", "OLILA6G", "29", "CDM")
    assert (dep["eobt"]["t"], dep["tsat"]["t"], dep["ttot"]["t"]) == ("1023", "1025", "1039")
    assert (dep["ctot"]["t"], dep["ctot"]["sub"]) == ("1043", "+20' EPWA29A") and "d30" in dep["ctot"]["cls"]
    assert dep["fls"]["t"] == "SI" and dep["status"]["t"] == "PARKED" and dep["stand"]["t"] is None
    assert dep["route"]["t"] == "OLILA L621" and dep["pts"]["l"] == "SID OLILA6G" and dep["rmk"]["t"] == "/V/"
    # przylot: ETA, ELDT, odległość, minuty, punkt wejścia i podejścia zamiast czasów A-CDM
    assert "tsat" not in arr and "ctot" not in arr and "rmk" not in arr
    assert (arr["eta"]["t"], arr["eldt"]["t"], arr["dist"]["t"], arr["in"]["t"]) == ("1018", "1022", "38 NM", "7'")
    assert (arr["proc"]["l"], arr["entry"]["t"], arr["apch"]["t"]) == ("STAR", "BIMPA", "RNP, ILS Z")
    assert (arr["lvl"]["t"], arr["status"]["t"], arr["gs"]["t"]) == ("F110", "AIRBORNE 330 KT", "330 KT")
    # lot lokalny VFR: bez wierszy pustych czasów vIFF; lot planowany: brak danych = None ("–")
    assert "tobt" not in loc and "ctot" not in loc and loc["eobt"]["t"] is None and loc["lvl"]["t"] == "A013"
    assert (pln["status"]["t"], pln["fls"]["t"], pln["ssr"]["t"], pln["lvl"]["t"]) == ("OFFLINE", "SU NRA", None, None)


def test_extended_label_window_stays_in_viewport(xl):
    p = xl["place"]
    assert p["below"] == {"left": 600, "top": 249}            # pod paskiem, od miejsca kliknięcia
    assert p["above"] == {"left": 600, "top": 297}            # brak miejsca pod paskiem: nad nim
    assert p["right"] == {"left": 1600 - 432 - 6, "top": 249}
    assert p["left"]["left"] == 6
    assert p["tall"]["top"] == 768 - 700 - 6 and p["tall"]["top"] >= 6


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
    assert 'document.addEventListener("click", onDocClick)' in js and 'document.removeEventListener("click", onDocClick)' in js
    assert "if (open) drawWin();" in js   # odświeżenie: nowe dane w oknie albo zamknięcie, gdy lotu już nie ma
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
