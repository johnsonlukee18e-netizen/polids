import { api, esc, h, lsGet, lsSet, ONLINE_EVENT } from "./api.js";
import { colorFor } from "./airspace.js";
import { dissolve, pointIn, ringStats } from "./dissolve.js";
import { EPWW_BBOX, FMP_LS, LEVEL_FT, bboxOf, bboxOrDefault, flText, pathAll, pathOf, projection, ringsOf, sliceAt } from "./radioboard.js";
import { capOf, fmpRows, loadClass, scnCond, scnEnabledIdle, scnTimeText, scnTip, tvLabel } from "./viffchart.js";

// OTHER › FMP (0.13.0, issue #23): sektory (traffic volumes) w tabeli SECTOR | CAPACITY | OCCUPANCY jak FMP PANDORY,
// z tych samych danych co panel sektorów na MAP (GET /api/viff/sectors, jedno zapytanie zbiorcze z cache).
// SECTOR = id bez prefiksu "EP-" (dymek: opis jak "sector B upper", "TMA EPWA"), CAPACITY (ENTRIES) = wejścia
// w bieżącej godzinie i przepustowość wejść "18 (45)", OCCUPANCY = samoloty w sektorze teraz i przepustowość chwilowa
// "9 (14)"; "–" bez liczby albo bez limitu. Przy regulacji obowiązującej teraz przepustowość z regulacji (niższa
// z deklarowanej i regulowanej), liczba w nawiasie czerwona, w dymku obie wartości. Aktywne sektory na szarym tle
// (ciemniej niż w PANDORZE: biały tekst zostaje czytelny), nieaktywne na czarnym, bez pasków zebry; aktywne na
// początku, potem sektory po literze (L, M, H), kombinacje, TMA i części FIR. Liczba żółta od 90 % przepustowości,
// czerwona powyżej (te same progi co wykres na MAP); id sektora czerwone, gdy obowiązuje regulacja.
// 0.13.1 (issue #25): klik w wiersz pokazuje po prawej wykresy ENTRY i OCC tego sektora (GET /api/viff/sectors/<TV>):
// ENTRY = wejścia w kolejnych 60 min co 20 min wobec przepustowości na godzinę, OCC = samoloty w sektorze minuta po
// minucie wobec progu zajętości; wspólna oś czasu od pełnej godziny przed bieżącą do +5 h, linia "teraz", przepustowość
// przerywana, regulacja czerwona. Drugi klik w ten sam wiersz albo ✕ zamyka wykresy; bez wyboru w panelu jedno zdanie.
// Wybrany sektor jest w adresie (#other/fmp/EP-BH, onPick); bez listy lotów (tylko wykresy).
// Odświeżanie co 60 s, gdy podzakładka jest na ekranie (wykres tylko przy wybranym sektorze); po powrocie serwera
// (ONLINE_EVENT) od razu.
// 0.14.0 (właściciel projektu): nad tabelą pasek CONFIGURATION z konfiguracjami sektorów ACC EPWW (GET /api/radio/configs, tabela
// Właściciela projektu w data/seed/fmp_configs.json): mały przycisk na każdy kod, w grupach wg liczby stanowisk (1..5), w dymku
// "2N: ALL + NFIR" ze znakami i częstotliwościami. Konfiguracja zalogowanych teraz ma znak NOW; gdy zestaw online nie
// pasuje do żadnej, krótka linia mówi, co jest otwarte ("Now: ALL+SFIR, not in the table"). Klik wybiera konfigurację
// (drugi klik = żadna); wybrana pokazuje panel ze stanowiskami (nazwa z tabeli, znak, częstotliwość, online albo nie)
// i warstwami sektorów każdego (LOW, MID, HIGH) oraz trzy małe podglądy LOW/MID/HIGH w kolorach stanowisk jak na MAP
// (colorFor), z nazwą stanowiska w jego obszarze. Z wybraną konfiguracją tabela grupuje sektory EP-<litera><L|M|H>
// pod stanowiskiem, które obsługuje tę warstwę sektora (L = LOW, M = MID, H = HIGH); sektory warstwy bez stanowiska
// konfiguracji w grupie NOT COVERED, TMA, części FIR i kombinacje na końcu w OTHER. Bez konfiguracji tabela jak dotąd.
// Adres: "#other/fmp/2N", "#other/fmp/2N/EP-BH", stare "#other/fmp/EP-BH" dalej działa (parseFmpArg, fmpArg); ostatnia
// konfiguracja w pamięci przeglądarki (savedCfg / saveCfg: OTHER otwiera FMP z nią, przycisk FMP na RADIO też).
// 0.14.2 (issue #35, "scenario preview oraz listę scenariuszy aktywnych i nieaktywnych"): w pasku nad tabelą przełącznik
// SECTORS | SCENARIOS. SCENARIOS: po lewej lista scenariuszy z tej samej odpowiedzi /api/viff/sectors (bez nowych
// zapytań) w grupach ACTIVE i INACTIVE: id, warunki stanowisk, okna czasu (TIME, bez okna H24), traffic volumes
// (w dymku przepustowości ze scenariusza), a z wybraną konfiguracją kolumna z jej kodem: czy warunki stanowisk ACC
// EPWW są spełnione (yes / no / ? = zależy od innych stanowisk; czasu i rezerwacji nie sprawdzamy). Klik w scenariusz
// = po prawej SCENARIO PREVIEW: jego traffic volumes z przepustowością ze scenariusza wobec ruchu teraz (CAPACITY NOW =
// przepustowość teraz), z konfiguracją w grupach stanowisk, trzy małe mapy LOW/MID/HIGH z obszarami tych traffic
// volumes, a klik w traffic volume = wykresy ENTRY i OCC z liniami przepustowości ze scenariusza. Podgląd liczy
// przeglądarka z danych do odczytu: nic nie jest włączane (napis "Preview only: nothing is activated."); endpointów
// zapisujących aplikacja nie wywołuje. Opisu scenariusza (wolny tekst) nie pokazujemy, jak na MAP. Adres:
// "#other/fmp/scenarios", "#other/fmp/scenarios/EP_NFIR", "#other/fmp/scenarios/EP_NFIR/EP-BH", z konfiguracją
// "#other/fmp/2N/scenarios/EP_NFIR"; słowo "scenarios" w adresie, bo id scenariusza bywa też id traffic volume
// (EP-WATMA). SECTORS po podglądzie zostawia wybrany traffic volume (wykresy z prawdziwą przepustowością).
// Przegląd 0.14.2: ACTIVE = scenariusz obowiązuje teraz (isActive z vIFF); włączony, ale jeszcze nieobowiązujący
// (enabled) jest w INACTIVE z dopiskiem "enabled, not active now" w dymku wiersza i podglądu. Kolumna TIME zawija się
// tylko między datą a godzinami i po półpauzie przed datą końca okna dłuższego niż doba (lista mieści się w 424 px jak
// tabela SECTORS); id scenariusza to wolny tekst (cleanScn), a wiersz scenariusza, którego id adres nie uniesie, nie
// wygląda na klikalny i ma dymek "No preview". Klik w traffic volume podglądu przewija panel do jego wykresu (raz,
// odświeżenie nie przewija); nieudane wczytanie listy nie zostawia w panelu "Loading".

const REFRESH_MS = 60000;

const NUM_CLS = { near: " near", over: " over" };
const DASH = "\u2013", DOT = " \u00b7 ";
// id sektora z adresu albo z wiersza tabeli: wielkie litery ("ep-bh" → "EP-BH", też "ED-EDWW-ALR"); inne napisy = "" (nic)
export const cleanTv = (s) => { const t = String(s ?? "").trim().toUpperCase(); return /^[A-Z]{2}-[A-Z0-9-]{1,20}$/.test(t) ? t : ""; };
// 0.14.0 (właściciel projektu): kod konfiguracji sektorów z adresu albo z pamięci: cyfra i litera ("2n" → "2N"); inne napisy = ""
export const cleanCfg = (s) => { const t = String(s ?? "").trim().toUpperCase(); return /^[1-9][A-Z]$/.test(t) ? t : ""; };
// 0.14.2 (issue #35): id scenariusza z adresu albo z wiersza listy wielkimi literami ("ep_nfir" → "EP_NFIR"); przegląd
// 0.14.2: id scenariusza w vIFF to wolny tekst ("EP-KK.TMA", "EP WAA1"), więc każdy napis do 64 znaków bez "/" (dzieli
// adres) i bez znaków sterujących; adres koduje i odkodowuje router (hashOf, parseHash); inne napisy = ""
export const cleanScn = (s) => { const t = String(s ?? "").trim().toUpperCase(); return t.length <= 64 && /^[^\/\u0000-\u001f\u007f]+$/.test(t) ? t : ""; };
// adres podzakładki → {cfg, tv, view, scn}: "2N", "2N/EP-BH", stare "EP-BH" (sam sektor, bez konfiguracji), 0.14.2:
// "scenarios", "scenarios/EP_NFIR", "2N/scenarios/EP_NFIR/EP-BH" (view = "scenarios", traffic volume tylko przy
// scenariuszu); zły kod, sektor albo scenariusz = ""
export const parseFmpArg = (s) => { const p = String(s ?? "").split("/"), cfg = cleanCfg(p[0]), r = cfg ? p.slice(1) : p, v = String(r[0] ?? "").trim().toLowerCase() === "scenarios", scn = v ? cleanScn(r[1]) : ""; return { cfg, tv: v ? (scn ? cleanTv(r.slice(2).join("/")) : "") : cleanTv(r.join("/")), view: v ? "scenarios" : "", scn }; };
// stan → adres podzakładki: "2N/EP-BH", "2N", "EP-BH", "" albo (0.14.2) "2N/scenarios/EP_NFIR/EP-BH", "scenarios"
export const fmpArg = (cfg, tv, view = "", scn = "") => (view === "scenarios" ? [cleanCfg(cfg), "scenarios", cleanScn(scn), cleanScn(scn) ? cleanTv(tv) : ""] : [cleanCfg(cfg), cleanTv(tv)]).filter(Boolean).join("/");
// ostatnio pokazana konfiguracja w pamięci przeglądarki (lsGet / lsSet: bez localStorage po prostu bez pamięci)
export const LS_CFG = FMP_LS;
export const savedCfg = () => cleanCfg(lsGet(LS_CFG));
export const saveCfg = (code) => lsSet(LS_CFG, cleanCfg(code));

