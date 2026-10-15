"""Słońce: wschód i zachód, zmierzch cywilny i położenie (algorytm NOAA ze wzorów Meeusa, dokładność ok. 1 min), UTC.

Zdarzenia liczone są dla doby słonecznej lotniska (od lokalnej północy do północy): daleko od Greenwich wschód albo
zachód wypada wtedy innego dnia UTC (Japonia: wschód poprzedniego dnia UTC, zachodnie wybrzeże USA: zachód
następnego), dlatego obok godzin "HH:MM" są pełne daty i godziny UTC (ISO)."""

import math
from datetime import date, datetime, timedelta, timezone

from .runways import eu_summer_time

SR_ZENITH = 90.833   # wschód / zachód: górny brzeg tarczy na horyzoncie, z refrakcją (90°50')
CIVIL_ZENITH = 96.0  # zmierzch cywilny: środek tarczy 6° pod horyzontem
EVENTS = (("sunrise", SR_ZENITH, True), ("sunset", SR_ZENITH, False),
          ("civil_dawn", CIVIL_ZENITH, True), ("civil_dusk", CIVIL_ZENITH, False))


def _utc(t: datetime) -> datetime:
    return t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)


def solar_position(t: datetime) -> tuple[float, float]:
    """(deklinacja słońca w stopniach, równanie czasu w minutach) w chwili t (UTC)."""
    jd = _utc(t).timestamp() / 86400 + 2440587.5
    c = (jd - 2451545.0) / 36525   # stulecia juliańskie od J2000.0
    l0 = (280.46646 + c * (36000.76983 + c * 0.0003032)) % 360          # średnia długość ekliptyczna
    m = math.radians(357.52911 + c * (35999.05029 - 0.0001537 * c))     # anomalia średnia
    e = 0.016708634 - c * (0.000042037 + 0.0000001267 * c)              # mimośród orbity Ziemi
    center = (math.sin(m) * (1.914602 - c * (0.004817 + 0.000014 * c)) + math.sin(2 * m) * (0.019993 - 0.000101 * c)
              + math.sin(3 * m) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * c)
    app = math.radians(l0 + center - 0.00569 - 0.00478 * math.sin(omega))   # długość pozorna
    eps = math.radians(23 + (26 + (21.448 - c * (46.815 + c * (0.00059 - c * 0.001813))) / 60) / 60
                       + 0.00256 * math.cos(omega))                          # nachylenie ekliptyki
    decl = math.degrees(math.asin(math.sin(eps) * math.sin(app)))
    y, l0r = math.tan(eps / 2) ** 2, math.radians(l0)
    eqt = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(m) + 4 * e * y * math.sin(m) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * m))
    return decl, eqt


def subsolar_point(t: datetime) -> tuple[float, float]:
    """Punkt podsłoneczny (słońce w zenicie) w chwili t: (szerokość, długość) w stopniach, długość -180..180."""
    t = _utc(t)
    decl, eqt = solar_position(t)
    minutes = t.hour * 60 + t.minute + t.second / 60 + t.microsecond / 6e7
    return decl, ((720 - minutes - eqt) / 4 + 180) % 360 - 180


def elevation(lat: float, lon: float, t: datetime) -> float:
    """Wysokość środka tarczy nad horyzontem w stopniach (bez refrakcji)."""
    slat, slon = subsolar_point(t)
    la, sa = math.radians(lat), math.radians(slat)
    cosz = math.sin(la) * math.sin(sa) + math.cos(la) * math.cos(sa) * math.cos(math.radians(lon - slon))
    return 90 - math.degrees(math.acos(max(-1.0, min(1.0, cosz))))


def _hour_angle(lat: float, decl: float, zenith: float) -> float | str:
    """Kąt godzinny zdarzenia w stopniach albo "day" / "night", gdy słońce całą dobę jest ponad / pod tym kątem."""
    la, d = math.radians(max(-89.99, min(89.99, lat))), math.radians(decl)
    x = math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(d)) - math.tan(la) * math.tan(d)
    if x > 1:
        return "night"
    if x < -1:
        return "day"
    return math.degrees(math.acos(x))


def _iso(t: datetime | None) -> str | None:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _hhmm(t: datetime | None) -> str | None:
    if t is None:
        return None
    t = (t + timedelta(seconds=30)).replace(second=0, microsecond=0)
    return t.strftime("%H:%M")


