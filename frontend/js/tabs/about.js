import { api, esc, h } from "../api.js";

const CHANGES = [
  ["18.10.2026", "0.12.5 – per issue #18: the whole interface in English and with sharp edges (no rounded corners), as in PANSA systems. AERODROME views are now INFO, AWOS and TRAFFIC; TRAFFIC no longer shows OFFLINE flights (known only from vIFF, pilot not connected)."],
  ["18.10.2026", "RADIO: colours as in the sector file – unstaffed airspace light grey, staffed dark, the same in LOW, MID and HIGH; TMA and CTR outlines in sector-file colours instead of blue and yellow; borders of the neighbour ACC sectors and the APP/TWR areas of aerodromes near the FIR border (e.g. LZTT, LKMT, EDDB); buttons and position tiles as on the PANDORA photo."],
  ["18.10.2026", "METEO: WIND and RADAR right after METAR/TAF, before GAMET; WIND always opens at 0 ft. QNH: the regional QNH map redrawn like the PANSA chart, with TMA and CTR outlines from the sector files."],
  ["18.10.2026", "MAP: aircraft labels like the PANSA P21 label – callsign and ground speed; level (A and altitude below the transition level) with a climb or descent arrow; type and wake category with the destination, or the FIR exit point for transits and departures abroad; h s r and the requested level. Smaller symbols, aerodromes as closed hexagons, the three Polish notes removed."],
  ["18.10.2026", "STRIP: nothing opens on hover; a click on a strip (or Enter) opens the EXTENDED LABEL WINDOW laid out as in the SDD manual: callsign with RVSM (W) and 8.33 (Y) status, full radio callsign, transponder and code, type and wake category, STS, assigned code when different, aerodromes with alternate, SID/STAR and runway, flight rules and route points, RFL, remarks, RVR, equipment and PBN, heading, ground speed and vertical rate. KEY shows the field names."],
  ["18.10.2026", "AIRCRAFT: only the types from ICAO_Aircraft.json, one record per designator, no added variants. AD CIV: the aerodrome buttons open the list of charts (AD 2.24). COORDINATION: sub-tabs LoA and DOCUMENTS. CONVERSION: UTC and Poland (CET/CEST) clocks instead of the time calculator, no scroll bar."],
  ["17.10.2026", "0.12.4 – polids.pl starts again: the Docker image gives the application files read permission, so files changed on the server (saved without read access for others) no longer block startup as after the 0.12.3 deployment."],
  ["15.10.2026", "0.12.3 – per issue #13: new tabs COORDINATION, CONVERSION and SQUAWK; PHRASEOLOGY moved to OTHER as a sub-tab after DOCS (the old #phraseology address redirects). The hidden ADMIN button no longer takes space in the menu."],
  ["15.10.2026", "HOME: rating of the logged-in controller, the position they are logged in on in VATSIM and their bookings for the next 24 hours; position choice shared with AERODROME › OVERVIEW and a PREPARE SESSION button (OVERVIEW, or the aerodrome for TWR); version and current AIRAC with dates at the bottom."],
  ["15.10.2026", "METEO: order METAR, TAF, GAMET, SIGWX, ICING, QNH, SAT EUR, SAT PL, TURB, SUN (WIND and RADAR at the end). IMGW GAMET for regions A1–A5 or all, with validity and a map of the regions; ICING: icing from Windy at FL050–FL300; SUN: day and night map of the Earth plus sunrise, sunset, transit, BMCT and EECT for any aerodrome or point on the map (UTC and Poland LT). Sun times computed correctly far from Greenwich too."],
  ["15.10.2026", "AD CIV: buttons for the 15 AD 2 aerodromes, each opens the aerodrome page in eAIP (address #adciv/EPWA). eAIP links follow the amendment of the current AIRAC cycle by themselves. CALLSIGN and AIRCRAFT: ALL button instead of ∗ across the full width, letters in two equal columns."],
  ["15.10.2026", "COORDINATION: LoA transfers as in ATCISS – EXIT (COPX) and ENTRY (COPN), filter by points (several words at once), choice of position with the sectors it covers (coverage order and controllers online), FIRs and LOA/LOP type; DOCUMENTS with readable names, AIRAC, FIR and sector tags and the PDF beside them. LOA is no longer in OTHER › DOCS, and in RADIO the COORDINATION › button opens the document. DOCUMENTS also holds 20 LOPs (Warszawa ACC, 4 APP, 15 TWR) with aerodrome ICAO codes – title only for now, content in preparation."],
  ["15.10.2026", "CONVERSION: unit calculator – hPa/inHg/mmHg, ft/m/FL, altitude and FL at QNH, NM/km/SM, kt/km/h/m/s/mph, Mach/TAS/CAS in ISA, vertical speed, gradient, °C/°F/K, kg/lb/t, UTC and Poland LT."],
  ["15.10.2026", "MAP: only traffic related to Poland – departures from EP aerodromes, arrivals to them and transits through FIR EPWW (the aircraft is in the FIR now or the rest of its flight plan route enters it). An aircraft without a flight plan only when it is in FIR EPWW. The selected flight stays on the map, even outside this traffic."],
  ["15.10.2026", "SQUAWK: SSR code pools of FIR EPWW from EUROCONTROL CAL v4.13 (area EUR-E, unit EP), plus CCAMS, NATO and all EUR-E entries; code check and special codes (7500, 7600, 7700, 2000, 7000, 1000)."],
  ["14.10.2026", "0.12.2 – EPWW and neighbour sectors from one file data/seed/sectors.geojson, generated from the .ese files (MAP and RADIO take them from there); new EDGG (Langen) .ese file: EDGG sectors on MAP, and in AERODROME › ED and ET all aerodromes with its positions."],
  ["14.10.2026", "MAP: with staffing by controllers online, sectors covered by the same position are one area in its colour with one label (position and frequency); a border only where the covering position changes, unstaffed airspace is not drawn (when nobody is online in a FIR, only the FIR borders remain)."],
  ["14.10.2026", "MAP: new Positions section – list of positions of FIR EPWW and neighbours (ACC, FIS and aerodromes, e.g. EPGD: GD APP, GD TWR, GD GND), logged-in positions ticked by default. A click turns an offline position on as if logged in (SYM, dashed outline) or hides a logged-in one; sectorisation and aerodrome labels follow this choice. “as online” returns to the network state, “clear” turns all off. The list has the positions from the EPWW .ese file, from vacs-data and those covering neighbour sectors; positions logged in at other foreign aerodromes (e.g. EDDS_TWR, LOWW_TWR) always have a label and cannot be turned off."],
  ["14.10.2026", "RADIO: ACC sectors on the LOW, MID and HIGH previews alike – one area and one label per position, borders only where the covering position changes, unstaffed sectors are not drawn (the FIR EPWW border remains)."],
  ["14.10.2026", "AERODROME: runways, frequencies and elevations of aerodromes from AIP Poland and AIP MIL (PANSA eAIP, AIRAC 10/26), VFR landing sites outside the AIP from lotniska.dlapilota.pl; e.g. EPBK now has 09R/27L 1350 m and grass 09L/27R instead of the wrong 01/19 and 08/26. Frequencies with operating hours and a remark (e.g. EPRA 118.430: civil and military TWR): for a position from the .ese file in the tooltip, AIP frequencies without a position in the .ese below the list (e.g. EPRA MIL GND 119.155, APP 128.680)."],
  ["14.10.2026", "Preferred runway per AIP AD 2.21 for EPWA, EPMO, EPWR, EPGD and EPPO: hours (winter and summer in UTC), wind limits with gusts, exceptions (thunderstorm, LVP); the reason in the tooltip, e.g. “ARR/DEP 08 per AIP (2000-0400 UTC), because 26: tailwind 8 kt > 5 kt”. In LVP the runways allowed by AD 2.22: EPWA landings 33 or 11 (RWY 11 CAT II from RVR 300 m, RWY 33 CAT IIIA from 175 m), take-offs 29 or 15; EPPO landings 28, take-offs 28 or 10; take-offs never against the landing direction, runway pair within the wind limit (EPWA at 070/10 landings 11, take-offs 15), with take-off runway RVR < 125 m the warning “take-offs not allowed”. When noise does not decide (e.g. fog), the take-off runway still comes from the AIP list (EPWA ARR 33 with ILS, DEP 29)."],
  ["14.10.2026", "LVP: thresholds of each aerodrome from the AIP (preparation, introduction, cancellation) in the tooltip; states LVP PREPARATION, LVP IN FORCE and LVP CANCELLED (for 30 min after cancellation) in AERODROME, AWOS and OVERVIEW; aerodromes without LVP in the AIP: “LVP not applicable”; military aerodromes: LVP for departures only."],
  ["12.10.2026", "0.12.1 – ATIS: landing and take-off runways read separately (e.g. EPWA “APPROACH RUNWAY 33 … DEPARTURES RUNWAY 29” gives ARR 33 and DEP 29); closed runways, runways on request, expected later and mentioned in remarks are skipped; separate arrival and departure ATIS are merged."],
  ["12.10.2026", "Menu: INOP under AD VFR; DOCS moved to OTHER as the first sub-tab (old #docs addresses redirect). AERODROME: aerodrome lists of all FIRs in one column, with PgUp and PgDn. Frequency panel: the controller's name always visible next to the position."],
  ["12.10.2026", "AWOS: 1 RWY / 2 RWYS / AUTO switch under the wind; in 2 RWYS a separate runway in the DEP and ARR columns; a manual choice returns to automatic after a runway change in ATIS or after 12 h. TRAFFIC at aerodromes without A-CDM: EOBT and ETOT instead of TSAT and TTOT, a flight with a slot at CTOT when CTOT is later than ETOT."],
  ["12.10.2026", "RADIO: EPWW, TMA, CTR and FIS sectors with nobody online show the ID only, without frequency; the frequency appears when someone covers them (a tower covered by APP: APP frequency with ↑APP)."],
  ["12.10.2026", "RADIO: neighbour stacks as in VACS (only sectors bordering EPWW, no FMP), frequency only when someone covers the sector, ADVISORY 122.800 in a stack with nobody online, each FL boundary once; APP layer in TMA parts (WA APP, WA N APP, WA S APP), TMA without APP with the tower frequency, TMA Rzeszów with KK RZ APP; APP and TWR labels beside the TMA and CTR outlines with a leader line to the point; LOW with an altitude slider."],
  ["12.10.2026", "0.12.0 – menu as in PANDORA: the ← arrow at the top returns to the previous screen (also sub-tabs and the selected aerodrome, just like the browser Back button); “?” is HOME with the welcome only, and the program information is in ABOUT; new tabs SYT OP, AUP, STRIP and OTHER (AUP and OTHER will be available in the future)."],
  ["12.10.2026", "RADIO on one page as in PANDORA: FIR EPWW LOW preview with neighbours EDWW, EDMM, EDUU, ESAA and LKAA, HIGH with UMKK, EYVL, UMMV, UKLV and LZBB, and a small MID; each sector shows its ID and the frequency of the position covering it now; neighbour frequencies split by levels; layers ATIS, LOW MID HIGH, APP, TWR, TWR/ATIS and FIS; clicking a neighbour FIR name opens the LOA extract. This one page replaces the former RADIO sub-tabs (aerodromes, GEO with the coverage map, SECTORISATION, bookings)."],
  ["12.10.2026", "AERODROME: sub-tabs 0 (FIR EPWW overview), EPWW, ESAA, ED, ET, LKAA, LZBB, UMKK, EYVL, UMMV and UKLV with aerodrome lists (also VFR and MIL) and a SHOW / CLEAR search; a foreign aerodrome shows METAR, TAF, ATIS and the APP, TWR, GND, DEL, ATIS positions. TRAFFIC like DMAN/AMAN: TSAT, TTOT and ELDT ladders and an AMAN view with entry points and FLOW spacing. EFES strips moved to the STRIP tab."],
  ["12.10.2026", "METEO: SAT PL and SAT EUR, TURB (IMGW turbulence charts from +0 to +21 h) and SIGWX (IMGW). SYT OP: all active NOTAMs of FIR EPWW and the main aerodromes with filter and sorting."],
  ["11.10.2026", "0.11.1 – AERODROME › OVERVIEW: on polids.pl in a browser with an ad blocker (uBlock, AdBlock, Opera, Brave) the area under the METAR bar was empty. Generic EasyList rules hid the classes “ad-grid” and “ad-col” (ad = aerodrome) as ads; all names with “ad” in the interface changed to “aero”. The wind card without METAR shows “–” instead of “undefined”."],
  ["08.10.2026", "AERODROME › OVERVIEW: one screen for FIR EPWW with the transition level (one for the country: FL080, and FL090 when QNH ≤ 995 hPa at any aerodrome), METARs of all aerodromes with LVP state, active NOTAMs, ECFMP and vIFF restrictions and the vIFF Airport Monitor. Position filter: APP or ACC narrows the aerodromes (e.g. EPWA_APP: EPWA, EPMO, EPLL, EPRA) and shows the opening checklist, TWR goes to the aerodrome OVERVIEW."],
  ["08.10.2026", "RADIO: new EDUU/EDYY tab; real radio callsigns of neighbours with sector names (VATSIM Germany Knowledgebase, LOA); LOA bar with transfer tables, rules and the PDF; quick jump buttons in all FIRs; VFR aerodromes without ID. DOCS: new LOA category."],
  ["08.10.2026", "METEO › QNH: new base map like the QNH regions chart from AIP Poland (PANSA), regions redrawn, emergency bands 15–17 at 53°N and 51°N, TMA/MTMA and SECTOR n boxes with QNH as in vAWOS, grey TMA/CTR labels from the AIP chart (“TMA/CTR labels” switch). AWOS: wind every 5 s with a smooth pointer, RVR from METAR, “>2000 M” or a simulation in poor visibility. MAP: ATIS line by line, controller data on hovering a label or position description (also ESGG GND), list of neighbouring FIRs collapsed by default."],
  ["08.10.2026", "New name: PolIDS (Polish Integrated Display System), formerly vPANDORA / POLIDS. New logo in the menu, on this page and on the login page, new app icons and favicon."],
  ["07.10.2026", "Denmark (EKDK) from its own .ese file too: Copenhagen, Bornholm and FIS sectors on MAP and in RADIO › GEO, coverage order from their file. Only Belarus is still taken from the EPWW file."],
  ["07.10.2026", "Neighbour sectors (Germany, Sweden, Lithuania, Czechia, Slovakia, Lviv, Kaliningrad) from their own .ese files: MAP draws them exactly at the selected level and colours them by who covers them (coverage order from their files), and RADIO › GEO shows the exact reach of their positions. From the Ukrainian package only Lviv is taken, without its old Polish sectors. Runway-dependent sectors in the western configuration."],
  ["07.10.2026", "MAP: corrected shape of the UKLV (Lviv) sector – no false triangle in the middle; grey FIR names no longer cover the neighbour frequency."],
  ["07.10.2026", "ADMIN: list of CIDs with access, login refusals"],
  ["07.10.2026", "0.9.0 - server version: Docker, login via VATSIM Connect, PWA"],
  ["07.10.2026", "Fixes for many simultaneous users, API parameter validation"],
  ["06.10.2026", "RADIO › GEO: position tiles like the GEO pages in VACS (no FMP), with frequencies and who is online; beside them a coverage map: click one or more positions (also any position of the neighbouring FIRs) to see what they cover. Neighbours: all positions from the .ese file and vacs-data, coverage from VATSpy."],
  ["06.10.2026", "RADIO › SECTORISATION (moved from MAP): coverage order of ACC sectors from om.plvacc.pl › ownerships instead of VACS, position list in one column, short position names (PO N APP, EPWW DBF, EDMM MEI, WA TWR)."],
  ["06.10.2026", "TMA and CTR with the full coverage order: first APP and TWR from the .ese file, then ACC per om.plvacc.pl. RADIO › SECTORISATION: TMA and CTR card, APP/TWR positions in the simulation. MAP: the TMA, CTA and CTR tooltip shows all positions in order with frequency and who is online; CTA layer (e.g. CTA 02 above TMA Warszawa) on by default. RADIO › GEO: neighbour tiles in FIR colours as in VACS. Messages in Polish when the server does not respond."],
  ["06.10.2026", "MAP: airspace drawn for the selected level (FL) or for all levels, lists to pick single ACC, TMA and CTR sectors and neighbouring FIRs, TMA/CTR description on hover, aircraft in departure / arrival / transit colours, ATIS with the controller's name, no UNICOM and no inheritance hierarchy. Fixed TMA Warszawa highlighting with EPWA APP online."],
  ["06.10.2026", "METEO: WIND (formerly WINDY) with a 0 ft / 3000 ft switch on approach (FAF/IAF point of each runway), METAR and TAF in alphabetical order. AERODROME: 0 ft and 3000 ft wind at the approach points (Open-Meteo), ARR/DEP runways in the flight list colours."],
  ["06.10.2026", "AIRCRAFT: AIRBUS, BOEING, EMBRAER, MCDONNELL, ATR, CESSNA buttons. The whole app in the Consolas font."],
  ["06.10.2026", "MAP: LOW/MID/HIGH sectorisation per VACS chains"],
  ["06.10.2026", "RADIO: neighbour positions as in the VACS ACC_EPWW profile"],
  ["06.10.2026", "AERODROME: EFES strips in the TRAFFIC tab"],
  ["06.10.2026", "NM UI look"],
  ["06.10.2026", "AERODROME: AWOS view, sunrise and sunset"],
  ["06.10.2026", "METEO: regional QNH map"],
  ["06.10.2026", "MAP: vIFF scenarios and TV, flight details"],
  ["05.10.2026", "AERODROME: departures from vIFF (EOBT, CTOT, CDM)"],
  ["05.10.2026", "MAP: TMA/CTR, sector capacity, aerodrome card, ATC labels"],
  ["05.10.2026", "EMERGENCY, CHECKLIST, PHRASEOLOGY"],
  ["05.10.2026", "AERODROME: runway in use from ATIS / preferred runway, NOTAM"],
  ["05.10.2026", "RADIO: who is online, bookings"],
  ["05.10.2026", "MAP: VATSIM traffic, routes, FIR borders"],
  ["05.10.2026", "Import of the EPWW sector file, navdata, callsigns and aircraft types"],
  ["05.10.2026", "First version"],
];

