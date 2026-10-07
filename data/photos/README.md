# Zdjęcia typów samolotów

Jeden plik na kod ICAO typu, np. `B738.jpg` (obsługiwane też `.png`, `.webp`).
Obok może leżeć `B738.json` z opisem źródła (`credit`, `page`).

Brakujące zdjęcie aplikacja pobiera sama z Wikipedii przy pierwszym otwarciu typu w zakładce AIRCRAFT
i zapisuje tutaj, więc później działa bez internetu. Wszystkie naraz: `python scripts/fetch_aircraft_photos.py`.
Własne zdjęcie wystarczy wrzucić pod nazwą `<ICAO>.jpg`; ma pierwszeństwo przed pobieraniem.
