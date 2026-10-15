"""Słońce (services/sun.py, METEO › SUN, AERODROME › PRZEGLĄD): wschód i zachód, zmierzch cywilny, polarny dzień i noc,
punkt podsłoneczny i /api/meteo/sun.

Wartości wzorcowe policzone niezależnym programem PyEphem 4.2.1 (libastro z XEphem, nie NOAA): wschód/zachód = górny
brzeg tarczy 34′ pod horyzontem (pressure=0, horizon=-0:34), zmierzch cywilny = środek tarczy 6° pod horyzontem; doba
od lokalnej północy (UTC − długość/15 h). Zgadzają się z tablicami (np. Warszawa 21.06: wschód 04:15 CEST)."""
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.services import sun  # noqa: E402

# najgorszy błąd względem PyEphem w REF: 0,32 min; dawny algorytm (sprzed 0.12.3) myli się o 1–2 min już w Warszawie
TOL = timedelta(minutes=1)
EPWA, KSFO, RJTT = (52.1657, 20.9671), (37.6188, -122.3756), (35.5523, 139.7798)
NZAA, ENSB = (-37.0081, 174.7917), (78.2461, 15.4656)
CYLT, ENTC = (82.5178, -62.2806), (69.6833, 18.9189)

# (miejsce, data doby lotniska, {zdarzenie: UTC z PyEphem})
REF = [
    (EPWA, date(2026, 10, 15), {"sunrise": "2026-10-15T05:00:52", "sunset": "2026-10-15T15:42:06",
                                "civil_dawn": "2026-10-15T04:26:39", "civil_dusk": "2026-10-15T16:16:15"}),
    (EPWA, date(2026, 6, 21), {"sunrise": "2026-06-21T02:14:58", "sunset": "2026-06-21T19:00:53",
                               "civil_dawn": "2026-06-21T01:25:36", "civil_dusk": "2026-06-21T19:50:15"}),
    (EPWA, date(2026, 12, 21), {"sunrise": "2026-12-21T06:42:43", "sunset": "2026-12-21T14:25:36"}),
    # San Francisco: zachód (i koniec zmierzchu) już następnego dnia UTC
    (KSFO, date(2026, 10, 15), {"sunrise": "2026-10-15T14:17:57", "sunset": "2026-10-16T01:31:55",
                                "civil_dawn": "2026-10-15T13:51:34", "civil_dusk": "2026-10-16T01:58:17"}),
    # Tokio: wschód jeszcze poprzedniego dnia UTC
    (RJTT, date(2026, 10, 15), {"sunrise": "2026-10-14T20:46:51", "sunset": "2026-10-15T08:06:08",
                                "civil_dawn": "2026-10-14T20:21:12", "civil_dusk": "2026-10-15T08:31:46"}),
    # Auckland (półkula południowa, blisko linii zmiany daty)
    (NZAA, date(2026, 12, 21), {"sunrise": "2026-12-20T16:57:23", "sunset": "2026-12-21T07:39:56"}),
    # Svalbard poza dniem i nocą polarną; w kwietniu białe noce (zmierzch cywilny całą dobę)
    (ENSB, date(2026, 3, 1), {"sunrise": "2026-03-01T07:28:00", "sunset": "2026-03-01T14:55:38",
                              "civil_dawn": "2026-03-01T05:38:27", "civil_dusk": "2026-03-01T16:45:49"}),
    (ENSB, date(2026, 4, 15), {"sunrise": "2026-04-15T00:44:45", "sunset": "2026-04-15T21:26:06"}),
]


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("place,day,ref", REF)
def test_events_against_reference(place, day, ref):
    ev = sun.sun_day(*place, day)
    for name, want in ref.items():
        assert ev[name] is not None, name
        assert abs(ev[name] - _t(want)) <= TOL, (name, ev[name], want)


