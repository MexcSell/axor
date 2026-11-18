/* Workforce (workforce.py): a company of AI agents. Seven tabs:
   Missions (the list, and one mission: its steps and token meter, the plan waiting for approval, the report and how the
   evaluator scored it against its criteria, the work by team and assignment, debates between authors, the shared blackboard, proposed actions,
   recalled memories, the live feed and every run's trace with its routing decision), Org (the CEO over six teams, live
   state, hiring; an agent's tools, instructions and versions), Memory (what the workforce remembers and how useful each
   memory proved), Scoreboard (pass rates, recovery, cost per success, failure categories, per agent, team and model),
   Improvement (proposed instruction changes, their blind tests and promotion), Benchmarks (the workforce against a single
   agent and other arms) and Settings (the model pool and router, mission defaults, self-improvement).
   While the page is open it follows the workforce over server-sent events. */
const Workforce = (() => {
  let home = null, tab = null, mid = null, d = null, wired = false, es = null, timer = null, clockTimer = null;
  let memory = null, metrics = null, imps = null, benches = null, settings = null, models = null;
  const benchRuns = {};
  let memKind = "", memQ = "", boardKind = "all";
  const root = () => $("#workforce");
  const shown = () => !$("#view-workforce").hidden;
  const err = e => e && e.message !== "cancelled" && Auth.toast(e.message);
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 1)}k` : fmtNum(n || 0, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const pctf = x => x == null ? "–" : `${Math.round(x * 100)}%`;
  const dur = s => s == null ? "–" : s < 1 ? `${Math.round(s * 1000)} ms` : s < 90 ? `${fmtNum(s, s < 10 ? 1 : 0)} s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  const ENGINE = { key: "memory", name: "Memory engine", title: "Shared infrastructure", icon: "layers", color: "slate" };
  const agent = k => (home?.agents || []).find(a => a.key === k) || (k === "memory" ? ENGINE : { key: k, name: k, title: "", icon: "bot", color: "slate" });
  const team = id => (home?.teams || []).find(t => t.id === id) || { id, name: id === "exec" ? "Executive" : id, icon: "star", color: "violet", job: "" };
  const av = (a, size = "sm") => `<span class="av ${size} c-${esc(a.color)}" aria-hidden="true">${icon(a.icon)}</span>`;
  const chip = (tone, text, ic) => `<span class="wf-chip t-${tone}">${ic ? icon(ic) : ""}${esc(text)}</span>`;
  const MSTATUS = { running: ["run", "Running", "play"], waiting: ["warn", "Waiting for you", "hand"], done: ["ok", "Done", "check"], failed: ["bad", "Failed", "alert"], cancelled: ["off", "Cancelled", "stop"] };
  const VERDICT = { pass: ["ok", "Pass", "check"], fail: ["bad", "Fail", "close"] };
  const STANCE = { hold: ["warn", "Holds"], amend: ["run", "Amends"], agree: ["ok", "Agrees"] };
  const DSTATUS = { open: ["run", "Debating", "chat"], consensus: ["ok", "Consensus", "check"], split: ["warn", "Split: your call", "hand"], skipped: ["off", "Not held", "stop"] };
  const ASTATUS = { queued: ["wait", "Queued"], running: ["run", "Working"], done: ["ok", "Filed"], failed: ["bad", "Failed"], skipped: ["off", "Skipped"] };
  const BSTATUS = { unverified: ["wait", "Unverified"], verified: ["ok", "Verified"], disputed: ["bad", "Disputed"], unverifiable: ["warn", "Can't verify"], open: ["warn", "Open"], answered: ["ok", "Answered"] };
  const RISK = { low: "ok", medium: "warn", high: "bad" };
  const IMP = { proposed: ["wait", "Proposed"], testing: ["run", "Testing"], better: ["ok", "Measured better"], not_better: ["warn", "Not better"], failed: ["bad", "Test failed"], promoted: ["ok", "Promoted"], rejected: ["off", "Rejected"] };
  const ROLE = { critic: "Red team", evaluator: "Independent evaluator", checker: "Fact checks", improver: "Improves agents" };
  const SOURCE = { template: "Starting version", user: "Edited", improvement: "Tested improvement", rollback: "Restored" };
  const KIND = { semantic: "Fact", procedural: "Procedure", strategy: "Strategy", episodic: "Episode" };
  const STEPS = [["recall", "Recall", "layers"], ["plan", "Plan", "target"], ["delegate", "Delegate", "users"], ["execute", "Execute", "zap"], ["critique", "Red team", "flag"],
    ["factcheck", "Fact check", "check"], ["debate", "Debate", "chat"], ["evaluate", "Evaluate", "chart"], ["rework", "Rework", "cycle"], ["synthesize", "Report", "doc"], ["learn", "Learn", "sprout"]];
  const STEP = Object.fromEntries([["queued", "Queued"], ...STEPS.map(s => [s[0], s[1]]), ["done", "Done"]]);
  const RUNSTEP = { plan: "planned", delegate: "delegated", execute: "worked", rework: "reworked", solo: "worked alone", critique: "challenged", respond: "answered a challenge",
    factcheck: "checked facts", debate: "looked for disagreements", argue: "argued in a debate", evaluate: "scored", synthesize: "wrote the report", learn: "consolidated memory", improve: "diagnosed failures", trial: "ran a test trial", judge: "scored blind" };
  const CAT = { none: "None", unsupported_claim: "Unsupported claim", wrong_data: "Wrong data", incomplete: "Incomplete", off_task: "Off task", ignored_challenge: "Ignored a challenge",
    no_evidence: "No evidence", unsafe: "Unsafe" };
  const KIND_ICON = { phase: "play", plan: "target", wait: "hand", decision: "hand", delegate: "users", start: "zap", tool: "search", denied: "ban", done: "check", fail: "alert",
    warn: "info", propose: "wrench", challenge: "flag", respond: "chat", verify: "check", debate: "chat", argue: "chat", eval: "chart", memory: "layers", improve: "sprout", info: "info" };
  const WEIGHTS = { quality: ["Quality first", "The strongest model unless it fails often; cost barely counts."], balanced: ["Balanced", "Pays for quality where it shows in the scores."],
    thrifty: ["Thrifty", "The cheapest model that holds up; cost counts most."] };
  const MODES = { off: ["Off", "No diagnoses, no proposals."], propose: ["Propose", "After a failure, Ivo proposes a new version; you start the test."],
    test: ["Propose and test", "Each proposal is tested right away (one trial each). Promotion still waits for you."] };
  const EXAMPLES = ["Find the three best subnets to mine on one RTX 4090 and plan the first 30 days",
    "Audit the risks of registering on the cheapest open subnet this week",
    "Compare the five biggest subnets by emissions and say which ones newcomers can win",
    "Review my repositories' CI and propose a safer release process"];

  // ---------- loading ----------
  async function open() {
    wire();
    if (tab === null) { tab = store.get("wf.tab", "missions"); mid = store.get("wf.mid", null); }
    if (!home) root().innerHTML = `<h1 class="page">Workforce</h1>${Loading.line("Calling the workforce in…")}`;
    try { home = await api("/api/workforce"); }
    catch (e) { root().innerHTML = `<h1 class="page">Workforce</h1><div class="empty">${esc(e.message)}</div>`; return; }
    if (mid == null) mid = home.missions[0]?.id ?? null;
    if (mid && (!d || d.mission.id !== mid)) {
      try { d = await api(`/api/workforce/missions/${mid}`); } catch { mid = home.missions[0]?.id ?? null; d = mid ? await api(`/api/workforce/missions/${mid}`).catch(() => null) : null; }
    }
    render(); await loadTab(); follow();
    clearInterval(clockTimer); clockTimer = setInterval(() => { if (shown()) times(); }, 30000);
  }
  function stop() { es?.close(); es = null; clearTimeout(timer); clearInterval(clockTimer); }
  function follow() {
    es?.close(); es = null; clearTimeout(timer);
    if (!shown()) return;
    es = new EventSource(`/api/workforce/stream${mid ? `?mission=${mid}` : ""}`);
    es.addEventListener("state", e => {
      const s = JSON.parse(e.data);
      const was = home.missions.map(m => `${m.id}:${m.status}`).join();
      Object.assign(home, { missions: s.missions, pending: s.pending, live: s.live });
      if (s.state && s.state.mission.id === mid) {
        const seen = new Set((d?.events || []).map(x => x.id)), fresh = s.state.events.filter(x => !seen.has(x.id));
        d = { ...s.state, events: [...(d?.events || []), ...fresh].slice(-300) };
        if (fresh.some(x => ["eval", "memory", "improve", "phase"].includes(x.kind))) metrics = imps = memory = null;
      }
      if (was !== home.missions.map(m => `${m.id}:${m.status}`).join()) metrics = null;
      live();
    });
    es.addEventListener("gone", () => { mid = null; d = null; store.set("wf.mid", null); open(); });
    es.addEventListener("auth", stop);
    es.onerror = () => { es?.close(); es = null; clearTimeout(timer); timer = setTimeout(() => { if (shown()) follow(); }, 5000); };
  }
  async function loadTab() {
    try {
      if (tab === "memory" && !memory) memory = await api(`/api/workforce/memory`);
      if (tab === "scores" && !metrics) metrics = await api("/api/workforce/metrics");
      if (tab === "improve" && !imps) imps = await api("/api/workforce/improvements");
      if (tab === "bench" && !benches) benches = await api("/api/workforce/benchmarks");
      if (tab === "settings" && !settings) { settings = await api("/api/workforce/settings"); if (!models) loadModels(); }
    } catch (e) { err(e); }
    render();
  }
  async function refresh(all) {
    try {
      home = await api("/api/workforce");
      if (mid) d = await api(`/api/workforce/missions/${mid}`).catch(() => d);
      if (all) { memory = metrics = imps = benches = null; }
    } catch (e) { err(e); }
    render(); loadTab();
  }
  async function select(id) {
    mid = id; store.set("wf.mid", id); d = null; boardKind = "all";
    if (tab !== "missions") { tab = "missions"; store.set("wf.tab", tab); }
    render();
    try { d = await api(`/api/workforce/missions/${id}`); } catch (e) { err(e); }
    render(); follow();
  }
  function setTab(k) { tab = k; store.set("wf.tab", k); render(); loadTab(); }

  // ---------- frame ----------
  // replaces el's HTML only when it changed, keeping what you typed in [data-keep] forms
  function put(el, html) {
    if (!el || el.dataset.html === html) return;
    const typed = $$("[data-keep] input:not([type=checkbox]), [data-keep] textarea, [data-keep] select", el).filter(x => x.dataset.dirty)
      .map(x => ({ sel: `[data-keep="${x.closest("[data-keep]").dataset.keep}"] [name="${x.name}"]`, value: x.value, focus: document.activeElement === x, a: x.selectionStart, b: x.selectionEnd }));
    el.innerHTML = html; el.dataset.html = html;
    for (const t of typed) {
      const x = $(t.sel, el); if (!x) continue;
      x.value = t.value; x.dataset.dirty = "1";
      if (t.focus) { x.focus(); try { x.setSelectionRange(t.a, t.b); } catch { /* selects have no selection */ } }
    }
  }
  function render() {
    if (!home) return;
    if (!$(".wf-body", root())) root().innerHTML = `<div class="wf-top"><div><h1 class="page">Workforce</h1>
        <p class="lead">A company of AI agents. A CEO plans each mission and staffs only the teams it needs, leads delegate, specialists work in their own context, a red teamer challenges the work and an independent evaluator scores it. The workforce remembers what it verified, routes calls across your models and proposes tested improvements to itself. You approve what matters.</p></div>
        <div class="wf-actions"></div></div><div class="wf-tabs-wrap"></div><div class="wf-body"></div>`;
    put($(".wf-actions", root()), topActions());
    put($(".wf-tabs-wrap", root()), tabs());
    const body = $(".wf-body", root());
    if (tab === "missions") {
      if (!$(".wf-missions", body)) { body.innerHTML = `<div class="wf-missions"><aside class="wf-list" aria-label="Missions"></aside><section class="wf-detail"></section></div>`; delete body.dataset.html; }
      put($(".wf-list", body), listHtml()); put($(".wf-detail", body), detailHtml());
    } else put(body, { org, memory: memoryTab, scores, improve, bench: benchTab, settings: settingsTab }[tab]?.() || "");
    times();
  }
  // a stream update: the tabs that follow the workforce live, and the counts everywhere
  function live() {
    if (!home || !shown()) return;
    if (["missions", "org"].includes(tab)) render();
    else { put($(".wf-actions", root()), topActions()); put($(".wf-tabs-wrap", root()), tabs()); }
    badge();
  }
  function times() { $$("time[data-ts]", root()).forEach(t => { t.textContent = ago(+t.dataset.ts); }); }
  function tabs() {
    const p = home.pending;
    return `<div class="seg wf-tabs" role="tablist">${[["missions", "Missions", "target", p.plans + p.actions], ["org", "Org", "group"], ["memory", "Memory", "layers"],
      ["scores", "Scoreboard", "chart"], ["improve", "Improvement", "sprout", p.improvements], ["bench", "Benchmarks", "trophy"], ["settings", "Settings", "gear"]]
      .map(([k, l, ic, n]) => `<button type="button" role="tab" data-wftab="${k}" aria-pressed="${tab === k}">${icon(ic)}${l}${n ? `<span class="wf-n">${n}</span>` : ""}</button>`).join("")}</div>`;
  }
  function topActions() {
    const working = Object.keys(home.live).length;
    return `${working ? `<span class="wf-working">${icon("zap")}${plural(working, "agent")} at work</span>` : ""}
      <button type="button" class="btn primary" data-wf="new" ${home.model_ready ? "" : "disabled title=\"Connect a model in Agents → Models first\""}>${icon("plus")}New mission</button>`;
  }

  // ---------- missions ----------
  function listHtml() {
    const p = home.pending;
    return `${p.actions ? `<button type="button" class="wf-waiting" data-wf="approvals">${icon("hand")}<span><b>${plural(p.actions, "proposal")} wait${p.actions === 1 ? "s" : ""} for you</b><small>Approve or reject what agents want done</small></span></button>` : ""}
      ${home.missions.length ? `<ol class="wf-mlist">${home.missions.map(m => {
        const [tone] = MSTATUS[m.status] || ["wait"];
        const what = m.status === "running" ? STEP[m.step] || m.step : m.status === "waiting" ? "Plan waits for you" : m.score != null ? `${m.score}/100 · ${m.verdict}` : MSTATUS[m.status]?.[1] || m.status;
        return `<li><button type="button" class="wf-mrow ${m.id === mid ? "on" : ""}" data-mission="${m.id}" aria-pressed="${m.id === mid}">
          <span class="wf-dot t-${tone}" aria-hidden="true"></span><span class="wf-mrow-t">${esc(m.title)}</span>
          <span class="wf-mrow-m">${esc(what)}${m.mode === "solo" ? " · solo" : ""} · ${short(m.tokens)} tokens · <time data-ts="${m.created}">${ago(m.created)}</time></span></button></li>`; }).join("")}</ol>`
        : `<p class="faint small wf-pad">No missions yet.</p>`}`;
  }
  function detailHtml() {
    if (!mid) return welcome();
    if (!d || d.mission.id !== mid) return `<div class="wf-card">${Loading.line("Opening the mission…")}</div>`;
    const m = d.mission;
    return [header(m), m.status === "waiting" ? planReview(m) : "", m.headline || m.report ? report(m) : "",
      `<div class="wf-grid">${work(m)}<div class="wf-col">${actionsCard()}${debatesCard(m)}${boardCard()}${recallCard(m)}</div></div>`, activity()].join("");
  }
  function welcome() {
    const ceo = agent("ceo");
    return `<div class="wf-card wf-welcome"><div><h2>Give the workforce its first mission</h2>
        <p>Describe a goal. ${esc(ceo.name)}, the CEO, plans it and staffs the teams it needs; leads split the work; specialists do it with read-only tools and post what they find on a shared blackboard. ${esc(agent("red-teamer").name)} challenges the claims, ${esc(agent("fact-checker").name)} re-checks the facts, and ${esc(agent("chief-evaluator").name)} scores everything independently before you read the report.</p>
        <p>Agents never change anything: what has side effects becomes a proposal you approve or reject.</p>
        <button type="button" class="btn primary" data-wf="new" ${home.model_ready ? "" : "disabled"}>${icon("plus")}New mission</button>
        ${home.model_ready ? "" : `<p class="faint small">An administrator needs to connect a model in Agents → Models first.</p>`}</div>
      <ul class="wf-examples">${EXAMPLES.map(x => `<li><button type="button" class="linkbtn" data-example="${esc(x)}">${esc(x)}</button></li>`).join("")}</ul></div>`;
  }
  function header(m) {
    const [tone, label, ic] = MSTATUS[m.status] || ["wait", m.status, "info"];
    const reached = new Set(m.timeline.map(x => x[0]));
    const active = ["running", "waiting"].includes(m.status);
    const steps = m.mode === "solo" ? STEPS.filter(s => ["recall", "execute", "evaluate", "learn"].includes(s[0])) : STEPS;
    const used = Math.min(100, m.tokens / m.budget * 100);
    const state = k => active && m.step === k ? (m.status === "waiting" ? "wait" : "now") : reached.has(k) ? "done" : active ? "todo" : "skip";
    return `<div class="wf-card wf-head">
      <div class="wf-head-top"><div class="wf-head-t"><h2>${esc(m.title)}</h2>
        <div class="wf-meta">${chip(tone, m.cancelling ? "Cancelling…" : label, ic)}${chip("off", m.mode === "solo" ? "One agent alone" : "Workforce team", m.mode === "solo" ? "bot" : "group")}
          ${m.bench_id ? chip("off", `Benchmark: ${home.arms[m.arm] || m.arm}, trial ${m.trial}`, "trophy") : ""}${m.netuids.map(n => `<span class="tag">SN${n}</span>`).join("")}
          <span class="faint small">Started ${stamp(m.created)}${m.finished ? ` · took ${dur(m.finished - m.created)}` : ""}</span></div></div>
        <div class="wf-head-act">${active ? `<button type="button" class="btn sm" data-wf="cancel" ${m.cancelling ? "disabled" : ""}>${icon("stop")}Cancel</button>`
          : m.bench_id ? `<button type="button" class="btn sm" data-wftab="bench">${icon("trophy")}Back to the benchmark</button>`
          : `<button type="button" class="btn sm" data-wf="rerun">${icon("cycle")}Run again</button>${m.status === "done" ? `<button type="button" class="btn sm" data-wf="benchmark">${icon("trophy")}Benchmark</button>` : ""}
             <button type="button" class="iconbtn danger" data-wf="delete" title="Delete this mission" aria-label="Delete this mission">${icon("trash")}</button>`}</div></div>
      <p class="wf-goal">${esc(m.goal)}</p>
      ${m.objective && m.objective !== m.goal ? `<p class="faint small"><b>Objective:</b> ${esc(m.objective)}</p>` : ""}
      <ol class="wf-steps" aria-label="Mission steps">${steps.map(([k, l, i]) => { const s = state(k); return `<li class="s-${s}"><span>${icon(s === "done" ? "check" : i)}</span>${l}<span class="wf-sr">: ${{ done: "done", now: "in progress", wait: "waiting for you", todo: "to do", skip: "skipped" }[s]}</span></li>`; }).join("")}</ol>
      <div class="wf-meter" role="img" aria-label="${fmtNum(m.tokens, 0)} of ${fmtNum(m.budget, 0)} tokens used">
        <div class="wf-meter-bar"><span style="width:${used.toFixed(1)}%"></span><i style="left:60%" title="Execute stops starting assignments here, so the review fits"></i></div>
        <small>${fmtNum(m.tokens, 0)} of ${fmtNum(m.budget, 0)} tokens${m.config?.eval_model ? ` · scored on ${esc(m.config.eval_model.split(":").pop())}` : ""}</small></div>
      ${m.error ? `<p class="wf-error">${icon("alert")}${esc(m.error)}</p>` : ""}</div>`;
  }
  const criteriaList = cs => cs.length ? `<ul class="wf-crit">${cs.map(c => `<li>${icon("target")}<span>${esc(c)}</span></li>`).join("")}</ul>` : "";
  function planReview(m) {
    const n = new Set(d.items.map(i => i.team)).size;
    return `<div class="wf-card wf-plan" data-keep="plan"><h3 class="wf-h">${icon("hand")}The plan waits for your approval <span class="faint">${esc(agent("ceo").name)} staffed ${plural(n, "team")}${m.replans ? `, planned again ${m.replans}×` : ""}</span></h3>
      <h4 class="wf-h4">Success criteria</h4>${criteriaList(m.criteria)}
      <h4 class="wf-h4">Work items</h4><ol class="wf-items">${d.items.map(it => { const t = team(it.team); return `<li><span class="wf-team-tag">${av(t, "xs")}${esc(t.name)}</span><div><b>${it.seq}. ${esc(it.title)}</b><p>${esc(it.brief)}</p>${it.depends.length ? `<small class="faint">After item ${it.depends.join(", ")}</small>` : ""}</div></li>`; }).join("")}</ol>
      <label class="wf-field"><span>Your note <em class="faint">optional when you approve; needed to send it back</em></span><textarea name="note" rows="2" maxlength="1500" placeholder="e.g. Add a security review before the strategy"></textarea></label>
      <div class="wf-row"><button type="button" class="btn primary" data-wf="approve">${icon("check")}Approve</button><button type="button" class="btn" data-wf="edit-plan">${icon("edit")}Edit the plan…</button>
        <button type="button" class="btn" data-wf="send-back" ${m.replans >= 2 ? "disabled" : ""}>${icon("undo")}Send it back with my note</button><button type="button" class="btn danger-text" data-wf="reject">Reject</button></div>
      <p class="faint small">Sent back, the CEO plans again with your note (${2 - m.replans} left). Rejecting closes the mission. A plan nobody decides on closes after 24 hours.</p></div>`;
  }
  function report(m) {
    const [tone, l, ic] = VERDICT[m.verdict] || ["wait", "Not scored", "info"];
    return `<div class="wf-card wf-report"><div class="wf-report-head"><div class="wf-score t-${tone}"><b>${m.score ?? "–"}</b><small>/100</small></div>
        <div><h3>${esc(m.headline || "Report")}</h3><div class="wf-meta">${chip(tone, `${l}, by ${agent("chief-evaluator").name}`, ic)}${m.summary ? `<span class="faint small">${esc(m.summary)}</span>` : ""}</div></div></div>
      ${m.criteria_eval.length ? `<ul class="wf-crit">${m.criteria_eval.map(c => `<li class="${c.met ? "ok" : "bad"}">${icon(c.met ? "check" : "close")}<span><b>${esc(c.criterion)}</b>${c.note ? ` <span class="faint">${esc(c.note)}</span>` : ""}</span><span class="wf-sr">${c.met ? "met" : "not met"}</span></li>`).join("")}</ul>` : criteriaList(m.criteria)}
      ${m.report ? `<div class="md wf-md">${Agents.md(m.report)}</div>` : ""}
      ${m.decisions.length ? `<h4 class="wf-h4">Decisions for you</h4><ul class="wf-decisions">${m.decisions.map(x => `<li>${icon("hand")}<span><b>${esc(x.title)}</b> ${esc(x.detail)}</span></li>`).join("")}</ul>` : ""}
      ${m.next_mission && !m.bench_id && m.status === "done" ? `<div class="wf-next">${icon("right")}<span><b>Next mission:</b> ${esc(m.next_mission)}</span><button type="button" class="btn sm" data-wf="follow">Start it</button></div>` : ""}</div>`;
  }
  function work(m) {
    const teams = new Set(d.items.map(i => i.team)).size;
    if (!d.items.length) return `<div class="wf-card"><h3 class="wf-h">${icon("group")}Work</h3><p class="faint small">${m.status === "running" ? `${esc(agent("ceo").name)} is planning…` : "No work items."}</p></div>`;
    return `<div class="wf-card wf-work"><h3 class="wf-h">${icon("group")}Work <span class="faint">${plural(d.assignments.length, "assignment")} across ${plural(teams, "team")}</span></h3>
      ${d.items.map(it => { const t = team(it.team), as = d.assignments.filter(a => a.item_seq === it.seq);
        return `<div class="wf-item"><div class="wf-item-h"><span class="wf-team-tag">${av(t, "xs")}${esc(t.name)}</span><b>${it.seq}. ${esc(it.title)}</b>${it.depends.length ? `<small class="faint">after item ${it.depends.join(", ")}</small>` : ""}</div>
          ${it.brief && m.mode !== "solo" ? `<p class="wf-brief">${esc(it.brief)}</p>` : ""}
          ${as.length ? as.map(asgCard).join("") : `<p class="faint small">${m.step === "delegate" ? "The lead is splitting it…" : "Not assigned yet."}</p>`}</div>`; }).join("")}</div>`;
  }
  function asgCard(a) {
    const g = agent(a.agent), [tone, l] = ASTATUS[a.status] || ["wait", a.status], lv = home.live[a.agent];
    const v = a.verdict && VERDICT[a.verdict];
    return `<button type="button" class="wf-asg s-${a.status}" data-asg="${a.id}">${av(g)}<span class="wf-asg-t"><b>${esc(a.title)}</b><small>${esc(g.name)}, ${esc(g.title)}${a.version > 1 ? ` · v${a.version}` : ""}</small>
        ${a.status === "running" && lv?.mission === mid ? `<small class="wf-live">${esc(lv.text)}</small>` : a.summary ? `<small class="wf-sum">${esc(a.summary)}</small>` : ""}</span>
      <span class="wf-asg-r">${v ? chip(v[0], `${v[1]} · ${a.score ?? "–"}`, v[2]) : chip(tone, l)}${a.attempt > 1 ? `<span class="tag" title="Reworked after the evaluator's note">attempt ${a.attempt}</span>` : ""}
        ${a.challenges ? `<span class="tag" title="Red-team challenges">${icon("flag")}${a.challenges}</span>` : ""}${a.model ? `<span class="tag wf-mono" title="${esc(a.model)}">${esc(a.model.split(":").pop())}</span>` : ""}</span></button>`;
  }
  function boardCard() {
    const kinds = [["all", "All"], ["finding", "Findings"], ["risk", "Risks"], ["question", "Questions"], ["challenge", "Challenges"]];
    const rows = d.board.filter(b => boardKind === "all" || b.kind === boardKind).slice().reverse();
    const checker = agent("fact-checker").name;
    const n = k => d.board.filter(b => b.kind === k).length;
    return `<div class="wf-card"><h3 class="wf-h">${icon("sticky")}Blackboard <span class="faint">what the team found, shared as it works</span></h3>
      <div class="seg wf-seg" role="group" aria-label="Show">${kinds.map(([k, l]) => `<button type="button" data-board="${k}" aria-pressed="${boardKind === k}">${l}${k !== "all" && n(k) ? ` ${n(k)}` : ""}</button>`).join("")}</div>
      ${rows.length ? `<ul class="wf-board">${rows.map(b => { const g = agent(b.author), st = BSTATUS[b.status] || ["wait", b.status];
        const lead = b.kind === "challenge" ? `<b>${b.severity === "major" ? "Major" : "Minor"} challenge:</b> ` : b.kind === "risk" ? "<b>Risk:</b> " : b.kind === "question" ? "<b>Question:</b> " : "";
        return `<li>${av(g, "xs")}<div><p>${lead}${esc(b.text)}</p><small class="faint">${esc(g.name)}${b.evidence ? ` · ${b.kind === "challenge" ? "on" : "evidence"}: ${esc(b.evidence)}` : ""}${b.confidence ? ` · ${esc(b.confidence)} confidence` : ""}</small>
          ${b.check_note ? `<small class="wf-check">${icon("check")}${esc(checker)}: ${esc(b.check_note)}</small>` : ""}</div>${chip(st[0], st[1])}</li>`; }).join("")}</ul>`
        : `<p class="faint small">Nothing here yet.</p>`}</div>`;
  }
  function debatesCard(m) {
    const ds = d.debates || [];
    if (!m.settings.debate && !ds.length) return "";
    const head = `<h3 class="wf-h">${icon("chat")}Debate <span class="faint">authors whose work disagrees argue it out, no lead in between</span></h3>`;
    if (!ds.length) {
      const now = m.status === "running" && m.step === "debate", held = m.timeline.some(x => x[0] === "debate");
      return `<div class="wf-card">${head}<p class="faint small">${now ? `${esc(agent("ceo").name)} is looking for what the deliverables disagree on…` : held ? "The deliverables didn't disagree on anything that changes what you'd do."
        : ["running", "waiting"].includes(m.status) ? "After the fact check, the authors of deliverables that disagree debate in up to two rounds." : "No debate ran: see Activity for why."}</p></div>`;
    }
    const sideName = (x, i) => `${esc(agent(x.sides[i - 1]?.agent).name)}`;
    return `<div class="wf-card">${head}${ds.map(x => { const [tone, l, ic] = DSTATUS[x.status] || ["wait", x.status], rounds = [...new Set(x.turns.map(t => t.round))];
      const live = x.status === "open" && m.status === "running";
      return `<div class="wf-debate"><div class="wf-debate-h"><b>${esc(x.question)}</b>${chip(live ? tone : x.status === "open" ? "off" : tone, live ? `Round ${Math.max(1, x.rounds + 1)}…` : x.status === "open" ? "Stopped" : l, ic)}</div>
        ${x.why ? `<p class="faint small">${esc(x.why)}</p>` : ""}
        <ul class="wf-sides">${x.sides.map((s, i) => { const g = agent(s.agent); return `<li>${av(g, "xs")}<div><b>Side ${i + 1}, ${esc(g.name)}</b> <small class="faint">assignment ${s.seq}</small><br><span class="small">${esc(s.opening)}</span></div></li>`; }).join("")}</ul>
        ${rounds.map(r => `<h4 class="wf-h4">Round ${r}</h4><ol class="wf-turns">${x.turns.filter(t => t.round === r).map(t => { const g = agent(t.agent), [st, sl] = STANCE[t.stance] || ["wait", t.stance];
          return `<li>${av(g, "xs")}<div><p><b>${esc(g.name)}</b> ${chip(st, t.stance === "agree" ? `Agrees with ${sideName(x, t.agree_with)}` : sl)}</p><p>${esc(t.argument)}</p>
            <small class="faint">${t.stance === "hold" ? "Position" : "Now"}: ${esc(t.position)}${t.evidence ? ` · Evidence: ${esc(t.evidence)}` : ""}${t.run ? ` · <button type="button" class="linkbtn" data-trace="${t.run}">trace</button>` : ""}</small></div></li>`; }).join("")}</ol>`).join("")}
        ${x.status === "consensus" ? `<p class="wf-outcome t-ok">${icon("check")}<span><b>Consensus on ${esc(agent(x.lead).name)}'s position:</b> ${esc(x.resolution)}</span></p>`
          : x.status === "split" ? `<p class="wf-outcome t-warn">${icon("hand")}<span><b>Split after ${plural(x.rounds, "round")}.</b> The positions stand side by side in the report's decisions for you.</span></p>` : ""}</div>`; }).join("")}</div>`;
  }
  function actionRow(x) {
    const g = agent(x.agent);
    return `<div class="wf-act" data-action="${x.id}" data-keep="act-${x.id}"><div class="wf-act-h">${av(g, "xs")}<b>${esc(x.action)}</b>${chip(RISK[x.risk] || "warn", `${x.risk} risk by policy`, "shield")}
        ${x.declared_risk !== x.risk ? `<span class="tag" title="The agent's own rating; the policy doesn't take its word for it">${esc(g.name)} said ${esc(x.declared_risk)}</span>` : ""}</div>
      ${x.details ? `<p>${esc(x.details)}</p>` : ""}<small class="faint">Why: ${esc(x.reason || "not given")} · The policy: ${esc(x.risk_why)}${x.mission_title ? ` · ${esc(x.mission_title)}` : ""}</small>
      ${x.status === "pending" ? `<div class="wf-row"><input name="note" placeholder="Your note (needed to reject)" maxlength="600" aria-label="Note"><button type="button" class="btn sm primary" data-decide="approve">${icon("check")}Approve</button><button type="button" class="btn sm" data-decide="reject">Reject</button></div>`
        : `<small>${x.status === "approved" ? chip("ok", "Approved: yours to carry out", "check") : chip("off", "Rejected")} ${esc(x.decided_by || "")}${x.decision_note ? `: ${esc(x.decision_note)}` : ""}</small>`}</div>`;
  }
  function actionsCard() {
    if (!d.actions.length) return "";
    return `<div class="wf-card"><h3 class="wf-h">${icon("hand")}Proposed actions <span class="faint">nothing runs unless you approve, and then you do it</span></h3>${d.actions.map(actionRow).join("")}</div>`;
  }
  function recallCard(m) {
    if (m.settings.memory === false) return `<div class="wf-card"><h3 class="wf-h">${icon("layers")}Memory</h3><p class="faint small">Memory was off for this mission.</p></div>`;
    if (!d.recall.length) return `<div class="wf-card"><h3 class="wf-h">${icon("layers")}Memory</h3><p class="faint small">${m.status === "running" && m.step === "queued" ? "Recalling…" : "Nothing stored matched this goal."}</p></div>`;
    return `<div class="wf-card"><h3 class="wf-h">${icon("layers")}Recalled memories <span class="faint">${d.recall.filter(r => r.cited).length} of ${d.recall.length} used by the work</span></h3>
      <ul class="wf-recall">${d.recall.map(r => `<li class="${r.cited ? "cited" : ""}"><span class="tag">${esc(KIND[r.kind] || r.kind)}</span><span>${esc(r.text)}</span>${r.cited ? `<small>${icon("check")}used</small>` : ""}</li>`).join("")}</ul></div>`;
  }
  function activity() {
    const ev = d.events.slice(-80).reverse();
    return `<div class="wf-grid"><div class="wf-card"><h3 class="wf-h">${icon("list")}Activity <span class="faint">live</span></h3>
        ${ev.length ? `<ol class="wf-feed">${ev.map(e => `<li class="k-${esc(e.kind)}">${icon(KIND_ICON[e.kind] || "info")}<span>${esc(e.text)}</span><time data-ts="${e.ts}" title="${stamp(e.ts)}">${ago(e.ts)}</time></li>`).join("")}</ol>` : `<p class="faint small">Nothing yet.</p>`}</div>
      <div class="wf-card"><h3 class="wf-h">${icon("route")}Runs <span class="faint">each one's routing decision, model calls and tool calls</span></h3>
        ${d.runs.length ? `<ol class="wf-runs">${d.runs.slice().reverse().map(r => { const g = agent(r.agent); return `<li><button type="button" data-trace="${r.id}">${av(g, "xs")}${runText(r, `<b>${esc(g.name)}</b> `)}${runEnd(r)}</button></li>`; }).join("")}</ol>`
          : `<p class="faint small">No runs yet.</p>`}</div></div>`;
  }

  const runText = (r, who = "") => `<span class="wf-run-t"><span>${who}${esc(RUNSTEP[r.step] || r.step)}</span><small class="faint"><span class="wf-mono">${esc((r.model || "").split(":").pop())}</span> · ${short(r.tokens)} tokens · ${r.finished ? dur(r.finished - r.started) : "running"}</small></span>`;
  const runEnd = r => r.status === "failed" ? chip("bad", "Failed") : r.status === "running" ? chip("run", "Running") : r.status === "cancelled" ? chip("off", "Cancelled")
    : r.score != null ? `<span class="tag" title="The evaluator's score for this work">${r.score}</span>` : "<span></span>";

  // ---------- dialogs ----------
  function dialog(id, cls = "") {
    let dlg = $(`#${id}`);
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = id; dlg.className = `modal wf-modal ${cls}`; document.body.append(dlg);
      dlg.addEventListener("click", e => { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); });
    }
    dlg.onclick = dlg.onsubmit = dlg.onchange = dlg.oninput = null;
    return dlg;
  }
  const closeBtn = `<button type="button" class="iconbtn wf-x" data-close aria-label="Close">${icon("close")}</button>`;
  function newMission(prefill = {}) {
    const s = home.settings, dlg = dialog("wf-new", "wide");
    const sw = (name, label, hint, on) => `<label class="wf-switch-row"><span><b>${label}</b><small>${hint}</small></span><span class="switch"><input type="checkbox" name="${name}" ${on ? "checked" : ""}><span></span></span></label>`;
    dlg.innerHTML = `<form class="wf-dlg">${closeBtn}<h3>${icon("target")}New mission</h3>
      <label class="wf-field"><span>Goal</span><textarea name="goal" rows="3" maxlength="2000" required placeholder="What should the workforce achieve?">${esc(prefill.goal || "")}</textarea></label>
      <div class="wf-chips">${EXAMPLES.map(x => `<button type="button" class="chip" data-ex="${esc(x)}">${esc(x.length > 52 ? x.slice(0, 50) + "…" : x)}</button>`).join("")}</div>
      <label class="wf-field"><span>Success criteria <em class="faint">optional, one per line; without them the CEO writes checkable ones</em></span><textarea name="criteria" rows="2" maxlength="1200" placeholder="e.g. Names three subnets with their daily emission"></textarea></label>
      <div class="wf-two"><label class="wf-field"><span>Subnets for context <em class="faint">optional, up to 3</em></span><input name="netuids" placeholder="e.g. 1, 64" inputmode="numeric" value="${esc(prefill.netuids || "")}"></label>
        <label class="wf-field"><span>Token budget</span><select name="budget">${home.budgets.map(b => `<option value="${b}" ${b === s.budget ? "selected" : ""}>${fmtNum(b, 0)}</option>`).join("")}</select></label></div>
      <fieldset class="wf-field"><legend>Who works on it</legend><div class="wf-modes">
        <label class="wf-modecard"><input type="radio" name="mode" value="team" checked><span>${icon("group")}<b>The workforce</b><small>Plan, delegate, execute, red team, fact check, evaluate, report.</small></span></label>
        <label class="wf-modecard"><input type="radio" name="mode" value="solo"><span>${icon("bot")}<b>One agent alone</b><small>A baseline: ${esc(agent("ceo").name)} with every tool, scored by the same evaluator.</small></span></label></div></fieldset>
      <div class="wf-switches">${sw("approve_plan", "Approve the plan first", "The mission waits for you after planning.", s.approve_plan)}${sw("critic", "Red-team review", `${esc(agent("red-teamer").name)} challenges the claims.`, s.critic)}
        ${sw("fact_check", "Fact check", `${esc(agent("fact-checker").name)} re-checks the key findings.`, s.fact_check)}${sw("rework", "Rework failures", "Failed work gets one more attempt.", s.rework)}
        ${sw("memory", "Memory", "Recall what earlier missions verified, and learn from this one.", s.memory)}${sw("debate", "Debate", "When deliverables disagree, their authors argue it out in up to two rounds. Needs a budget of 150,000 or more to fit.", s.debate)}</div>
      <div class="wf-row end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">${icon("play")}Start the mission</button></div></form>`;
    dlg.showModal(); $("[name=goal]", dlg).focus();
    dlg.onclick = e => { const x = e.target.closest("[data-ex]"); if (x) { $("[name=goal]", dlg).value = x.dataset.ex; $("[name=goal]", dlg).focus(); } };
    dlg.onsubmit = async e => {
      e.preventDefault();
      const f = e.target, btn = $("[type=submit]", f);
      const netuids = f.netuids.value.split(/[\s,]+/).filter(Boolean).map(x => +x.replace(/^sn/i, ""));
      if (netuids.some(n => !Number.isInteger(n) || n < 0)) return Auth.toast("Subnets are numbers, like 1, 64.");
      const body = { goal: f.goal.value.trim(), criteria: f.criteria.value.split("\n").map(x => x.trim()).filter(Boolean), netuids, budget: +f.budget.value, mode: f.mode.value,
        ...Object.fromEntries(["approve_plan", "critic", "fact_check", "rework", "memory", "debate"].map(k => [k, f[k].checked])) };
      btn.disabled = true;
      try { const s2 = await api("/api/workforce/missions", { method: "POST", body }); dlg.close(); d = s2; mid = s2.mission.id; store.set("wf.mid", mid); tab = "missions"; store.set("wf.tab", tab);
        home = await api("/api/workforce"); render(); follow(); Auth.toast("Mission started"); }
      catch (e2) { err(e2); btn.disabled = false; }
    };
  }
  async function approvalsDialog() {
    const dlg = dialog("wf-approvals", "wide");
    const draw = async () => {
      let list = [];
      try { list = (await api("/api/workforce/actions")).actions.filter(x => x.status === "pending"); } catch (e) { return err(e); }
      dlg.innerHTML = `<div class="wf-dlg">${closeBtn}<h3>${icon("hand")}Waiting for you</h3><p class="faint small">Agents propose; the policy rates the risk from what the action does; you decide. Approved, an action is yours to carry out: AXoR never does it.</p>
        ${list.length ? list.map(actionRow).join("") : `<p class="faint">Nothing waits for you.</p>`}</div>`;
    };
    await draw(); if (!dlg.open) dlg.showModal();
    dlg.onclick = async e => { const dc = e.target.closest("[data-decide]"); if (dc && await decideAction(dc)) { await draw(); refresh(); } };
  }
  async function decideAction(btn) {
    const box = btn.closest("[data-action]"), note = $("[name=note]", box)?.value.trim() || "", approve = btn.dataset.decide === "approve";
    if (!approve && !note) { Auth.toast("Say why you reject it: the workforce reads your note."); $("[name=note]", box)?.focus(); return false; }
    btn.disabled = true;
    try { await api(`/api/workforce/actions/${box.dataset.action}`, { method: "POST", body: { approve, note } }); Auth.toast(approve ? "Approved: it's on your list to carry out" : "Rejected"); return true; }
    catch (e) { err(e); btn.disabled = false; return false; }
  }
  function editPlan() {
    let items = d.items.map(it => ({ team: it.team, title: it.title, brief: it.brief, depends: [...it.depends] }));
    const teams = home.teams.filter(t => home.agents.some(a => a.team === t.id && a.status === "active" && a.role !== "evaluator"));
    const dlg = dialog("wf-plan", "wide");
    const read = () => { items = $$(".wf-pitem", dlg).map(fs => ({ team: $("[name=team]", fs).value, title: $("[name=title]", fs).value, brief: $("[name=brief]", fs).value, depends: $$("[name=dep]:checked", fs).map(x => +x.value) })); };
    const draw = note => {
      dlg.innerHTML = `<form class="wf-dlg">${closeBtn}<h3>${icon("edit")}Edit the plan</h3><p class="faint small">Change, add or remove work items; each goes to a team whose lead splits it for their people. Approving starts the work.</p>
        ${items.map((it, i) => `<fieldset class="wf-pitem"><div class="wf-row"><b>${i + 1}.</b><select name="team" aria-label="Team">${teams.map(t => `<option value="${t.id}" ${t.id === it.team ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>
            <input name="title" value="${esc(it.title)}" maxlength="200" required aria-label="Title" placeholder="What to deliver"><button type="button" class="iconbtn" data-rm="${i}" aria-label="Remove item ${i + 1}" ${items.length < 2 ? "disabled" : ""}>${icon("trash")}</button></div>
          <textarea name="brief" rows="2" maxlength="1000" aria-label="Brief" placeholder="What evidence it needs">${esc(it.brief)}</textarea>
          ${i ? `<div class="wf-deps"><span class="faint small">After:</span>${items.slice(0, i).map((_, j) => `<label class="chk"><input type="checkbox" name="dep" value="${j + 1}" ${it.depends.includes(j + 1) ? "checked" : ""}>item ${j + 1}</label>`).join("")}</div>` : ""}</fieldset>`).join("")}
        <button type="button" class="btn sm" data-add ${items.length >= 8 ? "disabled" : ""}>${icon("plus")}Add an item</button>
        <label class="wf-field"><span>Your note <em class="faint">optional; the team reads it</em></span><textarea name="note" rows="2" maxlength="1500">${esc(note || "")}</textarea></label>
        <div class="wf-row end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">${icon("check")}Approve this plan</button></div></form>`;
    };
    draw(); dlg.showModal();
    dlg.onclick = e => {
      const rm = e.target.closest("[data-rm]"), note = $("[name=note]", dlg)?.value;
      if (rm) { read(); const i = +rm.dataset.rm; items.splice(i, 1); items.forEach(it => { it.depends = it.depends.filter(x => x !== i + 1).map(x => x > i + 1 ? x - 1 : x); }); draw(note); }
      if (e.target.closest("[data-add]")) { read(); items.push({ team: teams[0]?.id, title: "", brief: "", depends: [] }); draw(note); $$("[name=title]", dlg).at(-1)?.focus(); }
    };
    dlg.onsubmit = async e => {
      e.preventDefault(); read();
      try { d = await api(`/api/workforce/missions/${mid}/plan`, { method: "POST", body: { approve: true, items, note: $("[name=note]", dlg).value.trim() } }); dlg.close(); Auth.toast("Plan approved: the leads are delegating"); render(); }
      catch (e2) { err(e2); }
    };
  }
  async function asgDialog(id) {
    let a; try { a = await api(`/api/workforce/assignments/${id}`); } catch (e) { return err(e); }
    const g = agent(a.agent), dlg = dialog("wf-asg", "wide"), v = a.verdict && VERDICT[a.verdict];
    const checker = agent("fact-checker").name;
    dlg.innerHTML = `<div class="wf-dlg">${closeBtn}<div class="wf-dlg-head">${av(g, "lg")}<div><h3>${esc(a.title)}</h3><p class="faint">${esc(g.name)}, ${esc(g.title)} · ${esc(team(a.team).name)} · assignment ${a.seq}${a.attempt > 1 ? ` · attempt ${a.attempt}` : ""}${a.version ? ` · instructions v${a.version}` : ""}</p></div>
        ${v ? chip(v[0], `${v[1]} · ${a.score ?? "–"}`, v[2]) : chip(...(ASTATUS[a.status] || ["wait", a.status]))}</div>
      <dl class="wf-dl"><dt>Task</dt><dd>${esc(a.task)}</dd><dt>Done when</dt><dd>${esc(a.done_when || "—")}</dd>
        ${a.eval_note ? `<dt>${esc(agent("chief-evaluator").name)}</dt><dd>${a.category && a.category !== "none" ? `<b>${esc(CAT[a.category] || a.category)}:</b> ` : ""}${esc(a.eval_note)}${a.first_verdict && a.first_verdict !== a.verdict ? ` <span class="faint">(first attempt: ${esc(a.first_verdict)} ${a.first_score ?? ""})</span>` : ""}</dd>` : ""}
        ${a.model ? `<dt>Model</dt><dd class="wf-mono">${esc(a.model)} · ${fmtNum(a.tokens, 0)} tokens · ${plural(a.tool_calls, "lookup")}</dd>` : ""}</dl>
      <h4 class="wf-h4">Deliverable</h4><div class="md wf-md wf-deliv">${a.output ? Agents.md(a.output) : `<p class="faint">Nothing filed yet.</p>`}</div>
      ${a.board.filter(b => b.kind !== "challenge").length ? `<h4 class="wf-h4">Findings</h4><ul class="wf-board">${a.board.filter(b => b.kind !== "challenge").map(b => { const st = BSTATUS[b.status] || ["wait", b.status];
        return `<li><div><p>${b.kind !== "finding" ? `<b>${b.kind === "risk" ? "Risk" : "Question"}:</b> ` : ""}${esc(b.text)}</p><small class="faint">Evidence: ${esc(b.evidence || "none given")} · ${esc(b.confidence || "")} confidence</small>${b.check_note ? `<small class="wf-check">${icon("check")}${esc(checker)}: ${esc(b.check_note)}</small>` : ""}</div>${chip(st[0], st[1])}</li>`; }).join("")}</ul>` : ""}
      ${a.board.some(b => b.kind === "challenge") ? `<h4 class="wf-h4">${esc(agent("red-teamer").name)}'s challenges</h4><ul class="wf-board">${a.board.filter(b => b.kind === "challenge").map(c => `<li><div><p><b>${c.severity === "major" ? "Major" : "Minor"}:</b> ${esc(c.text)}</p><small class="faint">On: ${esc(c.evidence)}</small></div>${chip(...(BSTATUS[c.status] || ["wait", c.status]))}</li>`).join("")}</ul>
        ${a.response ? `<p class="wf-response">${icon("chat")}<span><b>${esc(g.name)} ${a.stance === "revise" ? "revised the work" : "rebutted"}:</b> ${esc(a.response)}</span></p>` : ""}` : ""}
      ${a.actions.length ? `<h4 class="wf-h4">Proposed actions</h4>${a.actions.map(actionRow).join("")}` : ""}
      ${a.runs.length ? `<h4 class="wf-h4">Runs</h4><ol class="wf-runs">${a.runs.map(r => `<li><button type="button" data-trace="${r.id}">${runText(r)}${runEnd(r)}</button></li>`).join("")}</ol>` : ""}</div>`;
    if (!dlg.open) dlg.showModal();
    dlg.onclick = async e => {
      const t = e.target.closest("[data-trace]"); if (t) { dlg.close(); return traceDialog(+t.dataset.trace); }
      const dc = e.target.closest("[data-decide]"); if (dc && await decideAction(dc)) { refresh(); asgDialog(id); }
    };
  }
  async function traceDialog(id) {
    let r; try { r = await api(`/api/workforce/runs/${id}`); } catch (e) { return err(e); }
    const g = agent(r.agent), dlg = dialog("wf-trace", "wide"), route = r.route || {};
    dlg.innerHTML = `<div class="wf-dlg">${closeBtn}<div class="wf-dlg-head">${av(g, "lg")}<div><h3>${esc(g.name)} ${esc(RUNSTEP[r.step] || r.step)}</h3>
        <p class="faint">${esc(r.model || "")} · ${fmtNum(r.tokens, 0)} tokens · ${r.finished ? dur(r.finished - r.started) : "running"} · ${stamp(r.started)}</p></div>${chip(...({ done: ["ok", "Done"], failed: ["bad", "Failed"], running: ["run", "Running"], cancelled: ["off", "Cancelled"] }[r.status] || ["wait", r.status]))}</div>
      ${r.error ? `<p class="wf-error">${icon("alert")}${esc(r.error)}</p>` : ""}
      <h4 class="wf-h4">Routing decision <span class="faint">task: ${esc(route.task || r.task)}</span></h4><p class="small">${esc(route.reason || "—")}</p>
      ${route.candidates?.length ? `<div class="wf-scroll"><table class="wf-table"><thead><tr><th>Model</th><th>Tier</th><th title="The evaluator's average score, shrunk towards the tier's prior">Quality</th><th>Cost a call</th><th>Latency</th><th>Failure risk</th><th>Runs</th><th>Score</th></tr></thead>
        <tbody>${route.candidates.map(c => `<tr class="${c.model === route.model ? "on" : ""}"><td class="wf-mono">${esc(c.model.split(":").pop())}${c.model === route.model ? ` ${chip("ok", "picked")}` : ""}</td><td>${c.tier}</td><td>${fmtNum(c.quality, 0)}${c.scored ? "" : " <span class=\"faint\">prior</span>"}</td>
          <td>$${fmtNum(c.cost, 4)}</td><td>${dur(c.latency)}</td><td>${pctf(c.risk)}</td><td>${c.runs}</td><td><b>${fmtNum(c.score, 3)}</b></td></tr>`).join("")}</tbody></table></div>
        <p class="faint small">S = ${(route.weights || []).map((w, i) => `${["", "−", "−", "−"][i]}${fmtNum(w, 2)}·${["Q", "C", "L", "R"][i]}`).join(" ")} + exploration bonus. Cost against $0.25 a call, latency against 60 s.</p>` : ""}
      <h4 class="wf-h4">Spans <span class="faint">${plural(r.spans.length, "call")}</span></h4>
      <ol class="wf-spans">${r.spans.map(s => `<li class="k-${esc(s.kind)} ${s.error ? "err" : ""}"><details><summary>${icon(s.kind === "model" ? "chip" : s.kind === "denied" ? "ban" : "search")}<b>${esc(s.kind === "model" ? s.name : s.name.replace(/_/g, " "))}</b>
          <span class="faint">${s.kind === "denied" ? "refused: not in the grant" : s.kind}</span><span>${dur(s.end - s.ts)}</span>${s.tokens ? `<span>${short(s.tokens)}</span>` : "<span></span>"}</summary>
          ${s.input ? `<h5>Input</h5><pre>${esc(s.input)}</pre>` : ""}${s.output ? `<h5>Output</h5><pre>${esc(s.output)}</pre>` : ""}</details></li>`).join("")}</ol></div>`;
    if (!dlg.open) dlg.showModal();
  }

  // ---------- org ----------
  function org() {
    const ceo = home.agents.find(a => a.key === "ceo");
    return `<div class="wf-org">
      <div class="wf-org-top">${ceo ? node(ceo, "ceo") : ""}<p class="faint small">Plans missions and staffs only the teams each one needs. Work flows down to the leads and back up through the blackboard: no all-to-all chatter.</p></div>
      <div class="wf-teams">${home.teams.map(t => { const ms = home.agents.filter(a => a.team === t.id), lead = ms.find(a => a.level === "lead");
        return `<section class="wf-team" aria-label="${esc(t.name)} team"><header>${av(t)}<div><b>${esc(t.name)}</b><small>${esc(t.job)}</small></div></header>
          ${lead ? node(lead, "lead") : ""}<div class="wf-team-ppl">${ms.filter(a => a !== lead).map(a => node(a)).join("")}</div>
          <button type="button" class="btn sm wf-hire" data-hire="${t.id}" ${home.agents.length >= home.limits.agents ? "disabled" : ""}>${icon("userplus")}Hire a specialist</button></section>`; }).join("")}</div>
      <h3 class="wf-h wf-mt">${icon("layers")}Shared infrastructure</h3><div class="wf-infra">${infra()}</div></div>`;
  }
  function node(a, cls = "") {
    const lv = home.live[a.key], st = a.status === "paused" ? "paused" : lv ? "working" : "idle";
    const line = st === "paused" ? "Paused" : lv ? `${lv.text}${lv.mission ? ` · mission #${lv.mission}` : " · in a test"}`
      : a.n ? `${plural(a.n, "assignment")} · ${Math.round(a.passed / a.n * 100)}% passed · avg ${fmtNum(a.score, 0)}` : a.runs ? plural(a.runs, "run") : "No work yet";
    return `<button type="button" class="wf-node ${cls} s-${st}" data-agent="${esc(a.key)}">${av(a, cls === "ceo" ? "lg" : "sm")}<span class="wf-node-t">
      <b>${esc(a.name)}${a.version > 1 ? ` <span class="tag">v${a.version}</span>` : ""}${a.builtin ? "" : ` <span class="tag">hired</span>`}</b>
      <small>${esc(a.title)}${ROLE[a.role] ? ` · ${ROLE[a.role]}` : ""}</small><small class="${st === "working" ? "wf-live" : "faint"}">${esc(line)}</small></span></button>`;
  }
  function infra() {
    const s = home.settings, p = home.pending;
    return [["layers", "Memory", `${home.memory} active`, "Facts, procedures, strategies and episodes; a mission's blackboard is its working memory.", "memory"],
      ["key", "Tools & grants", plural(home.available.length, "tool") + " here", "Each agent gets only its team's tools, checked on every call.", "org"],
      ["route", "Model router", s.pool ? `${plural(s.pool, "model")} · ${WEIGHTS[s.weights]?.[0] || s.weights}` : "One model, no pool", "Picks a model per call by quality, cost, latency and failures.", "settings"],
      ["chart", "Evaluation", `${esc(agent("chief-evaluator").name)}, independent`, "Pass rates, recovery and cost per success on the Scoreboard.", "scores"],
      ["shield", "Governance", p.actions ? `${p.actions} waiting for you` : "Nothing waiting", "Agents propose; the policy rates the risk; you decide.", "missions"],
      ["sprout", "Self-improvement", MODES[s.improve]?.[0] || s.improve, "Changes are tested blind against the current version first.", "improve"]]
      .map(([ic, l, v, desc, go]) => `<button type="button" class="wf-tile" data-wftab="${go}">${icon(ic)}<span><b>${l}</b><small>${esc(v)}</small><em>${desc}</em></span></button>`).join("");
  }
  async function agentDialog(key) {
    let v; try { v = await api(`/api/workforce/agents/${encodeURIComponent(key)}`); } catch (e) { return err(e); }
    const dlg = dialog("wf-agent", "wide");
    const draw = () => {
      const a = v.agent, t = team(a.team), fixed = ["ceo", "chief-evaluator"].includes(a.key), next = Math.max(...v.versions.map(x => x.version)) + 1;
      dlg.innerHTML = `<form class="wf-dlg">${closeBtn}<div class="wf-dlg-head">${av(a, "lg")}<div><h3>${esc(a.name)} <span class="tag">v${a.version}</span></h3><p class="faint">${esc(a.title)} · ${esc(t.name)}${ROLE[a.role] ? ` · ${ROLE[a.role]}` : ""}</p></div>
          ${fixed ? `<span class="faint small">Runs every mission</span>` : `<label class="wf-switch-l"><span>Active</span><span class="switch"><input type="checkbox" name="active" ${a.status === "active" ? "checked" : ""}><span></span></span></label>`}</div>
        <div class="wf-two"><label class="wf-field"><span>Name</span><input name="name" value="${esc(a.name)}" maxlength="40" required></label><label class="wf-field"><span>Title</span><input name="title" value="${esc(a.title)}" maxlength="60" required></label></div>
        <label class="wf-field"><span>What ${esc(a.name)} does</span><input name="job" value="${esc(a.job)}" maxlength="300"></label>
        ${a.team !== "exec" ? `<fieldset class="wf-field"><legend>Tools <em class="faint">only what ${esc(t.name)} may use; checked on every call</em></legend><div class="wf-tools">${v.team_tools.map(n => `<label class="chk"><input type="checkbox" name="tool" value="${n}" ${a.tools.includes(n) ? "checked" : ""}>${esc(v.labels[n] || n)}${v.available.includes(n) ? "" : ` <em class="faint" title="Not available to you on this server">(unavailable here)</em>`}</label>`).join("")}</div></fieldset>`
          : `<p class="faint small">${esc(a.name)} plans from the fact sheet. Working alone, ${esc(a.name)} gets every tool you have.</p>`}
        <label class="wf-field"><span>Instructions <em class="faint">a change is saved as v${next}; any version can be restored</em></span><textarea name="instructions" rows="7" maxlength="4000">${esc(a.instructions)}</textarea></label>
        <label class="wf-field"><span>Why you're changing it <em class="faint">needed when the instructions or the tools change; saved with the new version</em></span><input name="note" maxlength="300" placeholder="e.g. Always compare with last week"></label>
        <div class="wf-row end">${a.builtin ? "" : `<button type="button" class="btn danger-text" data-fire>Remove from the workforce</button>`}<button type="button" class="btn" data-close>Close</button><button class="btn primary" type="submit">${icon("check")}Save</button></div>
        <h4 class="wf-h4">Versions</h4><div class="wf-scroll"><table class="wf-table"><thead><tr><th>Version</th><th>From</th><th>Note</th><th>Assignments</th><th>Passed first try</th><th>Avg score</th><th></th></tr></thead>
          <tbody>${v.versions.map(x => `<tr><td>v${x.version}${x.version === a.version ? ` ${chip("ok", "current")}` : ""}</td><td>${esc(SOURCE[x.source] || x.source)}${x.author ? `<br><small class="faint">${esc(x.author)}</small>` : ""}</td>
            <td>${esc(x.note || "")}<br><small class="faint">${stamp(x.created)}</small></td><td>${x.stats?.n ?? 0}</td><td>${x.stats?.n ? pctf(x.stats.pass1 / x.stats.n) : "–"}</td><td>${x.stats?.score != null ? fmtNum(x.stats.score, 0) : "–"}</td>
            <td>${x.version !== a.version ? `<button type="button" class="btn sm" data-restore="${x.version}">Restore</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
        ${v.recent.length ? `<h4 class="wf-h4">Recent work</h4><ul class="wf-recent">${v.recent.map(r => `<li><button type="button" class="linkbtn" data-open-mission="${r.mission_id}">${esc(r.mission_title)}</button><span>${esc(r.title)}</span>${r.verdict ? chip(VERDICT[r.verdict][0], `${VERDICT[r.verdict][1]} · ${r.score ?? "–"}`) : chip(...(ASTATUS[r.status] || ["wait", r.status]))}</li>`).join("")}</ul>` : ""}</form>`;
    };
    draw(); if (!dlg.open) dlg.showModal();
    const save = async body => {
      try { v = await api(`/api/workforce/agents/${encodeURIComponent(key)}`, { method: "PATCH", body }); home = await api("/api/workforce"); draw(); render(); return true; }
      catch (e) { err(e); return false; }
    };
    dlg.onsubmit = async e => {
      e.preventDefault();
      const f = e.target, a = v.agent, body = {};
      const el = f.elements;
      for (const k of ["name", "title", "job"]) if (el[k].value.trim() !== (a[k] || "")) body[k] = el[k].value.trim();
      if (el.instructions.value.trim() !== (a.instructions || "").trim()) body.instructions = el.instructions.value;
      if (a.team !== "exec") { const tools = $$("[name=tool]:checked", f).map(x => x.value); if (tools.sort().join() !== [...a.tools].sort().join()) body.tools = tools; }
      if (!Object.keys(body).length) return Auth.toast("Nothing changed.");
      if (body.instructions || body.tools) {  // a change to what the agent does needs a reason; it becomes a new version
        body.note = el.note.value.trim();
        if (body.note.length < 3) { el.note.focus(); return Auth.toast("Say why you're changing it"); }
      }
      if (await save(body)) Auth.toast(body.instructions || body.tools ? `Saved as v${v.agent.version}` : "Saved");
    };
    dlg.onchange = async e => { if (e.target.name === "active") { if (await save({ status: e.target.checked ? "active" : "paused" })) Auth.toast(e.target.checked ? "Back on the workforce" : "Paused: the CEO won't staff them"); } };
    dlg.onclick = async e => {
      const rs = e.target.closest("[data-restore]");
      if (rs) { try { v = await api(`/api/workforce/agents/${encodeURIComponent(key)}/restore`, { method: "POST", body: { version: +rs.dataset.restore } }); home = await api("/api/workforce"); draw(); render(); Auth.toast(`Restored as v${v.agent.version}`); } catch (e2) { err(e2); } return; }
      const om = e.target.closest("[data-open-mission]"); if (om) { dlg.close(); return select(+om.dataset.openMission); }
      if (e.target.closest("[data-fire]")) {
        if (!(await UI.confirm({ title: `Remove ${esc(v.agent.name)} from the workforce?`, body: "Their past work stays in the missions it belongs to.", ok: "Remove" }))) return;
        try { await api(`/api/workforce/agents/${encodeURIComponent(key)}`, { method: "DELETE" }); dlg.close(); Auth.toast("Removed"); refresh(); } catch (e2) { err(e2); }
      }
    };
  }
  function hireDialog(tid) {
    const t = team(tid), dlg = dialog("wf-hire", "wide"), tools = home.team_tools[tid] || [];
    dlg.innerHTML = `<form class="wf-dlg">${closeBtn}<h3>${icon("userplus")}Hire a specialist for ${esc(t.name)}</h3>
      <p class="faint small">${esc(t.name)}'s lead can give them assignments from the next mission on. They read data only, like everyone on the workforce.</p>
      <div class="wf-two"><label class="wf-field"><span>Name</span><input name="name" maxlength="40" required placeholder="e.g. Ola"></label><label class="wf-field"><span>Title</span><input name="title" maxlength="60" required placeholder="e.g. Pricing Analyst"></label></div>
      <label class="wf-field"><span>What they do <em class="faint">their lead reads this when delegating</em></span><input name="job" maxlength="300" placeholder="e.g. Compares GPU rental prices across providers"></label>
      <label class="wf-field"><span>Instructions</span><textarea name="instructions" rows="5" maxlength="4000" required placeholder="How they work: what to check, what evidence to bring, what to avoid."></textarea></label>
      <fieldset class="wf-field"><legend>Tools <em class="faint">what ${esc(t.name)} may use</em></legend><div class="wf-tools">${tools.map(n => `<label class="chk"><input type="checkbox" name="tool" value="${n}">${esc(home.labels[n] || n)}${home.available.includes(n) ? "" : ` <em class="faint">(unavailable here)</em>`}</label>`).join("")}</div></fieldset>
      <div class="wf-two"><label class="wf-field"><span>Icon</span><select name="icon">${["bot", "chart", "search", "coins", "shield", "server", "chip", "target", "bulb", "zap", "globe", "rocket", "book"].map(i => `<option>${i}</option>`).join("")}</select></label>
        <label class="wf-field"><span>Colour</span><select name="color">${["slate", "blue", "teal", "green", "amber", "orange", "rose", "violet"].map(c => `<option ${c === t.color ? "selected" : ""}>${c}</option>`).join("")}</select></label></div>
      <div class="wf-row end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">${icon("userplus")}Hire</button></div></form>`;
    dlg.showModal(); $("[name=name]", dlg).focus();
    dlg.onsubmit = async e => {
      e.preventDefault();
      const f = e.target, el = f.elements;
      try { await api("/api/workforce/agents", { method: "POST", body: { team: tid, name: el.name.value.trim(), title: el.title.value.trim(), job: el.job.value.trim(), instructions: el.instructions.value.trim(),
        tools: $$("[name=tool]:checked", f).map(x => x.value), icon: el.icon.value, color: el.color.value } }); dlg.close(); Auth.toast(`${el.name.value.trim()} joined ${t.name}`); refresh(); }
      catch (e2) { err(e2); }
    };
  }

  // ---------- memory ----------
  function memoryTab() {
    if (!memory) return Loading.line("Reading the memory…");
    const kinds = [["", "All"], ["semantic", "Facts"], ["procedural", "Procedures"], ["strategy", "Strategies"], ["episodic", "Episodes"]];
    const q = memQ.trim().toLowerCase();
    const rows = memory.memories.filter(r => (!memKind || r.kind === memKind) && (!q || `${r.text} ${r.tags.join(" ")}`.toLowerCase().includes(q)));
    const active = Object.values(memory.counts).reduce((s, n) => s + n, 0);
    return `<div class="wf-grid wide"><div class="wf-card"><div class="wf-toolbar"><div class="seg" role="group" aria-label="Kind">${kinds.map(([k, l]) => `<button type="button" data-memkind="${k}" aria-pressed="${memKind === k}">${l}${k && memory.counts[k] ? ` ${memory.counts[k]}` : ""}</button>`).join("")}</div>
        <div class="search wf-search">${icon("search")}<input data-memq type="search" placeholder="Search memories" value="${esc(memQ)}" aria-label="Search memories"></div></div>
      ${rows.length ? `<ul class="wf-mems">${rows.map(memRow).join("")}</ul>` : `<p class="faint">${memory.memories.length ? "Nothing matches." : "Nothing stored yet. Missions store what they verify and what passed; you can also teach the workforce yourself."}</p>`}</div>
      <div class="wf-col"><form class="wf-card" data-form="teach" data-keep="teach"><h3 class="wf-h">${icon("plus")}Teach the workforce</h3>
          <label class="wf-field"><span>Kind</span><select name="kind"><option value="semantic">A fact</option><option value="procedural">A procedure: how to do something</option><option value="strategy">A strategy: what works when</option></select></label>
          <label class="wf-field"><span>Memory</span><textarea name="text" rows="3" maxlength="200" required placeholder="e.g. I mine on one RTX 4090 in Frankfurt"></textarea></label>
          <label class="wf-field"><span>For</span><select name="team"><option value="all">Everyone</option>${home.teams.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select></label>
          <button class="btn primary" type="submit">${icon("plus")}Teach</button></form>
        <div class="wf-card"><h3 class="wf-h">${icon("info")}How memory works</h3><ul class="wf-howto">
          <li><b>Recall:</b> each mission retrieves the memories that share the most telling words with its goal, the useful and recent ones first. The CEO sees them all; a specialist sees its team's.</li>
          <li><b>Used, not just recalled:</b> agents cite the memories they rely on. A memory used in passing work gains usefulness; <b>lift</b> is the average score of missions that used it against your average${memory.average != null ? ` (${fmtNum(memory.average, 0)})` : ""}.</li>
          <li><b>Learn:</b> facts come only from findings the fact checker verified; procedures and strategies only from passing work. Near-duplicates merge, contradicted memories are superseded, and every mission leaves an episode.</li>
          <li><b>Working memory</b> is each mission's blackboard. ${active} of ${memory.limit} active; past the limit, the least useful are archived.</li></ul></div></div></div>`;
  }
  function memRow(r) {
    return `<li class="${r.status !== "active" ? "off" : ""}" data-mem="${r.id}"><div class="wf-mem-h"><span class="tag">${esc(KIND[r.kind] || r.kind)}</span>${r.team && r.team !== "all" ? `<span class="tag">${esc(team(r.team).name)}</span>` : ""}
        ${r.status !== "active" ? `<span class="tag">${esc(r.status)}</span>` : ""}<span class="faint small">${r.source === "user" ? "taught by you" : r.mission_id ? `from mission #${r.mission_id}` : ""} · <time data-ts="${r.updated}">${ago(r.updated)}</time></span></div>
      <p>${esc(r.text)}</p>${r.tags.length ? `<div class="wf-tags">${r.tags.map(t => `<span>#${esc(t)}</span>`).join("")}</div>` : ""}
      ${r.evidence ? `<small class="faint">Evidence: ${esc(r.evidence)}</small>` : ""}
      <div class="wf-mem-f"><span title="Missions that retrieved it">Recalled ${r.retrieved}</span><span title="Missions whose work used it">Used ${r.cited}</span><span title="Used in missions that passed">Helped ${r.helped}</span>
        ${r.lift != null ? `<span title="Average score of missions that used it, against your average">Lift ${r.lift >= 0 ? "+" : "−"}${fmtNum(Math.abs(r.lift), 1)}</span>` : ""}
        <span class="wf-mem-btns">${r.status === "active" ? `<button type="button" class="linkbtn" data-memact="archive">Archive</button>` : r.status === "archived" ? `<button type="button" class="linkbtn" data-memact="restore">Restore</button>` : ""}<button type="button" class="linkbtn" data-memact="delete">Delete</button></span></div></li>`;
  }
  async function memAction(id, act) {
    try {
      if (act === "delete") {
        if (!(await UI.confirm({ title: "Delete this memory?", body: "The workforce forgets it for good.", ok: "Delete" }))) return;
        memory = await api(`/api/workforce/memory/${id}`, { method: "DELETE" });
      } else memory = await api(`/api/workforce/memory/${id}`, { method: "PATCH", body: { status: act === "archive" ? "archived" : "active" } });
    } catch (e) { return err(e); }
    render();
  }

  // ---------- scoreboard ----------
  function scores() {
    if (!metrics) return Loading.line("Adding up the scores…");
    const k = metrics.kpi;
    if (!k.finished) return `<div class="wf-card"><p class="faint">No finished missions yet: the scoreboard fills in as the evaluator scores the work.</p></div>`;
    const tile = (label, value, sub) => `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
    return `<div class="stats">${tile("Missions passed", `${k.passes} of ${k.finished}`, `${pctf(k.pass_rate)} · 95% interval ${k.ci ? `${pctf(k.ci[0])}–${pctf(k.ci[1])}` : "–"}`)}
        ${tile("Average score", fmtNum(k.score, 0), "by the Chief Evaluator, out of 100")}${tile("Tokens per success", k.per_success ? short(k.per_success) : "–", `${short(k.tokens)} tokens in all`)}
        ${tile("Time per mission", dur(k.p50), `median · p95 ${dur(k.p95)}`)}</div>
      <div class="wf-grid">${trendChart()}${categoryChart()}</div>
      ${metrics.regressions.length ? `<div class="wf-card wf-warnbox">${icon("alert")}<div><b>Regressions</b>${metrics.regressions.map(r => `<p>${esc(r.name)} scored ${fmtNum(r.after, 0)} on v${r.to}, down from ${fmtNum(r.before, 0)} on v${r.from}. <button type="button" class="linkbtn" data-agent="${esc(r.key)}">Open ${esc(r.name)}</button> to restore a version.</p>`).join("")}</div></div>` : ""}
      <div class="wf-card"><h3 class="wf-h">${icon("users")}Agents <span class="faint">first-attempt pass rate, recovery after rework, and verified results per token</span></h3><div class="wf-scroll">${statTable(metrics.agents, true)}</div></div>
      <div class="wf-card"><h3 class="wf-h">${icon("group")}Teams</h3><div class="wf-scroll">${statTable(metrics.teams, false)}</div></div>
      <div class="wf-card"><h3 class="wf-h">${icon("route")}Models <span class="faint">what the router learns from</span></h3><div class="wf-scroll"><table class="wf-table"><thead><tr><th>Model</th><th>Tier</th><th class="num">Calls</th><th class="num">Failed</th><th class="num">Avg score</th><th class="num">Median call</th><th class="num">Tokens</th><th>Used for</th></tr></thead>
        <tbody>${metrics.models.map(x => `<tr><td class="wf-mono">${esc(x.model)}</td><td>${x.tier}</td><td class="num">${x.calls}</td><td class="num">${pctf(x.fail_rate)}</td><td class="num">${x.score != null ? `${fmtNum(x.score, 0)} <span class="faint">(${x.scored})</span>` : "–"}</td>
          <td class="num">${dur(x.p50)}</td><td class="num">${short(x.tokens)}</td><td class="small">${Object.entries(x.steps).map(([s, n]) => `${esc(s)} ${n}`).join(" · ")}</td></tr>`).join("")}</tbody></table></div></div>`;
  }
  function statTable(rows, agents) {
    return `<table class="wf-table"><thead><tr><th>${agents ? "Agent" : "Team"}</th><th class="num" title="Evaluated assignments">Work</th><th class="num" title="Passed on the first attempt">Pass@1</th><th class="num" title="Failed first, then passed after rework">Recovery</th>
      <th class="num">Avg ± sd</th><th class="num" title="Tokens per passed assignment">Tokens/pass</th><th class="num" title="Passed assignments per 100k tokens">Utility</th><th class="num" title="Verified findings per lookup">Efficiency</th><th class="num">Verified / disputed</th><th class="num">p95 time</th><th class="num">Runs</th></tr></thead>
      <tbody>${rows.map(r => `<tr>${agents ? `<td><button type="button" class="wf-who" data-agent="${esc(r.key)}">${av(r, "xs")}<span><b>${esc(r.name)}${r.version > 1 ? ` <span class="tag">v${r.version}</span>` : ""}</b><small class="faint">${esc(r.title)}</small></span></button></td>` : `<td><b>${esc(r.name)}</b></td>`}
        <td class="num">${r.n}</td><td class="num">${pctf(r.pass1)}</td><td class="num">${pctf(r.recovery)}</td><td class="num">${r.score != null ? `${fmtNum(r.score, 0)}${r.sd != null ? ` ± ${fmtNum(r.sd, 0)}` : ""}` : "–"}</td>
        <td class="num">${r.per_pass ? short(r.per_pass) : "–"}</td><td class="num">${r.utility != null ? fmtNum(r.utility, 1) : "–"}</td><td class="num">${r.efficiency != null ? fmtNum(r.efficiency, 2) : "–"}</td>
        <td class="num">${r.verified} / ${r.disputed}</td><td class="num">${dur(r.p95)}</td><td class="num">${r.runs}</td></tr>`).join("")}</tbody></table>`;
  }
  // one series (each mission's score): columns in the app's first series colour, a value per column on hover and focus
  function trendChart() {
    const t = metrics.trend;
    return `<div class="wf-card"><h3 class="wf-h">${icon("chart")}Mission scores <span class="faint">the last ${plural(t.length, "mission")}, oldest first</span></h3>
      <div class="wf-chart" role="group" aria-label="Scores of the last ${t.length} missions"><div class="wf-yaxis" aria-hidden="true"><span>100</span><span>50</span><span>0</span></div>
        <div class="wf-plot">${[100, 50, 0].map(v => `<i class="wf-grid-line" style="bottom:${v}%"></i>`).join("")}
          <div class="wf-cols">${t.map(m => `<span class="wf-col-hit" tabindex="0" data-tip="${m.score}/100|Mission #${m.id} · ${m.verdict} · ${short(m.tokens)} tokens" data-mission="${m.id}"><span class="wf-colbar" style="height:${Math.max(1, m.score)}%"></span></span>`).join("")}</div></div></div>
      <div class="wf-xaxis faint small"><span>#${t[0]?.id ?? ""}</span><span>#${t.at(-1)?.id ?? ""}</span></div>
      <details class="wf-tableview"><summary class="faint small">Show as a table</summary><table class="wf-table"><thead><tr><th>Mission</th><th class="num">Score</th><th>Verdict</th><th class="num">Tokens</th></tr></thead><tbody>${t.map(m => `<tr><td>#${m.id}</td><td class="num">${m.score}</td><td>${m.verdict}</td><td class="num">${short(m.tokens)}</td></tr>`).join("")}</tbody></table></details></div>`;
  }
  function categoryChart() {
    const rows = Object.entries(metrics.categories).sort((a, b) => b[1] - a[1]);
    const max = Math.max(1, ...rows.map(r => r[1]));
    return `<div class="wf-card"><h3 class="wf-h">${icon("alert")}Why work failed <span class="faint">first attempts the evaluator failed, by category</span></h3>
      ${rows.length ? `<ul class="wf-hbars">${rows.map(([k, n]) => `<li tabindex="0" data-tip="${n}|${esc(CAT[k] || k)}"><span class="wf-hbar-l">${esc(CAT[k] || k)}</span><span class="wf-hbar-t"><span style="width:${n / max * 100}%"></span></span><b>${n}</b></li>`).join("")}</ul>`
        : `<p class="faint small">No failed first attempts yet.</p>`}</div>`;
  }
  function tip(e) {
    const el = e.target.closest?.("[data-tip]");
    let box = $("#wf-tip");
    if (!el || !root().contains(el)) { if (box) box.hidden = true; return; }
    if (!box) { box = document.createElement("div"); box.id = "wf-tip"; box.className = "wf-tip"; box.setAttribute("role", "tooltip"); document.body.append(box); }
    const [v, l] = el.dataset.tip.split("|");
    const b = document.createElement("b"); b.textContent = v;
    const s = document.createElement("span"); s.textContent = l || "";
    box.replaceChildren(b, s); box.hidden = false;
    const r = el.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
    box.style.top = `${r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8}px`;
  }

  // ---------- improvement ----------
  function improve() {
    if (!imps) return Loading.line("Reading the proposals…");
    const [l, desc] = MODES[imps.mode] || [imps.mode, ""];
    return `<div class="wf-card wf-intro"><div><h3 class="wf-h">${icon("sprout")}Bounded self-improvement</h3>
        <p>When work still fails after rework, ${esc(agent("improvement-engineer").name)} diagnoses the root cause in the agent's instructions and proposes a new version. A test re-runs the failed assignment with the current and the new version (same model, same inputs, nothing written to the mission) and ${esc(agent("chief-evaluator").name)} scores each output blind. Only a version that measured better can be promoted, and only by you; every version stays and can be restored from Org.</p></div>
        <div class="wf-intro-r"><span class="faint small">Mode</span><b>${esc(l)}</b><small class="faint">${esc(desc)}</small><button type="button" class="linkbtn" data-wftab="settings">Change in Settings</button></div></div>
      ${imps.improvements.length ? imps.improvements.map(impCard).join("") : `<div class="wf-card"><p class="faint">No proposals yet. They appear after a mission whose work failed even after rework.</p></div>`}`;
  }
  function impCard(i) {
    const [tone, l] = IMP[i.status] || ["wait", i.status];
    const g = { name: i.name || "Removed agent", title: i.title || "", icon: i.icon || "bot", color: i.color || "slate" };
    const mean = xs => xs.length ? xs.reduce((s, x) => s + x.score, 0) / xs.length : null;
    const row = (label, xs) => `<div class="wf-trial"><span>${label}</span><span class="wf-pills">${xs.map(x => `<span class="wf-pill t-${x.verdict === "pass" ? "ok" : "bad"}" title="${esc(x.note)}">${icon(x.verdict === "pass" ? "check" : "close")}${x.score}</span>`).join("") || `<span class="faint small">${i.status === "testing" ? "running…" : "—"}</span>`}</span>${xs.length ? `<b>${fmtNum(mean(xs), 0)}</b>` : "<b></b>"}</div>`;
    return `<div class="wf-card wf-imp" data-imp="${i.id}"><div class="wf-imp-h">${av(g)}<div><b>${esc(g.name)}: v${i.base_version} → v${i.base_version + 1}</b>
        <small class="faint">${esc(g.title)} · from ${i.mission_title ? `<button type="button" class="linkbtn" data-open-mission="${i.mission_id}">${esc(i.mission_title)}</button>` : "a deleted mission"}${i.assignment_seq ? `, assignment ${i.assignment_seq}` : ""} · <time data-ts="${i.created}">${ago(i.created)}</time></small></div>${chip(tone, l)}</div>
      <dl class="wf-dl"><dt>What failed</dt><dd>${esc(CAT[i.category] || i.category || "—")}${i.eval_note ? `: ${esc(i.eval_note)}` : ""}</dd><dt>Root cause</dt><dd>${esc(i.root_cause)}</dd><dt>The change</dt><dd>${esc(i.change)}</dd></dl>
      ${i.baseline.length || i.candidate.length || i.status === "testing" ? `<div class="wf-trials">${row(`Current v${i.base_version}`, i.baseline)}${row(`Candidate v${i.base_version + 1}`, i.candidate)}</div>` : ""}
      ${i.result ? `<p class="wf-result">${esc(i.result)}</p>` : ""}
      <div class="wf-row"><button type="button" class="btn sm" data-impact="diff">${icon("columns")}Compare instructions</button>
        ${["proposed", "not_better", "failed"].includes(i.status) ? `<select name="trials" aria-label="Trials">${[1, 2, 3].map(n => `<option value="${n}">${plural(n, "trial")} each</option>`).join("")}</select><button type="button" class="btn sm" data-impact="test">${icon("play")}Test it</button>` : ""}
        ${i.status === "testing" ? `<button type="button" class="btn sm" data-impact="cancel">${icon("stop")}Stop the test</button>` : ""}
        ${i.status === "better" ? `<button type="button" class="btn sm primary" data-impact="promote">${icon("check")}Promote to v${i.base_version + 1}</button>` : ""}
        ${!["testing", "promoted", "rejected"].includes(i.status) ? `<button type="button" class="btn sm danger-text" data-impact="reject">Reject</button>` : ""}
        ${i.status === "promoted" ? `<span class="faint small">${esc(g.name)} runs on v${i.version} since ${esc(i.decided_by || "you")} promoted it.</span>` : ""}</div></div>`;
  }
  function diffWords(a, b) {
    const A = a.split(/(\s+)/), B = b.split(/(\s+)/), n = A.length, m = B.length;
    if (n * m > 600000) return `<del>${esc(a)}</del> <ins>${esc(b)}</ins>`;
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    let i = 0, j = 0, out = "";
    while (i < n && j < m) {
      if (A[i] === B[j]) { out += esc(A[i]); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) out += `<del>${esc(A[i++])}</del>`;
      else out += `<ins>${esc(B[j++])}</ins>`;
    }
    while (i < n) out += `<del>${esc(A[i++])}</del>`;
    while (j < m) out += `<ins>${esc(B[j++])}</ins>`;
    return out;
  }
  async function impAction(id, act, btn) {
    const i = imps.improvements.find(x => x.id === id);
    if (act === "diff") {
      const dlg = dialog("wf-diff", "wide");
      dlg.innerHTML = `<div class="wf-dlg">${closeBtn}<h3>${icon("columns")}${esc(i.name || "")}: v${i.base_version} → v${i.base_version + 1}</h3><p class="faint small">${esc(i.change)}</p>
        <div class="wf-diff"><div><h4 class="wf-h4">Changes</h4><p class="wf-difftext">${diffWords(i.current || "", i.instructions || "")}</p></div>
        <div><h4 class="wf-h4">Candidate v${i.base_version + 1} in full</h4><p class="wf-difftext">${esc(i.instructions)}</p></div></div></div>`;
      return dlg.showModal();
    }
    if (act === "promote" && !(await UI.confirm({ title: `Promote ${esc(i.name)} to v${i.base_version + 1}?`, body: "It runs on the new instructions from the next mission. You can restore v" + i.base_version + " any time in Org.", ok: "Promote", icon: "check", danger: false }))) return;
    btn.disabled = true;
    try {
      if (act === "test") imps = await api(`/api/workforce/improvements/${id}/test`, { method: "POST", body: { trials: +$("[name=trials]", btn.closest("[data-imp]")).value } });
      else imps = await api(`/api/workforce/improvements/${id}`, { method: "POST", body: { decision: act } });
      Auth.toast({ test: "Testing: both versions run, scored blind", promote: "Promoted", reject: "Rejected", cancel: "Stopping the test" }[act]);
      home = await api("/api/workforce");
    } catch (e) { err(e); }
    render();
    if (act === "test") pollImps();
  }
  let impTimer = null;
  function pollImps() {
    clearTimeout(impTimer);
    impTimer = setTimeout(async () => {
      if (!shown() || tab !== "improve") return;
      try { imps = await api("/api/workforce/improvements"); render(); } catch { return; }
      if (imps.improvements.some(x => x.status === "testing")) pollImps(); else { home = await api("/api/workforce").catch(() => home); render(); }
    }, 2500);
  }

  // ---------- benchmarks ----------
  function benchTab() {
    if (!benches) return Loading.line("Reading the benchmarks…");
    return `<div class="wf-card wf-intro"><div><h3 class="wf-h">${icon("trophy")}Does the workforce beat one agent?</h3>
        <p>A benchmark re-runs a finished mission's goal and success criteria in arms, a few trials each, interleaved so changing data hits every arm alike. Memory writes are off and one evaluator model scores every run, so the arms differ only in how the work is organised. Compare the full workforce with one agent alone (more agents should earn their tokens), with no red team or fact check, with no memory, with one fixed model instead of the router, or with a debate (the other arms run without one).</p></div>
        <div class="wf-intro-r"><button type="button" class="btn primary" data-wf="new-bench">${icon("plus")}New benchmark</button><small class="faint">One trial per arm is a hint; three start to show the spread.</small></div></div>
      ${benches.benchmarks.length ? benches.benchmarks.map(benchCard).join("") : `<div class="wf-card"><p class="faint">No benchmarks yet.</p></div>`}`;
  }
  function benchCard(b) {
    const [tone, l] = { running: ["run", "Running"], done: ["ok", "Done"], failed: ["bad", "Failed"], cancelled: ["off", "Cancelled"] }[b.status] || ["wait", b.status];
    const stats = b.arms.map(a => [a, b.stats[a]]);
    const best = stats.filter(([, s]) => s.finished).sort((x, y) => (y[1].pass_rate - x[1].pass_rate) || ((y[1].mean ?? 0) - (x[1].mean ?? 0)))[0]?.[0];
    const done = stats.reduce((n, [, s]) => n + s.runs, 0);
    const runs = benchRuns[b.id];
    return `<div class="wf-card" data-bench="${b.id}"><div class="wf-imp-h"><span class="av sm c-amber" aria-hidden="true">${icon("trophy")}</span><div><b>${esc(b.title)}</b><small class="faint">${b.arms.map(a => esc(benches.arms[a] || a)).join(" vs ")} · ${plural(b.trials, "trial")} each · scored on ${esc((b.eval_model || "").split(":").pop())} · <time data-ts="${b.created}">${ago(b.created)}</time></small></div>
        ${chip(tone, b.status === "running" ? `Running ${done} of ${b.planned}` : l)}</div>
      ${b.error ? `<p class="wf-error">${icon("alert")}${esc(b.error)}</p>` : ""}
      <div class="wf-scroll"><table class="wf-table"><thead><tr><th>Arm</th><th class="num">Runs</th><th>Pass rate, 95% interval</th><th class="num">Score ± sd</th><th class="num">Tokens per success</th><th class="num">Median time</th></tr></thead>
        <tbody>${stats.map(([a, s]) => `<tr class="${a === best && b.status !== "running" ? "on" : ""}"><td><b>${esc(benches.arms[a] || a)}</b>${a === best && b.status !== "running" ? ` ${chip("ok", "best")}` : ""}</td><td class="num">${s.finished}/${b.trials}</td>
          <td>${s.pass_rate != null ? `<span class="wf-ci" title="${pctf(s.ci?.[0])} to ${pctf(s.ci?.[1])}"><span class="wf-ci-t"><i style="left:${(s.ci?.[0] || 0) * 100}%;width:${((s.ci?.[1] || 0) - (s.ci?.[0] || 0)) * 100}%"></i><b style="left:${s.pass_rate * 100}%"></b></span>${pctf(s.pass_rate)} <span class="faint">${pctf(s.ci?.[0])}–${pctf(s.ci?.[1])}</span></span>` : "–"}</td>
          <td class="num">${s.mean != null ? `${fmtNum(s.mean, 0)}${s.sd != null ? ` ± ${fmtNum(s.sd, 0)}` : ""}` : "–"}</td><td class="num">${s.per_success ? short(s.per_success) : "–"}</td><td class="num">${dur(s.p50)}</td></tr>`).join("")}</tbody></table></div>
      <div class="wf-row">${runs ? "" : `<button type="button" class="btn sm" data-benchruns="${b.id}">${icon("list")}Show the runs</button>`}
        ${b.status === "running" ? `<button type="button" class="btn sm" data-benchact="cancel">${icon("stop")}Cancel</button>` : `<button type="button" class="btn sm danger-text" data-benchact="delete">Delete</button>`}</div>
      ${runs ? `<div class="wf-chips">${runs.map(r => `<button type="button" class="chip" data-mission="${r.id}">${esc(benches.arms[r.arm] || r.arm)} #${r.trial}: ${r.status === "done" ? `${r.score ?? "–"} ${r.verdict || ""}` : esc(r.status)}</button>`).join("")}</div>` : ""}</div>`;
  }
  function benchDialog(missionId) {
    const done = home.missions.filter(m => m.status === "done");
    if (!done.length) return Auth.toast("Finish a mission first: a benchmark re-runs a finished mission.");
    const dlg = dialog("wf-bench", "wide"), pool = home.settings.pool;
    dlg.innerHTML = `<form class="wf-dlg">${closeBtn}<h3>${icon("trophy")}New benchmark</h3>
      <label class="wf-field"><span>Mission to re-run</span><select name="mission">${done.map(m => `<option value="${m.id}" data-tokens="${m.tokens}" ${m.id === missionId ? "selected" : ""}>#${m.id} ${esc(m.title)}</option>`).join("")}</select></label>
      <fieldset class="wf-field"><legend>Arms <em class="faint">2 to 4</em></legend><div class="wf-tools">${Object.entries(home.arms).map(([k, l]) => `<label class="chk"><input type="checkbox" name="arm" value="${k}" ${["team", "solo"].includes(k) ? "checked" : ""} ${k === "fixed_model" && !pool ? "disabled" : ""}>${esc(l)}${k === "fixed_model" && !pool ? ` <em class="faint">(needs a model pool)</em>` : ""}</label>`).join("")}</div></fieldset>
      <label class="wf-field"><span>Trials per arm</span><select name="trials"><option value="1">1</option><option value="2">2</option><option value="3" selected>3</option></select></label>
      <p class="faint small" data-estimate></p>
      <div class="wf-row end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">${icon("play")}Start</button></div></form>`;
    const f = $("form", dlg);
    const estimate = () => { const t = +f.mission.selectedOptions[0].dataset.tokens, n = $$("[name=arm]:checked", f).length * +f.trials.value;
      $("[data-estimate]", f).textContent = `${n} runs. The original took ${fmtNum(t, 0)} tokens, so expect around ${short(t * n)} in all (a solo run costs much less). Each run keeps its own budget.`; };
    estimate(); dlg.showModal();
    dlg.onchange = estimate;
    dlg.onsubmit = async e => {
      e.preventDefault();
      const arms = $$("[name=arm]:checked", f).map(x => x.value);
      if (arms.length < 2 || arms.length > 4) return Auth.toast("Pick 2 to 4 arms.");
      try { await api("/api/workforce/benchmarks", { method: "POST", body: { mission: +f.mission.value, arms, trials: +f.trials.value } }); dlg.close(); Auth.toast("Benchmark started");
        benches = null; setTab("bench"); pollBench(); }
      catch (e2) { err(e2); }
    };
  }
  let benchTimer = null;
  function pollBench() {
    clearTimeout(benchTimer);
    benchTimer = setTimeout(async () => {
      if (!shown() || tab !== "bench") return;
      try { benches = await api("/api/workforce/benchmarks"); for (const id of Object.keys(benchRuns)) benchRuns[id] = (await api(`/api/workforce/benchmarks/${id}`)).runs; render(); } catch { return; }
      if (benches.benchmarks.some(b => b.status === "running")) pollBench();
    }, 3000);
  }

  // ---------- settings ----------
  function loadModels() {
    api("/api/agents/models").then(m => { models = m; if (tab === "settings") { const f = $("form[data-form=settings]", root()); if (!f?.dataset.dirty) render(); } }).catch(() => { models = { providers: [], default: null }; });
  }
  const modelOptions = (cur, auto) => {
    const known = (models?.providers || []).flatMap(p => p.models.map(m => m.id));
    return [auto ? `<option value="auto" ${cur === "auto" ? "selected" : ""}>Auto (the default model${models?.default ? `: ${esc(models.default.split(":").pop())}` : ""})</option>` : "",
      cur && cur !== "auto" && !known.includes(cur) ? `<option value="${esc(cur)}" selected>${esc(cur)}</option>` : "",
      ...(models?.providers || []).filter(p => p.models.length).map(p => `<optgroup label="${esc(p.label)}">${p.models.map(m => `<option value="${esc(m.id)}" ${cur === m.id ? "selected" : ""}>${esc(m.label || m.id)}</option>`).join("")}</optgroup>`)].join("");
  };
  const poolRow = p => `<div class="wf-pool-row" data-pool-row><select name="pmodel" aria-label="Model">${p ? "" : `<option value="">Pick a model…</option>`}${modelOptions(p?.model, false)}</select>
    <select name="ptier" aria-label="Tier"><option value="">Tier: auto</option>${[[1, "1 · light"], [2, "2 · strong"], [3, "3 · frontier"]].map(([v, l]) => `<option value="${v}" ${p?.set_tier === v ? "selected" : ""}>${l}</option>`).join("")}</select>
    <label class="wf-price"><span>$</span><input name="pprice" type="number" min="0" max="500" step="0.01" placeholder="auto" value="${p?.set_price ?? ""}" aria-label="Dollars per million tokens"><span class="faint small">/ M tokens</span></label>
    ${p ? `<span class="faint small">now tier ${p.tier}, $${fmtNum(p.price, 2)}</span>` : "<span></span>"}<button type="button" class="iconbtn" data-pool-rm aria-label="Remove">${icon("trash")}</button></div>`;
  function settingsTab() {
    if (!settings) return Loading.line("Reading the settings…");
    const s = settings.settings, raw = s.pool;
    const sw = (name, label, hint) => `<label class="wf-switch-row"><span><b>${label}</b><small>${hint}</small></span><span class="switch"><input type="checkbox" name="${name}" ${s[name] ? "checked" : ""}><span></span></span></label>`;
    return `<form class="wf-settings" data-form="settings">
      <div class="wf-card"><h3 class="wf-h">${icon("route")}Model pool and router</h3>
        <p class="faint small">With two or more models in the pool, every call goes to the model with the best S = wq·Q − wc·C − wl·L − wr·R for its task: Q is the evaluator's average score for that model on that kind of task (a tier's prior until there are scores), C the expected cost of a call, L its latency, R its failure rate. Planning, red-teaming, evaluating and the report need tier 2 or above. Leave the pool empty to run everything on one model.</p>
        <p class="faint small"><strong>Shared with every agent system.</strong> This pool and the weights also route Mission OS, the Company, Competition teams, subnets in My subnets, the project team and Long tasks whenever they are set to Auto. Each learns its own best model per kind of work from its runs. A model picked for a team, an agent or a task always runs as picked.</p>
        <div class="wf-pool">${raw.map(p => poolRow(p)).join("")}</div><button type="button" class="btn sm" data-pool-add>${icon("plus")}Add a model</button>
        <fieldset class="wf-field wf-mt"><legend>Weights</legend><div class="wf-modes">${Object.entries(WEIGHTS).map(([k, [l, h]]) => `<label class="wf-modecard"><input type="radio" name="weights" value="${k}" ${s.weights === k ? "checked" : ""}><span><b>${l}</b><small>${h}</small></span></label>`).join("")}</div></fieldset>
        ${sw("independent", "Independent evaluator", "The evaluator and the red teamer run on another model than the work they review, when the pool has one.")}
        <label class="wf-field"><span>Model without a pool</span><select name="model">${modelOptions(s.model, true)}</select></label>
        ${settings.preview.length ? `<h4 class="wf-h4">What the router would pick now</h4><div class="wf-scroll"><table class="wf-table"><thead><tr><th>Task</th><th>Model</th><th>Why</th></tr></thead><tbody>${settings.preview.map(p => `<tr><td>${esc(p.task)}</td><td class="wf-mono">${esc((p.model || "–").split(":").pop())}</td><td class="small">${esc(p.reason)}</td></tr>`).join("")}</tbody></table></div>` : ""}</div>
      <div class="wf-card"><h3 class="wf-h">${icon("target")}Mission defaults <span class="faint">each new mission starts from these; you can change them per mission</span></h3>
        <label class="wf-field"><span>Token budget</span><select name="budget">${settings.budgets.map(b => `<option value="${b}" ${b === s.budget ? "selected" : ""}>${fmtNum(b, 0)}</option>`).join("")}</select></label>
        <div class="wf-switches">${sw("approve_plan", "Approve the plan first", "Missions wait for you after planning.")}${sw("critic", "Red-team review", "Challenges the claims before scoring.")}
          ${sw("fact_check", "Fact check", "Re-checks the key findings with fresh lookups.")}${sw("rework", "Rework failures", "Failed work gets one more attempt.")}${sw("memory", "Memory", "Recall what earlier missions verified, and learn.")}
          ${sw("debate", "Debate", "Authors whose deliverables disagree argue it out before scoring. Needs a 150,000+ budget.")}</div></div>
      <div class="wf-card"><h3 class="wf-h">${icon("sprout")}Self-improvement</h3><div class="wf-modes">${Object.entries(MODES).map(([k, [l, h]]) => `<label class="wf-modecard"><input type="radio" name="improve" value="${k}" ${s.improve === k ? "checked" : ""}><span><b>${l}</b><small>${h}</small></span></label>`).join("")}</div></div>
      <div class="wf-row end wf-sticky"><button type="submit" class="btn primary">${icon("check")}Save settings</button></div></form>`;
  }
  async function saveSettings(f) {
    const pool = $$("[data-pool-row]", f).map(r => ({ model: $("[name=pmodel]", r).value, tier: $("[name=ptier]", r).value ? +$("[name=ptier]", r).value : null,
      price: $("[name=pprice]", r).value !== "" ? +$("[name=pprice]", r).value : null })).filter(p => p.model);
    const body = { pool, weights: f.weights.value, improve: f.improve.value, budget: +f.budget.value, model: f.model.value,
      ...Object.fromEntries(["independent", "approve_plan", "critic", "fact_check", "rework", "memory", "debate"].map(k => [k, f[k].checked])) };
    try { settings = await api("/api/workforce/settings", { method: "PUT", body });
      home = await api("/api/workforce"); Auth.toast("Settings saved"); delete f.dataset.dirty; render(); }
    catch (e) { err(e); }
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    root().addEventListener("click", async e => {
      const t = e.target;
      const tb = t.closest("[data-wftab]"); if (tb) return setTab(tb.dataset.wftab);
      const mr = t.closest("[data-mission]"); if (mr) return select(+mr.dataset.mission);
      const om = t.closest("[data-open-mission]"); if (om) return select(+om.dataset.openMission);
      const as = t.closest("[data-asg]"); if (as) return asgDialog(+as.dataset.asg);
      const tr = t.closest("[data-trace]"); if (tr) return traceDialog(+tr.dataset.trace);
      const ag = t.closest("[data-agent]"); if (ag) return agentDialog(ag.dataset.agent);
      const hi = t.closest("[data-hire]"); if (hi) return hireDialog(hi.dataset.hire);
      const bk = t.closest("[data-board]"); if (bk) { boardKind = bk.dataset.board; return render(); }
      const dc = t.closest("[data-decide]"); if (dc) { if (await decideAction(dc)) refresh(); return; }
      const mk = t.closest("[data-memkind]"); if (mk) { memKind = mk.dataset.memkind; return render(); }
      const ma = t.closest("[data-memact]"); if (ma) return memAction(+ma.closest("[data-mem]").dataset.mem, ma.dataset.memact);
      const ia = t.closest("[data-impact]"); if (ia) return impAction(+ia.closest("[data-imp]").dataset.imp, ia.dataset.impact, ia);
      const ex = t.closest("[data-example]"); if (ex) return newMission({ goal: ex.dataset.example });
      const brn = t.closest("[data-benchruns]"); if (brn) { try { benchRuns[brn.dataset.benchruns] = (await api(`/api/workforce/benchmarks/${brn.dataset.benchruns}`)).runs; } catch (e2) { err(e2); } return render(); }
      const ba = t.closest("[data-benchact]");
      if (ba) {
        const id = ba.closest("[data-bench]").dataset.bench;
        if (ba.dataset.benchact === "delete" && !(await UI.confirm({ title: "Delete this benchmark?", body: "Its runs go with it.", ok: "Delete" }))) return;
        try { await api(`/api/workforce/benchmarks/${id}${ba.dataset.benchact === "cancel" ? "/cancel" : ""}`, { method: ba.dataset.benchact === "cancel" ? "POST" : "DELETE" }); } catch (e2) { return err(e2); }
        delete benchRuns[id]; benches = await api("/api/workforce/benchmarks").catch(() => benches); return render();
      }
      if (t.closest("[data-pool-rm]")) { t.closest("[data-pool-row]").remove(); t.closest("form")?.setAttribute("data-dirty", "1"); return; }
      if (t.closest("[data-pool-add]")) { $(".wf-pool", root()).insertAdjacentHTML("beforeend", poolRow(null)); t.closest("form")?.setAttribute("data-dirty", "1"); return; }
      const b = t.closest("[data-wf]"); if (!b) return;
      const k = b.dataset.wf;
      if (k === "new") return newMission();
      if (k === "approvals") return approvalsDialog();
      if (k === "new-bench") return benchDialog();
      if (k === "benchmark") return benchDialog(mid);
      if (k === "edit-plan") return editPlan();
      if (k === "cancel") { b.disabled = true; try { d = await api(`/api/workforce/missions/${mid}/cancel`, { method: "POST" }); Auth.toast("Stopping after the call it's on"); render(); } catch (e2) { err(e2); } return; }
      if (k === "rerun" || k === "follow") {
        b.disabled = true;
        try { const r = await api(`/api/workforce/missions/${mid}/${k === "rerun" ? "rerun" : "follow-up"}`, { method: "POST" }); home = await api("/api/workforce"); Auth.toast("Mission started"); return select(r.id); }
        catch (e2) { err(e2); b.disabled = false; } return;
      }
      if (k === "delete") {
        const m = d.mission;
        if (!(await UI.confirm({ title: `Delete “${esc(m.title)}”?`, body: "Its plan, work, blackboard, proposals and traces go too. Memories it taught stay.", ok: "Delete" }))) return;
        try { await api(`/api/workforce/missions/${mid}`, { method: "DELETE" }); Auth.toast("Mission deleted"); home = await api("/api/workforce"); mid = home.missions[0]?.id ?? null; store.set("wf.mid", mid); d = null;
          if (mid) return select(mid); render(); follow(); } catch (e2) { err(e2); } return;
      }
      if (["approve", "send-back", "reject"].includes(k)) {
        const box = $(".wf-plan", root()), note = $("[name=note]", box)?.value.trim() || "";
        if (k === "send-back" && !note) { Auth.toast("Write what to change in your note first."); return $("[name=note]", box)?.focus(); }
        if (k === "reject" && !(await UI.confirm({ title: "Reject the plan and close the mission?", body: "Nothing more runs. To have it planned again, send it back with a note instead.", ok: "Reject the plan", icon: "close" }))) return;
        b.disabled = true;
        try { d = await api(`/api/workforce/missions/${mid}/plan`, { method: "POST", body: { approve: k === "approve", note: k === "reject" ? "" : note } });
          Auth.toast({ approve: "Plan approved: the leads are delegating", "send-back": "Sent back: planning again", reject: "Plan rejected" }[k]); home = await api("/api/workforce"); render(); }
        catch (e2) { err(e2); b.disabled = false; }
      }
    });
    root().addEventListener("input", e => {
      if (e.target.closest("[data-keep]")) e.target.dataset.dirty = "1";
      if (e.target.closest("form[data-form=settings]")) e.target.closest("form").dataset.dirty = "1";
      if (e.target.matches("[data-memq]")) { memQ = e.target.value; const pos = e.target.selectionStart; render(); const i = $("[data-memq]", root()); if (i) { i.focus(); i.setSelectionRange(pos, pos); } }
    });
    root().addEventListener("change", e => { if (e.target.closest("form[data-form=settings]")) e.target.closest("form").dataset.dirty = "1"; });
    root().addEventListener("submit", async e => {
      e.preventDefault();
      const f = e.target, btn = $("[type=submit]", f);
      if (btn) btn.disabled = true;
      if (f.dataset.form === "teach") {
        try { const el = f.elements; memory = await api("/api/workforce/memory", { method: "POST", body: { kind: el.kind.value, text: el.text.value.trim(), team: el.team.value, tags: [] } }); el.text.value = ""; delete el.text.dataset.dirty; Auth.toast("The workforce will remember that"); render(); }
        catch (e2) { err(e2); }
      }
      if (f.dataset.form === "settings") await saveSettings(f);
      if (btn) btn.disabled = false;
    });
    for (const ev of ["pointerover", "focusin"]) root().addEventListener(ev, tip);
    for (const ev of ["pointerout", "focusout"]) root().addEventListener(ev, e => { if (!e.relatedTarget?.closest?.("[data-tip]")) { const b = $("#wf-tip"); if (b) b.hidden = true; } });
  }

  // ---------- the sidebar's count: plans, proposals and promotable improvements waiting for you ----------
  function badge(n) {
    const c = $("#c-workforce"); if (!c) return;
    if (n == null && home) n = home.pending.actions + home.pending.plans + home.pending.improvements;
    c.textContent = n || "";
  }
  let polling = false;
  function init() {
    if (polling || !Auth.me() || !$("#c-workforce")) return;
    polling = true;
    const tick = () => { if ($("#nav-workforce")?.hidden || document.visibilityState !== "visible") return; api("/api/workforce/badge").then(b => badge(b.waiting)).catch(() => {}); };
    setTimeout(tick, 1800); setInterval(tick, 60000);
  }

  return { open, stop, init };
})();
