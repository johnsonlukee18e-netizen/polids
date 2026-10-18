import { api, choiceGet, choiceSet, esc, h, navigate, ONLINE_EVENT, POS_KEY } from "../api.js";

// HOME ("?" w menu, strona startowa): powitanie zalogowanego kontrolera (imię i nazwisko z CID z /auth/me) z ratingiem,
// jego połączenie i rezerwacje w VATSIM (/api/vatsim/me), wybór stanowiska jak w AERODROME › OVERVIEW i przycisk
// przejścia tam przed sesją; na dole wersja aplikacji i bieżący AIRAC z datami.
// Bez logowania (tryb lokalny) samo "Welcome" i wybór stanowiska, bez ratingu i bez VATSIM.

// POS_KEY z api.js (ten sam w overview.js): stanowisko wybrane tutaj AERODROME › OVERVIEW otwiera od razu
// (moduł importuje tylko api.js, bo test powłoki wczytuje go w Node)
const REFRESH_MS = 60000;    // stan VATSIM odświeżany, gdy HOME jest na ekranie (data feed i tak co 30 s)

export function greeting(me) {
  const u = me?.user;
  if (!u || (!u.name && !u.cid)) return "Welcome";
  if (!u.name) return `Welcome, ${u.cid}`;
  return u.cid ? `Welcome, ${u.name} (${u.cid})` : `Welcome, ${u.name}`;
}

// ratingi VATSIM: numer z VATSIM Connect, skrót i oficjalna pełna nazwa
export const RATINGS = [
  [-1, "INA", "Inactive"], [0, "SUS", "Suspended"], [1, "OBS", "Pilot/Observer"], [2, "S1", "Tower Trainee"],
  [3, "S2", "Tower Controller"], [4, "S3", "Senior Student"], [5, "C1", "Enroute Controller"], [6, "C2", "Controller 2"],
  [7, "C3", "Senior Controller"], [8, "I1", "Instructor"], [9, "I2", "Instructor 2"], [10, "I3", "Senior Instructor"],
  [11, "SUP", "Supervisor"], [12, "ADM", "Administrator"],
];

// "S3 · Senior Student"; numer ma pierwszeństwo przed skrótem (sesje sprzed 0.12.3 mają tylko skrót w /auth/me)
export function ratingText(user) {
  if (!user) return "";
  const r = (typeof user.rating === "number" && RATINGS.find(([id]) => id === user.rating))
    || RATINGS.find(([, s]) => s === user.rating_short);
  if (r) return `${r[1]} · ${r[2]}`;
  return user.rating_short ? String(user.rating_short) : "";
}

const ymd = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
};

// "AIRAC 2610 · 01.10.2026 – 28.10.2026": cykl kończy się dzień przed początkiem następnego
export function airacText(airac) {
  if (!airac?.ident) return "";
  const from = ymd(airac.effective);
  const next = /^\d{4}-\d{2}-\d{2}/.test(airac.next || "") ? new Date(airac.next.slice(0, 10) + "T00:00:00Z") : null;
  const to = next && !isNaN(next) ? ymd(new Date(next.getTime() - 86400000).toISOString()) : "";
  return `AIRAC ${airac.ident}` + (from && to ? ` · ${from} – ${to}` : from ? ` · from ${from}` : "");
}

// "10:12Z" (pusty napis dla złej daty: dane z zewnątrz, toISOString rzuciłby wyjątek)
export function utcHm(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? d.toISOString().slice(11, 16) + "Z" : "";
}

// godziny rezerwacji "18:00–20:00Z"; zaczyna się innego dnia (UTC) niż dziś: z datą, np. "16.10 08:00–10:00Z"
export function bookingTime(b, now = new Date()) {
  const s = b?.start ? new Date(b.start) : null;
  const day = s && !isNaN(s) && s.toISOString().slice(0, 10) !== now.toISOString().slice(0, 10)
    ? `${s.toISOString().slice(8, 10)}.${s.toISOString().slice(5, 7)} ` : "";
  return `${day}${utcHm(b?.start).replace("Z", "")}–${utcHm(b?.end)}`;
}

