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
    # komunikat o data feed (tekst z routers/vatsim.py), nie 500
    assert d["online"] == [] and d["online_error"].startswith("VATSIM data feed ")


# --- frontend: czyste funkcje HOME w Node -----------------------------------------------------------------------
NODE_SCRIPT = r"""
// localStorage podstawiony przed pierwszym odczytem: `blocked` = tryb prywatny (każdy dostęp rzuca wyjątek)
const store = new Map([["overview.position", "EPWA_APP"]]);
let blocked = false;
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
  getItem(k) { if (blocked) throw new Error("SecurityError"); return store.has(k) ? store.get(k) : null; },
  setItem(k, v) { if (blocked) throw new Error("SecurityError"); store.set(k, String(v)); },
} });
const home = await import(process.argv[2]);
const ov = await import(process.argv[3]);
const api = await import(new URL("./api.mjs", process.argv[2]));
const now = new Date("2026-10-15T12:00:00Z");
const list = [
  { callsign: "EPWW_DBT_CTR", goto: null }, { callsign: "EPWA_APP", goto: null },
  { callsign: "EPWA_TWR", goto: "EPWA" }, { callsign: "EPKK_TWR", goto: "EPKK" },
];
const on = (callsign, extra = {}) => ({ callsign, frequency: "127.025", logon_time: "2026-10-15T10:12:30Z", facility: 6, ...extra });
const bk = (callsign, start, end, extra = {}) => ({ callsign, start, end, type: "booking", active: false, ...extra });

// HOME jak decide() i zmiana pola: kroki {net} (odpowiedź /api/vatsim/me, zostaje do następnej), {pick} (wybór ręczny
// w polu, zapisany), {shared} (wybór zmieniony w OVERVIEW tego okna, potem pokazanie HOME); wynik: wartość pola po kroku
const FEED_DOWN = { online: [], bookings: [], error: "VATSIM data feed unavailable: timeout", online_error: "VATSIM data feed unavailable: timeout" };
// loadNet: wyjątek z api() (serwer PolIDS nie odpowiada)
const NO_SERVER = { online: [], bookings: [], error: api.OFFLINE_MSG, online_error: api.OFFLINE_MSG, bookings_error: api.OFFLINE_MSG };
const ONLINE = { online: [on("EPWW_CTR", { position: "EPWW_DBT_CTR" })], bookings: [] };
const OFFLINE = { online: [], bookings: [] };
const BOOKED = { online: [], bookings: [bk("EPWA_TWR", "2026-10-15T18:00:00+00:00", "2026-10-15T20:00:00+00:00")] };
function homeRun(steps, seen = "") {
  let state = { seen, picked: false, appliedOnline: "" }, shared = seen, net = null, sel = "";
  const out = steps.map((s) => {
    if ("pick" in s) { state = { ...state, picked: true, seen: s.pick }; shared = s.pick; return (sel = s.pick); }
    if ("shared" in s) shared = s.shared;
    if ("net" in s) net = s.net;
    const { choose, ...next } = home.homeChoice(state, { net, shared, list });
    state = next;
    if (choose === "" || list.some((p) => p.callsign === choose)) sel = choose;
    return sel;
  });
  return { sel: out, applied: state.appliedOnline };
}

// wybór w pamięci okna: z localStorage przy pierwszym odczycie, potem drugie okno go nie zmienia; bez localStorage w pamięci
const choice = [api.choiceGet(api.POS_KEY)];
store.set(api.POS_KEY, "EPKK_APP");                         // drugie okno PolIDS zapisuje swój wybór
choice.push(api.choiceGet(api.POS_KEY));
api.choiceSet(api.POS_KEY, "EPGD_APP");
choice.push(api.choiceGet(api.POS_KEY), store.get(api.POS_KEY));
blocked = true;
choice.push(api.choiceGet("test.blocked"));
api.choiceSet("test.blocked", "EPKK_APP");
choice.push(api.choiceGet("test.blocked"));
// tryb prywatny: wybór w OVERVIEW, inna zakładka, ponowne pokazanie PRZEGLĄDU: filtr zostaje
const isFilter = (cs) => ["EPWW_DBT_CTR", "EPWA_APP", "EPKK_APP"].includes(cs);
const privateSync = ov.syncPosition({ seen: "EPKK_APP", position: "EPKK_APP", loaded: true }, api.choiceGet("test.blocked"), isFilter);
blocked = false;

console.log(JSON.stringify({
  posKey: api.POS_KEY,
  choice,
  privateSync,
  homeRuns: {
    feedDown: homeRun([{ net: ONLINE }, { pick: "EPWA_APP" }, { net: FEED_DOWN }, { net: ONLINE }]),
    noServer: homeRun([{ net: ONLINE }, { pick: "EPWA_APP" }, { net: NO_SERVER }, { net: ONLINE }]),
    relogin: homeRun([{ net: ONLINE }, { pick: "EPWA_APP" }, { net: OFFLINE }, { net: ONLINE }]),
    listFirst: homeRun([{ net: null }, { net: ONLINE }], "EPWA_APP"),
    listFirstBooked: homeRun([{ net: null }, { net: BOOKED }, { net: BOOKED }]),
    downAtStart: homeRun([{ net: { ...BOOKED, online_error: "x" } }, { net: ONLINE }, { net: ONLINE }]),
    fromOverview: homeRun([{ net: ONLINE }, { shared: "EPWA_APP" }, { net: ONLINE }, { shared: "GONE_CTR" }]),
    stored: homeRun([{ net: OFFLINE }, { net: BOOKED }, { net: OFFLINE }], "EPWA_APP"),
  },
  sync: [
    [{ seen: "EPKK_APP", position: "EPKK_APP", loaded: true }, "EPKK_APP"],   // nic nowego: filtr zostaje
    [{ seen: "EPWA_APP", position: "EPWA_APP", loaded: true }, "EPKK_APP"],   // nowy wybór w HOME
    [{ seen: "EPWA_APP", position: "EPWA_APP", loaded: true }, "EPWA_TWR"],   // wieża z HOME: filtr bez zmian
    [{ seen: "EPWA_TWR", position: "", loaded: true }, "EPWA_TWR"],            // wieża zapisana przy otwarciu: cały FIR zostaje
    [{ seen: "EPWA_APP", position: "EPWA_APP", loaded: true }, ""],           // HOME: wszystkie lotniska
    [{ seen: "EPWA_APP", position: "EPWA_APP", loaded: true }, "GONE_CTR"],   // spoza listy: bez zmian
    [{ seen: "EPWA_APP", position: "", loaded: false }, "EPKK_APP"],          // lista jeszcze się wczytuje
  ].map(([st, shared]) => ov.syncPosition(st, shared, isFilter)),
  listPos: ["EPWA_APP", "EPWA_TWR", "GONE_CTR", ""].map((cs) => ov.listPosition(cs, isFilter)),
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
    # overview.js bez METEO i checklisty (DOM): tylko czyste funkcje wspólnego stanowiska
    (d / "meteo.mjs").write_text("export const colorize = (x) => x; export const wxLines = (k, x) => x;\n", "utf-8")
    (d / "checklist.mjs").write_text("export const renderChecklist = () => {};\n", "utf-8")
    (d / "overview.mjs").write_text((FRONTEND / "js" / "overview.js").read_text("utf-8")
                                    .replace('"./api.js"', '"./api.mjs"').replace('"./tabs/meteo.js"', '"./meteo.mjs"')
                                    .replace('"./checklist.js"', '"./checklist.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "home.mjs").as_uri(), (d / "overview.mjs").as_uri()],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_rating_text(js):
    assert js["rating"] == ["S3 · Senior Student", "OBS · Pilot/Observer", "INA · Inactive", "ADM · Administrator",
                            "C1 · Enroute Controller", "XX", "", "", ""]


def test_airac_text(js):
    # ostatni dzień cyklu = dzień przed następnym (także przez koniec roku i luty)
    assert js["airac"] == ["AIRAC 2610 · 01.10.2026 – 28.10.2026", "AIRAC 2613 · 24.12.2026 – 20.01.2027",
                           "AIRAC 2602 · 19.02.2026 – 18.03.2026", "AIRAC 2610 · from 01.10.2026", "", ""]


def test_times_and_lines(js):
    assert js["hm"] == ["10:12Z", "23:59Z", "", "", ""]
    assert js["booking"] == ["Booking: EPWA_TWR 18:00–20:00Z", "Booking: EPWA_TWR 16.10 08:00–10:00Z",
                             "Booking: EDDB_TWR 11:00–13:00Z (event) · in progress"]
    assert js["online"] == ["You are connected to VATSIM as EPWW_DBT_CTR (127.025) since 10:12Z",
                            "ATIS EPWA_ATIS (120.455) since 10:12Z · information K",
                            "You are connected to VATSIM as an observer (EPKK_OBS) since 10:12Z",
                            "You are connected to VATSIM as EPWA_APP"]
    assert js["hello"] == "Welcome, Jan Kowalski (1234567)"


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
    assert js["target"] == [{"arg": "0", "label": "PREPARE SESSION → AERODROME OVERVIEW"},
                            {"arg": "0", "label": "PREPARE SESSION → AERODROME OVERVIEW"},
                            {"arg": "EPWA", "label": "PREPARE SESSION → AERODROME EPWA"}]


def test_home_choice_sequences(js):
    """Stanowisko w HOME przy kolejnych odświeżeniach VATSIM (co 60 s), wyborze ręcznym i zmianie w OVERVIEW."""
    runs = js["homeRuns"]
    # wybór ręczny zostaje mimo chwilowej awarii data feed albo serwera PolIDS; ten sam kontroler na tym samym
    # połączeniu po powrocie feedu nie dostaje z powrotem stanowiska z sieci
    assert runs["feedDown"] == {"sel": ["EPWW_DBT_CTR", "EPWA_APP", "EPWA_APP", "EPWA_APP"], "applied": "EPWW_DBT_CTR"}
    assert runs["noServer"] == runs["feedDown"]
    # wylogowanie (feed odpowiedział, nie ma go w sieci) i nowe zalogowanie: znowu stanowisko z sieci
    assert runs["relogin"] == {"sel": ["EPWW_DBT_CTR", "EPWA_APP", "EPWA_APP", "EPWW_DBT_CTR"], "applied": "EPWW_DBT_CTR"}
    # pole ustawione już po wczytaniu listy (zapisany wybór), zanim odpowie VATSIM
    assert runs["listFirst"]["sel"] == ["EPWA_APP", "EPWW_DBT_CTR"]
    assert runs["listFirstBooked"]["sel"] == ["", "EPWA_TWR", "EPWA_TWR"]
    # feed niedostępny przy otwarciu: rezerwacja; potem pierwsze zalogowanie widziane w sieci
    assert runs["downAtStart"] == {"sel": ["EPWA_TWR", "EPWW_DBT_CTR", "EPWW_DBT_CTR"], "applied": "EPWW_DBT_CTR"}
    # wybór z OVERVIEW tego okna wygrywa z siecią, na której już ustawiono stanowisko; spoza listy: pole bez zmian
    assert runs["fromOverview"]["sel"] == ["EPWW_DBT_CTR", "EPWA_APP", "EPWA_APP", "EPWA_APP"]
    # zapisany wybór wygrywa z rezerwacją także przy kolejnych odświeżeniach
    assert runs["stored"]["sel"] == ["EPWA_APP", "EPWA_APP", "EPWA_APP"]


def test_position_choice_is_per_window(js):
    """Wybór stanowiska w pamięci okna: z localStorage tylko przy pierwszym odczycie, bez localStorage też działa."""
    # drugie okno zapisało EPKK_APP: to okno zostaje przy swoim; zapis idzie też do localStorage (następne otwarcie)
    assert js["choice"] == ["EPWA_APP", "EPWA_APP", "EPGD_APP", "EPGD_APP", "", "EPKK_APP"]
    # tryb prywatny: filtr wybrany w OVERVIEW zostaje po powrocie z innej zakładki
    assert js["privateSync"] == {"seen": "EPKK_APP", "position": "EPKK_APP"}


def test_overview_sync_rules(js):
    """Otwarty PRZEGLĄD po ponownym pokazaniu: zmienia filtr tylko nowy wybór z HOME, który jest filtrem ACC / APP."""
    assert js["sync"] == [
        {"seen": "EPKK_APP", "position": "EPKK_APP"},
        {"seen": "EPKK_APP", "position": "EPKK_APP"},
        {"seen": "EPWA_TWR", "position": "EPWA_APP"},
        {"seen": "EPWA_TWR", "position": ""},
        {"seen": "", "position": ""},
        {"seen": "GONE_CTR", "position": "EPWA_APP"},
        {"seen": "EPKK_APP", "position": ""},
    ]
    # filtr po wczytaniu listy: wieża zapisana w HOME i stanowisko spoza listy to cały FIR
    assert js["listPos"] == ["EPWA_APP", "", "", ""]


def test_home_shares_position_with_overview(js):
    """HOME i OVERVIEW wymieniają stanowisko przez wybór w pamięci okna (choiceGet / choiceSet pod kluczem OVERVIEW)."""
    overview = (FRONTEND / "js" / "overview.js").read_text("utf-8")
    # jeden klucz w api.js (ten sam co dawniej, więc zapisany wybór zostaje); OVERVIEW, HOME i COORDINATION go importują
    assert js["posKey"] == "overview.position"
    assert re.search(r'^import \{[^}]*\bPOS_KEY\b[^}]*\} from "\./api\.js";$', overview, re.M)
    coordination = (FRONTEND / "js" / "tabs" / "coordination.js").read_text("utf-8")
    agreements = (FRONTEND / "js" / "agreements.js").read_text("utf-8")
    assert 'export { POS_KEY } from "./api.js";' in agreements
    # otwarty PRZEGLĄD: reguły syncPosition; filtr dopiero z listą stanowisk (bez niej wieża z HOME nie jest filtrem)
    assert "sync() {" in overview
    assert "syncPosition({ seen, position, loaded: posLoaded }, choiceGet(POS_KEY), listed)" in overview
    assert "position = listPosition(seen, listed);" in overview and 'let position = "";' in overview
    assert "choiceSet(POS_KEY, position);" in overview
    aerodrome = (FRONTEND / "js" / "tabs" / "aerodrome.js").read_text("utf-8")
    assert 'if (mode === "ov" && ov) { ov.sync(); return; }' in aerodrome
    home = (FRONTEND / "js" / "tabs" / "home.js").read_text("utf-8")
    assert "homeChoice(choice, { net, shared: choiceGet(POS_KEY), list })" in home
    assert re.search(r'^import \{[^}]*\bPOS_KEY\b[^}]*\} from "\.\./api\.js";$', home, re.M)
    # COORDINATION: stanowisko domyślne z tego samego wyboru okna (zachowanie: test_coord_tab_js.py)
    assert "defaultPosition(d.positions, choiceGet(POS_KEY))" in coordination
    # bez localStorage wprost: inaczej tryb prywatny i drugie okno PolIDS znowu zmieniałyby wybór
    for src in (overview, home, coordination, agreements):
        assert "lsGet(POS_KEY)" not in src and "lsSet(POS_KEY" not in src
        assert "const POS_KEY" not in src
    # przycisk: OVERVIEW (0) albo strona lotniska wieży, zapis dopiero z wczytaną listą (inaczej pusty wybór kasowałby
    # zapisany); HOME importuje tylko api.js (test powłoki wczytuje go w Node)
    assert re.search(r'if \(listLoaded\) save\(\);\s*navigate\("aerodrome", sessionTarget\(current\(\)\)\.arg\);', home)
    assert re.findall(r'^import .* from "([^"]+)";$', home, re.M) == ["../api.js"]
    # stopka: sama wersja i AIRAC
    assert "[ctx.config?.version, airacText(ctx.config?.airac)]" in home
