import { api, debounce, esc, h, letterMenu, touchKeyboard } from "../api.js";

const CATEGORY = { CARGO: "CARGO", MIL: "MILITARY" };
// najwięcej wierszy na raz (ALL to ~7000 znaków wywoławczych): pełna lista = obcięta, z podpowiedzią jak w AIRCRAFT
const LIMIT = 1000;

export default {
  mount(root) {
    let prefix = "";
    const letters = letterMenu(root, (l) => { prefix = l; load(); });
    // 0.13.1: pole wyszukiwania u góry i klawiatura dotykowa na dole zostają na miejscu, przewija się tylko lista
    const pane = h(`<div class="pane cs-pane">
      <div class="toolbar">
        <input type="search" class="q" placeholder="Search: ICAO code, callsign, operator, country…" size="46" autofocus>
        <select class="cat"><option value="">All</option><option value="CARGO">CARGO only</option><option value="MIL">MILITARY only</option></select>
        <span class="hint count"></span>
      </div>
      <div class="cs-list"><table class="data callsigns"><thead><tr><th>ICAO</th><th>Callsign</th><th>Operator</th><th>Country</th><th>Info</th></tr></thead><tbody></tbody></table></div>
    </div>`);
    root.append(pane);
    const q = pane.querySelector(".q");
    const kbd = touchKeyboard(q, letters.kbd);
    pane.append(kbd.el);
    const body = pane.querySelector("tbody");
    let seq = 0;
    const load = async () => {
      const my = ++seq;
      try {
        const rows = await api(`/api/callsigns?q=${encodeURIComponent(q.value.trim())}&prefix=${prefix}&category=${pane.querySelector(".cat").value}&limit=${LIMIT}`);
        if (my !== seq) return;
        pane.querySelector(".count").textContent = `${rows.length} ${rows.length === 1 ? "result" : "results"}`
          + (rows.length === LIMIT ? ` (first ${LIMIT} shown – pick a letter or type a code)` : "");
        body.innerHTML = rows.map((r) => `<tr><td class="icao">${esc(r.icao)}</td><td class="tel">${esc(r.telephony || "–")}</td>
          <td class="minor">${esc(r.name)}</td><td class="minor">${esc(r.country)}</td>
          <td>${r.category ? `<span class="tag ${r.category.toLowerCase()}">${CATEGORY[r.category] || esc(r.category)}</span>` : ""}</td></tr>`).join("");
      } catch (e) {
        body.innerHTML = `<tr><td colspan="5" class="error">${esc(e.message)}</td></tr>`;
      }
    };
    q.addEventListener("input", debounce(load));
    pane.querySelector(".cat").addEventListener("change", load);
    load();
    // #callsign/A: litera z adresu (← i Wstecz), "" = wszystkie; przycisk menu (arg undefined) zostawia bieżącą
    return { activate: (arg) => {
      if (arg !== undefined && /^[A-Z]?$/.test(arg) && arg !== prefix) { prefix = arg; letters.set(arg); load(); }
      kbd.sync();
      q.focus();
    } };
  },
};
