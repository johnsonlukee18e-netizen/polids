import { api, BASEMAPS, esc, frameGo, h, splitTaf, subtabs, lsGet, lsSet, ONLINE_EVENT } from "../api.js";
import { CIVIL_ALT, SR_ALT, latLonTxt, nightRings, subsolarPoint, sunElevation, sunState, wrapLon } from "../solar.js";
import { qnhMap } from "../qnhmap.js";

// listy domyślne alfabetycznie (wyniki i tak są sortowane po ICAO)
const PL_CIV = "EPBY EPGD EPKK EPKT EPLB EPLL EPMO EPPO EPRA EPRZ EPSC EPSY EPWA EPWR EPZG";
const PL_MIL = "EPCE EPDA EPDE EPIR EPKS EPLK EPLY EPMB EPMI EPMM EPOK EPPR EPPW EPSN EPTM";
const INTL = "EDDB EDDF EDDM EKCH ESSA EVRA EYVI LKPR LOWW LZIB UKLL";

// Kolorowanie METAR/TAF tak jak w PANDORZE
export function colorize(raw) {
  if (!raw) return `<span class="nil">NIL</span>`;
  let rmk = false, station = false;
  return esc(raw).split(/\s+/).map((t) => {
    if (!station && /^[A-Z]{4}$/.test(t) && !["METAR", "TAF", "AUTO"].includes(t)) { station = true; return `<span class="st">${t}</span>`; }
    if (["METAR", "SPECI", "TAF", "AMD", "COR"].includes(t)) return `<span class="tm">${t}</span>`;
    if (t === "RMK") rmk = true;
    if (rmk) return `<span class="rmk">${t}</span>`;
    if (["NOSIG", "TEMPO", "BECMG", "PROB30", "PROB40"].includes(t) || /^(FM|TL|AT)\d{4}/.test(t)) return `<span class="trend">${t}</span>`;
    if (/^\d{6}Z$/.test(t) || /^\d{4}\/\d{4}$/.test(t)) return `<span class="tm">${t}</span>`;
    if (/^(\d{3}|VRB)\d{2,3}(G\d{2,3})?(KT|MPS)$/.test(t) || /^\d{3}V\d{3}$/.test(t)) return `<span class="wind">${t}</span>`;
    if (t === "CAVOK") return `<span class="cavok">${t}</span>`;
    if (/^(FEW|SCT|BKN|OVC|VV)/.test(t) || ["NSC", "NCD", "SKC"].includes(t)) return `<span class="cld">${t}</span>`;
    if (/^[QA]\d{4}$/.test(t)) return `<span class="q">${t}</span>`;
    if (t === "NIL") return `<span class="nil">${t}</span>`;
    if (/^(\+|-|VC)?[A-Z]{2,8}$/.test(t) && !["METAR", "TAF", "AUTO", "COR", "AMD", "SPECI"].includes(t)) return `<span class="wxph">${t}</span>`;
    return t;
  }).join(" ");
}

// TAF: każdy okres zmian w nowej linii, wcięty pod pierwszą linią
export function wxLines(kind, raw) {
  const lines = kind === "taf" ? splitTaf(raw) : [raw];
  return lines.map((l, i) => (i ? `<span class="cont">${colorize(l)}</span>` : colorize(l))).join("<br>");
}

// lista stacji w polu: wielkie litery, bez powtórzeń, alfabetycznie (także lista zapamiętana w starszej wersji)
const normIds = (s) => [...new Set(String(s || "").toUpperCase().split(/[\s,;]+/).filter(Boolean))].sort().join(" ");

function wxList(kind, defaults, key) {
  return (pane) => {
    pane.append(h(`<div>
      <div class="toolbar">
        <input type="text" class="ids" size="80" value="${esc(normIds(lsGet(key) || defaults))}">
        <button class="btn primary go">Show</button>
        <label class="sc"><input type="checkbox" class="auto" checked> refresh every 2 min</label>
        <span class="hint upd"></span>
      </div>
      <div class="wx"></div>
    </div>`));
    const $ = (s) => pane.querySelector(s);
    // dead: podzakładka zamknięta w trakcie pobierania (np. szybkie przejście na TURB); pane zostaje w DOM i trafia do
    // następnej podzakładki, więc spóźniona odpowiedź nie może do niego pisać
    let dead = false;
    const load = async () => {
      const ids = normIds($(".ids").value);
      $(".ids").value = ids;
      lsSet(key, ids);
      try {
        // METAR i TAF alfabetycznie po ICAO (odpowiedź też sortujemy, gdyby backend zmienił kolejność)
        const rows = (await api(`/api/meteo/${kind}?ids=${encodeURIComponent(ids.split(" ").join(","))}`)).sort((a, b) => a.icao.localeCompare(b.icao));
        if (dead) return;
        $(".wx").innerHTML = rows.map((r) => `<div class="row">${r.raw ? wxLines(kind, r.raw) : `<span class="st">${esc(r.icao)}</span> <span class="nil">NIL</span>`}</div>`).join("");
        $(".upd").textContent = "Updated " + new Date().toISOString().slice(11, 16) + "Z";
      } catch (e) { if (!dead) $(".wx").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    };
    $(".go").addEventListener("click", load);
    $(".ids").addEventListener("keydown", (e) => e.key === "Enter" && load());
    const timer = setInterval(() => $(".auto")?.checked && load(), 120000);
    // serwer wrócił (okno run.bat uruchomione ponownie): komunikat błędu od razu zastępują dane
    const online = () => $(".wx .error") && load();
    window.addEventListener(ONLINE_EVENT, online);
    load();
    return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); } };
  };
}

// --- RADAR, SAT PL, SAT EUR, ICING: Windy z własnym środkiem i zoomem dla każdej podzakładki; ICING także z poziomem
// ciśnienia (oblodzenie liczone na poziomie, przy ziemi bez sensu), pozostałe przy ziemi
export const WINDY_VIEWS = {
  radar: { overlay: "radar", lat: 52.0, lon: 19.3, zoom: 6 },
  "sat-pl": { overlay: "satellite", lat: 52.0, lon: 19.0, zoom: 6 },     // Polska (FIR EPWW z sąsiadami)
  "sat-eur": { overlay: "satellite", lat: 50.0, lon: 12.0, zoom: 4 },    // Europa
  icing: { overlay: "icing", lat: 52.0, lon: 19.0, zoom: 6, level: "700h" },   // Polska, domyślnie 700 hPa ≈ FL100
};
export const windyEmbedUrl = ({ overlay, lat, lon, zoom, level = "surface" }) => `https://embed.windy.com/embed2.html?lat=${lat.toFixed(1)}`
  + `&lon=${lon.toFixed(1)}&detailLat=52.17&detailLon=20.97&zoom=${zoom}&level=${level}&overlay=${overlay}&product=ecmwf&menu=`
  + "&message=true&marker=&calendar=now&pressure=true&type=map&location=coordinates&detail=&metricWind=kt&metricTemp=%C2%B0C&radarRange=-1";
const windy = (view) => (pane) => {
  pane.append(h(`<iframe class="embed" src="${esc(windyEmbedUrl(WINDY_VIEWS[view]))}" allowfullscreen></iframe>`));
};

