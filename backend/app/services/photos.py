"""Zdjęcia typów samolotów zapisywane w data/photos/ (plik <ICAO>.jpg + <ICAO>.json z opisem źródła).

Brakujące zdjęcie aplikacja pobiera raz z Wikipedii (miniatura głównej grafiki artykułu o danym typie)
i zapisuje lokalnie, więc kolejne wyświetlenia działają bez internetu. Własne zdjęcie wystarczy wrzucić
do data/photos/ jako <ICAO>.jpg.

0.13.3 (Marek: "czemu BCS3 ma zdjęcie A321neo?"): wyszukiwarka Wikipedii brała pierwszy wynik dla hasła z nazwy ICAO
("AIRBUS A-220-300"), a przy zapisie "A-220" pierwszym wynikiem bywał artykuł o innym modelu. Teraz:
- typy, których nazwa ICAO nie prowadzi do właściwego artykułu (A220, CRJ, MD-80), biorą artykuł z TITLES;
- hasło ma nazwę Airbusa bez łącznika ("A220-300"); z pięciu wyników wyszukiwania (pick) w kolejności wyszukiwarki
  bierzemy artykuł, którego tytuł albo przekierowanie zawiera numer modelu albo którego tytuł ma nazwę typu i nazwę
  producenta ("Airbus Beluga"), potem tytuły bez liczb; artykuł z innym numerem w tytule odpada – lepiej bez zdjęcia
  niż z cudzym;
- zdjęcie pobrane wcześniej (opis bez "v") z artykułu o innym numerze albo, dla typów z TITLES, z innego artykułu
  jest sprawdzane od nowa przy następnym otwarciu typu (type_photo): zostaje podmienione, gdy znajdzie się
  pasujący artykuł, a gdy nie ma lepszego albo Wikipedia nie odpowiada, zostaje stare. Własne zdjęcia (bez opisu,
  z opisem bez adresu grafiki Wikipedii albo wrzucone później niż opis) nie są ruszane;
- adres zdjęcia ma "?v=<czas pliku>", żeby przeglądarka i Cloudflare nie pokazywały starej wersji po podmianie."""

import json
import re

import httpx

from ..config import settings

WIKI_API = "https://en.wikipedia.org/w/api.php"
META_VERSION = 2  # pliki opisu bez "v" (do 0.13.2) sprawdzamy ponownie
SEARCH_LIMIT = 5
OWN_AFTER_S = 60  # obraz nowszy od opisu o więcej sekund to własne zdjęcie (fetch_photo zapisuje obraz przed opisem)
EXTS = ("jpg", "jpeg", "png", "webp")
_missing: set[str] = set()  # typy, dla których Wikipedia nic nie zwróciła (do restartu aplikacji)

# Artykuły dla typów, przy których nazwa ICAO myli wyszukiwarkę i numery modelu: A220 to dawne CSeries (wyszukiwarka
# dawała inne Airbusy), CRJ ma w nazwie "CL-600" jak Challenger 600 (CRJ-705/900/1000 opisuje artykuł o CRJ700),
# MD-81…MD-88 opisuje jeden artykuł o MD-80. Te typy biorą zdjęcie tylko z tego artykułu (po przekierowaniach).
TITLES = {"BCS1": "Airbus A220", "BCS3": "Airbus A220",
          "CRJ1": "Bombardier CRJ100/200", "CRJ2": "Bombardier CRJ100/200",
          "CRJ7": "Bombardier CRJ700 series", "CRJ9": "Bombardier CRJ700 series", "CRJX": "Bombardier CRJ700 series",
          **{code: "McDonnell Douglas MD-80" for code in ("MD81", "MD82", "MD83", "MD87", "MD88")}}

# słowa nazwy typu i producenta, które nie wyróżniają typu (artykuł z nimi w tytule nie musi być o tym typie)
GENERIC = frozenset((
    "super regional turbo twin grand long short wing range extended freighter cargo executive corporate special "
    "mission domestic winglets prestige replica light utility transport transporter trainer version model series "
    "family aircraft aerospace aviation industries industry company corporation international helicopter "
    "helicopters systems group manufacturing works aeronautics aeronautical motors factory").split())

# numer w oznaczeniu: liczba co najmniej dwucyfrowa albo jedna cyfra po literach i łączniku ("DC-9", "An-2", "DHC-8");
# pojedyncza cyfra osobno ("737 MAX 8", "Dash 8") albo po liczbie ("747-8") to wersja, nie numer modelu
_NUM = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]+-(\d)(?!\d)|(\d{2,})")


