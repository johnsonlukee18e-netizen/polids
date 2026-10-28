import { api, esc, h, ONLINE_EVENT } from "./api.js";

// OTHER › FLIGHT PLAN (0.13.0, issue #23): plan lotu po znaku wywoławczym (GET /api/vatsim/flightplan/<ZNAK>).
// Jedno pole (wielkie litery; Enter albo SHOW pokazuje, Esc czyści pole), nad wynikiem nagłówek ze znakiem, stanem
// ONLINE / PREFILED i odnośnikiem MAP › (#map/<ZNAK>: szczegóły lotu na mapie). Wartości w kratkach w dwóch grupach:
// pilot (imię, nazwisko, PID, godziny pilota i ATC, rating) i plan lotu w kolejności pól planu ICAO (7 znak + SSR,
// 8 reguły, 9 typ / turbulencja, 10 wyposażenie, 13 lotnisko i EOBT, 15 prędkość / poziom / trasa, 16 lotnisko
// docelowe / EET / zapasowe, 18 inne informacje rozbite na wskaźniki, 19 autonomia); pilot online także "teraz"
// (SSR, wysokość, GS, kurs). Imię i nazwisko to podział nazwy z sieci (heurystyka): pełna nazwa jest w dymku.
// Pokazany plan odświeża się co 30 s, gdy podzakładka jest na ekranie. Moduł nie zapisuje adresu sam:
// onLookup(znak) raz na każde wyszukanie z pola (OTHER zapisuje #other/flight-plan/<ZNAK>), odświeżenie go nie woła.

const REFRESH_MS = 30000;
// godziny pilota nie zdążyły (hours_pending): jedno dodatkowe pytanie po chwili, bez czekania na odświeżenie
const HOURS_RETRY_MS = 4000;
const RULES = { I: "IFR", V: "VFR", Y: "IFR, then VFR", Z: "VFR, then IFR" };
const WAKE = { L: "light", M: "medium", H: "heavy", J: "super" };
// znak jak w endpointcie: 2-12 liter i cyfr (wpisane spacje i myślniki, np. "SP-ABC", są pomijane)
export const CALLSIGN_RE = /^[A-Z0-9]{2,12}$/;
export const cleanCallsign = (v) => String(v ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12);

// Pola 10 i 18: equipment() i field18() przeniesione z dawnej zakładki STRIP (usuniętej w 0.13.0), bez zmian w działaniu.
// pole 10 z pełnego typu: "B38M/M-SDE2E3FGHIJ1RWXY/LB1" → typ, WTC, NAV/COM, dozorowanie
export function equipment(full) {
  const m = /^([A-Z0-9]{2,4})(?:\/([LMHJ]))?(?:-([A-Z0-9]*))?(?:\/([A-Z0-9]*))?$/.exec(String(full || "").trim().toUpperCase());
  if (!m) return { type: null, wake: null, navcom: null, surv: null };
  return { type: m[1], wake: m[2] || null, navcom: m[3] || null, surv: m[4] ?? null };
}

const F18_KEYS = new Set(["STS", "PBN", "NAV", "COM", "DAT", "SUR", "DEP", "DEST", "DOF", "REG", "EET", "SEL", "TYP", "CODE",
  "DLE", "OPR", "ORGN", "PER", "ALTN", "RALT", "TALT", "RIF", "RMK", "RVR", "RFP", "EUR", "IFP"]);
// pole 18 z uwag: { PBN: "A1B1", DOF: "261028", RMK: "TCAS", ... } w kolejności z planu; "/V/", "/R/", "/T/" pomijamy
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

const has = (v) => v !== null && v !== undefined && v !== "";

// pole 15, prędkość: TAS w węzłach jako N + 4 cyfry ("450" → "N0450"); gotowe "N0450", "K0830", "M078" bez zmian
export function speedText(tas) {
  const s = String(tas ?? "").trim().toUpperCase();
  if (/^(?:[NK]\d{4}|M\d{3})$/.test(s)) return s;
  return /^\d{1,4}$/.test(s) && Number(s) > 0 ? "N" + s.padStart(4, "0") : null;
}

