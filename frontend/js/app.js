import { api, esc } from "./api.js";
import meteo from "./tabs/meteo.js";
import { adciv, admil, advfr } from "./tabs/aip.js";
import about from "./tabs/about.js";
import radio from "./tabs/radio.js";
import emergency from "./tabs/emergency.js";
import aircraft from "./tabs/aircraft.js";
import callsign from "./tabs/callsign.js";
import aerodrome from "./tabs/aerodrome.js";
import map from "./tabs/map.js";
import inop from "./tabs/inop.js";
import docs from "./tabs/docs.js";
import phraseology from "./tabs/phraseology.js";
import checklist from "./tabs/checklist.js";
import admin from "./tabs/admin.js";

// Leaflet po polsku, raz dla wszystkich map (RADIO, METEO › QNH, MAP itd.), zanim którakolwiek się zbuduje:
// dymki przycisków powiększenia i odnośnika "Leaflet" w atrybucji (sama treść atrybucji bez zmian)
if (window.L) {
  L.Control.Zoom.mergeOptions({ zoomInTitle: "Przybliż", zoomOutTitle: "Oddal" });
  const prefix = L.Control.Attribution.prototype.options.prefix;
  if (typeof prefix === "string") {
    L.Control.Attribution.mergeOptions({ prefix: prefix.replace(/title="[^"]*"/, 'title="Leaflet: biblioteka JavaScript do map interaktywnych"') });
  }
}

const TABS = { about, radio, meteo, aerodrome, adciv, admil, advfr, callsign, aircraft, map, inop, docs, phraseology, checklist, emergency, admin };
const views = document.getElementById("views");
const mounted = {};
const ctx = { config: null, open };

function open(tab, arg) {
  if (!TABS[tab]) tab = "about";
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  views.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  if (!mounted[tab]) {
    const el = document.createElement("section");
    el.className = "view";
    views.append(el);
    mounted[tab] = { el, api: TABS[tab].mount(el, ctx) || {} };
  }
  mounted[tab].el.classList.add("active");
  mounted[tab].api.activate?.(arg);
  const hash = "#" + tab + (arg ? "/" + arg : "");
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-tab]");
  if (b) open(b.dataset.tab);
});

window.addEventListener("hashchange", () => {
  const [tab, arg] = location.hash.slice(1).split("/");
  if (tab) open(tab, arg);
});

function tick() {
  const d = new Date();
  document.getElementById("utc").textContent = d.toISOString().slice(11, 19) + "Z";
}
setInterval(tick, 1000);
tick();

(async () => {
  try {
    ctx.config = await api("/api/config");
    document.getElementById("airac").textContent = `AIRAC ${ctx.config.airac.ident}`;
    document.getElementById("airac").title = `od ${ctx.config.airac.effective}, następny ${ctx.config.airac.next}`;
  } catch (e) {
    ctx.config = { links: {}, default_aerodrome: "EPWA", airac: {} };
    console.error(e);
  }
  await showUser();
  // po uruchomieniu zawsze strona startowa "?" (ABOUT), niezależnie od adresu zapamiętanego w przeglądarce
  open("about");
})();

// zalogowany użytkownik pod zegarem
async function showUser() {
  const me = await api("/auth/me").catch(() => null);
  ctx.me = me;
  document.querySelector('#tabs button[data-tab="admin"]').hidden = !me?.admin;
  if (!me?.user) return;
  const u = me.user;
  const box = document.getElementById("userbox");
  box.innerHTML = `<div class="who" title="CID ${esc(u.cid)}${u.subdivision ? " · " + esc(u.subdivision) : ""}">${esc(u.name || "CID " + u.cid)}</div>
    <div class="hint">${esc(u.cid)} · ${esc(u.rating_short || "")}${me.mode === "dev" ? ' · <span class="dev">DEV</span>' : ""}</div>
    <form method="post" action="/auth/logout"><button type="submit">Wyloguj</button></form>`;
  box.hidden = false;
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("Service worker:", e));
}
