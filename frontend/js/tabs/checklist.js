import { api, esc, h, subtabs } from "../api.js";
import { renderChecklist } from "../checklist.js";

// CHECKLIST: otwarcie / zamknięcie stanowiska, przekazanie (WEST) i zmiana pasa, wg vatiris.
export default {
  mount(root) {
    const holder = h(`<div class="pane"><p class="hint">Ładowanie…</p></div>`);
    root.append(holder);
    api("/api/checklists").then((data) => {
      holder.remove();
      subtabs(root, data.checklists.map((c) => ({
        id: c.id, label: c.label, render: (pane) => {
          pane.innerHTML = `<div class="chk-page"><h2>${esc(c.title)}</h2><div class="checklist big"></div>
            <p class="hint" style="margin-top:16px">Zaznaczenia zostają w tej przeglądarce do wyczyszczenia. Źródło: vatiris (minsulander/vatiris), plik data/seed/checklists.json.</p></div>`;
          renderChecklist(pane.querySelector(".checklist"), c, `checklist.tab.${c.id}`);
        },
      })));
    }).catch((e) => { holder.innerHTML = `<p class="error">${esc(e.message)}</p>`; });
  },
};
