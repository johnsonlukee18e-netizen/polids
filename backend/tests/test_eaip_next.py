"""0.14.0 (issue #28): "dodaj opcję przy eAIP (next airac), gdzie będzie link do AIP na kolejny airac". /api/config
podaje następny cykl (airac_next) i index-v2.html jego poprawki w trzech pakietach (links.aip_ifr_next, aip_vfr_next,
aip_mil_next): adres z tego samego wzoru co bieżący (package_url), sprawdzony u PAŻP tak samo (folder_exists, pamięć na
cykl, jedno sprawdzenie naraz, najwyżej CONFIG_WAIT czekania); "" gdy katalogu (jeszcze) nie ma, wyliczony adres gdy nie
wiadomo. Bez sieci: udawany docs.pansa.pl (httpx.MockTransport) jak w test_eaip_links.py."""
import asyncio
import os
import tempfile
import time
from datetime import date

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.routers import system  # noqa: E402
from backend.app.services import eaip  # noqa: E402
from backend.app.services.airac import current_airac  # noqa: E402

PANSA = "https://docs.pansa.pl/ais/"
DAY = date(2026, 11, 20)   # cykl 2611 (od 29.10.2026), następny 2612 od 26.11.2026
NEXT_12 = {"aip_ifr": "eaipifr/AIRAC%20AMDT%2012-26_2026_11_26/index-v2.html",
           "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2012-26_2026_11_26/index-v2.html",
           "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2012-26_2026_11_26/index-v2.html"}
CUR_11 = {"aip_ifr": "eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/index-v2.html",
          "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2011-26_2026_10_29/index-v2.html",
          "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/index-v2.html"}
# katalogi na udawanym serwerze: bieżąca poprawka 11-26 i następna 12-26 tylko w IFR i MIL (VFR jeszcze nie ma)
ON_SERVER = {"eaipifr/AIRAC AMDT 11-26_2026_10_29", "eaipvfr/AIRAC AMDT VFR 11-26_2026_10_29",
             "eaipmil/AIRAC AMDT MIL 11-26_2026_10_29", "eaipifr/AIRAC AMDT 12-26_2026_11_26",
             "eaipmil/AIRAC AMDT MIL 12-26_2026_11_26"}


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    """Lokalny .env programisty nie wpływa na wynik: bez adresów z .env."""
    for link in eaip.PACKAGES:
        monkeypatch.setattr(settings, f"{link}_url", "")


