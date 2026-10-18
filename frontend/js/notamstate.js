// Okres ważności NOTAM-u względem teraz (pola B i C): jeden opis dla SYT OP i listy NOTAM w AERODROME › INFO.
// {cls: active | future | expired | "", txt}; cls to klasa wiersza .notam (kolor w style.css i sytop.css).
const dm = (iso) => { const d = new Date(iso); return `${String(d.getUTCDate()).padStart(2, "0")}.${String(d.getUTCMonth() + 1).padStart(2, "0")} ${d.toISOString().slice(11, 16)}Z`; };
function span(ms) {
  const min = Math.round(Math.abs(ms) / 60000);
  if (min < 1) return "<1 min";
  if (min < 60) return `${min} min`;
  if (min < 48 * 60) return `${Math.floor(min / 60)} h ${min % 60} min`;
  return `${Math.round(min / 1440)} days`;
}
export function notamState(n, now = Date.now()) {
  const s = n.start ? Date.parse(n.start) : null, e = n.end ? Date.parse(n.end) : null;
  const endTxt = n.perm ? "PERM" : e ? `${dm(n.end)}${n.est ? " EST" : ""}` : "?";
  if (e && e < now && !n.perm) return { cls: "expired", txt: `EXPIRED ${dm(n.end)}` };
  if (s && s > now) return { cls: "future", txt: `ACTIVE FROM ${dm(n.start)} (in ${span(s - now)}) until ${endTxt}` };
  if (n.perm) return { cls: "active", txt: `ACTIVE since ${s ? dm(n.start) : "?"} · PERM` };
  if (e) return { cls: "active", txt: `ACTIVE UNTIL ${endTxt} (${span(e - now)} left)` };
  if (s) return { cls: "active", txt: `ACTIVE since ${dm(n.start)}` };
  // bez B) i C) (nieznany format, uszkodzone pola): bez zielonego "ACTIVE", żółty jak domyślny NOTAM
  return { cls: "", txt: "validity unknown (no B/C fields)" };
}
