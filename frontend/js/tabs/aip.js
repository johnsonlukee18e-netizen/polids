import { api, esc, frameGo, h, iframeWithFallback, remember, subtabs } from "../api.js";

const NOTE = "If the page does not show, it blocks embedding – use the button next to it.";

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
// Od 0.12.5 to tylko przycisk "AD 2 TEXT ↗": przycisk lotniska otwiera listę map (issue #18).
export function aeroPageUrl(base, icao) {
  try {
    const u = new URL(base);
    if (!u.pathname.endsWith("/") && !/\.[a-z0-9]+$/i.test(u.pathname)) u.pathname += "/";
    return new URL(`eAIP/AD 2 ${icao} 1-en-GB.html`, u).href;
  } catch {
    return "";
  }
}
// strona AD 2 przewinięta do nagłówka AD 2.24 (fragment tekstowy, przeglądarki Chromium, Safari, Firefox 131+)
export const chartsSectionUrl = (page, icao) => (page ? `${page}#:~:text=${encodeURIComponent(`${icao} AD 2.24`)}` : "");

// arg adresu "#adciv/EPWA" albo "#adciv/EPWA/2-1" (mapa) → {icao, chart}; wielkość liter dowolna;
// inny tekst albo "" → {icao: "", chart: ""} (cały eAIP)
export function adcivArg(arg) {
  const [a = "", c = ""] = String(arg ?? "").trim().split("/");
  const icao = a.trim().toUpperCase();
  if (!AD2.some(([i]) => i === icao)) return { icao: "", chart: "" };
  return { icao, chart: /^\d{1,2}-\d{1,3}$/.test(c.trim()) ? c.trim() : "" };
}
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
    <a class="chl-pdf" href="${esc(c.url)}" target="_blank" rel="noopener" title="Open ${esc(c.page)} (PDF) in a new tab">PDF ↗</a></div>`).join("");
}

// lista map lotniska (GET /api/docs/charts/<ICAO>, AD 2.24 eAIP) z PDF-em obok; chart = mapa z adresu ("" = pierwsza),
// onPick(id) po kliknięciu mapy (krok historii)
// ICAO → { t, d }: odpowiedź serwera bez ponownego pobierania przy powrocie do lotniska; po godzinie pytamy znowu
// (serwer i tak trzyma listę 6 h, a sesja przez zmianę AIRAC dostaje wtedy nowe PDF-y)
const cache = new Map();
const CACHE_MS = 3600 * 1000;
export function mountCharts(pane, { icao, name, base, chart = "", onPick = () => {} }) {
  const text = aeroPageUrl(base, icao);
  const el = h(`<div class="mapwrap chl-wrap">
    <div class="mapside">
      <div class="ms-card"><h4>${esc(icao)} · CHARTS</h4>
        <div class="chl-name">${esc(name)}</div>
        <div class="chl-kinds"></div>
        <div class="chl-list"><p class="hint">Loading the chart list…</p></div></div>
      <div class="chl-act">
        <a class="btn chl-open" target="_blank" rel="noopener" hidden>PDF ↗</a>
        <a class="btn" href="${esc(text)}" target="_blank" rel="noopener" title="AD 2 ${esc(icao)}: aerodrome textual data (AD 2.1–AD 2.25)">AD 2 TEXT ↗</a>
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
      const sec = chartsSectionUrl(data.page || text, icao);
      $(".chl-kinds").innerHTML = "";
      $(".chl-list").innerHTML = `<p class="error">Chart list unavailable: ${esc(data.error || "no charts")}.</p>`
        + (sec ? `<p><a class="btn" href="${esc(sec)}" target="_blank" rel="noopener" title="Aerodrome charts section (AD 2.24)">AD 2.24 ↗</a></p>` : "");
      if (text && viewer.getAttribute("src") !== text) viewer = frameGo(viewer, text);
      return;
    }
    const c = charts.find((x) => x.id === sel) || charts[0];
    const label = c.page || `AD 2 ${icao} ${c.id}`;
    sel = c.id;
    $(".chl-kinds").innerHTML = kindButtons(charts, kind);
    $(".chl-list").innerHTML = chartRows(charts, { kind, selected: sel });
    $(".chl-list .chl-row.on")?.scrollIntoView({ block: "nearest" });
    const open = $(".chl-open");
    open.hidden = false;
    open.href = c.url;
    open.title = chartTip({ ...c, page: label });
    open.textContent = `${label} PDF ↗`;
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
  const got = (d) => { data = d; if (!d.error) cache.set(icao, { t: Date.now(), d }); picked(sel); draw(); };
  const hit = cache.get(icao);
  if (hit && Date.now() - hit.t < CACHE_MS) got(hit.d);
  else api(`/api/docs/charts/${icao}`).then(got).catch((e) => got({ page: text, charts: [], error: e.message }));
  // mapa z adresu (←, Wstecz): "" = pierwsza
  return { pick(id) { sel = id; picked(id); draw(); }, current: () => sel };
}

const EAIP = "eaip";   // id przycisku całej przeglądarki eAIP

// AD CIV: podmenu jak w PANDORZE: "eAIP" (cała przeglądarka index-v2.html) i przycisk dla każdego lotniska AD 2,
// który otwiera listę map lotniska (AD 2.24) z PDF-em obok (0.12.5, issue #18: lista map zamiast opisu tekstowego).
// Adres "#adciv/EPWA" (pierwsza mapa) albo "#adciv/EPWA/2-1", "#adciv" = cała przeglądarka; kliknięcie lotniska albo
// mapy to krok do cofnięcia (←).
export const adciv = {
  mount(root, ctx) {
    const base = ctx.config.links.aip_ifr;
    const names = Object.fromEntries(AD2);
    let charts = null, want = "";   // want: mapa z adresu dla lotniska, którego lista dopiero powstanie
    const argOf = (id) => (id === EAIP ? "" : id);
    const page = (url) => (pane) => { charts = null; iframeWithFallback(pane, url, NOTE); embedBar(pane); };
    const chartsPage = (icao) => (pane) => {
      pane.classList.add("chl-pane");
      charts = mountCharts(pane, { icao, name: names[icao], base, chart: want,
        onPick: (id) => remember("adciv", `${icao}/${id}`) });
      want = "";
      return { destroy() { charts = null; } };
    };
    const sub = subtabs(root, [
      { id: EAIP, label: "eAIP", fill: true, render: page(base) },
      { sep: true },
      ...AD2.map(([icao]) => ({ id: icao, label: icao, fill: true, render: chartsPage(icao) })),
    ], { arg: argOf });
    sub.nav.querySelectorAll("button[data-id]").forEach((b) => {
      b.title = b.dataset.id === EAIP ? "The whole eAIP IFR (table of contents)" : `${names[b.dataset.id]} – charts`;
    });
    return {
      // arg undefined (przycisk menu): zostaje otwarta strona; "" = cały eAIP; "EPWA" = mapy EPWA; "EPWA/2-1" = mapa
      activate(arg) {
        if (arg !== undefined) {
          const a = adcivArg(arg);
          const id = a.icao || EAIP;
          if (sub.current() !== id) { want = a.chart; sub.show(id); } else if (charts && a.chart !== charts.current()) charts.pick(a.chart);
        }
        const cur = sub.current();
        remember("adciv", cur === EAIP ? "" : charts?.current() ? `${cur}/${charts.current()}` : cur);
      },
    };
  },
};
export const admil = frame("aip_mil");
export const advfr = frame("aip_vfr");
