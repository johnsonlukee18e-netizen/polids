# Zdjęcia typów samolotów

Jeden plik na kod ICAO typu, np. `B738.jpg` (obsługiwane też `.png`, `.webp`).
Obok może leżeć `B738.json` z opisem źródła (`credit`, `page`).

Brakujące zdjęcie aplikacja pobiera sama z Wikipedii przy pierwszym otwarciu typu w zakładce AIRCRAFT
i zapisuje tutaj, więc później działa bez internetu. Wszystkie naraz: `python scripts/fetch_aircraft_photos.py`.
Własne zdjęcie wystarczy wrzucić pod nazwą `<ICAO>.jpg`; ma pierwszeństwo przed pobieraniem.

Od 0.13.3 pobierane jest tylko zdjęcie z artykułu o tym modelu: dla A220 (BCS1, BCS3), CRJ i MD-80 z artykułu
rodziny podanego w `TITLES` (`backend/app/services/photos.py`), dla pozostałych z pięciu wyników wyszukiwania
artykuł, którego tytuł (albo przekierowanie) zawiera numer modelu, a dopiero potem tytuł bez liczb; artykuł
z innym numerem w tytule jest odrzucany (lepiej bez zdjęcia niż z cudzym). Plik opisu dostaje `"v": 2`.
Zdjęcie pobrane wcześniej (opis bez `"v"`) z artykułu o innym modelu jest usuwane i pobierane od nowa przy
następnym otwarciu typu; własne zdjęcia (bez opisu albo z innym podpisem niż `Wikipedia: …`) zostają.
