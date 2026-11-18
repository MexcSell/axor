/* Missions and tasks in the Control Hub (control_missions.py: /api/control/missions…, /api/control/mission-tasks/…). Prefix ctlm-.
   Two levels kept apart, with Bittensor as the primary initiative:
     Mission = what the company wants to achieve: predefined (a Bittensor competition, from the mission wizard) or custom
               (a Mission Control goal).
     Task    = what agents do to get there: fixed (from the competition template: mandatory, some recurring) or dynamic
               (made by you, an agent or Mission Intelligence); a task may have subtasks, or stand alone.
   - missionsSec(): the Live operations area's "Missions" tab: initiatives (Bittensor first), their missions, and one mission's
     page (fixed tasks, dynamic tasks with subtasks, Mission Intelligence and its proposals, custom missions launched for it).
   - tasksSec(): the "Tasks" tab: every task by level (fixed, dynamic, subtasks, standalone, proposals), grouped by mission.
   - band(hub): the Overview's "Primary initiative · Bittensor" line.
   - openMission(ref): the Missions tab on that mission (the team page's mission card links here).
   - teamLine(unitRef): the team page's "Serves missions" line (lead or supporting).
   A predefined mission has a lead team (its Competition team) and any number of supporting teams; Mission Intelligence
   runs when asked, and in Auto mode also on a daily schedule (held by budget or by its own open tasks).
   control.js draws the hub synchronously, so each section renders from its last answer and refreshes in the background. */
