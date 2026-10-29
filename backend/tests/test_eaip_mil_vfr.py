"""0.13.1 (issue #25): AD MIL i AD VFR mają, jak AD CIV, przyciski lotnisk i listę map. Lotniska wojskowe (eAIP MIL)
i VFR (eAIP VFR) są w części AD 4: strona eAIP/AD 4 <ICAO> 1-en-GB.html bieżącej poprawki pakietu, mapy w tabeli
AD 4.24 (MIL) albo AD 4.13 (VFR), PDF-y AD_4_<ICAO>_<n>-<m>.pdf. Ten sam parser co AD 2 (część i numeracja serii map
z AIP_PARTS), ten sam katalog poprawki co index-v2.html pakietu (resolved_url), nowy adres
GET /api/docs/charts/<ifr|mil|vfr>/<ICAO> (stary /api/docs/charts/<ICAO> = IFR)."""
import asyncio
import os
import re
import tempfile
from datetime import date
from html import unescape

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.services import eaip  # noqa: E402
from backend.tests.eaip_pages import (PAGES4, PKG4, ad2_page, ad4_page, docs4, page4_url, page_url, pdf,  # noqa: E402
                                      pdf4)

AIP_JS = (ROOT_DIR / "frontend" / "js" / "tabs" / "aip.js").read_text("utf-8")
LINK = {"MIL": "aip_mil", "VFR": "aip_vfr"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """Bez adresów z lokalnego .env, z pustą pamięcią katalogów i list map."""
    for link in eaip.PACKAGES:
        monkeypatch.setattr(settings, f"{link}_url", "")
    eaip.reset_cache()
    eaip.reset_charts()
    yield
    eaip.reset_cache()
    eaip.reset_charts()


def parse4(icao, pkg, html=None):
    part, series = eaip.AIP_PARTS[LINK[pkg]]
    return eaip.parse_charts(ad4_page(icao, pkg) if html is None else html, page4_url(icao, pkg), icao, part, series)


def want4(icao, pkg):
    out = []
    for title, folder, page, short, kind in PAGES4[(icao, pkg)]:
        n, m = page.split("-")
        full = " ".join(re.sub(r'<span class="AmdtDeletedAIRAC">.*?</span>|<del>.*?</del>|<[^>]+>', "", title).split())
        full = re.sub(rf"^{icao} - ", "", unescape(full))
        out.append({"id": f"{int(n)}-{int(m)}", "page": f"AD 4 {icao} {int(n)}-{int(m)}", "title": short, "full": full,
                    "kind": kind, "url": docs4(icao, folder, page, pkg)})
    return out


@pytest.mark.parametrize("icao, pkg", sorted(PAGES4))
def test_ad4_pages_one_entry_per_chart(icao, pkg):
    # układ stron PAŻP (jak AD 2): każda mapa z krótką nazwą, rodzajem, numerem strony "AD 4 ..." i PDF-em z %20
    assert parse4(icao, pkg) == want4(icao, pkg)


def test_epks_kinds_and_names():
    charts = parse4("EPKS", "MIL")
    assert [c["kind"] for c in charts].count("IAC") == 7 and len(charts) == 14
    # mapy statków wysokomanewrowych w filtrach SID / STAR, z "HMA" w nazwie; pełny tytuł w dymku
    hma = [(c["id"], c["title"], c["kind"]) for c in charts if "HMA" in c["title"]]
    assert hma == [("8-1", "RWY 11 SID HMA", "SID"), ("8-5", "RWY 29 SID HMA", "SID"), ("10-1", "RWY 11 STAR HMA", "STAR"),
                   ("10-5", "RWY 29 STAR HMA", "STAR")]
    assert charts[2]["full"] == "HIGHLY MANOEUVRABLE MILITARY AIRCRAFT DEPARTURE CHART - RWY 11"


def test_amendment_markup_left_out():
    # EPDE: skreślone w poprawce numery dróg startowych (12/30) nie trafiają do tytułu ani nazwy
    for c in parse4("EPDE", "MIL"):
        assert "12," not in c["full"] and "30" not in c["full"] and " 12 " not in c["full"], c


def test_page_urls_of_mil_and_vfr():
    vfr = PKG4["VFR"] + "index-v2.html"
    assert eaip.aerodrome_page_url(vfr, "EPBC", 4) == page4_url("EPBC", "VFR")
    assert eaip.aerodrome_page_url(PKG4["MIL"].rstrip("/"), "EPKS", 4) == page4_url("EPKS", "MIL")
    assert eaip.aerodrome_page_url(PKG4["MIL"] + "index-v2.html?x=1#top", "EPKS", 4) == page4_url("EPKS", "MIL")
    # domyślnie AD 2 (AD CIV) jak dotąd
    assert eaip.aerodrome_page_url(vfr, "EPWA") == PKG4["VFR"] + "eAIP/AD%202%20EPWA%201-en-GB.html"
    assert eaip.AIP_PARTS["aip_ifr"][0] == 2 and eaip.AIP_PARTS["aip_mil"][0] == 4 and eaip.AIP_PARTS["aip_vfr"][0] == 4


def test_part_filter():
    # strona AD 4 bierze tylko PDF-y AD_4_<ICAO>, strona AD 2 tylko AD_2_<ICAO> (także przy tym samym kodzie lotniska)
    rows = [("EPKS - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC")]
    stray = f'<p><a href="{pdf("EPKS", "02", "2-1")}">AERODROME CHART</a></p>'
    html = ad4_page("EPKS", "MIL", rows).replace("</body>", stray + "</body>")
    got = parse4("EPKS", "MIL", html)
    assert [(c["id"], c["page"]) for c in got] == [("2-1", "AD 4 EPKS 2-1")] and "AD_4_EPKS_2-1.pdf" in got[0]["url"]
    page2 = ad2_page("EPZG").replace("</body>", f'<a href="{pdf4("EPZG", "02", "2-1", "MIL")}">X</a></body>')
    assert all("AD_2_" in c["url"] for c in eaip.parse_charts(page2, page_url("EPZG"), "EPZG"))
    assert eaip.parse_charts(ad4_page("EPKS", "MIL"), page4_url("EPKS", "MIL"), "EPKS") == []   # part 2: nic z AD 4


def test_kind_from_series_per_package():
    # tytuł, który nic nie mówi: rodzaj z numeru serii pakietu; VFR 3 i 4 to mapy operacji VFR (w IFR: ADC, APDC)
    vfr = [("", "3", "3-1"), ("", "4", "4-1"), ("", "2", "2-1"), ("", "5", "5-1")]
    got = [(c["id"], c["title"], c["kind"])
           for c in parse4("EPZW", "VFR", ad4_page("EPZW", "VFR", [(*r, "", "") for r in vfr]))]
    assert got == [("3-1", "AD 4 EPZW 3-1", "VFR"), ("4-1", "AD 4 EPZW 4-1", "VFR"), ("2-1", "AD 4 EPZW 2-1", "ADC"),
                   ("5-1", "AD 4 EPZW 5-1", "OTHER")]
    mil = [("", "08", "8-1"), ("", "10", "10-1"), ("", "12", "12-1"), ("", "04", "4-1")]
    got = [(c["id"], c["title"], c["kind"])
           for c in parse4("EPKS", "MIL", ad4_page("EPKS", "MIL", [(*r, "", "") for r in mil]))]
    assert got == [("8-1", "AD 4 EPKS 8-1", "SID"), ("10-1", "AD 4 EPKS 10-1", "STAR"), ("12-1", "AD 4 EPKS 12-1", "IAC"),
                   ("4-1", "AD 4 EPKS 4-1", "APDC")]
    assert eaip.VFR_SERIES_KINDS == {2: "ADC", 3: "VFR", 4: "VFR"} and eaip.AIP_PARTS["aip_mil"][1] is eaip.SERIES_KINDS


def test_short_names_hma_and_scale():
    def short(*titles):
        return eaip.short_names([(t, eaip.chart_kind(t)) for t in titles])

    assert short("HIGHLY MANOEUVRABLE MILITARY AIRCRAFT DEPARTURE CHART - RWY 11") == ["RWY 11 SID HMA"]
    assert short("HIGHLY MANOEUVRABLE MILITARY AIRCRAFT ARRIVAL CHART - RWY 29") == ["RWY 29 STAR HMA"]
    assert short("VISUAL OPERATION CHART (1: 50 000)", "VISUAL OPERATION CHART (1:250 000)") == \
        ["VISUAL OPERATION 1:50 000", "VISUAL OPERATION 1:250 000"]
    # mapy IFR bez skali i bez HMA bez zmian
    assert short("VISUAL OPERATION CHART") == ["VISUAL OPERATION"]
    assert short("STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO (RNAV RWY 11)") == ["RWY 11 SID"]


# --- serwer: strona AD 4 bieżącej poprawki pakietu
@pytest.fixture
def pansa4(monkeypatch):
    """Udawany docs.pansa.pl: katalogi poprawek (index-v2.html) z srv["on"], strony AD 4 z PAGES4, reszta 404."""
    srv = {"seen": [], "on": {"eaipmil/AIRAC AMDT MIL 11-26_2026_10_29", "eaipvfr/AIRAC AMDT VFR 10-26_2026_10_01",
                              "eaipifr/AIRAC AMDT 11-26_2026_10_29"}}

    def handler(request):
        path = request.url.path
        if path.endswith("/index-v2.html"):
            return httpx.Response(200 if path.removeprefix("/ais/").removesuffix("/index-v2.html") in srv["on"] else 404)
        srv["seen"].append(str(request.url))
        m = re.search(r"/eaip(mil|vfr)/.*/eAIP/AD 4 (EP[A-Z]{2}) 1-en-GB\.html$", path)
        key = m and (m[2], m[1].upper())
        if key in PAGES4:
            return httpx.Response(200, text=ad4_page(*key))
        return httpx.Response(404)

    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))  # noqa: E731
    monkeypatch.setattr(eaip, "_client", client)
    monkeypatch.setattr(eaip, "_page_client", client)
    return srv


