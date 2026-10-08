"""Wiatr na podejściu: punkty FAF/IF z procedur .ese albo na przedłużeniu osi (3°), interpolacja wiatru Open-Meteo
do 3000 ft AMSL i endpointy /api/meteo/approach-points, /api/meteo/approach-wind/{icao}."""
import json
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import DATA_DIR  # noqa: E402
from backend.app.routers import meteo  # noqa: E402
from backend.app.services import upperwind as uw  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

HAVE_ESE = bool(list((DATA_DIR / "import").glob("*.ese")))
NOW = datetime(2026, 10, 6, 16, 25, tzinfo=timezone.utc)
# poziomy ciśnienia: (hPa, wysokość m, prędkość kt, kierunek °); 914 m między 925 (770 m) a 900 hPa (1000 m)
LEVELS = [(1000, 120, 14, 300), (975, 330, 19, 305), (950, 545, 23, 309), (925, 770, 26, 310), (900, 1000, 30, 320),
          (850, 1470, 34, 324)]


def forecast_item(lat: float, lon: float, levels=LEVELS, sfc=(300, 12, 22)) -> dict:
    """Odpowiedź Open-Meteo dla jednego punktu: 24 godziny, wartości w godzinie 16 inne niż w pozostałych."""
    times = [f"2026-10-06T{h:02d}:00" for h in range(24)]
    hr = {"time": times}

    def series(v):
        return [v if h == 16 else (v or 0) + 50 for h in range(24)]

    hr["wind_direction_10m"], hr["wind_speed_10m"], hr["wind_gusts_10m"] = series(sfc[0]), series(sfc[1]), series(sfc[2])
    for p, hgt, spd, d in levels:
        hr[f"geopotential_height_{p}hPa"] = series(hgt)
        hr[f"wind_speed_{p}hPa"] = series(spd)
        hr[f"wind_direction_{p}hPa"] = series(d)
    return {"latitude": lat, "longitude": lon, "elevation": 100.0, "hourly": hr}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def fake_meteo(monkeypatch):
    calls = []

    async def fetch(url, ttl, params=None, headers=None):
        calls.append((url, ttl, params))
        lats, lons = params["latitude"].split(","), params["longitude"].split(",")
        items = [forecast_item(float(a), float(b)) for a, b in zip(lats, lons)]
        return json.dumps(items if len(items) > 1 else items[0])

    async def metars(icaos):
        return {i: f"{i} 061620Z 31014G26KT 9999 FEW030 12/05 Q1012" for i in icaos}

    monkeypatch.setattr(uw, "fetch_text", fetch)
    monkeypatch.setattr(meteo, "get_metars", metars)
    monkeypatch.setattr(uw, "parse_forecast", lambda text, now=None, _f=uw.parse_forecast: _f(text, NOW))
    return calls


# --- geometria

def test_geometry_roundtrip():
    lat, lon = uw.destination(52.1715, 20.9467, 295.0, 8.0)
    assert uw.distance_nm(52.1715, 20.9467, lat, lon) == pytest.approx(8.0, abs=0.01)
    assert uw.bearing(52.1715, 20.9467, lat, lon) == pytest.approx(295.0, abs=0.1)
    assert uw.angle_diff(355, 5) == 10 and uw.angle_diff(90, 270) == 180
    # ścieżka 3°: ok. 318 ft/NM, 3000 ft AMSL nad progiem na 362 ft po ok. 8.3 NM; minimum 2,5 NM
    assert uw.FT_PER_NM == pytest.approx(318.4, abs=0.2)
    assert uw.glide_distance_nm(362) == pytest.approx(8.29, abs=0.02)
    assert uw.glide_distance_nm(2900) == uw.MIN_NM


PROCS = {"EPXX": {"sid": {}, "star": {
    "29": [{"name": "AAAAA1A", "fixes": ["AAAAA", "XX701"], "approaches": ["ILS Z"]},
           {"name": "BBBBB1A", "fixes": ["BBBBB", "XX701"], "approaches": ["RNP"]},
           {"name": "CCCCC1A", "fixes": ["CCCCC", "XX702"], "approaches": ["RNP"]},
           {"name": "DDDDD1A", "fixes": ["DDDDD", "XX799"], "approaches": []}],   # bez podejścia: pomijany
    "11": [{"name": "EEEEE1B", "fixes": ["EEEEE", "XX401"], "approaches": ["ILS"]}],
    "15": [{"name": "FFFFF1C", "fixes": ["FFFFF", "XX501"], "approaches": ["RNP"]}],
}}}
THR = {"29": (52.0, 21.0, 290.0), "11": (52.0, 20.8, 110.0), "15": (52.1, 20.9, 150.0)}


