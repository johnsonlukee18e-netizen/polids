// STRIP: paski postępu lotu jak w EFES (elektroniczne paski PAŻP).
// Odloty niebieskie, przyloty żółte, loty lokalne (krąg, ADEP = ADES) różowe, planowane (prefile, tylko vIFF) przygaszone.
// Komórki wypełniamy tym, co naprawdę jest w danych VATSIM / vIFF / .ese; pusta komórka pokazuje tylko blady opis pola.
// Najechanie na pasek niczego nie otwiera (0.12.5); kliknięcie otwiera okno lotu (układ "Extended Label", XL_FIELDS).
// Backend: GET /api/aerodromes/{icao}/strips (routers/aerodromes.py, services/procedures.py).
import { api, esc } from "./api.js";

const REFRESH_MS = 30000;
const STATE_CLASS = { FI: "fi", SI: "si", SU: "su", AA: "aa", TA: "ta" };
// opisy stanów vIFF po angielsku (backend: services/viff.py); nieznany stan: opis z backendu albo sam kod
const STATE_TXT = {
  FI: "FI: filed, no slot",
  SI: "SI: slot issued (CTOT)",
  SU: "SU: suspended (FLS)",
  AA: "AA: ATC activated (AOBT)",
  TA: "TA: TACT activated (ATOT)",
};
const stateTxt = (st, d) => STATE_TXT[st] || d?.states?.[st] || st;
// kolor CTOT = opóźnienie jak w liście lotów NM: < 15 min, < 30, < 45, ≥ 45
const delayClass = (d) => (d === null || d === undefined || d < 1 ? "" : d < 15 ? "d15" : d < 30 ? "d30" : d < 45 ? "d45" : "d60");
const RULES = { I: "IFR", V: "VFR", Y: "IFR/V", Z: "VFR/I" };
const RWY_SRC = { ATIS: "from ATIS", SUGGESTED: "system suggestion (no ATIS)", CDM: "assigned in EuroScope (CDM)" };
const RWY_TAG = { ATIS: "ATIS", SUGGESTED: "SUGG", CDM: "CDM" };
const WAKE = { L: "light", M: "medium", H: "heavy", J: "super (A388)" };
const KIND = { dep: "DEP", arr: "ARR", local: "LOC" };

const ph = (t) => `<span class="ph">${t}</span>`;
const t4 = (v) => (v ? esc(v) : "");
const has = (v) => v !== null && v !== undefined && v !== "";
// poziom: do 6500 ft wysokość (A045), wyżej FL (F370)
const lvl = (ft) => (!has(ft) ? "" : ft >= 6500
  ? "F" + String(Math.round(ft / 100)).padStart(3, "0") : "A" + String(Math.max(0, Math.round(ft / 100))).padStart(3, "0"));
