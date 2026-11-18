/* Competition teams (mining_work.py): an agent team per competition, across every subnet in My subnets of yours.
   - The page (#teams, sidebar → Workspace → Competition teams): a tab per competition, grouped by subnet (SN<netuid> · <number>).
     Each holds its team's board (To do, In progress, Waiting for you, Done), the team as an org chart (the Director,
     then each squad under its lead), the notebook of approved findings, the sandbox (the team's files and the runs on them) and
     the activity. Autopilot runs a team on its own: the Director plans, tasks start themselves and squad leads review the work.
     Competitions come in through Import competitions (mining-sources.js): found by sources or imported by hand, approved by you.
   - The control room (My subnets → a campaign → Teams, control()): every team of the campaign in one table, with autopilot,
     pause, stop, budgets shared by emission share and Import competitions.
   A task opens in a dialog with its result, its review (approve, or send it back; answer an agent's question), its runs and
   their traces. */
const MiningWork = (() => {
  let all = null, wid = null, v = null, sub = null, who = "all", allDone = false, failed = "", timer = null, wired = false, on = false, loading = false;
  let models = null, task = null, taskId = null, sbxId = null, sbxTimer = null;
  const opened = new Set(), full = {};  // notebook entries open on the page, and their full text: a re-render keeps both
  let ccid = null, chome = null, cfailed = "", ctimer = null, cloaded = 0, cwired = false;  // the control room in My subnets
  const W = "/api/mining/work";
  const root = () => $("#teams");
  const err = e => e && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n || 0, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const dur = s => s < 1 ? `${Math.round(s * 1000)} ms` : s < 60 ? `${fmtNum(s, 1)} s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  const span = s => s < 3600 ? `${Math.max(1, Math.round(s / 60))}m` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
  const day = s => new Date(`${s}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const left = s => Math.round((new Date(`${s}T00:00:00`) - new Date(new Date().toDateString())) / 86400000);  // calendar days from today
  const pct = x => `${fmtNum(x * 100, x < 0.1 ? 1 : 0)}%`;
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;
  const AG = () => Object.fromEntries((v?.agents || []).map(a => [a.id, a]));
  const av = (a, size = "sm") => a ? `<span class="av ${size} c-${a.color}" aria-hidden="true">${icon(a.icon)}</span>` : `<span class="av ${size} mw-you" aria-hidden="true">${icon("smile")}</span>`;
  const mine = t => t.agent == null;
  const COLS = [["todo", "To do", t => t.status === "todo" && !mine(t)], ["doing", "In progress", t => ["queued", "working", "checking"].includes(t.status)],
    ["wait", "Waiting for you", t => ["review", "blocked"].includes(t.status) || (t.status === "todo" && mine(t))], ["done", "Done", t => t.status === "done"]];
  const EMPTY = { todo: "Nothing assigned and waiting. The lead plans; you can add tasks too.", doing: "No agent is working.", wait: "Nothing waits for you.", done: "Nothing finished yet." };
  const TS = { todo: ["none", "To do"], queued: ["wait", "Queued"], working: ["run", "Working"], checking: ["run", "In review"], review: ["warn", "Review"], blocked: ["bad", "Question"], done: ["ok", "Done"] };
  const RUN = { running: ["run", "Running"], done: ["ok", "Done"], failed: ["bad", "Failed"], cancelled: ["none", "Stopped"], timeout: ["bad", "Timed out"], error: ["bad", "Error"] };
  const CSTATE = { upcoming: ["wait", "Upcoming"], active: ["ok", "Active"], closed: ["off", "Closed"] };
  const PRI = { high: "High", medium: "Medium", low: "Low" }, RANK = { high: 0, medium: 1, low: 2 };
  const COLORS = ["violet", "blue", "teal", "green", "amber", "orange", "rose", "slate"];
  const KIND_ICON = { create: "folderplus", settings: "gear", team: "users", task: "note", assign: "pointer", queue: "clock", start: "play", review: "eye",
    blocked: "chat", approve: "check", revise: "undo", done: "check", followup: "sparkle", plan: "route", cancel: "stop", error: "alert", pilot: "zap",
    file: "file", sandbox: "terminal" };
  const PRESETS = [["Run the agent on every practice task", "python .axor/ridges_run.py --agent agent.py tasks/*", ["postgres"]],
    ["Check the databases answer", "psql -c 'select version()' && curl -s \"$CLICKHOUSE_URL/?query=SELECT%20version()\"", ["postgres", "clickhouse"]],
    ["List the files", "find . -type f | sort | head -100", []]];

  // ---------- the page ----------
  function open() {
    on = true; wire();
    if (sub === null) sub = store.get("mw.sub2", "status");  // first visit: Overview → Status (mining-stages.js)
    if (!all) put(root(), Loading.line("Opening your competition teams…"));
    load();
  }
  function stop() { on = false; clearTimeout(timer); }
  async function load() {
    if (loading) return; loading = true;
    try {
      const a = await api(`${W}/all`);
      all = a; failed = "";
      if (!all.comps.some(c => c.id === wid)) wid = store.get("mw.w", null);
      if (!all.comps.some(c => c.id === wid)) wid = (all.comps.find(c => c.status !== "closed") || all.comps[0])?.id ?? null;
      const at = wid, nv = wid ? await api(`${W}/comps/${wid}`) : null;
      if (at === wid) v = nv;
      badge(); MiningSources.peek();
    } catch (e) { failed = e.message; }
    finally { loading = false; }
    if (!MiningCrew.holding() && !MiningBench.holding() && !MiningFiles.holding() && !MiningAutoloop.holding() && !MiningUpgrade.holding() && !MiningTopMiner.holding()) render();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!on) return;
    const busy = (v && (v.planning || v.tasks.some(t => ["queued", "working", "checking"].includes(t.status)) || v.sandbox.runs.some(r => r.status === "running")))
      || all?.comps.some(c => c.working);
    timer = setTimeout(() => { if (!on || $("#view-teams")?.hidden || document.visibilityState !== "visible") return schedule(); load(); }, busy ? 2500 : 15000);
  }
  function apply(nv) {
    v = nv;
    const c = all?.comps.find(x => x.id === nv.comp.id);
    if (c) Object.assign(c, { label: nv.comp.label, status: nv.comp.status, autopilot: nv.comp.autopilot, paused: nv.comp.paused, share: nv.comp.share,
      waiting: MiningDirector.waiting(nv), relaying: MiningDirector.relaying(nv), agents: nv.agents.length });
    render(); schedule(); badge();
  }
  function badge() {
    const n = (all?.comps || []).reduce((s, c) => s + (c.waiting || 0), 0), el = $("#c-teams");
    if (el) el.textContent = n || "";
  }

  function render() {
    const el = root(); if (!el) return;
    if (!all) { put(el, failed ? `<div class="empty">${esc(failed)}</div>` : Loading.line("Opening your competition teams…")); return; }
    const f = document.activeElement?.matches?.("[data-mcpq]") ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
    put(el, `<div class="mw-page">${top()}${all.comps.length ? strip() : ""}<div class="mw" id="mw">${!all.comps.length ? welcome() : !v ? Loading.line("Opening the team…") : workspace()}</div></div>`);
    $$("time[data-ts]", el).forEach(t => { t.textContent = ago(+t.dataset.ts); });
    const q = f && $("[data-mcpq]", el); if (q && document.activeElement !== q) { q.focus(); q.setSelectionRange(...f); }
    if (task && $("#mw-task")?.open) syncTask();
  }
  const intakeBtn = (cls = "btn sm", text = "Import competitions") => `<button type="button" class="${cls}" data-mw="intake">${icon("download")}${text}<span class="hq-n alert cin-badge" ${MiningSources.count() ? "" : "hidden"}>${MiningSources.count() || ""}</span></button>`;
  function top() {
    return `<header class="mw-top"><div><h1>${icon("users")}Competition teams</h1>
        <p class="faint">An agent team per competition you enter. Control them all from My subnets, under each campaign's Teams tab.</p></div>
      <div class="mw-top-act">${intakeBtn()}
        <button type="button" class="btn sm" data-mw="new" ${all.campaigns.length ? "" : "disabled"}>${icon("folderplus")}New competition</button>
        <button type="button" class="btn sm" data-mw="portfolio">${icon("target")}Portfolio</button>
        <button type="button" class="btn sm" data-mw="hq">${icon("trophy")}My subnets</button></div></header>`;
  }
  function tstate(c) {
    if (c.status === "closed") return ["off", "Closed"];
    if (c.paused) return ["wait", "Paused"];
    if (!c.autopilot) return ["none", "Autopilot off"];
    return [c.working ? "run" : "ok", c.working ? `${c.working} at work` : "Autopilot on"];
  }
  function strip() {
    const groups = [];
    for (const c of all.comps) { let g = groups.find(x => x.netuid === c.netuid); if (!g) groups.push(g = { netuid: c.netuid, subnet: c.subnet, comps: [] }); g.comps.push(c); }
    return `<nav class="mw-strip" role="tablist" aria-label="Competitions">${groups.map(g => `<div class="mw-strip-g" role="group" aria-label="SN${g.netuid} ${esc(g.subnet || "")}">
        ${g.comps.map(c => { const [dot, st] = tstate(c);
          return `<button type="button" role="tab" class="mw-tab ${c.id === wid ? "on" : ""} ${c.status === "closed" ? "closed" : ""}" data-mwcomp="${c.id}" aria-selected="${c.id === wid}" title="${esc(`${c.label}: ${st}`)}">
            <span class="ci ci-${dot}"></span><span class="mw-tab-t"><b>SN${c.netuid} · ${c.number ?? esc(c.label)}</b>${c.number != null ? `<small>${esc(c.name || c.label)}</small>` : ""}</span>
            ${c.waiting ? `<span class="hq-n alert" title="Waiting for you">${c.waiting}</span>` : ""}</button>`; }).join("")}</div>`).join("")}</nav>`;
  }
  function welcome() {
    if (!all.campaigns.length) return `<section class="mh-welcome mw-welcome"><div><h2>Start by adding a subnet in My subnets</h2>
        <p>A competition team works for one of your subnets in My subnets: the subnet you mine. Start one there, then come back and import its competitions: from their pages, a file, or sources such as Ridges that are checked for you.</p>
        <button type="button" class="btn primary" data-mw="hq">${icon("trophy")}Open My subnets</button></div></section>`;
    return `<section class="mh-welcome mw-welcome"><div><h2>An agent team per competition</h2>
        <p>A subnet may run several competitions at once. Each gets a team of 20-odd agents in squads: a Director who plans, squad leads who review, and specialists who do the work, with their own board, notebook and sandbox.</p>
        <p>On autopilot the team runs itself: the Director plans every few hours, tasks start on their own and squad leads approve or send back each result. Nobody contacts you one by one: the Director settles what the team can and sends you one report with what only a person can do: uploads, registration, payments, and the decisions that are yours.</p>
        <div class="row">${intakeBtn("btn primary")}
          <button type="button" class="btn" data-mw="new">${icon("folderplus")}New competition</button></div></div>
      <ul class="mh-team-list">${(all.packs || []).map(p => `<li><span class="av sm c-violet" aria-hidden="true">${icon("users")}</span><div><b>${esc(p.label)}</b><p>${esc(p.about)}</p></div></li>`).join("")}</ul></section>`;
  }

  // ---------- a competition ----------
  function pilotLine(c) {
    if (c.status === "closed") return "The competition is closed: nothing new starts.";
    if (c.paused) return "Paused: work in progress finishes, nothing new starts.";
    if (!c.autopilot) return "Off: you start tasks and review the results.";
    const working = v.agents.filter(a => a.working).length, next = (c.last_plan || 0) + c.plan_every * 3600 - Date.now() / 1000;
    return `${working ? `${plural(working, "agent")} at work` : "Nobody at work"}, up to ${c.parallel} at once · ${v.planning ? "the Director is planning" : `next plan ${c.last_plan && next > 0 ? `in ${span(next)}` : "soon"}`}`;
  }
  function workspace() {
    const c = v.comp, A = AG(), lead = A[v.lead], [tone, sl] = CSTATE[c.status], u = v.usage, closed = c.status === "closed";
    const total = v.tasks.length, done = v.tasks.filter(t => t.status === "done").length;
    const startable = v.tasks.filter(t => t.status === "todo" && A[t.agent]?.on).length;
    const waiting = MiningDirector.waiting(v), relay = MiningDirector.relaying(v), running = v.tasks.some(t => ["queued", "working", "checking"].includes(t.status));
    // the earlier tools, under More: the Workflow (mining-bench.js) and Files come first
    const more = [["status", "Status", "info", 0], ["tasks", "Board", "list", relay ? 0 : waiting], ["report", "Report", "inbox", relay ? waiting : 0], ["team", "Agents", "users", 0, v.agents.length], ["notes", "Notebook", "book", 0, v.notes.length],
      ["sandbox", "Files & sandbox", "terminal", 0, v.files.length], ["activity", "Activity", "clock", 0], ["diagram", "Diagram", "route", 0], ["roadmap", "Roadmap", "map", 0], ["prompts", "Prompts", "chat", 0],
      ["levels", "Levels", "trophy", 0], ["links", "Links", "link", 0], ["desk", "Desk", "grid", 0]];
    if (sub === "flow") { sub = "status"; store.set("mw.sub2", sub); }  // the Workflow tab is hidden (11-09); Lab, Loadouts, Files and GitHub still run on the workbench
    if (MiningBench.owns(sub)) return MiningBench.page(v, sub, more);
    const squads = new Set(v.agents.map(a => a.squad).filter(Boolean)).size;
    const n = c.ends && c.status === "active" ? left(c.ends) : null;
    const dates = c.starts || c.ends ? `<span>${icon("calendar")}${c.starts ? day(c.starts) : "…"} – ${c.ends ? day(c.ends) : "…"}${n != null ? ` <b class="${n <= 1 ? "mw-late" : ""}">${n > 1 ? `ends in ${n} days` : n === 1 ? "ends tomorrow" : n === 0 ? "ends today" : "past its end date"}</b>` : ""}</span>` : "";
    const share = u.budget ? Math.min(1, u.day / u.budget) : 0;
    const pstate = closed ? "off" : c.paused ? "wait" : !c.autopilot ? "none" : "run";
    // the team's execution, apart from the competition's own status (a competition can be active while its team is idle)
    const working = v.agents.filter(a => a.working || a.doing).length;
    const teamState = closed ? ["off", "Team stopped"] : c.paused ? ["wait", "Team paused"] : working ? ["run", `Team at work · ${working} running`] : running ? ["run", "Team: work queued"] : ["none", "Team idle"];
    const carried = v.tasks.filter(t => /^(carried|import):/.test(t.origin || "")).length;
    return `<section class="mh-card mw-head"><div class="mw-head-main">
        <div class="mw-kicker">${icon("folder")}SN${v.campaign.netuid} · ${esc(v.campaign.subnet || v.campaign.title)}${c.number != null ? ` · competition ${c.number}` : ""}${c.source === "ridges" ? ` · <span title="Imported from ridges.ai">${icon("download")}from Ridges</span>` : c.source === "import" ? ` · <span title="Made from an approved import">${icon("download")}imported</span>` : ""}</div>
        <h2>${esc(c.label)} ${chip([tone, `Competition ${sl.toLowerCase()}`])} ${chip(teamState)}${c.share ? ` <span class="hq-chip t-run" title="The share of the subnet's emissions this competition's winners receive, as the subnet publishes it (not your earnings)">${icon("coins")}${pct(c.share)} of the subnet's emissions to this competition</span>` : ""}</h2>
        <div class="mw-meta">${dates}${c.link ? `<a href="${esc(c.link)}" target="_blank" rel="noopener noreferrer">${icon("external")}Competition page</a>` : ""}<span title="Assigned: agents on this team. Running: working on a task right now.">${icon("users")}${v.agents.length} assigned · ${working} running${squads ? ` · ${plural(squads, "squad")}` : ""}${lead ? ` · led by ${esc(lead.name)}` : ", no lead"}</span></div>
        ${c.goal ? `<p class="mw-goal">${icon("target")}<span>${esc(c.goal)}</span></p>` : `<p class="faint small">No goal yet. <button type="button" class="linkbtn" data-mw="edit">Add one</button> so the lead can plan.</p>`}
        ${c.description ? `<details class="mw-desc" ${opened.has("desc") ? "open" : ""}><summary>What the subnet says about it</summary><p>${esc(c.description)}</p></details>` : ""}
      </div><div class="mw-head-side">
        <div class="mw-pilot p-${pstate}"><label class="mw-switch" title="Autopilot: this team plans and runs its own work (execution autonomy). Not the Autoloop (repeats one bounded task) nor the Evolution Lab (new agent versions). ${c.autopilot ? "Switch it off" : "Switch it on"}"><input type="checkbox" data-mwpilot ${c.autopilot ? "checked" : ""} ${closed ? "disabled" : ""}><span aria-hidden="true"></span><b>Autopilot</b></label>
          <span class="mw-pilot-l">${esc(pilotLine(c))}</span>
          ${c.pilot_note && c.autopilot && !c.paused ? `<span class="mh-err small">${icon("info")}${esc(c.pilot_note)}</span>` : ""}
          <span class="row">${(c.autopilot || c.paused) && !closed ? `<button type="button" class="btn sm" data-mw="${c.paused ? "resume" : "pause"}">${icon(c.paused ? "play" : "stop")}${c.paused ? "Resume" : "Pause"}</button>` : ""}
            ${running ? `<button type="button" class="btn sm mw-danger" data-mw="stop" title="Stop the work in progress and pause the team">${icon("ban")}Stop now</button>` : ""}</span></div>
        <div class="mw-ctl" role="toolbar" aria-label="Control the team">
          <details class="mw-adv"><summary class="btn sm" title="Other ways to start work: they run on the team's board, outside a mission">${icon("sliders")}Advanced</summary><div class="mw-adv-menu" role="menu">
          <p class="faint small">Start mission (below) is the main way to give this team work. These run on the board directly.</p>
          <button type="button" class="btn sm" data-mw="plan" ${!lead || v.planning || closed ? "disabled" : ""}>${icon(v.planning ? "cycle" : "route")}${v.planning ? `${esc(lead?.name || "The lead")} is planning…` : "Plan now"}</button>
          ${c.autopilot ? "" : `<button type="button" class="btn sm" data-mw="startall" ${!startable || closed ? "disabled" : ""}>${icon("play")}Start assigned${startable ? ` (${startable})` : ""}</button>`}
          <button type="button" class="btn sm" data-mw="addtask">${icon("plus")}Task</button>
          <button type="button" class="btn sm" data-mw="import" title="Bring in your earlier work on this competition: code, eval sets, notes, git history, conversations">${icon("upload")}Import</button></div></details>
          <button type="button" class="iconbtn" data-mw="edit" aria-label="Team settings" title="Team settings">${icon("gear")}</button></div>
        <div class="mw-progress"><div class="mw-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${done}" aria-label="Tasks done"><i style="--w:${total ? (done / total * 100).toFixed(1) : 0}%"></i></div>
          <span title="Tasks on the team's board (planned, added, carried over or imported); missions are counted on the mission strip below">${done} of ${plural(total, "board task")} done${carried ? ` (${carried} carried over or imported)` : ""}${waiting ? ` · <b class="mw-waiting">${relay ? `${plural(waiting, "ask")} in ${esc(lead?.name || "the Director")}'s report` : `${waiting} waiting for you`}</b>` : ""}</span>
          <span class="${share >= 1 ? "mw-late" : ""}" title="Model tokens this team used since midnight, against its daily token budget. Money spent and cost per validated result: Intelligence → Analytics.">${short(u.day)}${u.budget ? ` of ${short(u.budget)}` : ""} tokens today (this team)${share >= 1 ? ": the budget is spent" : ""}${$('nav.side [data-view="analytics"]:not([hidden])') ? ` · <button type="button" class="linkbtn" data-mwview="analytics">cost</button>` : ""}</span></div>
        ${!v.model ? `<p class="mh-err small">${icon("info")}No model is connected: agents can't work until an administrator connects one in Agents → Models.</p>` : ""}</div></section>
      ${MiningStatus.strip(v)}
      ${MissionTeam.strip(v)}
      ${MiningBench.tabs(sub, more)}
      ${{ status: () => MiningStatus.view(v), autoloop: () => MiningAutoloop.view(v), upgrade: () => MiningUpgrade.view(v), topminer: () => MiningTopMiner.view(v), team, notes: notebook, sandbox, activity, report: () => MiningDirector.report(v), diagram: () => MiningCrew.diagram(v), roadmap: () => MiningCrew.roadmap(v), prompts: () => MiningCrew.prompts(v),
          levels: () => MiningCrew.levels(v), links: () => MiningCrew.links(v), desk: () => MiningCrew.desk(v) }[sub]?.() ?? board()}`;
  }

  // ---------- the board ----------
  function board() {
    const list = v.tasks.filter(t => who === "all" || (who === "you" ? mine(t) : t.agent === +who));
    const relay = MiningDirector.relaying(v), boss = AG()[v.lead]?.name || "the Director";
    const col = ([k, label, fits]) => {
      if (k === "wait" && relay) label = `With ${boss} and you`;
      let ts = list.filter(fits);
      const n = ts.length;
      ts.sort(k === "done" ? (a, b) => (b.done_at || b.updated) - (a.done_at || a.updated) : (a, b) => RANK[a.priority] - RANK[b.priority] || a.id - b.id);
      const more = k === "done" && !allDone && n > 8 ? n - 8 : 0;
      if (more) ts = ts.slice(0, 8);
      return `<section class="mw-col c-${k}" aria-label="${label}"><h3>${label}<span class="hq-n ${k === "wait" && n ? "alert" : ""}">${n || ""}</span>
          ${k === "todo" ? `<button type="button" class="iconbtn" data-mw="addtask" aria-label="Add a task" title="Add a task">${icon("plus")}</button>` : ""}</h3>
        ${k === "wait" && relay && n ? `<p class="faint small mw-relay">${icon("inbox")}${esc(boss)} settles these and sends you one <button type="button" class="linkbtn" data-mwsub="report">report</button>; you can still open any of them.</p>` : ""}
        <div class="mw-cards">${ts.map(card).join("") || `<p class="mw-none">${EMPTY[k]}</p>`}${more ? `<button type="button" class="linkbtn" data-mw="alldone">Show ${more} more</button>` : ""}</div></section>`;
    };
    return `<div class="mw-filter"><label class="mw-who"><select data-mwwho aria-label="Whose tasks to show">
        ${[["all", "Everyone's tasks"], ["you", "Yours"], ...v.agents.map(a => [String(a.id), `${a.name}'s`])].map(([k, l]) => `<option value="${k}" ${who === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
      <span class="faint small">Open a task for its result, its review and its controls.</span></div>
      <div class="mw-board">${COLS.map(col).join("")}</div>`;
  }
  function origin(t, A) {
    const o = t.origin || "";
    if (o.startsWith("plan:")) return "from the plan";
    if (o.startsWith("agent:")) return `suggested by ${esc(A[+o.split(":")[1]]?.name || "an agent")}`;
    if (o.startsWith("carried:")) return "carried over";
    return "";
  }
  function card(t) {
    const A = AG(), a = A[t.agent], from = origin(t, A), rv = A[t.reviewer];
    const line = t.status === "blocked" ? t.question : t.status === "checking" ? `${rv?.name || "A squad lead"} is reviewing it` : t.status === "todo" && t.note ? t.note : t.summary || t.detail;
    const late = t.due && t.status !== "done" && left(t.due) < 0;
    return `<button type="button" class="mw-task s-${t.status} p-${t.priority}" data-mwtask="${t.id}">
      <span class="mw-task-top"><span class="mw-pri p-${t.priority}">${PRI[t.priority]}</span>${["todo", "done"].includes(t.status) ? "" : chip(TS[t.status])}${t.hold ? `<span class="hq-chip ${t.hold === "retry" ? "t-warn" : "t-bad"}" title="${t.hold === "retry" ? "The Autoloop retries it after a short wait" : "Autopilot leaves it to you"}">${t.hold === "failed" ? "Failed twice" : t.hold === "retry" ? "Retries soon" : "Held"}</span>` : ""}${t.confidence === "low" && ["review", "checking", "done"].includes(t.status) ? `<span class="hq-chip t-warn" title="Its agent says the result rests on claims it couldn't check">Low confidence</span>` : ""}${t.due ? `<span class="mw-due ${late ? "mw-late" : ""}">${icon("calendar")}${day(t.due)}</span>` : ""}</span>
      <b class="mw-task-t">${esc(t.title)}</b>${line ? `<span class="mw-task-sum">${esc(line)}</span>` : ""}
      <span class="mw-task-foot">${av(a, "xs")}<span>${a ? esc(a.name) : "You"}${a && !a.on ? " (off)" : ""}</span>${from ? `<span class="faint">· ${from}</span>` : ""}${t.runs > 1 ? `<span class="faint">· run ${t.runs}</span>` : ""}</span>
      ${["working", "checking"].includes(t.status) ? `<span class="mw-working" aria-hidden="true"></span>` : ""}</button>`;
  }

  // ---------- the team: an org chart ----------
  function agentCard(a, T, big) {
    const [dot, state] = !a.on ? ["off", "Off: starts nothing new"] : a.doing === "review" ? ["run", `Reviewing “${T[a.working]?.title || "a task"}”`]
      : a.doing === "plan" ? ["run", "Planning the competition"] : a.working ? ["run", `On “${T[a.working]?.title || "a task"}”`]
      : a.queued ? ["wait", `${plural(a.queued, "task")} queued`] : ["ok", "Free"];
    return `<article class="mw-ag ${a.on ? "" : "off"} ${a.working || a.doing ? "busy" : ""} ${big ? "big" : ""}">
      <button type="button" class="mw-ag-main" data-mwedit="${a.id}" title="${esc(a.job)}">${av(a, big ? "lg" : "sm")}<span class="mw-ag-id"><b>${esc(a.name)}${MiningCrew.badge(a.id)}${a.lead ? ` <span class="hq-chip t-run">${icon("star")}Director</span>` : a.head ? ` <span class="hq-chip t-ok">Squad lead</span>` : ""}</b>
        <span class="faint small">${esc(a.title)}</span><span class="mw-ag-state"><span class="ci ci-${dot}"></span>${esc(state)}</span></span></button>
      ${big ? `<p class="small">${esc(a.job)}</p>` : ""}
      <div class="mw-ag-foot"><span class="faint small">${a.done} done · ${a.open} open · ${short(a.tokens_day)} tokens today${a.failed_day ? ` · <b class="mw-late">${a.failed_day} failed</b>` : ""}</span>
        <span class="mw-ag-act"><button type="button" class="iconbtn" data-mwnewfor="${a.id}" ${a.on ? "" : "disabled"} aria-label="Give ${esc(a.name)} a task" title="Give a task">${icon("plus")}</button>
          <button type="button" class="iconbtn" data-mwon="${a.id}" aria-label="${a.on ? "Switch off" : "Switch on"} ${esc(a.name)}" title="${a.on ? "Switch off" : "Switch on"}">${icon(a.on ? "ban" : "play")}</button></span></div></article>`;
  }
  function team() {
    MiningCrew.need(v);  // the engineer levels on the cards
    const T = Object.fromEntries(v.tasks.map(t => [t.id, t])), lead = v.agents.find(a => a.lead);
    const groups = [];
    for (const a of v.agents) {
      if (a === lead) continue;
      const k = a.squad || ""; let g = groups.find(x => x.k === k);
      if (!g) groups.push(g = { k, list: [] });
      g.list.push(a);
    }
    for (const g of groups) g.list.sort((x, y) => y.head - x.head);
    const add = v.agents.length < v.limits.agents ? `<button type="button" class="mw-ag mw-add" data-mw="addagent">${icon("userplus")}<b>Add an agent</b><span class="faint small">From a role, or one of your own (${v.agents.length} of ${v.limits.agents})</span></button>` : "";
    return `<p class="faint small mw-note">${v.comp.autopilot ? "On autopilot, squad leads review their squad's work, the Director reviews the squad leads, and the QA lead reviews the Director. " : ""}Each agent works one task at a time; at most ${v.comp.parallel} work at once. Click an agent to edit it: its instructions, model, squad, or make it a lead.</p>
      ${lead ? `<div class="mw-org-top">${agentCard(lead, T, true)}</div>` : ""}
      <div class="mw-org">${groups.map(g => { const head = g.list.find(a => a.head);
        return `<section class="mw-squad"><h3>${esc(v.squads[g.k] || (g.k ? g.k : "No squad"))}<span class="faint small">${g.list.length}${head ? ` · led by ${esc(head.name)}` : ""}</span></h3>
          <div class="mw-squad-list">${g.list.map(a => agentCard(a, T)).join("")}</div></section>`; }).join("")}</div>${add}
      <div class="mh-card mw-mcp" data-tmc-scope="team:${v.comp.id}"></div>`;  // the team's MCP tools (mcp.js)
  }

  // ---------- the notebook ----------
  function notebook() {
    const A = AG();
    if (!v.notes.length) return `<div class="empty small">The notebook is empty. When a squad lead (or you) approves a task, its finding lands here, and every agent on the team reads it before working.</div>`;
    return `<p class="faint small mw-note">What the team has established: every approved task, newest first. Agents read it before they work${v.notes.some(n => n.journal) ? ", and the Scribe saves each entry to your repository" : ""}.</p>
      <ol class="mw-notes">${v.notes.map(n => { const a = A[n.agent];
        const j = !n.journal ? "" : n.journal === "pending" ? ` · ${icon("clock")}saving` : n.journal.startsWith("failed") ? ` · <span class="mw-late" title="${esc(n.journal)}">${icon("alert")}not saved</span>` : ` · <a href="${esc(n.journal.startsWith("http") ? n.journal : "#")}" target="_blank" rel="noopener noreferrer">${icon("github")}saved</a>`;
        return `<li><details data-mwnote="${n.id}" ${opened.has(n.id) ? "open" : ""}><summary>${av(a, "xs")}<span class="mw-note-t"><b>${esc(n.title)}</b><span class="faint small">${a ? esc(a.name) : "You"} · approved by ${esc(n.reviewer || "?")} · <time data-ts="${n.ts}" title="${stamp(n.ts)}"></time>${j}</span></span></summary>
          <div class="md mw-note-body" id="mw-note-${n.id}">${full[n.id] ? Agents.md(full[n.id]) : `${Agents.md(n.body)}${n.body.length >= 400 ? "…" : ""}`}</div>
          <div class="row">${n.task ? `<button type="button" class="btn sm" data-mwtask="${n.task}">${icon("note")}Open the task</button>` : ""}<button type="button" class="btn sm mw-danger" data-mwnotedel="${n.id}">${icon("trash")}Take it out</button></div></details></li>`; }).join("")}</ol>`;
  }

  // ---------- the sandbox ----------
  function internetCard(s) {  // the team's sandbox internet: egress proxy + gVisor (sandbox.py, egress_proxy.py)
    const n = s.internet || {}, on = s.internet_on;
    const exit = n.exit === "separate" ? "through a separate exit address" : "through this server's own address (no exit proxy is set: abuse reports would land on this server)";
    const btn = s.can_switch ? (on ? `<button type="button" class="btn sm" data-mw="netoff">${icon("ban")}Turn off</button>`
      : `<button type="button" class="btn sm" data-mw="neton" ${n.ready ? "" : "disabled"}>${icon("globe")}Turn on</button>`) : "";
    return `<section class="mh-card mw-net ${on ? "on" : ""}"><h3>${icon("globe")}Internet in the sandbox <span class="faint small">${on ? "on" : "off"}</span>${btn}</h3>
      <p class="faint small">${on ? `Runs reach the public internet ${exit}: git clone over https, pip/npm/go installs, datasets and APIs. Never internal addresses; ports 80 and 443 only; a cap on bytes in and out per run; under gVisor; files that look like secrets (.env, keys, credentials) are held back. Each run lists the hosts it reached.`
        : `Off: runs reach only the model proxy. Agents fetch pages with web_read instead.${s.can_switch ? "" : " An administrator can turn it on."}`}</p>
      ${!on && s.can_switch && !n.ready && n.why ? `<p class="mh-err small">${icon("info")}${esc(n.why)}</p>` : ""}
      ${on && n.ready === false && n.why ? `<p class="mh-err small">${icon("alert")}Runs can't get internet right now, so they won't start: ${esc(n.why)}</p>` : ""}</section>`;
  }
  function netRecord(n) {
    if (!n) return "";
    if (n.error) return `<h4>${icon("globe")}Internet</h4><p class="mh-err small">${esc(n.error)}</p>`;
    const mb = b => `${((b || 0) / 1e6).toFixed(1)} MB`, hosts = Object.entries(n.hosts || {});
    return `<h4>${icon("globe")}Internet <span class="faint small">${mb(n.down_bytes)} in, ${mb(n.up_bytes)} out of ${mb(n.up_cap)} · ${plural(n.connections || 0, "connection")} · ${n.exit === "separate" ? "separate exit address" : "this server's address"}</span></h4>
      ${hosts.length ? `<ul class="mw-net-hosts">${hosts.map(([h, x]) => `<li><code>${esc(h)}</code> <span class="faint small">${plural(x.conns, "connection")} · ${mb(x.down)} in · ${mb(x.up)} out</span></li>`).join("")}</ul>` : `<p class="faint small">No hosts reached.</p>`}
      ${(n.refused || []).length ? `<p class="small"><b>Refused</b></p><ul class="mw-net-hosts">${n.refused.map(x => `<li><code>${esc(x.host)}</code> <span class="faint small">${esc(x.why)}</span></li>`).join("")}</ul>` : ""}
      ${(n.withheld || []).length ? `<p class="faint small">Held back from this run (they look like secrets): ${n.withheld.map(p => `<code>${esc(p)}</code>`).join(", ")}</p>` : ""}`;
  }
  function sandbox() {
    const s = v.sandbox, A = AG();  // the files themselves: MiningFiles (mining-files.js)
    const runs = s.runs.map(r => `<li><button type="button" class="mw-sbx-run" data-mwsbx="${r.id}">${chip(RUN[r.status] || RUN.done)}<code>${esc(r.command.split("\n")[0].slice(0, 90))}</code>
        <span class="faint small">${A[r.agent] ? esc(A[r.agent].name) : esc(r.by_user || "you")} · <time data-ts="${r.started}"></time>${r.finished ? ` · ${dur(r.finished - r.started)}` : ""}${r.exit_code != null ? ` · exit ${r.exit_code}` : ""}${r.cost ? ` · ${fmtNum(r.cost, 3)} USD` : ""}${r.services ? ` · ${esc(r.services.replace(",", ", "))}` : ""}${r.internet ? ` · ${icon("globe")}internet` : ""}</span></button></li>`).join("");
    return `<p class="faint small mw-note">${s.ready ? `Agents keep the team's code and practice tasks here and run them in a throwaway sandbox: Python, Go, Node, git and psql, with PostgreSQL and ClickHouse on localhost when asked for, and ${s.internet_on ? "internet through AXoR's egress proxy" : "no internet"}. Model calls go through a Ridges-style proxy (<code>$SANDBOX_PROXY_URL</code>) within a dollar budget. <code>python .axor/ridges_run.py --agent agent.py tasks/&lt;name&gt;</code> runs the agent the way Ridges does.` : ""}</p>
      ${s.ready ? "" : `<p class="mh-err">${icon("info")}The sandbox isn't available here: ${esc(s.why)} Agents can still write files; they just can't run them.</p>`}
      ${s.ready ? internetCard(s) : ""}
      ${MiningFiles.html("teams")}
      <div class="mw-sbx mw-sbx-runs-only"><section class="mh-card"><h3>${icon("terminal")}Runs<button type="button" class="btn sm" data-mw="run" ${s.ready ? "" : "disabled"}>${icon("play")}Run a command</button></h3>
          ${runs ? `<ul class="mw-sbx-runs">${runs}</ul>` : `<p class="faint small">No runs yet.</p>`}</section></div>`;
  }

  // ---------- activity ----------
  function activity() {
    const A = AG(), T = new Set(v.tasks.map(t => t.id));
    if (!v.events.length) return `<div class="empty small">Nothing yet. The team's work shows up here as it happens.</div>`;
    return `<section class="mh-card"><ol class="hq-feed mh-feed">${v.events.map(e => `<li class="k-${e.kind}">${av(A[e.agent], "xs")}<div>
      <span class="hq-feed-ico">${icon(KIND_ICON[e.kind] || "dots")}</span>${esc(e.text)}${e.task && T.has(e.task) ? ` <button type="button" class="linkbtn" data-mwtask="${e.task}">open</button>` : ""}
      <time data-ts="${e.ts}" title="${stamp(e.ts)}"></time></div></li>`).join("")}</ol></section>`;
  }

  // ---------- dialogs ----------
  function dialog(id, cls) {
    let dlg = document.getElementById(id);
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = id; document.body.append(dlg);
      dlg.addEventListener("click", dlgClick); dlg.addEventListener("submit", dlgSubmit); dlg.addEventListener("change", dlgChange);
      dlg.addEventListener("close", () => { if (id === "mw-task") { task = null; taskId = null; } if (id === "mw-sbx") { sbxId = null; clearTimeout(sbxTimer); } });
    }
    dlg.className = `modal mw-dlg ${cls}`;  // the same dialog serves forms of different widths
    return dlg;
  }
  const x = `<button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>`;
  function modelOptions(cur) {
    if (!models) {
      api("/api/agents/models").then(m => { models = m; $$(".mw-dlg select[name=model]").forEach(s => { const val = s.value; s.innerHTML = modelOptions(val); }); }).catch(() => { models = { providers: [], default: null }; });
      return `<option value="${esc(cur)}">${esc(cur === "auto" ? "The campaign's model" : cur)}</option>`;
    }
    return [`<option value="auto" ${cur === "auto" ? "selected" : ""}>The campaign's model</option>`,
      ...models.providers.filter(p => p.models.length).map(p => `<optgroup label="${esc(p.label)}">${p.models.map(m => `<option value="${esc(m.id)}" ${cur === m.id ? "selected" : ""}>${esc(m.label || m.id)}</option>`).join("")}</optgroup>`)].join("");
  }

  function compForm(edit) {
    const c = edit ? v.comp : null, camps = all.campaigns, cur = v?.campaign.id ?? camps[0]?.id;
    const status = ["upcoming", "active", "closed"].map(s => `<option value="${s}" ${(c?.status || "active") === s ? "selected" : ""}>${CSTATE[s][1]}</option>`).join("");
    const names = all.default_team.map(r => all.roles.find(k => k.id === r)?.name).filter(Boolean);
    const team = `<fieldset class="mw-pick"><legend>Team</legend>
        <label class="mh-check"><input type="radio" name="team" value="auto" checked><span><b>The team for this competition</b> <span class="faint">agents in squads, picked from its name: a Ridges niche team when its page is on ridges.ai, else the 37-agent top miner team</span></span></label>
        ${all.packs.map(p => `<label class="mh-check"><input type="radio" name="team" value="${p.id}"><span><b>${esc(p.label)}</b> <span class="faint">${esc(p.about)}</span></span></label>`).join("")}
        <label class="mh-check"><input type="radio" name="team" value="default"><span><b>A small team</b> <span class="faint">${esc(names[0])} (lead), ${esc(names.slice(1, -1).join(", "))} and ${esc(names.at(-1))}</span></span></label>
        ${all.comps.length ? `<label class="mh-check"><input type="radio" name="team" value="copy"><span><b>Copy another team</b> <span class="faint">its agents, squads, instructions and models</span></span></label>
          <div class="mw-copy" hidden><select name="copy" aria-label="Team to copy">${all.comps.map(k => `<option value="${k.id}" ${k.id === wid ? "selected" : ""}>SN${k.netuid} · ${esc(k.label)} · ${plural(k.agents, "agent")}</option>`).join("")}</select>
            <label class="mh-check"><input type="checkbox" name="carry"><span>Bring its unfinished tasks too</span></label></div>` : ""}
        <label class="mh-check"><input type="radio" name="team" value="empty"><span><b>Start empty</b> <span class="faint">add agents yourself</span></span></label></fieldset>`;
    const extra = c ? `<fieldset class="mw-pick"><legend>Autopilot</legend>
        <div class="mh-row3"><label class="in"><span>The Director plans every</span><select name="plan_every">${[2, 4, 6, 12, 24, 48].map(h => `<option value="${h}" ${c.plan_every === h ? "selected" : ""}>${h} hours</option>`).join("")}</select></label>
          <label class="in"><span>Agents at work at once</span><input name="parallel" type="number" min="1" max="24" value="${c.parallel}"></label>
          <label class="in"><span>Share of emissions <em class="opt">%</em></span><input name="share" type="number" min="0" max="100" step="0.1" value="${c.share != null ? +(c.share * 100).toFixed(1) : ""}" placeholder="e.g. 25"></label></div>
        <p class="faint small">And as soon as the board runs dry (at most every 15 minutes). The Director also plans when you choose Plan now.</p>
        <label class="mh-check"><input type="checkbox" name="relay" ${v.director?.relay !== false ? "checked" : ""}><span><b>Only the Director contacts me</b> <span class="faint">agents' questions, finished work and failed tasks go to the Director, who settles what the team can and sends you one report</span></span></label></fieldset>
        <div class="mh-row"><label class="in"><span>Token budget <em class="opt">per 24 hours, 0 for none</em></span><input name="budget" type="number" min="0" max="20000000" step="10000" value="${c.budget}"></label><span></span></div>
        <label class="in"><span>Standing instructions <em class="opt">every agent here reads them on every task</em></span><textarea name="directive" rows="2" maxlength="600" placeholder="e.g. Keep every change small enough to test in an hour.">${esc(c.directive || "")}</textarea></label>` : team;
    const dlg = dialog("mw-form", "mh-new-dlg");
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwform="${c ? "edit" : "new"}" autocomplete="off">${x}
      <h3>${icon(c ? "gear" : "folderplus")} ${c ? `${esc(c.label)}: settings` : "New competition"}</h3>
      ${c ? "" : `<p class="faint">A team for one competition: its own agents, board, notebook and sandbox. You can change all of it later.</p>
        <label class="in"><span>Campaign <em class="opt">the subnet it's on</em></span><select name="campaign">${camps.map(k => `<option value="${k.id}" ${k.id === cur ? "selected" : ""}>SN${k.netuid} · ${esc(k.title)}${k.comp && k.comp !== "Competition 1" ? ` · ${esc(k.comp)}` : ""}</option>`).join("")}</select></label>`}
      <div class="mh-row3"><label class="in"><span>Number <em class="opt">as the subnet numbers it</em></span><input name="number" type="number" min="0" max="1000000" value="${c ? c.number ?? "" : ""}" placeholder="e.g. 28"></label>
        <label class="in"><span>Name <em class="opt">optional</em></span><input name="name" maxlength="80" value="${esc(c?.name || "")}" placeholder="Database Query Engineering"></label>
        <label class="in"><span>Status</span><select name="status">${status}</select></label></div>
      <div class="mh-row"><label class="in"><span>Starts <em class="opt">optional</em></span><input name="starts" type="date" value="${c?.starts || ""}"></label>
        <label class="in"><span>Ends <em class="opt">optional</em></span><input name="ends" type="date" value="${c?.ends || ""}"></label></div>
      <label class="in"><span>Your goal in it</span><textarea name="goal" rows="2" maxlength="600" placeholder="e.g. Beat the leader by 3% before the round closes.">${esc(c?.goal || "")}</textarea></label>
      <label class="in"><span>Rules, scoring and notes <em class="opt">what the team should know; agents treat it as data</em></span><textarea name="notes" rows="4" maxlength="4000" placeholder="e.g. Scored on hidden tasks; a new agent only earns if it beats the leader.">${esc(c?.notes || "")}</textarea></label>
      <label class="in"><span>Competition page <em class="opt">optional</em></span><input name="link" type="url" maxlength="300" value="${esc(c?.link || "")}" placeholder="https://"></label>
      ${extra}
      <div class="row end">${c ? `<button type="button" class="btn mw-danger" data-mwd="delete">${icon("trash")}Delete</button>` : ""}<button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn primary">${icon(c ? "check" : "folderplus")}${c ? "Save" : "Open the competition"}</button></div></form>`;
    dlg.showModal();
  }

  function taskForm(agent) {
    const ons = v.agents.filter(a => a.on), pick = agent ?? ons[0]?.id ?? "";
    const dlg = dialog("mw-form", "mh-new-dlg");
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwform="task" autocomplete="off">${x}
      <h3>${icon("note")} New task <span class="faint small">${esc(v.comp.label)}</span></h3>
      <label class="in"><span>Task</span><input name="title" required minlength="2" maxlength="160" placeholder="e.g. Find why our agent fails the ClickHouse tasks"></label>
      <label class="in"><span>Details <em class="opt">what to do and what done looks like</em></span><textarea name="detail" rows="4" maxlength="4000"></textarea></label>
      <div class="mh-row3"><label class="in"><span>Assign to</span><select name="agent">${ons.map(a => `<option value="${a.id}" ${a.id === pick ? "selected" : ""}>${esc(a.name)} · ${esc(a.title)}</option>`).join("")}<option value="" ${pick === "" ? "selected" : ""}>You</option></select></label>
        <label class="in"><span>Priority</span><select name="priority"><option value="high">High</option><option value="medium" selected>Medium</option><option value="low">Low</option></select></label>
        <label class="in"><span>Due <em class="opt">optional</em></span><input name="due" type="date"></label></div>
      <label class="mh-check"><input type="checkbox" name="start" ${pick === "" || v.comp.status === "closed" ? "disabled" : "checked"}><span>Start it now <span class="faint">the agent picks it up as soon as it's free${v.comp.autopilot ? " (on autopilot it starts anyway)" : ""}</span></span></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("plus")}Add the task</button></div></form>`;
    dlg.showModal(); $("[name=title]", dlg).focus();
  }

  function planForm() {
    const lead = AG()[v.lead]; if (!lead) return;
    const dlg = dialog("mw-form", "mh-new-dlg");
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwform="plan">${x}
      <div class="hq-dlg-head">${av(lead, "lg")}<div><h3>Plan with ${esc(lead.name)}</h3><div class="faint">${esc(lead.title)} · ${esc(v.comp.label)}</div></div></div>
      <p>${esc(lead.name)} reads the competition, the goal and notes, the notebook, the team and the board, then writes up to ${v.agents.length >= 10 ? 12 : 8} tasks and assigns each one to the teammate best suited, or to you. Tasks already on the board aren't repeated.</p>
      ${v.comp.goal ? "" : `<p class="mh-err">${icon("info")}The competition has no goal yet: add one in its settings for a sharper plan.</p>`}
      <label class="in"><span>A note for ${esc(lead.name)} <em class="opt">optional</em></span><textarea name="note" rows="3" maxlength="600" placeholder="e.g. Two days left: only what we can ship by Sunday."></textarea></label>
      <label class="mh-check"><input type="checkbox" name="start" ${v.comp.autopilot ? "checked disabled" : ""}><span>Start the tasks right away <span class="faint">${v.comp.autopilot ? "on autopilot they start by themselves" : "otherwise they wait in To do for you to look over"}</span></span></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("route")}Plan</button></div></form>`;
    dlg.showModal();
  }

  function agentForm(id) {
    const a = id ? AG()[id] : null, roles = v.roles, r0 = roles[1] || roles[0];
    const dlg = dialog("mw-form", "mh-new-dlg");
    const roleCards = a ? "" : `<fieldset class="mw-roles"><legend>Role</legend>${roles.map(r => `<label class="mw-role"><input type="radio" name="role" value="${r.id}" ${r === r0 ? "checked" : ""}>
        <span>${av(r, "sm")}<span><b>${r.id === "custom" ? "Your own" : esc(r.title)}</b><small>${esc(r.job || "Give it a name, a title and what it does.")}</small></span></span></label>`).join("")}</fieldset>`;
    const squads = `<label class="in"><span>Squad</span><select name="squad"><option value="">No squad</option>${Object.entries(v.squads).map(([k, l]) => `<option value="${k}" ${a?.squad === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwform="${a ? "agent" : "addagent"}" data-id="${a?.id || ""}" autocomplete="off">${x}
      ${a ? `<div class="hq-dlg-head">${av(a, "lg")}<div><h3>${esc(a.name)}</h3><div class="faint">${esc(a.title)}${a.lead ? " · Director" : a.head ? " · squad lead" : ""}</div></div></div>` : `<h3>${icon("userplus")} Add an agent <span class="faint small">${esc(v.comp.label)}</span></h3>`}
      ${roleCards}
      <div class="mh-row"><label class="in"><span>Name</span><input name="name" maxlength="40" ${a ? "required" : ""} value="${esc(a?.name || "")}" placeholder="${esc(r0.name)}"></label>
        <label class="in"><span>Title</span><input name="title" maxlength="60" ${a ? "required" : ""} value="${esc(a?.title || "")}" placeholder="${esc(r0.title)}"></label></div>
      <label class="in"><span>What it does</span><textarea name="job" rows="2" maxlength="400" placeholder="${esc(r0.job)}">${esc(a?.job || "")}</textarea></label>
      <label class="in"><span>Your instructions <em class="opt">optional; it reads them on every task</em></span><textarea name="instructions" rows="3" maxlength="1500" placeholder="e.g. Always compare against the top 3 agents' last submissions.">${esc(a?.instructions || "")}</textarea></label>
      <div class="mh-row"><label class="in"><span>Model</span><select name="model">${modelOptions(a?.model || "auto")}</select></label>${squads}</div>
      ${a ? `<fieldset class="mw-colors"><legend>Colour</legend>${COLORS.map(k => `<label><input type="radio" name="color" value="${k}" ${a.color === k ? "checked" : ""}><span class="av xs c-${k}" title="${k}"></span></label>`).join("")}</fieldset>
        <label class="mh-check"><input type="checkbox" name="head" ${a.head ? "checked" : ""}><span><b>Squad lead</b> <span class="faint">reviews the squad's work on autopilot; one per squad</span></span></label>
        <label class="mh-check"><input type="checkbox" name="lead" ${a.lead ? "checked" : ""}><span><b>Director</b> <span class="faint">plans the competition and reviews the squad leads; one per team</span></span></label>` : ""}
      <div class="row end">${a ? `<button type="button" class="btn mw-danger" data-mwd="remove">${icon("trash")}Remove</button>` : ""}<button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn primary">${icon(a ? "check" : "userplus")}${a ? "Save" : "Add to the team"}</button></div></form>`;
    dlg.showModal();
  }

  function fileForm(f) {
    const dlg = dialog("mw-form", "wide mh-new-dlg");
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwform="file" data-id="${f?.id || ""}" autocomplete="off">${x}
      <h3>${icon("file")} ${f ? esc(f.path) : "New file"} <span class="faint small">${esc(v.comp.label)}</span></h3>
      ${f ? `<p class="faint small">${short(f.size)}B · last written by ${AG()[f.agent_id] ? esc(AG()[f.agent_id].name) : "you"} · ${stamp(f.updated)}</p>` : ""}
      <label class="in"><span>Path <em class="opt">e.g. agent.py or tasks/orders-report/check.sh</em></span><input name="path" required maxlength="200" value="${esc(f?.path || "")}" ${f ? "readonly" : ""} spellcheck="false"></label>
      <label class="in"><span>Content</span><textarea name="content" rows="18" class="mw-code" spellcheck="false" maxlength="${v.limits.file_bytes}">${esc(f?.content || "")}</textarea></label>
      <div class="row end">${f ? `<button type="button" class="btn mw-danger" data-mwd="delfile">${icon("trash")}Delete</button><button type="button" class="btn" data-mwd="copyfile">${icon("copy")}Copy</button>` : ""}<button type="button" class="btn" data-close>Cancel</button>
        <button type="submit" class="btn primary">${icon("check")}Save</button></div></form>`;
    dlg.showModal();
  }
  async function openFile(id) {
    try { const r = await api(`${W}/files/${id}`); fileForm(r.file); } catch (e) { err(e); }
  }

  function runForm() {
    const dlg = dialog("mw-form", "mh-new-dlg");
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwform="run" autocomplete="off">${x}
      <h3>${icon("terminal")} Run in the sandbox <span class="faint small">${esc(v.comp.label)}</span></h3>
      <p class="faint small">A throwaway pod with the team's ${plural(v.files.length, "file")} in its working folder and no internet. Output, exit code and cost land in Runs.</p>
      <div class="mw-presets">${PRESETS.map(([l, cmd, svc], i) => `<button type="button" class="btn sm" data-mwpreset="${i}">${esc(l)}</button>`).join("")}</div>
      <label class="in"><span>Command <em class="opt">bash, in the folder with the files</em></span><textarea name="command" rows="4" class="mw-code" required maxlength="4000" spellcheck="false" placeholder="python .axor/ridges_run.py --agent agent.py tasks/*"></textarea></label>
      <fieldset class="mw-pick"><legend>Databases on localhost</legend><label class="mh-check"><input type="checkbox" name="postgres"><span><b>PostgreSQL</b> <span class="faint">PGHOST, PGUSER… and DATABASE_URL set</span></span></label>
        <label class="mh-check"><input type="checkbox" name="clickhouse"><span><b>ClickHouse</b> <span class="faint">CLICKHOUSE_URL set (HTTP on 8123)</span></span></label></fieldset>
      <div class="mh-row"><label class="in"><span>Time limit</span><select name="timeout">${[[120, "2 minutes"], [300, "5 minutes"], [600, "10 minutes"], [1800, "30 minutes"]].map(([s, l]) => `<option value="${s}" ${s === 600 ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="in"><span>Inference budget <em class="opt">USD, through the proxy</em></span><input name="budget" type="number" min="0" max="10" step="0.05" value="1"></label></div>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("play")}Run</button></div></form>`;
    dlg.showModal();
  }
  async function openRun(id) {
    const dlg = dialog("mw-sbx", "wide");
    sbxId = id; clearTimeout(sbxTimer);
    if (!dlg.open) { dlg.innerHTML = `<div class="hq-dlg-in">${x}${Loading.line("Reading the run…")}</div>`; dlg.showModal(); }
    try {
      const { run: r } = await api(`${W}/sandbox/${id}`); if (sbxId !== id) return;
      const A = AG(), out = $(".mw-out", dlg), atEnd = out && out.scrollTop + out.clientHeight >= out.scrollHeight - 8;
      dlg.innerHTML = `<div class="hq-dlg-in">${x}<div class="hq-dlg-head"><span class="av lg mw-you" aria-hidden="true">${icon("terminal")}</span><div><h3>Sandbox run #${r.id}</h3>
          <div class="faint">${A[r.agent] ? `${esc(A[r.agent].name)} · ${esc(A[r.agent].title)}` : esc(r.by_user || "You")} · ${stamp(r.started)}${r.finished ? ` · ${dur(r.finished - r.started)}` : ""}</div>
          <div class="hq-node-state">${chip(RUN[r.status] || RUN.done)}${r.exit_code != null ? ` <span class="faint small">exit ${r.exit_code}</span>` : ""}${r.services ? ` <span class="faint small">with ${esc(r.services.replace(",", " and "))}</span>` : ""}${r.calls ? ` <span class="faint small">${plural(r.calls, "model call")}, ${fmtNum(r.cost, 3)} USD</span>` : ""}</div></div></div>
        <h4>Command</h4><pre class="mw-cmd">${esc(r.command)}</pre>${r.error ? `<p class="mh-err">${icon("alert")}${esc(r.error)}</p>` : ""}
        <h4>Output ${r.status === "running" ? `<span class="faint small">running…</span>` : ""}<button type="button" class="linkbtn" data-mwcopyout>${icon("copy")}Copy</button></h4>
        <pre class="mw-out">${esc(r.output || (r.status === "running" ? "Waiting for the run to finish…" : "(no output)"))}</pre>
        ${netRecord(r.net)}
        ${r.task ? `<div class="row"><button type="button" class="btn sm" data-mwtask="${r.task}">${icon("note")}Open its task</button></div>` : ""}</div>`;
      dlg.dataset.out = r.output || "";
      const o = $(".mw-out", dlg); if (o && (atEnd || r.status !== "running")) o.scrollTop = o.scrollHeight;
      if (r.status === "running") sbxTimer = setTimeout(() => { if (dlg.open && sbxId === id) openRun(id); }, 2500);
    } catch (e) { if (sbxId === id) dlg.innerHTML = `<div class="hq-dlg-in">${x}<div class="empty">${esc(e.message)}</div></div>`; }
  }

  // ---------- a task ----------
  async function openTask(id) {
    const dlg = dialog("mw-task", "wide mw-task-dlg");
    taskId = id; task = null;
    dlg.innerHTML = `<div class="hq-dlg-in">${x}${Loading.line("Reading the task…")}</div>`;
    if (!dlg.open) dlg.showModal();
    await readTask();
  }
  async function readTask() {
    const id = taskId;
    try { const r = await api(`${W}/tasks/${id}`); if (id !== taskId) return; task = r; drawTask(); }
    catch (e) { const dlg = $("#mw-task"); if (dlg && id === taskId) dlg.innerHTML = `<div class="hq-dlg-in">${x}<div class="empty">${esc(e.message)}</div></div>`; }
  }
  // the board changed under an open task: read it again, unless you're typing in it
  function syncTask() {
    const t = v?.tasks.find(k => k.id === taskId), dlg = $("#mw-task");
    if (!t || !task || !dlg || t.updated === task.task.updated) return;
    if ($$("textarea, input[type=text], input:not([type])", dlg).some(el => el.value.trim() && el.value !== el.defaultValue)) return;
    readTask();
  }
  // what the result rests on (submit_work's evidence and confidence): unsourced claims stand out, so you know what to check
  function evidence(t) {
    const ev = t.evidence || []; if (!ev.length && !t.confidence) return "";
    const bare = ev.filter(e => !(e.source || "").trim()).length;
    return `<details class="mw-ev ${t.confidence === "low" || bare ? "weak" : ""}" ${t.confidence === "low" || bare ? "open" : ""}><summary>${t.confidence ? `<span class="mb-conf c-${esc(t.confidence)}">${esc(t.confidence)} confidence</span>` : ""}${ev.length ? `${ev.length} claim${ev.length === 1 ? "" : "s"}${bare ? `, <b>${bare} without a source</b>` : ", each with a source"}` : "no evidence listed"}</summary>
      ${ev.length ? `<ul>${ev.map(e => `<li>${esc(e.claim)} ${(e.source || "").trim() ? `<code>${esc(e.source)}</code>` : `<span class="mw-nosrc">${icon("alert")}no source</span>`}</li>`).join("")}</ul>` : ""}</details>`;
  }
  // ---------- requirements (D-017): what the words suggest, what is declared, a person's confirmation, the live check ----------
  const RQ = "/api/control/requirements/mw";
  const capName = n => n.value ? `${n.cap}:${n.value}` : n.cap;
  async function drawReqs(id) {
    const el = $(`[data-mwreqs="${id}"]`); if (!el) return;
    let r; try { r = await api(`${RQ}/${id}`); } catch (e) { el.innerHTML = `<h4>${icon("shield")}Requirements</h4><p class="faint small">${esc(e.message)}</p>`; return; }
    if (taskId !== id) return;
    const st = { undeclared: "Not declared", declared: "Declared, not confirmed", confirmed: "Confirmed by a person", verified: "Verified against the environment" }[r.status] || r.status;
    const dec = r.declared ? (r.declared.needs.length ? r.declared.needs.map(n => `<code>${esc(n)}</code>`).join(" ") : "none (no external dependency)") : "";
    const sugg = r.inferred.filter(n => !n.declared);
    el.innerHTML = `<h4>${icon("shield")}Requirements <span class="faint small">${esc(st)}</span></h4>
      ${r.declared ? `<p class="small">Declared: ${dec} <span class="faint">by ${esc(r.declared.by || "?")}</span>${r.confirmed && r.confirmed.current ? ` · confirmed by ${esc(r.confirmed.by)}` : ""}${r.verified ? ` · live check ${r.verified.current ? (r.verified.ok ? "passed" : "failed") : "out of date"}` : ""}</p>` : `<p class="small faint">Nothing declared yet. Suggestions below come from the task's words: they never block it.</p>`}
      ${sugg.length ? `<ul class="mw-req-sugg">${sugg.map(n => `<li><code>${esc(capName(n))}</code> <span class="faint small">“${esc(n.why)}”</span>
        ${n.decision ? `<span class="faint small">${esc(n.decision)} by ${esc(n.by || "?")}</span>` : `<button type="button" class="linkbtn" data-mwreq="accept" data-cap="${esc(n.cap)}" data-val="${esc(n.value || "")}">Accept</button> <button type="button" class="linkbtn" data-mwreq="reject" data-cap="${esc(n.cap)}" data-val="${esc(n.value || "")}">Reject</button>`}</li>`).join("")}</ul>` : ""}
      <div class="row"><input class="mw-req-in" data-mwreqin value="${esc(r.declared ? r.declared.needs.join(", ") : "")}" placeholder="docker, registry, credential:NAME… (empty = none)" aria-label="Declared requirements">
        <button type="button" class="btn sm" data-mwreq="declare">Declare</button>
        ${r.declared && !(r.confirmed && r.confirmed.current) ? `<button type="button" class="btn sm" data-mwreq="confirm">Confirm</button>` : ""}</div>`;
  }
  async function reqAct(b) {
    const id = taskId, act = b.dataset.mwreq; b.disabled = true;
    try {
      if (act === "declare") { const raw = $("[data-mwreqin]")?.value || ""; await api(`${RQ}/${id}`, { method: "PUT", body: { needs: raw.split(",").map(x => x.trim()).filter(Boolean) } }); }
      else if (act === "confirm") await api(`${RQ}/${id}/confirm`, { method: "POST", body: { note: "" } });
      else await api(`${RQ}/${id}/decide`, { method: "POST", body: { cap: b.dataset.cap, value: b.dataset.val || null, decision: act === "accept" ? "accepted" : "rejected" } });
      drawReqs(id);
    } catch (e) { b.disabled = false; Auth.toast(e.message); }
  }

  function drawTask() {
    const t = task.task, A = AG(), a = A[t.agent], busy = ["queued", "working"].includes(t.status), from = origin(t, A), dlg = $("#mw-task"), rv = A[t.reviewer];
    if (!dlg) return;
    const opts = [...v.agents.map(g => `<option value="${g.id}" ${g.id === t.agent ? "selected" : ""} ${g.on || g.id === t.agent ? "" : "disabled"}>${esc(g.name)} · ${esc(g.title)}${g.on ? "" : " (off)"}</option>`), `<option value="" ${t.agent == null ? "selected" : ""}>You</option>`].join("");
    const review = ["review", "checking"].includes(t.status) ? `<section class="mw-review"><h4>${icon("eye")}${t.status === "checking" ? `${esc(rv?.name || "A squad lead")} is reviewing it` : "Your review"}</h4>
        <p>${t.status === "checking" ? "You can step in: your decision replaces the reviewer's. " : ""}Approve to close it (it goes into the notebook), or send it back with what to change: ${esc(a?.name || "the agent")} reworks the result with your feedback.</p>
        <form data-mwform="review"><textarea name="feedback" rows="3" maxlength="2000" aria-label="What to change" placeholder="e.g. Good, but check it against the ClickHouse tasks too."></textarea>
          <div class="row"><button type="button" class="btn primary sm" data-mwt="approve">${icon("check")}Approve</button><button type="submit" class="btn sm">${icon("undo")}Send back</button></div></form></section>` : "";
    const question = t.status === "blocked" ? `<section class="mw-review q"><h4>${icon("chat")}${esc(a?.name || "The agent")} needs you</h4><p class="mw-q">${esc(t.question || "")}</p>
        <form data-mwform="answer"><textarea name="feedback" rows="2" maxlength="2000" required aria-label="Your answer" placeholder="Your answer"></textarea>
          <div class="row"><button type="submit" class="btn primary sm">${icon("send")}Answer and continue</button><button type="button" class="btn sm" data-mwt="done">${icon("check")}Mark done yourself</button></div></form></section>` : "";
    // a task an agent left for the user: it closes with what they give back (mining_work.update_task refuses it empty)
    const asked = !a && /^(agent|plan):/.test(t.origin || "") && !(t.result || "").trim() && t.status === "todo";
    const askSec = asked ? `<section class="mw-review q"><h4>${icon("chat")}The team asked you for this</h4>
        <p class="faint small">Give them what they need, or say why it isn't needed. It goes back to the team as this task's result. Data on a public page they can now read themselves (web_read): say so.</p>
        <form data-mwform="giveanswer"><textarea name="answer" rows="4" maxlength="4000" required aria-label="Your answer" placeholder="e.g. the numbers, a link, or: not needed, because…"></textarea>
          <div class="row"><button type="submit" class="btn primary sm">${icon("send")}Send and close</button></div></form></section>` : "";
    const result = (busy ? `<p class="mw-busy"><span class="ci ci-${t.status === "working" ? "run" : "wait"}"></span>${esc(a?.name || "The agent")} ${t.status === "working" ? (t.runs > 1 ? "is reworking it…" : "is working on it…") : "has it in the queue and starts when free."}</p>` : "")
      + (t.result ? `<h4 class="mw-res-h">${busy ? "Last result" : "Result"}${t.summary ? ` <span class="faint">${esc(t.summary)}</span>` : ""}<button type="button" class="linkbtn" data-mwcopy>${icon("copy")}Copy</button></h4>${evidence(t)}<div class="md mw-result">${Agents.md(t.result)}</div>` : "");
    const hold = t.hold === "failed" ? "It failed twice in a row, so autopilot leaves it to you: start it again, reassign it, or mark it done." : t.hold === "stopped" ? "You stopped it, so autopilot leaves it alone until you start it again." : t.hold === "retry" ? `It failed on something passing, so the Autoloop starts it again${t.retry_at ? ` at ${new Date(t.retry_at * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}` : " soon"}.` : "";
    dlg.innerHTML = `<div class="hq-dlg-in">${x}
      <div class="hq-dlg-head">${av(a, "lg")}<div><h3>${esc(t.title)}</h3><div class="faint">${a ? `${esc(a.name)} · ${esc(a.title)}` : "Your task"} · ${PRI[t.priority]} priority${t.due ? ` · due ${day(t.due)}` : ""}${from ? ` · ${from}` : ""}</div>
        <div class="hq-node-state">${chip(TS[t.status])}${t.runs ? ` <span class="faint small">${plural(t.runs, "run")}</span>` : ""}${t.checks ? ` <span class="faint small">sent back ${plural(t.checks, "time")} by reviewers</span>` : ""}</div></div></div>
      ${t.detail ? `<div class="md mw-detail">${Agents.md(t.detail)}</div>` : ""}
      ${t.note ? `<p class="mw-note-line">${icon("info")}${esc(t.note)}</p>` : ""}${hold ? `<p class="mw-note-line">${icon("ban")}${esc(hold)}</p>` : ""}
      ${question}${askSec}${review}${result}
      <section class="mw-reqs" data-mwreqs="${t.id}"><h4>${icon("shield")}Requirements</h4><p class="faint small">Reading…</p></section>
      <form data-mwform="taskedit" class="mh-new mw-taskedit"><h4>Assignment</h4>
        <div class="mh-row3"><label class="in"><span>Assigned to</span><select name="agent" ${busy || t.status === "checking" ? "disabled" : ""}>${opts}</select></label>
          <label class="in"><span>Priority</span><select name="priority">${Object.entries(PRI).map(([k, l]) => `<option value="${k}" ${t.priority === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="in"><span>Due</span><input name="due" type="date" value="${t.due || ""}"></label></div>
        ${busy || t.status === "checking" ? "" : `<details class="mw-more"><summary>Edit the task</summary><label class="in"><span>Task</span><input name="title" minlength="2" maxlength="160" value="${esc(t.title)}"></label>
          <label class="in"><span>Details</span><textarea name="detail" rows="4" maxlength="4000">${esc(t.detail || "")}</textarea></label></details>`}
        <div class="row mw-trow">${busy || t.status === "checking" ? `<button type="button" class="btn sm" data-mwt="cancel">${icon("stop")}${t.status === "checking" ? "Stop the review" : "Stop"}</button>` : ""}
          ${t.status === "todo" && a ? `<button type="button" class="btn primary sm" data-mwt="start" ${a.on && v.comp.status !== "closed" ? "" : "disabled"}>${icon("play")}${t.runs ? "Run again" : "Start"}</button>` : ""}
          ${!busy && !asked && !["done", "blocked", "checking"].includes(t.status) ? `<button type="button" class="btn sm" data-mwt="done">${icon("check")}Mark done</button>` : ""}
          ${t.status === "done" ? `<button type="button" class="btn sm" data-mwt="reopen">${icon("undo")}Reopen</button>` : ""}
          <button type="submit" class="btn sm">${icon("check")}Save</button>
          ${busy || t.status === "checking" ? "" : `<button type="button" class="btn sm mw-danger" data-mwt="delete">${icon("trash")}Delete</button>`}</div></form>
      ${task.runs.length ? `<h4>Runs <span class="faint small">open one for its trace: each model and tool call with its input and output</span></h4><ol class="mw-runs">${task.runs.map(r => `<li>
          <button type="button" class="mw-run" data-mwrun="${r.id}" aria-expanded="false">${av(A[r.agent], "xs")}<span>${esc(A[r.agent]?.name || "An agent")}${r.kind === "review" ? " · review" : ""}</span>${chip(RUN[r.status] || RUN.done)}
            <span class="faint small">${stamp(r.started)} · ${r.finished ? dur(r.finished - r.started) : "running"} · ${short(r.tokens)} tokens${r.model ? ` · ${esc(r.model.split(":").pop())}` : ""}</span></button>
          ${r.kind === "review" && r.summary ? `<p class="mw-fb">${icon("eye")}<span>${esc(r.summary)}</span></p>` : ""}${r.feedback ? `<p class="mw-fb">${icon("chat")}<span>With feedback: ${esc(r.feedback)}</span></p>` : ""}${r.error ? `<p class="mh-err small">${icon("alert")}${esc(r.error)}</p>` : ""}
          <div class="mw-trace" id="mw-trace-${r.id}" hidden></div></li>`).join("")}</ol>` : ""}</div>`;
    drawReqs(t.id);  // D-017: loaded on its own: a slow read never holds the task up
  }
  async function trace(btn) {
    const id = btn.dataset.mwrun, el = $(`#mw-trace-${id}`); if (!el) return;
    const open = el.hidden; el.hidden = !open; btn.setAttribute("aria-expanded", open);
    if (!open || el.dataset.done) return;
    el.innerHTML = Loading.line("Reading the trace…");
    try {
      const r = await api(`${W}/runs/${id}`), sp = r.spans;
      el.dataset.done = r.run.status === "running" ? "" : "1";
      el.innerHTML = sp.length ? `<ol class="mw-spans">${sp.map(s => `<li><details><summary>${icon(s.kind === "model" ? "sparkle" : "wrench")}<span>${esc(s.kind === "model" ? `Model · ${s.name}` : s.name.replace(/_/g, " "))}</span>${s.error ? icon("alert") : ""}
          <span class="faint small">${dur(s.end - s.ts)}${s.tokens ? ` · ${short(s.tokens)} tokens` : ""}</span></summary>
          ${s.input ? `<b>${s.kind === "model" ? "Input" : "Arguments"}</b><pre>${esc(s.input)}</pre>` : ""}${s.output ? `<b>${s.kind === "model" ? "Answer" : "Result"}</b><pre>${esc(s.output)}</pre>` : ""}</details></li>`).join("")}</ol>`
        : `<p class="faint small">No steps recorded.</p>`;
    } catch (e) { el.innerHTML = `<p class="mh-err small">${esc(e.message)}</p>`; }
  }

  // ---------- actions ----------
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }
  async function selectComp(id) {
    wid = id; store.set("mw.w", id); v = null; allDone = false; who = "all"; render();
    try { const nv = await api(`${W}/comps/${id}`); if (wid === id) apply(nv); } catch (e) { err(e); }
  }
  const patch = (body, btn) => busy(btn, async () => { const nv = await api(`${W}/comps/${v.comp.id}`, { method: "PATCH", body }); apply(nv); return nv; });
  async function taskAct(k, btn) {
    const t = task?.task; if (!t) return;
    const go = (path, body, method = "POST") => busy(btn, async () => { const nv = await api(`${W}/tasks/${t.id}${path}`, { method, body }); apply(nv); return nv; });
    if (k === "approve") { if (await go("/review", { decision: "approve" })) { Auth.toast("Approved: it's in the notebook"); $("#mw-task").close(); } return; }
    if (k === "start") { if (await go("/start", {})) { Auth.toast(`${AG()[t.agent]?.name || "The agent"} has it`); readTask(); } return; }
    if (k === "cancel") { if (await go("/cancel", {})) { Auth.toast("Stopping"); readTask(); } return; }
    if (k === "done" || k === "reopen") { if (await go("", { status: k === "done" ? "done" : "todo" }, "PATCH")) readTask(); return; }
    if (k === "delete") {
      await UI.confirm({ title: "Delete this task?", body: `“${esc(t.title)}”, its result and its runs go. This can't be undone.`, ok: "Delete",
        run: async () => { apply(await api(`${W}/tasks/${t.id}`, { method: "DELETE" })); $("#mw-task").close(); Auth.toast("Task deleted"); } }).catch(err);
    }
  }
  async function dlgClick(e) {
    const dlg = e.currentTarget, t = e.target;
    if (t === dlg || t.closest("[data-close]")) return dlg.close();
    const rq = t.closest("[data-mwreq]"); if (rq) return reqAct(rq);
    const cp = t.closest("[data-mwcopy]"); if (cp) { navigator.clipboard?.writeText(task?.task.result || "").then(() => Auth.toast("Copied")); return; }
    const co = t.closest("[data-mwcopyout]"); if (co) { navigator.clipboard?.writeText(dlg.dataset.out || "").then(() => Auth.toast("Copied")); return; }
    const tk = t.closest("[data-mwtask]"); if (tk) { dlg.close(); return openTask(+tk.dataset.mwtask); }
    const pr = t.closest("[data-mwpreset]");
    if (pr) {
      const [, cmd, svc] = PRESETS[+pr.dataset.mwpreset], f = $("form", dlg);
      f.elements.command.value = cmd; f.elements.postgres.checked = svc.includes("postgres"); f.elements.clickhouse.checked = svc.includes("clickhouse"); return;
    }
    const run = t.closest("[data-mwrun]"); if (run) return trace(run);
    const ta = t.closest("[data-mwt]"); if (ta) return taskAct(ta.dataset.mwt, ta);
    const d = t.closest("[data-mwd]"); if (!d) return;
    const f = $("form", dlg);
    if (d.dataset.mwd === "delete") {
      const c = v.comp;
      await UI.confirm({ title: `Delete the ${esc(c.label)} team?`, body: "Its agents, tasks, results, notebook, files and traces go too. This can't be undone.", ok: "Delete", typed: c.label,
        run: async () => { await api(`${W}/comps/${c.id}`, { method: "DELETE" }); dlg.close(); Auth.toast("Team deleted"); v = null; wid = null; store.set("mw.w", null); await load(); } }).catch(err);
    }
    if (d.dataset.mwd === "remove") {
      const a = AG()[+f.dataset.id]; if (!a) return;
      await UI.confirm({ title: `Take ${esc(a.name)} off the team?`, body: "Their open tasks stay on the board, assigned to you, so you can hand them to someone else.", ok: "Remove",
        run: async () => { apply(await api(`${W}/comps/${v.comp.id}/agents/${a.id}`, { method: "DELETE" })); dlg.close(); } }).catch(err);
    }
    if (d.dataset.mwd === "delfile") {
      await UI.confirm({ title: `Delete ${esc(f.elements.path.value)}?`, body: "The team loses the file. This can't be undone.", ok: "Delete",
        run: async () => { apply(await api(`${W}/files/${f.dataset.id}`, { method: "DELETE" })); dlg.close(); Auth.toast("File deleted"); } }).catch(err);
    }
    if (d.dataset.mwd === "copyfile") navigator.clipboard?.writeText(f.elements.content.value).then(() => Auth.toast("Copied"));
  }
  function dlgChange(e) {
    const f = e.target.form; if (!f) return;
    if (e.target.name === "team") { const c = $(".mw-copy", f); if (c) c.hidden = e.target.value !== "copy"; }
    if (f.dataset.mwform === "task" && e.target.name === "agent") { const s = f.elements.start; s.disabled = !e.target.value || v.comp.status === "closed"; s.checked = !s.disabled; }
    if (f.dataset.mwform === "addagent" && e.target.name === "role") {
      const r = v.roles.find(k => k.id === e.target.value) || {};
      f.elements.name.placeholder = r.name || "e.g. Nova"; f.elements.title.placeholder = r.title || "e.g. Prompt Engineer"; f.elements.job.placeholder = r.job || "What it does on the team";
      f.elements.name.required = f.elements.title.required = r.id === "custom";
    }
  }
  async function dlgSubmit(e) {
    e.preventDefault();
    const f = e.target, dlg = e.currentTarget, btn = $("button[type=submit]", f), val = n => f.elements[n]?.value ?? "", k = f.dataset.mwform;
    const send = (path, body, method = "POST") => busy(btn, () => api(`${W}${path}`, { method, body }));
    const comp = () => ({ number: val("number") === "" ? null : +val("number"), name: val("name").trim(), status: val("status"), starts: val("starts"), ends: val("ends"),
      goal: val("goal"), notes: val("notes"), link: val("link").trim() });
    if (k === "new") {
      const team = f.elements.team?.value || "auto";
      const nv = await send(`/campaigns/${val("campaign")}/comps`, { ...comp(), team: team === "copy" ? val("copy") : team, carry: team === "copy" && !!f.elements.carry?.checked });
      if (!nv) return;
      dlg.close(); wid = nv.comp.id; store.set("mw.w", wid); sub = "status"; store.set("mw.sub2", sub); v = nv;
      Auth.toast(`${nv.comp.label} is open${nv.agents.length ? `: ${plural(nv.agents.length, "agent")} on the team` : ""}`); await load(); return;
    }
    if (k === "giveanswer") {
      const nv = await send(`/tasks/${task.task.id}`, { status: "done", answer: val("answer").trim() }, "PATCH");
      if (nv) { apply(nv); Auth.toast("Sent to the team"); readTask(); } return;
    }
    if (k === "edit") {
      const nv = await send(`/comps/${v.comp.id}`, { ...comp(), budget: +val("budget") || 0, directive: val("directive"), plan_every: +val("plan_every"), parallel: +val("parallel") || 4, relay: !!f.elements.relay?.checked,
        ...(val("share") === "" ? {} : { share: Math.min(1, Math.max(0, +val("share") / 100)) }) }, "PATCH");
      if (nv) { dlg.close(); apply(nv); Auth.toast("Saved"); } return;
    }
    if (k === "task") {
      const nv = await send(`/comps/${v.comp.id}/tasks`, { title: val("title"), detail: val("detail"), priority: val("priority"), due: val("due"),
        agent: val("agent") === "" ? null : +val("agent"), start: !!f.elements.start.checked && !f.elements.start.disabled });
      if (nv) { dlg.close(); apply(nv); Auth.toast(f.elements.start.checked && val("agent") ? "Added and started" : "Task added"); } return;
    }
    if (k === "plan") {
      const nv = await send(`/comps/${v.comp.id}/plan`, { note: val("note"), start: v.comp.autopilot || !!f.elements.start.checked });
      if (nv) { dlg.close(); apply(nv); Auth.toast(`${AG()[nv.lead]?.name || "The lead"} is planning`); } return;
    }
    if (k === "addagent") {
      const nv = await send(`/comps/${v.comp.id}/agents`, { role: f.elements.role.value, name: val("name"), title: val("title"), job: val("job"), instructions: val("instructions"),
        model: val("model") || "auto", squad: val("squad") });
      if (nv) { dlg.close(); apply(nv); Auth.toast("Welcome to the team"); } return;
    }
    if (k === "agent") {
      const a = AG()[+f.dataset.id];
      const nv = await send(`/comps/${v.comp.id}/agents/${a.id}`, { name: val("name"), title: val("title"), job: val("job"), instructions: val("instructions"), model: val("model") || "auto",
        ...(f.elements.color.value ? { color: f.elements.color.value } : {}), squad: val("squad"), ...(val("squad") ? { head: f.elements.head.checked } : {}), lead: f.elements.lead.checked }, "PATCH");
      if (nv) { dlg.close(); apply(nv); Auth.toast("Saved"); } return;
    }
    if (k === "file") {
      const nv = await send(`/comps/${v.comp.id}/files`, { path: val("path").trim(), content: val("content") }, "PUT");
      if (nv) { dlg.close(); apply(nv); Auth.toast("Saved"); } return;
    }
    if (k === "run") {
      const nv = await send(`/comps/${v.comp.id}/sandbox`, { command: val("command"), services: ["postgres", "clickhouse"].filter(s => f.elements[s].checked), timeout: +val("timeout"), budget: +val("budget") || 1 });
      if (nv) { dlg.close(); sub = "sandbox"; store.set("mw.sub2", sub); apply(nv); Auth.toast("Running in the sandbox"); openRun(nv.sandbox.runs[0].id); } return;
    }
    if (f.dataset.mwcform === "split") {
      const h = await busy(btn, () => api(`${W}/campaigns/${ccid}/split`, { method: "POST", body: { pool: +val("pool") } }));
      if (h) { chome = h; dlg.close(); crender(); Auth.toast("Budgets shared"); } return;
    }
    const t = task?.task; if (!t) return;
    if (k === "review" || k === "answer") {
      const fb = val("feedback").trim(); if (!fb) { Auth.toast(k === "answer" ? "Write your answer first" : "Say what to change"); f.elements.feedback.focus(); return; }
      const nv = await send(`/tasks/${t.id}/review`, { decision: "revise", feedback: fb });
      if (nv) { apply(nv); Auth.toast(`Sent back to ${AG()[t.agent]?.name || "the agent"}`); readTask(); } return;
    }
    if (k === "taskedit") {
      const body = { priority: val("priority"), due: val("due") };
      if (f.elements.title) Object.assign(body, { title: val("title"), detail: val("detail") });
      const ag = f.elements.agent;
      if (!ag.disabled && ag.value !== String(t.agent ?? "")) Object.assign(body, ag.value === "" ? { unassign: true } : { agent: +ag.value });
      const nv = await send(`/tasks/${t.id}`, body, "PATCH");
      if (nv) { apply(nv); Auth.toast("Saved"); readTask(); }
    }
  }

  function wire() {
    if (wired) return; const el = root(); if (!el) return; wired = true;
    MiningCrew.wire(el);  // the diagram, roadmap, prompts, levels and links (mining-crew.js)
    MiningDirector.wire(el);  // the Director's report (mining-director.js)
    MiningStatus.wire(el);  // the team's status (mining-status.js)
    MissionTeam.wire(el);  // the team's missions, Start mission and the chain of command (mission-team.js, command-map.js)
    MiningAutoloop.wire(el);  // the Autoloop's governor, queue and rules (mining-autoloop.js)
    MiningUpgrade.wire(el);  // the Agent Upgrade Factory (mining-upgrade.js)
    MiningTopMiner.wire(el);  // Top miner: roadmap, validation set, scorecard, elite team, first mission (mining-topminer.js)
    MiningBench.wire(el);  // the Workflow and Files (mining-bench.js)
    MiningFiles.wire(el, "teams");  // the team's files beside My workspace's, under Files & sandbox (mining-files.js)
    el.addEventListener("click", async e => {
      const t = e.target;
      const c = t.closest("[data-mwcomp]"); if (c) return selectComp(+c.dataset.mwcomp);
      const vw = t.closest("[data-mwview]"); if (vw) return setView(vw.dataset.mwview);
      const s = t.closest("[data-mwsub]"); if (s) { sub = s.dataset.mwsub; store.set("mw.sub2", sub); return render(); }
      const tk = t.closest("[data-mwtask]"); if (tk) return openTask(+tk.dataset.mwtask);
      const ed = t.closest("[data-mwedit]"); if (ed) return agentForm(+ed.dataset.mwedit);
      const nf = t.closest("[data-mwnewfor]"); if (nf) return taskForm(+nf.dataset.mwnewfor);
      const fl = t.closest("[data-mwfile]"); if (fl) return openFile(+fl.dataset.mwfile);
      const sb = t.closest("[data-mwsbx]"); if (sb) return openRun(+sb.dataset.mwsbx);
      const nd = t.closest("[data-mwnotedel]");
      if (nd) return UI.confirm({ title: "Take this entry out of the notebook?", body: "Agents stop reading it. The task and its result stay.", ok: "Take it out",
        run: async () => { apply(await api(`${W}/notes/${nd.dataset.mwnotedel}`, { method: "DELETE" })); } }).catch(err);
      const on = t.closest("[data-mwon]");
      if (on) {
        const a = AG()[+on.dataset.mwon]; if (!a) return;
        const nv = await busy(on, () => api(`${W}/comps/${v.comp.id}/agents/${a.id}`, { method: "PATCH", body: { on: !a.on } }));
        if (nv) { apply(nv); Auth.toast(a.on ? `${a.name} is off the team` : `${a.name} is back`); }
        return;
      }
      const b = t.closest("[data-mw]"); if (!b) return;
      const k = b.dataset.mw;
      if (k === "new") return compForm(false);
      if (k === "edit") return compForm(true);
      if (k === "addtask") return taskForm(null);
      if (k === "import") return MiningImport.open(v.comp.id);  // mining-import.js
      if (k === "addagent") return agentForm(null);
      if (k === "plan") return planForm();
      if (k === "newfile") return fileForm(null);
      if (k === "run") return runForm();
      if (k === "intake") return MiningSources.open("queue");  // mining-sources.js
      if (k === "hq") return toHQ();
      if (k === "portfolio") return setView("portfolio");
      if (k === "alldone") { allDone = true; return render(); }
      if (k === "neton") {
        const n = v.sandbox.internet || {};
        return UI.confirm({ title: `Give the ${esc(v.comp.label)} sandbox internet?`, ok: "Turn on",
          body: `Code the agents run can then reach any public site: clone, install and download. It never reaches this server or the cluster, runs under gVisor, sends at most a capped number of bytes out per run, and every host it reaches is recorded. ${n.exit === "separate" ? "Traffic leaves through the separate exit address." : "<b>No exit proxy is set, so traffic leaves through this server's own address.</b>"}`,
          run: async () => { if (await patch({ internet: true }, b)) Auth.toast("The sandbox has internet"); } }).catch(err);
      }
      if (k === "netoff") { if (await patch({ internet: false }, b)) Auth.toast("The sandbox's internet is off"); return; }
      if (k === "pause" || k === "resume") { if (await patch({ paused: k === "pause" }, b)) Auth.toast(k === "pause" ? "Paused: nothing new starts" : "Resumed"); return; }
      if (k === "stop") {
        return UI.confirm({ title: `Stop the ${esc(v.comp.label)} team now?`, body: "Work in progress stops where it is (queued tasks go back to To do) and the team is paused until you resume it.", ok: "Stop",
          run: async () => { apply(await api(`${W}/comps/${v.comp.id}/stop`, { method: "POST" })); Auth.toast("Stopped"); } }).catch(err);
      }
      if (k === "startall") {
        const nv = await busy(b, () => api(`${W}/comps/${v.comp.id}/start`, { method: "POST" }));
        if (nv) { apply(nv); Auth.toast(`${plural(nv.started, "task")} started`); }
      }
    });
    el.addEventListener("change", async e => {
      if (e.target.matches("[data-mwwho]")) { who = e.target.value; allDone = false; return render(); }
      if (e.target.matches("[data-mwpilot]")) {
        const want = e.target.checked;
        if (await patch({ autopilot: want })) Auth.toast(want ? "Autopilot on: the team runs itself" : "Autopilot off");
        else e.target.checked = !want;
      }
    });
    el.addEventListener("toggle", async e => {
      if (e.target.matches?.(".mw-desc")) { e.target.open ? opened.add("desc") : opened.delete("desc"); return; }
      const d = e.target.closest?.("[data-mwnote]"); if (!d) return;
      const id = +d.dataset.mwnote;
      if (!d.open) { opened.delete(id); return; }
      opened.add(id);
      if (full[id]) return;
      try { const { note } = await api(`${W}/notes/${id}`); full[id] = note.body; const b = $(`#mw-note-${id}`); if (b) b.innerHTML = Agents.md(note.body); } catch (er) { err(er); }
    }, true);
  }

  // ---------- the control room: My subnets → a campaign → Teams ----------
  function control(cid) {
    if (cid !== ccid) { ccid = cid; chome = null; cfailed = ""; }
    setTimeout(() => { cwire(); if (!chome || Date.now() - cloaded > 3000) cload(); else crender(); }, 0);
    return `<div class="mw-room" id="mwc" data-cid="${cid}">${Loading.line("Reading the teams…")}</div>`;
  }
  async function cload() {
    const at = ccid; if (at == null) return;
    try { const h = await api(`${W}/campaigns/${at}`); if (at !== ccid) return; chome = h; cfailed = ""; cloaded = Date.now(); MiningSources.peek(); }
    catch (e) { if (at === ccid) cfailed = e.message; }
    crender(); cschedule();
  }
  function cschedule() {
    clearTimeout(ctimer);
    ctimer = setTimeout(() => { if (!$("#mwc")) return; if ($("#view-mining")?.hidden || document.visibilityState !== "visible") return cschedule(); cload(); },
      chome?.comps.some(c => c.working || c.busy) ? 3000 : 15000);
  }
  function count(cid) { return cid === ccid && chome ? chome.comps.reduce((s, c) => s + (c.waiting || 0), 0) : 0; }
  function crender() {
    const el = $("#mwc"); if (!el || +el.dataset.cid !== ccid) return;
    if (!chome) { put(el, cfailed ? `<div class="empty">${esc(cfailed)}</div>` : Loading.line("Reading the teams…")); return; }
    const h = chome;
    const row = c => {
      const [dot, st] = tstate(c), share = c.budget ? Math.min(1, c.day / c.budget) : 0, closed = c.status === "closed";
      return `<tr class="${closed ? "closed" : ""}"><th scope="row"><button type="button" class="linkbtn mw-room-open" data-mwcopen="${c.id}"><b>${c.number != null ? `${c.number} · ` : ""}${esc(c.name || c.label)}</b></button>
          <span class="faint small">${CSTATE[c.status][1]}${c.source === "ridges" ? " · from Ridges" : ""}</span></th>
        <td><label class="mw-switch sm" title="${c.autopilot ? "Switch autopilot off" : "Switch autopilot on"}"><input type="checkbox" data-mwcpilot="${c.id}" aria-label="Autopilot for ${esc(c.label)}" ${c.autopilot ? "checked" : ""} ${closed ? "disabled" : ""}><span aria-hidden="true"></span></label>
          <span class="mw-room-st"><span class="ci ci-${dot}"></span>${esc(st)}</span>${c.pilot_note && c.autopilot && !c.paused ? `<span class="mh-err small" title="${esc(c.pilot_note)}">${icon("info")}</span>` : ""}</td>
        <td>${c.working} at work<span class="faint small"> · ${c.active}/${c.agents} on</span></td>
        <td>${c.waiting ? `<b class="mw-waiting">${c.waiting}</b>` : `<span class="faint">0</span>`}</td>
        <td><div class="mw-bar sm" role="progressbar" aria-valuemin="0" aria-valuemax="${c.budget || 0}" aria-valuenow="${c.day}" aria-label="Tokens today"><i style="--w:${(share * 100).toFixed(1)}%"></i></div><span class="faint small ${share >= 1 ? "mw-late" : ""}">${short(c.day)} of ${c.budget ? short(c.budget) : "no limit"}</span></td>
        <td>${c.share != null ? pct(c.share) : `<span class="faint">—</span>`}</td>
        <td class="mw-room-act">${(c.autopilot || c.paused) && !closed ? `<button type="button" class="btn sm" data-mwcpause="${c.id}" data-on="${c.paused ? 0 : 1}">${icon(c.paused ? "play" : "stop")}${c.paused ? "Resume" : "Pause"}</button>` : ""}
          ${c.working || c.busy ? `<button type="button" class="btn sm mw-danger" data-mwcstop="${c.id}">${icon("ban")}Stop</button>` : ""}
          <button type="button" class="btn sm" data-mwcopen="${c.id}">${icon("external")}Open</button></td></tr>`;
    };
    put(el, `<section class="mh-card mw-room-head"><div><h3>${icon("users")}Competition teams on SN${h.campaign.netuid}</h3>
        <p class="faint small">An agent team per competition. Switch autopilot on and a team runs itself: the Director plans, tasks start on their own, squad leads review. Stop halts the work in progress; Pause lets it finish.</p></div>
      <div class="mw-room-btns"><button type="button" class="btn sm" data-mwc="intake">${icon("download")}Import competitions<span class="hq-n alert cin-badge" ${MiningSources.count() ? "" : "hidden"}>${MiningSources.count() || ""}</span></button>
        <button type="button" class="btn sm" data-mwc="split" ${h.comps.length ? "" : "disabled"}>${icon("coins")}Share a daily budget</button>
        <button type="button" class="btn sm" data-mwc="page">${icon("users")}Competition teams</button>
        <button type="button" class="btn sm mw-danger" data-mwc="stopall">${icon("ban")}Stop every team</button></div></section>
      ${h.comps.length ? `<div class="mw-room-wrap"><table class="mw-room-t"><thead><tr><th scope="col">Competition</th><th scope="col">Autopilot</th><th scope="col">Team</th><th scope="col">Waiting for you</th><th scope="col">Tokens today</th><th scope="col">Emissions</th><th scope="col" aria-label="Actions"></th></tr></thead>
        <tbody>${h.comps.map(row).join("")}</tbody></table></div>`
        : `<div class="empty small">No competition teams on this campaign yet. <button type="button" class="linkbtn" data-mwc="intake">Import its competitions</button> to review and approve a team for each. <button type="button" class="linkbtn" data-mwc="page">Open Competition teams</button></div>`}`);
    $$("time[data-ts]", el).forEach(t => { t.textContent = ago(+t.dataset.ts); });
    const tab = $('#mining [data-mhtab="work"]');
    if (tab) { const n = count(ccid); let s = $(".hq-n", tab); if (!s && n) { s = document.createElement("span"); s.className = "hq-n alert"; tab.append(s); } if (s) s.textContent = n || ""; }
  }
  function openPage(id) { if (id) { wid = id; store.set("mw.w", id); v = null; } const b = $("#nav-teams"); if (b && !b.hidden) b.click(); else location.hash = "#teams"; }
  function splitForm() {
    const dlg = dialog("mw-form", "mh-new-dlg"), open = chome.comps.filter(c => c.status !== "closed"), known = open.some(c => c.share);
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mwcform="split">${x}<h3>${icon("coins")} Share a daily budget <span class="faint small">SN${chome.campaign.netuid}</span></h3>
      <p>Tokens per 24 hours for every open team on this campaign together, shared ${known ? "in proportion to each competition's share of the subnet's emissions (teams without one get the average)" : "equally (no team has an emission share yet)"}. Each team's budget is replaced.</p>
      <ul class="mw-split">${open.map(c => `<li><b>${c.number != null ? `${c.number} · ` : ""}${esc(c.name || c.label)}</b><span class="faint">${c.share != null ? pct(c.share) : "no share"} · now ${short(c.budget)}</span></li>`).join("")}</ul>
      <label class="in"><span>Tokens per 24 hours, all teams together</span><input name="pool" type="number" min="0" max="50000000" step="100000" required value="${open.reduce((s, c) => s + (c.budget || 0), 0)}"></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("check")}Share it</button></div></form>`;
    dlg.showModal();
  }
  function cwire() {
    if (cwired) return; const m = $("#mining"); if (!m) return; cwired = true;
    m.addEventListener("click", async e => {
      const t = e.target; if (!t.closest("#mwc")) return;
      const o = t.closest("[data-mwcopen]"); if (o) return openPage(+o.dataset.mwcopen);
      const p = t.closest("[data-mwcpause]");
      if (p) { const r = await busy(p, () => api(`${W}/comps/${p.dataset.mwcpause}`, { method: "PATCH", body: { paused: p.dataset.on === "1" } })); if (r) { Auth.toast(p.dataset.on === "1" ? "Paused" : "Resumed"); cload(); } return; }
      const s = t.closest("[data-mwcstop]");
      if (s) return UI.confirm({ title: "Stop this team now?", body: "Work in progress stops where it is and the team is paused until you resume it.", ok: "Stop",
        run: async () => { await api(`${W}/comps/${s.dataset.mwcstop}/stop`, { method: "POST" }); Auth.toast("Stopped"); cload(); } }).catch(err);
      const b = t.closest("[data-mwc]"); if (!b) return;
      const k = b.dataset.mwc;
      if (k === "page") return openPage(null);
      if (k === "split") return splitForm();
      if (k === "intake") return MiningSources.open("queue");
      if (k === "stopall") {
        return UI.confirm({ title: "Stop every competition team?", body: "On every campaign of yours: work in progress stops where it is and every team is paused until you resume it.", ok: "Stop them all",
          run: async () => { const r = await api(`${W}/stop-all`, { method: "POST" }); Auth.toast(r.stopped ? `${plural(r.stopped, "team")} stopped` : "Nothing was running"); cload(); } }).catch(err);
      }
    });
    m.addEventListener("change", async e => {
      const t = e.target; if (!t.closest?.("#mwc")) return;
      if (t.matches("[data-mwcpilot]")) {
        const want = t.checked, r = await busy(null, () => api(`${W}/comps/${t.dataset.mwcpilot}`, { method: "PATCH", body: { autopilot: want } }));
        if (r) { Auth.toast(want ? "Autopilot on" : "Autopilot off"); cload(); } else t.checked = !want;
      }
    });
  }

  // for mining-crew.js, which draws the Diagram, Roadmap, Prompts, Levels, Links and Desk sub-tabs
  const go = k => { sub = k; store.set("mw.sub2", k); render(); };
  const panel = k => ({ board, team, notes: notebook, sandbox, activity })[k]?.() ?? "";
  // Import competitions → Type it in: the New competition form, on the Competition teams page
  async function newComp() {
    if (!all) { openPage(null); for (let i = 0; i < 40 && !all; i++) await new Promise(r => setTimeout(r, 150)); }
    if (all?.campaigns.length) compForm(false); else Auth.toast("Add a subnet in My subnets first: a team works for one");
  }
  return { open, stop, control, count, view: () => v, rerender: render, apply, go, reload: () => (on ? load() : cload()), panel, openTask, openPage, newComp };
})();
