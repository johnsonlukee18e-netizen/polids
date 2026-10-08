// Wspólne funkcje: zapytania do API i drobne narzędzia DOM.

// Serwer nie odpowiada (brak internetu, restart serwera): zamiast angielskiego "Failed to fetch" komunikat po polsku i jeden pasek
// u dołu ekranu; znika po pierwszym udanym zapytaniu (sprawdzamy co 5 s, także gdy żadna zakładka nic nie odświeża).
// Po powrocie serwera zdarzenie ONLINE_EVENT na window: zakładki z komunikatem błędu od razu pobierają dane ponownie.
export const OFFLINE_MSG = "brak połączenia z serwerem PolIDS";
export const ONLINE_EVENT = "polids:online";
let offlineBar = null, offlineTimer = null;
function setOffline(on) {
  if (!on) {
    if (!offlineBar) return;
    clearInterval(offlineTimer);
    offlineTimer = null;
    offlineBar.remove();
    offlineBar = null;
    // po bieżącym zapytaniu, żeby zakładka nie pobierała tego samego dwa razy w jednej chwili
    setTimeout(() => window.dispatchEvent(new Event(ONLINE_EVENT)), 0);
    return;
  }
  if (offlineBar) return;
  offlineBar = h(`<div class="srv-off" role="alert"><b>Brak połączenia z serwerem PolIDS</b>
    <span>sprawdź internet; strona połączy się sama, gdy serwer odpowie.</span></div>`);
  document.body.append(offlineBar);
  offlineTimer = setInterval(() => fetch("/api/config", { cache: "no-store" }).then(() => setOffline(false), () => {}), 5000);
}

export async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch (e) {
    if (e?.name === "AbortError") throw e;   // zapytanie przerwane celowo (AbortController)
    setOffline(true);
    throw new Error(OFFLINE_MSG);
  }
  setOffline(false);
  // sesja wygasła
  if (res.status === 401) {
    location.href = "/auth/login";
    throw new Error("Wymagane logowanie");
  }
  let body = null;
  try { body = await res.json(); } catch { /* pusta odpowiedź albo nie JSON (np. strona błędu) */ }
  if (!res.ok) {
    const msg = body && body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail))
      : `Błąd serwera PolIDS (HTTP ${res.status})`;
    throw new Error(msg);
  }
  return body;
}

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function fmt(v, digits = 1, unit = "") {
  if (v === null || v === undefined || v === "") return "–";
  const n = Number(v);
  if (Number.isNaN(n)) return esc(v);
  return (Number.isInteger(n) ? n : n.toFixed(digits)) + unit;
}

export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// Podmenu PANDORY: kolumna zielonych przycisków obok menu głównego.
// tabs: [{id, label, render(pane), fill?}] albo {sep: true} jako odstęp.
export function subtabs(root, tabs) {
  const nav = h(`<nav class="submenu">${tabs.map((t) => t.sep ? `<div class="sep"></div>` : `<button data-id="${t.id}">${esc(t.label)}</button>`).join("")}</nav>`);
  const pane = h(`<div class="pane"></div>`);
  root.append(nav, pane);
  let current = null;
  const show = (id) => {
    current?.destroy?.();
    const t = tabs.find((x) => x.id === id) || tabs.find((x) => !x.sep);
    nav.querySelectorAll("button[data-id]").forEach((b) => b.classList.toggle("active", b.dataset.id === t.id));
    pane.className = "pane" + (t.fill ? " fill" : "");
    pane.innerHTML = "";
    current = t.render(pane) || null;
  };
  nav.addEventListener("click", (e) => { const b = e.target.closest("button[data-id]"); if (b) show(b.dataset.id); });
  show(tabs.find((x) => !x.sep).id);
  return { nav, pane, show };
}

// Podmenu z literami A–Z (jak w AIRCRAFT / CALLSIGN w PANDORZE). onPick("") = wszystkie.
export function letterMenu(root, onPick) {
  const letters = ["*", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
  const nav = h(`<nav class="submenu letters">${letters.map((l) => `<button data-l="${l}">${l === "*" ? "∗" : l}</button>`).join("")}</nav>`);
  root.append(nav);
  const set = (l) => nav.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.l === l));
  nav.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-l]");
    if (!b) return;
    set(b.dataset.l);
    onPick(b.dataset.l === "*" ? "" : b.dataset.l);
  });
  set("*");
  return { set: (l) => set(l || "*") };
}

export function iframeWithFallback(pane, url, note = "") {
  pane.append(h(`<div class="toolbar" style="padding:6px 10px;margin:0;background:var(--panel)">
      <span class="hint mono">${esc(url)}</span><span style="flex:1"></span>
      ${note ? `<span class="hint">${esc(note)}</span>` : ""}
      <a class="btn" href="${esc(url)}" target="_blank" rel="noopener">Otwórz w nowej karcie ↗</a></div>`));
  pane.append(h(`<iframe class="embed" src="${esc(url)}" referrerpolicy="no-referrer"></iframe>`));
}

