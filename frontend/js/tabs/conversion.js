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
// października, zmiana zawsze o 01:00 UTC (zasady UE)
const MIN = 60000, HOUR = 3600000;
const pad = (n) => String(n).padStart(2, "0");
// "14:30", "1430", "14.30", "9:05", "1430Z" → minuta doby; zły tekst → null
export function parseTime(s) {
  const m = String(s ?? "").trim().replace(/\s*(z|utc)$/i, "").match(/^(\d{1,2})[:.\s]?(\d{2})$/);
  if (!m) return null;
  const hh = Number(m[1]), mm = Number(m[2]);
  return hh < 24 && mm < 60 ? hh * 60 + mm : null;
}
// "2026-10-25" albo "25.10.2026" → północ UTC tego dnia (ms); zły tekst albo nieistniejący dzień → null
export function parseDay(s) {
  const t = String(s ?? "").trim();
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/), y, mo, d;
  if (m) [y, mo, d] = m.slice(1).map(Number);
  else if ((m = t.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/))) [d, mo, y] = m.slice(1).map(Number);
  else return null;
  const ms = Date.UTC(y, mo - 1, d);
  const back = new Date(ms);
  return back.getUTCFullYear() === y && back.getUTCMonth() === mo - 1 && back.getUTCDate() === d ? ms : null;
}
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
export const zoneOf = (off) => (off === 2 ? "CEST, UTC+2" : "CET, UTC+1");
const parts = (ms) => { const d = new Date(ms); return { date: d.toISOString().slice(0, 10), time: d.toISOString().slice(11, 16) }; };
// UTC → czas w Polsce: {date, time, offset, zone} albo null przy złej dacie / godzinie
export function utcToPl(day, time) {
  const d = parseDay(day), t = parseTime(time);
  if (d === null || t === null) return null;
  const ms = d + t * MIN, off = plOffset(ms);
  return { ...parts(ms + off * HOUR), offset: off, zone: zoneOf(off) };
}
// czas w Polsce → UTC. Przy zmianie czasu: note "gap" (godziny 02:00–02:59 w dniu przejścia na czas letni nie ma,
// liczymy jak CET) albo "twice" (02:00–02:59 w dniu powrotu do CET jest dwa razy: wynik CEST, w alt drugi raz CET)
export function plToUtc(day, time) {
  const d = parseDay(day), t = parseTime(time);
  if (d === null || t === null) return null;
  const local = d + t * MIN;
  const ok = [2, 1].filter((off) => plOffset(local - off * HOUR) === off);
  const off = ok[0] ?? 1;
  const out = { ...parts(local - off * HOUR), offset: off, zone: zoneOf(off), note: ok.length ? (ok.length > 1 ? "twice" : "") : "gap" };
  if (ok.length > 1) out.alt = parts(local - HOUR);
  return out;
}
export const nowUtc = (now = new Date()) => ({ date: now.toISOString().slice(0, 10), time: `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}` });

// --- Widok
const row = (u, name = "", ph = "") => `<label class="conv-row">${name ? `<span class="conv-name">${esc(name)}</span>` : ""}
  <input class="field" data-u="${esc(u.id)}" type="text" inputmode="decimal" autocomplete="off" spellcheck="false"${ph ? ` placeholder="${esc(ph)}"` : ""}>
  <span class="conv-unit">${esc(u.label)}</span></label>`;
const card = (key, title, body, note) => `<section class="card conv-card" data-k="${key}"><h3>${esc(title)}</h3>
  <div class="conv-rows">${body}</div><div class="conv-out"></div><p class="conv-note">${note}</p></section>`;
const U = (id, label) => ({ id, label });

