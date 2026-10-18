"""SQUAWK (0.12.3, issue #13): kody SSR, pule z arkusza EUROCONTROL CAL (importer), /api/squawk, zakładka.

Prawdziwy arkusz: data/import/eurocontrol-icao-eur-cal-v4-13.xls (CAL v4.13, 4 marca 2026) – testy z nim pomijane,
gdy brak xlrd (requirements-dev.txt). Pozostałe arkusze w testach importera są SYNTETYCZNE (budowane w teście,
wymyślone kody): układ CAL (walidacja kodów, kategorie) i układ ogólny (zapasowe zgadywanie kolumn)."""
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections import Counter

os.environ.setdefault("POLIDS_DATABASE_URL",
                      "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import DATA_DIR, settings  # noqa: E402
from backend.app.importers import squawk_cal  # noqa: E402
from backend.app.services.squawk import CATEGORIES, lookup, normalize, parse_codes, pool_size, valid_code  # noqa: E402

SPECIAL = {"7500", "7600", "7700", "2000", "7000", "1000"}
REAL_CAL = DATA_DIR / "import" / "eurocontrol-icao-eur-cal-v4-13.xls"
POOL_KEYS = ["from", "to", "count", "category", "pa", "unit", "civ_mil", "app", "assigned_by", "ar", "destination", "via",
             "protection", "remarks", "ver", "sheet", "row"]
# pule, z których FIR EPWW sam przydziela kody (CAL v4.13, PA EUR-E, A, Unit EP): od, do, liczba, CIV/MIL, ochrona, wiersz
EPWW = [("0001", "0017", 15, "CIV", "", 8), ("3101", "3177", 63, "MIL", "EUR-B EUR-C", 437),
        ("4130", "4177", 40, "CIV", "", 598), ("6301", "6377", 63, "CIV", "", 955), ("7401", "7477", 63, "CIV", "ES", 1152)]
EUR_E = ["EP", "EY", "LB", "LH", "LK", "LR", "LU", "LZ", "UK", "UMKK", "UMMV"]


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)   # bez startu aplikacji (baza niepotrzebna)


def _seed() -> dict:
    return json.loads((settings.seed_dir / "squawk.json").read_text("utf-8"))


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
    data = normalize({"_uwaga": "opis", "meta": "x", "pools": [
        {"from": "0200", "to": "0277", "count": 1, "unit": "LK", "category": "eur-e"},
        {"from": "4400", "to": "4477", "unit": "EP", "category": "ccams"}, {"from": "0100", "unit": "EPKK"},
        {"from": "0177", "to": "0100"}, {"from": "0800", "to": "0877"}, {"from": 100, "to": 177}, "x",
        {"from": "0240", "to": "0247", "unit": "EP", "category": "epww"}],
        "special": [{"code": "7700", "label": "EMERGENCY"}, {"code": "77"}, None]})
    assert data["note"] == "opis" and data["meta"] is None and "status" not in data
    # po kategorii (epww, ccams, nato, eur-e) i kodzie, count przeliczony, bez kategorii = epww, bez "to" = jeden kod
    assert [(p["category"], p["from"], p["to"], p["count"]) for p in data["pools"]] == [
        ("epww", "0100", "0100", 1), ("epww", "0240", "0247", 8), ("ccams", "4400", "4477", 64), ("eur-e", "0200", "0277", 64)]
    assert [s["code"] for s in data["special"]] == ["7700"]
    hit = lookup(data, "0244")   # pule wszystkich kategorii
    assert [(p["category"], p["unit"]) for p in hit["pools"]] == [("epww", "EP"), ("eur-e", "LK")] and hit["special"] == []
    assert set(hit) == {"code", "special", "pools"}
    assert lookup(data, "7700")["special"][0]["label"] == "EMERGENCY" and lookup(data, "0300")["pools"] == []
    assert normalize(None) == {"note": None, "meta": None, "pools": [], "special": []}


# --- plik data/seed/squawk.json i API

