"""0.12.6 (issue #21): AD CIV - lista map lotniska z AD 2.24 eAIP. Na prawdziwej stronie EPWA tabela map stoi w komórce
tabeli układu całej strony i parser z 0.12.5 dawał 37 wpisów z jednym sklejonym tytułem ("Charts Pages EPWA - AERODROME
CHART - ICAO EPWA - ...") i rodzajem OBST. Teraz: jeden wpis na mapę, krótka nazwa (title), pełny tytuł (full) i rodzaj
(ADC, APDC, SID, STAR, IAC, VFR, OBST, OTHER) w każdym układzie tabeli, który widzieliśmy albo którego można się spodziewać."""
import asyncio
import os
import random
import re
import tempfile
from collections import Counter
from html import unescape

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402

from backend.app.config import settings  # noqa: E402
from backend.app.services import eaip  # noqa: E402
from backend.tests.eaip_pages import EPWA, PAGES, PKG, ad2_page, chart_rows, docs, page_url, pdf  # noqa: E402
from backend.tests.test_eaip_links import _soup  # noqa: E402


def parse(html, icao="EPWA"):
    return eaip.parse_charts(html, page_url(icao), icao)


def want(icao, charts=None):
    """Oczekiwane wpisy z tabeli w eaip_pages.py: id bez zer z przodu, adres PDF-u ze spacją jako %20, "&amp;" → "&"."""
    out = []
    for title, folder, page, short, kind in (PAGES[icao] if charts is None else charts):
        n, m = page.split("-")
        full = re.sub(rf"^{icao} - ", "", unescape(title))
        out.append({"id": f"{int(n)}-{int(m)}", "page": f"AD 2 {icao} {int(n)}-{int(m)}", "title": short, "full": full,
                    "kind": kind, "url": docs(icao, folder, page)})
    return out


@pytest.mark.parametrize("icao", sorted(PAGES))
def test_real_layout_one_entry_per_chart(icao):
    # układ stron PAŻP: tabela map w komórce tabeli układu; każda mapa z własnym tytułem, krótką nazwą i rodzajem
    assert parse(ad2_page(icao), icao) == want(icao)


def test_epwa_no_glued_titles_and_kind_counts():
    charts = parse(ad2_page("EPWA"))
    assert len(charts) == 37 and len({c["url"] for c in charts}) == 37
    # żaden tytuł nie jest nagłówkiem tabeli ani sklejką kilku map (błąd z 0.12.5)
    assert not [c for c in charts if "Charts" in c["full"] or "Pages" in c["full"] or "EPWA" in c["full"]]
    assert all(len(c["title"]) <= 60 for c in charts)
    assert Counter(c["kind"] for c in charts) == {"ADC": 3, "APDC": 6, "OBST": 4, "SID": 4, "STAR": 4, "IAC": 13,
                                                  "VFR": 2, "OTHER": 1}
    names = [c["title"] for c in charts]
    assert len(set(names)) == len(names)
    for name in ("AERODROME", "AREAS OF RESPONSIBILITY", "PARKING APN 1, 7A, 7B, 9", "OBSTACLE TYPE A RWY 11/29",
                 "PATC RWY 11", "RWY 29 SID", "RWY 11 STAR", "RWY 11 ILS Z CAT II / LOC Z",
                 "RWY 33 ILS X CAT II & III / LOC X", "GROUND MOVEMENT (A380-800, AN-124-100, B747-8, C-5B GALAXY)"):
        assert name in names


# --- inne układy tej samej tabeli map: wynik jak w układzie PAŻP
def _page(body):
    return f"<html><body><h3>EPWA AD 2.24 AERONAUTICAL CHARTS RELATED TO AN AERODROME</h3>{body}</body></html>"


