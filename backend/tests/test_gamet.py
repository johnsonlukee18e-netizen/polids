"""GAMET (services/gamet.py, /api/meteo/gamet, METEO › GAMET).

UWAGA: odpowiedzi poniżej są UŁOŻONE RĘCZNIE. Kształt JSON-a ({"EPWW": {"A1": {"gamets": [{"message", "messageHTML"}]}}})
odczytano z kodu strony awiacja.imgw.pl (dokumentacja lotu i zakładka GAMET), a nie z żywej odpowiedzi serwera
aviation-api.imgw.pl, który był nieosiągalny; treść komunikatów wg wzoru GAMET z Załącznika 3 ICAO i instrukcji IMGW."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services import gamet
from backend.app.services.http_cache import UpstreamError, clear_cache

NOW = datetime(2026, 10, 15, 6, 10, tzinfo=timezone.utc)
A1 = ("FAPL21 EPWA 150300\nEPWW GAMET VALID 150400/151000 EPWA-\nEPWW WARSAW FIR/A1 BLW FL100\nSECN I\n"
      "SFC WIND: 10/12 310/30KT\nSFC VIS: 04/08 N OF N54 3000 BR\nSIGWX: NIL\nSECN II\n"
      "PSYS: 06 L 1004HPA N5430 E01530 MOV NE 15KT WKN\nCLD: BKN 012/045 AGL\nFZLVL: 3500FT AMSL\n")
A2_HTML = ("FAPL22 EPWR 150300<br>EPWW GAMET VALID 150400/151000 EPWR-<br>EPWW WARSAW FIR/A2 BLW FL150<br>"
           "SECN I<br>MT OBSC: 04/10 SUDETY &amp; KARKONOSZE<br>SECN II<br>CLD: OVC 008/060 AGL</br>")
# ułożone ręcznie wg kodu awiacja.imgw.pl (nie z żywej odpowiedzi)
INFERRED = {"EPWW": {
    "A1": {"gamets": [{"message": A1, "messageHTML": A1.replace("\n", "<br>")}]},
    "A2": {"gamets": [{"messageHTML": A2_HTML}]},
    "A3": {"gamets": []},
    "A4": {"gamets": [{"message": "FAPL24 EPWA 150300\r\nEPWW GAMET VALID 150400/151000 EPWA-\r\nEPWW WARSAW FIR/A4 BLW FL 100\r\n"}]},
    "A5": {"gamets": [{"message": "EPWW GAMET VALID 302200/010400 EPKK-\nEPWW WARSAW FIR/A5 BLW FL150\n"}]},
}}


def test_parse_inferred_shape():
    out = gamet.parse(json.dumps(INFERRED), NOW)
    assert out["error"] is None and list(out["areas"]) == ["A1", "A2", "A3", "A4", "A5"]
    a1 = out["areas"]["A1"]
    assert a1["text"].startswith("FAPL21 EPWA 150300\nEPWW GAMET") and a1["text"].endswith("FZLVL: 3500FT AMSL")
    assert (a1["valid"], a1["valid_from"], a1["valid_to"]) == ("150400/151000", "2026-10-15T04:00Z", "2026-10-15T10:00Z")
    assert (a1["below"], a1["issued"]) == ("FL100", "2026-10-15T03:00Z")
    # sam messageHTML: <br> to nowa linia, encje zamienione, znaczniki usunięte
    a2 = out["areas"]["A2"]
    assert "SUDETY & KARKONOSZE" in a2["text"] and "<" not in a2["text"] and a2["below"] == "FL150"
    assert a2["text"].split("\n")[2] == "EPWW WARSAW FIR/A2 BLW FL150"
    assert out["areas"]["A3"]["text"] is None and out["areas"]["A3"]["valid"] is None
    assert out["areas"]["A4"]["below"] == "FL100" and "\r" not in out["areas"]["A4"]["text"]
    # przełom miesiąca: 30.09 22:00 – 01.10 04:00 widziane 15.10 (dzień 30 = poprzedni miesiąc)
    assert out["areas"]["A5"]["valid_from"] == "2026-09-30T22:00Z" and out["areas"]["A5"]["valid_to"] == "2026-10-01T04:00Z"


@pytest.mark.parametrize("doc", [
    {"gamet": INFERRED},                                   # opakowane w "gamet"
    [INFERRED],                                            # lista z jednym obiektem
    INFERRED["EPWW"],                                      # od razu rejony
    {"EPWW": {"A1": [{"message": A1}], "A2": A1}},         # lista komunikatów / sam tekst zamiast obiektu
    {"EPWW": {"A1": {"message": A1}}},                     # sam komunikat bez "gamets"
])
def test_parse_variants(doc):
    out = gamet.parse(json.dumps(doc), NOW)
    assert out["error"] is None and out["areas"]["A1"]["below"] == "FL100"


def test_parse_errors():
    assert "nie JSON" in gamet.parse("<html>502</html>", NOW)["error"]
    assert "brak rejonów" in gamet.parse(json.dumps({"metar": {}}), NOW)["error"]
    out = gamet.parse(json.dumps({"EPWW": {"A1": {"gamets": []}}}), NOW)
    assert out["error"] and set(out["areas"]) == {"A1", "A2", "A3", "A4", "A5"}


def _msg(valid: str, issued: str, area: str = "A1", extra: str = "") -> str:
    return (f"FAPL21 EPWA {issued}{extra}\nEPWW GAMET VALID {valid} EPWA-\nEPWW WARSAW FIR/{area} BLW FL100\n"
            "SECN I\nSFC VIS: 04/08 3000 BR\n")


OLD, NEW = _msg("150400/151000", "150300"), _msg("151000/151600", "150900")


@pytest.mark.parametrize("order", ["old-first", "new-first"])
def test_parse_picks_current_message(order):
    """Kilka komunikatów rejonu w jednej odpowiedzi (bez count serwer zwraca ostatnie komunikaty): pokazany ważny teraz,
    nie pierwszy z listy; kolejność w odpowiedzi bez znaczenia."""
    msgs = [{"message": OLD}, {"message": NEW}]
    doc = {"EPWW": {"A1": {"gamets": msgs if order == "old-first" else msgs[::-1]}}}
    at = lambda h, m: datetime(2026, 10, 15, h, m, tzinfo=timezone.utc)  # noqa: E731
    a1 = gamet.parse(json.dumps(doc), at(13, 30))["areas"]["A1"]
    assert (a1["valid"], a1["valid_to"], a1["issued"]) == ("151000/151600", "2026-10-15T16:00Z", "2026-10-15T09:00Z")
    # 09:30: nowy (wydany 09:00, ważny od 10:00) jeszcze nie obowiązuje, stary tak
    assert gamet.parse(json.dumps(doc), at(9, 30))["areas"]["A1"]["valid"] == "150400/151000"
    # 17:00: oba już nieważne, pokazany późniejszy
    assert gamet.parse(json.dumps(doc), at(17, 0))["areas"]["A1"]["valid"] == "151000/151600"
    # poprawka AMD w trakcie ważności: późniejszy początek ważności wygrywa; COR z tą samą ważnością: późniejsze wydanie
    amd = _msg("151200/151600", "151150", extra=" AMD")
    cor = _msg("151000/151600", "151020", extra=" COR")
    for msgs2 in ([NEW, amd, cor], [amd, cor, NEW], [cor, NEW]):
        a = gamet.pick(msgs2, at(13, 30))
        assert a["text"] == (amd if amd in msgs2 else cor)


def test_parse_list_of_snapshots():
    """Lista kilku migawek całej odpowiedzi (zamiast jednego obiektu): rejony ze wszystkich, w każdym komunikat ważny teraz."""
    now = datetime(2026, 10, 15, 13, 30, tzinfo=timezone.utc)
    doc = [{"EPWW": {"A1": {"gamets": [{"message": NEW}]}, "A2": {"gamets": []}}},
           {"EPWW": {"A1": {"gamets": [{"message": OLD}]}, "A2": {"gamets": [{"message": _msg("150400/151000", "150300", "A2")}]}}}]
    out = gamet.parse(json.dumps(doc), now)
    assert out["error"] is None and out["areas"]["A1"]["valid"] == "151000/151600"
    assert out["areas"]["A2"]["valid"] == "150400/151000" and out["areas"]["A3"]["text"] is None
    assert gamet.parse(json.dumps({"gamet": doc}), now)["areas"]["A1"]["valid"] == "151000/151600"


@pytest.fixture
def fresh(monkeypatch):
    clear_cache()
    monkeypatch.setattr(gamet, "_no_count", False)
    yield
    clear_cache()


def _status_error(code: int) -> UpstreamError:
    req = httpx.Request("GET", gamet.GAMET_URL)
    try:
        raise httpx.HTTPStatusError(f"HTTP {code}", request=req, response=httpx.Response(code, request=req))
    except httpx.HTTPStatusError as cause:
        try:
            raise UpstreamError(f"{gamet.GAMET_URL}: {cause}") from cause
        except UpstreamError as exc:
            return exc


def test_get_gamet_retries_without_count(fresh, monkeypatch):
    calls = []

    async def fetch(url, ttl, params=None, headers=None):
        calls.append((url, ttl, dict(params)))
        if "count" in params:
            raise _status_error(400)
        return json.dumps(INFERRED)

    monkeypatch.setattr(gamet, "fetch_text", fetch)
    monkeypatch.setattr(gamet, "peek", lambda url, params=None: (30.0, ""))
    out = asyncio.run(gamet.get_gamet(NOW))
    assert [c[2] for c in calls] == [gamet.PARAMS, gamet.PARAMS_NO_COUNT] and calls[0][1] == 600
    assert calls[0][0] == "https://aviation-api.imgw.pl/data/last"
    assert out["error"] is None and out["stale"] is False and out["fetched_at"] == "2026-10-15T06:09:30Z"
    assert out["source_url"] == "https://awiacja.imgw.pl/prognozy-lotnicze/gamet"
    # serwer odrzucił count: kolejne zapytanie od razu bez niego
    asyncio.run(gamet.get_gamet(NOW))
    assert [c[2] for c in calls[2:]] == [gamet.PARAMS_NO_COUNT]


def test_get_gamet_upstream_down_and_stale(fresh, monkeypatch):
    async def down(url, ttl, params=None, headers=None):
        raise _status_error(503)

    monkeypatch.setattr(gamet, "fetch_text", down)
    out = asyncio.run(gamet.get_gamet(NOW))
    assert out["error"].startswith("Serwer IMGW nie odpowiada") and out["areas"]["A1"]["text"] is None
    assert out["fetched_at"] is None and out["source_url"].startswith("https://awiacja.imgw.pl/")

    async def old(url, ttl, params=None, headers=None):
        return json.dumps(INFERRED)

    monkeypatch.setattr(gamet, "fetch_text", old)
    monkeypatch.setattr(gamet, "peek", lambda url, params=None: (1500.0, ""))   # starsze niż TTL: serwer nie odpowiedział
    out = asyncio.run(gamet.get_gamet(NOW))
    assert out["stale"] is True and out["error"] is None and out["areas"]["A1"]["valid"] == "150400/151000"


def test_gamet_endpoint_never_500(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main

    async def down(url, ttl, params=None, headers=None):
        raise UpstreamError("aviation-api.imgw.pl: CONNECT 403")

    monkeypatch.setattr(gamet, "fetch_text", down)
    clear_cache()
    with TestClient(main.app) as c:
        r = c.get("/api/meteo/gamet")
    assert r.status_code == 200 and "nie odpowiada" in r.json()["error"]
    assert set(r.json()["areas"]) == {"A1", "A2", "A3", "A4", "A5"}


def test_get_gamet_stale_through_fetch_text(fresh, monkeypatch):
    """Starsze dane naprawdę z fetch_text: serwer IMGW odpowiedział, po TTL przestał (HTTP 503), więc fetch_text oddaje
    ostatnią udaną odpowiedź, a get_gamet oznacza ją jako "stale" z czasem pobrania sprzed awarii."""
    from backend.app.services import http_cache

    clock, up = [1000.0], [True]
    # zegar tylko w http_cache (asyncio dalej korzysta z prawdziwego time.monotonic)
    monkeypatch.setattr(http_cache, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def handler(request):
        assert request.url.host == "aviation-api.imgw.pl" and request.url.params["params"] == "gamet"
        return httpx.Response(200, text=json.dumps(INFERRED)) if up[0] else httpx.Response(503, text="down")

    real = httpx.AsyncClient
    monkeypatch.setattr(http_cache.httpx, "AsyncClient",
                        lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    out = asyncio.run(gamet.get_gamet(NOW))
    assert out["stale"] is False and out["fetched_at"] == "2026-10-15T06:10:00Z" and out["areas"]["A1"]["below"] == "FL100"
    up[0], clock[0] = False, 1000.0 + 900   # 15 min później serwer nie odpowiada
    out = asyncio.run(gamet.get_gamet(NOW))
    assert out["stale"] is True and out["error"] is None and out["fetched_at"] == "2026-10-15T05:55:00Z"
    assert out["areas"]["A1"]["valid"] == "150400/151000"