def _fixes():
    out = {}
    lat, lon, hdg = THR["29"]
    # XX701 (2 procedury) 7 NM na osi, XX702 (1 procedura) 8 NM na osi: wygrywa częstszy
    out["XX701"] = [uw.destination(lat, lon, hdg + 180, 7.0), (-40.0, 175.0)]   # nazwa powtórzona na świecie
    out["XX702"] = [uw.destination(lat, lon, hdg + 180, 8.0)]
    lat, lon, hdg = THR["11"]
    out["XX401"] = [uw.destination(lat, lon, hdg + 180, 18.0)]                  # za daleko
    lat, lon, hdg = THR["15"]
    out["XX501"] = [uw.destination(lat, lon, hdg + 180 + 40, 6.0)]              # 40° od osi
    return out


def _rwy(des):
    lat, lon, hdg = THR[des]
    return {"designator": des, "heading": hdg, "lat": lat, "lon": lon}


def test_approach_point_from_procedure():
    p = uw.approach_point("EPXX", 362, _rwy("29"), _fixes(), PROCS)
    assert p["method"] == "procedure" and p["method_label"] == "FAF z procedury" and p["fix"] == "XX701"
    assert p["dist_nm"] == pytest.approx(7.0, abs=0.05) and p["stars"] == ["AAAAA1A", "BBBBB1A"]
    assert p["approaches"] == ["ILS Z", "RNP"] and p["rejected"] == []
    assert p["path_ft"] == pytest.approx(362 + 7 * uw.FT_PER_NM, abs=10)


@pytest.mark.parametrize("des, why", [("11", "NM od progu"), ("15", "od kursu podejścia")])
def test_approach_point_fallback_on_centreline(des, why):
    p = uw.approach_point("EPXX", 362, _rwy(des), _fixes(), PROCS)
    assert p["method"] == "centreline" and p["method_label"] == "na przedłużeniu osi, 3°" and p["fix"] is None
    assert len(p["rejected"]) == 1 and why in p["rejected"][0]
    lat, lon, hdg = THR[des]
    assert p["dist_nm"] == pytest.approx(8.3, abs=0.05) and p["path_ft"] == pytest.approx(3000, abs=10)
    assert uw.distance_nm(lat, lon, p["lat"], p["lon"]) == pytest.approx(8.29, abs=0.02)
    # punkt przed progiem, na kursie podejścia: z punktu do progu lecimy kursem pasa
    assert uw.angle_diff(uw.bearing(p["lat"], p["lon"], lat, lon), hdg) < 0.5


def test_approach_point_without_procedures_or_coordinates():
    p = uw.approach_point("EPYY", 100, _rwy("29"), {}, PROCS)
    assert p["method"] == "centreline" and p["rejected"] == []
    p = uw.approach_point("EPXX", 100, _rwy("29"), {}, PROCS)
    assert p["method"] == "centreline" and all("brak współrzędnych" in r for r in p["rejected"])


def test_approach_point_faf_just_inside_3nm():
    """EPZG RWY 06: FAF ZG463 2,99 NM od progu mieści się w 2,5–15 NM; punkt bliżej niż 2,5 NM odrzucony z opisem."""
    lat, lon, hdg = THR["29"]
    fixes = {"XX701": [uw.destination(lat, lon, hdg + 180, 2.99)], "XX702": [uw.destination(lat, lon, hdg + 180, 2.3)]}
    p = uw.approach_point("EPXX", 192, _rwy("29"), fixes, PROCS)
    assert uw.MIN_NM == 2.5 and p["method"] == "procedure" and p["fix"] == "XX701" and p["dist_nm"] == 3.0
    assert p["rejected"] == ["XX702: 2.30 NM od progu (< 2.5 NM)"]
    far = {"XX701": [uw.destination(lat, lon, hdg + 180, 16.0)]}
    assert uw.approach_point("EPXX", 192, _rwy("29"), far, PROCS)["rejected"][0] == "XX701: 16.0 NM od progu (> 15 NM)"


def _r(des, surface="CON", length=2500.0, coords=True, hdg=None):
    return SimpleNamespace(designator=des, surface=surface, length_m=length, heading_true=hdg,
                           lat=50.1 if coords else None, lon=22.0 if coords else None)


