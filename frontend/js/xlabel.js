import { esc } from "./api.js";

// OTHER › FLIGHT PLAN (0.14.2, issue #35): okno "EXTENDED LABEL WINDOW" z instrukcji SDD 2014 (rozdz. 2.1.2.3,
// Figure 2-6, Table 2-13) dla wybranego lotu, nad pełnym planem lotu. Osiem wierszy jak w SDD:
// 1 znak, W (RVSM), Y (8.33), pełny znak radiowy, typ transpondera / kod A; 2 liczba samolotów, typ / WTC, STS, ORCAM;
// 3 ADEP ADES (zapasowe) STAR albo SID, RWY, następna częstotliwość; 4 reguły, trasa (do 7 punktów), poziom wyjścia
// z FIR; 5 CFL RFL RATE, tekst RMK, RVR, stan koordynacji; 6 NAV/COM, dozorowanie, PBN; 7-8 dane Mode S (z sieci tylko
// HDG, GS, prędkość pionowa, prędkość zakrętu i kąt drogi z dwóch odczytów). Pola bez danych są puste jak w SDD (bez
// napisów "brak danych"); przycisk KEY w belce pokazuje nad wartościami nazwy pól.
// Cały układ jest w XL_LINES: wiersz = { gap (odstęp nad), nr (liczby do prawej w kolumnie), f: pola }; pole =
// { k, l (nazwa w KEY, tekst albo funkcja), n (opis w dymku), w (szerokość z Table 2-13 w znakach: kolumna i limit
// wartości), max (dłuższy limit, tylko znak), right (do prawej krawędzi okna), v(d, x) = tekst, { t, cls, tip }
// albo [{ t, cls }, ...] (kolorowe części) albo null }. Wartość dłuższa niż limit jest ucięta z "..." (clip); pełna
// jest w dymku pola. Moduł czysty (testy w Node): tylko esc z api.js.
// Pola 10 i 18 planu (equipment, field18, voiceType) są tutaj od 0.14.2; flightplan.js je eksportuje dalej.

// szerokość okna w znakach: najdłuższy wiersz Table 2-13 to 5 (CFL 3 + RFL 3 + RATE 10 + tekst 20 + RVR 6 + COORD 6
// i odstępy = 53)
export const XL_WIDTH = 54;
const ELL = "\u2026";

// pole 10 z pełnego typu: "B38M/M-SDE2E3FGHIJ1RWXY/LB1" albo lot w grupie "2/F16/M-SG/C" -> liczba samolotów, typ, WTC,
// NAV/COM, dozorowanie; zapis FAA ("H/B738/L") i inne -> same null
export function equipment(full) {
  const m = /^(?:(\d{1,2})\/)?([A-Z0-9]{2,4})(?:\/([LMHJ]))?(?:-([A-Z0-9]*))?(?:\/([A-Z0-9]*))?$/
    .exec(String(full || "").trim().toUpperCase());
  if (!m) return { count: null, type: null, wake: null, navcom: null, surv: null };
  return { count: m[1] ? Number(m[1]) : null, type: m[2], wake: m[3] || null, navcom: m[4] || null, surv: m[5] ?? null };
}

const F18_KEYS = new Set(["STS", "PBN", "NAV", "COM", "DAT", "SUR", "DEP", "DEST", "DOF", "REG", "EET", "SEL", "TYP", "CODE",
  "DLE", "OPR", "ORGN", "PER", "ALTN", "RALT", "TALT", "RIF", "RMK", "RVR", "RFP", "EUR", "IFP"]);
// pole 18 z uwag: { PBN: "A1B1", DOF: "261028", RMK: "TCAS", ... } w kolejności z planu; "/V/", "/R/", "/T/" pomijamy
// (łączność głosowa: voiceType, kratka Voice w polu 10)
export function field18(remarks) {
  const out = {};
  let key = null;
  for (const tok of String(remarks || "").toUpperCase().split(/\s+/)) {
    if (!tok || /^\/[VRT]\/$/.test(tok)) continue;
    const m = /^([A-Z]{3,4})\/(.*)$/.exec(tok);
    if (m && F18_KEYS.has(m[1])) {
      key = m[1];
      out[key] = out[key] ? `${out[key]} ${m[2]}`.trim() : m[2];
    } else {
      // tekst bez wskaźnika przed sobą = uwagi
      key = key || "RMK";
      out[key] = out[key] ? `${out[key]} ${tok}` : tok;
    }
  }
  return out;
}

