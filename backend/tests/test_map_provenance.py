"""0.12.6 (issue #21): MAP bez dopisków, skąd jest wartość, opis albo struktura, i bez hierarchii przejmowania w opisie
przestrzeni (dymek TMA, CTA, CTR: tylko nazwa, ID, zakres pionowy, częstotliwość, kto obsługuje i od kiedy).
Komunikaty o awarii źródeł danych neutralne (bez nazwy i adresu źródła)."""
import os
import re
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR  # noqa: E402
from backend.app.routers import nav as nav_api  # noqa: E402
from backend.app.routers import vatsim as vatsim_api  # noqa: E402
from backend.app.services.http_cache import UpstreamError  # noqa: E402

FRONTEND = ROOT_DIR / "frontend"
MAP_JS = ("js/tabs/map.js", "js/airspace.js", "js/viffchart.js")


def _code(name):
    """Kod bez komentarzy (/* */ i // na końcu linii albo w osobnej linii; "https://" w napisie zostaje)."""
    src = re.sub(r"/\*.*?\*/", "", (FRONTEND / name).read_text("utf-8"), flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M)


def test_airspace_tooltip_without_takeover_order():
    """Obraz 4 z issue #21: pod wierszem TMA Gdańsk szła kolejność przejmowania ("GD APP …, ACC per om (TMA Gdańsk):
    EPWW G …"). Zostaje wiersz przestrzeni; kolejności nie ma w MAP nigdzie (także notka pod przełącznikami)."""
    code = _code("js/tabs/map.js")
    for gone in ("chainHtml", "as-ch", "asc-src", "as-chr", "ACC per", "ownership order", "OWNER lists", "r.chs", ".chs."):
        assert gone not in code, gone
    hover = code.split("const hoverHtml = (hits, lv) => {")[1].split("\n  };")[0]
    # wiersz: rodzaj, nazwa z ID, zakres pionowy, kto obsługuje (whoHtml: częstotliwość, znak, imię, od kiedy)
    assert '<td class="lv">${range(r.lo, r.hi)}</td><td>${r.w}</td></tr>`).join("")}</table>`' in hover
    assert "<tr" in hover and hover.count("<tr") == 1
    who = code.split("const whoHtml = (v) => {")[1].split("\n  };")[0]
    assert "since ${hhmm(x.logon_time)}" in who and "top-down:" in who and "unstaffed" in who
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "map.css").read_text("utf-8"), flags=re.S)
    assert ".as-ch" not in css and ".asc" not in css and "as-chr" not in css
    # przegląd: stałe max-width 640 px (dla dawnego wiersza kolejności) ucinało "since HH:MMZ" za ramką dymka;
    # teraz najwyżej szerokość mapy, a na wąskiej mapie zawija się ostatnia kolumna
    tip = re.search(r"\.leaflet-tooltip\.atc-tip\.as-tip \{([^}]*)\}", css).group(1)
    assert "max-width: calc(100% - 8px)" in tip and "640px" not in tip
    assert ".as-tip td:last-child { white-space: normal; }" in css
    # dawny rysunek sektorów z dopisywaną kolejnością (drawSectors, sectorOwners) usunięty z airspace.js
    air = _code("js/airspace.js")
    for gone in ("drawSectors", "sectorOwners", "vacsShort", "chain = false"):
        assert gone not in air, gone


PROVENANCE = ("VATSpy", ".ese", "OWNER", "plvacc.pl", "om.plvacc", "VACS", "EuroScope", "PEGASUS", "as in the NM",
              "(vIFF)", "vIFF:", "vIFF ", "in vIFF", "from vIFF", "VATSIM plan", "VATSIM data", "VATSIM network",
              "VATSIM traffic", "AIRAC", "h  s  r", "h s r", "openaip.net", "OpenAIP aviation", '"OSM"', "IFPS",
              "from the VATSIM", "from the .ese", "data feed")


def _texts(code):
    """Napisy widoczne dla użytkownika: zawartość "…", '…' i `…` (z ${…} w środku), bez adresów /api/… i selektorów."""
    out = re.findall(r'"((?:[^"\\\n]|\\.)*)"', code) + re.findall(r"`((?:[^`\\]|\\.)*)`", code, flags=re.S)
    return [t for t in out if not t.startswith(("/api/", "/static/", "https://", "."))]


@pytest.mark.parametrize("name", MAP_JS)
def test_map_texts_without_provenance(name):
    """Opisy, legendy, nagłówki, podpowiedzi i komunikaty MAP bez źródeł danych (VATSpy, .ese, om, VACS, vIFF,
    VATSIM data feed, PEGASUS_21 …); same dane i nazwy funkcji ("Coverage" zamiast "VATSpy coverage")."""
    bad = [(p, t[:90]) for t in _texts(_code(name)) for p in PROVENANCE if p in t]
    assert not bad, bad


def test_map_functional_names():
    code = _code("js/tabs/map.js")
    # 0.13.1 (issue #25): Traffic jako podtytuł w Visibility settings, Sector capacity → FMP (sekcja i zakładka legendy)
    for text in ('"FIR boundaries"', '<div class="vis-sub">Traffic</div>', "<h4>Visibility settings", "<h4>FMP</h4>",
                 '["viff", "FMP", () => [',
                 ">ACC sector map ↗</a>", '"aviation overlay"', '["osm", "streets"]', "Sector entries <span>",
                 "Flight history <span>", '<div class="fd-sec">Position</div>', '<div class="fd-sec">Flight</div>',
                 '"FIR boundary (separate switch)"', "Hover an aircraft: label; click: flight details and route."):
        assert text in code, text
    # tytuł panelu bez AIRAC (cykl jest w stopce HOME i pod zegarem menu)
    assert '<div class="ms-head"><b>MAP</b>\n' in code
    chart = _code("js/viffchart.js")
    assert '<span class="vf-stat">${esc(now.slice(0, 2))}:${esc(now.slice(2))}Z · peak' in chart
    assert "`ATFCM: ${v.atfcm_status}`" in chart


@pytest.fixture(scope="module")
def client():
    yield TestClient(main.app)  # bez lifespan: awarie źródeł przed pierwszym zapytaniem do bazy


def test_feed_errors_neutral(client, monkeypatch):
    """Awaria data feed i rezerwacji: komunikat bez nazwy i adresu źródła (szczegóły tylko w logu)."""
    async def down():
        raise UpstreamError("https://data.vatsim.net/v3/vatsim-data.json: timeout")

    monkeypatch.setattr(vatsim_api, "get_feed", down)
    monkeypatch.setattr(vatsim_api, "get_bookings", down)
    monkeypatch.setattr(nav_api, "get_feed", down)
    for url in ("/api/vatsim/online", "/api/vatsim/pilots?bbox=44,5,60,35&ep=1", "/api/nav/sectors/online"):
        r = client.get(url)
        assert r.status_code == 502 and r.json()["detail"] == "Network data unavailable", url
    r = client.get("/api/vatsim/bookings")
    assert r.status_code == 502 and r.json()["detail"] == "ATC bookings unavailable"
