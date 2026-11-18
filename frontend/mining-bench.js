/* Competition teams, the Workflow (mining_bench.py; the work runs on the AXoR Workbench on the host): the default tab of a team.
   - Five steps across the top, each one waiting for you before the next: Goal (folder, branch, what to reach), Plan (the
     Director reads the folder and proposes tasks; you edit, untick, approve), Work (you start a task; its engineer edits files
     on the task's own branch, live like Claude Code in VS Code), Review (the reviewer's verdict, the diff, the folder's checks;
     you merge, send back with a note or drop), Submit (you submit yourself and mark it here). Merge pins the branch's commit:
     when the review or a check doesn't back it, a dialog says why and merges only that commit once you confirm.
   - "What happens now": one line per thing that waits for you, with its button, and what's running.
   - Beside it the team (Director, engineers, reviewer: add, edit, switch off) and the log of every step.
   - The Files tab: your folder (live, read only) and every task's branch.
   - The Loadouts tab (mining-loadout.js): each agent's skills, plugins, MCP servers, memory and effort, with scores per version.
   - The Lab tab (mining-lab.js): the eval score of every checked commit, the base, earlier evals, task-by-task compares.
   - The GitHub tab (mining-github.js): mentions on a linked repository's issues and pull requests become tasks; replies go back.
   Every tab is filed under one of five stages, Overview · Plan · Run · Evaluate · Deliver (mining-stages.js; oldTabs() is the
   earlier row with More, kept as the fallback). mining-work.js draws the page around this. */
