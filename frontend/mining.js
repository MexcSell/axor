/* My subnets (mining.py): a team of agents per subnet competition that watches the competition, tracks your miners and plans
   the climb. Your campaigns sit in a row of chips (one per subnet competition), with New campaign beside them; on a subnet that
   runs several competitions a strip below switches between them (or puts a team on one that has none). A campaign has six tabs:
   Overview (the Captain's brief, actions and tasks waiting for you, recommendations, alerts, asking the team), Competition
   (field trends, the reward curve, Ellis's analysis, the leaderboard, operators, movers and churn), Teams (the control room for the
   campaign's competition teams: autopilot, pause, stop, budgets, Import competitions; the teams work on the Competition teams page,
   mining-work.js), My miners (each miner's
   rewards and rank against your goal, its neighbours, Finley's diagnosis), Team (the workflow as a live diagram (mining-flow.js)
   with run, stop, pause and per-step controls, Quinn's commits to your repository, the last cycles as a grid, directives,
   model use), Activity (the live feed and every run's trace: each model and tool call with its input,
   output, tokens and time) and Settings. While the page is open it follows the campaign over server-sent events.
   Command center, first in the row of campaigns, shows the division's control room instead (mining-command.js). */
// Deterministic readiness comes from the latest chain snapshot, never from a brief
// or a user marking a manual action done. Kept pure for regression coverage.
const MiningReadiness = (state, now = Date.now() / 1000) => {
  const keys = state.campaign.keys || [], miners = state.mine || [], missing = state.missing || [];
  const sampled = state.schedule.last_sample;
  const stale = !!sampled && now - sampled > Math.max(120, (state.schedule.interval || 1800) * 2);
  const base = { stale, sampled, miners, missing, tone: "warn", go: "mine" };
  if (!keys.length) return { ...base, title: "Add your miner keys", detail: "Track a public hotkey or coldkey to verify registration and earnings.", action: "Add keys", go: "settings" };
  if (!state.field || !sampled) return { ...base, title: "Registration not checked", detail: "No chain snapshot is available. A completed task does not verify registration.", action: "Check snapshot", go: "activity" };
  if (stale) return { ...base, title: "Chain data is out of date", detail: "Refresh the snapshot before relying on registration, rank or earnings.", action: "Inspect snapshot activity", go: "activity" };
  if (!miners.length) return { ...base, tone: "bad", title: "No registered miner found", detail: "The latest snapshot has no UID matching your tracked keys. Check the keys and registration evidence before registering again.", action: "Inspect tracked miners" };
  if (missing.length) return { ...base, title: "Some tracked keys have no miner", detail: "At least one tracked key has no UID in the latest snapshot. Review the missing keys.", action: "Review tracked keys" };
  const critical = (state.alerts || []).filter(a => a.level === "critical").length;
  if (critical) return { ...base, tone: "bad", title: "Critical alerts need attention", detail: `${critical} critical alert${critical === 1 ? "" : "s"} remain open. Inspect the miner evidence before continuing.`, action: "Inspect miners" };
  return { ...base, tone: "ok", title: "Registration verified", detail: `${miners.length} miner${miners.length === 1 ? "" : "s"} found in the latest chain snapshot. Benchmark and submission readiness are checked separately.`, action: "Review miner performance" };
};

