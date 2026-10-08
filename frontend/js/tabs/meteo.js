import { api, esc, h, splitTaf, subtabs, lsGet, lsSet, ONLINE_EVENT } from "../api.js";

// listy domyślne alfabetycznie (wyniki i tak są sortowane po ICAO)
const PL_CIV = "EPBY EPGD EPKK EPKT EPLB EPLL EPMO EPPO EPRA EPRZ EPSC EPSY EPWA EPWR EPZG";
const PL_MIL = "EPCE EPDA EPDE EPIR EPKS EPLK EPLY EPMB EPMI EPMM EPOK EPPR EPPW EPSN EPTM";
const INTL = "EDDB EDDF EDDM EKCH ESSA EVRA EYVI LKPR LOWW LZIB UKLL";

// Kolorowanie METAR/TAF tak jak w PANDORZE
export function colorize(raw) {
  if (!raw) return `<span class="nil">NIL</span>`;
  let rmk = false, station = false;
  return esc(raw).split(/\s+/).map((t) => {
    if (!station && /^[A-Z]{4}$/.test(t) && !["METAR", "TAF", "AUTO"].includes(t)) { station = true; return `<span class="st">${t}</span>`; }
    if (["METAR", "SPECI", "TAF", "AMD", "COR"].includes(t)) return `<span class="tm">${t}</span>`;
    if (t === "RMK") rmk = true;
    if (rmk) return `<span class="rmk">${t}</span>`;
    if (["NOSIG", "TEMPO", "BECMG", "PROB30", "PROB40"].includes(t) || /^(FM|TL|AT)\d{4}/.test(t)) return `<span class="trend">${t}</span>`;
    if (/^\d{6}Z$/.test(t) || /^\d{4}\/\d{4}$/.test(t)) return `<span class="tm">${t}</span>`;
    if (/^(\d{3}|VRB)\d{2,3}(G\d{2,3})?(KT|MPS)$/.test(t) || /^\d{3}V\d{3}$/.test(t)) return `<span class="wind">${t}</span>`;
    if (t === "CAVOK") return `<span class="cavok">${t}</span>`;
    if (/^(FEW|SCT|BKN|OVC|VV)/.test(t) || ["NSC", "NCD", "SKC"].includes(t)) return `<span class="cld">${t}</span>`;
    if (/^[QA]\d{4}$/.test(t)) return `<span class="q">${t}</span>`;
    if (t === "NIL") return `<span class="nil">${t}</span>`;
    if (/^(\+|-|VC)?[A-Z]{2,8}$/.test(t) && !["METAR", "TAF", "AUTO", "COR", "AMD", "SPECI"].includes(t)) return `<span class="wxph">${t}</span>`;
    return t;
  }).join(" ");
}

// TAF: każdy okres zmian w nowej linii, wcięty pod pierwszą linią
export function wxLines(kind, raw) {
  const lines = kind === "taf" ? splitTaf(raw) : [raw];
  return lines.map((l, i) => (i ? `<span class="cont">${colorize(l)}</span>` : colorize(l))).join("<br>");
}

// lista stacji w polu: wielkie litery, bez powtórzeń, alfabetycznie (także lista zapamiętana w starszej wersji)
const normIds = (s) => [...new Set(String(s || "").toUpperCase().split(/[\s,;]+/).filter(Boolean))].sort().join(" ");

function wxList(kind, defaults, key) {
  return (pane) => {
    pane.append(h(`<div>
      <div class="toolbar">
        <input type="text" class="ids" size="80" value="${esc(normIds(lsGet(key) || defaults))}">
        <button class="btn primary go">Pokaż</button>
        <label class="sc"><input type="checkbox" class="auto" checked> odświeżaj co 2 min</label>
        <span class="hint upd"></span>
      </div>
      <div class="wx"></div>
    </div>`));
    const $ = (s) => pane.querySelector(s);
    const load = async () => {
      const ids = normIds($(".ids").value);
      $(".ids").value = ids;
      lsSet(key, ids);
      try {
        // METAR i TAF alfabetycznie po ICAO (odpowiedź też sortujemy, gdyby backend zmienił kolejność)
        const rows = (await api(`/api/meteo/${kind}?ids=${encodeURIComponent(ids.split(" ").join(","))}`)).sort((a, b) => a.icao.localeCompare(b.icao));
        $(".wx").innerHTML = rows.map((r) => `<div class="row">${r.raw ? wxLines(kind, r.raw) : `<span class="st">${esc(r.icao)}</span> <span class="nil">NIL</span>`}</div>`).join("");
        $(".upd").textContent = "Aktualizacja " + new Date().toISOString().slice(11, 16) + "Z";
      } catch (e) { $(".wx").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    };
    $(".go").addEventListener("click", load);
    $(".ids").addEventListener("keydown", (e) => e.key === "Enter" && load());
    const timer = setInterval(() => $(".auto")?.checked && load(), 120000);
    // serwer wrócił (okno run.bat uruchomione ponownie): komunikat błędu od razu zastępują dane
    const online = () => $(".wx .error") && load();
    window.addEventListener(ONLINE_EVENT, online);
    load();
    return { destroy: () => { clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); } };
  };
}

