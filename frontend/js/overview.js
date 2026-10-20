// AERODROME › OVERVIEW: jeden ekran dla całego FIR EPWW, coś jak self-checkin przed otwarciem stanowiska.
// Panele (dane z /api/overview, każdy z własnym komunikatem błędu):
//   1. poziom przejściowy (TL): jeden dla całego kraju, FL080, a FL090, gdy gdziekolwiek QNH ≤ 995 hPa,
//   2. METAR + TAF wszystkich kontrolowanych lotnisk ze stanem LVP i pasem w użyciu (z ATIS albo preferowany,
//      jak w AERODROME › INFO), kolory jak w METEO,
//   3. NOTAM-y obowiązujące teraz,
//   4. restrykcje ECFMP dla FIR EPWW i regulacje vIFF na sektorach EP,
//   5. Airport Monitor vIFF (przepustowość, ruch, loty z CTOT) + liczby lotów z sieci VATSIM.
// Filtr stanowiska u góry: ACC / APP / TWR. APP i ACC zawężają panele do swoich lotnisk i pokazują checklistę
// otwarcia stanowiska, TWR przeskakuje od razu do PRZEGLĄDU danego lotniska (onGoto). Przy ACC / APP przełącznik
// MINE / ALL: MINE ukrywa lotniska, które przed wybranym stanowiskiem obsługuje teraz ktoś inny (covered_by z serwera).
import { api, choiceGet, choiceSet, esc, h, lsGet, lsSet, lvpState, lvpTip, ONLINE_EVENT, POS_KEY } from "./api.js";
import { colorize, wxLines } from "./tabs/meteo.js";
import { renderChecklist } from "./checklist.js";

const CHK_KEY = "checklist.overview.open-position";
const SCOPE_KEY = "overview.scope";
const REFRESH_MS = 60000;

const hm = (iso) => (iso ? new Date(iso).toISOString().slice(11, 16) + "Z" : "–");
const dhm = (iso) => {
  if (!iso) return "–";
  const d = new Date(iso);
  return `${String(d.getUTCDate()).padStart(2, "0")}.${String(d.getUTCMonth() + 1).padStart(2, "0")} ${hm(iso)}`;
};
const n0 = (v) => (v === null || v === undefined ? "–" : esc(v));
// liczba pojedyncza tylko dla 1: "1 aerodrome", "2 aerodromes"
const adWord = (n) => (n === 1 ? "aerodrome" : "aerodromes");

// --- 1. poziom przejściowy: jeden dla całego kraju, bez osobnego TL przy lotniskach ------------------------------
function tlPanel(d) {
  const t = d.tl || {};
  const low = t.low || [];
  const miss = t.missing || [];
  const thr = `QNH ≤ ${n0(t.threshold_hpa)} hPa`;
  const head = t.fl ? `TL <b>${esc(t.text)}</b> nationwide` : "TL <b>–</b> (no QNH)";
  return `<div class="ov-tl-big">${head}</div>
    <div class="hint ov-tl-rule">${esc(t.rule || "")}</div>
    ${t.qnh_icao ? `<div class="ov-tl-min">lowest QNH: <b class="ic">${esc(t.qnh_icao)}</b> ${n0(t.qnh_min)} hPa</div>` : ""}
    ${low.length ? `<div class="ov-note warn">${thr}: ${low.map(esc).join(", ")}</div>` : ""}
    ${miss.length ? `<div class="${t.uncertain ? "ov-note warn" : "hint"}">no QNH (not taken into account): ${miss.map(esc).join(", ")}${
      t.uncertain ? ` – if ${thr} there, TL is ${esc(t.raised)}` : ""}</div>` : ""}
    <div class="hint ov-src">${esc(t.normal || "")}, and when ${thr} at any of the ${n0((t.stations || 0) + miss.length)} controlled aerodromes,
      ${esc(t.raised || "")} nationwide. TA ${n0(t.ta_ft)} ft.</div>`;
}

