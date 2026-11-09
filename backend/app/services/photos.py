"""Zdjęcia typów samolotów zapisywane w data/photos/ (plik <ICAO>.jpg + <ICAO>.json z opisem źródła).

Brakujące zdjęcie aplikacja pobiera raz z Wikipedii (miniatura głównej grafiki artykułu o danym typie)
i zapisuje lokalnie, więc kolejne wyświetlenia działają bez internetu. Własne zdjęcie wystarczy wrzucić
do data/photos/ jako <ICAO>.jpg.

0.13.3 (Marek: "czemu BCS3 ma zdjęcie A321neo?"): wyszukiwarka Wikipedii brała pierwszy wynik dla hasła z nazwy ICAO
("AIRBUS A-220-300"), a przy zapisie "A-220" pierwszym wynikiem bywał artykuł o innym modelu. Teraz:
- typy, których nazwa ICAO nie prowadzi do właściwego artykułu (A220, CRJ, MD-80), mają tytuł artykułu w TITLES;
- hasło ma nazwę Airbusa bez łącznika ("A220-300"), z pięciu wyników bierzemy artykuł, którego tytuł (albo
  przekierowanie, przez które wyszukiwarka go znalazła) zawiera numer modelu, a artykuł z innym numerem w tytule
  odrzucamy – lepiej bez zdjęcia niż z cudzym;
- zdjęcia pobrane wcześniej (plik opisu bez "v") z artykułu o innym numerze albo, dla typów z TITLES, z innego
  artykułu są usuwane i pobierane od nowa przy następnym otwarciu typu."""

import json
import re

import httpx

from ..config import settings

WIKI_API = "https://en.wikipedia.org/w/api.php"
META_VERSION = 2  # pliki opisu bez "v" (do 0.13.2) sprawdzamy ponownie
SEARCH_LIMIT = 5
_missing: set[str] = set()  # typy, dla których Wikipedia nic nie zwróciła (do restartu aplikacji)

# Artykuły dla typów, przy których nazwa ICAO myli wyszukiwarkę i numery modelu: A220 to dawne CSeries (wyszukiwarka
# dawała inne Airbusy), CRJ ma w nazwie "CL-600" jak Challenger 600 (CRJ-705/900/1000 opisuje artykuł o CRJ700),
# MD-81…MD-88 opisuje jeden artykuł o MD-80. Gdy artykułu nie ma albo nie ma grafiki, zostaje wyszukiwarka.
TITLES = {"BCS1": "Airbus A220", "BCS3": "Airbus A220",
          "CRJ1": "Bombardier CRJ100/200", "CRJ2": "Bombardier CRJ100/200",
          "CRJ7": "Bombardier CRJ700 series", "CRJ9": "Bombardier CRJ700 series", "CRJX": "Bombardier CRJ700 series",
          **{code: "McDonnell Douglas MD-80" for code in ("MD81", "MD82", "MD83", "MD87", "MD88")}}


