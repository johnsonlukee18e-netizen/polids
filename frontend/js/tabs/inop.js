import { h, iframeWithFallback } from "../api.js";
import { embedBar } from "./aip.js";

// Strona INOP / procedur operacyjnych PL vACC (om.plvacc.pl) w ramce.
export default {
  mount(root, ctx) {
    const pane = h(`<div class="pane fill"></div>`);
    root.append(pane);
    iframeWithFallback(pane, ctx.config.links.inop);
    embedBar(pane);
  },
};
