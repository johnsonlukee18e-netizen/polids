// RADIO › GEO: strony GEO jak w VACS (kafelki stanowisk z profilu ACC_EPWW, vacs-data CC BY-NC-SA 4.0; bez FMP)
// z częstotliwościami i stanem sieci, obok mapa zasięgu. Kliknięcie kafelka włącza/wyłącza pozycję w symulacji
// (kilka naraz). Mapa: wycinki sektorów z pliku .ese (sąsiedzi: z plików .ese ich vACC), które przejmuje każda
// aktywna pozycja (coverage.js); bez wycinków – granica z VATSpy albo przybliżony okrąg wokół lotniska. Kafelek sektora ACC ("B H") pokazuje,
// kto teraz ma ten sektor w tej warstwie (kolejność z /api/nav/ownership), a kliknięty – zaznacza go na mapie.
import { BASEMAPS, LIGHT_BASEMAPS, esc, h, hhmm, lsGet, lsSet } from "./api.js";
import { VACS_LAYERS, drawFirs, loadFirs, loadVacs } from "./airspace.js";
import { accSummary, accText, geomKey, labelPoint, levelOk, levelText, rangeText, sliceChain, sliceOwner } from "./coverage.js";
import { displayName, loadDisplayNames } from "./posname.js";
import * as R from "./radiostate.js";

// tytuły stron w polskiej formie; strona FMP zostaje pustym miejscem (Marek: bez kafelków FMP)
const PAGE_TITLES = { "ACC / KRAJ": "ACC KRAJ", "TWR / KRAJ": "TWR KRAJ", "APP / KRAJ": "APP KRAJ", FIS: "FIS",
  "MALMO / VILNUS": "MALMÖ / VILNIUS", "RHEIN / BREMEN / MUNICH": "RHEIN / BREMEN / MÜNCHEN",
  "UMKK / MINSK / LVIV": "KALININGRAD / MIŃSK / LWÓW", "PRAHA / BRATI / SLAVA": "PRAGA / BRATYSŁAWA" };
// strona bez kluczy (albo spoza listy) liczy się jak FMP: pomijana
const fmpPage = (p) => !p?.keys?.length || p.keys.every((k) => !k || k.fmp);
const KINDS = [["acc", "ACC", "sektory ACC EPWW"], ["tma", "TMA", "TMA, APP i CTA"], ["ctr", "CTR", "strefy CTR lotnisk"],
  ["fis", "FIS", "FIS, ATZ i TRA"], ["nb", "SĄSIEDZI", "sektory sąsiednich FIR-ów z plików .ese ich vACC"]];
const KIND_Z = { nb: 0, acc: 1, fis: 2, tma: 3, ctr: 4 };
const KIND_ORDER = ["tma", "ctr", "fis", "nb"];
const LS = "radio.geo.";
const load = (k, d) => { try { const v = JSON.parse(lsGet(LS + k)); return v ?? d; } catch { return d; } };
const save = (k, v) => lsSet(LS + k, JSON.stringify(v));
const RANK = { 1: "OBS", 2: "S1", 3: "S2", 4: "S3", 5: "C1", 6: "C2", 7: "C3", 8: "I1", 9: "I2", 10: "I3", 11: "SUP", 12: "ADM" };

