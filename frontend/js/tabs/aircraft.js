import { api, debounce, esc, h, letterMenu, remember, touchKeyboard } from "../api.js";

const RECAT = {
  A: "Super Heavy", B: "Upper Heavy", C: "Lower Heavy", D: "Upper Medium", E: "Lower Medium", F: "Light",
};
// skrót kategorii RECAT-EU obok litery ("E|M↓"): J = super, strzałka = górna / dolna część kategorii
const RECAT_SHORT = { A: "J", B: "H\u2191", C: "H\u2193", D: "M\u2191", E: "M\u2193", F: "L" };
const WTC = { L: "Light", M: "Medium", H: "Heavy", J: "Super" };
// rodzaj silników z opisu typu wg ICAO Doc 8643 (trzecia litera, np. L2J): do dymku kolumny silników
const ENGINE = { J: "jet", T: "turboprop/turboshaft", P: "piston", E: "electric", R: "rocket" };
// 0.14.0 (issue #28): rodzaj silników w kolumnie listy ("2 Jet"), kategoria ICAO z opisu typu; T śmigłowca
// i tiltrotora to turbina wałowa (Turboshaft, niżej w engineLabel)
const ENGINE_KIND = { J: "Jet", T: "Turboprop", P: "Piston", E: "Electric", R: "Rocket" };
// engine_type z bazy (typ bez opisu ICAO), także "turbojet/turbofan": kategoria wg pierwszego rodzaju
const ENGINE_TYPE = { turbofan: "Jet", turbojet: "Jet", jet: "Jet", turboprop: "Turboprop", propfan: "Turboprop",
  turboshaft: "Turboshaft", piston: "Piston", electric: "Electric", rocket: "Rocket" };
// brak wartości w kratkach rozwinięcia (półpauza)
const NONE = "\u2013";
// Przyciski producentów u góry (0.13.1, issue #25): [klucz ?maker= w backendzie (tam dopasowanie różnych zapisów
// nazwy), etykieta, dymek, kolejność grup w widoku producenta (nazwy producenta w bazie małymi literami; grupy spoza
// listy na końcu, od największej)]. GA w kolejności z issue: Pilatus, Diamond, Cessna, Piper, AT3 (Aero), Robinson,
// Bell, Tecnam
export const MAKERS = [
  ["airbus", "AIRBUS", "All Airbus types", ["airbus"]],
  ["boeing", "BOEING", "All Boeing types", ["boeing"]],
  ["bombardier", "BOMBARDIER", "Bombardier, Canadair, Learjet and Dash 8 types",
    ["bombardier", "canadair", "learjet", "gates learjet", "de havilland canada"]],
  ["embraer", "EMBRAER", "All Embraer types", ["embraer"]],
  ["ga", "GA", "General aviation: Pilatus, Diamond, Cessna, Piper, Aero AT-3, Robinson, Bell, Tecnam",
    ["pilatus", "diamond", "cessna", "piper", "aero", "robinson", "bell", "tecnam"]],
];
// kolumny listy (issue #25): kod ICAO, producent, pełna nazwa, silniki (0.14.0, issue #28: liczba i rodzaj),
// WTC (ICAO), RECAT-EU
export const COLUMNS = [["icao", "ICAO", ""], ["mk", "Manufacturer", ""], ["name", "Name", ""],
  ["eng", "Engines", "Number and type of engines"], ["wtc", "WTC", "ICAO wake turbulence category"],
  ["recat", "RECAT", "RECAT-EU wake turbulence category"]];
// rekordów na liście: ALL ma więcej typów (2821), wtedy dopisek "first … shown"
const LIMIT = 1000;
const types = (n) => `${n} ${n === 1 ? "type" : "types"}`;
const norm = (s) => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

