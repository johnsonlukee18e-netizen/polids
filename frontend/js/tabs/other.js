import { h, navigate, remember, subtabs } from "../api.js";
import { mountChecklists } from "../checklist.js";
import { isCoordFile, mountDocs } from "../docs.js";
import { cleanCallsign, mountFlightPlan } from "../flightplan.js";
import { cleanTv, mountFmp } from "../fmp.js";
import { mountRegcause } from "../regcause.js";
import { mountSquawk } from "../squawk.js";
import { mountVfrMinima } from "../vfrminima.js";

// OTHER: podmenu jak w PANDORZE, alfabetycznie (0.13.0, issue #23): 17 podzakładek (0.13.1, issue #25: bez PHRASEOLOGY),
// z czego DOCS (PDF-y z data/docs/), CHECKLIST (do 0.12.5 osobna zakładka; checklisty w drugim podmenu), SQUAWK
// (do 0.12.6 osobna zakładka), FLIGHT PLAN, FMP, REGCAUSE i VFR MINIMA; reszta to zaślepki z jednym zdaniem.
// Bez adresu (przycisk menu przy pierwszym otwarciu, "#other") i dla nieznanego id: DOCS, jak do 0.12.6.
// Adresy "#other/<id>", a z zapamiętanym stanem "#other/docs/<plik w data/docs>" (bez pliku: pierwszy dokument),
// "#other/checklist/<id checklisty>" (bez id: pierwsza), "#other/squawk/<kod>", "#other/flight-plan/<ZNAK>"
// i "#other/fmp/<TV>" (sektor z wykresami ENTRY i OCC, np. EP-BH). Stare "#docs/<plik>", "#checklist/<id>"
// i "#squawk/<kod>" przekierowuje app.js; stare "#phraseology" otwiera OTHER w jego stanie, a "#other/phraseology"
// to nieznane id (DOCS). LOA i LOP (do 0.12.2 w DOCS, np. z RADIO) otwiera COORDINATION › DOKUMENTY:
// "#other/docs/LOA/<plik>" → "#coordination/docs/LOA/<plik>".
export const FUTURE = "This function will be available in the future.";
const DEFAULT = "docs";
// zaślepka: samo zdanie na środku panelu
const future = (pane) => { pane.append(h(`<div class="pane ot-future"><p>${FUTURE}</p></div>`)); };

