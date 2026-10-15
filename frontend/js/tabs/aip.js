import { h, iframeWithFallback, remember, subtabs } from "../api.js";

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

// AD CIV: lotniska z częścią AD 2 eAIP IFR (lista AD 1.3, AIRAC AMDT 10-26), nazwy jak w AIP
export const AD2 = [["EPBY", "BYDGOSZCZ"], ["EPGD", "GDAŃSK IM. LECHA WAŁĘSY"], ["EPKK", "KRAKÓW/Balice"],
  ["EPKT", "KATOWICE - PYRZOWICE"], ["EPLB", "LUBLIN"], ["EPLL", "ŁÓDŹ"], ["EPMO", "WARSZAWA/Modlin"],
  ["EPPO", "POZNAŃ/Ławica"], ["EPRA", "WARSZAWA - RADOM"], ["EPRZ", "RZESZÓW - JASIONKA"], ["EPSC", "SZCZECIN/Goleniów"],
  ["EPSY", "OLSZTYN - MAZURY"], ["EPWA", "LOTNISKO CHOPINA W WARSZAWIE"], ["EPWR", "WROCŁAW - STRACHOWICE"],
  ["EPZG", "ZIELONA GÓRA/Babimost"]];

// Strona AD 2 lotniska (AD 2.1–2.25, mapy w AD 2.24) z tej samej poprawki co skonfigurowany index-v2.html:
// ".../AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html" → ".../AIRAC%20AMDT%2010-26_2026_10_01/eAIP/AD%202%20EPWA%201-en-GB.html".
// Adres katalogu bez "/" na końcu (np. wpisany w .env) traktujemy jak katalog; brak albo zły adres → "".
export function aeroPageUrl(base, icao) {
  try {
    const u = new URL(base);
    if (!u.pathname.endsWith("/") && !/\.[a-z0-9]+$/i.test(u.pathname)) u.pathname += "/";
    return new URL(`eAIP/AD 2 ${icao} 1-en-GB.html`, u).href;
  } catch {
    return "";
  }
}

// arg adresu "#adciv/EPWA" → "EPWA" (wielkość liter dowolna); inny tekst albo "" → "" (cały eAIP)
export function aeroOf(arg) {
  const icao = String(arg ?? "").trim().toUpperCase();
  return AD2.some(([i]) => i === icao) ? icao : "";
}

const EAIP = "eaip";   // id przycisku całej przeglądarki eAIP

// AD CIV: podmenu jak w PANDORZE: "eAIP" (cała przeglądarka index-v2.html) i przycisk dla każdego lotniska AD 2,
// który otwiera w tej samej ramce stronę AD 2 lotniska, bez szukania w spisie treści. Adres "#adciv/EPWA",
// "#adciv" = cała przeglądarka; kliknięcie to krok do cofnięcia (←).
export const adciv = {
  mount(root, ctx) {
    const base = ctx.config.links.aip_ifr;
    const argOf = (id) => (id === EAIP ? "" : id);
    const page = (url) => (pane) => { iframeWithFallback(pane, url, NOTE); embedBar(pane); };
    const sub = subtabs(root, [
      { id: EAIP, label: "eAIP", fill: true, render: page(base) },
      { sep: true },
      ...AD2.map(([icao]) => ({ id: icao, label: icao, fill: true, render: page(aeroPageUrl(base, icao)) })),
    ], { arg: argOf });
    const names = Object.fromEntries(AD2);
    sub.nav.querySelectorAll("button[data-id]").forEach((b) => {
      b.title = b.dataset.id === EAIP ? "eAIP IFR: cała przeglądarka (spis treści)" : `${names[b.dataset.id]} – AD 2 ${b.dataset.id}`;
    });
    return {
      // arg undefined (przycisk menu): zostaje otwarta strona; "" = cały eAIP; "EPWA" = AD 2 EPWA
      activate(arg) {
        if (arg !== undefined) {
          const id = aeroOf(arg) || EAIP;
          if (sub.current() !== id) sub.show(id);
        }
        remember("adciv", argOf(sub.current()));
      },
    };
  },
};
export const admil = frame("aip_mil");
export const advfr = frame("aip_vfr");
