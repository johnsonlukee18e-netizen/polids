"""Pobieranie z zewnętrznych API z krótkim cache w pamięci. Równoczesne zapytania o ten sam adres czekają
na jedno pobranie (lock per klucz)."""

import asyncio
import re
import time

import httpx

from ..config import settings

_cache: dict[str, tuple[float, str]] = {}
_locks: dict[str, asyncio.Lock] = {}
MAX_ENTRIES = 1000


class UpstreamError(Exception):
    pass


def describe(exc: BaseException) -> str:
    """Krótki opis błędu pobierania do interfejsu, bez adresu i nazwy serwera (komunikat UpstreamError z fetch_text
    zaczyna się od adresu): brak odpowiedzi, kod HTTP, brak połączenia albo pierwsza linia komunikatu bez adresów."""
    cause = exc.__cause__ if isinstance(exc, UpstreamError) and exc.__cause__ is not None else exc
    if isinstance(cause, httpx.TimeoutException):
        return "no response (timeout)"
    if isinstance(cause, httpx.HTTPStatusError):
        return f"HTTP {cause.response.status_code}"
    if isinstance(cause, httpx.ConnectError):
        return "no connection"
    if isinstance(cause, (httpx.NetworkError, httpx.ProtocolError)):
        return "connection interrupted"
    msg = str(exc).strip().split("\n")[0]
    # "<adres albo host>: <komunikat>" -> sam komunikat
    msg = re.sub(r"^(?:[a-z][a-z0-9+.-]*://)?[^\s:/]*\.[^\s:]*:\s*", "", msg, flags=re.I)
    msg = re.sub(r"\s+", " ", re.sub(r"'?https?://\S+", "", msg)).strip(" :")
    return (msg[:79].rstrip() + "…" if len(msg) > 80 else msg) or "error"


def _prune():
    if len(_cache) > MAX_ENTRIES:
        for key, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:len(_cache) - MAX_ENTRIES * 8 // 10]:
            del _cache[key]
    if len(_locks) > MAX_ENTRIES:
        for key in [k for k, lock in _locks.items() if not lock.locked() and k not in _cache]:
            del _locks[key]


def _key(url: str, params: dict | None = None) -> str:
    return url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))


async def fetch_text(url: str, ttl: int, params: dict | None = None, headers: dict | None = None) -> str:
    key = _key(url, params)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        async with _locks.setdefault(key, asyncio.Lock()):
            hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            try:
                async with httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True,
                                             headers={"User-Agent": settings.user_agent, **(headers or {})}) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                if hit:  # lepiej pokazać starsze dane niż nic
                    return hit[1]
                raise UpstreamError(f"{url}: {exc}") from exc
            _cache[key] = (time.monotonic(), resp.text)
            return resp.text
    finally:
        _prune()


def peek(url: str, params: dict | None = None) -> tuple[float, str] | None:
    """Ostatnio pobrany tekst adresu i jego wiek w sekundach, bez pobierania i bez względu na ttl (None = brak).
    Wiek >= ttl tuż po fetch_text znaczy, że serwer nie odpowiedział i fetch_text oddał starsze dane."""
    hit = _cache.get(_key(url, params))
    return (time.monotonic() - hit[0], hit[1]) if hit else None


def forget(url: str, params: dict | None = None):
    """Usuwa adres z cache: odpowiedź 200 z nieczytelną treścią nie wraca z cache przez cały ttl."""
    _cache.pop(_key(url, params), None)


def clear_cache():
    _cache.clear()
    _locks.clear()
