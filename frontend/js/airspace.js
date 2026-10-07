// Wspólne warstwy mapy przestrzeni (RADIO i MAP): sektory EPWW z pliku .ese, granice FIR z VATSpy,
// podświetlenie stanowisk zalogowanych w sieci VATSIM.
import { api, esc } from "./api.js";

const PALETTE = ["#2f8fff", "#3ecf6e", "#ffb020", "#ff5c8a", "#a970ff", "#00c2c7", "#ff7a3d", "#c3d82b", "#ff4dd2", "#6f8cff"];
// Stałe kolory 19 stanowisk ACC EPWW (te same w MAPA, SEKTORYZACJA i RADIO). Dobrane tak, żeby najbardziej różniły się
// stanowiska, które mogą jednocześnie obsługiwać sąsiednie sektory; skrót stanowiska jest zawsze w etykiecie.
export const POSITION_COLORS = {
  EPWW_N_CTR: "#40f5ec", EPWW_ALH_CTR: "#4ed227", EPWW_DBT_CTR: "#ae5af9", EPWW_DBF_CTR: "#fd8c7b", EPWW_ALL_CTR: "#4fcc92",
  EPWW_DTC_CTR: "#5886f2", EPWW_S_CTR: "#c7b05a", EPWW_E_CTR: "#04a19b", EPWW_TCJ_CTR: "#e9dd3c", EPWW_C_CTR: "#05a92e",
  EPWW_DT_CTR: "#b871a1", EPWW_D_CTR: "#f7305d", EPWW_NE_CTR: "#f554ca", EPWW_FG_CTR: "#40befd", EPWW_F_CTR: "#90923b",
  EPWW_G_CTR: "#fca0e8", EPWW_JR_CTR: "#cb7229", EPWW_J_CTR: "#b0a5f2", EPWW_TM_CTR: "#5dfd6d",
};
export function colorFor(key) {
  if (POSITION_COLORS[key]) return POSITION_COLORS[key];
  let x = 0;
  for (const ch of String(key)) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[x % PALETTE.length];
}

let firsPromise = null;
export const loadFirs = () => (firsPromise ||= api("/api/vatsim/firs").catch((e) => { firsPromise = null; throw e; }));

export const fl = (ft) => "FL" + String(Math.round((ft || 0) / 100)).padStart(3, "0");

// --- VACS (vacs-data, CC BY-NC-SA 4.0): łańcuchy dziedziczenia sektorów EPWW w warstwach LOW/MID/HIGH.
// Wczytywane raz przy starcie modułu, żeby sectorOwners() (też w RADIO) miało je od razu.
let vacsPromise = null, vacsData = null;
export const loadVacs = () => (vacsPromise ||= api("/api/nav/vacs").then((d) => (vacsData = d))
  .catch((e) => { vacsPromise = null; throw e; }));
loadVacs().catch(() => { /* bez VACS: właściciele z listy OWNER pliku .ese */ });
export const VACS_LAYERS = ["LOW", "MID", "HIGH"];
// warstwa wg poziomu w stopach: poniżej FL335 LOW, poniżej FL365 MID, wyżej HIGH
export const vacsLayer = (ft) => (ft < 33500 ? "LOW" : ft < 36500 ? "MID" : "HIGH");
// litera sektora ACC z nazwy sektora .ese: EPWWB → B, EPWWR-N → R; EPWW-MIDSEA, TMA, CTA → null
export const accLetter = (name) => /^EPWW([A-Z])(?:-[A-Z]+)?$/.exec(name || "")?.[1] || null;
// skrót stanowiska VACS (EPWW_DBF_CTR → DBF)
export const vacsShort = (vacs, cs) => vacs?.acc_positions?.[cs]?.short || cs;

// --- Plakietki stanowisk online jak w VATSIM Radar: lotnisko = ICAO + D/G/T/A/APP, FIR = CTR + id.
// Po najechaniu dymek z listą: znak, częstotliwość, imię i nazwisko, CID, rating, od kiedy online, ATIS.
export const FACILITIES = [["DEL", "D", "Delivery"], ["GND", "G", "Ground"], ["TWR", "T", "Tower"], ["ATIS", "A", "ATIS"],
  ["APP", "APP", "Approach / Departure"]];
