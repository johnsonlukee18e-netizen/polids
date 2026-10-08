"""ECFMP (European Cross-Border Flow Management Position, https://ecfmp.vatsim.net) – restrykcje przepływu (flow measures).

Czytamy publiczne API bez klucza:
- GET /api/v1/flow-measure – restrykcje; domyślnie te, które zaczynają się w ciągu 24 h i skończyły się
  nie dawniej niż 24 h temu (parametry `active` i `notified` dodatkowo zawężają listę, więc ich nie używamy:
  stan liczymy sami z godzin, żeby pokazać też restrykcje zgłoszone na później),
- GET /api/v1/flight-information-region – numery FIR-ów (notified_flight_information_regions to numery, nie ICAO);
  FIR Warszawa ma identyfikator EPWW.

Zapas: vIFF (/etfms/ecfmp) podaje te same restrykcje przepisane po swojemu (notified_firs od razu jako kody ICAO,
odstęp między startami w minutach). Używamy go, gdy ECFMP nie odpowiada.

Nazwy pól pochodzą z odpowiedzi API i z kodu ECFMP (app/Enums/FlowMeasureType.php, FilterType.php)."""

import json
import re
from datetime import datetime, timedelta, timezone

from .http_cache import UpstreamError, fetch_text

API = "https://ecfmp.vatsim.net/api/v1"
FIR_EPWW = "EPWW"
CACHE_SECONDS = 120
FIR_CACHE_SECONDS = 86400

# rodzaje restrykcji (FlowMeasureType w ECFMP) po polsku
TYPE_PL = {
    "minimum_departure_interval": "minimalny odstęp między startami",
    "average_departure_interval": "średni odstęp między startami",
    "per_hour": "liczba lotów na godzinę",
    "miles_in_trail": "odstęp w milach (MIT)",
    "max_ias": "maksymalna prędkość IAS",
    "max_mach": "maksymalna liczba Macha",
    "ias_reduction": "redukcja prędkości IAS",
    "mach_reduction": "redukcja liczby Macha",
    "prohibit": "zakaz lotów",
    "mandatory_route": "trasa obowiązkowa",
    "ground_stop": "wstrzymanie startów (ground stop)",
}
# rodzaje warunków (FilterType w ECFMP) po polsku
FILTER_PL = {
    "ADEP": "odlot z", "ADES": "przylot do", "waypoint": "przez punkt",
    "level_above": "powyżej poziomu", "level_below": "poniżej poziomu", "level": "poziom",
    "member_event": "uczestnicy eventu", "member_not_event": "poza eventem",
    "range_to_destination": "odległość do lotniska docelowego",
}
_SECONDS_TYPES = ("minimum_departure_interval", "average_departure_interval")


def value_text(kind: str, value) -> str:
    """Wartość restrykcji z jednostką: odstępy między startami ECFMP podaje w sekundach, resztę w swoich jednostkach."""
    if value is None:
        return ""
    if kind in _SECONDS_TYPES and isinstance(value, (int, float)):
        return f"co {value / 60:g} min" if value >= 60 else f"co {value:g} s"
    if kind == "per_hour":
        return f"{value}/h"
    if kind in ("miles_in_trail", "range_to_destination"):
        return f"{value} NM"
    if kind in ("max_ias", "ias_reduction"):
        return f"{value} kt"
    if kind in ("max_mach", "mach_reduction"):
        return f"M{value}"
    return str(value)