// łączność głosowa z uwag: "V" (głos), "R" (tylko odbiór), "T" (tylko tekst); kilka znaczników: ostatni; null = brak
export function voiceType(remarks) {
  const found = String(remarks || "").toUpperCase().split(/\s+/).map((t) => /^\/([VRT])\/$/.exec(t)?.[1]).filter(Boolean);
  return found.length ? found[found.length - 1] : null;
}

const has = (v) => v !== null && v !== undefined && v !== "";
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

// pole 15, poziom: "37000", "FL370", "F370", "370" (setki stóp) -> "F370"; do 6500 ft wysokość ("3500" -> "A035");
// "VFR" i inne zapisy bez zmian
export function levelText(alt) {
  const s = String(alt ?? "").trim().toUpperCase();
  if (!s) return null;
  let m = /^FL?(\d{2,3})$/.exec(s);
  if (m) return "F" + m[1].padStart(3, "0");
  m = /^A(\d{2,3})$/.exec(s);
  if (m) return "A" + m[1].padStart(3, "0");
  if (/^\d+$/.test(s)) {
    const n = Number(s), ft = n < 1000 ? n * 100 : n;
    if (!ft) return null;
    return (ft >= 6500 ? "F" : "A") + String(Math.round(ft / 100)).padStart(3, "0");
  }
  return s;
}

// RFL w oknie: trzy cyfry poziomu ("F370" -> "370", "A035" -> "035"); "VFR" i inne zapisy bez zmian
export function fl3(level) {
  const s = String(level ?? "");
  if (!s) return null;
  return /^[FA]\d{3}$/.test(s) ? s.slice(1) : s;
}

// litery wyposażenia: pojedyncze albo z cyfrą (E1, J5, B1, ...)
const letters = (str) => new Set(String(str || "").toUpperCase().match(/[A-Z]\d*/g) || []);
// W: zielone = RVSM (W w polu 10a; bez pola 10a sufiks FAA L, W albo Z), żółte = zwolniony (STS/STATE), czerwone = bez
// RVSM (także STS/NONRVSM bez STATE) albo nieznane
export function rvsmClass(navcom, sts, faa) {
  if (navcom) {
    if (letters(navcom).has("W")) return "g";
  } else if (/^[LWZ]$/.test(String(faa || "").trim().toUpperCase().split("/").pop())) {
    return "g";
  }
  return /(^|\s)STATE(\s|$)/.test(String(sts || "").toUpperCase()) ? "y" : "r";
}
// Y: zielone = 8.33 (Y), żółte = bez 8.33, ale UHF (U), czerwone = bez 8.33 albo nieznane
export function vhf833Class(navcom) {
  const l = letters(navcom);
  return l.has("Y") ? "g" : l.has("U") ? "y" : "r";
}
// typ transpondera: S/ (Mode S: E H I L P S X), C/ (Mode C), A/ (tylko Mode A), "" (nieznany)
export function xpdrType(surv) {
  const l = letters(surv);
  if (["E", "H", "I", "L", "P", "S", "X"].some((c) => l.has(c))) return "S/";
  return l.has("C") ? "C/" : l.has("A") ? "A/" : "";
}

const RVSM_TIP = { g: "RVSM equipped", y: "RVSM exempt", r: "Not RVSM equipped or unknown" };
const VHF_TIP = { g: "8.33 equipped", y: "No 8.33, UHF equipped", r: "No 8.33 or unknown" };