DAY = date(2026, 10, 29)   # AIRAC 2611 (AMDT 11-26)


def test_mil_charts_from_current_amendment(pansa4):
    out = asyncio.run(eaip.aerodrome_charts("epks", DAY, link="aip_mil"))
    page = "https://docs.pansa.pl/ais/eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/eAIP/AD%204%20EPKS%201-en-GB.html"
    assert out["icao"] == "EPKS" and out["page"] == page and out["error"] is None
    assert out["charts"] == want4("EPKS", "MIL") and pansa4["seen"] == [page]
    # druga prośba z pamięci
    assert asyncio.run(eaip.aerodrome_charts("EPKS", DAY, link="aip_mil")) == out and len(pansa4["seen"]) == 1


def test_vfr_falls_back_like_ifr(pansa4):
    # brak katalogu VFR 11-26 u PAŻP: strona AD 4 z poprzedniej poprawki 10-26 (jak index-v2.html w /api/config)
    out = asyncio.run(eaip.aerodrome_charts("EPBC", DAY, link="aip_vfr"))
    assert out["page"] == ("https://docs.pansa.pl/ais/eaipvfr/AIRAC%20AMDT%20VFR%2010-26_2026_10_01/eAIP/"
                           "AD%204%20EPBC%201-en-GB.html")
    assert asyncio.run(eaip.resolved_url("aip_vfr", DAY)).startswith(out["page"].split("eAIP/")[0])
    assert [(c["id"], c["title"], c["kind"]) for c in out["charts"]] == \
        [("2-1", "AERODROME", "ADC"), ("3-1", "VISUAL OPERATION 1:50 000", "VFR"), ("4-1", "VISUAL OPERATION 1:250 000", "VFR")]
    assert out["charts"][0]["url"].startswith(PKG4["VFR"].replace("11-26_2026_10_29", "10-26_2026_10_01"))