// "Booking: EPWA_TWR 18:00–20:00Z", z rodzajem innym niż zwykła rezerwacja (event, training…) i "in progress"
export function bookingText(b, now = new Date()) {
  const type = b?.type && b.type !== "booking" ? ` (${b.type})` : "";
  return `Booking: ${b?.callsign || "?"} ${bookingTime(b, now)}${type}${b?.active ? " · in progress" : ""}`;
}

// obserwator i ATIS to też połączenia z CID kontrolera, ale nie stanowiska
export const isPosition = (c) => !/_(ATIS|OBS)$/i.test(c?.callsign || "") && c?.facility !== 0;

// "You are connected to VATSIM as EPWW_DBT_CTR (127.025) since 10:12Z"; ATIS i obserwator osobnymi słowami
export function onlineText(c) {
  const since = utcHm(c.logon_time) ? ` since ${utcHm(c.logon_time)}` : "";
  const freq = c.frequency ? ` (${c.frequency})` : "";
  if (/_ATIS$/i.test(c.callsign || "")) return `ATIS ${c.callsign}${freq}${since}${c.atis_code ? ` · information ${c.atis_code}` : ""}`;
  if (!isPosition(c)) return `You are connected to VATSIM as an observer (${c.callsign})${since}`;
  return `You are connected to VATSIM as ${c.callsign}${freq}${since}`;
}

// stanowisko z listy OVERVIEW dla znaku z sieci: dokładnie ten znak, stanowisko dopasowane przez serwer (`alt`, jak
// w EuroScope), znak bez pustych członów (zastępstwo EPWA__APP), a DEL/GND/TWR/RMP lotniska to wieża z listy
export function listedPosition(cs, list, alt = null) {
  const has = new Set(list.map((p) => p.callsign));
  const parts = String(cs || "").toUpperCase().split("_").filter(Boolean);
  for (const c of [cs, alt, parts.join("_")]) if (c && has.has(c)) return c;
  if (parts.length >= 2 && /^(DEL|GND|TWR|RMP)$/.test(parts[parts.length - 1])) {
    const twr = list.find((p) => p.goto && p.goto === parts[0]);
    if (twr) return twr.callsign;
  }
  return "";
}

// stanowisko na start HOME: zalogowany w sieci > zapisane (HOME albo OVERVIEW) > najbliższa rezerwacja > nic (cały FIR)
export function initialPosition({ online = [], bookings = [], stored = "", list = [] } = {}) {
  for (const c of online.filter(isPosition)) {
    const p = listedPosition(c.callsign, list, c.position);
    if (p) return { callsign: p, source: "online" };
  }
  if (stored && list.some((p) => p.callsign === stored)) return { callsign: stored, source: "stored" };
  const sorted = [...bookings].sort((a, b) => String(a.start || "").localeCompare(String(b.start || "")));
  for (const b of sorted) {
    const p = listedPosition(b.callsign, list);
    if (p) return { callsign: p, source: "booking" };
  }
  return { callsign: "", source: null };
}

// stanowisko w polu HOME po pokazaniu HOME, wczytaniu listy i każdej odpowiedzi VATSIM (czysta funkcja, testy w Node).
// state: {seen, picked, appliedOnline}: wybór wspólny z OVERVIEW (choiceGet), jaki HOME ostatnio widział, czy wybrano
// ręcznie (tu albo w OVERVIEW) i stanowisko z sieci już ustawione; net: odpowiedź /api/vatsim/me (null: jeszcze nie ma
// albo tryb lokalny); shared: wspólny wybór teraz. Zwraca nowy stan i `choose`: stanowisko do ustawienia albo null.
//  - wybór zmieniony w międzyczasie w OVERVIEW tego okna: ten wybór (jak ręczny);
//  - zalogowany w sieci na stanowisku z listy: to stanowisko, ale raz na zalogowanie, potem wybór ręczny zostaje;
//  - bez wyboru ręcznego: zapisany > rezerwacja > cały FIR (initialPosition);
//  - awaria data feed (online_error, także brak odpowiedzi PolIDS) to nie wylogowanie: nic się nie zmienia, a po powrocie
//    feedu kontroler dalej zalogowany na tym samym stanowisku nie dostaje go drugi raz w miejsce wyboru ręcznego.
export function homeChoice({ seen = "", picked = false, appliedOnline = "" } = {},
                           { net = null, shared = seen, list = [] } = {}) {
  if (shared !== seen) return { seen: shared, picked: true, appliedOnline, choose: shared };
  const known = Boolean(net) && !net.online_error;   // wiadomo, czy jest teraz w sieci
  const start = initialPosition({ online: known ? net.online || [] : [], bookings: net?.bookings || [], stored: seen, list });
  if (start.source === "online" && start.callsign !== appliedOnline) {
    return { seen, picked: true, appliedOnline: start.callsign, choose: start.callsign };   // po wylogowaniu zostaje
  }
  // nie ma go w sieci: następne zalogowanie (także na to samo stanowisko) znowu je ustawi
  const applied = start.source === "online" || !known ? appliedOnline : "";
  return { seen, picked, appliedOnline: applied, choose: picked ? null : start.callsign };
}

