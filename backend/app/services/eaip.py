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
import re
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

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


# --- AD CIV (0.12.5, issue #18): przycisk lotniska prowadzi do listy map, a nie do opisu tekstowego. eAIP PAŻP nie ma
# osobnej strony z listą map lotniska: mapy są w tabeli AD 2.24 ("AERONAUTICAL CHARTS RELATED TO AN AERODROME") na
# końcu strony AD 2 lotniska (eAIP/AD 2 EPWA 1-en-GB.html, ta sama poprawka co index-v2.html), wiersz = tytuł mapy
# i ikona z odnośnikiem do PDF-u .../documents/Root_WePub/AIP IFR/AD/EPZG/02/AD_2_EPZG_2-1.pdf. Serwer pobiera tę stronę
# (kilka MB przy EPWA), wyciąga wiersze z PDF-ami map lotniska i trzyma wynik w pamięci (strona zmienia się z AIRAC).
CHARTS_TTL = 6 * 3600        # s: lista map z poprawki (adres strony zawiera katalog poprawki)
CHARTS_FAIL_TTL = 120        # s: po błędzie pobrania ponowna próba najwcześniej po 2 min (bez zapytań co kliknięcie)
CHARTS_MAX_BYTES = 25 * 1024 * 1024
CHART_FILE = re.compile(r"AD_2_([A-Z]{4})_(\d+)-(\d+)\.pdf$", re.I)
PAGE_LABEL = re.compile(r"(?:AD\s*2\s+[A-Z]{4}\s+)?\d+\s*-\s*\d+", re.I)   # kolumna "Pages": "AD 2 EPZG 2-1" albo "2-1"
# rodzaj mapy z tytułu (kolejność ma znaczenie: "PRECISION APPROACH TERRAIN CHART" to mapa terenu, nie podejścia,
# a "VISUAL APPROACH CHART" to mapa VFR, nie podejście według przyrządów)
CHART_KINDS = (("OBST", ("OBSTACLE", "TERRAIN")),
               ("SID", ("STANDARD DEPARTURE", "INSTRUMENT DEPARTURE", "DEPARTURE CHART", "(SID)")),
               ("STAR", ("STANDARD ARRIVAL", "INSTRUMENT ARRIVAL", "ARRIVAL CHART", "(STAR)")),
               ("VFR", ("VISUAL", "VFR")), ("IAC", ("INSTRUMENT APPROACH", "APPROACH CHART")),
               ("AD", ("AERODROME CHART", "PARKING", "DOCKING", "GROUND MOVEMENT")))

# lotniska z częścią AD 2 eAIP IFR (AD 1.3, AIRAC AMDT 10-26); ta sama lista co AD2 w frontend/js/tabs/aip.js.
# Inny kod EPxx nie trafia do PAŻP (każdy dawałby pobranie strony, której nie ma).
AD2_AERODROMES = ("EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY", "EPWA",
                  "EPWR", "EPZG")
_charts: dict[str, tuple[float, dict]] = {}          # adres strony AD 2 -> (ważny do, wynik)
_charts_inflight: dict[str, asyncio.Task] = {}


def aerodrome_page_url(base: str, icao: str) -> str:
    """Strona AD 2 lotniska z tej samej poprawki co index-v2.html (jak aeroPageUrl w tabs/aip.js); adres katalogu
    bez "/" na końcu traktujemy jak katalog; ?query i #fragment odpadają."""
    parts = urlsplit(base)
    path = parts.path
    if not path.endswith("/") and not re.search(r"\.[a-z0-9]+$", path, re.I):
        path += "/"
    root = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return urljoin(root, quote(f"eAIP/AD 2 {icao} 1-en-GB.html"))


def chart_kind(title: str) -> str:
    t = title.upper()
    return next((kind for kind, words in CHART_KINDS if any(w in t for w in words)), "OTHER")


# znaczniki, które w przeglądarce rozdzielają słowa (tytuł mapy w dwóch liniach: "AERODROME<br/>GROUND MOVEMENT CHART")
BREAKS = {"br", "p", "div", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "h6"}


