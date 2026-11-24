"""0.14.2 (issue #35): listy CALLSIGN i AIRCRAFT. Właściciel projektu: "do list callsign i aircraft popraw kolorowanie co
drugiego wiersza, by było bardziej widoczne/kontrastujące" i "listy callsign i aircraft mają być praktycznie
identyczne". Paski wierszy z jednych zmiennych w :root (style.css), czarne i ciemnoszare jak w METAR; od unslop te same
pasy we wszystkich tabelach (table.data), pod myszą zielona krawędź zamiast jaśniejszego tła. Ta sama czcionka komórek
i to samo pole wyszukiwania w obu zakładkach."""
import re

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
HOVER = "table.data tbody tr:hover { outline: 1px solid var(--green-hi); outline-offset: -1px; }"
STYLE = (FRONTEND / "css" / "style.css").read_text("utf-8")
AIRCRAFT_CSS = (FRONTEND / "css" / "aircraft.css").read_text("utf-8")
AIRCRAFT_JS = (FRONTEND / "js" / "tabs" / "aircraft.js").read_text("utf-8")
CALLSIGN_JS = (FRONTEND / "js" / "tabs" / "callsign.js").read_text("utf-8")


def _plain(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _root_var(name):
    root = re.search(r"(?m)^:root \{(.*?)^\}", _plain(STYLE), re.S).group(1)
    m = re.search(rf"(?m)^\s*{re.escape(name)}:\s*([^;]+);", root)
    assert m, name
    return m.group(1).strip()


def _rgb(value):
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    assert re.fullmatch(r"[0-9a-fA-F]{6}", v), value
    return [int(v[i:i + 2], 16) for i in (0, 2, 4)]


def _lum(value):
    """Względna luminancja WCAG 2."""
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_list_stripes_contrast():
    """Paski wyraźnie różne (dawniej --row / --row-alt: stosunek luminancji ok. 1,04, praktycznie niewidoczne); wybrany
    wiersz czerwonym pasem (unslop, jak lista lotnisk PANDORY) innym niż oba paski; napisy obu list czytelne na obu
    paskach, biały napis na pasie zaznaczenia."""
    row, alt = (_root_var(f"--list-row{s}") for s in ("", "-alt"))
    assert (row, alt) == ("#000", "#2b2b2b")  # jak paski METAR (metar.css --mt-alt), zdjęcie PANDORY
    assert _ratio(row, alt) >= 1.3
    assert len({row, alt, _root_var("--sel")}) == 3 and _lum(_root_var("--sel")) > _lum(row)
    for text in ("#fff", _root_var("--yellow"), _root_var("--text"), "#c9d1c9", "#ff6a5a", _root_var("--ok")):
        assert min(_ratio(text, row), _ratio(text, alt)) >= 4.5, text
    assert _ratio("#fff", _root_var("--sel")) >= 4.5


def test_all_tables_share_the_stripes():
    """unslop: pasy PANDORY we wszystkich tabelach (table.data: AD, INOP, OVERVIEW i inne) jak w CALLSIGN i AIRCRAFT;
    pod myszą nigdzie jaśniejsze tło, tylko zielona krawędź wiersza (przy myszy)."""
    assert (_root_var("--row"), _root_var("--row-alt")) == (_root_var("--list-row"), _root_var("--list-row-alt"))
    css = _plain(STYLE)
    assert "table.data tbody tr:nth-child(odd) td { background: var(--row); }" in css
    assert "table.data tbody tr:nth-child(even) td { background: var(--row-alt); }" in css
    assert HOVER in css and css.rindex("@media (hover: hover) {", 0, css.index(HOVER)) >= 0
    for f in (FRONTEND / "css").glob("*.css"):
        assert not re.search(r"--(list-)?row-hover", _plain(f.read_text("utf-8"))), f.name
    users = {f.name for f in (FRONTEND / "css").glob("*.css") if "--list-row" in _plain(f.read_text("utf-8"))}
    assert users == {"style.css", "aircraft.css"}
    for line in css.splitlines():
        if "var(--list-row" in line:
            assert line.startswith("table.callsigns "), line


def test_both_lists_use_the_same_stripes_and_font():
    style, aircraft = _plain(STYLE), _plain(AIRCRAFT_CSS)
    assert "table.callsigns tbody tr:nth-child(odd) td { background: var(--list-row); }" in style
    assert "table.callsigns tbody tr:nth-child(even) td { background: var(--list-row-alt); }" in style
    assert HOVER in style and "table.callsigns tbody tr:hover" not in style  # wspólna krawędź z table.data
    assert "table.ac-table tbody tr.ac-rec td { background: var(--list-row); }" in aircraft
    assert "table.ac-table tbody tr.ac-rec:nth-child(even of .ac-rec) td { background: var(--list-row-alt); }" in aircraft
    assert "table.ac-table tbody tr:is(.ac-gh, .ac-detail-row, .ac-msg):hover { outline: none; }" in aircraft
    # jedna czcionka komórek: 20 px var(--mono), odstępy komórek jak table.data (4 px 8 px)
    assert "table.callsigns td.icao { font: 20px var(--mono); color: #fff; width: 90px; }" in style
    assert "table.data th, table.data td { padding: 4px 8px; text-align: left; }" in style
    assert ".ac-table tr.ac-rec td { padding: 4px 8px; font: 20px var(--mono); }" in aircraft
    assert ".ac-table tr.ac-rec td.icao { font: 20px var(--mono); color: #fff; white-space: nowrap; }" in aircraft
    # bez pogrubień, cieni, zaokrągleń i filtrów w nowych regułach
    for line in (style + aircraft).splitlines():
        if "list-row" in line:
            assert not re.search(r"bold|shadow|radius|filter|glow", line), line


def test_same_search_field():
    """Pole wyszukiwania tej samej szerokości (size) i z tym samym początkiem podpowiedzi; licznik w rzędzie pola
    (w AIRCRAFT dawniej zawsze w osobnej linijce: flex-basis 100%), jedna linijka skracana wielokropkiem; do osobnej
    linijki tylko w wąskim panelu (stałe min-width, nie długość tekstu)."""
    def field(src):
        m = re.search(r'<input type="search" class="q" placeholder="([^"]*)" size="(\d+)"', src)
        assert m
        return m.group(1), int(m.group(2))
    (cs_ph, cs_size), (ac_ph, ac_size) = field(CALLSIGN_JS), field(AIRCRAFT_JS)
    assert cs_size == ac_size == 46
    assert cs_ph.startswith("Search: ") and ac_ph.startswith("Search: ")
    count = re.search(r"(?m)^\.ac-pane \.toolbar \.count \{([^}]*)\}", _plain(AIRCRAFT_CSS)).group(1)
    assert "flex: 1 1 0;" in count and "1 1 100%" not in count and "min-width: min(100%, 16em);" in count
    assert "white-space: nowrap;" in count and "text-overflow: ellipsis;" in count


def test_list_code_lines_ascii():
    """Poza samodzielnymi komentarzami tylko ASCII (symbole w napisach jako \\uXXXX), w obu zakładkach."""
    for name, src in (("callsign.js", CALLSIGN_JS), ("aircraft.js", AIRCRAFT_JS)):
        for n, line in enumerate(src.splitlines(), 1):
            if line.strip().startswith("//"):
                continue
            assert all(ord(c) < 128 for c in line), (name, n)


def test_no_ad_like_names():
    for src in (AIRCRAFT_CSS, AIRCRAFT_JS, CALLSIGN_JS):
        assert not re.search(r"[.#\"' ](ad-|ads\b|advert|banner|sponsor|promo)", _plain(src), re.I)