def test_seed_file():
    path = settings.seed_dir / "squawk.json"
    raw = _seed()
    # format jak z importera (jedna pula na wiersz): ręczna poprawka musi zostawić ten sam układ
    assert path.read_text("utf-8") == squawk_cal.dumps(raw)
    assert list(raw) == ["_uwaga", "meta", "special", "pools"] and "_status" not in raw
    special = {s["code"]: s for s in raw["special"]}
    assert set(special) == SPECIAL and all(s["meaning"] and s["source"] for s in special.values())
    assert special["7000"]["source"] == "SERA.13005" and "CCAMS" in special["1000"]["source"]
    assert special["1000"]["excluded"] == ["EPCE", "EPDA", "EPDE", "EPIR", "EPKS", "EPLK", "EPLY", "EPMB", "EPMI",
                                           "EPMM", "EPOK", "EPPR", "EPPW", "EPSN", "EPTM"]
    meta = raw["meta"]
    assert (meta["source"], meta["layout"], meta["edition"], meta["skipped"]) == (REAL_CAL.name, "CAL", "4.13", 0)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["generated"]) and meta["participating_areas"]["EUR-E"] == EUR_E
    pools = raw["pools"]
    assert all(list(p) == POOL_KEYS for p in pools) and all(p["category"] in CATEGORIES for p in pools)
    assert all(p["count"] == pool_size(p["from"], p["to"]) and valid_code(p["from"]) and valid_code(p["to"]) for p in pools)
    assert meta["counts"] == dict(Counter(p["category"] for p in pools)) == {"epww": 5, "ccams": 37, "nato": 5, "eur-e": 160}
    assert [(p["from"], p["to"], p["count"], p["civ_mil"], p["protection"], p["row"])
            for p in pools if p["category"] == "epww"] == EPWW
    assert len(normalize(raw)["pools"]) == len(pools)   # każda pula z poprawnymi kodami


def test_api_squawk(client):
    data = client.get("/api/squawk").json()
    assert {s["code"] for s in data["special"]} == SPECIAL
    assert set(data) == {"note", "meta", "pools", "special"}
    assert data["meta"]["edition"] == "4.13" and len(data["pools"]) == 207
    hit = client.get("/api/squawk/lookup", params={"code": "7700"}).json()
    assert hit["code"] == "7700" and hit["special"][0]["label"] == "EMERGENCY" and hit["pools"] == []
    # 7450: pula EPWW 7401–7477 i przydział LR (EUR-E) w tym samym zakresie
    hit = client.get("/api/squawk/lookup", params={"code": "7450"}).json()
    assert [(p["category"], p["from"], p["to"], p["unit"]) for p in hit["pools"]] == [
        ("epww", "7401", "7477", "EP"), ("eur-e", "7401", "7477", "LR")] and hit["special"] == []
    # 0101: retencja w EUR-E kodów przydzielanych przez EB
    hit = client.get("/api/squawk/lookup", params={"code": "0101"}).json()
    assert [(p["category"], p["ar"], p["assigned_by"], p["from"], p["to"]) for p in hit["pools"]] == [
        ("eur-e", "R", "EB", "0101", "0117")]
    hit = client.get("/api/squawk/lookup", params={"code": "1500"}).json()
    assert [(p["category"], p["civ_mil"]) for p in hit["pools"]] == [("nato", "MIL")]
    assert client.get("/api/squawk/lookup", params={"code": " 1000 "}).json()["special"][0]["code"] == "1000"
    for bad, word in (("7800", "8 and 9"), ("77", "octal"), ("abcd", "octal"), ("77000", "octal")):
        r = client.get("/api/squawk/lookup", params={"code": bad})
        assert r.status_code == 422 and word in r.json()["detail"], bad
    assert "8 and 9" not in client.get("/api/squawk/lookup", params={"code": "77"}).json()["detail"]
    assert client.get("/api/squawk/lookup").status_code == 422