// pole 15, poziom: "37000", "FL370", "F370", "370" (setki stóp) → "F370"; do 6500 ft wysokość ("3500" → "A035");
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

// czas trwania HHMM jako H:MM (EET, autonomia): "0130" → "1:30", "45" → "0:45"
export function durationText(v) {
  const s = String(v ?? "").trim();
  if (!/^\d{1,4}$/.test(s)) return null;
  const p = s.padStart(4, "0"), mm = Number(p.slice(2));
  return mm < 60 ? `${Number(p.slice(0, 2))}:${p.slice(2)}` : null;
}

// godzina HHMM (EOBT): "930" → "0930"; poza 0000-2359 → null
export function clockText(v) {
  const s = String(v ?? "").trim();
  if (!/^\d{3,4}$/.test(s)) return null;
  const p = s.padStart(4, "0");
  return Number(p.slice(0, 2)) < 24 && Number(p.slice(2)) < 60 ? p : null;
}

export const hoursText = (v) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(1) : null);

// kratka: mała etykieta nad wartością; brak wartości = "–"; wide = długi tekst (trasa, uwagi) zawijany
function box(label, value, { tip = "", cls = "", wide = false } = {}) {
  const c = ["fpb", cls, wide ? "wide" : ""].filter(Boolean).join(" ");
  return `<div class="${c}"${tip ? ` title="${esc(tip)}"` : ""}><span class="fpb-k">${esc(label)}</span>`
    + `<span class="fpb-v">${has(value) ? esc(value) : "–"}</span></div>`;
}

// wiersz planu: numer pola z opisem w dymku, obok kratki
const item = (n, tip, boxes) => `<div class="fpl-item"><span class="fpl-n" title="${esc(`Item ${n}: ${tip}`)}">${n}</span>`
  + `<div class="fpl-boxes">${boxes}</div></div>`;

function pilotHtml(d) {
  const nameTip = d.name ? `Name as entered: ${d.name}` : "No name entered";
  const hrs = d.hours || {};
  const pilotH = hoursText(hrs.pilot), atcH = hoursText(hrs.atc);
  const r = d.pilot_rating;
  return `<section class="fpl-group fpl-pilot"><h3 class="fpl-h">Pilot</h3><div class="fpl-boxes">
    ${box("First name", d.first_name, { tip: nameTip, cls: "name" })}
    ${box("Last name", d.last_name, { tip: nameTip, cls: "name" })}
    ${box("PID", d.pid, { tip: "Pilot ID" })}
    ${box("Pilot hours", pilotH, { tip: pilotH ? `${pilotH} hours as pilot` : d.hours_error || "" })}
    ${box("ATC hours", atcH, { tip: atcH ? `${atcH} hours as controller` : d.hours_error || "" })}
    ${box("Rating", r ? r.short || String(r.id) : null, { tip: r?.long || (d.status === "online" ? "" : "Known for online pilots only") })}
  </div>${d.hours_error ? `<p class="fpl-note">${esc(d.hours_error)}</p>` : ""}</section>`;
}

function positionHtml(p) {
  if (!p) return "";
  const n = (v) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null);
  const alt = n(p.altitude), gs = n(p.groundspeed), hdg = n(p.heading);
  return `<section class="fpl-group fpl-now"><h3 class="fpl-h">Now</h3><div class="fpl-boxes">
    ${box("SSR", p.squawk, { tip: "Transponder code set now" })}
    ${box("Altitude", alt === null ? null : `${alt} ft`)}
    ${box("GS", gs === null ? null : `${gs} kt`, { tip: "Ground speed" })}
    ${box("HDG", hdg === null ? null : String(hdg % 360).padStart(3, "0"), { tip: "Heading" })}
  </div></section>`;
}

