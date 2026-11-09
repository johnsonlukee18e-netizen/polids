"""Zdjęcia typów w AIRCRAFT (services/photos.py), 0.13.3: Marek "czemu w zakladce aircrafs np BCS3 ma zdjecie
A321 neo?". Wyszukiwarka Wikipedii dawała dla "AIRBUS A-220-300" artykuł o innym Airbusie, a aplikacja brała pierwszy
wynik i zapisywała go na stałe. Teraz: artykuł z TITLES (A220, CRJ, MD-80), hasło Airbusa bez łącznika, wybór
artykułu o tym modelu (numer w tytule albo przekierowaniu, nazwa typu z producentem), odrzucanie tytułów z innym
numerem i ponowne sprawdzenie złych zdjęć zapisanych wcześniej (bez ruszania własnych). Wikipedia nie jest dostępna
z tego środowiska, więc odpowiedzi API są podstawione (httpx.MockTransport)."""
import json
import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import asyncio  # noqa: E402
import time  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.services import photos  # noqa: E402
from backend.app.services.photos import (TITLES, _words, fetch_photo, local_photo, model_numbers,  # noqa: E402
                                         photo_query, pick, recheck, stale, title_fit, type_photo)

JPEG = b"\xff\xd8\xff\xe0test"
OLD = time.time() - 30 * 86400  # pliki pobrane przez 0.13.2 miesiąc temu
MODELS = {r["ICAO"]: r for r in json.loads((ROOT_DIR / "data" / "import" / "ICAO_Aircraft.json").read_text("utf-8-sig"))}


@pytest.fixture
def photo_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "photos_dir", tmp_path)
    monkeypatch.setattr(photos, "_missing", set())
    return tmp_path


def wiki(monkeypatch, search=None, pages=None, redirects=None, down=False):
    """Podstawiona Wikipedia: search – wyniki list=search, pages – tytuł -> adres miniatury (None: artykuł bez
    grafiki), redirects – przekierowania w zapytaniu o tytuły, down – każde zapytanie kończy się błędem połączenia.
    Zwraca listę zapytań (słowniki parametrów, {"image": adres} dla pobrania obrazu)."""
    calls = []

    def handler(request):
        if down:
            raise httpx.ConnectError("unreachable")
        if request.url.host == "upload.wikimedia.org":
            calls.append({"image": str(request.url)})
            return httpx.Response(200, content=JPEG + str(request.url).encode())
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


def img(name, ext="jpg"):
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/x/{name}.{ext}"


def fetch(code):
    r = MODELS[code]
    return asyncio.run(fetch_photo(code, r["Manufacturer"], r["Model"]))


def get(code):
    r = MODELS[code]
    return asyncio.run(type_photo(code, r["Manufacturer"], r["Model"]))


def old_auto(dir_, code, title, ext="jpg", **extra):
    """Zdjęcie zapisane przez 0.13.2: obraz, potem opis bez "v" (oba sprzed miesiąca)."""
    f = dir_ / f"{code}.{ext}"
    f.write_bytes(b"old")
    meta = dir_ / f"{code}.json"
    meta.write_text(json.dumps({"credit": f"Wikipedia: {title}", "page": "p", "image": img("old", ext), **extra}),
                    "utf-8")
    os.utime(f, (OLD, OLD))
    os.utime(meta, (OLD + 1, OLD + 1))
    return f


# --- hasło, numery modelu, tytuły ---

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
    airbus = [r for r in MODELS.values() if (r.get("Manufacturer") or "").strip().upper() == "AIRBUS"]
    assert len(airbus) > 20
    assert [r["ICAO"] for r in airbus if " A-" in photo_query(r["Manufacturer"], r.get("Model"))] == []
    assert MODELS["BCS3"]["Model"] == "A-220-300"
    assert photo_query("AIRBUS", MODELS["BCS3"]["Model"]) == "AIRBUS A220-300"