// --- 2. METAR / TAF / LVP / pas w użyciu ---------------------------------------------------------------------
// stan LVP z progami z AIP; dymek: progi trzech faz (lvpTip), przy stanie też powody
function lvpChip(lvp) {
  if (!lvp) return "";
  const s = lvpState(lvp), tip = lvpTip(lvp);
  const short = { lvp: "LVP IN FORCE", prep: "LVP PREP", cancel: `LVP CNL ${lvp.since || ""}`.trim(), na: "LVP n/a", off: "LVP off" };
  const cls = { lvp: "bad", prep: "warn", cancel: "ok", na: "na", off: "" }[s.cls];
  const scope = lvp.scope === "DEP" && lvp.state ? " DEP" : "";
  return `<span class="ov-chip ${cls}" data-tip="${esc([s.label, ...(lvp.reasons || []), tip].filter(Boolean).join("\n"))}">${esc(short[s.cls] + scope)}</span>`;
}

// Pas w użyciu (a.runway z serwera, te same wartości co AERODROME › INFO): z ATIS pełna ramka z literą ATIS, pas
// preferowany ramka kreskowana i PREF, jak "preferred" w AERODROME. Jeden pas do lądowań i startów: RWY 29, różne:
// ARR 33 DEP 29 (kolory ról jak na paskach: ARR żółty, DEP niebieski). Dymek: ATIS albo powód wyboru pasa.
export function runwayChip(rw, atis = null) {
  if (!rw || !rw.arr) return "";
  const fromAtis = rw.source === "ATIS";
  const dep = rw.dep || rw.arr;
  const body = dep === rw.arr ? `<i>RWY</i><b>${esc(rw.arr)}</b>`
    : `<i>ARR</i><b class="arr">${esc(rw.arr)}</b><i>DEP</i><b class="dep">${esc(dep)}</b>`;
  const tip = fromAtis ? [`Runway in use · ATIS ${rw.letter || ""}`.trim(), atis?.callsign] : ["Preferred runway", rw.reason];
  return `<span class="ov-rwy ${fromAtis ? "atis" : "pref"}" data-tip="${esc(tip.filter(Boolean).join("\n"))}"><i class="src">${
    fromAtis ? esc(`ATIS ${rw.letter || ""}`.trim()) : "PREF"}</i>${body}</span>`;
}

function wxRow(a, open) {
  const p = a.parsed || {};
  const t = a.traffic || {};
  const obs = p.time ? `${esc(p.time.slice(2, 4))}:${esc(p.time.slice(4, 6))}Z` : "";
  // litera ATIS jest w ramce pasa, gdy pas jest z ATIS; ATIS bez czytelnego pasa ma osobną ramkę
  const atisChip = a.atis && a.runway?.source !== "ATIS";
  return `<div class="ov-aero${open ? " open" : ""}${a.covered_by ? " other" : ""}" data-icao="${esc(a.icao)}">
    <div class="ov-aero-head">
      <b class="ic">${esc(a.icao)}</b>
      <span class="cat cat-${esc(p.flight_category || "")}">${esc(p.flight_category || "–")}</span>
      ${lvpChip(a.lvp)}
      ${runwayChip(a.runway, a.atis)}
      ${atisChip ? `<span class="ov-chip on" data-tip="${esc(a.atis.callsign)}">ATIS ${esc(a.atis.letter || "")}</span>` : ""}
      ${(a.atc || []).length ? `<span class="ov-chip on" data-tip="${esc(a.atc.map((c) => `${c.callsign} ${c.frequency} ${c.name || ""}`).join("\n"))}">ATC ${a.atc.length}</span>` : ""}
      ${a.covered_by ? `<span class="ov-by" data-tip="Covered now by ${esc(a.covered_by)}">${esc(a.covered_by)}</span>` : ""}
      <span class="ov-traffic" data-tip="Flights with a flight plan from/to this aerodrome: ↑ departures, ↓ arrivals, ✎ prefiled">↑${t.departures ?? 0} ↓${t.arrivals ?? 0}${t.prefiles ? ` ✎${t.prefiles}` : ""}</span>
      <span class="ov-obs">${obs}</span>
      <span class="ov-more">${open ? "▾" : "▸"} TAF</span>
    </div>
    <div class="wx ov-metar">${colorize(a.metar)}</div>
    ${open ? `<div class="wx ov-taf">${a.taf ? wxLines("taf", a.taf) : colorize(null)}</div>` : ""}
    ${a.lvp && a.lvp.state ? `<div class="ov-lvp-why${a.lvp.state === "CANCELLED" ? " ok" : ""}">${(a.lvp.reasons || []).map(esc).join(" · ")}</div>` : ""}
  </div>`;
}