const minsTxt = (m) => (!has(m) ? "" : m < 60 ? `${m}'` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`);

function movement(s, d) {
  // lot tylko z vIFF: bez danych VATSIM nie wiadomo, czy pilot jest połączony
  if (s.planned) return s.planned === "viff" ? (d?.network_error ? "VATSIM ?" : "OFFLINE") : "PREFILE";
  // na ziemi daleko od lotniska: przylot jeszcze na lotnisku odlotu, odlot np. już po przylocie do ADES
  if (s.away) return s.kind === "arr" ? "ON GROUND" : `ON GROUND ${s.dist_nm} NM`; // przylot: odległość jest w 1. komórce
  // w powietrzu: dla przylotu poziom jest w swojej komórce, więc tu prędkość względem ziemi
  if (s.state === "air") return s.kind === "arr" ? `AIRBORNE ${s.groundspeed ?? "–"} KT` : `AIRBORNE ${lvl(s.altitude)}`;
  return (s.groundspeed || 0) >= 3 ? "TAXIING" : s.kind === "arr" ? "ON GROUND" : "PARKED";
}

function chip(s, d) {
  const v = s.viff;
  if (!v) return "";
  const label = v.state === "SU" && v.suspension ? "SU " + v.suspension.replace(/^FLS-?/, "") : v.state;
  return `<span class="fs fs-${STATE_CLASS[v.state] || "fi"}" data-h="${esc(stateTxt(v.state, d))}">${esc(label)}</span>`
    + (v.ready ? `<span class="fs fs-rea" data-h="REA: ready for departure before the slot">REA</span>` : "");
}

// SSR: kod przydzielony (plan lotu, assigned_transponder); bez przydziału aktualny transponder na szaro
function ssr(s) {
  if (s.assigned_squawk) return `<span class="ssr">${esc(s.assigned_squawk)}</span>`;
  return s.squawk ? `<span class="ssr cur">${esc(s.squawk)}</span>` : ph("SSR");
}

function procHint(s, icao) {
  const kind = s.kind === "arr" ? "STAR" : "SID";
  const p = s.proc;
  if (s.rules === "V") return `${kind}: VFR flight, no procedure.`;
  if (!s.runway) return `${kind}: runway in use unknown.`;
  if (p?.source === "CDM") return `SID assigned in EuroScope (CDM plugin, vIFF: ${s.runway}/${p.name}).`;
  if (p?.source === "route") return `${kind} ${p.name} filed in the flight plan route; exists for RWY ${s.runway} in the .ese file.`;
  if (p) return kind === "SID" ? `SID from the .ese file for RWY ${s.runway}: last SID point = first route point (${p.fix}).`
    : `STAR from the .ese file for RWY ${s.runway}: first STAR point = last route point (${p.fix}).`;
  if (!s.route) return `No ${kind}: no route in the flight plan.`;
  if (!s.proc_fix) return `No ${kind}: the route does not ${kind === "SID" ? "start" : "end"} with a navigation fix.`;
  return kind === "SID" ? `No SID: no SID for RWY ${s.runway} (${icao}) in the .ese file ends at ${s.proc_fix}.`
    : `No STAR: no STAR for RWY ${s.runway} (${icao}) in the .ese file starts at ${s.proc_fix}.`;
}

// prawe pole (w EFES przycisk SU): najważniejszy czas z vIFF albo minuty do przylotu
function box(s) {
  const v = s.viff || {};
  const b = (k, val, cls = "", h = "") => `<div class="c-box ${cls}" data-h="${esc(h)}"><span class="k">${k}</span><b>${esc(val)}</b></div>`;
  if (s.kind === "arr") {
    return has(s.eta_min) && s.state === "air"
      ? b("IN", minsTxt(s.eta_min), "", "Minutes to arrival (distance / ground speed).")
      : `<div class="c-box empty" data-h="Minutes to arrival: aircraft not airborne.">${ph("IN")}</div>`;
  }
  if (s.kind === "local") return `<div class="c-box empty" data-h="Local VFR flight: no slot and no A-CDM."></div>`;
  if (v.atot) return b("ATOT", v.atot, "", "ATOT: actual take-off time (vIFF).");
  if (v.ctot) {
    const h = ["CTOT: ATFM slot from vIFF", has(v.delay) && `delay ${v.delay} min`,
      v.regulation && `regulation ${v.regulation}`, v.airspace && `airspace ${v.airspace}`].filter(Boolean).join(" · ");
    return b("CTOT", v.ctot, "ctot " + delayClass(v.delay), h);
  }
  if (v.ttot) return b("TTOT", v.ttot, "", "TTOT: target take-off time from A-CDM (vIFF), no slot.");
  return `<div class="c-box empty" data-h="No CTOT / TTOT in vIFF.">${ph("CTOT")}</div>`;
}

function stripHtml(s, d, sel) {
  const v = s.viff || {};
  const dep = s.kind !== "arr";
  const local = s.kind === "local";
  const atis = d.atis?.letter;
  const cls = ["strip", s.kind, s.planned ? "planned" : "", s.state === "air" ? "air" : "", s.away ? "away" : "", sel ? "sel" : ""].join(" ");
  // 1: EOBT / SU-PB (odlot), ETA / CONT (przylot)
  let c1;
  if (s.kind === "arr") {
    c1 = `<div class="c c-time" data-h="ETA (UTC) = now + distance / ground speed. Below: distance from ${esc(d.icao)}.">
      ${s.eta ? `<b class="t">${esc(s.eta)}</b>` : ph("ETA")}${has(s.dist_nm) ? `<span class="s">${s.dist_nm} NM</span>` : ph("CONT")}</div>`;
  } else {
    const [k2, t2] = v.aobt ? ["AOBT", v.aobt] : v.tsat ? ["TSAT", v.tsat] : v.tobt ? ["TOBT", v.tobt] : [null, null];
    const h = `EOBT ${s.eobt_source === "vIFF" ? "from vIFF (IFPS)" : s.eobt_source === "FPL" ? "from the VATSIM flight plan (deptime)" : "unknown"}.`
      + ` SU/PB field: ${k2 ? { AOBT: "AOBT (off-block, vIFF)", TSAT: "TSAT (start-up from A-CDM, vIFF)", TOBT: "TOBT (target off-block, A-CDM)" }[k2] : "no TSAT/AOBT"}.`;
    c1 = `<div class="c c-time" data-h="${esc(h)}">${s.eobt ? `<b class="t">${esc(s.eobt)}</b>` : ph("EOBT")}
      ${k2 ? `<span class="s"><i>${k2}</i>${esc(t2)}</span>` : ph(local ? "TSTMP" : "SU/PB")}</div>`;
  }
  // 2: TYP + W / ADES (odlot) albo ADEP (przylot); lokalny: ADEP i ADES
  const wh = s.wake ? `Wake turbulence category ${s.wake} (${WAKE[s.wake] || "?"}) ${s.wake_source === "db" ? "from the type database" : "from the flight plan"}.` : "Wake turbulence category unknown.";
  const type = `<span class="ty">${s.aircraft ? esc(s.aircraft) : ph("TYPE")}${s.wake ? `<i class="w w-${esc(s.wake)}">${esc(s.wake)}</i>` : ""}</span>`;
  const c2 = local
    ? `<div class="c c-type three" data-h="${esc(`ICAO type. ${wh} ADEP = ADES: local flight (circuits).`)}">${type}<span class="s">${t4(s.departure)}</span><span class="s">${t4(s.arrival)}</span></div>`
    : `<div class="c c-type" data-h="${esc(`ICAO type. ${wh} Below: ${dep ? "destination (ADES), more relevant than ADEP for a departure" : "departure aerodrome (ADEP)"}.`)}">
      ${type}${(dep ? s.arrival : s.departure) ? `<span class="s">${esc(dep ? s.arrival : s.departure)}</span>` : ph(dep ? "ADES" : "ADEP")}</div>`;
  // 3: CALLSIGN / STATUS
  const cs = s.callsign || "";
  const c3 = `<div class="c c-cs" data-h="${esc(statusHint(s, d))}"><span class="cs ${cs.length > 7 ? "long" : ""}">${esc(cs)}</span>
    <span class="st">${chip(s, d)}<span class="mv">${esc(movement(s, d))}</span></span></div>`;
  // 4: A (litera ATIS) / reguły + pas
  const aH = `A = ATIS letter ${d.icao}${atis ? "" : " (ATIS not on air)"}. Below: flight rules and ${s.kind === "arr" ? "landing" : "departure"} runway${s.runway ? ` ${s.runway}: ${RWY_SRC[s.runway_source] || ""}` : ": unknown"}.`;
  const c4 = `<div class="c c-a" data-h="${esc(aH)}">${atis ? `<b class="atis">${esc(atis)}</b>` : ph("A")}
    <span class="s">${s.rules ? `<span class="ru ${s.rules === "V" ? "vfr" : ""}">${RULES[s.rules] || esc(s.rules)}</span>` : ""}${s.runway ? `<b class="rw">${esc(s.runway)}</b>` : ph("RWY")}</span></div>`;
  // 5: SID/STAR / CFL + SSR; lokalny: CUR / CFL + SSR
  const air = s.state === "air";
  const cflH = s.kind === "arr"
    ? `CFL: VATSIM data has no CFL. ${air ? "Showing the current level from the network" : "Aircraft not airborne"}; RFL from the flight plan ${s.rfl_ft ? lvl(s.rfl_ft) : "unknown"}.`
    : "CFL: VATSIM data has no CFL; showing RFL (cruising level from the flight plan).";
  const ssrH = `SSR: ${s.assigned_squawk ? `assigned code ${s.assigned_squawk}` : "no assigned code, grey = current transponder"}${s.squawk && s.squawk !== s.assigned_squawk ? ` (transponder ${s.squawk})` : ""}.`;
  const level = s.kind === "arr"
    ? (air ? `<span class="cur"><i>CUR</i>${lvl(s.altitude)}</span>` : ph("CFL"))
    : (s.rfl_ft ? lvl(s.rfl_ft) : ph("CFL"));
  const low = `<span class="s"><span class="cfl" data-h="${esc(cflH)}">${level}</span><span data-h="${esc(ssrH)}">${ssr(s)}</span></span>`;
  const top = local
    ? `<span class="pr" data-h="Current altitude / level from the VATSIM network (previous level not tracked).">${ph("PRV")}${air ? `<span class="cur"><i>CUR</i>${lvl(s.altitude)}</span>` : ph("CUR")}</span>`
    : s.proc ? `<b class="proc" data-h="${esc(procHint(s, d.icao))}">${esc(s.proc.name)}</b>` : `<span data-h="${esc(procHint(s, d.icao))}">${ph(s.kind === "arr" ? "STAR" : "SID")}</span>`;
  const c5 = `<div class="c c-proc">${top}${low}</div>`;
  const c6 = `<div class="c c-taxi" data-h="TAXI / GATE: taxi route and stand are not in VATSIM network data.">${ph("TAXI")}${ph("GATE")}</div>`;
  // FREETEXT: trasa (i krótkie uwagi)
  const rmk = s.remarks && s.remarks.length <= 32 ? s.remarks : "";
  const free = [s.route, rmk].filter(Boolean).map(esc).join(" · ") || ph("FREETEXT");
  const lp = local ? `<span class="lp" data-h="Low pass (LP) and touch-and-go (TG) counters: not in VATSIM data.">LP:__ | TG:__ |</span>` : "";
  return `<div class="${cls}" data-k="${esc(s.kind + ":" + cs)}">
    <div class="s-top">${c1}${c2}${c3}${c4}${c5}${c6}${box(s)}</div>
    <div class="s-free" data-h="Route from the flight plan${rmk ? " and remarks" : ""}.">${lp}<span class="ft">${free}</span></div></div>`;
}

// opis pola CALLSIGN / STATUS (także wiersz STATUS w oknie lotu)
function statusHint(s, d) {
  const v = s.viff || {};
  const away = s.away ? ` Aircraft on ground ${s.dist_nm} NM from ${d.icao}: ${s.kind === "arr" ? "still at the departure aerodrome" : "away from the departure aerodrome (e.g. already arrived)"}.` : "";
  const net = s.planned === "viff" && d.network_error ? " No VATSIM data: unknown whether the pilot is connected." : "";
  return `${s.viff ? stateTxt(v.state, d) + ". " : "Flight not in vIFF. "}Movement: ${movement(s, d)}${s.groundspeed ? `, GS ${s.groundspeed} kt` : ""}.${away}${net}`;
}

// ---------------------------------------------------------------------------------------------------------------------
// Okno lotu po kliknięciu paska, wzorowane na "Extended Label" z instrukcji SDD 2014 (rozdz. 2.1.2.3, Figure 2-6,
// Table 2-13). Układ TYMCZASOWY: stron instrukcji z tym rozdziałem nie udało się odczytać, więc pola są typowe dla
// rozszerzonej etykiety. Cały układ jest w XL_FIELDS: row / col / span w siatce XL_COLS kolumn, l = opis (tekst albo
// funkcja paska), v(s, d) = wartość (tekst, {t, cls, sub} albo null = brak danych "–"), when(s) = false pomija pole.
// Wiersze bez żadnego pola znikają (numeracja wierszy w oknie jest ciągła), więc zmiana układu = zmiana tej tablicy.
export const XL_COLS = 4;
const isDep = (s) => s.kind !== "arr";
const isArr = (s) => s.kind === "arr";
const isAcdm = (s) => s.kind === "dep";   // lot lokalny VFR: bez slotu i A-CDM, więc bez wierszy pustych czasów vIFF
const hhmm = (t) => (t ? { t } : null);
const viffState = (s) => (s.viff?.state ? (s.viff.state === "SU" && s.viff.suspension
  ? `SU ${s.viff.suspension.replace(/^FLS-?/, "")}` : s.viff.state) + (s.viff.ready ? " REA" : "") : null);
export const XL_FIELDS = [
  { k: "ssr", l: "SSR", row: 1, col: 1, v: (s) => (s.assigned_squawk
    ? { t: s.assigned_squawk, sub: s.squawk && s.squawk !== s.assigned_squawk ? `XPDR ${s.squawk}` : "" }
    : s.squawk ? { t: s.squawk, cls: "cur" } : null) },
  { k: "type", l: "TYPE/WTC", row: 1, col: 2, v: (s) => (s.aircraft ? `${s.aircraft}/${s.wake || "?"}` : null) },
  { k: "rules", l: "RULES", row: 1, col: 3, v: (s) => RULES[s.rules] || s.rules || null },
  { k: "reg", l: "REG", row: 1, col: 4, v: (s) => s.registration || null },
  { k: "adep", l: "ADEP", row: 2, col: 1, v: (s) => s.departure || null },
  { k: "ades", l: "ADES", row: 2, col: 2, v: (s) => s.arrival || null },
  { k: "rfl", l: "RFL", row: 2, col: 3, v: (s) => (s.rfl_ft ? lvl(s.rfl_ft) : null) },
  { k: "lvl", l: "LEVEL", row: 2, col: 4, v: (s) => (s.planned ? null : s.state === "air" ? lvl(s.altitude) : s.state === "ground" ? "GND" : null) },
  { k: "proc", l: (s) => (isArr(s) ? "STAR" : "SID"), row: 3, col: 1, v: (s) => s.proc?.name || null },
  { k: "rwy", l: "RWY", row: 3, col: 2, v: (s) => (s.runway ? { t: s.runway, sub: RWY_TAG[s.runway_source] || "" } : null) },
  { k: "atis", l: "ATIS", row: 3, col: 3, v: (s, d) => d.atis?.letter || null },
  { k: "gs", l: "GS", row: 3, col: 4, v: (s) => (!s.planned && has(s.groundspeed) ? `${s.groundspeed} KT` : null) },
  // odlot i lot lokalny: czasy A-CDM / ATFM z vIFF (EOBT także z planu lotu VATSIM)
  { k: "eobt", l: "EOBT", row: 4, col: 1, when: isDep, v: (s) => (s.eobt ? { t: s.eobt, sub: s.eobt_source || "" } : null) },
  { k: "tobt", l: "TOBT", row: 4, col: 2, when: isAcdm, v: (s) => hhmm(s.viff?.tobt) },
  { k: "tsat", l: "TSAT", row: 4, col: 3, when: isAcdm, v: (s) => hhmm(s.viff?.tsat) },
  { k: "ttot", l: "TTOT", row: 4, col: 4, when: isAcdm, v: (s) => hhmm(s.viff?.ttot) },
  { k: "ctot", l: "CTOT", row: 5, col: 1, when: isAcdm, v: (s) => (s.viff?.ctot ? { t: s.viff.ctot, cls: "ctot " + delayClass(s.viff.delay),
    sub: [s.viff.delay > 0 && `+${s.viff.delay}'`, s.viff.regulation].filter(Boolean).join(" ") } : null) },
  { k: "aobt", l: "AOBT", row: 5, col: 2, when: isAcdm, v: (s) => hhmm(s.viff?.aobt) },
  { k: "atot", l: "ATOT", row: 5, col: 3, when: isAcdm, v: (s) => hhmm(s.viff?.atot) },
  { k: "fls", l: "vIFF", row: 5, col: 4, when: isAcdm, v: (s) => viffState(s) },
  // przylot: ETA z pozycji, ELDT, odległość i minuty do przylotu; EOBT z lotniska odlotu, punkt wejścia, podejścia STAR
  { k: "eta", l: "ETA", row: 4, col: 1, when: isArr, v: (s) => hhmm(s.eta) },
  { k: "eldt", l: "ELDT", row: 4, col: 2, when: isArr, v: (s) => hhmm(s.eldt) },
  { k: "dist", l: "DIST", row: 4, col: 3, when: isArr, v: (s) => (has(s.dist_nm) ? `${s.dist_nm} NM` : null) },
  { k: "in", l: "IN", row: 4, col: 4, when: isArr, v: (s) => (s.state === "air" && has(s.eta_min) ? minsTxt(s.eta_min) : null) },
  { k: "aeobt", l: "EOBT", row: 5, col: 1, when: isArr, v: (s) => hhmm(s.eobt) },
  { k: "entry", l: "ENTRY", row: 5, col: 2, when: isArr, v: (s) => s.entry_fix?.fix || null },
  { k: "apch", l: "APCH", row: 5, col: 3, span: 2, when: isArr, v: (s) => s.proc?.approaches?.join(", ") || null },
  // przylot: stan vIFF (rzadko jest) dopisany do STATUS
  { k: "status", l: "STATUS", row: 6, col: 1, span: 3,
    v: (s, d) => movement(s, d) + (isArr(s) && s.viff?.state ? ` · vIFF ${viffState(s)}` : "") },
  { k: "stand", l: "STAND", row: 6, col: 4, v: () => null },   // stanowiska postojowego nie ma w danych VATSIM
  { k: "route", l: "ROUTE", row: 7, col: 1, span: 4, wrap: true, v: (s) => s.route || null },
  { k: "pts", l: (s) => `${isArr(s) ? "STAR" : "SID"} ${s.proc?.name || ""}`.trim(), row: 8, col: 1, span: 4, wrap: true,
    when: (s) => !!s.proc?.fixes?.length, v: (s) => s.proc.fixes.join(" ") },
  { k: "rmk", l: "RMK", row: 9, col: 1, span: 4, wrap: true, when: (s) => !!s.remarks, v: (s) => s.remarks },
];

