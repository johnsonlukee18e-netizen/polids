// RADIO: jedna strona jak w PANDORZE. 0.13.2 (issue #27, Marek: szkic strony) – cała strona w siatce szkicu
// (data/seed/radio_layout.json, GET /api/radio/board: grid, firs, indicators, berlin): u góry jeden rząd – małe
// wskaźniki konfiguracji ACC GAT, APP GD, APP WA, APP KK, APP PO (żółta nazwa nad szarym polem), na prawo od nich
// ATIS-y polskich lotnisk (przycisk ATIS chowa tylko ich treść, nic się nie przesuwa); pod nim siatka 13 kolumn
// szkicu: kafelki FIR-ów sąsiadów w swoich komórkach (kafelki różnych FIR-ów w jednym wierszu stoją równo, wysokości
// między kafelkami jak w stosach 0.13.1: stackGrid), żółty kod FIR-u w swojej komórce (nazwa tylko, gdy się mieści,
// ADVISORY 122.800 obok kodu; kliknięcie: LOA), BERLIN: WEST/EAST pod EDWW, w kolumnie H przyciski warstw ATIS /
// LOW MID HIGH / APP / TWR / TWR/A / FIS i stan danych, podglądy LOW (kolumny D–G), HIGH (I–K) i mały MID (na dole
// kolumny H), legenda w lewym dolnym rogu. Kafelek to sama częstotliwość (gdy ktoś go obsługuje) i ID w prawym
// górnym rogu, zawsze tego samego rozmiaru.
// Podglądy (0.13.2, Marek: "mapy całe czarne"): czarne tło, tylko cienkie jasne granice FIR-ów i granica FIR EPWW, bez
// sektorów sąsiadów, TMA i CTR; stałe przekroje LOW FL330, MID FL350, HIGH FL400 (bez suwaka wysokości). Sektory ACC
// EPWW warstwy podglądu: bez nikogo – szare pole bez granic i bez plakietki; obsadzone – czarne, z granatową granicą
// wokół całego obszaru stanowiska (wycinki tego samego stanowiska jako jeden obszar, dissolve.js) i plakietką jak
// kafelek (nazwa: jeden sektor – litera i warstwa, "B LOW"; kilka – skrót stanowiska, "ALL"). Na LOW warstwy APP,
// TWR, TWR/A i FIS: tylko stanowiska online – granatowa granica obsługiwanych części TMA, CTR wieży albo obszarów FIS
// i plakietka (TWR/A także sam ATIS); bez linii prowadzących, plakietka w środku swojego obszaru, przy tłoku lekko
// odsunięta. Czerwone tło sektora ACC i TMA z ograniczeniem przepływu albo zajętością ponad 80 %; dymki stałej
// szerokości.
// Dane: GET /api/radio/board co 30 s (geometria raz, potem tylko po zmianie wersji danych `ver`, np. po imporcie nowych
// danych sektorów). Panel z wyciągiem z LOA EPWW z FIR-em sąsiada
// (GET /api/radio/loa), z przyciskiem do dokumentu w COORDINATION › DOKUMENTY i PDF-em w nowej karcie. Kliknięcie
// kodu FIR-u sąsiada (np. EDWW) otwiera ten panel.
import { api, esc, h, lsGet, lsSet, navigate, remember } from "../api.js";
import { labelPoint } from "../coverage.js";
import { dissolve, pointIn } from "../dissolve.js";
import { displayName, loadDisplayNames, posName } from "../posname.js";
import { ADVISORY_FQ, DEFAULT_LAYERS, EPWW_BBOX, LAYERS, LAYER_IDS, LEVEL_FT, accPlateName, argOf, bboxOf, bboxOrDefault,
  cellArea, controllersOn, coverGrid, flText, labelOpts, limText, limTip, loaPlace, pageGrid, parseArg, pathAll, pathOf,
  placeLabels, projection, ringsOf, sliceAt, tipPos, utcHhmm } from "../radioboard.js";

const LS_LAYERS = "radio.layers";
const REFRESH_MS = 30000;
// podglądy w siatce strony (grid.maps z /api/radio/board: low, high, mid)
const MAPS = [
  { key: "LOW", layer: "low", cls: "rb-low" },
  { key: "MID", layer: "mid", cls: "rb-midmap" },
  { key: "HIGH", layer: "high", cls: "rb-high" },
];
// legenda czerwonego tła; bez danych o ograniczeniach przepływu (flow.ok false) przygaszona, z innym dymkiem
const FLOW_TIP = "Flow alert: red area \u2013 flow restriction now or occupancy over 80 % of capacity (ACC sector on its level preview, TMA on LOW)";
const FLOW_NA = "Flow data unavailable: red areas cannot be shown now";
const arr = (x) => (Array.isArray(x) ? x : []);

// warstwy z pamięci przeglądarki; stary wpis radio.cut (przekrój LOW z suwaka, do 0.13.1) pomijamy
function readLayers() {
  try {
    const v = JSON.parse(lsGet(LS_LAYERS));
    if (Array.isArray(v)) return new Set(v.filter((x) => LAYER_IDS.includes(x)));
  } catch { /* brak albo uszkodzony wpis */ }
  return new Set(DEFAULT_LAYERS);
}