const MiningBench = (() => {
  const B = "/api/mining/bench";
  let v = null, vWid = null, vAt = 0, loading = false, failed = "", wired = false, timer = null, pick = null, pickWid = null;
  const drafts = {}, logs = {}, opened = new Set(), diffs = {}, refused = {}, shown = new Set();
  const fs = { wid: null, path: "", ref: "", list: null, file: null, err: "", busy: false };
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const money = x => x > 0 && x < 0.01 ? "<$0.01" : `$${fmtNum(x || 0, x >= 10 ? 0 : 2)}`;
  const ago = ts => { const s = Date.now() / 1000 - ts; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(ts * 1000).toLocaleDateString(); };
  const draft = (k, d = "") => drafts[k] ?? d;
  const STEPS = [["goal", "Goal", "target", "What the team works toward, on which folder"], ["plan", "Plan", "route", "The Director proposes tasks, you approve them"],
    ["work", "Work", "code", "Engineers edit files, each task on its own branch"], ["review", "Review", "eye", "Reviewer's verdict, diff and checks: you merge"],
    ["submit", "Submit", "rocket", "You submit to the competition"]];
  const ORDER = STEPS.map(s => s[0]);
  const TS = { proposed: ["wait", "Proposed"], todo: ["none", "To start"], engineer: ["run", "Engineer working"], handoff: ["warn", "Waiting for you"],
    review: ["run", "Reviewer reading"], ready: ["warn", "Ready for you"], failed: ["bad", "Stopped"], merged: ["ok", "Merged"] };
  const ROLE_ICON = { director: ["star", "violet"], engineer: ["code", "blue"], reviewer: ["shield", "amber"] };
  const LOG_ICON = { goal: "target", plan: "route", run: "play", wait: "bell", ok: "check", error: "alert" };
  const chip = s => { const [c, l] = TS[s] || ["none", s]; return `<span class="hq-chip t-${c}">${l}</span>`; };
  const AG = () => Object.fromEntries((v?.agents || []).map(a => [a.id, a]));
  const av = a => { const [ic, c] = ROLE_ICON[a?.role] || ["bot", "slate"]; return `<span class="av sm c-${c}" aria-hidden="true">${icon(ic)}</span>`; };
  const who = id => AG()[id]?.name || "an engineer";
  const firstOf = role => (v?.agents || []).find(a => a.role === role && a.on_team);
  const running = () => !!(v?.flow && (v.flow.plan_run || v.tasks.some(t => ["engineer", "review"].includes(t.status)) || v.tasks.some(t => Object.values(t.checks || {}).some(c => c.status === "running"))));

  // ---------- data ----------
  function need(wid, force = false) {
    if (vWid !== wid) { v = null; vWid = wid; vAt = 0; failed = ""; }
    if (pickWid !== wid) { pick = null; pickWid = wid; }
    if (loading || (!force && Date.now() - vAt < 3000)) return;
    loading = true;
    api(`${B}/comps/${wid}`).then(nv => { if (vWid === wid) { v = nv; failed = ""; } })
      .catch(e => { if (vWid === wid) failed = e.message; })
      .finally(() => { vAt = Date.now(); loading = false; if (vWid === wid) { pullLogs(); rerender(); } schedule(); });
  }
  function apply(nv) { if (nv && nv.comp?.id === vWid) { v = nv; vAt = Date.now(); } rerender(); schedule(); }
  function holding() { const a = document.activeElement; return !!(a && a.closest && a.closest("#teams [data-mbhold]") && a.matches("input, textarea, select")); }
  function rerender() { if (!holding()) MiningWork.rerender(); }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!document.querySelector("#teams .mb-root") || $("#view-teams")?.hidden) return;
      if (document.visibilityState !== "visible") return schedule();
      need(vWid, true);
    }, running() ? 2000 : 10000);
  }
  function liveRuns() {
    if (!v?.flow) return [];
    const ids = new Set(opened);
    if (v.flow.plan_run) ids.add(v.flow.plan_run);
    v.tasks.forEach(t => { if (t.run) ids.add(t.run); Object.values(t.checks || {}).forEach(c => c.status === "running" && ids.add(c.run)); });
    return [...ids];
  }
  function pullLogs() {
    for (const rid of liveRuns()) {
      const l = logs[rid] ||= { events: [], n: 0, status: "", loading: false, done: false };
      if (l.loading || l.done) continue;
      l.loading = true;
      api(`${B}/runs/${rid}?after=${l.n}`).then(r => {
        l.events.push(...r.events); l.n = (r.from || 0) + r.events.length; l.status = r.status; l.cost = r.cost; l.rate = r.rate; l.error = r.error;
        l.done = !["queued", "running"].includes(r.status);
      }).catch(e => { l.error = e.message; l.done = true; }).finally(() => { l.loading = false; rerender(); });
    }
  }

  // ---------- the frame: tabs with More ----------
  function owns(sub) { return sub === "flow" || sub === "files" || sub === "loadout" || sub === "lab" || sub === "github"; }
  function tabs(sub, more) {
    // the five stages (mining-stages.js) file every tab below under Overview · Plan · Run · Evaluate · Deliver
    if (typeof MiningStages !== "undefined") {
      const waiting = v?.flow ? v.tasks.filter(t => ["handoff", "ready", "failed", "proposed"].includes(t.status)).length : 0;
      return MiningStages.tabs(sub, more, { flow: waiting, github: MiningGitHub.count() });
    }
    return oldTabs(sub, more);
  }
  function oldTabs(sub, more) {
    const inMore = more.find(m => m[0] === sub), alerts = more.reduce((n, m) => n + (m[3] || 0), 0);
    const waiting = v?.flow ? v.tasks.filter(t => ["handoff", "ready", "failed", "proposed"].includes(t.status)).length : 0;
    return `<div class="mb-tabs" role="tablist">
      <button type="button" role="tab" data-mwsub="autoloop" aria-pressed="${sub === "autoloop"}">${icon("cycle")}Autoloop</button>
      <button type="button" role="tab" data-mwsub="files" aria-pressed="${sub === "files"}">${icon("folder")}Files</button>
      <button type="button" role="tab" data-mwsub="loadout" aria-pressed="${sub === "loadout"}">${icon("sliders")}Loadouts</button>
      <button type="button" role="tab" data-mwsub="lab" aria-pressed="${sub === "lab"}">${icon("chart")}Lab</button>
      <button type="button" role="tab" data-mwsub="github" aria-pressed="${sub === "github"}">${icon("github")}GitHub${MiningGitHub.count() ? `<span class="hq-n alert">${MiningGitHub.count()}</span>` : ""}</button>
      <button type="button" role="tab" data-mwsub="upgrade" aria-pressed="${sub === "upgrade"}">${icon("sparkle")}Upgrade</button>
      <button type="button" role="tab" data-mwsub="topminer" aria-pressed="${sub === "topminer"}">${icon("trophy")}Top miner</button>
      <details class="mb-more" ${shown.has("more") ? "open" : ""} data-mbdetails="more"><summary aria-pressed="${!!inMore}">${icon("dots")}${inMore ? esc(inMore[1]) : "More"}${alerts ? `<span class="hq-n alert">${alerts}</span>` : ""}</summary>
        <div class="mb-more-menu" role="menu"><p class="faint small">The board Autoloop runs, the Director's report, the diagram and the rest.</p>
          ${more.map(([k, l, ic, x, n]) => `<button type="button" role="menuitem" data-mwsub="${k}" aria-pressed="${sub === k}">${icon(ic)}${l}${x ? `<span class="hq-n alert">${x}</span>` : n ? `<span class="hq-n">${n}</span>` : ""}</button>`).join("")}</div></details></div>`;
  }
  function page(wv, sub, more) {
    need(wv.comp.id);
    const c = wv.comp;
    const head = `<div class="mb-top"><div><div class="mw-kicker">${icon("folder")}SN${wv.campaign.netuid} · ${esc(wv.campaign.subnet || wv.campaign.title)}${c.number != null ? ` · competition ${c.number}` : ""}</div>
      <h2>${esc(c.label)}</h2></div>${c.autopilot && !c.paused ? `<button type="button" class="hq-chip t-ok mb-pilot" data-mwsub="status" title="The team's work runs on its board under Autoloop: that's the one execution path, and its benchmarks count in Status → Release & benchmarks. The Workflow here is a separate path on the host's folders (the AXoR Workbench): give a piece of work to one of the two, not both.">${icon("zap")}Autoloop runs this team</button>` : ""}${v?.info ? `<span class="mb-conn ok" title="${esc(v.info.claude || "")}">${icon("check")}Workbench connected${v.info.running ? ` · ${plural(v.info.running, "run")} going` : ""}${rate()}</span>` : ""}</div>`;
    let body;
    if (failed && !v) body = `<div class="mh-card"><p class="mh-err">${icon("alert")}${esc(failed)}</p></div>`;
    else if (!v) body = Loading.line("Opening the workflow…");
    else if (!v.connected) body = sub === "lab" && !v.flow ? labFirst(wv, false) : offline();
    else if (!v.flow) body = sub === "lab" ? labFirst(wv) : setup(wv);
    else body = sub === "files" ? filesView() : sub === "loadout" ? MiningLoadout.page(v) : sub === "lab" ? MiningLab.page(v) : sub === "github" ? MiningGitHub.page(v) : flow(wv);
    return `<div class="mb-root">${head}${MissionTeam.strip(wv)}${tabs(sub, more)}${body}</div>`;  // the team's missions (mission-team.js)
  }
  function rate() {
    const r = v?.info?.rate?.five_hour; if (!r || r.used == null) return "";
    return ` · <span title="Your Claude plan's 5-hour window: agents share it with your own Claude Code sessions">${fmtNum(r.used * 100, 0)}% of 5 h quota</span>`;
  }

  // ---------- not connected / not set up ----------
  function offline() {
    return `<section class="mh-card mb-offline"><h3>${icon("server")}The workbench isn't connected</h3>
      <p>The Workflow runs agents on this host's folders through the AXoR Workbench, a small service beside k3s. ${v.why ? `Right now: <span class="mh-err">${esc(v.why)}</span>` : ""}</p>
      <ol class="mb-howto"><li>On the host, as root: <code>./workbench/install.sh /home/thomas/bit</code>. It writes <code>/etc/axor-workbench.json</code> with a fresh token and the folder, and starts <code>axor-workbench</code> on 10.42.0.1:8350 (the pod network only).</li>
        <li>Then <code>./k8s/redeploy.sh</code>, so the web pod gets <code>WORKBENCH_URL</code> and the token.</li>
        <li>Come back here: you pick the folder and the branch, write the goal, and the team starts.</li></ol></section>`;
  }
  // the Lab without a Workflow: say which path counts, instead of opening a second execution path's setup
  function labFirst(wv, canSetUp = true) {
    return `<section class="mh-card mb-setup"><h3>${icon("chart")}The Lab scores the Workflow's evals</h3>
      <p>This team has no Workflow, so there's nothing for the Lab to score. Its work runs on the board under ${wv.comp.autopilot ? "Autoloop" : "the board (autopilot is off)"}, and its benchmarks are filed against the frozen release candidate and suite.</p>
      <p class="row"><button type="button" class="btn primary sm" data-mwsub="status">${icon("lock")}Open Release & benchmarks</button></p>
      ${canSetUp ? `<details class="mb-legacy"><summary class="small">Set up the Workflow anyway (a separate path on the host's folders)</summary>${setup(wv)}</details>` : `<p class="faint small">The Workflow (a separate path on the host's folders) needs the AXoR Workbench, which isn't connected.</p>`}</section>`;
  }
  function setup(wv) {
    const repos = v.info?.repos || [];
    const r = repos.find(x => x.id === draft("s-repo", repos[0]?.id)) || repos[0];
    return `<section class="mh-card mb-setup" data-mbhold><h3>${icon("route")}Set up the team's workflow</h3>
      <p>A small team works on your real folder, and asks you before every next step:</p>
      <ol class="mb-steps-intro">${STEPS.map(([, l, ic, d]) => `<li>${icon(ic)}<b>${l}</b><span>${d}</span></li>`).join("")}</ol>
      <p class="faint small">Agents never edit your checkout: each task gets its own git branch <code>bench/…</code> in a separate folder, made from the last commit. They can read and edit files there, but can't run commands; the tests and evals are buttons you press. Runs use this host's Claude Code login, the same quota as your own sessions.</p>
      ${repos.length ? `<div class="mb-form"><label class="in"><span>Folder</span><select name="repo" data-mbdraft="s-repo">${repos.map(x => `<option value="${esc(x.id)}" ${x.id === r.id ? "selected" : ""}>${esc(x.name)} · ${esc(x.path)}</option>`).join("")}</select></label>
        <label class="in"><span>Branch to start from and merge into</span><select name="into" data-mbdraft="s-into">${(r.branches || []).map(b => `<option ${b === draft("s-into", r.branch) ? "selected" : ""}>${esc(b)}</option>`).join("")}</select></label>
        ${r.dirty ? `<p class="mb-warn small">${icon("info")}${plural(r.dirty, "uncommitted change")} in the folder${r.staged ? ` (${r.staged} staged)` : ""}: agents start from the last commit, so they won't see those until you commit them.</p>` : ""}
        <label class="in mb-wide"><span>Goal</span><textarea name="goal" rows="3" data-mbdraft="s-goal" placeholder="e.g. Raise agent30's pass rate on the DB-engineering samples without breaking the hand-in tests">${esc(draft("s-goal", wv.comp.goal || ""))}</textarea></label>
        <div class="row"><button type="button" class="btn primary" data-mb="create">${icon("check")}Set up the team</button><span class="faint small">Director Dana, engineers Ada and Linus, reviewer Vera: you can change them after.</span></div></div>`
        : `<p class="mh-err">${icon("info")}The workbench offers no folder: add one to /etc/axor-workbench.json on the host.</p>`}</section>`;
  }

  // ---------- the workflow ----------
  function flow(wv) {
    const cur = v.step, at = pick && ORDER.includes(pick) ? pick : cur, ci = ORDER.indexOf(cur);
    const count = { plan: v.tasks.filter(t => t.status === "proposed").length, work: v.tasks.filter(t => ["todo", "engineer", "handoff", "review", "failed"].includes(t.status)).length,
      review: v.tasks.filter(t => t.status === "ready").length, submit: v.tasks.filter(t => t.status === "merged").length };
    const stepper = `<ol class="mb-stepper">${STEPS.map(([k, l, ic, d], i) => {
      const state = i < ci ? "done" : i === ci ? "now" : "next";
      return `<li class="s-${state} ${k === at ? "on" : ""}"><button type="button" data-mbstep="${k}" aria-current="${k === at ? "step" : "false"}">
        <span class="mb-dot">${state === "done" ? icon("check") : i + 1}</span><span class="mb-sl"><b>${l}${count[k] ? ` <span class="hq-n">${count[k]}</span>` : ""}</b><small>${d}</small></span></button></li>`;
    }).join("")}</ol>`;
    const panel = { goal: goalStep, plan: planStep, work: workStep, review: reviewStep, submit: submitStep }[at](wv);
    return `${stepper}${now()}<div class="mb-grid"><div class="mb-main">${panel}</div><aside class="mb-side">${teamCard()}${logCard()}</aside></div>`;
  }

  function now() {
    const items = [], A = AG(), rev = firstOf("reviewer"), dir = firstOf("director");
    const f = v.flow;
    if (f.plan_run) items.push(["run", `${esc(dir?.name || "The Director")} is reading the folder and planning…`, `<button type="button" class="btn sm" data-mbstep="plan">${icon("eye")}Watch</button>`]);
    else if (f.plan_error && !v.tasks.some(t => t.status !== "dropped")) items.push(["bad", `Planning failed: ${esc(f.plan_error)}`, `<button type="button" class="btn sm" data-mb="plan">${icon("cycle")}Plan again</button>`]);
    const proposed = v.tasks.filter(t => t.status === "proposed").length;
    if (proposed) items.push(["wait", `${plural(proposed, "task")} proposed: tick the ones you want, edit them, approve.`, `<button type="button" class="btn sm primary" data-mbstep="plan">${icon("check")}Review the plan</button>`]);
    for (const t of v.tasks) {
      if (t.status === "engineer") items.push(["run", `${esc(who(t.engineer_id))} is working on “${esc(t.title)}”…`, `<button type="button" class="btn sm" data-mbstep="work">${icon("eye")}Watch</button>`]);
      if (t.status === "review") items.push(["run", `${esc(rev?.name || "The reviewer")} is reviewing “${esc(t.title)}”…`, `<button type="button" class="btn sm" data-mbstep="work">${icon("eye")}Watch</button>`]);
      if (t.status === "handoff") items.push(["wait", `${esc(who(t.engineer_id))} finished “${esc(t.title)}”. Look at what changed, then send it to ${esc(rev?.name || "review")}.`,
        `<button type="button" class="btn sm primary" data-mbt="next" data-id="${t.id}">${icon("send")}Send to ${esc(rev?.name || "review")}</button>`]);
      if (t.status === "ready") items.push(["wait", `“${esc(t.title)}” is ready: ${t.review ? `${esc(rev?.name || "the reviewer")} ${t.review.verdict === "approve" ? "approves" : "asks for changes"}` : "no review"}. Run the checks, then merge or send back.`,
        `<button type="button" class="btn sm primary" data-mbstep="review">${icon("eye")}Review</button>`]);
      if (t.status === "failed") items.push(["bad", `${esc(who(t.engineer_id))} stopped on “${esc(t.title)}”: ${esc(t.error || "")}`, `<button type="button" class="btn sm" data-mbt="start" data-id="${t.id}">${icon("play")}Start again</button>`]);
    }
    for (const x of v.improving || []) {  // mining_improve.py: proposals to improve an engineer, and their trials
      const go = `<button type="button" class="btn sm ${["proposed", "better"].includes(x.status) ? "primary" : ""}" data-mbimprove>${icon("bulb")}${x.status === "better" ? "Promote or reject" : x.status === "proposed" ? "Test or decide" : "Watch"}</button>`;
      if (x.status === "diagnosing") items.push(["run", `The Improvement Engineer is looking at why ${esc(x.agent)}'s “${esc(x.task || "")}” went wrong…`, go]);
      else if (x.status === "testing") items.push(["run", `Trial of the proposal for ${esc(x.agent)}: the candidate does the task again and the eval scores it…`, go]);
      else items.push(["wait", x.status === "proposed" ? `The Improvement Engineer proposes for ${esc(x.agent)}: ${esc(x.change || "")}` : `Trial for ${esc(x.agent)}: ${esc(x.result || x.status)}`, go]);
    }
    const todo = v.tasks.filter(t => t.status === "todo");
    if (todo.length && !v.tasks.some(t => t.status === "engineer")) items.push(["none", `${plural(todo.length, "approved task")} to start. Each runs on its own branch; start one, or a few at once.`,
      `<button type="button" class="btn sm primary" data-mbt="start" data-id="${todo[0].id}">${icon("play")}Start “${esc(todo[0].title.slice(0, 40))}”</button>`]);
    if (!items.length) {
      if (v.step === "submit") items.push(["ok", `${plural(v.tasks.filter(t => t.status === "merged").length, "task")} merged into ${esc(f.into_branch)}. Submit when you're ready, or ask for the next plan.`,
        `<button type="button" class="btn sm" data-mbstep="submit">${icon("rocket")}Submit</button> <button type="button" class="btn sm" data-mbstep="plan">${icon("route")}Next plan</button>`]);
      else if (v.step === "goal") items.push(["wait", "Write the goal: the Director plans toward it.", `<button type="button" class="btn sm primary" data-mbstep="goal">${icon("target")}Goal</button>`]);
      else items.push(["none", `Ask ${esc(dir?.name || "the Director")} for a plan: it reads the folder and proposes tasks for you to approve.`, `<button type="button" class="btn sm primary" data-mb="plan">${icon("route")}Plan</button>`]);
    }
    const label = { run: "Working", wait: "Waiting for you", bad: "Needs you", ok: "Done", none: "Next" };
    return `<section class="mb-now" aria-live="polite"><h3>${icon("bell")}What happens now</h3><ul>${items.map(([k, text, btn]) =>
      `<li class="n-${k}"><span class="hq-chip t-${k === "wait" ? "warn" : k}">${k === "run" ? `<i class="mb-spin" aria-hidden="true"></i>` : ""}${label[k]}</span><span class="mb-now-t">${text}</span><span class="row">${btn}</span></li>`).join("")}</ul>
      <p class="faint small">Spent so far: ${money(v.spent)} of Claude usage${f.confirm ? " · asks you between agents" : " · goes straight from engineer to reviewer"}.</p></section>`;
  }

  // ----- 1. goal -----
  function goalStep() {
    const f = v.flow, r = v.repo || {};
    return `<section class="mh-card" data-mbhold><h3>${icon("target")}Goal</h3>
      <label class="in"><span>What the team works toward</span><textarea rows="4" data-mbdraft="goal">${esc(draft("goal", f.goal || ""))}</textarea></label>
      <div class="row"><button type="button" class="btn sm primary" data-mb="savegoal" ${draft("goal", f.goal || "") === (f.goal || "") ? "disabled" : ""}>${icon("check")}Save the goal</button></div>
      <h4>Folder</h4><p><b>${esc(r.name || f.repo)}</b> <code>${esc(r.path || "")}</code><br>
        Starts from and merges into <select data-mbinto data-mbhold>${(r.branches || [f.into_branch]).map(b => `<option ${b === f.into_branch ? "selected" : ""}>${esc(b)}</option>`).join("")}</select>
        ${r.heads?.[f.into_branch] ? `at <code>${esc(r.heads[f.into_branch].slice(0, 8))}</code>` : ""}</p>
      ${r.dirty ? `<p class="mb-warn small">${icon("info")}${plural(r.dirty, "uncommitted change")} in the folder${r.staged ? ` (${r.staged} staged)` : ""}. Agents start from the last commit, so they don't see them; merging waits until nothing staged is in the way.</p>` : ""}
      <h4>How the team works</h4>
      <label class="mb-switch"><input type="checkbox" data-mbconfirm ${f.confirm ? "checked" : ""}><span><b>Ask me between agents</b><small>When an engineer finishes, the task waits for you before the reviewer reads it.</small></span></label>
      <label class="in mb-narrow"><span>Most one run may spend (USD)</span><input type="number" min="0.1" max="5" step="0.1" value="${esc(draft("budget", String(f.budget)))}" data-mbdraft="budget"></label>
      <div class="row"><button type="button" class="btn sm" data-mb="savebudget">${icon("check")}Save</button></div>
      <details class="mb-danger"><summary>Start over</summary><p class="faint small">Forgets this workflow's tasks, team and log. Branches already on the folder stay.</p>
        <button type="button" class="btn sm mw-danger" data-mb="reset">${icon("trash")}Start over</button></details></section>`;
  }

  // ----- 2. plan -----
  function planStep() {
    const f = v.flow, dir = firstOf("director"), eng = (v.agents || []).filter(a => a.role === "engineer" && a.on_team);
    const proposed = v.tasks.filter(t => t.status === "proposed");
    const picked = proposed.filter(t => draft(`p-on-${t.id}`, "1") === "1").length;
    const approved = v.tasks.filter(t => !["proposed", "dropped"].includes(t.status));
    const engSel = (k, cur) => `<select data-mbdraft="${k}" aria-label="Engineer">${eng.map(a => `<option value="${a.id}" ${String(a.id) === String(draft(k, cur ?? eng[0]?.id)) ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>`;
    return `<section class="mh-card" data-mbhold><h3>${icon("route")}Plan</h3>
      ${f.plan_run ? `<p>${esc(dir?.name || "The Director")} is reading the folder (read only) and writing the plan.</p>${runLog(f.plan_run, true)}`
        : f.plan_summary && proposed.length ? `<p class="mb-quote">${icon("star")}<span>${esc(f.plan_summary)}</span></p>` : ""}
      ${f.plan_error && !f.plan_run ? `<p class="mh-err">${icon("alert")}${esc(f.plan_error)}</p>` : ""}
      ${proposed.length ? `<ol class="mb-proposed">${proposed.map(t => {
        const on = draft(`p-on-${t.id}`, "1") === "1";
        return `<li class="${on ? "" : "off"}"><label class="mb-tick"><input type="checkbox" data-mbdraft="p-on-${t.id}" data-mbbool ${on ? "checked" : ""}><span class="sr">Keep this task</span></label>
          <div class="mb-pbody"><input class="mb-ptitle" data-mbdraft="p-title-${t.id}" value="${esc(draft(`p-title-${t.id}`, t.title))}" aria-label="Title">
          <textarea rows="3" data-mbdraft="p-detail-${t.id}" aria-label="Detail">${esc(draft(`p-detail-${t.id}`, t.detail || ""))}</textarea>
          <div class="row small">${icon("code")}${engSel(`p-eng-${t.id}`, t.engineer_id)}${t.files?.length ? `<span class="faint">${t.files.slice(0, 5).map(x => `<code>${esc(x)}</code>`).join(" ")}</span>` : ""}</div></div></li>`;
      }).join("")}</ol>
      <div class="row"><button type="button" class="btn primary" data-mb="approve" ${picked ? "" : "disabled"}>${icon("check")}Approve ${plural(picked, "task")}</button><span class="faint small">Unticked tasks are left out. Nothing starts until you press Start in Work.</span></div>` : ""}
      ${!f.plan_run ? `<details class="mb-replan" ${proposed.length ? "" : "open"}><summary>${proposed.length ? "Plan again instead" : `Ask ${esc(dir?.name || "the Director")} for ${approved.length ? "the next" : "a"} plan`}</summary>
        <label class="in"><span>Anything to add for the Director (optional)</span><textarea rows="2" data-mbdraft="plannote" placeholder="e.g. Focus on the hand-in path; don't touch eval/">${esc(draft("plannote"))}</textarea></label>
        <button type="button" class="btn sm ${proposed.length ? "" : "primary"}" data-mb="plan">${icon("route")}Plan</button></details>` : ""}
      ${ledgerBox()}${researchBox()}
      ${approved.length ? `<h4>Approved</h4><ul class="mb-mini">${approved.map(t => `<li>${chip(t.status)} ${esc(t.title)} <span class="faint">· ${esc(who(t.engineer_id))}</span></li>`).join("")}</ul>` : ""}
      <details class="mb-add"><summary>${icon("plus")}Add a task yourself</summary>
        <label class="in"><span>Title</span><input data-mbdraft="n-title" value="${esc(draft("n-title"))}"></label>
        <label class="in"><span>What to do</span><textarea rows="3" data-mbdraft="n-detail">${esc(draft("n-detail"))}</textarea></label>
        <div class="row">${engSel("n-eng")}<button type="button" class="btn sm" data-mb="addtask">${icon("plus")}Add</button></div></details></section>`;
  }

  function ledgerBox() {  // the eval record the Director gets in its plan prompt (mining_lab.py)
    if (!v.ledger?.length) return "";
    return `<details class="mb-ledger" data-mbdetails="ledger" ${shown.has("ledger") ? "open" : ""}><summary>${icon("chart")}What ${esc(firstOf("director")?.name || "the Director")} is told about the eval score</summary>
      <pre>${esc(v.ledger.join("\n"))}</pre><p class="faint small">From the Lab, in every plan prompt: measure the base and run the eval on tasks to keep it current.</p></details>`;
  }
  function researchBox() {  // a Workforce mission as the Director's research arm (mining_research.py)
    const r = v.research; if (!r || (!r.available && !r.mission)) return "";
    const m = r.mission, dir = esc(firstOf("director")?.name || "the Director"), going = m && ["running", "waiting"].includes(m.status);
    const start = `<div class="row mb-rs-start"><input data-mbdraft="rsfocus" value="${esc(draft("rsfocus"))}" placeholder="Focus (optional): e.g. why agents time out on ClickHouse tasks" aria-label="Research focus">
      <button type="button" class="btn sm" data-mbresearch ${r.available ? "" : "disabled"}>${icon("search")}${m ? "Research again" : "Research first"}</button></div>`;
    const body = !m ? `<p class="faint small">The Workforce looks into how the competition scores agents, which tasks agents fail and why, and what's worth trying; ${dir} gets its report in the next plan. It runs on the Workforce's model credits, not your Claude Code quota.</p>${start}`
      : going ? `<p>${icon("clock")}The mission is ${m.status === "waiting" ? "waiting for you" : `at work (${esc(m.step)})`}. <a href="#workforce">Open it in Workforce</a></p>`
      : m.status === "done" ? `<p class="mb-quote">${icon("search")}<span>${esc(m.headline || "Done.")}</span></p>
        <label class="mb-switch"><input type="checkbox" data-mbresuse ${r.use ? "checked" : ""}><span><b>Give the report to ${dir}</b><small>It goes into the next plan prompt. <a href="#workforce">Read it in Workforce</a></small></span></label>${start}`
      : `<p class="mh-err small">${icon("alert")}${m.status === "gone" ? "The mission is gone from the Workforce." : `The mission ${esc(m.status)}${m.error ? `: ${esc(m.error)}` : "."}`}</p>${start}`;
    return `<div class="mb-research" data-mbhold><h4>${icon("search")}Research (Workforce)</h4>${body}</div>`;
  }

  // ----- 3. work -----
  function workStep() {
    const list = v.tasks.filter(t => ["todo", "engineer", "handoff", "review", "failed"].includes(t.status));
    const later = v.tasks.filter(t => ["ready", "merged"].includes(t.status));
    return `<section class="mh-card"><h3>${icon("code")}Work</h3>
      ${list.length ? `<ul class="mb-tasks">${list.map(taskCard).join("")}</ul>` : `<p class="faint">Nothing in progress. ${v.tasks.some(t => t.status === "proposed") ? `Approve the plan first.` : `Ask for a plan, or add a task yourself in Plan.`}</p>`}
      ${later.length ? `<h4>Further along</h4><ul class="mb-mini">${later.map(t => `<li>${chip(t.status)} ${esc(t.title)}${t.status === "ready" ? ` <button type="button" class="linkbtn" data-mbstep="review">review it</button>` : ""}</li>`).join("")}</ul>` : ""}</section>`;
  }
  function taskCard(t) {
    const rev = firstOf("reviewer"), runs = (v.runs || []).filter(r => r.task_id === t.id && r.run !== t.run);
    const acts = {
      todo: `<button type="button" class="btn sm primary" data-mbt="start" data-id="${t.id}">${icon("play")}Start</button><button type="button" class="btn sm" data-mbt="drop" data-id="${t.id}">${icon("trash")}Drop</button>`,
      engineer: `<button type="button" class="btn sm mw-danger" data-mbt="stop" data-id="${t.id}">${icon("stop")}Stop</button>`,
      review: `<button type="button" class="btn sm mw-danger" data-mbt="stop" data-id="${t.id}">${icon("stop")}Stop</button>`,
      handoff: `<button type="button" class="btn sm primary" data-mbt="next" data-id="${t.id}">${icon("send")}Send to ${esc(rev?.name || "review")}</button>${diffBtn(t)}${backBtn(t)}<button type="button" class="btn sm" data-mbt="drop" data-id="${t.id}">${icon("trash")}Drop</button>`,
      failed: `<button type="button" class="btn sm primary" data-mbt="start" data-id="${t.id}">${icon("play")}Start again</button>${t.slug ? diffBtn(t) : ""}${t.session ? backBtn(t) : ""}<button type="button" class="btn sm" data-mbt="drop" data-id="${t.id}">${icon("trash")}Drop</button>`,
    }[t.status] || "";
    return `<li class="mb-task st-${t.status}"><div class="mb-thead">${chip(t.status)}<b>${esc(t.title)}</b>${av(AG()[t.engineer_id])}<span class="faint small">${esc(who(t.engineer_id))}</span>
        ${t.slug ? `<code class="mb-branch" title="The task's branch">${icon("branch")}bench/${esc(t.slug)}</code>` : ""}${t.cost ? `<span class="faint small">${money(t.cost)}</span>` : ""}</div>
      ${t.detail ? `<details class="mb-detail"><summary>The task</summary><p>${esc(t.detail)}</p></details>` : ""}
      ${t.status === "failed" && t.error ? `<p class="mh-err small">${icon("alert")}${esc(t.error)}</p>` : ""}
      ${t.summary && !["engineer"].includes(t.status) ? `<div class="mb-said"><span class="faint small">${esc(who(t.engineer_id))} says</span><div class="mb-md">${esc(t.summary)}</div></div>` : ""}
      ${t.run ? runLog(t.run, true) : ""}
      ${backBox(t)}${diffBox(t)}
      <div class="row mb-acts">${acts}</div>
      ${runs.length ? `<details class="mb-history"><summary>Earlier runs (${runs.length})</summary><ul>${runs.map(r => `<li><button type="button" class="linkbtn" data-mbrun="${esc(r.run)}">${esc(r.who)} · ${esc(r.kind)} · ${esc(r.status)}${r.cost ? ` · ${money(r.cost)}` : ""}</button> <span class="faint small">${ago(r.started)}</span>${opened.has(r.run) ? runLog(r.run, false) : ""}</li>`).join("")}</ul></details>` : ""}</li>`;
  }
  const diffBtn = t => `<button type="button" class="btn sm" data-mbdiff="${t.id}">${icon("eye")}${diffs[t.id]?.open ? "Hide" : "See"} what changed</button>`;
  const backBtn = t => `<button type="button" class="btn sm" data-mbbackopen="${t.id}">${icon("undo")}Send back…</button>`;
  function backBox(t) {
    if (!shown.has(`back-${t.id}`)) return "";
    return `<div class="mb-back" data-mbhold><label class="in"><span>What should ${esc(who(t.engineer_id))} change? It carries on in the same session and branch.</span>
      <textarea rows="3" data-mbdraft="back-${t.id}">${esc(draft(`back-${t.id}`))}</textarea></label>
      <div class="row"><button type="button" class="btn sm primary" data-mbt="back" data-id="${t.id}">${icon("send")}Send back to ${esc(who(t.engineer_id))}</button><button type="button" class="btn sm" data-mbbackopen="${t.id}">Cancel</button></div></div>`;
  }
  function diffBox(t) {
    const d = diffs[t.id]; if (!d?.open) return "";
    if (d.err) return `<p class="mh-err small">${icon("alert")}${esc(d.err)}</p>`;
    if (!d.data) return Loading.line("Reading the diff…");
    const x = d.data;
    if (!x.files.length) return `<p class="faint small">No files changed on bench/${esc(t.slug)}.</p>`;
    const lines = x.patch.split("\n").map(l => {
      const c = l.startsWith("diff --git") ? "f" : l.startsWith("@@") ? "h" : l.startsWith("+++") || l.startsWith("---") ? "m" : l.startsWith("+") ? "a" : l.startsWith("-") ? "d" : "";
      return `<span class="${c ? `l-${c}` : ""}">${esc(l) || " "}</span>`;
    }).join("\n");
    return `<div class="mb-diff"><ul class="mb-dfiles">${x.files.map(f => `<li><code>${esc(f.path)}</code> <span class="l-a">+${f.added ?? "bin"}</span> <span class="l-d">−${f.removed ?? ""}</span></li>`).join("")}</ul>
      ${x.commits?.length ? `<p class="faint small">${x.commits.map(c => `<code>${esc(c.sha)}</code> ${esc(c.subject)}`).join(" · ")}</p>` : ""}
      <pre class="mb-patch">${lines}</pre>${x.truncated ? `<p class="faint small">The diff is cut here: see the rest in Files on bench/${esc(t.slug)}.</p>` : ""}</div>`;
  }

  // a run's steps, like Claude Code's own transcript
  function runLog(rid, live) {
    const l = logs[rid];
    if (!l) { if (live) pullLogs(); return `<div class="mb-log">${Loading.line("Connecting to the run…")}</div>`; }
    const ev = l.events.slice(-80);
    const row = e => e.k === "tool" ? `<li class="e-tool">${icon(e.name === "Edit" || e.name === "Write" ? "edit" : e.name === "Read" ? "file" : "search")}<b>${esc(e.name)}</b> <code>${esc(e.arg || "")}</code></li>`
      : e.k === "say" ? `<li class="e-say">${esc(e.text)}</li>` : e.k === "err" ? `<li class="e-err">${icon("alert")}${esc(e.text)}</li>`
      : e.k === "out" ? `<li class="e-out"><code>${esc(e.text)}</code></li>` : e.k === "done" ? `<li class="e-done">${icon("check")}${esc(e.text)}</li>` : `<li class="e-note">${esc(e.text)}</li>`;
    const going = ["queued", "running"].includes(l.status);
    return `<div class="mb-log ${going ? "mb-live" : ""}"><div class="mb-log-h">${going ? `<i class="mb-spin" aria-hidden="true"></i>${l.status === "queued" ? "Waiting for a free slot" : "Live"}` : esc(l.status || "")}
      ${l.events.length > 80 ? `<span class="faint small">last 80 of ${l.events.length} steps</span>` : ""}</div><ol>${ev.map(row).join("") || `<li class="e-note">Starting…</li>`}</ol></div>`;
  }

  // ----- 4. review -----
  function reviewStep() {
    const list = v.tasks.filter(t => t.status === "ready");
    return `<section class="mh-card"><h3>${icon("eye")}Review</h3>
      ${list.length ? `<ul class="mb-tasks">${list.map(reviewCard).join("")}</ul>` : `<p class="faint">Nothing waits for review. Tasks land here after the reviewer reads them.</p>`}</section>`;
  }
  function reviewCard(t) {
    const rv = t.review, rev = firstOf("reviewer"), checks = v.repo?.checks || [], no = refused[t.id];
    return `<li class="mb-task st-ready"><div class="mb-thead">${chip(t.status)}<b>${esc(t.title)}</b>${av(AG()[t.engineer_id])}<span class="faint small">${esc(who(t.engineer_id))}</span>
        <code class="mb-branch">${icon("branch")}bench/${esc(t.slug || "")}</code>${t.cost ? `<span class="faint small">${money(t.cost)}</span>` : ""}</div>
      ${rv ? `<div class="mb-verdict v-${rv.verdict}"><b>${icon(rv.verdict === "approve" ? "check" : "alert")}${esc(rev?.name || "The reviewer")} ${rv.verdict === "approve" ? "approves" : "asks for changes"}</b>${rv.confidence ? `<span class="mb-conf c-${esc(rv.confidence)}">${esc(rv.confidence)} confidence</span>` : ""}${t.reviewed ? `<span class="faint small">read commit <code>${esc(t.reviewed.slice(0, 8))}</code></span>` : ""}<p>${esc(rv.summary || "")}</p>
        ${rv.issues?.length ? `<ul>${rv.issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}${evidence(rv.evidence)}</div>` : ""}
      ${t.summary ? `<details class="mb-said"><summary>${esc(who(t.engineer_id))} says</summary><div class="mb-md">${esc(t.summary)}</div></details>` : ""}
      ${checks.length ? `<div class="mb-checks"><h4>Checks</h4>${checks.map(c => {
        const r = (t.checks || {})[c.id];
        return `<div class="mb-check"><div class="row"><button type="button" class="btn sm" data-mbcheck="${esc(c.id)}" data-id="${t.id}" ${r?.status === "running" ? "disabled" : ""}>${icon("play")}${esc(c.label)}</button>
          ${r ? `<span class="hq-chip t-${r.status === "done" ? "ok" : r.status === "running" ? "run" : "bad"}">${r.status === "done" ? "Passed" : r.status === "running" ? "Running" : "Failed"}</span>` : ""}${r?.head ? `<span class="faint small">on <code>${esc(r.head.slice(0, 8))}</code></span>` : ""}${scoreLine(r?.score, t, c)}${c.note ? `<span class="faint small">${esc(c.note)}</span>` : ""}</div>
          ${r?.status === "running" ? runLog(r.run, true) : r?.tail ? `<pre class="mb-tail">${esc(r.tail)}</pre>` : ""}</div>`;
      }).join("")}</div>` : `<p class="faint small">${icon("info")}The folder has no checks: add a test or eval command under "checks" in /etc/axor-workbench.json.</p>`}
      ${diffBox(t)}${backBox(t)}
      ${no ? `<div class="mb-refused"><p>${icon("info")}<b>Not merged:</b> ${esc(no.why)}</p>${no.how ? `<p class="small">Merge by hand when you're ready:</p><pre class="mb-cmd">${esc(no.how)}</pre>
        <div class="row"><button type="button" class="btn sm" data-mbcopy="${esc(no.how)}">${icon("copy")}Copy</button><button type="button" class="btn sm" data-mbt="merged" data-id="${t.id}">${icon("check")}I merged it</button></div>` : ""}</div>` : ""}
      <div class="row mb-acts"><button type="button" class="btn sm primary" data-mbt="merge" data-id="${t.id}" title="Merges the commit the review and checks saw; if they don't back it, you're told why and asked first">${icon("commit")}Merge into ${esc(v.flow.into_branch)}</button>${diffBtn(t)}${backBtn(t)}
        <button type="button" class="btn sm" data-mbt="drop" data-id="${t.id}">${icon("trash")}Drop</button></div></li>`;
  }
  function evidence(ev) {
    if (!ev?.length) return "";
    return `<details class="mb-ev"><summary>${plural(ev.length, "piece")} of evidence</summary><ul>${ev.map(e => `<li>${esc(e.claim || "")}${e.source ? ` <code>${esc(e.source)}</code>` : ` <span class="faint">(no source)</span>`}</li>`).join("")}</ul></details>`;
  }
  function scoreLine(s, t, c) {  // a scored check's eval result (mining_lab.py), beside the base the task started from
    if (!s) return "";
    const vs = s.vs, d = vs ? vs.solved - vs.base : 0;
    const at = (!vs || vs.stale) && t?.base ? `<button type="button" class="btn sm" data-mbbaseat="${esc(t.base)}" data-check="${esc(c.id)}" title="Run “${esc(c.label)}” on ${esc(v.flow.into_branch)} as it was when this task started, so the comparison counts">${icon("target")}Measure the base at ${esc(t.base.slice(0, 8))}</button>` : "";
    return `<button type="button" class="mb-score" data-mwsub="lab" title="${vs?.stale ? `Compared with the base at ${esc(vs.head.slice(0, 8))}, not the commit this task started from: the difference may come from work merged since, so it isn't counted for the agent` : "Open the Lab"}"><b>${s.solved}/${s.tasks}</b> solved · ${s.passed}/${s.runs} runs passed${vs
      ? ` · <span class="${vs.stale ? "" : d > 0 ? "up" : d < 0 ? "down" : ""}">base ${vs.base}/${vs.shared}${d ? ` (${d > 0 ? "+" : "−"}${Math.abs(d)})` : ", same"}</span>${vs.lost ? ` · ${vs.lost} lost` : ""}${vs.stale ? ` · <span class="mb-stale">${icon("alert")}other base</span>` : ""}` : " · no base measured yet"}</button>${at}`;
  }
  function approvalLine(t) {
    const p = t.approval; if (!p) return "";
    const over = p.over?.length ? ` <span class="mb-over" title="${esc(p.over.join(" "))}">${icon("alert")}merged over ${plural(p.over.length, "doubt")}</span>` : "";
    return `<span class="faint small">${p.by_hand ? "by hand, marked" : ""} by ${esc(p.by || "?")} ${p.at ? ago(p.at) : ""}${p.commit ? ` · commit <code>${esc(p.commit.slice(0, 8))}</code>` : ""}${p.verdict === "approve" ? " · reviewed" : ""}</span>${over}`;
  }

  // ----- 5. submit -----
  function submitStep(wv) {
    const f = v.flow, merged = v.tasks.filter(t => t.status === "merged");
    return `<section class="mh-card" data-mbhold><h3>${icon("rocket")}Submit</h3>
      ${merged.length ? `<p>Merged into <b>${esc(f.into_branch)}</b>:</p><ul class="mb-mini">${merged.map(t => `<li>${icon("check")}${esc(t.title)} <code>${esc(t.merged || "")}</code> ${approvalLine(t)}</li>`).join("")}</ul>` : `<p class="faint">Nothing merged yet.</p>`}
      <p>Submitting is yours: run your final eval on ${esc(f.into_branch)}, then upload the agent the way you always do${wv.comp.link ? ` (<a href="${esc(wv.comp.link)}" target="_blank" rel="noopener noreferrer">competition page</a>)` : ""}. AXoR never submits for you.</p>
      ${f.submitted ? `<p class="mb-ok">${icon("check")}You marked it submitted ${ago(f.submitted)}${f.submit_note ? `: ${esc(f.submit_note)}` : ""}.</p>` : ""}
      <label class="in"><span>Note (optional): version, score, what went in</span><input data-mbdraft="subnote" value="${esc(draft("subnote"))}"></label>
      <div class="row"><button type="button" class="btn sm primary" data-mb="submitted" ${merged.length ? "" : "disabled"}>${icon("check")}Mark as submitted</button>
        <button type="button" class="btn sm" data-mbstep="plan">${icon("route")}Plan the next round</button></div></section>`;
  }

  // ---------- the side: team and log ----------
  function teamCard() {
    const ag = v.agents || [];
    return `<section class="mh-card mb-team" data-mbhold><div class="mb-h"><h3>${icon("users")}Team</h3><button type="button" class="btn sm" data-mbaddopen>${icon("userplus")}Add agent</button></div>
      ${shown.has("add") ? agentForm(null) : ""}
      <ul>${ag.map(a => `<li class="${a.on_team ? "" : "off"}">${av(a)}<span class="mb-who"><b>${esc(a.name)}</b><small>${esc(v.roles[a.role] || a.role)} · ${esc(a.model)}${a.on_team ? "" : " · off"}</small></span>
        <button type="button" class="iconbtn" data-mbedit="${a.id}" aria-label="Edit ${esc(a.name)}" title="Edit">${icon("edit")}</button>
        ${shown.has(`edit-${a.id}`) ? agentForm(a) : ""}</li>`).join("")}</ul>
      <p class="faint small">Director plans, engineers edit, the reviewer reads the diff. Checks (tests, evals) run on the workbench when you press them. <button type="button" class="linkbtn" data-mwsub="loadout">Skills, memory, MCP: Loadouts</button></p></section>`;
  }
  function agentForm(a) {
    const k = a ? `a${a.id}` : "anew";
    return `<div class="mb-agent-form">${a ? "" : `<label class="in"><span>Role</span><select data-mbdraft="${k}-role">${Object.entries(v.roles).filter(([r]) => r !== "director" || !firstOf("director")).map(([r, l]) => `<option value="${r}" ${draft(`${k}-role`, "engineer") === r ? "selected" : ""}>${l}</option>`).join("")}</select></label>`}
      <label class="in"><span>Name</span><input data-mbdraft="${k}-name" value="${esc(draft(`${k}-name`, a?.name || ""))}"></label>
      <label class="in"><span>Model</span><select data-mbdraft="${k}-model">${v.models.map(m => `<option ${draft(`${k}-model`, a?.model || "sonnet") === m ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <label class="in"><span>How it works (instructions)</span><textarea rows="3" data-mbdraft="${k}-ins">${esc(draft(`${k}-ins`, a?.instructions || ""))}</textarea></label>
      ${a ? `<label class="in"><span>Why you're changing it <em class="faint">needed when the model or the instructions change; saved with the new version</em></span><input maxlength="300" data-mbdraft="${k}-why" value="${esc(draft(`${k}-why`, ""))}" placeholder="e.g. Reviews missed failing tests"></label>` : ""}
      <div class="row"><button type="button" class="btn sm primary" data-mbsave="${a ? a.id : "new"}">${icon("check")}${a ? "Save" : "Add"}</button>
        ${a ? `<button type="button" class="btn sm" data-mbon="${a.id}">${a.on_team ? "Switch off" : "Switch on"}</button><button type="button" class="btn sm mw-danger" data-mbdel="${a.id}">${icon("trash")}Remove</button>` : ""}</div></div>`;
  }
  function logCard() {
    const l = v.log || [];
    return `<section class="mh-card mb-logcard"><h3>${icon("clock")}Every step</h3>${l.length ? `<ol>${l.slice(0, 40).map(x => `<li class="k-${esc(x.kind)}">${icon(LOG_ICON[x.kind] || "info")}<span>${esc(x.text)}<small>${ago(x.ts)}</small></span></li>`).join("")}</ol>` : `<p class="faint small">Nothing yet.</p>`}</section>`;
  }

  // ---------- Files ----------
  function filesView() {
    const f = v.flow;
    if (fs.wid !== vWid) { Object.assign(fs, { wid: vWid, path: "", ref: "", list: null, file: null, err: "" }); }
    if (!fs.list && !fs.busy && !fs.err) loadDir(fs.path);
    const refs = [["", "Your folder, live (read only)"], [f.into_branch, `${f.into_branch} (last commit)`],
      ...v.tasks.filter(t => t.slug).map(t => [`bench/${t.slug}`, `bench/${t.slug} · ${t.title.slice(0, 40)}`])];
    const parts = fs.path ? fs.path.split("/") : [];
    const crumbs = `<nav class="mb-crumbs"><button type="button" class="linkbtn" data-mbdir="">${esc(v.repo?.name || f.repo)}</button>${parts.map((p, i) => ` / <button type="button" class="linkbtn" data-mbdir="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")}</nav>`;
    const list = fs.list ? `<ul class="mb-files">${fs.list.items.map(x => `<li><button type="button" ${x.dir ? `data-mbdir="${esc(fs.path ? `${fs.path}/${x.name}` : x.name)}"` : `data-mbfile="${esc(fs.path ? `${fs.path}/${x.name}` : x.name)}"`} class="${fs.file?.path === (fs.path ? `${fs.path}/${x.name}` : x.name) ? "on" : ""}">
        ${icon(x.dir ? "folder" : "file")}<span>${esc(x.name)}</span>${x.size != null ? `<small>${x.size < 1024 ? `${x.size} B` : x.size < 1048576 ? `${fmtNum(x.size / 1024, 0)} kB` : `${fmtNum(x.size / 1048576, 1)} MB`}</small>` : ""}</button></li>`).join("")}
        ${fs.list.hidden ? `<li class="faint small">${plural(fs.list.hidden, "item")} hidden (caches, virtualenvs, .git)</li>` : ""}</ul>` : fs.err ? `<p class="mh-err">${esc(fs.err)}</p>` : Loading.line("Reading the folder…");
    const file = fs.file ? (fs.file.binary ? `<p class="faint">A binary file (${fmtNum(fs.file.size, 0)} bytes).</p>`
      : `<pre class="mb-code">${fs.file.content.split("\n").map((l, i) => `<span><i>${i + 1}</i>${esc(l) || " "}</span>`).join("")}</pre>${fs.file.truncated ? `<p class="faint small">Showing the first 500 kB.</p>` : ""}`)
      : `<p class="faint">Pick a file to read it.</p>`;
    return `<section class="mh-card mb-fs"><div class="mb-h"><h3>${icon("folder")}Files</h3><select data-mbref aria-label="Which version">${refs.map(([r, l]) => `<option value="${esc(r)}" ${r === fs.ref ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
      <p class="faint small">${fs.ref ? `Exactly what's committed on ${esc(fs.ref)}.` : `Straight from ${esc(v.repo?.path || "the folder")}, uncommitted changes included. Nothing here edits it.`}</p>
      ${crumbs}<div class="mb-fsgrid"><div>${list}</div><div class="mb-viewer">${fs.file ? `<div class="mb-fh"><code>${esc(fs.file.path)}</code></div>` : ""}${file}</div></div></section>`;
  }
  function loadDir(path) {
    fs.busy = true; fs.err = "";
    api(`${B}/flows/${v.flow.id}/tree?path=${encodeURIComponent(path)}&ref=${encodeURIComponent(fs.ref)}`)
      .then(r => { fs.list = r; fs.path = r.path; }).catch(e => { fs.err = e.message; }).finally(() => { fs.busy = false; MiningWork.rerender(); });
  }
  function loadFile(path) {
    api(`${B}/flows/${v.flow.id}/file?path=${encodeURIComponent(path)}&ref=${encodeURIComponent(fs.ref)}`)
      .then(r => { fs.file = r; }).catch(err).finally(() => MiningWork.rerender());
  }

  // ---------- actions ----------
  async function act(btn, fn) {
    if (btn) { btn.disabled = true; btn.classList.add("loading"); }
    try { const r = await fn(); return r; } catch (e) { err(e); return null; }
    finally { if (btn) { btn.disabled = false; btn.classList.remove("loading"); } }
  }
  const post = (url, body = {}, method = "POST") => api(`${B}${url}`, { method, body });

  function wire(el) {
    if (wired) return; wired = true;
    MiningLoadout.wire(el);
    MiningLab.wire(el);
    MiningGitHub.wire(el);
    el.addEventListener("input", e => {
      const t = e.target.closest("[data-mbdraft]"); if (!t) return;
      drafts[t.dataset.mbdraft] = t.matches("[data-mbbool]") ? (t.checked ? "1" : "0") : t.value;
    });
    el.addEventListener("change", async e => {
      const t = e.target;
      if (t.matches("[data-mbdraft]")) {  // typed text re-renders on the next poll: re-rendering here would eat the click that blurred it
        drafts[t.dataset.mbdraft] = t.matches("[data-mbbool]") ? (t.checked ? "1" : "0") : t.value;
        if (t.matches("[data-mbbool], select")) { t.blur(); MiningWork.rerender(); }
        return;
      }
      if (t.matches("[data-mbconfirm]")) { const nv = await act(null, () => post(`/flows/${v.flow.id}`, { confirm: t.checked }, "PATCH")); if (nv) { apply(nv); Auth.toast(t.checked ? "The team asks you between agents" : "Engineers hand straight to the reviewer"); } return; }
      if (t.matches("[data-mbinto]")) { t.blur(); const nv = await act(null, () => post(`/flows/${v.flow.id}`, { into: t.value }, "PATCH")); if (nv) { apply(nv); Auth.toast(`Works from ${t.value} now`); } return; }
      if (t.matches("[data-mbref]")) { t.blur(); fs.ref = t.value; fs.list = null; fs.file = null; fs.path = ""; return MiningWork.rerender(); }
      if (t.matches("[data-mbresuse]")) { const nv = await act(null, () => api(`/api/mining/research/flows/${v.flow.id}`, { method: "PATCH", body: { use: t.checked } })); if (nv) { apply(nv); Auth.toast(t.checked ? "The Director gets the report" : "The Director plans without it"); } return; }
    });
    el.addEventListener("toggle", e => {
      const d = e.target.closest?.("[data-mbdetails]"); if (!d) return;
      d.open ? shown.add(d.dataset.mbdetails) : shown.delete(d.dataset.mbdetails);
    }, true);
    el.addEventListener("click", async e => {
      const t = e.target;
      if (!t.closest(".mb-more") && shown.has("more")) { shown.delete("more"); el.querySelector(".mb-more")?.removeAttribute("open"); }
      if (t.closest(".mb-more-menu [data-mwsub]")) { shown.delete("more"); }
      const st = t.closest("[data-mbstep]");
      if (st) { pick = st.dataset.mbstep; if (MiningWork.view()) MiningWork.go("flow"); return; }
      const dr = t.closest("[data-mbdir]"); if (dr) { fs.file = null; return loadDir(dr.dataset.mbdir); }
      const fl = t.closest("[data-mbfile]"); if (fl) return loadFile(fl.dataset.mbfile);
      const rn = t.closest("[data-mbrun]"); if (rn) { const r = rn.dataset.mbrun; opened.has(r) ? opened.delete(r) : (opened.add(r), pullLogs()); return MiningWork.rerender(); }
      const cp = t.closest("[data-mbcopy]"); if (cp) { navigator.clipboard?.writeText(cp.dataset.mbcopy).then(() => Auth.toast("Copied"), err); return; }
      const df = t.closest("[data-mbdiff]");
      if (df) {
        const id = +df.dataset.mbdiff, d = diffs[id] ||= {};
        d.open = !d.open;
        if (d.open) { d.data = null; d.err = ""; api(`${B}/tasks/${id}/diff`).then(x => { d.data = x; }).catch(e => { d.err = e.message; }).finally(() => MiningWork.rerender()); }
        return MiningWork.rerender();
      }
      const bo = t.closest("[data-mbbackopen]"); if (bo) { const k = `back-${bo.dataset.mbbackopen}`; shown.has(k) ? shown.delete(k) : shown.add(k); return MiningWork.rerender(); }
      if (t.closest("[data-mbaddopen]")) { shown.has("add") ? shown.delete("add") : shown.add("add"); return MiningWork.rerender(); }
      const ed = t.closest("[data-mbedit]"); if (ed) { const k = `edit-${ed.dataset.mbedit}`; shown.has(k) ? shown.delete(k) : shown.add(k); return MiningWork.rerender(); }
      const sv = t.closest("[data-mbsave]");
      if (sv) {
        const id = sv.dataset.mbsave, a = id === "new" ? null : AG()[+id], k = a ? `a${a.id}` : "anew";
        const body = { name: draft(`${k}-name`, a?.name || "").trim(), model: draft(`${k}-model`, a?.model || "sonnet"), instructions: draft(`${k}-ins`, a?.instructions || "") };
        if (!body.name) return Auth.toast("Give the agent a name");
        if (a && (body.model !== (a.model || "") || body.instructions !== (a.instructions || ""))) {  // a change to what the agent does needs a reason
          body.reason = draft(`${k}-why`, "").trim();
          if (body.reason.length < 3) return Auth.toast("Say why you're changing it");
        }
        const nv = await act(sv, () => a ? post(`/agents/${a.id}`, body, "PATCH") : post(`/flows/${v.flow.id}/agents`, { ...body, role: draft(`${k}-role`, "engineer") }));
        if (nv) { ["name", "model", "ins", "role", "why"].forEach(x => delete drafts[`${k}-${x}`]); shown.delete(a ? `edit-${a.id}` : "add"); apply(nv); Auth.toast(a ? "Saved" : `${body.name} joined the team`); }
        return;
      }
      const on = t.closest("[data-mbon]"); if (on) { const a = AG()[+on.dataset.mbon]; const nv = await act(on, () => post(`/agents/${a.id}`, { on: !a.on_team }, "PATCH")); if (nv) apply(nv); return; }
      const del = t.closest("[data-mbdel]");
      if (del) { const a = AG()[+del.dataset.mbdel]; return UI.confirm({ title: `Remove ${esc(a.name)} from the team?`, body: "Tasks assigned to it go to another engineer when they start.", ok: "Remove",
        run: async () => { apply(await post(`/agents/${a.id}`, {}, "DELETE")); } }).catch(err); }
      const ck = t.closest("[data-mbcheck]");
      if (ck) { const nv = await act(ck, () => post(`/tasks/${ck.dataset.id}/check`, { check: ck.dataset.mbcheck })); if (nv) { apply(nv); pullLogs(); } return; }
      const ba = t.closest("[data-mbbaseat]");  // the Lab measures the base at the task's starting commit; the comparison follows
      if (ba) { const x = await act(ba, () => api(`/api/mining/lab/flows/${v.flow.id}/baseline`, { method: "POST", body: { check: ba.dataset.check, at: ba.dataset.mbbaseat } }));
        if (x) { Auth.toast(`Measuring ${v.flow.into_branch} at ${ba.dataset.mbbaseat.slice(0, 8)}: the comparison follows when it ends`); need(vWid, true); } return; }
      const rs = t.closest("[data-mbresearch]");
      if (rs) { const nv = await act(rs, () => api(`/api/mining/research/flows/${v.flow.id}`, { method: "POST", body: { focus: draft("rsfocus") } })); if (nv) { delete drafts.rsfocus; apply(nv); Auth.toast("The Workforce is on it"); } return; }
      const im = t.closest("[data-mbimprove]"); if (im) { MiningLoadout.show("improve"); return MiningWork.go("loadout"); }
      const tb = t.closest("[data-mbt]");
      if (tb) return task(tb, tb.dataset.mbt, +tb.dataset.id);
      const b = t.closest("[data-mb]"); if (!b) return;
      const k = b.dataset.mb;
      if (k === "create") {
        const repos = v.info?.repos || [], r = repos.find(x => x.id === draft("s-repo", repos[0]?.id)) || repos[0];
        const nv = await act(b, () => post(`/comps/${vWid}`, { repo: r.id, into: draft("s-into", r.branch || r.branches[0]), goal: draft("s-goal", MiningWork.view()?.comp.goal || "") }));
        if (nv) { pick = null; apply(nv); Auth.toast("The team is set up"); }
      }
      if (k === "savegoal") { const nv = await act(b, () => post(`/flows/${v.flow.id}`, { goal: draft("goal", v.flow.goal) }, "PATCH")); if (nv) { delete drafts.goal; apply(nv); Auth.toast("Goal saved"); } }
      if (k === "savebudget") { const nv = await act(b, () => post(`/flows/${v.flow.id}`, { budget: +draft("budget", v.flow.budget) }, "PATCH")); if (nv) { delete drafts.budget; apply(nv); Auth.toast("Saved"); } }
      if (k === "plan") { const nv = await act(b, () => post(`/flows/${v.flow.id}/plan`, { note: draft("plannote") })); if (nv) { delete drafts.plannote; pick = "plan"; apply(nv); pullLogs(); } }
      if (k === "approve") {
        const tasks = v.tasks.filter(x => x.status === "proposed").map(x => ({ id: x.id, on: draft(`p-on-${x.id}`, "1") === "1", title: draft(`p-title-${x.id}`, x.title), detail: draft(`p-detail-${x.id}`, x.detail || ""),
          engineer: +draft(`p-eng-${x.id}`, x.engineer_id ?? "") || null }));
        const nv = await act(b, () => post(`/flows/${v.flow.id}/approve`, { tasks }));
        if (nv) { Object.keys(drafts).filter(x => x.startsWith("p-")).forEach(x => delete drafts[x]); pick = "work"; apply(nv); Auth.toast("Approved: start the tasks in Work"); }
      }
      if (k === "addtask") {
        const title = draft("n-title").trim(); if (title.length < 2) return Auth.toast("Give the task a title");
        const eng = +draft("n-eng", (v.agents.find(a => a.role === "engineer" && a.on_team) || {}).id) || null;
        const nv = await act(b, () => post(`/flows/${v.flow.id}/tasks`, { title, detail: draft("n-detail"), engineer: eng }));
        if (nv) { delete drafts["n-title"]; delete drafts["n-detail"]; apply(nv); Auth.toast("Added: start it in Work"); }
      }
      if (k === "submitted") { const nv = await act(b, () => post(`/flows/${v.flow.id}/submitted`, { note: draft("subnote") })); if (nv) { delete drafts.subnote; apply(nv); Auth.toast("Marked as submitted"); } }
      if (k === "reset") return UI.confirm({ title: "Start the workflow over?", body: "The tasks, team and log are forgotten. Branches on the folder stay.", ok: "Start over",
        run: async () => { apply(await post(`/flows/${v.flow.id}`, {}, "DELETE")); pick = null; } }).catch(err);
    });
  }
  async function task(btn, k, id) {
    const t = v.tasks.find(x => x.id === id); if (!t) return;
    if (k === "drop") return UI.confirm({ title: `Drop “${esc(t.title)}”?`, body: t.slug ? `Its branch bench/${esc(t.slug)} and that folder are deleted. Your checkout isn't touched.` : "", ok: "Drop",
      run: async () => { apply(await post(`/tasks/${id}/drop`)); } }).catch(err);
    if (k === "back") {
      const note = draft(`back-${id}`).trim(); if (note.length < 2) return Auth.toast("Say what to change");
      const nv = await act(btn, () => post(`/tasks/${id}/back`, { note }));
      if (nv) { delete drafts[`back-${id}`]; shown.delete(`back-${id}`); delete refused[id]; pick = "work"; apply(nv); pullLogs(); Auth.toast(`Sent back to ${who(t.engineer_id)}`); }
      return;
    }
    if (k === "merge") return merge(btn, t);
    const nv = await act(btn, () => post(`/tasks/${id}/${k}`));
    if (!nv) return;
    if (k === "merged") { delete refused[id]; Auth.toast("Marked as merged"); }
    if (k === "start") { pick = "work"; Auth.toast(`${who(t.engineer_id)} started`); }
    if (k === "next") Auth.toast("Sent to review");
    if (diffs[id]) diffs[id].open = false;
    apply(nv); pullLogs();
  }
  // merging: one click when the review and checks back the branch's commit; otherwise a dialog with why, and that commit only
  async function merge(btn, t) {
    const nv = await act(btn, () => post(`/tasks/${t.id}/merge`));
    if (!nv) return;
    const m = nv.merge || {};
    if (!m.confirm) return merged(t.id, nv);
    apply(nv);
    const sha = esc(m.head.slice(0, 8));
    return UI.confirm({ title: `Merge “${esc(t.title)}” anyway?`, icon: "commit", ok: `Merge ${sha}`,
      body: `This merges commit <code>${sha}</code> of bench/${esc(t.slug)} into ${esc(v.flow.into_branch)}, and nothing newer. The merge is recorded with these doubts:`,
      items: m.confirm.map(esc),
      run: async () => merged(t.id, await post(`/tasks/${t.id}/merge`, { anyway: true, head: m.head })) }).catch(err);
  }
  function merged(id, nv) {
    if (nv.merge?.ok) { delete refused[id]; Auth.toast(`Merged ${nv.merge.from ? nv.merge.from.slice(0, 8) : ""} (${nv.merge.head})`); }
    else { refused[id] = nv.merge; Auth.toast("Not merged: see why on the task"); }
    if (diffs[id]) diffs[id].open = false;
    apply(nv); pullLogs();
  }
  return { owns, tabs, page, wire, holding, view: () => v, apply, act };
})();