// pola okna dla paska: [{ k, l, row, col, span, wrap, t, cls, sub }] z ciągłą numeracją wierszy
export function extLabel(s, d) {
  const out = XL_FIELDS.filter((f) => !f.when || f.when(s, d)).map((f) => {
    const raw = f.v(s, d);
    const val = raw === null || raw === undefined || raw === "" ? null : typeof raw === "object" ? raw : { t: String(raw) };
    return { k: f.k, l: typeof f.l === "function" ? f.l(s, d) : f.l, row: f.row, col: f.col, span: f.span || 1,
      wrap: !!f.wrap, t: val ? String(val.t) : null, cls: val?.cls || "", sub: val?.sub || "" };
  });
  const rows = [...new Set(out.map((f) => f.row))].sort((a, b) => a - b);
  out.forEach((f) => { f.row = rows.indexOf(f.row) + 1; });
  return out;
}

function winHtml(s, d, note) {
  const kind = s.planned ? "PLN" : KIND[s.kind] || "";
  const cells = extLabel(s, d).map((f) => `<div class="xw-f${f.wrap ? " wrap" : ""}" data-f="${esc(f.k)}" style="grid-row:${f.row};grid-column:${f.col} / span ${f.span}">
    <i>${esc(f.l)}</i>${f.t === null ? `<b class="nil">–</b>` : `<b class="${esc(f.cls)}">${esc(f.t)}</b>`}${f.sub ? `<span class="sub">${esc(f.sub)}</span>` : ""}</div>`).join("");
  const foot = s.planned ? "Planned flight: pilot not connected yet." : "Double-click the strip: show on map.";
  return `<div class="xw-head ${esc(s.kind)}${s.planned ? " planned" : ""}"><b class="xw-cs">${esc(s.callsign || "")}</b>
      <span class="xw-kind">${kind}</span><button type="button" class="xw-x" aria-label="Close">×</button></div>
    <div class="xw-grid" style="grid-template-columns:repeat(${XL_COLS}, minmax(0, 1fr))">${cells}</div>
    ${note ? `<div class="xw-note"><i>FIELD</i><span>${esc(note)}</span></div>` : ""}
    <div class="xw-foot">${foot}</div>`;
}

