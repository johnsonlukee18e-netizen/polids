"""AWALON (0.13.0, issue #23): profil wiatru 0–10 000 ft AMSL co 1000 ft nad 15 lotniskami AD 2, jedno zapytanie
o prognozę na 9 poziomach ciśnienia i jedno o METAR-y, endpoint /api/meteo/wind-profile."""
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.routers import meteo  # noqa: E402
from backend.app.services import awalon  # noqa: E402
from backend.app.services import overview  # noqa: E402
from backend.app.services import upperwind as uw  # noqa: E402
from backend.app.services.eaip import AD2_AERODROMES  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

NOW = datetime(2026, 10, 28, 16, 25, tzinfo=timezone.utc)
# (hPa, wysokość m, kt, °) w godzinie 16; 10 000 ft (3048 m) między 700 (3010 m) a 600 hPa (4200 m)
LEVELS = [(1000, 110, 14, 300), (975, 320, 19, 305), (950, 540, 23, 309), (925, 760, 26, 313), (900, 990, 25, 318),
          (850, 1460, 18, 330), (800, 1950, 15, 300), (700, 3010, 26, 275), (600, 4200, 38, 268)]
SFC = (300, 12, 22)
# zmiana w godzinach 15 i 17 (prędkość kt, kierunek °); pozostałe godziny daleko (spoza okna ±1 h)
SHIFT = {15: (-2, -10), 16: (0, 0), 17: (3, 5)}
METARS = {"EPWA": "EPWA 281620Z 31014G26KT 280V340 9999 FEW030 12/05 Q1012",
          "EPLB": "EPLB 281620Z VRB02KT CAVOK 10/05 Q1013",
          "EPKT": "EPKT 281620Z 25008KT 9999 SCT030 10/05 Q1014"}


def item(lat: float, lon: float, levels=LEVELS, sfc=SFC) -> dict:
    times = [f"2026-10-28T{h:02d}:00" for h in range(24)]
    hr = {"time": times}

    def series(v, kind):
        out = []
        for h in range(24):
            ds, dd = SHIFT.get(h, (40, 90))
            out.append(None if v is None else v if kind == "h" else (v + ds if kind == "s" else (v + dd) % 360))
        return out

    hr["wind_direction_10m"], hr["wind_speed_10m"] = series(sfc[0], "d"), series(sfc[1], "s")
    hr["wind_gusts_10m"] = series(sfc[2], "s")
    for p, hgt, spd, d in levels:
        hr[f"geopotential_height_{p}hPa"] = series(hgt, "h")
        hr[f"wind_speed_{p}hPa"] = series(spd, "s")
        hr[f"wind_direction_{p}hPa"] = series(d, "d")
    return {"latitude": lat, "longitude": lon, "hourly": hr}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def fake(monkeypatch):
    calls = {"meteo": [], "metar": []}

    async def fetch(url, ttl, params=None, headers=None):
        calls["meteo"].append((url, ttl, params))
        lats, lons = params["latitude"].split(","), params["longitude"].split(",")
        return json.dumps([item(float(a), float(b)) for a, b in zip(lats, lons)])

    async def metars(icaos):
        calls["metar"].append(list(icaos))
        return {i: METARS[i] for i in icaos if i in METARS}

    monkeypatch.setattr(uw, "fetch_text", fetch)
    monkeypatch.setattr(meteo, "get_metars", metars)
    monkeypatch.setattr(awalon, "_now", lambda: NOW)
    return calls


def rows(ad: dict) -> dict:
    return {r["alt_ft"]: r for r in ad["profile"]}


