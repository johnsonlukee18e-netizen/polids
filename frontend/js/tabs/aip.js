import { api, esc, frameGo, h, iframeWithFallback, remember, subtabs } from "../api.js";

const NOTE = "If the page does not show, it blocks embedding \u2013 use the button next to it.";

// Pasek nad ramką w jednej linii: długi adres i uwaga skracane wielokropkiem, pełny tekst w dymku
export function embedBar(pane) {
  const bar = pane.querySelector(".toolbar");
  bar.classList.add("embed-bar");
  bar.querySelectorAll(".hint").forEach((el) => { el.title = el.textContent; });
}

// AD CIV: lotniska z częścią AD 2 eAIP IFR (lista AD 1.3, AIRAC AMDT 10-26), nazwy jak w AIP
export const AD2 = [["EPBY", "BYDGOSZCZ"], ["EPGD", "GDA\u0143SK IM. LECHA WA\u0141\u0118SY"], ["EPKK", "KRAK\u00d3W/Balice"],
  ["EPKT", "KATOWICE - PYRZOWICE"], ["EPLB", "LUBLIN"], ["EPLL", "\u0141\u00d3D\u0179"], ["EPMO", "WARSZAWA/Modlin"],
  ["EPPO", "POZNA\u0143/\u0141awica"], ["EPRA", "WARSZAWA - RADOM"], ["EPRZ", "RZESZ\u00d3W - JASIONKA"], ["EPSC", "SZCZECIN/Goleni\u00f3w"],
  ["EPSY", "OLSZTYN - MAZURY"], ["EPWA", "LOTNISKO CHOPINA W WARSZAWIE"], ["EPWR", "WROC\u0141AW - STRACHOWICE"],
  ["EPZG", "ZIELONA G\u00d3RA/Babimost"]];
// AD MIL (0.13.1, issue #25): lotniska z częścią MIL AD 4 eAIP MIL (lista AD 1.3, AIRAC AMDT 11-26), nazwy jak w AIP
export const AD_MIL = [["EPCE", "CEWICE"], ["EPDA", "DAR\u0141OWO"], ["EPDE", "D\u0118BLIN"], ["EPIR", "INOWROC\u0141AW"],
  ["EPKS", "POZNA\u0143/Krzesiny"], ["EPLK", "\u0141ASK"], ["EPLY", "\u0141\u0118CZYCA"], ["EPMB", "MALBORK"], ["EPMI", "MIROS\u0141AWIEC"],
  ["EPMM", "MI\u0143SK MAZOWIECKI"], ["EPOK", "OKSYWIE"], ["EPPR", "PRUSZCZ GDA\u0143SKI"], ["EPPW", "POWIDZ"], ["EPSN", "\u015aWIDWIN"],
  ["EPTM", "TOMASZ\u00d3W MAZOWIECKI"]];