// Mapa QNH regionalnego jak w vAWOS ("MAPA QNH REGIONALNEGO"): jasny podkład jak mapa AIP (bez kafelków), granica
// FIR EPWW, siatka co 1°, rejony 1–14 (zielone granice i numery), TMA/MTMA (liliowe), lotniska (romby, kody ICAO),
// etykiety "SEKTOR n" + QNH rejonu i "TMA ..." + QNH lotniska. Obok tabela rejonów (hPa, mmHg, inHg) i tabela TMA.
const QR_LAYERS = [["tma", "TMA/MTMA"], ["ad", "lotniska"], ["cap", "opisy BELOW"]];

function qnhMap(pane) {
  const wrap = h(`<div class="qrwrap"><div class="qrmapbox"><div class="map qrmap"></div><div class="qr-grat"></div></div>
    <div class="qrside">
      <div class="qr-head"><b>QNH regionalne</b><span class="qr-stamp"></span></div>
      <div class="qr-tools">${QR_LAYERS.map(([k, l]) => `<label><input type="checkbox" data-k="${k}" checked> ${l}</label>`).join("")}</div>
      <div class="qr-err"></div>
      <div class="qr-card"><h4>Rejony QNH <span>najniższe QNH z lotnisk rejonu</span></h4><table class="data qr-reg"></table></div>
      <div class="qr-card"><h4>TMA / MTMA <span>pod TMA QNH lotniska</span></h4><table class="data qr-tma"></table></div>
      <p class="qr-note"></p>
    </div></div>`);
  pane.append(wrap);
  const $ = (s) => wrap.querySelector(s);
  const map = L.map($(".qrmap"), { zoomSnap: 0.1, zoomDelta: 0.5, wheelPxPerZoomLevel: 120, attributionControl: false });
  // kolejność warstw jak na mapie AIP: siatka, TMA, granice rejonów, FIR, numery, lotniska, opisy, etykiety
  [["qgrid", 330], ["qtma", 340], ["qreg", 350], ["qfir", 360], ["qnum", 560], ["qad", 600], ["qcap", 620], ["qlbl", 640]]
    .forEach(([n, z]) => { map.createPane(n).style.zIndex = z; });
  const grid = L.layerGroup().addTo(map);   // siatka nie zależy od danych, draw() jej nie czyści
  const layers = { base: L.layerGroup().addTo(map), tma: L.layerGroup().addTo(map), ad: L.layerGroup().addTo(map),
    cap: L.layerGroup().addTo(map), lbl: L.layerGroup().addTo(map), hl: L.layerGroup().addTo(map) };
  const mmhg = (q) => Math.round(q * 0.750062);
  const inhg = (q) => (q * 0.0295300).toFixed(2);
  const q4 = (q) => (q ? String(q) : "----");
  // ikona: div wyśrodkowany w punkcie i przesunięty o (dx, dy) px; przy mniejszym zoomie przesunięcie i etykieta
  // maleją razem z mapą (--qs, --qb w CSS), żeby układ dobrany dla zoomu domyślnego nie nachodził na siebie
  const div = (cls, html, [dx, dy] = [0, 0], attr = "") => L.divIcon({ className: "qr-icon", iconSize: null,
    html: `<div class="qr-pos ${cls}"${attr} style="--dx:${dx}px;--dy:${dy}px">${html}</div>` });
  const mark = (lat, lon, icon, pane, layer) => L.marker([lat, lon], { icon, pane, interactive: false, keyboard: false }).addTo(layer);

  // siatka co 1° (w Mercatorze proste), opisy stopni przy górnej i prawej krawędzi mapy
  for (let lon = 12; lon <= 26; lon++) L.polyline([[47, lon], [57, lon]], { pane: "qgrid", className: "qr-gl", interactive: false }).addTo(grid);
  for (let lat = 47; lat <= 57; lat++) L.polyline([[lat, 11], [lat, 27]], { pane: "qgrid", className: "qr-gl", interactive: false }).addTo(grid);
  const grat = () => {
    if (!map._loaded) return;
    const c = map.getCenter(), sz = map.getSize();
    let out = "";
    for (let lon = 12; lon <= 26; lon++) {
      const x = map.latLngToContainerPoint([c.lat, lon]).x;
      if (x > 30 && x < sz.x - 20) out += `<span style="left:${Math.round(x)}px;top:2px">${lon}°</span>`;
    }
    for (let lat = 47; lat <= 57; lat++) {
      const y = map.latLngToContainerPoint([lat, c.lng]).y;
      if (y > 16 && y < sz.y - 10) out += `<span class="lat" style="top:${Math.round(y)}px;right:2px">${lat}°</span>`;
    }
    $(".qr-grat").innerHTML = out;
  };
  map.on("move zoom resize", grat);
  // zoom domyślny przy 1500x900 to ok. 6.9 (dla niego dobrane przesunięcia z JSON-a); poniżej 6.3 bez kodów lotnisk i opisów
  map.on("zoomend", () => {
    const z = map.getZoom(), s = Math.min(1, 2 ** (z - 6.9));
    wrap.style.setProperty("--qs", Math.max(0.6, s).toFixed(3));
    wrap.style.setProperty("--qb", Math.max(0.86, s).toFixed(3));
    wrap.classList.toggle("qr-far", z < 6.3);
  });

  const show = () => wrap.querySelectorAll(".qr-tools input").forEach((i) => {
    const l = layers[i.dataset.k];
    if (i.checked && !map.hasLayer(l)) l.addTo(map);
    if (!i.checked && map.hasLayer(l)) map.removeLayer(l);
  });
  wrap.querySelector(".qr-tools").addEventListener("change", show);

  let data = null;
  const draw = () => {
    Object.values(layers).forEach((l) => l.clearLayers());
    // TMA: obrys zewnętrzny = ciemna krawędź pod nieprzezroczystym wypełnieniem, na wierzchu cienkie linie podziału warstw
    // (każda warstwa TMA osobno, bo w jednym MultiPolygonie nakładające się warstwy wycinałyby dziury)
    const polys = data.tmas.filter((t) => t.area).flatMap((t) => t.area.coordinates.map((c) => ({ type: "Polygon", coordinates: c })));
    [["qr-tedge", { fill: false }], ["qr-tfill", { stroke: false, fillOpacity: 1 }], ["qr-tin", { fill: false }]].forEach(([className, o]) =>
      L.geoJSON(polys, { pane: "qtma", interactive: false, style: { className, ...o } }).addTo(layers.tma));
    data.tmas.filter((t) => t.outline).forEach((t) => L.geoJSON(t.outline, { pane: "qtma", interactive: false, style: { className: "qr-tline" } }).addTo(layers.tma));
    if (data.coast) L.geoJSON(data.coast, { pane: "qgrid", interactive: false, style: { className: "qr-coast" } }).addTo(layers.base);
    data.regions.filter((r) => !r.band).forEach((r) => L.geoJSON(r.geometry, { pane: "qreg", interactive: false, style: { className: "qr-rline", fill: false } }).addTo(layers.base));
    if (data.fir) L.geoJSON(data.fir, { pane: "qfir", interactive: false, style: { className: "qr-fir", fill: false } }).addTo(layers.base);

    // numery rejonów (15–17 pomarańczowe jak w vAWOS) i etykiety SEKTOR n
    data.regions.forEach((r) => {
      mark(r.num[1], r.num[0], div("qr-num" + (r.band ? " band" : ""), r.id), "qnum", layers.base);
      if (r.label) mark(r.label[1], r.label[0], div("qr-lbl sek" + (r.qnh ? "" : " nil"), `<small>SEKTOR ${r.id}</small><b>${q4(r.qnh)}</b>`,
        undefined, ` data-r="${r.id}"`), "qlbl", layers.lbl);
    });
    // lotniska: kółko z kropką = lotnisko z METAR-em/TMA, romb = pozostałe
    const qnhOf = {};
    data.regions.forEach((r) => r.stations.forEach((s) => { qnhOf[s.icao] = s.qnh; }));
    data.tmas.forEach((t) => { qnhOf[t.icao] = t.qnh; });
    // lądowiska w miejscu lotniska z METAR-em (np. EPSW = EPLB, EPIN obok EPIR) pomijamy, żeby kody się nie nakładały
    const main = data.aerodromes.filter((a) => a.metar);
    const dup = (a) => !a.metar && main.some((m) => Math.abs(m.lat - a.lat) < 0.04 && Math.abs(m.lon - a.lon) < 0.06);
    data.aerodromes.filter((a) => !dup(a)).forEach((a) => {
      L.marker([a.lat, a.lon], { pane: "qad", keyboard: false, icon: L.divIcon({ className: "qr-icon", iconSize: null,
        html: `<div class="qr-ad${a.metar ? " ctl" : ""}"><i></i><span>${a.icao}</span></div>` }) })
        .bindTooltip(`${a.icao}${qnhOf[a.icao] ? " Q" + qnhOf[a.icao] : ""}`, { direction: "top", offset: [0, -6], className: "qr-tip" })
        .addTo(layers.ad);
    });
    // TMA/MTMA: etykieta (nazwa + QNH lotniska) i opis "BELOW TMA QNH FROM EPxx"; przesunięcia w px z pliku JSON
    data.tmas.filter((t) => t.lat != null).forEach((t) => {
      if (t.box !== false) mark(t.lat, t.lon, div("qr-lbl tma" + (t.qnh ? "" : " nil"), `<small>${esc(t.short || t.name)}</small><b>${q4(t.qnh)}</b>`,
        t.off || [0, -24], ` data-t="${t.icao}"`), "qlbl", layers.lbl);
      if (t.cap) mark(t.lat, t.lon, div("qr-cap", `BELOW ${esc(t.below)}<br>QNH FROM ${t.icao}`, t.cap), "qcap", layers.cap);
    });
    show();
  };

  // podświetlenie rejonu / TMA po najechaniu na wiersz tabeli
  let hot = null;
  const highlight = (tr) => {
    if (tr === hot) return;
    hot = tr;
    layers.hl.clearLayers();
    wrap.querySelectorAll(".qr-lbl.on").forEach((e) => e.classList.remove("on"));
    if (!tr || !data) return;
    const r = tr.dataset.r && data.regions.find((x) => String(x.id) === tr.dataset.r);
    const t = tr.dataset.t && data.tmas.find((x) => x.icao === tr.dataset.t);
    const g = r ? r.geometry : t && (t.area || t.outline);
    if (g) L.geoJSON(g, { pane: "qfir", interactive: false, style: { className: "qr-hl" } }).addTo(layers.hl);
    wrap.querySelector(r ? `.qr-lbl[data-r="${r.id}"]` : `.qr-lbl[data-t="${tr.dataset.t}"]`)?.classList.add("on");
  };
  const side = $(".qrside");
  side.addEventListener("mouseover", (e) => highlight(e.target.closest("tr[data-r], tr[data-t]")));
  side.addEventListener("mouseleave", () => highlight(null));

  const table = () => {
    const st = (s, low) => `<span class="${s.qnh === null ? "nil" : s.qnh === low ? "low" : ""}">${s.icao}&nbsp;${s.qnh ?? "–"}</span>`;
    hot = null;
    $(".qr-reg").innerHTML = `<thead><tr><th>Sek.</th><th>QNH</th><th>mmHg</th><th>inHg</th><th>Lotniska</th></tr></thead><tbody>${data.regions.map((r) =>
      `<tr data-r="${r.id}"${r.band ? ` class="band" title="Rejon ${r.id}: pas przy granicy wschodniej (wg PANDORY), na mapie vAWOS tylko numer"` : ""}><td class="num">${r.id}</td>
      <td class="num q">${q4(r.qnh)}</td><td class="num">${r.qnh ? mmhg(r.qnh) : ""}</td><td class="num">${r.qnh ? inhg(r.qnh) : ""}</td>
      <td class="sta">${r.stations.map((s) => st(s, r.qnh)).join(" ")}</td></tr>`).join("")}</tbody>`;
    $(".qr-tma").innerHTML = `<thead><tr><th>TMA / MTMA</th><th>Lotn.</th><th>QNH</th><th>mmHg</th></tr></thead><tbody>${data.tmas.map((t) =>
      `<tr data-t="${t.icao}"><td>${esc(t.name)}</td><td class="mono">${t.icao}</td><td class="num q">${q4(t.qnh)}</td>
      <td class="num">${t.qnh ? mmhg(t.qnh) : ""}</td></tr>`).join("")}</tbody>`;
  };

  // widok od razu (także gdy API nie odpowiada), po pierwszym wczytaniu dopasowany do granicy FIR
  map.fitBounds(L.latLngBounds([49, 14.1], [55.3, 24.2]), { padding: [4, 4] });
  let fitted = false, dead = false;
  const load = async () => {
    let d;
    try { d = await api("/api/meteo/qnh-regions"); } catch (e) { if (!dead) $(".qr-err").textContent = e.message; return; }
    if (dead) return;   // zakładka zamknięta w trakcie pobierania
    data = d;
    draw();
    if (!fitted && data.fir) map.fitBounds(L.geoJSON(data.fir).getBounds(), { padding: [4, 4], animate: false });
    fitted = true;
    grat();
    $(".qr-stamp").textContent = "Aktualizacja " + new Date().toISOString().slice(11, 16) + "Z";
    $(".qr-err").textContent = data.error || "";
    table();
    $(".qr-note").textContent = data.note || "";
  };
  load();
  const timer = setInterval(load, 300000);
  const online = () => $(".qr-err").textContent && load();   // serwer wrócił, a na mapie jest komunikat błędu
  window.addEventListener(ONLINE_EVENT, online);
  const ro = new ResizeObserver(() => { map.invalidateSize(); grat(); });
  ro.observe($(".qrmap"));
  return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); ro.disconnect(); map.remove(); } };
}

