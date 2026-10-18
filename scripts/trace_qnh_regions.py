"""Mapa QNH regionalnego (METEO › QNH): rejony 1–14, pasy awaryjne 15–17, TMA/MTMA i CTR/MCTR do data/seed/qnh_regions.json.

Wzór: mapa rejonów QNH z AIP Polska (PAŻP), zrzut 3840x2160 data/import/qnh_pansa.png (siatka 14°–25°E, 49°–55°N
w odwzorowaniu stożkowym Lamberta dopasowanym do siatki zrzutu, LCC niżej; kontrola: symbole lotnisk wypadają średnio
0,2 px od współrzędnych z airports.csv, pomarańczowe linie dokładnie na 53°N i 51°N).

Źródła geometrii:
- granica FIR EPWW: plik sektorowy data/import/EPWW-Sector.sct (grupa "FIR border 0 - EPWW");
- TMA/MTMA cywilne i CTR/MCTR: sektory pliku data/import/EPWW-Sector.ese (dolne warstwy, poniżej FL095), wg
  przedrostków nazw "ese" przy TMA w pliku rejonów; obszar "BELOW … QNH FROM EPxx" = suma warstw, cienkie linie
  w środku = granice części TMA o różnych dolnych granicach (jak na mapie PAŻP); TMA Kraków dzieli na część Katowic
  i Krakowa pogrubiona linia z mapy PAŻP (SPLIT); części TMA, których brak w pliku .ese (TMA Łódź C), z obrysu
  "… TMA OUT" pliku .sct (SCT_FILL);
- MTMA i MCTR wojskowe, których nie ma w plikach sektorowych (MIL_TMA, MIL_CTR): wierzchołki odczytane ze zrzutu
  (proste odcinki jak na mapie); odcinki wspólne z TMA z pliku .ese biegną dokładnie po jej granicy;
- linie rejonów (LINES): wierzchołki odczytane ze zrzutu, proste odcinki; tam, gdzie linia na mapie PAŻP biegnie
  granicą TMA/CTR, biegnie dokładnie granicą z pliku .ese; końce na granicy FIR leżą na granicy z pliku .sct.
  Rejony powstają z podziału FIR liniami (shapely.polygonize), więc sąsiednie rejony mają identyczne wspólne
  granice i pokrywają FIR bez dziur i nakładania. Pasy 15–17 = FIR podzielony równoleżnikami 53°N i 51°N.

Wierzchołek w LINES, MIL_TMA i SPLIT: piksel zrzutu (x, y), węzeł z NODES, "@ICAO" (środek symbolu lotniska) albo
("ICAO", x, y) / ("CTR ICAO", x, y) = punkt przyciągnięty do granicy obszaru TMA / CTR tego lotniska (do jej
wierzchołka, gdy bliżej niż SNAP_PX); między dwoma kolejnymi punktami przyciągniętymi do tej samej granicy linia
biegnie tą granicą (krótszą drogą).

Układ napisów (wszystko [lon, lat], środek napisu) jest ręczny i skrypt przenosi go z dotychczasowego pliku:
'num' i 'qnh_at' rejonów (duży numer i ramka z QNH obok niego), 'cap' i 'code' TMA (opis BELOW … QNH FROM EPxx
z QNH), "chart_labels" (szare oznaczenia TMA/CTR) i "aero_labels" (strona kodu ICAO przy symbolu lotniska).
--layout rozsuwa nachodzące na siebie napisy (model rozmiarów jak w qnh.css i test_qnh.py, wszystkie widoki
services.qnh.VIEWS) i zapisuje nowe miejsca; przesuwa tylko napisy, które na coś nachodzą, więc na pliku bez kolizji
nic nie zmienia (test_script_reproduces_seed).

Użycie (z katalogu głównego repozytorium):
    python scripts/trace_qnh_regions.py                          # zapis do data/seed/qnh_regions.json
    python scripts/trace_qnh_regions.py --out /tmp/qnh.json      # zapis do innego pliku (kontrola: diff)
    python scripts/trace_qnh_regions.py --overlay kontrola.png   # jak wyżej + nakładka geometrii na zrzucie
    python scripts/trace_qnh_regions.py --layout                 # jak wyżej + rozsunięcie napisów
    python scripts/trace_qnh_regions.py --fit                    # ponowne dopasowanie odwzorowania do siatki zrzutu

Po podmianie pliku .ese/.sct uruchom skrypt ponownie (test_qnh.py porównuje sumy kontrolne plików z "sources").
Wymaga: numpy i shapely, dla --overlay i --fit także Pillow (pip install numpy shapely pillow).
"""

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
IMPORT = ROOT / "data" / "import"
OUT = SEED / "qnh_regions.json"
IMAGE = IMPORT / "qnh_pansa.png"
SCT = IMPORT / "EPWW-Sector.sct"
ESE = IMPORT / "EPWW-Sector.ese"

# odwzorowanie Lamberta dopasowane do siatki zrzutu (--fit): piksel bieguna (xp, yp), stała stożka n,
# ln skali C (promień równoleżnika = C * t(φ)^n, elipsoida GRS80) i południk środkowy lon0
LCC = {"xp": 1880.394, "yp": -12592.290, "n": 0.7981264, "lnC": 10.3826669, "lon0": 19.002774}
E = 0.0818191910428  # mimośród GRS80
SNAP_PX = 4.0        # przyciąganie do wierzchołka granicy TMA/CTR (ok. 1,4 km)
LOW_FT = 9500        # warstwy TMA z pliku .ese poniżej FL095 (mapa QNH: QNH obowiązuje pod TMA)