def _safe(icao: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", icao.upper())


def _files(code: str) -> list:
    return [settings.photos_dir / f"{code}.{ext}" for ext in EXTS]


def _ext(url: str) -> str:
    return "png" if url.lower().endswith(".png") else "jpg"


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
            credit = meta.get("credit")
            return {"url": f"/files/photos/{img.name}?v={int(img.stat().st_mtime)}",
                    "credit": credit if isinstance(credit, str) else "", "page": meta.get("page")}
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


def _numbers(text: str | None) -> list[str]:
    return [(m.group(1) or m.group(2)).lstrip("0") or "0" for m in _NUM.finditer(text or "")]


def model_numbers(model: str | None) -> set[str]:
    """Numery modelu: z każdego oznaczenia (słowa z cyframi) w nazwach na liście (po przecinkach i ukośnikach,
    bez nawiasów) pierwszy numer (_NUM) – "A-220-300" -> {220} (300 to wersja), "DC-9-10" -> {9},
    "CL-600 Regional Jet CRJ-705/900" -> {600, 705, 900}, "EMB-500 Phenom 100" -> {500, 100}. Sama liczba po ukośniku
    za oznaczeniem z wersją to kolejna wersja ("ATR-42-300/320" -> {42}), za oznaczeniem bez wersji kolejny model
    ("Tu-204/214" -> {204, 214}). Pusty zbiór: nazwa bez numeru (bez sprawdzania)."""
    nums = set()
    for name in re.sub(r"\([^()]*\)", "", model or "").split(","):
        prev: list[str] = []
        for alt in name.split("/"):
            if prev and alt.strip().isdigit() and len(_numbers(prev[-1])) > 1:
                continue
            for word in alt.split():
                if found := _numbers(word):
                    nums.add(found[0])
            prev = alt.split() or prev
    return nums


def _words(text: str | None) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]{4,}", re.sub(r"\([^()]*\)", "", text or ""))} - GENERIC


def title_fit(title: str, nums: set[str]) -> str:
    """Zgodność tytułu artykułu z numerami modelu: "exact" – tytuł zawiera numer modelu ("Airbus A220" dla A-220-300),
    "neutral" – tytuł bez numerów ("Embraer E-Jet family", "De Havilland Canada Dash 8") albo model bez numeru,
    "other" – tytuł z innym numerem ("Airbus A321" dla A-220-300, "McDonnell Douglas DC-10" dla DC-9-10, rok)."""
    found = set(_numbers(title))
    if not nums or not found:
        return "neutral"
    return "exact" if found & nums else "other"


def _named(title: str, words: set[str], maker: set[str]) -> bool:
    """Tytuł ma słowo z nazwy typu i słowo z nazwy producenta (początek słowa: "BelugaXL", "Beechcraft")."""
    have = [w.lower() for w in re.findall(r"[A-Za-z]+", title or "")]
    return any(t.startswith(w) for t in have for w in words) and any(t.startswith(m) for t in have for m in maker)


def pick(results: list[dict], nums: set[str], words: set[str] = frozenset(), maker: set[str] = frozenset()) -> list[str]:
    """Tytuły wyników wyszukiwania w kolejności wyboru: najpierw, w kolejności wyszukiwarki, artykuły o tym modelu –
    numer modelu w tytule albo w przekierowaniu, przez które wyszukiwarka je znalazła (np. "Bombardier Challenger 350"
    -> "Bombardier Challenger 300"), albo tytuł bez innego numeru z nazwą typu i producenta ("Airbus Beluga",
    "Boeing Dreamlifter"); potem pozostałe tytuły bez liczb; tytuły z innym numerem odpadają.
    words: słowa nazwy typu (_words(model)), maker: słowa nazwy producenta."""
    good, rest = [], []
    for r in results:
        title = r.get("title") or ""
        fit = title_fit(title, nums)
        if fit == "exact" or title_fit(r.get("redirecttitle") or "", nums) == "exact" \
                or (fit == "neutral" and _named(title, words, maker)):
            good.append(title)
        elif fit == "neutral":
            rest.append(title)
    return list(dict.fromkeys(good + rest))


def stale(meta: dict, model: str | None, title: str | None = None) -> bool:
    """Opis zdjęcia pobranego przed 0.13.3 (tytuł w "credit": "Wikipedia: …") z artykułu o innym modelu;
    title: artykuł z TITLES – wtedy każdy inny artykuł. Opisy od 0.13.3 ("v") i inne podpisy: False."""
    credit, v = meta.get("credit"), meta.get("v")
    if (isinstance(v, int) and v >= META_VERSION) or not isinstance(credit, str) or not credit.startswith("Wikipedia: "):
        return False
    got = credit.removeprefix("Wikipedia: ")
    if title:
        return got != title
    return title_fit(got, model_numbers(model)) == "other"