def _safe(icao: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", icao.upper())


def _files(code: str) -> list:
    return [settings.photos_dir / f"{code}.{ext}" for ext in ("jpg", "jpeg", "png", "webp")]


def _meta(code: str) -> dict:
    """Opis zdjęcia z <ICAO>.json; brak albo uszkodzony plik – pusty opis."""
    meta_file = settings.photos_dir / f"{code}.json"
    try:
        meta = json.loads(meta_file.read_text("utf-8")) if meta_file.exists() else {}
    except (OSError, ValueError):
        meta = {}
    return meta if isinstance(meta, dict) else {}


def local_photo(icao: str) -> dict | None:
    code = _safe(icao)
    for img in _files(code):
        if img.exists():
            meta = _meta(code)
            return {"url": f"/files/photos/{img.name}", "credit": meta.get("credit", ""),
                    "page": meta.get("page")}
    return None


def _model_name(manufacturer: str | None, model: str | None) -> str:
    """Pierwsza nazwa z listy wersji i nazw wojskowych; Airbus bez łącznika po A ("A-220-300" -> "A220-300"),
    bo tak nazywa typy Wikipedia, a wyszukiwarka "A-220" dzieli na "A" i "220". Nawiasy usuwane przed podziałem
    po przecinkach ("747-400 (domestic, no winglets)" -> "747-400")."""
    name = re.sub(r"\([^()]*\)", "", model or "").split(",")[0]
    name = " ".join(name.split("/")[0].split())
    if (manufacturer or "").strip().upper() == "AIRBUS":
        name = re.sub(r"^A-(?=\d)", "A", name)
    return name


def photo_query(manufacturer: str | None, model: str | None) -> str:
    """Hasło do wyszukiwarki Wikipedii z nazwy typu w ICAO_Aircraft.json, która wylicza wersje i nazwy wojskowe:
    "A-300(B4/C4/F4)-600" -> "A300-600", "737-800, BBJ2" -> "737-800", "172 Cutlass/Skyhawk, T-41" -> "172 Cutlass"."""
    return f"{manufacturer or ''} {_model_name(manufacturer, model)}".strip()


def model_numbers(model: str | None) -> set[str]:
    """Numery modelu: z każdego oznaczenia w nazwach na liście (po przecinkach i ukośnikach, bez nawiasów, słowa
    z cyframi) pierwsza liczba co najmniej dwucyfrowa – "A-220-300" -> {220} (300 to wersja, nie model),
    "EMB-500 Phenom 100" -> {500, 100}, "CL-600 Regional Jet CRJ-705/900" -> {600, 705, 900}, "DHC-8-400 Dash 8" ->
    {400}. Pusty zbiór: nazwa bez numeru (bez sprawdzania)."""
    nums = set()
    for part in re.split(r"[,/]", re.sub(r"\([^()]*\)", "", model or "")):
        for word in part.split():
            if m := re.search(r"\d{2,}", word):
                nums.add(m.group().lstrip("0") or "0")
    return nums


def _title_numbers(title: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in re.findall(r"\d{2,}", title or "")}


def title_fit(title: str, nums: set[str]) -> str:
    """Zgodność tytułu artykułu z numerami modelu: "exact" – tytuł zawiera numer modelu ("Airbus A220" dla A-220-300),
    "neutral" – tytuł bez liczb ("Embraer E-Jet family") albo model bez numeru, "other" – tytuł z innym numerem
    ("Airbus A321" dla A-220-300, także rok w tytule)."""
    found = _title_numbers(title)
    if not nums or not found:
        return "neutral"
    return "exact" if found & nums else "other"


def stale(meta: dict, model: str | None, title: str | None = None) -> bool:
    """Zdjęcie pobrane automatycznie przed 0.13.3 (tytuł w "credit": "Wikipedia: …") z artykułu o innym modelu;
    title: artykuł z TITLES – wtedy każdy inny artykuł. Własne zdjęcia (bez opisu albo z innym podpisem) i pobrane
    od 0.13.3 ("v") zostają."""
    credit = meta.get("credit") or ""
    if (meta.get("v") or 0) >= META_VERSION or not credit.startswith("Wikipedia: "):
        return False
    got = credit.removeprefix("Wikipedia: ")
    if title:
        return got != title
    return title_fit(got, model_numbers(model)) == "other"


def cached_photo(icao: str, model: str | None) -> dict | None:
    """Zdjęcie z data/photos/; nieaktualne (stale) usuwamy razem z opisem, żeby pobrać je od nowa."""
    code = _safe(icao)
    if stale(_meta(code), model, TITLES.get(code)):
        for f in [*_files(code), settings.photos_dir / f"{code}.json"]:
            f.unlink(missing_ok=True)
        _missing.discard(code)
        return None
    return local_photo(code)


def pick(results: list[dict], nums: set[str]) -> list[str]:
    """Tytuły wyników wyszukiwania w kolejności wyboru: najpierw tytuł z numerem modelu, potem znalezione przez
    przekierowanie z numerem modelu (np. "Bombardier CRJ900" -> "Bombardier CRJ700 series"), na końcu tytuły
    bez liczb; tytuły z innym numerem odpadają. Model bez numeru: wszystkie wyniki w kolejności wyszukiwarki."""
    if not nums:
        return [r["title"] for r in results]
    by_title = [r["title"] for r in results if title_fit(r["title"], nums) == "exact"]
    by_redirect = [r["title"] for r in results if r["title"] not in by_title
                   and title_fit(r.get("redirecttitle") or "", nums) == "exact"]
    neutral = [r["title"] for r in results if r["title"] not in by_title + by_redirect
               and title_fit(r["title"], nums) == "neutral"]
    return list(dict.fromkeys(by_title + by_redirect + neutral))


async def _first_with_image(client: httpx.AsyncClient, titles: list[str]) -> dict | None:
    """Pierwszy z artykułów (w podanej kolejności), który ma główną grafikę; tytuły po przekierowaniach
    i normalizacji Wikipedii (zmiana nazwy artykułu nie gubi zdjęcia)."""
    resp = await client.get(WIKI_API, params={
        "action": "query", "format": "json", "titles": "|".join(titles), "redirects": 1, "prop": "pageimages|info",
        "piprop": "thumbnail", "pithumbsize": 800, "inprop": "url"})
    resp.raise_for_status()
    query = resp.json().get("query") or {}
    normalized = {n.get("from"): n.get("to") for n in query.get("normalized") or []}
    redirects = {r.get("from"): r.get("to") for r in query.get("redirects") or []}
    pages = {p.get("title"): p for p in (query.get("pages") or {}).values()}
    for title in titles:
        title = normalized.get(title, title)
        page = pages.get(redirects.get(title, title)) or {}
        if page.get("thumbnail"):
            return page
    return None


async def fetch_photo(icao: str, query: str, nums: set[str] | None = None) -> dict | None:
    """Zapisuje miniaturę głównej grafiki artykułu o typie jako data/photos/<ICAO>.jpg: artykuł z TITLES, a bez niego
    (albo gdy nie ma grafiki) wyszukiwarka Wikipedii (pięć wyników, wybór: pick). nums: numery modelu
    (model_numbers); None/pusty – bez sprawdzania tytułu."""
    code = _safe(icao)
    if code in _missing:
        return None
    nums = nums or set()
    headers = {"User-Agent": settings.user_agent + " aircraft type photos"}
    async with httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True, headers=headers) as client:
        page = await _first_with_image(client, [TITLES[code]]) if code in TITLES else None
        if not page:
            resp = await client.get(WIKI_API, params={
                "action": "query", "format": "json", "list": "search", "srsearch": f"{query} aircraft",
                "srlimit": SEARCH_LIMIT, "srnamespace": 0, "srprop": "redirecttitle"})
            resp.raise_for_status()
            titles = pick((resp.json().get("query") or {}).get("search") or [], nums)
            page = await _first_with_image(client, titles) if titles else None
        if not page:
            _missing.add(code)
            return None
        img = await client.get(page["thumbnail"]["source"])
        img.raise_for_status()
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    for old in _files(code):
        old.unlink(missing_ok=True)
    ext = "png" if page["thumbnail"]["source"].lower().endswith(".png") else "jpg"
    (settings.photos_dir / f"{code}.{ext}").write_bytes(img.content)
    meta = {"credit": f"Wikipedia: {page['title']}", "page": page.get("fullurl"), "image": page["thumbnail"]["source"],
            "query": query, "v": META_VERSION}
    (settings.photos_dir / f"{code}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return local_photo(code)
