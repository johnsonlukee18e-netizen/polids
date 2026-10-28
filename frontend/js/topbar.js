// Pasek u góry ekranu jak w PANDORZE (index.html: header#topbar): Reload | Brighter | Darker, trzy równe pola na całą
// szerokość nad menu i zakładkami.
// Reload: wczytuje całą stronę od nowa (po aktualizacji serwera nowa wersja aplikacji; zainstalowane okno PWA nie ma
// przycisku przeglądarki) i wraca do tego samego ekranu. Adres ekranu czeka w sessionStorage tej karty na jedno
// uruchomienie (takeReload w app.js, po otwarciu HOME); każde inne uruchomienie (F5, nowe okno) otwiera HOME jak dotąd.
// Brighter / Darker: jasność całego ekranu, krok 12 % od -4 do +4 (52-148 %), zapamiętana w tej przeglądarce
// (localStorage); na granicy zakresu przycisk jest wyłączony, a dymek podaje bieżącą jasność. Filtr CSS na <html>, nigdy
// na main ani #views: filtr na przodku robi z niego blok zawierający dla position: fixed, więc dymki RADIO (.rb-tip)
// i pasek offline przesuwałyby się o szerokość menu i wysokość paska (pomiar w mapie rundy 16); <html> tego nie robi.
// Zapisaną jasność ustawia już skrypt w <head> index.html przed pierwszym rysowaniem (bez błysku 100 % przy F5
// i Reload); ten moduł ładuje index.html osobno, przed app.js, więc pasek działa, nawet gdy nie wczyta się któraś
// zakładka (moduł wykonuje się raz, także gdy importuje go app.js). Inne okna PolIDS w tej przeglądarce (drugi
// monitor) dostają zmianę jasności od razu przez zdarzenie "storage".
import { lsGet, lsSet, parseHash } from "./api.js";

// sessionStorage: adres ekranu sprzed Reload (jednorazowo); localStorage: poziom jasności -4..4
export const RELOAD_KEY = "shell.reload";
export const BRIGHT_KEY = "shell.bright";
export const BRIGHT_STEP = 0.12;
export const BRIGHT_MIN = -4;
export const BRIGHT_MAX = 4;

export const clampBright = (v) => Math.max(BRIGHT_MIN, Math.min(BRIGHT_MAX, Math.round(Number(v)) || 0));
// zapisana wartość: tylko liczba całkowita z zakresu, wszystko inne (brak, śmieć, 2.5, 9) = 0, czyli bez filtra
export function brightOf(raw) {
  const v = typeof raw === "string" && raw.trim() !== "" ? Number(raw) : NaN;
  return Number.isInteger(v) && v >= BRIGHT_MIN && v <= BRIGHT_MAX ? v : 0;
}
export const brightPct = (v) => Math.round((1 + v * BRIGHT_STEP) * 100);
// poziom 0 bez filtra (żadnego kosztu rysowania w zwykłym przypadku)
export const brightFilter = (v) => (v ? `brightness(${(1 + v * BRIGHT_STEP).toFixed(2)})` : "");

// sessionStorage bywa niedostępny (tryb prywatny, zablokowane dane strony): wtedy Reload otwiera HOME jak F5
const session = () => { try { return window.sessionStorage; } catch { return null; } };
export function markReload(hash, store = session()) {
  try { store?.setItem(RELOAD_KEY, hash || "#home"); } catch { /* brak miejsca, zablokowane */ }
}
// odczyt i od razu usunięcie: znacznik działa na jedno uruchomienie
export function takeReload(store = session()) {
  let hash = null;
  try { hash = store?.getItem(RELOAD_KEY) ?? null; store?.removeItem(RELOAD_KEY); } catch { /* zablokowane */ }
  return hash;
}
// ekran do przywrócenia po Reload: {tab, arg} z zapisanego adresu; HOME albo pusty adres = nic (HOME już otwarty)
export function reloadTarget(hash) {
  if (!hash) return null;
  const { tab, arg } = parseHash(hash);
  return tab && tab !== "home" ? { tab, arg } : null;
}

// bar: header#topbar; root: element z filtrem (<html>); here/reload/store/win: do testów w Node.
// Drugie wywołanie dla tego samego paska oddaje ten sam obiekt (bez drugiego zestawu nasłuchów).
const MOUNTED = new WeakMap();
export function mountTopbar(bar, { root, here = () => location.hash, reload = () => location.reload(), store,
  win = typeof window === "undefined" ? null : window } = {}) {
  if (!bar) return null;
  if (MOUNTED.has(bar)) return MOUNTED.get(bar);
  // domyślny <html> dopiero po sprawdzeniu bar: w Node (testy) nie ma document
  root ??= document.documentElement;
  const btn = (act) => bar.querySelector(`button[data-act="${act}"]`);
  let bright = brightOf(lsGet(BRIGHT_KEY));
  const apply = () => {
    root.style.filter = brightFilter(bright);
    const pct = brightPct(bright);
    btn("brighter").disabled = bright >= BRIGHT_MAX;
    btn("darker").disabled = bright <= BRIGHT_MIN;
    btn("brighter").title = `Brighter screen (now ${pct}%${bright >= BRIGHT_MAX ? ", the brightest" : ""})`;
    btn("darker").title = `Darker screen (now ${pct}%${bright <= BRIGHT_MIN ? ", the darkest" : ""})`;
  };
  bar.addEventListener("click", (e) => {
    const act = e.target.closest("button[data-act]")?.dataset.act;
    if (act === "reload") {
      markReload(here(), store === undefined ? session() : store);
      reload();
    } else if (act === "brighter" || act === "darker") {
      // przycisk wyłączony na granicy zakresu gubi fokus (przeglądarka przenosi go od razu na <body>, następny Tab od
      // początku strony): fokus sprawdzony przed apply(), potem na drugi przycisk jasności
      const b = btn(act), focused = b.ownerDocument?.activeElement === b;
      bright = clampBright(bright + (act === "brighter" ? 1 : -1));
      lsSet(BRIGHT_KEY, String(bright));
      apply();
      if (focused && b.disabled) btn(act === "brighter" ? "darker" : "brighter").focus();
    }
  });
  // zmiana w innym oknie tej przeglądarki (key null: wyczyszczone dane strony)
  win?.addEventListener("storage", (e) => {
    if (e.key !== BRIGHT_KEY && e.key !== null) return;
    bright = brightOf(lsGet(BRIGHT_KEY));
    apply();
  });
  apply();
  const api = { level: () => bright };
  MOUNTED.set(bar, api);
  return api;
}

// w przeglądarce pasek od razu przy wczytaniu modułu (index.html: <script type="module" src=".../topbar.js">)
if (typeof document !== "undefined") mountTopbar(document.getElementById("topbar"));