// Widok producenta: grupy wg nazwy producenta w bazie (np. Airbus, Airbus Helicopters) w kolejności order (MAKERS),
// pozostałe za nimi od największej grupy, dalej wg nazwy; w grupie kolejność z serwera (wg kodu ICAO)
export function makerGroups(list, order = []) {
  const by = new Map();
  list.forEach((a) => {
    const k = a.manufacturer || NONE;
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(a);
  });
  const rank = (name) => { const i = order.indexOf(norm(name)); return i < 0 ? order.length : i; };
  return [...by.entries()].sort(([a, x], [b, y]) => rank(a) - rank(b) || y.length - x.length || a.localeCompare(b));
}
// nazwa typu jak photo_query w services/photos.py (opis zdjęcia, alt): nazwa ICAO wylicza wersje i nazwy wojskowe,
// "A-300(B4/C4/F4)-600" -> "A300-600" (0.13.3: Airbus bez łącznika po A), "737-800, BBJ2" -> "737-800"
const searchName = (a) => {
  let name = (a.model || a.icao).replace(/\([^()]*\)/g, "").split(",")[0].split("/")[0].replace(/\s+/g, " ").trim();
  if ((a.manufacturer || "").trim().toUpperCase() === "AIRBUS") name = name.replace(/^A-(?=\d)/, "A");
  return `${a.manufacturer || ""} ${name}`.trim();
};

// --- wartości (czysty tekst; escapowanie przy składaniu HTML) ---
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
  return a === b ? a : `${a}\u2013${b}`;
};
const unit = (v, u) => (v ? `${v}${u}` : "");
const pre = (p, v) => (v ? `${p}${v}` : "");

// silniki słownie z bazy (dymek kolumny silników, gdy mówi więcej niż kolumna, np. "2 turbofan" przy "2 Jet"):
// liczba (z bazy albo z opisu typu) i rodzaj; T w opisie śmigłowca i tiltrotora (H2T, T2T) to turbina wałowa
export function engines(a) {
  const d = a.description || "";
  const kind = a.engine_type || (d[2] === "T" ? (/^[HT]/.test(d) ? "turboshaft" : "turboprop") : ENGINE[d[2]]);
  const count = a.engine_count ?? (d[1] === "C" ? "coupled" : /^\d$/.test(d[1] || "") ? d[1] : null);
  return [count, kind].filter((x) => x != null && x !== "").join(" ");
}
// 0.14.0 (issue #28): kolumna silników z liczbą i rodzajem, np. "2 Jet", "4 Turboprop", "1 Piston", "2 Turboshaft"
// (śmigłowiec). Liczba z bazy albo z opisu typu, sprzężone bez liczby w bazie (LCT) jako "Coupled"; rodzaj
// z opisu typu, bez opisu z engine_type z bazy; nieznany rodzaj: sama liczba, nic nie wiadomo: pusto
export function engineLabel(a) {
  const d = a.description || "";
  const count = a.engine_count ?? (d[1] === "C" ? "Coupled" : /^\d$/.test(d[1] || "") ? d[1] : null);
  let kind = ENGINE_KIND[d[2]] || ENGINE_TYPE[String(a.engine_type || "").toLowerCase().split("/")[0].trim()] || "";
  if (d[2] === "T" && /^[HT]/.test(d)) kind = "Turboshaft";
  return [count, kind].filter((x) => x != null && x !== "").join(" ");
}
// kod literowy lotniska (ARC) wg rozpiętości skrzydeł: A < 15 m, B < 24, C < 36, D < 52, E < 65, F < 80;
// bez kodu dla śmigłowców i wiatrakowców (średnica wirnika) i powyżej 80 m
export function arcCode(a) {
  const s = Number(a.wingspan);
  if (a.wingspan == null || !(s > 0) || /^[HG]/.test(a.description || "")) return "";
  return "ABCDEF"[[15, 24, 36, 52, 65, 80].findIndex((m) => s < m)] || "";
}

// Wiersz listy (domyślny widok, issue #25): sześć kolumn w kolejności COLUMNS. {key, value, title?, cls?}:
// silniki z liczbą i rodzajem (0.14.0, issue #28, engineLabel; pusto dla balonu, szybowca, ZZZZ), w dymku rodzaj
// silników z bazy, gdy mówi więcej (np. turbofan); WTC z nazwą kategorii w dymku; RECAT-EU z kategorią słownie
// w dymku, cls = kolor kategorii
export function cells(a) {
  const eng = engineLabel(a);
  const more = engines(a);
  const recat = a.recat && RECAT[a.recat];
  return [
    { key: "icao", value: a.icao || "" },
    { key: "mk", value: a.manufacturer || "" },
    { key: "name", value: a.model || "" },
    { key: "eng", value: eng, title: more.toLowerCase() !== eng.toLowerCase() ? more : "" },
    { key: "wtc", value: a.wtc || "", title: WTC[a.wtc] || "" },
    { key: "recat", value: recat ? `${a.recat}|${RECAT_SHORT[a.recat]}` : a.recat || "",
      title: recat ? `RECAT-EU ${a.recat} \u2013 ${RECAT[a.recat]}` : "", cls: a.recat ? `recat-${a.recat}` : "" },
  ];
}
export function record(a, i) {
  return `<tr class="ac-rec" data-i="${i}">${cells(a).map((c) => `<td class="${c.key}${c.cls ? ` ${esc(c.cls)}` : ""}"`
    + `${c.title ? ` title="${esc(c.title)}"` : ""}>${esc(c.value)}</td>`).join("")}</tr>`;
}
export const tableHead = () => `<thead><tr>${COLUMNS.map(([k, l, t]) =>
  `<th class="${k}"${t ? ` title="${t}"` : ""}>${l}</th>`).join("")}</tr></thead>`;

