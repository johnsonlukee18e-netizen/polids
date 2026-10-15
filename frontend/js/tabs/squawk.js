import { api, esc, h, ONLINE_EVENT, remember } from "../api.js";

// SQUAWK: pule kodów SSR do przydzielania w FIR EPWW (EUROCONTROL / ICAO EUR CAL, filtr UNIT EP i EUR-E) i kody
// specjalne (backend: GET /api/squawk, data/seed/squawk.json; pule wpisuje importer backend/app/importers/squawk_cal.py).
// Sprawdzanie kodu liczy przeglądarka z tych samych danych (bez zapytania na każdy wpisany kod).
// Adres: "#squawk" albo "#squawk/7700" (sprawdzany kod); każdy wpisany pełny kod to krok do cofnięcia (← i Wstecz).

export const IMPORT_CMD = "python -m backend.app.importers.squawk_cal eurocontrol-icao-eur-cal-v4-13.xls";
const EMERGENCY = new Set(["7500", "7600", "7700"]);
const RELOAD_MS = 60 * 1000;   // po powrocie na zakładkę dane z serwera najwyżej minutowe (import CAL bez F5)

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

// znaczenie kodu: kody specjalne o tym numerze i pule, w których leży (data jak z /api/squawk)
export function lookup(data, code) {
  const pools = data?.pools || [], special = data?.special || [];
  return { code, imported: pools.length > 0, special: special.filter((s) => s.code === code), pools: pools.filter((p) => inRange(code, p)) };
}

// czego kod nie ma (wynik lookup): "" = leży w puli
export function missText(r) {
  if (r.pools.length) return "";
  if (r.special.length) return r.imported ? "Nie leży w żadnej puli EPWW z CAL." : "Pule EPWW z CAL nie są jeszcze zaimportowane.";
  return r.imported ? "– nie jest kodem specjalnym i nie leży w żadnej puli EPWW z CAL."
    : "– nie jest kodem specjalnym; pule EPWW z CAL nie są jeszcze zaimportowane.";
}

// filtr pul: każde słowo musi pasować; pełny kod (4 cyfry 0–7) = pule, w których leży
const hay = (p) => [`${p.from}-${p.to}`, p.unit, p.type, p.remarks, ...(p.match || []), ...Object.values(p.raw || {})]
  .filter(Boolean).join(" ").toUpperCase();
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

// --- widok
const poolTip = (p) => [`arkusz ${p.sheet ?? "?"}, wiersz ${p.row ?? "?"}`, ...Object.entries(p.raw || {}).map(([k, v]) => `${k}: ${v}`)].join("\n");
const poolRow = (p, code) => `<tr class="${code && inRange(code, p) ? "selected" : ""}" title="${esc(poolTip(p))}">
  <td class="sq-range">${esc(rangeText(p))}</td><td class="num">${p.count ?? rangeSize(p.from, p.to || p.from)}</td>
  <td class="sq-unit">${esc(p.unit || "–")}${(p.match || []).filter((m) => m !== "unit" && m !== p.unit).map((m) => ` <span class="tag sq-match">${esc(m)}</span>`).join("")}</td>
  <td>${esc(p.type || "–")}</td><td class="sq-minor">${esc(p.remarks || "")}</td></tr>`;

const specialRow = (s, code) => `<tr class="${s.code === code ? "selected" : ""}">
  <td class="sq-scode${EMERGENCY.has(s.code) ? " emerg" : ""}">${esc(s.code)}</td>
  <td><b class="sq-label">${esc(s.label || "")}</b> <span class="sq-meaning">${esc(s.meaning || "")}</span>
    ${s.note ? `<div class="sq-note">${esc(s.note)}</div>` : ""}
    ${s.excluded?.length ? `<div class="sq-excl"><span class="hint">bez kodu ${esc(s.code)}:</span> ${s.excluded.map((x) => `<span class="tag">${esc(x)}</span>`).join(" ")}</div>` : ""}
    <div class="hint sq-src">źródło: ${esc(s.source || "–")}</div></td></tr>`;

