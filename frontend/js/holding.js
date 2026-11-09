// OTHER › HOLDING (0.13.2, issue #27): ściąga kontrolera do wydawania holdingu wg FLIRT (Fix, Level, Inbound track,
// Right/left turns, Time = czas odcinka od trawersu; na końcu zawsze EXPECT ... AT (czas)), frazeologia holdingu
// i opóźnienia z Doc 4444 (12.3.1.13, approach: EXPECTED APPROACH TIME, DELAY NOT DETERMINED), rysunek holdingu
// (fix, odcinek dolotowy i odlotowy, zakręty w prawo, trawers, strona holdingu i strona przeciwna, czas 1 min do FL140
// włącznie i 1,5 min wyżej), rysunek sektorów wejścia (linia 70° przez fix, sektory 1 PARALLEL 110°, 2 OFFSET 70°,
// 3 DIRECT 180°, ±5° tolerancji na granicach) i trzy małe rysunki wejść, tabela maksymalnych prędkości z PANS-OPS
// (Doc 8168: do FL140 230 kt, do FL200 240 kt, do FL340 265 kt, wyżej M0.83; w turbulencji 280 kt albo M0.80, CAT A/B
// 170 kt). Wartości sprawdzone w notatkach rundy 18 (SKYbrary, IVAO, Doc 4444, Doc 8168), na ekranie bez nazw dokumentów.
// Rysunki: wbudowane SVG, kolory ze zmiennych CSS (other.css), cienkie linie bez skalowania grubości (non-scaling-stroke),
// viewBox szerokości ok. 520 jednostek = szerokość kolumny strony przy 1920 i 1366 px, więc napisy mają ok. 12-13 px.
// Strona bez danych z serwera i bez timerów.

// FLIRT: [litera, element, co powiedzieć]; nawiasy jak we frazeologii: (fix) = do wstawienia
export const FLIRT = [
  ["F", "Fix", "CLEARED TO (fix)"],
  ["L", "Level", "MAINTAIN (or CLIMB / DESCEND TO) (level)"],
  ["I", "Inbound track", "HOLD INBOUND TRACK (three digits) DEGREES"],
  ["R", "Right or left turns", "RIGHT (or LEFT) HAND PATTERN"],
  ["T", "Time outbound", "OUTBOUND TIME (number) MINUTES"],
];
// na końcu każdego holdingu: czas dalszej zgody albo podejścia
export const EXPECT = ["+", "Expect time", "EXPECT FURTHER CLEARANCE (or APPROACH CLEARANCE) AT (time)"];
export const EXAMPLE = "LOT3AB, CLEARED TO OKE, MAINTAIN FL80, HOLD INBOUND TRACK 330 DEGREES, RIGHT HAND PATTERN, "
  + "OUTBOUND TIME 1 MINUTE, EXPECT FURTHER CLEARANCE AT 1435";
// frazeologia: [kiedy, fraza]
export const PHRASES = [
  ["Published hold", "CLEARED TO (fix) [MAINTAIN (level)], HOLD AS PUBLISHED, EXPECT APPROACH CLEARANCE "
    + "(or FURTHER CLEARANCE) AT (time)"],
  ["Hold at a DME fix", "CLEARED TO THE (three digits) RADIAL OF THE (name) VOR AT (distance) DME FIX, MAINTAIN (level), "
    + "HOLD BETWEEN (distance) AND (distance) DME, RIGHT (or LEFT) HAND PATTERN, EXPECT FURTHER CLEARANCE AT (time)"],
  ["Pilot asks", "REQUEST HOLDING INSTRUCTIONS"],
  ["No delay", "NO DELAY EXPECTED"],
  ["Delay", "EXPECTED APPROACH TIME (time)"],
  ["New time", "REVISED EXPECTED APPROACH TIME (time)"],
  ["Delay unknown", "DELAY NOT DETERMINED (reason)"],
];
export const PHRASE_NOTE = "Delay of 10 minutes or more: give an expected approach time. Holding for the approach: "
  + "EXPECT APPROACH CLEARANCE AT; elsewhere: EXPECT FURTHER CLEARANCE AT.";
