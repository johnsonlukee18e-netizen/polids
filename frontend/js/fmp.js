import { h } from "./api.js";

// OTHER › FMP: ZAŚLEPKA z gałęzi OTHER (r16/otherb), żeby OTHER działał bez gałęzi FLIGHT PLAN / FMP; przy scaleniu
// zastępuje ją pełny moduł (te same eksporty). mountFmp(pane) zwraca {activate(), destroy()}.
export function mountFmp(pane) {
  pane.append(h(`<div class="pane ot-future"><p>This function will be available in the future.</p></div>`));
  return { activate() {}, destroy() {} };
}
