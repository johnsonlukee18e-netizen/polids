import { api, esc, h, lsGet, lsSet, ONLINE_EVENT } from "./api.js";
import { colorFor } from "./airspace.js";
import { dissolve, pointIn, ringStats } from "./dissolve.js";
import { EPWW_BBOX, FMP_LS, LEVEL_FT, bboxOf, bboxOrDefault, flText, pathAll, pathOf, projection, ringsOf, sliceAt } from "./radioboard.js";
import { capOf, fmpRows, loadClass, tvLabel } from "./viffchart.js";

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

const REFRESH_MS = 60000;

const NUM_CLS = { near: " near", over: " over" };
const DASH = "\u2013", DOT = " \u00b7 ";
// id sektora z adresu albo z wiersza tabeli: wielkie litery ("ep-bh" → "EP-BH", też "ED-EDWW-ALR"); inne napisy = "" (nic)
export const cleanTv = (s) => { const t = String(s ?? "").trim().toUpperCase(); return /^[A-Z]{2}-[A-Z0-9-]{1,20}$/.test(t) ? t : ""; };
// 0.14.0 (właściciel projektu): kod konfiguracji sektorów z adresu albo z pamięci: cyfra i litera ("2n" → "2N"); inne napisy = ""
export const cleanCfg = (s) => { const t = String(s ?? "").trim().toUpperCase(); return /^[1-9][A-Z]$/.test(t) ? t : ""; };
// adres podzakładki → {cfg, tv}: "2N", "2N/EP-BH", stare "EP-BH" (sam sektor, bez konfiguracji); zły kod albo sektor = ""
export const parseFmpArg = (s) => { const t = String(s ?? ""), [a = "", ...r] = t.split("/"), cfg = cleanCfg(a); return { cfg, tv: cleanTv(cfg ? r.join("/") : t) }; };
// stan → adres podzakładki: "2N/EP-BH", "2N", "EP-BH" albo ""
export const fmpArg = (cfg, tv) => [cleanCfg(cfg), cleanTv(tv)].filter(Boolean).join("/");
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
function rowHtml(r, sel) {
  return `<tr class="${r.active ? "on" : "off"}${r.id === sel ? " sel" : ""}" data-tv="${esc(r.id)}">
    <td class="fmp-sec${r.restricted ? " reg" : ""}" title="${esc(r.sectorTip)}">${esc(r.code)}</td>
    <td class="fmp-num${NUM_CLS[r.entriesCls] || ""}" title="${esc(r.capacityTip)}">${pairHtml(r.entries, r.entriesMax, r.capacityReg)}</td>
    <td class="fmp-num${NUM_CLS[r.occupancyCls] || ""}" title="${esc(r.occupancyTip)}">${pairHtml(r.occupancy, r.occupancyMax, r.occupancyReg)}</td></tr>`;
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
// Wiersze tabeli w grupach konfiguracji c: [{p: stanowisko, rows}, …] w kolejności stanowisk konfiguracji, potem
// {kind: "free"} (warstwa sektora bez stanowiska konfiguracji; tylko niepusta) i {kind: "other"} (TMA, części FIR,
// kombinacje, nieznane litery; tylko niepusta). Kolejność wierszy w grupie jak bez konfiguracji (fmpRows)
export function cfgGroupRows(rows, c) {
  const groups = (c?.positions || []).map((p) => ({ p, rows: [] }));
  const free = { kind: "free", rows: [] }, other = { kind: "other", rows: [] };
  (rows || []).forEach((r) => {
    const s = tvSlot(r.id);
    const g = s && groups.find((x) => x.p.sectors?.[s.layer]?.includes(s.letter));
    if (g) g.rows.push(r);
    else if (s && c?.free?.[s.layer]?.includes(s.letter)) free.rows.push(r);
    else other.rows.push(r);
  });
  return [...groups, ...[free, other].filter((g) => g.rows.length)];
}
// nagłówek grupy w tabeli (td, nie th: th w tabeli są przyklejone u góry)
function groupHead(g) {
  if (g.p) {
    return `<tr class="fmp-grp"><td colspan="3" title="${esc(`${g.p.name}: ${g.p.callsign} ${g.p.frequency || ""}`.trim())}">`
      + `${swatch(g.p.callsign)}${esc(g.p.name)}<span class="fmp-grp-sub">${esc(g.p.callsign)} ${esc(g.p.frequency || "")}</span></td></tr>`;
  }
  return g.kind === "free"
    ? `<tr class="fmp-grp free"><td colspan="3" title="Sector layers with no position of this configuration">NOT COVERED</td></tr>`
    : `<tr class="fmp-grp other"><td colspan="3" title="TMA, FIR-wide and combined traffic volumes">OTHER</td></tr>`;
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
export function fmpChartHtml(c, row = null, note = "") {
  const ec = num(c.entries_cap), oc = num(c.occupancy_cap), regs = regList(c);
  const quiet = !(c.occupancy || []).some((v) => v > 0) && !(c.entries || []).some((e) => e.count > 0);
  const peak = num(c.peak) ? `${DOT}peak ${c.peak} at ${esc(c.peak_at)}Z` : "";
  return `<div class="fmc">${headHtml(c.id, row, c, note)}
    <div class="fmc-meta">capacity: ${ec === null ? "no entry limit" : `${ec} entries/h`}${DOT}${oc === null ? "no occupancy limit" : `${oc} aircraft at once`}`
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

// start / activate(arg) / onPick(arg, fix): adres podzakładki (fmpArg: "2N/EP-BH", "2N", "EP-BH", ""); fix = poprawa
// adresu bez nowego kroku historii (kod konfiguracji spoza tabeli)
export function mountFmp(pane, { start = "", onPick = () => {} } = {}) {
  const root = h(`<div class="fmp">
    <div class="fmp-cfg" role="group" aria-label="Sector configuration"></div>
    <div class="fmp-cp" hidden></div>
    <div class="fmp-bar"><span class="fmp-info hint"></span><span class="fmp-msg error"></span></div>
    <div class="fmp-main">
      <div class="fmp-scroll"><p class="hint">Loading\u2026</p></div>
      <aside class="fmp-side"></aside>
    </div>
  </div>`);
  pane.append(root);
  const info = root.querySelector(".fmp-info"), msg = root.querySelector(".fmp-msg"), box = root.querySelector(".fmp-scroll");
  const main = root.querySelector(".fmp-main"), side = root.querySelector(".fmp-side");
  const bar = root.querySelector(".fmp-cfg"), panel = root.querySelector(".fmp-cp");
  let data = null, loadedAt = 0, seq = 0, dead = false;
  // sel: wybrany sektor ("" = żaden), chart: ostatni wykres (c.id = sektor), reveal: przewinąć tabelę do wiersza sel
  // (wybór z adresu, nie z kliknięcia)
  const first = parseFmpArg(start);
  let sel = first.tv, chart = null, chartAt = 0, cseq = 0, reveal = !!sel;
  // 0.14.0 (właściciel projektu): cfgSel = wybrana konfiguracja ("" = żadna), cd = ostatnia odpowiedź /api/radio/configs (cdErr: błąd
  // ostatniego odświeżenia), geo = geometria podglądów (geoVer: jej wersja), grouped = konfiguracja, wg której jest
  // pogrupowana tabela na ekranie
  let cfgSel = first.cfg, cd = null, cdErr = "", cdAt = 0, kseq = 0, geo = null, geoVer = "", grouped = "";
  saveCfg(cfgSel);
  const visible = () => root.isConnected && root.offsetParent !== null;
  const rowOf = (id) => (data ? fmpRows(data).find((r) => r.id === id) || null : null);
  const cfgOf = () => (cfgSel && Array.isArray(cd?.configs) ? cd.configs.find((c) => c.code === cfgSel) || null : null);
  const keepRow = () => box.querySelector("tr.sel")?.scrollIntoView?.({ block: "nearest" });
  const showRow = () => { reveal = false; keepRow(); };
  // zaznaczenie wiersza bez rysowania tabeli od nowa (dymki i przewinięcie zostają)
  const mark = () => {
    box.querySelectorAll("tr[data-tv]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.tv === sel));
    main.classList.toggle("open", !!sel);
  };
  // kod spoza tabeli (stary albo wpisany adres), gdy konfiguracje są już wczytane: bez konfiguracji, adres poprawiony
  // bez nowego kroku historii
  const fixCfg = () => {
    if (!cfgSel || !Array.isArray(cd?.configs) || cfgOf()) return;
    cfgSel = "";
    saveCfg("");
    onPick(fmpArg(cfgSel, sel), true);
  };
  const draw = (html) => { const top = side.scrollTop; side.innerHTML = html; side.scrollTop = top; };
  // tabela (z grupami wybranej konfiguracji); przewinięcie zostaje
  const drawTable = () => {
    if (!data) return;
    const c = cfgOf(), top = box.scrollTop;
    grouped = c ? c.code : "";
    box.innerHTML = fmpHtml(data, sel, c);
    box.scrollTop = top;
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
      drawTable();
      info.textContent = fmpInfo(d);
      msg.textContent = "";
      if (reveal) showRow();
    } catch (e) {
      if (dead || my !== seq) return;
      loadedAt = Date.now();
      if (data) msg.textContent = `Not refreshed: ${e.message}`;
      else { box.innerHTML = `<p class="error fmp-err">${esc(e.message)}</p>`; info.textContent = ""; }
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
  };
  // wykres wybranego sektora; spóźniona odpowiedź dla poprzedniego wyboru nic nie rysuje (cseq); błąd odświeżenia
  // zostawia ostatni wykres z komunikatem w nagłówku
  const loadChart = async () => {
    const my = ++cseq, id = sel, fresh = chart?.id !== id;
    if (!id) { chart = null; chartAt = 0; side.innerHTML = fmpPickHtml(); return; }
    if (chart?.id !== id) side.innerHTML = fmpWaitHtml(id, rowOf(id));
    try {
      const c = await api(`/api/viff/sectors/${encodeURIComponent(id)}`);
      if (dead || my !== cseq) return;
      chart = c; chartAt = Date.now();
      draw(fmpChartHtml(c, rowOf(id)));
      // w wąskim oknie wykresy stoją pod tabelą i ją skracają: nowo wybrany wiersz zostaje widoczny (odświeżenie co
      // minutę nie przewija)
      if (fresh) keepRow();
    } catch (e) {
      if (dead || my !== cseq) return;
      chartAt = Date.now();
      if (chart?.id === id) draw(fmpChartHtml(chart, rowOf(id), `Not refreshed: ${e.message}`));
      else { chart = null; side.innerHTML = fmpWaitHtml(id, rowOf(id), e.message); }
    }
  };
  // user: klik (wiersz, ✕) = krok historii w OTHER (onPick); wybór z adresu (activate) bez onPick
  const pick = (id, user = false) => {
    sel = id;
    mark();
    if (!user && sel && data) showRow();
    loadChart();
    if (user) onPick(fmpArg(cfgSel, sel));
  };
  // 0.14.0: konfiguracja z kliknięcia (krok historii) albo z adresu; zapamiętana w przeglądarce; tabela od nowa w grupach
  // (wybrany sektor zostaje zaznaczony i widoczny)
  const pickCfg = (code, user = false) => {
    cfgSel = code;
    saveCfg(cfgSel);
    fixCfg();
    drawCfg();
    drawTable();
    // wybrany wiersz widoczny w tabeli; w niskim oknie cały obszar FMP zostaje, gdzie był (pasek pod kursorem)
    if (sel) { const top = root.scrollTop; keepRow(); root.scrollTop = top; }
    if (user) onPick(fmpArg(cfgSel, sel));
  };
  box.addEventListener("click", (e) => {
    const id = cleanTv(e.target.closest?.("tr[data-tv]")?.dataset.tv);
    if (id) pick(id === sel ? "" : id, true);
  });
  side.addEventListener("click", (e) => { if (e.target.closest?.(".fmc-close")) pick("", true); });
  bar.addEventListener("click", (e) => {
    const code = cleanCfg(e.target.closest?.("button[data-cfg]")?.dataset.cfg);
    if (code) pickCfg(code === cfgSel ? "" : code, true);
  });

  const refresh = () => { load(); loadCfg(); if (sel) loadChart(); };
  const timer = setInterval(() => { if (visible()) refresh(); }, REFRESH_MS);
  window.addEventListener(ONLINE_EVENT, refresh);
  mark();
  drawCfg();
  load();
  loadCfg();
  loadChart();
  return {
    // arg undefined (przycisk menu, powrót do podzakładki po dłuższej przerwie; w tle nie odświeżamy): dane starsze niż
    // 60 s od razu; arg = adres podzakładki ("" = bez konfiguracji i bez wykresów; "EP-BH" = sektor bez konfiguracji)
    activate(arg) {
      if (arg !== undefined) {
        // nowy sektor od razu w sel: tabela w grupach konfiguracji i poprawiony adres (fixCfg) już z nim
        const a = parseFmpArg(arg), tvNew = a.tv !== sel;
        if (tvNew) sel = a.tv;
        if (a.cfg !== cfgSel) pickCfg(a.cfg);
        if (tvNew) { reveal = !!a.tv; pick(a.tv); return; }
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