// maksymalne prędkości holdingu (IAS): [poziomy, normalnie, w turbulencji]
export const SPEEDS = [
  ["At or below FL140", "230 kt", "280 kt"],
  ["Above FL140 to FL200", "240 kt", "280 kt or M0.80, whichever is less"],
  ["Above FL200 to FL340", "265 kt", "280 kt or M0.80, whichever is less"],
  ["Above FL340", "M0.83", "M0.83"],
];
export const SPEED_NOTES = [
  "Holds for category A and B aircraft only: 170 kt at or below FL140.",
  "Turbulence speeds only after ATC clearance, unless the hold is published for them.",
];
// zasady rysunku holdingu (pod rysunkiem)
export const PATTERN_NOTES = [
  "Standard pattern: right turns. Left turns only when instructed (LEFT HAND PATTERN) or published.",
  "Outbound time: 1 min at or below FL140, 1.5 min above FL140, or a DME distance instead of time.",
  "Outbound timing starts over or abeam the fix, whichever is later.",
  "Turns: 25\u00b0 bank or 3\u00b0 per second, whichever needs the lesser bank.",
];
// wejścia: [nr, nazwa, opis]
export const ENTRIES = [
  ["1", "Parallel", "At the fix turn left onto the outbound heading, on the non-holding side, for the outbound time. "
    + "Turn left onto the holding side to intercept the inbound track or return to the fix. At the fix turn right "
    + "into the pattern."],
  ["2", "Offset", "At the fix turn onto a track 30\u00b0 from the reciprocal of the inbound track, on the holding side, "
    + "for the outbound time. Turn right to intercept the inbound track. At the fix turn right into the pattern."],
  ["3", "Direct", "At the fix turn right and follow the pattern."],
];
export const ENTRY_NOTE = "The entry depends on the heading on arrival at the fix, with \u00b15\u00b0 flexibility at the "
  + "sector boundaries (shaded). Right-hand pattern shown; a left-hand pattern is its mirror image.";

// --- rysunki (SVG): pomocnicze funkcje rysujące; współrzędne w jednostkach viewBox, y w dół
const r1 = (v) => Math.round(v * 10) / 10;
// grot strzałki w punkcie (x, y) skierowany pod kątem deg (0 = w prawo, 90 = w dół)
const arrow = (x, y, deg, cls = "hold-arrow") =>
  `<path class="${cls}" d="M5,0 L-4,-3.5 L-4,3.5 Z" transform="translate(${r1(x)},${r1(y)}) rotate(${deg})"/>`;
// fix: trójkąt jak punkt nawigacyjny na mapie
const fixMark = (x, y) => `<path class="hold-fix" d="M${x},${y - 7} L${x + 6.5},${y + 4.5} L${x - 6.5},${y + 4.5} Z"/>`;
const text = (x, y, s, cls = "hold-lbl", anchor = "middle") =>
  `<text class="${cls}" x="${r1(x)}" y="${r1(y)}" text-anchor="${anchor}">${s}</text>`;
// pętla holdingu z zakrętami w prawo: odcinek dolotowy od (xl, y) do fixu (xf, y), zakręty o promieniu r w dół
const racetrack = (xl, xf, y, r, cls) =>
  `<path class="${cls}" d="M${xl},${y} L${xf},${y} A${r},${r} 0 0 1 ${xf},${y + 2 * r} L${xl},${y + 2 * r} A${r},${r} 0 0 1 ${xl},${y}"/>`;
// punkt na kierunku (kurs w stopniach, 0 = północ = w górę) w odległości d od (x, y)
const at = (x, y, brg, d) => [x + d * Math.sin(brg * Math.PI / 180), y - d * Math.cos(brg * Math.PI / 180)];

// rysunek holdingu: odcinek dolotowy na wschód do fixu, zakręty w prawo (strona holdingu na południe, pod linią)
export function patternSvg() {
  const xl = 150, xf = 360, y = 88, r = 52, yb = y + 2 * r, mid = (xl + xf) / 2;
  return `<svg class="hold-svg hold-pattern" viewBox="0 30 520 220" role="img" aria-label="Holding pattern">
  <line class="hold-ext" x1="12" y1="${y}" x2="508" y2="${y}"/>
  <line class="hold-guide" x1="${xf}" y1="${y + 6}" x2="${xf}" y2="${yb - 4}"/>
  ${racetrack(xl, xf, y, r, "hold-track")}
  ${arrow(mid, y, 0)}${arrow(mid, yb, 180)}${arrow(xf + r, y + r, 90)}${arrow(xl - r, y + r, -90)}
  ${fixMark(xf, y)}<circle class="hold-abeam" cx="${xf}" cy="${yb}" r="3.5"/>
  ${text(xf, y - 18, "HOLDING FIX", "hold-lbl hold-key")}
  ${text(16, 52, "NON-HOLDING SIDE", "hold-side", "start")}
  ${text(mid, y + r + 5, "HOLDING SIDE", "hold-side")}
  ${text(mid, y - 9, "INBOUND LEG")}
  ${text(mid, yb + 20, "OUTBOUND LEG")}
  ${text(mid, yb + 38, "1 min at or below FL140, 1.5 min above", "hold-lbl hold-key")}
  ${text(xf, yb + 20, "ABEAM")}
  ${text(xf + r + 10, y + r - 4, "OUTBOUND", "hold-lbl", "start")}${text(xf + r + 10, y + r + 12, "TURN", "hold-lbl", "start")}
  ${text(xl - r - 10, y + r - 4, "INBOUND", "hold-lbl", "end")}${text(xl - r - 10, y + r + 12, "TURN", "hold-lbl", "end")}
</svg>`;
}