// --- 3. NOTAM -------------------------------------------------------------------------------------------------
function notamValid(n) {
  if (n.perm) return "PERM";
  if (!n.end) return "until ?";
  return `until ${dhm(n.end)}${n.est ? " EST" : ""}`;
}
function notamPanel(d) {
  // po błędzie serwera NOTAM nie piszemy "brak": nie wiemy, czy ich nie ma (komunikat błędu jest nad listą)
  if (!d.notams.length) return d.notam_error ? "" : `<div class="hint">No NOTAMs in force now for the aerodromes shown.</div>`;
  return d.notams.map((n) => `<div class="ov-nt" title="${esc(n.raw || "")}">
    <div class="ov-nt-head"><b class="ic">${esc(n.icao)}</b><span class="mono id">${esc(n.id || "")}</span>
      <span class="valid">${esc(notamValid(n))}</span>
      ${n.schedule ? `<span class="hint">D) ${esc(n.schedule)}</span>` : ""}</div>
    <div class="ov-nt-txt">${esc(n.text)}</div></div>`).join("");
}

// --- 4. ECFMP / vIFF ------------------------------------------------------------------------------------------
const STATE_TXT = { active: "in force", notified: "notified", finished: "finished" };
function flowPanel(d) {
  const f = d.flow || {};
  const ms = (f.measures || []).map((m) => `<div class="ov-fm ${esc(m.state)}">
    <div class="ov-fm-head"><b class="mono">${esc(m.ident)}</b>
      <span class="ov-chip ${m.state === "active" ? "on" : "warn"}">${esc(STATE_TXT[m.state] || m.state)}</span>
      <span class="ov-fm-val">${esc(m.type_label)}${m.value_text ? ` · ${esc(m.value_text)}` : ""}</span>
      <span class="ov-fm-time mono">${hm(m.start)}–${hm(m.end)}</span></div>
    <div class="ov-fm-why">${esc(m.reason || "")}${m.firs.length ? ` · FIR: ${esc(m.firs.join(", "))}` : ""}</div>
    <div class="ov-fm-flt">
      ${m.adep.length ? `<span>departing <b>${esc(m.adep.join(", "))}</b></span>` : ""}
      ${m.ades.length ? `<span>arriving <b>${esc(m.ades.join(", "))}</b></span>` : ""}
      ${m.waypoints.length ? `<span>via <b>${esc(m.waypoints.join(", "))}</b></span>` : ""}
      ${m.levels.length ? `<span>${esc(m.levels.join(", "))}</span>` : ""}</div></div>`).join("");
  const rs = (f.restrictions || []).map((r) => `<tr class="${r.active ? "on" : ""}" title="${esc(r.label || "")}${r.reason ? ` · reason: ${esc(r.reason)}` : ""}">
    <td class="mono">${esc(r.tv)}</td><td>${esc((r.type || "").replace(/^ENR-/, ""))}</td>
    <td class="num">${n0(r.value)}</td><td class="num mono">${esc(r.start || "")}–${esc(r.end || "")}</td></tr>`).join("");
  // "brak restrykcji" tylko wtedy, gdy źródło odpowiedziało; po awarii zostaje sam komunikat błędu
  return `<div class="ov-sub">Flow measures · FIR EPWW</div>
    ${f.error ? `<div class="error ov-err">${esc(f.error)}</div>` : ""}
    ${ms || (f.source ? `<div class="hint">No flow measures for FIR EPWW and Polish aerodromes.</div>` : "")}
    <div class="ov-sub">EP sector regulations</div>
    ${f.viff_error ? `<div class="error ov-err">${esc(f.viff_error)}</div>` : ""}
    ${rs ? `<table class="data ov-tab"><thead><tr><th>Sector</th><th>Type</th><th>Value</th><th>Hours</th></tr></thead>
      <tbody>${rs}</tbody></table><div class="hint">ENTRIES = entry limit per hour, OCCUPANCY = occupancy limit (hover: sector description).
      Highlighted = in force now.</div>`
      : f.viff_error ? "" : `<div class="hint">No restrictions on EP sectors.</div>`}`;
}