def test_model_numbers():
    assert model_numbers("A-220-300") == {"220"}
    assert model_numbers("A-300(B4/C4/F4)-600") == {"300"}
    assert model_numbers("A-321neo") == {"321"}
    assert model_numbers("737 MAX 8") == {"737"}
    assert model_numbers("747-8, VC-25B") == {"747", "25"}
    # jedna cyfra po literach i łączniku to numer modelu, liczba po niej to wersja
    assert model_numbers("DC-9-10") == {"9"}
    assert model_numbers("DHC-8-400 Dash 8") == {"8"}
    assert model_numbers("An-2") == {"2"}
    assert model_numbers("CL-600 Regional Jet CRJ-705/900, Challenger 890") == {"600", "705", "900", "890"}
    assert model_numbers("EMB-500 Phenom 100") == {"500", "100"}
    assert model_numbers("BAe-3100 Jetstream 31") == {"3100", "31"}
    assert model_numbers("190 (Lineage 1000)") == {"190"}
    # liczba po ukośniku: wersja za oznaczeniem z wersją, model za oznaczeniem bez wersji
    assert model_numbers("ATR-42-300/320") == {"42"}
    assert model_numbers("ATR-72-212A/500") == {"72"}
    assert model_numbers("PA-31-300/310") == {"31"}
    assert model_numbers("Tu-204/214/224/234") == {"204", "214", "224", "234"}
    assert model_numbers("BD-700 Global 7000/8000") == {"700", "7000", "8000"}
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
    assert title_fit("Embraer E-Jet E2 family", model_numbers("E190-E2")) == "neutral"
    assert title_fit("Embraer Phenom 100", model_numbers("EMB-500 Phenom 100")) == "exact"
    dc9 = model_numbers("DC-9-10")
    assert title_fit("McDonnell Douglas DC-9", dc9) == "exact"
    assert title_fit("McDonnell Douglas DC-10", dc9) == "other"
    assert title_fit("De Havilland Canada Dash 8", model_numbers("DHC-8-400 Dash 8")) == "neutral"
    assert title_fit("Boeing 747-8", model_numbers("737 MAX 8")) == "other"
    assert title_fit("Boeing 747-8", model_numbers("747-8, VC-25B")) == "exact"


# --- wybór artykułu z wyników wyszukiwania ---

def test_pick_rejects_other_airbus():
    results = [{"title": "Airbus A321neo"}, {"title": "Airbus A300"}, {"title": "Airbus"},
               {"title": "Airbus A220", "redirecttitle": "Airbus A220-300"}, {"title": "Airbus A320neo family"}]
    assert pick(results, model_numbers("A-220-300")) == ["Airbus A220", "Airbus"]
    assert pick(results[:2], model_numbers("A-220-300")) == []


def test_pick_keeps_search_order_among_matches():
    nums = model_numbers("A-321neo")
    results = [{"title": "Narrow-body aircraft"}, {"title": "Airbus A320neo family", "redirecttitle": "Airbus A321neo"},
               {"title": "Airbus A321"}, {"title": "Boeing 737 MAX"}]
    # numer w tytule i numer w przekierowaniu w kolejności wyszukiwarki, tytuł bez liczb na końcu
    assert pick(results, nums) == ["Airbus A320neo family", "Airbus A321", "Narrow-body aircraft"]
    # model bez numeru: kolejność wyszukiwarki bez tytułów z liczbami nie ma znaczenia
    assert pick(results, set()) == [r["title"] for r in results]


def test_pick_dc9_not_dc10():
    results = [{"title": "McDonnell Douglas DC-10"}, {"title": "McDonnell Douglas DC-9"}, {"title": "McDonnell Douglas"}]
    assert pick(results, model_numbers("DC-9-10")) == ["McDonnell Douglas DC-9", "McDonnell Douglas"]


def test_pick_family_article_via_redirect():
    nums = model_numbers("BD-100 Challenger 350/3500")
    results = [{"title": "Bombardier Challenger 300", "redirecttitle": "Bombardier Challenger 350"},
               {"title": "Bombardier Challenger 600 series"}]
    assert pick(results, nums, _words("BD-100 Challenger 350/3500"), _words("BOMBARDIER")) == \
        ["Bombardier Challenger 300"]


