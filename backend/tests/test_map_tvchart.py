"""0.14.0 (issue #28, MAP: "widać jedynie linię limitu górnego, ale nie widać aktualnej przepustowości").

Przyczyna: wykres TV na MAP rysował słupki z tv.hours i zajętość z tv.occupancy z /api/viff/sectors, a sectors()
brał do nich tylko koszyki vIFF, których pole "hour" było dosłownie napisem "HH" bieżącej i następnej godziny
(z osobnego zapytania "fromNow"). Koszyk z godziną liczbą (13), bez zera ("7") albo jako "1300" nie pasował: puste
godziny, brak lotów, zajętość same zera (płaska linia na osi), a linia przepustowości z definicji TV zostawała.
Wykresy OTHER › FMP liczą wejścia i zajętość wprost z krotek lotów całodobowych danych (tv_flights), więc działały.
Teraz: godzina koszyka przez _hour, sectors() z tych samych całodobowych danych co wykres FMP, a wykres MAP z GET
/api/viff/sectors/<TV> i rysunków entrySvg / occSvg z fmp.js (viffchart.js chartHtml)."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402

from backend.app.config import ROOT_DIR  # noqa: E402
from backend.app.services import viff  # noqa: E402

JS = ROOT_DIR / "frontend" / "js"
NOW = datetime(2026, 10, 5, 13, 10, tzinfo=timezone.utc)
TVS = [{"id": "EP-BH", "volumes": "EPWW-BH", "status": 1, "entries": 45, "occupancy": 14, "restrictions": []}]


def _day(hour):
    """Całodobowe /etfms/airspaces z godziną koszyka zapisaną funkcją hour(h): LOT1 i LOT2 są w sektorze o 13:10."""
    return {"EP-BH": [
        {"hour": hour(13), "entriesCapacity": 30, "peakCapacity": 14, "entriesCount": 5, "peakCount": 2,
         "flights": [["LOT1", "1300", "1330", "1302", "1335", True], ["LOT2", "1305", "1320", "", "", True]]},
        {"hour": hour(14), "entriesCapacity": 30, "entriesCount": 2,
         "flights": [["LOT3", "1400", "1410", "1401", "1411", False]]},
        {"hour": hour(15), "entriesCount": 1, "flights": [["LOT4", "1500", "1510", "", "", False]]},
    ]}


def _fake(day, calls=None):
    async def get(path, params=None, ttl=None):
        if path == "/etfms/trafficVolumes":
            return TVS
        if path == "/etfms/scenarios":
            return []
        if path == "/etfms/airspaces":
            if calls is not None:
                calls.append(dict(params))
            return day if params["date"] == "2026-10-05" else {}
        raise ValueError(path)
    return get


@pytest.mark.parametrize("value,want", [
    ("13", 13), ("07", 7), ("7", 7), (7, 7), (7.0, 7), (0, 0), ("00", 0), ("1300", 13), ("13:00", 13), ("130000", 13),
    ("2026-10-05T13:00:00Z", 13), ("2026-10-05 13:00", None), (24, None), ("24", None), ("2400", None), (-1, None),
    ("", None), (None, None), (True, None), ("x", None), ("123", None), (7.5, None), ([13], None)])
def test_bucket_hour(value, want):
    assert viff._hour(value) == want


@pytest.mark.parametrize("hour", [lambda h: f"{h:02d}", lambda h: h, lambda h: str(h), lambda h: f"{h:02d}00"],
                         ids=["HH", "int", "no-zero", "HHMM"])
def test_sectors_any_hour_format(hour):
    """Wiersz TV ma godziny, loty i zajętość także przy godzinie koszyka liczbą albo "1300" (do 0.13.6 tylko "13":
    puste hours i flights, zajętość same zera); godzina w odpowiedzi zawsze "HH" (FMP: tvNow)."""
    get = viff._get
    try:
        calls = []
        viff._get = _fake(_day(hour), calls)
        d = asyncio.run(viff.sectors("EP", NOW))
        row = d["sectors"][0]
        assert [(h["hour"], h["entries"], h["entries_cap"]) for h in row["hours"]] == [("13", 5, 30), ("14", 2, 30)]
        assert [f["callsign"] for f in row["flights"]] == ["LOT1", "LOT2", "LOT3"]
        assert row["occupancy"][0] == 2 and row["peak_60"] == 2 and [w["entries"] for w in row["windows"]] == [0, 0, 1]
        # te same całodobowe dane co wykres OTHER › FMP i szczegóły lotu (bez "fromNow", ten sam klucz cache)
        assert calls == [{"filter": "EP", "date": "2026-10-05"}]
    finally:
        viff._get = get


def test_sectors_odd_payloads():
    """Koszyki nie-słowniki, lista zamiast słownika i TV bez listy nie psują tabeli."""
    get = viff._get
    try:
        for day in ({"EP-BH": ["x", None, {"hour": 13, "flights": "x"}]}, [], {"EP-BH": "x"}, None):
            viff._get = _fake(day)
            row = asyncio.run(viff.sectors("EP", NOW))["sectors"][0]
            assert row["id"] == "EP-BH" and row["flights"] == [], day
    finally:
        viff._get = get


# --- frontend w Node: wykres TV na MAP z danych i rysunków OTHER › FMP

NODE_SCRIPT = r"""
const vc = await import(process.argv[2]);
const fmp = await import(process.argv[3]);
const { tv, c } = JSON.parse((await import("node:fs")).readFileSync(process.argv[4], "utf-8"));
const svg = { entry: fmp.entrySvg, occ: fmp.occSvg };
const pilot = (cs) => (cs === "LOT1" ? { departure: "EPWA", arrival: "EPGD", aircraft: "B738" } : null);
console.log(JSON.stringify({
  html: vc.chartHtml(tv, c, { pilot, sel: "LOT2", svg }),
  now: vc.chartNow(c),
  wait: vc.chartHtml(tv, null, { svg }),
  err: vc.chartHtml(tv, null, { svg, err: "Flow <data> unavailable" }),
  note: vc.chartHtml(tv, c, { svg, note: "Not refreshed: x" }),
  noList: vc.chartHtml(null, { ...c, active: false }, { svg }),
  nullNow: [vc.chartNow(null), vc.chartNow({ ...c, now_at: null })],
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    get = viff._get
    try:
        viff._get = _fake(_day(lambda h: h))
        tv = asyncio.run(viff.sectors("EP", NOW))["sectors"][0]
        c = asyncio.run(viff.sector_chart("EP-BH", NOW))
    finally:
        viff._get = get
    d = tmp_path_factory.mktemp("tvchart")
    (d / "api.mjs").write_text((JS / "api.js").read_text("utf-8"), "utf-8")
    for name in ("viffchart", "fmp"):
        src = (JS / f"{name}.js").read_text("utf-8")
        (d / f"{name}.mjs").write_text(src.replace('"./api.js"', '"./api.mjs"').replace('"./viffchart.js"', '"./viffchart.mjs"'), "utf-8")
    (d / "data.json").write_text(json.dumps({"tv": tv, "c": c}), "utf-8")
    (d / "run.mjs").write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(d / "run.mjs"), (d / "viffchart.mjs").as_uri(), (d / "fmp.mjs").as_uri(), str(d / "data.json")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return {**json.loads(r.stdout), "c": c}


def test_map_chart_shows_current_load(js):
    """Wykres MAP: słupki ENTRY (wejścia w 60 min co 20 min) i kolumny OCC (samoloty w sektorze) obok linii
    przepustowości, jak w OTHER › FMP; pod nimi stan teraz wobec przepustowości."""
    h, c = js["html"], js["c"]
    entry, occ = h.split("OCC <span>")
    bars = re.findall(r'<rect [^>]*class="(fmc-[a-z]+)[^"]*"><title>', entry)
    assert len(bars) == 15 and any(b != "fmc-nolim" for b in bars)
    counts = [int(v) for v in re.findall(r'class="fmc-val">(\d+)<', entry)]
    assert counts and counts == [e["count"] for e in c["entries"] if e["count"]]
    cols = re.findall(r'<rect [^>]*class="(fmc-[a-z]+)[^"]*"><title>([^<]*)</title>', occ)
    assert cols and all(cls != "fmc-nolim" for cls, _ in cols) and any(t.endswith(": 2 aircraft, capacity 14") for _, t in cols)
    assert entry.count('class="fmc-cap"') >= 1 and occ.count('class="fmc-cap"') == 1
    assert entry.count('class="fmc-now"') == 1 and occ.count('class="fmc-now"') == 1
    # stan teraz: słupek od 13:00 (wejścia LOT1 1302, LOT2 1305, LOT3 1401 w 60 min) wobec 30, w sektorze 2 z 14
    assert js["now"] == {"entries": 2, "entriesCap": 30, "entriesFrom": "1300", "occupancy": 2, "occupancyCap": 14}
    assert '<div class="vf-stat">1310Z · entries 2/30 from 1300Z · in sector 2/14 · peak 2 at 1310Z</div>' in h
    # nagłówek, obszar, przepustowość, legenda jak w FMP
    assert ('<span class="vf-id">EP-BH</span><span class="vf-desc">sector B upper</span><span class="vs-chip on">ACTIVE</span>'
            in h)
    assert '<button class="vf-close" title="Close chart">✕</button>' in h
    assert '<span title="airspace volumes">EPWW-BH</span>' in h and "capacity: 45 entries/h · 14 at once" in h
    for label in ("below 90 %", "90–100 %", "over capacity", "no limit", "capacity", "regulated"):
        assert f"</i>{label}</span>" in h, label
    # lista lotów w sektorze w ciągu godziny: dane pilota, wybrany lot podświetlony, kolejność wejścia
    assert re.findall(r'<tr data-cs="([^"]+)"', h) == ["LOT1", "LOT2", "LOT3"]
    assert "<td>EPWA</td><td>EPGD</td><td>B738</td>" in h and '<tr data-cs="LOT2" class=" on"' in h
    assert "Flights in sector within the hour <span>(3)</span>" in h
    # stary wykres (słupki z tv.hours, ścieżka zajętości) zniknął
    assert "vf-svg" not in h and "vf-occ" not in h and "Entries / h" not in h


def test_map_chart_states(js):
    assert "Loading…" in js["wait"] and 'class="vf-id">EP-BH<' in js["wait"] and "fmc-svg" not in js["wait"]
    assert '<p class="error vf-err">Flow &lt;data&gt; unavailable</p>' in js["err"] and "Loading" not in js["err"]
    # błąd odświeżenia: ostatni wykres zostaje, komunikat w nagłówku
    assert '<span class="vf-note error">Not refreshed: x</span>' in js["note"] and js["note"].count("fmc-svg") == 2
    # wykres bez wiersza listy (lista sektorów niedostępna): nagłówek z wykresu, bez listy lotów
    assert '<span class="vs-chip">inactive</span>' in js["noList"] and "no flight list" in js["noList"]
    assert js["nullNow"] == [None, None]
    for k in ("html", "wait", "err", "note", "noList"):
        assert "<b>" not in js[k] and "<b " not in js[k] and "<strong" not in js[k], k


def test_map_chart_wiring():
    """map.js: wykres z /api/viff/sectors/<TV> (spóźniona odpowiedź nic nie rysuje), rysunki z fmp.js, odświeżanie
    razem z listą, panel nie wyższy niż mapa; viffchart.js bez importu fmp.js (fmp.js importuje viffchart.js)."""
    src = (JS / "tabs" / "map.js").read_text("utf-8")
    assert 'import { entrySvg, occSvg } from "../fmp.js";' in src
    load = src.split("const loadChart = async () => {")[1].split("\n  };")[0]
    assert "api(`/api/viff/sectors/${encodeURIComponent(id)}`)" in load and "if (my !== chartSeq) return;" in load
    assert "svg: { entry: entrySvg, occ: occSvg }" in src
    assert src.split("const loadViff = async () => {")[1].split("\n  };")[0].rstrip().endswith("loadChart();")
    assert 'chartEl.style.maxHeight = Math.max(180, hgt - 110) + "px";' in src
    vc = (JS / "viffchart.js").read_text("utf-8")
    assert "fmp.js\"" not in vc and "from \"./fmp" not in vc
    # cały viffchart.js w ASCII poza komentarzami w osobnych linijkach
    bad = [line.strip() for line in vc.splitlines() if re.search(r"[^\x00-\x7F]", line) and not line.strip().startswith("//")]
    assert not bad, bad
    css = (JS.parent / "css" / "viff.css").read_text("utf-8")
    assert ".leaflet-control.viff-chart { width: 560px; margin-bottom: 24px; padding: 0; overflow: auto;" in css
    assert ".vf-svg" not in css and ".vf-legend" not in css
