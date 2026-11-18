/* Mission Operations (mission_ops.py: GET /api/control/ops, /ops/missions/{ref}, /ops/agents/{key}, /ops/tasks/{ref}/graph;
   PUT/DELETE /ops/missions/{ref}/criteria). The first thing on Control Hub → Overview (control.js secOverview). Prefix ctlo-.
   It answers five questions before anything else: what are we trying to achieve, what is happening, are we progressing, what
   prevents success, what happens next.
   - section(): competitions (objective, official progress or UNKNOWN with the reason, verified objective progress, work
     progress, blocker, next action and its owner), the activity in one nine-state model, the one decision queue; then, folded,
     run accountability, budgets and their reconciliation, the evolution registry and the G5 readiness rows.
   - Dialogs: a mission (criteria and their weights, the required sequence, five performance dimensions, strategy portfolio,
     budget reconciliation), an agent (derived status), a task's own graph.
   It renders from its last answer and refreshes in the background, like control-exec.js. */
const CtlOps = (() => {
  const B = "/api/control/ops";
  let data = null, at = 0, busy = false, fold = null, allQ = false;
  try { fold = localStorage.getItem("ctlo.fold") || null; } catch { /* storage off */ }
  const TONE = { PLANNED: "muted", READY: "new", RUNNING: "clear", REVIEW: "caution", VERIFIED: "clear", BLOCKED: "caution", FAILED: "scam", PAUSED: "muted", CANCELLED: "muted", COMPLETED: "new", DROPPED: "muted" };
  const HEALTH = { met: ["clear", "Objective met"], on_track: ["new", "Progressing"], unmeasurable: ["caution", "Not measurable yet"], blocked: ["scam", "Blocked"], paused: ["muted", "Paused"] };
  const QK = { infra: ["server", "Infrastructure"], human: ["hand", "Your decision"], regression: ["alert", "Regression"], budget: ["coins", "Budget"], promotion: ["zap", "Promotion"], milestone: ["flag", "Milestone"], verify: ["check", "Person's check"] };
  const RD = { pass: ["clear", "Pass"], partial: ["caution", "Partial"], fail: ["scam", "Fail"], unknown: ["muted", "No evidence yet"] };
  const badge = (tone, text, title = "") => `<span class="badge ${tone}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</span>`;
  const tok = n => n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(n);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const own = o => o === "you" ? `<b class="ctlo-you">You</b>` : esc(o ? o[0].toUpperCase() + o.slice(1) : "AXoR");
  const bar = (pct, cls = "") => `<span class="ctlo-bar ${cls}" role="img" aria-label="${pct == null ? "not measured" : pct + " percent"}"><i style="width:${Math.max(0, Math.min(100, pct || 0))}%"></i></span>`;
  const go = v => { if (typeof setView === "function" && v) setView(v); };

  function load(fresh) {
    if (busy) return;
    busy = true;
    api(`${B}${fresh ? "?fresh=1" : ""}`).then(d => { data = d; }).catch(e => { data = { error: e.message }; })
      .finally(() => { busy = false; at = Date.now(); redraw(); });
  }
  function redraw() { const el = document.getElementById("ctlo-root"); if (el) el.innerHTML = body(); if (el?.querySelector("[data-ctlo-unm]")) loadUnm(); }
  // D-025: runs whose tokens are unknown (Codex reported none). Under a stopping limit they hold the work until a person records an estimate.
  async function loadUnm() {
    const el = document.querySelector("[data-ctlo-unm]"); if (!el) return;
    let d; try { d = await api("/api/g5/unmetered"); } catch (e) { el.innerHTML = `<h4>Unmetered runs</h4><p class="faint small">${esc(e.message)}</p>`; return; }
    el.innerHTML = `<h4>Unmetered runs <small class="faint">${d.runs.length}</small></h4>
      <p class="faint small">Their token use is unknown: never counted as zero. Where a hard limit covers them, work in that scope waits until you record an estimate.</p>
      ${d.runs.length ? `<ul class="ctlo-unm-list">${d.runs.map(r => `<li><b>#${r.id}</b> ${esc(r.title || r.kind)} <span class="faint small">${esc(r.model || "")} · ${esc(r.system)} · ${esc(r.ref || "")} · ${r.tokens} counted</span>
        <span class="row"><input type="number" min="${r.floor || 1}" step="1000" placeholder="at least ${(r.floor || 0).toLocaleString()} tokens" data-ctlo-estin="${r.id}" aria-label="Estimated tokens for run ${r.id}"><button type="button" class="btn sm" data-ctlo-est="${r.id}">Record estimate</button></span></li>`).join("")}</ul>` : `<p class="faint small">None.</p>`}`;
  }
  function section() {
    if (!busy && (!data || Date.now() - at > 20000)) load();
    return `<section id="ctlo-root" class="ctlo" aria-labelledby="ctlo-h">${body()}</section>`;
  }
  const head = extra => `<div class="ctlo-head"><div><h2 id="ctlo-h">${icon("target")}Mission operations</h2>
      <p class="faint small">What we are trying to achieve, whether we are achieving it, what prevents it, what AXoR does about it, and what needs you.</p></div>${extra || ""}</div>`;

  function body() {
    if (!data) return `${head()}<p class="faint">${icon("cycle")}Loading…</p>`;
    if (data.error) return `${head()}<p class="ctl-warn">${icon("alert")}${esc(data.error)}</p>`;
    const k = data.kpis, r = data.readiness;
    const kpi = (l, v, sub, tone = "") => `<div class="ctlo-kpi ${tone}"><small>${esc(l)}</small><b>${v}</b><em>${esc(sub)}</em></div>`;
    return `${head(`<button type="button" class="iconbtn sm" data-ctlo-refresh title="Refresh" aria-label="Refresh mission operations">${icon("reset")}</button>`)}
      <div class="ctlo-kpis">${kpi("Active competitions", k.competitions, k.custom ? `${plural(k.custom, "custom mission")} open` : "no custom mission open")}
        ${kpi("Verified objectives", k.objectives_verified, "independently verified, not just finished", k.objectives_verified ? "good" : "")}
        ${kpi("Tasks requiring attention", k.attention, "blocked or failed", k.attention ? "warn" : "")}
        ${kpi("Decisions waiting", k.decisions, k.yours ? `${k.yours} for you` : "none for you", k.yours ? "warn" : "")}
        ${kpi("G5 readiness", `${r.pass}/${r.total}`, r.verdict, r.pass === r.total ? "good" : "")}</div>
      ${data.competitions.length ? `<div class="ctlo-comps">${data.competitions.map(compCard).join("")}</div>` : `<p class="faint ctlo-empty">No active competition. Start a Bittensor mission to give the company a measurable objective.</p>`}
      ${data.custom.length ? `<div class="ctlo-custom"><h3>Custom missions</h3><ul>${data.custom.map(customRow).join("")}</ul></div>` : ""}
      ${gate()}
      <div class="ctlo-two">${activity()}${queue()}</div>
      ${folds()}`;
  }

  // ---------- readiness gate (G5-2): each mission's state, what holds its tasks and who fixes it, the risk register ----------
  const GS = { PASS: ["good", "Ready"], CONDITIONAL: ["warn", "Conditional"], BLOCKED: ["bad", "Blocked"] };
  let riskOpen = false;  // the register's fold stays as the viewer left it across redraws
  document.addEventListener("toggle", e => { if (e.target.matches?.(".ctlo-gr")) riskOpen = e.target.open; }, true);
  // G5-3 R3.4: the register has more sources than readiness; the filter keeps its choice across redraws
  const RSRC = { readiness: "Readiness", diagnosis: "Failed runs", sandbox: "Sandbox", hq: "Agent HQ", budget: "Budget limits", ops: "Mining Operations", campaign: "Campaign alerts" };
  let riskSrc = "";
  document.addEventListener("change", e => {
    if (!e.target.matches?.(".ctlo-rsrc")) return;
    riskSrc = e.target.value;
    e.target.closest(".ctlo-gr")?.querySelectorAll("tr[data-src]").forEach(tr => { tr.hidden = !!riskSrc && tr.dataset.src !== riskSrc; });
  }, true);
  function gate() {
    const g = data.gate;
    if (!g) return "";
    if (g.error) return `<p class="ctl-warn">${icon("alert")}Readiness: ${esc(g.error)}</p>`;
    if (!g.missions.length && !g.risks.length) return "";
    const need = i => `${esc(i.cap)}${i.value ? ":" + esc(i.value) : ""}`;
    const when = i => !i.checked ? "not checked yet" : `checked ${new Date(i.checked * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}${i.stale ? ", stale" : ""}`;
    const mis = m => `<li><div class="ctlo-gh">${badge(...GS[m.state])}<b>${esc(m.title || m.ref)}</b>
        <small class="faint">${plural(m.tasks, "open task")} · ${m.blocked_n} held · ${m.conditional_n} conditional · ${plural(m.confirm, "need")} to confirm</small>
        <button type="button" class="btn sm" data-ctlo-recheck="${esc(m.ref)}" title="Probe this mission's requirements now (the sign-in check sends one tiny prompt)">${icon("reset")}Re-check</button></div>
        ${m.blocked.length ? `<ul class="ctlo-gb">${m.blocked.slice(0, 6).map(b => `<li><span>#${b.task} ${esc(b.title)}</span>${b.items.map(i =>
          `<small>${badge(i.critical ? "bad" : "warn", need(i))} ${esc(i.probe)} <span class="faint">(${esc(when(i))})</span>: ${esc(i.remedy || i.evidence)} <em>(${esc(i.who || "you")})</em></small>`).join("")}</li>`).join("")}
          ${m.blocked_n > 6 ? `<li class="faint small">and ${m.blocked_n - 6} more</li>` : ""}</ul>` : ""}</li>`;
    const risk = r => `<tr data-src="${esc(r.source || "")}"${riskSrc && r.source !== riskSrc ? " hidden" : ""}><td>${badge(r.critical ? "bad" : r.status === "accepted" ? "warn" : "muted", r.status === "accepted" ? "Accepted" : r.critical ? "Critical" : "Open")}</td>
        <td>${esc(r.title)}<small class="faint">${esc(RSRC[r.source] || r.source || "")}${r.mission ? " · " + esc(r.mission) : ""} · ${esc(r.countermeasure || "")} · ${esc(r.responsible || "")} · seen ${r.seen}×</small></td>
        <td class="ctlo-gact">${!r.critical && r.status === "open" ? `<button type="button" class="btn sm" data-ctlo-risk-accept="${r.id}" data-ctlo-risk-src="${esc(r.source || "readiness")}">Accept</button>` : ""}
          ${r.cap === "credential" && r.state === "UNKNOWN" && r.status === "open" ? `<button type="button" class="btn sm" data-ctlo-risk-verify="${r.id}">Verify</button>` : ""}
          ${r.cap === "approval" && r.status === "open" ? `<button type="button" class="btn sm" data-ctlo-risk-approve="${r.id}">Approve</button>` : ""}</td></tr>`;
    const srcs = [...new Set(g.risks.map(r => r.source).filter(Boolean))];
    if (riskSrc && !srcs.includes(riskSrc)) riskSrc = "";
    return `<section class="ctlo-card ctlo-gate" aria-labelledby="ctlo-g"><h3 id="ctlo-g">${icon("shield")}Mission readiness</h3>
      <p class="faint small">Each task's declared needs are checked against the real environment before an agent starts it; what fails holds the task, with its fix. Needs read from a task's words only ask for confirmation.</p>
      <ul class="ctlo-gl">${g.missions.map(mis).join("")}</ul>
      ${g.risks.length ? `<details class="ctlo-gr"${riskOpen ? " open" : ""}><summary>Risk register: ${plural(g.risks.length, "open or accepted risk")}</summary>
        ${srcs.length > 1 ? `<label class="ctlo-rsrcl small">Source <select class="ctlo-rsrc"><option value="">All</option>${srcs.map(x =>
          `<option value="${esc(x)}"${x === riskSrc ? " selected" : ""}>${esc(RSRC[x] || x)} (${g.risks.filter(r => r.source === x).length})</option>`).join("")}</select></label>` : ""}
        <table class="ctlo-tbl wide"><thead><tr><th>State</th><th>Risk, countermeasure, owner</th><th></th></tr></thead><tbody>${g.risks.map(risk).join("")}</tbody></table></details>` : ""}</section>`;
  }

  // ---------- a competition: objective, progress (two figures), blocker, next action ----------
  function compCard(c) {
    const [tone, label] = HEALTH[c.health] || ["muted", c.health], o = c.objective_progress, w = c.work, d = c.decision;
    const official = o.official.measurable ? `<b>${esc(o.official.text)}</b>` : `<b class="ctlo-unknown">Not measurable</b><small>Reason: ${esc(o.official.reason || "unknown")}</small>`;
    return `<article class="ctlo-comp h-${esc(c.health)}">
      <header><h3><button type="button" class="linkbtn" data-ctlo-mission="${esc(c.ref)}">${esc(c.title)}</button></h3>${badge(tone, label, d.label)}</header>
      <p class="ctlo-obj"><small>Objective</small>${esc(c.objective)}</p>
      <dl class="ctlo-prog">
        <div><dt>Official progress</dt><dd>${official}</dd></div>
        <div><dt>Objective progress <small class="faint">verified criteria only</small></dt><dd>${bar(o.pct, "obj")}<b>${o.pct == null ? "–" : o.pct + "%"}</b><small>${o.verified} of ${o.total} criteria met${o.unverified ? `, ${o.unverified} not verified` : ""}</small></dd></div>
        ${w.headline === "active"
          ? `<div><dt>Work progress <small class="faint">active plan</small></dt><dd>${bar(w.pct_active)}<b>${w.pct_active == null ? "–" : w.pct_active + "%"}</b>${w.pct != null ? ` <small class="faint" title="Verified work over the original scope">${w.pct}% of the original scope</small>` : ""}`
          : `<div><dt>Work progress <small class="faint">original scope</small></dt><dd>${bar(w.pct)}<b>${w.pct == null ? "–" : w.pct + "%"}</b>${w.pct_active != null ? ` <small class="faint" title="Verified work over the original scope plus additions a person made, less what a person cancelled; dropped work stays in as not done">${w.pct_active}% of the active plan</small>` : ""}`}<small>${w.verified_original ?? w.verified} verified of ${w.original ?? w.planned} in the original scope · ${w.review ?? 0} in review · ${w.completed} completed without a verdict${w.running ? ` · ${w.running} running` : ""}${w.dropped ? ` · ${w.dropped} dropped (never counted as done)` : ""}${addLine(w)}</small></dd></div>
      </dl>
      ${d.blocker ? `<p class="ctlo-block">${icon("alert")}<span><small>What prevents it</small>${esc(d.blocker)}</span></p>` : ""}
      <p class="ctlo-next">${icon("right")}<span><small>Next action · owner ${own(d.owner)}</small>${esc(d.next)}</span></p>
      <footer><small class="faint">${esc(d.label)}: ${esc(d.response.toLowerCase())} · confidence ${esc(c.confidence)}${c.budget.tokens ? ` · ${tok(c.budget.used_24h)} of ${tok(c.budget.tokens)} tokens in 24 h` : ""}</small>
        <span><button type="button" class="btn sm" data-ctlo-mission="${esc(c.ref)}">${icon("eye")}Details</button>${c.unit ? `<button type="button" class="btn sm" data-ctlo-node="${esc(c.unit)}">${icon("users")}Team</button>` : ""}</span></footer></article>`;
  }
  function customRow(c) {
    const o = c.objective_progress;
    return `<li><span><button type="button" class="linkbtn" data-ctlo-mission="${esc(c.ref)}">${esc(c.title)}</button><small class="faint">${esc(c.decision.next)}</small></span>
      ${badge(TONE[c.state] || "muted", c.state[0] + c.state.slice(1).toLowerCase(), c.decision.label)}<small class="ctlo-n">${o.pct == null ? "no criteria verified" : `${o.pct}% verified`}</small></li>`;
  }

  // ---------- global activity in one state model ----------
  function activity() {
    const a = data.activity, n = data.activity_note;
    const cell = s => `<li class="s-${s.key.toLowerCase()} ${a[s.key] ? "on" : ""}" title="${esc(s.note)}"><b>${a[s.key] || 0}</b><small>${esc(s.label)}</small></li>`;
    return `<section class="ctlo-card" aria-labelledby="ctlo-act"><h3 id="ctlo-act">${icon("list")}Global activity</h3>
      <ol class="ctlo-path">${data.states.filter(s => s.path).map(cell).join("")}</ol>
      <ul class="ctlo-off">${data.states.filter(s => !s.path).map(cell).join("")}</ul>
      <p class="faint small">Every task of every engine in one state. Done is not Verified: ${n.unverified_done ? `${plural(n.unverified_done, "task")} closed without an independent verdict (Completed)` : "nothing closed without a verdict"}, ${plural(n.in_review ?? 0, "task")} waiting for one (Review)${n.dropped ? `; ${plural(n.dropped, "task")} dropped by the Director, counted as neither` : ""}; ${n.verified_24h} verified in the last 24 hours.</p></section>`;
  }

  // ---------- the one decision queue ----------
  function queue() {
    const q = data.queue, rows = allQ ? q : q.slice(0, 6);
    const li = x => { const [ic, l] = QK[x.kind] || ["info", x.kind];
      return `<li class="l-${esc(x.level)}"><span class="ctlo-qi">${icon(ic)}</span><span class="ctlo-qt"><b>${esc(x.title)}</b><small>${esc(x.detail)}</small>
          <small class="faint">${esc(l)} · owner ${own(x.owner)}${x.ts ? ` · ${esc(ago(x.ts))}` : ""}</small></span>
        <span class="ctlo-qa">${x.action === "verify" ? `<button type="button" class="btn sm" data-ctlo-sample>Check</button>`
          : x.action === "competitors" && x.ref ? `<button type="button" class="btn sm" data-ctlo-mission="${esc(x.ref)}" data-tab="competitors">Decide</button>`
          : x.action === "budget" && x.ref ? `<button type="button" class="btn sm" data-ctlo-mission="${esc(x.ref)}" data-tab="budget">Reconcile</button>`
          : x.ref && /^(comp|mx):/.test(x.ref) ? `<button type="button" class="btn sm" data-ctlo-mission="${esc(x.ref)}">Open</button>`
          : x.go ? `<button type="button" class="btn sm" data-ctlo-go="${esc(x.go)}">Open</button>` : ""}</span></li>`; };
    return `<section class="ctlo-card" aria-labelledby="ctlo-q"><h3 id="ctlo-q">${icon("inbox")}Decision queue <small class="faint">${q.length}</small></h3>
      ${q.length ? `<ul class="ctlo-queue">${rows.map(li).join("")}</ul>${q.length > 6 ? `<button type="button" class="linkbtn" data-ctlo-allq>${allQ ? "Show fewer" : `Show all ${q.length}`}</button>` : ""}`
                 : `<p class="faint">${icon("check")}Nothing waits for a decision.</p>`}</section>`;
  }

  // ---------- secondary: accountability, budgets, evolution, readiness (folded) ----------
  const FOLDS = [["runs", "check", "Run accountability"], ["budget", "coins", "Budgets"], ["knowledge", "book", "Knowledge"], ["evolution", "zap", "Evolution"], ["readiness", "shield", "G5 readiness"]];
  function folds() {
    const sum = { runs: () => { const a = data.accountability; if (!a || !a.total) return "no finished run this week";
                                const inc = a.outcomes.find(o => o.key === "inconclusive").n; return `${a.total} finished this week · ${inc} inconclusive · ${a.coverage_pct ?? "–"}% of eligible scored`; },
                  budget: () => { const s = data.budget.scopes, m = s.filter(x => !x.set).length, o = data.budget.reconcile.filter(x => x.state === "over").length;
                                  return `${s.length - m} of ${s.length} scopes limited${o ? ` · ${plural(o, "team")} over budget` : ""} · ${data.budget.refused_7d} calls refused this week`; },
                  knowledge: () => data.knowledge?.error ? "couldn't be read" : data.knowledge?.summary || "no knowledge system on this server",
                  evolution: () => { const e = data.evolution; return e.items.length ? `${plural(e.items.length, "change")} across ${plural(e.sources.length, "loop")} · ${e.promoted} promoted, ${e.promoted_with_evidence} with benchmark evidence` : "no change proposed yet"; },
                  readiness: () => `${data.readiness.pass} of ${data.readiness.total} acceptance rows pass on records${data.readiness.design_only ? ` · ${data.readiness.design_only} implemented only` : ""} · ${data.readiness.verdict}` };
    const pane = { runs: runsPane, budget: budgetPane, knowledge: knowPane, evolution: evoPane, readiness: readyPane };
    return `<div class="ctlo-folds">${FOLDS.map(([k, ic, l]) => `<section class="ctlo-fold ${fold === k ? "open" : ""}">
        <button type="button" class="ctlo-fh" data-ctlo-fold="${k}" aria-expanded="${fold === k}">${icon(ic)}<b>${l}</b><small class="faint">${esc(sum[k]())}</small>${icon("chev")}</button>
        ${fold === k ? `<div class="ctlo-fb">${pane[k]()}</div>` : ""}</section>`).join("")}</div>`;
  }
  function runsPane() {
    const a = data.accountability;
    if (!a || !a.total) return `<p class="faint">No finished run in the last 7 days.</p>`;
    return `<p class="faint small">Every finished run of the last 7 days is in exactly one outcome; they add up to ${a.total}. Coverage: ${a.scored_eligible} of ${a.eligible} eligible runs scored (${a.coverage_pct ?? "–"}%, target ${a.target}%).</p>
      <ul class="ctlo-out">${a.outcomes.map(o => `<li class="o-${o.key}"><b>${o.n}</b><span>${esc(o.label)}<small class="faint">${esc(o.note)}</small></span></li>`).join("")}</ul>
      ${a.inconclusive.length ? `<h4>Inconclusive: why, and what happens next</h4><ul class="ctlo-list">${a.inconclusive.map(x => `<li><b>${x.n}</b><span>${esc(x.what)}<small>${esc(x.reason)}</small><small class="faint">Next: ${esc(x.next)}</small></span></li>`).join("")}</ul>` : ""}
      ${a.excluded_reasons.length ? `<h4>Excluded, with the reason</h4><ul class="ctlo-list">${a.excluded_reasons.map(x => `<li><b>${x.n}</b><span>${esc(x.reason || "No reason recorded")}</span></li>`).join("")}</ul>` : ""}
      <div class="row end"><button type="button" class="btn sm" data-ctlo-go="layers">${icon("layers")}Intelligence layers</button></div>`;
  }
  function recBlock(r) {
    if (!r) return "";
    const row = (l, v, sub = "") => `<tr><th scope="row">${esc(l)}</th><td class="num">${v}</td><td class="faint">${esc(sub)}</td></tr>`;
    return `<div class="ctlo-rec s-${esc(r.state)}"><h4>${esc(r.name)} ${badge(r.state === "over" ? "scam" : r.state === "near" ? "caution" : r.state === "unset" ? "muted" : "clear", r.state === "over" ? `${r.over_x}× over` : r.state === "near" ? "Near the limit" : r.state === "unset" ? "No budget" : "Within budget")}</h4>
      <table class="ctlo-tbl"><tbody>${row("24-hour budget", r.budget ? tok(r.budget) : "none", "the team's own setting")}
        ${row("Finished runs", tok(r.finished), `${r.finished_runs} runs, written when each ended`)}${row("Runs in flight", tok(r.in_flight), `${r.in_flight_runs} running now, counted as they spend`)}
        ${row("Counted against the budget", `<b>${tok(r.counted)}</b>`, r.over ? `${tok(r.over)} over` : "")}${row("The ledger, same window", tok(r.ledger), `${r.ledger_runs} runs, per model call`)}
        ${r.plan_share != null ? row("From plan (CLI) runs", `${r.plan_share}%`, "terminal, Codex, Copilot CLI") : ""}</tbody></table>
      ${r.causes.length ? `<ul class="ctlo-causes">${r.causes.map(x => `<li>${icon("info")}${esc(x)}</li>`).join("")}</ul>` : ""}${r.note ? `<p class="faint small">${esc(r.note)}</p>` : ""}
      ${r.biggest.length ? `<details><summary>Biggest runs and where the tokens went</summary><ul class="ctlo-list">${r.biggest.map(x => `<li><b>${tok(x.tokens)}</b><span>${esc(x.title || x.kind)}<small class="faint">${esc(x.kind)} · ${esc(x.model || "no model recorded")} · ${esc(x.status)} · ${esc(ago(x.started))}</small></span></li>`).join("")}</ul>
        <p class="faint small">By kind: ${r.by_kind.map(x => `${esc(x.kind)} ${tok(x.tokens)}`).join(" · ")}. By model: ${r.by_model.map(x => `${esc(x.model || "none")} ${tok(x.tokens)}`).join(" · ")}.</p></details>` : ""}</div>`;
  }
  function budgetPane() {
    const b = data.budget;
    return `<p class="faint small">A warning is not a hard budget. Limits are checked before every model call and before new work starts; AXoR never sets one for you.</p>
      <div class="ctlo-scopes">${b.scopes.map(s => `<div class="ctlo-scope ${s.set ? "set" : "unset"}"><h4>${esc(s.label)} ${badge(s.set ? "clear" : "scam", s.set ? "Limited" : "No hard limit")}</h4>
        <p class="small">${esc(s.required)}</p><p class="small"><b>${esc(s.detail)}</b></p>${s.missing.length ? `<p class="small ctlo-miss">Missing: ${esc(s.missing.slice(0, 3).join("; "))}${s.missing.length > 3 ? "…" : ""}</p>` : ""}
        <p class="faint small">${esc(s.where)}</p><button type="button" class="btn sm" data-ctlo-go="${esc(s.go)}">${s.set ? "Review" : "Set a limit"}</button></div>`).join("")}</div>
      ${b.reconcile.length ? `<h4>Reconciliation: each team's budget against every count of its tokens (last 24 hours)</h4>${b.reconcile.map(recBlock).join("")}` : ""}
      <section class="ctlo-unm" data-ctlo-unm><h4>Unmetered runs</h4><p class="faint small">Reading…</p></section>`;
  }
  // a search that ran is not knowledge that was used: six questions, each from records
  function knowPane() {
    const k = data.knowledge;
    if (!k || k.error) return `<p class="ctl-warn">${icon("alert")}${esc(k?.error || "Knowledge isn't on this server.")}</p>`;
    const QS = { ok: ["clear", "Yes"], warn: ["caution", "Gap"], none: ["muted", "Nothing yet"] }, r = k.retrieval, x = k.recalls;
    return `<p class="faint small">A search that ran is not knowledge that was used. Last 7 days; each answer is read from records.</p>
      <ol class="ctlo-kq">${k.questions.map(q => `<li class="k-${q.state}">${badge(QS[q.state][0], QS[q.state][1])}<span><b>${esc(q.q)}</b><small>${esc(q.a)}</small></span></li>`).join("")}</ol>
      ${k.access.note ? `<p class="ctlo-block">${icon("alert")}<span><small>What prevents retrieval</small>${esc(k.access.note)}</span></p>` : ""}
      ${k.actors.some(a => a.empty_scope) ? `<h4>Searches that found nothing the searcher may read</h4><ul class="ctlo-list">${k.actors.filter(a => a.empty_scope).map(a => `<li><b>${a.empty_scope}</b><span>${esc(a.label)} <small class="faint">of ${a.searches} searches · ${a.found} found something</small><small>${esc(a.fix)}</small></span></li>`).join("")}</ul>` : ""}
      <div class="ctlo-scopes">
        <div class="ctlo-scope"><h4>Sources</h4>${k.sources.map(s => `<p class="small"><b>${s.n}</b> ${esc(s.label)} <span class="faint">${esc(s.note)}</span></p>`).join("") || `<p class="faint small">None.</p>`}</div>
        <div class="ctlo-scope"><h4>Index</h4><p class="small"><b>${k.index.indexed}</b> of ${k.index.records} records searchable · ${k.index.passages} passages · ${k.index.vectors} vectors</p><p class="faint small">${esc(k.index.note)}</p></div>
        <div class="ctlo-scope"><h4>Who may read</h4>${k.access.reach.map(s => `<p class="small"><b>${s.n}</b> ${esc(s.label)}</p>`).join("") || `<p class="faint small">No records.</p>`}<p class="faint small">${plural(k.access.grants.length, "scope grant")}${k.access.grants.length ? `: ${k.access.grants.slice(0, 4).map(g => `${esc(g.actor)} → ${esc(g.scope)}`).join(", ")}` : ""}</p></div>
        <div class="ctlo-scope"><h4>Retrieved and used</h4><p class="small"><b>${r.found}</b> of ${r.searches} searches returned something · ${r.empty_scope} had nothing they may read · ${r.no_match} no match</p>
          <p class="small"><b>${r.cited}</b> answers cited what they retrieved · <b>${x.used}</b> experiences recalled into work</p>
          <p class="small">That work: ${x.success} succeeded · ${x.partial} partly · ${x.failure} failed · ${x.open} open</p><p class="faint small">${esc(k.caveat)}</p></div></div>
      <div class="row end"><button type="button" class="btn sm" data-ctlo-go="knowledge">${icon("book")}Knowledge</button><button type="button" class="btn sm" data-ctlo-go="learning">${icon("zap")}Learning</button></div>`;
  }
  const STG = { proposed: "muted", testing: "new", verified: "caution", promoted: "clear", rejected: "muted", rolled_back: "scam", regressed: "scam" };
  const evoRow = it => `<li><span>${esc(it.title)}<small class="faint">${esc(it.where)} · ${esc(it.target || "")}${it.baseline != null && it.candidate != null ? ` · ${esc(String(it.baseline))} → ${esc(String(it.candidate))}` : ""}${it.miner ? ` · miner benchmark ${it.miner.before} → ${it.miner.after}` : ""}${it.ts ? ` · ${esc(ago(it.ts))}` : ""}</small></span>
      ${badge(STG[it.stage] || "muted", it.stage.replace("_", " "))}${badge(it.evidence ? "clear" : "muted", it.evidence ? "Benchmark evidence" : "No evidence")}</li>`;
  function evoPane() {
    const e = data.evolution;
    return `<p class="faint small">${esc(e.rule)} An improvement of an agent is not yet an improvement of the miner: a competition's change also shows the team's benchmark after it.</p>
      ${e.items.length ? `<p class="small">${Object.entries(e.by_stage).map(([k, n]) => `${n} ${esc(k.replace("_", " "))}`).join(" · ")} · tested this week: ${e.tested_7d}</p><ul class="ctlo-evo">${e.items.slice(0, 14).map(evoRow).join("")}</ul>`
        : `<p class="faint">No improvement has been proposed in any loop yet: continuous evolution is not demonstrated.</p>`}
      <div class="row end"><button type="button" class="btn sm" data-ctlo-go="evolution">${icon("zap")}Evolution Lab</button></div>`;
  }
  function readyPane() {
    const r = data.readiness;
    const lv = r.levels || {};
    return `<p class="faint small">The conditions for calling the self-evolving ecosystem operational, each computed from records, not from a claim. Only rows whose records show them in operation pass; built-only rows are Implemented, never demonstrated.</p>
      ${r.levels ? `<p class="small">${["demonstrated", "operational", "partial", "implemented", "unknown", "fail"].filter(k => lv[k]).map(k => `${lv[k]} ${esc((r.level_labels || {})[k] || k).toLowerCase()}`).join(" · ")}</p>` : ""}
      <ul class="ctlo-ready">${r.rows.map(x => { const [tone, l] = RD[x.state]; return `<li class="r-${x.state}">${badge(tone, l)}<span><b>${esc(x.label)}</b>${x.level_label ? ` <small class="faint" title="${esc((r.level_notes || {})[x.level] || "")}">${esc(x.level_label)}</small>` : ""}<small class="faint">${esc(x.required)}</small><small>${esc(x.detail)}</small></span>
        ${x.go ? `<button type="button" class="iconbtn sm" data-ctlo-go="${esc(x.go)}" title="Open" aria-label="Open ${esc(x.label)}">${icon("right")}</button>` : ""}</li>`; }).join("")}</ul>
      <details><summary>How AXoR responds to each situation</summary><table class="ctlo-tbl wide"><thead><tr><th>Situation</th><th>Response</th><th>Next action</th></tr></thead>
        <tbody>${data.situations.map(s => `<tr><th scope="row">${esc(s.label)}</th><td>${esc(s.response)}</td><td>${esc(s.next)}</td></tr>`).join("")}</tbody></table>
        <table class="ctlo-tbl wide"><thead><tr><th>Failure class</th><th>Treated as</th><th>Recovery</th></tr></thead>
        <tbody>${data.recovery.map(s => `<tr><th scope="row">${esc(s.cls)}</th><td>${esc(s.situation)}</td><td>${esc(s.recovery)}</td></tr>`).join("")}</tbody></table></details>`;
  }

  // ---------- dialogs ----------
  // ---------- P3: a person checks this week's sample of agent approvals ----------
  async function sampleDlg() {
    const d = dlg("ctlo-sdlg");
    d.innerHTML = `<p class="faint">Loading…</p>`;
    try { sampleRender(await api(`${B}/verify-sample`)); } catch (x) { d.innerHTML = `<p>${esc(x.message)}</p><div class="row end"><button type="button" class="btn" data-ctlo-x>Close</button></div>`; }
  }
  // Milestone 3: additions to the original scope, shown apart: made by a person (in the active plan), made by agents (in neither figure)
  function addLine(w) {
    const a = w && w.additions;
    if (!a || !(a.approved || a.agent)) return "";
    return `<br>Added since: ${a.approved} by a person (${a.approved_verified} verified, in the active plan)${a.agent ? ` · ${a.agent} by agents (${a.agent_verified} verified, ${a.agent_dropped} dropped; in neither figure until the Owner decides how agent additions are approved)` : ""}`;
  }

  function sampleRender(v) {
    const d = dlg("ctlo-sdlg"), s = v.summary;
    const one = t => `<li class="ctlo-sitem"><b>#${t.id} ${esc(t.title)}</b><small class="faint">${esc(t.approved || "")}${t.agent ? ` · by ${esc(t.agent)}` : ""}</small>
        <p class="small">${esc(t.summary || "(no summary)")}</p>
        ${t.verdict ? `<p class="small">Your verdict: <b>${esc(t.verdict)}</b></p>` : `<label class="in"><span class="small">If you disagree, say why (optional)</span><textarea id="ctlo-sn-${t.id}" rows="2" maxlength="600"></textarea></label>
        <div class="row"><button type="button" class="btn sm" data-ctlo-sv="agree" data-task="${t.id}">Agree</button><button type="button" class="btn sm" data-ctlo-sv="disagree" data-task="${t.id}">Disagree</button><button type="button" class="btn sm" data-ctlo-sv="unsure" data-task="${t.id}">Unsure</button></div>`}</li>`;
    d.innerHTML = `<h3>Check agent-approved work</h3>
      <p class="small" data-ctlo-tiers>Agent-approved last week: <b>${s.agent_approved_week ?? "?"}</b> · Owner-reviewed (${s.threshold.days} days): <b>${s.owner_reviewed_30d ?? s.human_reviewed_30d ?? s.reviews_30d}</b> (${s.reviews_30d} decided, ${s.disagree_30d} disagree${s.agreement_pct != null ? `, ${s.agreement_pct}% agreement` : ""}; threshold ${s.met ? "met" : "not met"}) · Independently verified: <b>${s.independently_demonstrated ? "yes" : "no"}</b>${s.independent_reviewer ? "" : ` <span class="faint">(no independent reviewer yet)</span>`}</p>
      <p class="faint small">A reproducible ${Math.round(s.rate * 100)}% sample of this week's work an agent approved, chosen by no agent. Your verdict is recorded under your name; a disagreement is flagged for a decision and reopens nothing.
      Last ${s.threshold.days} days: ${s.agree_30d} agree, ${s.disagree_30d} disagree (${s.reviews_30d} reviews${s.agreement_pct != null ? `, ${s.agreement_pct}% agreement` : ""}), ${s.unsure_30d} unsure (counted apart).
      The owner-review threshold is ${s.threshold.min} reviews at ${s.threshold.agree}% agreement: ${s.met ? "met" : "not met yet"}. Your reviews check the agents; as the team's owner they aren't independent verification, which needs a reviewer outside the team.</p>
      ${v.tasks.length ? `<ul class="ctlo-slist">${v.tasks.map(one).join("")}</ul>` : `<p class="faint">Nothing to check this week.</p>`}
      <div class="row end"><button type="button" class="btn" data-ctlo-x>Close</button></div>`;
  }

  function dlg(cls = "") {
    let el = document.getElementById("ctlo-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "ctlo-dlg"; document.body.append(el); }
    el.className = `modal ctl-dlg wide ctlo-dlg ${cls}`;
    if (!el.open) el.showModal();
    return el;
  }
  const shell = (title, inner) => `<div class="ctl-h"><h3>${title}</h3><button type="button" class="iconbtn" data-ctlo-x aria-label="Close">${icon("close")}</button></div><div class="ctl-dbody">${inner}</div>`;
  const failBox = (el, e) => { el.innerHTML = shell("Couldn't load", `<p class="ctl-warn">${icon("alert")}${esc(e.message)}</p>`); };

  const MTABS = [["objective", "Objective"], ["performance", "Performance"], ["portfolio", "Strategy portfolio"], ["competitors", "Competitors"], ["budget", "Budget"], ["evolution", "Evolution"]];
  // competitors as evidence (mission_evidence.py): seven steps, what the field shows, and each technique's hypothesis,
  // reproduction and measured verdict. Adopt is offered only for a result that beat the baseline on the same suite.
  const TST = { hypothesis: ["muted", "Hypothesis"], reproducing: ["new", "Being reproduced"], evaluated: ["caution", "Measured"], adopted: ["clear", "Adopted"], rejected: ["muted", "Rejected"] };
  function compPane(v) {
    if (!v) return `<p class="faint">${icon("cycle")}Reading the field…</p>`;
    if (v.error) return `<p class="ctl-warn">${icon("alert")}${esc(v.error)}</p>`;
    const tech = t => { const [tone, l] = TST[t.status] || ["muted", t.status];
      return `<li><div class="ctlo-th"><b>${esc(t.title)}</b>${badge(tone, l)}</div>
        ${t.observation ? `<small><i>Observed:</i> ${esc(t.observation)}</small>` : ""}<small><i>Hypothesis:</i> ${esc(t.hypothesis)}</small>
        ${t.task ? `<small class="faint">Reproduction: board task #${t.task.id}, ${esc(t.task.status)}${t.task.gave_up ? " (gave up)" : ""} <button type="button" class="linkbtn" data-ctlo-graph="mw:${t.task.id}">trace</button></small>` : t.task_gone ? `<small class="faint">Its board task was deleted.</small>` : ""}
        <small class="${t.delta > 0 ? "ctlo-up" : t.delta != null ? "ctlo-down" : "faint"}">${t.candidate != null && t.baseline != null ? `Measured on ${esc(t.suite)}: ${t.baseline} → ${t.candidate} (${t.delta > 0 ? "+" : ""}${t.delta})` : esc(t.why_not || "")}</small>
        ${t.decided_by ? `<small class="faint">Decided by ${esc(t.decided_by)}${t.note ? `: ${esc(t.note)}` : ""}</small>` : ""}
        ${["adopted", "rejected"].includes(t.status) ? "" : `<div class="row">${!t.task && t.status === "hypothesis" ? `<button type="button" class="btn sm" data-ctlo-tech="reproduce" data-id="${t.id}">${icon("zap")}Reproduce in isolation</button>` : ""}
          ${t.can_adopt ? `<button type="button" class="btn primary sm" data-ctlo-tech="adopt" data-id="${t.id}">${icon("check")}Adopt</button>` : ""}
          <button type="button" class="btn sm" data-ctlo-tech="reject" data-id="${t.id}">Reject</button></div>`}</li>`; };
    return `<p class="faint small">${esc(v.note)}</p>
      <ol class="ctlo-steps">${v.steps.map(s => `<li class="${s.state}" title="${esc(s.what)}"><i>${s.state === "done" ? icon("check") : s.n}</i><b>${esc(s.label)}</b><small>${esc(s.detail)}</small></li>`).join("")}</ol>
      <div class="ctlo-dec"><b>${v.next.step ? `Next: ${esc(v.next.step.toLowerCase())}` : "All seven steps have evidence"}</b><p>${icon("right")}${esc(v.next.text)}</p></div>
      ${v.harvest ? `<p class="faint small">Field last read ${esc(ago(v.harvest.last))}${v.harvest.ok ? "" : ` · ${esc(v.harvest.error || "the last pass failed")}`}${v.leaders.length ? ` · leaders: ${v.leaders.map(l => `${esc(l.name)} v${l.version} (${l.score})`).join(", ")}` : ""}</p>` : ""}
      <h4>Techniques</h4>${v.techniques.length ? `<ul class="ctlo-tech">${v.techniques.map(tech).join("")}</ul>` : `<p class="faint">No hypothesis yet.</p>`}
      <h4>Observed in the field</h4>${v.observed.length ? `<ul class="ctlo-list">${v.observed.map((o, i) => `<li><span>${esc(o.title)}<small class="faint">${esc(o.kind)}</small><small>${esc(o.observation)}</small></span>
          ${o.taken ? badge("muted", "Has a hypothesis") : `<button type="button" class="btn sm" data-ctlo-hyp="${i}">Write a hypothesis</button>`}</li>`).join("")}</ul>`
        : `<p class="faint">${v.harvested ? "Nothing stands out in the field yet." : "No competitor harvest for this competition: write what you observed yourself."}</p>`}
      <div class="row"><button type="button" class="btn sm" data-ctlo-hyp="">${icon("plus")}Add a technique by hand</button></div>`;
  }
  async function loadComp(el) {
    const ref = el._m.mission.ref;
    try { el._c = await api(`${B}/missions/${encodeURIComponent(ref)}/competitors`); } catch (e) { el._c = { error: e.message }; }
    if (el.open && el._tab === "competitors" && el._m.mission.ref === ref) drawMission(el, el._m, "competitors");
  }
  function hypForm(el, i) {
    const o = i === "" ? null : el._c.observed[+i], pane = el.querySelector(".ctlo-pane");
    pane.innerHTML = `<form class="ctl-form ctlo-cform"><h4>${o ? esc(o.title) : "A technique you observed"}</h4>
      ${o ? `<p class="small"><i>Observed:</i> ${esc(o.observation)}</p>` : `<label class="ctl-field"><span>Technique</span><input name="title" maxlength="200" required minlength="3" placeholder="Retry with a smaller patch when the first one fails to apply"></label>
        <label class="ctl-field"><span>What you observed <small class="faint">where, and what it did for them</small></span><textarea name="observation" rows="2" maxlength="2000"></textarea></label>`}
      <label class="ctl-field"><span>Hypothesis <small class="faint">why it would work for your miner; this is what the reproduction tests</small></span><textarea name="hypothesis" rows="3" maxlength="2000" minlength="10" required></textarea></label>
      <p class="err" role="alert"></p><div class="row end"><button type="button" class="btn sm" data-ctlo-mtab="competitors">Cancel</button><button type="submit" class="btn primary sm">Save the hypothesis</button></div></form>`;
    pane.querySelector("form").onsubmit = async ev => {
      ev.preventDefault(); const fd = new FormData(ev.target);
      const body = o ? { title: o.title, observation: o.observation, source: o.source, source_ref: o.ref, hypothesis: fd.get("hypothesis") } : { title: fd.get("title"), observation: fd.get("observation") || "", hypothesis: fd.get("hypothesis") };
      try { el._c = await api(`${B}/missions/${encodeURIComponent(el._m.mission.ref)}/techniques`, { method: "POST", body }); drawMission(el, el._m, "competitors"); Auth.toast("Hypothesis saved"); }
      catch (e) { pane.querySelector(".err").textContent = e.message; }
    };
  }
  async function openMission(ref, tab = "objective") {
    const el = dlg();
    el._c = null;
    el.innerHTML = shell("Loading…", `<p class="faint">${icon("cycle")}Loading the mission…</p>`);
    try { drawMission(el, await api(`${B}/missions/${encodeURIComponent(ref)}`), tab); } catch (e) { failBox(el, e); }
  }
  function drawMission(el, d, tab) {
    const c = d.mission, comp = c.type === "predefined", o = c.objective_progress;
    const tabs = MTABS.filter(([k]) => comp || k === "objective");
    if (el._c && el._c.ref !== c.ref && !el._c.error) el._c = null;
    if (tab === "competitors" && comp && !el._c) { el._m = d; el._tab = tab; loadComp(el); }
    if (!tabs.some(([k]) => k === tab)) tab = "objective";
    const critRow = x => `<li class="${x.off ? "off" : x.verified && x.value >= 1 ? "met" : x.verified ? "part" : "open"}">
        <span class="ctlo-cs">${x.off ? icon("eye") : x.verified && x.value >= 1 ? icon("check") : x.unknown ? "?" : x.verified ? `${Math.round(x.value * 100)}%` : icon("clock")}</span>
        <span class="ctlo-ct"><b>${esc(x.label)}</b> <small class="faint">weight ${x.weight}${x.source === "yours" ? " · yours" : ""}${x.off ? " · switched off" : ""}</small>
          <small>${x.verified ? "" : `<em>${x.unknown ? "UNKNOWN" : "Not verified"}</em> · `}${esc((x.evidence || "").replace(/^UNKNOWN: /, ""))}</small>${x.needs ? `<small class="ctlo-need">Needed: ${esc(x.needs)} <i>(${esc(x.owner)})</i></small>` : ""}</span>
        <span class="ctlo-ca"><button type="button" class="iconbtn sm" data-ctlo-crit="${esc(x.key)}" title="Weight, evidence" aria-label="Edit ${esc(x.label)}">${icon("edit")}</button></span></li>`;
    const pane = {
      objective: () => `<p class="ctlo-obj big"><small>Objective</small>${esc(c.objective)}${c.objective_note ? `<small class="faint">${esc(c.objective_note)}</small>` : ""}</p>
        <div class="ctlo-pgrid"><div><small>Official progress</small>${o.official.measurable ? `<b>${esc(o.official.text)}</b>` : `<b class="ctlo-unknown">UNKNOWN</b><small>${esc(o.official.reason)}</small><small class="ctlo-need">Needed: ${esc(o.official.needs)}</small>`}</div>
          <div><small>Objective progress</small><b>${o.pct == null ? "–" : o.pct + "%"}</b>${bar(o.pct, "obj")}<small>Σ weight × verified value ÷ Σ weight; an unverified criterion counts 0</small></div>
          ${c.work.headline === "active"
            ? `<div><small>Work progress · active plan</small><b>${c.work.pct_active == null ? "–" : c.work.pct_active + "%"}</b>${bar(c.work.pct_active)}${c.work.pct != null ? `<small class="faint" title="Verified work over the original scope">${c.work.pct}% of the original scope</small>` : ""}`
            : `<div><small>Work progress · original scope</small><b>${c.work.pct == null ? "–" : c.work.pct + "%"}</b>${bar(c.work.pct)}${c.work.pct_active != null ? `<small class="faint" title="Verified work over what is still planned">${c.work.pct_active}% of the active plan</small>` : ""}`}<small>${c.work.verified_original ?? c.work.verified} verified of ${c.work.original ?? c.work.planned} in the original scope · ${c.work.review ?? 0} in review · ${c.work.completed} completed without a verdict${c.work.dropped ? ` · ${c.work.dropped} dropped (never counted as done)` : ""}${addLine(c.work)}</small></div></div>
        <div class="ctlo-dec"><b>${esc(c.decision.label)}</b> ${c.decision.blocker ? `<span>${esc(c.decision.blocker)}</span>` : ""}<p>${icon("right")}${esc(c.decision.next)} <small class="faint">owner: ${esc(c.decision.owner)}</small></p></div>
        <h4>Acceptance criteria${comp ? ", in the order they must be met" : ""}</h4><ol class="ctlo-crit">${c.criteria.map(critRow).join("") || `<li class="faint">No acceptance criteria on record.</li>`}</ol>
        <div class="row"><button type="button" class="btn sm" data-ctlo-crit="">${icon("plus")}Add a criterion</button></div>
        ${(c.attention || []).length ? `<h4>Needs attention</h4><ul class="ctlo-list">${c.attention.map(a => `<li>${badge(TONE[a.state], a.state[0] + a.state.slice(1).toLowerCase())}<span>${esc(a.title)}<small class="faint">${esc(a.why || "")}</small></span>
            <button type="button" class="btn sm" data-ctlo-graph="${esc(a.id)}">${icon("route")}Trace</button></li>`).join("")}</ul>` : ""}`,
      performance: () => `<p class="faint small">Five dimensions, kept apart: a good local benchmark without a rank is technical quality, not competition performance.</p>
        <div class="ctlo-dims">${d.performance.map(p => `<section class="${p.measured ? "" : "nm"}"><h4>${esc(p.label)} ${p.measured ? "" : badge("muted", "Not measured")}</h4>
          <dl>${p.figures.map(f => `<div><dt>${esc(f.label)}</dt><dd><b>${esc(String(f.value))}</b>${f.kind ? `<i class="ctlo-kind k-${esc(f.kind)}" title="${esc((d.figure_kinds || {})[f.kind] || "")}">${esc(f.kind)}</i>` : ""}${f.note ? `<small class="faint">${esc(f.note)}</small>` : ""}</dd></div>`).join("")}</dl></section>`).join("")}</div>
        <p class="faint small">Each figure says what it is. Only <b>measured</b> figures are measurements: the chain, a designated evaluator's report, or a job's own output. A board task's review is <b>reviewed</b>, not a score of the work.</p>`,
      portfolio: () => { const p = d.portfolio; if (!p) return `<p class="faint">No team agents.</p>`;
        return `<p class="faint small">Agents shouldn't all investigate the same approach. Lanes are read from each agent's squad, role and title; resources follow what verifies the most per token.</p>
          <div class="ctlo-lanes">${p.lanes.map((L, i) => `<section class="${L.agents.length ? "" : "empty"}"><h4><i>${"ABCDE"[i]}</i>${esc(L.label)} <small class="faint">${esc(L.aim)}</small></h4><p class="small faint">${esc(L.what)}</p>
            <p class="ctlo-ag">${L.agents.map(a => `<button type="button" class="ctlo-chip" data-ctlo-agent="${esc(a.key)}" title="${esc(a.title || "")}">${esc(a.name)}</button>`).join("") || `<em class="faint">Nobody assigned</em>`}</p>
            <p class="small">${L.verified_7d} verified · ${L.open} open · ${tok(L.tokens_7d)} tokens${L.yield != null ? ` · ${L.yield} per M` : ""} <small class="faint">(7 days)</small></p></section>`).join("")}</div>
          ${p.command.length ? `<p class="small">Command: ${p.command.map(a => `<button type="button" class="ctlo-chip" data-ctlo-agent="${esc(a.key)}">${esc(a.name)}</button>`).join("")}</p>` : ""}
          ${p.advice.length ? `<ul class="ctlo-causes">${p.advice.map(x => `<li>${icon("info")}${esc(x)}</li>`).join("")}</ul>` : ""}`; },
      competitors: () => compPane(el._c),
      budget: () => recBlock(d.reconcile) || `<p class="faint">No budget on record.</p>`,
      evolution: () => d.evolution.length ? `<ul class="ctlo-evo">${d.evolution.map(evoRow).join("")}</ul>` : `<p class="faint">No improvement of this competition's agents or miner is on record yet.</p>`,
    };
    el.innerHTML = shell(`${esc(c.title)} ${badge((HEALTH[c.health] || ["muted"])[0], (HEALTH[c.health] || [, c.health])[1])}`,
      `${tabs.length > 1 ? `<div class="ctlx-tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${k === tab}" class="ctlm-chip ${k === tab ? "on" : ""}" data-ctlo-mtab="${k}">${esc(l)}</button>`).join("")}</div>` : ""}
       <div class="ctlo-pane" role="tabpanel">${pane[tab]()}</div>`);
    el._m = d; el._tab = tab;
  }
  function critForm(el, key) {
    const d = el._m, c = d.mission, x = c.criteria.find(k => k.key === key), auto = x && x.source !== "yours";
    const pane = el.querySelector(".ctlo-pane");
    pane.innerHTML = `<form class="ctl-form ctlo-cform"><h4>${x ? esc(x.label) : "A criterion of your own"}</h4>
      ${x ? "" : `<label class="ctl-field"><span>What must be true</span><input name="label" maxlength="200" required placeholder="The Docker image is built and its digest frozen"></label>`}
      <label class="ctl-field"><span>Weight <small class="faint">its share in the objective's progress</small></span><input name="weight" type="number" min="0" max="100" step="1" value="${x ? x.weight : 10}"></label>
      ${auto ? `<p class="faint small">Its value comes from records (${esc(x.evidence || "none yet")}): you can change its weight, or leave it out of this mission's progress.</p>`
             : `<label class="ctl-field"><span>Verified value <small class="faint">0 to 100%; empty = not verified yet (counts 0)</small></span><input name="value" type="number" min="0" max="100" step="5" value="${x && x.verified ? Math.round(x.value * 100) : ""}"></label>
                <label class="ctl-field"><span>Evidence <small class="faint">what verified it: a result, a digest, a link</small></span><textarea name="evidence" rows="2" maxlength="1000">${x ? esc((x.evidence || "").replace(/ \(attested by .*\)$/, "")) : ""}</textarea></label>`}
      ${x ? `<label class="ctl-check"><input type="checkbox" name="off" ${x.off ? "checked" : ""}> Leave it out of this mission's progress</label>` : ""}
      <p class="err" role="alert"></p><div class="row end">${x && (x.edited || x.source === "yours") ? `<button type="button" class="btn sm" data-ctlo-critdrop="${esc(x.key)}">${x.source === "yours" ? "Remove" : "Reset to records"}</button>` : ""}
        <button type="button" class="btn sm" data-ctlo-mtab="objective">Cancel</button><button type="submit" class="btn primary sm">Save</button></div></form>`;
    pane.querySelector("form").onsubmit = async ev => {
      ev.preventDefault(); const fd = new FormData(ev.target), body = { key: key || null, weight: fd.get("weight") === "" ? null : +fd.get("weight") };
      if (fd.has("label")) body.label = fd.get("label");
      if (!auto) { const v = fd.get("value"); if (v !== "" && v != null) { body.value = +v / 100; body.evidence = fd.get("evidence") || ""; } else if (fd.get("evidence")) body.evidence = fd.get("evidence"); }
      if (x) body.off = fd.has("off");
      try { drawMission(el, await api(`${B}/missions/${encodeURIComponent(c.ref)}/criteria`, { method: "PUT", body }), "objective"); Auth.toast("Saved"); data = null; load(true); }
      catch (e) { pane.querySelector(".err").textContent = e.message; }
    };
  }

  async function openAgent(key) {
    const el = dlg();
    el.innerHTML = shell("Loading…", `<p class="faint">${icon("cycle")}Reading the agent's records…</p>`);
    let a; try { a = await api(`${B}/agents/${encodeURIComponent(key)}`); } catch (e) { return failBox(el, e); }
    const row = (l, v) => v ? `<div><dt>${esc(l)}</dt><dd>${v}</dd></div>` : "", r = a.last_run, time_ = ts => ts ? esc(ago(ts)) : "";
    el.innerHTML = shell(`${esc(a.name)} <small class="faint">${esc(a.role || "")} · ${esc(a.system)}</small>`,
      `<div class="ctlo-dec"><b>${esc(a.next.label)}</b><p>${icon("right")}${esc(a.next.next)}</p></div>
       <dl class="ctlo-adl">
        ${row("Mission and objective", a.mission ? `<button type="button" class="linkbtn" data-ctlo-mission="${esc(a.mission.ref)}">${esc(a.mission.title)}</button>: ${esc(a.mission.objective)}
              <small class="faint">objective progress ${a.mission.progress == null ? "–" : a.mission.progress + "%"} · official ${esc(a.mission.official.text)}</small>` : `<span class="faint">Not on a competition team</span>`)}
        ${row("Current task", a.task ? `${badge(TONE[a.task.state], a.task.state[0] + a.task.state.slice(1).toLowerCase())} ${esc(a.task.title)} <button type="button" class="linkbtn" data-ctlo-graph="${esc(a.task.ref)}">trace</button>
              <small class="faint">${esc(a.task.deliverable || "")}</small>` : `<span class="faint">${a.idle ? "Idle: no task assigned and nothing running" : "No open task"}</span>`)}
        ${row("Latest run", r ? `${badge(r.status === "done" ? "clear" : r.status === "running" ? "new" : "scam", r.status)} ${esc(r.title || r.kind)} <small class="faint">${time_(r.started)} · ${esc(r.model || "no model")} · ${tok(r.tokens)} tokens${r.score != null ? ` · score ${Math.round(r.score)}` : ""}${r.corr ? ` · trace ${esc(r.corr)}` : ""}</small>${r.error ? `<small class="bad">${esc(r.error)}</small>` : ""}` : `<span class="faint">It has never run</span>`)}
        ${row("Models and tools (7 days)", `${a.models.map(m => `${esc(m.model)} ×${m.runs}`).join(", ") || "no model run"}${a.tools.length ? `<small class="faint">${a.tools.map(t => `${esc(t.name)} ×${t.n}${t.errors ? ` (${t.errors} failed)` : ""}`).join(" · ")}</small>` : ""}`)}
        ${a.sandbox ? row("Sandbox", `${a.sandbox.runs_7d} runs this week, ${a.sandbox.failed_7d} couldn't run${a.sandbox.last ? `<small class="faint">last: ${esc(a.sandbox.last.status)} ${time_(a.sandbox.last.started)}${a.sandbox.last.error ? ` · ${esc(a.sandbox.last.error)}` : ""}</small>` : ""}`) : ""}
        ${row("Evaluation", `${a.evaluation.scored} of ${a.evaluation.of} runs scored${a.evaluation.avg != null ? `, average ${a.evaluation.avg}` : ""}${a.evaluation.recent.length ? `<small class="faint">${a.evaluation.recent.map(x => `${Math.round(x.score)}`).join(" · ")} (latest first)</small>` : ""}`)}
        ${row("Cost and budget", `${tok(a.cost.tokens_24h)} tokens in 24 h · ${tok(a.cost.tokens_7d)} in 7 days${a.cost.usd_7d ? ` · $${a.cost.usd_7d}` : ""}
              <small class="faint">${a.cost.limit ? `own limit ${tok(a.cost.limit.spent)} of ${tok(a.cost.limit.tokens)} per ${esc(a.cost.limit.period)}` : "no limit of its own"}${a.cost.team_left != null ? ` · ${tok(a.cost.team_left)} left in its team's 24-hour budget` : ""}</small>`)}
       </dl>
       <h4>Earlier attempts that failed</h4>${a.failures.length ? `<ul class="ctlo-list">${a.failures.map(f => `<li>${badge("scam", f.cls)}<span>${esc(f.title)}<small>${esc(f.error || "no error text")}</small><small class="faint">${time_(f.started)} · recovery: ${esc(f.recovery)}</small></span></li>`).join("")}</ul>` : `<p class="faint">None in its last 40 runs.</p>`}
       <h4>Versions and improvements</h4>${a.versions.length ? `<ul class="ctlo-list">${a.versions.map(v => `<li><span>${esc(v.what)}<small class="faint">${esc(v.source || "")}${v.by ? ` · ${esc(v.by)}` : ""} · ${time_(v.ts)}</small></span></li>`).join("")}</ul>` : `<p class="faint">No version or improvement on record.</p>`}`);
  }

  // one task's own graph: columns by what the node is, not the whole organization
  const COLS = [["mission", "Mission"], ["task", "Task"], ["work", "Agent · runs · sandbox · files"], ["means", "Model · tool calls"], ["evaluator", "Evaluator"], ["result", "Result"]];
  const COL_OF = { mission: "mission", task: "task", agent: "work", run: "work", sandbox: "work", file: "work", model: "means", tool: "means", evaluator: "evaluator", result: "result" };
  const NIC = { mission: "target", task: "list", agent: "bot", run: "zap", sandbox: "server", file: "note", model: "chips", tool: "key", evaluator: "shield", result: "check" };
  async function openGraph(ref) {
    const el = dlg("ctlo-gdlg");
    el.innerHTML = shell("Loading…", `<p class="faint">${icon("cycle")}Tracing the task…</p>`);
    let g; try { g = await api(`${B}/tasks/${encodeURIComponent(ref)}/graph`); } catch (e) { return failBox(el, e); }
    const bad = s => ["failed", "error", "timeout", "lost", "missing", "FAILED", "BLOCKED"].includes(s), ok = s => ["done", "VERIFIED"].includes(s);
    const lbl = {}; g.edges.forEach(e => { lbl[e.to] = lbl[e.to] || e.label; });
    el.innerHTML = shell(`${icon("route")}${esc(g.title)} ${badge(TONE[g.state], g.state[0] + g.state.slice(1).toLowerCase())}`,
      `<p class="faint small">This task's own neighbourhood: what it serves, who worked it on which model with which tools, where it ran, what it wrote, who judged it and the result. The whole organization's graph is the Unified control panel.</p>
       <div class="ctlo-graph">${COLS.map(([k, l]) => { const ns = g.nodes.filter(n => COL_OF[n.kind] === k);
         return `<section><h4>${esc(l)}</h4>${ns.map(n => `<div class="ctlo-node k-${n.kind} ${bad(n.state) ? "bad" : ok(n.state) ? "ok" : ""}" title="${esc(n.detail)}">${icon(NIC[n.kind] || "info")}<span><b>${esc(n.label)}</b>
           <small class="faint">${esc([lbl[n.id], n.state && n.kind !== "result" && n.kind !== "task" ? n.state : ""].filter(Boolean).join(" · "))}</small>${n.detail ? `<small>${esc(n.detail)}</small>` : ""}</span></div>`).join("") || `<p class="faint small">–</p>`}</section>`; }).join("")}</div>
       <div class="row end"><button type="button" class="btn sm" data-ctlo-go="topology">${icon("layers")}Unified control panel</button></div>`);
  }

  document.addEventListener("click", async e => {
    const t = e.target, q = s => t.closest?.(s);
    let b;
    if ((b = q("[data-ctlo-agent]"))) { e.preventDefault(); return openAgent(b.dataset.ctloAgent); }
    if (!q(".ctlo, .ctlo-dlg")) return;
    const el = document.getElementById("ctlo-dlg");
    if (q("[data-ctlo-x]")) return el?.close();
    if (q("[data-ctlo-refresh]")) { data = null; redraw(); return load(true); }
    if (q("[data-ctlo-allq]")) { allQ = !allQ; return redraw(); }
    if ((b = q("[data-ctlo-recheck]"))) {
      b.disabled = true;
      try { const r = await api(`${B}/readiness/${encodeURIComponent(b.dataset.ctloRecheck)}/refresh`, { method: "POST" }); Auth.toast(`Re-checked ${plural(r.tasks, "task")}`); data = null; load(true); }
      catch (x) { b.disabled = false; Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-risk-accept]"))) {
      const fed = (b.dataset.ctloRiskSrc || "readiness") !== "readiness";  // G5-3: a fed risk holds nothing; accepting records the decision
      if (!(await UI.confirm({ title: "Accept this risk?", body: fed ? "It stays in the register as accepted until its source closes it. Nothing else changes." : "Its tasks may then run without the requirement (Conditional). Critical requirements can't be accepted.", ok: "Accept", icon: "shield", danger: false }))) return;
      b.disabled = true;
      try { await api(`/api/g5/risks/${b.dataset.ctloRiskAccept}/accept`, { method: "POST" }); Auth.toast("Accepted"); data = null; load(true); }
      catch (x) { b.disabled = false; Auth.toast(x.message); }
      return;
    }
    if (q("[data-ctlo-sample]")) return sampleDlg();
    if ((b = q("[data-ctlo-est]"))) {
      const v = parseInt(document.querySelector(`[data-ctlo-estin="${b.dataset.ctloEst}"]`)?.value || "", 10);
      if (!(v >= 1)) return Auth.toast("Give the estimated tokens (at least 1)");
      b.disabled = true;
      try { await api(`/api/g5/unmetered/${b.dataset.ctloEst}`, { method: "POST", body: { tokens: v, note: "" } }); Auth.toast("Estimate recorded"); loadUnm(); }
      catch (x) { b.disabled = false; Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-sv]"))) {  // a person's verdict on one sampled agent approval (P3, D-023)
      b.disabled = true;
      try {
        const note = b.dataset.ctloSv === "disagree" ? (document.getElementById(`ctlo-sn-${b.dataset.task}`)?.value || "") : "";
        sampleRender(await api(`${B}/verify-sample/${b.dataset.task}`, { method: "POST", body: { verdict: b.dataset.ctloSv, note } }));
        data = null; load(true);
      } catch (x) { b.disabled = false; Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-risk-verify]"))) {
      const d = dlg("ctlo-vdlg");
      d.innerHTML = `<form method="dialog" class="ctlo-vf"><h3>Verify a credential</h3><p class="faint small">Say how you verified it works. It holds for 7 days while the credential stays the same (24 hours for one this server can't see); a changed credential voids it.</p>
        <label for="ctlo-vnote">How you verified it</label><textarea id="ctlo-vnote" rows="3" maxlength="500" required></textarea>
        <div class="row end"><button type="button" class="btn" data-ctlo-x>Cancel</button><button type="submit" class="btn primary" data-ctlo-vgo="${b.dataset.ctloRiskVerify}">Verify</button></div></form>`;
      d.querySelector("#ctlo-vnote").focus();
      return;
    }
    if ((b = q("[data-ctlo-risk-approve]"))) {
      const d = dlg("ctlo-vdlg");
      d.innerHTML = `<form method="dialog" class="ctlo-vf"><h3>Approve an external action</h3><p class="faint small">For this task only, as it reads now, once: it is used up when the task starts, and lapses after 24 hours. Any change to the task voids it.</p>
        <label for="ctlo-aact">The action you approve</label><input id="ctlo-aact" maxlength="200" required placeholder="e.g. push the image to the private repo">
        <div class="row end"><button type="button" class="btn" data-ctlo-x>Cancel</button><button type="submit" class="btn primary" data-ctlo-ago="${b.dataset.ctloRiskApprove}">Approve once</button></div></form>`;
      d.querySelector("#ctlo-aact").focus();
      return;
    }
    if ((b = q("[data-ctlo-ago]"))) {
      e.preventDefault();
      const action = document.getElementById("ctlo-aact")?.value.trim();
      if (!action) return Auth.toast("Name the action you approve.");
      try { await api(`/api/g5/risks/${b.dataset.ctloAgo}/approve`, { method: "POST", body: { action } }); el?.close(); Auth.toast("Approved once"); data = null; load(true); }
      catch (x) { Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-vgo]"))) {
      e.preventDefault();
      const note = document.getElementById("ctlo-vnote")?.value.trim();
      if (!note) return Auth.toast("Say how you verified it.");
      try { await api(`/api/g5/risks/${b.dataset.ctloVgo}/verify`, { method: "POST", body: { note } }); el?.close(); Auth.toast("Verified"); data = null; load(true); }
      catch (x) { Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-fold]"))) { fold = fold === b.dataset.ctloFold ? null : b.dataset.ctloFold; try { localStorage.setItem("ctlo.fold", fold || ""); } catch { /* storage off */ } return redraw(); }
    if ((b = q("[data-ctlo-mtab]"))) return drawMission(el, el._m, b.dataset.ctloMtab);
    if ((b = q("[data-ctlo-hyp]"))) return hypForm(el, b.dataset.ctloHyp);
    if ((b = q("[data-ctlo-tech]"))) {
      const ref = encodeURIComponent(el._m.mission.ref), id = b.dataset.id, act = b.dataset.ctloTech;
      if (act === "reproduce" && !confirm("Put its reproduction on the team's board? The team builds it in its sandbox as its own candidate and measures it on the frozen suite; that work spends the team's tokens.")) return;
      let note = "";
      if (act === "reject") { note = prompt("Reject this technique. What was learned? (optional)") ; if (note === null) return; }
      b.disabled = true;
      try { el._c = await api(`${B}/missions/${ref}/techniques/${id}/${act === "reproduce" ? "reproduce" : "decide"}`, { method: "POST", body: act === "reproduce" ? {} : { decision: act, note: note || "" } });
            drawMission(el, el._m, "competitors"); Auth.toast(act === "reproduce" ? "On the team's board" : act === "adopt" ? "Adopted" : "Rejected"); data = null; load(true); }
      catch (x) { b.disabled = false; Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-mission]"))) { e.preventDefault(); return openMission(b.dataset.ctloMission, b.dataset.tab || "objective"); }
    if ((b = q("[data-ctlo-graph]"))) { e.preventDefault(); return openGraph(b.dataset.ctloGraph); }
    if ((b = q("[data-ctlo-crit]"))) return critForm(el, b.dataset.ctloCrit);
    if ((b = q("[data-ctlo-critdrop]"))) {
      try { drawMission(el, await api(`${B}/missions/${encodeURIComponent(el._m.mission.ref)}/criteria/${encodeURIComponent(b.dataset.ctloCritdrop)}`, { method: "DELETE" }), "objective"); data = null; load(true); }
      catch (x) { Auth.toast(x.message); }
      return;
    }
    if ((b = q("[data-ctlo-node]"))) { if (typeof Control !== "undefined" && Control.go) Control.go(b.dataset.ctloNode); return; }
    if ((b = q("[data-ctlo-go]"))) { el?.open && el.close(); return go(b.dataset.ctloGo); }
  });

  return { section, refresh: () => { data = null; load(true); }, mission: openMission, agent: openAgent, graph: openGraph };
})();
