/* My Knowledge · linked folders (knowledge_linked.py; knowledge.js draws this card in Settings & connectors; prefix kbl-).
   Folders on this server, read through AXoR Host files and kept in sync: type the folder's path or browse to it (anywhere
   inside the server folders Host files mounts; the server finds which one), who reads
   its files (default: your agents and teams), what to leave out; each link shows its last sync, what was added, changed,
   removed and skipped, and opens as a Workspace folder. Administrators only (it reads the server's disk). */
const KnowledgeLinked = (() => {
  const K = "/api/knowledge/linked";
  const REACH = { teams: "Your agents and teams", agents: "You and your agents", page: "Only you" };
  const S = { d: null, loading: false, failed: "", adding: false, edit: null, pick: { host: "", dir: null, err: "" }, render: null, timer: null };
  const h = () => Knowledge.h;
  const num = v => (v || 0).toLocaleString();
  const inPage = el => el.closest("#knowledge, #myknowledge");

  async function load(quiet) {
    if (S.loading) return;
    S.loading = true;
    try { S.d = await api(K); S.failed = ""; } catch (e) { S.failed = e.message; }
    S.loading = false;
    if (!quiet || S.d) S.render?.();
    poll();
  }
  function poll() {  // while something syncs, look again every few seconds
    clearTimeout(S.timer);
    if ((S.d?.links || []).some(l => l.status === "syncing")) S.timer = setTimeout(() => { if (document.querySelector("[data-kbl-card]")) load(true); }, 3000);
  }
  function after(render) { S.render = render; if (!S.d && !S.loading && !S.failed) load(); }

  const hosts = () => (S.d?.roots || []).filter(r => r.mounted !== false && r.host).map(r => r.host.replace(/\/+$/, "") || "/").sort((a, b) => a.length - b.length);
  const inside = p => hosts().some(h => p === h || p.startsWith(h.replace(/\/$/, "") + "/"));
  const leaf = p => String(p || "").split("/").filter(Boolean).pop() || "";
  async function browse(host) {
    const want = String(host || "").trim();
    S.pick = { host: want, dir: null, err: "" }; S.render?.();
    try { const d = await api(`${K}/dir?host=${encodeURIComponent(want)}`); S.pick.dir = d; S.pick.host = d.host || want; } catch (e) { S.pick.err = e.message; }
    S.render?.();
    const box = document.querySelector("[data-kbl-path]"); if (box && document.activeElement !== box) box.value = S.pick.host;
  }

  // ---------- drawing ----------
  const skippedLine = st => {
    const s = st.skipped || {}, parts = [[s.media, "pictures/audio/video"], [s.binary, "binary"], [s.large, "too large"], [s.notext, "no text"], [s.unreadable, "not readable"],
      [s.excluded, "excluded"], [s.denied, "secrets/.git/venvs never shared"], [s.links, "links"]].filter(([n]) => n);
    return parts.length ? `Skipped: ${parts.map(([n, l]) => `${num(n)} ${l}`).join(" · ")}` : "";
  };
  function row(l) {
    const st = l.stats || {}, H = h();
    const status = l.status === "syncing" ? H.chip("run", "Syncing…") : l.status === "error" ? H.chip("bad", "Failed") : l.last_sync ? H.chip("ok", "In sync") : H.chip("none", "Not synced yet");
    return `<li class="kbl-row"><div class="kbl-head"><b>${icon("folder")}${esc(l.name)}</b>${status}</div>
      <span class="kb-faint kbl-host"><code>${esc(l.host)}</code> → ${esc(l.dest.slice(1))}</span>
      <span class="kb-faint">${H.plural(l.files, "file")} · ${l.last_sync ? `synced ${H.when(l.last_sync)}` : "not synced yet"}${l.auto ? ` · every ${S.d.every} min` : ""}${st.ms !== undefined ? ` · last sync: ${[[st.added, "added"], [st.changed, "changed"], [st.removed, "removed"], [st.errors, "unreadable"]].filter(([n]) => n).map(([n, w]) => `${num(n)} ${w}`).join(", ") || "no changes"}` : ""}${st.truncated ? ` · <span class="kb-warn">over ${num(S.d.max_files)} files: the rest aren't read</span>` : ""}</span>
      ${skippedLine(st) ? `<span class="kb-faint">${esc(skippedLine(st))}${st.redacted ? ` · ${num(st.redacted)} secrets taken out` : ""}</span>` : ""}
      ${l.error ? `<span class="kb-warn kb-note">${esc(l.error)}</span>` : ""}
      <span class="kb-row kbl-acts"><label class="kbl-reach"><span class="kb-faint">Who reads its files</span><select data-kbl-reach="${l.id}" aria-label="Who reads ${esc(l.name)}">${Object.entries(REACH).map(([v, t]) => `<option value="${v}" ${l.reach === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        <button type="button" class="btn sm" data-kbl-sync="${l.id}" ${l.status === "syncing" ? "disabled" : ""}>${icon("cycle")}Sync now</button>
        <button type="button" class="btn sm" data-kb-folder="${esc(l.dest)}">${icon("folder")}Open</button>
        <button type="button" class="btn sm" data-kbl-edit="${l.id}">${icon("edit")}Edit</button>
        <button type="button" class="btn sm danger" data-kbl-rm="${l.id}">${icon("trash")}Unlink</button></span>
      ${S.edit === l.id ? editForm(l) : ""}</li>`;
  }
  const excl = xs => `<label><span>Leave out (one pattern a line: a name like <code>*.log</code> or a path like <code>runs/old</code>)</span><textarea name="exclude" rows="4" maxlength="4000">${esc((xs || []).join("\n"))}</textarea></label>`;
  const editForm = l => `<form class="kb-form kb-card kb-inset" data-kbl-form="edit" data-id="${l.id}">
      <label><span>Name</span><input name="name" maxlength="60" value="${esc(l.name)}"></label>${excl(l.exclude)}
      <label class="kb-check"><input type="checkbox" name="auto" ${l.auto ? "checked" : ""}> Sync automatically every ${S.d.every} minutes</label>
      <div class="kb-row end"><button class="btn primary">${icon("check")}Save</button></div></form>`;
  function picker() {
    const p = S.pick, d = p.dir, segs = p.host.split("/").filter(Boolean);
    const crumbs = segs.map((x, i) => { const to = "/" + segs.slice(0, i + 1).join("/");
      return inside(to) ? `<button type="button" class="linkbtn" data-kbl-go="${esc(to)}">${esc(x)}</button>` : `<span class="kb-faint">${esc(x)}</span>`; }).join(`<span class="kb-faint">/</span>`);
    const list = p.err ? `<p class="kb-warn kb-note">${esc(p.err)}</p>` : !d ? `<p class="kb-faint">Reading the folder…</p>`
      : `<ul class="kbl-dirs">${d.dirs.map(x => `<li><button type="button" ${x.denied || !x.readable ? "disabled" : ""} data-kbl-go="${esc(p.host.replace(/\/$/, "") + "/" + x.name)}" title="${x.denied ? "Never shared (secrets, .git, virtual environments, caches)" : !x.readable ? "Not readable" : "Open"}">${icon(x.denied ? "lock" : "folder")}<span>${esc(x.name)}</span></button></li>`).join("") || `<li class="kb-faint">No subfolders</li>`}</ul>
        ${(fs => `<p class="kb-faint kb-note">${h().plural(fs.length, "file")} AXoR can read directly in this folder${fs.length ? `: ${fs.slice(0, 6).map(f => esc(f.name)).join(", ")}${fs.length > 6 ? "…" : ""}` : ""}.</p>`)(d.files.filter(f => f.readable && !f.denied))}`;  // private and never-shared files aren't even named
    return `<div class="kbl-pick"><div class="kbl-crumbs"><span class="kb-faint">/</span>${crumbs}</div>${list}</div>`;
  }
  function addForm() {
    const roots = S.d.roots || [];
    if (!roots.length) return `<p class="kb-warn kb-note">Host files runs but has no folders mounted (k8s/host/42-hostfiles.yaml).</p>`;
    const name = leaf(S.pick.host);
    return `<form class="kb-form kb-card kb-inset" data-kbl-form="add">
      <div class="kb-row kbl-pathrow"><label class="kb-grow"><span>Folder on the server</span><input name="path" data-kbl-path value="${esc(S.pick.host)}" spellcheck="false" autocomplete="off" placeholder="/home/thomas/projects" aria-describedby="kbl-pickhelp"></label>
        <button type="button" class="btn sm" data-kbl="go">${icon("right")}Go</button></div>
      <div class="kbl-roots"><span class="kb-faint">Start from</span>${hosts().map(h => `<button type="button" class="btn sm ${S.pick.host === h ? "primary" : ""}" data-kbl-go="${esc(h)}">${icon("folder")}${esc(h)}</button>`).join("")}</div>
      <p class="kb-note" id="kbl-pickhelp">Type a path (Enter) or browse to the folder, then link it: anywhere under ${hosts().map(h => `<code>${esc(h)}</code>`).join(", ")}. Link your own work folders one by one rather than a whole home folder. Private files, logins and wallets are never read.</p>
      ${picker()}
      <div class="kb-row"><label class="kb-grow"><span>Name (optional)</span><input name="name" maxlength="60" placeholder="${esc(name)}"></label>
        <label><span>Who reads its files</span><select name="reach">${Object.entries(REACH).map(([v, t]) => `<option value="${v}" ${v === "teams" ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
      ${excl(S.d.default_exclude)}
      <label class="kb-check"><input type="checkbox" name="auto" checked> Sync automatically every ${S.d.every} minutes</label>
      <div class="kb-row end"><span class="kb-note">${icon("lock")}Read only: nothing on the server changes. <code>*-data</code> keeps out other miners' agents copied in ridges-intel.</span><button class="btn primary" ${S.pick.dir ? "" : "disabled"}>${icon("plus")}Link ${name ? `“${esc(name)}”` : "this folder"}</button></div></form>`;
  }
  function card() {
    const H = h(), d = S.d;
    const body = S.failed ? `<p class="kb-warn kb-note">${esc(S.failed)} <button type="button" class="linkbtn" data-kbl="reload">Try again</button></p>`
      : !d ? `<p class="kb-faint">Loading…</p>`
      : !d.admin ? `<p class="kb-note">${icon("lock")}Only administrators link folders on the server, since it reads the server's disk.</p>`
      : !d.connected ? `<p class="kb-note kb-warn">AXoR Host files isn't connected on this server yet: it arrives with the next redeploy (k8s/host/42-hostfiles.yaml).</p>`
      : `${d.error ? `<p class="kb-warn kb-note">${esc(d.error)}</p>` : ""}${S.adding ? addForm() : ""}
        ${d.links.length ? `<ul class="kb-conn kbl-list">${d.links.map(row).join("")}</ul>` : S.adding ? "" : H.empty("No folders linked yet. Link one and its files become My Knowledge sources your agents can search.")}
        <p class="kb-note">Text, code and documents (Word, PDF, Excel…) are read; pictures, audio, video and binaries are skipped, and so are .env files, keys, .git and virtual environments. Secrets are taken out. A changed file becomes a new version; a deleted one leaves My Knowledge. Agents search these files (a few best passages a search): they don't read a whole folder at once.</p>`;
    const add = d?.admin && d.connected && !S.adding ? `<button type="button" class="btn sm" data-kbl="add">${icon("plus")}Link a folder</button>` : S.adding ? `<button type="button" class="btn sm" data-kbl="cancel">Cancel</button>` : "";
    return `<div data-kbl-card>${H.card("folder", "Linked folders", add, body)}</div>`;
  }

  // ---------- acting ----------
  document.addEventListener("click", async e => {
    const b = e.target.closest("[data-kbl],[data-kbl-sync],[data-kbl-edit],[data-kbl-rm],[data-kbl-go]");
    if (!b || !inPage(b)) return;
    const ds = b.dataset;
    if (ds.kbl === "reload") { S.failed = ""; S.d = null; return load(); }
    if (ds.kbl === "add") { S.adding = true; S.edit = null; browse(S.pick.host || hosts()[0] || ""); return; }
    if (ds.kbl === "go") { const box = document.querySelector("[data-kbl-path]"); return browse(box?.value || S.pick.host); }
    if (ds.kbl === "cancel") { S.adding = false; return S.render?.(); }
    if (ds.kblGo !== undefined) return browse(ds.kblGo);
    if (ds.kblEdit) { S.edit = S.edit === +ds.kblEdit ? null : +ds.kblEdit; return S.render?.(); }
    if (ds.kblSync) { const r = await h().busy(b, () => api(`${K}/${ds.kblSync}/sync`, { method: "POST" })); if (r) { toast("Syncing in the background", { kind: "success" }); load(); } return; }
    if (ds.kblRm) {
      const l = S.d.links.find(x => x.id === +ds.kblRm); if (!l) return;
      const ok = await UI.confirm({ title: `Unlink “${l.name}”?`, body: `Its ${h().plural(l.files, "file")} leave My Knowledge and agents stop finding them. The folder on the server isn't touched.`, ok: "Unlink", icon: "trash" });
      if (ok && await h().busy(b, () => api(`${K}/${l.id}`, { method: "DELETE" }))) { toast("Unlinked", { kind: "success" }); load(); }
    }
  });
  document.addEventListener("change", async e => {
    const t = e.target; if (!inPage(t)) return;
    if (t.matches("[data-kbl-reach]")) {
      const r = await h().busy(null, () => api(`${K}/${t.dataset.kblReach}`, { method: "PATCH", body: { reach: t.value } }));
      if (r) { toast(`Its files: ${REACH[r.reach].toLowerCase()}`, { kind: "success" }); load(); }
    }
  });
  document.addEventListener("submit", async e => {
    const fm = e.target.closest("form[data-kbl-form]"); if (!fm || !inPage(fm)) return;
    e.preventDefault();
    const F = new FormData(fm), btn = fm.querySelector("button.primary");
    const exclude = String(F.get("exclude") || "").split("\n").map(x => x.trim()).filter(Boolean);
    if (fm.dataset.kblForm === "add") {
      const r = await h().busy(btn, () => api(K, { method: "POST", body: { path: S.pick.host, name: F.get("name") || "", reach: F.get("reach"), exclude, auto: !!F.get("auto") } }));
      if (r) { S.adding = false; S.pick = { host: "", dir: null, err: "" }; toast(`Linked “${r.name}”: reading its files`, { kind: "success" }); load(); }
      return;
    }
    const r = await h().busy(btn, () => api(`${K}/${fm.dataset.id}`, { method: "PATCH", body: { name: F.get("name") || "", exclude, auto: !!F.get("auto") } }));
    if (r) { S.edit = null; toast("Saved", { kind: "success" }); load(); }
  });

  document.addEventListener("keydown", e => {  // Enter in the path box browses there instead of linking
    const t = e.target;
    if (e.key === "Enter" && t.matches?.("[data-kbl-path]") && inPage(t)) { e.preventDefault(); browse(t.value); }
  });

  return { card, after };
})();
