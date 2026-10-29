import { api, debounce, esc, h, letterMenu, remember, touchKeyboard } from "../api.js";

const RECAT = {
  A: "Super Heavy", B: "Upper Heavy", C: "Lower Heavy", D: "Upper Medium", E: "Lower Medium", F: "Light",
};
// skrót kategorii RECAT-EU obok litery w kratce ("E|M↓"): J = super, strzałka = górna / dolna część kategorii
const RECAT_SHORT = { A: "J", B: "H↑", C: "H↓", D: "M↑", E: "M↓", F: "L" };
const WTC = { L: "Light", M: "Medium", H: "Heavy", J: "Super" };
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

// --- wartości w kratkach (czysty tekst; escapowanie przy składaniu HTML) ---
// liczba bez zbędnych zer: 27.2, 27.05, 54.1; masa w tonach z jednym miejscem po przecinku
const num = (v) => String(+Number(v).toFixed(2));
const tons = (kg) => String(Math.round(kg / 100) / 10);
const flevel = (ft) => String(Math.round(ft / 100)).padStart(3, "0");
const mach = (m) => String(+Number(m).toFixed(3));
// osiągi z wersji produkcyjnych typu: od–do, gdy wersje się różnią (*_max z serwera), inaczej jedna wartość;
// porównanie po zaokrągleniu, żeby nie było "2–2 t" (MLW 1970 i 2047 kg)
const span = (lo, hi, f) => {
  if (lo == null) return "";
  const a = f(lo), b = hi == null ? a : f(hi);
  return a === b ? a : `${a}–${b}`;
};
const unit = (v, u) => (v ? `${v}${u}` : "");
const pre = (p, v) => (v ? `${p}${v}` : "");

// opis typu słownie: "L2J" -> "landplane, 2 × jet"
export function describe(d) {
  if (!d || d.length < 3) return "";
  return `${KIND[d[0]] || "?"}, ${d[1] === "C" ? "coupled" : `${d[1]} ×`} ${ENGINE[d[2]] || "?"}`;
}
// silniki do kratki ENG: liczba (z bazy albo z opisu typu) i rodzaj; T w opisie śmigłowca i tiltrotora (H2T, T2T)
// to turbina wałowa
export function engines(a) {
  const d = a.description || "";
  const kind = a.engine_type || (d[2] === "T" ? (/^[HT]/.test(d) ? "turboshaft" : "turboprop") : ENGINE[d[2]]);
  const count = a.engine_count ?? (d[1] === "C" ? "coupled" : /^\d$/.test(d[1] || "") ? d[1] : null);
  return [count, kind].filter((x) => x != null && x !== "").join(" ");
}
// kod literowy lotniska (ARC) wg rozpiętości skrzydeł: A < 15 m, B < 24, C < 36, D < 52, E < 65, F < 80;
// bez kodu dla śmigłowców i wiatrakowców (średnica wirnika) i powyżej 80 m
export function arcCode(a) {
  const s = Number(a.wingspan);
  if (a.wingspan == null || !(s > 0) || /^[HG]/.test(a.description || "")) return "";
  return "ABCDEF"[[15, 24, 36, 52, 65, 80].findIndex((m) => s < m)] || "";
}

// Rekord jako kratki: mała etykieta nad dużą wartością, kolor wg kategorii (id = identyfikacja, perf = osiągi,
// wake = masa i turbulencja, dim = wymiary). Puste wartości pomijane. {cat, label, value, title?, key?, cls?}:
// key = kratka wyróżniona (kod ICAO), cls = klasa wartości (kolor kategorii RECAT-EU)
export function boxes(a) {
  const b = (cat, label, value, extra) => ({ cat, label, value, ...extra });
  // śmigłowiec i wiatrakowiec: w polu rozpiętości jest średnica wirnika
  const rotor = /^[HG]/.test(a.description || "");
  return [
    b("id", "ICAO", a.icao, { key: true }),
    b("id", "IATA", a.iata),
    b("id", "DESC", a.description, { title: describe(a.description) }),
    b("perf", "ENG", engines(a)),
    b("perf", "VMO", unit(span(a.vmo_kt, a.vmo_kt_max, num), " kt")),
    b("perf", "MMO", pre("M", span(a.mmo, a.mmo_max, mach))),
    b("perf", "CEILING", pre("FL", span(a.ceiling_ft, a.ceiling_ft_max, flevel))),
    b("wake", "MTOW", a.mtow ? `${tons(a.mtow)} t` : ""),
    b("wake", "MLW", unit(span(a.mlw, a.mlw_max, tons), " t")),
    b("wake", "WTC", a.wtc, { title: WTC[a.wtc] }),
    b("wake", "WTG", a.wtg),
    b("wake", "RECAT", a.recat ? `${a.recat}${RECAT_SHORT[a.recat] ? `|${RECAT_SHORT[a.recat]}` : ""}` : "",
      { title: a.recat && RECAT[a.recat] ? `RECAT-EU ${a.recat} – ${RECAT[a.recat]}` : "", cls: `recat-${a.recat}` }),
    b("dim", rotor ? "ROTOR" : "WINGSPAN", a.wingspan ? `${num(a.wingspan)} m` : ""),
    b("dim", "ARC", arcCode(a)),
    b("dim", "LENGTH", a.length ? `${num(a.length)} m` : ""),
    b("dim", "HEIGHT", a.height ? `${num(a.height)} m` : ""),
  ].filter((x) => x.value != null && x.value !== "");
}
const box = (x) => `<div class="acb ${x.cat}${x.key ? " key" : ""}"${x.title ? ` title="${esc(x.title)}"` : ""}>`
  + `<span>${x.label}</span><b${x.cls ? ` class="${esc(x.cls)}"` : ""}>${esc(x.value)}</b></div>`;