// przybliżone pole wielokąta (do wyboru większej części sektora dzielonego w poziomie, np. R-N i R-S)
const areaOf = (g) => ringsOf(g).reduce((a, r) => a + Math.abs(r.reduce((s, [x1, y1], i) => {
  const [x2, y2] = r[(i + 1) % r.length];
  return s + x1 * y2 - x2 * y1;
}, 0)) / 2, 0);

// Sektory ACC podglądu wg obsługującego (runda 12, Marek): wycinki na wysokości podglądu (accs, sliceAt) z tym samym
// stanowiskiem z kolejności przejmowania warstwy (sectors z /api/radio/board: owner) → jeden obszar (dissolve.js,
// w pamięci wg klucza: wersja danych, stanowisko, wycinki) i jeden punkt plakietki poza dziurami; wycinki bez nikogo
// pomijamy (freeArea). Błąd sumy: geom null, rysujemy same wycinki bez granic. Wynik od największego obszaru:
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
// Sektory ACC bez nikogo na warstwie podglądu (0.13.2, Marek): szare pole bez granic i bez plakietki – wycinki, których
// sektor tej warstwy nie ma obsługującego, jako jeden obszar (bez granic między nimi). Wynik {geom, shapes} albo null
// (wszystko obsadzone); geom null po błędzie sumy – wtedy same wycinki (shapes), też bez granic
export function freeArea(accs, sectors, layer, ver = "") {
  const own = new Set(arr(sectors).filter((s) => s.layer === layer && s.owner).map((s) => s.letter));
  const sl = arr(accs).filter((a) => !own.has(a.letter));
  if (!sl.length) return null;
  const u = dissolve(`rbfree|${ver}|${layer}|${sl.map((a) => `${a.name}:${a.lo}`).sort().join(",")}`, sl.map((a) => a.geometry));
  return { geom: u?.geometry || null, shapes: sl.map((a) => a.geometry) };
}

// --- LOA EPWW z sąsiadem (data/seed/loa.json, jak do 0.11 w RADIO): tytuł, wersja, liczba przekazań i PDF, pod spodem
// gęste tabele przekazań OUT/IN, zasady (przekazanie kontroli, VFR, inne) i stanowiska wg LOA, z filtrem.
// Lista raz na sesję (plik zmienia się z nową wersją PolIDS); błąd nie zostaje w pamięci.
let loaP = null;
const loadLoa = () => (loaP ||= api("/api/radio/loa").catch((e) => { loaP = null; throw e; }));
// tylko ścieżki do plików PolIDS (/files/docs/…): PDF w nowej karcie; dokument w COORDINATION › DOKUMENTY
// (#coordination/docs/<FIR>: COORDINATION znajduje dokument LOA z tym FIR-em)
const DOCS = "/files/docs/";
const pdfPath = (pdf) => (String(pdf || "").startsWith(DOCS) ? String(pdf) : "");

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

