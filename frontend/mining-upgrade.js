/* Competition teams, the Agent Upgrade Factory (mining_upgrade.py), a sub-tab of the Competition teams page (mining-work.js
   draws the page):
   - Start: every agent, the ones ticked, or one; the sprint's minutes (30 by default, a hard deadline), how many at once, the
     Evaluator's model, and an estimate of calls, tokens and time.
   - While it runs: the countdown, the five phases on the clock with the agents in each, live counts and the token meter.
   - The squads, each agent with its status, phase and Agent Level Score before → after on the same held-out exam.
   - An agent's upgrade: the verdict and the seven dimensions, the squad lead's diagnosis, the exam tasks with both answers and
     the Evaluator's note, the practice round, the candidate's instructions beside the current ones and its package; promote
     (only a measured improvement, bound to its hash) or reject; its instruction versions, any of which can be restored.
   - Earlier sprints. */
const MiningUpgrade = (() => {
  const W = "/api/mining/work";
  let d = null, dWid = null, dAt = 0, loading = false, failed = "", wired = false, pick = new Set(), poll = null, clock = null;
  let form = { minutes: 30, parallel: 6, evaluator: "auto" }, models = null, rowId = null, row = null;
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const short = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n || 0, 0);
  const when = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const mmss = s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const VERDICT = { better: ["Better", "ok", "up"], same: ["No better", "none", "flat"], worse: ["Worse", "bad", "down"] };
  // D-031: a screened candidate's proposal in the Evolution Lab, in the words that page uses
  const GATE = { proposed: "waiting for its trial", testing: "on trial", verified: "trial passed: waiting for a person to promote it", not_better: "trial didn't show it is better",
    failed: "trial failed", promoted: "promoted", rejected: "rejected", rolled_back: "promoted, then rolled back", gone: "no longer there" };
  const STATUS = { waiting: ["Waiting", "none"], working: ["Working", "info"], cut: ["Cut by the clock", "warn"], failed: ["Failed", "bad"] };
  const running = () => d?.sprint?.status === "running";

  function need(v) {
    const wid = v.comp.id;
    if (dWid !== wid) { d = null; dWid = wid; dAt = 0; failed = ""; pick = new Set(); }
    if (loading || Date.now() - dAt < (running() ? 2500 : 8000)) return;
    load(wid);
  }
  function load(wid) {
    loading = true;
    return api(`${W}/comps/${wid}/upgrade`).then(x => { if (dWid === wid) { d = x; failed = ""; } })
      .catch(e => { failed = e.message; }).finally(() => { dAt = Date.now(); loading = false; tick(); if (dWid === wid && !holding() && shown()) MiningWork.rerender(); });
  }
  const shown = () => !!document.querySelector(".aup");
  // the start form keeps what's typed: no re-render while it has focus
  const holding = () => !!document.activeElement?.closest?.(".aup-start");
  function tick() {  // poll while a sprint runs; the clock updates in place every second
    clearInterval(poll); clearInterval(clock);
    if (!running()) return;
    poll = setInterval(() => { if (!shown()) return clearInterval(poll); if (dWid != null && !loading) load(dWid); }, 3000);
    clock = setInterval(() => {
      if (!shown()) return clearInterval(clock);
      const s = d?.sprint; if (!s) return;
      const now = Date.now() / 1000, el = document.querySelector("[data-aupclock]"), mk = document.querySelector(".aup-now");
      if (el) el.textContent = mmss(s.deadline - now);
      if (mk) mk.style.setProperty("--x", `${Math.min(100, (now - s.started) / (s.deadline - s.started) * 100).toFixed(2)}%`);
    }, 1000);
  }

  // ---------- the start form ----------
  function estimate(n) {
    const r = d.rules, groups = new Set(d.team.filter(a => !pick.size || pick.has(a.id)).map(a => a.squad)).size || 1;
    const calls = n * r.calls_per_agent + groups * 2, tokens = calls * r.call_tokens;
    const mins = Math.ceil((r.agent_secs * Math.ceil(n / Math.max(1, form.parallel)) + 60) / 60);
    return { calls, tokens, mins };
  }
  function start() {
    const n = pick.size || d.team.length, e = estimate(n), b = d.budget, left = b.budget ? Math.max(0, b.budget - b.day) : null;
    const tight = e.mins > form.minutes, poor = left != null && e.tokens > left;
    const opts = [["auto", `The team's model${d.model ? ` (${d.model.split(":").pop()})` : ""}`], ...(models || []).map(m => [m.id, m.label || m.id])];
    return `<section class="mh-card aup-card aup-start"><div class="aup-head"><div>
        <h3>${icon("sparkle")}Agent Upgrade Factory</h3>
        <p class="faint small">Each agent gets its own upgrade: a diagnosis by its squad lead, a candidate written from it, practice, then the same held-out exam for the old and the new version, scored blind by an independent Evaluator. The exam is scored by a model, so it screens candidates: one that did better can be sent to trial in the Evolution Lab, and only a trial on the team's benchmark promotes it. Nothing changes in the team here.</p></div></div>
      <form class="aup-form" data-aupform>
        <div class="aup-who" role="group" aria-label="Which agents">
          <span class="aup-lbl">Agents</span>
          <b>${pick.size ? `${plural(pick.size, "agent")} ticked` : `All ${plural(d.team.length, "active agent")}`}</b>
          ${pick.size ? `<button type="button" class="linkbtn" data-aup="clear">Untick all</button>` : `<span class="faint small">Tick agents below to upgrade only those.</span>`}</div>
        <label><span class="aup-lbl">Minutes</span><input type="number" name="minutes" min="${d.rules.minutes[0]}" max="${d.rules.minutes[1]}" value="${form.minutes}" required></label>
        <label><span class="aup-lbl">At once</span><input type="number" name="parallel" min="1" max="${d.rules.max_parallel}" value="${form.parallel}" required></label>
        <label class="aup-eval"><span class="aup-lbl">Evaluator</span><select name="evaluator">${opts.map(([k, l]) => `<option value="${esc(k)}" ${k === form.evaluator ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
        <button type="submit" class="btn primary" ${!d.model || running() ? "disabled" : ""}>${icon("play")}${pick.size ? `Upgrade ${plural(pick.size, "agent")}` : "Upgrade all agents"}</button></form>
      <p class="aup-est small ${tight || poor ? "aup-warn" : "faint"}">${icon(tight || poor ? "alert" : "info")}About ${fmtNum(e.calls, 0)} model calls and ${short(e.tokens)} tokens; at ${form.parallel} at once that needs about ${e.mins} min.
        ${tight ? ` The clock is shorter: the weakest agents go first and the rest are recorded as cut.` : ""}${poor ? ` Only ${short(left)} tokens are left in today's budget: the sprint stops there.` : ""}
        ${form.evaluator === "auto" ? ` The Evaluator runs on the team's model; pick another for a more independent score.` : ""}</p>
      ${!d.model ? `<p class="mh-err small">${icon("info")}No model is connected: an administrator connects one in Agents → Models.</p>` : ""}</section>`;
  }

  // ---------- the running sprint ----------
  function clockCard(s) {
    const now = Date.now() / 1000, total = s.deadline - s.started, live = s.status === "running";
    let at = 0;
    const segs = d.phases.map(p => { const sum = d.phases.reduce((n, x) => n + x.share, 0), w = p.share / sum * 100; const seg = { ...p, x: at, w }; at += w; return seg; });
    const inPhase = k => s.agents.filter(a => ["working", "waiting"].includes(a.status) && a.phase === k).length;
    const t = s.tally, used = s.token_cap ? Math.min(1, s.tokens / s.token_cap) : 0;
    const st = { running: ["Running", "info"], done: ["Finished", "ok"], stopped: ["Stopped", "warn"], failed: ["Failed", "bad"] }[s.status] || [s.status, "none"];
    return `<section class="mh-card aup-card aup-clock"><div class="aup-head"><div>
        <h3>${icon("clock")}Sprint ${s.id} <span class="hq-chip t-${st[1]}">${st[0]}</span></h3>
        <p class="faint small">${esc(s.by_user || "")} started it ${when(s.started)} for ${s.minutes} min${s.finished ? ` · ended ${when(s.finished)}` : ""}${s.note ? ` · ${esc(s.note)}` : ""}</p></div>
        ${live ? `<div class="aup-timer"><span class="aup-lbl">Left</span><b data-aupclock>${mmss(s.deadline - now)}</b><button type="button" class="btn sm mw-danger" data-aup="stop">${icon("ban")}Stop</button></div>` : ""}</div>
      <div class="aup-phases" role="list" aria-label="The five phases on the clock">
        ${segs.map((p, i) => `<div class="aup-ph" role="listitem" style="--x:${p.x.toFixed(2)}%;--w:${p.w.toFixed(2)}%"><span class="aup-ph-n">${i + 1}</span><b>${esc(p.label)}</b>
          <span class="faint small">${mmss(total * p.x / 100)}–${mmss(total * (p.x + p.w) / 100)}${live && inPhase(p.key) ? ` · ${inPhase(p.key)} here` : ""}</span></div>`).join("")}
        ${live ? `<i class="aup-now" style="--x:${Math.min(100, (now - s.started) / total * 100).toFixed(2)}%" aria-hidden="true"></i>` : ""}</div>
      <div class="aup-kpis">${[["better", "Better", "up"], ["same", "No better", "flat"], ["worse", "Worse", "down"], ["cut", "Cut", "clock"], ["failed", "Failed", "alert"], ["screened", "Sent to trial", "zap"], ["promoted", "Promoted", "check"]]
        .map(([k, l, ic]) => `<span class="aup-kpi k-${k}">${icon(ic)}<b>${t[k] || 0}</b><em>${l}</em></span>`).join("")}
        <span class="aup-kpi aup-tok"><span class="aup-lbl">Tokens</span><b>${short(s.tokens)}</b><em>of ${short(s.token_cap)} · ${fmtNum(s.calls, 0)} calls</em>
          <span class="aup-meter"><i style="--w:${(used * 100).toFixed(1)}%" class="${used >= 1 ? "full" : ""}"></i></span></span></div>
      ${s.expired ? `<p class="faint small">${icon("info")}These results are older than ${d.rules.approval_days} days: they can't be sent to trial any more. Run a new sprint.</p>` : ""}</section>`;
  }

  // ---------- squads and agents ----------
  function scoreCell(a) {
    if (a.base_score == null) return `<span class="faint">–</span>`;
    const dl = Math.round((a.cand_score - a.base_score) * 10) / 10;
    return `<span class="aup-sc"><b>${fmtNum(a.base_score, 0)}</b>${icon("right")}<b>${fmtNum(a.cand_score, 0)}</b><em class="${dl > 0 ? "up" : dl < 0 ? "down" : ""}">${dl > 0 ? "+" : dl < 0 ? "−" : "±"}${fmtNum(Math.abs(dl), Math.abs(dl) % 1 ? 1 : 0)}</em></span>`;
  }
  function chip(a) {
    if (a.decision === "promoted") return `<span class="hq-chip t-ok">${icon("check")}Promoted</span>`;
    if (a.decision === "screened") return `<span class="hq-chip t-info">${icon("zap")}${a.gate?.status === "promoted" ? "Promoted after its trial" : "Sent to trial"}</span>`;
    if (a.decision === "rejected") return `<span class="hq-chip t-none">Rejected</span>`;
    if (a.verdict) { const [l, tone] = VERDICT[a.verdict]; return `<span class="hq-chip t-${tone}">${l}</span>`; }
    const [l, tone] = STATUS[a.status] || [a.status, "none"];
    const ph = d.phases.find(p => p.key === a.phase);
    return `<span class="hq-chip t-${tone}" ${a.error ? `title="${esc(a.error)}"` : ""}>${a.status === "working" && ph ? `${esc(ph.label)}…` : l}</span>`;
  }
  function squads() {
    const s = d.sprint, live = running(), rows = s ? Object.fromEntries(s.agents.map(a => [a.agent_id, a])) : {};
    const by = new Map();
    for (const a of d.team) { const k = a.squad || ""; if (!by.has(k)) by.set(k, []); by.get(k).push(a); }
    const card = ([sq, xs]) => {
      const lead = xs.find(a => a.head) || xs.find(a => a.lead);
      const rs = xs.map(a => rows[a.id]).filter(Boolean), better = rs.filter(r => r.verdict === "better").length;
      return `<section class="mh-card aup-card aup-squad"><h3>${icon("users")}${esc(d.squads[sq] || (sq ? sq : "Team"))}<span class="hq-n">${xs.length}</span>
          ${rs.length ? `<span class="faint small aup-sq-sum">${lead ? `${esc(lead.name)} reports: ` : ""}${better} of ${rs.length} better</span>` : ""}</h3>
        <ul class="aup-rows">${xs.map(a => { const r = rows[a.id];
          return `<li class="${r ? "has" : ""}">
            ${live ? "" : `<label class="aup-tick" title="Tick to upgrade only the ticked agents"><input type="checkbox" data-auppick="${a.id}" ${pick.has(a.id) ? "checked" : ""} aria-label="Pick ${esc(a.name)}"></label>`}
            <button type="button" class="aup-who-b" ${r ? `data-aupopen="${r.id}"` : `data-aupone="${a.id}"`} ${!r && (live || !d.model) ? "disabled" : ""}>
              <span class="aup-nm"><b>${esc(a.name)}</b>${a.head ? `<em class="faint">lead</em>` : a.lead ? `<em class="faint">director</em>` : ""}<span class="faint small">${esc(a.title)}</span></span>
              ${r ? `${chip(r)}${scoreCell(r)}` : `<span class="faint small">${a.score != null ? `Level ${fmtNum(a.score, 0)} · ` : ""}${live ? "Not in this sprint" : "Upgrade this one"}</span>`}</button></li>`; }).join("")}</ul></section>`;
    };
    return `<div class="aup-squads">${[...by.entries()].map(card).join("")}</div>`;
  }
  function history() {
    const h = d.history.slice(d.sprint ? 1 : 0);
    if (!h.length) return "";
    return `<section class="mh-card aup-card"><h3>${icon("clock")}Earlier sprints</h3><ul class="aup-hist">${h.map(s => { const t = s.tally;
      return `<li><span><b>Sprint ${s.id}</b> <span class="faint small">${when(s.started)} · ${s.minutes} min · ${esc(s.by_user || "")}</span></span>
        <span class="small">${t.better || 0} better · ${t.same || 0} no better · ${t.worse || 0} worse · ${t.cut || 0} cut${t.screened ? ` · ${t.screened} sent to trial` : ""}${t.promoted ? ` · ${t.promoted} promoted` : ""}</span><span class="faint small">${short(s.tokens)} tokens</span></li>`; }).join("")}</ul></section>`;
  }
  function rules() {
    return `<details class="mh-card aup-card aup-rules"><summary>${icon("info")}How it's measured</summary>
      <p class="small">The Agent Level Score is 0–100: ${d.dims.map(x => `${esc(x.label)} ${x.weight}`).join(", ")}, each scored 0–10 by the Evaluator on every exam task.
        Every agent gets ${d.rules.practice} practice and ${d.rules.exam} exam tasks from an Examiner who isn't on the team; the exam is held out, so the upgrade never sees it.
        Better means ${d.rules.margin} points or more and no dimension down by more than ${d.rules.drop}; a dimension down by more, or a lower score, is worse.
        A candidate's instructions hold at most ${fmtNum(d.rules.max_instr, 0)} characters: it's a better prompt, not a longer one. Models, tools, permissions and credentials never change.
        A promotion is bound to the candidate's hash, works once, and only within ${d.rules.approval_days} days; every earlier version can be restored.</p></details>`;
  }

  function view(v) {
    need(v);
    if (!d) return failed ? `<p class="mh-err">${icon("alert")}${esc(failed)}</p>` : Loading.line("Opening the Upgrade Factory…");
    if (models === null) { models = []; api("/api/agents/models").then(r => { models = (r.providers || []).flatMap(p => p.models || []).filter(m => m.id).slice(0, 80); if (shown() && !holding()) MiningWork.rerender(); }).catch(() => {}); }
    if (!d.team.length) return `<div class="aup"><section class="mh-card aup-card"><p class="faint">${icon("users")}The team has no active agents to upgrade.</p></section></div>`;
    return `<div class="aup">${running() ? "" : start()}${d.sprint ? clockCard(d.sprint) : ""}${squads()}${history()}${rules()}</div>`;
  }

  // ---------- one agent's upgrade ----------
  function dlg() {
    let el = document.getElementById("aup-dlg");
    if (!el) {
      el = document.createElement("dialog"); el.id = "aup-dlg"; el.className = "modal mw-dlg wide aup-dlg"; document.body.append(el);
      el.addEventListener("click", e => { if (e.target === el || e.target.closest("[data-close]")) return el.close(); const b = e.target.closest("[data-aupd]"); if (b) act(b); });
      el.addEventListener("close", () => { rowId = null; row = null; });
    }
    return el;
  }
  async function openRow(id) {
    const el = dlg(); rowId = id; row = null;
    el.innerHTML = `<div class="hq-dlg-in">${closeBtn}${Loading.line("Reading the upgrade…")}</div>`;
    if (!el.open) el.showModal();
    try { const r = await api(`${W}/upgrade/agents/${id}`); if (rowId !== id) return; row = r; drawRow(); }
    catch (e) { if (rowId === id) el.innerHTML = `<div class="hq-dlg-in">${closeBtn}<div class="empty">${esc(e.message)}</div></div>`; }
  }
  const closeBtn = `<button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>`;
  const list = (xs, cls = "") => xs?.length ? `<ul class="aup-ul ${cls}">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="faint small">None.</p>`;
  function dims(r) {
    if (!r.base_dims || !Object.keys(r.base_dims).length) return "";
    return `<table class="aup-dims"><thead><tr><th>Dimension</th><th>Weight</th><th>Before</th><th>After</th><th></th></tr></thead><tbody>${d.dims.map(x => {
      const b = r.base_dims[x.key] ?? 0, c = r.cand_dims[x.key] ?? 0, dl = c - b, drop = (r.drops || []).includes(x.key);
      return `<tr class="${drop ? "drop" : ""}"><td>${esc(x.label)}</td><td class="num">${x.weight}</td><td class="num">${fmtNum(b, 1)}</td><td class="num">${fmtNum(c, 1)}</td>
        <td><span class="aup-bar"><i class="b" style="--w:${b * 10}%"></i><i class="c ${dl < 0 ? "down" : ""}" style="--w:${c * 10}%"></i></span></td></tr>`; }).join("")}</tbody></table>`;
  }
  function drawRow() {
    const el = dlg(), r = row; if (!el.open || !r) return;
    const s = d?.sprint, v = r.verdict ? VERDICT[r.verdict] : null, dg = r.diagnosis || {}, pk = r.package || {}, t = r.tasks || {};
    const exam = (t.exam || []).map((x, i) => { const p = r.cand?.pair?.[i], b = r.base?.exam?.[i], c = r.cand?.exam?.[i];
      const tot = o => o ? Math.round(d.dims.reduce((n, k) => n + k.weight * (o[k.key] || 0) / 10, 0)) : null;
      return `<details class="aup-task"><summary><b>Exam ${i + 1}</b> <span class="small">${esc(x.task.slice(0, 140))}${x.task.length > 140 ? "…" : ""}</span>
          ${p ? `<span class="aup-sc small"><b>${tot(p.old)}</b>${icon("right")}<b>${tot(p.new)}</b></span>` : ""}</summary>
        <p class="small">${esc(x.task)}</p><p class="faint small"><b>Rubric:</b> ${esc(x.rubric)}</p>
        <div class="aup-2"><div><h5>Before</h5><pre class="aup-pre">${esc(b || "(no answer)")}</pre></div><div><h5>Candidate</h5><pre class="aup-pre">${esc(c || "(not reached)")}</pre></div></div>
        ${p?.note ? `<p class="small">${icon("chat")}<b>Evaluator:</b> ${esc(p.note)}</p>` : ""}</details>`; }).join("");
    const pr = r.practice || {};
    const canPromote = r.verdict === "better" && !r.decision && !r.expired && !r.stale && s?.status !== "running";
    el.innerHTML = `<div class="hq-dlg-in aup-d">${closeBtn}
      <div class="aup-d-head"><div><div class="mw-kicker">${icon("sparkle")}Upgrade · sprint ${s?.id ?? ""}</div><h2>${esc(r.name)}</h2><p class="faint small">${esc(r.title)}${r.model ? ` · ${esc(r.model.split(":").pop())}` : ""} · ${short(r.tokens)} tokens</p></div>
        <div class="aup-d-v">${v ? `<span class="hq-chip t-${v[1]}">${icon(v[2])}${v[0]}</span>` : chip(r)}${scoreCell(r)}</div></div>
      ${r.error ? `<p class="mh-err small">${icon("info")}${esc(r.error)}</p>` : ""}
      ${r.stale && r.verdict === "better" && !r.decision ? `<p class="mh-err small">${icon("alert")}Its instructions changed since the sprint measured them, so this candidate can't be sent to trial. Run the upgrade again.</p>` : ""}
      ${dims(r)}
      <div class="aup-2">
        <section><h4>${icon("target")}The squad lead's diagnosis</h4>${(dg.weaknesses || []).length ? `<ul class="aup-ul">${dg.weaknesses.map(w => `<li><b>${esc(d.dims.find(x => x.key === w.dimension)?.label || w.dimension)}:</b> ${esc(w.issue)}${w.evidence ? ` <span class="faint">(${esc(w.evidence)})</span>` : ""}</li>`).join("")}</ul>` : `<p class="faint small">No weaknesses named.</p>`}
          ${(dg.strengths || []).length ? `<h5>Strengths</h5>${list(dg.strengths)}` : ""}${(dg.overlaps || []).length ? `<h5>Overlaps in the squad</h5>${list(dg.overlaps)}` : ""}</section>
        <section><h4>${icon("wrench")}What changed</h4>${list(pk.changes)}${(pk.removed || []).length ? `<h5>Removed</h5>${list(pk.removed)}` : ""}
          ${pr.old != null ? `<p class="small"><b>Practice:</b> ${fmtNum(pr.old, 0)} → ${fmtNum(pr.new, 0)}</p>` : ""}${(r.notes || []).map(n => `<p class="faint small">${esc(n)}</p>`).join("")}
          ${pk.model_advice ? `<p class="small">${icon("bulb")}<b>Model advice</b> (not applied): ${esc(pk.model_advice)}</p>` : ""}</section></div>
      <h4>${icon("book")}The held-out exam</h4>${exam || `<p class="faint small">Not reached.</p>`}
      <div class="aup-2"><section><h4>Current instructions</h4><pre class="aup-pre">${esc(r.current || "(none beyond the job)")}</pre></section>
        <section><h4>Candidate instructions <span class="faint small">${fmtNum((r.candidate || "").length, 0)} characters</span></h4><pre class="aup-pre">${esc(r.candidate || "(not written)")}</pre></section></div>
      ${pk.role ? `<details class="aup-task"><summary><b>The upgrade package</b></summary><p class="small"><b>Role:</b> ${esc(pk.role)}</p><h5>Responsibilities</h5>${list(pk.responsibilities)}<h5>Knowledge</h5>${list(pk.knowledge)}
        <h5>Tools</h5><p class="small">${esc(pk.tools || "")}</p><h5>Good work</h5>${list(pk.good_examples)}<h5>Failure patterns</h5>${list(pk.failure_patterns)}<h5>Done when</h5>${list(pk.done_criteria)}</details>` : ""}
      <div class="aup-vers" data-aupvers><h4>${icon("clock")}Instruction versions</h4><p class="faint small">${Loading.line("Reading versions…")}</p></div>
      ${r.decision === "screened" ? `<p class="small aup-gate">${icon("zap")}Sent to trial ${when(r.decided)} as <button type="button" class="linkbtn" data-aupd="lab">proposal #${r.gate?.proposal ?? "?"}</button> in the Evolution Lab (${esc(GATE[r.gate?.status] || r.gate?.status || "unknown")}). ${r.gate?.status === "promoted" ? "Its trial showed it is better and it was promoted there." : r.experiments === false ? "Its trial can't start yet: the Owner hasn't turned experiments on for this team." : "It is promoted only if a trial on the team's benchmark shows it is better."}</p>` : ""}
      <div class="row aup-d-act">${r.decision ? `<span class="faint small">${r.decision === "promoted" ? "Promoted" : r.decision === "screened" ? "Sent to trial" : "Rejected"} ${when(r.decided)}.</span>` :
        `${canPromote ? `<button type="button" class="btn primary" data-aupd="promote">${icon("zap")}Send to trial</button>` : r.verdict === "better" ? "" : `<span class="faint small">Only a candidate that did better on the exam can be sent to trial.</span>`}
         ${r.verdict ? `<button type="button" class="btn" data-aupd="reject">Reject</button>` : ""}`}</div></div>`;
    versions(r.agent_id);
  }
  async function versions(aid) {
    const box = document.querySelector("#aup-dlg [data-aupvers]"); if (!box || !dWid) return;
    try {
      const r = await api(`${W}/comps/${dWid}/upgrade/versions/${aid}`);
      const cur = row?.current ?? "";
      box.innerHTML = `<h4>${icon("clock")}Instruction versions</h4>${r.versions.length ? `<ul class="aup-hist">${r.versions.map(x => `<li><span><b>v${x.version}</b> <span class="faint small">${esc(x.source)} · ${when(x.ts)}${x.by_user ? ` · ${esc(x.by_user)}` : ""}${x.score != null ? ` · level ${fmtNum(x.score, 0)}` : ""}</span></span>
          <span class="small aup-clip">${esc((x.instructions || "(none)").slice(0, 120))}</span>${(x.instructions || "") === cur ? `<span class="hq-chip t-ok">In use</span>` : `<button type="button" class="btn sm" data-aupd="restore" data-vid="${x.id}">${icon("undo")}Restore</button>`}</li>`).join("")}</ul>`
        : `<p class="faint small">No versions yet: the first promotion keeps today's instructions as v1.</p>`}`;
    } catch (e) { box.innerHTML = `<p class="mh-err small">${esc(e.message)}</p>`; }
  }
  async function act(b) {
    const r = row; if (!r) return;
    const k = b.dataset.aupd;
    const run = async (fn, msg) => { b.disabled = true; try { await fn(); Auth.toast(msg); dAt = 0; load(dWid); MiningWork.reload(); } catch (e) { err(e); } finally { if (b.isConnected) b.disabled = false; } };
    if (k === "lab") { document.getElementById("aup-dlg")?.close(); return setView("evolution"); }
    if (k === "promote") return UI.confirm({ title: `Send ${esc(r.name)}'s candidate to trial?`, ok: "Send to trial", icon: "zap", danger: false,
      body: `The candidate goes to the Evolution Lab as a proposal (level ${fmtNum(r.base_score, 0)} → ${fmtNum(r.cand_score, 0)} on the held-out exam). The exam is scored by a model, so it doesn't promote: a trial on the team's benchmark does. Nothing changes in the team now.`,
      run: () => run(async () => { row = await api(`${W}/upgrade/agents/${r.id}/decide`, { method: "POST", body: { action: "promote", hash: r.hash } }); drawRow(); }, "Sent to trial") }).catch(err);
    if (k === "reject") return run(async () => { row = await api(`${W}/upgrade/agents/${r.id}/decide`, { method: "POST", body: { action: "reject" } }); drawRow(); }, "Rejected");
    if (k === "restore") return UI.confirm({ title: "Restore this version?", ok: "Restore", icon: "undo", danger: false, body: `${esc(r.name)}'s instructions go back to it; the ones in use now are kept as a version too.`,
      run: () => run(async () => { await api(`${W}/upgrade/versions/${b.dataset.vid}/restore`, { method: "POST" }); row = await api(`${W}/upgrade/agents/${r.id}`); drawRow(); }, "Restored") }).catch(err);
  }

  // ---------- actions ----------
  async function begin(agents, minutes) {
    const wid = dWid;
    try {
      d = await api(`${W}/comps/${wid}/upgrade`, { method: "POST", body: { agents, minutes, parallel: form.parallel, evaluator: form.evaluator } });
      dAt = Date.now(); pick = new Set(); Auth.toast("The upgrade sprint started"); tick(); MiningWork.rerender();
    } catch (e) { err(e); }
  }
  function onClick(e) {
    const t = e.target;
    const o = t.closest("[data-aupopen]"); if (o) return openRow(+o.dataset.aupopen);
    const one = t.closest("[data-aupone]");
    if (one) { const a = d.team.find(x => x.id === +one.dataset.aupone);
      return UI.confirm({ title: `Upgrade ${esc(a?.name || "this agent")}?`, ok: "Start", icon: "play", danger: false, body: "A quick upgrade of one agent: 10 minutes on the clock, the same diagnosis, practice and held-out exam.",
        run: () => begin([+one.dataset.aupone], 10) }).catch(err); }
    const b = t.closest("[data-aup]"); if (!b) return;
    if (b.dataset.aup === "clear") { pick = new Set(); return MiningWork.rerender(); }
    if (b.dataset.aup === "stop") return UI.confirm({ title: "Stop the sprint?", ok: "Stop", icon: "ban", body: "Agents that finished keep their results; the rest are recorded as cut.",
      run: async () => { try { d = await api(`${W}/upgrade/${d.sprint.id}/stop`, { method: "POST" }); tick(); MiningWork.rerender(); } catch (x) { err(x); } } }).catch(err);
  }
  function wire(el) {
    if (wired) return; wired = true;
    el.addEventListener("click", e => { if (e.target.closest(".aup")) onClick(e); });
    el.addEventListener("change", e => {
      const p = e.target.closest("[data-auppick]");
      if (p) { p.checked ? pick.add(+p.dataset.auppick) : pick.delete(+p.dataset.auppick); return MiningWork.rerender(); }
      const f = e.target.closest("[data-aupform]");
      if (f) { form = { minutes: +f.elements.minutes.value || 30, parallel: +f.elements.parallel.value || 1, evaluator: f.elements.evaluator.value }; }
    });
    el.addEventListener("focusout", e => { if (e.target.closest?.("[data-aupform]")) setTimeout(() => { if (!holding()) MiningWork.rerender(); }, 0); });
    el.addEventListener("submit", e => {
      const f = e.target.closest("[data-aupform]"); if (!f) return;
      e.preventDefault();
      form = { minutes: +f.elements.minutes.value || 30, parallel: +f.elements.parallel.value || 1, evaluator: f.elements.evaluator.value };
      const n = pick.size || d.team.length;
      UI.confirm({ title: pick.size ? `Upgrade ${plural(n, "agent")}?` : "Upgrade every agent?", ok: "Start", icon: "play", danger: false,
        body: `${form.minutes} minutes on the clock, ${form.parallel} at once. Agents are measured on candidates only: nothing in the team changes: a candidate that does better can be sent to trial afterwards.`,
        run: () => begin([...pick], form.minutes) }).catch(err);
    });
  }
  const fresh = () => { dAt = 0; };
  return { view, wire, holding, fresh };
})();
