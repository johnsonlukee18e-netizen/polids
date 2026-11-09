# Zdjęcia typów samolotów

Jeden plik na kod ICAO typu, np. `B738.jpg` (obsługiwane też `.png`, `.webp`).
Obok może leżeć `B738.json` z opisem źródła (`credit`, `page`).

Brakujące zdjęcie aplikacja pobiera sama z Wikipedii przy pierwszym otwarciu typu w zakładce AIRCRAFT
i zapisuje tutaj, więc później działa bez internetu. Wszystkie naraz: `python scripts/fetch_aircraft_photos.py`.
Własne zdjęcie wystarczy wrzucić pod nazwą `<ICAO>.jpg`; ma pierwszeństwo przed pobieraniem.

Od 0.13.3 pobierane jest tylko zdjęcie z artykułu o tym modelu: dla A220 (BCS1, BCS3), CRJ i MD-80 tylko z artykułu
rodziny podanego w `TITLES` (`backend/app/services/photos.py`), dla pozostałych z pięciu wyników wyszukiwania,
w ich kolejności, artykuł z numerem z pierwszej nazwy ICAO w tytule albo w przekierowaniu na artykuł (np. Antonov
An-158 -> Antonov An-148) albo z nazwą typu i producenta w tytule (np. Airbus Beluga), a dopiero potem tytuł bez
liczb albo z numerem tylko z dalszej, wojskowej nazwy (np. C-99 przy ERJ-145); artykuł z innym numerem w tytule
jest odrzucany (lepiej bez zdjęcia niż z cudzym). Plik opisu dostaje `"v": 2`.

Zdjęcie pobrane wcześniej (opis bez `"v"`) z artykułu o innym modelu jest sprawdzane przy następnym otwarciu typu:
podmienione tylko na artykuł o tym modelu, a gdy go nie ma, zostaje i opis dostaje `"v": 2`; gdy Wikipedia nie
odpowiada, zostaje do następnego otwarcia. Zastąpione pliki trafiają do `replaced/`.
Własnych zdjęć program nie rusza: pliku bez opisu, z opisem bez adresu grafiki Wikipedii (`image`) ani pliku
wrzuconego później niż opis (np. własne `<ICAO>.jpg` w miejsce pobranego, ze starym `<ICAO>.json` obok; liczy się
też czas skopiowania, więc `docker cp` z zachowaną datą pliku działa).