// --- TURB i SIGWX: obrazy IMGW wczytywane wprost przez przeglądarkę (bez pośrednictwa serwera PolIDS: serwer IMGW może
// wymagać sesji użytkownika w jego przeglądarce), dopasowane do okna (object-fit: contain) albo 1:1 z przewijaniem
const IMGW = "https://aviation-api.imgw.pl/image";
// turbulencja (IMGW, model DWD, statki rejsowe): 8 klatek co 3 h, od +0 h do +21 h, w animacji co 1,5 s
export const TURB_STEPS = ["000", "003", "006", "009", "012", "015", "018", "021"];
export const TURB_MS = 1500;
export const turbFrames = () => TURB_STEPS.map((s) => ({
  label: `+${Number(s)} h`, url: `${IMGW}/TURBULENCJE/gify_LOTN07_TURB_DWD_statkirejsowe/Turb11000.${s}.gif` }));
export const SIGWX_URL = `${IMGW}/significant/pl`;
export const IMG_REFRESH = 15 * 60000;   // nowe obrazy co 15 min
// znacznik czasu do adresu (?t=20261012121500): ten sam w obrębie okresu, więc powrót na podzakładkę bierze obraz z pamięci
// podręcznej przeglądarki, a po upływie okresu przeglądarka pobiera obraz od nowa
export const stamp = (now, period) => new Date(Math.floor(now / period) * period).toISOString().replace(/\D/g, "").slice(0, 14);
export const bust = (url, t) => `${url}${url.includes("?") ? "&" : "?"}t=${t}`;
// następna klatka w kierunku dir z pominięciem klatek z błędem; null, gdy wszystkie pozostałe mają błąd
export function nextFrame(states, i, dir = 1) {
  const n = states.length;
  for (let k = 1; k < n; k++) {
    const j = (((i + dir * k) % n) + n) % n;
    if (states[j] !== "err") return j;
  }
  return null;
}
// krok animacji (stany klatek: "load" / "ok" / "err"): indeks klatki do pokazania (ten sam = czekamy, aż bieżąca albo
// następna się wczyta, klatki z błędem pomijamy), -1 = zatrzymać animację (żadna klatka nie wczytała się)
export function playStep(states, cur) {
  if (states[cur] === "load") return cur;   // np. +0 h wczytuje się dłużej niż reszta: pokazujemy ją, zanim pójdziemy dalej
  const j = nextFrame(states, cur, 1);
  if (j === null) return states[cur] === "err" ? -1 : cur;
  return states[j] === "load" ? cur : j;
}

const utcHm = (d) => d.toISOString().slice(11, 16) + "Z";
// czas pierwszego udanego pobrania każdego adresu obrazu (na czas życia strony): powrót na podzakładkę w tym samym
// kwadransie bierze obraz z pamięci podręcznej przeglądarki, a "fetched" pokazuje wtedy czas pobrania, nie wyświetlenia
const FETCHED = new Map();
export function fetchedAt(url, now = new Date()) {
  if (!FETCHED.has(url)) {
    FETCHED.set(url, now);
    if (FETCHED.size > 200) FETCHED.delete(FETCHED.keys().next().value);   // najstarszy wpis
  }
  return FETCHED.get(url);
}

// <img> obrazu z zewnętrznego serwera (IMGW): wszystkie powstają tutaj, bez nagłówka Referer
function imgEl(alt) {
  const im = document.createElement("img");
  im.referrerPolicy = "no-referrer";
  im.decoding = "async";
  im.draggable = false;
  im.alt = alt;
  return im;
}