const AIRWAY = /^[A-Z]{1,2}\d{1,3}[A-Z]?$/;
const PROC_NAME_RE = /^[A-Z]{2,5}\d[A-Z]$/;
const SPEED_LEVEL = /^[NKM]\d{3,4}(?:[FAMS]\d{3,4}|VFR)?$/;
const LATLON = /^\d{2,4}[NS]\d{3,5}[EW]$/;
// pas startowy w trasie VFR: "RWY29", "RW11", "R29", "29L"
const RUNWAY = /^(?:RWY?|RY|R)?\d{2}[LRC]?$/;
// słowa z opisowych tras VFR / lotów lokalnych ("VFR CIRCUITS RWY 29", "LOCAL TRAINING OVER CITY"), które nie są
// punktami (lista z dawnego okna lotu STRIP, 0.12.5)
const NOT_FIX = new Set(["DCT", "SID", "STAR", "IFR", "VFR", "SVFR", "OAT", "GAT", "IFPSTOP", "IFPSTART",
  "IN", "TO", "GO", "ON", "OF", "AT", "BY", "UP",
  "RWY", "RWYS", "RUNWAY", "LOCAL", "CIRCUIT", "CIRCUITS", "CCT", "CCTS", "CIRC", "TRAINING", "TRAIN", "TRNG", "TNG",
  "OVER", "CITY", "AREA", "ZONE", "STAY", "HOLD", "HOLDS", "HOLDING", "TOUCH", "LOW", "PASS", "LAND", "FULL", "STOP",
  "BACK", "THEN", "AND", "FROM", "VIA", "WITH", "THE", "LEFT", "RIGHT", "BASE", "HOME", "SAME", "ROUTE", "FILED", "RADAR",
  "VECTORS", "TOUR", "TEST", "CHECK", "FLIGHT", "FLT", "NAV", "GPS", "RNAV", "VMC", "APP", "APCH", "ILS", "RNP", "VOR",
  "NDB", "DME", "LOC", "CTR", "TMA", "CTA", "ATZ", "MATZ", "ATC"]);
// punkty znaczące trasy z planu (bez DCT, dróg lotniczych, SID/STAR, grup prędkość/poziom, pasów, słów opisowych
// i lotnisk ADEP/ADES), pierwsze `max`
export function routePoints(fp, max = 7) {
  const dep = String(fp?.departure || "").toUpperCase(), arr = String(fp?.arrival || "").toUpperCase();
  const pts = String(fp?.route || "").toUpperCase().split(/\s+/).map((t) => t.split("/")[0])
    .filter((t) => t && !NOT_FIX.has(t) && t !== dep && t !== arr && !RUNWAY.test(t) && !AIRWAY.test(t)
      && !PROC_NAME_RE.test(t) && !SPEED_LEVEL.test(t) && (/^[A-Z]{2,5}$/.test(t) || LATLON.test(t)));
  return pts.filter((t, i) => t !== pts[i - 1]).slice(0, max);
}

// punkty w polu trasy (41 znaków): bez cięcia nazw, nadmiarowe odpadają z końca z "..."
export function fitPoints(pts, max) {
  const all = pts.join(" ");
  if (all.length <= max) return all;
  const keep = [];
  for (const t of pts) {
    if ([...keep, t, ELL].join(" ").length > max) break;
    keep.push(t);
  }
  return [...keep, ELL].join(" ");
}

// wartość dłuższa niż limit pola: początek i "..." (razem najwyżej max znaków), kolory części zostają
export function clip(parts, max) {
  if (parts.reduce((n, p) => n + p.t.length, 0) <= max) return parts;
  const out = [];
  let room = max - 1;
  for (const p of parts) {
    if (room <= 0) break;
    out.push({ t: p.t.slice(0, room), cls: p.cls });
    room -= p.t.length;
  }
  const last = out[out.length - 1];
  if (last) last.t = last.t.trimEnd();
  return [...out.filter((p) => p.t), { t: ELL, cls: "more" }];
}

export const pad3 = (n) => (num(n) === null ? null : String(Math.round(n)).padStart(3, "0"));
// kąt 000..359 jak w ATC: 0 -> 360
export const deg3 = (n) => (num(n) === null ? null : String(((Math.round(n) % 360) + 360) % 360 || 360).padStart(3, "0"));
// prędkość pionowa w setkach ft/min ze znakiem: 1300 -> "+13", -820 -> "-8", 20 -> "0"
export function signedHundreds(fpm) {
  if (num(fpm) === null) return null;
  const n = Math.round(fpm / 100);
  return n > 0 ? `+${n}` : n < 0 ? String(n) : "0";
}
// liczba ze znakiem (prędkość zakrętu w stopniach na sekundę): 2.4 -> "+2", -0.4 -> "0"
const signed = (v) => {
  if (num(v) === null) return null;
  const n = Math.round(v);
  return n > 0 ? `+${n}` : n < 0 ? String(n) : "0";
};

