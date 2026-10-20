import { navigate, remember, subtabs } from "../api.js";
import { mountChecklists } from "../checklist.js";
import { isCoordFile, mountDocs } from "../docs.js";
import { mountPhraseology } from "../phraseology.js";

// OTHER: podmenu jak w METEO: DOCS (PDF-y z data/docs/), PHRASEOLOGY (do 0.12.2 osobna zakładka menu) i CHECKLIST
// (do 0.12.5 osobna zakładka menu; checklisty w drugim podmenu obok tego).
// Adresy "#other/docs/<plik w data/docs>" (bez pliku: pierwszy dokument), "#other/phraseology" i
// "#other/checklist/<id checklisty>" (bez id: pierwsza checklista); stare "#docs/<plik>", "#phraseology" i
// "#checklist/<id>" przekierowuje app.js. LOA i LOP (do 0.12.2 w DOCS, np. z RADIO) otwiera
// COORDINATION › DOKUMENTY: "#other/docs/LOA/<plik>" i "#docs/LOA/<plik>" → "#coordination/docs/LOA/<plik>".
export default {
  mount(root, ctx) {
    // file: dokument z adresu albo kliknięty na liście ("" = pierwszy);
    // chkId: checklista z adresu albo kliknięta w podmenu ("" = pierwsza)
    let docs = null, file = "";
    let chk = null, chkId = "";
    let sub = null;
    const argOf = (id = sub?.current()) => (id === "phraseology" ? "phraseology"
      : id === "checklist" ? (chkId ? `checklist/${chkId}` : "checklist") : file ? `docs/${file}` : "docs");
    sub = subtabs(root, [
      // ponowne kliknięcie DOCS wczytuje listę od nowa, z tym samym dokumentem
      { id: "docs", label: "DOCS", fill: true, render: (pane) => {
        chk = null;
        docs = mountDocs(pane, ctx, { start: file, onPick: (f) => { file = f; remember("other", argOf()); } });
      } },
      { id: "phraseology", label: "PHRASEOLOGY", fill: true, render: (pane) => { docs = chk = null; mountPhraseology(pane, ctx); } },
      // ponowne kliknięcie CHECKLIST wraca do ostatnio wybranej checklisty; zaznaczenia są w przeglądarce.
      // render zwraca chk: destroy() przy przejściu do innej podzakładki, spóźnione dane już nic nie rysują
      { id: "checklist", label: "CHECKLIST", fill: true, render: (pane) => {
        docs = null;
        chk = mountChecklists(pane, { start: chkId, onPick: (id, fix) => {
          chkId = id;
          remember("other", argOf(), { replace: !!fix });
        } });
        return chk;
      } },
    ], { arg: argOf });
    return {
      // arg undefined (przycisk menu): zostaje otwarta podzakładka i dokument; "docs/LOA/plik.pdf" → DOCS z tym plikiem
      activate(arg) {
        if (arg !== undefined) {
          const [id, ...rest] = arg.split("/");
          if (id === "phraseology") {
            if (sub.current() !== "phraseology") sub.show("phraseology");
          } else if (id === "checklist") {
            chkId = rest.join("/");
            // render otwiera CHECKLIST od razu z tą checklistą
            if (sub.current() === "checklist" && chk) chk.pick(chkId);
            else sub.show("checklist");
          } else {
            const f = arg.startsWith("docs/") ? arg.slice("docs/".length) : "";
            // przekierowanie w activate(): app.js zapisuje adres COORDINATION w tym samym kroku historii
            if (isCoordFile(f)) return navigate("coordination", "docs/" + f);
            file = f;
            // render otwiera DOCS od razu z tym plikiem
            if (sub.current() === "docs" && docs) docs.pick(file);
            else sub.show("docs");
          }
        }
        // menu: bieżący stan do adresu (bez nowego kroku)
        remember("other", argOf());
      },
    };
  },
};
