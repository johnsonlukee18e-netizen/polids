// RADIO: stan wspólny podzakładek (GEO, SEKTORYZACJA, listy stanowisk): stanowiska (.ese + sąsiedzi z vacs-data),
// kto jest online i kto zarezerwował, tryb "VATSIM teraz" / "symulacja" i zestaw pozycji w symulacji
// (zapamiętany w przeglądarce). Zmiany rozsyłane do subskrybentów: on((co) => …), co = "net" | "sim".
import { api, atcPositions, hhmm, lsGet, lsSet } from "./api.js";
import { POSITION_COLORS, colorFor } from "./airspace.js";
import { loadVacsJson } from "./posname.js";

const LS_MODE = "radio.mode", LS_SIM = "radio.sim";
const TYPE_ORDER = ["CTR", "FSS", "APP", "DEP", "TWR", "GND", "DEL", "RMP", "ATIS"];
export const typeOf = (cs) => String(cs || "").split("_").pop();

// symulacja z rundy 7 (MAP › SEKTORYZACJA) przechodzi do RADIO przy pierwszym uruchomieniu
function readSim() {
  for (const k of [LS_SIM, "map.split.sim"]) {
    try {
      const v = JSON.parse(lsGet(k));
      if (Array.isArray(v)) return v.filter((x) => typeof x === "string");
    } catch { /* uszkodzony wpis */ }
  }
  return [];
}
// tryb: bez radio.mode (pierwsze uruchomienie po v0.8) z map.split.mode (JSON "sim"), razem z zestawem map.split.sim
function readMode() {
  const m = lsGet(LS_MODE);
  if (m !== null) return m === "sim" ? "sim" : "now";
  let old = null;
  try { old = JSON.parse(lsGet("map.split.mode")); } catch { /* uszkodzony wpis */ }
  if (old !== "sim") return "now";
  lsSet(LS_MODE, "sim");
  return "sim";
}

export const state = {
  mode: readMode(),
  sim: new Set(readSim()),
  online: {},        // znak stanowiska → kontroler (dopasowanie jak w EuroScope, też stanowiska tylko z vacs-data)
  firs: {},          // FIR-y z VATSpy z zalogowanym CTR/FSS
  controllers: [],   // zalogowani z EP** i znanych prefiksów (także niedopasowani)
  bookings: {},      // znak → rezerwacje na dziś
  onlineAt: 0,
  ok: false,         // czy ostatnie pobranie stanu sieci się udało
  tried: false,      // czy pierwsze pobranie już się zakończyło (do tego czasu "pobieranie…", potem "brak danych")
  err: "",
};

const subs = new Set();
export const on = (fn) => { subs.add(fn); return () => subs.delete(fn); };
const emit = (what) => subs.forEach((fn) => fn(what));

// --- stanowiska: /api/radio/positions; bez niego (starszy serwer) same stanowiska z pliku .ese
let posP = null;
export const loadPositions = () => (posP ||= api("/api/radio/positions")
  .catch(() => atcPositions().then((ps) => ps.map((p) => ({ ...p, in_ese: true, facility: typeOf(p.callsign) }))))
  .catch((e) => { posP = null; throw e; }));

// --- vacs-data (CC BY-NC-SA 4.0): strony GEO profilu ACC_EPWW, etykiety stanowisk sąsiadów; raz na sesję
// (to samo zapytanie co etykiety displayName w posname.js)
export const loadVacsData = loadVacsJson;

// --- wszystkie wycinki sektorów z pliku .ese (EPWW i sąsiedzi), raz na sesję
let secP = null;
export const loadSectors = () => (secP ||= api("/api/radio/sectors").catch((e) => { secP = null; throw e; }));

