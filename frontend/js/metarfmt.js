// METEO › METAR i TAF jak strona METAR w PANDORZE (0.13.1, zdjęcie Marka): grupy w kolorach, zjawiska z opisem
// [EN / PL] tuż za grupą, przełącznik COLOURED / MONO. Czyste funkcje (bez DOM), testy w Node: test_metar_fmt_js.py.
// Kod tylko w ASCII: polskie litery opisów jako \u escape (zasada projektu; polskie litery tylko w komentarzach).
// Klasy części grupy: mt-key (zielony: dzień, kierunek wiatru, zjawisko, RMK, pas RVR, CB/TCU), mt-val (jasnozielony:
// godzina, prędkość, widzialność, podstawa chmur, wartość QNH, RVR), mt-cov (ciemnozielony: ilość chmur), mt-trend
// (niebieski: BECMG, TEMPO, NOSIG, PROB, FM/TL/AT), mt-nil (czerwony: NIL); bez klasy = biały (stacja, jednostki
// KT/MPS/Z/G/V, temperatura, Q, reszta po RMK, grupy nieznane). Opis zjawiska: mt-dec (biały, kapitaliki).
import { esc, splitTaf } from "./api.js";

// wybór COLOURED / MONO zapamiętany w przeglądarce, wspólny dla METAR PL/MIL/INTL i TAF PL/INTL
export const MODE_KEY = "meteo.wx.mode";
export const wxMode = (v) => (v === "mono" ? "mono" : "coloured");

