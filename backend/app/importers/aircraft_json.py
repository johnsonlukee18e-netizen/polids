"""AIRCRAFT: lista typów z pliku ICAO_Aircraft.json (format jak w vatiris: ICAO, Manufacturer, Model, Description,
WTC, WTG, RECAT-EU, Wingspan, Length, Height, MTOW, Use, IATA). Jeden rekord na oznaczenie typu ICAO i nic spoza pliku
(0.12.5, issue #18: bez wersji produkcyjnych, które tylko wydłużały listę).

Osiągi, których plik nie ma (silniki, MLW, pułap, Vmo, Mmo), dokładamy do tego samego rekordu z wersji typu
w data/seed/aircraft.csv (aircraft-database.com, scripts/build_aircraft_seed.py): gdy wersje się różnią, zakres od–do
(kolumny *_max). Wersje niezgodne z opisem ICAO typu (np. czterosilnikowy odrzutowiec pod kodem śmigłowca EC35)
pomijamy, tak samo jak wiersze oznaczeń zbiorczych bez opisu ICAO (GLID, ULAC…). Wymiary, MTOW i kategorie
turbulencji tylko z pliku json."""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import AircraftType
from .sct import read_text

SOURCE = "ICAO_Aircraft.json"
PERF_SOURCE = "aircraft-database.com"
RANGES = ("mlw", "ceiling_ft", "vmo_kt", "mmo")  # liczby z aircraft.csv: najmniejsza i największa z wersji typu
# granice wiarygodności tych liczb (runda 14, przegląd): aircraft-database.com ma pomyłki, np. 737-200C z Vmo 0
# i Mmo 350 (zamienione kolumny; w zakresie typu B732 dawało "M0.82–350"), C408 z Mmo 240 (Vmo w węzłach), B230
# z pułapem 120 ft, GA8 z MLW 114 kg. Wartość spoza granic pomijamy, zakres typu liczymy z pozostałych wersji.
BOUNDS = {"mlw": (50, 700000), "ceiling_ft": (1000, 80000), "vmo_kt": (40, 700), "mmo": (0.1, 1.0)}
MLW_MTOW = (0.3, 1.1)  # MLW wersji względem jej MTOW z tego samego wiersza (gdy jest)
# opis ICAO (Doc 8643, np. L2J): rodzaj statku, liczba silników, rodzaj silników; pasujące aircraft_type / engine_type
# z aircraft-database.com (znak spoza tabel, np. "-" w opisie "---": bez sprawdzania)
KINDS = {"L": {"airplane", "glider"}, "S": {"airplane", "amphibious"}, "A": {"airplane", "amphibious"},
         "G": {"autogyro"}, "H": {"helicopter"}, "T": {"tiltrotor"}}
ENGINES = {"J": {"turbofan", "turbojet"}, "T": {"turboprop", "turboshaft", "propfan"}, "P": {"piston"},
           "E": {"electric"}, "R": {"rocket"}}


def _f(v) -> float | None:
    """Liczba dodatnia albo None (MTOW 0 w pliku json = brak danych)."""
    try:
        n = float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return n if n is not None and n > 0 else None


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def parse_icao_aircraft(text: str) -> dict[str, dict]:
    """Rekordy pliku wg oznaczenia typu (powtórzone oznaczenie: ostatni wpis), pola jak w AircraftType."""
    out = {}
    for row in json.loads(text):
        icao = _s(row.get("ICAO")).upper()
        if not re.fullmatch(r"[A-Z0-9]{1,4}", icao):
            continue
        desc = _s(row.get("Description")).upper()
        out[icao] = {
            "icao": icao,
            "iata": _s(row.get("IATA")).upper()[:3] or None,
            "manufacturer": _s(row.get("Manufacturer")).upper() or None,
            "model": _s(row.get("Model")) or icao,
            "description": desc if re.fullmatch(r"[A-Z][0-9A-Z][A-Z]", desc) else None,
            "wtc": _s(row.get("WTC")).upper()[:1] or None,
            "wtg": _s(row.get("WTG")).upper()[:1] or None,
            "recat": _s(row.get("RECAT-EU")).upper()[:1] or None,
            "wingspan": _f(row.get("Wingspan")),
            "length": _f(row.get("Length")),
            "height": _f(row.get("Height")),
            "mtow": _f(row.get("MTOW")),
            "use": _s(row.get("Use")).upper()[:2] or None,
        }
    return out