def test_env_override_and_separate_cache(pansa4, monkeypatch):
    monkeypatch.setattr(settings, "aip_mil_url", PKG4["MIL"] + "index-v2.html")
    monkeypatch.setattr(settings, "aip_vfr_url", PKG4["VFR"] + "index-v2.html")
    mil = asyncio.run(eaip.aerodrome_charts("EPKS", link="aip_mil"))
    vfr = asyncio.run(eaip.aerodrome_charts("EPML", link="aip_vfr"))
    assert mil["page"] == page4_url("EPKS", "MIL") and vfr["page"] == page4_url("EPML", "VFR")
    assert vfr["charts"] == want4("EPML", "VFR")
    # osobny wpis pamięci na pakiet (klucz: adres strony); lotnisko bez strony: komunikat jak w AD CIV
    assert pansa4["seen"] == [page4_url("EPKS", "MIL"), page4_url("EPML", "VFR")]
    gone = asyncio.run(eaip.aerodrome_charts("EPZW", link="aip_vfr"))
    assert gone == {"icao": "EPZW", "page": page4_url("EPZW", "VFR"), "charts": [], "error": "HTTP 404"}


# --- GET /api/docs/charts/<ifr|mil|vfr>/<ICAO>
def test_package_charts_endpoint(monkeypatch):
    seen = []

    async def fake(icao, today=None, link="aip_ifr"):
        seen.append((icao, link))
        return {"icao": icao, "page": "", "charts": [], "error": None}

    monkeypatch.setattr(eaip, "aerodrome_charts", fake)
    client = TestClient(main.app)
    for path, call in (("mil/epks", ("EPKS", "aip_mil")), ("VFR/EPBC", ("EPBC", "aip_vfr")), ("ifr/EPWA", ("EPWA", "aip_ifr")),
                       ("vfr/epzw", ("EPZW", "aip_vfr"))):
        r = client.get(f"/api/docs/charts/{path}")
        assert r.status_code == 200 and r.json()["icao"] == call[0] and seen[-1] == call, path
    n = len(seen)
    # lotnisko spoza listy pakietu (EPWA nie ma w AD 4 eAIP VFR, EPKS nie ma w AD 2 eAIP IFR): 404 bez pobierania
    for path in ("vfr/EPWA", "ifr/EPKS", "mil/EPBC"):
        r = client.get(f"/api/docs/charts/{path}")
        assert r.status_code == 404 and r.json()["detail"] == f"Aerodrome charts: no charts for {path[4:]}", path
    r = client.get("/api/docs/charts/xyz/EPWA")
    assert r.status_code == 404 and r.json()["detail"] == "Aerodrome charts: unknown AIP (ifr, mil or vfr)"
    for bad in ("KJFK", "EP1A", "EPWAX"):
        r = client.get(f"/api/docs/charts/mil/{bad}")
        assert r.status_code == 400 and "EP + 2 letters" in r.json()["detail"], bad
    assert len(seen) == n
    # stary adres AD CIV: IFR, wywołanie bez pakietu
    assert client.get("/api/docs/charts/epzg").status_code == 200 and seen[-1] == ("EPZG", "aip_ifr")
    assert client.get("/api/docs/charts/EPKS").status_code == 404


