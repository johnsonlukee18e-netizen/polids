"""GAMET (prognoza obszarowa dla lotów na małych wysokościach) FIR EPWW z serwisu lotniczego IMGW (METEO › GAMET).

Źródło: https://aviation-api.imgw.pl/data/last?params=gamet&format=json&count=1, ten sam adres, z którego strona
awiacja.imgw.pl buduje dokumentację lotu. Kształt odpowiedzi odczytany z kodu tej strony (nie z żywej odpowiedzi,
serwer IMGW był nieosiągalny przy pisaniu): {"EPWW": {"A1": {"gamets": [{"message": "...", "messageHTML": "..."}]},
..., "A5": {...}}}, możliwe też opakowanie w "gamet". Dlatego odczyt jest ostrożny: inny klucz, lista zamiast
obiektu albo sam HTML nie kończą się błędem serwera, tylko komunikatem w "error".

Rejony A1–A5 (sektory FIS z 2010 r., granice zmienione 14.04.2026 razem z rejonami QNH); nagłówek rejonu:
"EPWW WARSAW FIR/A1 BLW FL100" (A2 i A5 w górach: BLW FL150). GAMET wydawany o 03, 09, 15 i 21 UTC, ważny 6 h."""

import html
import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from .http_cache import UpstreamError, fetch_text, peek

GAMET_URL = "https://aviation-api.imgw.pl/data/last"
PARAMS = {"params": "gamet", "format": "json", "count": "1"}
# zapas: inny projekt zgłaszał HTTP 400 dla parametru count (count=4); bez niego serwer zwraca ostatnie komunikaty
PARAMS_NO_COUNT = {"params": "gamet", "format": "json"}
TTL = 600   # GAMET zmienia się cztery razy na dobę (plus poprawki), więc 10 min wystarcza
SOURCE_URL = "https://awiacja.imgw.pl/prognozy-lotnicze/gamet"
AREAS = ("A1", "A2", "A3", "A4", "A5")
_AREA_KEY = re.compile(r"^A\d$")
_no_count = False   # serwer odrzucił count=1 (HTTP 400): kolejne zapytania od razu bez niego

VALID_RE = re.compile(r"\bVALID\s+(\d{6})/(\d{6})\b")
BELOW_RE = re.compile(r"\bBLW\s+FL\s?(\d{2,3})\b")
# nagłówek WMO pierwszej linii, np. "FAPL21 EPWA 150300" (czas wydania ddhhmm)
ISSUED_RE = re.compile(r"^\s*[A-Z]{4}\d{2}\s+[A-Z]{4}\s+(\d{6})\b", re.M)


def _status(exc: UpstreamError) -> int | None:
    cause = exc.__cause__
    return cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else None


async def _fetch() -> tuple[str, dict]:
    """Tekst odpowiedzi IMGW i parametry, z którymi go pobrano (do peek: wiek danych)."""
    global _no_count
    if not _no_count:
        try:
            return await fetch_text(GAMET_URL, TTL, params=PARAMS), PARAMS
        except UpstreamError as exc:
            if _status(exc) != 400:
                raise
            _no_count = True
    return await fetch_text(GAMET_URL, TTL, params=PARAMS_NO_COUNT), PARAMS_NO_COUNT


def strip_html(s: str) -> str:
    """messageHTML bez znaczników: <br> i koniec akapitu to nowa linia, encje HTML zamienione na znaki."""
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr)>", "\n", s)
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def _clean(s: str) -> str:
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _region(data) -> dict | None:
    """Słownik rejonów (A1…A5) z odpowiedzi: root["EPWW"], root["gamet"]["EPWW"] albo od razu rejony."""
    for cand in (data, data.get("gamet") if isinstance(data, dict) else None):
        if isinstance(cand, list) and len(cand) == 1:
            cand = cand[0]
        if not isinstance(cand, dict):
            continue
        if isinstance(cand.get("EPWW"), dict):
            return cand["EPWW"]
        if any(_AREA_KEY.match(str(k)) for k in cand):
            return cand
    return None


