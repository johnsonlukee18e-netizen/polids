import { api, esc, h, subtabs } from "../api.js";

const ASSIST = [["A", "Acknowledge"], ["S", "Separate"], ["S", "Silence"], ["I", "Inform"], ["S", "Support"], ["T", "Time"]];
const assistBar = () => `<div class="assist">${ASSIST.map(([l, w]) => `<span><b>${l}</b>${w.slice(1)}</span>`).join("")}</div>`;

// Punkt: tekst, {text, items} (podpunkty) albo {note} (akapit bez punktora)
function items(list) {
  return `<ul>${list.map((i) => typeof i === "string" ? `<li>${esc(i)}</li>`
    : i.note ? `<li class="note">${esc(i.note)}</li>`
      : `<li class="sub">${esc(i.text)}${items(i.items || [])}</li>`).join("")}</ul>`;
}

export default {
  mount(root) {
    const holder = h(`<div class="pane"><p class="hint">Ładowanie…</p></div>`);
    root.append(holder);
    api("/api/emergency").then((data) => {
      holder.remove();
      subtabs(root, data.procedures.map((p) => ({
        id: p.id, label: p.label || p.id, render: (pane) => {
          pane.classList.add("emergency");
          pane.innerHTML = `<h2>${esc(p.title)}</h2>${p.subtitle ? `<div class="em-sub">${esc(p.subtitle)}</div>` : ""}
            ${p.assist ? assistBar() : ""}
            <div class="em-sections">${p.sections.map((s) => `<section><h3>${esc(s.title)}</h3>${items(s.items)}</section>`).join("")}</div>
            ${p.source ? `<p class="hint" style="margin-top:20px">Źródło: ${esc(p.source)}</p>` : ""}`;
        },
      })));
    }).catch((e) => { holder.innerHTML = `<p class="error">${esc(e.message)}</p>`; });
  },
};
