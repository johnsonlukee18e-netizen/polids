import json
import re
from datetime import datetime, timedelta, timezone

from ..config import settings
from .http_cache import fetch_text
from .lvp import obs_time

# 0.13.2 (issue #27): najnowszy znany METAR każdego lotniska ze wszystkich zapytań. Każda lista lotnisk to osobny adres
# z własną pamięcią podręczną (weather_cache_seconds): AWOS pyta o jedno lotnisko, METEO i OVERVIEW o wiele naraz, więc
# po nowym METAR (np. BKN009) METEO mogło go już pokazywać, a AWOS jeszcze do 2 min (plus 1 min odświeżania widoku)
# starszy METAR i VMC. Teraz z dwóch METAR-ów lotniska wygrywa późniejsza obserwacja, niezależnie od zapytania.
# Lotnisko, którego bieżąca odpowiedź nie zawiera, zostaje bez METAR jak dotąd (pamięć tylko zastępuje starszy).
_newest: dict[str, tuple[datetime, str]] = {}
NEWEST_MAX = 2000                  # tyle lotnisk w pamięci; przy przekroczeniu wypadają obserwacje starsze niż 6 h
NEWEST_KEEP = timedelta(hours=6)
OBS_RE = re.compile(r"\b(\d{6}Z)\b")


def reset_newest() -> None:
    """Zapomina najnowsze METAR-y (testy)."""
    _newest.clear()


def _observed(raw: str, now: datetime) -> datetime | None:
    m = OBS_RE.search(raw or "")
    return obs_time(m.group(1), now) if m else None


def newest(out: dict[str, str], now: datetime | None = None) -> dict[str, str]:
    """{ICAO: METAR} z odpowiedzi serwera, w którym METAR starszy od znanego już z innego zapytania zastępuje nowszy
    (ten sam czas obserwacji: wygrywa świeża odpowiedź, np. poprawka COR)."""
    now = now or datetime.now(timezone.utc)
    for icao, raw in list(out.items()):
        t = _observed(raw, now)
        if t is None:
            continue
        known = _newest.get(icao)
        if known and known[0] > t:
            out[icao] = known[1]
        else:
            _newest[icao] = (t, raw)
    if len(_newest) > NEWEST_MAX:
        for icao in [i for i, (t, _) in _newest.items() if now - t > NEWEST_KEEP]:
            del _newest[icao]
    return out


async def get_metars(icaos: list[str]) -> dict[str, str]:
    """Zwraca {ICAO: surowy METAR}; z kilku znanych METAR-ów lotniska najnowszy (newest)."""
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
        return newest(out)
    text = await fetch_text(f"{settings.awc_api}/metar", settings.weather_cache_seconds,
                            {"ids": ",".join(icaos), "format": "json"})
    return newest({d["icaoId"]: d["rawOb"] for d in json.loads(text or "[]")})


async def get_tafs(icaos: list[str]) -> dict[str, str]:
    icaos = [i.upper() for i in icaos if i]
    if not icaos:
        return {}
    text = await fetch_text(f"{settings.awc_api}/taf", settings.weather_cache_seconds,
                            {"ids": ",".join(icaos), "format": "json"})
    return {d["icaoId"]: d["rawTAF"] for d in json.loads(text or "[]")}