// "18 (45)" jak pairText; przepustowość z regulacji w nawiasie czerwona
function pairHtml(n, cap, reg) {
  if (n === null && cap === null) return DASH;
  const c = cap === null ? DASH : reg ? `<span class="fmp-regcap">${esc(cap)}</span>` : esc(cap);
  return `${n === null ? DASH : esc(n)} (${c})`;
}
// extra = dodatkowe komórki na końcu wiersza (0.14.2: CAPACITY NOW w podglądzie scenariusza)
function rowHtml(r, sel, extra = "") {
  return `<tr class="${r.active ? "on" : "off"}${r.id === sel ? " sel" : ""}" data-tv="${esc(r.id)}">
    <td class="fmp-sec${r.restricted ? " reg" : ""}" title="${esc(r.sectorTip)}">${esc(r.code)}</td>
    <td class="fmp-num${NUM_CLS[r.entriesCls] || ""}" title="${esc(r.capacityTip)}">${pairHtml(r.entries, r.entriesMax, r.capacityReg)}</td>
    <td class="fmp-num${NUM_CLS[r.occupancyCls] || ""}" title="${esc(r.occupancyTip)}">${pairHtml(r.occupancy, r.occupancyMax, r.occupancyReg)}</td>${extra}</tr>`;
}

// --- 0.14.0 (właściciel projektu): konfiguracje sektorów ACC (odpowiedź /api/radio/configs: configs, current, layers, geo)
const LAYER_KEYS = ["LOW", "MID", "HIGH"];
const BAND_LAYER = { L: "LOW", M: "MID", H: "HIGH" };
// "ALL+NFIR" → "ALL + NFIR"
const spaced = (label) => String(label ?? "").split("+").join(" + ");
const letters = (xs) => (Array.isArray(xs) && xs.length ? xs.join(" ") : DASH);
// kolor stanowiska jak na MAP; znak spoza tabeli kolorów: kolor z palety wg znaku (colorFor)
const swatch = (cs) => `<i class="fmp-sw" style="background:${esc(colorFor(cs))}"></i>`;

// konfiguracje w grupach wg liczby stanowisk (1..5), w kolejności tabeli: [{size, items}]
export function cfgGroups(cfgs) {
  const by = new Map();
  (Array.isArray(cfgs) ? cfgs : []).forEach((c) => {
    const n = Number(c?.size) || (Array.isArray(c?.positions) ? c.positions.length : 0);
    if (n > 0 && c?.code) by.set(n, [...(by.get(n) || []), c]);
  });
  return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([size, items]) => ({ size, items }));
}
// dymek przycisku: "2N: ALL + NFIR", pod spodem stanowiska ze znakiem i częstotliwością; now = to konfiguracja teraz
export const cfgTip = (c, now = false) => [`${c.code}: ${spaced(c.label)}`,
  ...(c.positions || []).map((p) => `${p.name} ${p.callsign} ${p.frequency || DASH}`), ...(now ? ["Controllers online now"] : [])].join("\n");
// linia o tym, co jest otwarte teraz, gdy zestaw online nie pasuje do żadnej konfiguracji (pasuje: "" – znak NOW
// na przycisku); bez danych sieci: nie wiadomo
export function cfgNowText(cur) {
  if (!cur) return "";
  if (!cur.ok) return `Now: unknown (${cur.error || "network data unavailable"})`;
  if (cur.code) return "";
  const names = Array.isArray(cur.names) ? cur.names : [];
  return names.length ? `Now: ${names.join("+")}, not in the table` : "Now: no EPWW ACC position online";
}
// pasek CONFIGURATION: grupy przycisków, znak NOW, linia "Now: ..."; cd = null (jeszcze nie ma albo błąd: err)
export function cfgBarHtml(cd, sel = "", err = "") {
  const head = `<span class="fmp-cfg-t" title="ACC sector configurations of FIR EPWW: click one to see its positions and sectors">CONFIGURATION</span>`;
  if (!cd) return head + (err ? `<span class="fmp-cfg-msg error">${esc(err)}</span>` : `<span class="fmp-cfg-msg hint">Loading\u2026</span>`);
  const now = cd.current?.ok ? cd.current.code : null;
  const groups = cfgGroups(cd.configs).map((g) => `<span class="fmp-cfg-g"><span class="fmp-cfg-n" title="${g.size} position${g.size === 1 ? "" : "s"}">${g.size}</span>`
    + g.items.map((c) => `<button type="button" class="fmp-cb${c.code === sel ? " on" : ""}${c.code === now ? " now" : ""}" data-cfg="${esc(c.code)}"`
      + ` aria-pressed="${c.code === sel}" title="${esc(cfgTip(c, c.code === now))}">${esc(c.code)}`
      + `${c.code === now ? `<span class="fmp-cb-now">NOW</span>` : ""}</button>`).join("") + "</span>").join("");
  const line = cfgNowText(cd.current);
  return head + (groups || `<span class="fmp-cfg-msg hint">No configurations.</span>`)
    + (line ? `<span class="fmp-cfg-now">${esc(line)}</span>` : "")
    + (err ? `<span class="fmp-cfg-msg error">Not refreshed: ${esc(err)}</span>` : "");
}

// panel wybranej konfiguracji: stanowiska (nazwa z tabeli, znak, częstotliwość, online albo nie) z warstwami sektorów,
// które obsługują, i wiersz warstw bez nikogo (Not covered); cur = current z /api/radio/configs, layers = granice warstw
export function cfgPanelHtml(c, cur = null, layers = {}) {
  const on = cur?.ok && Array.isArray(cur.positions) ? new Set(cur.positions) : null;
  const lyTip = (ly) => `${ly}${layers?.[ly]?.label ? `: ${layers[ly].label}` : ""}`;
  const cells = (by) => LAYER_KEYS.map((ly) => `<td class="fmp-cp-ly">${esc(letters(by?.[ly]))}</td>`).join("");
  const rows = (c.positions || []).map((p) => {
    const st = on ? (on.has(p.callsign) ? "online" : "offline") : "unknown";
    return `<tr><td class="fmp-cp-pos">${swatch(p.callsign)}${esc(p.name)}</td><td class="fmp-cp-cs">${esc(p.callsign)}</td>`
      + `<td class="fmp-cp-fq">${esc(p.frequency || DASH)}</td><td class="fmp-cp-st ${st}">${st}</td>${cells(p.sectors)}</tr>`;
  }).join("");
  const free = LAYER_KEYS.some((ly) => c.free?.[ly]?.length)
    ? `<tr class="fmp-cp-free" title="Sector layers with no position of this configuration in their takeover order"><td colspan="4">Not covered</td>${cells(c.free)}</tr>` : "";
  const now = !!cur?.ok && cur.code === c.code;
  return `<div class="fmp-cp-h"><span class="fmp-cp-code">${esc(c.code)}</span><span class="fmp-cp-lbl">${esc(spaced(c.label))}</span>`
    + (now ? `<span class="fmp-cp-now" title="The controllers online now match this configuration">NOW</span>` : "") + "</div>"
    + `<table class="fmp-cp-tab"><thead><tr><th>POSITION</th><th>CALLSIGN</th><th>FREQ</th><th>STATUS</th>`
    + LAYER_KEYS.map((ly) => `<th title="${esc(lyTip(ly))}">${ly}</th>`).join("") + `</tr></thead><tbody>${rows}${free}</tbody></table>`;
}