// granice sektorów (kurs od fixu): linia 70° (20° i 200°) i przedłużenie odcinka dolotowego za fixem (90°);
// sektory: 2 OFFSET 20°-90°, 1 PARALLEL 90°-200°, 3 DIRECT 200°-20° (przez zachód i północ)
export const BOUNDS = [20, 90, 200];
export const SECTORS = [["1", "PARALLEL", 110], ["2", "OFFSET", 70], ["3", "DIRECT", 180]];

export function sectorsSvg() {
  const fx = 245, fy = 140, R = 118, xl = fx - 110, r = 38;
  const wedge = (b) => {
    const [ax, ay] = at(fx, fy, b - 5, R), [bx, by] = at(fx, fy, b + 5, R);
    return `<path class="hold-flex" d="M${fx},${fy} L${r1(ax)},${r1(ay)} A${R},${R} 0 0 1 ${r1(bx)},${r1(by)} Z"/>`;
  };
  const ray = (b) => { const [x, y] = at(fx, fy, b, R); return `<line class="hold-bound" x1="${fx}" y1="${fy}" x2="${r1(x)}" y2="${r1(y)}"/>`; };
  // kąt 70° między odcinkiem dolotowym (270°) a linią 70° (200°)
  const [a1x, a1y] = at(fx, fy, 200, 26), [a2x, a2y] = at(fx, fy, 270, 26), [tx, ty] = at(fx, fy, 235, 42);
  const label = (b, d, num, name, deg) => {
    const [x, y] = at(fx, fy, b, d);
    return text(x, y - 3, `${num} ${name}`, "hold-lbl hold-key") + text(x, y + 13, `${deg}\u00b0`);
  };
  return `<svg class="hold-svg hold-sectors" viewBox="0 12 520 262" role="img" aria-label="Holding entry sectors">
  <circle class="hold-ring" cx="${fx}" cy="${fy}" r="${R}"/>
  ${BOUNDS.map(wedge).join("")}
  ${racetrack(xl, fx, fy, r, "hold-track")}
  ${arrow((xl + fx) / 2, fy, 0)}${arrow((xl + fx) / 2, fy + 2 * r, 180)}
  ${BOUNDS.map(ray).join("")}
  <path class="hold-angle" d="M${r1(a1x)},${r1(a1y)} A26,26 0 0 1 ${r1(a2x)},${r1(a2y)}"/>
  ${text(tx, ty + 4, "70\u00b0", "hold-lbl hold-small")}
  ${fixMark(fx, fy)}${text(fx - 10, fy - 10, "FIX", "hold-lbl", "end")}
  ${label(55, 80, "2", "OFFSET", 70)}${label(120, 95, "1", "PARALLEL", 110)}${label(295, 82, "3", "DIRECT", 180)}
  ${text(fx + R + 8, fy + 4, "INBOUND", "hold-lbl hold-small", "start")}${text(fx + R + 8, fy + 18, "TRACK", "hold-lbl hold-small", "start")}
  ${text(r1(at(fx, fy, 20, R)[0]) + 8, r1(at(fx, fy, 20, R)[1]) + 10, "70\u00b0 LINE", "hold-lbl hold-small", "start")}
</svg>`;
}

// trzy małe rysunki wejść (panel 173 jednostki): fix (128, 64), pętla od x 60, promień 24, całość powiększona 1,2 raza;
// ścieżka wejścia na zielono
export const ENTRY_PATHS = [
  // 1 PARALLEL: dolot z sektora 1, w lewo na kurs odlotowy po stronie przeciwnej, w lewo ponad 180° do odcinka dolotowego
  { num: "1", name: "PARALLEL",
    d: "M163,99 L129,65 Q121,57 113,57 L52,57 A20,20 0 1 0 66.1,91.1 L88,69 Q93.2,64 99,64 L128,64",
    arrows: [[146, 82, -135], [84, 57, 180], [77, 80, -45], [114, 64, 0]] },
  // 2 OFFSET: dolot z sektora 2, tor 30° od odwrotności odcinka dolotowego na stronę holdingu, w prawo do odcinka dolotowego
  { num: "2", name: "OFFSET", d: "M169,35 L128,64 L74.3,95 A16.6,16.6 0 1 1 66,64 L128,64",
    arrows: [[148.5, 49.5, 145], [101.2, 79.5, 150], [100, 64, 0]], angle: true },
  // 3 DIRECT: dolot z sektora 3, nad fixem w prawo i dalej po pętli
  { num: "3", name: "DIRECT", d: "M95.5,31.5 L128,64 C140,76 146,112 128,112 L60,112 A24,24 0 0 1 60,64 L128,64",
    arrows: [[110, 46, 45], [92, 112, 180], [92, 64, 0]] },
];

