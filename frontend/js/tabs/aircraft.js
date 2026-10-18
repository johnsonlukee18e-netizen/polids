import { api, debounce, esc, fmt, h, letterMenu, remember } from "../api.js";

const RECAT = {
  A: "Super Heavy", B: "Upper Heavy", C: "Lower Heavy", D: "Upper Medium", E: "Lower Medium", F: "Light",
};
// opis typu wg ICAO Doc 8643 (np. L2J): rodzaj statku, liczba silników (C = sprzężone), rodzaj silników
const KIND = { L: "landplane", S: "seaplane", A: "amphibian", G: "gyrocopter", H: "helicopter", T: "tiltrotor" };
const ENGINE = { J: "jet", T: "turboprop/turboshaft", P: "piston", E: "electric", R: "rocket" };
// Przyciski producentów u góry: [klucz ?maker= w backendzie (tam dopasowanie różnych zapisów nazwy), etykieta,
// główna nazwa producenta, której grupa idzie na początek listy]
const MAKERS = [["airbus", "AIRBUS", "airbus"], ["boeing", "BOEING", "boeing"], ["embraer", "EMBRAER", "embraer"],
  ["mcdonnell", "MCDONNELL", "mcdonnell douglas"], ["atr", "ATR", "atr"], ["cessna", "CESSNA", "cessna"]];
const types = (n) => `${n} ${n === 1 ? "type" : "types"}`;
const norm = (s) => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

// Widok producenta: grupy wg nazwy producenta w bazie (np. Airbus, Airbus Helicopters), główna nazwa pierwsza,
// dalej od największej grupy; w grupie kolejność z serwera (wg kodu ICAO)
function makerGroups(list, primary) {
  const by = new Map();
  list.forEach((a) => {
    const k = a.manufacturer || "–";
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(a);
  });
  return [...by.entries()].sort(([a, x], [b, y]) =>
    (norm(b) === primary) - (norm(a) === primary) || y.length - x.length || a.localeCompare(b));
}
// hasło do wyszukiwarek zdjęć jak photo_query w services/photos.py: nazwa ICAO wylicza wersje i nazwy wojskowe,
// "A-300(B4/C4/F4)-600" -> "A-300-600", "737-800, BBJ2" -> "737-800"
const searchName = (a) => `${a.manufacturer || ""} ${(a.model || a.icao).split(",")[0].replace(/\([^()]*\)/g, "")
  .split("/")[0].replace(/\s+/g, " ").trim()}`.trim();
// osiągi z wersji produkcyjnych typu: od–do, gdy wersje się różnią (*_max z serwera), inaczej jedna wartość
const range = (lo, hi, digits = 0, unit = "") => (hi == null || hi === lo ? fmt(lo, digits, unit)
  : `${fmt(lo, digits)}–${fmt(hi, digits, unit)}`);
const mach = (lo, hi) => (lo == null ? "–" : `M${+Number(lo).toFixed(3)}${hi == null || hi === lo ? "" : `–${+Number(hi).toFixed(3)}`}`);
const describe = (d) => (!d ? "–"
  : `${esc(d)} – ${KIND[d[0]] || "?"}, ${d[1] === "C" ? "coupled" : `${esc(d[1])} ×`} ${ENGINE[d[2]] || "?"}`);
function engines(a) {
  const kind = a.engine_type || ENGINE[a.description?.[2]];
  const count = a.engine_count ?? (a.description?.[1] === "C" ? "coupled" : null);
  if (count == null && !kind) return "–";
  return `${esc(count ?? "–")}${count === "coupled" ? "" : " ×"} ${esc(kind || "–")}`;
}
// skąd dane: plik ICAO, osiągi spoza niego z aircraft-database.com (zakresy z wersji produkcyjnych typu)
function sources(a) {
  const perf = [a.engine_type && "engine type", a.mlw != null && "MLW", a.ceiling_ft != null && "ceiling",
    (a.vmo_kt != null || a.mmo != null) && "Vmo/Mmo"].filter(Boolean);
  const ranged = ["mlw_max", "ceiling_ft_max", "vmo_kt_max", "mmo_max"].some((k) => a[k] != null);
  return "Source: ICAO_Aircraft.json (ICAO Doc 8643)"
    + (perf.length ? `; ${perf.join(", ")}: aircraft-database.com` : "")
    + (ranged ? ". Ranges span the type's production variants." : ".");
}
// EUROCONTROL Aircraft Performance Database: strona typu (details.aspx?ICAO=…) obok strony głównej z config
let PERF = "https://learningzone.eurocontrol.int/ilp/customs/ATCPFDB/default.aspx";
const perfUrl = (icao) => PERF.replace(/default\.aspx.*$/i, `details.aspx?ICAO=${encodeURIComponent(icao)}`);

