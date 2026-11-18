/* My workspace → Overview (overview.py): what waits for you and what every agent does, on one page, across Competition teams,
   the Workflow, the project team, My subnets, Workforce and Agent HQ.
   - Needs you: everything waiting for you, worst first, each with the button that takes you to it.
   - At work now, Competition teams (verdict, progress, the week, today's tokens, the Workflow's step), your miners, the
     project team, spend and the latest activity.
   workspace.js mounts it in its pane from the sidebar's Overview entry. It refreshes every 20 seconds while it shows and
   redraws only when something changed, so a refresh never moves the page under you. */
const Overview = (() => {
  const SRC = { teams: ["users", "Competition teams"], workflow: ["route", "Workflow"], projects: ["cycle", "Project team"], mining: ["trophy", "My subnets"],
                workforce: ["group", "Workforce"], hq: ["flag", "Agent HQ"], company: ["layers", "Company"], missions: ["target", "Mission OS"], longtask: ["file", "Long tasks"] };
  const STATE = { working: ["new", "Working"], stuck: ["avoid", "Stuck"], waiting: ["caution", "Waiting for you"], idle: ["", "Idle"], closed: ["", "Closed"] };
  const LEVEL = { stop: "Urgent", warn: "Needs you", info: "For your information" };
  const STEPS = [["goal", "Goal"], ["plan", "Plan"], ["work", "Work"], ["review", "Review"], ["submit", "Submit"]];
  const PHASE = { plan: "Planning", do: "Doing", check: "Checking", act: "Reporting", waiting: "Waiting for you", done: "Done", failed: "Failed", cancelled: "Stopped" };
  const USAGE = { chat: "Agent chats", workspace: "Workspace", study: "Study tutors", practice: "Practice drills", lab: "Study lab", team: "Project team",
                  board: "Whiteboard AI", profile: "Profile AI review", mining: "My subnets", writing: "Writing help", hq: "Agent HQ", tech: "Technology Research" };  // chatkit.js's names
  const NEEDS_MAX = 8, RUN_MAX = 10, EVERY = 20000;
  let d = null, sig = "", failed = "", seq = 0, timer = null, all = false, wired = false, gos = [];
  const el = () => document.getElementById("ov");
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : String(n);
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const meter = (x, cls = "", label = "") => `<span class="ov-meter ${cls}" role="img" aria-label="${esc(label || pct(x, 0))}"><i style="width:${(Math.min(1, x || 0) * 100).toFixed(0)}%"></i></span>`;
  const go = x => x ? `data-ov-go="${gos.push(x) - 1}"` : "";  // where an item leads: kept per draw, read on click
  const src = k => SRC[k] || ["info", k];

  // ---------- data ----------
  function render(pane) {
    pane.innerHTML = `<div id="ov" class="ov">${d ? body() : failed ? failure() : Loading.cards(3, "card")}</div>`;
    wire();
    load(true);
  }
  // fresh: opening the page or Refresh reads past the server's few-second cache; the 20-second polls don't
  async function load(fresh = false) {
    clearTimeout(timer);
    const s = ++seq;
    try {
      const r = await api(`/api/workspace/overview${fresh ? "?fresh=1" : ""}`);
      if (s !== seq) return;
      const nsig = JSON.stringify({ ...r, at: 0 });
      d = r; failed = "";
      if (nsig !== sig || !el()?.querySelector(".ov-top")) { sig = nsig; draw(); } else stamp();
    } catch (e) { if (s !== seq) return; failed = e.message; if (!d) draw(); }
    badge();
    schedule();
  }
  // only while the Overview shows: leaving it (a subnet, notes, another page) lets the timer lapse; opening it again restarts it
  function schedule() {
    clearTimeout(timer);
    if (!el()) return;
    timer = setTimeout(() => { if (!el() || S.view !== "workspace") return; if (document.visibilityState !== "visible") return schedule(); load(); }, EVERY);
  }
  // the count in the workspace's sidebar; peek() fetches it without a page (workspace.js calls it when the workspace loads)
  const count = () => d?.counts?.waiting || 0;
  function badge() { const b = document.getElementById("ws-ov-n"); if (b) { b.textContent = count() || ""; b.hidden = !count(); } }
  async function peek() { if (el()) return; try { d = await api("/api/workspace/overview"); sig = ""; badge(); } catch { /* the sidebar just shows no count */ } }
  function draw() { const x = el(); if (x) x.innerHTML = d ? body() : failure(); }
  function stamp() { const t = el()?.querySelector("[data-ov-at]"); if (t) t.textContent = `Updated ${ago(d.at)}`; }
  const failure = () => `<div class="card empty">${icon("alert")} ${esc(failed)} <button type="button" class="linkbtn" data-ov="refresh">Try again</button></div>`;

  // ---------- the page ----------
  function body() {
    gos = [];
    const C = d.counts, on = d.sources, any = Object.values(on).some(Boolean);
    const head = `<div class="ov-top"><div><h1 class="page">Overview</h1>
        <p class="lead">What waits for you and what your agents are doing, across Competition teams, the Workflow, My subnets and the rest. <span class="faint" data-ov-at>Updated ${ago(d.at)}</span></p></div>
        <div class="row ov-actions">${$("#tab-studio") && !$("#tab-studio").hidden ? `<button type="button" class="btn sm" ${go({ view: "studio" })} title="Every agent, live runs, traces and the Agent Studio">${icon("radio")}Agents</button>` : ""}
          <button type="button" class="btn sm" data-ov="refresh">${icon("reset")}Refresh</button></div></div>`;
    if (!any) return head + `<div class="card empty">${icon("bot")} Agents are available to administrators only, so there's nothing to show here yet.${Auth.me()?.role === "admin" ? "" : " Ask an administrator to let members use them."}</div>`;
    const tiles = [
      tile("inbox", "Waiting for you", C.waiting, C.stop ? `${C.stop} urgent` : C.waiting ? "nothing urgent" : "you're all caught up", C.stop ? "t-stop" : C.waiting ? "t-warn" : ""),
      tile("zap", "At work now", C.working, C.working ? plural(C.working, "agent run") : "no agent is running"),
      on.teams ? tile("users", "Competition teams", C.teams, C.stuck ? `${C.stuck} stuck` : d.closed ? `${d.closed} closed` : "open", C.stuck ? "t-stop" : "") : "",
      on.teams || C.done_week ? tile("check", "Tasks done (7 days)", C.done_week, `${C.done_day} today`) : "",
      on.teams ? tile("alert", "Failed runs (24 h)", C.failed_day, `${C.ok_day} succeeded`, C.failed_day && !C.ok_day ? "t-stop" : C.failed_day ? "t-warn" : "") : "",
      on.spend ? tile("coins", "Tokens today", tok(C.tokens_today), `${tok(d.spend?.week)} in 7 days`) : "",
    ].join("");
    return head
      + (d.errors.length ? `<div class="ov-err" role="status">${icon("alert")}<span>Some parts couldn't be read: ${d.errors.map(esc).join(" · ")}</span></div>` : "")
      + `<div class="stats ov-kpis">${tiles}</div>
      <div class="ov-grid">${needs()}<div class="ov-side">${running()}${on.projects ? projects() : ""}</div>${on.teams ? teams() : ""}${on.mining ? miners() : ""}${on.spend && d.spend ? spend() : ""}${activity()}</div>`;
  }
  const tile = (ic, label, value, sub, cls = "") => `<div class="stat ${cls}"><div class="label">${icon(ic)}${label}</div><div class="value num">${value}</div><div class="sub">${sub}</div></div>`;
  const card = (cls, ic, title, n, right, inner) => `<section class="card ov-card ${cls}"><div class="ws-card-head"><h3>${icon(ic)}${title}${n != null ? ` <span class="faint">${n}</span>` : ""}</h3>${right || ""}</div>${inner}</section>`;
  const none = text => `<p class="ov-none faint">${text}</p>`;

  function needs() {
    const list = d.needs.filter(x => x.level !== "info"), shown = all ? list : list.slice(0, NEEDS_MAX);
    return card("ov-needs", "inbox", "Needs you", list.length, "", list.length ? `<ul class="ov-list">${shown.map(x => `<li class="ov-need l-${x.level}">
        <span class="ov-dot" title="${LEVEL[x.level]}"></span><span class="sr">${LEVEL[x.level]}: </span>
        <div class="ov-txt"><b>${esc(x.title)}</b><small class="faint">${icon(src(x.source)[0])}${esc(src(x.source)[1])}${x.where && x.where !== src(x.source)[1] ? ` · ${esc(x.where)}` : ""}</small>${x.detail ? `<p>${esc(x.detail)}</p>` : ""}</div>
        <button type="button" class="btn sm ${x.level === "stop" ? "primary" : ""}" ${go(x.go)}>${esc(x.label)}</button></li>`).join("")}</ul>
      ${list.length > NEEDS_MAX ? `<button type="button" class="linkbtn ov-more" data-ov="all">${all ? "Show fewer" : `Show all ${list.length}`}</button>` : ""}`
      : `<p class="ov-none ov-clear">${icon("check")}Nothing waits for you.</p>`);
  }
  function running() {
    const r = d.running;
    return card("ov-run", "zap", "At work now", r.length, "", r.length ? `<ul class="ov-list">${r.slice(0, RUN_MAX).map(x => `<li><button type="button" class="ov-row" ${go(x.go)}>
        <span class="ov-pulse" aria-hidden="true"></span><span class="ov-txt"><b>${esc(x.who)}</b> <span>${esc(x.what)}</span>
        <small class="faint">${esc(x.where)} · ${esc(src(x.source)[1])}${x.since ? ` · started ${ago(x.since)}` : ""}</small></span></button></li>`).join("")}</ul>
      ${r.length > RUN_MAX ? `<p class="faint small">and ${r.length - RUN_MAX} more</p>` : ""}` : none("No agent is running right now."));
  }
  function teams() {
    const t = d.teams;
    const steps = f => { const i = STEPS.findIndex(s => s[0] === f.step);
      return `<div class="ov-steps"><span class="faint small">Workflow</span><ol aria-label="Workflow step: ${STEPS[i]?.[1] || esc(f.step)}">${STEPS.map(([, l], j) => `<li class="${j < i ? "done" : j === i ? "on" : ""}"${j === i ? ' aria-current="step"' : ""}>${l}</li>`).join("")}</ol>
        ${f.waiting ? `<b class="ov-wait">${f.waiting} wait for you</b>` : f.running ? `<span class="faint small">${plural(f.running, "run")} going</span>` : ""}</div>`; };
    const one = x => {
      const [cls, lab] = STATE[x.state] || ["", x.state], used = x.budget ? x.day / x.budget : 0, max = Math.max(1, ...x.week);
      return `<article class="ov-team s-${x.state}">
        <div class="ov-team-head"><div class="ov-txt"><b>SN${x.netuid} · ${esc(x.label)}</b><small class="faint">${esc(x.subnet)}${x.ends ? ` · ends ${esc(x.ends)}` : ""}${x.paused ? " · paused" : x.autopilot ? " · autopilot" : ""}</small></div><span class="badge ${cls}">${lab}</span></div>
        <p class="ov-line">${esc(x.line)}${x.why && x.state !== "working" ? ` <span class="faint">${esc(x.why)}</span>` : ""}</p>
        <div class="ov-prog"><div><span class="small">${x.done} of ${plural(x.total, "task")} done</span>${meter(x.total ? x.done / x.total : 0, "good", `${x.done} of ${x.total} done`)}</div>
          <div class="ov-week" role="img" aria-label="Tasks done each day, last 7 days: ${x.week.join(", ")}">${x.week.map((n, i) => `<i style="--h:${(n / max * 100).toFixed(0)}%" title="${n} done ${i === 6 ? "today" : `${6 - i} day${i < 5 ? "s" : ""} ago`}"></i>`).join("")}</div></div>
        <div class="mini ov-mini"><div><span>Agents at work</span><b>${x.working} of ${x.active}</b></div><div><span>Queued</span><b>${x.queued}</b></div>
          <div><span>Runs (24 h)</span><b>${x.ok_day}${x.fails_day ? ` <em class="ov-bad">· ${x.fails_day} failed</em>` : ""}</b></div></div>
        <div class="ov-budget"><span class="small">Tokens today</span>${meter(used, used >= 1 ? "stop" : used > .8 ? "warn" : "", `${pct(used, 0)} of today's budget`)}<small class="faint num">${tok(x.day)} of ${tok(x.budget)}</small></div>
        ${x.workflow ? steps(x.workflow) : ""}
        <div class="row end ov-actions"><button type="button" class="btn sm" ${go({ view: "teams", wid: x.id, sub: "status" })}>${icon("info")}Status</button>
          <button type="button" class="btn sm" ${go({ view: "teams", wid: x.id, sub: x.workflow ? "flow" : "tasks" })}>${icon(x.workflow ? "route" : "list")}${x.workflow ? "Workflow" : "Board"}</button></div></article>`;
    };
    return card("ov-teams ov-wide", "users", "Competition teams", t.length, `<button type="button" class="linkbtn" ${go({ view: "teams" })}>All teams</button>`,
      t.length ? `<div class="ov-team-grid">${t.map(one).join("")}</div>${d.closed ? `<p class="faint small">${plural(d.closed, "closed team")} not shown.</p>` : ""}`
        : none(`No open teams.${d.closed ? ` ${plural(d.closed, "closed team")}.` : ""} My subnets → a campaign → Teams makes one per competition.`));
  }
  function miners() {
    const m = d.miners;
    return card("ov-miners", "trophy", "Your miners", null, `<button type="button" class="linkbtn" ${go({ view: "mining" })}>My subnets</button>`,
      m.length ? `<ul class="ov-list">${m.map(x => `<li class="ov-miner">
          <div class="ov-txt"><b>SN${x.netuid}${x.name ? ` · ${esc(x.name)}` : ""}</b>${x.critical ? ` <span class="badge avoid">${x.critical} critical</span>` : ""}${x.running ? ` <span class="badge new">cycle running</span>` : ""}
            <p class="faint small">${esc(x.headline || (x.ts ? "" : "No brief yet: the team's first cycle writes one."))}</p></div>
          <dl class="ov-ranks"><div><dt>Best rank</dt><dd class="num">${x.rank ? `#${x.rank} <small class="faint">of ${x.of}</small>` : "–"}</dd></div>
            <div><dt>Earns</dt><dd class="num">${x.em != null ? `${money(x.em)}/d` : "–"}</dd></div>
            <div><dt>Goal: top ${x.target}</dt><dd class="num">${x.rank && x.rank <= x.target ? `<span class="ok">${icon("check")}Reached</span>` : x.gap ? `+${money(x.gap)}/d to go` : "–"}</dd></div></dl></li>`).join("")}</ul>`
        : none("No campaigns yet. Start one in My subnets to track your miners' rank and earnings here."));
  }
  function projects() {
    const p = d.projects;
    return card("ov-projects", "cycle", "Project team", null, "", p.length ? `<ul class="ov-list">${p.map(x => `<li><button type="button" class="ov-row" ${go({ view: "workspace", netuid: x.netuid, tab: x.pending ? "reports" : "team" })}>
        <span class="ov-phase s-${esc(x.status)}">${PHASE[x.status] || esc(x.status)}</span><span class="ov-txt"><b>SN${x.netuid}</b> <span>${esc(x.goal)}</span>
        <small class="faint">Round ${x.round || 1} · ${tok(x.tokens)} of ${tok(x.budget)} tokens${x.pending ? ` · ${plural(x.pending, "decision")} waiting` : ""}${x.error ? ` · ${esc(x.error)}` : ""}</small></span></button></li>`).join("")}</ul>`
      : none("No cycles yet. A subnet's Team tab starts one: the project team plans, works, checks and reports on its own."));
  }
  function spend() {
    const s = d.spend, top = s.by_source[0]?.tokens || 1, max = Math.max(1, ...s.days.map(x => x.tokens));
    return card("ov-spend", "coins", "Spend", null, `<span class="faint small">model tokens</span>`, `
      <div class="mini"><div><span>Today</span><b>${tok(s.today)}</b></div><div><span>7 days</span><b>${tok(s.week)}</b></div><div><span>30 days</span><b>${tok(s.month)}</b></div></div>
      <div class="ov-days" role="img" aria-label="Tokens per day, last 14 days">${s.days.map(x => `<i style="--h:${(x.tokens / max * 100).toFixed(0)}%" title="${esc(x.day)}: ${tok(x.tokens)}"></i>`).join("")}</div>
      ${s.by_source.length ? `<ul class="ov-src">${s.by_source.map(x => `<li><span>${esc(USAGE[x.id] || x.id)}</span>${meter(x.tokens / top)}<b class="num">${tok(x.tokens)}</b></li>`).join("")}</ul>` : none("No tokens spent in 30 days.")}
      ${s.workflow_usd_week != null ? `<p class="faint small">The Workflow runs Claude Code on the host: ${usd(s.workflow_usd_week)} in 7 days.</p>` : ""}`);
  }
  function activity() {
    const a = d.activity;
    return card("ov-act ov-wide", "list", "Latest activity", null, "", a.length ? `<ul class="ov-feed">${a.map(x => `<li><button type="button" class="ov-row" ${go(x.go)}>
        <time class="faint num" datetime="${new Date(x.ts * 1000).toISOString()}">${ago(x.ts)}</time><span class="ov-tag">${esc(src(x.source)[1])}</span>
        <span class="ov-txt"><b>${esc(x.where)}</b> ${esc(x.text)}</span></button></li>`).join("")}</ul>` : none("Nothing has happened yet."));
  }

  // ---------- going places ----------
  function follow(g) {
    if (!g) return;
    if (g.view === "teams") { MiningWork.openPage(g.wid); if (g.sub) MiningWork.go(g.sub); return; }
    if (g.view === "workspace") return Workspace.show(g.netuid, g.tab);
    setView(g.view);
  }
  function wire() {
    if (wired) return; wired = true;
    $("#view-workspace").addEventListener("click", e => {
      const t = e.target; if (!t.closest("#ov")) return;
      const a = t.closest("[data-ov]")?.dataset.ov;
      if (a === "refresh") { sig = ""; return load(true); }
      if (a === "all") { all = !all; return draw(); }
      const g = t.closest("[data-ov-go]"); if (g) follow(gos[+g.dataset.ovGo]);
    });
  }

  return { render, peek, count };
})();
