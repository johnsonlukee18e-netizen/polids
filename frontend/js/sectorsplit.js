// RADIO → SEKTORYZACJA: kto przejmuje sektory ACC EPWW, TMA, CTA i CTR; osobna mapa dla warstw LOW, MID i HIGH.
// Sektory ACC: kolejność przejmowania z /api/nav/ownership (źródło w polu source_label: plik .ese albo tabela om.plvacc.pl ownerships).
// TMA, CTA i CTR: kolejność z chains.js – najpierw APP/TWR z listy OWNER pliku .ese, potem ACC (tabela top-down om.plvacc.pl albo .ese).
// Właściciel = pierwsze aktywne stanowisko z kolejności; bez nikogo przestrzeń jest nieobsadzona.
// Aktywne: "VATSIM teraz" (zalogowani w sieci) albo "symulacja" – wspólne z GEO (radiostate.js, zapamiętane w przeglądarce).
import { BASEMAPS, LIGHT_BASEMAPS, api, esc, h, hhmm, lsGet, lsSet } from "./api.js";
import { VACS_LAYERS, accLetter, altLabel, colorFor, drawFirs, fl, loadFirs, loadVacs } from "./airspace.js";
import { airspaceChain, tmaTopdown } from "./chains.js";
import { geomKey, labelPoint } from "./coverage.js";
import { displayName, loadDisplayNames } from "./posname.js";
import * as R from "./radiostate.js";

