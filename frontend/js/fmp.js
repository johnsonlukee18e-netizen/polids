import { api, esc, h, ONLINE_EVENT } from "./api.js";
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

const REFRESH_MS = 60000;

const NUM_CLS = { near: " near", over: " over" };
const DASH = "\u2013", DOT = " \u00b7 ";
// id sektora z adresu albo z wiersza tabeli: wielkie litery ("ep-bh" → "EP-BH", też "ED-EDWW-ALR"); inne napisy = "" (nic)
export const cleanTv = (s) => { const t = String(s ?? "").trim().toUpperCase(); return /^[A-Z]{2}-[A-Z0-9-]{1,20}$/.test(t) ? t : ""; };

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

// tabela dla odpowiedzi /api/viff/sectors; sel = id wybranego sektora (wiersz z klasą sel); czysta funkcja (testy w Node)
export function fmpHtml(data, sel = "") {
  const rows = fmpRows(data);
  if (!rows.length) return `<p class="hint fmp-empty">No sectors.</p>`;
  return `<table class="fmp-table">
    <thead><tr><th title="Traffic volume: sector or area with a set capacity">SECTOR</th>
      <th title="Entries in the current hour (entry capacity per hour)">CAPACITY (ENTRIES)</th>
      <th title="Aircraft in the sector now (capacity at one time)">OCCUPANCY</th></tr></thead>
    <tbody>${rows.map((r) => rowHtml(r, sel)).join("")}</tbody></table>`;
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

export function mountFmp(pane, { start = "", onPick = () => {} } = {}) {
  const root = h(`<div class="fmp">
    <div class="fmp-bar"><span class="fmp-info hint"></span><span class="fmp-msg error"></span></div>
    <div class="fmp-main">
      <div class="fmp-scroll"><p class="hint">Loading\u2026</p></div>
      <aside class="fmp-side"></aside>
    </div>
  </div>`);
  pane.append(root);
  const info = root.querySelector(".fmp-info"), msg = root.querySelector(".fmp-msg"), box = root.querySelector(".fmp-scroll");
  const main = root.querySelector(".fmp-main"), side = root.querySelector(".fmp-side");
  let data = null, loadedAt = 0, seq = 0, dead = false;
  // sel: wybrany sektor ("" = żaden), chart: ostatni wykres (c.id = sektor), reveal: przewinąć tabelę do wiersza sel
  // (wybór z adresu, nie z kliknięcia)
  let sel = cleanTv(start), chart = null, chartAt = 0, cseq = 0, reveal = !!sel;
  const visible = () => root.isConnected && root.offsetParent !== null;
  const rowOf = (id) => (data ? fmpRows(data).find((r) => r.id === id) || null : null);
  const showRow = () => { reveal = false; box.querySelector("tr.sel")?.scrollIntoView?.({ block: "nearest" }); };
  // zaznaczenie wiersza bez rysowania tabeli od nowa (dymki i przewinięcie zostają)
  const mark = () => {
    box.querySelectorAll("tr[data-tv]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.tv === sel));
    main.classList.toggle("open", !!sel);
  };
  const draw = (html) => { const top = side.scrollTop; side.innerHTML = html; side.scrollTop = top; };

  // odświeżenie po błędzie zostawia ostatnią tabelę i pisze tylko komunikat nad nią
  const load = async () => {
    const my = ++seq;
    try {
      const d = await api("/api/viff/sectors");
      if (dead || my !== seq) return;
      data = d; loadedAt = Date.now();
      const top = box.scrollTop;
      box.innerHTML = fmpHtml(d, sel);
      box.scrollTop = top;
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
  // wykres wybranego sektora; spóźniona odpowiedź dla poprzedniego wyboru nic nie rysuje (cseq); błąd odświeżenia
  // zostawia ostatni wykres z komunikatem w nagłówku
  const loadChart = async () => {
    const my = ++cseq, id = sel;
    if (!id) { chart = null; chartAt = 0; side.innerHTML = fmpPickHtml(); return; }
    if (chart?.id !== id) side.innerHTML = fmpWaitHtml(id, rowOf(id));
    try {
      const c = await api(`/api/viff/sectors/${encodeURIComponent(id)}`);
      if (dead || my !== cseq) return;
      chart = c; chartAt = Date.now();
      draw(fmpChartHtml(c, rowOf(id)));
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
    if (user) onPick(sel);
  };
  box.addEventListener("click", (e) => {
    const id = cleanTv(e.target.closest?.("tr[data-tv]")?.dataset.tv);
    if (id) pick(id === sel ? "" : id, true);
  });
  side.addEventListener("click", (e) => { if (e.target.closest?.(".fmc-close")) pick("", true); });

  const refresh = () => { load(); if (sel) loadChart(); };
  const timer = setInterval(() => { if (visible()) refresh(); }, REFRESH_MS);
  window.addEventListener(ONLINE_EVENT, refresh);
  mark();
  load();
  loadChart();
  return {
    // arg undefined (przycisk menu, powrót do podzakładki po dłuższej przerwie; w tle nie odświeżamy): dane starsze niż
    // 60 s od razu; arg = sektor z adresu ("" = zamknąć wykresy)
    activate(arg) {
      if (arg !== undefined) {
        const id = cleanTv(arg);
        if (id !== sel) { reveal = !!id; pick(id); return; }
      }
      const now = Date.now();
      if (loadedAt && now - loadedAt > REFRESH_MS) load();
      if (sel && chartAt && now - chartAt > REFRESH_MS) loadChart();
    },
    destroy() {
      dead = true;
      ++cseq;
      clearInterval(timer);
      window.removeEventListener(ONLINE_EVENT, refresh);
    },
  };
}
