import { api, h, iframeWithFallback } from "../api.js";
import { embedBar } from "./aip.js";

// Frazeologia: "Say Again? The Phraseology Database" z EUROCONTROL Learning Zone (adres z POLIDS_PHRASEOLOGY_URL).
// Zawsze próbujemy pokazać stronę w ramce. Backend przy tym sprawdza nagłówki X-Frame-Options / CSP; jeśli serwis
// zabrania osadzania, przeglądarka pokaże w ramce komunikat o blokadzie, a nad ramką widać, dlaczego, i przycisk
// otwierający frazeologię w nowej karcie.
export default {
  mount(root, ctx) {
    const url = ctx.config.links.phraseology;
    const pane = h(`<div class="pane fill"></div>`);
    root.append(pane);
    iframeWithFallback(pane, url, "EUROCONTROL Learning Zone");
    embedBar(pane);
    const note = h(`<div class="embed-note hint">Sprawdzam, czy Learning Zone pozwala wyświetlić się w ramce…</div>`);
    pane.insertBefore(note, pane.querySelector("iframe"));
    api("/api/embed-check/phraseology").then((r) => {
      if (r.embeddable && !r.reason) note.remove();
      else if (r.embeddable === false) {
        note.classList.add("warn");
        note.textContent = `Learning Zone może nie wyświetlić się w ramce (${r.reason}). Jeśli poniżej jest pusto albo widać komunikat o blokadzie, użyj przycisku „Otwórz w nowej karcie ↗”.`;
      } else note.textContent = `Nie udało się sprawdzić strony (${r.reason}). Jeśli ramka jest pusta, użyj przycisku „Otwórz w nowej karcie ↗”.`;
    }).catch((e) => { note.textContent = `Nie udało się sprawdzić strony (${e.message}). Jeśli ramka jest pusta, użyj przycisku „Otwórz w nowej karcie ↗”.`; });
  },
};
