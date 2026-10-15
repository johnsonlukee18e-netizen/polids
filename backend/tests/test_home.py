"""HOME (0.12.3, issue #13): rating zalogowanego kontrolera, jego połączenie i rezerwacje w VATSIM (/api/vatsim/me),
wybór stanowiska wspólny z AERODROME › OVERVIEW, przycisk przejścia tam przed sesją, wersja i AIRAC na dole."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.routers import vatsim as vatsim_api  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402
from backend.app.services.vatsim import user_bookings, user_connections  # noqa: E402

FRONTEND = ROOT_DIR / "frontend"
CID = "1234567"
NOW = datetime.now(timezone.utc)


def _t(hours):
    return (NOW + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


FEED = {"general": {"update_timestamp": "2026-10-15T12:00:00Z"}, "pilots": [],
        "controllers": [
            # EuroScope: skrócony znak na częstotliwości sektora EPWW_DBT_CTR z pliku .ese
            {"cid": int(CID), "name": "Jan Kowalski", "callsign": "EPWW_CTR", "frequency": "127.025", "facility": 6,
             "rating": 4, "logon_time": "2026-10-15T10:12:30.0000000Z"},
            {"cid": int(CID), "name": "Jan Kowalski", "callsign": "EPKK_OBS", "frequency": "199.998", "facility": 0,
             "rating": 4, "logon_time": "2026-10-15T09:00:00Z"},
            {"cid": 7654321, "name": "Ktoś Inny", "callsign": "EPWA_APP", "frequency": "128.805", "facility": 5,
             "rating": 5, "logon_time": "2026-10-15T08:00:00Z"}],
        "atis": [{"cid": int(CID), "name": "Jan Kowalski", "callsign": "EPWA_ATIS", "frequency": "120.455", "facility": 4,
                  "logon_time": "2026-10-15T10:13:00Z", "atis_code": "K", "text_atis": ["WARSAW INFORMATION K"]}]}
BOOKINGS = [
    {"id": 1, "cid": int(CID), "type": "booking", "callsign": "EPWA_TWR", "start": _t(6), "end": _t(8)},
    {"id": 2, "cid": int(CID), "type": "event", "callsign": "EDDB_TWR", "start": _t(-1), "end": _t(1)},   # trwa
    {"id": 3, "cid": int(CID), "type": "booking", "callsign": "EPKK_APP", "start": _t(-5), "end": _t(-3)},  # minęła
    {"id": 4, "cid": int(CID), "type": "booking", "callsign": "EPGD_TWR", "start": _t(30), "end": _t(32)},  # za 30 h
    {"id": 5, "cid": 7654321, "type": "booking", "callsign": "EPWA_APP", "start": _t(1), "end": _t(2)},     # inny CID
]


def test_user_connections_and_bookings():
    online = user_connections(FEED, CID)
    # najpierw stanowisko, potem obserwator i ATIS; inne CID-y pominięte; CID z feedu to liczba, z sesji napis
    assert [c["callsign"] for c in online] == ["EPWW_CTR", "EPKK_OBS", "EPWA_ATIS"]
    assert online[0] == {"callsign": "EPWW_CTR", "frequency": "127.025", "name": "Jan Kowalski", "cid": int(CID),
                         "rating": 4, "logon_time": "2026-10-15T10:12:30.0000000Z", "text_atis": None,
                         "atis_code": None, "facility": 6}
    assert user_connections({"controllers": None, "atis": [None, "x"]}, CID) == []
    books = user_bookings(BOOKINGS, int(CID), now=NOW)
    # trwająca i dzisiejsza; skończona, za 30 h i cudza nie
    assert [(b["callsign"], b["type"], b["active"]) for b in books] == [("EDDB_TWR", "event", True),
                                                                        ("EPWA_TWR", "booking", False)]
    assert set(books[0]) == {"callsign", "cid", "type", "start", "end", "active"}
    assert [b["callsign"] for b in user_bookings(BOOKINGS, CID, now=NOW, hours=48)] == ["EDDB_TWR", "EPWA_TWR",
                                                                                         "EPGD_TWR"]


@pytest.fixture(scope="module")
def app_client():
    with TestClient(main.app) as c:   # lifespan: baza ze stanowiskami .ese (dopasowanie EPWW_CTR → EPWW_DBT_CTR)
        yield c


@pytest.fixture
def client(app_client, monkeypatch, state):
    async def feed():
        return FEED

    async def bookings():
        return BOOKINGS
    monkeypatch.setattr(vatsim_api, "get_feed", feed)
    monkeypatch.setattr(vatsim_api, "get_bookings", bookings)
    app_client.cookies.clear()
    yield app_client
    app_client.cookies.clear()


def _login(c, monkeypatch, cid=CID):
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "auth_admin_cids", cid)
    r = c.post("/auth/dev", data={"cid": cid, "name": "Jan Kowalski", "rating": 4, "division": "EUD",
                                  "subdivision": "POL", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_vatsim_me_without_login(client):
    # tryb lokalny (none): nie wiadomo, kto to, więc nic z sieci
    assert client.get("/api/vatsim/me").json() == {"cid": None, "online": [], "bookings": [], "updated": None,
                                                    "error": None, "online_error": None, "bookings_error": None}


def test_vatsim_me_logged_in(client, monkeypatch):
    _login(client, monkeypatch)
    me = client.get("/auth/me").json()["user"]
    assert me["rating"] == 4 and me["rating_short"] == "S3"
    d = client.get("/api/vatsim/me").json()
    assert d["cid"] == CID and d["error"] is None and d["updated"] == "2026-10-15T12:00:00Z"
    # EPWW_CTR na 127.025 to EPWW_DBT_CTR z pliku .ese (jak w EuroScope); ATIS EPWA też jest w .ese
    assert [(c["callsign"], c["position"]) for c in d["online"]] == [("EPWW_CTR", "EPWW_DBT_CTR"), ("EPKK_OBS", None),
                                                                     ("EPWA_ATIS", "EPWA_ATIS")]
    assert d["online"][0]["logon_time"].startswith("2026-10-15T10:12") and d["online"][0]["rating"] == 4
    assert [b["callsign"] for b in d["bookings"]] == ["EDDB_TWR", "EPWA_TWR"]


def test_vatsim_me_upstream_errors(client, monkeypatch):
    """Awaria data feed albo rezerwacji: bez 500, zostaje druga część i komunikat."""
    _login(client, monkeypatch)

    async def down():
        raise UpstreamError("data.vatsim.net: timeout")

    async def broken():
        return {"general": {}, "controllers": [{"cid": int(CID), "callsign": None, "frequency": None}], "atis": "x"}

    monkeypatch.setattr(vatsim_api, "get_feed", down)
    d = client.get("/api/vatsim/me").json()
    assert d["online"] == [] and "data feed" in d["online_error"] and d["error"] == d["online_error"]
    assert d["bookings_error"] is None and [b["callsign"] for b in d["bookings"]] == ["EDDB_TWR", "EPWA_TWR"]

    monkeypatch.setattr(vatsim_api, "get_bookings", down)
    d = client.get("/api/vatsim/me").json()
    assert d["online"] == [] and d["bookings"] == [] and "bookings" in d["bookings_error"]
    assert d["error"] == d["online_error"] + " · " + d["bookings_error"]

    async def bad_json():
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(vatsim_api, "get_feed", broken)
    monkeypatch.setattr(vatsim_api, "get_bookings", bad_json)
    r = client.get("/api/vatsim/me")
    assert r.status_code == 200
    d = r.json()
    assert d["bookings"] == [] and "Expecting value" in d["bookings_error"]
    # wpis bez znaku i "atis" nie-listą: pominięte, bez błędu
    assert d["online"] == [] and d["online_error"] is None

    async def as_list():
        return []          # JSON innego kształtu (lista zamiast obiektu): komunikat, nie 500
    monkeypatch.setattr(vatsim_api, "get_feed", as_list)
    d = client.get("/api/vatsim/me").json()
    assert d["online"] == [] and d["online_error"].startswith("VATSIM data feed niedostępny")


# --- frontend: czyste funkcje HOME w Node -----------------------------------------------------------------------
NODE_SCRIPT = r"""
const home = await import(process.argv[2]);
const now = new Date("2026-10-15T12:00:00Z");
const list = [
  { callsign: "EPWW_DBT_CTR", goto: null }, { callsign: "EPWA_APP", goto: null },
  { callsign: "EPWA_TWR", goto: "EPWA" }, { callsign: "EPKK_TWR", goto: "EPKK" },
];
const on = (callsign, extra = {}) => ({ callsign, frequency: "127.025", logon_time: "2026-10-15T10:12:30Z", facility: 6, ...extra });
const bk = (callsign, start, end, extra = {}) => ({ callsign, start, end, type: "booking", active: false, ...extra });
console.log(JSON.stringify({
  posKey: home.POS_KEY,
  rating: [
    { rating: 4, rating_short: "S3" }, { rating: 1 }, { rating: -1 }, { rating: 12, rating_short: "ADM" },
    { rating_short: "C1" }, { rating: 99, rating_short: "XX" }, { rating: 99 }, null, { rating: "constructor" },
  ].map(home.ratingText),
  airac: [
    { ident: "2610", effective: "2026-10-01", next: "2026-10-29" },
    { ident: "2613", effective: "2026-12-24", next: "2027-01-21" },
    { ident: "2602", effective: "2026-02-19", next: "2026-03-19" },
    { ident: "2610", effective: "2026-10-01" }, {}, null,
  ].map(home.airacText),
  hm: ["2026-10-15T10:12:30.0000000Z", "2026-10-15T23:59:59Z", "", null, "nonsense"].map(home.utcHm),
  booking: [
    bk("EPWA_TWR", "2026-10-15T18:00:00+00:00", "2026-10-15T20:00:00+00:00"),
    bk("EPWA_TWR", "2026-10-16T08:00:00+00:00", "2026-10-16T10:00:00+00:00"),
    bk("EDDB_TWR", "2026-10-15T11:00:00+00:00", "2026-10-15T13:00:00+00:00", { type: "event", active: true }),
  ].map((b) => home.bookingText(b, now)),
  online: [on("EPWW_DBT_CTR"), on("EPWA_ATIS", { frequency: "120.455", facility: 4, atis_code: "K" }),
           on("EPKK_OBS", { facility: 0 }), on("EPWA_APP", { logon_time: null, frequency: "" })].map(home.onlineText),
  listed: [
    ["EPWW_DBT_CTR"], ["EPWW_CTR", "EPWW_DBT_CTR"], ["EPWW_CTR", null], ["EPWA__APP"], ["EPWA_GND"],
    ["EPWA_N_TWR"], ["EPKK_DEL"], ["EPGD_TWR"], ["EDDB_TWR"], [""], [null],
  ].map(([cs, alt]) => home.listedPosition(cs, list, alt)),
  initial: [
    {},
    { list },
    { list, stored: "EPWA_APP" },
    { list, stored: "EPWA_TWR", bookings: [bk("EPWW_DBT_CTR", "2026-10-15T18:00:00+00:00", "2026-10-15T20:00:00+00:00")] },
    { list, stored: "", bookings: [bk("EDDB_TWR", "2026-10-15T13:00:00+00:00", "x"),
                                   bk("EPKK_GND", "2026-10-15T19:00:00+00:00", "x"),
                                   bk("EPWA_APP", "2026-10-15T14:00:00+00:00", "x")] },
    { list, stored: "GONE_CTR", bookings: [bk("EPWA_APP", "2026-10-15T14:00:00+00:00", "x")] },
    { list, stored: "EPWA_APP", online: [on("EPWW_CTR", { position: "EPWW_DBT_CTR" })] },
    { list, stored: "EPWA_APP", online: [on("EPWA_ATIS", { facility: 4 }), on("EPKK_OBS", { facility: 0 })] },
    { list, online: [on("EDDB_TWR")], bookings: [bk("EPWA_TWR", "2026-10-15T18:00:00+00:00", "x")] },
  ].map(home.initialPosition),
  target: [null, list[0], list[2]].map(home.sessionTarget),
  hello: home.greeting({ user: { cid: "1234567", name: "Jan Kowalski", rating: 4 } }),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "home.mjs").write_text((FRONTEND / "js" / "tabs" / "home.js").read_text("utf-8")
                                .replace('"../api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "home.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_rating_text(js):
    assert js["rating"] == ["S3 · Senior Student", "OBS · Pilot/Observer", "INA · Inactive", "ADM · Administrator",
                            "C1 · Enroute Controller", "XX", "", "", ""]


def test_airac_text(js):
    # ostatni dzień cyklu = dzień przed następnym (także przez koniec roku i luty)
    assert js["airac"] == ["AIRAC 2610 · 01.10.2026 – 28.10.2026", "AIRAC 2613 · 24.12.2026 – 20.01.2027",
                           "AIRAC 2602 · 19.02.2026 – 18.03.2026", "AIRAC 2610 · od 01.10.2026", "", ""]


def test_times_and_lines(js):
    assert js["hm"] == ["10:12Z", "23:59Z", "", "", ""]
    assert js["booking"] == ["Rezerwacja: EPWA_TWR 18:00–20:00Z", "Rezerwacja: EPWA_TWR 16.10 08:00–10:00Z",
                             "Rezerwacja: EDDB_TWR 11:00–13:00Z (event) · trwa"]
    assert js["online"] == ["Jesteś zalogowany na VATSIM jako EPWW_DBT_CTR (127.025) od 10:12Z",
                            "ATIS EPWA_ATIS (120.455) od 10:12Z · litera K",
                            "Jesteś zalogowany na VATSIM jako obserwator (EPKK_OBS) od 10:12Z",
                            "Jesteś zalogowany na VATSIM jako EPWA_APP"]
    assert js["hello"] == "Witaj, Jan Kowalski (1234567)"


def test_listed_position(js):
    # znak z sieci → stanowisko z listy OVERVIEW: dokładny, dopasowany przez serwer, zastępstwo "__", wieża lotniska
    assert js["listed"] == ["EPWW_DBT_CTR", "EPWW_DBT_CTR", "", "EPWA_APP", "EPWA_TWR", "EPWA_TWR", "EPKK_TWR", "", "",
                            "", ""]


def test_initial_position(js):
    assert js["initial"] == [
        {"callsign": "", "source": None},
        {"callsign": "", "source": None},
        {"callsign": "EPWA_APP", "source": "stored"},
        # zapisany wybór wygrywa z rezerwacją; bez wyboru najwcześniejsza rezerwacja stanowiska z listy
        {"callsign": "EPWA_TWR", "source": "stored"},
        {"callsign": "EPWA_APP", "source": "booking"},
        {"callsign": "EPWA_APP", "source": "booking"},
        # zalogowany w sieci: jego stanowisko, nawet gdy coś zapisano; ATIS i obserwator to nie stanowiska
        {"callsign": "EPWW_DBT_CTR", "source": "online"},
        {"callsign": "EPWA_APP", "source": "stored"},
        {"callsign": "EPWA_TWR", "source": "booking"},
    ]


def test_session_target(js):
    assert js["target"] == [{"arg": "0", "label": "PRZYGOTUJ SESJĘ → AERODROME OVERVIEW"},
                            {"arg": "0", "label": "PRZYGOTUJ SESJĘ → AERODROME OVERVIEW"},
                            {"arg": "EPWA", "label": "PRZYGOTUJ SESJĘ → AERODROME EPWA"}]


def test_home_shares_position_with_overview(js):
    """HOME zapisuje stanowisko pod kluczem OVERVIEW, a otwarty już PRZEGLĄD czyta go ponownie przy każdym pokazaniu."""
    overview = (FRONTEND / "js" / "overview.js").read_text("utf-8")
    assert re.search(r'^const POS_KEY = "([^"]+)";$', overview, re.M).group(1) == js["posKey"]
    assert "sync() {" in overview and "const want = lsGet(POS_KEY)" in overview
    aerodrome = (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    assert 'if (mode === "ov" && ov) { ov.sync(); return; }' in aerodrome
    home = (FRONTEND / "js" / "tabs" / "home.js").read_text("utf-8")
    # przycisk: OVERVIEW (0) albo strona lotniska wieży; HOME importuje tylko api.js (test powłoki wczytuje go w Node)
    assert 'navigate("aerodrome", sessionTarget(current()).arg)' in home
    assert re.findall(r'^import .* from "([^"]+)";$', home, re.M) == ["../api.js"]
    # stopka: sama wersja i AIRAC
    assert "[ctx.config?.version, airacText(ctx.config?.airac)]" in home
