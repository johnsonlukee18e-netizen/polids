// RADIO: jedna strona jak w PANDORZE. 0.13.1 (issue #25, Marek: "Przywróć stary styl strony RADIO") znów układ z 0.12.6:
// u góry jeden rząd – małe wskaźniki konfiguracji ACC GAT, APP GD, APP WA, APP KK, APP PO (żółta nazwa nad szarym polem),
// na prawo od nich ATIS-y polskich lotnisk (przycisk ATIS chowa tylko ich treść, nic się nie przesuwa); pod nim trzy
// kolumny: duży podgląd LOW ze stosami sąsiadów z zachodu (EDWW, pod nim BERLIN: WEST/EAST, czerwony napis =
// konfiguracja preferowana bez pasa z ATIS; EDUU, EDMM), z północy (ESAA) i z południa (LKAA), w środku przyciski
// warstw ATIS / LOW MID HIGH / APP / TWR / TWR/A / FIS, stan danych, legenda i mały podgląd MID, po prawej podgląd HIGH
// ze stosami UMKK, EYVL, UMMV, UKLV i LZBB. Jedyna zmiana wobec 0.12.6: podział okienek w stosach, ich granice i łączenie
// okienek jednego stanowiska wg szkicu Marka (0.13.0, data/seed/radio_layout.json, GET /api/radio/board: firs,
// indicators, berlin) – kafelek to sama częstotliwość (gdy ktoś go obsługuje) i ID w prawym górnym rogu, wysokości
// między kafelkami (stackGrid), stos zawsze tego samego rozmiaru.
// Sektory ACC na podglądach (runda 12, Marek): wycinki obsługiwane przez to samo stanowisko (kolejność przejmowania,
// ownership.json) jako jeden obszar z jedną etykietą (stanowisko i częstotliwość), granica tylko tam, gdzie zmienia
// się obsługujący; sektorów bez nikogo nie rysujemy (ramą zostaje granica FIR EPWW). FIS bez nikogo: samo ID (runda 11).
// Plakietki APP i TWR (0.13.0, Marek) tylko dla zalogowanych: jedna na stanowisko APP w środku części TMA, które
// obsługuje (WA APP, WA N APP i WA S APP – trzy), wieża w środku CTR (TWR/A także sam ATIS), bez linii do punktu;
// czerwone tło sektora ACC i TMA z ograniczeniem przepływu albo zajętością ponad 80 %; dymki stałej szerokości.
// LOW z suwakiem wysokości (FL095–FL330).
// Dane: GET /api/radio/board co 30 s (geometria raz, potem tylko po zmianie wersji danych `ver`, np. po imporcie nowych
// danych sektorów). Panel z wyciągiem z LOA EPWW z FIR-em sąsiada
// (GET /api/radio/loa), z przyciskiem do dokumentu w COORDINATION › DOKUMENTY i PDF-em w nowej karcie. Kliknięcie
// nagłówka stosu sąsiada (np. EDWW BREMEN) otwiera ten panel.
import { api, esc, h, lsGet, lsSet, navigate, remember } from "../api.js";
import { labelPoint } from "../coverage.js";
import { dissolve, pointIn } from "../dissolve.js";
import { displayName, loadDisplayNames, posName } from "../posname.js";
import { ADVISORY_FQ, DEFAULT_CUT, DEFAULT_LAYERS, EPWW_BBOX, LAYERS, LAYER_IDS, argOf, bboxOf, bboxOrDefault, controllersOn,
  coverGrid, cutAt, cutBand, cutBounds, cutRange, flText, labelOpts, limText, limTip, loaPlace, parseArg, pathAll, pathOf,
  placeLabels, projection, ringsOf, sliceAt, stackGrid, tipPos, utcHhmm } from "../radioboard.js";