def _variants():
    rows = chart_rows("EPWA", EPWA)
    sloppy = re.sub(r"</td>|</tr>|</tbody>|</p>", "", rows).replace("</table>", "")
    links_first = re.sub(r'<tr><td class="colsep"><p>(.*?)</p></td><td class="colsep">(<a .*?</a>)</td></tr>',
                         r"<tr><td>\2</td><td>\1</td></tr>", rows)
    page_text = re.sub(r'(AD_2_EPWA_(\d+-\d+)\.pdf" target="_blank">)<img[^>]*>', r"\1AD 2 EPWA \2", rows)
    td_header = rows.replace("<th>Charts</th><th>Pages</th>", "<td><b>Charts</b></td><td><b>Pages</b></td>")
    # tytuł w małej tabeli w komórce tytułu (jak w 0.12.5: tabela bez PDF-u mapy jest tekstem swojej komórki)
    title_table = re.sub(r"<p>(.*?)</p>", r"<table><tr><td><p>\1</p></td></tr></table>", rows)
    # odnośnik w tabeli w komórce "Pages", z tekstem "PDF" (opis odnośnika, nie tytuł)
    pdf_text = re.sub(r'(<a [^>]*>)<img[^>]*></a>', r"<table><tr><td>\1PDF</a></td></tr></table>", rows)
    return {
        "flat": rows,
        "two_layout_levels": f'<table><tr><td><table><tr><td></td><td>{rows}</td></tr></table></td></tr></table>',
        "heading_in_same_cell": f"<table><tr><td><b>EPWA AD 2.24 CHARTS</b><br/>{rows}<p>Nil</p></td></tr></table>",
        "header_row_as_td": f"<table><tr><td>{td_header}</td></tr></table>",
        "link_cell_first": f"<table><tr><td>{links_first}</td></tr></table>",
        "page_number_link_text": f"<table><tr><td>{page_text}</td></tr></table>",
        "title_in_nested_table": f"<table><tr><td>{title_table}</td></tr></table>",
        "pdf_link_text_in_nested_table": f"<table><tr><td>{pdf_text}</td></tr></table>",
        # tabela map bez </td>, </tr>, </p> i </table> w środku tabeli układu
        "unclosed_tags": f"<table><tr><td>{sloppy}</td></tr><tr><td><p>EPWA AD 2.25</p></td></tr></table>",
    }


@pytest.mark.parametrize("name", sorted(_variants()))
def test_layout_variants(name):
    assert parse(_page(_variants()[name])) == want("EPWA"), name


def test_several_charts_in_one_cell():
    # jeden wiersz z kilkoma tytułami i kilkoma PDF-ami: tytuły w osobnych liniach albo z przedrostkiem lotniska
    a = (f'<a href="{pdf("EPWA", "08", "8-1")}"><img alt=""></a><br/><a href="{pdf("EPWA", "08", "8-5")}"><img alt=""></a>'
         f'<br/><a href="{pdf("EPWA", "08", "8-9")}"><img alt=""></a>')
    lines = ("<tr><td><p>STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO (RNAV RWY 11)</p>"
             "<p>STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO (RNAV RWY 15)</p>"
             f"STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO (RNAV RWY 29)</td><td>{a}</td></tr>")
    prefixed = ("<tr><td>EPWA - STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO (RNAV RWY 11) EPWA - STANDARD DEPARTURE "
                "CHART INSTRUMENT (SID) - ICAO (RNAV RWY 15) EPWA - STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO "
                f"(RNAV RWY 29)</td><td>{a}</td></tr>")
    for row in (lines, prefixed):
        got = [(c["id"], c["title"], c["kind"]) for c in parse(_page(f"<table><tr><td><table>{row}</table></td></tr></table>"))]
        assert got == [("8-1", "RWY 11 SID", "SID"), ("8-5", "RWY 15 SID", "SID"), ("8-9", "RWY 29 SID", "SID")], row
    # liczba tytułów nie pasuje do liczby PDF-ów: zamiast sklejki numer strony (rodzaj z numeru serii)
    glued = prefixed.replace("EPWA - STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO (RNAV RWY 29)", "")
    got = [(c["id"], c["title"], c["kind"]) for c in parse(_page(f"<table>{glued}</table>"))]
    assert got == [("8-1", "AD 2 EPWA 8-1", "SID"), ("8-5", "AD 2 EPWA 8-5", "SID"), ("8-9", "AD 2 EPWA 8-9", "SID")]