// strona typu w bazie osiągów (details.aspx?ICAO=…) obok strony głównej z config
let PERF = "https://learningzone.eurocontrol.int/ilp/customs/ATCPFDB/default.aspx";
const perfUrl = (icao) => PERF.replace(/default\.aspx.*$/i, `details.aspx?ICAO=${encodeURIComponent(icao)}`);

// Rekord: nazwa typu w linii tytułu (z odnośnikiem do osiągów), pod nią kratki z wartościami
export function record(a, i) {
  return `<div class="ac-rec" data-i="${i}">
    <div class="ac-name"><span>${esc(`${a.manufacturer || ""} ${a.model || ""}`.trim() || a.icao)}</span>
      <a class="ac-perf" href="${esc(perfUrl(a.icao))}" target="_blank" rel="noopener">Performance ↗</a></div>
    <div class="ac-boxes">${boxes(a).map(box).join("")}</div>
  </div>`;
}

// Rozwinięty rekord (klik): zdjęcie, opis typu i kategorii RECAT-EU słownie, odnośniki do kolejnych zdjęć
// i do wyszukiwarki bazy osiągów (dla typów, których strony osiągów nie ma)
export function detail(a) {
  const q = encodeURIComponent(searchName(a));
  const lines = [a.description && `${a.description} – ${describe(a.description)}`,
    a.recat && RECAT[a.recat] && `RECAT-EU ${a.recat} – ${RECAT[a.recat]}`].filter(Boolean);
  return `<div class="ac-detail">
    <div class="photo-box"><span class="hint">Loading photo…</span></div>
    <div class="ac-info">${lines.map((l) => `<div>${esc(l)}</div>`).join("")}
      <div class="ac-links"><a href="https://www.jetphotos.com/photo/keyword/${q}" target="_blank" rel="noopener">More photos ↗</a>
        <a href="https://www.google.com/search?tbm=isch&q=${q}" target="_blank" rel="noopener">Image search ↗</a>
        <a href="${esc(PERF)}" target="_blank" rel="noopener">Performance search ↗</a></div></div>
  </div>`;
}

// Podpis pod zdjęciem: odnośnik do strony zdjęcia (autor i licencja) nazwany wg funkcji, bez nazwy serwisu;
// sam tekst podpisu tylko przy własnym zdjęciu bez strony (np. autor)
export function photoCredit(p) {
  if (p.page) return `<a href="${esc(p.page)}" target="_blank" rel="noopener">Photo page ↗</a>`;
  return p.credit ? esc(p.credit) : "";
}