const RATINGS = { 1: "OBS", 2: "S1", 3: "S2", 4: "S3", 5: "C1", 6: "C2", 7: "C3", 8: "I1", 9: "I2", 10: "I3", 11: "SUP", 12: "ADM" };
const since = (iso) => {
  if (!iso) return "";
  const min = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  return `od ${new Date(iso).toISOString().slice(11, 16)}Z (${min < 60 ? min + " min" : Math.floor(min / 60) + " h " + (min % 60) + " min"})`;
};
const tag = (kind, letter) => `<span class="ab ab-${kind.toLowerCase()}">${letter}</span>`;

function atcRows(list, kind, letter) {
  return list.map((c) => `<tr><td>${tag(kind, letter)}</td><td class="cs">${esc(c.callsign)}</td><td class="fq">${esc(c.frequency)}</td>
    <td>${esc(c.name || "?")} <span class="muted">${esc(c.cid ?? "")}${RATINGS[c.rating] ? " · " + RATINGS[c.rating] : ""}</span></td>
    <td class="muted">${since(c.logon_time)}</td></tr>${kind === "ATIS" && c.text_atis?.length
      ? `<tr><td></td><td colspan="4" class="atis">${c.atis_code ? `<b>INFO ${esc(c.atis_code)}</b> ` : ""}${c.text_atis.map(esc).join(" ")}</td></tr>` : ""}`).join("");
}

// Osobne warstwy (panes) nad nazwami punktów, żeby plakietek nie przykrywały etykiety; dymki jeszcze wyżej.
export function atcPanes(map) {
  [["atcFir", 655], ["atcAd", 660], ["atcTip", 700]].forEach(([n, z]) => {
    if (!map.getPane(n)) map.createPane(n).style.zIndex = z;
  });
  return { fir: "atcFir", ad: "atcAd", tip: "atcTip" };
}

export function atcTooltip(title, subtitle, rows) {
  return `<div class="atc-tip-h"><b>${esc(title)}</b> ${esc(subtitle || "")}</div><table>${rows}</table>`;
}

// Plakietka lotniska (divIcon pod punktem lotniska) z dymkiem
export function airportBadge(ap, panes = {}) {
  const fac = ap.facilities;
  const html = `<div class="atcb"><b class="ab-icao">${esc(ap.icao)}</b>${FACILITIES.filter(([k]) => fac[k])
    .map(([k, l]) => tag(k, l)).join("")}</div>`;
  const rows = FACILITIES.filter(([k]) => fac[k]).map(([k, l]) => atcRows(fac[k], k, l)).join("");
  return L.marker([ap.lat, ap.lon], { icon: L.divIcon({ className: "atcicon", html, iconSize: null }), pane: panes.ad || "markerPane" })
    .bindTooltip(atcTooltip(ap.icao, ap.name, rows), { direction: "top", offset: [0, -6], className: "atc-tip", opacity: 1, pane: panes.tip || "tooltipPane" });
}

// Granice FIR: szare kontury; FIR z zalogowanym kontrolerem CTR/FSS na zielono z plakietką CTR (dymek: kto jest online).
// FIR-y z `skip` (EPWW: rysujemy tam sektory z pliku .ese) dostają samą plakietkę, gdy ktoś jest online.
export function drawFirs(layer, firs, onlineFirs = {}, { skip = ["EPWW"], labels = true, panes = {} } = {}) {
  firs.features.forEach((f) => {
    const id = f.properties.id;
    const on = onlineFirs[id];
    const skipped = skip.some((s) => id === s || id.startsWith(s + "-"));
    if (skipped && !on) return;
    // sektory ACC (EDWW-ALR itd.) rysujemy tylko, gdy są online; całe FIR-y zawsze
    if (id.includes("-") && !on) return;
    if (!skipped) {
      L.geoJSON(f, {
        interactive: false,
        style: on ? { color: "#5fd23a", weight: 1.5, fillColor: "#5fd23a", fillOpacity: 0.12 }
          : { color: "#4a524a", weight: 1, fill: false, dashArray: "4 4" },
      }).addTo(layer);
    }
    if (!labels) return;
    const at = [f.properties.label[1], f.properties.label[0]];
    if (!on) {
      L.marker(at, { interactive: false, icon: L.divIcon({ className: "maplabel", html: `<div><span class="firname">${esc(id)}</span></div>`, iconSize: null }) })
        .addTo(layer);
      return;
    }
    const html = `<div class="atcb fir">${tag("CTR", "CTR")}<b class="ab-icao">${esc(id)}</b></div>`;
    L.marker(at, { icon: L.divIcon({ className: "atcicon center", html, iconSize: null }), pane: panes.fir || "markerPane" })
      .bindTooltip(atcTooltip(id, f.properties.name || "", atcRows(on, "CTR", "CTR")),
        { direction: "top", offset: [0, -12], className: "atc-tip", opacity: 1, pane: panes.tip || "tooltipPane" })
      .addTo(layer);
  });
}

