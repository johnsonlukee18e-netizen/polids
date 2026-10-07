"""Czy zewnętrzną stronę da się pokazać w ramce (iframe)? Sprawdzamy nagłówki, które wysyła jej serwer.

Przeglądarka nie mówi stronie, że ramka została zablokowana, więc pytamy serwer z backendu i dopiero wtedy
wybieramy: ramka albo przycisk "otwórz w nowej karcie"."""

import re
import time

import httpx

from ..config import settings

_cache: dict[str, tuple[float, dict]] = {}
_LOCAL = ("http://127.0.0.1", "http://localhost")


def _own_origins() -> tuple[str, ...]:
    return (*_LOCAL, settings.public_origin)


def frame_policy(headers) -> tuple[bool, str]:
    """(czy wolno osadzić, powód blokady) na podstawie X-Frame-Options i CSP frame-ancestors."""
    xfo = headers.get("x-frame-options", "").strip().upper()
    if xfo:
        return False, f"X-Frame-Options: {xfo}"
    policies = headers.get_list("content-security-policy") if hasattr(headers, "get_list") \
        else [headers.get("content-security-policy", "")]
    for csp in policies:
        m = re.search(r"frame-ancestors\s+([^;]*)", csp or "", re.I)
        if not m:
            continue
        srcs = m.group(1).split()
        if "*" in srcs or any(s.rstrip("/").startswith(_own_origins()) for s in srcs):
            continue
        return False, "Content-Security-Policy: frame-ancestors " + (m.group(1).strip() or "'none'")
    return True, ""


async def check(url: str, ttl: int = 3600) -> dict:
    hit = _cache.get(url)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout, follow_redirects=True,
                                     headers={"User-Agent": f"Mozilla/5.0 {settings.user_agent}"}) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return {"url": url, "embeddable": None, "reason": f"brak połączenia: {exc.__class__.__name__}"}
    ok, reason = frame_policy(resp.headers)
    final = str(resp.url)
    if ok and re.search(r"log-?in|sign-?in|auth", final, re.I) and final != url:
        reason = "strona przekierowuje do logowania"
    result = {"url": url, "final_url": final, "status": resp.status_code, "embeddable": ok, "reason": reason}
    _cache[url] = (time.monotonic(), result)
    return result
