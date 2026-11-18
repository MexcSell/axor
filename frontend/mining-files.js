/* The file manager (mining_files.py): a competition team's files beside My workspace's (AXoR Drive), copied either way.
   - It shows in Competition teams → More → Files & sandbox (the team's files come from MiningWork's view, kept fresh by its
     polling) and in My workspace → Files, under the drive's file list, with a picker of your teams (the open subnet's first).
   - Team side: folders from the paths, New file, New folder, upload (text files), open to edit, rename or move, delete, download.
   - My workspace side: My drive or the Shared drive, folder by folder (/api/drive/list), upload, new folder, preview, trash.
   - Copy: tick items and press Copy, or drag them onto the other side. Into the team: text files only, into its open folder,
     asking before replacing a file. Onto the drive: into its open folder (at a drive's top: Competition teams › <team>), a new
     version when the name is taken, tagged with the team's subnet so it shows with that subnet in My workspace.
   - GitHub (mining_source_files.py): when the Source hub has repositories, the head picks which two places sit side by side:
     Team ⇄ My workspace, Team ⇄ GitHub or GitHub ⇄ My workspace. The GitHub pane browses a repository at a branch (the Source
     hub's own routes); copying out of it keeps subfolders, copying into it is one commit on that branch, into its open folder,
     with a message you write (administrators only). Files that look like secrets never cross either way.
   Files open in a dialog outside the page, so the Competition teams page's polling re-renders leave an edit alone. */
