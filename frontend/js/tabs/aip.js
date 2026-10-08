import { h, iframeWithFallback } from "../api.js";

const NOTE = "Jeśli strona się nie wyświetla, blokuje osadzanie – użyj przycisku obok.";

// Pasek nad ramką w jednej linii: długi adres i uwaga skracane wielokropkiem, pełny tekst w dymku
export function embedBar(pane) {
  const bar = pane.querySelector(".toolbar");
  bar.classList.add("embed-bar");
  bar.querySelectorAll(".hint").forEach((el) => { el.title = el.textContent; });
}

const frame = (key) => ({
  mount(root, ctx) {
    const pane = h(`<div class="pane fill"></div>`);
    root.append(pane);
    iframeWithFallback(pane, ctx.config.links[key], NOTE);
    embedBar(pane);
  },
});

export const adciv = frame("aip_ifr");
export const admil = frame("aip_mil");
export const advfr = frame("aip_vfr");
