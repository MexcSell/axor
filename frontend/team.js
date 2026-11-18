/* Team and Reports tabs (workspace). Team: the project team runs Plan-Do-Check-Act cycles on the open subnet by itself.
   Paige plans tasks for her teammates, they work through them as their hand-offs finish, Tessa checks the results and
   Paige reports. Two diagrams show it at a glance: Activity (one lane per agent on a shared timeline: what everyone did
   and when) and Schedule (the plan as a dependency graph from Plan to Act, plus the repeat schedule).
   Reports: what only the user decides (the plan, raising the budget, funding, access, scope changes, risks) waits there
   for approval, one at a time or all at once, next to the cycle reports.
   Both tabs follow the server over server-sent events: each message carries only what changed and the new activity,
   and the stream runs only while one of the tabs is open. Task outputs are fetched when a task is opened. */
const Team = (() => {
  let st = null, n = null, es = null, pick = null, events = [], formKey = "", seq = 0, model = () => ({ model: "auto" });
  let mode = "team", diag = pref("diag") || "activity", rep = null, repScope = pref("rscope") || "here", repSeq = 0, tick = null, ro = null;
  const open = new Set(), outputs = {}, notes = {}, sel = { pend: new Set(), rep: new Set(), dec: new Set() };
  const PHASES = [["plan", "Plan", "calendar"], ["do", "Do", "zap"], ["check", "Check", "shield"], ["act", "Act", "trophy"]];
  const ACTIVE = ["plan", "do", "check", "act", "waiting"];
  const STATUS = { plan: ["new", "Planning"], do: ["new", "Doing"], check: ["new", "Checking"], act: ["new", "Reporting"], waiting: ["caution", "Waiting for you"], done: ["clear", "Done"], failed: ["avoid", "Failed"], cancelled: ["caution", "Cancelled"] };
  const TASK = { queued: ["", "Queued"], running: ["new", "Working"], done: ["clear", "Done"], failed: ["avoid", "Failed"], skipped: ["caution", "Skipped"] };
  const KIND = { phase: "cycle", plan: "calendar", start: "play", tool: "search", done: "check", fail: "alert", warn: "alert", check: "shield", act: "trophy", info: "info", ask: "bell", decision: "check" };
  const STATE = { working: "Working", queued: "Queued", waiting: "Needs you", done: "Done", idle: "Idle", paused: "Paused" };
  const ASK = { plan: ["calendar", "Plan"], budget: ["coins", "Budget"], fund: ["wallet", "Funding"], access: ["key", "Access"], risk: ["alert", "Risk"] };
  const REPEAT = { 0: "Once", 24: "Every day", 168: "Every week" };
  const EXAMPLES = ["Plan and design a competitive miner, with a test plan and a budget", "Decide whether this subnet is worth building for this month",
    "Get a miner running on testnet: code layout, deployment and monitoring", "Review our repos and CI and say what blocks a release"];
  function pref(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem("tm." + k)); localStorage.setItem("tm." + k, JSON.stringify(v)); } catch { return null; } }
  const tok = x => x >= 10000 ? `${fmtNum(x / 1000, 0)}k` : fmtNum(x || 0, 0);
  const active = () => ACTIVE.includes(st?.cycle?.status);
  // the phase a cycle is in (or paused in, while it waits for the user)
  const phaseOf = c => c.status !== "waiting" ? c.status : ((c.timeline || []).map(x => x[0]).filter(s => s !== "waiting").at(-1) || "plan");
  const now = () => Date.now() / 1000;

  // ---------- shared: stream and pending count ----------
  function listen() {
    stop(false);
    es = new EventSource(`/api/workspace/pdca/stream?netuid=${n}${pick && mode === "team" ? `&cycle=${pick}` : ""}`);
    es.addEventListener("state", e => {
      const d = JSON.parse(e.data);
      Workspace.setPending(d.pending_total);
      if (mode === "reports") return $("#rp") ? loadReports(true) : stop();
      if (!$("#tm")) return stop();
      if (d.cycle?.id !== st?.cycle?.id) { events = []; open.clear(); }
      const last = events.at(-1)?.id || 0;  // the first message repeats what the page loaded
      const fresh = d.events.filter(x => x.id > last);
      if (fresh.some(x => x.kind === "ask")) toast("The team needs your approval: see Reports");
      events = [...events, ...fresh].slice(-200);
      for (const t of d.tasks) if (outputs[t.id] && outputs[t.id].status !== t.status) delete outputs[t.id];  // fetched before it changed
      st = { ...d, events }; draw();
    });
    es.addEventListener("auth", () => { stop(); Auth.expired(); });
  }
  function stop(all = true) { es?.close(); es = null; if (all) { clearInterval(tick); tick = null; ro?.disconnect(); ro = null; } }

  // ---------- Team tab ----------
  function render(pane, netuid, choice) {
    if (n !== netuid) { pick = null; open.clear(); }
    n = netuid; model = choice; formKey = ""; mode = "team";
    pane.innerHTML = `<div class="tm" id="tm"><div id="tm-form"></div><div id="tm-cycle"></div><div id="tm-diag"></div><div class="tm-grid"><div id="tm-agents"></div><div id="tm-feed"></div></div><div id="tm-tasks"></div><div id="tm-report"></div></div>`;
    $("#tm-cycle").innerHTML = Loading.cards(2, "card");
    ro = new ResizeObserver(() => drawDiagram()); ro.observe($("#tm"));
    clearInterval(tick); tick = setInterval(() => { if (active() && $("#tm")) drawDiagram(); }, 5000);  // keeps "now" moving on the timeline
    load();
  }
  async function load() {
    const s = ++seq;
    try { const r = await api(`/api/workspace/pdca?netuid=${n}${pick ? `&cycle=${pick}` : ""}`); if (s !== seq) return; st = r; events = r.events; Workspace.setPending(r.pending_total); }
    catch (e) { if (s === seq && $("#tm")) $("#tm-cycle").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    draw(); listen();
  }
  function draw() {
    if (!$("#tm")) return;
    drawForm(); drawCycle(); drawDiagram(); drawAgents(); drawFeed(); drawTasks(); drawReport();
    for (const id of open) loadOutput(id);
  }
  // the start form keeps what's typed: it's only redrawn when a cycle starts or ends
  function drawForm() {
    const c = st.cycle, key = `${active()}|${c?.id}|${pick}`;
    if (key === formKey) return; formKey = key;
    const f = $("#tm-form");
    if (active() || pick) { f.innerHTML = ""; return; }
    const goal = c?.status === "done" && c.next_goal ? c.next_goal : "";
    f.innerHTML = `<form class="card tm-start" id="tm-start"><div class="ws-card-head"><h3>${icon("users")}Run a team cycle on SN${n}</h3><span class="faint small">Plan → Do → Check → Act, by the project team on its own</span></div>
      <textarea name="goal" rows="2" maxlength="600" placeholder="What should the team achieve in this cycle?" required>${esc(goal)}</textarea>
      ${goal ? `<p class="faint small tm-hint">${icon("info")}Prefilled with the next goal from the last report.</p>` : `<div class="chips">${EXAMPLES.map(x => `<button type="button" class="chip" data-tm-ex="${esc(x)}">${esc(x)}</button>`).join("")}</div>`}
      <div class="tm-opts">
        <label>Token budget <select name="budget">${st.budgets.map(b => `<option value="${b}" ${b === 60000 ? "selected" : ""}>${tok(b)}</option>`).join("")}</select></label>
        <label>Repeat <select name="repeat_hours">${st.repeats.map(h => `<option value="${h}">${REPEAT[h]}</option>`).join("")}</select></label>
        <label class="chk" title="The team waits for your approval of the plan in Reports before doing anything"><input type="checkbox" name="approve_plan" checked> I approve the plan</label>
        <label class="chk" title="Tasks the tester rejects get one more attempt with her note"><input type="checkbox" name="rework" checked> One rework round</label>
        <button class="btn primary" type="submit">${icon("play")}Start cycle</button></div>
      <p class="fine">Uses the model picked in the Agents tab (${esc(model().model === "auto" ? "Auto" : model().model.split(":").slice(1).join(":"))}). The team works on its own; what only you can decide (the plan, more budget, funding, access, scope changes, serious risks) waits in <b>Reports</b> for your approval. To save tokens the team shares one fact sheet, passes summaries between teammates, caps tool calls, and asks before going past 80% of the budget.</p></form>`;
    $("#tm-start").onsubmit = async e => {
      e.preventDefault();
      const fd = new FormData(e.target), btn = e.target.querySelector("[type=submit]");
      btn.disabled = true; btn.classList.add("loading");
      try {
        const r = await api("/api/workspace/pdca", { method: "POST", body: { netuid: n, goal: fd.get("goal"), budget: +fd.get("budget"), repeat_hours: +fd.get("repeat_hours"), rework: fd.get("rework") === "on", approve_plan: fd.get("approve_plan") === "on", model: model().model } });
        if (st?.cycle?.id !== r.cycle.id) { st = r; events = r.events; open.clear(); }  // unless the stream got here first with newer news
        formKey = ""; draw(); toast("The team started a cycle");
      } catch (x) { toast(x.message); btn.disabled = false; btn.classList.remove("loading"); }
    };
  }
  function drawCycle() {
    const c = st.cycle, box = $("#tm-cycle");
    const hist = st.history.length > 1 || pick ? `<label class="tm-hist">History <select id="tm-pick"><option value="">Latest</option>${st.history.map(h => `<option value="${h.id}" ${h.id === pick ? "selected" : ""}>#${h.id} · ${esc(STATUS[h.status]?.[1] || h.status)}${h.score != null ? ` · ${h.score}/100` : ""} · ${new Date(h.created * 1000).toLocaleDateString()} · ${esc(h.goal.slice(0, 50))}</option>`).join("")}</select></label>` : "";
    const sched = st.schedule ? `<div class="tm-sched">${icon("clock")}<span>${REPEAT[st.schedule.repeat_hours] || `Every ${st.schedule.repeat_hours}h`}: next cycle ${st.schedule.next_run ? until(st.schedule.next_run) : "after this one"}</span><button type="button" class="linkbtn" data-tm-unsched="${st.schedule.cycle}">Stop schedule</button></div>` : "";
    if (!c) { box.innerHTML = sched || hist ? `<div class="card">${hist}${sched}</div>` : ""; return; }
    const ph = phaseOf(c), at = ACTIVE.indexOf(ph), finished = !active();
    const steps = PHASES.map(([k, l, ic], i) => {
      const cls = c.status === "done" || (at > i) ? "done" : at === i && !finished ? (c.status === "waiting" ? "on wait" : "on") : finished && c.status !== "done" ? "off" : "";
      return `<li class="${cls}"><span class="tm-dot">${icon(cls === "done" ? "check" : ic)}</span><b>${l}</b>${k === "do" && c.round > 1 ? `<small>round 2</small>` : cls === "on wait" ? `<small>needs you</small>` : ""}</li>`;
    }).join("");
    const used = c.tokens / c.budget, [bc, bl] = STATUS[c.status] || ["", c.status];
    const asks = (c.asks || []).filter(d => d.status === "pending");
    box.innerHTML = `<div class="card tm-cycle"><div class="ws-card-head"><h3>${icon("cycle")}Cycle #${c.id}</h3><div class="row">${hist}<span class="badge ${bc}">${active() && c.status !== "waiting" ? `<span class="tm-live"></span>` : ""}${esc(bl)}</span>
        ${active() ? `<button type="button" class="btn sm danger-text" data-tm-cancel ${c.cancelling ? "disabled" : ""}>${icon("stop")}${c.cancelling ? "Stopping…" : "Cancel"}</button>`
          : `<button type="button" class="btn sm danger-text" data-tm-reset title="Delete every cycle on SN${n} and start the project over">${icon("reset")}Reset project</button>`}</div></div>
      <p class="tm-goal"><b>${esc(c.goal)}</b>${c.objective && c.objective !== c.goal ? `<br><span class="muted">${esc(c.objective)}</span>` : ""}</p>
      ${asks.length ? `<div class="tm-ask">${icon("bell")}<div><b>${asks.length === 1 ? "Waiting for your approval" : `${asks.length} items wait for your approval`}</b>${asks.map(d => `<small>${esc(ASK[d.kind]?.[1] || d.kind)}: ${esc(d.title)}</small>`).join("")}</div><button type="button" class="btn sm primary" data-ws-tab="reports">Review in Reports</button></div>` : ""}
      <ol class="tm-steps">${steps}</ol>
      <div class="tm-meter" title="${fmtNum(c.tokens, 0)} of ${fmtNum(c.budget, 0)} tokens"><div class="ws-bar ${used > 0.8 ? "full" : ""}"><i style="width:${Math.min(100, used * 100).toFixed(1)}%"></i><em style="left:80%"></em></div>
        <small class="faint">${tok(c.tokens)} of ${tok(c.budget)} tokens${c.check ? ` · check ${c.check.score}/100, ${c.check.verdict}` : ""} · started ${ago(c.created)}${c.finished ? ` · took ${Math.max(1, Math.round((c.finished - c.created) / 60))} min` : ""}</small></div>
      ${c.guidance?.length ? `<div class="tm-guide">${icon("chat")}<div><b>Your notes to the team</b> <span class="faint small">every later task, the check and the report follow them</span><ul class="ws-ul">${c.guidance.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div></div>` : ""}
      ${c.criteria.length ? `<details class="tm-crit"><summary>Success criteria (${c.criteria.length})</summary><ul class="ws-ul">${c.criteria.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}
      ${c.error ? `<p class="no small">${icon("alert")}${esc(c.error)}</p>` : ""}${sched}</div>`;
  }

  // ---------- diagrams ----------
  function drawDiagram() {
    const box = $("#tm-diag"); if (!box || !st) return;
    const c = st.cycle;
    if (!c) { box.innerHTML = ""; return; }
    const W = Math.max(320, (box.clientWidth || $("#tm").clientWidth) - 34);
    box.innerHTML = `<div class="card tm-diag"><div class="ws-card-head"><h3>${icon("chart")}Diagrams</h3>
        <div class="seg"><button type="button" data-tm-diag="activity" aria-pressed="${diag === "activity"}">Activity</button><button type="button" data-tm-diag="schedule" aria-pressed="${diag === "schedule"}">Schedule</button></div></div>
      ${diag === "activity" ? activity(c, W) : schedule(c, W)}<div class="tm-tip" id="tm-tip" hidden></div></div>`;
  }
  // tick spacing for a span in seconds: the first step giving at most ~6 ticks
  const STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 21600, 43200, 86400];
  const dur = s => s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m${s % 60 >= 1 && s < 600 ? ` ${Math.round(s % 60)}s` : ""}` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
  const trunc = (s, k) => s.length > k ? s.slice(0, k - 1) + "…" : s;
  const tip = s => `data-tip="${esc(s)}"`;

  // Activity: a swimlane per agent on one time axis. Bars are tasks (status in the legend and tooltip), outlined bars
  // are phases an agent leads (plan, check, report), ticks are tool calls and diamonds are approvals they asked for.
  function activity(c, W) {
    const t0 = c.created, t1 = c.finished || Math.max(now(), t0 + 1), span = t1 - t0;
    const L = W < 520 ? 74 : 150, R = 10, TOP = 26, ROW = 34, BAR = 14, pw = W - L - R;
    const x = t => L + Math.max(0, Math.min(1, (t - t0) / span)) * pw;
    const tl = (c.timeline || []).map(([s, t], i, a) => ({ s, a: t, b: a[i + 1]?.[1] ?? t1 }));
    const lead = { pm: ["plan", "act"], tester: ["check"] }, LEADN = { plan: "Planning", act: "Report", check: "Check" };
    const lanes = [{ cycle: true, name: "Cycle", role: "phases" }, ...st.agents];
    const H = TOP + lanes.length * ROW + 6;
    const step = STEPS.find(s => span / s <= 6) || 86400;
    let g = "";
    for (let s = 0; s <= span; s += step) g += `<line class="dg-grid" x1="${x(t0 + s)}" x2="${x(t0 + s)}" y1="${TOP - 6}" y2="${H}"/><text class="dg-axis" x="${x(t0 + s)}" y="${TOP - 10}" text-anchor="${s === 0 ? "start" : "middle"}">${s === 0 ? clock(t0) : "+" + dur(s)}</text>`;
    lanes.forEach((a, i) => {
      const y = TOP + i * ROW, mid = y + ROW / 2;
      g += `<line class="dg-lane" x1="0" x2="${W}" y1="${y + ROW}" y2="${y + ROW}"/>`;
      g += `<text class="dg-name" x="0" y="${mid - (W < 520 ? 0 : 1)}" dominant-baseline="middle"><tspan font-weight="600">${esc(a.name)}</tspan>${W < 520 ? "" : `<tspan class="dg-role" x="0" dy="13">${esc(trunc((a.role || "").replace(/^Senior /, ""), 22))}</tspan>`}</text>`;
      if (a.cycle) {
        for (const p of tl) {
          const x1 = x(p.a), x2 = Math.max(x1 + 2, x(p.b) - 2), lbl = p.s === "waiting" ? "Waiting" : (STATUS[p.s]?.[1] || p.s);
          g += `<rect class="dg-phase ${p.s === "waiting" ? "wait" : ["done", "failed", "cancelled"].includes(p.s) ? "end" : ""}" x="${x1}" y="${mid - BAR / 2}" width="${x2 - x1}" height="${BAR}" rx="4" ${tip(`${lbl}: ${clock(p.a)}${p.s === "done" ? "" : `, ${dur(p.b - p.a)}`}`)}/>`;
          if (x2 - x1 > lbl.length * 6.5 + 8) g += `<text class="dg-in" x="${x1 + 6}" y="${mid}" dominant-baseline="central">${lbl}</text>`;
        }
        return;
      }
      for (const [k, ph] of Object.entries(lead)) if (a.key === k) for (const p of tl.filter(p => ph.includes(p.s))) {
        const x1 = x(p.a), x2 = Math.max(x1 + 4, x(p.b) - 2);
        g += `<rect class="dg-lead" x="${x1}" y="${mid - BAR / 2}" width="${x2 - x1}" height="${BAR}" rx="4" ${tip(`${a.name}: ${LEADN[p.s]} (${dur(p.b - p.a)})`)}/>`;
      }
      for (const t of st.tasks.filter(t => t.agent_id === a.id && t.started)) {
        const x1 = x(t.started), x2 = Math.max(x1 + 4, x(t.finished || t1) - 2);
        g += `<rect class="dg-bar st-${t.status}" x="${x1}" y="${mid - BAR / 2}" width="${x2 - x1}" height="${BAR}" rx="4" ${tip(`${a.name} · task ${t.seq}: ${t.title}\n${TASK[t.status]?.[1] || t.status}${t.verdict ? `, ${t.verdict}` : ""} · ${dur((t.finished || now()) - t.started)}${t.tokens ? ` · ${tok(t.tokens)} tokens` : ""}`)}/>`;
        if (x2 - x1 > 26) g += `<text class="dg-in on" x="${x1 + 5}" y="${mid}" dominant-baseline="central">${t.seq}</text>`;
      }
      for (const e of events.filter(e => e.agent_id === a.id && e.kind === "tool")) g += `<line class="dg-tick" x1="${x(e.ts)}" x2="${x(e.ts)}" y1="${mid + BAR / 2 + 2}" y2="${mid + BAR / 2 + 7}" ${tip(`${a.name}: ${e.text} · ${clock(e.ts)}`)}/>`;
      for (const d of (c.asks || []).filter(d => d.agent_id === a.id)) {
        const cx = x(d.created), cy = y + 7;
        g += `<path class="dg-ask ${d.status}" d="M${cx} ${cy - 6}l6 6-6 6-6-6z" ${tip(`${a.name} asked (${ASK[d.kind]?.[1] || d.kind}): ${d.title}\n${d.status === "pending" ? "Waiting for you" : d.status}`)}/>`;
      }
    });
    if (active()) g += `<line class="dg-now" x1="${x(now())}" x2="${x(now())}" y1="${TOP - 4}" y2="${H}"/>`;
    const legend = [["st-running", "Working"], ["st-done", "Done"], ["st-failed", "Failed"], ["st-skipped", "Skipped"], ["dg-lead", "Leads a phase"], ["wait", "Waiting for you"]]
      .map(([k, l]) => `<span><i class="lg ${k}"></i>${l}</span>`).join("") + `<span><i class="lg tick"></i>Tool call</span><span><i class="lg diamond"></i>Asked for approval</span>${active() ? `<span><i class="lg now"></i>Now</span>` : ""}`;
    return `<svg class="dg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Activity of every agent in cycle ${c.id} over time">${g}</svg><div class="dg-legend">${legend}</div>
      <p class="fine">Every agent's activity in one view. Hover a mark for details; the task list below is the same data as a table.</p>`;
  }

  // Schedule: the plan as a dependency graph. Plan → tasks (columns by what they wait on) → Check → Act.
  function schedule(c, W) {
    const ts = st.tasks, who = Object.fromEntries(st.agents.map(a => [a.id, a])), depth = {};
    const d = t => depth[t.seq] ??= t.depends.length ? 1 + Math.max(...t.depends.map(s => d(ts.find(x => x.seq === s) || { depends: [] }))) : 0;
    ts.forEach(d);
    const ph = phaseOf(c), passed = s => c.status === "done" || ACTIVE.indexOf(ph) > ACTIVE.indexOf(s);
    const phaseSt = s => passed(s) ? "done" : ph === s && active() ? (c.status === "waiting" ? "waiting" : "running") : ["failed", "cancelled"].includes(c.status) ? "skipped" : "queued";
    const cols = [[{ id: "plan", label: "Plan", sub: who[st.agents.find(a => a.key === "pm")?.id]?.name || "Paige", st: phaseSt("plan") }]];
    for (const t of ts) (cols[depth[t.seq] + 1] ??= []).push({ id: t.seq, t, label: `${t.seq}. ${t.title}`, sub: `${who[t.agent_id]?.name || t.role} · ${TASK[t.status]?.[1] || t.status}`, st: t.status });
    for (let i = 1; i < cols.length; i++) cols[i] ??= [];
    cols.push([{ id: "check", label: "Check", sub: st.agents.find(a => a.key === "tester")?.name || "Tessa", st: phaseSt("check") }], [{ id: "act", label: "Act: report", sub: st.agents.find(a => a.key === "pm")?.name || "Paige", st: phaseSt("act") }]);
    const NW = W < 700 ? 150 : 176, NH = 46, GX = W < 700 ? 26 : 40, GY = 12, need = cols.length * NW + (cols.length - 1) * GX;
    const w = Math.max(W, need), gap = cols.length > 1 ? (w - cols.length * NW) / (cols.length - 1) : 0;
    const rows = Math.max(...cols.map(x => x.length)), H = rows * NH + (rows - 1) * GY + 8;
    const pos = {};
    cols.forEach((col, i) => col.forEach((nd, j) => { pos[nd.id] = { x: i * (NW + gap), y: 4 + (H - 8 - (col.length * NH + (col.length - 1) * GY)) / 2 + j * (NH + GY), nd }; }));
    const edge = (a, b, cls = "") => { const p = pos[a], q = pos[b]; if (!p || !q) return ""; const x1 = p.x + NW, y1 = p.y + NH / 2, x2 = q.x - 4, y2 = q.y + NH / 2, m = (x1 + x2) / 2;
      return `<path class="dg-edge ${cls}" d="M${x1} ${y1}C${m} ${y1} ${m} ${y2} ${x2} ${y2}" marker-end="url(#dg-arrow)"/>`; };
    let e = "";
    const leaves = ts.filter(t => !ts.some(o => o.depends.includes(t.seq)));
    for (const t of ts) e += t.depends.length ? t.depends.map(s => edge(s, t.seq, "dep")).join("") : edge("plan", t.seq);
    e += ts.length ? leaves.map(t => edge(t.seq, "check")).join("") : edge("plan", "check");
    e += edge("check", "act");
    const nodes = Object.values(pos).map(({ x, y, nd }) => `<g class="dg-node st-${nd.st}" transform="translate(${x} ${y})" ${tip(`${nd.t ? `${nd.label}\n${nd.t.instructions}` : nd.label}\n${nd.sub.includes("·") ? "" : nd.sub + " · "}${TASK[nd.st]?.[1] || (nd.st === "waiting" ? "Waiting for you" : nd.st)}${nd.t?.depends.length ? `\nAfter task ${nd.t.depends.join(", ")}` : ""}`)}>
        <rect width="${NW}" height="${NH}" rx="8"/><rect class="strip" width="4" height="${NH - 12}" x="6" y="6" rx="2"/>
        <text x="16" y="19">${esc(trunc(nd.label, NW < 176 ? 21 : 25))}</text><text class="sub" x="16" y="35">${esc(trunc(nd.t ? nd.sub : `${nd.sub} · ${TASK[nd.st]?.[1] || (nd.st === "waiting" ? "Needs you" : nd.st)}`, NW < 176 ? 24 : 28))}</text></g>`).join("");
    const nextRun = st.schedule ? `${REPEAT[st.schedule.repeat_hours] || `Every ${st.schedule.repeat_hours}h`} · next cycle ${st.schedule.next_run ? `${until(st.schedule.next_run)} (${new Date(st.schedule.next_run * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })})` : "after this one finishes"}` : "Runs once (no repeat)";
    return `<div class="dg-scroll"><svg class="dg" width="${w}" height="${H}" viewBox="0 0 ${w} ${H}" role="img" aria-label="Task schedule for cycle ${c.id}: plan, tasks by dependency, check and report">
        <defs><marker id="dg-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" class="dg-arrowhead"/></marker></defs>${e}${nodes}</svg></div>
      <div class="dg-legend"><span><i class="lg st-queued"></i>Queued</span><span><i class="lg st-running"></i>Working</span><span><i class="lg st-done"></i>Done</span><span><i class="lg st-failed"></i>Failed</span><span><i class="lg st-skipped"></i>Skipped</span><span><i class="lg wait"></i>Waiting for you</span></div>
      <div class="tm-sched">${icon("calendar")}<span><b>Schedule:</b> ${esc(nextRun)} · tasks in the same column run in parallel (two at a time), arrows are hand-offs${c.approve_plan ? " · the plan waits for your approval" : ""}</span></div>`;
  }

  function drawAgents() {
    $("#tm-agents").innerHTML = `<div class="card"><div class="ws-card-head"><h3>${icon("users")}Team</h3><span class="faint small">${st.agents.filter(a => a.state === "working").length} working</span></div>
      <div class="tm-agents">${st.agents.map(a => `<div class="tm-agent ${a.state}">${agentAvatar(a, "sm")}<div class="tm-agent-txt"><b>${esc(a.name)} <span class="faint">· ${esc(a.role)}</span></b>
        <small>${esc(a.detail || (a.state === "idle" ? "No task in this cycle" : ""))}</small>${a.last && a.state !== "idle" ? `<small class="faint">${esc(a.last.text.slice(0, 90))} · ${ago(a.last.ts)}</small>` : ""}</div>
        <div class="tm-agent-side"><span class="tm-state ${a.state}">${STATE[a.state] || a.state}</span>${a.tokens ? `<small class="faint num">${tok(a.tokens)} tok</small>` : ""}</div></div>`).join("")
        || `<p class="faint small">The project team is created when you start the first cycle.</p>`}</div></div>`;
  }
  function drawFeed() {
    const xs = [...events].reverse().slice(0, 60), who = Object.fromEntries(st.agents.map(a => [a.id, a]));
    $("#tm-feed").innerHTML = `<div class="card"><div class="ws-card-head"><h3>${icon("news")}Activity</h3>${active() ? `<span class="faint small"><span class="tm-live"></span>Live</span>` : ""}</div>
      <ul class="tm-feed">${xs.map(e => `<li class="k-${esc(e.kind)}">${who[e.agent_id] ? agentAvatar(who[e.agent_id], "xs") : `<span class="tm-ic">${icon(KIND[e.kind] || "info")}</span>`}
        <span><b>${who[e.agent_id] ? esc(who[e.agent_id].name) + " " : ""}</b>${esc(e.text)}${e.tokens ? ` <span class="faint num">· ${tok(e.tokens)} tok</span>` : ""}</span><time class="faint" title="${esc(stamp(e.ts))}">${clock(e.ts)}</time></li>`).join("")
        || `<li class="faint">Nothing yet. Start a cycle to watch the team work.</li>`}</ul></div>`;
  }
  function drawTasks() {
    const ts = st.tasks, who = Object.fromEntries(st.agents.map(a => [a.id, a]));
    if (!ts.length) { $("#tm-tasks").innerHTML = ""; return; }
    $("#tm-tasks").innerHTML = `<div class="card"><div class="ws-card-head"><h3>${icon("zap")}Tasks</h3><span class="faint small">${ts.filter(t => t.status === "done").length} of ${ts.length} done</span></div>
      <div class="tm-tasks">${ts.map(t => { const a = who[t.agent_id], [sc, sl] = TASK[t.status] || ["", t.status], o = outputs[t.id];
        return `<div class="tm-task ${open.has(t.id) ? "open" : ""}"><button type="button" class="tm-task-head" data-tm-task="${t.id}" aria-expanded="${open.has(t.id)}">
          <span class="tm-seq num">${t.seq}</span>${a ? agentAvatar(a, "xs") : ""}<span class="tm-task-txt"><b>${esc(t.title)}</b><small class="faint">${esc(a?.name || t.role)}${t.depends.length ? ` · after ${t.depends.join(", ")}` : ""}${t.tokens ? ` · ${tok(t.tokens)} tok` : ""}${t.attempts > 1 ? " · 2nd attempt" : ""}</small></span>
          ${t.verdict ? `<span class="badge ${t.verdict === "pass" ? "clear" : "caution"}">${t.verdict === "pass" ? "Pass" : "Rework"}</span>` : ""}<span class="badge ${sc}">${t.status === "running" ? `<span class="tm-live"></span>` : ""}${sl}</span>${icon("chev")}</button>
          ${open.has(t.id) ? `<div class="tm-task-body"><p class="muted small">${esc(t.instructions)}</p>${t.summary ? `<p><b>Summary:</b> ${esc(t.summary)}</p>` : ""}${t.check_note && t.verdict === "rework" ? `<p class="tm-note">${icon("shield")}<span><b>Tessa:</b> ${esc(t.check_note)}</span></p>` : ""}${t.user_note ? `<p class="tm-note">${icon("chat")}<span><b>You:</b> ${esc(t.user_note)}</span></p>` : ""}${taskActs(t)}
            ${t.status === "done" || t.status === "failed" ? o?.output != null ? Doc.block({ key: `out${t.id}`, title: `Task ${t.seq}: ${t.title}`, text: o.output || "", netuid: n, cls: "tm-out" }) : Loading.line("Loading output…") : t.status === "running" ? Loading.line(`${esc(a?.name || "The agent")} is working on it…`) : ""}</div>` : ""}</div>`; }).join("")}</div></div>`;
  }
  // what the user can do with a task: edit it (owner, title, instructions) and have its agent do it again
  function taskActs(t) {
    if (t.status === "running") return "";
    const again = t.status !== "queued";
    return `<div class="row tm-task-acts"><button type="button" class="btn sm" data-tm-edit="${t.id}">${icon("edit")}Edit${again ? " & redo" : ""}</button>
      ${again ? `<button type="button" class="btn sm" data-tm-redo="${t.id}">${icon("cycle")}Redo</button>` : ""}</div>`;
  }
  function redoTask(t) {
    const a = st.agents.find(x => x.id === t.agent_id);
    Auth.modal(`<h3>${icon("cycle")}Redo task ${t.seq}</h3><p class="muted small">${esc(t.title)}</p>
      <label class="in"><span>Note for ${esc(a?.name || "the agent")} <span class="faint">(optional)</span></span><textarea name="note" rows="3" maxlength="1000" placeholder="What to do differently: they follow it"></textarea></label>
      <p class="fine">${active() ? "It joins the running cycle." : "It runs now on its own; the check and report stay as they were."}</p>`,
      async f => { await api(`/api/workspace/pdca/tasks/${t.id}/redo`, { method: "POST", body: { note: f.elements.note.value } }); $("#modal").close(); delete outputs[t.id]; toast(`${a?.name || "The agent"} is on it again`); },
      { submit: "Redo" });
  }
  function editTask(t) {
    const again = t.status !== "queued", m = $("#modal");
    const owners = st.agents.filter(a => a.state !== "paused" || a.id === t.agent_id);
    const f = Auth.modal(`<h3>${icon("edit")}Edit task ${t.seq}</h3>
      <label class="in"><span>Owner</span><select name="role">${owners.map(a => `<option value="${a.key}" ${a.id === t.agent_id ? "selected" : ""}>${esc(a.name)} · ${esc(a.role.replace(/^Senior /, ""))}</option>`).join("")}</select></label>
      <label class="in"><span>Title</span><input name="title" maxlength="140" value="${esc(t.title)}" required></label>
      <label class="in"><span>Instructions</span><textarea name="instructions" rows="5" maxlength="700">${esc(t.instructions || "")}</textarea></label>
      ${again ? `<label class="in"><span>Note for the agent <span class="faint">(optional)</span></span><textarea name="note" rows="2" maxlength="1000" placeholder="What to do differently"></textarea></label>` : ""}
      <p class="fine">${again ? "Save &amp; redo has the owner do it again with your changes." : "The team picks it up with your changes."}</p>`,
      async f => save(f, again), { submit: again ? "Save & redo" : "Save" });
    if (again) $("[type=submit]", f).insertAdjacentHTML("beforebegin", `<button type="button" class="btn" data-te-only>Save only</button>`);
    $("[data-te-only]", f)?.addEventListener("click", () => save(f, false).catch(e => { $(".err", f).textContent = e.message; }));
    async function save(f, redo) {
      const el = f.elements;
      await api(`/api/workspace/pdca/tasks/${t.id}`, { method: "PATCH", body: { role: el.role.value, title: el.title.value, instructions: el.instructions.value, redo, note: el.note?.value || "" } });
      m.close(); delete outputs[t.id]; toast(redo ? "Saved: the agent is doing it again" : "Task saved");
    }
  }
  function resetProject() {
    const k = st.history.length;
    Auth.modal(`<h3>${icon("reset")}Reset the project on SN${n}?</h3>
      <p class="muted small">Deletes ${k >= 12 ? "every" : `all ${k}`} cycle${k === 1 ? "" : "s"} on SN${n} with their tasks, activity, reports and decisions, and stops the schedule. The team members and their settings stay. This can't be undone.</p>
      <label class="chk"><input type="checkbox" name="notes"> Also delete the cycles' notes on the PDCA board</label>`,
      async f => {
        const r = await api("/api/workspace/pdca/reset", { method: "POST", body: { netuid: n, notes: f.elements.notes.checked } });
        $("#modal").close(); pick = null; open.clear(); formKey = ""; toast(`Project reset: ${r.cycles} cycle${r.cycles === 1 ? "" : "s"} deleted`); load();
      }, { submit: `Reset SN${n}`, danger: true });
  }
  function drawReport() {
    const c = st.cycle;
    if (!c?.check && !c?.report) { $("#tm-report").innerHTML = ""; return; }
    $("#tm-report").innerHTML = `<div class="ws-grid2">${c.check ? `<div class="card"><div class="ws-card-head"><h3>${icon("shield")}Check</h3><span class="badge ${c.check.verdict === "go" ? "clear" : "caution"}">${c.check.score}/100 · ${c.check.verdict}</span></div>
        ${Doc.block({ key: `chk${c.id}`, title: `Check of cycle ${c.id}: ${c.check.score}/100, ${c.check.verdict}`, text: c.check.findings.length ? c.check.findings.map(x => `- ${x}`).join("\n") : "No findings.", netuid: c.netuid })}</div>` : ""}
      ${c.report ? `<div class="card"><div class="ws-card-head"><h3>${icon("trophy")}Act: report</h3>${c.note_id ? `<button type="button" class="linkbtn" data-ws-note="${c.note_id}">Open on the PDCA board</button>` : ""}</div>${Doc.block({ key: `rep${c.id}`, title: `Report of cycle ${c.id}: ${c.goal}`, text: c.report, netuid: c.netuid, edit: () => editReport(c.id, c.report, `Report of cycle ${c.id}`) })}
        ${c.next_goal ? `<p class="tm-note">${icon("right")}<span><b>Next goal:</b> ${esc(c.next_goal)}</span></p>` : ""}</div>` : ""}</div>`;
  }
  async function loadOutput(id) {
    const t = st.tasks.find(x => x.id === id);
    if (!t || outputs[id] || !["done", "failed"].includes(t.status)) return;
    outputs[id] = { status: t.status, loading: true };
    try { const r = await api(`/api/workspace/pdca/tasks/${id}`); outputs[id] = { ...r, status: t.status }; if ($("#tm")) drawTasks(); }
    catch (e) { delete outputs[id]; toast(e.message); }
  }

  // ---------- Reports tab ----------
  function reports(pane, netuid) {
    n = netuid; mode = "reports";
    clearInterval(tick); tick = null; ro?.disconnect(); ro = null;
    pane.innerHTML = `<div class="rp" id="rp">${Loading.cards(2, "card")}</div>`;
    loadReports(); listen();
  }
  async function loadReports(quiet) {
    const s = ++repSeq;
    try { const r = await api(`/api/workspace/pdca/decisions${repScope === "here" && n != null ? `?netuid=${n}` : ""}`); if (s !== repSeq || !$("#rp")) return; rep = r; Workspace.setPending(r.pending_total); }
    catch (e) { if (!quiet && $("#rp")) $("#rp").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    drawReports();
  }
  function drawReports() {
    const box = $("#rp"); if (!box || !rep) return;
    // keep notes typed into open requests across live redraws
    $$("[data-rp-note]", box).forEach(t => { notes[t.dataset.rpNote] = t.value; });
    const who = d => d.agent ? `${agentAvatar(d.agent, "xs")}<b>${esc(d.agent.name)}</b> <span class="faint">· ${esc(d.agent.role)}</span>` : `<span class="tm-ic">${icon("users")}</span><b>The team</b>`;
    const kind = d => `<span class="badge ${d.kind === "risk" ? "avoid" : d.kind === "plan" ? "new" : "caution"}">${icon(ASK[d.kind]?.[0] || "info")}${esc(ASK[d.kind]?.[1] || d.kind)}</span>`;
    const where = d => `<span class="faint small">SN${d.netuid} · cycle #${d.cycle_id} · ${ago(d.created)}</span>`;
    const blocking = d => d.source === "system" ? `<span class="faint small">${icon("clock")}The cycle is paused until you decide.</span>` : `<span class="faint small">${icon("zap")}The team keeps working meanwhile; approve and ${esc(d.agent?.name || "the agent")} gets a follow-up task.</span>`;
    // selections survive live redraws, minus what's gone
    const ids = { pend: rep.pending.map(d => d.id), rep: rep.reports.map(r => r.id), dec: rep.decided.map(d => d.id) };
    for (const k in sel) for (const id of sel[k]) if (!ids[k].includes(id)) sel[k].delete(id);
    const box1 = (k, id, label) => `<input type="checkbox" class="rp-sel" data-rp-sel="${k}:${id}" ${sel[k].has(id) ? "checked" : ""} aria-label="Select ${esc(label)}">`;
    const selAll = k => ids[k].length > 1 ? `<label class="chk sm"><input type="checkbox" data-rp-selall="${k}" ${sel[k].size === ids[k].length ? "checked" : ""}>Select all</label>` : "";
    const delSel = k => sel[k].size ? `<button type="button" class="btn sm danger-text" data-rp-delsel="${k}">${icon("trash")}Delete ${sel[k].size}</button>` : "";
    const placeholder = d => d.kind === "plan" && d.source === "system" ? "Your note: approve with it and Paige applies it to the plan; reject with it and she plans again"
      : d.source === "agent" ? `Your note: ${d.agent?.name || "the agent"} acts on it whether you approve or reject` : "Your note: the whole team follows it for the rest of the cycle";
    const pend = rep.pending.map(d => `<div class="card rp-item" data-rp="${d.id}"><div class="rp-head">${box1("pend", d.id, d.title)}${kind(d)}<span class="rp-who">${who(d)}</span>${where(d)}</div>
        <h4>${esc(d.title)}</h4>${d.detail ? Doc.block({ key: `dec${d.id}`, title: d.title, text: d.detail, netuid: d.netuid, edit: editorFor(d), cls: "rp-detail" }) : ""}${blocking(d)}
        <textarea rows="1" maxlength="1000" data-rp-note="${d.id}" placeholder="${esc(placeholder(d))}">${esc(notes[d.id] || "")}</textarea>
        <div class="row rp-acts"><button type="button" class="btn sm" data-rp-no="${d.id}">${icon("close")}Reject</button><button type="button" class="btn sm primary" data-rp-yes="${d.id}">${icon("check")}Approve</button></div></div>`).join("");
    const done = rep.decided.map(d => `<li>${box1("dec", d.id, d.title)}<span class="badge ${d.status === "approved" ? "clear" : d.status === "rejected" ? "avoid" : ""}">${esc(d.status === "approved" ? "Approved" : d.status === "rejected" ? "Rejected" : "Expired")}</span>
        <span>${esc(ASK[d.kind]?.[1] || d.kind)}: ${esc(d.title)}${d.note ? ` <span class="faint">(“${esc(d.note)}”)</span>` : ""}${d.outcome ? `<small class="rp-outcome">${icon("right")}${esc(d.outcome)}</small>` : ""}<small class="faint rp-meta">${d.agent ? esc(d.agent.name) + " · " : ""}SN${d.netuid} · ${ago(d.decided || d.created)}</small></span>
        <button type="button" class="iconbtn sm" data-rp-del="dec:${d.id}" title="Delete" aria-label="Delete">${icon("trash")}</button></li>`).join("");
    const reps = rep.reports.map(r => `<div class="rp-report-row">${box1("rep", r.id, r.goal)}<details class="rp-report"><summary><span class="badge ${STATUS[r.status]?.[0] || ""}">${esc(STATUS[r.status]?.[1] || r.status)}</span><b>${esc(r.goal)}</b><span class="faint small">SN${r.netuid} · #${r.id}${r.check ? ` · ${r.check.score}/100 ${r.check.verdict}` : ""} · ${tok(r.tokens)} tok${r.finished ? ` · ${ago(r.finished)}` : ""}</span></summary>
        ${Doc.block({ key: `rep${r.id}`, title: `Report of cycle ${r.id}: ${r.goal}`, text: r.report || "", netuid: r.netuid, edit: () => editReport(r.id, r.report, `Report of cycle ${r.id}`) })}${r.next_goal ? `<p class="tm-note">${icon("right")}<span><b>Next goal:</b> ${esc(r.next_goal)}</span></p>` : ""}</details>
        <button type="button" class="iconbtn sm" data-rp-del="rep:${r.id}" title="Delete report" aria-label="Delete report">${icon("trash")}</button></div>`).join("");
    box.innerHTML = `<div class="card rp-top"><div class="ws-card-head"><h3>${icon("bell")}Needs your approval <span class="faint">${rep.pending.length}</span></h3>
        <div class="row">${n != null ? `<div class="seg"><button type="button" data-rp-scope="here" aria-pressed="${repScope === "here"}">SN${n}</button><button type="button" data-rp-scope="all" aria-pressed="${repScope === "all"}">All subnets</button></div>` : ""}
        ${selAll("pend")}${sel.pend.size ? `<button type="button" class="btn sm" data-rp-bulk="0">${icon("close")}Reject ${sel.pend.size}</button><button type="button" class="btn sm primary" data-rp-bulk="1">${icon("check")}Approve ${sel.pend.size}</button>`
          : rep.pending.length > 1 ? `<button type="button" class="btn sm primary" data-rp-all>${icon("check")}Approve all ${rep.pending.length}</button>` : ""}</div></div>
        <p class="faint small">The team works on its own and stops here only for what you decide: the plan, more token budget, funding, access and permissions, scope changes and serious risks. Whatever you write in a note, the team does, whether you approve or reject.${repScope === "here" && rep.pending_total > rep.pending.length ? ` <b>${rep.pending_total - rep.pending.length} more on other subnets.</b>` : ""}</p></div>
      ${pend || `<div class="card empty">${icon("check")} Nothing waits for you${repScope === "here" ? ` on SN${n}` : ""}.</div>`}
      ${reps ? `<div class="card"><div class="ws-card-head"><h3>${icon("trophy")}Cycle reports</h3><div class="row">${selAll("rep")}${delSel("rep")}</div></div><div class="rp-reports">${reps}</div></div>` : ""}
      ${done ? `<div class="card"><div class="ws-card-head"><h3>${icon("clock")}Decided</h3><div class="row">${selAll("dec")}${delSel("dec")}</div></div><ul class="rp-done">${done}</ul></div>` : ""}`;
    for (const k in sel) { const a = $(`[data-rp-selall="${k}"]`, box); if (a) a.indeterminate = sel[k].size > 0 && sel[k].size < ids[k].length; }
  }
  // what Edit means for each request: the plan gets the plan editor, a budget raise its amount, an agent's request its text
  function editorFor(d) {
    if (d.kind === "plan" && d.source === "system") return () => planEditor(d);
    if (d.kind === "budget") return () => budgetEditor(d);
    if (d.source === "agent") return () => Doc.editText({ title: `Edit ${d.agent?.name || "the agent"}'s request`, text: d.detail,
      hint: "What you approve here is what the follow-up task carries out.",
      onSave: async t => { await api(`/api/workspace/pdca/decisions/${d.id}`, { method: "PATCH", body: { detail: t } }); toast("Request updated"); loadReports(true); } });
    return null;
  }
  function editReport(cid, text, title) {
    Doc.editText({ title: `Edit the ${title.toLowerCase()}`, text, hint: "Your version replaces the team's report here and on the PDCA board.",
      onSave: async t => { await api(`/api/workspace/pdca/${cid}/report`, { method: "PUT", body: { report: t } }); toast("Report saved"); mode === "reports" ? loadReports(true) : load(); } });
  }
  function budgetEditor(d) {
    const cur = d.payload?.extra || 15000;
    Auth.modal(`<h3>${icon("coins")}Change the budget raise</h3><p class="muted small">${esc(d.title)}</p>
      <label class="in"><span>Extra tokens</span><input name="extra" type="number" min="5000" max="500000" step="5000" value="${cur}"></label>
      <p class="fine">Between 5,000 and 500,000. Approve afterwards to apply it.</p>`, async f => {
      await api(`/api/workspace/pdca/decisions/${d.id}`, { method: "PATCH", body: { extra: +f.elements.extra.value } });
      $("#modal").close(); toast("Budget raise changed"); loadReports(true);
    }, { submit: "Save" });
  }
  // the plan as a form: objective, criteria, and each task's owner, title, instructions and hand-offs
  async function planEditor(d) {
    let p;
    try { p = await api(`/api/workspace/pdca/decisions/${d.id}/plan`); } catch (e) { return toast(e.message); }
    const m = $("#modal");
    const row = (t, i) => `<div class="pe-task" data-i="${i}"><div class="pe-top"><span class="tm-seq num">${i + 1}</span>
        <select data-k="role" aria-label="Owner">${p.owners.map(o => `<option value="${o.key}" ${o.key === t.role ? "selected" : ""}>${esc(o.name)} · ${esc(o.role.replace(/^Senior /, ""))}</option>`).join("")}</select>
        <input data-k="title" value="${esc(t.title)}" maxlength="140" placeholder="Task title" aria-label="Title">
        <button type="button" class="iconbtn sm" data-pe-up="${i}" ${i ? "" : "disabled"} title="Move up" aria-label="Move up">${icon("up")}</button>
        <button type="button" class="iconbtn sm" data-pe-rm="${i}" title="Remove task" aria-label="Remove task">${icon("close")}</button></div>
        <textarea data-k="instructions" rows="2" maxlength="700" placeholder="What to produce" aria-label="Instructions">${esc(t.instructions)}</textarea>
        ${i ? `<div class="pe-deps"><span class="faint small">After:</span>${p.tasks.slice(0, i).map((_, j) => `<label class="chk sm"><input type="checkbox" data-dep="${j + 1}" ${t.depends.includes(j + 1) ? "checked" : ""}>${j + 1}</label>`).join("")}</div>` : ""}</div>`;
    const f = Auth.modal(`<div class="pe"><h3>${icon("edit")}Edit the plan</h3><p class="muted small">Change what the team will do before you approve. Tasks without hand-offs run in parallel.</p>
        <label class="in"><span>Objective</span><textarea name="objective" rows="2" maxlength="600">${esc(p.objective)}</textarea></label>
        <label class="in"><span>Success criteria <span class="faint">(one per line)</span></span><textarea name="criteria" rows="3">${esc(p.criteria.join("\n"))}</textarea></label>
        <div class="field"><span class="lbl">Tasks</span><div class="pe-tasks"></div><button type="button" class="btn sm" data-pe-add>${icon("plus")}Add task</button></div></div>`,
      async () => { await save(); m.close(); toast("Plan saved: approve it when ready"); loadReports(true); }, { submit: "Save" });
    m.classList.add("doc-wide"); m.addEventListener("close", () => m.classList.remove("doc-wide"), { once: true });
    $("[type=submit]", f).insertAdjacentHTML("beforebegin", `<button type="button" class="btn" data-pe-approve>${icon("check")}Save &amp; approve</button>`);
    const list = $(".pe-tasks", f);
    const read = () => $$(".pe-task", f).forEach((el, i) => {  // the form back into p.tasks
      const t = p.tasks[i];
      t.role = $("[data-k=role]", el).value; t.title = $("[data-k=title]", el).value; t.instructions = $("[data-k=instructions]", el).value;
      t.depends = $$("[data-dep]:checked", el).map(x => +x.dataset.dep);
    });
    const draw = () => { list.innerHTML = p.tasks.map(row).join(""); $("[data-pe-add]", f).disabled = p.tasks.length >= p.max_tasks; };
    // moving or removing a task renumbers the hand-offs that point at it
    const renumber = map => p.tasks.forEach(t => { t.depends = [...new Set(t.depends.map(map).filter(x => x))].sort((a, b) => a - b); });
    draw();
    f.addEventListener("click", e => {
      const t = e.target;
      if (t.closest("[data-pe-add]")) { read(); p.tasks.push({ role: p.owners[0]?.key, title: "", instructions: "", depends: [] }); return draw(); }
      const rm = t.closest("[data-pe-rm]"); if (rm) { read(); const k = +rm.dataset.peRm; p.tasks.splice(k, 1); renumber(x => x === k + 1 ? 0 : x > k + 1 ? x - 1 : x); return draw(); }
      const up = t.closest("[data-pe-up]"); if (up) {
        read(); const k = +up.dataset.peUp; [p.tasks[k - 1], p.tasks[k]] = [p.tasks[k], p.tasks[k - 1]];
        renumber(x => x === k ? k + 1 : x === k + 1 ? k : x);
        p.tasks.forEach((x, i) => { x.depends = x.depends.filter(d => d <= i); });  // a task can only wait on tasks before it
        return draw();
      }
      if (t.closest("[data-pe-approve]")) busyApprove();
    });
    async function save() {
      read();
      await api(`/api/workspace/pdca/decisions/${d.id}/plan`, { method: "PUT", body: { objective: f.elements.objective.value,
        criteria: f.elements.criteria.value.split("\n").map(x => x.trim()).filter(Boolean), tasks: p.tasks } });
    }
    async function busyApprove() {
      try { await save(); await api(`/api/workspace/pdca/decisions/${d.id}`, { method: "POST", body: { approve: true, note: "" } }); m.close(); toast("Plan saved and approved"); loadReports(true); }
      catch (e) { $(".err", f).textContent = e.message; }
    }
  }
  async function decide(id, approve) {
    const note = $(`[data-rp-note="${id}"]`)?.value || "";
    try { await api(`/api/workspace/pdca/decisions/${id}`, { method: "POST", body: { approve, note } }); delete notes[id]; toast(note ? `${approve ? "Approved" : "Rejected"}: the team acts on your note` : approve ? "Approved: the team carries on" : "Rejected"); }
    catch (e) { toast(e.message); }
    loadReports(true);
  }
  // approve or reject several at once, with one note for all of them (each item's own note box is used when that's empty)
  function bulkDecide(xs, approve) {
    Auth.modal(`<h3>${icon(approve ? "check" : "close")}${approve ? "Approve" : "Reject"} ${xs.length}?</h3><ul class="ws-ul">${xs.map(d => `<li><b>${esc(ASK[d.kind]?.[1] || d.kind)}:</b> ${esc(d.title)} <span class="faint">(${esc(d.agent?.name || "the team")}, SN${d.netuid})</span></li>`).join("")}</ul>
      <label class="in"><span>Note for all of them <span class="faint">(optional: the team acts on it)</span></span><textarea name="note" rows="2" maxlength="1000"></textarea></label>
      <p class="muted small">${approve ? "Funding and access items become follow-up tasks; the team can't spend money or change permissions itself, so it tells you what to do by hand."
        : "Rejected plans stop their cycle unless there's a note (then Paige plans again); rejected requests with a note become follow-up tasks that do what it says."}</p>`,
      async f => {
        const shared = f.elements.note.value.trim();
        let k = 0;
        if (shared) k = (await api("/api/workspace/pdca/decisions/bulk", { method: "POST", body: { ids: xs.map(d => d.id), approve, note: shared } })).done;
        else for (const d of xs) {  // each with its own note
          try { await api(`/api/workspace/pdca/decisions/${d.id}`, { method: "POST", body: { approve, note: $(`[data-rp-note="${d.id}"]`)?.value || "" } }); k++; delete notes[d.id]; } catch {}
        }
        $("#modal").close(); sel.pend.clear(); toast(`${approve ? "Approved" : "Rejected"} ${k}`); loadReports(true);
      }, { submit: `${approve ? "Approve" : "Reject"} ${xs.length}`, danger: !approve });
  }
  const approveAll = () => bulkDecide(rep.pending, true);
  function removeItems(k, idList) {
    const what = k === "rep" ? ["report", "reports", "The cycles stay in the Team tab's history; only their reports go."] : ["decided item", "decided items", "They leave this list; the cycles keep their activity."];
    const xs = k === "rep" ? rep.reports.filter(r => idList.includes(r.id)).map(r => r.goal) : rep.decided.filter(d => idList.includes(d.id)).map(d => d.title);
    Auth.modal(`<h3>${icon("trash")}Delete ${xs.length} ${xs.length === 1 ? what[0] : what[1]}?</h3><ul class="ws-ul">${xs.slice(0, 8).map(x => `<li>${esc(x)}</li>`).join("")}${xs.length > 8 ? `<li class="faint">and ${xs.length - 8} more</li>` : ""}</ul>
      <p class="muted small">${what[2]} This can't be undone.</p>`,
      async () => {
        const r = await api("/api/workspace/pdca/remove", { method: "POST", body: k === "rep" ? { reports: idList } : { decisions: idList } });
        $("#modal").close(); idList.forEach(id => sel[k].delete(id)); toast(`Deleted ${k === "rep" ? r.reports : r.decisions}`); loadReports(true);
      }, { submit: "Delete", danger: true });
  }

  // ---------- events ----------
  function click(e) {
    const t = e.target;
    if ($("#rp")?.contains(t)) {
      const y = t.closest("[data-rp-yes]"); if (y) { decide(+y.dataset.rpYes, true); return true; }
      const no = t.closest("[data-rp-no]"); if (no) { decide(+no.dataset.rpNo, false); return true; }
      if (t.closest("[data-rp-all]")) { approveAll(); return true; }
      const bk = t.closest("[data-rp-bulk]"); if (bk) { bulkDecide(rep.pending.filter(d => sel.pend.has(d.id)), bk.dataset.rpBulk === "1"); return true; }
      const ds = t.closest("[data-rp-delsel]"); if (ds) { const k = ds.dataset.rpDelsel; removeItems(k, [...sel[k]]); return true; }
      const dl = t.closest("[data-rp-del]"); if (dl) { const [k, id] = dl.dataset.rpDel.split(":"); removeItems(k, [+id]); return true; }
      const sc = t.closest("[data-rp-scope]"); if (sc) { repScope = sc.dataset.rpScope; pref("rscope", repScope); loadReports(); return true; }
      return false;
    }
    if (!$("#tm")?.contains(t)) return false;
    const ex = t.closest("[data-tm-ex]"); if (ex) { const g = $("#tm-start [name=goal]"); g.value = ex.dataset.tmEx; g.focus(); return true; }
    const dg = t.closest("[data-tm-diag]"); if (dg) { diag = dg.dataset.tmDiag; pref("diag", diag); drawDiagram(); return true; }
    const tk = t.closest("[data-tm-task]"); if (tk) { const id = +tk.dataset.tmTask; open.has(id) ? open.delete(id) : open.add(id); drawTasks(); loadOutput(id); return true; }
    const ed = t.closest("[data-tm-edit]"); if (ed) { const x = st.tasks.find(y => y.id === +ed.dataset.tmEdit); if (x) editTask(x); return true; }
    const rd = t.closest("[data-tm-redo]"); if (rd) { const x = st.tasks.find(y => y.id === +rd.dataset.tmRedo); if (x) redoTask(x); return true; }
    if (t.closest("[data-tm-reset]")) { resetProject(); return true; }
    if (t.closest("[data-tm-cancel]")) {  // the stream shows the rest
      UI.confirm({ title: `Stop this cycle on SN${n}?`, body: "The team finishes the step it's on, then stops, and the cycle ends as cancelled. What it has done so far stays. A cancelled cycle can't be resumed.", ok: "Stop the cycle", icon: "stop",
        run: () => api(`/api/workspace/pdca/${st.cycle.id}/cancel`, { method: "POST" }).then(() => toast("The team stops after the step it's on")) });
      return true;
    }
    const us = t.closest("[data-tm-unsched]");
    if (us) {
      UI.confirm({ title: "Stop the schedule?", body: `No new cycles start on SN${n} on their own. The cycles so far stay. To repeat again, set a schedule when you start the next cycle.`, ok: "Stop the schedule", icon: "clock",
        run: () => api(`/api/workspace/pdca/${us.dataset.tmUnsched}/schedule`, { method: "DELETE" }).then(() => { toast("Schedule stopped"); load(); }) });
      return true;
    }
    return false;
  }
  function change(e) {
    const t = e.target;
    if (t.dataset?.rpSel) { const [k, id] = t.dataset.rpSel.split(":"); t.checked ? sel[k].add(+id) : sel[k].delete(+id); drawReports(); return true; }
    if (t.dataset?.rpSelall) {
      const k = t.dataset.rpSelall, all = { pend: rep.pending, rep: rep.reports, dec: rep.decided }[k].map(x => x.id);
      sel[k] = new Set(t.checked ? all : []); drawReports(); return true;
    }
    if (t.id !== "tm-pick") return false;
    pick = +e.target.value || null; open.clear(); formKey = ""; load();
    return true;
  }
  // one tooltip for every diagram mark (data-tip)
  function hover(e) {
    const tipEl = $("#tm-tip"); if (!tipEl) return;
    const m = e.target.closest?.("[data-tip]");
    if (!m || !$("#tm-diag")?.contains(m)) { tipEl.hidden = true; return; }
    const card = $("#tm-diag .tm-diag").getBoundingClientRect();
    tipEl.textContent = m.dataset.tip; tipEl.hidden = false;
    const x = Math.min(e.clientX - card.left + 12, card.width - tipEl.offsetWidth - 8), y = e.clientY - card.top + 14;
    tipEl.style.left = Math.max(8, x) + "px"; tipEl.style.top = y + "px";
  }
  return { render, reports, stop, click, change, hover };
})();
