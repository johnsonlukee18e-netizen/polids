// OTHER › VFR MINIMA (0.13.0): stałe tabele dla FIR Warszawa: minima VMC (widzialność i odległość od chmur wg pasma
// wysokości i klasy przestrzeni C, D, G), VFR w nocy, specjalne VFR (warunki dla pilota i kiedy ATC nie wydaje
// zgody) i minima meteo lotów HEMS (LPR) jak w tabeli z dokumentu LPR. Wartości z tekstów przepisów i polskiego AIP
// (notatki rundy 16: vfr.md); w podpowiedzi do śmigłowców w klasie G angielski AIP ma błąd tłumaczenia ("in less than
// 800 m"), polski tekst i rozporządzenie: "nie mniejszej niż 800 m", więc "not less than 800 m".
// Na ekranie bez numerów przepisów i nazw dokumentów. Strona bez danych z serwera i bez timerów.

const CLOUD = "1500 m horizontally<br>300 m (1000 ft) vertically";
const LOW = "900 m (3000 ft) AMSL or 300 m (1000 ft) above terrain, whichever is the higher";

// minima VMC: [pasmo, klasy, widzialność w locie, odległość od chmur]; pasmo null = to samo co w wierszu wyżej (rowspan)
export const VMC = [
  ["At and above FL100", "C", "8 km", CLOUD],
  [`Below FL100 and above ${LOW}`, "C D G", "5 km", CLOUD],
  [`At and below ${LOW}`, "C D", "5 km", CLOUD],
  [null, "G", "5 km *", "Clear of cloud and<br>with the surface in sight"],
];
// * klasa G nisko, w dzień: zmniejszona widzialność w locie
export const CLASS_G_REDUCED = [
  ["Not less than 1500 m", "At 140 kt IAS or less, to observe other traffic or any obstacles in time to avoid collision, or "
    + "where encounters with other traffic are normally unlikely (low traffic volume, aerial work at low levels)"],
  ["Helicopters: not less than 800 m", "At a speed that gives adequate opportunity to observe other traffic or any obstacles "
    + "in time to avoid collision"],
];
// VFR w nocy: [co, wartość]
export const NIGHT = [
  ["Visibility and distance from cloud", "As in VMC minima"],
  ["Ceiling", "Not less than 450 m (1500 ft)"],
  ["Reduced flight visibility in class G *", "Does not apply"],
  [`At and below ${LOW} (classes C, D, G)`, "Continuous sight of the surface"],
  ["Flight plan", "Required when leaving the vicinity of an aerodrome"],
  ["Radio", "Two-way communication on the appropriate ATS channel, when available"],
  ["Minimum level over high terrain or in mountainous areas", "600 m (2000 ft) above the highest obstacle within 8 km"],
  ["Minimum level elsewhere", "300 m (1000 ft) above the highest obstacle within 8 km"],
];
export const DAY_NIGHT = "Day: from 30 min before sunrise to 30 min after sunset. Night: from 30 min after sunset to 30 min before "
  + "sunrise. Minimum levels do not apply when necessary for take-off or landing.";
// VFR na lotnisku w strefie kontrolowanej bez zgody ATC: [co, poniżej]
export const CTR_VFR = [["Ceiling", "Less than 450 m (1500 ft)"], ["Ground visibility", "Less than 5 km"]];
// specjalne VFR: warunki dla pilota i kiedy ATC nie wydaje zgody
export const SVFR_PILOT = [
  ["Cloud", "Clear of cloud and with the surface in sight"],
  ["Flight visibility", "Not less than 1500 m<br>Helicopters: not less than 800 m"],
  ["Speed", "140 kt IAS or less"],
];
export const SVFR_ATC = [
  ["Ground visibility", "Less than 1500 m<br>Helicopters: less than 800 m"],
  ["Ceiling", "Less than 180 m (600 ft)"],
];
// HEMS (LPR): [podstawa chmur, widzialność] w dzień; w nocy jedna wartość na wszystkie trzy wiersze (komórki scalone)
export const HEMS_DAY = [["300 - 400 ft", "3 km"], ["410 - 500 ft", "2 km"], ["> 500 ft", "1500 m"]];
export const HEMS_NIGHT = ["> 1500 ft", "> 5 km"];

