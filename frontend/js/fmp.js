import { api, esc, h, ONLINE_EVENT } from "./api.js";
import { fmpRows } from "./viffchart.js";

// OTHER › FMP (0.13.0, issue #23): sektory (traffic volumes) w tabeli SECTOR | CAPACITY | OCCUPANCY jak FMP PANDORY,
// z tych samych danych co panel sektorów na MAP (GET /api/viff/sectors, jedno zapytanie zbiorcze z cache).
// SECTOR = id bez prefiksu "EP-" (dymek: opis jak "sector B upper", "TMA EPWA"), CAPACITY = wejścia w bieżącej godzinie
// i przepustowość wejść "18 (45)", OCCUPANCY = samoloty w sektorze teraz i przepustowość chwilowa "9 (14)"; "–" bez
// liczby albo bez limitu. Aktywne sektory na szarym tle (ciemniej niż w PANDORZE: biały tekst zostaje czytelny),
// nieaktywne na czarnym, bez pasków zebry; aktywne na początku, potem po id. Liczba żółta od 90 % przepustowości,
// czerwona powyżej (te same progi co wykres na MAP); id sektora czerwone, gdy obowiązuje regulacja.
// Odświeżanie co 60 s, gdy podzakładka jest na ekranie; po powrocie serwera (ONLINE_EVENT) od razu.

const REFRESH_MS = 60000;

const NUM_CLS = { near: " near", over: " over" };
function rowHtml(r) {
  return `<tr class="${r.active ? "on" : "off"}" data-tv="${esc(r.id)}">
    <td class="fmp-sec${r.restricted ? " reg" : ""}" title="${esc(r.sectorTip)}">${esc(r.code)}</td>
    <td class="fmp-num${NUM_CLS[r.entriesCls] || ""}" title="${esc(r.capacityTip)}">${esc(r.capacity)}</td>
    <td class="fmp-num${NUM_CLS[r.occupancyCls] || ""}" title="${esc(r.occupancyTip)}">${esc(r.occupancyText)}</td></tr>`;
}

// tabela dla odpowiedzi /api/viff/sectors; czysta funkcja (testy w Node)
export function fmpHtml(data) {
  const rows = fmpRows(data);
  if (!rows.length) return `<p class="hint fmp-empty">No sectors.</p>`;
  return `<table class="fmp-table">
    <thead><tr><th title="Traffic volume: sector or area with a set capacity">SECTOR</th>
      <th title="Entries in the current hour (entry capacity per hour)">CAPACITY</th>
      <th title="Aircraft in the sector now (capacity at one time)">OCCUPANCY</th></tr></thead>
    <tbody>${rows.map(rowHtml).join("")}</tbody></table>`;
}

// linia nad tabelą: godzina danych i liczba aktywnych
export function fmpInfo(data) {
  const rows = fmpRows(data), on = rows.filter((r) => r.active).length;
  const now = /^\d{4}$/.test(data?.now || "") ? `${data.now}Z · ` : "";
  return rows.length ? `${now}${on} of ${rows.length} active (grey rows)` : "";
}

export function mountFmp(pane) {
  const root = h(`<div class="fmp">
    <div class="fmp-bar"><span class="fmp-info hint"></span><span class="fmp-msg error"></span></div>
    <div class="fmp-scroll"><p class="hint">Loading…</p></div>
  </div>`);
  pane.append(root);
  const info = root.querySelector(".fmp-info"), msg = root.querySelector(".fmp-msg"), box = root.querySelector(".fmp-scroll");
  let data = null, loadedAt = 0, seq = 0, dead = false;
  const visible = () => root.isConnected && root.offsetParent !== null;

  // odświeżenie po błędzie zostawia ostatnią tabelę i pisze tylko komunikat nad nią
  const load = async () => {
    const my = ++seq;
    try {
      const d = await api("/api/viff/sectors");
      if (dead || my !== seq) return;
      data = d; loadedAt = Date.now();
      const top = box.scrollTop;
      box.innerHTML = fmpHtml(d);
      box.scrollTop = top;
      info.textContent = fmpInfo(d);
      msg.textContent = "";
    } catch (e) {
      if (dead || my !== seq) return;
      loadedAt = Date.now();
      if (data) msg.textContent = `Not refreshed: ${e.message}`;
      else { box.innerHTML = `<p class="error fmp-err">${esc(e.message)}</p>`; info.textContent = ""; }
    }
  };
  const timer = setInterval(() => { if (visible()) load(); }, REFRESH_MS);
  const online = () => load();
  window.addEventListener(ONLINE_EVENT, online);
  load();
  return {
    // powrót do podzakładki po dłuższej przerwie (w tle nie odświeżamy): dane od razu
    activate() { if (loadedAt && Date.now() - loadedAt > REFRESH_MS) load(); },
    destroy() {
      dead = true;
      clearInterval(timer);
      window.removeEventListener(ONLINE_EVENT, online);
    },
  };
}
