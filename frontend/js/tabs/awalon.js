import { api, esc, h, lsGet, lsSet, ONLINE_EVENT, remember, subtabs } from "../api.js";
import { CL3, NO_DATA, SPEED_BANDS, altLabel, angleTxt, arrowRot, axisMax, axisTicks, bandOf, dirTxt, forecastFor, forecastNote,
  hwTxt, matrixRows, maxSpeed, nm, pointTip, rowLabel, speedTxt, windTip, windVec, xwTxt } from "../wind.js";

// AWALON (issue #23, jak strona AWALON w PANDORZE): wiatr od 0 do 10 000 ft AMSL co 1000 ft nad lotniskami IFR
// z częścią AD 2 eAIP (backend: services/awalon.py, ta sama lista co eaip.AD2_AERODROMES). Podmenu: ALL (wszystkie
// lotniska w jednej tabeli, domyślnie), potem lotniska alfabetycznie; adres #awalon/EPWA. Strona lotniska: wykres
// profilu (pasy w kolorze klasy prędkości, groty z wiatrem), tabela profilu i panel pasów przeniesiony z METEO › WIND
// (wiatr przy ziemi i na 3000 ft w punkcie podejścia, składowe dla pasów).
export const AWALON_AD = ["EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY",
  "EPWA", "EPWR", "EPZG"];
// prognoza godzinowa (backend trzyma ją 30 min): nowe dane, gdy te na ekranie mają ponad 10 min; sprawdzane co 30 s,
// przy każdym powrocie na AWALON (przycisk menu, Wstecz) i przy powrocie do karty przeglądarki
export const REFRESH = 10 * 60000;
export const TICK = 30000;
export const stale = (at, now = Date.now()) => !at || now - at > REFRESH;
const COLORS_KEY = "awalon.colors";
const STATUS_TIP = { METAR: "Observed surface wind", FCST: "Forecast", GND: "At or below aerodrome elevation", "N/A": "No data" };
const MINMAX_TIP = "Previous, current and next hour; SFC from METAR: variable sector";

// --- wykres profilu: oś wysokości 0–10K (każdy wiersz to pas ±500 ft wokół swojej wysokości), oś prędkości w węzłach
export const CHART = { w: 520, h: 320, l: 40, r: 30, t: 22, b: 34 };
const PW = CHART.w - CHART.l - CHART.r, PH = CHART.h - CHART.t - CHART.b;
const ALT_MIN = -500, ALT_MAX = 10500;
export const yOf = (ft) => CHART.t + ((ALT_MAX - ft) / (ALT_MAX - ALT_MIN)) * PH;
export const xOf = (kt, max) => CHART.l + (Math.min(Math.max(kt, 0), max) / max) * PW;
const r1 = (v) => Math.round(v * 10) / 10;

// miejsce wiersza na wykresie i w tabeli profilu: wiatr przy ziemi (SFC, wiersz 0 ft) na wysokości lotniska, czyli na
// miejscu najwyższego wiersza GND (EPKT 1008 ft: SFC w pasie 1K), a wiersze GND (ziemia) o jeden niżej, pod SFC;
// bez wierszy GND (lotnisko poniżej 1000 ft) wszystko na swojej wysokości
export function placeOf(profile) {
  const rows = profile || [];
  const top = Math.max(0, ...rows.filter((r) => r.kind === "gnd").map((r) => r.alt_ft));
  return (r) => (!r.alt_ft ? top : r.kind === "gnd" && top ? r.alt_ft - 1000 : r.alt_ft);
}

// model wykresu bez DOM (testy w Node): podziałki, pasy wierszy z klasą prędkości i groty (x = prędkość, obrót z wiatrem);
// at: wysokość pasa na osi (placeOf), ft: wiersz profilu
export function chartModel(profile) {
  const rows = profile || [];
  const max = axisMax(maxSpeed(rows));
  const band = PH / ((ALT_MAX - ALT_MIN) / 1000);
  const at = placeOf(rows);
  return {
    max,
    ticks: axisTicks(max).map((v) => ({ v, x: r1(xOf(v, max)) })),
    alts: rows.map((r) => ({ ft: r.alt_ft, label: altLabel(r.alt_ft), y: r1(yOf(r.alt_ft)) })),
    bands: rows.map((r) => {
      const has = r.speed !== null && r.speed !== undefined;
      const rot = has ? arrowRot(r.dir, r.speed) : null;
      const a = at(r);
      // pas GND to ziemia pod lotniskiem: dymek bez wysokości wiersza (pas może stać niżej niż jego wiersz)
      const tip = r.kind === "gnd" ? `GND: ${STATUS_TIP.GND.toLowerCase()}` : `${r.alt_ft ? `${r.alt_ft} ft` : "SFC"}: ${windTip(r)} \u00b7 ${r.status}`;
      return { ft: r.alt_ft, at: a, kind: r.kind, cls: bandOf(r.speed), y: r1(yOf(a + 500)), h: r1(band),
        x: has ? r1(xOf(r.speed, max)) : null, cy: r1(yOf(a)), rot, vrb: has && rot === null, tip };
    }),
  };
}

