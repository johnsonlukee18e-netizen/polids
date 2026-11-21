"""0.14.2 (issue #35, właściciel projektu: "DO FMP dodaj opcję scenario preview oraz listę scenariuszy aktywnych
i nieaktywnych"): backend widoku SCENARIOS w OTHER › FMP. Okna activationPeriods (żywe dane z 21.11.2026: daty ISO)
w times scenariusza, scenarios_ok w /api/viff/sectors (brak listy ≠ pusta lista) i straż: aplikacja tylko czyta
z vIFF (GET). Podgląd scenariusza liczy przeglądarka; endpoint podglądu vIFF jest POST i zmienia stan sieci, więc
ani kod, ani zapytania nie mogą go użyć.

Przegląd 0.14.2: active = isActive z vIFF (scenariusz obowiązuje teraz), enabled = pole active (włączony); okres
activationPeriods o długości doby lub dłuższy z datą końca (to_date)."""
import ast
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone

import httpx

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

from backend.app.config import ROOT_DIR  # noqa: E402
from backend.app.services import http_cache, viff  # noqa: E402

NOW = datetime(2026, 11, 21, 14, 30, tzinfo=timezone.utc)
REAL_CLIENT = httpx.AsyncClient

# kształt żywej odpowiedzi GET /etfms/scenarios?filter=EP&active=false (21.11.2026), skrócony
LIVE = [
    {"_id": "1", "id": "EP-1X", "__v": 0, "active": False, "isActive": False, "positions": "EPWW_ALL_CTR", "anypositions": "",
     "nopositions": "EPWW_S_CTR,EPWW_J_CTR,EPWW_N_CTR,EPWW_D*_CTR", "trafficVolumes": [["EP-ALLFIR", 21, 52]],
     "useBookedPositions": True, "airports": [], "description": "ALLFIR SOLO", "activationPeriods": [],
     "bookingEndBufferMinutes": 0, "isLive": False},
    {"_id": "2", "id": "EP-KKTMA", "__v": 0, "active": True, "isActive": False, "positions": "", "anypositions": "EPKK_APP",
     "nopositions": "", "trafficVolumes": [["EP-KKTMA", 17, 999], ["EP-KKTMAD", 8, 999]], "useBookedPositions": True,
     "airports": [], "description": "test", "isLive": False, "bookingEndBufferMinutes": 0,
     "activationPeriods": [{"type": "date", "bookingFlag": 1, "start": "2026-11-21T19:00:00.000Z",
                            "end": "2026-11-21T21:00:00.000Z"}]},
    {"_id": "3", "id": "EP-WATMA", "__v": 0, "active": False, "isActive": False, "positions": "", "anypositions": "EPWA_APP",
     "nopositions": "", "trafficVolumes": [["EP-WATMA", 20, 999], ["EP-WATMAD", 15, 999]], "useBookedPositions": False,
     "airports": [], "description": "test", "activationPeriods": []},
]


