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
  if (s.start && s.end && !(s.start === "0000" && s.end === "2359")) out.push(`time ${v(`${s.start}–${s.end}`)}`);
  (s.times || []).forEach((t) => out.push(`${t.date ? e(t.date) + " " : ""}time ${v(`${t.from}–${t.to}`)}`));
  return out.join(" · ") || "no conditions";
}

// Dymek wiersza scenariusza vIFF po angielsku, z danych scenariusza: id, traffic volumes (z opisem jak tvLabel)
// i warunki. Opisu scenariusza z vIFF (s.description, wolny tekst po polsku) nie pokazujemy.
export function scnTip(s) {
  const tvs = (s.tvs || []).map((t) => `${t.id} (${tvLabel(t.id)})`);
  return `Scenario ${s.id}: ${tvs.length ? `traffic volumes ${tvs.join(", ")}` : "no traffic volumes"} · ${scnCond(s)}`;
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
  if (!tv) return `<button class="vf-row" data-tv="${esc(id)}" title="${esc(tvLabel(id))}"><b>${esc(id)}</b><span class="vf-bar"></span><span class="vf-num">–</span></button>`;
  const r = loadRatio(tv);
  const cls = r > 1 ? "over" : r >= 0.9 ? "near" : r > 0 ? "ok" : "nolim";
  // liczba przy pasku: godzina (bieżąca albo następna) z większym obciążeniem wejść
  const h0 = [...tv.hours].sort((a, b) => (b.entries_cap ? b.entries / b.entries_cap : 0) - (a.entries_cap ? a.entries / a.entries_cap : 0))[0];
  const tip = `${tv.id} · ${tvLabel(tv.id)}${h0 ? ` · ${h0.hour}Z: ${h0.entries ?? "–"} entries / ${h0.entries_cap ?? "no limit"}` : ""} · peak ${tv.peak_60}${tv.occupancy_cap ? "/" + tv.occupancy_cap : ""} in sector`;
  return `<button class="vf-row ${tv.id === selected ? "on" : ""}" data-tv="${esc(tv.id)}" title="${esc(tip)}">
    <b>${esc(tv.id)}</b><span class="vf-bar"><i class="${cls}" style="width:${Math.min(100, Math.round(r * 100))}%"></i></span>
    <span class="vf-num">${h0 ? `${h0.entries ?? "–"}/${h0.entries_cap ?? "∞"}` : "–"}</span></button>`;
}

// Stan lotu jak w liście lotów NM (te same kody i kolory co tabela odlotów w AERODROME)
const STATE_CLASS = { FI: "fi", SI: "si", SU: "su", AA: "aa", TA: "ta" };
export function stateChip(v, states) {
  if (!v) return "";
  const label = v.state === "SU" && v.suspension ? "SU " + v.suspension.replace(/^FLS-?/, "") : v.state;
  const tip = [states?.[v.state] || v.state, v.atfcm_status && `vIFF: ${v.atfcm_status}`, v.cdm_status && v.cdm_status !== v.atfcm_status && `CDM: ${v.cdm_status}`]
    .filter(Boolean).join(" · ");
  return `<span class="fs fs-${STATE_CLASS[v.state] || "fi"}" title="${esc(tip)}">${esc(label)}</span>${v.ready ? ` <span class="fs fs-rea" title="REA: ready to depart before the slot">REA</span>` : ""}`;
}
// kolory opóźnienia CTOT jak w liście lotów NM: < 15 min niebieski, < 30 żółty, < 45 pomarańczowy, ≥ 45 czerwony
export const delayClass = (d) => (d === null || d === undefined || d < 1 ? "" : d < 15 ? "d15" : d < 30 ? "d30" : d < 45 ? "d45" : "d60");

const clock = (now, m) => {
  const t = (parseInt(now.slice(0, 2), 10) * 60 + parseInt(now.slice(2), 10) + m) % 1440;
  return String(Math.floor(t / 60)).padStart(2, "0") + String(t % 60).padStart(2, "0");
};

