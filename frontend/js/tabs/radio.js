import { aerodromeNames, esc, hhmm, positionTip, subtabs } from "../api.js";
import { geoView } from "../geo.js";
import { displayName, loadDisplayNames } from "../posname.js";
import { sectorSplit } from "../sectorsplit.js";
import { sliceChain, sliceOwner } from "../coverage.js";
import { loadVacs } from "../airspace.js";
import * as R from "../radiostate.js";

const TYPE_ORDER = ["CTR", "FSS", "APP", "DEP", "TWR", "GND", "DEL", "ATIS"];
// Lotniska komunikacyjne z AIP IFR, wojskowe; pozostałe EP** traktujemy jak VFR
const IFR = ["EPBY", "EPGD", "EPKK", "EPKT", "EPLB", "EPLL", "EPMO", "EPPO", "EPRA", "EPRZ", "EPSC", "EPSY", "EPWA", "EPWR", "EPZG"];
const MIL = ["EPCE", "EPDA", "EPDE", "EPIR", "EPKS", "EPLK", "EPLY", "EPMB", "EPMI", "EPMM", "EPOK", "EPPR", "EPPW", "EPSN", "EPTM"];
// Sąsiedzi: stanowiska z vacs-data wg katalogu FIR-u (fir), z pliku .ese bez vacs-data wg prefiksu
const NEIGHBOURS = [
  { id: "edww", label: "EDWW", title: "Niemcy (Bremen, Berlin, Hamburg)", firs: ["EDWW"], test: (p) => ["EDWW", "EDDB", "EDAH"].includes(p) },
  { id: "edmm", label: "EDMM", title: "Niemcy (München, Rhein, Dresden, Leipzig)", firs: ["EDMM", "EDUU"], test: (p) => p.startsWith("ED") && !["EDWW", "EDDB", "EDAH"].includes(p) },
  { id: "cz", label: "LKAA", title: "Czechy (Praha)", firs: ["LK"], test: (p) => p.startsWith("LK") },
  { id: "sk", label: "LZBB", title: "Słowacja (Bratislava)", firs: ["LZ"], test: (p) => p.startsWith("LZ") },
  { id: "ua", label: "UKLV", title: "Ukraina (Lviv)", firs: [], test: (p) => p.startsWith("UK") },
  { id: "by", label: "UMMV", title: "Białoruś (Minsk)", firs: [], test: (p) => p.startsWith("UM") && p !== "UMKK" },
  { id: "kal", label: "UMKK", title: "Rosja (Kaliningrad)", firs: ["UMKK"], test: (p) => p === "UMKK" || p.startsWith("RU-") },
  { id: "lt", label: "EYVL", title: "Litwa (Vilnius)", firs: ["EY"], test: (p) => p.startsWith("EY") },
  { id: "se", label: "ESAA", title: "Szwecja", firs: ["ES"], test: (p) => p.startsWith("ES") },
  { id: "dk", label: "EKDK", title: "Dania", firs: ["EK"], test: (p) => p.startsWith("EK") },
];
const tabOf = (p) => NEIGHBOURS.find((n) => (p.fir ? n.firs.includes(p.fir) : p.prefix && n.test(p.prefix)));
const isOther = (p) => !p.prefix?.startsWith("EP") && !tabOf(p);

const typeOf = (cs) => cs.split("_").pop();
// polskie częstotliwości FIS (Warszawa Information) przenosimy do EPWW ACC; informacje lotniskowe (EPBC, EPML)
// zostają przy lotniskach, a FIS sąsiadów (Sweden, Kaunas, Kaliningrad Information) w zakładkach ich FIR-ów
const isFis = (p) => p.callsign.startsWith("EP") && /information/i.test(p.name || "") && /_(APP|CTR)$/.test(p.callsign);
const byType = (a, b) => TYPE_ORDER.indexOf(typeOf(a.callsign)) - TYPE_ORDER.indexOf(typeOf(b.callsign)) || a.callsign.localeCompare(b.callsign);
const isAcc = (p) => ["CTR", "FSS"].includes(typeOf(p.callsign));

