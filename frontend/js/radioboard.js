// RADIO (jedna strona jak w PANDORZE): czyste funkcje bez DOM – adres (warstwy), rzutowanie map, układ plakietek
// bez nakładania się, siatka strony wg szkicu (0.13.2, issue #27: miejsca kafelków, kodów FIR-ów, przycisków
// i podglądów jak na szkicu, wygląd kafelków z 0.13.1, wysokości między kafelkami). Testowane w Node
// (test_radio_board.py).

// Warstwy z kolumny przycisków (PANDORA: ATIS / LOW MID HIGH / APP / TWR / TWR/A / FIS; OAT pomijamy)
export const LAYERS = [
  { id: "atis", label: "ATIS", tip: "ATIS of Polish aerodromes at the top, next to the configuration boxes (online with the information letter)" },
  { id: "low", label: "LOW", tip: "ACC sectors on the left preview: LOW (cross-section at FL330)" },
  { id: "mid", label: "MID", tip: "ACC sectors on the small preview: MID (FL350)" },
  { id: "high", label: "HIGH", tip: "ACC sectors on the right preview: HIGH (FL400)" },
  { id: "app", label: "APP", tip: "APP positions online: TMA boundary, name and frequency (on the LOW preview)" },
  { id: "twr", label: "TWR", tip: "Towers online: CTR boundary, name and frequency (on the LOW preview)" },
  { id: "twra", label: "TWR/A", tip: "Towers online and aerodrome ATIS: CTR boundary, name, frequency and ATIS (on the LOW preview)" },
  { id: "fis", label: "FIS", tip: "FIS positions online: FIS area boundary, name and frequency (on the LOW preview)" },
];
export const LAYER_IDS = LAYERS.map((l) => l.id);
export const DEFAULT_LAYERS = ["atis", "low", "mid", "high"];
// Stałe przekroje podglądów (0.13.2, Marek: "Dla LOW przygotuj widok na FL330", bez suwaka wysokości – widoki
// uniwersalne): LOW na FL330 (kształty pasma FL295–FL335, bez wycięć TMA), MID na FL350, HIGH na FL400
export const LEVEL_FT = { LOW: 33000, MID: 35000, HIGH: 40000 };

// adres "#radio/<warstwy>": warstwy po przecinku w stałej kolejności, "none" = żadna
export function argOf(layers) {
  const ids = LAYER_IDS.filter((id) => layers.has(id));
  return ids.length ? ids.join(",") : "none";
}
// {layers: Set | null}; null = brak w adresie (zostaje bieżący stan). Stary adres z przekrojem LOW
// (#radio/atis,low/fl300, do 0.13.1) otwiera się dalej: część po "/" pomijamy
export function parseArg(arg) {
  const [ly = ""] = String(arg || "").split("/");
  let layers = null;
  if (ly === "none") layers = new Set();
  else if (ly) {
    const ids = ly.split(",").filter((x) => LAYER_IDS.includes(x));
    if (ids.length) layers = new Set(ids);
  }
  return { layers };
}

export const flNum = (ft) => String(Math.round((Number(ft) || 0) / 100));
export const flText = (ft) => "FL" + String(Math.round((Number(ft) || 0) / 100)).padStart(3, "0");

// wycinki ACC na podglądzie: przekrój poziomem ft (dolna granica włącznie)
export const sliceAt = (acc, ft) => (acc || []).filter((s) => s.lo <= ft && s.hi > ft);

// --- geometria
export function ringsOf(g) {
  if (!g) return [];
  if (g.type === "Polygon") return g.coordinates?.length ? [g.coordinates[0]] : [];
  if (g.type === "MultiPolygon") return (g.coordinates || []).filter((p) => p?.length).map((p) => p[0]);
  return [];
}
export function bboxOf(g) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  ringsOf(g).forEach((r) => r.forEach(([x, y]) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }));
  return [x0, y0, x1, y1];
}
// ramka FIR EPWW, gdy brak granicy FIR-u (bbox bez punktów: ±Infinity)
export const EPWW_BBOX = [14.1, 49.0, 24.2, 55.0];
export const bboxOrDefault = (b) => (b && b.length === 4 && b.every(Number.isFinite) && b[2] > b[0] && b[3] > b[1] ? b : null);
// czas z sieci (np. "2026-10-12T12:00:43.0000000Z": 7 cyfr ułamka) jako "HH:MMZ"; nieczytelny → "–"
export function utcHhmm(iso) {
  const t = Date.parse(String(iso || "").replace(/(\.\d{3})\d+/, "$1"));
  return Number.isNaN(t) ? "\u2013" : new Date(t).toISOString().slice(11, 16) + "Z";
}
// liczba kontrolerów na tablicy: online = stanowisko → kontroler; ten sam kontroler pod znakiem sąsiada (alias_of)
// i ATIS-y nie liczą się osobno
export const controllersOn = (online) => new Set(Object.entries(online || {})
  .filter(([cs, o]) => !/_ATIS$/.test(cs) && !/_ATIS$/.test(String(o?.callsign || "")))
  .map(([cs, o]) => String(o?.callsign || cs))).size;