const TILES = [
  ["aerodrome", "AERODROME", "FIR EPWW overview, aerodrome lists of EPWW and neighbours, the aerodrome on one screen: METAR, wind, runways, ATIS, NOTAM, AWOS, TRAFFIC (DMAN/AMAN)."],
  ["meteo", "METEO", "METAR and TAF of aerodromes, surface and approach wind, radar, GAMET, SIGWX, icing, regional QNH map, satellite, turbulence, sun."],
  ["map", "MAP", "VATSIM traffic, airspace at the selected level, TMA/CTR, sector capacity and flight status from vIFF."],
  ["radio", "RADIO", "One page as in PANDORA: EPWW ACC sectors on LOW/MID/HIGH previews with frequencies, APP/TWR/FIS layers, ATIS and neighbour positions; a neighbour FIR name opens the LOA extract."],
  ["coordination", "COORDINATION", "LoA and LOP: transfers by point and position, documents with tags."],
  ["sytop", "SYT OP", "Active NOTAMs of FIR EPWW and the main aerodromes."],
  ["strip", "STRIP", "EFES flight progress strips for the 15 main aerodromes; a click opens the extended label window."],
  ["callsign", "CALLSIGN", "Airline radiotelephony callsigns."],
  ["aircraft", "AIRCRAFT", "ICAO aircraft types by manufacturer, wake turbulence categories, performance, photos."],
  ["squawk", "SQUAWK", "SSR code pools of FIR EPWW from EUROCONTROL CAL and special codes."],
  ["conversion", "CONVERSION", "Unit conversion: pressure, height, FL at QNH, speed, Mach; UTC and Poland LT clocks."],
  ["checklist", "CHECKLIST", "Position opening and closing, handover, runway change."],
  ["emergency", "EMERGENCY", "ASSIST and emergency checklists."],
];