// Mały podgląd warstwy (LOW/MID/HIGH) w konfiguracji c: wycinki ACC na wysokości podglądu jak na RADIO (sliceAt,
// LEVEL_FT: LOW FL330, MID FL350, HIGH FL400) w kolorze stanowiska, które obsługuje warstwę sektora (wycinki jednego
// stanowiska jako jeden obszar: dissolve.js; bez biblioteki albo po błędzie sumy same wycinki), warstwa bez nikogo
// szara, granica FIR EPWW i nazwa stanowiska z tabeli w jego obszarze. geo = {border, acc} z /api/radio/configs?geo=1
const PV_W = 160, PV_H = 150;
const areaOf = (g) => ringsOf(g).reduce((a, r) => a + ringStats(r).area, 0);
export function cfgPreviewSvg(geo, c, layer, ver = "") {
  const { P } = projection(bboxOrDefault(bboxOf(geo?.border)) || EPWW_BBOX, { x: 0, y: 0, w: PV_W, h: PV_H }, 0.04);
  const owner = new Map();
  (c?.positions || []).forEach((p) => (p.sectors?.[layer] || []).forEach((x) => owner.set(x, p)));
  const by = new Map(), free = [];
  sliceAt(geo?.acc, LEVEL_FT[layer]).forEach((sl) => {
    const p = owner.get(sl.letter);
    if (!p) { free.push(sl); return; }
    if (!by.has(p.callsign)) by.set(p.callsign, { p, slices: [] });
    by.get(p.callsign).slices.push(sl);
  });
  const lib = !!globalThis.polygonClipping?.union;
  const xy = (at) => { const [x, y] = P([at[1], at[0]]); return `x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}"`; };
  const areas = [...by.values()].map(({ p, slices }) => {
    const key = `fmp|${ver}|${layer}|${p.callsign}|${slices.map((s) => `${s.name}:${s.lo}`).sort().join(",")}`;
    const u = lib ? dissolve(key, slices.map((s) => s.geometry)) : null;
    const big = slices.reduce((a, s) => (areaOf(s.geometry) > areaOf(a.geometry) ? s : a));
    const at = (u && (u.at ||= pointIn(u.geometry))) || pointIn(big.geometry);
    const col = esc(colorFor(p.callsign));
    const shape = u ? `<path class="fmp-pv-a" fill="${col}" stroke="${col}" d="${pathAll(u.geometry, P)}"/>`
      : slices.map((s) => `<path class="fmp-pv-s" fill="${col}" d="${pathOf(s.geometry, P)}"/>`).join("");
    return { shape, label: at ? `<text class="fmp-pv-l" ${xy(at)}>${esc(p.name)}</text>` : "" };
  });
  return `<svg class="fmp-pv-svg" viewBox="0 0 ${PV_W} ${PV_H}" role="img" aria-label="${esc(`${layer} sectors of configuration ${c?.code || ""}`)}">`
    + free.map((s) => `<path class="fmp-pv-free" d="${pathOf(s.geometry, P)}"/>`).join("")
    + areas.map((a) => a.shape).join("") + `<path class="fmp-pv-b" d="${pathOf(geo?.border, P)}"/>`
    + areas.map((a) => a.label).join("") + "</svg>";
}
// trzy podglądy obok siebie: tytuł warstwy (w dymku granice warstwy i wysokość przekroju) i mapa
export function cfgPreviewsHtml(geo, c, ver = "", layers = {}) {
  if (!geo?.acc?.length) return `<p class="hint fmp-pv-none">No sector geometry.</p>`;
  return LAYER_KEYS.map((ly) => `<figure class="fmp-pv"><figcaption title="${esc(`${ly}${layers?.[ly]?.label ? ` (${layers[ly].label})` : ""}: sectors at ${flText(LEVEL_FT[ly])}`)}">`
    + `${ly} <span>${flText(LEVEL_FT[ly])}</span></figcaption>${cfgPreviewSvg(geo, c, ly, ver)}</figure>`).join("");
}

// sektor EP-<litera><L|M|H> → {letter, layer}; inne traffic volumes (TMA, części FIR, kombinacje) → null
export const tvSlot = (id) => { const m = /^EP-([A-Z])([LMH])$/.exec(String(id ?? "")); return m ? { letter: m[1], layer: BAND_LAYER[m[2]] } : null; };
// 0.14.1: warstwy sektorów, które obejmuje traffic volume: z jego wolumenów EPWW-<litera><L|M|H> (prawdziwe id vIFF to
// kombinacje: EP-FG, EP-GBFLMH, EP-JRLM, EP-NFIR), bez wolumenów z id (tvSlot); TMA albo wolumen spoza sektorów EPWW = []
export function tvSlots(r) {
  const vols = Array.isArray(r?.volumes) ? r.volumes.filter(Boolean) : [];
  if (!vols.length) { const s = tvSlot(r?.id); return s ? [s] : []; }
  const ms = vols.map((v) => /^EPWW-([A-Z])([LMH])$/.exec(String(v)));
  return ms.every(Boolean) ? ms.map((m) => ({ letter: m[1], layer: BAND_LAYER[m[2]] })) : [];
}
// Wiersze tabeli w grupach konfiguracji c: [{p: stanowisko, rows}, …] w kolejności stanowisk konfiguracji, potem
// {kind: "free"} (warstwa sektora bez stanowiska konfiguracji; tylko niepusta) i {kind: "other"} (TMA, części FIR,
// kombinacje kilku stanowisk, nieznane litery; tylko niepusta). Traffic volume trafia do stanowiska, które obsługuje
// wszystkie jego warstwy sektorów (tvSlots). Kolejność wierszy w grupie jak bez konfiguracji (fmpRows)
export function cfgGroupRows(rows, c) {
  const groups = (c?.positions || []).map((p) => ({ p, rows: [] }));
  const free = { kind: "free", rows: [] }, other = { kind: "other", rows: [] };
  (rows || []).forEach((r) => {
    const ss = tvSlots(r);
    const covers = (sec) => ss.length > 0 && ss.every((s) => sec?.[s.layer]?.includes(s.letter));
    const g = groups.find((x) => covers(x.p.sectors));
    if (g) g.rows.push(r);
    else if (covers(c?.free)) free.rows.push(r);
    else other.rows.push(r);
  });
  return [...groups, ...[free, other].filter((g) => g.rows.length)];
}
// nagłówek grupy w tabeli (td, nie th: th w tabeli są przyklejone u góry); cols = liczba kolumn tabeli (0.14.2: podgląd
// scenariusza ma 4)
function groupHead(g, cols = 3) {
  if (g.p) {
    return `<tr class="fmp-grp"><td colspan="${cols}" title="${esc(`${g.p.name}: ${g.p.callsign} ${g.p.frequency || ""}`.trim())}">`
      + `${swatch(g.p.callsign)}${esc(g.p.name)}<span class="fmp-grp-sub">${esc(g.p.callsign)} ${esc(g.p.frequency || "")}</span></td></tr>`;
  }
  return g.kind === "free"
    ? `<tr class="fmp-grp free"><td colspan="${cols}" title="Sector layers with no position of this configuration">NOT COVERED</td></tr>`
    : `<tr class="fmp-grp other"><td colspan="${cols}" title="TMA, FIR-wide traffic volumes and combinations across positions">OTHER</td></tr>`;
}

// tabela dla odpowiedzi /api/viff/sectors; sel = id wybranego sektora (wiersz z klasą sel); czysta funkcja (testy w Node)
// 0.14.0 (właściciel projektu): cfg = wybrana konfiguracja z /api/radio/configs – wiersze w grupach stanowisk (cfgGroupRows); bez
// niej tabela dokładnie jak dotąd
export function fmpHtml(data, sel = "", cfg = null) {
  const rows = fmpRows(data);
  if (!rows.length) return `<p class="hint fmp-empty">No sectors.</p>`;
  const body = cfg ? cfgGroupRows(rows, cfg).map((g) => groupHead(g) + (g.rows.length ? g.rows.map((r) => rowHtml(r, sel)).join("")
    : `<tr class="fmp-none"><td colspan="3">No traffic volumes</td></tr>`)).join("") : rows.map((r) => rowHtml(r, sel)).join("");
  return `<table class="fmp-table${cfg ? " grouped" : ""}">
    <thead><tr><th title="Traffic volume: sector or area with a set capacity">SECTOR</th>
      <th title="Entries in the current hour (entry capacity per hour)">CAPACITY (ENTRIES)</th>
      <th title="Aircraft in the sector now (capacity at one time)">OCCUPANCY</th></tr></thead>
    <tbody>${body}</tbody></table>`;
}

// linia nad tabelą: godzina danych i liczba aktywnych
export function fmpInfo(data) {
  const rows = fmpRows(data), on = rows.filter((r) => r.active).length;
  const now = /^\d{4}$/.test(data?.now || "") ? `${data.now}Z${DOT}` : "";
  return rows.length ? `${now}${on} of ${rows.length} active (grey rows)` : "";
}

// --- wykresy ENTRY i OCC (odpowiedź /api/viff/sectors/<TV>). Wspólna oś czasu obu wykresów: lewy margines na liczby
// osi Y, prawy na wartość przepustowości; minuty okna od c.start ("HHMM"), c.minutes długości
const W = 600, H = 190, L = 34, R = 30, TOP = 12, BOTTOM = 18, PLOT = H - TOP - BOTTOM;
const xOf = (c, m) => +(L + (m / c.minutes) * (W - L - R)).toFixed(1);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
// minuta okna → "HHMM" (okno może przechodzić przez północ)
function clock(start, m) {
  const s = /^\d{4}$/.test(start || "") ? parseInt(start.slice(0, 2), 10) * 60 + parseInt(start.slice(2), 10) : 0;
  const t = (((s + m) % 1440) + 1440) % 1440;
  return String(Math.floor(t / 60)).padStart(2, "0") + String(t % 60).padStart(2, "0");
}
// najniższa regulacja obowiązująca w minucie m okna (przedziały [from, to) z backendu), null = bez regulacji
const regAt = (spans, m) => {
  const v = (spans || []).filter((s) => s.from <= m && m < s.to).map((s) => s.value);
  return v.length ? Math.min(...v) : null;
};
// regulacja wyznacza przepustowość, gdy nie jest wyższa od deklarowanej
const binds = (declared, reg) => reg !== null && (declared === null || reg <= declared);
const capTip = (declared, reg) => (reg === null ? (declared === null ? "no limit" : `capacity ${declared}`)
  : `regulated ${reg}, declared ${declared === null ? "no limit" : declared}`);
// odcinki stałej wartości at(m) dla minut 0..n-1 (linie przepustowości schodkami)
function segments(n, at) {
  const out = [];
  for (let m = 0; m < n; m += 1) {
    const v = at(m), last = out[out.length - 1];
    if (last && last.v === v) last.b = m + 1;
    else out.push({ a: m, b: m + 1, v });
  }
  return out.filter((s) => s.v !== null);
}
// podziałka osi Y: 0 i co najwyżej 4 okrągłe wartości do top
function ticks(top) {
  const step = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500].find((s) => top / s <= 4) || Math.ceil(top / 4);
  const out = [];
  for (let v = 0; v <= top; v += step) out.push(v);
  return out;
}
function axis(c, y, top) {
  const out = [];
  for (let m = 0; m <= c.minutes; m += 60) {
    const x = xOf(c, m);
    out.push(`<line x1="${x}" x2="${x}" y1="${TOP}" y2="${TOP + PLOT}" class="fmc-grid"/><text x="${x}" y="${H - 4}" class="fmc-ax">${clock(c.start, m)}</text>`);
  }
  ticks(top).forEach((v) => {
    out.push(`<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="fmc-grid"/><text x="${L - 5}" y="${y(v) + 4}" class="fmc-ax end">${v}</text>`);
  });
  out.push(`<line x1="${L}" x2="${W - R}" y1="${TOP + PLOT}" y2="${TOP + PLOT}" class="fmc-base"/>`);
  return out.join("");
}
// linia "teraz" nad słupkami
const nowLine = (c) => { const x = xOf(c, c.now_at); return `<line x1="${x}" x2="${x}" y1="${TOP - 6}" y2="${TOP + PLOT}" class="fmc-now"/>`; };
const capLines = (c, segs, y, cls) => segs.map((s) => `<line x1="${xOf(c, s.a)}" x2="${xOf(c, s.b)}" y1="${y(s.v)}" y2="${y(s.v)}" class="${cls}"/>`).join("");
const capText = (y, v, reg) => (v === null ? "" : `<text x="${W - R + 4}" y="${y(v) + 4}" class="fmc-capt${reg ? " reg" : ""}">${v}</text>`);
const scale = (top) => { const max = top * 1.12; return (v) => +(TOP + PLOT - (v / max) * PLOT).toFixed(1); };