def test_one_request_for_all_aerodromes(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    assert [a["icao"] for a in d["aerodromes"]] == list(AD2_AERODROMES)
    # jedno zapytanie o prognozę (15 punktów, 9 poziomów, 30 zmiennych, cache 30 min) i jedno o METAR-y
    assert len(fake["meteo"]) == 1 and len(fake["metar"]) == 1
    url, ttl, params = fake["meteo"][0]
    assert url == uw.OPEN_METEO_URL and ttl == uw.PROFILE_CACHE_SECONDS == 1800
    assert len(params["latitude"].split(",")) == len(params["longitude"].split(",")) == 15
    assert params["wind_speed_unit"] == "kn" and params["timezone"] == "GMT" and params["forecast_days"] == "1"
    hourly = params["hourly"].split(",")
    assert uw.PROFILE_LEVELS == (1000, 975, 950, 925, 900, 850, 800, 700, 600) and len(hourly) == 30
    assert all(f"{v}_{p}hPa" in hourly for p in uw.PROFILE_LEVELS
               for v in ("wind_speed", "wind_direction", "geopotential_height"))
    # METAR-y tą samą listą co OVERVIEW: jeden wpis w cache
    assert fake["metar"][0] == list(overview.AERODROMES)


def test_cache_does_not_cross_midnight():
    """Odpowiedź obejmuje tylko swoją dobę UTC: tuż po północy kopia sprzed północy jest nieaktualna."""
    at = lambda h, m, s=0: datetime(2026, 10, 28, h, m, s, tzinfo=timezone.utc)  # noqa: E731
    assert [uw.profile_ttl(at(*t)) for t in ((16, 25), (0, 30), (0, 10), (0, 0, 0), (23, 59))] == [1800, 1800, 600, 1, 1800]


def test_shape(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    assert set(d) == {"alts_ft", "valid", "fetched", "model_error", "metar_error", "aerodromes"}
    assert d["alts_ft"] == list(range(0, 10001, 1000)) and d["valid"] == "2026-10-28T16:00Z" and d["fetched"] == "16:25Z"
    assert d["model_error"] is None and d["metar_error"] is None
    epwa = d["aerodromes"][list(AD2_AERODROMES).index("EPWA")]
    assert set(epwa) == {"icao", "name", "lat", "lon", "elevation_ft", "metar", "metar_wind", "model_surface", "profile"}
    assert epwa["elevation_ft"] == 362 and epwa["model_surface"] == {"dir": 300, "speed": 12, "gust": 22}
    assert [r["alt_ft"] for r in epwa["profile"]] == d["alts_ft"]
    keys = {"alt_ft", "kind", "status", "dir", "speed", "gust", "variable", "min_dir", "max_dir", "min_speed",
            "max_speed", "samples", "levels_hpa"}
    assert all(set(r) == keys for a in d["aerodromes"] for r in a["profile"])
    # bez nazw dostawców w odpowiedzi
    assert "open-meteo" not in json.dumps(d).lower()


def test_top_row_between_700_and_600(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    r = rows(d["aerodromes"][list(AD2_AERODROMES).index("EPWA")])[10000]
    k = (3048 - 3010) / (4200 - 3010)
    assert r["kind"] == "air" and r["status"] == "FCST" and r["levels_hpa"] == [700, 600]
    assert r["speed"] == pytest.approx(26 + 12 * k, abs=1) and r["dir"] == pytest.approx(275 - 7 * k, abs=1)
    # 7K–9K między 800 a 700 hPa, 5K między 850 a 800
    assert rows(d["aerodromes"][0])[8000]["levels_hpa"] == [800, 700]
    assert rows(d["aerodromes"][0])[5000]["levels_hpa"] == [850, 800]


def test_epkt_1000ft_is_ground(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    kt = d["aerodromes"][list(AD2_AERODROMES).index("EPKT")]
    assert kt["elevation_ft"] == 1008
    r = rows(kt)
    assert r[1000]["kind"] == "gnd" and r[1000]["status"] == "GND" and r[1000]["dir"] is None and r[1000]["speed"] is None
    assert r[2000]["kind"] == "air" and r[2000]["status"] == "FCST"
    # na pozostałych lotniskach (najwyżej 792 ft) wiersz 1000 ft jest nad ziemią
    assert all(rows(a)[1000]["kind"] == "air" for a in d["aerodromes"] if a["icao"] != "EPKT")


def test_levels_below_ground_dropped():
    # EPKT 1008 ft = 307 m: 1000 hPa na 60 m i 975 hPa na 280 m (wartości spod ziemi) odpadają
    lv = [(1000, 60, 45, 90), (975, 280, 40, 100), (950, 500, 18, 230), (925, 720, 22, 240)]
    usable = awalon.usable_levels(lv, {"dir": 220, "speed": 8, "gust": None}, 1008)
    assert [x[0] for x in usable] == [950, 925, None] and usable[-1][1] == pytest.approx(1008 * 0.3048 + 10)
    # bez wiatru 10 m najniższy poziom nad ziemią, nie ekstrapolowany 1000 hPa
    assert [x[0] for x in awalon.usable_levels(lv, None, 1008)] == [950, 925]
    hours = [{"time": f"2026-10-28T{h:02d}:00", "surface": None, "levels": lv} for h in range(24)]
    r = {x["alt_ft"]: x for x in awalon.profile(hours, 16, 1008, None)}
    assert r[0]["status"] == "N/A" and r[1000]["status"] == "GND"
    assert (r[2000]["dir"], r[2000]["speed"]) == pytest.approx((236, 20), abs=1) and r[2000]["levels_hpa"] == [950, 925]
    # EPKK 792 ft: 1000 ft (305 m) między wiatrem 10 m (251 m) a 975 hPa (320 m), 1000 hPa (110 m) pod ziemią
    lv = [(1000, 110, 45, 90), (975, 320, 20, 300)]
    hours = [{"time": "2026-10-28T16:00", "surface": {"dir": 300, "speed": 10, "gust": 18}, "levels": lv}]
    r = {x["alt_ft"]: x for x in awalon.profile(hours, 0, 792, None)}
    k = (304.8 - (792 * 0.3048 + 10)) / (320 - (792 * 0.3048 + 10))
    assert r[1000]["dir"] == 300 and r[1000]["speed"] == pytest.approx(10 + 10 * k, abs=1)
    assert r[1000]["levels_hpa"] == [975] and r[1000]["samples"] == 1


def test_surface_metar_or_forecast(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    by = {a["icao"]: a for a in d["aerodromes"]}
    wa = rows(by["EPWA"])[0]
    # METAR z porywem i sektorem zmienności
    assert wa["kind"] == "sfc" and wa["status"] == "METAR"
    assert (wa["dir"], wa["speed"], wa["gust"], wa["variable"]) == (310, 14, 26, False)
    assert (wa["min_dir"], wa["max_dir"], wa["min_speed"], wa["max_speed"], wa["samples"]) == (280, 340, 14, 26, 1)
    assert by["EPWA"]["metar_wind"]["time"] == "281620Z"
    kt = rows(by["EPKT"])[0]
    assert (kt["status"], kt["dir"], kt["speed"], kt["gust"], kt["min_dir"], kt["max_dir"]) == ("METAR", 250, 8, None, 250, 250)
    # bez METAR-u: prognoza 10 m z porywem i min/max ±1 h
    zg = rows(by["EPZG"])[0]
    assert by["EPZG"]["metar"] is None and by["EPZG"]["metar_wind"] is None
    assert (zg["status"], zg["dir"], zg["speed"], zg["gust"]) == ("FCST", 300, 12, 22)
    assert (zg["min_dir"], zg["max_dir"], zg["min_speed"], zg["max_speed"], zg["samples"]) == (290, 305, 10, 15, 3)


def test_vrb_metar(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    lb = next(a for a in d["aerodromes"] if a["icao"] == "EPLB")
    r = rows(lb)[0]
    assert r["status"] == "METAR" and r["variable"] is True and r["dir"] is None and r["speed"] == 2
    assert r["min_dir"] is None and r["max_dir"] is None and r["min_speed"] == r["max_speed"] == 2
    assert lb["metar_wind"]["variable"] is True


def test_min_max_previous_current_next_hour(client, fake):
    d = client.get("/api/meteo/wind-profile").json()
    for a in d["aerodromes"]:
        for r in a["profile"]:
            if r["kind"] != "air":
                continue
            # godziny 15 (-2 kt, -10°), 16, 17 (+3 kt, +5°); godziny spoza okna (+40 kt, +90°) się nie liczą
            assert r["samples"] == 3, (a["icao"], r["alt_ft"])
            assert r["min_speed"] == pytest.approx(r["speed"] - 2, abs=1) and r["max_speed"] == pytest.approx(r["speed"] + 3, abs=1)
            assert uw.angle_diff(r["min_dir"], r["dir"] - 10) <= 1 and uw.angle_diff(r["max_dir"], r["dir"] + 5) <= 1


def test_window_at_start_of_day_and_through_north():
    lv = [(925, 760, 20, 355), (900, 990, 20, 355)]
    hours = [{"time": f"2026-10-28T{h:02d}:00", "surface": None,
              "levels": [(p, m, s + h, (d + 10 * h) % 360) for p, m, s, d in lv]} for h in range(24)]
    r = {x["alt_ft"]: x for x in awalon.profile(hours, 0, 100, None)}[3000]
    # 00Z: tylko bieżąca i następna godzina; kierunek przez północ 355 -> 005 (nie 005..355)
    assert r["samples"] == 2 and (r["min_dir"], r["max_dir"]) == (355, 5) and (r["min_speed"], r["max_speed"]) == (20, 21)
    assert awalon.dir_range([350, 360, 10], 360) == (350, 10) and awalon.dir_range([90, 80, 100], 90) == (80, 100)
    assert uw.hour_index([h["time"] for h in hours], datetime(2026, 10, 28, 0, 10, tzinfo=timezone.utc)) == 0


def test_degrades_without_network(client, monkeypatch, caplog):
    async def down(url, ttl, params=None, headers=None):
        raise UpstreamError(f"{url}: brak sieci")

    async def no_metar(icaos):
        raise UpstreamError("metar.vatsim.net: brak sieci")

    monkeypatch.setattr(uw, "fetch_text", down)
    monkeypatch.setattr(meteo, "get_metars", no_metar)
    r = client.get("/api/meteo/wind-profile")
    assert r.status_code == 200
    d = r.json()
    # krótkie komunikaty bez adresu i nazwy serwera, pełna przyczyna w logu
    assert d["model_error"] == "Wind forecast unavailable: brak sieci"
    assert d["metar_error"] == "METAR unavailable: brak sieci"
    logged = [m.getMessage() for m in caplog.records if m.name == "polids.meteo"]
    assert any(m.startswith("AWALON, METAR: metar.vatsim.net") for m in logged), logged
    assert any(m.startswith("AWALON, prognoza: brak sieci") and uw.OPEN_METEO_URL in m for m in logged), logged
    assert d["valid"] is None and len(d["aerodromes"]) == 15
    for a in d["aerodromes"]:
        assert a["model_surface"] is None and a["metar_wind"] is None
        for row in a["profile"]:
            assert row["status"] == ("GND" if row["kind"] == "gnd" else "N/A") and row["speed"] is None


def test_unreadable_forecast_is_an_error(client, monkeypatch, fake):
    async def bad(url, ttl, params=None, headers=None):
        return json.dumps([item(52.0, 21.0)])   # 1 punkt zamiast 15

    monkeypatch.setattr(uw, "fetch_text", bad)
    d = client.get("/api/meteo/wind-profile").json()
    assert d["model_error"] == "Wind forecast unavailable: 1 points in the response instead of 15"
    assert d["metar_error"] is None and rows(d["aerodromes"][0])[0]["status"] in ("METAR", "N/A")


def test_approach_wind_unchanged_shape():
    """AERODROME nadal używa approach-wind: interpolacja z poziomem przy ziemi (hPa None) nie zmienia levels_hpa."""
    w = uw.interpolate_wind([(None, 100, 10, 300), (975, 320, 20, 300)], 200)
    assert w["levels_hpa"] == [975] and set(w) == {"dir", "speed", "levels_hpa"}
    assert asyncio.iscoroutinefunction(uw.model_winds) and uw.LEVELS == (1000, 975, 950, 925, 900, 850)