# węzły wspólne kilku linii (piksele zrzutu); "F…" = koniec na granicy FIR (linia przedłużana do przecięcia z FIR),
# "@ICAO" = wierzchołek w punkcie lotniska (linie na mapie PAŻP przechodzą przez środek symbolu lotniska)
NODES = {
    "J1-2-3": ("EPGD", 1605.3, 584.3), "J1-3-4": (1444.8, 863.1), "J2-3-7-8": (1953.2, 865.2),
    "J3-4-8-9": (1904.2, 1049.9), "J8-9-10": ("EPWA", 2452.7, 1257.3), "J9-10-11-13": (2206.4, 1571.5),
    "J4-5-9": "@EPLK", "J5-9-11": (1932.8, 1579.9), "J11-12-13-14": (2150.5, 1861.2),
    "F1-2": (1279.5, 330.6), "F2-7": (2043.5, 494.9), "F7-8": (2786.1, 838.9), "F8-10": (2773.4, 1203.5),
    "F10-13": (2880.0, 1618.8), "F13-14": (2700.9, 1891.6), "F12-14": (2219.6, 2067.8), "F11-12": (1788.0, 1907.3),
    "F5-11": (1628.5, 1786.8), "F5-6s": (1475.9, 1741.2), "F5-6w": (1096.7, 1484.1), "F4-5": (1055.8, 1228.9),
    "F1-4": (1048.2, 1049.0),
}
# granice między rejonami: kolejne wierzchołki; 2/3 biegnie granicą TMA Gdańsk, 5/6 granicą TMA Wrocław,
# 8/9 granicą CTR Warszawa, 9/10 granicą TMA Warszawa (jak na mapie PAŻP); 3/4 i 4/9 przez lotniska EPIR i EPLY
LINES = {
    "1/2": ["F1-2", "J1-2-3"],
    "2/3": ["J1-2-3", ("EPGD", 1775.7, 726.2), "J2-3-7-8"],
    "1/3": ["J1-2-3", (1461.6, 700.6), "J1-3-4"],
    "1/4": ["F1-4", "J1-3-4"],
    "2/7": ["F2-7", "J2-3-7-8"],
    "3/4": ["J1-3-4", (1635.8, 947.8), "@EPIR", "J3-4-8-9"],
    "3/8": ["J2-3-7-8", "J3-4-8-9"],
    "7/8": ["J2-3-7-8", (2236.5, 933.2), "@EPGY", (2682.3, 860.0), "F7-8"],
    "8/9": ["J3-4-8-9", (2011.4, 1088.2), (2191.3, 1175.2), "@EPBC", ("CTR EPWA", 2266.3, 1172.2),
            ("CTR EPWA", 2298.4, 1208.7), (2309.2, 1251.4), "J8-9-10"],
    "8/10": ["J8-9-10", (2535.0, 1260.6), "F8-10"],
    "9/10": ["J8-9-10", ("EPWA", 2360.1, 1366.6), (2274.8, 1537.7), "J9-10-11-13"],
    "4/9": ["J3-4-8-9", "@EPLY", "J4-5-9"],
    "5/9": ["J4-5-9", "J5-9-11"],
    "4/5": ["F4-5", "J4-5-9"],
    "9/11": ["J5-9-11", (2044.0, 1576.5), "J9-10-11-13"],
    "10/13": ["J9-10-11-13", (2427.0, 1632.9), (2496.4, 1647.6), "F10-13"],
    "5/6": ["F5-6w", ("EPWR", 1356.9, 1574.0), ("EPWR", 1542.0, 1657.4), "F5-6s"],
    "5/11": ["J5-9-11", (1760.3, 1608.5), "F5-11"],
    "11/13": ["J9-10-11-13", "J11-12-13-14"],
    "11/12": ["F11-12", "J11-12-13-14"],
    "12/14": ["J11-12-13-14", "F12-14"],
    "13/14": ["J11-12-13-14", (2200.5, 1890.6), (2282.1, 1858.8), "F13-14"],
}
# środki numerów rejonów (piksele zrzutu: zielone 1–14, pomarańczowe 15–17) jak na mapie PAŻP (środek cyfr)
NUM = {1: (1478, 582.5), 2: (1506, 368.5), 3: (1606, 743.5), 4: (1228, 1045.5), 5: (1730, 1499.5), 6: (1421, 1701),
       7: (2455.5, 691.5), 8: (2392.5, 1051), 9: (2193.5, 1297.5), 10: (2706.5, 1302), 11: (1699.5, 1794.5),
       12: (2039, 2016), 13: (2276.5, 1722), 14: (2330, 1979.5), 15: (2662, 719.5), 16: (2656.5, 1040.5), 17: (2748, 1728)}
# lotniska z METAR-em, z których bierzemy najniższe QNH rejonu: leżące w rejonie, a leżące na granicy (EPLY, EPLK, EPBC,
# EPIR w wierzchołkach linii; na mapie PAŻP linia przechodzi przez symbol lotniska) we wszystkich stykających się
# rejonach; rejony 6, 12 i 14 nie mają własnego lotniska z METAR-em, więc biorą najbliższe (EPWR, EPKK, EPRZ);
# pasy 15–17 = wszystkie lotniska z METAR-em leżące w pasie
AIRPORTS = {
    1: ["EPSC", "EPSN", "EPMI", "EPDA"],
    2: ["EPGD", "EPOK", "EPPR", "EPCE", "EPMB"],
    3: ["EPBY", "EPIR"],
    4: ["EPPO", "EPKS", "EPPW", "EPZG", "EPIR", "EPLY", "EPLK"],
    5: ["EPWR", "EPLK"],
    6: ["EPWR"],
    7: ["EPSY"],
    8: ["EPMO", "EPMM", "EPBC"],
    9: ["EPWA", "EPLL", "EPTM", "EPRA", "EPLY", "EPLK", "EPBC"],
    10: ["EPLB", "EPDE"],
    11: ["EPKT", "EPKK"],
    12: ["EPKK"],
    13: ["EPRZ"],
    14: ["EPRZ"],
}
METAR = ("EPBC EPBY EPCE EPDA EPDE EPGD EPIR EPKK EPKS EPKT EPLB EPLK EPLL EPLY EPMB EPMI EPMM EPMO EPOK EPPO EPPR "
         "EPPW EPRA EPRZ EPSC EPSN EPSY EPTM EPWA EPWR EPZG").split()
BANDS = {15: (53.0, 90.0), 16: (51.0, 53.0), 17: (-90.0, 51.0)}

# TMA Kraków z pliku .ese (część zachodnia LTMA_W, wschodnia LTMA_E i sektory DEP) dzieli na obszary "QNH FROM EPKT"
# i "QNH FROM EPKK" pogrubiona linia z mapy PAŻP (od północnej granicy TMA do zachodniej); obszar lotniska = część,
# w której leży lotnisko
SPLIT = {("EPKT", "EPKK"): [(2017.6, 1600.0), (2015.0, 1681.7), (2012.3, 1768.3), (1913.3, 1839.3), (1780.0, 1839.3)]}

# części TMA, których brak w pliku .ese: TMA -> grupa [ARTCC] pliku .sct z jej obrysem; do obszaru dochodzi część
# obrysu, której nie pokrywa żadna warstwa TMA z pliku .ese (na dowolnej wysokości). TMA Łódź: w pliku .ese są
# części A, B, D i E_W, a części C (północnej, przy TMA Warszawa) nie ma - leży tam tylko CTA03 (od 5500 ft)
# i FIS, a na mapie PAŻP jest w obszarze "BELOW TMA QNH FROM EPLL". Pozostałe obrysy "… TMA OUT" sprawdzone:
# ich części poza warstwami poniżej FL095 to górne części TMA (EPGD_UTMA, EPKK_TMA_W/E, EPLB_TMA_F, EPRZ_TMA_D,
# EPPO_TMA_N_D, EPPO_TMA_S_G), a przy TMA Warszawa CTA01_N/S i EPWA_APP_S_G (od FL095) oraz CTA02_S - mapa PAŻP
# ich nie zalicza do obszarów BELOW TMA (test_tma_covers_sct_outline w test_qnh.py)
SCT_FILL = {"EPLL": "EPLL TMA OUT"}

