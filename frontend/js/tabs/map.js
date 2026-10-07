import { BASEMAPS, LIGHT_BASEMAPS, api, atcPositions, esc, h, hhmm, lsGet, lsSet, subtabs, vatsimAtc, vatsimOnline } from "../api.js";
import { chartHtml, delayClass, listRow, loadRatio, stateChip, tvGroup, tvLabel } from "../viffchart.js";
import { FACILITIES, PLANE_PATH, SymbolMarker, aircraftMarker, airportBadge, atcPanes, drawFirs, drawSectors, fl, loadFirs, loadVacs, sectorOwners, symbolFor, symbolSvg,
  vacsLayer } from "../airspace.js";
import { sectorSplit } from "../sectorsplit.js";

// Kolory zależne od podkładu (ciemny / jasny)
const THEME = {
  dark: { ad: "#c8ced4", vor: "#3ecf6e", ndb: "#c58cff", fix: "#8c969e", vfr: "#ffb020", route: "#ff4dd2", flight: "#ff9f1a", halo: "#000", airway: "#5f6b78",
    tma: "#7f95ff", ctr: "#ff6b6b" },
  light: { ad: "#33393f", vor: "#0a7a36", ndb: "#7b2cbf", fix: "#5c656c", vfr: "#c26a00", route: "#b0007c", flight: "#d4380d", halo: "#fff", airway: "#8b96a0",
    tma: "#3550c8", ctr: "#d62828" },
};
const KIND_COLOR = { aerodrome: "ad", vor: "vor", ndb: "ndb", fix: "fix", vfr: "vfr" };
const sw = (cls, label, checked = false, sym = "") => `<label class="sw"><input type="checkbox" class="${cls}" ${checked ? "checked" : ""}>
  <span class="sw-sym">${sym}</span><span>${label}</span></label>`;
const PLANE_SVG = `<svg class="sym" width="18" height="18" viewBox="-10 -10 20 20"><path d="${PLANE_PATH}" class="acsym"/></svg>`;
// localStorage bywa niedostępny (tryb prywatny): odczyt i zapis zawsze w try
const store = {
  get: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* tryb prywatny */ } },
};
// liczebnik z rzeczownikiem po polsku: 1 punkt, 2 punkty, 5 punktów
const plural = (n, one, few, many) => `${n} ${n === 1 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many}`;
const lg = (sym, label, cls = "") => `<div class="lgx-i ${cls}"><span class="lgx-s">${sym}</span><span>${label}</span></div>`;
// Legenda w zakładkach (zwinięta domyślnie razem z całą sekcją)
const LEGEND = [
  ["air", "Przestrzeń", () => [
    lg(`<span class="swatch sec"></span>`, "sektor EPWW (kontur)"), lg(`<span class="swatch on"></span>`, "sektor obsadzony (online)"),
    lg(`<span class="swatch unicom"></span>`, "sektor bez kontrolera (UNICOM 122.800)"), lg(`<span class="lg-freq">133.475</span>`, "częstotliwość sektora"),
    lg(`<span class="swatch tma"></span>`, "TMA (wypełniona, gdy APP online)"), lg(`<span class="swatch ctr"></span>`, "CTR (wypełniona, gdy TWR online)"),
    lg(`<span class="swatch fir"></span>`, "granica FIR sąsiedniego"),
    `<p class="lgx-note">Właściciel sektora ACC: pierwsze stanowisko online z łańcucha VACS w warstwie wybranego poziomu
      (LOW do FL335, MID do FL365, HIGH wyżej). TMA i CTR: lista OWNER z pliku .ese. Mapy warstw: MAP → SEKTORYZACJA.</p>`].join("")],
  ["pts", "Punkty", () => [
    lg(`<i data-sym="aerodrome"></i>`, "lotnisko"), lg(`<i data-sym="vor"></i>`, "VOR / DME"), lg(`<i data-sym="ndb"></i>`, "NDB"),
    lg(`<i data-sym="vfr"></i>`, "punkt VFR"), lg(`<i data-sym="fix"></i>`, "punkt FIX"), lg(`<span class="swatch awy"></span>`, "droga lotnicza"),
    lg(PLANE_SVG, "samolot VATSIM"), lg(`<span class="lg-line lg-flight"></span>`, "trasa wybranego samolotu"),
    lg(`<span class="lg-line lg-route"></span>`, "trasa wpisana ręcznie")].join("")],
  ["atc", "Kontrolerzy", (ctx) => `${FACILITIES.map(([k, l, n]) => lg(`<span class="ab ab-${k.toLowerCase()}">${l}</span>`, n)).join("")}
    ${lg(`<span class="ab ab-ctr">CTR</span>`, "Control (FIR)")}
    <p class="lgx-note">Najedź na plakietkę, żeby zobaczyć, kto jest online. Oficjalna mapa sektorów:
      <a href="${esc(ctx.config.links.sectors)}" target="_blank" rel="noopener">plvacc.pl/acc-sectors ↗</a></p>`],
  ["viff", "vIFF", () => [
    lg(`<span class="swatch viff"></span>`, "obszar TV z wykresu"), lg(`<span class="vs-chip on">AKTYWNY</span>`, "scenariusz / TV aktywny"),
    lg(`<span class="vf-bar"><i class="ok" style="width:60%"></i></span>`, "obciążenie &lt; 90 %"), lg(`<span class="vf-bar"><i class="near" style="width:95%"></i></span>`, "90–100 %"),
    lg(`<span class="vf-bar"><i class="over" style="width:100%"></i></span>`, "ponad przepustowość"), lg(`<span class="vf-bar"><i class="nolim" style="width:40%"></i></span>`, "bez limitu"),
    lg(`<span class="fs fs-fi">FI</span>`, "plan złożony"), lg(`<span class="fs fs-si">SI</span>`, "slot (CTOT)"), lg(`<span class="fs fs-su">SU</span>`, "zawieszony (FLS)"),
    lg(`<span class="fs fs-aa">AA</span>`, "aktywowany (AOBT)"), lg(`<span class="fs fs-ta">TA</span>`, "w powietrzu (ATOT)"),
    lg(`<span class="fd-ctot d15">+10</span><span class="fd-ctot d30">+20</span><span class="fd-ctot d45">+40</span><span class="fd-ctot d60">+50</span>`, "opóźnienie CTOT w minutach (jak w liście lotów NM)", "w"),
  ].join("")],
];

