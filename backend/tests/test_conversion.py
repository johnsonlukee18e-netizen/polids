"""0.12.3 (issue #13): CONVERSION, kalkulator jednostek dla kontrolera. Czyste funkcje z tabs/conversion.js w Node:
znane wartości, przeliczenia w obie strony, ISA (QNH a FL, Mach/TAS/CAS), czas w Polsce (CET/CEST wg zasad UE)."""
import json
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
CONV = (FRONTEND / "js" / "tabs" / "conversion.js").read_text("utf-8")

NODE_SCRIPT = r"""
const c = await import(process.argv[2]);
const G = c.GROUPS;
// pole wynikowe tak, jak pokazuje je karta (zaokrąglenie jednostki)
const show = (g, id, v) => Object.fromEntries(Object.entries(c.convert(G[g], id, v))
  .map(([k, x]) => [k, k === id ? String(v) : c.fmtNum(x, G[g].find((u) => u.id === k).dp)]));
// przeliczenie tam i z powrotem przez każdą jednostkę grupy: największy błąd względny
const roundtrip = (g, v) => Math.max(...G[g].flatMap((a) => G[g].map((b) => {
  const there = c.convert(G[g], a.id, v)[b.id];
  return Math.abs(c.convert(G[g], b.id, there)[a.id] - v) / Math.abs(v);
})));
const r = (x, d = 3) => Math.round(x * 10 ** d) / 10 ** d;
console.log(JSON.stringify({
  groups: Object.fromEntries(Object.entries(G).map(([k, us]) => [k, us.map((u) => [u.id, u.label, u.dp])])),
  pressure: [show("pressure", "inhg", 29.92), show("pressure", "hpa", 1013), show("pressure", "mmhg", 760)],
  height: [show("height", "fl", 100), show("height", "m", 1000), show("height", "ft", 3500)],
  distance: [show("distance", "nm", 1), show("distance", "km", 100), show("distance", "sm", 1)],
  speed: [show("speed", "kt", 100), show("speed", "ms", 10), show("speed", "kmh", 250)],
  vs: [show("vs", "fpm", 1000), show("vs", "ms", 5)],
  gradient: [show("gradient", "pct", 3.3), show("gradient", "deg", 3), show("gradient", "ftnm", 318)],
  temperature: [show("temperature", "c", 0), show("temperature", "c", -40), show("temperature", "f", 100),
    show("temperature", "k", 0)],
  mass: [show("mass", "kg", 1), show("mass", "lb", 1000), show("mass", "t", 79)],
  roundtrip: Object.keys(G).map((g) => [g, roundtrip(g, 12.3456)]),
  qnh: {
    level: [1013.25, 1013, 998, 1030, 950].map((q) => r(c.qnhLevelFt(q), 1)),
    fl100_std: c.paToAlt(10000, 1013.25), fl100_1013: r(c.paToAlt(10000, 1013), 1), fl70_998: r(c.paToAlt(7000, 998), 1),
    alt5000_998: r(c.altToPa(5000, 998), 1),
    back: r(c.altToPa(c.paToAlt(12345, 987.6), 987.6), 6),
  },
  isa: {
    temp: [0, 10000, 35000, 36089.24, 40000].map((ft) => r(c.isaTempK(ft) - 273.15, 2)),
    press: [0, 18000, 36089.24, 36089.2, 39000].map((ft) => r(c.isaPressure(ft), 2)),
    a: [0, 35000].map((ft) => r(c.soundKt(ft), 1)),
    tas: r(c.machToTas(0.78, 35000), 1), mach: r(c.tasToMach(450, 35000), 4),
    cas: [r(c.casToMach(280, 30000), 4), r(c.casToMach(250, 0), 4), r(c.machToCas(0.78, 35000), 1), r(c.machToCas(c.casToMach(300, 24000), 24000), 6)],
  },
  gradient_vs: [r(c.fpmOf(5.24, 140), 1), r(c.pctOf(c.fpmOf(3.3, 160), 160), 6)],
  parse: ["1013,25", " 29.92 ", "10 000", "FL100", "fl 35", "", "abc", "-5", "1,2,3", ".5", "+7", null].map((s) => {
    const v = c.parseNum(s);
    return Number.isNaN(v) ? "NaN" : v;
  }),
  fmt: [[29.9, 2], [760.04, 1], [-0.01, 1], [1234.5678, 0], [NaN, 1], [null, 1], [1e21 * 0 + 5, 3]].map(([v, d]) => c.fmtNum(v, d)),
  times: ["14:30", "1430", "14.30", "9:05", "1430Z", "0005 UTC", "24:00", "12:60", "x", ""].map(c.parseTime),
  days: ["2026-10-25", "25.10.2026", "2026-02-30", "2026-2-3", "29.02.2028", "x", ""].map((d) => {
    const ms = c.parseDay(d);
    return ms === null ? null : new Date(ms).toISOString().slice(0, 10);
  }),
  sundays: [[2026, 2], [2026, 9], [2027, 2], [2027, 9], [2025, 2], [2025, 9]].map(([y, m]) => new Date(c.lastSunday(y, m)).toISOString()),
  utc2pl: [["2026-07-01", "12:00"], ["2026-01-15", "23:30"], ["2026-03-29", "00:59"], ["2026-03-29", "01:00"],
    ["2026-10-25", "00:59"], ["2026-10-25", "01:00"], ["2026-12-31", "23:30"], ["2026-13-01", "12:00"], ["2026-07-01", "25:00"]]
    .map(([d, t]) => c.utcToPl(d, t)),
  pl2utc: [["2026-07-01", "14:00"], ["2026-01-01", "00:30"], ["2026-03-29", "02:30"], ["2026-03-29", "03:00"],
    ["2026-10-25", "02:30"], ["2026-10-25", "03:30"]].map(([d, t]) => c.plToUtc(d, t)),
  now: c.nowUtc(new Date(Date.UTC(2026, 9, 15, 7, 5, 59))),
}));
"""