# MTMA wojskowe bez danych w plikach sektorowych: obrys z mapy PAŻP (piksele zrzutu, kolejne wierzchołki);
# ("ICAO", x, y) = punkt na granicy TMA tego lotniska z pliku .ese (wspólny odcinek biegnie dokładnie po niej);
# części wspólne z TMA cywilną (np. kwadrat przy Malborku, pasek między TMA Poznań i MTMA Powidz) są na mapie
# ciemniejsze ("overlaps")
MIL_TMA = {
    "EPSN": [("EPSC", 1198.1, 624.2), ("EPSC", 1259.6, 781.5), (1285.0, 751.0), (1306.0, 745.0), (1361.7, 752.7),
             (1389.0, 746.0), (1392.0, 706.0), (1402.0, 704.0), (1409.0, 699.3), (1432.3, 684.3), (1399.0, 671.7),
             (1341.7, 646.7), (1220.0, 621.7)],
    "EPMI": [("EPSC", 1259.6, 781.5), (1285.0, 751.0), (1306.0, 745.0), (1361.7, 752.7), (1374.0, 782.7),
             (1425.0, 813.3), (1432.5, 863.0), (1403.8, 873.0), (1295.0, 845.8), (1268.8, 826.3)],
    "EPMB": [(1826.7, 619.3), (1853.3, 616.7), (1880.0, 586.7), (1928.3, 581.7), ("EPGD", 1924.3, 598.0),
             ("EPGD", 1949.4, 597.2), (1970.0, 599.3), (1993.3, 573.3), (2006.7, 635.0), (2021.7, 707.3),
             (1893.3, 742.7), ("EPGD", 1853.3, 676.4), (1826.7, 678.3)],
    "EPPW": [("EPPO", 1628.8, 1049.3), ("EPPO", 1570.9, 1124.1), ("EPPO", 1594.7, 1140.7), (1575.0, 1233.3),
             (1600.0, 1239.3), (1623.3, 1243.3), (1755.0, 1229.3), (1803.3, 1211.0), (1817.3, 1140.0),
             (1791.7, 1102.7)],
    "EPLK": [("EPLL", 1861.8, 1344.0), ("EPLL", 1995.2, 1363.3), (2010.0, 1407.3), (1991.7, 1468.3),
             (1948.3, 1516.7), (1930.0, 1532.7), (1851.7, 1517.3), (1800.7, 1389.0), (1833.3, 1356.0)],
    "EPMM": [(2340.7, 1132.7), ("EPWA", 2373.3, 1110.7), ("EPWA", 2426.0, 1110.3), (2470.0, 1107.3),
             (2488.3, 1085.0), (2560.0, 1091.7), (2581.7, 1094.0), (2575.0, 1136.7), (2586.7, 1183.3),
             (2526.7, 1198.3), (2511.7, 1220.0), (2383.3, 1226.7), (2381.7, 1208.3), (2370.0, 1209.3),
             (2350.7, 1190.0)],
}
# CTR z pliku .ese: nazwa na mapie -> sektory (suma, np. CTR Kraków dla obu kierunków pasa); "nazwa:ft" = tylko
# warstwa o tej dolnej granicy (CTR EDAH na mapie PAŻP = najniższa część TMA Szczecin nad podejściem do Heringsdorfu)
ESE_CTR = {
    "CTR EPGD": ["EPGD_CTR"], "CTR EPSC": ["EPSC_CTR"], "CTR EDAH": ["EPSC_TMA_EDAH:1000"], "CTR EPBY": ["EPBY_CTR"],
    "CTR EPSY": ["EPSY_CTR"], "CTR EPPO": ["EPPO_CTR"], "MCTR EPKS": ["EPKS_MCTR"], "CTR EPZG": ["EPZG_CTR"],
    "CTR EPWA": ["EPWA_CTR"], "CTR EPMO": ["EPMO_CTR"], "CTR EPLL": ["EPLL_CTR"], "CTR/MCTR EPRA": ["EPRA_CTR"],
    "MCTR EPDE": ["EPDE_MCTR"], "CTR EPLB": ["EPLB_CTR"], "CTR EPWR": ["EPWR_CTR"],
    "CTR EPKT": ["EPKT_CTR08", "EPKT_CTR26"], "CTR EPKK": ["EPKK_CTR07", "EPKK_CTR25"], "CTR EPRZ": ["EPRZ_CTR"],
}
# MCTR wojskowe bez danych w plikach sektorowych: obrys przerywanej linii (i szarego wypełnienia) z mapy PAŻP
# (piksele zrzutu); liczba = okrąg o tym promieniu (piksele) wokół lotniska
MIL_CTR = {
    "MCTR EPDA": [(1410.0, 441.7), (1451.7, 471.7), (1400.0, 530.0), (1370.0, 530.0), (1348.3, 515.0)],
    "MCTR EPOK": [(1728.3, 386.7), (1770.0, 378.3), (1866.7, 478.3), (1841.7, 500.0), (1793.3, 490.0),
                  (1766.7, 475.0), (1746.0, 428.3)],
    "MCTR EPCE": [(1609.0, 459.0), (1698.0, 454.0), (1705.0, 509.0), (1666.0, 534.0), (1595.0, 546.0), (1590.0, 500.0)],
    "MCTR EPPR": [(1785.0, 541.7), (1848.3, 533.3), (1875.0, 546.7), (1868.3, 576.7), (1833.3, 591.7), (1790.0, 581.7)],
    "MCTR EPMB": [(1852.0, 617.0), (1880.0, 587.0), (1928.0, 582.0), (1925.0, 601.0), (1973.0, 600.0),
                  (1973.0, 665.0), (1902.0, 672.0), (1852.0, 678.0)],
    "MCTR EPSN": [(1245.0, 624.0), (1342.0, 646.0), (1398.3, 671.7), (1375.0, 723.3), (1336.7, 746.7),
                  (1306.7, 743.3), (1211.7, 698.3), (1235.0, 650.0)],
    "MCTR EPMI": [(1310.0, 753.3), (1401.7, 821.7), (1390.0, 846.0), (1320.0, 845.0), (1268.3, 806.7)],
    # wydłużony ku EPIN (zachodnia część pod napisami EPIN i EPIR, wierzchołki z przedłużenia widocznych kresek)
    "MCTR EPIR": [(1724.5, 993.0), (1739.5, 981.5), (1752.0, 974.5), (1782.0, 972.5), (1789.5, 983.5),
                  (1757.0, 1020.5), (1745.0, 1020.5), (1727.0, 1006.5)],
    "MCTR EPPW": [(1611.7, 1070.7), (1721.7, 1116.0), (1701.7, 1186.0), (1618.3, 1156.7), (1570.7, 1122.7)],
    "MCTR EPLY": [(1874.0, 1228.0), (1925.0, 1236.0), (1930.0, 1262.0), (1905.0, 1272.0), (1872.0, 1262.0)],
    "MCTR EPLK": [(1860.0, 1345.0), (1930.0, 1369.3), (1980.0, 1390.0), (1961.7, 1459.3), (1836.7, 1421.3)],
    "MCTR EPMM": [(2348.3, 1158.3), (2443.3, 1150.0), (2462.0, 1200.0), (2392.0, 1207.0), (2370.0, 1209.3),
                  (2352.0, 1190.0)],
    "MCTR EPTM": [(2071.3, 1331.3), (2172.5, 1407.5), (2138.8, 1446.3), (2027.5, 1366.3)],
}

NOTE = ("Region QNH = lowest current QNH of the region's aerodromes (METAR); the official regional QNH is computed "
        "by IMGW from its model (lowest pressure in the region minus 3 hPa), so it may be lower. Regions 15–17 "
        "(bands split at 53°N and 51°N) are backup values, issued only when the IMGW model fails. Below a TMA/MTMA "
        "use the QNH of the aerodrome named in its BELOW … QNH FROM caption. TMA, CTR and FIR boundaries from the "
        "EPWW sector files; region lines, MTMA and MCTR not in the sector files traced from the PANSA QNH regions "
        "chart. For simulation use only.")
UWAGA = ("Plik generuje scripts/trace_qnh_regions.py (opis źródeł w skrypcie): granice rejonów, obszary TMA/MTMA, "
         "CTR/MCTR i FIR poprawiać w skrypcie i uruchomić go ponownie (także po podmianie plików sektorowych: "
         "'sources' = sha256 plików, test_qnh.py przypomni). Rejony: 'airports' = lotniska z METAR-em, QNH rejonu = "
         "najniższe z nich; 15-17 (band) = pasy awaryjne 53°N/51°N. TMA: 'ese' = przedrostki nazw sektorów pliku "
         ".ese (warstwy poniżej FL095), 'mil' = obrys MTMA z mapy PAŻP (brak w plikach sektorowych), 'area' = obszar "
         "BELOW ... QNH FROM, 'parts' = cienkie linie części TMA; QNH TMA = QNH z METAR-u lotniska 'icao'. 'ctrs' = "
         "CTR/MCTR ('src' ese albo chart), 'overlaps' = części wspólne obszarów TMA/MTMA (ciemniejsze). Układ "
         "napisów poprawiać ręcznie w tym pliku (skrypt go przenosi, --layout rozsuwa nachodzące): rejon 'num' = "
         "[lon, lat] środka numeru, 'qnh_at' = strona ramki QNH przy numerze (e, w, n, s, ne, nw, se, sw); TMA 'cap' = "
         "środek opisu BELOW ... QNH FROM EPxx z QNH, 'stack' = QNH w trzecim wierszu (węższy opis), 'code' = osobny "
         "napis 'EPxx QNH' (wtedy opis bez kodu), 'join' = "
         "lotniska z własnym napisem 'code' pod wspólnym opisem; 'chart_labels' = szare oznaczenia TMA/CTR ('lines' = "
         "wiersze); 'aero_labels' = strona kodu ICAO przy symbolu lotniska (domyślnie e). Brak nakładania napisów przy "
         "oknach 1600x900, 1600x789, 1366x768 i 1366x657 sprawdza test_label_layout w backend/tests/test_qnh.py. "
         "'note' = objaśnienie pod tabelami (po angielsku).")


