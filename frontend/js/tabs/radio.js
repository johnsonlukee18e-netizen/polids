import { aerodromeNames, api, atcPositions, esc, hhmm, positionTip, subtabs, vatsimBookings, vatsimOnline } from "../api.js";
import { atcPanes, drawFirs, drawSectors, loadFirs, loadVacs, sectorOwners } from "../airspace.js";

const TYPE_ORDER = ["CTR", "FSS", "APP", "DEP", "TWR", "GND", "DEL", "ATIS"];
// Lotniska komunikacyjne z AIP IFR, wojskowe; pozostałe EP** traktujemy jak VFR
const IFR = ["EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY", "EPWA", "EPWR", "EPZG"];
const MIL = ["EPCE", "EPDA", "EPDE", "EPIR", "EPKS", "EPLK", "EPLY", "EPMB", "EPMI", "EPMM", "EPOK", "EPPR", "EPPW", "EPSN", "EPTM"];
const NEIGHBOURS = [
  { id: "edww", label: "EDWW", title: "Niemcy (Bremen, Berlin)", test: (p) => ["EDWW", "EDDB", "EDAH"].includes(p) },
  { id: "edmm", label: "EDMM", title: "Niemcy (München, Rhein, Dresden, Leipzig)", test: (p) => p.startsWith("ED") && !["EDWW", "EDDB", "EDAH"].includes(p) },
  { id: "cz", label: "LKAA", title: "Czechy (Praha)", test: (p) => p.startsWith("LK") },
  { id: "sk", label: "LZBB", title: "Słowacja (Bratislava)", test: (p) => p.startsWith("LZ") },
  { id: "ua", label: "UKLV", title: "Ukraina (Lviv)", test: (p) => p.startsWith("UK") },
  { id: "by", label: "UMMV", title: "Białoruś (Minsk)", test: (p) => p.startsWith("UM") && p !== "UMKK" },
  { id: "kal", label: "UMKK", title: "Rosja (Kaliningrad)", test: (p) => p === "UMKK" || p.startsWith("RU-") },
  { id: "lt", label: "EYVL", title: "Litwa (Vilnius)", test: (p) => p.startsWith("EY") },
  { id: "se", label: "ESAA", title: "Szwecja", test: (p) => p.startsWith("ES") },
  { id: "dk", label: "EKDK", title: "Dania", test: (p) => p.startsWith("EK") },
];
const isOther = (p) => !p.startsWith("EP") && !NEIGHBOURS.some((n) => n.test(p));

const typeOf = (cs) => cs.split("_").pop();
// polskie częstotliwości FIS (Warszawa Information) przenosimy do EPWW ACC; informacje lotniskowe (EPBC, EPML)
// zostają przy lotniskach, a FIS sąsiadów (Sweden, Kaunas, Kaliningrad Information) w zakładkach ich FIR-ów
const isFis = (p) => p.callsign.startsWith("EP") && /information/i.test(p.name) && /_(APP|CTR)$/.test(p.callsign);
const byType = (a, b) => TYPE_ORDER.indexOf(typeOf(a.callsign)) - TYPE_ORDER.indexOf(typeOf(b.callsign)) || a.callsign.localeCompare(b.callsign);
const isAcc = (p) => ["CTR", "FSS"].includes(typeOf(p.callsign));

// Grupy wg prefiksu; z ctrFirst najpierw grupy ze stanowiskami ACC/CTR, potem lotniska (APP, TWR…)
function group(list, keyFn, { ctrFirst = false } = {}) {
  const g = {};
  list.forEach((p) => (g[keyFn(p)] ||= []).push(p));
  const rank = (ps) => (ctrFirst && ps.some(isAcc) ? 0 : 1);
  return Object.entries(g).sort(([a, pa], [b, pb]) => rank(pa) - rank(pb) || a.localeCompare(b)).map(([k, ps]) => [k, ps.sort(byType)]);
}