const live = (d) => d.status === "online" && !!d.position;
const yellow = (t) => (has(t) ? { t: String(t), cls: "y" } : null);
const procKind = (d) => ((d.label || {}).proc?.kind === "SID" ? "SID" : "STAR");

export const XL_LINES = [
  { f: [
    // znak: kolumna 7 znaków jak w SDD, ale znak w sieci bywa dłuższy, więc limit 10 (wiersz dalej mieści się w XL_WIDTH)
    { k: "cs", l: "CALLSIGN", n: "Callsign", w: 7, max: 10, v: (d) => (d.callsign ? { t: d.callsign, cls: "g" } : null) },
    { k: "wy", l: "W Y", n: "RVSM and 8.33 status", w: 2, v: (d, x) => {
      const w = rvsmClass(x.eq.navcom, x.f18.STS, x.fp.aircraft_faa), y = vhf833Class(x.eq.navcom);
      return [{ t: "W", cls: w, tip: `${RVSM_TIP[w]}, ${VHF_TIP[y]}` }, { t: "Y", cls: y }];
    } },
    { k: "tel", l: "FULL CALLSIGN", n: "Radio callsign", w: 28, v: (d) => (d.telephony ? { t: d.telephony, cls: "g" } : null) },
    { k: "xpdr", l: "XPDR", n: "Transponder type and Mode A code", w: 6, right: true,
      v: (d, x) => (live(d) && x.pos.squawk ? xpdrType(x.eq.surv) + x.pos.squawk : null) },
  ] },
  // wcięcie wiersza 2 w Figure 2-6 to pusta kolumna NUM (2 znaki i odstęp): typ zaczyna się 3 znaki od brzegu
  { f: [
    { k: "num", l: "NUM", n: "Number of aircraft", w: 2, v: (d, x) => (x.eq.count >= 2 ? String(x.eq.count) : null) },
    { k: "type", l: "TYPE/WTC", n: "Aircraft type and wake turbulence category", w: 6, v: (d, x) => {
      const t = x.fp.aircraft || x.eq.type, w = x.fp.wake || x.eq.wake;
      return t ? `${t}${w ? "/" + w : ""}` : null;
    } },
    { k: "sts", l: "STS", n: "Special handling", w: 20, v: (d, x) => x.f18.STS || null },
    // ORCAM: kod przydzielony, tylko gdy różni się od nadawanego (prefile: zawsze, nic jeszcze nie nadaje)
    { k: "orcam", l: "ORCAM", n: "Assigned SSR code", w: 4, right: true,
      v: (d, x) => (x.fp.assigned_squawk && x.fp.assigned_squawk !== x.pos.squawk ? yellow(x.fp.assigned_squawk) : null) },
  ] },
  { gap: true, f: [
    { k: "adep", l: "ADEP", n: "Departure aerodrome", w: 4, v: (d, x) => x.fp.departure || null },
    { k: "ades", l: "ADES", n: "Destination aerodrome", w: 4, v: (d, x) => x.fp.arrival || null },
    { k: "altn", l: "ALTN", n: "Alternate aerodromes", w: 11, v: (d, x) => {
      const a = [x.fp.alternate, ...(x.f18.ALTN || "").split(/\s+/)].map((v) => String(v || "").toUpperCase())
        .filter((v) => /^[A-Z]{4}$/.test(v) && v !== "ZZZZ");
      return a.length ? `(${[...new Set(a)].slice(0, 2).join(" ")})` : null;
    } },
    { k: "proc", l: procKind, n: (d) => (procKind(d) === "SID" ? "Departure procedure" : "Arrival procedure"), w: 7,
      v: (d, x) => x.lab.proc?.name || null },
    { k: "rwy", l: "RWY", n: (d) => (procKind(d) === "SID" ? "Departure runway" : "Arrival runway"), w: 6,
      v: (d, x) => (x.lab.proc?.runway ? `RWY${x.lab.proc.runway}` : null) },
    // NEXT FREQ zawsze białe: stanów ROF i "przejęty przez następny organ" z SDD sieć nie zna
    { k: "nfq", l: "NEXT FREQ", n: "Next frequency", w: 7, right: true, v: (d, x) => x.lab.next_freq || null },
  ] },
  { f: [
    { k: "rules", l: "FR", n: "Flight rules", w: 1, v: (d, x) => yellow(x.fp.rules) },
    // punkty przed samolotem (w powietrzu), inaczej pierwsze punkty z planu; w oknie do 7 (i do 41 znaków), w dymku
    // wszystkie
    { k: "route", l: "ROUTE", n: "Route", w: 41, v: (d, x) => {
      const pts = Array.isArray(x.lab.route_ahead) ? x.lab.route_ahead.map(String) : routePoints(x.fp, 99);
      if (!pts.length) return null;
      const t = fitPoints(pts.slice(0, 7), 41), more = t.endsWith(ELL);
      const head = { t: more ? t.slice(0, -1) : t, tip: pts.join(" "), cut: more || pts.length > 7 };
      return more ? [head, { t: ELL, cls: "more" }] : [head];
    } },
    { k: "xfl", l: "FIR EXIT", n: "FIR exit level", w: 4, right: true, v: (d, x) => {
      const e = x.lab.fir_exit, lvl = pad3(e?.level);
      return lvl ? { t: "/" + lvl, tip: `/${lvl}${e.point ? ` at ${e.point}` : ""}` } : null;
    } },
  ] },
  { f: [
    // CFL, RATE i stan koordynacji: tego sieć nie podaje, pola zostają puste (SDD: koordynacja niewidoczna bez potrzeby)
    { k: "cfl", l: "CFL", n: "Cleared flight level", w: 3, v: () => null },
    { k: "rfl", l: "RFL", n: "Requested flight level", w: 3, v: (d, x) => yellow(fl3(levelText(x.fp.altitude))) },
    { k: "rate", l: "RATE", n: "Assigned vertical rate", w: 10, v: () => null },
    { k: "free", l: "FREE TEXT", n: "Remarks", w: 20, v: (d, x) => x.f18.RMK || null },
    { k: "rvr", l: "RVR", n: "Minimum RVR", w: 6, v: (d, x) => yellow(x.f18.RVR) },
    { k: "coord", l: "COORD", n: "Coordination status", w: 6, right: true, v: () => null },
  ] },
  { f: [
    { k: "navcom", l: "NAV/COM", n: "Navigation and communication equipment", w: 18, v: (d, x) => x.eq.navcom || null },
    { k: "surv", l: "SUR", n: "Surveillance equipment", w: 15, v: (d, x) => x.eq.surv || null },
    // PBN w swojej kolumnie za SUR (kolumna 35 jak w Figure 2-6), nie przy prawej krawędzi
    { k: "pbn", l: "PBN", n: "PBN capabilities", w: 16, v: (d, x) => x.f18.PBN || null },
  ] },
  // Mode S: adres, wybrana wysokość, IAS, Mach, TAS, barometryczna prędkość pionowa i przechylenie nie istnieją
  // w danych sieci (szacunki wprowadzałyby w błąd), więc zostają puste; TAS z planu to nie TAS teraz
  { gap: true, nr: true, f: [
    { k: "addr", l: "ADDR", n: "Aircraft address", w: 6, v: () => null },
    { k: "sel", l: "SEL", n: "Selected altitude", w: 3, v: () => null },
    { k: "hdg", l: "HDG", n: "Heading", w: 3, v: (d, x) => (live(d) ? deg3(x.pos.heading) : null) },
    { k: "ias", l: "IAS", n: "Indicated airspeed", w: 4, v: () => null },
    { k: "mach", l: "MACH", n: "Mach number", w: 3, v: () => null },
    { k: "tas", l: "TAS", n: "True airspeed", w: 4, v: () => null },
  ] },
  { nr: true, f: [
    { k: "gs", l: "GS", n: "Ground speed", w: 4, v: (d, x) => (live(d) ? pad3(x.pos.groundspeed) : null) },
    { k: "ivv", l: "IVV", n: "Vertical speed (hundreds of ft/min)", w: 4, v: (d, x) => {
      const t = live(d) ? signedHundreds(x.pos.vv_fpm) : null;
      return t ? { t, tip: `${x.pos.vv_fpm > 0 ? "+" : ""}${Math.round(x.pos.vv_fpm)} ft/min` } : null;
    } },
    { k: "bvv", l: "BVV", n: "Barometric vertical speed", w: 4, v: () => null },
    { k: "tar", l: "TAR", n: "Turn rate (degrees per second)", w: 3, v: (d, x) => (live(d) ? signed(x.pos.turn_rate) : null) },
    { k: "roll", l: "ROLL", n: "Roll angle", w: 3, v: () => null },
    { k: "trk", l: "TRK", n: "Track", w: 3, v: (d, x) => (live(d) ? deg3(x.pos.track) : null) },
  ] },
];