function planHtml(d) {
  const fp = d.flight_plan;
  if (!fp) return `<section class="fpl-group fpl-plan"><h3 class="fpl-h">Flight plan</h3><p class="hint fpl-none">No flight plan filed.</p></section>`;
  const eq = equipment(fp.aircraft_icao);
  const type = fp.aircraft || eq.type, wake = fp.wake || eq.wake;
  const typeTip = [fp.aircraft_icao, fp.aircraft_faa].filter(Boolean).join(" · ");
  const f18 = Object.entries(field18(fp.remarks));
  const eet = durationText(fp.enroute_time), end = durationText(fp.fuel_time);
  return `<section class="fpl-group fpl-plan"><h3 class="fpl-h">Flight plan${has(fp.revision_id) ? ` <span class="fpl-rev">revision ${esc(fp.revision_id)}</span>` : ""}</h3>
    ${item(7, "aircraft identification and SSR code", box("Callsign", d.callsign) + box("SSR", fp.assigned_squawk, { tip: fp.assigned_squawk ? "Assigned SSR code" : "No code assigned" }))}
    ${item(8, "flight rules", box("Rules", fp.rules, { tip: RULES[fp.rules] || "" }))}
    ${item(9, "type of aircraft and wake turbulence category", box("Type", type, { tip: typeTip }) + box("Wake", wake, { tip: wake ? `Wake turbulence category ${WAKE[wake] || wake}` : "" }))}
    ${item(10, "equipment and capabilities", box("Equipment", eq.navcom, { tip: "Radio communication, navigation and approach aid equipment" }) + box("Surveillance", eq.surv, { tip: "Surveillance equipment" }))}
    ${item(13, "departure aerodrome and time", box("ADEP", fp.departure) + box("EOBT", clockText(fp.deptime), { tip: "Estimated off-block time (UTC)" }))}
    ${item(15, "cruising speed, level and route", box("Speed", speedText(fp.tas), { tip: has(fp.tas) ? `True airspeed ${fp.tas} kt` : "" })
      + box("Level", levelText(fp.altitude), { tip: has(fp.altitude) ? `Requested level ${fp.altitude}` : "" }) + box("Route", fp.route, { wide: true, cls: "route" }))}
    ${item(16, "destination aerodrome, total EET and alternate", box("ADES", fp.arrival) + box("EET", eet, { tip: eet ? `Total estimated elapsed time ${eet} (H:MM)` : "" })
      + box("ALTN", fp.alternate, { tip: "Alternate aerodrome" }))}
    ${item(18, "other information", f18.length ? f18.map(([k, v]) => box(k, v, { wide: v.length > 24, cls: "f18" })).join("") : box("Other information", null))}
    ${item(19, "supplementary information", box("Endurance", end, { tip: end ? `Fuel endurance ${end} (H:MM)` : "" }))}
  </section>`;
}

// cały wynik dla danych z /api/vatsim/flightplan; czysta funkcja (testy w Node), każdy tekst z sieci escapowany
export function fplHtml(d) {
  const online = d.status === "online";
  const cs = String(d.callsign || "");
  return `<div class="fpl-head">
      <span class="fpl-cs">${esc(cs)}</span>
      <span class="fpl-state ${online ? "on" : "pre"}" title="${online ? "Pilot connected now" : "Flight plan filed before connecting"}">${online ? "ONLINE" : "PREFILED"}</span>
      <a class="fpl-map" href="#map/${encodeURIComponent(cs)}" title="Show the flight on the map">MAP ›</a>
    </div>
    <div class="fpl-row">${pilotHtml(d)}${online ? positionHtml(d.position) : ""}</div>
    ${planHtml(d)}`;
}

const EMPTY = `<p class="hint fpl-empty">Type a callsign and press Enter.</p>`;