def test_one_title_on_two_lines_with_two_pdfs():
    # jeden tytuł w dwóch liniach i dwa PDF-y jednej mapy: wspólny tytuł, a nie dwie połówki tytułu
    two = (f'<a href="{pdf("EPWA", "05", "5-1")}"><img alt=""></a> <a href="{pdf("EPWA", "05", "5-2")}"><img alt=""></a>')
    rows = {
        "<td>EPWA - AERODROME<br/>GROUND MOVEMENT CHART - ICAO</td>":
            [("5-1", "GROUND MOVEMENT (1/2)", "ADC"), ("5-2", "GROUND MOVEMENT (2/2)", "ADC")],
        "<td><p>EPWA - AIRCRAFT PARKING, DOCKING CHART - ICAO</p><p>(APN 1,7A,7B,9)</p></td>":
            [("5-1", "PARKING APN 1, 7A, 7B, 9 (1/2)", "APDC"), ("5-2", "PARKING APN 1, 7A, 7B, 9 (2/2)", "APDC")],
    }
    for cell, expected in rows.items():
        html = _page(f"<table><tr><td><table><tr>{cell}<td>{two}</td></tr></table></td></tr></table>")
        assert [(c["id"], c["title"], c["kind"]) for c in parse(html)] == expected, cell


def test_rowspan_in_nested_chart_table():
    # wspólny tytuł dwóch PDF-ów (rowspan) w tabeli map zagnieżdżonej w tabeli układu
    rows = (f'<tr><td rowspan="2">EPWA - AERODROME CHART - ICAO</td><td><a href="{pdf("EPWA", "02", "2-1")}"></a></td></tr>'
            f'<tr><td><a href="{pdf("EPWA", "02", "2-2")}"></a></td></tr>'
            f'<tr><td>EPWA - AERODROME CHART AREAS OF RESPONSIBILITY</td><td><a href="{pdf("EPWA", "03", "3-1")}"></a></td></tr>')
    got = [(c["id"], c["title"], c["full"], c["kind"])
           for c in parse(_page(f"<table><tr><td><table>{rows}</table></td></tr></table>"))]
    assert got == [("2-1", "AERODROME (1/2)", "AERODROME CHART - ICAO", "ADC"),
                   ("2-2", "AERODROME (2/2)", "AERODROME CHART - ICAO", "ADC"),
                   ("3-1", "AREAS OF RESPONSIBILITY", "AERODROME CHART AREAS OF RESPONSIBILITY", "ADC")]


def test_nested_tables_in_title_and_link_cells():
    # tytuł w tabeli zagnieżdżonej w komórce tytułu i odnośnik z tekstem "PDF" w tabeli w komórce odnośnika
    a = (f'<tr><td><table><tr><td><p>EPWA - AERODROME CHART - ICAO</p></td></tr></table></td>'
         f'<td><a href="{pdf("EPWA", "02", "2-1")}"><img alt=""></a></td></tr>')
    b = (f'<tr><td>EPWA - AERODROME CHART AREAS OF RESPONSIBILITY</td>'
         f'<td><table><tr><td><a href="{pdf("EPWA", "03", "3-1")}">PDF</a></td></tr></table></td></tr>')
    c = (f'<tr><td><table><tr><td>EPWA - AIRCRAFT PARKING, DOCKING CHART</td></tr><tr><td>- ICAO (APN 2)</td></tr></table>'
         f'</td><td><table><tr><td>AD 2 EPWA 4-11</td><td><a href="{pdf("EPWA", "04", "4-11")}">Open PDF</a></td></tr>'
         f'<tr><td>AD 2 EPWA 4-12</td><td><a href="{pdf("EPWA", "04", "4-12")}">AD_2_EPWA_4-12.pdf</a></td></tr>'
         f'</table></td></tr>')
    got = [(x["id"], x["title"], x["full"], x["kind"]) for x in parse(_page(f"<table>{a}{b}{c}</table>"))]
    apdc = "AIRCRAFT PARKING, DOCKING CHART - ICAO (APN 2)"
    assert got == [("2-1", "AERODROME", "AERODROME CHART - ICAO", "ADC"),
                   ("3-1", "AREAS OF RESPONSIBILITY", "AERODROME CHART AREAS OF RESPONSIBILITY", "ADC"),
                   ("4-11", "PARKING APN 2 (1/2)", apdc, "APDC"), ("4-12", "PARKING APN 2 (2/2)", apdc, "APDC")]
    # tabela układu wokół tabeli map nie oddaje tytułu nagłówka ani sąsiedniej tabeli bez map
    legend = "<table><tr><td>Legend</td></tr></table>"
    got = parse(_page(f"<table><tr><td>EPWA AD 2.24{legend}<table>{a}{b}</table></td></tr></table>"))
    assert [x["title"] for x in got] == ["AERODROME", "AREAS OF RESPONSIBILITY"]