// ENTRY: słupek co c.step minut z liczbą wejść w kolejnych c.span minutach; kolor z obciążenia wobec przepustowości
// (niższa z deklarowanej i regulowanej), słupki, których 20 minut już minęło, przygaszone
export function entrySvg(c) {
  const list = c.entries || [];
  const caps = list.map((e) => capOf(num(e.cap), num(e.reg)));
  const top = Math.max(4, ...list.map((e) => e.count || 0), ...caps.filter((v) => v !== null));
  const y = scale(top);
  const bw = Math.max(1, xOf(c, c.step) - xOf(c, 0) - 4);
  const bars = list.map((e, i) => {
    const n = e.count || 0, x = +(xOf(c, e.from) + 2).toFixed(1), yy = y(n);
    const past = e.from + c.step <= c.now_at ? " past" : "";
    const tip = `${clock(c.start, e.from)}${DASH}${clock(c.start, e.from + c.span)}Z: ${n} ${n === 1 ? "entry" : "entries"} in ${c.span} min, `
      + capTip(num(e.cap), num(e.reg));
    return `<rect x="${x}" y="${yy}" width="${bw}" height="${+(TOP + PLOT - yy).toFixed(1)}" class="fmc-${loadClass(n, caps[i])}${past}"><title>${esc(tip)}</title></rect>`
      + (n ? `<text x="${+(x + bw / 2).toFixed(1)}" y="${yy - 3}" class="fmc-val">${n}</text>` : "");
  }).join("");
  const at = (m) => list[Math.floor(m / c.step)] || null;
  const declared = segments(c.minutes, (m) => num(at(m)?.cap));
  const reg = segments(c.minutes, (m) => { const e = at(m); return e && binds(num(e.cap), num(e.reg)) ? e.reg : null; });
  const last = list[list.length - 1];
  return `<svg viewBox="0 0 ${W} ${H}" class="fmc-svg" role="img" aria-label="Entries in 60 minutes, every 20 minutes">`
    + `${axis(c, y, top)}${bars}${capLines(c, declared, y, "fmc-cap")}${capLines(c, reg, y, "fmc-reg")}${nowLine(c)}`
    + `${last ? capText(y, caps[caps.length - 1], binds(num(last.cap), num(last.reg))) : ""}</svg>`;
}

// OCC: samoloty w sektorze w każdej minucie (kolumny tej samej wartości i koloru złączone), kolor wobec progu zajętości
// (niższy z deklarowanego i regulowanego); minuty przed "teraz" przygaszone
export function occSvg(c) {
  const occ = (c.occupancy || []).slice(0, c.minutes), cap = num(c.occupancy_cap);
  const capAt = (m) => capOf(cap, regAt(c.occupancy_reg, m));
  const regs = (c.occupancy_reg || []).map((s) => s.value).filter((v) => binds(cap, v));
  const top = Math.max(3, cap || 0, ...occ, ...regs);
  const y = scale(top);
  const runs = [];
  occ.forEach((v, m) => {
    const cls = `fmc-${loadClass(v, capAt(m))}${m < c.now_at ? " past" : ""}`, last = runs[runs.length - 1];
    if (last && last.v === v && last.cls === cls && last.b === m) last.b = m + 1;
    else runs.push({ a: m, b: m + 1, v, cls, reg: regAt(c.occupancy_reg, m) });
  });
  const cols = runs.filter((r) => r.v > 0).map((r) => {
    const when = r.b - r.a > 1 ? `${clock(c.start, r.a)}${DASH}${clock(c.start, r.b - 1)}Z` : `${clock(c.start, r.a)}Z`;
    const tip = `${when}: ${r.v} aircraft, ${capTip(cap, r.reg)}`;
    return `<rect x="${xOf(c, r.a)}" y="${y(r.v)}" width="${+(xOf(c, r.b) - xOf(c, r.a) + 0.3).toFixed(1)}" height="${+(TOP + PLOT - y(r.v)).toFixed(1)}" class="${r.cls}"><title>${esc(tip)}</title></rect>`;
  }).join("");
  const declared = segments(c.minutes, () => cap);
  const reg = segments(c.minutes, (m) => { const r = regAt(c.occupancy_reg, m); return binds(cap, r) ? r : null; });
  const end = c.minutes - 1, endReg = regAt(c.occupancy_reg, end);
  return `<svg viewBox="0 0 ${W} ${H}" class="fmc-svg" role="img" aria-label="Aircraft in the sector, per minute">`
    + `${axis(c, y, top)}${cols}${capLines(c, declared, y, "fmc-cap")}${capLines(c, reg, y, "fmc-reg")}${nowLine(c)}`
    + `${capText(y, capOf(cap, endReg), binds(cap, endReg))}</svg>`;
}

// nagłówek panelu: kod sektora (czerwony przy regulacji teraz), opis, ACTIVE / INACTIVE i ✕; note = komunikat obok
function headHtml(id, row, c, note = "") {
  const code = row?.code ?? String(id).replace(/^[A-Z]{2}-/, "");
  const active = c ? !!c.active : !!row?.active, restricted = c ? !!c.restricted : !!row?.restricted;
  return `<div class="fmc-head"><span class="fmc-code${restricted ? " reg" : ""}" title="${esc(id)}">${esc(code)}</span>`
    + `<span class="fmc-desc">${esc(c?.label || row?.label || tvLabel(id))}</span>`
    + (c || row ? `<span class="fmc-chip${active ? " on" : ""}">${active ? "ACTIVE" : "INACTIVE"}</span>` : "")
    + (note ? `<span class="fmc-msg error">${esc(note)}</span>` : "")
    + `<button type="button" class="fmc-close" title="Close the charts" aria-label="Close the charts">\u2715</button></div>`;
}

const regList = (c) => [...new Set([...(c.entries_reg || []).map((r) => `entries ${r.value} ${r.start}${DASH}${r.end}`),
  ...(c.occupancy_reg || []).map((r) => `occupancy ${r.value} ${r.start}${DASH}${r.end}`)])];

// panel z wykresami wybranego sektora; row = wiersz fmpRows (kod jak w tabeli) albo null; note = "Not refreshed: ..."
// 0.14.2: opts.scenario = id scenariusza, z którego jest przepustowość (podgląd scenariusza, scnChart)
export function fmpChartHtml(c, row = null, note = "", opts = {}) {
  const ec = num(c.entries_cap), oc = num(c.occupancy_cap), regs = regList(c);
  const quiet = !(c.occupancy || []).some((v) => v > 0) && !(c.entries || []).some((e) => e.count > 0);
  const peak = num(c.peak) ? `${DOT}peak ${c.peak} at ${esc(c.peak_at)}Z` : "";
  const scn = opts.scenario ? `scenario ${esc(opts.scenario)} ` : "";
  return `<div class="fmc">${headHtml(c.id, row, c, note)}
    <div class="fmc-meta">${scn}capacity: ${ec === null ? "no entry limit" : `${ec} entries/h`}${DOT}${oc === null ? "no occupancy limit" : `${oc} aircraft at once`}`
    + `${regs.length ? `<span class="fmc-regtxt">${DOT}regulated: ${esc(regs.join(", "))}</span>` : ""}</div>
    ${quiet ? `<p class="hint fmc-empty">No traffic in this period.</p>` : ""}
    <div class="fmc-charts">
      <div class="fmc-chart"><div class="fmc-title">ENTRY <span>entries in ${esc(c.span)} min, every ${esc(c.step)} min</span></div>${entrySvg(c)}</div>
      <div class="fmc-chart"><div class="fmc-title">OCC <span>aircraft in the sector, per minute</span></div>${occSvg(c)}</div>
    </div>
    <div class="fmc-legend"><span><i class="fmc-ok"></i>below 90 %</span><span><i class="fmc-near"></i>90${DASH}100 %</span>`
    + `<span><i class="fmc-over"></i>over capacity</span><span><i class="fmc-nolim"></i>no limit</span>`
    + `<span><i class="fmc-capl"></i>capacity</span><span><i class="fmc-regl"></i>regulated</span>`
    + `<span class="fmc-stat">${esc(c.now)}Z${peak}</span></div></div>`;
}

// panel bez wybranego sektora
export const fmpPickHtml = () => `<p class="hint fmp-pick">Click a sector to see its ENTRY and OCC charts.</p>`;
// pierwsze wczytanie wybranego sektora albo błąd bez wcześniejszego wykresu (✕ zamyka i wtedy)
export const fmpWaitHtml = (id, row = null, err = "") => `<div class="fmc">${headHtml(id, row, null)}`
  + (err ? `<p class="error fmc-err">${esc(err)}</p>` : `<p class="hint fmc-wait">Loading\u2026</p>`) + "</div>";

