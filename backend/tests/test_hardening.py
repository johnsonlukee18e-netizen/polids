import asyncio

import httpx

from backend.app.config import settings
from backend.app.services import http_cache


def test_concurrent_fetches_of_same_url_share_one_download(monkeypatch):
    calls = []

    async def fake_get(self, url, params=None):
        calls.append(url)
        await asyncio.sleep(0.05)
        return httpx.Response(200, text="DANE", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    http_cache.clear_cache()

    async def run():
        return await asyncio.gather(*(http_cache.fetch_text("https://example.test/feed", 30) for _ in range(30)))

    assert asyncio.run(run()) == ["DANE"] * 30 and len(calls) == 1


def test_cache_is_bounded(monkeypatch):
    async def fake_get(self, url, params=None):
        return httpx.Response(200, text=url, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(http_cache, "MAX_ENTRIES", 20)
    http_cache.clear_cache()

    async def run():
        for i in range(100):
            await http_cache.fetch_text(f"https://example.test/{i}", 300)
    asyncio.run(run())
    assert len(http_cache._cache) <= 20 and len(http_cache._locks) <= 21
    assert "https://example.test/99?" in http_cache._cache


def test_invalid_url_is_upstream_error(monkeypatch):
    http_cache.clear_cache()
    try:
        asyncio.run(http_cache.fetch_text("https://example.test/\x00", 30))
    except http_cache.UpstreamError:
        pass
    else:
        raise AssertionError("oczekiwano UpstreamError")


def test_user_agent_is_ascii_for_polish_names(monkeypatch):
    monkeypatch.setattr(settings, "name", "Pulpit Żółw Łódź")
    ua = settings.user_agent
    ua.encode("ascii")
    assert ua.startswith("PulpitZolwLodz/")
    httpx.Headers({"User-Agent": ua})
