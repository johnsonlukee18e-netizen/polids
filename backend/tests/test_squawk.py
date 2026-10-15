"""SQUAWK (0.12.3, issue #13): kody SSR, pule FIR EPWW z arkusza EUROCONTROL CAL (importer), /api/squawk.

Arkusze w testach importera są SYNTETYCZNE (budowane w teście, wymyślone kody i układ kolumn) – to nie są dane
CAL; prawdziwy plik eurocontrol-icao-eur-cal-v4-13.xls nie był dostępny przy pisaniu importera."""
import importlib.util
import json
import os
import sys
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.importers import squawk_cal  # noqa: E402
from backend.app.services.squawk import lookup, normalize, parse_codes, pool_size, valid_code  # noqa: E402

SPECIAL = {"7500", "7600", "7700", "2000", "7000", "1000"}


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)   # bez startu aplikacji (baza niepotrzebna)


# --- kody i zakresy

def test_codes_are_four_octal_digits():
    assert all(valid_code(c) for c in ("0000", "7777", "0100", "7700"))
    assert not any(valid_code(c) for c in ("7800", "0900", "777", "77777", "", None, 7700, "77a0", " 7700"))
    assert pool_size("0100", "0177") == 64 and pool_size("0000", "7777") == 4096 and pool_size("7700", "7700") == 1


def test_parse_codes_from_spreadsheet_cells():
    assert parse_codes("0100-0177") == [("0100", "0177")]
    assert parse_codes("0100 – 0177") == [("0100", "0177")] == parse_codes("100 TO 177") == parse_codes("01XX")
    assert parse_codes("100") == [("0100", "0100")]          # kod zapisany w arkuszu jako liczba 100(.0)
    assert parse_codes("010X") == [("0100", "0107")]
    assert parse_codes("4400-4477, 4500-4507") == [("4400", "4477"), ("4500", "4507")]
    assert parse_codes("4400-4477\n4500") == [("4400", "4477"), ("4500", "4500")]
    for bad in ("", "EPWW", "0180-0190", "0177-0100", "12345", "08XX", "TRANSIT"):
        assert parse_codes(bad) is None, bad


def test_normalize_and_lookup():
    data = normalize({"_status": "czeka", "meta": "x", "pools": [
        {"from": "0200", "to": "0277", "count": 1, "unit": "EPWW"}, {"from": "0100", "unit": "EPKK"},
        {"from": "0177", "to": "0100"}, {"from": "0800", "to": "0877"}, {"from": 100, "to": 177}, "x"],
        "special": [{"code": "7700", "label": "EMERGENCY"}, {"code": "77"}, None]})
    assert data["status"] == "czeka" and data["meta"] is None
    # posortowane po kodzie, count przeliczony, pojedynczy kod bez "to" = pula jednego kodu, złe wpisy pominięte
    assert [(p["from"], p["to"], p["count"]) for p in data["pools"]] == [("0100", "0100", 1), ("0200", "0277", 64)]
    assert [s["code"] for s in data["special"]] == ["7700"]
    hit = lookup(data, "0277")
    assert hit["imported"] and [p["unit"] for p in hit["pools"]] == ["EPWW"] and hit["special"] == []
    assert lookup(data, "7700")["special"][0]["label"] == "EMERGENCY" and lookup(data, "0300")["pools"] == []
    assert normalize(None) == {"status": None, "note": None, "meta": None, "pools": [], "special": []}


# --- plik data/seed/squawk.json i API