const windy = (overlay) => (pane) => {
  const url = `https://embed.windy.com/embed2.html?lat=52.0&lon=19.3&detailLat=52.17&detailLon=20.97&zoom=${overlay === "satellite" ? 4 : 6}&level=surface&overlay=${overlay}&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=kt&metricTemp=%C2%B0C&radarRange=-1`;
  pane.append(h(`<iframe class="embed" src="${url}" allowfullscreen></iframe>`));
};

// --- WIND: Windy przy ziemi (0 ft) albo na 900 hPa (≈3000 ft AMSL) z punktem prognozy w punkcie podejścia wybranego
// pasa; obok wiatr z Open-Meteo w punktach podejścia wszystkich pasów lotniska (backend: services/upperwind.py)
const MAIN_AD = PL_CIV.split(" ");

function windyUrl(o) {
  const q = new URLSearchParams({ lat: o.lat.toFixed(3), lon: o.lon.toFixed(3), detailLat: o.dlat.toFixed(4), detailLon: o.dlon.toFixed(4),
    zoom: o.zoom, level: o.level, overlay: "wind", product: "ecmwf", menu: "", message: "true", marker: "true", calendar: "now",
    pressure: "true", type: "map", location: "coordinates", detail: "true", metricWind: "kt", metricTemp: "°C", radarRange: "-1" });
  return `https://embed.windy.com/embed2.html?${q}`;
}

