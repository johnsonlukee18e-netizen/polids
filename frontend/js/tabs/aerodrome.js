import { api, esc, fmt, h, hhmm, positionTip, vatsimBookings, vatsimOnline, lsGet, lsSet } from "../api.js";
import { colorize, wxLines } from "./meteo.js";
import { mountAwos } from "../awos.js";
import { mountStrips } from "../strips.js";

const TYPE_ORDER = ["CTR", "FSS", "APP", "DEP", "TWR", "GND", "DEL", "ATIS"];
const byType = (a, b) => TYPE_ORDER.indexOf(a.callsign.split("_").pop()) - TYPE_ORDER.indexOf(b.callsign.split("_").pop()) || a.callsign.localeCompare(b.callsign);

// Czas obserwacji METAR (np. 051630Z) i ile minut temu
function obsAge(time) {
  const m = /^(\d{2})(\d{2})(\d{2})Z$/.exec(time || "");
  if (!m) return null;
  const now = new Date();
  let t = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), +m[1], +m[2], +m[3]);
  if (t - now.getTime() > 86400000) t = Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, +m[1], +m[2], +m[3]);
  return Math.round((now.getTime() - t) / 60000);
}

function lvpBox(lvp) {
  if (!lvp) return "";
  const th = lvp.thresholds;
  const rule = `LVP: RVR/widzialność < ${th.lvp.rvr_m} m lub podstawa ≤ ${th.lvp.ceiling_ft} ft · przygotowanie: < ${th.prep.rvr_m} m lub ≤ ${th.prep.ceiling_ft} ft`;
  if (!lvp.state) return `<div class="lvp lvp-off" data-tip="${esc(rule)}">LVP <span>nie obowiązują</span></div>`;
  const label = lvp.state === "LVP" ? "LVP W MOCY" : "PRZYGOTOWANIE LVP";
  return `<div class="lvp lvp-${lvp.state.toLowerCase()}" data-tip="${esc(rule)}">${label}<span>${lvp.reasons.map(esc).join("<br>")}</span></div>`;
}