// teksty są stałe w tym pliku (z <br> w niektórych wartościach), bez danych z zewnątrz
const rows = (list) => list.map(([k, v]) => `<tr><th scope="row">${k}</th><td class="vfr-val">${v}</td></tr>`).join("");

export function vfrHtml() {
  const vmc = VMC.map(([band, cls, vis, cloud], i) => {
    const span = VMC[i + 1] && VMC[i + 1][0] === null ? 2 : 1;
    const bandCell = band === null ? "" : `<th scope="row"${span > 1 ? ` rowspan="${span}"` : ""}>${band}</th>`;
    return `<tr>${bandCell}<td class="vfr-cls">${cls}</td><td class="vfr-val">${vis}</td><td class="vfr-val vfr-cloud">${cloud}</td></tr>`;
  }).join("");
  const hems = HEMS_DAY.map(([cb, vis], i) => `<tr><td>${cb}</td><td>${vis}</td>`
    + (i ? "" : `<td rowspan="${HEMS_DAY.length}">${HEMS_NIGHT[0]}</td><td rowspan="${HEMS_DAY.length}">${HEMS_NIGHT[1]}</td>`)
    + "</tr>").join("");
  return `<div class="vfr-page"><div class="vfr-cols">
  <section class="vfr-sec vfr-vmc"><h3 class="vfr-bar">VMC minima</h3>
    <table class="vfr-table"><thead><tr><th>Level</th><th>Class</th><th>Flight visibility</th><th>Distance from cloud</th></tr></thead>
      <tbody>${vmc}</tbody></table>
    <p class="vfr-sub">* Class G by day, at and below ${LOW}: flight visibility may be reduced to</p>
    <table class="vfr-table vfr-kv"><tbody>${rows(CLASS_G_REDUCED)}</tbody></table>
  </section>
  <section class="vfr-sec vfr-night"><h3 class="vfr-bar">Night VFR</h3>
    <table class="vfr-table vfr-kv"><tbody>${rows(NIGHT)}</tbody></table>
    <p class="vfr-note">${DAY_NIGHT}</p>
  </section>
  <section class="vfr-sec vfr-svfr"><h3 class="vfr-bar">Special VFR</h3>
    <p class="vfr-sub">VFR at an aerodrome in a control zone (take-off, landing, entering the aerodrome traffic zone or
      circuit) needs an ATC clearance when reported:</p>
    <table class="vfr-table vfr-kv"><tbody>${rows(CTR_VFR)}</tbody></table>
    <p class="vfr-sub">Special VFR: within a control zone, with an ATC clearance, day only. Pilot:</p>
    <table class="vfr-table vfr-kv"><tbody>${rows(SVFR_PILOT)}</tbody></table>
    <p class="vfr-sub">ATC does not clear special VFR to take off, land or enter the aerodrome traffic circuit within a
      control zone when reported at the aerodrome:</p>
    <table class="vfr-table vfr-kv"><tbody>${rows(SVFR_ATC)}</tbody></table>
    <p class="vfr-note">Helicopters on police, medical, search and rescue or fire-fighting flights may fly special VFR under
      other conditions with a specific permission.</p>
  </section>
  <section class="vfr-sec vfr-hems"><h3 class="vfr-bar">HEMS (LPR)</h3>
    <p class="vfr-sub">Meteorological minimums for HEMS flights</p>
    <table class="vfr-table vfr-hems-table"><thead><tr><th colspan="2" class="vfr-period">DAY</th><th colspan="2" class="vfr-period">NIGHT</th></tr>
      <tr><th>Cloud base</th><th>Visibility</th><th>Cloud base</th><th>Visibility</th></tr></thead>
      <tbody>${hems}</tbody></table>
  </section>
</div></div>`;
}

// panel podzakładki: sama treść, nic do sprzątania (bez destroy)
export function mountVfrMinima(pane) {
  pane.insertAdjacentHTML("beforeend", vfrHtml());
}