export function mountFlightPlan(pane, { start = "", onLookup = () => {} } = {}) {
  const root = h(`<div class="fpl">
    <div class="fpl-bar">
      <input class="field fpl-q" type="text" maxlength="14" placeholder="CALLSIGN" spellcheck="false" autocomplete="off" aria-label="Callsign">
      <button class="btn primary fpl-go" type="button">SHOW</button>
      <span class="fpl-msg"></span>
    </div>
    <div class="fpl-out">${EMPTY}</div>
  </div>`);
  pane.append(root);
  const input = root.querySelector(".fpl-q"), msg = root.querySelector(".fpl-msg"), out = root.querySelector(".fpl-out");
  // cs = pokazywany znak ("" = pusty formularz); data = ostatnia odpowiedź; seq odrzuca spóźnione odpowiedzi
  let cs = "", data = null, failed = false, loadedAt = 0, seq = 0, timer = null, retry = null, dead = false;
  const visible = () => root.isConnected && root.offsetParent !== null;
  const note = (text = "", cls = "hint") => { msg.className = "fpl-msg " + cls; msg.textContent = text; };

  // quiet = odświeżenie: błąd nie kasuje pokazanego planu, tylko pisze, że nie odświeżono
  const load = async (quiet = false) => {
    const my = ++seq, want = cs;
    if (!quiet) { data = null; out.innerHTML = `<p class="hint">Loading…</p>`; }
    try {
      const d = await api(`/api/vatsim/flightplan/${encodeURIComponent(want)}`);
      if (dead || my !== seq) return;
      data = d; failed = false; loadedAt = Date.now();
      out.innerHTML = fplHtml(d);
      note();
      if (d.hours_pending && retry === null) retry = setTimeout(() => load(true), HOURS_RETRY_MS);
    } catch (e) {
      if (dead || my !== seq) return;
      failed = true; loadedAt = Date.now();
      if (quiet && data) note(`Not refreshed: ${e.message}`, "error");
      else { data = null; out.innerHTML = `<p class="error fpl-err">${esc(e.message)}</p>`; note(); }
    }
  };
  // retry: null = dla tego znaku jeszcze nie pytano ponownie o godziny; potem id zegara (raz na wyszukanie)
  const stopRefresh = () => { clearInterval(timer); clearTimeout(retry); timer = retry = null; };
  const show = (value) => {
    const v = cleanCallsign(value);
    input.value = v;
    stopRefresh();
    seq++;
    cs = ""; data = null; failed = false;
    if (!v) { out.innerHTML = EMPTY; note(); return false; }
    if (!CALLSIGN_RE.test(v)) { out.innerHTML = EMPTY; note("Callsign = 2–12 letters and digits", "error"); return false; }
    cs = v;
    load();
    timer = setInterval(() => { if (visible()) load(true); }, REFRESH_MS);
    return true;
  };
  // wyszukanie z pola: krok w historii (onLookup) tylko dla poprawnego znaku
  const submit = () => {
    if (show(input.value)) onLookup(cs);
    focus();
  };

  input.addEventListener("input", () => {
    const v = cleanCallsign(input.value);
    if (v !== input.value) input.value = v;
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); submit(); }
    else if (e.key === "Escape" && input.value) { e.preventDefault(); input.value = ""; }
  });
  root.querySelector(".fpl-go").addEventListener("click", submit);
  // serwer wrócił po przerwie: plan, którego nie udało się pobrać, od razu jeszcze raz
  const online = () => { if (cs && failed) load(!!data); };
  window.addEventListener(ONLINE_EVENT, online);

  const focus = () => { input.focus(); input.select(); };
  if (start) show(start);
  return {
    // arg: znak z adresu ("" = pusty formularz); undefined (przycisk menu) zostawia pokazany plan
    activate(arg) {
      if (arg !== undefined && cleanCallsign(arg) !== cs) show(arg);
      else if (cs && Date.now() - loadedAt > REFRESH_MS) load(true);
      focus();
    },
    focus,
    destroy() {
      dead = true;
      stopRefresh();
      window.removeEventListener(ONLINE_EVENT, online);
    },
  };
}