function chartSvg(profile) {
  const m = chartModel(profile), { l, t } = CHART, bottom = t + PH;
  const bands = m.bands.map((b) => `<g class="awl-row"><title>${esc(b.tip)}</title>
    <rect class="awl-band ${b.cls}" x="${l}" y="${b.y}" width="${PW}" height="${b.h}"></rect>
    ${b.kind === "gnd" ? `<text class="awl-gnd" x="${l + 6}" y="${b.cy + 4}">GND</text>` : ""}
    ${b.rot !== null ? `<path class="awl-arrow" d="M0 -6.5 L5 5 L0 2.2 L-5 5 Z" transform="translate(${b.x} ${b.cy}) rotate(${b.rot})"></path>` : ""}
    ${b.vrb ? `<circle class="awl-vrb" cx="${b.x}" cy="${b.cy}" r="3.5"></circle>` : ""}</g>`).join("");
  const seps = m.bands.slice(1).map((b) => `<line class="awl-sep" x1="${l}" x2="${l + PW}" y1="${r1(b.y + b.h)}" y2="${r1(b.y + b.h)}"></line>`).join("");
  const yl = m.alts.map((a) => `<text class="awl-ax" x="${l - 6}" y="${a.y + 4}" text-anchor="end">${a.label}</text>`).join("");
  const xl = m.ticks.map((k) => `<text class="awl-ax" x="${k.x}" y="${bottom + 22}" text-anchor="middle">${k.v}</text>`).join("");
  return `<svg class="awl-svg" viewBox="0 0 ${CHART.w} ${CHART.h}" width="${CHART.w}" height="${CHART.h}" role="img">
    <text class="awl-ax" x="${l - 6}" y="${t - 8}" text-anchor="end">ft</text>${bands}${seps}${yl}
    <line class="awl-axis" x1="${l}" x2="${l + PW}" y1="${bottom + 6}" y2="${bottom + 6}"></line>${xl}
    <text class="awl-ax" x="${l + PW + 12}" y="${bottom + 22}">kt</text></svg>`;
}

const legend = () => `<ul class="awl-legend">${[...SPEED_BANDS, NO_DATA].map((b) => `<li><i class="awl-sw ${b.id}"></i>${esc(b.label)}</li>`).join("")}</ul>`;
const colorsGet = () => lsGet(COLORS_KEY) !== "0";
// przełącznik "Show colors" (wybór zapamiętany): bez kolorów pasy i komórki w kolorze panelu
function colorsToggle(wrap) {
  const sw = h(`<label class="sw awl-colors"><input type="checkbox"${colorsGet() ? " checked" : ""}><span>Show colors</span></label>`);
  const set = (on) => wrap.classList.toggle("awl-plain", !on);
  sw.querySelector("input").addEventListener("change", (e) => { lsSet(COLORS_KEY, e.target.checked ? "1" : "0"); set(e.target.checked); });
  set(colorsGet());
  return sw;
}
const errLines = (d) => [d?.model_error, d?.metar_error].filter(Boolean).map((e) => `<p class="error">${esc(e)}</p>`).join("");

