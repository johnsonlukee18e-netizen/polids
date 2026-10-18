import { esc, h } from "../api.js";

// CONVERSION: kalkulator jednostek dla kontrolera. Jedna karta na wielkość; wpisanie wartości w dowolne pole od razu
// przelicza pozostałe pola karty (bez przycisku). Przecinek albo kropka jako separator dziesiętny, spacje między
// tysiącami i "FL" przed poziomem są dozwolone. Pod każdą kartą stała albo wzór. Obliczenia to czyste funkcje
// (testy w Node: backend/tests/test_conversion.py).

// --- Stałe (dokładne z definicji, poza inHg i mmHg)
export const HPA_INHG = 33.8639;      // 1 inHg w hPa
export const HPA_MMHG = 1.333224;     // 1 mmHg w hPa
export const M_FT = 0.3048;           // 1 ft w m
export const KM_NM = 1.852;           // 1 NM w km
export const KM_SM = 1.609344;        // 1 mila lądowa (SM) w km
export const KG_LB = 0.45359237;      // 1 lb w kg
export const FT_NM = KM_NM * 1000 / M_FT;   // 1 NM w ft (6076.12)

// liczba z pola: "1013,25", " 29.92 ", "10 000", "FL100"; puste → null, inny tekst → NaN
export function parseNum(s) {
  const t = String(s ?? "").trim().replace(/^FL\s*/i, "").replace(/[\s ]/g, "").replace(",", ".");
  if (!t) return null;
  return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(t) ? Number(t) : NaN;
}

// wynik do pola: najwyżej dp miejsc po kropce, bez zer na końcu (29.90 → 29.9, 760.0 → 760), bez "-0"
export function fmtNum(v, dp = 2) {
  if (v === null || v === undefined || !Number.isFinite(v)) return "";
  let s = v.toFixed(dp);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s === "-0" ? "0" : s;
}

// liczba ze znakiem do opisu pod polami: +419, −454 (typograficzny minus), 0
export const signed = (v, dp = 0) => { const s = fmtNum(v, dp); return s === "0" ? s : v < 0 ? "−" + s.slice(1) : "+" + s; };

// Jednostka grupy: to(v) = wartość w jednostce bazowej grupy, from(b) = z jednostki bazowej; dp = zaokrąglenie w polu
const lin = (id, label, f, dp) => ({ id, label, dp, to: (v) => v * f, from: (b) => b / f });
const fn = (id, label, to, from, dp) => ({ id, label, dp, to, from });
const RAD = Math.PI / 180;
export const GROUPS = {
  pressure: [lin("hpa", "hPa", 1, 1), lin("inhg", "inHg", HPA_INHG, 2), lin("mmhg", "mmHg", HPA_MMHG, 1)],
  height: [lin("ft", "ft", 1, 0), lin("m", "m", 1 / M_FT, 1), lin("fl", "FL", 100, 1)],
  distance: [lin("nm", "NM", KM_NM, 3), lin("km", "km", 1, 3), lin("sm", "SM", KM_SM, 3)],
  speed: [lin("kt", "kt", KM_NM, 1), lin("kmh", "km/h", 1, 1), lin("ms", "m/s", 3.6, 1), lin("mph", "mph", KM_SM, 1)],
  vs: [lin("fpm", "ft/min", 1, 0), lin("ms", "m/s", 60 / M_FT, 2)],
  // gradient: baza w %; ft/NM i kąt w stopniach
  gradient: [lin("pct", "%", 1, 2), lin("ftnm", "ft/NM", 100 / FT_NM, 1),
    fn("deg", "°", (d) => Math.tan(d * RAD) * 100, (p) => Math.atan(p / 100) / RAD, 2)],
  temperature: [lin("c", "°C", 1, 1), fn("f", "°F", (f) => (f - 32) * 5 / 9, (c) => c * 9 / 5 + 32, 1),
    fn("k", "K", (k) => k - 273.15, (c) => c + 273.15, 2)],
  mass: [lin("kg", "kg", 1, 1), lin("lb", "lb", KG_LB, 1), lin("t", "t", 1000, 3)],
};

// wartość v w jednostce fromId → {id: wartość} dla wszystkich jednostek grupy
export function convert(units, fromId, v) {
  const src = units.find((u) => u.id === fromId);
  const base = src.to(v);
  return Object.fromEntries(units.map((u) => [u.id, u.id === fromId ? v : u.from(base)]));
}

