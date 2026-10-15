"""Adresy eAIP PAŻP (IFR, VFR, MIL) dla bieżącego cyklu AIRAC.

PAŻP publikuje każdą poprawkę AIRAC w osobnym katalogu, np. eaipifr/AIRAC AMDT 10-26_2026_10_01/index-v2.html
(numer cyklu w roku, rok, data wejścia w życie). Stare katalogi zostają na serwerze, więc stały adres po zmianie cyklu
nie daje błędu, tylko po cichu pokazuje nieaktualną poprawkę. Dlatego bez POLIDS_AIP_*_URL w .env adres jest liczony
przy każdym zapytaniu z cyklu na dziś (UTC: AIRAC zmienia się o 00:00 UTC), a jawny adres z .env wygrywa bez zmian.

Nie każdy cykl ma poprawkę: dla 2513 (25.12.2025) katalogu AIRAC AMDT 13-25 nie ma w żadnym z trzech pakietów i przez
cały cykl obowiązuje 12-25. Dlatego wyliczony katalog sprawdzamy na serwerze PAŻP (resolve): brak (4xx) → cykl
wcześniej, najwyżej BACK_CYCLES razy; błąd sieci albo serwera → zostaje wyliczony adres. Wynik w pamięci na cykl.

/api/config (od niego zależy otwarcie HOME i menu) nie czeka na PAŻP dłużej niż CONFIG_WAIT: jedno sprawdzenie na
pakiet naraz (wspólne dla wszystkich zapytań, single-flight), po CONFIG_WAIT ostatni znany adres albo wyliczony, a
sprawdzenie kończy się w tle i uzupełnia pamięć. Po upływie ważności wpisu odpowiedź od razu z poprzedniego wyniku
tego cyklu, sprawdzenie ponownie w tle. Pierwsze sprawdzenie startuje razem z serwerem (warm, main.lifespan)."""

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
PROBE_TIMEOUT = 4.0      # s na jedno sprawdzenie katalogu, łącznie (httpx liczy czas osobno na każdą fazę)
CONFIG_WAIT = 1.5        # s: najdłużej /api/config i /api/embed-check czekają na sprawdzenie, potem wyliczony adres
TTL_FOUND = 28 * 86400   # katalog bieżącego cyklu jest: do końca cyklu (klucz pamięci zawiera numer cyklu)
TTL_FALLBACK = 6 * 3600  # bieżącego nie ma: sprawdzamy znowu co kilka godzin (PAŻP może dołożyć katalog później)
TTL_UNKNOWN = 600        # brak połączenia z PAŻP: wyliczony adres, ponowna próba po 10 min

_resolved: dict[tuple[str, str], tuple[float, str]] = {}   # (link, cykl) -> (ważny do, adres); po terminie: stary wynik
_inflight: dict[tuple[str, str], asyncio.Task] = {}        # (link, cykl) -> sprawdzenie w toku (silna referencja)


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
    _inflight.clear()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=min(settings.http_timeout, PROBE_TIMEOUT), follow_redirects=True,
                             headers={"User-Agent": f"Mozilla/5.0 {settings.user_agent}"})


async def _status(client: httpx.AsyncClient, url: str) -> tuple[int, str]:
    """Kod odpowiedzi i ścieżka po przekierowaniach, bez pobierania treści strony."""
    async with client.stream("GET", url) as resp:
        return resp.status_code, resp.url.path


async def folder_exists(client: httpx.AsyncClient, url: str) -> bool | None:
    """True: index-v2.html poprawki jest; False: brak (4xx albo przekierowanie na inną stronę);
    None: nie wiadomo (brak połączenia, 5xx, 429, brak odpowiedzi w PROBE_TIMEOUT)."""
    try:
        status, path = await asyncio.wait_for(_status(client, url), PROBE_TIMEOUT)
    except (httpx.HTTPError, TimeoutError):
        return None
    if 200 <= status < 300:
        return path == httpx.URL(url).path
    if 400 <= status < 500 and status != 429:
        return False
    return None