def run_node(tmp_path_factory, source):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("js")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "conversion.mjs").write_text(CONV.replace('"../api.js"', '"./api.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(source, "utf-8")
    r = subprocess.run([node, str(script), (d / "conversion.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    return run_node(tmp_path_factory, NODE_SCRIPT)


# Karty z prawdziwym kodem obsługi pól (linkQnh, linkMach, linkGradient, linkGroup) na małej atrapie DOM: pola
# input[data-u], .conv-out, zdarzenie "input" z e.target. Każdy krok: wpis w pole → stan wszystkich pól karty.
CARDS_SCRIPT = r"""
const c = await import(process.argv[2]);
function card(ids) {
  const inputs = {}, listeners = [];
  for (const id of ids) {
    const cls = new Set(["field"]);
    inputs[id] = { value: "", dataset: { u: id }, cls, classList: {
      toggle: (k, on) => (on ? cls.add(k) : cls.delete(k)), remove: (k) => cls.delete(k), contains: (k) => cls.has(k) } };
  }
  let html = "";
  const out = { set textContent(t) { html = String(t); }, set innerHTML(t) { html = String(t); } };
  const el = {
    querySelector(sel) {
      const m = sel.match(/^input\[data-u="([^"]+)"\]$/);
      if (m) return inputs[m[1]] ?? null;
      return sel === ".conv-out" ? out : sel === ".conv-now" ? { addEventListener() {} } : null;
    },
    addEventListener: (type, fn) => type === "input" && listeners.push(fn),
  };
  const state = () => ({
    v: Object.fromEntries(ids.map((id) => [id, inputs[id].value])),
    bad: ids.filter((id) => inputs[id].cls.has("bad")),
    out: html.replace(/<[^>]+>/g, ""),
  });
  const type = (id, value) => { inputs[id].value = value; listeners.forEach((fn) => fn({ target: inputs[id] })); return state(); };
  return { el, type, state };
}
const steps = (link, ids, seq) => { const k = card(ids); link(k.el); return seq.map(([id, v]) => k.type(id, v)); };
console.log(JSON.stringify({
  qnh: steps(c.linkQnh, ["qnh", "alt", "fl"],
    [["fl", "70"], ["qnh", "998"], ["qnh", "99B"], ["qnh", "1200"], ["qnh", ""], ["qnh", "1013,25"], ["fl", "x"]]),
  gradient: steps(c.linkGradient, ["pct", "ftnm", "deg", "gs", "fpm"],
    [["gs", "140"], ["fpm", "1000"], ["gs", ""], ["gs", "140"], ["fpm", ""], ["fpm", "1000"], ["gs", "0"], ["gs", "1x"],
     ["gs", "140"], ["pct", "5.24"], ["gs", ""], ["gs", "abc"], ["gs", "140"], ["pct", ""]]),
  mach: steps(c.linkMach, ["fl", "mach", "tas", "cas"],
    [["fl", "350"], ["mach", "0.78"], ["fl", ""], ["fl", "700"], ["fl", "350"], ["mach", "1.2"]]),
  rows: c.CARDS.map((h) => {
    const rows = h.split('<label class="conv-row">').slice(1);
    return [h.match(/data-k="([^"]+)"/)[1], rows.filter((r) => r.trimStart().startsWith('<span class="conv-name">')).length, rows.length];
  }),
}));
"""


@pytest.fixture(scope="module")
def cards(tmp_path_factory):
    return run_node(tmp_path_factory, CARDS_SCRIPT)


def test_qnh_card_marks_bad_qnh(cards):
    q = cards["qnh"]
    assert q[0]["out"] == "Wpisz QNH." and q[0]["v"]["alt"] == ""
    assert q[1]["v"]["alt"] == "6581" and q[1]["bad"] == []
    # tekst zamiast liczby: czerwona ramka, wynik znika, komunikat o złej wartości (nie o zakresie)
    assert q[2]["bad"] == ["qnh"] and q[2]["v"]["alt"] == "" and q[2]["out"] == "Zła wartość QNH."
    assert q[3]["bad"] == ["qnh"] and q[3]["v"]["alt"] == "" and q[3]["out"] == "QNH poza zakresem 850–1100 hPa."
    assert q[4]["bad"] == [] and q[4]["out"] == "Wpisz QNH."
    assert q[5]["bad"] == [] and q[5]["v"]["alt"] == "7000" and q[5]["out"].startswith("Poziom QNH: 0 ft")
    assert q[6]["bad"] == ["fl"]


def test_gradient_card_clears_stale_results(cards):
    g = cards["gradient"]
    assert g[1]["v"] == {"pct": "7.05", "ftnm": "428.6", "deg": "4.03", "gs": "140", "fpm": "1000"}
    # bez GS, bez VS, GS 0 albo zła GS: gradient znika zamiast zostać policzony z poprzedniej GS
    for i, gs in ((2, ""), (4, "140"), (6, "0"), (7, "1x")):
        assert {k: g[i]["v"][k] for k in ("pct", "ftnm", "deg", "gs")} == {"pct": "", "ftnm": "", "deg": "", "gs": gs}, i
    assert g[3]["v"]["pct"] == "7.05" and g[5]["v"]["deg"] == "4.03" and g[7]["bad"] == ["gs"]
    # wpisany gradient liczy VS; bez poprawnej GS VS znika
    assert g[9]["v"]["fpm"] == "743" and g[9]["v"]["ftnm"] == "318.4"
    assert g[10]["v"]["fpm"] == "" and g[11]["v"]["fpm"] == "" and g[11]["bad"] == ["gs"]
    assert g[12]["v"]["fpm"] == "743" and g[13]["v"] == {"pct": "", "ftnm": "", "deg": "", "gs": "140", "fpm": ""}


def test_mach_card_clears_without_fl(cards):
    m = cards["mach"]
    assert m[1]["v"]["tas"] == "450" and m[1]["v"]["cas"] == "264"
    assert m[2]["v"] == {"fl": "", "mach": "0.78", "tas": "", "cas": ""} and m[2]["out"] == "Wpisz FL."
    assert m[3]["v"]["tas"] == "" and m[3]["out"] == "Wzory ISA w kalkulatorze: FL000–FL650."
    assert m[4]["v"]["tas"] == "450"
    assert m[5]["v"]["cas"] == "" and m[5]["out"].endswith("M ≥ 1: CAS poza zakresem wzoru")


def test_inputs_share_one_column(cards):
    # w karcie, w której choć jeden wiersz ma etykietę (GS, VS, QNH, FL…), mają ją wszystkie, więc pola zaczynają się
    # w jednej linii; wiersz z null ma pustą kolumnę etykiet
    for key, named, total in cards["rows"]:
        assert named in (0, total), key
    assert dict((k, (n, t)) for k, n, t in cards["rows"])["gradient"] == (5, 5)


def test_units_per_card(js):
    g = js["groups"]
    assert [u[1] for u in g["pressure"]] == ["hPa", "inHg", "mmHg"]
    assert [u[1] for u in g["height"]] == ["ft", "m", "FL"]
    assert [u[1] for u in g["distance"]] == ["NM", "km", "SM"]
    assert [u[1] for u in g["speed"]] == ["kt", "km/h", "m/s", "mph"]
    assert [u[1] for u in g["vs"]] == ["ft/min", "m/s"]
    assert [u[1] for u in g["temperature"]] == ["°C", "°F", "K"]
    assert [u[1] for u in g["mass"]] == ["kg", "lb", "t"]


def test_pressure(js):
    # 29.92 inHg = 1013.2 hPa; QNH 1013 = 29.91 inHg; 760 mmHg = 1013.25 hPa (standard)
    assert js["pressure"][0] == {"inhg": "29.92", "hpa": "1013.2", "mmhg": "760"}
    assert js["pressure"][1] == {"hpa": "1013", "inhg": "29.91", "mmhg": "759.8"}
    assert js["pressure"][2]["hpa"] == "1013.3" and js["pressure"][2]["inhg"] == "29.92"


def test_height_distance_speed(js):
    assert js["height"][0] == {"fl": "100", "ft": "10000", "m": "3048"}
    assert js["height"][1] == {"m": "1000", "ft": "3281", "fl": "32.8"}
    assert js["height"][2]["fl"] == "35" and js["height"][2]["m"] == "1066.8"
    assert js["distance"][0] == {"nm": "1", "km": "1.852", "sm": "1.151"}
    assert js["distance"][1]["nm"] == "53.996" and js["distance"][2]["km"] == "1.609"
    assert js["speed"][0] == {"kt": "100", "kmh": "185.2", "ms": "51.4", "mph": "115.1"}
    assert js["speed"][1]["kmh"] == "36" and js["speed"][1]["kt"] == "19.4"
    assert js["speed"][2]["kt"] == "135" and js["speed"][2]["ms"] == "69.4"
    assert js["vs"] == [{"fpm": "1000", "ms": "5.08"}, {"ms": "5", "fpm": "984"}]


def test_gradient_temperature_mass(js):
    # PDG 3.3 % = 200.5 ft/NM; ścieżka 3° = 5.24 % = 318 ft/NM
    assert js["gradient"][0] == {"pct": "3.3", "ftnm": "200.5", "deg": "1.89"}
    assert js["gradient"][1] == {"deg": "3", "pct": "5.24", "ftnm": "318.4"}
    assert js["gradient"][2]["pct"] == "5.23"
    assert js["gradient_vs"][0] == 742.9 and js["gradient_vs"][1] == 3.3   # 3° przy GS 140 kt ≈ 743 ft/min
    assert js["temperature"][0] == {"c": "0", "f": "32", "k": "273.15"}
    assert js["temperature"][1] == {"c": "-40", "f": "-40", "k": "233.15"}
    assert js["temperature"][2] == {"f": "100", "c": "37.8", "k": "310.93"}
    assert js["temperature"][3] == {"k": "0", "c": "-273.1", "f": "-459.7"}
    assert js["mass"][0] == {"kg": "1", "lb": "2.2", "t": "0.001"}
    assert js["mass"][1] == {"lb": "1000", "kg": "453.6", "t": "0.454"}
    assert js["mass"][2]["kg"] == "79000" and js["mass"][2]["lb"] == "174165.2"


def test_roundtrips(js):
    assert all(err < 1e-12 for _, err in js["roundtrip"]), js["roundtrip"]


def test_altitude_and_flight_level_at_qnh(js):
    q = js["qnh"]
    # poziom QNH w wysokości ciśnieniowej: 0 przy 1013.25, ok. 27 ft/hPa przy ziemi
    assert q["level"] == [0, 6.8, 418.9, -454.2, 1772]
    # FL100 przy QNH 1013.25 = 10000 ft; przy QNH 1013 o 7 ft niżej (1013 to w praktyce standard)
    assert q["fl100_std"] == 10000 and q["fl100_1013"] == 9993.2
    assert q["fl70_998"] == 6581.1 and q["alt5000_998"] == 5418.9 and q["back"] == 12345


def test_isa_mach_tas_cas(js):
    i = js["isa"]
    assert i["temp"] == [15.0, -4.81, -54.34, -56.5, -56.5]
    assert i["press"][0] == 1013.25 and i["press"][1] == 506.0 and i["press"][2] == 226.32
    assert abs(i["press"][2] - i["press"][3]) < 0.01 and i["press"][4] == 196.77   # ciągłość na tropopauzie, FL390
    assert i["a"] == [661.5, 576.4]
    assert i["tas"] == 449.6 and i["mach"] == 0.7807
    # 280 kt CAS na FL300 ≈ M0.74; przy ziemi CAS = TAS; M0.78 na FL350 ≈ 264 kt CAS; tam i z powrotem
    assert i["cas"] == [0.7422, 0.3779, 264.4, 300]


def test_parsing_and_formatting(js):
    assert js["parse"] == [1013.25, 29.92, 10000, 100, 35, None, "NaN", -5, "NaN", 0.5, 7, None]
    assert js["fmt"] == ["29.9", "760", "0", "1235", "", "", "5"]
    assert js["times"] == [870, 870, 870, 545, 870, 5, None, None, None, None]
    assert js["days"] == ["2026-10-25", "2026-10-25", None, "2026-02-03", "2028-02-29", None, None]


def test_poland_time_eu_dst(js):
    # ostatnie niedziele marca i października (zmiana czasu o 01:00 UTC)
    assert [s[:10] for s in js["sundays"]] == ["2026-03-29", "2026-10-25", "2027-03-28", "2027-10-31", "2025-03-30", "2025-10-26"]
    u = js["utc2pl"]
    assert u[0] == {"date": "2026-07-01", "time": "14:00", "offset": 2, "zone": "CEST, UTC+2"}
    assert u[1] == {"date": "2026-01-16", "time": "00:30", "offset": 1, "zone": "CET, UTC+1"}
    assert [(x["time"], x["offset"]) for x in u[2:6]] == [("01:59", 1), ("03:00", 2), ("02:59", 2), ("02:00", 1)]
    assert u[6]["date"] == "2027-01-01" and u[6]["time"] == "00:30"
    assert u[7] is None and u[8] is None
    p = js["pl2utc"]
    assert (p[0]["time"], p[0]["note"]) == ("12:00", "") and (p[1]["date"], p[1]["time"]) == ("2025-12-31", "23:30")
    # 02:30 w dniu przejścia na czas letni nie istnieje; 03:00 to już CEST
    assert p[2]["note"] == "gap" and p[3] == {"date": "2026-03-29", "time": "01:00", "offset": 2, "zone": "CEST, UTC+2", "note": ""}
    # 02:30 w dniu powrotu do CET jest dwa razy: 00:30 UTC (CEST) i 01:30 UTC (CET)
    assert (p[4]["time"], p[4]["offset"], p[4]["note"], p[4]["alt"]["time"]) == ("00:30", 2, "twice", "01:30")
    assert (p[5]["time"], p[5]["offset"], p[5]["note"]) == ("02:30", 1, "")
    assert js["now"] == {"date": "2026-10-15", "time": "07:05"}


def test_view():
    """Karty w kolejności z issue (najpierw hPa/inHg/mmHg i ft/m, potem "i takie tam"), pod każdą stała albo wzór,
    bez przycisku "przelicz"."""
    titles = ["Ciśnienie", "Wysokość", "Wysokość a FL przy QNH", "Odległość", "Prędkość", "Mach, TAS i CAS na FL (ISA)",
              "Prędkość pionowa", "Gradient wznoszenia / zniżania", "Temperatura", "Masa", "Czas: UTC a czas w Polsce"]
    pos = [CONV.index(f'"{t}"') for t in titles]
    assert pos == sorted(pos)
    assert CONV.count('<p class="conv-note">') == 1 and CONV.count("card(\"") == len(titles)
    # jedyny przycisk to "Teraz" w karcie czasu; przeliczenie na każde wpisanie znaku (zdarzenie input)
    assert CONV.count("<button") == 1 and ">Teraz</button>" in CONV and 'addEventListener("input"' in CONV
    assert "soon(" not in CONV
    css = (FRONTEND / "css" / "conversion.css").read_text("utf-8")
    assert ".conv-grid" in css and "text-shadow" not in css and "glow" not in css