class _Rows(HTMLParser):
    """Wiersze tabel (teksty komórek, odnośniki i ich zapasowe opisy: title odnośnika albo alt obrazka) oraz odnośniki
    poza tabelami (adres, tekst). Odporny na eAIP: <br>/<p>/<div> rozdzielają słowa; tekst i odnośniki w <del> (zmiana
    z poprawki: skreślone) pomijamy; <td> bez </td> i <tr> bez </tr> zamyka poprzednią komórkę / wiersz; tabela
    zagnieżdżona w komórce należy do tej komórki; komórka z rowspan przechodzi do następnych wierszy (tytuł mapy
    wspólny dla kilku PDF-ów)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[list[str], list[str], list[str]]] = []   # (komórki, odnośniki, opisy odnośników)
        self.loose: list[tuple[str, str]] = []
        self._stack: list[dict] = []          # otwarte wiersze (zagnieżdżone tabele): {cells, hrefs, alts, cell}
        self._span: list[tuple[str, int]] = []   # komórka z rowspan z poprzedniego wiersza: (tekst, ile wierszy jeszcze)
        self._a: tuple[str, list[str]] | None = None
        self._del = 0
        self._tables = 0                      # otwarte <table> (wiersz należy do najbardziej wewnętrznej)

    @property
    def _row(self):
        return self._stack[-1] if self._stack else None

    def _text(self, data: str):
        if self._del:
            return
        row = self._row
        if row is not None and row["cell"] is not None:
            row["cell"].append(data)
        if self._a is not None:
            self._a[1].append(data)

    def _close_cell(self, row):
        if row["cell"] is not None:
            text = " ".join("".join(row["cell"]).split())
            row["cells"].append(text)
            if row["rowspan"] > 1 and row["depth"] == 1:
                self._span = [(text, row["rowspan"] - 1)]
            row["cell"] = None

    def _close_row(self):
        row = self._stack.pop()
        self._close_cell(row)
        parent = self._row
        if parent is not None and parent["cell"] is not None:
            # wiersz tabeli zagnieżdżonej w komórce: tekst i odnośniki należą do komórki zewnętrznej
            parent["cell"].append(" " + " ".join(row["cells"]) + " ")
            parent["hrefs"] += row["hrefs"]
            parent["alts"] += row["alts"]
        else:
            self.rows.append((row["cells"], row["hrefs"], row["alts"]))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in BREAKS:
            self._text(" ")
        if tag == "del":
            self._del += 1
        elif tag == "table":
            self._tables += 1
        elif tag == "tr":
            while self._row is not None and self._row["table"] >= self._tables:
                self._close_row()                     # <tr> bez </tr> poprzedniego wiersza tej samej tabeli
            carried = [t for t, n in self._span if n > 0] if not self._stack else []
            self._span = [(t, n - 1) for t, n in self._span if n > 1] if not self._stack else self._span
            self._stack.append({"cells": carried, "hrefs": [], "alts": [], "cell": None, "rowspan": 1,
                                "depth": len(self._stack) + 1, "table": self._tables})
        elif tag in ("td", "th") and self._row is not None:
            row = self._row
            self._close_cell(row)                     # <td> bez </td> poprzedniej komórki
            row["cell"] = []
            try:
                row["rowspan"] = int(a.get("rowspan") or 1) if not row["cells"] else 1
            except ValueError:
                row["rowspan"] = 1
        elif tag == "a" and (href := a.get("href")) and not self._del:
            self._a = (href, [])
            if self._row is not None:
                self._row["hrefs"].append(href)
                self._row["alts"].append(a.get("title") or "")
        elif tag == "img" and self._a is not None and self._row is not None and a.get("alt") and not self._row["alts"][-1]:
            self._row["alts"][-1] = a["alt"]

    def handle_endtag(self, tag):
        if tag in BREAKS:
            self._text(" ")
        if tag == "del":
            self._del = max(0, self._del - 1)
        elif tag in ("td", "th") and self._row is not None:
            self._close_cell(self._row)
        elif tag == "tr" and self._row is not None:
            self._close_row()
        elif tag == "table":
            while self._row is not None and self._row["table"] >= self._tables:
                self._close_row()                     # tabela zamknięta bez </tr>
            self._tables = max(0, self._tables - 1)
        elif tag == "a" and self._a is not None:
            if self._row is None:
                self.loose.append((self._a[0], " ".join("".join(self._a[1]).split())))
            self._a = None

    def handle_data(self, data):
        self._text(data)

    def close(self):
        super().close()
        while self._stack:
            self._close_row()


def _chart_url(page_url: str, href: str) -> str | None:
    url = urljoin(page_url, href.strip())
    if urlsplit(url).scheme not in ("http", "https"):
        return None
    return quote(url, safe=":/?#[]@!$&'()*+,;=%~")   # spacje ("AIP IFR") → %20, istniejące %XX bez zmian


def _clean_title(text: str, icao: str) -> str:
    t = " ".join(text.split()).strip(" \"'“”„")
    return re.sub(rf"^{icao}\s*[-–]\s*", "", t, flags=re.I)


def parse_charts(html: str, page_url: str, icao: str) -> list[dict]:
    """Mapy lotniska ze strony AD 2: wiersze tabeli z odnośnikiem do PDF-u AD_2_<ICAO>_<n>-<m>.pdf (tabela AD 2.24;
    tytuł = pierwsza niepusta komórka poza numerem strony, bez przedrostka "<ICAO> - "), w kolejności strony,
    bez powtórzeń adresu.
    Bez tytułu w komórkach: title odnośnika albo alt obrazka. Odnośnik do mapy poza tabelą: tytuł z tekstu odnośnika. id "2-1" (numer z nazwy pliku, bez zer z przodu,
    08-1 → 8-1), page "AD 2 EPWA 2-1", kind: AD, OBST, SID, STAR, IAC, VFR albo OTHER."""
    icao = icao.upper()
    p = _Rows()
    p.feed(html)
    p.close()
    found = [(href, next((c for c in cells if c and not PAGE_LABEL.fullmatch(c)), "") or alt)
             for cells, hrefs, alts in p.rows for href, alt in zip(hrefs, alts)]
    found += p.loose
    out, seen = [], set()
    for href, text in found:
        m = CHART_FILE.search(urlsplit(href.strip()).path)
        if not m or m.group(1).upper() != icao:
            continue
        url = _chart_url(page_url, href)
        if not url or url in seen:
            continue
        seen.add(url)
        cid = f"{int(m.group(2))}-{int(m.group(3))}"
        title = _clean_title(text, icao) or f"AD 2 {icao} {cid}"
        out.append({"id": cid, "page": f"AD 2 {icao} {cid}", "title": title, "kind": chart_kind(title), "url": url})
    return out


def _page_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True,
                             headers={"User-Agent": f"Mozilla/5.0 {settings.user_agent}"})


def _fetch_error(exc: BaseException) -> str:
    if isinstance(exc, ValueError):
        return f"eAIP page could not be read ({exc})"
    if isinstance(exc, httpx.TimeoutException):
        return "no response from the eAIP server (timeout)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"eAIP server: HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TransportError):   # brak sieci, odmowa proxy, zerwane połączenie
        return "cannot connect to the eAIP server"
    return f"eAIP page could not be read ({type(exc).__name__})"


async def _load_charts(page_url: str, icao: str) -> dict:
    out = {"icao": icao, "page": page_url, "charts": [], "error": None}
    try:
        async with _page_client() as client:
            async with client.stream("GET", page_url) as resp:
                resp.raise_for_status()
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > CHARTS_MAX_BYTES:
                        raise ValueError(f"page larger than {CHARTS_MAX_BYTES // 1048576} MB")
                    chunks.append(chunk)
                raw, enc = b"".join(chunks), resp.encoding or "utf-8"
        # strona AD 2 ma kilka MB: dekodowanie i parsowanie poza pętlą zdarzeń (inaczej serwer stoi 1-3 s)
        out["charts"] = await asyncio.to_thread(lambda: parse_charts(raw.decode(enc, errors="replace"), page_url, icao))
        if not out["charts"]:
            out["error"] = "no charts found in AD 2.24 of the eAIP page"
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("eAIP %s: lista map z %s: %s", icao, page_url, exc)
        out["error"] = _fetch_error(exc)
    except Exception:   # nieprzewidziany błąd: komunikat zamiast 500, szczegóły w logu
        log.exception("eAIP %s: lista map z %s", icao, page_url)
        out["error"] = "eAIP page could not be read"
    _charts[page_url] = (time.monotonic() + (CHARTS_FAIL_TTL if out["error"] else CHARTS_TTL), out)
    return out


def reset_charts() -> None:
    _charts.clear()
    _charts_inflight.clear()


async def aerodrome_charts(icao: str, today: date | None = None) -> dict:
    """AD CIV: lista map lotniska z AD 2.24 eAIP IFR bieżącej poprawki (resolved_url, adres z .env wygrywa):
    {icao, page (strona AD 2), charts: [{id, page, title, kind, url}], error}. Jedno pobranie strony naraz
    (single-flight), wynik w pamięci CHARTS_TTL, po błędzie CHARTS_FAIL_TTL."""
    icao = icao.upper()
    page_url = aerodrome_page_url(await resolved_url("aip_ifr", today), icao)
    hit = _charts.get(page_url)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    task = _charts_inflight.get(page_url)
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.get_running_loop().create_task(_load_charts(page_url, icao))
        _charts_inflight[page_url] = task
        task.add_done_callback(lambda t: _charts_inflight.pop(page_url) if _charts_inflight.get(page_url) is t else None)
    return await asyncio.shield(task)
