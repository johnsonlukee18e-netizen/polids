"""AIRCRAFT w Node (pomocnicze funkcje aircraft.js z zastępczym api.js) i reguły aircraft.css.
0.12.6 (issue #21): wartości w kratkach (mała etykieta nad dużą wartością, kolor kratki wg kategorii), bez dopisków skąd
dane (plik ICAO, baza osiągów, Wikipedia) w interfejsie.
0.13.1 (issue #25): "w domyślnym widoku wyświetl w pierwszej kolumnie kod ICAO, potem producenta, potem pełną nazwę,
liczbę silników, WTC (ICAO), recat. Dopiero w dodatkowym widoku wyświetl zdjęcie na górze, niżej: Wingspan, length,
height, MLW, MTOW, dopiero potem pozostale informacje". Lista to tabela (wiersz na typ, cells/record), rozwinięcie
to wiersz pod klikniętym (detail): zdjęcie, pięć głównych kratek zawsze (brak = półpauza), pozostałe kratki, opis,
odnośniki. Przyciski AIRBUS, BOEING, BOMBARDIER, EMBRAER, GA; grupy GA w kolejności z issue (makerGroups).
0.14.0 (issue #28): "w kolumnie silników dodaj wiadomość o typie silnika, np. 2 Jet" (engineLabel); większa czcionka
i wyższe wiersze, kolumny bliżej siebie (tabela najwyżej 760 px); dane na prawo od zdjęcia w trzech linijkach
(lines): wingspan, ARC, length / MTOW, MLW, WTC / VMO, MMO, ceiling; reszta (wysokość, IATA, opis, silniki, WTG,
opis słownie) nie jest pokazywana w rozwinięciu, ale zostaje w bazie i w API."""
import json
import os
import re
import shutil
import subprocess
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.routers import aircraft as aircraft_router  # noqa: E402
from backend.app.services import photos  # noqa: E402

FRONTEND = ROOT_DIR / "frontend"
SRC = (FRONTEND / "js" / "tabs" / "aircraft.js").read_text("utf-8")
CSS = (FRONTEND / "css" / "aircraft.css").read_text("utf-8")

STUB = r"""
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const h = () => null;
export const api = async () => [];
export const debounce = (f) => f;
export const letterMenu = () => ({ set() {} });
export const remember = () => {};
export const touchKeyboard = () => ({ el: {}, sync() {} });
"""

# rekordy jak z /api/aircraft (AT76, A30B z zakresami osiągów, śmigłowiec bez wymiarów i mas)
AT76 = {"id": 1, "icao": "AT76", "iata": "AT7", "manufacturer": "ATR", "model": "ATR-72-600", "description": "L2T",
        "wtc": "M", "wtg": "F", "recat": "E", "wingspan": 27.05, "length": 27.2, "height": 7.7, "mtow": 23000.0,
        "use": "A", "engine_count": 2, "engine_type": "turboprop", "mlw": 21850.0, "mlw_max": None, "ceiling_ft": 25000.0,
        "ceiling_ft_max": None, "vmo_kt": 250.0, "vmo_kt_max": None, "mmo": 0.55, "mmo_max": None}
A30B = {**AT76, "icao": "A30B", "iata": "AB4", "manufacturer": "AIRBUS", "model": "A-300(B2/B4/C4/F4)",
        "description": "L2J", "wtc": "H", "wtg": "C", "recat": "C", "wingspan": 44.84, "length": 53.62, "height": 16.53,
        "mtow": 165000.0, "engine_type": "turbofan", "mlw": 122000.0, "mlw_max": 136000.0, "ceiling_ft": 37000.0,
        "ceiling_ft_max": 41000.0, "vmo_kt": 345.0, "vmo_kt_max": 360.0, "mmo": 0.82, "mmo_max": 0.86}
EC35 = {"id": 3, "icao": "EC35", "iata": None, "manufacturer": "AIRBUS HELICOPTERS", "model": "EC-135 <test>",
        "description": "H2T", "wtc": "L", "wtg": None, "recat": None, "wingspan": 10.2, "length": None, "height": None,
        "mtow": None, "engine_count": None, "engine_type": None, "mlw": None, "ceiling_ft": None, "vmo_kt": None,
        "mmo": None}
# sprzężone silniki (LCT) i typ zbiorczy bez opisu
C08T = {**EC35, "id": 4, "icao": "C08T", "manufacturer": "CESSNA", "model": "Skymaster", "description": "LCT",
        "recat": "F", "wingspan": None}
ZZZZ = {**EC35, "id": 5, "icao": "ZZZZ", "manufacturer": None, "model": None, "description": None, "wtc": None,
        "wingspan": None}