// Róża wiatrów: pasy jako prostokąty, strzałka wiatru skąd wieje.
// Kolor = rola: ARR zielony, DEP niebieski (ten sam pas do obu: połowa na połowę).
// Wypełnienie pełne = pas w użyciu wg ATIS; kreskowane = pas preferowany (sugestia systemu).
const USE_COLOR = { arr: "#5fd23a", dep: "#3ec7e0" };
const ROLE_LABEL = { arr: "ARR", dep: "DEP" };
function roleSets(status) {
  const use = status.runway_in_use || {};
  const pref = status.preferred || {};
  const atis = use.source === "ATIS" ? use : null;
  const sugg = atis ? pref : (pref.arr ? pref : use);
  // sugestię pokazujemy tylko tam, gdzie różni się od ATIS
  const s = { arr: sugg.arr, dep: sugg.dep || sugg.arr };
  if (atis) { if (s.arr === atis.arr) s.arr = null; if (s.dep === (atis.dep || atis.arr)) s.dep = null; }
  return { active: atis ? { arr: atis.arr, dep: atis.dep || atis.arr } : {}, sugg: s };
}
function windrose(status) {
  const p = status.parsed || {};
  const { active, sugg } = roleSets(status);
  const size = 280, c = size / 2, r = 112;
  const pt = (deg, d) => [c + Math.sin(deg * Math.PI / 180) * d, c - Math.cos(deg * Math.PI / 180) * d];
  const pairs = [];
  status.runways.forEach((x) => {
    const key = Math.round((x.heading % 180) / 5);
    let g = pairs.find((q) => q.key === key);
    if (!g) pairs.push(g = { key, ends: [] });
    if (!g.ends.some((e) => e.designator === x.designator)) g.ends.push(x);
  });
  const ticks = Array.from({ length: 36 }, (_, i) => {
    const [x1, y1] = pt(i * 10, r), [x2, y2] = pt(i * 10, r - (i % 9 === 0 ? 12 : 6));
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#9aa4af"/>`;
  }).join("");
  const labels = ["N", "E", "S", "W"].map((t, i) => {
    const [x, y] = pt(i * 90, r + 13);
    return `<text x="${x}" y="${y + 4}" fill="#9aa4af" font-size="12" text-anchor="middle">${t}</text>`;
  }).join("");
  const defs = `<defs>${["arr", "dep"].map((k) => `<pattern id="wr-h-${k}" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
    <rect width="6" height="6" fill="#151a1f"/><rect width="3" height="6" fill="${USE_COLOR[k]}"/></pattern>`).join("")}</defs>`;
  const rolesOf = (set, d) => ["arr", "dep"].filter((k) => set[k] === d);
  let rw = "", marks = "";
  pairs.forEach((g) => {
    const hdg = g.ends[0].heading;
    const act = [...new Set(g.ends.flatMap((e) => rolesOf(active, e.designator)))];
    const sug = [...new Set(g.ends.flatMap((e) => rolesOf(sugg, e.designator)))];
    const roles = act.length ? act : sug;
    const solid = act.length > 0;
    const fill = (k) => (solid ? USE_COLOR[k] : `url(#wr-h-${k})`);
    const tr = `transform="rotate(${hdg} ${c} ${c})"`;
    if (!roles.length) {
      rw += `<rect x="${c - 7}" y="${c - 72}" width="14" height="144" fill="#555" stroke="#888" ${tr}/>`;
    } else if (roles.length === 1) {
      rw += `<rect x="${c - 7}" y="${c - 72}" width="14" height="144" fill="${fill(roles[0])}" ${tr}/>`;
    } else {
      rw += `<rect x="${c - 7}" y="${c - 72}" width="7" height="144" fill="${fill("arr")}" ${tr}/><rect x="${c}" y="${c - 72}" width="7" height="144" fill="${fill("dep")}" ${tr}/>`;
    }
    if (roles.length) {
      rw += `<rect x="${c - 7}" y="${c - 72}" width="14" height="144" fill="none" stroke="#fff" stroke-width="1.5" ${solid ? "" : 'stroke-dasharray="5 3"'} ${tr}/>`;
    }
    g.ends.forEach((e) => {
      const ra = rolesOf(active, e.designator), rs = rolesOf(sugg, e.designator);
      const ro = ra.length ? ra : rs;
      // oznaczenie przy progu (z którego startuje / na który ląduje samolot lecący kursem pasa) i rola
      const [x, y] = pt(e.heading + 180, 88);
      const col = ro.length ? USE_COLOR[ro[0]] : "#c8ced4";
      marks += `<text x="${x}" y="${y + 3}" text-anchor="middle" font-family="monospace" font-weight="700"
        font-size="${ro.length ? 16 : 12}" fill="${col}">${esc(e.designator)}</text>`;
      if (ro.length) {
        marks += `<text x="${x}" y="${y + 15}" text-anchor="middle" font-family="monospace" font-weight="700" font-size="10"
          fill="${col}">${ro.map((k) => ROLE_LABEL[k]).join("/")}${ra.length ? "" : "?"}</text>`;
        // szewrony wzdłuż pasa w kierunku ruchu
        marks += `<g transform="rotate(${e.heading} ${c} ${c})" fill="none" stroke="#fff" stroke-width="2.5" opacity="${ra.length ? 1 : 0.7}">${[48, 12, -24]
          .map((o) => `<polyline points="${c - 5},${c + o + 6} ${c},${c + o} ${c + 5},${c + o + 6}" stroke="#000" stroke-width="5"/><polyline points="${c - 5},${c + o + 6} ${c},${c + o} ${c + 5},${c + o + 6}"/>`).join("")}</g>`;
      }
    });
  });
  let arrow = "";
  if (p.wind_dir !== null && p.wind_dir !== undefined) {
    arrow = `<g transform="rotate(${p.wind_dir} ${c} ${c})"><line x1="${c}" y1="${c - r + 4}" x2="${c}" y2="${c - 34}" stroke="#2f8fff" stroke-width="4"/>
      <polygon points="${c - 9},${c - 46} ${c + 9},${c - 46} ${c},${c - 30}" fill="#2f8fff"/></g>`;
  }
  if (p.wind_var_from !== null && p.wind_var_from !== undefined) {
    const [x1, y1] = pt(p.wind_var_from, r - 18), [x2, y2] = pt(p.wind_var_to, r - 18);
    const span = ((p.wind_var_to - p.wind_var_from) + 360) % 360;
    arrow += `<path d="M${x1},${y1} A${r - 18},${r - 18} 0 ${span > 180 ? 1 : 0} 1 ${x2},${y2}" stroke="#ffb020" stroke-width="3" fill="none"/>`;
  }
  return `<svg class="windrose" viewBox="0 0 ${size} ${size}">${defs}<circle cx="${c}" cy="${c}" r="${r}" fill="#1b1f24" stroke="#3c444e"/>${ticks}${labels}${rw}${arrow}${marks}</svg>
    <div class="wr-legend"><span><i class="sw-arr"></i>ARR</span><span><i class="sw-dep"></i>DEP</span><span><i class="sw-solid"></i>ATIS</span><span><i class="sw-hatch"></i>sugestia</span></div>`;
}