// AD VFR (0.13.1): lotniska z częścią AD 4 eAIP VFR (lista AD 1, AIRAC AMDT 11-26), nazwy jak w AIP
// (EPIN w VFR i EPIR w MIL to oba INOWROCŁAW: rozróżnia je kod)
export const AD_VFR = [["EPBA", "ALEKSANDROWICE k/Bielska-Bia\u0142ej"], ["EPBC", "WARSZAWA - BABICE"],
  ["EPBH", "BYDGOSZCZ BAZA LPR"], ["EPBK", "BIA\u0141YSTOK KRYWLANY"], ["EPBO", "BORSK"], ["EPCD", "DEPU\u0141TYCZE KR\u00d3LEWSKIE"],
  ["EPEL", "ELBL\u0104G"], ["EPGE", "GI\u017bE"], ["EPGI", "LISIE K\u0104TY k/Grudzi\u0105dza"], ["EPGL", "GLIWICE"], ["EPGY", "GR\u0104DY"],
  ["EPIN", "INOWROC\u0141AW"], ["EPJG", "JELENIA G\u00d3RA"], ["EPJS", "JE\u017b\u00d3W SUDECKI k/Jeleniej G\u00f3ry"], ["EPKA", "MAS\u0141\u00d3W k/Kielc"],
  ["EPKC", "KRAK\u00d3W - CZY\u017bYNY"], ["EPKE", "K\u0118TRZYN"], ["EPKG", "BAGICZ k/Ko\u0142obrzegu"], ["EPKH", "KOSZALIN BAZA LPR"],
  ["EPKI", "KIKITY"], ["EPKM", "KATOWICE MUCHOWIEC"], ["EPKO", "KORNE"], ["EPKP", "POBIEDNIK k/Krakowa"],
  ["EPKR", "KROSNO"], ["EPKW", "KANI\u00d3W"], ["EPKX", "KRAK\u00d3W BAZA LPR"], ["EPLI", "LINOWIEC"], ["EPLR", "RADAWIEC k/Lublina"],
  ["EPLS", "LESZNO"], ["EPLU", "LUBIN"], ["EPML", "MIELEC"], ["EPMR", "MIROS\u0141AWICE"], ["EPMX", "MILEWO"],
  ["EPMY", "MY\u015aLIB\u00d3RZ - GI\u017bYN"], ["EPNC", "CHRCYNNO"], ["EPNL", "\u0141OSOSINA DOLNA k/Nowego S\u0105cza"], ["EPNT", "NOWY TARG"],
  ["EPOD", "DAJTKI k/Olsztyna"], ["EPOM", "MICHA\u0141K\u00d3W k/Ostrowa Wlkp."], ["EPOP", "POLSKA NOWA WIE\u015a k/Opola"],
  ["EPPB", "POZNA\u0143 - BEDNARY"], ["EPPG", "K\u0104KOLEWO"], ["EPPI", "PI\u0141A"], ["EPPK", "POZNA\u0143/Kobylnica"], ["EPPL", "P\u0141OCK"],
  ["EPPT", "PIOTRK\u00d3W TRYBUNALSKI"], ["EPPZ", "PRZASNYSZ"], ["EPRD", "MAZURY AIR CAMP"], ["EPRG", "GOTARTOWICE k/Rybnika"],
  ["EPRJ", "RZESZ\u00d3W"], ["EPRP", "PIAST\u00d3W k/Radomia"], ["EPRU", "RUDNIKI k/Cz\u0119stochowy"], ["EPSA", "SANOK - BAZA"],
  ["EPSD", "SZCZECIN D\u0104BIE"], ["EPSK", "KR\u0118PA k/S\u0142upska"], ["EPSL", "\u015aWIDNIK k/LUBLINA"], ["EPSS", "\u015aWIDNICA - KRZCZON\u00d3W"],
  ["EPST", "TURBIA k/Stalowej Woli"], ["EPSU", "SUWA\u0141KI"], ["EPSW", "\u015aWIDNIK"], ["EPTO", "TORU\u0143"],
  ["EPWK", "KRUSZYN k/W\u0142oc\u0142awka"], ["EPWS", "SZYMAN\u00d3W"], ["EPWT", "WATOROWO"], ["EPZA", "ZAMO\u015a\u0106"], ["EPZE", "\u017bERNIKI"],
  ["EPZP", "PRZYLEP k/Zielonej G\u00f3ry"], ["EPZR", "\u017bAR k/\u017bywca"], ["EPZW", "ZAWISZYN"]];

// Trzy zakładki, trzy pakiety eAIP (0.13.1): link w /api/config, pakiet w GET /api/docs/charts/<api>/<ICAO>, część AIP
// ze stroną lotniska (AD 2 w IFR, AD 4 w MIL i VFR), sekcja z mapami, zakres sekcji opisu, lista lotnisk, dymek "eAIP"
export const AIP = {
  adciv: { link: "aip_ifr", api: "ifr", part: 2, charts: "2.24", text: "2.1\u2013AD 2.25", list: AD2,
    whole: "The whole eAIP IFR (table of contents)" },
  admil: { link: "aip_mil", api: "mil", part: 4, charts: "4.24", text: "4.1\u2013AD 4.25", list: AD_MIL,
    whole: "The whole eAIP MIL (table of contents)" },
  advfr: { link: "aip_vfr", api: "vfr", part: 4, charts: "4.13", text: "4.1\u2013AD 4.13", list: AD_VFR,
    whole: "The whole eAIP VFR (table of contents)" },
};

