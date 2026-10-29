"""0.13.1 (issue #25, MAP): panel boczny. Wszystkie sekcje domyślnie zwinięte (zapamiętane tylko rozwinięte, map.open),
AIRSPACE → VISIBILITY SETTINGS ze wszystkimi ustawieniami wyświetlania (ruch, przestrzeń i poziom, punkty i drogi,
podkład) jako podtytuły bez zwijania, Sector capacity → FMP. Przełączniki ruchu, plakietek i punktów zapamiętane
w map.air razem z warstwami przestrzeni."""
import re

from backend.app.config import ROOT_DIR

FRONTEND = ROOT_DIR / "frontend"


def _code(name):
    """Kod bez komentarzy (/* */ i // na końcu linii albo w osobnej linii; "https://" w napisie zostaje)."""
    src = re.sub(r"/\*.*?\*/", "", (FRONTEND / name).read_text("utf-8"), flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", src, flags=re.M)


def _panel():
    """Szablon panelu bocznego MAP (mainMap): od .mapside do przycisku »."""
    code = _code("js/tabs/map.js")
    return code.split('<div class="mapside">', 1)[1].split('<button class="btn ms-show"', 1)[0]


def _sections():
    return dict(re.findall(r'<section class="ms-card[^"]*" data-sec="(\w+)">(.*?)</section>', _panel(), flags=re.S))


def test_panel_sections_order():
    """Pięć sekcji: VISIBILITY SETTINGS (z poziomem w nagłówku), POSITIONS, ROUTE, FMP, LEGEND. Dawne Traffic, Airspace,
    Points and airways i Basemap nie są już osobnymi sekcjami."""
    panel = _panel()
    heads = re.findall(r'<section class="ms-card[^"]*" data-sec="(\w+)">\s*<h4>([^<]+)', panel)
    assert [(k, t.strip()) for k, t in heads] == [
        ("vis", "Visibility settings"), ("pos", "Positions"), ("route", "Route"), ("viff", "FMP"), ("legend", "Legend")]
    assert '<h4>Visibility settings <span class="vis-sum"></span></h4>' in panel
    assert 'class="ms-card as-card vis-card" data-sec="vis"' in panel
    # klasy i id sekcji FMP bez zmian (zapisany stan, reguły viff.css)
    assert 'class="ms-card vf-card" data-sec="viff"' in panel
    for gone in ("Sector capacity", "<h4>Airspace</h4>", "<h4>Points and airways</h4>", "<h4>Basemap</h4>", "<h4>Traffic</h4>"):
        assert gone not in _code("js/tabs/map.js"), gone
    assert not re.search(r'data-sec="(traffic|air|points|base)"', panel)


def test_visibility_holds_all_display_switches():
    """W jednej sekcji wszystkie ustawienia wyświetlania, w kolejności dawnych sekcji; poza nią tylko przełącznik FMP."""
    secs = _sections()
    vis = secs["vis"]
    assert re.findall(r'<div class="vis-sub">([^<]+)</div>', vis) == ["Traffic", "Airspace", "Points and airways", "Basemap"]
    order = ['sw("traffic"', 'class="ac-key"', 'sw("atc"', 'class="atc-info', 'class="traffic-info',
             'class="field fl"', 'class="allfl"', 'class="as-pre"', "AIR.map((a) =>", 'class="pk-btn"', 'sw("online"', 'sw("firs"',
             'class="sector-info', 'sw("aeros"', 'sw("navaids"', 'sw("ndbs"', 'sw("vfrs"', 'sw("fixes"', 'sw("airways"',
             'sw("labels"', "data-base=", 'sw("openaip"', "openaip-note"]
    at = [vis.index(s) for s in order]
    assert at == sorted(at), order
    # podtytuły między grupami
    subs = [vis.index(f'<div class="vis-sub">{t}</div>') for t in ("Airspace", "Points and airways", "Basemap")]
    assert at[4] < subs[0] < at[5] and at[12] < subs[1] < at[13] and at[19] < subs[2] < at[20]
    others = {k: re.findall(r'sw\("([\w-]+)"', v) for k, v in secs.items() if k != "vis"}
    assert others == {"pos": [], "route": [], "viff": ["viff"], "legend": []}
    # podtytuły nie zwijają się: zwijany jest tylko nagłówek h4 sekcji
    assert "vis-sub" not in _code("js/tabs/map.js").split("const open = new Set(")[1].split("});\n  });")[0]


def test_sections_collapsed_by_default():
    """Wszystkie sekcje zwinięte, dopóki użytkownik którejś nie rozwinie (map.open = lista rozwiniętych); dawny
    map.sections (rozwinięte Traffic, Airspace, Route…) pominięty."""
    code = _code("js/tabs/map.js")
    init = code.split("const open = new Set(")[1].split("const legendTab")[0]
    assert init.startswith('store.get("map.open", []).filter((k) => typeof k === "string"));')
    assert 'c.classList.toggle("shut", !open.has(k));' in init
    assert "if (c.classList.toggle(\"shut\")) open.delete(k); else open.add(k);" in init
    assert 'store.set("map.open", [...open]);' in init
    assert "map.sections" not in code
    assert 'k === "legend" || k === "pos"' not in code


def test_visibility_switches_saved():
    """Przełączniki ruchu, plakietek, punktów i dróg zapamiętane w map.air (stare wpisy bez tych kluczy: domyślne)."""
    code = _code("js/tabs/map.js")
    vis_sw = re.search(r"const VIS_SW = \{([^}]*)\};", code).group(1)
    assert dict(re.findall(r"(\w+): (true|false)", vis_sw)) == {
        "traffic": "true", "atc": "true", "aeros": "true", "navaids": "false", "ndbs": "false", "vfrs": "false",
        "fixes": "false", "airways": "false", "labels": "true"}
    assert 'const VIS_PTS = ["navaids", "ndbs", "vfrs", "fixes", "airways", "labels"];' in code
    assert "const visOn = (id) => airOn(id, VIS_SW[id]);" in code
    vis = _sections()["vis"]
    for k in ("traffic", "atc", "aeros", "navaids", "ndbs", "vfrs", "fixes", "airways", "labels"):
        assert re.search(rf'sw\("{k}", "[^"]*", visOn\("{k}"\)', vis), k
    # nakładka lotnicza bez zapisu (wymaga klucza, ładuje obce kafelki)
    assert 'sw("openaip", "aviation overlay")' in vis
    save = code.split("const saveAir = () => {")[1].split("\n  };")[0]
    assert '...Object.fromEntries(Object.keys(VIS_SW).map((k) => [k, $("." + k).checked]))' in save
    assert 'store.set("map.air", {' in save
    assert '$(".atc").addEventListener("change", () => { saveAir(); loadAtc(); });' in code
    assert '$(".traffic").addEventListener("change", () => { saveAir(); loadTraffic(); });' in code
    assert 'VIS_PTS.forEach((c) => $("." + c).addEventListener("change", () => { saveAir(); loadVisible(); }));' in code
    aeros = code.split('$(".aeros").addEventListener("change", (e) => {')[1].split("\n  });")[0]
    assert "saveAir();" in aeros and "map.removeLayer(layers.ads)" in aeros
    # lotniska wyłączone przy poprzedniej wizycie: warstwa zdjęta zaraz po utworzeniu warstw
    after = code.split("const layers = {")[1].split("\n  };", 1)[1]
    assert after.lstrip().startswith('if (!$(".aeros").checked) map.removeLayer(layers.ads);')


def test_visibility_level_summary():
    """Rysowany poziom w nagłówku zwiniętej sekcji (jak liczba stanowisk w Positions)."""
    code = _code("js/tabs/map.js")
    sync = code.split("const syncFl = () => {")[1].split("\n  };")[0]
    assert '$(".vis-sum").textContent = lv === null ? "all levels" : fl(lv);' in sync
    assert "const lv = level();" in sync


def test_fmp_label():
    """Sector capacity → FMP: nagłówek sekcji i zakładka legendy (klucz viff zostaje: zapisany map.legend.tab działa)."""
    code = _code("js/tabs/map.js")
    assert '["viff", "FMP", () => [' in code
    assert '"Capacity"' not in code and "Sector capacity" not in code


def test_panel_template_ascii():
    """Szablon nowej sekcji bez znaków spoza ASCII w kodzie (\\u2265, \\u25be jako escape)."""
    vis = _sections()["vis"]
    assert not re.search(r"[^\x00-\x7f]", vis)
    assert "(zoom \\u2265 8)" in vis and "all \\u25be" in vis


def test_map_css_vis_rules():
    """Reguły nowej sekcji tylko pod .vis-card (AD CIV używa tych samych .mapwrap/.mapside/.ms-card); bez pogrubienia,
    zaokrągleń, cieni i poświaty."""
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "css" / "map.css").read_text("utf-8"), flags=re.S)
    rules = re.findall(r"([^{}]*\bvis-(?:sub|sum)\b[^{}]*)\{([^}]*)\}", css)
    assert rules, "no .vis-sub / .vis-sum rules"
    for sel, body in rules:
        for part in sel.split(","):
            assert part.strip().startswith(".vis-card"), part
        assert "font-weight" not in body and "box-shadow" not in body and "text-shadow" not in body, sel
        assert not re.search(r"border-radius:\s*[1-9]", body), sel
    assert re.search(r"\.vis-card \.vis-sub \{", css)
    assert re.search(r"\.vis-card \.vis-sum \{", css)
    # zwijanie sekcji bez zmian (viff.css, każda .ms-card[data-sec] w MAP)
    viff = (FRONTEND / "css" / "viff.css").read_text("utf-8")
    assert ".mapside .ms-card.shut > :not(h4) { display: none !important; }" in viff


