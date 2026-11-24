import { api, choiceGet, choiceSet, esc, h, navigate, ONLINE_EVENT, POS_KEY, remember } from "../api.js";

// HOME ("?" w menu, strona startowa): powitanie zalogowanego kontrolera (imię i nazwisko z CID z /auth/me) z ratingiem,
// jego połączenie i rezerwacje w VATSIM (/api/vatsim/me), wybór stanowiska i przycisk SELF CHECK-IN; na dole wersja
// aplikacji i bieżący AIRAC z datami.
// Bez logowania (tryb lokalny) samo "Welcome" i wybór stanowiska, bez ratingu i bez VATSIM.
// 0.14.0 (issue #28): "Przenieś tutaj aerodrome overview i cały check-in. Najpierw wyświetl powitanie oraz wybór pozycji
// a następnie otwórz stronę selfcheckin (dawne overview)". Dwa kroki w jednej zakładce:
//   1. #home: powitanie, VATSIM, wybór stanowiska i przycisk SELF CHECK-IN (aplikacja zawsze startuje tutaj),
//   2. #home/checkin: SELF CHECK-IN dla wybranego stanowiska (overview.js, dawne AERODROME › OVERVIEW) w miejscu
//      kroku 1, z przyciskiem powrotu do kroku 1 (zmiana stanowiska); własny adres, więc ← i Wstecz działają.
// Wieża (TWR) zamiast check-inu otwiera od razu stronę INFO lotniska w AERODROME, jak wybór TWR w dawnym OVERVIEW.

// POS_KEY z api.js (ten sam w overview.js): stanowisko wybrane w kroku 1 check-in otwiera od razu.
// Moduł importuje statycznie tylko api.js (test powłoki wczytuje go w Node); overview.js przez import() w mount()
// (ovImport niżej), montowany dopiero w kroku 2
// stan VATSIM odświeżany, gdy krok 1 HOME jest na ekranie (data feed i tak co 30 s)
const REFRESH_MS = 60000;

// 0.14.0 (issue #28): krok 2 w adresie (#home/checkin); "" = krok 1
export const CHECKIN = "checkin";
// krok tylko wg adresu: "checkin" (dowolna wielkość liter) = krok 2, wszystko inne = krok 1: #home, stary albo nieznany
// #home/x, a także undefined, czyli przycisk "?" w menu, logo (href="#home") i nieznany adres (#foo). Przegląd 0.14.0:
// "?" zawsze otwiera najpierw powitanie i wybór pozycji (issue #28), nie ostatni krok jak stan innych zakładek
export const stepOf = (arg) => (String(arg ?? "").toLowerCase() === CHECKIN ? CHECKIN : "");

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

// na częstotliwości stanowiska z danych (`active` z /api/vatsim/me; 0.13.6, właściciel projektu: na 199.998 "jakby go nie było")
export const onFrequency = (c) => c?.active !== false && !/^199\.998/.test(String(c?.frequency || ""));

// obserwator i ATIS to też połączenia z CID kontrolera, ale nie stanowiska; bez częstotliwości stanowiska też nie
export const isObserver = (c) => /_OBS$/i.test(c?.callsign || "") || c?.facility === 0;
export const isPosition = (c) => !/_ATIS$/i.test(c?.callsign || "") && !isObserver(c) && onFrequency(c);

// "You are connected to VATSIM as EPWW_DBT_CTR (127.025) since 10:12Z"; ATIS, obserwator i połączenie bez
// częstotliwości stanowiska (199.998) osobnymi słowami
export function onlineText(c) {
  const since = utcHm(c.logon_time) ? ` since ${utcHm(c.logon_time)}` : "";
  const freq = c.frequency ? ` (${c.frequency})` : "";
  if (/_ATIS$/i.test(c.callsign || "")) {
    if (!onFrequency(c)) return `ATIS ${c.callsign}${freq}${since}, not on a position frequency`;
    return `ATIS ${c.callsign}${freq}${since}${c.atis_code ? ` · information ${c.atis_code}` : ""}`;
  }
  if (isObserver(c)) return `You are connected to VATSIM as an observer (${c.callsign})${since}`;
  if (!onFrequency(c)) return `You are connected to VATSIM as ${c.callsign}${freq}${since}, not on a position frequency`;
  return `You are connected to VATSIM as ${c.callsign}${freq}${since}`;
}

// stanowisko z listy check-inu dla znaku z sieci: stanowisko dopasowane przez serwer (`alt`; od 0.13.5 wg aktywnej
// częstotliwości, jak w EuroScope: EPWW_DBF_CTR na 127.025 to EPWW_DBT_CTR), dokładnie ten znak, znak bez pustych
// członów (zastępstwo EPWA__APP), a DEL/GND/TWR/RMP lotniska to wieża z listy
export function listedPosition(cs, list, alt = null) {
  const has = new Set(list.map((p) => p.callsign));
  const parts = String(cs || "").toUpperCase().split("_").filter(Boolean);
  for (const c of [alt, cs, parts.join("_")]) if (c && has.has(c)) return c;
  if (parts.length >= 2 && /^(DEL|GND|TWR|RMP)$/.test(parts[parts.length - 1])) {
    const twr = list.find((p) => p.goto && p.goto === parts[0]);
    if (twr) return twr.callsign;
  }
  return "";
}

