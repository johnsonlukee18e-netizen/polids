// METEO › QNH: mapa QNH regionalnego jak mapa rejonów QNH z AIP Polska (PAŻP): biały podkład bez kafelków
// w odwzorowaniu stożkowym (południki zbiegają się ku północy jak na mapie AIP), siatka co 1° z kreskami co 10′
// i opisami stopni, granica FIR EPWW (jedna oliwkowa linia w kolorze z mapy), rejony 1–14 (zielone granice
// i numery), pasy awaryjne 15–17 (pomarańczowe linie 53°N i 51°N), TMA/MTMA (liliowe, pogrubiony obrys i cienkie
// linie części TMA), CTR/MCTR (ciemniejsze, przerywany obrys), czarne opisy "BELOW TMA QNH FROM EPxx" z QNH lotniska,
// szare oznaczenia przestrzeni (TMA EPGD, MCTR EPOK…), lotniska (kółko z kropką = z METAR-em, romb = pozostałe)
// i ramki QNH przy numerach rejonów. Geometria i miejsca napisów z pliku rejonów (services/qnh.py), obok tabela
// rejonów (hPa, mmHg, inHg) i tabela TMA.
import { api, esc, h, ONLINE_EVENT } from "./api.js";

const QR_LAYERS = [["tma", "TMA/MTMA"], ["ctr", "CTR/MCTR"], ["ad", "Aerodromes"], ["cap", "Captions"],
  ["des", "Designators"]];
// zoom, dla którego dobrano miejsca napisów z JSON-a (mapa 960x900 przy oknie 1600x900, cały FIR): przy mniejszym
// napisy maleją razem z mapą (--k w CSS), ale nie mniej niż QR_MIN (60%, poniżej zoomu 6,76). Poziomy napisów
// (klasy qr-mid i qr-far w qnh.css): 0 = wszystkie; 1 = bez szarych oznaczeń i kodów lotnisk (najmniejsze napisy
// pierwsze nachodzą na inne); 2 = "z daleka": numery rejonów z ramką QNH i symbole lotnisk z METAR-em. Poziom to
// wyższy z dwóch: zoom poniżej progu z QR_TIERS (każdy próg to poziom wyżej, więc przybliżanie przywraca napisy krok
// po kroku; domyślny widok przy oknie 1366x657 i większym ma wszystkie napisy, przy 1366x627 i 1280x609 poziom 1,
// przy 1024x600 poziom 2) i oddalenie od widoku domyślnego ponad próg z QR_OUT (jedno "−" albo ząbek kółka to poziom
// wyżej, dwa "−" to widok "z daleka"). Ten sam model rozmiarów i poziomów: services/qnh.py (test nakładania).
const QR_ZOOM = 7.5, QR_MIN = 0.6, QR_TIERS = [6.95, 6.75], QR_OUT = [0.25, 0.75];
export const labelScale = (z) => Math.min(1, Math.max(QR_MIN, 2 ** (z - QR_ZOOM)));
// fit: zoom widoku domyślnego, przy którym cały FIR mieści się w oknie mapy
export const labelTier = (z, fit) => Math.max(QR_TIERS.filter((t) => z < t).length,
  QR_OUT.filter((d) => z < fit - d).length);
export const isFar = (z, fit) => labelTier(z, fit) === 2;

// odwzorowanie stożkowe wiernokątne Lamberta (kula) jak na mapie AIP: południk środkowy 19°E, stała stożka 0,798
// (styczne na ok. 53°N, wartość dopasowana do siatki mapy PAŻP); skala jak w EPSG:3857 (256 px na obwód przy zoomie 0).
// Tworzone dopiero przy otwarciu mapy (w testach Node nie ma Leafleta).
let qrCrs = null;
const lccCrs = () => qrCrs || (qrCrs = (() => {
  const R = 6378137, d = Math.PI / 180, n = 0.798, l0 = 19 * d;
  const tn = (lat) => Math.tan(Math.PI / 4 + lat / 2) ** n;
  const F = Math.cos(Math.asin(n)) * tn(Math.asin(n)) / n, r0 = R * F / tn(52 * d);
  const projection = {
    project: (ll) => {
      const r = R * F / tn(ll.lat * d), t = n * (ll.lng * d - l0);
      return L.point(r * Math.sin(t), r0 - r * Math.cos(t));
    },
    unproject: (p) => {
      const y = r0 - p.y, r = Math.hypot(p.x, y);
      return L.latLng((2 * Math.atan((R * F / r) ** (1 / n)) - Math.PI / 2) / d, (l0 + Math.atan2(p.x, y) / n) / d);
    },
    bounds: L.bounds([-2e7, -2e7], [2e7, 2e7]),
  };
  const s = 0.5 / (Math.PI * R);
  return L.extend({}, L.CRS.Earth, { code: "PolIDS:LCC", projection, transformation: new L.Transformation(s, 0.5, -s, 0.5) });
})());