function answerHtml(data, text) {
  const { code, ok, error } = checkCode(text);
  if (error) return `<p class="sq-bad">${esc(error)}</p>`;
  if (!ok) return `<p class="hint">${code ? `jeszcze ${4 - code.length} ${plural(4 - code.length, "cyfra", "cyfry", "cyfr")}` : "Wpisz 4 cyfry kodu SSR (0–7), np. 7700."}</p>`;
  if (!data) return `<p class="hint">Ładowanie…</p>`;
  const r = lookup(data, code);
  const lines = r.special.map((s) => `<p><b class="sq-big${EMERGENCY.has(s.code) ? " emerg" : ""}">${esc(s.code)}</b>
    <b class="sq-label">${esc(s.label || "")}</b> – ${esc(s.meaning || "")}</p>`);
  lines.push(...r.pools.map((p) => `<p><b class="sq-big">${esc(code)}</b> pula <b class="mono">${esc(rangeText(p))}</b>
    (${nCodes(p.count ?? rangeSize(p.from, p.to || p.from))}) · ${esc(p.unit || "–")}${p.type ? ` · ${esc(p.type)}` : ""}${p.remarks ? ` · <span class="sq-minor">${esc(p.remarks)}</span>` : ""}</p>`));
  const miss = missText(r);
  if (miss) lines.push(`<p class="hint">${r.special.length ? "" : `<b class="sq-big">${esc(code)}</b> `}${esc(miss)}</p>`);
  return lines.join("");
}

const emptyPools = () => `<tr><td colspan="5" class="sq-empty">
  <p>Pule kodów SSR FIR EPWW z <b>EUROCONTROL CAL v4.13</b> (filtr UNIT: EP i EUR-E) pojawią się tutaj po zaimportowaniu arkusza:</p>
  <code class="sq-cmd">${esc(IMPORT_CMD)}</code></td></tr>`;

function metaText(meta) {
  if (!meta) return "";
  const f = meta.filter || {};
  return [meta.edition ? `EUROCONTROL CAL v${meta.edition}` : "EUROCONTROL CAL", meta.source, meta.generated ? `import ${meta.generated}` : "",
    f.unit || f.mention ? `filtr: UNIT ${(f.unit || []).join(", ")}${f.mention?.length ? ` i ${f.mention.join(", ")}` : ""}` : ""]
    .filter(Boolean).join(" · ");
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
          <div class="card sq-pools"><h3>Pule kodów do przydzielania · FIR EPWW</h3>
            <div class="toolbar sq-bar">
              <input type="search" class="sq-filter" placeholder="Filtr: kod, jednostka, przeznaczenie, uwagi…" size="40">
              <span class="hint sq-count"></span>
            </div>
            <p class="hint sq-meta"></p>
            <table class="data sq-table"><thead><tr><th>Od–do</th><th class="num">Liczba kodów</th><th>Jednostka</th><th>Przeznaczenie</th><th>Uwagi</th></tr></thead>
              <tbody><tr><td colspan="5" class="hint">Ładowanie…</td></tr></tbody></table>
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
    let data = null, loadedAt = 0, seq = 0;

    const current = () => { const c = checkCode(input.value); return c.ok ? c.code : ""; };
    const drawPools = () => {
      if (!data) return;
      const code = current();
      const list = filterPools(data.pools, filter.value);
      const total = data.pools.reduce((n, p) => n + (p.count || 0), 0);
      pane.querySelector(".sq-count").textContent = data.pools.length
        ? `${list.length === data.pools.length ? nPools(list.length) : `${list.length} z ${nPools(data.pools.length)}`} · ${nCodes(total)}` : "";
      pane.querySelector(".sq-meta").textContent = metaText(data.meta);
      filter.disabled = !data.pools.length;
      poolBody.innerHTML = !data.pools.length ? emptyPools()
        : list.length ? list.map((p) => poolRow(p, code)).join("")
          : `<tr><td colspan="5" class="hint">Żadna pula nie pasuje do filtra.</td></tr>`;
      specialBody.innerHTML = data.special.map((s) => specialRow(s, code)).join("");
      poolBody.querySelector("tr.selected")?.scrollIntoView({ block: "nearest" });
    };
    const update = () => {
      const c = checkCode(input.value);
      input.classList.toggle("bad", !!c.error);
      answer.innerHTML = answerHtml(data, input.value);
      drawPools();
    };
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
          poolBody.innerHTML = `<tr><td colspan="5" class="error">${esc(e.message)}</td></tr>`;
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