def test_activation_periods_in_times():
    s = {x["id"]: viff.scenario(x) for x in LIVE}
    # okres z datami ISO = okno z datą, jak oneTimes; pusta lista = bez okna
    assert s["EP-KKTMA"]["times"] == [{"from": "1900", "to": "2100", "date": "2026-11-21"}]
    assert s["EP-1X"]["times"] == [] and s["EP-WATMA"]["times"] == []
    # warunki jak w odpowiedzi: wzorzec "EPWW_D*_CTR" zostaje (FMP porównuje go ze znakami konfiguracji)
    assert s["EP-1X"]["nopositions"] == ["EPWW_S_CTR", "EPWW_J_CTR", "EPWW_N_CTR", "EPWW_D*_CTR"]
    assert s["EP-1X"]["tvs"] == [{"id": "EP-ALLFIR", "occupancy_cap": 21, "entries_cap": 52}]
    assert s["EP-KKTMA"]["tvs"][1] == {"id": "EP-KKTMAD", "occupancy_cap": 8, "entries_cap": None}
    # okres przez północ: data początku; godziny "HHMM" bez daty; śmieci pominięte
    assert viff._periods([{"start": "2026-11-21T23:00:00Z", "end": "2026-11-22T01:00:00Z"}, {"start": "0600", "end": "0900"},
                          {"start": "2026-11-21", "end": "2026-11-22"}, {"start": "x"}, "x", None]) == [
        {"from": "2300", "to": "0100", "date": "2026-11-21"}, {"from": "0600", "to": "0900", "date": None}]
    assert viff._periods(None) == [] and viff._periods({"start": "0600"}) == []
    # przegląd 0.14.2: okres o długości doby lub dłuższy z datą końca (26 h też, nie tylko różnica dat > 1 dzień); krótszy
    # (także przez północ) bez to_date, jak wyżej
    assert viff._periods([{"start": "2026-11-21T19:00:00Z", "end": "2026-11-23T21:00:00Z"},
                          {"start": "2026-11-21T19:00:00.000Z", "end": "2026-11-22T21:00:00.000Z"},
                          {"start": "2026-11-21T19:00:00Z", "end": "2026-11-22T19:00:00Z"},
                          {"start": "2026-11-21T19:00:00Z", "end": "2026-11-22T18:59:00Z"}]) == [
        {"from": "1900", "to": "2100", "date": "2026-11-21", "to_date": "2026-11-23"},
        {"from": "1900", "to": "2100", "date": "2026-11-21", "to_date": "2026-11-22"},
        {"from": "1900", "to": "1900", "date": "2026-11-21", "to_date": "2026-11-22"},
        {"from": "1900", "to": "1859", "date": "2026-11-21"}]
    # times, oneTimes i activationPeriods razem
    both = viff.scenario({"id": "EP-X", "times": [[1, [], "1600", "2200"]], "oneTimes": [["2026-11-22", "0600", "0700"]],
                          "activationPeriods": [{"start": "2026-11-21T19:00:00.000Z", "end": "2026-11-21T21:00:00.000Z"}]})
    assert [(t["from"], t["to"], t["date"]) for t in both["times"]] == [
        ("1600", "2200", None), ("0600", "0700", "2026-11-22"), ("1900", "2100", "2026-11-21")]


def test_active_is_in_effect_flag():
    """Przegląd 0.14.2: żywy EP-KKTMA (active=true, isActive=false, okno 19:00–21:00Z jeszcze przed sobą) nie jest
    aktywny teraz, tylko włączony; active z pola active wyłącznie w rekordzie bez klucza isActive; isLive pomijamy."""
    kk = viff.scenario(LIVE[1])
    assert kk["active"] is False and kk["enabled"] is True
    assert [(viff.scenario(x)["active"], viff.scenario(x)["enabled"]) for x in (LIVE[0], LIVE[2])] == [(False, False)] * 2
    flags = [{"active": True}, {"active": False}, {"active": False, "isActive": True}, {"active": True, "isActive": True},
             {"isActive": True}, {"active": True, "isActive": None}, {"active": False, "isActive": False, "isLive": True}, {}]
    assert [(viff.scenario({"id": "X", **f})["active"], viff.scenario({"id": "X", **f})["enabled"]) for f in flags] == [
        (True, True), (False, False), (True, False), (True, True), (True, False), (False, True), (False, False), (False, False)]


def _recording_client(monkeypatch, calls, scenarios=LIVE):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.url.params)))
        body = {"/etfms/scenarios": scenarios, "/etfms/trafficVolumes": [], "/etfms/airspaces": {}}.get(request.url.path)
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404, text="not found")

    class Recording(REAL_CLIENT):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(http_cache.httpx, "AsyncClient", Recording)


def test_scenarios_read_with_get_only(monkeypatch):
    """Lista scenariuszy i tabela FMP to same zapytania GET; podglądu (POST /etfms/scenarios/{id}/preview) ani innych
    endpointów zapisujących nie ma wśród zapytań."""
    calls = []
    _recording_client(monkeypatch, calls)
    http_cache.clear_cache()
    try:
        scns = asyncio.run(viff.scenarios())
        d = asyncio.run(viff.sectors("EP", NOW))
    finally:
        http_cache.clear_cache()
    # aktywne na początku; przegląd 0.14.2: żaden nie obowiązuje teraz (EP-KKTMA tylko włączony), więc po id
    assert [s["id"] for s in scns] == ["EP-1X", "EP-KKTMA", "EP-WATMA"]
    assert d["scenarios_ok"] is True and [s["id"] for s in d["scenarios"]] == ["EP-1X", "EP-KKTMA", "EP-WATMA"]
    assert [(s["active"], s["enabled"]) for s in d["scenarios"]] == [(False, False), (False, True), (False, False)]
    assert calls and {m for m, _, _ in calls} == {"GET"}
    assert ("GET", "/etfms/scenarios", {"filter": "EP", "active": "false"}) in calls
    assert not any("preview" in p.lower() or p.lower() in ("/etfms/fetchscenarios", "/etfms/addscenario") for _, p, _ in calls)
    # TV ze scenariuszy w tabeli FMP, z przepustowością scenariusza tylko jako zapasem
    by = {s["id"]: s for s in d["sectors"]}
    assert {"EP-ALLFIR", "EP-KKTMA", "EP-KKTMAD", "EP-WATMA", "EP-WATMAD"} <= set(by)
    assert by["EP-KKTMA"]["scenarios"] == ["EP-KKTMA"] and by["EP-KKTMA"]["occupancy_cap"] == 17
    # przegląd 0.14.2: TV samego włączonego scenariusza nie jest aktywny (tabela SECTORS w OTHER › FMP, MAP)
    assert by["EP-KKTMA"]["active"] is False and by["EP-KKTMAD"]["active"] is False
    json.dumps(d)