// --- wskaźniki u góry strony, BERLIN, kody FIR-ów i kafelki sąsiadów z /api/radio/board (0.13.2: w siatce szkicu).
// x: {who(cs), pos(cs), freq(cs), net, sel} – zalogowany i opis stanowiska z tablicy, false = brak danych
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
// miejsce w siatce strony ({gc, gr} z cellArea) jako styl elementu
const placeAt = (a) => (a ? ` style="grid-column: ${a.gc}; grid-row: ${a.gr}"` : "");
// BERLIN (0.13.2, szkic): żółty napis w swojej komórce (kolumna A pod EDWW), pod nim szare pole WEST/EAST na dwie
// kolumny wysokości kafelka; bez pasa z ATIS (preferred) czerwony napis. Bez danych o zalogowanych (x.net === false)
// albo bez konfiguracji: kreska jak we wskaźnikach – nie wiadomo, czy jest ATIS. at = {label, box}: miejsca w siatce
export function berlinHtml(b, x = {}, at = null) {
  const cfg = x.net === false ? "" : b?.config || "", pref = !!cfg && !!b?.preferred;
  const tip = b?.tip || (x.net === false ? "ATIS unknown: no network data" : "");
  const rt = ["BERLIN: runway configuration of Berlin Brandenburg, WEST (runways 24) or EAST (runways 06)", tip,
    ...(pref ? ["Red text: preferred configuration, no runway in use from ATIS"] : [])].filter(Boolean).join("\n");
  return `<div class="rb-blbl"${placeAt(at?.label)} data-rt="${esc(rt)}">BERLIN</div>`
    + `<div class="rb-bln${pref ? " pref" : ""}"${placeAt(at?.box)} data-rt="${esc(rt)}">${esc(cfg || "\u2013")}</div>`;
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
// na swoich komórkach. Granice nie na kafelku, tylko między kafelkami (markHtml) i w dymku. t: kafelek ze stackGrid
// (tory siatki strony z pageGrid)
export function tileHtml(t, f, x) {
  const b = t.b, fq = b.owner ? b.frequency || x.freq(b.owner) : "";
  return `<div class="rb-box ${b.owner ? "on" : "off"}${b.merged ? " mrg" : ""}" data-fir="${esc(f.fir)}" data-box="${esc(b.id)}"`
    + ` style="grid-column: ${t.gc}; grid-row: ${t.gr}" data-rt="${esc(boxTip(b, f, x))}">`
    + `<span class="rb-id">${esc(b.label)}</span>${fq ? `<span class="rb-fq">${esc(fq)}</span>` : ""}</div>`;
}
// wysokości między kafelkami jak na szkicu i zdjęciu PANDORY (660, 365, 0), od lewej krawędzi kolumny; rząd liczb
// strony bywa wyższy niż liczba (okno wyższe niż strona), więc liczba stoi przy swoim kafelku (k.at z stackGrid):
// górna granica kafelka pod spodem na dole rzędu (up), dolna granica kafelka nad nią na górze (dn), wspólna w środku
// (sh); dwie liczby – nowy ciąg okienek (EDUU OSE1 i HVL2): dolna granica kafelka nad kreską, pod nią górna granica
// kafelka pod spodem
const lvTip = (n) => (n >= 999 ? "UNL" : n > 0 ? flText(n * 100) : "GND");
export function markHtml(k) {
  const [a, b] = k.n, two = k.n.length > 1;
  const rt = two ? `${lvTip(a)}: lower limit of the box above\n${lvTip(b)}: upper limit of the box below` : lvTip(a);
  return `<div class="rb-bd${k.at ? ` ${k.at}` : ""}" style="grid-column: ${k.gc}; grid-row: ${k.gr}" data-rt="${esc(rt)}"><i>${esc(String(a))}</i>`
    + `${two ? `<span class="rb-sep"></span><i>${esc(String(b))}</i>` : ""}</div>`;
}
// dymek kodu FIR-u: kod i nazwa, zalogowani tego FIR-u (bez nikogo: ADVISORY), znaczenie liczb, kliknięcie: LOA
export function firTip(f, x) {
  const on = arr(f.online);
  return [`${f.fir} ${f.title || ""}`.trim(),
    ...(x.net === false ? ["Online: no data"] : on.length ? on.map((o) => `Online: ${onlineLine(o)}`) : [`Nobody online \u2013 ADVISORY ${ADVISORY_FQ}`]),
    "Numbers between the boxes: vertical limits (FL)", `Click: LOA EPWW \u2013 ${f.fir}`].join("\n");
}
// Kod FIR-u sąsiada (0.13.2, szkic): żółty kod w swojej komórce (f.name), w miejscu f.room (komórka kodu i wolne
// komórki obok: radioboard.py head_room) szara nazwa – tylko gdy się mieści (radio.js chowa ją wtedy klasą nn, nazwa
// jest w dymku) – i małe ADVISORY 122.800, gdy w całym FIR-ze nikt nie obsługuje okienek: na prawo od kodu, a przy
// prawej krawędzi siatki (EYVL, UMMV, UKLV: miejsce w dół) pod kodem. Nic z tego nie przesuwa kafelków. Kliknięcie
// albo Enter: LOA EPWW z tym FIR-em. top = grid.top z /api/radio/board
export function firHeadHtml(f, x, top) {
  const room = f.room || f.name;
  if (!room) return "";
  const adv = !!f.advisory && x.net !== false, down = (Number(room.rows) || 1) > 1 && (Number(room.cols) || 1) === 1;
  return `<div class="rb-fh${down ? " down" : ""}${x.sel === f.fir ? " sel" : ""}" data-fir="${esc(f.fir)}" data-title="${esc(f.title || "")}"`
    + ` role="button" tabindex="0"${placeAt(cellArea(room, top))} data-rt="${esc(firTip(f, x))}">`
    + `<span class="rb-fc">${esc(f.fir)}</span><span class="rb-fn">${esc(f.title || "")}</span>`
    + `${adv ? `<span class="rb-fs">ADVISORY ${ADVISORY_FQ}</span>` : ""}</div>`;
}
// Kody, kafelki i liczby wszystkich FIR-ów sąsiadów oraz BERLIN na stronie (pg = pageGrid); grid z /api/radio/board
export function pageHtml(pg, grid, bd, x) {
  const ber = grid?.berlin;
  return pg.stacks.map(({ f, g }) => firHeadHtml(f, x, pg.top) + g.marks.map(markHtml).join("") + g.tiles.map((t) => tileHtml(t, f, x)).join("")).join("")
    + (ber ? berlinHtml(bd?.berlin, x, { label: cellArea(ber, pg.top), box: cellArea(ber.box, pg.top) }) : "");
}

// --- plakietki podglądów (0.13.2, Marek: "plakietki wyglądają jak kafelki"): jasne pole, częstotliwość, małe ID
// w prawym górnym rogu, rozmiar kafelka (radio.css); TWR/A – żółta litera ATIS obok ID; sam ATIS (wieża offline,
// TWR/A) – ciemne pole z jasnofioletową częstotliwością ATIS. Szczegóły zawsze w dymku. p: {kind: acc | app | twr | fis,
// k (granica na podglądzie z tym samym data-k: podświetlenie), id, fq, state: on | off, atis?, code?, icao?, rt}
export function plateHtml(p) {
  const attrs = ` data-k="${esc(p.k)}"${p.icao ? ` data-icao="${esc(p.icao)}" tabindex="0" role="button"` : ""} data-rt="${esc(p.rt)}"`;
  const code = p.code ? `<b class="rb-code">${esc(p.code)}</b>` : "";
  return `<div class="rb-pl ${p.kind} ${p.state || "on"}${p.atis ? " atis" : ""}"${attrs}><span class="rb-tr">${code}<span class="rb-id">${esc(p.id)}</span></span>`
    + `${p.fq ? `<span class="rb-fq">${esc(p.fq)}</span>` : ""}</div>`;
}
// x = {freq, nm, dn, on, who, pos, net}: częstotliwość (online albo z tablicy), nazwa stanowiska (krótka i pełna),
// kontroler online, kto (dymek), opis stanowiska z tablicy, false = brak danych o zalogowanych
const range = (lo, hi) => `${lo ? flText(lo) : "GND"}\u2013${flText(hi)}`;
// ACC: obszar jednego stanowiska na warstwie key (g z accGroups); nazwa wg accPlateName, częstotliwość z sieci
export function accPlate(g, key, x, bd) {
  return { at: g.at, kind: "acc", k: g.owner, id: accPlateName(g, key, bd?.acc_short, x.dn), fq: x.freq(g.owner), state: "on",
    rt: accTip(g, `${x.dn(g.owner)} \u00b7 ${key} ${flText(LEVEL_FT[key])}`, x, bd?.flow) };
}
// APP: jedna plakietka na zalogowane stanowisko APP (dyrektor bez plakietki); tma = grupy TMA (części) z tablicy,
// flow = alarmy przepływu. Dymek: TMA (i części, gdy TMA ma kilka), stanowisko, kto, inne TMA, które obsługuje, alarmy
export function appPlate(p, x, tma = [], flow = null) {
  const byId = new Map(arr(tma).map((g) => [g.id, g]));
  const cov = arr(p.covers).map((id) => byId.get(id)).filter(Boolean);
  const mine = cov.filter((g) => g.tma === p.tma), all = arr(tma).filter((g) => g.tma === p.tma);
  const others = [...new Set(cov.filter((g) => g.tma !== p.tma).map((g) => g.tma))];
  const part = all.length > 1 ? (mine.length === all.length ? " \u2013 all parts" : ` \u2013 part ${mine.map((g) => x.nm(g.nominal)).join(", ")}`) : "";
  const lims = mine.length ? ` (${range(Math.min(...mine.map((g) => g.lo || 0)), Math.max(...mine.map((g) => g.hi || 0)))})` : "";
  const rt = [`${p.tma || x.nm(p.owner)}${part}${lims}`, `Position: ${x.pos(p.owner)}`, nowText([p.owner], x),
    ...(others.length ? [`Also covers: ${others.join(", ")}`] : []),
    ...flowLines(flow?.tma?.[p.tma]), ...others.flatMap((t) => flowLines(flow?.tma?.[t], t))].join("\n");
  return { at: p.at, kind: "app", k: p.owner, id: x.nm(p.owner), fq: p.frequency || x.freq(p.owner), state: "on", rt };
}
// TWR: wieża lotniska online (TWR i TWR/A) albo na TWR/A sam ATIS lotniska; ctr = grupa CTR z tablicy (stanowisko
// wieży, ATIS, kto ją przejmuje). Litera ATIS tylko na TWR/A i tylko z ATIS online
export function twrPlate(p, ctr, x, twra = false) {
  const tw = arr(p.twr)[0] || null, nominal = ctr?.nominal || tw || `${p.icao}_TWR`;
  const acs = arr(p.atis)[0] || ctr?.atis || null, a = twra && acs ? x.on(acs) : null;
  const cover = arr(ctr?.owners);
  const now = tw ? null : cover.length ? `Tower offline \u2013 covered by ${cover.map((o) => x.who(o) || o).join(", ")}` : "Tower offline";
  // ATIS online: częstotliwość z sieci (jak na plakietce), offline: z listy stanowisk
  const ao = acs ? x.on(acs) : null;
  const atisLine = acs ? [`ATIS: ${x.pos(acs, ao ? x.freq(acs) : "")}${ao ? ` \u2013 online${ao.atis_code ? `, information ${ao.atis_code}` : ""}` : " \u2013 offline"}`] : [];
  const rt = groupTip({ nominal, owners: arr(p.twr), topdown: null }, `${p.id} \u00b7 ${p.icao}`, x, [...atisLine, "Click: AERODROME"], now);
  return { at: p.at, kind: "twr", k: p.icao, id: x.nm(tw || acs || nominal), fq: tw ? p.frequency || x.freq(tw) : acs ? x.freq(acs) : "",
    state: tw ? "on" : "off", atis: !tw, code: a?.atis_code || "", icao: p.icao, rt };
}
// FIS: jedna plakietka na zalogowane stanowisko FIS (fis z /api/radio/board: obszary, które obsługuje)
export function fisPlate(owner, at, x, fis = []) {
  const mine = arr(fis).filter((g) => arr(g.owners).includes(owner));
  const names = [...new Set(mine.map((g) => `${g.id} (up to ${flText(g.hi)})`))];
  const rt = [...(names.length ? names : [x.nm(owner)]), `Position: ${x.pos(owner)}`, nowText([owner], x)].join("\n");
  return { at: at || mine.find((g) => g.at)?.at || null, kind: "fis", k: owner, id: x.nm(owner), fq: x.freq(owner), state: "on", rt };
}
// granica kilku kształtów (części TMA, CTR, obszary FIS) jednego stanowiska: suma (dissolve.js, w pamięci wg klucza);
// błąd sumy – same kształty
const unionOf = (key, shapes) => {
  if (!shapes.length) return null;
  const u = dissolve(key, shapes.map((s) => s.geometry));
  return { geom: u?.geometry || null, shapes: shapes.map((s) => s.geometry), at: u ? (u.at ||= pointIn(u.geometry)) : null };
};
// Granice i plakietki podglądu key (0.13.2): {lines: [{kind, k, geom | null, shapes}], plates: [plakietka]} – tylko
// stanowiska online. Sektory ACC (groups z accGroups), gdy warstwa podglądu jest włączona; na LOW (bez względu na
// LOW) warstwy APP (granica obsługiwanych części TMA: areas.app), TWR (CTR wieży online), TWR/A (to samo, także sam
// ATIS – bez granicy) i FIS (areas.fis). Plakietki w kolejności układania: APP, TWR, ACC, FIS.
// bd = /api/radio/board, geo = jego geometria, x = jak w appPlate
export function previewItems(bd, geo, key, layers, groups, x, ver = "") {
  const lines = [], app = [], twr = [], acc = [], fis = [];
  if (layers.has(key.toLowerCase())) {
    arr(groups).forEach((g) => {
      lines.push({ kind: "acc", k: g.owner, geom: g.geom || null, shapes: g.geom ? [] : g.slices.map((sl) => sl.geometry) });
      if (g.at) acc.push(accPlate(g, key, x, bd));
    });
  }
  if (key === "LOW") {
    const byId = (list) => new Map(arr(list).map((s) => [s.id, s]));
    if (layers.has("app")) {
      const tma = byId(geo?.tma), areas = bd?.areas?.app || {}, plates = new Map(arr(bd?.plates?.app).map((p) => [p.owner, p]));
      [...new Set([...Object.keys(areas), ...plates.keys()])].forEach((o) => {
        const ids = arr(areas[o]), u = unionOf(`rbapp|${ver}|${o}|${ids.join(",")}`, ids.map((id) => tma.get(id)).filter(Boolean));
        if (u) lines.push({ kind: "app", k: o, geom: u.geom, shapes: u.geom ? [] : u.shapes });
        const p = plates.get(o) || { owner: o, covers: [] }, at = p.at || u?.at;
        if (at) app.push(appPlate({ ...p, at }, x, bd.tma, bd.flow));
      });
    }
    const twra = layers.has("twra");
    if (twra || layers.has("twr")) {
      const ctr = byId(bd?.twr);
      arr(bd?.plates?.twr).forEach((p) => {
        if (!arr(p.layers).includes(twra ? "twra" : "twr")) return;
        const u = arr(p.twr).length ? unionOf(`rbctr|${ver}|${p.id}`, arr(geo?.ctr).filter((c) => c.ctr === p.id)) : null;
        if (u) lines.push({ kind: "twr", k: p.icao, geom: u.geom, shapes: u.geom ? [] : u.shapes });
        const at = p.at || u?.at;
        if (at) twr.push(twrPlate({ ...p, at }, ctr.get(p.id), x, twra));
      });
    }
    if (layers.has("fis")) {
      const shapes = byId(geo?.fis);
      Object.entries(bd?.areas?.fis || {}).forEach(([o, ids]) => {
        const u = unionOf(`rbfis|${ver}|${o}|${arr(ids).join(",")}`, arr(ids).map((id) => shapes.get(id)).filter(Boolean));
        if (u) lines.push({ kind: "fis", k: o, geom: u.geom, shapes: u.geom ? [] : u.shapes });
        const p = fisPlate(o, u?.at, x, bd.fis);
        if (p.at) fis.push(p);
      });
    }
  }
  return { lines, plates: [...app, ...twr, ...acc, ...fis] };
}
// warstwa SVG granic stanowisk online (granatowe, radio.css): jedna ścieżka na stanowisko (suma z dziurami); po błędzie
// sumy same kształty
export const linesSvg = (lines, P) => `<g class="rb-own">${arr(lines).map((l) => `<path class="${l.kind}${l.geom ? "" : " fb"}" data-k="${esc(l.k)}"`
  + ` d="${l.geom ? pathAll(l.geom, P) : arr(l.shapes).map((g) => pathOf(g, P)).join("")}"/>`).join("")}</g>`;

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

// przyciski warstw w wierszach szkicu (grid.buttons z /api/radio/board: {col, rows: {warstwa: wiersz}}): jeden rząd na
// wiersz, w kolejności LAYERS (LOW MID HIGH obok siebie)
export function buttonRows(buttons) {
  const rows = buttons?.rows || {}, by = new Map();
  LAYERS.forEach((l) => {
    const r = Number(rows[l.id]);
    if (r > 0) by.set(r, [...(by.get(r) || []), l]);
  });
  return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([row, ls]) => ({ row, layers: ls }));
}