// Widok obrazu (klatek) z serwera IMGW. o: {key, title, note (krótko, w pasku), desc (w podpowiedzi), frames: [{label, url}]};
// przy kilku klatkach odtwarzacz: start/stop, poprzednia/następna, wybór klatki; wszystkie klatki wczytywane od razu
// (płynna animacja).
function imgView(o) {
  return (pane) => {
    const fr = o.frames, n = fr.length, multi = n > 1;
    const st = fr.map(() => "load"), got = fr.map(() => null), gen = fr.map(() => 0);
    let cur = 0, playing = false, held = false, play = null, dead = false, lastMsg = "", period = stamp(Date.now(), IMG_REFRESH);
    let zoom = lsGet(`meteo.${o.key}.zoom`) === "full" ? "full" : "fit";
    const secs = String(TURB_MS / 1000);
    const wrap = h(`<div class="mimg mimg-${esc(o.key)}">
      <div class="mimg-bar">
        <b class="mimg-title">${esc(o.title)}</b>
        ${multi ? `<span class="mimg-seg mimg-ctl"><button data-act="prev" title="Previous frame (←)">◀</button><button data-act="play"
          class="mimg-play"></button><button data-act="next" title="Next frame (→)">▶</button></span>
          <span class="mimg-seg mimg-steps">${fr.map((f, i) => `<button data-i="${i}">${esc(f.label)}</button>`).join("")}</span>` : ""}
        <span class="mimg-hint"></span>
        <span class="mimg-seg mimg-zoom"><button data-z="fit" title="Whole image fitted to the window">FIT</button><button data-z="full"
          title="Actual image size, with scrolling">1:1</button></span>
        <a class="btn mimg-open" target="_blank" rel="noopener noreferrer" title="Open the image in a new tab">Open<span
          class="mimg-long"> in new tab</span> ↗</a>
      </div>
      <div class="mimg-stage" tabindex="0"><div class="mimg-msg" hidden></div></div>
    </div>`);
    pane.append(wrap);
    const $ = (s) => wrap.querySelector(s);
    const stage = $(".mimg-stage"), msg = $(".mimg-msg");
    // METEO na ekranie (główne zakładki zostają w DOM, ukryte): bez tego animacja i odświeżanie szłyby w tle całą zmianę
    const shown = () => !document.hidden && stage.offsetParent !== null;

    // klatki: <img> dla każdej, wszystkie od razu w DOM (przeglądarka pobiera je równolegle), widoczna tylko bieżąca
    const mk = (i) => {
      const im = imgEl(multi ? `${o.title} ${fr[i].label}` : o.title);
      im.dataset.i = i;
      return im;
    };
    // pobranie klatki i do im (adres ze znacznikiem ?t=); po błędzie jeszcze raz bez ?t= (gdyby serwer IMGW odrzucał
    // nieznane parametry; znacznik wtedy tylko po "#", którego przeglądarka nie wysyła do serwera). done(true) po
    // wczytaniu, done(false) po drugim błędzie; wynik starszego pobrania tej samej klatki jest pomijany
    const fetchImg = (im, i, t, done) => {
      const g = ++gen[i];
      let again = false;
      const fail = () => {
        if (dead || g !== gen[i]) return;
        if (again) return done(false);
        again = true;
        im.src = `${fr[i].url}#t=${t}`;
      };
      im.onerror = fail;
      im.onload = () => {
        if (dead || g !== gen[i]) return;
        if (!im.naturalWidth) return fail();
        got[i] = fetchedAt(im.src);
        done(true);
      };
      im.src = bust(fr[i].url, t);
    };
    const imgs = fr.map((_, i) => stage.insertBefore(mk(i), msg));
    const load = (i, t) => { st[i] = "load"; fetchImg(imgs[i], i, t, (ok) => set(i, ok ? "ok" : "err")); };
    function set(i, s) {
      st[i] = s;
      if (s === "ok" && held) start();   // animacja stanęła, bo nic się nie wczytało; jest klatka, więc rusza dalej
      draw();
    }

    function draw() {
      imgs.forEach((im, i) => { im.classList.toggle("on", i === cur); im.classList.toggle("ok", st[i] === "ok"); });
      stage.className = `mimg-stage ${zoom}`;
      wrap.querySelectorAll(".mimg-zoom button").forEach((b) => b.classList.toggle("active", b.dataset.z === zoom));
      wrap.querySelectorAll(".mimg-steps button").forEach((b, i) => {
        b.classList.toggle("active", i === cur);
        b.classList.toggle("load", st[i] === "load");
        b.classList.toggle("err", st[i] === "err");
        b.title = fr[i].label + (st[i] === "err" ? ": image failed to load" : st[i] === "load" ? ": loading…" : "");
      });
      const pb = $(".mimg-play");
      if (pb) {
        pb.textContent = playing ? "STOP" : "START";
        pb.title = playing ? "Stop the animation (space)" : `Play the frames in sequence, every ${secs} s (space)`;
        pb.classList.toggle("active", playing);
      }
      const f = fr[cur], name = multi ? `${o.title} ${f.label}` : o.title;
      $(".mimg-open").href = f.url;
      // najpierw opis, potem czas: w wąskim oknie ucinany jest czas (jest też w podpowiedzi), nie opis
      const at = got[cur] && st[cur] === "ok" ? utcHm(got[cur]) : "";
      const hint = $(".mimg-hint");
      hint.textContent = [o.note, at && `fetched\u00a0${at}`].filter(Boolean).join(" · ");   // \u00a0: bez łamania wiersza w środku
      hint.title = `${name}: ${o.desc}${at ? `, fetched ${at}` : ""}\nRefreshed every ${IMG_REFRESH / 60000} min.`;
      msg.hidden = st[cur] === "ok";
      msg.className = `mimg-msg ${st[cur]}`;
      const html = st[cur] === "err"
        ? `<b>${esc(name)}: image failed to load</b>
          <span>The server did not return the image. It may require a login in this browser or be temporarily
          unavailable; try opening it in a new tab.</span>
          <span class="mimg-acts"><a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">open in new tab ↗</a>
          <button class="btn mimg-retry">Retry</button></span>`
        : `<span>Loading ${esc(name)}…</span>`;
      if (html !== lastMsg) msg.innerHTML = lastMsg = html;   // bez przebudowy przy każdej klatce (fokus na przycisku zostaje)
    }

    const go = (i) => { cur = ((i % n) + n) % n; draw(); };
    const tick = () => {
      if (!shown()) return;
      const j = playStep(st, cur);
      if (j < 0) { stop(); held = true; return; }   // żadna klatka się nie wczytała: stop, ruszy po wczytaniu którejś
      if (j !== cur) go(j);
    };
    function start() { clearInterval(play); held = false; playing = true; play = setInterval(tick, TURB_MS); draw(); }
    function stop() { clearInterval(play); play = null; held = false; playing = false; draw(); }
    const act = (a) => {
      if (a === "play") return playing ? stop() : start();
      stop();   // ręczny wybór klatki zatrzymuje animację
      go(cur + (a === "next" ? 1 : -1));
    };

    $(".mimg-bar").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.act) act(b.dataset.act);
      else if (b.dataset.i !== undefined) { stop(); go(Number(b.dataset.i)); }
      else if (b.dataset.z) { zoom = b.dataset.z; lsSet(`meteo.${o.key}.zoom`, zoom); draw(); }
    });
    // "Retry": nowy znacznik czasu, przeglądarka pyta serwer IMGW jeszcze raz (np. po zalogowaniu w innej karcie)
    msg.addEventListener("click", (e) => {
      if (!e.target.closest(".mimg-retry")) return;
      const t = stamp(Date.now(), 1000);
      fr.forEach((_, i) => st[i] === "err" && load(i, t));
      draw();
    });
    stage.addEventListener("keydown", (e) => {
      if (!multi || e.target !== stage) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") act(e.key === "ArrowLeft" ? "prev" : "next");
      else if (e.key === " ") act("play");
      else return;
      e.preventDefault();
    });

    // co 15 min (na pełny kwadrans) nowy znacznik czasu w adresie: nowy obraz wczytywany w tle i wstawiany w miejsce
    // starego dopiero po wczytaniu, więc nieudane odświeżenie nie zabiera wczytanego wcześniej obrazu; klatki z błędem
    // wczytujemy od nowa. Tylko gdy METEO jest na ekranie: po powrocie zaległy kwadrans dociągany w ciągu 10 s.
    const refresh = () => {
      const t = stamp(Date.now(), IMG_REFRESH);
      if (t === period || !shown()) return;
      period = t;
      fr.forEach((_, i) => {
        if (st[i] !== "ok") return load(i, t);
        const pre = mk(i);
        fetchImg(pre, i, t, (ok) => {
          if (!ok) return;   // nieudane odświeżenie: zostaje poprzedni obraz (z czasem "fetched" sprzed odświeżenia)
          imgs[i].replaceWith(pre);
          imgs[i] = pre;
          set(i, "ok");
        });
      });
      draw();
    };
    const refreshTimer = setInterval(refresh, 10000);

    fr.forEach((_, i) => load(i, period));
    if (multi) start(); else draw();
    return {
      destroy: () => {
        dead = true;
        clearInterval(play);
        clearInterval(refreshTimer);
      },
    };
  };
}

// --- WIND: Windy przy ziemi (0 ft) albo na 900 hPa (≈3000 ft AMSL) z punktem prognozy w punkcie podejścia wybranego
// pasa; obok wiatr z Open-Meteo w punktach podejścia wszystkich pasów lotniska (backend: services/upperwind.py)
const MAIN_AD = PL_CIV.split(" ");

function windyUrl(o) {
  const q = new URLSearchParams({ lat: o.lat.toFixed(3), lon: o.lon.toFixed(3), detailLat: o.dlat.toFixed(4), detailLon: o.dlon.toFixed(4),
    zoom: o.zoom, level: o.level, overlay: "wind", product: "ecmwf", menu: "", message: "true", marker: "true", calendar: "now",
    pressure: "true", type: "map", location: "coordinates", detail: "true", metricWind: "kt", metricTemp: "°C", radarRange: "-1" });
  return `https://embed.windy.com/embed2.html?${q}`;
}

// wiatr "310/14G26", składowe "H13" / "T13" (w plecy) i "5R" / "5L"; używane też w AERODROME
const p2 = (v, n) => String(v).padStart(n, "0");
export const windVec = (w) => (!w || w.speed === null || w.speed === undefined ? "–"
  : `${w.variable ? "VRB" : p2(w.dir, 3)}/${p2(w.speed, 2)}${w.gust ? "G" + w.gust : ""}`);
// składowe zawsze zaokrąglane po wartości bezwzględnej (-13.5 -> T14, 13.5 -> H14), wszędzie tak samo
export const kt = (v) => Math.round(Math.abs(v));
export const hwTxt = (v) => (v === null || v === undefined ? "–" : v < 0 && kt(v) ? `<span class="tw">T${kt(v)}</span>` : `H${kt(v)}`);
export const xwTxt = (v) => (v === null || v === undefined ? "–" : kt(v) === 0 ? "0" : `${kt(v)}${v > 0 ? "R" : "L"}`);
// "2026-10-06T18:00Z" -> "18:00Z 06.10"
export const validTxt = (t) => (t ? `${t.slice(11, 16)}Z ${t.slice(8, 10)}.${t.slice(5, 7)}` : "–");
// uwaga pod tabelą wiatru: ważność prognozy; przy błędzie pobrania tylko komunikat błędu (bez drugiego "unavailable")
export const forecastNote = (aw) => (aw?.valid ? `Forecast for ${validTxt(aw.valid)}, fetched ${aw.fetched || "–"}.`
  : aw?.model_error ? "" : "Forecast unavailable.");