def test_seed_file():
    path = settings.seed_dir / "squawk.json"
    raw = json.loads(path.read_text("utf-8"))
    # format jak z importera (jedna pula na wiersz): ręczna poprawka musi zostawić ten sam układ
    assert path.read_text("utf-8") == squawk_cal.dumps(raw)
    special = {s["code"]: s for s in raw["special"]}
    assert set(special) == SPECIAL and all(s["meaning"] and s["source"] for s in special.values())
    assert special["7000"]["source"] == "SERA.13005" and "CCAMS" in special["1000"]["source"]
    assert special["1000"]["excluded"] == ["EPCE", "EPDA", "EPDE", "EPIR", "EPKS", "EPLK", "EPLY", "EPMB", "EPMI",
                                           "EPMM", "EPOK", "EPPR", "EPPW", "EPSN", "EPTM"]
    data = normalize(raw)
    assert len(data["pools"]) == len(raw["pools"])   # każda pula z poprawnymi kodami
    if raw["pools"]:   # po imporcie: skąd pule i bez notatki o oczekiwaniu
        assert raw["meta"]["source"] and "_status" not in raw
        assert all(p["count"] == pool_size(p["from"], p["to"]) for p in raw["pools"])
    else:              # przed importem: notatka z poleceniem importu, żadnych wymyślonych pul
        assert "python -m backend.app.importers.squawk_cal" in raw["_status"] and raw["meta"] is None


def test_api_squawk(client):
    data = client.get("/api/squawk").json()
    assert {s["code"] for s in data["special"]} == SPECIAL
    assert set(data) == {"status", "note", "meta", "pools", "special"}
    hit = client.get("/api/squawk/lookup", params={"code": "7700"}).json()
    assert hit["code"] == "7700" and hit["special"][0]["label"] == "EMERGENCY"
    assert client.get("/api/squawk/lookup", params={"code": " 1000 "}).json()["special"][0]["code"] == "1000"
    for bad, word in (("7800", "8 i 9"), ("77", "ósemkowe"), ("abcd", "ósemkowe"), ("77000", "ósemkowe")):
        r = client.get("/api/squawk/lookup", params={"code": bad})
        assert r.status_code == 422 and word in r.json()["detail"], bad
    assert "8 i 9" not in client.get("/api/squawk/lookup", params={"code": "77"}).json()["detail"]
    assert client.get("/api/squawk/lookup").status_code == 422


def test_api_reads_changed_seed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "seed_dir", tmp_path)
    assert client.get("/api/squawk").status_code == 404
    f = tmp_path / "squawk.json"
    f.write_text("{zepsuty", "utf-8")
    assert client.get("/api/squawk").status_code == 500
    f.write_text(json.dumps({"pools": [{"from": "4400", "to": "4477", "unit": "EPWW", "type": "TEST"}],
                             "special": [{"code": "7700"}]}), "utf-8")
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 5_000_000_000))
    data = client.get("/api/squawk").json()
    assert data["pools"][0]["count"] == 64 and data["status"] is None
    hit = client.get("/api/squawk/lookup", params={"code": "4477"}).json()
    assert hit["imported"] and hit["pools"][0]["type"] == "TEST"
    assert client.get("/api/squawk/lookup", params={"code": "4500"}).json()["pools"] == []


# --- importer CAL na SYNTETYCZNYCH arkuszach