// pola okna: [{ line, gap, nr, f: [{ k, l, n, w, max, right, parts: [{ t, cls }] | null, full, tip, cut }] }];
// full = cała wartość, tip = tekst do dymku (domyślnie full), cut = w oknie nie ma całej wartości (ucięta albo, jak
// trasa, skrócona już w v: tip i cut z pierwszej części)
export function extLabel(d) {
  const fp = d.flight_plan || {};
  const x = { fp, eq: equipment(fp.aircraft_icao), f18: field18(fp.remarks), pos: d.position || {}, lab: d.label || {} };
  return XL_LINES.map((ln, i) => ({ line: i + 1, gap: !!ln.gap, nr: !!ln.nr, f: ln.f.map((f) => {
    const raw = f.v(d, x);
    const max = f.max || f.w;
    const list = !has(raw) ? null : Array.isArray(raw) ? raw : [typeof raw === "object" ? raw : { t: String(raw) }];
    const all = list && list.map((p) => ({ t: String(p.t), cls: p.cls || "" }));
    const parts = all && clip(all, max);
    const shown = parts ? parts.map((p) => p.t).join("") : null;
    const full = all ? all.map((p) => p.t).join("") : null;
    const tip = list ? String(list[0].tip ?? full) : null;
    return { k: f.k, l: typeof f.l === "function" ? f.l(d) : f.l, n: typeof f.n === "function" ? f.n(d) : f.n, w: f.w, max,
      right: !!f.right, parts, full, tip, cut: full !== null && (full !== shown || !!list[0].cut) };
  }) }));
}

