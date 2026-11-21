"""OTHER › FLIGHT PLAN (0.14.2, issue #35): ruch samolotu z dwóch kolejnych odczytów data feed do wierszy Mode S okna
EXTENDED LABEL (SDD 2014, Table 2-13): prędkość pionowa (IVV), kąt drogi (TRK) i prędkość zakrętu (TAR).

Sieć podaje tylko pozycję, wysokość, prędkość względem ziemi i kurs w chwili odczytu (co ok. 15 s, u nas co najwyżej
co 30 s z cache), więc ruch liczymy z różnicy dwóch odczytów pilota (czas z last_updated pilota):
- vv_fpm: zmiana wysokości w ft/min, zaokrąglona do 10 (wysokość z sieci jest geometryczna, więc to bliżej IVV niż BVV),
- track: kąt drogi z początku łuku koła wielkiego między pozycjami (1..360), tylko gdy samolot przesunął się co
  najmniej MIN_MOVE_NM (na postoju kąt drogi to szum),
- turn_rate: zmiana kursu (-180..180) na sekundę, zaokrąglona do 0,1.
Para odczytów liczy się tylko przy odstępie MIN_DT_S..MAX_DT_S; inaczej (pierwszy odczyt, długa przerwa) wartości to None.

Moduł nie importuje vatsim.py (vatsim.get_feed woła observe po każdym pobraniu, więc import w drugą stronę zrobiłby
krąg). Stan w pamięci: tylko znaki z ostatniego feedu (pilot, którego nie ma w feedzie, wypada). Nazw pilotów nie
trzymamy i nie logujemy."""

import logging
import math
import re
from datetime import datetime, timezone

log = logging.getLogger("polids.motion")

MIN_DT_S = 10
MAX_DT_S = 150
MIN_MOVE_NM = 0.3

# (czas odczytu [s od epoki], wysokość ft, szerokość, długość, kurs) dla każdego znaku: bieżący i poprzedni odczyt
Sample = tuple[float, float | None, float | None, float | None, float | None]
_cur: dict[str, Sample] = {}
_prev: dict[str, Sample] = {}
_stamp: str | None = None

# ułamek sekundy dłuższy niż 6 cyfr (sieć podaje 7) skracamy: fromisoformat w starszym Pythonie go nie przyjmie
_FRACTION = re.compile(r"(\.\d{6})\d+")


def _time(v) -> float | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(_FRACTION.sub(r"\1", v.strip()).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def observe(feed) -> None:
    """Zapamiętuje odczyt każdego pilota z feedu. Ten sam feed (ta sama update_timestamp) drugi raz nic nie zmienia,
    więc wolno wołać przy każdym pobraniu feedu. Błąd w danych nie przerywa pobrania (zostaje pusty ruch)."""
    global _stamp
    try:
        stamp = (feed.get("general") or {}).get("update_timestamp")
        if not stamp or stamp == _stamp:
            return
        _stamp = stamp
        seen = set()
        for p in feed.get("pilots") or []:
            if not isinstance(p, dict):
                continue
            cs = str(p.get("callsign") or "").strip().upper()
            t = _time(p.get("last_updated"))
            if not cs or t is None:
                continue
            seen.add(cs)
            old = _cur.get(cs)
            if old is not None and t <= old[0]:
                continue        # ten sam odczyt pilota (sieć go nie odświeżyła) albo starszy: bez zmian
            if old is not None:
                _prev[cs] = old
            _cur[cs] = (t, _num(p.get("altitude")), _num(p.get("latitude")), _num(p.get("longitude")),
                        _num(p.get("heading")))
        for cs in [cs for cs in _cur if cs not in seen]:
            del _cur[cs]
            _prev.pop(cs, None)
    except Exception as exc:  # noqa: BLE001 - nieoczekiwany kształt feedu nie może zepsuć pobrania
        log.warning("motion: %s", type(exc).__name__)


def _dist_nm(la1, lo1, la2, lo2) -> float:
    f1, f2 = math.radians(la1), math.radians(la2)
    h = math.sin((f2 - f1) / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(min(1.0, h)))


def _bearing(la1, lo1, la2, lo2) -> float:
    f1, f2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def motion(callsign: str) -> dict:
    """{"vv_fpm", "track", "turn_rate"} z dwóch ostatnich odczytów pilota; None, czego nie da się policzyć."""
    out = {"vv_fpm": None, "track": None, "turn_rate": None}
    cs = str(callsign or "").strip().upper()
    a, b = _prev.get(cs), _cur.get(cs)
    if a is None or b is None:
        return out
    dt = b[0] - a[0]
    if not MIN_DT_S <= dt <= MAX_DT_S:
        return out
    if a[1] is not None and b[1] is not None:
        out["vv_fpm"] = int(round((b[1] - a[1]) / dt * 60 / 10) * 10)
    if None not in (a[2], a[3], b[2], b[3]) and _dist_nm(a[2], a[3], b[2], b[3]) >= MIN_MOVE_NM:
        out["track"] = round(_bearing(a[2], a[3], b[2], b[3])) % 360 or 360
    if a[4] is not None and b[4] is not None:
        turn = (b[4] - a[4] + 180) % 360 - 180
        out["turn_rate"] = round(turn / dt, 1) + 0.0     # + 0.0: bez "-0.0"
    return out


def reset() -> None:
    """Testy: bez zapamiętanych odczytów."""
    global _stamp
    _cur.clear()
    _prev.clear()
    _stamp = None
