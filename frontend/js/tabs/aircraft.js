import { api, debounce, esc, fmt, h, letterMenu } from "../api.js";

const RECAT = {
  A: "Super Heavy", B: "Upper Heavy", C: "Lower Heavy", D: "Upper Medium", E: "Lower Medium", F: "Light",
};
const searchName = (a) => `${a.manufacturer || ""} ${a.model || a.icao}`.trim();
// EUROCONTROL Aircraft Performance Database: strona typu (details.aspx?ICAO=…) obok strony głównej z config
let PERF = "https://learningzone.eurocontrol.int/ilp/customs/ATCPFDB/default.aspx";
const perfUrl = (icao) => PERF.replace(/default\.aspx.*$/i, `details.aspx?ICAO=${encodeURIComponent(icao)}`);

// Rekord w dwóch liniach: kod ICAO duży po lewej, reszta jednolitą czcionką
function record(a, i) {
  return `<div class="ac-rec" data-i="${i}">
    <div class="ac-icao">${esc(a.icao)}</div>
    <div class="ac-l1">${esc(a.manufacturer || "")} ${esc(a.model)}
      <a class="perf" href="${esc(perfUrl(a.icao))}" target="_blank" rel="noopener" title="EUROCONTROL Aircraft Performance Database">osiągi ↗</a></div>
    <div class="ac-l2">WTC <b>${esc(a.wtc || "–")}</b> · RECAT-EU <b class="recat-${esc(a.recat)}">${esc(a.recat || "–")}</b>
      · rozp. ${fmt(a.wingspan, 1, " m")} · dł. ${fmt(a.length, 1, " m")} · wys. ${fmt(a.height, 1, " m")} · MTOW ${a.mtow ? Math.round(a.mtow / 100) / 10 + " t" : "–"}</div>
  </div>`;
}

export default {
  mount(root, ctx) {
    PERF = ctx.config.links?.performance_db || PERF;
    let prefix = "";
    const letters = letterMenu(root, (l) => { prefix = l; load(); });
    const pane = h(`<div class="pane"><div class="split">
      <div class="list">
        <div class="toolbar">
          <input type="search" class="q" placeholder="Typ ICAO, model, producent…" size="32">
          <select class="wtc"><option value="">WTC: wszystkie</option><option>L</option><option>M</option><option>H</option><option>J</option></select>
          <select class="recat"><option value="">RECAT-EU: wszystkie</option>${Object.entries(RECAT).map(([k, v]) => `<option value="${k}">${k} – ${v}</option>`).join("")}</select>
          <span class="hint count"></span>
        </div>
        <div class="ac-list"></div>
      </div>
      <div class="detail"><div class="card"><p class="hint">Wybierz typ z listy, żeby zobaczyć szczegóły i zdjęcie.</p></div></div>
    </div></div>`);
    root.append(pane);
    const $ = (s) => pane.querySelector(s);
    let rows = [];
    let seq = 0;

    const load = async () => {
      const qs = new URLSearchParams({ q: $(".q").value.trim(), prefix, wtc: $(".wtc").value, recat: $(".recat").value, limit: 500 });
      const my = ++seq;
      let data;
      try {
        data = await api(`/api/aircraft?${qs}`);
      } catch (e) { $(".ac-list").innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
      if (my !== seq) return; // starsza odpowiedź przyszła po nowszej
      rows = data;
      $(".count").textContent = `${rows.length} typów${rows.length === 500 ? " (pokazano pierwsze 500)" : ""}`;
      $(".ac-list").innerHTML = rows.map(record).join("");
    };

    const show = (a) => {
      $(".detail").innerHTML = `<div class="card">
        <h3 class="ac-title"><span class="ac-icao" style="font-size:26px">${esc(a.icao)}</span> ${esc(a.manufacturer)} ${esc(a.model)}</h3>
        <div class="perf-links"><a class="btn" href="${esc(perfUrl(a.icao))}" target="_blank" rel="noopener">EUROCONTROL Aircraft Performance: ${esc(a.icao)} ↗</a>
          <a class="hint" href="${esc(PERF)}" target="_blank" rel="noopener">wyszukiwarka bazy ↗</a></div>
        <div class="photo-box"><span class="hint">Ładowanie zdjęcia…</span></div>
        <dl class="props">
          <dt>WTC (ICAO)</dt><dd>${esc(a.wtc || "–")}</dd>
          <dt>RECAT-EU</dt><dd class="recat-${esc(a.recat)}">${esc(a.recat || "–")} ${a.recat ? "– " + RECAT[a.recat] : ""}</dd>
          <dt>Rozpiętość</dt><dd>${fmt(a.wingspan, 2, " m")}</dd>
          <dt>Długość</dt><dd>${fmt(a.length, 2, " m")}</dd>
          <dt>Wysokość</dt><dd>${fmt(a.height, 2, " m")}</dd>
          <dt>MTOW / MLW</dt><dd>${fmt(a.mtow, 0, " kg")} / ${fmt(a.mlw, 0, " kg")}</dd>
          <dt>Silniki</dt><dd>${esc(a.engine_count ?? "–")} × ${esc(a.engine_type || "–")}</dd>
          <dt>Pułap</dt><dd>${fmt(a.ceiling_ft, 0, " ft")}</dd>
          <dt>Vmo / Mmo</dt><dd>${fmt(a.vmo_kt, 0, " kt")} / ${fmt(a.mmo, 2)}</dd>
          <dt>IATA</dt><dd>${esc(a.iata || "–")}</dd>
        </dl></div>`;
      const box = $(".photo-box");
      const links = `<a href="https://www.jetphotos.com/photo/keyword/${encodeURIComponent(searchName(a))}" target="_blank" rel="noopener">JetPhotos ↗</a> ·
        <a href="https://www.google.com/search?tbm=isch&q=${encodeURIComponent(searchName(a))}" target="_blank" rel="noopener">Google Grafika ↗</a>`;
      api(`/api/aircraft/${a.id}/photo`).then((p) => {
        if (current !== a) return;
        box.innerHTML = `<img src="${esc(p.url)}" alt="${esc(searchName(a))}"><div class="hint">${p.page ? `<a href="${esc(p.page)}" target="_blank" rel="noopener">${esc(p.credit)}</a>` : esc(p.credit)} · ${links}</div>`;
      }).catch((e) => {
        if (current !== a) return;
        box.innerHTML = `<p class="hint">${esc(e.message)}. Własne zdjęcie wrzuć do <span class="mono">data/photos/${esc(a.icao)}.jpg</span>. ${links}</p>`;
      });
    };
    let current = null;

    $(".ac-list").addEventListener("click", (e) => {
      const rec = e.target.closest(".ac-rec[data-i]");
      if (!rec) return;
      pane.querySelectorAll(".ac-rec.selected").forEach((x) => x.classList.remove("selected"));
      rec.classList.add("selected");
      current = rows[rec.dataset.i];
      show(current);
    });
    $(".q").addEventListener("input", debounce(load));
    $(".wtc").addEventListener("change", load);
    $(".recat").addEventListener("change", load);
    load();
    return { activate: (arg) => { if (arg) { $(".q").value = arg; prefix = ""; letters.set(""); load(); } $(".q").focus(); } };
  },
};