// --- stan sieci (cache 25 s, wspólny dla podzakładek)
let netP = null, netT = 0;
export function refreshNet(force = false) {
  if (netP && !force && Date.now() - netT < 25000) return netP;
  netT = Date.now();
  netP = Promise.allSettled([api("/api/radio/online"), api("/api/radio/bookings")]).then(([on, bk]) => {
    const errs = [];
    if (on.status === "fulfilled") {
      Object.assign(state, { online: on.value.positions || {}, firs: on.value.firs || {}, controllers: on.value.controllers || [],
        onlineAt: Date.now(), ok: true });
    } else {
      Object.assign(state, { online: {}, firs: {}, controllers: [], ok: false });
      errs.push(on.reason.message);
    }
    if (bk.status === "fulfilled") state.bookings = bk.value || {};
    else errs.push(bk.reason.message);
    // komunikaty serwera zaczynają się już od "VATSIM …"; ten sam błąd obu zapytań (np. serwer wyłączony) raz
    state.err = [...new Set(errs.map((e) => (/^VATSIM/i.test(e) ? e : `VATSIM: ${e}`)))].join(" · ");
    state.tried = true;
    emit("net");
    return state;
  });
  return netP;
}

// odświeżanie co minutę, dopóki jakiś widok RADIO jest na ekranie
let watchers = 0, timer = null;
export function watch() {
  if (!watchers++) timer = setInterval(() => refreshNet(true), 60000);
  refreshNet();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    if (!--watchers) { clearInterval(timer); timer = null; }
  };
}

// --- tryb i symulacja
const saveSim = () => lsSet(LS_SIM, JSON.stringify([...state.sim]));
export function setMode(m) {
  state.mode = m === "sim" ? "sim" : "now";
  lsSet(LS_MODE, state.mode);
  emit("sim");
}
export function setSim(list) {
  state.sim = new Set(list);
  saveSim();
  emit("sim");
}
// kliknięcie pozycji: w trybie "VATSIM teraz" przejście do symulacji (zapamiętany zestaw) i przełączenie pozycji
export function toggle(cs) {
  const s = new Set(state.sim);
  if (s.has(cs)) s.delete(cs); else s.add(cs);
  state.sim = s;
  saveSim();
  if (state.mode !== "sim") { state.mode = "sim"; lsSet(LS_MODE, "sim"); }
  emit("sim");
}
// Linijka stanu sieci: liczba online i godzina ostatniego udanego pobrania; po błędzie "brak danych" (bez starej godziny)
export function netText(count = (n) => `${n} online`) {
  if (state.ok) return `VATSIM ${hhmm(new Date(state.onlineAt).toISOString())}: ${count(onlineList().length)}`;
  return state.tried ? "VATSIM: brak danych" : "VATSIM: pobieranie…";
}
// stanowiska, pod którymi zalogowany kontroler jest też wpisany znakiem z pliku sąsiada (EKDK_CTR → EKDK_UN_CTR,
// pole alias_of z /api/radio/online): liczymy go raz, pod znakiem z pliku sąsiada, bo ten ma dokładne sektory
export const aliased = () => new Set(Object.values(state.online)
  .filter((o) => o?.alias_of && state.online[o.alias_of]?.callsign === o.callsign).map((o) => o.alias_of));
// zalogowani w sieci, bez ATIS (to nie jest stanowisko kontroli)
export const onlineList = () => {
  const al = aliased();
  return Object.keys(state.online).filter((cs) => typeOf(cs) !== "ATIS" && !al.has(cs));
};
export const activeSet = () => new Set(state.mode === "sim" ? state.sim : onlineList());

// kolejność wyświetlania: EPWW i Polska, potem sąsiedzi; w obrębie: CTR/FSS, APP, TWR, GND, DEL
export function byRank(a, b) {
  const r = (cs) => (cs.startsWith("EPWW") ? 0 : cs.startsWith("EP") ? 1 : 2);
  const t = (cs) => { const i = TYPE_ORDER.indexOf(typeOf(cs)); return i < 0 ? 99 : i; };
  return r(a) - r(b) || t(a) - t(b) || a.localeCompare(b);
}

