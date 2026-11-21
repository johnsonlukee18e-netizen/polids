import { esc } from "./api.js";

// Ruch vs przepustowość sektorów (traffic volumes vIFF) na godzinę naprzód, w stylu wykresów NM UI.
// Kolory obciążenia: zielony < 90 % przepustowości, pomarańczowy 90–100 %, czerwony powyżej (przeciążenie).

const BAND = { H: "upper", M: "middle", L: "lower" };
const FIR_PART = { ALLFIR: "whole FIR", NFIR: "FIR north", SFIR: "FIR south" };

// ta sama logika co tv_label w backend/app/services/viff.py
export function tvLabel(id) {
  const code = id.replace(/^EP-/, "");
  let m = /^([A-Z])([HML])$/.exec(code);
  if (m) return `sector ${m[1]} ${BAND[m[2]]}`;
  m = /^([A-Z]{2})TMA(D?)$/.exec(code);
  if (m) return `TMA EP${m[1]}${m[2] ? " (D)" : ""}`;
  m = /^(ALLFIR|NFIR|SFIR)(.*)$/.exec(code);
  if (m) return `${FIR_PART[m[1]]}${m[2] ? " " + m[2] : ""}`;
  return "sector combination";
}

// Warunki aktywacji scenariusza vIFF (vIFF sam decyduje, czy jest aktywny; pokazujemy tylko warunki). html: wartości
// w <b> i escapowane (wiersz scenariusza w MAP), bez html sam tekst (dymek, escapowany przy wstawianiu).
export function scnCond(s, { html = false } = {}) {
  const e = html ? esc : (t) => String(t);
  const v = (t) => (html ? `<b>${esc(t)}</b>` : String(t));
  const b = (xs, sep) => xs.map(v).join(sep);
  const out = [];
  if (s.positions?.length) out.push(`when online: ${b(s.positions, " + ")}`);
  if (s.anypositions?.length) out.push(`when online: ${b(s.anypositions, " or ")}`);
  if (s.nopositions?.length) out.push(`and offline: ${b(s.nopositions, ", ")}`);
  if (s.booked) out.push("bookings count too");
  if (s.start && s.end && !(s.start === "0000" && s.end === "2359")) out.push(`time ${v(`${s.start}\u2013${s.end}`)}`);
  (s.times || []).forEach((t) => out.push(`${t.date ? e(t.date) + " " : ""}time ${v(`${t.from}\u2013${t.to}`)}`));
  return out.join(" \u00b7 ") || "no conditions";
}

// Dymek wiersza scenariusza vIFF po angielsku, z danych scenariusza: id, traffic volumes (z opisem jak tvLabel)
// i warunki. Opisu scenariusza z vIFF (s.description, wolny tekst po polsku) nie pokazujemy.
export function scnTip(s) {
  const tvs = (s.tvs || []).map((t) => `${t.id} (${tvLabel(t.id)})`);
  return `Scenario ${s.id}: ${tvs.length ? `traffic volumes ${tvs.join(", ")}` : "no traffic volumes"} \u00b7 ${scnCond(s)}`;
}

// aktywny = status 1 w vIFF albo członek aktywnego scenariusza (backend liczy to w polu active)
export const tvGroup = (tv) => (tv.active ?? tv.status === 1 ? "active" : "inactive");

export function loadClass(n, cap) {
  if (!cap || n === null || n === undefined) return "nolim";
  const r = n / cap;
  return r > 1 ? "over" : r >= 0.9 ? "near" : "ok";
}

// największe obciążenie w ciągu godziny: wejścia (vIFF, bieżąca i następna godzina) albo zajętość
export function loadRatio(tv) {
  const e = Math.max(0, ...tv.hours.map((h) => (h.entries_cap ? h.entries / h.entries_cap : 0)));
  const o = tv.occupancy_cap ? tv.peak_60 / tv.occupancy_cap : 0;
  return Math.max(e, o);
}

