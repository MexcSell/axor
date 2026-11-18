/* Agent Swarm (AXoR G5; swarm.py /api/swarm, swarm.css, prefix swm-): the collaborative execution engine's page. A swarm is a
   mission run by a temporary team of Workforce agents: the Swarm Controller picks the size and the pattern and writes task
   contracts; agents work them over their dependencies, talk on the message bus as the pattern allows and file findings on the
   blackboard; an evaluator checks each contract, failed work is reassigned and an adaptive swarm replans. Cards, pills and KPIs
   reuse command.css (occ-) and hubs.css (axh-); dialogs reuse company.css (co-form). */
const Swarm = (() => {
  const B = "/api/swarm";
  const ST = { queued: ["s-off", "Queued", "clock"], running: ["s-info", "Running", "cycle"], done: ["s-ok", "Done", "check"], failed: ["s-crit", "Failed", "alert"],
               cancelled: ["s-off", "Cancelled", "ban"], skipped: ["s-off", "Skipped", "minus"], dropped: ["s-off", "Dropped", "minus"] };
  const VERDICT = { pass: ["s-ok", "Pass"], partial: ["s-warn", "Partial"], fail: ["s-crit", "Fail"] };
  const TRY = { done: "Filed", over_budget: "Over budget", overdue: "Out of time", failed: "Failed", lost: "Lost in a restart", cancelled: "Cancelled", running: "Working" };
  const TALK = { none: "No messaging", up: "Messages to the controller", peers: "Peer messaging" };
  const KIND = { finding: "s-info", request: "s-warn", answer: "s-ok", requirement: "s-crit", blocker: "s-crit" };
  const TABS = [["swarms", "sparkle", "Swarms"], ["patterns", "trophy", "Patterns & track record"], ["how", "info", "How it works"]];
  const SUB = [["contracts", "doc", "Contracts"], ["bus", "chat", "Message bus"], ["board", "list", "Blackboard"], ["activity", "clock", "Activity"], ["result", "check", "Result"]];
  let home = null, cur = null, sel = null, err = "", on = false, timer = null, wired = false, tab = "swarms", sub = "contracts", kindF = "all";
  try { tab = localStorage.getItem("swm.tab") || tab; sub = localStorage.getItem("swm.sub") || sub; } catch {}

  const root = () => document.getElementById("swm-root");
  const pill = (cls, text, ic) => `<span class="occ-pill ${cls}">${ic ? icon(ic) : "<i></i>"}${esc(text)}</span>`;
  const st = s => ST[s] || ["s-off", s || "–", "info"];
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : String(Math.round(n));
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const empty = t => `<p class="occ-empty">${icon("info")}${t}</p>`;
  const md = t => (typeof Agents !== "undefined" && Agents.md) ? Agents.md(t || "") : `<p>${esc(t || "")}</p>`;
  const pat = k => home?.patterns?.[k] || cur?.patterns?.[k] || { label: k || "–", icon: "sparkle" };
  const who = k => cur?.people?.[k]?.name || (k === "controller" ? "Swarm Controller" : k === "all" ? "Everyone" : k === "evaluator" ? "Evaluator" : k);
  const bar = (v, max, cls = "") => `<span class="swm-bar ${cls}" title="${tok(v)} of ${tok(max)} tokens"><i style="width:${Math.min(100, max ? 100 * v / max : 0).toFixed(1)}%"></i></span>`;

  // ---------- data ----------
  async function load() {
    try {
      home = await api(B); err = "";
      if (!sel && home.swarms.length) sel = home.swarms[0].id;
      if (sel && !home.swarms.some(s => s.id === sel)) sel = home.swarms[0]?.id || null;
      cur = sel ? await api(`${B}/swarms/${sel}`) : null;
    } catch (e) { err = e.message; }
    if (on) draw();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!on) return;
    const busy = home?.swarms?.some(s => s.status === "running" || s.status === "queued");
    timer = setTimeout(() => { if (!document.hidden && on) load(); else schedule(); }, busy ? 2500 : 20000);
  }

  // ---------- the swarm map: controller → contracts by dependency depth → result ----------
  function map(s, cs) {
    if (!cs.length) return "";
    const depth = {}, by = Object.fromEntries(cs.map(c => [c.key, c]));
    const d = c => depth[c.key] ??= c.depends.length ? 1 + Math.max(...c.depends.map(k => by[k] ? d(by[k]) : 0)) : 0;
    cs.forEach(d);
    const cols = Math.max(...Object.values(depth)) + 1, W = 172, H = 60, GX = 46, GY = 14, X0 = 128;
    const rows = Array.from({ length: cols }, (_, i) => cs.filter(c => depth[c.key] === i));
    const tall = Math.max(...rows.map(r => r.length)), height = Math.max(tall * (H + GY) - GY, H) + 16;
    const pos = {};
    rows.forEach((r, i) => { const top = (height - (r.length * (H + GY) - GY)) / 2; r.forEach((c, j) => pos[c.key] = [X0 + i * (W + GX), top + j * (H + GY)]); });
    const xr = X0 + cols * (W + GX), width = xr + 110, mid = height / 2;
    const edge = (x1, y1, x2, y2, cls) => `<path class="${cls}" d="M${x1},${y1} C${x1 + 28},${y1} ${x2 - 28},${y2} ${x2},${y2}"/>`;
    const leaves = cs.filter(c => !cs.some(o => o.depends.includes(c.key)));
    let e = "";
    cs.forEach(c => {
      const [x, y] = pos[c.key];
      if (!c.depends.length) e += edge(104, mid, x, y + H / 2, "swm-e-ctl");
      c.depends.forEach(k => { if (pos[k]) e += edge(pos[k][0] + W, pos[k][1] + H / 2, x, y + H / 2, `swm-e ${by[k].status === "done" ? "on" : ""}`); });
    });
    leaves.forEach(c => e += edge(pos[c.key][0] + W, pos[c.key][1] + H / 2, xr, mid, `swm-e ${c.status === "done" ? "on" : ""}`));
    const node = c => {
      const [x, y] = pos[c.key], names = (c.mode === "competitive" && c.status !== "done" ? c.contenders : [c.agent]).map(who);
      const doing = (c.mode === "competitive" ? c.contenders : [c.agent]).some(k => cur.people[k]?.doing) && c.status === "running";
      const t = c.title.length > 24 ? c.title.slice(0, 23) + "…" : c.title, a = names.join(" · ");
      return `<g class="swm-n st-${c.status}" data-swm-c="${c.key}" tabindex="0" role="button" aria-label="Contract ${c.key}: ${esc(c.title)}, ${esc(st(c.status)[1])}">
        <rect x="${x}" y="${y}" width="${W}" height="${H}" rx="9"/>${doing ? `<circle class="swm-live" cx="${x + W - 12}" cy="${y + 12}" r="4"/>` : ""}
        <text x="${x + 11}" y="${y + 21}" class="swm-t">#${c.key} ${esc(t)}</text>
        <text x="${x + 11}" y="${y + 38}" class="swm-a">${esc(a.length > 28 ? a.slice(0, 27) + "…" : a)}${c.mode === "competitive" ? " ⚔" : ""}</text>
        <text x="${x + 11}" y="${y + 52}" class="swm-s">${esc(st(c.status)[1])}${c.score != null ? ` · ${c.score}/100` : ""}${c.attempts > 1 ? ` · try ${c.attempts}` : ""}${c.revision ? " · revised" : ""}</text></g>`;
    };
    return `<div class="swm-map" role="group" aria-label="Swarm map: the controller, the contracts by dependency, the result">
      <svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">${e}
        <g class="swm-n swm-hub"><rect x="8" y="${mid - 26}" width="96" height="52" rx="26"/><text x="56" y="${mid - 3}" text-anchor="middle" class="swm-t">Controller</text>
          <text x="56" y="${mid + 13}" text-anchor="middle" class="swm-s">${esc(pat(s.pattern).label || "planning")}</text></g>
        ${cs.map(node).join("")}
        <g class="swm-n swm-hub ${s.status === "done" ? "st-done" : ""}"><rect x="${xr}" y="${mid - 26}" width="96" height="52" rx="26"/><text x="${xr + 48}" y="${mid - 3}" text-anchor="middle" class="swm-t">Result</text>
          <text x="${xr + 48}" y="${mid + 13}" text-anchor="middle" class="swm-s">${s.verdict ? esc(s.verdict) : s.step === "integrate" ? "integrating" : esc(s.status)}</text></g></svg></div>`;
  }

  // ---------- pieces ----------
  function list() {
    if (!home.swarms.length) return empty("No swarms yet. Start one: give it a goal and the Swarm Controller sizes the team.");
    return `<ul class="swm-list">${home.swarms.map(s => `<li><button type="button" class="swm-item ${s.id === sel ? "on" : ""}" data-swm-sel="${s.id}" aria-pressed="${s.id === sel}">
        <span class="swm-ih"><b>${esc(s.title)}</b>${pill(...st(s.status))}</span>
        <span class="swm-im faint">${s.pattern ? `${icon(pat(s.pattern).icon)}${esc(pat(s.pattern).label)} · ${esc(home.sizes[s.size]?.label || s.size)} · ` : ""}${s.contracts ? `${s.done}/${s.contracts} contracts · ` : ""}${tok(s.tokens)} tok${s.score != null ? ` · ${s.score}/100` : ""}${s.parent ? ` · mission #${s.parent}` : ""}</span>
        <span class="swm-im faint">${ago(s.created)}</span></button></li>`).join("")}</ul>`;
  }

  function contract(c, s) {
    const tries = c.tries.map(t => `<li><span class="swm-who">${esc(who(t.agent))}${t.entry ? ` <small class="faint">entry ${esc(t.entry)}</small>` : ""}</span>
        ${pill(t.verdict === "pass" ? "s-ok" : t.verdict === "lost" ? "s-off" : t.status === "done" && !t.verdict ? "s-info" : "s-crit", t.verdict === "lost" ? "Lost the comparison" : t.verdict ? t.verdict : TRY[t.status] || t.status)}
        ${t.score != null ? `<b class="num">${t.score}/100</b>` : ""}<span class="faint num">${tok(t.tokens)} tok</span>${t.note ? `<span class="swm-note">${esc(t.note)}</span>` : ""}</li>`).join("");
    const hist = c.history.filter(h => h.what !== "planned").map(h => `<li>${esc(h.what)}${h.agent ? ` · ${esc(who(h.agent))}` : ""}${h.note ? ` · <span class="faint">${esc(h.note)}</span>` : ""}</li>`).join("");
    const doing = c.status !== "running" ? [] : (c.mode === "competitive" && c.attempts <= 1 ? c.contenders : [c.agent]).map(k => cur.people[k]?.doing && `${who(k)}: ${cur.people[k].doing}`).filter(Boolean);
    return `<article class="card swm-c st-${c.status}" id="swm-c${c.key}">
      <header><span class="swm-k">#${c.key}</span><h4>${esc(c.title)}</h4>${pill(...st(c.status))}${c.mode === "competitive" ? pill("src", `Competitive · ${c.contenders.length}`, "trophy") : ""}
        ${c.added ? pill("s-warn", "Added by a replan", "cycle") : ""}${c.revision ? pill("s-warn", `Revised ×${c.revision}`, "edit") : ""}</header>
      <p class="swm-obj">${esc(c.objective)}</p>
      <div class="swm-cm"><span>${icon("users")}${(c.mode === "competitive" && c.status !== "done" ? c.contenders : [c.agent]).map(k => esc(who(k))).join(", ")}</span>
        <span title="Tokens used of the contract's budget_limit">${icon("coins")}${tok(c.tokens)} / ${tok(c.budget_limit)} ${bar(c.tokens, c.budget_limit, c.tokens > c.budget_limit ? "over" : "")}</span>
        ${c.depends.length ? `<span>${icon("link")}after ${c.depends.map(k => "#" + k).join(", ")}</span>` : ""}${c.score != null ? `<span>${icon("check")}${c.score}/100</span>` : ""}</div>
      ${doing.length ? `<p class="swm-doing">${icon("radio")}${esc(doing.join(" · "))}</p>` : ""}
      <ul class="swm-dl">${c.deliverables.map(x => `<li>${esc(x)}</li>`).join("")}</ul>
      ${tries ? `<ul class="swm-tries" aria-label="Attempts">${tries}</ul>` : ""}
      ${hist ? `<ul class="swm-hist" aria-label="History">${hist}</ul>` : ""}
      ${c.status === "done" && c.output ? `<details class="swm-out"><summary>Deliverable</summary><div class="swm-md">${md(c.output)}</div></details>` : ""}
      <details class="swm-json"><summary>Task contract</summary><pre>${esc(JSON.stringify(c.contract, null, 2))}</pre></details></article>`;
  }

  function bus() {
    const ms = cur.messages.filter(m => !(m.kind === "finding" && m.status === "board" || m.status === "withdrawn") && (kindF === "all" || m.kind === kindF));
    const kinds = ["all", "finding", "request", "answer", "requirement", "blocker"];
    return `<div class="swm-filt" role="group" aria-label="Kind">${kinds.map(k => `<button type="button" class="chip ${kindF === k ? "on" : ""}" data-swm-kind="${k}" aria-pressed="${kindF === k}">${k === "all" ? "All" : k}</button>`).join("")}</div>
      ${cur.swarm.decision?.policy?.talk === "none" ? `<p class="faint small">${icon("info")}This pattern has no messaging: agents read the blackboard instead.</p>` : ""}
      ${ms.length ? `<ol class="swm-msgs">${ms.map(m => `<li><span class="swm-route"><b>${esc(who(m.sender))}</b>${icon("right")}<b>${esc(who(m.recipient))}</b></span>${pill(KIND[m.kind] || "s-off", m.kind)}
        ${m.status === "handled" ? pill("s-ok", "Handled", "check") : ""}<span class="faint small">${ago(m.created)}</span><p>${esc(m.text)}</p></li>`).join("")}</ol>` : empty("No messages yet.")}`;
  }

  function board() {
    const s = cur.swarm, f = cur.messages.filter(m => m.kind === "finding" && m.recipient === "all" && (m.status === "board" || m.status === "withdrawn"));
    return `<div class="swm-state"><h4>Mission state</h4><ul>${cur.contracts.map(c => `<li>${pill(...st(c.status))}<b>#${c.key}</b> ${esc(c.title)} <span class="faint">· ${esc(who(c.agent))}</span>${c.summary ? `<p class="faint small">${esc(c.summary)}</p>` : ""}</li>`).join("")}</ul></div>
      <h4>Findings</h4>${f.length ? `<ul class="swm-finds">${f.map(m => `<li class="${m.status === "withdrawn" ? "gone" : ""}"><b>${esc(who(m.sender))}</b> ${esc(m.text)}${m.evidence ? ` <span class="faint small">(${esc(m.evidence)})</span>` : ""}
        ${m.status === "withdrawn" ? pill("s-off", "Withdrawn: the work failed its check") : ""}</li>`).join("")}</ul>` : empty("Nothing on the blackboard yet.")}
      <p class="faint small">${icon("info")}What every agent of the swarm reads with read_blackboard: ${s.goal.length > 120 ? esc(s.goal.slice(0, 119)) + "…" : esc(s.goal)}</p>`;
  }

  function activity() {
    const ev = cur.events;
    return ev.length ? `<ol class="swm-ev">${ev.map(e => `<li class="k-${esc(e.kind)}"><span class="faint small num">${new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
      <b>${esc(who(e.agent))}</b><span>${esc(e.text)}</span>${e.tokens ? `<span class="faint small num">${tok(e.tokens)} tok</span>` : ""}</li>`).join("")}</ol>` : empty("Nothing happened yet.");
  }

  function result() {
    const s = cur.swarm;
    if (!s.report) return empty(s.status === "running" ? "The result comes when the contracts are done and integrated." : s.error ? esc(s.error) : "No result.");
    return `<div class="swm-res">${s.headline ? `<p class="swm-headline">${esc(s.headline)}</p>` : ""}${s.verdict ? `<p>${pill(...(VERDICT[s.verdict] || ["s-off", s.verdict]))}${s.score != null ? ` <b>${s.score}/100</b>` : ""}${s.parent ? ` <span class="faint small">from Mission Control's verification of mission #${s.parent}</span>` : ""}</p>` : s.parent ? `<p class="faint small">${icon("info")}Mission Control (mission #${s.parent}) verifies this result.</p>` : ""}
      ${s.criteria_eval?.length ? `<ul class="swm-crit">${s.criteria_eval.map(x => `<li>${pill(x.met ? "s-ok" : "s-crit", x.met ? "Met" : "Not met", x.met ? "check" : "close")}<b>${esc(x.criterion)}</b> <span class="faint">${esc(x.note)}</span></li>`).join("")}</ul>` : ""}
      <div class="swm-md">${md(s.report)}</div>${s.limits?.length ? `<h4>Limits</h4><ul>${s.limits.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`;
  }

  function detail() {
    if (!cur) return `<div class="card swm-detail">${empty("Pick a swarm, or start a new one.")}</div>`;
    const s = cur.swarm, dec = s.decision || {}, pol = dec.policy, live = s.status === "running" || s.status === "queued";
    const steps = ["plan", "execute", "integrate", ...(s.parent ? [] : ["evaluate"])], at = steps.indexOf(s.step);
    const n = { contracts: cur.contracts.length, bus: cur.messages.filter(m => !(m.kind === "finding" && m.recipient === "all" && m.status !== "sent")).length,
                board: cur.messages.filter(m => m.kind === "finding" && m.status === "board").length, activity: 0, result: 0 };
    return `<section class="card swm-detail" aria-labelledby="swm-h">
      <header class="swm-dh"><div><h2 id="swm-h">${esc(s.title)}</h2><p class="faint small">${esc(s.goal.length > 260 ? s.goal.slice(0, 259) + "…" : s.goal)}</p></div>
        <div class="row">${pill(...st(s.status))}${live ? `<button type="button" class="btn sm" data-swm="cancel">${icon("stop")}Cancel</button>` : `<button type="button" class="btn sm ghost" data-swm="delete">${icon("trash")}Delete</button>`}</div></header>
      <ol class="swm-steps" aria-label="Steps">${steps.map((k, i) => `<li class="${s.status === "done" || i < at ? "done" : i === at && live ? "now" : ""}">${esc({ plan: "Plan", execute: "Execute", integrate: "Integrate", evaluate: "Evaluate" }[k])}</li>`).join("")}</ol>
      <div class="swm-meta"><span>${icon(pat(s.pattern).icon || "sparkle")}<b>${esc(pat(s.pattern).label || "Planning…")}</b></span><span>${icon("users")}${esc(cur.sizes[s.size] || "–")} · ${plural((dec.agents || []).length, "agent")}</span>
        <span title="Tokens used of the swarm's budget">${icon("coins")}${tok(s.tokens)} / ${tok(s.budget)} ${bar(s.tokens, s.budget)}</span>${s.adapts ? `<span>${icon("cycle")}${plural(s.adapts, "replan")}</span>` : ""}
        ${s.deadline ? `<span>${icon("clock")}due ${new Date(s.deadline * 1000).toLocaleString()}</span>` : ""}</div>
      ${dec.why ? `<div class="swm-ctl"><p><b>${icon("sparkle")}Swarm Controller:</b> ${esc(dec.why)}</p>
        ${dec.switch ? `<p class="swm-switch">${icon("cycle")}Switched from ${esc(pat(dec.picked).label)} to ${esc(pat(s.pattern).label)}: ${esc(dec.switch)}.</p>` : ""}
        ${pol ? `<p class="swm-pol">${pill("src", TALK[pol.talk], "chat")}${pill("src", pol.compete ? "Competitive contracts allowed" : "No competitive contracts", "trophy")}${pill("src", pol.adapt ? "Replans mid-flight" : "Fixed plan", "cycle")}${pill("src", pol.same_team ? "Reassigns inside the team" : "Reassigns to the best fit", "users")}</p>` : ""}
        ${dec.record?.similar ? `<p class="faint small">${icon("chart")}Weighed ${plural(dec.record.similar, "similar earlier swarm")}.</p>` : ""}</div>` : ""}
      ${s.error ? `<p class="swm-err">${icon("alert")}${esc(s.error)}</p>` : ""}
      ${map(s, cur.contracts)}
      <nav class="axh-tabs" role="tablist">${SUB.map(([k, ic, l]) => `<button type="button" role="tab" data-swm-sub="${k}" aria-selected="${sub === k}">${icon(ic)}${l}${n[k] ? ` <b>${n[k]}</b>` : ""}</button>`).join("")}</nav>
      <div class="swm-sub">${({ contracts: () => cur.contracts.length ? cur.contracts.map(c => contract(c, s)).join("") : empty(live ? "The controller is planning the contracts…" : "No contracts."),
                                bus, board, activity, result })[sub]?.() || ""}</div></section>`;
  }

  function patterns() {
    const r = home.record, rows = Object.entries(home.patterns);
    return `<div class="swm-pats">${rows.map(([k, p]) => { const e = r.patterns[k];
      return `<article class="card swm-pat"><h3>${icon(p.icon)}${esc(p.label)}${k === "hybrid" ? pill("s-ok", "Recommended") : ""}</h3><p>${esc(p.about)}</p><p class="faint small">Best for: ${esc(p.best)}</p>
        <p class="swm-pol">${pill("src", TALK[p.talk], "chat")}${p.compete ? pill("src", "Competitive", "trophy") : ""}${p.adapt ? pill("src", "Replans", "cycle") : ""}</p>
        <p class="swm-rec">${e ? `<b>${e.avg}/100</b> average over ${plural(e.n, "swarm")} · ${tok(e.tokens)} tok · ${fmtNum(e.minutes, 1)} min each` : `<span class="faint">No finished swarm yet</span>`}</p></article>`; }).join("")}</div>
      <section class="card swm-roster"><h3>${icon("users")}Who can hold a contract</h3><p class="faint small">Your active Workforce agents (not the CEO, who integrates, or the Chief Evaluator, who checks). Their scores rank who gets work and who takes over failed work.</p>
        <ul>${home.roster.map(a => `<li><span><b>${esc(a.name)}</b> <span class="faint">${esc(a.title)}</span></span>${a.record ? `<span class="num small" title="Weighted score of their attempts">${a.record.score}/100 · ${a.record.passed}/${a.record.n} passed</span>` : `<span class="faint small">no attempts yet</span>`}</li>`).join("")}</ul></section>`;
  }

  function how() {
    const L = home.limits;
    const step = (ic, t, x) => `<li><span class="swm-hi">${icon(ic)}</span><div><b>${t}</b><p>${x}</p></div></li>`;
    return `<section class="card swm-how"><ol>
      ${step("sparkle", "1. The Swarm Controller plans", `It decides how many agents the mission needs (one, a small team of 2-3, or a swarm of 3-${L.agents}: more agents don't mean better results), picks the pattern, and writes up to ${L.contracts} task contracts: objective, deliverables, dependencies, the agent who fits best and a token budget. Similar earlier swarms' results can switch its pattern.`)}
      ${step("columns", "2. Contracts run over their dependencies", `Up to ${L.slots} agents work at once; a contract starts when the ones it needs are done and gets their hand-offs. Each attempt is metered: it stops when its budget_limit or its ${L.minutes}-minute limit runs out.`)}
      ${step("chat", "3. Agents communicate through controlled interfaces", "Never each other's internals: the blackboard (every contract's state and the findings filed so far), the message bus (to one agent, everyone or the controller, as the pattern allows) and notices of unread messages in their tool results.")}
      ${step("check", "4. Every contract is checked independently", `The Chief Evaluator (on another model than the worker, when your pool has one) checks each contract. A competitive contract's ${L.contenders} attempts are compared blind. Failed work is reassigned with the evaluator's note (${L.attempts} attempts at most).`)}
      ${step("cycle", "5. The plan adapts", `In the adaptive, hierarchical and hybrid patterns, a requirement or blocker sent to the controller, or a contract that failed for good, makes it revise, drop or add contracts (${L.adapts} replans at most).`)}
      ${step("doc", "6. Integrate, evaluate, learn", `The CEO integrates the results; the evaluator judges them against your criteria (Mission Control does that itself for missions it runs here). Each swarm's pattern, size and score feed the next plans. Contracts stop starting at ${Math.round(L.exec_share * 100)}% of the budget so this fits.`)}
    </ol><p class="faint small">${icon("shield")}Agents only read and draft: nothing is deployed, paid or posted. Mission Control can also run a mission on the swarm (engine “Agent Swarm”).</p></section>`;
  }

  function draw() {
    const el = root(); if (!el) return;
    if (!home) { el.innerHTML = err ? `<div class="card empty">${esc(err)} <button type="button" class="linkbtn" data-swm="refresh">Try again</button></div>` : `<div class="stats">${Loading.tiles(4)}</div>`; return; }
    const sw = home.swarms, y = scrollY;
    const kpi = (ic, label, v, s, tone) => `<div class="stat occ-kpi ${tone ? "t-" + tone : ""}"><div class="label">${icon(ic)}${label}</div><div class="value">${esc(String(v))}</div><div class="sub">${esc(s || "")}</div></div>`;
    const best = Object.entries(home.record.patterns).sort((a, b) => b[1].score - a[1].score)[0];  // ranked by the weighted score, shown as the plain average
    const running = sw.filter(s => s.status === "running" || s.status === "queued").length, done = sw.filter(s => s.status === "done");
    el.innerHTML = `<div class="occ swm"><div class="occ-head"><div><p class="occ-kicker">${icon("sparkle")}Workforce · AXoR G5</p><h1 class="page">Agent Swarm</h1>
        <p class="lead">A temporary team of your Workforce agents runs a mission as task contracts: the Swarm Controller picks the size and the pattern, agents work in parallel and share what they find, every contract is checked, failed work is reassigned and the plan adapts.</p></div>
        <div class="row"><button type="button" class="btn sm primary" data-swm="new">${icon("plus")}New swarm</button><button type="button" class="btn sm" data-swm="refresh">${icon("cycle")}Refresh</button></div></div>
      <div class="stats occ-kpis">${kpi("cycle", "Running", running, "swarms at work", running ? "info" : "")}
        ${kpi("check", "Finished", done.length, `${done.filter(s => s.verdict === "pass").length} passed`)}
        ${kpi("doc", "Contracts fulfilled", sw.reduce((a, s) => a + s.done, 0), `of ${sw.reduce((a, s) => a + s.contracts, 0)} planned`)}
        ${kpi("trophy", "Best pattern", best ? pat(best[0]).label : "–", best ? `${best[1].avg}/100 average over ${plural(best[1].n, "swarm")}` : "after the first finished swarm")}</div>
      <nav class="axh-tabs" role="tablist">${TABS.map(([k, ic, l]) => `<button type="button" role="tab" data-swm-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}</button>`).join("")}</nav>
      ${tab === "patterns" ? patterns() : tab === "how" ? how() : `<div class="swm-grid"><aside class="card swm-side" aria-label="Swarms">${list()}</aside>${detail()}</div>`}
      ${err ? `<p class="faint small">${icon("alert")}${esc(err)}</p>` : ""}</div>`;
    if (Math.abs(scrollY - y) > 1) scrollTo(0, y);
  }

  // ---------- new swarm ----------
  function create() {
    let el = document.getElementById("swm-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "swm-dlg"; document.body.append(el); }
    el.className = "modal swm-dlg";
    const opt = (v, l, on) => `<option value="${esc(v)}" ${on ? "selected" : ""}>${esc(l)}</option>`;
    el.innerHTML = `<form method="dialog" class="co-form" novalidate><div class="swm-dlgh"><h3>${icon("sparkle")}New swarm</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      <label class="in"><span>Goal</span><textarea name="goal" rows="4" maxlength="4000" required placeholder="e.g. Find the three best subnets for a CPU miner this month and plan the first 30 days"></textarea></label>
      <label class="in"><span>Success criteria <em class="opt">one per line, up to 6; the evaluator checks the result against them</em></span><textarea name="criteria" rows="3" maxlength="1500"></textarea></label>
      <div class="row"><label class="in"><span>Size</span><select name="size">${opt("auto", "Let the controller decide", true)}${Object.entries(home.sizes).map(([k, v]) => opt(k, `${v.label} (${v.min === v.max ? v.min : `${v.min}-${v.max}`} agent${v.max > 1 ? "s" : ""})`)).join("")}</select></label>
        <label class="in"><span>Pattern</span><select name="pattern">${opt("auto", "Let the controller decide", true)}${Object.entries(home.patterns).map(([k, p]) => opt(k, p.label)).join("")}</select></label></div>
      <div class="row"><label class="in"><span>Token budget</span><select name="budget">${home.budgets.map(b => opt(b, `${tok(b)} tokens`, b === 80000)).join("")}</select></label>
        <label class="in"><span>Deadline <em class="opt">hours, optional</em></span><input type="number" name="hours" min="0" max="168" step="0.5" inputmode="decimal"></label></div>
      <p class="faint small">${icon("info")}Spends model credits like a Workforce mission. Agents only read and draft.</p>
      <p class="err" role="alert"></p><div class="row end"><button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn primary">${icon("play")}Start swarm</button></div></form>`;
    const f = el.querySelector("form"), e = f.querySelector(".err");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    f.onsubmit = async ev => {
      ev.preventDefault();
      const fd = new FormData(f), goal = String(fd.get("goal") || "").trim(), h = parseFloat(fd.get("hours"));
      if (goal.length < 10) { e.textContent = "Describe the goal in a sentence or more."; return; }
      const btn = f.querySelector("[type=submit]"); btn.classList.add("loading"); btn.disabled = true; e.textContent = "";
      try {
        const r = await api(`${B}/swarms`, { method: "POST", body: { goal, criteria: String(fd.get("criteria") || "").split("\n").map(x => x.trim()).filter(Boolean).slice(0, 6),
          size: fd.get("size"), pattern: fd.get("pattern"), budget: +fd.get("budget"), deadline: h > 0 ? Date.now() / 1000 + h * 3600 : null } });
        el.close(); sel = r.swarm.id; tab = "swarms"; sub = "contracts"; toast("Swarm started: the controller is planning it."); load();
      } catch (x) { e.textContent = x.message; } finally { btn.classList.remove("loading"); btn.disabled = false; }
    };
    el.showModal(); f.goal.focus();
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", async ev => {
      const t = ev.target.closest?.("[data-swm],[data-swm-sel],[data-swm-tab],[data-swm-sub],[data-swm-kind],[data-swm-c]");
      if (!t || !root()?.contains(t)) return;
      if (t.dataset.swmSel) { sel = +t.dataset.swmSel; tab = "swarms"; cur = null; draw(); return load(); }
      if (t.dataset.swmTab) { tab = t.dataset.swmTab; try { localStorage.setItem("swm.tab", tab); } catch {} return draw(); }
      if (t.dataset.swmSub) { sub = t.dataset.swmSub; try { localStorage.setItem("swm.sub", sub); } catch {} return draw(); }
      if (t.dataset.swmKind) { kindF = t.dataset.swmKind; return draw(); }
      if (t.dataset.swmC) { sub = "contracts"; draw(); return document.getElementById("swm-c" + t.dataset.swmC)?.scrollIntoView({ behavior: "smooth", block: "start" }); }
      const a = t.dataset.swm;
      if (a === "refresh") return load();
      if (a === "new") return home && create();
      if (a === "cancel" && cur) { try { await api(`${B}/swarms/${cur.swarm.id}/cancel`, { method: "POST" }); toast("Cancelling: running contracts stop at their next step."); } catch (x) { toast(x.message, { kind: "error" }); } return load(); }
      if (a === "delete" && cur) {
        const ok = await UI.confirm({ title: "Delete this swarm?", body: "Its contracts, messages and traces go too.", ok: "Delete", icon: "trash", danger: true });
        if (!ok) return;
        try { await api(`${B}/swarms/${cur.swarm.id}`, { method: "DELETE" }); sel = null; cur = null; } catch (x) { toast(x.message, { kind: "error" }); }
        return load();
      }
    });
    document.addEventListener("keydown", ev => { const g = ev.target.closest?.("[data-swm-c]"); if (g && (ev.key === "Enter" || ev.key === " ") && root()?.contains(g)) { ev.preventDefault(); g.dispatchEvent(new MouseEvent("click", { bubbles: true })); } });
  }

  // the sidebar entry shows whenever the Workforce's does (app.js, which defines $, loads after this file: plain DOM calls)
  const wfNav = document.getElementById("nav-workforce");
  const mirror = () => { const b = document.getElementById("nav-swarm"); if (wfNav && b && b.hidden !== wfNav.hidden) b.hidden = wfNav.hidden; };
  mirror();
  if (wfNav) new MutationObserver(mirror).observe(wfNav, { attributes: true, attributeFilter: ["hidden"] });

  function open(id) { on = true; wire(); if (id) { sel = id; tab = "swarms"; } draw(); load(); }
  function stop() { on = false; clearTimeout(timer); }
  return { open, stop, show: id => { sel = id; tab = "swarms"; if (typeof setView === "function") setView("swarm"); } };
})();