// Grupy wg prefiksu; z ctrFirst najpierw grupy ze stanowiskami ACC/CTR, potem lotniska (APP, TWR…)
function group(list, keyFn, { ctrFirst = false } = {}) {
  const g = {};
  list.forEach((p) => (g[keyFn(p)] ||= []).push(p));
  const rank = (ps) => (ctrFirst && ps.some(isAcc) ? 0 : 1);
  return Object.entries(g).sort(([a, pa], [b, pb]) => rank(pa) - rank(pb) || a.localeCompare(b)).map(([k, ps]) => [k, ps.sort(byType)]);
}

const st = R.state;
// 1 stanowisko, 2–4 stanowiska (poza 12–14), 5+ stanowisk
const nStan = (n) => `${n} ${n === 1 ? "stanowisko" : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "stanowiska" : "stanowisk"}`;
// stan sieci z ostatniego udanego pobrania; po błędzie "VATSIM: brak danych" i komunikat (bez starej godziny)
const netMsg = () => esc(R.netText((n) => `${nStan(n)} online`)) + (st.err ? ` <span class="error">${esc(st.err)}</span>` : "");

// VACS (vacs-data, profil ACC_EPWW): etykiety stanowisk sąsiadów z dopiskiem wysokości. Bez danych zostaje displayName.
const VACS_URL = "https://github.com/vacs-project/vacs-data";
let vacs = null;
let vacsIdx = null;
const loadVacsIndex = () => (vacsIdx ||= R.loadVacsData().then(indexVacs).catch(() => { vacsIdx = null; return null; }));

// {pos: {callsign .ese: {label, alt, keys}}}; klucze FMP/TMU pomijamy (to nie są stanowiska z .ese)
function indexVacs(d) {
  const by = {};
  (d.neighbours || []).filter((n) => !n.fmp && n.ese?.callsign).forEach((n) => (by[n.ese.callsign] ||= []).push(n));
  const pos = {};
  Object.entries(by).forEach(([cs, keys]) => {
    // wspólne stanowisko kilku kluczy: wspólny początek etykiety + reszty po "/" (LKAA N + LKAA S -> LKAA N/S)
    const words = keys.map((k) => k.label.split(" "));
    let i = 0;
    while (words.every((w) => i < w.length - 1 && w[i] === words[0][i])) i++;
    const tails = [...new Set(words.map((w) => w.slice(i).join(" ")))];
    pos[cs] = {
      label: [...words[0].slice(0, i), tails.join("/")].join(" "),
      alt: [...new Set(keys.map((k) => k.alt).filter(Boolean))].join("/"),
      keys: keys.map((k) => ({ label: k.label, alt: k.alt })),
    };
  });
  return { pos, commit: (d.commit || "").slice(0, 7), date: d.commit_date || "" };
}

// dopisek wysokości w formie VACS (+365, -195, 335-365) -> opis w dymku
const altTip = (a) => a.split("/").map((x) => x.replace(/^\+(\d+)$/, "powyżej FL$1").replace(/^-(\d+)$/, "do FL$1")
  .replace(/^(\d+)-(\d+)$/, "FL$1–FL$2")).join(" / ");

// Kto przejmuje wycinki stanowiska offline: dla wycinków, w których jest pierwsze w kolejności przejmowania (coverage.js:
// sektory ACC wg /api/nav/ownership, TMA/CTR: APP/TWR z pliku .ese, potem ACC), pierwsze zalogowane dalej w tej kolejności.
let sectors = null, own = null;
function cover(cs) {
  if (st.online[cs] || !sectors) return "";
  const onl = new Set(R.onlineList());
  const hits = new Map();
  sectors.features.forEach((f) => {
    if (sliceChain(f.properties, own).chain[0] !== cs) return;
    const o = sliceOwner(f.properties, onl, own);
    if (o && o !== cs) (hits.get(o) || hits.set(o, new Set()).get(o)).add(f.properties.group);
  });
  if (!hits.size) return "";
  return `<span class="inhs">${[...hits].map(([o, groups]) => {
    const on = st.online[o];
    const tip = `${displayName(cs)} offline – wg kolejności przejmowania wycinki (${[...groups].join(", ")}) przejmuje ${displayName(o)} (${o})`
      + `${on?.name ? `, ${on.name}` : ""}${on?.frequency ? `, ${on.frequency}` : ""}`;
    return `<span class="inh" title="${esc(tip)}"><b>→ ${esc(displayName(o))}</b> (online)</span>`;
  }).join("")}</span>`;
}

