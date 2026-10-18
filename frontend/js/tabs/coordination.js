import { api, choiceGet, debounce, esc, frameGo, h, lsGet, lsSet, remember, stash, stashed, subtabs, vatsimOnline } from "../api.js";
import {
  POS_KEY, agreementsArg, blockHtml, defaultPosition, docCardHtml, docFilter, docFocus, docRef, docSelect, docsArg, notesHtml,
  ownedKeys, parseArg, positionOptions, shortCs, sumHtml, view,
} from "../agreements.js";

// COORDINATION (0.12.3): wszystkie LOA i LOP, jak „Agreements” w ATCISS (VATSIM Germany). Podmenu:
// POROZUMIENIA – tabela przekazań WYJŚCIE (COPX) / WEJŚCIE (COPN) z filtrem punktów, wyborem stanowiska (pokazuje tylko
//   sektory, które ono teraz obsługuje wg kolejności przejmowania i zalogowanych w VATSIM), FIR-ami i rodzajem dokumentu;
// DOKUMENTY – karty dokumentów (nazwa, FIR-y, AIRAC, wersja, sektory) i PDF obok.
// Adresy: "#coordination/agreements[/<stanowisko|ALL>[/<filtr>]]" i "#coordination/docs/<id>" (także FIR z loa.json albo
// plik w data/docs – tak otwiera RADIO i stare odnośniki). Dane: GET /api/coordination (data/seed/coordination.json
// i loa.json).
const OFF_KEY = "coordination.firs.off", TYPES_KEY = "coordination.types.off", NOTES_KEY = "coordination.notes.open";
const lsSetOf = (key) => { try { return new Set(JSON.parse(lsGet(key) || "[]")); } catch { return new Set(); } };