// Rzut równoodległościowy (długość × cos 52°) dopasowany do prostokąta rect {x, y, w, h}: bbox [lon0, lat0, lon1, lat1]
// mieści się w nim w całości, wyśrodkowany w poziomie. Wynik: P([lon, lat]) → [x, y] w pikselach panelu.
// valign: "middle" (domyślnie) albo "bottom" (mały podgląd MID przy dolnej krawędzi, jak w PANDORZE).
export function projection(bbox, rect, pad = 0.03, valign = "middle") {
  const [x0, y0, x1, y1] = bbox;
  const k = Math.cos((52 * Math.PI) / 180);
  const w = Math.max(1e-6, (x1 - x0) * k), hh = Math.max(1e-6, y1 - y0);
  const s = Math.max(0.0001, Math.min(rect.w / w, rect.h / hh) * (1 - 2 * pad));
  const ox = rect.x + (rect.w - w * s) / 2;
  const oy = valign === "bottom" ? rect.y + rect.h - hh * s - rect.h * pad : rect.y + (rect.h - hh * s) / 2;
  const P = ([lon, lat]) => [ox + (lon - x0) * k * s, oy + (y1 - lat) * s];
  return { P, s, box: { x: ox, y: oy, w: w * s, h: hh * s } };
}
export function pathOf(g, P) {
  return ringsOf(g).map((r) => r.length > 2 ? "M" + r.map((c) => P(c).map((v) => v.toFixed(1)).join(",")).join("L") + "Z" : "").join("");
}
// wielokąt z dziurami (suma wycinków ACC jednego stanowiska): wszystkie pierścienie, wypełnienie evenodd (radio.css)
export function pathAll(g, P) {
  const polys = g?.type === "Polygon" ? [g.coordinates] : g?.type === "MultiPolygon" ? g.coordinates : [];
  return polys.flatMap((poly) => poly || []).map((r) => r.length > 2 ? "M" + r.map((c) => P(c).map((v) => v.toFixed(1)).join(",")).join("L") + "Z" : "").join("");
}

// Siatka kształtów warstwy (CTR, TMA) w pikselach panelu do układu etykiet: komórki `cell` px, przez które biegnie
// obrys (rings: [[x, y], …] już w pikselach) albo leży punkt (points: kropki lotnisk i TMA), z sumą prefiksową – coverOf
// liczy w stałym czasie, ile pola prostokąta zasłania obrysy. Liczy się obrys, nie wnętrze: etykieta w pustym środku
// dużej TMA nie chowa jej kształtu, etykieta na małym CTR – tak.
export function coverGrid(rings, w, h, { cell = 3, points = [] } = {}) {
  const nx = Math.max(1, Math.ceil(w / cell)), ny = Math.max(1, Math.ceil(h / cell)), g = new Uint8Array(nx * ny);
  const mark = (x, y) => {
    const i = Math.floor(x / cell), j = Math.floor(y / cell);
    if (i >= 0 && j >= 0 && i < nx && j < ny) g[j * nx + i] = 1;
  };
  (rings || []).forEach((r) => {
    (r || []).forEach(([ax, ay], k) => {
      const [bx, by] = r[(k + 1) % r.length];
      const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / (cell / 2)));
      for (let t = 0; t <= n; t++) mark(ax + ((bx - ax) * t) / n, ay + ((by - ay) * t) / n);
    });
  });
  (points || []).forEach(([x, y]) => {
    for (let dy = -4; dy <= 4; dy += cell / 2) for (let dx = -4; dx <= 4; dx += cell / 2) mark(x + dx, y + dy);
  });
  const S = new Int32Array((nx + 1) * (ny + 1));
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) S[(j + 1) * (nx + 1) + i + 1] = g[j * nx + i] + S[j * (nx + 1) + i + 1] + S[(j + 1) * (nx + 1) + i] - S[j * (nx + 1) + i];
  }
  return { cell, nx, ny, S };
}
// pole (px²) prostokąta {x0, y0, x1, y1}, które zasłania obrysy i punkty z coverGrid (null = nic)
export function coverOf(gr, r) {
  if (!gr) return 0;
  const { cell, nx, ny, S } = gr, cl = (v, n) => Math.max(0, Math.min(n, v));
  const i0 = cl(Math.round(r.x0 / cell), nx), i1 = cl(Math.round(r.x1 / cell), nx);
  const j0 = cl(Math.round(r.y0 / cell), ny), j1 = cl(Math.round(r.y1 / cell), ny);
  if (i1 <= i0 || j1 <= j0) return 0;
  const W = nx + 1;
  return (S[j1 * W + i1] - S[j0 * W + i1] - S[j1 * W + i0] + S[j0 * W + i0]) * cell * cell;
}
// czy odcinek (x0, y0)–(x1, y1) przecina prostokąt r (Liang–Barsky)
function crosses(x0, y0, x1, y1, r) {
  let t0 = 0, t1 = 1;
  const dx = x1 - x0, dy = y1 - y0;
  for (const [p, q] of [[-dx, x0 - r.x0], [dx, r.x1 - x0], [-dy, y0 - r.y0], [dy, r.y1 - y0]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t);
    if (t0 > t1) return false;
  }
  return true;
}
// czy odcinki a i b ([x0, y0, x1, y1]) przecinają się (bez stykania końcami)
function cross2(a, b) {
  const o = (x0, y0, x1, y1, px, py) => Math.sign((x1 - x0) * (py - y0) - (y1 - y0) * (px - x0));
  return o(...a, b[0], b[1]) * o(...a, b[2], b[3]) < 0 && o(...b, a[0], a[1]) * o(...b, a[2], a[3]) < 0;
}
// odległość punktu (px, py) od odcinka s
function distSeg(px, py, [x0, y0, x1, y1]) {
  const dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / l2)) : 0;
  return Math.hypot(px - x0 - t * dx, py - y0 - t * dy);
}
// Plakietki (0.13.2, Marek: "Usuń wszystkie leader line"): jedna odmiana jak kafelek, w środku swojego obszaru, bez
// linii do punktu – przy tłoku tylko lekko odsunięta: krawędź plakietki najwyżej `max` px od jej punktu (w tłoku
// × STRETCH). Parametry do placeLabels (wspólne dla strony i testu), kind acc / app / twr / fis: APP w środku
// obsługiwanych części TMA; TWR obok swojego CTR, gdy CTR jest mniejszy niż plakietka (obrys CTR pod plakietką kosztuje:
// wc, więc granica wieży zostaje widoczna); ACC i FIS – duże obszary, dalej od punktu, z dala od obrysów TMA i CTR
export const PLATE_MAX = 20;
export function labelOpts(kind) {
  if (kind === "app") return { max: PLATE_MAX, wc: 0.2 };
  if (kind === "twr") return { max: PLATE_MAX + 10, wc: 2 };
  return { max: 3 * PLATE_MAX, wc: 0.4 };
}

