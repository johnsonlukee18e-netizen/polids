// Zasięg pozycji (RADIO › GEO i SEKTORYZACJA): kto przejmuje który wycinek sektora przy danym zestawie aktywnych pozycji.
// Sektor ACC EPWW (B, C, … R-N): pierwsza aktywna pozycja z kolejności przejmowania (/api/nav/ownership) w warstwie
// wycinka (LOW/MID/HIGH wg dolnej granicy). Pozostałe wycinki (TMA, CTR, FIS, sąsiedzi): kolejność z chains.js –
// najpierw APP/TWR z listy OWNER pliku .ese, potem ACC (TMA: top-down z om.plvacc.pl, inne: lista OWNER .ese).
// Wycinki z /api/radio/sectors (owners = znaki stanowisk).
import { VACS_LAYERS, accLetter, fl, vacsLayer } from "./airspace.js";
import { airspaceChain } from "./chains.js";

// kolejność przejmowania wycinka (znaki stanowisk) i warstwa (tylko sektory ACC EPWW);
// src: "own" (sektor ACC, /api/nav/ownership), "om" (TMA z tabeli top-down om.plvacc.pl), "ese" (lista OWNER .ese)
const chainCache = new WeakMap();  // wycinek → {own, out}: sliceChain woła się dla każdego wycinka przy każdym rysowaniu
export function sliceChain(pr, own) {
  const hit = chainCache.get(pr);
  if (hit && hit.own === own) return hit.out;
  const letter = pr.fir === "EPWW" || !pr.fir ? accLetter(pr.name) : null;
  const layer = letter ? vacsLayer(pr.lower_ft ?? 0) : null;
  const chain = letter && own?.sectors?.[letter]?.[layer];
  let out;
  if (chain?.length) out = { chain, letter, layer, src: "own" };
  else {
    const a = airspaceChain(pr.name, pr.owners, own);
    out = { chain: a.chain, letter, layer, src: a.src, tma: a.tma };
  }
  chainCache.set(pr, { own, out });
  return out;
}
export const sliceOwner = (pr, active, own) => sliceChain(pr, own).chain.find((c) => active.has(c)) || null;

// filtr poziomu: {k: "all"} | {k: "LOW"|"MID"|"HIGH"} (wycinki zachodzące na warstwę) | {k: "fl", fl: 300}
export function levelOk(pr, lv, own) {
  if (!lv || lv.k === "all") return true;
  if (lv.k === "fl") return pr.lower_ft <= lv.fl * 100 && pr.upper_ft > lv.fl * 100;
  const L = own?.layers?.[lv.k];
  return !L || (pr.lower_ft < L.upper_ft && pr.upper_ft > L.lower_ft);
}
export const levelText = (lv, own) => (lv.k === "all" ? "wszystkie poziomy" : lv.k === "fl" ? `FL${String(lv.fl).padStart(3, "0")}`
  : `${lv.k} ${own?.layers?.[lv.k]?.label || ""}`.trim());
export const rangeText = (lo, hi) => `${lo ? fl(lo) : "GND"}–${fl(hi)}`;

// klucz kształtu: wycinki tej samej nazwy o tej samej geometrii (różne przedziały wysokości) rysujemy raz
export function geomKey(f) {
  const g = f.geometry, ring = g.type === "Polygon" ? g.coordinates[0] : g.type === "MultiPolygon" ? g.coordinates[0][0] : [];
  const p = (c) => (c ? `${c[0].toFixed(4)},${c[1].toFixed(4)}` : "");
  return `${f.properties.fir}/${f.properties.name}/${ring.length}/${p(ring[0])}/${p(ring[Math.floor(ring.length / 2)])}`;
}

// Sektory ACC w warstwach dla aktywnego zestawu: {pozycja: {litera: "LMH"}}, oraz nieobsadzone {litera: "LM"}
export function accSummary(active, own) {
  const by = {}, free = {};
  Object.keys(own?.sectors || {}).sort().forEach((s) => VACS_LAYERS.forEach((ly) => {
    const o = (own.sectors[s][ly] || []).find((c) => active.has(c));
    const m = o ? (by[o] ||= {}) : free;
    m[s] = (m[s] || "") + ly[0];
  }));
  return { by, free };
}
export const accText = (m) => Object.entries(m || {}).map(([s, ls]) => `${s} ${ls}`).join(", ");

// Punkt etykiety wewnątrz wielokąta, możliwie daleko od krawędzi (uproszczony polylabel: siatka próbek).
// within: [lonMin, latMin, lonMax, latMax] – szukaj tylko w tej ramce (np. część sektora sąsiada blisko Polski).
const labelCache = new Map();
export function labelPoint(f, within = null) {
  // klucz wg kształtu: u sąsiadów ta sama nazwa i dolna granica bywa przy różnych wielokątach (EDMM ALB, ETSIA)
  const key = `${geomKey(f)}/${within || ""}`;
  if (labelCache.has(key)) return labelCache.get(key);
  const g = f.geometry;
  const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
  let best = null, bestD = -1;
  polys.forEach(([ring]) => {
    if (!ring?.length) return;
    const k = Math.cos((ring[0][1] * Math.PI) / 180);  // długość geogr. → te same jednostki co szerokość
    const pts = ring.map(([x, y]) => [x * k, y]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (within) {
      [x0, x1, y0, y1] = [Math.max(x0, within[0] * k), Math.min(x1, within[2] * k), Math.max(y0, within[1]), Math.min(y1, within[3])];
      if (x0 >= x1 || y0 >= y1) return;
    }
    const N = 22;
    for (let i = 0; i < N; i++) {
      for (let j = 0; j < N; j++) {
        const x = x0 + ((x1 - x0) * (i + 0.5)) / N, y = y0 + ((y1 - y0) * (j + 0.5)) / N;
        let inside = false, d = Infinity;
        for (let a = 0, b = pts.length - 1; a < pts.length; b = a++) {
          const [ax, ay] = pts[a], [bx, by] = pts[b];
          if ((ay > y) !== (by > y) && x < ((bx - ax) * (y - ay)) / (by - ay) + ax) inside = !inside;
          const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
          const t = l2 ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) : 0;
          d = Math.min(d, Math.hypot(x - ax - t * dx, y - ay - t * dy));
        }
        if (inside && d > bestD) { bestD = d; best = [y, x / k]; }
      }
    }
  });
  const out = best ? { at: best, d: bestD } : null;
  labelCache.set(key, out);
  return out;
}
