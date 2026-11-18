/* Company (company.py): your AI agent company (#company, sidebar → Workspace). You're the founder and final authority.
   - Overview: brief the leadership (CEO, COO, CTO, CFO, Governance propose a project for a goal), the organization explorer
     (divisions → projects → teams), what waits for you and the latest activity.
   - Projects: each project's workspace: objective, budget, tasks; a task's team is proposed by the team builder from the agents'
     skills and workload, you start it, the members report to the lead, the lead writes the deliverable, the evaluator scores it.
   - Agents: the directory and each agent's workspace (company-agents.js): chat, instructions, memory, tools, contract, history.
   - Approvals: every action that needs you, bound to the exact artifact and parameters; approve, ask for changes or reject, then
     execute (once). No "approve all".
   - Knowledge, Audit (append-only), Settings (name, model, which actions may be proposed at all).
   It polls every 15 seconds while it shows (every 2.5 while a team works or the leadership briefs) and redraws only what changed. */
const Company = (() => {
  const C = "/api/company";
  const TONE = { ok: "clear", run: "new", warn: "caution", bad: "scam", none: "muted" };
  const chip = (cls, text, ic = "") => `<span class="badge ${TONE[cls] || "muted"}">${ic ? icon(ic) : ""}${text}</span>`;
  const TASK = { pending: ["none", "To staff"], proposed: ["warn", "Team proposed"], running: ["run", "Working"], evaluating: ["run", "Evaluating"],
                 done: ["ok", "Done"], failed: ["bad", "Failed"], cancelled: ["none", "Cancelled"] };
  const APPR = { pending: ["warn", "Waiting for you"], approved: ["run", "Approved: not run yet"], consumed: ["ok", "Executed"], rejected: ["bad", "Rejected"],
                 changes: ["warn", "Changes asked"], expired: ["none", "Expired"] };
  const PROJ = { planning: "none", active: "ok", paused: "warn", done: "ok", archived: "none" };
  const AG = { available: "ok", paused: "warn", disabled: "bad" };
  const SCOPE = { company: ["ok", "globe", "Company"], division: ["run", "layers", "Division"], project: ["none", "folder", "Project"], restricted: ["bad", "lock", "Restricted"] };
  const VERD = { pass: "ok", revise: "warn", fail: "bad" };
  let d = null, failed = "", tab = null, on = false, wired = false, timer = null, loading = false;
  let proj = null, openTask = {}, taskInfo = {}, apprFilter = "open", kFilter = "all", older = [];
  const root = () => document.getElementById("company");
  const err = e => e && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const short = h => h ? `<code class="co-hash" title="SHA-256 ${esc(h)}">${esc(h.slice(0, 12))}</code>` : "";
  const A = id => d?.agents.find(a => a.id === id);
  const DIV = id => d?.divisions.find(x => x.id === id);
  const P = id => d?.projects.find(x => x.id === id);
  const who = s => { const [t, n] = String(s || "").split(":"); return t === "agent" ? `${icon("bot")}${esc(n)}` : t === "user" ? `${icon("users")}${esc(n)} (you)` : esc(s || ""); };
  const busyNow = () => d && (d.counts.running > 0 || d.brief?.status === "running");
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- data ----------
  function open() {
    on = true; wire();
    if (tab === null) { try { tab = store.get("co.tab", "overview"); } catch { tab = "overview"; } }
    if (!d) put(root(), Loading.line("Opening your company…"));
    load();
  }
  function stop() { on = false; clearTimeout(timer); }
  async function load() {
    if (loading) return; loading = true;
    try { d = await api(C); failed = ""; } catch (e) { failed = e.message; } finally { loading = false; }
    if (d) for (const tid of Object.keys(openTask)) { const t = d.tasks.find(x => x.id === +tid); if (t && (["running", "evaluating"].includes(t.status) || !taskInfo[tid])) fetchTask(+tid, false); }
    badge();
    if (!typing()) render();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!on) return;
    timer = setTimeout(() => { if (!on || $("#view-company")?.hidden || document.visibilityState !== "visible") return schedule(); load(); }, busyNow() ? 2500 : 15000);
  }
  const typing = () => !!document.activeElement?.closest?.("#company form, #company textarea, #company input[type=text], #company input[type=number], #company select");
  function badge() { const el = $("#c-company"); if (el) el.textContent = d?.counts.pending || ""; }
  function take(r) { if (r?.company) d = r; badge(); render(); schedule(); }
  async function fetchTask(tid, draw = true) {
    try { taskInfo[tid] = await api(`${C}/tasks/${tid}`); } catch (e) { err(e); }
    if (draw && !typing()) render();
  }
  const fetchAgent = aid => CompanyAgents.refresh(aid);

  // ---------- the page ----------
  function render() {
    const el = root(); if (!el) return;
    if (!d) { put(el, failed ? `<div class="empty">${esc(failed)} <button type="button" class="linkbtn" data-co="reload">Try again</button></div>` : Loading.line("Opening your company…")); return; }
    const n = d.counts;
    const tabs = [["overview", "dash", "Overview", ""], ["projects", "folder", "Projects", d.projects.filter(p => p.status !== "archived").length],
                  ["agents", "bot", "Agents", d.agents.length], ["approvals", "shield", "Approvals", n.pending ? `<span class="hq-n alert" title="Waiting for you">${n.pending}</span>` : ""],
                  ["knowledge", "book", "Knowledge", d.knowledge.length || ""], ["audit", "list", "Audit", ""], ["settings", "gear", "Settings", ""]];
    const body = { projects, agents, approvals, knowledge, audit, settings }[tab] || overview;
    put(el, `<div class="co">
      <header class="co-top"><div><h1>${icon("group")}${esc(d.company.name)}</h1>
        <p class="faint">One organization of divisions, projects, teams and agents. Agents propose; you approve what matters, and nothing outside AXoR runs without you.</p></div>
        <div class="co-top-act">${chip("none", "Hybrid organization", "layers")}${chip("none", "Managed autonomy", "shield")}</div></header>
      <div class="stats co-kpis">
        ${tile("layers", "Divisions", n.divisions, `${d.divisions.filter(x => x.status === "active").length} active`)}
        ${tile("folder", "Active projects", n.active_projects, `${d.projects.length} in all`)}
        ${tile("bot", "Agents at work", n.active_agents, `of ${n.agents} registered`)}
        ${tile("cycle", "Running tasks", n.running, `${d.tasks.filter(t => t.status === "done").length} done`)}
        ${tile("shield", "Pending approvals", n.pending, "only you decide", n.pending ? "t-warn" : "")}
        ${tile("coins", "Tokens (7 days)", tok(d.finance.week), `${tok(d.finance.today)} today`)}</div>
      <nav class="co-tabs" role="tablist" aria-label="Company">${tabs.map(([id, ic, l, c]) => `<button type="button" role="tab" class="co-tab ${tab === id ? "on" : ""}" aria-selected="${tab === id}" data-cotab="${id}">${icon(ic)}${l}${c !== "" && c != null ? ` <span class="faint">${c}</span>` : ""}</button>`).join("")}</nav>
      <div class="co-body">${body()}</div></div>`);
  }
  const tile = (ic, l, v, sub, cls = "") => `<div class="stat ${cls}"><div class="label">${icon(ic)}${l}</div><div class="value num">${v}</div><div class="sub">${sub}</div></div>`;

  // ---------- overview ----------
  function overview() {
    const b = d.brief, o = b?.out, going = b?.status === "running";
    const waiting = d.approvals.filter(a => a.status === "pending");
    return `<section class="card co-brief">
        <div class="co-h"><h2>${icon("sparkle")}Brief the leadership</h2><span class="faint small">CEO · COO · CTO · CFO · Governance</span></div>
        <form class="co-ask" data-coform="brief"><label class="in"><span class="sr">A goal for the company</span>
          <textarea name="goal" rows="2" maxlength="2000" placeholder="A goal, e.g. Build a validator dashboard for Handshake name auctions" ${going ? "disabled" : ""}></textarea></label>
          <button type="submit" class="btn sm primary" ${going || !d.company.model_id ? "disabled" : ""} title="${d.company.model_id ? "One model call: the leadership proposes a project" : "Connect a model in Agents → Models"}">${icon(going ? "cycle" : "send")}${going ? "Thinking…" : "Brief them"}</button></form>
        ${going ? `<p class="co-going">${icon("cycle")}The leadership is reading the goal and the company's projects…</p>` : ""}
        ${b?.status === "failed" ? `<p class="co-fail">${icon("alert")}The brief failed: ${esc(b.error || "no reason given")}</p>` : ""}
        ${o && b.status === "done" ? briefOut(b, o) : ""}</section>
      <section class="card co-org"><div class="co-h"><h2>${icon("layers")}Organization</h2>
          <details class="co-add"><summary class="btn sm">${icon("plus")}Division</summary>
            <form class="co-form" data-coform="division"><label class="in"><span>Name</span><input type="text" name="name" maxlength="60" required placeholder="e.g. AI Research Division"></label>
              <label class="in"><span>What it does</span><input type="text" name="description" maxlength="400"></label><button type="submit" class="btn sm primary">Add</button></form></details></div>
        <div class="co-tree"><div class="co-node co-root">${icon("group")}<b>${esc(d.company.name)}</b><span class="faint small">Company HQ · leadership: ${d.agents.filter(a => a.category === "leadership").map(a => esc(a.title.replace(" Agent", ""))).join(" · ")}</span></div>
          <div class="co-divs">${d.divisions.map(division).join("")}</div>
          <div class="co-node co-shared">${icon("users")}<b>Shared services</b><span class="faint small">${d.agents.filter(a => a.category === "shared").map(a => esc(a.title)).join(" · ")}</span></div></div></section>
      <div class="co-two">
        <section class="card"><div class="co-h"><h2>${icon("shield")}Waiting for you</h2>${waiting.length ? `<button type="button" class="btn sm" data-cotab="approvals">Approval center</button>` : ""}</div>
          ${waiting.length ? `<ul class="co-list">${waiting.slice(0, 6).map(a => `<li><button type="button" class="linkbtn" data-cotab="approvals">${esc(d.catalog.actions[a.action_type]?.label || a.action_type)}: ${esc(a.title)}</button><span class="faint small">${who(a.requested_by)} · ${P(a.project_id) ? esc(P(a.project_id).name) : ""}</span></li>`).join("")}</ul>`
            : `<p class="faint">Nothing waits for you.</p>`}</section>
        <section class="card"><div class="co-h"><h2>${icon("list")}Latest activity</h2><button type="button" class="btn sm" data-cotab="audit">Audit log</button></div>
          <ul class="co-list">${d.audit.slice(0, 8).map(r => `<li><span>${actor(r)} ${esc(act(r))}</span><time class="faint small num">${when(r.ts)}</time></li>`).join("") || `<li class="faint">Nothing yet.</li>`}</ul></section></div>`;
  }
  function briefOut(b, o) {
    const dv = d.divisions.find(x => (x.key || `custom-${x.name}`) === o.division);
    return `<div class="co-out"><p class="co-head"><b>${esc(o.headline || "")}</b> <span class="faint small">${when(b.finished || b.ts)} · ${tok(b.tokens)} tokens</span></p>
      <div class="co-board">
        <div><h4>${icon("target")}CEO</h4><p>${esc(o.ceo)}</p></div>
        <div><h4>${icon("folder")}COO: ${esc(o.project?.name || "")}</h4><p>${esc(o.project?.objective || "")}</p>${o.project?.success ? `<p class="faint small"><b>Success:</b> ${esc(o.project.success)}</p>` : ""}<p class="faint small">${dv ? esc(dv.name) : ""}</p></div>
        <div><h4>${icon("chip")}CTO</h4><p>${esc(o.cto)}</p></div>
        <div><h4>${icon("coins")}CFO</h4><p>${tok(o.cfo?.budget)} tokens. ${esc(o.cfo?.note || "")}</p></div>
        <div><h4>${icon("shield")}Governance</h4><p>${(o.governance?.approvals || []).map(x => esc(d.catalog.actions[x]?.label || x)).join(", ") || "No approvals expected."}</p>${(o.governance?.risks || []).length ? `<ul>${o.governance.risks.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</div></div>
      <ol class="co-ptasks">${(o.tasks || []).map(t => `<li><b>${esc(t.title)}</b> <span class="faint small">${esc(t.kind)} · P${t.priority}</span><br><span class="small">${esc(t.description)}</span> ${t.skills.map(s => `<span class="co-skill">${esc(s)}</span>`).join("")}</li>`).join("")}</ol>
      <div class="row">${b.project_id ? `<button type="button" class="btn sm" data-coproj="${b.project_id}">${icon("check")}Created: open the project</button>`
        : `<button type="button" class="btn sm primary" data-cobrief="${b.id}">${icon("plus")}Create this project</button>`}</div></div>`;
  }
  function division(x) {
    const ps = d.projects.filter(p => p.division_id === x.id && p.status !== "archived");
    return `<div class="co-div"><div class="co-node">${icon("layers")}<b>${esc(x.name)}</b>${chip(x.status === "active" ? "ok" : "none", esc(x.status))}</div>
      <p class="faint small">${esc(x.description || "")}</p>
      <ul class="co-projs">${ps.map(p => { const teams = d.teams.filter(t => t.project_id === p.id && t.status === "active");
        return `<li><button type="button" class="linkbtn" data-coproj="${p.id}">${icon(p.link ? "link" : "folder")}${esc(p.name)}</button> ${chip(PROJ[p.status], esc(p.status))}
          ${p.linked ? `<span class="faint small">${plural(p.linked.teams, "competition team")} · ${plural(p.linked.agents, "agent")}</span>` : `<span class="faint small">${p.done}/${p.tasks} tasks${teams.length ? ` · ${plural(teams.length, "team")} at work` : ""}</span>`}</li>`; }).join("")
        || `<li class="faint small">No project yet.</li>`}</ul>
      <p class="faint small">${plural(x.agents, "agent")} in the division</p></div>`;
  }
  const actor = r => r.actor_type === "agent" ? `<b>${icon("bot")}${esc(r.actor)}</b>` : r.actor_type === "user" ? `<b>${icon("users")}${esc(r.actor)}</b>` : `<b class="faint">${esc(r.actor)}</b>`;
  const ACT = { "company.created": "created the company", "company.settings": "changed the settings", "division.created": "added a division", "project.created": "created a project",
                "project.changed": "changed a project", "task.created": "added a task", "task.cancelled": "cancelled a task", "task.done": "finished a task", "task.failed": "a task failed",
                "task.stopped": "stopped a task", "team.proposed": "proposed a team", "team.started": "started a team", "team.released": "released a team",
                "message.sent": "reported to the lead", "artifact.created": "wrote a deliverable", "artifact.evaluated": "evaluated a deliverable", "artifact.edited": "edited a deliverable",
                "approval.requested": "asked for approval", "approval.approved": "approved", "approval.rejected": "rejected", "approval.changes": "asked for changes",
                "approval.expired": "an approval request expired", "approval.refused": "refused to ask for approval", "execution.done": "executed an approved action",
                "execution.handed_off": "authorized an action to carry out by hand", "execution.failed": "an execution failed", "execution.refused": "the gateway refused an execution",
                "agent.registered": "registered an agent", "agent.changed": "changed an agent's contract", "knowledge.added": "added knowledge", "knowledge.deleted": "deleted knowledge",
                "brief.asked": "briefed the leadership", "brief.proposed": "proposed a project", "agent.configured": "configured an agent", "agent.archived": "archived an agent",
                "agent.assigned": "assigned an agent to a project", "agent.unassigned": "unassigned an agent", "agent.handoff": "handed an answer to an agent" };
  const act = r => `${ACT[r.action] || r.action}${r.target_type ? ` (${r.target_type} ${r.target_id})` : ""}`;

  // ---------- projects ----------
  function projects() {
    const live = d.projects.filter(p => p.status !== "archived");
    if (proj == null || !P(proj)) proj = live.find(p => !p.link)?.id ?? live[0]?.id ?? null;
    const p = P(proj);
    return `<div class="co-split">
      <aside class="co-side card">${d.divisions.map(x => { const ps = d.projects.filter(q => q.division_id === x.id);
        return `<div class="co-sgroup"><h4>${esc(x.name)}</h4>${ps.map(q => `<button type="button" class="co-sitem ${q.id === proj ? "on" : ""}" data-coproj="${q.id}">${icon(q.link ? "link" : "folder")}<span>${esc(q.name)}</span>${q.running ? `<span class="badge new">${q.running}</span>` : ""}${q.status === "archived" ? `<span class="faint small">archived</span>` : ""}</button>`).join("") || `<p class="faint small">No project.</p>`}</div>`; }).join("")}
        <details class="co-add" ${live.length ? "" : "open"}><summary class="btn sm">${icon("plus")}New project</summary>${newProject()}</details></aside>
      <div class="co-main">${p ? project(p) : `<section class="card"><p class="faint">Create a project to start.</p></section>`}</div></div>`;
  }
  function newProject() {
    return `<form class="co-form" data-coform="project">
      <label class="in"><span>Division</span><select name="division_id" data-cotpl>${d.divisions.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
      <label class="in"><span>Template</span><select name="template"><option value="">None: I'll add tasks</option>${Object.entries(d.catalog.templates).map(([k, ts]) => ts.map(t => `<option value="${esc(t.name)}" data-div="${esc(k)}">${esc(t.name)}</option>`).join("")).join("")}</select></label>
      <label class="in"><span>Name</span><input type="text" name="name" maxlength="80" required></label>
      <label class="in"><span>Objective</span><textarea name="objective" rows="2" maxlength="1500" required></textarea></label>
      <label class="in"><span>Success criteria</span><input type="text" name="success" maxlength="800" placeholder="How you'll know it worked"></label>
      <label class="in"><span>Token budget</span><select name="budget">${d.catalog.budgets.map((b, i) => `<option value="${b}" ${i === 1 ? "selected" : ""}>${tok(b)}</option>`).join("")}</select></label>
      <button type="submit" class="btn sm primary">${icon("plus")}Create</button></form>`;
  }
  function project(p) {
    const dv = DIV(p.division_id), pct = p.budget ? Math.min(100, Math.round(100 * p.spent / p.budget)) : 0;
    const tasks = d.tasks.filter(t => t.project_id === p.id).sort((a, b) => a.priority - b.priority || a.id - b.id);
    const arts = d.artifacts.filter(a => a.project_id === p.id);
    const know = d.knowledge.filter(k => k.project_id === p.id);
    return `<section class="card co-proj">
        <div class="co-h"><div><h2>${icon(p.link ? "link" : "folder")}${esc(p.name)}</h2><p class="faint small">${dv ? esc(dv.name) : ""} · created ${when(p.created)}</p></div>
          <label class="in co-status"><span class="sr">Status</span><select data-costatus="${p.id}">${["planning", "active", "paused", "done", "archived"].map(s => `<option ${s === p.status ? "selected" : ""}>${s}</option>`).join("")}</select></label></div>
        <p>${esc(p.objective)}</p>${p.success ? `<p class="small"><b>Success:</b> ${esc(p.success)}</p>` : ""}
        <div class="co-budget"><div class="co-bar"><i style="width:${pct}%" class="${pct >= 90 ? "hot" : ""}"></i></div><span class="small num">${tok(p.spent)} of ${tok(p.budget)} tokens</span>
          <select class="co-bsel" data-cobudget="${p.id}" aria-label="Budget">${[...new Set([...d.catalog.budgets, p.budget])].sort((a, b) => a - b).map(b => `<option value="${b}" ${b === p.budget ? "selected" : ""}>${tok(b)}</option>`).join("")}</select></div>
        ${p.linked ? `<div class="co-linked"><p>${icon("link")}<b>Linked to My subnets.</b> Its campaigns and competition teams keep running there; these numbers are read live.</p>
          <div class="co-mini"><div><span>Campaigns</span><b>${p.linked.campaigns}</b></div><div><span>Competition teams</span><b>${p.linked.teams}</b></div><div><span>Agents on</span><b>${p.linked.agents}</b></div><div><span>Done (7 d)</span><b>${p.linked.done_week}</b></div></div>
          <div class="row"><button type="button" class="btn sm" data-cogo="mining">${icon("trophy")}My subnets</button><button type="button" class="btn sm" data-cogo="teams">${icon("users")}Competition teams</button><button type="button" class="btn sm" data-cogo="portfolio">${icon("target")}Portfolio</button></div></div>` : ""}
      </section>
      ${p.link ? "" : `<section class="card"><div class="co-h"><h2>${icon("list")}Tasks</h2>
          <details class="co-add"><summary class="btn sm">${icon("plus")}Task</summary>${newTask(p)}</details></div>
        <div class="co-tasks">${tasks.map(task).join("") || `<p class="faint">No task yet. Add one: name the skills it needs and the team builder finds the team.</p>`}</div></section>`}
      ${arts.length ? `<section class="card"><div class="co-h"><h2>${icon("doc")}Deliverables</h2></div><div class="co-arts">${arts.map(artifactRow).join("")}</div></section>` : ""}
      <section class="card"><div class="co-h"><h2>${icon("book")}Project knowledge</h2><span class="faint small">Only this project's teams read it, until you approve sharing it wider</span></div>
        ${know.length ? `<ul class="co-know">${know.map(knowItem).join("")}</ul>` : `<p class="faint small">Lessons from finished tasks land here.</p>`}
        <details class="co-add"><summary class="btn sm">${icon("plus")}Add knowledge</summary><form class="co-form" data-coform="knowledge" data-project="${p.id}">
          <label class="in"><span>Title</span><input type="text" name="title" maxlength="160" required></label><label class="in"><span>What to know</span><textarea name="body" rows="3" maxlength="6000" required></textarea></label>
          <label class="co-check"><input type="checkbox" name="restricted"> Restricted: never in an agent's prompt, never shared</label><button type="submit" class="btn sm primary">Add</button></form></details></section>`;
  }
  function newTask(p) {
    return `<form class="co-form" data-coform="task" data-project="${p.id}">
      <label class="in"><span>Title</span><input type="text" name="title" maxlength="160" required></label>
      <label class="in"><span>What's wanted</span><textarea name="description" rows="3" maxlength="3000"></textarea></label>
      <fieldset class="co-skills"><legend>Skills it needs</legend>${Object.entries(d.catalog.skills).map(([k, v]) => `<label title="${esc(v)}"><input type="checkbox" name="skills" value="${k}"><span>${esc(k.replace(/_/g, " "))}</span></label>`).join("")}</fieldset>
      <div class="row"><label class="in"><span>Kind</span><select name="kind"><option value="report">Report</option><option value="code">Code draft</option></select></label>
        <label class="in"><span>Priority</span><select name="priority">${[1, 2, 3, 4, 5].map(n => `<option ${n === 3 ? "selected" : ""}>${n}</option>`).join("")}</select></label></div>
      <button type="submit" class="btn sm primary">${icon("plus")}Add task</button></form>`;
  }
  function task(t) {
    const [sc, sl] = TASK[t.status] || ["none", esc(t.status)], team = d.teams.find(x => x.id === t.team_id), o = openTask[t.id];
    const can = ["pending", "proposed", "failed"].includes(t.status), live = ["running", "evaluating"].includes(t.status);
    return `<article class="co-task s-${t.status}">
      <div class="co-task-h"><div><b>${esc(t.title)}</b> <span class="faint small">P${t.priority} · ${t.kind === "code" ? "code draft" : "report"}${t.tokens ? ` · ${tok(t.tokens)} tokens` : ""}</span>
          <div>${t.skills.map(s => `<span class="co-skill">${esc(s)}</span>`).join("")}</div></div>${chip(sc, sl, live ? "cycle" : "")}</div>
      ${t.description ? `<p class="small">${esc(t.description)}</p>` : ""}
      ${t.error ? `<p class="co-fail small">${icon("alert")}${esc(t.error)}</p>` : ""}
      ${team && team.status !== "discarded" ? teamBox(team, t) : ""}
      <div class="row co-act">
        ${can ? `<label class="in co-kind"><span class="sr">Team type</span><select data-cokind="${t.id}"><option value="dynamic">Dynamic team</option><option value="taskforce">Task force</option><option value="permanent">Permanent team</option></select></label>
          <button type="button" class="btn sm" data-cobuild="${t.id}">${icon("users")}${team?.status === "proposed" ? "Build again" : "Propose a team"}</button>` : ""}
        ${team?.status === "proposed" && t.status === "proposed" ? `<button type="button" class="btn sm primary" data-costart="${team.id}" ${d.company.model_id ? "" : "disabled title=\"Connect a model in Agents → Models\""}>${icon("play")}Start the team</button>` : ""}
        ${team && team.status === "active" && !live ? `<button type="button" class="btn sm" data-corelease="${team.id}">${icon("stop")}Release the team</button>` : ""}
        ${!["done", "failed", "cancelled"].includes(t.status) ? `<button type="button" class="btn sm ghost" data-cocancel="${t.id}">Cancel</button>` : ""}
        ${t.status !== "pending" ? `<button type="button" class="btn sm ghost" data-cotask="${t.id}">${icon(o ? "up" : "down")}${o ? "Hide the work" : "Show the work"}</button>` : ""}</div>
      ${o ? taskWork(t) : ""}</article>`;
  }
  function teamBox(team, t) {
    const pr = team.proposal || {}, ev = A(team.evaluator_id);
    return `<div class="co-team ${team.status}"><div class="co-team-h"><b>${icon("users")}${esc({ dynamic: "Dynamic team", taskforce: "Task force", permanent: "Permanent team" }[team.kind] || team.kind)}</b>
        <span class="faint small">${team.status === "proposed" ? "proposed by the team builder" : team.status === "active" ? "at work" : `released ${when(team.released)}`}</span></div>
      <ul class="co-members">${[...team.members].sort((a, b) => (b.role === "lead") - (a.role === "lead")).map(m => { const a = A(m.agent_id);
        return `<li><button type="button" class="co-ag" data-coagent="${m.agent_id}">${m.role === "lead" ? icon("star") : icon("bot")}<b>${esc(a?.name || "?")}</b> <span class="faint">${esc(a?.title || "")}</span></button><span class="faint small">${esc(m.why || "")}</span></li>`; }).join("")}
        ${ev ? `<li class="co-ev"><button type="button" class="co-ag" data-coagent="${ev.id}">${icon("check")}<b>${esc(ev.name)}</b> <span class="faint">${esc(ev.title)}</span></button><span class="faint small">Evaluates, not on the team</span></li>` : ""}</ul>
      ${(pr.uncovered || []).length ? `<p class="co-warn small">${icon("alert")}No available agent covers: ${pr.uncovered.map(esc).join(", ")}.</p>` : ""}
      ${(pr.busy || []).length && team.status === "proposed" ? `<p class="faint small">At their workload limit: ${pr.busy.map(esc).join(", ")}.</p>` : ""}</div>`;
  }
  function taskWork(t) {
    const w = taskInfo[t.id];
    if (!w) return `<div class="co-work">${Loading.line("Reading the team's work…")}</div>`;
    return `<div class="co-work"><ol class="co-msgs">${w.messages.map(m => { const p = m.payload, f = A(m.from_agent), to = A(m.to_agent);
        return `<li class="co-msg t-${esc(m.type)}"><div class="co-msg-h"><b>${icon(m.type === "deliverable" ? "doc" : "bot")}${esc(f?.name || "?")}</b> <span class="faint small">${esc(f?.title || "")}${to ? ` → ${esc(to.name)}` : ""} · ${when(m.ts)}</span>
            ${chip(m.type === "risk" ? "warn" : m.type === "deliverable" ? "ok" : "none", esc(m.type))}${p.confidence != null ? `<span class="faint small">confidence ${p.confidence}</span>` : ""}${p.risk ? chip(p.risk === "high" ? "bad" : p.risk === "medium" ? "warn" : "none", `risk ${esc(p.risk)}`) : ""}</div>
          <p>${esc(p.summary || "")}</p>
          ${p.body ? `<details><summary class="small">The work</summary><div class="md">${Agents.md(p.body)}</div></details>` : ""}
          ${(p.evidence || []).length ? `<p class="faint small"><b>Evidence:</b> ${p.evidence.map(esc).join(" · ")}</p>` : ""}
          ${p.next_action ? `<p class="faint small"><b>Next:</b> ${esc(p.next_action)}</p>` : ""}
          ${p.action && p.action.type !== "none" ? `<p class="small">${icon("shield")}<b>Proposes:</b> ${esc(d.catalog.actions[p.action.type]?.label || p.action.type)}: ${esc(p.action.title || "")}</p>` : ""}</li>`; }).join("")
        || `<li class="faint small">${["running", "evaluating"].includes(t.status) ? "The first member is working…" : "No messages."}</li>`}</ol>
      ${w.artifacts.map(a => artifact(a, true)).join("")}</div>`;
  }
  function artifactRow(a) {
    const e = a.eval;
    return `<div class="co-art-row"><div><b>${icon("doc")}${esc(a.title)}</b> <span class="faint small">${when(a.created)} · ${short(a.sha)}</span>${a.status === "released" ? chip("ok", "Released", "check") : ""}
        <p class="small faint">${esc(a.summary || "")}</p></div>
      <div class="co-art-side">${e ? chip(VERD[e.verdict], `${e.score}/100 · ${esc(e.verdict)}`) + (e.stale ? chip("warn", "edited since") : "") : chip("none", "not evaluated")}
        ${a.task_id ? `<button type="button" class="btn sm ghost" data-cotask="${a.task_id}">Open</button>` : `<button type="button" class="btn sm ghost" data-coagent="${a.by_agent}" data-cawtab="files" title="Saved from ${esc(A(a.by_agent)?.name || "an agent")}'s chat">Open</button>`}</div></div>`;
  }
  function artifact(a, full) {
    const e = a.eval, editing = openTask[`edit${a.id}`];
    return `<div class="co-art"><div class="co-h"><h4>${icon("doc")}${esc(a.title)} ${a.status === "released" ? chip("ok", "Released", "check") : ""}</h4><span class="faint small">SHA-256 ${short(a.sha)}</span></div>
      ${editing ? `<form class="co-form" data-coform="edit" data-art="${a.id}"><textarea name="body" rows="14" maxlength="60000">${esc(a.body)}</textarea>
          <p class="faint small">Saving changes the hash: approvals asked for the old text can't run any more.</p><div class="row"><button type="submit" class="btn sm primary">Save</button><button type="button" class="btn sm ghost" data-coedit="${a.id}">Cancel</button></div></form>`
        : `<div class="md co-md">${Agents.md(a.body || "")}</div>`}
      ${e ? `<div class="co-eval v-${esc(e.verdict)}"><p>${chip(VERD[e.verdict], `${e.score}/100 · ${esc(e.verdict)}`, "check")} <b>${esc(A(e.evaluator_id)?.name || "Evaluator")}</b> ${esc(e.summary || "")}${e.stale ? ` ${chip("warn", "the text changed after this evaluation")}` : ""}</p>
          ${(e.strengths || []).length ? `<p class="small"><b>Strengths:</b> ${e.strengths.map(esc).join(" · ")}</p>` : ""}${(e.issues || []).length ? `<p class="small"><b>Issues:</b> ${e.issues.map(esc).join(" · ")}</p>` : ""}
          <p class="faint small">${e.evidence_ok ? "Claims rest on the evidence given." : "Some claims aren't backed by the evidence given."}</p></div>` : ""}
      ${full && a.status !== "released" ? `<div class="row co-act">${editing ? "" : `<button type="button" class="btn sm ghost" data-coedit="${a.id}">${icon("edit")}Edit</button>`}
          <label class="in"><span class="sr">Action</span><select data-coreqsel="${a.id}">${Object.entries(d.catalog.actions).filter(([k]) => !["knowledge_promotion", "permission_change"].includes(k) && !(d.company.settings.actions_off || []).includes(k)).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("")}</select></label>
          <button type="button" class="btn sm" data-coreq="${a.id}">${icon("shield")}Ask for approval</button></div>` : ""}</div>`;
  }
  function knowItem(k) {
    const [c, ic, l] = SCOPE[k.scope] || SCOPE.project, pending = d.approvals.some(a => a.artifact_kind === "knowledge" && a.artifact_id === k.id && ["pending", "approved"].includes(a.status));
    return `<li><div class="co-kh">${chip(c, l, ic)}<b>${esc(k.title)}</b>${P(k.project_id) && tab === "knowledge" ? `<span class="faint small">${esc(P(k.project_id).name)}</span>` : ""}<span class="faint small">${k.source === "you" ? "by you" : esc(k.source || "")}</span></div>
      ${k.body !== k.title ? `<p class="small">${esc(k.body)}</p>` : ""}
      <div class="row co-act">${k.scope === "project" || k.scope === "division" ? (pending ? `<span class="faint small">${icon("clock")}A request to share it waits in Approvals</span>`
        : `${k.scope === "project" ? `<button type="button" class="btn sm ghost" data-copromote="${k.id}" data-to="division">${icon("layers")}Share with the division</button>` : ""}<button type="button" class="btn sm ghost" data-copromote="${k.id}" data-to="company">${icon("globe")}Share company-wide</button>`) : ""}
        <button type="button" class="btn sm ghost" data-coforget="${k.id}">${icon("trash")}Delete</button></div></li>`;
  }

  // ---------- agents: the directory and the workspaces are company-agents.js's; it gets the data and these helpers ----------
  const agents = () => CompanyAgents.tab({ d, chip, tok, when, plural, short, A, DIV, P, AG, VERD, TASK, actor, act, newAgent, render, take, busy, err, load });
  function newAgent() {
    return `<form class="co-form" data-coform="agent">
      <div class="row"><label class="in"><span>Name</span><input type="text" name="name" maxlength="40" required></label><label class="in"><span>Title</span><input type="text" name="title" maxlength="60" required placeholder="e.g. Rust Engineer"></label></div>
      <label class="in"><span>Division</span><select name="division_id"><option value="">Shared specialist (any division)</option>${d.divisions.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
      <label class="in"><span>What it does</span><input type="text" name="about" maxlength="400"></label>
      <fieldset class="co-skills"><legend>Skills (proficiency 3; change later)</legend>${Object.entries(d.catalog.skills).map(([k, v]) => `<label title="${esc(v)}"><input type="checkbox" name="skills" value="${k}"><span>${esc(k.replace(/_/g, " "))}</span></label>`).join("")}</fieldset>
      <div class="row"><label class="in"><span>Works in</span><select name="stage">${d.catalog.stages.map(s => `<option>${s}</option>`).join("")}</select></label>
        <label class="in"><span>Teams at once</span><input type="number" name="max_load" min="1" max="10" value="3"></label></div>
      <button type="submit" class="btn sm primary">${icon("plus")}Register</button></form>`;
  }
  // ---------- approvals ----------
  function approvals() {
    const open_ = d.approvals.filter(a => ["pending", "approved"].includes(a.status)), list = apprFilter === "open" ? open_ : d.approvals;
    return `<div class="co-filter"><button type="button" class="co-chip ${apprFilter === "open" ? "on" : ""}" data-coapf="open">Open ${open_.length}</button><button type="button" class="co-chip ${apprFilter === "all" ? "on" : ""}" data-coapf="all">All ${d.approvals.length}</button>
        <span class="faint small">Each approval is for one exact action on one exact version, expires, and runs once. There's no approve-all.</span></div>
      <div class="co-appr">${list.map(approval).join("") || `<section class="card"><p class="faint">${apprFilter === "open" ? "Nothing waits for you." : "No approval request yet."}</p></section>`}</div>`;
  }
  function approval(a) {
    const [sc, sl] = APPR[a.status] || ["none", esc(a.status)], cat = d.catalog.actions[a.action_type] || { label: a.action_type, kind: "external", means: "" }, pl = a.payload, ev = a.evidence?.evaluation;
    const left = a.expires_at - Date.now() / 1000, p = P(a.project_id);
    return `<article class="card co-ap s-${a.status} r-${esc(a.risk)}">
      <div class="co-h"><div><h3>${icon("shield")}${esc(cat.label)}: ${esc(a.title)}</h3><p class="faint small">${who(a.requested_by)}${p ? ` · ${esc(p.name)}` : ""} · ${when(a.created)}</p></div>
        <div class="co-ap-chips">${chip(sc, sl)}${chip(a.risk === "high" ? "bad" : a.risk === "medium" ? "warn" : "none", `risk ${esc(a.risk)}`)}${chip(cat.kind === "internal" ? "run" : "none", cat.kind === "internal" ? "Runs in AXoR" : "Handed to you")}</div></div>
      ${a.reason ? `<p>${esc(a.reason)}</p>` : ""}
      <dl class="co-dl"><dt>Exact action</dt><dd><pre class="co-pre">${esc(pl.details || pl.title || "")}${pl.to ? `\n→ ${esc(pl.from)} to ${esc(pl.to)}` : ""}${pl.changes ? `\n${esc(JSON.stringify(pl.changes))}` : ""}</pre></dd>
        <dt>Bound to</dt><dd>${esc(a.artifact_kind)} ${a.artifact_id} · ${short(a.artifact_hash)} · parameters ${short(a.payload_hash)}${a.changed ? ` ${chip("bad", "changed since: can't run", "alert")}` : ""}${a.artifact_kind === "artifact" && a.task_id ? ` <button type="button" class="linkbtn" data-cotask="${a.task_id}" data-goproj="1">read it</button>` : ""}</dd>
        ${ev ? `<dt>Evaluation</dt><dd>${chip(VERD[ev.verdict] || "none", `${ev.score}/100 · ${esc(ev.verdict)}`)} ${esc(ev.summary || "")}${ev.current === false ? ` ${chip("warn", "for an older version")}` : ""}</dd>` : a.artifact_kind === "artifact" ? `<dt>Evaluation</dt><dd class="faint">none</dd>` : ""}
        ${a.expected ? `<dt>Expected</dt><dd>${esc(a.expected)}</dd>` : ""}${a.rollback ? `<dt>Rollback</dt><dd>${esc(a.rollback)}</dd>` : ""}
        <dt>${["pending", "approved"].includes(a.status) ? "Expires" : "Expired"}</dt><dd>${when(a.expires_at)}${["pending", "approved"].includes(a.status) && left > 0 ? ` <span class="faint small">(in ${left > 7200 ? `${Math.round(left / 3600)} h` : `${Math.max(1, Math.round(left / 60))} min`})</span>` : ""}</dd>
        ${a.decided_by ? `<dt>Decided</dt><dd>${esc(a.decided_by)} · ${when(a.decided_at)}${a.decision_reason ? `: ${esc(a.decision_reason)}` : ""}</dd>` : ""}
        ${a.execution ? `<dt>Execution</dt><dd>${chip(a.execution.status === "done" ? "ok" : a.execution.status === "handed_off" ? "run" : "bad", esc(a.execution.status === "handed_off" ? "authorized: yours to carry out" : a.execution.status))} ${esc(a.execution.result?.note || a.execution.result?.error || "")} <span class="faint small">${when(a.execution.finished)}</span></dd>` : ""}</dl>
      ${a.status === "pending" ? `<form class="co-decide" data-coform="decide" data-appr="${a.id}"><label class="in"><span class="sr">Reason</span><input type="text" name="reason" maxlength="1000" placeholder="A reason (needed to reject or ask for changes)"></label>
          <div class="row"><button type="submit" name="decision" value="approve" class="btn sm primary" ${a.changed ? "disabled" : ""}>${icon("check")}Approve</button><button type="submit" name="decision" value="changes" class="btn sm">${icon("edit")}Ask for changes</button><button type="submit" name="decision" value="reject" class="btn sm ghost">${icon("ban")}Reject</button></div></form>` : ""}
      ${a.status === "approved" ? `<div class="row"><button type="button" class="btn sm primary" data-coexec="${a.id}" ${a.changed ? "disabled" : ""}>${icon("play")}${cat.kind === "internal" ? "Execute" : "Authorize and hand off"}</button><span class="faint small">${esc(cat.means)}</span></div>` : ""}</article>`;
  }

  // ---------- knowledge, audit, settings ----------
  function knowledge() {
    const list = d.knowledge.filter(k => kFilter === "all" || k.scope === kFilter);
    return `<div class="co-filter">${[["all", "All"], ["company", "Company"], ["division", "Division"], ["project", "Project"], ["restricted", "Restricted"]].map(([k, l]) => `<button type="button" class="co-chip ${kFilter === k ? "on" : ""}" data-cokf="${k}">${l} ${k === "all" ? d.knowledge.length : d.knowledge.filter(x => x.scope === k).length}</button>`).join("")}</div>
      <section class="card co-tiers"><p class="small"><b>Who reads what.</b> A team reads its project's knowledge, its division's and the company's: never another project's, never restricted items. Sharing wider is an approval: project → division → company.</p></section>
      <section class="card">${list.length ? `<ul class="co-know">${list.map(knowItem).join("")}</ul>` : `<p class="faint">No knowledge here yet.</p>`}</section>`;
  }
  function audit() {
    const rows = [...d.audit, ...older];
    return `<section class="card"><div class="co-h"><h2>${icon("list")}Audit log</h2><span class="faint small">Append-only: nothing changes or removes an entry</span></div>
      <div class="co-tablewrap"><table class="co-table"><thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead><tbody>
        ${rows.map(r => `<tr><td class="num faint">${when(r.ts)}</td><td>${actor(r)}</td><td>${esc(act(r))}</td><td class="small faint">${esc(Object.entries(r.meta || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("; ").slice(0, 220))}</td></tr>`).join("")}</tbody></table></div>
      ${rows.length >= 60 ? `<button type="button" class="btn sm" data-co="older">Older entries</button>` : ""}</section>`;
  }
  function settings() {
    const s = d.company.settings, off = new Set(s.actions_off || []);
    return `<section class="card"><form class="co-form" data-coform="settings">
        <label class="in"><span>Company name</span><input type="text" name="name" maxlength="80" value="${esc(d.company.name)}"></label>
        <label class="in"><span>Model</span><input type="text" name="model" maxlength="120" value="${esc(d.company.model)}" placeholder="auto"><small class="faint">auto = the server's default (now ${esc(d.company.model_id || "none connected")}); or a provider:model id from Agents → Models</small></label>
        <fieldset class="co-policy"><legend>Actions agents may propose</legend><p class="faint small">Every one of them needs your approval. Switched off, it's never proposed and an approved one can't run.</p>
          ${Object.entries(d.catalog.actions).map(([k, v]) => `<label class="co-check"><input type="checkbox" name="on" value="${k}" ${off.has(k) ? "" : "checked"}><span><b>${esc(v.label)}</b> <span class="faint small">${v.kind === "internal" ? "runs in AXoR" : "handed to you"}: ${esc(v.means)}</span></span></label>`).join("")}</fieldset>
        <button type="submit" class="btn sm primary">Save</button></form></section>
      <section class="card"><h3>${icon("shield")}Fixed rules</h3><ul class="small">
        <li>Agents never write to production, act outside, move money or sign transactions: these restrictions are in every contract and can't be switched on.</li>
        <li>Approvals are checked by the server: bound to the artifact's and the parameters' SHA-256, single-use, expiring after 72 hours.</li>
        <li>Agents can't change any contract, their own included, and can't approve anything.</li>
        <li>Production execution is off: approved outside actions are handed to you with the exact payload.</li></ul></section>`;
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    const v = $("#view-company");
    v.addEventListener("click", async e => {
      const t = e.target;
      const tb = t.closest("[data-cotab]"); if (tb) { tab = tb.dataset.cotab; try { store.set("co.tab", tab); } catch { /* only the tab isn't remembered */ } return render(); }
      const pj = t.closest("[data-coproj]"); if (pj) { proj = +pj.dataset.coproj; tab = "projects"; return render(); }
      const go = t.closest("[data-cogo]"); if (go) return setView(go.dataset.cogo);
      const ag = t.closest("[data-coagent]"); if (ag) { CompanyAgents.open(+ag.dataset.coagent); tab = "agents"; try { store.set("co.tab", tab); } catch { /* only the tab isn't remembered */ } return render(); }
      const f2 = t.closest("[data-coapf]"); if (f2) { apprFilter = f2.dataset.coapf; return render(); }
      const f3 = t.closest("[data-cokf]"); if (f3) { kFilter = f3.dataset.cokf; return render(); }
      const tk = t.closest("[data-cotask]");
      if (tk) { const tid = +tk.dataset.cotask;
        if (tk.dataset.goproj || tk.closest(".co-arts")) { const task = d.tasks.find(x => x.id === tid); if (task) { proj = task.project_id; tab = "projects"; } openTask[tid] = true; }
        else if (openTask[tid]) delete openTask[tid]; else openTask[tid] = true;
        render(); if (openTask[tid]) fetchTask(tid); return; }
      const ed = t.closest("[data-coedit]"); if (ed) { const k = `edit${ed.dataset.coedit}`; if (openTask[k]) delete openTask[k]; else openTask[k] = true; return render(); }
      const bd = t.closest("[data-cobuild]");
      if (bd) { const kind = v.querySelector(`[data-cokind="${bd.dataset.cobuild}"]`)?.value || "dynamic";
        const r = await busy(bd, () => api(`${C}/tasks/${bd.dataset.cobuild}/team`, { method: "POST", body: { kind } })); if (r) { Auth.toast("The team builder proposed a team"); take(r); } return; }
      const st = t.closest("[data-costart]");
      if (st) { const r = await busy(st, () => api(`${C}/teams/${st.dataset.costart}/start`, { method: "POST" })); if (r) { const tm = r.teams.find(x => x.id === +st.dataset.costart); if (tm) { openTask[tm.task_id] = true; fetchTask(tm.task_id, false); } Auth.toast("The team is working"); take(r); } return; }
      const rl = t.closest("[data-corelease]"); if (rl) { const r = await busy(rl, () => api(`${C}/teams/${rl.dataset.corelease}/release`, { method: "POST" })); if (r) { Auth.toast("Released"); take(r); } return; }
      const cc = t.closest("[data-cocancel]");
      if (cc) return UI.confirm({ title: "Cancel this task?", body: "A team at work stops after the call it's in. What it wrote so far stays.", ok: "Cancel the task", icon: "stop",
        run: async () => { take(await api(`${C}/tasks/${cc.dataset.cocancel}/cancel`, { method: "POST" })); Auth.toast("Cancelled"); } }).catch(err);
      const br = t.closest("[data-cobrief]");
      if (br) { const r = await busy(br, () => api(`${C}/briefs/${br.dataset.cobrief}/create`, { method: "POST" })); if (r) { proj = r.project_id; tab = "projects"; Auth.toast("Project created"); take(r); } return; }
      const rq = t.closest("[data-coreq]");
      if (rq) { const sel = v.querySelector(`[data-coreqsel="${rq.dataset.coreq}"]`), a = d.artifacts.find(x => x.id === +rq.dataset.coreq), lab = d.catalog.actions[sel.value]?.label;
        const r = await busy(rq, () => api(`${C}/approvals`, { method: "POST", body: { action_type: sel.value, title: `${lab}: ${a?.title || "deliverable"}`.slice(0, 160), artifact_id: +rq.dataset.coreq, details: `${lab} for "${a?.title}" (SHA-256 ${a?.sha?.slice(0, 12)}).` } }));
        if (r) { Auth.toast("Asked: it waits in Approvals"); take(r); } return; }
      const pm = t.closest("[data-copromote]");
      if (pm) { const k = d.knowledge.find(x => x.id === +pm.dataset.copromote);
        const r = await busy(pm, () => api(`${C}/approvals`, { method: "POST", body: { action_type: "knowledge_promotion", knowledge_id: k.id, scope: pm.dataset.to, title: `Share "${k.title}" with the ${pm.dataset.to}`.slice(0, 160), details: k.body.slice(0, 3900) } }));
        if (r) { Auth.toast("Asked: approve it in Approvals"); take(r); } return; }
      const fg = t.closest("[data-coforget]");
      if (fg) return UI.confirm({ title: "Delete this knowledge?", body: "Teams stop reading it. The audit log keeps that it existed.", ok: "Delete",
        run: async () => { take(await api(`${C}/knowledge/${fg.dataset.coforget}`, { method: "DELETE" })); Auth.toast("Deleted"); } }).catch(err);
      const ex = t.closest("[data-coexec]"); if (ex) { const r = await busy(ex, () => api(`${C}/approvals/${ex.dataset.coexec}/execute`, { method: "POST" })); if (r) { Auth.toast("Executed: see the result on the card"); take(r); } return; }
      const sa = t.closest("[data-costat]");
      if (sa) { const r = await busy(sa, () => api(`${C}/agents/${sa.dataset.costat}`, { method: "PATCH", body: { status: sa.dataset.s } })); if (r) { take(r); fetchAgent(+sa.dataset.costat); } return; }
      const b = t.closest("[data-co]"); if (!b) return;
      if (b.dataset.co === "reload") return load();
      if (b.dataset.co === "older") { const last = [...d.audit, ...older].at(-1); const r = await busy(b, () => api(`${C}/audit?before=${last.id}`)); if (r) { older = older.concat(r.audit); render(); } }
    });
    v.addEventListener("change", async e => {
      const t = e.target;
      if (t.matches("[data-costatus]")) { const r = await busy(null, () => api(`${C}/projects/${t.dataset.costatus}`, { method: "PATCH", body: { status: t.value } })); if (r) { t.blur(); take(r); } }
      if (t.matches("[data-cobudget]")) { const r = await busy(null, () => api(`${C}/projects/${t.dataset.cobudget}`, { method: "PATCH", body: { budget: +t.value } })); if (r) { t.blur(); Auth.toast("Budget changed"); take(r); } }
      if (t.matches("[data-cotpl]")) { const key = d.divisions.find(x => x.id === +t.value)?.key; t.form.querySelectorAll("[name=template] option[data-div]").forEach(o => { o.hidden = o.dataset.div !== key; if (o.hidden && o.selected) t.form.template.value = ""; }); }
    });
    v.addEventListener("submit", async e => {
      const fm = e.target.closest("[data-coform]"); if (!fm) return;
      e.preventDefault();
      const kind = fm.dataset.coform, btn = e.submitter || fm.querySelector("[type=submit]"), F = new FormData(fm);
      const done = (r, msg) => { if (r) { document.activeElement?.blur(); if (msg) Auth.toast(msg); take(r); } return r; };
      if (kind === "brief") done(await busy(btn, () => api(`${C}/brief`, { method: "POST", body: { goal: F.get("goal") } })), "The leadership is working on it");
      if (kind === "division") done(await busy(btn, () => api(`${C}/divisions`, { method: "POST", body: { name: F.get("name"), description: F.get("description") || "" } })), "Division added");
      if (kind === "project") { const r = await busy(btn, () => api(`${C}/projects`, { method: "POST", body: { division_id: +F.get("division_id"), name: F.get("name"), objective: F.get("objective"), success: F.get("success") || "", budget: +F.get("budget"), template: F.get("template") || "" } }));
        if (r) { proj = r.project_id; done(r, "Project created"); } }
      if (kind === "task") done(await busy(btn, () => api(`${C}/projects/${fm.dataset.project}/tasks`, { method: "POST", body: { title: F.get("title"), description: F.get("description") || "", skills: F.getAll("skills"), kind: F.get("kind"), priority: +F.get("priority") } })), "Task added: propose a team for it");
      if (kind === "knowledge") done(await busy(btn, () => api(`${C}/knowledge`, { method: "POST", body: { project_id: +fm.dataset.project, title: F.get("title"), body: F.get("body"), restricted: !!F.get("restricted") } })), "Added");
      if (kind === "edit") { const r = done(await busy(btn, () => api(`${C}/artifacts/${fm.dataset.art}`, { method: "PUT", body: { body: F.get("body") } })), "Saved: it has a new hash");
        if (r) { delete openTask[`edit${fm.dataset.art}`]; const a = r.artifacts.find(x => x.id === +fm.dataset.art); if (a) fetchTask(a.task_id); } }
      if (kind === "decide") { const dec = btn?.value || "approve";
        done(await busy(btn, () => api(`${C}/approvals/${fm.dataset.appr}/decide`, { method: "POST", body: { decision: dec, reason: F.get("reason") || "" } })), dec === "approve" ? "Approved: execute it when you're ready" : dec === "reject" ? "Rejected" : "Changes asked"); }
      if (kind === "agent") { const sk = Object.fromEntries(F.getAll("skills").map(k => [k, 3]));
        done(await busy(btn, () => api(`${C}/agents`, { method: "POST", body: { name: F.get("name"), title: F.get("title"), division_id: F.get("division_id") ? +F.get("division_id") : null, about: F.get("about") || "", skills: sk, stage: F.get("stage"), max_load: +F.get("max_load") || 3 } })), "Registered"); }
      if (kind === "contract") { const aid = +fm.dataset.agent, a = A(aid), skills = {};
        for (const k of Object.keys(a.skills)) { const n = +F.get(`sk_${k}`); if (n > 0) skills[k] = Math.min(5, n); }
        if (F.get("sk_new")) skills[F.get("sk_new")] = 3;
        const list = s => String(s || "").split(",").map(x => x.trim()).filter(Boolean);
        const r = done(await busy(btn, () => api(`${C}/agents/${aid}`, { method: "PATCH", body: { skills, write: list(F.get("write")), execute: list(F.get("execute")), max_load: +F.get("max_load") } })), "Saved: a new version");
        if (r) fetchAgent(aid); }
      if (kind === "settings") done(await busy(btn, () => api(C, { method: "PATCH", body: { name: F.get("name") || "", model: F.get("model") || "auto", actions_off: Object.keys(d.catalog.actions).filter(k => !F.getAll("on").includes(k)) } })), "Saved");
    });
  }

  return { open, stop };
})();
