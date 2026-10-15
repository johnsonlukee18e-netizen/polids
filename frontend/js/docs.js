import { api, esc, frameGo, h } from "./api.js";

// OTHER › DOCS: dokumenty PDF zgromadzone w folderze data/docs/ (podfolder = kategoria). Tylko podgląd.
// LOA i LOP (podfoldery data/docs/LOA i LOP) są od 0.12.3 w COORDINATION › DOKUMENTY, tu tylko pozostałe dokumenty.
// Wybrany dokument w adresie zapisuje OTHER (#other/docs/<plik w data/docs>, ← i Wstecz wracają do poprzedniego
// dokumentu): start = dokument z adresu ("" = pierwszy z listy), onPick(plik) po kliknięciu dokumentu na liście.
export const COORD_CATEGORIES = ["LOA", "LOP"];
export const otherDocs = (list) => list.filter((d) => !COORD_CATEGORIES.includes(String(d.category).toUpperCase()));
// plik z adresu OTHER › DOCS ("LOA/…pdf", "lop/…pdf") należy do COORDINATION: stare odnośniki tam przekierowujemy
export function isCoordFile(file) {
  const [cat, ...rest] = String(file ?? "").split("/");
  return rest.join("/") !== "" && COORD_CATEGORIES.includes(cat.toUpperCase());
}

export function mountDocs(pane, ctx, { start = "", onPick = () => {} } = {}) {
  const wrap = h(`<div class="mapwrap">
    <div class="mapside">
      <div class="ms-card"><h4>Dokumenty</h4><div class="list doc-list"></div></div>
      <p class="hint">Nowe PDF-y wrzuć do folderu <span class="mono">data/docs/</span>
      (podfolder = kategoria) i kliknij „Odśwież”.</p>
      <p class="hint">LOA i LOP: <a href="#coordination/docs">COORDINATION › DOKUMENTY</a>.</p>
      <button class="btn refresh">Odśwież</button>
    </div>
    <iframe class="embed viewer" style="background:#333"></iframe>
  </div>`);
  pane.append(wrap);
  const list = wrap.querySelector(".list");
  let viewer = wrap.querySelector(".viewer");
  const PREFIX = "/files/docs/";
  const argOf = (url) => (url.startsWith(PREFIX) ? url.slice(PREFIX.length) : url);
  let docs = [], want = start || null;   // want: dokument z adresu, zanim lista się wczyta
  const mark = () => list.querySelectorAll("a[data-url]").forEach((a) => a.classList.toggle("on", a.dataset.url === viewer.getAttribute("src")));
  const pick = (arg) => {        // "" albo plik spoza listy (np. wpisany ręcznie) = pierwszy dokument, nigdy pusty podgląd
    const d = docs.find((x) => argOf(x.url) === arg) || docs[0];
    if (viewer.getAttribute("src") !== d.url) viewer = frameGo(viewer, d.url);
    mark();
  };

  const load = async () => {
    docs = otherDocs(await api("/api/docs"));
    if (!docs.length) {
      list.innerHTML = `<p class="hint">Brak dokumentów w data/docs/.</p>`;
      return;
    }
    const groups = {};
    docs.forEach((d) => (groups[d.category] ||= []).push(d));
    list.innerHTML = Object.entries(groups).map(([cat, ds]) => `<div class="doc-cat">${esc(cat)}</div>` +
      ds.map((d) => `<a href="#" data-url="${esc(d.url)}">${esc(d.title)}</a>`).join("")).join("");
    if (want !== null) { pick(want); want = null; } else if (!viewer.getAttribute("src")) viewer.src = docs[0].url;
    mark();
  };
  list.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-url]");
    if (!a) return;
    e.preventDefault();
    viewer = frameGo(viewer, a.dataset.url);   // bez kroku w historii ramki: ← cofa wybór dokumentu
    list.querySelectorAll("a.on").forEach((x) => x.classList.remove("on"));
    a.classList.add("on");
    onPick(argOf(a.dataset.url));
  });
  // ponowny import tylko dla admina, reszta po prostu przeładowuje listę
  wrap.querySelector(".refresh").addEventListener("click", async () => {
    if (ctx.me?.admin) await api("/api/import", { method: "POST" }).catch(() => {});
    load();
  });
  load();
  // dokument z adresu (←, Wstecz); "" = pierwszy
  return { pick: (arg) => { if (docs.length) pick(arg); else want = arg; } };
}
