/* The Execution Monitor (task_lifecycle.py: GET /api/control/execution, /api/control/tasks/{id}/trace|retry|reassign|contract).
   Shown at the top of Control Hub → Tasks (control-missions.js tasksView). Prefix ctlx-.
   - section(): running / under way / open / overdue dispatch / needs you, the canonical stage pipeline (CREATED … COMPLETED,
     then FAILED, TIMEOUT, CANCELLED, BLOCKED), missions and tasks reconciled from the same records, the top reasons tasks
     aren't moving, and one row per open (or recently failed) task with its stage, destination, tries and why.
   - Row controls: Details (reason, logs, deliverable and its checks, contract), Retry, Reassign, Cancel.
   It renders from its last answer and refreshes in the background (control.js draws the hub synchronously). */
const CtlExec = (() => {
  const B = "/api/control";
  let data = null, at = 0, busy = false, all = false;
  const TONE = { COMPLETED: "clear", RUNNING: "clear", CLAIMED: "new", VERIFYING: "new", SUBMITTED: "new", DISPATCHED: "muted", QUEUED: "muted",
                 DISPATCHING: "muted", CREATED: "muted", FAILED: "scam", TIMEOUT: "scam", BLOCKED: "caution", CANCELLED: "muted" };
  const badge = (tone, text, title = "") => `<span class="badge ${tone}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</span>`;
  const when = ts => ts ? ago(ts) : "";
  const time_ = ts => ts ? new Date(ts * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "";

  function load() {
    if (busy) return;
    busy = true;
    api(`${B}/execution`).then(d => { data = d; }).catch(e => { data = { error: e.message }; })
      .finally(() => { busy = false; at = Date.now(); redraw(); });
  }
  function redraw() { const el = document.getElementById("ctlx-root"); if (el) el.innerHTML = body(); }
  function section() {
    if (!busy && (!data || Date.now() - at > 15000)) load();
    return `<section id="ctlx-root" class="card ctl-card ctlx" aria-labelledby="ctlx-h">${body()}</section>`;
  }

  function body() {
    if (!data) return `<div class="ctl-h"><h3 id="ctlx-h">${icon("monitor")}Execution monitor</h3></div><p class="faint">${icon("cycle")}Loading…</p>`;
    if (data.error) return `<div class="ctl-h"><h3 id="ctlx-h">${icon("monitor")}Execution monitor</h3></div><p class="ctl-warn">${icon("alert")}${esc(data.error)}</p>`;
    const c = data.counts, d = data.dispatch || {}, rc = data.reconcile, w = data.week;
    const kpi = (l, v, tone = "", sub = "") => `<div class="ctlx-kpi ${tone}"><small>${esc(l)}</small><b>${v}</b>${sub ? `<em>${sub}</em>` : ""}</div>`;
    const on = d.on ? `Dispatcher on · every ${d.every} s${d.last ? ` · last pass ${when(d.last)}` : ""}` : (data.mode === "manual" ? "Manual mode: the dispatcher sends nothing" : "Dispatcher off on this server");
    const stages = data.stages.filter(s => !s.off_path), off = data.stages.filter(s => s.off_path);
    const rows = all ? data.tasks : data.tasks.slice(0, 8);
    return `<div class="ctl-h"><h3 id="ctlx-h">${icon("monitor")}Execution monitor <small class="faint">${esc(data.mode[0].toUpperCase() + data.mode.slice(1))} mode</small></h3>
        <button type="button" class="iconbtn sm" data-ctlx-refresh title="Refresh" aria-label="Refresh the execution monitor">${icon("cycle")}</button></div>
      <p class="faint small ctlx-sub">${icon(d.on ? "clock" : "info")}${esc(on)}${d.held ? ` · <b>${esc(d.held)}</b>` : ""} · this week ${w.dispatched} dispatched, ${w.retried} retried, ${w.reassigned} reassigned, ${w.escalated} escalated</p>
      <div class="ctlx-kpis">${kpi("Running", c.running)}${kpi("Under way", c.under_way, "", "claimed, running or being checked")}${kpi("Open", c.open)}
        ${kpi("Overdue dispatch", c.overdue, c.overdue ? "warn" : "", "not moving for 1 h+, AXoR's move")}${kpi("Needs you", c.needs_you, c.needs_you ? "bad" : "", c.dead ? `${c.dead} dead letter${c.dead === 1 ? "" : "s"}` : "")}</div>
      <ol class="ctlx-pipe" aria-label="Tasks by stage">${stages.map(s => `<li class="${s.n ? "on" : ""}"><small>${esc(s.label)}</small><b>${s.n}</b></li>`).join("")}</ol>
      <ul class="ctlx-off" aria-label="Off the path">${off.map(s => `<li class="${s.n ? "on s-" + s.stage.toLowerCase() : ""}">${esc(s.label)} <b>${s.n}</b></li>`).join("")}</ul>
      <p class="small ctlx-rec ${rc.orphans.length ? "warn" : ""}">${icon(rc.orphans.length ? "alert" : "check")}<span><b>Missions and tasks, same records:</b> ${rc.missions_open.predefined} predefined mission${rc.missions_open.predefined === 1 ? "" : "s"} (your Competition teams) + ${rc.missions_open.custom} custom open ·
        ${rc.tasks_open} open task${rc.tasks_open === 1 ? "" : "s"}: ${rc.tasks_by_mission.predefined} on predefined, ${rc.tasks_by_mission.custom} on custom, ${rc.tasks_by_mission.standalone} standalone${rc.orphans.length ? ` · <b>${rc.orphans.length} whose mission is closed or gone</b>: ${rc.orphans.slice(0, 3).map(o => `<button type="button" class="linkbtn" data-ctlx-open="${o.id}">#${o.id}</button> (${esc(o.why)})`).join(", ")}` : " · none orphaned"}.</span></p>
      ${data.reasons.length ? `<div class="ctlx-why"><small class="faint">Not moving for over an hour</small><ul>${data.reasons.map(r => `<li><b>${r.n}</b> ${esc(r.why)}${r.owner ? ` <small class="faint">· next: ${esc(r.owner)}</small>` : ""}</li>`).join("")}</ul></div>` : ""}
      ${rows.length ? `<div class="ctlx-table" role="table" aria-label="Tasks being executed">
        <div class="ctlx-tr ctlx-th" role="row"><span role="columnheader">Task</span><span role="columnheader">Assigned</span><span role="columnheader">Stage</span><span role="columnheader">Tries</span><span role="columnheader">Why</span><span role="columnheader"><span class="sr-only">Actions</span></span></div>
        ${rows.map(row).join("")}</div>
        ${data.tasks.length > 8 ? `<button type="button" class="linkbtn ctlx-more" data-ctlx-all>${all ? "Show fewer" : `Show all ${data.tasks.length}`}</button>` : ""}`
        : `<p class="ctl-cc-empty">No open task: nothing to execute.</p>`}`;
  }

  function row(t) {
    const who = t.agent || (t.route === "board" ? (t.board_agent != null ? "Assigned on the board" : "The team's Director") : t.route === "mission" ? "Mission Control" : "Nobody yet");
    const canRetry = ["failed", "needs_input"].includes(t.status) || t.dead || (t.status === "todo" && !t.run && t.attempts > 0);
    const canMove = t.route !== "mission" && !["running", "review", "done", "cancelled"].includes(t.status);
    const flag = t.dead ? `<span class="badge scam" title="${esc(t.dead)}">Needs you</span>` : t.overdue ? `<span class="badge caution">Overdue</span>` : "";
    return `<div class="ctlx-tr ${t.dead ? "dead" : t.overdue ? "late" : ""}" role="row">
      <span role="cell" class="ctlx-task"><button type="button" class="linkbtn" data-ctlx-open="${t.id}" title="Details: reason, logs, deliverable, contract">${esc(t.title)}</button>
        <small class="faint">#${t.id}${t.mission_title ? ` · ${esc(t.mission_title)}` : t.mission ? "" : " · standalone"} · ${esc(t.destination)}${t.duplicate_of ? ` · <b>same title as #${t.duplicate_of}</b>` : ""}</small></span>
      <span role="cell" class="ctlx-who"><small class="ctlx-lbl">Assigned</small>${esc(who)}${t.team ? `<small class="faint">${esc(t.team)}</small>` : ""}</span>
      <span role="cell"><small class="ctlx-lbl">Stage</small>${badge(TONE[t.stage] || "muted", t.stage_label, t.stage_note || "")} ${flag}</span>
      <span role="cell" class="ctlx-n"><small class="ctlx-lbl">Tries</small>${t.attempts}${t.next_try && t.next_try * 1000 > Date.now() ? `<small class="faint">next ${esc(time_(t.next_try))}</small>` : ""}</span>
      <span role="cell" class="ctlx-reason"><small class="ctlx-lbl">Why</small>${esc(t.dead || t.why?.text || t.stage_note || "")}${t.why?.owner ? `<small class="faint">next: ${esc(t.why.owner)}</small>` : ""}</span>
      <span role="cell" class="ctlx-acts">
        ${canRetry ? `<button type="button" class="btn sm" data-ctlx-retry="${t.id}">${icon("reset")}Retry</button>` : ""}
        ${canMove ? `<button type="button" class="btn sm" data-ctlx-open="${t.id}" data-tab="reassign">${icon("swap")}Reassign</button>` : ""}
        ${!["done", "cancelled"].includes(t.status) ? `<button type="button" class="iconbtn sm" data-ctlx-cancel="${t.id}" title="Cancel this task" aria-label="Cancel ${esc(t.title)}">${icon("close")}</button>` : ""}</span></div>`;
  }

  // ---------- one task: reason, logs, deliverable, contract, reassign ----------
  const TABS = [["reason", "Reason"], ["logs", "Logs"], ["deliverable", "Deliverable"], ["contract", "Contract"], ["reassign", "Reassign"]];
  async function openTask(id, tab = "reason") {
    let el = document.getElementById("ctlx-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "ctlx-dlg"; el.className = "modal ctl-dlg ctlx-dlg"; document.body.append(el); }
    el.innerHTML = `<div class="ctl-dbody"><p class="faint">${icon("cycle")}Loading task #${id}…</p></div>`;
    if (!el.open) el.showModal();
    try { draw(el, await api(`${B}/tasks/${id}/trace`), tab); }
    catch (e) { el.innerHTML = `<div class="ctl-dbody"><p class="ctl-warn">${icon("alert")}${esc(e.message)}</p><div class="row end"><button type="button" class="btn" data-x>Close</button></div></div>`;
                el.querySelector("[data-x]").onclick = () => el.close(); }
  }
  function draw(el, d, tab) {
    const t = d.task, cur = d.stages.indexOf(d.stage);
    const pane = {
      reason: () => `<ol class="ctlx-steps" aria-label="Lifecycle">${d.stages.map((s, i) => `<li class="${i < cur ? "past" : i === cur ? "now" : ""}">${esc(s[0] + s.slice(1).toLowerCase())}</li>`).join("")}
          ${cur < 0 ? `<li class="now off">${esc(d.stage_label)}</li>` : ""}</ol>
        <dl class="ctlx-dl"><dt>Stage</dt><dd>${badge(TONE[d.stage] || "muted", d.stage_label)} ${esc(d.stage_note || "")}</dd>
          ${t.why ? `<dt>Why</dt><dd>${esc(t.why.text)}${t.why.owner ? ` <small class="faint">· next: ${esc(t.why.owner)}</small>` : ""}</dd>` : ""}
          ${d.dead ? `<dt>Dead letter</dt><dd class="bad">${d.dead === t.why?.text ? "No automatic path left: escalated to you." : esc(d.dead)}</dd>` : ""}
          <dt>Route</dt><dd>${esc(t.route === "board" ? "Team board" : t.route === "mission" ? "Mission Control" : "Agent run")}${t.ref ? ` · ${esc(t.ref)}` : ""}${d.board ? ` · board status ${esc(d.board.status)}${d.board.agent ? ` (${esc(d.board.agent)})` : ""}${d.board.hold ? `, hold ${esc(d.board.hold)}` : ""}` : ""}</dd>
          <dt>Agent</dt><dd>${esc(t.agent || "–")}</dd>
          <dt>Tries</dt><dd>${t.attempts}${t.next_try ? ` · next ${esc(time_(t.next_try))}` : ""}</dd>
          <dt>Source</dt><dd>${esc(t.origin === "template" ? "Competition template" : t.origin === "intelligence" ? "Mission Intelligence" : t.origin === "you" ? "You" : t.origin || "–")}${t.mission_title || t.mission ? ` · ${esc(t.mission_title || t.mission)}` : " · standalone"}</dd>
          ${d.contract.problems.length ? `<dt>Contract</dt><dd class="bad">${esc(d.contract.problems.join("; "))}</dd>` : ""}
          ${t.summary && !(t.why?.text || "").includes(t.summary.slice(0, 60)) && t.summary !== d.dead && !(d.dead || "").includes(t.summary.slice(0, 60)) ? `<dt>Last note</dt><dd>${esc(t.summary)}</dd>` : ""}</dl>`,
      logs: () => `${d.runs.length ? `<h4>Runs</h4><ul class="ctlx-runs">${d.runs.map(r => `<li>${badge(r.status === "done" ? "clear" : r.status === "running" ? "new" : ["failed", "timeout", "lost"].includes(r.status) ? "scam" : "muted", r.status || "–")}
            <span>${esc(time_(r.started))}${r.finished ? ` → ${esc(time_(r.finished))}` : ""}${r.model ? ` · ${esc(r.model)}` : ""}${r.tokens ? ` · ${r.tokens} tokens` : ""}${r.board ? " · on the board" : ""}</span>${r.error ? `<small class="bad">${esc(r.error)}</small>` : ""}</li>`).join("")}</ul>` : `<p class="faint">No run yet.</p>`}
        <h4>History</h4><ol class="ctlx-hist">${(t.history || []).slice().reverse().map(h => `<li><small class="faint">${esc(time_(h.ts))} · ${esc(h.by || "")}</small>${esc(h.what || "")}</li>`).join("") || "<li class='faint'>Nothing yet.</li>"}</ol>`,
      deliverable: () => `${d.verify ? `<div class="ctlx-verify ${d.verify.ok ? "ok" : "bad"}"><b>${icon(d.verify.ok ? "check" : "alert")}${d.verify.ok ? "Passed its checks" : "Failed its checks"}</b> <small class="faint">by ${esc(d.verify.by)} · ${esc(time_(d.verify.at))}</small>
            <ul>${d.verify.checks.map(c => `<li class="${c.ok ? "ok" : "bad"}">${icon(c.ok ? "check" : "close")}<span>${esc(c.check)} <small class="faint">${esc(c.note)}</small></span></li>`).join("")}</ul>
            <ul>${d.verify.criteria.map(c => `<li class="${c.met === true ? "ok" : c.met === false ? "bad" : ""}">${icon(c.met === true ? "check" : c.met === false ? "close" : "eye")}<span>${esc(c.criterion)} <small class="faint">${esc(c.evidence)}</small></span></li>`).join("")}</ul></div>`
          : `<p class="faint small">${t.route === "board" ? "A board task is checked by its team (the board's checks and review)." : "Not checked yet: the checks run when the agent says it's done."}</p>`}
        ${t.result ? `<h4>Result</h4><pre class="ctlx-result">${esc(t.result.length > 20000 ? t.result.slice(0, 20000) + "…" : t.result)}</pre>` : `<p class="faint">No deliverable yet.</p>`}`,
      contract: () => `<form class="ctl-form ctlx-contract" data-ctlx-contract="${t.id}">
          <label class="ctl-field"><span>Acceptance criteria <small class="faint">one per line; empty = the default for its kind</small></span><textarea name="accept" rows="4" maxlength="2000">${esc(d.contract.accept.join("\n"))}</textarea></label>
          <label class="ctl-field"><span>Required outputs <small class="faint">one per line; each must be named in the result</small></span><textarea name="outputs" rows="2" maxlength="1000">${esc(d.contract.outputs.join("\n"))}</textarea></label>
          <p class="faint small">An agent's “done” is checked against these before your review; a board task carries them to its team.</p>
          <p class="err" role="alert"></p><div class="row end"><button type="submit" class="btn primary sm">Save the contract</button></div></form>`,
      reassign: () => {
        if (t.route === "mission") return `<p class="faint">A Mission Control mission staffs itself.</p>`;
        const opts = t.route === "board" ? d.board_agents.map(a => ({ key: a.key, name: a.name, note: a.lead ? "Director" : "", ok: true }))
                                         : d.candidates.map(a => ({ key: a.key, name: a.name, note: `${a.team} (${a.relation}) · ${a.load}/${a.cap}${a.why_not ? ` · ${a.why_not}` : ""}`, ok: a.eligible }));
        if (!opts.length) return `<p class="faint">${t.route === "board" ? "It isn't on a team board yet: retry it to send it there." : "Nobody on its team or the mission's supporting teams: add an agent to the team."}</p>`;
        return `<form class="ctl-form" data-ctlx-reassign="${t.id}"><fieldset class="ctlx-pick"><legend>Give it to</legend>
          ${opts.map(o => `<label class="ctl-check ${o.ok ? "" : "faint"}"><input type="radio" name="agent" value="${esc(o.key)}" ${o.ok ? "" : "disabled"}> ${esc(o.name)} <small class="faint">${esc(o.note)}</small></label>`).join("")}
          <label class="ctl-check"><input type="radio" name="agent" value="" checked> Let AXoR pick another agent</label></fieldset>
          <p class="err" role="alert"></p><div class="row end"><button type="submit" class="btn primary sm">${icon("swap")}Reassign</button></div></form>`;
      },
    };
    el.innerHTML = `<div class="ctl-h"><h3>#${t.id} · ${esc(t.title)}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      <div class="ctlx-tabs" role="tablist">${TABS.map(([k, l]) => `<button type="button" role="tab" aria-selected="${k === tab}" class="ctlm-chip ${k === tab ? "on" : ""}" data-ctlx-tab="${k}">${esc(l)}</button>`).join("")}</div>
      <div class="ctl-dbody ctlx-pane" role="tabpanel">${pane[tab]()}</div>
      <div class="row end ctlx-foot">${["failed", "needs_input"].includes(t.status) || d.dead ? `<button type="button" class="btn sm" data-ctlx-retry="${t.id}">${icon("reset")}Retry</button>` : ""}<button type="button" class="btn sm" data-x>Close</button></div>`;
    el.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    el.querySelectorAll("[data-ctlx-tab]").forEach(b => b.onclick = () => draw(el, d, b.dataset.ctlxTab));
    const cf = el.querySelector("[data-ctlx-contract]");
    if (cf) cf.onsubmit = async ev => { ev.preventDefault(); const fd = new FormData(cf);
      try { draw(el, await api(`${B}/tasks/${t.id}/contract`, { method: "PUT", body: { accept: fd.get("accept") || "", outputs: fd.get("outputs") || "" } }), "contract"); Auth.toast("Contract saved"); }
      catch (x) { cf.querySelector(".err").textContent = x.message; } };
    const rf = el.querySelector("[data-ctlx-reassign]");
    if (rf) rf.onsubmit = async ev => { ev.preventDefault(); const fd = new FormData(rf);
      try { const nd = await api(`${B}/tasks/${t.id}/reassign`, { method: "POST", body: { agent: fd.get("agent") || "" } }); Auth.toast(`Reassigned to ${nd.task.agent || "another agent"}`); refreshAll(); draw(el, nd, "reason"); }
      catch (x) { rf.querySelector(".err").textContent = x.message; } };
  }

  function refreshAll() { data = null; at = 0; if (typeof CtlMissions !== "undefined") CtlMissions.invalidate(); if (typeof Control !== "undefined" && Control.rerender) Control.rerender(); else load(); }

  document.addEventListener("click", async e => {
    const t = e.target; if (!t.closest?.(".ctlx, .ctlx-dlg")) return;
    const q = s => t.closest(s);
    let b;
    if (q("[data-ctlx-refresh]")) { data = null; at = 0; load(); return; }
    if (q("[data-ctlx-all]")) { all = !all; return redraw(); }
    if ((b = q("[data-ctlx-open]"))) { e.preventDefault(); return openTask(+b.dataset.ctlxOpen, b.dataset.tab || "reason"); }
    try {
      if ((b = q("[data-ctlx-retry]"))) {
        b.disabled = true; const d = await api(`${B}/tasks/${b.dataset.ctlxRetry}/retry`, { method: "POST", body: {} });
        Auth.toast(`Retried: ${d.stage_label.toLowerCase()}`); refreshAll();
        const dlg = document.getElementById("ctlx-dlg"); if (dlg?.open) draw(dlg, d, "reason"); return;
      }
      if ((b = q("[data-ctlx-cancel]"))) {
        if (!confirm("Cancel this task? A run under way finishes but its result is discarded; a board task stays on its team's board.")) return;
        b.disabled = true; await api(`${B}/tasks/${b.dataset.ctlxCancel}`, { method: "PATCH", body: { status: "cancelled" } }); Auth.toast("Cancelled"); return refreshAll();
      }
    } catch (x) { if (b) b.disabled = false; Auth.toast(x.message || "Something went wrong."); }
  });

  return { section, refresh: refreshAll };
})();