// punkt podejścia bez nazwy: na przedłużeniu osi pasa, w którym ścieżka 3° osiąga 3000 ft
const CL3 = "CL 3°";
// odległość od progu zawsze z jedną cyfrą po przecinku ("3.0 NM", nie "3 NM" obok "4.9 NM")
const nm = (v) => (v === null || v === undefined ? "–" : Number(v).toFixed(1));
export const pointTip = (r) => `RWY ${r.designator}: ${r.fix ? r.fix + ", " : ""}${r.method_label}, ${nm(r.dist_nm)} NM from THR`
  + `, 3° path ≈ ${r.path_ft} ft${r.approaches?.length ? `\nApproaches: ${r.approaches.join(", ")}` : ""}`;

function windTab(pane) {
  const wrap = h(`<div class="wnd">
    <div class="wnd-bar">
      <span class="wnd-seg wnd-mode"><button data-m="0">0 ft</button><button data-m="3000">3000 ft (approach)</button></span>
      <label class="wnd-aero-l">Aerodrome <select class="wnd-aero"></select></label>
      <span class="wnd-rwyl">RWY <span class="wnd-seg wnd-rwys"></span></span>
      <span class="wnd-hint"></span>
    </div>
    <div class="wnd-body"><iframe class="embed wnd-frame" allowfullscreen></iframe><aside class="wnd-side"></aside></div>
  </div>`);
  pane.append(wrap);
  const $ = (s) => wrap.querySelector(s);
  // WIND zawsze otwiera się na wietrze przy ziemi (0 ft, issue #18): 3000 ft tylko do zamknięcia podzakładki, bez
  // zapamiętywania (wcześniej zapamiętany wybór 3000 ft, klucz "meteo.wind.mode", jest pomijany)
  let mode = "0";
  let icao = (lsGet("meteo.wind.ad") || "EPWA").toUpperCase();
  let ads = [], ad = null, rwy = null, inUse = null, aw = null, awErr = "", ptsErr = "", src = "", seq = 0, dead = false;
  const rwyKey = () => `meteo.wind.rwy.${icao}`;
  const sel = () => ad?.runways.find((r) => r.designator === rwy) || null;
  const roles = (d) => ["arr", "dep"].filter((k) => inUse?.[k] === d);
  const tags = (d) => roles(d).map((k) => `<span class="wnd-tag ${k}">${k.toUpperCase()}${inUse?.source === "ATIS" ? "" : "?"}</span>`).join("");

  const frame = () => {
    const r = sel(), up = mode === "3000";
    const o = up && r ? { lat: r.lat, lon: r.lon, dlat: r.lat, dlon: r.lon, zoom: 8, level: "900h" }
      : { lat: 52.0, lon: 19.3, dlat: ad ? ad.lat : 52.166, dlon: ad ? ad.lon : 20.967, zoom: 6, level: up ? "900h" : "surface" };
    const url = windyUrl(o);
    // nowa ramka zamiast zmiany src: bez kroku w historii przeglądarki (← i Wstecz cofają ekrany, nie ramkę Windy)
    if (url !== src) { const f = $(".wnd-frame"), g = f.cloneNode(false); g.src = src = url; f.replaceWith(g); }
    const hint = $(".wnd-hint");
    hint.textContent = up
      ? `900 hPa ≈ 3000 ft AMSL · forecast point ${r ? `RWY ${r.designator} ${r.fix || CL3}` : "– no RWY data"}`
      : `10 m (surface) · forecast point ${ad ? ad.icao : icao}`;
    hint.title = `${hint.textContent}${up && r ? ` (${r.method_label}, ${nm(r.dist_nm)} NM from THR)` : ""}`;
  };

  const bar = () => {
    wrap.querySelectorAll(".wnd-mode button").forEach((b) => b.classList.toggle("active", b.dataset.m === mode));
    $(".wnd-rwyl").hidden = mode !== "3000" || !ad;
    $(".wnd-rwys").innerHTML = (ad?.runways || []).map((r) => `<button data-rwy="${esc(r.designator)}" class="${r.designator === rwy ? "active" : ""} ${roles(r.designator).join(" ")}"
      title="${esc(pointTip(r))}">${esc(r.designator)}</button>`).join("");
  };

  const side = () => {
    const el = $(".wnd-side");
    const head = `<h3>${esc(ad?.icao || icao)} · ${mode === "3000" ? "approach wind 3000 ft" : "surface wind"}</h3>`;
    if (!aw) {
      el.innerHTML = `<div class="card wnd-card">${head}<p class="${awErr || ptsErr ? "error" : "hint"}">${esc(awErr || ptsErr || "Loading…")}</p></div>`;
      return;
    }
    const thead = mode === "3000" ? `<tr><th>RWY</th><th>Approach point</th><th>Wind</th><th>H/T</th><th>XW</th></tr>`
      : `<tr><th rowspan="2">RWY</th><th colspan="2">METAR</th><th colspan="2">Model 10 m</th></tr><tr><th>H/T</th><th>XW</th><th>H/T</th><th>XW</th></tr>`;
    const rows = aw.runways.map((r) => {
      const cls = [r.designator === rwy ? "sel" : "", ...roles(r.designator)].join(" ");
      const cells = mode === "3000"
        ? `<td class="pt"><b>${esc(r.fix || CL3)} <span>${nm(r.dist_nm)} NM</span></b><small>${esc(r.method_label)}</small></td>
          <td class="num w">${windVec(r.w3000)}</td><td class="num">${hwTxt(r.c3000.hw)}</td><td class="num">${xwTxt(r.c3000.xw)}</td>`
        : `<td class="num">${hwTxt(r.c_metar.hw)}</td><td class="num">${xwTxt(r.c_metar.xw)}</td>
          <td class="num">${hwTxt(r.c_model.hw)}</td><td class="num">${xwTxt(r.c_model.xw)}</td>`;
      return `<tr data-rwy="${esc(r.designator)}" class="${cls}" title="${esc(pointTip(r))}"><td class="rwy"><b>${esc(r.designator)}</b><span class="wnd-tags">${tags(r.designator)}</span></td>${cells}</tr>`;
    }).join("");
    el.innerHTML = `<div class="card wnd-card">${head}
      <div class="wnd-sfc"><span><i>0 ft METAR</i><b>${windVec(aw.metar_wind)}</b></span><span><i>0 ft model 10 m</i><b>${windVec(aw.model_surface)}</b></span></div>
      <table class="data wnd-tab"><thead>${thead}</thead><tbody>${rows}</tbody></table>
      ${[aw.model_error, aw.metar_error].filter(Boolean).map((e) => `<p class="error">${esc(e)}</p>`).join("")}
      ${forecastNote(aw) ? `<p class="wnd-note">${esc(forecastNote(aw))}</p>` : ""}
      ${mode === "3000" ? `<p class="wnd-note">${CL3}: point on the extended centreline where a 3° path reaches 3000 ft.
        Click a RWY to move the map forecast point there.</p>`
        : `<p class="wnd-note">0 ft wind: METAR and 10 m model over the aerodrome reference point; components relative to each RWY heading.</p>`}
      <p class="wnd-note">H = headwind, T = tailwind, L/R = crosswind from the left/right, kt. ${inUse ? `ARR/DEP: RWY in use (${inUse.source === "ATIS" ? "ATIS" : "? = system suggestion"}).` : ""}</p>
    </div>`;
  };

  const loadWind = async () => {
    const my = seq;
    try {
      const d = await api(`/api/meteo/approach-wind/${icao}`);
      if (dead || my !== seq) return;
      aw = d;
      awErr = "";
    } catch (e) {
      if (dead || my !== seq) return;
      awErr = e.message;
    }
    side();
  };

  const pick = async (code) => {
    icao = code;
    lsSet("meteo.wind.ad", icao);
    ad = ads.find((a) => a.icao === icao) || null;
    rwy = lsGet(rwyKey());
    if (!ad?.runways.some((r) => r.designator === rwy)) rwy = null;
    inUse = aw = null;
    awErr = "";
    const my = ++seq;
    if (mode === "0" || rwy) frame();   // punkt prognozy już znany; w 3000 ft bez wybranego pasa czekamy na pas w użyciu
    bar();
    side();
    loadWind();
    // pas do lądowania w użyciu (ATIS albo sugestia systemu) jako domyślny, jeśli odpowiedź przyjdzie szybko
    const st = api(`/api/aerodromes/${icao}/status`).then((x) => x.runway_in_use || null).catch(() => null);
    const first = await Promise.race([st, new Promise((res) => setTimeout(() => res(null), 1500))]);
    if (dead || my !== seq) return;
    inUse = first;
    if (!rwy) rwy = (ad?.runways.some((r) => r.designator === inUse?.arr) ? inUse.arr : ad?.runways[0]?.designator) || null;
    bar();
    frame();
    side();
    st.then((u) => { if (!dead && my === seq && u && !inUse) { inUse = u; bar(); side(); } });
  };

  wrap.querySelector(".wnd-mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-m]");
    if (!b || b.dataset.m === mode) return;
    mode = b.dataset.m;
    bar();
    frame();
    side();
  });
  const choose = (e) => {
    const t = e.target.closest("[data-rwy]");
    if (!t || !ad) return;
    rwy = t.dataset.rwy;
    lsSet(rwyKey(), rwy);
    bar();
    frame();
    side();
  };
  $(".wnd-rwys").addEventListener("click", choose);
  $(".wnd-side").addEventListener("click", choose);
  $(".wnd-aero").addEventListener("change", (e) => pick(e.target.value));

  bar();
  side();
  const init = async () => {
    try {
      ads = (await api("/api/meteo/approach-points")).aerodromes;
      ptsErr = "";
    } catch (e) { ptsErr = `Approach points: ${e.message}`; }
    if (dead) return;
    if (ads.length && !ads.some((a) => a.icao === icao)) icao = ads.some((a) => a.icao === "EPWA") ? "EPWA" : ads[0].icao;
    const opt = (a) => `<option value="${a.icao}"${a.icao === icao ? " selected" : ""}>${a.icao} ${esc(a.name)}</option>`;
    const main = ads.filter((a) => MAIN_AD.includes(a.icao)), rest = ads.filter((a) => !MAIN_AD.includes(a.icao));
    $(".wnd-aero").innerHTML = ads.length ? `<optgroup label="Main aerodromes">${main.map(opt).join("")}</optgroup><optgroup label="Other">${rest.map(opt).join("")}</optgroup>`
      : `<option>${esc(icao)}</option>`;
    pick(icao);
  };
  init();
  const timer = setInterval(() => { if (!document.hidden) loadWind(); }, 600000);
  // serwer wrócił po przerwie: brakujące punkty podejścia albo wiatr pobieramy od razu, nie po 10 min
  const online = () => (!ads.length ? init() : awErr && loadWind());
  window.addEventListener(ONLINE_EVENT, online);
  return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); } };
}