// Rekord w dwóch liniach: kod ICAO duży po lewej, reszta jednolitą czcionką (jeden rekord na typ ICAO)
function record(a, i) {
  return `<div class="ac-rec" data-i="${i}">
    <div class="ac-icao">${esc(a.icao)}</div>
    <div class="ac-l1">${esc(a.manufacturer || "")} ${esc(a.model)}
      <a class="perf" href="${esc(perfUrl(a.icao))}" target="_blank" rel="noopener" title="EUROCONTROL Aircraft Performance Database">performance ↗</a></div>
    <div class="ac-l2">${esc(a.description || "–")} · WTC <b>${esc(a.wtc || "–")}</b> · RECAT-EU <b class="recat-${esc(a.recat)}">${esc(a.recat || "–")}</b>
      · span ${fmt(a.wingspan, 1, " m")} · len ${fmt(a.length, 1, " m")} · hgt ${fmt(a.height, 1, " m")} · MTOW ${a.mtow ? Math.round(a.mtow / 100) / 10 + " t" : "–"}</div>
  </div>`;
}

export default {
  mount(root, ctx) {
    PERF = ctx.config.links?.performance_db || PERF;
    let prefix = "";
    let maker = ""; // aktywny przycisk producenta; litera albo ponowny klik wraca do zwykłego widoku
    const letters = letterMenu(root, (l) => { prefix = l; setMaker(""); load(); });
    const pane = h(`<div class="pane ac-pane">
      <nav class="ac-makers">${MAKERS.map(([k, l]) => `<button class="gbtn" data-m="${k}" title="All ${l} types">${l}</button>`).join("")}</nav>
      <div class="split">
      <div class="list">
        <div class="toolbar">
          <input type="search" class="q" placeholder="ICAO type, model, manufacturer…" size="32">
          <select class="wtc"><option value="">WTC: all</option><option>L</option><option>M</option><option>H</option><option>J</option></select>
          <select class="recat"><option value="">RECAT-EU: all</option>${Object.entries(RECAT).map(([k, v]) => `<option value="${k}">${k} – ${v}</option>`).join("")}</select>
          <span class="hint count"></span>
        </div>
        <div class="ac-list"></div>
      </div>
      <div class="detail"><div class="card"><p class="hint">Select a type from the list to show its details and photo.</p></div></div>
    </div></div>`);
    root.append(pane);
    const $ = (s) => pane.querySelector(s);
    let rows = [];
    let seq = 0;

    // przyciski producentów: aktywny podświetlony, w podmenu liter wtedy żadna litera nie jest zaznaczona
    const setMaker = (m) => {
      maker = m;
      pane.querySelectorAll(".ac-makers button").forEach((b) => b.classList.toggle("active", b.dataset.m === m));
      if (m) root.querySelectorAll(".submenu.letters button.active").forEach((b) => b.classList.remove("active"));
    };
    const load = async () => {
      const qs = new URLSearchParams({ q: $(".q").value.trim(), prefix: maker ? "" : prefix, maker, wtc: $(".wtc").value,
        recat: $(".recat").value, limit: 500 });
      const my = ++seq;
      let data;
      try {
        data = await api(`/api/aircraft?${qs}`);
      } catch (e) {
        if (my !== seq) return;
        $(".count").textContent = "";
        $(".ac-list").innerHTML = `<p class="error">Could not load aircraft types: ${esc(e.message)}</p>`;
        return;
      }
      if (my !== seq) return; // starsza odpowiedź przyszła po nowszej
      const [, label, primary] = MAKERS.find(([k]) => k === maker) || [];
      const groups = label ? makerGroups(data, primary) : [];
      rows = label ? groups.flatMap(([, list]) => list) : data;
      $(".count").textContent = `${label ? label + ": " : ""}${types(rows.length)}${groups.length > 1 ? ` in ${groups.length} groups` : ""}`
        + (rows.length === 500 ? " (first 500 shown)" : "");
      let i = 0;
      $(".ac-list").innerHTML = !rows.length ? `<p class="hint ac-empty">No${label ? ` ${label}` : ""} types for these filters.</p>`
        : !label ? rows.map(record).join("")
          : groups.map(([name, list]) => `<div class="ac-group"><div class="ac-gh">${esc(name)}<span>${types(list.length)}</span></div>
            ${list.map((a) => record(a, i++)).join("")}</div>`).join("");
    };

    const show = (a) => {
      $(".detail").innerHTML = `<div class="card">
        <h3 class="ac-title"><span class="ac-icao" style="font-size:26px">${esc(a.icao)}</span> ${esc(a.manufacturer)} ${esc(a.model)}</h3>
        <div class="perf-links"><a class="btn" href="${esc(perfUrl(a.icao))}" target="_blank" rel="noopener">EUROCONTROL Aircraft Performance: ${esc(a.icao)} ↗</a>
          <a class="hint" href="${esc(PERF)}" target="_blank" rel="noopener">database search ↗</a></div>
        <div class="photo-box"><span class="hint">Loading photo…</span></div>
        <dl class="props">
          <dt>Description</dt><dd>${describe(a.description)}</dd>
          <dt>WTC (ICAO)</dt><dd>${esc(a.wtc || "–")}</dd>
          <dt>WTG (ICAO)</dt><dd>${esc(a.wtg || "–")}</dd>
          <dt>RECAT-EU</dt><dd class="recat-${esc(a.recat)}">${esc(a.recat || "–")} ${a.recat ? "– " + RECAT[a.recat] : ""}</dd>
          <dt>Wingspan</dt><dd>${fmt(a.wingspan, 2, " m")}</dd>
          <dt>Length</dt><dd>${fmt(a.length, 2, " m")}</dd>
          <dt>Height</dt><dd>${fmt(a.height, 2, " m")}</dd>
          <dt>MTOW / MLW</dt><dd>${fmt(a.mtow, 0, " kg")} / ${range(a.mlw, a.mlw_max, 0, " kg")}</dd>
          <dt>Engines</dt><dd>${engines(a)}</dd>
          <dt>Ceiling</dt><dd>${range(a.ceiling_ft, a.ceiling_ft_max, 0, " ft")}</dd>
          <dt>Vmo / Mmo</dt><dd>${range(a.vmo_kt, a.vmo_kt_max, 0, " kt")} / ${mach(a.mmo, a.mmo_max)}</dd>
          <dt>IATA</dt><dd>${esc(a.iata || "–")}</dd>
        </dl>
        <p class="hint">${esc(sources(a))}</p></div>`;
      const box = $(".photo-box");
      const links = `<a href="https://www.jetphotos.com/photo/keyword/${encodeURIComponent(searchName(a))}" target="_blank" rel="noopener">JetPhotos ↗</a> ·
        <a href="https://www.google.com/search?tbm=isch&q=${encodeURIComponent(searchName(a))}" target="_blank" rel="noopener">Google Images ↗</a>`;
      api(`/api/aircraft/${a.id}/photo`).then((p) => {
        if (current !== a) return;
        box.innerHTML = `<img src="${esc(p.url)}" alt="${esc(searchName(a))}"><div class="hint">${p.page ? `<a href="${esc(p.page)}" target="_blank" rel="noopener">${esc(p.credit)}</a>` : esc(p.credit)} · ${links}</div>`;
      }).catch((e) => {
        if (current !== a) return;
        box.innerHTML = `<p class="hint">${esc(e.message)}. To use your own photo, put it in <span class="mono">data/photos/${esc(a.icao)}.jpg</span>. ${links}</p>`;
      });
    };
    let current = null;

    $(".ac-list").addEventListener("click", (e) => {
      const rec = e.target.closest(".ac-rec[data-i]");
      if (!rec) return;
      pane.querySelectorAll(".ac-rec.selected").forEach((x) => x.classList.remove("selected"));
      rec.classList.add("selected");
      current = rows[rec.dataset.i];
      show(current);
    });
    pane.querySelector(".ac-makers").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-m]");
      if (!b) return;
      // ponowny klik: zwykły widok (wszystkie); nowy producent: wszystkie jego typy, więc bez tekstu wyszukiwania
      if (b.dataset.m === maker) { prefix = ""; setMaker(""); letters.set(""); } else { $(".q").value = ""; setMaker(b.dataset.m); }
      $(".list").scrollTop = 0;
      load();
      remember("aircraft", maker ? "maker/" + maker : "");   // krok do cofnięcia (←), jak litery
    });
    $(".q").addEventListener("input", debounce(load));
    $(".wtc").addEventListener("change", load);
    $(".recat").addEventListener("change", load);
    load();
    // arg z adresu (← i Wstecz): litera "A"–"Z", "" = wszystkie, "maker/airbus" = producent, inny tekst = szukany typ
    // (np. #aircraft/B738); przycisk menu (arg undefined) zostawia bieżący widok
    return { activate: (arg) => {
      const mk = arg?.startsWith("maker/") ? arg.slice(6) : null;
      if (arg === undefined) { /* bez zmian */ } else if (/^[A-Z]?$/.test(arg)) {
        if (arg !== prefix || maker) { prefix = arg; setMaker(""); letters.set(arg); load(); }
      } else if (mk && MAKERS.some(([k]) => k === mk)) {
        if (mk !== maker) { $(".q").value = ""; setMaker(mk); load(); }
      } else { $(".q").value = arg; prefix = ""; setMaker(""); letters.set(""); load(); }
      $(".q").focus();
    } };
  },
};
