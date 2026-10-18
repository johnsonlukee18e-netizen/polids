"""0.12.3: adresy eAIP PAŻP (AD CIV / AD MIL / AD VFR) idą za cyklem AIRAC. Bez POLIDS_AIP_*_URL katalog poprawki
liczy się z cyklu na dziś (UTC), więc po 29.10.2026 zakładki nie pokazują po cichu starej poprawki 10-26."""
import asyncio
import os
import re
import tempfile
import time
from datetime import date

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
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


# --- /api/config nie czeka na PAŻP: jedno sprawdzenie naraz, limit czekania, twardy limit na sprawdzenie, start w tle
DAY = date(2026, 10, 15)   # cykl 2610: katalogu 10-26 „nie ma”, 09-26 jest (cykl bez poprawki)
FALLBACK = {"aip_ifr": "eaipifr/AIRAC%20AMDT%2009-26_2026_09_03/index-v2.html",
            "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2009-26_2026_09_03/index-v2.html",
            "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2009-26_2026_09_03/index-v2.html"}


@pytest.fixture
def slow_pansa(monkeypatch):
    """PAŻP odpowiadający po srv["delay"] s: 404 dla katalogów 10-26, 200 dla pozostałych; liczy zapytania."""
    srv = {"seen": [], "delay": 0.3}

    async def handler(request):
        srv["seen"].append(request.url.path)
        await asyncio.sleep(srv["delay"])
        return httpx.Response(404 if "10-26" in request.url.path else 200, text="eAIP")

    monkeypatch.setattr(eaip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(eaip, "utc_today", lambda: DAY)
    return srv


def strip(links):
    return {k: v.removeprefix(PANSA) for k, v in links.items()}


def test_concurrent_callers_share_one_check(slow_pansa):
    """20 przeglądarek naraz po starcie albo po wygaśnięciu wpisu: tyle zapytań do PAŻP, co dla jednej (dawniej 20×)."""
    async def run(n):
        eaip.reset_cache()
        slow_pansa["seen"].clear()
        res = await asyncio.gather(*(eaip.resolved_links(DAY) for _ in range(n)))
        return len(slow_pansa["seen"]), res

    one, res1 = asyncio.run(run(1))
    many, res20 = asyncio.run(run(20))
    assert strip(res1[0]) == FALLBACK and all(strip(r) == FALLBACK for r in res20)
    # na pakiet: bieżący cykl, potem BACK_CYCLES poprzednich naraz
    assert one == many == 3 * (eaip.BACK_CYCLES + 1)


def test_config_waits_at_most_config_wait(slow_pansa, monkeypatch):
    """PAŻP wolniejszy niż limit: /api/config po CONFIG_WAIT z wyliczonym adresem, sprawdzenie kończy się w tle,
    a następne /api/config ma już poprawkę z poprzedniego cyklu (bez ponownego pytania PAŻP)."""
    from backend.app.routers import system

    assert eaip.CONFIG_WAIT <= 2   # HOME i menu czekają na /api/config
    monkeypatch.setattr(eaip, "CONFIG_WAIT", 0.3)
    slow_pansa["delay"] = 0.8

    async def run():
        t = time.monotonic()
        first = (await system.config())["links"]
        took = time.monotonic() - t
        await asyncio.gather(*list(eaip._inflight.values()))
        t = time.monotonic()
        second = (await system.config())["links"]
        return took, first, second, time.monotonic() - t

    took, first, second, took2 = asyncio.run(run())
    assert took < 0.3 + 0.4, took
    assert {k: first[k] for k in FALLBACK} == eaip.aip_links(DAY)
    assert strip({k: second[k] for k in FALLBACK}) == FALLBACK and took2 < 0.1
    assert len(slow_pansa["seen"]) == 3 * (eaip.BACK_CYCLES + 1)


def test_expired_entry_answers_at_once_and_refreshes(slow_pansa):
    """Po terminie ważności: od razu poprzedni wynik tego cyklu, nowe sprawdzenie w tle."""
    async def run():
        for link in eaip.PACKAGES:
            eaip._resolved[(link, "2610")] = (time.monotonic() - 1, f"stary/{link}")
        t = time.monotonic()
        stale = await eaip.resolved_links(DAY)
        took = time.monotonic() - t
        await asyncio.gather(*list(eaip._inflight.values()))
        return took, stale, await eaip.resolved_links(DAY)

    took, stale, fresh = asyncio.run(run())
    assert stale == {link: f"stary/{link}" for link in eaip.PACKAGES} and took < 0.1
    assert strip(fresh) == FALLBACK


def test_probe_has_hard_timeout(monkeypatch):
    """Serwer, który przyjmuje połączenie i nie odpowiada (albo sączy bajty): limit na całe sprawdzenie, nie na fazę
    httpx; wynik „nie wiadomo” → wyliczony adres na TTL_UNKNOWN."""
    async def handler(request):
        await asyncio.sleep(30)
        return httpx.Response(200)

    monkeypatch.setattr(eaip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(eaip, "PROBE_TIMEOUT", 0.2)

    async def run():
        async with eaip._client() as client:
            t = time.monotonic()
            res = await eaip._resolve(client, "aip_ifr", current_airac(DAY))
            return time.monotonic() - t, res

    took, (url, ttl) = asyncio.run(run())
    assert took < 1 and url == eaip.package_url("aip_ifr", current_airac(DAY)) and ttl == eaip.TTL_UNKNOWN


def test_startup_checks_in_background(pansa, monkeypatch):
    """main.lifespan startuje sprawdzenie (eaip.warm): pierwsze /api/config ma gotowy wynik i nie pyta PAŻP drugi raz."""
    monkeypatch.setattr(eaip, "utc_today", lambda: DAY)
    with TestClient(main.app) as client:
        deadline = time.monotonic() + 5
        while len(eaip._resolved) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(pansa["seen"]) == 3
        assert strip({k: v for k, v in client.get("/api/config").json()["links"].items() if k in FALLBACK}) == folders(DAY)
        assert len(pansa["seen"]) == 3


# --- AD CIV (0.12.5, issue #18): przycisk lotniska = lista map z AD 2.24 strony AD 2 (GET /api/docs/charts/<ICAO>) ---
PKG = PANSA + "eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/"
ZG_PAGE = PKG + "eAIP/AD%202%20EPZG%201-en-GB.html"
DOCS = PKG + "documents/Root_WePub/AIP%20IFR/AD/EPZG/"
# układ jak AD 2.24 EPZG i EPSY w eAIP PAŻP (AIRAC AMDT 10-26): tabela "Charts | Pages", tytuł w pierwszej komórce
# (czasem w cudzysłowie albo z przedrostkiem "EPZG - "), odnośnik do PDF-u ze spacją w "AIP IFR", zera z przodu (08-1)
ZG_HTML = """<html><body><h3>EPZG AD 2.23 ADDITIONAL INFORMATION</h3><p>Nil</p>
<h3 id="EPZG-AD-2.24">EPZG AD 2.24 AERONAUTICAL CHARTS RELATED TO AN AERODROME</h3>
<table><thead><tr><th>Charts</th><th>Pages</th></tr></thead><tbody>
<tr><td>EPZG - AERODROME CHART - ICAO</td>
  <td><a href="../documents/Root_WePub/AIP IFR/AD/EPZG/02/AD_2_EPZG_2-1.pdf"><img src="pdf.gif"></a></td></tr>
<tr><td>"AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 06, RWY 24) &amp; more"</td>
  <td><a href="../documents/Root_WePub/AIP%20IFR/AD/EPZG/06/AD_2_EPZG_06-1.pdf">AD 2 EPZG 6-1</a></td></tr>
<tr><td>AERODROME CHART again</td>
  <td><a href="../documents/Root_WePub/AIP%20IFR/AD/EPZG/02/AD_2_EPZG_2-1.pdf"></a></td></tr>
<tr><td>Warsaw chart on a wrong page</td><td><a href="../documents/Root_WePub/AIP IFR/AD/EPWA/02/AD_2_EPWA_2-1.pdf"></a></td></tr>
<tr><td>script</td><td><a href="javascript:alert(1)//AD_2_EPZG_9-1.pdf"></a></td></tr>
<tr><td>VISUAL APPROACH CHART - ICAO</td><td><a href="ftp://docs.pansa.pl/AD_2_EPZG_14-1.pdf"></a></td></tr>
<tr><td>   </td><td><a href="https://docs.pansa.pl/x/AD_2_EPZG_13-1.pdf?v=2">13-1</a></td></tr>
<tr><td>TEXT WITHOUT LINK</td><td>-</td></tr>
<tr><td>AERODROME DATA</td><td><a href="AD 2 EPZG 1-en-GB.html#EPZG-AD-2.1">AD 2.1</a></td></tr>
</tbody></table>
<p>See <a href="../documents/Root_WePub/AIP IFR/AD/EPZG/12/AD_2_EPZG_12-1.pdf">INSTRUMENT APPROACH CHART - ICAO (ILS z) RWY 24</a></p>
</body></html>"""


def test_aerodrome_page_url_matches_frontend():
    # ta sama strona co aeroPageUrl w tabs/aip.js (test_aip_tabs.py: test_aerodrome_page_urls)
    assert eaip.aerodrome_page_url(PKG + "index-v2.html", "EPZG") == ZG_PAGE
    amdt11 = PANSA + "eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/eAIP/AD%202%20EPKK%201-en-GB.html"
    assert eaip.aerodrome_page_url(PANSA + "eaipifr/AIRAC%20AMDT%2011-26_2026_10_29", "EPKK") == amdt11
    assert eaip.aerodrome_page_url(PANSA + "eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/", "EPKK") == amdt11
    assert eaip.aerodrome_page_url(PKG + "index-v2.html?x=1#top", "EPZG") == ZG_PAGE


def test_chart_kind():
    kinds = {
        "AERODROME CHART - ICAO": "AD", "AERODROME CHART AREAS OF RESPONSIBILITY": "AD",
        "AIRCRAFT PARKING/DOCKING CHART - ICAO": "AD", "AERODROME GROUND MOVEMENT CHART - ICAO": "AD",
        "AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 06, RWY 24)": "OBST",
        "PRECISION APPROACH TERRAIN CHART - ICAO RWY 33": "OBST",
        "STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO RWY 29": "SID",
        "STANDARD INSTRUMENT DEPARTURE CHART - ICAO": "SID",
        "STANDARD ARRIVAL CHART INSTRUMENT (STAR) - ICAO (RWY 06, RWY 24)": "STAR",
        "INSTRUMENT APPROACH CHART - ICAO (ILS z) RWY 24 (CAT A/B/C/D)": "IAC",
        "VISUAL APPROACH CHART - ICAO": "VFR", "VISUAL OPERATION CHART": "VFR",
        "ATC SURVEILLANCE MINIMUM ALTITUDE CHART - ICAO": "OTHER", "BIRD CONCENTRATION": "OTHER",
    }
    assert {t: eaip.chart_kind(t) for t in kinds} == kinds
    assert eaip.chart_kind("instrument approach chart") == "IAC"


def test_parse_charts():
    charts = eaip.parse_charts(ZG_HTML, ZG_PAGE, "epzg")
    # tylko PDF-y map tego lotniska (http/https), w kolejności strony, bez powtórzeń adresu (spacja i %20 to ten sam)
    assert [c["id"] for c in charts] == ["2-1", "6-1", "13-1", "12-1"]
    assert charts[0] == {"id": "2-1", "page": "AD 2 EPZG 2-1", "title": "AERODROME CHART - ICAO", "kind": "AD",
                         "url": DOCS + "02/AD_2_EPZG_2-1.pdf"}
    # cudzysłów i encje HTML z tytułu, 06-1 → 6-1 (adres pliku bez zmian)
    assert charts[1]["title"] == "AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 06, RWY 24) & more"
    assert charts[1]["kind"] == "OBST" and charts[1]["url"] == DOCS + "06/AD_2_EPZG_06-1.pdf"
    # pusta komórka tytułu: numer strony; adres bezwzględny z ?v zostaje
    assert charts[2]["title"] == "AD 2 EPZG 13-1" and charts[2]["url"] == "https://docs.pansa.pl/x/AD_2_EPZG_13-1.pdf?v=2"
    # odnośnik poza tabelą: tytuł z tekstu odnośnika
    assert charts[3]["title"] == "INSTRUMENT APPROACH CHART - ICAO (ILS z) RWY 24" and charts[3]["kind"] == "IAC"
    assert all(" " not in c["url"] for c in charts)
    assert eaip.parse_charts("<html><p>AD 2.24 Nil</p></html>", ZG_PAGE, "EPZG") == []


@pytest.fixture
def ad2(monkeypatch):
    """Udawana strona AD 2 EPZG (adres poprawki z .env, więc bez sprawdzania katalogu u PAŻP)."""
    srv = {"seen": [], "status": 200, "html": ZG_HTML, "delay": 0.0}

    async def handler(request):
        srv["seen"].append(str(request.url))
        if srv["delay"]:
            await asyncio.sleep(srv["delay"])
        if srv["status"] == "down":
            raise httpx.ConnectError("brak sieci", request=request)
        if srv["status"] == "slow":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(srv["status"], text=srv["html"])

    monkeypatch.setattr(settings, "aip_ifr_url", PKG + "index-v2.html")
    monkeypatch.setattr(eaip, "_page_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    eaip.reset_charts()
    yield srv
    eaip.reset_charts()


def test_aerodrome_charts_cached(ad2):
    first = asyncio.run(eaip.aerodrome_charts("epzg"))
    assert first["icao"] == "EPZG" and first["page"] == ZG_PAGE and first["error"] is None
    assert [c["id"] for c in first["charts"]] == ["2-1", "6-1", "13-1", "12-1"]
    assert ad2["seen"] == [ZG_PAGE]
    # druga prośba z pamięci, bez pobierania strony (kilka MB przy EPWA)
    assert asyncio.run(eaip.aerodrome_charts("EPZG")) == first and len(ad2["seen"]) == 1


def test_aerodrome_charts_single_flight(ad2):
    ad2["delay"] = 0.2

    async def both():
        return await asyncio.gather(eaip.aerodrome_charts("EPZG"), eaip.aerodrome_charts("EPZG"))

    a, b = asyncio.run(both())
    assert a == b and len(a["charts"]) == 4 and len(ad2["seen"]) == 1


@pytest.mark.parametrize("status, error", [
    (404, "eAIP server: HTTP 404"), ("down", "cannot connect to the eAIP server"),
    ("slow", "no response from the eAIP server (timeout)"),
])
def test_aerodrome_charts_errors(ad2, status, error):
    ad2["status"] = status
    out = asyncio.run(eaip.aerodrome_charts("EPZG"))
    assert out == {"icao": "EPZG", "page": ZG_PAGE, "charts": [], "error": error}
    # błąd też trzymany chwilę (CHARTS_FAIL_TTL): bez zapytania do PAŻP przy każdym kliknięciu
    asyncio.run(eaip.aerodrome_charts("EPZG"))
    assert len(ad2["seen"]) == 1


def test_aerodrome_charts_no_charts_and_size_cap(ad2, monkeypatch):
    ad2["html"] = "<html><h3>EPZG AD 2.24</h3><p>Nil</p></html>"
    assert asyncio.run(eaip.aerodrome_charts("EPZG"))["error"] == "no charts found in AD 2.24 of the eAIP page"
    eaip.reset_charts()
    ad2["html"] = ZG_HTML
    monkeypatch.setattr(eaip, "CHARTS_MAX_BYTES", 100)
    out = asyncio.run(eaip.aerodrome_charts("EPZG"))
    assert out["charts"] == [] and out["error"] == "eAIP page could not be read (page larger than 0 MB)"


def test_charts_endpoint(monkeypatch):
    seen = []

    async def fake(icao, today=None):
        seen.append(icao)
        return {"icao": icao, "page": ZG_PAGE, "charts": [], "error": None}

    monkeypatch.setattr(eaip, "aerodrome_charts", fake)
    client = TestClient(main.app)
    r = client.get("/api/docs/charts/epzg")
    assert r.status_code == 200 and r.json()["icao"] == "EPZG" and seen == ["EPZG"]
    for bad in ("KJFK", "EP1A", "EPWAX", "EP"):
        r = client.get(f"/api/docs/charts/{bad}")
        assert r.status_code == 400, bad
        assert r.json()["detail"] == "Aerodrome charts: ICAO code of a Polish aerodrome (EP + 2 letters)"
    assert seen == ["EPZG"]
    # EP-kod bez części AD 2 w eAIP: 404 bez pobierania strony u PAŻP
    r = client.get("/api/docs/charts/EPKS")
    assert r.status_code == 404 and seen == ["EPZG"]


def test_ad2_list_matches_frontend():
    js = (ROOT_DIR / "frontend" / "js" / "tabs" / "aip.js").read_text("utf-8")
    block = js[js.index("export const AD2 = ["):js.index("]];") + 3]
    assert tuple(re.findall(r'\["(EP[A-Z]{2})"', block)) == eaip.AD2_AERODROMES


VARIANT_HTML = """<html><body><table>
<tr><td>EPWA - AERODROME<br/>GROUND MOVEMENT CHART - ICAO</td><td><a href="AD_2_EPWA_3-1.pdf"><img src="p.gif"></a></td></tr>
<tr><td><p>STANDARD DEPARTURE CHART</p><p>INSTRUMENT (SID) - ICAO RWY 29</p></td><td><a href="AD_2_EPWA_4-1.pdf"></a></td></tr>
<tr><td><del>OLD AERODROME CHART</del><ins>AERODROME CHART - ICAO</ins></td><td><a href="AD_2_EPWA_2-1.pdf"></a></td></tr>
<tr><td><del>WITHDRAWN CHART</del></td><td><del><a href="AD_2_EPWA_9-1.pdf"></a></del></td></tr>
<tr><td rowspan="2">INSTRUMENT APPROACH CHART - ICAO RWY 33</td><td><a href="AD_2_EPWA_12-1.pdf"></a></td></tr>
<tr><td><a href="AD_2_EPWA_12-2.pdf"></a></td></tr>
<tr><td>VISUAL APPROACH CHART - ICAO</td><td><table><tr><td><a href="AD_2_EPWA_13-1.pdf"></a></td></tr></table></td></tr>
<tr><td>AIRCRAFT PARKING/DOCKING CHART - ICAO<td><a href="AD_2_EPWA_5-1.pdf"></a>
<tr><td></td><td><a href="AD_2_EPWA_6-1.pdf" title="BIRD CONCENTRATION CHART"></a></td></tr>
<tr><td></td><td><a href="AD_2_EPWA_7-1.pdf"><img src="p.gif" alt="AERODROME OBSTACLE CHART - ICAO TYPE A"></a></td></tr>
</table></body></html>"""


def test_parse_charts_real_eaip_variants():
    # <br>/<p> rozdzielają słowa, <del> (skreślone w poprawce) pomijamy, rowspan i tabela w komórce, brak </td>/</tr>,
    # tytuł z title odnośnika albo alt obrazka
    page = "https://docs.pansa.pl/ais/eaipifr/X/eAIP/AD%202%20EPWA%201-en-GB.html"
    got = {c["id"]: (c["title"], c["kind"]) for c in eaip.parse_charts(VARIANT_HTML, page, "EPWA")}
    assert got == {
        "3-1": ("AERODROME GROUND MOVEMENT CHART - ICAO", "AD"),
        "4-1": ("STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO RWY 29", "SID"),
        "2-1": ("AERODROME CHART - ICAO", "AD"),
        "12-1": ("INSTRUMENT APPROACH CHART - ICAO RWY 33", "IAC"),
        "12-2": ("INSTRUMENT APPROACH CHART - ICAO RWY 33", "IAC"),
        "13-1": ("VISUAL APPROACH CHART - ICAO", "VFR"),
        "5-1": ("AIRCRAFT PARKING/DOCKING CHART - ICAO", "AD"),
        "6-1": ("BIRD CONCENTRATION CHART", "OTHER"),
        "7-1": ("AERODROME OBSTACLE CHART - ICAO TYPE A", "OBST"),
    }


# --- runda 14 (przegląd): parser nie rzuca wyjątku na żadnej zbitce znaczników (IndexError z _Rows dawał pustą listę
# map całego lotniska na CHARTS_FAIL_TTL), rowspan nie przechodzi do następnej tabeli
ZG = "../documents/Root_WePub/AIP IFR/AD/EPZG/{n:02d}/AD_2_EPZG_{n:02d}-1.pdf"


def _ids(html, icao="EPZG"):
    return [(c["id"], c["title"]) for c in eaip.parse_charts(html, ZG_PAGE, icao)]


def test_parse_charts_unclosed_link_then_img_alt_in_later_row():
    # <a> bez </a> kończy się z wierszem: alt obrazka z następnego wiersza nie trafia do niego (dawniej IndexError)
    html = (f'<table><tr><td>A</td><td><a href="{ZG.format(n=2)}">AD 2 EPZG 2-1</td></tr>'
            '<tr><td>B<img alt="x"></td></tr></table>')
    assert _ids(html) == [("2-1", "A")]
    # ten sam odnośnik bez tytułu w komórkach: alt obrazka w jego własnym wierszu dalej jest tytułem
    html = f'<table><tr><td></td><td><a href="{ZG.format(n=2)}"><img alt="AERODROME CHART"></td></tr><tr><td><img alt="y"></td></tr></table>'
    assert _ids(html) == [("2-1", "AERODROME CHART")]


def test_parse_charts_link_wrapping_nested_table():
    # <a href=pdf> obejmujący tabelę z obrazkiem (dawniej IndexError): odnośnik poza tabelą, tytuł = numer strony
    html = f'<a href="{ZG.format(n=2)}"><table><tr><td><img alt="pdf"></td></tr></table></a>'
    assert _ids(html) == [("2-1", "AD 2 EPZG 2-1")]
    # to samo bez </a> i bez </table>: odnośnik nie ginie (koniec strony go zamyka)
    assert _ids(f'<a href="{ZG.format(n=2)}"><table><tr><td><img alt="pdf">') == [("2-1", "AD 2 EPZG 2-1")]
    # <a> w komórce obejmujący tabelę zagnieżdżoną: alt obrazka z tej tabeli to opis tego odnośnika
    html = f'<table><tr><td></td><td><a href="{ZG.format(n=6)}"><table><tr><td><img alt="OBSTACLE CHART"></td></tr></table></a></td></tr></table>'
    assert _ids(html) == [("6-1", "OBSTACLE CHART")]


def test_parse_charts_rowspan_stops_at_table_end():
    # rowspan=3 w ostatnim wierszu tabeli: tekst nie przechodzi do pierwszego wiersza następnej tabeli
    html = (f'<table><tr><td rowspan="3">IAC</td><td><a href="{ZG.format(n=12)}">AD 2 EPZG 12-1</a></td></tr></table>'
            f'<table><tr><td><a href="{ZG.format(n=2)}">AD 2 EPZG 2-1</a></td><td>AERODROME CHART</td></tr></table>')
    assert _ids(html) == [("12-1", "IAC"), ("2-1", "AERODROME CHART")]
    # w tej samej tabeli rowspan działa dalej (wspólny tytuł kilku PDF-ów)
    html = (f'<table><tr><td rowspan="2">IAC RWY 24</td><td><a href="{ZG.format(n=12)}"></a></td></tr>'
            f'<tr><td><a href="{ZG.format(n=13)}"></a></td></tr></table>')
    assert _ids(html) == [("12-1", "IAC RWY 24"), ("13-1", "IAC RWY 24")]


def test_parse_charts_bad_url_skips_only_that_link():
    # adres, którego urllib nie rozbierze (ValueError), pomijamy; reszta listy zostaje
    html = (f'<table><tr><td>X</td><td><a href="http://[x/AD_2_EPZG_3-1.pdf"></a></td></tr>'
            f'<tr><td>AERODROME CHART</td><td><a href="{ZG.format(n=2)}"></a></td></tr></table>'
            '<a href="//[nie-ip]/AD_2_EPZG_4-1.pdf">SID</a>')
    assert _ids(html) == [("2-1", "AERODROME CHART")]


FUZZ_TAGS = ("tr", "td", "th", "a", "img", "table", "br", "del", "ins", "p", "div")


def _soup(rnd, n):
    """Losowa zbitka znaczników z FUZZ_TAGS (otwarcia, zamknięcia, atrybuty rowspan / href / alt / title) i tekstu."""
    out = []
    for _ in range(n):
        tag, r = rnd.choice(FUZZ_TAGS), rnd.random()
        if r < 0.15:
            out.append(rnd.choice(["AERODROME CHART", "SID RWY 29", "2-1", " ", "&amp;", "STAR", "<", "\""]))
        elif r < 0.55:
            attrs = ""
            if tag == "a" and rnd.random() < 0.8:
                attrs = f' href="{rnd.choice([ZG.format(n=rnd.randint(1, 30)), "AD_2_EPZG_7-2.pdf", "http://[x/AD_2_EPZG_5-1.pdf", "x.html", "", "AD_2_EPWA_2-1.pdf"])}"'
                if rnd.random() < 0.3:
                    attrs += ' title="BIRD CHART"'
            elif tag == "img" and rnd.random() < 0.8:
                attrs = f' alt="{rnd.choice(["pdf", "", "VISUAL APPROACH CHART"])}"'
            elif tag in ("td", "th") and rnd.random() < 0.3:
                attrs = f' rowspan="{rnd.choice(["2", "3", "0", "-1", "x", "", "99"])}"'
            out.append(f"<{tag}{attrs}>")
        elif r < 0.95:
            out.append(f"</{tag}>")
        else:
            out.append(f"<{tag}/>")
    return "".join(out)


def test_parse_charts_fuzz_never_raises():
    """Losowe zbitki znaczników (wiele ziaren): parse_charts nie rzuca wyjątku i daje poprawne wpisy; dobrze zbudowane
    strony z dopisaną na końcu zbitką mają te same mapy co bez niej (zbitka używa innych numerów stron)."""
    import random

    page = "https://docs.pansa.pl/ais/eaipifr/X/eAIP/AD%202%20EPWA%201-en-GB.html"
    good = {name: (html, icao, eaip.parse_charts(html, page, icao))
            for name, html, icao in (("zg", ZG_HTML, "EPZG"), ("variant", VARIANT_HTML, "EPWA"))}
    for seed in range(400):
        rnd = random.Random(seed)
        soup = _soup(rnd, rnd.randint(1, 80))
        charts = eaip.parse_charts(soup, ZG_PAGE, "EPZG")
        urls = [c["url"] for c in charts]
        assert len(urls) == len(set(urls)), (seed, soup)
        for c in charts:
            assert set(c) == {"id", "page", "title", "kind", "url"} and re.fullmatch(r"\d+-\d+", c["id"]), (seed, soup)
            assert c["title"] and c["url"].startswith("https://") and " " not in c["url"], (seed, soup)
        # dobrze zbudowana strona + zbitka (z numerami stron 90+): mapy strony bez zmian, w tej samej kolejności
        for name, (html, icao, want) in good.items():
            tail = soup.replace("AD_2_EPZG_", f"AD_2_{icao}_9").replace("AD_2_EPWA_", f"AD_2_{icao}_9")
            got = [c for c in eaip.parse_charts(html + tail, page, icao) if not c["id"].startswith("9")]
            assert got == [c for c in want if not c["id"].startswith("9")], (name, seed, soup)
