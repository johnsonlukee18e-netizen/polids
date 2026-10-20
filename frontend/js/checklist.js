// Checklisty w formacie vatiris: punkt "Co zrobić...AKCJA", sections = {indeks: nagłówek}.
// Stan zaznaczeń (i notatki z pól INPUT) zapisuje się w przeglądarce pod podanym kluczem.
import { api, esc, h, lsGet, lsSet, subtabs } from "./api.js";

// Tekst jest escapowany, przepuszczamy tylko proste znaczniki formatowania z plików vatiris
export const markup = (s) => esc(s).replace(/&lt;(\/?)(b|i|tt)&gt;/g, "<$1$2>");

// HTML checklisty bez DOM (testy w Node): st = zapisany stan {indeks: zaznaczony, "n"+indeks: notatka}.
// Punkt bez "...AKCJA" (przekazanie, wskazówki) to sam tekst, bez kropek; numbered: true numeruje punkty (1., 2., ...).
export function checklistHtml(chk, st = {}) {
  const rows = chk.items.map((item, i) => {
    const cut = item.lastIndexOf("...");
    const what = cut >= 0 ? item.slice(0, cut) : item;
    const action = cut >= 0 ? item.slice(cut + 3) : "";
    const head = chk.sections?.[i] ? `<div class="chk-section">${markup(chk.sections[i])}</div>` : "";
    const num = chk.numbered ? `<b class="chk-num">${i + 1}.</b> ` : "";
    const input = action.startsWith("INPUT:");
    const right = input
      ? `<input class="field chk-note" data-i="${i}" placeholder="${esc(action.slice(6))}" value="${esc(st["n" + i] || "")}">`
      : `<b class="chk-action">${markup(action)}</b>`;
    return `${head}<label class="chk-row${st[i] ? " done" : ""}"><input type="checkbox" data-i="${i}" ${st[i] ? "checked" : ""}>
      <span class="chk-body"><span class="chk-what">${num}${markup(what)}</span>${action ? `<span class="chk-dots"></span>${right}` : ""}</span></label>`;
  }).join("");
  return (chk.preDescription ? `<p class="chk-pre">${markup(chk.preDescription)}</p>` : "") + rows
    + `<div class="chk-foot"><button class="btn reset" title="Untick all items and clear the notes">Clear</button><span class="hint chk-count"></span></div>`;
}

export function renderChecklist(el, chk, key) {
  let st = {};
  try { st = JSON.parse(lsGet(key) || "{}"); } catch { st = {}; }
  // zapisany stan bywa nie-obiektem ("null", liczba, lista ze starszej wersji): wtedy od zera
  if (!st || typeof st !== "object" || Array.isArray(st)) st = {};
  const save = () => lsSet(key, JSON.stringify(st));
  el.innerHTML = checklistHtml(chk, st);
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

// OTHER › CHECKLIST (do 0.12.5 osobna zakładka menu): checklisty z /api/checklists w drugim podmenu, obok podmenu OTHER.
// start = id checklisty z adresu ("" = pierwsza); onPick(id) po kliknięciu w podmenu, onPick(id, true), gdy adres
// wskazywał nieznaną checklistę (pokazana jest pierwsza, OTHER poprawia adres bez nowego kroku historii).
// Zaznaczenia pod kluczem "checklist.tab.<id>" jak w dawnej zakładce CHECKLIST, więc zapisany postęp zostaje.
export function mountChecklists(pane, { start = "", onPick = () => {} } = {}) {
  const box = h(`<div class="chk-tabs" style="display:flex;flex:1;min-height:0"><div class="pane"><p class="hint">Loading…</p></div></div>`);
  pane.append(box);
  let sub = null, list = [], want = start, dead = false;
  const page = (c) => (p) => {
    p.innerHTML = `<div class="chk-page"><h2>${esc(c.title)}</h2><div class="checklist big"></div>
      <p class="hint" style="margin-top:16px">Ticks stay in this browser until cleared.</p></div>`;
    renderChecklist(p.querySelector(".checklist"), c, `checklist.tab.${c.id}`);
  };
  const pick = (id) => {
    const c = list.find((x) => x.id === id) || list[0];
    if (sub.current() !== c.id) sub.show(c.id);
    if (id && id !== c.id) onPick(c.id, true);
  };
  api("/api/checklists").then((data) => {
    if (dead) return;
    list = data.checklists || [];
    if (!list.length) { box.innerHTML = `<div class="pane"><p class="hint">No checklists.</p></div>`; return; }
    box.innerHTML = "";
    // podmenu bez własnego zapisu adresu (remember): adres OTHER składa onPick
    sub = subtabs(box, list.map((c) => ({ id: c.id, label: c.label, render: page(c) })), { remember: false });
    sub.nav.addEventListener("click", (e) => { if (e.target.closest("button[data-id]")) onPick(sub.current()); });
    pick(want);
  }).catch((e) => { if (!dead) box.innerHTML = `<div class="pane"><p class="error">${esc(e.message)}</p></div>`; });
  return {
    pick: (id) => { if (sub) pick(id); else want = id; },
    current: () => sub?.current() || null,
    destroy: () => { dead = true; },
  };
}