// Strona AD 2 lotniska (AD 2.1–2.25, mapy w AD 2.24) z tej samej poprawki co skonfigurowany index-v2.html:
// ".../AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html" → ".../AIRAC%20AMDT%2010-26_2026_10_01/eAIP/AD%202%20EPWA%201-en-GB.html".
// part 4: strona AD 4 lotniska eAIP MIL / VFR (".../eAIP/AD%204%20EPKS%201-en-GB.html").
// Adres katalogu bez "/" na końcu (np. wpisany w .env) traktujemy jak katalog; brak albo zły adres → "".
// Od 0.12.5 to tylko przycisk "AD 2 TEXT ↗": przycisk lotniska otwiera listę map (issue #18).
export function aeroPageUrl(base, icao, part = 2) {
  try {
    const u = new URL(base);
    if (!u.pathname.endsWith("/") && !/\.[a-z0-9]+$/i.test(u.pathname)) u.pathname += "/";
    return new URL(`eAIP/AD ${part} ${icao} 1-en-GB.html`, u).href;
  } catch {
    return "";
  }
}
// strona AD 2 przewinięta do nagłówka AD 2.24 (sect: "4.24" w MIL, "4.13" w VFR; fragment tekstowy, przeglądarki
// Chromium, Safari, Firefox 131+)
export const chartsSectionUrl = (page, icao, sect = "2.24") =>
  (page ? `${page}#:~:text=${encodeURIComponent(`${icao} AD ${sect}`)}` : "");

// arg adresu "#adciv/EPWA" albo "#adciv/EPWA/2-1" (mapa) → {icao, chart}; wielkość liter dowolna; lotnisko spoza
// listy zakładki (list: AD2, AD_MIL, AD_VFR), inny tekst albo "" → {icao: "", chart: ""} (cały eAIP)
export function aipArg(list, arg) {
  const [a = "", c = ""] = String(arg ?? "").trim().split("/");
  const icao = a.trim().toUpperCase();
  if (!list.some(([i]) => i === icao)) return { icao: "", chart: "" };
  return { icao, chart: /^\d{1,2}-\d{1,3}$/.test(c.trim()) ? c.trim() : "" };
}
// AD CIV; jeden argument (wywołania .map(adcivArg) i .map(aeroOf) dają drugim argumentem numer elementu)
export const adcivArg = (arg) => aipArg(AD2, arg);
export const aeroOf = (arg) => adcivArg(arg).icao;

// rodzaje map (kind z backendu, services/eaip.py: chart_kind) w kolejności przycisków filtra;
// 0.12.6: mapa lotniska (ADC) i mapy postojowe (APDC) osobno
export const KINDS = [["ADC", "Aerodrome, ground movement and areas of responsibility charts"],
  ["APDC", "Aircraft parking and docking charts"], ["SID", "Standard instrument departure charts"],
  ["STAR", "Standard instrument arrival charts"], ["IAC", "Instrument approach charts"], ["VFR", "Visual approach and VFR charts"],
  ["OBST", "Obstacle and terrain charts"], ["OTHER", "Other charts"]];
const KIND_TIP = Object.fromEntries(KINDS);

// lista map: przyciski rodzajów (ALL i rodzaje obecne na liście, z liczbą map) i wiersze mapy
export function kindButtons(charts, kind) {
  const n = (k) => charts.filter((c) => c.kind === k).length;
  return `<button type="button" class="gbtn chl-kind${kind ? "" : " on"}" data-kind="" title="All charts">ALL <small>${charts.length}</small></button>`
    + KINDS.filter(([k]) => n(k)).map(([k, tip]) => `<button type="button" class="gbtn chl-kind${kind === k ? " on" : ""}" data-kind="${k}"`
      + ` title="${esc(tip)}">${k} <small>${n(k)}</small></button>`).join("");
}
// filtr rodzaju po wyborze mapy spoza filtra (adres, historia ←, pierwsze wczytanie z mapą w adresie): mapa ukryta
// filtrem go wyłącza (""), mapa tego rodzaju albo filtr ALL go zostawia; id "" albo nieznane = pierwsza mapa listy.
// Kliknięcie przycisku filtra go nie wywołuje (filtr działa także, gdy wybrana mapa jest innego rodzaju).
export function kindAfterPick(charts, kind, id) {
  const c = charts.find((x) => x.id === id) || charts[0];
  return kind && c && c.kind !== kind ? "" : kind;
}
// wiersz: krótka nazwa mapy (title), pełny tytuł (full) w dymku
export const chartTip = (c) => `${c.page}: ${c.full || c.title}`;
export function chartRows(charts, { kind = "", selected = "" } = {}) {
  const list = charts.filter((c) => !kind || c.kind === kind);
  if (!list.length) return `<p class="hint">No charts of this type.</p>`;
  return list.map((c) => `<div class="chl-row${c.id === selected ? " on" : ""}" data-chart="${esc(c.id)}" tabindex="0" title="${esc(chartTip(c))}">
    <span class="chl-kd" title="${esc(KIND_TIP[c.kind] || c.kind)}">${esc(c.kind)}</span><span class="chl-tt">${esc(c.title)}</span>
    <a class="chl-pdf" href="${esc(c.url)}" target="_blank" rel="noopener" title="Open ${esc(c.page)} (PDF) in a new tab">PDF \u2197</a></div>`).join("");
}

