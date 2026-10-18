"""METEO (runda 10): SAT PL i SAT EUR (Windy z własnym środkiem i zoomem), TURB (8 klatek IMGW co 3 h, odtwarzacz)
i SIGWX (mapa IMGW odświeżana co 15 min). Obrazy IMGW wczytuje przeglądarka użytkownika, nie serwer PolIDS.
0.12.3 (issue #13): kolejność podzakładek, GAMET (rejony A1–A5 i ALL), ICING (Windy z poziomem), SUN.
0.12.5 (issue #18): WIND i RADAR jako środkowa grupa podzakładek, WIND zawsze od 0 ft, napisy po angielsku."""
import json
import re
import shutil
import subprocess

import pytest

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"
METEO = (FRONTEND / "js" / "tabs" / "meteo.js").read_text("utf-8")
CSS = (FRONTEND / "css" / "meteoimg.css").read_text("utf-8")
TURB_BASE = "https://aviation-api.imgw.pl/image/TURBULENCJE/gify_LOTN07_TURB_DWD_statkirejsowe/Turb11000."
# adres RADAR sprzed rundy 10 (bez zmian)
RADAR_URL = ("https://embed.windy.com/embed2.html?lat=52.0&lon=19.3&detailLat=52.17&detailLon=20.97&zoom=6&level=surface"
             "&overlay=radar&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=true&type=map&location=coordinates"
             "&detail=&metricWind=kt&metricTemp=%C2%B0C&radarRange=-1")

NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const T = Date.UTC(2026, 9, 12, 12, 22, 5);
const P = m.IMG_REFRESH;
const S = (s) => s.split("");   // "olle" -> ["o","l","l","e"]; o = ok, l = wczytywanie, e = błąd
const st = (s) => S(s).map((c) => ({ o: "ok", l: "load", e: "err" }[c]));
console.log(JSON.stringify({
  frames: m.turbFrames(),
  steps: m.TURB_STEPS, ms: m.TURB_MS, refresh: P, sigwx: m.SIGWX_URL,
  windy: Object.fromEntries(Object.entries(m.WINDY_VIEWS).map(([k, v]) => [k, m.windyEmbedUrl(v)])),
  icing: m.ICING_LEVELS.map(([l, fl]) => [fl, m.windyEmbedUrl({ ...m.WINDY_VIEWS.icing, level: l })]),
  icingLevel: [m.icingLevel("300h"), m.icingLevel("surface"), m.icingLevel(null)],
  gamet: {
    area: [m.gametArea("A3"), m.gametArea("ALL"), m.gametArea("A9"), m.gametArea(null)],
    shown: [m.gametShown({ A2: {}, A1: {}, A5: {} }, "ALL"), m.gametShown({ A1: {} }, "A4"), m.gametShown(null, "ALL")],
    valid: [m.gametValidTxt({ valid: "150400/151000", valid_from: "2026-10-15T04:00Z", valid_to: "2026-10-15T10:00Z" }),
            m.gametValidTxt({ valid: "152200/160400", valid_from: "2026-10-15T22:00Z", valid_to: "2026-10-16T04:00Z" }),
            m.gametValidTxt({ valid: "150400/151000" }), m.gametValidTxt(null)],
    expired: [m.gametExpired({ valid_to: "2026-10-12T12:00Z" }, T), m.gametExpired({ valid_to: "2026-10-12T16:00Z" }, T),
              m.gametExpired({}, T)],
    urls: [m.GAMET_MAP_URL, m.GAMET_PAGE, m.GAMET_REFRESH],
  },
  sun: {
    icao: [m.sunIcao(" epwa "), m.sunIcao("EP/A"), m.sunIcao("LONGER"), m.sunIcao(null)],
    cell: [m.sunCell("2026-10-15T05:00:52Z", "2026-10-15"), m.sunCell("2026-10-14T20:46:51Z", "2026-10-15"),
           m.sunCell("2026-10-15T05:00:52Z", "2026-10-15", { hm: "07:01", tz: "CEST" }), m.sunCell(null, "2026-10-15"),
           m.sunCell("2026-10-15T23:59:40Z", "2026-10-15")],
    dur: [m.durTxt(641), m.durTxt(1440), m.durTxt(0), m.durTxt(45), m.durTxt(null)],
    until: [m.untilTxt(30000), m.untilTxt(12 * 60000 + 59000), m.untilTxt(3 * 3600000 + 12 * 60000)],
    polar: [m.polarTxt({ polar: "day" }), m.polarTxt({ polar: "night", civil_polar: "night" }),
            m.polarTxt({ polar: "night" }), m.polarTxt({ civil_polar: "day" }), m.polarTxt({})],
    // dni przejścia: tylko wschód / tylko zachód / tylko BMCT / tylko EECT; zwykły dzień bez uwagi
    edge: [m.polarTxt({ sunrise: "a", sunset: null, civil_polar: "day" }), m.polarTxt({ sunrise: null, sunset: "b" }),
           m.polarTxt({ sunrise: "a", sunset: "b", civil_dawn: "c", civil_dusk: null }),
           m.polarTxt({ sunrise: "a", sunset: "b", civil_dawn: null, civil_dusk: "d" }),
           m.polarTxt({ sunrise: "a", sunset: "b", civil_dawn: "c", civil_dusk: "d" })],
    next: (() => {
      const up = [{ event: "sunset", at: "2026-10-15T15:42:04Z" }, { event: "civil_dusk", at: "2026-10-15T16:16:14Z" },
                  { event: "civil_dawn", at: "2026-10-16T04:28:17Z" }];
      const at = (hm) => Date.parse(`2026-10-15T${hm}:00Z`);
      const ev = (n) => n?.event ?? null;
      return [ev(m.sunNext({ upcoming: up, next: up[0] }, at("15:41"))), ev(m.sunNext({ upcoming: up, next: up[0] }, at("15:44"))),
              ev(m.sunNext({ upcoming: up, next: up[0] }, at("16:17"))), ev(m.sunNext({ upcoming: up }, Date.parse("2026-10-16T05:00:00Z"))),
              ev(m.sunNext({ next: up[0] }, at("15:41"))), ev(m.sunNext({ next: up[0] }, at("15:44"))), ev(m.sunNext(null, 0))];
    })(),
    zoom: [932, 698, 1600, 1024, 1366, 300, 0].map((w) => [w, m.sunZoom(w)]),
    near: [m.nearLon(-47, 313), m.nearLon(-47, 0), m.nearLon(170, -175), m.nearLon(20.97, 380), m.nearLon(-170, 200)],
    query: [m.sunQuery(" epwa "), m.sunQuery("ep-a"), m.sunQuery(null)],
    ms: [m.SUN_TICK, m.SUN_REFRESH],
  },
  stamp: [m.stamp(T, P), m.stamp(T + 7 * 60000, P), m.stamp(T + 8 * 60000, P), m.stamp(T, 1000)],
  bust: [m.bust(m.SIGWX_URL, "20261012121500"), m.bust("https://x/y?a=1", "1")],
  next: [m.nextFrame(st("oooooooo"), 7), m.nextFrame(st("oeeooooo"), 0), m.nextFrame(st("oooooooe"), 6),
         m.nextFrame(st("eeeeeeee"), 3), m.nextFrame(st("oooooooo"), 0, -1), m.nextFrame(st("eooooooe"), 1, -1)],
  play: [m.playStep(st("oooooooo"), 0), m.playStep(st("oooooooo"), 7), m.playStep(st("olllllll"), 0),
         m.playStep(st("oeolllll"), 0), m.playStep(st("eeeeeeee"), 0), m.playStep(st("eeeeoeee"), 4),
         m.playStep(st("leeeeeee"), 0), m.playStep(st("oeeeeeee"), 0), m.playStep(st("eeoeeeeo"), 7),
         m.playStep(st("looooooo"), 0), m.playStep(st("oolooooo"), 2), m.playStep(st("ooleoooo"), 3)],
  fetched: (() => {
    const u = "https://x/a.gif?t=1", a = new Date(T), b = new Date(T + 9 * 60000);
    return [m.fetchedAt(u, a).toISOString(), m.fetchedAt(u, b).toISOString(), m.fetchedAt(u + "0", b).toISOString()];
  })(),
}));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("brak Node.js")
    d = tmp_path_factory.mktemp("meteo")
    (d / "api.mjs").write_text((FRONTEND / "js" / "api.js").read_text("utf-8"), "utf-8")
    (d / "solar.mjs").write_text((FRONTEND / "js" / "solar.js").read_text("utf-8"), "utf-8")
    (d / "meteo.mjs").write_text(METEO.replace('"../api.js"', '"./api.mjs"').replace('"../solar.js"', '"./solar.mjs"'), "utf-8")
    script = d / "run.mjs"
    script.write_text(NODE_SCRIPT, "utf-8")
    r = subprocess.run([node, str(script), (d / "meteo.mjs").as_uri()], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_submenu_order():
    """Kolejność z issue #13 i #18: METAR i TAF jak dotąd (PL, MIL, INTL), po odstępie WIND i RADAR (środkowa grupa,
    issue #18), po drugim odstępie GAMET, SIGWX, ICING, QNH, SAT EUR, SAT PL, TURB, SUN."""
    mount = METEO[METEO.index("export default {"):]
    items = re.findall(r'\{ id: "([^"]+)", label: "([^"]+)"', mount)
    assert items == [("metar-pl", "METAR PL"), ("metar-mil", "METAR MIL"), ("metar-intl", "METAR INTL"), ("taf-pl", "TAF PL"),
                     ("taf-intl", "TAF INTL"), ("wind", "WIND"), ("radar", "RADAR"), ("gamet", "GAMET"), ("sigwx", "SIGWX"),
                     ("icing", "ICING"), ("qnh", "QNH"), ("sat-eur", "SAT EUR"), ("sat-pl", "SAT PL"), ("turb", "TURB"),
                     ("sun", "SUN")]
    # odstępy: po grupie METAR/TAF i po grupie WIND/RADAR (trzy grupy)
    seq = [i or "|" for i, _ in re.findall(r'\{ (?:id: "([^"]+)"|(sep): true)', mount)]
    assert seq[5:9] == ["|", "wind", "radar", "|"] and seq.count("|") == 2 and seq[-1] == "sun"
    # id podzakładek są częścią adresu "#meteo/<id>": bez "/"
    assert all("/" not in i for i, _ in items)


def test_windy_views(js):
    w = js["windy"]
    assert w["radar"] == RADAR_URL
    assert "overlay=satellite" in w["sat-pl"] and "lat=52.0&lon=19.0&" in w["sat-pl"] and "&zoom=6&" in w["sat-pl"]
    assert "overlay=satellite" in w["sat-eur"] and "lat=50.0&lon=12.0&" in w["sat-eur"] and "&zoom=4&" in w["sat-eur"]
    # SAT PL i SAT EUR bez zmian poza środkiem i zoomem (ten sam szablon co RADAR, przy ziemi)
    assert w["sat-pl"] == RADAR_URL.replace("lon=19.3", "lon=19.0").replace("overlay=radar", "overlay=satellite")
    for url in w.values():
        assert url.startswith("https://embed.windy.com/embed2.html?") and "metricWind=kt" in url


def test_icing_levels(js):
    """ICING: warstwa Windy "icing" na poziomie ciśnienia, przyciski w FL (ISA), domyślnie 700 hPa ≈ FL100."""
    assert [fl for fl, _ in js["icing"]] == ["FL050", "FL100", "FL140", "FL180", "FL240", "FL300"]
    levels = ["850h", "700h", "600h", "500h", "400h", "300h"]
    for (fl, url), lvl in zip(js["icing"], levels):
        assert url == (RADAR_URL.replace("lon=19.3", "lon=19.0").replace("level=surface", f"level={lvl}")
                       .replace("overlay=radar", "overlay=icing")), fl
    assert "&level=700h&overlay=icing&" in js["windy"]["icing"]
    assert js["icingLevel"] == ["300h", "700h", "700h"]
    assert 'lsGet("meteo.icing.level")' in METEO and "frameGo(frame, windyEmbedUrl(" in METEO


def test_gamet_helpers(js):
    g = js["gamet"]
    # wybór rejonu zapamiętany w localStorage; nieznany = ALL (wszystkie rejony jeden pod drugim)
    assert g["area"] == ["A3", "ALL", "ALL", "ALL"] and 'lsGet("meteo.gamet.area")' in METEO
    assert g["shown"] == [["A1", "A2", "A5"], ["A4"], []]
    assert g["valid"] == ["15.10 04:00–10:00Z", "15.10 22:00 – 16.10 04:00Z", "150400/151000", ""]
    assert g["expired"] == [True, False, False]
    assert g["urls"] == ["https://awiacja.imgw.pl/assets/img/gamet-map.webp",
                         "https://awiacja.imgw.pl/prognozy-lotnicze/gamet", 600000]
    # przyciski A1–A5 i ALL, tekst z backendu w <pre>, odnośnik do strony IMGW przy błędzie
    view = METEO[METEO.index("function gametTab("):METEO.index("// --- ICING")]
    assert '[...GAMET_AREAS, "ALL"]' in view and "<pre>${esc(a.text)}</pre>" in view and 'api("/api/meteo/gamet")' in view
    assert "awiacja.imgw.pl › GAMET ↗" in view and "imgEl(" in view and "clearInterval(timer)" in view
    assert re.search(r"offsetParent\s*!==\s*null", view)


def test_sun_helpers(js):
    s = js["sun"]
    assert s["icao"] == ["EPWA", "", "", ""]
    # godzina zaokrąglona do minuty; data, gdy zdarzenie wypada innego dnia UTC niż kolumna; czas polski pod spodem
    assert s["cell"][0] == "05:01Z"
    assert s["cell"][1] == '20:47Z <small class="d">14.10</small>'
    assert s["cell"][2] == '05:01Z<small class="loc">07:01 CEST</small>'
    assert s["cell"][3] == "–" and s["cell"][4] == '00:00Z <small class="d">16.10</small>'
    assert s["dur"] == ["10 h 41 min", "24 h", "0 min", "45 min", "–"]
    assert s["until"] == ["in <1 min", "in 12 min", "in 3 h 12 min"]
    assert s["polar"][0].startswith("polar day:") and s["polar"][1].startswith("polar night:")
    assert "more than 6°" in s["polar"][1] and "more than 6°" not in s["polar"][2]
    assert s["polar"][3].startswith("white nights:") and s["polar"][4] == ""
    assert s["edge"][0].startswith("polar day begins") and s["edge"][1].startswith("polar day ends")
    assert s["edge"][2].startswith("white nights begin") and s["edge"][3].startswith("white nights end")
    assert s["edge"][4] == ""
    # "Następne": pierwsze nieminione z listy, więc po zachodzie od razu EECT (bez czekania 10 min na serwer)
    assert s["next"] == ["sunset", "civil_dusk", "civil_dawn", None, "sunset", None, None]
    # zoom na start: świat (256 px · 2^zoom) mieści się w szerokości mapy, a o 0,25 większy już nie
    for w, z in s["zoom"]:
        assert z >= 1 and (z == 1 or 256 * 2 ** z <= w < 256 * 2 ** (z + 0.25)), (w, z)
    assert dict(s["zoom"]) == {932: 1.75, 698: 1.25, 1600: 2.5, 1024: 2, 1366: 2.25, 300: 1, 0: 1}
    # znacznik na kopii świata klikniętej albo najbliższej środka widoku
    assert [round(v, 2) for v in s["near"]] == [313, -47, -190, 380.97, 190]
    assert s["query"][0] == {"q": {"icao": "EPWA"}, "err": "", "label": "EPWA"}
    assert s["query"][1]["q"] is None and s["query"][1]["label"] == "EP-A" and "ICAO" in s["query"][1]["err"]
    assert s["query"][2]["q"] is None and s["query"][2]["label"] == ""
    assert s["ms"] == [60000, 600000]
    view = METEO[METEO.index("function sunTab("):METEO.index("export default {")]
    assert 'lsGet("meteo.sun.icao")' in view and '"EPWA"' in view and "BASEMAPS.dark(L, ctx?.config?.carto_api_key)" in view
    assert "/api/meteo/sun?" in view and "map.remove()" in view and "ro.disconnect()" in view
    # kod lotniska zapamiętany dopiero po odpowiedzi serwera (nieznany kod nie wraca po przeładowaniu), a zły format
    # kasuje zapytanie (zegar i powrót serwera nie wczytują znów poprzedniego lotniska)
    load = view[view.index("const load = async"):view.index("const pick =")]
    go = view[view.index("const go = () =>"):view.index('$(".sun-go")')]
    assert view.count('lsSet("meteo.sun.icao"') == 1 and load.index("await api(") < load.index('lsSet("meteo.sun.icao"')
    assert "lsSet(" not in go and "q = null" in go and "place.remove()" in go and "seq++" in go
    # kliknięcie mapy: do serwera długość -180..180, znacznik w klikniętym miejscu
    assert "wrapLon(e.latlng.lng), ref: e.latlng.lng" in view and "nearLon(d.lon, q.ref ?? map.getCenter().lng)" in view
    assert "sunZoom(" in view and "sunNext(data, now)" in view
    assert re.search(r"offsetParent\s*!==\s*null", view)


def test_turb_frames(js):
    assert js["steps"] == ["000", "003", "006", "009", "012", "015", "018", "021"]
    assert [f["label"] for f in js["frames"]] == ["+0 h", "+3 h", "+6 h", "+9 h", "+12 h", "+15 h", "+18 h", "+21 h"]
    assert [f["url"] for f in js["frames"]] == [f"{TURB_BASE}{s}.gif" for s in js["steps"]]
    assert js["ms"] == 1500


def test_sigwx_and_refresh(js):
    assert js["sigwx"] == "https://aviation-api.imgw.pl/image/significant/pl"
    assert js["refresh"] == 15 * 60000
    # znacznik czasu: pełny kwadrans UTC, ten sam w obrębie 15 min; "Wczytaj ponownie" z dokładnością do sekundy
    assert js["stamp"] == ["20261012121500", "20261012121500", "20261012123000", "20261012122205"]
    assert js["bust"] == ["https://aviation-api.imgw.pl/image/significant/pl?t=20261012121500", "https://x/y?a=1&t=1"]


def test_frame_order_logic(js):
    # następna klatka: po kolei z zawinięciem, klatki z błędem pominięte, null gdy wszystkie pozostałe z błędem
    assert js["next"] == [0, 3, 0, None, 7, 6]
    # krok animacji: następna wczytana klatka; czeka (ta sama), gdy następna się wczytuje; -1 = stop (nic się nie wczytało)
    assert js["play"][:9] == [1, 0, 0, 2, -1, 4, 0, 0, 2]
    # bieżąca klatka jeszcze się wczytuje (np. wolna +0 h na starcie): czeka na nią, nie przeskakuje do następnej
    assert js["play"][9:] == [0, 2, 4]


def test_fetched_time(js):
    """"pobrano": czas pierwszego udanego pobrania adresu, nie czas ponownego wyświetlenia z pamięci podręcznej."""
    assert js["fetched"] == ["2026-10-12T12:22:05.000Z", "2026-10-12T12:22:05.000Z", "2026-10-12T12:31:05.000Z"]


def test_images_loaded_by_browser():
    """Obrazy IMGW bezpośrednio z aviation-api.imgw.pl (bez pośrednictwa serwera PolIDS), bez nagłówka Referer."""
    # wszystkie <img> klatek (także te wczytywane w tle przy odświeżaniu) powstają w jednym miejscu, bez Referer
    assert re.search(r"referrerPolicy\s*=\s*[\"']no-referrer[\"']", METEO)
    assert len(re.findall(r"createElement\([\"']img[\"']\)", METEO)) == 1
    # obrazy nie przez serwer PolIDS: aviation-api.imgw.pl zna tylko services/gamet.py (tekst GAMET w JSON, bez obrazów)
    app = ROOT_DIR / "backend" / "app"
    assert "aviation-api" not in "".join(p.read_text("utf-8").lower() for p in app.rglob("*.py") if p.name != "gamet.py")
    gamet = (app / "services" / "gamet.py").read_text("utf-8")
    urls = re.findall(r"https://aviation-api\.imgw\.pl[^\"\s]*", gamet)
    assert urls and all(u.startswith("https://aviation-api.imgw.pl/data/last") for u in urls)
    assert "/image" not in gamet and "webp" not in gamet.lower()
    assert not re.search(r"api\([^)]*imgw", METEO, re.I)
    # błąd klatki: odnośnik do obrazu w nowej karcie; obraz dopasowany do okna
    assert re.search(r"open in new tab", METEO) and 'rel="noopener noreferrer"' in METEO
    assert re.search(r"object-fit:\s*contain", CSS)
    # timery odtwarzacza i odświeżania zatrzymywane przy zamknięciu podzakładki
    view = METEO[METEO.index("function imgView("):METEO.index("// --- WIND")]
    destroy = re.search(r"destroy:\s*\(\)\s*=>\s*\{(.*?)\}", view, re.S)
    assert destroy and re.search(r"clearInterval\(\s*play\s*\)", destroy.group(1))
    assert re.search(r"clearInterval\(\s*refreshTimer\s*\)", destroy.group(1))
    assert re.search(r"setInterval\(\s*tick\s*,\s*TURB_MS\s*\)", view)
    # animacja i odświeżanie tylko, gdy METEO jest na ekranie (ukryte zakładki zostają w DOM)
    assert re.search(r"offsetParent\s*!==\s*null", view)


def test_wind_opens_at_0ft():
    """Issue #18: WIND zawsze otwiera się na wietrze przy ziemi (0 ft); 3000 ft tylko do zamknięcia podzakładki, bez
    zapamiętywania (wcześniej zapamiętany wybór 3000 ft w localStorage jest pomijany)."""
    view = METEO[METEO.index("function windTab("):METEO.index("// --- GAMET")]
    assert re.search(r'let mode = "0";', view)
    assert not re.search(r'lsSet\("meteo\.wind\.mode"', METEO) and not re.search(r'lsGet\("meteo\.wind\.mode"', METEO)
    # pozostałe wybory WIND (lotnisko, pas lotniska) nadal zapamiętane
    assert 'lsGet("meteo.wind.ad")' in view and "lsGet(rwyKey())" in view
    # przyciski 0 ft / 3000 ft: 0 ft pierwszy
    assert '<button data-m="0">0 ft</button><button data-m="3000">3000 ft (approach)</button>' in view


def test_strings_in_english():
    """Issue #18: interfejs po angielsku: w kodzie METEO (bez komentarzy) nie ma polskich liter. Mapa QNH regionalnego
    (przenoszona do qnhmap.js) ma własne testy."""
    src = METEO
    a, b = src.find("// Mapa QNH regionalnego"), src.find("// --- RADAR, SAT PL")
    if 0 <= a < b:
        src = src[:a] + src[b:]
    code = "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in src.splitlines())
    assert not re.findall(r".{0,30}[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ].{0,30}", code)
    for txt in ("Updated ", ">Show</button>", "refresh every 2 min", ">FIT</button>", "image failed to load", ">Retry</button>",
                "Loading GAMET…", "No GAMET for area", "approach wind 3000 ft", "surface wind", "Main aerodromes",
                "CIVIL TWILIGHT", "Point on map"):
        assert txt in METEO, txt


def test_no_glow():
    assert "text-shadow" not in CSS and "glow" not in CSS.lower().replace("bez poświaty", "")