def test_deleted_and_hidden_text():
    # skreślone w poprawce (klasa AmdtDeleted..., <del>) i ukryte (display:none) nie wchodzą do tytułu ani listy
    rows = (f'<tr><td><span class="AmdtDeletedAIRAC">EPWA - OLD CHART</span><span class="AmdtInsertedAIRAC">EPWA - '
            f'AERODROME CHART - ICAO</span><span style="display: none">AD_HP;TXT_NAME</span></td>'
            f'<td><a href="{pdf("EPWA", "02", "2-1")}"><img alt=""></a></td></tr>'
            f'<tr><td><del>EPWA - WITHDRAWN CHART</del></td><td><del><a href="{pdf("EPWA", "09", "9-1")}"></a></del></td></tr>'
            f'<tr><td><span class="AmdtDeletedAIRAC"><span>EPWA - </span>X</span>BIRD CONCENTRATIONS</td>'
            f'<td><a href="{pdf("EPWA", "14", "14-1")}"></a></td></tr>')
    got = [(c["id"], c["full"]) for c in parse(_page(f"<table><tr><td><table>{rows}</table></td></tr></table>"))]
    assert got == [("2-1", "AERODROME CHART - ICAO"), ("14-1", "BIRD CONCENTRATIONS")]


def test_kind_from_series_when_title_says_nothing():
    # tytuł bez słów rodzaju albo numer strony zamiast tytułu: rodzaj z serii w nazwie PDF-u (4 postojowe, 8 SID,
    # 12 podejścia); serie 9 (mapa obszaru), 11 i 14 (ptaki) zostają OTHER; krótka nazwa bez rodzaju z serii
    charts = (("AIRCRAFT PARKING CHART - ICAO", "04", "4-1"), ("HOT SPOT", "04", "4-3"), ("", "08", "08-1"),
              ("EPKK - AREA CHART ICAO - ARRIVAL AND TRANSIT ROUTES", "09", "09-1"), ("", "11", "11-1"),
              ("EPKK - BIRD CONCENTRATIONS", "14", "14-1"), ("RWY 25 ADDITIONAL INFORMATION", "12", "12-9"))
    rows = "".join(f'<tr><td>{t}</td><td><a href="{pdf("EPKK", f, p)}"><img alt=""></a></td></tr>' for t, f, p in charts)
    got = [(c["id"], c["title"], c["kind"]) for c in parse(_page(f"<table>{rows}</table>"), "EPKK")]
    assert got == [("4-1", "PARKING", "APDC"), ("4-3", "HOT SPOT", "ADC"), ("8-1", "AD 2 EPKK 8-1", "SID"),
                   ("9-1", "AREA ARRIVAL AND TRANSIT ROUTES", "OTHER"), ("11-1", "AD 2 EPKK 11-1", "OTHER"),
                   ("14-1", "BIRD CONCENTRATIONS", "OTHER"), ("12-9", "ADDITIONAL INFORMATION RWY 25", "IAC")]


# --- krótkie nazwy
def short(*titles):
    return eaip.short_names([(t, eaip.chart_kind(t)) for t in titles])