const MiningFiles = (() => {
  const F = "/api/mining/files", W = "/api/mining/work";
  const fresh = () => ({ tpath: "", tsel: new Set(), vdirs: new Set(), dspace: store.get("mf.space", "mine"), dfolder: null, dsel: new Set(),
    drive: null, dErr: "", dAt: 0, dSeq: 0, note: null, busy: "",
    pair: null, grepo: null, gref: null, gpath: "", gsel: new Set(), git: null, branches: null, gErr: "", gAt: 0, gSeq: 0 });
  const st = {};  // per place, made on first use: app.js (store) loads after this file
  const S_ = k => st[k] || (st[k] = fresh());
  let wsTeams = null, wsTeam = null, wsAt = 0, wsWid = null, wsSub = null, wsLoading = false, dragging = null;
  let picks = null;  // the team last picked in My workspace, per subnet
  let src = null, srcAt = 0, srcLoading = false;  // the Source hub's repositories (GET /api/mining/files/source)
  const pickOf = n => (picks ??= store.get("mf.ws", {}) || {})[n ?? "all"] ?? null;
  const err = e => e && toast(e.message, { kind: "error" });
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const bytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${fmtNum(n / 1024, 0)} kB` : `${fmtNum(n / 1048576, 1)} MB`;
  const join = (a, b) => a ? `${a}/${b}` : b;
  const parent = p => p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "";
  const base = p => p.slice(p.lastIndexOf("/") + 1);
  const safe = n => (n || "").trim().replace(/[^A-Za-z0-9._@+-]/g, "-").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "file";
  const SPACE = { mine: ["My drive", "lock", "only you"], shared: ["Shared drive", "users", "everyone signed in"] };
  // the two places side by side (left, right): the team stays left and My workspace right, so today's layout is the first
  const PAIRS = { "team-drive": ["Team", "My workspace"], "team-source": ["Team", "GitHub"], "source-drive": ["GitHub", "My workspace"] };
  const PLACE = { team: "the team", drive: "My workspace", source: "GitHub" };
  const hasGit = () => !!(src?.configured && src.repos.length);
  function pair(key) {
    const s = S_(key);
    s.pair ??= store.get("mf.pair", "team-drive");
    return hasGit() && PAIRS[s.pair] ? s.pair : "team-drive";
  }
  const sides = key => pair(key).split("-");
  const other = (key, side) => { const [l, r] = sides(key); return side === l ? r : l; };

  // ---------- the team: Competition teams' open team, or the one picked in My workspace ----------
  function team(key) {
    if (key === "ws") return wsTeam && { wid: wsTeam.comp.id, label: wsTeam.comp.label, netuid: wsTeam.comp.netuid, files: wsTeam.files, limits: wsTeam.limits };
    const v = MiningWork.view(); if (!v) return null;
    const A = Object.fromEntries(v.agents.map(a => [a.id, a.name]));
    return { wid: v.comp.id, label: v.comp.label, netuid: v.campaign.netuid, files: v.files.map(f => ({ ...f, author: A[f.agent] })), limits: v.limits };
  }
  function rerender(key) {
    if (key === "teams") return MiningWork.rerender();
    const el = document.querySelector("[data-tfmhost]"); if (!el) return;
    el.innerHTML = html("ws");
    $$("time[data-ts]", el).forEach(t => { t.textContent = ago(+t.dataset.ts); });
  }
  // after the team's files changed: Competition teams reloads its view, My workspace its listing (or takes the one given)
  async function teamChanged(key, listing) {
    if (key === "teams") { await MiningWork.reload(); return rerender(key); }  // reload skips while a poll is in flight
    if (listing) wsTeam = listing; else if (wsTeam) wsTeam = await api(`${F}/teams/${wsTeam.comp.id}`).catch(e => (err(e), wsTeam));
    rerender(key);
  }
  function tree(files, path, vdirs) {
    const pre = path ? `${path}/` : "", dirs = new Map(), list = [];
    for (const f of files) {
      if (!f.path.startsWith(pre)) continue;
      const rest = f.path.slice(pre.length), i = rest.indexOf("/");
      if (i < 0) { list.push(f); continue; }
      const d = rest.slice(0, i), x = dirs.get(d) || { name: d, path: pre + d, n: 0, size: 0, updated: 0 };
      x.n++; x.size += f.size; x.updated = Math.max(x.updated, f.updated); dirs.set(d, x);
    }
    for (const p of vdirs) if (parent(p) === path && !dirs.has(base(p))) dirs.set(base(p), { name: base(p), path: p, n: 0, size: 0, updated: 0 });
    return { dirs: [...dirs.values()].sort((a, b) => a.name.localeCompare(b.name)), files: list.sort((a, b) => a.path.localeCompare(b.path)) };
  }

  // ---------- the drive ----------
  async function loadDrive(key, quiet = false) {
    const s = S_(key), seq = ++s.dSeq;
    s.dAt = Date.now();
    try {
      const q = new URLSearchParams({ space: s.dspace, ...(s.dfolder ? { folder: s.dfolder } : {}) });
      const r = await api(`/api/drive/list?${q}`);
      if (seq !== s.dSeq) return;
      s.drive = r; s.dErr = "";
      const ids = new Set(r.items.map(x => x.id)); s.dsel = new Set([...s.dsel].filter(i => ids.has(i)));
    } catch (e) {
      if (seq !== s.dSeq) return;
      if (s.dfolder && e.status === 404) { s.dfolder = null; return loadDrive(key, quiet); }  // the open folder went away
      s.drive = null; s.dErr = e.message;
    }
    if (!quiet || !dragging) rerender(key);
  }
  const needDrive = key => { const s = S_(key); if (Date.now() - s.dAt > 20000) setTimeout(() => loadDrive(key, true)); };

  // ---------- the page ----------
  function html(key) {
    const s = S_(key), t = team(key);
    needSrc(key);
    const [left, right] = sides(key);
    if (right === "drive") needDrive(key);
    if (left === "source" || right === "source") needGit(key);
    const pick = key === "ws" && left === "team" ? picker() : "";
    if (!t && left === "team") return `<section class="mh-card tfm" data-tfm="${key}">${head(key, pick)}${key === "ws" && wsTeams && !wsTeams.length ? `<p class="faint small">You have no competition teams yet. Make one in Competition teams, then copy files between it and My workspace here.</p>` : Loading.line("Opening the team's files…")}</section>`;
    if (t && s.wid !== t.wid) Object.assign(s, { wid: t.wid, tpath: "", tsel: new Set(), vdirs: new Set(), note: null });
    if (t) for (const p of [...s.tsel]) if (!s.vdirs.has(p) && !t.files.some(f => f.path === p || f.path.startsWith(`${p}/`))) s.tsel.delete(p);  // gone since
    return `<section class="mh-card tfm" data-tfm="${key}">${head(key, pick)}${note(s)}
      <div class="tfm-panes">${left === "team" ? teamPane(s, t, right) : sourcePane(s, left, right)}${right === "drive" ? drivePane(s, t, left) : sourcePane(s, right, left)}</div></section>`;
  }
  function head(key, pick) {
    const pr = pair(key), [l, r] = PAIRS[pr];
    const seg = hasGit() ? `<div class="seg tfm-pairs" role="group" aria-label="Places side by side">${Object.entries(PAIRS).map(([k, [a, b]]) =>
      `<button type="button" data-tfmpair="${k}" aria-pressed="${pr === k}">${esc(a)} ⇄ ${esc(b)}</button>`).join("")}</div>` : "";
    const say = { "team-drive": "Agents read and run the team's files; My workspace keeps yours in AXoR Drive.",
      "team-source": "Copy a repository's files into the team, or commit the team's files to a branch.",
      "source-drive": "Copy a repository's files into AXoR Drive, or commit yours to a branch." }[pr];
    return `<div class="tfm-head"><div><h3>${icon("swap")}Files: ${esc(l === "Team" ? "the team" : l)} and ${esc(r)}</h3>
        <p class="faint small">Tick files or folders and copy them across, or drag them onto the other side. ${say}</p>${seg}</div>${pick}</div>`;
  }
  function picker() {
    if (!wsTeams?.length) return "";
    const here = wsTeams.filter(x => x.netuid === wsSub), rest = wsTeams.filter(x => x.netuid !== wsSub);
    const opt = x => `<option value="${x.id}" ${x.id === wsTeam?.comp.id ? "selected" : ""}>SN${x.netuid} · ${esc(x.label)}${x.status === "closed" ? " (closed)" : ""}</option>`;
    return `<label class="tfm-pick"><span class="faint small">Team</span><select data-tfmteam aria-label="Competition team">${here.length && rest.length ? `<optgroup label="SN${wsSub}">${here.map(opt).join("")}</optgroup><optgroup label="Other subnets">${rest.map(opt).join("")}</optgroup>` : wsTeams.map(opt).join("")}</select></label>`;
  }
  function note(s) {
    const n = s.note; if (!n) return "";
    return `<div class="tfm-note ${n.kind}" role="status">${icon(n.kind === "ok" ? "check" : "alert")}<div><b>${esc(n.text)}</b>${n.items?.length ? `<ul>${n.items.slice(0, 8).map(x => `<li>${esc(x)}</li>`).join("")}${n.items.length > 8 ? `<li class="faint">and ${n.items.length - 8} more</li>` : ""}</ul>` : ""}
      ${n.replace ? `<div class="row"><button type="button" class="btn sm" data-tfma="replace">${icon("cycle")}Replace ${plural(n.replace.n, "file")}</button></div>` : ""}</div>
      <button type="button" class="iconbtn sm" data-tfma="unnote" aria-label="Dismiss" title="Dismiss">${icon("close")}</button></div>`;
  }
  const check = (side, val, on, label) => `<input type="checkbox" data-tfmck="${side}" value="${esc(val)}" ${on ? "checked" : ""} aria-label="Select ${esc(label)}">`;
  function teamPane(s, t, to) {
    const { dirs, files } = tree(t.files, s.tpath, s.vdirs), used = t.files.reduce((n, f) => n + f.size, 0);
    const crumbs = [["", t.label], ...s.tpath.split("/").filter(Boolean).map((p, i, a) => [a.slice(0, i + 1).join("/"), p])];
    const all = [...dirs.map(d => d.path), ...files.map(f => f.path)], n = s.tsel.size, busy = s.busy === "team";
    const rows = [
      ...(s.tpath ? [`<li class="tfm-row up"><span></span><button type="button" class="tfm-name" data-tfmt="${esc(parent(s.tpath))}">${icon("folderup")}..</button><span></span></li>`] : []),
      ...dirs.map(d => `<li class="tfm-row" draggable="true" data-tfmrow="team" data-v="${esc(d.path)}">${check("team", d.path, s.tsel.has(d.path), d.name)}
        <button type="button" class="tfm-name" data-tfmt="${esc(d.path)}">${icon("folder")}<span>${esc(d.name)}</span></button>
        <span class="tfm-meta faint small">${d.n ? `${plural(d.n, "file")} · ${bytes(d.size)}` : "empty: save a file here"}</span></li>`),
      ...files.map(f => `<li class="tfm-row" draggable="true" data-tfmrow="team" data-v="${esc(f.path)}">${check("team", f.path, s.tsel.has(f.path), base(f.path))}
        <button type="button" class="tfm-name" data-tfmopen="${f.id}">${icon("file")}<span>${esc(base(f.path))}</span></button>
        <span class="tfm-meta faint small">${bytes(f.size)} · ${f.author ? esc(f.author) : "you"} · <time data-ts="${f.updated}"></time></span></li>`)];
    return `<div class="tfm-pane" data-tfmpane="team" aria-label="The team's files">
      <div class="tfm-ph"><b>${icon("users")}Team</b><span class="faint small" title="A team file holds text up to ${bytes(t.limits.file_bytes)}">${plural(t.files.length, "file")} · ${bytes(used)} of ${bytes(t.limits.files_bytes)}</span></div>
      <nav class="tfm-crumbs" aria-label="Team folder">${crumbs.map(([p, l], i) => `${i ? `<span class="faint">/</span>` : ""}<button type="button" data-tfmt="${esc(p)}" ${p === s.tpath ? `aria-current="true"` : ""}>${esc(l)}</button>`).join("")}</nav>
      <div class="tfm-bar">${n ? `<span class="tfm-n">${n} selected</span>
          ${copyBtn("tcopy", "right", to, busy)}
          ${n === 1 ? `<button type="button" class="btn sm" data-tfma="tmove">${icon("edit")}Rename or move</button>` : ""}
          <button type="button" class="btn sm mw-danger" data-tfma="tdel">${icon("trash")}Delete</button>
          <button type="button" class="linkbtn small" data-tfma="tnone">Clear</button>`
        : `<button type="button" class="btn sm" data-tfma="tnew">${icon("plus")}New file</button><button type="button" class="btn sm" data-tfma="tdir">${icon("folderplus")}New folder</button>
          <label class="btn sm" title="Text files, up to ${bytes(t.limits.file_bytes)} each"><input type="file" multiple class="sr" data-tfmup="team">${icon("upload")}Upload</label>`}</div>
      <div class="tfm-listwrap ${busy ? "busy" : ""}" data-tfmdrop="team">${all.length ? `<label class="tfm-all small faint">${check("team-all", "", all.every(p => s.tsel.has(p)), "everything here")}Everything here</label>` : ""}
        <ul class="tfm-list">${rows.join("")}</ul>
        ${all.length ? "" : `<p class="faint small tfm-empty">${s.tpath ? "This folder is empty." : "No files yet. The Agent Architect writes <code>agent.py</code>; drop files here or copy them from My workspace."}</p>`}</div></div>`;
  }
  function drivePane(s, t, from) {
    const d = s.drive, n = s.dsel.size, busy = s.busy === "drive", [sl] = SPACE[s.dspace];
    const space = `<div class="seg" role="group" aria-label="Drive">${Object.entries(SPACE).map(([k, [l, ic, who]]) => `<button type="button" data-tfmspace="${k}" aria-pressed="${s.dspace === k}" title="${l}: ${who}">${icon(ic)}${l}</button>`).join("")}</div>`;
    let body;
    if (s.dErr) body = `<p class="mh-err small">${icon("alert")}${esc(s.dErr)}</p>`;
    else if (!d) body = Loading.line("Opening the drive…");
    else {
      const items = d.items;
      body = `${items.length ? `<label class="tfm-all small faint">${check("drive-all", "", items.every(x => s.dsel.has(x.id)), "everything here")}Everything here</label>` : ""}<ul class="tfm-list">
        ${s.dfolder ? `<li class="tfm-row up"><span></span><button type="button" class="tfm-name" data-tfmd="${esc(d.path.length > 1 ? d.path[d.path.length - 2].id : "")}">${icon("folderup")}..</button><span></span></li>` : ""}
        ${items.map(x => `<li class="tfm-row" draggable="true" data-tfmrow="drive" data-v="${esc(x.id)}">${check("drive", x.id, s.dsel.has(x.id), x.name)}
          <button type="button" class="tfm-name" ${x.kind === "folder" ? `data-tfmd="${esc(x.id)}"` : `data-tfmview="${esc(x.id)}"`}>${icon(x.kind === "folder" ? "folder" : "file")}<span>${esc(x.name)}</span></button>
          <span class="tfm-meta faint small">${x.kind === "folder" ? "folder" : bytes(x.size)}${x.netuid != null ? ` · SN${x.netuid}` : ""}${x.mine ? "" : ` · ${esc(x.owner || "someone")}`} · <time data-ts="${x.updated}"></time></span></li>`).join("")}</ul>
        ${items.length ? "" : `<p class="faint small tfm-empty">${s.dfolder ? "This folder is empty." : `Nothing in ${sl} yet.`} Copy team files here, or drop files to upload them.</p>`}`;
    }
    const crumbs = [["", sl], ...(d?.path || []).map(p => [p.id, p.name])];
    const into = s.dfolder ? (d?.path || []).map(p => p.name).join(" › ") : from === "source" ? `GitHub › ${(s.grepo || "").replace("/", "-")}` : `${TEAMS} › ${t?.label || "the team"}`;
    return `<div class="tfm-pane" data-tfmpane="drive" aria-label="My workspace's files">
      <div class="tfm-ph"><b>${icon("pickaxe")}My workspace</b>${space}</div>
      <nav class="tfm-crumbs" aria-label="Drive folder">${crumbs.map(([id, l], i) => `${i ? `<span class="faint">/</span>` : ""}<button type="button" data-tfmd="${esc(id)}" ${id === (s.dfolder || "") ? `aria-current="true"` : ""}>${esc(l)}</button>`).join("")}</nav>
      <div class="tfm-bar">${n ? `<span class="tfm-n">${n} selected</span>
          ${copyBtn("dcopy", "left", from, busy)}
          <button type="button" class="btn sm mw-danger" data-tfma="ddel">${icon("trash")}Move to trash</button>
          <button type="button" class="linkbtn small" data-tfma="dnone">Clear</button>`
        : `<button type="button" class="btn sm" data-tfma="ddir" ${s.dErr ? "disabled" : ""}>${icon("folderplus")}New folder</button>
          <label class="btn sm ${s.dErr ? "disabled" : ""}"><input type="file" multiple class="sr" data-tfmup="drive" ${s.dErr ? "disabled" : ""}>${icon("upload")}Upload</label>
          <button type="button" class="btn sm" data-open-drive>${icon("external")}Open Drive</button>`}</div>
      <div class="tfm-listwrap ${busy ? "busy" : ""}" data-tfmdrop="drive">${body}</div>
      ${s.dErr ? "" : `<p class="faint small tfm-into">${icon("info")}<span>${from === "source" ? "Repository files" : "Team files"} copied here go to <b>${esc(sl)} › ${esc(into)}</b>${s.dspace === "shared" ? ", where everyone signed in can read them" : ""}.</span></p>`}</div>`;
  }
  const TEAMS = "Competition teams";
  // a selection's copy button, named for where it goes; committing to GitHub is for administrators
  function copyBtn(a, arrow, to, busy) {
    const git = to === "source", no = git && !src?.can_write;
    return `<button type="button" class="btn sm primary" data-tfma="${a}" ${busy || no ? "disabled" : ""} ${no ? `title="Only administrators commit to the Source hub's repositories"` : ""}>${icon(git ? "commit" : arrow)}${git ? "Commit to GitHub" : `Copy to ${PLACE[to]}`}</button>`;
  }

  // ---------- GitHub: the Source hub's repositories ----------
  async function loadSrc(key) {
    if (srcLoading) return; srcLoading = true;
    try { src = await api(`${F}/source`); srcAt = Date.now(); }
    catch { src = { configured: false, repos: [] }; srcAt = Date.now(); }
    finally { srcLoading = false; }
    rerender(key);
  }
  const needSrc = key => { if (!src || Date.now() - srcAt > 60000) setTimeout(() => loadSrc(key)); };
  const repoUrl = r => `/api/source/repos/${r.split("/").map(encodeURIComponent).join("/")}`;
  async function loadGit(key, quiet = false) {
    const s = S_(key), seq = ++s.gSeq;
    s.gAt = Date.now();
    if (!src?.repos.length) return;
    if (!src.repos.includes(s.grepo)) { const r = store.get("mf.repo", null); s.grepo = src.repos.includes(r) ? r : src.repos[0]; s.gref = null; s.gpath = ""; s.branches = null; }
    try {
      if (!s.branches) s.branches = await api(`${repoUrl(s.grepo)}/branches`);
      if (seq !== s.gSeq) return;
      if (!s.branches.some(b => b.name === s.gref)) s.gref = (s.branches.find(b => b.default) || s.branches[0])?.name || null;
      const q = new URLSearchParams({ path: s.gpath, ...(s.gref ? { ref: s.gref } : {}) });
      const r = await api(`${repoUrl(s.grepo)}/contents?${q}`);
      if (seq !== s.gSeq) return;
      if (r.type !== "dir") { s.gpath = parent(s.gpath); return loadGit(key, quiet); }
      s.git = r; s.gErr = "";
      const have = new Set(r.entries.map(e => e.path)); s.gsel = new Set([...s.gsel].filter(p => have.has(p)));
    } catch (e) {
      if (seq !== s.gSeq) return;
      if (s.gpath && e.status === 404) { s.gpath = ""; return loadGit(key, quiet); }  // the open folder isn't on this branch
      s.git = null; s.gErr = e.message;
    }
    if (!quiet || !dragging) rerender(key);
  }
  const needGit = key => { const s = S_(key); if (src?.repos.length && (!s.git && !s.gErr || Date.now() - s.gAt > 60000) && Date.now() - s.gAt > 1500) setTimeout(() => loadGit(key, true)); };
  function sourcePane(s, side, to) {
    const g = s.git, n = s.gsel.size, busy = s.busy === "source", arrow = side === "source" && to === "drive" ? "right" : "left";
    const repos = src?.repos || [], br = s.branches || [];
    const pickRepo = `<select data-tfmrepo aria-label="Repository">${repos.map(r => `<option value="${esc(r)}" ${r === s.grepo ? "selected" : ""}>${esc(r)}</option>`).join("")}</select>`;
    const pickRef = `<select data-tfmref aria-label="Branch" ${br.length ? "" : "disabled"}>${br.map(b => `<option value="${esc(b.name)}" ${b.name === s.gref ? "selected" : ""}>${esc(b.name)}${b.default ? " (default)" : ""}${b.protected ? " 🔒" : ""}</option>`).join("") || `<option>${esc(s.gref || "…")}</option>`}</select>`;
    let body;
    if (s.gErr) body = `<p class="mh-err small">${icon("alert")}${esc(s.gErr)}</p>`;
    else if (!g) body = Loading.line("Opening the repository…");
    else {
      const pickable = g.entries.filter(e => (e.type === "dir" || e.type === "file") && !e.secret);
      body = `${pickable.length ? `<label class="tfm-all small faint">${check("source-all", "", pickable.every(e => s.gsel.has(e.path)), "everything here")}Everything here</label>` : ""}<ul class="tfm-list">
        ${s.gpath ? `<li class="tfm-row up"><span></span><button type="button" class="tfm-name" data-tfmg="${esc(parent(s.gpath))}">${icon("folderup")}..</button><span></span></li>` : ""}
        ${g.entries.map(e => {
          const ok = (e.type === "dir" || e.type === "file") && !e.secret;
          return `<li class="tfm-row ${ok ? "" : "off"}" ${ok ? `draggable="true" data-tfmrow="source" data-v="${esc(e.path)}"` : ""}>${ok ? check("source", e.path, s.gsel.has(e.path), e.name) : `<span class="tfm-lock" title="${e.secret ? "Looks like a secret: it stays on GitHub" : "Open it on GitHub"}">${icon("lock")}</span>`}
          <button type="button" class="tfm-name" ${e.type === "dir" ? `data-tfmg="${esc(e.path)}"` : e.type === "file" && !e.secret ? `data-tfmgview="${esc(e.path)}"` : "disabled"}>${icon(e.type === "dir" ? "folder" : "file")}<span>${esc(e.name)}</span></button>
          <span class="tfm-meta faint small">${e.type === "dir" ? "folder" : e.secret ? "secret: stays on GitHub" : e.type === "file" ? bytes(e.size) : e.type}</span></li>`; }).join("")}</ul>
        ${g.entries.length ? "" : `<p class="faint small tfm-empty">This folder is empty.</p>`}`;
    }
    const crumbs = [["", s.grepo || "GitHub"], ...s.gpath.split("/").filter(Boolean).map((p, i, a) => [a.slice(0, i + 1).join("/"), p])];
    const web = s.grepo && s.gref ? `https://github.com/${s.grepo}/tree/${encodeURIComponent(s.gref)}${s.gpath ? `/${s.gpath}` : ""}` : null;
    return `<div class="tfm-pane" data-tfmpane="source" aria-label="A GitHub repository's files">
      <div class="tfm-ph"><b>${icon("github")}GitHub</b><span class="tfm-git">${pickRepo}${pickRef}</span></div>
      <nav class="tfm-crumbs" aria-label="Repository folder">${crumbs.map(([p, l], i) => `${i ? `<span class="faint">/</span>` : ""}<button type="button" data-tfmg="${esc(p)}" ${p === s.gpath ? `aria-current="true"` : ""}>${esc(l)}</button>`).join("")}</nav>
      <div class="tfm-bar">${n ? `<span class="tfm-n">${n} selected</span>
          ${copyBtn("gcopy", arrow, to, busy)}
          <button type="button" class="linkbtn small" data-tfma="gnone">Clear</button>`
        : `${web ? `<a class="btn sm" href="${esc(web)}" target="_blank" rel="noopener">${icon("external")}Open on GitHub</a>` : ""}
          <button type="button" class="btn sm" data-tfma="greload">${icon("cycle")}Refresh</button>
          ${src?.can_write ? `<button type="button" class="btn sm" data-tfma="gnew">${icon("plus")}New repository</button>` : ""}`}</div>
      <div class="tfm-listwrap ${busy ? "busy" : ""}" data-tfmdrop="source">${body}</div>
      <p class="faint small tfm-into">${icon("info")}<span>${src?.can_write ? `Files dropped here are committed to <b>${esc(s.grepo || "")} › ${esc(s.gref || "")}${s.gpath ? ` › ${esc(s.gpath)}` : ""}</b> as one commit, with a message you write. Keep it off a branch that deploys on push.`
        : "Only administrators commit to GitHub: the Source hub's tokens are theirs. You can copy files out of it."}</span></p></div>`;
  }
  // out of a repository: into the team (text files, asking before replacing) or onto the drive (a new version when taken)
  async function fromGit(key, to, paths, replace = false) {
    const s = S_(key), t = team(key); if (!paths.length || !s.grepo || !s.gref) return;
    s.busy = to === "team" ? "team" : "drive"; rerender(key);
    const body = { repo: s.grepo, ref: s.gref, paths, base: s.gpath };
    try {
      if (to === "team") {
        if (!t) throw new Error("Pick a team first.");
        const r = await api(`${F}/source/to-team/${t.wid}`, { method: "POST", body: { ...body, folder: s.tpath, replace } });
        const bad = r.results.filter(x => !x.ok && !x.conflict), swapped = r.results.filter(x => x.replaced).length;
        s.note = { kind: bad.length || r.conflicts.length ? "warn" : "ok",
          text: [r.copied ? `Copied ${plural(r.copied, "file")} from ${s.grepo} into ${t.label}${s.tpath ? ` / ${s.tpath}` : ""}${swapped ? ` (${swapped} replaced)` : ""}` : "Nothing was copied",
            r.conflicts.length ? `${plural(r.conflicts.length, "file")} ${r.conflicts.length === 1 ? "is" : "are"} already in the team` : "", bad.length ? `${bad.length} didn't copy` : ""].filter(Boolean).join("; ") + ".",
          items: [...r.conflicts.map(p => `${p}: the team has a file there`), ...bad.map(x => `${x.name}: ${x.error}`)],
          replace: r.conflicts.length ? { git: paths, folder: s.tpath, n: r.conflicts.length } : null };
        s.gsel.clear(); s.busy = ""; return teamChanged(key, r.team);
      }
      const r = await api(`${F}/source/to-drive`, { method: "POST", body: { ...body, space: s.dspace, folder: s.dfolder } });
      const bad = r.results.filter(x => !x.ok), again = r.results.filter(x => x.new_version).length;
      const where = [SPACE[s.dspace][0], ...(r.where.path.length ? r.where.path : (s.drive?.path || []).map(p => p.name))].join(" › ");
      s.note = { kind: bad.length ? "warn" : "ok", text: `${r.copied ? `Copied ${plural(r.copied, "file")} from ${s.grepo} to ${where}` : "Nothing was copied"}${again ? ` (${again} as a new version of a file already there)` : ""}${bad.length ? `; ${bad.length} didn't copy:` : "."}`,
        items: bad.map(x => `${x.path}: ${x.error}`) };
      s.gsel.clear();
      if (!s.dfolder && r.where.folder) s.dfolder = r.where.folder;
      s.busy = ""; await loadDrive(key);
    } catch (e) { s.busy = ""; s.note = { kind: "warn", text: e.message }; rerender(key); }
  }
  // into a repository: one commit on the open branch, into the open folder (administrators)
  async function toGit(key, from, items) {
    const s = S_(key), t = team(key); if (!items.length || !s.grepo || !s.gref) return;
    if (!src?.can_write) return toast("Only administrators commit to the Source hub's repositories.", { kind: "error" });
    const what = from === "team" ? `from ${t?.label || "the team"}` : "from My workspace";
    const msg = await ask(`${icon("commit")}Commit to ${esc(s.grepo)}`, "Commit message", `Add ${items.length === 1 ? base(from === "team" ? items[0] : (s.drive?.items.find(x => x.id === items[0])?.name || "a file")) : plural(items.length, "item")} ${what}`,
      `One commit on <b>${esc(s.gref)}</b>, into <code>${esc(s.gpath || "/")}</code>; a file already there is replaced. Folders keep their subfolders. Files that look like secrets are left out.`);
    if (!msg) return;
    s.busy = "source"; rerender(key);
    const body = { repo: s.grepo, branch: s.gref, folder: s.gpath, message: msg };
    try {
      const r = from === "team" ? await api(`${F}/source/from-team/${t.wid}`, { method: "POST", body: { ...body, paths: items, base: s.tpath } })
        : await api(`${F}/source/from-drive`, { method: "POST", body: { ...body, ids: items } });
      const bad = r.results.filter(x => !x.ok);
      s.note = { kind: bad.length ? "warn" : "ok", text: `${r.committed ? `Committed ${plural(r.committed, "file")} to ${s.grepo} on ${s.gref} (${r.commit.sha.slice(0, 7)})` : "Nothing was committed"}${bad.length ? `; ${bad.length} left out:` : "."}`,
        items: bad.map(x => `${x.path}: ${x.error}`) };
      (from === "team" ? s.tsel : s.dsel).clear();
    } catch (e) { s.note = { kind: "warn", text: e.message }; }
    s.busy = ""; s.branches = null; await loadGit(key);
  }
  async function copy(key, from, items, to = other(key, from)) {
    if (!items.length || from === to) return;
    if (from === "team" && to === "drive") return toDrive(key, items);
    if (from === "drive" && to === "team") return toTeam(key, items);
    if (from === "source") return fromGit(key, to, items);
    return toGit(key, from, items);
  }
  async function openGitFile(key, path) {
    const s = S_(key), d = dlg(), to = other(key, "source");
    d.onclose = d.oncancel = null;
    d.innerHTML = `<div class="hq-dlg-in tfm-edit"><h3>${icon("file")}${esc(base(path))} <span class="faint small">${esc(s.grepo)} · ${esc(s.gref)}</span></h3><div class="tfm-prev">${Loading.line("Reading…")}</div>
      <div class="row end"><a class="btn" href="https://github.com/${esc(s.grepo)}/blob/${encodeURIComponent(s.gref)}/${esc(path)}" target="_blank" rel="noopener">${icon("external")}Open on GitHub</a><button type="button" class="btn" data-tfmx="copy">${icon(to === "drive" ? "right" : "left")}Copy to ${PLACE[to]}</button><button type="button" class="btn primary" data-tfmx="close">Close</button></div></div>`;
    d.querySelector(".tfm-edit").onclick = e => {
      const b = e.target.closest("[data-tfmx]"); if (!b) return;
      d.close(); if (b.dataset.tfmx === "copy") fromGit(key, to, [path]);
    };
    d.showModal();
    try {
      const r = await api(`${repoUrl(s.grepo)}/contents?${new URLSearchParams({ path, ref: s.gref })}`);
      const p = d.querySelector(".tfm-prev"); if (!p) return;
      p.innerHTML = r.text == null ? `<p class="faint small">No preview: ${r.hidden === "binary" ? "this isn't a text file" : r.hidden === "large" ? "it's over GitHub's 1 MB preview limit" : "GitHub doesn't show it here"}. You can still copy it to My workspace.</p>`
        : `<pre class="tfm-pre">${esc(r.text.slice(0, 200000))}</pre>${r.truncated || r.text.length > 200000 ? `<p class="faint small">The preview stops here.</p>` : ""}`;
    } catch (e) { const p = d.querySelector(".tfm-prev"); if (p) p.innerHTML = `<p class="mh-err small">${esc(e.message)}</p>`; }
  }

  // ---------- copying ----------
  async function toDrive(key, paths) {
    const s = S_(key), t = team(key); if (!t || !paths.length) return;
    s.busy = "drive"; rerender(key);
    try {
      const r = await api(`${F}/teams/${t.wid}/to-drive`, { method: "POST", body: { paths, base: s.tpath, space: s.dspace, folder: s.dfolder } });
      const bad = r.results.filter(x => !x.ok), where = [SPACE[s.dspace][0], ...(r.where.path.length ? r.where.path : (s.drive?.path || []).map(p => p.name))].join(" › ");
      const again = r.results.filter(x => x.new_version).length;
      s.note = { kind: bad.length ? "warn" : "ok", text: `${r.copied ? `Copied ${plural(r.copied, "file")} to ${where}` : "Nothing was copied"}${again ? ` (${again} as a new version of a file already there)` : ""}${bad.length ? `; ${bad.length} didn't copy:` : "."}`,
        items: bad.map(x => `${x.path}: ${x.error}`) };
      s.tsel.clear();
      if (!s.dfolder && r.where.folder) s.dfolder = r.where.folder;  // show where they went
    } catch (e) { s.note = { kind: "warn", text: e.message }; }
    s.busy = ""; await loadDrive(key);
  }
  async function toTeam(key, ids, replace = false) {
    const s = S_(key), t = team(key); if (!t || !ids.length) return;
    s.busy = "team"; rerender(key);
    try {
      const r = await api(`${F}/teams/${t.wid}/from-drive`, { method: "POST", body: { ids, folder: s.tpath, replace } });
      const bad = r.results.filter(x => !x.ok && !x.conflict), swapped = r.results.filter(x => x.replaced).length;
      s.note = { kind: bad.length || r.conflicts.length ? "warn" : "ok",
        text: [r.copied ? `Copied ${plural(r.copied, "file")} into ${t.label}${s.tpath ? ` / ${s.tpath}` : ""}${swapped ? ` (${swapped} replaced)` : ""}` : "Nothing was copied",
          r.conflicts.length ? `${plural(r.conflicts.length, "file")} ${r.conflicts.length === 1 ? "is" : "are"} already in the team` : "", bad.length ? `${bad.length} didn't copy` : ""].filter(Boolean).join("; ") + ".",
        items: [...r.conflicts.map(p => `${p}: the team has a file there`), ...bad.map(x => `${x.name}: ${x.error}`)],
        replace: r.conflicts.length ? { ids, folder: s.tpath, n: r.conflicts.length } : null };
      s.dsel.clear();
      s.busy = ""; await teamChanged(key, r.team);
    } catch (e) { s.busy = ""; s.note = { kind: "warn", text: e.message }; rerender(key); }
  }

  // ---------- uploads ----------
  async function uploadTeam(key, list) {
    const s = S_(key), t = team(key); if (!t) return;
    const skipped = [];
    let done = 0, nv = null;
    for (const file of list) {
      if (file.size > t.limits.file_bytes) { skipped.push(`${file.name}: over ${bytes(t.limits.file_bytes)}`); continue; }
      const text = await file.text();
      if (text.includes("\u0000")) { skipped.push(`${file.name}: not a text file (team files hold text only)`); continue; }
      try { nv = await api(`${W}/comps/${t.wid}/files`, { method: "PUT", body: { path: join(s.tpath, safe(file.name)), content: text } }); done++; }
      catch (e) { skipped.push(`${file.name}: ${e.message}`); }
    }
    s.note = { kind: skipped.length ? "warn" : "ok", text: `${done ? `Uploaded ${plural(done, "file")} to the team` : "Nothing was uploaded"}${skipped.length ? `; ${skipped.length} skipped:` : "."}`, items: skipped };
    if (key === "teams" && nv) MiningWork.apply(nv); else await teamChanged(key);
    rerender(key);
  }
  async function uploadDrive(key, list) {
    const s = S_(key), bad = [];
    let done = 0;
    for (const file of list) {
      const q = new URLSearchParams({ name: file.name, space: s.dspace, ...(s.dfolder ? { parent: s.dfolder } : {}) });
      try {
        const r = await fetch(`/api/drive/files?${q}`, { method: "POST", body: file, credentials: "same-origin", headers: { "X-Requested-With": "scout", "Content-Type": "application/octet-stream" } });
        if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`); }
        done++;
      } catch (e) { bad.push(`${file.name}: ${e.message}`); }
    }
    s.note = { kind: bad.length ? "warn" : "ok", text: `${done ? `Uploaded ${plural(done, "file")} to My workspace` : "Nothing was uploaded"}${bad.length ? `; ${bad.length} failed:` : "."}`, items: bad };
    await loadDrive(key);
  }

  // ---------- dialogs: a team file to edit, a drive file to read, a name to type ----------
  function dlg() {
    let d = document.getElementById("tfm-dlg");
    if (!d) { d = document.createElement("dialog"); d.id = "tfm-dlg"; document.body.append(d); }
    d.className = "modal mw-dlg tfm-dlg";
    return d;
  }
  function ask(title, label, value, hint = "") {
    const d = dlg();
    d.classList.add("tfm-ask");
    d.innerHTML = `<form method="dialog" class="hq-dlg-in" autocomplete="off"><h3>${title}</h3>
      <label class="in"><span>${label}</span><input name="v" value="${esc(value)}" spellcheck="false" required maxlength="400"></label>${hint ? `<p class="faint small">${hint}</p>` : ""}
      <div class="row end"><button type="button" class="btn" data-tfmx>Cancel</button><button type="submit" class="btn primary">OK</button></div></form>`;
    return new Promise(res => {
      const f = d.querySelector("form"), i = f.elements.v;
      let out = null;
      d.oncancel = null;
      f.onsubmit = e => { e.preventDefault(); out = i.value.trim() || null; d.close(); };
      d.querySelector("[data-tfmx]").onclick = () => d.close();
      d.onclose = () => res(out);
      d.showModal(); i.focus(); i.setSelectionRange(i.value.length, i.value.length);
    });
  }
  async function openTeamFile(key, id, path = "") {
    const t = team(key); if (!t) return;
    let f = { id: null, path, content: "" };
    if (id) { try { f = (await api(`${W}/files/${id}`)).file; } catch (e) { return err(e); } }
    const d = dlg(); let dirty = false;
    d.innerHTML = `<form class="hq-dlg-in tfm-edit" autocomplete="off"><h3>${icon("file")}${id ? esc(f.path) : "New file"} <span class="faint small">${esc(t.label)}</span></h3>
      ${id ? "" : `<label class="in"><span>Path <em class="opt">folders with /</em></span><input name="path" value="${esc(f.path)}" required maxlength="400" spellcheck="false" placeholder="tasks/orders-report/check.sh"></label>`}
      <label class="in"><span>Content</span><textarea name="content" rows="20" class="mw-code" spellcheck="false" maxlength="${t.limits.file_bytes}">${esc(f.content)}</textarea></label>
      <p class="err small" role="alert"></p>
      <div class="row end">${id ? `<button type="button" class="btn" data-tfmx="dl">${icon("download")}Download</button>${other(key, "team") === "source" && !src?.can_write ? "" : `<button type="button" class="btn" data-tfmx="copy">${icon(other(key, "team") === "source" ? "commit" : "right")}${other(key, "team") === "source" ? "Commit to GitHub" : "Copy to My workspace"}</button>`}` : ""}
        <button type="button" class="btn" data-tfmx="close">Close</button><button type="submit" class="btn primary">${icon("check")}Save</button></div></form>`;
    const form = d.querySelector("form"), msg = form.querySelector(".err");
    form.elements.content.oninput = () => { dirty = true; };
    d.onclose = null;
    d.oncancel = e => { if (dirty) { e.preventDefault(); form.querySelector('[data-tfmx="close"]').click(); } };  // Esc asks too
    form.onsubmit = async e => {
      e.preventDefault();
      const p = id ? f.path : form.elements.path.value.trim(), btn = form.querySelector("[type=submit]");
      btn.classList.add("loading"); btn.disabled = true; msg.textContent = "";
      try {
        const nv = await api(`${W}/comps/${t.wid}/files`, { method: "PUT", body: { path: p, content: form.elements.content.value } });
        dirty = false; d.close(); toast(`${base(p)} saved`, { kind: "success" });
        if (key === "teams") MiningWork.apply(nv); else teamChanged(key);
      } catch (x) { msg.textContent = x.message; }
      finally { btn.classList.remove("loading"); btn.disabled = false; }
    };
    form.onclick = async e => {
      const b = e.target.closest("[data-tfmx]"); if (!b) return;
      const k = b.dataset.tfmx;
      if (k === "close") {
        if (dirty && !(await UI.confirm({ title: "Close without saving?", body: "Your changes to this file are lost.", ok: "Close", icon: "close" }))) return;
        return d.close();
      }
      if (k === "dl") return save(base(f.path), form.elements.content.value);
      if (k === "copy") { d.close(); return copy(key, "team", [f.path]); }
    };
    d.showModal();
    (id ? form.elements.content : form.elements.path).focus();
  }
  async function openDriveFile(key, id) {
    const x = S_(key).drive?.items.find(i => i.id === id); if (!x) return;
    const d = dlg();
    d.onclose = d.oncancel = null;
    d.innerHTML = `<div class="hq-dlg-in tfm-edit"><h3>${icon("file")}${esc(x.name)} <span class="faint small">${bytes(x.size)}</span></h3><div class="tfm-prev">${Loading.line("Reading…")}</div>
      <div class="row end"><a class="btn" href="/api/drive/nodes/${esc(id)}/content?download=true" download>${icon("download")}Download</a>${other(key, "drive") === "source" && !src?.can_write ? "" : `<button type="button" class="btn" data-tfmx="copy">${icon(other(key, "drive") === "source" ? "commit" : "left")}${other(key, "drive") === "source" ? "Commit to GitHub" : "Copy to the team"}</button>`}<button type="button" class="btn primary" data-tfmx="close">Close</button></div></div>`;
    d.querySelector(".tfm-edit").onclick = e => {
      const b = e.target.closest("[data-tfmx]"); if (!b) return;
      d.close(); if (b.dataset.tfmx === "copy") copy(key, "drive", [id]);
    };
    d.showModal();
    try {
      const r = await api(`/api/drive/nodes/${id}/text`);
      const p = d.querySelector(".tfm-prev"); if (!p) return;
      p.innerHTML = r.text == null ? `<p class="faint small">No preview: this isn't a text file, so it can't be copied to the team either. Download it, or open it in Drive.</p>`
        : `<pre class="tfm-pre">${esc(r.text.slice(0, 200000))}</pre>${r.text.length > 200000 ? `<p class="faint small">The preview stops here.</p>` : ""}`;
    } catch (e) { const p = d.querySelector(".tfm-prev"); if (p) p.innerHTML = `<p class="mh-err small">${esc(e.message)}</p>`; }
  }
  function save(name, text) {
    const a = document.createElement("a"), u = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.href = u; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000);
  }

  // ---------- team edits ----------
  async function newFolder(key) {
    const s = S_(key), n = await ask(`${icon("folderplus")}New folder`, "Name", "", "It shows here until you leave it; it stays once it holds a file. Letters, digits, . _ - only.");
    if (!n) return;
    const p = join(s.tpath, n.split("/").map(safe).join("/"));
    s.vdirs.add(p); s.tpath = p; s.tsel.clear(); rerender(key);
  }
  async function move(key) {
    const s = S_(key), t = team(key), src = [...s.tsel][0]; if (!t || !src) return;
    const dst = await ask(`${icon("edit")}Rename or move`, "New path", src, "Change the name, or the folders before it to move it (a folder takes its files along).");
    if (!dst || dst === src) return;
    try {
      const r = await api(`${F}/teams/${t.wid}/move`, { method: "POST", body: { src, dst } });
      s.tsel.clear(); s.vdirs.delete(src);
      toast(`Moved to ${dst}`, { kind: "success" });
      await teamChanged(key, r);
    } catch (e) { err(e); }
  }
  async function del(key) {
    const s = S_(key), t = team(key), paths = [...s.tsel]; if (!t || !paths.length) return;
    const files = t.files.filter(f => paths.some(p => f.path === p || f.path.startsWith(`${p}/`)));
    const empty = paths.filter(p => !files.some(f => f.path === p || f.path.startsWith(`${p}/`)));  // folders that only exist here
    empty.forEach(p => s.vdirs.delete(p));
    if (!files.length) { s.tsel.clear(); return rerender(key); }
    await UI.confirm({ title: `Delete ${files.length === 1 ? esc(files[0].path) : plural(files.length, "file")} from ${esc(t.label)}?`, body: "Agents lose them. This can't be undone (copy them to My workspace first to keep them).",
      items: files.map(f => esc(f.path)), ok: "Delete",
      run: async () => { const r = await api(`${F}/teams/${t.wid}/delete`, { method: "POST", body: { paths: paths.filter(p => !empty.includes(p)) } }); s.tsel.clear(); await teamChanged(key, r); } }).catch(err);
  }
  async function trash(key) {
    const s = S_(key), ids = [...s.dsel], items = (s.drive?.items || []).filter(x => ids.includes(x.id)); if (!items.length) return;
    await UI.confirm({ title: `Move ${items.length === 1 ? esc(items[0].name) : plural(items.length, "item")} to the trash?`, body: `You can restore ${items.length === 1 ? "it" : "them"} from Drive › Trash for a while.`,
      items: items.map(x => esc(x.name)), ok: "Move to trash",
      run: async () => { for (const x of items) await api(`/api/drive/nodes/${x.id}/trash`, { method: "POST" }); s.dsel.clear(); await loadDrive(key); } }).catch(err);
  }
  async function driveFolder(key) {
    const s = S_(key), n = await ask(`${icon("folderplus")}New folder in My workspace`, "Name", "");
    if (!n) return;
    try { const r = await api("/api/drive/folders", { method: "POST", body: { space: s.dspace, parent: s.dfolder, name: n } }); s.dfolder = r.id || s.dfolder; s.dsel.clear(); await loadDrive(key); }
    catch (e) { err(e); }
  }

  // ---------- events (delegated: the panes are redrawn often) ----------
  function wire(el, key) {
    const keyOf = t => t.closest?.("[data-tfm]")?.dataset.tfm;
    el.addEventListener("click", async e => {
      const t = e.target, k = keyOf(t); if (!k || (key && k !== key)) return;
      const s = S_(k);
      const tf = t.closest("[data-tfmt]"); if (tf) { s.tpath = tf.dataset.tfmt; s.tsel.clear(); for (const p of [...s.vdirs]) if (s.tpath !== p && !s.tpath.startsWith(`${p}/`) && !(team(k)?.files || []).some(f => f.path.startsWith(`${p}/`))) s.vdirs.delete(p); return rerender(k); }
      const pp = t.closest("[data-tfmpair]"); if (pp) { s.pair = pp.dataset.tfmpair; store.set("mf.pair", s.pair); s.note = null; if (k === "ws") loadWs(); return rerender(k); }
      const gf = t.closest("[data-tfmg]"); if (gf) { s.gpath = gf.dataset.tfmg; s.gsel.clear(); s.git = null; return loadGit(k); }
      const gv = t.closest("[data-tfmgview]"); if (gv) return openGitFile(k, gv.dataset.tfmgview);
      const df = t.closest("[data-tfmd]"); if (df) { s.dfolder = df.dataset.tfmd || null; s.dsel.clear(); s.drive = null; return loadDrive(k); }
      const sp = t.closest("[data-tfmspace]"); if (sp) { if (sp.dataset.tfmspace !== s.dspace) { s.dspace = sp.dataset.tfmspace; store.set("mf.space", s.dspace); s.dfolder = null; s.dsel.clear(); s.drive = null; loadDrive(k); } return; }
      const op = t.closest("[data-tfmopen]"); if (op) return openTeamFile(k, +op.dataset.tfmopen);
      const vw = t.closest("[data-tfmview]"); if (vw) return openDriveFile(k, vw.dataset.tfmview);
      const a = t.closest("[data-tfma]")?.dataset.tfma; if (!a) return;
      if (a === "unnote") { s.note = null; return rerender(k); }
      if (a === "replace") { const r = s.note?.replace; s.note = null; if (r) s.tpath = r.folder; return r && (r.git ? fromGit(k, "team", r.git, true) : toTeam(k, r.ids, true)); }
      if (a === "tcopy") return copy(k, "team", [...s.tsel]);
      if (a === "dcopy") return copy(k, "drive", [...s.dsel]);
      if (a === "gcopy") return copy(k, "source", [...s.gsel]);
      if (a === "gnone") { s.gsel.clear(); return rerender(k); }
      if (a === "greload") { s.branches = null; s.git = null; return loadGit(k); }
      if (a === "gnew") {
        const r = await RepoNew.open(); if (!r) return;
        src.repos = r.repos; s.grepo = r.repo; store.set("mf.repo", r.repo);
        Object.assign(s, { gref: null, gpath: "", gsel: new Set(), git: null, branches: null });
        return loadGit(k);
      }
      if (a === "tnone") { s.tsel.clear(); return rerender(k); }
      if (a === "dnone") { s.dsel.clear(); return rerender(k); }
      if (a === "tnew") return openTeamFile(k, null, s.tpath ? `${s.tpath}/` : "");
      if (a === "tdir") return newFolder(k);
      if (a === "tmove") return move(k);
      if (a === "tdel") return del(k);
      if (a === "ddel") return trash(k);
      if (a === "ddir") return driveFolder(k);
    });
    el.addEventListener("change", e => {
      const t = e.target, k = keyOf(t); if (!k || (key && k !== key)) return;
      const s = S_(k);
      if (t.matches("[data-tfmteam]")) { wsWid = +t.value; pickOf(wsSub); picks[wsSub ?? "all"] = wsWid; store.set("mf.ws", picks); wsTeam = null; rerender("ws"); loadWs(true); return; }
      if (t.matches("[data-tfmrepo]")) { s.grepo = t.value; store.set("mf.repo", s.grepo); Object.assign(s, { gref: null, gpath: "", gsel: new Set(), git: null, branches: null }); return loadGit(k); }
      if (t.matches("[data-tfmref]")) { s.gref = t.value; s.gsel.clear(); s.git = null; return loadGit(k); }
      if (t.matches("[data-tfmup]")) { const list = [...t.files]; t.value = ""; return t.dataset.tfmup === "team" ? uploadTeam(k, list) : uploadDrive(k, list); }
      const side = t.dataset.tfmck; if (!side) return;
      const sel = { team: s.tsel, drive: s.dsel, source: s.gsel };
      if (side.endsWith("-all")) {
        const one = side.slice(0, -4), set = sel[one];
        $$(`[data-tfmck="${one}"]`, t.closest("[data-tfmpane]")).forEach(c => t.checked ? set.add(c.value) : set.delete(c.value));
      } else sel[side][t.checked ? "add" : "delete"](t.value);
      rerender(k);
    });
    // drag rows onto the other side to copy them; drop files from the computer onto a side to upload them
    el.addEventListener("dragstart", e => {
      const r = e.target.closest?.("[data-tfmrow]"), k = keyOf(e.target); if (!r || !k || (key && k !== key)) return;
      const s = S_(k), side = r.dataset.tfmrow, set = { team: s.tsel, drive: s.dsel, source: s.gsel }[side];
      dragging = { key: k, side, items: set.has(r.dataset.v) ? [...set] : [r.dataset.v] };
      e.dataTransfer.effectAllowed = "copy"; e.dataTransfer.setData("text/plain", dragging.items.join("\n"));
    });
    el.addEventListener("dragend", () => { dragging = null; $$(".tfm-pane.over", el).forEach(p => p.classList.remove("over")); });
    const target = e => { const p = e.target.closest?.("[data-tfmpane]"); if (!p || (key && keyOf(p) !== key)) return null;
      return (dragging && dragging.side !== p.dataset.tfmpane) || (!dragging && p.dataset.tfmpane !== "source" && e.dataTransfer?.types?.includes("Files")) ? p : null; };
    el.addEventListener("dragover", e => { const p = target(e); if (p) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; p.classList.add("over"); } });
    el.addEventListener("dragleave", e => { const p = e.target.closest?.("[data-tfmpane]"); if (p && !p.contains(e.relatedTarget)) p.classList.remove("over"); });
    el.addEventListener("drop", e => {
      const p = target(e); if (!p) return;
      e.preventDefault(); p.classList.remove("over");
      const k = keyOf(p), side = p.dataset.tfmpane;
      if (dragging) { const d = dragging; dragging = null; return copy(k, d.side, d.items, side); }
      const list = [...e.dataTransfer.files]; if (list.length) side === "team" ? uploadTeam(k, list) : uploadDrive(k, list);
    });
  }

  // ---------- My workspace → Files ----------
  async function loadWs(force = false) {
    if (wsLoading) return; wsLoading = true;
    try {
      if (force || !wsTeams || Date.now() - wsAt > 30000) { wsTeams = (await api(`${F}/teams`)).teams; wsAt = Date.now(); }
      const pick = wsTeams.find(x => x.id === wsWid) || wsTeams.find(x => x.netuid === wsSub && x.status !== "closed") || wsTeams.find(x => x.netuid === wsSub) || wsTeams[0];
      if (pick && (force || wsTeam?.comp.id !== pick.id)) wsTeam = await api(`${F}/teams/${pick.id}`);
      if (!pick) wsTeam = null;
    } catch (e) { if (e.status === 403 || e.status === 404) { wsTeams = null; const el = document.querySelector("[data-tfmhost]"); if (el) el.hidden = true; return; } err(e); }
    finally { wsLoading = false; }
    rerender("ws");
  }
  // the host is redrawn with My workspace's Files pane: draw into it and wire it (a new element each time)
  function mountWs(el, netuid) {
    if (!el) return;
    if ($("#nav-teams")?.hidden) { el.hidden = true; return; }
    if (wsSub !== netuid || wsWid == null) { wsSub = netuid; wsWid = pickOf(netuid); }
    el.dataset.tfmhost = "1";
    wire(el, "ws");
    rerender("ws");
    loadWs(Date.now() - wsAt > 30000);
  }

  const holding = () => !!dragging;
  return { html, wire, mountWs, holding };
})();
