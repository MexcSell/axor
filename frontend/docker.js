/* Docker view: this server's containers and images (admins only; the server and its Docker proxy enforce every rule). */
const Docker = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  let data = null, stats = {}, wired = false, timer, logsFor = null;

  const bytes = n => !n ? "0 B" : n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : n < 1073741824 ? `${fmtNum(n / 1048576, 1)} MB` : `${fmtNum(n / 1073741824, 2)} GB`;
  const STATE = { running: ["Running", "clear", "play"], restarting: ["Restarting", "caution", "reset"], paused: ["Paused", "caution", "clock"],
    created: ["Created", "new", "plus"], exited: ["Stopped", "avoid", "stop"], dead: ["Dead", "scam", "ban"], removing: ["Removing", "caution", "trash"] };
  const ACTIONS = {
    start: { label: "Start", icon: "play" },
    stop: { label: "Stop", icon: "stop", confirm: "Its processes get 10 seconds to exit, then they're killed. Anything that depends on it stops working.", danger: true },
    restart: { label: "Restart", icon: "reset" },
    remove: { label: "Remove", icon: "trash", confirm: "The container and its writable layer are deleted. Named volumes and the image stay. This can't be undone.", danger: true },
  };
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const age = ts => { const d = (Date.now() / 1000 - ts) / 86400; return d < 1 ? ago(ts) : d < 60 ? `${Math.floor(d)}d ago` : d < 730 ? `${Math.floor(d / 30)}mo ago` : `${Math.floor(d / 365)}y ago`; };

  async function open() {
    wire();
    if (!data) { $("#dk-stats").innerHTML = Loading.tiles(4); $("#dk-containers").innerHTML = Loading.rows(8, 6); $("#dk-images").innerHTML = Loading.rows(6, 5); }
    try { data = await api("/api/docker"); }
    catch (e) {
      data = null; $("#dk-stats").innerHTML = "";
      $("#dk-containers").innerHTML = `<tr><td colspan="8"><div class="empty">${esc(e.message)}</div></td></tr>`; $("#dk-images").innerHTML = "";
      return;
    }
    render(); loadStats();
    clearInterval(timer);
    timer = setInterval(() => { if ($("#view-docker").hidden) return clearInterval(timer); loadStats(); }, 15000);
  }

  async function loadStats() {
    stats = await api("/api/docker/stats").catch(() => stats);
    if (data) { renderContainers(); renderTiles(); }
  }

  function render() { renderTiles(); renderContainers(); renderImages(); }

  function renderTiles() {
    const e = data.engine, cs = data.containers, run = cs.filter(c => c.state === "running").length;
    const cpu = Object.values(stats).reduce((a, s) => a + (s?.cpu || 0), 0), mem = Object.values(stats).reduce((a, s) => a + (s?.mem || 0), 0);
    const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
    $("#dk-stats").innerHTML = [
      tile("server", "Engine", esc(e.version || "?"), esc(e.os || "")),
      tile("play", "Containers", `${run}/${cs.length}`, `${cs.length - run} not running`),
      tile("chip", "CPU", `${fmtNum(cpu, 1)}%`, `of ${e.cpus || "?"} cores × 100%`),
      tile("chips", "Memory", bytes(mem), `of ${bytes(e.memory)} · ${data.images.length} images`),
    ].join("");
  }

  function renderContainers() {
    if (!data) return;  // a search typed while the first load is still running
    const q = $("#dk-q").value.trim().toLowerCase(), f = $("#dk-filter").value;
    const rows = data.containers.filter(c =>
      (!q || [c.name, c.image, c.project, c.id].some(x => x.toLowerCase().includes(q))) &&
      (!f || (f === "running") === (c.state === "running")));
    $("#dk-count").textContent = `${rows.length} of ${data.containers.length}`;
    $("#dk-containers").innerHTML = rows.map(c => {
      const [label, lvl, ic] = STATE[c.state] || [c.state, "new", "info"], s = stats[c.id], on = c.state === "running";
      const acts = c.self ? [] : [on ? (!c.protected && "stop") : "start", on && "restart", !on && !c.protected && "remove"].filter(Boolean);
      return `<tr data-cid="${c.id}">
        <td><b>${esc(c.name)}</b>${c.self ? ' <span class="badge new">AXoR</span>' : c.protected ? ` <span class="tag" title="AXoR needs it: restart only">${icon("lock")}AXoR</span>` : ""}
          <small class="faint num">${esc(c.id)}${c.project ? ` · ${esc(c.project)}` : ""}</small></td>
        <td><span class="badge ${lvl}">${icon(ic)}${esc(label)}</span><small class="faint">${esc(c.status)}</small></td>
        <td class="dk-img" title="${esc(c.image)}">${esc(c.image)}</td>
        <td>${c.ports.map(p => `<span class="tag num">${esc(p)}</span>`).join(" ") || '<span class="faint">–</span>'}</td>
        <td class="r num">${on ? (s ? `${fmtNum(s.cpu, 1)}%` : '<span class="faint">…</span>') : ""}</td>
        <td class="r num">${on ? (s ? bytes(s.mem) : '<span class="faint">…</span>') : ""}</td>
        <td class="num" title="${new Date(c.created * 1000).toLocaleString()}">${age(c.created)}</td>
        <td class="r dk-acts"><button class="iconbtn" data-logs="${c.id}" title="Logs" aria-label="Logs of ${esc(c.name)}">${icon("terminal")}</button>${
          acts.map(a => `<button class="iconbtn ${ACTIONS[a].danger ? "danger" : ""}" data-act="${a}" title="${ACTIONS[a].label}" aria-label="${ACTIONS[a].label} ${esc(c.name)}">${icon(ACTIONS[a].icon)}</button>`).join("")}</td></tr>`;
    }).join("") || `<tr><td colspan="8"><div class="empty">No containers match.</div></td></tr>`;
  }

  function renderImages() {
    if (!data) return;  // a search typed while the first load is still running
    const q = $("#dk-iq").value.trim().toLowerCase();
    const rows = data.images.filter(i => !q || i.short.includes(q) || i.tags.some(t => t.toLowerCase().includes(q)))
      .sort((a, b) => b.created - a.created);
    $("#dk-icount").textContent = `${rows.length} of ${data.images.length} · ${bytes(data.images.reduce((a, i) => a + i.size, 0))}`;
    $("#dk-images").innerHTML = rows.map(i => `<tr>
        <td>${i.tags.map(t => `<b class="dk-tag">${esc(t)}</b>`).join("") || '<span class="faint">&lt;untagged&gt;</span>'}</td>
        <td class="num faint">${esc(i.short)}</td>
        <td class="r num">${bytes(i.size)}</td>
        <td class="num" title="${new Date(i.created * 1000).toLocaleString()}">${age(i.created)}</td>
        <td class="r num">${i.containers || '<span class="faint">0</span>'}</td>
        <td class="r">${i.containers ? "" : `<button class="iconbtn danger" data-rmi="${esc(i.tags[0] || i.id)}" title="Remove image" aria-label="Remove image">${icon("trash")}</button>`}</td></tr>`
    ).join("") || `<tr><td colspan="6"><div class="empty">No images match.</div></td></tr>`;
  }

  async function act(c, a) {
    const A = ACTIONS[a];
    const go = async () => {
      if (a === "restart" && c.protected) Auth.toast(`Restarting ${c.name}…`);
      await withSudo(() => api(`/api/docker/containers/${c.id}`, { method: "POST", body: { action: a } }));
      Auth.toast(`${A.label}: ${c.name}`);
      await open();
    };
    if (!A.confirm) return go().catch(err);
    Auth.modal(`<h3>${icon(A.icon)}${A.label} container?</h3><p><b>${esc(c.name)}</b> <span class="faint">${esc(c.image)}</span></p><p class="muted">${A.confirm}</p>`,
      async () => { $("#modal").close(); await go().catch(err); }, { submit: A.label, danger: A.danger });
  }

  function removeImage(ref) {
    Auth.modal(`<h3>${icon("trash")}Remove image?</h3><p><b>${esc(ref)}</b></p><p class="muted">Its tag is removed, and its layers too unless another image shares them. You can pull it again later.</p>`,
      async () => {
        $("#modal").close();
        try {
          const r = await withSudo(() => api(`/api/docker/images/${ref.split("/").map(encodeURIComponent).join("/")}`, { method: "DELETE" }));
          Auth.toast(`Removed ${ref} (${r.deleted} layer${r.deleted === 1 ? "" : "s"} deleted)`); open();
        } catch (e) { err(e); }
      }, { submit: "Remove", danger: true });
  }

  function pull() {
    const f = Auth.modal(`<h3>${icon("download")}Pull image</h3><p class="muted">From Docker Hub or any registry the server can reach. Private registries need <code>docker login</code> on the server.</p>
      <label class="in"><span>Image</span><input name="image" placeholder="redis:7 or ghcr.io/org/app:1.2" autocapitalize="none" spellcheck="false" maxlength="255" required></label>`,
      async f => {
        const image = f.elements.image.value.trim(); if (!image) throw new Error("Enter an image name.");
        const btn = $("button[type=submit]", f); btn.textContent = "Pulling…";
        try {
          const r = await withSudo(() => api("/api/docker/images/pull", { method: "POST", body: { image } }));
          $("#modal").close(); Auth.toast(`${r.image}: ${r.status || "pulled"}`); open();
        } finally { btn.textContent = "Pull"; }
      }, { submit: "Pull" });
    setTimeout(() => f.elements.image.focus(), 30);
  }

  function prune() {
    Auth.modal(`<h3>${icon("trash")}Prune images</h3><p class="muted">Removes <b>dangling</b> images: untagged layers left behind by rebuilds and pulls.</p>
      <label class="chk"><input type="checkbox" name="all"> Also remove every tagged image that no container uses</label>`,
      async f => {
        const all = f.elements.all.checked;
        const r = await withSudo(() => api("/api/docker/images/prune", { method: "POST", body: { all } }));
        $("#modal").close(); Auth.toast(`Pruned ${r.deleted} image${r.deleted === 1 ? "" : "s"}, ${bytes(r.reclaimed)} freed`); open();
      }, { submit: "Prune", danger: true });
  }

  async function logs(c, tail = 300) {
    logsFor = c;
    const d = $("#modal");
    if (!d.open || !d.classList.contains("dk-wide")) {
      Auth.modal(`<h3>${icon("terminal")}Logs <span class="faint">${esc(c.name)}</span></h3>
        <div class="toolbar"><select name="tail" aria-label="Lines"><option>100</option><option selected>300</option><option>1000</option><option>5000</option></select>
          <button type="button" class="btn" data-reload>${icon("reset")}Refresh</button>
          <button type="button" class="btn" data-copy>${icon("copy")}Copy</button></div>
        <pre class="dk-logs" tabindex="0">${Loading.line("Reading logs…")}</pre>`,
        async () => d.close(), { submit: "Close" });
      d.classList.add("dk-wide");
      d.addEventListener("close", () => d.classList.remove("dk-wide"), { once: true });
      const f = $("form", d);
      f.elements.tail.onchange = () => logs(logsFor, +f.elements.tail.value);
      $("[data-reload]", d).onclick = () => logs(logsFor, +f.elements.tail.value);
      $("[data-copy]", d).onclick = () => { navigator.clipboard?.writeText($(".dk-logs", d).textContent); Auth.toast("Copied"); };
    }
    const pre = $(".dk-logs", d);
    try {
      const r = await api(`/api/docker/containers/${c.id}/logs?tail=${tail}`);
      if (logsFor !== c) return;
      pre.textContent = r.text || "No output yet.";
      pre.scrollTop = pre.scrollHeight;
    } catch (e) { pre.textContent = e.message; }
  }

  const withSudo = fn => Admin.withSudo(fn);

  function wire() {
    if (wired) return; wired = true;
    hydrateIcons($("#view-docker"));
    $("#dk-q").oninput = renderContainers; $("#dk-filter").onchange = renderContainers;
    $("#dk-iq").oninput = renderImages;
    $("#dk-refresh").onclick = open;
    $("#dk-pull").onclick = pull; $("#dk-prune").onclick = prune;
    $("#dk-containers").onclick = e => {
      const b = e.target.closest("[data-act], [data-logs]"); if (!b) return;
      const c = data.containers.find(x => x.id === b.closest("tr").dataset.cid);
      if (b.dataset.logs) logs(c); else act(c, b.dataset.act);
    };
    $("#dk-images").onclick = e => { const b = e.target.closest("[data-rmi]"); if (b) removeImage(b.dataset.rmi); };
  }

  return { open };
})();