def test_pick_named_variants_over_base_model():
    """Beluga, Dreamlifter i Super Guppy mają artykuły bez numeru; artykuł o bazowym samolocie ma numer modelu,
    ale nie wyprzedza wyższego w wyszukiwarce artykułu z nazwą typu i producenta."""
    def go(code, titles):
        r = MODELS[code]
        return pick([{"title": t} for t in titles], model_numbers(r["Model"]), _words(r["Model"]),
                    _words(r["Manufacturer"]))

    assert go("A3ST", ["Airbus Beluga", "Airbus BelugaXL", "Airbus A300"])[0] == "Airbus Beluga"
    assert go("A337", ["Airbus BelugaXL", "Airbus A330"])[0] == "Airbus BelugaXL"
    assert go("BLCF", ["Boeing Dreamlifter", "Boeing 747-400", "Boeing 787 Dreamliner"]) == \
        ["Boeing Dreamlifter", "Boeing 747-400"]
    assert go("SGUP", ["Aero Spacelines Super Guppy", "Boeing 377 Stratocruiser"])[0] == "Aero Spacelines Super Guppy"
    # nazwa typu bez producenta w tytule nie wystarcza (Cutlass Cessny to nie Vought F7U)
    assert go("C172", ["Vought F7U Cutlass", "Cessna 172"]) == ["Cessna 172", "Vought F7U Cutlass"]
    # nazwa typu nie ratuje tytułu z innym numerem
    assert go("E50P", ["Embraer Phenom 300", "Embraer Phenom 100"]) == ["Embraer Phenom 100"]
    # Dash 8: tytuł bez numeru z nazwą typu i producenta przed innymi tytułami bez liczb
    assert go("DH8D", ["Turboprop", "De Havilland Canada Dash 8"]) == ["De Havilland Canada Dash 8", "Turboprop"]


# --- pobieranie (podstawiona Wikipedia) ---