const LOW_MIN = 95, LOW_MAX = 330;  // przekrój LOW: FL095–FL330 (od FL335 jest już MID)
const LEVEL = { MID: 350, HIGH: 400 };  // MID i HIGH mają jeden kształt sektorów
const FREE = "#5a615a";
const LS = "map.split.";
const load = (k, d) => { try { const v = lsGet(LS + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const save = (k, v) => lsSet(LS + k, JSON.stringify(v));
// wszystkie wycinki sektorów EPWW (granice kształtów LOW, szczegóły sektora), raz na sesję
let allPromise = null;
const loadAll = () => (allPromise ||= api("/api/nav/sectors?fir=EPWW").catch((e) => { allPromise = null; throw e; }));
const flRange = (lo, hi) => `${fl(lo)}–${fl(hi)}`;
const altRange = (lo, hi) => `${altLabel(lo)}–${altLabel(hi)}`;
const plural = (n, one, few, many) => (n === 1 ? one : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? few : many);
// stanowiska lotniska na liście: APP, DEP, FIS, potem TWR
const AD_TYPES = ["APP", "DEP", "FIS", "FSS", "TWR"];
const adRank = (cs) => { const i = AD_TYPES.indexOf(cs.split("_").pop()); return i < 0 ? 9 : i; };

// Jedna kolejność dla wielu wycinków przestrzeni (warianty kierunków pracy, sektory zbliżania): a jest przed b, gdy tak jest
// w większej liczbie wycinków zawierających oba; wyżej stanowisko, które wyprzedza więcej innych. Przy remisie wyżej to, które
// jest pierwsze w większej liczbie wycinków, potem większa suma przewag i kolejność pierwszego wystąpienia.
// TMA Warszawa: WA DIR, WA S APP, WA N APP, WA APP.
function mergeOrder(lists) {
  const ids = [], cnt = new Map(), lead = new Map();
  const n = (a, b) => cnt.get(`${a}|${b}`) || 0;
  lists.forEach((l) => l.forEach((a, i) => {
    if (!ids.includes(a)) ids.push(a);
    if (!i) lead.set(a, (lead.get(a) || 0) + 1);
    l.slice(i + 1).forEach((b) => cnt.set(`${a}|${b}`, n(a, b) + 1));
  }));
  const wins = new Map(ids.map((a) => [a, ids.filter((b) => n(a, b) > n(b, a)).length]));
  const margin = new Map(ids.map((a) => [a, ids.reduce((s, b) => s + n(a, b) - n(b, a), 0)]));
  return [...ids].sort((a, b) => wins.get(b) - wins.get(a) || (lead.get(b) || 0) - (lead.get(a) || 0)
    || margin.get(b) - margin.get(a) || ids.indexOf(a) - ids.indexOf(b));
}
// a jest podciągiem b (ta sama kolejność, w b mogą być dodatkowe stanowiska): KK APP w KK E APP › KK APP
const isSub = (a, b) => { let i = 0; b.forEach((c) => { if (c === a[i]) i++; }); return i === a.length; };
// przybliżone pole wielokąta GeoJSON (stopnie², długość skrócona o cos szerokości) – do kolejności części przestrzeni
const ringArea = (r) => {
  if (!r?.length) return 0;
  const k = Math.cos((r[0][1] * Math.PI) / 180);
  return Math.abs(r.reduce((s, [x1, y1], i) => { const [x2, y2] = r[(i + 1) % r.length]; return s + x1 * y2 - x2 * y1; }, 0) * k) / 2;
};
const geoArea = (g) => (g?.type === "Polygon" ? [g.coordinates] : g?.type === "MultiPolygon" ? g.coordinates : [])
  .reduce((a, p) => a + ringArea(p[0]), 0);

export function sectorSplit(ctx) {
  const el = h(`<div class="ss-root">
    <div class="ss-maps">${VACS_LAYERS.map((ly) => `<section class="ss-mapcard" data-ly="${ly}">
      <div class="ss-mh"><b class="ss-ly">${ly}</b><span class="ss-rng"></span><span class="ss-sp"></span>
        ${ly === "LOW" ? `<span class="ss-cut" title="Poziom przekroju warstwy LOW (kształty sektorów zmieniają się z wysokością)">przekrój
          <span class="flbox">FL<input type="number" class="field ss-fl" min="${LOW_MIN}" max="${LOW_MAX}" step="5"></span></span>
          <button class="ss-step" data-step="-1" title="Poprzedni przedział (inne kształty sektorów)">◀</button>
          <button class="ss-step" data-step="1" title="Następny przedział (inne kształty sektorów)">▶</button>`
          : `<span class="ss-cut">przekrój <b>FL${LEVEL[ly]}</b></span>`}
        <button class="ss-fit" title="Pokaż całą FIR EPWW">⌂</button></div>
      <div class="ss-map map"></div></section>`).join("")}</div>
    <div class="ss-bottom">
      <section class="ss-card ss-poscard"><h3>Stanowiska <span class="ss-src"></span></h3>
        <div class="ss-modebar"><div class="seg ss-mode"><button data-mode="now">VATSIM teraz</button><button data-mode="sim">symulacja</button></div>
          <span class="ss-simbar"><button class="btn" data-act="online" title="Symulacja od stanowisk zalogowanych teraz w VATSIM">kopiuj online</button>
            <button class="btn" data-act="none" title="Wyłącz w symulacji wszystkie stanowiska z tej listy (ACC, APP i TWR)">wyłącz wszystkie</button></span></div>
        <div class="ss-status hint"></div>
        <div class="ss-pos"></div></section>
      <section class="ss-card"><h3>Kto co obsługuje <button class="ss-copy" title="Kopiuj podsumowanie jako tekst">kopiuj</button></h3>
        <div class="ss-sum"></div></section>
      <section class="ss-card ss-tmacard"><h3>TMA i CTR <span class="seg ss-tk"><button data-k="tma" title="TMA i CTA">TMA · CTA</button><button data-k="ctr" title="Strefy kontrolowane lotnisk">CTR</button></span>
        <span class="ss-tcnt"></span></h3>
        <div class="ss-tma"></div></section>
      <section class="ss-card"><h3 class="ss-dh">Szczegóły</h3><div class="ss-detail"></div></section>
    </div>
    <div class="ss-float"></div>
  </div>`);
  const $ = (s) => el.querySelector(s);
  const float = $(".ss-float");

  let own = null, all = null, errOwn = "";
  let secs = null, errSecs = "", posInfo = {};  // wycinki z /api/radio/sectors, stanowiska z /api/radio/positions (częstotliwości)
  let groups = [], gByKey = new Map(), sliceAt = new Map(), locals = [], localSet = new Set(), ads = [];
  let lowFl = Math.min(LOW_MAX, Math.max(LOW_MIN, parseInt(load("fl", 300), 10) || 300));
  let tk = load("tk", "tma") === "ctr" ? "ctr" : "tma";  // zakładka listy TMA i CTR
  let sel = null, selG = null, hoverPos = null, hoverG = null, hoverV = null, visible = false, fitted = false, baseName = null, active = new Set(), dirty = true;
  let colors = {};
  $(".ss-fl").value = lowFl;

  // --- trzy mapy, przesuwane i przybliżane razem
  const views = {};
  let syncing = false;
  VACS_LAYERS.forEach((ly, i) => {
    const card = el.querySelector(`.ss-mapcard[data-ly="${ly}"]`);
    const last = i === VACS_LAYERS.length - 1;  // atrybucja podkładu tylko na ostatniej mapie
    const map = L.map(card.querySelector(".ss-map"), { zoomSnap: 0.25, zoomDelta: 0.5, zoomAnimation: false, attributionControl: last, minZoom: 4, maxZoom: 11 })
      .setView([52.0, 19.3], 5.5, { animate: false });
    if (last) map.attributionControl.setPrefix(false);
    map.createPane("ssTma").style.zIndex = 420;  // TMA/CTR z listy nad sektorami ACC, pod obrysem FIR
    map.getPane("ssTma").style.pointerEvents = "none";
    map.createPane("ssFir").style.zIndex = 450;  // obrys FIR nad sektorami, pod etykietami
    map.getPane("ssFir").style.pointerEvents = "none";
    const v = { ly, card, map, base: null, firs: L.layerGroup().addTo(map), layer: L.layerGroup().addTo(map), items: [], gj: null, seq: 0 };
    map.on("move", () => {
      if (syncing || !visible) return;
      syncing = true;
      Object.values(views).forEach((o) => { if (o !== v) o.map.setView(map.getCenter(), map.getZoom(), { animate: false }); });
      syncing = false;
    });
    views[ly] = v;
  });
  const tmaLayer = L.layerGroup().addTo(views.LOW.map);
  let fitBounds = null, fitView = null;
  // widok taki jak po ostatnim dopasowaniu (ten sam zoom, środek przesunięty najwyżej o 3 px)
  const untouched = () => {
    const m = views.LOW.map;
    return !!fitView && m.getZoom() === fitView.z && m.latLngToContainerPoint(fitView.c).distanceTo(m.getSize().divideBy(2)) < 3;
  };
  const fit = () => {
    const v = views.LOW, size = v.map.getSize();
    if (!fitBounds || size.x < 40 || size.y < 40) return;  // ukryta mapa: bez dopasowania (zoom wyszedłby NaN)
    v.map.fitBounds(fitBounds, { padding: [6, 6], animate: false });
    fitted = true;
    fitView = { c: v.map.getCenter(), z: v.map.getZoom() };
  };
  el.querySelectorAll(".ss-fit").forEach((b) => b.addEventListener("click", fit));
  // zmiana rozmiaru okna: widok nieruszany przez użytkownika dopasowujemy na nowo do całej FIR
  views.LOW.map.on("resize", () => { if (visible && untouched()) fit(); });

  // podkład wspólny z mapą główną (wybór zapisany przez MAPA w "map.base")
  const syncBase = () => {
    const name = BASEMAPS[lsGet("map.base")] ? lsGet("map.base") : "dark";
    if (name === baseName) return;
    baseName = name;
    const light = LIGHT_BASEMAPS.includes(name);
    Object.values(views).forEach((v) => {
      if (v.base) v.map.removeLayer(v.base);
      v.base = BASEMAPS[name](L, ctx.config?.carto_api_key).addTo(v.map);
      v.base.bringToBack?.();
      v.map.getContainer().classList.toggle("light", light);
      v.map.getContainer().classList.toggle("white", name === "white");
    });
    drawFirOutline();
    redraw();
  };
  const theme = () => (LIGHT_BASEMAPS.includes(baseName)
    ? { edge: "#ffffff", fir: "#2b2f2b", freeEdge: "#8a918a", hole: "#9aa29a", holeFill: "#ffffff", hi: "#000000" }
    : { edge: "#050605", fir: "#d8e0d8", freeEdge: "#737b73", hole: "#4a524a", holeFill: "#000000", hi: "#ffffff" });

  // --- dane
  const name = (cs) => displayName(cs);
  const accShort = (cs) => name(cs).replace(/^EPWW /, "");  // w łańcuchu TMA po etykiecie "ACC"
  const freq = (cs) => own?.acc_positions?.[cs]?.frequency || posInfo[cs]?.frequency || "";
  const onlineOf = (cs) => R.state.online[cs] || null;
  const col = (cs) => colors[cs] || colorFor(cs);
  const mine = (cs) => order.includes(cs) || localSet.has(cs);  // stanowiska z list tego widoku (ACC, APP, TWR)
  const letters = () => Object.keys(own?.sectors || {}).sort();
  const chainOf = (s, ly) => own?.sectors?.[s]?.[ly] || [];
  const ownerOf = (s, ly) => chainOf(s, ly).find((c) => active.has(c)) || null;
  const sOwner = (s) => s.chain.find((c) => active.has(c)) || null;  // właściciel wycinka TMA/CTR
  // właściciele przestrzeni: stanowisko → liczba wycinków; free = wycinki bez nikogo
  const gOwners = (g) => {
    const m = new Map();
    let free = 0;
    g.slices.forEach((s) => { const o = sOwner(s); if (o) m.set(o, (m.get(o) || 0) + 1); else free++; });
    return { m, free };
  };
  // stanowiska od najbardziej szczegółowych (pierwsze w kolejnościach) do zbiorczych (ALL, ALH)
  let order = [];
  const sortPositions = () => {
    const r = {};
    Object.values(own.sectors).forEach((ls) => Object.values(ls).forEach((ch) => ch.forEach((c, i) => (r[c] ||= []).push(i / Math.max(1, ch.length - 1)))));
    const avg = (c) => (r[c] ? r[c].reduce((a, b) => a + b, 0) / r[c].length : 2);
    order = Object.keys(own.acc_positions).sort((a, b) => avg(a) - avg(b) || name(a).localeCompare(name(b)));
  };
  // kolory jak w GEO: stałe dla ACC, stanowiska lotniskowe z zapasowej palety, gdy kolor byłby zbyt podobny
  const computeActive = () => {
    active = R.activeSet();
    colors = R.colorMap?.([...active].filter(mine)) || {};
  };

  // --- TMA, CTA i CTR: wycinki .ese pogrupowane po przestrzeni, kolejność przejmowania z chains.js
  const buildGroups = () => {
    if (!own || !secs) return;
    const by = new Map(), city = {};
    sliceAt = new Map();
    (secs.features || []).forEach((f) => {
      const pr = f.properties;
      if (pr.fir !== "EPWW" || (pr.kind !== "tma" && pr.kind !== "ctr")) return;
      const icao = /^EP[A-Z]{2}(?=_)/.exec(pr.name)?.[0];
      if (icao && (!city[icao] || pr.kind === "ctr")) city[icao] = pr.group.replace(/^(TMA|CTR) /, "");
      // TMA Poznań N i S osobno (jak w tabeli om); nazwa z .ese, gdy to ta sama przestrzeń (TMA Mazury = TMA Olsztyn-Mazury)
      const t = pr.kind === "tma" ? tmaTopdown(pr.name, own) : null;
      const key = t && !pr.group.includes(t.name.replace(/^TMA /, "")) ? t.name : pr.group;
      const s = { f, name: pr.name, lo: pr.lower_ft, hi: pr.upper_ft, key, ...airspaceChain(pr.name, pr.owners, own) };
      sliceAt.set(`${pr.name}|${pr.lower_ft}|${pr.upper_ft}`, s);
      if (!by.has(key)) by.set(key, { key, name: key, kind: pr.kind === "ctr" ? "ctr" : /^CTA/.test(key) ? "cta" : "tma", slices: [] });
      by.get(key).slices.push(s);
    });
    const list = [...by.values()];
    list.forEach((g) => {
      // wycinki bez własnej nazwy w tabeli om (wspólne Poznań/Gdańsk przy TMA Poznań N i S): nazwa z lotnisk
      // obecnych w nazwach wszystkich wycinków (EPPO_EPGD_TMA-CMN → TMA Poznań/Gdańsk (wspólna))
      if (list.some((o) => o !== g && o.name.startsWith(g.name + " "))) {
        const codes = g.slices.map((s) => s.name.match(/EP[A-Z]{2}/g) || [])
          .reduce((a, l) => a.filter((c) => l.includes(c))).filter((c) => city[c]);
        g.name = codes.length > 1 ? `TMA ${codes.map((c) => city[c]).join("/")} (wspólna)` : `${g.name} (pozostałe)`;
      }
      g.slices.sort((a, b) => a.name.localeCompare(b.name) || a.lo - b.lo);
      // części przestrzeni o różnej kolejności APP/TWR (TMA Warszawa: sektory N i S, DIR…), największy obszar najpierw;
      // kolejność zawarta w dłuższej (KK APP w KK DIR › KK E APP › KK APP) nie tworzy osobnej części
      const byOrd = new Map();
      g.slices.forEach((s) => { const k = s.local.join(); if (!byOrd.has(k)) byOrd.set(k, { local: s.local, slices: [] }); byOrd.get(k).slices.push(s); });
      const vars = [];
      [...byOrd.values()].sort((a, b) => b.local.length - a.local.length || b.slices.length - a.slices.length).forEach((v) => {
        const sup = vars.find((x) => isSub(v.local, x.local));
        if (sup) sup.slices.push(...v.slices); else vars.push(v);
      });
      vars.forEach((v) => {
        const keys = new Set();
        v.area = v.slices.reduce((a, s) => { const k = geomKey(s.f); if (keys.has(k)) return a; keys.add(k); return a + geoArea(s.f.geometry); }, 0);
        v.slices.sort((a, b) => a.name.localeCompare(b.name) || a.lo - b.lo);
      });
      g.vars = vars.sort((a, b) => b.area - a.area);
      // jedna część: jej kolejność; kilka: zbiorcza (lista stanowisk, podpowiedzi), na ekranie każda część osobno
      g.local = vars.length === 1 ? vars[0].local : mergeOrder(g.slices.map((s) => s.local));
      g.acc = mergeOrder(g.slices.map((s) => s.acc.filter((c) => !s.local.includes(c)))).filter((c) => !g.local.includes(c));
      g.chain = [...g.local, ...g.acc];
      g.lo = Math.min(...g.slices.map((s) => s.lo));
      g.hi = Math.max(...g.slices.map((s) => s.hi));
      g.src = [...new Set(g.slices.map((s) => s.src))].sort().reverse();  // ["om"], ["ese"] albo ["om", "ese"]
      g.tma = g.slices.find((s) => s.tma)?.tma || null;
    });
    // najpierw TMA z tabeli om (w jej kolejności), potem pozostałe TMA, CTA i CTR alfabetycznie
    const omOrder = Object.keys(own.tma_topdown || {});
    const rank = (g) => ({ tma: 0, cta: 1, ctr: 2 }[g.kind]);
    const omIdx = (g) => (g.tma ? omOrder.indexOf(g.tma) : 99);
    groups = list.sort((a, b) => rank(a) - rank(b) || omIdx(a) - omIdx(b) || a.name.localeCompare(b.name, "pl", { numeric: true }));
    gByKey = new Map(groups.map((g) => [g.key, g]));
    // stanowiska APP/TWR (i inne spoza ACC) z kolejności TMA/CTR, wg lotnisk w kolejności pierwszego wystąpienia
    const byAd = new Map();
    groups.forEach((g) => g.local.forEach((c) => {
      const icao = c.split("_")[0];
      if (!byAd.has(icao)) byAd.set(icao, []);
      if (!byAd.get(icao).includes(c)) byAd.get(icao).push(c);
    }));
    ads = [...byAd].map(([icao, l]) => ({ icao, city: city[icao] || "", list: l.sort((a, b) => adRank(a) - adRank(b) || a.localeCompare(b)) }));
    locals = ads.flatMap((a) => a.list);
    localSet = new Set(locals);
    if (selG && !gByKey.has(selG)) selG = null;
  };

  // --- rysowanie map
  const drawFirOutline = async () => {
    let firs = null;
    try { firs = await loadFirs(); } catch { /* bez VATSpy: obrys z sektorów */ }
    const epww = firs?.features.find((f) => f.properties.id === "EPWW");
    const t = theme();
    Object.values(views).forEach((v) => {
      v.firs.clearLayers();
      if (firs) drawFirs(v.firs, firs, {}, { labels: false });
      if (epww) L.geoJSON(epww, { interactive: false, pane: "ssFir", style: { color: t.fir, weight: 1.6, opacity: 0.9, fill: false } }).addTo(v.firs);
    });
    if (epww && !fitBounds) { fitBounds = L.geoJSON(epww).getBounds(); if (visible && !fitted) fit(); }
  };
  const styleOf = (it) => {
    const t = theme();
    const st = it.letter
      ? it.own ? { color: t.edge, weight: 1, opacity: 0.9, dashArray: null, fillColor: col(it.own), fillOpacity: 0.55 }
        : { color: t.freeEdge, weight: 1, opacity: 0.9, dashArray: "3 3", fillColor: FREE, fillOpacity: 0.32 }
      // TMA/CTA: "dziura" w ACC, w kolorze właściciela z kolejności TMA (APP/TWR, potem ACC)
      : it.own ? { color: t.hole, weight: 0.8, opacity: 0.9, dashArray: "2 3", fillColor: col(it.own), fillOpacity: 0.3 }
        : { color: t.hole, weight: 0.8, opacity: 0.8, dashArray: "2 3", fillColor: t.holeFill, fillOpacity: 0.35 };
    if (hoverPos && it.letter) {
      if (it.own === hoverPos) Object.assign(st, { color: t.hi, weight: 2.4, opacity: 1, dashArray: null });
      else st.fillOpacity = it.own ? 0.12 : 0.06;
    }
    if (it.letter && it.letter === sel) Object.assign(st, { color: t.hi, weight: 3, opacity: 1, dashArray: null });
    if (it.hover) Object.assign(st, { color: t.hi, weight: 2.4, opacity: 1, dashArray: null });
    return st;
  };
  const restyle = () => Object.values(views).forEach((v) => v.items.forEach((it) => {
    it.poly.setStyle(styleOf(it));
    if (it.letter && (it.letter === sel || it.own === hoverPos)) it.poly.bringToFront();
  }));
  const labelHtml = (it) => `<div class="ss-lbl${it.own ? "" : " un"}"><b>${esc(it.letter)}</b>`
    + (it.own ? `<i style="background:${col(it.own)}"></i>${esc(name(it.own))}` : `<i class="un" title="nieobsadzony"></i>`) + "</div>";
  const drawMap = (v) => {
    v.layer.clearLayers();
    v.items = [];
    if (!v.gj || !own) return;
    // najpierw TMA/CTA (tło), na wierzchu sektory ACC
    const feats = [...v.gj.features].sort((a, b) => !!accLetter(a.properties.name) - !!accLetter(b.properties.name));
    feats.forEach((f) => {
      const pr = f.properties;
      if (pr.name === "EPWW-MIDSEA") return;
      const letter = own.sectors[accLetter(pr.name)] ? accLetter(pr.name) : null;
      const sl = letter ? null : sliceAt.get(`${pr.name}|${pr.lower_ft}|${pr.upper_ft}`) || null;
      const it = { f, letter, sl, own: letter ? ownerOf(letter, v.ly) : sl ? sOwner(sl) : null, hover: false };
      it.poly = L.geoJSON(f, { style: styleOf(it) }).addTo(v.layer);
      it.poly.on("mouseover", (e) => {
        it.hover = true;
        it.poly.setStyle(styleOf(it)).bringToFront();  // pełny obrys nad sąsiadami
        showFloat(tipHtml(v, it), e.originalEvent);
      });
      it.poly.on("mousemove", (e) => moveFloat(e.originalEvent));
      it.poly.on("mouseout", () => {
        it.hover = false;
        it.poly.setStyle(styleOf(it));
        if (sel || hoverPos) restyle();  // wybrany sektor z powrotem na wierzch
        hideFloat();
      });
      if (letter) it.poly.on("click", () => select(sel === letter ? null : letter));
      else if (sl) it.poly.on("click", () => selectG(selG === sl.key ? null : sl.key, true));
      v.items.push(it);
      const at = letter && labelPoint({ ...f, properties: { ...pr, fir: "EPWW" } })?.at;
      if (at) {
        it.label = L.marker(at, { interactive: false, keyboard: false, icon: L.divIcon({ className: "maplabel ss-maplabel", iconSize: null, html: labelHtml(it) }) })
          .addTo(v.layer);
      }
    });
    if (sel || hoverPos) restyle();
  };
  // TMA/CTR na mapie LOW: wiersz listy pod kursorem albo wybrany oraz przestrzenie stanowiska pod kursorem,
  // wypełnione kolorem właściciela (nieobsadzone szare, przerywane); niezależnie od przekroju LOW
  const drawTma = () => {
    tmaLayer.clearLayers();
    if (!groups.length || !own) return;
    const t = theme(), g = gByKey.get(hoverG || selG);
    const part = g && hoverG && hoverV !== null ? g.vars[hoverV] : null;  // część przestrzeni pod kursorem
    const gl = part ? part.slices : g ? g.slices : [];
    const list = [...gl, ...(hoverPos ? groups.flatMap((x) => x.slices.filter((s) => sOwner(s) === hoverPos)) : [])];
    const seen = new Set(), inG = new Set(gl), gb = L.latLngBounds([]);
    list.forEach((s) => {
      const k = geomKey(s.f);
      if (seen.has(k)) return;  // ten sam kształt w kilku przedziałach wysokości: raz
      seen.add(k);
      const o = sOwner(s);
      // wypełnienie prawie kryjące: kolor właściciela nie miesza się z kolorem sektora ACC pod spodem
      const lay = L.geoJSON(s.f, { pane: "ssTma", interactive: false, style: o
        ? { color: t.hi, weight: 1.3, opacity: 0.95, fillColor: col(o), fillOpacity: 0.75 }
        : { color: t.hi, weight: 1.2, opacity: 0.85, dashArray: "4 3", fillColor: FREE, fillOpacity: 0.7 } }).addTo(tmaLayer);
      if (inG.has(s)) gb.extend(lay.getBounds());
    });
    if (!g || !gb.isValid()) return;
    // etykieta nad północną krawędzią przestrzeni (przy widoku całej FIR TMA jest mała – etykieta w środku by ją zasłoniła)
    const ow = [...new Set(gl.map(sOwner).filter(Boolean))];
    L.marker([gb.getNorth(), gb.getCenter().lng], { interactive: false, keyboard: false, icon: L.divIcon({ className: "maplabel ss-maplabel", iconSize: null,
      html: `<div class="ss-lbl ss-tlbl${ow.length ? "" : " un"}"><b>${esc(g.name)}</b>${ow.length
        ? ow.slice(0, 2).map((c) => `<i style="background:${col(c)}"></i>${esc(name(c))}`).join(" ") + (ow.length > 2 ? ` +${ow.length - 2}` : "")
        : `<i class="un"></i>nieobsadzona`}</div>` }) })
      .addTo(tmaLayer);
  };
  const redraw = () => {
    if (!own) return;
    if (!visible || !el.offsetWidth) { dirty = true; return; }  // ukryta: rysujemy po powrocie (ResizeObserver)
    dirty = false;
    hideFloat();  // wielokąt pod kursorem jest rysowany od nowa (bez mouseout)
    computeActive();
    Object.values(views).forEach(drawMap);
    drawTma();
    renderPositions();
    renderSummary();
    renderTma();
    renderDetail();
  };
  const loadLayer = async (v) => {
    const my = ++v.seq;
    const level = v.ly === "LOW" ? lowFl : LEVEL[v.ly];
    try {
      const gj = await api(`/api/nav/sectors?fir=EPWW&level_ft=${level * 100}`);
      if (my !== v.seq) return;
      v.gj = gj;
      v.err = "";
    } catch (e) {
      if (my !== v.seq) return;
      v.gj = null;
      v.err = `Sektory ${v.ly}: ${e.message}`;
    }
    renderStatus();
    computeActive();
    drawMap(v);
    if (v.ly === "LOW") renderBand();
    if (!fitBounds && v.items.length) {
      fitBounds = L.featureGroup(v.items.map((it) => it.poly)).getBounds();
      if (visible && !fitted) fit();
    }
  };

  // --- przekrój LOW: przedziały, w których kształty sektorów ACC są stałe (granice wycinków z pliku .ese)
  const lowBounds = () => {
    const lo = own.layers.LOW.lower_ft, hi = own.layers.LOW.upper_ft;
    const b = new Set([lo, hi]);
    (all?.features || []).filter((f) => accLetter(f.properties.name)).forEach((f) => {
      [f.properties.lower_ft, f.properties.upper_ft].forEach((x) => { if (x > lo && x < hi) b.add(x); });
    });
    return [...b].sort((x, y) => x - y);
  };
  const band = () => {
    const b = lowBounds(), ft = lowFl * 100;
    const i = Math.max(0, b.findLastIndex((x) => x <= ft));
    return { b, i, lo: b[i], hi: b[Math.min(i + 1, b.length - 1)] };
  };
  const renderBand = () => {
    if (!own) return;
    const { b, i, lo, hi } = band();
    const card = views.LOW.card;
    card.querySelector(".ss-rng").textContent = own.layers.LOW.label;
    card.querySelector(".ss-cut").title = `Poziom przekroju warstwy LOW. Kształty sektorów ACC są takie same w przedziale ${flRange(lo, hi)}.`;
    card.querySelector('[data-step="-1"]').disabled = i <= 0;
    card.querySelector('[data-step="1"]').disabled = i >= b.length - 2;
    views.LOW.bandCtl.getContainer().innerHTML = `kształty sektorów dla <b>${flRange(lo, hi)}</b>`;
  };
  const setLowFl = (v) => {
    lowFl = Math.min(LOW_MAX, Math.max(LOW_MIN, Math.round((parseInt(v, 10) || 300) / 5) * 5));
    $(".ss-fl").value = lowFl;
    save("fl", lowFl);
    loadLayer(views.LOW);
  };
  let flTimer = null;
  $(".ss-fl").addEventListener("change", (e) => { clearTimeout(flTimer); flTimer = setTimeout(() => setLowFl(e.target.value), 200); });
  views.LOW.card.querySelectorAll(".ss-step").forEach((btn) => btn.addEventListener("click", () => {
    if (!own) return;
    const { b, i } = band();
    const j = i + Number(btn.dataset.step);
    if (j >= 0 && j < b.length - 1) setLowFl(b[j] / 100);
  }));
  // informacja o przedziale kształtów w rogu mapy LOW
  views.LOW.bandCtl = L.control({ position: "bottomleft" });
  views.LOW.bandCtl.onAdd = () => L.DomUtil.create("div", "ss-band");
  views.LOW.bandCtl.addTo(views.LOW.map);

  // --- dymek po najechaniu na sektor (poza kontenerem mapy, więc nie jest przycinany)
  const showFloat = (html, e) => { float.innerHTML = html; float.style.display = "block"; moveFloat(e); };
  const moveFloat = (e) => {
    if (!e || float.style.display !== "block") return;
    const w = float.offsetWidth, hh = float.offsetHeight, pad = 16;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 4) x = e.clientX - w - pad;
    if (y + hh > innerHeight - 4) y = Math.max(4, innerHeight - hh - 4);
    float.style.left = Math.max(4, x) + "px";
    float.style.top = y + "px";
  };
  const hideFloat = () => { float.style.display = "none"; };

  // kolejność przejmowania z wyróżnionym właścicielem (owner: znak albo Set znaków); nieaktywne przygaszone.
  // accFrom: od której pozycji zaczyna się część ACC (łańcuchy TMA/CTR), accLbl: skąd jest ta część;
  // short: nazwy ACC bez "EPWW" (wąskie kolumny warstw w szczegółach sektora); num: numery miejsc (bez: "›", ACC po częściach TMA)
  const chainHtml = (chain, owner, accFrom = -1, accLbl = "", short = false, num = true) => {
    const isOwn = (c) => (owner instanceof Set ? owner.has(c) : c === owner);
    return `<ol class="ss-chain">${chain.map((c, i) => {
      const on = onlineOf(c);
      const cls = isOwn(c) ? "own" : active.has(c) ? "act" : "off";
      return (i === accFrom && i > 0 ? `<li class="ss-chs">${accLbl}</li>` : "")
        + `<li class="${cls}" title="${esc(c)}${on ? ` · online: ${esc(on.name || "")}` : ""}"><span class="n">${num ? i + 1 : "›"}</span>`
        + `<i style="background:${col(c)}"></i><b>${esc(short ? accShort(c) : name(c))}</b><span class="fq">${esc(freq(c))}</span>`
        + `${on ? `<span class="onl">online</span>` : ""}${isOwn(c) ? `<span class="tag">właściciel</span>` : ""}</li>`;
    }).join("")}</ol>`;
  };
  // właściciel: pełny opis (dymek) albo nazwa z częstotliwością (kolumny szczegółów)
  const ownerLine = (owner, full = true, free = "nieobsadzony", short = false) => {
    if (!owner) return `<span class="ss-free">${free}</span>${full ? ` <span class="muted">nikt z kolejności nie jest ${R.state.mode === "sim" ? "w symulacji" : "online"}</span>` : ""}`;
    const on = onlineOf(owner);
    return `<i class="ss-swi" style="background:${col(owner)}"></i><b>${esc(short ? accShort(owner) : name(owner))}</b> <span class="fq">${esc(freq(owner))}</span>`
      + (on && full ? ` <span class="muted">${esc(on.name || "")}</span>` : "");
  };
  const srcShort = (src) => (src === "om" ? "om.plvacc.pl" : "plik .ese");
  const accLbl = (g) => `ACC · ${g.src.map(srcShort).join(" / ")}`;
  const tipHtml = (v, it) => {
    const pr = it.f.properties;
    if (!it.letter) {
      const s = it.sl, g = s && gByKey.get(s.key);
      if (!g) {
        return `<div class="ss-fh"><b>${esc(pr.name)}</b><span>${flRange(pr.lower_ft, pr.upper_ft)}</span></div>
          <div class="ss-fsub">poza sektorami ACC (TMA / CTA) · właściciel z listy OWNER pliku .ese</div>`;
      }
      return `<div class="ss-fh"><b>${esc(g.name)}</b><span>${altRange(g.lo, g.hi)}</span></div>
        <div class="ss-fsub">wycinek ${esc(pr.name)} ${altRange(pr.lower_ft, pr.upper_ft)}</div>
        <div class="ss-own">${ownerLine(it.own)}</div>
        <div class="ss-k">Kolejność przejmowania</div>${chainHtml(s.chain, it.own, s.local.length, `ACC · ${srcShort(s.src)}`)}
        <div class="ss-fhint">kliknij: ${esc(g.name)} na liście TMA i CTR</div>`;
    }
    const chain = chainOf(it.letter, v.ly);
    return `<div class="ss-fh"><b>Sektor ${esc(it.letter)}</b><span>${v.ly} · ${esc(own.layers[v.ly].label)}</span></div>
      <div class="ss-fsub">wycinek ${esc(pr.name)} ${flRange(pr.lower_ft, pr.upper_ft)}</div>
      <div class="ss-own">${ownerLine(it.own)}</div>
      <div class="ss-k">Kolejność przejmowania</div>${chainHtml(chain, it.own)}
      <div class="ss-fhint">kliknij: wszystkie warstwy sektora</div>`;
  };

  // --- panel stanowisk (jedna kolumna): ACC, potem APP i TWR wg lotnisk
  const renderStatus = () => {
    if (!own) return;
    const s = R.state, nAcc = order.filter((c) => active.has(c)).length, nLoc = locals.filter((c) => active.has(c)).length;
    let txt = "";
    if (s.mode === "sim") {
      txt = `Symulacja: ACC ${nAcc} z ${order.length}${locals.length ? `, APP/TWR ${nLoc} z ${locals.length}` : ""}. Kliknij stanowisko: włącz / wyłącz.`;
    } else if (s.ok) {
      const onl = [...order, ...locals].filter(onlineOf);
      txt = `VATSIM ${s.onlineAt ? hhmm(new Date(s.onlineAt).toISOString()) : "…"} · online: ${onl.length ? onl.map((c) => `<b>${esc(name(c))}</b>`).join(", ") : "nikt"}`;
    } else if (!s.err) txt = "VATSIM …";
    // stan sieci z radiostate: po nieudanym pobraniu "brak danych" (szczegóły w podpowiedzi)
    const net = !s.ok && s.err ? `<span class="error" title="${esc(s.err)}">VATSIM: brak danych</span>` : "";
    $(".ss-status").innerHTML = [txt, net, ...VACS_LAYERS.map((ly) => views[ly].err && `<span class="error">${esc(views[ly].err)}</span>`)]
      .filter(Boolean).join(" ");
  };
  const paintMode = () => {
    el.querySelectorAll(".ss-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === R.state.mode));
    $(".ss-poscard").classList.toggle("sim", R.state.mode === "sim");
  };
  const posRow = (c) => {
    const sim = R.state.mode === "sim";
    const on = onlineOf(c), act = active.has(c);
    const tip = `${c} · ${freq(c)}${on ? `\nonline: ${on.name || "?"} (CID ${on.cid ?? "?"}), od ${hhmm(on.logon_time)}` : ""}`
      + `\nkliknij: ${act && sim ? "wyłącz w symulacji" : "włącz w symulacji"}`;
    return `<div class="ss-prow${act ? " act" : ""}${on ? " onl" : ""}${hoverPos === c ? " hl" : ""}" data-cs="${esc(c)}" title="${esc(tip)}">`
      + (sim ? `<span class="ss-chk${act ? " on" : ""}"></span>` : `<span class="ss-dot"></span>`)
      + `<i class="ss-sw" style="background:${col(c)}"></i><b class="ss-short">${esc(name(c))}</b>`
      + `<span class="ss-fq${on ? " on" : ""}">${esc(freq(c))}</span><span class="ss-who">${on ? esc(on.name || "online") : ""}</span></div>`;
  };
  const secHead = (key, label, list, title) => {
    const n = R.state.mode === "sim" ? `${list.filter((c) => active.has(c)).length}/${list.length}` : `online ${list.filter(onlineOf).length}`;
    return `<div class="ss-ph" title="${esc(title)}"><b>${label}</b><span class="n">${n}</span>
      <span class="ss-simbtn"><button data-sec="${key}" data-on="1" title="Włącz w symulacji wszystkie stanowiska ${label}">wszystkie</button>`
      + `<button data-sec="${key}" data-on="0" title="Wyłącz w symulacji wszystkie stanowiska ${label}">wyłącz</button></span></div>`;
  };
  const renderPositions = () => {
    paintMode();
    renderStatus();
    // każda sekcja we własnym bloku: przyklejony nagłówek tylko w obrębie swojej sekcji
    $(".ss-pos").innerHTML = `<div class="ss-psec">${secHead("acc", "ACC EPWW", order, "Sektory ACC EPWW (kolejność przejmowania z /api/nav/ownership)")}
      ${order.map(posRow).join("")}</div><div class="ss-psec">`
      + (locals.length ? secHead("loc", "APP/TWR", locals, "Stanowiska APP i TWR z list OWNER wycinków TMA, CTA i CTR w pliku .ese")
        + ads.map((a) => `<div class="ss-adh"><b>${esc(a.icao)}</b> ${esc(a.city)}</div>${a.list.map(posRow).join("")}`).join("")
        : `<div class="ss-ph"><b>APP/TWR</b><span class="n">${errSecs ? `<span class="error">${esc(errSecs)}</span>` : secs ? "brak w pliku .ese" : "wczytywanie…"}</span></div>`)
      + "</div>";
  };
  $(".ss-mode").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) R.setMode(b.dataset.mode); });
  $(".ss-simbar").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b || !own) return;
    if (b.dataset.act === "online") {
      await R.refreshNet(true);  // świeży stan sieci
      if (!R.state.ok) { renderStatus(); return; }  // bez danych z sieci nie kasujemy zaznaczeń
      R.setSim(R.onlineList());
    } else R.setSim([...R.state.sim].filter((c) => !mine(c)));  // pozycje spoza tej listy (GEO) zostają
    R.setMode("sim");
  });
  $(".ss-pos").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-sec]");
    if (b) {
      const list = b.dataset.sec === "acc" ? order : locals, s = new Set(R.state.sim);
      list.forEach((c) => (b.dataset.on === "1" ? s.add(c) : s.delete(c)));
      R.setSim([...s]);
      R.setMode("sim");
      return;
    }
    const row = e.target.closest(".ss-prow");
    if (row) R.toggle(row.dataset.cs);
  });
  // najechanie na stanowisko (lista albo podsumowanie): jego sektory obrysowane na wszystkich mapach, jego TMA/CTR na mapie LOW
  const setHover = (cs) => {
    if (cs === hoverPos) return;
    hoverPos = cs;
    el.querySelectorAll(".ss-prow, .ss-srow").forEach((r) => r.classList.toggle("hl", !!cs && r.dataset.cs === cs));
    const gs = new Set(cs ? groups.filter((g) => g.slices.some((s) => sOwner(s) === cs)).map((g) => g.key) : []);
    el.querySelectorAll(".ss-trow").forEach((r) => r.classList.toggle("hl", gs.has(r.dataset.g)));
    restyle();
    drawTma();
  };
  [".ss-pos", ".ss-sum"].forEach((s) => {
    $(s).addEventListener("mouseover", (e) => setHover(e.target.closest("[data-cs]")?.dataset.cs || null));
    $(s).addEventListener("mouseleave", () => setHover(null));
  });

  // --- podsumowanie: kto co obsługuje (jak na plvacc: "EPWW N — B LMH, E LMH"), TMA/CTR, sektory nieobsadzone
  const gShort = (g) => g.name.replace(/^(TMA|CTA|CTR) /, "");
  const gKinds = [["tma", "TMA"], ["cta", "CTA"], ["ctr", "CTR"]];
  const summary = () => {
    const by = new Map(), free = {};
    const ent = (c) => by.get(c) || by.set(c, { m: {}, g: [] }).get(c);
    letters().forEach((s) => VACS_LAYERS.forEach((ly) => {
      const o = ownerOf(s, ly);
      const m = o ? ent(o).m : free;
      (m[s] ||= []).push(ly[0]);
    }));
    const gFree = [];
    groups.forEach((g) => {
      const { m, free: fr } = gOwners(g);
      m.forEach((n, c) => ent(c).g.push({ g, n, part: n < g.slices.length }));
      if (fr) gFree.push(g);
    });
    const fmt = (m) => Object.entries(m).map(([s, ls]) => `${s} ${ls.join("")}`).join(", ");
    const idx = (c) => (order.includes(c) ? order.indexOf(c) : 1000 + locals.indexOf(c));
    // aktywne stanowiska bez niczego (wszystko przejęte przez stanowiska wcześniej w kolejności) na końcu
    const rows = [...by.entries(), ...[...active].filter((c) => mine(c) && !by.has(c)).map((c) => [c, { m: {}, g: [] }])]
      .map(([c, e]) => ({ c, ...e, n: Object.values(e.m).flat().length, acc: order.includes(c) }))
      .sort((a, b) => !(a.n + a.g.length) - !(b.n + b.g.length) || b.acc - a.acc || b.n - a.n || b.g.length - a.g.length || idx(a.c) - idx(b.c));
    return { rows, free, gFree, fmt };
  };
  // TMA/CTA/CTR stanowiska, każdy rodzaj w osobnej linii ("TMA Warszawa, Łódź"); część przestrzeni z liczbą wycinków
  const gHtml = (gl) => gKinds.map(([k, lbl]) => {
    const l = gl.filter((x) => x.g.kind === k);
    return l.length ? `<span class="g"><em>${lbl}</em> ${l.map((x) => `${esc(gShort(x.g))}${x.part ? ` <small>${x.n}/${x.g.slices.length}</small>` : ""}`).join(", ")}</span>` : "";
  }).join("");
  const gText = (gl) => gKinds.map(([k, lbl]) => {
    const l = gl.filter((x) => x.g.kind === k);
    return l.length ? `${lbl} ${l.map((x) => gShort(x.g) + (x.part ? ` (${x.n}/${x.g.slices.length})` : "")).join(", ")}` : "";
  }).filter(Boolean).join("; ");
  const renderSummary = () => {
    const { rows, free, gFree, fmt } = summary();
    const total = letters().length * VACS_LAYERS.length;
    const freeN = Object.values(free).flat().length;
    const gOwned = groups.length - groups.filter((g) => !gOwners(g).m.size).length;
    const nPos = rows.filter((r) => r.n || r.g.length).length;
    // blok na stanowisko: nazwa i częstotliwość, pod nimi sektory ACC i TMA/CTA/CTR na całą szerokość karty
    const secSpans = (m) => Object.entries(m).map(([s, ls]) => `<span><b>${esc(s)}</b> ${ls.join("")}</span>`).join("");
    $(".ss-sum").innerHTML = rows.map(({ c, m, n, g }) => {
      const on = onlineOf(c);
      return `<div class="ss-srow${hoverPos === c ? " hl" : ""}" data-cs="${esc(c)}" title="${esc(`${c} ${freq(c)}${on ? ` · online: ${on.name || ""}` : ""}`)}">
        <div class="ss-sh"><i class="ss-swi" style="background:${col(c)}"></i><b>${esc(name(c))}</b><span class="fq">${esc(freq(c))}</span>
          ${n ? `<span class="n" title="sektor × warstwa">${n}</span>` : ""}</div>
        ${n ? `<div class="ss-ssec">${secSpans(m)}</div>` : ""}${gHtml(g)}
        ${n || g.length ? "" : `<div class="ss-snone muted">nic (przejęte wcześniej w kolejności)</div>`}</div>`;
    }).join("")
      + (freeN || gFree.length ? `<div class="ss-srow un"><div class="ss-sh"><i class="ss-swi un"></i><b>nieobsadzone</b>
          ${freeN ? `<span class="n" title="sektor × warstwa">${freeN}</span>` : ""}</div>
        ${freeN ? `<div class="ss-ssec">${secSpans(free)}</div>` : ""}
        ${gFree.length ? `<span class="g" title="${esc(gFree.map((g) => g.name).join(", "))}"><em>TMA/CTR</em> ${gFree.length} z ${groups.length}</span>` : ""}</div>` : "")
      + `
      <div class="ss-sumnote hint">${nPos ? `${nPos} ${plural(nPos, "stanowisko", "stanowiska", "stanowisk")}` : "Żadne stanowisko nie jest aktywne"}.
        Sektory ACC obsadzone: ${total - freeN} z ${total} (sektor × warstwa: L = LOW ${esc(own.layers.LOW.label)}, M = MID ${esc(own.layers.MID.label)},
        H = HIGH ${esc(own.layers.HIGH.label)}).${groups.length ? ` TMA, CTA i CTR obsadzone: ${gOwned} z ${groups.length} (liczba przy nazwie: część wycinków).` : ""}</div>`;
    $(".ss-copy").onclick = () => {
      const txt = [...rows.map(({ c, m, n, g }) => `${name(c)} ${freq(c)} — ${[n ? fmt(m) : "", gText(g)].filter(Boolean).join("; ") || "nic"}`),
        ...(freeN || gFree.length ? [`nieobsadzone — ${[freeN ? fmt(free) : "", gFree.map((g) => g.name).join(", ")].filter(Boolean).join("; ")}`] : [])].join("\n");
      navigator.clipboard?.writeText(txt).then(() => { $(".ss-copy").textContent = "skopiowano"; setTimeout(() => { $(".ss-copy").textContent = "kopiuj"; }, 1500); })
        .catch(() => { /* brak dostępu do schowka */ });
    };
  };

  // --- TMA i CTR: jedna kolumna, wiersz = przestrzeń z granicami, właścicielem i pełną kolejnością przejmowania;
  // przestrzeń z częściami o różnej kolejności APP/TWR: linia na część (najedź: ta część na mapie LOW), pod nimi wspólne ACC
  const SEP = "&nbsp;<s>›</s> ";  // "›" zostaje na końcu wiersza
  const partTip = (v) => `${v.slices.length} ${plural(v.slices.length, "wycinek", "wycinki", "wycinków")}: `
    + `${[...new Set(v.slices.map((s) => s.name))].join(", ")}\nNajedź: ta część na mapie LOW`;
  const tmaRow = (g) => {
    const { m, free } = gOwners(g), owners = new Set(m.keys()), first = [...m.keys()][0];
    const fqShown = new Set();  // częstotliwość przy pierwszym wystąpieniu stanowiska w wierszu
    const item = (c, acc, own = owners) => {
      const on = onlineOf(c);
      const cls = own.has(c) ? "own" : active.has(c) ? "act" : "off";
      const tip = `${name(c)} · ${c} · ${freq(c)}${on ? `\nonline: ${on.name || "?"}` : ""}${own.has(c) ? "\nwłaściciel" : ""}`;
      const fq = !acc && !fqShown.has(c) && freq(c) ? ` <em>${esc(freq(c))}</em>` : "";
      if (!acc) fqShown.add(c);
      return `<span class="${cls}${on ? " onl" : ""}" title="${esc(tip)}">${esc(acc ? accShort(c) : name(c))}${fq}</span>`;
    };
    const srcTip = g.src.length > 1 ? `ACC: tabela top-down om.plvacc.pl (${g.tma}) w części wycinków, w pozostałych lista OWNER pliku .ese`
      : g.src[0] === "om" ? `ACC: tabela top-down om.plvacc.pl (${g.tma})` : "ACC: lista OWNER pliku .ese";
    const ow = m.size
      ? [...m].map(([c, n]) => `<span><i class="ss-swi" style="background:${col(c)}"></i>${esc(name(c))}${m.size > 1 || free ? ` <small>${n}/${g.slices.length}</small>` : ""}</span>`).join("")
      : `<span class="ss-free">nieobsadzona</span>`;
    const acc = g.acc.length ? [`<span class="ss-acck" title="${esc(srcTip)}">ACC ${g.src.map((s) => (s === "om" ? "om" : ".ese")).join("/")}</span>${item(g.acc[0], true)}`,
      ...g.acc.slice(1).map((c) => item(c, true))] : [];
    const body = g.vars.length < 2 ? `<div class="ss-tc">${[...g.local.map((c) => item(c, false)), ...acc].join(SEP)}</div>`
      : g.vars.map((v, i) => {
        const vo = new Set(v.slices.map(sOwner).filter(Boolean));
        return `<div class="ss-tc ss-tv" data-v="${i}" title="${esc(partTip(v))}">${v.local.map((c) => item(c, false, vo)).join(SEP)}${acc.length ? "&nbsp;<s>›</s>" : ""}</div>`;
      }).join("") + (acc.length ? `<div class="ss-tc ss-ta">${acc.join(SEP)}</div>` : "");
    return `<div class="ss-trow${m.size ? "" : " un"}${selG === g.key ? " sel" : ""}" data-g="${esc(g.key)}"${first ? ` style="border-left-color:${col(first)}"` : ""}>
      <div class="ss-th"><b>${esc(g.name)}</b><span class="lim">${altRange(g.lo, g.hi)}</span><span class="ow">${ow}</span></div>${body}</div>`;
  };
  const renderTma = () => {
    el.querySelectorAll(".ss-tk button").forEach((b) => b.classList.toggle("on", b.dataset.k === tk));
    const box = $(".ss-tma");
    if (!groups.length) {
      $(".ss-tcnt").textContent = "";
      box.innerHTML = `<p class="hint">${errSecs ? `<span class="error">Wycinki TMA i CTR (/api/radio/sectors): ${esc(errSecs)}</span> Ponowna próba co minutę.`
        : secs ? "Brak wycinków TMA i CTR: zaimportuj plik .ese (data/import)." : "Wczytywanie wycinków TMA i CTR…"}</p>`;
      return;
    }
    const list = groups.filter((g) => (g.kind === "ctr") === (tk === "ctr"));
    const n = list.filter((g) => gOwners(g).m.size).length;
    $(".ss-tcnt").innerHTML = `${n}/${list.length}<span class="w"> obsadzone</span>`;  // słowo znika w wąskim oknie (sectors.css)
    $(".ss-tcnt").title = `Obsadzone ${n} z ${list.length} (${tk === "ctr" ? "CTR" : "TMA i CTA"})`;
    box.innerHTML = list.map(tmaRow).join("")
      + `<p class="ss-tnote hint">Kolejność: APP i TWR z listy OWNER pliku .ese, potem ACC (om = tabela top-down om.plvacc.pl, .ese = lista OWNER).
        Kilka linii APP/TWR: części przestrzeni o różnej kolejności (np. sektory N i S), ACC wspólne pod nimi.
        Białe tło: właściciel, przygaszone: nieaktywne, ● online. Liczba przy właścicielu: część wycinków przestrzeni.
        Najedź: przestrzeń (albo jej część) na mapie LOW, kliknij: wycinki i szczegóły.</p>`;
  };
  $(".ss-tk").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-k]");
    if (!b || b.dataset.k === tk) return;
    tk = b.dataset.k;
    save("tk", tk);
    renderTma();
  });
  // przestrzeń pod kursorem (k) i jej część (v: indeks w g.vars albo null = cała)
  const setHoverG = (k, v = null) => { if (k === hoverG && v === hoverV) return; hoverG = k; hoverV = k ? v : null; drawTma(); };
  const partOf = (e) => { const v = e.target.closest("[data-v]")?.dataset.v; return v === undefined ? null : Number(v); };
  $(".ss-tma").addEventListener("mouseover", (e) => setHoverG(e.target.closest(".ss-trow")?.dataset.g || null, partOf(e)));
  $(".ss-tma").addEventListener("mouseleave", () => setHoverG(null));
  // części wybranej przestrzeni w szczegółach: ta część na mapie LOW
  $(".ss-detail").addEventListener("mouseover", (e) => { const v = partOf(e); setHoverG(v === null ? null : selG, v); });
  $(".ss-detail").addEventListener("mouseleave", () => setHoverG(null));
  $(".ss-tma").addEventListener("click", (e) => { const r = e.target.closest(".ss-trow"); if (r) selectG(selG === r.dataset.g ? null : r.dataset.g); });

  // --- szczegóły: kliknięty sektor we wszystkich warstwach albo wybrana TMA/CTR; bez wyboru – skąd są kolejności przejmowania
  const select = (s) => {
    sel = s;
    if (s) selG = null;
    restyle();
    renderTma();
    renderDetail();
    drawTma();
  };
  const selectG = (k, reveal = false) => {
    selG = k;
    if (k) sel = null;
    const g = gByKey.get(k);
    if (g && (g.kind === "ctr") !== (tk === "ctr")) { tk = g.kind === "ctr" ? "ctr" : "tma"; save("tk", tk); }
    restyle();
    renderTma();
    renderDetail();
    drawTma();
    // kliknięcie na mapie: wiersz przewinięty do widoku (tylko lista, bez przewijania strony)
    const row = reveal && g && el.querySelector(`.ss-trow[data-g="${CSS.escape(k)}"]`), box = $(".ss-tma");
    if (row) {
      const r = row.getBoundingClientRect(), b = box.getBoundingClientRect();
      if (r.top < b.top || r.bottom > b.bottom) box.scrollTop += r.top - b.top - 6;
    }
  };
  // warianty kolejności APP/TWR w przestrzeni: wycinki o tej samej kolejności razem
  const variantHtml = ({ s, list }) => {
    const o = sOwner(s);
    const loc = s.local.map((c) => `<span class="${c === o ? "own" : active.has(c) ? "act" : "off"}">${esc(name(c))}</span>`);
    const acc = s.acc.length ? [`<span class="${o && !s.local.includes(o) ? "own" : "act"}" title="${esc(s.acc.map(name).join(" › "))}">ACC ${s.src === "om" ? "om" : ".ese"}${o && !s.local.includes(o) ? `: ${esc(accShort(o))}` : ""}</span>`] : [];
    return `<div class="ss-var"><div class="ss-vch">${[...loc, ...acc].join("&nbsp;<s>›</s> ")}</div>
      <div class="ss-vsl">${list.map((x) => `<span>${esc(x.name)} <em>${altRange(x.lo, x.hi)}</em></span>`).join("")}</div></div>`;
  };
  // część przestrzeni z własną kolejnością APP/TWR: kolejność (właściciel części na białym tle), potem ACC i jej wycinki
  const partHtml = (v, i) => {
    const vo = new Set(v.slices.map(sOwner).filter(Boolean)), accOwn = [...vo].filter((c) => !v.local.includes(c));
    const loc = v.local.map((c) => `<span class="${vo.has(c) ? "own" : active.has(c) ? "act" : "off"}${onlineOf(c) ? " onl" : ""}" title="${esc(`${c} · ${freq(c)}`)}">${esc(name(c))}</span>`);
    const acc = `<span class="${accOwn.length ? "own" : "act"}">ACC${accOwn.length ? `: ${esc(accOwn.map(accShort).join(", "))}` : ""}</span>`;
    return `<div class="ss-var ss-part" data-v="${i}" title="Najedź: ta część na mapie LOW"><div class="ss-vch">${[...loc, acc].join(SEP)}</div>
      <div class="ss-vsl">${v.slices.map((x) => `<span>${esc(x.name)} <em>${altRange(x.lo, x.hi)}</em></span>`).join("")}</div></div>`;
  };
  const groupDetail = (g) => {
    const { m, free } = gOwners(g), owners = new Set(m.keys()), n = g.slices.length;
    const vars = new Map();
    g.slices.forEach((s) => { const k = s.chain.join(); if (!vars.has(k)) vars.set(k, { s, list: [] }); vars.get(k).list.push(s); });
    const src = g.src.length > 1 ? `tabela top-down om.plvacc.pl (${esc(g.tma)}) w części wycinków, w pozostałych lista OWNER pliku .ese`
      : g.src[0] === "om" ? `tabela top-down om.plvacc.pl (${esc(g.tma)})` : "lista OWNER pliku .ese (brak tej przestrzeni w tabeli top-down om.plvacc.pl)";
    // kilka części o różnej kolejności APP/TWR: każda osobno z wycinkami, wspólne ACC pod nimi
    const order = g.vars.length > 1
      ? `<div class="ss-k">Kolejność APP/TWR · ${g.vars.length} części przestrzeni</div>${g.vars.map(partHtml).join("")}
        <div class="ss-k">Potem ${accLbl(g)}</div>${chainHtml(g.acc, owners, -1, "", false, false)}`
      : `<div class="ss-k">Kolejność przejmowania${vars.size > 1 ? " (nie każdy wycinek ma wszystkie stanowiska)" : ""}</div>
        ${chainHtml(g.chain, owners, g.local.length, accLbl(g))}`;
    return `<div class="ss-own">${altRange(g.lo, g.hi)} <span class="muted">· ${n} ${plural(n, "wycinek", "wycinki", "wycinków")} (.ese)</span></div>
      <div class="ss-own">${m.size ? [...m].map(([c, k]) => ownerLine(c, false) + (m.size > 1 || free ? ` <span class="muted">${k}/${n}</span>` : "")).join("<br>")
        : ownerLine(null, true, "nieobsadzona")}${free && m.size ? `<br><span class="ss-free">nieobsadzone</span> <span class="muted">${free}/${n}</span>` : ""}</div>
      ${order}
      <p class="ss-srcnote">APP/TWR: lista OWNER pliku .ese. ACC: ${src}.</p>
      ${g.vars.length < 2 && n > 1 ? `<div class="ss-k">Wycinki${vars.size > 1 ? " wg kolejności przejmowania" : ""}</div>${[...vars.values()].map(variantHtml).join("")}` : ""}`;
  };
  const renderDetail = () => {
    const d = $(".ss-detail");
    if (!own) { d.innerHTML = ""; return; }
    const g = selG && gByKey.get(selG);
    if (g) {
      $(".ss-dh").innerHTML = `${esc(g.name)} <button class="ss-x" title="Zamknij">✕</button>`;
      d.innerHTML = groupDetail(g);
      return;
    }
    if (sel) {
      $(".ss-dh").innerHTML = `Sektor ${esc(sel)} <button class="ss-x" title="Zamknij">✕</button>`;
      d.innerHTML = `<div class="ss-cols">${VACS_LAYERS.map((ly) => {
        const chain = chainOf(sel, ly), owner = ownerOf(sel, ly);
        return `<div class="ss-col"><div class="ss-colh"><b>${ly}</b> <span>${esc(own.layers[ly].label)}</span></div>
          <div class="ss-own" title="${esc(owner ? `${name(owner)} ${freq(owner)}` : "nieobsadzony")}">${ownerLine(owner, false, "nieobsadzony", true)}</div>
          ${chainHtml(chain, owner, -1, "", true)}</div>`;
      }).join("")}</div>`;
      return;
    }
    $(".ss-dh").textContent = "Szczegóły";
    const om = Object.keys(own.tma_topdown || {});
    d.innerHTML = `<p class="hint">Najedź na sektor albo TMA na mapie: kolejność przejmowania. Kliknij sektor: kolejność we wszystkich warstwach.
        Najedź na TMA/CTR na liście: przestrzeń na mapie LOW; kliknij: wycinki i kolejność. Najedź na stanowisko: jego sektory i TMA na mapach.
        Kliknij stanowisko: symulacja (wspólna z GEO).</p>
      <div class="ss-k">Kolejność przejmowania sektorów ACC</div>
      <p class="ss-srcnote">Źródło: <b>${esc(own.source_label || own.source || "")}</b>.${own.note ? ` ${esc(own.note)}` : ""}
        ${own.url ? `<a href="${esc(own.url)}" target="_blank" rel="noopener">${esc(own.url.replace(/^https?:\/\//, ""))} ↗</a>` : ""}</p>
      <div class="ss-k">Kolejność przejmowania TMA, CTA i CTR</div>
      <p class="ss-srcnote">Najpierw stanowiska APP i TWR z listy OWNER pliku .ese (w kolejności z pliku), potem ACC:
        ${om.length ? `tabela top-down om.plvacc.pl dla ${esc(om.join(", "))}, dla pozostałych` : ""} lista OWNER pliku .ese.</p>
      ${all?.err ? `<p class="error">Wycinki sektorów z pliku .ese: ${esc(all.err)} (ponowna próba co minutę)</p>` : ""}`;
  };
  $(".ss-dh").addEventListener("click", (e) => { if (e.target.closest(".ss-x")) { sel = null; selectG(null); } });

  // --- start
  const init = async () => {
    try {
      [own] = await Promise.all([loadVacs(), loadDisplayNames()]);  // etykiety stanowisk jak w VACS (displayName)
      errOwn = "";
    } catch (e) {
      errOwn = e.message;
      $(".ss-status").innerHTML = `<span class="error">Brak kolejności przejmowania (/api/nav/ownership): ${esc(e.message)}</span>`;
      return;
    }
    sortPositions();
    VACS_LAYERS.forEach((ly) => { views[ly].card.querySelector(".ss-rng").textContent = own.layers[ly].label; });
    const src = $(".ss-src");
    src.textContent = (own.source_label || "").split(" › ")[0];
    src.title = `Kolejność przejmowania sektorów ACC: ${own.source_label || ""}`;
    buildGroups();
    redraw();
    VACS_LAYERS.forEach((ly) => loadLayer(views[ly]));
    loadSlices();
    loadTma();
  };
  const loadSlices = () => loadAll().then((g) => { all = g; renderBand(); renderDetail(); })
    .catch((e) => { all = { features: [], err: e.message }; renderDetail(); });
  // wycinki TMA/CTR (lista OWNER jako znaki stanowisk) i częstotliwości stanowisk lotniskowych
  const loadTma = () => Promise.all([R.loadSectors(), R.loadPositions().catch(() => [])]).then(([s, ps]) => {
    secs = s;
    errSecs = "";
    posInfo = Object.fromEntries((ps || []).map((p) => [p.callsign, p]));
    buildGroups();
    redraw();  // także "dziury" TMA w mapach, jeśli warstwy przyszły wcześniej (właściciel z kolejności TMA)
  }).catch((e) => { errSecs = e.message; renderTma(); renderPositions(); });
  paintMode();
  syncBase();
  init();
  R.on(() => redraw());
  // powrót do zakładki RADIO: zaległe przerysowanie (zmiany z czasu, gdy widok był ukryty)
  new ResizeObserver(() => {
    if (!visible || !el.offsetWidth) return;
    // okno zmienione, gdy była otwarta inna zakładka: Leaflet zapamiętał rozmiar 0×0 (puste mapy); nieruszany widok
    // dopasowuje na nowo obsługa "resize" mapy LOW
    Object.values(views).forEach((v) => v.map.invalidateSize({ animate: false }));
    syncBase();  // podkład mógł się zmienić w zakładce MAP
    if (dirty) redraw();
  }).observe(el);
  let unwatch = null;
  setInterval(() => {
    if (!visible || !el.isConnected || !el.offsetWidth) return;
    if (errOwn || !own) { init(); return; }  // ponowna próba po błędzie /api/nav/ownership
    // ponowna próba po błędzie wycinków (np. serwer jeszcze wczytuje plik .ese)
    VACS_LAYERS.forEach((ly) => { if (!views[ly].gj) loadLayer(views[ly]); });
    if (all?.err) loadSlices();
    if (errSecs) loadTma();
  }, 60000);

  return {
    el,
    show: () => {
      visible = true;
      unwatch ||= R.watch();
      setTimeout(() => {
        if (!el.isConnected) return;
        Object.values(views).forEach((v) => v.map.invalidateSize({ animate: false }));
        syncBase();
        if (!fitted) fit();
        if (dirty) redraw();
      }, 30);
    },
    hide: () => { visible = false; hideFloat(); unwatch?.(); unwatch = null; },
  };
}
