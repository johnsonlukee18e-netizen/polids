# Zdjęcia typów samolotów dodawane ręcznie

Zdjęcia z tego katalogu są pokazywane w zakładce AIRCRAFT zamiast zdjęć pobieranych automatycznie. Pod zdjęciem jest
zwykły podpis z autorem (`Photo: <autor>`), bez odnośnika.

## Pliki

- `<ICAO>.jpg`, `<ICAO>.jpeg`, `<ICAO>.png` albo `<ICAO>.webp`: jedno zdjęcie na kod ICAO typu, np. `B738.jpg` albo
  `A20N.webp`. Wielkość liter w nazwie nie ma znaczenia (`b738.JPG` też zadziała). Gdy typ ma tu kilka zdjęć, brane jest
  pierwsze w kolejności jpg, jpeg, png, webp.
- `<ICAO>.txt` (opcjonalny): autor zdjęcia w pierwszej linijce, np. `Imię Nazwisko` albo
  `Imię Nazwisko / Przykładowa Grupa Fotograficzna`. Zapisz go w UTF-8 (BOM nie przeszkadza). Liczy się tylko pierwsza
  niepusta linijka: nadmiarowe spacje są zwijane, początkowe `Photo:` usuwane (aplikacja dopisuje je sama), a podpis
  jest obcinany do 120 znaków. Bez tego pliku (albo z pustym plikiem) zdjęcie jest pokazywane bez podpisu.

Przykład:

```
data/photos-manual/B738.jpg
data/photos-manual/B738.txt    ->  Imię Nazwisko
```

## Jak to działa

- Zdjęcie z tego katalogu zawsze ma pierwszeństwo przed wszystkim w `data/photos/` (zdjęciami pobranymi z Wikipedii
  i starszymi własnymi). Aplikacja nie przenosi, nie podmienia ani nie usuwa plików z tego katalogu i nie pyta
  Wikipedii o typ, który ma tu zdjęcie. Pobranych wcześniej plików tego typu w `data/photos/` też nie rusza.
- Zdjęcie jest pokazywane w stałej ramce 3:2 (najwyżej 450 x 300 px), w całości, bez przycinania (pionowe i bardzo
  szerokie z czarnymi pasami). Najlepiej wygląda poziome zdjęcie o szerokości ok. 960 do 1280 px i rozmiarze poniżej
  500 KB; małe zdjęcia są powiększane i mogą być nieostre.
- Podpis zajmuje zawsze jedną linijkę pod ramką, więc dane typu obok zdjęcia nie przesuwają się po jego wczytaniu.
  W pełnej ramce (450 px) mieści się ok. 65 znaków autora, w węższym oknie mniej (w najwęższej ramce, 220 px, ok. 30).
  Dłuższy podpis jest skracany wielokropkiem (`…`), a w całości widać go w dymku po najechaniu na niego myszą.
  Najlepiej więc krótko: autor i ewentualnie licencja.
- Usuń zdjęcie (i jego `.txt`), żeby wrócić do zdjęcia pobieranego automatycznie.

## Dodawanie zdjęć na serwerze

Ten katalog jest częścią repozytorium i obrazu dockera (nie leży w wolumenie `data/photos`). Dodaj pliki do
repozytorium, np. na GitHubie przez „Add file” > „Upload files” do `data/photos-manual/`, i wdróż jak zwykle
(`sh deploy/update.sh`). Plik skopiowany do działającego kontenera przez `docker cp` zniknie przy następnej
przebudowie.

Upewnij się, że masz prawo do użycia każdego zdjęcia, i podaj jego autora tak, jak wymaga licencja.