const LS_LAYERS = "radio.layers", LS_CUT = "radio.cut";
const REFRESH_MS = 30000;
// MID i HIGH mają jeden kształt sektorów
const LEVEL_FT = { MID: 35000, HIGH: 40000 };
// podglądy (0.12.6): LOW po lewej ze stosami sąsiadów z zachodu, północy i południa, MID w środkowej kolumnie, HIGH po
// prawej ze stosami ze wschodu (side = map stosów z /api/radio/board)
const MAPS = [
  { key: "LOW", layer: "low", cls: "rb-low", side: "left" },
  { key: "MID", layer: "mid", cls: "rb-midmap", side: null },
  { key: "HIGH", layer: "high", cls: "rb-high", side: "right" },
];
// miejsce stosu sąsiada w panelu: strona FIR-u na mapie (at) → obszar ramki panelu (rb-top, rb-bot, rb-col) i kolejność
// w kolumnie z boku; BERLIN w kolumnie LOW zaraz pod stosem EDWW
const AREA = { n: "top", s: "bot", nw: "col", w: "col", sw: "col", ne: "col", e: "col", se: "col" };
const COL_ORDER = { nw: 0, w: 1, sw: 2, ne: 0, e: 1, se: 2 };
const BERLIN_AFTER = "EDWW";
// legenda czerwonego tła; bez danych o ograniczeniach przepływu (flow.ok false) przygaszona, z innym dymkiem
const FLOW_TIP = "Flow alert: red area \u2013 flow restriction now or occupancy over 80 % of capacity (ACC sector on its level preview, TMA on LOW)";
const FLOW_NA = "Flow data unavailable: red areas cannot be shown now";
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
  return `<div class="rb-loa-sec"><h4>${esc(from)} \u2192 ${esc(to)} <small>${rows.length}</small></h4>
    <table class="rb-loa-tab"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}
const loaList = (title, items) => (arr(items).length ? `<div class="rb-loa-sec"><h4>${esc(title)} <small>${items.length}</small></h4>
  <ul>${items.map((x) => `<li data-f="${esc(String(x).toLowerCase())}">${esc(x)}</li>`).join("")}</ul></div>` : "");

// fir, title: FIR sąsiada i jego nazwa z /api/radio/board; f: wpis z loa.json albo null (brak LOA z tym FIR-em, błąd: msg,
// jeszcze się wczytuje: loading); radio(cs): znak radiowy stanowiska, gdy LOA go nie podaje
export function loaHtml(fir, title, f, radio, { msg = "", loading = false } = {}) {
  const tr = arr(f?.transfers), out = tr.filter((t) => t.dir === "out"), inn = tr.filter((t) => t.dir === "in");
  const pdf = pdfPath(f?.pdf);
  // tytuł LOA podaje już FIR sąsiada (LOA EPWW – EDWW (Bremen)); bez LOA: FIR i jego nazwa z tablicy
  const head = `<div class="rb-loa-h"><b class="rb-loa-tag">LOA</b>${f ? "" : `<span class="rb-loa-fir"><b>${esc(fir)}</b> ${esc(title)}</span>`}`
    + (f ? `<span class="rb-loa-t" data-rt="${esc(f.title)}">${esc(f.title)}</span>` : "")
    + `<span class="rb-loa-sp"></span>`
    + (pdf ? `<button type="button" class="rb-loa-a" data-coord="${esc(fir)}" data-rt="Open the LOA in COORDINATION \u203a DOCUMENTS (\u2190 returns to RADIO)">COORDINATION \u203a</button>`
      + `<a class="rb-loa-a" href="${esc(encodeURI(pdf))}" target="_blank" rel="noopener" data-rt="Open the LOA PDF">PDF \u2197</a>` : "")
    + `<button type="button" class="rb-loa-x" aria-label="Close" data-rt="Close (Esc)">\u2715</button></div>`;
  if (!f) {
    return head + `<div class="rb-loa-b"><p class="${msg ? "error" : "hint"}">${msg ? esc(msg) : loading ? "Loading LOA\u2026"
      : `No EPWW LOA with ${esc(fir)} in PolIDS. All LOAs: COORDINATION \u203a DOCUMENTS.`}</p></div>`;
  }
  const pos = arr(f.positions).map((p) => `<tr data-f="${esc(Object.values(p).join(" ").toLowerCase())}">`
    + `<td class="${p.side === "EP" ? "ep" : "nb"}">${p.side === "EP" ? "EPWW" : esc(fir)}</td><td class="pcs">${esc(p.callsign)}</td>`
    + `<td>${esc(p.radio || radio(p.callsign))}</td><td class="cop">${esc(p.sector)}</td><td class="lvl">${esc(p.frequency)}</td>`
    + `<td class="cond">${esc(p.note)}</td></tr>`).join("");
  return head + `<div class="rb-loa-b">
    <div class="rb-loa-tools"><input type="search" class="rb-loa-q" placeholder="filter: COP, aerodrome, FL, sector\u2026" aria-label="LOA filter">
      <span class="rb-loa-cnt"></span><span class="rb-loa-n">transfers: ${out.length} from EPWW \u00b7 ${inn.length} to EPWW</span></div>
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

