import { api, esc, h, ONLINE_EVENT, remember } from "../api.js";

// SQUAWK: pule kodów SSR z EUROCONTROL / ICAO EUR CAL (arkusz data/import/eurocontrol-icao-eur-cal-v4-13.xls,
// importer backend/app/importers/squawk_cal.py → data/seed/squawk.json, GET /api/squawk) i kody specjalne.
// Kategorie pul: EPWW (domyślny widok: FIR EPWW przydziela sam), CCAMS, NATO i EUR-E (wszystkie wpisy obszaru).
// Sprawdzanie kodu liczy przeglądarka z tych samych danych (bez zapytania na każdy wpisany kod) i pokazuje pule
// wszystkich kategorii. Adres: "#squawk" albo "#squawk/7700" (sprawdzany kod); każdy wpisany pełny kod to krok
// do cofnięcia (← i Wstecz).

const EMERGENCY = new Set(["7500", "7600", "7700"]);
const RELOAD_MS = 60 * 1000;   // po powrocie na zakładkę dane z serwera najwyżej minutowe (nowy import bez F5)

// widoki tabeli pul: id = kategoria puli z importera; EUR-E pokazuje wszystkie wiersze obszaru (także pule EPWW)
export const CATEGORIES = [
  { id: "epww", label: "EPWW", tag: "EPWW", line: "EPWW – pule, z których FIR EPWW sam przydziela kody (CAL, PA EUR-E, UNIT EP)." },
  { id: "ccams", label: "CCAMS", tag: "CCAMS", line: "CCAMS – kody przydzielane centralnie przez CCAMS (na VATSIM: wtyczka CCAMS); UNIT z EP." },
  { id: "nato", label: "NATO", tag: "NATO", line: "NATO – pule wojskowe NATO (UNIT z EP)." },
  { id: "eur-e", label: "EUR-E (wszystkie)", tag: "EUR-E",
    line: "EUR-E – wszystkie wpisy obszaru EUR-E (Polska, Litwa, Bułgaria, Węgry, Czechy, Rumunia, Mołdawia, Słowacja, "
      + "Ukraina, Kaliningrad, Białoruś): przydziały sąsiadów i retencja." },
];
export const DEFAULT_VIEW = "epww";
const CAT = Object.fromEntries(CATEGORIES.map((c) => [c.id, c]));
export const catTag = (id) => CAT[id]?.tag || String(id || "?").toUpperCase();

// --- kody SSR: cztery cyfry ósemkowe, zawsze napis ("0100", nie 100)
export const isCode = (code) => typeof code === "string" && /^[0-7]{4}$/.test(code);
export const codeValue = (code) => parseInt(code, 8);
// liczba kodów w puli od–do (włącznie), ósemkowo: 0100–0177 = 64
export const rangeSize = (from, to) => codeValue(to) - codeValue(from) + 1;
export const inRange = (code, pool) => codeValue(pool.from) <= codeValue(code) && codeValue(code) <= codeValue(pool.to || pool.from);

// tekst z pola → {code, ok, error}; error = podpowiedź do pokazania (null: nic złego, najwyżej jeszcze niepełny)
export function checkCode(text) {
  const code = String(text ?? "").trim();
  if (!code) return { code, ok: false, error: null };
  if (/[89]/.test(code)) return { code, ok: false, error: "8 i 9 nie występują w kodach SSR: cyfry 0–7 (system ósemkowy)." };
  if (!/^\d+$/.test(code)) return { code, ok: false, error: "Kod SSR to same cyfry 0–7." };
  if (code.length > 4) return { code, ok: false, error: "Kod SSR ma 4 cyfry." };
  return { code, ok: code.length === 4, error: null };
}

// --- kategorie i widoki
export const inView = (pool, view) => (view === "eur-e" ? pool.category === "eur-e" || pool.category === "epww" : pool.category === view);
// pule widoku po kodzie (w EUR-E pule EPWW między pulami sąsiadów)
export const viewPools = (pools, view) => (pools || []).filter((p) => inView(p, view))
  .sort((a, b) => codeValue(a.from) - codeValue(b.from) || codeValue(a.to) - codeValue(b.to));