// Widok MAPA: duża mapa z panelem bocznym. Element budowany raz i przepinany między podzakładkami (stan mapy zostaje).
function mainMap(ctx) {
  const pane = h(`<div class="pane fill"><div class="mapwrap">
    <div class="mapside">
      <div class="ms-head"><b>MAPA</b><span class="hint">AIRAC ${esc(ctx.config.airac?.ident || "")}</span>
        <button class="btn ms-hide" title="Schowaj panel">«</button></div>
      <section class="ms-card" data-sec="traffic">
        <h4>Ruch VATSIM</h4>
        ${sw("traffic", "samoloty", true, PLANE_SVG)}
        ${sw("traffic-detail", "etykiety z FL, typem i GS")}
        ${sw("atc", "kontrolerzy online: plakietki (FIR EPWW, u sąsiadów tylko APP)", true, `<span class="ab ab-twr">T</span>`)}
        <div class="atc-info hint"></div>
        <div class="traffic-info hint"></div>
      </section>
      <section class="ms-card" data-sec="route">
        <h4>Trasa</h4>
        <textarea class="field route" rows="3" placeholder="np. EPKK OKENO N871 POLON L980 VAMPU EPGD"></textarea>
        <div class="ms-row"><button class="btn primary show-route">Pokaż trasę</button><button class="btn clear-route">Wyczyść</button></div>
        <div class="route-info hint"></div>
      </section>
      <section class="ms-card" data-sec="air">
        <h4>Przestrzeń</h4>
        <div class="ms-row"><label class="hint">Poziom</label><span class="flbox">FL<input type="number" class="field fl" value="300" min="0" max="660" step="5"></span></div>
        ${sw("sectors", "sektory EPWW", true, `<span class="swatch sec"></span>`)}
        ${sw("online", "aktualna sektoryzacja (kto jest online)", true, `<span class="swatch on"></span>`)}
        ${sw("tma", "TMA", true, `<span class="swatch tma"></span>`)}
        ${sw("ctrs", "CTR (wypełnione, gdy TWR online)", true, `<span class="swatch ctr"></span>`)}
        ${sw("firs", "granice FIR-ów sąsiednich (VATSpy)", true, `<span class="swatch fir"></span>`)}
        <div class="sector-info hint"></div>
      </section>
      <section class="ms-card vf-card" data-sec="viff">
        <h4>Przepustowość sektorów (vIFF)</h4>
        ${sw("viff", "ruch i przepustowość na godzinę naprzód", true, `<span class="swatch viff"></span>`)}
        <div class="vs-list"></div>
        <div class="vs-sub">Wszystkie sektory (traffic volumes)</div>
        <select class="field viff-tv"><option value="">wybierz sektor…</option></select>
        <div class="viff-info hint"></div>
      </section>
      <section class="ms-card" data-sec="points">
        <h4>Punkty i drogi</h4>
        ${sw("ads", "lotniska", true, `<i data-sym="aerodrome"></i>`)}
        ${sw("navaids", "VOR / DME", false, `<i data-sym="vor"></i>`)}
        ${sw("ndbs", "NDB", false, `<i data-sym="ndb"></i>`)}
        ${sw("vfrs", "punkty VFR <small>(zoom ≥ 8)</small>", false, `<i data-sym="vfr"></i>`)}
        ${sw("fixes", "punkty FIX <small>(zoom ≥ 8)</small>", false, `<i data-sym="fix"></i>`)}
        ${sw("airways", "drogi lotnicze <small>(zoom ≥ 7)</small>", false, `<span class="swatch awy"></span>`)}
        ${sw("labels", "nazwy punktów", true)}
      </section>
      <section class="ms-card" data-sec="base">
        <h4>Podkład</h4>
        <div class="seg">${[["dark", "ciemny"], ["light", "jasny"], ["white", "biały"], ["osm", "OSM"]]
          .map(([v, l]) => `<button data-base="${v}" class="${v === "dark" ? "on" : ""}">${l}</button>`).join("")}</div>
        ${sw("openaip", "nakładka lotnicza OpenAIP")}
        <div class="hint openaip-note"></div>
      </section>
      <section class="ms-card lgx" data-sec="legend">
        <h4>Legenda</h4>
        <div class="lgx-tabs">${LEGEND.map(([k, l]) => `<button data-lg="${k}">${l}</button>`).join("")}</div>
        ${LEGEND.map(([k, , body]) => `<div class="lgx-body" data-lg="${k}">${body(ctx)}</div>`).join("")}
      </section>
    </div>
    <button class="btn ms-show" title="Pokaż panel">»</button>
    <div class="map"></div>
  </div></div>`);
  const $ = (s) => pane.querySelector(s);
  const mapEl = $(".map");
  const map = L.map(mapEl, { preferCanvas: true, zoomSnap: 0.5 }).setView([52.0, 19.3], 6);
  const key = ctx.config.carto_api_key;
  let baseName = lsGet("map.base") || "dark";  // wspólny z widokiem SEKTORYZACJA
  let base = null;
  let theme = THEME.dark;
  const layers = {
    firs: L.layerGroup().addTo(map), sectors: L.layerGroup().addTo(map), airways: L.layerGroup(),
    airOn: L.layerGroup().addTo(map), tma: L.layerGroup().addTo(map), ctrs: L.layerGroup().addTo(map),
    ads: L.layerGroup().addTo(map), points: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map), atc: L.layerGroup().addTo(map),
    traffic: L.layerGroup().addTo(map), flight: L.layerGroup().addTo(map), viff: L.layerGroup().addTo(map),
  };
  let openaip = null;
  const panes = atcPanes(map);

  const paintLegend = () => pane.querySelectorAll("i[data-sym]").forEach((i) => {
    i.outerHTML = `<i data-sym="${i.dataset.sym}">${symbolSvg(i.dataset.sym, THEME.dark[KIND_COLOR[i.dataset.sym]])}</i>`;
  });
  paintLegend();

  // Sekcje panelu zwijane kliknięciem w nagłówek (stan w localStorage); legenda domyślnie zwinięta
  const secs = store.get("map.sections", {});
  pane.querySelectorAll(".ms-card[data-sec]").forEach((c) => {
    const k = c.dataset.sec;
    c.classList.toggle("shut", secs[k] ?? k === "legend");
    const h4 = c.querySelector("h4");
    h4.classList.add("ms-tog");
    h4.title = "Zwiń / rozwiń";
    h4.addEventListener("click", () => { secs[k] = c.classList.toggle("shut"); store.set("map.sections", secs); });
  });
  const legendTab = (k) => {
    k = LEGEND.some(([x]) => x === k) ? k : LEGEND[0][0];
    pane.querySelectorAll(".lgx [data-lg]").forEach((el) => el.classList.toggle("on", el.dataset.lg === k));
    store.set("map.legend.tab", k);
  };
  $(".lgx-tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-lg]"); if (b) legendTab(b.dataset.lg); });
  legendTab(store.get("map.legend.tab", "air"));

  const setBase = (name) => {
    baseName = BASEMAPS[name] ? name : "dark";
    lsSet("map.base", baseName);
    if (base) map.removeLayer(base);
    base = BASEMAPS[baseName](L, key).addTo(map);
    base.bringToBack?.();
    const light = LIGHT_BASEMAPS.includes(baseName);
    theme = light ? THEME.light : THEME.dark;
    mapEl.classList.toggle("light", light);
    mapEl.classList.toggle("white", baseName === "white");
    pane.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.base === baseName));
    drawAds(); loadVisible(); redrawFlight(); redrawRoute(); drawAirspace(); loadSectors();
  };
  $(".seg").addEventListener("click", (e) => { const b = e.target.closest("button[data-base]"); if (b) setBase(b.dataset.base); });
  $(".openaip").addEventListener("change", (e) => {
    const k = ctx.config.openaip_api_key;
    if (!k) {
      e.target.checked = false;
      $(".openaip-note").textContent = "Brak klucza: załóż darmowe konto na openaip.net i wpisz POLIDS_OPENAIP_API_KEY w pliku .env";
      return;
    }
    if (e.target.checked) {
      openaip = L.tileLayer(`https://api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png?apiKey=${encodeURIComponent(k)}`,
        { attribution: "© openAIP", maxZoom: 14, opacity: 0.9 }).addTo(map);
    } else if (openaip) { map.removeLayer(openaip); }
  });
  $(".ms-hide").addEventListener("click", () => { pane.querySelector(".mapwrap").classList.add("collapsed"); setTimeout(() => map.invalidateSize(), 50); });
  $(".ms-show").addEventListener("click", () => { pane.querySelector(".mapwrap").classList.remove("collapsed"); setTimeout(() => map.invalidateSize(), 50); });

  // Punkt jako symbol EuroScope z nazwą obok
  const pointMarker = (p, { color, label = true, scale = 1.6, weight = 1.6, permanent = true, cls = "lbl", popup = true, tooltip = true } = {}) => {
    const sym = symbolFor(p.kind);
    const m = new SymbolMarker([p.lat, p.lon], { symbol: sym, color: color || theme[KIND_COLOR[sym]], scale, weight, radius: 7 * scale / 1.6 });
    const full = `${esc(p.ident)} ${esc(p.kind)}${p.frequency ? " " + esc(p.frequency) : ""}${p.name ? " " + esc(p.name) : ""}`;
    if (label) m.bindTooltip(esc(p.ident), { permanent, direction: "right", offset: [6 * scale / 1.6, 0], className: cls });
    else if (tooltip) m.bindTooltip(full);
    if (label && popup) m.bindPopup(full);
    return m;
  };

  // --- dymek lotniska: ICAO, nazwa, METAR, kontrolerzy online i ATIS (dane ładowane po najechaniu)
  let atcData = { airports: [] };
  const metarCache = {};
  const metarFor = (icao) => {
    const hit = metarCache[icao];
    if (hit && Date.now() - hit.t < 120000) return hit.p;
    const p = api(`/api/meteo/metar?ids=${icao}`).then((r) => r[0]?.raw || null).catch(() => null);
    metarCache[icao] = { t: Date.now(), p };
    return p;
  };
  const adCard = (icao, name, metar) => {
    const ap = atcData.airports.find((a) => a.icao === icao);
    const fac = ap?.facilities || {};
    const ctrls = FACILITIES.filter(([k]) => k !== "ATIS" && fac[k]).flatMap(([k, l]) => fac[k].map((c) => ({ ...c, k, l })));
    const atis = fac.ATIS || [];
    return `<div class="adc-h"><b>${esc(icao)}</b><span>${esc(name || "")}</span></div>
      <div class="adc-sec">METAR</div><div class="adc-metar">${metar === undefined ? '<span class="muted">ładowanie…</span>' : metar ? esc(metar) : '<span class="muted">brak</span>'}</div>
      <div class="adc-sec">Kontrola</div>${ctrls.length ? `<table>${ctrls.map((c) => `<tr><td><span class="ab ab-${c.k.toLowerCase()}">${c.l}</span></td>
        <td class="cs">${esc(c.callsign)}</td><td class="fq">${esc(c.frequency)}</td><td>${esc(c.name || "")}</td><td class="muted">od ${hhmm(c.logon_time)}</td></tr>`).join("")}</table>`
        : '<div class="muted">nikt nie jest zalogowany (UNICOM 122.800)</div>'}
      ${atis.map((a) => `<div class="adc-sec">ATIS ${esc(a.atis_code || "")} <span class="muted">${esc(a.callsign)} ${esc(a.frequency)}</span></div>
        <div class="adc-atis">${(a.text_atis || []).map(esc).join(" ")}</div>`).join("")}`;
  };
  // Dymek podpinamy do markera; METAR doładowuje się przy pierwszym najechaniu
  const bindAdCard = (m, icao, name) => {
    m.bindTooltip(() => adCard(icao, name, metarCache[icao]?.v), { direction: "top", offset: [0, -8], className: "atc-tip ad-tip", opacity: 1, pane: panes.tip });
    m.on("tooltipopen", async () => {
      const v = await metarFor(icao);
      if (metarCache[icao]) metarCache[icao].v = v;
      if (m.isTooltipOpen()) m.setTooltipContent(adCard(icao, name, v));
    });
    return m;
  };

  // --- lotniska (lotnisko z plakietką ATC nie dostaje osobnej nazwy: ICAO jest na plakietce)
  let ads = [];
  let atcAds = new Set();
  const drawAds = () => {
    layers.ads.clearLayers();
    const z = map.getZoom();
    ads.forEach((a) => {
      const big = a.kind === "large_airport" || a.kind === "medium_airport";
      if (!big && z < 8 && !atcAds.has(a.icao)) return;
      const scale = big ? 1.8 : 1.4;
      const m = pointMarker({ ident: a.icao, kind: "AD", lat: a.lat, lon: a.lon, name: a.name }, { label: false, tooltip: false, scale, popup: false })
        .on("click", () => ctx.open("aerodrome", a.icao)).addTo(layers.ads);
      bindAdCard(m, a.icao, a.city || a.name);
      // nazwa jako osobna stała etykieta (marker ma już dymek z kartą lotniska)
      if (!atcAds.has(a.icao) && (z >= 7 || (big && z >= 6))) {
        L.tooltip([a.lat, a.lon], { content: esc(a.icao), permanent: true, direction: "right", offset: [6 * scale / 1.6, 0], className: "lbl", interactive: false })
          .addTo(layers.ads);
      }
    });
  };
  api("/api/aerodromes").then((list) => {
    ads = list.filter((a) => a.kind !== "small_airport" || a.icao.startsWith("EP"));
    loadAtc();
  });
  $(".ads").addEventListener("change", (e) => (e.target.checked ? layers.ads.addTo(map) : map.removeLayer(layers.ads)));

  // --- TMA i CTR: kontury z pliku .sct (jak w EuroScope), wypełnienie z sektorów .ese, gdy obsadzone:
  // CTR, gdy właścicielem jest TWR; TMA, gdy APP
  const airspaceLines = { tma: api("/api/nav/airspace?kind=tma").catch(() => null), ctr: api("/api/nav/airspace?kind=ctr").catch(() => null) };
  const drawAirspace = async () => {
    const [tma, ctr] = await Promise.all([airspaceLines.tma, airspaceLines.ctr]);
    layers.tma.clearLayers();
    layers.ctrs.clearLayers();
    if (tma && $(".tma").checked) {
      L.geoJSON(tma, { interactive: false, style: (f) => (f.properties.inner
        ? { color: theme.tma, weight: 1, opacity: 0.55, dashArray: "4 4" } : { color: theme.tma, weight: 1.6, opacity: 0.95 }) }).addTo(layers.tma);
    }
    if (ctr && $(".ctrs").checked) {
      L.geoJSON(ctr, { interactive: false, style: { color: theme.ctr, weight: 1.4, opacity: 0.9, dashArray: "6 3" } }).addTo(layers.ctrs);
    }
  };
  let allSectors = null;
  const isCtr = (n) => /^EP[A-Z]{2}_M?CTR\d*$/.test(n);
  const isTma = (n) => /^EP[A-Z]{2}_M?TMA/.test(n);
  function drawAirspaceFills(gj, positions, online) {
    layers.airOn.clearLayers();
    if (!gj || !online) return;
    const want = (n) => ($(".ctrs").checked && isCtr(n)) || ($(".tma").checked && isTma(n));
    const feats = gj.features.filter((f) => want(f.properties.name));
    const owners = sectorOwners({ features: feats }, positions, online).sector_owner;
    const seen = new Set();
    feats.forEach((f) => {
      const n = f.properties.name, own = owners[n];
      const ctr = isCtr(n);
      if (!own || !own.callsign.endsWith(ctr ? "_TWR" : "_APP")) return;
      const key = ctr ? n.split("_")[0] : n;
      if (seen.has(key)) return;  // EPKK_CTR07 / CTR25 to ta sama strefa w dwóch konfiguracjach
      seen.add(key);
      const color = ctr ? theme.ctr : theme.tma;
      L.geoJSON(f, { style: { stroke: false, fillColor: color, fillOpacity: ctr ? 0.24 : 0.13 } })
        .bindTooltip(`<b>${esc(ctr ? key + " CTR" : n)}</b> ${fl(f.properties.lower_ft)}–${fl(f.properties.upper_ft)}<br>${esc(own.callsign)} ${esc(own.frequency)} · ${esc(own.name || "")}`, { sticky: true })
        .addTo(layers.airOn);
    });
  }
  ["tma", "ctrs"].forEach((c) => $("." + c).addEventListener("change", () => { drawAirspace(); loadSectors(); }));

  // --- sektory EPWW i FIR-y sąsiednie, podświetlone wg zalogowanych kontrolerów
  const loadSectors = async () => {
    const level = parseInt($(".fl").value || "0", 10);
    const wantOnline = $(".online").checked;
    const needAir = $(".tma").checked || $(".ctrs").checked;
    const [gj, firs, net, positions, gjAll, vacs] = await Promise.all([
      $(".sectors").checked ? api(`/api/nav/sectors?fir=EPWW&level_ft=${level * 100}`).catch((e) => ({ error: e.message })) : null,
      $(".firs").checked ? loadFirs().catch(() => null) : null,
      wantOnline || $(".firs").checked || needAir ? vatsimOnline().catch((e) => ({ error: e.message })) : null,
      atcPositions().catch(() => []),
      needAir ? (allSectors ||= api("/api/nav/sectors?fir=EPWW").catch(() => { allSectors = null; return null; })) : null,
      loadVacs().catch(() => null),
    ]);
    layers.sectors.clearLayers();
    layers.firs.clearLayers();
    // podświetlenie obsady tylko w FIR EPWW; FIR-y sąsiednie jako same kontury
    const epwwOnline = Object.fromEntries(Object.entries(net?.firs || {}).filter(([id]) => id.startsWith("EPWW")));
    if (firs) drawFirs(layers.firs, firs, epwwOnline, { panes });
    drawAirspaceFills(gjAll, positions, net && !net.error ? net.positions : null);
    if (!gj) { $(".sector-info").textContent = ""; return; }
    if (gj.error) { $(".sector-info").innerHTML = `<span class="error">Sektory EPWW: ${esc(gj.error)}</span>`; return; }
    // sektory ACC wg łańcuchów VACS (warstwa z poziomu), pozostałe wg listy OWNER z pliku .ese
    const online = wantOnline && net && !net.error ? sectorOwners(gj, positions, net.positions, vacs) : null;
    drawSectors(layers.sectors, gj, online, { tipPane: panes.tip });
    const layer = vacsLayer(level * 100);
    $(".sector-info").innerHTML = net?.error ? `<span class="error">${esc(net.error)}</span>`
      : online ? `${Object.keys(online.vacs).length ? `Sektory ACC wg łańcuchów VACS, warstwa <b>${layer}</b> (${esc(vacs.layers?.[layer]?.label || "")}).<br>` : ""}`
        + `Online: ${Object.values(net.positions).filter((c) => c.callsign.startsWith("EPWW")).map((c) => esc(c.callsign)).join(", ") || "brak kontrolerów EPWW"}`
        : `${gj.features.length} sektorów na ${fl(level * 100)} (podział pełny)`;
  };
  ["sectors", "online", "firs"].forEach((c) => $("." + c).addEventListener("change", loadSectors));
  $(".fl").addEventListener("change", loadSectors);
  setInterval(() => document.body.contains(pane) && loadSectors(), 60000);

  // --- vIFF: ruch vs przepustowość sektorów (traffic volumes) na godzinę naprzód.
  // W panelu najpierw scenariusze (aktywne na górze) z ich TV, pod nimi lista wszystkich TV; wykres wybranego TV
  // z listą lotów w lewym dolnym rogu mapy, obrys TV na mapie.
  let viffData = null;
  let viffSel = store.get("map.viff.sel", null);
  let pilots = [], pilotIdx = new Map();
  let chartSel = null;  // lot, do którego tabela wykresu była już przewinięta
  const chart = L.control({ position: "bottomleft" });
  chart.onAdd = () => {
    const el = L.DomUtil.create("div", "viff-chart");
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
    el.addEventListener("click", (e) => {
      if (e.target.closest(".vf-close")) { selectTv(""); return; }
      const r = e.target.closest("tr[data-cs]");
      if (r) showFlight(r.dataset.cs);
    });
    return el;
  };
  chart.addTo(map);
  const chartEl = chart.getContainer();
  // obrys: litera sektora EPWW (EPWW-BH → sektory EPWWB na wszystkich poziomach) albo TMA lotniska (EPWA-TMA)
  const drawTvArea = async (tv) => {
    layers.viff.clearLayers();
    if (!tv) return;
    const [secs, tma] = await Promise.all([allSectors ||= api("/api/nav/sectors?fir=EPWW").catch(() => { allSectors = null; return null; }), airspaceLines.tma]);
    const feats = [];
    tv.volumes.forEach((v) => {
      const [area, part = ""] = v.split("-");
      if (area === "EPWW" && /^[A-Z]/.test(part)) {
        const n = "EPWW" + part[0];
        feats.push(...(secs?.features || []).filter((f) => f.properties.name === n || f.properties.name.startsWith(n + "-")));
      } else if (/TMA/.test(part)) {
        feats.push(...(tma?.features || []).filter((f) => f.properties.name.startsWith(area + " ") && !f.properties.inner));
        feats.push(...(secs?.features || []).filter((f) => f.properties.name.startsWith(area + "_") && /TMA/.test(f.properties.name)));
      }
    });
    if (viffSel !== tv.id) return;
    L.geoJSON({ type: "FeatureCollection", features: feats }, { interactive: false,
      style: { color: "#ffd400", weight: 2.6, opacity: 0.95, fillColor: "#ffd400", fillOpacity: 0.025 } }).addTo(layers.viff);
  };
  // warunki aktywacji scenariusza (vIFF sam decyduje, czy jest aktywny; pokazujemy tylko warunki)
  const scnCond = (s) => {
    const b = (xs, sep) => xs.map((x) => `<b>${esc(x)}</b>`).join(sep);
    const out = [];
    if (s.positions.length) out.push(`gdy online: ${b(s.positions, " + ")}`);
    if (s.anypositions.length) out.push(`gdy online: ${b(s.anypositions, " lub ")}`);
    if (s.nopositions.length) out.push(`i offline: ${b(s.nopositions, ", ")}`);
    if (s.booked) out.push("liczą się też rezerwacje");
    if (s.start && s.end && !(s.start === "0000" && s.end === "2359")) out.push(`godz. <b>${esc(s.start)}–${esc(s.end)}</b>`);
    s.times.forEach((t) => out.push(`${t.date ? esc(t.date) + " " : ""}godz. <b>${esc(t.from)}–${esc(t.to)}</b>`));
    return out.join(" · ") || "bez warunków";
  };
  const scnHtml = (s, byId) => `<div class="vs-scn ${s.active ? "on" : ""}"${s.description ? ` title="${esc(s.description)}"` : ""}>
      <div class="vs-top"><b>${esc(s.id)}</b>${s.active ? `<span class="vs-chip on">AKTYWNY</span>` : ""}<span class="vs-n">${s.tvs.length} TV</span></div>
      <div class="vs-cond">${scnCond(s)}</div>
      ${s.tvs.map((t) => listRow(byId[t.id], viffSel, t.id)).join("")}</div>`;
  const renderChart = () => {
    const tv = (viffData?.sectors || []).find((t) => t.id === viffSel);
    const show = !!tv && $(".viff").checked;
    const keep = chartEl.querySelector(".vf-tblwrap")?.scrollTop || 0;
    chartEl.style.display = show ? "" : "none";
    chartEl.innerHTML = show ? chartHtml(tv, viffData.now, (cs) => pilotIdx.get(cs), selected) : "";
    const w = chartEl.querySelector(".vf-tblwrap");
    if (w) w.scrollTop = keep;
    // nowo wybrany lot spoza widocznej części tabeli: przewiń do jego wiersza
    const r = selected !== chartSel && w?.querySelector("tr.on");
    if (r && (r.offsetTop < w.scrollTop + 20 || r.offsetTop + r.offsetHeight > w.scrollTop + w.clientHeight)) w.scrollTop = r.offsetTop - w.clientHeight / 2;
    if (show) chartSel = selected;
    fitFd();
    return show ? tv : null;
  };
  const drawViff = () => {
    const list = viffData?.sectors || [], scns = viffData?.scenarios || [];
    const byId = Object.fromEntries(list.map((t) => [t.id, t]));
    const act = scns.filter((s) => s.active), off = scns.filter((s) => !s.active);
    $(".vs-list").innerHTML = !viffData || !$(".viff").checked ? "" : !scns.length ? `<div class="vs-none">vIFF nie podał scenariuszy</div>`
      : `<div class="vs-sub">Scenariusze <span>aktywne: ${act.length} z ${scns.length}</span></div>
      ${act.map((s) => scnHtml(s, byId)).join("") || `<div class="vs-none">żaden scenariusz nie jest teraz aktywny</div>`}
      ${off.length ? `<details class="vs-more" ${store.get("map.viff.off", false) ? "open" : ""}><summary>Nieaktywne scenariusze (${off.length})</summary>
        ${off.map((s) => scnHtml(s, byId)).join("")}</details>` : ""}`;
    // wszystkie TV: aktywne (status 1 albo w aktywnym scenariuszu) i nieaktywne
    const groups = { aktywne: [], nieaktywne: [] };
    list.forEach((t) => groups[tvGroup(t)].push(t));
    $(".viff-tv").innerHTML = `<option value="">wybierz sektor…</option>` + Object.entries(groups).filter(([, ts]) => ts.length).map(([g, ts]) =>
      `<optgroup label="${g} (${ts.length})">${ts.map((t) => `<option value="${esc(t.id)}" ${t.id === viffSel ? "selected" : ""}>${esc(t.id)} · ${esc(tvLabel(t.id))}</option>`).join("")}</optgroup>`).join("");
    drawTvArea(renderChart());
  };
  const selectTv = (id) => {
    viffSel = id;
    store.set("map.viff.sel", id);
    drawViff();
  };
  const loadViff = async () => {
    $(".vf-card").classList.toggle("off", !$(".viff").checked);  // wyłączony vIFF: bez scenariuszy i listy TV
    if (!$(".viff").checked) { chartEl.style.display = "none"; layers.viff.clearLayers(); $(".vs-list").innerHTML = ""; $(".viff-info").textContent = ""; fitFd(); return; }
    try {
      viffData = await api("/api/viff/sectors");
      // pierwszy raz: pierwszy TV aktywnego scenariusza, a bez niego najbardziej obciążony
      if (viffSel === null && viffData.sectors.length) {
        viffSel = viffData.scenarios?.find((x) => x.active)?.tvs[0]?.id || [...viffData.sectors].sort((a, b) => loadRatio(b) - loadRatio(a))[0].id;
      }
      $(".viff-info").textContent = `${viffData.sectors.length} TV · ${plural(viffData.scenarios?.length || 0, "scenariusz", "scenariusze", "scenariuszy")} · stan ${viffData.now.slice(0, 2)}:${viffData.now.slice(2)}Z`;
    } catch (e) {
      viffData = null;
      $(".viff-info").innerHTML = `<span class="error">${esc(e.message)}</span>`;
    }
    drawViff();
  };
  $(".viff").addEventListener("change", loadViff);
  $(".viff-tv").addEventListener("change", (e) => selectTv(e.target.value));
  $(".vs-list").addEventListener("click", (e) => { const b = e.target.closest("[data-tv]"); if (b) selectTv(b.dataset.tv); });
  $(".vs-list").addEventListener("toggle", (e) => { if (e.target.matches?.(".vs-more")) store.set("map.viff.off", e.target.open); }, true);
  setInterval(() => document.body.contains(pane) && $(".viff").checked && loadViff(), 60000);

  // --- kontrolerzy online: plakietki lotnisk (D/G/T/A/APP) jak w VATSIM Radar; CTR rysuje drawFirs
  // Plakietki: lotniska w FIR EPWW ze wszystkimi stanowiskami, u sąsiadów tylko APP (koordynacja zbliżania).
  const badgeFacilities = (ap) => (ap.icao.startsWith("EP") ? ap.facilities : ap.facilities.APP ? { APP: ap.facilities.APP } : null);
  const loadAtc = async () => {
    layers.atc.clearLayers();
    try {
      atcData = await vatsimAtc();
    } catch (e) {
      atcData = { airports: [] }; atcAds = new Set();
      $(".atc-info").innerHTML = `<span class="error">${esc(e.message)}</span>`;
      drawAds();
      return;
    }
    const shown = $(".atc").checked ? atcData.airports.map((ap) => ({ ...ap, facilities: badgeFacilities(ap) })).filter((ap) => ap.facilities) : [];
    const known = new Set(ads.map((a) => a.icao));
    atcAds = new Set(shown.map((a) => a.icao));
    shown.forEach((ap) => {
      // lotniska spoza listy (zagraniczne) dostają sam symbol pod plakietką
      if (!known.has(ap.icao)) pointMarker({ ident: ap.icao, kind: "AD", lat: ap.lat, lon: ap.lon, name: ap.name }, { label: false, tooltip: false, scale: 1.6 }).addTo(layers.atc);
      const m = airportBadge(ap, panes).addTo(layers.atc);
      m.unbindTooltip();
      bindAdCard(m, ap.icao, ads.find((a) => a.icao === ap.icao)?.city || ap.name);
      if (ap.icao.startsWith("EP")) m.on("click", () => ctx.open("aerodrome", ap.icao));
    });
    $(".atc-info").textContent = $(".atc").checked ? `${plural(shown.length, "lotnisko", "lotniska", "lotnisk")} z kontrolerem · ${hhmm(new Date().toISOString())}` : "";
    drawAds();
  };
  $(".atc").addEventListener("change", loadAtc);
  setInterval(() => document.body.contains(pane) && loadAtc(), 30000);

  // --- trasa: gruba linia z obwódką (czytelna na każdym podkładzie), punkty jako symbole z nazwą w ramce
  const drawRoute = (layer, pts, color) => {
    const ll = pts.map((p) => [p.lat, p.lon]);
    L.polyline(ll, { color: theme.halo, weight: 9, opacity: 0.85, lineJoin: "round", interactive: false }).addTo(layer);
    const line = L.polyline(ll, { color, weight: 4, opacity: 1, lineJoin: "round" }).addTo(layer);
    pts.forEach((p, i) => {
      const first = i === 0 || i === pts.length - 1;
      pointMarker(p, { color, scale: first ? 2.2 : 1.9, weight: 2.4, cls: "rtlbl" }).addTo(layer);
    });
    return line;
  };
  let route = null;
  const redrawRoute = () => {
    layers.route.clearLayers();
    if (route) drawRoute(layers.route, route.points, theme.route);
  };

  // --- samoloty z VATSIM; kliknięcie otwiera szczegóły lotu (jak "Flight details" w NM UI) w prawym górnym rogu mapy:
  // VATSIM (pozycja, plan, trasa na mapie) + vIFF (czasy, slot, regulacja, CDM, wejścia w sektory, historia)
  let selected = null, flight = null;
  const redrawFlight = () => {
    layers.flight.clearLayers();
    if (!flight) return;
    if (flight.points.length) drawRoute(layers.flight, flight.points, theme.flight);
  };
  const fd = { cs: null, vat: undefined, viff: undefined, vatErr: null, viffErr: null };
  const fdOpen = store.get("map.fd.open", {});
  const fdCtl = L.control({ position: "topright" });
  fdCtl.onAdd = () => {
    const el = L.DomUtil.create("div", "fd-panel");
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
    el.addEventListener("click", (e) => {
      if (e.target.closest(".fd-close")) { closeFlight(); return; }
      const r = e.target.closest("tr[data-tv]");  // wejście w sektor → wykres tego TV
      if (!r) return;
      selectTv(r.dataset.tv);
      if (!$(".viff").checked) { $(".viff").checked = true; loadViff(); }
    });
    el.addEventListener("toggle", (e) => {
      if (!e.target.matches?.("details[data-x]")) return;
      fdOpen[e.target.dataset.x] = e.target.open;
      store.set("map.fd.open", fdOpen);
    }, true);
    return el;
  };
  fdCtl.addTo(map);
  const fdEl = fdCtl.getContainer();
  fdEl.style.display = "none";
  const chartH = () => (chartEl.style.display === "none" ? 0 : chartEl.offsetHeight);
  // na wąskiej mapie panel lotu (prawy górny róg) kończy się nad wykresem TV (lewy dolny róg), żeby się nie nakładały
  const fitFd = () => {
    const { x: w, y: hgt } = map.getSize(), ch = chartH();
    const clash = ch && w < chartEl.offsetWidth + 420 + 40;
    fdEl.style.maxHeight = Math.max(200, hgt - 20 - (clash ? ch + 34 : 0)) + "px";
  };
  map.on("resize", fitFd);
  const t4 = (v) => (v ? esc(v) : "–");
  const kv = (k, v, tip = "") => `<span class="k"${tip ? ` title="${esc(tip)}"` : ""}>${k}</span><span class="v">${v}</span>`;
  const alt = (a) => (a === null || a === undefined ? "–" : a >= 6000 ? fl(a) : `${a} ft`);
  const histTime = (t) => {
    const [d, hm] = (t || "").split(" ");
    return !hm ? esc(t) : d === new Date().toISOString().slice(0, 10) ? esc(hm) : `${esc(d.slice(8, 10))}.${esc(d.slice(5, 7))} ${esc(hm)}`;
  };
  const renderFd = () => {
    const { cs, vat: p, viff: v } = fd;
    if (!cs) { fdEl.style.display = "none"; fdEl.innerHTML = ""; return; }
    const keep = fdEl.dataset.cs === cs ? fdEl.querySelector(".fd-body")?.scrollTop || 0 : 0;
    fdEl.dataset.cs = cs;
    fdEl.style.display = "";
    fitFd();
    const adep = v?.departure || p?.departure, ades = v?.arrival || p?.arrival, type = v?.aircraft || p?.aircraft;
    const head = `<div class="fd-bar"><span>Szczegóły lotu</span><button class="fd-close" title="Zamknij">✕</button></div>
      <div class="fd-head"><div class="fd-l1"><b class="fd-cs">${esc(cs)}</b>${v ? stateChip(v, v.states) : ""}${v?.landed ? ` <span class="fs fs-fi">wylądował</span>` : ""}</div>
        <div class="fd-od"><b>${esc(adep || "????")}</b><span class="ar">→</span><b>${esc(ades || "????")}</b>${type ? `<span class="fd-tag">${esc(type)}</span>` : ""}${p?.rules ? `<span class="fd-tag">${p.rules === "V" ? "VFR" : "IFR"}</span>` : ""}</div>
        ${p ? `<div class="fd-who">${esc(p.name || "")} · CID ${esc(p.cid)}</div>` : v?.cid ? `<div class="fd-who">CID ${esc(v.cid)}</div>` : ""}</div>`;
    const vat = p === undefined ? `<div class="fd-note">Ładowanie danych VATSIM…</div>`
      : p ? `<div class="fd-grid g4">${kv("Poziom", alt(p.altitude))}${kv("GS", `${esc(p.groundspeed ?? "–")} kt`)}${kv("SQ", t4(p.squawk))}${kv("HDG", p.heading ?? "–")}
        ${kv("RFL", t4(p.rfl ? (p.rfl >= 6000 ? fl(p.rfl) : p.rfl) : ""), "z planu lotu VATSIM")}</div>`
      : `<div class="fd-note">${esc(fd.vatErr)}</div>`;
    let vf;
    if (v === undefined) vf = `<div class="fd-note">Ładowanie danych vIFF…</div>`;
    else if (!v) vf = `<div class="fd-note">${esc(fd.viffErr)}</div>`;
    else {
      const dtip = [v.delay !== null && v.delay !== undefined && `opóźnienie ATFM ${v.delay} min (CTOT − EOBT − kołowanie)`, v.ctot_reason && `powód: ${v.ctot_reason}`,
        v.revised_ctot && `ostatni zmieniony CTOT ${v.revised_ctot}`].filter(Boolean).join(" · ");
      const ctot = v.ctot ? `<span class="fd-ctot ${delayClass(v.delay)}">${esc(v.ctot)}${v.delay ? ` ${v.delay > 0 ? "+" : ""}${v.delay}` : ""}</span>` : "–";
      const eet = v.enroute_min !== null && v.enroute_min !== undefined ? `${Math.floor(v.enroute_min / 60)}:${String(v.enroute_min % 60).padStart(2, "0")}` : "–";
      vf = `<div class="fd-grid g4">
          ${kv("EOBT", t4(v.eobt))}${kv("TOBT", t4(v.tobt))}${kv("TSAT", t4(v.tsat))}${kv("CTOT", ctot, dtip || "bez slotu")}
          ${kv("AOBT", t4(v.aobt))}${kv("ATOT", t4(v.atot), "rzeczywisty start")}${kv("TTOT", t4(v.ttot), "planowany start (A-CDM)")}${kv("ETA", t4(v.eta))}
          ${kv("RFL", t4(v.rfl))}${kv("TAS", v.tas ? v.tas + " kt" : "–")}${kv("EET", eet, "czas lotu z planu")}${kv("Na czas", t4(v.on_time), "pole onTime z vIFF (odchyłka od planu)")}
        </div>
        <div class="fd-grid g2">
          ${kv("Regulacja", v.regulation ? `<b class="fd-reg">${esc(v.regulation)}</b>` : "brak")}${kv("Najbardziej karząca", t4(v.airspace), "most penalising airspace")}
          ${kv("Przestrzeń teraz", t4(v.actual_airspace))}${kv("Status CDM", esc([v.cdm_status, v.is_cdm && "A-CDM"].filter(Boolean).join(" · ") || "–"), "status CDM vIFF · A-CDM = lotnisko odlotu z A-CDM")}
          ${kv("Status ATFCM", t4(v.atfcm_status))}${kv("Pas / SID", t4(v.dep_info))}
        </div>`;
    }
    const route = v?.route || p?.route;
    const rt = `<div class="fd-sec">Trasa (pole 15)${!v?.route && p?.route ? " · plan VATSIM" : ""}</div>
      <div class="fd-route">${esc(route || "brak trasy")}</div>
      ${flight?.points?.length ? `<div class="fd-meta">na mapie: ${plural(flight.points.length, "punkt", "punkty", "punktów")} · ${flight.distance_nm} NM${p ? " (trasa z planu VATSIM)" : " (trasa z vIFF)"}</div>` : ""}
      ${flight?.warnings?.length ? `<div class="fd-warn">${flight.warnings.map(esc).join("<br>")}</div>` : ""}`;
    const secs = v?.sectors || [], hist = v?.history || [];
    const sec = !v ? "" : `<details class="fd-x" data-x="sectors" ${fdOpen.sectors ? "open" : ""}><summary>Wejścia w sektory (vIFF) <span>${secs.length}</span></summary>
      ${secs.length ? `<table class="fd-tbl"><thead><tr><th rowspan="2">TV</th><th rowspan="2">Opis</th><th colspan="2">Planowane</th><th colspan="2">Wyliczone</th></tr>
        <tr><th>wej.</th><th>wyj.</th><th>wej.</th><th>wyj.</th></tr></thead><tbody>
        ${secs.map((x) => `<tr data-tv="${esc(x.tv)}" class="${esc(x.state)}" title="${x.state === "now" ? "lot jest teraz w tym sektorze · " : ""}kliknij: wykres sektora">
          <td class="cs">${esc(x.tv)}</td><td class="d">${esc(x.label)}</td><td class="t">${t4(x.planned_entry)}</td><td class="t">${t4(x.planned_exit)}</td>
          <td class="t">${t4(x.entry)}</td><td class="t">${t4(x.exit)}</td></tr>`).join("")}</tbody></table>`
        : `<div class="fd-note">${v.sectors_error ? "vIFF: " + esc(v.sectors_error) : "Brak wejść w sektory EP w danych na dziś."}</div>`}</details>
      <details class="fd-x" data-x="history" ${fdOpen.history ? "open" : ""}><summary>Historia vIFF <span>${hist.length}</span></summary>
      ${hist.length ? `<ol class="fd-hist">${hist.map((x) => `<li><span class="t" title="${esc(x.time)}">${histTime(x.time)}</span><span>${esc(x.text)}</span></li>`).join("")}</ol>`
        : `<div class="fd-note">brak wpisów</div>`}</details>`;
    fdEl.innerHTML = `${head}<div class="fd-body"><div class="fd-sec">Pozycja (VATSIM)</div>${vat}<div class="fd-sec">Lot (vIFF)</div>${vf}${rt}${sec}</div>`;
    fdEl.querySelector(".fd-body").scrollTop = keep;
  };
  const fitFlight = (f) => {
    // z prawej miejsce na panel szczegółów lotu, z dołu na wykres TV
    const pad = { paddingTopLeft: [50, 50], paddingBottomRight: [50 + (fdEl.offsetWidth || 0), 50 + chartH()], maxZoom: 9 };
    if (f.points.length) map.fitBounds(L.latLngBounds(f.points.map((x) => [x.lat, x.lon])), pad);
    else if (f.lat !== null && f.lat !== undefined) map.setView([f.lat, f.lon], Math.max(map.getZoom(), 8));
  };
  const showFlight = async (cs) => {
    cs = String(cs).trim().toUpperCase();
    selected = cs;
    flight = null;
    layers.flight.clearLayers();
    Object.assign(fd, { cs, vat: undefined, viff: undefined, vatErr: null, viffErr: null });
    renderFd();
    drawTraffic();
    if (viffData) renderChart();  // podświetlenie lotu w tabeli wykresu
    const vatP = api(`/api/vatsim/pilots/${encodeURIComponent(cs)}/route`).then((f) => {
      if (selected !== cs) return;
      fd.vat = flight = f;
      redrawFlight();
      fitFlight(f);
      renderFd();
    }).catch((e) => {
      if (selected !== cs) return;
      fd.vat = null;
      fd.vatErr = /nie jest online/.test(e.message) ? "Nie ma go teraz w sieci VATSIM." : e.message;
      renderFd();
    });
    const viffP = (/^[A-Z0-9]{2,10}$/.test(cs) ? api(`/api/viff/flight/${encodeURIComponent(cs)}`) : Promise.reject(new Error("vIFF: znak wywoławczy spoza formatu ICAO")))
      .then((v) => { if (selected === cs) { fd.viff = v; renderFd(); } })
      .catch((e) => { if (selected === cs) { fd.viff = null; fd.viffErr = e.message; renderFd(); } });
    await Promise.all([vatP, viffP]);
    // pilota nie ma w sieci, ale vIFF zna trasę: rozpisujemy ją na punkty i rysujemy
    if (selected !== cs || fd.vat || !fd.viff?.route) return;
    try {
      const r = await api(`/api/nav/route?route=${encodeURIComponent([fd.viff.departure, fd.viff.route, fd.viff.arrival].filter(Boolean).join(" "))}`);
      if (selected !== cs || !r.points.length) return;
      flight = r;
      redrawFlight();
      fitFlight(r);
      renderFd();
    } catch { /* trasa nierozpoznana */ }
  };
  const refreshFd = () => {
    const cs = fd.cs;
    if (!cs || !fd.viff) return;
    api(`/api/viff/flight/${encodeURIComponent(cs)}`).then((v) => { if (fd.cs === cs) { fd.viff = v; renderFd(); } })
      .catch(() => { /* zostają poprzednie dane */ });
  };
  setInterval(() => document.body.contains(pane) && refreshFd(), 60000);
  const closeFlight = () => {
    selected = null; flight = null; fd.cs = null;
    layers.flight.clearLayers();
    renderFd();
    drawTraffic();
    if (viffData) renderChart();
  };
  const drawTraffic = () => {
    layers.traffic.clearLayers();
    if (!$(".traffic").checked) return;
    const z = map.getZoom(), b = map.getBounds().pad(0.2);
    pilots.filter((p) => b.contains([p.lat, p.lon])).forEach((p) => {
      const m = aircraftMarker(p, { label: z >= 6, detail: $(".traffic-detail").checked || z >= 9 })
        .bindTooltip(`${esc(p.callsign)} ${esc(p.aircraft || "")} ${esc(p.departure || "")}→${esc(p.arrival || "")} ${fl(p.altitude)}`)
        .on("click", () => showFlight(p.callsign)).addTo(layers.traffic);
      if (p.callsign === selected) m.getElement()?.classList.add("sel");
    });
  };
  const loadTraffic = async () => {
    if (!$(".traffic").checked) { layers.traffic.clearLayers(); $(".traffic-info").textContent = ""; return; }
    try {
      pilots = await api("/api/vatsim/pilots?bbox=44,5,60,35");
      $(".traffic-info").textContent = `${plural(pilots.length, "samolot", "samoloty", "samolotów")} w Europie Środkowej · ${hhmm(new Date().toISOString())}. Kliknij samolot: szczegóły lotu i trasa.`;
    } catch (e) { pilots = []; $(".traffic-info").innerHTML = `<span class="error">${esc(e.message)}</span>`; }
    pilotIdx = new Map(pilots.map((p) => [p.callsign, p]));
    const q = fd.vat && pilotIdx.get(fd.cs);  // otwarty panel lotu: świeża pozycja z VATSIM
    if (q) { ["lat", "lon", "altitude", "groundspeed", "heading", "squawk"].forEach((k) => { fd.vat[k] = q[k]; }); renderFd(); }
    drawTraffic();
    if (viffData) renderChart();  // ADEP/ADES/typ w tabeli lotów wykresu
  };
  $(".traffic").addEventListener("change", loadTraffic);
  $(".traffic-detail").addEventListener("change", drawTraffic);
  map.on("moveend", drawTraffic);
  setInterval(() => document.body.contains(pane) && $(".traffic").checked && loadTraffic(), 30000);

  // --- punkty i drogi w widocznym obszarze
  const bbox = () => { const b = map.getBounds(); return [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].map((x) => x.toFixed(3)).join(","); };
  let seq = 0;
  const loadVisible = async () => {
    const z = map.getZoom(), my = ++seq;
    const kinds = [];
    if ($(".navaids").checked && z >= 5) kinds.push("VOR", "VOR-DME", "DME", "VORTAC");
    if ($(".ndbs").checked && z >= 5) kinds.push("NDB", "NDB-DME");
    if ($(".vfrs").checked && z >= 8) kinds.push("VFR");
    if ($(".fixes").checked && z >= 8) kinds.push("FIX");
    let pts = [], segs = [];
    try { if (kinds.length) pts = await api(`/api/nav/points?bbox=${bbox()}&kinds=${kinds.join(",")}`); } catch { /* zbyt duży obszar */ }
    try { if ($(".airways").checked && z >= 7) segs = await api(`/api/nav/airways?bbox=${bbox()}`); } catch { /* zbyt duży obszar */ }
    if (my !== seq) return;
    layers.points.clearLayers();
    layers.airways.clearLayers();
    if ($(".airways").checked) layers.airways.addTo(map); else map.removeLayer(layers.airways);
    segs.forEach((s) => L.polyline(s.coords, { color: theme.airway, weight: 1 }).bindTooltip(esc(s.airway)).addTo(layers.airways));
    const labels = $(".labels").checked;
    pts.forEach((p) => {
      const nav = p.kind !== "FIX" && p.kind !== "VFR";
      const vor = symbolFor(p.kind) === "vor";
      pointMarker(p, { label: labels && (vor ? z >= 6 : nav ? z >= 7 : z >= 9), scale: nav ? 1.7 : 1.4 }).addTo(layers.points);
    });
  };
  map.on("moveend", loadVisible);
  map.on("zoomend", drawAds);
  ["navaids", "ndbs", "vfrs", "fixes", "airways", "labels"].forEach((c) => $("." + c).addEventListener("change", loadVisible));

  // --- trasa wpisana ręcznie
  $(".show-route").addEventListener("click", async () => {
    const info = $(".route-info");
    try {
      const r = await api(`/api/nav/route?route=${encodeURIComponent($(".route").value)}`);
      if (!r.points.length) { info.innerHTML = `<span class="error">Nie rozpoznano żadnego punktu.</span>`; return; }
      route = r;
      redrawRoute();
      map.fitBounds(L.latLngBounds(r.points.map((p) => [p.lat, p.lon])), { padding: [40, 40] });
      info.innerHTML = `${r.points.length} punktów · ${r.distance_nm} NM<br><span class="mono">${r.points.map((p) => esc(p.ident)).join(" ")}</span>` +
        (r.warnings.length ? `<div class="error">${r.warnings.map(esc).join("<br>")}</div>` : "");
    } catch (e) { info.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
  });
  $(".clear-route").addEventListener("click", () => { route = null; layers.route.clearLayers(); $(".route-info").textContent = ""; });

  setBase(baseName);
  loadTraffic();
  loadViff();
  return {
    el: pane,
    // po dłuższym pobycie w SEKTORYZACJI (odłączona mapa nie odświeża się w tle)
    refresh: () => { loadSectors(); loadTraffic(); loadAtc(); if ($(".viff").checked) loadViff(); },
    activate: (arg) => setTimeout(() => {
      map.invalidateSize();
      loadVisible();
      if (arg && arg !== selected) showFlight(decodeURIComponent(arg));
    }, 50),
  };
}