// Podkłady mapy. CARTO wymaga klucza w parametrze ?key= (POLIDS_CARTO_API_KEY); bez klucza kafelki dostają
// znak wodny "API KEY REQUIRED". Dlatego bez klucza (albo gdy CARTO odrzuca klucz, np. 403 przy ograniczeniu
// domen) używamy szarych podkładów Esri Canvas, które działają bez klucza. "white" = sama biała plansza.
const CARTO_ATTR = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, © <a href="https://carto.com/attributions">CARTO</a>';
const ESRI_ATTR = "Powered by Esri | Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS user community";
const cartoUrl = (style, key) => `https://{s}.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(key)}`;
// Esri ma kafelki Europy do zoomu 16, dalej powiększamy ostatni poziom
const esri = (L, svc) => L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${svc}/MapServer/tile/{z}/{y}/{x}`,
  { attribution: ESRI_ATTR, maxNativeZoom: 16, maxZoom: 19 });
function cartoOrEsri(L, style, svc, key) {
  key = (key || "").trim();
  if (!key) return esri(L, svc);
  const group = L.layerGroup();
  const carto = L.tileLayer(cartoUrl(style, key), { attribution: CARTO_ATTR, subdomains: "abcd", maxZoom: 20 });
  let errors = 0;
  carto.on("tileerror", () => {
    if (++errors !== 4) return;
    console.warn("CARTO nie wydaje kafelków (np. 403: klucz ograniczony do innych domen), przełączam podkład na Esri");
    group.removeLayer(carto);
    group.addLayer(esri(L, svc));
  });
  return group.addLayer(carto);
}
export const BASEMAPS = {
  dark: (L, key) => cartoOrEsri(L, "dark_nolabels", "World_Dark_Gray_Base", key),
  light: (L, key) => cartoOrEsri(L, "light_nolabels", "World_Light_Gray_Base", key),
  white: (L) => L.layerGroup(),
  osm: (L) => L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap", maxZoom: 19 }),
};
export const LIGHT_BASEMAPS = ["light", "white", "osm"];

// --- VATSIM: wspólny cache dla wszystkich zakładek (data feed odświeża się co ~15 s, rezerwacje rzadziej)
const shared = {};
function cached(key, ttl, fn) {
  const hit = shared[key];
  if (hit && Date.now() - hit.t < ttl) return hit.p;
  const p = fn().catch((e) => { delete shared[key]; throw e; });
  shared[key] = { t: Date.now(), p };
  return p;
}
export const vatsimOnline = () => cached("online", 30000, () => api("/api/vatsim/online"));
export const vatsimAtc = () => cached("atc", 30000, () => api("/api/vatsim/atc"));
export const vatsimBookings = () => cached("bookings", 300000, () => api("/api/vatsim/bookings?prefix=EP"));
export const atcPositions = () => cached("positions", 3600000, () => api("/api/nav/positions"));
export const aerodromeNames = () => cached("adnames", 3600000, () => api("/api/aerodromes")
  .then((list) => Object.fromEntries(list.map((a) => [a.icao, a.name]))));

export const hhmm = (iso) => (iso ? new Date(iso).toISOString().slice(11, 16) + "Z" : "–");

// Opis do dymka po najechaniu na stanowisko: kto jest zalogowany / kto zarezerwował.
export function positionTip(on, books = []) {
  const lines = [];
  if (on) lines.push(`ONLINE: ${on.name || "?"} (CID ${on.cid ?? "?"})`, `${on.callsign} ${on.frequency}, od ${hhmm(on.logon_time)}`);
  books.forEach((b) => lines.push(`${b.active ? "BOOKING TERAZ" : "BOOKING"}: CID ${b.cid}${b.name ? " " + b.name : ""}`,
    `${b.callsign} ${hhmm(b.start)}–${hhmm(b.end)}${b.type && b.type !== "booking" ? " (" + b.type + ")" : ""}`));
  return lines.join("\n");
}

// ATIS z VATSIM (text_atis): każdy element tablicy w osobnej linijce, jak w VATSIM Radar, a nie jeden ciągły tekst.
// Element bywa też napisem z własnymi znakami nowej linii; puste linijki pomijamy. null (ATIS bez tekstu) → [].
export function splitAtis(lines) {
  if (lines === null || lines === undefined) return [];
  return (Array.isArray(lines) ? lines : [lines]).flatMap((l) => String(l ?? "").split(/\r?\n/)).map((l) => l.trim()).filter(Boolean);
}
// ATIS do HTML: każda linijka osobno (esc), dłuższa zawija się z wcięciem, żeby było widać początek następnej (.atl w map.css)
export const atisHtml = (lines) => splitAtis(lines).map((l) => `<div class="atl">${esc(l)}</div>`).join("");

// TAF: każda grupa zmian (BECMG, TEMPO, PROB, FM) w osobnej linii.
export function splitTaf(raw) {
  if (!raw) return [];
  const tokens = raw.replace(/\s+/g, " ").trim().split(" ");
  const lines = [[]];
  tokens.forEach((t, i) => {
    const prev = tokens[i - 1];
    const starts = /^(BECMG|TEMPO|FM\d{6}|PROB\d{2})$/.test(t) && !(t === "TEMPO" && /^PROB\d{2}$/.test(prev));
    if (starts && lines[lines.length - 1].length) lines.push([]);
    lines[lines.length - 1].push(t);
  });
  return lines.map((l) => l.join(" "));
}

// localStorage bywa niedostępny (tryb prywatny, zablokowane dane witryny): odczyt i zapis zawsze w try
export function lsGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
export function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* tryb prywatny */ }
}