def _t(phi: float) -> float:
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - E * s) / (1 + E * s)) ** (E / 2)


def to_px(lon: float, lat: float, p: dict = LCC) -> tuple[float, float]:
    r = math.exp(p["lnC"]) * _t(math.radians(lat)) ** p["n"]
    th = math.radians(lon - p["lon0"]) * p["n"]
    return p["xp"] + r * math.sin(th), p["yp"] + r * math.cos(th)


def to_lonlat(x: float, y: float, p: dict = LCC) -> tuple[float, float]:
    r = math.hypot(x - p["xp"], y - p["yp"])
    lon = p["lon0"] + math.degrees(math.atan2(x - p["xp"], y - p["yp"]) / p["n"])
    t = (r / math.exp(p["lnC"])) ** (1 / p["n"])
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(8):
        s = math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(t * ((1 - E * s) / (1 + E * s)) ** (E / 2))
    return lon, math.degrees(phi)


def file_sha256(path: Path) -> str:
    """sha256 treści z końcami wierszy LF (jak sources w sectors.geojson)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def airports() -> dict[str, tuple[float, float]]:
    with open(SEED / "airports.csv", encoding="utf-8") as f:
        return {r["ident"]: (float(r["longitude_deg"]), float(r["latitude_deg"])) for r in csv.DictReader(f)}


def fir_ring() -> list[tuple[float, float]]:
    """Granica FIR EPWW z pliku sektorowego jako zamknięty pierścień (lon, lat)."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    sys.path.insert(0, str(ROOT))
    from backend.app.importers.sct import parse_line_groups, read_text, sections

    if not SCT.exists():
        sys.exit(f"Brak pliku {SCT.relative_to(ROOT)} (granica FIR)")
    segs = parse_line_groups(sections(read_text(SCT)).get("[ARTCC HIGH]", []))["FIR border 0 - EPWW"]
    polys = list(polygonize(unary_union([LineString([(a[1], a[0]), (b[1], b[0])]) for a, b in segs if a != b])))
    return list(max(polys, key=lambda p: p.area).exterior.coords)