// --- 0.14.2 (issue #35): SCENARIOS i SCENARIO PREVIEW (scenariusze z odpowiedzi /api/viff/sectors: id, active, tvs
// [{id, entries_cap, occupancy_cap}], positions, anypositions, nopositions, start, end, times, booked)

// przełącznik widoku w pasku nad tabelą; view = "" (SECTORS) albo "scenarios"
const VIEWS = [["sectors", "SECTORS", "Traffic volumes with traffic and capacity now"],
  ["scenarios", "SCENARIOS", "Active and inactive scenarios: click one to preview its traffic volumes and capacities"]];
export const viewBarHtml = (view = "") => VIEWS.map(([v, label, tip]) => {
  const on = (view === "scenarios" ? "scenarios" : "sectors") === v;
  return `<button type="button" class="fmp-cb fmp-vb${on ? " on" : ""}" data-view="${v}" aria-pressed="${on}" title="${esc(tip)}">${label}</button>`;
}).join("");

// scenariusze z odpowiedzi: aktywne na początku, potem po id (jak backend)
const scnList = (data) => (Array.isArray(data?.scenarios) ? data.scenarios.filter((s) => s && s.id) : [])
  .sort((a, b) => (!!a.active !== !!b.active ? (a.active ? -1 : 1) : String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0));
// znak stanowiska ACC EPWW (też ze wzorcem jak "EPWW_D*_CTR"); tylko takie stanowiska ma konfiguracja
const ACC_CS = /^EPWW(?:_[A-Z0-9*]+)?_CTR$/;
// znak z gwiazdką ("EPWW_D*_CTR") jako wzorzec
const csRe = (p) => {
  const t = String(p).toUpperCase().replace(/[.+?^$|()[\]{}\\]/g, "\\$&").replace(/\*/g, "[A-Z0-9_]*");
  return new RegExp(`^${t}$`);
};
const capWords = (v, unit, none) => (num(v) === null ? none : `${v} ${unit}`);

// Warunki stanowisk scenariusza s przy konfiguracji cfg (stanowiska konfiguracji online, inne ACC EPWW offline):
// {state: "yes" | "no" | "unknown", text}; bez konfiguracji null. "no": stanowisko z positions offline, z nopositions
// online albo żadne z anypositions nie może być online; "unknown": warunek dotyczy stanowiska spoza ACC EPWW (APP,
// TWR), którego konfiguracja nie opisuje. Okien czasu i rezerwacji nie sprawdzamy.
export function scnMatch(s, cfg) {
  if (!cfg) return null;
  const on = (cfg.positions || []).map((p) => String(p.callsign || "").toUpperCase());
  const state = (p) => (!ACC_CS.test(String(p).toUpperCase()) ? "unknown" : on.some((c) => csRe(p).test(c)) ? "online" : "offline");
  const pos = s?.positions || [], any = s?.anypositions || [], no = s?.nopositions || [];
  const why = [...pos.filter((p) => state(p) === "offline").map((p) => `${p} not open`),
    ...no.filter((p) => state(p) === "online").map((p) => `${p} open`),
    ...(any.length && any.every((p) => state(p) === "offline") ? [`none of ${any.join(", ")} open`] : [])];
  const unk = [...new Set([...pos, ...any, ...no].filter((p) => state(p) === "unknown"))];
  const head = `With ${cfg.code} (${spaced(cfg.label)})`;
  if (why.length) return { state: "no", text: `${head}: not met (${why.join("; ")})` };
  if (unk.length) return { state: "unknown", text: `${head}: depends on other positions (${unk.join(", ")})` };
  return { state: "yes", text: `${head}: the position conditions are met` };
}
const MATCH_TEXT = { yes: "yes", no: "no", unknown: "?" };
// przegląd 0.14.2: komórka TIME zawija się tylko między słowami (data, okno godzin) i po półpauzie przed datą końca
// ("2026-11-20 1900–" / "2026-11-22 2100"), nigdy w środku daty ani okna: każdy kawałek w <span> bez zawijania (CSS)
export const timeHtml = (t) => String(t ?? "").split(" ")
  .map((w) => w.split(/(?<=\u2013)(?=\d{4}-)/).map((x) => `<span>${esc(x)}</span>`).join("<wbr>")).join(" ");
const NOT_CHECKED = "Time windows and bookings are not checked.";
const NO_PREVIEW = "\nNo preview: this scenario id cannot be used in the page address.";

// lista scenariuszy (lewa strona widoku SCENARIOS): grupy ACTIVE i INACTIVE, wiersz = scenariusz (sel = id wybranego);
// cfg = wybrana konfiguracja: kolumna z jej kodem (scnMatch). Czysta funkcja (testy w Node)
export function scnListHtml(data, sel = "", cfg = null) {
  if (data?.scenarios_ok === false) return `<p class="error fmp-empty">Scenarios unavailable.</p>`;
  const all = scnList(data);
  if (!all.length) return `<p class="hint fmp-empty">No scenarios.</p>`;
  const cols = cfg ? 5 : 4, prefix = (data?.prefix || "EP") + "-";
  const code = (id) => (String(id).startsWith(prefix) ? String(id).slice(prefix.length) : String(id));
  const row = (s) => {
    const id = cleanScn(s.id), tvs = (s.tvs || []).filter((t) => t?.id), m = scnMatch(s, cfg);
    const tvTip = tvs.map((t) => `${t.id}: ${capWords(t.entries_cap, "entries/h", "no entry limit")}, `
      + `${capWords(t.occupancy_cap, "aircraft at once", "no occupancy limit")}`).join("\n") || "No traffic volumes";
    // przegląd 0.14.2: id, którego adres nie uniesie ("/", znaki sterujące, ponad 64 znaki; cleanScn = ""): wiersz bez
    // data-scn, bez kursora rączki i podświetlenia (CSS fmp-scn-nopv) i z dymkiem, że podglądu nie ma; inaczej wyglądałby
    // na klikalny, a klik nic nie robi
    return `<tr class="${s.active ? "on" : "off"}${id && id === sel ? " sel" : ""}${id ? "" : " fmp-scn-nopv"}"${id ? ` data-scn="${esc(id)}"` : ""}>`
      + `<td class="fmp-sec" title="${esc(scnTip(s) + (id ? "" : NO_PREVIEW))}">${esc(s.id)}</td>`
      + `<td class="fmp-scn-cond">${esc(scnCond(s, { times: false }))}</td>`
      + `<td class="fmp-scn-time">${timeHtml(scnTimeText(s))}</td>`
      + `<td class="fmp-scn-tvs" title="${esc(tvTip)}">${esc(tvs.map((t) => code(t.id)).join(" ") || DASH)}</td>`
      + (m ? `<td class="fmp-scn-m ${m.state}" title="${esc(`${m.text}. ${NOT_CHECKED}`)}">${MATCH_TEXT[m.state]}</td>` : "") + "</tr>";
  };
  const group = (label, tip, list, none) => `<tr class="fmp-grp"><td colspan="${cols}" title="${tip}">${label}<span class="fmp-grp-sub">${list.length}</span></td></tr>`
    + (list.length ? list.map(row).join("") : `<tr class="fmp-none"><td colspan="${cols}">${none}</td></tr>`);
  const on = all.filter((s) => s.active), off = all.filter((s) => !s.active);
  return `<table class="fmp-table fmp-scn-table">
    <thead><tr><th title="Scenario: a set of traffic volumes with their own capacities">SCENARIO</th>
      <th title="Positions that must be online (or offline) for the scenario">CONDITION</th>
      <th title="Time windows of the scenario (UTC); H24 = no window">TIME</th>
      <th title="Traffic volumes of the scenario (hover: their capacities in the scenario)">TV</th>`
    + (cfg ? `<th title="${esc(`With configuration ${cfg.code} (${spaced(cfg.label)}) open: are the ACC position conditions met? `
      + `yes, no or ? (depends on other positions). ${NOT_CHECKED}`)}">${esc(cfg.code)}</th>` : "") + `</tr></thead>
    <tbody>${group("ACTIVE", "Scenarios active now (grey rows)", on, "No scenario is active now")}`
    + (off.length ? group("INACTIVE", "Scenarios not active now", off, "") : "") + "</tbody></table>";
}

// linia nad listą: godzina danych i liczba aktywnych scenariuszy
export function scnInfo(data) {
  const all = data?.scenarios_ok === false ? [] : scnList(data), on = all.filter((s) => s.active).length;
  const now = /^\d{4}$/.test(data?.now || "") ? `${data.now}Z${DOT}` : "";
  return all.length ? `${now}${on} of ${all.length} scenario${all.length === 1 ? "" : "s"} active (grey rows)` : "";
}

// Wiersze podglądu scenariusza s w kolejności jego traffic volumes: wiersz fmpRows z przepustowością ze scenariusza
// (także w godzinowych koszykach, bo tvNow bierze najpierw przepustowość godziny; regulacje TV zostają) i ruchem teraz,
// a nowEntries / nowOccupancy = przepustowość teraz (z regulacją) z prawdziwego wiersza tabeli
export function scnTvRows(data, s) {
  const by = new Map((data?.sectors || []).filter((t) => t && t.id).map((t) => [t.id, t]));
  const real = new Map(fmpRows(data).map((r) => [r.id, r]));
  const tvs = (s?.tvs || []).filter((t) => t && typeof t.id === "string" && t.id);
  const sectors = tvs.map((t) => {
    const tv = by.get(t.id) || { id: t.id, hours: [], occupancy: [], volumes: [] };
    const ec = num(t.entries_cap), oc = num(t.occupancy_cap);
    return { ...tv, entries_cap: ec, occupancy_cap: oc, hours: (tv.hours || []).map((x) => ({ ...x, entries_cap: ec })) };
  });
  const rows = new Map(fmpRows({ ...data, sectors }).map((r) => [r.id, r]));
  return tvs.map((t) => {
    const n = real.get(t.id);
    return { ...rows.get(t.id), nowKnown: !!n, nowEntries: n ? n.entriesMax : null, nowOccupancy: n ? n.occupancyMax : null };
  });
}