export default {
  mount(root) {
    // rząd u góry (wskaźniki, na prawo od nich ATIS), pod nim siatka strony wg szkicu (kody, kafelki, BERLIN, przyciski,
    // podglądy, stan danych, legenda – miejsca z /api/radio/board: grid); panel LOA nad siatką
    const el = h(`<div class="rb">
      <div class="rb-cfg"><div class="rb-inds"></div><div class="rb-atis" aria-label="ATIS"><div class="rb-atis-in"></div></div></div>
      <div class="rb-page">
        <div class="rb-nbs"></div>
        <div class="rb-btns"></div>
        ${MAPS.map(mapHtml).join("")}
        <div class="rb-status"></div>
        <div class="rb-legend">
          <span data-rt="Position online (EPWW ACC sector on its level preview; APP, TWR, FIS on LOW with their layers): navy boundary around the whole area it controls and a plate with its name and frequency"><i class="rb-sw on"></i>position online</span>
          <span data-rt="EPWW ACC sector of the preview level without a controller: grey area, no boundary and no plate. Neighbour box without a controller: dark, ID only; nobody in the whole FIR \u2013 ADVISORY ${ADVISORY_FQ} next to its code"><i class="rb-sw off"></i>EPWW unstaffed</span>
          <span class="rb-lg-flow" data-rt="${esc(FLOW_TIP)}"><i class="rb-sw flow"></i>flow alert</span>
        </div>
        <div class="rb-loa" role="dialog" aria-label="LOA" hidden></div>
      </div>
      <div class="rb-tip" hidden></div>
    </div>`);
    root.append(el);
    const $ = (s) => el.querySelector(s);
    const tip = $(".rb-tip"), loaBox = $(".rb-loa"), page = $(".rb-page");

    let layers = readLayers();
    let d = null, geo = null, geoVer = "", err = "", border = null, noBorder = false, timer = null, loading = false, lastLoad = 0;
    // FIR, którego LOA jest otwarte (panel .rb-loa); układ przycisków (zmienia się tylko z nowym szkicem)
    let loaFir = null, btnKey = "";
    const maps = Object.fromEntries(MAPS.map((m) => {
      const p = el.querySelector(`.rb-map[data-map="${m.key}"]`);
      return [m.key, { ...m, el: p, svg: p.querySelector("svg"), lbls: p.querySelector(".rb-lbls") }];
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

    // --- wskaźniki u góry i siatka strony: kody FIR-ów, kafelki, liczby, BERLIN, przyciski, podglądy, stan danych
    // i legenda w komórkach szkicu; kto i częstotliwości z tablicy
    const cx = () => ({ who, pos: posLine, freq: freqOf, sel: loaFir, net: d?.net?.ok !== false });
    function renderInds() {
      $(".rb-inds").innerHTML = arr(d?.indicators).map((i) => indicatorHtml(i, cx())).join("");
    }
    const place = (e, a) => { if (e && a) Object.assign(e.style, { gridColumn: a.gc, gridRow: a.gr }); };
    const spills = (e) => {
      const r = e.getBoundingClientRect();
      return [...e.children].some((c) => {
        const q = c.getBoundingClientRect();
        return q.width > 0 && (q.left < r.left - 1 || q.right > r.right + 1 || q.top < r.top - 1 || q.bottom > r.bottom + 1);
      });
    };
    function renderPage() {
      const grid = d?.grid;
      if (!grid) return;
      const pg = pageGrid(grid, d.firs), top = pg.top;
      page.classList.add("rb-on");
      page.style.gridTemplateColumns = pg.cols.join(" ");
      page.style.gridTemplateRows = pg.rows.join(" ");
      $(".rb-nbs").innerHTML = pageHtml(pg, grid, d, cx());
      // nazwa FIR-u tylko, gdy mieści się w swoim miejscu obok kodu, a ADVISORY zostaje wtedy na prawo od kodu
      // (inaczej nazwa w dymku); treść przy dolnej krawędzi wychodzi w górę, więc liczą się prostokąty dzieci, nie
      // scrollHeight
      el.querySelectorAll(".rb-fh").forEach((e) => {
        const c = e.querySelector(".rb-fc"), a = e.querySelector(".rb-fs");
        const wraps = !!a && !e.classList.contains("down") && a.getBoundingClientRect().top >= c.getBoundingClientRect().bottom - 2;
        if (wraps || spills(e)) e.classList.add("nn");
      });
      renderButtonCells(grid.buttons, top);
      MAPS.forEach((m) => place(maps[m.key].el, grid.maps?.[m.layer] ? cellArea(grid.maps[m.layer], top) : null));
      // stan danych z rzędami liczb nad i pod swoją komórką (krótka linia nie zmienia wysokości strony)
      place($(".rb-status"), grid.status ? cellArea(grid.status, top, { above: 1, below: 1 }) : null);
      place($(".rb-legend"), grid.legend ? cellArea(grid.legend, top) : null);
    }
    // przyciski: komórki tworzone raz na układ (fokus i najechanie zostają przy odświeżaniu), potem tylko stan
    function renderButtonCells(buttons, top) {
      const rows = buttonRows(buttons), key = JSON.stringify([buttons?.col, rows.map((r) => [r.row, r.layers.map((l) => l.id)]), top]);
      if (key === btnKey) return;
      btnKey = key;
      const col = Number(buttons?.col) || 1;
      $(".rb-btns").innerHTML = rows.map((r) => {
        const a = cellArea({ col, row: r.row }, top);
        return `<div class="rb-bt" style="grid-column: ${a.gc}; grid-row: ${a.gr}">${r.layers.map((l) => `<button type="button" data-ly="${l.id}"`
          + ` data-rt="${esc(l.tip)}" aria-pressed="false">${esc(l.label)}</button>`).join("")}</div>`;
      }).join("");
      renderButtons();
    }

    // --- podglądy
    // plakietki i dymki podglądu (previewItems, flowAreas): częstotliwości, nazwy i kto z tablicy
    const px = () => ({ freq: freqOf, nm, on, who, pos: posLine, net: d?.net?.ok !== false, dn: displayName });

    function renderMap(m) {
      const p = m.el, W = p.clientWidth, H = p.clientHeight;
      if (!geo || !d || W < 40 || H < 40) return;
      const { P } = projection(border, { x: 0, y: 0, w: W, h: H }, 0.03);
      const accs = sliceAt(geo.acc, LEVEL_FT[m.key]), shown = layers.has(m.layer), x = px();
      const groups = shown ? accGroups(accs, d.sectors, m.key, geoVer) : [];
      const free = shown ? freeArea(accs, d.sectors, m.key, geoVer) : null;
      const { lines, plates } = previewItems(d, geo, m.key, layers, groups, x, geoVer);
      m.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      m.svg.setAttribute("width", W);
      m.svg.setAttribute("height", H);
      // kolejność (kolory: radio.css): cienkie granice FIR-ów, FIR EPWW (czarny – kryje granice sąsiadów), szare sektory
      // ACC bez nikogo, czerwone tło alarmów przepływu (sektory ACC warstwy, na LOW także TMA – zawsze, bez względu na
      // warstwy i obsadę), granica FIR EPWW, granatowe granice obszarów stanowisk online
      m.svg.innerHTML = `<g class="rb-firs">${arr(geo.firs).map((f) => `<path d="${pathOf(f.geometry, P)}"/>`).join("")}</g>`
        + `<path class="rb-land" d="${pathOf(geo.border, P)}"/>`
        + (free ? `<g class="rb-free">${free.geom ? `<path d="${pathAll(free.geom, P)}"/>` : free.shapes.map((g) => `<path class="fb" d="${pathOf(g, P)}"/>`).join("")}</g>` : "")
        + flowSvg(flowAreas(d, m.key, accs, geo.tma, x, geoVer), P)
        + `<path class="rb-border" d="${pathOf(geo.border, P)}"/>`
        + linesSvg(lines, P);
      renderTitle(m);
      // plakietki: wstawiamy, mierzymy, układamy (ważniejsze pierwsze: APP, TWR, ACC, FIS) bez nakładania się, każda
      // w środku swojego obszaru, przy tłoku lekko odsunięta (bez linii prowadzących)
      m.lbls.innerHTML = plates.map(plateHtml).join("");
      const els = [...m.lbls.children], pts = plates.map((it) => P([it.at[1], it.at[0]]));
      const pr = p.getBoundingClientRect();
      const rel = (e) => { const r = e.getBoundingClientRect(); return { x0: r.left - pr.left - 2, y0: r.top - pr.top - 2, x1: r.right - pr.left + 2, y1: r.bottom - pr.top + 2 }; };
      const obstacles = [...p.querySelectorAll(".rb-title")].filter((e) => e.offsetWidth && e.offsetHeight).map(rel);
      // granice stanowisk online pod plakietkami: plakietka ACC i FIS nie zasłania granic TMA i CTR (labelOpts)
      const cover = lines.length ? coverGrid(lines.flatMap((l) => (l.geom ? [l.geom] : arr(l.shapes)).flatMap((g) => ringsOf(g).map((r) => r.map(P)))), W, H) : null;
      const moves = placeLabels(plates.map((it, i) => ({ x: pts[i][0], y: pts[i][1], w: els[i].offsetWidth, h: els[i].offsetHeight, ...labelOpts(it.kind) })),
        { x: 2, y: 2, w: W - 4, h: H - 4 }, { obstacles, cover, lines: false });
      els.forEach((e, i) => {
        const { dx, dy } = moves[i], [x0, y0] = pts[i];
        e.style.left = `${Math.round(x0 + dx - e.offsetWidth / 2)}px`;
        e.style.top = `${Math.round(y0 + dy - e.offsetHeight / 2)}px`;
      });
    }
    // mały tytuł podglądu w górnym rogu (radio.css: HIGH w prawym, z dala od przycisków): warstwa i stały przekrój
    // (bez suwaka)
    function renderTitle(m) {
      const t = m.el.querySelector(".rb-title");
      t.innerHTML = `<span class="rb-tk">${m.key}</span> <span class="rb-tl">${flText(LEVEL_FT[m.key])}</span>`;
      t.dataset.rt = `${m.key}: EPWW ACC sectors at ${flText(LEVEL_FT[m.key])}${m.key === "LOW" ? "; APP, TWR, TWR/A and FIS layers on this preview" : ""}`;
    }
    // włączona warstwa: jasne pole i ciemny napis, wyłączona: szare pole i jasny napis (kolor, bez pogrubienia)
    function renderButtons() {
      el.querySelectorAll(".rb-btns button[data-ly]").forEach((b) => {
        b.classList.toggle("on", layers.has(b.dataset.ly));
        b.setAttribute("aria-pressed", String(layers.has(b.dataset.ly)));
      });
    }
    // stan danych: sieć, brak granicy FIR-u, błąd strony i brak danych o ograniczeniach przepływu (wtedy legenda czerwonego
    // tła przygaszona: brak czerwieni nie znaczy „bez ograniczeń”); całość także w dymku (wąska kolumna)
    function renderStatus() {
      const s = $(".rb-status");
      const n = d ? controllersOn(d.online) : 0;
      const net = d?.net, noFlow = !!d && d.flow?.ok === false;
      s.innerHTML = `<span>${!d ? (err ? `<span class="error">${esc(err)}</span>` : "Loading\u2026")
        : `${net?.ok ? `Updated ${esc(utcHhmm(net.updated))} \u00b7 ${n} on the board` : `<span class="error">${esc(net?.error || "No data")}</span>`}`
          + (noFlow ? ` <span class="error">Flow data unavailable</span>` : "")
          + (noBorder ? ` <span class="error">No FIR EPWW boundary: previews without the FIR outline.</span>` : "")
          + (err ? ` <span class="error">${esc(err)}</span>` : "")}</span>`;
      s.dataset.rt = s.textContent;
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
        // siatka przed podglądami: rozmiar podglądu to jego komórki
        safe(renderPage);
        // panel LOA na nowo po zmianie rozmiaru strony
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
    ro.observe(page);

    // --- warstwy: zapamiętane w przeglądarce, każda zmiana to krok do cofnięcia (#radio/atis,low); stary adres
    // z przekrojem LOW (#radio/atis,low/fl300) otwiera te same warstwy
    const save = () => lsSet(LS_LAYERS, JSON.stringify([...layers]));
    const apply = (arg) => {
      const a = parseArg(arg);
      if (a.layers && argOf(a.layers) !== argOf(layers)) { layers = a.layers; save(); renderAll(); }
    };
    // przyciski warstw: kliknięcie łapiemy na kontenerze
    $(".rb-btns").addEventListener("click", (e) => {
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
      remember("radio", argOf(layers));
    });
    // lotnisko z paska ATIS albo plakietki TWR → AERODROME (krok do cofnięcia)
    el.addEventListener("click", (e) => {
      const a = e.target.closest(".rb-at[data-icao], .rb-pl.twr[data-icao]");
      if (a) navigate("aerodrome", a.dataset.icao);
    });
    // plakietka TWR z klawiatury (tabindex, role=button): Enter albo spacja
    el.addEventListener("keydown", (e) => {
      const a = e.target.closest?.(".rb-pl.twr[data-icao]");
      if (a && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); navigate("aerodrome", a.dataset.icao); }
    });

    // --- LOA: kod FIR-u sąsiada otwiera panel (drugie kliknięcie, ✕ albo Esc zamyka); bez kroku w historii
    const markLoa = () => el.querySelectorAll(".rb-fh").forEach((x) => x.classList.toggle("sel", x.dataset.fir === loaFir));
    const radioOf = (cs) => d?.pos?.[cs]?.name || "";
    // panel po tej stronie FIR-u (kod i kafelki), gdzie jest więcej miejsca, i nie szerszy niż to miejsce (loaPlace):
    // kod i okienka klikniętego FIR-u zostają widoczne, a z nimi inne FIR-y tej strony (inny FIR jednym kliknięciem)
    function placeLoa() {
      if (!loaFir || loaBox.hidden) return;
      const gr = page.getBoundingClientRect();
      const rs = [...el.querySelectorAll(".rb-nbs [data-fir]")].filter((e) => e.dataset.fir === loaFir)
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
    el.addEventListener("click", (e) => {
      const hd = e.target.closest(".rb-fh[data-fir]");
      if (hd) openLoa(hd.dataset.fir, hd.dataset.title || "");
    });
    el.addEventListener("keydown", (e) => {
      const hd = e.target.closest?.(".rb-fh[data-fir]");
      if (hd && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openLoa(hd.dataset.fir, hd.dataset.title || ""); }
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

    // --- dymek (jeden pływający, stałej szerokości – radio.css) i podświetlenie granicy pod plakietką. Miejsce: tipPos
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
      const svg = lbl?.closest(".rb-map")?.querySelector("svg");
      if (k && svg && lbl.classList.contains("rb-pl")) svg.querySelectorAll(`.rb-own [data-k="${CSS.escape(k)}"]`).forEach((p) => p.classList.toggle("hl", onOff));
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
        // menu albo adres bez stanu (albo stary z przekrojem LOW): bieżące warstwy w adresie (bez nowego kroku)
        remember("radio", argOf(layers));
        if (Date.now() - lastLoad > REFRESH_MS) load();
        else later();
      },
      destroy() {
        clearInterval(timer); ro.disconnect();
        document.removeEventListener("visibilitychange", onVis);
      },
    };
  },
};

// podgląd: mapa (svg) w swoich komórkach siatki, plakietki i mały tytuł
function mapHtml(m) {
  return `<section class="rb-map ${m.cls}" data-map="${m.key}"><svg class="rb-svg" aria-hidden="true"></svg>`
    + `<div class="rb-lbls"></div><div class="rb-title"></div></section>`;
}
