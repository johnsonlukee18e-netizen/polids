// Checklisty w formacie vatiris: punkt "Co zrobić...AKCJA", sections = {indeks: nagłówek}.
// Stan zaznaczeń (i notatki z pól INPUT) zapisuje się w przeglądarce pod podanym kluczem.
import { esc } from "./api.js";

// Tekst jest escapowany, przepuszczamy tylko proste znaczniki formatowania z plików vatiris
export const markup = (s) => esc(s).replace(/&lt;(\/?)(b|i|tt)&gt;/g, "<$1$2>");

export function renderChecklist(el, chk, key) {
  let st = {};
  try { st = JSON.parse(localStorage.getItem(key) || "{}"); } catch { st = {}; }
  const save = () => { try { localStorage.setItem(key, JSON.stringify(st)); } catch { /* tryb prywatny */ } };
  const rows = chk.items.map((item, i) => {
    const cut = item.lastIndexOf("...");
    const what = cut >= 0 ? item.slice(0, cut) : item;
    const action = cut >= 0 ? item.slice(cut + 3) : "";
    const head = chk.sections?.[i] ? `<div class="chk-section">${markup(chk.sections[i])}</div>` : "";
    const input = action.startsWith("INPUT:");
    const right = input
      ? `<input class="field chk-note" data-i="${i}" placeholder="${esc(action.slice(6))}" value="${esc(st["n" + i] || "")}">`
      : `<b class="chk-action">${markup(action)}</b>`;
    return `${head}<label class="chk-row${st[i] ? " done" : ""}"><input type="checkbox" data-i="${i}" ${st[i] ? "checked" : ""}>
      <span class="chk-body"><span class="chk-what">${markup(what)}</span>${action ? `<span class="chk-dots"></span>${right}` : ""}</span></label>`;
  }).join("");
  el.innerHTML = (chk.preDescription ? `<p class="chk-pre">${markup(chk.preDescription)}</p>` : "") + rows
    + `<div class="chk-foot"><button class="btn reset">Wyczyść</button><span class="hint chk-count"></span></div>`;
  const count = () => {
    const n = chk.items.filter((_, i) => st[i]).length;
    el.querySelector(".chk-count").textContent = `${n}/${chk.items.length}`;
  };
  el.onchange = (e) => {
    const i = e.target.dataset.i;
    if (i === undefined) return;
    if (e.target.type === "checkbox") {
      st[i] = e.target.checked;
      e.target.closest(".chk-row").classList.toggle("done", e.target.checked);
    } else st["n" + i] = e.target.value;
    save();
    count();
  };
  el.querySelector(".reset").onclick = () => { st = {}; save(); renderChecklist(el, chk, key); };
  count();
}