// --- 5. Airport Monitor vIFF ----------------------------------------------------------------------------------
const loadCls = (n, cap) => {
  if (n === null || n === undefined || !cap) return "";
  const r = n / cap;
  return r > 1 ? "over" : r >= 0.9 ? "near" : "ok";
};
function monitorPanel(d) {
  const rows = d.aerodromes.map((a) => {
    const m = a.monitor || {};
    const now = m.now || {}, nxt = m.next || {};
    const regs = m.regulated || [];
    // lista lotów w zwykłym dymku przeglądarki (title): dymek data-tip ucinała dolna krawędź przewijanego panelu
    const tip = regs.length
      ? regs.map((f) => `${f.callsign} ${f.role} ${f.departure}→${f.arrival} CTOT ${f.ctot || "–"}${f.delay ? ` (+${f.delay} min)` : ""} ${f.regulation || ""}`).join("\n")
      : "No flights with CTOT";
    const t = a.traffic || {};
    return `<tr><td class="ic">${esc(a.icao)}</td>
      <td class="num ${loadCls(now.entries, now.cap)}">${n0(now.entries)}</td>
      <td class="num ${loadCls(nxt.entries, nxt.cap)}">${n0(nxt.entries)}</td>
      <td class="num">${n0(m.rate ?? now.cap)}</td>
      <td>${m.cdm ? `<span class="ov-chip on" title="Aerodrome with A-CDM (TOBT/TSAT/TTOT)">CDM</span>` : ""}</td>
      <td class="num tip" title="${esc(tip)}">${regs.length || "–"}</td>
      <td class="num ${m.avg_delay >= 10 ? "near" : ""}">${m.avg_delay ? "+" + m.avg_delay : "–"}</td>
      <td class="num">${t.departures ?? 0}/${t.arrivals ?? 0}</td></tr>`;
  }).join("");
  // vIFF liczy przepustowość lotniska dla przylotów (Base Rate = Default Arrival Rate w dokumentacji vIFF),
  // a godzinowe entriesCount z /etfms/airports to przyloty w tej godzinie
  return `<table class="data ov-tab ov-mon-tab"><thead>
      <tr><th rowspan="2">AD</th><th colspan="2">Arrivals</th><th rowspan="2" title="Aerodrome capacity (arrivals/h)">Cap.</th>
        <th rowspan="2">A-CDM</th><th colspan="2">Flights with CTOT</th><th rowspan="2" title="Flights with a flight plan: departures/arrivals">DEP/ARR</th></tr>
      <tr><th title="Current UTC hour">now</th><th>+1 h</th><th title="Number of flights with CTOT (hover: list)">no.</th><th title="Average ATFM delay (CTOT − ETOT)">delay</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="hint">Arrivals planned in the hour vs aerodrome capacity (green &lt; 90&nbsp;%, orange 90–100&nbsp;%, red above).</div>`;
}

// --- stanowisko wspólne z HOME (czyste funkcje, testy w Node) ---------------------------------------------------
// Wybór stanowiska (choiceGet: z HOME albo z tego PRZEGLĄDU, w pamięci tego okna) a filtr PRZEGLĄDU. isFilter(cs):
// stanowisko jest na liście jako filtr (ACC / APP); wieża zapisana w HOME nie jest filtrem, jak wybór TWR tutaj.
// Filtr po wczytaniu listy stanowisk: wybór, jeśli jest filtrem, inaczej cały FIR. Bez listy zawsze cały FIR: inaczej
// filtra nie byłoby widać w polu, a wieża z HOME stałaby się filtrem.
export const listPosition = (seen, isFilter) => (seen && isFilter(seen) ? seen : "");
// ponowne pokazanie otwartego PRZEGLĄDU. state: {seen, position, loaded}: wybór, jaki PRZEGLĄD ostatnio widział, bieżący
// filtr i czy lista stanowisk już jest. Zmienia filtr tylko nowy wybór (z HOME): ten sam co ostatnio zostawia filtr
// i zaznaczenia checklisty; przed wczytaniem listy filtr ustawi loadPositions (z `seen`).
export function syncPosition({ seen = "", position = "", loaded = false } = {}, shared = "", isFilter = () => false) {
  if (shared === seen) return { seen, position };
  if (!loaded) return { seen: shared, position };
  return { seen: shared, position: !shared || isFilter(shared) ? shared : position };
}