// Kratki rozwinięcia: mała etykieta nad dużą wartością. 0.14.0 (issue #28): trzy linijki po trzy kratki, zawsze
// w tej kolejności i zawsze widoczne (brak = półpauza, none): 1) rozpiętość, ARC, długość (bez wysokości),
// 2) MTOW, MLW, WTC, 3) VMO, MMO, pułap. Kolor linijki wg kategorii (dim = wymiary, wake = masa i turbulencja,
// perf = osiągi). Pozostałe dane (wysokość, IATA, opis typu, WTG) nie są pokazywane, ale zostają w bazie i w API.
// [kategoria, [{cat, label, value, title?, none?} x 3]] x 3
export function lines(a) {
  // linijka: kategoria i kratki [etykieta, wartość, dymek?]
  const line = (cat, ...row) => [cat, row.map(([label, value, title]) => ({ cat, label, value: value || NONE,
    ...(title ? { title } : {}), ...(value ? {} : { none: true }) }))];
  // śmigłowiec i wiatrakowiec: w polu rozpiętości jest średnica wirnika (bez ARC)
  const rotor = /^[HG]/.test(a.description || "");
  return [
    line("dim", [rotor ? "ROTOR" : "WINGSPAN", a.wingspan ? `${num(a.wingspan)} m` : "", rotor ? "Rotor diameter" : ""],
      ["ARC", arcCode(a), "Aerodrome reference code (wingspan)"],
      ["LENGTH", a.length ? `${num(a.length)} m` : ""]),
    line("wake", ["MTOW", a.mtow ? `${tons(a.mtow)} t` : ""],
      ["MLW", unit(span(a.mlw, a.mlw_max, tons), " t")],
      ["WTC", a.wtc || "", WTC[a.wtc]]),
    line("perf", ["VMO", unit(span(a.vmo_kt, a.vmo_kt_max, num), " kt")],
      ["MMO", pre("M", span(a.mmo, a.mmo_max, mach))],
      ["CEILING", pre("FL", span(a.ceiling_ft, a.ceiling_ft_max, flevel))]),
  ];
}
const box = (x) => `<div class="acb ${x.cat}${x.none ? " none" : ""}"${x.title ? ` title="${esc(x.title)}"` : ""}>`
  + `<span class="lbl">${x.label}</span><span class="val">${esc(x.value)}</span></div>`;

// strona typu w bazie osiągów (details.aspx?ICAO=…) obok strony głównej z config
let PERF = "https://learningzone.eurocontrol.int/ilp/customs/ATCPFDB/default.aspx";
const perfUrl = (icao) => PERF.replace(/default\.aspx.*$/i, `details.aspx?ICAO=${encodeURIComponent(icao)}`);
const link = (href, text, cls) => `<a${cls ? ` class="${cls}"` : ""} href="${esc(href)}" target="_blank" rel="noopener">${text} \u2197</a>`;

// Rozwinięcie (klik w wiersz, issue #25 "dodatkowy widok"): wiersz pod klikniętym na całą szerokość tabeli.
// 0.14.0 (issue #28): zdjęcie po lewej, dane na prawo od zdjęcia (rozwinięcie niższe): trzy linijki kratek (lines),
// pod nimi odnośnik do strony osiągów typu. Pod zdjęcie dane schodzą tylko wtedy, gdy obok nich na zdjęcie zostaje
// mniej niż 220 px (aircraft.css, .ac-split z zawijaniem).
// 0.14.2 (issue #35): zdjęcie w ramce o stałych proporcjach (.photo-frame), pod nią linijka podpisu (.photo-credit):
// photo() zmienia tylko ich treść, więc dane obok się nie przesuwają; bez odnośników More photos, Image search
// i Performance search (zostaje Performance)
export function detail(a) {
  return `<tr class="ac-detail-row"><td colspan="${COLUMNS.length}"><div class="ac-detail"><div class="ac-split">
    <div class="photo-box"><div class="photo-frame"><span class="hint">Loading photo\u2026</span></div><div class="photo-credit hint"></div></div>
    <div class="ac-data">
      <div class="ac-boxes">${lines(a).map(([cat, row]) => `<div class="ac-line ${cat}">${row.map(box).join("")}</div>`).join("")}</div>
      <div class="ac-links">${link(perfUrl(a.icao), "Performance", "ac-perf")}</div>
    </div>
  </div></div></td></tr>`;
}