def _xlsx(path):
    """SYNTETYCZNY arkusz .xlsx (nie dane CAL): tytuł z wydaniem, kody jako liczby, scalona komórka UNIT."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CAL"
    ws.append(["SYNTHETIC TEST DATA - not the EUROCONTROL CAL"])
    ws.append(["SSR CODE ALLOCATION LIST", None, None, "Edition 4.13"])
    ws.append([])
    ws.append(["SERIES", "CODE FROM", "CODE TO", "Unit", "TYPE", "REMARKS"])
    for row in (["01", 100, 177, "EPWW", "DOMESTIC", "test A"],
                ["02", 200, 237, None, "DOMESTIC", "test B"],      # UNIT ze scalonej komórki D5:D6
                ["02", "0240", "0277", "EDWW", "TRANSIT", ""],      # nie EP
                ["40", 4000, None, "EPKK", "SINGLE", ""],           # jeden kod
                ["50", 5000, 5077, "ORCAM", "TRANSIT", "EUR-E pool"],
                ["60", 6000, 6077, "EUR-EAST", "X", ""],            # EUR-E tylko jako całe słowo
                ["70", 7000, 6777, "EPWW", "BAD", "odwrócony"],     # do pominiętych
                ["03", 300, 307, "LKAA/EPWW", "SHARED", ""]):
        ws.append(row)
    ws.merge_cells("D5:D6")
    wb.save(path)
    return path


def _xls(path):
    """SYNTETYCZNY arkusz .xls (nie dane CAL): nagłówek dwupoziomowy (scalone CODES nad FROM/TO) i drugi arkusz
    z zakresami w jednej kolumnie."""
    xlwt = pytest.importorskip("xlwt")
    pytest.importorskip("xlrd")
    wb = xlwt.Workbook()
    ws = wb.add_sheet("PA")
    ws.write(0, 0, "SYNTHETIC TEST DATA")
    ws.write_merge(2, 2, 0, 1, "CODES")
    ws.write_merge(2, 3, 2, 2, "UNIT")
    ws.write(2, 3, "REMARKS")
    ws.write(3, 0, "FROM")
    ws.write(3, 1, "TO")
    ws.write(4, 0, "0100")
    ws.write(4, 1, "0137")
    ws.write(4, 2, "EPWW")
    ws.write(5, 0, 1000)
    ws.write(5, 1, 1077)
    ws.write(5, 2, "EP")
    ws.write(5, 3, "national")
    ws.write(6, 0, 2100)
    ws.write(6, 1, 2177)
    ws.write(6, 2, "LKAA")
    ws.write(6, 3, "eur-e")
    ws2 = wb.add_sheet("RANGES")
    for c, v in enumerate(["SSR CODES", "UNIT", "USE"]):
        ws2.write(0, c, v)
    ws2.write(1, 0, "4400-4477, 4500-4507")
    ws2.write_merge(1, 2, 1, 1, "EPGD")
    ws2.write(1, 2, "APP")
    ws2.write(2, 0, "45XX")
    ws2.write(2, 2, "TWR")
    ws2.write(3, 0, "TBD")
    ws2.write(3, 1, "EPKK")
    wb.save(str(path))
    return path


def test_import_xlsx(tmp_path):
    path = _xlsx(tmp_path / "synthetic.xlsx")
    log = []
    res = squawk_cal.extract(squawk_cal.read_book(path), path.name, report=log.append)
    assert [(p["from"], p["to"], p["count"], p["unit"]) for p in res["pools"]] == [
        ("0100", "0177", 64, "EPWW"), ("0200", "0237", 32, "EPWW"), ("0300", "0307", 8, "LKAA/EPWW"),
        ("4000", "4000", 1, "EPKK"), ("5000", "5077", 64, "ORCAM")]
    first, eur = res["pools"][0], res["pools"][-1]
    assert (first["type"], first["remarks"], first["match"], first["sheet"], first["row"]) == ("DOMESTIC", "test A", ["unit"], "CAL", 5)
    # surowe kolumny wiersza, kody jako napisy z zerami
    assert first["raw"] == {"SERIES": "01", "CODE FROM": "0100", "CODE TO": "0177", "Unit": "EPWW", "TYPE": "DOMESTIC",
                            "REMARKS": "test A"}
    assert eur["match"] == ["EUR-E"] and eur["type"] == "TRANSIT"
    assert [(s["row"], s["match"]) for s in res["skipped"]] == [(11, ["unit"])]
    meta = res["meta"]
    assert (meta["edition"], meta["edition_from"], meta["source"]) == ("4.13", "arkusz", "synthetic.xlsx")
    assert meta["filter"] == {"unit": ["EP"], "mention": ["EUR-E"]} and meta["sheets"]["CAL"]["header_row"] == 4
    assert meta["sheets"]["CAL"]["columns"]["from"] == "CODE FROM" and meta["sheets"]["CAL"]["columns"]["to"] == "CODE TO"
    # raport: wartości każdej kolumny z liczbą wystąpień (do ustalenia znaczenia EUR-E)
    text = "\n".join(log)
    assert "'EPWW': 3" in text and "'EUR-EAST': 1" in text and "role:" in text


def test_import_xls_two_level_header_and_ranges(tmp_path):
    path = _xls(tmp_path / "eurocontrol-icao-eur-cal-v4-13.xls")
    res = squawk_cal.extract(squawk_cal.read_book(path), path.name, report=lambda *_: None)
    got = [(p["from"], p["to"], p["unit"], p["sheet"], p["match"]) for p in res["pools"]]
    assert got == [("0100", "0137", "EPWW", "PA", ["unit"]), ("1000", "1077", "EP", "PA", ["unit"]),
                   ("2100", "2177", "LKAA", "PA", ["EUR-E"]), ("4400", "4477", "EPGD", "RANGES", ["unit"]),
                   ("4500", "4507", "EPGD", "RANGES", ["unit"]), ("4500", "4577", "EPGD", "RANGES", ["unit"])]
    assert res["pools"][1]["raw"]["CODES FROM"] == "1000" and res["pools"][1]["remarks"] == "national"
    assert res["pools"][-1]["type"] == "TWR"   # EPGD ze scalonej komórki
    assert res["meta"]["sheets"]["PA"]["columns"] == {"unit": "UNIT", "from": "CODES FROM", "to": "CODES TO",
                                                      "remarks": "REMARKS"}
    assert res["meta"]["sheets"]["RANGES"]["columns"]["code"] == "SSR CODES"
    assert [s["raw"]["SSR CODES"] for s in res["skipped"]] == ["TBD"]
    assert (res["meta"]["edition"], res["meta"]["edition_from"]) == ("4.13", "nazwa pliku")
    # inne filtry z wiersza poleceń
    only = squawk_cal.extract(squawk_cal.read_book(path), path.name, units=["EPGD"], mentions=[], only=["RANGES"],
                              report=lambda *_: None)
    assert {p["unit"] for p in only["pools"]} == {"EPGD"} and len(only["pools"]) == 3


def test_import_command_keeps_special_codes(tmp_path, capsys):
    path = _xlsx(tmp_path / "cal.xlsx")
    out = tmp_path / "squawk.json"
    out.write_text(json.dumps({"_uwaga": "opis", "_status": "czeka", "meta": None,
                               "special": [{"code": "7700", "label": "EMERGENCY"}], "pools": []}), "utf-8")
    assert squawk_cal.main([str(path), "--out", str(out), "--dry-run"]) == 0
    assert json.loads(out.read_text("utf-8"))["_status"] == "czeka"   # --dry-run nic nie zapisuje
    assert squawk_cal.main([str(path), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "0100–0177" in printed and "wydanie CAL: 4.13" in printed
    data = json.loads(out.read_text("utf-8"))
    assert list(data) == ["_uwaga", "meta", "special", "pools"]
    assert data["special"] == [{"code": "7700", "label": "EMERGENCY"}] and data["meta"]["source"] == "cal.xlsx"
    assert len(data["pools"]) == 5 and all(isinstance(p["from"], str) for p in data["pools"])
    assert out.read_text("utf-8") == squawk_cal.dumps(data)
    assert len(normalize(data)["pools"]) == 5
    # kolumna wskazana ręcznie, której nie ma
    assert squawk_cal.main([str(path), "--out", str(out), "--from-col", "NIE MA"]) == 2
    assert "nie ma takiej kolumny" in capsys.readouterr().err


def test_import_errors(tmp_path, monkeypatch, capsys):
    assert squawk_cal.main([str(tmp_path / "brak.xls")]) == 2
    assert "nie ma takiego pliku" in capsys.readouterr().err
    other = tmp_path / "cal.csv"
    other.write_text("UNIT\n", "utf-8")
    assert squawk_cal.main([str(other)]) == 2
    assert ".xls i .xlsx" in capsys.readouterr().err
    xlsx = tmp_path / "cal.xlsx"
    xlsx.write_bytes(b"PK")
    monkeypatch.setitem(sys.modules, "openpyxl", None)   # biblioteki nie ma: czytelny błąd, nie ślad stosu
    with pytest.raises(squawk_cal.CalError, match="openpyxl"):
        squawk_cal.read_book(xlsx)
    if "xlrd" in sys.modules or importlib.util.find_spec("xlrd"):   # uszkodzony plik: błąd zamiast śladu stosu
        (tmp_path / "zly.xls").write_bytes(b"to nie arkusz")
        assert squawk_cal.main([str(tmp_path / "zly.xls")]) == 2
        assert "nie da się odczytać arkusza .xls" in capsys.readouterr().err
    monkeypatch.setitem(sys.modules, "xlrd", None)
    assert squawk_cal.main([str(tmp_path / "cal.xls")]) == 2   # brak pliku sprawdzany przed biblioteką
    (tmp_path / "cal.xls").write_bytes(b"x")
    assert squawk_cal.main([str(tmp_path / "cal.xls")]) == 2
    assert "xlrd" in capsys.readouterr().err


def test_unit_and_mention_filters():
    assert squawk_cal.unit_match("EPWW", ["EP"]) and squawk_cal.unit_match("ep", ["EP"])
    assert squawk_cal.unit_match("LKAA / EPKK", ["EP"]) and not squawk_cal.unit_match("LEPA", ["EP"])
    assert squawk_cal.unit_match("EPWW", ["EPWW"]) and not squawk_cal.unit_match("EPWWX", ["EPWW"])
    pat = squawk_cal.mention_pattern(["EUR-E"])
    assert pat.search("pool EUR-E") and pat.search("(eur-e)") and not pat.search("EUR-EAST") and not pat.search("XEUR-E")
    assert squawk_cal.mention_pattern([]) is None


def test_detect_roles_without_name_hints():
    """Kolumny bez podpowiedzi w nazwach: numer wiersza i numer serii (1–2 cyfry) to nie kody, pierwsza kolumna
    pojedynczych kodów = od, następna = do."""
    names = ["NO", "SERIES", "A", "B", "UNIT", "USAGE", "NOTES"]
    rows = [["1", "01", "100", "177", "EPWW", "DOM", ""], ["2", "02", "0200", "0277", "EPKK", "TRA", "x"],
            ["3", "07", "7000", "7077", "LKAA", "DOM", ""]]
    assert squawk_cal.detect_roles(names, rows) == {"unit": 4, "from": 2, "to": 3, "code": None, "type": 5, "remarks": 6}
    forced = squawk_cal.detect_roles(names, rows, {"code": "series", "type": "NOTES"})
    assert (forced["code"], forced["from"], forced["type"], forced["remarks"]) == (1, None, 6, None)


# --- frontend: czyste funkcje tabs/squawk.js w Node (bez DOM)

NODE_SCRIPT = r"""
const sq = await import(process.argv[2]);
const pools = [
  { from: "0100", to: "0177", count: 64, unit: "EPWW", type: "DOMESTIC", remarks: "test", match: ["unit"], raw: { NOTE: "abc" } },
  { from: "4000", to: "4000", count: 1, unit: "EPKK", type: "", remarks: "", match: ["unit"] },
  { from: "5000", to: "5077", count: 64, unit: "ORCAM", type: "TRANSIT", remarks: "", match: ["EUR-E"] }];
