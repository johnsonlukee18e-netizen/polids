import { api, debounce, esc, frameGo, h, lsGet, lsSet, remember, subtabs, vatsimOnline } from "../api.js";
import {
  POS_KEY, agreementsArg, blockHtml, defaultPosition, docCardHtml, docFilter, docRef, docsArg, notesHtml, ownedKeys,
  parseArg, positionOptions, shortCs, view,
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
    const argOf = (id = sub?.current()) => (id === "docs" ? docsArg(st.doc) : agreementsArg(st.pos, st.q));
    const freq = (cs) => onInfo[cs]?.frequency || data?.positions.find((p) => p.callsign === cs)?.frequency || "";

    // --- POROZUMIENIA
    function mountAgreements(pane) {
      const el = h(`<div class="cr-wrap">
        <div class="cr-main"><div class="cr-sum"></div><div class="cr-blocks"><p class="hint">Wczytywanie porozumień…</p></div>
          <details class="cr-notes"><summary>Zasady z LOA</summary><div class="cr-notes-b"></div></details></div>
        <div class="cr-side">
          <div class="ms-card"><h4>Punkty / filtr</h4>
            <input type="search" class="field cr-q" list="cr-cops" placeholder="np. ALUKA EPKS" autocomplete="off" spellcheck="false" aria-label="Punkty i filtr">
            <datalist id="cr-cops"></datalist>
            <p class="hint">Słowa oddzielone spacją muszą pasować wszystkie (COP, lotnisko, sektor, FIR, FL, warunki). Pełna nazwa COP – te wiersze na górze.</p></div>
          <div class="ms-card"><h4>Stanowisko</h4><select class="field cr-pos" aria-label="Stanowisko"><option value="">Wszystkie</option></select>
            <p class="hint cr-own"></p></div>
          <div class="ms-card"><h4>FIR</h4><div class="cr-tgs cr-firs"></div></div>
          <div class="ms-card"><h4>Rodzaj</h4><div class="cr-tgs cr-types"></div></div>
        </div></div>`);
      pane.append(el);
      const $ = (s) => el.querySelector(s);
      const q = $(".cr-q"), pos = $(".cr-pos"), notes = $(".cr-notes");
      notes.open = lsGet(NOTES_KEY) === "1";
      notes.addEventListener("toggle", () => lsSet(NOTES_KEY, notes.open ? "1" : "0"));

      const refresh = () => {
        q.value = st.q;
        if (!data) {
          $(".cr-blocks").innerHTML = err ? `<p class="error">${esc(err)}</p>` : `<p class="hint">Wczytywanie porozumień…</p>`;
          return;
        }
        $("#cr-cops").innerHTML = data.cops.map((c) => `<option value="${esc(c)}"></option>`).join("");
        pos.innerHTML = positionOptions(data.positions, st.pos);
        const counts = {};
        data.agreements.forEach((r) => { counts[r.fir] = (counts[r.fir] || 0) + 1; counts[r.type] = (counts[r.type] || 0) + 1; });
        $(".cr-firs").innerHTML = data.firs.map((f) => `<button type="button" class="gbtn cr-tg${st.off.has(f) ? "" : " on"}" data-fir="${esc(f)}"`
          + ` title="${esc(data.notes[f]?.title || f)}">${esc(f)} <small>${counts[f] || 0}</small></button>`).join("")
          + `<button type="button" class="btn cr-all" title="Włącz wszystkie FIR-y">wszystkie</button>`;
        $(".cr-types").innerHTML = ["LOA", "LOP"].map((t) => `<button type="button" class="gbtn cr-tg${st.typesOff.has(t) ? "" : " on"}" data-kind="${t}">`
          + `${t} <small>${counts[t] || 0}</small></button>`).join("");
        const v = view(data, { pos: st.pos || "", q: st.q, off: st.off, typesOff: st.typesOff, online });
        const x = { online, pos: st.pos || "", toks: v.toks, freq };
        $(".cr-blocks").innerHTML = blockHtml("out", v.out, data, x) + blockHtml("in", v.in, data, x);
        $(".cr-sum").innerHTML = `<b>${v.shown}</b> z ${v.total} przekazań`
          + (st.pos ? ` · stanowisko <b>${esc(st.pos)}</b>` : " · wszystkie stanowiska")
          + (v.toks.length ? ` · filtr <b>${esc(v.toks.join(" "))}</b>` : "")
          + `<span class="hint"> · wyciąg z PDF (data/seed/loa.json), w razie wątpliwości obowiązuje PDF</span>`;
        // kto obsługuje: sektory wybranego stanowiska przy obecnych zalogowanych
        const own = $(".cr-own");
        if (st.pos) {
          const keys = ownedKeys(data.chains, st.pos, online);
          const ons = data.positions.filter((p) => online.has(p.callsign) && p.callsign !== st.pos).map((p) => shortCs(p.callsign));
          own.innerHTML = (keys.length ? `Obsługuje: <b>${esc(keys.join(", "))}</b>.` : "Teraz nie obsługuje żadnego sektora z LOA (przejmuje ktoś wyżej w kolejności).")
            + (net === false ? " Brak danych VATSIM: liczymy tak, jakby nikt nie był online."
              : net ? ` Online: ${ons.length ? esc(ons.join(", ")) : "nikt z tych stanowisk"}.` : "");
        } else own.textContent = "Wszystkie przekazania, bez podziału na sektory.";
        const firs = [...new Set([...v.out, ...v.in].map((r) => r.fir))];
        $(".cr-notes summary").textContent = `Zasady z LOA: przekazanie kontroli, VFR, inne${firs.length ? " – " + firs.join(", ") : ""}`;
        $(".cr-notes-b").innerHTML = notesHtml(data, firs) || `<p class="hint">Brak zasad dla wybranych FIR-ów.</p>`;
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
      return { refresh, destroy() { if (agr?.el === el) agr = null; }, el };
    }

    // --- DOKUMENTY
    function mountDocuments(pane) {
      const el = h(`<div class="mapwrap cd-wrap">
        <div class="mapside">
          <div class="ms-card"><h4>Dokumenty LOA i LOP</h4>
            <div class="ms-row"><select class="field cd-fir" aria-label="FIR"><option value="">Wszystkie FIR-y</option></select>
              <select class="field cd-type" aria-label="Rodzaj"><option value="">LOA i LOP</option><option>LOA</option><option>LOP</option></select></div>
            <div class="cd-list"><p class="hint">Wczytywanie…</p></div></div>
          <p class="hint">Nazwy, tagi i AIRAC: <span class="mono">data/seed/coordination.json</span>; PDF-y w
            <span class="mono">data/docs/LOA</span> i <span class="mono">data/docs/LOP</span>.</p>
        </div>
        <iframe class="embed viewer" style="background:#333" title="Dokument"></iframe>
      </div>`);
      pane.append(el);
      const list = el.querySelector(".cd-list"), fir = el.querySelector(".cd-fir"), type = el.querySelector(".cd-type");
      let viewer = el.querySelector(".viewer");
      const show = (d) => {
        if (!d) return;
        st.doc = d.id;
        const url = d.exists ? d.url : "";
        if (url && viewer.getAttribute("src") !== url) viewer = frameGo(viewer, url);
        list.querySelectorAll(".cd-card").forEach((c) => c.classList.toggle("on", c.dataset.doc === d.id));
        list.querySelector(".cd-card.on")?.scrollIntoView({ block: "nearest" });
      };
      const refresh = () => {
        if (!data) {
          list.innerHTML = err ? `<p class="error">${esc(err)}</p>` : `<p class="hint">Wczytywanie…</p>`;
          return;
        }
        const firs = [...new Set(data.documents.flatMap((d) => d.firs))].sort();
        fir.innerHTML = `<option value="">Wszystkie FIR-y</option>` + firs.map((f) => `<option${f === st.dfir ? " selected" : ""}>${esc(f)}</option>`).join("");
        type.value = st.dtype;
        const ds = docFilter(data.documents, { fir: st.dfir, type: st.dtype });
        const cur = docRef(data.documents, st.doc) || ds[0] || data.documents[0];
        list.innerHTML = ds.length ? ds.map((d) => docCardHtml(d, { selected: d.id === cur?.id, airac: data.current_airac })).join("")
          : `<p class="hint">Brak dokumentów dla tego filtra.</p>`;
        show(cur);
      };
      const pick = (id) => {
        const d = data && docRef(data.documents, id);
        if (!d) return false;
        show(d);
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
    function showAgreementsOf(id) {
      const d = docRef(data.documents, id);
      if (!d) return;
      const mine = new Set(data.agreements.filter((r) => r.doc === d.id).map((r) => r.fir));
      st.off = new Set(data.firs.filter((f) => !mine.has(f)));
      st.typesOff.delete(d.type);
      lsSet(OFF_KEY, JSON.stringify([...st.off]));
      lsSet(TYPES_KEY, JSON.stringify([...st.typesOff]));
      st.doc = d.id;
      sub.show("agreements");
      remember("coordination", argOf());
    }

    const refreshAll = () => { agr?.refresh(); docs?.refresh(); };
    sub = subtabs(root, [
      { id: "agreements", label: "POROZUMIENIA", fill: true, render: (pane) => (agr = mountAgreements(pane)) },
      { id: "docs", label: "DOKUMENTY", fill: true, render: (pane) => (docs = mountDocuments(pane)) },
    ], { arg: argOf });

    // dane raz na otwarcie zakładki (pliki zmieniają się z wersją PolIDS); błąd: ponowna próba przy następnym activate
    let loading = null;
    const load = () => (loading ||= api("/api/coordination").then((d) => {
      data = d;
      err = "";
      if (st.pos === undefined) st.pos = defaultPosition(d.positions, lsGet(POS_KEY));
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
          } else if (a.doc) st.doc = data ? docRef(data.documents, a.doc)?.id || a.doc : a.doc;
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