export const viewCounts = (pools) => Object.fromEntries(CATEGORIES.map((c) => [c.id, viewPools(pools, c.id).length]));

// A/R z CAL: A = przydział (kody przydziela JEDNOSTKA), R = retencja (kod nadany przez PRZYDZIELA zostaje)
export function arInfo(ar) {
  if (ar === "A") return { text: "przydział", tip: "A – przydział: kody z tej puli przydziela JEDNOSTKA (kolumna Unit) w obszarze PA." };
  if (ar === "R") {
    return { text: "retencja", tip: "R – retencja: kod nadany przez jednostkę z kolumny PRZYDZIELA (Unit which assigned) "
      + "zostaje bez zmiany, gdy lot wlatuje do obszaru JEDNOSTKA (kolumna Unit)." };
  }
  return { text: ar || "–", tip: "" };
}
export const civMil = (v) => (v === "CIV_MIL" ? "CIV/MIL" : v || "");
// lista Unit równa całemu obszarowi PA z arkusza PAs (areas = meta.participating_areas) → w widoku "cały EUR-E"
export function wholeArea(text, pa, areas) {
  const members = areas?.[pa], t = String(text || "").split(/\s+/).filter(Boolean);
  return !!members?.length && t.length === members.length && members.every((m) => t.includes(m));
}

// znaczenie kodu: kody specjalne o tym numerze i pule wszystkich kategorii, w których leży (data jak z /api/squawk)
export function lookup(data, code) {
  const pools = data?.pools || [], special = data?.special || [];
  return { code, special: special.filter((s) => s.code === code), pools: pools.filter((p) => inRange(code, p)) };
}

// czego kod nie ma (wynik lookup): "" = leży w puli
export function missText(r) {
  if (r.pools.length) return "";
  return `${r.special.length ? "Nie leży" : "– nie jest kodem specjalnym i nie leży"} w żadnej puli z CAL (EPWW, CCAMS, NATO, EUR-E).`;
}

// filtr pul: każde słowo musi pasować; pełny kod (4 cyfry 0–7) = pule, w których leży
const hay = (p) => [`${p.from}-${p.to}`, catTag(p.category), p.pa, p.unit, civMil(p.civ_mil), p.app, p.assigned_by,
  p.ar, arInfo(p.ar).text, p.destination, p.via, p.protection, p.remarks, p.ver && `V${p.ver}`, p.type, ...(p.match || []),
  ...Object.values(p.raw || {})].filter(Boolean).join(" ").toUpperCase();
export function filterPools(pools, q = "") {
  const words = String(q).toUpperCase().split(/\s+/).filter(Boolean);
  if (!words.length) return pools;
  return pools.filter((p) => { const t = hay(p); return words.every((w) => (isCode(w) && inRange(w, p)) || t.includes(w)); });
}

// 1 kod, 2 kody, 5 kodów, 22 kody, 12 kodów
export function plural(n, one, few, many) {
  const d = n % 10, dd = n % 100;
  return n === 1 ? one : d >= 2 && d <= 4 && (dd < 12 || dd > 14) ? few : many;
}
const nCodes = (n) => `${n} ${plural(n, "kod", "kody", "kodów")}`;
const nPools = (n) => `${n} ${plural(n, "pula", "pule", "pul")}`;
export const rangeText = (p) => (p.to && p.to !== p.from ? `${p.from}–${p.to}` : p.from);
const countOf = (p) => p.count ?? rangeSize(p.from, p.to || p.from);

// --- widok
// lista prefiksów ICAO z wyróżnionym EP (Polska)
const units = (text) => (text ? String(text).split(/\s+/).filter(Boolean)
  .map((t) => (t === "EP" ? `<b class="sq-ep">EP</b>` : esc(t))).join(" ") : "–");
const FIELDS = [["pa", "PA"], ["unit", "Unit"], ["civ_mil", "CIV/MIL"], ["app", "APP"], ["assigned_by", "Unit which assigned"],
  ["ar", "A/R"], ["destination", "Destination"], ["via", "Via"], ["protection", "Protection"], ["remarks", "Remarks"], ["ver", "Ver"],
  ["type", "przeznaczenie"]];