def test_short_names_examples():
    cases = {
        "AERODROME CHART - ICAO": "AERODROME",
        "AERODROME CHART AREAS OF RESPONSIBILITY": "AREAS OF RESPONSIBILITY",
        "AIRCRAFT PARKING, DOCKING CHART - ICAO (APN 12,13,CARGO)": "PARKING APN 12, 13, CARGO",
        "AIRCRAFT PARKING, DOCKING CHART - ICAO": "PARKING",
        "AERODROME GROUND MOVEMENT CHART - ICAO": "GROUND MOVEMENT",
        "AERODROME OBSTACLE CHART - ICAO TYPE A (RWY 01, RWY 19)": "OBSTACLE TYPE A RWY 01/19",
        "PRECISION APPROACH TERRAIN CHART - ICAO (RWY 01)": "PATC RWY 01",
        "STANDARD DEPARTURE CHART - INSTRUMENT (SID) - ICAO (RNP RWY 08)": "RWY 08 SID",
        "STANDARD INSTRUMENT DEPARTURE CHART - ICAO RWY 29": "RWY 29 SID",
        "STANDARD ARRIVAL CHART INSTRUMENT (STAR) - ICAO (RNAV RWY 08)": "RWY 08 STAR",
        "INSTRUMENT APPROACH CHART - ICAO (ILS z CAT II or LOC z) RWY 01 (CAT A,B,C,D)": "RWY 01 ILS Z CAT II / LOC Z",
        "INSTRUMENT APPROACH CHART - ICAO (ILS CAT II or LOC) RWY 08 (CAT A,B,C,D)": "RWY 08 ILS CAT II / LOC",
        "INSTRUMENT APPROACH CHART - ICAO (VOR z) RWY 19 (CAT A,B,C,D)": "RWY 19 VOR Z",
        "INSTRUMENT APPROACH CHART - ICAO (RNP RWY 07) CAT A,B,C,D": "RWY 07 RNP",
        "INSTRUMENT APPROACH CHART - ICAO (ILS) RWY 25 (CAT A/B/C/D)": "RWY 25 ILS",
        "INSTRUMENT APPROACH CHART - ICAO (ILS z CAT II &amp; III or LOC z) RWY 33 (CAT A,B,C,D)":
            "RWY 33 ILS Z CAT II &amp; III / LOC Z",
        "INSTRUMENT APPROACH CHART - ICAO (ILS x CAT II & III or LOC x) RWY 33 (CAT A,B,C,D)": "RWY 33 ILS X CAT II & III / LOC X",
        # nawias w nawiasie (EPKT) i PAR (EPRA)
        "AIRCRAFT PARKING, DOCKING CHART - ICAO (APN 1, 2 (DE-ICING), 3)": "PARKING APN 1, 2 (DE-ICING), 3",
        "INSTRUMENT APPROACH CHART - ICAO (PAR) RWY 07 (CAT A,B,C,D,E) MILITARY USE ONLY": "RWY 07 PAR MILITARY USE ONLY",
        "INSTRUMENT APPROACH CHART - ICAO (NDB z) RWY 25 (CAT A,B,C,D,E) MILITARY USE ONLY": "RWY 25 NDB Z MILITARY USE ONLY",
        "HOT SPOT": "HOT SPOT",
        "VISUAL APPROACH CHART - ICAO (RWY 26)": "VISUAL APPROACH RWY 26",
        "VISUAL OPERATION CHART": "VISUAL OPERATION",
        "VFR ARRIVAL AND DEPARTURE ROUTES": "VFR ARRIVAL AND DEPARTURE ROUTES",
        "ATC SURVEILLANCE MINIMUM ALTITUDE CHART - ICAO": "ATC SURVEILLANCE MINIMUM ALTITUDE",
        "BIRD CONCENTRATIONS": "BIRD CONCENTRATIONS",
        "AD 2 EPWA 13-1": "AD 2 EPWA 13-1",
    }
    for full, name in cases.items():
        assert short(full) == [name], full