// --- MINE / ALL (czyste funkcje, testy w Node) -------------------------------------------------------------------
// Zakres listy lotnisk: "mine" (domyślny) albo "all"; inna wartość (stary zapis, brak localStorage) = "mine".
export const scopeOf = (v) => (v === "all" ? "all" : "mine");
// Przełącznik ma sens tylko przy stanowisku ACC / APP (wieża przeskakuje do lotniska, bez stanowiska cały FIR).
export const hasScope = (pos) => Boolean(pos && (pos.kind === "ACC" || pos.kind === "APP"));
// Dane widoku w zakresie: MINE bez lotnisk, które przed wybranym stanowiskiem obsługuje teraz ktoś inny (covered_by),
// także bez ich NOTAM-ów i wierszy Airport Monitor; hidden = ukryte lotniska z tym, kto je obsługuje. ALL bez zmian.
export function scoped(d, scope) {
  const hidden = scopeOf(scope) === "mine" ? (d.aerodromes || []).filter((a) => a.covered_by) : [];
  const out = new Set(hidden.map((a) => a.icao));
  const keep = (icao) => !out.has(icao);
  return { ...d, aerodromes: (d.aerodromes || []).filter((a) => keep(a.icao)), notams: (d.notams || []).filter((n) => keep(n.icao)),
    airports: (d.airports || []).filter(keep), hidden: hidden.map((a) => ({ icao: a.icao, by: a.covered_by })) };
}
// "3 hidden" przy przełączniku; dymek: lotnisko i kto je obsługuje
export const hiddenNote = (hidden) => ({
  text: hidden.length ? `${hidden.length} hidden` : "",
  tip: hidden.map((x) => `${x.icao}: ${x.by}`).join("\n"),
});