// --- ALL: jedna tabela, wiersze od 10K do SFC, kolumna na lotnisko; klik w kolumnę albo komórkę otwiera lotnisko
export const cellTxt = (r) => (!r ? "\u2013" : r.kind === "gnd" ? "GND" : windVec(r));
function allView(store, open) {
  return (pane) => {
    const wrap = h(`<div class="awl awl-allv">
      <div class="awl-bar"><span class="awl-for"></span><span class="awl-tg"></span><span class="hint">Click an aerodrome: wind profile chart and runways.</span></div>
      <div class="awl-errs"></div><div class="awl-all"></div>
      <div class="awl-foot">${legend()}<p class="hint">SFC: surface wind, METAR; <i>italic</i>: 10 m forecast (no METAR). GND: at or below aerodrome elevation. Altitudes AMSL.</p></div>
    </div>`);
    pane.append(wrap);
    wrap.querySelector(".awl-tg").append(colorsToggle(wrap));
    const draw = () => {
      const { data, err } = store.get();
      wrap.querySelector(".awl-for").innerHTML = `Forecast for: <span>${esc(forecastFor(data?.valid))}</span>`;
      wrap.querySelector(".awl-errs").innerHTML = err ? `<p class="error">${esc(err)}</p>` : errLines(data);
      const el = wrap.querySelector(".awl-all");
      if (!data) { el.innerHTML = err ? "" : `<p class="hint">Loading\u2026</p>`; return; }
      const ads = data.aerodromes || [];
      const head = ads.map((a) => `<th data-icao="${esc(a.icao)}" title="${esc(`${a.icao} ${a.name || ""}, elevation ${a.elevation_ft ?? "\u2013"} ft`)}">${esc(a.icao)}<small>${a.elevation_ft ?? "\u2013"} ft</small></th>`).join("");
      const body = matrixRows(data).map((row) => `<tr><th>${rowLabel(row.alt_ft)}</th>${row.cells.map((r, i) => {
        const a = ads[i], cls = ["awl-c", bandOf(r?.kind === "gnd" ? null : r?.speed), r?.status === "FCST" && !row.alt_ft ? "fc" : "", r?.gust ? "g" : ""];
        const tip = `${a.icao} ${row.alt_ft ? `${row.alt_ft} ft` : "SFC"}: ${windTip(r)} \u00b7 ${r?.status || "N/A"}`;
        return `<td class="${cls.filter(Boolean).join(" ")}" data-icao="${esc(a.icao)}" title="${esc(tip)}">${cellTxt(r)}</td>`;
      }).join("")}</tr>`).join("");
      el.innerHTML = `<table class="awl-mx"><thead><tr><th class="ft">ft</th>${head}</tr></thead><tbody>${body}</tbody></table>`;
    };
    wrap.querySelector(".awl-all").addEventListener("click", (e) => {
      const c = e.target.closest("[data-icao]");
      if (c) open(c.dataset.icao);
    });
    const off = store.sub(draw);
    draw();
    store.fresh();
    return { destroy: off };
  };
}

// --- strona lotniska: nagłówek, wykres z legendą, tabela profilu, panel pasów

// tabela profilu: stałe szerokości kolumn (table-layout: fixed w awalon.css), więc kolumny nie przesuwają się między
// lotniskami z porywem i bez; kwadrat klasy prędkości zawsze przy lewej krawędzi kolumny Speed, poryw we własnej
// kolumnie; kolejność wierszy jak na wykresie (SFC nad wierszami GND, placeOf)
export const PROF_COLS = [["Altitude", 76], ["Dir", 40], ["Speed", 72], ["Gust", 50], ["Status", 63], ["Min Angle", 84],
  ["Max Angle", 88], ["Min Spd", 68], ["Max Spd", 72]];
export function profileTable(profile) {
  const at = placeOf(profile);
  const rows = [...(profile || [])].sort((a, b) => at(b) - at(a)).map((r) => `<tr class="${r.kind}">
    <td>${r.alt_ft ? `${r.alt_ft} ft` : "SFC"}</td><td class="num">${dirTxt(r)}</td>
    <td class="num spd"><i class="awl-sw ${bandOf(r.kind === "gnd" ? null : r.speed)}"></i>${speedTxt(r.speed)}</td>
    <td class="num">${r.gust ? speedTxt(r.gust) : ""}</td>
    <td title="${esc(STATUS_TIP[r.status] || "")}">${esc(r.status)}</td>
    <td class="num">${angleTxt(r.min_dir)}</td><td class="num">${angleTxt(r.max_dir)}</td>
    <td class="num">${speedTxt(r.min_speed)}</td><td class="num">${speedTxt(r.max_speed)}</td></tr>`).join("");
  const th = ([t], i) => (i >= 5 ? `<th class="num" title="${MINMAX_TIP}">${t}</th>` : `<th${i && i !== 4 ? ' class="num"' : ""}>${t}</th>`);
  return `<colgroup>${PROF_COLS.map(([, w]) => `<col style="width:${w}px">`).join("")}</colgroup>
    <thead><tr>${PROF_COLS.map(th).join("")}</tr></thead>
    <tbody>${rows}</tbody>`;
}

