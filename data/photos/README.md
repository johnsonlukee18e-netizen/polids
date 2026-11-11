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
jest odrzucany (lepiej bez zdjęcia niż z cudzym). Plik opisu dostaje `"v"` (od 0.13.4: 3). Miniatury mają
szerokość 960 px, jedną ze standardowych szerokości Wikimedia.

Zdjęcie pobrane wcześniej (opis bez `"v"` albo z `"v"` mniejszym niż 3) z artykułu o innym modelu jest sprawdzane
przy następnym otwarciu typu i podmieniane tylko na artykuł o tym modelu. Od 0.13.4 takie zdjęcie nie jest
pokazywane, gdy nie da się go podmienić: bez artykułu o tym modelu obraz i opis idą do `replaced/`, a w miejscu opisu
zostaje `<ICAO>.json` ze znacznikiem `"only_exact": true` (typ bez zdjęcia; kolejne pobranie, np. po restarcie, też
tylko z artykułu o tym modelu; usunięcie tego pliku przywraca zwykłe pobieranie). Gdy Wikipedia nie odpowiada, typ
chwilowo pokazuje „Photo unavailable”, a zdjęcie jest sprawdzane przy następnym otwarciu. Zastąpione pliki trafiają do
`replaced/` (plik o tej samej nazwie już tam leżący zostaje, nowy dostaje w nazwie czas przeniesienia). Każda podmiana
i ukrycie trafia do logu serwera (`docker compose logs app | grep polids.photos`).
Pobrane zdjęcie program rozpoznaje po adresie grafiki (`image`) z dowolnego serwera Wikimedia (`upload.wikimedia.org`,
`thumb.wikimedia.org`). Własnych zdjęć program nie rusza: pliku bez opisu, z opisem bez adresu grafiki Wikimedia ani
pliku wrzuconego później niż opis (np. własne `<ICAO>.jpg` w miejsce pobranego, ze starym `<ICAO>.json` obok; liczy
się też czas skopiowania, więc `docker cp` z zachowaną datą pliku działa). Zdjęcie z podpisem artykułu o innym
modelu uznane za własne trafia raz do logu z przyczyną.