def test_polar_day_and_night():
    june, dec, april = sun.sun_day(*ENSB, date(2026, 6, 21)), sun.sun_day(*ENSB, date(2026, 12, 21)), \
        sun.sun_day(*ENSB, date(2026, 4, 15))
    assert (june["polar"], june["civil_polar"]) == ("day", "day")
    assert (dec["polar"], dec["civil_polar"]) == ("night", "night")
    assert all(june[n] is None and dec[n] is None for n in ("sunrise", "sunset", "civil_dawn", "civil_dusk"))
    # białe noce: słońce zachodzi, ale nie schodzi 6° pod horyzont
    assert april["polar"] is None and april["civil_polar"] == "day" and april["civil_dawn"] is None
    assert sun.sun_day(*EPWA, date(2026, 6, 21))["polar"] is None


def _crossings(lat, lon, ev, alt):
    """Przejścia środka tarczy przez wysokość alt w dobie słonecznej (od północy do północy wokół górowania), co 15 s:
    [("rise" / "set", chwila)]; ta sama wysokość słońca co w sun.py, tylko bez żadnego wzoru na kąt godzinny."""
    t, end, out = ev["noon"] - timedelta(hours=12), ev["noon"] + timedelta(hours=12), []
    prev = sun.elevation(lat, lon, t) - alt
    while t < end:
        t += timedelta(seconds=15)
        e = sun.elevation(lat, lon, t) - alt
        if prev * e < 0:
            out.append(("rise" if e > 0 else "set", t))
        prev = e
    return out


@pytest.mark.parametrize("place,day,alt,kind", [
    # pierwsze słońce po nocy polarnej (Svalbard 15.02 i Alert 14.10: kilka minut nad horyzontem); dawniej bez wschodu
    (ENSB, date(2026, 2, 15), -0.833, "both"), (CYLT, date(2026, 10, 14), -0.833, "both"),
    # początek dnia polarnego: wschód, a zachodu do końca doby już nie ma
    (ENSB, date(2026, 4, 18), -0.833, "rise"), (CYLT, date(2026, 4, 6), -0.833, "rise"),
    (ENTC, date(2026, 5, 17), -0.833, "rise"),
    # koniec dnia polarnego: słońce nad horyzontem od początku doby i zachodzi
    (CYLT, date(2026, 9, 5), -0.833, "set"), (ENTC, date(2026, 7, 26), -0.833, "set"),
    (ENSB, date(2026, 8, 24), -0.833, "set"),
    # białe noce: pierwszy BMCT bez EECT i ostatni EECT bez BMCT
    (ENSB, date(2026, 4, 4), -6, "rise"), (ENSB, date(2026, 9, 8), -6, "set"),
])
def test_polar_transition_days(place, day, alt, kind):
    """Dni przejścia do dnia lub nocy polarnej i białych nocy: te same zdarzenia co gęste przeszukanie wysokości słońca
    (±1 min), w dniu jednostronnym brak drugiego zdarzenia, a "polar" puste (to nie jest cała doba po jednej stronie)."""
    ev = sun.sun_day(*place, day)
    rise, set_, key = ("sunrise", "sunset", "polar") if alt > -1 else ("civil_dawn", "civil_dusk", "civil_polar")
    want = _crossings(*place, ev, alt)
    assert [k for k, _ in want] == {"both": ["rise", "set"], "rise": ["rise"], "set": ["set"]}[kind]
    got = {"rise": ev[rise], "set": ev[set_]}
    assert ev[key] is None and sum(v is not None for v in got.values()) == len(want)
    for k, t in want:
        assert got[k] is not None and abs(got[k] - t) <= TOL, (k, got[k], t)
        assert abs(sun.elevation(*place, got[k]) - alt) < 0.01


def test_report_transition_day_length():
    """Dzień jednostronny: długość dnia od wschodu do końca doby albo od początku doby do zachodu (zamiast "–")."""
    r = sun.report(*ENSB, now=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc))
    d = r["days"][0]
    assert d["sunrise"] and d["sunset"] is None and d["polar"] is None
    end = datetime.fromisoformat(d["noon"].replace("Z", "+00:00")) + timedelta(hours=12)
    sr = datetime.fromisoformat(d["sunrise"].replace("Z", "+00:00"))
    assert abs(d["day_length"] - (end - sr).total_seconds() / 60) <= 1 and 1300 < d["day_length"] < 1440
    d = sun.report(*CYLT, now=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))["days"][0]
    assert d["sunrise"] is None and d["sunset"] and 1300 < d["day_length"] < 1440
    # pierwsze słońce po nocy polarnej: kilka minut dnia
    d = sun.report(*ENSB, now=datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc))["days"][0]
    assert 0 < d["day_length"] < 10