// --- widok -----------------------------------------------------------------------------------------------------
export function mountOverview(el, { onGoto } = {}) {
  el.innerHTML = `<div class="ov">
    <div class="toolbar ov-bar">
      <label class="sc">Position
        <select class="field ov-pos"><option value="">All aerodromes of FIR EPWW</option></select></label>
      <span class="ov-scope" hidden><button type="button" data-scope="mine" title="Only aerodromes not covered now by other controllers">MINE</button><button type="button" data-scope="all" title="All aerodromes of the position">ALL</button></span>
      <span class="hint ov-hidden"></span>
      <span class="hint ov-pos-note"></span>
      <span style="flex:1"></span>
      <span class="error ov-net"></span>
      <span class="hint ov-upd"></span>
    </div>
    <div class="ov-grid">
      <div class="ov-col">
        <div class="card ov-tl"><h3>Transition level</h3><div class="scroll ov-tl-body"><span class="hint">Loading…</span></div></div>
        <div class="card grow ov-chk"><h3>Position opening checklist</h3><div class="scroll ov-chk-body"></div></div>
      </div>
      <div class="ov-col">
        <div class="card grow ov-wx"><h3>METAR · TAF · LVP<span class="ov-h-note"></span></h3><div class="scroll ov-wx-body"><span class="hint">Loading…</span></div></div>
        <div class="card part ov-mon"><h3>Airport monitor</h3><div class="scroll ov-mon-body"></div></div>
      </div>
      <div class="ov-col">
        <div class="card grow ov-notam"><h3>NOTAMs in force now<span class="ov-h-note ov-nt-n"></span></h3><div class="scroll ov-notam-body"><span class="hint">Loading…</span></div></div>
        <div class="card grow ov-flow"><h3>Flow restrictions</h3><div class="scroll ov-flow-body"></div></div>
      </div>
    </div></div>`;
  const $ = (s) => el.querySelector(s);
  let seen = choiceGet(POS_KEY);  // wybór stanowiska (HOME albo tutaj), jaki PRZEGLĄD ostatnio widział
  let position = "";             // filtr: dopiero z listą stanowisk (listPosition), bez niej cały FIR
  let open = new Set();          // lotniska kliknięte: TAF w stanie odwrotnym do domyślnego (rozwinięty / zwinięty)
  // MINE / ALL, zapamiętane w tej przeglądarce
  let scope = scopeOf(lsGet(SCOPE_KEY));
  let timer = null, chk = null, destroyed = false, last = null, posLoaded = false;

  // lista stanowisk do filtra (ACC / APP / TWR); bez niej zostaje sam widok całego FIR-u
  const loadPositions = async () => {
    let data;
    try { data = await api("/api/overview/positions"); } catch (e) { $(".ov-pos-note").textContent = e.message; return; }
    if (destroyed || posLoaded) return;
    posLoaded = true;
    const sel = $(".ov-pos");
    data.groups.forEach((g) => {
      if (!g.positions.length) return;
      const og = document.createElement("optgroup");
      og.label = g.label;
      og.innerHTML = g.positions.map((p) => `<option value="${esc(p.callsign)}" ${p.goto ? `data-goto="${esc(p.goto)}"` : ""}>${esc(p.callsign)}${p.goto
        ? ` → INFO ${esc(p.goto)}` : ` (${p.airports.length} ${adWord(p.airports.length)})`}</option>`).join("");
      sel.append(og);
    });
    position = listPosition(seen, listed);
    sel.value = position;
  };
  // stanowisko z listy jako filtr: ACC / APP; wieża zapisana w HOME (ten sam klucz) nie jest filtrem, jak wybór TWR tutaj
  const listed = (cs) => {
    const opt = cs && $(".ov-pos").querySelector(`option[value="${CSS.escape(cs)}"]`);
    return Boolean(opt && !opt.dataset.goto);
  };

  const drawChecklist = (data) => {
    const body = $(".ov-chk-body");
    if (!position || data?.position?.goto) {
      body.innerHTML = `<div class="hint">Select a position (ACC or APP) at the top to show the opening checklist
        and only the aerodromes of that position. Selecting a tower (TWR) goes straight to the aerodrome INFO page.</div>`;
      return;
    }
    if (chk && chk.position === position) return;   // ta sama checklista: nie przerysowujemy (zaznaczenia zostają)
    body.innerHTML = `<span class="hint">Loading checklist…</span>`;
    const want = position;
    api("/api/checklists").then((d) => {
      if (destroyed || want !== position) return;   // w międzyczasie wybrano inne stanowisko
      const item = d.checklists.find((c) => c.id === (d.aerodrome || "open-position"));
      if (!item) { body.innerHTML = `<div class="hint">No checklist.</div>`; return; }
      body.innerHTML = `<div class="ov-chk-pos">${esc(position)}</div><div class="checklist"></div>`;
      renderChecklist(body.querySelector(".checklist"), item, CHK_KEY);
      chk = { position };
    }).catch((e) => { if (!destroyed && want === position) body.innerHTML = `<div class="error">${esc(e.message)}</div>`; });
  };

  const draw = (raw) => {
    const pos = raw.position;
    const sw = hasScope(pos);
    const d = scoped(raw, sw ? scope : "all");
    const note = hiddenNote(d.hidden);
    $(".ov-scope").hidden = !sw;
    el.querySelectorAll(".ov-scope button").forEach((b) => b.classList.toggle("on", b.dataset.scope === scope));
    const hid = $(".ov-hidden");
    hid.textContent = sw ? note.text : "";
    if (sw && note.tip) hid.dataset.tip = note.tip; else hid.removeAttribute("data-tip");
    $(".ov-pos-note").innerHTML = pos
      ? `${esc(pos.name || "")}${pos.frequency ? ` · ${esc(pos.frequency)}` : ""} · aerodromes: <b>${d.airports.map(esc).join(", ")}</b>`
      : `all controlled aerodromes of FIR EPWW (${d.airports.length})`;
    $(".ov-net").textContent = [d.network_error, d.wx_error].filter(Boolean).join(" · ");
    $(".ov-upd").textContent = "Updated " + new Date().toISOString().slice(11, 16) + "Z";
    $(".ov-tl-body").innerHTML = tlPanel(d);
    // z filtrem (mało lotnisk) TAF od razu widoczny, bez filtra dopiero po kliknięciu wiersza;
    // kliknięcie odwraca stan domyślny, więc przy rozwiniętych TAF-ach zwija TAF danego lotniska
    const all = Boolean(position) && d.aerodromes.length <= 6;
    $(".ov-h-note").textContent = all ? "TAF expanded · click = collapse" : "click an aerodrome = TAF";
    $(".ov-wx-body").innerHTML = (d.wx_error ? `<div class="error ov-err">${esc(d.wx_error)}</div>` : "")
      + d.aerodromes.map((a) => wxRow(a, all !== open.has(a.icao))).join("");
    $(".ov-nt-n").textContent = d.notam_error && !d.notams.length ? "–" : `${d.notams.length}`;   // "0" po awarii by kłamało
    $(".ov-notam-body").innerHTML = (d.notam_error ? `<div class="error ov-err">${esc(d.notam_error)}</div>` : "")
      + notamPanel(d);
    $(".ov-flow-body").innerHTML = flowPanel(d);
    $(".ov-mon-body").innerHTML = (d.monitor_error ? `<div class="error ov-err">${esc(d.monitor_error)}</div>` : "")
      + monitorPanel(d);
    drawChecklist(d);
  };

  const load = async () => {
    const want = position;
    let d;
    try {
      d = await api("/api/overview" + (want ? "?position=" + encodeURIComponent(want) : ""));
    } catch (e) {
      if (destroyed || want !== position) return;
      // komunikat w każdym panelu: pusty panel (albo dane sprzed awarii) wyglądałby jak "brak restrykcji"
      const msg = `<div class="error">${esc(e.message)}</div>`;
      [".ov-wx-body", ".ov-tl-body", ".ov-notam-body", ".ov-flow-body", ".ov-mon-body"].forEach((s) => { $(s).innerHTML = msg; });
      return;
    }
    if (destroyed || want !== position) return;
    last = d;
    draw(d);
  };

  $(".ov-pos").addEventListener("change", (e) => {
    const goto = e.target.selectedOptions[0]?.dataset.goto;
    if (goto) {                     // TWR: od razu PRZEGLĄD lotniska, filtr zostaje jak był
      e.target.value = position;
      onGoto?.(goto);
      return;
    }
    position = e.target.value;
    seen = position;
    choiceSet(POS_KEY, position);
    open = new Set();
    chk = null;
    load();
  });
  // MINE / ALL: tylko inny widok tych samych danych (bez nowego zapytania), wybór zapamiętany w przeglądarce
  $(".ov-scope").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-scope]");
    if (!b || b.dataset.scope === scope) return;
    scope = scopeOf(b.dataset.scope);
    lsSet(SCOPE_KEY, scope);
    if (last) draw(last);
  });
  // kliknięcie wiersza lotniska rozwija / zwija TAF
  $(".ov-wx-body").addEventListener("click", (e) => {
    const row = e.target.closest(".ov-aero");
    if (!row) return;
    const icao = row.dataset.icao;
    if (open.has(icao)) open.delete(icao); else open.add(icao);
    if (last) draw(last);           // sam TAF: przerysowujemy z danych, które już mamy
  });
  // serwer wrócił: lista stanowisk, jeśli się wtedy nie wczytała, i dane, jeśli któryś panel pokazuje błąd
  // (.ov-net ma klasę error także pusty, więc liczą się tylko niepuste komunikaty)
  const online = () => {
    if (!posLoaded) loadPositions().then(load);
    else if (el.querySelector(".ov .error:not(:empty)")) load();
  };
  window.addEventListener(ONLINE_EVENT, online);

  loadPositions().then(load);
  timer = setInterval(load, REFRESH_MS);
  return {
    // ponowne pokazanie otwartego PRZEGLĄDU: stanowisko wybrane w międzyczasie w HOME (tego okna) zamiast starego
    sync() {
      const next = syncPosition({ seen, position, loaded: posLoaded }, choiceGet(POS_KEY), listed);
      seen = next.seen;
      if (next.position === position) return;
      position = next.position;
      $(".ov-pos").value = position;
      open = new Set();
      chk = null;
      load();
    },
    destroy() {
      destroyed = true;
      clearInterval(timer);
      window.removeEventListener(ONLINE_EVENT, online);
    },
  };
}
