# PolIDS

![PolIDS](frontend/icons/polids-logo.svg)

Polish Integrated Display System dla kontrolerów VATSIM PL vACC. Układ wzorowany na PANDORZE (PAŻP), zawartość zakładek
w stylu EUROCONTROL NM UI. Cały interfejs jest po angielsku i ma ostre krawędzie (od 0.12.5). Backend FastAPI + SQLite,
frontend w czystym JS, całość w Dockerze.

| Zakładka | Co jest |
|---|---|
| RADIO | jedna strona jak w PANDORZE: kolory jak w pliku sektorowym (obszar bez nikogo jasnoszary, obsadzony ciemny, tak samo w LOW, MID i HIGH), przyciski i kafelki stanowisk jak na zdjęciu PANDORY; u góry pasek ATIS polskich lotnisk, podglądy FIR EPWW LOW (przekrój FL095–FL330 suwakiem wysokości), mały MID i HIGH z obszarami stanowisk ACC: sektory obsługiwane przez to samo stanowisko (kolejność przejmowania z om.plvacc.pl) jako jeden obszar z nazwą stanowiska i częstotliwością, sektory bez nikogo jasnoszare z samym ID; granice sektorów ACC sąsiadów na podglądach (wg poziomu) i obszary APP/TWR lotnisk przy granicy FIR (np. LZTT, LKMT, EDDB); stosy sektorów sąsiadów graniczących z EPWW jak w VACS, bez FMP (ESAA, EDWW, EDUU, EDMM, LKAA po lewej; UMKK, EYVL, UMMV, UKLV, LZBB po prawej): częstotliwość tylko, gdy ktoś obsługuje sektor, bez nikogo w stosie ADVISORY 122.800, granice FL raz, między polami; warstwy ATIS, LOW MID HIGH, APP (część TMA na stanowisko: WA APP, WA N APP, WA S APP; TMA bez APP z wieżą), TWR, TWR/ATIS i FIS – etykiety obok obrysów TMA i CTR, z linią do punktu, częstotliwość tylko, gdy ktoś obsługuje; kliknięcie nazwy FIR-u sąsiada otwiera wyciąg z LOA (tabele przekazań, zasady, stanowiska, przycisk COORDINATION › do dokumentu) |
| METEO | kolejno METAR (PL, MIL, INTL), TAF (PL, INTL), WIND z wiatrem 0 ft / 3000 ft na podejściu do każdego pasa (zawsze otwiera się na 0 ft) i RADAR, GAMET (IMGW, rejony A1–A5 albo wszystkie, z mapą rejonów; tekst pobiera serwer PolIDS), SIGWX (IMGW), ICING (oblodzenie z Windy, FL050–FL300), mapa QNH regionalnego rysowana jak mapa rejonów QNH PAŻP z obrysami TMA i CTR z plików sektorowych `.sct`/`.ese` (`scripts/trace_qnh_regions.py` → `data/seed/qnh_regions.json`), SAT EUR i SAT PL, TURB (mapy turbulencji IMGW +0…+21 h z odtwarzaniem), SUN (mapa dnia i nocy na Ziemi z punktem podsłonecznym; wschód, zachód, górowanie, BMCT i EECT dla dowolnego lotniska albo punktu na mapie, UTC i czas polski) |
| AERODROME | podzakładki jak w PANDORZE: 0 = OVERVIEW całego FIR EPWW (jeden TL dla kraju: FL080, a FL090, gdy na którymkolwiek lotnisku QNH ≤ 995 hPa; METAR/TAF ze stanem LVP, aktywne NOTAM-y, restrykcje ECFMP i vIFF, Airport Monitor vIFF; filtr stanowiska: APP/ACC zawęża lotniska i pokazuje checklistę otwarcia, TWR przenosi do lotniska); EPWW, ESAA, ED, ET, LKAA, LZBB, UMKK, EYVL, UMMV, UKLV = listy lotnisk FIR-u (także VFR i MIL) z wyszukiwarką SHOW / CLEAR; lotnisko zagraniczne: karta z METAR, TAF, ATIS i stanowiskami APP/TWR/GND/DEL/ATIS; lotnisko polskie: INFO (wiatr, pasy, ATIS, LVP, NOTAM, częstotliwości, wiatr na podejściu), AWOS (wiatr co 5 s, RVR z METAR albo symulowany, układ 1 RWY / 2 RWYS z osobnym pasem DEP i ARR) i TRAFFIC jak DMAN/AMAN (bez lotów OFFLINE znanych tylko z vIFF; drabiny TSAT, TTOT i ELDT, na lotniskach bez A-CDM EOBT i ETOT; widok AMAN z punktami wejścia i odstępem FLOW) |
| AD CIV / AD MIL / AD VFR, INOP | eAIP PAŻP; w AD CIV przyciski 15 lotnisk AD 2 (lista map lotniska z AD 2.24 eAIP, `GET /api/docs/charts/<ICAO>`, adres `#adciv/EPWA`); linki eAIP same przechodzą na poprawkę bieżącego cyklu AIRAC; INOP: om.plvacc.pl (procedury operacyjne PL vACC) |
| CALLSIGN, AIRCRAFT | callsigny, typy samolotów tylko z `data/import/ICAO_Aircraft.json`, jeden rekord na oznaczenie ICAO (dane osiągów z `aircraft.csv` dołączone jako zakresy; WTC, RECAT-EU, wymiary, zdjęcia, przyciski producentów); przycisk ALL i litery w dwóch kolumnach |
| MAP | etykiety samolotów jak P21 PAŻP (callsign i GS; poziom, poniżej TL „A 53”, ze strzałką wznoszenia/zniżania; typ i WTC z lotniskiem docelowym albo punktem wyjścia z FIR; „h s r” i RFL w dziesiątkach), mniejsze symbole, lotniska jako zamknięte sześciokąty; ruch VATSIM związany z Polską: odloty z lotnisk EP, przyloty do nich i tranzyt przez FIR EPWW (samolot w FIR albo dalsza trasa z planu lotu wchodzi do FIR; bez planu lotu tylko w FIR), wybrany lot zostaje na mapie; przestrzeń na wybranym poziomie FL (ACC, TMA, CTA, CTR, FIS, sektory sąsiadów z ich plików `.ese`), przepustowość i szczegóły lotów z vIFF; ATIS linia po linii, dane kontrolera po najechaniu na plakietkę lub opis stanowiska, lista sąsiednich FIR-ów domyślnie zwinięta; obsada wg kontrolerów online: sektory jednego stanowiska jako jeden obszar z jedną etykietą (granica tylko tam, gdzie zmienia się obsługujący), przestrzeni bez nikogo nie rysujemy; sekcja Positions: drzewo FIR → ACC / FIS / lotniska → stanowiska, w którym można włączyć stanowisko offline (symulacja logowania, SYM) albo ukryć zalogowane – sektoryzacja, plakietki lotnisk i plakietki CTR FIR-ów wg tego wyboru |
| COORDINATION | porozumienia LOA i LOP jak w ATCISS: LoA (tabele EXIT/COPX i ENTRY/COPN, filtr po punktach, wybór stanowiska z sektorami, które obsługuje wg kolejności przejmowania i kontrolerów online, FIR-y, LOA/LOP; adres `#coordination/agreements/<stanowisko>/<filtr>`) i DOCUMENTS (7 LOA z `data/docs/LOA` i 20 LOP z podfolderów `data/docs/LOP` (LOP ACC, LOP APP, LOP TWR); nazwy, tagi AIRAC/FIR/sektory, PDF obok; `#coordination/docs/<id>`); rejestr dokumentów `data/seed/coordination.json`, przekazania z `data/seed/loa.json` |
| CONVERSION | u góry zegary UTC i czasu polskiego (CET/CEST), bez paska przewijania; kalkulator jednostek: hPa/inHg/mmHg, ft/m/FL, wysokość a FL przy QNH (ISA), NM/km/SM, kt/km/h/m/s/mph, Mach/TAS/CAS (ISA), ft/min a m/s, gradient, °C/°F/K, kg/lb/t |
| CHECKLIST, EMERGENCY | checklisty stanowiska, procedury awaryjne EUROCONTROL |
| SYT OP | wszystkie aktywne NOTAM-y FIR EPWW i głównych lotnisk (cv.plvacc.pl) z filtrem lokalizacji i tekstu, sortowaniem i pełną treścią |
| AUP | na razie tylko informacja, że będzie dostępny w przyszłości |
| STRIP | paski postępu lotu EFES (przeniesione z AERODROME › TRAFFIC), podzakładka dla każdego z 15 głównych lotnisk; najechanie nic nie otwiera, kliknięcie paska (albo Enter) otwiera okno EXTENDED LABEL WINDOW jak w instrukcji SDD 2014 (Figure 2-6, Table 2-13; przycisk KEY pokazuje nazwy pól) |
| SQUAWK | pule kodów SSR FIR EPWW z EUROCONTROL CAL v4.13 (`data/import/eurocontrol-icao-eur-cal-v4-13.xls`, wyciąg `data/seed/squawk.json`), sprawdzanie kodu (`#squawk/7700`), kody specjalne; import arkusza: `python -m backend.app.importers.squawk_cal <plik.xls>` (narzędzia w `requirements-dev.txt`) |
| OTHER | podmenu: DOCS (PDF-y z `data/docs/` bez LOA i LOP, które są w COORDINATION; adres `#other/docs/<plik>`, stare `#docs/<plik>` przekierowuje) i PHRASEOLOGY (baza frazeologii EUROCONTROL, `#other/phraseology`, stare `#phraseology` przekierowuje) |
| ? (HOME), ABOUT | HOME: przywitanie z ratingiem, stanowisko, na którym kontroler jest zalogowany w VATSIM, i jego rezerwacje, wybór stanowiska (wspólny z AERODROME › OVERVIEW) i przycisk PREPARE SESSION, na dole wersja i bieżący AIRAC z datami; ABOUT: informacje o programie, skróty do zakładek i lista zmian |
| ADMIN | lista CID-ów z dostępem i odmowy logowania (tylko admin) |

Źródła danych: pliki EuroScope (sektorówka EPWW, navdata, pliki `.ese` vACC sąsiadów w `data/import/neighbours/`; sektory z nich
w `data/seed/sectors.geojson`), VATSIM (data feed, bookings), metar.vatsim.net /
aviationweather.gov, NOTAM z cv.plvacc.pl, [vIFF](https://api.viffsys.com/docs), [ECFMP](https://ecfmp.vatsim.net), OurAirports, vacs-data, VATSpy,
[VATSIM Germany Knowledgebase](https://knowledgebase.vatsim-germany.org/shelves/centersektoren) (`data/seed/names_de.json`), LOA (`data/docs/LOA/`, wyciąg `data/seed/loa.json`, rejestr dokumentów `data/seed/coordination.json`), GAMET z IMGW
(aviation-api.imgw.pl), kody SSR z EUROCONTROL CAL.

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

- PAŻP, om.plvacc.pl i EUROCONTROL Learning Zone blokują ramki (`X-Frame-Options`) - zostaje przycisk otwierający stronę w nowej karcie (↗).
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