// 0.14.1 tvSlots, ale bez "wszystko albo nic": warstwy sektorów z wolumenów EPWW-<litera><L|M|H>, inne wolumeny
// (EPWA-TMA w EP-ALLFIR) pomijamy; bez wolumenów z id (tvSlot)
export function tvCover(r) {
  const vols = Array.isArray(r?.volumes) ? r.volumes.filter(Boolean) : [];
  if (!vols.length) { const s = tvSlot(r?.id); return s ? [s] : []; }
  return vols.map((v) => /^EPWW-([A-Z])([LMH])$/.exec(String(v))).filter(Boolean).map((m) => ({ letter: m[1], layer: BAND_LAYER[m[2]] }));
}

// Mała mapa warstwy (LOW/MID/HIGH) scenariusza jak cfgPreviewSvg: wycinki ACC na wysokości podglądu, obszar każdego
// traffic volume scenariusza zielony (wycinki jednego TV jako jeden obszar; bez biblioteki same wycinki), z kodem TV;
// reszta szara, granica FIR na wierzchu. rows = scnTvRows, sel = wybrany TV (jaśniej)
export function scnPreviewSvg(geo, rows, layer, ver = "", id = "", sel = "") {
  const { P } = projection(bboxOrDefault(bboxOf(geo?.border)) || EPWW_BBOX, { x: 0, y: 0, w: PV_W, h: PV_H }, 0.04);
  const slices = sliceAt(geo?.acc, LEVEL_FT[layer]), used = new Set();
  const lib = !!globalThis.polygonClipping?.union;
  const xy = (at) => { const [x, y] = P([at[1], at[0]]); return `x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}"`; };
  const areas = (rows || []).map((r) => {
    const letters = new Set(tvCover(r).filter((x) => x.layer === layer).map((x) => x.letter));
    const mine = slices.filter((sl) => letters.has(sl.letter));
    if (!mine.length) return null;
    mine.forEach((sl) => used.add(sl));
    const key = `scn|${ver}|${layer}|${r.id}|${mine.map((x) => `${x.name}:${x.lo}`).sort().join(",")}`;
    const u = lib ? dissolve(key, mine.map((x) => x.geometry)) : null;
    const big = mine.reduce((a, x) => (areaOf(x.geometry) > areaOf(a.geometry) ? x : a));
    const at = (u && (u.at ||= pointIn(u.geometry))) || pointIn(big.geometry);
    const cls = `fmp-pv-on${r.id === sel ? " sel" : ""}`;
    const shape = u ? `<path class="${cls}" d="${pathAll(u.geometry, P)}"/>`
      : mine.map((x) => `<path class="fmp-pv-s ${cls}" d="${pathOf(x.geometry, P)}"/>`).join("");
    return { shape, label: at ? `<text class="fmp-pv-l" ${xy(at)}>${esc(r.code)}</text>` : "" };
  }).filter(Boolean);
  return `<svg class="fmp-pv-svg" viewBox="0 0 ${PV_W} ${PV_H}" role="img" aria-label="${esc(`${layer} traffic volumes of scenario ${id}`)}">`
    + slices.filter((sl) => !used.has(sl)).map((sl) => `<path class="fmp-pv-free" d="${pathOf(sl.geometry, P)}"/>`).join("")
    + areas.map((a) => a.shape).join("") + `<path class="fmp-pv-b" d="${pathOf(geo?.border, P)}"/>`
    + areas.map((a) => a.label).join("") + "</svg>";
}
// trzy mapy obok siebie jak cfgPreviewsHtml i pod nimi traffic volumes spoza sektorów ACC (TMA)
export function scnPreviewsHtml(geo, rows, ver = "", layers = {}, id = "", sel = "") {
  const off = (rows || []).filter((r) => !tvCover(r).length).map((r) => r.code);
  const note = off.length ? `<p class="hint fmp-sp-off">Not on the maps: ${esc(off.join(", "))}</p>` : "";
  if (!geo?.acc?.length) return `<p class="hint fmp-pv-none">No sector geometry.</p>${note}`;
  return `<div class="fmp-pvs">` + LAYER_KEYS.map((ly) => `<figure class="fmp-pv"><figcaption title="${esc(`${ly}${layers?.[ly]?.label ? ` (${layers[ly].label})` : ""}: sectors at ${flText(LEVEL_FT[ly])}`)}">`
    + `${ly} <span>${flText(LEVEL_FT[ly])}</span></figcaption>${scnPreviewSvg(geo, rows, ly, ver, id, sel)}</figure>`).join("") + `</div>${note}`;
}

// wykres TV z przepustowością ze scenariusza t ({entries_cap, occupancy_cap}): linie przepustowości i kolory słupków
// wobec niej, regulacje TV zostają; c się nie zmienia
export function scnChart(c, t) {
  const ec = num(t?.entries_cap), oc = num(t?.occupancy_cap);
  return { ...c, entries_cap: ec, occupancy_cap: oc, entries: (c?.entries || []).map((e) => ({ ...e, cap: ec })) };
}

// wiersz podglądu: jak wiersz tabeli FMP i CAPACITY NOW = przepustowość teraz "40 / 14"
function spRowHtml(r, sel) {
  const now = `${r.nowEntries ?? DASH} / ${r.nowOccupancy ?? DASH}`;
  const tip = r.nowKnown ? `capacity now: ${capWords(r.nowEntries, "entries/h", "no entry limit")}, `
    + `${capWords(r.nowOccupancy, "aircraft at once", "no occupancy limit")}` : "Not in the traffic volume list now";
  return rowHtml(r, sel, `<td class="fmp-sp-now" title="${esc(tip)}">${esc(now)}</td>`);
}

// dymek znaku ACTIVE / INACTIVE w podglądzie; przegląd 0.14.2: włączony, ale nieobowiązujący teraz osobno
const chipTip = (s) => (s.active ? "Active now" : scnEnabledIdle(s) ? "Enabled, not active now" : "Not active now");

// SCENARIO PREVIEW (prawa strona widoku SCENARIOS): nagłówek (id, ACTIVE / INACTIVE, ✕), warunki, z konfiguracją
// linia scnMatch, zdanie, że to tylko podgląd, tabela traffic volumes z przepustowością ze scenariusza (z konfiguracją
// w grupach stanowisk), pod nią wykresy wybranego TV (sel; chart = odpowiedź /api/viff/sectors/<TV>, note / err jak
// w widoku SECTORS) i trzy mapy
export function scnPreviewHtml(data, s, { cfg = null, geo = null, ver = "", layers = {}, sel = "", chart = null, note = "", err = "" } = {}) {
  const rows = scnTvRows(data, s), m = scnMatch(s, cfg);
  const none = `<tr class="fmp-none"><td colspan="4">No traffic volumes</td></tr>`;
  const body = !rows.length ? none : cfg ? cfgGroupRows(rows, cfg).map((g) => groupHead(g, 4)
    + (g.rows.length ? g.rows.map((r) => spRowHtml(r, sel)).join("") : none)).join("") : rows.map((r) => spRowHtml(r, sel)).join("");
  let part = "";
  if (sel) {
    const row = rows.find((r) => r.id === sel) || null, t = (s.tvs || []).find((x) => x?.id === sel);
    part = `<div class="fmp-sp-chart">${chart && chart.id === sel && t ? fmpChartHtml(scnChart(chart, t), row, note, { scenario: s.id })
      : fmpWaitHtml(sel, row, err)}</div>`;
  }
  return `<div class="fmc fmp-sp"><div class="fmc-head"><span class="fmc-code" title="${esc(scnTip(s))}">${esc(s.id)}</span>`
    + `<span class="fmc-desc">scenario preview</span><span class="fmc-chip${s.active ? " on" : ""}" title="${chipTip(s)}">${s.active ? "ACTIVE" : "INACTIVE"}</span>`
    + `<button type="button" class="fmp-sp-close" title="Close the preview" aria-label="Close the preview">\u2715</button></div>`
    + `<div class="fmc-meta">${esc(scnCond(s))}</div>`
    + (m ? `<div class="fmp-sp-cfg ${m.state}" title="${NOT_CHECKED}">${esc(m.text)}</div>` : "")
    + `<p class="hint fmp-sp-note">Preview only: nothing is activated. Capacities as set in the scenario, traffic now.</p>`
    + `<table class="fmp-table fmp-sp-tab${cfg ? " grouped" : ""}"><thead><tr>`
    + `<th title="Traffic volume of the scenario">SECTOR</th>`
    + `<th title="Entries in the current hour (entry capacity per hour in the scenario)">CAPACITY (ENTRIES)</th>`
    + `<th title="Aircraft in the sector now (capacity at one time in the scenario)">OCCUPANCY</th>`
    + `<th title="Capacity in force now: entries per hour / aircraft at once">CAPACITY NOW</th></tr></thead><tbody>${body}</tbody></table>`
    + `${part}${scnPreviewsHtml(geo, rows, ver, layers, s.id, sel)}</div>`;
}
// panel bez wybranego scenariusza
export const scnPickHtml = () => `<p class="hint fmp-pick">Click a scenario to preview its traffic volumes and capacities.</p>`;