const poolTip = (p) => [`${catTag(p.category)} · arkusz ${p.sheet ?? "?"}, wiersz ${p.row ?? "?"}`,
  ...FIELDS.filter(([k]) => p[k]).map(([k, n]) => `${n}: ${p[k]}`),
  ...Object.entries(p.raw || {}).map(([k, v]) => `${k}: ${v}`)].join("\n");
const COLS = 10;

function poolRow(p, code, view, areas) {
  const ar = arInfo(p.ar);
  const own = view === "eur-e" && p.category === "epww" ? ` <span class="tag sq-cat-tag">EPWW</span>` : "";
  const notes = [p.type, p.remarks].filter(Boolean).join(" · ");
  return `<tr class="${code && inRange(code, p) ? "selected" : ""}" title="${esc(poolTip(p))}">
  <td class="sq-range">${esc(rangeText(p))}</td><td class="num">${countOf(p)}</td>
  <td class="sq-cm">${esc(civMil(p.civ_mil) || "–")}${p.app === "APP" ? ` <span class="tag sq-app">APP</span>` : ""}</td>
  <td><span class="sq-ar sq-ar-${p.ar === "R" ? "r" : "a"}" title="${esc(ar.tip)}">${esc(ar.text)}</span></td>
  <td class="sq-units">${wholeArea(p.unit, p.pa, areas) ? `<span class="sq-all" title="${esc(p.unit)}">cały ${esc(p.pa)}</span>` : units(p.unit)}${own}</td>
  <td class="sq-units">${units(p.assigned_by)}</td>
  <td class="sq-units">${units(p.destination)}${p.via ? `<div class="sq-minor">przez ${esc(p.via)}</div>` : ""}</td>
  <td class="sq-units">${units(p.protection)}</td>
  <td class="sq-minor">${esc(notes)}</td><td class="sq-ver">${esc(p.ver || "")}</td></tr>`;
}

const specialRow = (s, code) => `<tr class="${s.code === code ? "selected" : ""}">
  <td class="sq-scode${EMERGENCY.has(s.code) ? " emerg" : ""}">${esc(s.code)}</td>
  <td><b class="sq-label">${esc(s.label || "")}</b> <span class="sq-meaning">${esc(s.meaning || "")}</span>
    ${s.note ? `<div class="sq-note">${esc(s.note)}</div>` : ""}
    ${s.excluded?.length ? `<div class="sq-excl"><span class="hint">bez kodu ${esc(s.code)}:</span> ${s.excluded.map((x) => `<span class="tag">${esc(x)}</span>`).join(" ")}</div>` : ""}
    <div class="hint sq-src">źródło: ${esc(s.source || "–")}</div></td></tr>`;

// jedna pula w odpowiedzi: kategoria (przycisk: pokaż w tabeli), zakres, liczba, CIV/MIL, przydział albo retencja, cel
export function hitText(p, areas) {
  const parts = [`${rangeText(p)} (${nCodes(countOf(p))})`];
  const unit = wholeArea(p.unit, p.pa, areas) ? `cały ${p.pa}` : p.unit;
  if (p.civ_mil) parts.push(civMil(p.civ_mil) + (p.app === "APP" ? " APP" : ""));
  if (p.ar === "R") parts.push(`retencja (${unit || "–"}), przydziela ${p.assigned_by || "–"}`);
  else if (p.ar === "A") parts.push(`przydział: ${unit || "–"}`);
  else if (unit) parts.push(unit);
  if (p.destination) parts.push(`cel ${p.destination}`);
  if (p.protection) parts.push(`ochrona ${p.protection}`);
  if (p.type) parts.push(p.type);
  if (p.remarks) parts.push(p.remarks);
  return parts.join(" · ");
}

