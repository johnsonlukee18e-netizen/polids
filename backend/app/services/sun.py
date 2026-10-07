"""Wschód i zachód słońca oraz zmierzch cywilny (algorytm NOAA, dokładność ok. 1 min) w UTC."""

import math
from datetime import date, datetime, timezone


def _event(day: date, lat: float, lon: float, zenith: float, rising: bool) -> float | None:
    """Minuta doby UTC zdarzenia (wschód / zachód dla danego kąta zenitalnego) albo None (dzień / noc polarna)."""
    n = day.timetuple().tm_yday
    minutes = 720.0
    for _ in range(2):  # drugi przebieg z porą dnia z pierwszego przybliżenia
        g = 2 * math.pi / 365 * (n - 1 + (minutes / 60 - 12) / 24)
        eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                           - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
        decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
                + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
        la = math.radians(lat)
        x = math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
        if not -1 <= x <= 1:
            return None
        ha = math.degrees(math.acos(x))
        minutes = 720 - 4 * (lon + (ha if rising else -ha)) - eqtime
    return minutes % 1440


def _hhmm(m: float | None) -> str | None:
    if m is None:
        return None
    m = round(m) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def sun_times(lat: float | None, lon: float | None, day: date | None = None, now: datetime | None = None) -> dict | None:
    """SR/SS (wschód/zachód, zenit 90°50') i początek/koniec zmierzchu cywilnego (zenit 96°), godziny UTC."""
    if lat is None or lon is None:
        return None
    now = now or datetime.now(timezone.utc)
    day = day or now.date()
    sr, ss = _event(day, lat, lon, 90.833, True), _event(day, lat, lon, 90.833, False)
    dawn, dusk = _event(day, lat, lon, 96.0, True), _event(day, lat, lon, 96.0, False)
    cur = now.hour * 60 + now.minute
    return {"sunrise": _hhmm(sr), "sunset": _hhmm(ss), "civil_dawn": _hhmm(dawn), "civil_dusk": _hhmm(dusk),
            "day": sr is not None and ss is not None and sr <= cur < ss}
