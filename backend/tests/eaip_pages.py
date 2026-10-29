"""0.12.6 (issue #21): strony AD 2 eAIP do testów listy map (AD CIV), w układzie prawdziwych stron PAŻP (AIRAC AMDT 10-26).

Cała treść strony AD 2 jest w tabeli układu (każdy nagłówek i akapit to wiersz, puste wiersze wokół nagłówków sekcji),
a tabela map AD 2.24 ("Charts | Pages") jest osobną tabelą wewnątrz komórki tej tabeli; w wierszu mapy: komórka
z tytułem i komórka z odnośnikiem do PDF-u (sama ikona, bez tekstu i bez alt). Parser z 0.12.5 sklejał wtedy wszystkie
tytuły w jeden (wszystkie 37 map EPWA z tym samym tytułem i rodzajem OBST, zrzut w issue #21).

Tytuły i pliki EPWA jak w eAIP (zrzut z issue #21 i strony serii map AD 2 EPWA <n>-en-GB.html: strona AD 2 EPWA jest
za długa dla narzędzia, którym ją czytaliśmy). EPBY, EPLL, EPZG: tytuły jak na stronach PAŻP. Tytuły są wstawiane do
HTML-a bez zmian, więc "&" jest zapisane jako "&amp;" (jak na stronie)."""

PKG = "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/"


def page_url(icao: str) -> str:
    return PKG + f"eAIP/AD%202%20{icao}%201-en-GB.html"


def pdf(icao: str, folder: str, page: str) -> str:
    """Odnośnik jak na stronie (względny, ze spacją w "AIP IFR")."""
    return f"../documents/Root_WePub/AIP IFR/AD/{icao}/{folder}/AD_2_{icao}_{page}.pdf"


def docs(icao: str, folder: str, page: str) -> str:
    """Adres PDF-u po rozwinięciu przez parser (spacja → %20)."""
    return PKG + f"documents/Root_WePub/AIP%20IFR/AD/{icao}/{folder}/AD_2_{icao}_{page}.pdf"


IAC = "INSTRUMENT APPROACH CHART - ICAO"
SID = "STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO"
STAR = "STANDARD ARRIVAL CHART INSTRUMENT (STAR) - ICAO"
APDC = "AIRCRAFT PARKING, DOCKING CHART - ICAO"