// --- GAMET: prognoza obszarowa IMGW dla rejonów A1–A5 FIR EPWW (tekst z backendu: services/gamet.py) obok mapy rejonów
// z awiacja.imgw.pl (obraz wczytuje przeglądarka, bez Referer, jak SIGWX). Wybór rejonu jak sektory SIGWX w PANDORZE.
export const GAMET_AREAS = ["A1", "A2", "A3", "A4", "A5"];
export const GAMET_MAP_URL = "https://awiacja.imgw.pl/assets/img/gamet-map.webp";
export const GAMET_PAGE = "https://awiacja.imgw.pl/prognozy-lotnicze/gamet";
export const GAMET_REFRESH = 10 * 60000;   // nowy tekst co 10 min (GAMET co 6 h plus poprawki)
// zapamiętany wybór: rejon A1–A5 albo ALL (wszystkie jeden pod drugim, domyślnie)
export const gametArea = (v) => (v === "ALL" || GAMET_AREAS.includes(v) ? v : "ALL");
// rejony do pokazania: ALL = wszystkie z odpowiedzi (A1–A5 i ewentualne inne), inaczej tylko wybrany
export const gametShown = (areas, sel) => (sel === "ALL" ? Object.keys(areas || {}).sort() : [sel]);
// "2026-10-15T04:00Z" -> "15.10 04:00"
const dm = (t) => `${t.slice(8, 10)}.${t.slice(5, 7)}`;
// ważność rejonu: "15.10 04:00–10:00Z", przez północ "15.10 22:00 – 16.10 04:00Z"; bez dat sam napis z VALID
export function gametValidTxt(a) {
  if (!a?.valid_from || !a?.valid_to) return a?.valid || "";
  const f = a.valid_from, t = a.valid_to;
  return f.slice(0, 10) === t.slice(0, 10) ? `${dm(f)} ${f.slice(11, 16)}–${t.slice(11, 16)}Z`
    : `${dm(f)} ${f.slice(11, 16)} – ${dm(t)} ${t.slice(11, 16)}Z`;
}
export const gametExpired = (a, now = Date.now()) => !!a?.valid_to && Date.parse(a.valid_to) <= now;