const CARDS = [
  card("pressure", "Ciśnienie", GROUPS.pressure.map((u) => row(u)).join(""), "1 inHg = 33.8639 hPa · 1 mmHg = 1.333224 hPa"),
  card("height", "Wysokość", GROUPS.height.map((u) => row(u)).join(""),
    "1 ft = 0.3048 m · FL = ft / 100 (wysokość ciśnieniowa przy 1013.25 hPa)"),
  card("qnh", "Wysokość a FL przy QNH",
    row(U("qnh", "hPa"), "QNH", "np. 998") + row(U("alt", "ft AMSL"), "ALT") + row(U("fl", ""), "FL", "np. 70"),
    "ISA: poziom QNH = 145366.45 × (1 − (QNH / 1013.25)<sup>0.190284</sup>) ft wysokości ciśnieniowej; FL = (ALT + poziom QNH) / 100."
    + " Reguła kciuka: ok. 27–30 ft na 1 hPa różnicy od 1013."),
  card("distance", "Odległość", GROUPS.distance.map((u) => row(u)).join(""), "1 NM = 1.852 km · 1 SM (mila lądowa) = 1.609344 km"),
  card("speed", "Prędkość", GROUPS.speed.map((u) => row(u)).join(""), "1 kt = 1 NM/h = 1.852 km/h · 1 m/s = 3.6 km/h · 1 mph = 1.609344 km/h"),
  card("mach", "Mach, TAS i CAS na FL (ISA)",
    row(U("fl", ""), "FL", "np. 350") + row(U("mach", ""), "Mach", "np. 0.78") + row(U("tas", "kt"), "TAS") + row(U("cas", "kt"), "CAS"),
    "ISA: T = 15 °C − 1.98 °C / 1000 ft (od FL361 −56.5 °C); a = 661.48 kt × √(T / 288.15 K); TAS = M × a;"
    + " CAS z ciśnienia dynamicznego (przepływ ściśliwy, M &lt; 1). Bez odchyłki od ISA i bez wiatru."),
  card("vs", "Prędkość pionowa", GROUPS.vs.map((u) => row(u)).join(""), "1 ft/min = 0.00508 m/s · 1000 ft/min ≈ 5.08 m/s"),
  card("gradient", "Gradient wznoszenia / zniżania",
    GROUPS.gradient.map((u) => row(u)).join("") + row(U("gs", "kt"), "GS") + row(U("fpm", "ft/min"), "VS"),
    "ft/NM = % × 60.76 · kąt = atan(% / 100) · ft/min = ft/NM × GS / 60 (3° ≈ 5.24 % ≈ 318 ft/NM ≈ 5.3 × GS)"),
  card("temperature", "Temperatura", GROUPS.temperature.map((u) => row(u)).join(""), "°F = °C × 9/5 + 32 · K = °C + 273.15"),
  card("mass", "Masa", GROUPS.mass.map((u) => row(u)).join(""), "1 lb = 0.45359237 kg · 1 t = 1000 kg"),
  card("time", "Czas: UTC a czas w Polsce",
    `<label class="conv-row"><span class="conv-name">UTC</span><input class="field conv-day" data-u="utc-day" type="date">
      <input class="field conv-time" data-u="utc" type="text" inputmode="numeric" autocomplete="off" placeholder="hh:mm"></label>
    <label class="conv-row"><span class="conv-name">Polska</span><input class="field conv-day" data-u="pl-day" type="date">
      <input class="field conv-time" data-u="pl" type="text" inputmode="numeric" autocomplete="off" placeholder="hh:mm"></label>
    <div class="conv-row"><button type="button" class="btn conv-now">Teraz</button></div>`,
    "CET = UTC+1, czas letni CEST = UTC+2 od ostatniej niedzieli marca do ostatniej niedzieli października; zmiana o 01:00 UTC."),
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
function linkGroup(el, units, after = () => {}) {
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

function linkQnh(el) {
  const { f, val, put, ok, out } = fields(el);
  let src = "fl";   // ostatnio wpisane: ALT albo FL; zmiana QNH przelicza drugie z nich
  const update = () => {
    const q = val("qnh");
    const bad = ok(q) && (q < 850 || q > 1100);
    f("qnh").classList.toggle("bad", bad);
    if (!ok(q) || bad) {
      put(src === "alt" ? "fl" : "alt", null);
      out.textContent = q === null ? "Wpisz QNH." : "QNH poza zakresem 850–1100 hPa.";
      return;
    }
    const lvl = qnhLevelFt(q);
    const v = val(src);
    if (!Number.isNaN(v)) {
      if (src === "alt") put("fl", v === null ? null : altToPa(v, q) / 100, 1);
      else put("alt", v === null ? null : paToAlt(v * 100, q), 0);
    }
    const d = 1013.25 - q;
    out.innerHTML = `Poziom QNH: ${signed(lvl, 0)} ft wysokości ciśnieniowej · FL = (ALT ${lvl < 0 ? "−" : "+"} ${fmtNum(Math.abs(lvl), 0)} ft) / 100`
      + `<br>reguła kciuka: ${signed(d, 2)} hPa × 27…30 ft = <span class="conv-nowrap">${signed(d * 27, 0)}…${signed(d * 30, 0)} ft</span>`;
  };
  el.addEventListener("input", (e) => {
    if (e.target.dataset.u === "alt" || e.target.dataset.u === "fl") src = e.target.dataset.u;
    update();
  });
  update();
}

function linkMach(el) {
  const { val, put, ok, out } = fields(el);
  let src = "mach";   // ostatnio wpisana prędkość; zmiana FL przelicza pozostałe z niej
  const update = () => {
    const fl = val("fl");
    // bez poprawnego FL wyniki z poprzedniego FL znikają (zostaje tylko wpisana prędkość)
    const stop = (msg) => { ["mach", "tas", "cas"].forEach((id) => id !== src && put(id, null)); out.textContent = msg; };
    if (!ok(fl)) return stop("Wpisz FL.");
    if (fl < 0 || fl > 650) return stop("Wzory ISA w kalkulatorze: FL000–FL650.");
    const ft = fl * 100;
    const v = val(src);
    let m = null;
    if (!Number.isNaN(v)) {
      m = v === null ? null : src === "mach" ? v : src === "tas" ? tasToMach(v, ft) : casToMach(v, ft);
      if (src !== "mach") put("mach", m, 3);
      if (src !== "tas") put("tas", m === null ? null : machToTas(m, ft), 0);
      if (src !== "cas") put("cas", m === null || m >= 1 ? null : machToCas(m, ft), 0);
    }
    out.textContent = `ISA na FL${fmtNum(fl, 0).padStart(3, "0")}: ${signed(isaTempK(ft) - 273.15, 1)} °C · a = ${fmtNum(soundKt(ft), 0)} kt`
      + ` · p = ${fmtNum(isaPressure(ft), 1)} hPa${m >= 1 ? " · M ≥ 1: CAS poza zakresem wzoru" : ""}`;
  };
  el.addEventListener("input", (e) => {
    if (["mach", "tas", "cas"].includes(e.target.dataset.u)) src = e.target.dataset.u;
    update();
  });
  update();
}

// gradient (%, ft/NM, °) i VS przy danej GS: wpisany gradient liczy VS, wpisana VS liczy gradient; zmiana GS
// przelicza to z nich, które nie było wpisane ostatnio
function linkGradient(el) {
  const { val, put, ok } = fields(el);
  const units = GROUPS.gradient;
  let src = "grad";
  const update = () => {
    const gs = val("gs");
    if (Number.isNaN(gs)) return;
    if (src === "grad") {
      const p = val("pct");
      if (!Number.isNaN(p)) put("fpm", ok(p) && ok(gs) ? fpmOf(p, gs) : null, 0);
      return;
    }
    const fpm = val("fpm");
    if (!ok(fpm) || !ok(gs) || gs <= 0) return;
    const all = convert(units, "pct", pctOf(fpm, gs));
    units.forEach((u) => put(u.id, all[u.id], u.dp));
  };
  linkGroup(el, units, () => { src = "grad"; update(); });
  el.addEventListener("input", (e) => {
    const id = e.target.dataset.u;
    if (id === "fpm") src = "fpm";
    if (id === "fpm" || id === "gs") update();
  });
}

function linkTime(el) {
  const { f, out } = fields(el);
  // pod polami strefa czasu w Polsce w tej chwili i ewentualna uwaga o zmianie czasu
  const show = (r, from) => {
    if (from === "utc" && r) { f("pl-day").value = r.date; f("pl").value = r.time; }
    if (from === "pl" && r) { f("utc-day").value = r.date; f("utc").value = r.time; }
    const note = from === "utc" || !r ? "" : r.note === "gap" ? "Tej godziny w Polsce nie ma: zegary przestawia się z 02:00 na 03:00 (liczone jak CET)."
      : r.note === "twice" ? `Ta godzina jest w Polsce dwa razy: ${r.time} UTC (CEST) i ${r.alt.time} UTC (CET).` : "";
    out.innerHTML = r ? `Polska: <span class="conv-zone">${esc(r.zone)}</span>${note ? `<br>${esc(note)}` : ""}` : "";
  };
  const fromUtc = () => {
    const r = utcToPl(f("utc-day").value, f("utc").value);
    f("utc").classList.toggle("bad", !!f("utc").value.trim() && parseTime(f("utc").value) === null);
    show(r, "utc");
  };
  const fromPl = () => {
    const r = plToUtc(f("pl-day").value, f("pl").value);
    f("pl").classList.toggle("bad", !!f("pl").value.trim() && parseTime(f("pl").value) === null);
    show(r, "pl");
  };
  const now = () => { const n = nowUtc(); f("utc-day").value = n.date; f("utc").value = n.time; fromUtc(); };
  el.addEventListener("input", (e) => {
    const id = e.target.dataset.u;
    if (id === "utc" || id === "utc-day") fromUtc();
    if (id === "pl" || id === "pl-day") fromPl();
  });
  el.querySelector(".conv-now").addEventListener("click", now);
  now();
}

export default {
  mount(root) {
    const pane = h(`<div class="pane conv-pane">
      <div class="conv-head"><h2 class="title">Przeliczanie jednostek</h2>
        <span class="hint">Wpisz wartość w dowolne pole – pozostałe pola karty przeliczają się od razu. Przecinek albo kropka.</span></div>
      <div class="conv-grid">${CARDS.join("")}</div></div>`);
    root.append(pane);
    const el = (k) => pane.querySelector(`.conv-card[data-k="${k}"]`);
    ["pressure", "height", "distance", "speed", "vs", "temperature", "mass"].forEach((k) => linkGroup(el(k), GROUPS[k]));
    linkQnh(el("qnh"));
    linkMach(el("mach"));
    linkGradient(el("gradient"));
    linkTime(el("time"));
  },
};
