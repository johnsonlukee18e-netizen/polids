import { api, esc, h } from "../api.js";

// Dokumenty PDF zgromadzone w folderze data/docs/ (podfolder = kategoria). Tylko podgląd.
export default {
  mount(root, ctx) {
    const wrap = h(`<div class="pane fill"><div class="mapwrap">
      <div class="mapside">
        <div class="ms-card"><h4>Dokumenty</h4><div class="list doc-list"></div></div>
        <p class="hint">Nowe PDF-y wrzuć do folderu <span class="mono">data/docs/</span>
        (podfolder = kategoria) i kliknij „Odśwież”.</p>
        <button class="btn refresh">Odśwież</button>
      </div>
      <iframe class="embed viewer" style="background:#333"></iframe>
    </div></div>`);
    root.append(wrap);
    const list = wrap.querySelector(".list");
    const viewer = wrap.querySelector(".viewer");

    const load = async () => {
      const docs = await api("/api/docs");
      if (!docs.length) {
        list.innerHTML = `<p class="hint">Brak dokumentów w data/docs/.</p>`;
        return;
      }
      const groups = {};
      docs.forEach((d) => (groups[d.category] ||= []).push(d));
      list.innerHTML = Object.entries(groups).map(([cat, ds]) => `<div class="doc-cat">${esc(cat)}</div>` +
        ds.map((d) => `<a href="#" data-url="${esc(d.url)}">${esc(d.title)}</a>`).join("")).join("");
      if (!viewer.getAttribute("src")) viewer.src = docs[0].url;
      list.querySelectorAll("a[data-url]").forEach((a) => a.classList.toggle("on", a.dataset.url === viewer.getAttribute("src")));
    };
    list.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-url]");
      if (!a) return;
      e.preventDefault();
      viewer.src = a.dataset.url;
      list.querySelectorAll("a.on").forEach((x) => x.classList.remove("on"));
      a.classList.add("on");
    });
    // ponowny import tylko dla admina, reszta po prostu przeładowuje listę
    wrap.querySelector(".refresh").addEventListener("click", async () => {
      if (ctx.me?.admin) await api("/api/import", { method: "POST" }).catch(() => {});
      load();
    });
    load();
  },
};