def _message(item) -> str | None:
    """Tekst GAMET rejonu: gamets[0].message, bez niego messageHTML bez znaczników (także gdy rejon to sama lista
    komunikatów albo sam komunikat)."""
    if isinstance(item, dict) and "gamets" in item:
        item = item["gamets"]
    if isinstance(item, list):
        item = item[0] if item else None
    if isinstance(item, str):
        return _clean(item) or None
    if not isinstance(item, dict):
        return None
    for key, conv in (("message", str), ("raw_message", str), ("messageHTML", strip_html)):
        if isinstance(item.get(key), str) and item[key].strip():
            return _clean(conv(item[key])) or None
    return None


def _ddhhmm(s: str, now: datetime) -> str | None:
    """"150400" (dzień, godzina, minuta UTC) jako data ISO najbliższa chwili now (przełom miesiąca w obie strony)."""
    d, hh, mm = int(s[:2]), int(s[2:4]), int(s[4:])
    if not (1 <= d <= 31 and hh <= 24 and mm < 60):
        return None
    best = None
    for months in (-1, 0, 1):
        y, m = now.year + (now.month - 1 + months) // 12, (now.month - 1 + months) % 12 + 1
        try:
            t = datetime(y, m, d, tzinfo=timezone.utc) + timedelta(hours=hh, minutes=mm)
        except ValueError:
            continue
        if best is None or abs(t - now) < abs(best - now):
            best = t
    return best.strftime("%Y-%m-%dT%H:%MZ") if best else None


def area_info(text: str | None, now: datetime) -> dict:
    """Ważność (VALID ddhhmm/ddhhmm), pułap rejonu (BLW FLnnn) i czas wydania z nagłówka WMO, jeśli są w tekście."""
    out = {"text": text, "valid": None, "valid_from": None, "valid_to": None, "below": None, "issued": None}
    if not text:
        return out
    if m := VALID_RE.search(text):
        out.update(valid=f"{m[1]}/{m[2]}", valid_from=_ddhhmm(m[1], now), valid_to=_ddhhmm(m[2], now))
    if m := BELOW_RE.search(text):
        out["below"] = f"FL{int(m[1]):03d}"
    if m := ISSUED_RE.search(text):
        out["issued"] = _ddhhmm(m[1], now)
    return out


def parse(text: str, now: datetime | None = None) -> dict:
    """{"areas": {"A1": {text, valid, valid_from, valid_to, below, issued}, ...}, "error": None albo opis}.
    Rejony A1–A5 zawsze (text None = brak komunikatu), inne klucze "An" z odpowiedzi także."""
    now = now or datetime.now(timezone.utc)
    empty = {a: area_info(None, now) for a in AREAS}
    try:
        data = json.loads(text)
    except ValueError:
        return {"areas": empty, "error": "Nieczytelna odpowiedź serwera IMGW (to nie JSON)"}
    region = _region(data)
    if region is None:
        return {"areas": empty, "error": "Nieznany format odpowiedzi IMGW: brak rejonów A1–A5"}
    keys = list(AREAS) + sorted(k for k in region if _AREA_KEY.match(str(k)) and k not in AREAS)
    areas = {k: area_info(_message(region.get(k)), now) for k in keys}
    error = None if any(a["text"] for a in areas.values()) else "Brak komunikatów GAMET w odpowiedzi IMGW"
    return {"areas": areas, "error": error}


async def get_gamet(now: datetime | None = None) -> dict:
    """GAMET do METEO › GAMET; nigdy wyjątek: przy awarii źródła "error" (i rejony bez tekstu), "stale" = starsze dane,
    bo serwer IMGW nie odpowiedział (fetch_text oddał ostatnią udaną odpowiedź)."""
    now = now or datetime.now(timezone.utc)
    base = {"source_url": SOURCE_URL, "fetched_at": None, "stale": False}
    try:
        text, params = await _fetch()
    except UpstreamError as exc:
        return {**base, "areas": {a: area_info(None, now) for a in AREAS}, "error": f"Serwer IMGW nie odpowiada: {exc}"}
    hit = peek(GAMET_URL, params)
    age = hit[0] if hit else 0.0
    out = {**base, **parse(text, now), "fetched_at": (now - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "stale": age >= TTL}
    return out