def test_api_reads_changed_seed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "seed_dir", tmp_path)
    assert client.get("/api/squawk").status_code == 404
    f = tmp_path / "squawk.json"
    f.write_text("{zepsuty", "utf-8")
    assert client.get("/api/squawk").status_code == 500
    f.write_text(json.dumps({"pools": [{"from": "4400", "to": "4477", "unit": "EP", "remarks": "TEST"}],
                             "special": [{"code": "7700"}]}), "utf-8")
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 5_000_000_000))
    data = client.get("/api/squawk").json()
    assert data["pools"][0]["count"] == 64 and data["pools"][0]["category"] == "epww" and data["meta"] is None
    hit = client.get("/api/squawk/lookup", params={"code": "4477"}).json()
    assert hit["pools"][0]["remarks"] == "TEST"
    assert client.get("/api/squawk/lookup", params={"code": "4500"}).json()["pools"] == []


# --- importer na PRAWDZIWYM arkuszu CAL v4.13 (data/import)

@pytest.fixture(scope="module")
def real_cal():
    pytest.importorskip("xlrd")
    assert REAL_CAL.is_file(), REAL_CAL
    log = []
    res = squawk_cal.extract(squawk_cal.read_book(REAL_CAL), REAL_CAL.name, report=log.append)
    return res, "\n".join(log)


def test_real_cal_layout_and_categories(real_cal):
    res, log = real_cal
    meta, pools = res["meta"], res["pools"]
    assert (meta["layout"], meta["edition"], meta["edition_from"], meta["latest_ver"]) == ("CAL", "4.13", "file name and Ver column", "4.13")
    assert (meta["rows"], meta["skipped"], res["skipped"]) == (1273, 0, [])
    assert meta["participating_areas"]["EUR-E"] == EUR_E and "EP" in meta["participating_areas"]["CCAMS"]
    assert list(meta["participating_areas"]) == ["EUR-A", "EUR-B", "EUR-C", "EUR-D", "EUR-E", "EUR-F", "CCAMS"]
    assert meta["counts"] == {"epww": 5, "ccams": 37, "nato": 5, "eur-e": 160}
    assert all(list(p) == POOL_KEYS and p["sheet"] == "CAL" for p in pools)
    by = {c: [p for p in pools if p["category"] == c] for c in CATEGORIES}
    # EPWW: dokładnie 5 pul, PA EUR-E, przydział (A) jednostki EP, trasowe, lądowanie w EP, CAL 4.5
    assert [(p["from"], p["to"], p["count"], p["civ_mil"], p["protection"], p["row"]) for p in by["epww"]] == EPWW
    assert {(p["pa"], p["unit"], p["ar"], p["app"], p["destination"], p["assigned_by"], p["ver"]) for p in by["epww"]} == {
        ("EUR-E", "EP", "A", "ENR", "EP", "", "4.5")}
    assert all(p["pa"] == "CCAMS" and p["ar"] == "A" and "EP" in p["unit"].split() for p in by["ccams"])
    assert [(p["from"], p["to"]) for p in by["nato"]] == [("1300", "1327"), ("1500", "1577"), ("1600", "1677"),
                                                          ("1700", "1727"), ("2400", "2477")]
    assert all(p["civ_mil"] == "MIL" and "EP" in p["unit"].split() for p in by["nato"])
    # EUR-E: przydziały pozostałych członków (A) i retencja (R) z jednostką, która kody nadała
    assert Counter(p["ar"] for p in by["eur-e"]) == {"A": 46, "R": 114}
    assert all(p["pa"] == "EUR-E" and p["unit"] != "EP" for p in by["eur-e"])
    assert all(p["assigned_by"] for p in by["eur-e"] if p["ar"] == "R")
    assert {p["unit"] for p in by["eur-e"] if p["ar"] == "A"} == set(EUR_E) - {"EP"}
    # kody zawsze jako 4 cyfry ósemkowe, From = 00 daje kod XX00
    assert all(valid_code(p["from"]) and valid_code(p["to"]) for p in pools) and by["nato"][0]["from"] == "1300"
    assert "układ EUROCONTROL CAL" in log and "EUR-E  EP EY LB LH LK LR LU LZ UK UMKK UMMV" in log
    assert "CAL:738 EUR-C A/R=''" in log   # jedyny wiersz bez A/R (EUR-C, nas nie dotyczy) jest w raporcie