async def _resolve(client: httpx.AsyncClient, link: str, airac: dict) -> tuple[str, float]:
    """(adres, ile trzymać w pamięci): bieżąca poprawka, a gdy jej katalogu nie ma, najbliższa wcześniejsza.
    Najpierw sam bieżący cykl (zwykle jest: jedno zapytanie), potem BACK_CYCLES poprzednich naraz; wynik jak przy
    sprawdzaniu po kolei: najnowszy katalog, który jest, a "nie wiadomo" przed nim → wyliczony adres."""
    computed = package_url(link, airac)
    cycles = [airac]
    for _ in range(BACK_CYCLES):
        cycles.append(current_airac(date.fromisoformat(cycles[-1]["effective"]) - timedelta(days=1)))
    urls = [package_url(link, c) for c in cycles]
    found = [await folder_exists(client, urls[0])]
    if found[0] is False:
        found += await asyncio.gather(*(folder_exists(client, u) for u in urls[1:]))
    for step, (url, ok) in enumerate(zip(urls, found)):
        if ok is None:
            return computed, TTL_UNKNOWN
        if ok:
            if step:
                log.warning("eAIP %s: brak katalogu %s, pokazuję poprawkę %s", link, computed, url)
            return url, TTL_FOUND if step == 0 else TTL_FALLBACK
    log.warning("eAIP %s: brak katalogu %s ani %d poprzednich, zostaje wyliczony adres", link, computed, BACK_CYCLES)
    return computed, TTL_FALLBACK


async def _refresh(link: str, airac: dict) -> str:
    """Sprawdzenie jednego pakietu u PAŻP i zapis w pamięci (zadanie w tle, wspólne dla zapytań)."""
    key = (link, airac["ident"])
    try:
        async with _client() as client:
            url, ttl = await _resolve(client, link, airac)
    except Exception:   # nieprzewidziany błąd: jak brak połączenia, bez wyjątku w zadaniu, którego nikt nie odbierze
        log.exception("eAIP %s: sprawdzenie katalogu nie powiodło się", link)
        url, ttl = _resolved.get(key, (0.0, package_url(link, airac)))[1], TTL_UNKNOWN
    _resolved[key] = (time.monotonic() + ttl, url)
    return url


def _start(link: str, airac: dict) -> asyncio.Task:
    """Sprawdzenie (link, cykl) w toku albo nowe: jedno naraz, niezależnie od liczby zapytań (single-flight)."""
    key = (link, airac["ident"])
    task = _inflight.get(key)
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.get_running_loop().create_task(_refresh(link, airac))
        _inflight[key] = task
        task.add_done_callback(lambda t: _inflight.pop(key) if _inflight.get(key) is t else None)
    return task


def warm() -> None:
    """Start serwera: sprawdzenie bieżących katalogów w tle, zanim pierwsza przeglądarka zapyta o /api/config."""
    airac = current_airac(utc_today())
    for link in PACKAGES:
        if not override(link):
            _start(link, airac)


async def resolved_links(today: date | None = None, links=tuple(PACKAGES)) -> dict[str, str]:
    """Adresy dla /api/config i /api/embed-check: z .env bez zmian, inaczej katalog poprawki sprawdzony u PAŻP.
    Bez wyniku dla tego cyklu czeka na sprawdzenie najwyżej CONFIG_WAIT, potem wyliczony adres (sprawdzenie trwa dalej
    w tle); wynik po terminie ważności: od razu on, a nowe sprawdzenie w tle."""
    airac = current_airac(today or utc_today())
    out = {link: override(link) for link in links}
    now = time.monotonic()
    waiting: dict[str, asyncio.Task] = {}
    for link in links:
        if out[link]:
            continue
        hit = _resolved.get((link, airac["ident"]))
        if hit and hit[0] > now:
            out[link] = hit[1]
            continue
        task = _start(link, airac)
        if hit:
            out[link] = hit[1]
        else:
            waiting[link] = task
    if waiting:
        await asyncio.wait(waiting.values(), timeout=CONFIG_WAIT)   # bez anulowania: zadania kończą się w tle
        for link, task in waiting.items():
            ok = task.done() and not task.cancelled() and task.exception() is None
            out[link] = task.result() if ok else package_url(link, airac)
    return out


async def resolved_url(link: str, today: date | None = None) -> str:
    return (await resolved_links(today, (link,)))[link]