function gametTab(pane) {
  const wrap = h(`<div class="mimg gmt">
    <div class="mimg-bar">
      <b class="mimg-title">GAMET</b>
      <span class="mimg-seg gmt-areas">${[...GAMET_AREAS, "ALL"].map((a) => `<button data-area="${a}"
        title="${a === "ALL" ? "All areas, one below the other" : `Area ${a}`}">${a}</button>`).join("")}</span>
      <span class="mimg-hint gmt-hint"></span>
      <a class="btn mimg-open" href="${GAMET_PAGE}" target="_blank" rel="noopener noreferrer"
        title="Open the GAMET page in a new tab">GAMET page ↗</a>
    </div>
    <div class="gmt-body">
      <div class="gmt-text"><p class="hint">Loading GAMET…</p></div>
      <div class="gmt-map"><div class="gmt-imgmsg" hidden></div></div>
    </div>
  </div>`);
  pane.append(wrap);
  const $ = (s) => wrap.querySelector(s);
  let area = gametArea(lsGet("meteo.gamet.area")), data = null, err = "", last = 0, dead = false;
  const shown = () => !document.hidden && wrap.offsetParent !== null;

  // mapa rejonów: nie wczytała się (np. serwer IMGW nie wydaje obrazu innym stronom) = krótka uwaga zamiast obrazu
  const im = imgEl("GAMET areas A1–A5 map");
  im.className = "gmt-img";
  im.onerror = () => {
    if (dead) return;
    im.hidden = true;
    $(".gmt-map").classList.add("off");   // wąska kolumna z uwagą, więcej miejsca na tekst
    const m = $(".gmt-imgmsg");
    m.hidden = false;
    m.innerHTML = `<span>GAMET areas map failed to load.</span>
      <a href="${GAMET_MAP_URL}" target="_blank" rel="noopener noreferrer">open map ↗</a>`;
  };
  $(".gmt-map").prepend(im);
  im.src = GAMET_MAP_URL;

  const draw = () => {
    wrap.querySelectorAll(".gmt-areas button").forEach((b) => b.classList.toggle("active", b.dataset.area === area));
    const hint = $(".gmt-hint");
    const at = data?.fetched_at ? `fetched ${data.fetched_at.slice(11, 16)}Z` : "";
    hint.textContent = ["FIR EPWW", at, data?.stale ? "old data: no response" : ""].filter(Boolean).join(" · ");
    hint.title = `GAMET (area forecast for low-level flights), refreshed every ${GAMET_REFRESH / 60000} min.`;
    if (!data && !err) return;
    const link = `<a href="${GAMET_PAGE}" target="_blank" rel="noopener noreferrer">GAMET page ↗</a>`;
    const error = err || data?.error;
    const areas = data?.areas || {};
    const body = gametShown(areas, area).map((k) => {
      const a = areas[k] || {}, valid = gametValidTxt(a), old = gametExpired(a);
      return `<section class="gmt-area" data-area="${esc(k)}"><h4><b>${esc(k)}</b>${a.below ? `<span>BLW ${esc(a.below)}</span>` : ""}
        ${valid ? `<span class="${old ? "old" : ""}" title="${old ? "Validity expired" : "Forecast validity"}">valid ${esc(valid)}</span>` : ""}
        ${a.issued ? `<span>issued ${esc(a.issued.slice(11, 16))}Z</span>` : ""}</h4>
        ${a.text ? `<pre>${esc(a.text)}</pre>` : `<p class="hint">No GAMET for area ${esc(k)}.</p>`}</section>`;
    }).join("");
    // bez żadnego komunikatu (serwer IMGW nie odpowiada): sam błąd z odnośnikiem, bez pięciu pustych rejonów
    const any = Object.values(areas).some((a) => a?.text);
    $(".gmt-text").innerHTML = (error ? `<p class="error">${esc(error)} · ${link}</p>` : "") + (any ? body : "");
  };

  const load = async () => {
    last = Date.now();
    try {
      const d = await api("/api/meteo/gamet");
      if (dead) return;
      data = d;
      err = "";
    } catch (e) {
      if (dead) return;
      err = e.message;
    }
    draw();
  };
  $(".gmt-areas").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-area]");
    if (!b) return;
    area = b.dataset.area;
    lsSet("meteo.gamet.area", area);
    draw();
  });
  draw();
  load();
  // co 10 min, tylko gdy METEO jest na ekranie; po powrocie zaległe odświeżenie w ciągu 10 s
  const timer = setInterval(() => { if (shown() && Date.now() - last >= GAMET_REFRESH) load(); }, 10000);
  const online = () => err && load();   // serwer PolIDS wrócił, a na ekranie jest komunikat błędu
  window.addEventListener(ONLINE_EVENT, online);
  return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); } };
}

// --- ICING: Windy, warstwa "icing" (prawdopodobieństwo oblodzenia w locie) na wybranym poziomie ciśnienia;
// poziomy jak w PANDORZE w FL (wysokość ciśnienia wg atmosfery wzorcowej ISA)
export const ICING_LEVELS = [["850h", "FL050"], ["700h", "FL100"], ["600h", "FL140"], ["500h", "FL180"], ["400h", "FL240"],
  ["300h", "FL300"]];
export const icingLevel = (v) => (ICING_LEVELS.some(([l]) => l === v) ? v : WINDY_VIEWS.icing.level);

function icingTab(pane) {
  const wrap = h(`<div class="mimg icg">
    <div class="mimg-bar">
      <b class="mimg-title">ICING</b>
      <span class="mimg-seg icg-levels">${ICING_LEVELS.map(([l, fl]) => `<button data-level="${l}"
        title="${l.slice(0, -1)} hPa ≈ ${fl}">${fl}</button>`).join("")}</span>
      <span class="mimg-hint icg-hint"></span>
    </div>
    <iframe class="embed icg-frame" allowfullscreen></iframe>
  </div>`);
  pane.append(wrap);
  let level = icingLevel(lsGet("meteo.icing.level")), frame = wrap.querySelector(".icg-frame");
  const show = () => {
    const fl = ICING_LEVELS.find(([l]) => l === level)[1];
    wrap.querySelectorAll(".icg-levels button").forEach((b) => b.classList.toggle("active", b.dataset.level === level));
    const hint = wrap.querySelector(".icg-hint");
    hint.textContent = `Icing ${level.slice(0, -1)} hPa ≈ ${fl}`;
    hint.title = `Probability of in-flight icing at ${level.slice(0, -1)} hPa (≈ ${fl} in ISA).`;
    // nowa ramka zamiast zmiany src: bez kroku w historii przeglądarki (← i Wstecz cofają ekrany, nie ramkę Windy)
    frame = frameGo(frame, windyEmbedUrl({ ...WINDY_VIEWS.icing, level }));
  };
  wrap.querySelector(".icg-levels").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-level]");
    if (!b || b.dataset.level === level) return;
    level = b.dataset.level;
    lsSet("meteo.icing.level", level);
    show();
  });
  show();
}

// --- SUN: dzień i noc na mapie świata (granica cienia, pas zmierzchu cywilnego, punkt podsłoneczny; co minutę)
// oraz wschód i zachód słońca dziś i jutro dla lotniska albo klikniętego punktu (backend: /api/meteo/sun)
export const SUN_TICK = 60000;               // mapa i "teraz" co minutę
export const SUN_REFRESH = 10 * 60000;       // godziny wschodu i zachodu z serwera co 10 min (i po zmianie doby)
const SUN_ROWS = [["civil_dawn", "BMCT", "beginning of morning civil twilight (sun 6° below the horizon)"],
  ["sunrise", "Sunrise", "sunrise (SR): upper limb on the horizon"], ["noon", "Noon", "sun at its highest (solar noon)"],
  ["sunset", "Sunset", "sunset (SS)"], ["civil_dusk", "EECT", "end of evening civil twilight (sun 6° below the horizon)"]];
const SUN_NEXT = { civil_dawn: "BMCT", sunrise: "sunrise", sunset: "sunset", civil_dusk: "EECT" };
const SUN_STATE = { day: "DAY", civil: "CIVIL TWILIGHT", night: "NIGHT" };
const PT_MAP = "Point on map";
// kod lotniska z pola: wielkie litery, 3–4 znaki, inaczej ""
export const sunIcao = (v) => { const s = String(v || "").trim().toUpperCase(); return /^[A-Z0-9]{3,4}$/.test(s) ? s : ""; };
// czas zdarzenia "05:01Z", zaokrąglony do minuty; data, gdy wypada innego dnia UTC niż kolumna (np. wschód w Tokio)
export function sunCell(iso, day, local = null) {
  if (!iso) return "–";
  const t = new Date(Date.parse(iso) + 30000).toISOString();
  return `${t.slice(11, 16)}Z${t.slice(0, 10) !== day ? ` <small class="d">${dm(t)}</small>` : ""}`
    + (local ? `<small class="loc">${esc(local.hm)} ${esc(local.tz)}</small>` : "");
}
// "10 h 41 min", "24 h", "0 min"
export const durTxt = (min) => (min === null || min === undefined ? "–"
  : `${Math.floor(min / 60) ? `${Math.floor(min / 60)} h` : ""}${min % 60 || !Math.floor(min / 60) ? ` ${min % 60} min` : ""}`.trim());