function answerHtml(data, text, view) {
  const { code, ok, error } = checkCode(text);
  if (error) return `<p class="sq-bad">${esc(error)}</p>`;
  if (!ok) return `<p class="hint">${code ? `jeszcze ${4 - code.length} ${plural(4 - code.length, "cyfra", "cyfry", "cyfr")}` : "Wpisz 4 cyfry kodu SSR (0–7), np. 7700."}</p>`;
  if (!data) return `<p class="hint">Ładowanie…</p>`;
  const r = lookup(data, code);
  const lines = r.special.map((s) => `<p><b class="sq-big${EMERGENCY.has(s.code) ? " emerg" : ""}">${esc(s.code)}</b>
    <b class="sq-label">${esc(s.label || "")}</b> – ${esc(s.meaning || "")}</p>`);
  if (r.pools.length) {
    const shown = r.pools.some((p) => inView(p, view));
    lines.push(`<p><b class="sq-big">${esc(code)}</b> ${nPools(r.pools.length)} w CAL${shown ? "" : " <span class=\"hint\">(kliknij kategorię, żeby pokazać w tabeli)</span>"}:</p>`);
    lines.push(`<ul class="sq-hits">${r.pools.map((p) => `<li><button type="button" class="sq-cat${inView(p, view) ? " on" : ""}"
      data-view="${esc(p.category)}" title="${esc(CAT[p.category]?.line || "")}">${esc(catTag(p.category))}</button>
      <span class="sq-hit">${esc(hitText(p, data.meta?.participating_areas))}</span></li>`).join("")}</ul>`);
  }
  const miss = missText(r);
  if (miss) lines.push(`<p class="hint">${r.special.length ? "" : `<b class="sq-big">${esc(code)}</b> `}${esc(miss)}</p>`);
  return lines.join("");
}

function metaText(meta) {
  if (!meta) return "";
  return [meta.edition ? `EUROCONTROL CAL v${meta.edition}` : "EUROCONTROL CAL", meta.source, meta.generated ? `import ${meta.generated}` : "",
    meta.layout && meta.layout !== "CAL" ? `układ arkusza: ${meta.layout}` : ""].filter(Boolean).join(" · ");
}