// Sektory EPWW: kolor wg właściciela; w trybie online szary = nikt nie obsługuje (UNICOM).
// online = {sector_owner: {nazwa: {callsign, frequency, name, cid}}} albo null (podział pełny z pliku .ese).
// tipPane: warstwa dymków (np. nad plakietkami ATC), domyślnie zwykła warstwa dymków Leafleta.
export function drawSectors(layer, gj, online = null, { labels = true, tipPane = "tooltipPane" } = {}) {
  gj.features.forEach((f) => {
    const pr = f.properties;
    const own = online ? online.sector_owner[pr.name] : null;
    const cs = online ? own?.callsign : pr.callsign;
    const freq = online ? own?.frequency : pr.frequency;
    // sektor ACC rozstrzygnięty wg VACS: łańcuch dziedziczenia z wyróżnionym właścicielem; kolor wg stanowiska VACS
    // (ten sam co w SEKTORYZACJI także przy znaku zastępczym, np. EPWW_C1_CTR na częstotliwości C)
    const vc = online?.vacs?.[pr.name];
    const color = online && !own ? "#555" : colorFor(vc?.key || cs || pr.name);
    const chain = vc ? `<br><span class="muted">VACS ${esc(vc.layer)}:</span> ${vc.chain.map((s) => (s === vc.owner ? `<b>${esc(s)}</b>` : esc(s))).join(" › ")}` : "";
    const poly = L.geoJSON(f, { style: { color, weight: 1.2, fillColor: color, fillOpacity: online && !own ? 0.03 : 0.16 } })
      .bindTooltip(`<b>${esc(pr.name)}</b> ${fl(pr.lower_ft)}–${fl(pr.upper_ft)}<br>${online ? (own ? `${esc(own.callsign)} ${esc(own.frequency)}<br>${esc(own.name || "")} (${esc(own.cid ?? "")})` : "UNICOM 122.800") : `${esc(cs || "")} ${esc(freq || "")}`}${chain}`, { sticky: true, pane: tipPane, opacity: 1 });
    poly.addTo(layer);
    if (labels) {
      L.marker(poly.getBounds().getCenter(), {
        interactive: false,
        icon: L.divIcon({ className: "maplabel", iconSize: null,
          html: `<div><small>${esc(pr.name)}</small><br>${freq ? `<span class="freq${own ? " on" : ""}">${esc(freq)}</span>` : `<span class="hint">UNICOM</span>`}</div>` }),
      }).addTo(layer);
    }
  });
}

// Właściciel każdego sektora. Sektory ACC EPWW (B, C, … R-N): pierwsze zalogowane stanowisko z łańcucha VACS
// w warstwie wycinka (LOW/MID/HIGH wg jego dolnej granicy). Reszta (TMA, CTR, EPWW-MIDSEA) i brak danych VACS:
// pierwsze zalogowane z listy OWNER pliku .ese (jak w EuroScope).
// Wynik: {sector_owner: {nazwa: kontroler}, vacs: {nazwa: {layer, chain: [skróty], owner: skrót|null, key: znak VACS|null}}}.
export function sectorOwners(gj, positions, online, vacs = vacsData) {
  if (!vacsData && !vacsPromise) loadVacs().catch(() => { /* następna próba przy kolejnym rysowaniu */ });
  const byId = Object.fromEntries(positions.map((p) => [p.position_id, p]));
  // stanowisko VACS → wpis online (klucze online to znaki z pliku .ese; dopasowanie przez ese_id)
  const onl = (cs) => online[byId[vacs?.acc_positions?.[cs]?.ese_id]?.callsign] || online[cs];
  const owners = {}, chains = {};
  gj.features.forEach((f) => {
    const pr = f.properties, letter = accLetter(pr.name);
    const layer = vacsLayer(pr.lower_ft ?? 0);
    const chain = letter && vacs?.sectors?.[letter]?.[layer];
    if (chain?.length) {
      const cs = chain.find(onl);
      chains[pr.name] = { layer, chain: chain.map((c) => vacsShort(vacs, c)), owner: cs ? vacsShort(vacs, cs) : null, key: cs || null };
      if (cs) owners[pr.name] = onl(cs);
      return;
    }
    const owner = (pr.owners || []).map((id) => byId[id]).find((p) => p && online[p.callsign]);
    if (owner) owners[pr.name] = online[owner.callsign];
  });
  return { sector_owner: owners, vacs: chains };
}

