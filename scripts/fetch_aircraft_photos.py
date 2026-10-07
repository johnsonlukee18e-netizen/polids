"""Pobiera z Wikipedii zdjęcia wszystkich typów samolotów do data/photos/ (jeden plik na kod ICAO).

Aplikacja robi to sama przy pierwszym otwarciu typu w zakładce AIRCRAFT; ten skrypt pobiera wszystko naraz,
np. żeby wrzucić zdjęcia do repozytorium. Istniejące pliki są pomijane.

    python scripts/fetch_aircraft_photos.py            # wszystkie typy
    python scripts/fetch_aircraft_photos.py B738 A320  # wybrane
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from backend.app.database import SessionLocal  # noqa: E402
from backend.app.importers.seed import init_db  # noqa: E402
from backend.app.models import AircraftType  # noqa: E402
from backend.app.services.photos import fetch_photo, local_photo  # noqa: E402


async def main(codes: list[str]):
    init_db()
    with SessionLocal() as db:
        types = {}
        for a in db.scalars(select(AircraftType).order_by(AircraftType.icao, AircraftType.id)):
            types.setdefault(a.icao, a)
    todo = [a for code, a in types.items() if (not codes or code in codes) and not local_photo(code)]
    print(f"Do pobrania: {len(todo)} typów")
    for i, a in enumerate(todo, 1):
        try:
            found = await fetch_photo(a.icao, f"{a.manufacturer or ''} {a.model}".strip())
            print(f"[{i}/{len(todo)}] {a.icao}: {found['credit'] if found else 'brak zdjęcia'}")
        except Exception as exc:  # noqa: BLE001 - jeden błąd nie przerywa reszty
            print(f"[{i}/{len(todo)}] {a.icao}: błąd {exc}")
        await asyncio.sleep(0.5)  # nie zasypujemy Wikipedii zapytaniami


if __name__ == "__main__":
    asyncio.run(main([c.upper() for c in sys.argv[1:]]))