# (tytuł, katalog, strona, oczekiwana krótka nazwa, oczekiwany rodzaj)
EPWA = [
    ("EPWA - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    ("EPWA - AERODROME CHART AREAS OF RESPONSIBILITY", "03", "3-1", "AREAS OF RESPONSIBILITY", "ADC"),
    (f"EPWA - {APDC} (APN 1,7A,7B,9)", "04", "4-1", "PARKING APN 1, 7A, 7B, 9", "APDC"),
    (f"EPWA - {APDC} (APN 3,5A,5B,5C)", "04", "4-3", "PARKING APN 3, 5A, 5B, 5C", "APDC"),
    (f"EPWA - {APDC} (APN 12,13,CARGO)", "04", "4-5", "PARKING APN 12, 13, CARGO", "APDC"),
    (f"EPWA - {APDC} (APN 10)", "04", "4-7", "PARKING APN 10", "APDC"),
    (f"EPWA - {APDC} (APN 9, MIL APN)", "04", "4-9", "PARKING APN 9, MIL APN", "APDC"),
    (f"EPWA - {APDC} (APN 2)", "04", "4-11", "PARKING APN 2", "APDC"),
    ("EPWA - AERODROME GROUND MOVEMENT CHART (TWYs FOR A380-800, AN-124-100, B747-8, C-5B GALAXY)", "05", "5-1",
     "GROUND MOVEMENT (A380-800, AN-124-100, B747-8, C-5B GALAXY)", "ADC"),
    ("EPWA - AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 11, RWY 29)", "06", "6-1", "OBSTACLE TYPE A RWY 11/29", "OBST"),
    ("EPWA - AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 15, RWY 33)", "06", "6-3", "OBSTACLE TYPE A RWY 15/33", "OBST"),
    ("EPWA - PRECISION APPROACH TERRAIN CHART - ICAO (RWY 11)", "07", "7-1", "PATC RWY 11", "OBST"),
    ("EPWA - PRECISION APPROACH TERRAIN CHART - ICAO (RWY 33)", "07", "7-3", "PATC RWY 33", "OBST"),
    (f"EPWA - {SID} (RNAV RWY 11)", "08", "08-1", "RWY 11 SID", "SID"),
    (f"EPWA - {SID} (RNAV RWY 15)", "08", "08-5", "RWY 15 SID", "SID"),
    (f"EPWA - {SID} (RNAV RWY 29)", "08", "08-9", "RWY 29 SID", "SID"),
    (f"EPWA - {SID} (RNAV RWY 33)", "08", "08-13", "RWY 33 SID", "SID"),
    (f"EPWA - {STAR} (RNAV RWY 11)", "10", "10-1", "RWY 11 STAR", "STAR"),
    (f"EPWA - {STAR} (RNAV RWY 15)", "10", "10-5", "RWY 15 STAR", "STAR"),
    (f"EPWA - {STAR} (RNAV RWY 29)", "10", "10-9", "RWY 29 STAR", "STAR"),
    (f"EPWA - {STAR} (RNAV RWY 33)", "10", "10-13", "RWY 33 STAR", "STAR"),
    (f"EPWA - {IAC} (ILS z CAT II or LOC z) RWY 11 (CAT A,B,C,D)", "12", "12-1", "RWY 11 ILS Z CAT II / LOC Z", "IAC"),
    (f"EPWA - {IAC} (ILS y CAT II) RWY 11 (CAT A,B,C,D)", "12", "12-3", "RWY 11 ILS Y CAT II", "IAC"),
    (f"EPWA - {IAC} (ILS z CAT II &amp; III or LOC z) RWY 33 (CAT A,B,C,D)", "12", "12-5",
     "RWY 33 ILS Z CAT II & III / LOC Z", "IAC"),
    (f"EPWA - {IAC} (ILS y CAT II &amp; III) RWY 33 (CAT A,B,C,D)", "12", "12-7", "RWY 33 ILS Y CAT II & III", "IAC"),
    (f"EPWA - {IAC} (ILS x CAT II &amp; III or LOC x) RWY 33 (CAT A,B,C,D)", "12", "12-9",
     "RWY 33 ILS X CAT II & III / LOC X", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 11 (CAT A,B,C,D)", "12", "12-11", "RWY 11 VOR", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 15 (CAT A,B,C,D)", "12", "12-13", "RWY 15 VOR", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 29 (CAT A,B,C,D)", "12", "12-15", "RWY 29 VOR", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 33 (CAT A,B,C,D)", "12", "12-17", "RWY 33 VOR", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 11 (CAT A,B,C,D)", "12", "12-19", "RWY 11 RNP", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 15 (CAT A,B,C,D)", "12", "12-23", "RWY 15 RNP", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 29 (CAT A,B,C,D)", "12", "12-27", "RWY 29 RNP", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 33 (CAT A,B,C,D)", "12", "12-31", "RWY 33 RNP", "IAC"),
    # dwie mapy o tym samym tytule
    ("EPWA - VFR ARRIVAL, DEPARTURE AND TRANSIT ROUTES", "13", "13-1", "VFR ARRIVAL, DEPARTURE AND TRANSIT ROUTES (1/2)",
     "VFR"),
    ("EPWA - VFR ARRIVAL, DEPARTURE AND TRANSIT ROUTES", "13", "13-3", "VFR ARRIVAL, DEPARTURE AND TRANSIT ROUTES (2/2)",
     "VFR"),
    ("EPWA - BIRD CONCENTRATIONS", "14", "14-1", "BIRD CONCENTRATIONS", "OTHER"),
]

# EPBY: SID konwencjonalne i RNP dla tej samej drogi startowej, tytuły z przedrostkiem i bez, "CHART - INSTRUMENT"
SID_BY = "STANDARD DEPARTURE CHART - INSTRUMENT (SID) - ICAO"
STAR_BY = "STANDARD ARRIVAL CHART - INSTRUMENT (STAR) - ICAO"
EPBY = [
    ("EPBY - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    ("EPBY - AIRCRAFT PARKING CHART - ICAO (APN 1,2,4, TWY E1, E3)", "04", "4-1", "PARKING APN 1, 2, 4, TWY E1, E3", "APDC"),
    ("EPBY - AIRCRAFT PARKING CHART - ICAO (TWY E2)", "04", "4-3", "PARKING TWY E2", "APDC"),
    ("EPBY - AERODROME GROUND MOVEMENT CHART - ICAO", "05", "5-1", "GROUND MOVEMENT", "ADC"),
    ("EPBY - AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 08, RWY 26)", "06", "6-1", "OBSTACLE TYPE A RWY 08/26", "OBST"),
    (f"{SID_BY} (RWY 08)", "08", "08-1", "RWY 08 SID", "SID"),
    (f"{SID_BY} (RWY 26)", "08", "08-3", "RWY 26 SID", "SID"),
    (f"EPBY - {SID_BY} (RNP RWY 08)", "08", "08-5", "RWY 08 RNP SID", "SID"),
    (f"EPBY - {SID_BY} (RNP RWY 26)", "08", "08-7", "RWY 26 RNP SID", "SID"),
    (f"{STAR_BY} (RWY 08, RWY 26)", "10", "10-1", "RWY 08/26 STAR", "STAR"),
    # STAR konwencjonalna dla obu dróg startowych i RNP dla każdej osobno: RNP w nazwie
    (f"EPBY - {STAR_BY} (RNP RWY 08)", "10", "10-3", "RWY 08 RNP STAR", "STAR"),
    (f"EPBY - {STAR_BY} (RNP RWY 26)", "10", "10-5", "RWY 26 RNP STAR", "STAR"),
    (f"EPBY - {IAC} (ILS z) RWY 26 (CAT A,B,C,D)", "12", "12-1", "RWY 26 ILS Z", "IAC"),
    (f"EPBY - {IAC} (ILS y or LOC y) RWY 26 (CAT A/B/C/D)", "12", "12-3", "RWY 26 ILS Y / LOC Y", "IAC"),
    (f"EPBY - {IAC} (VOR z) RWY 08 (CAT A/B/C/D)", "12", "12-5", "RWY 08 VOR Z", "IAC"),
    (f"EPBY - {IAC} (VOR y) RWY 08 (CAT A/B/C/D)", "12", "12-7", "RWY 08 VOR Y", "IAC"),
    (f"EPBY - {IAC} (VOR) RWY 26 (CAT A/B/C/D)", "12", "12-9", "RWY 26 VOR", "IAC"),
    (f"EPBY - {IAC} (RNP) RWY 08 (CAT A/B/C/D)", "12", "12-11", "RWY 08 RNP", "IAC"),
    (f"EPBY - {IAC} (RNP) RWY 26 (CAT A/B/C/D)", "12", "12-15", "RWY 26 RNP", "IAC"),
    ("EPBY - VFR ARRIVAL AND DEPARTURE ROUTES", "13", "13-1", "VFR ARRIVAL AND DEPARTURE ROUTES", "VFR"),
]

# EPLL: droga startowa poza nawiasem i w nawiasie, CAT bez nawiasu, dwie mapy o tym samym tytule, mapa obszaru TMA
EPLL = [
    ("AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    ("AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 07, RWY 25)", "06", "6-1", "OBSTACLE TYPE A RWY 07/25", "OBST"),
    (f"EPLL - {SID} (RNP) RWY 07", "08", "08-1", "RWY 07 SID", "SID"),
    (f"EPLL - {SID} (RNP) RWY 25", "08", "08-5", "RWY 25 SID (1/2)", "SID"),
    (f"EPLL - {SID} (RNP) RWY 25", "08", "08-9", "RWY 25 SID (2/2)", "SID"),
    ("EPLL - AREA CHART ICAO - ARRIVAL AND TRANSIT ROUTES (TMA ŁÓDŹ)", "09", "09-1",
     "AREA ARRIVAL AND TRANSIT ROUTES (TMA ŁÓDŹ)", "OTHER"),
    (f"EPLL - {STAR} (RNP) RWY 07", "10", "10-1", "RWY 07 STAR", "STAR"),
    (f"EPLL - {STAR} (RNP) RWY 25", "10", "10-5", "RWY 25 STAR", "STAR"),
    (f"EPLL - {IAC} (ILS z RWY 25) CAT A,B,C,D", "12", "12-1", "RWY 25 ILS Z", "IAC"),
    (f"EPLL - {IAC} (ILS y or LOC y) RWY 25 (CAT A,B,C,D)", "12", "12-3", "RWY 25 ILS Y / LOC Y", "IAC"),
    (f"EPLL - {IAC} (VOR RWY 07) CAT A,B,C,D", "12", "12-5", "RWY 07 VOR", "IAC"),
    (f"EPLL - {IAC} (VOR RWY 25) CAT A,B,C,D", "12", "12-7", "RWY 25 VOR", "IAC"),
    (f"EPLL - {IAC} (RNP RWY 07) CAT A,B,C,D", "12", "12-9", "RWY 07 RNP", "IAC"),
    (f"EPLL - {IAC} (RNP RWY 25) CAT A,B,C,D", "12", "12-13", "RWY 25 RNP", "IAC"),
    ("EPLL - VFR ARRIVAL AND DEPARTURE ROUTES", "13", "13-1", "VFR ARRIVAL AND DEPARTURE ROUTES", "VFR"),
]

# EPZG: STAR konwencjonalna i RNP dla tych samych dróg startowych
EPZG = [
    ("EPZG - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    ("EPZG - AERODROME CHART AREAS OF RESPONSIBILITY", "03", "3-1", "AREAS OF RESPONSIBILITY", "ADC"),
    ("EPZG - AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 06, RWY 24)", "06", "6-1", "OBSTACLE TYPE A RWY 06/24", "OBST"),
    (f"EPZG - {STAR} (RWY 06, RWY 24)", "10", "10-1", "RWY 06/24 STAR", "STAR"),
    (f"EPZG - {STAR} (RNP RWY 06, RWY 24)", "10", "10-3", "RWY 06/24 RNP STAR", "STAR"),
    (f"EPZG - {IAC} (ILS z) RWY 24 (CAT A/B/C/D)", "12", "12-1", "RWY 24 ILS Z", "IAC"),
    (f"EPZG - {IAC} (ILS y or LOC y) RWY 24 (CAT A/B/C/D)", "12", "12-3", "RWY 24 ILS Y / LOC Y", "IAC"),
    (f"EPZG - {IAC} (VOR) RWY 06 (CAT A/B/C/D)", "12", "12-5", "RWY 06 VOR", "IAC"),
    (f"EPZG - {IAC} (VOR) RWY 24 (CAT A/B/C/D)", "12", "12-7", "RWY 24 VOR", "IAC"),
    (f"EPZG - {IAC} (RNP) RWY 06 (CAT A/B/C/D)", "12", "12-9", "RWY 06 RNP", "IAC"),
    (f"EPZG - {IAC} (RNP) RWY 24 (CAT A/B/C/D)", "12", "12-13", "RWY 24 RNP", "IAC"),
    ("EPZG - VISUAL OPERATION CHART", "13", "13-1", "VISUAL OPERATION", "VFR"),
]

PAGES = {"EPWA": EPWA, "EPBY": EPBY, "EPLL": EPLL, "EPZG": EPZG}


def chart_rows(icao: str, charts) -> str:
    """Tabela map AD 2.24: nagłówek "Charts | Pages" i wiersz na mapę (tytuł, odnośnik z samą ikoną PDF)."""
    rows = "".join(
        f'<tr><td class="colsep"><p>{title}</p></td><td class="colsep">'
        f'<a href="{pdf(icao, folder, page)}" target="_blank"><img src="../graphics/eaip/pdf.gif" alt=""></a></td></tr>\n'
        for title, folder, page, *_ in charts)
    return ('<table class="AmdtTable" width="100%"><thead><tr><th>Charts</th><th>Pages</th></tr></thead>\n'
            f"<tbody>\n{rows}</tbody></table>")


def ad2_page(icao: str, charts=None) -> str:
    """Strona AD 2 w układzie PAŻP: tabela układu z wierszem na nagłówek / akapit, tabela map w komórce."""
    charts = PAGES[icao] if charts is None else charts

    def head(section, name):
        return (f'<tr><td>&#160;</td></tr><tr><td><ul><li><b id="{icao}-AD-{section}">{icao} AD {section} {name}</b>'
                '</li></ul></td></tr><tr><td>&#160;</td></tr>\n')

    return (f'<html><head><title>AD 2 {icao}</title></head><body>\n<a href="TChart.html">TChart.html</a>\n'
            '<table class="layout" width="100%"><tbody>\n'
            + head("2.1", "AERODROME LOCATION INDICATOR AND NAME")
            + f"<tr><td><p>{icao}</p></td></tr>\n"
            + head("2.23", "ADDITIONAL INFORMATION")
            + "<tr><td><p>6.4 REPORTING</p></td></tr><tr><td><p>Each presence of birds shall be reported.</p></td></tr>\n"
            + head("2.24", "AERONAUTICAL CHARTS RELATED TO AN AERODROME")
            + f"<tr><td>{chart_rows(icao, charts)}</td></tr>\n"
            + head("2.25", "VISUAL SEGMENT SURFACE (VSS) PENETRATION")
            + "<tr><td><p>No penetrations.</p></td></tr>\n</tbody></table>\n"
            '<a href="BChart.html">BChart.html</a></body></html>')


# --- 0.13.1 (issue #25): strony AD 4 eAIP MIL i VFR (AIRAC AMDT 11-26). Ten sam generator stron co AD 2 w IFR: tabela
# układu, tabela map "Charts | Pages" w komórce, w wierszu tytuł i odnośnik z samą ikoną PDF-u. MIL: sekcja AD 4.24,
# PDF-y w podkatalogach serii z zerem (02, 06, 08 ...). VFR: sekcja AD 4.13 "CHARTS RELATED TO THE AERODROME", PDF-y
# bez podkatalogu (EPBC) albo w podkatalogach bez zera (EPML: 2, 3, 4). Tytuły EPKS, EPBC, EPML i EPGE jak w eAIP
# (sprawdzone 2026-10-29); EPDE i EPTM: tytuły ze zmianą poprawki (skreślone i wstawione numery dróg startowych).
PKG4 = {"MIL": "https://docs.pansa.pl/ais/eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/",
        "VFR": "https://docs.pansa.pl/ais/eaipvfr/AIRAC%20AMDT%20VFR%2011-26_2026_10_29/"}


def page4_url(icao: str, pkg: str) -> str:
    return PKG4[pkg] + f"eAIP/AD%204%20{icao}%201-en-GB.html"


def pdf4(icao: str, folder: str, page: str, pkg: str) -> str:
    """Odnośnik jak na stronie AD 4 (względny, ze spacją w "AIP MIL" / "AIP VFR"; folder "" = bez podkatalogu)."""
    sub = f"{folder}/" if folder else ""
    return f"../documents/Root_WePub/AIP {pkg}/AD/{icao}/{sub}AD_4_{icao}_{page}.pdf"


def docs4(icao: str, folder: str, page: str, pkg: str) -> str:
    sub = f"{folder}/" if folder else ""
    return PKG4[pkg] + f"documents/Root_WePub/AIP%20{pkg}/AD/{icao}/{sub}AD_4_{icao}_{page}.pdf"


HMA_DEP = "HIGHLY MANOEUVRABLE MILITARY AIRCRAFT DEPARTURE CHART"
HMA_ARR = "HIGHLY MANOEUVRABLE MILITARY AIRCRAFT ARRIVAL CHART"
DEL = '<span class="AmdtDeletedAIRAC">{}</span>'
INS = '<span class="AmdtInsertedAIRAC">{}</span>'

# (tytuł, katalog, strona, oczekiwana krótka nazwa, oczekiwany rodzaj)
MIL_EPKS = [
    ("EPKS - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    ("EPKS - AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 11, RWY 29)", "06", "6-1", "OBSTACLE TYPE A RWY 11/29", "OBST"),
    (f"EPKS - {HMA_DEP} - RWY 11", "08", "8-1", "RWY 11 SID HMA", "SID"),
    (f"EPKS - {HMA_DEP} - RWY 29", "08", "8-5", "RWY 29 SID HMA", "SID"),
    (f"EPKS - {HMA_ARR} - RWY 11", "10", "10-1", "RWY 11 STAR HMA", "STAR"),
    (f"EPKS - {HMA_ARR} - RWY 29", "10", "10-5", "RWY 29 STAR HMA", "STAR"),
    (f"EPKS - {IAC} (ILS z or LOC z) RWY 29 (CAT A/B/C/D/E)", "12", "12-1", "RWY 29 ILS Z / LOC Z", "IAC"),
    (f"EPKS - {IAC} (ILS y or LOC y) RWY 29 (CAT A/B/C/D/E)", "12", "12-3", "RWY 29 ILS Y / LOC Y", "IAC"),
    (f"EPKS - {IAC} (NDB) RWY 29 (CAT A/B/C/D/E)", "12", "12-5", "RWY 29 NDB", "IAC"),
    (f"EPKS - {IAC} (TACAN) RWY 11 (CAT A/B/C/D/E)", "12", "12-7", "RWY 11 TACAN", "IAC"),
    (f"EPKS - {IAC} (TACAN) RWY 29 (CAT A/B/C/D/E)", "12", "12-9", "RWY 29 TACAN", "IAC"),
    (f"EPKS - {IAC} (PAR) RWY 11 (CAT A/B/C/D/E)", "12", "12-11", "RWY 11 PAR", "IAC"),
    (f"EPKS - {IAC} (PAR) RWY 29 (CAT A/B/C/D/E)", "12", "12-13", "RWY 29 PAR", "IAC"),
    ("EPKS - VISUAL OPERATION CHART", "13", "13-1", "VISUAL OPERATION", "VFR"),
]

# EPDE: drogi startowe 12/30 zmienione w poprawce na 11/29 (skreślone w <span class="AmdtDeletedAIRAC"> albo <del>)
MIL_EPDE = [
    ("EPDE - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    (f"EPDE - AERODROME OBSTACLE CHART - ICAO TYPE A (RWY {DEL.format('12, ')}{INS.format('11, ')}RWY {DEL.format('30)')}"
     f"{INS.format('29)')}", "06", "6-1", "OBSTACLE TYPE A RWY 11/29", "OBST"),
    (f"EPDE - {IAC} (ILS z or LOC z) RWY <del>30</del> <ins>29</ins> (CAT A/B/C/D/E)", "12", "12-1", "RWY 29 ILS Z / LOC Z",
     "IAC"),
    (f"EPDE - {IAC} (TACAN z) RWY {DEL.format('12')} {INS.format('11')} (CAT A/B/C/D/E)", "12", "12-11", "RWY 11 TACAN Z",
     "IAC"),
    (f"EPDE - {IAC} (TACAN y) RWY {DEL.format('12')} {INS.format('11')} (CAT A/B/C/D/E)", "12", "12-13", "RWY 11 TACAN Y",
     "IAC"),
    (f"EPDE - {IAC} (PAR) RWY {DEL.format('12')} {INS.format('11')} (CAT A/B/C/D/E)", "12", "12-19", "RWY 11 PAR", "IAC"),
    ("EPDE - VISUAL OPERATION CHART", "13", "13-1", "VISUAL OPERATION", "VFR"),
]

# EPTM: śmigłowce (CAT H), mapa przeszkód bez przedrostka lotniska
MIL_EPTM = [
    ("EPTM - AERODROME CHART - ICAO", "02", "2-1", "AERODROME", "ADC"),
    ("AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 11, RWY 29)", "06", "6-1", "OBSTACLE TYPE A RWY 11/29", "OBST"),
    (f"EPTM - {IAC} (NDB) RWY 29 (CAT A,H)", "12", "12-1", "RWY 29 NDB", "IAC"),
    (f"EPTM - {IAC} (TACAN) RWY 11 (CAT A,H)", "12", "12-3", "RWY 11 TACAN", "IAC"),
    (f"EPTM - {IAC} (PAR) RWY 11 (CAT A)", "12", "12-7", "RWY 11 PAR", "IAC"),
    ("EPTM - VISUAL OPERATION CHART", "13", "13-1", "VISUAL OPERATION", "VFR"),
]

# VFR: mapa lotniska (bez "- ICAO", czasem bez przedrostka) i dwie mapy operacji VFR w skali 1:50 000 i 1:250 000
VFR_EPBC = [
    ("AERODROME CHART", "", "2-1", "AERODROME", "ADC"),
    ("EPBC - VISUAL OPERATION CHART (1: 50 000)", "", "3-1", "VISUAL OPERATION 1:50 000", "VFR"),
    ("EPBC - VISUAL OPERATION CHART (1: 250 000)", "", "4-1", "VISUAL OPERATION 1:250 000", "VFR"),
]
VFR_EPML = [
    ("EPML - AERODROME CHART", "2", "2-1", "AERODROME", "ADC"),
    ("EPML - VISUAL OPERATION CHART (1: 50 000)", "3", "3-1", "VISUAL OPERATION 1:50 000", "VFR"),
    ("EPML - VISUAL OPERATION CHART (1: 250 000)", "4", "4-1", "VISUAL OPERATION 1:250 000", "VFR"),
]
VFR_EPGE = [("EPGE - VISUAL OPERATION CHART (1: 250 000)", "4", "4-1", "VISUAL OPERATION 1:250 000", "VFR")]

# (lotnisko, pakiet) -> mapy
PAGES4 = {("EPKS", "MIL"): MIL_EPKS, ("EPDE", "MIL"): MIL_EPDE, ("EPTM", "MIL"): MIL_EPTM,
          ("EPBC", "VFR"): VFR_EPBC, ("EPML", "VFR"): VFR_EPML, ("EPGE", "VFR"): VFR_EPGE}


def chart_rows4(icao: str, charts, pkg: str) -> str:
    rows = "".join(
        f'<tr><td class="colsep"><p>{title}</p></td><td class="colsep">'
        f'<a href="{pdf4(icao, folder, page, pkg)}" target="_blank"><img src="../images/application_pdf.png"></a></td></tr>\n'
        for title, folder, page, *_ in charts)
    return ('<table class="AmdtTable" width="100%"><thead><tr><th>Charts</th><th>Pages</th></tr></thead>\n'
            f"<tbody>\n{rows}</tbody></table>")


def ad4_page(icao: str, pkg: str, charts=None) -> str:
    """Strona AD 4 lotniska MIL (mapy w AD 4.24, ostatnia sekcja AD 4.25) albo VFR (mapy w AD 4.13, ostatnia sekcja)."""
    charts = PAGES4[(icao, pkg)] if charts is None else charts

    def head(section, name):
        return (f'<tr><td>&#160;</td></tr><tr><td><ul><li><b id="{icao}-AD-{section}">{icao} AD {section} {name}</b>'
                '</li></ul></td></tr><tr><td>&#160;</td></tr>\n')

    if pkg == "MIL":
        body = (head("4.23", "ADDITIONAL INFORMATION") + "<tr><td><p>Bird hazard: see AD 4.24.</p></td></tr>\n"
                + head("4.24", "AERONAUTICAL CHARTS RELATED TO AN AERODROME")
                + f"<tr><td>{chart_rows4(icao, charts, pkg)}</td></tr>\n"
                + head("4.25", "VISUAL SEGMENT SURFACE (VSS) PENETRATION") + "<tr><td><p>NIL</p></td></tr>\n")
    else:
        body = (head("4.12", "ADDITIONAL INFORMATION") + "<tr><td><p>PPR 24 HR.</p></td></tr>\n"
                + head("4.13", "CHARTS RELATED TO THE AERODROME")
                + f"<tr><td>{chart_rows4(icao, charts, pkg)}</td></tr>\n")
    return (f'<html><head><title>AD 4 {icao}</title></head><body>\n<a href="TChart.html">TChart.html</a>\n'
            '<table class="layout" width="100%"><tbody>\n'
            + head("4.1", "AERODROME LOCATION INDICATOR AND NAME") + f"<tr><td><p>{icao}</p></td></tr>\n"
            + body + '</tbody></table>\n<a href="BChart.html">BChart.html</a></body></html>')