// wiersz TV z paskiem obciążenia; tv = null, gdy vIFF nie podał danych sektora
export function listRow(tv, selected, id = tv?.id) {
  if (!tv) return `<button class="vf-row" data-tv="${esc(id)}" title="${esc(tvLabel(id))}"><b>${esc(id)}</b><span class="vf-bar"></span><span class="vf-num">\u2013</span></button>`;
  const r = loadRatio(tv);
  const cls = r > 1 ? "over" : r >= 0.9 ? "near" : r > 0 ? "ok" : "nolim";
  // liczba przy pasku: godzina (bieżąca albo następna) z większym obciążeniem wejść
  const h0 = [...tv.hours].sort((a, b) => (b.entries_cap ? b.entries / b.entries_cap : 0) - (a.entries_cap ? a.entries / a.entries_cap : 0))[0];
  const tip = `${tv.id} \u00b7 ${tvLabel(tv.id)}${h0 ? ` \u00b7 ${h0.hour}Z: ${h0.entries ?? "\u2013"} entries / ${h0.entries_cap ?? "no limit"}` : ""} \u00b7 peak ${tv.peak_60}${tv.occupancy_cap ? "/" + tv.occupancy_cap : ""} in sector`;
  return `<button class="vf-row ${tv.id === selected ? "on" : ""}" data-tv="${esc(tv.id)}" title="${esc(tip)}">
    <b>${esc(tv.id)}</b><span class="vf-bar"><i class="${cls}" style="width:${Math.min(100, Math.round(r * 100))}%"></i></span>
    <span class="vf-num">${h0 ? `${h0.entries ?? "\u2013"}/${h0.entries_cap ?? "\u221e"}` : "\u2013"}</span></button>`;
}

// Stan lotu jak w liście lotów NM (te same kody i kolory co tabela odlotów w AERODROME)
const STATE_CLASS = { FI: "fi", SI: "si", SU: "su", AA: "aa", TA: "ta" };
export function stateChip(v, states) {
  if (!v) return "";
  const label = v.state === "SU" && v.suspension ? "SU " + v.suspension.replace(/^FLS-?/, "") : v.state;
  const tip = [states?.[v.state] || v.state, v.atfcm_status && `ATFCM: ${v.atfcm_status}`, v.cdm_status && v.cdm_status !== v.atfcm_status && `CDM: ${v.cdm_status}`]
    .filter(Boolean).join(" \u00b7 ");
  return `<span class="fs fs-${STATE_CLASS[v.state] || "fi"}" title="${esc(tip)}">${esc(label)}</span>${v.ready ? ` <span class="fs fs-rea" title="REA: ready to depart before the slot">REA</span>` : ""}`;
}
// kolory opóźnienia CTOT jak w liście lotów NM: < 15 min niebieski, < 30 żółty, < 45 pomarańczowy, ≥ 45 czerwony
export const delayClass = (d) => (d === null || d === undefined || d < 1 ? "" : d < 15 ? "d15" : d < 30 ? "d30" : d < 45 ? "d45" : "d60");

// 0.14.0 (issue #28, "widać jedynie linię limitu górnego, a nie aktualną przepustowość"): wykres TV na MAP z tych
// samych danych i tym samym rysunkiem co OTHER › FMP. c = odpowiedź GET /api/viff/sectors/<TV> (wejścia w 60 min co
// 20 min i samoloty w sektorze minuta po minucie, od pełnej godziny przed teraz do +5 h, z przepustowością
// i regulacjami), opts.svg = {entry, occ}: entrySvg i occSvg z fmp.js (podane z map.js, bo fmp.js importuje ten moduł).
// Do 0.13.6 słupki i zajętość szły z koszyków godzinowych listy sektorów; koszyk, którego godzina nie była dosłownie
// napisem "HH", nie trafiał w żadną godzinę, więc zostawała sama linia przepustowości z definicji TV.
// tv = wiersz TV z /api/viff/sectors (obszary, scenariusze, loty w sektorze w ciągu godziny) albo null; c = null:
// wykres jeszcze się wczytuje albo (err) się nie wczytał; note = błąd odświeżenia przy ostatnim wykresie.
// Pod wykresem lista lotów jak tabela wyników NM; pilot(cs) = {departure, arrival, aircraft} albo nic,
// sel = znak lotu otwartego w szczegółach (wiersz podświetlony).
const DASH_ = "\u2013", DOT_ = " \u00b7 ";
const regsOf = (c) => [...new Set([...(c.entries_reg || []).map((r) => `entries ${r.value} ${r.start}${DASH_}${r.end}`),
  ...(c.occupancy_reg || []).map((r) => `occupancy ${r.value} ${r.start}${DASH_}${r.end}`)])];