// kolumna ID: etykieta VACS + dopisek wysokości (stanowiska z profilu ACC_EPWW), poza tym displayName (etykieta
// kafelka GEO, np. EPWA_I_APP → WA C FIS, albo nazwa w stylu VACS)
function pidHtml(p) {
  const v = vacs?.pos[p.callsign];
  if (v) {
    const tip = [`VACS ACC_EPWW · ${p.callsign}${p.position_id ? ` · ID w pliku .ese: ${p.position_id}` : ""}`,
      ...v.keys.map((k) => `${k.label}${k.alt ? " " + k.alt : ""}`)].join("\n");
    return `<span class="pid vacs"><span title="${esc(tip)}">${esc(v.label)}</span>${v.alt ? `<b class="alt" title="${esc(altTip(v.alt))}">${esc(v.alt)}</b>` : ""}</span>`;
  }
  const src = p.position_id ? `ID w pliku .ese: ${p.position_id}` : p.nb_source ? `stanowisko z pliku .ese sąsiada (${p.nb_source})` : "stanowisko spoza pliku .ese (vacs-data)";
  return `<span class="pid" title="${esc(src)}">${esc(displayName(p.callsign))}</span>`;
}
const pidLen = (p) => (vacs?.pos[p.callsign] ? vacs.pos[p.callsign].label.length + 5 : displayName(p.callsign).length);

// linijka o klikaniu pozycji i o źródle etykiet
function listNote(list) {
  const parts = [`Kliknij pozycję, żeby włączyć ją w symulacji zasięgu (<a data-goto="geo">mapa w GEO</a>).`];
  if (vacs && list.some((p) => vacs.pos[p.callsign] || !p.in_ese)) {
    parts.push(`Etykiety i stanowiska spoza pliku .ese: <a href="${VACS_URL}" target="_blank" rel="noopener"
      title="vacs-project/vacs-data, commit ${esc(vacs.commit)} z ${esc(vacs.date)}">vacs-data</a> (CC BY-NC-SA 4.0).`);
  }
  return `<p class="hint pickhint">${parts.join(" ")}</p>`;
}

function row(p, colors, active) {
  const on = p._on || st.online[p.callsign];
  const books = st.bookings[p.callsign] || [];
  const cls = on ? "on" : books.length ? "booked" : "";
  const tip = positionTip(on, books);
  const act = active.has(p.callsign);
  const who = on ? `<b class="who">${esc(on.name || on.callsign)}</b>` : books.length ? `<span class="booked-txt">booking ${hhmm(books[0].start)}–${hhmm(books[0].end)}</span>` : "";
  const nm = p.name ? `<span class="nm" title="${esc(p.name)}">${esc(p.name)}</span>`
    : `<span class="nm fir" title="Stanowisko tylko w vacs-data (bez nazwy w pliku .ese)">${esc(p.fir_name || "")}</span>`;
  return `<div class="radio-row pick ${cls}${act ? " act" : ""}" data-cs="${esc(p.callsign)}" ${act ? `style="--pc:${colors[p.callsign]}"` : ""}
    ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="act-mark"></span><span class="freq ${cls}">${esc(p.frequency)}</span>
    ${pidHtml(p)}<span class="cs">${esc(p.callsign)}</span>${nm}${who}${cover(p.callsign)}</div>`;
}