// Stan sieci wspólny dla wszystkich podzakładek: {online: {callsign: kontroler}, bookings: {callsign: [...]}}
const st = { online: {}, bookings: {}, msg: "" };
async function refreshNetwork() {
  const [on, bk] = await Promise.allSettled([vatsimOnline(), vatsimBookings()]);
  st.online = on.status === "fulfilled" ? on.value.positions : {};
  st.onlineRaw = on.status === "fulfilled" ? on.value : null;
  st.bookings = bk.status === "fulfilled" ? bk.value : {};
  const errs = [on, bk].filter((r) => r.status === "rejected").map((r) => r.reason.message);
  st.msg = (on.status === "fulfilled" ? `VATSIM: ${Object.keys(st.online).length} stanowisk online · ${hhmm(new Date().toISOString())}` : "")
    + (errs.length ? ` <span class="error">${esc(errs.join(" · "))}</span>` : "");
}

// VACS (vacs-data, profil ACC_EPWW): etykiety stanowisk sąsiadów z dopiskiem wysokości i łańcuchem controlled_by.
// Bez danych (błąd /api/nav/vacs) zostają ID z pliku .ese.
const VACS_URL = "https://github.com/vacs-project/vacs-data";
let vacs = null;
let vacsP = null;
const loadVacsIndex = () => (vacsP ||= loadVacs().then(indexVacs).catch(() => { vacsP = null; return null; }));

// {pos: {callsign .ese: {label, alt, keys}}, width}; klucze FMP/TMU pomijamy (to nie są stanowiska z .ese)
function indexVacs(d) {
  const by = {};
  (d.neighbours || []).filter((n) => !n.fmp && n.ese?.callsign).forEach((n) => (by[n.ese.callsign] ||= []).push(n));
  const pos = {};
  Object.entries(by).forEach(([cs, keys]) => {
    // wspólne stanowisko kilku kluczy: wspólny początek etykiety + reszty po "/" (LKAA N + LKAA S -> LKAA N/S)
    const words = keys.map((k) => k.label.split(" "));
    let i = 0;
    while (words.every((w) => i < w.length - 1 && w[i] === words[0][i])) i++;
    const tail = (w) => w.slice(i).join(" ");
    const tails = [...new Set(words.map(tail))];
    pos[cs] = {
      label: [...words[0].slice(0, i), tails.join("/")].join(" "),
      alt: [...new Set(keys.map((k) => k.alt).filter(Boolean))].join("/"),
      keys: keys.map((k, j) => ({ label: k.label, alt: k.alt, tail: tails.length > 1 ? tail(words[j]) : "", chain: k.controlled_by || [] })),
    };
  });
  const width = Math.max(6, ...Object.values(pos).map((v) => v.label.length));
  return { pos, width, commit: (d.commit || "").slice(0, 7), date: d.commit_date || "" };
}

// dopisek wysokości w formie VACS (+365, -195, 335-365) -> opis w dymku
const altTip = (a) => a.split("/").map((x) => x.replace(/^\+(\d+)$/, "powyżej FL$1").replace(/^-(\d+)$/, "do FL$1")
  .replace(/^(\d+)-(\d+)$/, "FL$1–FL$2")).join(" / ");

// Dziedziczenie VACS: główne stanowisko offline -> pierwsze zalogowane dalej w łańcuchu controlled_by danego klucza
function cover(cs, v) {
  if (st.online[cs]) return "";
  const hits = v.keys.map((k) => [k, k.chain.slice(k.chain.indexOf(cs) + 1).find((c) => st.online[c])]).filter(([, c]) => c);
  if (!hits.length) return "";
  const same = hits.length === v.keys.length && hits.every(([, c]) => c === hits[0][1]);
  // kilka różnych przejęć (scalony wiersz) zawija się w obrębie wiersza zamiast wychodzić za prawą krawędź
  return `<span class="inhs">${(same ? [hits[0]] : hits).map(([k, c]) => {
    const on = st.online[c];
    const tip = `${k.label}${k.alt ? " " + k.alt : ""}: ${cs} offline – wg łańcucha VACS (controlled_by) obszar przejmuje ${c}`
      + `${on.name ? `, ${on.name}` : ""}${on.frequency ? `, ${on.frequency}` : ""}`;
    return `<span class="inh" title="${esc(tip)}">${same ? "" : `${esc(k.tail)} `}<b>→ ${esc(c)}</b> (online)</span>`;
  }).join("")}</span>`;
}

