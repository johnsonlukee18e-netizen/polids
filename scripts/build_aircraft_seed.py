"""Buduje data/seed/aircraft.csv z bazy aircraft-database.com (licencja ODC-By).

Źródło danych: https://aircraft-database.com (kopia w repozytorium vatger/atciss,
katalog contrib/ac-data/aircraft-db). Kategorie WTC / RECAT-EU liczone tak jak w atciss
(MIT), z nadpisaniami z pliku data/seed/wtc_overrides.csv.

Użycie:
    python scripts/build_aircraft_seed.py ŚCIEŻKA/DO/aircraft-db
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"

PROPS = {
    "wingspan": "1ec96f97-2526-643a-9933-d748a416ba2f",
    "length": "1ec85ab4-c080-6d48-b99a-377e0c86c3f3",
    "height": "1ec85ab3-da18-6a9a-b99a-331ba92f259f",
    "mtow": "1ec96f93-22b5-66f0-9933-45bd403e4df0",
    "mlw": "1ec96f94-5471-66de-9933-a93eae676780",
    "ceiling": "1ec989bb-f1f3-68c6-9933-d379390912fd",
    "vmo": "1ec96fa2-ebe3-6f04-9933-fd26352c594f",
    "mmo": "1ec96fa3-9b42-6be4-9933-8d57c1daa4aa",
}

FIELDS = [
    "icao", "iata", "manufacturer", "model", "aircraft_type", "engine_type", "engine_count",
    "wtc", "recat", "wingspan", "length", "height", "mtow", "mlw", "ceiling_ft", "vmo_kt", "mmo",
]


def num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def wtc_from_mtow(mtow):
    if mtow is None:
        return None
    if mtow <= 7000:
        return "L"
    if mtow < 136000:
        return "M"
    return "H"


def recat_from_dims(span, mtow):
    if mtow is None or span is None:
        return None
    if mtow < 15000:
        return "F"
    if mtow < 100000:
        return "E" if span < 32 else "D"
    if span < 52:
        return "C"
    if span < 60:
        return None
    if span < 72:
        return "B"
    return "A"


def main(src: Path):
    overrides = {}
    with open(SEED / "wtc_overrides.csv", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and not row[0].startswith("#"):
                overrides[row[0].strip()] = (row[1].strip(), row[2].strip())

    mfs = {m["id"]: m["name"] for m in json.loads((src / "manufacturers.json").read_text("utf-8"))}
    types = json.loads((src / "aircraft-types.json").read_text("utf-8"))

    rows = []
    for t in types:
        icao = t.get("icaoCode")
        if not icao:
            continue
        props = {p["property"]: p["value"] for p in t.get("propertyValues", [])}
        r = {
            "icao": icao,
            "iata": t.get("iataCode") or "",
            "manufacturer": mfs.get(t.get("manufacturer"), ""),
            "model": t.get("name") or "",
            "aircraft_type": t.get("aircraftFamily") or "",
            "engine_type": t.get("engineFamily") or "",
            "engine_count": t.get("engineCount") or "",
        }
        for k, pid in PROPS.items():
            v = num(props.get(pid))
            r[k] = v
        r["ceiling_ft"] = r.pop("ceiling")
        r["vmo_kt"] = r.pop("vmo")
        if icao in overrides:
            r["wtc"], r["recat"] = overrides[icao]
        else:
            r["wtc"] = wtc_from_mtow(r["mtow"])
            r["recat"] = recat_from_dims(r["wingspan"], r["mtow"])
        rows.append(r)

    rows.sort(key=lambda r: (r["icao"], r["manufacturer"], r["model"]))
    out = SEED / "aircraft.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: fmt(r.get(k)) for k in FIELDS})
    print(f"Zapisano {len(rows)} typów do {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