def test_seed_matches_fresh_import(real_cal):
    res = real_cal[0]
    raw = _seed()
    assert raw["pools"] == res["pools"]
    assert {k: v for k, v in raw["meta"].items() if k != "generated"} == {k: v for k, v in res["meta"].items() if k != "generated"}


def test_real_cal_command(tmp_path, capsys):
    pytest.importorskip("xlrd")
    out = tmp_path / "squawk.json"
    seed = (settings.seed_dir / "squawk.json").read_text("utf-8")
    base = _seed()
    out.write_text(squawk_cal.dumps({**base, "_status": "stara notatka", "meta": None, "pools": []}), "utf-8")
    assert squawk_cal.main([str(REAL_CAL), "--out", str(out), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "# układ: CAL" in printed and "# wydanie CAL: 4.13 (file name and Ver column)" in printed
    assert "# pule: 207 (epww 5, ccams 37, nato 5, eur-e 160)" in printed and "7401–7477" in printed
    assert json.loads(out.read_text("utf-8"))["pools"] == []   # --dry-run nic nie zapisuje
    assert squawk_cal.main([str(REAL_CAL), "--out", str(out)]) == 0
    # ten sam plik co w repozytorium (poza datą importu): _uwaga i special zostają, _status znika
    gen = re.compile(r'"generated": "[^"]*"')
    assert gen.sub("", out.read_text("utf-8")) == gen.sub("", seed)


# --- importer: układ CAL na SYNTETYCZNYM arkuszu (walidacja kodów i kategorie)

CAL_HEAD = ["Series", "From", "To", "PA", "Unit", "CIV/MIL", "APP", "Unit which assigned", "A/R", "Destination", "Via",
            "Protection", "Remarks", "Ver"]


def _cal_xlsx(path):
    """SYNTETYCZNY arkusz w układzie CAL (nie dane CAL): Series/From/To jako liczby i jako tekst, złe kody,
    kategorie i arkusz PAs."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CAL"
    ws.append(CAL_HEAD)
    for row in ([74, 1, 77, "EUR-E", "EP", "CIV", "ENR", "", "A", "EP", "", "ES", "", "V4.5"],          # 2: epww
                [75, 0, 7, "EUR-E", "EP", "MIL", "APP", "", "A", "EP", "", "", "test", "4.13"],         # 3: epww 7500–7507
                ["01", "01", "17", "EUR-E", "EP EY LB", "CIV", "ENR", "ED", "R", "ALL", "", "", "", "V4.12"],  # 4: retencja
                [41, 30, 77, "EUR-E", "ep  lk", "CIV", "ENR", "", "A", "LK", "ED", "", "x\ny", "V4.5"],  # 5: eur-e (nie samo EP)
                [20, 1, 77, "CCAMS", "EE EP ES", "CIV", "ENR", "", "A", "All", "", "EUR-D", "CCAMS", "V4.12"],  # 6: ccams
                [21, 1, 77, "CCAMS", "EE ES", "CIV", "ENR", "", "A", "ALL", "", "", "", "V4.12"],      # 7: CCAMS bez EP
                [24, 0, 77, "NATO", "ED EP", "MIL", "ENR", "", "A", "ED EP", "", "", "", "V4.11"],     # 8: nato
                [30, 1, 77, "EUR-B", "EP", "CIV", "ENR", "", "A", "EP", "", "", "", "V4.5"],           # 9: inny obszar
                [18, 1, 77, "EUR-E", "LK", "CIV", "ENR", "", "A", "LK", "", "", "", "V4.5"],           # 10: cyfra 8
                [42, 70, 60, "EUR-E", "LK", "CIV", "ENR", "", "A", "LK", "", "", "", "V4.5"],          # 11: From > To
                [43, 1, 9, "EUR-E", "LK", "CIV", "ENR", "", "A", "LK", "", "", "", "V4.5"],            # 12: cyfra 9
                [None] * 14,                                                                            # 13: pusty
                [44, 1, 7, "EUR-C", "EE", "CIV", "ENR", "", "", "ALL", "", "", "", "V4.5"],           # 14: bez A/R
                [45, "1.5", 7, "EUR-E", "LK", "CIV", "ENR", "", "A", "LK", "", "", "", "V4.5"]):      # 15: zły From
        ws.append(row)
    pas = wb.create_sheet("PAs")
    for row in (["", "", ""], ["EUR-E", " ".join(EUR_E), "EUR-E"], ["CCAMS", "EE EP ES", "CCAMS"], ["uwaga", "", ""]):
        pas.append(row)
    wb.save(path)
    return path


def test_cal_layout_synthetic(tmp_path):
    path = _cal_xlsx(tmp_path / "synthetic-cal-v4-13.xlsx")
    log = []
    sheets = squawk_cal.read_book(path)
    assert squawk_cal.cal_layout(sheets["CAL"])[0] == 0 and squawk_cal.cal_layout(sheets["PAs"]) is None
    res = squawk_cal.extract(sheets, path.name, report=log.append)
    got = [(p["category"], p["from"], p["to"], p["count"], p["unit"], p["ar"], p["row"]) for p in res["pools"]]
    assert got == [("epww", "7401", "7477", 63, "EP", "A", 2), ("epww", "7500", "7507", 8, "EP", "A", 3),
                   ("ccams", "2001", "2077", 63, "EE EP ES", "A", 6), ("nato", "2400", "2477", 64, "ED EP", "A", 8),
                   ("eur-e", "0101", "0117", 15, "EP EY LB", "R", 4), ("eur-e", "4130", "4177", 40, "EP LK", "A", 5)]
    p3, p4, p5, p6 = (next(p for p in res["pools"] if p["row"] == r) for r in (3, 4, 5, 6))
    assert (p3["app"], p3["ver"], p3["remarks"], p3["civ_mil"]) == ("APP", "4.13", "test", "MIL")
    assert (p4["assigned_by"], p4["destination"], p4["ver"]) == ("ED", "ALL", "4.12")
    assert (p5["via"], p5["remarks"]) == ("ED", "x / y") and p6["destination"] == "ALL"
    assert [(s["row"], s["why"]) for s in res["skipped"]] == [
        (10, "Series/From/To: dwie cyfry ósemkowe 0–7"), (11, "From > To"), (12, "Series/From/To: dwie cyfry ósemkowe 0–7"),
        (15, "Series/From/To: dwie cyfry ósemkowe 0–7")]
    assert res["skipped"][0]["raw"]["Series"] == "18" and res["skipped"][0]["pa"] == "EUR-E"
    meta = res["meta"]
    assert (meta["edition"], meta["edition_from"], meta["rows"], meta["skipped"]) == ("4.13", "file name and Ver column", 13, 4)
    assert meta["participating_areas"] == {"EUR-E": EUR_E, "CCAMS": ["EE", "EP", "ES"]}
    assert meta["counts"] == {"epww": 2, "ccams": 1, "nato": 1, "eur-e": 2}
    assert "CAL:14 EUR-C A/R=''" in "\n".join(log)
    # wydanie bez numeru w nazwie pliku: najnowsza wersja z kolumny Ver
    other = squawk_cal.extract(sheets, "cal.xlsx", report=lambda *_: None)["meta"]
    assert (other["edition"], other["edition_from"]) == ("4.13", "Ver column")
    # opcje układu ogólnego nie zmieniają wyboru w układzie CAL (tylko uwaga w raporcie)
    log.clear()
    forced = squawk_cal.extract(sheets, path.name, units=["LK"], report=log.append)
    assert forced["pools"] == res["pools"] and "dotyczą tylko układu ogólnego" in log[0]
    # --generic: ten sam arkusz przez zgadywanie kolumn
    assert squawk_cal.extract(sheets, path.name, generic=True, report=lambda *_: None)["meta"]["layout"] == "generic"


def test_cal_helpers():
    assert [squawk_cal.octal2(v) for v in ("0", "1", "07", "77", "8", "18", "100", "", "1.5", "A")] == [
        "00", "01", "07", "77", None, None, None, None, None, None]
    assert squawk_cal.tokens(" ep  lA\tEY ") == ["EP", "LA", "EY"] and squawk_cal.tokens("") == []
    assert [squawk_cal.ver_text(v) for v in ("V4.5", "4.12", "v4.13", "x")] == ["4.5", "4.12", "4.13", "x"]
    cat = squawk_cal.category
    assert cat("EUR-E", "A", ["EP"]) == "epww" and cat("EUR-E", "A", ["EP", "LK"]) == "eur-e"
    assert cat("EUR-E", "R", ["EP"]) == "eur-e" and cat("EUR-E", "R", ["LK"]) == "eur-e"
    assert cat("CCAMS", "A", ["EE", "EP"]) == "ccams" and cat("CCAMS", "A", ["EE"]) is None
    assert cat("NATO", "A", ["EP"]) == "nato" and cat("NATO", "R", ["EP"]) is None and cat("EUR-B", "A", ["EP"]) is None
    # nagłówek CAL bez kolumny wymaganej (A/R) to nie układ CAL
    assert squawk_cal.cal_layout([[h for h in CAL_HEAD if h != "A/R"]]) is None
    assert squawk_cal.cal_layout([["tytuł"], [h.upper() for h in CAL_HEAD]])[0] == 1


# --- importer: układ ogólny (zapasowy) na SYNTETYCZNYCH arkuszach

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
    assert [p["category"] for p in res["pools"]] == ["epww", "epww", "epww", "epww", "eur-e"]   # bez UNIT EP: eur-e
    assert [(s["row"], s["match"]) for s in res["skipped"]] == [(11, ["unit"])]
    meta = res["meta"]
    assert (meta["edition"], meta["edition_from"], meta["source"]) == ("4.13", "sheet", "synthetic.xlsx")
    assert meta["filter"] == {"unit": ["EP"], "mention": ["EUR-E"]} and meta["sheets"]["CAL"]["header_row"] == 4
    assert meta["layout"] == "generic" and meta["counts"] == {"epww": 4, "ccams": 0, "nato": 0, "eur-e": 1}
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
    assert (res["meta"]["edition"], res["meta"]["edition_from"]) == ("4.13", "file name")
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
    assert "0100–0177" in printed and "wydanie CAL: 4.13" in printed and "układ: generic" in printed
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
  { from: "7401", to: "7477", count: 63, category: "epww", pa: "EUR-E", unit: "EP", civ_mil: "CIV", app: "ENR", ar: "A",
    destination: "EP", protection: "ES", remarks: "", ver: "4.5" },
  { from: "0001", to: "0017", count: 15, category: "epww", pa: "EUR-E", unit: "EP", civ_mil: "CIV", ar: "A", destination: "EP" },
  { from: "2001", to: "2077", count: 63, category: "ccams", pa: "CCAMS", unit: "EE EP ES", civ_mil: "CIV", ar: "A", destination: "ALL",
    protection: "EUR-D", remarks: "Protection ensured by CCAMS" },
  { from: "1500", to: "1577", count: 64, category: "nato", pa: "NATO", unit: "ED EP", civ_mil: "MIL", ar: "A" },
  { from: "0101", to: "0117", count: 15, category: "eur-e", pa: "EUR-E", unit: "EP EY LB", civ_mil: "CIV", ar: "R", assigned_by: "EB",
    destination: "ALL", ver: "4.12" },
  { from: "7401", to: "7477", count: 63, category: "eur-e", pa: "EUR-E", unit: "LR", civ_mil: "CIV_MIL", app: "APP", ar: "A", destination: "LR" },
  { from: "4000", to: "4000", count: 1, category: "epww", unit: "EPKK", type: "SINGLE", remarks: "", match: ["unit"], raw: { NOTE: "abc" } }];
const areas = { "EUR-E": ["EP", "EY", "LB"] };
const data = { pools, special: [{ code: "7700", label: "EMERGENCY" }, { code: "1000", label: "MODE S CONSPICUITY" }] };
const empty = { pools: [], special: data.special };
const short = (r) => [r.special.map((s) => s.code), r.pools.map((p) => `${p.category}:${p.from}`)];
console.log(JSON.stringify({
  isCode: ["7700", "0000", "7777", "7800", "0900", "770", "77000", "", null, 7700].map(sq.isCode),
  size: [sq.rangeSize("0100", "0177"), sq.rangeSize("0000", "7777"), sq.rangeSize("7700", "7700"), sq.rangeSize("0170", "0207")],
  inRange: ["7400", "7401", "7477", "7500"].map((c) => sq.inRange(c, pools[0])).concat([sq.inRange("4000", { from: "4000" })]),
  check: ["", " 7700 ", "77", "7800", "9", "77a", "77000", "0000"].map(sq.checkCode),
  categories: sq.CATEGORIES.map((c) => [c.id, c.label, c.tag]), lines: sq.CATEGORIES.map((c) => c.line), def: sq.DEFAULT_VIEW,
  views: sq.CATEGORIES.map((c) => sq.viewPools(pools, c.id).map((p) => `${p.category}:${p.from}`)),
  counts: sq.viewCounts(pools), countsEmpty: sq.viewCounts(undefined),
  ar: ["A", "R", "", "X"].map((a) => [sq.arInfo(a).text, sq.arInfo(a).tip.slice(0, 1)]),
  civMil: ["CIV", "MIL", "CIV_MIL", "", undefined].map(sq.civMil),
  whole: [sq.wholeArea("EP EY LB", "EUR-E", areas), sq.wholeArea("LB EP EY", "EUR-E", areas), sq.wholeArea("EP EY", "EUR-E", areas),
    sq.wholeArea("EP EY LB LK", "EUR-E", areas), sq.wholeArea("EP EY LB", "CCAMS", areas), sq.wholeArea("EP EY LB", "EUR-E", null)],
  lookup: [sq.lookup(data, "7450"), sq.lookup(data, "0101"), sq.lookup(data, "7700"), sq.lookup(data, "1234"),
    sq.lookup(empty, "7700"), sq.lookup(null, "7700")].map(short),
  miss: [sq.lookup(data, "7450"), sq.lookup(data, "7700"), sq.lookup(data, "1234"), sq.lookup(empty, "1234")].map(sq.missText),
  hits: [sq.hitText(pools[0], areas), sq.hitText(pools[4], areas), sq.hitText(pools[4], {}), sq.hitText(pools[5], areas), sq.hitText(pools[6], areas)],
  filter: ["", "ep", "ccams", "retention", "7450", "4000", "eb all", "abc", "7700", "v4.12", "civ/mil app"].map((q) => sq.filterPools(pools, q).map((p) => `${p.category}:${p.from}`)),
  plural: [0, 1, 2, 4, 5, 12, 14, 22, 25, 64, 112, 1024].map((n) => sq.plural(n, "code", "codes")),
  range: [sq.rangeText(pools[0]), sq.rangeText(pools[6]), sq.rangeText({ from: "1000" })],
  tag: ["epww", "eur-e", "inne", undefined].map(sq.catTag),
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
    assert "8 and 9" in res[3][2] and "8 and 9" in res[4][2] and "0–7" in res[5][2] and "4 digits" in res[6][2]
    assert res[7] == ("0000", True, None)


def test_js_categories_and_views(js):
    # te same kategorie co w importerze, domyślnie pule EPWW
    assert [c[0] for c in js["categories"]] == list(CATEGORIES) and js["def"] == "epww"
    assert [c[1] for c in js["categories"]] == ["EPWW", "CCAMS", "NATO", "EUR-E (all)"]
    assert js["lines"][0].startswith("EPWW – pools from which FIR EPWW assigns codes itself")
    assert "CCAMS" in js["lines"][1] and "VATSIM" in js["lines"][1] and "military" in js["lines"][2]
    assert all(c in js["lines"][3] for c in ("Poland", "Lithuania", "Kaliningrad", "Belarus", "retention"))
    # widoki po kodzie; EUR-E (wszystkie) = wiersze EUR-E sąsiadów i pule EPWW
    assert js["views"] == [["epww:0001", "epww:4000", "epww:7401"], ["ccams:2001"], ["nato:1500"],
                           ["epww:0001", "eur-e:0101", "epww:4000", "epww:7401", "eur-e:7401"]]
    assert js["counts"] == {"epww": 3, "ccams": 1, "nato": 1, "eur-e": 5}
    assert js["countsEmpty"] == {"epww": 0, "ccams": 0, "nato": 0, "eur-e": 0}
    assert js["ar"] == [["allocation", "A"], ["retention", "R"], ["–", ""], ["X", ""]]
    assert js["civMil"] == ["CIV", "MIL", "CIV/MIL", "", ""]
    assert js["whole"] == [True, True, False, False, False, False]
    assert js["tag"] == ["EPWW", "EUR-E", "INNE", "?"]


def test_js_lookup_and_filter(js):
    # kod w pulach wszystkich kategorii
    assert js["lookup"] == [[[], ["epww:7401", "eur-e:7401"]], [[], ["eur-e:0101"]], [["7700"], []], [[], []],
                            [["7700"], []], [[], []]]
    miss = js["miss"]
    assert miss[0] == "" and miss[1] == "Not in any CAL pool (EPWW, CCAMS, NATO, EUR-E)."
    assert miss[2] == miss[3] == "– not a special code and not in any CAL pool (EPWW, CCAMS, NATO, EUR-E)."
    assert js["hits"] == ["7401–7477 (63 codes) · CIV · allocation: EP · dest EP · protection ES",
                          "0101–0117 (15 codes) · CIV · retention (whole EUR-E), assigned by EB · dest ALL",
                          "0101–0117 (15 codes) · CIV · retention (EP EY LB), assigned by EB · dest ALL",
                          "7401–7477 (63 codes) · CIV/MIL APP · allocation: LR · dest LR",
                          "4000 (1 code) · EPKK · SINGLE"]
    assert js["filter"] == [
        ["epww:7401", "epww:0001", "ccams:2001", "nato:1500", "eur-e:0101", "eur-e:7401", "epww:4000"],
        ["epww:7401", "epww:0001", "ccams:2001", "nato:1500", "eur-e:0101", "epww:4000"],   # EP też w EPKK
        ["ccams:2001"], ["eur-e:0101"], ["epww:7401", "eur-e:7401"], ["epww:4000"], ["eur-e:0101"], ["epww:4000"], [],
        ["eur-e:0101"], ["eur-e:7401"]]
    # 0, 1, 2, 4, 5, 12, 14, 22, 25, 64, 112, 1024 (0.12.5: po angielsku – liczba pojedyncza tylko dla 1)
    assert js["plural"] == ["codes", "code"] + ["codes"] * 10
    assert js["range"] == ["7401–7477", "4000", "1000"]


def test_squawk_tab_wiring():
    """Zakładka czyta /api/squawk, adres #squawk/<kod>, przełącznik kategorii; bez starego pustego stanu
    "pule nie są zaimportowane"; arkusz stylów podpięty."""
    src = (settings.frontend_dir / "js" / "tabs" / "squawk.js").read_text("utf-8")
    assert 'api("/api/squawk")' in src and 'remember("squawk", c.code)' in src and "activate: (arg)" in src
    assert 'data-view="${c.id}"' in src and "setView(b.dataset.view)" in src
    assert "soon(" not in src and "IMPORT_CMD" not in src and "zaimportowan" not in src
    index = (settings.frontend_dir / "index.html").read_text("utf-8")
    assert 'href="/static/css/squawk.css"' in index
