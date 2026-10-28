import { api, esc, h, ONLINE_EVENT } from "./api.js";

// OTHER › REGCAUSE (0.13.0): kody przyczyn regulacji ATFM z /api/regcause (data/seed/regcause.json) jak w PANDORZE:
// jedna przewijana lista, zielony pasek na całą szerokość z nazwą kategorii (przykleja się u góry przy przewijaniu),
// pod nim czarne i ciemnoszare wiersze w trzech kolumnach: kod ("CD 89"), opis, opis opóźnienia IATA.
// Kolejność kategorii i wierszy z pliku. Bez stopki i bez nagłówka kolumn (jak na zdjęciu).

// lista z danych /api/regcause ({categories: [{name, rows: [{code, description, iata}]}]}); tekst escapowany
export function regcauseHtml(data) {
  const cats = (data?.categories || []).filter((c) => c?.rows?.length);
  if (!cats.length) return `<p class="hint rc-empty">No codes.</p>`;
  return cats.map((c) => `<section class="rc-cat"><h3 class="rc-bar">${esc(c.name)}</h3>${c.rows.map((r) => `<div class="rc-row">`
    + `<span class="rc-code">${esc(r.code)}</span><span class="rc-text">${esc(r.description)}</span>`
    + `<span class="rc-iata">${esc(r.iata)}</span></div>`).join("")}</section>`).join("");
}

// panel podzakładki; destroy(): spóźniona odpowiedź nic nie rysuje, nasłuch ONLINE_EVENT zdjęty
export function mountRegcause(pane) {
  const list = h(`<div class="rc-list"><p class="hint rc-empty">Loading…</p></div>`);
  pane.append(list);
  let dead = false, done = false;
  const load = () => api("/api/regcause").then((d) => {
    if (dead) return;
    done = true;
    list.innerHTML = regcauseHtml(d);
  }).catch((e) => { if (!dead && !done) list.innerHTML = `<p class="error rc-empty">${esc(e.message)}</p>`; });
  const online = () => { if (!done) load(); };
  window.addEventListener(ONLINE_EVENT, online);
  load();
  return { destroy: () => { dead = true; window.removeEventListener(ONLINE_EVENT, online); } };
}