def sct_outline(name: str):
    """Obszar ograniczony grupą linii [ARTCC] pliku .sct (np. "EPLL TMA OUT") jako wielokąt shapely bez dziur."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union

    sys.path.insert(0, str(ROOT))
    from backend.app.importers.sct import parse_line_groups, read_text, sections

    segs = parse_line_groups(sections(read_text(SCT)).get("[ARTCC]", [])).get(name)
    if not segs:
        sys.exit(f"Brak grupy {name!r} w sekcji [ARTCC] pliku {SCT.relative_to(ROOT)}")
    faces = polygonize(unary_union([LineString([(a[1], a[0]), (b[1], b[0])]) for a, b in segs if a != b]))
    g = unary_union(list(faces))
    return unary_union([Polygon(p.exterior) for p in getattr(g, "geoms", [g])])


def ese_sectors() -> list[dict]:
    """Sektory pliku .ese EPWW (nazwa, FIR, granice pionowe, wielokąt lon/lat) jak w sectors.geojson."""
    sys.path.insert(0, str(ROOT))
    from backend.app.importers.sectors_geojson import epww_features

    if not ESE.exists():
        sys.exit(f"Brak pliku {ESE.relative_to(ROOT)} (TMA i CTR)")
    return [{**f["properties"], "geometry": f["geometry"]} for f in epww_features(ESE)]


def _poly(geom):
    """Wielokąt shapely z GeoJSON-a, poprawiony (buffer(0)) i bez dziur."""
    from shapely.geometry import Polygon, shape

    g = shape(geom).buffer(0)
    parts = getattr(g, "geoms", [g])
    from shapely.ops import unary_union
    return unary_union([Polygon(p.exterior) for p in parts])


class Snapper:
    """Przyciąganie wierzchołków do granic obszarów (TMA, CTR) i wstawianie odcinków tych granic."""

    def __init__(self):
        self.rings = {}

    def add(self, name: str, poly) -> None:
        from shapely.geometry import LineString

        parts = sorted(getattr(poly, "geoms", [poly]), key=lambda q: -q.area)
        self.rings[name] = LineString(parts[0].exterior.coords)

    def point(self, name: str, x: float, y: float) -> tuple[float, float]:
        """Punkt zrzutu (x, y) na granicy obszaru: wierzchołek granicy, gdy bliżej niż SNAP_PX, inaczej rzut."""
        from shapely.geometry import Point

        ring = self.rings[name]
        lon, lat = to_lonlat(x, y)
        best = min(ring.coords, key=lambda c: math.dist(to_px(*c), (x, y)))
        if math.dist(to_px(*best), (x, y)) < SNAP_PX:
            return tuple(best)
        p = ring.interpolate(ring.project(Point(lon, lat)))
        if math.dist(to_px(p.x, p.y), (x, y)) > 3 * SNAP_PX:
            sys.exit(f"Punkt ({x}, {y}) jest {math.dist(to_px(p.x, p.y), (x, y)):.0f} px od granicy {name}")
        return p.x, p.y

    def path(self, name: str, a: tuple, b: tuple) -> list[tuple[float, float]]:
        """Wierzchołki granicy obszaru między punktami a i b (bez nich), krótszą drogą."""
        from shapely.geometry import Point

        ring = self.rings[name]
        n = ring.length
        da, db = ring.project(Point(a)), ring.project(Point(b))
        coords = list(ring.coords)[:-1]
        cum = [0.0]
        for p, q in zip(coords, coords[1:] + coords[:1]):
            cum.append(cum[-1] + math.dist(p, q))

        def walk(d0, d1):   # wierzchołki o odległości w (d0, d1) wzdłuż pierścienia, z przejściem przez początek
            if d1 < d0:
                d1 += n
            out = []
            for k in (0, 1):
                for c, d in zip(coords, cum):
                    dd = d + k * n
                    if d0 + 1e-9 < dd < d1 - 1e-9:
                        out.append((dd, c))
            return [c for _, c in sorted(out)]
        fwd = walk(da, db)
        back = walk(db, da)[::-1]
        length = lambda pts: sum(math.dist(p, q) for p, q in zip([a] + pts, pts + [b]))  # noqa: E731
        return fwd if length(fwd) <= length(back) else back


def resolve(seq: list, snap: Snapper, ads: dict) -> list[tuple[float, float]]:
    """Wierzchołki (piksele, węzły, "@ICAO", przyciągnięte do granic) jako (lon, lat), z odcinkami granic TMA/CTR
    między kolejnymi punktami przyciągniętymi do tej samej granicy."""
    out, prev = [], None
    for v in seq:
        if isinstance(v, str) and v in NODES:
            v = NODES[v]
        if isinstance(v, str) and v.startswith("@"):
            pt, name = ads[v[1:]], None
        elif isinstance(v, tuple) and isinstance(v[0], str):
            name, pt = v[0], snap.point(v[0], v[1], v[2])
        else:
            pt, name = to_lonlat(*v), None
        if name and prev and prev[1] == name:
            out += snap.path(name, prev[0], pt)
        out.append(pt)
        prev = (pt, name)
    return out


def tma_areas(cfg: dict, secs: list[dict], ads: dict):
    """Obszary "BELOW … QNH FROM" (MultiPolygon) i cienkie linie części TMA dla każdej TMA z pliku rejonów,
    CTR/MCTR i części wspólne obszarów. Zwraca (areas, parts, ctrs, overlaps, snapper)."""
    from shapely.geometry import LineString, MultiLineString, Point, Polygon
    from shapely.ops import linemerge, polygonize, unary_union

    snap = Snapper()
    areas, parts, low = {}, {}, {}
    for t in cfg["tmas"]:
        if not t.get("ese"):
            continue
        layers = [s for s in secs if s["fir"] == "EPWW" and s["name"].startswith(tuple(t["ese"])) and s["lower_ft"] < LOW_FT]
        if not layers:
            sys.exit(f"{t['icao']}: brak sektorów {t['ese']} w pliku .ese")
        low[t["icao"]] = [(_poly(s["geometry"]), s["lower_ft"]) for s in layers]
        if t["icao"] in SCT_FILL:
            # część obrysu z pliku .sct, której nie ma w żadnej warstwie TMA z pliku .ese; dolna granica jak
            # w warstwie, z którą ma najdłuższą wspólną granicę (cienka linia tylko tam, gdzie granica się zmienia)
            every = unary_union([_poly(s["geometry"]) for s in secs
                                 if s["fir"] == "EPWW" and s["name"].startswith(tuple(t["ese"]))])
            gap = sct_outline(SCT_FILL[t["icao"]]).difference(every)
            for q in getattr(gap, "geoms", [gap]):
                if q.geom_type != "Polygon" or q.buffer(-0.002).is_empty:   # pomijamy drzazgi wzdłuż granic
                    continue
                edge = q.boundary.buffer(1e-4)
                ft = max(low[t["icao"]], key=lambda pf: pf[0].boundary.intersection(edge).length)[1]
                low[t["icao"]].append((Polygon(q.exterior), ft))
        areas[t["icao"]] = unary_union([p for p, _ in low[t["icao"]]])
        areas[t["icao"]] = unary_union([Polygon(p.exterior) for p in getattr(areas[t["icao"]], "geoms", [areas[t["icao"]]])])
    # TMA Kraków: część Katowic i część Krakowa
    for (west, east), seq in SPLIT.items():
        whole = areas[east]
        cut = LineString([to_lonlat(*p) for p in seq])
        pieces = list(polygonize(unary_union([whole.exterior, cut])))
        pieces = [q for q in pieces if whole.contains(q.representative_point())]
        a = unary_union([q for q in pieces if q.distance(Point(ads[west])) < q.distance(Point(ads[east]))])
        areas[west], areas[east] = a, whole.difference(a)
        low[west] = low[east]
    # drobne zakładki między sąsiednimi TMA z pliku .ese (inne współrzędne wspólnej granicy): część wspólna należy
    # do TMA wcześniejszej w pliku rejonów
    done = []
    for t in cfg["tmas"]:
        i = t["icao"]
        if i in areas:
            for j in done:
                if (i, j) not in SPLIT and (j, i) not in SPLIT and areas[i].intersection(areas[j]).area > 0:
                    areas[i] = areas[i].difference(areas[j]).buffer(0)
            done.append(i)
    for i, g in areas.items():
        snap.add(i, g)
    # cienkie linie: granice części o różnych dolnych granicach (najniższa granica w każdym punkcie), bez obrysu
    for i, g in areas.items():
        cells, below = [], None
        for ft in sorted({f for _, f in low[i]}):
            c = unary_union([p for p, f in low[i] if f == ft])
            cells.append(c if below is None else c.difference(below))
            below = c if below is None else unary_union([below, c])
        lines = unary_union([c.boundary for c in cells if not c.is_empty])
        inner = lines.intersection(g.buffer(-1e-5)) if not lines.is_empty else lines
        inner = linemerge(inner) if inner.geom_type in ("MultiLineString", "GeometryCollection") and not inner.is_empty \
            and all(q.geom_type == "LineString" for q in getattr(inner, "geoms", [])) else inner
        segs = [q for q in getattr(inner, "geoms", [inner]) if q.geom_type == "LineString" and q.length > 0.003]
        parts[i] = MultiLineString(segs) if segs else None
    # CTR z pliku .ese (przed MTMA: linie rejonów i obrysy mogą biec ich granicą)
    ctrs = []
    for name, names in ESE_CTR.items():
        g = unary_union([_poly(s["geometry"]) for s in secs if s["name"] in names or f"{s['name']}:{s['lower_ft']}" in names])
        if g.is_empty:
            sys.exit(f"{name}: brak sektorów {names} w pliku .ese")
        ctrs.append({"name": name, "src": "ese", "geometry": g})
        snap.add(name, g)
    # MTMA z mapy PAŻP
    for t in cfg["tmas"]:
        if t.get("mil"):
            ring = resolve(MIL_TMA[t["icao"]], snap, ads)
            areas[t["icao"]] = Polygon(ring).buffer(0)
            parts[t["icao"]] = None
    for name, spec in MIL_CTR.items():
        if isinstance(spec, float):
            x, y = to_px(*ads[name.split()[-1]])
            ring = [to_lonlat(x + spec * math.cos(k * math.pi / 18), y + spec * math.sin(k * math.pi / 18)) for k in range(36)]
        else:
            ring = [to_lonlat(*p) for p in spec]
        ctrs.append({"name": name, "src": "chart", "geometry": Polygon(ring)})
    keys = [t["icao"] for t in cfg["tmas"]]
    over = [areas[a].intersection(areas[b]) for n, a in enumerate(keys) for b in keys[n + 1:]]
    over = unary_union([q for o in over for q in getattr(o, "geoms", [o]) if q.geom_type == "Polygon" and q.area > 1e-6])
    return areas, parts, ctrs, over, snap


def build(fir: list, snap: Snapper, ads: dict, old: dict) -> tuple[list[dict], dict]:
    """Rejony z podziału FIR liniami LINES; old = dotychczasowe rejony (układ napisów: 'qnh_at')."""
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import polygonize, unary_union

    firp = Polygon(fir)
    edge = firp.exterior
    lines = []
    for name, seq in LINES.items():
        pts = resolve(seq, snap, ads)
        # koniec na granicy FIR: odcinek przedłużony do pierwszego przecięcia z granicą (wierzchołek FIR, gdy bliżej
        # niż ~50 m); pierwsze, a nie najbliższe końcowi, żeby linia nie wychodziła poza FIR przy narożniku granicy
        for end, prev in ((0, 1), (-1, -2)):
            v = seq[end]
            if isinstance(v, str) and v.startswith("F"):
                (x0, y0), (x1, y1) = pts[prev], pts[end]
                far = LineString([(x0, y0), (x1 + (x1 - x0) * 0.5, y1 + (y1 - y0) * 0.5)])
                hit = far.intersection(edge)
                cand = [hit] if hit.geom_type == "Point" else list(getattr(hit, "geoms", []))
                if not cand:
                    sys.exit(f"Linia {name}: koniec {v} nie przecina granicy FIR")
                p = min(cand, key=lambda q: q.distance(Point(x0, y0)))
                near = min(fir, key=lambda c: math.dist(c, (p.x, p.y)))
                pts[end] = near if math.dist(near, (p.x, p.y)) < 0.0005 else (p.x, p.y)
                # minimalnie za granicę, żeby polygonize na pewno połączyło linię z granicą FIR (końcówka za
                # granicą odpada, a wierzchołkiem rejonu jest punkt przecięcia leżący na granicy FIR)
                (x0, y0), (x1, y1) = pts[prev], pts[end]
                k = 0.0002 / math.dist((x0, y0), (x1, y1))
                pts[end] = (x1 + (x1 - x0) * k, y1 + (y1 - y0) * k)
        lines.append(LineString(pts))
    faces = [f for f in polygonize(unary_union([edge] + lines)) if firp.contains(f.representative_point())]
    if len(faces) != 14:
        sys.exit(f"Podział FIR dał {len(faces)} obszarów zamiast 14")
    prev = {r["id"]: r for r in old}
    regions = []
    for rid, (x, y) in sorted(NUM.items()):
        lon, lat = to_lonlat(x, y)
        reg = {"id": rid}
        if rid in BANDS:
            s, n = BANDS[rid]
            geom = firp.intersection(box(13, max(s, 48), 26, min(n, 56)))
            inside = [a for a in METAR if geom.contains(Point(ads[a]))]
            reg.update({"airports": inside, "band": True})
        else:
            hit = [f for f in faces if f.contains(Point(lon, lat))]
            if len(hit) != 1:
                sys.exit(f"Rejon {rid}: numer w {len(hit)} obszarach")
            geom = hit[0]
            reg["airports"] = AIRPORTS[rid]
        reg["num"] = prev.get(rid, {}).get("num") or _r((lon, lat), 3)
        reg["qnh_at"] = prev.get(rid, {}).get("qnh_at", "e")
        if geom.geom_type == "MultiPolygon":   # pas 17: także "worek turoszowski" na zachód od Bogatyni
            parts = sorted(geom.geoms, key=lambda q: -q.area)
            reg["geometry"] = {"type": "MultiPolygon", "coordinates": [[_ring(q, True)] for q in parts]}
        else:
            reg["geometry"] = {"type": "Polygon", "coordinates": [_ring(geom, rid in BANDS)]}
        regions.append(reg)
    return regions, {"type": "Polygon", "coordinates": [[_r(c) for c in fir]]}


def _r(c, nd: int = 5) -> list[float]:
    return [round(c[0], nd), round(c[1], nd)]


def _ring(geom, band: bool) -> list[list[float]]:
    """Zewnętrzny pierścień (lon, lat) w kierunku przeciwnym do wskazówek zegara, bez powtórzonych punktów; w pasach
    odcinki wzdłuż równoleżnika zagęszczone co 0,1°, żeby w odwzorowaniu stożkowym biegły łukiem jak na mapie."""
    from shapely.geometry.polygon import orient

    pts = list(orient(geom, 1.0).exterior.coords)
    out = []
    for a, b in zip(pts, pts[1:]):
        if not out or _r(a) != out[-1]:
            out.append(_r(a))
        if band and abs(a[1] - b[1]) < 1e-9 and abs(a[1] - round(a[1])) < 1e-9:
            k = int(abs(b[0] - a[0]) / 0.1)
            out += [_r((a[0] + (b[0] - a[0]) * i / (k + 1), a[1])) for i in range(1, k + 1)]
    out.append(out[0])
    return out


def _gj(g, nd: int = 5) -> dict | None:
    """Geometria shapely jako GeoJSON (MultiPolygon / MultiLineString) z zaokrąglonymi współrzędnymi."""
    if g is None or g.is_empty:
        return None
    if g.geom_type in ("Polygon", "MultiPolygon"):
        polys = [q for q in getattr(g, "geoms", [g]) if q.area > 1e-7]
        return {"type": "MultiPolygon", "coordinates": [[_dedup([_r(c, nd) for c in q.exterior.coords])] for q in polys]}
    lines = [q for q in getattr(g, "geoms", [g]) if q.geom_type == "LineString"]
    return {"type": "MultiLineString", "coordinates": [_dedup([_r(c, nd) for c in q.coords]) for q in lines]}


def _dedup(pts: list) -> list:
    out = []
    for p in pts:
        if not out or p != out[-1]:
            out.append(p)
    return out


def check(regions: list[dict], fir: dict, areas: dict) -> None:
    """Rejony 1–14 i pasy 15–17 pokrywają FIR bez dziur i nakładania; lotniska rejonów leżą w swoich rejonach."""
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union

    firp = shape(fir)
    ads = airports()
    for group in ([r for r in regions if not r.get("band")], [r for r in regions if r.get("band")]):
        polys = [shape(r["geometry"]) for r in group]
        union = unary_union(polys)
        over = sum(a.intersection(b).area for i, a in enumerate(polys) for b in polys[i + 1:])
        print(f"rejony {group[0]['id']}–{group[-1]['id']}: różnica z FIR {union.symmetric_difference(firp).area:.2e} "
              f"st.², nakładanie {over:.2e} st.²")
    for r in regions:
        g = shape(r["geometry"])
        inside = [a for a in METAR if g.buffer(0.002).contains(Point(ads[a]))]   # także na granicy rejonu
        out = [a for a in r["airports"] if a not in inside]
        print(f"{r['id']:>2}: lotniska z METAR-em w rejonie {' '.join(inside) or '–'}"
              f"{'; spoza rejonu: ' + ' '.join(out) if out else ''}")
    for i, g in areas.items():
        if not g.contains(Point(ads[i])) and g.distance(Point(ads[i])) > 0.02:
            print(f"{i}: lotnisko poza swoim obszarem TMA ({g.distance(Point(ads[i])):.3f}°)")


def overlay(out: str, cfg: dict) -> None:
    """Geometria z pliku narysowana na zrzucie (rejony magenta, pasy pomarańczowe, obszary TMA niebieskie, cienkie
    linie TMA granatowe, CTR czerwone, numery w kółkach, opisy BELOW zielone, szare oznaczenia krzyżykami) – do
    kontroli wzrokowej."""
    from PIL import Image, ImageDraw

    im = Image.open(IMAGE).convert("RGB")
    d = ImageDraw.Draw(im)
    polys = lambda g: [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]  # noqa: E731
    for t in cfg["tmas"]:
        for poly in polys(t["area"]):
            d.line([to_px(*c) for c in poly[0]], fill=(0, 90, 255), width=3)
        for line in (t.get("parts") or {}).get("coordinates", []):
            d.line([to_px(*c) for c in line], fill=(0, 0, 120), width=1)
    for c in cfg["ctrs"]:
        for poly in polys(c["geometry"]):
            d.line([to_px(*p) for p in poly[0]], fill=(220, 0, 0), width=2)
    for r in cfg["regions"]:
        for poly in polys(r["geometry"]):
            d.line([to_px(*c) for c in poly[0]], fill=(255, 140, 0) if r.get("band") else (230, 0, 230),
                   width=2 if r.get("band") else 3)
        x, y = to_px(*r["num"])
        d.ellipse((x - 6, y - 6, x + 6, y + 6), outline=(0, 0, 255), width=2)
    for t in cfg["tmas"]:
        for k in ("cap", "code"):
            if t.get(k):
                x, y = to_px(*t[k])
                d.rectangle((x - 80, y - 18, x + 80, y + 18), outline=(0, 150, 0), width=2)
    for c in cfg.get("chart_labels", []):
        x, y = to_px(*c["lonlat"])
        d.line((x - 8, y, x + 8, y), fill=(120, 120, 120), width=2)
        d.line((x, y - 8, x, y + 8), fill=(120, 120, 120), width=2)
    im.save(out)
    print(f"nakładka: {out}")


def fit(image: str) -> None:
    """Dopasowanie odwzorowania do siatki zrzutu: szare piksele południków 14–24°E i równoleżników 50–55°N."""
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(image).convert("RGB")).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    grey = (abs(r - g) < 10) & (abs(g - b) < 10) & (r > 110) & (r < 225)
    ys, xs = np.nonzero(grey[45:2150, 905:2936])
    ys, xs = ys + 45.0, xs + 905.0
    p0 = np.array([LCC["xp"], LCC["yp"], LCC["n"], LCC["lnC"], LCC["lon0"]])

    def inv(p, x, y):
        rr = np.hypot(x - p[0], y - p[1])
        lon = p[4] + np.degrees(np.arctan2(x - p[0], y - p[1]) / p[2])
        t = (rr / np.exp(p[3])) ** (1 / p[2])
        phi = np.pi / 2 - 2 * np.arctan(t)
        for _ in range(6):
            s = np.sin(phi)
            phi = np.pi / 2 - 2 * np.arctan(t * ((1 - E * s) / (1 + E * s)) ** (E / 2))
        return lon, np.degrees(phi)

    # punkty siatki: piksele leżące (wg bieżącego odwzorowania) blisko pełnego stopnia długości albo szerokości
    lon, lat = inv(p0, xs, ys)
    dlon, dlat = lon - np.round(lon), lat - np.round(lat)
    mer = (np.abs(dlon) * 200 < 2) & (np.round(lon) >= 14) & (np.round(lon) <= 24)
    par = (np.abs(dlat) * 313 < 2) & (np.round(lat) >= 50) & (np.round(lat) <= 55) & ~mer
    P = np.r_[np.c_[xs[mer], ys[mer], np.zeros(mer.sum()), np.round(lon[mer])],
              np.c_[xs[par], ys[par], np.ones(par.sum()), np.round(lat[par])]]

    def res(p):
        lo, la = inv(p, P[:, 0], P[:, 1])
        return np.where(P[:, 2] == 0, (lo - P[:, 3]) * 200, (la - P[:, 3]) * 313)

    p = p0.copy()
    for _ in range(20):
        r0 = res(p)
        jac = np.stack([(res(p + np.eye(5)[k] * 1e-6 * max(1, abs(p[k]))) - r0) / (1e-6 * max(1, abs(p[k])))
                        for k in range(5)], 1)
        p = p + np.linalg.lstsq(jac, -r0, rcond=None)[0]
    r0 = res(p)
    print(f"punkty siatki: {len(P)}, błąd średni {np.sqrt((r0 ** 2).mean()):.2f} px")
    print("LCC =", {k: round(float(v), 7) for k, v in zip(("xp", "yp", "n", "lnC", "lon0"), p)})


def _unpx(x: float, y: float, zoom: float) -> list[float]:
    """Odwrotność services.qnh.px(): [lon, lat] piksela mapy przy zoomie (kula, stożek jak lccCrs() w qnhmap.js)."""
    from backend.app.services.qnh import LCC_N, LCC_R

    d = math.pi / 180
    tn = lambda phi: math.tan(math.pi / 4 + phi / 2) ** LCC_N   # noqa: E731
    f = math.cos(math.asin(LCC_N)) * tn(math.asin(LCC_N)) / LCC_N
    s = 0.5 / (math.pi * LCC_R) * 256 * 2 ** zoom
    mx, my = x / s, LCC_R * f / tn(52 * d) + y / s
    r = math.hypot(mx, my)
    lat = 2 * math.atan((LCC_R * f / r) ** (1 / LCC_N)) - math.pi / 2
    return [round(19 + math.atan2(mx, my) / LCC_N / d, 3), round(lat / d, 3)]


# przesunięcia napisu przy rozsuwaniu (px przy zoomie 7,5), od najmniejszego (w pionie drożej: napisy są szerokie)
NUDGE = sorted(((dx * 1.5, dy * 1.5) for dx in range(-24, 25) for dy in range(-16, 17)),
               key=lambda p: (math.hypot(p[0], p[1] * 1.3), abs(p[1])))
NUM_NUDGE = [p for p in NUDGE if math.hypot(*p) <= 15]
NUM_SIDES = ("e", "w", "n", "s", "ne", "se", "nw", "sw")
AERO_SIDES = ("e", "w", "se", "ne", "sw", "nw", "s", "n")


def relayout(cfg: dict, ads: dict) -> None:
    """Rozsuwa napisy we wszystkich domyślnych widokach (services.qnh.VIEWS, model jak w test_qnh.py), tak żeby się
    nie nakładały: przesuwa tylko napisy, które nachodzą na inne (napis, który tylko przecina linię, zostaje na swoim
    miejscu z mapy PAŻP), a nowe miejsce wybiera tak, żeby nie nachodziło na inne napisy i, o ile się da, nie
    przecinało granic rejonów, linii 53°N/51°N, granicy FIR i obrysów TMA: numer rejonu z ramką QNH (najpierw inna
    strona ramki, potem przesunięcie numeru do 15 px), opisy BELOW, kody 'code' i szare oznaczenia przesunięte
    najmniej, jak się da, kod ICAO lotniska na wolnej stronie symbolu. Na pliku bez kolizji nic nie zmienia."""
    from shapely.geometry import MultiLineString
    from shapely.geometry import box as rect
    from shapely.prepared import prep

    from backend.app.services.qnh import VIEWS, clash, drawn_aerodromes, label_boxes, px

    metar = {a for r in cfg["regions"] for a in r["airports"]} | {t["icao"] for t in cfg["tmas"]}
    rows = [{"icao": k, "lon": v[0], "lat": v[1]} for k, v in ads.items() if k.startswith("EP")]
    sides = cfg.setdefault("aero_labels", {})
    zooms = list(VIEWS.values())
    empty = {"regions": [], "tmas": [], "chart_labels": []}
    polys = lambda g: [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]  # noqa: E731
    # linie, których napisy nie powinny przecinać: granice rejonów 1–14 (z granicą FIR), linie 53°N i 51°N
    # i pogrubione obrysy obszarów TMA/MTMA
    lines = [p[0] for r in cfg["regions"] if not r.get("band") for p in polys(r["geometry"])]
    lines += [ring for t in cfg["tmas"] if t.get("area") for p in polys(t["area"]) for ring in p]
    lines += [[(14 + i / 10, par) for i in range(103)] for par in (51, 53)]   # równoleżnik = łuk, co 0,1°
    # linia z otoczką ma ok. 4,5 px, więc napis trzyma się 2,5 px od osi linii
    lines_px = [prep(MultiLineString([[px(*c, z) for c in ln] for ln in lines]).buffer(2.5)) for z in zooms]

    def boxes(item_cfg: dict, aero: list) -> list[list]:
        return [label_boxes({**empty, **item_cfg}, aero, z) for z in zooms]

    items = {("r", r["id"]): (lambda r=r: ({"regions": [r]}, [])) for r in cfg["regions"]}
    items |= {("t", t["icao"]): (lambda t=t: ({"tmas": [t]}, [])) for t in cfg["tmas"]}
    items |= {("d", i): (lambda c=c: ({"chart_labels": [c]}, [])) for i, c in enumerate(cfg.get("chart_labels", []))}
    ad_list = lambda: drawn_aerodromes(rows, metar, sides)  # noqa: E731
    cur: dict = {}
    for key, fn in items.items():
        cur[key] = boxes(*fn())
    for a in ad_list():
        cur[("a", a["icao"])] = boxes({}, [a])

    def near(key, own: list[list], reach: float = 90) -> list[list]:
        """Napisy innych elementów w promieniu reach px od napisów elementu (do szybszego liczenia kolizji)."""
        out = []
        for zi, mine in enumerate(own):
            x0, y0 = min(b[2][0] for b in mine) - reach, min(b[2][1] for b in mine) - reach
            x1, y1 = max(b[2][2] for b in mine) + reach, max(b[2][3] for b in mine) + reach
            out.append([b for k2, other in cur.items() if k2 != key for b in other[zi]
                        if b[2][0] < x1 and b[2][2] > x0 and b[2][1] < y1 and b[2][3] > y0])
        return out

    def cost(own: list[list], nbrs: list[list], skip: tuple = ()) -> tuple[int, int]:
        """(kolizje z innymi napisami, przecięcia linii); skip: rodzaje napisów pomijane (ustawiane później)."""
        hit = cross = 0
        for zi, mine in enumerate(own):
            for a in mine:
                hit += sum(clash(a, b) for b in nbrs[zi] if b[0] not in skip)
                if a[0] != "sym":
                    cross += lines_px[zi].intersects(rect(*a[2]))
        return hit, cross

    def place(key, variants, skip: tuple = ()) -> None:
        """variants: (opis, funkcja ustawiająca wariant), pierwszy = obecne miejsce; wybór pierwszego (najbliższego)
        bez kolizji i bez przecięć linii ponad te, które napis ma w obecnym miejscu, inaczej najlepszego."""
        fn = items.get(key)
        nbrs = near(key, cur[key])
        best = base = None
        for i, (label, apply) in enumerate(variants):
            apply()
            own = boxes(*fn()) if fn else boxes({}, [next(a for a in ad_list() if a["icao"] == key[1])])
            hit, cross = cost(own, nbrs, skip)
            base = cross if base is None else base
            c = (hit, max(0, cross - base))
            if best is None or c < best[0]:
                best = (c, i, label, apply, own)
            if c == (0, 0):
                break
        best[3]()
        cur[key] = best[4]
        if best[1]:
            print(f"  {key[1]}: {best[2]}" + (f" (kolizje {best[0][0]}, przecięcia {best[0][1]})" if any(best[0]) else ""))

    def shifts(obj: dict, field: str, offsets) -> list:
        base = obj[field]
        x0, y0 = px(*base, zooms[0])

        def at(dx, dy):
            return lambda: obj.__setitem__(field, _unpx(x0 + dx, y0 + dy, zooms[0]) if (dx or dy) else base)
        return [(f"{field} {dx:+.1f}, {dy:+.1f} px", at(dx, dy)) for dx, dy in offsets]

    def clashes(key, skip: tuple = (), kind: str | None = None) -> bool:
        """Czy napisy elementu (tylko rodzaju kind, np. 'code') nachodzą na inne (przecięcia linii nie liczą się:
        napis z mapy PAŻP zostaje na miejscu)."""
        own = [[b for b in mine if kind is None or b[0] == kind] for mine in cur[key]]
        return cost(own, near(key, cur[key]), skip)[0] > 0

    # kolejność: opisy BELOW i kody 'code' (najbliżej miejsc z mapy PAŻP), szare oznaczenia, numery rejonów z ramką
    # QNH, kody lotnisk; w pierwszej rundzie każdy pomija napisy ustawiane po nim
    for rnd in range(4):
        later = lambda *kinds: kinds if rnd == 0 else ()  # noqa: E731
        for t in cfg["tmas"]:
            key = ("t", t["icao"])
            for field in ("cap", "code"):
                if t.get(field) and clashes(key, later("qnh", "aero"), field):
                    place(key, shifts(t, field, NUDGE), later("qnh", "aero"))
        for i, c in enumerate(cfg.get("chart_labels", [])):
            key = ("d", i)
            if clashes(key, later("qnh", "aero")):
                place(key, shifts(c, "lonlat", NUDGE), later("qnh", "aero"))
        for r in cfg["regions"]:
            key = ("r", r["id"])
            if not clashes(key, later("aero")):
                continue
            keep = r.get("qnh_at", "e")
            order = (keep, *[s for s in NUM_SIDES if s != keep])
            near_ = shifts(r, "num", [p for p in NUM_NUDGE if math.hypot(*p) <= 8])
            far = shifts(r, "num", NUM_NUDGE)

            def both(shift, side):
                return lambda: (shift(), r.__setitem__("qnh_at", side))
            # ramka po tej samej stronie co zwykle (e, potem w, n, s) z przesunięciem numeru do 8 px, dopiero potem
            # inne strony i dalsze przesunięcia
            variants = [(f"{lab}, QNH {side}", both(sh, side)) for side in order[:4] for lab, sh in near_]
            variants += [(f"{lab}, QNH {side}", both(sh, side)) for lab, sh in far for side in order]
            place(key, variants, later("aero"))
        for a in ad_list():
            key = ("a", a["icao"])
            if not clashes(key):
                continue
            order = (a["label"], *[s for s in AERO_SIDES if s != a["label"]])
            place(key, [(f"kod {s}", lambda s=s, i=a["icao"]: sides.__setitem__(i, s)) for s in order])
        total = [0, 0]
        for key, own in cur.items():
            c = cost(own, near(key, own))
            total[0] += c[0]
            total[1] += c[1]
        print(f"runda {rnd + 1}: kolizje {total[0] // 2}, przecięcia linii {total[1]}")
        if total[0] == 0 and rnd:
            break
    cfg["aero_labels"] = {k: v for k, v in sorted(sides.items()) if v != "e"}


def dump(cfg: dict) -> str:
    """Tekst pliku: jeden rejon / jedna TMA / jeden CTR / jeden napis w wierszu."""
    def val(k, v):
        sep = (", ", ": ") if k in ("chart_labels",) else (",", ":")
        if isinstance(v, list):
            return "[\n" + ",\n".join(json.dumps(x, ensure_ascii=False, separators=sep) for x in v) + "\n]"
        if k in ("aero_labels", "sources"):
            return "{" + ",".join(f"\n {json.dumps(a)}: {json.dumps(b)}" for a, b in v.items()) + "\n}"
        return json.dumps(v, ensure_ascii=False, separators=(", ", ": ") if isinstance(v, str) else sep)

    return "{" + ",\n".join(f'"{k}": {val(k, v)}' for k, v in cfg.items()) + "}\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--overlay", help="zapisz nakładkę geometrii na zrzucie mapy PAŻP do tego pliku PNG")
    ap.add_argument("--layout", action="store_true", help="rozsuń nachodzące na siebie napisy")
    ap.add_argument("--fit", action="store_true", help="dopasuj odwzorowanie do siatki zrzutu i wypisz parametry")
    ap.add_argument("--dry-run", action="store_true", help="bez zapisu pliku JSON")
    ap.add_argument("--out", default=str(OUT), help="plik wynikowy (domyślnie data/seed/qnh_regions.json); "
                    "TMA i układ napisów zawsze z data/seed/qnh_regions.json")
    args = ap.parse_args()
    if args.fit:
        fit(str(IMAGE))
        return
    from shapely.geometry import Polygon

    cfg = json.loads(OUT.read_text("utf-8"))
    ads = airports()
    fir = fir_ring()
    areas, parts, ctrs, over, snap = tma_areas(cfg, ese_sectors(), ads)
    regions, fir_gj = build(fir, snap, ads, cfg.get("regions", []))
    check(regions, fir_gj, areas)
    firp = Polygon(fir)
    tmas = []
    for t in cfg["tmas"]:
        keep = {k: v for k, v in t.items() if k not in ("area", "parts", "aip", "sct", "box", "short")}
        tmas.append({**keep, "area": _gj(areas[t["icao"]]), "parts": _gj(parts[t["icao"]])})
    out = {"_uwaga": UWAGA, "note": NOTE,
           "sources": {p.relative_to(ROOT).as_posix(): file_sha256(p) for p in (SCT, ESE)},
           "regions": regions, "tmas": tmas,
           "ctrs": [{"name": c["name"], "src": c["src"], "geometry": _gj(c["geometry"])} for c in ctrs],
           "overlaps": _gj(over), "chart_labels": cfg.get("chart_labels", []),
           "aero_labels": dict(sorted(cfg.get("aero_labels", {}).items())), "fir": fir_gj}
    if not firp.is_valid:
        sys.exit("Granica FIR nie jest poprawnym wielokątem")
    if args.layout:
        relayout(out, ads)
    if args.overlay:
        overlay(args.overlay, out)
    if args.dry_run:
        return
    Path(args.out).write_text(dump(out), "utf-8")
    print(f"zapisano {args.out}")


if __name__ == "__main__":
    main()
