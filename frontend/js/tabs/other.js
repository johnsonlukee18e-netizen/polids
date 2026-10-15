import { navigate, remember, subtabs } from "../api.js";
import { isCoordFile, mountDocs } from "../docs.js";
import { mountPhraseology } from "../phraseology.js";

// OTHER: podmenu jak w METEO: DOCS (PDF-y z data/docs/) i PHRASEOLOGY (do 0.12.2 osobna zakładka menu).
// Adresy "#other/docs/<plik w data/docs>" (bez pliku: pierwszy dokument) i "#other/phraseology";
// stare "#docs/<plik>" i "#phraseology" przekierowuje app.js. LOA i LOP (do 0.12.2 w DOCS, np. z RADIO) otwiera
// COORDINATION › DOKUMENTY: "#other/docs/LOA/<plik>" i "#docs/LOA/<plik>" → "#coordination/docs/LOA/<plik>".
export default {
  mount(root, ctx) {
    let docs = null, file = "";   // file: dokument z adresu albo kliknięty na liście ("" = pierwszy)
    let sub = null;
    const argOf = (id = sub?.current()) => (id === "phraseology" ? "phraseology" : file ? `docs/${file}` : "docs");
    sub = subtabs(root, [
      // ponowne kliknięcie DOCS wczytuje listę od nowa, z tym samym dokumentem
      { id: "docs", label: "DOCS", fill: true, render: (pane) => {
        docs = mountDocs(pane, ctx, { start: file, onPick: (f) => { file = f; remember("other", argOf()); } });
      } },
      { id: "phraseology", label: "PHRASEOLOGY", fill: true, render: (pane) => { docs = null; mountPhraseology(pane, ctx); } },
    ], { arg: argOf });
    return {
      // arg undefined (przycisk menu): zostaje otwarta podzakładka i dokument; "docs/LOA/plik.pdf" → DOCS z tym plikiem
      activate(arg) {
        if (arg !== undefined) {
          if (arg.split("/")[0] === "phraseology") {
            if (sub.current() !== "phraseology") sub.show("phraseology");
          } else {
            const f = arg.startsWith("docs/") ? arg.slice("docs/".length) : "";
            // przekierowanie w activate(): app.js zapisuje adres COORDINATION w tym samym kroku historii
            if (isCoordFile(f)) return navigate("coordination", "docs/" + f);
            file = f;
            if (sub.current() === "docs" && docs) docs.pick(file);
            else sub.show("docs");   // render otwiera DOCS od razu z tym plikiem
          }
        }
        remember("other", argOf());   // menu: bieżący stan do adresu (bez nowego kroku)
      },
    };
  },
};
