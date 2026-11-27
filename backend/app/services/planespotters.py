"""0.15.0: zdjęcie konkretnego samolotu po rejestracji z Planespotters.net Photo API
(https://www.planespotters.net/photo/api).

Warunki API, których pilnuje ten moduł i frontend:
- serwer pyta API z własnym User-Agent z adresem kontaktowym (settings.user_agent, POLIDS_CONTACT_URL);
- odpowiedź JSON najwyżej 24 h w cache (settings.planespotters_cache_seconds, domyślnie 6 h);
- adresy (miniatura, strona zdjęcia) idą do przeglądarki bez zmian: serwer nie pobiera, nie zapisuje i nie
  pośredniczy w pobieraniu obrazów; przeglądarka bierze miniaturę prosto z CDN Planespotters;
- przy zdjęciu zawsze autor i odnośnik (zwykłe <a>, bez rel="nofollow") do strony zdjęcia (frontend, api.js
  planespottersHtml).

Rejestracja z planu lotu VATSIM (REG/SPLWA) zwykle nie ma łącznika, a Planespotters szuka po zapisie z łącznikiem
(SP-LWA). candidates() daje zapis z pliku i najwyżej dwa zapisy z łącznikiem po prefiksie kraju; pierwszy, który
ma zdjęcie, wygrywa."""

import json
import re
from urllib.parse import quote, urlsplit

from ..config import settings
from .http_cache import UpstreamError, fetch_text, forget, peek

REG = re.compile(r"^[A-Z0-9]{1,3}-?[A-Z0-9]{1,6}$")
# kraje bez łącznika w rejestracji (USA N12345, Japonia JA801A, Korea HL7xxx)
NO_DASH = ("N", "JA", "HL")
# jednoliterowe prefiksy kraju: Kanada, Niemcy, Francja, Wielka Brytania, Włochy, Chiny, Wyspa Man
ONE_LETTER = set("BCDFGIM")
# strony zdjęć na planespotters.net, miniatury na cdn.planespotters.net albo t.plnspttrs.net (CDN Planespotters)
HOSTS = ("planespotters.net", "plnspttrs.net")
PHOTOS_DOWN = "Photos unavailable"


def clean(reg: str | None) -> str:
    return re.sub(r"[^A-Z0-9-]", "", str(reg or "").upper()).strip("-")[:10]


def candidates(reg: str) -> list[str]:
    """Zapisy rejestracji do sprawdzenia, w kolejności: SPLWA -> [SPLWA, SP-LWA, S-PLWA]; DABCD -> [DABCD, D-ABCD,
    DA-BCD]; z łącznikiem albo z kraju bez łącznika (N, JA, HL) tylko zapis z pliku."""
    reg = clean(reg)
    if not reg or "-" in reg or reg.startswith(NO_DASH) or len(reg) < 4:
        return [reg] if reg else []
    one, two = f"{reg[:1]}-{reg[1:]}", f"{reg[:2]}-{reg[2:]}"
    # jednoliterowy prefiks z czterema znakami po nim (D-ABCD, G-EUUA, F-GKXA) przed dwuliterowym
    order = [one, two] if reg[0] in ONE_LETTER and len(reg) == 5 else [two, one]
    return list(dict.fromkeys([reg, *order]))


def _https(url) -> bool:
    """Adres https na serwerze Planespotters (HOSTS i ich poddomeny)."""
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in HOSTS)


def parse(body) -> dict | None:
    """Pierwsze zdjęcie z odpowiedzi API: {thumbnail, thumbnail_large, width, height, link, photographer}; adresy bez
    zmian. None: brak zdjęć albo zdjęcie bez miniatury, strony lub autora (bez nich warunki API nie pozwalają go
    pokazać) albo z adresem spoza Planespotters."""
    photos = body.get("photos") if isinstance(body, dict) else None
    for p in photos or []:
        if not isinstance(p, dict):
            continue
        thumb = (p.get("thumbnail") or {}).get("src")
        large = (p.get("thumbnail_large") or {}).get("src")
        link, author = p.get("link"), p.get("photographer")
        if not (_https(thumb) and _https(link) and isinstance(author, str) and author.strip()):
            continue
        size = (p.get("thumbnail_large") if _https(large) else p.get("thumbnail")) or {}
        size = size.get("size") or {}
        return {"thumbnail": thumb, "thumbnail_large": large if _https(large) else None,
                "width": size.get("width") if isinstance(size.get("width"), int) else None,
                "height": size.get("height") if isinstance(size.get("height"), int) else None,
                "link": link, "photographer": " ".join(author.split())[:120]}
    return None


def reg_url(reg: str) -> str:
    return f"{settings.planespotters_url.rstrip('/')}/reg/{quote(reg, safe='-')}"


async def by_registration(reg: str) -> dict:
    """{registration (zapis, pod którym jest zdjęcie, albo z pliku), photo (parse albo None)}. Błąd sieci albo
    nieczytelna odpowiedź przy pierwszym zapisie: UpstreamError (nieczytelna odpowiedź nie zostaje w cache)."""
    names = candidates(reg)
    if not names:
        raise ValueError("Registration: 2-10 letters or digits")
    first_error = None
    for name in names:
        url = reg_url(name)
        try:
            text = await fetch_text(url, settings.planespotters_cache_seconds, headers={"Accept": "application/json"})
            body = json.loads(text)
        except UpstreamError as exc:
            first_error = first_error or exc
            continue
        except ValueError:
            forget(url)
            first_error = first_error or UpstreamError(f"{url}: unexpected reply")
            continue
        if isinstance(body, dict) and body.get("error"):
            forget(url)
            first_error = first_error or UpstreamError(f"{url}: {str(body['error'])[:80]}")
            continue
        if photo := parse(body):
            return {"registration": name, "photo": photo}
    # żaden zapis nie dostał odpowiedzi API (także pustej listy zdjęć): błąd, nie "brak zdjęcia"
    if first_error and not any(peek(reg_url(n)) is not None for n in names):
        raise first_error
    return {"registration": names[0], "photo": None}