// lista map lotniska (GET /api/docs/charts/<ifr|mil|vfr>/<ICAO>: AD 2.24 eAIP IFR, AD 4.24 MIL, AD 4.13 VFR) z PDF-em
// obok; pkg = wpis z AIP (domyślnie AD CIV); chart = mapa z adresu ("" = pierwsza), onPick(id) po kliknięciu mapy
// (krok historii)
// pakiet/ICAO → { t, d }: odpowiedź serwera bez ponownego pobierania przy powrocie do lotniska; po godzinie pytamy znowu
// (serwer i tak trzyma listę 6 h, a sesja przez zmianę AIRAC dostaje wtedy nowe PDF-y)
const cache = new Map();
const CACHE_MS = 3600 * 1000;
export function mountCharts(pane, { icao, name, base, chart = "", onPick = () => {}, pkg = AIP.adciv }) {
  const text = aeroPageUrl(base, icao, pkg.part);
  const key = `${pkg.api}/${icao}`;
  const el = h(`<div class="mapwrap chl-wrap">
    <div class="mapside">
      <div class="ms-card"><h4>${esc(icao)} \u00b7 CHARTS</h4>
        <div class="chl-name">${esc(name)}</div>
        <div class="chl-kinds"></div>
        <div class="chl-list"><p class="hint">Loading the chart list\u2026</p></div></div>
      <div class="chl-act">
        <a class="btn chl-open" target="_blank" rel="noopener" hidden>PDF \u2197</a>
        <a class="btn" href="${esc(text)}" target="_blank" rel="noopener" title="AD ${pkg.part} ${esc(icao)}: aerodrome textual data (AD ${pkg.text})">AD ${pkg.part} TEXT \u2197</a>
      </div>
    </div>
    <iframe class="embed viewer" style="background:#333" title="Chart"></iframe>
  </div>`);
  pane.append(el);
  const $ = (s) => el.querySelector(s);
  let viewer = $(".viewer"), data = null, kind = "", sel = chart;
  const draw = () => {
    if (!data) return;
    const charts = data.charts || [];
    if (!charts.length) {
      const sec = chartsSectionUrl(data.page || text, icao, pkg.charts);
      $(".chl-kinds").innerHTML = "";
      $(".chl-list").innerHTML = `<p class="error">Chart list unavailable: ${esc(data.error || "no charts")}.</p>`
        + (sec ? `<p><a class="btn" href="${esc(sec)}" target="_blank" rel="noopener" title="Aerodrome charts section (AD ${pkg.charts})">AD ${pkg.charts} \u2197</a></p>` : "");
      if (text && viewer.getAttribute("src") !== text) viewer = frameGo(viewer, text);
      return;
    }
    const c = charts.find((x) => x.id === sel) || charts[0];
    const label = c.page || `AD ${pkg.part} ${icao} ${c.id}`;
    sel = c.id;
    $(".chl-kinds").innerHTML = kindButtons(charts, kind);
    $(".chl-list").innerHTML = chartRows(charts, { kind, selected: sel });
    $(".chl-list .chl-row.on")?.scrollIntoView({ block: "nearest" });
    const open = $(".chl-open");
    open.hidden = false;
    open.href = c.url;
    open.title = chartTip({ ...c, page: label });
    open.textContent = `${label} PDF \u2197`;
    if (viewer.getAttribute("src") !== c.url) viewer = frameGo(viewer, c.url);
  };
  el.addEventListener("click", (e) => {
    const k = e.target.closest(".chl-kind");
    if (k) { kind = k.dataset.kind; draw(); return; }
    const row = e.target.closest(".chl-row");
    if (!row || e.target.closest("a")) return;
    if (row.dataset.chart !== sel) { sel = row.dataset.chart; draw(); onPick(sel); }
  });
  el.addEventListener("keydown", (e) => {
    const row = e.target.closest?.(".chl-row");
    if (row && e.target === row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); row.click(); }
  });
  // filtr (kind) zmieniają tylko przyciski filtra i wybór mapy spoza filtra (pick, pierwsze wczytanie), nie draw()
  const picked = (id) => { if (data?.charts?.length) kind = kindAfterPick(data.charts, kind, id); };
  const got = (d) => { data = d; if (!d.error) cache.set(key, { t: Date.now(), d }); picked(sel); draw(); };
  const hit = cache.get(key);
  if (hit && Date.now() - hit.t < CACHE_MS) got(hit.d);
  else api(`/api/docs/charts/${pkg.api}/${icao}`).then(got).catch((e) => got({ page: text, charts: [], error: e.message }));
  // mapa z adresu (←, Wstecz): "" = pierwsza
  return { pick(id) { sel = id; picked(id); draw(); }, current: () => sel };
}