def test_sun_times_keys_for_aerodrome():
    """AERODROME › PRZEGLĄD (sunBox) czyta "HH:MM" spod dotychczasowych kluczy; pełne daty ISO pod kluczami z "_at"."""
    s = sun.sun_times(*EPWA, now=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc))
    assert (s["sunrise"], s["sunset"], s["civil_dawn"], s["civil_dusk"]) == ("05:01", "15:42", "04:27", "16:16")
    assert abs(_t(s["sunrise_at"][:-1]) - _t("2026-10-15T05:00:52")) <= TOL
    assert s["day"] is True and s["polar"] is None
    assert sun.sun_times(*EPWA, now=datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc))["day"] is False
    assert sun.sun_times(None, 20.0) is None


@pytest.mark.parametrize("place,hour,day", [
    # zachód w UTC przed wschodem: dawniej "sr <= teraz < ss" dawało noc w środku dnia
    (KSFO, datetime(2026, 10, 15, 23, 0), True), (KSFO, datetime(2026, 10, 15, 10, 0), False),
    (RJTT, datetime(2026, 10, 15, 3, 0), True), (RJTT, datetime(2026, 10, 15, 12, 0), False),
    (ENSB, datetime(2026, 6, 21, 23, 30), True), (ENSB, datetime(2026, 12, 21, 11, 0), False),
])
def test_day_flag_far_from_greenwich(place, hour, day):
    s = sun.sun_times(*place, now=hour.replace(tzinfo=timezone.utc))
    assert s["day"] is day
    # godziny "HH:MM" i daty ISO opisują tę samą chwilę (HH:MM zaokrąglone do pełnej minuty)
    if s["sunset_at"]:
        assert (_t(s["sunset_at"][:-1]) + timedelta(seconds=30)).strftime("%H:%M") == s["sunset"]


def test_subsolar_point():
    # przesilenie czerwcowe 2026 (21.06 08:24 UTC): zwrotnik Raka; równonoc marcowa (20.03 14:46 UTC): równik
    lat, lon = sun.subsolar_point(datetime(2026, 6, 21, 8, 24, tzinfo=timezone.utc))
    assert abs(lat - 23.44) < 0.01 and abs(lon - 54.45) < 0.05
    lat, lon = sun.subsolar_point(datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc))
    assert abs(lat) < 0.01 and abs(lon + 39.65) < 0.05
    # 12:00 UTC: długość = −(równanie czasu)/4; 3.11 równanie czasu ok. +16,5 min, więc słońce ok. 4,1° na zachód
    _, eqt = sun.solar_position(datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc))
    lat, lon = sun.subsolar_point(datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc))
    assert abs(eqt - 16.49) < 0.1 and abs(lon - (-eqt / 4)) < 1e-9 and abs(lon + 4.11) < 0.05
    # wzorzec PyEphem: 21.12.2026 20:50 UTC
    lat, lon = sun.subsolar_point(datetime(2026, 12, 21, 20, 50, tzinfo=timezone.utc))
    assert abs(lat + 23.437) < 0.01 and abs(lon + 132.938) < 0.05


def test_elevation_and_state():
    noon = sun.sun_day(*EPWA, date(2026, 6, 21))["noon"]
    # w południe przesilenia: 90 − 52,17 + 23,44
    assert abs(sun.elevation(*EPWA, noon) - (90 - 52.1657 + 23.438)) < 0.05
    assert sun.state(*EPWA, datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)) == "day"
    assert sun.state(*EPWA, datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc)) == "civil"
    assert sun.state(*EPWA, datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)) == "night"


