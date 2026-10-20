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
# 0.12.6 (issue #21): tabela map stoi w komórce tabeli układu całej strony; jeden wpis na mapę z krótką nazwą.
CHARTS_TTL = 6 * 3600        # s: lista map z poprawki (adres strony zawiera katalog poprawki)
CHARTS_FAIL_TTL = 120        # s: po błędzie pobrania ponowna próba najwcześniej po 2 min (bez zapytań co kliknięcie)
CHARTS_MAX_BYTES = 25 * 1024 * 1024
CHART_FILE = re.compile(r"AD_2_([A-Z]{4})_(\d+)-(\d+)\.pdf$", re.I)
PAGE_LABEL = re.compile(r"(?:AD\s*2\s+[A-Z]{4}\s+)?\d+\s*-\s*\d+", re.I)   # kolumna "Pages": "AD 2 EPZG 2-1" albo "2-1"
# rodzaj mapy z pełnego tytułu (kolejność ma znaczenie: "PRECISION APPROACH TERRAIN CHART" to mapa terenu, nie podejścia,
# "VISUAL APPROACH CHART" i "VFR ARRIVAL AND DEPARTURE ROUTES" to mapy VFR, nie procedury według przyrządów).
# 0.12.6 (issue #21): mapa lotniska (ADC) i mapy postojowe (APDC) osobno: EPWA ma sześć map postojowych.
CHART_KINDS = (("OBST", ("OBSTACLE", "TERRAIN")),
               ("VFR", ("VISUAL", "VFR")),
               ("SID", ("STANDARD DEPARTURE", "INSTRUMENT DEPARTURE", "DEPARTURE CHART", "(SID)")),
               ("STAR", ("STANDARD ARRIVAL", "INSTRUMENT ARRIVAL", "ARRIVAL CHART", "(STAR)")),
               ("IAC", ("INSTRUMENT APPROACH", "APPROACH CHART")),
               ("APDC", ("PARKING", "DOCKING")),
               ("ADC", ("AERODROME CHART", "GROUND MOVEMENT", "AREAS OF RESPONSIBILITY")))

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


