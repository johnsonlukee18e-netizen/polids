import { api, esc, h } from "../api.js";

const CHANGES = [
  ["07.10.2026", "ADMIN: lista CID-ów z dostępem, odmowy logowania"],
  ["07.10.2026", "0.9.0 - wersja serwerowa: Docker, logowanie przez VATSIM Connect, PWA"],
  ["07.10.2026", "Poprawki pod wielu użytkowników naraz, walidacja parametrów API"],
  ["06.10.2026", "MAP: sektoryzacja LOW/MID/HIGH wg łańcuchów VACS"],
  ["06.10.2026", "RADIO: stanowiska sąsiadów jak w profilu VACS ACC_EPWW"],
  ["06.10.2026", "AERODROME: paski EFES w zakładce RUCH"],
  ["06.10.2026", "Wygląd w stylu NM UI"],
  ["06.10.2026", "AERODROME: widok AWOS, wschód i zachód słońca"],
  ["06.10.2026", "METEO: mapa QNH regionalnego"],
  ["06.10.2026", "MAP: scenariusze i TV z vIFF, szczegóły lotu"],
  ["05.10.2026", "AERODROME: odloty z vIFF (EOBT, CTOT, CDM)"],
  ["05.10.2026", "MAP: TMA/CTR, przepustowość sektorów, karta lotniska, plakietki ATC"],
  ["05.10.2026", "EMERGENCY, CHECKLIST, PHRASEOLOGY"],
  ["05.10.2026", "AERODROME: pas w użyciu z ATIS / pas preferowany, NOTAM"],
  ["05.10.2026", "RADIO: kto jest online, rezerwacje"],
  ["05.10.2026", "MAP: ruch VATSIM, trasy, granice FIR"],
  ["05.10.2026", "Import sektorówki EPWW, navdata, callsignów i typów samolotów"],
  ["05.10.2026", "Pierwsza wersja"],
];

const TILES = [
  ["aerodrome", "AERODROME", "Lotnisko na jednym ekranie: METAR, wiatr, pasy, ATIS, ruch z vIFF, NOTAM, widok AWOS."],
  ["meteo", "METEO", "METAR i TAF lotnisk, mapa QNH regionalnego."],
  ["map", "MAP", "Ruch VATSIM, sektory, TMA/CTR, przepustowość sektorów i status lotu z vIFF."],
  ["radio", "RADIO", "Częstotliwości, kto jest online i rezerwacje na dziś."],
  ["callsign", "CALLSIGN", "Znaki wywoławcze linii lotniczych."],
  ["aircraft", "AIRCRAFT", "Typy samolotów, kategorie turbulencji, zdjęcia."],
  ["checklist", "CHECKLIST", "Otwarcie i zamknięcie stanowiska, przekazanie, zmiana pasa."],
  ["emergency", "EMERGENCY", "ASSIST i checklisty sytuacji awaryjnych."],
];

export default {
  mount(root, ctx) {
    const pane = h(`<div class="pane about">
      <div class="about-head">
        <div class="logo">${esc(ctx.config.name || "")}<small>${esc(ctx.config.tagline || "")}</small></div>
        <div class="card about-info"><h3>System</h3><dl class="props info"></dl></div>
      </div>
      <div class="about-tiles">${TILES.map(([tab, name, txt]) => `<button class="about-tile${tab === "emergency" ? " red" : ""}" data-open="${tab}"><b>${name}</b><span>${esc(txt)}</span></button>`).join("")}</div>
      <div class="card about-changes"><h3>Ostatnie zmiany</h3>
        <table class="data"><tbody>${CHANGES.map(([d, t]) => `<tr><td class="mono">${esc(d)}</td><td>${esc(t)}</td></tr>`).join("")}</tbody></table></div>
    </div>`);
    root.append(pane);
    pane.querySelector(".about-tiles").addEventListener("click", (e) => {
      const b = e.target.closest("[data-open]");
      if (b) location.hash = b.dataset.open;
    });
    const load = async () => {
      const st = await api("/api/status").catch(() => ({ counts: {} }));
      const c = st.counts;
      const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
      pane.querySelector(".info").innerHTML = row("Wersja", esc(ctx.config.version || "–"))
        + row("Cykl AIRAC", `${esc(ctx.config.airac.ident)} (od ${esc(ctx.config.airac.effective)})`)
        + row("Dane", `${c.aerodromes ?? "–"} lotnisk, ${c.aircraft_types ?? "–"} typów samolotów, ${c.callsigns ?? "–"} callsignów`)
        + row("Nawigacja", `${c.nav_points ?? "–"} punktów, ${c.airway_segments ?? "–"} odcinków dróg, ${c.sectors ?? "–"} sektorów, ${c.atc_positions ?? "–"} stanowisk ATC`)
        + row("Klucz CARTO", ctx.config.carto_api_key ? "wczytany" : "brak (mapa używa zastępczego podkładu Esri)")
        + row("Klucz OpenAIP", ctx.config.openaip_api_key ? "wczytany" : "brak")
        + row("Logowanie", ctx.me?.user ? `${esc(ctx.me.user.name || "")} (CID ${esc(ctx.me.user.cid)})${ctx.me.admin ? ", administrator" : ""}` : "wyłączone (tryb lokalny)")
        + row("API", `<a href="/docs" target="_blank">/docs</a>`);
    };
    return { activate: load };
  },
};