def test_polish_time():
    assert sun.polish_time(datetime(2026, 10, 15, 5, 1, tzinfo=timezone.utc)) == {"hm": "07:01", "tz": "CEST"}
    # 25.10.2026 01:00 UTC koniec czasu letniego
    assert sun.polish_time(datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc)) == {"hm": "06:00", "tz": "CET"}


def test_report_today_tomorrow_and_next():
    now = datetime(2026, 10, 15, 23, 0, tzinfo=timezone.utc)
    r = sun.report(*KSFO, now=now)
    assert [d["date"] for d in r["days"]] == ["2026-10-15", "2026-10-16"]
    assert r["state"] == "day" and r["days"][0]["sunset"].startswith("2026-10-16T01:3")
    assert r["next"]["event"] == "sunset" and r["next"]["local"] is None
    assert 600 < r["days"][0]["day_length"] < 700 and "local" not in r["days"][0]
    p = sun.report(*EPWA, now=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc), polish=True)
    assert p["days"][0]["local"]["sunrise"] == {"hm": "07:01", "tz": "CEST"} and p["next"]["event"] == "sunset"
    assert p["days"][0]["local"]["noon"] == {"hm": "12:22", "tz": "CEST"}
    assert len(p["subsolar"]) == 2
    polar = sun.report(*ENSB, now=datetime(2026, 12, 21, 12, 0, tzinfo=timezone.utc))
    assert polar["days"][0]["polar"] == "night" and polar["days"][0]["day_length"] == 0 and polar["next"] is None
    assert sun.report(*ENSB, now=datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc))["days"][0]["day_length"] == 1440


def test_report_upcoming_events():
    """Lista najbliższych zdarzeń (co najmniej doba naprzód): po zachodzie przeglądarka od razu pokazuje EECT."""
    r = sun.report(*EPWA, now=datetime(2026, 10, 15, 15, 39, tzinfo=timezone.utc), polish=True)
    up = r["upcoming"]
    assert [u["event"] for u in up[:5]] == ["sunset", "civil_dusk", "civil_dawn", "sunrise", "sunset"]
    assert r["next"] == up[0] and [u["at"] for u in up] == sorted(u["at"] for u in up) and len(up) == 8
    assert all(u["at"] > r["now"] for u in up) and up[1]["local"]["tz"] == "CEST"
    # daleko na zachód (doba lokalna od 11:20 UTC): o 02:00 UTC najbliższy jest zachód z doby "wczorajszej"
    w = sun.report(70.0, -170.0, now=datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc))["upcoming"]
    assert w[0]["event"] == "sunset" and w[0]["at"].startswith("2026-10-15T03:")
    assert sun.report(*ENSB, now=datetime(2026, 12, 21, 12, 0, tzinfo=timezone.utc))["upcoming"] == []


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_sun_endpoint(client):
    r = client.get("/api/meteo/sun", params={"icao": "epwa"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["icao"] == "EPWA" and d["polish"] is True and abs(d["lat"] - 52.17) < 0.05
    assert len(d["days"]) == 2 and d["days"][0]["local"]["sunrise"]["tz"] in ("CET", "CEST")
    assert d["state"] in ("day", "civil", "night")
    p = client.get("/api/meteo/sun", params={"lat": 35.55, "lon": 139.78}).json()
    assert p["icao"] is None and p["polish"] is False and "local" not in p["days"][0]
    assert client.get("/api/meteo/sun", params={"icao": "ZZZZ"}).status_code == 404
    assert client.get("/api/meteo/sun", params={"icao": "EP/A"}).status_code == 400
    assert client.get("/api/meteo/sun").status_code == 400
    assert client.get("/api/meteo/sun", params={"lat": 95, "lon": 0}).status_code == 422


def test_aerodrome_status_keeps_sun_box_keys(client):
    st = client.get("/api/aerodromes/EPWA/status")
    if st.status_code != 200:
        pytest.skip("brak lotniska EPWA w bazie testowej")
    s = st.json()["sun"]
    for k in ("sunrise", "sunset", "civil_dawn", "civil_dusk"):
        assert len(s[k]) == 5 and s[k][2] == ":"
    assert isinstance(s["day"], bool) and s["sunrise_at"].endswith("Z")