// wiatr "310/14G26", składowe "H13" / "T13" (w plecy) i "5R" / "5L"; używane też w AERODROME
const p2 = (v, n) => String(v).padStart(n, "0");
export const windVec = (w) => (!w || w.speed === null || w.speed === undefined ? "–"
  : `${w.variable ? "VRB" : p2(w.dir, 3)}/${p2(w.speed, 2)}${w.gust ? "G" + w.gust : ""}`);
// składowe zawsze zaokrąglane po wartości bezwzględnej (-13.5 -> T14, 13.5 -> H14), wszędzie tak samo
export const kt = (v) => Math.round(Math.abs(v));
export const hwTxt = (v) => (v === null || v === undefined ? "–" : v < 0 && kt(v) ? `<span class="tw">T${kt(v)}</span>` : `H${kt(v)}`);
export const xwTxt = (v) => (v === null || v === undefined ? "–" : kt(v) === 0 ? "0" : `${kt(v)}${v > 0 ? "R" : "L"}`);
// "2026-10-06T18:00Z" -> "18:00Z 06.10"
export const validTxt = (t) => (t ? `${t.slice(11, 16)}Z ${t.slice(8, 10)}.${t.slice(5, 7)}` : "–");
// odległość od progu zawsze z jedną cyfrą po przecinku ("3.0 NM", nie "3 NM" obok "4.9 NM")
const nm = (v) => (v === null || v === undefined ? "–" : Number(v).toFixed(1));
export const pointTip = (r) => `RWY ${r.designator}: ${r.fix ? r.fix + ", " : ""}${r.method_label}, ${nm(r.dist_nm)} NM od progu`
  + `, ścieżka 3° ≈ ${r.path_ft} ft${r.approaches?.length ? `\nPodejścia: ${r.approaches.join(", ")}` : ""}`
  + `${r.rejected?.length ? `\nOdrzucone punkty procedur: ${r.rejected.join("; ")}` : ""}`;

