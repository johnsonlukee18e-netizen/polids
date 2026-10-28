import { api, esc, h, ONLINE_EVENT } from "./api.js";

// OTHER › SQUAWK (do 0.12.6 osobna zakładka menu): jedna lista kodów SSR posortowana po kodzie: pule (EPWW, CCAMS,
// NATO, EUR-E; importer backend/app/importers/squawk_cal.py → data/seed/squawk.json, GET /api/squawk) i kody specjalne
// (sam tytuł). Jedno pole na górze: pełny kod (4 cyfry 0–7) zaznacza kod specjalny i pule, w których leży, i przewija
// listę do pierwszej, tekst filtruje listę (każde słowo musi pasować).
// Adres składa OTHER: "#other/squawk" albo "#other/squawk/7700" (szukany kod); każdy wpisany pełny kod to krok do
// cofnięcia (onCode). Stare "#squawk" i "#squawk/<kod>" przekierowuje app.js.

const EMERGENCY = new Set(["7500", "7600", "7700"]);
// po powrocie na zakładkę dane z serwera najwyżej minutowe (nowy import bez F5)
const RELOAD_MS = 60 * 1000;

// grupy pul (kategoria z importera): znacznik w kolumnie Area, opis w dymku; kolejność = kolejność pul tego samego zakresu
export const CATEGORIES = [
  { id: "epww", tag: "EPWW", line: "EPWW – pools from which FIR EPWW assigns codes itself." },
  { id: "ccams", tag: "CCAMS", line: "CCAMS – codes assigned centrally by CCAMS." },
  { id: "nato", tag: "NATO", line: "NATO – NATO military pools." },
  { id: "eur-e", tag: "EUR-E", line: "EUR-E – allocations of the other EUR-E members and retention." },
];
const CAT = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));
export const catTag = (id) => CAT[id]?.tag || String(id || "?").toUpperCase();
const catIndex = (id) => { const i = CATEGORIES.findIndex((c) => c.id === id); return i < 0 ? CATEGORIES.length : i; };

// --- kody SSR: cztery cyfry ósemkowe, zawsze napis ("0100", nie 100)
export const isCode = (code) => typeof code === "string" && /^[0-7]{4}$/.test(code);
export const codeValue = (code) => parseInt(code, 8);
// liczba kodów w puli od–do (włącznie), ósemkowo: 0100–0177 = 64
export const rangeSize = (from, to) => codeValue(to) - codeValue(from) + 1;
export const inRange = (code, pool) => codeValue(pool.from) <= codeValue(code) && codeValue(code) <= codeValue(pool.to || pool.from);

// same cyfry → {code, ok, error}; error = podpowiedź do pokazania (null: nic złego, najwyżej jeszcze niepełny)
export function checkCode(text) {
  const code = String(text ?? "").trim();
  if (!code) return { code, ok: false, error: null };
  if (/[89]/.test(code)) return { code, ok: false, error: "8 and 9 do not occur in SSR codes: digits 0–7 (octal)." };
  if (!/^\d+$/.test(code)) return { code, ok: false, error: "An SSR code has digits 0–7 only." };
  if (code.length > 4) return { code, ok: false, error: "An SSR code has 4 digits." };
  return { code, ok: code.length === 4, error: null };
}

// tekst z pola wyszukiwania → {code, error, more, words}. Same cyfry to kod: pełny (code), niepełny (more = ile cyfr
// brakuje) albo zły (error); lista się wtedy nie filtruje. Inaczej słowa filtra (wielkie litery), a pierwszy pełny
// kod wśród nich tylko zaznacza pule (np. "4131 ccams": pule CCAMS, zaznaczone te z 4131).
export function parseQuery(text) {
  const q = String(text ?? "").trim();
  if (/^\d+$/.test(q)) {
    const c = checkCode(q);
    return { code: c.ok ? c.code : "", error: c.error, more: c.ok || c.error ? 0 : 4 - q.length, words: [] };
  }
  const words = q.toUpperCase().split(/\s+/).filter(Boolean);
  const code = words.find(isCode) || "";
  return { code, error: null, more: 0, words: code ? words.filter((w) => w !== code) : words };
}

