"""Zdjęcia typów w AIRCRAFT (services/photos.py), 0.13.3: Marek "czemu w zakladce aircrafs np BCS3 ma zdjecie
A321 neo?". Wyszukiwarka Wikipedii dawała dla "AIRBUS A-220-300" artykuł o innym Airbusie, a aplikacja brała pierwszy
wynik i zapisywała go na stałe. Teraz: artykuł z TITLES (A220, CRJ, MD-80), hasło Airbusa bez łącznika, wybór
artykułu o tym modelu (numer w tytule albo przekierowaniu, nazwa typu z producentem), odrzucanie tytułów z innym
numerem i ponowne sprawdzenie złych zdjęć zapisanych wcześniej (bez ruszania własnych). 0.13.4 (Marek po wdrożeniu:
BCS3 "dalej pokazuje Airbusa"): adres grafiki z dowolnego serwera Wikimedia (thumb.wikimedia.org), rozszerzenie
z samej ścieżki adresu, zdjęcie z artykułu o innym modelu nigdy nie jest pokazywane (bez zastępstwa idzie do replaced/,
a typ zostaje bez zdjęcia), miniatury 960 px, log podmian i ukryć. Wikipedia nie jest dostępna z tego środowiska, więc
odpowiedzi API są podstawione (httpx.MockTransport)."""
import json
import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import asyncio  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.services import photos  # noqa: E402
from backend.app.services.photos import (TITLES, fetch_photo, local_photo, model_numbers, only_exact,  # noqa: E402
                                         photo_query, pick, recheck, stale, title_fit, type_photo, type_words)

JPEG = b"\xff\xd8\xff\xe0test"
REAL_CLIENT = httpx.AsyncClient  # wiki() można wywołać w teście kilka razy (podmienia klienta od nowa)
OLD = time.time() - 30 * 86400  # pliki pobrane przez 0.13.2 miesiąc temu
MODELS = {r["ICAO"]: r for r in json.loads((ROOT_DIR / "data" / "import" / "ICAO_Aircraft.json").read_text("utf-8-sig"))}


@pytest.fixture
def photo_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "photos_dir", tmp_path)
    monkeypatch.setattr(photos, "_missing", set())
    monkeypatch.setattr(photos, "_own_logged", set())
    return tmp_path