const data = { pools, special: [{ code: "7700", label: "EMERGENCY" }, { code: "1000", label: "MODE S CONSPICUITY" }] };
const empty = { pools: [], special: data.special };
const short = (r) => [r.imported, r.special.map((s) => s.code), r.pools.map((p) => p.from)];
console.log(JSON.stringify({
  isCode: ["7700", "0000", "7777", "7800", "0900", "770", "77000", "", null, 7700].map(sq.isCode),
  size: [sq.rangeSize("0100", "0177"), sq.rangeSize("0000", "7777"), sq.rangeSize("7700", "7700"), sq.rangeSize("0170", "0207")],
  inRange: ["0077", "0100", "0177", "0200"].map((c) => sq.inRange(c, pools[0])).concat([sq.inRange("4000", { from: "4000" })]),
  check: ["", " 7700 ", "77", "7800", "9", "77a", "77000", "0000"].map(sq.checkCode),
  lookup: [sq.lookup(data, "7700"), sq.lookup(data, "0150"), sq.lookup(data, "5077"), sq.lookup(data, "1234"),
    sq.lookup(empty, "7700"), sq.lookup(empty, "1234"), sq.lookup(null, "7700")].map(short),
  miss: [sq.lookup(data, "0150"), sq.lookup(data, "7700"), sq.lookup(empty, "7700"), sq.lookup(data, "1234"), sq.lookup(empty, "1234")].map(sq.missText),
  filter: ["", "epww", "eur-e", "0150", "4000", "5070", "transit orcam", "abc", "7700"].map((q) => sq.filterPools(pools, q).map((p) => p.from)),
  plural: [0, 1, 2, 4, 5, 12, 14, 22, 25, 64, 112, 1024].map((n) => sq.plural(n, "kod", "kody", "kodów")),
  range: [sq.rangeText(pools[0]), sq.rangeText(pools[1]), sq.rangeText({ from: "1000" })],
  cmd: sq.IMPORT_CMD,
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    front = settings.frontend_dir / "js"
    d = tmp_path_factory.mktemp("sqjs")
    (d / "api.mjs").write_text((front / "api.js").read_text("utf-8"), "utf-8")
    (d / "squawk.mjs").write_text((front / "tabs" / "squawk.js").read_text("utf-8").replace('"../api.js"', '"./api.mjs"'), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "squawk.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_js_codes(js):
    assert js["isCode"] == [True, True, True, False, False, False, False, False, False, False]
    assert js["size"] == [64, 4096, 1, 16]   # 0170–0207 przez granicę serii: 0170..0177 i 0200..0207
    assert js["inRange"] == [False, True, True, False, True]


def test_js_check_code(js):
    res = [(c["code"], c["ok"], c["error"]) for c in js["check"]]
    assert res[0] == ("", False, None) and res[1] == ("7700", True, None) and res[2] == ("77", False, None)
    assert "8 i 9" in res[3][2] and "8 i 9" in res[4][2] and "0–7" in res[5][2] and "4 cyfry" in res[6][2]
    assert res[7] == ("0000", True, None)


def test_js_lookup_and_filter(js):
    assert js["lookup"] == [[True, ["7700"], []], [True, [], ["0100"]], [True, [], ["5000"]], [True, [], []],
                            [False, ["7700"], []], [False, [], []], [False, [], []]]
    miss = js["miss"]
    assert miss[0] == "" and miss[1] == "Nie leży w żadnej puli EPWW z CAL."
    assert "nie są jeszcze zaimportowane" in miss[2] and "nie jest kodem specjalnym" in miss[3]
    assert "nie jest kodem specjalnym" in miss[4] and "zaimportowane" in miss[4]
    assert js["filter"] == [["0100", "4000", "5000"], ["0100"], ["5000"], ["0100"], ["4000"], ["5000"], ["5000"], ["0100"], []]
    # 0, 1, 2, 4, 5, 12, 14, 22, 25, 64, 112, 1024
    assert js["plural"] == ["kodów", "kod", "kody", "kody", "kodów", "kodów", "kodów", "kody", "kodów", "kody", "kodów", "kody"]
    assert js["range"] == ["0100–0177", "4000", "1000"]
    assert js["cmd"].startswith("python -m backend.app.importers.squawk_cal ")


def test_squawk_tab_wiring():
    """Zakładka czyta /api/squawk, adres #squawk/<kod>, pusty stan z poleceniem importu; arkusz stylów podpięty."""
    src = (settings.frontend_dir / "js" / "tabs" / "squawk.js").read_text("utf-8")
    assert 'api("/api/squawk")' in src and 'remember("squawk", c.code)' in src and "activate: (arg)" in src
    assert "soon(" not in src and "emptyPools()" in src and "IMPORT_CMD" in src
    index = (settings.frontend_dir / "index.html").read_text("utf-8")
    assert 'href="/static/css/squawk.css"' in index