export default {
  mount(root, ctx) {
    PERF = ctx.config.links?.performance_db || PERF;
    let prefix = "";
    // aktywny przycisk producenta; litera albo ponowny klik wraca do zwykłego widoku
    let maker = "";
    const letters = letterMenu(root, (l) => { prefix = l; setMaker(""); load(); });
    const pane = h(`<div class="pane ac-pane">
      <nav class="ac-makers">${MAKERS.map(([k, l]) => `<button class="gbtn" data-m="${k}" title="All ${l} types">${l}</button>`).join("")}</nav>
      <div class="toolbar">
        <input type="search" class="q" placeholder="ICAO type, model, manufacturer…" size="32">
        <select class="wtc"><option value="">WTC: all</option><option>L</option><option>M</option><option>H</option><option>J</option></select>
        <select class="recat"><option value="">RECAT-EU: all</option>${Object.entries(RECAT).map(([k, v]) => `<option value="${k}">${k} – ${v}</option>`).join("")}</select>
        <span class="hint count"></span>
      </div>
      <div class="ac-list"></div>
    </div>`);
    root.append(pane);
    // 0.13.1: klawiatura dotykowa (KEYBOARD pod ALL) zawsze ostatnia w panelu, pod przewijaną listą
    const kbd = touchKeyboard(pane.querySelector(".q"), letters.kbd);
    pane.append(kbd.el);
    const $ = (s) => pane.querySelector(s);
    let rows = [];
    let seq = 0;
    let current = null;

    // przyciski producentów: aktywny podświetlony, w podmenu liter wtedy żadna litera nie jest zaznaczona
    const setMaker = (m) => {
      maker = m;
      pane.querySelectorAll(".ac-makers button").forEach((b) => b.classList.toggle("active", b.dataset.m === m));
      if (m) root.querySelectorAll(".submenu.letters button[data-l].active").forEach((b) => b.classList.remove("active"));
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
      // starsza odpowiedź przyszła po nowszej
      if (my !== seq) return;
      const [, label, primary] = MAKERS.find(([k]) => k === maker) || [];
      const groups = label ? makerGroups(data, primary) : [];
      rows = label ? groups.flatMap(([, list]) => list) : data;
      current = null;
      $(".count").textContent = `${label ? label + ": " : ""}${types(rows.length)}${groups.length > 1 ? ` in ${groups.length} groups` : ""}`
        + (rows.length === 500 ? " (first 500 shown)" : "") + (rows.length ? " · click a type for its photo" : "");
      let i = 0;
      $(".ac-list").innerHTML = !rows.length ? `<p class="hint ac-empty">No${label ? ` ${label}` : ""} types for these filters.</p>`
        : !label ? rows.map(record).join("")
          : groups.map(([name, list]) => `<div class="ac-group"><div class="ac-gh">${esc(name)}<span>${types(list.length)}</span></div>
            ${list.map((a) => record(a, i++)).join("")}</div>`).join("");
    };

    // rozwinięty rekord przy dolnej krawędzi listy przewijany do widoku (najmniejszy ruch)
    const reveal = (rec) => rec.scrollIntoView({ block: "nearest" });
    // zdjęcie w rozwiniętym rekordzie; odpowiedź po zwinięciu albo po wyborze innego typu jest pomijana
    const photo = (rec, a) => {
      const pb = rec.querySelector(".photo-box");
      api(`/api/aircraft/${a.id}/photo`).then((p) => {
        if (current !== a) return;
        const credit = photoCredit(p);
        pb.innerHTML = `<img src="${esc(p.url)}" alt="${esc(searchName(a))}">${credit ? `<div class="hint">${credit}</div>` : ""}`;
        // zdjęcie wydłuża rekord dopiero po wczytaniu
        pb.querySelector("img").addEventListener("load", () => { if (current === a) reveal(rec); }, { once: true });
      }).catch((e) => {
        if (current !== a) return;
        pb.classList.add("none");
        pb.innerHTML = `<p class="hint">${esc(e.message)}</p>`;
      });
    };

    // klik w rekord rozwija go (zdjęcie i opis), ponowny klik zwija; odnośniki i treść rozwinięcia bez zmian
    $(".ac-list").addEventListener("click", (e) => {
      if (e.target.closest("a, .ac-detail")) return;
      const rec = e.target.closest(".ac-rec[data-i]");
      if (!rec) return;
      const was = rec.classList.contains("selected");
      pane.querySelectorAll(".ac-rec.selected").forEach((x) => { x.classList.remove("selected"); x.querySelector(".ac-detail")?.remove(); });
      current = null;
      if (was) return;
      rec.classList.add("selected");
      current = rows[rec.dataset.i];
      rec.insertAdjacentHTML("beforeend", detail(current));
      reveal(rec);
      photo(rec, current);
    });
    pane.querySelector(".ac-makers").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-m]");
      if (!b) return;
      // ponowny klik: zwykły widok (wszystkie); nowy producent: wszystkie jego typy, więc bez tekstu wyszukiwania
      if (b.dataset.m === maker) { prefix = ""; setMaker(""); letters.set(""); } else { $(".q").value = ""; setMaker(b.dataset.m); }
      $(".ac-list").scrollTop = 0;
      load();
      // krok do cofnięcia (←), jak litery
      remember("aircraft", maker ? "maker/" + maker : "");
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
      kbd.sync();
      $(".q").focus();
    } };
  },
};