// --- wskaźniki u góry strony, BERLIN i stosy sąsiadów z /api/radio/board (0.13.1: stary styl, podział okienek wg
// szkicu). x: {who(cs), pos(cs), freq(cs), net, sel} – zalogowany i opis stanowiska z tablicy, false = brak danych
// o zalogowanych (bez ADVISORY i bez zer we wskaźnikach), FIR otwartego LOA
const onlineLine = (o) => `${o.callsign} ${o.frequency || ""} \u2013 ${o.name || "?"}`.replace(/  +/g, " ");
// wskaźnik (0.13.1: dużo mniejszy, w rzędzie u góry strony): mała żółta nazwa nad małym szarym polem z wartością (ALL+S,
// 2H+L+D, 2); w dymku znaczenie i liczone stanowiska. Wartość dłuższa niż pole (ACC GAT przy 4 i więcej stanowiskach
// ACC) od początku, z wielokropkiem na końcu (rb-indt)
export function indicatorHtml(i, x) {
  const ps = arr(i.positions);
  const rt = [`${i.id}${i.tip ? `: ${i.tip}` : ""}`, ...(x.net === false ? ["Now: no data"] : ps.length ? ps.map(onlineLine) : ["Nobody online"])].join("\n");
  const v = x.net === false ? "\u2013" : String(i.value ?? "0");
  return `<div class="rb-indc" data-rt="${esc(rt)}"><div class="rb-ind">${esc(i.id)}</div>`
    + `<div class="rb-indv"><span class="rb-indt">${esc(v)}</span></div></div>`;
}
// BERLIN: konfiguracja pasów Berlina w takim samym małym polu jak wskaźniki (w kolumnie LOW pod stosem EDWW); bez pasa
// z ATIS (preferred) czerwony napis. Bez danych o zalogowanych (x.net === false) albo bez konfiguracji: kreska jak we
// wskaźnikach – nie wiadomo, czy jest ATIS
export function berlinHtml(b, x = {}) {
  const cfg = x.net === false ? "" : b?.config || "", pref = !!cfg && !!b?.preferred;
  const tip = b?.tip || (x.net === false ? "ATIS unknown: no network data" : "");
  const rt = ["BERLIN: runway configuration of Berlin Brandenburg, WEST (runways 24) or EAST (runways 06)", tip,
    ...(pref ? ["Red text: preferred configuration, no runway in use from ATIS"] : [])].filter(Boolean).join("\n");
  return `<div class="rb-indc rb-ber" data-rt="${esc(rt)}"><div class="rb-blbl">BERLIN</div>`
    + `<div class="rb-bln${pref ? " pref" : ""}">${esc(cfg || "\u2013")}</div></div>`;
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
// kafelek jak na zdjęciu PANDORY (stos LKAA): obsadzony – jasne pole z szarą częstotliwością tego, kto go teraz obsługuje,
// i małym ID w prawym górnym rogu; bez nikogo – ciemne pole z samym ID; zawsze ten sam rozmiar (radio.css), połączony
// na swoich komórkach stosu. Granice nie na kafelku, tylko między kafelkami (markHtml) i w dymku. t: kafelek ze stackGrid
export function tileHtml(t, f, x) {
  const b = t.b, fq = b.owner ? b.frequency || x.freq(b.owner) : "";
  return `<div class="rb-box ${b.owner ? "on" : "off"}${b.merged ? " mrg" : ""}" data-box="${esc(b.id)}"`
    + ` style="grid-column: ${t.gc}; grid-row: ${t.gr}" data-rt="${esc(boxTip(b, f, x))}">`
    + `<span class="rb-id">${esc(b.label)}</span>${fq ? `<span class="rb-fq">${esc(fq)}</span>` : ""}</div>`;
}
// wysokości między kafelkami jak na szkicu i zdjęciu PANDORY (660, 365, 0), w kolumnie od lewej; dwie liczby – nowy
// ciąg okienek (EDUU OSE1 i HVL2): dolna granica kafelka nad kreską, pod nią górna granica kafelka pod spodem
const lvTip = (n) => (n >= 999 ? "UNL" : n > 0 ? flText(n * 100) : "GND");
export function markHtml(k) {
  const [a, b] = k.n, two = k.n.length > 1;
  const rt = two ? `${lvTip(a)}: lower limit of the box above\n${lvTip(b)}: upper limit of the box below` : lvTip(a);
  return `<div class="rb-bd" style="grid-column: ${k.gc}; grid-row: ${k.gr}" data-rt="${esc(rt)}"><i>${esc(String(a))}</i>`
    + `${two ? `<span class="rb-sep"></span><i>${esc(String(b))}</i>` : ""}</div>`;
}
// tory siatki stosu (stackGrid): kafelek stałej szerokości i wysokości, rzędy liczb stałej wysokości (radio.css)
const TRACK = { t: "var(--rb-th)", l0: "var(--rb-lv0)", l1: "var(--rb-lv1)", l2: "var(--rb-lv2)" };
// nagłówek stosu: żółty kod FIR-u i szara nazwa (kliknięcie: LOA EPWW z tym FIR-em); w dymku zalogowani tego FIR-u
export function firTip(f, x) {
  const on = arr(f.online);
  return [`${f.fir} ${f.title || ""}`.trim(),
    ...(x.net === false ? ["Online: no data"] : on.length ? on.map((o) => `Online: ${onlineLine(o)}`) : [`Nobody online \u2013 ADVISORY ${ADVISORY_FQ}`]),
    "Numbers between the boxes: vertical limits (FL)", `Click: LOA EPWW \u2013 ${f.fir}`].join("\n");
}
// stos sąsiada jak w 0.12.6: nagłówek, linia ADVISORY 122.800 (zawsze na miejscu, napis tylko, gdy w całym FIR-ze nikt
// nie obsługuje okienek – stos nie zmienia wysokości), pod nią kafelki i wysokości w siatce stackGrid
export function nbStackHtml(f, x) {
  const g = stackGrid(f), adv = !!f.advisory && x.net !== false;
  return `<div class="rb-nb" data-fir="${esc(f.fir)}"><div class="rb-nbh${x.sel === f.fir ? " sel" : ""}" role="button" tabindex="0"`
    + ` data-title="${esc(f.title || "")}" data-rt="${esc(firTip(f, x))}"><span class="rb-nbc">${esc(f.fir)}</span> ${esc(f.title || "")}</div>`
    + `<div class="rb-unicom">${adv ? `ADVISORY ${ADVISORY_FQ}` : ""}</div>`
    + `<div class="rb-sg" style="grid-template-columns: ${g.cols.map(() => "var(--rb-tw)").join(" ")}; grid-template-rows: ${g.rows.map((r) => TRACK[r]).join(" ")}">`
    + g.marks.map(markHtml).join("") + g.tiles.map((t) => tileHtml(t, f, x)).join("") + "</div></div>";
}

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
  // ATIS online: częstotliwość z sieci (jak na plakietce), offline: z listy stanowisk
  const ao = acs ? x.on(acs) : null;
  const atisLine = acs ? [`ATIS: ${x.pos(acs, ao ? x.freq(acs) : "")}${ao ? ` \u2013 online${ao.atis_code ? `, information ${ao.atis_code}` : ""}` : " \u2013 offline"}`] : [];
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
    // stary styl (0.12.6): rząd u góry (wskaźniki, na prawo od nich ATIS), pod nim [LOW + stosy sąsiadów]
    // [przyciski, stan, legenda, MID] [HIGH + stosy sąsiadów]; panel LOA nad siatką
    const el = h(`<div class="rb">
      <div class="rb-cfg"><div class="rb-inds"></div><div class="rb-atis" aria-label="ATIS"><div class="rb-atis-in"></div></div></div>
      <div class="rb-grid">
        ${MAPS.map((m) => (m.key === "MID" ? `<div class="rb-mid">
            <div class="rb-btns">${LAYERS.map((l) => `<button type="button" data-ly="${l.id}" data-rt="${esc(l.tip)}" aria-pressed="false">${esc(l.label)}</button>`).join("")}</div>
            <div class="rb-status"></div>
            <div class="rb-legend"><span data-rt="Staffed airspace (EPWW and neighbour ACC sectors): dark area. EPWW ACC sectors: one area and one label (position, frequency) per position; a boundary only where the controlling position changes. Neighbour box: light, with the frequency of the controller covering it."><i class="rb-sw on"></i>staffed</span><span data-rt="Unstaffed airspace: light grey area. APP and TWR plates only for stations online; FIS without anyone online: ID only, no frequency (position and frequency in the tooltip); neighbour box: dark, ID only; nobody in the whole FIR \u2013 ADVISORY ${ADVISORY_FQ} under its name"><i class="rb-sw off"></i>unstaffed</span><span class="rb-lg-flow" data-rt="${esc(FLOW_TIP)}"><i class="rb-sw flow"></i>flow alert</span><span data-rt="TMA boundary (APP layer; of the neighbours only Ostrava and Berlin)"><i class="rb-ln-sw tma"></i>TMA</span><span data-rt="CTR boundary (TWR layers, FIR EPWW only)"><i class="rb-ln-sw ctr"></i>CTR</span></div>
            ${panelHtml(m)}
          </div>` : panelHtml(m))).join("")}
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
      return o ? `${o.callsign} ${o.frequency} \u2013 ${o.name || "?"} (CID ${o.cid ?? "?"})${o.logon_time ? `, since ${utcHhmm(o.logon_time)}` : ""}` : "";
    };
    // opis stanowiska: znak, nazwa i częstotliwość z listy stanowisk albo podana (fq: z sieci, gdy stanowisko jest online)
    const posLine = (cs, fq = "") => `${cs}${d?.pos?.[cs]?.name ? ` \u00b7 ${d.pos[cs].name}` : ""} ${fq || d?.pos?.[cs]?.frequency || ""}`.trim();

    // --- ATIS-y w rzędzie u góry, na prawo od wskaźników (0.13.1: bez osobnego paska): zawsze na miejscu i tej samej
    // wysokości (jedna linia); przycisk ATIS chowa tylko treść (visibility), więc nic się nie przesuwa ani przy
    // przełączaniu, ani gdy ATIS-y się logują.
    // Gdy pozycje się nie mieszczą (wszystkie ATIS-y online z literami, ATIS-y dzielone): najpierw ciaśniej (tight),
    // potem ostatnie pozycje w jednej "+N" z listą w dymku – nic nie znika bez śladu
    function renderAtis() {
      const box = $(".rb-atis"), inn = box.firstElementChild, off = !layers.has("atis");
      box.classList.toggle("off", off);
      inn.setAttribute("aria-hidden", String(off));
      if (!d) return;
      const items = d.atis.map((a) => {
        const o = on(a.callsign), fq = freqOf(a.callsign) || "\u2014", id = a.callsign.replace(/_ATIS$/, "").replace(/_/g, " ");
        const rt = [posLine(a.callsign, o ? fq : ""), o ? `Online: ${who(a.callsign)}${o.atis_code ? `\nInformation ${o.atis_code}` : ""}` : "ATIS offline",
          ...(o?.text_atis || []).slice(0, 6), "Click: AERODROME"].join("\n");
        return { line: `${id} ${fq}${o ? (o.atis_code ? ` \u2013 information ${o.atis_code}` : " \u2013 online") : " \u2013 offline"}`,
          html: `<button type="button" class="rb-at ${o ? "on" : "off"}" data-icao="${esc(a.icao)}" data-rt="${esc(rt)}">`
            + `<span class="rb-ati">${esc(id)}</span><span class="rb-fq">${esc(fq)}</span>`
            + `${o?.atis_code ? `<span class="rb-code">${esc(o.atis_code)}</span>` : ""}</button>` };
      });
      inn.classList.remove("tight");
      inn.innerHTML = items.map((it) => it.html).join("") || `<span class="rb-none">No ATIS positions.</span>`;
      const over = () => inn.scrollWidth > inn.clientWidth + 1;
      if (!inn.clientWidth || !over()) return;
      inn.classList.add("tight");
      if (!over()) return;
      const btns = [...inn.querySelectorAll(".rb-at")], more = document.createElement("span");
      more.className = "rb-at-more";
      inn.append(more);
      let n = 0;
      while (btns.length > 1 && (n === 0 || over())) {
        btns.pop().remove();
        n += 1;
        more.textContent = `+${n}`;
        more.dataset.rt = ["More ATIS:", ...items.slice(items.length - n).map((it) => it.line)].join("\n");
      }
    }

    // --- wskaźniki u góry i stosy sąsiadów przy podglądach LOW i HIGH (nbStackHtml, BERLIN pod EDWW); kto
    // i częstotliwości z tablicy
    const cx = () => ({ who, pos: posLine, freq: freqOf, sel: loaFir, net: d?.net?.ok !== false });
    function renderInds() {
      $(".rb-inds").innerHTML = arr(d?.indicators).map((i) => indicatorHtml(i, cx())).join("");
    }
    function renderStacks() {
      if (!d) return;
      const x = cx();
      let ber = false;
      const item = (f) => {
        if (f.fir !== BERLIN_AFTER || f.map !== "left") return nbStackHtml(f, x);
        ber = true;
        return `<div class="rb-grp">${nbStackHtml(f, x)}${berlinHtml(d.berlin, x)}</div>`;
      };
      ["left", "right"].forEach((side) => {
        const p = maps[MAPS.find((m) => m.side === side).key].el;
        const fs = arr(d.firs).filter((f) => f.map === side);
        const html = (area) => fs.filter((f) => AREA[f.at] === area)
          .sort((a, b) => (COL_ORDER[a.at] ?? 9) - (COL_ORDER[b.at] ?? 9)).map(item).join("");
        p.querySelector(".rb-top").innerHTML = html("top");
        p.querySelector(".rb-bot").innerHTML = html("bot");
        p.querySelector(".rb-col").innerHTML = html("col") + (side === "left" && !ber ? berlinHtml(d.berlin, x) : "");
      });
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
      // obsadzone rysowane na końcu, nad nieobsadzonymi), na LOW także TMA Ostrawy i Berlina przy granicy FIR EPWW
      // (0.13.1, Marek: TWR tylko EPWW, APP tylko EPWW, LKMT i EDDB – backend nie wysyła CTR sąsiadów ani innych TMA)
      const nbOn = d.nb || {}, nbAll = geo.nb || [];
      const nbAcc = sliceAt(nbAll.filter((a) => a.kind === "acc"), ft).sort((a, b) => !!nbOn[a.id] - !!nbOn[b.id]);
      const nbTma = low && layers.has("app") ? nbAll.filter((a) => a.kind === "app") : [];
      m.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      m.svg.setAttribute("width", W);
      m.svg.setAttribute("height", H);
      // kolejność (kolory: radio.css): tło FIR-ów, sąsiedzi, FIR EPWW nieobsadzony, obszary stanowisk
      // ACC (obsadzone: ciemne, pełne – pod nimi nic nie ginie), czerwone tło alarmów przepływu (sektory ACC warstwy,
      // na LOW także TMA – zawsze, bez względu na warstwy i obsadę), granice TMA/CTR/FIS EPWW i TMA sąsiadów, granica FIR EPWW
      m.svg.innerHTML = g("rb-firs", geo.firs)
        + `<g class="rb-nbacc">${nbAcc.map((a) => `<path class="${nbOn[a.id] ? "on" : "off"}" d="${pathOf(a.geometry, P)}"/>`).join("")}</g>`
        + `<path class="rb-land" d="${pathOf(geo.border, P)}"/>`
        // obszar stanowiska (bez granic między jego sektorami); po błędzie sumy same wypełnienia wycinków
        + `<g class="rb-accg">${groups.map((a) => (a.geom ? `<path data-k="${esc(a.owner)}" class="st" d="${pathAll(a.geom, P)}"/>`
          : a.slices.map((sl) => `<path data-k="${esc(a.owner)}" class="st fb" d="${pathOf(sl.geometry, P)}"/>`).join(""))).join("")}</g>`
        + flowSvg(flowAreas(d, m.key, accs, geo.tma, x, geoVer), P)
        + (low && layers.has("fis") ? g("rb-fisg", geo.fis) : "")
        + g("rb-tmag nb", nbTma)
        + (low && layers.has("app") ? g("rb-tmag", geo.tma) : "")
        + (low && twrOn ? g("rb-ctrg", geo.ctr) : "")
        + `<path class="rb-border" d="${pathOf(geo.border, P)}"/>`;
      renderTitle(m, { top: fr.top - pr.top, left: fr.left - pr.left, right: pr.right - fr.right });
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
      // przeszkody: stosy sąsiadów, BERLIN i tytuł podglądu (współrzędne w panelu)
      const rel = (e) => { const r = e.getBoundingClientRect(); return { x0: r.left - pr.left - 2, y0: r.top - pr.top - 2, x1: r.right - pr.left + 2, y1: r.bottom - pr.top + 2 }; };
      const obstacles = [...p.querySelectorAll(".rb-nb, .rb-ber, .rb-title")].filter((e) => e.offsetWidth && e.offsetHeight).map(rel);
      // obrysy, których etykiety ACC i FIS nie zasłaniają (runda 11, Marek): TMA na warstwie APP, CTR na TWR i TWR/A;
      // plakietki APP i TWR stoją na nich w środku (labelOpts)
      const shapes = low ? [...(layers.has("app") ? geo.tma : []), ...(twrOn ? geo.ctr : []), ...nbTma] : [];
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
    // tytuł w górnym rogu wolnego pola (bez stosów sąsiadów) od strony środkowej kolumny (LOW z suwakiem wysokości),
    // MID w lewym górnym rogu (radio.css)
    function renderTitle(m, free) {
      const t = m.el.querySelector(".rb-title");
      if (m.key === "LOW") Object.assign(t.style, { top: `${Math.round(free.top)}px`, right: `${Math.round(free.right)}px` });
      if (m.key === "HIGH") Object.assign(t.style, { top: `${Math.round(free.top)}px`, left: `${Math.round(free.left)}px` });
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
      inp.dataset.rt = `LOW cross-section at ${flText(v * 100)}: sector shapes of the band ${flText(c.lo)}\u2013${flText(c.hi)}`
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
    // stan danych: sieć, brak granicy FIR-u, błąd strony i brak danych o ograniczeniach przepływu (wtedy legenda czerwonego
    // tła przygaszona: brak czerwieni nie znaczy „bez ograniczeń”)
    function renderStatus() {
      const s = $(".rb-status");
      const n = d ? controllersOn(d.online) : 0;
      const net = d?.net, noFlow = !!d && d.flow?.ok === false;
      s.innerHTML = !d ? (err ? `<span class="error">${esc(err)}</span>` : "Loading\u2026")
        : `${net?.ok ? `Updated ${esc(utcHhmm(net.updated))} \u00b7 ${n} on the board` : `<span class="error">${esc(net?.error || "No data")}</span>`}`
          + (noFlow ? ` <span class="error">Flow data unavailable</span>` : "")
          + (noBorder ? ` <span class="error">No FIR EPWW boundary: previews without the FIR outline.</span>` : "")
          + (err ? ` <span class="error">${esc(err)}</span>` : "");
      const lg = $(".rb-lg-flow");
      lg.classList.toggle("na", noFlow);
      lg.dataset.rt = noFlow ? `${FLOW_TIP}\n${FLOW_NA}` : FLOW_TIP;
    }
    let raf = 0;
    // jeden błąd (np. dziwne dane) nie zatrzymuje reszty strony
    const safe = (f, ...a) => { try { f(...a); } catch (e) { console.error("RADIO", e); } };
    function renderAll() {
      cancelAnimationFrame(raf);
      raf = 0;
      safe(renderButtons);
      safe(renderAtis);
      if (d) {
        safe(renderInds);
        // stosy przed podglądami: wolne pole do rzutowania mapy to panel bez stosów
        safe(renderStacks);
        // panel LOA na nowo po zmianie rozmiaru strony (stosy przesuwają się z podglądami)
        safe(placeLoa);
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
    // przyciski warstw: kliknięcie łapiemy na kontenerze
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

    // --- LOA: nagłówek stosu sąsiada otwiera panel (drugie kliknięcie, ✕ albo Esc zamyka); bez kroku w historii
    const markLoa = () => el.querySelectorAll(".rb-nbh").forEach((x) => x.classList.toggle("sel", x.closest(".rb-nb")?.dataset.fir === loaFir));
    const radioOf = (cs) => d?.pos?.[cs]?.name || "";
    // panel po tej stronie stosu, gdzie jest więcej miejsca, i nie szerszy niż to miejsce (loaPlace): nagłówek i okienka
    // klikniętego FIR-u zostają widoczne, a z nimi inne stosy tej strony (inny FIR jednym kliknięciem)
    function placeLoa() {
      if (!loaFir || loaBox.hidden) return;
      const gr = $(".rb-grid").getBoundingClientRect();
      const rs = [...el.querySelectorAll(".rb-nb[data-fir]")].filter((e) => e.dataset.fir === loaFir)
        .map((e) => e.getBoundingClientRect()).filter((r) => r.width);
      if (!rs.length || !gr.width) return;
      const p = loaPlace(Math.min(...rs.map((r) => r.left)) - gr.left, Math.max(...rs.map((r) => r.right)) - gr.left, gr.width);
      loaBox.classList.toggle("at-left", p.left);
      loaBox.style.width = `${p.width}px`;
    }
    function closeLoa() {
      loaFir = null;
      loaBox.hidden = true;
      loaBox.innerHTML = "";
      markLoa();
    }
    async function openLoa(fir, title) {
      if (loaFir === fir) return closeLoa();
      loaFir = fir;
      markLoa();
      loaBox.hidden = false;
      placeLoa();
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
    const firOf = (hd) => hd.closest(".rb-nb")?.dataset.fir || "";
    el.addEventListener("click", (e) => {
      const hd = e.target.closest(".rb-nbh");
      if (hd && firOf(hd)) openLoa(firOf(hd), hd.dataset.title || "");
    });
    el.addEventListener("keydown", (e) => {
      const hd = e.target.closest?.(".rb-nbh");
      if (hd && firOf(hd) && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openLoa(firOf(hd), hd.dataset.title || ""); }
      if (e.key === "Escape" && !loaBox.hidden) { e.preventDefault(); closeLoa(); }
    });
    loaBox.addEventListener("click", (e) => {
      if (e.target.closest(".rb-loa-x")) return closeLoa();
      const doc = e.target.closest("button[data-coord]");
      // COORDINATION › DOKUMENTY z tym LOA
      if (doc) navigate("coordination", "docs/" + doc.dataset.coord);
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
    // wysokość z treści, najwyżej okno bez dwóch odstępów (radio.css)
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

// podgląd: mapa (svg) na całym panelu, ramka z miejscami na stosy sąsiadów (0.12.6: LOW – kolumna z lewej, u góry
// i u dołu; HIGH – u góry, u dołu i kolumna z prawej) i wolnym polem do rzutowania mapy (rb-free), etykiety i tytuł
function panelHtml(m) {
  const frame = m.side === "left"
    ? `<div class="rb-frame"><div class="rb-col"></div><div class="rb-top"></div><div class="rb-free"></div><div class="rb-bot"></div></div>`
    : m.side === "right"
      ? `<div class="rb-frame"><div class="rb-top"></div><div class="rb-free"></div><div class="rb-bot"></div><div class="rb-col"></div></div>`
      : `<div class="rb-frame"><div class="rb-free"></div></div>`;
  return `<section class="rb-panel ${m.cls}" data-map="${m.key}"><svg class="rb-svg" aria-hidden="true"></svg>${frame}`
    + `<div class="rb-lbls"></div><div class="rb-title"></div></section>`;
}