# --- listy lotnisk: te same w services/eaip.py i frontend/js/tabs/aip.js
def _js_list(name):
    block = AIP_JS[AIP_JS.index(f"export const {name} = ["):]
    block = block[:block.index("]];") + 3]
    return re.findall(r'\["(EP[A-Z]{2})", "([^"]+)"\]', block)


def test_lists_match_frontend():
    mil, vfr = _js_list("AD_MIL"), _js_list("AD_VFR")
    assert tuple(i for i, _ in mil) == eaip.MIL_AERODROMES and tuple(i for i, _ in vfr) == eaip.VFR_AERODROMES
    assert len(eaip.MIL_AERODROMES) == 15 and len(eaip.VFR_AERODROMES) == 69 and len(eaip.AD2_AERODROMES) == 15
    for codes in eaip.AERODROMES.values():
        assert list(codes) == sorted(set(codes))
    sets = [set(c) for c in eaip.AERODROMES.values()]
    assert sum(len(s) for s in sets) == len(set().union(*sets)) == 99   # rozłączne (AD 1.3 eAIP IFR: 99 lotnisk)
    assert eaip.AERODROMES == {"aip_ifr": eaip.AD2_AERODROMES, "aip_mil": eaip.MIL_AERODROMES,
                               "aip_vfr": eaip.VFR_AERODROMES}
    # nazwy jak w AIP, w kodzie JS jako \\uXXXX
    names = {i: n.encode().decode("unicode_escape") for i, n in mil + vfr}
    assert names["EPKS"] == "POZNAŃ/Krzesiny" and names["EPBC"] == "WARSZAWA - BABICE" and names["EPZR"] == "ŻAR k/Żywca"
    assert names["EPIR"] == names["EPIN"] == "INOWROCŁAW"