// A/R: A = przydział (kody przydziela JEDNOSTKA), R = retencja (kod nadany przez PRZYDZIELA zostaje)
export function arInfo(ar) {
  if (ar === "A") return { text: "allocation", tip: "A – allocation: codes from this pool are assigned by the UNIT (Unit column) in the PA area." };
  if (ar === "R") {
    return { text: "retention", tip: "R – retention: a code assigned by the unit in the ASSIGNED BY column (Unit which assigned) "
      + "is kept unchanged when the flight enters the area of the UNIT (Unit column)." };
  }
  return { text: ar || "–", tip: "" };
}
export const civMil = (v) => (v === "CIV_MIL" ? "CIV/MIL" : v || "");
// lista Unit równa całemu obszarowi PA (areas = meta.participating_areas) → "whole EUR-E"
export function wholeArea(text, pa, areas) {
  const members = areas?.[pa], t = String(text || "").split(/\s+/).filter(Boolean);
  return !!members?.length && t.length === members.length && members.every((m) => t.includes(m));
}

// znaczenie kodu: kody specjalne o tym numerze i pule wszystkich grup, w których leży (data jak z /api/squawk)
export function lookup(data, code) {
  const pools = data?.pools || [], special = data?.special || [];
  return { code, special: special.filter((s) => s.code === code), pools: pools.filter((p) => inRange(code, p)) };
}

// 1 code, 2 codes, 0 codes
export const plural = (n, one, many) => (n === 1 ? one : many);
const nPools = (n) => `${n} ${plural(n, "pool", "pools")}`;
export const rangeText = (p) => (p.to && p.to !== p.from ? `${p.from}–${p.to}` : p.from);
const countOf = (p) => p.count ?? rangeSize(p.from, p.to || p.from);

// lista prefiksów w odpowiedzi: cały obszar PA, do 4 prefiksów wprost, dłuższa jako liczba (pełna lista w wierszu)
export function unitsBrief(text, pa, areas) {
  const t = String(text || "").split(/\s+/).filter(Boolean);
  if (wholeArea(text, pa, areas)) return `whole ${pa}`;
  return t.length > 4 ? `${t.length} units` : t.join(" ");
}
// co odróżnia pulę od innych pul tej samej grupy i zakresu: w EUR-E przydział = jednostka, retencja = kto nadał kod
// (full: też obszar retencji, gdy kilka pul ma ten sam opis); MIL, CIV/MIL i APP poza NATO (tam wszystkie MIL)
export function poolBrief(p, areas, full = false) {
  const parts = [];
  if (p.category === "eur-e") {
    if (p.ar === "R") {
      parts.push(`retention${full ? ` in ${unitsBrief(p.unit, p.pa, areas) || "–"}` : ""} (assigned by ${unitsBrief(p.assigned_by) || "–"})`);
    } else parts.push(unitsBrief(p.unit, p.pa, areas) || "–");
  }
  if (p.category !== "nato" && p.civ_mil && p.civ_mil !== "CIV") parts.push(civMil(p.civ_mil));
  if (p.app === "APP") parts.push("APP");
  return parts.join(" ");
}
// pule kodu w odpowiedzi (wynik lookup) w kolejności listy; pule tej samej grupy i zakresu razem:
// "EUR-E 0020–0037: LB, LH, LU" (areas = meta.participating_areas); "" = w żadnej
export function hitsText(r, areas) {
  if (!r.pools.length) return "";
  const pools = [...r.pools].sort((a, b) => codeValue(a.from) - codeValue(b.from) || catIndex(a.category) - catIndex(b.category)
    || codeValue(a.to || a.from) - codeValue(b.to || b.from));
  const groups = new Map();
  pools.forEach((p) => { const k = `${catTag(p.category)} ${rangeText(p)}`; groups.set(k, [...(groups.get(k) || []), p]); });
  const parts = [...groups].map(([k, ps]) => {
    let briefs = ps.map((p) => poolBrief(p, areas));
    if (new Set(briefs).size < briefs.length) briefs = ps.map((p) => poolBrief(p, areas, true));
    briefs = briefs.filter(Boolean);
    return briefs.length ? `${k}: ${briefs.join(", ")}` : k;
  });
  return `${r.special.length ? "Also in" : "In"} ${nPools(r.pools.length)}: ${parts.join(" · ")}`;
}
// czego kod nie ma (wynik lookup): "" = leży w puli
export function missText(r) {
  if (r.pools.length) return "";
  return r.special.length ? "Not in any pool." : "– not a special code and not in any pool.";
}

