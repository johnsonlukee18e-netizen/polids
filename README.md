# PolIDS

![PolIDS](frontend/icons/polids-logo.svg)

Polish Integrated Display System dla kontrolerów VATSIM PL vACC. Układ wzorowany na PANDORZE (PAŻP), zawartość zakładek
w stylu EUROCONTROL NM UI. Cały interfejs jest po angielsku i ma ostre krawędzie (od 0.12.5). Od 0.12.6 interfejs pokazuje same dane, bez
dopisków, skąd pochodzą i jak je wyliczono (źródła są wymienione niżej w tym pliku), a komunikaty o błędach są krótkie;
pełna przyczyna błędu trafia do logu serwera. Od 0.13.0 cały program ma czcionkę bezszeryfową (Arial / Liberation Sans)
bez pogrubień, a nad treścią jest wąski pasek na całą szerokość: Reload (przeładowuje stronę i wraca do tego samego
ekranu; F5 otwiera HOME), Brighter i Darker (jasność całego ekranu w krokach po 12 %, od −2 do +2, zapamiętana w przeglądarce).
Od 0.13.1 każdy przycisk lewego menu i każdego podmenu ma 137 x 28 px z marginesem 1,5 px z każdej strony (rząd co 31 px),
pierwszy i każdy następny przycisk podmenu stoi na wysokości przycisku menu obok (odstęp w podmenu to jeden pusty rząd),
a w niskim oknie przyciski obu kolumn zmniejszają się po równo (najmniej 16 px), więc całe menu mieści się bez
przewijania; logo jest na dole menu, pod zegarem z AIRAC i nad danymi zalogowanego użytkownika.
Backend FastAPI + SQLite,
frontend w czystym JS, całość w Dockerze.