// stanowisko na start HOME: zalogowany w sieci > zapisane (krok 1 albo check-in) > najbliższa rezerwacja > nic (cały FIR).
// Zalogowany tylko przez stanowisko dopasowane przez serwer po częstotliwości (0.13.6: nie po znaku)
export function initialPosition({ online = [], bookings = [], stored = "", list = [] } = {}) {
  for (const c of online.filter(isPosition)) {
    const p = c.position ? listedPosition(c.position, list) : "";
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
// state: {seen, picked, appliedOnline}: wybór wspólny z check-inem (choiceGet), jaki HOME ostatnio widział, czy wybrano
// ręcznie (tu albo w check-inie) i stanowisko z sieci już ustawione; net: odpowiedź /api/vatsim/me (null: jeszcze nie ma
// albo tryb lokalny); shared: wspólny wybór teraz. Zwraca nowy stan i `choose`: stanowisko do ustawienia albo null.
//  - wybór zmieniony w międzyczasie w check-inie (krok 2) albo w COORDINATION tego okna: ten wybór (jak ręczny);
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

// dokąd prowadzi przycisk: wieża (goto = ICAO) od razu do strony INFO lotniska w AERODROME, jak wybór TWR w check-inie;
// reszta (ACC, APP, cały FIR) do kroku 2 HOME, czyli SELF CHECK-IN (0.14.0, issue #28; dawniej AERODROME › OVERVIEW)
export function sessionTarget(p) {
  return p?.goto ? { tab: "aerodrome", arg: p.goto, label: `SELF CHECK-IN \u2192 AERODROME ${p.goto}` }
    : { tab: "home", arg: CHECKIN, label: "SELF CHECK-IN" };
}

// 0.14.0 (issue #28): import() z ponowną próbą (czysta funkcja, testy w Node). load(n) zwraca obietnicę modułu, n = numer
// próby (0 = pierwsza). Wczytywany albo wczytany moduł zostaje (każde wywołanie dostaje tę samą obietnicę), nieudana
// próba jest zapominana, a następna dostaje kolejny numer: nieudany import() przeglądarka zapamiętuje pod jego adresem
// (Chrome nie pobiera go drugi raz aż do przeładowania strony), więc ponowna próba musi iść pod innym (?retry=n)
export function retryImport(load) {
  let p = null, n = 0;
  return () => (p ??= load(n).catch((e) => { p = null; n += 1; throw e; }));
}

const aerodromes = (n) => (n === 1 ? "aerodrome" : "aerodromes");

export default {
  mount(root, ctx) {
    const user = ctx.me?.user || null;
    const rating = ratingText(user);
    // cykl nieznany (brak /api/config): "AIRAC –" jak w menu, nie pusta stopka
    const foot = [ctx.config?.version, airacText(ctx.config?.airac) || "AIRAC –"].filter(Boolean);
    // 0.14.0 (issue #28): krok 1 (.home-main) i krok 2 (.home-checkin, SELF CHECK-IN) w jednym panelu, widoczny jeden;
    // stopka z wersją i AIRAC pod oboma
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
      <div class="home-checkin" hidden></div>
      <footer class="home-foot">${foot.map((t) => `<span>${esc(t)}</span>`).join("")}</footer>
    </div>`));
    const $ = (s) => root.querySelector(s);
    const pane = $(".home-pane");
    const sel = $(".home-pos");
    const list = [];          // stanowiska z /api/overview/positions: {callsign, name, frequency, airports, goto}
    let listLoaded = false;
    let net = null;           // ostatnia odpowiedź /api/vatsim/me
    let netAt = 0;
    // stan wyboru (homeChoice): wspólny wybór, jaki HOME ostatnio widział (z pamięci okna: działa bez localStorage,
    // a drugie okno PolIDS go nie zmienia), wybór ręczny i stanowisko z sieci już ustawione
    let choice = { seen: choiceGet(POS_KEY), picked: false, appliedOnline: "" };
    // 0.14.0 (issue #28): krok na ekranie ("" albo CHECKIN) i check-in (mountOverview), gdy już otwarty
    let step = "", ov = null, ovLoading = null;

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

    // stanowisko na start, po zmianie w check-inie i po nowym zalogowaniu w sieci; wyboru ręcznego odświeżenie nie zmienia
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
    // check-in tego okna dostaje wybór z pamięci okna (choiceGet), następne otwarcie strony z localStorage
    const save = () => { choice = { ...choice, seen: sel.value }; choiceSet(POS_KEY, sel.value); };

    // --- 0.14.0 (issue #28): krok 2, SELF CHECK-IN ------------------------------------------------------------------
    const box = $(".home-checkin");
    // overview.js pobierany od razu przy montowaniu HOME (serwer właśnie odpowiedział; do 0.13.6 statyczny import
    // w AERODROME), a montowany dopiero w kroku 2. Ponowna próba po błędzie pod nowym adresem (retryImport);
    // importy overview.js (api.js, meteo.js, checklist.js) to dalej te same, już wczytane moduły
    const ovImport = retryImport((n) => import(n ? `../overview.js?retry=${n}` : "../overview.js"));
    // błąd pokaże dopiero otwarcie kroku 2
    ovImport().catch(() => {});
    // serwer nie odpowiada przy otwarciu kroku 2: komunikat z przyciskiem TRY AGAIN, ponowna próba także po powrocie
    // serwera i przy następnym otwarciu kroku 2.
    // Check-in już otwarty: zostaje ze swoim filtrem i checklistą, chyba że w kroku 1 wybrano inne stanowisko (sync)
    const openCheckin = () => {
      if (ov) { ov.sync(); return; }
      if (ovLoading) return;
      box.innerHTML = `<div class="hint home-ci-msg">Loading the self check-in\u2026</div>`;
      ovLoading = ovImport().then(({ mountOverview }) => {
        box.innerHTML = "";
        ov = mountOverview(box, {
          // wieża wybrana w polu check-inu: strona INFO lotniska w AERODROME (krok do cofnięcia)
          onGoto: (code) => navigate("aerodrome", code),
          // powrót do kroku 1 (zmiana stanowiska): krok do cofnięcia, jak każda zmiana ekranu
          onBack: () => navigate("home", ""),
        });
      }).catch((e) => {
        console.error(e);
        box.innerHTML = `<div class="home-ci-msg"><span class="error">The self check-in could not be loaded.</span>
          <button class="btn home-ci-retry" type="button">TRY AGAIN</button></div>`;
        box.querySelector(".home-ci-retry").addEventListener("click", () => openCheckin());
      }).finally(() => { ovLoading = null; });
    };
    // krok na ekranie: krok 1 albo check-in; krok 2 bez wczytanego modułu wczytuje go teraz
    const showStep = (s) => {
      step = s;
      const ci = step === CHECKIN;
      pane.classList.toggle("ci-mode", ci);
      $(".home-main").hidden = ci;
      box.hidden = !ci;
      if (ci) openCheckin();
    };

    sel.addEventListener("change", () => {
      choice = { ...choice, picked: true };
      save();
      drawChoice();
    });
    $(".home-go").addEventListener("click", () => {
      // także wybór automatyczny (z sieci albo z rezerwacji): check-in otworzy to samo; przed wczytaniem listy pole jest
      // puste, więc nic nie zapisujemy (check-in zostaje przy wyborze sprzed chwili)
      if (listLoaded) save();
      const t = sessionTarget(current());
      navigate(t.tab, t.arg);
    });

    // krok 1 na ekranie: co minutę stan VATSIM (zalogowanie w EuroScope widać bez przeładowania strony)
    setInterval(() => {
      if (user && step === "" && root.classList.contains("active") && !document.hidden) loadNet().then(decide);
    }, REFRESH_MS);

    // wybór w polu zaraz po wczytaniu listy (zapisany albo cały FIR), nie dopiero po odpowiedzi VATSIM; potem z siecią
    const loadAll = () => Promise.all([loadList().then(decide), loadNet()]).then(decide);
    // łańcuch: kolejne pokazanie HOME czeka na poprzednie wczytanie (błąd jednego nie blokuje następnych)
    let ready = loadAll().catch((e) => console.error(e));
    // serwer wrócił (lista stanowisk albo check-in się nie wczytały): od razu, nie dopiero przy następnym pokazaniu HOME
    window.addEventListener(ONLINE_EVENT, () => {
      if (!listLoaded) ready = ready.then(loadAll).catch((e) => console.error(e));
      if (step === CHECKIN && !ov) openCheckin();
    });
    return {
      // arg: "checkin" = krok 2, wszystko inne = krok 1 (stepOf), także undefined: start aplikacji, przycisk "?" w menu
      // i logo zawsze otwierają krok 1; check-in zostaje zamontowany, więc SELF CHECK-IN wraca do niego z filtrem.
      // Każde pokazanie HOME: stanowisko zmienione w międzyczasie w check-inie i świeży stan VATSIM (najwyżej co 30 s)
      activate(arg) {
        showStep(stepOf(arg));
        remember("home", step);
        ready = ready.then(() => {
          if (!listLoaded) return loadAll();
          decide();
          return user && Date.now() - netAt > 30000 ? loadNet().then(decide) : undefined;
        }).catch((e) => console.error(e));
      },
    };
  },
};
