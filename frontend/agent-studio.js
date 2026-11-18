/* Agent operations (agent_studio.py, agent-studio.css; prefix aos-): every agent AXoR has, in one workspace.
   It draws the operations side of the Agents page (#aos inside #view-agents, beside agents.js's #hub-main): the page's rail
   (Directory, Operations, Live runs, Connected systems, Ecosystem) picks the section; setView("studio") is an alias for it.
   - Overview: the agents by system, what needs attention, the approval queue, token use and the activity feed.
   - Live operations: what runs now and what failed in the last day; any run opens its execution trace.
   - Directory: every agent, filtered by system and state; one opens in the Agent Studio.
   - Agent Studio: overview, instructions, skills, tools, memory, tasks, evaluations, versions and activity. Your own agents are
     edited here (each save is a version), tried on a message before saving, compared version against version and restored.
     Every other agent links to the page that manages it, where its approval rules live.
   - Connected: where orchestration, evaluation, evolution and governance already happen (Workforce, Missions & tasks, the
     Company, Competition teams, Agent evaluation, the Approval Center), with live counts.
   The page polls every 20 s while it shows; the Studio is never redrawn under your typing. */
const Studio = (() => {
  const EVERY = 20000;
  const SYS = { hub: ["bot", "Your agents"], builtin: ["shield", "Built-in"], company: ["layers", "Company"], workforce: ["group", "Workforce"],
                teams: ["users", "Competition teams"], workflow: ["code", "Workflow"], hq: ["flag", "Agent HQ"], other: ["info", "Other"] };
  const STATE = { working: ["Working", "good"], review: ["In review", "warn"], attention: ["Needs attention", "crit"], paused: ["Paused", "mute"], idle: ["Idle", "mute"] };
  const TABS = [["overview", "Overview"], ["instructions", "Instructions"], ["skills", "Skills"], ["tools", "Tools"], ["memory", "Memory"], ["tasks", "Tasks"],
                ["evaluations", "Evaluations"], ["versions", "Versions"], ["activity", "Activity"]];
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("aos." + k)); localStorage.setItem("aos." + k, JSON.stringify(v)); } catch { return null; } };
  let d = null, err = "", sec = pref("sec") || "directory", key = pref("key") || null, tab = "overview", agent = null, agentErr = "", timer = null, sig = "", wired = false;
  let f = { sys: "all", state: "all", q: "", own: "all" }, gos = [], draft = null, testOut = null, testBusy = false, cmp = { a: null, b: null, msg: "", out: null, busy: false }, seq = 0;

  // ---------- small pieces ----------
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e4 ? 0 : 1)}k` : String(Math.round(n));
  const pct = x => x == null ? "–" : `${Math.round(x * 100)}%`;
  const secs = s => s == null ? "–" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${fmtNum(s / 3600, 1)} h`;
  const when = ts => ts ? ago(ts) : "–";
  const go = x => x ? `data-aos-go="${gos.push(x) - 1}"` : "";
  const sys = k => SYS[k] || SYS.other;
  const sysPill = k => `<span class="aos-pill">${icon(sys(k)[0])}${esc(sys(k)[1])}</span>`;
  const statePill = s => { const [t, tone] = STATE[s] || [s || "–", "mute"]; return `<span class="aos-state t-${tone}"><i></i>${esc(t)}</span>`; };
  const tone = s => /fail|error|timeout|reject|avoid|crit/i.test(s || "") ? "crit" : /run|work|queued|check|doing|progress/i.test(s || "") ? "good"
    : /review|wait|pending|block|propos/i.test(s || "") ? "warn" : /done|pass|merged|succe|approved|kept|clear/i.test(s || "") ? "ok" : "mute";
  const status = s => `<span class="aos-st t-${tone(s)}">${esc(s || "–")}</span>`;
  const empty = t => `<p class="aos-empty">${t}</p>`;
  const avatar = a => `<span class="aos-av c-${esc(a.color || "slate")}">${icon(a.icon || "bot")}</span>`;
  const card = (ic, title, extra, body, cls = "") => `<section class="aos-card ${cls}"><header><h3>${icon(ic)}${title}</h3>${extra || ""}</header>${body}</section>`;
  const kpi = (label, value, sub, t, to) => `<button type="button" class="aos-kpi ${t ? "t-" + t : ""}" ${to ? `data-aos-sec="${to}"` : "disabled"}><span>${esc(label)}</span><b>${esc(String(value))}</b><small>${esc(sub || "")}</small></button>`;
  const bars = (items, fmt = tok) => {
    if (!items.length) return empty("Nothing yet.");
    const max = Math.max(...items.map(i => i.value), 1e-9);
    return `<ul class="aos-bars">${items.map(i => `<li><span class="aos-bl" title="${esc(i.label)}">${esc(i.label)}</span><span class="aos-bt"><i style="width:${Math.max(2, i.value / max * 100).toFixed(1)}%"></i>${i.part ? `<em style="width:${(i.part / max * 100).toFixed(1)}%"></em>` : ""}</span><b>${esc(fmt(i.value))}</b></li>`).join("")}</ul>`;
  };
  const mine = () => agent && agent.system === "hub" && agent.can_edit;
  const on = () => S.view === "agents" && $("#aos") && !$("#aos").hidden;  // showing: the Agents page on its operations side
  const SEC_RAIL = { studio: "directory" };  // an agent's profile belongs to the Directory

  // ---------- open, poll, stop ----------
  async function open(want) {
    wire();
    if (want && want !== sec) { sec = want; pref("sec", sec); }
    if (!$("#aos").innerHTML) $("#aos").innerHTML = `<div class="aos-loading">${icon("radio")} Loading agent operations…</div>`;
    await load(true);
    if (sec === "studio" && key) openAgent(key, true);
    clearInterval(timer); timer = setInterval(() => { if (on() && !document.hidden) load(false); }, EVERY);
  }
  function stop() { clearInterval(timer); timer = null; }
  async function load(fresh) {
    try { d = await api("/api/studio" + (fresh ? "?fresh=1" : "")); err = ""; }
    catch (e) { err = e.message; }
    const s = JSON.stringify([d?.counts, d?.agents?.map(a => a.key + a.state), d?.running?.length, d?.failed?.length, d?.activity?.[0]?.ts, d?.approvals?.length, err]);
    if (s === sig && !fresh) return;
    sig = s;
    const badge = $("#c-agents"); if (badge) badge.textContent = d?.counts?.attention || "";  // on Agents (the hidden #c-studio would count twice in the section header)
    const ln = $("#hub-live-n"); if (ln) ln.textContent = d?.counts?.running || "";
    if ((sec === "studio" && agent) || document.activeElement?.id === "aos-q" || Ecosystem.holding()) { drawTop(); return; }  // never redraw under your typing
    draw();
  }
  function openAgent(k, keepTab) {
    key = k; pref("key", k); sec = "studio"; pref("sec", sec);
    if (!keepTab) tab = "overview";
    draft = null; testOut = null; cmp = { a: null, b: null, msg: "", out: null, busy: false };
    const mySeq = ++seq;
    agent = null; agentErr = ""; draw();
    api("/api/studio/agents/" + encodeURIComponent(k)).then(x => { if (mySeq !== seq) return; agent = x; draw(); })
      .catch(e => { if (mySeq !== seq) return; agentErr = e.message; draw(); });
  }
  function show(k) { if (!on()) { pref("sec", "studio"); pref("key", k); sec = "studio"; key = k; setView("studio"); } else openAgent(k); }

  // ---------- drawing ----------
  function draw() {
    gos = [];
    const el = $("#aos");
    if (!el) return;
    rail();
    if (err && !d) { el.innerHTML = `<div class="aos-head"><div><p class="aos-kick">AXoR · Agents</p><h1>Agents</h1></div></div>${empty(esc(err))}`; return; }
    if (!d) return;
    el.innerHTML = `<div id="aos-top">${top()}</div><div class="aos-body">${body()}</div>`;
    for (const strip of $$(".aos-sec, .aos-tabs", el)) {  // on a narrow screen the chosen tab stays in sight
      const b = strip.querySelector("[aria-selected=true]");
      if (b && strip.scrollWidth > strip.clientWidth) strip.scrollLeft = b.offsetLeft - (strip.clientWidth - b.offsetWidth) / 2;
    }
  }
  // the Agents rail: which item is current, for the section showing here
  function rail() {
    if (!on()) return;
    const cur = SEC_RAIL[sec] || sec;
    $$("#view-agents [data-ops-sec], #view-agents [data-hub]").forEach(b => b.setAttribute("aria-current", b.dataset.opsSec === cur ? "page" : "false"));
  }
  function drawTop() { const t = $("#aos-top"); if (t) t.innerHTML = top(); }
  const HEADS = { overview: ["Operations", "What every agent is doing, what needs attention, the approval queue and token use."],
    live: ["Live runs", "What runs now, what failed in the last day and what waits for your approval. A run opens its execution trace."],
    directory: ["Agents", ""], connected: ["Connected systems", "Where orchestration, evaluation, evolution and governance happen, with live counts."],
    ecosystem: ["Ecosystem", "The eight layers agents work in, and the registry of external agents."] };
  function top() {
    const c = d.counts;
    if (sec === "studio") return d.errors?.length ? `<p class="aos-warnline">${icon("alert")}Some sources didn't load: ${esc(d.errors.join(" · "))}</p>` : "";  // the profile has its own head
    const [h1, lede] = HEADS[sec] || HEADS.directory;
    return `<div class="aos-head"><div><p class="aos-kick"><span class="aos-dot ${err ? "off" : ""}"></span>AXoR · Agents · ${err ? "can't refresh: " + esc(err) : "live"}</p>
        <h1>${esc(h1)}</h1><p class="aos-lede">${lede ? esc(lede) : `Every agent in one directory: your own, the built-in ones, the Company, Workforce, Competition teams${d.admin ? ", the Workflow and Agent HQ" : ""}. Open one for its profile, chat, versions and runs.`}</p></div>
        <div class="aos-acts"><button type="button" class="btn sm" data-aos-act="refresh" title="Refresh now">${icon("reset")}Refresh</button>
        <button type="button" class="btn sm primary" data-aos-act="create">${icon("plus")}New agent</button></div></div>
      ${sec === "connected" || sec === "ecosystem" ? "" : `<div class="aos-kpis">${kpi("Agents", c.agents, `${Object.keys(d.systems).length} systems`, "", "directory")}${kpi("Working", c.working, `${c.running} runs live`, c.working ? "good" : "", "live")}
        ${kpi("In review", c.review, "waiting on a review", c.review ? "warn" : "", "live")}${kpi("Needs attention", c.attention, `${c.failed} failed in 24 h`, c.attention || c.failed ? "crit" : "", "live")}
        ${kpi("Approvals", c.approvals, "in the Approval Center", c.approvals ? "warn" : "", "overview")}${kpi("Tokens · 7 days", tok(c.tokens_week), "every model call", "", "overview")}</div>`}
      ${d.errors?.length ? `<p class="aos-warnline">${icon("alert")}Some sources didn't load: ${esc(d.errors.join(" · "))}</p>` : ""}`;
  }
  function body() {
    if (sec === "live") return live();
    if (sec === "directory") return directory();
    if (sec === "studio") return studio();
    if (sec === "connected") return connected();
    if (sec === "ecosystem") return Ecosystem.view();  // the eight layers and the external-agent registry (ecosystem.js)
    return overview();
  }

  // ---------- Overview ----------
  function overview() {
    const sysItems = Object.entries(d.systems).map(([k, s]) => ({ label: s.label, value: s.agents, part: s.working })).sort((a, b) => b.value - a.value);
    const att = d.agents.filter(a => a.state === "attention" || a.state === "review").slice(0, 8);
    return `<div class="aos-grid">
      ${card("users", "Agents by system", `<button type="button" class="aos-link" data-aos-sec="directory">Directory${icon("right")}</button>`, bars(sysItems, String) + `<p class="aos-note">Bar length: agents; the brighter part: working now.</p>`)}
      ${card("alert", "Needs attention", `<button type="button" class="aos-link" data-aos-sec="live">Live operations${icon("right")}</button>`,
        att.length || d.failed.length ? `<ul class="aos-list">${att.map(a => `<li><button type="button" class="aos-row" data-aos-agent="${esc(a.key)}">${avatar(a)}<span class="aos-rt"><b>${esc(a.name)}</b><small>${esc(a.role)} · ${esc(a.team || a.system_label)}</small></span>${statePill(a.state)}</button></li>`).join("")}
          ${d.failed.slice(0, Math.max(0, 6 - att.length)).map(r => runRow(r)).join("")}</ul>` : empty("Nothing needs you. No failed runs in the last day."))}
      ${card("inbox", "Approval queue", `<button type="button" class="aos-link" ${go({ view: "approvals" })}>Approval Center${icon("right")}</button>`,
        d.approvals.length ? `<ul class="aos-list">${d.approvals.slice(0, 6).map(p => `<li><button type="button" class="aos-row" ${go(p.go)}><span class="aos-lv l-${esc(p.level)}"></span><span class="aos-rt"><b>${esc(p.title)}</b><small>${esc(p.where || p.source)}${p.ts ? " · " + ago(p.ts) : ""}</small></span><span class="aos-go">${esc(p.label || "Open")}${icon("right")}</span></button></li>`).join("")}</ul>`
          + (d.approvals.length > 6 ? `<p class="aos-note">${d.approvals.length - 6} more in the Approval Center.</p>` : "") : empty("No requests wait for your decision."))}
      ${card("chart", "Token use · last 7 days", "", bars(d.tokens.map(t => ({ label: t.label, value: t.tokens }))) + `<p class="aos-note">From the agent core's run ledger: every model call of every agent system, counted once. Costs aren't shown: AXoR keeps no price list.</p>`)}
      ${d.budget ? budgetCard(d.budget) : ""}
      ${card("clock", "Recent activity", "", d.activity.length ? `<ul class="aos-feed">${d.activity.slice(0, 14).map(feedItem).join("")}</ul>` : empty("No agent activity yet."), "wide")}
    </div>`;
  }
  // your daily limit over every agent system (agent_core.py): off unless set
  function budgetCard(b) {
    const cap = b.daily_tokens, pctUsed = cap ? Math.min(100, Math.round(100 * b.today / cap)) : 0;
    return card("coins", "Daily budget", "", `<div class="aos-budget">
        <div class="aos-bnum"><span>Today, every system</span><b>${tok(b.today)}</b>${cap ? `<small>of ${tok(cap)} (${pctUsed}%)</small>` : `<small>no limit set</small>`}</div>
        ${cap ? `<span class="aos-bbar${pctUsed >= 100 ? " full" : pctUsed >= 80 ? " warn" : ""}" role="img" aria-label="${pctUsed}% of today's limit used"><i style="width:${pctUsed}%"></i></span>` : ""}
        <label class="aos-bin"><span>Daily limit in tokens (empty: none)</span><input type="number" min="0" step="10000" inputmode="numeric" value="${cap || ""}" placeholder="No limit" data-aos-budget></label></div>
      ${policyLine(b)}
      ${b.by_system.length ? bars(b.by_system.map(x => ({ label: x.label, value: x.tokens }))) : ""}
      <p class="aos-note">When today's use reaches the limit, agent work in every system stops before its next model call, until midnight or until you raise it. Chats count toward it; Agent HQ has its own hourly budget.</p>
      ${limitsBlock(b.limits || [])}`);
  }
  // the spending boundary: a limit, or running without one chosen knowingly (agent_core.policy), and how much of the spend is priced
  function policyLine(b) {
    const p = b.policy, c = b.coverage;
    if (!p) return "";
    const cov = c && c.tokens ? `<p class="aos-note">Last 24 hours: ${c.priced_pct ?? 0}% of ${tok(c.tokens)} tokens can be priced (${tok(c.recorded_cost)} with a recorded cost, ${tok(c.priced_by_model)} at the model's list price)${c.unpriced ? `; <b>${tok(c.unpriced)} tokens have no model to price them by</b>` : ""}${c.runs_without_tokens ? `; ${c.runs_without_tokens} of ${c.runs} finished runs recorded no token count` : ""}.</p>` : "";
    const line = p.state === "unset"
      ? `<div class="aos-policy unset">${icon("alert")}<span><b>No spending boundary decided.</b> Set a daily limit above or a scoped limit below, or confirm that agents run without a cap.</span><button type="button" class="btn sm" data-aos-act="unlimited-on">Run without a cap</button></div>`
      : p.state === "unlimited"
        ? `<div class="aos-policy">${icon("info")}<span>Running without a daily cap, confirmed ${p.unlimited_by ? `by ${esc(p.unlimited_by)} ` : ""}${p.unlimited_at ? ago(p.unlimited_at) : ""}. Only missions and scoped limits stop work.</span><button type="button" class="btn sm ghost" data-aos-act="unlimited-off">Take it back</button></div>`
        : "";
    return line + cov;
  }
  // G5 scoped limits (agent_core ac_limits, /api/g5/limits): hard, checked before every model call of the runs they match
  const LIMIT_KEYS = { mission: "mx:12", team: "comp:3", agent: "workforce:5", contract: "swc:9 or co:41", system: "workforce", global: "" };
  function limitsBlock(L) {
    const rows = L.map(x => `<li><span class="aos-rt"><b>${esc(x.scope_label)} · ${esc(x.label || x.key)}</b><small>${x.tokens ? `${tok(x.spent)} of ${tok(x.tokens)} ${x.period === "day" ? "today" : "in all"}` : "no token limit"}${x.per_call ? ` · ${tok(x.per_call)} per call` : ""}${x.tokens ? ` · warns at ${x.warn_at}% · ${x.mode === "alert" ? "alerts only" : "stops at the limit"}` : ""}${x.blocked_7d ? ` · refused ${x.blocked_7d} call${x.blocked_7d === 1 ? "" : "s"} in 7 days` : ""}${x.origin && x.origin !== "manual" ? ` · ${esc(x.origin)}` : ""}</small></span>
        <button type="button" class="btn sm ghost" data-aos-act="limit-del" data-id="${x.id}" aria-label="Remove the limit on ${esc(x.label || x.key)}">${icon("trash")}</button></li>`).join("");
    return `<h4 class="aos-h4">Scoped limits</h4>${rows ? `<ul class="aos-list aos-limits">${rows}</ul>` : `<p class="aos-note">None. A Mission Control mission gets its dollar budget as one while it runs.</p>`}
      <form class="aos-limform" data-aos-limform>
        <label><span>On</span><select name="scope">${Object.keys(LIMIT_KEYS).map(k => `<option value="${k}">${k === "contract" ? "task contract" : k}</option>`).join("")}</select></label>
        <label><span>Which</span><input name="key" placeholder="${LIMIT_KEYS.mission}" maxlength="120"></label>
        <label><span>Tokens</span><input name="tokens" type="number" min="0" step="10000" inputmode="numeric"></label>
        <label><span>Per</span><select name="period"><option value="total">in all</option><option value="day">day</option></select></label>
        <label><span>Per call</span><input name="per_call" type="number" min="0" step="1000" inputmode="numeric" placeholder="none"></label>
        <label><span>Warn at %</span><input name="warn_pct" type="number" min="1" max="100" step="1" inputmode="numeric" placeholder="default"></label>
        <label><span>At the limit</span><select name="mode"><option value="stop">stop the work</option><option value="alert">alert only</option></select></label>
        <button type="button" class="btn sm" data-aos-act="limit-add">${icon("plus")}Add</button></form>
      <p class="aos-note">A limit warns at its share (or your default on Intelligence layers → Budgets) and, set to stop, stops the work it matches before its next model call once its scope has used that many tokens; a per-call limit caps each call's output and stops the run after a call goes over. Keys are the run ledger's: a mission <code>mx:N</code>, a team <code>comp:N</code> or <code>co-team:N</code>, an agent <code>system:id</code>, a contract <code>swc:N</code> or a run ref.</p>`;
  }
  // "Morgan sent you a report" under the name Morgan reads as "Morgan Morgan sent…": drop the repeated name
  const feedText = e => e.who && (e.text || "").startsWith(e.who + " ") ? e.text.slice(e.who.length + 1) : e.text || "";
  const feedItem = e => `<li><button type="button" class="aos-feedi" ${go(e.go)}><span class="aos-ft">${esc(ago(e.ts))}</span>${sysPill(e.system)}<span class="aos-fx"><b>${esc(e.who)}</b> ${esc(feedText(e))}</span></button></li>`;
  const runRow = r => `<li><button type="button" class="aos-row" data-aos-trace="${esc(r.trace)}" title="Open the execution trace"><span class="aos-lv l-${r.status === "failed" ? "stop" : r.status === "running" ? "run" : "warn"}"></span>
      <span class="aos-rt"><b>${esc(r.title || "Run")}</b><small>${esc(r.agent || "")}${r.agent ? " · " : ""}${esc(r.where)}${r.error ? " · " + esc(r.error) : ""}</small></span>${status(r.status)}<span class="aos-meta">${esc(when(r.finished || r.started))}</span></button></li>`;

  // ---------- Live operations ----------
  function live() {
    const waiting = d.approvals.slice(0, 10);
    const runTable = (rows, none) => rows.length ? `<div class="aos-tw"><table class="aos-table"><thead><tr><th>Run</th><th>Agent</th><th>Where</th><th>Status</th><th class="r">Tokens</th><th>Started</th><th></th></tr></thead><tbody>
      ${rows.map(r => `<tr><td><button type="button" class="aos-tl" data-aos-trace="${esc(r.trace)}">${esc(r.title || "Run")}</button>${r.error ? `<small class="aos-err">${esc(r.error)}</small>` : ""}</td>
        <td>${r.agent_key ? `<button type="button" class="aos-tl" data-aos-agent="${esc(r.agent_key)}">${esc(r.agent)}</button>` : esc(r.agent || "–")}</td><td>${sysPill(r.system)} <small>${esc(r.where)}</small></td>
        <td>${status(r.status)}</td><td class="r num">${tok(r.tokens)}</td><td>${esc(when(r.started))}</td><td><button type="button" class="btn sm" ${go(r.go)} title="Open where it runs">${icon("right")}</button></td></tr>`).join("")}</tbody></table></div>` : empty(none);
    return `<div class="aos-stack">
      ${card("radio", `Running now <span class="aos-n">${d.running.length}</span>`, `<span class="aos-note">Refreshes every 20 s · a run opens its trace</span>`, runTable(d.running, "Nothing runs right now."))}
      ${card("alert", `Failed in the last 24 hours <span class="aos-n">${d.failed.length}</span>`, "", runTable(d.failed, "No failures in the last day.") + (d.failed.length ? `<p class="aos-note">Retries happen on each run's own page (Workforce retries assignments; Competition teams send tasks back; the Company re-plans).</p>` : ""))}
      ${card("inbox", `Waiting for approval <span class="aos-n">${d.approvals.length}</span>`, `<button type="button" class="aos-link" ${go({ view: "approvals" })}>Approval Center${icon("right")}</button>`,
        waiting.length ? `<ul class="aos-list">${waiting.map(p => `<li><button type="button" class="aos-row" ${go(p.go)}><span class="aos-lv l-${esc(p.level)}"></span><span class="aos-rt"><b>${esc(p.title)}</b><small>${esc(p.where || p.source)}${p.detail ? " · " + esc(p.detail) : ""}</small></span><span class="aos-go">${esc(p.label || "Open")}${icon("right")}</span></button></li>`).join("")}</ul>` : empty("Nothing waits for you."))}
      ${card("clock", "Agent communication and events", "", d.activity.length ? `<ul class="aos-feed">${d.activity.map(feedItem).join("")}</ul>` : empty("No events yet."))}
    </div>`;
  }

  // ---------- Directory ----------
  function directory() {
    const systems = [...new Set(d.agents.map(a => a.system))];
    const q = f.q.trim().toLowerCase();
    const rows = d.agents.filter(a => (f.sys === "all" || a.system === f.sys) && (f.state === "all" || a.state === f.state)
      && (f.own === "all" || a.mine) && (!q || `${a.name} ${a.role} ${a.team}`.toLowerCase().includes(q)));
    const chip = (k, v, label, n) => `<button type="button" class="aos-chip" data-aos-f="${k}:${v}" aria-pressed="${f[k] === v}">${label}${n != null ? ` <em>${n}</em>` : ""}</button>`;
    return `<div class="aos-filters"><input type="search" id="aos-q" placeholder="Search agents by name, role or team" value="${esc(f.q)}" aria-label="Search agents">
        <div class="aos-chips">${chip("sys", "all", "All systems", d.agents.length)}${systems.map(s => chip("sys", s, esc(sys(s)[1]), d.agents.filter(a => a.system === s).length)).join("")}</div>
        <div class="aos-chips">${chip("state", "all", "Any state")}${Object.entries(STATE).map(([k, [t]]) => chip("state", k, t, d.agents.filter(a => a.state === k).length)).join("")}
          <span class="aos-chipsep"></span>${chip("own", f.own === "mine" ? "all" : "mine", "Only mine", d.agents.filter(a => a.mine).length).replace(/aria-pressed="(true|false)"/, `aria-pressed="${f.own === "mine"}"`)}</div></div>
      <div class="aos-tw"><table class="aos-table aos-dir"><thead><tr><th>Agent</th><th>System</th><th>Team</th><th>State</th><th class="r">Tokens · 7 d</th><th>Last active</th><th aria-label="Actions"></th></tr></thead><tbody>
      ${rows.slice(0, 300).map(a => `<tr><td><button type="button" class="aos-who" data-aos-agent="${esc(a.key)}">${avatar(a)}<span><b>${esc(a.name)}</b><small>${esc(a.role)}</small></span></button></td>
        <td>${sysPill(a.system)}</td><td><small>${esc(a.team)}</small></td><td>${statePill(a.state)}</td><td class="r num">${tok(a.tokens_week)}</td><td><small>${esc(when(a.last))}</small></td>
        <td class="r">${rowActs(a)}</td></tr>`).join("")
        || `<tr><td colspan="7">${empty("No agent matches.")}</td></tr>`}</tbody></table></div>
      ${rows.length > 300 ? `<p class="aos-note">Showing 300 of ${rows.length}. Narrow the search.</p>` : ""}`;
  }

  // chat and the action menu for agents of the Agents hub (agents.js runs both); other systems' agents are managed on their own page
  const hubId = a => a.key.slice(a.key.indexOf(":") + 1);
  function rowActs(a) {
    if (a.system !== "hub" && a.system !== "builtin") return "";
    return `<span class="aos-racts">${a.state !== "paused" ? `<button type="button" class="iconbtn sm" data-aos-chat="${esc(hubId(a))}" title="Chat with ${esc(a.name)}" aria-label="Chat with ${esc(a.name)}">${icon("chat")}</button>` : ""}
      ${a.system === "hub" ? `<button type="button" class="iconbtn sm" data-aos-menu="${esc(hubId(a))}" title="Actions" aria-label="Actions for ${esc(a.name)}">${icon("dots")}</button>` : ""}</span>`;
  }

  // ---------- Agent Studio ----------
  function studio() {
    if (!key) return empty(`Pick an agent in the <button type="button" class="aos-link" data-aos-sec="directory">Directory</button> to open it here.`);
    if (agentErr) return empty(esc(agentErr) + ` <button type="button" class="aos-link" data-aos-sec="directory">Back to the directory</button>`);
    if (!agent) return `<div class="aos-loading">${icon("radio")} Opening the agent…</div>`;
    const a = agent, m = a.evaluations.metrics;
    return `<button type="button" class="aos-back" data-aos-sec="directory">${icon("left")}All agents</button>
      <div class="aos-id">${avatar(a)}<div class="aos-idt"><h2>${esc(a.name)}</h2><p>${esc(a.role)}${a.team ? " · " + esc(a.team) : ""}</p>
        <div class="aos-idp">${sysPill(a.system)}${statePill(a.state)}${a.can_edit ? `<span class="aos-pill">${icon("edit")}Editable here</span>` : `<span class="aos-pill">${icon("lock")}Managed on its own page</span>`}</div></div>
        <div class="aos-acts">${(a.manage || []).map((x, i) => `<button type="button" class="btn sm ${i || a.system !== "hub" && a.system !== "builtin" ? "" : "primary"}" ${go(x.go)}>${esc(x.label)}${icon("right")}</button>`).join("")}
          ${mine() ? `<button type="button" class="btn sm" data-aos-edit="${esc(hubId(a))}">${icon("edit")}Edit</button><button type="button" class="iconbtn" data-aos-menu="${esc(hubId(a))}" title="More actions" aria-label="More actions">${icon("dots")}</button>` : ""}</div></div>
      <nav class="aos-tabs" role="tablist" aria-label="${esc(a.name)}">${TABS.map(([id, t]) => `<button type="button" role="tab" data-aos-tab="${id}" aria-selected="${tab === id}">${t}${count(id)}</button>`).join("")}</nav>
      <div class="aos-pane">${pane(a, m)}</div>`;
  }
  function count(id) {
    const a = agent, n = { skills: a.skills.length, tools: a.tools.length, memory: a.memory.length, tasks: a.tasks.length, evaluations: a.evaluations.items.length, versions: a.versions.length, activity: a.activity.length }[id];
    return n ? ` <em>${n}</em>` : "";
  }
  function pane(a, m) {
    switch (tab) {
      case "instructions": return instructions(a);
      case "skills": return skills(a);
      case "tools": return a.tools.length ? `<div class="aos-tw"><table class="aos-table"><thead><tr><th>Tool</th><th>Kind</th><th>Allowed</th></tr></thead><tbody>${a.tools.map(t => `<tr><td><b>${esc(t.label)}</b><small class="mono"> ${esc(t.name)}</small></td><td>${esc(t.kind)}</td><td>${t.enabled ? status("on") : status("off")}</td></tr>`).join("")}</tbody></table></div>
          <p class="aos-note">${a.system === "company" ? "Contract permissions and chat tools. Change them in its Company workspace; contract changes need an approval." : a.can_edit ? "AXoR's own tools only read data. MCP tools do what their server allows: give them below." : a.system === "teams" ? "MCP tools come from the team: give them on the team's Agents tab." : "Permissions are set where the agent is managed."}</p>
          ${mine() ? `<div class="aos-mcp" data-tmc-scope="hub:${esc(hubId(a))}"></div>` : ""}` : empty("No tools listed for this agent.");
      case "memory": return a.memory.length ? `<ul class="aos-mem">${a.memory.map(x => `<li><p>${esc(x.text)}</p><small>${esc(x.source || "")} · ${esc(when(x.ts))}</small></li>`).join("")}</ul>` : empty("Nothing remembered yet.");
      case "tasks": return a.tasks.length ? `<div class="aos-tw"><table class="aos-table"><thead><tr><th>Task</th><th>Status</th><th class="r">Tokens</th><th>When</th></tr></thead><tbody>${a.tasks.map(t => `<tr><td>${t.trace ? `<button type="button" class="aos-tl" data-aos-trace="${esc(t.trace)}">${esc(t.title || "Task")}</button>` : `<b>${esc(t.title || "Task")}</b>`}${t.detail ? `<small> ${esc(t.detail)}</small>` : ""}</td><td>${status(t.status)}</td><td class="r num">${t.tokens == null ? "–" : tok(t.tokens)}</td><td><small>${esc(when(t.ts))}</small></td></tr>`).join("")}</tbody></table></div>` : empty("No tasks or chats yet.");
      case "evaluations": return evaluations(a, m);
      case "versions": return versions(a);
      case "activity": return a.activity.length ? `<ul class="aos-feed">${a.activity.map(e => `<li><span class="aos-feedi static"><span class="aos-ft">${esc(when(e.ts))}</span><span class="aos-pill">${esc(e.kind || "event")}</span><span class="aos-fx">${esc(e.text || "")}${e.tokens ? ` <small>· ${tok(e.tokens)} tokens</small>` : ""}</span></span></li>`).join("")}</ul>` : empty("No activity recorded yet.");
      default: return agentOverview(a, m);
    }
  }
  function agentOverview(a, m) {
    const stat = (l, v, s) => `<div class="aos-stat"><span>${l}</span><b>${v}</b>${s ? `<small>${s}</small>` : ""}</div>`;
    return `<div class="aos-grid">
      ${card("info", "Identity", "", `<p class="aos-about">${esc(a.about || "No description.")}</p><dl class="aos-dl">${a.settings.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(String(v ?? "–"))}</dd>`).join("")}</dl>`)}
      ${card("chart", "Performance", "", m.runs ? `<div class="aos-stats">${stat("Success rate", pct(m.success_rate), `${m.done} done · ${m.failed} failed`)}${stat("First attempt", pct(m.first_attempt))}${stat("Avg latency", secs(m.avg_latency))}${stat("Tokens / success", tok(m.tokens_per_success))}${m.avg_score != null ? stat("Avg score", m.avg_score) : ""}</div>`
        : empty(a.system === "hub" || a.system === "builtin" ? "Chats aren't scored as tasks. Ratings and tests are under Evaluations." : "No runs yet."))}
      ${card("clock", "Current and recent work", `<button type="button" class="aos-link" data-aos-tab="tasks">All tasks${icon("right")}</button>`,
        a.recent_runs.length ? `<ul class="aos-list">${a.recent_runs.slice(0, 6).map(r => r.trace ? runRow({ ...r, agent: "", where: r.model || "" }) : `<li><span class="aos-row static"><span class="aos-rt"><b>${esc(r.title || "Run")}</b></span>${status(r.status)}</span></li>`).join("")}</ul>`
          : a.tasks.length ? `<ul class="aos-list">${a.tasks.slice(0, 6).map(t => `<li><button type="button" class="aos-row" ${t.trace ? `data-aos-trace="${esc(t.trace)}"` : "disabled"}><span class="aos-rt"><b>${esc(t.title || "Task")}</b><small>${esc(when(t.ts))}</small></span>${status(t.status)}</button></li>`).join("")}</ul>` : empty("Nothing yet."))}
    </div>`;
  }
  function instructions(a) {
    const text = draft ?? a.instructions.text;
    if (!mine()) return `${a.instructions.text ? `<pre class="aos-pre">${esc(a.instructions.text)}</pre>` : ""}<p class="aos-note">${esc(a.instructions.note || "")}</p>${a.can_test ? testPanel(a, false) : ""}`;
    const dirty = draft != null && draft !== a.instructions.text;
    return `<div class="aos-edit"><label for="aos-ins">System instructions <small>${text.length} / 8000</small></label>
        <textarea id="aos-ins" rows="12" maxlength="8000" spellcheck="true">${esc(text)}</textarea>
        <div class="aos-row-acts"><button type="button" class="btn sm primary" data-aos-act="save" ${dirty ? "" : "disabled"}>${icon("check")}Save as a new version</button>
          <button type="button" class="btn sm" data-aos-act="revert" ${dirty ? "" : "disabled"}>Discard changes</button>
          <span class="aos-note">${dirty ? "Unsaved draft. Try it below before you save." : "Saved. Every save is kept under Versions."}</span></div></div>
      ${testPanel(a, dirty)}`;
  }
  function testPanel(a, dirty) {
    const o = testOut;
    return `<section class="aos-test"><h4>${icon("zap")}Test ${dirty ? "the draft" : "the saved instructions"} on one message</h4>
      <div class="aos-tin"><input id="aos-tmsg" placeholder="${esc(a.examples?.[0] || "Ask what you'd ask it in a chat")}" maxlength="4000" aria-label="Test message">
        <button type="button" class="btn sm primary" data-aos-act="test" ${testBusy ? "disabled" : ""}>${testBusy ? "Running…" : `${icon("send")}Run test`}</button></div>
      <p class="aos-note">Read-only tools, nothing remembered, nothing saved except the result under Evaluations. Tokens count like a chat's.</p>
      ${o ? `<div class="aos-tout ${o.error ? "bad" : ""}"><div class="aos-tmeta">${o.draft ? "Draft" : o.version ? "v" + o.version : "Saved"} · ${esc(o.model || "")} · ${tok(o.tokens)} tokens · ${secs(o.ms / 1000)}${o.tools?.length ? " · tools: " + esc(o.tools.join(", ")) : ""}</div>
        ${o.error ? `<p>${esc(o.error)}</p>` : `<div class="aos-md">${Agents.md(o.answer || "(no answer)")}</div>`}</div>` : ""}</section>`;
  }
  function skills(a) {
    if (!mine()) return a.skills.length ? `<ul class="aos-skl">${a.skills.map(s => `<li><b>${esc(s.name)}</b><small>${esc(s.description || "")}</small></li>`).join("")}</ul>` : empty("No skills on this agent.");
    const on = new Set(draftSkills ?? a.skills.map(s => s.id));
    const dirty = draftSkills != null;
    return `<p class="aos-note">Skills are playbooks added to the agent's instructions. Up to 10. Write your own in Agents → Skill hub.</p>
      <ul class="aos-skl pick">${a.skill_catalog.map(s => `<li><label><input type="checkbox" data-aos-skill="${esc(s.id)}" ${on.has(s.id) ? "checked" : ""}><span><b>${esc(s.name)}</b><small>${esc(s.description || "")}</small></span></label></li>`).join("")}</ul>
      <div class="aos-row-acts"><button type="button" class="btn sm primary" data-aos-act="save-skills" ${dirty ? "" : "disabled"}>${icon("check")}Save as a new version</button>
        <button type="button" class="btn sm" data-aos-act="revert-skills" ${dirty ? "" : "disabled"}>Discard</button><span class="aos-note">${on.size} of 10</span></div>`;
  }
  let draftSkills = null;
  function evaluations(a, m) {
    const vt = a.evaluations.versions || [];
    return `${m.runs ? `<div class="aos-stats">${[["Runs", m.runs], ["Success rate", pct(m.success_rate)], ["First attempt", pct(m.first_attempt)], ["Avg latency", secs(m.avg_latency)], ["Tokens", tok(m.tokens)], ["Tokens / success", tok(m.tokens_per_success)], ["Avg score", m.avg_score ?? "–"]].map(([l, v]) => `<div class="aos-stat"><span>${l}</span><b>${v}</b></div>`).join("")}</div>` : ""}
      ${vt.length ? card("branch", "By version", "", `<div class="aos-tw"><table class="aos-table"><thead><tr><th>Version</th><th class="r">Runs</th><th class="r">Success</th><th class="r">Change</th><th class="r">First attempt</th><th class="r">Tokens / success</th></tr></thead><tbody>
        ${vt.map(v => `<tr class="${v.regression ? "aos-reg" : ""}"><td>v${v.version}${v.regression ? ` <span class="aos-st t-crit">regression</span>` : ""}</td><td class="r num">${v.runs}</td><td class="r num">${pct(v.success_rate)}</td><td class="r num">${v.delta == null ? "–" : (v.delta > 0 ? "+" : "") + Math.round(v.delta * 100) + " pts"}</td><td class="r num">${pct(v.first_attempt)}</td><td class="r num">${tok(v.tokens_per_success)}</td></tr>`).join("")}</tbody></table></div>
        <p class="aos-note">A drop of more than 5 points against the previous version, over at least 3 finished runs, is flagged as a regression.</p>`) : ""}
      ${a.evaluations.improvements?.length ? card("bulb", "Improvements", `<button type="button" class="aos-link" ${go({ view: "workforce" })}>Workforce${icon("right")}</button>`, `<ul class="aos-list">${a.evaluations.improvements.map(i => `<li><span class="aos-row static"><span class="aos-rt"><b>${esc(i.title)}</b><small>v${i.from ?? "?"} → ${i.to ? "v" + i.to : "candidate"}${i.result ? " · " + esc(i.result) : ""}</small></span>${status(i.status)}</span></li>`).join("")}</ul>`) : ""}
      ${card("trophy", "Results", "", a.evaluations.items.length ? `<ul class="aos-list">${a.evaluations.items.map(e => `<li><span class="aos-row static"><span class="aos-rt"><b>${esc(e.title)}</b><small>${esc(e.detail || "")}${e.ts ? " · " + esc(when(e.ts)) : ""}${e.tokens ? ` · ${tok(e.tokens)} tokens` : ""}</small></span>${e.score != null ? `<span class="aos-score">${esc(String(e.score))}</span>` : ""}${status(e.status)}</span></li>`).join("")}</ul>` : empty("No evaluations yet."))}
      <p class="aos-note">${esc(a.evaluations.note || "")} Fixed benchmarks and experiments: <button type="button" class="aos-link" ${go({ view: "evaluation" })}>Agent evaluation</button>.</p>`;
  }
  function versions(a) {
    const vs = a.versions;
    if (!vs.length) return empty(mine() ? "No versions yet. The first save (Instructions, Skills or Edit) starts the history." : "This system keeps no versions for the agent.");
    const A = vs.find(v => v.version === cmp.a), B = vs.find(v => v.version === cmp.b);
    const o = cmp.out;
    return `<div class="aos-tw"><table class="aos-table aos-vers"><thead><tr><th>Compare</th><th>Version</th><th>Note</th><th>By</th><th>When</th><th></th></tr></thead><tbody>
      ${vs.map(v => `<tr><td><label class="aos-cmp"><input type="checkbox" data-aos-cmp="${v.version}" ${cmp.a === v.version || cmp.b === v.version ? "checked" : ""} aria-label="Compare ${esc(v.label)}"></label></td>
        <td><b>${esc(v.label)}</b>${v.current ? ` <span class="aos-st t-ok">current</span>` : ""}</td><td><small>${esc(v.note || "")}</small></td><td><small>${esc(v.author || "")}</small></td><td><small>${esc(when(v.ts))}</small></td>
        <td>${mine() && !v.current ? `<button type="button" class="btn sm" data-aos-restore="${v.version}">Restore</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
      <p class="aos-note">Tick two versions to compare their ${a.system === "hub" || a.system === "workforce" ? "instructions" : "configuration"}${mine() ? " and try both on the same message" : ""}. Restoring makes a new version; nothing is lost.</p>
      ${A && B ? `<section class="aos-diffw"><h4>${esc(A.label)} → ${esc(B.label)}</h4>${diff(A.text || "", B.text || "")}
        ${mine() ? `<div class="aos-tin"><input id="aos-cmsg" placeholder="One message for both versions" value="${esc(cmp.msg)}" maxlength="4000" aria-label="Message for both versions"><button type="button" class="btn sm primary" data-aos-act="compare" ${cmp.busy ? "disabled" : ""}>${cmp.busy ? "Running both…" : `${icon("zap")}Run both`}</button></div>
          ${o ? `<div class="aos-side">${[[A, o[0]], [B, o[1]]].map(([v, r]) => `<div class="aos-tout ${r.error ? "bad" : ""}"><div class="aos-tmeta">${esc(v.label)} · ${tok(r.tokens)} tokens · ${secs((r.ms || 0) / 1000)}${r.tools?.length ? " · tools: " + esc(r.tools.join(", ")) : ""}</div>${r.error ? `<p>${esc(r.error)}</p>` : `<div class="aos-md">${Agents.md(r.answer || "(no answer)")}</div>`}</div>`).join("")}</div>` : ""}` : ""}</section>` : ""}`;
  }
  // a line diff (longest common subsequence): removed lines red, added green
  function diff(x, y) {
    const a = x.split("\n"), b = y.split("\n");
    if (a.length * b.length > 250000) return `<p class="aos-note">Too long to compare line by line.</p>`;
    const L = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
    for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    const out = []; let i = 0, j = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { out.push(["", a[i]]); i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) out.push(["del", a[i++]]); else out.push(["add", b[j++]]);
    }
    while (i < a.length) out.push(["del", a[i++]]);
    while (j < b.length) out.push(["add", b[j++]]);
    if (!out.some(([k]) => k)) return `<p class="aos-note">No differences.</p>`;
    return `<pre class="aos-diff">${out.map(([k, t]) => `<span class="${k}">${k === "add" ? "+ " : k === "del" ? "− " : "  "}${esc(t)}</span>`).join("\n")}</pre>`;
  }

  // ---------- Connected ----------
  function connected() {
    const s = d.systems, n = k => s[k]?.agents || 0;
    const items = [
      ["branch", "Orchestration", "Workforce", "Missions broken down by the CEO and run by standing teams: sequential and parallel steps, dependencies, handoffs, retries, budgets, debate and approval gates.", { view: "workforce" }, `${n("workforce")} agents`],
      ["users", "Teams & squads", "Company · Competition teams", "Dynamic teams per project with leads and evaluators; a 20-agent squad per subnet competition with autopilot.", { view: "company", tab: "projects" }, `${n("company") + n("teams")} agents`],
      ["list", "Workflows & tasks", "Task board", "Every task from every system on one board, in five lanes.", { view: "missions" }, `${d.counts.running} running`],
      ["trophy", "Evaluations & benchmarks", "Agent evaluation", "Scores, benchmarks and experiments, models in use, long tasks, knowledge and skills.", { view: "evaluation" }, ""],
      ["bulb", "Recommendations & experiments", "Workforce · My subnets", "Improvement Engineer trials on diagnosed and held-out tasks; a change is promoted only after your approval.", { view: "workforce" }, ""],
      ["inbox", "Approvals, permissions & audit", "Approval Center", "Every request that waits for you, executions, the audit trail and agent permissions.", { view: "approvals" }, `${d.counts.approvals} waiting`],
      ["target", "Knowledge & memory", "Portfolio", "Shared knowledge in three tiers, kept by the Knowledge Manager, plus each agent's own memory (Studio → Memory).", { view: "portfolio" }, ""],
      ...(d.admin ? [["flag", "Platform watch", "Agent HQ", "Field agents patrol AXoR's services; leads review every fix before it runs.", { view: "hq" }, `${n("hq")} agents`]] : []),
    ];
    return `<p class="aos-lede2">The Agent Workspace connects to these modules rather than copying them. Each card opens the page that does the work.</p>
      <div class="aos-cgrid">${items.map(([ic, t, where, txt, g, c]) => `<button type="button" class="aos-conn" ${go(g)}><span class="aos-ci">${icon(ic)}</span><span class="aos-ct"><b>${esc(t)}</b><small>${esc(where)}</small><span>${esc(txt)}</span></span>${c ? `<em>${esc(c)}</em>` : ""}</button>`).join("")}</div>`;
  }

  // ---------- the execution trace ----------
  async function trace(k) {
    closeTrace();
    const el = document.createElement("div");
    el.id = "aos-trace"; el.className = "aos-drawer"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Execution trace");
    el.innerHTML = `<div class="aos-dw"><header><h3>${icon("route")}Execution trace</h3><button type="button" class="iconbtn" data-aos-act="close-trace" aria-label="Close">${icon("close")}</button></header><div class="aos-db">${icon("radio")} Loading…</div></div>`;
    document.body.appendChild(el);
    el.querySelector("[data-aos-act=close-trace]").focus();
    try {
      const t = await api("/api/studio/traces/" + k.split(":").map(encodeURIComponent).join(":"));
      const t0 = t.started || t.spans.find(s => s.ts)?.ts;
      el.querySelector(".aos-db").innerHTML = `<h4>${esc(t.title)}</h4><p class="aos-tmeta">${esc(t.who)} · ${status(t.status)} · ${tok(t.tokens)} tokens${t.model ? " · " + esc(t.model) : ""}${t.started ? " · started " + esc(ago(t.started)) : ""}${t.finished && t.started ? " · took " + secs(t.finished - t.started) : ""}</p>
        ${t.error ? `<p class="aos-err">${esc(t.error)}</p>` : ""}
        ${t.spans.length ? `<ol class="aos-spans">${t.spans.map(s => `<li class="${s.error ? "bad" : ""}"><div class="aos-sh"><span class="aos-pill">${esc(s.kind || "step")}</span><b>${esc(s.name || "")}</b>${s.ts && t0 ? `<small>+${secs(s.ts - t0)}</small>` : ""}${s.end && s.ts ? `<small>${secs(s.end - s.ts)}</small>` : ""}${s.tokens ? `<small>${tok(s.tokens)} tok</small>` : ""}</div>
          ${s.input ? `<details><summary>Input</summary><pre>${esc(s.input)}</pre></details>` : ""}${s.output ? `<details ${t.spans.length < 4 ? "open" : ""}><summary>Output</summary><pre>${esc(s.output)}</pre></details>` : ""}</li>`).join("")}</ol>` : `<p class="aos-empty">No steps were recorded for this run.</p>`}
        ${t.output ? `<details><summary>Result</summary><pre>${esc(t.output)}</pre></details>` : ""}`;
    } catch (e) { el.querySelector(".aos-db").innerHTML = `<p class="aos-empty">${esc(e.message)}</p>`; }
  }
  function closeTrace() { $("#aos-trace")?.remove(); }

  // ---------- actions ----------
  async function hubBody(changes) {
    const all = await api("/api/agents/custom");
    const a = [...all.mine].find(x => x.id === agent.id);
    if (!a) throw new Error("Only the agent's creator can change it.");
    return { name: a.name, role: a.role, description: a.description, instructions: a.instructions, icon: a.icon, color: a.color, face: a.face ?? null, kind: a.kind ?? null,
             skills: a.skills, examples: a.examples, shared_with: a.shared_with || [], in_directory: a.in_directory, status: a.status, ...changes };
  }
  async function save(changes, msg) {
    try {
      await api(`/api/agents/custom/${agent.id}`, { method: "PUT", body: await hubBody(changes) });
      draft = null; draftSkills = null; toast(msg); openAgent(key, true);
    } catch (e) { toast(e.message, { kind: "error" }); }
  }
  async function runTest(body) {
    return api(`/api/studio/agents/${encodeURIComponent(key)}/test`, { method: "POST", body });
  }
  function act(name, t) {
    if (name === "refresh") { sig = ""; load(true); if (sec === "studio" && key) openAgent(key, true); return; }
    if (name === "limit-add" || name === "limit-del") {
      const f = t.closest("[data-aos-limform]"), v = n => f?.elements[n]?.value.trim();
      const req = name === "limit-del" ? api(`/api/g5/limits/${+t.dataset.id}`, { method: "DELETE" })
        : api("/api/g5/limits", { method: "PUT", body: { scope: v("scope"), key: v("key") || "", tokens: v("tokens") ? Math.round(+v("tokens")) : null, period: v("period"),
                                                           per_call: v("per_call") ? Math.round(+v("per_call")) : null,
                                                           warn_pct: v("warn_pct") ? Math.round(+v("warn_pct")) : null, mode: v("mode") || "stop" } });
      req.then(() => { toast(name === "limit-del" ? "Limit removed" : "Limit set: it applies from the next model call"); load(true); }).catch(e => toast(e.message, { kind: "error" }));
      return;
    }
    if (name === "unlimited-on" || name === "unlimited-off") {
      const on = name === "unlimited-on";
      const go = () => api("/api/studio/budget", { method: "PUT", body: { unlimited: on } }).then(() => { toast(on ? "Running without a daily cap: noted" : "Taken back: set a limit"); load(true); }).catch(e => toast(e.message, { kind: "error" }));
      return on ? UI.confirm({ title: "Run agents without a daily cap?", body: "Nothing stops agent work by tokens except missions' own budgets and any scoped limits. You can set a limit at any time.", ok: "Run without a cap", icon: "alert", danger: false }).then(y => y && go()) : go();
    }
    if (name === "create") return Agents.create();
    if (name === "close-trace") return closeTrace();
    if (name === "save") return save({ instructions: draft }, "Saved as a new version.");
    if (name === "revert") { draft = null; testOut = null; return draw(); }
    if (name === "save-skills") return save({ skills: draftSkills }, "Skills saved as a new version.");
    if (name === "revert-skills") { draftSkills = null; return draw(); }
    if (name === "test") {
      const msg = $("#aos-tmsg")?.value.trim() || agent.examples?.[0] || "";
      if (!msg) return toast("Type a test message.");
      testBusy = true; draw();
      const keep = msg;
      runTest({ message: msg, instructions: draft != null && draft !== agent.instructions.text ? draft : null })
        .then(o => { testOut = o; }).catch(e => { testOut = { error: e.message }; })
        .finally(() => { testBusy = false; if (sec === "studio" && tab === "instructions") { draw(); const i = $("#aos-tmsg"); if (i) i.value = keep; } });
      return;
    }
    if (name === "compare") {
      cmp.msg = $("#aos-cmsg")?.value.trim() || "";
      if (!cmp.msg) return toast("Type one message for both versions.");
      cmp.busy = true; draw();
      Promise.all([cmp.a, cmp.b].map(v => runTest({ message: cmp.msg, version: v }).catch(e => ({ error: e.message }))))
        .then(r => { cmp.out = r; }).finally(() => { cmp.busy = false; if (tab === "versions") draw(); });
    }
  }
  function follow(g) {
    if (!g) return;
    if (g.view === "agents" && g.agent != null) { Agents.openAgent(String(g.agent)); setView("agents"); return; }
    if (g.view === "company" && g.agent != null) {
      Command.follow({ view: "company", tab: "agents" });
      const t0 = Date.now(), tick = () => { if ($("#view-company [data-cotab='agents'][aria-selected='true']")) CompanyAgents.open(g.agent); else if (Date.now() - t0 < 6000) setTimeout(tick, 150); };
      return tick();
    }
    Command.follow(g);
  }
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const t = e.target;
      if (t.closest("#aos-trace")) {
        if (t.closest("[data-aos-act=close-trace]") || t.id === "aos-trace") closeTrace();
        return;
      }
      if (!t.closest("#aos")) return;
      const s = t.closest("[data-aos-sec]"); if (s && !s.disabled) { sec = s.dataset.aosSec; pref("sec", sec); if (sec === "studio" && key && !agent) return openAgent(key, true); return draw(); }
      const g = t.closest("[data-aos-go]"); if (g) return follow(gos[+g.dataset.aosGo]);
      const ch = t.closest("[data-aos-chat]"); if (ch) return Agents.chat(ch.dataset.aosChat);
      const ed = t.closest("[data-aos-edit]"); if (ed) return Agents.edit(ed.dataset.aosEdit);
      const mn = t.closest("[data-aos-menu]"); if (mn) { e.stopPropagation(); return Agents.menu(mn, mn.dataset.aosMenu); }
      const a = t.closest("[data-aos-agent]"); if (a) return openAgent(a.dataset.aosAgent);
      const tr = t.closest("[data-aos-trace]"); if (tr) return trace(tr.dataset.aosTrace);
      const tb = t.closest("[data-aos-tab]"); if (tb) { tab = tb.dataset.aosTab; return draw(); }
      const fl = t.closest("[data-aos-f]"); if (fl) { const [k, v] = fl.dataset.aosF.split(":"); f[k] = v; return draw(); }
      const rs = t.closest("[data-aos-restore]");
      if (rs) {
        const v = +rs.dataset.aosRestore;
        UI.confirm({ title: `Restore v${v}?`, body: "Its instructions and skills become the current configuration, saved as a new version. Nothing is lost.", ok: "Restore", icon: "undo", danger: false }).then(y => y && restore(v));
        return;
      }
      const ac = t.closest("[data-aos-act]"); if (ac) return act(ac.dataset.aosAct, ac);
    });
    document.addEventListener("input", e => {
      const t = e.target;
      if (t.id === "aos-q") { f.q = t.value; const pos = t.selectionStart; draw(); const n = $("#aos-q"); n.focus(); n.setSelectionRange(pos, pos); }
      else if (t.id === "aos-ins") {
        const was = draft != null && draft !== agent.instructions.text;
        draft = t.value;
        const now = draft !== agent.instructions.text;
        $(".aos-edit label small").textContent = `${draft.length} / 8000`;
        if (was !== now) { $$("[data-aos-act=save], [data-aos-act=revert]").forEach(b => b.disabled = !now); $(".aos-edit .aos-note").textContent = now ? "Unsaved draft. Try it below before you save." : "Saved. Every save is kept under Versions."; $(".aos-test h4").lastChild.textContent = `Test ${now ? "the draft" : "the saved instructions"} on one message`; }
      }
    });
    document.addEventListener("change", async e => {
      const t = e.target;
      if (t.dataset.aosBudget != null) {
        const v = t.value.trim() === "" ? null : Math.max(0, Math.round(+t.value || 0));
        try { await api("/api/studio/budget", { method: "PUT", body: { daily_tokens: v } }); toast(v ? `Daily limit: ${tok(v)} tokens` : "No daily limit"); load(true); }
        catch (x) { toast(x.message); }
        return;
      }
      if (t.dataset.aosSkill != null) {
        const on = new Set(draftSkills ?? agent.skills.map(s => s.id));
        t.checked ? on.add(t.dataset.aosSkill) : on.delete(t.dataset.aosSkill);
        if (on.size > 10) { t.checked = false; on.delete(t.dataset.aosSkill); toast("Up to 10 skills."); }
        draftSkills = [...on]; draw();
      }
      if (t.dataset.aosCmp != null) {
        const v = +t.dataset.aosCmp;
        if (t.checked) { if (cmp.a == null) cmp.a = v; else if (cmp.b == null) cmp.b = v; else { cmp.a = cmp.b; cmp.b = v; } }
        else { if (cmp.a === v) cmp.a = null; if (cmp.b === v) cmp.b = null; }
        if (cmp.a != null && cmp.b != null && cmp.a > cmp.b) [cmp.a, cmp.b] = [cmp.b, cmp.a];
        cmp.out = null; draw();
      }
    });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && $("#aos-trace")) { closeTrace(); return; }
      if (e.key === "Enter" && e.target.id === "aos-tmsg") act("test");
      if (e.key === "Enter" && e.target.id === "aos-cmsg") act("compare");
    });
  }
  async function restore(v) {
    try { agent = await api(`/api/studio/agents/${encodeURIComponent(key)}/restore`, { method: "POST", body: { version: v } }); draft = null; draftSkills = null; cmp = { a: null, b: null, msg: "", out: null, busy: false }; toast(`Restored v${v} as a new version.`); draw(); }
    catch (e) { toast(e.message, { kind: "error" }); }
  }

  // the Agents page's rail and the agents.js menu actions: show a section, or reload after a change
  const section = s => { sec = s; pref("sec", s); if (sec === "studio" && key && !agent) return openAgent(key, true); draw(); };
  const reload = () => { sig = ""; load(true); if (sec === "studio" && key) openAgent(key, true); };
  const forget = k => { if (key !== k) return; key = null; pref("key", null); agent = null; if (sec === "studio") { sec = "directory"; pref("sec", sec); } };  // a deleted agent
  return { open, stop, show, section, reload, forget, redraw: () => { if (sec === "ecosystem") draw(); } };
})();
