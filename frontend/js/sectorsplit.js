// MAP → SEKTORYZACJA: dziedziczenie sektorów EPWW przez konkretne stanowiska, osobna mapa dla warstw LOW, MID i HIGH.
// Łańcuchy z vacs-data (stations.toml, controlled_by; te same zasady co om.plvacc.pl ownerships). Właściciel sektora
// w warstwie = pierwsze aktywne stanowisko z łańcucha, brak = UNICOM 122.800. Aktywne: "VATSIM teraz" (zalogowani
// w sieci) albo "symulacja" (zaznaczone ręcznie, zapamiętane w przeglądarce). Presetów plvacc nie odtwarzamy.
import { BASEMAPS, LIGHT_BASEMAPS, api, atcPositions, esc, h, hhmm, lsGet, lsSet, vatsimOnline } from "./api.js";
import { VACS_LAYERS, accLetter, colorFor, drawFirs, fl, loadFirs, loadVacs } from "./airspace.js";

const LOW_MIN = 95, LOW_MAX = 330;  // przekrój LOW: FL095–FL330 (od FL335 jest już MID)
const LEVEL = { MID: 350, HIGH: 400 };  // MID i HIGH mają jeden kształt sektorów
const UNICOM = "#5a615a";
const LS = "map.split.";
const load = (k, d) => { try { const v = lsGet(LS + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const save = (k, v) => lsSet(LS + k, JSON.stringify(v));
// wszystkie wycinki sektorów EPWW (porównanie z .ese, granice kształtów LOW), raz na sesję
let allPromise = null;
const loadAll = () => (allPromise ||= api("/api/nav/sectors?fir=EPWW").catch((e) => { allPromise = null; throw e; }));
const flRange = (lo, hi) => `${fl(lo)}–${fl(hi)}`;

// Punkt etykiety wewnątrz wielokąta, możliwie daleko od krawędzi (uproszczony polylabel: siatka próbek)
const labelCache = new Map();
function labelPoint(f) {
  const key = `${f.properties.name}/${f.properties.lower_ft}`;
  if (labelCache.has(key)) return labelCache.get(key);
  const g = f.geometry;
  const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
  let best = null, bestD = -1;
  polys.forEach(([ring]) => {
    if (!ring?.length) return;
    const k = Math.cos((ring[0][1] * Math.PI) / 180);  // długość geogr. → te same jednostki co szerokość
    const pts = ring.map(([x, y]) => [x * k, y]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const N = 22;
    for (let i = 0; i < N; i++) {
      for (let j = 0; j < N; j++) {
        const x = x0 + ((x1 - x0) * (i + 0.5)) / N, y = y0 + ((y1 - y0) * (j + 0.5)) / N;
        let inside = false, d = Infinity;
        for (let a = 0, b = pts.length - 1; a < pts.length; b = a++) {
          const [ax, ay] = pts[a], [bx, by] = pts[b];
          if ((ay > y) !== (by > y) && x < ((bx - ax) * (y - ay)) / (by - ay) + ax) inside = !inside;
          const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
          const t = l2 ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) : 0;
          d = Math.min(d, Math.hypot(x - ax - t * dx, y - ay - t * dy));
        }
        if (inside && d > bestD) { bestD = d; best = [y, x / k]; }
      }
    }
  });
  labelCache.set(key, best);
  return best;
}

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
      <section class="ss-card ss-poscard"><h3>Stanowiska ACC <span class="ss-src"></span></h3>
        <div class="ss-modebar"><div class="seg ss-mode"><button data-mode="now">VATSIM teraz</button><button data-mode="sim">symulacja</button></div>
          <span class="ss-simbar"><button class="btn" data-act="none" title="Odznacz wszystkie stanowiska">wyłącz wszystkie</button>
            <button class="btn" data-act="online" title="Zaznacz stanowiska zalogowane teraz w VATSIM">kopiuj online</button>
            <button class="btn" data-act="all" title="Wszystkie stanowiska: każdy sektor u swojego pierwszego stanowiska">wszystkie</button></span></div>
        <div class="ss-status hint"></div>
        <div class="ss-pos"></div></section>
      <section class="ss-card"><h3>Kto co obsługuje <button class="ss-copy" title="Kopiuj podsumowanie jako tekst">kopiuj</button></h3>
        <div class="ss-sum"></div></section>
      <section class="ss-card"><h3 class="ss-dh">Sektor</h3><div class="ss-detail"></div></section>
    </div>
    <div class="ss-float"></div>
  </div>`);
  const $ = (s) => el.querySelector(s);
  const float = $(".ss-float");

  let vacs = null, positions = [], online = {}, onlineAt = 0, all = null, errNet = "";
  let mode = load("mode", "now") === "sim" ? "sim" : "now";
  let sim = new Set([load("sim", [])].flat().filter((c) => typeof c === "string"));  // odporne na uszkodzony wpis
  let lowFl = Math.min(LOW_MAX, Math.max(LOW_MIN, parseInt(load("fl", 300), 10) || 300));
  let sel = null, hoverPos = null, visible = false, fitted = false, baseName = null, active = new Set();
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
      v.base = BASEMAPS[name](L, ctx.config.carto_api_key).addTo(v.map);
      v.base.bringToBack?.();
      v.map.getContainer().classList.toggle("light", light);
      v.map.getContainer().classList.toggle("white", name === "white");
    });
    drawFirOutline();
    redraw();
  };
  const theme = () => (LIGHT_BASEMAPS.includes(baseName)
    ? { edge: "#ffffff", fir: "#2b2f2b", unicomEdge: "#8a918a", hole: "#9aa29a", holeFill: "#ffffff", hi: "#000000" }
    : { edge: "#050605", fir: "#d8e0d8", unicomEdge: "#737b73", hole: "#4a524a", holeFill: "#000000", hi: "#ffffff" });

  // --- dane
  const pos = (cs) => vacs?.acc_positions?.[cs] || {};
  const short = (cs) => pos(cs).short || cs;
  let byId = {};  // stanowiska z pliku .ese wg position_id
  const eseShort = () => Object.fromEntries(Object.values(vacs.acc_positions).map((p) => [p.ese_id, p.short]));
  // wpis VATSIM dla stanowiska VACS: klucze online to znaki z pliku .ese (dopasowanie przez ese_id)
  const onlineOf = (cs) => online[byId[pos(cs).ese_id]?.callsign] || online[cs] || null;
  const letters = () => Object.keys(vacs?.sectors || {}).sort();
  const chainOf = (s, ly) => vacs?.sectors?.[s]?.[ly] || [];
  const ownerOf = (s, ly) => chainOf(s, ly).find((c) => active.has(c)) || null;
  // stanowiska od najbardziej szczegółowych (pierwsze w łańcuchach) do zbiorczych (ALL, ALH)
  let order = [];
  const sortPositions = () => {
    const r = {};
    Object.values(vacs.sectors).forEach((ls) => Object.values(ls).forEach((ch) => ch.forEach((c, i) => (r[c] ||= []).push(i / Math.max(1, ch.length - 1)))));
    const avg = (c) => (r[c] ? r[c].reduce((a, b) => a + b, 0) / r[c].length : 2);
    order = Object.keys(vacs.acc_positions).sort((a, b) => avg(a) - avg(b) || short(a).localeCompare(short(b)));
  };
  const computeActive = () => { active = mode === "sim" ? new Set(order.filter((c) => sim.has(c))) : new Set(order.filter(onlineOf)); };

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
      ? it.own ? { color: t.edge, weight: 1, opacity: 0.9, dashArray: null, fillColor: colorFor(it.own), fillOpacity: 0.55 }
        : { color: t.unicomEdge, weight: 1, opacity: 0.9, dashArray: "3 3", fillColor: UNICOM, fillOpacity: 0.32 }
      : { color: t.hole, weight: 0.8, opacity: 0.8, dashArray: "2 3", fillColor: t.holeFill, fillOpacity: 0.35 };  // TMA/CTA: "dziura" w ACC
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
    + (it.own ? `<i style="background:${colorFor(it.own)}"></i>${esc(short(it.own))}` : `<i class="un"></i>UNICOM`) + "</div>";
  const drawMap = (v) => {
    v.layer.clearLayers();
    v.items = [];
    if (!v.gj || !vacs) return;
    // najpierw TMA/CTA (tło), na wierzchu sektory ACC
    const feats = [...v.gj.features].sort((a, b) => !!accLetter(a.properties.name) - !!accLetter(b.properties.name));
    feats.forEach((f) => {
      const pr = f.properties;
      if (pr.name === "EPWW-MIDSEA") return;
      const letter = vacs.sectors[accLetter(pr.name)] ? accLetter(pr.name) : null;
      const it = { f, letter, own: letter ? ownerOf(letter, v.ly) : null, hover: false };
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
      v.items.push(it);
      const at = letter && labelPoint(f);
      if (at) {
        it.label = L.marker(at, { interactive: false, keyboard: false, icon: L.divIcon({ className: "maplabel ss-maplabel", iconSize: null, html: labelHtml(it) }) })
          .addTo(v.layer);
      }
    });
    if (sel || hoverPos) restyle();
  };
  const redraw = () => {
    if (!vacs) return;
    hideFloat();  // wielokąt pod kursorem jest rysowany od nowa (bez mouseout)
    computeActive();
    Object.values(views).forEach(drawMap);
    renderPositions();
    renderSummary();
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
    drawMap(v);
    if (v.ly === "LOW") renderBand();
    if (!fitBounds && v.items.length) {
      fitBounds = L.featureGroup(v.items.map((it) => it.poly)).getBounds();
      if (visible && !fitted) fit();
    }
  };

  // --- przekrój LOW: przedziały, w których kształty sektorów ACC są stałe (granice wycinków z pliku .ese)
  const lowBounds = () => {
    const lo = vacs.layers.LOW.lower_ft, hi = vacs.layers.LOW.upper_ft;
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
    if (!vacs) return;
    const { b, i, lo, hi } = band();
    const card = views.LOW.card;
    card.querySelector(".ss-rng").textContent = vacs.layers.LOW.label;
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
    if (!vacs) return;
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

  // łańcuch stanowisk z wyróżnionym właścicielem; aktywne przed właścicielem nie występują, nieaktywne przygaszone
  const chainHtml = (chain, owner) => `<ol class="ss-chain">${chain.map((c, i) => {
    const on = onlineOf(c);
    const cls = c === owner ? "own" : active.has(c) ? "act" : "off";
    return `<li class="${cls}" title="${esc(c)}${on ? ` · online: ${esc(on.name || "")}` : ""}"><span class="n">${i + 1}</span>`
      + `<i style="background:${colorFor(c)}"></i><b>${esc(short(c))}</b><span class="fq">${esc(pos(c).frequency || "")}</span>`
      + `${on ? `<span class="onl">online</span>` : ""}${c === owner ? `<span class="tag">właściciel</span>` : ""}</li>`;
  }).join("")}</ol>`;
  // właściciel: pełny opis (dymek) albo skrót z częstotliwością (kolumny szczegółów)
  const ownerLine = (owner, full = true) => {
    if (!owner) return `<span class="ss-unicom">UNICOM 122.800</span>${full ? ` <span class="muted">nikt z łańcucha nie jest ${mode === "sim" ? "zaznaczony" : "online"}</span>` : ""}`;
    const on = onlineOf(owner);
    return `<i class="ss-swi" style="background:${colorFor(owner)}"></i><b>${esc(short(owner))}</b> ${full ? esc(owner) + " " : ""}<span class="fq">${esc(pos(owner).frequency || "")}</span>`
      + (on && full ? ` <span class="muted">${esc(on.name || "")}</span>` : "");
  };
  // lista OWNER z pliku .ese dla wycinka, w skrótach VACS; porównanie z łańcuchem VACS
  const eseCompare = (owners, chain) => {
    const map = eseShort();
    const ese = (owners || []).map((id) => map[id] || id);
    const vs = chain.map(short);
    if (ese.join(" ") === vs.join(" ")) return { same: true, html: `<div class="ss-ese ok">.ese OWNER: zgodna z VACS</div>` };
    const extra = ese.filter((s) => !vs.includes(s)), missing = vs.filter((s) => !ese.includes(s));
    // inna kolejność: porównanie samych wspólnych stanowisk (dodatkowe nie przesuwają reszty)
    const ce = ese.filter((s) => vs.includes(s)), cv = vs.filter((s) => ese.includes(s));
    const moved = new Set(ce.filter((s, i) => s !== cv[i]));
    // właściciel wg .ese przy tym samym zbiorze aktywnych stanowisk
    const ids = Object.fromEntries(Object.entries(vacs.acc_positions).map(([cs, p]) => [p.ese_id, cs]));
    const eseOwner = (owners || []).map((id) => ids[id]).find((cs) => cs && active.has(cs)) || null;
    const vacsOwner = chain.find((c) => active.has(c)) || null;
    const notes = [extra.length && `w .ese dodatkowo ${extra.join(", ")}`, missing.length && `brak w .ese: ${missing.join(", ")}`,
      moved.size && "inna kolejność"].filter(Boolean);
    return { same: false, notes, html: `<div class="ss-ese diff"><span class="k">.ese OWNER:</span> ${ese.map((s) =>
      `<span class="${extra.includes(s) ? "x" : moved.has(s) ? "o" : ""}">${esc(s)}</span>`).join(" ")}
      <div class="ss-esenote">${esc(notes.join(" · "))}${eseOwner !== vacsOwner
        ? ` · <b>właściciel wg .ese: ${eseOwner ? esc(short(eseOwner)) : "UNICOM"}</b> (VACS: ${vacsOwner ? esc(short(vacsOwner)) : "UNICOM"})` : ""}</div></div>` };
  };
  const tipHtml = (v, it) => {
    const pr = it.f.properties;
    if (!it.letter) {
      const map = eseShort();
      return `<div class="ss-fh"><b>${esc(pr.name)}</b><span>${flRange(pr.lower_ft, pr.upper_ft)}</span></div>
        <div class="ss-fsub">poza sektorami ACC (TMA / CTA) · właściciel z listy OWNER pliku .ese</div>
        <div class="ss-ese"><span class="k">.ese OWNER:</span> ${(pr.owners || []).map((id) => esc(map[id] || id)).join(" ")}</div>`;
    }
    const chain = chainOf(it.letter, v.ly);
    return `<div class="ss-fh"><b>Sektor ${esc(it.letter)}</b><span>${v.ly} · ${esc(vacs.layers[v.ly].label)}</span></div>
      <div class="ss-fsub">wycinek ${esc(pr.name)} ${flRange(pr.lower_ft, pr.upper_ft)}</div>
      <div class="ss-own">${ownerLine(it.own)}</div>
      <div class="ss-k">Łańcuch VACS (kolejność przejmowania)</div>${chainHtml(chain, it.own)}
      ${eseCompare(pr.owners, chain).html}
      <div class="ss-fhint">kliknij: wszystkie warstwy sektora</div>`;
  };

  // --- panel stanowisk
  const renderStatus = () => {
    if (!vacs) return;
    const onl = order.filter(onlineOf);
    $(".ss-status").innerHTML = (mode === "sim"
      ? `Symulacja: ${active.size ? `zaznaczone ${active.size} z ${order.length}` : "nic nie zaznaczono"}. Kliknij stanowisko, żeby je włączyć lub wyłączyć.`
      : errNet ? "" : `VATSIM ${onlineAt ? hhmm(new Date(onlineAt).toISOString()) : "…"} · ACC online: ${onl.length ? onl.map((c) => `<b>${esc(short(c))}</b>`).join(", ") : "nikt"}`)
      + [errNet, ...VACS_LAYERS.map((ly) => views[ly].err)].filter(Boolean).map((e) => ` <span class="error">${esc(e)}</span>`).join("");
  };
  const paintMode = () => {
    el.querySelectorAll(".ss-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    $(".ss-poscard").classList.toggle("sim", mode === "sim");
  };
  const renderPositions = () => {
    paintMode();
    renderStatus();
    $(".ss-pos").innerHTML = order.map((c) => {
      const on = onlineOf(c), act = active.has(c);
      const tip = `${c} · ${pos(c).frequency} · w pliku .ese: ${pos(c).ese_id}${on ? `\nonline: ${on.name || "?"} (CID ${on.cid ?? "?"}), od ${hhmm(on.logon_time)}` : ""}`;
      return `<label class="ss-prow${act ? " act" : ""}${on ? " onl" : ""}${hoverPos === c ? " hl" : ""}" data-cs="${esc(c)}" title="${esc(tip)}">`
        + (mode === "sim" ? `<input type="checkbox" ${sim.has(c) ? "checked" : ""}>` : `<span class="ss-dot"></span>`)
        + `<i class="ss-sw" style="background:${colorFor(c)}"></i><b class="ss-short">${esc(short(c))}</b>`
        + `<span class="ss-fq${on ? " on" : ""}">${esc(pos(c).frequency || "")}</span><span class="ss-who">${on ? esc(on.name || "online") : ""}</span></label>`;
    }).join("");
  };
  const setMode = (m) => { mode = m; save("mode", m); redraw(); };
  $(".ss-mode").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) setMode(b.dataset.mode); });
  const setSim = (list) => { sim = new Set(list); save("sim", [...sim]); redraw(); };
  $(".ss-simbar").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b || !vacs) return;
    if (b.dataset.act === "online") {
      await refreshOnline();  // świeży stan sieci
      if (errNet) { renderStatus(); return; }  // bez danych z sieci nie kasujemy zaznaczeń
    }
    setSim(b.dataset.act === "none" ? [] : b.dataset.act === "online" ? order.filter(onlineOf) : order);
  });
  $(".ss-pos").addEventListener("change", (e) => {
    const row = e.target.closest(".ss-prow");
    if (!row || mode !== "sim") return;
    const s = new Set(sim);
    if (e.target.checked) s.add(row.dataset.cs); else s.delete(row.dataset.cs);
    setSim([...s]);
  });
  // najechanie na stanowisko (lista albo podsumowanie): jego sektory obrysowane na wszystkich mapach
  const setHover = (cs) => {
    if (cs === hoverPos) return;
    hoverPos = cs;
    el.querySelectorAll(".ss-prow, .ss-sumt tr").forEach((r) => r.classList.toggle("hl", !!cs && r.dataset.cs === cs));
    restyle();
  };
  [".ss-pos", ".ss-sum"].forEach((s) => {
    $(s).addEventListener("mouseover", (e) => setHover(e.target.closest("[data-cs]")?.dataset.cs || null));
    $(s).addEventListener("mouseleave", () => setHover(null));
  });

  // --- podsumowanie: kto co obsługuje (jak na plvacc: "N — B LMH, E LMH"), sektory bez kontrolera
  const summary = () => {
    const own = new Map(), un = {};
    letters().forEach((s) => VACS_LAYERS.forEach((ly) => {
      const o = ownerOf(s, ly);
      const m = o ? (own.get(o) || own.set(o, {}).get(o)) : un;
      (m[s] ||= []).push(ly[0]);
    }));
    const fmt = (m) => Object.entries(m).map(([s, ls]) => `${s} ${ls.join("")}`).join(", ");
    // aktywne stanowiska bez sektorów (wszystko przejęte przez stanowiska wcześniej w łańcuchach) na końcu
    const rows = [...own.entries(), ...order.filter((c) => active.has(c) && !own.has(c)).map((c) => [c, {}])]
      .map(([c, m]) => ({ c, m, n: Object.values(m).flat().length }))
      .sort((a, b) => b.n - a.n || order.indexOf(a.c) - order.indexOf(b.c));
    return { rows, own, un, fmt };
  };
  const renderSummary = () => {
    const { rows, own, un, fmt } = summary();
    const total = letters().length * VACS_LAYERS.length;
    const unN = Object.values(un).flat().length;
    $(".ss-sum").innerHTML = `<table class="ss-sumt"><tbody>${rows.map(({ c, m, n }) => `<tr data-cs="${esc(c)}"${hoverPos === c ? ' class="hl"' : ""}>
        <td><i class="ss-swi" style="background:${colorFor(c)}"></i><b>${esc(short(c))}</b></td><td class="fq">${esc(pos(c).frequency || "")}</td>
        <td class="sec">${n ? Object.entries(m).map(([s, ls]) => `<span><b>${esc(s)}</b> ${ls.join("")}</span>`).join("")
          : `<span class="muted">bez sektorów (przejęte wcześniej w łańcuchach)</span>`}</td><td class="n">${n}</td></tr>`).join("")}
      ${unN ? `<tr class="un"><td><i class="ss-swi un"></i><b>UNICOM</b></td><td class="fq">122.800</td>
        <td class="sec">${Object.entries(un).map(([s, ls]) => `<span><b>${esc(s)}</b> ${ls.join("")}</span>`).join("")}</td><td class="n">${unN}</td></tr>` : ""}
      </tbody></table>
      <div class="ss-sumnote hint">${own.size ? `${own.size} ${own.size === 1 ? "stanowisko obsługuje" : own.size < 5 ? "stanowiska obsługują" : "stanowisk obsługuje"} ${total - unN} z ${total}`
        : "Żadne stanowisko ACC nie jest aktywne"} (sektor × warstwa: L = LOW ${esc(vacs.layers.LOW.label)}, M = MID ${esc(vacs.layers.MID.label)},
        H = HIGH ${esc(vacs.layers.HIGH.label)}).</div>`;
    $(".ss-copy").onclick = () => {
      const txt = [...rows.map(({ c, m, n }) => `${short(c)} ${pos(c).frequency} — ${n ? fmt(m) : "bez sektorów"}`),
        ...(unN ? [`UNICOM 122.800 — ${fmt(un)}`] : [])].join("\n");
      navigator.clipboard?.writeText(txt).then(() => { $(".ss-copy").textContent = "skopiowano"; setTimeout(() => { $(".ss-copy").textContent = "kopiuj"; }, 1500); })
        .catch(() => { /* brak dostępu do schowka */ });
    };
  };

  // --- szczegóły: kliknięty sektor we wszystkich warstwach; bez wyboru różnice VACS ↔ .ese
  const slicesOf = (s, ly) => (all?.features || []).filter((f) => accLetter(f.properties.name) === s
    && f.properties.lower_ft >= vacs.layers[ly].lower_ft && f.properties.lower_ft < vacs.layers[ly].upper_ft);
  // warianty listy OWNER w warstwie (zwykle jeden), z zakresem poziomów
  const eseVariants = (s, ly) => {
    const out = new Map();
    slicesOf(s, ly).forEach((f) => {
      const k = (f.properties.owners || []).join(":");
      const o = out.get(k) || out.set(k, { owners: f.properties.owners, lo: Infinity, hi: -Infinity }).get(k);
      o.lo = Math.min(o.lo, f.properties.lower_ft);
      o.hi = Math.max(o.hi, f.properties.upper_ft);
    });
    return [...out.values()];
  };
  const select = (s) => { sel = s; restyle(); renderDetail(); };
  const renderDetail = () => {
    const d = $(".ss-detail");
    if (!vacs) { d.innerHTML = ""; return; }
    if (sel) {
      $(".ss-dh").innerHTML = `Sektor ${esc(sel)} <button class="ss-x" title="Zamknij">✕</button>`;
      d.innerHTML = `<div class="ss-cols">${VACS_LAYERS.map((ly) => {
        const chain = chainOf(sel, ly), owner = ownerOf(sel, ly);
        const vars = eseVariants(sel, ly);
        return `<div class="ss-col"><div class="ss-colh"><b>${ly}</b> <span>${esc(vacs.layers[ly].label)}</span></div>
          <div class="ss-own">${ownerLine(owner, false)}</div>${chainHtml(chain, owner)}
          ${vars.map((x) => `${vars.length > 1 ? `<div class="ss-k">${flRange(x.lo, x.hi)}</div>` : ""}${eseCompare(x.owners, chain).html}`).join("")}</div>`;
      }).join("")}</div>`;
      return;
    }
    $(".ss-dh").textContent = "Sektor";
    const diffs = [];
    letters().forEach((s) => VACS_LAYERS.forEach((ly) => eseVariants(s, ly).forEach((x) => {
      const r = eseCompare(x.owners, chainOf(s, ly));
      if (!r.same) diffs.push(`<li><b>${esc(s)} ${ly}</b> <span class="muted">${flRange(x.lo, x.hi)}</span> ${r.html}</li>`);
    })));
    d.innerHTML = `<p class="hint">Najedź na sektor: łańcuch VACS w tej warstwie. Kliknij: łańcuchy we wszystkich warstwach.
        Najedź na stanowisko: jego sektory na mapach.</p>
      <div class="ss-k">Różnice łańcuchów VACS i list OWNER z pliku .ese</div>
      ${all?.err ? `<p class="error">Wycinki sektorów z pliku .ese: ${esc(all.err)} (ponowna próba co minutę)</p>`
        : all ? (diffs.length ? `<ul class="ss-diffs">${diffs.join("")}</ul>` : `<p class="hint">Brak różnic: wszystkie łańcuchy zgodne.</p>`)
        : `<p class="hint">Ładowanie…</p>`}
      <p class="hint ss-lic">Łańcuchy: <a href="${esc(vacs.url)}" target="_blank" rel="noopener">vacs-data</a> (commit ${esc((vacs.commit || "").slice(0, 7))},
        ${esc(vacs.commit_date || "")}), licencja CC BY-NC-SA 4.0. Zasady jak w
        <a href="https://om.plvacc.pl/docs/2610/ownerships" target="_blank" rel="noopener">om.plvacc.pl ownerships ↗</a>.</p>`;
  };
  $(".ss-dh").addEventListener("click", (e) => { if (e.target.closest(".ss-x")) select(null); });

  // --- start i odświeżanie stanu sieci
  const refreshOnline = async () => {
    try {
      online = (await vatsimOnline()).positions || {};
      onlineAt = Date.now();
      errNet = "";
    } catch (e) { online = {}; errNet = `VATSIM: ${e.message}`; }
  };
  const init = async () => {
    try {
      [vacs, positions] = await Promise.all([loadVacs(), atcPositions().catch(() => [])]);
    } catch (e) {
      $(".ss-status").innerHTML = `<span class="error">Brak danych VACS: ${esc(e.message)}</span>`;
      return;
    }
    byId = Object.fromEntries(positions.map((p) => [p.position_id, p]));
    sortPositions();
    VACS_LAYERS.forEach((ly) => { views[ly].card.querySelector(".ss-rng").textContent = vacs.layers[ly].label; });
    $(".ss-src").innerHTML = `<span title="Łańcuchy controlled_by z vacs-data, licencja CC BY-NC-SA 4.0">VACS</span>`;
    await refreshOnline();
    redraw();
    VACS_LAYERS.forEach((ly) => loadLayer(views[ly]));
    loadSlices();
  };
  const loadSlices = () => loadAll().then((g) => { all = g; renderBand(); renderDetail(); })
    .catch((e) => { all = { features: [], err: e.message }; renderDetail(); });
  paintMode();
  syncBase();
  init();
  setInterval(async () => {
    if (!visible || !el.isConnected || !el.offsetWidth) return;
    if (!vacs) { init(); return; }  // ponowna próba po błędzie /api/nav/vacs
    // ponowna próba po błędzie wycinków (np. serwer jeszcze wczytuje plik .ese)
    VACS_LAYERS.forEach((ly) => { if (!views[ly].gj) loadLayer(views[ly]); });
    if (all?.err) loadSlices();
    await refreshOnline();
    redraw();
  }, 60000);

  return {
    el,
    show: () => {
      visible = true;
      setTimeout(() => {
        if (!el.isConnected) return;
        Object.values(views).forEach((v) => v.map.invalidateSize({ animate: false }));
        syncBase();
        if (!fitted) fit();
        // po powrocie do widoku świeży stan sieci (cache VATSIM 30 s)
        if (vacs && Date.now() - onlineAt > 30000) refreshOnline().then(redraw);
      }, 30);
    },
    hide: () => { visible = false; hideFloat(); },
  };
}