// --- jedna lista: wiersze {kind: "special", s} i {kind: "pool", p} po kodzie; kod specjalny przed pulą od tego
// samego kodu (0001 przed 0001–0017), pule tego samego zakresu w kolejności grup (EPWW pierwsze)
export function listRows(data) {
  const rows = [...(data?.special || []).filter((s) => isCode(s?.code)).map((s) => ({ kind: "special", from: s.code, to: s.code, s })),
    ...(data?.pools || []).filter((p) => isCode(p?.from)).map((p) => ({ kind: "pool", from: p.from, to: p.to || p.from, p }))];
  const rank = (r) => (r.kind === "special" ? -1 : catIndex(r.p.category));
  return rows.sort((a, b) => codeValue(a.from) - codeValue(b.from) || rank(a) - rank(b) || codeValue(a.to) - codeValue(b.to));
}
// tekst wiersza do filtra (wielkie litery): zakres, grupa, pola puli; kod specjalny: kod, SPECIAL i tytuł
const poolHay = (p) => [`${p.from}-${p.to}`, catTag(p.category), p.pa, p.unit, civMil(p.civ_mil), p.app, p.assigned_by,
  p.ar, arInfo(p.ar).text, p.destination, p.via, p.protection, p.remarks, p.type, ...Object.values(p.raw || {})]
  .filter(Boolean).join(" ").toUpperCase();
export const rowHay = (r) => (r.kind === "special" ? `${r.s.code} SPECIAL ${r.s.label || ""}`.toUpperCase() : poolHay(r.p));
// słowo równe nazwie grupy (EPWW, CCAMS, NATO, EUR-E) = dokładnie ta grupa albo obszar PA (EUR-E: też pule EPWW),
// nie wzmianka w uwagach (np. "Protection ensured by CCAMS" przy pulach EUR-E); inne słowa: fragment tekstu wiersza
const GROUP_WORDS = new Set(CATEGORIES.map((c) => c.tag));
const inGroup = (r, w) => r.kind === "pool" && (catTag(r.p.category) === w || String(r.p.pa || "").toUpperCase() === w);
export function filterRows(rows, words = []) {
  if (!words.length) return rows;
  return rows.filter((r) => { const t = rowHay(r); return words.every((w) => (GROUP_WORDS.has(w) ? inGroup(r, w) : t.includes(w))); });
}
// wiersz zaznaczony dla szukanego kodu: ten kod specjalny albo pula, w której kod leży
export const rowHas = (r, code) => isCode(code) && (r.kind === "special" ? r.s.code === code : inRange(code, r.p));

// licznik nad listą: "207 pools · 7 special codes", po filtrze "5 of 207 pools · 0 of 7 special codes"
export function countText(shown, all) {
  const part = (kind, one, many) => {
    const n = shown.filter((r) => r.kind === kind).length, total = all.filter((r) => r.kind === kind).length;
    return `${n === total ? "" : `${n} of `}${total} ${plural(total, one, many)}`;
  };
  return `${part("pool", "pool", "pools")} · ${part("special", "special code", "special codes")}`;
}

// --- widok
// lista prefiksów ICAO z wyróżnionym EP (Polska)
const units = (text) => (text ? String(text).split(/\s+/).filter(Boolean)
  .map((t) => (t === "EP" ? `<span class="sq-ep">EP</span>` : esc(t))).join(" ") : "–");
const FIELDS = [["pa", "PA"], ["unit", "Unit"], ["civ_mil", "CIV/MIL"], ["app", "APP"], ["assigned_by", "Unit which assigned"],
  ["ar", "A/R"], ["destination", "Destination"], ["via", "Via"], ["protection", "Protection"], ["remarks", "Remarks"], ["type", "purpose"]];
const poolTip = (p) => [catTag(p.category), ...FIELDS.filter(([k]) => p[k]).map(([k, n]) => `${n}: ${p[k]}`),
  ...Object.entries(p.raw || {}).map(([k, v]) => `${k}: ${v}`)].join("\n");
