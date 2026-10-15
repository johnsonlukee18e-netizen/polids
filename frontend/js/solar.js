// Położenie słońca i granica dnia i nocy (METEO › SUN). Te same wzory co backend (services/sun.py: algorytm NOAA ze
// wzorów Meeusa, dokładność ok. 1 min czasu). Same obliczenia, bez DOM i bez Leafleta (testy w Node).

const RAD = Math.PI / 180;
export const SR_ALT = -0.833;      // wschód / zachód: górny brzeg tarczy na horyzoncie, z refrakcją
export const CIVIL_ALT = -6;       // koniec zmierzchu cywilnego (EECT) / początek świtu cywilnego (BMCT)

// deklinacja słońca (°) i równanie czasu (min) w chwili t (Date albo ms UTC)
export function solarPosition(t) {
  const jd = +t / 86400000 + 2440587.5, c = (jd - 2451545) / 36525;
  const l0 = (280.46646 + c * (36000.76983 + c * 0.0003032)) % 360;
  const m = (357.52911 + c * (35999.05029 - 0.0001537 * c)) * RAD;
  const e = 0.016708634 - c * (0.000042037 + 0.0000001267 * c);
  const center = Math.sin(m) * (1.914602 - c * (0.004817 + 0.000014 * c)) + Math.sin(2 * m) * (0.019993 - 0.000101 * c)
    + Math.sin(3 * m) * 0.000289;
  const omega = (125.04 - 1934.136 * c) * RAD;
  const app = (l0 + center - 0.00569 - 0.00478 * Math.sin(omega)) * RAD;
  const eps = (23 + (26 + (21.448 - c * (46.815 + c * (0.00059 - c * 0.001813))) / 60) / 60 + 0.00256 * Math.cos(omega)) * RAD;
  const decl = Math.asin(Math.sin(eps) * Math.sin(app)) / RAD;
  const y = Math.tan(eps / 2) ** 2, l = l0 * RAD;
  const eqt = 4 / RAD * (y * Math.sin(2 * l) - 2 * e * Math.sin(m) + 4 * e * y * Math.sin(m) * Math.cos(2 * l)
    - 0.5 * y * y * Math.sin(4 * l) - 1.25 * e * e * Math.sin(2 * m));
  return { decl, eqt };
}

// długość -180..180
export const wrapLon = (lon) => ((((lon + 180) % 360) + 360) % 360) - 180;

// punkt podsłoneczny (słońce w zenicie): o 12:00 UTC długość = −(równanie czasu)/4
export function subsolarPoint(t) {
  const { decl, eqt } = solarPosition(t);
  const d = new Date(+t);
  const minutes = d.getUTCHours() * 60 + d.getUTCMinutes() + d.getUTCSeconds() / 60 + d.getUTCMilliseconds() / 60000;
  return { lat: decl, lon: wrapLon((720 - minutes - eqt) / 4) };
}

// odległość kątowa dwóch punktów na kuli (°)
export function angDist(lat1, lon1, lat2, lon2) {
  const c = Math.sin(lat1 * RAD) * Math.sin(lat2 * RAD) + Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.cos((lon2 - lon1) * RAD);
  return Math.acos(Math.max(-1, Math.min(1, c))) / RAD;
}

// wysokość środka tarczy nad horyzontem (°, bez refrakcji)
export function sunElevation(lat, lon, t) {
  const s = subsolarPoint(t);
  return 90 - angDist(lat, lon, s.lat, s.lon);
}

// "day" (słońce nad horyzontem), "civil" (zmierzch cywilny) albo "night"
export const sunState = (elev) => (elev > SR_ALT ? "day" : elev > CIVIL_ALT ? "civil" : "night");

// Okrąg o promieniu kątowym r (°) wokół punktu [lat, lon] jako łamana [lat, lon] z ciągłą długością (bez skoku przy
// ±180°), od kierunku północnego zgodnie z ruchem wskazówek zegara. pole: 1 / -1 = okrąg obejmuje biegun północny /
// południowy (długość na końcu łamanej różni się wtedy od początku o 360°), 0 = nie obejmuje (łamana zamknięta).
export function capRing(lat, lon, r, steps = 360) {
  const p = lat * RAD, d = r * RAD, ring = [];
  let prev = null;
  for (let i = 0; i <= steps; i++) {
    const b = (i / steps) * 2 * Math.PI;
    const p2 = Math.asin(Math.sin(p) * Math.cos(d) + Math.cos(p) * Math.sin(d) * Math.cos(b));
    let l2 = lon + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p), Math.cos(d) - Math.sin(p) * Math.sin(p2)) / RAD;
    if (prev !== null) l2 += Math.round((prev - l2) / 360) * 360;   // ciągła długość
    ring.push([p2 / RAD, l2]);
    prev = l2;
  }
  return { ring, pole: 90 - lat < r ? 1 : 90 + lat < r ? -1 : 0 };
}

// Obszar, w którym słońce jest niżej niż alt (°): czasza wokół punktu przeciwsłonecznego o promieniu 90° + alt, jako
// pierścienie [lat, lon] do wielokąta Leafleta. Pięć obiegów długości (co najmniej od -540° do 540°): przy najmniejszym
// zoomie mapa pokazuje ok. 700° długości, a worldCopyJump trzyma środek widoku w -180..180. Czasza z biegunem: jeden
// pierścień (granica przez pięć obiegów i zamknięcie przez biegun), bez szwów między kopiami; czasza bez bieguna
// (okolice równonocy): pięć rozłącznych kopii przesuniętych o 360°.
const COPIES = [-2, -1, 0, 1, 2];
export function nightRings(t, alt = SR_ALT, steps = 360) {
  const s = subsolarPoint(t);
  const { ring, pole } = capRing(-s.lat, wrapLon(s.lon + 180), 90 + alt, steps);
  if (!pole) return COPIES.map((k) => ring.slice(0, -1).map(([la, lo]) => [la, lo + k * 360]));
  const dir = Math.sign(ring[ring.length - 1][1] - ring[0][1]) * 360;   // obieg w stronę rosnącej albo malejącej długości
  const curve = COPIES.flatMap((k, i) => ring.slice(i ? 1 : 0).map(([la, lo]) => [la, lo + k * dir]));
  return [[...curve, [pole * 90, curve[curve.length - 1][1]], [pole * 90, curve[0][1]]]];
}

// "52°10′N 020°58′E"
export function latLonTxt(lat, lon) {
  const f = (v, w, pos, neg) => {
    const a = Math.abs(v), d = Math.floor(a), m = Math.round((a - d) * 60);
    const [dd, mm] = m === 60 ? [d + 1, 0] : [d, m];
    return `${String(dd).padStart(w, "0")}°${String(mm).padStart(2, "0")}′${v < 0 ? neg : pos}`;
  };
  return `${f(lat, 2, "N", "S")} ${f(wrapLon(lon), 3, "E", "W")}`;
}