// odliczanie do zdarzenia: "in 3 h 12 min", "in 5 min", "in <1 min"
export const untilTxt = (ms) => (ms < 60000 ? "in <1 min" : `in ${durTxt(Math.floor(ms / 60000))}`);
// opis doby bez wschodu lub zmierzchu (dzień / noc polarna, białe noce) albo z jednym z nich (dzień przejścia: wschód bez
// zachodu = słońce nie zachodzi do końca doby, zachód bez wschodu = było nad horyzontem od jej początku)
export function polarTxt(d) {
  if (d.polar === "day") return "polar day: sun above the horizon all day";
  if (d.polar === "night") return d.civil_polar === "night" ? "polar night: sun more than 6° below the horizon all day"
    : "polar night: sun below the horizon all day";
  if (d.sunrise && !d.sunset) return "polar day begins: after sunrise the sun does not set until the end of the day";
  if (!d.sunrise && d.sunset) return "polar day ends: sun above the horizon from the start of the day until sunset";
  if (d.civil_polar === "day") return "white nights: the sun does not go 6° below the horizon (no BMCT or EECT)";
  if (d.civil_dawn && !d.civil_dusk) return "white nights begin: after BMCT the sun no longer goes 6° below the horizon (no EECT)";
  if (!d.civil_dawn && d.civil_dusk) return "white nights end: sun 6° below the horizon only after EECT (no BMCT)";
  return "";
}
// najbliższe zdarzenie: pierwsze jeszcze nieminione z listy z serwera (po zachodzie od razu EECT, bez czekania na
// kolejne pobranie); starsza odpowiedź bez listy: samo "next"
export const sunNext = (data, now) => (data?.upcoming || (data?.next ? [data.next] : []))
  .find((e) => Date.parse(e.at) > now) || null;
// zoom na start: cały świat (256 px · 2^zoom) mieści się w szerokości mapy, co 0,25, co najmniej 1; wolne miejsce po
// bokach to kopie świata (cień i siatka sięgają ±540°), nad biegunami tło mapy
export const sunZoom = (width) => Math.max(1, Math.floor(4 * Math.log2(Math.max(width || 0, 256) / 256)) / 4);
// długość lon na tej kopii świata, która leży najbliżej ref (kliknięte miejsce albo środek widoku)
export const nearLon = (lon, ref) => lon + 360 * Math.round((ref - lon) / 360);
// pole lotniska: zapytanie o kod ICAO albo (zły format) brak zapytania, błąd i wpisany tekst do nagłówka karty
export function sunQuery(value) {
  const icao = sunIcao(value);
  return icao ? { q: { icao }, err: "", label: icao }
    : { q: null, err: "Enter an aerodrome ICAO code (3–4 characters)", label: String(value || "").trim().toUpperCase().slice(0, 12) };
}

