"""0.12.3: adresy eAIP PAŻP (AD CIV / AD MIL / AD VFR) idą za cyklem AIRAC. Bez POLIDS_AIP_*_URL katalog poprawki
liczy się z cyklu na dziś (UTC), więc po 29.10.2026 zakładki nie pokazują po cichu starej poprawki 10-26."""
import asyncio
import os
import tempfile
from datetime import date

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.services import eaip, embed  # noqa: E402
from backend.app.services.airac import current_airac  # noqa: E402

PANSA = "https://docs.pansa.pl/ais/"


def folders(day):
    return {k: v.removeprefix(PANSA) for k, v in eaip.aip_links(day).items()}


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    """Lokalny .env programisty nie wpływa na wynik: bez adresów z .env."""
    for link in eaip.PACKAGES:
        monkeypatch.setattr(settings, f"{link}_url", "")


def test_cycle_2610():
    # pierwszy i ostatni dzień cyklu (wejście 01.10.2026, następny 29.10.2026)
    for day in (date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 28)):
        assert folders(day) == {
            "aip_ifr": "eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html",
            "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2010-26_2026_10_01/index-v2.html",
            "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2010-26_2026_10_01/index-v2.html",
        }


def test_cycle_2611():
    assert current_airac(date(2026, 10, 29))["ident"] == "2611"
    assert folders(date(2026, 10, 29)) == {
        "aip_ifr": "eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/index-v2.html",
        "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2011-26_2026_10_29/index-v2.html",
        "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/index-v2.html",
    }


def test_cycle_2601_and_year_change():
    assert folders(date(2026, 1, 22))["aip_ifr"] == "eaipifr/AIRAC%20AMDT%2001-26_2026_01_22/index-v2.html"
    # dzień wcześniej: ostatni cykl 2025 (2513 od 25.12.2025); to tylko wzór nazwy, katalogu 13-25 u PAŻP nie ma
    # (cykl bez poprawki), /api/config pokazuje wtedy 12-25: test_nil_cycle_falls_back_to_previous_amendment
    assert current_airac(date(2026, 1, 21))["ident"] == "2513"
    # poprawka sprzed roku znaleziona w sieci: AIRAC AMDT 05-25_2025_05_15
    assert folders(date(2025, 5, 20))["aip_ifr"] == "eaipifr/AIRAC%20AMDT%2005-25_2025_05_15/index-v2.html"


def test_env_override_wins_unchanged(monkeypatch):
    own = "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2009-26_2026_09_03/index-v2.html"
    monkeypatch.setattr(settings, "aip_ifr_url", f"  {own} ")
    links = eaip.aip_links(date(2026, 11, 30))
    assert links["aip_ifr"] == own
    # pozostałe dwa bez wpisu w .env dalej liczone z cyklu
    assert links["aip_vfr"].endswith("AIRAC%20AMDT%20VFR%2012-26_2026_11_26/index-v2.html")


def test_utc_today_is_utc():
    assert eaip.utc_today() == eaip.datetime.now(eaip.timezone.utc).date()


def test_config_and_embed_check_follow_cycle(monkeypatch):
    """/api/config liczy adresy przy każdym zapytaniu (nowy cykl bez restartu), embed-check sprawdza ten sam adres."""
    client = TestClient(main.app)
    day = {"d": date(2026, 10, 28)}
    monkeypatch.setattr(eaip, "utc_today", lambda: day["d"])
    cfg = client.get("/api/config").json()
    assert cfg["airac"] == {"ident": "2610", "effective": "2026-10-01", "next": "2026-10-29"}
    assert cfg["links"]["aip_ifr"] == PANSA + "eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html"
    day["d"] = date(2026, 10, 29)
    cfg = client.get("/api/config").json()
    assert cfg["airac"]["ident"] == "2611"
    assert cfg["links"]["aip_mil"] == PANSA + "eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/index-v2.html"
    assert cfg["links"]["inop"].startswith("https://om.plvacc.pl")

    checked = []

    async def fake_check(url, ttl=3600):
        checked.append(url)
        return {"url": url, "embeddable": True, "reason": ""}

    monkeypatch.setattr(embed, "check", fake_check)
    for link in ("aip_ifr", "aip_vfr", "aip_mil", "inop"):
        assert client.get(f"/api/embed-check/{link}").status_code == 200
    assert checked == [cfg["links"][k] for k in ("aip_ifr", "aip_vfr", "aip_mil", "inop")]
    monkeypatch.setattr(settings, "aip_vfr_url", "https://example.test/vfr/index-v2.html")
    assert client.get("/api/embed-check/aip_vfr").json()["url"] == "https://example.test/vfr/index-v2.html"
    assert client.get("/api/config").json()["links"]["aip_vfr"] == "https://example.test/vfr/index-v2.html"
    assert client.get("/api/embed-check/nieznany").status_code == 404


# katalogi poprawek, które są na docs.pansa.pl (sprawdzone 2026-10: cykl 2513 nie ma AMDT 13-25 w żadnym pakiecie)
ON_SERVER = {"eaipifr/AIRAC AMDT 12-25_2025_11_27", "eaipvfr/AIRAC AMDT VFR 12-25_2025_11_27",
             "eaipmil/AIRAC AMDT MIL 12-25_2025_11_27", "eaipifr/AIRAC AMDT 01-26_2026_01_22",
             "eaipvfr/AIRAC AMDT VFR 01-26_2026_01_22", "eaipmil/AIRAC AMDT MIL 01-26_2026_01_22",
             "eaipifr/AIRAC AMDT 10-26_2026_10_01", "eaipvfr/AIRAC AMDT VFR 10-26_2026_10_01",
             "eaipmil/AIRAC AMDT MIL 10-26_2026_10_01"}