export default {
  mount(root) {
    // pos: undefined = jeszcze nie wybrane (po wczytaniu: stanowisko z OVERVIEW/HOME), "" = wszystkie
    const st = { pos: undefined, q: "", doc: "", off: lsSetOf(OFF_KEY), typesOff: lsSetOf(TYPES_KEY), dfir: "", dtype: "" };
    let data = null, err = "", online = new Set(), onInfo = {}, net = null;   // net: true/false = dane VATSIM są/nie ma
    let agr = null, docs = null, sub = null;
    let wantTop = null;   // przewinięcie tabel z wpisu historii (← / Wstecz z DOKUMENTY), ustawiane po narysowaniu wierszy
    const argOf = (id = sub?.current()) => (id === "docs" ? docsArg(st.doc) : agreementsArg(st.pos, st.q));
    const freq = (cs) => onInfo[cs]?.frequency || data?.positions.find((p) => p.callsign === cs)?.frequency || "";

    // --- POROZUMIENIA
    function mountAgreements(pane) {
      const el = h(`<div class="cr-wrap">
        <div class="cr-main"><div class="cr-sum"></div><div class="cr-blocks"><p class="hint">Loading LoA…</p></div>
          <details class="cr-notes"><summary>LOA rules</summary><div class="cr-notes-b"></div></details></div>
        <div class="cr-side">
          <div class="ms-card"><h4>Points / filter</h4>
            <input type="search" class="field cr-q" list="cr-cops" placeholder="e.g. ALUKA EPKS" autocomplete="off" spellcheck="false" aria-label="Points and filter">
            <datalist id="cr-cops"></datalist>
            <p class="hint">Several full COP names: any of them (ALUKA BODLA). All other words must match (aerodrome, sector, FIR, FL, conditions). Rows with a full COP name go to the top.</p></div>
          <div class="ms-card"><h4>Position</h4><select class="field cr-pos" aria-label="Position"><option value="">All</option></select>
            <p class="hint cr-own"></p></div>
          <div class="ms-card"><h4>FIR</h4><div class="cr-tgs cr-firs"></div></div>
          <div class="ms-card"><h4>Type</h4><div class="cr-tgs cr-types"></div></div>
        </div></div>`);
      pane.append(el);
      const $ = (s) => el.querySelector(s);
      const q = $(".cr-q"), pos = $(".cr-pos"), notes = $(".cr-notes"), main = $(".cr-main");
      notes.open = lsGet(NOTES_KEY) === "1";
      notes.addEventListener("toggle", () => lsSet(NOTES_KEY, notes.open ? "1" : "0"));

      let built = null;   // dane, dla których są już podpowiedzi COP i lista stanowisk (bez przebudowy co minutę)
      const refresh = () => {
        if (q.value !== st.q) q.value = st.q;   // bez przestawiania kursora w trakcie pisania
        if (!data) {
          $(".cr-blocks").innerHTML = err ? `<p class="error">${esc(err)}</p>` : `<p class="hint">Loading LoA…</p>`;
          return;
        }
        if (built !== data) {
          built = data;
          $("#cr-cops").innerHTML = data.cops.map((c) => `<option value="${esc(c)}"></option>`).join("");
          pos.innerHTML = positionOptions(data.positions, st.pos);
        }
        if (pos.value !== (st.pos || "")) pos.value = st.pos || "";
        const counts = {};
        data.agreements.forEach((r) => { counts[r.fir] = (counts[r.fir] || 0) + 1; counts[r.type] = (counts[r.type] || 0) + 1; });
        $(".cr-firs").innerHTML = data.firs.map((f) => `<button type="button" class="gbtn cr-tg${st.off.has(f) ? "" : " on"}" data-fir="${esc(f)}"`
          + ` title="${esc(data.notes[f]?.title || f)}">${esc(f)} <small>${counts[f] || 0}</small></button>`).join("")
          + `<button type="button" class="btn cr-all" title="Show all FIRs">all</button>`;
        $(".cr-types").innerHTML = ["LOA", "LOP"].map((t) => `<button type="button" class="gbtn cr-tg${st.typesOff.has(t) ? "" : " on"}" data-kind="${t}">`
          + `${t} <small>${counts[t] || 0}</small></button>`).join("");
        const v = view(data, { pos: st.pos || "", q: st.q, off: st.off, typesOff: st.typesOff, online });
        const x = { online, pos: st.pos || "", toks: v.toks, freq };
        $(".cr-blocks").innerHTML = blockHtml("out", v.out, data, x) + blockHtml("in", v.in, data, x);
        $(".cr-sum").innerHTML = sumHtml(v, { pos: st.pos || "", firs: data.firs, off: st.off, typesOff: st.typesOff });
        // kto obsługuje: sektory wybranego stanowiska przy obecnych zalogowanych
        const own = $(".cr-own");
        if (st.pos) {
          const keys = ownedKeys(data.chains, st.pos, online);
          const ons = data.positions.filter((p) => online.has(p.callsign) && p.callsign !== st.pos).map((p) => shortCs(p.callsign));
          own.innerHTML = (keys.length ? `Covers: <b>${esc(keys.join(", "))}</b>.` : "Covers no LOA sector now (covered by a position higher in the order).")
            + (net === false ? " No VATSIM data: computed as if nobody were online."
              : net ? ` Online: ${ons.length ? esc(ons.join(", ")) : "none of these positions"}.` : "");
        } else own.textContent = "All transfers, not split by sector.";
        const firs = [...new Set([...v.out, ...v.in].map((r) => r.fir))];
        $(".cr-notes summary").textContent = `LOA rules: transfer of control, VFR, other${firs.length ? " – " + firs.join(", ") : ""}`;
        $(".cr-notes-b").innerHTML = notesHtml(data, firs) || `<p class="hint">No rules for the selected FIRs.</p>`;
        if (wantTop !== null) { main.scrollTop = wantTop; wantTop = null; }
      };
      const saveQ = debounce(() => remember("coordination", argOf(), { replace: true }), 400);
      q.addEventListener("input", () => { st.q = q.value; refresh(); saveQ(); });
      pos.addEventListener("change", () => { st.pos = pos.value; refresh(); remember("coordination", argOf()); });
      el.addEventListener("click", (e) => {
        const tg = e.target.closest(".cr-tg");
        if (tg?.dataset.fir) {
          st.off.has(tg.dataset.fir) ? st.off.delete(tg.dataset.fir) : st.off.add(tg.dataset.fir);
          lsSet(OFF_KEY, JSON.stringify([...st.off]));
          return refresh();
        }
        if (tg?.dataset.kind) {
          st.typesOff.has(tg.dataset.kind) ? st.typesOff.delete(tg.dataset.kind) : st.typesOff.add(tg.dataset.kind);
          lsSet(TYPES_KEY, JSON.stringify([...st.typesOff]));
          return refresh();
        }
        if (e.target.closest(".cr-all")) {
          st.off.clear();
          lsSet(OFF_KEY, "[]");
          return refresh();
        }
        const doc = e.target.closest(".cr-doc");
        if (doc) openDoc(doc.dataset.doc);
      });
      refresh();
      // wyjście do DOKUMENTY (podmenu, znacznik dokumentu w wierszu): przewinięcie zostaje we wpisie historii tej tabeli,
      // ← / Wstecz wraca do tego samego wiersza (stash poza activate(), więc nie trafi do wpisu, do którego wracamy)
      const destroy = () => {
        if (data) stash("coordination", { top: main.scrollTop });
        if (agr?.el === el) agr = null;
      };
      return { refresh, destroy, el };
    }

    // --- DOKUMENTY
    function mountDocuments(pane) {
      const el = h(`<div class="mapwrap cd-wrap">
        <div class="mapside">
          <div class="ms-card"><h4>LOA and LOP documents</h4>
            <div class="ms-row"><select class="field cd-fir" aria-label="FIR"><option value="">All FIRs</option></select>
              <select class="field cd-type" aria-label="Type"><option value="">LOA and LOP</option><option>LOA</option><option>LOP</option></select></div>
            <div class="cd-list"><p class="hint">Loading…</p></div></div>
          <p class="hint">Names, tags and AIRAC: <span class="mono">data/seed/coordination.json</span>; PDFs in
            <span class="mono">data/docs/LOA</span> and <span class="mono">data/docs/LOP</span>.</p>
          <div class="cd-errs" hidden></div>
        </div>
        <iframe class="embed viewer" style="background:#333" title="Document"></iframe>
      </div>`);
      pane.append(el);
      const list = el.querySelector(".cd-list"), fir = el.querySelector(".cd-fir"), type = el.querySelector(".cd-type");
      const errs = el.querySelector(".cd-errs");
      let viewer = el.querySelector(".viewer");
      const show = (d) => {
        if (!d) return;
        st.doc = d.id;
        const url = d.exists ? d.url : "";
        if (url && viewer.getAttribute("src") !== url) viewer = frameGo(viewer, url);
        else if (!url && viewer.getAttribute("src")) {   // brak pliku: nie zostawiamy na ekranie PDF-u poprzedniego dokumentu
          const blank = viewer.cloneNode(false);
          blank.removeAttribute("src");
          viewer.replaceWith(blank);
          viewer = blank;
        }
        list.querySelectorAll(".cd-card").forEach((c) => c.classList.toggle("on", c.dataset.doc === d.id));
        list.querySelector(".cd-card.on")?.scrollIntoView({ block: "nearest" });
      };
      // reveal: dokument wskazany z zewnątrz (adres, RADIO, znacznik w POROZUMIENIACH) ma kartę na liście – filtr, który
      // go ukrywa, znika; zmiana filtra ukrywająca pokazany dokument: pierwszy z listy (adres podmieniony bez kroku historii)
      let reveal = true;
      const refresh = () => {
        if (!data) {
          list.innerHTML = err ? `<p class="error">${esc(err)}</p>` : `<p class="hint">Loading…</p>`;
          return;
        }
        // uwagi do danych (PDF bez wpisu, nieznany sektor): dla tego, kto utrzymuje coordination.json
        errs.hidden = !data.errors?.length;
        errs.innerHTML = data.errors?.length ? `<h4>To fix in the data</h4><ul>${data.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : "";
        const was = docRef(data.documents, st.doc);
        const sel = docSelect(data.documents, st.doc, { fir: st.dfir, type: st.dtype }, { reveal });
        reveal = false;
        st.dfir = sel.fir;
        st.dtype = sel.type;
        const firs = [...new Set(data.documents.flatMap((d) => d.firs))].sort();
        fir.innerHTML = `<option value="">All FIRs</option>` + firs.map((f) => `<option${f === st.dfir ? " selected" : ""}>${esc(f)}</option>`).join("");
        type.value = st.dtype;
        const ds = docFilter(data.documents, { fir: st.dfir, type: st.dtype });
        list.innerHTML = ds.length ? ds.map((d) => docCardHtml(d, { selected: d.id === sel.doc?.id, airac: data.current_airac })).join("")
          : `<p class="hint">No documents for this filter.</p>`;
        show(sel.doc);
        if (was && sel.doc && was.id !== sel.doc.id) remember("coordination", argOf(), { replace: true });
      };
      const pick = (id) => {
        const d = data && docRef(data.documents, id);
        if (!d) return false;
        if (docFilter([d], { fir: st.dfir, type: st.dtype }).length) show(d);
        else { st.doc = d.id; reveal = true; refresh(); }
        return true;
      };
      fir.addEventListener("change", () => { st.dfir = fir.value; refresh(); });
      type.addEventListener("change", () => { st.dtype = type.value; refresh(); });
      list.addEventListener("click", (e) => {
        const card = e.target.closest(".cd-card");
        if (!card || e.target.closest("a")) return;
        if (e.target.closest(".cd-agr")) return showAgreementsOf(card.dataset.doc);
        if (card.dataset.doc !== st.doc) { show(docRef(data.documents, card.dataset.doc)); remember("coordination", argOf()); }
      });
      list.addEventListener("keydown", (e) => {
        const card = e.target.closest?.(".cd-card");
        if (card && e.target === card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); card.click(); }
      });
      refresh();
      return { refresh, pick, destroy() { if (docs?.el === el) docs = null; }, el };
    }

    // wiersz tabeli → dokument; karta dokumentu → porozumienia z jego FIR-ów
    function openDoc(id) {
      st.doc = id;
      if (sub.current() !== "docs") sub.show("docs");
      else docs?.pick(id);
      remember("coordination", argOf());
    }
    // jednorazowe zawężenie bez zapisu w localStorage: po przeładowaniu wracają zapisane przełączniki FIR, a do tego
    // czasu podsumowanie nad tabelami mówi, które FIR-y są ukryte
    function showAgreementsOf(id) {
      const d = docRef(data.documents, id);
      if (!d) return;
      Object.assign(st, docFocus(data, d.id, { pos: st.pos || "", typesOff: st.typesOff, online }));
      st.doc = d.id;
      sub.show("agreements");
      remember("coordination", argOf());
    }

    const refreshAll = () => { agr?.refresh(); docs?.refresh(); };
    sub = subtabs(root, [
      { id: "agreements", label: "LoA", fill: true, render: (pane) => (agr = mountAgreements(pane)) },
      { id: "docs", label: "DOCUMENTS", fill: true, render: (pane) => (docs = mountDocuments(pane)) },
    ], { arg: argOf });

    // dane raz na otwarcie zakładki (pliki zmieniają się z wersją PolIDS); błąd: ponowna próba przy następnym activate
    let loading = null;
    const load = () => (loading ||= api("/api/coordination").then((d) => {
      data = d;
      err = "";
      // wybór z HOME / OVERVIEW tego okna (pamięć okna jak tam, nie localStorage: drugie okno, tryb prywatny)
      if (st.pos === undefined) st.pos = defaultPosition(d.positions, choiceGet(POS_KEY));
      else if (st.pos && !d.positions.some((p) => p.callsign === st.pos)) st.pos = "";
      refreshAll();
      remember("coordination", argOf(), { replace: true });
    }).catch((e) => { err = `COORDINATION: ${e.message}`; loading = null; refreshAll(); }));
    // zalogowani (kolejność przejmowania): co minutę, gdy zakładka jest na ekranie
    const loadOnline = () => vatsimOnline().then((d) => {
      onInfo = d?.positions || {};
      online = new Set(Object.keys(onInfo));
      net = true;
    }).catch(() => { onInfo = {}; online = new Set(); net = false; }).then(() => agr?.refresh());
    setInterval(() => { if (root.classList.contains("active") && !document.hidden) loadOnline(); }, 60000);

    return {
      // arg undefined (przycisk menu): zostaje stan zakładki; inaczej podzakładka, stanowisko, filtr i dokument z adresu
      activate(arg) {
        if (arg !== undefined) {
          const a = parseArg(arg);
          const id = a.sub || "agreements";
          if (id === "agreements") {
            if (a.pos !== undefined) st.pos = data && a.pos && !data.positions.some((p) => p.callsign === a.pos) ? "" : a.pos;
            st.q = a.q || "";
            const s = stashed("coordination");   // ← / Wstecz: przewinięcie tabel z tego wpisu
            wantTop = Number.isFinite(s?.top) ? s.top : null;
          } else if (a.doc) {
            const d = data && docRef(data.documents, a.doc);
            if (d) st.doc = d.id;
            // przed danymi albo bez listy na ekranie: refresh() weźmie pierwszy dokument, a adres pójdzie za nim; nieznany id
            // przy otwartych DOKUMENTACH: zostaje pokazany dokument, a remember() niżej poprawia adres na niego (replaceState)
            else if (!data || !docs) st.doc = a.doc;
          }
          if (sub.current() !== id) sub.show(id);
          else if (id === "docs" && a.doc) docs?.pick(st.doc);
          else agr?.refresh();
        }
        load();
        loadOnline();
        remember("coordination", argOf());
      },
    };
  },
};
