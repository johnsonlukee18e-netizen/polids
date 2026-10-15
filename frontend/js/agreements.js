import { esc } from "./api.js";

// COORDINATION: czysta logika i HTML porozumień LOA/LOP (bez DOM – testy w Node). Dane z GET /api/coordination.
// Wiersz: {id, doc, type, fir, dir: out = EPWW → sąsiad | in = sąsiad → EPWW, cop, cop_key, traffic, adep[], ades[],
// level_text, level, transfer C|D, from, to, ep (strona polska), nb (sąsiad), conditions, ep_chains[], ep_unknown, scope[]}.

export const ALL = "ALL";            // adres "#coordination/agreements/ALL" = wszystkie stanowiska
export { POS_KEY } from "./api.js";   // stanowisko wybrane w AERODROME › OVERVIEW / HOME (choiceGet w COORDINATION)
const U = (s) => String(s ?? "").toLocaleUpperCase("pl");

// --- adres: "agreements[/<STANOWISKO|ALL>[/<filtr>]]", "docs[/<id dokumentu | FIR | plik w data/docs>]"
export function parseArg(arg) {
  const s = String(arg ?? "");
  const i = s.indexOf("/");
  const head = i < 0 ? s : s.slice(0, i), rest = i < 0 ? "" : s.slice(i + 1);
  if (head === "docs") return { sub: "docs", doc: rest };
  if (head !== "agreements") return {};
  if (i < 0) return { sub: "agreements" };
  const j = rest.indexOf("/");
  const p = j < 0 ? rest : rest.slice(0, j);
  return { sub: "agreements", pos: U(p) === ALL || !p ? "" : U(p), q: j < 0 ? "" : rest.slice(j + 1) };
}
export const agreementsArg = (pos, q = "") => (pos === undefined || pos === null) && !q
  ? "agreements" : `agreements/${pos || ALL}${q.trim() ? "/" + q.trim() : ""}`;
export const docsArg = (doc) => (doc ? `docs/${doc}` : "docs");

// dokument z adresu: id, plik (LOA/…pdf, stary adres OTHER › DOCS) albo FIR z loa.json (RADIO: "docs/EDUU")
export function docRef(docs, ref) {
  const r = String(ref ?? "").trim();
  if (!r) return null;
  return docs.find((d) => d.id === r) || docs.find((d) => d.file === r)
    || docs.find((d) => d.loa.includes(U(r))) || docs.find((d) => d.firs.includes(U(r)) && U(r) !== "EPWW") || null;
}

// stanowisko na start: z adresu, inaczej zapisane w OVERVIEW/HOME, gdy jest na liście (EPWW i APP/TWR z LOA)
export function defaultPosition(positions, stored) {
  const s = U(stored).trim();
  return positions.some((p) => p.callsign === s) ? s : "";
}

// --- kto obsługuje sektor (jak backend services/coordination.py): stanowisko w kolejności przejmowania, nikt przed
// nim online; bez nikogo online – każdy sektor, w którego kolejności jest
export function owns(chain, position, online) {
  const i = chain.indexOf(position);
  return i >= 0 && !chain.slice(0, i).some((cs) => online.has(cs));
}
export const ownedKeys = (chains, position, online) => Object.keys(chains).filter((k) => owns(chains[k], position, online));
export const firstOnline = (chain, online) => chain.find((cs) => online.has(cs)) || null;
const ACC_CS = /^EPWW_[A-Z0-9]+_CTR$/;
export function rowApplies(row, owned, position) {
  if (!row.ep_chains.length) return ACC_CS.test(position);   // wiersz bez sektora: każde stanowisko ACC
  return row.ep_chains.some((k) => owned.has(k));
}

// --- filtr: słowa (spacje, przecinki, średniki); każde do COP, lotnisk, sektorów, warunków, FIR-u, ruchu lub FL.
// Pełne nazwy COP to alternatywy (wiersz ma jeden COP: "ALUKA BODLA" = ALUKA albo BODLA), pozostałe słowa muszą
// pasować wszystkie: "ALUKA BODLA EPKS" = (ALUKA albo BODLA) i EPKS
export const tokens = (q) => U(q).split(/[\s,;]+/).filter(Boolean);
function haystack(r) {
  return [r.cop, ...r.adep, ...r.ades, r.traffic, r.from, r.to, r.conditions, r.fir, r.level_text, r.type, r.doc]
    .map(U);
}
export function matchRow(r, toks, cops = new Set()) {
  if (!toks.length) return true;
  const hay = haystack(r);
  const has = (t) => hay.some((x) => x.includes(t));
  const alt = toks.filter((t) => cops.has(t));
  return (!alt.length || alt.some(has)) && toks.every((t) => cops.has(t) || has(t));
}
export const copHit = (r, toks) => !!r.cop_key && toks.includes(r.cop_key);

