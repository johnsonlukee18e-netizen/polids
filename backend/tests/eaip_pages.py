"""0.12.6 (issue #21): strony AD 2 eAIP do testów listy map (AD CIV), w układzie prawdziwych stron PAŻP (AIRAC AMDT 10-26).

Cała treść strony AD 2 jest w tabeli układu (każdy nagłówek i akapit to wiersz, puste wiersze wokół nagłówków sekcji),
a tabela map AD 2.24 ("Charts | Pages") jest osobną tabelą wewnątrz komórki tej tabeli; w wierszu mapy: komórka
z tytułem i komórka z odnośnikiem do PDF-u (sama ikona, bez tekstu i bez alt). Parser z 0.12.5 sklejał wtedy wszystkie
tytuły w jeden (wszystkie 37 map EPWA z tym samym tytułem i rodzajem OBST, zrzut w issue #21).

Tytuły EPWA 1-23 jak na zrzucie z issue #21, reszta (24-37) dopisana w tym samym stylu (strona EPWA jest za długa dla
narzędzia, którym ją czytaliśmy, AD 2.24 nie dało się odczytać). EPBY, EPLL, EPZG: tytuły jak na stronach PAŻP."""

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
    (f"EPWA - {SID} (RNAV RWY 11)", "08", "8-1", "RWY 11 SID", "SID"),
    (f"EPWA - {SID} (RNAV RWY 15)", "08", "8-5", "RWY 15 SID", "SID"),
    (f"EPWA - {SID} (RNAV RWY 29)", "08", "8-9", "RWY 29 SID", "SID"),
    (f"EPWA - {SID} (RNAV RWY 33)", "08", "8-13", "RWY 33 SID", "SID"),
    (f"EPWA - {STAR} (RNAV RWY 11)", "10", "10-1", "RWY 11 STAR", "STAR"),
    (f"EPWA - {STAR} (RNAV RWY 15)", "10", "10-5", "RWY 15 STAR", "STAR"),
    (f"EPWA - {STAR} (RNAV RWY 29)", "10", "10-9", "RWY 29 STAR", "STAR"),
    (f"EPWA - {STAR} (RNAV RWY 33)", "10", "10-13", "RWY 33 STAR", "STAR"),
    (f"EPWA - {IAC} (ILS z CAT II or LOC z) RWY 11 (CAT A,B,C,D)", "12", "12-1", "RWY 11 ILS Z CAT II / LOC Z", "IAC"),
    (f"EPWA - {IAC} (ILS y CAT II) RWY 11 (CAT A,B,C,D)", "12", "12-3", "RWY 11 ILS Y CAT II", "IAC"),
    (f"EPWA - {IAC} (ILS z CAT II/III or LOC z) RWY 33 (CAT A,B,C,D)", "12", "12-5", "RWY 33 ILS Z CAT II/III / LOC Z", "IAC"),
    (f"EPWA - {IAC} (ILS y CAT II/III) RWY 33 (CAT A,B,C,D)", "12", "12-7", "RWY 33 ILS Y CAT II/III", "IAC"),
    (f"EPWA - {IAC} (ILS or LOC) RWY 15 (CAT A,B,C,D)", "12", "12-9", "RWY 15 ILS / LOC", "IAC"),
    (f"EPWA - {IAC} (ILS z or LOC z) RWY 29 (CAT A,B,C,D)", "12", "12-11", "RWY 29 ILS Z / LOC Z", "IAC"),
    (f"EPWA - {IAC} (ILS y) RWY 29 (CAT A,B,C,D)", "12", "12-13", "RWY 29 ILS Y", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 11 (CAT A,B,C,D)", "12", "12-15", "RWY 11 VOR", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 29 (CAT A,B,C,D)", "12", "12-17", "RWY 29 VOR", "IAC"),
    (f"EPWA - {IAC} (VOR) RWY 33 (CAT A,B,C,D)", "12", "12-19", "RWY 33 VOR", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 11 (CAT A,B,C,D)", "12", "12-21", "RWY 11 RNP", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 15 (CAT A,B,C,D)", "12", "12-25", "RWY 15 RNP", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 29 (CAT A,B,C,D)", "12", "12-29", "RWY 29 RNP", "IAC"),
    (f"EPWA - {IAC} (RNP) RWY 33 (CAT A,B,C,D)", "12", "12-33", "RWY 33 RNP", "IAC"),
    ("EPWA - VFR ARRIVAL AND DEPARTURE ROUTES", "13", "13-1", "VFR ARRIVAL AND DEPARTURE ROUTES", "VFR"),
    ("BIRD CONCENTRATIONS", "14", "14-1", "BIRD CONCENTRATIONS", "OTHER"),
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
    (f"EPBY - {STAR_BY} (RNP RWY 08)", "10", "10-3", "RWY 08 STAR", "STAR"),
    (f"EPBY - {STAR_BY} (RNP RWY 26)", "10", "10-5", "RWY 26 STAR", "STAR"),
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