function fieldHtml(f, key) {
  const val = f.parts ? f.parts.map((p) => (p.cls ? `<span class="${p.cls}">${esc(p.t)}</span>` : esc(p.t))).join("") : "";
  const cls = `xl-f${f.right ? " rt" : ""}${f.parts ? "" : " nil"}${f.cut ? " cut" : ""}`;
  const title = f.parts ? `${f.n}: ${f.tip}` : f.n;
  return `<span class="${cls}" data-f="${esc(f.k)}" style="--w:${f.w}" title="${esc(title)}">`
    + `${key ? `<span class="xl-k">${esc(f.l)}</span>` : ""}<span class="xl-v">${val}</span></span>`;
}

// okno dla danych z /api/vatsim/flightplan (także prefile i pilot online bez planu); key = nazwy pól nad wartościami
export function xlHtml(d, { key = false } = {}) {
  const lines = extLabel(d).map((ln) => `<div class="xl-ln${ln.gap ? " gap" : ""}${ln.nr ? " nr" : ""}" `
    + `data-ln="${ln.line}">${ln.f.map((f) => fieldHtml(f, key)).join("")}</div>`).join("");
  return `<section class="fpl-xl" aria-label="Extended label">`
    + `<div class="xl-head"><span class="xl-t">EXTENDED LABEL WINDOW</span>`
    + `<button type="button" class="btn xl-key${key ? " on" : ""}" aria-pressed="${key}" title="Show field names">KEY</button></div>`
    + `<div class="xl-body${key ? " key" : ""}">${lines}</div></section>`;
}