// Pas w użyciu z ATIS albo preferowany wg systemu (wiatr, wyposażenie, LVP)
function runwayBox(st) {
  const u = st.runway_in_use || {};
  const fromAtis = u.source === "ATIS";
  const atc = st.atc_online || [];
  const title = fromAtis ? `PAS W UŻYCIU · ATIS ${esc(st.atis?.letter || "")}` : "PAS PREFEROWANY";
  const body = !u.arr ? "–" : u.arr === u.dep ? `<b>${esc(u.arr)}</b>`
    : `<span>ARR</span><b style="color:${USE_COLOR.arr}">${esc(u.arr)}</b><span>DEP</span><b style="color:${USE_COLOR.dep}">${esc(u.dep)}</b>`;
  let note = fromAtis ? `${esc(st.atis.callsign)}` : esc(u.reason || "");
  if (!fromAtis && st.atis) note += `<br>ATIS ${esc(st.atis.letter || "")} online, nie udało się odczytać pasa`;
  else if (!fromAtis && atc.length) note += `<br>Kontrola online (${atc.map((c) => esc(c.callsign)).join(", ")}), brak ATIS`;
  if (fromAtis && st.preferred?.arr && st.preferred.arr !== u.arr) note += `<br><span class="hint">wg wiatru: ${esc(st.preferred.arr)}</span>`;
  return `<div class="rwy-use ${fromAtis ? "atis" : "pref"}"><div class="label">${title}</div><div class="pair">${body}</div><div class="hint">${note}</div></div>`;
}