// Kolory aktywnych pozycji: stałe dla stanowisk ACC EPWW (POSITION_COLORS), reszta z colorFor; gdy kolor pozycji
// spoza ACC jest taki sam albo prawie taki sam jak kolor pozycji już na mapie, dostaje kolor z zapasowej palety
// najbardziej różny od użytych.
const SPARE = ["#ff9f1a", "#00e0ff", "#ff5cf0", "#b6ff3c", "#ffe14d", "#ff6b6b", "#7a8cff", "#3dffb0", "#ffa3c8", "#c08bff",
  "#4dd2ff", "#ffd27a", "#9dff6e", "#ff7ae0", "#6fffe9", "#f0a35e"];
const rgb = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const dist = (a, b) => { const x = rgb(a), y = rgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
export function colorMap(list) {
  const out = {}, used = [];
  const near = (c) => (used.length ? Math.min(...used.map((u) => dist(c, u))) : Infinity);
  [...list].sort(byRank).forEach((cs) => {
    let c = colorFor(cs);
    if (used.includes(c) || (!POSITION_COLORS[cs] && near(c) < 70)) {
      const free = SPARE.filter((x) => !used.includes(x));
      if (free.length) c = free.reduce((a, b) => (near(b) > near(a) ? b : a));
    }
    out[cs] = c;
    used.push(c);
  });
  return out;
}

// Kolory FIR-ów sąsiadów (kafelki GEO, nagłówki list RADIO): jak w VACS, jeden stały kolor na FIR, przygaszony pod
// ciemny wygląd NM UI. Stanowiska lotnisk i APP (EDDB, EDDC, ESSA…) mają kolor swojego FIR-u; EPWW i Polska bez koloru.
export const FIR_COLORS = {
  EDWW: { c: "#8396b0", name: "FIR Bremen" }, EDYY: { c: "#5d8fd8", name: "UAC Maastricht" },
  EDUU: { c: "#b8915e", name: "UIR Rhein" }, EDMM: { c: "#35a89f", name: "FIR München" },
  ESAA: { c: "#d681ae", name: "Szwecja (ESMM, ESOS)" }, EKDK: { c: "#cf9f45", name: "FIR København" },
  EYVL: { c: "#86d2a4", name: "FIR Vilnius" }, UMKK: { c: "#a993da", name: "FIR Kaliningrad" },
  UMMV: { c: "#8f948f", name: "FIR Minsk" }, UKLV: { c: "#d6ca5c", name: "FIR Lviv" },
  LKAA: { c: "#e3917a", name: "FIR Praha" }, LZBB: { c: "#e25d36", name: "FIR Bratislava" },
};
// katalog FIR-u w vacs-data (pole fir stanowiska) → klucz koloru
const FIR_DIR = { EDWW: "EDWW", EDMM: "EDMM", EDUU: "EDUU", ES: "ESAA", EK: "EKDK", EY: "EYVL", LK: "LKAA", LZ: "LZBB", UMKK: "UMKK" };
// klucz koloru FIR-u stanowiska (fir = katalog vacs-data z /api/radio/positions, gdy jest) albo null (Polska, nieznane)
export function firKey(cs, fir) {
  const pre = String(cs || "").toUpperCase().split("_")[0];
  if (!pre || pre.startsWith("EP")) return null;
  if (pre === "EDYY" || pre === "EDUU") return pre;  // w katalogu EDWW/EDMM, ale to osobne organy
  if (FIR_DIR[fir]) return FIR_DIR[fir];
  if (pre === "UMKK" || pre.startsWith("RU-")) return "UMKK";
  const by = [["UK", "UKLV"], ["UM", "UMMV"], ["LK", "LKAA"], ["LZ", "LZBB"], ["EY", "EYVL"], ["ES", "ESAA"], ["EK", "EKDK"]]
    .find(([p]) => pre.startsWith(p));
  if (by) return by[1];
  if (pre.startsWith("ED")) return ["EDWW", "EDDB", "EDAH", "EDDH", "EDDW", "EDDV"].includes(pre) ? "EDWW" : "EDMM";
  return null;
}
export const firColor = (cs, fir) => FIR_COLORS[firKey(cs, fir)]?.c || null;
