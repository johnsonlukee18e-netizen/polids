// Wiatr: wspólne funkcje bez DOM i bez zapytań (AWALON, AERODROME › INFO; testy w Node).
// Zapis wiatru "310/14G26", składowe względem pasa "H13" / "T13" (w plecy) i "5R" / "5L", punkt podejścia pasa
// oraz klasy prędkości, osie i strzałki wykresu profilu wiatru AWALON (kolory klas w css/awalon.css).

const p2 = (v, n) => String(v).padStart(n, "0");
export const windVec = (w) => (!w || w.speed === null || w.speed === undefined ? "\u2013"
  : `${w.variable ? "VRB" : p2(w.dir ?? 0, 3)}/${p2(w.speed, 2)}${w.gust ? "G" + w.gust : ""}`);
// składowe zawsze zaokrąglane po wartości bezwzględnej (-13.5 -> T14, 13.5 -> H14), wszędzie tak samo
export const kt = (v) => Math.round(Math.abs(v));
export const hwTxt = (v) => (v === null || v === undefined ? "\u2013" : v < 0 && kt(v) ? `<span class="tw">T${kt(v)}</span>` : `H${kt(v)}`);
export const xwTxt = (v) => (v === null || v === undefined ? "\u2013" : kt(v) === 0 ? "0" : `${kt(v)}${v > 0 ? "R" : "L"}`);
// "2026-10-06T18:00Z" -> "18:00Z 06.10"
export const validTxt = (t) => (t ? `${t.slice(11, 16)}Z ${t.slice(8, 10)}.${t.slice(5, 7)}` : "\u2013");
// uwaga pod tabelą wiatru: ważność prognozy; przy błędzie pobrania tylko komunikat błędu (bez drugiego "unavailable")
export const forecastNote = (aw) => (aw?.valid ? `Forecast for ${validTxt(aw.valid)}, fetched ${aw.fetched || "\u2013"}.`
  : aw?.model_error ? "" : "Forecast unavailable.");
// punkt podejścia bez nazwy: na przedłużeniu osi pasa, w którym ścieżka 3° osiąga 3000 ft
export const CL3 = "CL 3\u00b0";
// odległość od progu zawsze z jedną cyfrą po przecinku ("3.0 NM", nie "3 NM" obok "4.9 NM")
export const nm = (v) => (v === null || v === undefined ? "\u2013" : Number(v).toFixed(1));
export const pointTip = (r) => `RWY ${r.designator}: ${r.fix ? r.fix + ", " : ""}${r.method_label}, ${nm(r.dist_nm)} NM from THR`
  + `, 3\u00b0 path \u2248 ${r.path_ft} ft${r.approaches?.length ? `\nApproaches: ${r.approaches.join(", ")}` : ""}`;

// --- AWALON: profil wiatru 0–10 000 ft

// klasy prędkości od najsilniejszej (kolejność legendy jak w PANDORZE); dolna granica w klasie, "> 60" bez 60 kt
export const SPEED_BANDS = [
  { id: "s60", label: ">60" },
  { id: "s40", label: "40-60" },
  { id: "s30", label: "30-40" },
  { id: "s20", label: "20-30" },
  { id: "s15", label: "15-20" },
  { id: "s10", label: "10-15" },
  { id: "s0", label: "0-10" },
];
export const NO_DATA = { id: "none", label: "No data" };
export function bandOf(speed) {
  if (speed === null || speed === undefined || Number.isNaN(Number(speed))) return NO_DATA.id;
  const s = Number(speed);
  return s > 60 ? "s60" : s >= 40 ? "s40" : s >= 30 ? "s30" : s >= 20 ? "s20" : s >= 15 ? "s15" : s >= 10 ? "s10" : "s0";
}
// koniec osi prędkości: co najmniej 40 kt, wyżej pełne dziesiątki; 7 podziałek co 1/6 osi w pełnych węzłach
// (40 kt: 0 6 13 20 26 33 40 jak w PANDORZE)
export const axisMax = (maxSpeed) => Math.max(40, Math.ceil((Number(maxSpeed) || 0) / 10) * 10);
export const axisTicks = (max) => Array.from({ length: 7 }, (_, i) => Math.floor((max * i) / 6));
// podpis osi wysokości: 0, 1K … 10K; wiersz 0 ft w tabelach to SFC (wiatr przy ziemi)
export const altLabel = (ft) => (ft ? `${ft / 1000}K` : "0");
export const rowLabel = (ft) => (ft ? altLabel(ft) : "SFC");
// obrót grotu rysowanego w stronę północy: wiatr "z" kierunku dir, grot w stronę, w którą wieje (z wiatrem);
// bez kierunku (VRB, cisza, brak danych) bez grotu
export const arrowRot = (dir, speed = 1) => (dir === null || dir === undefined || !dir || !speed ? null : (Number(dir) + 180) % 360);
// "310°/14 kt" (skąd wieje), z porywem "310°/14 kt G26"
export const windTip = (r) => (!r || r.speed === null || r.speed === undefined ? "No data"
  : `${r.variable ? "VRB" : r.dir ? p2(r.dir, 3) + "\u00b0" : "CALM"}/${r.speed} kt${r.gust ? ` G${r.gust}` : ""}`);
export const dirTxt = (r) => (!r || r.speed === null || r.speed === undefined ? "\u2013"
  : r.variable ? "VRB" : r.dir ? `${p2(r.dir, 3)}\u00b0` : "CALM");
export const angleTxt = (d) => (d === null || d === undefined ? "\u2013" : `${p2(d, 3)}\u00b0`);
export const speedTxt = (s) => (s === null || s === undefined ? "\u2013" : `${s} kt`);
// macierz ALL: wiersze od 10K u góry do SFC na dole, w każdym wierszu wiatr kolejnych lotnisk (null = brak wiersza)
export function matrixRows(data) {
  const alts = [...(data?.alts_ft || [])].sort((a, b) => b - a);
  const ads = data?.aerodromes || [];
  return alts.map((alt) => ({ alt_ft: alt, cells: ads.map((a) => (a.profile || []).find((r) => r.alt_ft === alt) || null) }));
}
// największa prędkość profilu (koniec osi wykresu)
export const maxSpeed = (profile) => Math.max(0, ...(profile || []).map((r) => r.speed || 0));
// "Today, 16:00 UTC" albo "27.10, 23:00 UTC" (inna doba UTC niż teraz)
export function forecastFor(valid, now = Date.now()) {
  if (!valid) return "\u2013";
  const today = new Date(now).toISOString().slice(0, 10);
  return `${valid.slice(0, 10) === today ? "Today" : `${valid.slice(8, 10)}.${valid.slice(5, 7)}`}, ${valid.slice(11, 16)} UTC`;
}