// Sylwetka samolotu widziana z góry (nos do góry), obracana wg kursu
export const PLANE_PATH = "M0,-9.5 C0.9,-9.5 1.3,-8.4 1.3,-7 L1.3,-2.6 L9,1.6 L9,3.3 L1.3,1 L1.1,5.6 L3.6,7.6 L3.6,8.9 L0,8 "
  + "L-3.6,8.9 L-3.6,7.6 L-1.1,5.6 L-1.3,1 L-9,3.3 L-9,1.6 L-1.3,-2.6 L-1.3,-7 C-1.3,-8.4 -0.9,-9.5 0,-9.5 Z";

// Samolot: sylwetka obrócona wg kursu, etykieta z callsignem (i FL/typem przy większym zoomie).
export function aircraftMarker(p, { label = true, detail = false } = {}) {
  const fl = p.altitude !== null && p.altitude !== undefined ? "FL" + String(Math.round(p.altitude / 100)).padStart(3, "0") : "";
  const html = `<div class="ac"><svg viewBox="-10 -10 20 20" style="transform:rotate(${p.heading || 0}deg)"><path d="${PLANE_PATH}"/></svg>`
    + (label ? `<span>${esc(p.callsign)}${detail ? `<br>${fl} ${esc(p.aircraft || "")} ${p.groundspeed ?? ""}` : ""}</span>` : "") + "</div>";
  return L.marker([p.lat, p.lon], { icon: L.divIcon({ className: "acicon", html, iconSize: [20, 20], iconAnchor: [10, 10] }) });
}

// Symbole punktów jak w EuroScope (SYMBOLDEF, jednostki = piksele, oś Y w dół).
// Linie: [[x, y], ...] rysowane jako łamana; okrąg: {circle: promień}.
export const SYMBOLS = {
  aerodrome: [[[-2, -4], [4, -4]], [[4, -4], [7, -1]], [[7, -1], [4, 2]], [[4, 2], [-2, 2]], [[-2, 2], [-6, -2]], [[-4, -2], [-2, -4]]],
  vor: [[[-4, 0], [-2, 2], [2, 2], [4, 0], [2, -2], [-2, -2], [-4, 0]]],
  ndb: [[[0, -4], [-2, 0], [0, 4], [2, 0], [0, -4]]],
  vfr: { circle: 3 },
  fix: { circle: 4 },
};
export const symbolFor = (kind) => ({ AD: "aerodrome", VOR: "vor", "VOR-DME": "vor", VORTAC: "vor", DME: "vor", NDB: "ndb", "NDB-DME": "ndb", VFR: "vfr" }[kind] || "fix");

// Ikona SVG symbolu (legenda, przyciski warstw)
export function symbolSvg(name, color = "currentColor", size = 18, scale = 1.6) {
  const sym = SYMBOLS[name];
  const v = size / 2 / scale;
  const body = sym.circle ? `<circle cx="0" cy="0" r="${sym.circle}"/>`
    : sym.map((line) => `<polyline points="${line.map(([x, y]) => `${x},${y}`).join(" ")}"/>`).join("");
  return `<svg class="sym" width="${size}" height="${size}" viewBox="${-v} ${-v} ${2 * v} ${2 * v}" fill="none" stroke="${color}" stroke-width="${1.4 / scale * 1.4}">${body}</svg>`;
}

// Marker rysowany na kanwie (mapa z preferCanvas): kształt z SYMBOLS, skalowany. Obsługuje dymki i kliknięcia
// jak CircleMarker (obszar trafienia = promień).
export const SymbolMarker = L.CircleMarker.extend({
  options: { symbol: "fix", scale: 1.6, fill: false, weight: 1.6, radius: 8 },
  _updatePath() {
    const r = this._renderer;
    if (!r._ctx) { r._updateCircle(this); return; }
    if (!r._drawing || this._empty()) return;
    const ctx = r._ctx, p = this._point, s = this.options.scale, sym = SYMBOLS[this.options.symbol] || SYMBOLS.fix;
    ctx.beginPath();
    if (sym.circle) {
      ctx.moveTo(p.x + sym.circle * s, p.y);
      ctx.arc(p.x, p.y, sym.circle * s, 0, Math.PI * 2);
    } else {
      sym.forEach((line) => line.forEach(([x, y], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, p.x + x * s, p.y + y * s)));
    }
    r._fillStroke(ctx, this);
  },
});