def test_short_names_details_only_to_tell_charts_apart():
    # RNP tylko tam, gdzie ten sam RWY ma SID konwencjonalny i RNP; tak samo kategorie statków przy podejściach
    sid = "STANDARD DEPARTURE CHART INSTRUMENT (SID) - ICAO"
    assert short(f"{sid} (RWY 08)", f"{sid} (RNP RWY 08)", f"{sid} (RNP RWY 26)") == \
        ["RWY 08 SID", "RWY 08 RNP SID", "RWY 26 SID"]
    # te same drogi startowe w innym zestawie (EPBY: STAR konwencjonalna RWY 08/26, RNP osobno dla RWY 08 i RWY 26)
    star = "STANDARD ARRIVAL CHART - INSTRUMENT (STAR) - ICAO"
    assert short(f"{star} (RWY 08, RWY 26)", f"{star} (RNP RWY 08)", f"{star} (RNP RWY 26)") == \
        ["RWY 08/26 STAR", "RWY 08 RNP STAR", "RWY 26 RNP STAR"]
    # EPPO: konwencjonalna i RNAV tylko dla RWY 28; RWY 10 ma jedną STAR
    assert short(f"{star} (RWY 28)", f"{star} (RNAV RWY 10)", f"{star} (RNAV RWY 28)") == \
        ["RWY 28 STAR", "RWY 10 STAR", "RWY 28 RNAV STAR"]
    # STAR bez drogi startowej (wszystkie) i RNP dla RWY 08; same RNAV dla różnych dróg: bez RNAV
    assert short(f"{star}", f"{star} (RNP RWY 08)") == ["STAR", "RWY 08 RNP STAR"]
    assert short(f"{sid} (RNAV RWY 11)", f"{sid} (RNAV RWY 29)", f"{star} (RWY 11)") == \
        ["RWY 11 SID", "RWY 29 SID", "RWY 11 STAR"]
    iac = "INSTRUMENT APPROACH CHART - ICAO"
    assert short(f"{iac} (VOR) RWY 24 (CAT A,B)", f"{iac} (VOR) RWY 24 (CAT C/D)", f"{iac} (VOR) RWY 06 (CAT A,B,C,D)") == \
        ["RWY 24 VOR CAT A/B", "RWY 24 VOR CAT C/D", "RWY 06 VOR"]
    # różnica tylko w reszcie pełnego tytułu: pełny tytuł; jednakowe tytuły: numer
    assert short("AERODROME CHART - ICAO", "AERODROME CHART") == ["AERODROME CHART - ICAO", "AERODROME CHART"]
    assert short(f"{sid} (RNP) RWY 25", f"{sid} (RNP) RWY 25", f"{sid} (RNP) RWY 07") == \
        ["RWY 25 SID (1/2)", "RWY 25 SID (2/2)", "RWY 07 SID"]
    assert short() == []


def test_short_names_never_empty():
    # tytuł z samych słów ogólnych: zostaje pełny tytuł
    assert short("CHART - ICAO") == ["CHART - ICAO"]
    assert short("(RWY 11)") == ["RWY 11"]


# --- serwer: lista map EPWA z udawanej strony w układzie PAŻP
def test_aerodrome_charts_epwa(monkeypatch):
    seen = []

    async def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text=ad2_page("EPWA"))

    monkeypatch.setattr(settings, "aip_ifr_url", PKG + "index-v2.html")
    monkeypatch.setattr(eaip, "_page_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    eaip.reset_charts()
    try:
        out = asyncio.run(eaip.aerodrome_charts("EPWA"))
    finally:
        eaip.reset_charts()
    assert seen == [page_url("EPWA")] and out["error"] is None and out["charts"] == want("EPWA")


def test_fuzz_tail_after_real_layout_page():
    """Strona w układzie PAŻP z dopisaną na końcu losową zbitką znaczników: te same mapy (bez krótkiej nazwy, która
    zależy od całej listy), parser nie rzuca wyjątku."""
    good = [{k: v for k, v in c.items() if k != "title"} for c in want("EPWA")]
    for seed in range(150):
        rnd = random.Random(1000 + seed)
        tail = _soup(rnd, rnd.randint(1, 80)).replace("AD_2_EPZG_", "AD_2_EPWA_9").replace("AD_2_EPWA_", "AD_2_EPWA_9")
        got = [{k: v for k, v in c.items() if k != "title"} for c in parse(ad2_page("EPWA") + tail)
               if not c["id"].startswith("9")]
        assert got == good, (seed, tail)