// Etykiety bez nakładania się. items [{x, y, w, h, alts?: [{w, h}], near?, max?, wc?, wv?, pin?}] w kolejności priorytetu
// (najpierw ważniejsze); x, y = punkt zakotwiczenia, w, h = rozmiar pełnej etykiety, alts = mniejsze odmiany (np.
// skrócona w jednej linii), pin = punkt to kropka na mapie (lotnisko, TMA), której żadna etykieta nie zasłania.
// Kandydaci leżą na pierścieniach coraz dalej od punktu (coraz więcej kierunków); dozwolony jest tylko kandydat bez
// kolizji z już ułożonymi etykietami i przeszkodami (obstacles: tytuł podglądu; {x0, y0, x1, y1}),
// w obrębie bounds {x, y, w, h} i bez kropki z pin (swojej i cudzej) pod sobą. Spośród nich wygrywa najtańszy:
// odległość etykiety od punktu (px) + pole zasłoniętych obrysów warstwy (cover z coverGrid, waga wc etykiety,
// domyślnie 1) × WC + kara za mniejszą odmianę (× wv) + kara WX za linię prowadzącą przez inną etykietę, przez inną
// linię albo tuż obok cudzej kropki i za etykietę na cudzej linii. Bez kształtów etykieta zostaje na punkcie, gdy jest
// tam miejsce; z kształtami (CTR, TMA) odchodzi obok nich, w wolne miejsce, z cienką linią do punktu. Pełna etykieta
// może odejść od punktu najwyżej o `near` px (krawędź etykiety od punktu; it.near nadpisuje), mniejsza odmiana albo
// jedyna (samo ID bez nikogo) o `max` px (domyślnie `far`); gdy nic nie pasuje, to samo w zasięgu × STRETCH (dłuższa
// linia), a dopiero potem najmniejsza odmiana w miejscu najmniejszego nałożenia. Układ zachłanny; gdy etykieta z wv > 1 zmalała (skrócona) albo coś zasłania, kolejna runda układa ją przed
// innymi (w tłoku, np. Warszawa–Modlin–Łódź–Radom na 1366 px, najpierw ta bez miejsca), a zostaje runda z najmniejszą
// liczbą zasłonięć, z nich ta o najmniejszym koszcie (nałożenie gorsze niż dłuższa linia i więcej skróconych).
// lines = false (plakietki RADIO od 0.13.2: bez linii prowadzących): bez kar za linie, tylko odległość, obrysy
// i nałożenia. Wynik: [{dx, dy, v, hit}] – przesunięcie środka, numer odmiany (0 = pełna) i czy coś zasłania.
const WC = 0.5, WV = [0, 25, 100], WX = 40, HIT = 500, ROUNDS = 4, STRETCH = 1.5;
export function placeLabels(items, bounds, { gap = 2, obstacles = [], near = 26, far = 90, rings = 14, cover = null, lines = true } = {}) {
  const pins = items.map((it, i) => (it.pin ? [it.x, it.y, i] : null)).filter(Boolean);
  const over = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  const rectAt = (it, s, dx, dy) => ({ x0: it.x + dx - s.w / 2 - gap / 2, y0: it.y + dy - s.h / 2 - gap / 2,
    x1: it.x + dx + s.w / 2 + gap / 2, y1: it.y + dy + s.h / 2 + gap / 2 });
  const outside = (r) => (bounds ? Math.max(0, bounds.x - r.x0) + Math.max(0, r.x1 - (bounds.x + bounds.w))
    + Math.max(0, bounds.y - r.y0) + Math.max(0, r.y1 - (bounds.y + bounds.h)) : 0);
  // odległość punktu zakotwiczenia od etykiety (0 = punkt pod etykietą)
  const reach = (s, dx, dy) => Math.hypot(Math.max(0, Math.abs(dx) - s.w / 2), Math.max(0, Math.abs(dy) - s.h / 2));
  // kropki pod prostokątem (z promieniem kropki)
  const dots = (r) => pins.filter(([x, y]) => x > r.x0 - 3 && x < r.x1 + 3 && y > r.y0 - 3 && y < r.y1 + 3);
  // linia od punktu do najbliższego miejsca etykiety
  const leadOf = (it, r) => [it.x, it.y, Math.max(r.x0, Math.min(it.x, r.x1)), Math.max(r.y0, Math.min(it.y, r.y1))];
  // kandydaci etykiety: pierścienie wokół punktu dla odmiany s w zasięgu limit
  function* ring(s, limit) {
    const sx = s.w * 0.3 + gap, sy = s.h * 0.55 + gap;
    for (let k = 0; k <= rings; k++) {
      const n = k ? 8 * k : 1;
      let any = false;
      for (let a = 0; a < n; a++) {
        const t = (a * 2 * Math.PI) / n;
        const dx = Math.round(Math.cos(t) * k * sx), dy = Math.round(Math.sin(t) * k * sy), d = reach(s, dx, dy);
        if (d > limit) continue;
        any = true;
        yield [dx, dy, d];
      }
      // cały pierścień poza zasięgiem
      if (!any && k > 1) return;
    }
  }
  // jedna runda w kolejności order: wybór i koszt każdej etykiety
  function once(order) {
    const placed = obstacles.map((o) => ({ ...o })), leads = [], out = [];
    let total = 0, hits = 0;
    order.forEach((idx) => {
      const it = items[idx], sizes = [{ w: it.w, h: it.h }, ...(it.alts || [])], wc = WC * (it.wc ?? 1);
      // najtańszy kandydat bez kolizji w zasięgu × k
      const search = (k) => {
        let pick = null, best = Infinity;
        sizes.forEach((s, v) => {
          const pv = WV[Math.min(v, WV.length - 1)] * (it.wv ?? 1);
          for (const [dx, dy, d] of ring(s, k * (v === 0 && sizes.length > 1 ? (it.near ?? near) : (it.max ?? far)))) {
            // już droższy niż najlepszy
            if (d + pv >= best) continue;
            const r = rectAt(it, s, dx, dy);
            if (outside(r) || placed.some((p) => over(r, p) > 0)) continue;
            if (dots(r).length) continue;  // kropka lotniska i TMA (swoja albo cudza) zostaje widoczna
            let cost = d + pv + coverOf(cover, r) * wc;
            if (cost >= best) continue;
            if (lines) cost += leads.reduce((acc, l) => acc + (crosses(...l, r) ? WX : 0), 0);
            if (lines && d > 0) {
              const l = leadOf(it, r);
              cost += placed.reduce((acc, p) => acc + (crosses(...l, p) ? WX : 0), 0)
                + leads.reduce((acc, m) => acc + (cross2(l, m) ? WX : 0), 0)
                + pins.reduce((acc, [x, y, i]) => acc + (i !== idx && distSeg(x, y, l) < 6 ? WX : 0), 0);
            }
            if (cost < best) { best = cost; pick = { dx, dy, v, r, d, hit: false }; }
          }
        });
        return { pick, best };
      };
      // w zasięgu nic wolnego (tłok wokół Warszawy): dalej, z dłuższą linią, zanim cokolwiek zasłoni
      let { pick, best } = search(1);
      if (!pick) ({ pick, best } = search(STRETCH));
      if (!pick) {
        // nic wolnego: najmniejsza odmiana tam, gdzie zasłania najmniej (także kropek)
        const v = sizes.length - 1, s = sizes[v];
        for (const [dx, dy, d] of ring(s, it.max ?? far)) {
          const r = rectAt(it, s, dx, dy);
          const cost = placed.reduce((acc, p) => acc + over(r, p), 0) + outside(r) * s.h * 4 + dots(r).length * s.w * 2
            + Math.hypot(dx, dy) * 0.05;
          if (cost < best) { best = cost; pick = { dx, dy, v, r, d, hit: true }; }
        }
        best += HIT;
      }
      placed.push(pick.r);
      if (lines && pick.d > 0) leads.push(leadOf(it, pick.r));
      out[idx] = { dx: pick.dx, dy: pick.dy, v: pick.v, hit: pick.hit };
      total += best;
      hits += pick.hit ? 1 : 0;
    });
    return { out, total, hits };
  }
  let order = items.map((_, i) => i), front = [], win = null;
  for (let round = 0; round < ROUNDS; round++) {
    const res = once(order);
    if (!win || res.hits < win.hits || (res.hits === win.hits && res.total < win.total)) win = res;
    const bad = order.filter((i) => (res.out[i].hit || (res.out[i].v > 0 && (items[i].wv ?? 1) > 1)) && !front.includes(i));
    if (!bad.length) break;
    front = [...front, ...bad];
    order = [...front, ...order.filter((i) => !front.includes(i))];
  }
  return win.out;
}