const pair = (n, cap) => `${n}${cap === null ? "" : `/${cap}`}`;
// teraz: wejścia w 60 min od początku słupka z bieżącą minutą i samoloty w sektorze w tej minucie, wobec przepustowości
// (niższej z deklarowanej i regulowanej, jak kolory słupków)
export function chartNow(c) {
  const at = num(c?.now_at);
  if (!c || at === null) return null;
  const bar = [...(c.entries || [])].reverse().find((e) => e.from <= at) || null;
  const occ = num((c.occupancy || [])[at]);
  const regAt = (c.occupancy_reg || []).filter((s) => s.from <= at && at < s.to).map((s) => s.value);
  return {
    entries: bar ? num(bar.count) ?? 0 : null, entriesCap: bar ? capOf(num(bar.cap), num(bar.reg)) : null, entriesFrom: bar?.time || null,
    occupancy: occ, occupancyCap: capOf(num(c.occupancy_cap), regAt.length ? Math.min(...regAt) : null),
  };
}

export function chartHtml(tv, c, { pilot = () => null, sel = null, svg = null, err = "", note = "" } = {}) {
  const id = c?.id || tv?.id || "";
  const active = c ? !!c.active : !!(tv?.active ?? tv?.status === 1);
  const ec = num(c ? c.entries_cap : tv?.entries_cap), oc = num(c ? c.occupancy_cap : tv?.occupancy_cap);
  const vols = tv?.volumes || c?.volumes || [], scns = tv?.scenarios || c?.scenarios || [];
  const regs = c ? regsOf(c) : [];
  const head = `<div class="vf-title"><span class="vf-kind" title="TV (traffic volume): sector or area with a set capacity">TV sector</span>`
    + `<span class="vf-id">${esc(id)}</span><span class="vf-desc">${esc(tvLabel(id))}</span>`
    + `<span class="vs-chip${active ? " on" : ""}">${active ? "ACTIVE" : "inactive"}</span>`
    + (note ? `<span class="vf-note error">${esc(note)}</span>` : "")
    + `<button class="vf-close" title="Close chart">\u2715</button></div>`;
  const meta = `<div class="vf-meta">${vols.length ? `<span title="airspace volumes">${esc(vols.join(", "))}</span>` : ""}`
    + `${scns.length ? `<span>scenario: ${esc(scns.join(", "))}</span>` : ""}`
    + `<span>capacity: ${ec === null ? "no entry limit" : `${ec} entries/h`}${DOT_}${oc === null ? "no occupancy limit" : `${oc} at once`}</span>`
    + `${regs.length ? `<span class="vf-reg">regulated: ${esc(regs.join(", "))}</span>` : ""}</div>`;
  let charts;
  if (!c || !svg) charts = err ? `<p class="error vf-err">${esc(err)}</p>` : `<p class="hint vf-wait">Loading\u2026</p>`;
  else {
    const n = chartNow(c);
    const stat = [`${esc(c.now)}Z`,
      n && n.entries !== null ? `entries ${pair(n.entries, n.entriesCap)} from ${esc(n.entriesFrom)}Z` : "",
      n && n.occupancy !== null ? `in sector ${pair(n.occupancy, n.occupancyCap)}` : "",
      num(c.peak) ? `peak ${c.peak} at ${esc(c.peak_at)}Z` : ""].filter(Boolean).join(DOT_);
    // przegląd 0.14.0 (issue #28): bez ruchu w oknie wykresu same linie przepustowości wyglądały jak dawny błąd, więc
    // zdanie jak w OTHER › FMP (fmpChartHtml)
    const quiet = !(c.occupancy || []).some((v) => v > 0) && !(c.entries || []).some((e) => e.count > 0);
    charts = (quiet ? `<p class="hint fmc-empty">No traffic in this period.</p>` : "")
      + `<div class="fmc-chart"><div class="fmc-title">ENTRY <span>entries in ${esc(c.span)} min, every ${esc(c.step)} min</span></div>${svg.entry(c)}</div>`
      + `<div class="fmc-chart"><div class="fmc-title">OCC <span>aircraft in the sector, per minute</span></div>${svg.occ(c)}</div>`
      + `<div class="fmc-legend"><span><i class="fmc-ok"></i>below 90 %</span><span><i class="fmc-near"></i>90${DASH_}100 %</span>`
      + `<span><i class="fmc-over"></i>over capacity</span><span><i class="fmc-nolim"></i>no limit</span>`
      + `<span><i class="fmc-capl"></i>capacity</span><span><i class="fmc-regl"></i>regulated</span></div>`
      + `<div class="vf-stat">${stat}</div>`;
  }
  const flights = tv?.flights || [];
  const rows = flights.map((f) => {
    const p = pilot(f.callsign);
    return `<tr data-cs="${esc(f.callsign)}" class="${f.airborne ? "" : "gnd"}${f.callsign === sel ? " on" : ""}" title="${f.airborne ? "airborne" : "still on ground / planned"}${DOT_}click: flight details">
      <td class="cs">${esc(f.callsign)}</td><td>${esc(p?.departure || DASH_)}</td><td>${esc(p?.arrival || DASH_)}</td><td>${esc(p?.aircraft || DASH_)}</td>
      <td class="t">${esc(f.entry)}</td><td class="t">${esc(f.exit)}</td></tr>`;
  }).join("");
  return `${head}<div class="vf-body">${meta}${charts}
    <div class="vf-fhead">Flights in sector within the hour <span>(${flights.length})</span></div>
    ${rows ? `<div class="vf-tblwrap"><table class="vf-tbl"><thead><tr><th>Callsign</th><th>ADEP</th><th>ADES</th><th>Type</th><th>Entry</th><th>Exit</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : `<div class="vf-empty">${tv ? "no flights within the hour" : "no flight list"}</div>`}
    </div>`;
}

// --- OTHER › FMP (0.13.0): tabela SECTOR | CAPACITY | OCCUPANCY, wiersz na traffic volume (dane z /api/viff/sectors)

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const DASH = "\u2013", DOT = " \u00b7 ";
// "18 (45)": liczba i przepustowość jak w FMP PANDORY; brak liczby albo limitu = "-", brak obu = samo "-"
export const pairText = (n, cap) => (n === null && cap === null ? DASH : `${n ?? DASH} (${cap ?? DASH})`);
const RESTR_KIND = { "ENR-ENTRIES": "entries", "ENR-OCCUPANCY": "occupancy" };
// przepustowość, z której liczymy obciążenie: niższa z deklarowanej i z regulacji obowiązującej teraz
export const capOf = (declared, reg) => (reg === null ? declared : declared === null ? reg : Math.min(declared, reg));
// regulacja wyznacza przepustowość (nie wyższa od deklarowanej)
const regBinds = (declared, reg) => reg !== null && (declared === null || reg <= declared);
const capTip = (declared, reg) => (reg === null ? (declared === null ? "no limit" : `capacity ${declared}`)
  : `regulated ${reg}, declared ${declared === null ? "no limit" : declared}`);

// Sektor teraz: wejścia w bieżącej godzinie (koszyk o tej godzinie, nie hours[0], które bywa następną godziną),
// przepustowość wejść tej godziny (albo z definicji TV), zajętość w tej minucie (occupancy[0]) i jej przepustowość;
// *Reg = wartość regulacji obowiązującej teraz (backend: regulated). now = "HHMM" z odpowiedzi; to samo przyda się
// RADIO (sektor na czerwono przy dużej zajętości).
export function tvNow(tv, now) {
  const cur = (tv.hours || []).find((x) => x.hour === String(now || "").slice(0, 2)) || null;
  return {
    entries: num(cur?.entries), entriesCap: num(cur?.entries_cap) ?? num(tv.entries_cap), entriesReg: num(tv.regulated?.entries),
    occupancy: num(Array.isArray(tv.occupancy) ? tv.occupancy[0] : null), occupancyCap: num(tv.occupancy_cap),
    occupancyReg: num(tv.regulated?.occupancy), peak: num(tv.peak_60),
  };
}

// opis regulacji z definicji TV do dymka: "entries 20 1500-1600"
const restrText = (r) => [RESTR_KIND[r?.type] || String(r?.type || "").toLowerCase(), r?.value, r?.start && r?.end ? `${r.start}${DASH}${r.end}` : ""]
  .filter((x) => x !== null && x !== undefined && x !== "").join(" ");

// kolejność FMP jak w PANDORZE: sektory EPWW po literze (pasma L, M, H), potem kombinacje sektorów, TMA i części FIR
const BAND_ORDER = { L: 0, M: 1, H: 2 };
const groupRank = (code) => (/^[A-Z][LMH]$/.test(code) ? 0 : /^[A-Z]{2}TMAD?$/.test(code) ? 2 : /^(ALLFIR|NFIR|SFIR)/.test(code) ? 3 : 1);
const sortKey = (code) => (/^[A-Z][LMH]$/.test(code) ? code[0] + BAND_ORDER[code[1]] : code);
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// wiersze FMP: aktywne na początku, potem grupy (groupRank); liczby, napisy komórek, dymki i klasy obciążenia
// (loadClass z przepustowości po regulacji)
export function fmpRows(data) {
  const prefix = (data?.prefix || "EP") + "-";
  const rows = (data?.sectors || []).filter((tv) => tv && tv.id).map((tv) => {
    const n = tvNow(tv, data.now);
    const active = !!(tv.active ?? tv.status === 1);
    const restr = Array.isArray(tv.restrictions) ? tv.restrictions.map(restrText).filter(Boolean) : [];
    const entriesMax = capOf(n.entriesCap, n.entriesReg), occupancyMax = capOf(n.occupancyCap, n.occupancyReg);
    const sectorTip = [`${tv.id}: ${tvLabel(tv.id)}`, active ? "active" : "inactive",
      tv.restricted ? "regulated now" : "", restr.length ? `regulations: ${restr.join(", ")}` : ""].filter(Boolean).join(DOT);
    const capacityTip = `${n.entries === null ? "No entry count this hour" : `${n.entries} ${n.entries === 1 ? "entry" : "entries"} this hour`}, `
      + capTip(n.entriesCap, n.entriesReg);
    const occupancyTip = `${n.occupancy === null ? "No occupancy data" : `${n.occupancy} aircraft in the sector now`}, `
      + capTip(n.occupancyCap, n.occupancyReg)
      + (n.peak === null ? "" : `${DOT}peak ${n.peak} within the hour`);
    const code = tv.id.startsWith(prefix) ? tv.id.slice(prefix.length) : tv.id;
    return {
      id: tv.id, code, label: tvLabel(tv.id),
      active, restricted: !!tv.restricted, ...n, entriesMax, occupancyMax,
      capacity: pairText(n.entries, entriesMax), occupancyText: pairText(n.occupancy, occupancyMax),
      capacityReg: regBinds(n.entriesCap, n.entriesReg), occupancyReg: regBinds(n.occupancyCap, n.occupancyReg),
      sectorTip, capacityTip, occupancyTip,
      entriesCls: loadClass(n.entries, entriesMax), occupancyCls: loadClass(n.occupancy, occupancyMax),
    };
  });
  rows.sort((a, b) => (a.active !== b.active ? (a.active ? -1 : 1)
    : groupRank(a.code) - groupRank(b.code) || cmp(sortKey(a.code), sortKey(b.code)) || cmp(a.id, b.id)));
  return rows;
}
