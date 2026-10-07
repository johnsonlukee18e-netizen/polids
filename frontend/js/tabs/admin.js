import { api, esc, h } from "../api.js";

const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const when = (iso) => (iso ? new Date(iso).toISOString().slice(0, 16).replace("T", " ") + "Z" : "–");

export default {
  mount(root, ctx) {
    const pane = h(`<div class="pane admin">
      <div class="card">
        <h3>Dostęp - CID z VATSIM</h3>
        <form class="toolbar add">
          <input class="cid" placeholder="CID" required pattern="[0-9]{6,8}" size="10" inputmode="numeric">
          <input class="note" placeholder="Opis (np. imię, stanowisko)" maxlength="120" size="36">
          <button class="btn primary" type="submit">Dodaj</button>
          <span class="hint msg"></span>
        </form>
        <p class="hint admins"></p>
        <table class="data users"><thead><tr><th>CID</th><th>Opis</th><th>Imię (VATSIM)</th><th>Dodany</th>
          <th>Ostatnie logowanie</th><th></th></tr></thead><tbody></tbody></table>
      </div>
      <div class="card">
        <h3>Odmowy dostępu</h3>
        <div class="toolbar"><span class="hint">Osoby, które próbowały się zalogować, a nie ma ich na liście.</span>
          <span style="flex:1"></span><button class="btn clear" type="button">Wyczyść</button></div>
        <table class="data denied"><thead><tr><th>CID</th><th>Imię</th><th>Rating</th><th>Prób</th><th>Ostatnia</th><th></th>
          </tr></thead><tbody></tbody></table>
      </div>
    </div>`);
    root.append(pane);
    const $ = (s) => pane.querySelector(s);
    const msg = (text, bad = false) => { $(".msg").textContent = text; $(".msg").classList.toggle("error", bad); };

    const load = async () => {
      try {
        const [data, denied] = await Promise.all([api("/api/admin/users"), api("/api/admin/denied")]);
        $(".admins").textContent = data.admins.length
          ? `Administratorzy (z konfiguracji, zawsze mają dostęp): ${data.admins.join(", ")}`
          : "Brak administratorów w POLIDS_AUTH_ADMIN_CIDS.";
        $(".users tbody").innerHTML = data.users.length ? data.users.map((u) => `<tr data-cid="${esc(u.cid)}">
          <td class="mono">${esc(u.cid)}</td>
          <td><input class="field note-edit" value="${esc(u.note || "")}" maxlength="120" placeholder="-"></td>
          <td>${esc(u.name || "–")}</td><td class="mono">${when(u.added_at)}${u.added_by ? ` <span class="hint">(${esc(u.added_by)})</span>` : ""}</td>
          <td class="mono">${when(u.last_login)}</td>
          <td class="actions"><button class="btn danger del" type="button">Usuń</button></td></tr>`).join("")
          : `<tr><td colspan="6" class="hint">Lista jest pusta - zalogować mogą się tylko administratorzy.</td></tr>`;
        $(".denied tbody").innerHTML = denied.length ? denied.map((d) => `<tr data-cid="${esc(d.cid)}" data-name="${esc(d.name || "")}">
          <td class="mono">${esc(d.cid)}</td><td>${esc(d.name || "–")}</td><td>${esc(d.rating || "–")}</td>
          <td class="num">${d.count}</td><td class="mono">${when(d.last)}</td>
          <td class="actions"><button class="btn allow" type="button">Dodaj</button></td></tr>`).join("")
          : `<tr><td colspan="6" class="hint">Brak.</td></tr>`;
      } catch (e) {
        $(".users tbody").innerHTML = `<tr><td colspan="6" class="error">${esc(e.message)}</td></tr>`;
      }
    };

    const add = async (cid, note) => {
      try {
        await api("/api/admin/users", json("POST", { cid, note }));
        msg(`Dodano ${cid}`);
        await load();
        return true;
      } catch (e) {
        msg(e.message, true);
        return false;
      }
    };

    $(".add").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (await add($(".cid").value.trim(), $(".note").value.trim())) {
        $(".cid").value = "";
        $(".note").value = "";
        $(".cid").focus();
      }
    });

    pane.addEventListener("click", async (e) => {
      const row = e.target.closest("tr[data-cid]");
      if (!row) return;
      const cid = row.dataset.cid;
      if (e.target.closest(".del")) {
        if (!confirm(`Usunąć CID ${cid} z listy? Straci dostęp od razu.`)) return;
        try {
          await api(`/api/admin/users/${cid}`, { method: "DELETE" });
          msg(`Usunięto ${cid}`);
        } catch (err) {
          msg(err.message, true);
        }
        load();
      } else if (e.target.closest(".allow")) {
        add(cid, row.dataset.name);
      }
    });

    pane.addEventListener("change", async (e) => {
      const input = e.target.closest(".note-edit");
      if (!input) return;
      const cid = input.closest("tr").dataset.cid;
      try {
        await api(`/api/admin/users/${cid}`, json("PATCH", { note: input.value.trim() }));
        msg(`Zapisano opis ${cid}`);
      } catch (err) {
        msg(err.message, true);
      }
    });

    $(".clear").addEventListener("click", async () => {
      await api("/api/admin/denied", { method: "DELETE" });
      load();
    });

    return { activate: load };
  },
};