// widok tabeli: wiersze po filtrze, stanowisku, FIR-ach i typie; trafione COP na górze, potem FIR-y w kolejności
// z danych i COP alfabetycznie. opts: {pos ("" = wszystkie), q, off: Set wyłączonych FIR-ów, typesOff: Set, online: Set}
export function view(data, { pos = "", q = "", off = new Set(), typesOff = new Set(), online = new Set() } = {}) {
  const toks = tokens(q);
  const cops = new Set(data.cops || []);
  const owned = new Set(pos ? ownedKeys(data.chains, pos, online) : []);
  const order = new Map(data.firs.map((f, i) => [f, i]));
  const rank = new Map(data.agreements.map((r, i) => [r.id, i]));
  const rows = data.agreements.filter((r) => !off.has(r.fir) && !typesOff.has(r.type)
    && (!pos || rowApplies(r, owned, pos)) && matchRow(r, toks, cops));
  const key = (r) => [copHit(r, toks) ? 0 : 1, order.get(r.fir) ?? 99, r.cop_key ? 0 : 1, r.cop_key, rank.get(r.id)];
  const cmp = (a, b) => {
    const x = key(a), y = key(b);
    for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
    return 0;
  };
  rows.sort(cmp);
  return { out: rows.filter((r) => r.dir === "out"), in: rows.filter((r) => r.dir === "in"), toks, owned: [...owned],
    total: data.agreements.length, shown: rows.length };
}

// karta dokumentu → POROZUMIENIA: tylko FIR-y tego dokumentu, jego rodzaj włączony, bez filtra słów. Wybrane
// stanowisko zostaje, gdy ma wiersze z tego dokumentu; inaczej wszystkie stanowiska (DBT nie obsługuje sektorów
// z LOA ze Lwowem – zostałaby pusta tabela). Wynik: {off, typesOff, pos, q} do stanu zakładki (bez zapisu w localStorage)
export function docFocus(data, docId, { pos = "", typesOff = new Set(), online = new Set() } = {}) {
  const doc = data.documents.find((d) => d.id === docId);
  const mine = new Set(data.agreements.filter((r) => r.doc === docId).map((r) => r.fir));
  const off = new Set(data.firs.filter((f) => !mine.has(f)));
  const types = new Set([...typesOff].filter((t) => t !== doc?.type));
  const has = (p) => {
    const v = view(data, { pos: p, off, typesOff: types, online });
    return [...v.out, ...v.in].some((r) => r.doc === docId);
  };
  return { off, typesOff: types, pos: pos && has(pos) ? pos : "", q: "" };
}

// --- HTML
const dash = `<span class="muted">–</span>`;
export const shortCs = (cs) => String(cs).replace(/^EPWW_/, "").replace(/_CTR$/, "");
// FL: strzałka ↑/↓ (we wznoszeniu / w zniżaniu), potem tekst z LOA bez strzałki
export function levelHtml(r) {
  const txt = String(r.level_text).replace(/^[↑↓]\s*/, "");
  const arrow = r.transfer === "C" ? `<span class="cr-c" title="przekazanie we wznoszeniu">↑</span>`
    : r.transfer === "D" ? `<span class="cr-d" title="przekazanie w zniżaniu">↓</span>` : "";
  return r.level === null || r.level === undefined
    ? `${arrow}<span class="cr-indiv" title="koordynacja indywidualna">${esc(txt) || "koord. indyw."}</span>`
    : `${arrow}<b>${esc(txt)}</b>`;
}
export function aeroHtml(r) {
  const parts = [];
  if (r.adep.length) parts.push(`<span class="cr-dep" title="odloty">↗ ${esc(r.adep.join(", "))}</span>`);
  if (r.ades.length) parts.push(`<span class="cr-arr" title="przyloty">↘ ${esc(r.ades.join(", "))}</span>`);
  return parts.length ? parts.join(" ") : r.traffic ? `<span class="muted">${esc(r.traffic)}</span>` : dash;
}
// strona polska: sektor z LOA (pusty – "nieokreślony") i kto go teraz obsługuje: pierwszy z kolejności, który jest
// online albo jest wybranym stanowiskiem (wybrany sam siebie nie podpisuje, jak w ATCISS)
function epHtml(r, data, x) {
  if (r.ep_unknown) {
    const sc = r.scope.length ? ` Wiersz dla stanowisk obsługujących sektory wymienione w LOA: ${r.scope.join(", ")}.` : "";
    return `<span class="cr-unk" title="${esc(data.unknown_label + "." + sc)}">${esc(data.unknown_label)}</span>`;
  }
  const on = x.pos ? new Set([...x.online, x.pos]) : x.online;
  const by = [...new Set(r.ep_chains.map((k) => firstOnline(data.chains[k] || [], on)).filter(Boolean))]
    .filter((cs) => cs !== x.pos);
  const who = by.map((cs) => `${shortCs(cs)}${x.freq?.(cs) ? " " + x.freq(cs) : ""}`).join(", ");
  return `<span class="cr-ep">${esc(r.ep)}</span>${who ? ` <span class="cr-by" title="obsługuje teraz">${esc(who)}</span>` : ""}`;
}
const nbHtml = (r) => (r.nb ? `<span class="cr-nb">${esc(r.nb)}</span>` : dash);