const EQUIP_SHOW = ["ILS", "LOC", "RNP"];
function runwayTable(st) {
  const { active, sugg } = roleSets(st);
  const tags = (d) => ["arr", "dep"].map((k) => (active[k] === d ? `<span class="tag ${k}">${ROLE_LABEL[k]}</span>`
    : sugg[k] === d ? `<span class="tag ${k} sugg" title="sugestia systemu">${ROLE_LABEL[k]}?</span>` : "")).join("");
  return `<table class="data rwy-table"><thead><tr><th>Pas</th><th></th><th>Kurs</th><th>Dł. m</th><th>Podejście</th><th>Czoł.</th><th>Bocz.</th></tr></thead><tbody>
    ${st.runways.map((r) => {
      const tg = tags(r.designator);
      const eq = r.equipment || [];
      const tip = `${r.designator}: ${fmt(r.length_m, 0)} × ${fmt(r.width_m, 0)} m, ${r.surface || "?"}; podejścia: ${eq.join(", ") || "brak danych"}`;
      return `<tr class="${tg ? "inuse" : ""}" title="${esc(tip)}"><td class="rwy">${esc(r.designator)}</td><td class="tags">${tg}</td>
      <td class="num">${fmt(r.heading, 0)}°</td><td class="num">${fmt(r.length_m, 0)}</td>
      <td>${eq.filter((k) => EQUIP_SHOW.includes(k)).map((k) => `<span class="eq ${k === "ILS" ? "ils" : ""}">${k}</span>`).join("")}</td>
      <td class="num" style="color:${r.headwind < 0 ? "var(--bad)" : "inherit"}">${r.headwind === null ? "–" : (r.headwind < 0 ? "TW " : "") + Math.abs(r.headwind).toFixed(0) + " kt"}</td>
      <td class="num">${r.crosswind === null ? "–" : Math.abs(r.crosswind).toFixed(0) + " kt" + (r.crosswind > 0 ? " R" : r.crosswind < 0 ? " L" : "")}</td></tr>`;
    }).join("")}
  </tbody></table><div class="hint">TW = wiatr w plecy · ARR? / DEP? = sugestia systemu · najedź na pas: szerokość, nawierzchnia, podejścia</div>`;
}

// NOTAM: okres ważności względem teraz
const dm = (iso) => { const d = new Date(iso); return `${String(d.getUTCDate()).padStart(2, "0")}.${String(d.getUTCMonth() + 1).padStart(2, "0")} ${d.toISOString().slice(11, 16)}Z`; };
function span(ms) {
  const min = Math.round(Math.abs(ms) / 60000);
  if (min < 60) return `${min} min`;
  if (min < 48 * 60) return `${Math.floor(min / 60)} h ${min % 60} min`;
  return `${Math.round(min / 1440)} dni`;
}
function notamState(n, now = Date.now()) {
  const s = n.start ? Date.parse(n.start) : null, e = n.end ? Date.parse(n.end) : null;
  const endTxt = n.perm ? "PERM" : e ? `${dm(n.end)}${n.est ? " EST" : ""}` : "?";
  if (e && e < now) return { cls: "expired", txt: `WYGASŁ ${dm(n.end)}` };
  if (s && s > now) return { cls: "future", txt: `AKTYWNY OD ${dm(n.start)} (za ${span(s - now)}) do ${endTxt}` };
  if (n.perm) return { cls: "active", txt: `AKTYWNY od ${s ? dm(n.start) : "?"} · PERM` };
  if (e) return { cls: "active", txt: `AKTYWNY DO ${endTxt} (jeszcze ${span(e - now)})` };
  return { cls: "", txt: "" };
}
const NOTAM_SORT = {
  id: (a, b) => (a.id || "").localeCompare(b.id || ""),
  start: (a, b) => (a.start || "").localeCompare(b.start || ""),
  end: (a, b) => (a.perm - b.perm) || (a.end || "9").localeCompare(b.end || "9"),
};

// Ruch: paski postępu lotu w widoku RUCH (strips.js); w PRZEGLĄDZIE tylko jednowierszowe podsumowanie
function ruchLine(t, icao) {
  const local = t.departures.filter((p) => p.arrival === icao).length;
  const n = (v, one, few, many) => `<b>${v}</b> ${v === 1 ? one : v % 10 >= 2 && v % 10 <= 4 && (v % 100 < 10 || v % 100 >= 20) ? few : many}`;
  return `<div class="ruch-line"><span><s class="lg dep"></s>${n(t.departures.length - local, "odlot", "odloty", "odlotów")}</span>
    <span><s class="lg arr"></s>${n(t.arrivals.length, "przylot", "przyloty", "przylotów")}</span>
    ${local ? `<span><s class="lg loc"></s>${n(local, "lokalny", "lokalne", "lokalnych")}</span>` : ""}
    ${t.prefiles.length ? `<span><s class="lg plan"></s>${n(t.prefiles.length, "prefile", "prefile", "prefile")}</span>` : ""}
</div>`;
}