// panel pasów: wiatr przy ziemi (METAR i prognoza 10 m nad lotniskiem) i na 3000 ft w punkcie podejścia każdego pasa,
// składowe względem kursu pasa; pas w użyciu z ATIS (litera ATIS) albo pas preferowany ("?")
export function rwyPanel(aw, inUse, err) {
  if (!aw) return `<p class="${err ? "error" : "hint"}">${esc(err || "Loading\u2026")}</p>`;
  const roles = (d) => ["arr", "dep"].filter((k) => inUse?.[k] === d);
  const tags = (d) => `<span class="awl-tags">${roles(d).map((k) => `<span class="awl-tag ${k}">${k.toUpperCase()}${inUse?.source === "ATIS" ? "" : "?"}</span>`).join("")}</span>`;
  const rows = aw.runways.map((r) => `<tr class="${roles(r.designator).join(" ")}" title="${esc(pointTip(r))}">
    <td class="rwy"><span>${esc(r.designator)}</span>${tags(r.designator)}</td>
    <td class="num">${hwTxt(r.c_metar.hw)}</td><td class="num">${xwTxt(r.c_metar.xw)}</td>
    <td class="num">${hwTxt(r.c_model.hw)}</td><td class="num">${xwTxt(r.c_model.xw)}</td>
    <td class="pt ${r.method}">${esc(r.fix || CL3)} <small>${nm(r.dist_nm)} NM</small></td>
    <td class="num w">${windVec(r.w3000)}</td><td class="num">${hwTxt(r.c3000.hw)}</td><td class="num">${xwTxt(r.c3000.xw)}</td></tr>`).join("");
  const use = inUse ? (inUse.source === "ATIS" ? `ARR/DEP: RWY in use \u00b7 ${esc(`ATIS ${inUse.letter || ""}`.trim())}.` : "ARR?/DEP?: preferred runway.") : "";
  return `<div class="awl-sfc"><span><span class="k">0 ft METAR</span><span class="v">${windVec(aw.metar_wind)}</span></span>
    <span><span class="k">10 m FCST</span><span class="v">${windVec(aw.model_surface)}</span></span></div>
    <table class="data awl-rt"><thead><tr><th rowspan="2">RWY</th><th colspan="2">0 ft METAR</th><th colspan="2">10 m FCST</th><th colspan="4">3000 ft approach</th></tr>
      <tr><th>H/T</th><th>XW</th><th>H/T</th><th>XW</th><th>Point</th><th>Wind</th><th>H/T</th><th>XW</th></tr></thead><tbody>${rows}</tbody></table>
    ${errLines(aw)}
    ${forecastNote(aw) ? `<p class="wnd-note">${esc(forecastNote(aw))}</p>` : ""}
    <p class="wnd-note">${CL3}: point on the extended centreline where a 3\u00b0 path reaches 3000 ft. 0 ft wind over the aerodrome; components relative to each RWY heading.</p>
    <p class="wnd-note">H = headwind, T = tailwind, L/R = crosswind from the left/right, kt. ${use}</p>`;
}

