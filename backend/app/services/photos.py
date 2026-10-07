"""Zdjęcia typów samolotów zapisywane w data/photos/ (plik <ICAO>.jpg + <ICAO>.json z opisem źródła).

Brakujące zdjęcie aplikacja pobiera raz z Wikipedii (miniatura głównej grafiki artykułu o danym typie)
i zapisuje lokalnie, więc kolejne wyświetlenia działają bez internetu. Własne zdjęcie wystarczy wrzucić
do data/photos/ jako <ICAO>.jpg."""

import json
import re

import httpx

from ..config import settings

WIKI_API = "https://en.wikipedia.org/w/api.php"
_missing: set[str] = set()  # typy, dla których Wikipedia nic nie zwróciła (do restartu aplikacji)


def _safe(icao: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", icao.upper())


def local_photo(icao: str) -> dict | None:
    code = _safe(icao)
    for ext in ("jpg", "jpeg", "png", "webp"):
        img = settings.photos_dir / f"{code}.{ext}"
        if img.exists():
            meta_file = settings.photos_dir / f"{code}.json"
            meta = json.loads(meta_file.read_text("utf-8")) if meta_file.exists() else {}
            return {"url": f"/files/photos/{img.name}", "credit": meta.get("credit", "zdjęcie lokalne"),
                    "page": meta.get("page")}
    return None


async def fetch_photo(icao: str, query: str) -> dict | None:
    """Szuka artykułu na Wikipedii i zapisuje jego miniaturę jako data/photos/<ICAO>.jpg."""
    code = _safe(icao)
    if code in _missing:
        return None
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} aircraft",
              "gsrlimit": 1, "prop": "pageimages|info", "piprop": "thumbnail", "pithumbsize": 800,
              "inprop": "url", "redirects": 1}
    headers = {"User-Agent": settings.user_agent + " aircraft type photos"}
    async with httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True, headers=headers) as client:
        resp = await client.get(WIKI_API, params=params)
        resp.raise_for_status()
        pages = list((resp.json().get("query") or {}).get("pages", {}).values())
        if not pages or not pages[0].get("thumbnail"):
            _missing.add(code)
            return None
        page = pages[0]
        img = await client.get(page["thumbnail"]["source"])
        img.raise_for_status()
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    ext = "png" if page["thumbnail"]["source"].lower().endswith(".png") else "jpg"
    (settings.photos_dir / f"{code}.{ext}").write_bytes(img.content)
    meta = {"credit": f"Wikipedia: {page['title']}", "page": page.get("fullurl"), "image": page["thumbnail"]["source"]}
    (settings.photos_dir / f"{code}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return local_photo(code)