function windText(p) {
  if (!p || p.wind_speed === null) return "–";
  const dir = p.wind_variable ? "VRB" : String(p.wind_dir).padStart(3, "0");
  return `${dir}°/${p.wind_speed}${p.wind_gust ? "G" + p.wind_gust : ""} kt`;
}

// Wschód i zachód słońca oraz zmierzch cywilny (BMCT/EECT) dla lotniska, czas UTC (backend: services/sun.py)
function sunBox(sun) {
  if (!sun) return "";
  const t = (v) => esc(v || "–");
  return `<div class="sunbox ${sun.day ? "day" : "night"}" title="Słońce w UTC: BMCT = początek zmierzchu cywilnego rano, EECT = koniec wieczorem">
    <div class="label">Słońce UTC · ${sun.day ? "dzień" : "noc"}</div>
    <div><span>Wschód</span><b>${t(sun.sunrise)}</b><span>Zachód</span><b>${t(sun.sunset)}</b></div>
    <div class="hint">BMCT ${t(sun.civil_dawn)} · EECT ${t(sun.civil_dusk)}</div></div>`;
}

function value(label, v, extra = "") {
  return `<div class="card"><div class="label">${label}</div><div class="val">${v}</div>${extra}</div>`;
}

export default {
  mount(root, ctx) {
    const MAIN = ["EPWA", "EPMO", "EPKK", "EPKT", "EPGD", "EPPO", "EPWR", "EPLL", "EPRZ", "EPLB", "EPSC", "EPBY", "EPSY", "EPZG", "EPRA"].sort();
    const sub = h(`<nav class="submenu">${MAIN.map((i) => `<button data-ad="${i}">${i}</button>`).join("")}</nav>`);
    root.append(sub);
    sub.addEventListener("click", (e) => { const b = e.target.closest("button[data-ad]"); if (b) go(b.dataset.ad); });
    const pane = h(`<div class="pane ad-pane">
      <div class="toolbar">
        <input class="field ad" list="ad-list" size="10" placeholder="ICAO">
        <datalist id="ad-list"></datalist>
        <button class="btn primary go">Pokaż</button>
        <span class="ad-view"><button data-view="overview">PRZEGLĄD</button><button data-view="awos">AWOS</button><button data-view="ruch">RUCH</button></span>
        <span class="title" style="font-weight:600"></span><span style="flex:1"></span>
        <span class="hint upd"></span>
      </div>
      <div class="content"></div>
    </div>`);
    root.append(pane);
    const $ = (s) => pane.querySelector(s);
    let icao = lsGet("aerodrome.icao") || ctx.config.default_aerodrome || "EPWA";
    let timer = null;
    // widok: PRZEGLĄD (siatka poniżej), AWOS (awos.js) albo RUCH (paski EFES, strips.js); AWOS i RUCH mają własne
    // zegary sprzątane przez destroy()
    let view = ["awos", "ruch"].includes(lsGet("aerodrome.view")) ? lsGet("aerodrome.view") : "overview", awos = null, strips = null;

    api("/api/aerodromes").then((ads) => {
      $("#ad-list").innerHTML = ads.map((a) => `<option value="${a.icao}">${esc(a.name)}</option>`).join("");
    });

    const renderRuch = async (el) => {
      try {
        el.innerHTML = ruchLine(await api(`/api/vatsim/airport/${icao}`), icao);
      } catch (e) { el.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
    };

    let notamSort = lsGet("notam.sort") || "id";
    const renderNotams = async (el) => {
      if (!el.innerHTML) el.innerHTML = `<span class="hint">Ładowanie NOTAM…</span>`;
      let data;
      try { data = await api(`/api/notam/${icao}`); } catch (e) { el.innerHTML = `<span class="error">${esc(e.message)}</span>`; return; }
      const draw = () => {
        const list = [...data.notams].sort(NOTAM_SORT[notamSort] || NOTAM_SORT.id);
        el.innerHTML = `<div class="notam-bar">Sortuj: ${[["id", "numer"], ["start", "początek"], ["end", "koniec"]].map(([k, l]) =>
          `<button class="btn ${k === notamSort ? "primary" : ""}" data-sort="${k}">${l}</button>`).join("")}
          <span class="hint">${list.length} NOTAM</span></div>`
          + (list.length ? list.map((n) => {
            const s = notamState(n);
            return `<div class="notam ${s.cls}"><div class="nhead"><b class="mono">${esc(n.id || "")}</b><span class="valid">${esc(s.txt)}</span>
              ${n.schedule ? `<span class="hint">harmonogram: ${esc(n.schedule)}</span>` : ""}</div><pre>${esc(n.raw)}</pre></div>`;
          }).join("") : `<span class="hint">Brak NOTAM-ów dla ${esc(icao)}.</span>`);
      };
      el.onclick = (e) => {
        const b = e.target.closest("button[data-sort]");
        if (!b) return;
        notamSort = b.dataset.sort;
        lsSet("notam.sort", notamSort);
        draw();
      };
      draw();
    };

    const renderFreqs = async (el, info) => {
      const draw = (online = {}, bookings = {}, msg = "") => {
        // częstotliwości FIS (Information) są w RADIO › EPWW ACC; informacja lotniskowa (np. EPBC) zostaje
        const ps = info.atc_positions.filter((p) => !(/information/i.test(p.name) && /_(APP|CTR)$/.test(p.callsign))).sort(byType);
        const extra = Object.keys(bookings).filter((cs) => cs.startsWith(icao + "_") && !ps.some((p) => p.callsign === cs));
        el.innerHTML = (ps.map((p) => {
          const on = online[p.callsign], books = bookings[p.callsign] || [];
          const cls = on ? "on" : books.length ? "booked" : "";
          const tip = positionTip(on, books);
          return `<div class="radio-row ${cls}" ${tip ? `data-tip="${esc(tip)}"` : ""}><span class="freq ${cls}">${esc(p.frequency)}</span>
            <span class="cs">${esc(p.callsign)}</span><span class="nm">${esc(p.name)}</span>
            ${on ? `<b class="who">${esc(on.name || "")}</b>` : books.length ? `<span class="booked-txt">${hhmm(books[0].start)}–${hhmm(books[0].end)}</span>` : ""}</div>`;
        }).join("") || info.frequencies.map((x) => `<div class="radio-row"><span class="freq">${esc(x.mhz)}</span><span class="nm">${esc(x.kind)} ${esc(x.description)}</span></div>`).join("")
          || `<span class="hint">Brak danych</span>`)
          + extra.map((cs) => `<div class="radio-row booked" data-tip="${esc(positionTip(null, bookings[cs]))}"><span class="freq booked">-</span><span class="cs">${esc(cs)}</span>
            <span class="booked-txt">${hhmm(bookings[cs][0].start)}–${hhmm(bookings[cs][0].end)}</span></div>`).join("")
          + `<p class="hint">${msg}</p>`;
      };
      draw();
      const [on, bk] = await Promise.allSettled([vatsimOnline(), vatsimBookings()]);
      const errs = [on, bk].filter((r) => r.status === "rejected").map((r) => esc(r.reason.message));
      draw(on.status === "fulfilled" ? on.value.positions : {}, bk.status === "fulfilled" ? bk.value : {},
        `Zielone = online, przerywana ramka = rezerwacja (najedź, żeby zobaczyć kto). ${errs.length ? `<span class="error">${errs.join(" · ")}</span>` : ""}`);
    };

    // Układ na jeden ekran: trzy kolumny, długie listy przewijają się wewnątrz swoich okienek
    // (checklista jest tylko w zakładce CHECKLIST, loty w widoku RUCH). Szkielet budujemy raz na lotnisko, dane odświeżamy co minutę.
    const build = () => {
      $(".content").innerHTML = `
        <div class="ad-errors"></div>
        <div class="metar-head"></div>
        <div class="ad-grid">
          <div class="ad-col">
            <div class="card ad-wind"></div>
            <div class="card grow"><h3 class="atis-h">ATIS</h3><div class="scroll ad-atis"></div></div>
          </div>
          <div class="ad-col">
            <div class="values compact"></div>
            <div class="card"><h3>Pasy</h3><div class="ad-rwys"></div></div>
            <div class="card grow"><h3>TAF</h3><div class="scroll ad-taf wx"></div></div>
            <div class="card ad-ruch" title="Pokaż paski postępu lotu (widok RUCH)"><h3>Ruch VATSIM<span class="ruch-go">paski ›</span></h3><div class="ad-ruch-line"><span class="hint">Ładowanie…</span></div></div>
          </div>
          <div class="ad-col">
            <div class="card part"><h3>Częstotliwości · online · rezerwacje</h3><div class="scroll freqs"></div></div>
            <div class="card grow"><h3>NOTAM</h3><div class="scroll notams"></div></div>
          </div>
        </div>`;
      $(".ad-ruch").addEventListener("click", () => setView("ruch"));
      renderNotams($(".notams"));
    };

    let ticks = 0;
    const load = async () => {
      let info, st;
      try {
        [info, st] = await Promise.all([api(`/api/aerodromes/${icao}`), api(`/api/aerodromes/${icao}/status`)]);
      } catch (e) { if (view === "overview") $(".ad-errors").innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
      if (view !== "overview") return; // w międzyczasie przełączono na AWOS
      const p = st.parsed || {};
      $(".title").textContent = `${info.icao} · ${info.name}  (elev ${fmt(info.elevation_ft, 0)} ft)`;
      $(".upd").textContent = "Aktualizacja " + new Date().toISOString().slice(11, 16) + "Z";
      const clouds = (p.clouds || []).map((c) => `${c.cover}${c.base_ft !== null ? String(c.base_ft / 100).padStart(3, "0") : "///"}${c.type || ""}`).join(" ") || (p.cavok ? "CAVOK" : "NSC");
      const rvr = (p.rvr || []).map((x) => `R${x.runway} ${x.value}`).join("<br>") || "–";
      const age = obsAge(p.time);
      const gust = p.wind_gust ? ` <span class="gust">G${p.wind_gust}</span>` : "";
      $(".ad-errors").innerHTML = st.errors.length ? `<p class="error">${st.errors.map(esc).join("<br>")}</p>` : "";
      $(".metar-head").innerHTML = `
          <div class="wx">${colorize(st.metar)}</div>
          <div class="obs ${age !== null && age > 70 ? "stale" : ""}">${p.time ? `obs. ${esc(p.time.slice(2, 4))}:${esc(p.time.slice(4, 6))}Z` : ""}${age !== null ? ` · ${age} min temu` : ""}</div>
          ${sunBox(st.sun)}
          ${lvpBox(st.lvp)}`;
      $(".ad-wind").innerHTML = `${windrose(st)}
            <div class="big">${windText(p).replace(/G\d+/, "")}${gust}</div>
            <div class="hint">${p.wind_speed !== null && p.wind_speed !== undefined ? `${Math.round(p.wind_speed * 0.514)} m/s` : ""}${p.wind_var_from !== null && p.wind_var_from !== undefined ? ` · zmienny ${p.wind_var_from}°–${p.wind_var_to}°` : ""}</div>
            ${runwayBox(st)}`;
      $(".values").innerHTML = `
              ${value("QNH", p.qnh ?? "–", '<span class="hint">hPa</span>')}
              ${value("QFE", st.qfe ?? "–", '<span class="hint">hPa (przybl.)</span>')}
              ${value("Widzialność", p.visibility_m !== null && p.visibility_m !== undefined ? (p.visibility_m >= 9999 ? "≥10 km" : p.visibility_m + " m") : "–")}
              ${value("RVR", `<span class="sm">${rvr}</span>`)}
              ${value("Podstawa", p.ceiling_ft ? p.ceiling_ft + " ft" : "–")}
              ${value("Chmury", `<span class="sm">${esc(clouds)}</span>`)}
              ${value("Temp / Dew", `${p.temperature ?? "–"} / ${p.dewpoint ?? "–"}`, p.temperature !== null && p.dewpoint !== null && p.temperature !== undefined && p.temperature - p.dewpoint <= 2 ? '<span class="hint" style="color:var(--warn)">mały spread</span>' : "")}
              ${value("Zjawiska", `<span class="sm">${esc((p.weather || []).join(" ") || "–")}</span>`)}
              ${value("Kategoria", `<span class="cat-${esc(p.flight_category)}">${esc(p.flight_category || "–")}</span>`, p.trend ? `<span class="hint mono">${esc(p.trend)}</span>` : "")}`;
      $(".ad-rwys").innerHTML = runwayTable(st);
      $(".ad-taf").innerHTML = st.taf ? wxLines("taf", st.taf) : colorize(null);
      $(".atis-h").textContent = `ATIS ${st.atis ? st.atis.letter || "" : ""}`;
      $(".ad-atis").innerHTML = st.atis ? `<div class="mono atis-text">${st.atis.lines.map(esc).join("<br>")}</div>`
        : `<span class="hint">${st.network_error ? esc(st.network_error) : "ATIS nie jest teraz nadawany w sieci VATSIM."}</span>`;
      renderFreqs($(".freqs"), info);
      renderRuch($(".ad-ruch-line"));
      if (++ticks % 10 === 0) renderNotams($(".notams"));
    };

    const go = (code) => {
      icao = (code || $(".ad").value || icao).trim().toUpperCase();
      $(".ad").value = icao;
      lsSet("aerodrome.icao", icao);
      sub.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.ad === icao));
      history.replaceState(null, "", "#aerodrome/" + icao);
      ticks = 0;
      clearInterval(timer);
      awos?.destroy();
      awos = null;
      strips?.destroy();
      strips = null;
      pane.querySelectorAll(".ad-view button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
      if (view === "awos") {
        $(".title").textContent = $(".upd").textContent = "";
        awos = mountAwos($(".content"), icao);
        return;
      }
      if (view === "ruch") {
        $(".title").textContent = icao;
        $(".upd").textContent = "";
        strips = mountStrips($(".content"), icao, { onUpdate: (d) => {
          $(".title").textContent = `${d.icao} · ${d.name}  (elev ${fmt(d.elevation_ft, 0)} ft)`;
          $(".upd").textContent = `Aktualizacja ${d.now.slice(0, 2)}:${d.now.slice(2)}Z · co 30 s`;
        } });
        return;
      }
      build();
      load();
      timer = setInterval(load, 60000);
    };
    $(".go").addEventListener("click", () => go());
    const setView = (v) => {
      if (v === view) return;
      view = v;
      lsSet("aerodrome.view", view);
      go(icao);
    };
    $(".ad-view").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-view]");
      if (b) setView(b.dataset.view);
    });
    $(".ad").addEventListener("keydown", (e) => e.key === "Enter" && go());
    $(".ad").addEventListener("change", () => go());
    // AWOS już pokazuje to lotnisko: zostaje (wybrany pas, otwarta nakładka, wykrywanie nowej litery ATIS).
    // RUCH tego lotniska: zostaje (zaznaczony pasek, przewinięcie zatok), tylko wznawia odświeżanie co 30 s.
    return { activate: (arg) => {
      if (strips && (arg || icao).toUpperCase() === icao) return strips.resume();
      if (!(awos && (arg || icao).toUpperCase() === icao)) go(arg || icao);
    } };
  },
};