export function geoView(ctx) {
  const el = h(`<div class="geo-root">
    <div class="geo-left">
      <div class="geo-bar">
        <div class="seg geo-mode"><button data-mode="now" title="Aktywne = stanowiska zalogowane teraz w sieci VATSIM">VATSIM teraz</button><button data-mode="sim" title="Aktywne = pozycje wybrane kliknięciem (zapamiętane w przeglądarce)">symulacja</button></div>
        <span class="geo-simbar">
          <button class="btn" data-act="clear" title="Wyłącz wszystkie pozycje w symulacji">wyczyść</button>
          <button class="btn" data-act="online" title="Symulacja od stanowisk zalogowanych teraz w VATSIM">kopiuj online</button>
          <button class="btn" data-act="acc" title="Dodaj do symulacji wszystkie stanowiska ACC EPWW (pełny podział sektorów); pozostałe pozycje zostają">wszystkie ACC</button></span>
      </div>
      <div class="geo-status hint"></div>
      <nav class="geo-pages"></nav>
      <div class="geo-grid"><p class="hint">Ładowanie stron GEO…</p></div>
      <div class="geo-legend"></div>
      <section class="geo-card geo-who"><h3>Kto co obsługuje <span class="geo-whon"></span><button class="geo-copy" title="Kopiuj listę jako tekst">kopiuj</button></h3>
        <div class="geo-wholist"></div></section>
    </div>
    <section class="geo-mapcard">
      <div class="geo-mh">
        <span class="geo-lv">${VACS_LAYERS.map((l) => `<button data-lv="${l}">${l}</button>`).join("")}
          <span class="flbox" title="Przekrój na jednym poziomie lotu">FL<input type="number" class="field geo-fl" min="0" max="660" step="5"></span>
          <button data-lv="all" title="Wszystkie poziomy: wycinki niezależnie od wysokości (rzut 2D)">wszystkie</button></span>
        <span class="geo-kinds">${KINDS.map(([k, l, t]) => `<button data-kind="${k}" title="${esc(`${t}: pokaż / ukryj${k === "acc" ? "" : ". Wycinki aktywnej pozycji, która nie ma innych widocznych (np. sam FIS), zostają na mapie"}`)}">${l}</button>`).join("")}</span>
        
      </div>
      <div class="geo-map map"></div>
      <div class="geo-info"></div>
    </section>
    <div class="geo-float"></div>
  </div>`);
  const $ = (s) => el.querySelector(s);
  const float = $(".geo-float");

  let vacs = null, own = null, sectors = null, firs = null, pos = {}, errs = {};
  let page = load("page", 0), lv = load("level", { k: "all" }), kinds = load("kinds", {});
  if (!Number.isInteger(page) || page < 0) page = 0;  // uszkodzony wpis; zakres stron sprawdza init()
  if (!lv || !["all", "fl", ...VACS_LAYERS].includes(lv.k)) lv = { k: "all" };
  if (lv.k === "fl" && !(Number.isFinite(lv.fl) && lv.fl >= 0 && lv.fl <= 660)) lv = { k: "fl", fl: 300 };
  // rodzaje wycinków: brakujące albo uszkodzone wpisy = włączone
  kinds = Object.fromEntries(KINDS.map(([k]) => [k, kinds && typeof kinds === "object" && kinds[k] === 0 ? 0 : 1]));
  let active = new Set(), colors = {}, focus = null, hoverCs = null, visible = false, dirty = true, fitted = false, baseName = null;
  $(".geo-fl").value = lv.fl || 300;

  // --- mapa
  const map = L.map($(".geo-map"), { zoomSnap: 0.25, zoomDelta: 0.5, attributionControl: true, minZoom: 4, maxZoom: 11 })
    .setView([52.0, 19.3], 5.5, { animate: false });
  map.attributionControl.setPrefix(false);
  map.createPane("geoFir").style.zIndex = 450;  // obrys FIR nad wycinkami, pod etykietami
  map.getPane("geoFir").style.pointerEvents = "none";
  map.createPane("geoRange").style.zIndex = 430;  // zasięg z VATSpy i okręgi nad wycinkami
  // przyciski widoku pod +/−: cała FIR EPWW i wszystko, co obsługują aktywne pozycje
  const ViewCtl = L.Control.extend({
    onAdd: () => {
      const d = L.DomUtil.create("div", "leaflet-bar geo-viewctl");
      d.innerHTML = `<a href="#" role="button" class="geo-fit" title="Pokaż całą FIR EPWW">⌂</a>`
        + `<a href="#" role="button" class="geo-fitall" title="Pokaż wszystko, co obsługują aktywne pozycje (także zasięg sąsiadów)">⤢</a>`;
      L.DomEvent.disableClickPropagation(d);
      L.DomEvent.on(d, "click", (e) => L.DomEvent.preventDefault(e));
      return d;
    },
  });
  new ViewCtl({ position: "topleft" }).addTo(map);
  let base = null;
  const firLayer = L.layerGroup().addTo(map), secLayer = L.layerGroup().addTo(map), rangeLayer = L.layerGroup().addTo(map),
    lblLayer = L.layerGroup().addTo(map);
  let items = [], fitB = null, auto = true, fitting = false;
  // dopasowanie do FIR EPWW; dopóki użytkownik nie przesunie ani nie przybliży mapy, powtarzane po zmianie rozmiaru
  const fit = () => {
    if (!fitB || map.getSize().x < 40 || map.getSize().y < 40) return;  // ukryta mapa: zoom wyszedłby NaN
    fitting = true;
    map.fitBounds(fitB, { padding: [8, 8], animate: false });
    fitting = false;
    fitted = true;
    if (visible) drawLabels();
  };
  map.on("movestart zoomstart", () => { if (!fitting) auto = false; });
  map.on("zoomend", () => { if (visible && !fitting) drawLabels(); });
  $(".geo-fit").addEventListener("click", () => { auto = true; fit(); });
  // dopasowanie do FIR EPWW i wszystkiego, co przejmują aktywne pozycje (wycinki i zasięg zastępczy)
  $(".geo-fitall").addEventListener("click", () => {
    if (!fitB || map.getSize().x < 40) return;
    const bb = L.latLngBounds(fitB.getSouthWest(), fitB.getNorthEast());
    items.forEach((it) => { if (it.own) bb.extend(it.poly.getBounds()); });
    rangeLayer.eachLayer((l) => bb.extend(l.getBounds ? l.getBounds() : l.getLatLng()));
    fitting = true;
    map.fitBounds(bb, { padding: [8, 8], animate: false });
    fitting = false;
    auto = false;
    drawLabels();
  });
  const ro = new ResizeObserver(() => {
    if (!visible || !el.isConnected) return;
    fitting = true;
    map.invalidateSize({ animate: false });
    fitting = false;
    if (auto) fit(); else drawLabels();
    if (map.getSize().x >= 40) syncBase();  // podkład mógł się zmienić w zakładce MAP
    if (dirty) render();
  });
  ro.observe($(".geo-map"));
  const syncBase = () => {
    const name = BASEMAPS[lsGet("map.base")] ? lsGet("map.base") : "dark";
    if (name === baseName) return;
    baseName = name;
    if (base) map.removeLayer(base);
    base = BASEMAPS[name](L, ctx.config?.carto_api_key).addTo(map);
    base.bringToBack?.();
    map.getContainer().classList.toggle("light", LIGHT_BASEMAPS.includes(name));
    drawFirLayer();
    dirty = true;
  };
  const theme = () => (LIGHT_BASEMAPS.includes(baseName) ? { fir: "#2b2f2b", free: "#7d857d", hi: "#000" } : { fir: "#d8e0d8", free: "#5d665d", hi: "#fff" });
  const drawFirLayer = () => {
    firLayer.clearLayers();
    if (!firs) return;
    drawFirs(firLayer, firs, {}, { labels: true });
    const epww = firs.features.find((f) => f.properties.id === "EPWW");
    if (epww) {
      L.geoJSON(epww, { interactive: false, pane: "geoFir", style: { color: theme().fir, weight: 1.6, opacity: 0.85, fill: false } }).addTo(firLayer);
      fitB ||= L.geoJSON(epww).getBounds();
    }
  };

  // --- dane
  const P = (cs) => pos[cs] || null;
  // częstotliwość z pliku .ese / ownership.json; z VACS (kafelek) tylko gdy stanowiska tam nie ma
  const freqOf = (cs) => P(cs)?.frequency || own?.acc_positions?.[cs]?.frequency || "";
  const tileFreq = (k) => freqOf(k.callsign) || k.frequency || "";
  const freqDiff = (k) => !!k.frequency && !!freqOf(k.callsign) && Math.abs(parseFloat(k.frequency) - parseFloat(freqOf(k.callsign))) > 0.001;
  const firById = () => Object.fromEntries((firs?.features || []).map((f) => [f.properties.id, f]));

  // nazwa wycinka na liście: sąsiedzi wg stanowiska, do którego wycinek należy (pierwsze na liście OWNER),
  // jak w VACS (EDMM_MEI_CTR → EDMM MEI, EDDB_N_APP → EDDB N APP); EPWW: TMA Warszawa, CTR Kraków…
  const secName = (pr) => (pr.kind === "nb" && pr.owners?.[0] ? displayName(pr.owners[0]) : pr.group);
  // aktywne pozycje, ich kolory, przejęte wycinki (nazwy zbiorcze bez ACC) i kto ma choć jeden wycinek z pliku .ese
  let grp = {}, owned = new Set();
  const compute = () => {
    active = R.activeSet();
    colors = R.colorMap(active);
    grp = {};
    owned = new Set();
    (sectors?.features || []).forEach((f) => {
      const pr = f.properties, o = sliceOwner(pr, active, own);
      if (!o) return;
      owned.add(o);
      if (pr.kind !== "acc") ((grp[o] ||= {})[pr.kind] ||= new Set()).add(secName(pr));
    });
  };
  // wszystkie pozycje z list OWNER pliku .ese i z kolejności przejmowania sektorów ACC
  let listedSet = null, listedFor = [];
  const listed = () => {
    if (listedSet && listedFor[0] === sectors && listedFor[1] === own) return listedSet;
    listedFor = [sectors, own];
    listedSet = new Set(Object.values(own?.sectors || {}).flatMap((ls) => Object.values(ls).flat()));
    (sectors?.features || []).forEach((f) => (f.properties.owners || []).forEach((c) => listedSet.add(c)));
    return listedSet;
  };
  // zasięg zastępczy (gdy brak wycinków w pliku .ese): granica z VATSpy, okrąg wokół lotniska; GND/DEL = punkt.
  // Dokładna granica sektora z VATSpy zostaje też obok wycinków, przybliżenia (cały FIR, okrąg) – tylko bez nich.
  // Stanowiska EP: tylko gdy nie ma ich na żadnej liście przejmowania (np. EPBK_R_TWR, EPKS_P_APP) – stanowisko
  // z wycinkami, które teraz ma ktoś wyżej w kolejności, nie dostaje okręgu.
  const fallback = (cs) => {
    const r = P(cs)?.range;
    if (!r || r.kind === "point") return r || null;
    if (cs.startsWith("EP")) return owned.has(cs) || listed().has(cs) ? null : r;
    // sąsiad z dokładnymi sektorami z pliku .ese swojego vACC: jak stanowiska EP (bez obrysu VATSpy na wycinkach)
    if (P(cs)?.nb_ese) return owned.has(cs) || listed().has(cs) ? null : r;
    if (r.kind === "vatspy" && r.exact) return r;
    return owned.has(cs) ? null : r;
  };

  // --- strony i kafelki
  const pages = () => vacs?.geo_pages || [];
  const renderPages = () => {
    $(".geo-pages").innerHTML = pages().map((p, i) => (fmpPage(p) ? `<span class="geo-pg empty" title="Strona FMP pominięta"></span>`
      : `<button class="geo-pg${i === page ? " on" : ""}" data-pg="${i}" title="${esc(PAGE_TITLES[p.label] || p.label)}">${esc(PAGE_TITLES[p.label] || p.label)}</button>`)).join("");
  };
  const ownerOfSector = (letter, layer) => (own?.sectors?.[letter]?.[layer] || []).find((c) => active.has(c)) || null;
  const tileHtml = (k, i) => {
    if (!k || k.fmp) return `<div class="gt sp"></div>`;
    const lines = k.lines.map((l) => `<span class="gl${l === k.alt ? " alt" : ""}">${esc(l)}</span>`).join("");
    if (k.sector) {
      const o = ownerOfSector(k.sector.letter, k.sector.layer);
      const cls = ["gt", "sec", o ? "act" : "", o && R.state.online[o] ? "on" : "",
        focus && focus.letter === k.sector.letter && focus.layer === k.sector.layer ? "focus" : ""].join(" ");
      return `<button class="${cls}" data-i="${i}" ${o ? `style="--pc:${colors[o]}"` : ""}>${lines}`
        + (o ? `<span class="go">${esc(displayName(o))}</span><span class="gf">${esc(freqOf(o))}</span>` : "") + "</button>";
    }
    const cs = k.callsign, p = P(cs), freq = tileFreq(k);
    const on = R.state.online[cs], bk = (R.state.bookings[cs] || []).length;
    // sąsiad: kolor FIR-u jak w VACS (pasek z lewej i zabarwione tło); online i rezerwacja jak dotąd
    const fc = R.firColor(cs, p?.fir);
    const cls = ["gt", fc ? "fir" : "", on ? "on" : bk ? "bk" : "", !p && !freq ? "unk" : "", active.has(cs) ? "act" : "", hoverCs === cs ? "hl" : ""].join(" ");
    const css = [fc && `--fc:${fc}`, active.has(cs) && `--pc:${colors[cs]}`].filter(Boolean).join(";");
    return `<button class="${cls}" data-i="${i}" data-cs="${esc(cs || "")}"${css ? ` style="${css}"` : ""}>${lines}`
      + `<span class="gf">${esc(freq)}</span></button>`;
  };
  // legenda pod kafelkami: stany kafelka i kolory FIR-ów sąsiadów z tej strony
  const renderLegend = (pg) => {
    const firs = [...new Set((pg?.keys || []).filter((k) => k && !k.fmp && !k.sector).map((k) => R.firKey(k.callsign, P(k.callsign)?.fir)).filter(Boolean))];
    $(".geo-legend").innerHTML = !pg ? "" : `<span class="glg" title="Stanowisko zalogowane teraz w sieci VATSIM"><i class="glg-on"></i>online</span>`
      + `<span class="glg" title="Rezerwacja stanowiska na dziś (atc-bookings.vatsim.net)"><i class="glg-bk"></i>rezerwacja</span>`
      + `<span class="glg" title="Pozycja aktywna (online albo w symulacji): pasek u góry w kolorze pozycji na mapie"><i class="glg-act"></i>aktywna</span>`
      + `<span class="glg" title="Stanowisko nieznane: brak w pliku .ese i bez częstotliwości"><i class="glg-unk">A</i>nieznane</span>`
      + (firs.length ? `<span class="glg-sep">FIR:</span>${firs.map((f) => `<span class="glg" title="${esc(R.FIR_COLORS[f].name)}"><i style="background:${R.FIR_COLORS[f].c}"></i>${esc(f)}</span>`).join("")}` : "");
  };
  const renderGrid = () => {
    const pg = pages()[page];
    const g = $(".geo-grid");
    renderLegend(pg);
    if (!pg) { g.innerHTML = errs.vacs ? `<p class="error">Brak stron GEO (vacs-data): ${esc(errs.vacs)}</p>` : `<p class="hint">Ładowanie stron GEO…</p>`; return; }
    const cols = Math.ceil(pg.keys.length / pg.rows);
    g.innerHTML = `<div class="geo-tiles" style="--rows:${pg.rows};--cols:${cols}">${pg.keys.map(tileHtml).join("")}</div>`;
  };

  // --- dymek (poza kontenerami, position: fixed)
  const showFloat = (html, e) => { float.innerHTML = html; float.style.display = "block"; moveFloat(e); };
  const moveFloat = (e) => {
    if (!e || float.style.display !== "block") return;
    const w = float.offsetWidth, hh = float.offsetHeight, pad = 14;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 4) x = e.clientX - w - pad;
    if (y + hh > innerHeight - 4) y = Math.max(4, e.clientY - hh - pad);
    float.style.left = Math.max(4, x) + "px";
    float.style.top = y + "px";
  };
  const hideFloat = () => { float.style.display = "none"; };

  // kolejność przejmowania: nazwa, częstotliwość, kto online; note = warstwy, których dotyczy (kilka różnych kolejności)
  const chainHtml = (chain, owner, note = "") => chain.length ? `<div class="gtt-k">Kolejność przejmowania${note ? ` <span>${esc(note)}</span>` : ""}</div><ol class="gtt-chain">${chain.map((c) =>
    `<li class="${c === owner ? "own" : active.has(c) ? "act" : ""}">${c === owner ? `<i style="background:${colors[c]}"></i>` : ""}${esc(displayName(c))}`
    + ` <span class="fq">${esc(freqOf(c))}</span>${R.state.online[c] ? ` <span class="onl">online${R.state.online[c].name ? ": " + esc(R.state.online[c].name) : ""}</span>` : ""}</li>`).join("")}</ol>` : "";
  const srcText = (src) => (src === "own" ? `źródło: ${own?.source_label || "kolejność przejmowania ACC"}`
    : src === "om" ? `źródło: APP/TWR z listy OWNER pliku .ese, potem ACC wg ${own?.source_label || "om.plvacc.pl"}` : "źródło: lista OWNER pliku .ese");
  // co przejmuje pozycja (kafelek APP/TWR/FIS…): obszary spoza sektorów ACC, na których liście jest, z miejscem w kolejności
  // i tym, kto je teraz obsługuje
  const takeover = (cs) => {
    const by = new Map();
    (sectors?.features || []).forEach((f) => {
      const pr = f.properties;
      if (pr.kind === "acc") return;
      const i = sliceChain(pr, own).chain.indexOf(cs);
      if (i < 0) return;
      const g = secName(pr), o = sliceOwner(pr, active, own);
      const e = by.get(g) || by.set(g, { i, owners: new Set() }).get(g);
      e.i = Math.min(e.i, i);
      if (o) e.owners.add(o);
    });
    const list = [...by].sort((a, b) => a[1].i - b[1].i || a[0].localeCompare(b[0]));
    if (!list.length) return "";
    const now = (e) => (e.owners.has(cs) ? `<span class="me">obsługuje</span>`
      : e.owners.size ? `teraz: ${[...e.owners].slice(0, 2).map((o) => esc(displayName(o))).join(", ")}${e.owners.size > 2 ? "…" : ""}`
        : `<span class="muted">nieobsadzony</span>`);
    return `<div class="gtt-k">Przejmuje <span>miejsce w kolejności</span></div><ul class="gtt-take">${list.slice(0, 8).map(([g, e]) =>
      `<li><b>${esc(g)}</b> ${e.i + 1}. · ${now(e)}</li>`).join("")}${list.length > 8 ? `<li class="muted">+${list.length - 8} więcej</li>` : ""}</ul>`;
  };
  // kafelek stanowiska ACC EPWW: sektory, które ma teraz (warstwy L/M/H), i sektory, w których kolejności jest
  const accTake = (cs) => {
    if (!own?.acc_positions?.[cs]) return "";
    const has = accText(accSummary(active, own).by[cs]);
    const letters = Object.keys(own.sectors || {}).sort()
      .filter((s) => VACS_LAYERS.some((ly) => (own.sectors[s][ly] || []).includes(cs)));
    const now = !active.has(cs) ? "" : has ? `<li><span class="me">obsługuje</span> <b>${esc(has)}</b></li>`
      : `<li class="muted">nie ma żadnego sektora: mają je pozycje wyżej w kolejności</li>`;
    return `<div class="gtt-k">Sektory ACC</div><ul class="gtt-take">${now}${letters.length ? `<li>w kolejności sektorów: ${esc(letters.join(", "))}</li>` : ""}</ul>`;
  };
  const onlineLine = (on) => `<div class="gtt-on">ONLINE: ${esc(on.name || "?")} (CID ${esc(on.cid ?? "?")}${RANK[on.rating] ? " · " + RANK[on.rating] : ""})`
    + `${on.callsign ? ` · ${esc(on.callsign)} ${esc(on.frequency || "")}` : ""}${on.logon_time ? ` · od ${hhmm(on.logon_time)}` : ""}</div>`;
  const rangeNote = (cs) => {
    const r = fallback(cs);
    if (!r) return "";
    if (r.kind === "vatspy") return r.exact ? `zasięg wg VATSpy: ${r.ids.join(", ")}` : `zasięg ≈ ${r.ids.join(", ")} (VATSpy, cały FIR – przybliżenie)`;
    if (r.kind === "circle") return `zasięg ≈ okrąg ${r.nm} NM wokół lotniska (przybliżenie)`;
    return "stanowisko naziemne (bez przestrzeni)";
  };
  const tileTip = (k) => {
    if (k.sector) {
      const { letter, layer } = k.sector, L0 = own?.layers?.[layer];
      const chain = own?.sectors?.[letter]?.[layer] || [], o = ownerOfSector(letter, layer);
      return `<div class="gtt-h"><b>Sektor ${esc(letter)} ${layer}</b><span>${esc(L0?.label || "")}</span></div>
        <div class="gtt-own">${o ? `<i style="background:${colors[o]}"></i><b>${esc(displayName(o))}</b> ${esc(freqOf(o))}` : `<span class="muted">nieobsadzony (nikt z kolejności nie jest ${R.state.mode === "sim" ? "w symulacji" : "online"})</span>`}</div>
        ${o && R.state.online[o] ? onlineLine(R.state.online[o]) : ""}${chainHtml(chain, o)}
        ${own?.source_label ? `<div class="gtt-src">źródło: ${esc(own.source_label)}</div>` : ""}
        <div class="gtt-hint">kliknij: pokaż sektor na mapie</div>`;
    }
    const cs = k.callsign, p = P(cs), on = R.state.online[cs], bks = R.state.bookings[cs] || [];
    const fk = R.firKey(cs, p?.fir);
    return `<div class="gtt-h"><b>${esc(displayName(cs))}</b><span>${esc(cs || "")}</span></div>
      <div class="gtt-sub">${esc(tileFreq(k))} · ${esc(p?.name || p?.fir_name || "stanowisko spoza pliku .ese")}</div>
      ${on ? onlineLine(on) : ""}${bks.map((b) => `<div class="gtt-bk">BOOKING${b.active ? " TERAZ" : ""}: ${hhmm(b.start)}–${hhmm(b.end)} · CID ${esc(b.cid)}${b.name ? " " + esc(b.name) : ""}</div>`).join("")}
      ${accTake(cs)}${takeover(cs)}
      ${!p && !(k.frequency) ? `<div class="gtt-src">nieznane stanowisko: brak w pliku .ese i bez częstotliwości</div>` : ""}
      ${freqDiff(k) ? `<div class="gtt-src">VACS podaje ${esc(k.frequency)} – pokazana częstotliwość z pliku .ese</div>` : ""}
      <div class="gtt-src">VACS: ${esc(k.label)}${k.alt ? ` (${esc(k.alt)})` : ""}${fk ? ` · ${esc(R.FIR_COLORS[fk].name)}` : ""}${rangeNote(cs) ? " · " + esc(rangeNote(cs)) : ""}</div>
      <div class="gtt-hint">${R.state.mode === "sim" ? (active.has(cs) ? "w symulacji · kliknij: wyłącz" : "kliknij: dodaj do symulacji")
        : `kliknij: symulacja (zapamiętany zestaw) ${R.state.sim.has(cs) ? "bez tej pozycji" : "z tą pozycją"}`}</div>`;
  };
  const grid = $(".geo-grid");
  grid.addEventListener("mouseover", (e) => {
    const t = e.target.closest(".gt[data-i]");
    const k = t && pages()[page]?.keys[t.dataset.i];
    if (k) showFloat(tileTip(k), e); else hideFloat();
  });
  grid.addEventListener("mousemove", moveFloat);
  grid.addEventListener("mouseleave", hideFloat);
  grid.addEventListener("click", (e) => {
    const t = e.target.closest(".gt[data-i]");
    const k = t && pages()[page]?.keys[t.dataset.i];
    if (!k) return;
    if (k.sector) {
      const same = focus && focus.letter === k.sector.letter && focus.layer === k.sector.layer;
      focus = same ? null : { ...k.sector };
      if (focus && lv.k !== "all") setLevel({ k: focus.layer });
      else render();
    } else if (k.callsign) R.toggle(k.callsign);
    const k2 = pages()[page]?.keys[t.dataset.i];
    const t2 = grid.querySelector(`.gt[data-i="${t.dataset.i}"]`);
    if (k2 && t2) showFloat(tileTip(k2), e);
  });
  $(".geo-pages").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-pg]");
    if (!b) return;
    page = Number(b.dataset.pg);
    save("page", page);
    renderPages();
    renderGrid();
  });

  // --- tryb i symulacja
  $(".geo-mode").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) R.setMode(b.dataset.mode); });
  $(".geo-simbar").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    if (b.dataset.act === "online") {
      await R.refreshNet(true);
      if (!R.state.ok) { renderStatus(); return; }  // bez danych z sieci nie kasujemy symulacji
    }
    // "wszystkie ACC" dokłada stanowiska ACC do zestawu (jak w SEKTORYZACJI), pozostałe pozycje zostają
    R.setSim(b.dataset.act === "clear" ? [] : b.dataset.act === "online" ? R.onlineList()
      : [...R.state.sim, ...Object.keys(own?.acc_positions || {})]);
    R.setMode("sim");
  });
  const renderStatus = () => {
    el.querySelectorAll(".geo-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === R.state.mode));
    el.classList.toggle("sim", R.state.mode === "sim");
    const n = active.size, s = R.state;
    // stan sieci tylko z udanego pobrania (state.ok); po błędzie "brak danych" zamiast starej godziny
    const net = R.netText();
    const txt = s.mode === "sim"
      ? `Symulacja: ${n ? `${n} ${n === 1 ? "pozycja" : n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n > 20) ? "pozycje" : "pozycji"}` : "nic nie wybrano"} · kliknij kafelek: włącz/wyłącz · ${net}`
      : `${net} · kliknij kafelek, żeby przejść do symulacji`;
    const errsAll = [s.err, errs.own && `Kolejność przejmowania: ${errs.own}`, errs.sectors && `Wycinki sektorów: ${errs.sectors}`,
      errs.pos && `Stanowiska: ${errs.pos}`, errs.firs && `Granice VATSpy: ${errs.firs}`].filter(Boolean);
    $(".geo-status").innerHTML = esc(txt) + errsAll.map((x) => ` <span class="error">${esc(x)}</span>`).join("");
  };

  // --- poziom i rodzaje wycinków
  const setLevel = (v) => {
    lv = v;
    save("level", lv);
    render();
  };
  const paintLevel = () => {
    el.querySelectorAll(".geo-lv button").forEach((b) => b.classList.toggle("on", b.dataset.lv === lv.k));
    $(".geo-lv .flbox").classList.toggle("on", lv.k === "fl");
    el.querySelectorAll(".geo-kinds button").forEach((b) => b.classList.toggle("on", !!kinds[b.dataset.kind]));
  };
  // zmiana poziomu przez użytkownika: zaznaczony sektor z innej warstwy znika z mapy, więc zdejmujemy zaznaczenie
  const userLevel = (v) => {
    if (focus && v.k !== "all" && v.k !== focus.layer) focus = null;
    setLevel(v);
  };
  $(".geo-lv").addEventListener("click", (e) => { const b = e.target.closest("button[data-lv]"); if (b) userLevel({ k: b.dataset.lv }); });
  const flInput = $(".geo-fl");
  const takeFl = () => {
    const v = Math.max(0, Math.min(660, Math.round((parseInt(flInput.value, 10) || 0) / 5) * 5));
    flInput.value = v;
    userLevel({ k: "fl", fl: v });
  };
  flInput.addEventListener("change", takeFl);
  flInput.addEventListener("focus", () => { if (lv.k !== "fl") takeFl(); });
  $(".geo-kinds").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-kind]");
    if (!b) return;
    kinds = { ...kinds, [b.dataset.kind]: kinds[b.dataset.kind] ? 0 : 1 };
    save("kinds", kinds);
    render();
  });

  // --- wycinki na mapie
  const styleOf = (it) => {
    const t = theme();
    let st;
    if (it.own) {
      const c = colors[it.own];
      st = { color: c, weight: 1.2, opacity: 0.95, dashArray: null, fillColor: c, fillOpacity: lv.k === "all" ? 0.22 : 0.36 };
    } else {
      st = { color: t.free, weight: it.kind === "acc" ? 1 : 0.7, opacity: 0.8, dashArray: it.kind === "acc" ? "3 3" : "2 3", fillColor: t.free, fillOpacity: 0.04 };
    }
    if (hoverCs) {
      if (it.own === hoverCs) Object.assign(st, { color: t.hi, weight: 2.4, opacity: 1, dashArray: null });
      else st.fillOpacity *= 0.35;
    }
    if (it.focus) Object.assign(st, { color: t.hi, weight: 3, opacity: 1, dashArray: null });
    if (it.hover) Object.assign(st, { color: t.hi, weight: 2.4, opacity: 1, dashArray: null });
    return st;
  };
  const restyle = () => items.forEach((it) => {
    it.poly.setStyle(styleOf(it));
    if (it.focus || (hoverCs && it.own === hoverCs)) it.poly.bringToFront();
  });
  const sliceTip = (it) => {
    const pr = it.f.properties, on = it.own && R.state.online[it.own];
    // ten sam kształt w kilku warstwach ("wszystkie poziomy"): każda część ma swoją kolejność – blok na każdą inną
    const chains = [];
    it.parts.forEach((p) => {
      const key = p.chain.join(" ");
      let c = chains.find((x) => x.key === key);
      if (!c) chains.push(c = { key, chain: p.chain, src: p.src, parts: [] });
      c.parts.push(p);
    });
    const layers = [...new Set(it.parts.map((p) => p.layer).filter(Boolean))];
    const partsText = (ps) => [...new Set(ps.map((p) => p.layer || rangeText(p.lo, p.hi)))].join(", ");
    return `<div class="gtt-h"><b>${esc(secName(pr))}</b><span>${esc(pr.name)}${pr.fir !== "EPWW" ? ` · ${esc(pr.fir)}` : ""}</span></div>
      <div class="gtt-sub">${it.parts.map((p) => rangeText(p.lo, p.hi)).join(", ")}${layers.length ? ` · warstwa ${layers.join(", ")}` : ""}</div>
      <div class="gtt-own">${it.own ? `<i style="background:${colors[it.own]}"></i><b>${esc(displayName(it.own))}</b> ${esc(freqOf(it.own))}`
        : `<span class="muted">nieobsadzony: nikt z kolejności nie jest ${R.state.mode === "sim" ? "w symulacji" : "online"}</span>`}</div>
      ${on ? onlineLine(on) : ""}${chains.map((c) => chainHtml(c.chain, it.own, chains.length > 1 ? partsText(c.parts) : "")).join("")}
      <div class="gtt-src">${[...new Set(chains.map((c) => srcText(c.src)))].map(esc).join("<br>")}</div>`;
  };
  const drawSectors = () => {
    secLayer.clearLayers();
    items = [];
    if (!sectors) return;
    const seen = new Map();
    const all = sectors.features.filter((f) => levelOk(f.properties, lv, own)).map((f) => ({ f, own: sliceOwner(f.properties, active, own) }));
    // aktywna pozycja, której wszystkie przejęte wycinki są w wyłączonych rodzajach (np. FIS przy wyłączonym FIS),
    // i tak je pokazuje – inaczej nie byłoby jej na mapie; sektory ACC wyłączone przyciskiem ACC znikają zawsze
    const seenOwn = new Set(all.filter((x) => x.own && kinds[x.f.properties.kind]).map((x) => x.own));
    const list = all.filter((x) => kinds[x.f.properties.kind] || (x.own && x.f.properties.kind !== "acc" && !seenOwn.has(x.own)));
    list.sort((a, b) => !!a.own - !!b.own || KIND_Z[a.f.properties.kind] - KIND_Z[b.f.properties.kind]);
    list.forEach(({ f, own: o }) => {
      const pr = f.properties;
      const key = `${o || "-"}|${geomKey(f)}`;
      const sc = sliceChain(pr, own);
      const fo = !!focus && pr.kind === "acc" && sc.letter === focus.letter && sc.layer === focus.layer;
      const part = { lo: pr.lower_ft, hi: pr.upper_ft, layer: sc.layer, chain: sc.chain, src: sc.src };
      const dup = seen.get(key);
      // ten sam kształt w kilku warstwach: jeden wielokąt z listą części (zakres wysokości, warstwa, kolejność)
      if (dup) { dup.parts.push(part); dup.focus ||= fo; return; }
      const it = { f, own: o, kind: pr.kind, parts: [part], hover: false, focus: fo };
      seen.set(key, it);
      it.poly = L.geoJSON(f, { style: styleOf(it) }).addTo(secLayer);
      it.poly.on("mouseover", (e) => { it.hover = true; it.poly.setStyle(styleOf(it)).bringToFront(); showFloat(sliceTip(it), e.originalEvent); });
      it.poly.on("mousemove", (e) => moveFloat(e.originalEvent));
      it.poly.on("mouseout", () => { it.hover = false; it.poly.setStyle(styleOf(it)); if (hoverCs || focus) restyle(); hideFloat(); });
      it.poly.on("click", () => { if (it.own) setHover(hoverCs === it.own ? null : it.own); });
      items.push(it);
    });
    items.forEach((it) => it.parts.sort((a, b) => a.lo - b.lo));
    if (focus) items.forEach((it) => { if (it.focus) it.poly.setStyle(styleOf(it)).bringToFront(); });
  };
  // zasięg sąsiadów (VATSpy / okrąg / punkt lotniska) i stanowisk naziemnych
  const drawRanges = () => {
    rangeLayer.clearLayers();
    const byId = firById();
    [...active].forEach((cs) => {
      const r = fallback(cs), c = colors[cs];
      if (!r) return;
      const tip = (txt) => `<div class="gtt-h"><b>${esc(displayName(cs))}</b><span>${esc(freqOf(cs))}</span></div><div class="gtt-sub">${esc(txt)}</div>`;
      // obrys z VATSpy obok własnych wycinków pozycji leży nad nimi: bez myszy, żeby dymki wycinków działały
      const solo = !owned.has(cs);
      const hov = (lyr, txt) => (solo ? lyr.on("mouseover", (e) => showFloat(tip(txt), e.originalEvent)).on("mousemove", (e) => moveFloat(e.originalEvent))
        .on("mouseout", hideFloat) : lyr).addTo(rangeLayer);
      if (r.kind === "point") {
        hov(L.circleMarker([r.lat, r.lon], { pane: "geoRange", radius: 5, color: c, weight: 2, fillColor: c, fillOpacity: 0.9 }),
          "stanowisko naziemne (GND/DEL): bez własnej przestrzeni");
      } else if (r.kind === "circle") {
        hov(L.circle([r.lat, r.lon], { pane: "geoRange", radius: r.nm * 1852, color: c, weight: 2, dashArray: "6 5", fillColor: c, fillOpacity: 0.08 }),
          `zasięg ≈ ${r.nm} NM wokół lotniska – przybliżenie (brak wycinków w pliku .ese i granicy w VATSpy)`);
      } else if (r.kind === "vatspy") {
        r.ids.forEach((id) => {
          const f = byId[id];
          if (!f) return;
          hov(L.geoJSON(f, { pane: "geoRange", interactive: solo, style: { color: c, weight: 2, dashArray: "7 5", fillColor: c, fillOpacity: solo ? (r.exact ? 0.1 : 0.05) : 0 } }),
            `zasięg wg VATSpy: ${id} ${f.properties.name || ""}${r.exact ? "" : " – cały FIR (przybliżenie: brak osobnego sektora)"}; bez podziału pionowego`);
        });
      }
    });
  };
  // etykieta pozycji: w największym przejętym wycinku, w którym nie zasłania etykiety pozycji wyżej w kolejności;
  // bez wycinków – w środku zasięgu (VATSpy, okrąg, lotnisko)
  const drawLabels = () => {
    lblLayer.clearLayers();
    if (map.getSize().x < 40) return;
    const cand = {};
    items.forEach((it) => {
      if (!it.own) return;
      const lp = labelPoint(it.f);
      if (lp) (cand[it.own] ||= []).push(lp);
    });
    const byId = firById();
    const boxes = [];
    const hit = (b) => boxes.some((o) => b.x1 < o.x2 && b.x2 > o.x1 && b.y1 < o.y2 && b.y2 > o.y1);
    [...active].sort(R.byRank).forEach((cs) => {
      const name = displayName(cs), w = name.length * 7 + 22, hh = 18;
      let pts = (cand[cs] || []).sort((a, b) => b.d - a.d).slice(0, 25).map((x) => x.at);
      const r = fallback(cs);
      if (!pts.length && r && (r.kind === "circle" || r.kind === "point")) pts = [[r.lat, r.lon]];
      if (!pts.length && r?.kind === "vatspy" && byId[r.ids[0]]) {
        const at = labelPoint({ ...byId[r.ids[0]], properties: { name: r.ids[0], fir: "vatspy" } })?.at;
        if (at) pts = [at];
      }
      if (!pts.length) return;
      const boxAt = (at, dy = 0) => {
        const c = map.latLngToContainerPoint(at);
        return { at, dy, x1: c.x - w / 2, x2: c.x + w / 2, y1: c.y - hh / 2 + dy, y2: c.y + hh / 2 + dy };
      };
      // najpierw wolne miejsce w kolejnych wycinkach, potem przesunięcie w pionie przy najlepszym
      const tries = [...pts.map((at) => boxAt(at)), ...[1, -1, 2, -2].map((k) => boxAt(pts[0], k * hh))];
      const b = tries.find((x) => !hit(x)) || tries[0];
      boxes.push(b);
      L.marker(b.at, { interactive: false, keyboard: false, icon: L.divIcon({ className: "maplabel geo-maplabel", iconSize: null,
        html: `<div class="geo-lbl${hoverCs === cs ? " hl" : ""}" style="transform:translate(-50%,calc(-50% + ${b.dy}px))"><i style="background:${colors[cs]}"></i>${esc(name)}</div>` }) }).addTo(lblLayer);
    });
  };
  const renderInfo = () => {
    const sep = `<span class="gk-sep">·</span>`;
    let html = `<b>${esc(levelText(lv, own))}</b>`;
    if (focus) {
      const o = ownerOfSector(focus.letter, focus.layer);
      html += `${sep}<span class="gk-f">sektor <b>${esc(focus.letter)} ${focus.layer}</b>: ${o ? `<i class="sw" style="background:${colors[o]}"></i>${esc(displayName(o))} ${esc(freqOf(o))}` : "nieobsadzony"}
        <button class="geo-unfocus" title="Usuń zaznaczenie sektora">✕</button></span>`;
    }
    html += `${sep}<span class="gk"><i class="gk-own"></i>przejęte przez pozycję</span><span class="gk"><i class="gk-free"></i>nieobsadzone</span>`
      + `<span class="gk" title="Stanowisko bez wycinków w pliku .ese: obszar FIR/sektora z VATSpy (bez podziału pionowego); APP/TWR bez danych: okrąg ≈30/10 NM wokół lotniska">`
      + `<i class="gk-rng"></i>zasięg bez wycinków (VATSpy / okrąg ≈30/10 NM)</span>`;
    $(".geo-info").innerHTML = html;
  };
  $(".geo-info").addEventListener("click", (e) => { if (e.target.closest(".geo-unfocus")) { focus = null; render(); } });

  // --- kto co obsługuje
  // "CTA 01, CTA 03" → "CTA 01/03" (tak samo ATZ i TRA)
  const compact = (gs) => {
    const out = [], at = {};
    gs.forEach((g) => {
      const m = /^(CTA|ATZ|TRA) (.+)$/.exec(g);
      if (!m) { out.push(g); return; }
      if (at[m[1]] === undefined) { at[m[1]] = out.length; out.push(g); } else out[at[m[1]]] += "/" + m[2];
    });
    return out;
  };
  const renderWho = () => {
    const list = [...active].sort(R.byRank);
    const { by, free } = accSummary(active, own);
    // własny sektor pozycji (ta sama nazwa) na początku, potem przejęte alfabetycznie
    const groupsOf = (cs) => KIND_ORDER.flatMap((k) => compact([...(grp[cs]?.[k] || [])]
      .sort((a, b) => (b === displayName(cs)) - (a === displayName(cs)) || a.localeCompare(b))));
    $(".geo-whon").textContent = list.length ? `· ${list.length}` : "";
    const rows = list.map((cs) => {
      const on = R.state.online[cs], acc = accText(by[cs]), g = groupsOf(cs);
      const rn = rangeNote(cs);
      const none = acc || g.length || rn ? "" : !sectors || !own ? "brak danych o sektorach (błąd pobierania)" : !P(cs) ? "nieznane stanowisko"
        : listed().has(cs) ? "nic nie przejmuje: wycinki mają pozycje wyżej w kolejności"
          : `brak wycinków w pliku .ese${P(cs).range ? "" : " i granicy w VATSpy"}`;
      return `<div class="gw-row${hoverCs === cs ? " hl" : ""}" data-cs="${esc(cs)}">
        <div class="gw-h"><i class="sw" style="background:${colors[cs]}"></i><b>${esc(displayName(cs))}</b><span class="fq">${esc(freqOf(cs))}</span>
          <span class="who">${on ? esc(on.name || "online") : ""}</span>
          ${R.state.mode === "sim" ? `<button class="gw-x" title="Wyłącz pozycję">✕</button>` : ""}</div>
        <div class="gw-sec">${acc ? `<span class="acc">${esc(acc)}</span>` : ""}${g.slice(0, 10).map((x) => `<span>${esc(x)}</span>`).join("")}${g.length > 10 ? `<span class="rn" title="${esc(g.slice(10).join(", "))}">+${g.length - 10} więcej</span>` : ""}
          ${rn ? `<span class="rn">${esc(rn)}</span>` : ""}${none ? `<span class="rn">${esc(none)}</span>` : ""}</div></div>`;
    }).join("");
    const freeTxt = accText(free);
    $(".geo-wholist").innerHTML = (rows || `<p class="hint">${R.state.mode === "sim" ? "Nic nie wybrano: kliknij kafelek albo pozycję na liście."
      : R.state.ok ? "Nikt z EPWW ani sąsiadów nie jest teraz online." : R.state.tried ? "Brak danych z sieci VATSIM." : "Pobieranie stanu sieci VATSIM…"}</p>`)
      + (own && freeTxt ? `<div class="gw-free"><i class="sw free"></i>nieobsadzone sektory ACC: <b>${esc(freeTxt)}</b></div>` : "")
      + (own ? `<div class="gw-note hint">L/M/H = warstwy ${VACS_LAYERS.map((l) => `${l} ${esc(own.layers?.[l]?.label || "")}`).join(", ")}</div>` : "");
    $(".geo-copy").onclick = () => {
      const txt = [...list.map((cs) => `${displayName(cs)} ${freqOf(cs)} — ${[accText(by[cs]), ...groupsOf(cs)].filter(Boolean).join(", ") || rangeNote(cs) || "—"}`),
        ...(own && freeTxt ? [`nieobsadzone: ${freeTxt}`] : [])].join("\n");
      navigator.clipboard?.writeText(txt).then(() => { $(".geo-copy").textContent = "skopiowano"; setTimeout(() => { $(".geo-copy").textContent = "kopiuj"; }, 1500); })
        .catch(() => { /* brak dostępu do schowka */ });
    };
  };
  const setHover = (cs) => {
    if (cs === hoverCs) return;
    hoverCs = cs;
    el.querySelectorAll(".gw-row").forEach((r) => r.classList.toggle("hl", !!cs && r.dataset.cs === cs));
    el.querySelectorAll(".gt[data-cs]").forEach((t) => t.classList.toggle("hl", !!cs && t.dataset.cs === cs));
    restyle();
    drawLabels();
  };
  const who = $(".geo-wholist");
  who.addEventListener("mouseover", (e) => setHover(e.target.closest(".gw-row")?.dataset.cs || null));
  who.addEventListener("mouseleave", () => setHover(null));
  who.addEventListener("click", (e) => { const x = e.target.closest(".gw-x"); if (x) R.toggle(x.closest(".gw-row").dataset.cs); });

  // --- całość
  // ukryta zakładka (inna zakładka główna): rysujemy dopiero po powrocie (ResizeObserver)
  const render = () => {
    if (!visible || !el.offsetWidth) { dirty = true; return; }
    dirty = false;
    hideFloat();
    compute();
    renderStatus();
    paintLevel();
    renderPages();
    renderGrid();
    drawSectors();
    drawRanges();
    drawLabels();
    renderInfo();
    renderWho();
  };

  const init = async () => {
    // nazwy stanowisk (displayName: etykiety VACS) przed pierwszym rysowaniem; bez nich zostaje posName
    const [v, o, p, s, f] = await Promise.allSettled([vacs || R.loadVacsData(), own || loadVacs(), R.loadPositions(),
      sectors || R.loadSectors(), firs || loadFirs(), loadDisplayNames()]);
    const take = (r, k) => { errs[k] = r.status === "rejected" ? r.reason.message : ""; return r.status === "fulfilled" ? r.value : null; };
    vacs = take(v, "vacs");
    own = take(o, "own");
    const ps = take(p, "pos");
    if (ps) pos = Object.fromEntries(ps.map((x) => [x.callsign, x]));
    sectors = take(s, "sectors");
    if (sectors && !sectors.features.length && sectors.note) errs.sectors = sectors.note;
    const firsNew = !firs && take(f, "firs");
    if (firsNew) { firs = firsNew; drawFirLayer(); }
    if (vacs && (page >= pages().length || fmpPage(pages()[page]))) page = 0;
    if (!fitB && sectors?.features.length) fitB = L.geoJSON(sectors.features.filter((x) => x.properties.fir === "EPWW")).getBounds();
    if (visible && (!fitted || auto)) fit();
    render();
  };
  const unsub = R.on(() => render());
  let unwatch = null, retry = null;
  syncBase();
  init();

  return {
    el,
    show: () => {
      visible = true;
      unwatch ||= R.watch();
      retry ||= setInterval(() => { if (Object.values(errs).some(Boolean) || !vacs || !sectors) init(); }, 60000);
      setTimeout(() => {
        if (!el.isConnected) return;
        fitting = true;
        map.invalidateSize({ animate: false });
        fitting = false;
        syncBase();
        if (!fitted || auto) fit();
        render();
      }, 30);
    },
    hide: () => {
      visible = false;
      hideFloat();
      unwatch?.();
      unwatch = null;
      clearInterval(retry);
      retry = null;
    },
    destroy: () => { unsub(); unwatch?.(); clearInterval(retry); ro.disconnect(); map.remove(); },
  };
}