// położenie okna: pod paskiem (x = miejsce kliknięcia), gdy brak miejsca nad nim; zawsze w całości w oknie przeglądarki
export function placeWin(a, w, h, vw, vh, m = 6) {
  const left = Math.max(m, Math.min(a.x, vw - w - m));
  let top = a.bottom + 3;
  if (top + h > vh - m) top = a.top - h - 3 >= m ? a.top - h - 3 : vh - h - m;
  return { left, top: Math.max(m, top) };
}

const BAYS = [
  { key: "departures", cls: "dep main", title: "Departures", sub: "on ground by TSAT / CTOT / EOBT, then airborne", empty: "No departures" },
  { key: "planned", cls: "plan side", title: "Planned", sub: "prefiles and vIFF flights not connected", empty: "No planned flights" },
  { key: "arrivals", cls: "arr main", title: "Arrivals", sub: "by ETA", empty: "No arrivals" },
  { key: "local", cls: "loc side", title: "Local", sub: "ADEP = ADES (circuits)", empty: "No local flights" },
];

function bayList(key, list, d, selected) {
  if (!list.length) return "";
  const html = (s) => stripHtml(s, d, selected === s.kind + ":" + s.callsign);
  const div = (t) => `<div class="sx-div">${t}</div>`;
  // na ziemi daleko od lotniska (backend: away) zawsze na końcu zatoki
  const x = list.filter((s) => s.away);
  const away = x.length ? div(`On ground away from ${esc(d.icao)} · ${x.length}`) + x.map(html).join("") : "";
  if (key === "departures") {
    const g = list.filter((s) => s.state !== "air" && !s.away), a = list.filter((s) => s.state === "air");
    return g.map(html).join("") + (a.length ? div(`Airborne · ${a.length}`) + a.map(html).join("") : "") + away;
  }
  if (key === "arrivals") {
    const g = list.filter((s) => s.state === "ground" && !s.away), a = list.filter((s) => s.state !== "ground");
    return (g.length ? div(`Landed · ${g.length}`) + g.map(html).join("") + (a.length ? div(`Airborne · ${a.length}`) : "") : "")
      + a.map(html).join("") + away;
  }
  return list.map(html).join("");
}