// Podpis pod zdjęciem. 0.14.2 (issue #35): zdjęcie dodane ręcznie (data/photos-manual/) z autorem jako zwykły tekst
// "Photo: <autor>", bez odnośnika. Zdjęcie pobrane automatycznie: odnośnik do strony zdjęcia (autor i licencja)
// nazwany wg funkcji, bez nazwy serwisu; sam tekst podpisu tylko przy własnym zdjęciu w data/photos/ bez strony
export function photoCredit(p) {
  if (p.author) return `Photo: ${esc(p.author)}`;
  if (p.page) return `<a href="${esc(p.page)}" target="_blank" rel="noopener">Photo page \u2197</a>`;
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
      <nav class="ac-makers">${MAKERS.map(([k, l, t]) => `<button class="gbtn" data-m="${k}" title="${t}">${l}</button>`).join("")}</nav>
      <div class="toolbar">
        <input type="search" class="q" placeholder="Search: ICAO type, model, manufacturer\u2026" size="46">
        <select class="wtc"><option value="">WTC: all</option><option>L</option><option>M</option><option>H</option><option>J</option></select>
        <select class="recat"><option value="">RECAT-EU: all</option>${Object.entries(RECAT).map(([k, v]) => `<option value="${k}">${k} \u2013 ${v}</option>`).join("")}</select>
        <span class="hint count"></span>
      </div>
      <div class="ac-list"><table class="data ac-table">${tableHead()}<tbody></tbody></table></div>
    </div>`);
    root.append(pane);
    // 0.13.1: klawiatura dotykowa (przycisk "()" pod ALL, do 0.13.2 KEYBOARD) zawsze ostatnia w panelu, pod
    // przewijaną listą
    const kbd = touchKeyboard(pane.querySelector(".q"), letters.kbd);
    pane.append(kbd.el);
    const $ = (s) => pane.querySelector(s);
    const list = $(".ac-list");
    const body = $(".ac-table tbody");
    // komunikat (brak typów, błąd) jako jeden wiersz na całą szerokość tabeli
    const message = (cls, text) => `<tr class="ac-msg"><td colspan="${COLUMNS.length}" class="${cls}">${text}</td></tr>`;
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
        recat: $(".recat").value, limit: LIMIT });
      const my = ++seq;
      let data;
      try {
        data = await api(`/api/aircraft?${qs}`);
      } catch (e) {
        if (my !== seq) return;
        $(".count").textContent = "";
        current = null;
        body.innerHTML = message("error", `Could not load aircraft types: ${esc(e.message)}`);
        return;
      }
      // starsza odpowiedź przyszła po nowszej
      if (my !== seq) return;
      const mk = MAKERS.find(([k]) => k === maker);
      const label = mk?.[1] || "";
      const groups = mk ? makerGroups(data, mk[3]) : [];
      rows = mk ? groups.flatMap(([, g]) => g) : data;
      current = null;
      $(".count").textContent = `${label ? label + ": " : ""}${types(rows.length)}${groups.length > 1 ? ` in ${groups.length} groups` : ""}`
        + (rows.length === LIMIT ? ` (first ${LIMIT} shown)` : "") + (rows.length ? " \u00b7 click a type for details" : "");
      // widok producenta: przed każdą grupą wiersz z nazwą producenta w bazie i liczbą typów
      let i = 0;
      body.innerHTML = !rows.length ? message("hint", `No${label ? ` ${label}` : ""} types for these filters.`)
        : !mk ? rows.map((a, n) => record(a, n)).join("")
          : groups.map(([name, g]) => `<tr class="ac-gh"><td colspan="${COLUMNS.length}">${esc(name)}<span>${types(g.length)}</span></td></tr>`
            + g.map((a) => record(a, i++)).join("")).join("");
    };

    // rozwinięcie przy dolnej krawędzi listy przewijane do widoku (najmniejszy ruch), ale kliknięty wiersz zostaje
    // widoczny pod przyklejonym nagłówkiem tabeli (scroll-margin-top w aircraft.css)
    const reveal = (rec, det) => {
      det.scrollIntoView({ block: "nearest" });
      if (rec.getBoundingClientRect().top < list.getBoundingClientRect().top + $(".ac-table thead").offsetHeight) {
        rec.scrollIntoView({ block: "start" });
      }
    };
    // zdjęcie w rozwinięciu; odpowiedź po zwinięciu albo po wyborze innego typu jest pomijana. 0.14.2 (issue #35):
    // zdjęcie albo komunikat w ramce, podpis w linijce pod nią; ramka ma stały rozmiar, więc rozwinięcie nie zmienia
    // wysokości po wczytaniu zdjęcia (bez ponownego przewijania do widoku)
    const photo = (det, a) => {
      const frame = det.querySelector(".photo-frame");
      const cap = det.querySelector(".photo-credit");
      api(`/api/aircraft/${a.id}/photo`).then((p) => {
        if (current !== a) return;
        frame.innerHTML = `<img src="${esc(p.url)}" alt="${esc(searchName(a))}">`;
        cap.innerHTML = photoCredit(p);
      }).catch((e) => {
        if (current !== a) return;
        frame.innerHTML = `<span class="hint">${esc(e.message)}</span>`;
      });
    };

    // klik w wiersz rozwija go (wiersz z rozwinięciem pod nim), ponowny klik zwija; nie jest krokiem do cofnięcia.
    // Odnośniki i treść rozwinięcia bez zmian
    list.addEventListener("click", (e) => {
      if (e.target.closest("a, .ac-detail-row")) return;
      const rec = e.target.closest("tr.ac-rec[data-i]");
      if (!rec) return;
      const was = rec.classList.contains("selected");
      body.querySelectorAll("tr.ac-rec.selected").forEach((x) => x.classList.remove("selected"));
      body.querySelectorAll("tr.ac-detail-row").forEach((x) => x.remove());
      current = null;
      if (was) return;
      rec.classList.add("selected");
      current = rows[rec.dataset.i];
      rec.insertAdjacentHTML("afterend", detail(current));
      const det = rec.nextElementSibling;
      reveal(rec, det);
      photo(det, current);
    });
    pane.querySelector(".ac-makers").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-m]");
      if (!b) return;
      // ponowny klik: zwykły widok (wszystkie); nowy producent: wszystkie jego typy, więc bez tekstu wyszukiwania
      if (b.dataset.m === maker) { prefix = ""; setMaker(""); letters.set(""); } else { $(".q").value = ""; setMaker(b.dataset.m); }
      list.scrollTop = 0;
      load();
      // krok do cofnięcia (←), jak litery
      remember("aircraft", maker ? "maker/" + maker : "");
    });
    $(".q").addEventListener("input", debounce(load));
    $(".wtc").addEventListener("change", load);
    $(".recat").addEventListener("change", load);
    load();
    // arg z adresu (← i Wstecz): litera "A"–"Z", "" = wszystkie, "maker/airbus" = producent, inny tekst = szukany typ
    // (np. #aircraft/B738); przycisk menu (arg undefined) zostawia bieżący widok. Dawny albo nieznany producent
    // (#aircraft/maker/atr, /mcdonnell, /cessna sprzed 0.13.1) otwiera ALL i podmienia adres na #aircraft
    return { activate: (arg) => {
      const mk = arg?.startsWith("maker/") ? arg.slice(6) : null;
      if (arg === undefined) { /* bez zmian */ } else if (/^[A-Z]?$/.test(arg)) {
        if (arg !== prefix || maker) { prefix = arg; setMaker(""); letters.set(arg); load(); }
      } else if (mk !== null && MAKERS.some(([k]) => k === mk)) {
        if (mk !== maker) { $(".q").value = ""; setMaker(mk); load(); }
      } else if (mk !== null) {
        if (prefix || maker || $(".q").value) { $(".q").value = ""; prefix = ""; setMaker(""); letters.set(""); load(); }
        remember("aircraft", "", { replace: true });
      } else { $(".q").value = arg; prefix = ""; setMaker(""); letters.set(""); load(); }
      kbd.sync();
      $(".q").focus();
    } };
  },
};