# znaczniki, które w przeglądarce zaczynają nową linię (tytuł mapy w dwóch liniach: "AERODROME<br/>GROUND MOVEMENT CHART",
# albo kilka tytułów w jednej komórce, każdy w osobnej linii)
BREAKS = {"br", "p", "div", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
# znaczniki bez zamknięcia: nie liczą się do zagnieżdżenia ukrytego elementu
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
# skreślone w poprawce AIRAC (<del>, <s>, <strike>, klasa "...Deleted...") i niewidoczne (style display:none)
HIDDEN_TAGS = {"del", "s", "strike"}
HIDDEN_CLASS = re.compile(r"deleted", re.I)
HIDDEN_STYLE = re.compile(r"display\s*:\s*none", re.I)
MAX_ROWSPAN = 500


class _Rows(HTMLParser):
    """Wiersze tabel jako drzewo i odnośniki w kolejności strony. Strona AD 2 eAIP PAŻP to tabela układu (każdy
    nagłówek i akapit w osobnym wierszu), a tabela map AD 2.24 stoi w komórce tej tabeli: wiersz tabeli zagnieżdżonej
    jest osobnym wierszem (z rodzicem = wiersz, w którego komórce stoi tabela), a jego tekst nie trafia do komórki
    rodzica (w 0.12.5 trafiał i wszystkie mapy EPWA dostawały jeden sklejony tytuł). Komórka: tekst i tekst z podziałem
    na linie (<br>, <p>, <div> zaczynają nową linię). Tekstu i odnośników skreślonych w poprawce i ukrytych nie bierzemy. <td> bez </td>
    i <tr> bez </tr> zamyka poprzednią komórkę / wiersz tej samej tabeli; <td> bez <tr> otwiera wiersz (jak przeglądarka);
    komórka z rowspan przechodzi do następnych wierszy tej samej tabeli. Nie rzuca wyjątku na żadnej zbitce znaczników:
    <a> bez </a> kończy się razem ze swoim wierszem albo na następnym <a> (odnośnik poza tabelą: na końcu strony)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []        # wszystkie wiersze w kolejności otwarcia
        self.links: list[dict] = []       # odnośniki w kolejności strony: {href, title, alt, text, row}
        self._stack: list[dict] = []      # otwarte wiersze (najbardziej wewnętrzny na końcu)
        self._tables: list[dict] = []     # otwarte tabele: {owner: wiersz, w którym stoi tabela, span: [(komórka, ile)]}
        self._hide: list[list] = []       # otwarte elementy skreślone / ukryte: [znacznik, ile takich samych w środku]
        self._a: dict | None = None       # otwarty <a href>

    @property
    def _row(self):
        return self._stack[-1] if self._stack else None

    def _text(self, data: str):
        if self._hide:
            return
        row = self._row
        # tekst tabeli zagnieżdżonej (przed jej pierwszym wierszem) nie należy do komórki rodzica
        if row is not None and row["cell"] is not None and row["level"] == len(self._tables):
            row["cell"].append(data)
        if self._a is not None:
            self._a["text"].append(data)

    def _hide_open(self, tag: str, attrs: dict):
        if tag in VOID:
            return
        if tag in HIDDEN_TAGS or (attrs and (HIDDEN_CLASS.search(attrs.get("class") or "")
                                             or HIDDEN_STYLE.search(attrs.get("style") or ""))):
            self._hide.append([tag, 0])
        elif self._hide and self._hide[-1][0] == tag:
            self._hide[-1][1] += 1

    def _hide_close(self, tag: str):
        if self._hide and self._hide[-1][0] == tag:
            if self._hide[-1][1]:
                self._hide[-1][1] -= 1
            else:
                self._hide.pop()

    def _open_row(self, hide: int):
        level = len(self._tables)
        while self._row is not None and self._row["level"] >= level:
            self._close_row()                     # <tr> bez </tr> poprzedniego wiersza tej samej tabeli
        table = self._tables[-1] if self._tables else None
        carried = []
        if table is not None:
            carried = [dict(c) for c, n in table["span"] if n > 0]
            table["span"] = [(c, n - 1) for c, n in table["span"] if n > 1]
        row = {"cells": carried, "cell": None, "links": [], "parent": table["owner"] if table else None,
               "level": level, "table": table, "rowspan": 1, "hide": hide, "cell_hide": hide}
        self._stack.append(row)
        self.rows.append(row)

    def _close_cell(self, row):
        if row["cell"] is None:
            return
        raw = "".join(row["cell"])
        cell = {"text": " ".join(raw.split()), "raw": raw}
        row["cells"].append(cell)
        if row["rowspan"] > 1 and row["table"] is not None:
            row["table"]["span"] = [(cell, row["rowspan"] - 1)]
        row["cell"] = None
        del self._hide[row["cell_hide"]:]           # skreślenie bez zamknięcia kończy się z komórką

    def _close_row(self):
        row = self._stack.pop()
        self._close_cell(row)
        if self._a is not None and self._a["row"] is row:
            self._a = None                         # <a> bez </a> kończy się z wierszem
        del self._hide[row["hide"]:]

    def _close_tables(self, level: int):
        """Zamyka tabele głębsze niż level (razem z ich wierszami), np. tabelę zagnieżdżoną bez </table>."""
        while len(self._tables) > level:
            while self._row is not None and self._row["level"] >= len(self._tables):
                self._close_row()
            self._tables.pop()

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag in BREAKS:
            self._text("\n")
        depth = len(self._hide)                      # skreślenia otwarte przed tym znacznikiem
        self._hide_open(tag, a)
        if tag == "table":
            self._tables.append({"owner": self._row, "span": []})
        elif tag == "tr":
            self._open_row(depth)
        elif tag in ("td", "th"):
            row = self._row
            if row is None or row["level"] != len(self._tables):
                if not self._tables and row is None:
                    return                           # komórka poza tabelą i wierszem: pomijamy
                self._open_row(depth)                # <td> bez <tr>: wiersz domyślny
                row = self._row
            self._close_cell(row)                    # <td> bez </td> poprzedniej komórki
            row["cell"] = []
            row["cell_hide"] = depth
            try:
                span = int(a.get("rowspan") or 1) if not row["cells"] else 1
            except ValueError:
                span = 1
            row["rowspan"] = max(1, min(span, MAX_ROWSPAN))
        elif tag == "a" and (href := a.get("href")) and not self._hide:
            row = self._row
            self._a = {"href": href, "title": a.get("title") or "", "alt": "", "text": [], "row": row}
            self.links.append(self._a)
        elif tag == "img" and self._a is not None and not self._hide and a.get("alt") and not self._a["alt"]:
            self._a["alt"] = a["alt"]

    def handle_endtag(self, tag):
        if tag in BREAKS:
            self._text("\n")
        self._hide_close(tag)
        if tag in ("td", "th"):
            row = self._row
            if row is not None and row["level"] < len(self._tables) and row["cell"] is not None:
                self._close_tables(row["level"])     # tabela w komórce bez </table>: kończy się z komórką
            if row is not None and row["level"] == len(self._tables):
                self._close_cell(row)
        elif tag == "tr":
            if self._row is not None and self._row["level"] == len(self._tables):
                self._close_row()
        elif tag == "table":
            self._close_tables(max(0, len(self._tables) - 1))
        elif tag == "a" and self._a is not None:
            self._a = None

    def handle_data(self, data):
        self._text(data)

    def close(self):
        super().close()
        while self._stack:
            self._close_row()
        self._a = None


def _chart_url(page_url: str, href: str) -> str | None:
    url = urljoin(page_url, href.strip())
    if urlsplit(url).scheme not in ("http", "https"):
        return None
    return quote(url, safe=":/?#[]@!$&'()*+,;=%~")   # spacje ("AIP IFR") → %20, istniejące %XX bez zmian


def _clean_title(text: str, icao: str) -> str:
    t = " ".join(text.split()).strip(" \"'“”„")
    return re.sub(rf"^{icao}\s*[-–]\s*", "", t, flags=re.I)


# opis odnośnika, który nie jest tytułem (alt ikony PDF-u)
JUNK_ALT = re.compile(r"\W*(?:pdf|icon|image|img|link|download|open)?\W*(?:\.(?:gif|png|jpe?g|svg))?", re.I)


def _row_title(row: dict) -> dict | None:
    """Komórka z tytułem wiersza: pierwsza niepusta, która nie jest numerem strony ("AD 2 EPZG 2-1", "2-1")."""
    return next((c for c in row["cells"] if c["text"] and not PAGE_LABEL.fullmatch(c["text"])), None)


def _split_titles(cell: dict, icao: str, n: int) -> list[str] | None:
    """Kilka tytułów w jednej komórce dla n map tego wiersza (w kolejności): podział po przedrostku "<ICAO> - " albo po
    liniach, gdy daje dokładnie n części; inaczej None."""
    parts = [p for p in re.split(rf"(?=\b{icao}\s*[-–]\s)", cell["text"], flags=re.I) if p.strip(" -–")]
    if len(parts) == n:
        return parts
    lines = [" ".join(x.split()) for x in cell["raw"].split("\n") if x.strip()]
    return lines if len(lines) == n else None


def _glued(text: str, icao: str) -> bool:
    """Sklejone tytuły kilku map (przedrostek "<ICAO> - " więcej niż raz): nie nadaje się na tytuł jednej mapy."""
    return len(re.findall(rf"\b{icao}\s*[-–]\s", text, flags=re.I)) > 1


def parse_charts(html: str, page_url: str, icao: str) -> list[dict]:
    """Mapy lotniska ze strony AD 2: odnośniki do PDF-ów AD_2_<ICAO>_<n>-<m>.pdf (tabela AD 2.24), jeden wpis na mapę,
    najpierw z tabel (w kolejności strony), potem spoza tabel, bez powtórzeń adresu.

    Tytuł: komórka tytułu wiersza z odnośnikiem (bez przedrostka "<ICAO> - "). Wiersz bez tytułu (odnośnik w tabeli
    zagnieżdżonej w komórce) bierze tytuł wiersza nadrzędnego tylko wtedy, gdy ten nie zawiera innych wierszy z tytułem
    (czyli jest wierszem jednej mapy, a nie tabelą układu wokół całej tabeli map). Kilka map z jednego tytułu: podział
    tytułu po przedrostku lotniska albo liniach (_split_titles), inaczej wspólny tytuł (rowspan: kilka PDF-ów jednej
    mapy). Bez tytułu: title odnośnika, alt obrazka, tekst odnośnika spoza tabeli, numer strony "AD 2 EPWA 2-1".

    Wpis: id "2-1" (numer z nazwy pliku, bez zer z przodu, 08-1 → 8-1), page "AD 2 EPWA 2-1", full (pełny tytuł),
    title (krótka nazwa, short_names), kind (ADC, APDC, SID, STAR, IAC, VFR, OBST, OTHER), url."""
    icao = icao.upper()
    p = _Rows()
    p.feed(html)
    p.close()
    own = {id(r): _row_title(r) for r in p.rows}
    # wiersze, w których (w tabeli zagnieżdżonej) jest wiersz z tytułem: tabela układu, nie wiersz jednej mapy
    outer: set[int] = set()
    for r in p.rows:
        if own[id(r)] is not None:
            x = r["parent"]
            while x is not None and id(x) not in outer:
                outer.add(id(x))
                x = x["parent"]

    def source(row):
        if own[id(row)] is not None:
            return row
        x = row
        while x is not None and id(x) not in outer:
            if own[id(x)] is not None:
                return x
            x = x["parent"]
        return None

    found, seen = [], set()
    for link in [x for x in p.links if x["row"] is not None] + [x for x in p.links if x["row"] is None]:
        href = link["href"]
        try:
            m = CHART_FILE.search(urlsplit(href.strip()).path)
            url = _chart_url(page_url, href) if m and m.group(1).upper() == icao else None
        except ValueError:   # adres, którego urllib nie rozbierze ("http://[x/..."): ten jeden odnośnik pomijamy
            continue
        if not url or url in seen:
            continue
        seen.add(url)
        found.append((link, url, m, source(link["row"]) if link["row"] is not None else None))

    groups: dict[int, list[int]] = {}
    for i, (_, _, _, src) in enumerate(found):
        if src is not None:
            groups.setdefault(id(src), []).append(i)
    texts = [""] * len(found)
    for members in groups.values():
        cell = own[id(found[members[0]][3])]
        parts = _split_titles(cell, icao, len(members)) if len(members) > 1 else None
        for k, i in enumerate(members):
            text = parts[k] if parts else cell["text"]
            texts[i] = "" if _glued(text, icao) else text

    out = []
    for i, (link, url, m, _) in enumerate(found):
        cid = f"{int(m.group(2))}-{int(m.group(3))}"
        alt = link["alt"] if not JUNK_ALT.fullmatch(link["alt"]) else ""
        loose = " ".join("".join(link["text"]).split()) if link["row"] is None else ""
        text = next((t for t in (texts[i], link["title"], alt, loose) if t and not _glued(t, icao)), "")
        full = _clean_title(text, icao) or f"AD 2 {icao} {cid}"
        out.append({"id": cid, "page": f"AD 2 {icao} {cid}", "title": full, "full": full, "kind": chart_kind(full),
                    "url": url})
    try:
        for c, name in zip(out, short_names([(c["full"], c["kind"]) for c in out])):
            c["title"] = name
    except Exception:   # nieprzewidziany tytuł: zostają pełne tytuły, lista map działa dalej
        log.exception("eAIP %s: krótkie nazwy map", icao)
    return out


# --- krótkie nazwy map (0.12.6, issue #21): na liście sama nazwa jednej mapy ("AERODROME", "RWY 29 SID",
# "PARKING APN 2", "RWY 11 ILS Z CAT II / LOC Z"), pełny tytuł w dymku. Bez przedrostka lotniska, "- ICAO" i słów
# ogólnych (CHART, STANDARD ... INSTRUMENT, AERODROME przed dłuższą nazwą). RNAV/RNP przy SID/STAR i kategorie statków
# powietrznych (CAT A,B,C,D) przy podejściach tylko wtedy, gdy odróżniają mapy o tej samej nazwie (EPBY: SID
# konwencjonalny i RNP dla RWY 08); mapy o tym samym tytule (EPLL: dwa SID RNP RWY 25) dostają "(1/2)", "(2/2)".
SHORT_PHRASES = tuple((re.compile(p, re.I), r) for p, r in (
    (r"\bAERODROME OBSTACLE CHART\b", "OBSTACLE"),
    (r"\bPRECISION APPROACH TERRAIN CHART\b", "PATC"),
    (r"\b(?:STANDARD\s+)?(?:INSTRUMENT\s+)?DEPARTURE\s+CHART\b(?:\s*-?\s*INSTRUMENT\b)?(?:\s*\(SID\))?|\(SID\)", " "),
    (r"\b(?:STANDARD\s+)?(?:INSTRUMENT\s+)?ARRIVAL\s+CHART\b(?:\s*-?\s*INSTRUMENT\b)?(?:\s*\(STAR\))?|\(STAR\)", " "),
    (r"\bINSTRUMENT\s+APPROACH\s+CHART\b", " "),
    (r"\bAIRCRAFT\s+PARKING(?:\s*(?:,|/|\bAND\b)\s*DOCKING)?\s+CHART\b", "PARKING"),
    (r"\bAERODROME\s+GROUND\s+MOVEMENT\s+CHART\b", "GROUND MOVEMENT"),
    (r"\bTWYS?\s+FOR\s+", ""),
    (r"\s*[-–]?\s*\bICAO\b\s*[-–]?", " "),
    (r"\bCHART\b", " "),
))
RWY_LIST = re.compile(r"\bRWYS?\s*(\d{2}[LRC]?(?:\s*(?:,|/|&|\bAND\b)\s*(?:RWYS?\s*)?\d{2}[LRC]?)*)\b", re.I)
ACFT_CAT = re.compile(r"\(?\bCAT\s+([A-EH](?:\s*[,/]\s*[A-EH])*)\b\)?", re.I)
NAV_SPEC = re.compile(r"\b(RNAV|RNP|GNSS|CONVENTIONAL|CONV)\b", re.I)
# nawias z oznaczeniem procedury albo miejsca postoju: bez nawiasu ("(ILS z) RWY 24" → "RWY 24 ILS Z", "(APN 2)" → "APN 2")
UNWRAP = re.compile(r"\(\s*((?:APN|TWY|ILS|LOC|VOR|NDB|RNP|RNAV|GNSS|GLS|DME|SRA|LPV|LNAV|TACAN|MIL)\b[^()]*)\)", re.I)
DESIGNATOR = re.compile(r"\b(ILS|LOC|VOR|NDB|RNP|RNAV|GLS|GNSS|DME|LPV|SRA|TACAN)\s+([a-z])\b")


def _tidy(t: str) -> str:
    t = re.sub(r"\(\s*\)", " ", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"(?:^|(?<=\s))[-–](?=\s|$)", " ", t)          # samotny łącznik po usuniętym słowie
    out, depth = [], 0
    for ch in t:                                                 # nawiasy bez pary
        if ch == "(":
            depth += 1
        elif ch == ")":
            if not depth:
                continue
            depth -= 1
        out.append(ch)
    t = "".join(out)
    while depth:
        i = t.rfind("(")
        t, depth = t[:i] + t[i + 1:], depth - 1
    t = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", t))
    return " ".join(t.split()).strip(" ,-–/")


def _name_parts(full: str, kind: str) -> tuple[str, str, str, str]:
    """(nazwa bez drogi startowej, "RWY 11/29", RNAV/RNP przy SID/STAR, "CAT A/B/C/D") z pełnego tytułu."""
    t = full
    for pat, rep in SHORT_PHRASES:
        t = pat.sub(rep, t)
    rwys: list[str] = []

    def rwy(m):
        rwys.extend(n for n in re.findall(r"\d{2}[LRC]?", m[1], re.I) if n not in rwys)
        return " "
    t = RWY_LIST.sub(rwy, t)
    cats: list[str] = []

    def cat(m):
        cats.append("CAT " + "/".join(re.findall(r"[A-EH]", m[1].upper())))
        return " "
    t = ACFT_CAT.sub(cat, t)
    nav: list[str] = []
    if kind in ("SID", "STAR"):
        def spec(m):
            nav.append(m[1].upper())
            return " "
        t = NAV_SPEC.sub(spec, t)
    t = UNWRAP.sub(r" \1 ", t)
    if kind == "IAC":
        t = re.sub(r"\s+OR\s+", " / ", t, flags=re.I)
    t = _tidy(DESIGNATOR.sub(lambda m: f"{m[1]} {m[2].upper()}", t))
    t = re.sub(r"^AERODROME\s+(?=\S)", "", t, flags=re.I)        # "AERODROME" tylko jako cała nazwa
    return t, f"RWY {'/'.join(rwys)}" if rwys else "", " ".join(dict.fromkeys(nav)), " ".join(dict.fromkeys(cats))


def _short(parts: tuple[str, str, str, str], kind: str, level: int) -> str:
    """Nazwa na poziomie szczegółów: 0 = sama nazwa, 1 = z RNAV/RNP (SID/STAR) i kategoriami statków (podejścia)."""
    rest, rwy, nav, cats = parts
    if kind in ("SID", "STAR"):
        words = [rwy, nav if level else "", kind, rest]
    elif kind == "IAC":
        words = [rwy, rest or "IAC", cats if level else ""]
    else:
        words = [rest, rwy, cats if level else ""]
    return " ".join(w for w in words if w)


def short_names(charts: list[tuple[str, str]]) -> list[str]:
    """Krótkie nazwy dla listy (pełny tytuł, rodzaj): mapy o tej samej nazwie dostają szczegóły (poziom 1: RNAV/RNP,
    kategorie; poziom 2: pełny tytuł) tylko do rozróżnienia, a jednakowe na każdym poziomie - "(1/2)", "(2/2)"."""
    parts = [_name_parts(full, kind) for full, kind in charts]

    def name(i: int, level: int) -> str:
        full, kind = charts[i]
        return full if level >= 2 else (_short(parts[i], kind, level) or full)

    def by_name(idx: list[int], level: int) -> list[list[int]]:
        groups: dict[str, list[int]] = {}
        for i in idx:
            groups.setdefault(name(i, level), []).append(i)
        return list(groups.values())

    out = [""] * len(charts)

    def assign(idx: list[int], level: int):
        if len(idx) == 1:
            out[idx[0]] = name(idx[0], level)
            return
        for lv in range(level + 1, 3):
            groups = by_name(idx, lv)
            if len(groups) > 1:
                for g in groups:
                    assign(g, lv)
                return
        for k, i in enumerate(idx):
            out[i] = f"{name(i, level)} ({k + 1}/{len(idx)})"

    for g in by_name(list(range(len(charts))), 0):
        assign(g, 0)
    return out


def _page_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True,
                             headers={"User-Agent": f"Mozilla/5.0 {settings.user_agent}"})


def _fetch_error(exc: BaseException) -> str:
    """Krótki opis błędu do listy map ("Chart list unavailable: …"), bez nazwy serwera."""
    if isinstance(exc, ValueError):
        return f"page could not be read ({exc})"
    if isinstance(exc, httpx.TimeoutException):
        return "no response (timeout)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TransportError):   # brak sieci, odmowa proxy, zerwane połączenie
        return "no connection"
    return f"page could not be read ({type(exc).__name__})"


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
            out["error"] = "no charts found"
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("eAIP %s: lista map z %s: %s", icao, page_url, exc)
        out["error"] = _fetch_error(exc)
    except Exception:   # nieprzewidziany błąd: komunikat zamiast 500, szczegóły w logu
        log.exception("eAIP %s: lista map z %s", icao, page_url)
        out["error"] = "page could not be read"
    _charts[page_url] = (time.monotonic() + (CHARTS_FAIL_TTL if out["error"] else CHARTS_TTL), out)
    return out


def reset_charts() -> None:
    _charts.clear()
    _charts_inflight.clear()


async def aerodrome_charts(icao: str, today: date | None = None) -> dict:
    """AD CIV: lista map lotniska z AD 2.24 eAIP IFR bieżącej poprawki (resolved_url, adres z .env wygrywa):
    {icao, page (strona AD 2), charts: [{id, page, title, full, kind, url}], error}. Jedno pobranie strony naraz
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