def _dt(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _state(start: datetime | None, end: datetime | None, now: datetime) -> str:
    """"active" – obowiązuje teraz, "notified" – zgłoszona na później, "finished" – już się skończyła."""
    if end and end < now:
        return "finished"
    if start and start > now:
        return "notified"
    return "active"


def _levels(filters: list[dict]) -> list[str]:
    out = []
    for f in filters:
        kind = f.get("type")
        if kind in ("level", "level_above", "level_below"):
            out.append(f"{FILTER_PL[kind]} {f.get('value')}")
    return out


def measure(raw: dict, firs: dict[int, str], now: datetime) -> dict:
    """Restrykcja z ECFMP w postaci dla panelu OVERVIEW."""
    m = raw.get("measure") or {}
    kind = m.get("type") or ""
    filters = [f for f in (raw.get("filters") or []) if isinstance(f, dict)]
    pick = lambda t: [str(v) for f in filters if f.get("type") == t for v in (f.get("value") or [])]  # noqa: E731
    start, end = _dt(raw.get("starttime")), _dt(raw.get("endtime"))
    return {
        "ident": raw.get("ident") or "", "reason": raw.get("reason") or "",
        "type": kind, "type_label": TYPE_PL.get(kind, kind), "value": m.get("value"),
        "value_text": value_text(kind, m.get("value")),
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "adep": pick("ADEP"), "ades": pick("ADES"), "waypoints": pick("waypoint"), "levels": _levels(filters),
        "firs": sorted({firs.get(i, str(i)) for i in raw.get("notified_flight_information_regions") or []}),
        "state": _state(start, end, now), "withdrawn": bool(raw.get("withdrawn_at")), "source": "ECFMP",
    }


def viff_measure(raw: dict, now: datetime) -> dict:
    """Ta sama restrykcja z vIFF (/etfms/ecfmp): godziny jako "1730/2030" i data "07/10", odstępy w minutach."""
    kind = raw.get("type") or ""
    value = raw.get("value")
    times = re.fullmatch(r"(\d{4})/(\d{4})", str(raw.get("valid_time") or "") or "")
    day = re.fullmatch(r"(\d{2})/(\d{2})", str(raw.get("valid_date") or "") or "")
    start = end = None
    if times and day:
        base = datetime(now.year, int(day.group(2)), int(day.group(1)), tzinfo=timezone.utc)
        start = base + timedelta(hours=int(times.group(1)[:2]), minutes=int(times.group(1)[2:]))
        end = base + timedelta(hours=int(times.group(2)[:2]), minutes=int(times.group(2)[2:]))
        if end < start:            # przejście przez północ
            end += timedelta(days=1)
    seconds = value * 60 if kind in _SECONDS_TYPES and isinstance(value, (int, float)) else value
    levels = [f"{r.get('type', '')} {r.get('value', '')}".strip() for r in raw.get("levelRestrictions") or []
              if isinstance(r, dict)]
    return {
        "ident": raw.get("ident") or "", "reason": raw.get("reason") or "",
        "type": kind, "type_label": TYPE_PL.get(kind, kind), "value": seconds,
        "value_text": value_text(kind, seconds),
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "adep": [str(x) for x in raw.get("ADEP") or []], "ades": [str(x) for x in raw.get("ADES") or []],
        "waypoints": [str(x) for x in raw.get("waypoints") or []], "levels": levels,
        "firs": sorted({str(x) for x in raw.get("notified_firs") or []}),
        "state": _state(start, end, now), "withdrawn": False, "source": "vIFF",
    }


def relevant(m: dict, airports: set[str]) -> bool:
    """Restrykcja dotyczy nas: zgłoszona do FIR EPWW, albo w warunkach jest polskie lotnisko, albo własny znak EPWW."""
    if FIR_EPWW in m["firs"] or m["ident"].upper().startswith(FIR_EPWW):
        return True
    return any(a.upper() in airports or a.upper().startswith("EP") for a in (*m["adep"], *m["ades"]))


async def firs() -> dict[int, str]:
    """Numer FIR-u ECFMP → kod ICAO (lista zmienia się bardzo rzadko, trzymamy ją dobę)."""
    text = await fetch_text(f"{API}/flight-information-region", FIR_CACHE_SECONDS)
    data = json.loads(text or "[]")
    return {f["id"]: f.get("identifier") or str(f["id"]) for f in data if isinstance(f, dict) and "id" in f}


async def measures(airports=(), now: datetime | None = None) -> dict:
    """Restrykcje ECFMP dotyczące FIR EPWW (albo polskich lotnisk), obowiązujące i zgłoszone na później.

    Przy błędzie ECFMP próbujemy jeszcze vIFF; gdy i to nie wyjdzie, zwracamy pustą listę z komunikatem."""
    now = now or datetime.now(timezone.utc)
    ads = {a.upper() for a in airports}
    try:
        text = await fetch_text(f"{API}/flow-measure", CACHE_SECONDS)
        raw = json.loads(text or "[]")
        fir_ids = {}
        try:
            fir_ids = await firs()
        except (UpstreamError, ValueError, KeyError):
            pass    # bez listy FIR-ów pokażemy numery zamiast kodów ICAO
        items = [measure(m, fir_ids, now) for m in raw if isinstance(m, dict)]
        return _result(items, ads, "ECFMP", None)
    except (UpstreamError, ValueError, KeyError, TypeError, AttributeError) as exc:   # Attribute: np. "measure" nie jako obiekt
        ecfmp_error = f"ECFMP niedostępny: {exc}"
    from . import viff as viff_service  # import tutaj, żeby nie robić zależności na starcie
    try:
        data = await viff_service._get("/etfms/ecfmp", ttl=CACHE_SECONDS)
        items = [viff_measure(m, now) for m in (data if isinstance(data, list) else []) if isinstance(m, dict)]
        return _result(items, ads, "vIFF", f"{ecfmp_error} – dane z vIFF (/etfms/ecfmp)")
    except Exception as exc:  # noqa: BLE001 - zapas: każdy błąd vIFF kończy się komunikatem w panelu
        return {"measures": [], "source": None, "error": f"{ecfmp_error}; zapas vIFF też nie odpowiedział: {exc}"}


def _result(items: list[dict], airports: set[str], source: str, note: str | None) -> dict:
    mine = [m for m in items if m["state"] != "finished" and not m["withdrawn"] and relevant(m, airports)]
    mine.sort(key=lambda m: (m["state"] != "active", m["start"] or "", m["ident"]))
    return {"measures": mine, "source": source, "error": note, "all": len(items)}
