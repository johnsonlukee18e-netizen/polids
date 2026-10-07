"""Pobieranie z zewnętrznych API z krótkim cache w pamięci. Równoczesne zapytania o ten sam adres czekają
na jedno pobranie (lock per klucz)."""

import asyncio
import time

import httpx

from ..config import settings

_cache: dict[str, tuple[float, str]] = {}
_locks: dict[str, asyncio.Lock] = {}
MAX_ENTRIES = 1000


class UpstreamError(Exception):
    pass


def _prune():
    if len(_cache) > MAX_ENTRIES:
        for key, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[:len(_cache) - MAX_ENTRIES * 8 // 10]:
            del _cache[key]
    if len(_locks) > MAX_ENTRIES:
        for key in [k for k, lock in _locks.items() if not lock.locked() and k not in _cache]:
            del _locks[key]


async def fetch_text(url: str, ttl: int, params: dict | None = None, headers: dict | None = None) -> str:
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
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


def clear_cache():
    _cache.clear()
    _locks.clear()