@pytest.fixture
def pansa(monkeypatch):
    """Udawany docs.pansa.pl: 200 dla katalogów z ON_SERVER, 404 dla reszty; status=... wymusza odpowiedź."""
    srv = {"seen": [], "status": None, "on": set(ON_SERVER)}

    def handler(request):
        path = request.url.path
        srv["seen"].append(path)
        if srv["status"] is not None:
            if srv["status"] == "down":
                raise httpx.ConnectError("brak sieci", request=request)
            return httpx.Response(srv["status"])
        folder = path.removeprefix("/ais/").removesuffix("/index-v2.html")
        return httpx.Response(200 if folder in srv["on"] else 404, text="eAIP")

    monkeypatch.setattr(eaip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return srv


def resolved(day):
    return {k: v.removeprefix(PANSA) for k, v in asyncio.run(eaip.resolved_links(day)).items()}


def test_nil_cycle_falls_back_to_previous_amendment(pansa):
    # 2513 (25.12.2025–21.01.2026) bez poprawki: przez cały cykl obowiązuje 12-25, a nie martwy katalog 13-25
    for day in (date(2025, 12, 25), date(2026, 1, 21)):
        eaip.reset_cache()
        assert resolved(day) == {
            "aip_ifr": "eaipifr/AIRAC%20AMDT%2012-25_2025_11_27/index-v2.html",
            "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2012-25_2025_11_27/index-v2.html",
            "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2012-25_2025_11_27/index-v2.html",
        }
    # pierwszy dzień 2601: znowu poprawka bieżącego cyklu
    assert resolved(date(2026, 1, 22))["aip_vfr"] == "eaipvfr/AIRAC%20AMDT%20VFR%2001-26_2026_01_22/index-v2.html"


def test_found_folder_cached_for_cycle(pansa):
    assert resolved(date(2026, 10, 15)) == folders(date(2026, 10, 15))
    assert len(pansa["seen"]) == 3
    # kolejne /api/config w tym samym cyklu bez pytania PAŻP
    assert resolved(date(2026, 10, 28)) == folders(date(2026, 10, 15))
    assert len(pansa["seen"]) == 3


def test_network_or_server_error_keeps_computed_url(pansa):
    # bez połączenia z PAŻP albo przy błędzie serwera nie zgadujemy: wyliczony adres bieżącego cyklu
    for status in ("down", 500, 503, 429):
        eaip.reset_cache()
        pansa["status"] = status
        assert resolved(date(2026, 1, 10)) == folders(date(2026, 1, 10)), status


def test_redirect_elsewhere_counts_as_missing(pansa, monkeypatch):
    # serwer, który brak katalogu przekierowuje na stronę błędu z 200, to też brak
    def handler(request):
        if "13-25" in request.url.path:
            return httpx.Response(302, headers={"location": "https://docs.pansa.pl/ais/404.html"})
        if request.url.path == "/ais/404.html" or "12-25" in request.url.path:
            return httpx.Response(200, text="eAIP")
        return httpx.Response(404)

    monkeypatch.setattr(eaip, "_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True))
    assert resolved(date(2026, 1, 1))["aip_ifr"] == "eaipifr/AIRAC%20AMDT%2012-25_2025_11_27/index-v2.html"


def test_no_folder_within_back_cycles_keeps_computed_url(pansa):
    pansa["on"] = set()
    assert resolved(date(2026, 10, 15)) == folders(date(2026, 10, 15))
    # bieżący i BACK_CYCLES poprzednich na każdy z trzech pakietów
    assert len(pansa["seen"]) == 3 * (eaip.BACK_CYCLES + 1)


def test_env_override_is_not_probed(pansa, monkeypatch):
    own = "https://example.test/ifr/index-v2.html"
    monkeypatch.setattr(settings, "aip_ifr_url", own)
    links = asyncio.run(eaip.resolved_links(date(2026, 1, 10)))
    assert links["aip_ifr"] == own
    assert not any(p.startswith("/ais/eaipifr/") for p in pansa["seen"])


def test_config_and_embed_check_use_fallback(pansa, monkeypatch):
    """/api/config i /api/embed-check dają ten sam sprawdzony adres; strony AD 2 (aeroPageUrl w aip.js) liczą się
    z adresu z /api/config, więc też idą do 12-25."""
    client = TestClient(main.app)
    monkeypatch.setattr(eaip, "utc_today", lambda: date(2026, 1, 21))
    cfg = client.get("/api/config").json()
    assert cfg["airac"]["ident"] == "2513"
    assert cfg["links"]["aip_ifr"] == PANSA + "eaipifr/AIRAC%20AMDT%2012-25_2025_11_27/index-v2.html"
    checked = []

    async def fake_check(url, ttl=3600):
        checked.append(url)
        return {"url": url, "embeddable": True, "reason": ""}

    monkeypatch.setattr(embed, "check", fake_check)
    eaip.reset_cache()
    for link in ("aip_ifr", "aip_vfr", "aip_mil"):
        assert client.get(f"/api/embed-check/{link}").status_code == 200
    assert checked == [cfg["links"][k] for k in ("aip_ifr", "aip_vfr", "aip_mil")]
    assert all("12-25_2025_11_27" in u for u in checked)