def sun_day(lat: float, lon: float, day: date) -> dict:
    """Zdarzenia doby słonecznej lotniska z datą day (lokalnie od północy do północy): {nazwa: datetime UTC albo None},
    "polar": "day" / "night" (słońce całą dobę nad / pod horyzontem), "civil_polar" to samo dla zmierzchu cywilnego,
    "noon": górowanie (UTC)."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    at = lambda minutes: midnight + timedelta(minutes=minutes)  # noqa: E731
    noon = 720 - 4 * lon
    for _ in range(2):   # górowanie: południe średnie poprawione o równanie czasu w chwili górowania
        noon = 720 - 4 * lon - solar_position(at(noon))[1]
    decl_noon = solar_position(at(noon))[0]
    out: dict = {"noon": at(noon), "polar": None, "civil_polar": None}
    for name, zenith, rising in EVENTS:
        ha = _hour_angle(lat, decl_noon, zenith)
        if isinstance(ha, str):
            out[name] = None
            out["polar" if zenith == SR_ZENITH else "civil_polar"] = ha
            continue
        minutes = noon + (-4 if rising else 4) * ha
        for _ in range(3):   # deklinacja i równanie czasu w chwili samego zdarzenia
            decl, eqt = solar_position(at(minutes))
            ha = _hour_angle(lat, decl, zenith)
            if isinstance(ha, str):
                break
            minutes = 720 - 4 * lon - eqt + (-4 if rising else 4) * ha
        out[name] = at(minutes) if not isinstance(ha, str) else None
    return out


def state(lat: float, lon: float, t: datetime) -> str:
    """"day" (słońce nad horyzontem), "civil" (zmierzch cywilny) albo "night"."""
    el = elevation(lat, lon, t)
    return "day" if el > 90 - SR_ZENITH else "civil" if el > 90 - CIVIL_ZENITH else "night"


def sun_times(lat: float | None, lon: float | None, day: date | None = None, now: datetime | None = None) -> dict | None:
    """SR/SS (wschód/zachód, zenit 90°50') i początek/koniec zmierzchu cywilnego (zenit 96°) doby lotniska, UTC:
    "HH:MM" pod dotychczasowymi kluczami (AERODROME › PRZEGLĄD) i pełne daty ISO pod kluczami z "_at";
    "day" = słońce teraz nad horyzontem (z wysokości słońca, więc dobrze także wtedy, gdy zachód wypada w UTC
    przed wschodem: obie Ameryki, Azja, Pacyfik)."""
    if lat is None or lon is None:
        return None
    now = _utc(now or datetime.now(timezone.utc))
    ev = sun_day(lat, lon, day or now.date())
    out = {name: _hhmm(ev[name]) for name, _, _ in EVENTS}
    out.update({f"{name}_at": _iso(ev[name]) for name, _, _ in EVENTS})
    out.update({"polar": ev["polar"], "civil_polar": ev["civil_polar"], "day": state(lat, lon, now) == "day"})
    return out


def polish_time(t: datetime) -> dict:
    """Czas polski chwili t: {"hm": "07:01", "tz": "CEST"} (CET zimą, CEST latem, zmiana jak w całej UE)."""
    summer = eu_summer_time(t)
    return {"hm": _hhmm(t + timedelta(hours=2 if summer else 1)), "tz": "CEST" if summer else "CET"}


def report(lat: float, lon: float, now: datetime | None = None, polish: bool = False) -> dict:
    """METEO › SUN: słońce teraz (wysokość, dzień / zmierzch cywilny / noc), zdarzenia dziś i jutro (daty UTC, doba
    słoneczna miejsca, czasy ISO) i najbliższe zdarzenie; polish=True: także czas polski (lotniska EP)."""
    now = _utc(now or datetime.now(timezone.utc))
    names = [name for name, _, _ in EVENTS]
    evs = {k: sun_day(lat, lon, now.date() + timedelta(days=k)) for k in (-1, 0, 1, 2)}
    days = []
    for k in (0, 1):
        ev = evs[k]
        sr, ss = ev["sunrise"], ev["sunset"]
        length = (round((ss - sr).total_seconds() / 60) if sr and ss
                  else {"day": 1440, "night": 0}.get(ev["polar"]))
        day = {"date": (now.date() + timedelta(days=k)).isoformat(), "noon": _iso(ev["noon"]), "polar": ev["polar"],
               "civil_polar": ev["civil_polar"], "day_length": length, **{n: _iso(ev[n]) for n in names}}
        if polish:
            day["local"] = {n: polish_time(ev[n]) if ev[n] else None for n in [*names, "noon"]}
        days.append(day)
    upcoming = sorted((ev[n], n) for ev in evs.values() for n in names if ev[n] and ev[n] > now)
    nxt = None
    if upcoming:
        t, n = upcoming[0]
        nxt = {"event": n, "at": _iso(t), "local": polish_time(t) if polish else None}
    return {"now": _iso(now), "elevation": round(elevation(lat, lon, now), 1), "state": state(lat, lon, now),
            "subsolar": [round(v, 2) for v in subsolar_point(now)], "days": days, "next": nxt}