// dokąd prowadzi przycisk: wieża (goto = ICAO) od razu do AERODROME lotniska, jak wybór TWR w OVERVIEW; reszta do OVERVIEW
export function sessionTarget(p) {
  return p?.goto ? { arg: p.goto, label: `PREPARE SESSION → AERODROME ${p.goto}` }
    : { arg: "0", label: "PREPARE SESSION → AERODROME OVERVIEW" };
}

const aerodromes = (n) => (n === 1 ? "aerodrome" : "aerodromes");

export default {
  mount(root, ctx) {
    const user = ctx.me?.user || null;
    const rating = ratingText(user);
    const foot = [ctx.config?.version, airacText(ctx.config?.airac)].filter(Boolean);
    root.append(h(`<div class="pane home-pane">
      <div class="home-main">
        <h1 class="home-hello">${esc(greeting(ctx.me))}</h1>
        ${rating ? `<div class="home-rating">${esc(rating)}</div>` : ""}
        ${user ? `<div class="card home-card"><h3>VATSIM</h3><div class="home-net"><span class="hint">Checking…</span></div></div>` : ""}
        <div class="card home-card"><h3>Position</h3>
          <select class="field home-pos" disabled><option value="">All aerodromes FIR EPWW</option></select>
          <div class="hint home-pos-note"></div>
          <button class="gbtn home-go" type="button">${esc(sessionTarget(null).label)}</button>
        </div>
      </div>
      <footer class="home-foot">${foot.map((t) => `<span>${esc(t)}</span>`).join("")}</footer>
    </div>`));
    const $ = (s) => root.querySelector(s);
    const sel = $(".home-pos");
    const list = [];          // stanowiska z /api/overview/positions: {callsign, name, frequency, airports, goto}
    let listLoaded = false;
    let net = null;           // ostatnia odpowiedź /api/vatsim/me
    let netAt = 0;
    // stan wyboru (homeChoice): wspólny wybór, jaki HOME ostatnio widział (z pamięci okna: działa bez localStorage,
    // a drugie okno PolIDS go nie zmienia), wybór ręczny i stanowisko z sieci już ustawione
    let choice = { seen: choiceGet(POS_KEY), picked: false, appliedOnline: "" };

    const current = () => list.find((p) => p.callsign === sel.value) || null;
    const drawChoice = () => {
      const p = current();
      $(".home-go").textContent = sessionTarget(p).label;
      const booked = p && (net?.bookings || []).find((b) => listedPosition(b.callsign, list) === p.callsign);
      $(".home-pos-note").innerHTML = !p ? (listLoaded ? "all controlled aerodromes FIR EPWW" : "")
        : esc([p.name, p.frequency].filter(Boolean).join(" · "))
          + (p.goto ? "" : ` · aerodromes: <b>${p.airports.map(esc).join(", ")}</b>`)
          + (booked ? ` · <span class="home-ok">booking ${booked.callsign !== p.callsign ? esc(booked.callsign) + " " : ""}${esc(bookingTime(booked))}</span>` : "");
    };
    const choose = (cs) => {
      if (cs === "" || list.some((p) => p.callsign === cs)) sel.value = cs;
      drawChoice();
    };

    const drawNet = () => {
      const body = $(".home-net");
      if (!body || !net) return;
      const online = net.online || [], books = net.bookings || [];
      const line = (text, cls = "") => `<div class="home-line${cls ? " " + cls : ""}">${esc(text)}</div>`;
      const lines = online.map((c) => line(onlineText(c), isPosition(c) ? "home-on" : ""));
      if (!online.length && !net.online_error) lines.push(line("You are not connected to VATSIM as a controller.", "muted"));
      lines.push(...books.map((b) => line(bookingText(b))));
      if (!books.length && !net.bookings_error) lines.push(line("No bookings in the next 24 h.", "muted"));
      if (net.error) lines.push(line(net.error, "error"));
      body.innerHTML = lines.join("");
    };

    // stanowisko na start, po zmianie w OVERVIEW i po nowym zalogowaniu w sieci; wyboru ręcznego odświeżenie nie zmienia
    const decide = () => {
      if (!listLoaded) return;
      const { choose: cs, ...next } = homeChoice(choice, { net, shared: choiceGet(POS_KEY), list });
      choice = next;
      if (cs !== null) choose(cs); else drawChoice();
    };

    const loadList = async () => {
      let data;
      try { data = await api("/api/overview/positions"); } catch (e) { $(".home-pos-note").innerHTML = `<span class="error">${esc(e.message)}</span>`; return; }
      if (listLoaded) return;
      listLoaded = true;
      data.groups.forEach((g) => {
        if (!g.positions.length) return;
        list.push(...g.positions);
        const og = document.createElement("optgroup");
        og.label = g.label;
        og.innerHTML = g.positions.map((p) => `<option value="${esc(p.callsign)}">${esc(p.callsign)}${p.frequency ? ` · ${esc(p.frequency)}` : ""}${p.goto
          ? ` → AERODROME ${esc(p.goto)}` : ` · ${p.airports.length} ${aerodromes(p.airports.length)}`}</option>`).join("");
        sel.append(og);
      });
      sel.disabled = false;
    };
    const loadNet = async () => {
      if (!user) return;
      netAt = Date.now();
      try { net = await api("/api/vatsim/me"); } catch (e) { net = { online: [], bookings: [], error: e.message, online_error: e.message, bookings_error: e.message }; }
      drawNet();
    };
    // OVERVIEW tego okna dostaje wybór z pamięci okna (choiceGet), następne otwarcie strony z localStorage
    const save = () => { choice = { ...choice, seen: sel.value }; choiceSet(POS_KEY, sel.value); };

    sel.addEventListener("change", () => {
      choice = { ...choice, picked: true };
      save();
      drawChoice();
    });
    $(".home-go").addEventListener("click", () => {
      // także wybór automatyczny (z sieci albo z rezerwacji): OVERVIEW otworzy to samo; przed wczytaniem listy pole jest
      // puste, więc nic nie zapisujemy (OVERVIEW zostaje przy wyborze sprzed chwili)
      if (listLoaded) save();
      navigate("aerodrome", sessionTarget(current()).arg);
    });

    // HOME na ekranie: co minutę stan VATSIM (zalogowanie w EuroScope widać bez przeładowania strony)
    setInterval(() => {
      if (user && root.classList.contains("active") && !document.hidden) loadNet().then(decide);
    }, REFRESH_MS);

    // wybór w polu zaraz po wczytaniu listy (zapisany albo cały FIR), nie dopiero po odpowiedzi VATSIM; potem z siecią
    const loadAll = () => Promise.all([loadList().then(decide), loadNet()]).then(decide);
    // łańcuch: kolejne pokazanie HOME czeka na poprzednie wczytanie (błąd jednego nie blokuje następnych)
    let ready = loadAll().catch((e) => console.error(e));
    // serwer wrócił (lista stanowisk się nie wczytała): od razu, nie dopiero przy następnym pokazaniu HOME
    window.addEventListener(ONLINE_EVENT, () => {
      if (!listLoaded) ready = ready.then(loadAll).catch((e) => console.error(e));
    });
    return {
      // każde pokazanie HOME: stanowisko zmienione w międzyczasie w OVERVIEW i świeży stan VATSIM (najwyżej co 30 s)
      activate() {
        ready = ready.then(() => {
          if (!listLoaded) return loadAll();
          decide();
          return user && Date.now() - netAt > 30000 ? loadNet().then(decide) : undefined;
        }).catch((e) => console.error(e));
      },
    };
  },
};
