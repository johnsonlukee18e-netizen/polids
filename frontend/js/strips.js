// AERODROME › RUCH: paski postępu lotu jak w EFES (elektroniczne paski PAŻP).
// Odloty niebieskie, przyloty żółte, loty lokalne (krąg, ADEP = ADES) różowe, planowane (prefile, tylko vIFF) przygaszone.
// Komórki wypełniamy tym, co naprawdę jest w danych VATSIM / vIFF / .ese; pusta komórka pokazuje tylko blady opis pola.
// Backend: GET /api/aerodromes/{icao}/strips (routers/aerodromes.py, services/procedures.py).
import { api, esc } from "./api.js";

const REFRESH_MS = 30000;
const STATE_CLASS = { FI: "fi", SI: "si", SU: "su", AA: "aa", TA: "ta" };
// kolor CTOT = opóźnienie jak w liście lotów NM: < 15 min, < 30, < 45, ≥ 45
const delayClass = (d) => (d === null || d === undefined || d < 1 ? "" : d < 15 ? "d15" : d < 30 ? "d30" : d < 45 ? "d45" : "d60");
const RULES = { I: "IFR", V: "VFR", Y: "IFR/V", Z: "VFR/I" };
const RWY_SRC = { ATIS: "z ATIS", SUGGESTED: "sugestia systemu (brak ATIS)", CDM: "przydzielony w EuroScope (CDM)" };
const WAKE = { L: "lekki", M: "średni", H: "ciężki", J: "super (A388)" };

const ph = (t) => `<span class="ph">${t}</span>`;
const t4 = (v) => (v ? esc(v) : "");
// poziom: do 6500 ft wysokość (A045), wyżej FL (F370)
const lvl = (ft) => (ft === null || ft === undefined || ft === "" ? "" : ft >= 6500
  ? "F" + String(Math.round(ft / 100)).padStart(3, "0") : "A" + String(Math.max(0, Math.round(ft / 100))).padStart(3, "0"));