def wiki(monkeypatch, search=None, pages=None, redirects=None, redirs=None, down=False, error=False):
    """Podstawiona Wikipedia: search – wyniki list=search, pages – tytuł -> adres miniatury (None: artykuł bez
    grafiki), redirects – przekierowania w zapytaniu o tytuły (from -> to), redirs – tytuł -> tytuły przekierowań
    na artykuł (prop=redirects), down – każde zapytanie kończy się błędem połączenia, error – API odpowiada błędem
    w treści z kodem 200 (jak przeciążona wyszukiwarka). Zwraca listę zapytań (słowniki parametrów,
    {"image": adres} dla pobrania obrazu)."""
    calls = []

    def handler(request):
        if down:
            raise httpx.ConnectError("unreachable")
        wikimedia = request.url.host.endswith(".wikimedia.org")
        if error and not wikimedia:
            calls.append({"error": True})
            return httpx.Response(200, json={"error": {"code": "search-error", "info": "Search is currently too busy"}},
                                  headers={"MediaWiki-API-Error": "search-error"})
        if wikimedia:
            calls.append({"image": str(request.url)})
            return httpx.Response(200, content=JPEG + str(request.url).encode())
        q = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        calls.append(q)
        if q.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": search or []}})
        asked = q["titles"].split("|")
        if q.get("prop") == "redirects":
            return httpx.Response(200, json={"query": {"pages": {str(100 + i): {
                "title": t, "redirects": [{"ns": 0, "title": x} for x in (redirs or {}).get(t, [])]}
                for i, t in enumerate(asked)}}})
        moved = [r for r in (redirects or []) if r["from"] in asked]
        out = {}
        for i, t in enumerate(asked):
            t = next((r["to"] for r in moved if r["from"] == t), t)
            if t not in (pages or {}):
                out[str(-1 - i)] = {"title": t, "missing": ""}
                continue
            page = {"pageid": 100 + i, "title": t, "fullurl": "https://en.wikipedia.org/wiki/" + t.replace(" ", "_")}
            if pages[t]:
                page["thumbnail"] = {"source": pages[t], "width": 960, "height": 640}
            out[str(100 + i)] = page
        body = {"query": {"pages": out}}
        if moved:
            body["query"]["redirects"] = moved
        return httpx.Response(200, json=body)

    monkeypatch.setattr(photos.httpx, "AsyncClient",
                        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return calls


def img(name, ext="jpg", host="upload.wikimedia.org"):
    return f"https://{host}/wikipedia/commons/thumb/x/{name}.{ext}/960px-{name}.{ext}"


def fetch(code):
    r = MODELS[code]
    return asyncio.run(fetch_photo(code, r["Manufacturer"], r["Model"]))


def get(code):
    r = MODELS[code]
    return asyncio.run(type_photo(code, r["Manufacturer"], r["Model"]))


def old_auto(dir_, code, title, ext="jpg", image=None, **extra):
    """Zdjęcie zapisane przez 0.13.2: obraz, potem opis bez "v" (oba sprzed miesiąca); image: adres grafiki w opisie."""
    f = dir_ / f"{code}.{ext}"
    f.write_bytes(b"old")
    meta = dir_ / f"{code}.json"
    meta.write_text(json.dumps({"credit": f"Wikipedia: {title}", "page": "p", "image": image or img("old", ext),
                                **extra}), "utf-8")
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
    # primary: tylko pierwsza nazwa (ta z hasła), bez nazw wojskowych i handlowych
    assert model_numbers("ERJ-145, C-99", primary=True) == {"145"}
    assert model_numbers("CL-600 Regional Jet CRJ-705/900, Challenger 890", primary=True) == {"600", "705", "900"}


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
    # numer tylko z dalszej nazwy: nie inny model, ale też nie artykuł o tym typie
    e145 = model_numbers("ERJ-145, C-99"), model_numbers("ERJ-145, C-99", primary=True)
    assert title_fit("Embraer R-99", *e145) == "alias" and title_fit("Embraer ERJ family", *e145) == "neutral"
    assert title_fit("Embraer Legacy 600", *e145) == "other"
    # ten sam numer z łącznikiem w nazwie ICAO i spacją w tytule
    assert title_fit("Schweizer SGM 2-37", model_numbers("SGM-2-37, TG-7")) == "exact"


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


def args(code):
    r = MODELS[code]
    return (model_numbers(r["Model"]), model_numbers(r["Model"], primary=True), *type_words(r["Manufacturer"], r["Model"]))


def test_pick_family_article_via_redirect():
    """Artykuł o rodzinie nazwany numerem innego modelu: pasuje przez przekierowanie z numerem tego modelu, podane
    przez wyszukiwarkę ("redirecttitle") albo z listy przekierowań na artykuł."""
    results = [{"title": "Bombardier Challenger 300"}, {"title": "Bombardier Challenger 600 series"},
               {"title": "Bombardier Aviation"}]
    assert pick(results, *args("CL35")) == ["Bombardier Aviation"]
    assert pick(results, *args("CL35"), strict=True) == []
    redirs = {"Bombardier Challenger 300": ["Bombardier Challenger 350", "BD-100"]}
    assert pick(results, *args("CL35"), redirects=redirs) == ["Bombardier Challenger 300", "Bombardier Aviation"]
    assert pick(results, *args("CL35"), redirects=redirs, strict=True) == ["Bombardier Challenger 300"]
    hit = [{"title": "Bombardier Challenger 300", "redirecttitle": "Bombardier Challenger 350"}]
    assert pick(hit, *args("CL35"), strict=True) == ["Bombardier Challenger 300"]


def test_pick_alias_number_after_type_article():
    """E145 ("ERJ-145, C-99"): Embraer R-99 (radarowy, numer z nazwy wojskowej) nie wyprzedza artykułu o ERJ."""
    results = [{"title": "Embraer ERJ family"}, {"title": "Embraer Legacy 600"}, {"title": "Embraer R-99"}]
    assert pick(results, *args("E145")) == ["Embraer ERJ family", "Embraer R-99"]
    # przekierowania na R-99 z numerem cywilnego płatowca nie robią z niego artykułu o ERJ
    assert pick(list(reversed(results)), *args("E145"),
                redirects={"Embraer ERJ family": ["Embraer ERJ 145"], "Embraer R-99": ["EMB 145 AEW&C"]}) == \
        ["Embraer ERJ family", "Embraer R-99"]


def test_pick_named_variants_over_base_model():
    """Beluga, Dreamlifter i Super Guppy mają artykuły bez numeru; artykuł o bazowym samolocie ma numer modelu,
    ale nie wyprzedza wyższego w wyszukiwarce artykułu z nazwą typu i producenta."""
    def go(code, titles):
        return pick([{"title": t} for t in titles], *args(code))

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
    # nazwa producenta w nazwie typu to nie nazwa typu: artykuł o firmie nie wyprzedza artykułu o modelu
    assert go("GLF6", ["Gulfstream Aerospace", "Gulfstream G650"]) == ["Gulfstream G650", "Gulfstream Aerospace"]
    assert type_words("DIAMOND", "DA-40 Diamond Star") == ({"star"}, {"diamond"})


# --- pobieranie (podstawiona Wikipedia) ---

def test_fetch_bcs3_uses_a220_article(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    got = fetch("BCS3")
    assert got["url"].startswith("/files/photos/BCS3.jpg?v=")
    assert got["credit"] == "Wikipedia: Airbus A220" and got["page"] == "https://en.wikipedia.org/wiki/Airbus_A220"
    assert calls[0]["titles"] == "Airbus A220" and calls[0]["redirects"] == "1"
    # 0.13.4: standardowa szerokość miniatur Wikimedia (inne serwer miniatur ogranicza albo odrzuca)
    assert calls[0]["pithumbsize"] == "960" == str(photos.THUMB_WIDTH)
    assert not any(c.get("list") == "search" for c in calls)
    meta = json.loads((photo_dir / "BCS3.json").read_text("utf-8"))
    assert meta["v"] == photos.META_VERSION == 3 and meta["image"] == img("A220") and meta["query"] == "AIRBUS A220-300"


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
    # A321 bez grafiki, więc A321neo
    assert got["credit"] == "Wikipedia: Airbus A321neo"
    search = next(c for c in calls if c.get("list") == "search")
    assert search["srsearch"] == "AIRBUS A321neo aircraft" and search["srlimit"] == "5"
    assert search["srprop"] == "redirecttitle"
    # A320neo family (inny numer) sprawdzony przez przekierowania na artykuł, bez numeru 321 odpada
    assert next(c for c in calls if c.get("prop") == "redirects")["titles"] == "Airbus A320neo family"
    assert next(c for c in calls if c.get("prop") == "pageimages|info")["titles"] == "Airbus A321|Airbus A321neo"
    assert calls[-1] == {"image": img("A21N")}


def test_fetch_family_via_redirect_list(monkeypatch, photo_dir):
    """Wyszukiwarka nie podaje przekierowania, przez które znalazła artykuł: lista przekierowań na artykuł."""
    calls = wiki(monkeypatch, search=[{"title": "Bombardier Aviation"}, {"title": "Bombardier Challenger 300"}],
                 pages={"Bombardier Aviation": img("BA"), "Bombardier Challenger 300": img("CL30")},
                 redirs={"Bombardier Challenger 300": ["Bombardier Challenger 350", "Challenger 300"]})
    assert fetch("CL35")["credit"] == "Wikipedia: Bombardier Challenger 300"
    lookup = next(c for c in calls if c.get("prop") == "redirects")
    assert lookup["titles"] == "Bombardier Aviation|Bombardier Challenger 300" and lookup["rdlimit"] == "max"


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
    # zastąpione pliki w replaced/
    assert (photo_dir / "replaced" / "E190.jpg").read_bytes() == b"old"
    assert "Lineage" in (photo_dir / "replaced" / "E190.json").read_text("utf-8")


# --- zdjęcia zapisane wcześniej ---

def test_stale():
    old = {"credit": "Wikipedia: Airbus A321neo", "page": "x"}
    assert stale(old, "A-220-300")
    assert not stale({**old, "v": 3}, "A-220-300")
    assert stale({**old, "v": 1}, "A-220-300")
    # 0.13.4: opis z 0.13.3 ("v": 2, zdjęcie zostawione bez lepszego artykułu) sprawdzany jeszcze raz
    assert stale({**old, "v": 2}, "A-220-300")
    assert not stale({"credit": "Wikipedia: Airbus A220", "v": 2}, "A-220-300", "Airbus A220")
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
    assert stale({"credit": "Wikipedia: Airbus A321neo", "v": "3"}, "A-220-300")


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
    assert sorted(f.name for f in photo_dir.iterdir()) == ["BCS3.jpg", "BCS3.json", "replaced"]
    assert (photo_dir / "replaced" / "BCS3.jpg").read_bytes() == b"old"


def test_type_photo_hides_wrong_photo_without_better_article(monkeypatch, photo_dir, caplog):
    """0.13.4: bez artykułu o tym modelu zdjęcie z artykułu o innym modelu nie jest pokazywane (lepiej bez zdjęcia
    niż z cudzym): obraz i opis do replaced/, w miejscu opisu znacznik only_exact, więc kolejne pobranie też tylko
    z artykułu o tym modelu (artykuł o firmie, bez numeru, wystarczyłby na zwykłe pierwsze pobranie)."""
    old_auto(photo_dir, "A158", "Antonov An-148")
    calls = wiki(monkeypatch, search=[{"title": "Antonov An-148"}, {"title": "Antonov"}],
                 pages={"Antonov An-148": img("A148"), "Antonov": img("logo")})
    with caplog.at_level(logging.INFO, logger="polids.photos"):
        assert get("A158") is None
    assert "A158" in caplog.text and "Antonov An-148" in caplog.text and "ukryte" in caplog.text
    assert local_photo("A158") is None and not recheck("A158", "An-158") and only_exact("A158")
    assert (photo_dir / "replaced" / "A158.jpg").read_bytes() == b"old"
    old_meta = json.loads((photo_dir / "replaced" / "A158.json").read_text("utf-8"))
    assert old_meta["credit"] == "Wikipedia: Antonov An-148"
    marker = json.loads((photo_dir / "A158.json").read_text("utf-8"))
    assert marker == {"credit": "", "only_exact": True, "hidden": "Wikipedia: Antonov An-148", "v": 3}
    assert not any("image" in c for c in calls)
    # do restartu bez kolejnych zapytań
    n = len(calls)
    assert get("A158") is None and len(calls) == n
    # po restarcie znów tylko artykuł o tym modelu: logo producenta nie wchodzi
    monkeypatch.setattr(photos, "_missing", set())
    assert get("A158") is None and len(calls) > n and not any("image" in c for c in calls)
    # Wikipedia podaje przekierowanie An-158 -> An-148: zdjęcie wraca, znacznik do replaced/ pod nową nazwą
    monkeypatch.setattr(photos, "_missing", set())
    wiki(monkeypatch, search=[{"title": "Antonov"}, {"title": "Antonov An-148"}],
         pages={"Antonov An-148": img("A148"), "Antonov": img("logo")}, redirs={"Antonov An-148": ["Antonov An-158"]})
    got = get("A158")
    assert got["credit"] == "Wikipedia: Antonov An-148" and (photo_dir / "A158.jpg").read_bytes().startswith(JPEG)
    assert not only_exact("A158") and not recheck("A158", "An-158")
    aside = sorted(f.name for f in (photo_dir / "replaced").iterdir())
    assert len(aside) == 3 and aside[1:] == ["A158.jpg", "A158.json"]
    assert aside[0].startswith("A158-") and aside[0].endswith(".json")
    assert json.loads((photo_dir / "replaced" / aside[0]).read_text("utf-8"))["only_exact"] is True
    assert json.loads((photo_dir / "replaced" / "A158.json").read_text("utf-8")) == old_meta


def test_move_aside_keeps_earlier_files(photo_dir):
    for body in (b"1", b"2", b"3"):
        (photo_dir / "X.jpg").write_bytes(body)
        photos._move_aside(photo_dir / "X.jpg")
    aside = photo_dir / "replaced"
    assert sorted(f.read_bytes() for f in aside.iterdir()) == [b"1", b"2", b"3"]
    assert (aside / "X.jpg").read_bytes() == b"1" and not (photo_dir / "X.jpg").exists()
    photos._move_aside(photo_dir / "missing.jpg")  # brak pliku: nic


def test_type_photo_hides_wrong_titles_photo(monkeypatch, photo_dir):
    """Typ z TITLES, którego artykuł nie ma grafiki: zdjęcie z innego artykułu też nie jest pokazywane."""
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    wiki(monkeypatch, pages={"Airbus A220": None})
    assert get("BCS3") is None and only_exact("BCS3")
    assert (photo_dir / "replaced" / "BCS3.jpg").read_bytes() == b"old"


def test_v2_kept_by_0133_is_checked_again(monkeypatch, photo_dir):
    """0.13.3 zostawiała zdjęcie z artykułu o innym modelu i dopisywała "v": 2; 0.13.4 sprawdza je jeszcze raz."""
    old_auto(photo_dir, "BCS3", "Airbus A321neo", v=2)
    assert recheck("BCS3", "A-220-300")
    wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    assert get("BCS3")["credit"] == "Wikipedia: Airbus A220"
    # zdjęcie pobrane przez 0.13.3 z właściwego artykułu nie jest pobierane drugi raz
    old_auto(photo_dir, "BCS1", "Airbus A220", v=2)
    assert not recheck("BCS1", "A-220-100")


def test_recheck_any_wikimedia_host(monkeypatch, photo_dir):
    """Wikimedia przenosi miniatury na thumb.wikimedia.org: opis z takim adresem to też zdjęcie pobrane automatycznie
    (0.13.3 uznawała je za własne i nie sprawdzała; najpewniej dlatego BCS3 dalej miał A321neo po wdrożeniu)."""
    old_auto(photo_dir, "BCS3", "Airbus A321neo", image=img("old", host="thumb.wikimedia.org"))
    assert recheck("BCS3", "A-220-300")
    wiki(monkeypatch, pages={"Airbus A220": img("A220", host="thumb.wikimedia.org")})
    got = get("BCS3")
    assert got["credit"] == "Wikipedia: Airbus A220" and (photo_dir / "replaced" / "BCS3.jpg").read_bytes() == b"old"
    assert json.loads((photo_dir / "BCS3.json").read_text("utf-8"))["image"].startswith("https://thumb.wikimedia.org/")
    # podmiana pobranego wcześniej z thumb.wikimedia.org (np. inne rozszerzenie) też przenosi stary plik
    old_auto(photo_dir, "DC91", "McDonnell Douglas DC-10", ext="png", image=img("old", "png", "thumb.wikimedia.org"))
    wiki(monkeypatch, search=[{"title": "McDonnell Douglas DC-9"}], pages={"McDonnell Douglas DC-9": img("DC9")})
    assert get("DC91")["url"].startswith("/files/photos/DC91.jpg?v=") and not (photo_dir / "DC91.png").exists()
    # inne serwery i adresy to nie Wikimedia
    for bad in ("https://wikimedia.org.evil.example/x.jpg", "http://upload.wikimedia.org/x.jpg",
                "//upload.wikimedia.org/x.jpg", "https://example.com/wikimedia.org/x.jpg", "https://[x/a.jpg", None,
                ["https://upload.wikimedia.org/x.jpg"]):
        assert not photos._wikimedia(bad), bad
    assert photos._wikimedia("https://UPLOAD.wikimedia.org/x.jpg") and photos._wikimedia("https://thumb.wikimedia.org/x")


# BCS3.json z polids.pl (Marek, zrzut z 10.11.2026 po wdrożeniu 0.13.3): adres na thumb.wikimedia.org z "?utm_..."
BCS3_ON_SERVER = {
    "credit": "Wikipedia: Airbus A321neo",
    "page": "https://en.wikipedia.org/wiki/Airbus_A321neo",
    "image": "https://thumb.wikimedia.org/wikipedia/commons/thumb/e/e9/HA-LVA%40PEK_%2820200403093313%29.jpg/"
             "960px-HA-LVA%40PEK_%2820200403093313%29.jpg?utm_source=en.wikipedia.org&utm_campaign=api"
             "&utm_content=thumbnail"}


def test_bcs3_as_on_server_is_replaced(monkeypatch, photo_dir, caplog):
    """Dokładnie ten opis 0.13.3 brała za własne zdjęcie (adres spoza upload.wikimedia.org) i pokazywała dalej A321neo."""
    (photo_dir / "BCS3.jpg").write_bytes(b"old")
    (photo_dir / "BCS3.json").write_text(json.dumps(BCS3_ON_SERVER, ensure_ascii=False, indent=1), "utf-8")
    os.utime(photo_dir / "BCS3.jpg", (OLD, OLD))
    os.utime(photo_dir / "BCS3.json", (OLD + 1, OLD + 1))
    assert recheck("BCS3", MODELS["BCS3"]["Model"])
    new = img("A220", host="thumb.wikimedia.org") + "?utm_source=en.wikipedia.org&utm_campaign=api"
    calls = wiki(monkeypatch, pages={"Airbus A220": new})
    with caplog.at_level(logging.INFO, logger="polids.photos"):
        got = get("BCS3")
    assert got["credit"] == "Wikipedia: Airbus A220" and got["url"].startswith("/files/photos/BCS3.jpg?v=")
    assert calls[-1] == {"image": new} and "Airbus A321neo" in caplog.text
    assert (photo_dir / "replaced" / "BCS3.jpg").read_bytes() == b"old"
    assert json.loads((photo_dir / "replaced" / "BCS3.json").read_text("utf-8")) == BCS3_ON_SERVER
    # nowy opis z takim samym adresem (thumb.wikimedia.org, "?utm_...") nie jest sprawdzany ponownie
    assert not recheck("BCS3", MODELS["BCS3"]["Model"]) and photos._downloaded("BCS3")["v"] == 3


def test_replace_legacy_png_saved_as_jpg(monkeypatch, photo_dir):
    """Do 0.13.3 obraz .png z "?utm_…" w adresie zapisywany był jako .jpg: przy podmianie na artykuł z obrazem .png
    przenoszony jest wyświetlany .jpg (inaczej dalej byłby pokazywany, już z podpisem właściwego artykułu)."""
    q = "?utm_source=en.wikipedia.org&utm_campaign=api&utm_content=thumbnail"
    old_auto(photo_dir, "DC91", "McDonnell Douglas DC-10", ext="jpg", image=img("DC10", "png", "thumb.wikimedia.org") + q)
    assert recheck("DC91", "DC-9-10")
    wiki(monkeypatch, search=[{"title": "McDonnell Douglas DC-9"}],
         pages={"McDonnell Douglas DC-9": img("DC9", "png", "thumb.wikimedia.org") + q})
    got = get("DC91")
    assert got["url"].startswith("/files/photos/DC91.png?v=") and got["credit"] == "Wikipedia: McDonnell Douglas DC-9"
    assert not (photo_dir / "DC91.jpg").exists() and (photo_dir / "DC91.png").read_bytes().startswith(JPEG)
    assert (photo_dir / "replaced" / "DC91.jpg").read_bytes() == b"old"
    assert not recheck("DC91", "DC-9-10") and photos._downloaded("DC91")
    # ukrycie takiego zdjęcia też przenosi wyświetlany .jpg
    old_auto(photo_dir, "BCS3", "Airbus A321neo", ext="jpg", image=img("A21N", "png", "thumb.wikimedia.org") + q)
    wiki(monkeypatch, pages={"Airbus A220": None})
    assert get("BCS3") is None and not (photo_dir / "BCS3.jpg").exists()


def test_recheck_extension_from_url_path(photo_dir):
    """Rozszerzenie z samej ścieżki adresu (bez "?..."); plik zapisany według całego adresu (do 0.13.3) też pasuje."""
    assert photos._ext("https://thumb.wikimedia.org/a/960px-X.png?20240101") == "png"
    assert photos._ext("https://upload.wikimedia.org/a/960px-X.PNG") == "png"
    assert photos._ext("https://upload.wikimedia.org/a/960px-X.svg.png") == "png"
    assert photos._ext("https://upload.wikimedia.org/a/960px-X.jpg?x.png") == "jpg"
    old_auto(photo_dir, "BCS3", "Airbus A321neo", ext="png", image=img("old", "png") + "?20240101")
    assert recheck("BCS3", "A-220-300")
    # do 0.13.3 rozszerzenie z całego adresu: png z "?..." zapisany jako jpg
    old_auto(photo_dir, "BCS1", "Airbus A321neo", ext="jpg", image=img("old", "png") + "?20240101")
    assert recheck("BCS1", "A-220-100")


def test_own_photo_with_wikipedia_credit_is_logged_once(photo_dir, caplog):
    """Zdjęcie z podpisem artykułu o innym modelu uznane za własne: przyczyna raz w logu (do restartu)."""
    old_auto(photo_dir, "BCS3", "Airbus A321neo", image="https://example.com/a.jpg")
    with caplog.at_level(logging.INFO, logger="polids.photos"):
        assert not recheck("BCS3", "A-220-300") and not recheck("BCS3", "A-220-300")
    lines = [r.getMessage() for r in caplog.records if r.name == "polids.photos"]
    assert len(lines) == 1 and "BCS3" in lines[0] and "Wikimedia" in lines[0]
    # zdjęcie z właściwego artykułu albo bez podpisu Wikipedii: bez wpisu
    caplog.clear()
    old_auto(photo_dir, "BCS1", "Airbus A220", image="https://example.com/a.jpg")
    (photo_dir / "B738.jpg").write_bytes(b"own")
    with caplog.at_level(logging.INFO, logger="polids.photos"):
        assert not recheck("BCS1", "A-220-100") and not recheck("B738", "737-800")
    assert not [r for r in caplog.records if r.name == "polids.photos"]


def test_replace_is_logged(monkeypatch, photo_dir, caplog):
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    wiki(monkeypatch, pages={"Airbus A220": img("A220")})
    with caplog.at_level(logging.INFO, logger="polids.photos"):
        get("BCS3")
    assert "BCS3" in caplog.text and "Airbus A321neo" in caplog.text and "Wikipedia: Airbus A220" in caplog.text


def test_fetch_refuses_image_outside_wikimedia(monkeypatch, photo_dir):
    calls = wiki(monkeypatch, pages={"Airbus A220": "https://example.com/A220.jpg"})
    with pytest.raises(ValueError, match="outside Wikimedia"):
        fetch("BCS3")
    assert list(photo_dir.iterdir()) == [] and not any("image" in c for c in calls)


def test_type_photo_refreshes_family_article_via_redirect(monkeypatch, photo_dir):
    old_auto(photo_dir, "A158", "Antonov An-148")
    wiki(monkeypatch, search=[{"title": "Antonov"}, {"title": "Antonov An-148"}],
         pages={"Antonov An-148": img("A148"), "Antonov": img("logo")}, redirs={"Antonov An-148": ["Antonov An-158"]})
    got = get("A158")
    assert got["credit"] == "Wikipedia: Antonov An-148" and (photo_dir / "A158.jpg").read_bytes().startswith(JPEG)


def test_type_photo_withholds_wrong_photo_on_api_error(monkeypatch, photo_dir):
    """Błąd w treści odpowiedzi z kodem 200 (przeciążona wyszukiwarka) to nie "brak artykułu": zdjęcie z artykułu
    o innym modelu nie jest pokazywane (błąd idzie dalej, w AIRCRAFT "Photo unavailable"), ale pliki zostają do
    następnego sprawdzenia; nic nie trafia do _missing."""
    old_auto(photo_dir, "DC91", "McDonnell Douglas DC-10")
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    wiki(monkeypatch, error=True)
    for code in ("DC91", "BCS3", "A318"):
        with pytest.raises(ValueError, match="search-error"):
            get(code)
    assert recheck("DC91", "DC-9-10") and recheck("BCS3", "A-220-300")
    assert (photo_dir / "BCS3.jpg").read_bytes() == b"old" and not (photo_dir / "replaced").exists()
    assert photos._missing == set()


def test_type_photo_withholds_wrong_photo_when_wikipedia_down(monkeypatch, photo_dir):
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    wiki(monkeypatch, down=True)
    with pytest.raises(httpx.ConnectError):
        get("BCS3")
    assert recheck("BCS3", "A-220-300") and (photo_dir / "BCS3.jpg").read_bytes() == b"old"
    with pytest.raises(httpx.ConnectError):
        get("BCS1")


def test_own_photo_copied_with_old_time(monkeypatch, photo_dir):
    """Własne zdjęcie skopiowane z zachowanym starym czasem modyfikacji (docker cp, cp -p, tar): czas zmiany
    i-węzła jest nowszy niż opisu, więc to własne zdjęcie."""
    monkeypatch.setattr(photos, "OWN_AFTER_S", 0)
    old_auto(photo_dir, "BCS3", "Airbus A321neo")
    assert recheck("BCS3", "A-220-300")
    time.sleep(0.05)
    own = photo_dir / "BCS3.jpg"
    own.write_bytes(b"own")
    os.utime(own, (OLD - 365 * 86400, OLD - 365 * 86400))
    assert not recheck("BCS3", "A-220-300")


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


def test_api_wrong_photo_not_shown(client, monkeypatch, photo_dir):
    """0.13.4: zdjęcie BCS3 z A321neo bez zastępstwa – 502 przy błędzie Wikipedii, 404 bez artykułu ze zdjęciem."""
    mount = next(r for r in main.app.routes if getattr(r, "path", "") == "/files/photos")
    monkeypatch.setattr(mount.app, "all_directories", [photo_dir])
    old_auto(photo_dir, "BCS3", "Airbus A321neo", image=img("old", host="thumb.wikimedia.org"))
    a = client.get("/api/aircraft", params={"q": "BCS3"}).json()[0]
    wiki(monkeypatch, down=True)
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 502 and r.json()["detail"] == "Photo unavailable"
    wiki(monkeypatch, pages={"Airbus A220": None})
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 404 and r.json()["detail"] == "No photo of this type"
    assert client.get("/files/photos/BCS3.jpg").status_code == 404


def test_api_no_matching_article_is_404(client, monkeypatch, photo_dir):
    wiki(monkeypatch, search=[{"title": "Airbus A321neo"}], pages={"Airbus A321neo": img("A21N")})
    a = client.get("/api/aircraft", params={"q": "A318"}).json()[0]
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 404 and r.json()["detail"] == "No photo of this type"
    assert list(photo_dir.iterdir()) == []