function sunTab(ctx) {
  return (pane) => {
    const wrap = h(`<div class="mimg sun">
      <div class="mimg-bar">
        <b class="mimg-title">SUN</b>
        <label class="sun-l">Aerodrome <input type="text" class="sun-icao" maxlength="4" size="5" spellcheck="false"
          title="ICAO code of any aerodrome"></label>
        <button class="btn primary sun-go">Show</button>
        <span class="mimg-hint sun-hint"></span>
      </div>
      <div class="sun-body"><div class="map sun-map"></div><aside class="sun-side"></aside></div>
    </div>`);
    pane.append(wrap);
    const $ = (s) => wrap.querySelector(s);
    const input = $(".sun-icao");
    input.value = sunIcao(lsGet("meteo.sun.icao")) || "EPWA";
    const shown = () => !document.hidden && wrap.offsetParent !== null;

    // na start cały świat w szerokości mapy (cała granica cienia, także nad Pacyfikiem)
    const map = L.map($(".sun-map"), { worldCopyJump: true, minZoom: 1, maxZoom: 10, zoomSnap: 0.25, zoomDelta: 0.5 })
      .setView([0, 15], sunZoom($(".sun-map").getBoundingClientRect().width));
    BASEMAPS.dark(L, ctx?.config?.carto_api_key).addTo(map);
    // zmierzch cywilny (słońce 0,8°–6° pod horyzontem) jaśniej, noc (niżej niż 6°) ciemniej: dwie nałożone czasze
    const twi = L.polygon([], { className: "sun-twi", stroke: false, interactive: false }).addTo(map);
    const night = L.polygon([], { className: "sun-night", stroke: false, interactive: false }).addTo(map);
    // siatka bez kafelków (gdy podkład się nie wczyta, granica cienia nadal ma odniesienie): równik, zwrotniki, koła
    // podbiegunowe i południki co 30°, na pięć obiegów długości jak cień
    const grat = L.layerGroup().addTo(map), lons = [-540, -180, 180, 540];
    [[0, ""], [23.44, " dash"], [-23.44, " dash"], [66.56, " dash"], [-66.56, " dash"]].forEach(([la, c]) =>
      L.polyline(lons.map((lo) => [la, lo]), { className: "sun-grat" + c, interactive: false }).addTo(grat));
    for (let lo = -540; lo <= 540; lo += 30) L.polyline([[-85, lo], [85, lo]], { className: "sun-grat", interactive: false }).addTo(grat);
    const sub = L.circleMarker([0, 0], { radius: 8, className: "sun-subsolar", interactive: true }).addTo(map);
    const place = L.circleMarker([0, 0], { radius: 6, className: "sun-place" });
    // q: zapytanie ({icao} albo {lat, lon}; ref = długość znacznika na kopii świata, na której go widać), cardTitle:
    // nagłówek karty przed odpowiedzią serwera i przy błędzie
    let q = null, cardTitle = "", data = null, err = "", seq = 0, last = 0, dead = false, day0 = "";

    const side = () => {
      const el = $(".sun-side");
      if (!data) {
        el.innerHTML = `<div class="card wnd-card sun-card"><h3>${esc(cardTitle || "Sun")}</h3>
          <p class="${err ? "error" : "hint"}">${esc(err || "Loading…")}</p></div>`;
        return;
      }
      const now = Date.now(), elev = sunElevation(data.lat, data.lon, now), st = sunState(elev);
      const today = new Date(now).toISOString().slice(0, 10);
      const nxt = sunNext(data, now);
      const head = data.icao ? `${esc(data.icao)}${data.name ? ` · ${esc(data.name)}` : ""}` : PT_MAP;
      const rows = SUN_ROWS.map(([k, label, tip]) => `<tr title="${esc(tip)}"><td>${label}</td>${data.days.map((d) =>
        `<td class="num">${sunCell(d[k], d.date, d.local?.[k])}</td>`).join("")}</tr>`).join("");
      const notes = data.days.map((d) => polarTxt(d) && `${dm(d.date)}: ${polarTxt(d)}`).filter(Boolean);
      el.innerHTML = `<div class="card wnd-card sun-card"><h3>${head}</h3>
        <div class="sun-pos">${latLonTxt(data.lat, data.lon)}</div>
        <div class="sun-now ${st}"><b>${SUN_STATE[st]}</b> sun ${Math.abs(elev).toFixed(1)}° ${elev >= 0 ? "above" : "below"} the horizon</div>
        ${nxt ? `<div class="sun-next">Next: <b>${SUN_NEXT[nxt.event]} ${sunCell(nxt.at, today)}</b>${nxt.local ? ` (${esc(nxt.local.hm)} ${esc(nxt.local.tz)})` : ""}
          · ${untilTxt(Date.parse(nxt.at) - now)}</div>` : ""}
        <table class="data sun-tab"><thead><tr><th></th>${data.days.map((d, i) => `<th class="num">${i ? "Tomorrow" : "Today"} ${dm(d.date)}</th>`).join("")}</tr></thead>
          <tbody>${rows}<tr title="from sunrise to sunset"><td>Daylight</td>${data.days.map((d) => `<td class="num">${durTxt(d.day_length)}</td>`).join("")}</tr></tbody></table>
        ${notes.map((n) => `<p class="sun-polar">${esc(n)}</p>`).join("")}
        <p class="wnd-note">Times in UTC${data.polish ? ", Poland (LT) below them" : ""}. The day follows local solar time, so far from
          Greenwich sunrise or sunset may fall on another UTC date (date next to the time). Sunrise and sunset: upper limb on the
          horizon (with refraction); BMCT and EECT: centre of the disc 6° below the horizon.</p>
      </div>
      <div class="card wnd-card sun-card"><h3>Map</h3>
        <div class="sun-legend"><span><i class="lg-day"></i>day</span><span><i class="lg-twi"></i>civil twilight</span>
          <span><i class="lg-night"></i>night</span><span><i class="lg-sub"></i>sun at zenith</span></div>
        <p class="wnd-note">Click the map: sun at any point. Day/night boundary refreshed every minute.</p></div>`;
    };

    const tick = () => {
      const now = Date.now(), s = subsolarPoint(now);
      twi.setLatLngs(nightRings(now, SR_ALT).map((r) => [r]));
      night.setLatLngs(nightRings(now, CIVIL_ALT).map((r) => [r]));
      sub.setLatLng([s.lat, s.lon]);
      sub.unbindTooltip().bindTooltip(`Sun at zenith: ${latLonTxt(s.lat, s.lon)}`, { direction: "top", offset: [0, -6],
        className: "sun-tip" });
      const hint = $(".sun-hint");
      hint.textContent = `${new Date(now).toISOString().slice(11, 16)}Z · sun at zenith ${latLonTxt(s.lat, s.lon)}`;
      hint.title = "Day/night boundary refreshed every minute. Click the map: sun at that point.";
      const today = new Date(now).toISOString().slice(0, 10);
      if (q && (today !== day0 || now - last >= SUN_REFRESH)) load();   // nowa doba UTC: dziś i jutro od nowa
      else if (data) side();
    };

    const load = async () => {
      const my = ++seq;
      last = Date.now();
      day0 = new Date(last).toISOString().slice(0, 10);
      const qs = q.icao ? `icao=${encodeURIComponent(q.icao)}` : `lat=${q.lat.toFixed(4)}&lon=${q.lon.toFixed(4)}`;
      try {
        const d = await api(`/api/meteo/sun?${qs}`);
        if (dead || my !== seq) return;
        data = d;
        err = "";
        if (q.icao) lsSet("meteo.sun.icao", d.icao || q.icao);   // zapamiętane tylko lotnisko, które serwer zna
        // znacznik na kopii świata klikniętej albo najbliższej środka widoku: bez przeskoku mapy o pełny obrót
        q.ref = nearLon(d.lon, q.ref ?? map.getCenter().lng);
        place.setLatLng([d.lat, q.ref]).addTo(map);
        place.unbindTooltip().bindTooltip(d.icao || latLonTxt(d.lat, d.lon), { permanent: true, direction: "right",
          offset: [8, 0], className: "sun-tip" });
        if (!map.getBounds().contains(place.getLatLng())) map.panTo(place.getLatLng());
      } catch (e) {
        if (dead || my !== seq) return;
        data = null;
        err = e.message;
        place.remove();
      }
      side();
    };
    const pick = (next, title) => {
      q = next;
      cardTitle = title;
      data = null;
      err = "";
      side();
      load();
    };
    const go = () => {
      const r = sunQuery(input.value);
      if (!r.q) {
        // zły format: bez zapytania i bez znacznika (zegar ani powrót serwera nie wczytają znów poprzedniego miejsca)
        seq++;
        q = null; cardTitle = r.label; data = null; err = r.err;
        place.remove();
        side();
        return;
      }
      input.value = r.q.icao;
      pick(r.q, r.label);
    };
    $(".sun-go").addEventListener("click", go);
    input.addEventListener("keydown", (e) => e.key === "Enter" && go());
    // do serwera długość -180..180, znacznik w klikniętym miejscu (także na kopii świata za linią zmiany daty)
    map.on("click", (e) => pick({ lat: e.latlng.lat, lon: wrapLon(e.latlng.lng), ref: e.latlng.lng }, PT_MAP));
    // po przesunięciu mapy znacznik poza widokiem: na kopię świata najbliższą środka (worldCopyJump przenosi widok o obrót)
    map.on("moveend", () => {
      if (!data || !q || !map.hasLayer(place) || map.getBounds().contains(place.getLatLng())) return;
      q.ref = nearLon(q.ref, map.getCenter().lng);
      place.setLatLng([data.lat, q.ref]);
    });

    tick();
    go();
    const timer = setInterval(() => { if (shown()) tick(); }, SUN_TICK);
    const online = () => err && q && load();
    window.addEventListener(ONLINE_EVENT, online);
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe($(".sun-map"));
    return { destroy: () => { dead = true; clearInterval(timer); window.removeEventListener(ONLINE_EVENT, online); ro.disconnect(); map.remove(); } };
  };
}

export default {
  mount(root, ctx) {
    // kolejność z issue #13 i #18: METAR i TAF, odstęp, WIND i RADAR (środkowa grupa, issue #18), odstęp, GAMET, SIGWX,
    // ICING, QNH, SAT EUR, SAT PL, TURB, SUN
    subtabs(root, [
      { id: "metar-pl", label: "METAR PL", render: wxList("metar", PL_CIV, "meteo.metar.pl") },
      { id: "metar-mil", label: "METAR MIL", render: wxList("metar", PL_MIL, "meteo.metar.mil") },
      { id: "metar-intl", label: "METAR INTL", render: wxList("metar", INTL, "meteo.metar.intl") },
      { id: "taf-pl", label: "TAF PL", render: wxList("taf", PL_CIV, "meteo.taf.pl") },
      { id: "taf-intl", label: "TAF INTL", render: wxList("taf", INTL, "meteo.taf.intl") },
      { sep: true },
      { id: "wind", label: "WIND", fill: true, render: windTab },
      { id: "radar", label: "RADAR", fill: true, render: windy("radar") },
      { sep: true },
      { id: "gamet", label: "GAMET", fill: true, render: gametTab },
      { id: "sigwx", label: "SIGWX", fill: true, render: imgView({ key: "sigwx", title: "SIGWX", frames: [{ label: "", url: SIGWX_URL }],
        note: "SFC–FL100", desc: "significant weather chart SFC–FL100 (FIR EPWW)" }) },
      { id: "icing", label: "ICING", fill: true, render: icingTab },
      { id: "qnh", label: "QNH", fill: true, render: qnhMap },
      { id: "sat-eur", label: "SAT EUR", fill: true, render: windy("sat-eur") },
      { id: "sat-pl", label: "SAT PL", fill: true, render: windy("sat-pl") },
      { id: "turb", label: "TURB", fill: true, render: imgView({ key: "turb", title: "TURB", frames: turbFrames(),
        note: "airliners", desc: "turbulence forecast for airliners" }) },
      { id: "sun", label: "SUN", fill: true, render: sunTab(ctx) },
    ]);
  },
};
