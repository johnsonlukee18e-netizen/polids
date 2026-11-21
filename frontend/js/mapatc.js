// MAP: kto obsługuje przestrzeń w punkcie kursora (podziałka wysokości w dymku) i plakietki CTR bez dublowania.
// Czyste funkcje bez Leafleta (testy w Node: backend/tests/test_map_scale.py).
import { esc } from "./api.js";

const DASH = "\u2013";
// granica pionowa jak altLabel w airspace.js: GND, stopy do 6500 ft, wyżej poziom lotu
const altText = (ft) => (!ft ? "GND" : ft <= 6500 ? `${ft} ft` : "FL" + String(Math.round(ft / 100)).padStart(3, "0"));
const keys = (who) => (who || []).map((w) => w.key).sort().join("|");

// 0.14.0 (issue #28, właściciel projektu: "bardzo długie, niepotrzebne objaśnienia; wystarczy prosta podziałka wysokości z id
// kontrolera, imieniem i nazwiskiem oraz wysokościami granicznymi"). Dymek po najechaniu na przestrzeń zamiast wierszy
// z rodzajem, nazwą, ID, zakresem, częstotliwością i "since": cała kolumna przestrzeni w punkcie kursora, od góry.
// slices: wycinki w tym punkcie {lo, hi: granice w stopach, size: pole (mniejsze = dokładniejsze, np. CTR w TMA),
// who: [{key: znak, id: nazwa stanowiska jak na mapie, name: imię i nazwisko, sim, color}] (pusta = nieobsadzony)}.
// Wynik od góry: {alt: ft} (granica) i {lo, hi, who} (pasmo między granicami). Pasmo obsługują wszyscy z wycinków,
// które je pokrywają (od najmniejszego obszaru); gdy ktoś je obsługuje, nieobsadzone wycinki w nim się nie liczą.
// Sąsiednie pasma z tymi samymi obsługującymi razem (bez granicy między nimi); bez żadnego wycinka (przerwa)
// tylko dwie granice, bez pasma.
export function altScale(slices) {
  const ok = (slices || []).filter((s) => Number.isFinite(s?.lo) && Number.isFinite(s?.hi) && s.hi > s.lo);
  const cuts = [...new Set(ok.flatMap((s) => [s.lo, s.hi]))].sort((a, b) => b - a);
  const bands = [];
  for (let i = 0; i < cuts.length - 1; i += 1) {
    const hi = cuts[i], lo = cuts[i + 1];
    const cover = ok.filter((s) => s.lo <= lo && s.hi >= hi).sort((a, b) => (a.size ?? 0) - (b.size ?? 0));
    if (!cover.length) continue;
    const who = [];
    cover.forEach((s) => (s.who || []).forEach((w) => { if (w?.key && !who.some((x) => x.key === w.key)) who.push(w); }));
    const last = bands[bands.length - 1];
    if (last && last.lo === hi && keys(last.who) === keys(who)) last.lo = lo;
    else bands.push({ hi, lo, who });
  }
  const out = [];
  bands.forEach((b) => {
    if (out[out.length - 1]?.alt !== b.hi) out.push({ alt: b.hi });
    out.push(b, { alt: b.lo });
  });
  return out;
}

// HTML dymka z altScale: granica w osobnej linijce, pod nią obsługujący pasma (nazwa stanowiska, częstotliwość
// i imię i nazwisko, jak panel Positions z obrazka właściciela projektu w issue #28;
// symulacja: SYM; nieobsadzone: "–"); kreska po lewej w kolorze stanowiska jak jego obszar na mapie. lv: rysowany
// poziom (null = wszystkie): pasmo z tym poziomem wyróżnione. alt: zapis granicy (altLabel z airspace.js).
export function altScaleHtml(rows, { lv = null, alt = altText } = {}) {
  if (!rows?.length) return "";
  return `<table class="as-scale">${rows.map((r) => {
    if (r.alt !== undefined) return `<tr class="sc-a"><td colspan="3">${esc(alt(r.alt))}</td></tr>`;
    const at = lv !== null && r.lo <= lv && lv < r.hi ? " at" : "";
    if (!r.who.length) return `<tr class="sc-b${at} none"><td class="sc-id">${DASH}</td><td></td><td></td></tr>`;
    return r.who.map((w) => `<tr class="sc-b${at}"><td class="sc-id"${/^#[0-9a-f]{3,8}$/i.test(w.color || "") ? ` style="border-left-color:${w.color}"` : ""}>`
      + `${esc(w.id)}</td><td class="sc-f">${esc(w.freq || "")}</td><td class="sc-n">${w.sim ? `<span class="pos-sim">SYM</span>` : esc(w.name || "")}</td></tr>`).join("");
  }).join("")}</table>`;
}

// 0.14.0 (issue #28: "podwójne tabliczki pozycji CTR"). Na MAP kontroler ACC EPWW miał dwie tabliczki: etykietę obszaru
// stanowiska (nazwa i częstotliwość, drawOwned) i plakietkę "CTR EPWW-x" granicy FIR z VATSpy (online_firs: granica wg
// stanowiska z częstotliwości), np. "EPWW S 123.625" i tuż pod nią "CTR EPWW-S". Plakietka CTR zostaje tylko dla tych,
// których obszaru nie ma na mapie (warstwa ACC wyłączona, inny poziom, obsada wyłączona).
// firs: {id FIR-u: [kontrolerzy]} z zestawu aktywnego; labelled: kontrolerzy z etykietą obszaru na mapie. Wynik: FIR-y
// z prefiksem (EPWW, EPWW-*) bez kontrolerów z etykietą i bez tych na częstotliwości stanowiska z etykietą (uczeń
// i instruktor: jedna tabliczka); każdy kontroler na jednej plakietce (UIR obejmuje FIR i wszystkie jego sektory:
// zostaje plakietka całego FIR-u). FIR bez nikogo odpada.
export function ctrBadges(firs, labelled = [], prefix = "EPWW") {
  const cs = new Set((labelled || []).map((c) => c?.callsign).filter(Boolean));
  const fq = new Set((labelled || []).map((c) => c?.frequency).filter(Boolean));
  const seen = new Set(), out = {};
  Object.keys(firs || {}).filter((id) => id === prefix || id.startsWith(prefix + "-"))
    .sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0))
    .forEach((id) => {
      const list = (Array.isArray(firs[id]) ? firs[id] : [])
        .filter((c) => c?.callsign && !cs.has(c.callsign) && !(c.frequency && fq.has(c.frequency)) && !seen.has(c.callsign));
      list.forEach((c) => seen.add(c.callsign));
      if (list.length) out[id] = list;
    });
  return out;
}