export default {
  mount(root) {
    const pane = h(`<div class="pane sq-pane">
      <h2 class="title">SQUAWK – kody SSR FIR EPWW</h2>
      <div class="sq-grid">
        <div class="sq-col">
          <div class="card sq-look"><h3>Sprawdź kod</h3>
            <div class="sq-lookrow">
              <input class="field sq-code" type="text" inputmode="numeric" maxlength="6" autocomplete="off" spellcheck="false" placeholder="7700" aria-label="Kod SSR">
              <div class="sq-answer"></div>
            </div>
          </div>
          <div class="card sq-pools"><h3>Pule kodów SSR · EUROCONTROL CAL</h3>
            <div class="toolbar sq-bar">
              <span class="sq-views">${CATEGORIES.map((c) => `<button type="button" class="btn" data-view="${c.id}" title="${esc(c.line)}">${esc(c.label)} <span class="sq-n"></span></button>`).join("")}</span>
              <input type="search" class="sq-filter" placeholder="Filtr: kod, jednostka, cel…" size="32">
              <span class="hint sq-count"></span>
            </div>
            <p class="sq-line"></p>
            <p class="hint sq-meta"></p>
            <table class="data sq-table"><thead><tr><th>Od–do</th><th class="num">Liczba</th><th>CIV/MIL</th>
              <th title="${esc(`${arInfo("A").tip}\n${arInfo("R").tip}`)}">Przydział</th><th>Jednostka</th><th>Przydziela</th>
              <th>Cel</th><th>Ochrona</th><th>Uwagi</th><th title="wersja CAL, w której wiersz ostatnio zmieniono">Wer.</th></tr></thead>
              <tbody><tr><td colspan="${COLS}" class="hint">Ładowanie…</td></tr></tbody></table>
          </div>
        </div>
        <div class="card sq-special"><h3>Kody specjalne</h3>
          <table class="data sq-table"><thead><tr><th>Kod</th><th>Znaczenie</th></tr></thead><tbody></tbody></table>
          <p class="hint sq-foot">Znaczenia ogólne ICAO i SERA, nie z arkusza CAL – do potwierdzenia w AIP Polska ENR 1.6.</p>
        </div>
      </div>
    </div>`);
    root.append(pane);
    const input = pane.querySelector(".sq-code");
    const answer = pane.querySelector(".sq-answer");
    const filter = pane.querySelector(".sq-filter");
    const poolBody = pane.querySelector(".sq-pools tbody");
    const specialBody = pane.querySelector(".sq-special tbody");
    let data = null, loadedAt = 0, seq = 0, view = DEFAULT_VIEW;

    const current = () => { const c = checkCode(input.value); return c.ok ? c.code : ""; };
    const drawPools = () => {
      pane.querySelectorAll(".sq-views [data-view]").forEach((b) => {
        b.classList.toggle("primary", b.dataset.view === view);
        b.setAttribute("aria-pressed", String(b.dataset.view === view));
      });
      pane.querySelector(".sq-line").textContent = CAT[view]?.line || "";
      if (!data) return;
      const code = current();
      const counts = viewCounts(data.pools);
      pane.querySelectorAll(".sq-views [data-view]").forEach((b) => { b.querySelector(".sq-n").textContent = counts[b.dataset.view] ?? 0; });
      const all = viewPools(data.pools, view);
      const list = filterPools(all, filter.value);
      const total = list.reduce((n, p) => n + countOf(p), 0);
      pane.querySelector(".sq-count").textContent = all.length
        ? `${list.length === all.length ? nPools(list.length) : `${list.length} z ${nPools(all.length)}`} · ${nCodes(total)}` : "";
      pane.querySelector(".sq-meta").textContent = metaText(data.meta);
      poolBody.innerHTML = !data.pools.length ? `<tr><td colspan="${COLS}" class="hint sq-empty">Brak pul kodów w pliku data/seed/squawk.json.</td></tr>`
        : !all.length ? `<tr><td colspan="${COLS}" class="hint">Brak pul w tej kategorii.</td></tr>`
          : list.length ? list.map((p) => poolRow(p, code, view, data.meta?.participating_areas)).join("")
            : `<tr><td colspan="${COLS}" class="hint">Żadna pula nie pasuje do filtra.</td></tr>`;
      specialBody.innerHTML = data.special.map((s) => specialRow(s, code)).join("");
      poolBody.querySelector("tr.selected")?.scrollIntoView({ block: "nearest" });
    };
    const update = () => {
      const c = checkCode(input.value);
      input.classList.toggle("bad", !!c.error);
      answer.innerHTML = answerHtml(data, input.value, view);
      drawPools();
    };
    const setView = (v) => { if (CAT[v] && v !== view) { view = v; update(); } };
    const load = async () => {
      const my = ++seq;
      try {
        const d = await api("/api/squawk");
        if (my !== seq) return;
        data = d;
        loadedAt = Date.now();
      } catch (e) {
        if (my !== seq) return;
        if (!data) {
          poolBody.innerHTML = `<tr><td colspan="${COLS}" class="error">${esc(e.message)}</td></tr>`;
          specialBody.innerHTML = `<tr><td colspan="2" class="error">${esc(e.message)}</td></tr>`;
          answer.innerHTML = checkCode(input.value).ok ? `<p class="error">${esc(e.message)}</p>` : answer.innerHTML;
          return;
        }
      }
      update();
    };

    input.addEventListener("input", () => {
      update();
      const c = checkCode(input.value);
      // pełny kod = krok do cofnięcia; puste albo niepełne pole nie zmienia adresu (← wraca do poprzedniego kodu)
      if (c.ok) remember("squawk", c.code);
    });
    input.addEventListener("keydown", (e) => { if (e.key === "Escape" && input.value) { input.value = ""; input.dispatchEvent(new Event("input")); } });
    filter.addEventListener("input", drawPools);
    // przyciski kategorii nad tabelą i kategorie w odpowiedzi (pokaż pulę w tabeli)
    pane.addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) setView(b.dataset.view); });
    window.addEventListener(ONLINE_EVENT, () => { if (!data) load(); });
    update();
    load();
    // #squawk/7700: kod z adresu (← i Wstecz); przycisk menu (arg undefined) zostawia wpisany kod
    return { activate: (arg) => {
      if (arg !== undefined && arg !== input.value.trim()) { input.value = arg; update(); }
      if (data && Date.now() - loadedAt > RELOAD_MS) load();
      input.focus();
    } };
  },
};
