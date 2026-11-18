/* DevOps view: AXoR's own CI/CD (admins only). Pipelines build, test and deploy Source hub repositories on this server
   through the AXoR Runner. The list shows each pipeline's last run and what's live; a pipeline has Runs (open one for
   its steps and logs, live while it runs; cancel, roll back to it), App (the deployed container: start, stop, restart,
   logs) and Settings. Changes ask for sudo first; the server and the runner enforce every rule. Polls faster while a
   run is live. */
const DevOps = (() => {
  let d = null, sel = null, pipe = null, run = null, tab = "runs", wired = false, timer = null, openSteps = new Set(), logTail = 300;
  const TABS = [["runs", "Runs", "cycle"], ["app", "App", "server"], ["settings", "Settings", "gear"]];
  const STEP = { source: ["Source", "github"], build: ["Build", "wrench"], test: ["Test", "check"], deploy: ["Deploy", "rocket"] };
  const TRIG = { manual: "Run by hand", push: "New commit", rollback: "Rollback" };
  const CLS = { success: "ok", failed: "bad", running: "run", queued: "wait", pending: "wait" };
  const LABEL = { success: "Success", failed: "Failed", running: "Running", queued: "Queued", pending: "Pending", cancelled: "Cancelled", skipped: "Skipped" };
  const APP = { running: ["Live", "clear"], restarting: ["Restarting", "caution"], exited: ["Stopped", "avoid"], created: ["Created", "new"], dead: ["Dead", "scam"], paused: ["Paused", "caution"] };
  const dot = st => `<span class="ci ci-${CLS[st] || "off"}" title="${esc(LABEL[st] || st)}" role="img" aria-label="${esc(LABEL[st] || st)}"></span>`;
  const pill = st => `<span class="ci-pill ci-${CLS[st] || "off"}">${esc(LABEL[st] || st)}</span>`;
  const busy = r => r && (r.status === "running" || r.status === "queued");
  const sha = s => s ? `<code class="src-sha">${esc(s.slice(0, 7))}</code>` : "";
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const withSudo = fn => Admin.withSudo(fn);
  const bytes = n => n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : n < 1073741824 ? `${fmtNum(n / 1048576, 0)} MB` : `${fmtNum(n / 1073741824, 1)} GB`;
  function dur(a, b) {
    if (!a) return "";
    const s = Math.max(0, Math.round((b || Date.now() / 1000) - a));
    return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`;
  }
  const since = ts => { const s = Date.now() / 1000 - ts; return s < 86400 ? ago(ts) : s < 30 * 86400 ? `${Math.floor(s / 86400)}d ago` : new Date(ts * 1000).toLocaleDateString(); };
  const appUrl = p => p.host_port ? `http://${location.hostname}:${p.host_port}/` : "";
  const cur = () => d?.pipelines.find(p => p.id === sel);
  const empty = (html, cls = "") => `<div class="empty ${cls}">${html}</div>`;

  // ---------- loading ----------
  async function open() {
    wire();
    if (!d) $("#dv").innerHTML = `<h1 class="page">DevOps</h1>${Loading.line("Loading pipelines…")}`;
    await load();
    schedule();
  }
  async function load() {
    try { d = await api("/api/devops"); }
    catch (e) { d = null; $("#dv").innerHTML = `<h1 class="page">DevOps</h1>${empty(esc(e.message))}`; return; }
    if (!d.pipelines.some(p => p.id === sel)) sel = d.pipelines[0]?.id ?? null;
    store.set("devops.sel", sel);
    pipe = sel ? await api(`/api/devops/pipelines/${sel}`).catch(() => pipe) : null;
    if (run) run = await api(`/api/devops/runs/${run.id}`).catch(() => run);
    render();
  }
  function schedule() {
    clearTimeout(timer);
    const hot = d?.pipelines.some(p => busy(p.last)) || busy(run);
    timer = setTimeout(async () => { if ($("#view-devops").hidden) return; await load(); schedule(); }, hot ? 2500 : 15000);
  }
  async function select(id) {
    sel = id; run = null; store.set("devops.sel", sel);
    pipe = null; render();
    pipe = await api(`/api/devops/pipelines/${id}`).catch(e => (err(e), null));
    render();
  }
  async function openRun(id) {
    run = { id, loading: true }; openSteps = new Set(); renderRun();
    run = await api(`/api/devops/runs/${id}`).catch(e => ({ id, error: e.message }));
    (run.steps || []).forEach(s => { if (s.status === "failed" || s.status === "running") openSteps.add(s.seq); });
    renderRun(); renderMain(); schedule();
  }

  // ---------- page ----------
  // polls redraw only the parts whose markup changed, so scroll positions, open steps and hover survive
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; return true; } return false; };
  function render() {
    if (!d) return;
    if (!$("#dv-main")) $("#dv").innerHTML = `<h1 class="page">DevOps</h1>
      <p class="lead">AXoR's own CI/CD: pipelines build, test and deploy your Source hub repositories on this server through the AXoR Runner, with health checks and rollback. Changes ask you to confirm it's you once every 10 minutes and are recorded in the audit log.</p>
      <div id="dv-warn"></div><div class="stats" id="dv-stats"></div>
      <div class="src dv">
        <aside class="card src-repos"><div class="src-side-head"><b>Pipelines</b><span class="spacer"></span>
          <button type="button" class="btn sm primary" data-dv="new" id="dv-new">${icon("plus")}New</button></div>
          <div class="src-list" id="dv-list"></div></aside>
        <div class="card src-main" id="dv-main"></div>
        <aside class="card src-run" id="dv-run" hidden></aside>
      </div>`;
    put($("#dv-warn"), (d.runner.error ? `<div class="sl-err dv-warn">${icon("alert")}<span>${esc(d.runner.error)}</span></div>` : "")
      + (!d.github ? `<div class="sl-err dv-warn">${icon("github")}<span>Connect GitHub and add repositories in the <button type="button" class="linkbtn" data-goto="source">Source hub</button> first: pipelines build from them.</span></div>` : ""));
    put($("#dv-stats"), tiles());
    put($("#dv-list"), side());
    $("#dv-new").disabled = !d.github || !d.repos.length;
    renderMain(); renderRun();
  }
  function tiles() {
    const ps = d.pipelines, liveN = ps.filter(p => p.live?.state === "running").length, w = d.week, done = (w.success || 0) + (w.failed || 0);
    const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
    return [
      tile("cycle", "Pipelines", ps.length, `${ps.filter(p => p.auto).length} on every commit`),
      tile("rocket", "Live apps", `${liveN}/${ps.filter(p => p.port).length}`, `${ps.filter(p => p.port && p.live && p.live.state !== "running").length} stopped`),
      tile("check", "Runs, 7 days", done, done ? `${Math.round((w.success || 0) / done * 100)}% succeeded` : "none finished"),
      tile("server", "Runner", d.runner.error ? "Offline" : esc(d.runner.engine || "?"), d.runner.error ? "see the note above" : `ports ${d.runner.ports?.join("–")} · ≤ ${d.runner.max_memory_mb} MB`),
    ].join("");
  }
  function side() {
    if (!d.pipelines.length) return `<p class="faint small dv-pad">No pipelines yet.</p>`;
    return d.pipelines.map(p => {
      const [lbl, lvl] = p.live ? APP[p.live.state] || [p.live.state, "new"] : [];
      return `<button type="button" class="src-item" data-pipe="${p.id}" aria-current="${p.id === sel}">${p.last ? dot(p.last.status) : `<span class="ci ci-none" aria-hidden="true"></span>`}
        <span class="src-item-main"><b>${esc(p.app)}</b><small class="faint">${esc(p.repo.split("/")[1])} · ${esc(p.branch)}</small></span>
        ${p.port ? (p.live ? `<span class="badge ${lvl} dv-mini">${esc(lbl)}</span>` : "") : `<span class="tag dv-mini" title="Builds and tests, doesn't deploy">CI</span>`}</button>`;
    }).join("");
  }

  function renderMain() {
    const box = $("#dv-main"); if (!box) return;
    const p = cur();
    if (!p) {
      put(box, empty(`<h3>${icon("rocket")}Ship from your repositories</h3><p>A pipeline takes a Source hub repository and branch, builds its Dockerfile, runs your tests in the new image and deploys it on this server on a port of its own, checking its health and rolling back if it fails.</p>
        ${d.github && d.repos.length ? `<button type="button" class="btn primary" data-dv="new">${icon("plus")}New pipeline</button>` : ""}`, "dv-hello"));
      return;
    }
    const v = pipe && pipe.id === p.id ? pipe : null, url = appUrl(p), last = p.last;
    put(box, `<div class="sl-head">${last ? dot(last.status) : ""}<div><b>${esc(p.app)}</b>
        <small class="faint">${esc(p.repo)} · ${esc(p.branch)}${p.context ? ` · ${esc(p.context)}/` : ""}${p.auto ? " · runs on every commit" : ""}</small></div><span class="spacer"></span>
        ${p.live?.state === "running" && url ? `<a class="btn sm" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${icon("external")}Open</a>` : ""}
        <button type="button" class="btn sm primary" data-dv="run" ${busy(last) ? "disabled title='A run is in progress'" : ""}>${icon("play")}Run</button></div>
      <nav class="src-tabs" role="tablist">${TABS.map(([k, label, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${icon(ic)}<span>${label}</span></button>`).join("")}</nav>
      <div class="src-body" id="dv-tab">${!v ? Loading.line("Loading…") : tab === "runs" ? runRows(v) : tab === "app" ? appTab(v) : settingsTab(v)}</div>`);
    if (tab === "app" && v?.port && v.live) loadLogs();  // every poll: the log follows the app
  }

  function runRows(v) {
    if (v.runner_error && !v.runs.length) return empty(esc(v.runner_error));
    if (!v.runs.length) return empty(`No runs yet. <b>Run</b> builds the head of ${esc(v.branch)}${v.auto ? ", and new commits start runs on their own" : ""}.`);
    return `<div class="src-rows">${v.runs.map(r => `<button type="button" class="src-row" data-run="${r.id}" aria-current="${run?.id === r.id}">${dot(r.status)}
      <span class="src-row-main"><b>#${r.number} ${esc(r.message || (r.trigger === "rollback" ? "Rollback" : r.ref))}</b>
        <small class="faint">${esc(TRIG[r.trigger] || r.trigger)}${r.rollback_of ? ` to #${r.rollback_of}` : ""} · ${esc(r.actor || "")}${v.live_run === r.id ? ` · <span class="badge clear dv-mini">${icon("rocket")}live</span>` : ""}
        <span class="dv-pips" aria-hidden="true">${r.steps.map(s => `<i class="ci-${CLS[s.status] || "off"}" title="${esc(STEP[s.name]?.[0] || s.name)}: ${esc(LABEL[s.status] || s.status)}"></i>`).join("")}</span></small></span>
      <span class="src-chip" title="Branch or commit asked for">${icon("branch")}${esc(r.ref || "")}</span>${sha(r.sha)}
      <span class="src-when faint small"><span>${since(r.created)}</span><span>${r.started ? dur(r.started, r.finished) : esc(LABEL[r.status])}</span></span></button>`).join("")}</div>`;
  }

  function appTab(v) {
    if (!v.port) return empty(`This pipeline is CI only: it builds and tests but doesn't deploy. Give it the app's port and a host port in <b>Settings</b> to deploy it.`);
    if (v.runner_error) return empty(esc(v.runner_error));
    if (!v.live) return empty(`Not deployed yet. A successful run deploys it on port ${v.host_port}.`);
    const a = v.live, [lbl, lvl] = APP[a.state] || [a.state, "new"], on = a.state === "running", url = appUrl(v);
    const liveRun = v.runs.find(r => r.id === v.live_run);
    return `<div class="dv-app">
      <div class="dv-facts">
        <div><span>State</span><b><span class="badge ${lvl}">${esc(lbl)}</span> <small class="faint">${esc(a.status)}</small></b></div>
        <div><span>Address</span><b>${on && url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>` : `port ${v.host_port}`} <small class="faint">→ ${v.port} in the container</small></b></div>
        <div><span>Version</span><b>${liveRun ? `#${liveRun.number} ${sha(liveRun.sha)} <small class="faint">${esc(liveRun.message || "")}</small>` : `<code>${esc(a.image)}</code>`}</b></div>
        <div><span>Limits</span><b>${fmtNum(v.memory, 0)} MB · ${v.cpus} CPU${v.volume ? ` · volume at <code>${esc(v.volume)}</code>` : ""}</b></div>
        <div><span>Health check</span><b>${v.health ? `<code>${esc(v.health)}</code> within ${v.health_timeout}s` : `<span class="faint">stays up for 10 seconds</span>`}</b></div>
        <div><span>Container</span><b><code>${esc(a.name)}</code> <small class="faint">since ${since(a.created)}</small></b></div>
      </div>
      <div class="row">${on ? `<button type="button" class="btn sm" data-app="restart">${icon("reset")}Restart</button><button type="button" class="btn sm danger-text" data-app="stop">${icon("stop")}Stop</button>`
                            : `<button type="button" class="btn sm" data-app="start">${icon("play")}Start</button>`}</div>
      <div class="toolbar dv-logbar"><b>Logs</b><span class="spacer"></span><select data-tail aria-label="Lines">${[100, 300, 1000, 5000].map(n => `<option ${n === logTail ? "selected" : ""}>${n}</option>`).join("")}</select>
        <button type="button" class="btn sm" data-dv="logs">${icon("reset")}Refresh</button><button type="button" class="btn sm" data-dv="copy-logs">${icon("copy")}Copy</button></div>
      <pre class="src-log dv-applog" id="dv-applog" tabindex="0">${Loading.line("Reading logs…")}</pre></div>`;
  }
  async function loadLogs() {
    const pre = $("#dv-applog"); if (!pre) return;
    const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8 || !pre.dataset.loaded;
    try {
      const r = await api(`/api/devops/pipelines/${sel}/logs?tail=${logTail}`);
      if (!$("#dv-applog")) return;
      pre.textContent = r.text || "No output yet."; pre.dataset.loaded = 1;
      if (atEnd) pre.scrollTop = pre.scrollHeight;
    } catch (e) { pre.textContent = e.message; }
  }

  function settingsTab(v) {
    const row = (k, val) => `<div><span>${k}</span><b>${val}</b></div>`, none = `<span class="faint">–</span>`;
    const env = Object.entries(v.env);
    return `<div class="dv-app"><div class="dv-facts">
        ${row("Repository", `${esc(v.repo)} <span class="src-chip">${icon("branch")}${esc(v.branch)}</span>`)}
        ${row("Build", `<code>${esc(v.context ? v.context + "/" : "")}${esc(v.dockerfile)}</code> <small class="faint">context: ${esc(v.context || "repository root")}</small>`)}
        ${row("Tests", v.test ? `<code>${esc(v.test)}</code> <small class="faint">up to ${v.test_timeout}s</small>` : `<span class="faint">none: the run only builds${v.port ? " and deploys" : ""}</span>`)}
        ${row("Deploy", v.port ? `container port ${v.port} → host port ${v.host_port}` : `<span class="faint">CI only</span>`)}
        ${v.port ? row("Health check", v.health ? `<code>${esc(v.health)}</code> within ${v.health_timeout}s` : "the container stays up for 10 seconds") : ""}
        ${v.port ? row("Limits", `${fmtNum(v.memory, 0)} MB memory · ${v.cpus} CPU${v.volume ? ` · volume at <code>${esc(v.volume)}</code>` : ""}`) : ""}
        ${row("Triggers", v.auto ? "every new commit on the branch, and by hand" : "by hand")}
        ${row("Variables", env.length ? env.map(([k, x]) => `<code>${esc(k)}=${esc(x)}</code>`).join(" ") : none)}
        ${row("Secrets", v.secrets.length ? v.secrets.map(k => `<code>${esc(k)}=••••</code>`).join(" ") : none)}
        ${row("Created", `${esc(v.created_by || "")} · ${since(v.created)}${v.updated > v.created + 1 ? ` · edited ${since(v.updated)}` : ""}`)}
      </div>
      <div class="row"><button type="button" class="btn sm" data-dv="edit">${icon("edit")}Edit</button><button type="button" class="btn sm danger-text" data-dv="delete">${icon("trash")}Delete pipeline</button></div></div>`;
  }

  function renderRun() {
    const box = $("#dv-run"); if (!box) return;
    $(".src.dv")?.classList.toggle("with-run", !!run);
    box.hidden = !run;
    if (!run) return;
    const close = `<button type="button" class="iconbtn sm" data-dv="close-run" aria-label="Close run">${icon("close")}</button>`;
    if (run.loading || run.error) { put(box, `<div class="sl-head"><b>Run</b><span class="spacer"></span>${close}</div>${run.error ? `<div class="sl-err">${icon("alert")}${esc(run.error)}</div>` : Loading.line("Loading run…")}`); return; }
    const r = run, p = cur(), body = $(".src-run-body", box), keep = body?.scrollTop;
    const logPos = {}; $$(".src-log", box).forEach(el => logPos[el.dataset.seq] = el.scrollTop + el.clientHeight >= el.scrollHeight - 8 ? "end" : el.scrollTop);
    const canBack = r.status === "success" && r.image && p?.port && pipe?.runs?.find(x => x.id === r.id)?.kept && pipe.live_run !== r.id;
    const html = `<div class="sl-head">${dot(r.status)}<div><b>#${r.number} ${esc(r.message || r.ref || "")}</b><small class="faint">${esc(r.app)} · ${esc(TRIG[r.trigger] || r.trigger)}${r.rollback_of ? ` to #${r.rollback_of}` : ""}</small></div><span class="spacer"></span>${close}</div>
      <div class="src-run-body">
      <div class="src-facts small">${pill(r.status)}<span class="src-chip">${icon("branch")}${esc(r.ref || "")}</span>${sha(r.sha)}
        <span class="faint">${r.author ? `${esc(r.author)} · ` : ""}by ${esc(r.actor || "")} · ${since(r.created)}${r.started ? ` · ${busy(r) ? "running " : ""}${dur(r.started, r.finished)}` : ""}</span></div>
      ${r.error && r.status !== "success" ? `<div class="sl-err">${icon("alert")}<span>${esc(r.error)}</span></div>` : ""}
      <div class="row">${busy(r) ? `<button type="button" class="btn sm danger-text" data-dv="cancel">${icon("stop")}Cancel run</button>` : ""}
        ${canBack ? `<button type="button" class="btn sm" data-dv="rollback" title="Deploy this run's image again">${icon("undo")}Roll back to this</button>` : ""}
        ${r.image ? `<span class="faint small"><code>${esc(r.image)}</code></span>` : ""}</div>
      ${r.steps.map(s => `<details class="src-job" data-seq="${s.seq}" ${openSteps.has(s.seq) ? "open" : ""}><summary>${dot(s.status)}${icon(STEP[s.name]?.[1] || "dots")}<b>${esc(STEP[s.name]?.[0] || s.name)}</b><span class="spacer"></span>
          <span class="faint small">${s.started ? dur(s.started, s.finished) : esc(LABEL[s.status] || s.status)}</span></summary>
          ${s.log ? `${s.cut ? `<p class="faint small dv-pad">Showing the end of the log.</p>` : ""}<pre class="src-log" data-seq="${s.seq}">${esc(s.log)}</pre>` : `<p class="faint small dv-pad">${s.status === "pending" ? "Waiting for the steps before it." : s.status === "skipped" ? "Skipped." : "No output yet."}</p>`}</details>`).join("")}
      </div>`;
    if (!put(box, html)) return;
    if (keep) $(".src-run-body", box).scrollTop = keep;
    $$(".src-log", box).forEach(el => { const k = logPos[el.dataset.seq]; el.scrollTop = k === undefined || k === "end" ? el.scrollHeight : k; });
  }

  // ---------- actions ----------
  function runDialog() {
    const p = cur();
    const f = Auth.modal(`<h3>${icon("play")}Run ${esc(p.app)}</h3><p class="muted">Builds ${p.test ? "and tests " : ""}${p.port ? `and deploys it on port ${p.host_port}` : ""} from the head of <b>${esc(p.branch)}</b>, or from the branch, tag or commit you enter.</p>
      <label class="in"><span>Branch, tag or commit <small class="faint">(optional)</small></span><input name="ref" placeholder="${esc(p.branch)}" autocapitalize="none" spellcheck="false" maxlength="250"></label>`,
      async f => {
        const ref = f.elements.ref.value.trim();
        const r = await withSudo(() => api(`/api/devops/pipelines/${p.id}/run`, { method: "POST", body: { ref } }));
        $("#modal").close(); Auth.toast(`Run #${r.number} queued`); tab = "runs"; await load(); openRun(r.id);
      }, { submit: "Run" });
    setTimeout(() => f.elements.ref.focus(), 30);
  }

  async function cancelRun() {
    try { await withSudo(() => api(`/api/devops/runs/${run.id}/cancel`, { method: "POST" })); Auth.toast("Cancelling…"); await load(); }
    catch (e) { err(e); }
  }

  function rollback() {
    const r = run, p = cur();
    Auth.modal(`<h3>${icon("undo")}Roll back ${esc(p.app)}?</h3><p>Deploys run <b>#${r.number}</b> again: ${sha(r.sha)} ${esc(r.message || "")}</p>
      <p class="muted">The running version stops, this image starts on port ${p.host_port} and must pass the health check; if it doesn't, the current version comes back. Nothing is rebuilt.</p>`,
      async () => {
        const n = await withSudo(() => api(`/api/devops/runs/${r.id}/rollback`, { method: "POST" }));
        $("#modal").close(); Auth.toast(`Rollback #${n.number} queued`); await load(); openRun(n.id);
      }, { submit: "Roll back" });
  }

  async function appAct(action) {
    const p = cur();
    const go = async () => {
      const r = await withSudo(() => api(`/api/devops/pipelines/${p.id}/app`, { method: "POST", body: { action } }));
      Auth.toast(`${p.app}: ${r.state}`); await load();
    };
    if (action !== "stop") return go().catch(err);
    Auth.modal(`<h3>${icon("stop")}Stop ${esc(p.app)}?</h3><p class="muted">It stops answering on port ${p.host_port} until you start it again or a run deploys it.</p>`,
      async () => { $("#modal").close(); await go().catch(err); }, { submit: "Stop", danger: true });
  }

  function removePipeline() {
    const p = cur();
    Auth.modal(`<h3>${icon("trash")}Delete ${esc(p.app)}?</h3><p class="muted">Its run history and secrets are deleted${p.port ? `, and its container and images are removed from the server (it stops answering on port ${p.host_port})` : ""}. This can't be undone.</p>
      ${p.volume ? `<label class="chk"><input type="checkbox" name="volume"> Also delete its volume (the data in <code>${esc(p.volume)}</code>)</label>` : ""}`,
      async f => {
        const vol = !!f.elements.volume?.checked;
        await withSudo(() => api(`/api/devops/pipelines/${p.id}?volume=${vol}`, { method: "DELETE" }));
        $("#modal").close(); Auth.toast(`Deleted ${p.app}`); sel = null; run = null; await load();
      }, { submit: "Delete", danger: true });
  }

  // the pipeline form: sudo is asked before it opens, so its prompt can't replace a half-filled form
  async function form(p) {
    try { await withSudo(() => api("/api/devops/sudo", { method: "POST" })); } catch (e) { return err(e); }
    const v = { app: "", repo: d.repos[0] || "", branch: "main", context: "", dockerfile: "Dockerfile", test: "", test_timeout: 600, port: null, host_port: null,
      health: "", health_timeout: 60, memory: 512, cpus: 1, volume: "", env: {}, secrets: [], auto: false, ...(p || {}) };
    const used = new Set(d.pipelines.filter(x => x.id !== p?.id).map(x => x.host_port)), [lo, hi] = d.runner.ports || [9200, 9299];
    const freePort = (() => { for (let n = lo; n <= hi; n++) if (!used.has(n)) return n; return lo; })();
    const deploys = p ? !!v.port : true;
    const secretRow = (k = "", saved = false) => `<div class="dv-secret"><input name="sk" value="${esc(k)}" placeholder="NAME" autocapitalize="characters" spellcheck="false" maxlength="64" ${saved ? "readonly" : ""}>
      <input name="sv" type="password" autocomplete="new-password" placeholder="${saved ? "saved: leave empty to keep" : "value"}"><button type="button" class="iconbtn sm" data-rm aria-label="Remove secret">${icon("close")}</button></div>`;
    const f = Auth.modal(`<h3>${icon("rocket")}${p ? `Edit ${esc(p.app)}` : "New pipeline"}</h3>
      <div class="dv-form">
      <label class="in"><span>App name</span><input name="app" value="${esc(v.app)}" ${p ? "readonly" : "required"} pattern="[a-z][a-z0-9\\-]{0,29}" placeholder="miner-api" autocapitalize="none" spellcheck="false" maxlength="30">
        <small class="faint">Lowercase letters, digits and dashes. Its container is <code>axor-&lt;name&gt;</code>; other apps reach it at <code>http://&lt;name&gt;:&lt;port&gt;</code>.</small></label>
      <div class="dv-two"><label class="in"><span>Repository</span><select name="repo">${d.repos.map(x => `<option ${x === v.repo ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
        <label class="in"><span>Branch</span><input name="branch" value="${esc(v.branch)}" list="dv-branches" required autocapitalize="none" spellcheck="false" maxlength="250"><datalist id="dv-branches"></datalist></label></div>
      <div class="dv-two"><label class="in"><span>Context folder <small class="faint">(optional)</small></span><input name="context" value="${esc(v.context)}" placeholder="repository root" autocapitalize="none" spellcheck="false"></label>
        <label class="in"><span>Dockerfile <small class="faint">(in the context)</small></span><input name="dockerfile" value="${esc(v.dockerfile)}" required autocapitalize="none" spellcheck="false"></label></div>
      <div class="dv-two"><label class="in"><span>Test command <small class="faint">(optional, runs in the new image)</small></span><input name="test" value="${esc(v.test)}" placeholder="python -m pytest -q" autocapitalize="none" spellcheck="false" maxlength="4000"></label>
        <label class="in"><span>Test time limit (s)</span><input name="test_timeout" type="number" min="10" max="7200" value="${v.test_timeout}"></label></div>
      <label class="chk"><input type="checkbox" name="deploys" ${deploys ? "checked" : ""}> Deploy on this server <small class="faint">(otherwise CI only: build and test)</small></label>
      <fieldset class="dv-deploy" ${deploys ? "" : "disabled hidden"}>
        <div class="dv-two"><label class="in"><span>The app listens on port</span><input name="port" type="number" min="1" max="65535" value="${v.port ?? 8000}"></label>
          <label class="in"><span>Published on host port <small class="faint">(${lo}–${hi})</small></span><input name="host_port" type="number" min="${lo}" max="${hi}" value="${v.host_port ?? freePort}"></label></div>
        <div class="dv-two"><label class="in"><span>Health check path <small class="faint">(optional)</small></span><input name="health" value="${esc(v.health)}" placeholder="/health" autocapitalize="none" spellcheck="false"></label>
          <label class="in"><span>Healthy within (s)</span><input name="health_timeout" type="number" min="5" max="600" value="${v.health_timeout}"></label></div>
        <div class="dv-two"><label class="in"><span>Memory (MB)</span><input name="memory" type="number" min="32" max="${d.runner.max_memory_mb || 65536}" value="${v.memory}"></label>
          <label class="in"><span>CPUs</span><input name="cpus" type="number" min="0.1" max="${d.runner.max_cpus || 64}" step="0.1" value="${v.cpus}"></label></div>
        <label class="in"><span>Volume path <small class="faint">(optional: a folder kept across deploys)</small></span><input name="volume" value="${esc(v.volume)}" placeholder="/data" autocapitalize="none" spellcheck="false"></label>
      </fieldset>
      <label class="in"><span>Environment variables <small class="faint">(NAME=value, one per line)</small></span><textarea name="env" rows="3" spellcheck="false" placeholder="LOG_LEVEL=info">${esc(Object.entries(v.env).map(([k, x]) => `${k}=${x}`).join("\n"))}</textarea></label>
      <div class="in"><span>Secrets <small class="faint">(stored encrypted, never shown again, masked in logs)</small></span><div class="dv-secrets">${v.secrets.map(k => secretRow(k, true)).join("")}</div>
        <button type="button" class="btn sm" data-add-secret>${icon("plus")}Add secret</button></div>
      <label class="chk"><input type="checkbox" name="auto" ${v.auto ? "checked" : ""}> Run on every new commit to the branch <small class="faint">(checked every few minutes)</small></label>
      </div>`,
      async f => {
        const el = f.elements, num = n => el[n].value === "" ? null : Number(el[n].value), dep = el.deploys.checked;
        const env = {};
        for (const ln of el.env.value.split("\n").map(x => x.trim()).filter(Boolean)) {
          const i = ln.indexOf("="); if (i < 1) throw new Error(`“${ln}” isn't NAME=value.`);
          env[ln.slice(0, i).trim()] = ln.slice(i + 1);
        }
        const secrets = {};
        $$(".dv-secret", f).forEach(r => { const k = $("[name=sk]", r).value.trim(); if (k) secrets[k] = $("[name=sv]", r).value || null; });
        const body = { app: el.app.value.trim(), repo: el.repo.value, branch: el.branch.value.trim(), context: el.context.value.trim(), dockerfile: el.dockerfile.value.trim(),
          test: el.test.value.trim(), test_timeout: num("test_timeout") || 600, port: dep ? num("port") : null, host_port: dep ? num("host_port") : null,
          health: dep ? el.health.value.trim() : "", health_timeout: num("health_timeout") || 60, memory: num("memory") || 512, cpus: num("cpus") || 1,
          volume: dep ? el.volume.value.trim() : "", env, secrets, auto: el.auto.checked };
        if (!p && !body.app) throw new Error("Name the app.");
        const r = await withSudo(() => api(p ? `/api/devops/pipelines/${p.id}` : "/api/devops/pipelines", { method: p ? "PUT" : "POST", body }));
        $("#modal").close(); Auth.toast(p ? `Saved ${r.app}` : `Created ${r.app}: press Run to build it`);
        sel = r.id; tab = p ? "settings" : "runs"; await load();
      }, { submit: p ? "Save" : "Create" });
    $("#modal").classList.add("dv-wide");
    $("#modal").addEventListener("close", () => $("#modal").classList.remove("dv-wide"), { once: true });
    const el = f.elements;
    el.deploys.onchange = () => { const fs = $(".dv-deploy", f); fs.hidden = fs.disabled = !el.deploys.checked; };
    $("[data-add-secret]", f).onclick = () => { $(".dv-secrets", f).insertAdjacentHTML("beforeend", secretRow()); $(".dv-secret:last-child [name=sk]", f).focus(); };
    $(".dv-secrets", f).onclick = e => e.target.closest("[data-rm]")?.closest(".dv-secret").remove();
    const branches = async () => {
      const [o, n] = el.repo.value.split("/"); if (!n) return;
      const bs = await api(`/api/source/repos/${encodeURIComponent(o)}/${encodeURIComponent(n)}/branches`).catch(() => []);
      $("#dv-branches").innerHTML = (Array.isArray(bs) ? bs : bs.branches || []).map(b => `<option value="${esc(b.name)}">`).join("");
      if (!p && Array.isArray(bs) && bs.find(b => b.default) && !el.branch.dataset.typed) el.branch.value = bs.find(b => b.default).name;
    };
    el.branch.oninput = () => el.branch.dataset.typed = 1;
    el.repo.onchange = branches; branches();
    setTimeout(() => (p ? el.branch : el.app).focus(), 30);
  }

  function wire() {
    if (wired) return; wired = true;
    sel = store.get("devops.sel", null);
    $("#view-devops").addEventListener("click", e => {
      const b = e.target.closest("[data-dv], [data-pipe], [data-tab], [data-run], [data-app], [data-goto]"); if (!b) return;
      if (b.dataset.goto) return setView(b.dataset.goto);
      if (b.dataset.pipe) return select(+b.dataset.pipe);
      if (b.dataset.tab) { tab = b.dataset.tab; return renderMain(); }
      if (b.dataset.run) return openRun(+b.dataset.run);
      if (b.dataset.app) return appAct(b.dataset.app);
      const a = b.dataset.dv;
      if (a === "new") form(null);
      else if (a === "edit") form(pipe);
      else if (a === "run") runDialog();
      else if (a === "delete") removePipeline();
      else if (a === "close-run") { run = null; renderRun(); renderMain(); }
      else if (a === "cancel") cancelRun();
      else if (a === "rollback") rollback();
      else if (a === "logs") loadLogs();
      else if (a === "copy-logs") { navigator.clipboard?.writeText($("#dv-applog").textContent); Auth.toast("Copied"); }
    });
    $("#view-devops").addEventListener("change", e => { if (e.target.matches("[data-tail]")) { logTail = +e.target.value; loadLogs(); } });
    $("#view-devops").addEventListener("toggle", e => {
      const s = e.target.closest?.(".src-job"); if (!s) return;
      s.open ? openSteps.add(+s.dataset.seq) : openSteps.delete(+s.dataset.seq);
    }, true);
  }

  return { open };
})();