// MAP: podzakładki MAPA (mapa z ruchem) i SEKTORYZACJA (trzy mapy warstw LOW/MID/HIGH z dziedziczeniem sektorów).
// Oba widoki budowane raz i przepinane, więc przełączanie nie gubi stanu (wybrany lot, przybliżenie).
export default {
  mount(root, ctx) {
    let main = null, split = null, cur = "map", left = 0;
    const tabs = subtabs(root, [
      { id: "map", label: "MAPA", fill: true, render: (p) => {
        cur = "map";
        const again = !!main;
        main ||= mainMap(ctx);
        p.append(main.el);
        if (again) main.activate();  // powrót z SEKTORYZACJI: przeliczenie rozmiaru mapy
        if (again && Date.now() - left > 30000) main.refresh();
      } },
      { id: "sektoryzacja", label: "SEKTORYZACJA", fill: true, render: (p) => {
        cur = "sektoryzacja";
        left = Date.now();  // od tej chwili mapa główna jest odłączona
        split ||= sectorSplit(ctx);
        p.append(split.el);
        split.show();
        return { destroy: () => split.hide() };
      } },
    ]);
    return {
      activate: (arg) => {
        // #map/ZNAK otwiera lot na mapie głównej
        if (arg && cur !== "map") tabs.show("map");
        if (cur === "map") main.activate(arg);
        else split.show();
      },
    };
  },
};