const CtlMissions = (() => {
  const B = "/api/control";
  const ST = { proposed: ["new", "Proposed"], todo: ["muted", "To do"], running: ["clear", "Running"], review: ["caution", "For review"], needs_input: ["caution", "Needs you"],
               done: ["clear", "Done"], failed: ["scam", "Failed"], cancelled: ["muted", "Cancelled"], skipped: ["muted", "Skipped"] };
  const MX = { queued: "Queued", running: "Running", needs_input: "Needs you", paused: "Paused", delivered: "Delivered", done: "Done", failed: "Failed", cancelled: "Cancelled" };
  const GAP = { met: ["clear", "On target", "check"], behind: ["caution", "Behind", "up"], unknown: ["muted", "No rank yet", "info"], unset: ["muted", "No target", "info"] };
  const OUT = { created: ["clear", "Created"], proposed: ["new", "Waiting for you"], covered: ["muted", "Already covered"], applied: ["clear", "Applied"], suggested: ["new", "Suggested"] };
  const cache = { list: null, detail: {} }, busy = {}, at = {};
  let open = null, filter = "open", intelBusy = false;

  const badge = (tone, text, ic = "", title = "") => `<span class="badge ${tone}"${title ? ` title="${esc(title)}"` : ""}>${ic ? icon(ic) : ""}${esc(text)}</span>`;
  const st = s => { const [t, l] = ST[s] || ["muted", s || "–"]; return badge(t, l); };
  const tok = n => n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(n);
  const when = ts => ts ? ago(ts) : "";
  const prio = p => p === "high" ? `<span class="ctlm-prio hi" title="High priority">${icon("up")}</span>` : p === "low" ? `<span class="ctlm-prio lo" title="Low priority">${icon("down")}</span>` : "";
  const isOpen = s => ["proposed", "todo", "running", "review", "needs_input"].includes(s);
  const allTeams = () => typeof Control !== "undefined" && Control.teams ? Control.teams() : [];
  const leadOf = ref => { const ms = [...(cache.list?.initiatives || []).flatMap(i => i.missions), ...Object.values(cache.detail).map(d => d.mission).filter(Boolean)];
                          return ms.find(m => m.ref === ref)?.teams?.find(t => t.role === "lead")?.ref; };
  const teamName = id => { const n = id ? allTeams().find(x => x.id === id)?.name || "" : ""; return n.length > 40 ? n.slice(0, 39) + "…" : n; };

  async function load(key, path, then) {
    if (busy[key]) return;
    busy[key] = true;
    try { const d = await api(path); if (key === "list") cache.list = d; else cache.detail[key] = d; at[key] = Date.now(); then?.(); }
    catch (e) { if (key === "list") cache.list = { error: e.message }; else cache.detail[key] = { error: e.message }; then?.(); }
    finally { busy[key] = false; }
  }
  const redraw = () => {
    const el = document.getElementById("ctlm-root"); if (el) el.innerHTML = body();
    document.querySelectorAll("[data-ctlm-team]").forEach(x => { x.innerHTML = teamHtml(x.dataset.ctlmTeam); });  // a team page's "Serves" line
  };
  function want(key, path) {
    const have = key === "list" ? cache.list : cache.detail[key];
    if (!busy[key] && (!have || Date.now() - (at[key] || 0) > 15000)) load(key, path, redraw);
    return have;
  }
  const loading = `<p class="faint ctlm-load">${icon("cycle")}Loading…</p>`;
  const fail = d => `<p class="ctl-warn">${icon("alert")}${esc(d.error)}</p>`;

  // ---------- the Missions tab ----------
  let mode = "missions";
  function missionsSec() { mode = "missions"; return `<div id="ctlm-root" class="ctlm">${body()}</div>`; }
  function tasksSec() { mode = "tasks"; open = null; return `<div id="ctlm-root" class="ctlm">${body()}</div>`; }
  function body() {
    if (mode === "tasks") { const d = want("list", `${B}/missions`); return !d ? loading : d.error ? fail(d) : tasksView(d); }
    if (open) { const d = want(open, `${B}/missions/${encodeURIComponent(open)}`); return !d ? loading : d.error ? `${back()}${fail(d)}` : detail(d); }
    const d = want("list", `${B}/missions`); return !d ? loading : d.error ? fail(d) : listView(d);
  }
  const legend = () => `<p class="ctlm-legend">${icon("info")}<span><b>Mission</b> = what the company wants to achieve: <i>predefined</i> (a Bittensor competition) or <i>custom</i> (a Mission Control goal).
      <b>Task</b> = what agents do to get there: <i>fixed</i> (mandatory, from the competition template) or <i>dynamic</i> (made by you, an agent or Mission Intelligence).</span></p>`;
  function listView(d) {
    const [bt, other] = d.initiatives, s = bt.summary, c = d.counts;
    const fact = (l, v, sub = "") => `<div class="ctlm-fact"><small>${esc(l)}</small><b>${v}</b>${sub ? `<em>${sub}</em>` : ""}</div>`;
    return `${legend()}
      <section class="ctlm-init primary" aria-labelledby="ctlm-bt">
        <header class="ctlm-ih"><span class="ctlm-iic">${icon("nodes")}</span><div><h3 id="ctlm-bt">${esc(bt.name)} ${badge("clear", "Primary initiative", "flag")}</h3><p class="faint small">${esc(bt.about)}</p></div>
          <div class="ctlm-iacts"><button type="button" class="btn primary sm" data-act="wizard">${icon("plus")}New Bittensor mission</button></div></header>
        <div class="ctlm-facts">${fact("Subnets", s.subnets)}${fact("Predefined missions", s.predefined, s.custom ? `+ ${s.custom} custom` : "")}
          ${fact("On target", s.met, s.behind ? `${s.behind} behind` : "")}${fact("Best rank", s.best_rank ?? "–")}
          ${fact("Tokens today", tok(s.tokens_today), s.share_today != null ? `${Math.round(s.share_today * 100)}% of all agent work` : "")}</div>
        ${bt.missions.length ? `<div class="ctlm-cards">${bt.missions.map(card).join("")}</div>`
          : `<p class="ctl-cc-empty">No Bittensor mission yet. <button type="button" class="linkbtn" data-act="wizard">Start one on a subnet's competition</button>: it brings its team, its target rank and its fixed tasks.</p>`}
      </section>
      <section class="ctlm-init" aria-labelledby="ctlm-ot">
        <header class="ctlm-ih"><span class="ctlm-iic">${icon("target")}</span><div><h3 id="ctlm-ot">${esc(other.name)}</h3><p class="faint small">${esc(other.about)}</p></div>
          <div class="ctlm-iacts"><button type="button" class="btn sm" data-goview="mos">${icon("plus")}New custom mission</button></div></header>
        ${other.missions.length ? `<div class="ctlm-cards">${other.missions.map(card).join("")}</div>` : `<p class="faint small">None. A custom mission is a goal with a budget and a deadline, planned by Mission Control.</p>`}
      </section>
      <p class="faint small ctlm-foot">${c.tasks_open} open task${c.tasks_open === 1 ? "" : "s"} (${c.fixed_open} fixed · ${c.dynamic_open} dynamic${c.standalone_open ? ` · ${c.standalone_open} standalone` : ""}), ${c.in_progress ?? 0} under way (running or in review)${d.dispatch?.stuck ? ` · <b>${d.dispatch.stuck} not moving for over an hour</b>` : ""}${c.proposed ? ` · <b>${c.proposed} proposal${c.proposed === 1 ? "" : "s"} waiting for you</b>` : ""}.
        <button type="button" class="linkbtn" data-ctlm-tasks>See every task</button></p>`;
  }
  function card(m) {
    if (m.type === "predefined") {
      const [tone, l, ic] = GAP[m.gap.state] || GAP.unset, t = m.tasks, pct = t.fixed_total ? Math.round(t.fixed_done / t.fixed_total * 100) : 0;
      return `<button type="button" class="ctlm-card" data-ctlm-open="${esc(m.ref)}">
        <span class="ctlm-ct">${badge("new", "Predefined")}<small>SN${m.subnet}</small></span>
        <b class="ctlm-cn">${esc(m.title)}</b>
        <span class="ctlm-cl">${m.target_rank ? `Target top ${m.target_rank}` : "No target yet"} · ${m.standing?.rank ? `rank ${m.standing.rank}${m.standing.of ? ` of ${m.standing.of}` : ""}` : "no rank yet"} ${badge(tone, l, ic)}</span>
        <span class="ctlm-prog" title="Fixed tasks done"><i style="width:${pct}%"></i></span>
        <small class="ctlm-cs">Fixed ${t.fixed_done}/${t.fixed_total} · ${t.dynamic} dynamic open${(m.teams || []).length > 1 ? ` · ${m.teams.length} teams` : ""}${t.proposed ? ` · <b>${t.proposed} proposed</b>` : ""}</small></button>`;
    }
    return `<button type="button" class="ctlm-card" data-ctlm-open="${esc(m.ref)}">
      <span class="ctlm-ct">${badge("muted", "Custom")}<small>${esc(MX[m.status] || m.status || "")}</small></span>
      <b class="ctlm-cn">${esc(m.title)}</b>
      <span class="ctlm-cl">${m.parent_title ? `For ${esc(m.parent_title)}` : "Mission Control"}${m.stage ? ` · ${esc(m.stage)}` : ""}</span>
      ${m.progress != null ? `<span class="ctlm-prog"><i style="width:${Math.round((m.progress > 1 ? m.progress : m.progress * 100))}%"></i></span>` : ""}
      <small class="ctlm-cs">${m.tasks.plan ? `${m.tasks.plan} planned task${m.tasks.plan === 1 ? "" : "s"}` : "Not planned yet"}${m.from_task ? ` · from task #${m.from_task}` : ""}</small></button>`;
  }

  // ---------- one mission ----------
  const back = () => `<button type="button" class="linkbtn ctlm-back" data-ctlm-back>${icon("left")}All missions</button>`;
  function taskRow(t, kids = []) {
    const acts = [];
    if (t.status === "proposed") acts.push(`<button type="button" class="btn primary sm" data-ctlm-decide="${t.id}" data-ok="1">Approve</button>`, `<button type="button" class="btn sm" data-ctlm-decide="${t.id}" data-ok="0">Decline</button>`);
    else {
      if (t.kind === "fixed" && (t.status === "todo" && !t.ref)) acts.push(`<button type="button" class="btn sm" data-ctlm-run="${t.id}">${icon("play")}Start</button>`);
      if (t.kind === "fixed" && t.status !== "skipped" && !["running", "review"].includes(t.status)) acts.push(`<button type="button" class="iconbtn sm" data-ctlm-skip="${t.id}" data-on="1" title="Not needed for this mission" aria-label="Skip ${esc(t.title)}">${icon("minus")}</button>`);
      if (t.status === "skipped") acts.push(`<button type="button" class="btn sm" data-ctlm-skip="${t.id}" data-on="0">Needed again</button>`);
      if (t.kind !== "fixed" && t.route !== "mission" && isOpen(t.status)) acts.push(`<button type="button" class="iconbtn sm" data-ctlm-sub="${t.id}" title="Add a subtask" aria-label="Add a subtask to ${esc(t.title)}">${icon("plus")}</button>`);
      acts.push(`<button type="button" class="iconbtn sm" data-ctlm-edit="${t.id}" title="Edit" aria-label="Edit ${esc(t.title)}">${icon("edit")}</button>`);
    }
    const meta = [t.kind === "fixed" ? (t.cadence_days ? `every ${t.cadence_days} day${t.cadence_days === 1 ? "" : "s"}${t.due ? ` · due ${new Date(t.due * 1000).toLocaleDateString()}` : ""}` : "mandatory") : "",
                  t.status === "proposed" ? "" : t.route === "board" ? (t.ref ? "on the team's board" : "not started") : t.route === "mission" ? "runs as a custom mission" : "agent run",
                  t.team && t.team !== leadOf(t.mission) ? teamName(t.team) : "", t.agent || "", t.origin === "intelligence" ? "from Mission Intelligence" : t.origin === "template" ? "competition template" : "", t.summary && t.status !== "proposed" ? t.summary : ""].filter(Boolean).join(" · ");
    return `<li class="ctlm-t ${t.status}"><div class="ctlm-tr"><span class="ctlm-tm">${prio(t.priority)}<button type="button" class="linkbtn ctlm-tt" data-task="${t.id}">${esc(t.title)}</button>
        <small>${esc(meta)}</small>${t.why && !["moving", "review", "decision"].includes(t.why.state) ? `<small class="ctlm-stall s-${esc(t.why.state)}" title="Why it isn't moving (the dispatcher's reading)">${icon(["dispatch", "retry", "busy", "queued"].includes(t.why.state) ? "clock" : "alert")}${esc(t.why.text)}${t.why.owner ? ` · next: ${esc(t.why.owner)}` : ""}</small>` : ""}${t.status === "proposed" && t.detail ? `<small class="ctlm-why">${esc(t.detail.split("\n\nWhy: ").pop())}</small>` : ""}</span>
        <span class="ctlm-ta">${st(t.status)}${acts.join("")}</span></div>
      ${kids.length ? `<ul class="ctlm-kids">${kids.map(k => taskRow(k)).join("")}</ul>` : ""}</li>`;
  }
  function nest(ts) {
    const by = {}, ids = new Set(ts.map(t => t.id));
    for (const t of ts) if (t.parent_id && ids.has(t.parent_id)) (by[t.parent_id] = by[t.parent_id] || []).push(t);
    return ts.filter(t => !(t.parent_id && ids.has(t.parent_id))).map(t => taskRow(t, by[t.id] || []));
  }
  function detail(d) {
    const m = d.mission;
    if (m.type === "custom") {
      return `${back()}<header class="ctlm-dh"><div><p class="ctlm-ct">${badge("muted", "Custom mission")}${m.initiative === "bittensor" ? badge("clear", "Bittensor", "flag") : ""}</p><h2>${esc(m.title)}</h2>
          <p class="faint small">${esc(MX[m.status] || m.status)}${m.stage ? ` · ${esc(m.stage)}` : ""}${m.parent_title ? ` · for <button type="button" class="linkbtn" data-ctlm-open="${esc(m.parent)}">${esc(m.parent_title)}</button>` : ""}${m.from_task ? ` · from <button type="button" class="linkbtn" data-task="${m.from_task}">task #${m.from_task}</button>` : ""}</p></div>
          <div class="ctlm-iacts"><button type="button" class="btn sm" data-goview="mos">${icon("external")}Open in Mission Control</button><button type="button" class="btn sm" data-ctlj-open="${esc(m.ref)}">${icon("route")}Journey</button></div></header>
        <section class="card ctl-card"><div class="ctl-h"><h3>${icon("list")}Dynamic tasks <small class="faint">planned by the mission engine</small></h3></div>
          ${d.plan.length ? `<ol class="ctlm-plan">${d.plan.map(p => `<li><b>${esc(p.title || "")}</b><small>${esc([p.owner, p.done_when ? `done when ${p.done_when}` : "", p.depends.length ? `after ${p.depends.join(", ")}` : ""].filter(Boolean).join(" · "))}</small></li>`).join("")}</ol>`
            : `<p class="faint">Not planned yet: the engine plans a custom mission's tasks after it understands the goal.</p>`}
          <p class="faint small">A custom mission's engine creates and revises its own tasks; Mission Intelligence works on predefined missions.</p></section>`;
    }
    const [tone, l, ic] = GAP[m.gap.state] || GAP.unset;
    const intel = d.intelligence;
    const facts = `<div class="ctlm-facts">
        <div class="ctlm-fact"><small>Target</small><b>${m.target_rank ? `Top ${m.target_rank}` : "–"}</b></div>
        <div class="ctlm-fact"><small>Rank now</small><b>${m.standing?.rank ?? "–"}${m.standing?.of ? `<span class="faint"> / ${m.standing.of}</span>` : ""}</b></div>
        <div class="ctlm-fact"><small>Deadline</small><b>${esc(m.deadline || "–")}</b></div>
        <div class="ctlm-fact"><small>Budget today</small><b>${tok(m.used_today)}<span class="faint"> / ${tok(m.budget)}</span></b></div></div>`;
    const fixedDone = d.fixed.filter(t => t.status === "done").length, fixedAll = d.fixed.filter(t => t.status !== "skipped").length;
    return `${back()}<header class="ctlm-dh"><div><p class="ctlm-ct">${badge("new", "Predefined mission")}${badge("clear", "Bittensor", "flag")}<small>SN${m.subnet}</small></p><h2>${esc(m.title)}</h2>
          <p>${esc(m.objective || "Reach and hold the target rank.")}</p><p class="ctlm-gap">${badge(tone, l, ic)} ${esc(m.gap.text)}</p></div>
        <div class="ctlm-iacts"><button type="button" class="btn sm" data-fixed="${m.comp_id}">${icon("target")}${m.configured ? "Edit mission" : "Configure"}</button>
          ${m.unit ? `<button type="button" class="btn sm" data-go="${esc(m.unit)}">${icon("users")}Team</button>` : ""}<button type="button" class="btn sm" data-goview="teams" data-comp="${m.comp_id}">${icon("columns")}Board</button></div></header>
      ${facts}
      ${teamsCard(m)}
      <div class="ctl-grid2">
        <section class="card ctl-card"><div class="ctl-h"><h3>${icon("check")}Fixed tasks <small class="faint">${fixedDone}/${fixedAll} done</small></h3></div>
          <p class="faint small">Mandatory work every competition needs, from the competition template. Edit, skip, or make one recur.</p>
          ${d.fixed.length ? `<ul class="ctlm-ts">${d.fixed.map(t => taskRow(t)).join("")}</ul>` : `<p class="faint">None.</p>`}</section>
        <section class="card ctl-card"><div class="ctl-h"><h3>${icon("list")}Dynamic tasks <small class="faint">${d.dynamic.filter(t => isOpen(t.status)).length} open</small></h3>
            <button type="button" class="btn sm" data-ctlm-new="${esc(m.ref)}" data-team="${esc(m.unit || "")}">${icon("plus")}New task</button></div>
          <p class="faint small">Made as the work goes: by you, by an agent, or by Mission Intelligence. A dynamic task can become fixed.</p>
          ${d.dynamic.length ? `<ul class="ctlm-ts">${nest(d.dynamic).join("")}</ul>` : `<p class="faint">None yet.</p>`}</section></div>
      <section class="card ctl-card ctlm-intel"><div class="ctl-h"><h3>${icon("sparkle")}Mission Intelligence</h3>
          <button type="button" class="btn primary sm ${intelBusy ? "loading" : ""}" data-ctlm-intel="${esc(m.ref)}" ${intelBusy ? "disabled" : ""}>${icon("cycle")}Review results now</button></div>
        <p class="faint small">Reads the standing against the target, the latest brief, open alerts, failed runs and the open tasks, then ${d.mode === "manual"
          ? "<b>proposes</b> dynamic tasks for you to approve (Manual mode)" : "<b>creates</b> the dynamic tasks the results call for on the team's board and adjusts priorities (" + (d.mode === "auto" ? "Auto" : "Hybrid") + " mode)"}. Nothing external: registering, deploying and submitting stay yours.</p>
        ${schedLine(m.schedule)}
        ${d.proposed.length ? `<h4 class="ctl-h4">${icon("inbox")}Waiting for you</h4><ul class="ctlm-ts">${d.proposed.map(t => taskRow(t)).join("")}</ul>` : ""}
        ${intel ? `<div class="ctlm-last"><p class="small"><b>Last review</b> ${esc(when(intel.ts))}${intel.by_user === "schedule" ? " (scheduled)" : ""} · ${intel.source === "model" ? `by ${esc((intel.model || "").split(":").pop() || "a model")}` : "from the mission's signals"}${intel.tokens ? ` · ${tok(intel.tokens)} tokens` : ""}</p>
            ${intel.summary ? `<p>${esc(intel.summary)}</p>` : ""}${intel.error ? `<p class="faint small">${icon("alert")}The model didn't answer: ${esc(intel.error)}</p>` : ""}
            ${intel.items.length || intel.revisions.length ? `<ul class="ctlm-items">${intel.items.map(i => { const [t, l] = OUT[i.outcome] || ["muted", i.outcome];
              return `<li>${badge(t, l)}<span><b>${esc(i.title)}</b><small>${esc([i.team, i.reason].filter(Boolean).join(" · "))}</small></span></li>`; }).join("")}${intel.revisions.map(r => { const [t, l] = OUT[r.outcome] || ["muted", r.outcome];
              return `<li>${badge(t, l)}<span><b>Priority ${esc(r.priority)}: ${esc(r.title)}</b><small>${esc(r.reason || "")}</small></span></li>`; }).join("")}</ul>` : `<p class="faint small">Nothing new: the open tasks cover what the results call for.</p>`}</div>`
          : `<p class="faint">Not run yet on this mission.</p>`}</section>
      ${d.custom?.length ? `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("target")}Custom missions for this competition</h3></div><div class="ctlm-cards">${d.custom.map(card).join("")}</div></section>` : ""}`;
  }

  function teamsCard(m) {
    const ts = m.teams || [];
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("users")}Teams <small class="faint">${ts.length}</small></h3>
        <button type="button" class="btn sm" data-ctlm-addteam="${esc(m.ref)}">${icon("userplus")}Add a team</button></div>
      <p class="faint small">The Competition team leads and holds the target; supporting teams work on the same mission at the same time. Give any task to any of them.</p>
      <ul class="ctlm-teams">${ts.map(t => `<li><span class="ctlm-tm2">${badge(t.role === "lead" ? "clear" : "new", t.role === "lead" ? "Lead" : "Supporting")}
          <button type="button" class="linkbtn" data-go="${esc(t.ref)}">${esc(t.name)}</button><small>${esc(t.duty || "")}${t.board ? " · has a board" : " · its agents run tasks"}</small></span>
          <span class="ctlm-ta"><small class="faint">${t.open} open</small>${t.role === "support" ? `<button type="button" class="iconbtn sm" data-ctlm-rmteam="${esc(t.ref)}" data-m="${esc(m.ref)}" title="Take this team off the mission (its tasks stay with the mission)" aria-label="Take ${esc(t.name)} off the mission">${icon("close")}</button>` : ""}</span></li>`).join("")}</ul></section>`;
  }
  function schedLine(s) {
    if (!s) return "";
    if (!s.on) return `<p class="faint small">${icon("clock")}Runs when you click. In Auto mode it also reviews each mission every ${s.every_h || 24} hours.</p>`;
    return `<p class="small ctlm-sched ${s.hold ? "held" : ""}">${icon("clock")}<span><b>Scheduled</b> every ${s.every_h} hours (Auto mode) · ${s.hold ? `held: ${esc(s.hold)}` : s.next ? `next ${esc(new Date(s.next * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }))}` : "due now: it runs within 10 minutes"}</span></p>`;
  }
  function teamDlg(ref) {
    const d = cache.detail[ref], on = new Set((d?.mission?.teams || []).map(t => t.ref));
    const opts = allTeams().filter(t => !on.has(t.id));
    let el = document.getElementById("ctlm-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "ctlm-dlg"; document.body.append(el); }
    el.className = "modal ctl-dlg";
    el.innerHTML = `<form method="dialog" class="ctl-form co-form" novalidate><div class="ctl-h"><h3>Add a team · ${esc(d?.mission?.title || "")}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      <div class="ctl-dbody">${opts.length ? `<label class="ctl-field"><span>Team</span><select name="team">${opts.map(t => `<option value="${esc(t.id)}">${esc(t.name)} · ${esc(t.dept)}</option>`).join("")}</select></label>
        <label class="ctl-field"><span>Its duty on this mission</span><input type="text" name="duty" maxlength="200" placeholder="Research the miners ranked above us, build the evaluation set…"></label>
        <p class="faint small">It works alongside the lead team. Its tasks on this mission show up here, and Mission Intelligence can give it tasks.</p>`
        : `<p class="faint">Every team is on this mission already. Make a new team in a department first.</p>`}</div>
      <p class="err" role="alert"></p><div class="row end"><button type="button" class="btn" data-x>Cancel</button>${opts.length ? `<button type="submit" class="btn primary">Add</button>` : ""}</div></form>`;
    const f = el.querySelector("form");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    f.onsubmit = async ev => {
      ev.preventDefault(); const fd = new FormData(f);
      try { cache.detail[ref] = await api(`${B}/missions/${encodeURIComponent(ref)}/teams`, { method: "POST", body: { team: fd.get("team"), duty: fd.get("duty") || "" } });
            el.close(); Auth.toast("Added to the mission"); cache.list = null; redraw(); }
      catch (x) { f.querySelector(".err").textContent = x.message; }
    };
    el.showModal();
  }
  function teamHtml(unit) {
      const l = cache.list; if (!l || l.error) return "";
      const ms = l.initiatives.flatMap(i => i.missions).filter(m => (m.teams || []).some(t => t.ref === unit));
      if (!ms.length) return "";
      return `<p class="ctlm-serves">${icon("target")}<span>Serves ${ms.map(m => { const t = m.teams.find(x => x.ref === unit);
        return `<button type="button" class="linkbtn" data-ctlm-open="${esc(m.ref)}">${esc(m.title)}</button> <small class="faint">(${t.role === "lead" ? "lead" : "supporting"}${t.duty && t.role !== "lead" ? `: ${esc(t.duty)}` : ""})</small>`; }).join(", ")}</span></p>`;
  }
  function teamLine(unit) {
    want("list", `${B}/missions`);  // loads (or refreshes) in the background; redraw() fills the line
    return `<div class="ctlm-teamline" data-ctlm-team="${esc(unit)}">${teamHtml(unit)}</div>`;
  }

  // ---------- the Tasks tab ----------
  const FILTERS = [["open", "Open"], ["fixed", "Fixed"], ["dynamic", "Dynamic"], ["standalone", "Standalone"], ["proposed", "Proposed"], ["all", "All"]];
  function tasksView(d) {
    const pass = t => filter === "all" ? true : filter === "open" ? isOpen(t.status) && t.status !== "proposed" : filter === "fixed" ? t.kind === "fixed" && t.status !== "skipped"
      : filter === "dynamic" ? t.kind !== "fixed" && t.status !== "proposed" && t.status !== "cancelled" : filter === "standalone" ? !t.mission : t.status === "proposed";
    const n = k => d.tasks.filter(t => { const f = filter; filter = k; const r = pass(t); filter = f; return r; }).length;
    const rows = d.tasks.filter(pass);
    const groups = new Map();
    for (const t of rows) { const k = t.mission || ""; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(t); }
    const order = [...groups.keys()].sort((a, b) => (a === "") - (b === "") || (a.startsWith("mx:")) - (b.startsWith("mx:")));
    return `${typeof CtlExec !== "undefined" ? CtlExec.section() : ""}${legend()}<div class="ctlm-bar"><div class="ctlm-chips" role="group" aria-label="Show">${FILTERS.map(([k, l]) => `<button type="button" class="ctlm-chip ${filter === k ? "on" : ""}" aria-pressed="${filter === k}" data-ctlm-filter="${k}">${esc(l)} <b>${n(k)}</b></button>`).join("")}</div>
        <button type="button" class="btn sm" data-act="task">${icon("plus")}New task</button></div>
      ${rows.length ? order.map(k => { const ts = groups.get(k), title = k ? ts[0].mission_title || k : "No mission (standalone)";
        return `<section class="card ctl-card ctlm-group"><div class="ctl-h"><h3>${icon(k.startsWith("comp:") ? "trophy" : k ? "target" : "list")}${k ? `<button type="button" class="linkbtn" data-ctlm-open="${esc(k)}">${esc(title)}</button>` : esc(title)}
            <small class="faint">${k.startsWith("comp:") ? "predefined · Bittensor" : k ? "custom" : "routine work"}</small></h3></div>
          <ul class="ctlm-ts">${nest(ts).join("")}</ul></section>`; }).join("")
        : `<p class="ctl-cc-empty">No task here.</p>`}`;
  }

  // ---------- the Overview's band ----------
  function band(hub) {
    const s = hub?.structure; if (!s) return "";
    const i = s.initiative, c = s.counts;
    return `<section class="ctlm-band" aria-label="Primary initiative">
      <span class="ctlm-iic">${icon("nodes")}</span>
      <div><small>Primary initiative</small><b>${esc(i.name)}</b></div>
      <ul><li><b>${i.subnets}</b> subnet${i.subnets === 1 ? "" : "s"}</li><li><b>${i.predefined}</b> mission${i.predefined === 1 ? "" : "s"}</li>
        <li><b>${i.met}</b> on target${i.behind ? ` · <b>${i.behind}</b> behind` : ""}</li><li>best rank <b>${i.best_rank ?? "–"}</b></li>
        ${i.share_today != null ? `<li><b>${Math.round(i.share_today * 100)}%</b> of today's tokens</li>` : ""}
        <li><b>${c.tasks_open}</b> open task${c.tasks_open === 1 ? "" : "s"}${c.proposed ? ` · <b class="warn">${c.proposed}</b> proposed` : ""}</li></ul>
      <button type="button" class="btn sm" data-ctlm-go="missions">${icon("target")}Missions</button></section>`;
  }

  // ---------- actions ----------
  function invalidate() { cache.list = null; cache.detail = {}; }
  function refresh() { invalidate(); if (typeof Control !== "undefined" && Control.rerender) Control.rerender(); else redraw(); }
  function openMission(ref) { open = ref; mode = "missions"; if (typeof Control !== "undefined") Control.showSec("missions"); }
  function editDlg(t) {
    let el = document.getElementById("ctlm-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "ctlm-dlg"; document.body.append(el); }
    el.className = "modal ctl-dlg";
    const fixed = t.kind === "fixed";
    el.innerHTML = `<form method="dialog" class="ctl-form co-form" novalidate><div class="ctl-h"><h3>${fixed ? "Fixed task" : "Dynamic task"}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      <div class="ctl-dbody">
        <label class="ctl-field"><span>Title</span><input type="text" name="title" maxlength="160" required value="${esc(t.title)}"></label>
        <label class="ctl-field"><span>Detail</span><textarea name="detail" rows="4" maxlength="4000">${esc(t.detail || "")}</textarea></label>
        <div class="ctl-row2"><label class="ctl-field"><span>Priority</span><select name="priority">${["high", "medium", "low"].map(p => `<option value="${p}" ${t.priority === p ? "selected" : ""}>${p[0].toUpperCase() + p.slice(1)}</option>`).join("")}</select></label>
          ${fixed ? `<label class="ctl-field"><span>Recurs</span><select name="cadence">${[[0, "No: once"], [1, "Every day"], [3, "Every 3 days"], [7, "Every week"], [14, "Every 2 weeks"], [30, "Every 30 days"]].map(([v, l]) => `<option value="${v}" ${(t.cadence_days || 0) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>`
            : `<label class="ctl-field"><span>Serves</span><select name="mission"><option value="">${t.mission ? "Its mission (keep)" : "No mission (standalone)"}</option>${t.mission ? `<option value="none">No mission: make it standalone</option>` : ""}</select></label>`}</div>
        ${fixed ? "" : `<label class="ctl-check"><input type="checkbox" name="fixed"> Make it a fixed task: mandatory for this mission (you can then make it recur)</label>`}
      </div><p class="err" role="alert"></p><div class="row end"><button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn primary">Save</button></div></form>`;
    const f = el.querySelector("form");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    f.onsubmit = async ev => {
      ev.preventDefault();
      const fd = new FormData(f), b = { title: fd.get("title"), detail: fd.get("detail"), priority: fd.get("priority") };
      if (fixed) b.cadence_days = +fd.get("cadence") || 0;
      else { if (fd.get("mission") === "none") b.mission = "none"; if (fd.get("fixed") === "on") b.kind = "fixed"; }
      try { await api(`${B}/mission-tasks/${t.id}`, { method: "PATCH", body: b }); el.close(); Auth.toast(b.kind === "fixed" ? "Now a fixed task" : "Saved"); refresh(); }
      catch (x) { f.querySelector(".err").textContent = x.message; }
    };
    el.showModal();
  }
  const findTask = id => { const pool = [cache.list?.tasks || [], ...Object.values(cache.detail).flatMap(d => [d.fixed || [], d.dynamic || [], d.proposed || []])].flat(); return pool.find(t => t.id === id); };

  document.addEventListener("click", async e => {
    const t = e.target; if (!t.closest?.(".ctlm, .ctlm-band, [data-ctlm-open]")) return;
    const q = s => t.closest(s);
    let b;
    if ((b = q("[data-ctlm-open]"))) { e.preventDefault(); open = b.dataset.ctlmOpen; mode = "missions"; if (typeof Control !== "undefined") Control.showSec("missions"); return; }
    if (q("[data-ctlm-back]")) { open = null; return redraw(); }
    if (q("[data-ctlm-tasks]")) { if (typeof Control !== "undefined") Control.showSec("tasks"); return; }
    if ((b = q("[data-ctlm-go]"))) { open = null; if (typeof Control !== "undefined") Control.showSec(b.dataset.ctlmGo); return; }
    if ((b = q("[data-ctlm-filter]"))) { filter = b.dataset.ctlmFilter; return redraw(); }
    if ((b = q("[data-ctlm-new]"))) { if (typeof Control !== "undefined") Control.taskDlg(b.dataset.team || null, null, { mission: b.dataset.ctlmNew, done: refresh }); return; }
    if ((b = q("[data-ctlm-sub]"))) { const p = findTask(+b.dataset.ctlmSub); if (p && typeof Control !== "undefined") Control.taskDlg(p.team, null, { parent: p, done: refresh }); return; }
    if ((b = q("[data-ctlm-addteam]"))) { teamDlg(b.dataset.ctlmAddteam); return; }
    if ((b = q("[data-ctlm-edit]"))) { const x = findTask(+b.dataset.ctlmEdit); if (x) editDlg(x); return; }
    try {
      if ((b = q("[data-ctlm-rmteam]"))) { const ref = b.dataset.m; cache.detail[ref] = await api(`${B}/missions/${encodeURIComponent(ref)}/teams/${encodeURIComponent(b.dataset.ctlmRmteam)}`, { method: "DELETE" });
                                            Auth.toast("Off the mission: its tasks stay with it"); cache.list = null; return redraw(); }
      if ((b = q("[data-ctlm-run]"))) { b.disabled = true; await api(`${B}/mission-tasks/${b.dataset.ctlmRun}/run`, { method: "POST", body: {} }); Auth.toast("On the team's board: its Director hands it out"); return refresh(); }
      if ((b = q("[data-ctlm-skip]"))) { await api(`${B}/mission-tasks/${b.dataset.ctlmSkip}`, { method: "PATCH", body: { skip: b.dataset.on === "1" } }); Auth.toast(b.dataset.on === "1" ? "Skipped: not needed for this mission" : "Needed again"); return refresh(); }
      if ((b = q("[data-ctlm-decide]"))) { b.disabled = true; await api(`${B}/mission-tasks/${b.dataset.ctlmDecide}/decide`, { method: "POST", body: { ok: b.dataset.ok === "1" } }); Auth.toast(b.dataset.ok === "1" ? "Approved: on the team's board" : "Declined"); return refresh(); }
      if ((b = q("[data-ctlm-intel]"))) {
        const ref = b.dataset.ctlmIntel; intelBusy = true; redraw();
        try { cache.detail[ref] = await api(`${B}/missions/${encodeURIComponent(ref)}/intelligence`, { method: "POST", body: {} }); at[ref] = Date.now();
              const it = cache.detail[ref].intelligence?.items || [];
              Auth.toast(`Mission Intelligence: ${it.filter(i => i.outcome === "created").length} created, ${it.filter(i => i.outcome === "proposed").length} proposed`); }
        finally { intelBusy = false; }
        cache.list = null; return redraw();
      }
    } catch (x) { if (b) b.disabled = false; Auth.toast(x.message || "Something went wrong."); }
  });

  return { missionsSec, tasksSec, band, openMission, invalidate, teamLine };
})();
