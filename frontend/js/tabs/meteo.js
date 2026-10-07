import { api, esc, h, splitTaf, subtabs, lsGet, lsSet } from "../api.js";

const PL_CIV = "EPWA EPMO EPKK EPKT EPGD EPPO EPWR EPLL EPRZ EPLB EPSC EPBY EPSY EPZG EPRA";
const PL_MIL = "EPCE EPDA EPDE EPIR EPKS EPLK EPLY EPMB EPMI EPMM EPOK EPPR EPPW EPSN EPTM";
const INTL = "EDDB EDDF EDDM EKCH ESSA LKPR LZIB LOWW EVRA EYVI UKLL";

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

function wxList(kind, defaults, key) {
  return (pane) => {
    pane.append(h(`<div>
      <div class="toolbar">
        <input type="text" class="ids" size="80" value="${esc(lsGet(key) || defaults)}">
        <button class="btn primary go">Pokaż</button>
        <label class="sc"><input type="checkbox" class="auto" checked> odświeżaj co 2 min</label>
        <span class="hint upd"></span>
      </div>
      <div class="wx"></div>
    </div>`));
    const $ = (s) => pane.querySelector(s);
    const load = async () => {
      const ids = $(".ids").value.trim().split(/[\s,]+/).filter(Boolean).join(",");
      lsSet(key, $(".ids").value.trim());
      try {
        const rows = await api(`/api/meteo/${kind}?ids=${ids}`);
        $(".wx").innerHTML = rows.map((r) => `<div class="row">${r.raw ? wxLines(kind, r.raw) : `<span class="st">${esc(r.icao)}</span> <span class="nil">NIL</span>`}</div>`).join("");
        $(".upd").textContent = "Aktualizacja " + new Date().toISOString().slice(11, 16) + "Z";
      } catch (e) { $(".wx").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    };
    $(".go").addEventListener("click", load);
    $(".ids").addEventListener("keydown", (e) => e.key === "Enter" && load());
    const timer = setInterval(() => $(".auto")?.checked && load(), 120000);
    load();
    return { destroy: () => clearInterval(timer) };
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
  const ro = new ResizeObserver(() => { map.invalidateSize(); grat(); });
  ro.observe($(".qrmap"));
  return { destroy: () => { dead = true; clearInterval(timer); ro.disconnect(); map.remove(); } };
}

const windy = (overlay) => (pane) => {
  const url = `https://embed.windy.com/embed2.html?lat=52.0&lon=19.3&detailLat=52.17&detailLon=20.97&zoom=${overlay === "satellite" ? 4 : 6}&level=surface&overlay=${overlay}&product=ecmwf&menu=&message=true&marker=&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=kt&metricTemp=%C2%B0C&radarRange=-1`;
  pane.append(h(`<iframe class="embed" src="${url}" allowfullscreen></iframe>`));
};

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
      { id: "wind", label: "WINDY", fill: true, render: windy("wind") },
      { id: "radar", label: "RADAR", fill: true, render: windy("radar") },
      { id: "sat", label: "SAT EUR", fill: true, render: windy("satellite") },
    ]);
  },
};