const COLS = 10;

function poolRow(r, code, areas) {
  const p = r.p, ar = arInfo(p.ar);
  const notes = [p.type, p.remarks].filter(Boolean).join(" · ");
  return `<tr class="sq-pool${rowHas(r, code) ? " selected" : ""}" title="${esc(poolTip(p))}">
  <td class="sq-range">${esc(rangeText(p))}</td><td class="num">${countOf(p)}</td>
  <td><span class="tag sq-grp${p.category === "epww" ? " own" : ""}" title="${esc(CAT[p.category]?.line || "")}">${esc(catTag(p.category))}</span></td>
  <td class="sq-cm">${esc(civMil(p.civ_mil) || "–")}${p.app === "APP" ? ` <span class="tag sq-app">APP</span>` : ""}</td>
  <td><span class="sq-ar sq-ar-${p.ar === "R" ? "r" : "a"}" title="${esc(ar.tip)}">${esc(ar.text)}</span></td>
  <td class="sq-units">${wholeArea(p.unit, p.pa, areas) ? `<span class="sq-all" title="${esc(p.unit)}">whole ${esc(p.pa)}</span>` : units(p.unit)}</td>
  <td class="sq-units">${units(p.assigned_by)}</td>
  <td class="sq-units">${units(p.destination)}${p.via ? `<div class="sq-minor">via ${esc(p.via)}</div>` : ""}</td>
  <td class="sq-units">${units(p.protection)}</td>
  <td class="sq-minor">${esc(notes)}</td></tr>`;
}

// kod specjalny: sam kod i tytuł (kontrolerzy znają znaczenie)
const specialRow = (r, code) => `<tr class="sq-special${rowHas(r, code) ? " selected" : ""}">
  <td class="sq-range sq-scode${EMERGENCY.has(r.s.code) ? " emerg" : ""}">${esc(r.s.code)}</td><td></td>
  <td colspan="${COLS - 2}"><span class="sq-label">${esc(r.s.label || "")}</span></td></tr>`;

// activate(arg): nowy tekst pola albo null (pole zostaje). arg undefined = przycisk menu; arg równy addr (kod w adresie
// przy ostatnim wejściu albo wpisaniu) = Wstecz na wpis, w którym potem wpisano tekst filtra: tekst zostaje
export const textFromAddress = (arg, addr) => (arg === undefined || arg === addr ? null : String(arg));

export function answerHtml(data, text) {
  const q = parseQuery(text);
  if (q.error) return `<p class="sq-bad">${esc(q.error)}</p>`;
  if (q.more) return `<p class="hint">${q.more} more ${plural(q.more, "digit", "digits")}</p>`;
  if (!q.code) return "";
  if (!data) return `<p class="hint">Loading…</p>`;
  const r = lookup(data, q.code);
  const big = (c) => `<span class="sq-big${EMERGENCY.has(c) ? " emerg" : ""}">${esc(c)}</span>`;
  const lines = r.special.map((s) => `<p>${big(s.code)} <span class="sq-label">${esc(s.label || "")}</span></p>`);
  const pools = hitsText(r, data.meta?.participating_areas), miss = missText(r);
  if (pools) lines.push(`<p>${r.special.length ? "" : `${big(q.code)} `}<span class="sq-hit">${esc(pools)}</span></p>`);
  if (miss) lines.push(`<p class="hint">${r.special.length ? "" : `${big(q.code)} `}${esc(miss)}</p>`);
  return lines.join("");
}

