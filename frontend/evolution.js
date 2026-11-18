/* Evolution Lab (AXoR 5.0; evolution.py /api/evolution, evolution.css, prefix evo-): the Evolution Engine's page.
   Observe → Propose → Experiment → Evaluate → Promote → Version & rollback. A change is promoted only with measured evidence:
   its candidate and the current version answer the same benchmark cases and an independent judge scores them blind. Your own
   agents' configuration changes run and apply here; every other target records its evidence and decision here and is changed
   on its own page. The policy (what the engine may do by itself) is on Governance. Cards, pills and KPIs reuse command.css
   (occ-) and hubs.css (axh-). */
const Evolution = (() => {
  const B = "/api/evolution";
  const STATE = { proposed: ["s-info", "Proposed", "bulb"], testing: ["s-warn", "Testing", "cycle"], verified: ["s-ok", "Verified", "check"],
                  not_better: ["s-off", "Not better", "minus"], failed: ["s-crit", "Failed", "alert"], promoted: ["s-ok", "Promoted", "rocket"],
                  rolled_back: ["s-warn", "Rolled back", "undo"], rejected: ["s-off", "Rejected", "ban"], answered: ["s-ok", "Answered", "check"] };
  const TABS = [["proposals", "sparkle", "Proposals"], ["benchmarks", "target", "Benchmarks"], ["agents", "bot", "Agents"], ["signals", "eye", "Signals"],
                ["loops", "cycle", "Other loops"], ["audit", "list", "Audit"]];
  const SYS = { hub: "Your agents", builtin: "Built-in", workforce: "Workforce", company: "Company", teams: "Competition teams", workflow: "Workflow", hq: "Agent HQ" };
  let d = null, err = "", on = false, timer = null, tab = "proposals", filt = "all", focus = null, wired = false, sig = "";
  try { tab = localStorage.getItem("evo.tab") || tab; } catch {}

  const root = () => $("#evo-root");
  const pill = (cls, text, ic) => `<span class="occ-pill ${cls}">${ic ? icon(ic) : "<i></i>"}${esc(text)}</span>`;
  const st = s => STATE[s] || ["s-off", s, "info"];
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : String(Math.round(n));
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const empty = t => `<p class="occ-empty">${t}</p>`;
  const signed = x => x == null ? "–" : `${x > 0 ? "+" : ""}${fmtNum(x, 1)}`;

  // ---------- data ----------
  async function load() {
    try { d = await api(B); err = ""; } catch (e) { err = e.message; if (e.status === 403) d = null; }
    const c = document.getElementById("c-evolution"); if (c && d) c.textContent = d.counts.verified || "";
    if (on) draw();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!on) return;
    const busy = d?.proposals?.some(p => p.status === "testing" && !p.progress?.trial);  // a team agent's trial lasts days: no fast polling for it
    timer = setTimeout(() => { if (!document.hidden && on) load(); else schedule(); }, busy ? 3000 : 30000);
  }

  // ---------- pieces ----------
  function evidence(e, compact) {
    if (!e) return `<span class="faint small">No evidence yet: run its experiment${compact ? "" : " (or record measurements made elsewhere)"}.</span>`;
    const max = 100, w = x => Math.max(1.5, Math.min(100, (x || 0) / max * 100)).toFixed(1);
    return `<div class="evo-ev ${e.verified ? "ok" : "no"}">
      <div class="evo-bars" role="img" aria-label="Baseline ${e.baseline}, candidate ${e.candidate} out of 100">
        <span class="evo-bar-l">Current</span><span class="evo-bar-t"><i class="b" style="width:${w(e.baseline)}%"></i></span><b class="num">${e.baseline ?? "–"}</b>
        <span class="evo-bar-l">Candidate</span><span class="evo-bar-t"><i class="c" style="width:${w(e.candidate)}%"></i></span><b class="num">${e.candidate ?? "–"}</b>
      </div>
      <p class="small"><b class="num ${e.delta > 0 ? "up" : e.delta < 0 ? "down" : ""}">${signed(e.delta)} pts</b> on ${plural(e.cases, "case")} · won ${e.wins}, lost ${e.losses}, tied ${e.ties}
        · needs +${fmtNum(e.margin, 0)} on ${e.min_cases}${e.source === "recorded" ? ` · recorded: ${esc(e.test_set || "")}` : e.model ? ` · ${esc(e.model)}` : ""}${e.tokens ? ` · ${tok(e.tokens)} tokens` : ""}</p>
      ${e.why?.length ? `<p class="small evo-why">${icon("info")}${esc(e.why.join("; "))}</p>` : ""}</div>`;
  }
  function actions(p) {
    const b = [];
    const mine = p.applies_here, team = teamAgent(p);
    const more = `<button type="button" class="btn sm ghost" data-evo="detail" data-id="${p.id}">${icon("eye")}Details</button>`;
    if (p.gap) {  // a gap a mission measured (L5.5): answered with a proposal for one of the team's agents, never tested or promoted itself
      if (p.status === "proposed") b.push(`<button type="button" class="btn sm primary" data-evo="answer" data-id="${p.id}">${icon("edit")}Answer</button>`,
        `<button type="button" class="btn sm ghost" data-evo="reject" data-id="${p.id}">${icon("ban")}Reject</button>`);
      return b.join("") + more;
    }
    if (p.status === "testing" && p.progress?.trial) return `<span class="evo-prog">${icon("cycle")}On trial since ${ago(p.progress.trial.started)}</span>
      <button type="button" class="btn sm" data-evo="trial-end" data-id="${p.id}">${icon("check")}End trial</button>${more}`;
    if (p.status === "testing") return `<span class="evo-prog">${icon("cycle")}${p.progress ? `${p.progress.done} of ${p.progress.total} answers` : "starting"}</span>`;
    if (["proposed", "not_better", "failed", "verified"].includes(p.status)) {
      if (team) { if (p.status !== "verified") b.push(`<button type="button" class="btn sm" data-evo="trial-start" data-id="${p.id}">${icon("play")}${p.evidence ? "Trial again" : "Start trial"}</button>`); }
      else if (mine) b.push(`<button type="button" class="btn sm" data-evo="run" data-id="${p.id}" ${p.benchmark_id ? "" : "disabled title=\"Pick a benchmark first\""}>${icon("play")}${p.evidence ? "Run again" : "Run experiment"}</button>`,
        `<button type="button" class="btn sm ghost" data-evo="bench-pick" data-id="${p.id}" title="Which benchmark its experiment runs on">${icon("target")}${esc(benchName(p.benchmark_id))}</button>`);
      else b.push(`<button type="button" class="btn sm" data-evo="evidence" data-id="${p.id}">${icon("chart")}Record evidence</button>`);
    }
    if (p.status === "verified") b.push(`<button type="button" class="btn sm primary" data-evo="promote" data-id="${p.id}">${icon("rocket")}Promote</button>`);
    if (p.status === "promoted") b.push(`<button type="button" class="btn sm" data-evo="rollback" data-id="${p.id}">${icon("undo")}Roll back${p.before_version ? ` to v${p.before_version}` : ""}</button>`);
    if (["proposed", "not_better", "failed", "verified"].includes(p.status)) b.push(`<button type="button" class="btn sm ghost" data-evo="reject" data-id="${p.id}">${icon("ban")}Reject</button>`);
    return b.join("") + more;
  }
  const teamAgent = p => (p.target_key || "").startsWith("teams:") && p.risk === "config";
  const origin = p => p.origin === "drafted" ? "drafted by a model" : p.origin === "manual" ? "by you" : p.origin === "mission" ? "measured by a mission's cycle"
    : p.origin === "answer" ? `answers gap #${p.answers_gap}` : p.origin === "upgrade" ? "screened by an upgrade sprint" : esc(p.origin);
  const num = x => x == null ? "–" : typeof x === "number" ? fmtNum(x, Number.isInteger(x) ? 0 : 4) : esc(String(x));
  function gapCard(p) {
    const s = st(p.status), g = p.signal || {}, m = g.measure || {}, v = g.values || {}, cyc = g.cycles || [], ans = p.answers || [];
    return `<li class="card occ-card evo-prop ${focus === p.id ? "focus" : ""}" id="evo-p${p.id}">
      <div class="evo-prop-h"><div><h3>${esc(p.title)}</h3>
        <p class="small faint">${esc(p.target_name)} · ${esc(p.kind_label)} · #${p.id} · ${origin(p)} · ${ago(p.updated)}</p></div>
        <div class="evo-pills">${pill("src", g.label === "technical" ? "Technical gap" : "Measured gap", "target")}${pill(s[0], s[1], s[2])}</div></div>
      <p class="evo-hyp">${esc((p.change || {}).text || "")}</p>
      <p class="small faint">Mission ${esc((g.mission || "").replace("mx:", "#"))}, ${cyc.length === 1 ? `cycle ${cyc[0].n}` : `cycles ${cyc.map(c => c.n).join(", ")}`} · ${esc(m.metric || m.id || "")} now ${num(v.current)}, target ${esc(m.op || "")} ${num(m.target)}
        · rests on ${esc(String((g.evidence || {}).basis || "").replaceAll("_", " "))}${g.label === "technical" ? " (the release's frozen measuring job; not a competition result)" : ""}${(g.risks || []).length ? ` · ${plural(g.risks.length, "open risk row")} for the team` : ""}</p>
      <p class="small">${ans.length ? `Answers: ${ans.map(a => `#${a.id} ${esc(a.target_name)} (${esc(st(a.status)[1].toLowerCase())}${a.after_version ? `, v${a.before_version} → v${a.after_version}` : ""})`).join(" · ")}`
        : p.status === "proposed" ? "No answer yet. It says what was measured, not what to change: answer it with new instructions for one of the team's agents." : ""}</p>
      ${p.note ? `<p class="small evo-why">${icon("info")}${esc(p.note)}</p>` : ""}
      <div class="row evo-acts">${actions(p)}</div></li>`;
  }
  function proposalCard(p) {
    if (p.gap) return gapCard(p);
    const s = st(p.status), ch = p.change || {};
    return `<li class="card occ-card evo-prop ${focus === p.id ? "focus" : ""}" id="evo-p${p.id}">
      <div class="evo-prop-h"><div><h3>${esc(p.title)}</h3>
        <p class="small faint">${esc(p.target_name)} · ${esc(p.kind_label)} · #${p.id} · ${origin(p)} · ${ago(p.updated)}</p></div>
        <div class="evo-pills">${pill(p.risk === "config" ? "src" : "s-warn", p.risk_label, p.risk === "config" ? "sliders" : "lock")}${pill(s[0], s[1], s[2])}</div></div>
      ${p.hypothesis ? `<p class="evo-hyp">${esc(p.hypothesis)}</p>` : ""}
      <p class="small faint">${ch.instructions ? "Changes the instructions" : ""}${ch.instructions && ch.skills ? " and " : ""}${ch.skills ? `sets ${plural(ch.skills.length, "skill")}` : ""}${ch.text ? esc(ch.text) : ""}
        ${!p.applies_here ? ` · applied on its own page after you decide` : ""}${p.decided_by ? ` · decided by ${esc(p.decided_by)}` : ""}${p.after_version ? ` · v${p.before_version} → v${p.after_version}` : ""}</p>
      ${!p.evidence && teamAgent(p) ? `<span class="faint small">No evidence yet: start its trial. What counts is the team's benchmark jobs during the trial, on a candidate the team froze during it.</span>` : evidence(p.evidence, true)}
      ${p.note ? `<p class="small evo-why">${icon("info")}${esc(p.note)}</p>` : ""}
      <div class="row evo-acts">${actions(p)}</div></li>`;
  }
  const loopStep = (ic, name, n, sub) => `<div class="evo-step"><span class="evo-step-i">${icon(ic)}</span><b>${esc(name)}</b><span class="num">${n}</span><small>${esc(sub)}</small></div>`;
  function loop() {
    const l = d.loop;
    return `<section class="card occ-card evo-loop" aria-label="The self-evolution loop">
      ${loopStep("eye", "Observe", l.observe, "weak spots with evidence")}<span class="evo-arr" aria-hidden="true">${icon("right")}</span>
      ${loopStep("bulb", "Propose", d.proposals.length, "changes proposed")}<span class="evo-arr" aria-hidden="true">${icon("right")}</span>
      ${loopStep("play", "Experiment", l.experiment, "measured, same cases")}<span class="evo-arr" aria-hidden="true">${icon("right")}</span>
      ${loopStep("check", "Evaluate", l.verified, "beat the current version")}<span class="evo-arr" aria-hidden="true">${icon("right")}</span>
      ${loopStep("rocket", "Promote", l.promoted, l.avg_gain != null ? `${signed(l.avg_gain)} pts on average` : "with evidence only")}<span class="evo-arr" aria-hidden="true">${icon("right")}</span>
      ${loopStep("undo", "Version & rollback", l.rolled_back, "rolled back")}
    </section>`;
  }

  // ---------- tabs ----------
  function proposals() {
    const counts = d.proposals.reduce((a, p) => (a[p.status] = (a[p.status] || 0) + 1, a), {});
    if (filt !== "all" && !counts[filt]) filt = "all";
    const rows = d.proposals.filter(p => filt === "all" || p.status === filt);
    const chips = Object.keys(counts).length > 1 ? `<div class="occ-filters" role="group" aria-label="Filter by status"><button type="button" class="chip" data-evo-f="all" aria-pressed="${filt === "all"}">All <b>${d.proposals.length}</b></button>
      ${STATES().filter(k => counts[k]).map(k => `<button type="button" class="chip" data-evo-f="${k}" aria-pressed="${filt === k}">${icon(st(k)[2])}${st(k)[1]} <b>${counts[k]}</b></button>`).join("")}</div>` : "";
    return `${chips}${!d.proposals.length ? empty(`No proposal yet. Start from a signal, let a model draft one for an agent of yours, or write your own. Nothing is adopted until an experiment shows it beats the current version.
        <span class="row"><button type="button" class="btn sm primary" data-evo="new">${icon("plus")}New proposal</button><button type="button" class="btn sm" data-evo="bench-new">${icon("target")}New benchmark</button></span>`)
      : `<ul class="evo-list">${rows.map(proposalCard).join("")}</ul>`}`;
  }
  const STATES = () => Object.keys(STATE);
  function benchmarks() {
    const name = k => d.agents.find(a => a.key === k)?.name || k || "Any agent";
    return `<div class="row evo-tools"><button type="button" class="btn sm primary" data-evo="bench-new">${icon("plus")}New benchmark</button>
        <span class="faint small">A benchmark is the fixed test set both versions answer: realistic requests and what a good answer contains.</span></div>
      ${!d.benchmarks.length ? empty("No benchmark yet. Experiments need one: a few cases for the agent you want to improve.")
        : `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Benchmark</th><th>For</th><th class="r">Cases</th><th>Origin</th><th>Updated</th><th></th></tr></thead><tbody>
        ${d.benchmarks.map(b => `<tr><td><b>${esc(b.name)}</b><br><small class="faint">${esc((b.cases[0]?.prompt || "").slice(0, 90))}</small></td><td>${esc(name(b.target_key))}</td><td class="r num">${b.cases.length}</td>
          <td>${esc(b.origin || "manual")}</td><td class="faint">${ago(b.updated)}</td>
          <td class="r"><button type="button" class="btn sm" data-evo="bench-edit" data-id="${b.id}">${icon("edit")}Edit</button>
            <button type="button" class="btn sm" data-evo="bench-draft" data-id="${b.id}" title="A model writes more cases; review them before you use them">${icon("sparkle")}Draft cases</button>
            <button type="button" class="iconbtn" data-evo="bench-del" data-id="${b.id}" aria-label="Delete ${esc(b.name)}">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>`}`;
  }
  function agents() {
    const mine = d.agents, others = d.registry;
    return `<p class="faint small evo-note">Each agent is a versioned capability package: core, model, skills, tools, memory, knowledge, evaluation and policies. Your own agents' configuration evolves here; the others evolve on their own pages.</p>
      ${!mine.length ? empty(`You have no agents of your own yet. <button type="button" class="linkbtn" data-evo-to="agents">Create one in Agents</button>`)
        : `<div class="evo-agents">${mine.map(a => `<button type="button" class="card evo-agent" data-evo="pkg" data-key="${esc(a.key)}"><b>${esc(a.name)}</b><small>${esc(a.role || "Agent")}</small>
            <span class="small faint">${plural(a.versions, "version")} · ${plural(a.skills, "skill")}${a.level != null ? ` · L${a.level}` : ""}</span></button>`).join("")}</div>`}
      ${others.length ? `<details class="evo-others"><summary>${plural(others.length, "agent")} in your other systems</summary>
        <div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Agent</th><th>System</th><th>Where</th><th></th></tr></thead><tbody>
        ${others.map(a => `<tr><td>${esc(a.name)}<br><small class="faint">${esc(a.role || "")}</small></td><td>${esc(SYS[a.system] || a.system)}</td><td class="faint">${esc(a.place || "")}</td>
          <td class="r"><button type="button" class="btn sm" data-evo="pkg" data-key="${esc(a.key)}">${icon("eye")}Package</button></td></tr>`).join("")}</tbody></table></div></details>` : ""}`;
  }
  function signals() {
    return !d.signals.length ? empty("No weak spot found in the last 14 days: no repeated failures, low scores, thumbs-down or failed tests. Signals come from the run ledger, chat ratings and Studio tests.")
      : `<ul class="occ-list evo-sigs">${d.signals.map(s => `<li><div class="occ-need-t"><b>${esc(s.name)}</b> <small class="faint">${esc(SYS[s.system] || s.system)}</small>
          <ul class="small">${s.evidence.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
          ${s.mine ? `<button type="button" class="btn sm" data-evo="draft" data-key="${esc(s.key)}">${icon("sparkle")}Draft a fix</button>` : ""}
          <button type="button" class="btn sm ghost" data-evo="new" data-key="${esc(s.key)}">${icon("plus")}Propose</button></li>`).join("")}</ul>`;
  }
  function loops() {
    const L = d.loops, go = x => x ? `data-evo-go='${esc(JSON.stringify(x))}'` : "";
    return `<p class="faint small evo-note">These systems run their own improvement loops with their own approval rules; each row opens the page that decides it.</p>
      ${!L.improvements.length && !L.watches.length && !L.sprints.length ? empty("No other loop has produced anything yet: Workforce improvements, the Competition teams' Workflow (administrators) and Upgrade sprints show here.")
      : `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Agent</th><th>System</th><th>Change</th><th>Result</th><th>Status</th><th>Updated</th></tr></thead><tbody>
        ${L.improvements.map(x => `<tr><td><button type="button" class="linkbtn" ${go(x.go)}>${esc(x.who)}</button></td><td>${esc(x.system === "teams" ? "Workflow" : "Workforce")}</td><td>${esc(x.change || "–")}</td>
          <td class="faint">${esc(x.result || "–")}</td><td>${pill(/promoted|applied|kept/.test(x.status) ? "s-ok" : /fail|reject/.test(x.status) ? "s-crit" : "s-info", (x.status || "").replace(/_/g, " "))}</td><td class="faint">${ago(x.ts)}</td></tr>`).join("")}
        ${L.watches.map(x => `<tr><td><button type="button" class="linkbtn" ${go(x.go)}>${esc(x.who)}</button></td><td>Workflow watch</td><td class="num">v${x.from ?? "?"} → v${x.to ?? "?"}</td>
          <td class="faint">${esc(x.result || "–")}</td><td>${pill(x.status === "kept" ? "s-ok" : x.status === "rolled_back" ? "s-crit" : "s-warn", (x.status || "").replace(/_/g, " "))}</td><td class="faint">${ago(x.ts)}</td></tr>`).join("")}
        ${L.sprints.map(x => `<tr><td><button type="button" class="linkbtn" ${go(x.go)}>${esc(x.where)}</button></td><td>Upgrade sprint</td><td>${plural(x.versions, "version")} made</td>
          <td class="faint">${esc(x.note || "–")}</td><td>${pill(x.status === "running" ? "s-warn" : "s-info", x.status || "")}</td><td class="faint">${ago(x.ts)}</td></tr>`).join("")}</tbody></table></div>`}
      ${L.errors?.length ? `<p class="faint small">${icon("info")}${esc(L.errors.join(" · "))}</p>` : ""}`;
  }
  function audit() {
    return !d.audit.length ? empty("Nothing recorded yet. Every proposal, experiment, promotion, rollback and policy change is written here.")
      : `<ul class="evo-audit">${d.audit.map(a => `<li><span class="faint num">${new Date(a.ts * 1000).toLocaleString()}</span><b>${esc(a.actor)}</b><code>${esc(a.action)}</code><span>${esc(a.detail || a.target)}</span></li>`).join("")}</ul>`;
  }

  // ---------- frame ----------
  function draw() {
    const el = root(); if (!el) return;
    const k = JSON.stringify([d, err, tab, filt, focus]);
    if (k === sig) return; sig = k;
    if (!d) {
      el.innerHTML = err ? `<div class="card empty">${esc(err)} <button type="button" class="linkbtn" data-evo="refresh">Try again</button></div>`
        : `<div class="stats">${Loading.tiles(5)}</div>`;
      return;
    }
    const c = d.counts, pol = d.policy, y = scrollY;
    const kpi = (ic, label, v, sub, tone) => `<div class="stat occ-kpi ${tone ? "t-" + tone : ""}"><div class="label">${icon(ic)}${label}</div><div class="value">${esc(String(v))}</div><div class="sub">${esc(sub || "")}</div></div>`;
    el.innerHTML = `<div class="occ evo"><div class="occ-head"><div><p class="occ-kicker">${icon("cycle")}AXoR 5.0 · Evolution Engine</p><h1 class="page">Evolution Lab</h1>
        <p class="lead">Improves what makes future work succeed: agents, skills, teams, workflows and the organization. A change is adopted only when it measurably beats the current version on the same cases, judged blind, and every promotion can be rolled back.
          <span class="faint">Updated ${ago(d.at)}</span></p></div>
        <div class="row"><button type="button" class="btn sm primary" data-evo="new">${icon("plus")}New proposal</button><button type="button" class="btn sm" data-evo="bench-new">${icon("target")}New benchmark</button>
          <button type="button" class="btn sm" data-evo="refresh">${icon("cycle")}Refresh</button></div></div>
      <div class="evo-policy card"><span>${icon("shield")}Policy: <b>${esc(pol.label)}</b> · promote at +${fmtNum(pol.margin, 0)} pts on ${pol.min_cases}+ cases · engine budget ${tok(d.loop.spent_today)} of ${tok(pol.daily_tokens)} tokens today</span>
        <button type="button" class="linkbtn" data-evo-to="governance">Change in Governance${icon("right")}</button></div>
      <div class="stats occ-kpis">${kpi("eye", "Signals", d.signals.length, "weak spots, 14 days", d.signals.length ? "warn" : "")}
        ${kpi("bulb", "Proposed", c.proposed, `${c.not_better} not better · ${c.rejected} rejected`)}
        ${kpi("cycle", "Testing", c.testing, "experiments running", c.testing ? "info" : "")}
        ${kpi("check", "Verified", c.verified, "waiting for a decision", c.verified ? "ok" : "")}
        ${kpi("rocket", "Promoted", c.promoted, d.loop.avg_gain != null ? `${signed(d.loop.avg_gain)} pts on average` : "with evidence only")}
        ${kpi("undo", "Rolled back", c.rolled_back, "back to the version before")}</div>
      ${loop()}
      <nav class="axh-tabs" role="tablist">${TABS.map(([k, ic, l]) => { const n = { proposals: d.proposals.length, benchmarks: d.benchmarks.length, agents: d.agents.length, signals: d.signals.length, loops: d.loops.improvements.length + d.loops.watches.length + d.loops.sprints.length }[k];
        return `<button type="button" role="tab" data-evo-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}${n ? ` <b>${n}</b>` : ""}</button>`; }).join("")}</nav>
      <div class="evo-tab">${{ proposals, benchmarks, agents, signals, loops, audit }[tab]?.() || proposals()}</div></div>`;
    if (Math.abs(scrollY - y) > 1) scrollTo(0, y);
    if (focus) { const f = $(`#evo-p${focus}`); if (f) { f.scrollIntoView({ block: "center" }); focus = null; } }
  }

  // ---------- dialogs ----------
  function dlg(title, body, ok, run, wide = false) {
    let el = document.getElementById("evo-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "evo-dlg"; document.body.append(el); }
    el.className = `modal evo-dlg ${wide ? "wide" : ""}`;
    el.innerHTML = `<form method="dialog" class="co-form" novalidate><div class="evo-dh"><h3>${title}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      ${body}<p class="err" role="alert"></p>${ok ? `<div class="row end"><button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn primary">${ok}</button></div>` : ""}</form>`;
    const f = el.querySelector("form"), e = f.querySelector(".err");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    f.onsubmit = async ev => {
      ev.preventDefault(); if (!run) return el.close();
      const btn = f.querySelector("[type=submit]"); btn.classList.add("loading"); btn.disabled = true; e.textContent = "";
      try { const r = await run(new FormData(f), f); if (r !== false) el.close(); }
      catch (x) { e.textContent = x?.message || "Something went wrong."; }
      finally { btn.classList.remove("loading"); btn.disabled = false; }
    };
    el.showModal();
    return { el, f };
  }
  const benchName = id => d?.benchmarks.find(b => b.id === id)?.name || "Pick a benchmark";
  const benchOpts = (sel, key) => `<option value="">No benchmark yet</option>${d.benchmarks.filter(b => !key || !b.target_key || b.target_key === key)
    .map(b => `<option value="${b.id}" ${b.id === sel ? "selected" : ""}>${esc(b.name)} (${plural(b.cases.length, "case")})</option>`).join("")}`;

  async function newProposal(key = "") {
    const opts = [`<optgroup label="Your agents (changed and tested here)">${d.agents.map(a => `<option value="agent|${esc(a.key)}" ${a.key === key ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</optgroup>`,
      d.registry.length ? `<optgroup label="Agents in other systems (decided here, changed on their page)">${d.registry.map(a => `<option value="agent|${esc(a.key)}" ${a.key === key ? "selected" : ""}>${esc(a.name)} · ${esc(SYS[a.system] || a.system)}</option>`).join("")}</optgroup>` : "",
      `<optgroup label="Something else">${Object.entries(d.kinds).filter(([k]) => k !== "agent").map(([k, l]) => `<option value="${k}|">${esc(l)}</option>`).join("")}</optgroup>`].join("");
    const { f } = dlg("New proposal", `<label class="in"><span>What to improve</span><select name="target">${opts}</select></label>
      <label class="in evo-name" hidden><span>Which one (a team, workflow, skill…)</span><input type="text" name="name" maxlength="120" placeholder="e.g. Engineering department"></label>
      <label class="in"><span>The change, in a few words</span><input type="text" name="title" maxlength="160" required placeholder="e.g. Ask for the error message before guessing"></label>
      <label class="in"><span>Hypothesis: why it should help, and what the benchmark should show</span><textarea name="hypothesis" rows="2" maxlength="1500"></textarea></label>
      <div class="evo-mine"><label class="in"><span>Instructions (the candidate version)</span><textarea name="instructions" rows="9" maxlength="8000" placeholder="Loading the current instructions…"></textarea></label>
        <label class="in"><span>Benchmark</span><select name="benchmark"></select></label></div>
      <div class="evo-else" hidden><label class="in"><span>The change in detail</span><textarea name="change" rows="4" maxlength="2000"></textarea></label>
        <label class="in"><span>Kind of change</span><select name="risk">${Object.entries(d.risks).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select></label></div>
      <p class="faint small">${icon("info")}A proposal proves nothing by itself. Your agents' changes run against the current version on the benchmark; other changes need measurements recorded before they can be promoted.</p>`,
      "Create proposal", async fd => {
        const [kind, k] = fd.get("target").split("|"), hub = k.startsWith("hub:");
        const body = { target_kind: kind, target_key: kind === "agent" ? k : (fd.get("name") || "").trim() || d.kinds[kind], title: fd.get("title"), hypothesis: fd.get("hypothesis") || "",
                       risk: hub ? "config" : fd.get("risk"), change: hub ? "" : fd.get("change") || "",
                       instructions: hub ? fd.get("instructions") : null, benchmark_id: hub && fd.get("benchmark") ? +fd.get("benchmark") : null };
        const p = await api(`${B}/proposals`, { method: "POST", body });
        Auth.toast("Proposal created."); tab = "proposals"; focus = p.id; sig = ""; await load();
      }, true);
    const sel = f.querySelector("[name=target]");
    const sync = async () => {
      const [kind, k] = sel.value.split("|"), hub = k.startsWith("hub:");
      f.querySelector(".evo-mine").hidden = !hub; f.querySelector(".evo-else").hidden = hub; f.querySelector(".evo-name").hidden = kind === "agent";
      if (hub) {
        f.querySelector("[name=benchmark]").innerHTML = benchOpts(null, k);
        const first = d.benchmarks.find(b => b.target_key === k); if (first) f.querySelector("[name=benchmark]").value = first.id;
        const ta = f.querySelector("[name=instructions]"); ta.value = ""; ta.placeholder = "Loading the current instructions…";
        try { const a = await api(`/api/studio/agents/${encodeURIComponent(k)}`); if (sel.value.endsWith(k)) { ta.value = a.instructions?.text || ""; ta.placeholder = "The agent's complete new instructions"; } }
        catch { ta.placeholder = "The agent's complete new instructions"; }
      }
    };
    sel.onchange = sync; sync();
  }

  function benchDialog(b) {
    const cases = b?.cases?.length ? b.cases : [{ prompt: "", rubric: "" }];
    const row = (c, i) => `<fieldset class="evo-case"><legend>Case ${i + 1}</legend><label class="in"><span>Request</span><textarea name="p" rows="2" maxlength="3000">${esc(c.prompt)}</textarea></label>
      <label class="in"><span>A good answer contains</span><input type="text" name="r" maxlength="800" value="${esc(c.rubric)}"></label></fieldset>`;
    const { f } = dlg(b ? `Edit ${esc(b.name)}` : "New benchmark", `<label class="in"><span>Name</span><input type="text" name="name" maxlength="120" required value="${esc(b?.name || "")}" placeholder="e.g. Python engineering"></label>
      <label class="in"><span>For agent</span><select name="key"><option value="">Any agent</option>${d.agents.map(a => `<option value="${esc(a.key)}" ${a.key === b?.target_key ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select></label>
      <div class="evo-cases">${cases.map(row).join("")}</div><button type="button" class="btn sm" data-add>${icon("plus")}Add a case</button>
      <p class="faint small">Empty cases are dropped. Keep them fixed once you compare versions: both versions always answer the same cases.</p>`,
      b ? "Save" : "Create benchmark", async fd => {
        const ps = fd.getAll("p"), rs = fd.getAll("r");
        const body = { name: fd.get("name"), target_key: fd.get("key") || "", cases: ps.map((p, i) => ({ id: b?.cases?.[i]?.id, prompt: p, rubric: rs[i] })).filter(c => c.prompt.trim()) };
        await api(b ? `${B}/benchmarks/${b.id}` : `${B}/benchmarks`, { method: b ? "PUT" : "POST", body });
        Auth.toast(b ? "Benchmark saved." : "Benchmark created."); tab = "benchmarks"; sig = ""; await load();
      }, true);
    f.querySelector("[data-add]").onclick = () => { const w = f.querySelector(".evo-cases"); w.insertAdjacentHTML("beforeend", row({ prompt: "", rubric: "" }, w.children.length)); w.lastElementChild.querySelector("textarea").focus(); };
  }

  function evidenceDialog(p) {
    dlg(`Record evidence · ${esc(p.title)}`, `<p class="small faint">Measured outside the lab (a team's validation set, a workflow's runs): one score per case, 0-100, the current version's and the candidate's in the same order. The same rule decides: +${fmtNum(d.policy.margin, 0)} points on ${d.policy.min_cases} or more cases.</p>
      <label class="in"><span>Test set</span><input type="text" name="set" maxlength="200" required placeholder="e.g. the last 6 validation runs"></label>
      <label class="in"><span>Metric</span><input type="text" name="metric" maxlength="60" value="score"></label>
      <div class="row"><label class="in"><span>Current version, per case</span><input type="text" name="b" required placeholder="52, 48, 55"></label>
        <label class="in"><span>Candidate, per case</span><input type="text" name="c" required placeholder="61, 60, 63"></label></div>`,
      "Record", async fd => {
        const nums = s => String(s || "").split(/[\s,;]+/).filter(Boolean).map(Number);
        const b = nums(fd.get("b")), c = nums(fd.get("c"));
        if (b.some(isNaN) || c.some(isNaN)) throw new Error("Use numbers separated by commas.");
        const r = await api(`${B}/proposals/${p.id}/evidence`, { method: "POST", body: { test_set: fd.get("set"), metric: fd.get("metric") || "score", baseline: b, candidate: c } });
        Auth.toast(r.status === "verified" ? "Verified: it can be promoted." : "Not better by the policy's rule."); sig = ""; await load();
      });
  }

  // A gap a mission measured (L5.5) is answered with the complete new instructions for one agent of that team.
  async function answerDialog(id) {
    let p;
    try { p = await api(`${B}/proposals/${id}`); } catch (e) { return Auth.toast(e.message); }
    const ags = p.agents || [];
    if (!ags.length) return Auth.toast("This team has no agents to answer for.");
    const { f } = dlg(`Answer gap #${p.id}`, `<p class="small faint">${esc((p.change || {}).text || p.title)}</p>
      <label class="in"><span>Which agent of ${esc(p.target_name)} changes</span><select name="agent">${ags.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join("")}</select></label>
      <label class="in"><span>The change, in a few words</span><input type="text" name="title" maxlength="160" placeholder="e.g. Benchmark every candidate before approving it"></label>
      <label class="in"><span>Why it should close the gap</span><textarea name="hypothesis" rows="2" maxlength="1500"></textarea></label>
      <label class="in"><span>The agent's complete new instructions</span><textarea name="instructions" rows="10" maxlength="8000" required></textarea></label>
      <p class="faint small">${icon("info")}This makes a proposal for that agent. Nothing changes until its trial measures it on the team's frozen suite and you promote it. Whether the gap closed is what the mission's later cycles measure.</p>`,
      "Create the answer", async fd => {
        const r = await api(`${B}/proposals/${id}/answer`, { method: "POST", body: { agent: +fd.get("agent"), title: fd.get("title") || "", hypothesis: fd.get("hypothesis") || "", instructions: fd.get("instructions") } });
        Auth.toast("Answer created. Start its trial when the team is ready."); tab = "proposals"; focus = r.id; sig = ""; await load();
      }, true);
    const sel = f.querySelector("[name=agent]"), ta = f.querySelector("[name=instructions]");
    const fill = () => { ta.value = ags.find(a => a.id === +sel.value)?.instructions || ""; };
    sel.onchange = fill; fill();
  }

  function gapDetail(p) {
    const g = p.signal || {}, m = g.measure || {}, ev = g.evidence || {}, ans = p.answers || [];
    return `<h4>What ${esc((g.mission || "the mission").replace("mx:", "mission #"))} measured</h4>
      <div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Cycle</th><th class="r">Before</th><th class="r">Measured</th><th class="r">Short by</th></tr></thead>
        <tbody>${(g.cycles || []).map(c => `<tr><td>${c.n}${c.at ? ` · ${ago(c.at)}` : ""}</td><td class="r num">${num(c.previous)}</td><td class="r num">${num(c.current)}</td><td class="r num">${num(c.gap)}</td></tr>`).join("")}</tbody></table></div>
      <p class="small faint">${esc(m.metric || m.id || "")} (${esc(m.source || "")}), target ${esc(m.op || "")} ${num(m.target)} · external evidence: ${esc(String(ev.basis || "").replaceAll("_", " "))}
        ${(g.diagnosis || []).length ? ` · ${esc(g.diagnosis.join(", "))}` : ""}${(g.risks || []).length ? ` · open risk rows for the team: ${g.risks.map(r => `#${r}`).join(", ")}` : ""}${(g.earlier || []).length ? ` · earlier gaps on this measure: ${g.earlier.map(r => `#${r}`).join(", ")}` : ""}</p>
      <h4>Answers</h4>${!ans.length ? empty("None yet.") : `<ul class="evo-vers">${ans.map(a => `<li><b class="num">#${a.id}</b>${pill(st(a.status)[0], st(a.status)[1])}<span>${esc(a.target_name)}: ${esc(a.title)}${a.after_version ? ` · v${a.before_version} → v${a.after_version}` : ""}</span></li>`).join("")}</ul>`}
      <p class="small faint">A gap is never tested or promoted itself. It closes when one of its answers is promoted, and opens again if that promotion is rolled back. A closed gap doesn't mean the measure improved: the mission's later cycles show that.</p>
      ${p.status === "proposed" ? `<div class="row"><button type="button" class="btn sm primary" data-evo="answer" data-id="${p.id}">${icon("edit")}Answer</button></div>` : ""}`;
  }

  async function detail(id) {
    let p;
    try { p = await api(`${B}/proposals/${id}`); } catch (e) { return Auth.toast(e.message); }
    if (p.gap) return dlg(esc(p.title), `<p class="small faint">${esc(p.target_name)} · ${esc(p.kind_label)} · ${pill(st(p.status)[0], st(p.status)[1])}</p>
      <p>${esc((p.change || {}).text || "")}</p>${p.note ? `<p class="small evo-why">${icon("info")}${esc(p.note)}</p>` : ""}${gapDetail(p)}`, "", null, true);
    const ch = p.change || {}, e = p.evidence;
    const cases = {};
    (p.trials || []).forEach(t => (cases[t.case_id] ||= { baseline: [], candidate: [] })[t.arm].push(t));
    dlg(esc(p.title), `<p class="small faint">${esc(p.target_name)} · ${esc(p.kind_label)} · ${esc(p.risk_label)} · ${pill(st(p.status)[0], st(p.status)[1])}</p>
      ${p.hypothesis ? `<p>${esc(p.hypothesis)}</p>` : ""}
      ${ch.instructions ? `<details><summary>Candidate instructions</summary><pre class="evo-pre">${esc(ch.instructions)}</pre></details>` : ""}${ch.text ? `<p>${esc(ch.text)}</p>` : ""}
      ${evidence(e)}
      ${Object.keys(cases).length ? `<h4>Per case (judged blind)</h4><div class="evo-trials">${Object.entries(cases).map(([cid, arms]) => `<div class="evo-trial"><b>${esc(cid)}</b>
        ${["baseline", "candidate"].map(arm => arms[arm].map(t => `<div class="evo-ans ${arm}"><span class="small"><b>${arm === "baseline" ? "Current" : "Candidate"}</b> · ${t.score ?? "failed"}${t.notes ? ` · ${esc(t.notes)}` : ""}${t.error ? ` · ${esc(t.error)}` : ""}</span>
          <details><summary class="small faint">Answer</summary><p class="small evo-pre">${esc(t.answer || "")}</p></details></div>`).join("")).join("")}</div>`).join("")}</div>` : ""}
      <p class="small faint">${p.origin === "drafted" ? "Drafted by a model. " : ""}Created ${ago(p.created)}${p.tested ? ` · measured ${ago(p.tested)}` : ""}${p.promoted ? ` · promoted ${ago(p.promoted)} by ${esc(p.decided_by || "")}` : ""}</p>`, "", null, true);
  }

  async function pkg(key) {
    let p;
    try { p = await api(`${B}/agents/${encodeURIComponent(key)}`); } catch (e) { return Auth.toast(e.message); }
    dlg(`${esc(p.name)} · capability package`, `<p class="small faint">${esc(p.role || "")}${p.level != null ? ` · organization level L${p.level}` : ""}</p>
      <div class="evo-pkg">${p.components.map(c => `<div class="evo-comp"><small>${esc(c.name)}</small><b>${esc(String(c.value))}</b><span class="small faint">${esc(c.detail)}</span></div>`).join("")}</div>
      <h4>Version history</h4>${!p.versions.length ? empty(p.mine ? "No version kept yet: the first save or promotion keeps one." : "Versions of this agent are kept on its own page.")
        : `<ul class="evo-vers">${p.versions.map(v => `<li><b class="num">v${v.version}</b>${v.current ? pill("s-ok", "current") : ""}<span>${esc(v.note || "")}</span>
          ${v.evolution?.evidence ? `<small class="faint">${signed(v.evolution.evidence.delta)} pts on ${v.evolution.evidence.cases} cases</small>` : ""}<small class="faint">${esc(v.author || "")} · ${ago(v.ts)}</small></li>`).join("")}</ul>`}
      <h4>Changes</h4>${!p.proposals.length ? empty("No proposal for this agent yet.") : `<ul class="evo-vers">${p.proposals.map(x => `<li>${pill(st(x.status)[0], st(x.status)[1])}<span>${esc(x.title)}</span>${x.evidence ? `<small class="faint">${signed(x.evidence.delta)} pts</small>` : ""}</li>`).join("")}</ul>`}
      <div class="row">${p.mine ? `<button type="button" class="btn sm" data-evo="draft" data-key="${esc(key)}">${icon("sparkle")}Draft an improvement</button>` : ""}
        <button type="button" class="btn sm" data-evo="new" data-key="${esc(key)}">${icon("plus")}New proposal</button></div>`, "", null, true);
  }

  // ---------- actions ----------
  async function act(a, el) {
    const id = +el.dataset.id, key = el.dataset.key;
    const close = () => document.getElementById("evo-dlg")?.open && document.getElementById("evo-dlg").close();
    if (a === "refresh") { sig = ""; return load(); }
    if (a === "new") { close(); return newProposal(key || ""); }
    if (a === "bench-new") return benchDialog(null);
    if (a === "bench-edit") return benchDialog(d.benchmarks.find(b => b.id === id));
    if (a === "detail") return detail(id);
    if (a === "pkg") return pkg(key);
    if (a === "evidence") return evidenceDialog(d.proposals.find(p => p.id === id));
    if (a === "answer") { close(); return answerDialog(id); }
    if (a === "bench-pick") {
      const p = d.proposals.find(x => x.id === id);
      return dlg(`Benchmark · ${esc(p.title)}`, `<label class="in"><span>Its experiment runs on</span><select name="b">${benchOpts(p.benchmark_id, p.target_key)}</select></label>
        <p class="small faint">Both versions answer every case of this benchmark. Evidence already measured stays until the next experiment.</p>`, "Save", async fd => {
          await api(`${B}/proposals/${id}`, { method: "PATCH", body: { benchmark_id: fd.get("b") ? +fd.get("b") : null } }); sig = ""; await load();
        });
    }
    try {
      if (a === "draft") {
        close(); Auth.toast("Drafting a change from the agent's weak spots…");
        const p = await api(`${B}/proposals/draft`, { method: "POST", body: { target_key: key } });
        Auth.toast("Drafted. It's a proposal until its experiment shows it's better."); tab = "proposals"; focus = p.id;
      } else if (a === "bench-draft") {
        Auth.toast("Drafting cases…");
        await api(`${B}/benchmarks/${id}/draft`, { method: "POST", body: { count: 4 } });
        Auth.toast("Cases added. Review them before you run an experiment.");
      } else if (a === "bench-del") {
        const b = d.benchmarks.find(x => x.id === id);
        if (!await UI.confirm({ title: `Delete ${esc(b?.name || "the benchmark")}?`, body: "Experiments already measured keep their evidence." })) return;
        await api(`${B}/benchmarks/${id}`, { method: "DELETE" });
      } else if (a === "run") {
        await api(`${B}/proposals/${id}/run`, { method: "POST", body: {} });
        Auth.toast("Experiment started: both versions answer every case, then the judge scores them blind.");
      } else if (a === "trial-start") {
        const p = d.proposals.find(x => x.id === id);
        const ok = await UI.confirm({ title: `Start the trial of “${esc(p.title)}”?`, body: `${esc(p.target_name)} works under the candidate instructions until you end the trial; then the version before comes back, whatever the numbers say. The team needs the Owner's opt-in to experiments and a frozen release.`, ok: "Start trial", icon: "play", danger: false });
        if (!ok) return;
        await api(`${B}/proposals/${id}/trial/start`, { method: "POST" }); Auth.toast("On trial: the candidate instructions are the agent's until you end it.");
      } else if (a === "trial-end") {
        if (!await UI.confirm({ title: "End the trial?", body: "The version before the trial comes back now. The evidence is read from the team's benchmark jobs during the trial; nothing is promoted.", ok: "End trial", icon: "check", danger: false })) return;
        const r = await api(`${B}/proposals/${id}/trial/end`, { method: "POST" });
        Auth.toast(r.status === "verified" ? "Verified on measured evidence: you can promote it." : "Not better by the policy's rule.");
      } else if (a === "promote") {
        const p = d.proposals.find(x => x.id === id);
        const ok = await UI.confirm({ title: `Promote “${esc(p.title)}”?`, body: p.applies_here ? `${esc(p.target_name)} gets the candidate configuration as a new version. The current one is kept; you can roll back.`
          : "This records your decision. Apply the change on its own page.", ok: "Promote", icon: "rocket", danger: false });
        if (!ok) return;
        await api(`${B}/proposals/${id}/promote`, { method: "POST" }); Auth.toast("Promoted.");
      } else if (a === "rollback") {
        if (!await UI.confirm({ title: "Roll back?", body: "The version before this change is restored as a new version.", ok: "Roll back", icon: "undo" })) return;
        const rb = await api(`${B}/proposals/${id}/rollback`, { method: "POST" });
        // the rollback went through; when its lesson couldn't be withdrawn that isn't a plain success: say so as an error, long enough to read
        if (rb && rb.lesson_not_withdrawn) Auth.toast(`Rolled back. ${rb.lesson_not_withdrawn}`, { kind: "error", ms: 20000 });
        else Auth.toast("Rolled back.");
      } else if (a === "reject") {
        await api(`${B}/proposals/${id}/reject`, { method: "POST" }); Auth.toast("Rejected.");
      } else return;
    } catch (e) { return Auth.toast(e.message); }
    sig = ""; await load();
  }

  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const t = e.target;
      if (!t.closest("#evo-root, #evo-dlg")) return;
      const tb = t.closest("[data-evo-tab]"); if (tb) { tab = tb.dataset.evoTab; try { localStorage.setItem("evo.tab", tab); } catch {} return draw(); }
      const f = t.closest("[data-evo-f]"); if (f) { filt = f.dataset.evoF; return draw(); }
      const to = t.closest("[data-evo-to]"); if (to) { document.getElementById("evo-dlg")?.close?.(); return setView(to.dataset.evoTo); }
      const g = t.closest("[data-evo-go]"); if (g) { try { return Command.follow(JSON.parse(g.dataset.evoGo)); } catch { return; } }
      const a = t.closest("[data-evo]"); if (a && !a.disabled) act(a.dataset.evo, a);
    });
  }

  function open() { on = true; wire(); sig = ""; draw(); load(); }
  function stop() { on = false; clearTimeout(timer); }
  function show(id) { tab = "proposals"; filt = "all"; focus = id || null; sig = ""; setView("evolution"); }
  // the sidebar button shows whenever Benchmarks & evaluations does (command.js decides that for the agent hubs)
  const ev = document.getElementById("nav-evaluation");
  const mirror = () => ["nav-evolution", "nav-analytics", "nav-governance"].forEach(id => { const b = document.getElementById(id); if (ev && b && b.hidden !== ev.hidden) b.hidden = ev.hidden; });
  mirror();
  if (ev) new MutationObserver(mirror).observe(ev, { attributes: true, attributeFilter: ["hidden"] });
  return { open, stop, show };
})();