export default {
  mount(root, ctx) {
    // stan podzakładek, który przetrwa ponowne rysowanie (każde kliknięcie w podmenu rysuje od nowa):
    // file: dokument DOCS ("" = pierwszy), chkId: checklista ("" = pierwsza), sqCode: kod SQUAWK w adresie, sqText:
    // tekst pola SQUAWK (kod albo filtr, jak w dawnej osobnej zakładce), fpCs: znak FLIGHT PLAN, fmpTv: sektor FMP
    // z wykresami ("" = żaden)
    let file = "", chkId = "", sqCode = "", sqText = "", fpCs = "", fmpTv = "";
    let sub = null, live = null;   // live: obiekt strony na ekranie (z render), np. docs z pick()
    // Strona: {id, label, render(pane) → obiekt strony albo nic, arg() → stan do adresu, set(rest) → stan z adresu,
    // update(live) → otwarta strona pokazuje nowy stan z adresu, resume(live) → przycisk menu przy otwartej stronie}.
    // Bez render: zaślepka. Obiekt strony z destroy() jest niszczony przy przejściu do innej podzakładki (subtabs).
    const PAGES = [
      { id: "4p", label: "4P" },
      { id: "aftn", label: "AFTN" },
      { id: "bomb-phone", label: "BOMB PHONE" },
      { id: "braking-action", label: "BRAKING ACTION" },
      // ponowne kliknięcie CHECKLIST wraca do ostatnio wybranej checklisty; zaznaczenia są w przeglądarce.
      // destroy() przy przejściu do innej podzakładki: spóźnione dane już nic nie rysują
      { id: "checklist", label: "CHECKLIST", arg: () => chkId, set: (id) => { chkId = id; }, update: (chk) => chk.pick(chkId),
        render: (pane) => mountChecklists(pane, { start: chkId, onPick: (id, fix) => {
          chkId = id;
          remember("other", argOf(), { replace: !!fix });
        } }) },
      // ponowne kliknięcie DOCS wczytuje listę od nowa, z tym samym dokumentem
      { id: "docs", label: "DOCS", arg: () => file, set: (f) => { file = f; }, update: (docs) => docs.pick(file),
        render: (pane) => mountDocs(pane, ctx, { start: file, onPick: (f) => { file = f; remember("other", argOf()); } }) },
      // każde wyszukanie znaku to krok do cofnięcia (onLookup); znak z adresu oczyszczony jak w polu ("lot-3827" →
      // LOT3827, adres też); przycisk menu: plan starszy niż 30 s od razu odświeżony (activate bez arg)
      { id: "flight-plan", label: "FLIGHT PLAN", arg: () => fpCs, set: (cs) => { fpCs = cleanCallsign(cs); },
        update: (fp) => fp.activate(fpCs), resume: (fp) => fp.activate(),
        render: (pane) => mountFlightPlan(pane, { start: fpCs, onLookup: (cs) => { fpCs = cleanCallsign(cs); remember("other", argOf()); } }) },
      // 0.13.1: kliknięty sektor (wykresy ENTRY i OCC po prawej) w adresie; każdy klik to krok do cofnięcia (onPick),
      // drugi klik w ten sam wiersz albo ✕ zamyka wykresy ("#other/fmp"); przycisk menu: dane starsze niż 60 s od nowa
      { id: "fmp", label: "FMP", arg: () => fmpTv, set: (tv) => { fmpTv = cleanTv(tv); },
        update: (fmp) => fmp.activate(fmpTv), resume: (fmp) => fmp.activate(),
        render: (pane) => mountFmp(pane, { start: fmpTv, onPick: (tv) => { fmpTv = cleanTv(tv); remember("other", argOf()); } }) },
      { id: "holding", label: "HOLDING" },
      { id: "ia", label: "IA" },
      { id: "light-gun", label: "LIGHT GUN" },
      { id: "meteo", label: "METEO" },
      { id: "nato-weather", label: "NATO WEATHER" },
      { id: "position", label: "POSITION" },
      { id: "regcause", label: "REGCAUSE", render: (pane) => mountRegcause(pane) },
      // każdy wpisany pełny kod to krok do cofnięcia (onCode); wyczyszczone pole podmienia adres (replace); tekst pola
      // (onInput) wraca po przejściu przez inną podzakładkę; przycisk menu: fokus w polu i świeże dane
      { id: "squawk", label: "SQUAWK", arg: () => sqCode, set: (c) => { sqCode = sqText = c; },
        update: (sq) => sq.activate(sqCode), resume: (sq) => sq.activate(),
        render: (pane) => mountSquawk(pane, { start: sqText, addr: sqCode, onInput: (t) => { sqText = t; },
          onCode: (c, o = {}) => { sqCode = sqText = c; remember("other", argOf(), { replace: !!o.replace }); } }) },
      { id: "vfr-minima", label: "VFR MINIMA", render: (pane) => mountVfrMinima(pane) },
    ];
    const byId = new Map(PAGES.map((p) => [p.id, p]));
    const argOf = (id = sub?.current()) => { const s = byId.get(id)?.arg?.() || ""; return s ? `${id}/${s}` : id; };
    // 0.13.1 (issue #25): napisy w jednej linijce, jak w pozostałych podmenu (przyciski 137 x 28)
    sub = subtabs(root, PAGES.map((p) => ({ id: p.id, label: p.label, fill: true,
      render: (pane) => (live = (p.render || future)(pane) || null) })), { arg: argOf, first: DEFAULT });
    return {
      // arg undefined (przycisk menu): zostaje otwarta podzakładka i jej stan; "docs/LOA/plik.pdf" → COORDINATION
      activate(arg) {
        if (arg !== undefined) {
          const [head, ...more] = arg.split("/");
          const id = byId.has(head) ? head : DEFAULT;
          const rest = byId.has(head) ? more.join("/") : "";
          const f = id === "docs" ? rest : "";
          // przekierowanie w activate(): app.js zapisuje adres COORDINATION w tym samym kroku historii
          if (isCoordFile(f)) return navigate("coordination", "docs/" + f);
          const page = byId.get(id);
          page.set?.(rest);
          // otwarta strona dostaje nowy stan bez ponownego rysowania; inna podzakładka rysuje się od razu z tym stanem
          if (sub.current() === id && live) page.update?.(live);
          else if (sub.current() !== id) sub.show(id);
        } else if (live) byId.get(sub.current())?.resume?.(live);
        // menu: bieżący stan do adresu (bez nowego kroku)
        remember("other", argOf());
      },
    };
  },
};