# grupy GA wymieszane i różnej wielkości (kolejność z issue niezależna od wielkości), dwie grupy spoza listy
GA_ROWS = [{"icao": f"{m[:3]}{i}", "manufacturer": m} for m, n in
           (("CESSNA", 5), ("OTHER BIG", 6), ("BELL", 3), ("TECNAM", 1), ("PIPER", 4), ("DIAMOND", 2), ("AERO", 1),
            ("OTHER SMALL", 1), ("ROBINSON", 1), ("PILATUS", 1)) for i in range(n)]

NODE_SCRIPT = r"""
const ac = await import(process.argv[2]);
const recs = JSON.parse(process.argv[3]);
const ga = JSON.parse(process.argv[4]);
const order = (k) => ac.MAKERS.find((m) => m[0] === k)[3];
const spans = [null, 0, 9.8, 14.99, 15, 23.99, 24, 35.99, 36, 51.99, 52, 64.99, 65, 79.99, 80, 117];
const each = (f) => Object.fromEntries(Object.entries(recs).map(([k, a]) => [k, f(a)]));
// silniki: opis typu z liczbą i bez, liczba i rodzaj z bazy, sam rodzaj z bazy (także "turbojet/turbofan"), śmigłowiec,
// tiltrotor, sprzężone z liczbą w bazie, nieznany rodzaj (opis "---", rodzaj spoza listy), nic
const ENGINES = [{ description: "LCT" }, { description: "L4J", engine_count: 4, engine_type: "turbofan" },
  { description: "L2J" }, { engine_type: "piston" }, { description: "H1T" }, {}, { description: "T2T" },
  { description: "L4T", engine_count: 4, engine_type: "turboprop" }, { description: "L1P", engine_count: 1 },
  { engine_count: 2, engine_type: "Turbojet/turbofan" }, { description: "LCT", engine_count: 2, engine_type: "turboprop" },
  { description: "L2E" }, { description: "L1R" }, { description: "---", engine_count: 3 }, { engine_count: 1, engine_type: "steam" },
  { description: "H2T", engine_count: 2, engine_type: "turboshaft" }, { description: "A2P" }, { engine_type: "propfan" }];
console.log(JSON.stringify({
  makers: ac.MAKERS.map(([k, l, t]) => [k, l, t]),
  columns: ac.COLUMNS.map(([k, l]) => [k, l]),
  head: ac.tableHead(),
  lines: each(ac.lines),
  cells: each(ac.cells),
  record: each((a) => ac.record(a, 7)),
  detail: each(ac.detail),
  gaGroups: ac.makerGroups(ga, order("ga")).map(([name, list]) => [name, list.map((a) => a.icao)]),
  airbusGroups: ac.makerGroups([{ icao: "EC35", manufacturer: "AIRBUS HELICOPTERS" }, { icao: "H160", manufacturer: "AIRBUS HELICOPTERS" },
    { icao: "A320", manufacturer: "AIRBUS" }], order("airbus")).map(([name]) => name),
  bombardierGroups: ac.makerGroups([{ manufacturer: "DE HAVILLAND CANADA" }, { manufacturer: "DE HAVILLAND CANADA" },
    { manufacturer: "LEARJET" }, { manufacturer: "GATES LEARJET" }, { manufacturer: "CANADAIR" }, { manufacturer: "BOMBARDIER" }],
    order("bombardier")).map(([name]) => name),
  arc: spans.map((s) => ac.arcCode({ wingspan: s, description: "L2J" })),
  arcHeli: ac.arcCode({ wingspan: 10.2, description: "H2T" }),
  engines: ENGINES.map(ac.engines),
  engineLabel: ENGINES.map(ac.engineLabel),
  mlw: [[1970, 2047], [1202, 1247], [490, 522], [122000, 136000], [21850, null], [21850, 21850]]
    .map(([lo, hi]) => ac.lines({ icao: "X", mlw: lo, mlw_max: hi })[1][1].find((b) => b.label === "MLW").value),
  credit: [{ credit: "Wikipedia: ATR 72", page: "https://en.wikipedia.org/wiki/ATR_72" },
    { credit: "J. Kowalski <own>", page: null }, { credit: "", page: null }].map(ac.photoCredit),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text(STUB, "utf-8")
    (d / "aircraft.mjs").write_text(SRC.replace('"../api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    recs = json.dumps({"AT76": AT76, "A30B": A30B, "EC35": EC35, "C08T": C08T, "ZZZZ": ZZZZ})
    r = subprocess.run([node, str(script), (d / "aircraft.mjs").as_uri(), recs, json.dumps(GA_ROWS)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# --- przyciski producentów i grupy ----------------------------------------------------------------------------------

def test_five_maker_buttons(js):
    assert [k for k, _, _ in js["makers"]] == ["airbus", "boeing", "bombardier", "embraer", "ga"]
    assert [lbl for _, lbl, _ in js["makers"]] == ["AIRBUS", "BOEING", "BOMBARDIER", "EMBRAER", "GA"]
    # te same klucze co ?maker= w backendzie (inne to 400)
    assert [k for k, _, _ in js["makers"]] == list(aircraft_router.MAKERS)
    titles = {k: t for k, _, t in js["makers"]}
    assert titles["ga"] == "General aviation: Pilatus, Diamond, Cessna, Piper, Aero AT-3, Robinson, Bell, Tecnam"
    for t in titles.values():
        assert not PROVENANCE.search(t), t


def test_ga_groups_in_issue_order(js):
    # kolejność z issue (Pilatus, Diamond, Cessna, Piper, AT3, Robinson, Bell, Tecnam) niezależnie od wielkości grup;
    # grupy spoza listy na końcu od największej; w grupie kolejność z serwera
    assert [name for name, _ in js["gaGroups"]] == ["PILATUS", "DIAMOND", "CESSNA", "PIPER", "AERO", "ROBINSON", "BELL",
                                                    "TECNAM", "OTHER BIG", "OTHER SMALL"]
    assert dict(js["gaGroups"])["CESSNA"] == ["CES0", "CES1", "CES2", "CES3", "CES4"]
    assert js["airbusGroups"] == ["AIRBUS", "AIRBUS HELICOPTERS"]
    assert js["bombardierGroups"] == ["BOMBARDIER", "CANADAIR", "LEARJET", "GATES LEARJET", "DE HAVILLAND CANADA"]


# --- domyślny widok: wiersz tabeli ----------------------------------------------------------------------------------

def test_columns_in_issue_order(js):
    assert js["columns"] == [["icao", "ICAO"], ["mk", "Manufacturer"], ["name", "Name"], ["eng", "Engines"],
                             ["wtc", "WTC"], ["recat", "RECAT"]]
    head = js["head"]
    assert re.findall(r"<th class=\"([a-z]+)\"[^>]*>([^<]+)</th>", head) == [tuple(c) for c in js["columns"]]
    assert head.startswith("<thead><tr>") and head.endswith("</tr></thead>")
    assert 'title="ICAO wake turbulence category"' in head


def test_cells_six_values(js):
    def kv(name):
        return [(c["key"], c["value"]) for c in js["cells"][name]]
    # 0.14.0 (issue #28): silniki z liczbą i rodzajem ("2 Turboprop", "2 Jet")
    assert kv("AT76") == [("icao", "AT76"), ("mk", "ATR"), ("name", "ATR-72-600"), ("eng", "2 Turboprop"), ("wtc", "M"),
                          ("recat", "E|M↓")]
    by = {c["key"]: c for c in js["cells"]["AT76"]}
    # dymek silników tylko, gdy mówi więcej niż kolumna (tu to samo: bez dymku)
    assert by["eng"]["title"] == "" and by["wtc"]["title"] == "Medium"
    assert by["recat"]["title"] == "RECAT-EU E – Lower Medium" and by["recat"]["cls"] == "recat-E"
    # pełna nazwa ICAO bez skracania; odrzutowiec: w kolumnie "Jet", w dymku rodzaj z bazy (turbofan)
    assert kv("A30B")[2] == ("name", "A-300(B2/B4/C4/F4)") and kv("A30B")[5] == ("recat", "C|H↓")
    assert kv("A30B")[3] == ("eng", "2 Jet") and {c["key"]: c for c in js["cells"]["A30B"]}["eng"]["title"] == "2 turbofan"
    # silniki z opisu typu, gdy brak w bazie (H2T: 2 turbiny wałowe, LCT: sprzężone)
    assert kv("EC35") == [("icao", "EC35"), ("mk", "AIRBUS HELICOPTERS"), ("name", "EC-135 <test>"), ("eng", "2 Turboshaft"),
                          ("wtc", "L"), ("recat", "")]
    assert kv("C08T")[3] == ("eng", "Coupled Turboprop") and kv("C08T")[5] == ("recat", "F|L")
    assert kv("ZZZZ") == [("icao", "ZZZZ"), ("mk", ""), ("name", ""), ("eng", ""), ("wtc", ""), ("recat", "")]
    assert not {c["key"]: c for c in js["cells"]["EC35"]}["recat"]["cls"]


def test_record_markup(js):
    html = js["record"]["AT76"]
    assert html == ('<tr class="ac-rec" data-i="7"><td class="icao">AT76</td><td class="mk">ATR</td>'
                    '<td class="name">ATR-72-600</td><td class="eng">2 Turboprop</td>'
                    '<td class="wtc" title="Medium">M</td>'
                    '<td class="recat recat-E" title="RECAT-EU E – Lower Medium">E|M↓</td></tr>')
    assert '<td class="eng" title="2 turbofan">2 Jet</td>' in js["record"]["A30B"]
    # w wierszu nic więcej (odnośnik do osiągów i kratki są w rozwinięciu)
    for k in ("AT76", "A30B", "EC35", "C08T", "ZZZZ"):
        rec = js["record"][k]
        assert rec.count("<td") == 6 and "<a" not in rec and "acb" not in rec, k
        assert not PROVENANCE.search(_visible(rec)), k
    # nazwa z bazy escapowana
    assert '<td class="name">EC-135 &lt;test&gt;</td>' in js["record"]["EC35"] and "<test>" not in js["record"]["EC35"]
    assert '<td class="recat"></td>' in js["record"]["EC35"]
    assert '<td class="eng"></td>' in js["record"]["ZZZZ"]


# --- rozwinięcie -----------------------------------------------------------------------------------------------------

def _lines(name, js):
    return [(cat, [(b["cat"], b["label"], b["value"]) for b in row]) for cat, row in js["lines"][name]]


def test_three_lines_of_data(js):
    """0.14.0 (issue #28): 1) wingspan, ARC, length (bez wysokości), 2) MTOW, MLW, WTC, 3) VMO, MMO, ceiling;
    każda linijka w kolorze swojej kategorii."""
    assert _lines("AT76", js) == [
        ("dim", [("dim", "WINGSPAN", "27.05 m"), ("dim", "ARC", "C"), ("dim", "LENGTH", "27.2 m")]),
        ("wake", [("wake", "MTOW", "23 t"), ("wake", "MLW", "21.9 t"), ("wake", "WTC", "M")]),
        ("perf", [("perf", "VMO", "250 kt"), ("perf", "MMO", "M0.55"), ("perf", "CEILING", "FL250")])]
    rows = [b for _, row in js["lines"]["AT76"] for b in row]
    assert not any(b.get("none") for b in rows)
    by = {b["label"]: b for b in rows}
    assert by["WTC"]["title"] == "Medium" and by["ARC"]["title"] == "Aerodrome reference code (wingspan)"
    assert "title" not in by["LENGTH"] and "title" not in by["WINGSPAN"]
    # reszta danych nie jest pokazywana (zostaje w bazie i w API, test_api_keeps_hidden_values)
    for name in ("AT76", "A30B", "EC35", "C08T", "ZZZZ"):
        labels = [b["label"] for _, row in js["lines"][name] for b in row]
        assert len(labels) == 9 and not {"HEIGHT", "IATA", "DESC", "ENG", "WTG"} & set(labels), name


def test_lines_ranges_of_production_variants(js):
    by = {b["label"]: b["value"] for _, row in js["lines"]["A30B"] for b in row}
    assert by["VMO"] == "345–360 kt" and by["MMO"] == "M0.82–0.86" and by["MLW"] == "122–136 t"
    assert by["CEILING"] == "FL370–410" and by["MTOW"] == "165 t" and by["ARC"] == "D" and by["WTC"] == "H"
    assert by["WINGSPAN"] == "44.84 m" and by["LENGTH"] == "53.62 m"
    # zakres tylko, gdy wartości różnią się po zaokrągleniu (lekkie typy: MLW 1970 i 2047 kg to "2 t", nie "2–2 t")
    assert js["mlw"] == ["2 t", "1.2 t", "0.5 t", "122–136 t", "21.9 t", "21.9 t"]


def test_missing_values_are_dashes(js):
    # śmigłowiec: pole rozpiętości to średnica wirnika (ROTOR), bez ARC; każdy brak to półpauza w tej samej kratce
    # (siatka się nie przesuwa)
    assert _lines("EC35", js) == [
        ("dim", [("dim", "ROTOR", "10.2 m"), ("dim", "ARC", "–"), ("dim", "LENGTH", "–")]),
        ("wake", [("wake", "MTOW", "–"), ("wake", "MLW", "–"), ("wake", "WTC", "L")]),
        ("perf", [("perf", "VMO", "–"), ("perf", "MMO", "–"), ("perf", "CEILING", "–")])]
    assert [bool(b.get("none")) for _, row in js["lines"]["EC35"] for b in row] == [False, True, True, True, True,
                                                                                     False, True, True, True]
    html = js["detail"]["EC35"]
    assert '<div class="acb dim none" title="Aerodrome reference code (wingspan)"><span class="lbl">ARC</span>' in html
    assert '<div class="acb dim" title="Rotor diameter"><span class="lbl">ROTOR</span><span class="val">10.2 m</span></div>' in html
    assert '<div class="acb wake" title="Light"><span class="lbl">WTC</span><span class="val">L</span></div>' in html
    assert '<span class="val"></span>' not in html
    # typ bez żadnych wartości: dziewięć kratek z półpauzą (WTC bez dymku)
    zz = js["detail"]["ZZZZ"]
    assert zz.count('class="acb ') == 9 and zz.count(" none") == 9
    assert '<div class="acb wake none"><span class="lbl">WTC</span><span class="val">–</span></div>' in zz


def _line_labels(html):
    return [re.findall(r'<span class="lbl">([A-Z]+)</span>', m)
            for m in re.findall(r'<div class="ac-line [a-z]+">(.*?</div>)</div>', html)]


def test_detail_markup(js):
    html = js["detail"]["AT76"]
    # wiersz pod klikniętym na całą szerokość tabeli (6 kolumn)
    assert html.startswith('<tr class="ac-detail-row"><td colspan="6"><div class="ac-detail"><div class="ac-split">')
    assert html.rstrip().endswith("</div></div></td></tr>")
    # 0.14.0 (issue #28): zdjęcie, na prawo od niego dane (kratki w trzech linijkach, pod nimi odnośniki)
    marks = ['class="photo-box"', 'class="ac-data"', 'class="ac-boxes"', 'class="ac-line dim"', 'class="ac-line wake"',
             'class="ac-line perf"', 'class="ac-links"']
    assert [html.index(m) for m in marks] == sorted(html.index(m) for m in marks)
    split = html[html.index('<div class="ac-split">'):]
    assert re.match(r'<div class="ac-split">\s*<div class="photo-box"><span class="hint">Loading photo…</span></div>\s*'
                    r'<div class="ac-data">', split)
    assert _line_labels(html) == [["WINGSPAN", "ARC", "LENGTH"], ["MTOW", "MLW", "WTC"], ["VMO", "MMO", "CEILING"]]
    assert _line_labels(js["detail"]["EC35"])[0] == ["ROTOR", "ARC", "LENGTH"]
    # reszta danych zniknęła z rozwinięcia: wysokość, IATA, opis typu i kategorii słownie, silniki, WTG
    for k in ("AT76", "A30B", "EC35", "C08T", "ZZZZ"):
        d = js["detail"][k]
        assert not re.search(r">(HEIGHT|IATA|DESC|ENG|WTG)<", d), k
        assert "ac-info" not in d and "landplane" not in d and "RECAT-EU" not in d, k
    assert "7.7 m" not in html and "AT7<" not in html
    # strona osiągów typu jako pierwszy odnośnik, potem zdjęcia i wyszukiwarki
    links = re.findall(r"<a[^>]*>([^<]+)</a>", html[html.index('class="ac-links"'):])
    assert links == ["Performance ↗", "More photos ↗", "Image search ↗", "Performance search ↗"]
    assert re.search(r'<a class="ac-perf" href="[^"]*details\.aspx\?ICAO=AT76"[^>]*>Performance ↗</a>', html)
    assert "keyword/ATR%20ATR-72-600" in html
    # wyszukiwarka bazy osiągów (typy bez własnej strony osiągów), nazwana wg funkcji
    assert re.search(r'<a href="[^"]*/default\.aspx"[^>]*>Performance search ↗</a>', html)
    for k in ("AT76", "A30B", "EC35", "C08T", "ZZZZ"):
        assert not PROVENANCE.search(_visible(js["detail"][k])), k
    # nazwa z bazy w adresach wyszukiwarek zakodowana
    assert "<test>" not in js["detail"]["EC35"] and "EC-135%20%3Ctest%3E" in js["detail"]["EC35"]
    # 0.13.3: Airbus bez łącznika po A w wyszukiwarkach zdjęć (jak photo_query), inni producenci bez zmian
    assert "keyword/AIRBUS%20A300" in js["detail"]["A30B"] and "A-300" not in js["detail"]["A30B"].split("ac-links")[1]


def test_no_bold_markup(js):
    """Cała aplikacja bez pogrubień: wartości kratek w <span>, nie w <b>."""
    for kind in ("record", "detail"):
        for k, html in js[kind].items():
            assert not re.search(r"<(b|strong)\b", html), (kind, k)
    assert not re.search(r"<(b|strong)\b", SRC)


def test_arc_code_letters(js):
    # ICAO Annex 14: A < 15 m, B < 24 m, C < 36 m, D < 52 m, E < 65 m, F < 80 m
    assert js["arc"] == ["", "", "A", "A", "B", "B", "C", "C", "D", "D", "E", "E", "F", "F", "", ""]
    assert js["arcHeli"] == ""


def test_engine_label_count_and_type(js):
    """0.14.0 (issue #28): liczba i rodzaj silników ("2 Jet"): kategoria z opisu ICAO (J Jet, T Turboprop, u śmigłowca
    i tiltrotora Turboshaft, P Piston, E Electric, R Rocket), bez opisu z engine_type z bazy; nieznany rodzaj: sama
    liczba; sprzężone bez liczby w bazie: Coupled."""
    assert js["engineLabel"] == ["Coupled Turboprop", "4 Jet", "2 Jet", "Piston", "1 Turboshaft", "", "2 Turboshaft",
                                 "4 Turboprop", "1 Piston", "2 Jet", "2 Turboprop", "2 Electric", "1 Rocket", "3", "1",
                                 "2 Turboshaft", "2 Piston", "Turboprop"]


def test_engines_detail_for_title(js):
    # dymek kolumny silników: rodzaj z bazy; tiltrotor (T2T) ma turbiny wałowe jak śmigłowiec
    assert js["engines"][:7] == ["coupled turboprop", "4 turbofan", "2 jet", "piston", "1 turboshaft", "",
                                 "2 turboshaft"]
    assert js["engines"][9] == "2 Turbojet/turbofan"


def _visible(html):
    """Tekst widoczny dla użytkownika: bez znaczników i adresów (href), z dymkami title."""
    titles = " ".join(re.findall(r'title="([^"]*)"', html))
    return re.sub(r"<[^>]+>", " ", html) + " " + titles


PROVENANCE = re.compile(r"eurocontrol|icao_aircraft|aircraft-database|aircraft\.csv|doc 8643|wikipedia|jetphotos|google"
                        r"|source|from |data/photos|atciss", re.I)


def test_photo_credit_names_no_source(js):
    # strona zdjęcia (autor, licencja) jako odnośnik nazwany wg funkcji; własny podpis bez strony jako tekst
    page, own, empty = js["credit"]
    assert page == '<a href="https://en.wikipedia.org/wiki/ATR_72" target="_blank" rel="noopener">Photo page ↗</a>'
    assert not PROVENANCE.search(_visible(page))
    assert own == "J. Kowalski &lt;own&gt;" and empty == ""


# --- mount(): zachowanie z kodu źródłowego ---------------------------------------------------------------------------

def test_mount_table_and_detail_row():
    """Lista to tabela z nagłówkiem, wiersze w tbody; rozwinięcie wstawiane jako wiersz za klikniętym (nie krok
    historii); widok producenta grupuje wg kolejności z MAKERS; dawny adres producenta otwiera ALL."""
    assert '<div class="ac-list"><table class="data ac-table">${tableHead()}<tbody></tbody></table></div>' in SRC
    assert 'rec.insertAdjacentHTML("afterend", detail(current));' in SRC
    assert 'body.querySelectorAll("tr.ac-detail-row").forEach((x) => x.remove());' in SRC
    click = SRC[SRC.index('list.addEventListener("click"'):SRC.index('pane.querySelector(".ac-makers").addEventListener')]
    assert "remember(" not in click
    assert "makerGroups(data, mk[3])" in SRC
    assert '<tr class="ac-gh"><td colspan="${COLUMNS.length}">' in SRC
    assert " \\u00b7 click a type for details" in SRC
    # maker/<klucz spoza MAKERS> (#aircraft/maker/atr, /mcdonnell, /cessna): ALL i adres #aircraft bez nowego kroku
    act = SRC[SRC.index("return { activate: (arg) => {"):]
    assert re.search(r'\} else if \(mk !== null\) \{\n\s+if \(prefix \|\| maker \|\| \$\("\.q"\)\.value\) \{ \$\("\.q"\)\.value = ""; '
                     r'prefix = ""; setMaker\(""\); letters\.set\(""\); load\(\); \}\n\s+remember\("aircraft", "", '
                     r'\{ replace: true \}\);', act)
    assert act.index("MAKERS.some(([k]) => k === mk)") < act.index("} else if (mk !== null) {")


def test_code_lines_ascii():
    """Poza samodzielnymi komentarzami tylko ASCII (symbole napisów jako \\uXXXX)."""
    for n, line in enumerate(SRC.splitlines(), 1):
        if line.strip().startswith("//"):
            continue
        bad = {c for c in line if ord(c) > 127}
        assert not bad, (n, sorted(hex(ord(c)) for c in bad))


def test_no_provenance_strings_in_code():
    """Napisy w aircraft.js (poza komentarzami i adresami) bez nazw źródeł danych."""
    code = "\n".join(line for line in SRC.splitlines() if not line.strip().startswith("//"))
    code = re.sub(r"https?://[^\s\"'`]+", "", code)
    for word in ("ICAO_Aircraft", "aircraft-database", "EUROCONTROL", "Wikipedia", "JetPhotos", "Google Images",
                 "Source:", "data/photos", "database search"):
        assert word not in code, word


def _css_rule(selector):
    text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    m = re.search(r"(?m)^" + re.escape(selector) + r" \{([^}]*)\}", text)
    assert m, selector
    return m.group(1)


def test_css_flat_and_linked():
    index = (FRONTEND / "index.html").read_text("utf-8")
    assert 'href="/static/css/aircraft.css"' in index
    text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert all(r.strip() == "0" for r in re.findall(r"border-radius:\s*([^;}]+)", text))
    assert "text-shadow" not in text and "font-weight" not in text and "bold" not in text
    assert all(v.strip().startswith("inset") for v in re.findall(r"box-shadow:\s*([^;}]+)", text))
    # wartość wyraźnie większa od etykiety
    label = int(re.search(r"\.acb > \.lbl \{[^}]*font: (\d+)px", text).group(1))
    value = int(re.search(r"\.acb > \.val \{[^}]*font: (\d+)px", text).group(1))
    assert value >= label + 6
    assert "color: var(--muted);" in _css_rule(".acb.none > .val")
    # trzy kategorie (linijki) w różnych kolorach
    bgs = {c: re.search(rf"\.acb\.{c} \{{[^}}]*background: (#[0-9a-f]{{6}})", text).group(1)
           for c in ("perf", "wake", "dim")}
    assert len(set(bgs.values())) == 3
    # bez nazw, które chowają blokery reklam
    assert not re.search(r"[.#](ad-|ads|advert|banner|sponsor|promo)", text, re.I)
    assert not re.search(r'class="[^"]*\b(ad-|ads\b|advert|banner|sponsor|promo)', SRC, re.I)


def test_css_three_lines_right_of_photo():
    """0.14.0 (issue #28): dane na prawo od zdjęcia (flex w rzędzie, zdjęcie się zmniejsza, dane nie), trzy linijki
    po trzy kratki w siatce; pod zdjęcie dane schodzą tylko w wąskim panelu (zapytanie o kontener rozwinięcia).
    Rozwinięcie najwyżej na widoczną szerokość listy i przyklejone do jej lewej krawędzi (lista przewijana w bok)."""
    text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    split = _css_rule(".ac-split")
    assert "display: flex;" in split and "flex-direction" not in split and "flex-wrap" not in split
    assert "align-items: flex-start;" in split
    photo = _css_rule(".ac-split > .photo-box")
    assert "flex: 0 1 auto;" in photo and "min-width: 0;" in photo
    data = _css_rule(".ac-data")
    assert "flex: none;" in data and "width: min-content;" in data
    # siatka 3 x 3: linijka bez własnego pudełka, kratki w kolumnach
    assert "grid-template-columns: repeat(3, max-content);" in _css_rule(".ac-boxes")
    assert "display: contents;" in _css_rule(".ac-line")
    # dane pod zdjęciem dopiero w wąskim kontenerze rozwinięcia
    detail = _css_rule(".ac-detail")
    assert "container: ac-detail / inline-size;" in detail
    assert "position: sticky;" in detail and "width: min(100%, calc(100cqi - 22px));" in detail
    assert "container-type: inline-size;" in _css_rule(".ac-list")
    q = re.search(r"@container ac-detail \(max-width: (\d+)px\) \{\s*\.ac-split \{ flex-direction: column; \}\s*\}", text)
    assert q and 520 <= int(q.group(1)) <= 640
    # zdjęcie w proporcjach pliku
    img = _css_rule(".ac-detail .photo-box img")
    assert "max-height: 300px;" in img and "max-width: min(640px, 100%);" in img and "object-fit" not in img
    assert "ac-info" not in text and ".acb.id" not in text


def test_css_table():
    text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    # przyciski producentów tej samej wielkości co przyciski menu (miary powłoki z style.css)
    makers = _css_rule(".ac-makers .gbtn")
    for decl in ("width: var(--btn-w);", "height: var(--btn-h);", "margin: var(--btn-m);",
                 "line-height: calc(var(--btn-h) - 2px);"):
        assert decl in makers, decl
    assert "min-width" not in makers and "padding: 0 4px;" in makers
    # rząd producentów na wysokości pierwszego rzędu menu
    assert "padding-top: var(--col-pad);" in _css_rule(".ac-pane")
    # tabela o stałych kolumnach, nazwa się zawija
    table = _css_rule("table.ac-table")
    assert "table-layout: fixed;" in table
    assert "nowrap" in _css_rule(".ac-table tr.ac-rec td.icao") and "nowrap" not in _css_rule(".ac-table td.name")
    # 0.14.0 (issue #28): większa czcionka i wyższe wiersze (dawniej 13 px i padding 4 px), kolumny bliżej siebie:
    # tabela najwyżej 760 px (dawniej 980), na nazwę zostaje najwyżej 280 px
    rec = _css_rule(".ac-table tr.ac-rec td")
    assert int(re.search(r"font-size: (\d+)px;", rec).group(1)) >= 16
    assert int(re.search(r"padding: (\d+)px", rec).group(1)) >= 6
    assert int(re.search(r"font-size: (\d+)px;", _css_rule(".ac-table tr.ac-rec td.icao")).group(1)) >= 17
    ceiling = float(re.search(r"max-width: (\d+)px;", table).group(1))
    # w wąskim panelu (tablet pionowo) kolumna nazwy nie znika: tabela co najmniej 640 px (lista przewija się w bok),
    # na nazwę zostaje co najmniej 160 px poza stałymi kolumnami; nazwa łamana na spacjach, nie po jednej literze
    floor = re.search(r"min-width: (\d+)px;", table)
    assert floor, "table.ac-table bez min-width"
    floor = float(floor.group(1))
    widths = {c: float(re.search(r"width: (\d+)px;", _css_rule(f".ac-table th.{c}")).group(1))
              for c in ("icao", "mk", "eng", "wtc", "recat")}
    fixed = sum(widths.values())
    assert floor == 640 and fixed == 480 and floor - fixed >= 160
    assert ceiling == 760 and ceiling - fixed <= 280
    # kolumna silników mieści "2 Turboshaft" przy 16 px (ok. 89 px tekstu + 16 px paddingu), łamana tylko na spacji
    assert widths["eng"] >= 108
    eng = _css_rule(".ac-table td.eng")
    assert "overflow-wrap: normal;" in eng and "nowrap" not in eng
    assert "overflow: auto;" in _css_rule(".ac-list")
    assert "overflow-wrap: break-word;" in _css_rule(".ac-table td.name")
    # RECAT-EU w kolorze kategorii, także w zaznaczonym wierszu
    for k, color in (("A", "#ff6a5a"), ("B", "#ff6a5a"), ("C", "var(--yellow)"), ("D", "var(--yellow)"),
                     ("E", "var(--ok)"), ("F", "var(--ok)")):
        assert re.search(rf"table\.ac-table tr td\.recat-{k}[^{{]*\{{ color: {re.escape(color)}; \}}", text), k
    # paski wierszy tylko po wierszach typów (rozwinięcie nie przestawia kolorów), rozwinięcie bez podświetlenia
    assert "table.ac-table tbody tr.ac-rec:nth-child(even of .ac-rec) td { background: var(--row-alt); }" in text
    assert "background: var(--sel) !important;" in _css_rule("table.ac-table tbody tr.ac-detail-row td")
    assert "background: var(--head) !important;" in _css_rule("table.ac-table tbody tr.ac-gh td")


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_api_has_no_source_field(client):
    a = client.get("/api/aircraft", params={"q": "AT76"}).json()[0]
    assert a["icao"] == "AT76" and "source" not in a
    assert "source" not in client.get(f"/api/aircraft/{a['id']}").json()


def test_api_keeps_hidden_values(client):
    """0.14.0 (issue #28): wartości, których rozwinięcie już nie pokazuje (wysokość, IATA, opis typu, WTG, rodzaj
    i liczba silników), zostają w bazie i w API "na wszelki wypadek"."""
    a = client.get("/api/aircraft", params={"q": "AT76"}).json()[0]
    assert a["icao"] == "AT76"
    assert a["height"] and a["iata"] and a["description"] == "L2T" and a["wtg"] and a["engine_count"] == 2
    assert {"engine_type", "use", "mlw_max", "ceiling_ft_max", "vmo_kt_max", "mmo_max"} <= set(a)
    assert client.get(f"/api/aircraft/{a['id']}").json()["height"] == a["height"]


def test_photo_error_is_neutral(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "photos_dir", tmp_path)
    monkeypatch.setattr(photos, "_missing", set())

    async def broken(icao, manufacturer, model, strict=False):
        raise httpx.ConnectError("[Errno -3] wikipedia.org unreachable")

    monkeypatch.setattr(photos, "fetch_photo", broken)
    a = client.get("/api/aircraft", params={"q": "B738"}).json()[0]
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 502 and r.json()["detail"] == "Photo unavailable"
    # własne zdjęcie bez pliku opisu: bez podpisu
    (tmp_path / "B738.jpg").write_bytes(b"\xff\xd8\xff")
    own = client.get(f"/api/aircraft/{a['id']}/photo").json()
    assert own["url"].startswith("/files/photos/B738.jpg?v=") and own["credit"] == "" and own["page"] is None


def test_touch_keyboard_hook():
    """0.13.1 (issue #25): klawiatura dotykowa ("()" pod ALL, api.js touchKeyboard) jako ostatnie dziecko .ac-pane,
    pod przewijaną listą; producent zdejmuje zaznaczenie liter, ale nie "()"; activate() ustawia stan klawiatury
    wg wspólnego wyboru przed fokusem w polu (test_touch_keyboard.py sprawdza samą klawiaturę)."""
    assert re.search(r'^import \{[^}]*\btouchKeyboard\b[^}]*\} from "\.\./api\.js";', SRC, re.M)
    assert 'const kbd = touchKeyboard(pane.querySelector(".q"), letters.kbd);\n    pane.append(kbd.el);' in SRC
    # dołączona po zbudowaniu panelu (po .ac-list), nic nie jest potem dopisywane na koniec panelu
    assert SRC.index("root.append(pane);") < SRC.index("pane.append(kbd.el);")
    assert SRC.count("pane.append(") == 1 and "pane.insertAdjacent" not in SRC
    assert 'root.querySelectorAll(".submenu.letters button[data-l].active")' in SRC
    assert re.search(r'kbd\.sync\(\);\n\s+\$\("\.q"\)\.focus\(\);', SRC)