@pytest.fixture
def pansa(monkeypatch):
    """Udawany docs.pansa.pl: 200 dla katalogów z srv["on"], 404 dla reszty; status=... wymusza odpowiedź, delay
    opóźnia każdą odpowiedź."""
    srv = {"seen": [], "status": None, "on": set(ON_SERVER), "delay": 0.0}

    async def handler(request):
        path = request.url.path
        srv["seen"].append(path)
        if srv["delay"]:
            await asyncio.sleep(srv["delay"])
        if srv["status"] is not None:
            if srv["status"] == "down":
                raise httpx.ConnectError("brak sieci", request=request)
            return httpx.Response(srv["status"])
        folder = path.removeprefix("/ais/").removesuffix("/index-v2.html")
        return httpx.Response(200 if folder in srv["on"] else 404, text="eAIP")

    monkeypatch.setattr(eaip, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(eaip, "utc_today", lambda: DAY)
    return srv


def strip(links):
    return {k: v.removeprefix(PANSA) for k, v in links.items()}


def nxt(day=DAY):
    return strip(asyncio.run(eaip.next_links(day)))


def test_next_airac():
    """Cykl po bieżącym: ten, który zaczyna się w dniu "next" bieżącego; ostatni i pierwszy dzień cyklu, zmiana roku."""
    assert eaip.next_airac(DAY) == {"ident": "2612", "effective": "2026-11-26", "next": "2026-12-24"}
    assert eaip.next_airac(date(2026, 11, 25))["ident"] == "2612"
    assert eaip.next_airac(date(2026, 11, 26)) == {"ident": "2613", "effective": "2026-12-24", "next": "2027-01-21"}
    assert eaip.next_airac(date(2026, 12, 24)) == {"ident": "2701", "effective": "2027-01-21", "next": "2027-02-18"}
    assert eaip.next_airac(date(2025, 12, 1))["ident"] == "2513"
    for day in (DAY, date(2026, 1, 1), date(2027, 6, 30)):
        assert eaip.next_airac(day)["effective"] == current_airac(day)["next"]


def test_next_package_urls():
    """Ten sam wzór katalogu co bieżący eAIP (package_url): AMDT 12-26 z datą wejścia 2026_11_26."""
    assert strip({k: eaip.package_url(k, eaip.next_airac(DAY)) for k in eaip.PACKAGES}) == NEXT_12


def test_next_links_published_or_not(pansa):
    """Katalog jest: adres; brak (404): "" (przycisk NEXT AIRAC pokazuje komunikat); jedno sprawdzenie na pakiet, bez
    szukania wcześniejszych poprawek (poprzednia to bieżący eAIP)."""
    assert nxt() == {"aip_ifr": NEXT_12["aip_ifr"], "aip_vfr": "", "aip_mil": NEXT_12["aip_mil"]}
    assert sorted(pansa["seen"]) == sorted("/ais/" + v.replace("%20", " ") for v in NEXT_12.values())


def test_next_links_cached_for_cycle(pansa):
    """Wynik w pamięci: kolejne zapytania w tym cyklu bez pytania PAŻP (także brak: do TTL_NEXT_MISSING)."""
    first = nxt()
    assert nxt() == first and nxt(date(2026, 11, 25)) == first
    assert len(pansa["seen"]) == 3


def test_missing_next_checked_again_later(pansa):
    """Brak katalogu trzymany TTL_NEXT_MISSING (godzina), potem od razu stary wynik i sprawdzenie w tle; gdy PAŻP
    w tym czasie opublikował poprawkę, następne zapytanie ma adres."""
    assert eaip.TTL_NEXT_MISSING == 3600
    assert nxt()["aip_vfr"] == ""
    pansa["on"].add("eaipvfr/AIRAC AMDT VFR 12-26_2026_11_26")

    async def run():
        key = ("aip_vfr" + eaip.NEXT, "2612")
        assert eaip._resolved[key][1] == ""
        eaip._resolved[key] = (time.monotonic() - 1, "")   # termin minął
        stale = await eaip.next_links(DAY)
        await asyncio.gather(*list(eaip._inflight.values()))
        return stale, await eaip.next_links(DAY)

    stale, fresh = asyncio.run(run())
    assert stale["aip_vfr"] == "" and strip(fresh) == NEXT_12
    assert len(pansa["seen"]) == 4


@pytest.mark.parametrize("status", ["down", 500, 503, 429])
def test_unknown_keeps_computed_url(pansa, status):
    """Bez połączenia z PAŻP albo przy błędzie serwera nie zgadujemy: wyliczony adres (jak bieżący eAIP), a nie
    komunikat o braku poprawki."""
    pansa["status"] = status
    assert nxt() == NEXT_12


@pytest.mark.parametrize("status", ["down", 503, 429])
def test_unknown_recheck_keeps_last_result(pansa, status):
    """Przegląd 0.14.0: ponowne sprawdzenie po TTL_NEXT_MISSING trafia na chwilowy błąd PAŻP: zostaje znany brak ("",
    komunikat), a nie wyliczony adres strony, której nie ma; kolejna próba po TTL_UNKNOWN, a gdy PAŻP wróci
    z opublikowaną poprawką, jest adres."""
    assert nxt()["aip_vfr"] == ""
    key = ("aip_vfr" + eaip.NEXT, "2612")

    async def recheck():
        eaip._resolved[key] = (time.monotonic() - 1, eaip._resolved[key][1])   # termin minął
        stale = await eaip.next_links(DAY)
        await asyncio.gather(*list(eaip._inflight.values()))
        return stale, await eaip.next_links(DAY)

    pansa["status"] = status
    stale, after = asyncio.run(recheck())
    assert stale["aip_vfr"] == "" and after["aip_vfr"] == ""
    until, url = eaip._resolved[key]
    assert url == "" and until - time.monotonic() <= eaip.TTL_UNKNOWN
    # znany adres (IFR, katalog jest) też nie znika przy błędzie
    assert strip(after)["aip_ifr"] == NEXT_12["aip_ifr"]
    pansa["status"] = None
    pansa["on"].add("eaipvfr/AIRAC AMDT VFR 12-26_2026_11_26")
    stale, after = asyncio.run(recheck())
    assert stale["aip_vfr"] == "" and strip(after) == NEXT_12


def test_redirect_elsewhere_counts_as_missing(pansa, monkeypatch):
    """Przekierowanie brakującego katalogu na inną stronę (200) to też brak."""
    def handler(request):
        if "12-26" in request.url.path:
            return httpx.Response(302, headers={"location": "https://docs.pansa.pl/ais/404.html"})
        return httpx.Response(200, text="eAIP")

    monkeypatch.setattr(eaip, "_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True))
    assert nxt() == {k: "" for k in eaip.PACKAGES}


def test_next_missing_does_not_leak_into_current_cycle(pansa):
    """Klucz pamięci następnego cyklu ma przyrostek NEXT: "" (brak 12-26 przed 26.11) nie trafia do bieżącego linku, gdy
    2612 staje się bieżącym cyklem; wtedy bieżący eAIP szuka poprawki jak zawsze (brak 12-26 → 11-26)."""
    pansa["on"] = {f for f in ON_SERVER if "11-26" in f}
    assert nxt() == {k: "" for k in eaip.PACKAGES}
    current = strip(asyncio.run(eaip.resolved_links(date(2026, 11, 26))))
    assert current == CUR_11


def test_env_override_only_for_current(pansa, monkeypatch):
    """Adres z .env (POLIDS_AIP_IFR_URL) dotyczy bieżącej poprawki; następna dalej z cyklu i sprawdzana u PAŻP."""
    monkeypatch.setattr(settings, "aip_ifr_url", "https://example.test/ifr/index-v2.html")
    links = asyncio.run(eaip.resolved_links(DAY))
    assert links["aip_ifr"] == "https://example.test/ifr/index-v2.html"
    assert nxt()["aip_ifr"] == NEXT_12["aip_ifr"]


def test_config_has_next_cycle_and_links(pansa):
    """/api/config: airac_next (ident, effective, next) i links.<pakiet>_next obok bieżących adresów."""
    cfg = TestClient(main.app).get("/api/config").json()
    assert cfg["airac"] == {"ident": "2611", "effective": "2026-10-29", "next": "2026-11-26"}
    assert cfg["airac_next"] == {"ident": "2612", "effective": "2026-11-26", "next": "2026-12-24"}
    links = strip(cfg["links"])
    assert {k: links[k] for k in eaip.PACKAGES} == CUR_11
    assert {k: links[f"{k}_next"] for k in eaip.PACKAGES} == {"aip_ifr": NEXT_12["aip_ifr"], "aip_vfr": "",
                                                              "aip_mil": NEXT_12["aip_mil"]}
    # bez osobnego sprawdzania osadzania: embed-check zna tylko bieżące adresy
    assert TestClient(main.app).get("/api/embed-check/aip_ifr_next").status_code == 404


def test_config_waits_at_most_config_wait(pansa, monkeypatch):
    """PAŻP wolniejszy niż limit: bieżące i następne sprawdzenia równolegle, /api/config po CONFIG_WAIT (nie 2 x) z
    wyliczonymi adresami; sprawdzenie kończy się w tle, następne /api/config od razu z wynikiem."""
    monkeypatch.setattr(eaip, "CONFIG_WAIT", 0.3)
    pansa["delay"] = 0.8

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
    assert strip({k: first[f"{k}_next"] for k in eaip.PACKAGES}) == NEXT_12
    assert strip({k: second[f"{k}_next"] for k in eaip.PACKAGES}) == {"aip_ifr": NEXT_12["aip_ifr"], "aip_vfr": "",
                                                                      "aip_mil": NEXT_12["aip_mil"]}
    assert took2 < 0.1


def test_concurrent_callers_share_one_check(pansa):
    """20 przeglądarek naraz: jedno sprawdzenie na pakiet (single-flight jak dla bieżącego cyklu)."""
    pansa["delay"] = 0.2

    async def run():
        return await asyncio.gather(*(eaip.next_links(DAY) for _ in range(20)))

    res = asyncio.run(run())
    assert all(r == res[0] for r in res) and len(pansa["seen"]) == 3


def test_startup_warms_next_cycle(pansa):
    """main.lifespan (eaip.warm) sprawdza od startu także następny cykl: pierwsze /api/config bez pytania PAŻP."""
    with TestClient(main.app) as client:
        deadline = time.monotonic() + 5
        while len(eaip._resolved) < 6 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(pansa["seen"]) == 6
        links = strip(client.get("/api/config").json()["links"])
        assert links["aip_ifr_next"] == NEXT_12["aip_ifr"] and links["aip_vfr_next"] == ""
        assert len(pansa["seen"]) == 6