def test_approach_runways_skip_grass_emergency_and_no_threshold():
    """EPRZ: 08L/26R trawa i 08R/26L bez współrzędnych progu, 09ES/27ES "GRS Emergency Strip" pomijane."""
    eprz = [_r("08L", "GRASS", 746, False), _r("08R", "CONC/ASPH", 900, False), _r("09", "CON", 3200),
            _r("09ES", "GRS Emergency Strip", 2085), _r("26L", "CONC/ASPH", 900, False), _r("26R", "GRASS", 746, False),
            _r("27", "CON", 3200), _r("27ES", "GRS Emergency Strip", 2085)]
    des = lambda rs: [r.designator for r in rs]  # noqa: E731
    assert des(uw.approach_runways(eprz, lambda d: False)) == ["09", "27"]
    # pas z procedurą podejścia zostaje mimo wszystko; krótki twardy pas (< 1200 m) pomijany
    assert des(uw.approach_runways(eprz, lambda d: d == "26L")) == ["09", "26L", "27"]
    assert des(uw.approach_runways([_r("05", length=1100), _r("13", length=2500)], lambda d: False)) == ["13"]
    assert uw.soft_runway("grass paved with a plastic grille", "05L") and uw.soft_runway("G", "18")
    assert not uw.soft_runway("Concrete", "09") and not uw.soft_runway("ASPH-CONC", "07")
    # lądowisko bez takiego pasa: wszystkie kierunki, z równoległych lepszy (współrzędne progu, twardy, dłuższy)
    small = [_r("08L", "grass", 700, False), _r("08R", "Ashpalt", 900, False), _r("10", "Grass", 680, False),
             _r("26L", "Ashpalt", 900, False), _r("26R", "grass", 700, False), _r("28", "Grass", 680, False)]
    assert des(uw.approach_runways(small, lambda d: False)) == ["08R", "10", "26L", "28"]


# --- wiatr

def test_interpolate_wind_between_levels():
    w = uw.interpolate_wind(LEVELS, uw.ALT_M)
    k = (914.4 - 770) / (1000 - 770)
    assert w["levels_hpa"] == [925, 900]
    assert w["dir"] == pytest.approx(310 + 10 * k, abs=1) and w["speed"] == pytest.approx(26 + 4 * k, abs=1)
    # składowe u/v: przez północ bez skoku 350 -> 10 i bez zera prędkości
    w = uw.interpolate_wind([(925, 800, 20, 350), (900, 1000, 20, 10)], 900)
    assert w["dir"] == 360 and w["speed"] == 20
    # poza zakresem: najbliższy poziom; brakujące wartości pomijane
    assert uw.interpolate_wind([(900, 1000, 30, 200), (850, 1500, 40, 210)], 914)["dir"] == 200
    assert uw.interpolate_wind([(925, 700, None, 100), (900, 1000, 30, 200)], 914)["levels_hpa"] == [900]
    assert uw.interpolate_wind([(925, None, 10, 100)], 914) is None


def test_parse_forecast_current_hour_and_shapes():
    one = json.dumps(forecast_item(52.0, 21.0))
    res = uw.parse_forecast(one, NOW)
    assert len(res) == 1 and res[0]["valid"] == "2026-10-06T16:00Z"
    assert res[0]["surface"] == {"dir": 300, "speed": 12, "gust": 22}
    assert res[0]["w3000"]["levels_hpa"] == [925, 900]
    many = json.dumps([forecast_item(52.0, 21.0), forecast_item(52.1, 21.1, sfc=(5, 3, 4))])
    res = uw.parse_forecast(many, NOW)
    assert [r["surface"]["dir"] for r in res] == [300, 5]
    with pytest.raises(UpstreamError, match="Open-Meteo"):
        uw.parse_forecast(json.dumps({"error": True, "reason": "Latitude must be in range"}), NOW)


def test_model_winds_one_request(fake_meteo):
    import asyncio
    res = asyncio.run(uw.model_winds([(52.16571, 20.9671), (52.22739, 20.74647)]))
    assert len(res) == 2 and len(fake_meteo) == 1
    url, ttl, params = fake_meteo[0]
    assert url == uw.OPEN_METEO_URL and ttl == 600 and params["wind_speed_unit"] == "kn"
    assert params["latitude"] == "52.1657,52.2274" and params["longitude"] == "20.9671,20.7465"
    hourly = params["hourly"].split(",")
    assert "wind_speed_10m" in hourly and all(f"geopotential_height_{p}hPa" in hourly for p in uw.LEVELS)


# --- endpointy