const q4 = (q) => (q ? String(q) : "----");
// pasy awaryjne 15–17 (opis w podpowiedzi wiersza tabeli)
const BAND = { 15: "north of 53°N", 16: "between 51°N and 53°N", 17: "south of 51°N" };

// opis TMA jak na mapie AIP: "BELOW TMA" / "QNH FROM EPxx" z QNH lotniska w ramce na końcu (przy 'stack' ramka
// w trzecim wierszu, opis węższy); przy 'code' (TMA Kraków dzielona na część Katowic i Krakowa) bez kodu, a kod
// z QNH jest osobnym napisem w części lotniska
export function captionHtml(t) {
  const q = `<b class="q${t.qnh ? "" : " nil"}">${q4(t.qnh)}</b>`;
  if (t.code) return `<span>BELOW ${esc(t.below)}</span><span>QNH FROM</span>`;
  return t.stack ? `<span>BELOW ${esc(t.below)}</span><span>QNH FROM ${esc(t.icao)}</span><span>${q}</span>`
    : `<span>BELOW ${esc(t.below)}</span><span>QNH FROM ${esc(t.icao)} ${q}</span>`;
}
export const codeHtml = (t) => `<span>${esc(t.icao)} <b class="q${t.qnh ? "" : " nil"}">${q4(t.qnh)}</b></span>`;

