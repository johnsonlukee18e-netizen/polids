"""Paski postępu lotu (AERODROME › RUCH): SID/STAR z .ese, kategoria turbulencji, przydzielony SSR, kolejność pasków."""

from datetime import datetime, timezone

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
