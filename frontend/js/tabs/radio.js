// RADIO: jedna strona jak w PANDORZE. Od 0.13.0 (issue #23, szkic Marka i zdjęcie PANDORY) siatka 13 × 21 komórek
// z data/seed/radio_layout.json (GET /api/radio/board: grid, firs, indicators, berlin): u góry stały pasek ATIS (ta sama
// wysokość, gdy jest ukryty i przy dowolnej liczbie ATIS-ów – strona nigdy nie skacze), pod nim wskaźniki ACC GAT,
// APP GD, APP WA, APP KK, APP PO, BERLIN (WEST/EAST, czerwony napis = konfiguracja preferowana, bez pasa z ATIS),
// okienka FIR-ów sąsiednich (żółta nazwa, w okienku ID i granice jak na szkicu, np. "OSE2 660-365", i częstotliwość,
// gdy ktoś je obsługuje; okienka jednego stanowiska połączone w backendzie), w środku kolumna przycisków ATIS /
// LOW MID HIGH / APP / TWR / TWR/A / FIS, podgląd LOW na lewo od niej, HIGH na prawo, mały MID na dole.
// Sektory ACC na podglądach (runda 12, Marek): wycinki obsługiwane przez to samo stanowisko (kolejność przejmowania,
// ownership.json) jako jeden obszar z jedną etykietą (stanowisko i częstotliwość), granica tylko tam, gdzie zmienia
// się obsługujący; sektorów bez nikogo nie rysujemy (ramą zostaje granica FIR EPWW). FIS bez nikogo: samo ID (runda 11).
// Plakietki APP i TWR (0.13.0, Marek) tylko dla zalogowanych: jedna na stanowisko APP w środku części TMA, które
// obsługuje (WA APP, WA N APP i WA S APP – trzy), wieża w środku CTR (TWR/A także sam ATIS), bez linii do punktu;
// czerwone tło sektora ACC i TMA z ograniczeniem przepływu albo zajętością ponad 80 %; dymki stałej szerokości.
// LOW z suwakiem wysokości (FL095–FL330).
// Dane: GET /api/radio/board co 30 s (geometria raz, potem tylko po zmianie wersji danych `ver`, np. po imporcie nowych
// danych sektorów). Kliknięcie nazwy FIR-u sąsiada (np. EDWW): panel z wyciągiem z LOA EPWW z tym FIR-em
// (GET /api/radio/loa), z przyciskiem do dokumentu w COORDINATION › DOKUMENTY i PDF-em w nowej karcie.
import { api, esc, h, lsGet, lsSet, navigate, remember } from "../api.js";
import { labelPoint } from "../coverage.js";
import { dissolve, pointIn } from "../dissolve.js";
import { displayName, loadDisplayNames, posName } from "../posname.js";
import { ADVISORY_FQ, DEFAULT_CUT, DEFAULT_LAYERS, EPWW_BBOX, LAYERS, LAYER_IDS, argOf, bboxOf, bboxOrDefault, buttonRows,
  controllersOn, coverGrid, cutAt, cutBand, cutBounds, cutRange, flText, gridArea, gridTracks, labelOpts, limText, limTip, parseArg,
  pathAll, pathOf, placeLabels, projection, ringsOf, sliceAt, tipPos, utcHhmm } from "../radioboard.js";

const LS_LAYERS = "radio.layers", LS_CUT = "radio.cut";
const REFRESH_MS = 30000;
// MID i HIGH mają jeden kształt sektorów
const LEVEL_FT = { MID: 35000, HIGH: 40000 };
// podglądy: miejsce w siatce z grid.maps (klucz = warstwa)
const MAPS = [
  { key: "LOW", layer: "low", cls: "rb-low" },
  { key: "MID", layer: "mid", cls: "rb-midmap" },
  { key: "HIGH", layer: "high", cls: "rb-high" },
];
// etykiety warstw APP/TWR/FIS: krótkie ID bez rodzaju (kolor paska z lewej mówi, co to jest): WA S APP → WA S
const shortId = (id) => String(id).replace(/ (?:APP|DEP|TWR|FIS)$/, "");

function readLayers() {
  try {
    const v = JSON.parse(lsGet(LS_LAYERS));
    if (Array.isArray(v)) return new Set(v.filter((x) => LAYER_IDS.includes(x)));
  } catch { /* brak albo uszkodzony wpis */ }
  return new Set(DEFAULT_LAYERS);
}
// zapamiętany przekrój LOW wyrównany do suwaka (stary wpis z przycisków ◀ ▶ mógł mieć FL335 albo FL302)
function readCut() {
  const n = parseInt(lsGet(LS_CUT), 10);
  return n >= 95 && n <= 335 ? cutAt(n, cutRange(null)) : DEFAULT_CUT;
}

// przybliżone pole wielokąta (do wyboru większej części sektora dzielonego w poziomie, np. R-N i R-S)
const areaOf = (g) => ringsOf(g).reduce((a, r) => a + Math.abs(r.reduce((s, [x1, y1], i) => {
  const [x2, y2] = r[(i + 1) % r.length];
  return s + x1 * y2 - x2 * y1;
}, 0)) / 2, 0);

// Sektory ACC podglądu wg obsługującego (runda 12, Marek): wycinki na wysokości podglądu (accs, sliceAt) z tym samym
// stanowiskiem z kolejności przejmowania warstwy (sectors z /api/radio/board: owner) → jeden obszar (dissolve.js,
// w pamięci wg klucza: wersja danych, stanowisko, wycinki) i jeden punkt etykiety poza dziurami; wycinki bez nikogo
// pomijamy. Błąd sumy: geom null, rysujemy same wypełnienia wycinków. Wynik od największego obszaru:
// [{owner, sectors (wg ID), slices, geom, area, at: [lat, lon]}]
export function accGroups(accs, sectors, layer, ver = "") {
  const own = new Map((sectors || []).filter((s) => s.layer === layer && s.owner).map((s) => [s.letter, s]));
  const by = new Map();
  (accs || []).forEach((sl) => {
    const s = own.get(sl.letter);
    if (!s) return;
    let g = by.get(s.owner);
    if (!g) by.set(s.owner, (g = { owner: s.owner, sectors: [], slices: [] }));
    if (!g.sectors.includes(s)) g.sectors.push(s);
    g.slices.push(sl);
  });
  return [...by.values()].map((g) => {
    const u = dissolve(`rb|${ver}|${g.owner}|${g.slices.map((sl) => `${sl.name}:${sl.lo}`).sort().join(",")}`, g.slices.map((sl) => sl.geometry));
    const big = g.slices.reduce((a, sl) => (areaOf(sl.geometry) > areaOf(a.geometry) ? sl : a));
    const at = (u && (u.at ||= pointIn(u.geometry))) || labelPoint({ type: "Feature", geometry: big.geometry, properties: { fir: "EPWW", name: big.name } })?.at || null;
    return { ...g, sectors: g.sectors.sort((a, b) => a.id.localeCompare(b.id)), geom: u?.geometry || null,
      area: u ? u.area : g.slices.reduce((a, sl) => a + areaOf(sl.geometry), 0), at };
  }).sort((a, b) => b.area - a.area);
}
// etykieta sektorów ACC jednego stanowiska: nazwa stanowiska (id) i częstotliwość; x.freq jak w lblLines
export const accLabel = (g, id, x) => ({ cls: "acc", state: "on", id, k: g.owner, ls: [{ fq: x.freq(g.owner), by: "" }] });

// --- LOA EPWW z sąsiadem (data/seed/loa.json, jak do 0.11 w RADIO): tytuł, wersja, liczba przekazań i PDF, pod spodem
// gęste tabele przekazań OUT/IN, zasady (przekazanie kontroli, VFR, inne) i stanowiska wg LOA, z filtrem.
// Lista raz na sesję (plik zmienia się z nową wersją PolIDS); błąd nie zostaje w pamięci.
let loaP = null;
const loadLoa = () => (loaP ||= api("/api/radio/loa").catch((e) => { loaP = null; throw e; }));
// tylko ścieżki do plików PolIDS (/files/docs/…): PDF w nowej karcie; dokument w COORDINATION › DOKUMENTY
// (#coordination/docs/<FIR>: COORDINATION znajduje dokument LOA z tym FIR-em)
const DOCS = "/files/docs/";
const pdfPath = (pdf) => (String(pdf || "").startsWith(DOCS) ? String(pdf) : "");
const arr = (x) => (Array.isArray(x) ? x : []);