// UNICOM: FIR sąsiada bez nikogo online w sektorach przy granicy (linia pod nazwą FIR-u)
export const ADVISORY_FQ = "122.800";

// --- stos okienek FIR-u sąsiada (0.13.1, issue #25: stary styl strony, podział okienek wg szkicu Marka z
// data/seed/radio_layout.json). Siatka CSS z kolumn i wierszy szkicu, w których stoją okienka (f.cols, f.rows
// z /api/radio/board; bez nich – z okienek): kolumna stosu = kolumna szkicu, na przemian rząd liczb (wysokości między
// kafelkami, k = 0..m) i rząd kafelków (m = liczba wierszy). Kolumny i wiersze tylko ze szkicu i z okienek bez łączenia
// (połączone rozłożone na members z komórkami), więc stos nigdy nie zmienia rozmiaru: połączone okienko zajmuje te
// kolumny i wiersze stosu, które leżą w jego prostokącie (EDUU_H12_CTR w OSE2 … HVL1, wiersze szkicu 7–12 z pustymi
// 9 i 10: cztery rzędy kafelków jak bez łączenia, nie sześć).
// Liczby w kolumnie i, rząd k: nad = kafelek w (i, k-1), pod = kafelek w (i, k); liczy tylko kafelek w swojej pierwszej
// kolumnie, ten sam nad i pod = zakryte (bez liczby). Tylko pod: jego górna granica; tylko nad: jego dolna; ten sam
// zakres (EDWW MRZ, MAR, FLG: 285-0; też dwa połączone okienka, EDUU OSE2+OSE1 nad HVL2+HVL1: 660-285): nic
// między nimi; ta sama granica (nad.lower = pod.upper): jedna liczba; inaczej
// dwie z kreską między nimi (nowy ciąg okienek: EDUU OSE1 285, HVL2 660). Liczby jak na szkicu i zdjęciu PANDORY (660,
// 365, 999, 0); nad i pod połączonym okienkiem granice jego członków przy tej krawędzi (jak bez łączenia). Wysokość
// rzędów liczb stała, z podziału bez łączenia: l0 bez liczb, l1 jedna, l2 dwie z kreską. Wynik {ncols, nrows,
// cols: ["t", …], rows: ["l1", "t", …] (tory: t = kafelek, l0..l2 = rząd liczb), tiles: [{b, gc, gr}] (grid-column,
// grid-row), marks: [{gc, gr, n: [liczby], at: up | dn | sh | two}]}.
// 0.13.2 (issue #27): ta sama siatka dla całej strony – pageGrid podaje każdemu FIR-owi wszystkie kolumny i wiersze
// szkicu (f.cols, f.rows), więc tory stosów są torami strony, a kafelki różnych FIR-ów w jednym wierszu stoją równo.
// Połączone okienko na kilka kolumn (przegląd 0.13.2): w dalszej kolumnie granica jego członka z tej kolumny, gdy
// inna niż w kolumnie obok (ESAA 9+6+8+7 nad L: 195 pod 8 i 0 pod 7; EDMM MEI+SPE1: 315 i 660 nad nim)
export function stackGrid(f) {
  const num = (v, d = 0) => (Number(v) > 0 ? Math.round(Number(v)) : d);
  const cellOf = (b) => ({ b, col: num(b?.col, 1), row: num(b?.row, 1), cols: num(b?.cols, 1), rows: num(b?.rows, 1) });
  const boxes = (Array.isArray(f?.boxes) ? f.boxes : []).map(cellOf);
  // komórki bez łączenia: połączone okienko rozłożone na members, gdy wszyscy mają komórki w jego prostokącie (inaczej
  // samo okienko); of = okienko na stronie, do którego należy komórka
  const inside = (x, c) => x.col >= c.col && x.row >= c.row && x.col + x.cols <= c.col + c.cols && x.row + x.rows <= c.row + c.rows;
  const base = boxes.flatMap((c) => {
    const ms = Array.isArray(c.b.members) ? c.b.members : [], cs = ms.map(cellOf);
    return c.b.merged && ms.length && ms.every((x) => num(x?.col) && num(x?.row)) && cs.every((x) => inside(x, c))
      ? cs.map((x) => ({ ...x, of: c.b })) : [{ ...c, of: c.b }];
  });
  // kolumny i wiersze stosu: ze szkicu (część stała) i z komórek bez łączenia (żadne okienko nie wypada poza stos);
  // prostokąt połączonego okienka nie dodaje pustych wierszy szkicu między członkami
  const axis = (fixed, k, s) => [...new Set([...(Array.isArray(fixed) ? fixed.map(Number).filter((v) => v > 0) : []),
    ...base.flatMap((c) => Array.from({ length: c[s] }, (_, i) => c[k] + i))])].sort((a, b) => a - b);
  const cols = axis(f?.cols, "col", "cols"), rows = axis(f?.rows, "row", "rows"), m = rows.length;
  const within = (list, v0, n) => list.map((v, i) => (v >= v0 && v < v0 + n ? i : -1)).filter((i) => i >= 0);
  const grid = (list) => {
    const occ = cols.map(() => Array(m).fill(null));
    const placed = list.map((c) => {
      const ci = within(cols, c.col, c.cols), ri = within(rows, c.row, c.rows);
      return { ...c, c0: ci[0], c1: ci[ci.length - 1], r0: ri[0], r1: ri[ri.length - 1] };
    });
    placed.forEach((t) => { for (let i = t.c0; i <= t.c1; i++) for (let k = t.r0; k <= t.r1; k++) occ[i][k] ||= t; });
    return { occ, placed };
  };
  const up = (t) => Math.round(Number(t.b.upper) || 0), lo = (t) => Math.round(Number(t.b.lower) || 0);
  // granice kafelka t przy jego krawędzi w wierszu r stosu (pierwszym albo ostatnim): z jego komórek bez łączenia
  // w tym wierszu (najwyższa górna, najniższa dolna), bez nich – samo okienko. Połączone EDUU OSE1 + HVL2 (660-285):
  // nad nim 365 (OSE1), pod nim 365 (HVL2) jak bez łączenia, nie 365/660 i 285/365 w rzędzie na jedną liczbę.
  // 0.13.2 (issue #27): liczba stoi w pierwszej kolumnie kafelka, więc najpierw komórka z tej kolumny – ESAA 8 + 7
  // nad L: 195 (dolna granica 8, ta sama co górna L), nie 0/195, i rząd liczb strony nie rośnie przy łączeniu
  const rim = (t, r) => {
    const row = st.occ.map((c) => c[r]).filter((s) => s && s.of === t.b), mine = row.filter((s) => s.c0 === t.c0);
    const cs = mine.length ? mine : row;
    return cs.length ? { ...t, b: { upper: Math.max(...cs.map(up)), lower: Math.min(...cs.map(lo)) } } : t;
  };
  // {n: liczby, at: przy czym stoją}: up = górna granica kafelka pod spodem (liczba przy nim, na dole rzędu), dn = dolna
  // granica kafelka nad nią (na górze rzędu), sh = wspólna granica obu (w środku), two = dwie (dolna nad kreską,
  // górna pod nią; rząd liczb wyższy niż zwykle na stronie rozciąga się między nimi)
  const NONE = { n: [], at: "" };
  // Dalsza kolumna połączonego okienka (0.13.2, przegląd: ESAA 9+6+8+7 nad L pokazywało 660-195, choć 7 sięga ziemi;
  // EDMM MEI+SPE1 – 315-165 bez 660 nad SPE1): granica jego komórki bez łączenia w tej kolumnie przy krawędzi w wierszu
  // r (f = up albo lo), gdy różni się od granicy w kolumnie przed nią (ta sama – liczba już stoi obok; 660 nad ESAA 6)
  const cellAt = (t, r, i) => { const s = st.occ[i]?.[r]; return s && s.of === t.b ? s : null; };
  const later = (t, r, i, f) => {
    const s = cellAt(t, r, i);
    if (!s) return null;
    let p = null;
    for (let j = i - 1; j > t.c0 && !p; j--) p = cellAt(t, r, j);
    return f(s) === f(p || rim(t, r)) ? null : { ...t, b: { upper: up(s), lower: lo(s) } };
  };
  const nums = (occ, i, k, at = null) => {
    const aT = k > 0 ? occ[i][k - 1] : null, bT = k < m ? occ[i][k] : null;
    if (aT && aT === bT) return NONE;
    const a0 = aT && aT.c0 === i ? aT : null, b0 = bT && bT.c0 === i ? bT : null;
    if (a0 && b0 && up(a0) === up(b0) && lo(a0) === lo(b0)) return NONE;
    const a = a0 ? (at ? at(a0, k - 1) : a0) : at && aT ? later(aT, k - 1, i, lo) : null;
    const b = b0 ? (at ? at(b0, k) : b0) : at && bT ? later(bT, k, i, up) : null;
    if (a && b) {
      return up(a) === up(b) && lo(a) === lo(b) ? NONE : lo(a) === up(b) ? { n: [up(b)], at: "sh" } : { n: [lo(a), up(b)], at: "two" };
    }
    return a ? { n: [lo(a)], at: "dn" } : b ? { n: [up(b)], at: "up" } : NONE;
  };
  const cur = grid(boxes), st = grid(base), marks = [];
  // rząd liczb k: wysokość z podziału bez łączenia; po łączeniu liczb nie przybywa (granice członków), max – żeby
  // żadna liczba nie wyszła poza swój rząd także przy nietypowym połączeniu
  const now = Array.from({ length: m + 1 }, (_, k) => cols.map((_, i) => nums(cur.occ, i, k, rim)));
  const lv = now.map((n, k) => Math.max(0, ...cols.map((_, i) => Math.max(nums(st.occ, i, k).n.length, n[i].n.length))));
  now.forEach((n, k) => n.forEach((v, i) => { if (v.n.length) marks.push({ gc: `${i + 1}`, gr: `${2 * k + 1}`, n: v.n, at: v.at }); }));
  return { ncols: cols.length, nrows: 2 * m + 1, cols: cols.map(() => "t"), rows: lv.flatMap((l, k) => (k < m ? [`l${l}`, "t"] : [`l${l}`])),
    tiles: cur.placed.map((t) => ({ b: t.b, gc: `${t.c0 + 1} / ${t.c1 + 2}`, gr: `${2 * t.r0 + 2} / ${2 * t.r1 + 3}` })), marks };
}
// --- siatka strony wg szkicu (0.13.2, issue #27, Marek: "Zrób stronę dokładnie jak na szkicu"): 13 kolumn szkicu
// (grid.tracks z /api/radio/board: box = kafelek stałej szerokości, btn = przyciski warstw i MID, name = same kody
// FIR-ów z prawej, map = podglądy LOW i HIGH dzielące resztę szerokości) i wiersze szkicu od grid.top + 1 (rząd
// u góry: wskaźniki i ATIS-y, poza siatką). Każdy wiersz szkicu r to dwa tory: rząd liczb nad nim (levelTrack, tor
// nieparzysty) i kafelek (tileTrack); ostatni rząd liczb zamyka siatkę. Rzędy liczb rozciągają się (1fr), gdy okno
// jest wyższe niż strona – kafelki zawsze tej samej wysokości (radio.css: --rb-th). Liczby między kafelkami jak
// w stosach 0.13.1 (stackGrid na wszystkich kolumnach i wierszach strony)
export const COL_TRACK = { box: "var(--rb-tw)", btn: "var(--rb-hw)", name: "var(--rb-nw)", map: "minmax(0, 1fr)" };
export const ROW_TRACK = { t: "var(--rb-th)", l0: "minmax(var(--rb-lv0), 1fr)", l1: "minmax(var(--rb-lv1), 1fr)",
  l2: "minmax(var(--rb-lv2), 1fr)" };
