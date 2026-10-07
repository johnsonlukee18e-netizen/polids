"""Pobiera dane lotnisk, pasów, pomocy nawigacyjnych i częstotliwości dla Polski z OurAirports
(domena publiczna, https://ourairports.com/data/) i zapisuje je do data/seed/.

Użycie:
    python scripts/fetch_ourairports.py [PREFIKS_ICAO=EP] [KRAJ_ISO=PL]
"""

import csv
import io
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/"
SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


def get(name):
    with urllib.request.urlopen(BASE + name, timeout=60) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))


def write(name, rows, fields):
    with open(SEED / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)}")


def main(prefix="EP", country="PL"):
    airports = [
        a for a in get("airports.csv")
        if a["iso_country"] == country and a["ident"].startswith(prefix) and len(a["ident"]) == 4
        and a["type"] not in ("closed", "heliport")
    ]
    idents = {a["ident"] for a in airports}
    write("airports.csv", airports,
          ["ident", "type", "name", "latitude_deg", "longitude_deg", "elevation_ft", "municipality", "iata_code"])
    runways = [r for r in get("runways.csv") if r["airport_ident"] in idents and r["closed"] != "1"]
    write("runways.csv", runways,
          ["airport_ident", "length_ft", "width_ft", "surface", "lighted", "le_ident", "le_latitude_deg",
           "le_longitude_deg", "le_elevation_ft", "le_heading_degT", "he_ident", "he_latitude_deg",
           "he_longitude_deg", "he_elevation_ft", "he_heading_degT"])
    navaids = [n for n in get("navaids.csv") if n["iso_country"] == country]
    write("navaids.csv", navaids,
          ["ident", "name", "type", "frequency_khz", "latitude_deg", "longitude_deg", "elevation_ft",
           "magnetic_variation_deg"])
    freqs = [f for f in get("airport-frequencies.csv") if f["airport_ident"] in idents]
    write("frequencies.csv", freqs, ["airport_ident", "type", "description", "frequency_mhz"])


if __name__ == "__main__":
    main(*sys.argv[1:])