def test_fetch_bcs3_uses_a220_article(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    got = fetch("BCS3")
    assert got["url"].startswith("/files/photos/BCS3.jpg?v=")
    assert got["credit"] == "Wikipedia: Airbus A220" and got["page"] == "https://en.wikipedia.org/wiki/Airbus_A220"
    assert calls[0]["titles"] == "Airbus A220" and calls[0]["redirects"] == "1"
    assert not any(c.get("list") == "search" for c in calls)
    meta = json.loads((photo_dir / "BCS3.json").read_text("utf-8"))
    assert meta["v"] == photos.META_VERSION == 2 and meta["image"] == img("A220") and meta["query"] == "AIRBUS A220-300"


def test_titles_follow_redirect(monkeypatch, photo_dir):
    """Artykuł z TITLES przeniesiony pod inny tytuł: zdjęcie z artykułu docelowego."""
    wiki(monkeypatch, pages={"Mitsubishi CRJ700 series": img("CRJ")},
         redirects=[{"from": "Bombardier CRJ700 series", "to": "Mitsubishi CRJ700 series"}])
    assert fetch("CRJ9")["credit"] == "Wikipedia: Mitsubishi CRJ700 series"


def test_titles_without_image_no_search(monkeypatch, photo_dir):
    """Typ z TITLES bierze zdjęcie tylko z tego artykułu (wyszukiwarka dałaby CRJ9 Challengera 600 przez "CL-600")."""
    calls = wiki(monkeypatch, search=[{"title": "Bombardier Challenger 600 series"}],
                 pages={"Bombardier CRJ700 series": None, "Bombardier Challenger 600 series": img("CL60")})
    assert fetch("CRJ9") is None and "CRJ9" in photos._missing and list(photo_dir.iterdir()) == []
    assert not any(c.get("list") == "search" for c in calls)


def test_fetch_search_picks_model_number(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, search=[{"title": "Airbus A320neo family"}, {"title": "Airbus A321"},
                                      {"title": "Airbus A321neo"}],
                 pages={"Airbus A321": None, "Airbus A321neo": img("A21N"), "Airbus A320neo family": img("A20N")})
    got = fetch("A21N")
    # A321 bez grafiki, więc A321neo; A320neo family (inny numer) nawet nie pytany
    assert got["credit"] == "Wikipedia: Airbus A321neo"
    search = next(c for c in calls if c.get("list") == "search")
    assert search["srsearch"] == "AIRBUS A321neo aircraft" and search["srlimit"] == "5"
    assert search["srprop"] == "redirecttitle"
    assert next(c for c in calls if "titles" in c)["titles"] == "Airbus A321|Airbus A321neo"
    assert calls[-1] == {"image": img("A21N")}


def test_fetch_dc91(monkeypatch, photo_dir):
    wiki(monkeypatch, search=[{"title": "McDonnell Douglas DC-10"}, {"title": "McDonnell Douglas DC-9"}],
         pages={"McDonnell Douglas DC-10": img("DC10"), "McDonnell Douglas DC-9": img("DC9")})
    assert fetch("DC91")["credit"] == "Wikipedia: McDonnell Douglas DC-9"


def test_fetch_nothing_matching(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, search=[{"title": "Airbus A300"}], pages={"Airbus A300": img("A300")})
    assert asyncio.run(fetch_photo("A318", "AIRBUS", "A-318")) is None
    assert list(photo_dir.iterdir()) == [] and not any("image" in c for c in calls)
    n = len(calls)
    assert asyncio.run(fetch_photo("A318", "AIRBUS", "A-318")) is None
    assert len(calls) == n  # zapamiętane do restartu


def test_fetch_png_replaces_only_downloaded_file(monkeypatch, photo_dir):
    old_auto(photo_dir, "E190", "Embraer Lineage 1000")
    (photo_dir / "E190.webp").write_bytes(b"own")  # własne, przesłonięte przez pobrane .jpg
    wiki(monkeypatch, search=[{"title": "Embraer E-Jet family", "redirecttitle": "Embraer 190"}],
         pages={"Embraer E-Jet family": img("E190", "png")})
    got = fetch("E190")
    assert got["url"].startswith("/files/photos/E190.png?v=")
    assert not (photo_dir / "E190.jpg").exists() and (photo_dir / "E190.webp").read_bytes() == b"own"


# --- zdjęcia zapisane wcześniej ---

def test_stale():
    old = {"credit": "Wikipedia: Airbus A321neo", "page": "x"}
    assert stale(old, "A-220-300")
    assert not stale({**old, "v": 2}, "A-220-300")
    assert stale({**old, "v": 1}, "A-220-300")
    assert not stale({"credit": "Wikipedia: Airbus A220"}, "A-220-300")
    assert not stale({"credit": "Wikipedia: Airbus"}, "A-220-300")
    assert not stale({"credit": "J. Kowalski"}, "A-220-300")
    assert not stale({}, "A-220-300")
    assert stale({"credit": "Wikipedia: McDonnell Douglas DC-10"}, "DC-9-10")
    # typ z TITLES: każdy inny artykuł (także bez liczb w tytule) jest do sprawdzenia
    assert stale({"credit": "Wikipedia: Airbus"}, "A-220-300", "Airbus A220")
    assert not stale({"credit": "Wikipedia: Airbus A220"}, "A-220-300", "Airbus A220")
    assert not stale({"credit": "Wikipedia: Bombardier CRJ700 series"}, MODELS["CRJ9"]["Model"], TITLES["CRJ9"])
    # ręcznie wpisane pola innego typu nie wywracają sprawdzenia
    assert not stale({"credit": ["Wikipedia: X"]}, "A-220-300")
    assert stale({"credit": "Wikipedia: Airbus A321neo", "v": "2"}, "A-220-300")


def test_recheck_only_downloaded_photo(photo_dir):
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    assert recheck("BCS3", "A-220-300")
    # własne zdjęcie wrzucone w miejsce pobranego, stary opis został
    own = photo_dir / "BCS3.jpg"
    own.write_bytes(b"own")
    assert not recheck("BCS3", "A-220-300")
    # opis bez adresu grafiki Wikipedii (wpisany ręcznie)
    (photo_dir / "CRJ9.jpg").write_bytes(b"own")
    (photo_dir / "CRJ9.json").write_text(json.dumps({"credit": "Wikipedia: Bombardier CRJ900"}), "utf-8")
    assert not recheck("CRJ9", MODELS["CRJ9"]["Model"])
    # wyświetlany jest inny plik niż pobrany (pobrany .png, własny .jpg przed nim)
    old_auto(photo_dir, "A21N", "Airbus A320neo family", ext="png")
    (photo_dir / "A21N.jpg").write_bytes(b"own")
    assert not recheck("A21N", "A-321neo")
    # bez opisu, uszkodzony opis
    (photo_dir / "B738.jpg").write_bytes(b"own")
    (photo_dir / "A319.jpg").write_bytes(b"own")
    (photo_dir / "A319.json").write_text("{zepsuty", "utf-8")
    assert not recheck("B738", "737-800") and not recheck("A319", "A-319") and not recheck("ZZZZ", None)


def test_type_photo_replaces_wrong_photo(monkeypatch, photo_dir):
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    before = local_photo("BCS3")["url"]
    wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    got = get("BCS3")
    assert got["credit"] == "Wikipedia: Airbus A220"
    # nowy adres: przeglądarka i Cloudflare nie pokażą starego obrazu
    assert got["url"] != before and got["url"].startswith("/files/photos/BCS3.jpg?v=")
    assert (photo_dir / "BCS3.jpg").read_bytes().startswith(JPEG)
    assert sorted(f.name for f in photo_dir.iterdir()) == ["BCS3.jpg", "BCS3.json"]


def test_type_photo_keeps_old_without_better_article(monkeypatch, photo_dir):
    """Rodzina opisana artykułem o innym numerze (An-158 w artykule o An-148): bez lepszego artykułu zdjęcie zostaje
    i nie jest więcej sprawdzane."""
    old_auto(photo_dir, "A158", "Antonov An-148")
    calls = wiki(monkeypatch, search=[{"title": "Antonov An-148"}], pages={"Antonov An-148": img("A148")})
    got = get("A158")
    assert got["credit"] == "Wikipedia: Antonov An-148" and (photo_dir / "A158.jpg").read_bytes() == b"old"
    assert json.loads((photo_dir / "A158.json").read_text("utf-8"))["v"] == 2
    assert not recheck("A158", "An-158")
    n = len(calls)
    monkeypatch.setattr(photos, "_missing", set())
    assert get("A158")["credit"] == "Wikipedia: Antonov An-148" and len(calls) == n


def test_type_photo_keeps_old_when_wikipedia_down(monkeypatch, photo_dir):
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    wiki(monkeypatch, down=True)
    assert get("BCS3")["credit"] == "Wikipedia: Airbus A321neo"
    assert recheck("BCS3", "A-220-300")  # sprawdzane przy następnym otwarciu
    with pytest.raises(httpx.ConnectError):
        get("BCS1")


def test_type_photo_never_fetches_over_own(monkeypatch, photo_dir):
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    (photo_dir / "BCS3.jpg").write_bytes(b"own")
    calls = wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    assert get("BCS3")["url"].startswith("/files/photos/BCS3.jpg?v=") and calls == []
    assert (photo_dir / "BCS3.jpg").read_bytes() == b"own"


# --- cała ścieżka przez API ---

@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_api_refetches_wrong_bcs3(client, monkeypatch, photo_dir):
    # /files/photos podaje pliki z katalogu testu (montowany przy starcie aplikacji)
    mount = next(r for r in main.app.routes if getattr(r, "path", "") == "/files/photos")
    monkeypatch.setattr(mount.app, "all_directories", [photo_dir])
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    calls = wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    a = client.get("/api/aircraft", params={"q": "BCS3"}).json()[0]
    assert a["icao"] == "BCS3"
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 200 and r.json()["credit"] == "Wikipedia: Airbus A220"
    n = len(calls)
    # drugi raz z dysku, bez pobierania; plik pod adresem z odpowiedzi
    again = client.get(f"/api/aircraft/{a['id']}/photo").json()
    assert again == r.json() and len(calls) == n
    assert client.get(again["url"]).content.startswith(JPEG)  # adres z "?v=" podaje nowy plik


def test_api_no_matching_article_is_404(client, monkeypatch, photo_dir):
    wiki(monkeypatch, search=[{"title": "Airbus A321neo"}], pages={"Airbus A321neo": img("A21N")})
    a = client.get("/api/aircraft", params={"q": "A318"}).json()[0]
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 404 and r.json()["detail"] == "No photo of this type"
    assert list(photo_dir.iterdir()) == []
