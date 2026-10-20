"""0.12.6 (issue #21, AIRCRAFT): "bardziej zaznacz te wartości, np w kwadraty" – wartości rekordu w kratkach jak w ATCISS:
mała etykieta nad dużą wartością, kolor kratki wg kategorii (identyfikacja, osiągi, masa i turbulencja, wymiary), puste
wartości bez kratek. Do tego bez dopisków skąd dane (plik ICAO, baza osiągów, Wikipedia) w interfejsie.
Pomocnicze funkcje aircraft.js (boxes, record, detail, arcCode, engines, describe) wołane w Node z zastępczym api.js."""
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
"""

# rekordy jak z /api/aircraft (AT76, A30B z zakresami osiągów, śmigłowiec bez wymiarów)
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

NODE_SCRIPT = r"""
const ac = await import(process.argv[2]);
const recs = JSON.parse(process.argv[3]);
const spans = [null, 0, 9.8, 14.99, 15, 23.99, 24, 35.99, 36, 51.99, 52, 64.99, 65, 79.99, 80, 117];
console.log(JSON.stringify({
  boxes: Object.fromEntries(Object.entries(recs).map(([k, a]) => [k, ac.boxes(a)])),
  record: Object.fromEntries(Object.entries(recs).map(([k, a]) => [k, ac.record(a, 7)])),
  detail: Object.fromEntries(Object.entries(recs).map(([k, a]) => [k, ac.detail(a)])),
  arc: spans.map((s) => ac.arcCode({ wingspan: s, description: "L2J" })),
  arcHeli: ac.arcCode({ wingspan: 10.2, description: "H2T" }),
  engines: [{ description: "LCT" }, { description: "L4J", engine_count: 4, engine_type: "turbofan" },
    { description: "L2J" }, { engine_type: "piston" }, { description: "H1T" }, {}, { description: "T2T" }].map(ac.engines),
  mlw: [[1970, 2047], [1202, 1247], [490, 522], [122000, 136000], [21850, null], [21850, 21850]]
    .map(([lo, hi]) => ac.boxes({ icao: "X", mlw: lo, mlw_max: hi }).find((b) => b.label === "MLW").value),
  credit: [{ credit: "Wikipedia: ATR 72", page: "https://en.wikipedia.org/wiki/ATR_72" },
    { credit: "J. Kowalski <own>", page: null }, { credit: "", page: null }].map(ac.photoCredit),
  describe: ["L2J", "LCT", "H2T", null].map(ac.describe),
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
    recs = json.dumps({"AT76": AT76, "A30B": A30B, "EC35": EC35})
    r = subprocess.run([node, str(script), (d / "aircraft.mjs").as_uri(), recs], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _rows(boxes):
    return [(b["cat"], b["label"], b["value"]) for b in boxes]


def test_boxes_every_field_in_categories(js):
    # kolejność jak w ATCISS (ICAO, ENG, VMO, MMO, MTOW, WTC, RECAT, WINGSPAN, ARC, LENGTH, HEIGHT) plus pozostałe pola
    assert _rows(js["boxes"]["AT76"]) == [
        ("id", "ICAO", "AT76"), ("id", "IATA", "AT7"), ("id", "DESC", "L2T"),
        ("perf", "ENG", "2 turboprop"), ("perf", "VMO", "250 kt"), ("perf", "MMO", "M0.55"), ("perf", "CEILING", "FL250"),
        ("wake", "MTOW", "23 t"), ("wake", "MLW", "21.9 t"), ("wake", "WTC", "M"), ("wake", "WTG", "F"),
        ("wake", "RECAT", "E|M↓"),
        ("dim", "WINGSPAN", "27.05 m"), ("dim", "ARC", "C"), ("dim", "LENGTH", "27.2 m"), ("dim", "HEIGHT", "7.7 m")]
    icao = js["boxes"]["AT76"][0]
    assert icao.get("key") is True
    by = {b["label"]: b for b in js["boxes"]["AT76"]}
    assert by["RECAT"]["title"] == "RECAT-EU E – Lower Medium" and by["RECAT"]["cls"] == "recat-E"
    assert by["DESC"]["title"] == "landplane, 2 × turboprop/turboshaft" and by["WTC"]["title"] == "Medium"


def test_boxes_ranges_of_production_variants(js):
    by = {b["label"]: b["value"] for b in js["boxes"]["A30B"]}
    assert by["VMO"] == "345–360 kt" and by["MMO"] == "M0.82–0.86" and by["MLW"] == "122–136 t"
    assert by["CEILING"] == "FL370–410" and by["MTOW"] == "165 t" and by["RECAT"] == "C|H↓" and by["ARC"] == "D"
    assert by["WINGSPAN"] == "44.84 m" and by["LENGTH"] == "53.62 m"
    # zakres tylko, gdy wartości różnią się po zaokrągleniu (lekkie typy: MLW 1970 i 2047 kg to "2 t", nie "2–2 t")
    assert js["mlw"] == ["2 t", "1.2 t", "0.5 t", "122–136 t", "21.9 t", "21.9 t"]


def test_empty_values_have_no_boxes(js):
    # śmigłowiec: pole rozpiętości to średnica wirnika (ROTOR), bez ARC, bez pustych kratek; liczba i rodzaj silników
    # z opisu H2T
    assert _rows(js["boxes"]["EC35"]) == [("id", "ICAO", "EC35"), ("id", "DESC", "H2T"), ("perf", "ENG", "2 turboshaft"),
                                          ("wake", "WTC", "L"), ("dim", "ROTOR", "10.2 m")]
    assert "<b></b>" not in js["record"]["EC35"] and "–</b>" not in js["record"]["EC35"]


def test_arc_code_letters(js):
    assert js["arc"] == ["", "", "A", "A", "B", "B", "C", "C", "D", "D", "E", "E", "F", "F", "", ""]
    assert js["arcHeli"] == ""


def test_engines_and_description(js):
    # tiltrotor (T2T) ma turbiny wałowe jak śmigłowiec
    assert js["engines"] == ["coupled turboprop", "4 turbofan", "2 jet", "piston", "1 turboshaft", "", "2 turboshaft"]
    assert js["describe"] == ["landplane, 2 × jet", "landplane, coupled turboprop/turboshaft",
                              "helicopter, 2 × turboprop/turboshaft", ""]


def _visible(html):
    """Tekst widoczny dla użytkownika: bez znaczników i adresów (href), z dymkami title."""
    titles = " ".join(re.findall(r'title="([^"]*)"', html))
    return re.sub(r"<[^>]+>", " ", html) + " " + titles


PROVENANCE = re.compile(r"eurocontrol|icao_aircraft|aircraft-database|aircraft\.csv|doc 8643|wikipedia|jetphotos|google"
                        r"|source|from |data/photos|atciss", re.I)


def test_record_markup(js):
    html = js["record"]["AT76"]
    assert 'data-i="7"' in html and "<span>ATR ATR-72-600</span>" in html
    assert '<div class="acb id key"><span>ICAO</span><b>AT76</b></div>' in html
    assert '<div class="acb wake" title="RECAT-EU E – Lower Medium"><span>RECAT</span><b class="recat-E">E|M↓</b></div>' in html
    assert re.search(r'<a class="ac-perf" href="[^"]*details\.aspx\?ICAO=AT76"[^>]*>Performance ↗</a>', html)
    # nazwa z bazy escapowana
    assert "EC-135 &lt;test&gt;" in js["record"]["EC35"] and "<test>" not in js["record"]["EC35"]
    for k in ("AT76", "A30B", "EC35"):
        assert not PROVENANCE.search(_visible(js["record"][k])), k


def test_detail_markup(js):
    html = js["detail"]["AT76"]
    assert "L2T – landplane, 2 × turboprop/turboshaft" in html and "RECAT-EU E – Lower Medium" in html
    assert ">More photos ↗</a>" in html and ">Image search ↗</a>" in html and "Loading photo…" in html
    assert "keyword/ATR%20ATR-72-600" in html
    # wyszukiwarka bazy osiągów (typy bez własnej strony osiągów), nazwana wg funkcji
    assert re.search(r'<a href="[^"]*/default\.aspx"[^>]*>Performance search ↗</a>', html)
    for k in ("AT76", "A30B", "EC35"):
        assert not PROVENANCE.search(_visible(js["detail"][k])), k
    assert "RECAT-EU" not in js["detail"]["EC35"]


def test_photo_credit_names_no_source(js):
    # strona zdjęcia (autor, licencja) jako odnośnik nazwany wg funkcji; własny podpis bez strony jako tekst
    page, own, empty = js["credit"]
    assert page == '<a href="https://en.wikipedia.org/wiki/ATR_72" target="_blank" rel="noopener">Photo page ↗</a>'
    assert not PROVENANCE.search(_visible(page))
    assert own == "J. Kowalski &lt;own&gt;" and empty == ""


def test_code_lines_ascii_except_symbols():
    """Poza samodzielnymi komentarzami tylko ASCII i typograficzne symbole napisów (bez znaków łączących w regexach)."""
    allowed = set("–↗×…↑↓·›")
    for n, line in enumerate(SRC.splitlines(), 1):
        if line.strip().startswith("//"):
            continue
        bad = {c for c in line if ord(c) > 127} - allowed
        assert not bad, (n, sorted(hex(ord(c)) for c in bad))


def test_no_provenance_strings_in_code():
    """Napisy w aircraft.js (poza komentarzami i adresami) bez nazw źródeł danych."""
    code = "\n".join(line for line in SRC.splitlines() if not line.strip().startswith("//"))
    code = re.sub(r"https?://[^\s\"'`]+", "", code)
    for word in ("ICAO_Aircraft", "aircraft-database", "EUROCONTROL", "Wikipedia", "JetPhotos", "Google Images",
                 "Source:", "data/photos", "database search"):
        assert word not in code, word


def test_css_boxes_flat_and_linked():
    index = (FRONTEND / "index.html").read_text("utf-8")
    assert 'href="/static/css/aircraft.css"' in index
    text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert all(r.strip() == "0" for r in re.findall(r"border-radius:\s*([^;}]+)", text))
    assert "text-shadow" not in text
    assert all(v.strip().startswith("inset") for v in re.findall(r"box-shadow:\s*([^;}]+)", text))
    # wartość wyraźnie większa od etykiety; kratki się zawijają
    label = int(re.search(r"\.acb > span \{[^}]*font: 700 (\d+)px", text).group(1))
    value = int(re.search(r"\.acb > b \{[^}]*font: 700 (\d+)px", text).group(1))
    assert value >= label + 6
    assert re.search(r"\.ac-boxes \{[^}]*flex-wrap: wrap", text)
    # kolor kategorii RECAT-EU na wartości: selektor silniejszy od białej wartości (.acb > b)
    for k, color in (("A", "#ff6a5a"), ("B", "#ff6a5a"), ("C", "var(--yellow)"), ("D", "var(--yellow)"),
                     ("E", "var(--ok)"), ("F", "var(--ok)")):
        assert re.search(rf"\.acb > b\.recat-{k}[^{{]*\{{ color: {re.escape(color)}; \}}", text), k
    # cztery kategorie w różnych kolorach
    bgs = {c: re.search(rf"\.acb\.{c} \{{[^}}]*background: (#[0-9a-f]{{6}})", text).group(1)
           for c in ("id", "perf", "wake", "dim")}
    assert len(set(bgs.values())) == 4


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_api_has_no_source_field(client):
    a = client.get("/api/aircraft", params={"q": "AT76"}).json()[0]
    assert a["icao"] == "AT76" and "source" not in a
    assert "source" not in client.get(f"/api/aircraft/{a['id']}").json()


def test_photo_error_is_neutral(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "photos_dir", tmp_path)
    monkeypatch.setattr(photos, "_missing", set())

    async def broken(icao, query):
        raise httpx.ConnectError("[Errno -3] wikipedia.org unreachable")

    monkeypatch.setattr(aircraft_router, "fetch_photo", broken)
    a = client.get("/api/aircraft", params={"q": "B738"}).json()[0]
    r = client.get(f"/api/aircraft/{a['id']}/photo")
    assert r.status_code == 502 and r.json()["detail"] == "Photo unavailable"
    # własne zdjęcie bez pliku opisu: bez podpisu
    (tmp_path / "B738.jpg").write_bytes(b"\xff\xd8\xff")
    assert client.get(f"/api/aircraft/{a['id']}/photo").json() == {"url": "/files/photos/B738.jpg", "credit": "",
                                                                   "page": None}