// start / activate(arg) / onPick(arg, fix): adres podzakładki (fmpArg: "2N/EP-BH", "2N", "EP-BH", "", 0.14.2 także
// "2N/scenarios/EP_NFIR/EP-BH"); fix = poprawa adresu bez nowego kroku historii (kod konfiguracji spoza tabeli,
// nieznany scenariusz albo traffic volume spoza scenariusza)
export function mountFmp(pane, { start = "", onPick = () => {} } = {}) {
  const root = h(`<div class="fmp">
    <div class="fmp-cfg" role="group" aria-label="Sector configuration"></div>
    <div class="fmp-cp" hidden></div>
    <div class="fmp-bar"><span class="fmp-vw" role="group" aria-label="FMP view"></span><span class="fmp-info hint"></span><span class="fmp-msg error"></span></div>
    <div class="fmp-main">
      <div class="fmp-scroll"><p class="hint">Loading\u2026</p></div>
      <aside class="fmp-side"></aside>
    </div>
  </div>`);
  pane.append(root);
  const info = root.querySelector(".fmp-info"), msg = root.querySelector(".fmp-msg"), box = root.querySelector(".fmp-scroll");
  const main = root.querySelector(".fmp-main"), side = root.querySelector(".fmp-side");
  const bar = root.querySelector(".fmp-cfg"), panel = root.querySelector(".fmp-cp"), vw = root.querySelector(".fmp-vw");
  let data = null, loadedAt = 0, seq = 0, dead = false;
  // sel: wybrany sektor ("" = żaden), chart: ostatni wykres (c.id = sektor), reveal: przewinąć tabelę do wiersza sel
  // (wybór z adresu, nie z kliknięcia)
  const first = parseFmpArg(start);
  // 0.14.2 (issue #35): view = "" (SECTORS) albo "scenarios", scnSel = wybrany scenariusz ("" = żaden; sel = jego
  // traffic volume z wykresami), chartNote / chartErr = błąd odświeżenia / wczytania wykresu w podglądzie, drawnScn =
  // scenariusz, którego podgląd jest w panelu (inny = panel przewinięty na początek)
  let view = first.view, scnSel = first.scn, chartNote = "", chartErr = "", drawnScn = "", shownTv = "";
  let sel = first.tv, chart = null, chartAt = 0, cseq = 0, reveal = view ? !!scnSel : !!sel;
  // 0.14.0 (właściciel projektu): cfgSel = wybrana konfiguracja ("" = żadna), cd = ostatnia odpowiedź /api/radio/configs (cdErr: błąd
  // ostatniego odświeżenia), geo = geometria podglądów (geoVer: jej wersja), grouped = konfiguracja, wg której jest
  // pogrupowana tabela na ekranie
  let cfgSel = first.cfg, cd = null, cdErr = "", cdAt = 0, kseq = 0, geo = null, geoVer = "", grouped = "";
  saveCfg(cfgSel);
  const visible = () => root.isConnected && root.offsetParent !== null;
  const rowOf = (id) => (data ? fmpRows(data).find((r) => r.id === id) || null : null);
  const cfgOf = () => (cfgSel && Array.isArray(cd?.configs) ? cd.configs.find((c) => c.code === cfgSel) || null : null);
  const scnOf = () => (scnSel && Array.isArray(data?.scenarios) ? data.scenarios.find((s) => cleanScn(s?.id) === scnSel) || null : null);
  const keepRow = () => box.querySelector("tr.sel")?.scrollIntoView?.({ block: "nearest" });
  const showRow = () => { reveal = false; keepRow(); };
  const here = () => fmpArg(cfgSel, sel, view, scnSel);
  // zaznaczenie wiersza bez rysowania tabeli od nowa (dymki i przewinięcie zostają); w widoku SCENARIOS wiersz scenariusza
  const mark = () => {
    if (view) box.querySelectorAll("tr[data-scn]").forEach((tr) => tr.classList.toggle("sel", cleanScn(tr.dataset.scn) === scnSel));
    else box.querySelectorAll("tr[data-tv]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.tv === sel));
    main.classList.toggle("open", view ? !!scnSel : !!sel);
  };
  // kod spoza tabeli (stary albo wpisany adres), gdy konfiguracje są już wczytane: bez konfiguracji, adres poprawiony
  // bez nowego kroku historii
  const fixCfg = () => {
    if (!cfgSel || !Array.isArray(cd?.configs) || cfgOf()) return;
    cfgSel = "";
    saveCfg("");
    onPick(here(), true);
  };
  // 0.14.2: scenariusz spoza listy albo traffic volume spoza scenariusza (stary albo wpisany adres), gdy lista jest już
  // wczytana: bez nich, adres poprawiony bez nowego kroku historii (lista niedostępna: adres zostaje)
  const fixScn = () => {
    if (!view || !data || data.scenarios_ok === false) return;
    let fix = false;
    if (scnSel && !scnOf()) { scnSel = ""; fix = true; }
    if (sel && !(scnOf()?.tvs || []).some((t) => t?.id === sel)) { sel = ""; ++cseq; chart = null; chartAt = 0; fix = true; }
    if (fix) { mark(); onPick(here(), true); }
  };
  const draw = (html) => { const top = side.scrollTop; side.innerHTML = html; side.scrollTop = top; };
  // przegląd 0.14.2: nowo wybrany traffic volume podglądu (wykres pod tabelą podglądu) przewinięty do widoku jak
  // scrollIntoView "nearest": wykres niższy od panelu cały, wyższy od góry (8 px odstępu); tylko panel (szerokie okno)
  // albo obszar tabeli i panelu (wąskie okno, panel pod listą), bez przewijania całego obszaru FMP; wykres już widoczny
  // zostaje, gdzie jest (wybrany wiersz też)
  // shownTv = traffic volume, którego wykres (albo błąd) panel już tak pokazał: odświeżenie co minutę (także po błędzie
  // wykresu) nie przewija; done = false: tylko "Loading" (wykres jeszcze przewinie się po wczytaniu)
  const showChart = (done = true) => {
    if (!view || !sel || shownTv === sel || !scnOf()) return;
    if (done) shownTv = sel;
    for (const sc of [side, main]) {
      const cb = side.querySelector(".fmp-sp-chart")?.getBoundingClientRect?.(), sb = sc.getBoundingClientRect?.();
      if (!cb || !sb || !(sc.scrollHeight > sc.clientHeight)) continue;
      const top = cb.top - sb.top - (sc.clientTop || 0) + sc.scrollTop - 8;
      const want = Math.min(top, top + 8 + cb.height - sc.clientHeight);
      if (want > sc.scrollTop) sc.scrollTop = want;
    }
  };
  // tabela (z grupami wybranej konfiguracji) albo lista scenariuszy; przewinięcie zostaje
  const drawTable = () => {
    if (!data) return;
    const c = cfgOf(), top = box.scrollTop;
    grouped = c ? c.code : "";
    box.innerHTML = view ? scnListHtml(data, scnSel, c) : fmpHtml(data, sel, c);
    box.scrollTop = top;
  };
  // przełącznik SECTORS | SCENARIOS; fokus z klawiatury wraca na przycisk tego samego widoku (jak w pasku CONFIGURATION)
  const drawView = () => {
    const a = globalThis.document?.activeElement, had = a && vw.contains?.(a) ? a.dataset?.view : "";
    vw.innerHTML = viewBarHtml(view);
    if (had === "sectors" || had === "scenarios") vw.querySelector?.(`button[data-view="${had}"]`)?.focus?.({ preventScroll: true });
  };
  // panel bez zapytania: SECTORS = wykres wybranego sektora (ostatni wczytany), "Loading" albo podpowiedź; SCENARIOS =
  // podgląd wybranego scenariusza (przewinięcie zostaje, nowy scenariusz od początku), "Loading" przed listą albo podpowiedź
  const drawSide = () => {
    if (!view) {
      drawnScn = "";
      side.innerHTML = !sel ? fmpPickHtml() : chart?.id === sel ? fmpChartHtml(chart, rowOf(sel)) : fmpWaitHtml(sel, rowOf(sel));
      return;
    }
    const s = scnOf();
    if (!s) {
      drawnScn = "";
      // przegląd 0.14.2: lista się nie wczytała (loadedAt bez data): bez "Loading" (nic już nie czeka; błąd jest
      // w liście), z wybranym scenariuszem krótki komunikat, bez wyboru pusto (nie ma czego kliknąć)
      side.innerHTML = !data && loadedAt ? (scnSel ? `<p class="error fmp-pick">Scenarios unavailable.</p>` : "")
        : scnSel && !data ? `<p class="hint fmp-pick">Loading\u2026</p>`
        : scnSel && data?.scenarios_ok === false ? `<p class="error fmp-pick">Scenarios unavailable.</p>` : scnPickHtml();
      return;
    }
    const html = scnPreviewHtml(data, s, { cfg: cfgOf(), geo, ver: geoVer, layers: cd?.layers || {}, sel,
      chart: chart?.id === sel ? chart : null, note: chartNote, err: chartErr });
    if (drawnScn === scnSel) draw(html);
    else { side.innerHTML = html; side.scrollTop = 0; shownTv = ""; }
    drawnScn = scnSel;
  };
  // pasek CONFIGURATION i panel wybranej konfiguracji (stanowiska i podglądy); przegląd 0.14.0: fokus z klawiatury
  // na przycisku konfiguracji wraca na przycisk tego samego kodu (pasek rysowany od nowa po wyborze i co 60 s)
  const drawCfg = () => {
    const a = globalThis.document?.activeElement, had = a && bar.contains?.(a) ? cleanCfg(a.dataset?.cfg) : "";
    bar.innerHTML = cfgBarHtml(cd, cfgSel, cdErr);
    if (had) bar.querySelector?.(`button[data-cfg="${had}"]`)?.focus?.({ preventScroll: true });
    const c = cfgOf();
    panel.hidden = !c;
    panel.innerHTML = c ? `<div class="fmp-cp-list">${cfgPanelHtml(c, cd.current, cd.layers)}</div>`
      + `<div class="fmp-pvs">${cfgPreviewsHtml(geo, c, geoVer, cd.layers)}</div>` : "";
  };

  // odświeżenie po błędzie zostawia ostatnią tabelę i pisze tylko komunikat nad nią
  const load = async () => {
    const my = ++seq;
    try {
      const d = await api("/api/viff/sectors");
      if (dead || my !== seq) return;
      data = d; loadedAt = Date.now();
      fixScn();
      drawTable();
      if (view) { drawSide(); if (chart?.id === sel || chartErr) showChart(); }
      info.textContent = view ? scnInfo(d) : fmpInfo(d);
      msg.textContent = "";
      if (reveal) showRow();
    } catch (e) {
      if (dead || my !== seq) return;
      loadedAt = Date.now();
      if (data) msg.textContent = `Not refreshed: ${e.message}`;
      else {
        box.innerHTML = `<p class="error fmp-err">${esc(e.message)}</p>`; info.textContent = "";
        // przegląd 0.14.2: panel wg tej samej reguły co po wczytaniu konfiguracji i wykresu (drawSide), bez "Loading"
        if (view) drawSide();
      }
    }
  };
  // konfiguracje i kto jest online (co 60 s z tabelą); geometria podglądów raz, potem tylko po zmianie wersji danych
  // (have); błąd odświeżenia zostawia ostatnie konfiguracje z komunikatem w pasku
  const loadCfg = async () => {
    const my = ++kseq;
    try {
      const d = await api(`/api/radio/configs${geo && geoVer ? `?have=${encodeURIComponent(geoVer)}` : "?geo=1"}`);
      if (dead || my !== kseq) return;
      if (d.geo) { geo = d.geo; geoVer = d.ver || ""; }
      cd = d; cdErr = ""; cdAt = Date.now();
      fixCfg();
    } catch (e) {
      if (dead || my !== kseq) return;
      cdAt = Date.now();
      cdErr = e.message;
    }
    drawCfg();
    if (grouped !== (cfgOf()?.code || "")) drawTable();
    // 0.14.2: podgląd scenariusza z konfiguracją (grupy, linia warunków) i z geometrią map
    if (view) drawSide();
  };
  // wykres wybranego sektora; spóźniona odpowiedź dla poprzedniego wyboru nic nie rysuje (cseq); błąd odświeżenia
  // zostawia ostatni wykres z komunikatem w nagłówku. 0.14.2: w widoku SCENARIOS wykres w podglądzie scenariusza
  // (drawSide, przepustowość ze scenariusza), to samo zapytanie
  const loadChart = async () => {
    const my = ++cseq, id = sel, fresh = chart?.id !== id;
    if (view) {
      if (!id || fresh) { chart = null; chartAt = 0; chartNote = chartErr = ""; drawSide(); }
      if (!id) { shownTv = ""; return; }
      // przegląd 0.14.2: "Loading" pod tabelą podglądu od razu widoczny, po wczytaniu jeszcze raz (wykres jest wyższy)
      if (fresh) showChart(false);
    } else {
      if (!id) { chart = null; chartAt = 0; side.innerHTML = fmpPickHtml(); return; }
      if (chart?.id !== id) side.innerHTML = fmpWaitHtml(id, rowOf(id));
    }
    try {
      const c = await api(`/api/viff/sectors/${encodeURIComponent(id)}`);
      if (dead || my !== cseq) return;
      chart = c; chartAt = Date.now();
      if (view) { chartNote = chartErr = ""; drawSide(); showChart(); return; }
      draw(fmpChartHtml(c, rowOf(id)));
      // w wąskim oknie wykresy stoją pod tabelą i ją skracają: nowo wybrany wiersz zostaje widoczny (odświeżenie co
      // minutę nie przewija)
      if (fresh) keepRow();
    } catch (e) {
      if (dead || my !== cseq) return;
      chartAt = Date.now();
      if (view) {
        if (chart?.id === id) chartNote = `Not refreshed: ${e.message}`;
        else { chart = null; chartErr = e.message; }
        drawSide();
        showChart();
        return;
      }
      if (chart?.id === id) draw(fmpChartHtml(chart, rowOf(id), `Not refreshed: ${e.message}`));
      else { chart = null; side.innerHTML = fmpWaitHtml(id, rowOf(id), e.message); }
    }
  };
  // user: klik (wiersz, ✕) = krok historii w OTHER (onPick); wybór z adresu (activate) bez onPick
  const pick = (id, user = false) => {
    sel = id;
    mark();
    if (!user && sel && data && !view) showRow();
    loadChart();
    if (user) onPick(here());
  };
  // 0.14.2: scenariusz z kliknięcia (krok historii) albo z adresu; podgląd bez wybranego traffic volume
  const pickScn = (id, user = false) => {
    scnSel = id;
    sel = "";
    mark();
    if (!user && scnSel && data) showRow();
    loadChart();
    if (user) onPick(here());
  };
  // 0.14.0: konfiguracja z kliknięcia (krok historii) albo z adresu; zapamiętana w przeglądarce; tabela od nowa w grupach
  // (wybrany sektor zostaje zaznaczony i widoczny); 0.14.2: lista scenariuszy z kolumną konfiguracji i podgląd od nowa
  const pickCfg = (code, user = false) => {
    cfgSel = code;
    saveCfg(cfgSel);
    fixCfg();
    drawCfg();
    drawTable();
    if (view) drawSide();
    // wybrany wiersz widoczny w tabeli; w niskim oknie cały obszar FMP zostaje, gdzie był (pasek pod kursorem)
    if (view ? scnSel : sel) { const top = root.scrollTop; keepRow(); root.scrollTop = top; }
    if (user) onPick(here());
  };
  // 0.14.2: widok z przełącznika (krok historii) albo z adresu (activate ustawia stan sam). SCENARIOS zaczyna bez wyboru;
  // SECTORS zostawia traffic volume wybrany w podglądzie (jego wykres z prawdziwą przepustowością)
  const setView = (v, user = false) => {
    if (v === view) return;
    view = v;
    scnSel = "";
    if (view) sel = "";
    showView();
    if (user) onPick(here());
  };
  // nowy widok na ekranie: przełącznik, tabela albo lista od początku (z wybranym wierszem), linia nad tabelą i panel
  const showView = () => {
    ++cseq;
    chartNote = chartErr = "";
    drawView();
    drawTable();
    box.scrollTop = 0;
    side.scrollTop = 0;
    info.textContent = data ? (view ? scnInfo(data) : fmpInfo(data)) : "";
    mark();
    keepRow();
    drawSide();
    loadChart();
  };
  box.addEventListener("click", (e) => {
    if (view) {
      const id = cleanScn(e.target.closest?.("tr[data-scn]")?.dataset.scn);
      if (id) pickScn(id === scnSel ? "" : id, true);
      return;
    }
    const id = cleanTv(e.target.closest?.("tr[data-tv]")?.dataset.tv);
    if (id) pick(id === sel ? "" : id, true);
  });
  side.addEventListener("click", (e) => {
    if (e.target.closest?.(".fmp-sp-close")) pickScn("", true);
    else if (e.target.closest?.(".fmc-close")) pick("", true);
    else if (view) {
      // 0.14.2: klik w traffic volume podglądu = jego wykresy pod tabelą (drugi klik zamyka)
      const id = cleanTv(e.target.closest?.("tr[data-tv]")?.dataset.tv);
      if (id) pick(id === sel ? "" : id, true);
    }
  });
  bar.addEventListener("click", (e) => {
    const code = cleanCfg(e.target.closest?.("button[data-cfg]")?.dataset.cfg);
    if (code) pickCfg(code === cfgSel ? "" : code, true);
  });
  vw.addEventListener("click", (e) => {
    const v = e.target.closest?.("button[data-view]")?.dataset.view;
    if (v === "sectors" || v === "scenarios") setView(v === "scenarios" ? "scenarios" : "", true);
  });

  const refresh = () => { load(); loadCfg(); if (sel) loadChart(); };
  const timer = setInterval(() => { if (visible()) refresh(); }, REFRESH_MS);
  window.addEventListener(ONLINE_EVENT, refresh);
  drawView();
  mark();
  drawCfg();
  load();
  loadCfg();
  loadChart();
  return {
    // arg undefined (przycisk menu, powrót do podzakładki po dłuższej przerwie; w tle nie odświeżamy): dane starsze niż
    // 60 s od razu; arg = adres podzakładki ("" = bez konfiguracji i bez wykresów; "EP-BH" = sektor bez konfiguracji;
    // 0.14.2: "scenarios/EP_NFIR/EP-BH" = podgląd scenariusza z wykresami jego traffic volume)
    activate(arg) {
      if (arg !== undefined) {
        // nowy stan od razu (widok, scenariusz, sektor): tabela w grupach konfiguracji i poprawiony adres (fixCfg,
        // fixScn) już z nim; kolejność: widok, konfiguracja, scenariusz, sektor
        const a = parseFmpArg(arg), viewNew = a.view !== view, scnNew = a.scn !== scnSel, tvNew = a.tv !== sel;
        view = a.view;
        scnSel = a.scn;
        sel = a.tv;
        if (a.cfg !== cfgSel) pickCfg(a.cfg);
        if (viewNew) {
          fixScn();
          reveal = view ? !!scnSel : !!sel;
          showView();
          if (reveal && data) showRow();
          return;
        }
        if (view && scnNew) {
          drawTable();
          fixScn();
          reveal = !!scnSel;
          mark();
          if (reveal && data) showRow();
          // nowy scenariusz w panelu od razu (także z tym samym traffic volume, którego wykres już jest)
          drawSide();
          loadChart();
          return;
        }
        if (tvNew) {
          if (view) { fixScn(); loadChart(); return; }
          reveal = !!a.tv;
          pick(a.tv);
          return;
        }
      }
      const now = Date.now();
      if (loadedAt && now - loadedAt > REFRESH_MS) load();
      if (cdAt && now - cdAt > REFRESH_MS) loadCfg();
      if (sel && chartAt && now - chartAt > REFRESH_MS) loadChart();
    },
    destroy() {
      dead = true;
      ++cseq;
      ++kseq;
      clearInterval(timer);
      window.removeEventListener(ONLINE_EVENT, refresh);
    },
  };
}
