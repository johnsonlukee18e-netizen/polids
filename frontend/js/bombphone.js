import { esc, h } from "./api.js";

// OTHER › BOMB PHONE (0.13.2, issue #27): checklista rozmowy z groźbą bombową jak lista CISA (Bomb Threat Checklist
// 08/2025) i ProtectUK (Bomb threats checklist): co robić w czasie rozmowy, pytania do dzwoniącego (z polami na
// odpowiedzi), dokładne słowa groźby, dane rozmowy (data, czasy UTC z przyciskiem NOW, czas trwania liczony sam, numer
// na wyświetlaczu, imię i stanowisko), dzwoniący, głos, dźwięki w tle i język groźby (pola wyboru), uwagi i co zrobić
// po rozmowie. Czas trwania liczony z obu czasów po każdym NOW i każdej ręcznej zmianie czasu (powtórne NOW przy
// końcu rozmowy go poprawia), aż dyżurny sam wpisze czas trwania; koniec przed początkiem daje puste pole, nie prawie
// 24 h. Polski numer alarmowy 112 duży na górze strony i w punktach po rozmowie (Policja 997 mniejszy: numer
// dalej działa, zgłoszenia trafiają do operatorów numerów alarmowych jak z 112). Na ekranie bez nazw źródeł.
// Stan formularza tylko w tej karcie przeglądarki (sessionStorage, bez niego w pamięci strony): przetrwa przejście
// do innej podzakładki i Reload, znika po zamknięciu karty albo po CLEAR. Nic nie idzie do serwera.

export const STORE_KEY = "bombphone.form";
export const EMERGENCY = "112";
export const POLICE = "997";

// w czasie rozmowy
export const DURING = [
  "Stay calm, be polite and listen carefully.",
  "Keep the caller talking as long as possible. Do not interrupt.",
  "Do not hang up, even if the caller does.",
  "Signal a colleague to listen in and to inform the supervisor.",
  "Note the number shown on the display.",
  "Record the call if you can.",
  "Write down the exact words of the threat.",
  "Ask the questions below and note the answers.",
];
// pytania: [klucz, pytanie, podpowiedź]
export const QUESTIONS = [
  ["q-when", "When will it explode?", ""],
  ["q-where", "Where is it right now?", "Aerodrome, building, aircraft or flight"],
  ["q-look", "What does it look like?", ""],
  ["q-kind", "What kind of bomb is it?", ""],
  ["q-cause", "What will cause it to explode?", ""],
  ["q-placed", "Did you place the bomb?", "If not, who did?"],
  ["q-why", "Why?", ""],
  ["q-from", "Where are you calling from?", ""],
  ["q-name", "What is your name?", ""],
  ["q-address", "What is your address?", ""],
  ["q-phone", "What is your telephone number?", ""],
  ["q-group", "Are you acting alone or for a group?", ""],
];
// dane rozmowy: [klucz, etykieta, now = przycisk NOW (bieżący czas UTC)]
export const CALL = [
  ["c-date", "Date (UTC)"],
  ["c-start", "Time of call (UTC)", true],
  ["c-end", "Caller hung up (UTC)", true],
  ["c-dur", "Duration"],
  ["c-number", "Number displayed"],
  ["c-line", "Line called"],
  ["c-taker", "Your name"],
  ["c-position", "Your position"],
];
// dzwoniący: pola wyboru płci i pola tekstowe
export const SEX = ["Male", "Female"];
export const CALLER = [["p-age", "Estimated age"], ["p-accent", "Nationality / accent"], ["p-familiar", "Voice familiar? Who?"]];
// pola wyboru (alfabetycznie): głos, dźwięki w tle, język groźby
export const VOICE = ["Accent", "Angry", "Calm", "Clearing throat", "Coughing", "Cracking voice", "Crying", "Deep",
  "Deep breathing", "Disguised", "Distinct", "Excited", "Familiar", "Hoarse", "Laughter", "Lisp", "Loud", "Nasal", "Normal",
  "Ragged", "Rapid", "Raspy", "Slow", "Slurred", "Soft", "Stutter", "Whispered"];
export const BACKGROUND = ["Aircraft", "Animal noises", "Booth", "Clear", "Conversation", "Crockery", "Factory machinery",
  "House noises", "Kitchen noises", "Local", "Long distance", "Motor", "Music", "Office machinery", "PA system", "Static",
  "Street noises", "Voices"];
export const LANGUAGE = ["Foul / profane", "Incoherent", "Irrational", "Message read", "Taped message", "Well spoken"];
// po rozmowie; pierwszy punkt z numerami alarmowymi (rysowany osobno)
export const AFTER = [
  "Inform the supervisor and follow local procedures.",
  "Complete this checklist while your memory is fresh.",
  "Do not discuss the threat with anyone other than the supervisor and the police.",
  "Do not use radios or mobile phones near a suspicious item. Do not touch or move it.",
];
export const KEEP_NOTE = "The form stays only in this browser tab until cleared or the tab is closed.";