// OTHER › SQUAWK w panelu podzakładki. start = kod (albo tekst) z adresu; onCode(kod) po wpisaniu pełnego kodu (OTHER
// zapisuje krok historii). destroy() przy przejściu do innej podzakładki: zdejmuje nasłuch ONLINE_EVENT, a spóźniona
// odpowiedź /api/squawk nic już nie rysuje (seq).
export function mountSquawk(pane, { start = "", onCode = () => {} } = {}) {
  const box = h(`<div class="pane sq-pane">
    <h2 class="title">SQUAWK – SSR codes FIR EPWW</h2>
    <div class="card sq-card">
      <div class="sq-top">
        <input class="field sq-q" type="text" autocomplete="off" spellcheck="false" placeholder="Code or text: 7700, EPWW, LR…"
          title="A code highlights its pools, text filters the list; EPWW, CCAMS, NATO or EUR-E shows that group"
          aria-label="Search SSR codes">
        <div class="sq-answer"></div>
        <span class="hint sq-count"></span>
      </div>
      <div class="sq-scroll">
        <table class="data sq-table"><thead><tr><th>Code</th><th class="num">Count</th><th>Area</th><th>CIV/MIL</th>
          <th title="${esc(`${arInfo("A").tip}\n${arInfo("R").tip}`)}">A/R</th><th>Unit</th><th>Assigned by</th>
          <th>Dest</th><th>Protection</th><th>Remarks</th></tr></thead>
          <tbody><tr><td colspan="${COLS}" class="hint">Loading…</td></tr></tbody></table>
      </div>
    </div>
  </div>`);
  pane.append(box);
  const input = box.querySelector(".sq-q");
  const answer = box.querySelector(".sq-answer");
  const count = box.querySelector(".sq-count");
  const scroller = box.querySelector(".sq-scroll");
  const body = box.querySelector(".sq-table tbody");
  // addr = kod w adresie (ostatni zapisany albo z adresu); wpisany tekst go nie zmienia
  let data = null, rows = [], loadedAt = 0, seq = 0, addr = "", dead = false;

  const drawList = (scroll) => {
    if (!data) return;
    const q = parseQuery(input.value);
    const list = filterRows(rows, q.words);
    count.textContent = rows.length ? countText(list, rows) : "";
    const areas = data.meta?.participating_areas;
    body.innerHTML = !rows.length ? `<tr><td colspan="${COLS}" class="hint sq-empty">No data.</td></tr>`
      : list.length ? list.map((r) => (r.kind === "special" ? specialRow(r, q.code) : poolRow(r, q.code, areas))).join("")
        : `<tr><td colspan="${COLS}" class="hint sq-empty">Nothing matches the filter.</td></tr>`;
    // nowy kod: pierwszy zaznaczony wiersz na środek listy; bez kodu lista od góry
    if (scroll) {
      const hit = body.querySelector("tr.selected");
      if (hit) hit.scrollIntoView({ block: "center" });
      else scroller.scrollTop = 0;
    }
  };
  const update = (scroll) => {
    const q = parseQuery(input.value);
    input.classList.toggle("bad", !!q.error);
    answer.innerHTML = answerHtml(data, input.value);
    drawList(scroll);
  };
  const load = async () => {
    const my = ++seq;
    try {
      const d = await api("/api/squawk");
      if (my !== seq) return;
      const first = !data;
      data = d;
      rows = listRows(d);
      loadedAt = Date.now();
      update(first);
    } catch (e) {
      if (my !== seq || data) return;
      body.innerHTML = `<tr><td colspan="${COLS}" class="error">${esc(e.message)}</td></tr>`;
      if (parseQuery(input.value).code) answer.innerHTML = `<p class="error">${esc(e.message)}</p>`;
    }
  };
  const online = () => { if (!data) load(); };

  input.addEventListener("input", () => {
    update(true);
    const q = parseQuery(input.value);
    // sam pełny kod = krok do cofnięcia; tekst, puste albo niepełne pole nie zmienia adresu
    if (q.code && !q.words.length) { addr = q.code; onCode(addr); }
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Escape" && input.value) { input.value = ""; input.dispatchEvent(new Event("input")); } });
  window.addEventListener(ONLINE_EVENT, online);
  if (start) { addr = String(start); input.value = addr; }
  update(false);
  load();
  input.focus();
  // "#other/squawk/7700": kod z adresu (← i Wstecz) trafia do pola tylko, gdy adres wskazuje inny kod niż ostatnio
  return {
    activate: (arg) => {
      if (dead) return;
      const text = textFromAddress(arg, addr);
      if (text !== null) { addr = text; input.value = text; update(true); }
      if (data && Date.now() - loadedAt > RELOAD_MS) load();
      input.focus();
    },
    focus: () => { if (!dead) input.focus(); },
    destroy: () => { dead = true; seq++; window.removeEventListener(ONLINE_EVENT, online); },
  };
}