export function entriesSvg() {
  const panels = ENTRY_PATHS.map((p, i) => `<g transform="translate(${i * 173},0)"><g transform="translate(-32,4) scale(1.2)">
    ${racetrack(60, 128, 64, 24, "hold-track hold-faint")}
    <path class="hold-entry" d="${p.d}"/>${p.arrows.map(([x, y, a]) => arrow(x, y, a, "hold-arrow hold-entry-arrow")).join("")}
    ${p.angle ? `<path class="hold-angle" d="M106,64 A22,22 0 0 0 108.9,75"/>${text(89, 82, "30\u00b0", "hold-lbl hold-small")}` : ""}
    ${fixMark(128, 64)}</g>
    ${text(86, 166, `${p.num} ${p.name}`, "hold-lbl hold-key")}
  </g>`).join("");
  return `<svg class="hold-svg hold-entries" viewBox="0 30 520 146" role="img" aria-label="Holding entries">${panels}</svg>`;
}

// frazy stałe w tym pliku; (fix), (level) itd. wyróżnione kolorem
const ph = (s) => s.replace(/\(([a-z][a-z ]*)\)/g, `<span class="hold-ph">($1)</span>`);
const kv = (list) => list.map(([k, v]) => `<tr><th scope="row">${k}</th><td class="hold-say">${ph(v)}</td></tr>`).join("");

export function holdingHtml() {
  const flirt = [...FLIRT, EXPECT].map(([l, what, say], i) => `<tr${i === FLIRT.length ? ` class="hold-expect"` : ""}>`
    + `<td class="hold-letter">${l}</td><th scope="row">${what}</th><td class="hold-say">${ph(say)}</td></tr>`).join("");
  const speeds = SPEEDS.map(([lvl, n, t]) => `<tr><th scope="row">${lvl}</th><td class="hold-val">${n}</td><td class="hold-val">${t}</td></tr>`).join("");
  const entries = ENTRIES.map(([n, name, what]) => `<tr><th scope="row"><span class="hold-num">${n}</span> ${name}</th><td>${what}</td></tr>`).join("");
  const notes = (list) => `<ul class="hold-notes">${list.map((s) => `<li>${s}</li>`).join("")}</ul>`;
  // dwie kolumny (wąsko: jedna): zasady i frazy | rysunki; szeroko trzy kolumny przez obszary siatki (other.css)
  return `<div class="hold-page"><div class="hold-cols"><div class="hold-col">
  <section class="hold-sec hold-flirt"><h3 class="hold-bar">Holding clearance (FLIRT)</h3>
    <table class="hold-table hold-flirt-table"><tbody>${flirt}</tbody></table>
    <p class="hold-sub">Example</p>
    <p class="hold-example">${EXAMPLE}</p>
  </section>
  <section class="hold-sec hold-phrases"><h3 class="hold-bar">Phraseology</h3>
    <table class="hold-table hold-kv"><tbody>${kv(PHRASES)}</tbody></table>
    <p class="hold-note">${PHRASE_NOTE}</p>
  </section>
  <section class="hold-sec hold-speeds"><h3 class="hold-bar">Maximum holding speeds (IAS)</h3>
    <table class="hold-table"><thead><tr><th>Level</th><th>Normal</th><th>Turbulence</th></tr></thead><tbody>${speeds}</tbody></table>
    ${notes(SPEED_NOTES)}
  </section>
</div><div class="hold-col">
  <section class="hold-sec hold-drawing"><h3 class="hold-bar">Holding pattern</h3>
    ${patternSvg()}
    ${notes(PATTERN_NOTES)}
  </section>
  <section class="hold-sec hold-entry-sec"><h3 class="hold-bar">Entry sectors</h3>
    ${sectorsSvg()}
    <p class="hold-note">${ENTRY_NOTE}</p>
  </section>
  <section class="hold-sec hold-entry-how"><h3 class="hold-bar">Entries</h3>
    ${entriesSvg()}
    <table class="hold-table hold-kv"><tbody>${entries}</tbody></table>
  </section>
</div></div></div>`;
}

// panel podzakładki: sama treść, nic do sprzątania (bez destroy)
export function mountHolding(pane) {
  pane.insertAdjacentHTML("beforeend", holdingHtml());
}