// zjawiska: en / pl małymi literami (wielkie litery i kapitaliki robi CSS), g = rodzaj (m, f, n, p = mnogi),
// ins = narzędnik po "z"/"ze" (opad dołączony do pierwszego: "deszcz ze śniegiem", "burza z gradem"), pcp = opad
export const WX_PHEN = {
  DZ: { en: "drizzle", pl: "m\u017cawka", g: "f", ins: "m\u017cawk\u0105", z: "z", pcp: true },
  RA: { en: "rain", pl: "deszcz", g: "m", ins: "deszczem", z: "z", pcp: true },
  SN: { en: "snow", pl: "\u015bnieg", g: "m", ins: "\u015bniegiem", z: "ze", pcp: true },
  SG: { en: "snow grains", pl: "\u015bnieg ziarnisty", g: "m", ins: "\u015bniegiem ziarnistym", z: "ze", pcp: true },
  IC: { en: "ice crystals", pl: "ig\u0142y lodowe", g: "p", ins: "ig\u0142ami lodowymi", z: "z", pcp: true },
  PL: { en: "ice pellets", pl: "ziarna lodowe", g: "p", ins: "ziarnami lodowymi", z: "z", pcp: true },
  GR: { en: "hail", pl: "grad", g: "m", ins: "gradem", z: "z", pcp: true },
  GS: { en: "small hail", pl: "krupa", g: "f", ins: "krup\u0105", z: "z", pcp: true },
  UP: { en: "unknown precipitation", pl: "nieznany opad", g: "m", ins: "nieznanym opadem", z: "z", pcp: true },
  BR: { en: "mist", pl: "zamglenie", g: "n" },
  FG: { en: "fog", pl: "mg\u0142a", g: "f" },
  FU: { en: "smoke", pl: "dym", g: "m" },
  VA: { en: "volcanic ash", pl: "popi\u00f3\u0142 wulkaniczny", g: "m" },
  DU: { en: "widespread dust", pl: "py\u0142", g: "m" },
  SA: { en: "sand", pl: "piasek", g: "m" },
  HZ: { en: "haze", pl: "zm\u0119tnienie", g: "n" },
  PY: { en: "spray", pl: "py\u0142 wodny", g: "m" },
  PO: { en: "dust whirls", pl: "wiry py\u0142owe", g: "p" },
  SQ: { en: "squalls", pl: "szkwa\u0142", g: "m" },
  FC: { en: "funnel cloud", pl: "chmura lejkowa", g: "f" },
  SS: { en: "sandstorm", pl: "burza piaskowa", g: "f" },
  DS: { en: "duststorm", pl: "burza py\u0142owa", g: "f" },
};
const G = { m: 0, f: 1, n: 2, p: 3 };
// przymiotniki [m, f, n, p]: mianownik (nom) i narzędnik (ins)
const ADJ = {
  light: { en: "light", nom: ["lekki", "lekka", "lekkie", "lekkie"], ins: ["lekkim", "lekk\u0105", "lekkim", "lekkimi"] },
  heavy: { en: "heavy", nom: ["silny", "silna", "silne", "silne"], ins: ["silnym", "siln\u0105", "silnym", "silnymi"] },
  SH: { nom: ["przelotny", "przelotna", "przelotne", "przelotne"] },
  FZ: { nom: ["marzn\u0105cy", "marzn\u0105ca", "marzn\u0105ce", "marzn\u0105ce"] },
  RE: { nom: ["niedawny", "niedawna", "niedawne", "niedawne"] },
};
// MI, PR i BC tylko z mgłą (BC także z zamgleniem), DR i BL ze śniegiem, piaskiem, pyłem, wodą: gotowe nazwy
const FIXED = {
  MIFG: { en: "shallow fog", pl: "p\u0142ytka mg\u0142a", g: "f" },
  PRFG: { en: "partial fog", pl: "cz\u0119\u015bciowa mg\u0142a", g: "f" },
  BCFG: { en: "fog patches", pl: "p\u0142aty mg\u0142y", g: "p" },
  BCBR: { en: "mist patches", pl: "p\u0142aty zamglenia", g: "p" },
  DRSN: { en: "low drifting snow", pl: "zamie\u0107 \u015bnie\u017cna niska", g: "f" },
  BLSN: { en: "blowing snow", pl: "zamie\u0107 \u015bnie\u017cna wysoka", g: "f" },
  DRSA: { en: "low drifting sand", pl: "zamie\u0107 piaskowa niska", g: "f" },
  BLSA: { en: "blowing sand", pl: "zamie\u0107 piaskowa wysoka", g: "f" },
  DRDU: { en: "low drifting dust", pl: "zamie\u0107 py\u0142owa niska", g: "f" },
  BLDU: { en: "blowing dust", pl: "zamie\u0107 py\u0142owa wysoka", g: "f" },
  BLPY: { en: "blowing spray", pl: "py\u0142 wodny niesiony wiatrem", g: "m" },
};
// grupa zjawisk: RE (ostatnie), intensywność albo VC, deskryptor, zjawiska po dwie litery
export const WX_RE = /^(RE)?([+-]|VC)?(MI|PR|BC|DR|BL|SH|TS|FZ)?((?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$/;

// grupa -> { en, pl } (małymi literami) albo null: nie grupa zjawisk albo połączenie bez opisu
export function wxPhrase(code) {
  if (code === "NSW") return { en: "no significant weather", pl: "brak istotnych zjawisk" };
  const m = WX_RE.exec(code || "");
  if (!m) return null;
  const [, re, pre, desc] = m, list = m[4].match(/../g) || [];
  if (!desc && !list.length) return null;
  const int = pre === "-" ? ADJ.light : pre === "+" ? ADJ.heavy : null;
  const intEn = int ? int.en + " " : "", intNom = (g) => (int ? int.nom[G[g]] + " " : "");
  const enList = list.map((x) => WX_PHEN[x].en).join(" and ");
  // dalsze zjawiska: opad w narzędniku ("ze śniegiem"), inne po "i"
  const rest = (xs) => xs.map((x) => (WX_PHEN[x].pcp ? ` ${WX_PHEN[x].z} ${WX_PHEN[x].ins}` : ` i ${WX_PHEN[x].pl}`)).join("");
  let en, pl, g;
  if (desc === "TS") {
    g = "f";
    if (list.length) {
      const [a, ...b] = list, p = WX_PHEN[a];
      en = `thunderstorm with ${intEn}${enList}`;
      pl = `burza ${p.z} ${int ? int.ins[G[p.g]] + " " : ""}${p.ins}${b.map((x) => ` i ${WX_PHEN[x].ins}`).join("")}`;
    } else {
      en = `${intEn}thunderstorm`;
      pl = `${intNom("f")}burza`;
    }
  } else if (desc === "SH" || desc === "FZ") {
    if (!list.length) {
      if (desc === "FZ") return null;
      en = "showers"; pl = "opady przelotne"; g = "p";
    } else {
      const [a, ...b] = list;
      g = WX_PHEN[a].g;
      en = desc === "SH" ? `${intEn}${enList} showers` : `${intEn}freezing ${enList}`;
      pl = `${intNom(g)}${ADJ[desc].nom[G[g]]} ${WX_PHEN[a].pl}${rest(b)}`;
    }
  } else if (desc) {
    const f = FIXED[desc + list.join("")];
    if (!f) return null;
    g = f.g;
    en = intEn + f.en;
    pl = intNom(g) + f.pl;
  } else {
    const [a, ...b] = list;
    if (a === "FC" && pre === "+" && !b.length) {
      en = "tornado or waterspout"; pl = "tr\u0105ba powietrzna lub wodna"; g = "f";
    } else {
      g = WX_PHEN[a].g;
      en = intEn + enList;
      pl = `${intNom(g)}${WX_PHEN[a].pl}${rest(b)}`;
    }
  }
  if (pre === "VC") { en += " in the vicinity"; pl += " w pobli\u017cu"; }
  if (re) { en = "recent " + en; pl = `${ADJ.RE.nom[G[g]]} ${pl}`; }
  return { en, pl };
}

// jedna grupa -> { parts: [[klasa, tekst]], dec } ("" = biały); st.rmk: po RMK reszta biała, bez opisów
const P = (...xs) => xs.filter(([, t]) => t);
export function groupParts(t, st = {}) {
  let m;
  if (st.rmk) return { parts: [["", t]] };
  if (t === "RMK") { st.rmk = true; return { parts: [["mt-key", t]] }; }
  if (t === "NIL") return { parts: [["mt-nil", t]] };
  if (/^(BECMG|TEMPO|NOSIG|INTER|PROB30|PROB40)$/.test(t)) return { parts: [["mt-trend", t]] };
  if ((m = /^(FM|TL|AT)(\d{4}|\d{6})$/.exec(t))) return { parts: [["mt-trend", m[1]], ["mt-val", m[2]]] };
  if ((m = /^(\d{2})(\d{4})Z$/.exec(t))) return { parts: [["mt-key", m[1]], ["mt-val", m[2]], ["", "Z"]] };
  if ((m = /^(\d{2})(\d{2})\/(\d{2})(\d{2})$/.exec(t))) return { parts: [["mt-key", m[1]], ["mt-val", m[2]], ["", "/"], ["mt-key", m[3]], ["mt-val", m[4]]] };
  if ((m = /^(\d{3}|VRB)(P?\d{2,3})(?:(G)(P?\d{2,3}))?(KT|MPS|KMH)$/.exec(t)))
    return { parts: P(["mt-key", m[1]], ["mt-val", m[2]], ["", m[3]], ["mt-val", m[4]], ["", m[5]]) };
  if ((m = /^(\d{3})V(\d{3})$/.exec(t))) return { parts: [["mt-key", m[1]], ["", "V"], ["mt-key", m[2]]] };
  if ((m = /^(\d{4})(NDV|N|NE|E|SE|S|SW|W|NW)?$/.exec(t))) return { parts: P(["mt-val", m[1]], ["", m[2]]) };
  if ((m = /^([PM]?\d+(?:\/\d+)?)(SM)$/.exec(t))) return { parts: [["mt-val", m[1]], ["", m[2]]] };
  if (t === "CAVOK") return { parts: [["mt-val", t]] };
  if ((m = /^R(\d{2}[LCR]?)\/([PM]?)(\d{4})(?:V([PM]?)(\d{4}))?(FT)?(\/?[UDN])?$/.exec(t)))
    return { parts: P(["", "R"], ["mt-key", m[1]], ["", "/" + m[2]], ["mt-val", m[3]], ["", m[5] ? "V" + m[4] : ""], ["mt-val", m[5]],
      ["", (m[6] || "") + (m[7] || "")]) };
  if ((m = /^R(\d{2}[LCR]?)\/(\d{6}|CLRD\d\d)$/.exec(t))) return { parts: [["", "R"], ["mt-key", m[1]], ["", "/"], ["mt-val", m[2]]] };
  if ((m = /^(FEW|SCT|BKN|OVC|VV)(\d{3}|\/{3})(CB|TCU|\/{3})?$/.exec(t)))
    return { parts: P(["mt-cov", m[1]], [m[2][0] === "/" ? "" : "mt-val", m[2]], [m[3] && m[3][0] !== "/" ? "mt-key" : "", m[3]]) };
  if (/^(NSC|NCD|SKC|CLR)$/.test(t)) return { parts: [["mt-cov", t]] };
  if ((m = /^([QA])(\d{4})$/.exec(t))) return { parts: [["", m[1]], ["mt-val", m[2]]] };
  if ((m = /^(T[XN]M?\d{2}\/)(\d{2})(\d{2})Z$/.exec(t))) return { parts: [["", m[1]], ["mt-key", m[2]], ["mt-val", m[3]], ["", "Z"]] };
  const dec = wxPhrase(t);
  return dec ? { parts: [["mt-key", t]], dec } : { parts: [["", t]] };
}

// linie grup bez "METAR"/"TAF" na początku i bez kodu stacji (jest w osobnej kolumnie); TAF: grupa zmian w nowej linii
export function wxLinesOf(kind, raw, icao) {
  let toks = String(raw || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  if (toks[0] === "METAR" || toks[0] === "TAF") toks = toks.slice(1);
  const i = toks.indexOf(String(icao || "").toUpperCase());
  if (i >= 0 && i < 3) toks.splice(i, 1);   // po SPECI / AMD / COR
  if (!toks.length) return [];
  return (kind === "taf" ? splitTaf(toks.join(" ")) : [toks.join(" ")]).map((l) => l.split(" "));
}

// treść komórki: linie z grupami; grupa (z opisem) nie łamie się w środku, linia zawija się między grupami
export function wxBody(kind, raw, icao, { decode = true } = {}) {
  const st = {};
  return wxLinesOf(kind, raw, icao).map((line, n) => `<div class="mt-ln${n ? " mt-cont" : ""}">${line.map((t) => {
    const eq = t.length > 1 && t.endsWith("=") ? "=" : "";
    const g = groupParts(eq ? t.slice(0, -1) : t, st);
    const html = g.parts.map(([c, x]) => (c ? `<span class="${c}">${esc(x)}</span>` : esc(x))).join("");
    const dec = decode && g.dec ? `<span class="mt-dec">[${esc(g.dec.en)} / ${esc(g.dec.pl)}]</span>` : "";
    return `<span class="mt-g">${html}${dec}${eq}</span>`;
  }).join(" ")}</div>`).join("");
}

// wiersz tabeli: stacja | treść (NIL, gdy serwer nie ma komunikatu)
export const wxRow = (kind, r, opts) => `<tr><td class="mt-st">${esc(r.icao)}</td><td class="mt-tx">${r.raw
  ? wxBody(kind, r.raw, r.icao, opts) : `<div class="mt-ln"><span class="mt-nil">NIL</span></div>`}</td></tr>`;
export const wxTable = (kind, rows, opts) => `<table class="mt-tab"><tbody>${rows.map((r) => wxRow(kind, r, opts)).join("")}</tbody></table>`;