export default {
  mount(root, ctx) {
    const pane = h(`<div class="pane about">
      <div class="about-head">
        <div class="logo"><img src="/static/icons/polids-logo.svg" alt="${esc(ctx.config.name || "PolIDS")} – Polish Integrated Display System"><small>VATSIM PL vACC</small></div>
        <div class="card about-info"><h3>System</h3><dl class="props info"></dl></div>
      </div>
      <div class="about-tiles">${TILES.map(([tab, name, txt]) => `<button class="about-tile${tab === "emergency" ? " red" : ""}" data-open="${tab}"><b>${name}</b><span>${esc(txt)}</span></button>`).join("")}</div>
      <div class="card about-changes"><h3>Recent changes</h3>
        <table class="data"><tbody>${CHANGES.map(([d, t]) => `<tr><td class="mono">${esc(d)}</td><td>${esc(t)}</td></tr>`).join("")}</tbody></table></div>
    </div>`);
    root.append(pane);
    pane.querySelector(".about-tiles").addEventListener("click", (e) => {
      const b = e.target.closest("[data-open]");
      if (b) ctx.open(b.dataset.open);
    });
    const load = async () => {
      const st = await api("/api/status").catch(() => ({ counts: {} }));
      const c = st.counts;
      const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
      pane.querySelector(".info").innerHTML = row("Version", esc(ctx.config.version || "–"))
        + row("AIRAC cycle", `${esc(ctx.config.airac.ident)} (from ${esc(ctx.config.airac.effective)})`)
        + row("Data", `${c.aerodromes ?? "–"} aerodromes, ${c.aircraft_types ?? "–"} aircraft types, ${c.callsigns ?? "–"} callsigns`)
        + row("Navigation", `${c.nav_points ?? "–"} points, ${c.airway_segments ?? "–"} airway segments, ${c.sectors ?? "–"} sectors, ${c.atc_positions ?? "–"} ATC positions`)
        + row("CARTO key", ctx.config.carto_api_key ? "loaded" : "none (the map uses the Esri fallback base map)")
        + row("OpenAIP key", ctx.config.openaip_api_key ? "loaded" : "none")
        + row("Login", ctx.me?.user ? `${esc(ctx.me.user.name || "")} (CID ${esc(ctx.me.user.cid)})${ctx.me.admin ? ", administrator" : ""}` : "off (local mode)")
        + row("API", `<a href="/docs" target="_blank">/docs</a>`);
    };
    return { activate: load };
  },
};
