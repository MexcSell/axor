/* Competition teams, the team's status (mining_status.py), for the Competition teams page (mining-work.js draws the page):
   - A strip above the sub-tabs, on every tab: the verdict (working, stuck, waiting for you, idle, closed), the one sentence that
     explains it, and the fix for the worst blocker.
   - The Status sub-tab: progress (tasks done, done per day this week, the roadmap's current milestone, findings, time left and
     how long the open work takes at the recent pace), right now (who works on what and since when, the queue, the slots, the
     deepest queues), why it isn't moving (every blocker, worst first, each with its fix) and the last day's failed runs grouped
     by error with their likely cause. */
const MiningStatus = (() => {
  const W = "/api/mining/work";
  let st = null, stWid = null, stAt = 0, stLoading = false, failed = "", wired = false;
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const hours = s => s == null ? "–" : s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 2 * 86400 ? `${fmtNum(s / 3600, s < 36000 ? 1 : 0)} h` : `${fmtNum(s / 86400, 1)} days`;
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n || 0, 0);
  const left = s => Math.round((new Date(`${s}T00:00:00`) - new Date(new Date().toDateString())) / 86400000);
  const STATE = { working: ["run", "Working", "cycle"], stuck: ["bad", "Stuck", "alert"], waiting: ["warn", "Waiting for you", "chat"], idle: ["none", "Idle", "clock"], closed: ["off", "Closed", "ban"] };
  const LEVEL = { stop: ["bad", "Blocks the team", "ban"], warn: ["warn", "Slows it down", "alert"], info: ["none", "Good to know", "info"] };

  function need(v) {
    const wid = v.comp.id;
    if (stWid !== wid) { st = null; stWid = wid; stAt = 0; failed = ""; }
    if (stLoading || Date.now() - stAt < 5000) return;
    stLoading = true;
    api(`${W}/comps/${wid}/status`).then(s => { if (stWid === wid) { st = s; failed = ""; } })
      .catch(e => { failed = e.message; }).finally(() => { stAt = Date.now(); stLoading = false; if (stWid === wid) MiningWork.rerender(); });
  }

  function fix(f, cls = "btn sm") {
    if (!f) return "";
    // the page's own controls where they exist (mining-work.js handles data-mw), ours for the rest
    const own = { edit: "edit", resume: "resume", plan: "plan" }[f.act];
    const at = own ? `data-mw="${own}"` : `data-mst="${f.act}"${f.id ? ` data-mstid="${f.id}"` : ""}`;
    return `<button type="button" class="${cls}" ${at}>${esc(f.label)}</button>`;
  }

  // ---------- the strip above the sub-tabs ----------
  function strip(v) {
    need(v);
    if (!st) return failed ? `<div class="ms-strip s-stuck"><span>${icon("alert")}Couldn't read the team's status: ${esc(failed)}</span></div>` : "";
    const [tone, label, ic] = STATE[st.state] || STATE.idle, p = st.progress;
    const worst = st.blockers.find(b => b.level !== "info");
    return `<div class="ms-strip s-${st.state}" role="status">
      <span class="hq-chip t-${tone}">${icon(ic)}${label}</span>
      <span class="ms-line"><b>${esc(st.line)}</b>${st.why && st.state !== "working" ? ` <span class="faint">${esc(st.why)}</span>` : ""}</span>
      <span class="ms-strip-r"><span class="faint small">${p.done}/${p.total} done${p.done_day ? ` · ${p.done_day} today` : ""}</span>
        ${worst?.fix ? fix(worst.fix) : ""}
        ${st.blockers.length ? `<button type="button" class="linkbtn" data-mwsub="status">${plural(st.blockers.length, "issue")}</button>` : ""}</span></div>`;
  }

  // ---------- the Status sub-tab ----------
  function view(v) {
    need(v);
    if (!st) return failed ? `<p class="mh-err">${icon("alert")}${esc(failed)}</p>` : Loading.line("Working out where the team stands…");
    const p = st.progress, n = st.now, b = st.budget, A = Object.fromEntries(v.agents.map(a => [a.id, a]));
    const pc = p.total ? p.done / p.total * 100 : 0;
    const ends = p.ends ? left(p.ends) : null;
    const max = Math.max(1, ...p.week);
    const days = p.week.map((x, i) => { const d = new Date(Date.now() - (6 - i) * 86400000);
      return `<span class="ms-day" title="${x} done on ${d.toLocaleDateString(undefined, { weekday: "long" })}"><i style="--h:${(x / max * 100).toFixed(0)}%"></i><em>${x || ""}</em><small>${d.toLocaleDateString(undefined, { weekday: "narrow" })}</small></span>`; }).join("");
    const counts = [["todo", "To do"], ["queued", "Queued"], ["working", "Working"], ["checking", "In review"], ["review", "Your review"], ["blocked", "Questions"], ["done", "Done"]]
      .map(([k, l]) => `<span class="ms-count c-${k}"><b>${p.counts[k]}</b>${l}</span>`).join("");
    const [tone, label, ic] = STATE[st.state] || STATE.idle;

    const progress = `<section class="mh-card ms-card"><h3>${icon("target")}How far it has got</h3>
      <div class="ms-big"><b>${fmtNum(pc, 0)}%</b><span>${p.done} of ${plural(p.total, "task")} done${p.findings ? ` · ${plural(p.findings, "finding")} in the notebook` : ""}</span></div>
      <div class="mw-bar" role="progressbar" aria-valuemin="0" aria-valuemax="${p.total}" aria-valuenow="${p.done}" aria-label="Tasks done"><i style="--w:${pc.toFixed(1)}%"></i></div>
      <div class="ms-counts">${counts}</div>
      <div class="ms-week" aria-label="Tasks done per day, last 7 days">${days}</div>
      <dl class="ms-dl">
        ${p.milestones.total ? `<dt>Roadmap</dt><dd>${p.milestones.done} of ${plural(p.milestones.total, "milestone")} done${p.milestones.current ? ` · now: <b>${esc(p.milestones.current.title)}</b>${p.milestones.current.due ? ` (due ${esc(p.milestones.current.due)})` : ""}` : ""} <button type="button" class="linkbtn" data-mwsub="roadmap">Open</button></dd>` : ""}
        ${ends != null ? `<dt>Competition</dt><dd>${ends > 1 ? `ends in ${ends} days` : ends === 1 ? "ends tomorrow" : ends === 0 ? "ends today" : "past its end date"} (${esc(p.ends)})</dd>` : ""}
        <dt>Open work</dt><dd>${p.ready ? `${plural(p.ready, "task")} assigned and ready${p.eta ? ` · about <b>${hours(p.eta)}</b> at the recent pace (${hours(p.avg_run)} a task, ${p.lanes} at once)` : " · no finished run today to estimate from"}` : "none assigned"}</dd>
        <dt>Last finished</dt><dd>${p.last_done ? `<button type="button" class="linkbtn" data-mwtask="${p.last_done.id}">${esc(p.last_done.title)}</button> by ${esc(p.last_done.agent)}, ${ago(p.last_done.at)}` : "nothing yet"}</dd>
        <dt>Last activity</dt><dd>${p.last_activity ? ago(p.last_activity) : "none yet"}</dd></dl></section>`;

    const runs = n.running.map(r => { const a = A[r.agent_id];
      return `<li>${a ? `<span class="av sm c-${a.color}" aria-hidden="true">${icon(a.icon)}</span>` : ""}<span><b>${esc(r.agent)}</b> ${r.kind === "review" ? "reviews" : r.kind === "task" ? "works on" : ""}
        ${r.task ? `<button type="button" class="linkbtn" data-mwtask="${r.task}">${esc(r.title)}</button>` : esc(r.title)}</span><span class="faint small">for ${hours(Date.now() / 1000 - r.since)}</span></li>`; }).join("");
    const now = `<section class="mh-card ms-card"><h3>${icon("clock")}Right now</h3>
      <p class="ms-verdict"><span class="hq-chip t-${tone}">${icon(ic)}${label}</span> ${esc(st.line)}</p>
      <dl class="ms-dl">
        <dt>Autopilot</dt><dd>${n.paused ? "paused" : n.autopilot ? `on${n.next_plan ? ` · next plan ${n.next_plan > Date.now() / 1000 ? `in ${hours(n.next_plan - Date.now() / 1000)}` : "due"}` : ""}` : "off: nothing starts by itself"}${n.pilot_note ? ` · <span class="mh-err">${esc(n.pilot_note)}</span>` : ""}</dd>
        <dt>Slots</dt><dd>${n.running.length} of ${n.parallel} in use · ${n.queued} queued · ${plural(n.free, "agent")} free</dd>
        ${n.piles.length ? `<dt>Longest queues</dt><dd>${n.piles.map(x => `${esc(x.agent)} ${x.n}`).join(" · ")}</dd>` : ""}
        <dt>Tokens today</dt><dd>${short(b.used)}${b.budget ? ` of ${short(b.budget)}` : " (no cap)"}${b.frees ? ` · frees up around ${new Date(b.frees * 1000).toLocaleString(undefined, { weekday: b.frees - Date.now() / 1000 > 43200 ? "short" : undefined, hour: "2-digit", minute: "2-digit" })}` : ""}</dd>
        <dt>Runs today</dt><dd>${st.ok_day} finished · ${st.fails_day ? `<b class="mw-late">${st.fails_day} failed</b>` : "0 failed"}</dd>
        ${st.director ? `<dt>Director</dt><dd>${st.director.reporting ? "writing a report now" : st.director.waiting ? `report open: ${plural(st.director.waiting, "ask")} for you` : "no report waiting"}${st.director.with_director ? ` · ${st.director.with_director} items to settle` : ""}${st.director.last_report ? ` · last report ${ago(st.director.last_report)}` : ""}</dd>` : ""}</dl>
      ${runs ? `<ul class="ms-runs">${runs}</ul>` : `<p class="faint small">Nobody is working.</p>`}</section>`;

    const blockers = `<section class="mh-card ms-card ms-wide"><h3>${icon("alert")}Why it isn't moving faster</h3>
      ${st.blockers.length ? `<ul class="ms-blockers">${st.blockers.map(x => { const [t, l, i] = LEVEL[x.level];
        return `<li class="l-${x.level}"><span class="ms-bi" title="${l}">${icon(i)}</span><span><b>${esc(x.title)}</b>${x.detail ? `<span class="faint">${esc(x.detail)}</span>` : ""}</span>${fix(x.fix)}</li>`; }).join("")}</ul>`
        : `<p class="ms-ok">${icon("check")}Nothing is in the way.</p>`}</section>`;

    const errors = st.errors.length ? `<section class="mh-card ms-card ms-wide" id="ms-errors"><h3>${icon("ban")}Failed runs, last 24 hours</h3>
      <ul class="ms-errors">${st.errors.map(e => `<li${e.resolved ? ` class="faint"` : ""}><span class="ms-n">${e.n}×</span><span>
        ${e.resolved ? `<b>Earlier runs: the task has run fine since, or is done.</b>` : e.cause ? `<b>${esc(e.cause)}</b>` : ""}<code>${esc(e.error)}</code>
        <span class="faint small">${esc(e.agents.join(", "))} · last ${ago(e.last)}${e.task ? ` · <button type="button" class="linkbtn" data-mwtask="${e.task.id}">${esc(e.task.title || "the task")}</button>` : ""}</span></span></li>`).join("")}</ul></section>` : "";

    const web = typeof MiningWeb !== "undefined" ? MiningWeb.card(v) : "";  // mining-web.js: saved web reads and watches
    const rel = typeof MiningRelease !== "undefined" ? MiningRelease.card(v) : "";  // mining-release.js: the frozen candidate, benchmarks, duplicates
    return `<div class="ms-grid">${blockers}${progress}${now}${errors}${rel}${web}</div>`;
  }

  async function act(b) {
    const v = MiningWork.view(); if (!v) return;
    const k = b.dataset.mst, wid = v.comp.id;
    b.disabled = true;
    try {
      if (k === "kick") { st = await api(`${W}/comps/${wid}/status/kick`, { method: "POST" }); stAt = Date.now(); Auth.toast("Queue restarted"); MiningWork.reload(); }
      else if (k === "autopilot" || k === "parallel") {
        const body = k === "autopilot" ? { autopilot: true } : { parallel: Math.min(24, (v.comp.parallel || 4) + 2) };
        MiningWork.apply(await api(`${W}/comps/${wid}`, { method: "PATCH", body }));
        stAt = 0; Auth.toast(k === "autopilot" ? "Autopilot on" : `${body.parallel} can work at once`);
      }
      else if (k === "task") MiningWork.openTask(+b.dataset.mstid);
      else if (k === "errors") { MiningWork.go("status"); setTimeout(() => $("#ms-errors")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); }
      else if (k === "director") MiningWork.go("report");
      else if (k === "board") MiningWork.go("tasks");
      else if (k === "autoloop") MiningWork.go("autoloop");
      else if (k === "team") MiningWork.go("team");
      else if (k === "agents") { const n = $("#nav-agents"); if (n && !n.hidden) n.click(); else location.hash = "#agents"; }
      else if (k === "tools") { if (typeof Agents !== "undefined" && Agents.tools) Agents.tools(); else location.hash = "#agents"; }  // Agents → Tools & MCP
    } catch (e) { err(e); } finally { if (b.isConnected) b.disabled = false; }
  }

  function wire(el) {
    if (wired) return; wired = true;
    el.addEventListener("click", e => { const b = e.target.closest("[data-mst]"); if (b) act(b); });
  }
  const fresh = () => { stAt = 0; };
  return { strip, view, wire, fresh };
})();