// kolumna ID: etykieta VACS + dopisek wysokości; sąsiedzi spoza profilu – ID z .ese, wyszarzone; EP bez zmian
function pidHtml(p, v) {
  if (!vacs) return `<span class="pid">${esc(p.position_id || "")}</span>`;
  if (v) {
    const tip = [`VACS ACC_EPWW · ID w pliku .ese: ${p.position_id || "–"}`,
      ...v.keys.map((k) => `${k.label}${k.alt ? " " + k.alt : ""}: ${k.chain.join(" → ")}`)].join("\n");
    return `<span class="pid vacs"><span title="${esc(tip)}">${esc(v.label)}</span>${v.alt ? `<b class="alt" title="${esc(altTip(v.alt))}">${esc(v.alt)}</b>` : ""}</span>`;
  }
  const ese = !p.callsign.startsWith("EP");
  return `<span class="pid${ese ? " ese" : ""}"${ese ? ` title="ID z pliku .ese – stanowiska nie ma w profilu VACS ACC_EPWW"` : ""}>${esc(p.position_id || "")}</span>`;
}

// linijka o źródle etykiet, gdy na liście są stanowiska z profilu VACS
function vacsNote(list) {
  if (!vacs || !list.some((p) => vacs.pos[p.callsign])) return "";
  return `<p class="hint vacs-note">ID pozycji wg profilu VACS ACC_EPWW (<a href="${VACS_URL}" target="_blank" rel="noopener"
    title="vacs-project/vacs-data, commit ${esc(vacs.commit)} z ${esc(vacs.date)}">vacs-data</a>, CC BY-NC-SA 4.0)</p>`;
}

function row(p) {
  const on = st.online[p.callsign];
  const books = st.bookings[p.callsign] || [];
  const cls = on ? "on" : books.length ? "booked" : "";
  const tip = positionTip(on, books);
  const v = vacs?.pos[p.callsign];
  const who = on ? `<b class="who">${esc(on.name || on.callsign)}</b>` : books.length ? `<span class="booked-txt">booking ${hhmm(books[0].start)}–${hhmm(books[0].end)}</span>` : "";
  return `<div class="radio-row ${cls}" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="freq ${cls}">${esc(p.frequency)}</span>
    ${pidHtml(p, v)}<span class="cs">${esc(p.callsign)}</span><span class="nm">${esc(p.name)}</span>${who}${v ? cover(p.callsign, v) : ""}</div>`;
}

let names = {};
function groupsHtml(groups, empty = "Brak stanowisk.") {
  return groups.length ? groups.map(([name, ps]) => `<div class="radio-group" data-group="${esc(name)}"><h3>${esc(name)}${names[name] ? ` <small>${esc(names[name])}</small>` : ""}</h3>${ps.map(row).join("")}</div>`).join("")
    : `<p class="hint">${esc(empty)}</p>`;
}