const minsTxt = (m) => (m === null || m === undefined ? "" : m < 60 ? `${m}'` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`);

function movement(s, d) {
  // lot tylko z vIFF: bez danych VATSIM nie wiadomo, czy pilot jest połączony
  if (s.planned) return s.planned === "viff" ? (d?.network_error ? "VATSIM ?" : "OFFLINE") : "PREFILE";
  // na ziemi daleko od lotniska: przylot jeszcze na lotnisku odlotu, odlot np. już po przylocie do ADES
  if (s.away) return s.kind === "arr" ? "NA ZIEMI" : `NA ZIEMI ${s.dist_nm} NM`; // przylot: odległość jest w 1. komórce
  // w powietrzu: dla przylotu poziom jest w swojej komórce, więc tu prędkość względem ziemi
  if (s.state === "air") return s.kind === "arr" ? `W POW. ${s.groundspeed ?? "–"} KT` : `W POW. ${lvl(s.altitude)}`;
  return (s.groundspeed || 0) >= 3 ? "KOŁUJE" : s.kind === "arr" ? "NA ZIEMI" : "POSTÓJ";
}

function chip(s, states) {
  const v = s.viff;
  if (!v) return "";
  const label = v.state === "SU" && v.suspension ? "SU " + v.suspension.replace(/^FLS-?/, "") : v.state;
  return `<span class="fs fs-${STATE_CLASS[v.state] || "fi"}" data-h="${esc(states?.[v.state] || v.state)}">${esc(label)}</span>`
    + (v.ready ? `<span class="fs fs-rea" data-h="REA: gotowy do odlotu przed slotem">REA</span>` : "");
}

// SSR: kod przydzielony (plan lotu, assigned_transponder); bez przydziału aktualny transponder na szaro
function ssr(s) {
  if (s.assigned_squawk) return `<span class="ssr">${esc(s.assigned_squawk)}</span>`;
  return s.squawk ? `<span class="ssr cur">${esc(s.squawk)}</span>` : ph("SSR");
}

function procHint(s, icao) {
  const kind = s.kind === "arr" ? "STAR" : "SID";
  const p = s.proc;
  if (s.rules === "V") return `${kind}: lot VFR, bez procedury.`;
  if (!s.runway) return `${kind}: nie znamy pasa w użyciu.`;
  if (p?.source === "CDM") return `SID przydzielony w EuroScope (wtyczka CDM, vIFF: ${s.runway}/${p.name}).`;
  if (p?.source === "route") return `${kind} ${p.name} wpisany w trasę planu lotu; istnieje dla pasa ${s.runway} w pliku .ese.`;
  if (p) return kind === "SID" ? `SID z pliku .ese dla pasa ${s.runway}: ostatni punkt SID = pierwszy punkt trasy (${p.fix}).`
    : `STAR z pliku .ese dla pasa ${s.runway}: pierwszy punkt STAR = ostatni punkt trasy (${p.fix}).`;
  if (!s.route) return `Brak ${kind}: brak trasy w planie lotu.`;
  if (!s.proc_fix) return `Brak ${kind}: trasa ${kind === "SID" ? "nie zaczyna" : "nie kończy"} się punktem nawigacyjnym.`;
  return kind === "SID" ? `Brak SID: żaden SID pasa ${s.runway} (${icao}) w pliku .ese nie kończy się w ${s.proc_fix}.`
    : `Brak STAR: żaden STAR pasa ${s.runway} (${icao}) w pliku .ese nie zaczyna się w ${s.proc_fix}.`;
}

// prawe pole (w EFES przycisk SU): najważniejszy czas z vIFF albo minuty do przylotu
function box(s) {
  const v = s.viff || {};
  const b = (k, val, cls = "", h = "") => `<div class="c-box ${cls}" data-h="${esc(h)}"><span class="k">${k}</span><b>${esc(val)}</b></div>`;
  if (s.kind === "arr") {
    return s.eta_min !== null && s.eta_min !== undefined && s.state === "air"
      ? b("ZA", minsTxt(s.eta_min), "", "Minuty do przylotu (odległość / prędkość względem ziemi).")
      : `<div class="c-box empty" data-h="Minuty do przylotu: samolot nie jest w powietrzu.">${ph("ZA")}</div>`;
  }
  if (s.kind === "local") return `<div class="c-box empty" data-h="Lot lokalny VFR: bez slotu i A-CDM."></div>`;
  if (v.atot) return b("ATOT", v.atot, "", "ATOT: rzeczywisty czas startu (vIFF).");
  if (v.ctot) {
    const h = ["CTOT: slot ATFM z vIFF", v.delay !== null && v.delay !== undefined && `opóźnienie ${v.delay} min`,
      v.regulation && `regulacja ${v.regulation}`, v.airspace && `przestrzeń ${v.airspace}`].filter(Boolean).join(" · ");
    return b("CTOT", v.ctot, "ctot " + delayClass(v.delay), h);
  }
  if (v.ttot) return b("TTOT", v.ttot, "", "TTOT: planowany czas startu z A-CDM (vIFF), bez slotu.");
  return `<div class="c-box empty" data-h="Brak CTOT / TTOT w vIFF.">${ph("CTOT")}</div>`;
}

function stripHtml(s, d, sel) {
  const v = s.viff || {};
  const dep = s.kind !== "arr";
  const local = s.kind === "local";
  const states = d.states;
  const atis = d.atis?.letter;
  const cls = ["strip", s.kind, s.planned ? "planned" : "", s.state === "air" ? "air" : "", s.away ? "away" : "", sel ? "sel" : ""].join(" ");
  // 1: EOBT / SU-PB (odlot), ETA / CONT (przylot)
  let c1;
  if (s.kind === "arr") {
    c1 = `<div class="c c-time" data-h="ETA (UTC) = teraz + odległość / prędkość względem ziemi. Pod spodem odległość od ${esc(d.icao)}.">
      ${s.eta ? `<b class="t">${esc(s.eta)}</b>` : ph("ETA")}${s.dist_nm !== null && s.dist_nm !== undefined ? `<span class="s">${s.dist_nm} NM</span>` : ph("CONT")}</div>`;
  } else {
    const [k2, t2] = v.aobt ? ["AOBT", v.aobt] : v.tsat ? ["TSAT", v.tsat] : v.tobt ? ["TOBT", v.tobt] : [null, null];
    const h = `EOBT ${s.eobt_source === "vIFF" ? "z vIFF (IFPS)" : s.eobt_source === "FPL" ? "z planu lotu VATSIM (deptime)" : "nieznany"}.`
      + ` Pole SU/PB: ${k2 ? { AOBT: "AOBT (off-block, vIFF)", TSAT: "TSAT (start-up z A-CDM, vIFF)", TOBT: "TOBT (gotowość, A-CDM)" }[k2] : "brak TSAT/AOBT"}.`;
    c1 = `<div class="c c-time" data-h="${esc(h)}">${s.eobt ? `<b class="t">${esc(s.eobt)}</b>` : ph("EOBT")}
      ${k2 ? `<span class="s"><i>${k2}</i>${esc(t2)}</span>` : ph(local ? "TSTMP" : "SU/PB")}</div>`;
  }
  // 2: TYP + W / ADES (odlot) albo ADEP (przylot); lokalny: ADEP i ADES
  const wh = s.wake ? `Kategoria turbulencji ${s.wake} (${WAKE[s.wake] || "?"}) ${s.wake_source === "db" ? "z bazy typów" : "z planu lotu"}.` : "Kategoria turbulencji nieznana.";
  const type = `<span class="ty">${s.aircraft ? esc(s.aircraft) : ph("TYPE")}${s.wake ? `<i class="w w-${esc(s.wake)}">${esc(s.wake)}</i>` : ""}</span>`;
  const c2 = local
    ? `<div class="c c-type three" data-h="${esc(`Typ ICAO. ${wh} ADEP = ADES: lot lokalny (krąg).`)}">${type}<span class="s">${t4(s.departure)}</span><span class="s">${t4(s.arrival)}</span></div>`
    : `<div class="c c-type" data-h="${esc(`Typ ICAO. ${wh} Pod spodem ${dep ? "lotnisko docelowe (ADES): przy odlocie ważniejsze niż ADEP" : "lotnisko odlotu (ADEP)"}.`)}">
      ${type}${(dep ? s.arrival : s.departure) ? `<span class="s">${esc(dep ? s.arrival : s.departure)}</span>` : ph(dep ? "ADES" : "ADEP")}</div>`;
  // 3: CALLSIGN / STATUS
  const cs = s.callsign || "";
  const awayH = s.away ? ` Samolot na ziemi ${s.dist_nm} NM od ${d.icao}: ${s.kind === "arr" ? "jeszcze na lotnisku odlotu" : "poza lotniskiem odlotu (np. już po przylocie)"}.` : "";
  const netH = s.planned === "viff" && d.network_error ? " Brak danych VATSIM: nie wiadomo, czy pilot jest połączony." : "";
  const stH = `${s.viff ? (states?.[v.state] || v.state) + ". " : "Brak lotu w vIFF. "}Ruch: ${movement(s, d)}${s.groundspeed ? `, GS ${s.groundspeed} kt` : ""}.${awayH}${netH}`;
  const c3 = `<div class="c c-cs" data-h="${esc(stH)}"><span class="cs ${cs.length > 7 ? "long" : ""}">${esc(cs)}</span>
    <span class="st">${chip(s, states)}<span class="mv">${esc(movement(s, d))}</span></span></div>`;
  // 4: A (litera ATIS) / reguły + pas
  const aH = `A = litera ATIS ${d.icao}${atis ? "" : " (ATIS nie nadaje)"}. Pod spodem reguły lotu i pas ${s.kind === "arr" ? "do lądowania" : "startowy"}${s.runway ? ` ${s.runway}: ${RWY_SRC[s.runway_source] || ""}` : ": nieznany"}.`;
  const c4 = `<div class="c c-a" data-h="${esc(aH)}">${atis ? `<b class="atis">${esc(atis)}</b>` : ph("A")}
    <span class="s">${s.rules ? `<span class="ru ${s.rules === "V" ? "vfr" : ""}">${RULES[s.rules] || esc(s.rules)}</span>` : ""}${s.runway ? `<b class="rw">${esc(s.runway)}</b>` : ph("RWY")}</span></div>`;
  // 5: SID/STAR / CFL + SSR; lokalny: CUR / CFL + SSR
  const air = s.state === "air";
  const cflH = s.kind === "arr"
    ? `CFL: w danych VATSIM nie ma CFL. ${air ? "Pokazany aktualny poziom z sieci" : "Samolot nie jest w powietrzu"}; RFL z planu lotu ${s.rfl_ft ? lvl(s.rfl_ft) : "nieznany"}.`
    : "CFL: w danych VATSIM nie ma CFL, pokazany RFL (poziom przelotowy z planu lotu).";
  const ssrH = `SSR: ${s.assigned_squawk ? `kod przydzielony ${s.assigned_squawk}` : "brak przydzielonego kodu, szary = aktualny transponder"}${s.squawk && s.squawk !== s.assigned_squawk ? ` (transponder ${s.squawk})` : ""}.`;
  const level = s.kind === "arr"
    ? (air ? `<span class="cur"><i>CUR</i>${lvl(s.altitude)}</span>` : ph("CFL"))
    : (s.rfl_ft ? lvl(s.rfl_ft) : ph("CFL"));
  const low = `<span class="s"><span class="cfl" data-h="${esc(cflH)}">${level}</span><span data-h="${esc(ssrH)}">${ssr(s)}</span></span>`;
  const top = local
    ? `<span class="pr" data-h="Aktualna wysokość / poziom z sieci VATSIM (poprzedniego nie śledzimy).">${ph("PRV")}${air ? `<span class="cur"><i>CUR</i>${lvl(s.altitude)}</span>` : ph("CUR")}</span>`
    : s.proc ? `<b class="proc" data-h="${esc(procHint(s, d.icao))}">${esc(s.proc.name)}</b>` : `<span data-h="${esc(procHint(s, d.icao))}">${ph(s.kind === "arr" ? "STAR" : "SID")}</span>`;
  const c5 = `<div class="c c-proc">${top}${low}</div>`;
  const c6 = `<div class="c c-taxi" data-h="TAXI / GATE: drogi kołowania i stanowiska nie ma w danych sieci VATSIM.">${ph("TAXI")}${ph("GATE")}</div>`;
  // FREETEXT: trasa (i krótkie uwagi)
  const rmk = s.remarks && s.remarks.length <= 32 ? s.remarks : "";
  const free = [s.route, rmk].filter(Boolean).map(esc).join(" · ") || ph("FREETEXT");
  const lp = local ? `<span class="lp" data-h="Licznik przejść (LP) i dotyków (TG): nie ma tego w danych VATSIM.">LP:__ | TG:__ |</span>` : "";
  return `<div class="${cls}" data-k="${esc(s.kind + ":" + cs)}">
    <div class="s-top">${c1}${c2}${c3}${c4}${c5}${c6}${box(s)}</div>
    <div class="s-free" data-h="Trasa z planu lotu${rmk ? " i uwagi" : ""}.">${lp}<span class="ft">${free}</span></div></div>`;
}

// dymek: opis wskazanego pola + pełne dane paska
function tipText(s, d) {
  const v = s.viff || {};
  const fl = (ft) => (ft ? lvl(ft) : "–");
  const lines = [
    `${s.callsign}  ${s.aircraft_icao || s.aircraft || ""}`.trim(),
    `${s.departure || "?"} → ${s.arrival || "?"}  ·  ${RULES[s.rules] || "reguły ?"}  ·  RFL ${fl(s.rfl_ft)}`,
    `Trasa: ${s.route || "–"}`,
  ];
  if (s.remarks) lines.push(`Uwagi: ${s.remarks}`);
  lines.push(`SSR: przydzielony ${s.assigned_squawk || "–"} · transponder ${s.squawk || "–"}`);
  if (s.proc) lines.push(`${s.kind === "arr" ? "STAR" : "SID"} ${s.proc.name} (RWY ${s.proc.runway || s.runway})${s.proc.fixes?.length ? ": " + s.proc.fixes.join(" ") : ""}`
    + (s.proc.approaches?.length ? `  · podejścia: ${s.proc.approaches.join(", ")}` : ""));
  const times = [["EOBT", v.eobt], ["TOBT", v.tobt], ["TSAT", v.tsat], ["TTOT", v.ttot], ["CTOT", v.ctot], ["AOBT", v.aobt], ["ATOT", v.atot]]
    .filter(([, t]) => t).map(([k, t]) => `${k} ${t}`);
  if (s.viff) lines.push(`vIFF: ${times.join(" · ") || "bez czasów"}${v.delay ? ` · opóźnienie ${v.delay} min` : ""}${v.regulation ? ` · ${v.regulation}` : ""}`);
  if (s.kind === "arr" && s.eta) lines.push(`ETA ${s.eta}Z · ${s.dist_nm ?? "?"} NM · GS ${s.groundspeed ?? "?"} kt`);
  lines.push(s.planned ? "Lot planowany: pilot jeszcze nie połączony." : "Klik: zaznacz pasek · dwuklik: pokaż na mapie");
  return lines.join("\n");
}

const BAYS = [
  { key: "departures", cls: "dep main", title: "Odloty", sub: "na ziemi wg TSAT / CTOT / EOBT, potem w powietrzu", empty: "Brak odlotów" },
  { key: "planned", cls: "plan side", title: "Planowane", sub: "prefile i loty z vIFF bez połączenia", empty: "Brak planów" },
  { key: "arrivals", cls: "arr main", title: "Przyloty", sub: "wg ETA", empty: "Brak przylotów" },
  { key: "local", cls: "loc side", title: "Lokalne", sub: "ADEP = ADES (krąg)", empty: "Brak lotów lokalnych" },
];

function bayList(key, list, d, selected) {
  if (!list.length) return "";
  const html = (s) => stripHtml(s, d, selected === s.kind + ":" + s.callsign);
  const div = (t) => `<div class="sx-div">${t}</div>`;
  // na ziemi daleko od lotniska (backend: away) zawsze na końcu zatoki
  const x = list.filter((s) => s.away);
  const away = x.length ? div(`Na ziemi poza ${esc(d.icao)} · ${x.length}`) + x.map(html).join("") : "";
  if (key === "departures") {
    const g = list.filter((s) => s.state !== "air" && !s.away), a = list.filter((s) => s.state === "air");
    return g.map(html).join("") + (a.length ? div(`W powietrzu · ${a.length}`) + a.map(html).join("") : "") + away;
  }
  if (key === "arrivals") {
    const g = list.filter((s) => s.state === "ground" && !s.away), a = list.filter((s) => s.state !== "ground");
    return (g.length ? div(`Po lądowaniu · ${g.length}`) + g.map(html).join("") + (a.length ? div(`W powietrzu · ${a.length}`) : "") : "")
      + a.map(html).join("") + away;
  }
  return list.map(html).join("");
}

export function mountStrips(el, icao, { onUpdate } = {}) {
  el.innerHTML = `<div class="strips">
    <div class="sx-bar"><span class="hint">Ładowanie pasków…</span></div>
    <div class="sx-board">
      <div class="sx-col">${BAYS.slice(0, 2).map((b) => `<section class="sx-bay ${b.cls}" data-bay="${b.key}">
        <h3>${b.title} <span class="n"></span><span class="sub">${b.sub}</span></h3><div class="sx-list"></div></section>`).join("")}</div>
      <div class="sx-col">${BAYS.slice(2).map((b) => `<section class="sx-bay ${b.cls}" data-bay="${b.key}">
        <h3>${b.title} <span class="n"></span><span class="sub">${b.sub}</span></h3><div class="sx-list"></div></section>`).join("")}</div>
    </div>
    <div class="sx-tip" hidden></div>
  </div>`;
  const root = el.querySelector(".strips");
  const tip = root.querySelector(".sx-tip");
  let data = null, byKey = new Map(), selected = null, timer = null, dead = false, seq = 0, tipKey = "";

  const bar = (d) => {
    const u = d.runway_in_use || {};
    const src = u.source === "ATIS" ? `ATIS ${esc(d.atis?.letter || "")}` : "sugestia systemu";
    const errs = [d.network_error, d.viff_error].filter(Boolean);
    const n = (k) => d[k].length;
    const noProc = !d.procedures?.sid?.length && !d.procedures?.star?.length;
    return `<span class="kv" title="Pas startowy w użyciu (${esc(src)})"><i>DEP</i><b class="dep">${esc(u.dep || "–")}</b></span>
      <span class="kv" title="Pas do lądowania w użyciu (${esc(src)})"><i>ARR</i><b class="arr">${esc(u.arr || "–")}</b></span>
      ${u.source === "ATIS" ? "" : `<span class="kv sugg">sugestia systemu, brak pasa z ATIS</span>`}
      <span class="kv"><i>ATIS</i><b>${esc(d.atis?.letter || "–")}</b></span>
      <span class="kv" title="A-CDM: TOBT, TSAT, TTOT z vIFF${d.viff_error ? " (vIFF niedostępny: nie wiadomo)" : ""}"><i>A-CDM</i>${d.viff_error ? "?" : d.cdm ? "tak" : "nie"}</span>
      ${noProc ? `<span class="kv sugg">brak SID/STAR ${esc(d.icao)} w pliku .ese</span>` : ""}
      <span class="sx-legend"><span><s class="lg dep"></s>odlot ${n("departures")}</span><span><s class="lg arr"></s>przylot ${n("arrivals")}</span>
        <span><s class="lg loc"></s>lokalny ${n("local")}</span><span><s class="lg plan"></s>planowany ${n("planned")}</span></span>
      <span class="hint sx-note">CFL = RFL z planu lotu · SID/STAR z pliku .ese · najedź na pole: opis i trasa</span>
      ${errs.length ? `<span class="error">${errs.map(esc).join(" · ")}</span>` : ""}`;
  };

  const render = () => {
    const d = data;
    byKey = new Map();
    ["departures", "arrivals", "local", "planned"].forEach((k) => d[k].forEach((s) => byKey.set(s.kind + ":" + s.callsign, s)));
    if (selected && !byKey.has(selected)) selected = null;
    root.querySelector(".sx-bar").innerHTML = bar(d);
    BAYS.forEach((b) => {
      const sec = root.querySelector(`[data-bay="${b.key}"]`);
      const list = d[b.key] || [];
      sec.classList.toggle("empty", !list.length);
      sec.querySelector(".n").textContent = list.length;
      // bez danych VATSIM pusta zatoka nie znaczy "brak ruchu" (PLANOWANE mają jeszcze loty z vIFF)
      const empty = d.network_error && b.key !== "planned" ? "Brak danych z sieci VATSIM (zob. błąd wyżej)" : b.empty;
      sec.querySelector(".sx-list").innerHTML = bayList(b.key, list, d, selected) || `<div class="hint sx-empty">${empty}</div>`;
    });
    tip.hidden = true;
    tipKey = "";
  };

  const refresh = async () => {
    const my = ++seq;
    try {
      const d = await api(`/api/aerodromes/${icao}/strips`);
      if (dead || my !== seq) return;
      data = d;
      render();
      onUpdate?.(d);
    } catch (e) {
      if (dead || my !== seq) return;
      root.querySelector(".sx-bar").innerHTML = `<span class="error">${esc(e.message)}</span>`;
    }
  };

  // odświeżanie co 30 s tylko, gdy widok jest widoczny; schowany (inna zakładka) zatrzymuje się, activate() wznawia
  const visible = () => !document.hidden && root.isConnected && root.offsetParent !== null;
  const schedule = () => { clearTimeout(timer); timer = dead ? null : setTimeout(tick, REFRESH_MS); };
  const tick = async () => {
    timer = null;
    if (dead || !visible()) return;
    await refresh();
    if (!timer) schedule();
  };
  const onVis = () => { if (!document.hidden && !timer && visible()) { refresh(); schedule(); } };
  document.addEventListener("visibilitychange", onVis);

  root.addEventListener("click", (e) => {
    const st = e.target.closest(".strip");
    if (!st) return;
    selected = selected === st.dataset.k ? null : st.dataset.k;
    root.querySelectorAll(".strip.sel").forEach((x) => x.classList.remove("sel"));
    if (selected) st.classList.add("sel");
  });
  root.addEventListener("dblclick", (e) => {
    const s = byKey.get(e.target.closest(".strip")?.dataset.k);
    if (s && !s.planned) location.hash = "#map/" + encodeURIComponent(s.callsign);
  });
  root.addEventListener("mousemove", (e) => {
    const st = e.target.closest(".strip");
    const s = st && byKey.get(st.dataset.k);
    if (!s) { tip.hidden = true; tipKey = ""; return; }
    const cell = e.target.closest("[data-h]");
    const key = st.dataset.k + "|" + (cell?.dataset.h || "");
    if (key !== tipKey) {
      tipKey = key;
      tip.innerHTML = (cell?.dataset.h ? `<div class="h">${esc(cell.dataset.h)}</div>` : "") + `<div class="b">${esc(tipText(s, data))}</div>`;
    }
    tip.hidden = false;
    const w = tip.offsetWidth, hgt = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 18;
    if (x + w > innerWidth - 6) x = Math.max(6, e.clientX - w - 14);
    if (y + hgt > innerHeight - 6) y = Math.max(6, e.clientY - hgt - 14);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  });
  root.addEventListener("mouseleave", () => { tip.hidden = true; tipKey = ""; });

  refresh();
  schedule();
  return {
    resume() { if (!dead) { refresh(); schedule(); } },
    destroy() {
      dead = true;
      clearTimeout(timer);
      timer = null;
      document.removeEventListener("visibilitychange", onVis);
    },
  };
}