let names = {};
function groupsHtml(groups, empty = "Brak stanowisk.") {
  const active = R.activeSet(), colors = R.colorMap(active);
  // sąsiedzi: znaczek koloru FIR-u (jak kafelki GEO) przed nazwą grupy
  const sw = (ps) => {
    const k = R.firKey(ps[0]?.callsign, ps[0]?.fir);
    return k ? `<i class="fir-sw" style="background:${R.FIR_COLORS[k].c}" title="${esc(R.FIR_COLORS[k].name)}"></i>` : "";
  };
  return groups.length ? groups.map(([name, ps]) => `<div class="radio-group" data-group="${esc(name)}"><h3>${sw(ps)}${esc(name)}${names[name] ? ` <small>${esc(names[name])}</small>` : ""}</h3>${ps.map((p) => row(p, colors, active)).join("")}</div>`).join("")
    : `<p class="hint">${esc(empty)}</p>`;
}

// Widok listy, odświeżany razem ze stanem sieci i symulacją. wide = szersza kolumna ID na etykiety VACS z dopiskiem wysokości.
function listView(build, { wide = false, goto } = {}) {
  return (pane) => {
    pane.innerHTML = `<div class="netstatus hint"></div><div class="body radio-list single"><p class="hint">Ładowanie…</p></div>`;
    let ps = null, err = "", alive = true;
    const draw = () => {
      // po przejściu do innej podzakładki panel należy już do niej (spóźnione dane nie mogą go nadpisać)
      if (!alive) return;
      pane.querySelector(".netstatus").innerHTML = netMsg();
      const body = pane.querySelector(".body");
      if (!ps) { body.innerHTML = err ? `<p class="error">${esc(err)}</p>` : `<p class="hint">Ładowanie…</p>`; return; }
      body.classList.toggle("vacs", wide && !!vacs);
      const top = pane.scrollTop;
      body.innerHTML = build(ps);
      const byCs = Object.fromEntries(ps.map((p) => [p.callsign, p]));
      const lens = [...body.querySelectorAll(".radio-row[data-cs]")].map((r) => pidLen(byCs[r.dataset.cs] || { callsign: r.dataset.cs }));
      body.style.setProperty("--pid-ch", Math.max(6, ...lens));
      pane.scrollTop = top;
    };
    Promise.all([R.loadPositions(), aerodromeNames().catch(() => ({})), loadVacsIndex(),
      R.loadSectors().catch(() => null), loadVacs().catch(() => null), loadDisplayNames()])
      .then(([p, n, v, s, o]) => { ps = p; names = n; vacs = v; sectors = s; own = o; draw(); })
      .catch((e) => { err = e.message; draw(); });
    // panel jest wspólny dla podzakładek: obsługę kliknięć zdejmujemy w destroy, inaczej kolejna lista
    // dostałaby drugą (kliknięcie wiersza przełączałoby pozycję dwa razy, czyli wcale)
    const onClick = (e) => {
      // szybki skok do lotniska z paska przycisków (LOTNISKA)
      const b = e.target.closest("[data-jump]");
      if (b) {
        const g = pane.querySelector(`.radio-group[data-group="${CSS.escape(b.dataset.jump)}"]`);
        // przewijamy tak, żeby nagłówek lotniska wypadł tuż pod przyklejonym paskiem przycisków
        if (g) pane.scrollBy({ top: g.getBoundingClientRect().top - pane.getBoundingClientRect().top - b.closest(".ad-jump").offsetHeight - 6, behavior: "smooth" });
        return;
      }
      const go = e.target.closest("[data-goto]");
      if (go) { goto?.(go.dataset.goto); return; }
      const r = e.target.closest(".radio-row[data-cs]");
      if (r && !e.target.closest("a")) R.toggle(r.dataset.cs);
    };
    pane.addEventListener("click", onClick);
    const unsub = R.on(draw);
    const unwatch = R.watch();
    return { destroy: () => { alive = false; pane.removeEventListener("click", onClick); unsub(); unwatch(); } };
  };
}