def test_sector_active_follows_scenario_in_effect(monkeypatch):
    """Przegląd 0.14.2: TV jest aktywny przez scenariusz tylko, gdy scenariusz obowiązuje teraz (isActive), bez względu
    na pole active (włączony); aktywne TV i scenariusze na początku."""
    calls = []
    now = [{**LIVE[1], "isActive": True}, {**LIVE[2], "active": True}, LIVE[0]]
    _recording_client(monkeypatch, calls, scenarios=now)
    http_cache.clear_cache()
    try:
        d = asyncio.run(viff.sectors("EP", NOW))
    finally:
        http_cache.clear_cache()
    by = {s["id"]: s for s in d["sectors"]}
    assert [(s["id"], s["active"], s["enabled"]) for s in d["scenarios"]] == [
        ("EP-KKTMA", True, True), ("EP-1X", False, False), ("EP-WATMA", False, True)]
    assert by["EP-KKTMA"]["active"] and by["EP-KKTMAD"]["active"]
    assert not by["EP-WATMA"]["active"] and not by["EP-WATMAD"]["active"] and not by["EP-ALLFIR"]["active"]
    assert [s["id"] for s in d["sectors"]][:2] == ["EP-KKTMA", "EP-KKTMAD"]


def test_scenarios_unavailable_flag(monkeypatch):
    calls = []
    _recording_client(monkeypatch, calls, scenarios=None)   # HTTP 404 z /etfms/scenarios
    http_cache.clear_cache()
    try:
        d = asyncio.run(viff.sectors("EP", NOW))
    finally:
        http_cache.clear_cache()
    assert d["scenarios"] == [] and d["scenarios_ok"] is False and d["sectors"] == []
    # pusta lista z serwera to nie błąd
    calls.clear()
    _recording_client(monkeypatch, calls, scenarios=[])
    try:
        d = asyncio.run(viff.sectors("EP", NOW))
    finally:
        http_cache.clear_cache()
    assert d["scenarios"] == [] and d["scenarios_ok"] is True


WRITE_METHODS = {"post", "put", "patch", "delete"}


def _code_calls(path):
    """Wywołania metod HTTP, napisy z nazwą metody zapisującej i argumenty method= w kodzie (bez docstringów)."""
    tree = ast.parse(path.read_text("utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in WRITE_METHODS | {"request", "stream", "send"}:
            bad.append(f"call .{n.func.attr}()")
        if isinstance(n, ast.keyword) and n.arg == "method":
            bad.append("method=")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs \
                and n.value.strip().lower() in WRITE_METHODS:
            bad.append(repr(n.value))
    return bad


def test_viff_code_has_no_write_calls():
    for rel in ("backend/app/services/viff.py", "backend/app/routers/viff.py", "backend/app/services/http_cache.py"):
        assert _code_calls(ROOT_DIR / rel) == [], rel
    # http_cache pobiera wyłącznie przez client.get
    src = (ROOT_DIR / "backend/app/services/http_cache.py").read_text("utf-8")
    assert "client.get(url, params=params)" in src
    # strona FMP pyta tylko o /api/... (api() bez opcji = GET), bez adresu vIFF i bez podglądu z serwera vIFF
    fmp = (ROOT_DIR / "frontend/js/fmp.js").read_text("utf-8")
    assert "viffsys" not in fmp and "method:" not in fmp and '"POST"' not in fmp and "/preview" not in fmp