export function rowHtml(r, data, x = {}) {
  const ctx = { online: x.online || new Set(), pos: x.pos || "", freq: x.freq };
  const toks = x.toks || [];
  const cop = r.cop_key ? `<b class="cr-cop${copHit(r, toks) ? " hit" : ""}">${esc(r.cop)}</b>`
    : r.cop ? `<span class="muted">${esc(r.cop)}</span>` : dash;
  const ep = epHtml(r, data, ctx), nb = nbHtml(r);
  const doc = (data.documents || []).find((d) => d.id === r.doc);
  const tag = doc ? `<button type="button" class="cr-doc" data-doc="${esc(doc.id)}" title="${esc(doc.name)} – otwórz w DOKUMENTY">${esc(r.type)} ${esc(r.fir)}</button>`
    : `<span class="muted">${esc(r.type)} ${esc(r.fir)}</span>`;
  return `<tr data-id="${esc(r.id)}"${r.ep_unknown ? ` class="unk"` : ""}><td class="c-cop">${cop}</td><td class="c-aero">${aeroHtml(r)}</td>`
    + `<td class="c-fl">${levelHtml(r)}</td><td class="c-cond">${r.conditions ? esc(r.conditions) : ""}</td>`
    + `<td class="c-sec">${r.dir === "out" ? ep : nb}</td><td class="c-sec">${r.dir === "out" ? nb : ep}</td><td class="c-doc">${tag}</td></tr>`;
}

export function blockHtml(dir, rows, data, x = {}) {
  const head = dir === "out" ? ["WYJŚCIE (COPX)", "EPWW → sąsiad", "COPX"] : ["WEJŚCIE (COPN)", "sąsiad → EPWW", "COPN"];
  const body = rows.length ? rows.map((r) => rowHtml(r, data, x)).join("")
    : `<tr class="none"><td colspan="7" class="muted">Brak przekazań dla tych ustawień.</td></tr>`;
  return `<div class="cr-block" data-dir="${dir}"><h3 class="cr-bh">${head[0]} <small>${head[1]} · ${rows.length}</small></h3>
    <table class="data cr-tab"><thead><tr><th>${head[2]}</th><th>ADEP/ADES</th><th>FL</th><th>WARUNKI</th><th>OD</th><th>DO</th><th>DOKUMENT</th></tr></thead>
    <tbody>${body}</tbody></table></div>`;
}

// podsumowanie nad tabelami: ile wierszy, stanowisko, filtr i co jest wyłączone po prawej (FIR-y, LOA/LOP) –
// pusta tabela nie zostaje bez wyjaśnienia (przełączniki FIR zapamiętuje przeglądarka)
export function sumHtml(v, { pos = "", firs = [], off = new Set(), typesOff = new Set() } = {}) {
  const hidden = firs.filter((f) => off.has(f)), on = firs.filter((f) => !off.has(f));
  const types = ["LOA", "LOP"].filter((t) => typesOff.has(t));
  const firTxt = !hidden.length ? "" : !on.length ? " · <b>wszystkie FIR-y wyłączone</b>"
    : hidden.length > on.length ? ` · tylko FIR <b>${esc(on.join(", "))}</b>` : ` · ukryte FIR-y <b>${esc(hidden.join(", "))}</b>`;
  return `<b>${v.shown}</b> z ${v.total} przekazań`
    + (pos ? ` · stanowisko <b>${esc(pos)}</b>` : " · wszystkie stanowiska")
    + (v.toks.length ? ` · filtr <b>${esc(v.toks.join(" "))}</b>` : "")
    + `<span class="cr-off">${firTxt}${types.length ? ` · ukryte <b>${esc(types.join(", "))}</b>` : ""}</span>`
    + `<span class="hint"> · wyciąg z PDF (data/seed/loa.json), w razie wątpliwości obowiązuje PDF</span>`;
}