function loaTransfers(rows, from, to) {
  if (!rows.length) return "";
  // kolumny sektorów tylko, gdy LOA je podaje (LKAA, LZBB: bez sektorów)
  const sec = rows.some((t) => t.from || t.to);
  const head = `<tr><th>Traffic</th><th>COP</th><th>Level</th>${sec ? "<th>From sector</th><th>To sector</th>" : ""}<th>Conditions</th></tr>`;
  // filtr po treści wiersza bez pola dir ("out"/"in" pasowałoby do każdego przekazania w tę stronę)
  const body = rows.map((t) => `<tr data-f="${esc(Object.entries(t).filter(([k]) => k !== "dir").map(([, v]) => v).join(" ").toLowerCase())}">`
    + `<td class="trf">${esc(t.traffic)}</td><td class="cop">${esc(t.cop)}</td><td class="lvl">${esc(t.level)}</td>`
    + `${sec ? `<td class="sec">${esc(t.from)}</td><td class="sec">${esc(t.to)}</td>` : ""}<td class="cond">${esc(t.conditions)}</td></tr>`).join("");
  return `<div class="rb-loa-sec"><h4>${esc(from)} → ${esc(to)} <small>${rows.length}</small></h4>
    <table class="rb-loa-tab"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}
const loaList = (title, items) => (arr(items).length ? `<div class="rb-loa-sec"><h4>${esc(title)} <small>${items.length}</small></h4>
  <ul>${items.map((x) => `<li data-f="${esc(String(x).toLowerCase())}">${esc(x)}</li>`).join("")}</ul></div>` : "");

// fir, title: stos sąsiada z /api/radio/board; f: wpis z loa.json albo null (brak LOA z tym FIR-em, błąd: msg,
// jeszcze się wczytuje: loading); radio(cs): znak radiowy stanowiska, gdy LOA go nie podaje
export function loaHtml(fir, title, f, radio, { msg = "", loading = false } = {}) {
  const tr = arr(f?.transfers), out = tr.filter((t) => t.dir === "out"), inn = tr.filter((t) => t.dir === "in");
  const pdf = pdfPath(f?.pdf);
  // tytuł LOA podaje już FIR sąsiada (LOA EPWW – EDWW (Bremen)); bez LOA: FIR i nazwa ze stosu
  const head = `<div class="rb-loa-h"><b class="rb-loa-tag">LOA</b>${f ? "" : `<span class="rb-loa-fir"><b>${esc(fir)}</b> ${esc(title)}</span>`}`
    + (f ? `<span class="rb-loa-t" title="${esc(f.title)}">${esc(f.title)}</span>` : "")
    + `<span class="rb-loa-sp"></span>`
    + (pdf ? `<button type="button" class="rb-loa-a" data-coord="${esc(fir)}" title="Open the LOA in COORDINATION › DOCUMENTS (← returns to RADIO)">COORDINATION ›</button>`
      + `<a class="rb-loa-a" href="${esc(encodeURI(pdf))}" target="_blank" rel="noopener" title="Open the LOA PDF">PDF ↗</a>` : "")
    + `<button type="button" class="rb-loa-x" title="Close (Esc)">✕</button></div>`;
  if (!f) {
    return head + `<div class="rb-loa-b"><p class="${msg ? "error" : "hint"}">${msg ? esc(msg) : loading ? "Loading LOA…"
      : `No EPWW LOA with ${esc(fir)} in PolIDS. All LOAs: COORDINATION › DOCUMENTS.`}</p></div>`;
  }
  const pos = arr(f.positions).map((p) => `<tr data-f="${esc(Object.values(p).join(" ").toLowerCase())}">`
    + `<td class="${p.side === "EP" ? "ep" : "nb"}">${p.side === "EP" ? "EPWW" : esc(fir)}</td><td class="pcs">${esc(p.callsign)}</td>`
    + `<td>${esc(p.radio || radio(p.callsign))}</td><td class="cop">${esc(p.sector)}</td><td class="lvl">${esc(p.frequency)}</td>`
    + `<td class="cond">${esc(p.note)}</td></tr>`).join("");
  return head + `<div class="rb-loa-b">
    <div class="rb-loa-tools"><input type="search" class="rb-loa-q" placeholder="filter: COP, aerodrome, FL, sector…" aria-label="LOA filter">
      <span class="rb-loa-cnt"></span><span class="rb-loa-n">transfers: ${out.length} from EPWW · ${inn.length} to EPWW</span></div>
    ${loaTransfers(out, "EPWW", fir)}${loaTransfers(inn, fir, "EPWW")}
    <div class="rb-loa-rules">${loaList("Transfer of control and communication", f.silent)}${loaList("VFR", f.vfr)}${loaList("Other rules", f.other)}</div>
    ${pos ? `<div class="rb-loa-sec"><h4>Positions and sectors <small>${arr(f.positions).length}</small></h4>
      <table class="rb-loa-tab pos"><thead><tr><th>Side</th><th>Position</th><th>Radio callsign</th><th>Sector</th><th>Freq.</th><th>Remarks</th></tr></thead>
      <tbody>${pos}</tbody></table></div>` : ""}
  </div>`;
}

// --- dymki (runda 15, Marek): przestrzeń, stanowisko i kto ją teraz obsługuje – bez kolejności przejmowania i bez
// dopisków, skąd jest wartość. x: {who(cs), pos(cs), net} – zalogowany i opis stanowiska z tablicy, false = brak danych
// o zalogowanych
export const nowText = (owners, x) => (owners.length ? owners.map((o) => `Now: ${x.who(o) || o}`).join("\n")
  : x.net === false ? "Now: no data" : "Now: unstaffed");
// linie dymku alarmów przepływu (flow z /api/radio/board: ograniczenie albo zajętość ponad 80 % dopuszczalnej);
// pre: przestrzeń, gdy dymek mówi o kilku (sektor HB, TMA Radom)
export const flowLines = (alerts, pre = "") => arr(alerts).flatMap((a) => arr(a?.tip)).map((t) => (pre ? `${pre}: ${t}` : t));
// obszar stanowiska ACC na podglądzie: head (stanowisko i warstwa), kto, sektory warstwy w tym obszarze; flow – alarmy
// przepływu jego sektorów (sektor podany przy każdej linii)
export const accTip = (g, head, x, flow = null) => [head, nowText([g.owner], x), `Sectors: ${g.sectors.map((s) => s.id).join(", ")}`,
  ...g.sectors.flatMap((s) => flowLines(flow?.sectors?.[s.id], s.id))].join("\n");
// etykieta APP, TWR, FIS: tytuł, stanowisko, kto teraz (bez nikogo z tej przestrzeni: ACC, który przejmuje top-down),
// dodatki (extra); now zastępuje linijkę "kto teraz" (wieża przejmowana przez inne stanowisko)
export function groupTip(g, title, x, extra = [], now = null) {
  const cur = now || (g.owners.length || !g.topdown ? nowText(g.owners, x) : `Now top-down: ${x.who(g.topdown) || g.topdown}`);
  return [title, `Position: ${x.pos(g.nominal)}`, cur, ...extra].join("\n");
}

// --- okienka wg szkicu (0.13.0): wskaźniki, BERLIN, nazwy FIR-ów i okienka sąsiadów z /api/radio/board. Każde ma
// stałe miejsce w siatce (gridArea z komórek grid); x: {who(cs), pos(cs), freq(cs), net, sel} – zalogowany i opis
// stanowiska z tablicy, false = brak danych o zalogowanych (bez ADVISORY i bez zer we wskaźnikach), FIR otwartego LOA
const onlineLine = (o) => `${o.callsign} ${o.frequency || ""} \u2013 ${o.name || "?"}`.replace(/  +/g, " ");
// wskaźnik u góry: żółta nazwa, pod nią szare pole z wartością (ALL+S, 2H+L, 1-0); w dymku znaczenie i liczone stanowiska
export function indicatorHtml(i, x) {
  const ps = arr(i.positions);
  const rt = [`${i.id}${i.tip ? `: ${i.tip}` : ""}`, ...(x.net === false ? ["Now: no data"] : ps.length ? ps.map(onlineLine) : ["Nobody online"])].join("\n");
  const v = x.net === false ? "\u2013" : String(i.value ?? "0");
  return `<div class="rb-ind" style="grid-area: ${gridArea({ ...i, rows: 1 })}" data-rt="${esc(rt)}">${esc(i.id)}</div>`
    + `<div class="rb-indv" style="grid-area: ${gridArea({ ...i, row: (Number(i.row) || 1) + 1, rows: 1 })}" data-rt="${esc(rt)}">${esc(v)}</div>`;
}
// BERLIN: konfiguracja pasów Berlina w szarym polu jak w PANDORZE; bez pasa z ATIS (preferred) czerwony napis
export function berlinHtml(b) {
  const pref = !!b?.preferred;
  const rt = ["BERLIN: runway configuration of Berlin Brandenburg, WEST (runways 24) or EAST (runways 06)", b?.tip || "",
    ...(pref ? ["Red text: preferred configuration, no runway in use from ATIS"] : [])].filter(Boolean).join("\n");
  const box = b?.box?.col ? b.box : { col: b?.col, row: (Number(b?.row) || 1) + 1, cols: 2 };
  return `<div class="rb-blbl" style="grid-area: ${gridArea(b)}" data-rt="${esc(rt)}">BERLIN</div>`
    + `<div class="rb-bln${pref ? " pref" : ""}" style="grid-area: ${gridArea(box)}" data-rt="${esc(rt)}">${esc(b?.config || "\u2013")}</div>`;
}
// nazwa nad okienkami (okienko FIR-u tuż pod nią) albo obok nich (side: EYVL, UMMV, UKLV w kolumnie po prawej)
export function nameSide(f) {
  const n = f?.name || {};
  const c0 = Number(n.col) || 1, c1 = c0 + (Number(n.cols) || 1) - 1, below = (Number(n.row) || 1) + (Number(n.rows) || 1);
  return !arr(f?.boxes).some((b) => Number(b.row) === below && Number(b.col) <= c1 && Number(b.col) + (Number(b.cols) || 1) - 1 >= c0);
}
// nazwa FIR-u sąsiada (żółta; kliknięcie: LOA EPWW z tym FIR-em); cały FIR bez nikogo – pod nazwą ADVISORY 122.800
export function firNameHtml(f, x) {
  const on = arr(f.online);
  const rt = [`${f.fir} ${f.title || ""}`.trim(),
    ...(x.net === false ? ["Online: no data"] : on.length ? on.map((o) => `Online: ${onlineLine(o)}`) : [`Nobody online \u2013 ADVISORY ${ADVISORY_FQ}`]),
    `Click: LOA EPWW \u2013 ${f.fir}`].join("\n");
  return `<div class="rb-fir${nameSide(f) ? " side" : ""}${x.sel === f.fir ? " sel" : ""}" role="button" tabindex="0" data-fir="${esc(f.fir)}" data-title="${esc(f.title || "")}"`
    + ` style="grid-area: ${gridArea(f.name)}" data-rt="${esc(rt)}"><span class="rb-firn">${esc(f.fir)}</span>`
    + `${f.advisory && x.net !== false ? `<span class="rb-unfq">ADVISORY ${ADVISORY_FQ}</span>` : ""}</div>`;
}
// dymek okienka: ID i granice, stanowisko okienka, kto teraz (znak, częstotliwość, kontroler), okienka połączone
// w jedno; okienko na cały FIR (UMKK, UMMV, UKLV) – także pozostali zalogowani tego FIR-u
export function boxTip(b, f, x) {
  const lines = [`${f.fir} ${b.label} \u00b7 ${limTip(b)}`];
  if (!b.merged && b.callsign) lines.push(`Position: ${x.pos(b.callsign)}`);
  lines.push(b.owner ? nowText([b.owner], x) : x.net === false ? "Now: no data"
    : f.advisory ? `Now: unstaffed \u2013 ADVISORY ${ADVISORY_FQ}` : "Now: unstaffed");
  if (b.merged) lines.push(`Merged: ${arr(b.members).map((m) => `${m.id} ${limText(m)}`).join(", ")}`);
  if (arr(f.boxes).length === 1) arr(f.online).filter((o) => o.position !== b.owner).forEach((o) => lines.push(`Also online: ${onlineLine(o)}`));
  return lines.join("\n");
}
// okienko sąsiada jak na szkicu i zdjęciu PANDORY: ID i granice ("OSE2 660-365"), pod nimi częstotliwość tego, kto je
// teraz obsługuje (białe pole); bez nikogo samo ID i granice (ciemnoszare pole); połączone przez kilka komórek
export function boxHtml(b, f, x) {
  const fq = b.owner ? b.frequency || x.freq(b.owner) : "";
  return `<div class="rb-box ${b.owner ? "on" : "off"}${b.merged ? " mrg" : ""}" data-fir="${esc(f.fir)}" data-box="${esc(b.id)}"`
    + ` style="grid-area: ${gridArea(b)}" data-rt="${esc(boxTip(b, f, x))}">`
    + `<span class="rb-bt"><span class="rb-id">${esc(b.label)}</span> <span class="rb-lim">${esc(limText(b))}</span></span>`
    + `${fq ? `<span class="rb-fq">${esc(fq)}</span>` : ""}</div>`;
}
export const firHtml = (f, x) => firNameHtml(f, x) + arr(f.boxes).map((b) => boxHtml(b, f, x)).join("");

// --- etykieta podglądu (sektor ACC, plakietka APP i TWR, FIS) w odmianach: 0 pełna (ID nad częstotliwością),
// 1 skrócona (ID i częstotliwość w jednej linii, gdy pełna nie mieści się przy swoim punkcie) i 2 samo ID; szczegóły
// zawsze w dymku. lb: {cls, state, id, ls: [{fq, by}], more?, extra?, code?, k?, icao?, rt}.
// Samo ID tylko bez nikogo (FIS; runda 11, Marek): ls bez częstotliwości i stanowiska, bez linii ATIS. Obsadzona
// nigdy nie traci częstotliwości: samo ID czytałoby się jak „nikt”.
const bare = (lb) => !lb.extra && !lb.ls.some((l) => l.fq || l.by);
// odmiany do ułożenia (placeLabels): APP/TWR/FIS pełna i skrócona, sektor ACC (small = false) tylko pełna, bez nikogo
// samo ID; plakietka z samym ATIS (TWR/A, wieża offline) tylko pełna – skrócona zgubiłaby częstotliwość ATIS
export const lblVariants = (lb, small = true) => (bare(lb) ? [2] : small && lb.ls.some((l) => l.fq || l.by) ? [0, 1] : [0]);
// kolejność układania (najpierw mniejsza): plakietki APP i TWR (stoją w środku swojej przestrzeni, wolno je tylko
// lekko odsunąć), potem sektory ACC (schodzą z plakietek), FIS z częstotliwością, na końcu samo ID bez nikogo
const PRIO = { app: [0, 3], twr: [0.5, 3.5], acc: [1, 1], fis: [2, 4] };
export const lblPrio = (kind, lb) => PRIO[kind][bare(lb) ? 1 : 0];
export function lblHtml(lb, v = 0) {
  const attrs = `${lb.k ? ` data-k="${esc(lb.k)}"` : ""}${lb.icao ? ` data-icao="${esc(lb.icao)}" tabindex="0" role="button"` : ""} data-rt="${esc(lb.rt)}"`;
  const cls = `rb-lbl ${lb.cls} ${lb.state}${v ? " cmp" : ""}`;
  // ID w skróconej i samym ID: z częstotliwością bez rodzaju (WA S 135.930), bez niej pełne – samo „GD” czytałoby się
  // jak lotnisko
  const cid = lb.ls[0]?.fq ? shortId(lb.id) : lb.id;
  if (v === 2) return `<div class="${cls}"${attrs}><b class="rb-id">${esc(cid)}</b></div>`;
  const fq = lb.ls[0]?.fq ? `<span class="rb-fq">${esc(lb.ls[0].fq)}</span>` : "";
  // skrócona: kto obsługuje (inny niż stanowisko etykiety) przed częstotliwością – skrótem, a bez częstotliwości pełną
  // nazwą zamiast pustej linii
  const b0 = String(lb.ls[0]?.by || "").replace(/^\u2191/, "");
  const by = b0 ? `<i class="rb-by">\u2191${esc(fq ? shortId(b0) : b0)}</i>` : "";
  // skrócona plakietka TWR/A: litera ATIS-u za częstotliwością wieży (pełna ma całą linię ATIS)
  const code = lb.code ? `<b class="rb-code">${esc(lb.code)}</b>` : "";
  if (v === 1) return `<div class="${cls}"${attrs}><b class="rb-id">${esc(cid)}</b>${by}${fq}${code}</div>`;
  const more = lb.more ? `<i class="rb-more">+${lb.more}</i>` : "";
  return `<div class="${cls}"${attrs}><b class="rb-id">${esc(lb.id)}</b>${lb.ls.filter((l) => l.fq || l.by).map((l) => `<span class="rb-ln">${l.by ? `<i class="rb-by">${esc(l.by)}</i>` : ""}`
    + `${l.fq ? `<span class="rb-fq">${esc(l.fq)}</span>` : ""}</span>`).join("")}${more}${lb.extra || ""}</div>`;
}

// --- linijki etykiet ({fq, by}); x = {freq, nm}: częstotliwość (online albo z tablicy) i nazwa stanowiska. Właściciele
// (najwyżej dwaj) z częstotliwością, by = właściciel inny niż stanowisko etykiety; nikt → żadnej linijki (samo ID)
export const lblLines = (nominal, owners, x) => owners.slice(0, 2).map((o) => ({ fq: x.freq(o), by: o === nominal ? "" : x.nm(o) }));

// --- plakietki APP i TWR (0.13.0, Marek: „jak nikt nie siedzi, nie pokazuj tysiąca plakietek”): tylko zalogowani
// (plates z /api/radio/board), plakietka w środku obsługiwanych części TMA albo w środku CTR, bez linii do punktu i bez
// kropki. x = {freq, nm, on, who, pos, net}: częstotliwość, nazwa stanowiska, kontroler online, kto (dymek), opis
// stanowiska z tablicy, false = brak danych o zalogowanych
const range = (lo, hi) => `${lo ? flText(lo) : "GND"}\u2013${flText(hi)}`;
// APP: jedna plakietka na zalogowane stanowisko APP (dyrektor bez plakietki); tma = grupy TMA (części) z tablicy,
// flow = alarmy przepływu. Dymek: TMA (i części, gdy TMA ma kilka), stanowisko, kto, inne TMA, które obsługuje, alarmy
export function appPlate(p, x, tma = [], flow = null) {
  const byId = new Map(arr(tma).map((g) => [g.id, g]));
  const cov = arr(p.covers).map((id) => byId.get(id)).filter(Boolean);
  const mine = cov.filter((g) => g.tma === p.tma), all = arr(tma).filter((g) => g.tma === p.tma);
  const others = [...new Set(cov.filter((g) => g.tma !== p.tma).map((g) => g.tma))];
  const part = all.length > 1 ? (mine.length === all.length ? " \u2013 all parts" : ` \u2013 part ${mine.map((g) => x.nm(g.nominal)).join(", ")}`) : "";
  const lims = mine.length ? ` (${range(Math.min(...mine.map((g) => g.lo || 0)), Math.max(...mine.map((g) => g.hi || 0)))})` : "";
  const rt = [`${p.tma}${part}${lims}`, `Position: ${x.pos(p.owner)}`, nowText([p.owner], x),
    ...(others.length ? [`Also covers: ${others.join(", ")}`] : []),
    ...flowLines(flow?.tma?.[p.tma]), ...others.flatMap((t) => flowLines(flow?.tma?.[t], t))].join("\n");
  return { at: p.at, kind: "app", name: p.owner, lb: { cls: "app", state: "on", id: x.nm(p.owner),
    ls: [{ fq: p.frequency || x.freq(p.owner), by: "" }], rt } };
}
// TWR: wieża lotniska online (TWR i TWR/A) albo na TWR/A sam ATIS lotniska; ctr = grupa CTR z tablicy (stanowisko
// wieży, ATIS, kto ją przejmuje). Linia ATIS z literą tylko na TWR/A i tylko z ATIS online
export function twrPlate(p, ctr, x, twra = false) {
  const tw = arr(p.twr)[0] || null, nominal = ctr?.nominal || tw || `${p.icao}_TWR`;
  const ls = tw ? [{ fq: p.frequency || x.freq(tw), by: tw === nominal ? "" : x.nm(tw) }] : [];
  const acs = arr(p.atis)[0] || ctr?.atis || null, a = twra && acs ? x.on(acs) : null;
  const atl = a ? `<span class="rb-ln rb-atl"><i class="rb-by">ATIS</i><span class="rb-fq">${esc(x.freq(acs))}</span>`
    + `${a.atis_code ? `<b class="rb-code">${esc(a.atis_code)}</b>` : ""}</span>` : "";
  const cover = arr(ctr?.owners);
  const now = tw ? null : cover.length ? `Tower offline \u2013 covered by ${cover.map((o) => x.who(o) || o).join(", ")}` : "Tower offline";
  const atisLine = acs ? [`ATIS: ${x.pos(acs)}${x.on(acs) ? ` \u2013 online${x.on(acs).atis_code ? `, information ${x.on(acs).atis_code}` : ""}` : " \u2013 offline"}`] : [];
  const rt = groupTip({ nominal, owners: arr(p.twr), topdown: null }, `${p.id} \u00b7 ${p.icao}`, x, [...atisLine, "Click: AERODROME"], now);
  return { at: p.at, kind: "twr", name: p.icao, lb: { cls: "twr", state: tw ? "on" : "off", id: x.nm(nominal), ls, extra: atl,
    code: a?.atis_code || "", icao: p.icao, k: p.icao, rt } };
}
// Etykiety podglądu key (LOW, MID, HIGH): [{at: [lat, lon], kind, name, lb, dot?}]. Sektory ACC: jedna etykieta na
// stanowisko (groups z accGroups), gdy warstwa podglądu jest włączona; na LOW plakietki APP (warstwa APP), TWR (TWR:
// wieże online, TWR/A: także sam ATIS) i FIS. bd = /api/radio/board, x = jak w appPlate oraz dn (nazwa stanowiska ACC)
export function previewItems(bd, key, layers, groups, x) {
  const out = [], ly = bd?.layers?.[key];
  if (layers.has(key.toLowerCase())) {
    arr(groups).forEach((g) => { if (g.at) out.push({ at: g.at, kind: "acc", name: g.owner, lb: { ...accLabel(g, x.dn(g.owner), x),
      rt: accTip(g, `${x.dn(g.owner)} \u00b7 ${key}${ly?.label ? ` ${ly.label}` : ""}`, x, bd.flow) } }); });
  }
  if (key !== "LOW") return out;
  if (layers.has("app")) arr(bd.plates?.app).forEach((p) => { if (p.at) out.push(appPlate(p, x, bd.tma, bd.flow)); });
  const twra = layers.has("twra");
  if (twra || layers.has("twr")) {
    const ctr = new Map(arr(bd.twr).map((g) => [g.id, g]));
    arr(bd.plates?.twr).forEach((p) => { if (p.at && arr(p.layers).includes(twra ? "twra" : "twr")) out.push(twrPlate(p, ctr.get(p.id), x, twra)); });
  }
  if (layers.has("fis")) {
    arr(bd.fis).forEach((g) => {
      if (!g.at) return;
      out.push({ at: g.at, kind: "fis", name: g.nominal, dot: "fis", lb: { cls: "fis", state: g.owners.length ? "on" : "off", id: x.nm(g.nominal),
        ls: lblLines(g.nominal, g.owners, x), more: Math.max(0, g.owners.length - 2), rt: groupTip(g, `${g.id} (up to ${flText(g.hi)})`, x) } });
    });
  }
  return out;
}
// znaczniki pod etykietami (SVG): etykieta ACC albo FIS odsunięta dalej niż o pół swojego rozmiaru – cienka linia do
// punktu; FIS z kropką w punkcie; plakietki APP i TWR bez linii i bez kropki. moves z placeLabels, sizes = rozmiar
// wybranej odmiany {w, h}, pts = punkty w pikselach
export function marksSvg(items, moves, sizes, pts) {
  return items.map((it, i) => {
    if (it.kind === "app" || it.kind === "twr") return "";
    const { dx, dy } = moves[i], { w, h } = sizes[i], [x, y] = pts[i];
    let m = it.dot ? `<circle class="rb-dot ${it.dot}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2"/>` : "";
    if (Math.abs(dx) > w / 2 + 2 || Math.abs(dy) > h / 2 + 2) {
      const ex = Math.max(x + dx - w / 2, Math.min(x, x + dx + w / 2)), ey = Math.max(y + dy - h / 2, Math.min(y, y + dy + h / 2));
      m += `<path class="rb-lead" d="M${x.toFixed(1)},${y.toFixed(1)}L${ex.toFixed(1)},${ey.toFixed(1)}"/>`;
    }
    return m;
  }).join("");
}
// Czerwone tło (0.13.0, Marek): przestrzeń z ograniczeniem przepływu albo z zajętością ponad 80 % dopuszczalnej –
// sektor ACC na podglądzie swojej warstwy (wycinki jego litery na wysokości podglądu: slices = sliceAt) i TMA na LOW
// (kształty z kluczem TMA: tmaGeo), także bez nikogo. Kształty jednej przestrzeni sumowane (dissolve.js, w pamięci wg
// wersji danych i wycinków): jedna czerwona granica wokół całej TMA, bez granic jej wycinków; błąd sumy – same
// wypełnienia (fb). Wynik [{id, kind: "acc" | "tma", geom: MultiPolygon | null, shapes: [geometria], rt}]
export function flowAreas(bd, key, slices, tmaGeo, x, ver = "") {
  const fl = bd?.flow || {}, out = [];
  const add = (id, kind, k, shapes, rt) => {
    const u = dissolve(`rbflow|${ver}|${k}`, shapes);
    out.push({ id, kind, geom: u?.geometry || null, shapes, rt });
  };
  arr(bd?.sectors).forEach((s) => {
    const al = arr(fl.sectors?.[s.id]), sl = s.layer === key && al.length ? arr(slices).filter((a) => a.letter === s.letter) : [];
    if (sl.length) add(s.id, "acc", `${s.id}|${sl.map((a) => `${a.name}:${a.lo}`).sort().join(",")}`, sl.map((a) => a.geometry),
      [`Sector ${s.id} \u00b7 ${key}`, nowText(s.owner ? [s.owner] : [], x), ...flowLines(al)].join("\n"));
  });
  if (key !== "LOW") return out;
  Object.entries(fl.tma || {}).forEach(([t, al]) => {
    const sh = arr(tmaGeo).filter((g) => g.tma === t);
    const own = [...new Set(arr(bd.tma).filter((g) => g.tma === t && g.owners?.length).map((g) => g.owners[0]))];
    if (sh.length && arr(al).length) add(t, "tma", `tma|${t}|${sh.length}`, sh.map((g) => g.geometry), [t, nowText(own, x), ...flowLines(al)].join("\n"));
  });
  return out;
}
// warstwa SVG czerwonego tła: jedna ścieżka na przestrzeń (klasa flow, dymek z powodem); po błędzie sumy wycinki bez
// granic (fb)
export const flowSvg = (areas, P) => (areas.length ? `<g class="rb-flow">${areas.map((a) => `<path class="flow ${a.kind}${a.geom ? "" : " fb"}"`
  + ` data-rt="${esc(a.rt)}" d="${a.geom ? pathAll(a.geom, P) : a.shapes.map((g) => pathOf(g, P)).join("")}"/>`).join("")}</g>` : "");

export default {
  mount(root) {
    // siatka wg szkicu: podglądy, przyciski warstw (rzędy z grid.buttons), okienka (rb-cells: wskaźniki, BERLIN, FIR-y),
    // stan danych i legenda; miejsca i szerokości kolumn ustawia renderLayout z części stałej (do tego czasu ukryte)
    const el = h(`<div class="rb">
      <div class="rb-atis" aria-label="ATIS"><div class="rb-atis-in"></div></div>
      <div class="rb-grid">
        ${MAPS.map(panelHtml).join("")}
        <div class="rb-btns"></div>
        <div class="rb-cells"></div>
        <div class="rb-status"></div>
        <div class="rb-legend"><span title="Staffed airspace (EPWW and neighbour ACC sectors): dark area. EPWW ACC sectors: one area and one label (position, frequency) per position; a boundary only where the controlling position changes. Neighbour box: white with the frequency of the controller covering it."><i class="rb-sw on"></i>staffed</span><span title="Unstaffed airspace: light grey area. APP and TWR plates only for stations online; FIS without anyone online: ID only, no frequency (position and frequency in the tooltip); neighbour box: dark grey, ID and limits only; nobody in the whole FIR \u2013 ADVISORY ${ADVISORY_FQ} under its name"><i class="rb-sw off"></i>unstaffed</span><span title="Flow alert: red area \u2013 flow restriction now or occupancy over 80 % of capacity (ACC sector on its level preview, TMA on LOW)"><i class="rb-sw flow"></i>flow alert</span><span title="TMA boundary (APP layer)"><i class="rb-ln-sw tma"></i>TMA</span><span title="CTR boundary (TWR layers)"><i class="rb-ln-sw ctr"></i>CTR</span></div>
        <div class="rb-loa" role="dialog" aria-label="LOA" hidden></div>
      </div>
      <div class="rb-tip" hidden></div>
    </div>`);
    root.append(el);
    const $ = (s) => el.querySelector(s);
    const tip = $(".rb-tip"), loaBox = $(".rb-loa");

    let layers = readLayers(), cut = readCut();
    // poziom przekroju LOW wyrównany do suwaka (adres i pamięć przeglądarki mogą mieć dowolny FL095–FL335)
    const lowCut = () => cutAt(cut, cutRange(d?.layers?.LOW));
    let d = null, geo = null, geoVer = "", err = "", border = null, noBorder = false, timer = null, loading = false, lastLoad = 0;
    // FIR, którego LOA jest otwarte (panel .rb-loa)
    let loaFir = null;
    const maps = Object.fromEntries(MAPS.map((m) => {
      const p = el.querySelector(`.rb-panel[data-map="${m.key}"]`);
      return [m.key, { ...m, el: p, svg: p.querySelector("svg"), lbls: p.querySelector(".rb-lbls"), free: p.querySelector(".rb-free") }];
    }));

    // --- nazwy i częstotliwości
    const nm = (cs) => (String(cs).startsWith("EP") ? displayName(cs).replace(/^EPWW /, "") : posName(cs));
    const on = (cs) => d?.online?.[cs];
    const freqOf = (cs) => on(cs)?.frequency || d?.pos?.[cs]?.frequency || "";
    const who = (cs) => {
      const o = on(cs);
      return o ? `${o.callsign} ${o.frequency} – ${o.name || "?"} (CID ${o.cid ?? "?"})${o.logon_time ? `, since ${utcHhmm(o.logon_time)}` : ""}` : "";
    };
    const posLine = (cs) => `${cs}${d?.pos?.[cs]?.name ? ` · ${d.pos[cs].name}` : ""} ${d?.pos?.[cs]?.frequency || ""}`.trim();

    // --- pasek ATIS: zawsze na miejscu i tej samej wysokości (jedna linia); przycisk ATIS chowa tylko treść
    // (visibility), więc podglądy pod nim nie zmieniają rozmiaru ani przy przełączaniu, ani gdy ATIS-y się logują
    function renderAtis() {
      const box = $(".rb-atis"), off = !layers.has("atis");
      box.classList.toggle("off", off);
      box.firstElementChild.setAttribute("aria-hidden", String(off));
      if (!d) return;
      box.firstElementChild.innerHTML = d.atis.map((a) => {
        const o = on(a.callsign), fq = freqOf(a.callsign) || "—";
        const rt = [posLine(a.callsign), o ? `Online: ${who(a.callsign)}${o.atis_code ? `\nInformation ${o.atis_code}` : ""}` : "ATIS offline",
          ...(o?.text_atis || []).slice(0, 6), "Click: AERODROME"].join("\n");
        return `<button type="button" class="rb-at ${o ? "on" : "off"}" data-icao="${esc(a.icao)}" data-rt="${esc(rt)}">`
          + `<span class="rb-ati">${esc(a.callsign.replace(/_ATIS$/, "").replace(/_/g, " "))}</span><span class="rb-fq">${esc(fq)}</span>`
          + `${o?.atis_code ? `<span class="rb-code">${esc(o.atis_code)}</span>` : ""}</button>`;
      }).join("") || `<span class="rb-none">No ATIS positions.</span>`;
    }

    // --- siatka strony (część stała grid): szerokości kolumn, miejsca podglądów, przycisków, stanu i legendy. Tylko gdy
    // zmieni się układ (nowa wersja danych): przy zwykłym odświeżeniu nic się nie przesuwa
    let layKey = "";
    function renderLayout() {
      const g = d?.grid;
      if (!g?.cols) return;
      const key = JSON.stringify(g);
      if (key === layKey) return;
      layKey = key;
      const grid = $(".rb-grid");
      grid.style.gridTemplateColumns = gridTracks(g.tracks);
      grid.style.gridTemplateRows = `repeat(${Number(g.rows) || 21}, minmax(0, 1fr))`;
      MAPS.forEach((m) => { if (g.maps?.[m.layer]) maps[m.key].el.style.gridArea = gridArea(g.maps[m.layer]); });
      if (g.status) $(".rb-status").style.gridArea = gridArea(g.status);
      if (g.legend) $(".rb-legend").style.gridArea = gridArea(g.legend);
      $(".rb-btns").innerHTML = buttonRows(g.buttons).map((r) => `<div class="rb-brow" style="grid-area: ${gridArea(r)}">`
        + r.ids.map((id) => LAYERS.find((l) => l.id === id)).map((l) => `<button type="button" data-ly="${l.id}" title="${esc(l.tip)}" aria-pressed="false">${esc(l.label)}</button>`).join("")
        + "</div>").join("");
      grid.classList.add("laid");
    }
    // --- okienka: wskaźniki, BERLIN, nazwy FIR-ów i okienka sąsiadów (firHtml); kto i częstotliwości z tablicy
    const cx = () => ({ who, pos: posLine, freq: freqOf, sel: loaFir, net: d?.net?.ok !== false });
    function renderCells() {
      if (!d?.grid?.cols) return;
      const x = cx();
      $(".rb-cells").innerHTML = arr(d.indicators).map((i) => indicatorHtml(i, x)).join("")
        + (d.berlin?.col ? berlinHtml(d.berlin) : "") + arr(d.firs).map((f) => firHtml(f, x)).join("");
    }

    // --- podglądy
    // etykiety, plakietki i dymki podglądu (previewItems, flowAreas): częstotliwości, nazwy i kto z tablicy
    const px = () => ({ freq: freqOf, nm, on, who, pos: posLine, net: d?.net?.ok !== false, dn: displayName });

    function renderMap(m) {
      const p = m.el, W = p.clientWidth, H = p.clientHeight;
      if (!geo || !d || W < 40 || H < 40) return;
      const pr = p.getBoundingClientRect(), fr = m.free.getBoundingClientRect();
      const { P } = projection(border, { x: fr.left - pr.left, y: fr.top - pr.top, w: fr.width, h: fr.height }, 0.03,
        m.key === "MID" ? "bottom" : "middle");
      const ft = m.key === "LOW" ? lowCut() * 100 : LEVEL_FT[m.key];
      const accs = sliceAt(geo.acc, ft), groups = accGroups(accs, d.sectors, m.key, geoVer);
      const low = m.key === "LOW", x = px();
      const g = (cls, list) => `<g class="${cls}">${list.map((x) => `<path d="${pathOf(x.geometry, P)}"/>`).join("")}</g>`;
      const twrOn = layers.has("twr") || layers.has("twra");
      // sąsiedzi (0.12.5, Marek): sektory ACC na wysokości podglądu (jak EPWW: jasnoszare nieobsadzone, ciemne obsadzone –
      // obsadzone rysowane na końcu, nad nieobsadzonymi), na LOW także TMA i CTR lotnisk sąsiadów przy granicy FIR EPWW
      const nbOn = d.nb || {}, nbAll = geo.nb || [];
      const nbAcc = sliceAt(nbAll.filter((a) => a.kind === "acc"), ft).sort((a, b) => !!nbOn[a.id] - !!nbOn[b.id]);
      const nbTma = low && layers.has("app") ? nbAll.filter((a) => a.kind === "app") : [];
      const nbCtr = low && twrOn ? nbAll.filter((a) => a.kind === "twr") : [];
      m.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      m.svg.setAttribute("width", W);
      m.svg.setAttribute("height", H);
      // kolejność (kolory z pliku sektora, radio.css): tło FIR-ów, sąsiedzi, FIR EPWW nieobsadzony, obszary stanowisk
      // ACC (obsadzone: ciemne, pełne – pod nimi nic nie ginie), czerwone tło alarmów przepływu (sektory ACC warstwy,
      // na LOW także TMA – zawsze, bez względu na warstwy i obsadę), granice TMA/CTR/FIS EPWW i sąsiadów, granica FIR EPWW
      m.svg.innerHTML = g("rb-firs", geo.firs)
        + `<g class="rb-nbacc">${nbAcc.map((a) => `<path class="${nbOn[a.id] ? "on" : "off"}" d="${pathOf(a.geometry, P)}"/>`).join("")}</g>`
        + `<path class="rb-land" d="${pathOf(geo.border, P)}"/>`
        // obszar stanowiska (bez granic między jego sektorami); po błędzie sumy same wypełnienia wycinków
        + `<g class="rb-accg">${groups.map((a) => (a.geom ? `<path data-k="${esc(a.owner)}" class="st" d="${pathAll(a.geom, P)}"/>`
          : a.slices.map((sl) => `<path data-k="${esc(a.owner)}" class="st fb" d="${pathOf(sl.geometry, P)}"/>`).join(""))).join("")}</g>`
        + flowSvg(flowAreas(d, m.key, accs, geo.tma, x, geoVer), P)
        + (low && layers.has("fis") ? g("rb-fisg", geo.fis) : "")
        + g("rb-tmag nb", nbTma) + g("rb-ctrg nb", nbCtr)
        + (low && layers.has("app") ? g("rb-tmag", geo.tma) : "")
        + (low && twrOn ? g("rb-ctrg", geo.ctr) : "")
        + `<path class="rb-border" d="${pathOf(geo.border, P)}"/>`;
      renderTitle(m);
      // etykiety: wstawiamy wszystkie odmiany, mierzymy, układamy (ważniejsze pierwsze), zostawiamy wybraną odmianę
      const items = previewItems(d, m.key, layers, groups, x).map((it) => ({ ...it, prio: lblPrio(it.kind, it.lb) }))
        .sort((a, b) => a.prio - b.prio);
      const vs = items.map((it) => lblVariants(it.lb, it.kind !== "acc"));
      m.lbls.innerHTML = items.map((it, i) => vs[i].map((v) => lblHtml(it.lb, v)).join("")).join("");
      const els = [...m.lbls.children];
      let ei = 0;
      const vars = vs.map((v) => els.slice(ei, (ei += v.length)));
      const sz = (e) => ({ w: e.offsetWidth, h: e.offsetHeight });
      const pts = items.map((it) => P([it.at[1], it.at[0]]));
      // przeszkoda: tytuł podglądu (współrzędne w panelu)
      const rel = (e) => { const r = e.getBoundingClientRect(); return { x0: r.left - pr.left - 2, y0: r.top - pr.top - 2, x1: r.right - pr.left + 2, y1: r.bottom - pr.top + 2 }; };
      const obstacles = [...p.querySelectorAll(".rb-title")].filter((e) => e.offsetWidth && e.offsetHeight).map(rel);
      // obrysy, których etykiety ACC i FIS nie zasłaniają (runda 11, Marek): TMA na warstwie APP, CTR na TWR i TWR/A;
      // plakietki APP i TWR stoją na nich w środku (labelOpts)
      const shapes = low ? [...(layers.has("app") ? geo.tma : []), ...(twrOn ? geo.ctr : []), ...nbTma, ...nbCtr] : [];
      const shapeKind = !shapes.length ? "" : twrOn ? "twr" : "app";
      const cover = shapes.length ? coverGrid(shapes.flatMap((a) => ringsOf(a.geometry).map((r) => r.map(P))), W, H) : null;
      const moves = placeLabels(items.map((it, i) => {
        const [full, ...alts] = vars[i].map(sz);
        return { x: pts[i][0], y: pts[i][1], ...full, alts, ...labelOpts(it.kind, { on: it.lb.state !== "off", fq: !!it.lb.ls?.[0]?.fq, shapes: shapeKind }) };
      }), { x: 2, y: 2, w: W - 4, h: H - 4 }, { obstacles, cover, near: cover ? 40 : 26 });
      // wybrana odmiana na swoim miejscu; ACC i FIS odsunięte daleko z cienką linią do punktu, FIS z kropką (marksSvg)
      const sizes = items.map((it, i) => {
        const { dx, dy, v } = moves[i];
        vars[i].forEach((e, j) => { if (j !== v) e.remove(); });
        const e = vars[i][v], w = e.offsetWidth, hh = e.offsetHeight, [x0, y0] = pts[i];
        e.style.left = `${Math.round(x0 + dx - w / 2)}px`;
        e.style.top = `${Math.round(y0 + dy - hh / 2)}px`;
        return { w, h: hh };
      });
      const marks = marksSvg(items, moves, sizes, pts);
      if (marks) m.svg.insertAdjacentHTML("beforeend", `<g class="rb-marks">${marks}</g>`);
    }
    // tytuł w lewym górnym rogu podglądu (LOW: nad mapą, z suwakiem wysokości; radio.css)
    function renderTitle(m) {
      const t = m.el.querySelector(".rb-title");
      const ly = d?.layers?.[m.key];
      // szkielet raz: suwak LOW powstały od nowa przy każdym rysowaniu zgubiłby przeciąganie i fokus
      if (!t.firstChild) {
        t.innerHTML = `<span class="rb-tk">${m.key}</span> <span class="rb-tl"></span>` + (m.key !== "LOW" ? ""
          : `<span class="rb-lvl"><input type="range" class="rb-cut" aria-label="LOW cross-section level"><span class="rb-ticks" aria-hidden="true"></span></span>`
            + `<output class="rb-cutv"></output>`);
      }
      t.querySelector(".rb-tl").textContent = ly?.label || "";
      if (m.key !== "LOW" || !geo) return;
      // suwak wysokości (runda 11, Marek): kreski pod suwakiem = granice wycinków ACC, na których zmieniają się kształty
      const r = cutRange(ly), v = lowCut();
      const b = cutBounds(geo.acc.filter((s) => s.lo < (ly?.upper_ft ?? 33500) && s.hi > (ly?.lower_ft ?? 9500)), ly);
      const c = cutBand(b, v), inp = t.querySelector(".rb-cut");
      Object.assign(inp, { min: r.min, max: r.max, step: r.step });
      if (Number(inp.value) !== v) inp.value = v;
      inp.setAttribute("aria-valuetext", flText(v * 100));
      inp.title = `LOW cross-section at ${flText(v * 100)}: sector shapes of the band ${flText(c.lo)}–${flText(c.hi)}`
        + `\nTicks: ACC slice limits (shapes change there); arrow keys: 500 ft steps`;
      t.querySelector(".rb-cutv").textContent = flText(v * 100);
      t.querySelector(".rb-ticks").innerHTML = b.filter((x) => x / 100 > r.min && x / 100 <= r.max)
        .map((x) => `<i style="left:${(((x / 100 - r.min) / Math.max(1, r.max - r.min)) * 100).toFixed(1)}%"></i>`).join("");
    }
    // włączona warstwa: jasne pole i ciemny napis, wyłączona: szare pole i jasny napis (kolor, bez pogrubienia)
    function renderButtons() {
      el.querySelectorAll(".rb-btns button[data-ly]").forEach((b) => {
        b.classList.toggle("on", layers.has(b.dataset.ly));
        b.setAttribute("aria-pressed", String(layers.has(b.dataset.ly)));
      });
    }
    function renderStatus() {
      const s = $(".rb-status");
      const n = d ? controllersOn(d.online) : 0;
      const net = d?.net;
      s.innerHTML = !d ? (err ? `<span class="error">${esc(err)}</span>` : "Loading…")
        : `${net?.ok ? `Updated ${esc(utcHhmm(net.updated))} · ${n} on the board` : `<span class="error">${esc(net?.error || "No data")}</span>`}`
          + (noBorder ? ` <span class="error">No FIR EPWW boundary: previews without the FIR outline.</span>` : "")
          + (err ? ` <span class="error">${esc(err)}</span>` : "");
    }
    let raf = 0;
    // jeden błąd (np. dziwne dane) nie zatrzymuje reszty strony
    const safe = (f, ...a) => { try { f(...a); } catch (e) { console.error("RADIO", e); } };
    function renderAll() {
      cancelAnimationFrame(raf);
      raf = 0;
      safe(renderLayout);
      safe(renderButtons);
      safe(renderAtis);
      if (d) {
        safe(renderCells);
        Object.values(maps).forEach((m) => safe(renderMap, m));
      }
      safe(renderStatus);
    }
    const later = () => { if (!raf) raf = requestAnimationFrame(renderAll); };

    // --- dane
    const visible = () => el.isConnected && !!el.closest(".view.active") && document.visibilityState !== "hidden";
    async function load() {
      if (loading) return;
      loading = true;
      try {
        // geometria raz, potem tylko gdy zmieni się wersja danych (np. po imporcie nowych danych sektorów)
        const r = await api(`/api/radio/board${geo && geoVer ? `?have=${encodeURIComponent(geoVer)}` : "?geo=1"}`);
        if (r.geo) {
          geo = r.geo;
          geoVer = r.ver || "";
          const b = bboxOrDefault(bboxOf(geo.border));
          noBorder = !b;
          border = b || EPWW_BBOX;
        } else if (geo && r.ver !== geoVer) {
          // nowa wersja danych bez geometrii w odpowiedzi: pobierzemy ją zaraz (?geo=1)
          geoVer = "";
          setTimeout(load, 0);
        }
        d = r;
        // poziom z adresu albo starej pamięci przeglądarki (fl302, fl335) wyrównany do suwaka: od razu też w adresie
        const was = cut;
        cut = lowCut();
        if (cut !== was) { save(); remember("radio", argOf(layers, cut), { replace: true }); }
        err = "";
        lastLoad = Date.now();
      } catch (e) {
        err = `RADIO: ${e.message}`;
      } finally {
        loading = false;
      }
      renderAll();
    }
    const tick = () => { if (visible()) load(); };
    // powrót do karty przeglądarki: dane mogą mieć do 30 s – odświeżamy od razu
    const onVis = () => { if (visible() && Date.now() - lastLoad > REFRESH_MS) load(); };
    document.addEventListener("visibilitychange", onVis);
    loadDisplayNames().then(() => { if (d) later(); });
    load();
    timer = setInterval(tick, REFRESH_MS);
    const ro = new ResizeObserver(later);
    ro.observe($(".rb-grid"));

    // --- warstwy i przekrój: zapamiętane w przeglądarce, każda zmiana to krok do cofnięcia (#radio/atis,low/fl300)
    const save = () => { lsSet(LS_LAYERS, JSON.stringify([...layers])); lsSet(LS_CUT, String(cut)); };
    const apply = (arg) => {
      const a = parseArg(arg);
      let changed = false;
      if (a.layers && argOf(a.layers, cut) !== argOf(layers, cut)) { layers = a.layers; changed = true; }
      if (a.cut && a.cut >= 95 && a.cut <= 335 && a.cut !== cut) { cut = cutAt(a.cut, cutRange(d?.layers?.LOW)); changed = true; }
      if (changed) { save(); renderAll(); }
    };
    // przyciski warstw powstają z układu (renderLayout): kliknięcie łapiemy na kontenerze
    el.querySelector(".rb-btns").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-ly]");
      if (!b) return;
      const s = new Set(layers);
      if (s.has(b.dataset.ly)) s.delete(b.dataset.ly); else s.add(b.dataset.ly);
      // TWR/A (wieże i ATIS) zawiera TWR: włączenie jednej z nich wyłącza drugą
      if (s.has(b.dataset.ly) && b.dataset.ly === "twra") s.delete("twr");
      if (s.has(b.dataset.ly) && b.dataset.ly === "twr") s.delete("twra");
      layers = s;
      save();
      renderAll();
      remember("radio", argOf(layers, cut));
    });
    // suwak wysokości LOW: przeciąganie rysuje od razu tylko podgląd LOW; poziom do adresu (krok do cofnięcia) po
    // puszczeniu suwaka, a seria strzałek z klawiatury to jeden krok
    let rafLow = 0, cutT = 0;
    maps.LOW.el.addEventListener("input", (e) => {
      if (!e.target.matches(".rb-cut")) return;
      cut = Number(e.target.value);
      save();
      if (!rafLow) rafLow = requestAnimationFrame(() => { rafLow = 0; safe(renderMap, maps.LOW); });
    });
    maps.LOW.el.addEventListener("change", (e) => {
      if (!e.target.matches(".rb-cut")) return;
      clearTimeout(cutT);
      cutT = setTimeout(() => remember("radio", argOf(layers, cut)), 600);
    });
    // lotnisko z paska ATIS albo etykiety TWR → AERODROME (krok do cofnięcia)
    el.addEventListener("click", (e) => {
      const a = e.target.closest(".rb-at[data-icao], .rb-lbl.twr[data-icao]");
      if (a) navigate("aerodrome", a.dataset.icao);
    });
    // etykieta TWR z klawiatury (tabindex, role=button): Enter albo spacja
    el.addEventListener("keydown", (e) => {
      const a = e.target.closest?.(".rb-lbl.twr[data-icao]");
      if (a && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); navigate("aerodrome", a.dataset.icao); }
    });

    // --- LOA: nazwa FIR-u sąsiada otwiera panel (drugie kliknięcie, ✕ albo Esc zamyka); bez kroku w historii
    const markLoa = () => el.querySelectorAll(".rb-fir[data-fir]").forEach((x) => x.classList.toggle("sel", x.dataset.fir === loaFir));
    const radioOf = (cs) => d?.pos?.[cs]?.name || "";
    // strona strony, po której leży FIR (kolumna jego nazwy w siatce)
    const sideOf = (fir) => {
      const f = arr(d?.firs).find((x) => x.fir === fir);
      return f && Number(f.name?.col) > (Number(d?.grid?.cols) || 13) / 2 ? "right" : "left";
    };
    function closeLoa() {
      loaFir = null;
      loaBox.hidden = true;
      loaBox.innerHTML = "";
      markLoa();
    }
    // panel po przeciwnej stronie niż kliknięty FIR (okienka tej strony zostają widoczne: inny FIR jednym kliknięciem)
    async function openLoa(fir, title, side) {
      if (loaFir === fir) return closeLoa();
      loaFir = fir;
      markLoa();
      loaBox.classList.toggle("at-left", side === "right");
      loaBox.hidden = false;
      loaBox.innerHTML = loaHtml(fir, title, null, radioOf, { loading: true });
      let html;
      try {
        const data = await loadLoa();
        html = loaHtml(fir, title, data?.firs?.[fir] || null, radioOf);
      } catch (e) {
        html = loaHtml(fir, title, null, radioOf, { msg: e.message || "LOA data unavailable" });
      }
      // w międzyczasie zamknięty albo otwarty inny FIR
      if (loaFir !== fir) return;
      loaBox.innerHTML = html;
      loaBox.querySelector(".rb-loa-b").scrollTop = 0;
    }
    el.addEventListener("click", (e) => {
      const hd = e.target.closest(".rb-fir[data-fir]");
      if (hd) openLoa(hd.dataset.fir, hd.dataset.title || "", sideOf(hd.dataset.fir));
    });
    el.addEventListener("keydown", (e) => {
      const hd = e.target.closest?.(".rb-fir[data-fir]");
      if (hd && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openLoa(hd.dataset.fir, hd.dataset.title || "", sideOf(hd.dataset.fir)); }
      if (e.key === "Escape" && !loaBox.hidden) { e.preventDefault(); closeLoa(); }
    });
    loaBox.addEventListener("click", (e) => {
      if (e.target.closest(".rb-loa-x")) return closeLoa();
      const doc = e.target.closest("button[data-coord]");
      if (doc) navigate("coordination", "docs/" + doc.dataset.coord);   // COORDINATION › DOKUMENTY z tym LOA
    });
    // filtr: wiersze tabel i zasady zawierające wpisany tekst; sekcje bez trafień znikają
    loaBox.addEventListener("input", (e) => {
      if (!e.target.matches(".rb-loa-q")) return;
      const t = e.target.value.trim().toLowerCase();
      const items = [...loaBox.querySelectorAll("[data-f]")];
      items.forEach((x) => { x.hidden = !!t && !x.dataset.f.includes(t); });
      loaBox.querySelectorAll(".rb-loa-sec").forEach((sec) => { sec.hidden = !!t && !sec.querySelector("[data-f]:not([hidden])"); });
      loaBox.querySelector(".rb-loa-cnt").textContent = t ? `${items.filter((x) => !x.hidden).length} of ${items.length}` : "";
    });

    // --- dymek (jeden pływający, stałej szerokości – radio.css) i podświetlenie sektora pod etykietą. Miejsce: tipPos
    // (na prawo i pod kursorem, przy prawej i dolnej krawędzi okna po drugiej stronie kursora, zawsze 12 px od brzegu);
    // wysokość z treści, nic nie jest ucinane
    let tipFor = null;
    const moveTip = (e) => {
      const { left, top } = tipPos(e.clientX, e.clientY, tip.offsetWidth, tip.offsetHeight, window.innerWidth, window.innerHeight);
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    };
    const hl = (lbl, onOff) => {
      const k = lbl?.dataset.k;
      const svg = lbl?.closest(".rb-panel")?.querySelector("svg");
      if (k && svg && lbl.classList.contains("acc")) svg.querySelectorAll(`[data-k="${CSS.escape(k)}"]`).forEach((p) => p.classList.toggle("hl", onOff));
    };
    el.addEventListener("mouseover", (e) => {
      const t = e.target.closest("[data-rt]");
      if (t === tipFor) return;
      hl(tipFor, false);
      tipFor = t;
      if (!t) { tip.hidden = true; return; }
      // miejsce przed pomiarem: dymek w lewym górnym rogu okna ma swoją pełną szerokość, wysokość z nowej treści
      tip.style.left = tip.style.top = "0px";
      tip.textContent = t.dataset.rt;
      tip.hidden = false;
      moveTip(e);
      hl(t, true);
    });
    el.addEventListener("mousemove", (e) => { if (tipFor) moveTip(e); });
    el.addEventListener("mouseleave", () => { hl(tipFor, false); tipFor = null; tip.hidden = true; });

    return {
      activate(arg) {
        if (arg) apply(arg);
        // menu albo adres bez stanu: dopisujemy bieżące warstwy do adresu (bez nowego kroku)
        remember("radio", argOf(layers, cut));
        if (Date.now() - lastLoad > REFRESH_MS) load();
        else later();
      },
      destroy() {
        clearInterval(timer); clearTimeout(cutT); cancelAnimationFrame(rafLow); ro.disconnect();
        document.removeEventListener("visibilitychange", onVis);
      },
    };
  },
};

// podgląd: mapa (svg), wolne pole do rzutowania (rb-free: cały panel bez marginesu, LOW pod tytułem z suwakiem),
// etykiety i tytuł
function panelHtml(m) {
  return `<section class="rb-panel ${m.cls}" data-map="${m.key}"><svg class="rb-svg" aria-hidden="true"></svg>`
    + `<div class="rb-frame"><div class="rb-free"></div></div><div class="rb-lbls"></div><div class="rb-title"></div></section>`;
}