| Zakładka | Co jest |
|---|---|
| RADIO | jedna strona w starym układzie z 0.12.6 (trzy kolumny), tylko podział okienek sąsiadów wg szkicu (`data/seed/radio_layout.json`): u góry jeden rząd – małe wskaźniki konfiguracji ACC GAT (litery sektorów ACC online, ALL i ALH w całości, np. ALL+S), APP GD, APP WA (HL = samo EPWA APP, H+L = z N APP, 2H+L = jeszcze z S APP, +D = dyrektor F APP), APP KK i APP PO (liczba aktywnych częstotliwości APP; uczeń i instruktor na jednej częstotliwości liczą się raz), a na prawo od nich ATIS-y polskich lotnisk (przycisk ATIS chowa tylko ich treść, nic się nie przesuwa; gdy się nie mieszczą, ostatnie lotniska zbiera „+N” z listą w dymku); po lewej duży podgląd LOW (przekrój suwakiem wysokości) ze stosami sąsiadów z zachodu (EDWW, pod nim BERLIN: WEST albo EAST z pasa w ATIS EDDB, a bez pasa w ATIS konfiguracja preferowana przy wietrze z METAR, na czerwono; EDUU, EDMM), z północy (ESAA) i z południa (LKAA); w środku przyciski ATIS / LOW MID HIGH / APP / TWR / TWR/A / FIS, stan danych, legenda i podgląd MID; po prawej podgląd HIGH ze stosami UMKK, EYVL, UMMV, UKLV i LZBB; podglądy w kolorach pliku sektorowego, sektory jednego stanowiska jako jeden obszar z nazwą i częstotliwością; kafelek sąsiada stałego rozmiaru: ID sektora w prawym górnym rogu i częstotliwość, gdy ktoś go obsługuje (jasne pole), bez nikogo ciemne pole z samym ID; granice pionowe między kafelkami, jak na szkicu (660, 365, 0; FL w dymku), FIR bez nikogo ADVISORY 122.800 pod nazwą; w EDUU, EDMM, ESAA, EYVL, LZBB i LKAA kafelki jednego kontrolera łączą się w jeden, w EDWW nigdy; CTR-y i TMA na podglądzie LOW tylko FIR EPWW, z sąsiadów jedynie TMA Ostrawy (LKMT) i Berlina (EDDB); sektor albo TMA z aktywną restrykcją vIFF lub zajętością powyżej 80 % przepustowości ma czerwone tło (czerwona TMA zawsze na LOW), a brak danych przepływu widać w wierszu stanu; plakietki APP i TWR tylko dla stacji online, na środku obsługiwanej części TMA albo CTR, bez linii (podzielone APP, np. EPWA, EPKK: plakietka na każde stanowisko; TWR/A pokazuje też wieżę z samym ATIS); dymki o stałej szerokości 360 px, odsunięte od kursora i od krawędzi ekranu; kliknięcie nagłówka stosu sąsiada otwiera obok niego wyciąg z LOA (tabele przekazań, zasady, stanowiska, przycisk COORDINATION › do dokumentu) |
| METEO | kolejno METAR (PL, MIL, INTL) i TAF (PL, INTL), od 0.13.1 jak strona METAR w PANDORZE: stacja w wąskiej lewej kolumnie, komunikat bez kodu stacji zawija się pod swoim początkiem, wiersze na przemian czarne i ciemnoszare; grupy w kolorach (dzień, kierunek wiatru, zjawisko i RMK zielone, wartości jasnozielone, ilość chmur ciemnozielona, BECMG/TEMPO/NOSIG/PROB/FM niebieskie, jednostki, temperatura i reszta po RMK białe), zjawiska z opisem po angielsku i po polsku tuż za grupą, np. „-RA[LIGHT RAIN / LEKKI DESZCZ]”; TAF: każda grupa zmian w nowej, wciętej linii; przełącznik COLOURED / MONO (MONO: wszystko białe, opisy zostają) pierwszy na pasku, zapamiętany w przeglądarce i wspólny dla pięciu list (`frontend/js/metarfmt.js`, `frontend/css/metar.css`; AERODROME, OVERVIEW, AWOS i karta lotniska zagranicznego bez zmian), WIND (sama mapa wiatru Windy, od 0.13.0 bez tabel i okienek; wiatr na wysokościach jest w AWALON) i RADAR, GAMET (IMGW, rejony A1–A5 albo wszystkie, z mapą rejonów; tekst pobiera serwer PolIDS), SIGWX (IMGW), ICING (oblodzenie z Windy, FL050–FL300), mapa QNH regionalnego rysowana jak mapa rejonów QNH PAŻP z obrysami TMA i CTR z plików sektorowych `.sct`/`.ese` (`scripts/trace_qnh_regions.py` → `data/seed/qnh_regions.json`), SAT EUR i SAT PL, TURB (mapy turbulencji IMGW +0…+21 h z odtwarzaniem), SUN (mapa dnia i nocy na Ziemi z punktem podsłonecznym; wschód, zachód, górowanie, BMCT i EECT dla dowolnego lotniska albo punktu na mapie, UTC i czas polski) |
| AWALON | wiatr od ziemi do 10 000 ft co 1000 ft (AMSL) nad 15 lotniskami AD 2 (bez wojskowych): tabela ALL z wszystkimi lotniskami (kolory prędkości do wyłączenia) i dla każdego lotniska wykres profilu jak w PANDORZE, tabela profilu (kierunek, prędkość, poryw, min/max kierunku i prędkości w ciągu ±1 h) i wiatr na pasach (0 ft z METAR, 10 m z prognozy, 3000 ft na podejściu); wiersz SFC na wysokości lotniska = wiatr z METAR (bez METAR prognoza 10 m kursywą), wiersze poniżej wysokości lotniska GND; prognoza [Open-Meteo](https://open-meteo.com) na poziomach 1000–600 hPa, jedno zapytanie na wszystkie lotniska, cache 30 min (najwyżej do północy UTC); `GET /api/meteo/wind-profile`, adres `#awalon/<ICAO>` |
| AERODROME | podzakładki jak w PANDORZE: 0 = OVERVIEW całego FIR EPWW (jeden TL dla kraju: FL080, a FL090, gdy na którymkolwiek lotnisku QNH ≤ 995 hPa; METAR/TAF ze stanem LVP, aktywne NOTAM-y, restrykcje ECFMP i vIFF, Airport Monitor vIFF; filtr stanowiska: APP/ACC zawęża lotniska i pokazuje checklistę otwarcia, TWR przenosi do lotniska; przy każdym lotnisku pas w użyciu z ATIS z literą ATIS albo pas preferowany w przerywanej ramce PREF, ARR/DEP, gdy są różne; przełącznik MINE/ALL dla ACC i APP: MINE ukrywa lotniska, które obsługuje teraz inny kontroler online – pierwszy zalogowany w kolejności przejmowania od poziomu APP w górę, bez TWR/GND/DEL lotniska, stanowisk informacji i dyrektorów – a „N hidden” mówi, kto je ma; ALL pokazuje je ze znakiem tego kontrolera); EPWW, ESAA, ED, ET, LKAA, LZBB, UMKK, EYVL, UMMV, UKLV = listy lotnisk FIR-u (także VFR i MIL) z wyszukiwarką SHOW / CLEAR; lotnisko zagraniczne: karta z METAR, TAF, ATIS i stanowiskami APP/TWR/GND/DEL/ATIS; lotnisko polskie: INFO (wiatr, pasy, ATIS, LVP, NOTAM, częstotliwości, wiatr na podejściu), AWOS (wiatr co 5 s, RVR z METAR albo symulowany, układ 1 RWY / 2 RWYS z osobnym pasem DEP i ARR) i TRAFFIC jak DMAN/AMAN (bez lotów OFFLINE znanych tylko z vIFF; drabiny TSAT, TTOT i ELDT, na lotniskach bez A-CDM EOBT i ETOT; widok AMAN z punktami wejścia i odstępem FLOW; zakładki STRIP z paskami EFES od 0.13.0 nie ma, stare `#strip/<ICAO>` otwiera TRAFFIC tego lotniska) |
| AD CIV / AD MIL / AD VFR, INOP | eAIP PAŻP; w każdej z trzech zakładek podmenu jak w PANDORZE: „eAIP” (cała przeglądarka pakietu) i przyciski lotnisk: AD CIV 15 lotnisk AD 2 eAIP IFR (mapy z AD 2.24), AD MIL 15 lotnisk wojskowych z MIL AD 4 eAIP MIL (AD 1.3, mapy z AD 4.24), AD VFR 69 lotnisk z AD 4 eAIP VFR (AD 1, mapy z AD 4.13; podmenu w jednej kolumnie zwykłych przycisków, przewijane, a lotnisko z adresu albo po ← przewija się do widoku); listy lotnisk z AIRAC AMDT 11-26 (AD CIV: 10-26) w kodzie z testem zgodności backend/frontend; lista map lotniska z PDF-em obok (`GET /api/docs/charts/<ifr\|mil\|vfr>/<ICAO>`, stary `GET /api/docs/charts/<ICAO>` = IFR; adresy `#adciv/EPWA`, `#admil/EPKS/12-5`, `#advfr/EPBC`; jeden wpis na mapę z krótką nazwą, np. AERODROME, PARKING APN 2, RWY 29 SID, RWY 11 ILS Z CAT II / LOC Z, w MIL RWY 11 SID HMA / RWY 29 STAR HMA (mapy dla statków wysokomanewrowych w filtrach SID / STAR), RWY 11 TACAN, RWY 29 PAR, w VFR VISUAL OPERATION 1:50 000 i 1:250 000; pełny tytuł w dymku; filtry ALL / ADC / APDC / SID / STAR / IAC / VFR / OBST / OTHER z liczbami; przyciski PDF ↗ i AD 2 TEXT ↗ albo AD 4 TEXT ↗); pasek nad ramką bez adresu strony; linki eAIP i strony lotnisk same przechodzą na poprawkę bieżącego cyklu AIRAC (wszystkie trzy pakiety tak samo, z cofnięciem do poprzedniej poprawki, gdy bieżącej nie ma); INOP: om.plvacc.pl (procedury operacyjne PL vACC) |
| CALLSIGN, AIRCRAFT | callsigny, typy samolotów tylko z `data/import/ICAO_Aircraft.json`, jeden rekord na oznaczenie ICAO (dane osiągów z `aircraft.csv` dołączone jako zakresy; WTC, RECAT-EU, wymiary, zdjęcia); AIRCRAFT: u góry przyciski producentów AIRBUS, BOEING, BOMBARDIER (z Canadairem, Learjetem i Dash 8 DH8A–DH8D), EMBRAER i GA (Pilatus, Diamond, Cessna, Piper, Aero AT-3, Robinson, Bell, Tecnam; grupy w tej kolejności) tej samej wielkości co przyciski menu; lista to tabela, jeden wiersz na typ: kod ICAO, producent, pełna nazwa ICAO, liczba silników, WTC, RECAT-EU; kliknięcie wiersza otwiera pod nim rozwinięcie: zdjęcie u góry, niżej zawsze rozpiętość (wirnik dla śmigłowców), długość, wysokość, MLW i MTOW (brak wartości to „–”), dalej pozostałe wartości w kratkach (IATA, opis typu, silniki, VMO, MMO, pułap, WTG, kod ARC), opis słownie i odnośniki (osiągi typu, kolejne zdjęcia); w podmenu ALL, pod nim KEYBOARD (oba na całą szerokość) i litery w dwóch kolumnach (pół szerokości przycisku); KEYBOARD otwiera i zamyka klawiaturę dotykową na dole zakładki pod listą (cyfry, QWERTY, „-”, CLEAR, SPACE, BACKSPACE), która wpisuje do pola wyszukiwania w miejscu kursora razem z wybraną literą lub producentem; wybór (otwarta / zamknięta) wspólny dla obu zakładek i zapamiętany w przeglądarce, bez wyboru klawiatura jest otwarta tylko na ekranie dotykowym; w CALLSIGN pole wyszukiwania zostaje u góry, przewija się tylko tabela |
| MAP | etykiety samolotów jak P21 PAŻP (callsign i GS; poziom, poniżej TL „A 53”, ze strzałką wznoszenia/zniżania; typ i WTC z lotniskiem docelowym albo punktem wyjścia z FIR; od 0.12.6 trzy linijki), widoczne tylko po najechaniu na samolot, w nieprzezroczystym okienku ustawianym w obrębie mapy, obok panelu lotu i wykresu TV (wybrany lot zostaje z etykietą; bez białego dymka samolotu i bez przełącznika etykiet), mniejsze symbole, lotniska jako zamknięte sześciokąty; ruch VATSIM związany z Polską: odloty z lotnisk EP, przyloty do nich i tranzyt przez FIR EPWW (samolot w FIR albo dalsza trasa z planu lotu wchodzi do FIR; bez planu lotu tylko w FIR), wybrany lot zostaje na mapie; przestrzeń na wybranym poziomie FL (ACC, TMA, CTA, CTR, FIS, sektory sąsiadów z ich plików `.ese`), FMP (dawniej Sector capacity: ruch i przepustowość sektorów na godzinę naprzód) i szczegóły lotów; panel boczny od 0.13.1: VISIBILITY SETTINGS, POSITIONS, ROUTE, FMP, LEGEND, wszystkie sekcje domyślnie zwinięte (zapamiętane są rozwinięte); VISIBILITY SETTINGS zbiera wszystkie ustawienia wyświetlania w grupach Traffic (samoloty, plakietki kontrolerów), Airspace (poziom FL, warstwy ACC/TMA/CTA/CTR/FIS/sąsiedzi z listami wyboru, obsada, granice FIR), Points and airways (lotniska, VOR/DME, NDB, punkty VFR i FIX, drogi lotnicze, nazwy punktów) i Basemap, a w nagłówku pokazuje rysowany poziom (np. FL300); przełączniki zapamiętane między wizytami (poza nakładką lotniczą); dymek przestrzeni: nazwa, ID, poziomy, częstotliwość, kto obsługuje i od kiedy (bez kolejności przejmowania); ATIS linia po linii, dane kontrolera po najechaniu na plakietkę lub opis stanowiska, lista sąsiednich FIR-ów domyślnie zwinięta; obsada wg kontrolerów online: sektory jednego stanowiska jako jeden obszar z jedną etykietą (granica tylko tam, gdzie zmienia się obsługujący), przestrzeni bez nikogo nie rysujemy; sekcja Positions: drzewo FIR → ACC / FIS / lotniska → stanowiska, w którym można włączyć stanowisko offline (symulacja logowania, SYM) albo ukryć zalogowane – sektoryzacja, plakietki lotnisk i plakietki CTR FIR-ów wg tego wyboru |
| COORDINATION | porozumienia LOA i LOP jak w ATCISS: LoA (tabele EXIT/COPX i ENTRY/COPN, filtr po punktach, wybór stanowiska z sektorami, które obsługuje wg kolejności przejmowania i kontrolerów online, FIR-y, LOA/LOP; adres `#coordination/agreements/<stanowisko>/<filtr>`) i DOCUMENTS (7 LOA z `data/docs/LOA` i 20 LOP z podfolderów `data/docs/LOP` (LOP ACC, LOP APP, LOP TWR); karta z nazwą i przyciskami PDF / LoA, bez typu, FIR-ów, AIRAC, dat, rewizji i listy sektorów; PDF obok; `#coordination/docs/<id>`); rejestr dokumentów `data/seed/coordination.json`, przekazania z `data/seed/loa.json` |
| CONVERSION | u góry zegary UTC i czasu polskiego (CET/CEST), bez paska przewijania; kalkulator jednostek: hPa/inHg/mmHg, ft/m/FL, wysokość a FL przy QNH (ISA), NM/km/SM, kt/km/h/m/s/mph, Mach/TAS/CAS (ISA), ft/min a m/s, gradient, °C/°F/K, kg/lb/t |
| EMERGENCY | procedury awaryjne (ASSIST i checklisty sytuacji niestandardowych) |
| SYT OP | wszystkie aktywne NOTAM-y FIR EPWW i głównych lotnisk (cv.plvacc.pl) z filtrem lokalizacji i tekstu, sortowaniem i pełną treścią |
| AUP | na razie tylko informacja, że będzie dostępny w przyszłości |
| OTHER | podmenu alfabetycznie jak w PANDORZE (17 pozycji, domyślnie DOCS; adres `#other/<id>`; od 0.13.1 bez PHRASEOLOGY: stare `#phraseology` otwiera OTHER w jego stanie, a `#other/phraseology` – DOCS): 4P, AFTN, BOMB PHONE, BRAKING ACTION, HOLDING, IA, LIGHT GUN, METEO, NATO WEATHER i POSITION na razie z informacją „This function will be available in the future.”; CHECKLIST (checklisty stanowiska: OPEN, CLOSE, HANDOVER, RWY CHG i TIPS – pięć wskazówek dla kontrolerów; `#other/checklist/<id>`, stare `#checklist` i `#checklist/<id>` przekierowuje, zaznaczenia zostają); DOCS (PDF-y z `data/docs/` bez LOA i LOP, które są w COORDINATION; `#other/docs/<plik>`, stare `#docs/<plik>` przekierowuje); FLIGHT PLAN (callsign → plan lotu VATSIM z polami 7–19 jak w FPL ICAO, z typem łączności /V/ /R/ /T/, oraz imię, nazwisko, PID, rating i godziny pilota i kontrolera z api.vatsim.net, które nie wstrzymują planu; lot online z obecnym SSR, wysokością i prędkością, prefile bez MAP; `GET /api/vatsim/flightplan/<CALLSIGN>`, `#other/flight-plan/<CALLSIGN>`); FMP (traffic volumes vIFF w tabeli SECTOR \| CAPACITY (ENTRIES) \| OCCUPANCY, aktywne szare na górze, przepustowość wg aktywnej regulacji na czerwono z deklarowaną w nawiasie; kliknięcie sektora pokazuje po prawej wykresy ENTRY (wejścia w kolejnych 60 min co 20 min wobec przepustowości na godzinę) i OCC (samoloty w sektorze minuta po minucie wobec progu zajętości) na wspólnej osi od pełnej godziny przed bieżącą do +5 h, z linią „teraz”, przepustowością przerywaną i regulacjami na czerwono; drugie kliknięcie albo ✕ zamyka; w oknie węższym niż ok. 1250 px wykresy są pod tabelą; całodobowe `/etfms/airspaces` vIFF, `GET /api/viff/sectors/<TV>`, `#other/fmp/<TV>`); REGCAUSE (kody przyczyn regulacji ATFM z opisem i opóźnieniem IATA, przewijana lista z zielonymi paskami kategorii, `data/seed/regcause.json`, `GET /api/regcause`); SQUAWK (od 0.13.0 tutaj, wcześniej osobna zakładka: pule kodów SSR FIR EPWW z EUROCONTROL CAL v4.13 (`data/import/eurocontrol-icao-eur-cal-v4-13.xls`, wyciąg `data/seed/squawk.json`), jedna lista pul i kodów specjalnych (sam tytuł, m.in. 0001 LPR) po kodzie; jedno pole wyszukiwania: kod zaznacza pule i przewija do nich (`#other/squawk/7700`, stare `#squawk/7700` przekierowuje), odpowiedź łączy pule tego samego zakresu (np. EUR-E 0020–0037: LB, LH, LU), tekst filtruje, nazwa grupy (EPWW, CCAMS, NATO, EUR-E) pokazuje tę grupę; kody specjalne `{code, label}` w `data/seed/squawk.json` są utrzymywane ręcznie i import ich nie zmienia; import arkusza: `python -m backend.app.importers.squawk_cal <plik.xls>` (narzędzia w `requirements-dev.txt`)); VFR MINIMA (minima VMC wg poziomu i klasy przestrzeni, minimalne wysokości w dzień i w nocy, VFR w nocy, specjalny VFR oraz minima LPR (HEMS) w dzień i w nocy) |
| ? (HOME), ABOUT | HOME: przywitanie z ratingiem, stanowisko, na którym kontroler jest zalogowany w VATSIM, i jego rezerwacje, wybór stanowiska (wspólny z AERODROME › OVERVIEW) i przycisk PREPARE SESSION, na dole wersja i bieżący AIRAC z datami; ABOUT: informacje o programie, skróty do zakładek i lista zmian |
| ADMIN | lista CID-ów z dostępem i odmowy logowania (tylko admin) |

Źródła danych: pliki EuroScope (sektorówka EPWW, navdata, pliki `.ese` vACC sąsiadów w `data/import/neighbours/`; sektory z nich
w `data/seed/sectors.geojson`), VATSIM (data feed, bookings), metar.vatsim.net /
aviationweather.gov, NOTAM z cv.plvacc.pl, [vIFF](https://api.viffsys.com/docs), [ECFMP](https://ecfmp.vatsim.net), OurAirports, vacs-data, VATSpy,
[VATSIM Germany Knowledgebase](https://knowledgebase.vatsim-germany.org/shelves/centersektoren) (`data/seed/names_de.json`), LOA (`data/docs/LOA/`, wyciąg `data/seed/loa.json`, rejestr dokumentów `data/seed/coordination.json`), GAMET, SIGWX, TURB, SAT PL i radar z IMGW-PIB
(aviation-api.imgw.pl), mapy WIND i ICING z Windy (ECMWF), prognoza wiatru na podejściu i profile wiatru AWALON z [Open-Meteo](https://open-meteo.com) (CC BY 4.0,
wymienione w ABOUT), statystyki godzin członków z api.vatsim.net, kody przyczyn regulacji z ATFCM Users Manual EUROCONTROL, minima VFR z SERA i przepisów ULC, minima LPR z dokumentu PL vACC, kody SSR z EUROCONTROL CAL, wskazówki TIPS z plakatu TOP 5 TIPS (Air Ground Communication Safety
Improvement Initiative, SKYbrary bookshelf 116).

## Uruchomienie

```bash
cp .env.example .env
docker compose up --build
```

http://localhost:1337 - pierwszy build trwa kilka minut (import sektorówki i navdata do bazy w obrazie).
Lokalnie domyślnie jest `POLIDS_AUTH_MODE=dev`, czyli formularz z dowolnym CID i ratingiem zamiast VATSIM.

Praca nad kodem (backend przeładowuje się sam, zmiany w JS/CSS po odświeżeniu):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Bez Dockera: `pip install -r requirements.txt` i
`python -m uvicorn backend.app.main:app --port 1337 --reload --reload-dir backend`.

Testy:

```bash
docker build --target test -t polids-test . && docker run --rm polids-test
```

Swagger: http://localhost:1337/docs (po zalogowaniu).

## Konfiguracja

Wszystko przez zmienne `POLIDS_*` w `.env`, opis w [.env.example](.env.example). Klucze wpisujemy tylko do `.env`,
repo jest publiczne.

Logowanie (`POLIDS_AUTH_MODE`):

- `none` - bez logowania,
- `dev` - formularz testowy, tylko na localhost,
- `vatsim` - VATSIM Connect, na serwerze wymuszone w `docker-compose.prod.yml`. Wymaga `POLIDS_VATSIM_CLIENT_ID`,
  `POLIDS_VATSIM_CLIENT_SECRET` i `POLIDS_SECRET_KEY` (min. 32 znaki), inaczej aplikacja nie wstanie.

Kto może wejść:

- administratorzy z `POLIDS_AUTH_ADMIN_CIDS` - zawsze, i tylko oni widzą zakładkę ADMIN,
- CID-y dodane przez admina w zakładce ADMIN (dodaj, usuń, opis). Usunięcie odcina dostęp od razu,
- reszta dostaje "No access for CID ...", a próba ląduje w ADMIN -> Denied logins, skąd można ją dodać jednym klikiem.

Lista jest w osobnej bazie `data/state/polids-state.db` (w Dockerze wolumen `state`), bo `polids.db` jest
przebudowywana z repo przy każdym obrazie. Bez logowania dostępne jest tylko `/auth/*`, `/healthz` i pliki PWA.

Do testów VATSIM Connect bez prawdziwych kont jest sandbox `https://auth-dev.vatsim.net` (konta 10000000-10000010,
hasło = CID), ustawiany przez `POLIDS_VATSIM_AUTH_URL`.

PWA: w Chrome/Edge "Zainstaluj aplikację" w pasku adresu - otwiera się jako osobne okno.

## Serwer

Docker Compose na VPS + Caddy (Let's Encrypt), obraz budowany w GitHub Actions i trzymany w GHCR, deploy po pushu
do `main`. Instrukcja: [deploy/README.md](deploy/README.md).

## Aktualizacja danych

- nowa sektorówka: podmienić pliki w `data/import/`, odświeżyć sektory (`python -m backend.app.importers.sectors_geojson`),
  potem mapę QNH (`python scripts/trace_qnh_regions.py`: obrysy TMA/CTR/FIR z `.sct`/`.ese` do `data/seed/qnh_regions.json`;
  potrzebuje numpy i shapely z `requirements-dev.txt`) i przebudować obraz (na serwerze wystarczy push)
- sektory EPWW i sąsiadów (MAP, RADIO): aplikacja bierze je z `data/seed/sectors.geojson`, a ten plik generuje
  `python -m backend.app.importers.sectors_geojson` z plików `.ese` (`--check`: czy plik pasuje do plików `.ese`
  i ustawień generatora; po podmianie pliku przypomina o tym test, ostrzeżenie w logu przy starcie, a build obrazu
  Dockera się przerywa). Ręczne poprawki w pliku działają po restarcie aplikacji, generator je nadpisze
- OurAirports: `python scripts/fetch_ourairports.py` (tylko lotniska i pomoce; elewacje ze źródłem, z AIP albo
  lotniska.dlapilota.pl, zostają; lotnisko z pasami lub częstotliwościami, którego OurAirports już nie ma, zostaje
  z ostrzeżeniem; pasów i częstotliwości skrypt nie nadpisuje)
- pasy, częstotliwości (z godzinami pracy i uwagą), pasy preferowane i progi LVP z AIP Polska / AIP MIL (eAIP PAŻP): ręcznie
  w `data/seed/runways.csv` (metry), `frequencies.csv`, `runway_config.json`, `lvp.json`; każdy wiersz/wpis ma źródło
  (sekcja AIP albo serwis dla lotnisk VFR). Po zmianie CSV podbić `SCHEMA_VERSION` w `backend/app/database.py`
  (przy starcie pełny import danych)
- typy samolotów: lista typów to `data/import/ICAO_Aircraft.json` (podmienić plik); `python scripts/build_aircraft_seed.py
  <ścieżka do aircraft-db>` odświeża tylko dane osiągów w `data/seed/aircraft.csv`
- logo i ikony: `frontend/icons/` (paczka logo PolIDS, opcja „FIR EPWW”)
- sąsiedzi: nowszy plik `.ese` vACC sąsiada do `data/import/neighbours/` (lista w `data/import/README.md`), potem generator
  `sectors.geojson` jak wyżej
- bez kodu: `data/seed/qnh_regions.json`, `lvp.json`, `runway_config.json`, `checklists.json`, `emergency.json`,
  `callsigns.csv`

## Pas preferowany

Jeśli na lotnisku nadaje ATIS, pas w użyciu bierzemy z jego tekstu. Bez ATIS-u (zasada z
[vatiris](https://github.com/minsulander/vatiris)):

1. pasy preferowane z AIP AD 2.21 (`data/seed/runway_config.json`: EPWA, EPMO, EPWR, EPGD, EPPO) w swoich oknach czasowych
   (godziny UTC zimą, w nawiasie latem; czas letni UE liczony bez tzdata), osobno dla lądowań i startów, w kolejności
   z AIP („26, potem 08”); pas odpada, gdy składowa w plecy albo boczna z porywami przekracza limit z AIP albo gdy
   zachodzi warunek, przy którym hałas nie decyduje (podstawa chmur, widzialność, podejście bez ILS, burza); wtedy
   do startu pierwszy pas z listy AIP w limicie wiatru (ILS liczy się tylko przy lądowaniu: EPWA w mgle ARR 33, DEP 29);
   start pod prąd lądowań (ten sam pas, przeciwny kierunek) tylko na lotnisku z jednym pasem, gdzie AIP to dopuszcza
   (EPPO przy 100/08: ARR 10, DEP 28), na EPWA następny pas z listy (przy 190/10: ARR 11, DEP 15, nie 29); w LVP
   pasów preferowanych z AD 2.21 nie stosujemy: obowiązują pasy dopuszczone w LVP przez AD 2.22 (klucz `lvp`, EPWA:
   lądowania 33 albo 11, starty 29 albo 15; EPPO: lądowania 28, starty 28 albo 10), starty nigdy pod prąd lądowań
   (EPWA 33/29 albo 11/15, EPPO 28/28), pierwsza para z wiatrem w plecy z porywami w limicie lotniska (EPWA przy
   070/10: 11/15, nie 33/29 z 7 kt w plecy), bez niej osobno pierwszy pas w limicie; lądowania tylko od minimów
   kategorii ILS (RWY 11 CAT II od RVR 300 m, RWY 33 CAT IIIA od 175 m; poniżej minimów na wszystkich pasach pas
   z najniższymi, z uwagą), a przy RVR pasa startowego < 125 m ostrzeżenie „starty niedozwolone” (bez grupy RVR
   widzialność, tak też nazwana); bez list z AD 2.22 kierunek z ILS,
2. LVP / przygotowanie LVP / IMC: kierunek z ILS, o ile wiatr w plecy nie przekracza 5 kt (przy ciszy i wietrze
   zmiennym pierwszy w kolejności lądowań z AIP),
3. słaby wiatr (< 5 kt), tylko lotniska bez pasów preferowanych w AIP: konfiguracja preferowana lotniska (arr/dep
   w `runway_config.json`, obecnie żadne lotnisko jej nie ma), bez niej kierunek z ILS,
4. w pozostałych przypadkach największa składowa czołowa.

Wyposażenie pasów (ILS, RNP, VOR, NDB) czytane jest z nazw procedur w `.ese`. Pasa niesuchego i uskoku wiatru z METAR
nie oceniamy.

## LVP

Progi z AIP AD 2.22 i AIP MIL AD 4.20 w `data/seed/lvp.json`: przygotowanie, wprowadzenie i odwołanie (RVR, widzialność,
podstawa chmur; lotniska wojskowe: widzialność z odpowiednikiem RVR, tylko odloty). LVP po wprowadzeniu trwa do spełnienia
warunków odwołania (histereza w pamięci procesu, po restarcie albo przerwie w METAR-ach ponad 90 min od zera; starszy
METAR z innego zapytania dostaje stan z nowszego), potem przez 30 min od godziny odwołania „LVP CANCELLED”. Lotniska, dla
których AIP nie przewiduje LVP (VFR, część wojskowych, EPRA, EPZG), mają „LVP not applicable”. EPWA i EPPO: z tekstu AD 2.22
wklejonego przez Marka (strony eAIP urywały się przy pobieraniu).

## Znane ograniczenia

- PAŻP i om.plvacc.pl blokują ramki (`X-Frame-Options`) - zostaje przycisk otwierający stronę w nowej karcie (↗).
- Format NOTAM z cv.plvacc.pl nie jest udokumentowany, parser dzieli tekst po nagłówkach `A1234/26 NOTAMN`.
- Parser ATIS obsługuje typowe formaty vATIS.
- vIFF nie publikuje schematów odpowiedzi; TOBT/TSAT/TTOT są tylko, gdy ktoś prowadzi CDM na EPWA. Godziny w vIFF
  są bez daty, przejście przez północ liczone względem bieżącej godziny UTC.
- AWOS nie ma czujników - wiatr chwilowy, średnia 2 min i min/max są symulowane z METAR (oznaczenie SYM). RVR bez grupy w METAR
  jest symulowany z widzialności (zakładamy światła HI, więc w nocy na małych lotniskach może wyjść za wysoki).
- QFE liczone w przybliżeniu z QNH i elewacji.
- Mapa QNH (`qnh_regions.json`, `scripts/trace_qnh_regions.py`): granica FIR i obrysy TMA/CTR z plików sektorowych `.sct`/`.ese`;
  ze zrzutu mapy z AIP Polska (`data/import/qnh_pansa.png`, ok. 0,5 km) odrysowane są tylko linie rejonów QNH 1-14 i wojskowe MTMA/MCTR. QNH rejonu = najniższe QNH z METAR jego lotnisk (oficjalne liczy IMGW z modelu);
  pasy 15-17 (53°N, 51°N) = najniższe QNH z lotnisk pasa.
- OVERVIEW: TL liczony z QNH 15 kontrolowanych lotnisk z METAR (lotnisko bez METAR nie jest liczone); próg 995 hPa
  włącznie (OM PL vACC pisze „poniżej 995”). TA 6500 ft niesprawdzone w eAIP. Część pól vIFF (przepustowość lotniska, przyloty
  w godzinie) odczytana z dokumentacji i odpowiedzi API. NOTAM-y wg okresu B)-C), bez harmonogramu D). ECFMP/vIFF zawsze dla całego FIR.
- LOA w RADIO i COORDINATION to ręczny wyciąg z PDF-ów (obowiązuje PDF); LOA z Lwowem jest z 2022 r. Nazwy niemieckie z Knowledgebase (08.10.2026);
  CTR bez nazwy w żadnym źródle dostaje callsign wspólny dla FIR-u (szarszy, „przyjęty”).
- Kolejność przejmowania sektorów ACC z tabel om.plvacc.pl/docs/2610/ownerships (`data/seed/ownership.json`, wklejone 06.10.2026,
  przy nowym AIRAC trzeba wkleić ponownie); B, C, D HIGH i T MID wg pliku `.ese`. TMA/CTR: najpierw APP/TWR z `.ese`, potem ACC.
- Sektory sąsiadów: z każdego pliku tylko FIR-y tego vACC (z ukraińskiego tylko Lwów), sektory zależne od pasa w jednym układzie
  na lotnisko (kierunek najbliższy wiatrowi z ok. 250°), granice uproszczone o ok. 100 m, Białoruś (UMMV) z kopii w pliku EPWW.
  Zasięg stanowisk bez sektora w żadnym pliku jest przybliżony (VATSpy albo okrąg 30/10 NM).
- Paski EFES: CFL, TAXI/GATE, NR, PRV, LP/TG puste - tych danych nie ma w feedzie VATSIM ani w vIFF.
- Rezerwacje VATSIM mają tylko CID; imię widać, gdy ta osoba jest online.
- Jeden worker uvicorna (cache w pamięci). 40 osób odświeżających co 15 s to ~23 req/s przy p95 < 100 ms;
  sufit jednego procesu to ok. 50 req/s, wyżej trzeba Redisa i kilku workerów.

## Licencje danych

- typy samolotów: `data/import/ICAO_Aircraft.json` (lista typów ICAO); dane osiągów z [aircraft-database.com](https://aircraft-database.com) (ODC-By), progi WTC/RECAT z
  [vatger/atciss](https://github.com/vatger/atciss) (MIT)
- lotniska, pomoce: [OurAirports](https://ourairports.com/data/) (public domain)
- pasy, częstotliwości, elewacje, pasy preferowane i progi LVP: AIP Polska i AIP MIL (PAŻP, eAIP, AIRAC AMDT 10-26);
  lotniska VFR spoza AIP: [lotniska.dlapilota.pl](https://lotniska.dlapilota.pl), [airfield.directory](https://airfield.directory),
  progi pasów z `EPWW-Sector.sct` albo OurAirports (źródło w kolumnie `source` i `elevation_source`)
- Leaflet (BSD-2), CARTO/OpenStreetMap (ODbL), Esri World Gray Canvas
- [polygon-clipping](https://github.com/mfogel/polygon-clipping) 0.15.7 (MIT, z splaytree MIT i robust-predicates
  Unlicense) w `frontend/vendor/polygon-clipping/`: suma sektorów jednego stanowiska na mapie
- ATFCM/CDM: [vIFF](https://viffsys.com) (Roger Puig), tylko odczyt
- granice FIR: [vatspy-data-project](https://github.com/vatsimnetwork/vatspy-data-project) (CC BY-SA 4.0)
- callsigny i nazwy sektorów niemieckich: [VATSIM Germany Knowledgebase](https://knowledgebase.vatsim-germany.org/shelves/centersektoren)
  (tylko krótkie dane, przy każdym wpisie adres źródła)
- LOA: porozumienia PL vACC z vACC sąsiadów (`data/docs/LOA/`); układ COORDINATION wzorowany na
  [vatger/atciss](https://github.com/vatger/atciss) (MIT), kod napisany od nowa
- kody SSR: EUROCONTROL, ICAO EUR SSR Code Allocation List (CAL) wyd. 4.13 z 04.03.2026
- GAMET: IMGW-PIB (awiacja.imgw.pl)
- mapa rejonów QNH: linie rejonów i MTMA/MCTR z AIP Polska (PAŻP), zrzut `data/import/qnh_pansa.png`; TMA/CTR z plików sektorowych
- sektory i stanowiska FIR-ów sąsiednich: pliki `.ese` pakietów sektorowych vACC sąsiadów (`data/import/neighbours/`)
- łańcuchy sektorów i etykiety sąsiadów: [vacs-data](https://github.com/vacs-project/vacs-data)
  ([CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), commit c5aa4bd), wyciąg
  `data/seed/vacs_epww.json` na tej samej licencji
- checklisty stanowiska i wybór pasa: [vatiris](https://github.com/minsulander/vatiris) (GPL-3.0)
- checklisty EMERGENCY: EUROCONTROL HRS/TSP-004-GUI-05 wyd. 2.0, Annex A i B
- widok AWOS i mapa QNH wzorowane na [vAWOS](https://github.com/aleksandermarcingadomski-commits/vAWOS)
  (bez licencji, więc kod napisany od nowa)
- zdjęcia samolotów z Wikipedii, autor i licencja na stronie artykułu
- pliki EuroScope: pakiet sektorowy PL vACC / GNG

PDF-y w `data/docs/` (ICAO Doc 4444, Doc 9432, RECAT-EU) są chronione prawem autorskim - na serwerze tylko po
zalogowaniu, ale w publicznym repo lepiej trzymać linki niż pliki.