// Wykres: po lewej wejścia na godzinę (vIFF: bieżąca i następna pełna godzina) z linią przepustowości,
// po prawej liczba samolotów w sektorze minuta po minucie od teraz do +60 min z linią przepustowości chwilowej.
// Pod wykresem lista lotów jak tabela wyników NM; pilot(cs) → {departure, arrival, aircraft} z VATSIM albo nic,
// sel = znak lotu otwartego w szczegółach (wiersz podświetlony).
export function chartHtml(tv, now, pilot = () => null, sel = null) {
  const W = 540, H = 150, top = 16, bottom = 22, plotH = H - top - bottom;
  // --- wejścia / h
  const hours = tv.hours.length ? tv.hours : [];
  const eMax = Math.max(4, tv.entries_cap || 0, ...hours.map((h) => h.entries || 0)) * 1.1;
  const ey = (v) => top + plotH - (v / eMax) * plotH;
  const bars = hours.map((h, i) => {
    const x = 34 + i * 62, y = ey(h.entries || 0);
    return `<rect x="${x}" y="${y}" width="40" height="${top + plotH - y}" class="vf-${loadClass(h.entries, h.entries_cap)}"/>
      <text x="${x + 20}" y="${y - 3}" class="vf-val">${h.entries ?? "–"}</text>
      <text x="${x + 20}" y="${H - 6}" class="vf-ax">${esc(h.hour)}Z${i === 0 ? " now" : ""}</text>`;
  }).join("");
  const eCap = tv.entries_cap ? `<line x1="26" x2="162" y1="${ey(tv.entries_cap)}" y2="${ey(tv.entries_cap)}" class="vf-cap"/>
    <text x="164" y="${ey(tv.entries_cap) + 4}" class="vf-capt">${tv.entries_cap}</text>` : "";
  // --- zajętość minuta po minucie
  const occ = tv.occupancy || [];
  const oMax = Math.max(3, tv.occupancy_cap || 0, ...occ) * 1.1;
  const x0 = 214, x1 = W - 34, ox = (m) => x0 + (m / 60) * (x1 - x0), oy = (v) => top + plotH - (v / oMax) * plotH;
  let path = `M${ox(0)},${oy(0)}`;
  occ.forEach((v, m) => { path += `L${ox(m)},${oy(v)}L${ox(m + 1 > 60 ? 60 : m + 1)},${oy(v)}`; });
  path += `L${ox(60)},${oy(0)}Z`;
  const oCls = loadClass(tv.peak_60, tv.occupancy_cap);
  const ticks = [0, 20, 40, 60].map((m) => `<line x1="${ox(m)}" x2="${ox(m)}" y1="${top}" y2="${top + plotH}" class="vf-grid"/>
    <text x="${ox(m)}" y="${H - 6}" class="vf-ax">${clock(now, m)}</text>`).join("");
  const oCap = tv.occupancy_cap ? `<line x1="${x0}" x2="${x1}" y1="${oy(tv.occupancy_cap)}" y2="${oy(tv.occupancy_cap)}" class="vf-cap"/>
    <text x="${x1 + 3}" y="${oy(tv.occupancy_cap) + 4}" class="vf-capt">${tv.occupancy_cap}</text>` : "";
  const yTicks = (max, y, x) => [0, Math.round(max / 2), Math.floor(max)].map((v) => `<text x="${x}" y="${y(v) + 4}" class="vf-ax end">${v}</text>`).join("");
  const svg = `<svg viewBox="0 0 ${W} ${H}" class="vf-svg">
    <line x1="26" x2="170" y1="${top + plotH}" y2="${top + plotH}" class="vf-base"/><line x1="${x0}" x2="${x1}" y1="${top + plotH}" y2="${top + plotH}" class="vf-base"/>
    <text x="96" y="${top - 5}" class="vf-sub">Entries / h${tv.entries_cap ? "" : " (no limit)"}</text>
    ${yTicks(eMax / 1.1, ey, 24)}${bars}${eCap}
    <text x="${(x0 + x1) / 2}" y="${top - 5}" class="vf-sub">Occupancy: aircraft in sector (now → +60 min)</text>
    ${ticks}${yTicks(oMax / 1.1, oy, x0 - 6)}<path d="${path}" class="vf-occ vf-${oCls}"/>${oCap}
  </svg>`;
  const rows = (tv.flights || []).map((f) => {
    const p = pilot(f.callsign);
    return `<tr data-cs="${esc(f.callsign)}" class="${f.airborne ? "" : "gnd"}${f.callsign === sel ? " on" : ""}" title="${f.airborne ? "airborne" : "still on ground / planned"} · click: flight details">
      <td class="cs">${esc(f.callsign)}</td><td>${esc(p?.departure || "–")}</td><td>${esc(p?.arrival || "–")}</td><td>${esc(p?.aircraft || "–")}</td>
      <td class="t">${esc(f.entry)}</td><td class="t">${esc(f.exit)}</td></tr>`;
  }).join("");
  const active = tv.active ?? tv.status === 1;
  return `<div class="vf-title"><span class="vf-kind" title="TV (traffic volume) in vIFF: sector or area with a set capacity">TV sector</span><b>${esc(tv.id)}</b><span class="vf-desc">${esc(tvLabel(tv.id))}</span>
      ${active ? `<span class="vs-chip on">ACTIVE</span>` : `<span class="vs-chip">inactive</span>`}
      <button class="vf-close" title="Close chart">✕</button></div>
    <div class="vf-body">
    <div class="vf-meta">${tv.volumes.length ? `<span title="airspace volumes">${esc(tv.volumes.join(", "))}</span>` : ""}
      ${tv.scenarios?.length ? `<span>scenario: ${esc(tv.scenarios.join(", "))}</span>` : ""}
      <span>capacity: <b>${tv.entries_cap ?? "∞"}</b> entries/h · <b>${tv.occupancy_cap ?? "∞"}</b> at once</span></div>
    ${svg}
    <div class="vf-legend"><span><i class="vf-ok"></i>&lt; 90 %</span><span><i class="vf-near"></i>90–100 %</span><span><i class="vf-over"></i>&gt; capacity</span>
      <span><i class="vf-capl"></i>capacity</span><span class="vf-stat">vIFF ${esc(now.slice(0, 2))}:${esc(now.slice(2))}Z · peak ${tv.peak_60}${tv.occupancy_cap ? "/" + tv.occupancy_cap : ""} ·
      entries per 20 min: ${(tv.windows || []).map((w) => w.entries).join(" · ") || "–"}</span></div>
    <div class="vf-fhead">Flights in sector within the hour <span>(${(tv.flights || []).length})</span></div>
    ${rows ? `<div class="vf-tblwrap"><table class="vf-tbl"><thead><tr><th>Callsign</th><th>ADEP</th><th>ADES</th><th>Type</th><th>Entry</th><th>Exit</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : `<div class="vf-empty">no flights within the hour</div>`}
    </div>`;
}
