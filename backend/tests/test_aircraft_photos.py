"""Zdjęcia typów w AIRCRAFT (services/photos.py), 0.13.3: Marek "czemu w zakladce aircrafs np BCS3 ma zdjecie
A321 neo?". Wyszukiwarka Wikipedii dawała dla "AIRBUS A-220-300" artykuł o innym Airbusie, a aplikacja brała pierwszy
wynik i zapisywała go na stałe. Teraz: artykuł z TITLES (A220, CRJ, MD-80), hasło Airbusa bez łącznika, wybór
artykułu z numerem modelu w tytule, odrzucanie tytułów z innym numerem i ponowne pobranie złych zdjęć zapisanych
wcześniej. Wikipedia nie jest dostępna z tego środowiska, więc odpowiedzi API są podstawione (httpx.MockTransport)."""
import json
import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import asyncio  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.routers import aircraft as aircraft_router  # noqa: E402
from backend.app.services import photos  # noqa: E402
from backend.app.services.photos import (TITLES, cached_photo, fetch_photo, model_numbers, photo_query,  # noqa: E402
                                         pick, stale, title_fit)

JPEG = b"\xff\xd8\xff\xe0test"


@pytest.fixture
def photo_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "photos_dir", tmp_path)
    monkeypatch.setattr(photos, "_missing", set())
    return tmp_path


