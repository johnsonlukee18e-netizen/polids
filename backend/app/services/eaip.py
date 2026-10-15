"""Adresy eAIP PAŻP (IFR, VFR, MIL) dla bieżącego cyklu AIRAC.

PAŻP publikuje każdą poprawkę AIRAC w osobnym katalogu, np. eaipifr/AIRAC AMDT 10-26_2026_10_01/index-v2.html
(numer cyklu w roku, rok, data wejścia w życie). Stare katalogi zostają na serwerze, więc stały adres po zmianie cyklu
nie daje błędu, tylko po cichu pokazuje nieaktualną poprawkę. Dlatego bez POLIDS_AIP_*_URL w .env adres jest liczony
przy każdym zapytaniu z cyklu na dziś (UTC: AIRAC zmienia się o 00:00 UTC), a jawny adres z .env wygrywa bez zmian.

Nie każdy cykl ma poprawkę: dla 2513 (25.12.2025) katalogu AIRAC AMDT 13-25 nie ma w żadnym z trzech pakietów i przez
cały cykl obowiązuje 12-25. Dlatego wyliczony katalog sprawdzamy na serwerze PAŻP (resolve): brak (4xx) → cykl
wcześniej, najwyżej BACK_CYCLES razy; błąd sieci albo serwera → zostaje wyliczony adres. Wynik w pamięci na cykl."""

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from ..config import settings
from .airac import current_airac

log = logging.getLogger(__name__)

BASE = "https://docs.pansa.pl/ais"
# klucz linku w /api/config -> (katalog eAIP, wstawka w nazwie poprawki)
PACKAGES = {"aip_ifr": ("eaipifr", ""), "aip_vfr": ("eaipvfr", "VFR%20"), "aip_mil": ("eaipmil", "MIL%20")}
BACK_CYCLES = 3          # ile cykli wstecz szukać poprawki, gdy bieżącej nie ma
PROBE_TIMEOUT = 4.0      # s na jedno sprawdzenie katalogu (pierwsze /api/config w cyklu czeka na wynik)
TTL_FOUND = 28 * 86400   # katalog bieżącego cyklu jest: do końca cyklu (klucz pamięci zawiera numer cyklu)
TTL_FALLBACK = 6 * 3600  # bieżącego nie ma: sprawdzamy znowu co kilka godzin (PAŻP może dołożyć katalog później)
TTL_UNKNOWN = 600        # brak połączenia z PAŻP: wyliczony adres, ponowna próba po 10 min

_resolved: dict[tuple[str, str], tuple[float, str]] = {}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def package_url(link: str, airac: dict) -> str:
    """index-v2.html poprawki dla cyklu z current_airac(): ident "2610" -> AMDT 10-26, data wejścia 2026-10-01."""
    folder, infix = PACKAGES[link]
    ident = airac["ident"]
    return (f"{BASE}/{folder}/AIRAC%20AMDT%20{infix}{ident[2:]}-{ident[:2]}_{airac['effective'].replace('-', '_')}"
            "/index-v2.html")


def override(link: str) -> str:
    """Adres z .env (POLIDS_AIP_IFR_URL itd.) albo "" (wtedy liczony z cyklu)."""
    return (getattr(settings, f"{link}_url") or "").strip()


def aip_url(link: str, today: date | None = None) -> str:
    """Adres z .env, a bez niego wyliczony z cyklu AIRAC na dziś (UTC), bez sprawdzania na serwerze."""
    return override(link) or package_url(link, current_airac(today or utc_today()))


def aip_links(today: date | None = None) -> dict[str, str]:
    today = today or utc_today()
    return {link: aip_url(link, today) for link in PACKAGES}


def reset_cache() -> None:
    _resolved.clear()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=min(settings.http_timeout, PROBE_TIMEOUT), follow_redirects=True,
                             headers={"User-Agent": f"Mozilla/5.0 {settings.user_agent}"})


async def folder_exists(client: httpx.AsyncClient, url: str) -> bool | None:
    """True: index-v2.html poprawki jest; False: brak (4xx albo przekierowanie na inną stronę);
    None: nie wiadomo (brak połączenia, 5xx, 429)."""
    try:
        resp = await client.get(url)
    except httpx.HTTPError:
        return None
    if resp.is_success:
        return resp.url.path == httpx.URL(url).path
    if 400 <= resp.status_code < 500 and resp.status_code != 429:
        return False
    return None


async def _resolve(client: httpx.AsyncClient, link: str, airac: dict) -> tuple[str, float]:
    """(adres, ile trzymać w pamięci): bieżąca poprawka, a gdy jej katalogu nie ma, najbliższa wcześniejsza."""
    computed = package_url(link, airac)
    cycle = airac
    for step in range(BACK_CYCLES + 1):
        url = package_url(link, cycle)
        found = await folder_exists(client, url)
        if found is None:
            return computed, TTL_UNKNOWN
        if found:
            if step:
                log.warning("eAIP %s: brak katalogu %s, pokazuję poprawkę %s", link, computed, url)
            return url, TTL_FOUND if step == 0 else TTL_FALLBACK
        cycle = current_airac(date.fromisoformat(cycle["effective"]) - timedelta(days=1))
    log.warning("eAIP %s: brak katalogu %s ani %d poprzednich, zostaje wyliczony adres", link, computed, BACK_CYCLES)
    return computed, TTL_FALLBACK


async def resolved_links(today: date | None = None, links=tuple(PACKAGES)) -> dict[str, str]:
    """Adresy dla /api/config i /api/embed-check: z .env bez zmian, inaczej katalog poprawki sprawdzony u PAŻP."""
    airac = current_airac(today or utc_today())
    out = {link: override(link) for link in links}
    todo = [link for link in links if not out[link]]
    now = time.monotonic()
    for link in list(todo):
        hit = _resolved.get((link, airac["ident"]))
        if hit and hit[0] > now:
            out[link] = hit[1]
            todo.remove(link)
    if todo:
        async with _client() as client:
            results = await asyncio.gather(*(_resolve(client, link, airac) for link in todo))
        for link, (url, ttl) in zip(todo, results):
            _resolved[(link, airac["ident"])] = (time.monotonic() + ttl, url)
            out[link] = url
    return out


async def resolved_url(link: str, today: date | None = None) -> str:
    return (await resolved_links(today, (link,)))[link]