// zasady z LOA (przekazanie kontroli, VFR, inne) dla FIR-ów z tabeli
export function notesHtml(data, firs) {
  const list = (title, items) => (items?.length ? `<h5>${esc(title)}</h5><ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : "");
  return firs.filter((f) => data.notes?.[f]).map((f) => {
    const n = data.notes[f];
    return `<div class="cr-note"><h4>${esc(n.title || f)} <small>${esc(n.version)}</small></h4>`
      + list("Przekazanie kontroli i łączności", n.silent) + list("VFR", n.vfr) + list("Inne zasady", n.other) + "</div>";
  }).join("");
}

// stanowiska do listy: grupy ACC / APP / TWR, opis "EPWW_DBT_CTR · 127.025 Warszawa Radar"
export function positionOptions(positions, selected) {
  const groups = [["ACC", "ACC / FIR"], ["APP", "APP / zbliżanie"], ["TWR", "TWR / lotnisko"]];
  const opt = (p) => `<option value="${esc(p.callsign)}"${p.callsign === selected ? " selected" : ""}>${esc(p.callsign)}`
    + `${p.frequency ? " · " + esc(p.frequency) : ""}</option>`;
  return `<option value=""${selected ? "" : " selected"}>Wszystkie</option>` + groups.map(([k, label]) => {
    const ps = positions.filter((p) => p.kind === k);
    return ps.length ? `<optgroup label="${esc(label)}">${ps.map(opt).join("")}</optgroup>` : "";
  }).join("");
}

// --- DOKUMENTY: karta dokumentu (nazwa, typ, FIR-y, AIRAC – wyróżniony, gdy bieżący cykl, data, wersja, sektory)
const dmy = (iso) => (/^\d{4}-\d{2}-\d{2}$/.test(iso || "") ? iso.split("-").reverse().join(".") : "");
export function docCardHtml(d, { selected = false, airac = "" } = {}) {
  const firs = d.firs.filter((f) => f !== "EPWW" || d.type === "LOP");
  const tags = [`<span class="cd-tag ty">${esc(d.type)}</span>`, ...firs.map((f) => `<span class="cd-tag fir">${esc(f)}</span>`)];
  if (d.airac) {
    tags.push(`<span class="cd-tag airac${d.current ? " cur" : ""}" title="${d.current ? "bieżący cykl AIRAC" : `bieżący cykl: ${esc(airac)}`}">AIRAC ${esc(d.airac)}</span>`);
  }
  const meta = [dmy(d.effective) && `od ${dmy(d.effective)}`, d.version, `${d.count} przekazań`].filter(Boolean).map(esc).join(" · ")
    + (d.registered === false ? ` · <span class="cd-new">${esc(d.note || "brak wpisu w coordination.json")}</span>` : "");
  const url = String(d.url || "").startsWith("/files/docs/") && d.exists ? d.url : "";
  return `<div class="cd-card${selected ? " on" : ""}" data-doc="${esc(d.id)}" tabindex="0" title="${esc(d.note || d.name)}">
    <div class="cd-name">${esc(d.name)}</div>
    <div class="cd-tags">${tags.join("")}</div>
    <div class="cd-meta">${meta}</div>
    ${d.positions.length ? `<div class="cd-pos">${d.positions.map(esc).join(" · ")}</div>` : ""}
    <div class="cd-act">${url ? `<a class="btn" href="${esc(encodeURI(url))}" target="_blank" rel="noopener" title="${esc(d.file)}">PDF ↗</a>`
      : `<span class="error">brak pliku ${esc(d.file)}</span>`}
      ${d.count ? `<button type="button" class="btn cd-agr" title="Porozumienia z tego dokumentu">POROZUMIENIA ›</button>` : ""}</div>
  </div>`;
}
export const docFilter = (docs, { fir = "", type = "" } = {}) => docs.filter((d) => (!fir || d.firs.includes(fir)) && (!type || d.type === type));