export function mountStrips(el, icao, { onUpdate } = {}) {
  el.innerHTML = `<div class="strips">
    <div class="sx-bar"><span class="hint">Loading strips…</span></div>
    <div class="sx-board">
      <div class="sx-col">${BAYS.slice(0, 2).map((b) => `<section class="sx-bay ${b.cls}" data-bay="${b.key}">
        <h3>${b.title} <span class="n"></span><span class="sub">${b.sub}</span></h3><div class="sx-list"></div></section>`).join("")}</div>
      <div class="sx-col">${BAYS.slice(2).map((b) => `<section class="sx-bay ${b.cls}" data-bay="${b.key}">
        <h3>${b.title} <span class="n"></span><span class="sub">${b.sub}</span></h3><div class="sx-list"></div></section>`).join("")}</div>
    </div>
    <div class="sx-win" role="dialog" hidden></div>
  </div>`;
  const root = el.querySelector(".strips");
  const win = root.querySelector(".sx-win");
  // open = { key, dx (miejsce kliknięcia względem lewej krawędzi paska), note (indeks klikniętego pola [data-h]) }
  let data = null, byKey = new Map(), open = null, timer = null, dead = false, seq = 0;

  const bar = (d) => {
    const u = d.runway_in_use || {};
    const src = u.source === "ATIS" ? `ATIS ${esc(d.atis?.letter || "")}` : "system suggestion";
    const errs = [d.network_error, d.viff_error].filter(Boolean);
    const n = (k) => d[k].length;
    const noProc = !d.procedures?.sid?.length && !d.procedures?.star?.length;
    return `<span class="kv" title="Departure runway in use (${esc(src)})"><i>DEP</i><b class="dep">${esc(u.dep || "–")}</b></span>
      <span class="kv" title="Landing runway in use (${esc(src)})"><i>ARR</i><b class="arr">${esc(u.arr || "–")}</b></span>
      ${u.source === "ATIS" ? "" : `<span class="kv sugg">system suggestion, no runway from ATIS</span>`}
      <span class="kv"><i>ATIS</i><b>${esc(d.atis?.letter || "–")}</b></span>
      <span class="kv" title="A-CDM: TOBT, TSAT, TTOT from vIFF${d.viff_error ? " (vIFF unavailable: unknown)" : ""}"><i>A-CDM</i>${d.viff_error ? "?" : d.cdm ? "yes" : "no"}</span>
      ${noProc ? `<span class="kv sugg">no SID/STAR for ${esc(d.icao)} in the .ese file</span>` : ""}
      <span class="sx-legend"><span><s class="lg dep"></s>departure ${n("departures")}</span><span><s class="lg arr"></s>arrival ${n("arrivals")}</span>
        <span><s class="lg loc"></s>local ${n("local")}</span><span><s class="lg plan"></s>planned ${n("planned")}</span></span>
      <span class="hint sx-note">click: flight details · double-click: map · CFL = RFL · SID/STAR from .ese</span>
      ${errs.length ? `<span class="error">${errs.map(esc).join(" · ")}</span>` : ""}`;
  };

  const stripEl = (key) => [...root.querySelectorAll(".strip")].find((x) => x.dataset.k === key) || null;
  const markSel = () => root.querySelectorAll(".strip").forEach((x) => x.classList.toggle("sel", x.dataset.k === open?.key));
  const closeWin = () => {
    open = null;
    win.hidden = true;
    win.innerHTML = "";
    markSel();
  };
  // okno przy pasku; pasek przewinięty poza zatokę (albo zniknął) zamyka okno
  const placeAt = () => {
    if (!open) return;
    const st = stripEl(open.key);
    if (!st) return closeWin();
    if (st.offsetParent === null) return;   // widok schowany (inna zakładka): położenie po powrocie
    const r = st.getBoundingClientRect();
    const lr = st.closest(".sx-list")?.getBoundingClientRect();
    if (lr && (r.bottom <= lr.top || r.top >= lr.bottom)) return closeWin();
    const p = placeWin({ x: r.left + open.dx, top: r.top, bottom: r.bottom }, win.offsetWidth, win.offsetHeight, innerWidth, innerHeight);
    win.style.left = p.left + "px";
    win.style.top = p.top + "px";
  };
  const drawWin = () => {
    const s = open && byKey.get(open.key);
    const st = open && stripEl(open.key);
    if (!s || !st) return closeWin();
    const note = open.note >= 0 ? st.querySelectorAll("[data-h]")[open.note]?.dataset.h || "" : "";
    win.innerHTML = winHtml(s, data, note);
    win.setAttribute("aria-label", `Flight ${s.callsign || ""}`);
    win.hidden = false;
    markSel();
    placeAt();
  };

  const render = () => {
    const d = data;
    byKey = new Map();
    ["departures", "arrivals", "local", "planned"].forEach((k) => d[k].forEach((s) => byKey.set(s.kind + ":" + s.callsign, s)));
    root.querySelector(".sx-bar").innerHTML = bar(d);
    BAYS.forEach((b) => {
      const sec = root.querySelector(`[data-bay="${b.key}"]`);
      const list = d[b.key] || [];
      sec.classList.toggle("empty", !list.length);
      sec.querySelector(".n").textContent = list.length;
      // bez danych VATSIM pusta zatoka nie znaczy "brak ruchu" (PLANOWANE mają jeszcze loty z vIFF)
      const empty = d.network_error && b.key !== "planned" ? "No VATSIM network data (see the error above)" : b.empty;
      sec.querySelector(".sx-list").innerHTML = bayList(b.key, list, d, open?.key) || `<div class="hint sx-empty">${empty}</div>`;
    });
    // okno lotu: nowe dane tego samego lotu albo zamknięcie, gdy lotu już nie ma
    if (open) drawWin();
  };

  const refresh = async () => {
    const my = ++seq;
    try {
      const d = await api(`/api/aerodromes/${icao}/strips`);
      if (dead || my !== seq) return;
      data = d;
      render();
      onUpdate?.(d);
    } catch (e) {
      if (dead || my !== seq) return;
      root.querySelector(".sx-bar").innerHTML = `<span class="error">${esc(e.message)}</span>`;
    }
  };

  // odświeżanie co 30 s tylko, gdy widok jest widoczny; schowany (inna zakładka) zatrzymuje się, activate() wznawia
  const visible = () => !document.hidden && root.isConnected && root.offsetParent !== null;
  const schedule = () => { clearTimeout(timer); timer = dead ? null : setTimeout(tick, REFRESH_MS); };
  const tick = async () => {
    timer = null;
    if (dead || !visible()) return;
    await refresh();
    if (!timer) schedule();
  };
  const onVis = () => { if (!document.hidden && !timer && visible()) { refresh(); schedule(); } };
  document.addEventListener("visibilitychange", onVis);

  // klik: okno lotu (jedno naraz); ten sam pasek, przycisk ×, Esc albo klik poza oknem i paskami zamyka
  root.addEventListener("click", (e) => {
    if (e.target.closest(".xw-x")) return closeWin();
    if (win.contains(e.target)) return;
    const st = e.target.closest(".strip");
    if (!st) return closeWin();
    if (e.detail > 1) return;   // drugi klik dwukliku (mapa) nie zamyka okna otwartego pierwszym
    if (open?.key === st.dataset.k) return closeWin();
    const r = st.getBoundingClientRect();
    const cell = e.target.closest("[data-h]");
    open = { key: st.dataset.k, dx: e.clientX - r.left - 24, note: cell ? [...st.querySelectorAll("[data-h]")].indexOf(cell) : -1 };
    drawWin();
  });
  root.addEventListener("dblclick", (e) => {
    const s = byKey.get(e.target.closest(".strip")?.dataset.k);
    if (s && !s.planned) { closeWin(); location.hash = "#map/" + encodeURIComponent(s.callsign); }
  });
  const onDocClick = (e) => { if (open && !root.contains(e.target)) closeWin(); };
  const onKey = (e) => { if (e.key === "Escape" && open && visible()) { e.preventDefault(); closeWin(); } };
  const onMove = () => { if (open) placeAt(); };
  document.addEventListener("click", onDocClick);
  document.addEventListener("keydown", onKey);
  root.addEventListener("scroll", onMove, true);   // przewijanie zatoki: okno idzie za paskiem
  window.addEventListener("resize", onMove);

  refresh();
  schedule();
  return {
    resume() { if (!dead) { refresh(); schedule(); } },
    destroy() {
      dead = true;
      clearTimeout(timer);
      timer = null;
      document.removeEventListener("visibilitychange", onVis);
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onMove);
    },
  };
}