def test_tv_chart_not_opened_by_itself():
    """Okno wykresu TV (lewy dolny róg mapy) domyślnie zamknięte: przy pierwszym wejściu (bez map.viff.sel) żaden TV
    nie jest wybierany sam (dawniej pierwszy TV aktywnego scenariusza albo najbardziej obciążony); wykres otwiera wybór
    użytkownika (lista, scenariusz, wejście w sektor w panelu lotu), a zapisany wybór wraca po przeładowaniu."""
    code = _code("js/tabs/map.js")
    assert 'let viffSel = store.get("map.viff.sel", null);' in code
    # jedyne przypisania wyboru: odczyt zapisanego i selectTv (zapis w map.viff.sel)
    assert re.findall(r"\bviffSel\s*=[^=]", code) == ["viffSel = ", "viffSel = "]
    select = code.split("const selectTv = (id) => {")[1].split("\n  };")[0]
    assert "viffSel = id;" in select and 'store.set("map.viff.sel", id);' in select
    load = code.split("const loadViff = async () => {")[1].split("\n  };")[0]
    assert "viffSel" not in load and "loadRatio" not in load and ".active)?.tvs" not in load
    assert "loadRatio" not in code
    # okno pokazane tylko dla wybranego TV przy włączonym FMP
    render = code.split("const renderChart = () => {")[1].split("\n  };")[0]
    assert "const tv = (viffData?.sectors || []).find((t) => t.id === viffSel);" in render
    assert 'const show = !!tv && $(".viff").checked;' in render
    assert 'chartEl.style.display = show ? "" : "none";' in render
    # wybór z listy, ze scenariusza i z panelu lotu, zamknięcie ✕ zapisuje pusty wybór
    assert '$(".viff-tv").addEventListener("change", (e) => selectTv(e.target.value));' in code
    assert 'if (b) selectTv(b.dataset.tv);' in code
    assert 'if (e.target.closest(".vf-close")) { selectTv(""); return; }' in code