// Widok listy, odświeżany razem ze stanem sieci. single = jedna kolumna z większym tekstem (LOTNISKA, sąsiedzi),
// wide = szersza kolumna ID na etykiety VACS z dopiskiem wysokości (sąsiedzi, INNE, ONLINE)
function listView(build, { single = true, wide = false } = {}) {
  return (pane) => {
    pane.innerHTML = `<div class="netstatus hint"></div><div class="body radio-list ${single ? "single" : ""}"><p class="hint">Ładowanie…</p></div>`;
    const draw = async () => {
      try {
        const [ps, n, v] = await Promise.all([atcPositions(), aerodromeNames().catch(() => ({})), loadVacsIndex()]);
        names = n;
        vacs = v;
        const body = pane.querySelector(".body");
        body.classList.toggle("vacs", wide && !!vacs);
        if (vacs) body.style.setProperty("--pid-ch", vacs.width);
        body.innerHTML = build(ps);
        pane.querySelector(".netstatus").innerHTML = st.msg;
      } catch (e) { pane.querySelector(".body").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    };
    // szybki skok do lotniska z paska przycisków (LOTNISKA)
    pane.addEventListener("click", (e) => {
      const b = e.target.closest("[data-jump]");
      if (!b) return;
      const g = pane.querySelector(`.radio-group[data-group="${CSS.escape(b.dataset.jump)}"]`);
      // przewijamy tak, żeby nagłówek lotniska wypadł tuż pod przyklejonym paskiem przycisków
      if (g) pane.scrollBy({ top: g.getBoundingClientRect().top - pane.getBoundingClientRect().top - b.closest(".ad-jump").offsetHeight - 6, behavior: "smooth" });
    });
    draw();
    refreshNetwork().then(draw);
    const timer = setInterval(() => refreshNetwork().then(draw), 60000);
    return { destroy: () => clearInterval(timer) };
  };
}

function aerodromes(ps) {
  const ad = ps.filter((p) => p.prefix?.startsWith("EP") && p.prefix !== "EPWW" && !isFis(p));
  const kinds = [["Lotniska komunikacyjne (AIP IFR)", "IFR", (x) => IFR.includes(x)], ["Lotniska VFR", "VFR", (x) => !IFR.includes(x) && !MIL.includes(x)],
    ["Lotniska wojskowe", "MIL", (x) => MIL.includes(x)]].map(([title, short, filter]) => ({ title, short, g: group(ad.filter((p) => filter(p.prefix)), (p) => p.prefix) }));
  // pasek przycisków na górze: kliknięcie przewija do lotniska; zielony = ktoś jest online, pomarańczowy = rezerwacja
  const state = (ps) => (ps.some((p) => st.online[p.callsign]) ? "on" : ps.some((p) => st.bookings[p.callsign]?.length) ? "booked" : "");
  const jump = `<div class="ad-jump">${kinds.filter((k) => k.g.length).map((k) => `<span class="aj-kind">${k.short}</span>${k.g.map(([icao, ps]) =>
    `<button data-jump="${esc(icao)}" class="${state(ps)}" title="${esc(names[icao] || "")}">${esc(icao)}</button>`).join("")}`).join("")}</div>`;
  return jump + kinds.map((k) => (k.g.length ? `<h2 class="radio-section">${k.title}</h2>${groupsHtml(k.g)}` : "")).join("");
}

// EPWW ACC: lista stanowisk (najpierw CTR, niżej FIS) i mapa sektorów z aktualnie zalogowanymi
function accView(pane) {
  pane.innerHTML = `<div class="radio-acc">
    <div class="acc-list"><div class="netstatus hint"></div><div class="body"><p class="hint">Ładowanie…</p></div></div>
    <div class="acc-map"><div class="toolbar">
        <label>Poziom FL <input type="number" class="fl" value="300" min="0" max="660" step="5" style="width:80px"></label>
        <label><input type="checkbox" class="split"> podział pełny (wszystkie sektory)</label>
        <span class="hint info"></span></div>
      <div class="map"></div></div>
  </div>`;
  const $ = (s) => pane.querySelector(s);
  const map = L.map($(".map"), { zoomSnap: 0.25, attributionControl: false }).setView([52.0, 19.3], 6.25);
  const firLayer = L.layerGroup().addTo(map);
  const secLayer = L.layerGroup().addTo(map);
  let positions = [];
  let fitted = false;
  let epwwBounds = null;
  // mapa tworzona w ukrytym widoku ma rozmiar 0×0 (fitBounds dałby zoom NaN); dopasowanie czeka, aż kontener będzie widoczny
  const fit = () => {
    map.invalidateSize();
    if (!fitted && epwwBounds && map.getSize().x > 40) { map.fitBounds(epwwBounds, { padding: [10, 10], animate: false }); fitted = true; }
  };

  const drawList = () => {
    const acc = positions.filter((p) => p.prefix === "EPWW" && !isFis(p));
    const fis = positions.filter(isFis).sort((a, b) => a.callsign.localeCompare(b.callsign));
    $(".body").innerHTML = groupsHtml([["EPWW ACC · Warszawa Radar", acc.sort(byType)]]) + groupsHtml([["FIS · Warszawa Information", fis]]);
    $(".netstatus").innerHTML = st.msg;
  };
  const drawMap = async () => {
    const level = parseInt($(".fl").value || "0", 10);
    const [gj, firs] = await Promise.all([api(`/api/nav/sectors?fir=EPWW&level_ft=${level * 100}`), loadFirs().catch(() => null)]);
    firLayer.clearLayers();
    secLayer.clearLayers();
    if (firs) {
      drawFirs(firLayer, firs, st.onlineRaw?.firs || {}, { panes: atcPanes(map) });
      const epww = firs.features.find((f) => f.properties.id === "EPWW");
      if (epww) {
        const outline = L.geoJSON(epww, { interactive: false, style: { color: "#9cdc84", weight: 2, fill: false } }).addTo(firLayer);
        epwwBounds = outline.getBounds();
        fit();
      }
    }
    const online = !$(".split").checked && st.onlineRaw ? sectorOwners(gj, positions, st.online) : null;
    drawSectors(secLayer, gj, online);
    $(".info").textContent = online ? `${Object.keys(online.sector_owner).length}/${gj.features.length} sektorów obsadzonych` : `${gj.features.length} sektorów na FL${level}`;
  };
  const draw = () => { drawList(); drawMap().catch((e) => { $(".info").textContent = e.message; }); };
  atcPositions().then((ps) => { positions = ps; draw(); refreshNetwork().then(draw); });
  $(".fl").addEventListener("change", draw);
  $(".split").addEventListener("change", draw);
  const timer = setInterval(() => refreshNetwork().then(draw), 60000);
  setTimeout(fit, 50);
  return { destroy: () => { clearInterval(timer); map.remove(); } };
}

export default {
  mount(root) {
    subtabs(root, [
      { id: "acc", label: "EPWW ACC", fill: true, render: accView },
      { id: "ad", label: "LOTNISKA", render: listView(aerodromes) },
      { sep: true },
      ...NEIGHBOURS.map((n) => ({ id: n.id, label: n.label, render: listView((ps) => {
        const list = ps.filter((p) => p.prefix && n.test(p.prefix));
        return `<h2 class="radio-section">${esc(n.title)}</h2>` + vacsNote(list) + groupsHtml(group(list, (p) => p.prefix, { ctrFirst: true }));
      }, { wide: true }) })),
      { id: "other", label: "INNE", render: listView((ps) => {
        const list = ps.filter((p) => p.prefix && isOther(p.prefix));
        return `<h2 class="radio-section">Pozostałe (UIR, Eurocontrol)</h2>` + vacsNote(list) + groupsHtml(group(list, (p) => p.prefix, { ctrFirst: true }));
      }, { wide: true }) },
      { sep: true },
      { id: "online", label: "ONLINE", render: listView((ps) => {
        const list = ps.filter((p) => st.online[p.callsign] || st.bookings[p.callsign]);
        const known = new Set(list.map((p) => st.online[p.callsign]?.callsign));
        // kontrolerzy EP** spoza pliku .ese (np. nowe stanowiska) też są na liście
        const extra = (st.onlineRaw?.controllers || []).filter((c) => !known.has(c.callsign) && !c.callsign.endsWith("_OBS"))
          .map((c) => ({ callsign: c.callsign, name: "(spoza pliku .ese)", frequency: c.frequency, prefix: c.callsign.split("_")[0], _on: c }));
        extra.forEach((p) => { st.online[p.callsign] ||= p._on; });
        return vacsNote(list) + groupsHtml(group([...list, ...extra], (p) => p.prefix, { ctrFirst: true }), "Nikt z EPWW ani sąsiadów nie jest teraz online i nie ma rezerwacji na dziś.");
      }, { wide: true }) },
    ]);
  },
};