def wiki(monkeypatch, search=None, pages=None, redirects=None):
    """Podstawiona Wikipedia: search – wyniki list=search, pages – tytuł -> adres miniatury (None: artykuł bez
    grafiki), redirects – przekierowania w zapytaniu o tytuły. Zwraca listę zapytań (słowniki parametrów)."""
    calls = []

    def handler(request):
        if request.url.host == "upload.wikimedia.org":
            calls.append({"image": str(request.url)})
            return httpx.Response(200, content=JPEG)
        q = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        calls.append(q)
        if q.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": search or []}})
        asked = q["titles"].split("|")
        moved = [r for r in (redirects or []) if r["from"] in asked]
        out = {}
        for i, t in enumerate(asked):
            t = next((r["to"] for r in moved if r["from"] == t), t)
            if t not in (pages or {}):
                out[str(-1 - i)] = {"title": t, "missing": ""}
                continue
            page = {"pageid": 100 + i, "title": t, "fullurl": "https://en.wikipedia.org/wiki/" + t.replace(" ", "_")}
            if pages[t]:
                page["thumbnail"] = {"source": pages[t], "width": 800, "height": 533}
            out[str(100 + i)] = page
        body = {"query": {"pages": out}}
        if moved:
            body["query"]["redirects"] = moved
        return httpx.Response(200, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(photos.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


def img(name):
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/x/{name}.jpg"


def meta_of(dir_, code):
    return json.loads((dir_ / f"{code}.json").read_text("utf-8"))


# --- hasło i numery modelu ---

def test_photo_query_airbus_without_hyphen():
    assert photo_query("AIRBUS", "A-220-300") == "AIRBUS A220-300"
    assert photo_query("AIRBUS", "A-300(B4/C4/F4)-600") == "AIRBUS A300-600"
    assert photo_query("AIRBUS", "A-330-200, A-330-MRTT, KC-30, KC-330 Cygnus") == "AIRBUS A330-200"
    # inni producenci bez zmian, także łącznik po literze
    assert photo_query("BOEING", "737-800, BBJ2") == "BOEING 737-800"
    assert photo_query("ANTONOV", "An-148") == "ANTONOV An-148"
    assert photo_query("AIRBUS HELICOPTERS", "EC-135") == "AIRBUS HELICOPTERS EC-135"
    # nawias z przecinkiem w środku znika przed podziałem po przecinkach
    assert photo_query("BOEING", "747-400 (domestic, no winglets)") == "BOEING 747-400"
    assert photo_query("FOKKER", "50 (Fokker50Freighter, Maritime Enforcer)") == "FOKKER 50"
    assert photo_query(None, None) == ""


def test_no_airbus_query_keeps_hyphen():
    rows = json.loads((ROOT_DIR / "data" / "import" / "ICAO_Aircraft.json").read_text("utf-8-sig"))
    airbus = [r for r in rows if (r.get("Manufacturer") or "").strip().upper() == "AIRBUS"]
    assert len(airbus) > 20
    bad = [r["ICAO"] for r in airbus if " A-" in photo_query(r["Manufacturer"], r.get("Model"))]
    assert bad == []
    by_code = {r["ICAO"]: r for r in rows}
    assert by_code["BCS3"]["Model"] == "A-220-300"
    assert photo_query("AIRBUS", by_code["BCS3"]["Model"]) == "AIRBUS A220-300"


def test_model_numbers():
    assert model_numbers("A-220-300") == {"220"}
    assert model_numbers("A-300(B4/C4/F4)-600") == {"300"}
    assert model_numbers("A-321neo") == {"321"}
    assert model_numbers("737 MAX 8") == {"737"}
    assert model_numbers("DHC-8-400 Dash 8") == {"400"}
    assert model_numbers("CL-600 Regional Jet CRJ-705/900, Challenger 890") == {"600", "705", "900", "890"}
    assert model_numbers("EMB-500 Phenom 100") == {"500", "100"}
    assert model_numbers("BAe-3100 Jetstream 31") == {"3100", "31"}
    assert model_numbers("190 (Lineage 1000)") == {"190"}
    assert model_numbers("ATP") == set() and model_numbers(None) == set()


def test_title_fit():
    nums = model_numbers("A-220-300")
    assert title_fit("Airbus A220", nums) == "exact"
    assert title_fit("Airbus A321neo", nums) == "other"
    assert title_fit("Airbus A320neo family", nums) == "other"
    assert title_fit("Airbus A300", nums) == "other"
    assert title_fit("2019 Airbus accident", nums) == "other"
    assert title_fit("Narrow-body aircraft", nums) == "neutral"
    assert title_fit("Airbus A321", set()) == "neutral"
    assert title_fit("Embraer E-Jet family", model_numbers("190 (Lineage 1000)")) == "neutral"
    assert title_fit("Embraer Phenom 100", model_numbers("EMB-500 Phenom 100")) == "exact"


# --- wybór artykułu z wyników wyszukiwania ---

def test_pick_rejects_other_airbus_for_bcs3():
    results = [{"title": "Airbus A321neo"}, {"title": "Airbus A300"}, {"title": "Airbus"},
               {"title": "Airbus A220", "redirecttitle": "Airbus A220-300"}, {"title": "Airbus A320neo family"}]
    assert pick(results, model_numbers("A-220-300")) == ["Airbus A220", "Airbus"]
    # tylko artykuły o innych modelach: nic
    assert pick(results[:2], model_numbers("A-220-300")) == []


def test_pick_order_title_redirect_neutral():
    nums = model_numbers("A-321neo")
    results = [{"title": "Narrow-body aircraft"}, {"title": "Airbus A320neo family", "redirecttitle": "Airbus A321neo"},
               {"title": "Airbus A321"}, {"title": "Boeing 737 MAX"}]
    assert pick(results, nums) == ["Airbus A321", "Airbus A320neo family", "Narrow-body aircraft"]
    # model bez numeru: kolejność wyszukiwarki
    assert pick(results, set()) == [r["title"] for r in results]


def test_pick_crj900_via_redirect():
    nums = model_numbers("CL-600 Regional Jet CRJ-705/900, Challenger 890")
    results = [{"title": "Bombardier CRJ700 series", "redirecttitle": "Bombardier CRJ900"},
               {"title": "Bombardier CRJ100/200"}]
    assert pick(results, nums) == ["Bombardier CRJ700 series"]


# --- pobieranie (podstawiona Wikipedia) ---

def test_fetch_bcs3_uses_a220_article(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    got = asyncio.run(fetch_photo("BCS3", photo_query("AIRBUS", "A-220-300"), model_numbers("A-220-300")))
    assert got == {"url": "/files/photos/BCS3.jpg", "credit": "Wikipedia: Airbus A220",
                   "page": "https://en.wikipedia.org/wiki/Airbus_A220"}
    assert calls[0]["titles"] == "Airbus A220" and calls[0]["redirects"] == "1"
    assert not any(c.get("list") == "search" for c in calls)
    assert (photo_dir / "BCS3.jpg").read_bytes() == JPEG
    meta = meta_of(photo_dir, "BCS3")
    assert meta["v"] == photos.META_VERSION == 2 and meta["image"] == img("A220") and meta["query"] == "AIRBUS A220-300"


def test_titles_follow_redirect(monkeypatch, photo_dir):
    """Artykuł z TITLES przeniesiony pod inny tytuł: zdjęcie z artykułu docelowego."""
    wiki(monkeypatch, pages={"Mitsubishi CRJ700 series": img("CRJ")},
         redirects=[{"from": "Bombardier CRJ700 series", "to": "Mitsubishi CRJ700 series"}])
    model = "CL-600 Regional Jet CRJ-705/900, Challenger 890"
    got = asyncio.run(fetch_photo("CRJ9", photo_query("CANADAIR", model), model_numbers(model)))
    assert got["credit"] == "Wikipedia: Mitsubishi CRJ700 series"


def test_titles_fallback_to_search(monkeypatch, photo_dir):
    """Artykuł z TITLES bez grafiki: wyszukiwarka, z numerem modelu w tytule."""
    calls = wiki(monkeypatch, search=[{"title": "Airbus A321neo"}, {"title": "Airbus A220"}],
                 pages={"Airbus A220": None, "Airbus A321neo": img("A21N")})
    got = asyncio.run(fetch_photo("BCS1", "AIRBUS A220-100", model_numbers("A-220-100")))
    # A220 bez grafiki, A321neo odrzucony: brak zdjęcia, nic nie zapisane
    assert got is None and "BCS1" in photos._missing and list(photo_dir.iterdir()) == []
    search = next(c for c in calls if c.get("list") == "search")
    assert search["srsearch"] == "AIRBUS A220-100 aircraft" and search["srlimit"] == "5"
    assert search["srprop"] == "redirecttitle"
    assert not any("image" in c for c in calls)


def test_fetch_search_picks_model_number(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, search=[{"title": "Airbus A320neo family"}, {"title": "Airbus A321"},
                                      {"title": "Airbus A321neo"}],
                 pages={"Airbus A321": None, "Airbus A321neo": img("A21N"), "Airbus A320neo family": img("A20N")})
    got = asyncio.run(fetch_photo("A21N", "AIRBUS A321neo", model_numbers("A-321neo")))
    # A321 bez grafiki, więc A321neo; A320neo family (inny numer) nawet nie pytany
    assert got["credit"] == "Wikipedia: Airbus A321neo"
    titles = next(c for c in calls if "titles" in c)["titles"]
    assert titles == "Airbus A321|Airbus A321neo"
    assert calls[-1] == {"image": img("A21N")}


def test_fetch_without_numbers_takes_first_with_image(monkeypatch, photo_dir):
    wiki(monkeypatch, search=[{"title": "British Aerospace ATP"}, {"title": "Hawker Siddeley HS 748"}],
         pages={"British Aerospace ATP": img("ATP"), "Hawker Siddeley HS 748": img("748")})
    got = asyncio.run(fetch_photo("ATP", "BRITISH AEROSPACE ATP", model_numbers("ATP")))
    assert got["credit"] == "Wikipedia: British Aerospace ATP"


def test_fetch_png_and_replaces_old_files(monkeypatch, photo_dir):
    (photo_dir / "E190.webp").write_bytes(b"old")
    wiki(monkeypatch, search=[{"title": "Embraer E-Jet family", "redirecttitle": "Embraer 190"}],
         pages={"Embraer E-Jet family": img("E190").replace(".jpg", ".png")})
    got = asyncio.run(fetch_photo("E190", "EMBRAER 190", model_numbers("190 (Lineage 1000)")))
    assert got["url"] == "/files/photos/E190.png" and not (photo_dir / "E190.webp").exists()


def test_missing_is_remembered(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, search=[{"title": "Airbus A300"}], pages={"Airbus A300": img("A300")})
    assert asyncio.run(fetch_photo("BCS3", "AIRBUS A220-300", {"220"})) is None
    n = len(calls)
    assert asyncio.run(fetch_photo("BCS3", "AIRBUS A220-300", {"220"})) is None
    assert len(calls) == n


# --- zdjęcia zapisane wcześniej ---

def write_photo(dir_, code, meta=None, ext="jpg"):
    (dir_ / f"{code}.{ext}").write_bytes(JPEG)
    if meta is not None:
        (dir_ / f"{code}.json").write_text(json.dumps(meta), "utf-8")


def test_stale():
    old = {"credit": "Wikipedia: Airbus A321neo", "page": "x"}
    assert stale(old, "A-220-300")
    assert not stale({**old, "v": 2}, "A-220-300")
    assert stale({**old, "v": 1}, "A-220-300")
    assert not stale({"credit": "Wikipedia: Airbus A220"}, "A-220-300")
    assert not stale({"credit": "Wikipedia: Airbus"}, "A-220-300")
    assert not stale({"credit": "J. Kowalski"}, "A-220-300")
    assert not stale({}, "A-220-300")
    # typ z TITLES: każdy inny artykuł (także bez liczb w tytule) jest nieaktualny
    assert stale({"credit": "Wikipedia: Airbus"}, "A-220-300", "Airbus A220")
    assert not stale({"credit": "Wikipedia: Airbus A220"}, "A-220-300", "Airbus A220")
    assert stale({"credit": "Wikipedia: Bombardier Challenger 600 series"},
                 "CL-600 Regional Jet CRJ-705/900, Challenger 890", TITLES["CRJ9"])
    assert not stale({"credit": "Wikipedia: Bombardier CRJ700 series"},
                     "CL-600 Regional Jet CRJ-705/900, Challenger 890", TITLES["CRJ9"])


def test_cached_photo_drops_stale(photo_dir):
    write_photo(photo_dir, "BCS3", {"credit": "Wikipedia: Airbus A321neo", "page": "p"})
    photos._missing.add("BCS3")
    assert cached_photo("BCS3", "A-220-300") is None
    assert list(photo_dir.iterdir()) == [] and "BCS3" not in photos._missing


def test_cached_photo_keeps_good_and_own(photo_dir):
    write_photo(photo_dir, "A21N", {"credit": "Wikipedia: Airbus A321neo", "page": "p"})
    write_photo(photo_dir, "E190", {"credit": "Wikipedia: Embraer E-Jet family", "page": "p"})
    write_photo(photo_dir, "A20N", {"credit": "Wikipedia: Airbus A321neo", "v": 2})
    write_photo(photo_dir, "B738")  # własne, bez opisu
    write_photo(photo_dir, "A320", {"credit": "Fot. J. Kowalski"}, ext="png")
    write_photo(photo_dir, "A319", None)
    (photo_dir / "A319.json").write_text("{zepsuty", "utf-8")
    assert cached_photo("A21N", "A-321neo")["credit"] == "Wikipedia: Airbus A321neo"
    assert cached_photo("E190", "190 (Lineage 1000)")["credit"] == "Wikipedia: Embraer E-Jet family"
    assert cached_photo("A20N", "A-320neo")["credit"] == "Wikipedia: Airbus A321neo"
    assert cached_photo("B738", "737-800, BBJ2") == {"url": "/files/photos/B738.jpg", "credit": "", "page": None}
    assert cached_photo("A320", "A-320")["url"] == "/files/photos/A320.png"
    assert cached_photo("A319", "A-319") == {"url": "/files/photos/A319.jpg", "credit": "", "page": None}
    assert len(list(photo_dir.iterdir())) == 11  # nic nie usunięte


# --- cała ścieżka przez API ---

@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_api_refetches_stale_bcs3(client, monkeypatch, photo_dir):
    write_photo(photo_dir, "BCS3", {"credit": "Wikipedia: Airbus A321neo", "page": "p"})
    seen = []

    async def fake(icao, query, nums=None):
        seen.append((icao, query, nums))
        write_photo(photo_dir, "BCS3", {"credit": "Wikipedia: Airbus A220", "page": "q", "v": 2})
        return photos.local_photo(icao)

    monkeypatch.setattr(aircraft_router, "fetch_photo", fake)
    a = client.get("/api/aircraft", params={"q": "BCS3"}).json()[0]
    assert a["icao"] == "BCS3"
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 200 and r.json()["credit"] == "Wikipedia: Airbus A220"
    assert seen == [("BCS3", "AIRBUS A220-300", {"220"})]
    # drugi raz z dysku, bez pobierania
    assert client.get(f"/api/aircraft/{a['id']}/photo").json()["credit"] == "Wikipedia: Airbus A220"
    assert len(seen) == 1


def test_api_no_matching_article_is_404(client, monkeypatch, photo_dir):
    wiki(monkeypatch, search=[{"title": "Airbus A321neo"}], pages={"Airbus A321neo": img("A21N")})
    a = client.get("/api/aircraft", params={"q": "BCS3"}).json()[0]
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 404 and r.json()["detail"] == "No photo of this type"
    assert list(photo_dir.iterdir()) == []