export function qnhMap(pane) {
  const wrap = h(`<div class="qrwrap"><div class="qrmapbox"><div class="map qrmap"></div><div class="qr-grat"></div></div>
    <div class="qrside">
      <div class="qr-head"><b>QNH regions</b><span class="qr-stamp"></span></div>
      <div class="qr-tools">${QR_LAYERS.map(([k, l]) => `<label><input type="checkbox" data-k="${k}" checked> ${l}</label>`).join("")}</div>
      <div class="qr-err"></div>
      <div class="qr-card"><h4>QNH regions <span>lowest aerodrome QNH</span></h4><table class="data qr-reg"></table></div>
      <div class="qr-card"><h4>TMA / MTMA <span>QNH below TMA</span></h4><table class="data qr-tma"></table></div>
      <p class="qr-note"></p>
    </div></div>`);
  pane.append(wrap);
  const $ = (s) => wrap.querySelector(s);
  // minZoom: dalej FIR to kilka pikseli, a napisy (nie mniejsze niż 60%) zlewają się w jeden stos
  const map = L.map($(".qrmap"), { crs: lccCrs(), minZoom: 5.5, zoomSnap: 0.1, zoomDelta: 0.5, wheelPxPerZoomLevel: 120,
    attributionControl: false });
  // kolejność warstw jak na mapie AIP: siatka i brzeg, TMA (wypełnienie, części wspólne, CTR, cienkie linie, obrysy),
  // pasy 15–17, granice rejonów, FIR, numery, szare oznaczenia, lotniska, opisy BELOW
  [["qgrid", 330], ["qtma", 340], ["qband", 345], ["qreg", 350], ["qfir", 360], ["qnum", 560], ["qdes", 580], ["qad", 600],
    ["qcap", 620]].forEach(([n, z]) => { map.createPane(n).style.zIndex = z; });
  const grid = L.layerGroup().addTo(map);   // siatka nie zależy od danych, draw() jej nie czyści
  const layers = Object.fromEntries(["base", "tma", "ctr", "ad", "cap", "des", "num", "hl"].map((k) => [k, L.layerGroup().addTo(map)]));
  const mmhg = (q) => Math.round(q * 0.750062);
  const inhg = (q) => (q * 0.0295300).toFixed(2);
  // napis w punkcie [lon, lat] z pliku (środek napisu); skala --k z CSS
  const div = (cls, html, attr = "") => L.divIcon({ className: "qr-icon", iconSize: null,
    html: `<div class="${cls}"${attr}>${html}</div>` });
  const mark = ([lon, lat], icon, pane, layer) => L.marker([lat, lon], { icon, pane, interactive: false, keyboard: false }).addTo(layer);
  const geo = (g, pane, className, layer, o = {}) => g && L.geoJSON(g, { pane, interactive: false, style: { className, ...o } }).addTo(layer);

  // siatka co 1° (południki proste, równoleżniki łukami) z kreskami co 10′ jak na mapie AIP
  const GL = { pane: "qgrid", className: "qr-gl", interactive: false };
  const steps = (a, b, st) => Array.from({ length: Math.round((b - a) / st) + 1 }, (_, i) => a + i * st);
  for (let lon = 12; lon <= 26; lon++) L.polyline([[47, lon], [57, lon]], GL).addTo(grid);
  for (let lat = 47; lat <= 57; lat++) L.polyline(steps(11, 27, 0.25).map((lon) => [lat, lon]), GL).addTo(grid);
  const ticks = [];
  for (let lon = 12; lon <= 26; lon++) for (let m = 47 * 6 + 1; m < 57 * 6; m++) if (m % 6) ticks.push([[m / 6, lon - 0.035], [m / 6, lon + 0.035]]);
  for (let lat = 47; lat <= 57; lat++) for (let m = 11 * 6 + 1; m < 27 * 6; m++) if (m % 6) ticks.push([[lat - 0.022, m / 6], [lat + 0.022, m / 6]]);
  L.polyline(ticks, { ...GL, className: "qr-gl tick" }).addTo(grid);
  // opisy stopni: długość przy górnej krawędzi, szerokość przy lewej i prawej (tam, gdzie linia siatki przecina krawędź)
  const grat = () => {
    if (!map._loaded) return;
    const sz = map.getSize(), pt = (lat, lon) => map.latLngToContainerPoint([lat, lon]);
    let out = "";
    // przy bardzo małym zoomie (południki gęściej niż szerokość opisu) bez opisów długości, żeby nie zlewały się w jeden napis
    for (let lon = 12; lon <= 26 && pt(57, 20).x - pt(57, 19).x >= 28; lon++) {
      // po oddaleniu, gdy siatka nie sięga górnej krawędzi: opis nad końcem południka (57°N), a nie przy krawędzi
      const a = pt(50, lon), b = pt(57, lon), y = Math.max(8, b.y - 8), x = a.x + (b.x - a.x) * (y - a.y) / (b.y - a.y);
      if (x > 30 && x < sz.x - 30) out += `<span style="left:${Math.round(x)}px;top:${Math.round(y - 6)}px">${lon}°</span>`;
    }
    for (let lat = 47; lat <= 57; lat++) {
      const pts = steps(10, 28, 0.1).map((lon) => pt(lat, lon));
      [[3, "left"], [sz.x - 3, "right"]].forEach(([ex, side]) => {
        const i = pts.findIndex((p, k) => k && (pts[k - 1].x - ex) * (p.x - ex) <= 0);
        if (i < 0) return;
        const a = pts[i - 1], b = pts[i], y = a.y + (b.y - a.y) * (ex - a.x) / (b.x - a.x);
        if (y > 22 && y < sz.y - 10) out += `<span class="lat" style="top:${Math.round(y)}px;${side}:2px">${lat}°</span>`;
      });
    }
    $(".qr-grat").innerHTML = out;
  };
  map.on("move zoom resize", grat);
  // obszar widoku domyślnego (przed wczytaniem danych prostokąt wokół FIR, potem granica FIR) i odstęp od brzegów
  let home = L.latLngBounds([49, 14.1], [55.85, 24.15]);
  const PAD = [4, 4];
  const scaleLabels = () => {
    const z = map.getZoom(), fit = map.getBoundsZoom(home, false, L.point(PAD).multiplyBy(2));
    const t = labelTier(z, fit);
    wrap.style.setProperty("--k", labelScale(z).toFixed(3));
    wrap.classList.toggle("qr-mid", t === 1);
    wrap.classList.toggle("qr-far", t === 2);
  };
  map.on("zoomend", scaleLabels);

  const show = () => wrap.querySelectorAll(".qr-tools input").forEach((i) => {
    const l = layers[i.dataset.k];
    if (i.checked && !map.hasLayer(l)) l.addTo(map);
    if (!i.checked && map.hasLayer(l)) map.removeLayer(l);
  });
  wrap.querySelector(".qr-tools").addEventListener("change", show);

  let data = null;
  const draw = () => {
    Object.values(layers).forEach((l) => l.clearLayers());
    // TMA jak na mapie AIP: liliowe obszary "BELOW ... QNH FROM", części wspólne dwóch obszarów ciemniejsze, CTR/MCTR
    // (półprzezroczyste: na TMA ciemniejsze, poza nią szare) z przerywanym obrysem, cienkie linie części TMA
    // i na wierzchu pogrubiony obrys każdego obszaru (także granica między sąsiednimi obszarami)
    const areas = data.tmas.filter((t) => t.area).map((t) => t.area);
    areas.forEach((g) => geo(g, "qtma", "qr-tfill", layers.tma, { stroke: false, fillOpacity: 1 }));
    geo(data.overlaps, "qtma", "qr-tover", layers.tma, { stroke: false, fillOpacity: 1 });
    data.tmas.forEach((t) => geo(t.parts, "qtma", "qr-tin", layers.tma, { fill: false }));
    areas.forEach((g) => geo(g, "qtma", "qr-tedge", layers.tma, { fill: false }));
    (data.ctrs || []).forEach((c) => geo(c.geometry, "qtma", "qr-ctr", layers.ctr, { fillOpacity: 1 }));
    if (data.coast) geo(data.coast, "qgrid", "qr-coast", layers.base);
    // granice rejonów (zielone na jasnoniebieskiej otoczce jak na mapie AIP), z obrysów pasów 15–17 tylko pomarańczowe
    // linie 53°N i 51°N (reszta obrysu to granica FIR, a szersza linia pasa wystawałaby spod niej) i FIR (jedna linia)
    const reg = data.regions.filter((r) => !r.band);
    ["qr-rcase", "qr-rline"].forEach((c) => reg.forEach((r) => geo(r.geometry, "qreg", c, layers.base, { fill: false })));
    const par = [];
    data.regions.filter((r) => r.band).flatMap((r) => (r.geometry.type === "Polygon" ? [r.geometry.coordinates] : r.geometry.coordinates))
      .forEach((poly) => {
        let run = [];
        const flush = () => { if (run.length > 1) par.push(run); run = []; };
        poly[0].forEach(([lon, lat]) => ([51, 53].some((p) => Math.abs(lat - p) < 1e-6) ? run.push([lat, lon]) : flush()));
        flush();
      });
    if (par.length) L.polyline(par, { pane: "qband", interactive: false, className: "qr-bline" }).addTo(layers.base);
    geo(data.fir, "qfir", "qr-fir", layers.base, { fill: false });

    // numery rejonów (15–17 pomarańczowe jak na mapie AIP) z ramką QNH rejonu po stronie 'qnh_at'
    data.regions.forEach((r) => mark(r.num, div(`qr-num${r.band ? " band" : ""}`,
      `${esc(r.id)}<span class="q q-${esc(r.qnh_at || "e")}${r.qnh ? "" : " nil"}">${q4(r.qnh)}</span>`, ` data-r="${esc(r.id)}"`),
    "qnum", layers.num));
    // lotniska: kółko z kropką = lotnisko z METAR-em (kontrolowane), romb = pozostałe; kod ICAO po stronie 'label'
    const qnhOf = {};
    data.regions.forEach((r) => r.stations.forEach((s) => { qnhOf[s.icao] = s.qnh; }));
    data.tmas.forEach((t) => { qnhOf[t.icao] = t.qnh; });
    data.aerodromes.forEach((a) => {
      L.marker([a.lat, a.lon], { pane: "qad", keyboard: false, icon: L.divIcon({ className: "qr-icon", iconSize: null,
        html: `<div class="qr-aero${a.metar ? " ctl" : ""} s-${esc(a.label || "e")}"><i></i><span>${esc(a.icao)}</span></div>` }) })
        .bindTooltip(`${esc(a.icao)}${qnhOf[a.icao] ? " Q" + qnhOf[a.icao] : ""}`, { direction: "top", offset: [0, -6], className: "qr-tip" })
        .addTo(layers.ad);
    });
    // opisy "BELOW TMA / QNH FROM EPxx 1013" czarnym napisem w miejscu z mapy AIP ("cap"), kod z QNH osobno ("code")
    data.tmas.forEach((t) => {
      if (t.cap) mark(t.cap, div("qr-cap", captionHtml(t), ` data-t="${esc(t.icao)}"`), "qcap", layers.cap);
      if (t.code) mark(t.code, div("qr-cap qr-code", codeHtml(t), ` data-t="${esc(t.icao)}"`), "qcap", layers.cap);
    });
    // szare oznaczenia przestrzeni z mapy AIP: rodzaj nad kodem (TMA / EPGD, MCTR / EPOK, TMA / EPPO NORTH)
    (data.chart_labels || []).forEach((c) => mark(c.lonlat, div("qr-des", c.lines.map((l) => `<span>${esc(l)}</span>`).join("")),
      "qdes", layers.des));
    show();
  };

  // podświetlenie rejonu / TMA po najechaniu na wiersz tabeli
  let hot = null;
  const highlight = (tr) => {
    if (tr === hot) return;
    hot = tr;
    layers.hl.clearLayers();
    wrap.querySelectorAll(".qrmap .on").forEach((e) => e.classList.remove("on"));
    if (!tr || !data) return;
    const r = tr.dataset.r && data.regions.find((x) => String(x.id) === tr.dataset.r);
    const t = tr.dataset.t && data.tmas.find((x) => x.icao === tr.dataset.t);
    const g = r ? r.geometry : t && t.area;
    if (g) geo(g, "qfir", "qr-hl", layers.hl);
    wrap.querySelectorAll(r ? `.qr-num[data-r="${CSS.escape(tr.dataset.r)}"]` : `.qr-cap[data-t="${CSS.escape(tr.dataset.t)}"]`)
      .forEach((e) => e.classList.add("on"));
  };
  const side = $(".qrside");
  side.addEventListener("mouseover", (e) => highlight(e.target.closest("tr[data-r], tr[data-t]")));
  side.addEventListener("mouseleave", () => highlight(null));

  // pasy awaryjne 15–17: zamiast wszystkich lotnisk pasa tylko lotnisko z najniższym QNH (i liczba lotnisk pasa)
  const table = () => {
    const st = (s, low) => `<span class="${s.qnh === null ? "nil" : s.qnh === low ? "low" : ""}">${esc(s.icao)}&nbsp;${s.qnh ?? "–"}</span>`;
    const sta = (r) => (!r.band ? r.stations.map((s) => st(s, r.qnh)).join(" ")
      : `${r.stations.filter((s) => s.qnh !== null && s.qnh === r.qnh).slice(0, 2).map((s) => st(s, r.qnh)).join(" ") || "–"}
        <span class="nil of">of ${r.stations.length} AD</span>`);
    hot = null;
    $(".qr-reg").innerHTML = `<thead><tr><th>Reg</th><th>QNH</th><th>mmHg</th><th>inHg</th><th>Aerodromes</th></tr></thead><tbody>${data.regions.map((r) =>
      `<tr data-r="${esc(r.id)}"${r.band ? ` class="band" title="Region ${esc(r.id)}: backup band ${BAND[r.id] || ""}, issued only when the IMGW model fails; here the lowest QNH of ${r.stations.length} band aerodromes"` : ""}>
      <td class="num">${esc(r.id)}</td><td class="num q">${q4(r.qnh)}</td><td class="num">${r.qnh ? mmhg(r.qnh) : ""}</td>
      <td class="num">${r.qnh ? inhg(r.qnh) : ""}</td><td class="sta">${sta(r)}</td></tr>`).join("")}</tbody>`;
    $(".qr-tma").innerHTML = `<thead><tr><th>TMA / MTMA</th><th>AD</th><th>QNH</th><th>mmHg</th></tr></thead><tbody>${data.tmas.map((t) =>
      `<tr data-t="${esc(t.icao)}"><td>${esc(t.name)}</td><td class="mono">${esc(t.icao)}</td><td class="num q">${q4(t.qnh)}</td>
      <td class="num">${t.qnh ? mmhg(t.qnh) : ""}</td></tr>`).join("")}</tbody>`;
  };

  // widok od razu (także gdy API nie odpowiada), po pierwszym wczytaniu dopasowany do granicy FIR
  map.fitBounds(home, { padding: PAD });
  scaleLabels();
  let fitted = false, dead = false;
  const load = async () => {
    let d;
    try { d = await api("/api/meteo/qnh-regions"); } catch (e) { if (!dead) $(".qr-err").textContent = e.message; return; }
    if (dead) return;   // zakładka zamknięta w trakcie pobierania
    data = d;
    draw();
    if (data.fir) home = L.geoJSON(data.fir).getBounds();
    if (!fitted && data.fir) map.fitBounds(home, { padding: PAD, animate: false });
    fitted = true;
    scaleLabels();
    grat();
    $(".qr-stamp").textContent = "Updated " + new Date().toISOString().slice(11, 16) + "Z";
    $(".qr-err").textContent = data.error || "";
    table();
    $(".qr-note").textContent = data.note || "";
  };
  load();
  const timer = setInterval(load, 300000);
  const online = () => $(".qr-err").textContent && load();   // serwer wrócił, a na mapie jest komunikat błędu
  window.addEventListener(ONLINE_EVENT, online);
  // zmiana okna: inny zoom dopasowany do FIR, więc i poziom napisów
  const ro = new ResizeObserver(() => { map.invalidateSize(); grat(); scaleLabels(); });
  ro.observe($(".qrmap"));
  return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); ro.disconnect(); map.remove(); } };
}