const Mining = (() => {
  let home = null, cid = null, d = null, tab = null, wired = false;  // cid and tab come from store on first open: app.js (store) loads last
  let field = null, mine = null, runs = null, trace = null, briefs = null, models = null, es = null, sampleSeen = null, cycles = null, flowSeen = null;
  let fieldMech = null, pendingNew = null;  // the Competition tab's sub-tab ("all", a mech, or null: the team's own); a new team asked for from the Explorer
  let cmd = null;  // the Command center (mining-command.js) shows instead of a campaign
  const xcomps = {}, xsel = {};  // the Explorer's competitions card: what each subnet runs, and the tab picked
  let days = 7, who = "", query = "", showAll = false, dismissing = null, timer = null;
  const root = () => $("#mining");
  const err = e => e && e.message !== "cancelled" && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 1)}k` : fmtNum(n || 0, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const hk = k => k && k.length > 12 ? `${k.slice(0, 6)}…${k.slice(-4)}` : k || "";
  const tau = v => v == null ? "–" : `${fmtNum(v)} τ`;
  const dur = s => s < 1 ? `${Math.round(s * 1000)} ms` : s < 60 ? `${fmtNum(s, 1)} s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  const hours = h => h == null ? "–" : h < 48 ? `${fmtNum(h, h < 10 ? 1 : 0)} h` : `${fmtNum(h / 24, 1)} d`;
  const when = ts => ts > Date.now() / 1000 - 86400 ? clock(ts) : new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + clock(ts);
  const STAFF = () => Object.fromEntries((d?.staff || home?.staff || []).map(a => [a.id, a]));
  const av = (a, size = "sm") => a ? `<span class="av ${size} c-${a.color}" aria-hidden="true">${icon(a.icon)}</span>` : `<span class="av ${size} c-slate">${icon("bot")}</span>`;
  const STATE = { ok: ["ok", "Ready"], issues: ["bad", "Alerts open"], working: ["run", "Working…"], error: ["warn", "Had a problem"], off: ["off", "Off the team"],
    paused: ["off", "Paused"], nomodel: ["none", "Needs a model"], idle: ["wait", "Waiting for its first run"] };
  const STEPS = [["scout", "Snapshot"], ["analysis", "Analysis"], ["strategy", "Strategy"], ["brief", "Brief"]];
  const TONE = { green: ["ok", "On track"], amber: ["warn", "Needs a look"], red: ["bad", "Action needed"] };
  const MSTATUS = { at_goal: ["ok", "At your goal"], chasing: ["run", "Chasing"], at_risk: ["bad", "At risk"], immune: ["wait", "Immune"], idle: ["warn", "Earning nothing"] };
  const TRACK = { at_goal: ["ok", "At the goal"], on_track: ["ok", "On track"], at_risk: ["warn", "At risk"], losing: ["bad", "Losing ground"], not_registered: ["bad", "Not registered"], no_keys: ["off", "No keys"] };
  const AUTONOMY = {
    report: ["eye", "Recommend only", "The team analyses and recommends. No actions are proposed."],
    ask: ["hand", "Ask me", "Every action on your miner waits here for your approval; manual steps become tasks for you."],
    auto: ["zap", "Restart when down", "Avery may restart your miner on its own when Kit sees it down, at most once in 6 hours. Everything else still waits for you."]};
  const KIND_ICON = { start: "play", cycle: "cycle", sample: "radio", alert: "alert", news: "info", resolved: "check", tool: "search", report: "doc",
    plan: "target", propose: "wrench", approve: "check", escalate: "hand", reject: "ban", brief: "star", error: "alert", budget: "coins", nomodel: "info",
    early: "zap", ask: "chat", answer: "chat", feedback: "thumbup", decision: "hand", settings: "gear", roster: "users", cancel: "stop", skip: "info", fix: "check", saved: "commit" };
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;

  // ---------- loading ----------
  async function open() {
    wire();
    if (tab === null) { cid = store.get("mh.cid", null); tab = store.get("mh.tab", "overview"); cmd = store.get("mh.cmd", true); }
    if (!home) root().innerHTML = `<h1 class="page">My subnets</h1>${Loading.line("Calling the team in…")}`;
    try { home = await api("/api/mining"); }
    catch (e) { root().innerHTML = `<h1 class="page">My subnets</h1><div class="empty">${esc(e.message)}</div>`; return; }
    if (!home.campaigns.some(c => c.id === cid)) cid = home.campaigns[0]?.id ?? null;
    if (cid && !cmd) await select(cid, true); else render();
    if (pendingNew) { const p = pendingNew; pendingNew = null; newCampaign(p); }
  }
  function stop() { es?.close(); es = null; clearTimeout(timer); MiningCommand.stop(); }
  async function select(id, keepTab) {
    cid = id; store.set("mh.cid", id);
    if (!keepTab) tab = "overview";
    d = field = mine = runs = trace = briefs = cycles = null; sampleSeen = flowSeen = fieldMech = null;
    render();
    try { d = await api(`/api/mining/campaigns/${id}`); } catch (e) { err(e); return; }
    sampleSeen = d.schedule.last_sample; flowSeen = flowKey(d);
    render(); await loadTab(); follow();
  }
  function follow() {
    stop();
    if (!cid || cmd || $("#view-mining").hidden) return;
    es = new EventSource(`/api/mining/campaigns/${cid}/stream`);
    es.addEventListener("state", e => {
      const s = JSON.parse(e.data), seen = new Set((d?.events || []).map(x => x.id));
      const fresh = s.events.filter(x => !seen.has(x.id));
      d = { ...s, events: [...fresh, ...(d?.events || [])].slice(0, 250) };
      if (s.schedule.last_sample !== sampleSeen) { sampleSeen = s.schedule.last_sample; field = mine = null; if (["competition", "mine"].includes(tab)) loadTab(); }
      if (tab === "activity" && fresh.some(x => ["report", "plan", "brief", "answer", "error"].includes(x.kind))) runs = null, loadTab();
      if (flowKey(d) !== flowSeen) { flowSeen = flowKey(d); cycles = null; if (tab === "team") loadTab(); }
      live();
    });
    es.addEventListener("gone", () => { stop(); open(); });
    es.addEventListener("auth", stop);
    es.onerror = () => { es?.close(); es = null; clearTimeout(timer); timer = setTimeout(() => { if (!$("#view-mining").hidden) follow(); }, 5000); };
  }
  async function loadTab() {
    try {
      if (tab === "competition" && !field && fieldMech !== "all") field = await api(`/api/mining/campaigns/${cid}/field?days=${days}${fieldMech != null ? `&mech=${fieldMech}` : ""}`);
      if (tab === "mine" && !mine) { mine = await api(`/api/mining/campaigns/${cid}/mine?days=${days}`); }
      if (tab === "activity" && !runs) { runs = await api(`/api/mining/campaigns/${cid}/runs${who ? `?agent=${who}` : ""}`); }
      if (tab === "overview" && !briefs) briefs = await api(`/api/mining/campaigns/${cid}/briefs`);
      if (tab === "team" && !cycles) cycles = (await api(`/api/mining/campaigns/${cid}/cycles`)).cycles;
    } catch (e) { err(e); }
    render();
  }
  // the cycle grid reloads when a cycle starts or ends, or a step in it changes state
  const flowKey = s => s?.flow ? `${s.flow.cycle}:${s.flow.status}:${Object.values(s.flow.steps).map(x => x.status).join()}:${Object.values(s.flow.saved).map(x => x.status).join()}` : "";
  async function refresh() { if (cid) { d = await api(`/api/mining/campaigns/${cid}`).catch(e => (err(e), d)); live(); } }

  // ---------- frame ----------
  function render() {
    if (!home) return;
    if (!$(".mh-body", root())) root().innerHTML = `<div class="hq-top"><div><h1 class="page">My subnets</h1>
        <p class="lead">A team of agents per subnet: they take snapshots of the competition, track your miners, work out how to reach the top, and report to you. You steer them and approve what they do.</p></div>
        <div class="hq-actions mh-actions"></div></div>
      <div class="mh-camps"></div><div class="mh-comps-wrap"></div><div class="hq-run mh-run" hidden></div><div class="mh-tabs-wrap"></div><div class="mh-body"></div>`;
    put($(".mh-camps", root()), camps());
    if (cmd) {
      put($(".mh-comps-wrap", root()), ""); put($(".mh-actions", root()), ""); put($(".mh-tabs-wrap", root()), ""); $(".mh-run", root()).hidden = true;
      const body = $(".mh-body", root());
      if (!$("#mcx-host", body)) { body.innerHTML = `<div id="mcx-host"></div>`; body.dataset.html = ""; body.dataset.tab = "cmd"; }
      return MiningCommand.mount($("#mcx-host", body));
    }
    put($(".mh-comps-wrap", root()), cid && d ? comps() : "");
    if (!cid) { put($(".mh-actions", root()), ""); put($(".mh-tabs-wrap", root()), ""); $(".mh-run", root()).hidden = true; put($(".mh-body", root()), welcome()); return; }
    if (!d) { put($(".mh-body", root()), Loading.line("Opening the campaign…")); return; }
    put($(".mh-actions", root()), actions());
    const run = $(".mh-run", root());
    run.hidden = !d.running; put(run, d.running ? running() : "");
    const waiting = d.actions.filter(a => ["awaiting", "todo"].includes(a.status)).length;
    put($(".mh-tabs-wrap", root()), `<div class="seg hq-tabs" role="tablist">${[["overview", "Overview", "dash", waiting], ["competition", "Competition", "chart"], ["work", "Teams", "users", MiningWork.count(cid)],
      ["mine", "My miners", "pickaxe", d.alerts.filter(a => a.level === "critical").length], ["team", "Team", "users"], ["activity", "Activity", "list"], ["settings", "Settings", "gear"]]
      .map(([k, l, ic, n]) => `<button type="button" role="tab" data-mhtab="${k}" aria-pressed="${tab === k}">${icon(ic)}${l}${n ? `<span class="hq-n alert">${n}</span>` : ""}</button>`).join("")}</div>`);
    const body = $(".mh-body", root());
    if (tab === "settings" && body.dataset.tab === "settings" && body.dataset.cid === String(cid)) return;  // don't clobber edits
    body.dataset.tab = tab; body.dataset.cid = cid;
    // a live update mustn't eat what you're typing: a question, an instruction, why you dismiss something
    const typed = $$("form[data-ask] textarea, form[data-directive] textarea, form[data-dismiss] input", body).map(el => {
      const k = ["data-ask", "data-directive", "data-dismiss"].find(a => el.form.hasAttribute(a));
      return { sel: `form[${k}="${el.form.getAttribute(k)}"] [name="${el.name}"]`, value: el.value, focus: document.activeElement === el, a: el.selectionStart, b: el.selectionEnd };
    });
    put(body, { overview, competition, work: () => MiningWork.control(cid), mine: minersTab, team, activity, settings }[tab]());
    for (const t of typed) {
      const el = $(t.sel, body); if (!el || el.value === t.value) continue;
      el.value = t.value; if (t.focus) { el.focus(); el.setSelectionRange(t.a, t.b); }
    }
    if (tab === "competition") drawCompetition();
    if (tab === "mine") drawMine();
    if (tab === "overview" || tab === "activity") times();
  }
  // a stream update: only the parts that follow the team live
  function live() {
    if (!d || cmd || $("#view-mining").hidden) return;
    const c = home.campaigns.find(x => x.id === cid);
    if (c) { c.running = !!d.running; c.waiting = d.actions.filter(a => ["awaiting", "todo"].includes(a.status)).length; c.critical = d.alerts.filter(a => a.level === "critical").length; c.status = d.campaign.status; }
    if (["overview", "team", "activity"].includes(tab)) render();
    else { put($(".mh-camps", root()), camps()); put($(".mh-comps-wrap", root()), comps()); put($(".mh-actions", root()), actions()); const run = $(".mh-run", root()); run.hidden = !d.running; put(run, d.running ? running() : ""); }
    badge();
  }
  function times() { $$(".mh-body time[data-ts]", root()).forEach(t => { t.textContent = ago(+t.dataset.ts); }); }

  function camps() {
    return `<div class="mh-camp-row" role="tablist" aria-label="Campaigns"><button type="button" class="mh-camp mh-camp-cmd ${cmd ? "on" : ""}" data-mhcmd aria-pressed="${!!cmd}">${icon("dash")}<b>Command center</b></button>
      ${home.campaigns.map(c => `<button type="button" class="mh-camp ${c.id === cid && !cmd ? "on" : ""}" data-camp="${c.id}" aria-pressed="${c.id === cid && !cmd}">
        <span class="ci ci-${c.running ? "run" : c.status === "live" ? (c.critical ? "bad" : "ok") : "none"}"></span><b>SN${c.netuid}</b><span title="${esc(c.name)}">${esc(c.name)}</span>${c.mechs > 1 || c.mech ? `<span class="mh-camp-comp" title="${esc(c.comp)}">${esc(c.comp)}</span>` : ""}
        ${c.waiting ? `<span class="hq-n alert" title="Waiting for you">${c.waiting}</span>` : ""}</button>`).join("")}
      ${home.campaigns.length < home.limits.campaigns ? `<button type="button" class="btn sm" data-mh="new">${icon("plus")}New campaign</button>` : ""}</div>`;
  }

  // the subnet's competitions, when it runs more than one: each one's share of the rewards, where you stand, and its team
  function comps() {
    const list = d.competitions || [];
    if (list.length < 2) return "";
    return `<div class="mh-comps" role="group" aria-label="Competitions on SN${d.campaign.netuid}"><span class="mh-comps-h">${icon("columns")}SN${d.campaign.netuid} runs ${list.length} competitions <span class="faint">each ranks miners on its own and pays its share of the rewards</span></span>
      <div class="mh-comp-row">${list.map(x => { const on = x.mech === d.campaign.mech, team = x.campaign;
        return `<button type="button" class="mh-comp ${on ? "on" : ""} ${team ? "" : "none"}" ${team ? `data-camp="${team}"` : `data-mhclone="${x.mech}"`} aria-pressed="${on}">
          <span class="mh-comp-top"><b>${esc(x.name)}</b><span class="mh-comp-share" style="--w:${(x.share * 100).toFixed(1)}%"><i></i>${fmtNum(x.share * 100, 0)}%</span></span>
          <span class="mh-comp-meta">${x.rank ? `You #${x.rank} of ${x.miners}` : "You: not ranked"} · leader UID ${x.top1_uid ?? "–"} ${tau(x.top1)}/day</span>
          <span class="mh-comp-team">${team ? (on ? "This team" : "Open its team") : `${icon("plus")}Put a team on it`}</span></button>`; }).join("")}</div></div>`;
  }

  function actions() {
    const s = d.campaign.settings, sch = d.schedule, live = d.campaign.status === "live";
    const next = live ? `next snapshot ${sch.next_sample && sch.next_sample <= Date.now() / 1000 + 5 ? "now" : clock(sch.next_sample)} · cycle ~${when(sch.next_cycle)}` : "paused";
    return `<span class="hq-duty ${live ? "on" : "off"}"><span class="ci ${d.running ? "ci-run" : live ? "ci-none" : "ci-off"}"></span>${d.running ? "Analysis cycle running" : live ? "Monitoring scheduled" : "Paused"}<span class="faint">· ${next}</span></span>
      <span class="hq-mode" title="${esc(AUTONOMY[s.autonomy][2])}">${icon(AUTONOMY[s.autonomy][0])}${AUTONOMY[s.autonomy][1]}</span>
      ${d.running ? `<button type="button" class="btn" data-mh="cancel">${icon("stop")}Stop</button>` : ""}
      <button type="button" class="btn primary" data-mh="run" ${d.running || !live ? "disabled" : ""}>${icon(d.running ? "cycle" : "play")}${d.running ? "Working…" : "Run a cycle"}</button>`;
  }

  function running() {
    const r = d.running, at = STEPS.findIndex(([k]) => k === r.step), P = STAFF();
    const doing = Object.entries(r.activity || {}).map(([a, t]) => `<span class="mh-doing">${av(P[a], "xs")}<b>${esc(P[a]?.name || a)}</b> ${esc(t)}</span>`).join("");
    return `<div class="hq-steps">${STEPS.map(([k, l], i) => `<span class="${i < at ? "done" : i === at ? "now" : ""}">${i < at ? icon("check") : "<i></i>"}${l}</span>`).join("")}</div>
      <span class="mh-doing-row">${doing || `<span class="faint small">Started ${clock(r.started)}</span>`}</span>`;
  }

  // ---------- no campaign yet ----------
  function welcome() {
    const team = home.staff.map(a => `<li>${av(a)}<div><b>${esc(a.name)}</b> <span class="faint">${esc(a.title)}</span><p>${esc(a.job)}</p></div></li>`).join("");
    return `<section class="mh-welcome"><div><h2>Put a team on your subnet</h2>
        <p>Pick a subnet and the place you're aiming for, and add your miner's hotkey (or coldkey). Rio takes a snapshot of every miner on chain on a schedule, Kit alerts you when something needs you, and every few hours Ellis, Finley and Sage study the field, your miners and the plan. Avery sums it up for you.</p>
        <p class="faint small">Nothing is ever signed, registered or staked for you. ${home.model ? `Agents run on ${esc(home.model.split(":").pop())}; snapshots and alerts cost no tokens.` : "No model is connected yet: snapshots and alerts still work, and an administrator can connect a model in Agents → Models."}</p>
        <button type="button" class="btn primary" data-mh="new">${icon("plus")}New campaign</button></div>
      <ul class="mh-team-list">${team}</ul></section>`;
  }

  // ---------- overview ----------
  // the overview is a set of panels each viewer arranges (flex.js): presets from a command center to a quiet focus view
  const LAYOUTS = [
    { id: "command", label: "Command center", layout: { order: ["ticker", "waiting", "brief", "alerts", "recs", "activity", "ask", "done"], size: { ticker: 6, waiting: 6, brief: 4, alerts: 2, recs: 4, activity: 2, ask: 3, done: 3 }, density: "compact" } },
    { id: "classic", label: "Classic", layout: { order: ["brief", "waiting", "recs", "alerts", "done", "ask", "activity"], size: { brief: 6, waiting: 6, recs: 4, alerts: 2, done: 4, ask: 2, activity: 6 }, hide: ["ticker"] } },
    { id: "focus", label: "Focus", layout: { order: ["brief", "waiting", "recs"], size: { brief: 6, waiting: 6, recs: 6 }, hide: ["ticker", "alerts", "ask", "activity", "done"] } },
    { id: "watch", label: "Watch floor", layout: { order: ["ticker", "alerts", "activity", "waiting", "brief"], size: { ticker: 6, alerts: 3, activity: 3, waiting: 6, brief: 6 }, hide: ["recs", "ask", "done"], density: "compact" } }];
  // the Key numbers: a tile per figure (label, value, what it's measured against), tinted by how it stands
  function ticker() {
    const f = d.field, t = d.campaign.settings.target, sch = d.schedule, health = MiningReadiness(d);
    const best = (d.mine || []).reduce((a, m) => !a || m.rank < a.rank ? m : a, null);
    const st = { rank: best?.rank, uid: best?.uid, of: best?.of, gap: best?.gap_target,
      em: f ? (d.mine || []).reduce((sum, m) => sum + (m.em || 0), 0) : null };
    const crit = d.alerts.filter(a => a.level === "critical").length, waiting = d.actions.filter(a => ["awaiting", "todo"].includes(a.status)).length, teams = MiningWork.count(cid);
    const k = (l, v, sub, ic, tone = "", go = "") => `<${go ? `button type="button" data-mhgo="${go}"` : "div"} class="mh-kpi ${tone}">
      <span class="mh-kpi-l">${l}</span>${icon(ic)}<b>${v}</b><small>${sub}</small></${go ? "button" : "div"}>`;
    const keys = d.campaign.keys.length;
    return `<div class="mh-kpis" role="group" aria-label="Key numbers">
      ${k("Chain readiness", `<span class="mh-kpi-txt">${esc(health.title)}</span>`, sch.last_sample ? `Snapshot · ${clock(sch.last_sample)}` : "no snapshot yet", "shield", health.tone, health.go)}
      ${k("Best rank", st.rank ? `#${st.rank}` : "–", st.rank ? `of ${st.of} · goal top ${t}` : `goal top ${t}`, "trophy", st.rank && st.rank <= t ? "ok" : "", "mine")}
      ${k("Your τ/day", st.em != null ? fmtNum(st.em) : "–", st.rank ? `UID ${st.uid}` : "no ranked miner", "coins", "", "mine")}
      ${k(`Gap to top ${t}`, st.gap ? fmtNum(st.gap) : st.rank ? "0" : "–", st.gap ? "τ/day to close" : st.rank ? "inside the goal" : "not ranked yet", "target", st.gap ? "warn" : st.rank ? "ok" : "")}
      ${k("Top miner", f ? fmtNum(f.top1) : "–", f?.leader_uid != null ? `τ/day · UID ${f.leader_uid}` : "τ/day", "chart", "info", "competition")}
      ${k("Miners earning", f ? `${f.earners}<span class="mh-kpi-of">/${f.miners}</span>` : "–", f && f.miners ? `${Math.round(f.earners / f.miners * 100)}% of the field` : "no snapshot yet", "users", "", "competition")}
      ${k("Register", f ? fmtNum(f.reg_cost, 3) : "–", "τ for a UID now", "key")}
      ${k("Keys tracked", keys, keys ? "hotkeys and coldkeys" : "add them in Settings", "pickaxe", keys ? "" : "warn", keys ? "mine" : "settings")}
      ${k("Snapshot alerts", crit || d.alerts.length || "0", crit ? "critical" : d.alerts.length ? "open" : health.tone === "ok" ? "no open alerts" : "see readiness check", "shield", crit ? "bad" : d.alerts.length || health.tone !== "ok" ? "warn" : "", "mine")}
      ${k("Manual requests", waiting || "0", waiting ? "actions and tasks" : "no open requests", "hand", waiting ? "warn" : "")}
      ${k("Team requests", teams || "0", teams ? "waiting for review" : "open team controls for status", "rocket", teams ? "warn" : "", "work")}
      ${k(d.running ? "Cycle" : "Next cycle", d.running ? "Now" : sch.next_cycle ? clock(sch.next_cycle) : "–", d.running ? "the team is working" : "analysis, plan, brief", "cycle", d.running ? "run" : "")}</div>`;
  }
  function readiness() {
    const h = MiningReadiness(d), sampled = h.sampled ? `Snapshot ${when(h.sampled)}` : "No snapshot yet";
    return `<section class="mh-readiness t-${h.tone}" aria-label="Mining readiness">
      <div class="mh-readiness-main"><span class="hq-chip t-${h.tone}">${icon(h.tone === "ok" ? "check" : "alert")}Chain readiness</span>
        <h2>${esc(h.title)}</h2><p>${esc(h.detail)}</p>
        <small>${esc(sampled)}${d.field?.block != null ? ` · block ${fmtNum(d.field.block, 0)}` : ""}${h.stale ? " · stale" : ""}</small></div>
      <div class="mh-readiness-next"><span>Next step</span><button type="button" class="btn primary" data-mhgo="${h.go}">${esc(h.action)}${icon("right")}</button>
        <small>Registration and production changes require your approval.</small></div></section>`;
  }
  function overview() {
    Flex.register("mh.overview", { render, presets: LAYOUTS });
    const waiting = d.actions.filter(a => ["awaiting", "todo"].includes(a.status));
    // Readiness stays visible even when a saved layout hides the alert panel.
    return readiness() + Flex.grid("mh.overview", [
      { k: "ticker", title: "Key numbers", icon: "dash", size: 6, html: ticker() },
      { k: "brief", title: "Captain's brief", icon: "star", size: 6, html: hero() },
      { k: "waiting", title: "Waiting for you", icon: "hand", size: 6, html: waiting.length ? `<section class="mh-card hq-wait"><h2 class="hq-h">${icon("hand")}Waiting for you <span class="faint">actions on your miner expire after 6 hours; tasks stay until you close them</span></h2>
        <div class="hq-cards">${waiting.map(actionCard).join("")}</div></section>` : "" },
      { k: "recs", title: "Recommendations", icon: "target", size: 4, html: recsBlock() },
      { k: "alerts", title: "Alerts", icon: "shield", size: 2, html: alertsBlock() },
      { k: "done", title: "Recent actions", icon: "check", size: 4, html: doneBlock() },
      { k: "ask", title: "Ask the team", icon: "chat", size: 2, html: askBlock() },
      { k: "activity", title: "Latest activity", icon: "list", size: 2, html: `<section class="mh-card"><h2 class="hq-h">Latest activity <span class="hq-live ${d.running ? "on" : ""}">${d.running ? "live" : ""}</span>
          <button type="button" class="linkbtn" data-mhgo="activity">All activity</button></h2>${feed(d.events.slice(0, 12))}</section>` }]);
  }

  function hero() {
    const b = d.brief, f = d.field, t = d.campaign.settings.target, P = STAFF();
    if (!b) return `<article class="hq-hero t-wait"><div class="hq-hero-main"><div class="hq-kicker">${icon("star")}Captain's brief</div>
      <h2 class="hq-head">${d.running ? "The team is on its first cycle." : "The first brief comes with the first cycle."}</h2>
      <p class="hq-sum">${f ? `Rio has a snapshot: ${f.miners} miners, ${f.earners} of them earning.` : "Rio is reading the subnet from the chain."}</p></div></article>`;
    const st = b.stats || {}, [cls, label] = TONE[b.standing] || TONE.amber;
    const ticked = !Flex.layout("mh.overview").hide.includes("ticker");  // the Key numbers strip already shows these
    const tile =(v, l, tone = "") => `<div class="hq-tile ${tone}"><b>${v}</b><span>${l}</span></div>`;
    const mineTiles = st.rank ? tile(`#${st.rank}`, `of ${st.of} · UID ${st.uid}`, st.rank <= t ? "ok" : "") + tile(fmtNum(st.em), "your τ/day") +
      (st.gap ? tile(fmtNum(st.gap), `τ/day to top ${t}`, "warn") : tile(`Top ${t}`, "goal reached", "ok"))
      : tile("–", d.campaign.keys.length ? "no ranked miner" : "add your keys") + tile("–", "your τ/day") + tile(`#${t}`, "your goal");
    return `<article class="hq-hero t-${cls} ${ticked ? "mh-hero-solo" : ""}"><div class="hq-hero-main">
        <div class="hq-kicker"><span class="hq-pill t-${cls}">${label}</span>Captain's brief · ${when(b.ts)}${b.author === "captain" ? "" : ` · <span title="No model wrote this one: it's from the numbers">from the numbers</span>`}</div>
        <h2 class="hq-head">${esc(b.headline)}</h2>${b.summary ? `<p class="hq-sum">${esc(b.summary)}</p>` : ""}
        ${b.priorities.length ? `<div class="hq-todo"><div class="hq-todo-h">${icon("hand")}What to do</div><ol>${b.priorities.map(p => `<li>${esc(p)}</li>`).join("")}</ol></div>` : ""}
        <div class="hq-sign">${av(P.captain, "xs")}<span>${esc(P.captain?.name || "Avery")}, Team Captain</span><span class="faint">· next cycle ~${when(d.schedule.next_cycle || b.ts)}</span>
          ${briefs?.briefs?.length > 1 ? `<button type="button" class="linkbtn" data-mh="briefs">Earlier briefs (${briefs.briefs.length - 1})</button>` : ""}</div></div>
      ${ticked ? "" : `<div class="hq-tiles">${mineTiles}${tile(f ? fmtNum(f.top1) : "–", "top miner τ/day")}${tile(f ? `${f.earners}/${f.miners}` : "–", "miners earning")}${tile(f ? fmtNum(f.reg_cost, 3) : "–", "τ to register")}</div>`}</article>`;
  }

  function actionCard(a) {
    const P = STAFF(), backed = a.captain === "approve";
    return `<article class="hq-fix ${a.on_miner ? "" : "mh-task"}" data-action="${a.id}">
      <div class="hq-fix-top">${av(P[a.on_miner ? "captain" : "strategist"])}<div><div class="mh-act-label">${a.on_miner ? icon("server") : icon("hand")}${esc(a.title)}</div>
        <div class="faint small">${a.on_miner ? "On your miner · proposed by Sage" : "A task for you · from Sage"} · ${ago(a.created)}</div></div></div>
      ${a.detail ? `<p class="hq-fix-why">${esc(a.detail)}</p>` : ""}
      ${a.commands ? `<div class="mh-cmd"><pre>${esc(a.commands)}</pre><button type="button" class="iconbtn" data-copy="${esc(a.commands)}" title="Copy" aria-label="Copy the commands">${icon("copy")}</button></div>
        <p class="faint small">${icon("info")} Review commands before you run them. Never paste a seed phrase or key file anywhere.</p>` : ""}
      ${a.captain_note ? `<div class="hq-lead ${backed ? "ok" : ""}">${av(P.captain, "xs")}<span><b>Avery</b> ${backed ? "backs it" : "passes it to you"}: ${esc(a.captain_note)}</span></div>` : ""}
      <div class="hq-fix-foot"><span class="faint small">${a.on_miner ? `${icon("clock")}expires in ${until(a.expires).replace("in ", "")}` : ""}</span>
        <span class="row">${a.on_miner ? `<button type="button" class="btn sm" data-mhact="reject">Reject</button><button type="button" class="btn sm primary" data-mhact="approve">${icon("check")}Approve</button>`
          : `<button type="button" class="btn sm" data-mhact="dismiss">Dismiss</button><button type="button" class="btn sm primary" data-mhact="done">${icon("check")}Done</button>`}</span></div></article>`;
  }

  const IMPACT = { high: ["bad", "High impact"], medium: ["warn", "Medium"], low: ["off", "Low"] };
  const RKIND = { advantage: ["sparkle", "Advantage"], improvement: ["wrench", "Improvement"], risk: ["alert", "Risk"], timing: ["clock", "Timing"] };
  function recsBlock() {
    const list = d.recs;
    return `<section class="mh-card"><h2 class="hq-h">${icon("target")}Recommendations <span class="faint">from Sage, refreshed every cycle; what you dismiss (and why) shapes the next plan</span></h2>
      ${list.length ? `<ul class="mh-recs">${list.map(r => `<li class="mh-rec ${r.status}" data-rec="${r.id}">
        <div class="mh-rec-top"><span class="mh-rkind">${icon(RKIND[r.kind]?.[0] || "bulb")}${RKIND[r.kind]?.[1] || r.kind}</span>${chip(IMPACT[r.impact] || IMPACT.medium)}<span class="hq-chip">${esc(r.effort)} effort</span>
          ${r.status === "accepted" ? chip(["run", "On it"]) : ""}${r.seen > 1 ? `<span class="faint small">raised ${r.seen}×</span>` : ""}</div>
        <b class="mh-rec-title">${esc(r.title)}</b><p>${esc(r.detail)}</p>
        ${dismissing === r.id ? `<form class="mh-dismiss" data-dismiss="${r.id}"><input name="note" maxlength="400" placeholder="Why? Sage reads this next cycle (optional)" aria-label="Why you're dismissing it"><button type="submit" class="btn sm">Dismiss</button><button type="button" class="btn sm ghost" data-mhrec="cancel">Cancel</button></form>`
          : `<div class="row">${r.status === "open" ? `<button type="button" class="btn sm" data-mhrec="accepted">${icon("play")}I'm on it</button>` : ""}<button type="button" class="btn sm" data-mhrec="done">${icon("check")}Done</button><button type="button" class="btn sm ghost" data-mhrec="dismiss">Dismiss</button></div>`}</li>`).join("")}</ul>`
        : `<div class="empty small">${d.model ? "No open recommendations. Sage writes them after each cycle." : "Sage needs a model to plan. Connect one in Agents → Models."}</div>`}</section>`;
  }
  function doneBlock() {
    const closed = d.actions.filter(a => !["awaiting", "todo", "proposed"].includes(a.status)).slice(0, 6);
    if (!closed.length) return "";
    const S = { done: ["ok", "Done"], failed: ["bad", "Failed"], rejected: ["off", "Rejected"], dismissed: ["off", "Dismissed"], expired: ["off", "Expired"], running: ["run", "Running"] };
    return `<section class="mh-card"><h2 class="hq-h">Recent actions</h2><ul class="hq-mini mh-mini">${closed.map(a => `<li>${chip(S[a.status] || ["off", a.status])} ${esc(a.title)}
      <span class="faint">${a.decided_by ? `by ${esc(a.decided_by)}` : a.status === "rejected" && a.captain_note ? `Avery: ${esc(a.captain_note)}` : ""}${a.result ? ` · ${esc(a.result)}` : ""}</span></li>`).join("")}</ul></section>`;
  }
  function alertsBlock() {
    const L = { critical: ["critical", "alert", "Critical"], warning: ["warning", "alert", "Warning"], info: ["ok", "info", "News"] };
    return `<section class="mh-card"><h2 class="hq-h">${icon("shield")}Alerts <span class="faint">from Kit, checked on every snapshot</span></h2>
      ${d.alerts.length ? `<ul class="mh-alerts">${d.alerts.map(a => { const [cls, ic, l] = L[a.level] || L.info;
        return `<li class="lv-${a.level}" data-alert="${a.id}"><span class="hq-sev ${cls}">${icon(ic)}${l}</span><div><b>${esc(a.title)}</b><p>${esc(a.detail)}</p>
          <span class="faint small"><time data-ts="${a.first_seen}"></time>${a.last_seen - a.first_seen > 60 ? ` · still there ${ago(a.last_seen)}` : ""}</span></div>
          <button type="button" class="iconbtn" data-mh="ack" title="Got it: hide it" aria-label="Hide this alert">${icon("check")}</button></li>`; }).join("")}</ul>`
        : `<div class="empty small">${icon("info")}No open snapshot alerts. ${MiningReadiness(d).tone === "ok" ? "Registration was found in the latest snapshot." : "The readiness check still needs attention."}</div>`}</section>`;
  }
  function askBlock() {
    const asks = d.asks;
    return `<section class="mh-card"><h2 class="hq-h">${icon("chat")}Ask the team <span class="faint">Avery answers with the team's data</span></h2>
      <form class="mh-ask" data-ask><textarea name="q" rows="2" maxlength="1500" placeholder="e.g. What does UID ${d.field?.leader_uid ?? 9} do better than me?" aria-label="Your question" ${d.model ? "" : "disabled"}></textarea>
        <button type="submit" class="btn primary" ${d.model ? "" : "disabled"}>${icon("send")}Ask</button></form>
      ${asks.length ? `<ol class="mh-qa">${asks.map(a => `<li><div class="mh-q">${icon("chat")}${esc(a.question)}</div>
        <div class="mh-a">${a.status === "running" ? Loading.line("Avery is looking into it…") : a.answer ? `<div class="md">${Agents.md(a.answer)}</div>` : `<span class="faint">${esc(a.error || "No answer.")}</span>`}</div>
        <div class="faint small">${a.finished ? `${short(a.tokens)} tokens · ` : ""}<time data-ts="${a.started}"></time> · <button type="button" class="linkbtn" data-trace="${a.id}">Trace</button></div></li>`).join("")}</ol>` : ""}</section>`;
  }

  function feed(events) {
    if (!events.length) return `<div class="empty small">Nothing yet. The team's work shows up here as it happens.</div>`;
    const P = STAFF();
    return `<ol class="hq-feed mh-feed">${events.map(e => `<li class="k-${e.kind}">${av(P[e.agent], "xs")}<div><span class="hq-feed-who">${esc(P[e.agent]?.name || e.agent)}</span>
      <span class="hq-feed-ico">${icon(KIND_ICON[e.kind] || "dots")}</span>${esc(e.text)}${e.tokens ? ` <span class="faint">· ${short(e.tokens)} tokens</span>` : ""}
      ${e.run_id ? ` <button type="button" class="linkbtn" data-trace="${e.run_id}">trace</button>` : ""}<time data-ts="${e.ts}" title="${stamp(e.ts)}"></time></div></li>`).join("")}</ol>`;
  }

  // ---------- competition ----------
  function rangeSeg() {
    return `<div class="seg" role="group" aria-label="Time range">${[[1, "24 h"], [7, "7 days"], [30, "30 days"]].map(([k, l]) => `<button type="button" data-days="${k}" aria-pressed="${days === k}">${l}</button>`).join("")}</div>`;
  }
  // a subnet with several competitions: a sub-tab per competition, and one comparing them all
  function compTabs() {
    const list = d.competitions || [];
    if (list.length < 2) return "";
    const cur = fieldMech ?? d.campaign.mech;
    return `<div class="mh-subtabs" role="tablist" aria-label="SN${d.campaign.netuid}'s competitions">
      <button type="button" role="tab" data-fmech="all" aria-selected="${cur === "all"}">${icon("columns")}Compare all</button>
      ${list.map(x => `<button type="button" role="tab" data-fmech="${x.mech}" aria-selected="${cur === x.mech}"><b>${esc(x.name)}</b><span class="faint">${fmtNum(x.share * 100, 0)}%</span>${x.mech === d.campaign.mech ? `<span class="mh-camp-comp">this team</span>` : ""}</button>`).join("")}</div>`;
  }
  function teamLink(x) {
    return x.campaign ? (x.campaign === cid ? `<span class="faint">this team</span>` : `<button type="button" class="linkbtn" data-camp="${x.campaign}">Open its team</button>`)
      : `<button type="button" class="linkbtn" data-mhclone="${x.mech}">${icon("plus")}Put a team on it</button>`;
  }
  function compareView() {
    const list = d.competitions || [], t = d.campaign.settings.target, tone = i => ["s1", "s2", "s3"][i % 3];
    const rows = [["Share of the miners' rewards", x => pct(x.share, 0)], ["Miners' rewards", x => `${tau(x.pool)}/day`], ["Earning miners", x => `${x.earners} of ${x.miners}`],
      ["Leader", x => x.top1_uid == null ? "–" : `UID ${x.top1_uid} · ${tau(x.top1)}/day`], ["Leader's share", x => pct(x.share1, 0)],
      [`Top ${t} cutoff`, x => x.cut == null ? "–" : `${tau(x.cut)}/day`], ["Median earner", x => `${tau(x.median)}/day`], ["Spread (Gini)", x => fmtNum(x.gini, 2)],
      ["Your best", x => x.rank ? `#${x.rank} of ${x.miners} · UID ${x.uid} · ${tau(x.em)}/day` : `<span class="faint">not ranked</span>`], ["Team", teamLink]];
    return `${compTabs()}<section class="mh-card"><h2 class="hq-h">${icon("columns")}How SN${d.campaign.netuid}'s miner rewards split <span class="faint">each competition ranks miners on its own and pays its share; the same UIDs compete in all of them</span></h2>
        <div class="mh-split" role="img" aria-label="${esc(list.map(x => `${x.name} ${Math.round(x.share * 100)}%`).join(", "))}">${list.map((x, i) => `<i class="${tone(i)}" style="flex:${Math.max(x.share, 0.001)}" title="${esc(x.name)}: ${pct(x.share, 0)}"></i>`).join("")}</div>
        <div class="mh-legend">${list.map((x, i) => `<span><i class="k-bar ${tone(i)}"></i>${esc(x.name)} · ${pct(x.share, 0)}</span>`).join("")}</div>
        <div class="tablewrap mh-table-wrap"><table class="mh-table mh-compare"><thead><tr><th></th>${list.map(x => `<th><button type="button" class="linkbtn" data-fmech="${x.mech}">${esc(x.name)}</button></th>`).join("")}</tr></thead>
          <tbody>${rows.map(([l, f]) => `<tr><th scope="row">${l}</th>${list.map(x => `<td class="num">${f(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>
      <div class="mh-compare-tops">${list.map(x => `<section class="mh-card"><h2 class="hq-h">${icon("trophy")}${esc(x.name)} <span class="faint">top 5</span></h2>
        <ol class="mh-top5">${x.top.map(b => `<li class="${b.mine ? "mine" : ""}"><span class="num faint">#${b.rank}</span><b>UID ${b.uid}</b><code title="${esc(b.hk)}">${hk(b.hk)}</code>${b.mine ? `<span class="hq-chip t-run">yours</span>` : ""}<span class="num">${tau(b.em)}/day</span></li>`).join("") || `<li class="faint">Nobody earns yet.</li>`}</ol>
        <div class="row"><button type="button" class="btn sm" data-fmech="${x.mech}">${icon("chart")}Its field</button>${teamLink(x)}</div></section>`).join("")}</div>`;
  }
  function competition() {
    if (fieldMech === "all") return compareView();
    if (!field) return compTabs() + Loading.line("Ellis is laying out the field…");
    const r = field.report;
    if (!r) return `${compTabs()}<div class="empty">No snapshot yet: Rio takes the first one within a minute.</div>`;
    const other = field.mech !== d.campaign.mech ? (d.competitions || []).find(x => x.mech === field.mech) : null;
    const note = other ? `<div class="mh-viewing">${icon("info")}<span>You're looking at <b>${esc(other.name)}</b>, which gets ${pct(other.share, 0)} of the rewards. This team works on ${esc(d.campaign.comp)}${other.campaign ? "; the analysis is from that competition's own team." : ", and no team of yours watches this one, so there's no analysis."}</span>${teamLink(other)}</div>` : "";
    const st = r.stats, sr = r.series, t = r.target, a = field.analysis;
    const tiles = [["Top miner", sr.top1, v => tau(v), "τ/day for #1"], [`Top ${t} cutoff`, sr.cut, v => tau(v), `τ/day at #${t}`],
      ["Prune line", sr.prune, v => v == null ? "not full" : tau(v), "lowest past immunity"], ["Earning miners", sr.earners, v => fmtNum(v, 0), `of ${st.miners}`],
      ["Top miner's share", sr.share1, v => pct(v, 0), "of the miner pool"], ["Registration", sr.reg_cost, v => tau(v), "burn to register"]];
    const tile = ([label, vals, f, sub]) => {
      const v = vals.filter(x => x != null), last = v.at(-1), first = v[0];
      const ch = v.length > 1 && first ? last / first - 1 : null;
      return `<div class="stat mh-stat"><span class="mh-stat-l">${label}</span><b>${f(last)}</b><span class="faint small">${sub}${ch != null && Math.abs(ch) >= 0.005 ? ` · ${ch > 0 ? "+" : ""}${(ch * 100).toFixed(0)}% in range` : ""}</span>${spark(vals)}</div>`;
    };
    const P = STAFF();
    const lead = r.leader;
    const board = r.board.filter(b => !query || `${b.uid} ${b.hk} ${b.ck} ${b.cm}`.toLowerCase().includes(query.toLowerCase()));
    const rows = showAll || query ? board : board.filter(b => b.rank <= 50 || b.mine);
    const refAgo = r.ref_ts ? hours((r.ts - r.ref_ts) / 3600) : null;
    return `${compTabs()}${note}<div class="mh-filters">${rangeSeg()}<span class="faint small">Snapshot at block ${r.block.toLocaleString()} · ${ago(r.ts)}${refAgo ? ` · changes since ${refAgo} earlier` : ""}</span></div>
      <div class="mh-stats">${tiles.map(tile).join("")}</div>
      <div class="mh-grid wide"><section class="mh-card"><h2 class="hq-h">Rewards by rank <span class="faint">τ/day per miner, top ${Math.min(64, r.board.length)}${r.mine.some(m => m.rank > 64) ? " and yours" : ""}</span></h2>
          <div class="mh-legend"><span><i class="k-bar mine"></i>Your miners</span><span><i class="k-bar"></i>Everyone else</span><span><i class="k-ref"></i>Top ${t} cutoff</span></div>
          <div class="mh-chart" id="mh-curve" role="img" aria-label="Rewards per day by rank; the leaderboard below has every value"></div></section>
        <section class="mh-card">${analysisCard(a, P)}</section></div>
      <div class="mh-grid three">
        <section class="mh-card"><h2 class="hq-h">${icon("trophy")}The leader</h2>${lead ? `<p class="mh-big">UID ${lead.uid} <span class="faint">${hk(lead.hk)}</span></p>
          <dl class="mh-dl"><dt>Rewards</dt><dd>${tau(lead.em)}/day · ${pct(st.share1, 0)} of the pool</dd><dt>Leading for</dt><dd>${hours((r.ts - lead.since) / 3600)}${lead.since <= (sr.ts[0] || 0) ? "+" : ""}</dd>
          <dt>Trust · consensus</dt><dd>${fmtNum(lead.tr, 2)} · ${fmtNum(lead.cs, 2)}</dd>${lead.op ? `<dt>Operator</dt><dd>${lead.op} UIDs under one coldkey</dd>` : ""}
          <dt>Commitment</dt><dd>${lead.cm ? `<code title="${esc(lead.cm)}">${esc(lead.cm)}</code>${lead.cm_age_h != null ? ` <span class="faint">${hours(lead.cm_age_h)} old</span>` : ""}` : `<span class="faint">none published</span>`}</dd></dl>` : "–"}</section>
        <section class="mh-card"><h2 class="hq-h">${icon("swap")}Movers <span class="faint">${refAgo ? `since ${refAgo} earlier` : "need two snapshots"}</span></h2>
          ${r.movers.up.length || r.movers.down.length ? `<ul class="mh-movers">${[...r.movers.up.map(b => [b, "up"]), ...r.movers.down.map(b => [b, "down"])].map(([b, dir]) =>
            `<li class="${b.mine ? "mine" : ""}"><span class="delta ${dir}">${icon(dir)}${Math.abs(b.delta)}</span><b>UID ${b.uid}</b><span class="faint">now #${b.rank} · ${tau(b.em)}/day</span></li>`).join("")}</ul>` : `<div class="empty small">No rank changes yet.</div>`}</section>
        <section class="mh-card"><h2 class="hq-h">${icon("cycle")}Churn</h2>
          <dl class="mh-dl"><dt>Registered</dt><dd>${r.churn.registered.length}${r.churn.registered.length ? ` <span class="faint">best now #${Math.min(...r.churn.registered.map(x => x.rank))}</span>` : ""}</dd>
          <dt>Deregistered</dt><dd>${r.churn.deregistered.length}${r.churn.deregistered.some(x => x.mine) ? ` <span class="hq-chip t-bad">incl. yours</span>` : ""}</dd>
          <dt>Top ${10} turnover</dt><dd>${r.turnover ?? "–"}</dd><dt>Newcomers, 7 days</dt><dd>${r.newcomers.count} · ${r.newcomers.earning} earn${r.newcomers.best ? ` · best #${r.newcomers.best}` : ""}</dd>
          <dt>Validators</dt><dd>${r.validators.count} · ${r.validators.fresh} set weights lately</dd><dt>Slots</dt><dd>${st.full ? `full · next registration replaces UID ${st.prune_uid}` : `${st.open} open`}</dd></dl></section></div>
      ${r.operators.length ? `<section class="mh-card"><h2 class="hq-h">${icon("users")}Operators <span class="faint">coldkeys that run two or more miners</span></h2><div class="tablewrap mh-table-wrap"><table class="mh-table">
        <thead><tr><th>Coldkey</th><th class="r">UIDs</th><th class="r">τ/day</th><th class="r">Pool share</th><th class="r">Best rank</th><th class="r">Commitments</th></tr></thead>
        <tbody>${r.operators.map(o => `<tr><td><code>${esc(o.short)}</code></td><td class="r num">${o.uids}</td><td class="r num">${fmtNum(o.em)}</td><td class="r num">${pct(o.share, 1)}</td><td class="r num">#${o.best}</td><td class="r num">${o.commitments}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
      <section class="mh-card"><div class="mh-board-head"><h2 class="hq-h">${icon("list")}Leaderboard <span class="faint">${plural(r.board.length, "miner")}; validators and the owner aren't ranked</span></h2>
        <input type="search" class="mh-search" data-mhq value="${esc(query)}" placeholder="UID, hotkey, coldkey or commitment" aria-label="Filter the leaderboard">
        ${!query && r.board.length > 50 ? `<button type="button" class="btn sm" data-mh="all">${showAll ? "Top 50" : `All ${r.board.length}`}</button>` : ""}</div>
        <div class="tablewrap mh-table-wrap"><table class="mh-table mh-board"><thead><tr><th class="r">#</th><th class="r" title="Rank change since the reference snapshot">±</th><th class="r">UID</th><th>Hotkey</th>
          <th class="r">τ/day</th><th class="r">Incentive</th><th class="r">Trust</th><th class="r">Consensus</th><th class="r">Age</th><th>Axon</th><th>Commitment</th></tr></thead>
          <tbody>${rows.map(b => `<tr class="${b.mine ? "mine" : ""} ${b.rank === t ? "cut" : ""}"><td class="r num">${b.rank}</td><td class="r num">${b.new ? `<span class="hq-chip t-run">new</span>` : b.delta ? `<span class="delta ${b.delta > 0 ? "up" : "down"}">${b.delta > 0 ? "+" : ""}${b.delta}</span>` : `<span class="faint">·</span>`}</td>
            <td class="r num">${b.uid}</td><td><code title="${esc(b.hk)}">${hk(b.hk)}</code>${b.mine ? ` <span class="hq-chip t-run">yours</span>` : ""}${b.op ? ` <span class="hq-chip" title="${b.op} UIDs under coldkey ${esc(hk(b.ck))}">×${b.op}</span>` : ""}${b.immune ? ` <span class="hq-chip" title="Immune for ${hours(b.imm_left_h)} more">immune</span>` : ""}</td>
            <td class="r num">${fmtNum(b.em)}</td><td class="r num">${fmtNum(b.inc, 4)}</td><td class="r num">${fmtNum(b.tr, 2)}</td><td class="r num">${fmtNum(b.cs, 2)}</td><td class="r num">${hours(b.age_h)}</td>
            <td>${b.served ? `<span class="ci ci-ok" title="Serving"></span>` : `<span class="ci ci-none" title="No axon"></span>`}</td><td class="mh-cm">${b.cm ? `<code title="${esc(b.cm)}">${esc(b.cm)}</code>` : `<span class="faint">–</span>`}</td></tr>`).join("") ||
            `<tr><td colspan="11" class="empty small">No miner matches.</td></tr>`}</tbody></table></div></section>`;
  }
  function analysisCard(a, P) {
    const head = `<h2 class="hq-h">${av(P.analyst, "xs")}Ellis's analysis ${a ? `<span class="faint">${when(a.ts)}</span>` : ""}</h2>`;
    if (!a) return head + `<div class="empty small">${field && field.team == null ? "No team of yours works on this competition, so Ellis hasn't analysed it." : d.model ? "Ellis files an analysis every cycle." : "Ellis needs a model. Connect one in Agents → Models."}</div>`;
    return `${head}<p>${esc(a.summary)}</p>${a.bar_to_beat ? `<div class="mh-bar-beat">${icon("target")}<div><b>The bar to beat</b><p>${esc(a.bar_to_beat)}</p></div></div>` : ""}
      ${a.advantages.length ? `<h3 class="mh-h3">Advantages you can use</h3><ul class="mh-points">${a.advantages.map(x => `<li>${chip(IMPACT[x.impact] || IMPACT.medium)} <b>${esc(x.title)}</b><p>${esc(x.detail)}</p>${x.evidence ? `<p class="faint small">${icon("chart")} ${esc(x.evidence)}</p>` : ""}</li>`).join("")}</ul>` : ""}
      ${a.leaders.length ? `<h3 class="mh-h3">Why the leaders lead</h3><ul class="mh-points">${a.leaders.map(x => `<li><b>UID ${x.uid}</b> ${esc(x.note)}</li>`).join("")}</ul>` : ""}
      ${a.threats.length ? `<h3 class="mh-h3">Threats</h3><ul class="mh-points">${a.threats.map(x => `<li><b>${esc(x.title)}</b> ${esc(x.detail)}</li>`).join("")}</ul>` : ""}`;
  }

  // ---------- charts (plain SVG, the app's own tokens; tooltips enhance, the tables below carry every value) ----------
  // clean axis steps from at or below lo to at or above hi, so the plot always holds every value
  function ticks(lo, hi, n = 3) {
    const span = hi - lo || Math.abs(hi) || 1, step = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step;
    const s = step * (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1), out = [];
    for (let v = Math.floor(lo / s) * s; ; v += s) { out.push(+v.toFixed(10)); if (v >= hi - s * 1e-9) break; }
    return out;
  }
  // one decimal style per axis, from its step: 0 / 20 / 40, or 0 / 0.5 / 1.0
  const axisNum = (v, tk) => { const s = Math.abs(tk[1] - tk[0]) || 1; return fmtNum(v, s >= 1 ? 0 : s >= 0.1 ? 1 : s >= 0.01 ? 2 : 3); };
  function tip(el) { let t = $(".mh-tip", el); if (!t) { t = document.createElement("div"); t.className = "mh-tip"; t.hidden = true; el.append(t); } return t; }
  function curve(el, r) {
    const top = r.board.slice(0, 64), extra = r.board.slice(64).filter(b => b.mine), bars = [...top, ...extra];
    if (!bars.length) { el.innerHTML = `<div class="empty small">No miners.</div>`; return; }
    const W = el.clientWidth || 640, H = 190, L = 44, R = 8, T = 16, B = 22, gapIdx = extra.length ? top.length : -1;
    const slots = bars.length + (extra.length ? 1 : 0), slot = (W - L - R) / slots, bw = Math.max(1, Math.min(24, slot - 2));
    const hi = Math.max(...bars.map(b => b.em)) || 1, tk = ticks(0, hi), y1 = tk.at(-1);
    const Y = v => T + (1 - v / y1) * (H - T - B), X = i => L + (i + (gapIdx >= 0 && i >= gapIdx ? 1 : 0)) * slot + (slot - bw) / 2;
    const bar = (x, v) => { const y = Y(v), base = H - B, rr = Math.min(4, bw / 2, base - y); return base - y < 0.5 ? "" : `M${x},${base}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + bw - rr}Q${x + bw},${y} ${x + bw},${y + rr}V${base}Z`; };
    const t = r.target, cut = t <= top.length ? L + t * slot : null;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" tabindex="0" aria-hidden="true">
      ${tk.map(v => `<line class="mh-grid-l" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="mh-axis" x="${L - 6}" y="${Y(v) + 3}" text-anchor="end">${axisNum(v, tk)}</text>`).join("")}
      <line class="mh-base" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
      ${bars.map((b, i) => `<path class="mh-b ${b.mine ? "mine" : ""}" data-i="${i}" d="${bar(X(i), b.em)}"/>`).join("")}
      ${cut ? `<line class="mh-ref" x1="${cut}" x2="${cut}" y1="${T - 6}" y2="${H - B}"/><text class="mh-axis" x="${cut + 4}" y="${T - 4}">Top ${t}</text>` : ""}
      ${gapIdx >= 0 ? `<text class="mh-axis" x="${L + gapIdx * slot + slot / 2}" y="${H - B - 4}" text-anchor="middle">…</text>` : ""}
      ${[1, Math.min(10, top.length), Math.min(25, top.length), top.length].filter((v, i, a) => a.indexOf(v) === i && v > 0).map(n => `<text class="mh-axis" x="${X(n - 1) + bw / 2}" y="${H - 6}" text-anchor="middle">#${n}</text>`).join("")}
      ${extra.map((b, j) => `<text class="mh-axis" x="${X(top.length + j) + bw / 2}" y="${H - 6}" text-anchor="middle">#${b.rank}</text>`).join("")}
      ${bars.map((b, i) => `<rect class="mh-hit" data-i="${i}" x="${L + (i + (gapIdx >= 0 && i >= gapIdx ? 1 : 0)) * slot}" y="${T}" width="${slot}" height="${H - T - B}"/>`).join("")}</svg>`;
    const tp = tip(el), svg = $("svg", el);
    const show = i => {
      const b = bars[i]; if (!b) return;
      $$(".mh-b", svg).forEach(p => p.classList.toggle("hover", +p.dataset.i === i));
      tp.hidden = false; tp.innerHTML = `<b>${fmtNum(b.em)} τ/day</b><span>#${b.rank} · UID ${b.uid}${b.mine ? " · yours" : ""}</span>`;
      const bx = svg.getBoundingClientRect(), x = (X(i) + bw / 2) / W * bx.width;
      tp.style.left = `${Math.min(bx.width - 80, Math.max(60, x))}px`; tp.style.top = `${Y(b.em) / H * bx.height - 8}px`;
    };
    let at = 0;
    svg.addEventListener("pointermove", e => { const i = +e.target.dataset?.i; if (!isNaN(i)) { at = i; show(i); } });
    svg.addEventListener("pointerleave", () => { tp.hidden = true; $$(".mh-b.hover", svg).forEach(p => p.classList.remove("hover")); });
    svg.addEventListener("keydown", e => { if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return; e.preventDefault(); at = Math.max(0, Math.min(bars.length - 1, at + (e.key === "ArrowRight" ? 1 : -1))); show(at); });
    svg.addEventListener("focus", () => show(at)); svg.addEventListener("blur", () => { tp.hidden = true; });
  }
  // a line chart over time: up to two series on one axis, a legend, direct end labels, a crosshair tooltip with every series
  function lines(el, ts, series, { fmt = v => fmtNum(v), invert = false, ref = null, height = 170 } = {}) {
    const pts = series.map(s => s.values.map((v, i) => [ts[i], v]).filter(p => p[1] != null));
    if (pts.every(p => p.length < 2)) { el.innerHTML = `<div class="empty small">Not enough history yet: the chart fills in with every snapshot.</div>`; return; }
    const W = el.clientWidth || 600, H = height, L = 44, R = 64, T = 10, B = 22;
    const all = pts.flat().map(p => p[1]).concat(ref ? [ref.value] : []);
    let lo = Math.min(...all), hi = Math.max(...all);
    if (invert) { lo = Math.max(1, lo); } else lo = Math.min(0, lo);
    const tk = ticks(lo, hi), y0 = invert ? Math.max(1, tk[0]) : tk[0], y1 = tk.at(-1);
    const xs = ts.filter((_, i) => series.some(s => s.values[i] != null)), x0 = Math.min(...xs), x1 = Math.max(...xs);
    const X = x => L + (x - x0) / (x1 - x0 || 1) * (W - L - R), Y = v => invert ? T + (v - y0) / (y1 - y0 || 1) * (H - T - B) : T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
    const span = x1 - x0, nx = Math.max(2, Math.min(6, Math.floor((W - L - R) / 90)));
    const xt = Array.from({ length: nx }, (_, i) => x0 + span * i / (nx - 1));
    const xl = x => span < 2 * 86400 ? new Date(x * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : new Date(x * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const path = p => p.map((q, i) => `${i ? "L" : "M"}${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join("");
    const ends = pts.map((p, i) => p.length ? { i, x: X(p.at(-1)[0]), y: Y(p.at(-1)[1]), v: p.at(-1)[1] } : null).filter(Boolean);
    const clash = ends.length === 2 && Math.abs(ends[0].y - ends[1].y) < 14;
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" tabindex="0" aria-hidden="true">
      ${tk.filter(v => !invert || v >= 1).map(v => `<line class="mh-grid-l" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="mh-axis" x="${L - 6}" y="${Y(v) + 3}" text-anchor="end">${invert ? `#${v}` : axisNum(v, tk)}</text>`).join("")}
      ${xt.map(x => `<text class="mh-axis" x="${X(x)}" y="${H - 5}" text-anchor="middle">${xl(x)}</text>`).join("")}
      ${ref ? `<line class="mh-ref" x1="${L}" x2="${W - R}" y1="${Y(ref.value)}" y2="${Y(ref.value)}"/><text class="mh-axis" x="${W - R + 6}" y="${Y(ref.value) + 3}">${esc(ref.label)}</text>` : ""}
      ${pts.map((p, i) => p.length > 1 ? `<path class="mh-line s${series[i].slot}" d="${path(p)}"/>` : "").join("")}
      ${ends.map(e => `<circle class="mh-dot s${series[e.i].slot}" cx="${e.x}" cy="${e.y}" r="4"/>${clash && e.i ? "" : `<text class="mh-end" x="${e.x + 8}" y="${Math.max(T + 8, Math.min(e.y + 4, H - B - 4))}">${esc(fmt(e.v))}</text>`}`).join("")}
      <line class="mh-cross" y1="${T}" y2="${H - B}" visibility="hidden"/><rect class="mh-hit" x="${L}" y="0" width="${W - L - R}" height="${H}"/></svg>`;
    const svg = $("svg", el), tp = tip(el), cross = $(".mh-cross", svg);
    let at = ts.length - 1;
    const show = i => {
      at = i; const x = X(ts[i]), bx = svg.getBoundingClientRect();
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      tp.hidden = false; tp.innerHTML = `<span>${new Date(ts[i] * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>` +
        series.map(s => `<div><i class="k-line s${s.slot}"></i><b>${s.values[i] == null ? "–" : esc(fmt(s.values[i]))}</b> <span>${esc(s.label)}</span></div>`).join("");
      tp.style.left = `${Math.min(bx.width - 90, Math.max(70, x / W * bx.width))}px`; tp.style.top = "8px";
    };
    const near = mx => { let best = 0; ts.forEach((t, i) => { if (Math.abs(X(t) - mx) < Math.abs(X(ts[best]) - mx)) best = i; }); return best; };
    svg.addEventListener("pointermove", e => { const bx = svg.getBoundingClientRect(); show(near((e.clientX - bx.left) * W / bx.width)); });
    svg.addEventListener("pointerleave", () => { tp.hidden = true; cross.setAttribute("visibility", "hidden"); });
    svg.addEventListener("keydown", e => { if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return; e.preventDefault(); show(Math.max(0, Math.min(ts.length - 1, at + (e.key === "ArrowRight" ? 1 : -1)))); });
    svg.addEventListener("focus", () => show(at)); svg.addEventListener("blur", () => { tp.hidden = true; cross.setAttribute("visibility", "hidden"); });
  }
  function drawCompetition() { const el = $("#mh-curve", root()); if (el && field?.report) curve(el, field.report); }

  // ---------- my miners ----------
  function minersTab() {
    if (!mine) return Loading.line("Finley is pulling up your miners…");
    const P = STAFF(), t = mine.target, tr = mine.tracking;
    if (!d.campaign.keys.length) return `<div class="mh-card mh-empty-card">${icon("pickaxe")}<h2>Add your miner's keys</h2><p>Paste your miner's hotkey (or your coldkey, for every UID under it) in Settings and Finley starts tracking it on the next snapshot.</p>
      <button type="button" class="btn primary" data-mhgo="settings">${icon("gear")}Open Settings</button></div>`;
    const cards = mine.miners.map((m, i) => {
      const [cls, label] = MSTATUS[m.status] || MSTATUS.chasing, h = m.history;
      const cutAt = h.ts.map(x => mine.series.cut[mine.series.ts.indexOf(x)] ?? null);
      return `<article class="mh-card mh-miner" data-miner="${i}"><header><div><h2 class="mh-miner-h">UID ${m.uid} <code title="${esc(m.hk)}">${hk(m.hk)}</code></h2>${chip([cls, label])}</div>
          <div class="mh-miner-rank"><b>#${m.rank}</b><span>of ${m.of}${m.delta ? ` · <span class="delta ${m.delta > 0 ? "up" : "down"}">${m.delta > 0 ? "+" : ""}${m.delta}</span>` : ""}</span></div></header>
        <div class="mh-kv"><div><span>Rewards</span><b>${tau(m.em)}/day</b></div><div><span>To top ${t}</span><b>${m.gap_target ? tau(m.gap_target) : "inside"}</b></div><div><span>To #1</span><b>${tau(m.gap_top)}</b></div>
          <div><span>Incentive</span><b>${fmtNum(m.inc, 4)}</b></div><div><span>Trust · consensus</span><b>${fmtNum(m.tr, 2)} · ${fmtNum(m.cs, 2)}</b></div>
          <div><span>${m.immune ? "Immunity left" : "Prune line"}</span><b>${m.immune ? hours(m.imm_left_h) : m.prune_pos ? `${m.prune_pos - 1} below you` : "not full"}</b></div>
          <div><span>Axon</span><b>${m.served ? "serving" : "not serving"}</b></div><div><span>Registered</span><b>${hours(m.age_h)} ago</b></div></div>
        ${m.cm ? `<p class="faint small">Commitment: <code>${esc(m.cm)}</code>${m.cm_age_h != null ? ` · ${hours(m.cm_age_h)} old` : ""}</p>` : ""}
        <div class="mh-two-charts"><div><h3 class="mh-h3">Rewards per day</h3><div class="mh-legend"><span><i class="k-line s1"></i>UID ${m.uid}</span><span><i class="k-line s2"></i>Top ${t} cutoff</span></div>
            <div class="mh-chart" data-chart="em" role="img" aria-label="UID ${m.uid}'s rewards per day against the top ${t} cutoff; the table below has every value"></div></div>
          <div><h3 class="mh-h3">Rank</h3><div class="mh-chart" data-chart="rank" role="img" aria-label="UID ${m.uid}'s rank over time; the table below has every value"></div></div></div>
        <div class="mh-near"><h3 class="mh-h3">Around you</h3><table class="mh-table mh-compact"><thead><tr><th class="r">#</th><th class="r">UID</th><th class="r">τ/day</th><th class="r">Incentive</th><th class="r">Trust</th><th class="r">Consensus</th><th>Axon</th></tr></thead>
          <tbody>${[...m.above.map(x => [x, ""]), [m, "mine"], ...m.below.map(x => [x, ""])].map(([x, c]) => `<tr class="${c}"><td class="r num">${x.rank}</td><td class="r num">${x.uid}</td><td class="r num">${fmtNum(x.em)}</td><td class="r num">${fmtNum(x.inc, 4)}</td><td class="r num">${fmtNum(x.tr, 2)}</td><td class="r num">${fmtNum(x.cs, 2)}</td><td>${x.served ? "yes" : "no"}</td></tr>`).join("")}</tbody></table></div>
        <details class="mh-data"><summary>History as a table (${h.ts.length} snapshots)</summary><div class="tablewrap mh-table-wrap"><table class="mh-table mh-compact"><thead><tr><th>When</th><th class="r">Rank</th><th class="r">τ/day</th><th class="r">Top ${t} cutoff</th><th class="r">Trust</th><th class="r">Consensus</th></tr></thead>
          <tbody>${h.ts.map((x, j) => [x, j]).reverse().slice(0, 120).map(([x, j]) => `<tr><td>${when(x)}</td><td class="r num">${h.rank[j]}</td><td class="r num">${fmtNum(h.em[j])}</td><td class="r num">${fmtNum(cutAt[j])}</td><td class="r num">${fmtNum(h.tr[j], 2)}</td><td class="r num">${fmtNum(h.cs[j], 2)}</td></tr>`).join("")}</tbody></table></div></details></article>`;
    }).join("");
    const missing = mine.missing.map(k => `<li><code title="${esc(k.key)}">${esc(k.short)}</code> ${k.validator ? "is a validator here, not a miner." : k.gone ? `<span class="hq-chip t-bad">deregistered</span> since the reference snapshot.` : "has no miner UID on this subnet."}</li>`).join("");
    const p = d.campaign.product;
    return `<div class="mh-filters">${rangeSeg()}<span class="faint small">Goal: a top ${t} place · the cutoff now pays ${tau(mine.stats.cut[String(t)])}/day</span></div>
      <div class="mh-grid wide"><div class="mh-col">${cards || `<div class="mh-card empty">None of your keys has a miner UID ranked on this subnet right now.</div>`}
          ${missing ? `<section class="mh-card"><h2 class="hq-h">${icon("info")}Keys without a ranked miner</h2><ul class="mh-points">${missing}</ul></section>` : ""}</div>
        <div class="mh-col"><section class="mh-card"><h2 class="hq-h">${av(P.tracker, "xs")}Finley's report ${tr ? `<span class="faint">${when(tr.ts)}</span>` : ""}</h2>
            ${tr ? `${chip(TRACK[tr.status] || ["off", tr.status])}<p>${esc(tr.summary)}</p>${tr.diagnosis.length ? `<h3 class="mh-h3">Diagnosis</h3><ul class="mh-points">${tr.diagnosis.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
              ${tr.improvements.length ? `<h3 class="mh-h3">How to improve your miner</h3><ul class="mh-points">${tr.improvements.map(x => `<li>${chip(IMPACT[x.impact] || IMPACT.medium)} <span class="hq-chip">${esc(x.effort)} effort</span> <b>${esc(x.title)}</b><p>${esc(x.detail)}</p>${x.evidence ? `<p class="faint small">${icon("chart")} ${esc(x.evidence)}</p>` : ""}</li>`).join("")}</ul>` : ""}`
              : `<div class="empty small">${d.model ? "Finley reports every cycle." : "Finley needs a model. Connect one in Agents → Models."}</div>`}</section>
          <section class="mh-card"><h2 class="hq-h">${icon("pickaxe")}Your product <button type="button" class="linkbtn" data-mhgo="settings">Edit</button></h2>
            ${p.product_name || p.product_notes || p.repo ? `<dl class="mh-dl">${p.product_name ? `<dt>Name</dt><dd>${esc(p.product_name)}</dd>` : ""}${p.product_notes ? `<dt>About it</dt><dd class="mh-pre">${esc(p.product_notes)}</dd>` : ""}
              ${p.repo ? `<dt>Repository</dt><dd><code>${esc(p.repo)}</code></dd>` : ""}<dt>Runs</dt><dd>${p.runs_kind === "devops" ? `DevOps pipeline <code>${esc(p.runs_name)}</code>` : p.runs_kind === "app" ? `app <code>${esc(p.runs_name)}</code>` : "elsewhere (actions are manual)"}</dd></dl>`
              : `<p class="faint">Tell the team what your miner is (model, approach, hardware, version) and where its code lives: Finley's advice gets specific.</p>`}</section></div></div>`;
  }
  function drawMine() {
    if (!mine) return;
    $$(".mh-miner", root()).forEach(card => {
      const m = mine.miners[+card.dataset.miner], h = m.history, sr = mine.series, t = mine.target;
      const cut = h.ts.map(x => { const j = sr.ts.indexOf(x); return j >= 0 ? sr.cut[j] : null; });
      lines($('[data-chart="em"]', card), h.ts, [{ label: `UID ${m.uid}`, slot: 1, values: h.em }, { label: `Top ${t} cutoff`, slot: 2, values: cut }], { fmt: v => fmtNum(v) });
      lines($('[data-chart="rank"]', card), h.ts, [{ label: "Rank", slot: 1, values: h.rank }], { fmt: v => `#${Math.round(v)}`, invert: true, ref: { value: t, label: `Top ${t}` } });
    });
  }

  // ---------- team ----------
  function team() {
    const live = d.campaign.status === "live", f = d.flow, P = STAFF(), u = d.usage, share = u.budget ? Math.min(1, u.day / u.budget) : 0;
    const per = d.staff.filter(a => a.model), max = Math.max(1, ...per.map(a => a.tokens_day));
    const why = { schedule: "scheduled", manual: "you asked", alert: "after an alert", kickoff: "the first cycle" };
    const head = f ? `Cycle #${f.cycle} · ${f.status === "running" ? `running since ${clock(f.started)}` : `${esc(f.status)} ${when(f.finished || f.started)}`} · ${why[f.trigger] || esc(f.trigger)}`
      + `${f.agents ? ` · only ${f.agents.map(a => esc(P[a]?.name || a)).join(", ")}` : ""}${f.tokens ? ` · ${short(f.tokens)} tokens` : ""}` : "No cycle yet";
    return `<section class="mh-card mf-wrap"><div class="mf-bar"><h2 class="hq-h">${icon("route")}Workflow <span class="faint">${head}</span></h2>
        <div class="mf-ctl" role="toolbar" aria-label="Control the team">
          <button type="button" class="btn primary sm" data-mh="run" ${d.running || !live ? "disabled" : ""}>${icon("play")}Run a cycle</button>
          <button type="button" class="btn sm" data-mfrun="scout" ${d.running || !live ? "disabled" : ""}>${icon("radio")}Snapshot now</button>
          ${d.running ? `<button type="button" class="btn sm" data-mh="cancel">${icon("stop")}Stop</button>` : ""}
          <button type="button" class="btn sm" data-mh="pause" aria-pressed="${!live}">${icon(live ? "clock" : "play")}${live ? "Pause the team" : "Resume the team"}</button></div></div>
        ${MiningFlow.diagram(d)}
        <p class="faint small mf-help">Click an agent for its controls and what it found. ${icon("play")} runs from that step on: the steps before it lend their last results. ${icon("ban")} switches an agent off until you switch it back on.</p></section>
      <section class="mh-card mf-cycles"><h2 class="hq-h">${icon("list")}Recent cycles <span class="faint">a row per cycle, a cell per step; open a cell for its trace</span></h2>${MiningFlow.grid(cycles, d)}</section>
      <div class="hq-grid mf-below"><section class="hq-org-wrap"><h2 class="hq-h">${icon("coins")}Model use <span class="faint">last 24 hours</span></h2>
        <div class="mh-meter ${share >= 1 ? "full" : share >= 0.8 ? "high" : ""}" role="meter" aria-valuemin="0" aria-valuemax="${u.budget || u.day}" aria-valuenow="${u.day}" aria-label="Tokens used today"><i style="--w:${(share * 100).toFixed(1)}%"></i></div>
        <p class="faint small">${short(u.day)} of ${u.budget ? short(u.budget) : "unlimited"} tokens${share >= 1 ? ": analysis waits until some of the last 24 hours' use rolls off, or raise the budget in Settings" : ""}. Rio, Kit and Quinn never use tokens.</p>
        <ul class="hq-bars">${per.map(a => `<li><span>${esc(a.name)}</span><i style="--w:${(a.tokens_day / max * 100).toFixed(1)}%"></i><b>${short(a.tokens_day)}</b><span class="faint">${plural(a.runs_day, "run")}${a.failed_day ? `, ${a.failed_day} failed` : ""}</span></li>`).join("")}</ul></section>
      <section class="hq-feed-wrap"><h2 class="hq-h">${icon("note")}Standing instructions for the team</h2>
        <form class="mh-directive" data-directive="team"><textarea name="text" rows="3" maxlength="600" placeholder="e.g. Our budget is $200/month; we can't rent more GPUs. Prefer changes we can ship in a day.">${esc(d.campaign.directives.team || "")}</textarea>
          <button type="submit" class="btn sm">${icon("check")}Save</button></form>
        <p class="faint small">Every agent reads these on every run. Give one agent its own in its card.</p></section></div>`;
  }
  // the Scribe's card: where it saves, and how it's doing
  function scribeInfo() {
    const j = d.journal || {}, dv = j.drive || {};
    const ws = dv.on && dv.enabled ? `<div class="mf-detail"><div>${icon("folder")}My workspace: <code>${esc(dv.space === "shared" ? "Shared drive" : "My drive")} › ${esc((dv.path || "").split("/").join(" › "))}</code>
        ${dv.folder ? `<button type="button" class="linkbtn small" data-open-drive="${esc(dv.folder.space)}:${esc(dv.folder.id)}">Open</button>` : ""}</div>
      <p class="faint small">${plural(dv.saved_day, "file")} saved in the last 24 hours.${dv.last?.status === "failed" ? ` The last one failed: ${esc(dv.last.error || "")}` : ""}</p></div>` : "";
    return ws + scribeGit(j);
  }
  function scribeGit(j) {
    if (!j.on) return `<p class="faint small">Saving to a repository is off. ${j.can ? "Turn it on in Settings, under Save results to a repository." : j.connected ? "Only an administrator's campaign can save to the Source hub's repositories." : "Connect GitHub in the Source view first."}</p>
      ${j.can ? `<div class="row"><button type="button" class="btn sm" data-mhgo="settings">${icon("gear")}Open Settings</button></div>` : ""}`;
    return `<div class="mf-detail"><div>${icon("repo")}<a href="${esc(j.url || "#")}" target="_blank" rel="noopener">${esc(j.repo)}</a> on ${icon("branch")}<code>${esc(j.branch)}</code>, under <code>${esc(j.folder)}/</code></div>
      <p class="faint small">${plural(j.saved_day, "file")} committed in the last 24 hours.${j.last?.status === "failed" ? ` The last one failed: ${esc(j.last.error || "")}` : ""}</p></div>`;
  }
  async function agentCard(id) {
    const a = STAFF()[id]; if (!a) return;
    let dlg = $("#mh-agent");
    if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "mh-agent"; dlg.className = "modal hq-dlg mh-dlg"; document.body.append(dlg); dlg.addEventListener("click", dlgClick); dlg.addEventListener("submit", dlgSubmit); dlg.addEventListener("change", dlgChange); }
    const [dot, label] = STATE[a.status] || STATE.idle;
    const can = !d.running && d.campaign.status === "live", from = MiningFlow.FROM[id];
    const runs = id === "scout" ? [[["scout"], "radio", "Take a snapshot now"]] : id === "captain" ? [[["captain"], "star", "Write a new brief"], [[], "play", "Run a full cycle"]]
      : from ? [[[id], "play", `Run only ${a.name}`], [from, "route", `Run from ${a.name} on`]] : [];
    dlg.dataset.agent = id;
    dlg.innerHTML = `<div class="hq-dlg-in"><button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>
      <div class="hq-dlg-head">${av(a, "lg")}<div><h3>${esc(a.name)}</h3><div class="faint">${esc(a.title)} · ${a.model ? "runs on the campaign's model" : "plain code, no tokens"}</div>
        <div class="hq-node-state"><span class="ci ci-${dot}"></span>${label}${a.note && a.status !== "working" && !d.flow?.steps?.[id] && id !== "scribe" ? ` <span class="faint">· ${esc(a.note)}</span>` : ""}</div></div></div>
      <p>${esc(a.job)}</p>
      ${id === "scribe" ? scribeInfo() : MiningFlow.stepDetail(d, id)}
      <div class="hq-dlg-stats"><span><b>${a.runs_day}</b> ${{ scout: "snapshots", sentinel: "new alerts", scribe: "files saved" }[a.id] || "runs"} today</span>${a.model ? `<span><b>${short(a.tokens_day)}</b> tokens today</span>` : ""}${a.last_run ? `<span><b>${ago(a.last_run)}</b> last active</span>` : ""}</div>
      ${a.switchable ? `<label class="toggle-row"><span><b>On the team</b><small class="faint">${id === "sentinel" ? "Off, no alerts and its open alerts close." : "Off, it sits out every cycle until you switch it back on."}</small></span><span class="switch"><input type="checkbox" data-mh-on="${id}" ${a.on ? "checked" : ""}><span></span></span></label>` : ""}
      ${a.model ? `<form class="mh-directive" data-directive="${id}"><label class="in"><span>Your instructions for ${esc(a.name)}</span><textarea name="text" rows="3" maxlength="600" placeholder="${esc({ analyst: "e.g. Watch UID 17's commitments closely.", tracker: "e.g. Our latency is 2.1 s; we can cut it with a smaller model.", strategist: "e.g. Don't suggest more UIDs until UID 23 is in the top 10.", captain: "e.g. Keep the brief to two sentences." }[id] || "")}">${esc(a.directive || "")}</textarea></label>
        <button type="submit" class="btn sm">${icon("check")}Save</button></form>` : ""}
      ${runs.length ? `<div class="row">${runs.map(([list, ic, l]) => `<button type="button" class="btn sm" data-mh-runs="${list.join(",")}" ${can ? "" : "disabled"}>${icon(ic)}${esc(l)}</button>`).join("")}</div>
        ${from && id !== "scout" && id !== "captain" ? `<p class="faint small">Run only ${esc(a.name)}: just this step. Run from here: this step, then the plan and the brief; the steps before it lend their last results.</p>` : ""}` : ""}
      <h4>Recent runs</h4><div class="mh-dlg-runs">${!a.model ? `<p class="faint small">${esc(a.name)} works in plain code; its work is in the feed below.</p>` : Loading.line("Reading…")}</div>
      <h4>Recent work</h4><div class="mh-dlg-feed">${Loading.line("Reading…")}</div></div>`;
    if (!dlg.open) dlg.showModal();
    try {
      const [r, ev] = await Promise.all([a.model ? api(`/api/mining/campaigns/${cid}/runs?agent=${id}`) : null, api(`/api/mining/campaigns/${cid}/events?agent=${id}`)]);
      if (r) $(".mh-dlg-runs", dlg).innerHTML = r.runs.length ? runTable(r.runs.slice(0, 8)) : `<p class="faint small">No runs yet.</p>`;
      $(".mh-dlg-feed", dlg).innerHTML = feed(ev.events.slice(0, 12)); $$("time[data-ts]", dlg).forEach(t => { t.textContent = ago(+t.dataset.ts); });
    } catch (e) { $(".mh-dlg-feed", dlg).innerHTML = `<div class="empty small">${esc(e.message)}</div>`; }
  }
  async function dlgClick(e) {
    const dlg = e.currentTarget;
    if (e.target === dlg || e.target.closest("[data-close]")) return dlg.close();
    const tr = e.target.closest("[data-trace]"); if (tr) { dlg.close(); return openTrace(+tr.dataset.trace); }
    const go = e.target.closest("[data-mhgo]"); if (go) { dlg.close(); tab = go.dataset.mhgo; store.set("mh.tab", tab); render(); return loadTab(); }
    const one = e.target.closest("[data-mh-runs]");
    if (one) { one.disabled = true; await run(one.dataset.mhRuns ? one.dataset.mhRuns.split(",") : [], ""); dlg.close(); }
  }
  async function dlgSubmit(e) { e.preventDefault(); await saveDirective(e.target); }
  async function setOn(id, on, btn) {
    if (btn) btn.disabled = true;
    try { await api(`/api/mining/campaigns/${cid}/agents/${id}`, { method: "POST", body: { on } }); Auth.toast(on ? `${STAFF()[id]?.name} is back on the team` : `${STAFF()[id]?.name} is off the team`); }
    catch (e) { err(e); }
    await refresh();
  }
  async function cloneTeam(mech) {
    const x = (d.competitions || []).find(c => c.mech === mech); if (!x) return;
    await UI.confirm({ title: `Put a team on ${x.name}?`, icon: "users", ok: "Start the team", danger: false,
      body: `It gets ${fmtNum(x.share * 100, 0)}% of SN${d.campaign.netuid}'s rewards. The new team starts with this one's goal, keys, product, instructions and settings, and runs its own cycles on its own budget.`,
      run: async () => { const r = await api(`/api/mining/campaigns/${cid}/competitions/${mech}`, { method: "POST" }); home = await api("/api/mining"); Auth.toast("Team assembled: its first cycle has started"); await select(r.id); } }).catch(err);
  }
  async function dlgChange(e) {
    const sw = e.target.closest("[data-mh-on]"); if (!sw) return;
    try { await api(`/api/mining/campaigns/${cid}/agents/${sw.dataset.mhOn}`, { method: "POST", body: { on: sw.checked } }); Auth.toast(sw.checked ? "Back on the team" : "Off the team"); await refresh(); }
    catch (e2) { sw.checked = !sw.checked; err(e2); }
  }
  async function saveDirective(form) {
    const btn = $("button[type=submit]", form); btn.classList.add("loading"); btn.disabled = true;
    try { d = await api(`/api/mining/campaigns/${cid}`, { method: "PATCH", body: { directives: { [form.dataset.directive]: form.elements.text.value } } }); Auth.toast("Instructions saved: the team reads them on its next run"); live(); }
    catch (e) { err(e); }
    btn.classList.remove("loading"); btn.disabled = false;
  }

  // ---------- activity and traces ----------
  function runTable(list) {
    const P = STAFF(), S = { done: ["ok", "Done"], failed: ["bad", "Failed"], running: ["run", "Running"], cancelled: ["off", "Stopped"] };
    const K = { analysis: "Analysis", tracking: "Tracking", plan: "Plan", brief: "Brief", ask: "Question" };
    return `<div class="tablewrap mh-table-wrap"><table class="mh-table mh-runs"><thead><tr><th>Run</th><th>Status</th><th class="r">Time</th><th class="r">Tokens</th></tr></thead>
      <tbody>${list.map(r => `<tr data-trace="${r.id}" tabindex="0"><td><span class="mh-run-who">${av(P[r.agent], "xs")}<b>${esc(P[r.agent]?.name || r.agent)}</b> ${K[r.kind] || esc(r.kind)}
          <span class="faint mh-run-meta">${when(r.started)}${r.spans ? ` · ${plural(r.spans - r.tools, "model call")}, ${plural(r.tools, "tool call")}` : ""}</span></span>
          <span class="faint mh-run-sum">${esc(r.question || r.summary || r.error || "")}</span></td>
        <td>${chip(S[r.status] || ["off", r.status])}</td><td class="r num">${r.finished ? dur(r.finished - r.started) : "…"}</td><td class="r num">${short(r.tokens)}</td></tr>`).join("")}</tbody></table></div>
      <p class="faint small">Open a run for its full trace: every model call and tool call with its input, output, tokens and time.</p>`;
  }
  function activity() {
    const P = STAFF(), list = who ? d.events.filter(e => e.agent === who) : d.events;
    return `<div class="mh-filters"><div class="seg" role="group" aria-label="Agent"><button type="button" data-who="" aria-pressed="${!who}">Everyone</button>${d.staff.map(a => `<button type="button" data-who="${a.id}" aria-pressed="${who === a.id}">${esc(a.name)}</button>`).join("")}</div>
        <span class="hq-live ${es ? "on" : ""}">${es ? "live" : "reconnecting…"}</span></div>
      <div class="mh-grid"><section class="mh-card"><h2 class="hq-h">Feed <span class="faint">${who ? `${esc(P[who]?.name)}'s work` : "everything the team does, as it happens"}</span></h2>${feed(list.slice(0, 120))}</section>
        <section class="mh-card"><h2 class="hq-h">${icon("layers")}Runs <span class="faint">every model run, traced</span></h2>${runs ? (runs.runs.length ? runTable(runs.runs) : `<div class="empty small">No runs yet.</div>`) : Loading.line("Reading the runs…")}</section></div>`;
  }
  async function openTrace(id) {
    let dlg = $("#mh-trace");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "mh-trace"; dlg.className = "modal wide mh-trace-dlg"; document.body.append(dlg);
      dlg.addEventListener("click", e => {
        if (e.target === dlg || e.target.closest("[data-close]")) return dlg.close();
        const row = e.target.closest("[data-span]"); if (row) { const x = $(`#mh-span-${row.dataset.span}`, dlg); if (x) { x.hidden = !x.hidden; row.setAttribute("aria-expanded", !x.hidden); } }
      });
    }
    dlg.innerHTML = `<div class="hq-dlg-in">${Loading.line("Reading the trace…")}</div>`;
    if (!dlg.open) dlg.showModal();
    try { trace = await api(`/api/mining/runs/${id}`); } catch (e) { dlg.innerHTML = `<div class="hq-dlg-in"><div class="empty">${esc(e.message)}</div></div>`; return; }
    const r = trace.run, sp = trace.spans, P = STAFF(), a = P[r.agent];
    const t0 = r.started, total = Math.max(0.001, (r.finished || Math.max(r.started, ...sp.map(s => s.end))) - t0);
    const out = r.output ? (r.output.answer ? `<div class="md">${Agents.md(r.output.answer)}</div>` : `<pre class="mh-json">${esc(JSON.stringify(r.output, null, 2))}</pre>`) : "";
    dlg.innerHTML = `<div class="hq-dlg-in"><button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>
      <div class="hq-dlg-head">${av(a, "lg")}<div><h3>${esc(a?.name || r.agent)} · ${esc({ analysis: "analysis", tracking: "tracking", plan: "plan", brief: "brief", ask: "question" }[r.kind] || r.kind)}</h3>
        <div class="faint">${stamp(r.started)} · ${r.finished ? dur(r.finished - r.started) : "running"} · ${short(r.tokens)} tokens${r.model ? ` · ${esc(r.model.split(":").pop())}` : ""}</div></div></div>
      ${r.question ? `<p class="mh-q">${icon("chat")}${esc(r.question)}</p>` : ""}${r.error ? `<p class="mh-err">${icon("alert")}${esc(r.error)}</p>` : ""}
      <h4>Trace <span class="faint small">${plural(sp.filter(s => s.kind === "model").length, "model call")}, ${plural(sp.filter(s => s.kind === "tool").length, "tool call")}; click a step for its input and output</span></h4>
      <div class="mh-legend"><span><i class="k-bar s1"></i>Model call</span><span><i class="k-bar s2"></i>Tool call</span></div>
      ${sp.length ? `<ol class="mh-spans">${sp.map(s => { const off = (s.ts - t0) / total * 100, w = Math.max(0.6, (s.end - s.ts) / total * 100);
        return `<li><button type="button" class="mh-span ${s.error ? "err" : ""}" data-span="${s.id}" aria-expanded="false"><span class="mh-span-n">${s.kind === "model" ? icon("sparkle") : icon("wrench")}${esc(s.kind === "model" ? `Model · ${s.name}` : s.name.replace(/_/g, " "))}${s.error ? ` ${icon("alert")}` : ""}</span>
          <span class="mh-span-track"><i class="s${s.kind === "model" ? 1 : 2}" style="left:${off.toFixed(2)}%;width:${Math.min(100 - off, w).toFixed(2)}%"></i></span><span class="mh-span-t num">${dur(s.end - s.ts)}${s.tokens ? ` · ${short(s.tokens)}` : ""}</span></button>
          <div class="mh-span-io" id="mh-span-${s.id}" hidden>${s.input ? `<div><b>${s.kind === "model" ? "Input" : "Arguments"}</b><pre>${esc(s.input)}</pre></div>` : ""}${s.output ? `<div><b>${s.kind === "model" ? "Answer" : "Result"}</b><pre>${esc(s.output)}</pre></div>` : ""}</div></li>`; }).join("")}</ol>`
        : `<p class="faint small">${r.agent === "captain" && !r.tokens ? "No model was used: this brief was written from the numbers." : "No steps recorded."}</p>`}
      ${out ? `<h4>What it filed</h4>${out}` : ""}
      ${trace.events.length ? `<h4>In the feed</h4>${feed(trace.events)}` : ""}</div>`;
    $$("time[data-ts]", dlg).forEach(t => { t.textContent = ago(+t.dataset.ts); });
  }

  // ---------- settings ----------
  function modelOptions(cur) {
    if (!models) { api("/api/agents/models").then(m => { models = m; const s = $("select[name=model]", root()); if (s) s.innerHTML = modelOptions(cur); }).catch(() => { models = { providers: [], default: null }; }); return `<option value="${esc(cur)}">${esc(cur === "auto" ? "Auto" : cur)}</option>`; }
    return [`<option value="auto" ${cur === "auto" ? "selected" : ""}>Auto (the default model${models.default ? `: ${esc(models.default.split(":").pop())}` : ""})</option>`,
      ...models.providers.filter(p => p.models.length).map(p => `<optgroup label="${esc(p.label)}">${p.models.map(m => `<option value="${esc(m.id)}" ${cur === m.id ? "selected" : ""}>${esc(m.label || m.id)}</option>`).join("")}</optgroup>`)].join("");
  }
  function walletPicks(keys) {
    const ws = home.wallets || [];
    if (!ws.length) return `<p class="faint small">Tip: add your wallets on the <a href="#wallet">Wallets</a> page to pick keys here.</p>`;
    return `<div class="mh-picks">${ws.flatMap(w => [[w.coldkey, `${w.name} · coldkey`], ...w.hotkeys.map(h => [h.ss58, `${w.name}/${h.name || "hotkey"}`])]).map(([k, l]) =>
      `<button type="button" class="chip" data-pick="${esc(k)}" aria-pressed="${keys.includes(k)}" title="${esc(k)}">${esc(l)} <code>${hk(k)}</code></button>`).join("")}</div>`;
  }
  function productFields(p, admin) {
    return `<label class="in"><span>Product name</span><input name="product_name" maxlength="80" value="${esc(p.product_name || "")}" placeholder="e.g. Ridges agent v3"></label>
      <label class="in"><span>What it is</span><textarea name="product_notes" rows="4" maxlength="2000" placeholder="Model, approach, hardware, version, what you changed lately, what you can't change (budget, time).">${esc(p.product_notes || "")}</textarea></label>
      <div class="ps-pair"><label class="in"><span>Repository <small class="faint">owner/name on GitHub; Finley reads its activity when the Source hub is connected</small></span><input name="repo" maxlength="140" value="${esc(p.repo || "")}" placeholder="my-org/my-miner"></label>
        ${admin ? `<button type="button" class="btn" data-ps="repo">${icon("plus")}New repository</button>` : ""}</div>
      ${admin ? `<div class="mh-runs-on"><label class="in"><span>Where it runs</span><select name="runs_kind">${[["none", "Elsewhere (actions are manual)"], ["devops", "A DevOps pipeline on this server"], ["app", "An app on this server"]].map(([k, l]) => `<option value="${k}" ${p.runs_kind === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="in"><span>Pipeline or app name</span><input name="runs_name" maxlength="63" value="${esc(p.runs_name || "")}" placeholder="my-miner"></label></div>
        <div class="row ps-acts" ${p.runs_kind === "devops" || p.runs_kind === "app" ? "" : "hidden"}><button type="button" class="btn sm" data-ps="runs">${icon(p.runs_kind === "app" ? "apps" : "rocket")}Create the ${p.runs_kind === "app" ? "app" : "pipeline"}</button>
          <span class="faint small">or type the name of one there is</span></div>
        <p class="faint small">Linked, Kit watches it and the team can propose restarting it (or running its pipeline) for you to approve.</p>` : ""}`;
  }
  function settings() {
    const c = d.campaign, s = c.settings, ch = home.choices;
    const seg = (name, list, cur, fmt) => `<div class="seg" role="radiogroup">${list.map(v => `<label class="mh-radio"><input type="radio" name="${name}" value="${v}" ${v === cur ? "checked" : ""}><span>${fmt(v)}</span></label>`).join("")}</div>`;
    return `<form class="hq-settings mh-settings" autocomplete="off" data-settings data-cid="${c.id}" data-netuid="${c.netuid}">
      <section class="hq-sec"><label class="toggle-row"><span><b>Team at work</b><small class="faint">Paused, no snapshots, alerts or cycles, and nothing is spent. Everything is kept.</small></span>
        <span class="switch"><input type="checkbox" name="live" ${c.status === "live" ? "checked" : ""}><span></span></span></label></section>
      <section class="hq-sec"><h2 class="hq-h">Goal and schedule</h2>
        ${(d.competitions || []).length > 1 || c.mech ? `<label class="in mh-comp-name"><span>This competition's name <small class="faint">SN${c.netuid} runs ${(d.competitions || []).length || "several"} competitions; this team works on competition ${c.mech + 1}</small></span>
          <input name="comp_name" maxlength="40" value="${esc(s.comp_name || "")}" placeholder="Competition ${c.mech + 1}"></label>` : ""}
        <div class="mh-field"><span>Your goal</span>${seg("target", ch.target, s.target, v => `Top ${v}`)}</div>
        <div class="mh-field"><span>Snapshot every</span>${seg("sample_min", ch.sample, s.sample_min, v => `${v} min`)}<small class="faint">Rio reads every miner on chain. No tokens.</small></div>
        <div class="mh-field"><span>Team cycle every</span>${seg("cycle_hours", ch.cycle, s.cycle_hours, v => `${v} h`)}<small class="faint">Analysis, plan and brief. A critical alert brings the next one forward (at most once an hour).</small></div></section>
      <section class="hq-sec"><h2 class="hq-h">How much the team may do on its own</h2><div class="hq-modes">${Object.entries(AUTONOMY).map(([k, [ic, l, t]]) =>
        `<label class="hq-modecard ${s.autonomy === k ? "on" : ""}"><input type="radio" name="autonomy" value="${k}" ${s.autonomy === k ? "checked" : ""}>${icon(ic)}<b>${l}</b><span>${t}</span>${k === "auto" && d.admin ? `<small class="faint">${icon("lock")}Asks you to confirm it's you</small>` : ""}</label>`).join("")}</div>
        <p class="faint small">${d.control ? "Your miner is linked, so the team can propose restarting it." : "Actions on the miner itself need it linked below (administrators, with the miner running on this server); otherwise every action is a task with steps for you."} Nothing is ever signed, registered or staked for you.</p></section>
      <section class="hq-sec hq-fields"><label class="in"><span>Model</span><select name="model">${modelOptions(s.model)}</select><small class="faint">Every agent in this campaign. A smaller model is plenty for most cycles.</small></label>
        <label class="in"><span>Token budget per 24 hours</span><input name="budget" type="number" min="0" step="10000" value="${s.budget}"><small class="faint">${short(d.usage.day)} used in the last 24 hours. 0 means no limit.</small></label></section>
      <section class="hq-sec"><label class="toggle-row"><span><b>Push notifications</b><small class="faint">To your devices: critical alerts right away, actions waiting for you, and a brief that turns red. Quiet hours count, except for critical alerts.</small></span>
        <span class="switch"><input type="checkbox" name="notify" ${s.notify ? "checked" : ""}><span></span></span></label></section>
      <section class="hq-sec"><h2 class="hq-h">Your miners</h2><label class="in"><span>Hotkeys or coldkeys <small class="faint">one per line, public SS58 addresses only; a coldkey covers every UID under it</small></span>
        <textarea name="keys" rows="3" spellcheck="false" placeholder="5F…">${esc(c.keys.join("\n"))}</textarea></label>${walletPicks(c.keys)}</section>
      <section class="hq-sec mh-product"><h2 class="hq-h">Your product</h2>${productFields(c.product, d.admin)}</section>
      ${journalFields()}
      <div class="row end"><button type="submit" class="btn primary">${icon("check")}Save</button></div>
      <section class="hq-sec mh-danger"><h2 class="hq-h">Delete this campaign</h2><p class="faint small">Removes its briefs, runs, alerts and recommendations. Snapshots of the subnet go after two days if nobody else watches it. Results saved to My workspace or GitHub stay there.</p>
        <button type="button" class="btn primary danger" data-mh="delete">${icon("trash")}Delete campaign</button></section></form>`;
  }
  function journalFields() {
    const j = d.journal || {}, c = d.campaign, can = j.can, repos = [...new Set([j.repo, c.product.repo, ...(j.repos || [])].filter(Boolean))];
    const repoIn = repos.length && can ? `<select name="j_repo">${repos.map(r => `<option value="${esc(r)}" ${r === (j.repo || c.product.repo) ? "selected" : ""}>${esc(r)}</option>`).join("")}<option value="__new">+ New private repository…</option></select>`
      : `<input name="j_repo" maxlength="140" value="${esc(j.repo || c.product.repo || "")}" placeholder="my-org/my-miner" ${can ? "" : "disabled"}>`;
    const dv = j.drive || {}, SP = { mine: "My drive", shared: "Shared drive" };
    return `<section class="hq-sec mh-journal"><h2 class="hq-h">${icon("download")}Save results</h2>
      <label class="toggle-row"><span><b>Save each step's results to My workspace</b><small class="faint">Quinn saves the same Markdown file per step to AXoR Drive as the step finishes, and rewrites a README with the latest brief and the recent cycles. No GitHub needed.</small></span>
        <span class="switch"><input type="checkbox" name="j_drive" ${dv.on ? "checked" : ""} ${dv.enabled ? "" : "disabled"}><span></span></span></label>
      <div class="mh-row3 mh-jdrive"><label class="in"><span>Drive</span><select name="j_space" ${dv.enabled ? "" : "disabled"}>${Object.entries(SP).map(([k, l]) => `<option value="${k}" ${k === (dv.space || "mine") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        ${dv.folder ? `<div class="in"><span>&nbsp;</span><button type="button" class="btn" data-open-drive="${esc(dv.folder.space)}:${esc(dv.folder.id)}">${icon("folder")}Open the folder</button></div>` : ""}</div>
      <p class="faint small">Files go to <code>${esc(SP[dv.space] || SP.mine)} › ${esc((dv.path || "").split("/").join(" › "))} › &lt;date&gt; › &lt;time&gt;-cycle-&lt;n&gt;</code>. Only you can read My drive; everyone signed in can read the Shared drive.</p>
      ${!dv.enabled ? `<p class="faint small">${icon("info")}File storage isn't set up on this server.</p>` : dv.on && dv.last?.status === "failed" ? `<p class="mh-err">${icon("alert")}The last save failed: ${esc(dv.last.error || "")}</p>` : ""}
      <h3 class="mh-jsub">${icon("github")}GitHub</h3>
      <label class="toggle-row"><span><b>Commit each step's results</b><small class="faint">Quinn commits one Markdown file per step as the step finishes (snapshot, checks, analysis, tracking, plan, brief), then rewrites a README with the latest brief and the recent cycles.</small></span>
        <span class="switch"><input type="checkbox" name="j_on" ${j.on ? "checked" : ""} ${can ? "" : "disabled"}><span></span></span></label>
      <div class="mh-row3"><label class="in"><span>Repository <small class="faint">on the Source hub's list</small></span>${repoIn}</label>
        <label class="in"><span>Branch</span><input name="j_branch" maxlength="100" value="${esc(j.branch || "mining-hq")}" spellcheck="false" ${can ? "" : "disabled"}></label>
        <label class="in"><span>Folder</span><input name="j_folder" maxlength="160" value="${esc(j.folder || "mining-hq")}" spellcheck="false" ${can ? "" : "disabled"}></label></div>
      <p class="faint small">Files go to <code>${esc(j.folder || "mining-hq")}/sn${c.netuid}/competition-${c.mech + 1}/&lt;date&gt;/&lt;time&gt;-cycle-&lt;n&gt;/</code> on that branch, which is made from the default branch when it's new.
        Keep it off a branch that deploys on push. The Source hub's token needs Contents read and write on the repository, and anyone who can read the repository can read these files.</p>
      ${!j.connected ? `<p class="faint small">${icon("info")}Connect GitHub in the Source view first.</p>` : !d.admin ? `<p class="faint small">${icon("lock")}Only administrators can turn this on: the Source hub's GitHub tokens are theirs.</p>` : ""}
      ${j.on && j.last?.status === "failed" ? `<p class="mh-err">${icon("alert")}The last commit failed: ${esc(j.last.error || "")}</p>` : ""}</section>`;
  }
  // "+ New private repository…" in Save results: made on GitHub (repo-new.js), added to the Source hub's list and picked
  async function newRepo(sel) {
    const prev = sel.dataset.prev && sel.dataset.prev !== "__new" ? sel.dataset.prev : sel.options[0]?.value;
    const r = await RepoNew.open({ name: `sn${d.campaign.netuid}-mining-results`, description: `My subnets results for SN${d.campaign.netuid}` });
    if (!r) { sel.value = prev; return; }
    if (d.journal) d.journal.repos = r.repos;
    const o = document.createElement("option"); o.value = o.textContent = r.repo;
    sel.insertBefore(o, sel.querySelector('option[value="__new"]')); sel.value = r.repo; sel.dataset.prev = r.repo;
  }
  async function saveSettings(f) {
    const v = n => f.elements[n]?.value, checked = n => f.elements[n]?.checked;
    const b = { status: checked("live") ? "live" : "paused", target: +v("target"), sample_min: +v("sample_min"), cycle_hours: +v("cycle_hours"), autonomy: v("autonomy"),
      budget: +v("budget") || 0, notify: checked("notify"), keys: v("keys").split(/[\s,]+/).filter(Boolean), product_name: v("product_name"), product_notes: v("product_notes"), repo: v("repo") };
    if (f.elements.runs_kind) { b.runs_kind = v("runs_kind"); b.runs_name = v("runs_name"); }
    if (f.elements.comp_name) b.comp_name = v("comp_name");
    b.journal = { drive: checked("j_drive"), space: v("j_space") || "mine",
      ...(d.journal?.can ? { on: checked("j_on"), repo: v("j_repo") === "__new" ? "" : v("j_repo") || "", branch: v("j_branch") || "", folder: v("j_folder") || "" } : {}) };
    if (models && v("model") !== d.campaign.settings.model) b.model = v("model");
    const btn = $("button[type=submit]", f);
    const go = async () => { d = await api(`/api/mining/campaigns/${cid}`, { method: "PATCH", body: b }); };
    try {
      btn.classList.add("loading"); btn.disabled = true;
      if (b.autonomy === "auto" && d.campaign.settings.autonomy !== "auto") {
        const ok = await UI.confirm({ title: "Let Avery restart your miner on its own?", icon: "zap", ok: "Turn it on", danger: false,
          body: "When Kit sees your miner down and Avery backs Sage's restart, it runs without asking you: at most once in 6 hours. Everything else still waits for you.",
          run: () => d.admin ? Admin.withSudo(go) : go() });
        if (!ok) return;
      } else await go();
      Auth.toast("Settings saved"); home = await api("/api/mining"); $(".mh-body", root()).dataset.tab = ""; render();
    } catch (e) { err(e); }
    finally { btn.classList.remove("loading"); btn.disabled = false; }
  }

  // ---------- a new campaign ----------
  function newCampaign(preset) {
    let dlg = $("#mh-new");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "mh-new"; dlg.className = "modal mh-new-dlg"; document.body.append(dlg);
      dlg.addEventListener("click", e => {
        if (e.target === dlg || e.target.closest("[data-close]")) return dlg.close();
        const p = e.target.closest("[data-pick]"); if (p) togglePick(p, $("textarea[name=keys]", dlg));
      });
      dlg.addEventListener("change", e => { if (e.target.name === "netuid") pickComps(dlg); });
      dlg.addEventListener("submit", async e => {
        e.preventDefault();
        const f = e.target, v = n => f.elements[n]?.value, btn = $("button[type=submit]", f);
        const boxes = $$("input[name=mechs]", f), mechs = boxes.length ? boxes.filter(x => x.checked && !x.disabled).map(x => +x.value) : [0];
        if (!mechs.length) { Auth.toast("Pick at least one competition for a team"); return; }
        const b = { netuid: +v("netuid"), mechs, target: +v("target"), sample_min: +v("sample_min"), cycle_hours: +v("cycle_hours"), keys: v("keys").split(/[\s,]+/).filter(Boolean),
          product_name: v("product_name"), product_notes: v("product_notes"), repo: v("repo"), ...(f.elements.runs_kind ? { runs_kind: v("runs_kind"), runs_name: v("runs_name") } : {}) };
        btn.classList.add("loading"); btn.disabled = true;
        try { const r = await api("/api/mining/campaigns", { method: "POST", body: b }); dlg.close(); Auth.toast(r.ids?.length > 1 ? `${r.ids.length} teams assembled, one per competition: their first cycles have started` : "Team assembled: the first cycle has started"); home = await api("/api/mining"); await select(r.id); }
        catch (e2) { err(e2); } finally { btn.classList.remove("loading"); btn.disabled = false; }
      });
    }
    const per = {};  // a subnet stays on the list while one of its competitions has no team of yours
    home.campaigns.forEach(c => { per[c.netuid] = { n: (per[c.netuid]?.n || 0) + 1, of: Math.max(c.mechs || 1, per[c.netuid]?.of || 1) }; });
    const subs = (S.data?.subnets || []).filter(r => !per[r.netuid] || per[r.netuid].n < per[r.netuid].of).sort((a, b) => a.netuid - b.netuid);
    const ch = home.choices, opt = (list, cur, f) => list.map(x => `<option value="${x}" ${x === cur ? "selected" : ""}>${f(x)}</option>`).join("");
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" autocomplete="off"><button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>
      <h3>${icon("trophy")} New campaign</h3><p class="faint">One subnet, one goal. You can change everything later in Settings.</p>
      <div class="mh-row"><label class="in"><span>Subnet</span>${subs.length ? `<select name="netuid" required>${subs.map(r => `<option value="${r.netuid}">SN${r.netuid} · ${esc(r.name)}</option>`).join("")}</select>`
        : `<input name="netuid" type="number" min="1" max="4096" required placeholder="netuid, e.g. 62">`}</label>
        <label class="in"><span>Your goal</span><select name="target">${opt(ch.target, 10, v => `Top ${v}`)}</select></label></div>
      <div class="mh-new-comps" aria-live="polite"></div>
      <label class="in"><span>Your miner's hotkeys or coldkey <small class="faint">optional, one per line; public SS58 addresses only</small></span><textarea name="keys" rows="2" spellcheck="false" placeholder="5F…"></textarea></label>
      ${walletPicks([])}
      <details class="mh-more"><summary>Your product and schedule</summary>${productFields({}, home.admin)}
        <div class="mh-row"><label class="in"><span>Snapshot every</span><select name="sample_min">${opt(ch.sample, 30, v => `${v} min`)}</select></label>
          <label class="in"><span>Team cycle every</span><select name="cycle_hours">${opt(ch.cycle, 6, v => `${v} h`)}</select></label></div></details>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("play")}Start the team</button></div></form>`;
    if (preset?.netuid) {
      const sel = $("[name=netuid]", dlg);
      if (sel && (sel.tagName === "INPUT" || sel.querySelector(`option[value="${preset.netuid}"]`))) sel.value = preset.netuid;
    }
    dlg.showModal();
    pickComps(dlg, preset?.mech);
  }
  // a subnet with several competitions: which ones get a team (each its own)
  async function pickComps(dlg, only) {
    const box = $(".mh-new-comps", dlg), n = +($("[name=netuid]", dlg)?.value || 0);
    if (!box) return;
    box.dataset.netuid = n; box.innerHTML = "";
    if (!n) return;
    try {
      const r = await api(`/api/mining/subnets/${n}/competitions`);
      if (box.dataset.netuid !== String(n)) return;
      const list = r.competitions;
      if (list.length < 2) { box.innerHTML = list[0]?.taken ? `<p class="mh-err">${icon("info")}You already have a team on SN${n}.</p>` : ""; return; }
      box.innerHTML = `<fieldset class="mh-pick-comps"><legend>SN${n} runs ${list.length} competitions <small class="faint">each ranks miners on its own and pays its share of the rewards; each one you pick gets its own team</small></legend>
        ${list.map(c => `<label class="mh-check"><input type="checkbox" name="mechs" value="${c.mech}" ${c.taken ? "disabled" : only == null || only === c.mech ? "checked" : ""}><span><b>${esc(c.name)}</b>
          <span class="faint">${fmtNum(c.share * 100, 0)}% of the rewards${c.taken ? " · you have a team on it" : ""}</span></span></label>`).join("")}</fieldset>`;
    } catch (e) { if (box.dataset.netuid === String(n)) box.innerHTML = ""; }
  }
  function togglePick(btn, area) {
    const k = btn.dataset.pick, keys = area.value.split(/[\s,]+/).filter(Boolean), on = keys.includes(k);
    area.value = (on ? keys.filter(x => x !== k) : [...keys, k]).join("\n");
    btn.setAttribute("aria-pressed", !on);
  }

  // ---------- actions ----------
  async function run(agents, note) {
    try { await api(`/api/mining/campaigns/${cid}/run`, { method: "POST", body: { note, agents } }); Auth.toast(agents.length ? "On it" : "Cycle started"); await refresh(); }
    catch (e) { err(e); }
  }
  async function runDialog() {
    let dlg = $("#mh-run");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "mh-run"; dlg.className = "modal"; document.body.append(dlg);
      dlg.addEventListener("click", e => { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); });
      dlg.addEventListener("submit", async e => { e.preventDefault(); const note = e.target.elements.note.value.trim(); dlg.close(); await run([], note); });
    }
    dlg.innerHTML = `<form class="hq-dlg-in"><button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button><h3>${icon("play")} Run a cycle now</h3>
      <p class="faint">A fresh snapshot, then analysis, the plan and a brief. ${d.usage.budget ? `${short(d.usage.day)} of ${short(d.usage.budget)} tokens used in the last 24 hours.` : ""}</p>
      <label class="in"><span>A note for the team <small class="faint">optional, for this cycle only</small></span><textarea name="note" rows="3" maxlength="600" placeholder="e.g. We shipped v2 an hour ago: did it help?"></textarea></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("play")}Run it</button></div></form>`;
    dlg.showModal();
  }
  async function decide(id, decision, btn) {
    const a = d.actions.find(x => x.id === id);
    btn.classList.add("loading"); btn.disabled = true;
    try {
      const go = () => api(`/api/mining/actions/${id}`, { method: "POST", body: { decision } });
      const r = a?.on_miner && decision === "approve" ? await Admin.withSudo(go) : await go();
      if (r.status === "failed") throw new Error(r.message);
      Auth.toast({ done: a?.on_miner ? `Done: ${a.title}` : "Marked done", rejected: "Rejected", dismissed: "Dismissed" }[r.status] || "Saved");
    } catch (e) { err(e); }
    await refresh();
  }
  async function setRec(id, status, note = "") {
    try { await api(`/api/mining/recs/${id}`, { method: "PATCH", body: { status, note } }); dismissing = null; Auth.toast({ accepted: "Noted: you're on it", done: "Marked done", dismissed: "Dismissed" }[status]); }
    catch (e) { err(e); }
    await refresh();
  }

  function wire() {
    if (wired) return; wired = true;
    root().addEventListener("click", async e => {
      const t = e.target;
      const cp = t.closest("[data-copy]"); if (cp) { navigator.clipboard?.writeText(cp.dataset.copy).then(() => Auth.toast("Copied")); return; }
      if (t.closest("[data-mhcmd]")) { cmd = true; store.set("mh.cmd", true); es?.close(); es = null; clearTimeout(timer); return render(); }
      const camp = t.closest("[data-camp]"); if (camp) { cmd = false; store.set("mh.cmd", false); MiningCommand.stop(); return select(+camp.dataset.camp); }
      const tb = t.closest("[data-mhtab]") || t.closest("[data-mhgo]");
      if (tb) { tab = tb.dataset.mhtab || tb.dataset.mhgo; store.set("mh.tab", tab); render(); return loadTab(); }
      const dy = t.closest("[data-days]"); if (dy) { days = +dy.dataset.days; field = mine = null; render(); return loadTab(); }
      const fm = t.closest("[data-fmech]");
      if (fm) { fieldMech = fm.dataset.fmech === "all" ? "all" : +fm.dataset.fmech === d.campaign.mech ? null : +fm.dataset.fmech; field = null; query = ""; tab = "competition"; store.set("mh.tab", tab); render(); return loadTab(); }
      const w = t.closest("[data-who]"); if (w) { who = w.dataset.who; runs = null; render(); return loadTab(); }
      const tr = t.closest("[data-trace]"); if (tr) return openTrace(+tr.dataset.trace);
      const fr = t.closest("[data-mfrun]"); if (fr) { fr.disabled = true; return run(MiningFlow.FROM[fr.dataset.mfrun] || [], ""); }
      const fo = t.closest("[data-mfoff]"); if (fo) return setOn(fo.dataset.mfoff, fo.getAttribute("aria-pressed") === "true", fo);
      const cl = t.closest("[data-mhclone]"); if (cl) return cloneTeam(+cl.dataset.mhclone);
      const ag = t.closest("[data-agent]"); if (ag) return agentCard(ag.dataset.agent);
      const pk = t.closest("[data-pick]"); if (pk) return togglePick(pk, $("textarea[name=keys]", root()));
      const act = t.closest("[data-mhact]"); if (act) return decide(+act.closest("[data-action]").dataset.action, act.dataset.mhact, act);
      const rec = t.closest("[data-mhrec]");
      if (rec) {
        const id = +rec.closest("[data-rec]").dataset.rec, s = rec.dataset.mhrec;
        if (s === "dismiss") { dismissing = id; render(); $(`[data-dismiss="${id}"] input`, root())?.focus(); return; }
        if (s === "cancel") { dismissing = null; return render(); }
        return setRec(id, s);
      }
      const b = t.closest("[data-mh]"); if (!b) return;
      const k = b.dataset.mh;
      if (k === "new") return newCampaign();
      if (k === "run") return runDialog();
      if (k === "pause") {
        const on = d.campaign.status === "live"; b.disabled = true;
        try {
          d = await api(`/api/mining/campaigns/${cid}`, { method: "PATCH", body: { status: on ? "paused" : "live" } }); home = await api("/api/mining");
          Auth.toast(!on ? "Back to work" : d.running ? "Paused: the running cycle finishes first" : "Paused: no snapshots, alerts or cycles until you resume");
        } catch (e2) { err(e2); }
        b.disabled = false; return render();
      }
      if (k === "cancel") { b.disabled = true; try { await api(`/api/mining/campaigns/${cid}/cancel`, { method: "POST" }); Auth.toast("Stopping after the current step"); } catch (e2) { err(e2); } return; }
      if (k === "all") { showAll = !showAll; return render(); }
      if (k === "ack") { try { await api(`/api/mining/alerts/${b.closest("[data-alert]").dataset.alert}/ack`, { method: "POST" }); } catch (e2) { err(e2); } return refresh(); }
      if (k === "briefs") return briefsDialog();
      if (k === "delete") {
        const c = d.campaign;
        const what = (d.competitions || []).length > 1 || c.mech ? `SN${c.netuid} ${c.comp}` : `SN${c.netuid}`;
        await UI.confirm({ title: `Delete the ${what} team?`, body: "Its briefs, runs, traces, alerts and recommendations go too; files it saved to a repository stay there. This can't be undone.", ok: "Delete", typed: `SN${c.netuid}`,
          run: async () => { await api(`/api/mining/campaigns/${cid}`, { method: "DELETE" }); Auth.toast("Campaign deleted"); stop(); home = d = null; cid = null; store.set("mh.cid", null); await open(); } }).catch(err);
      }
    });
    root().addEventListener("input", e => {
      if (e.target.matches("[data-mhq]")) { query = e.target.value; const pos = e.target.selectionStart; render(); const i = $("[data-mhq]", root()); if (i) { i.focus(); i.setSelectionRange(pos, pos); } }
    });
    root().addEventListener("change", e => { if (e.target.name === "autonomy") $$(".hq-modecard", root()).forEach(c => c.classList.toggle("on", c.contains(e.target))); });
    root().addEventListener("focusin", e => { if (e.target.name === "j_repo") e.target.dataset.prev = e.target.value; });
    root().addEventListener("change", e => { if (e.target.name === "j_repo" && e.target.value === "__new") newRepo(e.target); });
    root().addEventListener("ps:linked", e => { d = e.detail; });  // product-setup.js linked a new repository, pipeline or app
    root().addEventListener("submit", async e => {
      e.preventDefault();
      const f = e.target;
      if (f.matches("[data-settings]")) return saveSettings(f);
      if (f.matches("[data-directive]")) return saveDirective(f);
      if (f.matches("[data-dismiss]")) return setRec(+f.dataset.dismiss, "dismissed", f.elements.note.value.trim());
      if (f.matches("[data-ask]")) {
        const q = f.elements.q.value.trim(); if (q.length < 2) return;
        const btn = $("button[type=submit]", f); btn.classList.add("loading"); btn.disabled = true;
        try { await api(`/api/mining/campaigns/${cid}/ask`, { method: "POST", body: { question: q } }); f.elements.q.value = ""; await refresh(); }
        catch (e2) { err(e2); } finally { btn.classList.remove("loading"); btn.disabled = false; }
      }
    });
    root().addEventListener("keydown", e => { if (e.key === "Enter" && e.target.closest("tr[data-trace]")) openTrace(+e.target.closest("tr[data-trace]").dataset.trace); });
    let resized;
    window.addEventListener("resize", () => { if ($("#view-mining").hidden) return; clearTimeout(resized); resized = setTimeout(() => { if (tab === "competition") drawCompetition(); if (tab === "mine") drawMine(); }, 150); });
    setInterval(() => { if (!$("#view-mining").hidden) times(); }, 30000);
  }
  async function briefsDialog() {
    let dlg = $("#mh-briefs");
    if (!dlg) { dlg = document.createElement("dialog"); dlg.id = "mh-briefs"; dlg.className = "modal wide"; document.body.append(dlg); dlg.addEventListener("click", e => { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); }); }
    const list = briefs?.briefs || [];
    dlg.innerHTML = `<div class="hq-dlg-in"><button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button><h3>${icon("star")} Briefs</h3>
      <ol class="mh-briefs">${list.map(b => { const [cls, l] = TONE[b.standing] || TONE.amber; return `<li class="t-${cls}"><div class="faint small">${stamp(b.ts)} · ${l}${b.author === "captain" ? "" : " · from the numbers"}</div>
        <b>${esc(b.headline)}</b>${b.summary ? `<p>${esc(b.summary)}</p>` : ""}${b.priorities.length ? `<ol>${b.priorities.map(p => `<li>${esc(p)}</li>`).join("")}</ol>` : ""}</li>`; }).join("")}</ol></div>`;
    dlg.showModal();
  }

  // ---------- the sidebar's count: actions waiting for your approval and critical alerts ----------
  function badge(n) {
    const c = $("#c-mining"); if (!c) return;
    if (n == null && home) n = home.campaigns.reduce((s, x) => s + (x.critical || 0), 0) + (d ? d.actions.filter(a => a.status === "awaiting").length : 0);
    c.textContent = n || "";
  }
  let polling = false;
  function init() {
    if (polling || !Auth.me() || !$("#c-mining")) return;
    polling = true;
    const tick = () => { if ($("#nav-mining")?.hidden || document.visibilityState !== "visible") return; api("/api/mining/badge").then(b => badge(b.waiting + b.critical)).catch(() => {}); };
    setTimeout(tick, 1500); setInterval(tick, 60000);
  }

  // ---------- the Explorer's subnet drawer: a Competitions card (app.js puts compsCard() in; it fills itself) ----------
  function compsCard(netuid) {
    setTimeout(() => fillComps(netuid), 0);
    return `<div class="card mh-xcomps" id="mh-xcomps-${netuid}"><h3>${icon("columns")}Competitions</h3><div class="mh-xc-body">${Loading.line("Reading the subnet's competitions…")}</div></div>`;
  }
  async function fillComps(netuid) {
    let el = $(`#mh-xcomps-${netuid}`); if (!el) return;
    if (!xcomps[netuid]) {
      try { xcomps[netuid] = await api(`/api/mining/subnets/${netuid}/competitions?detail=1`); }
      catch (e) { el = $(`#mh-xcomps-${netuid}`); if (el) $(".mh-xc-body", el).innerHTML = `<p class="muted" style="margin:0">${esc(e.message)}</p>`; return; }
      el = $(`#mh-xcomps-${netuid}`); if (!el) return;
    }
    const r = xcomps[netuid], list = r.competitions, sel = list.find(x => x.mech === xsel[netuid]) || list[0];
    const hq = !$("#nav-mining")?.hidden;
    if (list.length < 2) {
      $(".mh-xc-body", el).innerHTML = `<p class="muted" style="margin:0">One competition: every miner is ranked on the same incentive and shares the same rewards.</p>`;
      return;
    }
    const kv = (l, v) => `<div><span>${l}</span><b>${v}</b></div>`;
    $(".mh-xc-body", el).innerHTML = `<p class="muted" style="margin:0 0 10px">SN${netuid} runs ${list.length} competitions (on-chain incentive mechanisms). Each ranks miners on its own and pays its share of the miners' rewards; the same UIDs compete in all of them.</p>
      <div class="mh-split">${list.map((x, i) => `<i class="${["s1", "s2", "s3"][i % 3]}" style="flex:${Math.max(x.share, 0.001)}" title="${esc(x.name)}: ${pct(x.share, 0)}"></i>`).join("")}</div>
      <div class="seg mh-xc-tabs" role="tablist" aria-label="SN${netuid}'s competitions">${list.map(x => `<button type="button" role="tab" data-xc="${x.mech}" aria-selected="${x === sel}" aria-pressed="${x === sel}">${esc(x.name)} · ${pct(x.share, 0)}</button>`).join("")}</div>
      <div class="kv">${kv("Share of the miners' rewards", pct(sel.share, 0))}${kv("Miners' rewards", `${fmtNum(sel.pool)} τ/day`)}${kv("Earning miners", `${sel.earners} of ${sel.miners}`)}
        ${kv("Leader", sel.top1_uid == null ? "–" : `UID ${sel.top1_uid} · ${fmtNum(sel.top1)} τ/day`)}${kv("Leader's share", pct(sel.share1, 0))}${kv("Top 10 share", pct(sel.share10, 0))}</div>
      ${sel.top.length ? `<div class="tablewrap flat"><table class="grid mini-table"><thead><tr><th>#</th><th>UID</th><th>Hotkey</th><th class="r">τ / day</th><th class="r">Incentive</th></tr></thead>
        <tbody>${sel.top.map(b => `<tr><td class="num">${b.rank}</td><td class="num">${b.uid}</td><td><code title="${esc(b.hk)}">${hk(b.hk)}</code></td><td class="r num">${fmtNum(b.em)}</td><td class="r num">${pct(b.inc, 1)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="muted">Nobody earns in this competition yet.</p>`}
      ${hq ? `<div class="row" style="margin-top:10px">${sel.campaign ? `<button type="button" class="btn sm" data-xc-open="${sel.campaign}">${icon("trophy")}Open it in My subnets</button>`
        : `<button type="button" class="btn sm" data-xc-new="${sel.mech}">${icon("plus")}Add it to My subnets</button>`}</div>` : ""}
      <p class="fine">At block ${(r.block || 0).toLocaleString()}${r.ts ? `, ${ago(r.ts)}` : ""}. A miner's rewards in a competition: the miners' pool × the competition's share × its incentive there.</p>`;
    el.onclick = e => {
      const b = e.target.closest("[data-xc]"); if (b) { xsel[netuid] = +b.dataset.xc; return fillComps(netuid); }
      const o = e.target.closest("[data-xc-open]");
      if (o) { store.set("mh.cid", +o.dataset.xcOpen); store.set("mh.tab", "competition"); store.set("mh.cmd", false); cid = tab = null; closeDrawer(); return setView("mining"); }
      const n = e.target.closest("[data-xc-new]"); if (n) { pendingNew = { netuid, mech: +n.dataset.xcNew }; closeDrawer(); setView("mining"); }
    };
  }

  // a campaign's tab, from the Command center
  function camp(id, t) { cmd = false; store.set("mh.cmd", false); MiningCommand.stop(); tab = t || "overview"; store.set("mh.tab", tab); return select(id, true); }
  // the My subnets shell's rail and search (mining-shell.js), from this page or another: {cmd: section, wid?}, {tab} on the open campaign, {camp, tab}
  function nav(r) {
    const c = !!r.cmd, shown = !$("#view-mining").hidden;
    store.set("mh.cmd", c);
    if (c) MiningCommand.go(r.cmd, r.wid);  // loads only while mounted
    else { store.set("mh.tab", r.tab || "overview"); if (r.camp != null) store.set("mh.cid", r.camp); }
    if (tab === null) return setView("mining");  // the first open reads the store
    if (!shown) { cmd = c; if (!c) { tab = r.tab || "overview"; if (r.camp != null) cid = r.camp; } return setView("mining"); }
    if (c) { if (!cmd) { cmd = true; es?.close(); es = null; clearTimeout(timer); render(); } return; }
    if (cmd || (r.camp != null && r.camp !== cid)) return camp(r.camp ?? cid, r.tab);
    tab = r.tab || "overview"; render(); return loadTab();
  }

  return { open, stop, init, compsCard, camp, nav };
})();

