/* Source hub: the team's GitHub repositories and their CI/CD, opened from the sidebar. Browse branches, commits
   with their CI status, the code (folders and files at any branch; secret-looking files stay hidden), open pull requests, workflow runs (jobs, steps, logs) and deployments. Admins connect
   one or more sources (GitHub accounts, organizations or Enterprise servers, each with its own token), add and
   remove repositories several at a time, run workflows with their inputs, re-run or cancel runs and switch
   workflows on or off. The server calls GitHub with one shared cache; this page polls the server, faster while a run is live. */
const Source = (() => {
  let d = { configured: false }, sel = null, tab = "actions";  // the saved choice is read in init(): app.js (store) loads after this file
  let lists = {}, errs = {}, meta = null, filt = { workflow: "", branch: "" }, ref = "", run = null, cpath = "";
  let logs = {}, openJobs = new Set(), wired = false, timer = null, bg = null, ticks = 0, cfgOpen = null;
  const TABS = [["code", "Code", "file"], ["actions", "Actions", "play"], ["commits", "Commits", "commit"], ["pulls", "Pull requests", "pr"],
    ["branches", "Branches", "branch"], ["workflows", "Workflows", "cycle"], ["deployments", "Deployments", "rocket"]];
  const admin = () => d.is_admin;
  const base = () => "/api/source/repos/" + sel.split("/").map(encodeURIComponent).join("/");
  const cur = () => (d.repos || []).find(r => r.repo === sel);

  // ---------- status, time ----------
  // one colour per outcome: green passed, red failed, amber running, blue waiting, grey everything else
  function state(x) {
    if (!x) return null;
    if (typeof x === "string") return x;
    if (x.status && x.status !== "completed") return x.status === "in_progress" ? "running" : "queued";
    return x.conclusion || "neutral";
  }
  const CLS = { success: "ok", failure: "bad", timed_out: "bad", startup_failure: "bad", action_required: "bad", error: "bad",
    running: "run", in_progress: "run", queued: "wait", pending: "wait", waiting: "wait" };
  const LABEL = { success: "Success", failure: "Failed", timed_out: "Timed out", startup_failure: "Startup failure", action_required: "Needs action",
    error: "Error", running: "Running", in_progress: "In progress", queued: "Queued", pending: "Pending", waiting: "Waiting", cancelled: "Cancelled",
    skipped: "Skipped", neutral: "Neutral", inactive: "Inactive", stale: "Stale" };
  const tone = st => CLS[st] || "off";
  const dot = x => { const st = state(x); return st ? `<span class="ci ci-${tone(st)}" title="${esc(LABEL[st] || st)}" role="img" aria-label="${esc(LABEL[st] || st)}"></span>` : `<span class="ci ci-none" aria-hidden="true"></span>`; };
  const pill = x => { const st = state(x); return `<span class="ci-pill ci-${tone(st)}">${esc(LABEL[st] || st || "Unknown")}</span>`; };
  const done = x => x && x.status === "completed";
  const secs = iso => iso ? Date.parse(iso) / 1000 : null;
  function since(iso) {
    const ts = secs(iso); if (!ts) return "";
    const s = Date.now() / 1000 - ts;
    return s < 86400 ? ago(ts) : s < 30 * 86400 ? `${Math.floor(s / 86400)}d ago` : new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }
  function dur(a, b) {
    if (!a) return "";
    const s = Math.max(0, Math.round((b ? secs(b) : Date.now() / 1000) - secs(a)));
    return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`;
  }
  const sha = s => `<code class="src-sha">${esc((s || "").slice(0, 7))}</code>`;
  const first = m => esc((m || "").split("\n")[0]);
  const ext = (url, label, cls = "btn sm") => url ? `<a class="${cls}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${icon("external")}${label}</a>` : "";

  // ---------- sidebar ----------
  async function init() {
    $("#nav-source").hidden = true;
    if (!Auth.me()) return;
    sel = store.get("source.repo", null); tab = store.get("source.tab", "actions");
    if (!TABS.some(([k]) => k === tab)) tab = "actions";
    await load();
    clearInterval(bg); bg = setInterval(() => { if (S.view !== "source") load(); }, 120000);
  }
  async function load() {
    try { d = await api("/api/source"); } catch { return; }
    side();
  }
  function side() {
    $("#nav-source").hidden = !Auth.me() || (!d.configured && !d.is_admin);
    $("#source-lbl").textContent = d.configured ? "Source" : "Connect GitHub";
    const n = (d.repos || []).filter(r => tone(state(r.last_run)) === "bad").length;
    $("#c-source").textContent = n || "";
  }

  // ---------- data ----------
  async function open() {
    wire();
    if (d.repos === undefined) $("#source").innerHTML = Loading.cards(3, "card");
    await load();
    if (!(d.repos || []).some(r => r.repo === sel)) pick((d.repos || [])[0]?.repo || null, false);
    render();
    if (sel) { loadMeta(); loadTab(); }
    clearInterval(timer); ticks = 0;
    timer = setInterval(tick, 5000);
  }
  async function tick() {
    if (S.view !== "source") return clearInterval(timer);
    if (document.visibilityState !== "visible" || !sel) return;
    ticks++;
    if (run && !done(run)) loadRun(run.id, true);
    const live = tab === "actions" && (lists.actions || []).some(r => !done(r));
    if (ticks % (live ? 2 : 6) === 0 && tab !== "code") loadTab(true);  // code doesn't change under you: refresh by hand
    if (ticks % 12 === 0) { await load(); renderRepos(); renderHead(); }
  }
  function pick(repo, reload = true) {
    sel = repo; store.set("source.repo", repo);
    lists = {}; errs = {}; meta = null; run = null; logs = {}; openJobs = new Set(); filt = { workflow: "", branch: "" }; ref = ""; cpath = "";
    if (reload) { render(); loadMeta(); loadTab(); }
  }
  function setTab(t) {
    tab = t; store.set("source.tab", t);
    renderHead(); renderBody(); loadTab();
  }
  async function loadMeta() {
    const at = sel;
    const [workflows, branches] = await Promise.all([api(base() + "/workflows").catch(() => []), api(base() + "/branches").catch(() => [])]);
    if (at !== sel) return;
    meta = { workflows, branches };
    if (["actions", "commits", "code"].includes(tab)) renderBody();
  }
  async function loadTab(quiet = false) {
    if (!sel) return;
    const at = sel, t = tab, q = new URLSearchParams();
    if (t === "actions") { if (filt.workflow) q.set("workflow", filt.workflow); if (filt.branch) q.set("branch", filt.branch); }
    if ((t === "commits" || t === "code") && ref) q.set("ref", ref);
    if (t === "code" && cpath) q.set("path", cpath);
    const path = { code: "/contents", actions: "/runs", commits: "/commits", pulls: "/pulls", branches: "/branches", workflows: "/workflows", deployments: "/deployments" }[t];
    if (!quiet) { lists[t] = undefined; errs[t] = null; renderBody(); }
    try {
      const r = await api(base() + path + (q.toString() ? "?" + q : ""));
      if (at !== sel || t !== tab) return;
      lists[t] = r; errs[t] = null;
      if (t === "workflows" && meta) meta.workflows = r;
    } catch (e) {
      if (at !== sel || t !== tab) return;
      if (!quiet || !lists[t]) errs[t] = e.message;
    }
    renderBody();
  }
  async function openRun(id) {
    run = { id: +id, loading: true }; openJobs = new Set();
    renderRun(); renderBody();
    await loadRun(id);
  }
  async function loadRun(id, quiet = false) {
    const at = sel;
    try {
      const r = await api(`${base()}/runs/${id}`);
      if (at !== sel || run?.id !== +id) return;
      if (!quiet) r.jobs.filter(j => tone(state(j)) === "bad" || !done(j)).forEach(j => openJobs.add(j.id));  // failures and live jobs start open
      run = r;
    } catch (e) { if (run?.id === +id && !quiet) run = { id: +id, error: e.message }; }
    renderRun();
  }
  async function loadLog(job) {
    logs[job] = { loading: true }; renderRun();
    try { logs[job] = await api(`${base()}/jobs/${job}/log`); }
    catch (e) { logs[job] = { error: e.message }; }
    renderRun();
    const pre = $(`#src-log-${job}`); if (pre) pre.scrollTop = pre.scrollHeight;
  }

  // ---------- rendering ----------
  function render() {
    const box = $("#source");
    if (!d.configured) {
      box.innerHTML = `<div class="card chat-empty sl-setup"><span class="av c-violet xl" aria-hidden="true">${icon("github")}</span><h3>Your code and CI/CD in one place</h3>
        <p class="muted">See your GitHub repositories, commits, pull requests and GitHub Actions runs, and run or re-run workflows without leaving AXoR.</p>
        ${d.is_admin ? `<button type="button" class="btn primary" data-src="settings">${icon("plus")}Connect GitHub</button>${help()}` : `<p class="faint">An admin hasn't connected GitHub yet.</p>`}</div>`;
      return;
    }
    if (!(d.repos || []).length) {
      box.innerHTML = `<div class="card chat-empty sl-setup"><span class="av c-violet xl" aria-hidden="true">${icon("repo")}</span><h3>No repositories yet</h3>
        ${d.error ? `<p class="no">${esc(d.error)}</p>` : ""}
        ${d.is_admin ? `<p class="muted">Pick which repositories the Source hub shows.</p><button type="button" class="btn primary" data-src="settings">${icon("plus")}Add repositories</button>` : `<p class="faint">An admin hasn't added any repositories.</p>`}</div>`;
      return;
    }
    box.innerHTML = `<div class="src ${run ? "with-run" : ""}">
      <aside class="card src-repos"><div class="src-side-head"><b>Repositories</b><span class="spacer"></span>
        ${(d.sources || []).length ? `<span class="faint small" title="${esc(d.sources.map(x => `${x.label}: ${x.login ? "@" + x.login : x.error || ""}`).join("\n"))}">${d.sources.length === 1 && d.sources[0].login ? `@${esc(d.sources[0].login)}` : `${d.sources.length} sources`}</span>` : ""}
        ${admin() ? `<button type="button" class="iconbtn sm" data-src="settings" title="Source hub settings" aria-label="Source hub settings">${icon("gear")}</button>` : ""}</div>
        <div id="src-list" class="src-list"></div></aside>
      <div class="card src-main"><div id="src-head"></div><div id="src-body" class="src-body"></div></div>
      <div class="card src-run" id="src-run" ${run ? "" : "hidden"}></div>
    </div>`;
    renderRepos(); renderHead(); renderBody(); renderRun();
  }
  function renderRepos() {
    const box = $("#src-list"); if (!box) return;
    const many = (d.sources || []).length > 1;  // grouped under each source's name
    let last = null;
    box.innerHTML = [...(d.repos || [])].sort((a, b) => many ? (a.source?.label || "").localeCompare(b.source?.label || "") : 0).map(r => {
      const head = many && r.source?.id !== last ? `<div class="src-group faint">${icon("github")}${esc(r.source?.label || "")}</div>` : "";
      last = r.source?.id;
      const [owner, name] = r.repo.split("/");
      return `${head}<button type="button" class="src-item" data-repo="${esc(r.repo)}" aria-current="${r.repo === sel}">
        ${r.error ? `<span class="ci ci-bad" title="${esc(r.error)}"></span>` : dot(r.last_run)}
        <span class="src-item-main"><b>${esc(name)}</b><small class="faint">${esc(owner)}${r.private ? " · private" : ""}${r.pushed ? ` · ${since(r.pushed)}` : ""}</small></span>
        ${r.open_prs ? `<span class="src-n" title="Open pull requests">${icon("pr")}${r.open_prs}${r.open_prs_more ? "+" : ""}</span>` : ""}</button>`;
    }).join("");
  }
  function renderHead() {
    const box = $("#src-head"), r = cur(); if (!box || !r) return;
    box.innerHTML = `<div class="sl-head"><span class="sl-hash">${icon("repo")}</span>
        <div><b>${esc(r.repo)}</b><small class="faint">${esc(r.description || (r.error ? "" : "No description"))}</small></div><span class="spacer"></span>
        ${admin() && !r.error ? `<button type="button" class="btn primary sm" data-src="dispatch">${icon("play")}Run workflow</button>` : ""}
        ${ext(r.url, "GitHub")}</div>
      ${r.error ? `<div class="sl-err">${icon("alert")}${esc(r.error)}</div>` : `<div class="src-facts faint small">
        <span>${icon("branch")}${esc(r.default_branch || "")}</span>${r.language ? `<span>${esc(r.language)}</span>` : ""}
        <span title="Stars">★ ${fmtNum(r.stars || 0, 0)}</span><span title="Forks">${fmtNum(r.forks || 0, 0)} forks</span>
        ${r.private ? `<span class="badge new">Private</span>` : ""}${r.archived ? `<span class="badge caution">Archived</span>` : ""}
        ${r.last_run ? `<span>Last run ${dot(r.last_run)}${since(r.last_run.created)}</span>` : ""}</div>`}
      <nav class="src-tabs" role="tablist">${TABS.map(([k, label, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${icon(ic)}<span>${label}</span></button>`).join("")}</nav>`;
  }
  function renderBody() {
    const box = $("#src-body"); if (!box) return;
    const items = lists[tab];
    const head = tab === "actions" ? runFilters() : tab === "commits" ? commitFilters() : tab === "code" ? codeFilters() : "";
    let body;
    if (errs[tab]) body = `<div class="sl-err">${icon("alert")}${esc(errs[tab])}</div>`;
    else if (items === undefined) body = Loading.line("Loading from GitHub…");
    else body = ({ code: codeView, actions: runRows, commits: commitRows, pulls: pullRows, branches: branchRows, workflows: workflowRows, deployments: deployRows })[tab](items);
    const keep = box.scrollTop;
    box.innerHTML = head + body;
    box.scrollTop = keep;
  }
  const empty = text => `<div class="empty">${text}</div>`;

  function runFilters() {
    const wfs = meta?.workflows || [], brs = meta?.branches || [];
    return `<div class="src-filters">
      <select data-f="workflow" aria-label="Workflow"><option value="">All workflows</option>${wfs.map(w => `<option value="${w.id}" ${String(w.id) === filt.workflow ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select>
      <select data-f="branch" aria-label="Branch"><option value="">All branches</option>${brs.map(b => `<option ${b.name === filt.branch ? "selected" : ""}>${esc(b.name)}</option>`).join("")}${filt.branch && !brs.some(b => b.name === filt.branch) ? `<option selected>${esc(filt.branch)}</option>` : ""}</select>
      <span class="spacer"></span><button type="button" class="iconbtn sm" data-src="refresh" title="Refresh" aria-label="Refresh">${icon("reset")}</button></div>`;
  }
  const runRows = rs => rs.length ? `<div class="src-rows">${rs.map(r => `<button type="button" class="src-row" data-run="${r.id}" aria-current="${run?.id === r.id}">${dot(r)}
      <span class="src-row-main"><b>${esc(r.title || r.name)}</b><small class="faint">${esc(r.name)} #${r.number}${r.attempt > 1 ? ` · attempt ${r.attempt}` : ""} · ${esc(r.event)}${r.actor ? ` · ${esc(r.actor.login)}` : ""}</small></span>
      <span class="src-chip" title="Branch">${icon("branch")}${esc(r.branch || "")}</span>
      <span class="src-when faint small"><span>${since(r.created)}</span><span>${done(r) ? dur(r.started || r.created, r.updated) : dur(r.started || r.created)}</span></span></button>`).join("")}</div>`
    : empty(filt.workflow || filt.branch ? "No runs match these filters." : "No workflow runs yet.");

  function commitFilters() {
    const brs = meta?.branches || [], def = cur()?.default_branch;
    return `<div class="src-filters"><select data-ref aria-label="Branch">${brs.map(b => `<option value="${esc(b.name)}" ${(ref || def) === b.name ? "selected" : ""}>${esc(b.name)}${b.default ? " (default)" : ""}</option>`).join("") || `<option>${esc(ref || def || "")}</option>`}</select>
      <span class="spacer"></span><button type="button" class="iconbtn sm" data-src="refresh" title="Refresh" aria-label="Refresh">${icon("reset")}</button></div>`;
  }
  // ---------- code: folders and files at a branch ----------
  const bytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : `${fmtNum(n / 1048576, 1)} MB`;
  function codeFilters() {
    const parts = cpath ? cpath.split("/") : [], repoName = sel.split("/")[1];
    const crumbs = [`<button type="button" class="linkbtn" data-path="">${esc(repoName)}</button>`,
      ...parts.map((p, i) => i === parts.length - 1 ? `<b>${esc(p)}</b>` : `<button type="button" class="linkbtn" data-path="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`)];
    return commitFilters().replace('<span class="spacer"></span>', `<nav class="src-crumbs" aria-label="Path">${crumbs.join('<span class="faint">/</span>')}</nav><span class="spacer"></span>`);
  }
  const HIDDEN = { secret: "This file looks like a secret (keys, tokens, .env, wallets), so AXoR doesn't show its contents to anyone. Open it on GitHub if you have access.",
    large: "This file is over 1 MB. Open it on GitHub.", binary: "This is a binary file. Open it on GitHub." };
  function fileBody(f, inline = false) {
    if (f.type !== "file") return empty(`This is a ${esc(f.type || "special entry")}. ${ext(f.url, "Open on GitHub")}`);
    if (f.hidden) return `<div class="src-hidden">${icon(f.hidden === "secret" ? "lock" : "file")}<span>${HIDDEN[f.hidden]}</span>${ext(f.url, "GitHub")}</div>`;
    if (/\.(md|markdown)$/i.test(f.name)) return `<div class="md src-md">${Agents.md(f.text)}</div>`;
    const lines = f.text.replace(/\n$/, "").split("\n");
    return `<div class="src-code${inline ? " inline" : ""}"><table><tbody>${lines.map((l, i) => `<tr><td class="ln">${i + 1}</td><td><code>${esc(l) || " "}</code></td></tr>`).join("")}</tbody></table></div>
      ${f.truncated ? `<p class="faint small">Showing the first ${fmtNum(f.text.length, 0)} characters. ${ext(f.url, "Whole file on GitHub")}</p>` : ""}`;
  }
  function codeView(x) {
    if (x.type === "dir") {
      const up = cpath ? `<button type="button" class="src-row src-file" data-path="${esc(cpath.split("/").slice(0, -1).join("/"))}"><span class="src-fico">${icon("left")}</span><span class="src-row-main"><b>..</b></span></button>` : "";
      const rows = x.entries.map(e => `<button type="button" class="src-row src-file" data-path="${esc(e.path)}" ${e.type === "dir" ? "" : `data-file`}>
          <span class="src-fico ${e.type === "dir" ? "dir" : ""}">${icon(e.type === "dir" ? "folder" : e.secret ? "lock" : "file")}</span>
          <span class="src-row-main"><b>${esc(e.name)}</b>${e.secret ? `<small class="faint">hidden: looks like a secret</small>` : ""}</span>
          <span class="faint small num">${e.type === "file" ? bytes(e.size) : e.type === "dir" ? "" : esc(e.type)}</span></button>`).join("");
      return `<div class="src-rows">${up}${rows || empty("This folder is empty.")}</div>
        ${x.readme ? `<div class="src-readme"><div class="src-readme-head">${icon("file")}<b>${esc(x.readme.name)}</b></div>${fileBody(x.readme, true)}</div>` : ""}`;
    }
    return `<div class="src-filehead">${icon("file")}<b>${esc(x.path)}</b><span class="faint small">${bytes(x.size)}${x.text != null ? ` · ${fmtNum(x.text.replace(/\n$/, "").split("\n").length, 0)} lines` : ""}</span><span class="spacer"></span>
        ${x.text != null ? `<button type="button" class="btn sm" data-copy-file>${icon("copy")}Copy</button>` : ""}${ext(x.url, "GitHub")}</div>${fileBody(x)}`;
  }

  const avatar = (url, name) => url ? `<img class="src-av" src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="${esc((name || "?")[0].toUpperCase())}">` : `<span class="src-av">${esc((name || "?")[0].toUpperCase())}</span>`;
  const commitRows = cs => cs.length ? `<div class="src-rows">${cs.map(c => `<div class="src-row">
      ${c.ci ? `<button type="button" class="src-ci" data-runs-sha="${esc(c.sha)}" title="${c.runs} workflow run${c.runs === 1 ? "" : "s"}: show this branch's runs">${dot(c.ci)}</button>` : `<span class="ci ci-none" title="No CI runs"></span>`}
      <span class="src-row-main"><b>${first(c.message)}</b><small class="faint">${avatar(c.avatar, c.author)}${esc(c.author)} committed ${since(c.date)}</small></span>
      ${ext(c.url, sha(c.sha), "src-chip link")}</div>`).join("")}</div>` : empty("No commits on this branch.");

  const pullRows = ps => ps.length ? `<div class="src-rows">${ps.map(p => `<div class="src-row">
      <span class="src-pr ${p.draft ? "draft" : ""}" title="${p.draft ? "Draft" : "Open"}">${icon("pr")}</span>
      <span class="src-row-main"><b><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.title)}</a> <span class="faint">#${p.number}</span></b>
        <small class="faint">${p.author ? `${avatar(p.author.avatar, p.author.login)}${esc(p.author.login)} · ` : ""}${esc(p.head)} → ${esc(p.base)} · updated ${since(p.updated)}${p.draft ? " · draft" : ""}</small>
        ${p.labels.length ? `<span class="src-labels">${p.labels.map(l => `<span>${esc(l)}</span>`).join("")}</span>` : ""}</span>
      <button type="button" class="btn sm" data-runs-branch="${esc(p.head)}">${icon("play")}Checks</button></div>`).join("")}</div>` : empty("No open pull requests.");

  const branchRows = bs => bs.length ? `<div class="src-rows">${bs.map(b => `<div class="src-row">
      <span class="src-pr">${icon("branch")}</span>
      <span class="src-row-main"><b>${esc(b.name)} ${b.default ? `<span class="badge new">Default</span>` : ""}${b.protected ? ` <span class="badge clear">${icon("lock")}Protected</span>` : ""}</b><small class="faint">${sha(b.sha)}</small></span>
      <span class="src-acts"><button type="button" class="btn sm" data-commits-ref="${esc(b.name)}">${icon("commit")}Commits</button>
      <button type="button" class="btn sm" data-runs-branch="${esc(b.name)}">${icon("play")}Runs</button>
      ${admin() ? `<button type="button" class="btn sm" data-dispatch-ref="${esc(b.name)}" title="Run a workflow on ${esc(b.name)}">${icon("rocket")}Run</button>` : ""}</span></div>`).join("")}</div>` : empty("No branches.");

  const workflowRows = ws => ws.length ? `<div class="src-rows">${ws.map(w => {
      const on = w.state === "active";
      return `<div class="src-row">
      <span class="src-pr ${on ? "" : "draft"}">${icon("cycle")}</span>
      <span class="src-row-main"><b>${esc(w.name)} ${on ? "" : `<span class="badge caution">${w.state === "disabled_manually" ? "Disabled" : esc(w.state.replace(/_/g, " "))}</span>`}</b><small class="faint"><code>${esc(w.path)}</code></small></span>
      <span class="src-acts"><button type="button" class="btn sm" data-runs-wf="${w.id}">Runs</button>
      ${admin() && on ? `<button type="button" class="btn sm" data-dispatch-wf="${w.id}">${icon("play")}Run</button>` : ""}
      ${admin() && w.path.startsWith(".github/") ? `<button type="button" class="btn sm ${on ? "danger-text" : ""}" data-wf-toggle="${w.id}" data-on="${on}">${on ? "Disable" : "Enable"}</button>` : ""}</span></div>`;
    }).join("")}</div>` : empty("This repository has no GitHub Actions workflows.");

  const deployRows = ds => ds.length ? `<div class="src-rows">${ds.map(x => `<div class="src-row">${dot(x.state)}
      <span class="src-row-main"><b>${esc(x.environment)} ${pill(x.state)}</b><small class="faint">${x.creator ? `${esc(x.creator.login)} · ` : ""}${since(x.created)}</small></span>
      <span class="src-chip">${icon("branch")}${esc(x.ref)}</span>${sha(x.sha)}${ext(x.url, "Open")}</div>`).join("")}</div>` : empty("No deployments. Workflows that use <code>environment:</code> show up here.");

  function renderRun() {
    const box = $("#src-run"); if (!box) return;
    $(".src")?.classList.toggle("with-run", !!run);
    box.hidden = !run;
    if (!run) return;
    const close = `<button type="button" class="iconbtn sm" data-src="close-run" aria-label="Close run">${icon("close")}</button>`;
    if (run.loading || run.error) { box.innerHTML = `<div class="sl-head"><b>Run</b><span class="spacer"></span>${close}</div>${run.error ? `<div class="sl-err">${icon("alert")}${esc(run.error)}</div>` : Loading.line("Loading run…")}`; return; }
    const r = run, failed = done(r) && tone(state(r)) === "bad";
    const keep = $(".src-run-body", box)?.scrollTop;
    box.innerHTML = `<div class="sl-head">${dot(r)}<div><b>${esc(r.title || r.name)}</b><small class="faint">${esc(r.name)} #${r.number}${r.attempt > 1 ? ` · attempt ${r.attempt}` : ""}</small></div><span class="spacer"></span>${close}</div>
      <div class="src-run-body">
      <div class="src-facts small">${pill(r)}<span class="src-chip">${icon("branch")}${esc(r.branch || "")}</span>${sha(r.sha)}
        <span class="faint">${esc(r.event)}${r.actor ? ` by ${esc(r.actor.login)}` : ""} · ${since(r.created)} · ${done(r) ? dur(r.started || r.created, r.updated) : "running " + dur(r.started || r.created)}</span></div>
      <div class="row">${admin() ? (done(r) ? `<button type="button" class="btn sm" data-src="rerun">${icon("reset")}Re-run all jobs</button>${failed ? `<button type="button" class="btn sm" data-src="rerun-failed">${icon("reset")}Re-run failed jobs</button>` : ""}`
        : `<button type="button" class="btn sm danger-text" data-src="cancel">${icon("stop")}Cancel run</button>`) : ""}${ext(r.url, "Open on GitHub")}</div>
      ${r.jobs.map(j => {
        const lg = logs[j.id];
        return `<details class="src-job" data-job="${j.id}" ${openJobs.has(j.id) ? "open" : ""}><summary>${dot(j)}<b>${esc(j.name)}</b><span class="spacer"></span><span class="faint small">${j.started ? (done(j) ? dur(j.started, j.completed) : dur(j.started)) : LABEL[state(j)] || ""}</span></summary>
          <ol class="src-steps">${j.steps.map(s => `<li>${dot(s)}<span>${esc(s.name)}</span><span class="faint small">${s.started && s.completed ? dur(s.started, s.completed) : ""}</span></li>`).join("") || `<li class="faint">Waiting for a runner…</li>`}</ol>
          <div class="src-logbar">${done(j) ? `<button type="button" class="btn sm" data-log="${j.id}">${icon("file")}${lg && !lg.error ? "Reload log" : "Show log"}</button>` : `<span class="faint small">The log is available when the job finishes.</span>`}${ext(j.url, "Job on GitHub")}</div>
          ${lg ? lg.loading ? Loading.line("Downloading log…") : lg.error ? `<p class="no small">${esc(lg.error)}</p>` : `${lg.truncated ? `<p class="faint small">Showing the end of the log.</p>` : ""}<pre class="src-log" id="src-log-${j.id}">${logHtml(lg.text)}</pre>` : ""}</details>`;
      }).join("") || `<p class="faint">No jobs yet.</p>`}</div>`;
    if (keep) $(".src-run-body", box).scrollTop = keep;
  }
  // Actions log markers: ##[group]/##[endgroup], ##[error], ##[warning], ##[command]
  const logHtml = text => text.split("\n").map(l => {
    const m = l.match(/^##\[(group|endgroup|error|warning|notice|command|debug|section)\](.*)$/);
    if (!m) return esc(l);
    if (m[1] === "endgroup") return "";
    return `<span class="lg-${m[1]}">${esc(m[2])}</span>`;
  }).join("\n");

  // ---------- CI/CD actions (admins) ----------
  async function runAction(action) {
    const label = { rerun: "Re-running all jobs", "rerun-failed": "Re-running failed jobs", cancel: "Cancelling the run" }[action];
    try {
      await api(`${base()}/runs/${run.id}/${action}`, { method: "POST" });
      toast(label);
      setTimeout(() => { if (run) loadRun(run.id, true); loadTab(true); }, 2500);
    } catch (e) { toast(e.message); }
  }
  async function dispatch(preset = {}) {
    if (!meta) await loadMeta();
    const wfs = (meta?.workflows || []).filter(w => w.state === "active");
    if (!wfs.length) return toast("This repository has no active workflows.");
    const r = cur();
    const f = Auth.modal(`<div class="src-dlg"><h3>${icon("play")}Run workflow</h3><p class="muted">${esc(sel)}</p>
      <label class="in"><span>Workflow</span><select name="workflow">${wfs.map(w => `<option value="${w.id}" ${String(w.id) === String(preset.workflow) ? "selected" : ""}>${esc(w.name)}</option>`).join("")}</select></label>
      <label class="in"><span>Branch or tag</span><input name="ref" list="src-refs" value="${esc(preset.ref || r?.default_branch || "")}" autocomplete="off" spellcheck="false" required>
        <datalist id="src-refs">${(meta.branches || []).map(b => `<option value="${esc(b.name)}">`).join("")}</datalist></label>
      <div id="src-inputs"></div>
      <p class="fine">Runs on GitHub Actions with the connected token and is recorded in the audit log.</p></div>`,
      async f => {
        const form = f._form; if (!form?.dispatchable) throw new Error("This workflow can't be run by hand: it has no workflow_dispatch trigger.");
        const inputs = {};
        for (const i of form.inputs) {
          const el = f.elements["in_" + i.name]; if (!el) continue;
          if (i.type === "boolean") inputs[i.name] = el.checked;
          else if (el.value.trim() !== "") inputs[i.name] = el.value.trim();
          else if (i.required) throw new Error(`Fill in "${i.name}".`);
        }
        await api(base() + "/dispatch", { method: "POST", body: { workflow: f.elements.workflow.value, ref: f.elements.ref.value.trim(), inputs } });
        $("#modal").close();
        toast("Workflow started. It shows up under Actions in a few seconds");
        filt = { workflow: f.elements.workflow.value, branch: "" };
        if (tab !== "actions") setTab("actions");
        setTimeout(() => loadTab(true), 3000); setTimeout(() => loadTab(true), 8000);
      }, { submit: "Run workflow" });
    const submit = $("button[type=submit]", f);
    let seq = 0;
    const inputsFor = async () => {
      const my = ++seq, box = $("#src-inputs", f);
      box.innerHTML = Loading.line("Reading the workflow's inputs…"); submit.disabled = true;
      let form;
      try { form = await api(`${base()}/workflows/${f.elements.workflow.value}/form?ref=${encodeURIComponent(f.elements.ref.value.trim())}`); }
      catch (e) { if (my === seq) box.innerHTML = `<p class="no small">${esc(e.message)}</p>`; return; }
      if (my !== seq) return;
      f._form = form; submit.disabled = !form.dispatchable;
      box.innerHTML = !form.dispatchable ? `<p class="no small">${icon("alert")}This workflow has no <code>workflow_dispatch</code> trigger, so it can't be run by hand.</p>`
        : form.inputs.map(i => {
          const id = "in_" + esc(i.name), hint = i.description ? `<small class="hint">${esc(i.description)}</small>` : "";
          const name = `${esc(i.name)}${i.required ? "" : ` <em class="opt">optional</em>`}`;
          if (i.type === "boolean") return `<label class="chk"><input type="checkbox" name="${id}" ${i.default === true || i.default === "true" ? "checked" : ""}> ${esc(i.description || i.name)}</label>`;
          if (i.type === "choice") return `<label class="in"><span>${name}</span><select name="${id}">${i.options.map(o => `<option ${String(i.default) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>${hint}</label>`;
          return `<label class="in"><span>${name}</span><input name="${id}" ${i.type === "number" ? `inputmode="decimal"` : ""} value="${esc(i.default ?? "")}" autocomplete="off" spellcheck="false">${hint}</label>`;
        }).join("");
    };
    f.elements.workflow.onchange = inputsFor;
    f.elements.ref.onchange = inputsFor;
    inputsFor();
  }
  async function toggleWorkflow(id, on) {
    try {
      await api(`${base()}/workflows/${id}/${on ? "disable" : "enable"}`, { method: "PUT" });
      toast(on ? "Workflow disabled" : "Workflow enabled");
      loadTab(true); loadMeta();
    } catch (e) { toast(e.message); }
  }

  // ---------- admin settings ----------
  const help = () => `<details class="sl-help"><summary>How to create the GitHub token</summary><ol>
      <li>Go to <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">github.com → Settings → Developer settings → Fine-grained tokens</a> and <b>Generate new token</b>. For an organization's repositories, pick the organization as the resource owner.</li>
      <li>Choose the repositories the hub should show.</li>
      <li>Repository permissions: <b>Actions</b> read and write (to run, re-run and cancel), <b>Contents</b>, <b>Pull requests</b> and <b>Deployments</b> read-only. Metadata is added automatically.</li>
      <li>A classic token works too, with the <code>repo</code> and <code>workflow</code> scopes. Paste the token here, then add repositories.</li></ol></details>`;
  // Settings: one card per source (account, server, token, its repositories) and a form to add another source.
  // Repositories are added and removed several at a time; adding or deleting a source and changing a token need sudo.
  async function settings() {
    let c;
    try { c = await api("/api/source/config"); } catch (e) { return toast(e.message); }
    if (!c.sources.some(x => x.id === cfgOpen)) cfgOpen = c.sources[0]?.id || null;
    const total = c.sources.reduce((n, x) => n + x.repos.length, 0);
    const host = x => x.default_api ? "github.com" : (() => { try { return new URL(x.api).host; } catch { return x.api; } })();
    const card = x => {
      const a = x.account || {}, on = x.id === cfgOpen;
      return `<details class="src-source" data-sid="${esc(x.id)}" ${on ? "open" : ""}><summary>${icon("github")}<b>${esc(x.label)}</b>
          <span class="faint small">${a.login ? `@${esc(a.login)}` : ""} · ${esc(host(x))} · ${x.repos.length} repo${x.repos.length === 1 ? "" : "s"}</span>${a.error ? `<span class="badge avoid">${icon("alert")}Error</span>` : ""}</summary>
        <div class="src-source-body">
          ${a.error ? `<div class="sl-status">${icon("alert")}<span class="no">${esc(a.error)}</span></div>` : a.missing?.length ? `<div class="sl-status">${icon("alert")}<span class="no">The classic token is missing: ${a.missing.map(esc).join(", ")}</span></div>` : ""}
          <div class="src-meta faint small"><span>Token ${esc(x.token || "none")}${x.token_source === "env" ? " (server environment)" : ""}</span>
            <span class="spacer"></span><button type="button" class="linkbtn" data-s-rename="${esc(x.id)}">Rename</button><button type="button" class="linkbtn" data-s-token="${esc(x.id)}">Replace token</button>
            <button type="button" class="linkbtn danger-text" data-s-del="${esc(x.id)}">Delete source</button></div>
          <div class="field"><span class="lbl">Repositories <span class="faint">(${x.repos.length})</span></span>
            ${x.repos.length ? `<ul class="src-cfg">${x.repos.map(r => `<li><label class="src-chk"><input type="checkbox" data-s-sel="${esc(r)}"><span>${esc(r)}</span></label></li>`).join("")}</ul>
              <div class="row src-bulk"><label class="chk sm"><input type="checkbox" data-s-all="${esc(x.id)}"> Select all</label><span class="spacer"></span><button type="button" class="btn sm" data-s-rm="${esc(x.id)}" disabled>${icon("close")}Remove selected</button></div>` : `<p class="faint small">No repositories from this source yet.</p>`}</div>
          <div class="field"><span class="lbl">Add repositories</span>
            <div class="search"><span>${icon("search")}</span><input type="search" data-s-q placeholder="Filter the repositories this token can see…" autocomplete="off"></div>
            <ul class="src-cfg src-avail" data-s-avail="${esc(x.id)}"><li class="faint">${on && !a.error ? "Loading…" : "Open to load."}</li></ul>
            <textarea rows="2" data-s-extra placeholder="Or type them: owner/name or GitHub URLs, one per line or comma-separated"></textarea>
            <div class="row src-bulk"><span class="faint small" data-s-count></span><span class="spacer"></span><button type="button" class="btn sm primary" data-s-add="${esc(x.id)}">${icon("plus")}Add selected</button></div></div>
        </div></details>`;
    };
    const f = Auth.modal(`<div class="src-dlg"><h3>${icon("github")}Source hub</h3>
      <p class="muted small">${c.sources.length ? `${c.sources.length} source${c.sources.length === 1 ? "" : "s"}, ${total} of ${c.max_repos} repositories. ` : ""}Each source is a GitHub account, organization or Enterprise server with its own token. Everyone signed in can browse the repositories, private ones included; only admins can run, re-run or cancel workflows.</p>
      <div class="src-sources">${c.sources.map(card).join("") || `<p class="faint">No sources yet. Add the first one below.</p>`}</div>
      ${c.sources.length < c.max_sources ? `<details class="src-new" ${c.sources.length ? "" : "open"}><summary>${icon("plus")}<b>Add a source</b></summary>
        <div class="src-source-body">
          <label class="in"><span>Name <span class="faint">(optional)</span></span><input name="label" maxlength="60" placeholder="e.g. Our org, Personal, Enterprise" autocomplete="off"></label>
          <label class="in"><span>GitHub token</span><div class="pw"><input name="token" type="password" autocomplete="off" spellcheck="false" placeholder="github_pat_… or ghp_…"><button type="button" class="eye" aria-label="Show token"></button></div>
            <small class="hint">Checked with GitHub before saving, stored encrypted and never sent back to browsers.</small></label>
          <label class="in"><span>Server <span class="faint">(GitHub Enterprise only)</span></span><input name="api" placeholder="Leave empty for github.com, or https://host/api/v3" autocomplete="off" spellcheck="false"></label>
          ${help()}
          <div class="row end"><button type="button" class="btn primary sm" data-s-new>${icon("plus")}Connect source</button></div></div></details>` : `<p class="faint small">The hub holds up to ${c.max_sources} sources.</p>`}</div>`,
      async () => $("#modal").close(), { submit: "Done" });
    $("[data-close]", f)?.remove();  // one way out: Done
    const err = $(".err", f), fail = e => { if (e.message !== "cancelled") err.textContent = e.message; };
    const again = async (msg, sid) => { if (msg) toast(msg); if (sid) cfgOpen = sid; await refresh(); settings(); };
    $$(".eye", f).forEach(b => b.addEventListener("click", () => { const i = b.previousElementSibling; i.type = i.type === "password" ? "text" : "password"; }));

    // the repositories each source's token can see, loaded when its card is open
    const avail = {};
    const fillAvail = async sid => {
      const ul = $(`[data-s-avail="${sid}"]`, f); if (!ul || avail[sid]) return;
      avail[sid] = "loading";
      try { avail[sid] = await api(`/api/source/config/sources/${sid}/available`); }
      catch (e) { avail[sid] = null; ul.innerHTML = `<li class="no">${esc(e.message)}</li>`; return; }
      const xs = avail[sid].filter(x => !x.listed);
      ul.innerHTML = xs.map(x => `<li data-hay="${esc(x.repo.toLowerCase())}"><label class="src-chk"><input type="checkbox" data-s-pick="${esc(x.repo)}"><span>${esc(x.repo)}</span></label><span class="faint small">${x.private ? "private" : "public"}</span></li>`).join("")
        || `<li class="faint">Every repository this token can see is already in the hub.</li>`;
    };
    $$("details.src-source", f).forEach(dt => {
      dt.addEventListener("toggle", () => { if (dt.open) { cfgOpen = dt.dataset.sid; fillAvail(dt.dataset.sid); } });
      if (dt.open) fillAvail(dt.dataset.sid);
      const sync = () => {  // button labels follow what's ticked
        const n = $$("[data-s-sel]:checked", dt).length, rm = $("[data-s-rm]", dt);
        if (rm) { rm.disabled = !n; rm.innerHTML = `${icon("close")}Remove ${n ? n : "selected"}`; }
        const k = $$("[data-s-pick]:checked", dt).length + $("[data-s-extra]", dt).value.split(/[\s,]+/).filter(Boolean).length;
        $("[data-s-count]", dt).textContent = k ? `${k} to add` : "";
        $("[data-s-add]", dt).innerHTML = `${icon("plus")}Add ${k || "selected"}`;
      };
      dt.addEventListener("change", e => { if (e.target.matches("[data-s-all]")) $$("[data-s-sel]", dt).forEach(b => b.checked = e.target.checked); sync(); });
      $("[data-s-extra]", dt).addEventListener("input", sync);
      $("[data-s-q]", dt).addEventListener("input", e => { const q = e.target.value.trim().toLowerCase(); $$("[data-hay]", dt).forEach(li => li.hidden = !!q && !li.dataset.hay.includes(q)); });
    });

    f.addEventListener("click", async e => {
      const t = e.target, b = sel => t.closest(sel);
      let x;
      if ((x = b("[data-s-add]"))) {
        const sid = x.dataset.sAdd, dt = x.closest("details");
        const repos = [...$$("[data-s-pick]:checked", dt).map(i => i.dataset.sPick), ...$("[data-s-extra]", dt).value.split(/[\s,]+/).filter(Boolean)];
        if (!repos.length) return fail(new Error("Tick repositories or type some first."));
        x.classList.add("loading"); x.disabled = true;
        try {
          const r = await api(`/api/source/config/sources/${sid}/repos`, { method: "POST", body: { repos } });
          if (r.errors.length) toast(`${r.errors.length} not added: ${r.errors.map(e => `${e.repo} (${e.error})`).join("; ")}`.slice(0, 300));
          return again(r.added.length ? `Added ${r.added.length} repositor${r.added.length === 1 ? "y" : "ies"}` : "", sid);
        } catch (e) { x.classList.remove("loading"); x.disabled = false; return fail(e); }
      }
      if ((x = b("[data-s-rm]"))) {
        const dt = x.closest("details"), repos = $$("[data-s-sel]:checked", dt).map(i => i.dataset.sSel);
        if (!await UI.confirm({ title: `Remove ${repos.length} repositor${repos.length === 1 ? "y" : "ies"} from the hub?`, body: "People here stop seeing them. Nothing changes on GitHub, and you can add them again.",
          items: repos.map(esc), ok: "Remove", icon: "repo" })) return;
        try { const r = await api("/api/source/config/repos/remove", { method: "POST", body: { repos } }); return again(`Removed ${r.removed.length} repositor${r.removed.length === 1 ? "y" : "ies"}`, x.dataset.sRm); }
        catch (e) { return fail(e); }
      }
      if ((x = b("[data-s-del]"))) {
        const src = c.sources.find(y => y.id === x.dataset.sDel);
        let done = false;
        await UI.confirm({ title: `Delete the source “${esc(src.label)}”?`, body: `Its saved token is deleted and its ${src.repos.length} repositor${src.repos.length === 1 ? "y leaves" : "ies leave"} the hub for everyone. Nothing changes on GitHub.`,
          typed: src.label, run: async () => { await Admin.withSudo(() => api(`/api/source/config/sources/${src.id}`, { method: "DELETE" })); done = true; } });
        if (done) return again(`Deleted ${src.label}`);
        return;
      }
      if ((x = b("[data-s-token]")) || (x = b("[data-s-rename]"))) {
        const src = c.sources.find(y => y.id === (x.dataset.sToken || x.dataset.sRename)), tokenMode = !!x.dataset.sToken;
        const v = prompt(tokenMode ? `New GitHub token for “${src.label}” (checked before saving):` : `Name for this source:`, tokenMode ? "" : src.label);
        if (!v?.trim()) return;
        try { await Admin.withSudo(() => api(`/api/source/config/sources/${src.id}`, { method: "PATCH", body: tokenMode ? { token: v.trim() } : { label: v.trim() } })); return again(tokenMode ? "Token replaced" : "Renamed", src.id); }
        catch (e) { return fail(e); }
      }
      if ((x = b("[data-s-new]"))) {
        const token = f.elements.token.value.trim();
        if (!token) return fail(new Error("Paste a GitHub token."));
        x.classList.add("loading"); x.disabled = true;
        try {
          const r = await Admin.withSudo(() => api("/api/source/config/sources", { method: "POST", body: { label: f.elements.label.value, token, api: f.elements.api.value } }));
          return again("Source connected: now add its repositories", r.added);
        } catch (e) { x.classList.remove("loading"); x.disabled = false; return fail(e); }
      }
    });
  }
  async function refresh() {
    await load();
    if (!(d.repos || []).some(r => r.repo === sel)) pick((d.repos || [])[0]?.repo || null, false);
    if (S.view === "source") { render(); if (sel) { loadMeta(); loadTab(); } }
  }

  function wire() {
    if (wired) return; wired = true;
    const root = $("#view-source");
    root.addEventListener("click", e => {
      const t = e.target, g = sel => t.closest(sel);
      const a = g("[data-src]")?.dataset.src;
      if (a === "settings") return settings();
      if (a === "dispatch") return dispatch();
      if (a === "refresh") return loadTab();
      if (a === "close-run") { run = null; renderRun(); return renderBody(); }
      if (["rerun", "rerun-failed", "cancel"].includes(a)) return runAction(a);
      let x;
      if ((x = g("[data-repo]"))) return x.dataset.repo !== sel && pick(x.dataset.repo);
      if ((x = g("[data-tab]"))) return x.dataset.tab !== tab && setTab(x.dataset.tab);
      if ((x = g("[data-run]"))) return openRun(x.dataset.run);
      if ((x = g("[data-log]"))) return loadLog(+x.dataset.log);
      if ((x = g("[data-runs-branch]"))) { filt = { workflow: "", branch: x.dataset.runsBranch }; return setTab("actions"); }
      if ((x = g("[data-runs-wf]"))) { filt = { workflow: x.dataset.runsWf, branch: "" }; return setTab("actions"); }
      if ((x = g("[data-runs-sha]"))) { filt = { workflow: "", branch: ref || cur()?.default_branch || "" }; return setTab("actions"); }  // a commit's CI dot
      if ((x = g("[data-path]"))) { cpath = x.dataset.path; return loadTab(); }
      if ((x = g("[data-copy-file]"))) { navigator.clipboard.writeText(lists.code?.text || "").then(() => toast("Copied"), () => toast("Couldn't copy")); return; }
      if ((x = g("[data-commits-ref]"))) { ref = x.dataset.commitsRef; return setTab("commits"); }
      if ((x = g("[data-dispatch-ref]"))) return dispatch({ ref: x.dataset.dispatchRef });
      if ((x = g("[data-dispatch-wf]"))) return dispatch({ workflow: x.dataset.dispatchWf });
      if ((x = g("[data-wf-toggle]"))) return toggleWorkflow(x.dataset.wfToggle, x.dataset.on === "true");
    });
    root.addEventListener("change", e => {
      const f = e.target.dataset.f;
      if (f) { filt[f] = e.target.value; return loadTab(); }
      if (e.target.matches("[data-ref]")) { ref = e.target.value; loadTab(); }
    });
    // remember which jobs are expanded across the run panel's live refreshes
    root.addEventListener("toggle", e => {
      const j = e.target.closest?.("[data-job]"); if (!j) return;
      j.open ? openJobs.add(+j.dataset.job) : openJobs.delete(+j.dataset.job);
    }, true);
  }

  return { init, open, load, settings };
})();
