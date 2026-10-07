import json

from ..config import settings
from .http_cache import fetch_text


async def get_metars(icaos: list[str]) -> dict[str, str]:
    """Zwraca {ICAO: surowy METAR}."""
    icaos = [i.upper() for i in icaos if i]
    if not icaos:
        return {}
    if settings.metar_source == "vatsim":
        text = await fetch_text(settings.vatsim_metar_url.format(icao=",".join(icaos)), settings.weather_cache_seconds)
        out = {}
        for line in text.splitlines():
            line = line.strip()
            if len(line) > 4 and line[:4] in icaos:
                out[line[:4]] = line
        return out
    text = await fetch_text(f"{settings.awc_api}/metar", settings.weather_cache_seconds,
                            {"ids": ",".join(icaos), "format": "json"})
    return {d["icaoId"]: d["rawOb"] for d in json.loads(text or "[]")}


async def get_tafs(icaos: list[str]) -> dict[str, str]:
    icaos = [i.upper() for i in icaos if i]
    if not icaos:
        return {}
    text = await fetch_text(f"{settings.awc_api}/taf", settings.weather_cache_seconds,
                            {"ids": ",".join(icaos), "format": "json"})
    return {d["icaoId"]: d["rawTAF"] for d in json.loads(text or "[]")}