// klucz pola wyboru: przedrostek grupy i nazwa małymi literami ("v-clearing-throat", "l-foul-profane")
export const slug = (prefix, label) => `${prefix}-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`;
const TEXT_KEYS = [...QUESTIONS.map(([k]) => k), ...CALL.map(([k]) => k), ...CALLER.map(([k]) => k), "words", "remarks"];
const BOX_KEYS = [...SEX.map((s) => slug("s", s)), ...VOICE.map((s) => slug("v", s)), ...BACKGROUND.map((s) => slug("b", s)),
  ...LANGUAGE.map((s) => slug("l", s))];
export const KEYS = new Set([...TEXT_KEYS, ...BOX_KEYS]);
const BOXES = new Set(BOX_KEYS);

// stan {klucz: tekst albo true} z zapisu; obce klucze i złe wartości (stara wersja, ręczna zmiana) pomijane
export function loadForm(store) {
  let o = null;
  try { o = JSON.parse(store?.getItem(STORE_KEY) || "{}"); } catch { o = null; }
  const st = {};
  if (!o || typeof o !== "object" || Array.isArray(o)) return st;
  for (const [k, v] of Object.entries(o)) {
    if (BOXES.has(k) ? v === true : KEYS.has(k) && typeof v === "string" && v) st[k] = v;
  }
  return st;
}
// pusty formularz: zapis usunięty
export function saveForm(store, st) {
  try {
    if (Object.keys(st).length) store?.setItem(STORE_KEY, JSON.stringify(st));
    else store?.removeItem(STORE_KEY);
  } catch { /* tryb prywatny, pe\u0142na pami\u0119\u0107: zostaje stan w pami\u0119ci strony */ }
}

// czas trwania z dwóch czasów "HH:MM[:SS]" (przez północ też, do 12 h); zły czas albo koniec przed początkiem
// (przerwa ponad 12 h, np. NOW przy końcu wciśnięte przed NOW przy początku): ""
export function durationOf(a, b) {
  const sec = (t) => {
    const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(String(t || "").trim());
    if (!m || +m[1] > 23 || +m[2] > 59 || +(m[3] || 0) > 59) return null;
    return +m[1] * 3600 + +m[2] * 60 + +(m[3] || 0);
  };
  const x = sec(a), y = sec(b);
  if (x === null || y === null) return "";
  const d = (y - x + 86400) % 86400;
  if (d > 43200) return "";
  return `${Math.floor(d / 60)} min ${String(d % 60).padStart(2, "0")} s`;
}
export const utcTime = (d = new Date()) => d.toISOString().slice(11, 19);
export const utcDate = (d = new Date()) => d.toISOString().slice(0, 10);

const input = (k, st, extra = "") => `<input class="field bp-in" type="text" data-k="${k}" value="${esc(st[k] || "")}" `
  + `maxlength="200" autocomplete="off" spellcheck="false"${extra}>`;
const area = (k, st, rows, extra = "") => `<textarea class="field bp-area" data-k="${k}" rows="${rows}" maxlength="2000" `
  + `spellcheck="false"${extra}>${esc(st[k] || "")}</textarea>`;
const checks = (prefix, list, st) => `<div class="bp-checks">${list.map((label) => {
  const k = slug(prefix, label);
  return `<label class="bp-chk"><input type="checkbox" data-k="${k}"${st[k] === true ? " checked" : ""}><span>${label}</span></label>`;
}).join("")}</div>`;
const sec = (cls, title, body) => `<section class="bp-sec ${cls}"><h3 class="bp-bar">${title}</h3>${body}</section>`;

// treść strony (bez DOM, testy w Node); st = stan formularza, wartości escapowane
export function bombBody(st = {}) {
  const during = `<ol class="bp-list">${DURING.map((s) => `<li>${s}</li>`).join("")}</ol>`;
  const questions = QUESTIONS.map(([k, q, hint], i) => `<label class="bp-row"><span class="bp-lbl bp-qlbl"><span class="bp-n">${i + 1}</span>`
    + `<span>${q}${hint ? `<span class="bp-hint">${hint}</span>` : ""}</span></span>${input(k, st)}</label>`).join("");
  const call = CALL.map(([k, label, now]) => `<label class="bp-row"><span class="bp-lbl">${label}</span>`
    + (now ? `<span class="bp-time">${input(k, st)}<button class="btn bp-now" type="button" data-act="now" data-for="${k}" `
      + `title="Current UTC time">NOW</button></span>` : input(k, st)) + `</label>`).join("");
  const caller = checks("s", SEX, st) + CALLER.map(([k, label]) => `<label class="bp-row"><span class="bp-lbl">${label}</span>`
    + `${input(k, st)}</label>`).join("");
  const after = `<div class="bp-call"><span class="bp-call-txt">Report immediately</span><span class="bp-call-num">${EMERGENCY}</span>`
    + `<span class="bp-call-txt">Police <span class="bp-police">${POLICE}</span></span></div>`
    + `<ol class="bp-list">${AFTER.map((s) => `<li>${s}</li>`).join("")}</ol>`;
  return `<div class="bp-top">
    <p class="bp-lead"><span class="bp-lead-key">Bomb threat call:</span> stay calm, keep the caller talking, do not hang up.</p>
    <div class="bp-sos" title="Emergency number"><span class="bp-sos-lbl">EMERGENCY</span><span class="bp-sos-num">${EMERGENCY}</span></div>
    <div class="bp-sos bp-sos-alt" title="Police"><span class="bp-sos-lbl">POLICE</span><span class="bp-sos-num">${POLICE}</span></div>
    <button class="btn bp-clear" type="button" data-act="clear" title="Clear the whole form">CLEAR</button>
  </div>
  <div class="bp-cols">
    <div class="bp-col bp-col-a">
      ${sec("bp-during", "During the call", during)}
      ${sec("bp-questions", "Questions to ask", questions)}
    </div>
    <div class="bp-col bp-col-b">
      ${sec("bp-words", "Exact words of the threat", area("words", st, 5, ` placeholder="Write down the exact words"`))}
      ${sec("bp-details", "Call details", call)}
      ${sec("bp-caller", "Caller", caller)}
      ${sec("bp-remarks", "Remarks", area("remarks", st, 3))}
    </div>
    <div class="bp-col bp-col-c">
      ${sec("bp-voice", "Caller's voice", checks("v", VOICE, st))}
      ${sec("bp-sounds", "Background sounds", checks("b", BACKGROUND, st))}
      ${sec("bp-language", "Threat language", checks("l", LANGUAGE, st))}
      ${sec("bp-after", "After the call", after)}
      <p class="bp-keep">${KEEP_NOTE}</p>
    </div>
  </div>`;
}
export const bombHtml = (st = {}) => `<div class="bp-page">${bombBody(st)}</div>`;