def plausible(field: str, value: float, row: dict | None = None) -> bool:
    """Liczba z aircraft.csv w granicach BOUNDS (MLW także względem MTOW wiersza)."""
    lo, hi = BOUNDS[field]
    if not lo <= value <= hi:
        return False
    mtow = _f((row or {}).get("mtow")) if field == "mlw" else None
    return not mtow or MLW_MTOW[0] * mtow <= value <= MLW_MTOW[1] * mtow


def _fits(desc: str | None, row: dict) -> bool:
    """Wersja z aircraft.csv pasuje do opisu ICAO typu (rodzaj statku i silników). Typ bez opisu to oznaczenie zbiorcze
    różnych statków (GLID, ULAC, BALL, ZZZZ…), więc bez osiągów z wersji."""
    if not desc:
        return False
    kind, engine = KINDS.get(desc[0]), ENGINES.get(desc[2])
    ac, eng = _s(row.get("aircraft_type")).lower(), _s(row.get("engine_type")).lower()
    return (kind is None or not ac or ac in kind) and (engine is None or not eng or eng in engine)


def performance(rows: list[dict], descriptions: dict[str, str | None]) -> dict[str, dict]:
    """Osiągi typów z pliku json z wierszy aircraft.csv (wersje produkcyjne, kilka na typ): liczby jako najmniejsza
    wartość i *_max (tylko gdy wersje się różnią; wartości niewiarygodne, poza BOUNDS, pomijamy), rodzaje silników od
    najczęstszego ("turbojet/turbofan"), liczba silników, gdy wszystkie wersje mają tę samą. Wiersze typów spoza pliku
    json pomijamy."""
    by = defaultdict(list)
    for r in rows:
        icao = _s(r.get("icao")).upper()
        if icao in descriptions and _fits(descriptions[icao], r):
            by[icao].append(r)
    out = {}
    for icao, variants in by.items():
        p = {}
        for k in RANGES:
            vals = [v for r in variants for v in (_f(r.get(k)), _f(r.get(f"{k}_max"))) if v is not None and plausible(k, v, r)]
            if vals:
                p[k] = min(vals)
                if max(vals) != p[k]:
                    p[f"{k}_max"] = max(vals)
        kinds = Counter(e for r in variants if (e := _s(r.get("engine_type")).lower()) not in ("", "none"))
        if kinds:
            p["engine_type"] = "/".join(k for k, _ in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])))
        counts = {_s(r.get("engine_count")) for r in variants} - {""}
        if len(counts) == 1 and (n := counts.pop()).isdigit():
            p["engine_count"] = int(n)
        if p:
            out[icao] = p
    return out


def build_aircraft(db: Session, json_paths: list[Path], perf_rows: list[dict]) -> dict:
    """Lista AIRCRAFT od nowa: typy z plików json (kolejne pliki nadpisują wcześniejsze), osiągi z perf_rows
    (wiersze aircraft.csv). Pusty plik nie kasuje listy (wyjątek, poprzednia lista zostaje po rollback)."""
    types: dict[str, dict] = {}
    for p in json_paths:
        types.update(parse_icao_aircraft(read_text(p)))
    if not types:
        raise ValueError(f"{', '.join(p.name for p in json_paths)}: no aircraft types in the file")
    perf = performance(perf_rows, {icao: t["description"] for icao, t in types.items()})
    db.execute(delete(AircraftType))
    # wczytane wcześniej rekordy (te same id po przebudowie) nie mogą zostać w sesji obok nowych
    for obj in [o for o in db.identity_map.values() if isinstance(o, AircraftType)]:
        db.expunge(obj)
    for icao, t in sorted(types.items()):
        p = dict(perf.get(icao, {}))
        desc = t["description"]
        # liczba silników z opisu ICAO (L2J: 2); bez cyfry (np. LCT, silniki sprzężone) z aircraft.csv
        count = int(desc[1]) if desc and desc[1].isdigit() else p.get("engine_count")
        p.pop("engine_count", None)
        db.add(AircraftType(**t, **p, engine_count=count, source=f"{SOURCE}, {PERF_SOURCE}" if p else SOURCE))
    db.flush()
    return {"aircraft_types": len(types), "with_performance": len(perf)}