function windTab(pane) {
  const wrap = h(`<div class="wnd">
    <div class="wnd-bar">
      <span class="wnd-seg wnd-mode"><button data-m="0">0 ft</button><button data-m="3000">3000 ft (podejście)</button></span>
      <label class="wnd-adl">Lotnisko <select class="wnd-ad"></select></label>
      <span class="wnd-rwyl">Pas <span class="wnd-seg wnd-rwys"></span></span>
      <span class="wnd-hint"></span>
    </div>
    <div class="wnd-body"><iframe class="embed wnd-frame" allowfullscreen></iframe><aside class="wnd-side"></aside></div>
  </div>`);
  pane.append(wrap);
  const $ = (s) => wrap.querySelector(s);
  let mode = lsGet("meteo.wind.mode") === "3000" ? "3000" : "0";
  let icao = (lsGet("meteo.wind.ad") || "EPWA").toUpperCase();
  let ads = [], ad = null, rwy = null, inUse = null, aw = null, awErr = "", ptsErr = "", src = "", seq = 0, dead = false;
  const rwyKey = () => `meteo.wind.rwy.${icao}`;
  const sel = () => ad?.runways.find((r) => r.designator === rwy) || null;
  const roles = (d) => ["arr", "dep"].filter((k) => inUse?.[k] === d);
  const tags = (d) => roles(d).map((k) => `<span class="wnd-tag ${k}">${k.toUpperCase()}${inUse?.source === "ATIS" ? "" : "?"}</span>`).join("");

  const frame = () => {
    const r = sel(), up = mode === "3000";
    const o = up && r ? { lat: r.lat, lon: r.lon, dlat: r.lat, dlon: r.lon, zoom: 8, level: "900h" }
      : { lat: 52.0, lon: 19.3, dlat: ad ? ad.lat : 52.166, dlon: ad ? ad.lon : 20.967, zoom: 6, level: up ? "900h" : "surface" };
    const url = windyUrl(o);
    if (url !== src) $(".wnd-frame").src = src = url;
    const hint = $(".wnd-hint");
    hint.textContent = up
      ? `Windy 900 hPa ≈ 3000 ft AMSL · punkt prognozy ${r ? `RWY ${r.designator} ${r.fix || "oś 3°"}` : "– brak danych pasa"}`
      : `Windy 10 m (przy ziemi) · punkt prognozy ${ad ? ad.icao : icao}`;
    hint.title = `${hint.textContent}${up && r ? ` (${r.method_label}, ${nm(r.dist_nm)} NM od progu)` : ""} · model Windy: ECMWF`;
  };

  const bar = () => {
    wrap.querySelectorAll(".wnd-mode button").forEach((b) => b.classList.toggle("active", b.dataset.m === mode));
    $(".wnd-rwyl").hidden = mode !== "3000" || !ad;
    $(".wnd-rwys").innerHTML = (ad?.runways || []).map((r) => `<button data-rwy="${esc(r.designator)}" class="${r.designator === rwy ? "active" : ""} ${roles(r.designator).join(" ")}"
      title="${esc(pointTip(r))}">${esc(r.designator)}</button>`).join("");
  };

  const side = () => {
    const el = $(".wnd-side");
    const head = `<h3>${esc(ad?.icao || icao)} · ${mode === "3000" ? "wiatr na podejściu 3000 ft" : "wiatr przy ziemi"}</h3>`;
    if (!aw) {
      el.innerHTML = `<div class="card wnd-card">${head}<p class="${awErr || ptsErr ? "error" : "hint"}">${esc(awErr || ptsErr || "Ładowanie…")}</p></div>`;
      return;
    }
    const thead = mode === "3000" ? `<tr><th>Pas</th><th>Punkt podejścia</th><th>Wiatr</th><th>H/T</th><th>XW</th></tr>`
      : `<tr><th rowspan="2">Pas</th><th colspan="2">METAR</th><th colspan="2">Model 10 m</th></tr><tr><th>H/T</th><th>XW</th><th>H/T</th><th>XW</th></tr>`;
    const rows = aw.runways.map((r) => {
      const cls = [r.designator === rwy ? "sel" : "", ...roles(r.designator)].join(" ");
      const cells = mode === "3000"
        ? `<td class="pt"><b>${esc(r.fix || "oś 3°")} <span>${nm(r.dist_nm)} NM</span></b><small>${esc(r.method_label)}</small></td>
          <td class="num w">${windVec(r.w3000)}</td><td class="num">${hwTxt(r.c3000.hw)}</td><td class="num">${xwTxt(r.c3000.xw)}</td>`
        : `<td class="num">${hwTxt(r.c_metar.hw)}</td><td class="num">${xwTxt(r.c_metar.xw)}</td>
          <td class="num">${hwTxt(r.c_model.hw)}</td><td class="num">${xwTxt(r.c_model.xw)}</td>`;
      return `<tr data-rwy="${esc(r.designator)}" class="${cls}" title="${esc(pointTip(r))}"><td class="rwy"><b>${esc(r.designator)}</b><span class="wnd-tags">${tags(r.designator)}</span></td>${cells}</tr>`;
    }).join("");
    el.innerHTML = `<div class="card wnd-card">${head}
      <div class="wnd-sfc"><span><i>0 ft METAR</i><b>${windVec(aw.metar_wind)}</b></span><span><i>0 ft model 10 m</i><b>${windVec(aw.model_surface)}</b></span></div>
      <table class="data wnd-tab"><thead>${thead}</thead><tbody>${rows}</tbody></table>
      ${[aw.model_error, aw.metar_error].filter(Boolean).map((e) => `<p class="error">${esc(e)}</p>`).join("")}
      <p class="wnd-note">Źródło: <a href="${esc(aw.source_url)}" target="_blank" rel="noopener">${esc(aw.source)}</a> (model ${esc(aw.model)}),
        ${aw.valid ? `prognoza na ${validTxt(aw.valid)}, pobrano ${esc(aw.fetched)}` : "prognoza niedostępna"}. Wiatr 3000 ft AMSL interpolowany z poziomów 1000–850 hPa.</p>
      ${mode === "3000" ? `<p class="wnd-note">Punkt podejścia: FAF/IF, na którym kończą się STAR z przejściem do podejścia (plik .ese), jeśli leży 2.5–15 NM od progu
        i do 15° od osi; inaczej punkt na przedłużeniu osi, w którym ścieżka 3° osiąga 3000 ft. Kliknij pas, żeby przenieść tam punkt prognozy Windy.</p>`
        : `<p class="wnd-note">Wiatr 0 ft: METAR oraz model 10 m nad punktem lotniska; składowe względem kursu każdego pasa.</p>`}
      <p class="wnd-note">H = czołowy, T = w plecy, L/R = boczny z lewej/prawej, kt. ${inUse ? `ARR/DEP: pas w użyciu (${inUse.source === "ATIS" ? "ATIS" : "? = sugestia systemu"}).` : ""}
        Windy pokazuje model ECMWF, Open-Meteo zwykle ICON, więc wartości mogą się różnić.</p>
    </div>`;
  };

  const loadWind = async () => {
    const my = seq;
    try {
      const d = await api(`/api/meteo/approach-wind/${icao}`);
      if (dead || my !== seq) return;
      aw = d;
      awErr = "";
    } catch (e) {
      if (dead || my !== seq) return;
      awErr = e.message;
    }
    side();
  };

  const pick = async (code) => {
    icao = code;
    lsSet("meteo.wind.ad", icao);
    ad = ads.find((a) => a.icao === icao) || null;
    rwy = lsGet(rwyKey());
    if (!ad?.runways.some((r) => r.designator === rwy)) rwy = null;
    inUse = aw = null;
    awErr = "";
    const my = ++seq;
    if (mode === "0" || rwy) frame();   // punkt prognozy już znany; w 3000 ft bez wybranego pasa czekamy na pas w użyciu
    bar();
    side();
    loadWind();
    // pas do lądowania w użyciu (ATIS albo sugestia systemu) jako domyślny, jeśli odpowiedź przyjdzie szybko
    const st = api(`/api/aerodromes/${icao}/status`).then((x) => x.runway_in_use || null).catch(() => null);
    const first = await Promise.race([st, new Promise((res) => setTimeout(() => res(null), 1500))]);
    if (dead || my !== seq) return;
    inUse = first;
    if (!rwy) rwy = (ad?.runways.some((r) => r.designator === inUse?.arr) ? inUse.arr : ad?.runways[0]?.designator) || null;
    bar();
    frame();
    side();
    st.then((u) => { if (!dead && my === seq && u && !inUse) { inUse = u; bar(); side(); } });
  };

  wrap.querySelector(".wnd-mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-m]");
    if (!b || b.dataset.m === mode) return;
    mode = b.dataset.m;
    lsSet("meteo.wind.mode", mode);
    bar();
    frame();
    side();
  });
  const choose = (e) => {
    const t = e.target.closest("[data-rwy]");
    if (!t || !ad) return;
    rwy = t.dataset.rwy;
    lsSet(rwyKey(), rwy);
    bar();
    frame();
    side();
  };
  $(".wnd-rwys").addEventListener("click", choose);
  $(".wnd-side").addEventListener("click", choose);
  $(".wnd-ad").addEventListener("change", (e) => pick(e.target.value));

  bar();
  side();
  const init = async () => {
    try {
      ads = (await api("/api/meteo/approach-points")).aerodromes;
      ptsErr = "";
    } catch (e) { ptsErr = `Punkty podejścia: ${e.message}`; }
    if (dead) return;
    if (ads.length && !ads.some((a) => a.icao === icao)) icao = ads.some((a) => a.icao === "EPWA") ? "EPWA" : ads[0].icao;
    const opt = (a) => `<option value="${a.icao}"${a.icao === icao ? " selected" : ""}>${a.icao} ${esc(a.name)}</option>`;
    const main = ads.filter((a) => MAIN_AD.includes(a.icao)), rest = ads.filter((a) => !MAIN_AD.includes(a.icao));
    $(".wnd-ad").innerHTML = ads.length ? `<optgroup label="Lotniska główne">${main.map(opt).join("")}</optgroup><optgroup label="Pozostałe">${rest.map(opt).join("")}</optgroup>`
      : `<option>${esc(icao)}</option>`;
    pick(icao);
  };
  init();
  const timer = setInterval(() => { if (!document.hidden) loadWind(); }, 600000);
  // serwer wrócił po przerwie: brakujące punkty podejścia albo wiatr pobieramy od razu, nie po 10 min
  const online = () => (!ads.length ? init() : awErr && loadWind());
  window.addEventListener(ONLINE_EVENT, online);
  return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); } };
}

export default {
  mount(root) {
    subtabs(root, [
      { id: "metar-pl", label: "METAR PL", render: wxList("metar", PL_CIV, "meteo.metar.pl") },
      { id: "metar-mil", label: "METAR MIL", render: wxList("metar", PL_MIL, "meteo.metar.mil") },
      { id: "metar-intl", label: "METAR INTL", render: wxList("metar", INTL, "meteo.metar.intl") },
      { id: "taf-pl", label: "TAF PL", render: wxList("taf", PL_CIV, "meteo.taf.pl") },
      { id: "taf-intl", label: "TAF INTL", render: wxList("taf", INTL, "meteo.taf.intl") },
      { sep: true },
      { id: "qnh", label: "QNH", fill: true, render: qnhMap },
      { id: "wind", label: "WIND", fill: true, render: windTab },
      { id: "radar", label: "RADAR", fill: true, render: windy("radar") },
      { id: "sat", label: "SAT EUR", fill: true, render: windy("satellite") },
    ]);
  },
};