def _downloaded(code: str) -> dict | None:
    """Opis zdjęcia, jeśli wyświetlany plik został pobrany automatycznie: opis ma adres grafiki Wikipedii ("image"),
    plik ma rozszerzenie z tego adresu i nie jest nowszy od opisu (nowszy to własne zdjęcie wrzucone w miejsce
    pobranego, z pozostawionym starym opisem)."""
    shown = next((f for f in _files(code) if f.exists()), None)
    meta_file = settings.photos_dir / f"{code}.json"
    meta = _meta(code)
    image = meta.get("image")
    if not shown or not meta_file.exists() or not isinstance(image, str) \
            or not image.startswith("https://upload.wikimedia.org/") or shown.suffix != "." + _ext(image):
        return None
    if shown.stat().st_mtime > meta_file.stat().st_mtime + OWN_AFTER_S:
        return None
    return meta


def recheck(icao: str, model: str | None) -> bool:
    """Wyświetlane zdjęcie pobrano automatycznie przed 0.13.3 z artykułu o innym modelu (stale): do sprawdzenia."""
    code = _safe(icao)
    meta = _downloaded(code)
    return meta is not None and stale(meta, model, TITLES.get(code))


def keep_photo(icao: str) -> None:
    """Sprawdzone zdjęcie zostaje (nie ma lepszego artykułu): opis dostaje "v", więc nie jest sprawdzany ponownie."""
    code = _safe(icao)
    if meta := _meta(code):
        (settings.photos_dir / f"{code}.json").write_text(
            json.dumps({**meta, "v": META_VERSION}, ensure_ascii=False, indent=1), "utf-8")


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
        if isinstance((page.get("thumbnail") or {}).get("source"), str):
            return page
    return None


async def fetch_photo(icao: str, manufacturer: str | None, model: str | None) -> dict | None:
    """Zapisuje miniaturę głównej grafiki artykułu o typie jako data/photos/<ICAO>.jpg: dla typów z TITLES tylko z tego
    artykułu, dla pozostałych z wyników wyszukiwarki Wikipedii (pięć wyników, wybór: pick). Zastępuje tylko
    zdjęcie pobrane wcześniej automatycznie; None – brak pasującego artykułu z grafiką."""
    code = _safe(icao)
    if code in _missing:
        return None
    query = photo_query(manufacturer, model)
    headers = {"User-Agent": settings.user_agent + " aircraft type photos"}
    async with httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True, headers=headers) as client:
        if code in TITLES:
            page = await _first_with_image(client, [TITLES[code]])
        else:
            resp = await client.get(WIKI_API, params={
                "action": "query", "format": "json", "list": "search", "srsearch": f"{query} aircraft",
                "srlimit": SEARCH_LIMIT, "srnamespace": 0, "srprop": "redirecttitle"})
            resp.raise_for_status()
            titles = pick((resp.json().get("query") or {}).get("search") or [], model_numbers(model),
                          _words(model), _words(manufacturer))
            page = await _first_with_image(client, titles) if titles else None
        if not page:
            _missing.add(code)
            return None
        img = await client.get(page["thumbnail"]["source"])
        img.raise_for_status()
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    if old := _downloaded(code):
        (settings.photos_dir / f"{code}.{_ext(old['image'])}").unlink(missing_ok=True)
    ext = _ext(page["thumbnail"]["source"])
    (settings.photos_dir / f"{code}.{ext}").write_bytes(img.content)
    meta = {"credit": f"Wikipedia: {page['title']}", "page": page.get("fullurl"), "image": page["thumbnail"]["source"],
            "query": query, "v": META_VERSION}
    (settings.photos_dir / f"{code}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return local_photo(code)


async def type_photo(icao: str, manufacturer: str | None, model: str | None) -> dict | None:
    """Zdjęcie typu: zapisane, a gdy go nie ma albo jest do sprawdzenia (recheck) – pobrane (fetch_photo).
    Zdjęcie do sprawdzenia zostaje, gdy nie ma lepszego artykułu (keep_photo) albo Wikipedia nie odpowiada.
    Błąd HTTP bez żadnego zdjęcia idzie dalej (httpx.HTTPError, ValueError)."""
    found = local_photo(icao)
    if found and not recheck(icao, model):
        return found
    try:
        new = await fetch_photo(icao, manufacturer, model)
    except (httpx.HTTPError, ValueError):
        if found:
            return found
        raise
    if new:
        return new
    if found:
        keep_photo(icao)
    return found