function aerodromes(ps, note) {
  const ad = ps.filter((p) => p.prefix?.startsWith("EP") && p.prefix !== "EPWW" && !isFis(p));
  const kinds = [["Lotniska komunikacyjne (AIP IFR)", "IFR", (x) => IFR.includes(x)], ["Lotniska VFR", "VFR", (x) => !IFR.includes(x) && !MIL.includes(x)],
    ["Lotniska wojskowe", "MIL", (x) => MIL.includes(x)]].map(([title, short, filter]) => ({ title, short, g: group(ad.filter((p) => filter(p.prefix)), (p) => p.prefix) }));
  // pasek przycisków na górze: kliknięcie przewija do lotniska; zielony = ktoś jest online, pomarańczowy = rezerwacja
  const state = (ps) => (ps.some((p) => st.online[p.callsign]) ? "on" : ps.some((p) => st.bookings[p.callsign]?.length) ? "booked" : "");
  const jump = `<div class="ad-jump">${kinds.filter((k) => k.g.length).map((k) => `<span class="aj-kind">${k.short}</span>${k.g.map(([icao, ps]) =>
    `<button data-jump="${esc(icao)}" class="${state(ps)}" title="${esc(names[icao] || "")}">${esc(icao)}</button>`).join("")}`).join("")}</div>`;
  return jump + note + kinds.map((k) => (k.g.length ? `<h2 class="radio-section">${k.title}</h2>${groupsHtml(k.g)}` : "")).join("");
}

export default {
  mount(root, ctx) {
    let geo = null, split = null;
    const goto = (id) => tabs.show(id);
    const tabs = subtabs(root, [
      { id: "geo", label: "GEO", fill: true, render: (p) => {
        geo ||= geoView(ctx);
        p.append(geo.el);
        geo.show();
        return { destroy: () => geo.hide() };
      } },
      { id: "sektoryzacja", label: "SEKTORYZACJA", fill: true, render: (p) => {
        split ||= sectorSplit(ctx);
        p.append(split.el);
        split.show();
        return { destroy: () => split.hide() };
      } },
      { id: "acc", label: "EPWW ACC", render: listView((ps) => {
        const acc = ps.filter((p) => p.prefix === "EPWW" && !isFis(p)).sort(byType);
        const fis = ps.filter(isFis).sort((a, b) => a.callsign.localeCompare(b.callsign));
        return listNote([]) + groupsHtml([["EPWW ACC · Warszawa Radar", acc]]) + groupsHtml([["FIS · Warszawa Information", fis]]);
      }, { goto }) },
      { id: "ad", label: "LOTNISKA", render: listView((ps) => aerodromes(ps, listNote([])), { goto }) },
      { sep: true },
      ...NEIGHBOURS.map((n) => ({ id: n.id, label: n.label, render: listView((ps) => {
        const list = ps.filter((p) => tabOf(p) === n);
        return `<h2 class="radio-section">${esc(n.title)}</h2>` + listNote(list) + groupsHtml(group(list, (p) => p.prefix, { ctrFirst: true }));
      }, { wide: true, goto }) })),
      { id: "other", label: "INNE", render: listView((ps) => {
        const list = ps.filter((p) => isOther(p));
        return `<h2 class="radio-section">Pozostałe (UIR, Eurocontrol)</h2>` + listNote(list) + groupsHtml(group(list, (p) => p.prefix, { ctrFirst: true }));
      }, { wide: true, goto }) },
      { sep: true },
      { id: "online", label: "ONLINE", render: listView((ps) => {
        const al = R.aliased();  // ten sam kontroler pod dwoma znakami: zostaje wiersz ze znakiem z pliku sąsiada
        const list = ps.filter((p) => !al.has(p.callsign) && (st.online[p.callsign] || st.bookings[p.callsign]));
        const known = new Set(list.map((p) => st.online[p.callsign]?.callsign));
        // zalogowani spoza pliku .ese i vacs-data (np. nowe stanowiska) też są na liście
        const extra = st.controllers.filter((c) => !known.has(c.callsign))
          .map((c) => ({ callsign: c.callsign, name: "spoza .ese i vacs-data", frequency: c.frequency, prefix: c.callsign.split("_")[0], _on: c }));
        return listNote(list) + groupsHtml(group([...list, ...extra], (p) => p.prefix, { ctrFirst: true }),
          st.ok ? "Nikt z EPWW ani sąsiadów nie jest teraz online i nie ma rezerwacji na dziś." : "Brak danych z sieci VATSIM.");
      }, { wide: true, goto }) },
    ]);
    return {};
  },
};