// zapis w pamięci strony, gdy przeglądarka nie daje sessionStorage (tryb prywatny, zablokowane dane witryny)
const memo = new Map();
const MEMORY = { getItem: (k) => memo.get(k) ?? null, setItem: (k, v) => { memo.set(k, String(v)); }, removeItem: (k) => { memo.delete(k); } };
const session = () => {
  try {
    const s = window.sessionStorage;
    s.getItem(STORE_KEY);
    return s;
  } catch { return MEMORY; }
};

// panel podzakładki. opts.store: zapis (testy), domyślnie sessionStorage tej karty; opts.ask: pytanie przed CLEAR
// wypełnionego formularza (domyślnie confirm), opts.now: bieżąca data (testy). destroy() zdejmuje nasłuchy.
export function mountBombPhone(pane, { store = session(), ask = (q) => window.confirm(q), now = () => new Date() } = {}) {
  let st = loadForm(store);
  // czas trwania wpisany sam (ostatnia policzona wartość); inna wartość w polu = wpisana ręcznie, wtedy bez zmian
  let autoDur = st["c-dur"] && st["c-dur"] === durationOf(st["c-start"], st["c-end"]) ? st["c-dur"] : "";
  const root = h(`<div class="bp-page"></div>`);
  root.innerHTML = bombBody(st);
  pane.append(root);
  const field = (k) => root.querySelector(`[data-k="${k}"]`);
  const put = (k, v) => {
    if (!KEYS.has(k)) return;
    if (v === false || v === "" || v === null || v === undefined) delete st[k];
    else st[k] = v === true && BOXES.has(k) ? true : String(v);
    saveForm(store, st);
  };
  const fill = (k, v) => { const el = field(k); if (el) el.value = v; put(k, v); };
  // czas trwania z obu czasów, gdy pole puste albo wpisane samo (zły czas albo koniec przed początkiem: pole puste)
  const syncDur = () => {
    const d = durationOf(st["c-start"], st["c-end"]);
    if (st["c-dur"] && st["c-dur"] !== autoDur) return;
    fill("c-dur", d);
    autoDur = d;
  };
  // pole zmienione ręcznie; zmiana czasu początku albo końca liczy czas trwania od nowa
  const onField = (e) => {
    const k = e.target?.dataset?.k;
    if (!k) return;
    put(k, e.target.type === "checkbox" ? e.target.checked : e.target.value);
    if (k === "c-start" || k === "c-end") syncDur();
  };
  // NOW: bieżący czas UTC w polu; pusta data dostaje dzisiejszą, czas trwania liczy się od nowa
  const onClick = (e) => {
    const b = e.target?.closest?.("button[data-act]");
    if (!b) return;
    if (b.dataset.act === "clear") {
      if (Object.keys(st).length && !ask("Clear the whole bomb threat form?")) return;
      st = {};
      autoDur = "";
      saveForm(store, st);
      root.innerHTML = bombBody(st);
    } else if (b.dataset.act === "now" && KEYS.has(b.dataset.for)) {
      const d = now();
      fill(b.dataset.for, utcTime(d));
      if (!st["c-date"]) fill("c-date", utcDate(d));
      syncDur();
    }
  };
  root.addEventListener("input", onField);
  root.addEventListener("change", onField);
  root.addEventListener("click", onClick);
  return {
    destroy: () => {
      root.removeEventListener("input", onField);
      root.removeEventListener("change", onField);
      root.removeEventListener("click", onClick);
    },
  };
}
