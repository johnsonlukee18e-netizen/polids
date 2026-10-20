import { api, h, iframeWithFallback } from "./api.js";
import { embedBar } from "./tabs/aip.js";

// Frazeologia (OTHER › PHRASEOLOGY): "Say Again? The Phraseology Database" z EUROCONTROL Learning Zone
// (adres z POLIDS_PHRASEOLOGY_URL). Zawsze próbujemy pokazać stronę w ramce. Backend przy tym sprawdza nagłówki
// X-Frame-Options / CSP; jeśli serwis zabrania osadzania, przeglądarka pokaże w ramce komunikat o blokadzie, a nad
// ramką widać, dlaczego, i przycisk otwierający frazeologię w nowej karcie. 0.12.6: napisy bez nazwy serwisu,
// pasek nad ramką bez adresu strony.
export function mountPhraseology(pane, ctx) {
  iframeWithFallback(pane, ctx.config.links.phraseology, "", { showUrl: false });
  embedBar(pane);
  const note = h(`<div class="embed-note hint">Checking whether the page can be shown in a frame…</div>`);
  pane.insertBefore(note, pane.querySelector("iframe"));
  api("/api/embed-check/phraseology").then((r) => {
    if (r.embeddable && !r.reason) note.remove();
    else if (r.embeddable === false) {
      note.classList.add("warn");
      note.textContent = `The page may not show in the frame (${r.reason}). If the frame below is empty or shows a blocking message, open the page in a new tab with the ↗ button above.`;
    } else note.textContent = `Could not check the page (${r.reason}). If the frame is empty, open the page in a new tab with the ↗ button above.`;
  }).catch((e) => { note.textContent = `Could not check the page (${e.message}). If the frame is empty, open the page in a new tab with the ↗ button above.`; });
}
