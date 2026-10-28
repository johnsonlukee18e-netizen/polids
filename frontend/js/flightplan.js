import { h } from "./api.js";

// OTHER › FLIGHT PLAN: ZAŚLEPKA z gałęzi OTHER (r16/otherb), żeby OTHER działał bez gałęzi FLIGHT PLAN / FMP;
// przy scaleniu zastępuje ją pełny moduł (te same eksporty). mountFlightPlan(pane, {start, onLookup}) zwraca
// {activate(arg), focus(), destroy()}; start/arg = znak wywoławczy ("" = puste pole), onLookup(callsign) po każdym
// wyszukaniu (OTHER zapisuje adres #other/flight-plan/<CALLSIGN>).
export function mountFlightPlan(pane, { start = "", onLookup = () => {} } = {}) {
  void start; void onLookup;
  pane.append(h(`<div class="pane ot-future"><p>This function will be available in the future.</p></div>`));
  return { activate() {}, focus() {}, destroy() {} };
}