// --- Wysokość a poziom lotu przy QNH (ISA). Wysokościomierz z QNH pokazuje wysokość ciśnieniową (PA, przy 1013.25)
// pomniejszoną o wysokość ciśnieniową poziomu QNH: ALT = PA − PA(QNH), FL = PA / 100.
export const qnhLevelFt = (qnh) => 145366.45 * (1 - Math.pow(qnh / 1013.25, 0.190284));
export const altToPa = (altFt, qnh) => altFt + qnhLevelFt(qnh);
export const paToAlt = (paFt, qnh) => paFt - qnhLevelFt(qnh);

// --- ISA: temperatura, ciśnienie i prędkość dźwięku na wysokości ciśnieniowej (ft); tropopauza 36089 ft, wzory do FL650
export const TROPO_FT = 36089.24;
const A0 = 661.4786;   // prędkość dźwięku przy 15 °C, kt
const P0 = 1013.25;
const G_RL = 5.25588;                                  // g / (R × L) w troposferze ISA
const P_TROPO = P0 * Math.pow(216.65 / 288.15, G_RL);   // 226.32 hPa
export const isaTempK = (ft) => (ft < TROPO_FT ? 288.15 - 0.0019812 * ft : 216.65);
// troposfera: p = p0 × (T / T0)^(g/RL); nad tropopauzą T stała, p maleje wykładniczo (skala 20806 ft)
export const isaPressure = (ft) => (ft < TROPO_FT ? P0 * Math.pow(isaTempK(ft) / 288.15, G_RL)
  : P_TROPO * Math.exp(-(ft - TROPO_FT) / 20805.8));
export const soundKt = (ft) => A0 * Math.sqrt(isaTempK(ft) / 288.15);
export const machToTas = (m, ft) => m * soundKt(ft);
export const tasToMach = (tas, ft) => tas / soundKt(ft);
// CAS ↔ Mach z ciśnienia dynamicznego (przepływ ściśliwy, poddźwiękowy: M < 1)
export function casToMach(cas, ft) {
  const qc = P0 * (Math.pow(1 + 0.2 * (cas / A0) ** 2, 3.5) - 1);
  return Math.sqrt(5 * (Math.pow(qc / isaPressure(ft) + 1, 2 / 7) - 1));
}
export function machToCas(m, ft) {
  const qc = isaPressure(ft) * (Math.pow(1 + 0.2 * m * m, 3.5) - 1);
  return A0 * Math.sqrt(5 * (Math.pow(qc / P0 + 1, 2 / 7) - 1));
}

// --- Prędkość pionowa z gradientu: ft/min = ft/NM × GS / 60
export const fpmOf = (pct, gs) => (pct / 100) * FT_NM * gs / 60;
export const pctOf = (fpm, gs) => (fpm * 60 / gs) / FT_NM * 100;

