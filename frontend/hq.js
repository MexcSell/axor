/* Agent HQ (admins): the agents that run AXoR's platform (hq.py).
   Overview: the Team Boss's latest hourly report, fixes waiting for you, the org chart (boss, Agents Manager, the two
   leads and their field agents, each with its state) and the live activity feed. Issues: what the checks found, the field
   agent's diagnosis, its fixes and the lead's decisions; snooze. Reports: every hourly report. Roster: the Agents
   Manager's view of every agent on the server, HQ's and members' (pause and resume). Settings: duty, how much HQ may fix on
   its own, the model, the hourly token budget and push notifications. Approving a fix or letting HQ fix on its own asks
   for sudo; the server checks every rule again. */
const HQ = (() => {
  let d = null, tab = "overview", wired = false, timer = null, filter = "open", issues = null, reports = null, report = null, roster = null, models = null;
  const root = () => $("#hq");
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 1)}k` : fmtNum(n || 0, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const day = ts => new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const left = ts => { const m = Math.max(0, Math.round((ts - Date.now() / 1000) / 60)); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m} min`; };
  const STATE = {  // field agent state -> dot class and words
    ok: ["ok", "All clear"], issues: ["bad", "Found issues"], working: ["run", "Working…"], error: ["warn", "Can't check"],
    unavailable: ["none", "Not set up here"], off: ["off", "Off duty"], idle: ["wait", "Waiting for the first patrol"]};
  const STEPS = [["checks", "Checks"], ["investigating", "Investigating"], ["reviewing", "Leads review"], ["report", "Report"]];
  const TONE = { green: ["ok", "All clear"], amber: ["warn", "Needs a look"], red: ["bad", "Action needed"] };
  const FIX = { awaiting: ["warn", "Waiting for you"], done: ["ok", "Done"], failed: ["bad", "Failed"], rejected: ["off", "Rejected"],
                expired: ["off", "Expired"], running: ["run", "Running"], proposed: ["wait", "With the lead"] };
  const AUTONOMY = {
    report: ["eye", "Report only", "Field agents diagnose and recommend. Nothing is proposed or changed."],
    ask: ["hand", "Ask me", "Every fix a lead doesn't reject waits here for your approval."],
    auto: ["zap", "Fix safe issues", "A lead may restart something that's failing right now on its own: at most 3 fixes a patrol, once per target in 6 hours. Rollbacks, deploys and anything else still wait for you."]};

  // a field agent's own state; the boss, the manager and the leads are on duty, working or off duty with HQ
  const stateOf = a => !a.tier ? STATE[a.status] || STATE.idle : a.status === "working" ? STATE.working : a.status === "off" ? STATE.off : ["ok", "On duty"];
  const people = () => Object.fromEntries([...(d?.staff || []), ...(d?.field || [])].map(a => [a.id, a]));
  const av = (a, size = "sm") => a ? `<span class="av ${size} c-${a.color}" aria-hidden="true">${icon(a.icon)}</span>` : `<span class="av ${size} c-slate">${icon("bot")}</span>`;
  const who = id => { const a = people()[id]; return a ? `<b>${esc(a.name)}</b> <span class="faint">${esc(a.title)}</span>` : esc(id || "HQ"); };
  const sev = s => `<span class="hq-sev ${s}">${s === "critical" ? icon("alert") : icon("info")}${s === "critical" ? "Critical" : "Warning"}</span>`;
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;

  async function open() {
    wire();
    if (!d) root().innerHTML = `<h1 class="page">Agent HQ</h1>${Loading.line("Calling the agents in…")}`;
    await load().catch(e => { root().innerHTML = `<h1 class="page">Agent HQ</h1><div class="empty">${esc(e.message)}</div>`; });
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if ($("#view-hq").hidden) return;
      await load().catch(() => {});
      schedule();
    }, d?.running ? 2500 : 15000);
  }
  async function load() {
    d = await api("/api/hq");
    if (tab === "issues") issues = await api(`/api/hq/issues?status=${filter}`);
    if (tab === "roster" && !roster) roster = await api("/api/hq/roster");
    if (tab === "reports" && !reports) reports = await api("/api/hq/reports");
    render();
    badge(d.settings.available ? d.waiting.length + d.open.filter(i => i.severity === "critical" && !(i.snoozed_until > Date.now() / 1000)).length : 0);
  }

  // ---------- frame ----------
  function render() {
    const s = d.settings;
    if (!$(".hq-body", root())) root().innerHTML = `<div class="hq-top">
        <div><h1 class="page">Agent HQ</h1><p class="lead">Field agents check AXoR's services and infrastructure every ${s.patrol_minutes} minutes, investigate what they find and propose fixes; team leads review every fix, and the Team Boss reports to you every hour.</p></div>
        <div class="hq-actions"></div></div>
      <div class="hq-run" hidden></div>
      <div class="seg hq-tabs" role="tablist">${[["overview", "Overview", "dash"], ["issues", "Issues", "alert"], ["reports", "Reports", "doc"], ["roster", "Roster", "users"], ["settings", "Settings", "gear"]]
        .map(([k, l, ic]) => `<button type="button" role="tab" data-hqtab="${k}">${icon(ic)}${l}<span class="hq-n" data-n="${k}"></span></button>`).join("")}</div>
      <div class="hq-body"></div>`;
    $$(".hq-tabs button", root()).forEach(b => b.setAttribute("aria-pressed", b.dataset.hqtab === tab));
    const n = s.available ? { issues: d.open.length, overview: d.waiting.length } : {};  // turned off: earlier counts can't be acted on
    $$(".hq-n", root()).forEach(x => { x.textContent = n[x.dataset.n] || ""; x.classList.toggle("alert", x.dataset.n === "overview"); });
    put($(".hq-actions", root()), actions());
    const run = $(".hq-run", root());
    run.hidden = !d.running;
    put(run, d.running ? running() : "");
    const body = { overview, issues: issuesTab, reports: reportsTab, roster: rosterTab, settings: settingsTab }[tab];
    put($(".hq-body", root()), body());
    if (tab === "overview") feedTimes();
  }

  function actions() {
    const s = d.settings;
    if (!s.available) return `<span class="hq-duty off"><span class="ci ci-none"></span>Turned off on this server (HQ=0)</span>`;
    const next = s.on && d.next_patrol ? `next patrol ${d.next_patrol <= Date.now() / 1000 + 5 ? "now" : clock(d.next_patrol)} · report ~${clock(d.next_report)}` : "patrols paused";
    return `<span class="hq-duty ${s.on ? "on" : "off"}" title="${esc(AUTONOMY[s.autonomy][2])}"><span class="ci ${s.on ? "ci-ok" : "ci-none"}"></span>${s.on ? "On duty" : "Off duty"}
        <span class="faint">· ${next}</span></span>
      <span class="hq-mode">${icon(AUTONOMY[s.autonomy][0])}${AUTONOMY[s.autonomy][1]}</span>
      <button type="button" class="btn primary" data-hq="run" ${d.running ? "disabled" : ""}>${icon(d.running ? "cycle" : "play")}${d.running ? "Patrolling…" : "Patrol now"}</button>`;
  }

  function running() {
    const at = STEPS.findIndex(([k]) => k === d.running.step);
    return `<div class="hq-steps">${STEPS.filter(([k]) => k !== "report" || d.running.report).map(([k, l], i) =>
      `<span class="${i < at ? "done" : i === at ? "now" : ""}">${i < at ? icon("check") : `<i></i>`}${l}</span>`).join("")}</div>
      <span class="faint small">Started ${clock(d.running.ts)} · ${d.running.report ? "with the hourly report" : "patrol"}</span>`;
  }

  // ---------- overview ----------
  function overview() {
    if (!d.settings.available) return `<div class="empty">Agent HQ is turned off on this server: HQ=0 is set in its environment, so no agent patrols and no fix can run.
      Earlier issues and reports stay readable under Issues and Reports. Remove HQ=0 and restart AXoR to turn it on.</div>`;
    return `${hero()}${waiting()}<div class="hq-grid"><section class="hq-org-wrap"><h2 class="hq-h">The team <span class="faint">${plural(d.field.filter(a => a.on).length, "field agent")} on the roster</span></h2>${org()}</section>
      <section class="hq-feed-wrap"><h2 class="hq-h">Activity <span class="hq-live ${d.running ? "on" : ""}">${d.running ? "live" : ""}</span></h2>${feed(d.events)}</section></div>`;
  }

  function hero() {
    const r = d.report;
    if (!r) return `<article class="hq-hero t-wait"><div class="hq-hero-main"><div class="hq-kicker">${icon("doc")}Hourly report</div>
      <h2 class="hq-head">The first report comes with the first patrol.</h2>
      <p class="hq-sum">${d.settings.on ? `The agents start about a minute after AXoR does, then every ${d.settings.patrol_minutes} minutes. Patrol now to see them work.` : "Patrols are paused: turn them on in Settings."}</p></div></article>`;
    const st = r.stats || {}, boss = people().boss, [cls, label] = TONE[r.status];
    const tile = (v, l, tone = "") => `<div class="hq-tile ${tone}"><b>${v}</b><span>${l}</span></div>`;
    return `<article class="hq-hero t-${cls}">
      <div class="hq-hero-main">
        <div class="hq-kicker"><span class="hq-pill t-${cls}">${label}</span>Hourly report · ${clock(r.ts)}${r.author === "boss" ? "" : ` · <span title="Nothing needed a model: this hour's report is written from the numbers">from the numbers</span>`}</div>
        <h2 class="hq-head">${esc(r.headline)}</h2>
        ${r.summary ? `<p class="hq-sum">${esc(r.summary)}</p>` : ""}
        ${r.actions.length ? `<div class="hq-todo"><div class="hq-todo-h">${icon("hand")}What needs you</div><ol>${r.actions.map(a => `<li>${esc(a)}</li>`).join("")}</ol></div>` : ""}
        <div class="hq-sign">${av(boss, "xs")}<span>${esc(boss.name)}, ${esc(boss.title)}</span><span class="faint">· next report ~${clock(d.next_report || r.ts + 3600)}</span>
          <button type="button" class="linkbtn" data-hq="reports">All reports</button></div>
      </div>
      <div class="hq-tiles">${tile(st.open ?? 0, "open", st.open ? "warn" : "")}${tile(st.fixed ?? 0, "fixed by HQ", st.fixed ? "ok" : "")}${tile(st.waiting ?? 0, "waiting for you", st.waiting ? "warn" : "")}
        ${tile(st.resolved ?? 0, "resolved")}${tile(st.patrols ?? 0, "patrols")}${tile(short(st.tokens || 0), "tokens")}</div>
    </article>`;
  }

  function waiting() {
    if (!d.waiting.length) return "";
    return `<section class="hq-wait"><h2 class="hq-h">${icon("hand")}Waiting for you <span class="faint">fixes expire 3 hours after they're proposed</span></h2>
      <div class="hq-cards">${d.waiting.map(fixCard).join("")}</div></section>`;
  }
  function fixCard(f) {
    const issue = d.open.find(i => i.id === f.issue_id), lead = people()[(people()[f.agent] || {}).team === "infra" ? "lead-infra" : "lead-services"];
    const backed = f.lead_decision === "approve";
    return `<article class="hq-fix ${f.danger ? "danger" : ""}" data-fix="${f.id}">
      <div class="hq-fix-top">${av(people()[f.agent])}<div><div class="hq-fix-label">${esc(f.label)}</div>
        <div class="faint small">${who(f.agent)}${issue ? ` · for <a href="#hq" data-hq-issue="${issue.id}">${esc(issue.title)}</a>` : ""}</div></div></div>
      ${f.reason ? `<p class="hq-fix-why">${esc(f.reason)}</p>` : ""}
      ${f.lead_note || f.result ? `<div class="hq-lead ${backed ? "ok" : ""}">${av(lead, "xs")}<span><b>${esc(lead?.name || "Lead")}</b> ${backed ? "backs it" : "escalated it"}${f.lead_note ? `: ${esc(f.lead_note)}` : ""}${f.result ? ` <span class="faint">${esc(f.result)}</span>` : ""}</span></div>` : ""}
      <div class="hq-fix-foot"><span class="faint small">${icon("clock")}expires in ${left(f.expires)}${f.safe ? "" : " · not a restart, so it's yours to decide"}</span>
        <span class="row"><button type="button" class="btn sm" data-hq="reject">Reject</button><button type="button" class="btn sm primary ${f.danger ? "danger" : ""}" data-hq="approve">${icon("check")}Approve</button></span></div>
    </article>`;
  }

  function org() {
    const P = people(), node = (a, cls = "") => {
      const s = stateOf(a);
      const meta = a.tier === "boss" ? `${d.report ? `Last report ${ago(d.report.ts)}` : "No report yet"}`
        : a.tier === "manager" ? `${plural(d.open.length, "open issue")} · ${short(d.hour_tokens)} tokens this hour`
        : a.tier === "leader" ? `${plural(a.open, "open issue")}${a.critical ? ` · <b class="hq-crit">${a.critical} critical</b>` : ""} · ${plural(a.fixed_day, "fix", "es")} today`
        : a.status === "unavailable" ? esc(a.note || "") : `${a.open ? `${plural(a.open, "issue")}${a.critical ? ` · <b class="hq-crit">${a.critical} critical</b>` : ""}` : a.last_run ? `Checked ${ago(a.last_run)}` : "Not checked yet"}`;
      return `<button type="button" class="hq-node ${cls} s-${a.status}" data-agent="${a.id}" aria-label="${esc(a.name)}, ${esc(a.title)}: ${s[1]}">
        ${av(a, a.tier === "boss" ? "" : "sm")}<span class="hq-node-txt"><b>${esc(a.name)}</b><span class="hq-node-title">${esc(a.title)}</span>
        <span class="hq-node-state"><span class="ci ci-${s[0]}"></span>${s[1]}</span><span class="hq-node-meta">${meta}</span></span></button>`;
    };
    const team = t => `<div class="hq-team"><div class="hq-team-name">${esc(t.name)}</div>${node(P[t.lead], "lead")}
      <div class="hq-squad">${d.field.filter(a => a.team === t.id).map(a => node(a, "field")).join("")}</div></div>`;
    return `<div class="hq-org"><div class="hq-tier">${node(P.boss, "boss")}</div><div class="hq-tier">${node(P.manager, "manager")}</div>
      <div class="hq-teams">${d.teams.map(team).join("")}</div></div>`;
  }

  const KIND_ICON = { assign: "inbox", investigate: "search", report: "doc", propose: "wrench", review: "eye", approve: "check", escalate: "hand",
    reject: "ban", fix: "check", resolved: "check", error: "alert", budget: "coins", nomodel: "info", worse: "alert", write: "edit", roster: "users",
    decision: "hand", snooze: "clock", skip: "info" };
  function feed(events) {
    if (!events.length) return `<div class="empty small">Nothing yet. Each patrol's work shows up here as it happens.</div>`;
    const P = people();
    return `<ol class="hq-feed">${events.map(e => `<li class="k-${e.kind}">${av(P[e.agent], "xs")}<div><span class="hq-feed-who">${esc(P[e.agent]?.name || "HQ")}</span>
      <span class="hq-feed-ico">${icon(KIND_ICON[e.kind] || "dots")}</span>${esc(e.text)}${e.tokens ? ` <span class="faint">· ${short(e.tokens)} tokens</span>` : ""}
      <time data-ts="${e.ts}" title="${stamp(e.ts)}"></time></div></li>`).join("")}</ol>`;
  }
  function feedTimes() { $$(".hq-feed time", root()).forEach(t => { t.textContent = ago(+t.dataset.ts); }); }

  // ---------- issues ----------
  function issuesTab() {
    const rows = issues?.issues;
    const seg = `<div class="seg" role="group" aria-label="Show">${[["open", "Open"], ["resolved", "Resolved"], ["all", "All"]].map(([k, l]) =>
      `<button type="button" data-hqfilter="${k}" aria-pressed="${filter === k}">${l}</button>`).join("")}</div>`;
    if (!rows) return `<div class="hq-bar">${seg}</div>${Loading.line("Reading the issues…")}`;
    const now = Date.now() / 1000;
    const list = rows.map(i => {
      const snoozed = i.snoozed_until > now, open = i.status === "open";
      return `<article class="hq-issue ${open ? i.severity : "done"} ${i.needs_admin && open ? "needs" : ""}" id="hq-issue-${i.id}" data-issue="${i.id}">
        <header>${open ? sev(i.severity) : `<span class="hq-sev ok">${icon("check")}Resolved</span>`}
          <h3>${esc(i.title)}</h3>
          <span class="hq-issue-meta">${av(people()[i.agent], "xs")}${who(i.agent)} · first seen ${ago(i.first_seen)} · ${plural(i.seen, "patrol")}${snoozed ? ` · <span class="hq-chip t-off">${icon("clock")}snoozed until ${clock(i.snoozed_until)}</span>` : ""}${i.needs_admin && open ? ` · <span class="hq-chip t-warn">needs you</span>` : ""}</span></header>
        <dl>
          <dt>What the checks saw</dt><dd>${esc(i.detail)}</dd>
          ${i.cause ? `<dt>Diagnosis${i.verdict && i.verdict !== "confirmed" ? ` <span class="hq-chip t-off">${i.verdict === "false_alarm" ? "false alarm" : "already fine"}</span>` : ""}</dt><dd>${esc(i.cause)}</dd>` : open && !i.investigated ? `<dt>Diagnosis</dt><dd class="faint">Not investigated yet${d.model ? "" : ": no model is connected"}.</dd>` : ""}
          ${i.recommendation ? `<dt>Recommendation</dt><dd>${esc(i.recommendation)}</dd>` : ""}
          ${!open ? `<dt>Resolution</dt><dd>${esc(i.resolution || "")} <span class="faint">${ago(i.resolved)}</span></dd>` : ""}
        </dl>
        ${i.fixes.length ? `<ul class="hq-fixes">${i.fixes.map(f => `<li>${chip(FIX[f.status] || ["off", f.status])}<b>${esc(f.label)}</b>
          <span class="faint">${f.lead_note ? `${esc(f.lead_decision === "approve" ? "backed" : f.lead_decision === "reject" ? "rejected" : "escalated")}: ${esc(f.lead_note)}` : ""}${f.decided_by ? ` · by ${esc(f.decided_by)}` : ""}${f.result ? ` · ${esc(f.result)}` : ""}${f.verified === "helped" ? " · it worked" : f.verified === "no_effect" ? " · it didn't help" : ""}</span>
          ${f.status === "awaiting" ? `<span class="row" data-fix="${f.id}"><button type="button" class="btn sm" data-hq="reject">Reject</button><button type="button" class="btn sm primary ${f.danger ? "danger" : ""}" data-hq="approve">Approve</button></span>` : ""}</li>`).join("")}</ul>` : ""}
        ${open ? `<footer><button type="button" class="btn sm" data-hq="${snoozed ? "wake" : "snooze"}">${icon("clock")}${snoozed ? "Wake it up" : "Snooze 24 h"}</button></footer>` : ""}
      </article>`;
    }).join("");
    return `<div class="hq-bar">${seg}<span class="faint small">${filter === "open" ? "Open issues stay until a check stops finding them. Snoozing one keeps it out of reports and investigations." : ""}</span></div>
      ${list || `<div class="empty">${filter === "open" ? `${icon("check")} No open issues. Every check passed on the last patrol.` : "No issues yet."}</div>`}`;
  }

  // ---------- reports ----------
  function reportsTab() {
    if (!reports) return Loading.line("Reading the reports…");
    if (!reports.reports.length) return `<div class="empty">No reports yet: the Team Boss writes one every hour, the first with the first patrol.</div>`;
    let lastDay = "";
    return `<ol class="hq-reports">${reports.reports.map(r => {
      const head = day(r.ts) !== lastDay ? `<li class="hq-day">${day(r.ts)}</li>` : ""; lastDay = day(r.ts);
      const [cls] = TONE[r.status], st = r.stats || {}, open = report?.id === r.id;
      return `${head}<li class="hq-rep t-${cls} ${open ? "open" : ""}" data-report="${r.id}"><button type="button" class="hq-rep-row" aria-expanded="${open}">
        <time>${clock(r.ts)}</time><span class="ci ci-${cls}"></span><b>${esc(r.headline)}</b>
        <span class="hq-rep-n faint">${st.open ? `${st.open} open` : ""}${st.fixed ? ` · ${st.fixed} fixed` : ""}${st.waiting ? ` · ${st.waiting} waiting` : ""}</span>${icon(open ? "up" : "down")}</button>
        ${open ? reportBody(report) : ""}</li>`;
    }).join("")}</ol>${reports.reports.length >= 48 ? `<div class="row center"><button type="button" class="btn" data-hq="more">Older reports</button></div>` : ""}`;
  }
  function reportBody(r) {
    if (!r.issues) return Loading.line("Opening the report…");
    const st = r.stats;
    return `<div class="hq-rep-body">
      ${r.summary ? `<p>${esc(r.summary)}</p>` : ""}
      ${r.actions.length ? `<div class="hq-todo"><div class="hq-todo-h">${icon("hand")}What needed you</div><ol>${r.actions.map(a => `<li>${esc(a)}</li>`).join("")}</ol></div>` : ""}
      <p class="faint small">${clock(r.since)}–${clock(r.ts)} · ${plural(st.patrols, "patrol")} · ${plural(st.agents, "field agent")} on duty · ${short(st.tokens)} tokens${r.author === "boss" ? ` · written by the Team Boss on ${esc((r.model || "").split(":").pop())}` : " · written from the numbers"}</p>
      ${r.issues.length ? `<h4>Issues in this hour</h4><ul class="hq-mini">${r.issues.map(i => `<li>${i.status === "open" ? sev(i.severity) : `<span class="hq-sev ok">${icon("check")}Resolved</span>`} ${esc(i.title)} <span class="faint">${who(i.agent)}</span></li>`).join("")}</ul>` : ""}
      ${r.fixes.length ? `<h4>Fixes</h4><ul class="hq-mini">${r.fixes.map(f => `<li>${chip(FIX[f.status] || ["off", f.status])} ${esc(f.label)} <span class="faint">${f.decided_by ? `by ${esc(f.decided_by)}` : ""}</span></li>`).join("")}</ul>` : ""}
      ${r.events.length ? `<details><summary>What the agents did (${r.events.length})</summary>${feed(r.events)}</details>` : ""}</div>`;
  }

  // ---------- roster (the Agents Manager) ----------
  function rosterTab() {
    if (!roster) return Loading.line("The Agents Manager is reading the roster…");
    const mgr = people().manager, max = Math.max(1, ...roster.usage.map(u => u.month));
    const SRC = { chat: "Agent chats", hq: "Agent HQ", team: "Project team", study: "Study", practice: "Study practice", workspace: "Workspace", board: "Whiteboard", profile: "My profile", lab: "Study Lab", mining: "My subnets", writing: "Writing help", tech: "Technology Research" };
    const hq = roster.hq.map(a => `<tr data-agent="${a.id}"><td>${av(a, "xs")} <b>${esc(a.name)}</b> <span class="faint">${esc(a.title)}</span></td>
      <td>${a.tier === "boss" ? "Boss" : a.tier === "manager" ? "Manager" : a.tier === "leader" ? `Lead · ${esc(a.team === "infra" ? "Infrastructure" : "Services")}` : `Field · ${esc(a.team === "infra" ? "Infrastructure" : "Services")}`}</td>
      <td><span class="ci ci-${stateOf(a)[0]}"></span> ${stateOf(a)[1]}</td>
      <td class="r num">${a.last_run ? ago(a.last_run) : "–"}</td><td class="r num">${a.open || "–"}</td><td class="r num">${a.fixed_day || "–"}</td><td class="r num">${short(a.tokens_day)}</td>
      <td class="r">${a.tier ? "" : `<label class="switch" title="${a.on ? "On duty" : "Off duty"}"><input type="checkbox" data-hq-duty="${a.id}" ${a.on ? "checked" : ""} aria-label="${esc(a.name)} on duty"><span></span></label>`}</td></tr>`).join("");
    const builtins = roster.builtins.map(b => `<li>${av(b, "xs")}<b>${esc(b.name)}</b><span class="faint">${esc(b.role)}</span><span class="r faint">${plural(b.chats, "chat")}${b.last_activity ? ` · ${ago(b.last_activity)}` : ""}</span></li>`).join("");
    const custom = roster.custom.map(a => `<tr><td>${av(a, "xs")} <b>${esc(a.name)}</b> <span class="faint">${esc(a.role || "")}</span></td><td>${esc(a.owner || "–")}</td>
      <td>${a.kind === "study" ? "Study" : "Subnet data"}${a.in_directory ? ` <span class="badge new">directory</span>` : ""}${a.shared ? ` <span class="faint">· shared with ${a.shared}</span>` : ""}</td>
      <td class="r num">${short(a.tokens_today)}</td><td class="r num">${short(a.tokens_month)}</td><td class="r num">${a.last_activity ? ago(a.last_activity) : "–"}</td>
      <td class="r"><button type="button" class="btn sm" data-hq-status="${a.id}" data-to="${a.status === "paused" ? "live" : "paused"}">${icon(a.status === "paused" ? "play" : "stop")}${a.status === "paused" ? "Resume" : "Pause"}</button></td></tr>`).join("");
    return `<div class="hq-mgr">${av(mgr, "")}<div><b>${esc(mgr.name)}, ${esc(mgr.title)}</b><p class="faint">${esc(mgr.job)}</p></div></div>
      <section class="hq-sec"><h2 class="hq-h">HQ staff</h2><div class="tablewrap"><table class="hq-table"><thead><tr><th>Agent</th><th>Role</th><th>State</th><th class="r">Last check</th><th class="r">Open</th><th class="r">Fixes today</th><th class="r">Tokens today</th><th class="r">On duty</th></tr></thead><tbody>${hq}</tbody></table></div></section>
      <div class="hq-two">
        <section class="hq-sec"><h2 class="hq-h">Model use on this server <span class="faint">last 30 days</span></h2>${roster.usage.length ? `<ul class="hq-bars">${roster.usage.map(u => `<li><span>${esc(SRC[u.source] || u.source)}</span><i style="--w:${(u.month / max * 100).toFixed(1)}%"></i><b>${short(u.month)}</b><span class="faint">${u.today ? `${short(u.today)} today` : ""}</span></li>`).join("")}</ul>` : `<div class="empty small">No model calls yet.</div>`}</section>
        <section class="hq-sec"><h2 class="hq-h">Built-in agents</h2><ul class="hq-list">${builtins || `<li class="faint">None</li>`}</ul></section>
      </div>
      <section class="hq-sec"><h2 class="hq-h">Members' agents <span class="faint">${plural(roster.custom.length, "agent")}, made in the agent hub</span></h2>
        ${custom ? `<div class="tablewrap"><table class="hq-table"><thead><tr><th>Agent</th><th>Owner</th><th>Kind</th><th class="r">Tokens today</th><th class="r">30 days</th><th class="r">Last used</th><th></th></tr></thead><tbody>${custom}</tbody></table></div>` : `<div class="empty small">Nobody has made an agent yet.</div>`}
        <p class="faint small">Pausing an agent stops anyone from chatting with it until it's resumed; its owner can resume it too. Every change is in the audit log.</p></section>`;
  }

  // ---------- settings ----------
  function settingsTab() {
    const s = d.settings;
    const opts = models ? [`<option value="auto" ${s.model === "auto" ? "selected" : ""}>Auto (the default model${models.default ? `: ${esc(models.default.split(":").pop())}` : ""})</option>`,
      ...models.providers.filter(p => p.models.length).map(p => `<optgroup label="${esc(p.label)}">${p.models.map(m => `<option value="${esc(m.id)}" ${s.model === m.id ? "selected" : ""}>${esc(m.label || m.id)}</option>`).join("")}</optgroup>`)].join("")
      : `<option>${esc(s.model)}</option>`;
    if (!models) api("/api/agents/models").then(m => { models = m; if (tab === "settings") render(); }).catch(() => { models = { providers: [], default: null }; });
    return `<form class="hq-settings" autocomplete="off">
      <section class="hq-sec"><label class="toggle-row"><span><b>On duty</b><small class="faint">Patrols every ${s.patrol_minutes} minutes and a report every hour. Off, nothing runs and nothing is spent.</small></span>
        <span class="switch"><input type="checkbox" name="on" ${s.on ? "checked" : ""}><span></span></span></label></section>
      <section class="hq-sec"><h2 class="hq-h">How much HQ may fix on its own</h2><div class="hq-modes">${Object.entries(AUTONOMY).map(([k, [ic, l, t]]) =>
        `<label class="hq-modecard ${s.autonomy === k ? "on" : ""}"><input type="radio" name="autonomy" value="${k}" ${s.autonomy === k ? "checked" : ""}>${icon(ic)}<b>${l}</b><span>${t}</span>${k === "auto" ? `<small class="faint">${icon("lock")}Asks you to confirm it's you</small>` : ""}</label>`).join("")}</div>
        <p class="faint small">Whatever you pick, AXoR itself is never restarted from here, every fix is checked again before it runs, and every change is in the audit log (fixes HQ ran on its own as "HQ · Quinn" or "HQ · Rowan").</p></section>
      <section class="hq-sec hq-fields">
        <label class="in"><span>Model</span><select name="model">${opts}</select><small class="faint">Investigations, reviews and reports. A smaller model is plenty for most issues.</small></label>
        <label class="in"><span>Token budget per hour</span><input name="budget" type="number" min="0" step="5000" value="${s.budget}"><small class="faint">${short(d.hour_tokens)} used in the last hour. 0 means no limit. Checks never use tokens; only investigating, reviewing and reporting do.</small></label>
      </section>
      <section class="hq-sec"><label class="toggle-row"><span><b>Push notifications</b><small class="faint">To administrators' devices: critical issues right away, fixes waiting for you, and a report when the status changes or turns red. Quiet hours count, except for critical issues.</small></span>
        <span class="switch"><input type="checkbox" name="notify" ${s.notify ? "checked" : ""}><span></span></span></label></section>
      <div class="row end"><button type="submit" class="btn primary">${icon("check")}Save</button></div>
    </form>`;
  }
  async function save(f) {
    const b = { on: f.elements.on.checked, autonomy: f.elements.autonomy.value, budget: +f.elements.budget.value || 0, notify: f.elements.notify.checked };
    if (models && f.elements.model.value !== d.settings.model) b.model = f.elements.model.value;
    const go = () => Admin.withSudo(() => api("/api/hq/settings", { method: "POST", body: b }));
    if (b.autonomy === "auto" && d.settings.autonomy !== "auto") {
      const ok = await UI.confirm({ title: "Let HQ fix safe issues on its own?", icon: "zap", ok: "Turn it on", danger: false,
        body: "A lead may then restart a failing deployment, app or function, or recycle a crashed pod, without asking you: at most 3 fixes a patrol and once per target in 6 hours. Everything else still waits for you.", run: go });
      if (!ok) return;
    } else await go();
    d.settings = { ...d.settings, ...b }; Auth.toast("Agent HQ settings saved");
    await load();
  }

  // ---------- an agent's card ----------
  async function agent(id) {
    const a = people()[id];
    if (!a) return;
    let dlg = $("#hq-agent");
    if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "hq-agent"; dlg.className = "modal hq-dlg"; document.body.append(dlg); dlg.addEventListener("click", e => { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); }); }
    const s = stateOf(a);
    const mine = d.open.filter(i => i.agent === id || (a.tier === "leader" && i.team === a.team));
    dlg.innerHTML = `<div class="hq-dlg-in"><button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>
      <div class="hq-dlg-head">${av(a, "lg")}<div><h3>${esc(a.name)}</h3><div class="faint">${esc(a.title)}${a.team ? ` · ${a.team === "infra" ? "Infrastructure" : "Services"} team` : ""}</div>
        <div class="hq-node-state"><span class="ci ci-${s[0]}"></span>${s[1]}${a.note && a.status !== "ok" ? ` <span class="faint">· ${esc(a.note)}</span>` : ""}</div></div></div>
      <p>${esc(a.job || `Watches ${a.watch}.`)}</p>
      ${a.checks ? `<h4>Checks every patrol</h4><ul class="hq-checks">${a.checks.map(c => `<li>${icon("check")}${esc(c)}</li>`).join("")}</ul>` : ""}
      <div class="hq-dlg-stats"><span><b>${a.open || 0}</b> open</span><span><b>${a.fixed_day || 0}</b> fixed today</span><span><b>${short(a.tokens_day)}</b> tokens today</span>${a.last_run ? `<span><b>${ago(a.last_run)}</b> last check</span>` : ""}</div>
      ${mine.length ? `<h4>Open issues</h4><ul class="hq-mini">${mine.map(i => `<li>${sev(i.severity)} <a href="#hq" data-hq-issue="${i.id}">${esc(i.title)}</a></li>`).join("")}</ul>` : ""}
      <h4>Recent work</h4><div class="hq-dlg-feed">${Loading.line("Reading…")}</div>
      ${a.tier ? "" : `<label class="toggle-row"><span><b>On duty</b><small class="faint">Off, its checks stop and its open issues close.</small></span><span class="switch"><input type="checkbox" data-hq-duty="${a.id}" ${a.on ? "checked" : ""}><span></span></span></label>`}</div>`;
    dlg.showModal();
    try { const r = await api(`/api/hq/events?agent=${encodeURIComponent(id)}`); $(".hq-dlg-feed", dlg).innerHTML = feed(r.events.slice(0, 15)); $$("time", dlg).forEach(t => { t.textContent = ago(+t.dataset.ts); }); }
    catch (e) { $(".hq-dlg-feed", dlg).innerHTML = `<div class="empty small">${esc(e.message)}</div>`; }
  }

  // ---------- actions ----------
  async function decide(id, approve, btn) {
    const f = [...d.waiting, ...(issues?.issues || []).flatMap(i => i.fixes)].find(x => x.id === id);
    const go = async () => {
      const r = await Admin.withSudo(() => api(`/api/hq/fixes/${id}`, { method: "POST", body: { approve } }));
      if (r.status === "failed") throw new Error(r.message);
      Auth.toast(approve ? `Done: ${f?.label || "fix"}` : "Rejected");
    };
    try {
      if (approve && f?.danger) await UI.confirm({ title: `${f.label}?`, body: "This rolls back or stops something. The next patrol checks whether it helped.", ok: "Approve", icon: "hand", run: go });
      else { btn.classList.add("loading"); btn.disabled = true; await go(); }
    } catch (e) { err(e); }
    issues = null; await load().catch(() => {});
    if (tab === "issues") { issues = await api(`/api/hq/issues?status=${filter}`).catch(() => null); render(); }
  }

  function wire() {
    if (wired) return; wired = true;
    root().addEventListener("click", async e => {
      const t = e.target;
      const tb = t.closest("[data-hqtab]");
      if (tb) {
        tab = tb.dataset.hqtab; render();
        if (tab === "issues") { issues = await api(`/api/hq/issues?status=${filter}`).catch(e2 => ({ issues: [], error: err(e2) })); render(); }
        if (tab === "reports") { reports = await api("/api/hq/reports").catch(() => ({ reports: [] })); render(); }
        if (tab === "roster") { roster = await api("/api/hq/roster").catch(() => ({ hq: [], builtins: [], custom: [], usage: [] })); render(); }
        return;
      }
      const fl = t.closest("[data-hqfilter]");
      if (fl) { filter = fl.dataset.hqfilter; issues = null; render(); issues = await api(`/api/hq/issues?status=${filter}`); return render(); }
      const ag = t.closest("[data-agent]");
      if (ag && !t.closest("input, label.switch")) return agent(ag.dataset.agent);
      const iss = t.closest("[data-hq-issue]");
      if (iss) { e.preventDefault(); return showIssue(+iss.dataset.hqIssue); }
      const rep = t.closest(".hq-rep-row");
      if (rep) {
        const id = +rep.closest("[data-report]").dataset.report;
        if (report?.id === id) { report = null; return render(); }
        report = { id }; render();
        report = await api(`/api/hq/reports/${id}`).catch(e2 => (err(e2), null)); return render();
      }
      const st = t.closest("[data-hq-status]");
      if (st) {
        st.disabled = true;
        try { await api(`/api/hq/roster/${st.dataset.hqStatus}`, { method: "POST", body: { status: st.dataset.to } }); Auth.toast(st.dataset.to === "paused" ? "Agent paused" : "Agent resumed"); }
        catch (e2) { err(e2); }
        roster = await api("/api/hq/roster").catch(() => roster); return render();
      }
      const b = t.closest("[data-hq]");
      if (!b) return;
      const act = b.dataset.hq;
      if (act === "run") {
        b.disabled = true;
        try { await api("/api/hq/run", { method: "POST" }); Auth.toast("Patrol started"); } catch (e2) { err(e2); }
        await load().catch(() => {}); return schedule();
      }
      if (act === "reports") { tab = "reports"; reports = null; render(); reports = await api("/api/hq/reports").catch(() => ({ reports: [] })); return render(); }
      if (act === "more") {
        const older = await api(`/api/hq/reports?before=${reports.reports.at(-1).id}`).catch(() => ({ reports: [] }));
        reports.reports.push(...older.reports); return render();
      }
      if (act === "approve" || act === "reject") return decide(+b.closest("[data-fix]").dataset.fix, act === "approve", b);
      if (act === "snooze" || act === "wake") {
        const id = +b.closest("[data-issue]").dataset.issue;
        try { await api(`/api/hq/issues/${id}/snooze`, { method: "POST", body: { hours: act === "snooze" ? 24 : 0 } }); Auth.toast(act === "snooze" ? "Snoozed for 24 hours" : "Woken up"); }
        catch (e2) { err(e2); }
        issues = await api(`/api/hq/issues?status=${filter}`).catch(() => issues); await load().catch(() => {});
      }
    });
    root().addEventListener("change", e => { if (e.target.name === "autonomy") $$(".hq-modecard", root()).forEach(c => c.classList.toggle("on", c.contains(e.target))); });
    root().addEventListener("submit", e => { e.preventDefault(); save(e.target).catch(err); });
    document.addEventListener("change", async e => {  // on-duty switches: the roster table and an agent's card
      const sw = e.target.closest?.("[data-hq-duty]");
      if (!sw) return;
      try { await api(`/api/hq/agents/${sw.dataset.hqDuty}`, { method: "POST", body: { on: sw.checked } }); Auth.toast(sw.checked ? "Back on duty" : "Off duty"); }
      catch (e2) { sw.checked = !sw.checked; err(e2); }
      roster = tab === "roster" ? await api("/api/hq/roster").catch(() => roster) : roster; await load().catch(() => {});
    });
  }

  async function showIssue(id) {
    $("#hq-agent")?.close();
    const i = d.open.find(x => x.id === id);
    tab = "issues"; filter = i ? "open" : "all"; issues = null; render();
    issues = await api(`/api/hq/issues?status=${filter}`).catch(() => ({ issues: [] })); render();
    const el = $(`#hq-issue-${id}`);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); }
  }

  // ---------- the sidebar's count: fixes waiting for you and critical issues ----------
  function badge(n) { const c = $("#c-hq"); if (c) c.textContent = n || ""; }
  let polling = false;
  function init() {
    if (polling || Auth.me()?.role !== "admin" || !$("#c-hq")) return;
    polling = true;
    const tick = () => api("/api/hq/badge").then(b => badge(b.waiting + b.critical)).catch(() => {});
    tick(); setInterval(() => { if (Auth.me()?.role === "admin" && document.visibilityState === "visible") tick(); }, 60000);
  }

  return { open, init };
})();
