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
const WAKE = { L: "light", M: "medium", H: "heavy", J: "super (A388)" };

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
  return `<span class="fs fs-${STATE_CLASS[v.state] || "fi"}" data-f="state" data-h="${esc(stateTxt(v.state, d))}">${esc(label)}</span>`
    + (v.ready ? `<span class="fs fs-rea" data-f="rea" data-h="REA: ready for departure before the slot">REA</span>` : "");
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
  const b = (k, val, cls = "", h = "") => `<div data-f="box" class="c-box ${cls}" data-h="${esc(h)}"><span class="k">${k}</span><b>${esc(val)}</b></div>`;
  if (s.kind === "arr") {
    return has(s.eta_min) && s.state === "air"
      ? b("IN", minsTxt(s.eta_min), "", "Minutes to arrival (distance / ground speed).")
      : `<div data-f="box" class="c-box empty" data-h="Minutes to arrival: aircraft not airborne.">${ph("IN")}</div>`;
  }
  if (s.kind === "local") return `<div data-f="box" class="c-box empty" data-h="Local VFR flight: no slot and no A-CDM."></div>`;
  if (v.atot) return b("ATOT", v.atot, "", "ATOT: actual take-off time (vIFF).");
  if (v.ctot) {
    const h = ["CTOT: ATFM slot from vIFF", has(v.delay) && `delay ${v.delay} min`,
      v.regulation && `regulation ${v.regulation}`, v.airspace && `airspace ${v.airspace}`].filter(Boolean).join(" · ");
    return b("CTOT", v.ctot, "ctot " + delayClass(v.delay), h);
  }
  if (v.ttot) return b("TTOT", v.ttot, "", "TTOT: target take-off time from A-CDM (vIFF), no slot.");
  return `<div data-f="box" class="c-box empty" data-h="No CTOT / TTOT in vIFF.">${ph("CTOT")}</div>`;
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
    c1 = `<div class="c c-time" data-f="time" data-h="ETA (UTC) = now + distance / ground speed. Below: distance from ${esc(d.icao)}.">
      ${s.eta ? `<b class="t">${esc(s.eta)}</b>` : ph("ETA")}${has(s.dist_nm) ? `<span class="s">${s.dist_nm} NM</span>` : ph("CONT")}</div>`;
  } else {
    const [k2, t2] = v.aobt ? ["AOBT", v.aobt] : v.tsat ? ["TSAT", v.tsat] : v.tobt ? ["TOBT", v.tobt] : [null, null];
    const h = `EOBT ${s.eobt_source === "vIFF" ? "from vIFF (IFPS)" : s.eobt_source === "FPL" ? "from the VATSIM flight plan (deptime)" : "unknown"}.`
      + ` SU/PB field: ${k2 ? { AOBT: "AOBT (off-block, vIFF)", TSAT: "TSAT (start-up from A-CDM, vIFF)", TOBT: "TOBT (target off-block, A-CDM)" }[k2] : "no TSAT/AOBT"}.`;
    c1 = `<div class="c c-time" data-f="time" data-h="${esc(h)}">${s.eobt ? `<b class="t">${esc(s.eobt)}</b>` : ph("EOBT")}
      ${k2 ? `<span class="s"><i>${k2}</i>${esc(t2)}</span>` : ph(local ? "TSTMP" : "SU/PB")}</div>`;
  }
  // 2: TYP + W / ADES (odlot) albo ADEP (przylot); lokalny: ADEP i ADES
  const wh = s.wake ? `Wake turbulence category ${s.wake} (${WAKE[s.wake] || "?"}) ${s.wake_source === "db" ? "from the type database" : "from the flight plan"}.` : "Wake turbulence category unknown.";
  const type = `<span class="ty">${s.aircraft ? esc(s.aircraft) : ph("TYPE")}${s.wake ? `<i class="w w-${esc(s.wake)}">${esc(s.wake)}</i>` : ""}</span>`;
  const c2 = local
    ? `<div class="c c-type three" data-f="type" data-h="${esc(`ICAO type. ${wh} ADEP = ADES: local flight (circuits).`)}">${type}<span class="s">${t4(s.departure)}</span><span class="s">${t4(s.arrival)}</span></div>`
    : `<div class="c c-type" data-f="type" data-h="${esc(`ICAO type. ${wh} Below: ${dep ? "destination (ADES), more relevant than ADEP for a departure" : "departure aerodrome (ADEP)"}.`)}">
      ${type}${(dep ? s.arrival : s.departure) ? `<span class="s">${esc(dep ? s.arrival : s.departure)}</span>` : ph(dep ? "ADES" : "ADEP")}</div>`;
  // 3: CALLSIGN / STATUS
  const cs = s.callsign || "";
  const c3 = `<div class="c c-cs" data-f="cs" data-h="${esc(statusHint(s, d))}"><span class="cs ${cs.length > 7 ? "long" : ""}">${esc(cs)}</span>
    <span class="st">${chip(s, d)}<span class="mv">${esc(movement(s, d))}</span></span></div>`;
  // 4: A (litera ATIS) / reguły + pas
  const aH = `A = ATIS letter ${d.icao}${atis ? "" : " (ATIS not on air)"}. Below: flight rules and ${s.kind === "arr" ? "landing" : "departure"} runway${s.runway ? ` ${s.runway}: ${RWY_SRC[s.runway_source] || ""}` : ": unknown"}.`;
  const c4 = `<div class="c c-a" data-f="a" data-h="${esc(aH)}">${atis ? `<b class="atis">${esc(atis)}</b>` : ph("A")}
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
  const low = `<span class="s"><span class="cfl" data-f="cfl" data-h="${esc(cflH)}">${level}</span><span data-f="ssr" data-h="${esc(ssrH)}">${ssr(s)}</span></span>`;
  const top = local
    ? `<span class="pr" data-f="prv" data-h="Current altitude / level from the VATSIM network (previous level not tracked).">${ph("PRV")}${air ? `<span class="cur"><i>CUR</i>${lvl(s.altitude)}</span>` : ph("CUR")}</span>`
    : s.proc ? `<b class="proc" data-f="proc" data-h="${esc(procHint(s, d.icao))}">${esc(s.proc.name)}</b>` : `<span data-f="proc" data-h="${esc(procHint(s, d.icao))}">${ph(s.kind === "arr" ? "STAR" : "SID")}</span>`;
  const c5 = `<div class="c c-proc">${top}${low}</div>`;
  const c6 = `<div class="c c-taxi" data-f="taxi" data-h="TAXI / GATE: taxi route and stand are not in VATSIM network data.">${ph("TAXI")}${ph("GATE")}</div>`;
  // FREETEXT: trasa (i krótkie uwagi)
  const rmk = s.remarks && s.remarks.length <= 32 ? s.remarks : "";
  const free = [s.route, rmk].filter(Boolean).map(esc).join(" · ") || ph("FREETEXT");
  const lp = local ? `<span class="lp" data-f="lp" data-h="Low pass (LP) and touch-and-go (TG) counters: not in VATSIM data.">LP:__ | TG:__ |</span>` : "";
  return `<div class="${cls}" data-k="${esc(s.kind + ":" + cs)}" tabindex="0" role="button" aria-expanded="${sel}">
    <div class="s-top">${c1}${c2}${c3}${c4}${c5}${c6}${box(s)}</div>
    <div class="s-free" data-f="free" data-h="Route from the flight plan${rmk ? " and remarks" : ""}.">${lp}<span class="ft">${free}</span></div></div>`;
}

// opis pola CALLSIGN / STATUS (także wiersz STATUS w oknie lotu)
function statusHint(s, d) {
  const v = s.viff || {};
  const away = s.away ? ` Aircraft on ground ${s.dist_nm} NM from ${d.icao}: ${s.kind === "arr" ? "still at the departure aerodrome" : "away from the departure aerodrome (e.g. already arrived)"}.` : "";
  const net = s.planned === "viff" && d.network_error ? " No VATSIM data: unknown whether the pilot is connected." : "";
  return `${s.viff ? stateTxt(v.state, d) + ". " : "Flight not in vIFF. "}Movement: ${movement(s, d)}${s.groundspeed ? `, GS ${s.groundspeed} kt` : ""}.${away}${net}`;
}

// ---------------------------------------------------------------------------------------------------------------------
// Okno lotu po kliknięciu paska: "EXTENDED LABEL WINDOW" z instrukcji SDD 2014 (rozdz. 2.1.2.3, Figure 2-6, Table 2-13).
// Osiem wierszy jak w SDD: 1 callsign, W (RVSM), Y (8.33), pełny znak radiowy, typ transpondera / kod A;
// 2 typ / WTC, STS, ORCAM SSR; 3 ADEP ADES (zapasowe) STAR/SID RWY; 4 reguły, trasa (do 7 punktów);
// 5 CFL RFL, tekst RMK, RVR; 6 NAV/COM, wyposażenie dozorowania, PBN; 7-8 dane Mode S (z VATSIM tylko HDG, GS, VV).
// Pola bez danych są puste jak w SDD; przycisk KEY w belce pokazuje nad wartościami nazwy pól.
// Cały układ jest w XL_LINES: wiersz = { indent, gap (odstęp nad), f: pola }; pole = { k, l (nazwa w KEY), w (szerokość
// w znakach), right (do prawej krawędzi), v(s, d, x) = tekst, { t, cls } albo [{ t, cls }, ...] (kolorowe części) albo null }.
export const XL_WIDTH = 52;   // szerokość okna w znakach (najdłuższy wiersz SDD: 6 pól dozorowania/PBN)
const STS_KEYS = new Set(["STS", "PBN", "NAV", "COM", "DAT", "SUR", "DEP", "DEST", "DOF", "REG", "EET", "SEL", "TYP", "CODE",
  "DLE", "OPR", "ORGN", "PER", "ALTN", "RALT", "TALT", "RIF", "RMK", "RVR", "RFP", "EUR", "IFP"]);

// pole 10 planu lotu z pola aircraft VATSIM: "B38M/M-SDE2E3FGHIJ1RWXY/LB1" → typ, WTC, NAV/COM, dozorowanie
export function equipment(full) {
  const m = /^([A-Z0-9]{2,4})(?:\/([LMHJ]))?(?:-([A-Z0-9]*))?(?:\/([A-Z0-9]*))?$/.exec(String(full || "").trim().toUpperCase());
  if (!m) return { type: null, wake: null, navcom: null, surv: null };
  return { type: m[1], wake: m[2] || null, navcom: m[3] || null, surv: m[4] ?? null };
}

// pole 18 z uwag VATSIM: { STS: "HOSP MEDEVAC", PBN: "A1B1", RMK: "TCAS", ... }; "/V/", "/R/", "/T/" (głos/odbiór) pomijamy
export function field18(remarks) {
  const out = {};
  let key = null;
  for (const tok of String(remarks || "").toUpperCase().split(/\s+/)) {
    if (!tok || /^\/[VRT]\/$/.test(tok)) continue;
    const m = /^([A-Z]{3,4})\/(.*)$/.exec(tok);
    if (m && STS_KEYS.has(m[1])) {
      key = m[1];
      out[key] = out[key] ? `${out[key]} ${m[2]}`.trim() : m[2];
    } else {
      key = key || "RMK";   // tekst bez pola 18 przed sobą = uwagi
      out[key] = out[key] ? `${out[key]} ${tok}` : tok;
    }
  }
  return out;
}

// litery wyposażenia: pojedyncze albo z cyfrą (E1, J5, B1, ...)
const letters = (str) => new Set(String(str || "").match(/[A-Z]\d*/g) || []);
// W: zielone = RVSM (W w NAV/COM), żółte = zwolniony (STS/NONRVSM albo STATE), czerwone = bez RVSM albo nieznane
function rvsm(navcom, sts) {
  if (letters(navcom).has("W")) return "g";
  return /\b(NONRVSM|STATE)\b/.test(sts || "") ? "y" : "r";
}
// Y: zielone = 8.33 (Y), żółte = bez 8.33, ale UHF (U), czerwone = bez 8.33 albo nieznane
function vhf833(navcom) {
  const l = letters(navcom);
  return l.has("Y") ? "g" : l.has("U") ? "y" : "r";
}
// typ transpondera: S/ (Mode S: E H I L P S X), C/ (Mode C), A/ (tylko Mode A)
function xpdrType(surv) {
  const l = letters(surv);
  if (["E", "H", "I", "L", "P", "S", "X"].some((c) => l.has(c))) return "S/";
  return l.has("C") ? "C/" : l.has("A") ? "A/" : "";
}

const AIRWAY = /^[A-Z]{1,2}\d{1,3}[A-Z]?$/;
const PROC_NAME_RE = /^[A-Z]{2,5}\d[A-Z]$/;
const SPEED_LEVEL = /^[NKM]\d{3,4}(?:[FAMS]\d{3,4}|VFR)?$/;
const LATLON = /^\d{2,4}[NS]\d{3,5}[EW]$/;
// punkty znaczące trasy (bez DCT, dróg lotniczych, SID/STAR, grup prędkość/poziom i lotnisk ADEP/ADES), najwyżej 7:
// dla przylotu ostatnie (najbliżej lotniska), dla odlotu i lotu lokalnego pierwsze
export function routePoints(s, max = 7) {
  const skip = new Set(["DCT", "SID", "STAR", "IFR", "VFR", "OAT", "GAT", "IFPSTOP", "IFPSTART", s.departure, s.arrival]);
  const pts = String(s.route || "").toUpperCase().split(/\s+/).map((t) => t.split("/")[0])
    .filter((t) => t && !skip.has(t) && !AIRWAY.test(t) && !PROC_NAME_RE.test(t) && !SPEED_LEVEL.test(t)
      && (/^[A-Z]{2,5}$/.test(t) || LATLON.test(t)));
  const out = pts.filter((t, i) => t !== pts[i - 1]);
  return s.kind === "arr" ? out.slice(-max) : out.slice(0, max);
}

const fl3 = (ft) => (has(ft) ? String(Math.max(0, Math.round(ft / 100))).padStart(3, "0") : null);
const pad3 = (n) => (has(n) ? String(Math.round(n)).padStart(3, "0") : null);
const live = (s) => !s.planned && s.state !== "offline";

export const XL_LINES = [
  { f: [
    { k: "cs", l: "CALLSIGN", w: 7, v: (s) => ({ t: s.callsign || "", cls: "g" }) },
    { k: "wy", l: "W Y", w: 2, v: (s, d, x) => [{ t: "W", cls: rvsm(x.eq.navcom, x.f18.STS) }, { t: "Y", cls: vhf833(x.eq.navcom) }] },
    { k: "tel", l: "FULL CALLSIGN", w: 1, v: (s) => (s.telephony ? { t: s.telephony, cls: "g" } : null) },
    { k: "xpdr", l: "XPDR/A", w: 6, right: true, v: (s, d, x) => (live(s) && s.squawk ? xpdrType(x.eq.surv) + s.squawk : null) },
  ] },
  { indent: 3, f: [
    { k: "type", l: "TYPE/WTC", w: 6, v: (s, d, x) => {
      const t = s.aircraft || x.eq.type;
      const w = s.wake || x.eq.wake;
      return t ? `${t}${w ? "/" + w : ""}` : null;
    } },
    { k: "sts", l: "STS", w: 1, v: (s, d, x) => x.f18.STS || null },
    // ORCAM SSR: kod przydzielony, tylko gdy różni się od nadawanego
    { k: "orcam", l: "ORCAM SSR", w: 4, right: true,
      v: (s) => (s.assigned_squawk && s.assigned_squawk !== s.squawk ? { t: s.assigned_squawk, cls: "y" } : null) },
  ] },
  { gap: true, f: [
    { k: "adep", l: "ADEP", w: 4, v: (s) => s.departure || null },
    { k: "ades", l: "ADES", w: 4, v: (s) => s.arrival || null },
    { k: "altn", l: "ALTN", w: 11, v: (s, d, x) => {
      const a = [s.alternate, ...(x.f18.ALTN || "").split(/\s+/)].filter((v) => v && /^[A-Z]{4}$/.test(v));
      return a.length ? `(${[...new Set(a)].slice(0, 2).join(" ")})` : null;
    } },
    { k: "proc", l: (s) => (s.kind === "arr" ? "STAR" : "SID"), w: 7, v: (s) => s.proc?.name || null },
    { k: "rwy", l: "RWY", w: 6, v: (s) => (s.runway ? `RWY${s.runway}` : null) },
  ] },
  { f: [
    { k: "rules", l: "FR", w: 1, v: (s) => (s.rules ? { t: s.rules, cls: "y" } : null) },
    { k: "route", l: "ROUTE (MAX 7 POINTS)", w: 1, v: (s) => routePoints(s).join(" ") || null },
  ] },
  { f: [
    // CFL: sieć VATSIM nie podaje poziomu zezwolenia, pole zostaje puste
    { k: "cfl", l: "CFL", w: 3, v: () => null },
    { k: "rfl", l: "RFL", w: 3, v: (s) => (s.rfl_ft ? { t: fl3(s.rfl_ft), cls: "y" } : null) },
    { k: "free", l: "FREE TEXT (RMK)", w: 20, v: (s, d, x) => (x.f18.RMK ? x.f18.RMK.slice(0, 20) : null) },
    { k: "rvr", l: "RVR", w: 3, right: true, v: (s, d, x) => (x.f18.RVR ? { t: x.f18.RVR.slice(0, 6), cls: "y" } : null) },
  ] },
  { f: [
    { k: "navcom", l: "NAV/COM", w: 18, v: (s, d, x) => x.eq.navcom || null },
    { k: "surv", l: "SUR", w: 15, v: (s, d, x) => x.eq.surv || null },
    { k: "pbn", l: "PBN", w: 1, v: (s, d, x) => x.f18.PBN?.slice(0, 16) || null },
  ] },
  // Mode S: adres ICAO, wybrana wysokość, IAS, Mach, TAS, zmiana i przechylenie nie istnieją w danych VATSIM
  { gap: true, f: [
    { k: "addr", l: "ICAO ADDR", w: 6, v: () => null },
    { k: "sel", l: "SEL", w: 3, v: () => null },
    { k: "hdg", l: "HDG", w: 3, v: (s) => (live(s) && s.state === "air" ? pad3(s.heading) : null) },
    { k: "ias", l: "IAS", w: 3, v: () => null },
    { k: "mach", l: "MACH", w: 3, v: () => null },
    { k: "tas", l: "TAS", w: 3, v: () => null },
  ] },
  { f: [
    { k: "gs", l: "GS", w: 3, v: (s) => (live(s) && has(s.groundspeed) ? pad3(s.groundspeed) : null) },
    // VV: zmiana wysokości między dwoma odczytami sieci (co 30 s), setki ft/min ze znakiem
    { k: "vv", l: "VV ×100", w: 3, v: (s, d, x) => (has(x.vv) ? (x.vv > 0 ? "+" : x.vv < 0 ? "-" : "") + Math.abs(Math.round(x.vv / 100)) : null) },
  ] },
];

// pola okna: [{ line, indent, gap, f: [{ k, l, w, right, parts: [{ t, cls }] | null }] }]
export function extLabel(s, d, ctx = {}) {
  const x = { eq: equipment(s.aircraft_icao), f18: field18(s.remarks), vv: ctx.vv ?? null };
  return XL_LINES.map((ln, i) => ({ line: i + 1, indent: ln.indent || 0, gap: !!ln.gap, f: ln.f.map((f) => {
    const raw = f.v(s, d, x);
    const parts = raw === null || raw === undefined || raw === "" ? null
      : (Array.isArray(raw) ? raw : [typeof raw === "object" ? raw : { t: String(raw) }]).map((p) => ({ t: String(p.t), cls: p.cls || "" }));
    return { k: f.k, l: typeof f.l === "function" ? f.l(s, d) : f.l, w: f.w, right: !!f.right, parts };
  }) }));
}

function winHtml(s, d, note, ctx, key) {
  const kind = s.planned ? "PLANNED" : { dep: "DEPARTURE", arr: "ARRIVAL", local: "LOCAL" }[s.kind] || "";
  const lines = extLabel(s, d, ctx).map((ln) => `<div class="xw-ln${ln.gap ? " gap" : ""}"${ln.indent ? ` style="padding-left:${ln.indent}ch"` : ""}>${ln.f.map((f) => {
    const val = f.parts ? f.parts.map((p) => `<span${p.cls ? ` class="${esc(p.cls)}"` : ""}>${esc(p.t)}</span>`).join("") : "";
    return `<span class="xw-f${f.right ? " rt" : ""}${f.parts ? "" : " nil"}" data-f="${esc(f.k)}" style="min-width:${f.w}ch">${key ? `<i>${esc(f.l)}</i>` : ""}<b>${val}</b></span>`;
  }).join("")}</div>`).join("");
  const foot = s.planned ? "Planned flight: pilot not connected yet." : "Double-click the strip: show on map.";
  return `<div class="xw-head"><span class="xw-t">EXTENDED LABEL WINDOW</span>
      <button type="button" class="xw-key${key ? " on" : ""}" aria-pressed="${key}">KEY</button><button type="button" class="xw-x" aria-label="Close">×</button></div>
    <div class="xw-body${key ? " key" : ""}" style="width:${XL_WIDTH}ch">${lines}</div>
    ${note ? `<div class="xw-note"><i>FIELD</i><span>${esc(note)}</span></div>` : ""}
    <div class="xw-foot"><b>${kind}</b> · ${foot}</div>`;
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
  // open = { key, dx (miejsce kliknięcia względem lewej krawędzi paska), note (data-f klikniętego pola), kb (z klawiatury) }
  let data = null, byKey = new Map(), open = null, timer = null, dead = false, seq = 0;
  // prędkość pionowa do okna (wiersz Mode S): wysokość z poprzedniego odczytu sieci VATSIM, ft/min
  const alts = new Map(), vv = new Map();
  // przycisk KEY (nazwy pól w oknie) zapamiętany w przeglądarce; bez localStorage zostaje wyłączony
  let keyMode = false;
  try { keyMode = localStorage.getItem("polids.xlKey") === "1"; } catch { keyMode = false; }
  const saveKey = () => { try { localStorage.setItem("polids.xlKey", keyMode ? "1" : "0"); } catch { return false; } return true; };

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
  const markSel = () => root.querySelectorAll(".strip").forEach((x) => {
    x.classList.toggle("sel", x.dataset.k === open?.key);
    x.setAttribute("aria-expanded", String(x.dataset.k === open?.key));
  });
  const closeWin = (focusStrip = false) => {
    const key = open?.key;
    open = null;
    win.hidden = true;
    win.innerHTML = "";
    markSel();
    if (focusStrip && key) stripEl(key)?.focus();
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
    const note = open.note ? st.querySelector(`[data-f="${CSS.escape(open.note)}"]`)?.dataset.h || "" : "";
    win.innerHTML = winHtml(s, data, note, { vv: vv.get(open.key) }, keyMode);
    win.setAttribute("aria-label", `Flight ${s.callsign || ""}`);
    win.hidden = false;
    markSel();
    placeAt();
  };

  // VV z dwóch kolejnych odczytów sieci (znacznik czasu VATSIM); ten sam odczyt nic nie zmienia, przerwa > 150 s zeruje
  const trackVv = (d) => {
    const ts = Date.parse(d.updated || "") / 1000 || d.now_ts;
    const seen = new Set();
    byKey.forEach((s, k) => {
      if (s.planned || s.state === "offline" || !has(s.altitude)) return;
      seen.add(k);
      const p = alts.get(k);
      if (p && ts - p.ts < 10) return;
      if (p && ts - p.ts <= 150) vv.set(k, (s.altitude - p.alt) / (ts - p.ts) * 60);
      else vv.delete(k);
      alts.set(k, { alt: s.altitude, ts });
    });
    [...alts.keys()].forEach((k) => { if (!seen.has(k)) { alts.delete(k); vv.delete(k); } });
  };

  const render = () => {
    const d = data;
    byKey = new Map();
    ["departures", "arrivals", "local", "planned"].forEach((k) => d[k].forEach((s) => byKey.set(s.kind + ":" + s.callsign, s)));
    trackVv(d);
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
    if (e.target.closest(".xw-x")) return closeWin(open?.kb);
    if (e.target.closest(".xw-key")) {
      keyMode = !keyMode;
      saveKey();
      drawWin();
      return win.querySelector(".xw-key")?.focus();
    }
    if (win.contains(e.target)) return;
    const st = e.target.closest(".strip");
    if (!st) return closeWin();
    if (e.detail > 1) return;   // drugi klik dwukliku (mapa) nie zamyka okna otwartego pierwszym
    if (open?.key === st.dataset.k) return closeWin();
    const r = st.getBoundingClientRect();
    open = { key: st.dataset.k, dx: e.clientX - r.left - 24, note: e.target.closest("[data-f]")?.dataset.f || null, kb: false };
    drawWin();
  });
  // klawiatura: Enter / spacja na pasku otwiera i zamyka okno (fokus na ×), Esc wraca na pasek
  root.addEventListener("keydown", (e) => {
    const st = e.target.classList?.contains("strip") ? e.target : null;
    if (!st || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    if (open?.key === st.dataset.k) return closeWin(true);
    open = { key: st.dataset.k, dx: 0, note: null, kb: true };
    drawWin();
    win.querySelector(".xw-x")?.focus();
  });
  root.addEventListener("dblclick", (e) => {
    const s = byKey.get(e.target.closest(".strip")?.dataset.k);
    if (s && !s.planned) { closeWin(); location.hash = "#map/" + encodeURIComponent(s.callsign); }
  });
  // klik poza STRIP zamyka okno; przycisk KEY przerysowuje okno, więc jego cel jest już odłączony od dokumentu
  const onDocClick = (e) => { if (open && e.target.isConnected && !root.contains(e.target)) closeWin(); };
  const onKey = (e) => { if (e.key === "Escape" && open && visible()) { e.preventDefault(); closeWin(open.kb); } };
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