// --- Czas w Polsce: CET (UTC+1), czas letni CEST (UTC+2) od ostatniej niedzieli marca do ostatniej niedzieli
// października, zmiana zawsze o 01:00 UTC (zasady UE). 0.12.5 (issue #18): zamiast kalkulatora UTC a czas polski
// dwa zegary obok siebie w nagłówku zakładki
const HOUR = 3600000;
const pad = (n) => String(n).padStart(2, "0");
// ostatnia niedziela miesiąca (month 0–11) o północy UTC
export function lastSunday(year, month) {
  const end = new Date(Date.UTC(year, month + 1, 0));
  return Date.UTC(year, month, end.getUTCDate() - end.getUTCDay());
}
// przesunięcie czasu w Polsce (h) w chwili UTC ms
export function plOffset(ms) {
  const y = new Date(ms).getUTCFullYear();
  return ms >= lastSunday(y, 2) + HOUR && ms < lastSunday(y, 9) + HOUR ? 2 : 1;
}
export const zoneOf = (off) => (off === 2 ? "CEST" : "CET");
const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
// chwila ms → {time "08:22:45", date "18.10.2026", day "SUN"} z pól UTC (dla Polski: ms przesunięte o offset)
function stamp(ms) {
  const d = new Date(ms);
  return { time: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`,
    date: `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}`, day: DAYS[d.getUTCDay()] };
}
// oba zegary: {utc: {time, date, day}, pl: {time, date, day, offset, zone}}
export function clocks(ms = Date.now()) {
  const off = plOffset(ms);
  return { utc: stamp(ms), pl: { ...stamp(ms + off * HOUR), offset: off, zone: zoneOf(off) } };
}

// --- Widok
// name: etykieta przed polem; "" = wiersz bez kolumny etykiet, null = pusta kolumna etykiet (pola w jednej linii
// z wierszami z etykietą w tej samej karcie)
const row = (u, name = "", ph = "") => `<label class="conv-row">${name !== "" ? `<span class="conv-name">${esc(name ?? "")}</span>` : ""}
  <input class="field" data-u="${esc(u.id)}" type="text" inputmode="decimal" autocomplete="off" spellcheck="false"${ph ? ` placeholder="${esc(ph)}"` : ""}>
  <span class="conv-unit">${esc(u.label)}</span></label>`;
const card = (key, title, body, note) => `<section class="card conv-card" data-k="${key}"><h3>${esc(title)}</h3>
  <div class="conv-rows">${body}</div><div class="conv-out"></div><p class="conv-note">${note}</p></section>`;
const U = (id, label) => ({ id, label });

export const CARDS = [
  card("pressure", "Pressure", GROUPS.pressure.map((u) => row(u)).join(""), "1 inHg = 33.8639 hPa · 1 mmHg = 1.333224 hPa"),
  card("height", "Height", GROUPS.height.map((u) => row(u)).join(""),
    "1 ft = 0.3048 m · FL = ft / 100 (pressure altitude at 1013.25 hPa)"),
  card("qnh", "Altitude and FL at QNH",
    row(U("qnh", "hPa"), "QNH", "e.g. 998") + row(U("alt", "ft AMSL"), "ALT") + row(U("fl", ""), "FL", "e.g. 70"),
    "ISA: QNH level = 145366.45 × (1 − (QNH / 1013.25)<sup>0.190284</sup>) ft pressure altitude; FL = (ALT + QNH level) / 100."
    + " Rule of thumb: approx. 27–30 ft per 1 hPa difference from 1013."),
  card("distance", "Distance", GROUPS.distance.map((u) => row(u)).join(""), "1 NM = 1.852 km · 1 SM (statute mile) = 1.609344 km"),
  card("speed", "Speed", GROUPS.speed.map((u) => row(u)).join(""), "1 kt = 1 NM/h = 1.852 km/h · 1 m/s = 3.6 km/h · 1 mph = 1.609344 km/h"),
  card("mach", "Mach, TAS and CAS at FL (ISA)",
    row(U("fl", ""), "FL", "e.g. 350") + row(U("mach", ""), "Mach", "e.g. 0.78") + row(U("tas", "kt"), "TAS") + row(U("cas", "kt"), "CAS"),
    "ISA: T = 15 °C − 1.98 °C / 1000 ft (−56.5 °C from FL361); a = 661.48 kt × √(T / 288.15 K); TAS = M × a;"
    + " CAS from impact pressure (compressible flow, M &lt; 1). No ISA deviation, no wind."),
  card("vs", "Vertical speed", GROUPS.vs.map((u) => row(u)).join(""), "1 ft/min = 0.00508 m/s · 1000 ft/min ≈ 5.08 m/s"),
  card("gradient", "Climb / descent gradient",
    GROUPS.gradient.map((u, i) => row(u, i ? null : "Grad")).join("") + row(U("gs", "kt"), "GS") + row(U("fpm", "ft/min"), "VS"),
    "ft/NM = % × 60.76 · angle = atan(% / 100) · ft/min = ft/NM × GS / 60 (3° ≈ 5.24 % ≈ 318 ft/NM ≈ 5.3 × GS)"),
  card("temperature", "Temperature", GROUPS.temperature.map((u) => row(u)).join(""), "°F = °C × 9/5 + 32 · K = °C + 273.15"),
  card("mass", "Mass", GROUPS.mass.map((u) => row(u)).join(""), "1 lb = 0.45359237 kg · 1 t = 1000 kg"),
];

// pola karty: wartość, zaznaczenie złej wartości, wpis wyniku
function fields(el) {
  const f = (id) => el.querySelector(`input[data-u="${id}"]`);
  const val = (id) => {
    const v = parseNum(f(id).value);
    f(id).classList.toggle("bad", Number.isNaN(v));
    return v;
  };
  const put = (id, v, dp) => { f(id).value = v === null ? "" : fmtNum(v, dp); f(id).classList.remove("bad"); };
  const ok = (v) => v !== null && !Number.isNaN(v);
  return { f, val, put, ok, out: el.querySelector(".conv-out") };
}

// zwykła grupa jednostek: wpis w jednym polu przelicza pozostałe; puste pole czyści kartę
export function linkGroup(el, units, after = () => {}) {
  const { val, put } = fields(el);
  el.addEventListener("input", (e) => {
    const id = e.target.dataset.u;
    if (!units.some((u) => u.id === id)) return;
    const v = val(id);
    if (Number.isNaN(v)) return;
    const out = v === null ? null : convert(units, id, v);
    units.forEach((u) => { if (u.id !== id) put(u.id, out ? out[u.id] : null, u.dp); });
    after(id);
  });
}

export function linkQnh(el) {
  const { f, val, put, ok, out } = fields(el);
  let src = "fl";   // ostatnio wpisane: ALT albo FL; zmiana QNH przelicza drugie z nich
  const update = () => {
    const q = val("qnh");
    const bad = Number.isNaN(q) || (ok(q) && (q < 850 || q > 1100));
    f("qnh").classList.toggle("bad", bad);
    if (!ok(q) || bad) {
      put(src === "alt" ? "fl" : "alt", null);
      out.textContent = q === null ? "Enter QNH." : Number.isNaN(q) ? "Invalid QNH." : "QNH out of range 850–1100 hPa.";
      return;
    }
    const lvl = qnhLevelFt(q);
    const v = val(src);
    if (!Number.isNaN(v)) {
      if (src === "alt") put("fl", v === null ? null : altToPa(v, q) / 100, 1);
      else put("alt", v === null ? null : paToAlt(v * 100, q), 0);
    }
    const d = 1013.25 - q;
    out.innerHTML = `QNH level: ${signed(lvl, 0)} ft pressure altitude · FL = (ALT ${lvl < 0 ? "−" : "+"} ${fmtNum(Math.abs(lvl), 0)} ft) / 100`
      + `<br>rule of thumb: ${signed(d, 2)} hPa × 27…30 ft = <span class="conv-nowrap">${signed(d * 27, 0)}…${signed(d * 30, 0)} ft</span>`;
  };
  el.addEventListener("input", (e) => {
    if (e.target.dataset.u === "alt" || e.target.dataset.u === "fl") src = e.target.dataset.u;
    update();
  });
  update();
}

export function linkMach(el) {
  const { val, put, ok, out } = fields(el);
  let src = "mach";   // ostatnio wpisana prędkość; zmiana FL przelicza pozostałe z niej
  const update = () => {
    const fl = val("fl");
    // bez poprawnego FL wyniki z poprzedniego FL znikają (zostaje tylko wpisana prędkość)
    const stop = (msg) => { ["mach", "tas", "cas"].forEach((id) => id !== src && put(id, null)); out.textContent = msg; };
    if (!ok(fl)) return stop("Enter FL.");
    if (fl < 0 || fl > 650) return stop("ISA formulas valid FL000–FL650.");
    const ft = fl * 100;
    const v = val(src);
    let m = null;
    if (!Number.isNaN(v)) {
      m = v === null ? null : src === "mach" ? v : src === "tas" ? tasToMach(v, ft) : casToMach(v, ft);
      if (src !== "mach") put("mach", m, 3);
      if (src !== "tas") put("tas", m === null ? null : machToTas(m, ft), 0);
      if (src !== "cas") put("cas", m === null || m >= 1 ? null : machToCas(m, ft), 0);
    }
    out.textContent = `ISA at FL${fmtNum(fl, 0).padStart(3, "0")}: ${signed(isaTempK(ft) - 273.15, 1)} °C · a = ${fmtNum(soundKt(ft), 0)} kt`
      + ` · p = ${fmtNum(isaPressure(ft), 1)} hPa${m >= 1 ? " · M ≥ 1: CAS outside the formula range" : ""}`;
  };
  el.addEventListener("input", (e) => {
    if (["mach", "tas", "cas"].includes(e.target.dataset.u)) src = e.target.dataset.u;
    update();
  });
  update();
}

// gradient (%, ft/NM, °) i VS przy danej GS: wpisany gradient liczy VS, wpisana VS liczy gradient; zmiana GS
// przelicza to z nich, które nie było wpisane ostatnio. Bez poprawnej GS (VS: GS > 0) wynik znika, a nie zostaje
// policzony z poprzedniej GS
export function linkGradient(el) {
  const { val, put, ok } = fields(el);
  const units = GROUPS.gradient;
  let src = "grad";
  const update = () => {
    const gs = val("gs");
    if (src === "grad") {
      const p = val("pct");
      put("fpm", ok(p) && ok(gs) ? fpmOf(p, gs) : null, 0);
      return;
    }
    const fpm = val("fpm");
    const all = ok(fpm) && ok(gs) && gs > 0 ? convert(units, "pct", pctOf(fpm, gs)) : null;
    units.forEach((u) => put(u.id, all ? all[u.id] : null, u.dp));
  };
  linkGroup(el, units, () => { src = "grad"; update(); });
  el.addEventListener("input", (e) => {
    const id = e.target.dataset.u;
    if (id === "fpm") src = "fpm";
    if (id === "fpm" || id === "gs") update();
  });
}

// karty w czterech stałych kolumnach (wysokości kolumn zbliżone, cała strona bez przewijania przy 768 px wysokości);
// stały przydział, bo kolumny CSS wyrównywane automatycznie przenosiłyby kartę, w której się pisze (wynik QNH, ISA)
export const COLUMNS = [["pressure", "height", "distance"], ["qnh", "speed"], ["mach", "vs"], ["gradient", "temperature", "mass"]];
const cardOf = (k) => CARDS.find((c) => c.includes(`data-k="${k}"`));
export const gridHtml = () => COLUMNS.map((ks) => `<div class="conv-col">${ks.map(cardOf).join("")}</div>`).join("");

// zegary w nagłówku: UTC i czas w Polsce (CET/CEST) obok siebie, co sekundę
export const clocksHtml = () => `<div class="conv-clocks">
  <div class="conv-clock" title="Coordinated Universal Time"><span class="conv-ck-l">UTC</span><b class="conv-ck-t" data-ck="utc"></b>
    <span class="conv-ck-s" data-ck="utc-s"></span></div>
  <div class="conv-clock" title="Poland local time: CET = UTC+1, summer time CEST = UTC+2 (last Sunday of March to last Sunday of October, change at 01:00 UTC)">
    <span class="conv-ck-l">POLAND (LT)</span><b class="conv-ck-t" data-ck="pl"></b><span class="conv-ck-s" data-ck="pl-s"></span></div></div>`;
export function drawClocks(box, ms = Date.now()) {
  const c = clocks(ms);
  const set = (k, t) => { const e = box.querySelector(`[data-ck="${k}"]`); if (e.textContent !== t) e.textContent = t; };
  set("utc", `${c.utc.time}Z`);
  set("utc-s", `${c.utc.day} ${c.utc.date}`);
  set("pl", c.pl.time);
  set("pl-s", `${c.pl.zone} · UTC+${c.pl.offset}${c.pl.date === c.utc.date ? "" : ` · ${c.pl.day} ${c.pl.date}`}`);
}

export default {
  mount(root) {
    const pane = h(`<div class="pane conv-pane">
      <div class="conv-head"><h2 class="title">Unit conversion</h2>
        <span class="hint conv-hint" title="Type a value in any field: the other fields of the card are converted at once. Comma or dot as the decimal separator.">Type in any field – the card converts instantly.</span>
        ${clocksHtml()}</div>
      <div class="conv-grid">${gridHtml()}</div></div>`);
    root.append(pane);
    const el = (k) => pane.querySelector(`.conv-card[data-k="${k}"]`);
    ["pressure", "height", "distance", "speed", "vs", "temperature", "mass"].forEach((k) => linkGroup(el(k), GROUPS[k]));
    linkQnh(el("qnh"));
    linkMach(el("mach"));
    linkGradient(el("gradient"));
    const box = pane.querySelector(".conv-clocks");
    drawClocks(box);
    // co sekundę tylko wtedy, gdy zakładka jest na ekranie
    setInterval(() => { if (root.classList.contains("active") && !document.hidden) drawClocks(box); }, 1000);
    return { activate: () => drawClocks(box) };
  },
};