export const levelTrack = (r, top) => 2 * (r - top - 1) + 1;
export const tileTrack = (r, top) => 2 * (r - top - 1) + 2;
// miejsce komórki szkicu {col, row, cols, rows} na stronie (grid-column, grid-row): od toru kafelka pierwszego wiersza
// do końca toru kafelka ostatniego; above / below = ile torów więcej nad i pod (rząd liczb obok)
export function cellArea(c, top, { above = 0, below = 0 } = {}) {
  const n = (v) => Math.max(1, Math.round(Number(v) || 1));
  const r0 = tileTrack(n(c?.row), top) - above, r1 = tileTrack(n(c?.row) + n(c?.rows) - 1, top) + 1 + below;
  return { gc: `${n(c?.col)} / span ${n(c?.cols)}`, gr: `${Math.max(1, r0)} / ${r1}` };
}
// Siatka strony: grid z /api/radio/board (cols, rows, top, tracks) i bloki FIR-ów (firs: boxes) → {top, cols: tory
// kolumn (COL_TRACK), rows: tory wierszy (ROW_TRACK; rząd liczb tak wysoki jak najwyższy z FIR-ów), stacks:
// [{f, g: stackGrid}] w torach strony}
export function pageGrid(grid, firs) {
  const n = (v) => Math.max(0, Math.round(Number(v) || 0));
  const top = n(grid?.top), nc = Math.max(1, n(grid?.cols)), nr = Math.max(top + 1, n(grid?.rows));
  const cols = Array.from({ length: nc }, (_, i) => i + 1), rows = Array.from({ length: nr - top }, (_, i) => top + 1 + i);
  const stacks = (Array.isArray(firs) ? firs : []).map((f) => ({ f, g: stackGrid({ ...f, cols, rows }) }));
  const len = Math.max(2 * rows.length + 1, ...stacks.map((s) => s.g.nrows));
  const lvl = (j) => Math.max(0, ...stacks.map((s) => Number(String(s.g.rows[j] || "l0").slice(1)) || 0));
  const kinds = Array.isArray(grid?.tracks) && grid.tracks.length ? grid.tracks : cols.map(() => "box");
  return { top, cols: kinds.map((k) => COL_TRACK[k] || COL_TRACK.map),
    rows: Array.from({ length: len }, (_, j) => (j % 2 ? ROW_TRACK.t : ROW_TRACK[`l${Math.min(2, lvl(j))}`])), stacks };
}
// Nazwa plakietki stanowiska ACC (0.13.2, Marek): jeden sektor tej warstwy – litera i warstwa ("B LOW"), kilka – skrót
// stanowiska (acc_short z /api/radio/board: "ALL", "DBT", "TM"), bez skrótu – nazwa stanowiska (dn)
export function accPlateName(g, key, short, dn = (cs) => cs) {
  const ss = Array.isArray(g?.sectors) ? g.sectors : [];
  return ss.length === 1 && ss[0]?.letter ? `${ss[0].letter} ${key}` : short?.[g?.owner] || dn(g?.owner);
}