const EAIP = "eaip";   // id przycisku ca\u0142ej przegl\u0105darki eAIP

// AD CIV / AD MIL / AD VFR: podmenu jak w PANDORZE: "eAIP" (cała przeglądarka index-v2.html pakietu) i przycisk dla
// każdego lotniska z listy, który otwiera listę map lotniska z PDF-em obok (AD CIV od 0.12.5, issue #18; AD MIL i AD VFR
// od 0.13.1, issue #25, wcześniej tylko cała przeglądarka). Adres "#adciv/EPWA" (pierwsza mapa) albo "#admil/EPKS/12-5",
// "#advfr" = cała przeglądarka; kliknięcie lotniska albo mapy to krok do cofnięcia (←). AD VFR ma 69 lotnisk: podmenu
// przewija się, a przycisk lotniska z adresu (←, link) jest przewijany do widoku.
function aipTab(tab) {
  const pkg = AIP[tab];
  return {
    mount(root, ctx) {
      const base = ctx.config.links[pkg.link];
      const names = Object.fromEntries(pkg.list);
      let charts = null, want = "";   // want: mapa z adresu dla lotniska, kt\u00f3rego lista dopiero powstanie
      const argOf = (id) => (id === EAIP ? "" : id);
      const page = (url) => (pane) => { charts = null; iframeWithFallback(pane, url, NOTE); embedBar(pane); };
      const chartsPage = (icao) => (pane) => {
        pane.classList.add("chl-pane");
        charts = mountCharts(pane, { icao, name: names[icao], base, chart: want, pkg,
          onPick: (id) => remember(tab, `${icao}/${id}`) });
        want = "";
        return { destroy() { charts = null; } };
      };
      const sub = subtabs(root, [
        { id: EAIP, label: "eAIP", fill: true, render: page(base) },
        { sep: true },
        ...pkg.list.map(([icao]) => ({ id: icao, label: icao, fill: true, render: chartsPage(icao) })),
      ], { arg: argOf });
      sub.nav.querySelectorAll("button[data-id]").forEach((b) => {
        b.title = b.dataset.id === EAIP ? pkg.whole : `${names[b.dataset.id]} \u2013 charts`;
      });
      // wybrany przycisk widoczny w przewijanym podmenu (AD VFR: lotnisko z dołu listy z adresu albo po ←); przy
      // pierwszym (eAIP) podmenu wraca na samą górę, razem z odstępem nad przyciskiem
      const reveal = () => {
        const b = sub.nav.querySelector("button.active");
        if (b === sub.nav.querySelector("button")) sub.nav.scrollTop = 0;
        else b?.scrollIntoView({ block: "nearest" });
      };
      return {
        // arg undefined (przycisk menu): zostaje otwarta strona; "" = cały eAIP; "EPWA" = mapy EPWA; "EPWA/2-1" = mapa
        activate(arg) {
          if (arg !== undefined) {
            const a = aipArg(pkg.list, arg);
            const id = a.icao || EAIP;
            if (sub.current() !== id) { want = a.chart; sub.show(id); } else if (charts && a.chart !== charts.current()) charts.pick(a.chart);
          }
          reveal();
          const cur = sub.current();
          remember(tab, cur === EAIP ? "" : charts?.current() ? `${cur}/${charts.current()}` : cur);
        },
      };
    },
  };
}
export const adciv = aipTab("adciv");
export const admil = aipTab("admil");
export const advfr = aipTab("advfr");