function aeroView(store, icao) {
  return (pane) => {
    const wrap = h(`<div class="awl awl-page">
      <div class="awl-head"><h2 class="awl-title">Wind Profile Chart for Aerodrome ${esc(icao)}</h2><div class="awl-sub"></div><div class="awl-errs"></div></div>
      <div class="awl-body">
        <div class="awl-main">
          <div class="awl-chart"><div class="awl-tg"></div><div class="awl-plot"><div class="awl-svgbox"></div>${legend()}</div></div>
          <table class="data awl-prof"></table>
        </div>
        <div class="card awl-rwy"><h3>Runways \u00b7 0 ft and 3000 ft approach</h3><div class="awl-rwyb"></div></div>
      </div>
    </div>`);
    pane.append(wrap);
    const $ = (s) => wrap.querySelector(s);
    $(".awl-tg").append(colorsToggle(wrap));
    let aw = null, awErr = "", inUse = null, dead = false, awAt = 0, busy = false;

    const draw = () => {
      const { data, err } = store.get();
      const ad = data?.aerodromes?.find((a) => a.icao === icao) || null;
      $(".awl-title").textContent = `Wind Profile Chart for Aerodrome ${icao}${ad?.name ? " " + ad.name : ""}`;
      const metar = ad?.metar_wind?.time ? ` \u00b7 METAR ${ad.metar_wind.time.slice(2)}` : "";
      $(".awl-sub").innerHTML = data ? `Forecast for: <span>${esc(forecastFor(data.valid))}</span> \u00b7 Elevation ${ad?.elevation_ft ?? "\u2013"} ft${esc(metar)}`
        : `<span class="hint">${err ? "" : "Loading\u2026"}</span>`;
      $(".awl-sub").title = data?.fetched ? `Fetched ${data.fetched}` : "";
      $(".awl-errs").innerHTML = err ? `<p class="error">${esc(err)}</p>` : data && !ad ? `<p class="error">No wind profile for ${esc(icao)}</p>` : errLines(data);
      $(".awl-svgbox").innerHTML = chartSvg(ad?.profile || []);
      $(".awl-prof").innerHTML = ad ? profileTable(ad.profile) : "";
    };
    const drawRwy = () => { $(".awl-rwyb").innerHTML = rwyPanel(aw, inUse, awErr); };

    const loadRwy = async () => {
      if (busy) return;
      busy = true;
      // pas w użyciu (ATIS albo pas preferowany) z literą ATIS; bez odpowiedzi tabela bez znaczników
      api(`/api/aerodromes/${icao}/status`).then((x) => (x.runway_in_use ? { ...x.runway_in_use, letter: x.atis?.letter || "" } : null))
        .catch(() => null).then((u) => { if (!dead) { inUse = u; drawRwy(); } });
      try {
        aw = await api(`/api/meteo/approach-wind/${icao}`);
        awErr = "";
      } catch (e) {
        awErr = e.message;
      } finally {
        busy = false;
        awAt = Date.now();
      }
      if (!dead) drawRwy();
    };

    const off = store.sub(draw);
    draw();
    drawRwy();
    store.fresh();
    loadRwy();
    // panel pasów starszy niż 10 min: przy powrocie na ekran i co 30 s, gdy AWALON jest widoczny (store.wake)
    const offWake = store.onWake(() => stale(awAt) && loadRwy());
    // serwer wrócił po przerwie: panel pasów od razu, nie po 10 min
    const online = () => awErr && loadRwy();
    window.addEventListener(ONLINE_EVENT, online);
    return { destroy: () => { dead = true; off(); offWake(); window.removeEventListener(ONLINE_EVENT, online); } };
  };
}

export default {
  mount(root) {
    // wspólne dane wszystkich podzakładek: jedno zapytanie o wszystkie lotniska, odświeżane co 10 min
    let data = null, err = "", at = 0, loading = null;
    const subs = new Set(), wakers = new Set();
    const load = () => loading || (loading = (async () => {
      try {
        data = await api("/api/meteo/wind-profile");
        err = "";
      } catch (e) { err = e.message; }
      at = Date.now();
      loading = null;
      subs.forEach((f) => f());
    })());
    const store = {
      get: () => ({ data, err }),
      sub: (f) => { subs.add(f); return () => subs.delete(f); },
      // przy otwarciu podzakładki i przy powrocie na ekran: pierwsze pobranie albo dane starsze niż 10 min
      fresh: () => { if ((!data && !loading) || (!loading && stale(at))) load(); },
      // podzakładka na ekranie dostaje to samo budzenie (panel pasów lotniska ma własne dane)
      onWake: (f) => { wakers.add(f); return () => wakers.delete(f); },
    };
    let ctl = null;
    const open = (icao) => {
      if (!ctl) return;
      ctl.show(icao);
      remember("awalon", icao);
    };
    ctl = subtabs(root, [
      { id: "all", label: "ALL", render: allView(store, open) },
      { sep: true },
      ...AWALON_AD.map((i) => ({ id: i, label: i, render: aeroView(store, i) })),
    ]);
    // AWALON znów widoczny: przycisk menu albo Wstecz do tej samej podzakładki nie rysuje jej od nowa (app.js),
    // więc zmiana klasy "active" widoku, powrót do karty przeglądarki i zegar co 30 s; dane tylko, gdy są stare
    const wake = () => {
      if (document.hidden || root.offsetParent === null) return;
      store.fresh();
      wakers.forEach((f) => f());
    };
    setInterval(wake, TICK);
    new MutationObserver(wake).observe(root, { attributes: true, attributeFilter: ["class"] });
    document.addEventListener("visibilitychange", wake);
    // serwer wrócił po przerwie albo prognoza / METAR były niedostępne: od razu nowe dane
    window.addEventListener(ONLINE_EVENT, () => (err || data?.model_error || data?.metar_error) && load());
  },
};