def test_approach_points_endpoint(client):
    d = client.get("/api/meteo/approach-points").json()
    assert d["alt_ft"] == 3000 and len(d["aerodromes"]) > 10
    ads = {a["icao"]: a for a in d["aerodromes"]}
    for a in ads.values():
        for r in a["runways"]:
            assert r["method"] in ("procedure", "centreline")
            if r["method"] == "procedure":
                assert uw.MIN_NM <= r["dist_nm"] <= uw.MAX_NM and r["fix"]
            else:
                assert r["dist_nm"] == pytest.approx(uw.glide_distance_nm(a["elevation_ft"]), abs=0.05)
    if HAVE_ESE:
        epwa = {r["designator"]: r for r in ads["EPWA"]["runways"]}
        assert {k: v["fix"] for k, v in epwa.items()} == {"11": "WA409", "15": "WA612", "29": "WA728", "33": "WA529"}
        assert all(v["method_label"] == "FAF z procedury" for v in epwa.values())
    if "EPRZ" in ads:
        # bez trawiastych 08L/26R, 08R/26L bez współrzędnych progu i pasów awaryjnych 09ES/27ES
        assert [r["designator"] for r in ads["EPRZ"]["runways"]] == ["09", "27"]


def test_approach_wind_endpoint(client, fake_meteo):
    d = client.get("/api/meteo/approach-wind/epwa").json()
    assert d["icao"] == "EPWA" and d["source"] == "Open-Meteo" and d["valid"] == "2026-10-06T16:00Z"
    assert d["model_error"] is None and d["metar_error"] is None and len(fake_meteo) == 1
    # jedno zapytanie: punkt lotniska + punkt podejścia każdego pasa
    assert len(fake_meteo[0][2]["latitude"].split(",")) == 1 + len(d["runways"])
    assert d["metar_wind"]["dir"] == 310 and d["metar_wind"]["gust"] == 26
    assert d["model_surface"] == {"dir": 300, "speed": 12, "gust": 22}
    for r in d["runways"]:
        assert r["w3000"]["speed"] > 26 and set(r["c3000"]) == {"hw", "xw"}
        hdg = r["heading"]
        hw, xw = r["c_metar"]["hw"], r["c_metar"]["xw"]
        assert (hw ** 2 + xw ** 2) ** 0.5 == pytest.approx(14, abs=0.2)
        assert (hw > 0) == (uw.angle_diff(310, hdg) < 90)
    if HAVE_ESE:
        r29 = next(r for r in d["runways"] if r["designator"] == "29")
        assert r29["fix"] == "WA728" and r29["c3000"]["hw"] > 0


def test_approach_wind_degrades_without_open_meteo(client, monkeypatch):
    async def down(url, ttl, params=None, headers=None):
        raise UpstreamError(f"{url}: brak sieci")

    async def no_metar(icaos):
        raise UpstreamError("metar.vatsim.net: brak sieci")

    monkeypatch.setattr(uw, "fetch_text", down)
    monkeypatch.setattr(meteo, "get_metars", no_metar)
    d = client.get("/api/meteo/approach-wind/EPKK").json()
    assert "Open-Meteo" in d["model_error"] and "brak sieci" in d["model_error"] and "METAR" in d["metar_error"]
    assert d["valid"] is None and d["model_surface"] is None and d["runways"]
    for r in d["runways"]:
        assert r["w3000"] is None and r["c3000"] == {"hw": None, "xw": None} and r["lat"] and r["method"]


def test_upstream_reason_short_without_query():
    """Błąd Open-Meteo w UI bez adresu z parametrami: HTTP 400 z "reason" z JSON, brak sieci bez adresu."""
    import httpx
    req = httpx.Request("GET", uw.OPEN_METEO_URL + "?latitude=52.1&hourly=" + ",".join(uw.hourly_variables()))
    resp = httpx.Response(400, json={"error": True, "reason": "Cannot initialize WeatherVariable"}, request=req)
    try:
        raise UpstreamError(f"{uw.OPEN_METEO_URL}: boom") from httpx.HTTPStatusError("400", request=req, response=resp)
    except UpstreamError as exc:
        assert uw.upstream_reason(exc) == "HTTP 400: Cannot initialize WeatherVariable"
    bad = httpx.Response(502, text="<html>", request=req)
    try:
        raise UpstreamError("x") from httpx.HTTPStatusError("502", request=req, response=bad)
    except UpstreamError as exc:
        assert uw.upstream_reason(exc) == "HTTP 502 Bad Gateway"
    assert uw.upstream_reason(UpstreamError(f"{uw.OPEN_METEO_URL}: [Errno -3] DNS")) == "[Errno -3] DNS"


def test_approach_wind_unknown_aerodrome(client):
    r = client.get("/api/meteo/approach-wind/XXXX")
    assert r.status_code == 404 and "XXXX" in r.json()["detail"]