// granice okienka jak na szkicu (górna-dolna, FL): "660-365", "285-0" (dymek połączonego okienka)
export const limText = (b) => `${Math.round(Number(b?.upper) || 0)}-${Math.round(Number(b?.lower) || 0)}`;
// granice w dymku: od dolnej do górnej, GND od ziemi, UNL bez górnej (999)
const flOf = (n) => `FL${String(Math.round(n)).padStart(3, "0")}`;
export const limTip = (b) => `${Number(b?.lower) > 0 ? flOf(Number(b.lower)) : "GND"}\u2013${Number(b?.upper) >= 999 ? "UNL" : flOf(Number(b?.upper) || 0)}`;

// --- dymek przy kursorze (0.13.0, Marek: okno ściśnięte przy prawej krawędzi): stała szerokość (radio.css), na prawo
// od kursora, a gdy podszedłby bliżej niż TIP_GAP px do prawej krawędzi okna – na lewo od niego; pod kursorem, przy
// dolnej krawędzi nad nim; nigdy bliżej brzegu okna niż TIP_GAP. cx, cy = kursor, w, h = rozmiar dymku (szerokość
// stała, więc mierzona przed ustawieniem miejsca jest ta sama), vw, vh = okno. Wynik {left, top, flipX, flipY} (px)
// Dymek wyższy niż miejsce nad i pod kursorem: dosunięty do dolnej krawędzi (12 px od niej), a gdy wyższy niż okno,
// od góry – radio.css ogranicza wysokość dymku do okna bez dwóch odstępów, więc nic nie wychodzi poza okno
export const TIP_GAP = 12;
export function tipPos(cx, cy, w, h, vw, vh) {
  const flipX = cx + 14 + w > vw - TIP_GAP, flipY = cy + 16 + h > vh - TIP_GAP;
  const left = flipX ? cx - 14 - w : cx + 14, top = flipY ? cy - 10 - h : cy + 16;
  return { left: Math.round(Math.max(TIP_GAP, Math.min(left, vw - TIP_GAP - w))),
    top: Math.round(Math.max(TIP_GAP, Math.min(top, vh - TIP_GAP - h))), flipX, flipY };
}

// Panel LOA (kliknięcie nagłówka stosu sąsiada): po tej stronie klikniętego stosu, gdzie jest więcej miejsca, i nie
// szerszy niż to miejsce, żeby nagłówek i okienka tego FIR-u zostały widoczne (drugie kliknięcie zamyka panel; ESAA,
// LKAA, LZBB i UMKK stoją blisko środka strony). x0, x1 = lewa i prawa krawędź stosu FIR-u w siatce strony, W = szerokość
// siatki (px). Najwyżej LOA_MAX px i LOA_FRAC siatki, nie węższy niż LOA_MIN px (wtedy może zasłonić część FIR-u).
// Wynik {left: panel przy lewej krawędzi siatki, width}
export const LOA_MAX = 1120, LOA_FRAC = 0.72, LOA_MIN = 420, LOA_GAP = 8;
export function loaPlace(x0, x1, W) {
  const want = Math.min(LOA_MAX, W * LOA_FRAC), roomL = x0 - LOA_GAP, roomR = W - x1 - LOA_GAP;
  const room = Math.max(roomL, roomR);
  return { left: roomL > roomR, width: Math.round(Math.max(Math.min(want, room), Math.min(want, LOA_MIN))) };
}
