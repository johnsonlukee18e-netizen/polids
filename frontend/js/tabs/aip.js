import { h, iframeWithFallback } from "../api.js";

const NOTE = "Jeśli strona się nie wyświetla, blokuje osadzanie – użyj przycisku obok.";

const frame = (key) => ({
  mount(root, ctx) {
    const pane = h(`<div class="pane fill"></div>`);
    root.append(pane);
    iframeWithFallback(pane, ctx.config.links[key], NOTE);
  },
});

export const adciv = frame("aip_ifr");
export const admil = frame("aip_mil");
export const advfr = frame("aip_vfr");
