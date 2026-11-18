/* AXoR 2.0 hubs (hubs.py, hubs.css; prefix axh-, with command.css's occ- cards and pills): one page per area, over the systems
   that already do the work. Every row leads to the page that owns it (Command.follow); nothing is decided or started here.
   - Portfolio & projects (projects) and Missions & tasks (missions): every project on one scale, every task on one board, dependencies.
   - Agent evaluation (evaluation): scores, benchmarks and experiments, models, long tasks, knowledge and skills.
   - Workspace home (home) and Settings (settings).
   hub-intel.js (Bittensor Intelligence) and hub-infra.js (Platform overview) register their pages here too.
   A page polls every 30 s while it shows and redraws only when something changed. */
const Hubs = (() => {
  const reg = {};
  const SYS = { company: ["layers", "Company"], workforce: ["group", "Workforce"], teams: ["users", "Competition teams"], projects: ["cycle", "Project team"],
                longtasks: ["route", "Long tasks"], agents: ["bot", "Your agents"], hq: ["flag", "Agent HQ"], mining: ["trophy", "My subnets"], portfolio: ["target", "Portfolio"],
                account: ["key", "Your account"] };
  const EVERY = 30000;
  let view = "", sig = "", seq = 0, timer = null, wired = false, gos = [];
  const cache = {}, st = {};  // per URL: {at, d, err}; per page: {tab, f, q}
  const S_ = v => st[v] ||= { tab: (() => { try { return localStorage.getItem("hub.tab." + v) || ""; } catch { return ""; } })(), f: "all", q: "" };

  // ---------- shared pieces (hub-intel.js and hub-infra.js use them too) ----------
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : String(Math.round(n));
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const go = x => x ? `data-axh-go="${gos.push(x) - 1}"` : "";
  const sys = k => SYS[k] || ["info", k];
  const pill = (cls, text, ic) => `<span class="occ-pill ${cls}">${ic ? icon(ic) : "<i></i>"}${esc(text)}</span>`;
  const sysPill = k => pill("src", sys(k)[1], sys(k)[0]);
  const empty = t => `<p class="occ-empty">${t}</p>`;
  const card = (cls, ic, title, extra, body) => `<section class="card occ-card axh-card ${cls}"><div class="occ-ch"><h3>${icon(ic)}${title}</h3>${extra || ""}</div>${body}</section>`;
  const kpi = (ic, label, value, sub, tone, to) => {
    const tag = to ? `button type="button" data-axh-to="${to}"` : "div";
    return `<${tag} class="stat occ-kpi ${tone ? "t-" + tone : ""}"><div class="label">${icon(ic)}${label}</div><div class="value">${esc(String(value))}</div><div class="sub">${esc(sub || "")}</div></${to ? "button" : "div"}>`;
  };
  const meter = (x, title, cls = "") => `<span class="occ-prog axh-meter ${cls}" title="${esc(title || "")}"><i style="width:${Math.max(0, Math.min(100, (x || 0) * 100)).toFixed(0)}%"></i></span>`;
  // a horizontal bar chart: one hue, the value as text beside each bar, the bar's own tooltip (dataviz: thin marks, text in text colors)
  const bars = (items, fmt = tok, opts = {}) => {
    if (!items.length) return empty(opts.none || "Nothing to show yet.");
    const max = Math.max(...items.map(i => i.value), 1e-9);
    return `<ul class="axh-bars" role="list">${items.map(i => `<li><${i.go || i.open != null ? `button type="button" ${i.go ? go(i.go) : `data-open="${i.open}"`}` : "span"} class="axh-bar-l" title="${esc(i.title || i.label)}">${esc(i.label)}</${i.go || i.open != null ? "button" : "span"}>
      <span class="axh-bar-t" title="${esc(i.title || `${i.label}: ${fmt(i.value)}`)}"><i class="${i.tone || ""}" style="width:${Math.max(1.5, i.value / max * 100).toFixed(1)}%"></i></span><b class="num">${esc(fmt(i.value))}</b></li>`).join("")}</ul>`;
  };
  const state = s => {  // any system's status word → a pill tone
    const k = String(s || "").toLowerCase();
    if (/^(active|running|working|doing|live|ok|success|done|approved|consumed|available|ready|healthy)$/.test(k)) return "s-ok";
    if (/^(failed|error|stuck|rejected|blocked|down|crit)/.test(k)) return "s-crit";
    if (/^(waiting|review|paused|pending|proposed|planning|testing|warn|dissolving|stopping)/.test(k)) return "s-warn";
    if (/^(queued|todo|plan|do|check|act|evaluating|checking|better)$/.test(k)) return "s-info";
    return "s-off";
  };
  const chips = (v, counts, labelOf) => {
    const s = S_(v), keys = Object.keys(counts).filter(k => counts[k]);
    if (keys.length < 2) return "";
    if (s.f !== "all" && !counts[s.f]) s.f = "all";
    const all = Object.values(counts).reduce((a, b) => a + b, 0);
    return `<div class="occ-filters" role="group" aria-label="Filter"><button type="button" class="chip" data-axh-f="all" aria-pressed="${s.f === "all"}">All <b>${all}</b></button>
      ${keys.map(k => { const [ic, l] = labelOf(k); return `<button type="button" class="chip" data-axh-f="${k}" aria-pressed="${s.f === k}">${icon(ic)}${esc(l)} <b>${counts[k]}</b></button>`; }).join("")}</div>`;
  };
  const search = (v, ph) => `<label class="search occ-q"><span class="sr">${esc(ph)}</span>${icon("search")}<input type="search" data-axh-q placeholder="${esc(ph)}" value="${esc(S_(v).q)}" autocomplete="off"></label>`;
  const tabs = (v, list) => {
    const s = S_(v);
    if (!list.some(([k]) => k === s.tab)) s.tab = list[0][0];
    return `<nav class="axh-tabs" role="tablist">${list.map(([k, ic, l, n]) => `<button type="button" role="tab" data-axh-tab="${k}" aria-selected="${s.tab === k}">${icon(ic)}${esc(l)}${n ? ` <b>${n}</b>` : ""}</button>`).join("")}</nav>`;
  };
  const counts = (rows, key) => rows.reduce((a, r) => (a[r[key]] = (a[r[key]] || 0) + 1, a), {});
  const match = (v, ...t) => { const q = S_(v).q.trim().toLowerCase(); return !q || t.some(x => String(x || "").toLowerCase().includes(q)); };
  const ui = { tok, plural, go, sys, pill, sysPill, empty, card, kpi, meter, bars, state, chips, search, tabs, counts, match, st: S_ };

  // ---------- the frame ----------
  function register(v, spec) { reg[v] = spec; }
  async function get(url, fresh) {
    const c = cache[url];
    if (c && !fresh && Date.now() - c.at < 8000) return c.d;
    const d = await api(url + (fresh ? (url.includes("?") ? "&" : "?") + "fresh=1" : ""));
    cache[url] = { at: Date.now(), d };
    return d;
  }
  async function load(fresh) {
    const v = view, spec = reg[v], s = ++seq;
    if (!spec) return;
    try { const d = await spec.load(fresh, get); if (s !== seq || v !== view) return; S_(v).d = d; S_(v).err = ""; }
    catch (e) { if (s !== seq || v !== view) return; S_(v).err = e.message; }
    draw();
  }
  function draw(force) {
    const v = view, spec = reg[v], el = $("#axh-" + v), s = S_(v);
    if (!spec || !el) return;
    const k = JSON.stringify([s.d, s.err, s.tab, s.f, s.q, S.data?.block]);
    if (k === sig && !force) return stamp();
    sig = k; gos = [];
    const y = scrollY;
    const body = s.d ? spec.body(s.d, ui) : s.err ? `<div class="card empty">${esc(s.err)} <button type="button" class="linkbtn" data-hub="refresh">Try again</button></div>`
      : `<div class="stats">${Loading.tiles(6)}</div><div class="occ-grid">${Loading.cards(4, "card")}</div>`;
    const at = s.d?.at || (s.d && Date.now() / 1000);
    el.innerHTML = `<div class="occ axh axh-${v}"><div class="occ-head"><div><p class="occ-kicker">${icon(spec.icon)}AXoR 5.0 · ${esc(spec.kicker)}</p><h1 class="page">${esc(spec.title)}</h1>
        <p class="lead">${spec.lead}${at ? ` <span class="faint" data-axh-at>Updated ${ago(at)}</span>` : ""}</p></div>
        <div class="row">${spec.actions ? spec.actions(s.d, ui) : ""}<button type="button" class="btn sm" data-hub="refresh">${icon("cycle")}Refresh</button></div></div>${body}</div>`;
    if (Math.abs(scrollY - y) > 1) scrollTo(0, y);
  }
  function stamp() { const t = $(`#axh-${view} [data-axh-at]`), at = S_(view).d?.at; if (t && at) t.textContent = `Updated ${ago(at)}`; }
  function wire() {
    if (wired) return; wired = true;
    $("main").addEventListener("click", e => {
      const t = e.target; if (!t.closest(".axh-root")) return;
      const s = S_(view);
      const g = t.closest("[data-axh-go]"); if (g) return Command.follow(gos[+g.dataset.axhGo]);
      const to = t.closest("[data-axh-to]"); if (to) return setView(to.dataset.axhTo);
      const tb = t.closest("[data-axh-tab]"); if (tb) { s.tab = tb.dataset.axhTab; s.f = "all"; try { localStorage.setItem("hub.tab." + view, s.tab); } catch {} return draw(); }
      const f = t.closest("[data-axh-f]"); if (f) { s.f = f.dataset.axhF; return draw(); }
      const a = t.closest("[data-hub]")?.dataset.hub;
      if (a === "refresh") { sig = ""; return load(true); }
      if (a) return reg[view]?.act?.(a, t.closest("[data-hub]"), s);
    });
    $("main").addEventListener("input", e => {
      const i = e.target; if (!i.matches?.(".axh-root [data-axh-q]")) return;
      S_(view).q = i.value; const pos = i.selectionStart;
      draw(); const n = $(`#axh-${view} [data-axh-q]`); if (n) { n.focus(); n.setSelectionRange(pos, pos); }
    });
  }
  function onView(v) {
    clearInterval(timer); timer = null;
    if (!reg[v]) { view = ""; return; }
    wire();
    if (v !== view) sig = "";
    view = v;
    draw(true);
    load(true);
    timer = setInterval(() => { if (!document.hidden && view === v) load(false); }, reg[v].every || EVERY);
  }

  // Organization (#org) is its own page now: organization.js (the hierarchy, missions, authority); /api/hub/org stays for the API

  // ---------- Portfolio & Project HQ ----------
  const projStatus = p => p.state || p.status;
  register("projects", {
    title: "Portfolio & projects", kicker: "Operations", icon: "layers",
    lead: "Every project your agents run, on one scale: Company projects, Competition teams, Workforce missions, the project team and long tasks. Each opens on its own page.",
    load: (fresh, get) => get("/api/hub/projects", fresh),
    actions: () => `<button type="button" class="btn sm" data-axh-to="missions">${icon("list")}Task board</button>`,
    body(d, h) {
      const c = d.counts, s = h.st("projects");
      return `<div class="stats occ-kpis">${h.kpi("layers", "Projects", c.projects, `${c.active} active`)}${h.kpi("zap", "In progress", c.doing, "tasks being worked", "", "missions")}
          ${h.kpi("inbox", "Needs review", c.review, "waiting on you or a reviewer", c.review ? "warn" : "", "missions")}${h.kpi("alert", "Blocked or failed", c.blocked, "", c.blocked ? "crit" : "", "missions")}
          ${h.kpi("check", "Done", c.done, "recent tasks")}${h.kpi("route", "Dependencies", c.deps, "between projects")}</div>
        ${h.tabs("projects", [["all", "layers", "Portfolio", d.projects.length], ["deps", "route", "Dependencies", d.deps.length]])}
        ${s.tab === "deps" ? projDeps(d, h) : projList(d, h)}
        ${d.errors.length ? `<p class="faint small occ-errs">${icon("info")}${esc(d.errors.join(" · "))}</p>` : ""}`;
    },
  });
  function projList(d, h) {
    const s = h.st("projects"), rows = d.projects.filter(p => (s.f === "all" || p.system === s.f) && h.match("projects", p.name, p.goal, p.where));
    return `<div class="occ-ap-bar">${h.chips("projects", h.counts(d.projects, "system"), h.sys)}${h.search("projects", "Find a project…")}</div>
      ${rows.length ? `<div class="axh-cards axh-proj">${rows.map(p => {
        const pr = p.total ? p.done / p.total : null, spend = p.budget ? p.tokens / p.budget : null;
        return `<article class="axh-pcard"><div class="occ-ap-h">${h.sysPill(p.system)}${h.pill(h.state(projStatus(p)), projStatus(p))}${p.running ? h.pill("s-ok", `${p.running} running`) : ""}</div>
          <button type="button" class="axh-pname" ${h.go(p.go)}>${esc(p.name)}</button>${p.goal || p.line ? `<p>${esc(p.line || p.goal)}</p>` : ""}
          <dl class="axh-pstats"><div><dt>Tasks</dt><dd>${p.total ? `${h.meter(pr, `${p.done} of ${p.total} done`)}<span class="num">${p.done}/${p.total}</span>` : `<span class="faint">–</span>`}</dd></div>
            <div><dt>${p.system === "teams" ? "Tokens today" : "Tokens"}</dt><dd>${spend != null ? `${h.meter(spend, `${h.tok(p.tokens)} of ${h.tok(p.budget)}`, spend > 1 ? "over" : "")}<span class="num">${h.tok(p.tokens)}/${h.tok(p.budget)}</span>` : `<span class="num">${h.tok(p.tokens)}</span>`}</dd></div></dl>
          <small class="faint">${esc(p.where || "")}${p.updated ? ` · updated ${ago(p.updated)}` : ""}</small></article>`;
      }).join("")}</div>` : `<div class="card empty">${d.projects.length ? "No project matches." : "No projects yet. Start one in the Company, a Competition team, a Workforce mission or a long task."}</div>`}`;
  }
  function projDeps(d, h) {
    const end = x => `<button type="button" class="axh-dep-end" ${h.go(x.go)}>${icon(h.sys(x.system)[0])}<span>${esc(x.name)}</span></button>`;
    return d.deps.length ? `<ul class="axh-deps">${d.deps.map(x => `<li>${end(x.from)}<span class="axh-dep-k">${icon("right")}${esc(x.kind)}</span>${end(x.to)}</li>`).join("")}</ul>`
      : `<div class="card empty">No dependencies: your projects run on their own. Links appear when a Workforce mission researches for a team, a task force works inside one, a Company project reads My subnets, or a mission's steps wait on each other.</div>`;
  }

  // ---------- Missions & tasks ----------
  const LANE = { todo: ["To do", "info"], doing: ["In progress", "ok"], review: ["Needs review", "warn"], blocked: ["Blocked or failed", "crit"], done: ["Done", "off"] };
  const LANE_MAX = 30;
  register("missions", {
    title: "Task board", kicker: "Operations", icon: "list",
    lead: "Every task from the Company, Competition teams, Workforce missions, the project team and long tasks on one board. Click a task to open it where it runs.",
    load: (fresh, get) => get("/api/hub/projects", fresh),
    actions: () => `<button type="button" class="btn sm" data-axh-to="projects">${icon("layers")}Projects</button>`,
    body(d, h) {
      const s = h.st("missions"), rows = d.tasks.filter(t => (s.f === "all" || t.system === s.f) && h.match("missions", t.title, t.project, t.who));
      const c = d.counts;
      return `<div class="stats occ-kpis">${Object.entries(LANE).map(([k, [l, tone]]) => h.kpi(k === "done" ? "check" : k === "blocked" ? "alert" : k === "review" ? "inbox" : k === "doing" ? "zap" : "list", l, c[k], k === "done" ? "recent" : "", k === "blocked" && c[k] ? "crit" : k === "review" && c[k] ? "warn" : "")).join("")}</div>
        <div class="occ-ap-bar">${h.chips("missions", h.counts(d.tasks, "system"), h.sys)}${h.search("missions", "Find a task, project or agent…")}</div>
        ${d.tasks.length ? `<div class="axh-board" role="region" aria-label="Task board" tabindex="0">${d.lanes.map(k => {
          const lane = rows.filter(t => t.lane === k);
          return `<section class="axh-lane l-${LANE[k][1]}"><h4><span>${LANE[k][0]}</span><b>${lane.length}</b></h4><ul>${lane.slice(0, LANE_MAX).map(t => `<li><button type="button" class="axh-task" ${h.go(t.go)} title="${esc(t.detail || t.title)}">
              <b>${esc(t.title)}</b><small>${icon(h.sys(t.system)[0])}${esc(t.project || h.sys(t.system)[1])}</small>
              <span class="axh-task-f">${t.who ? `<span>${esc(t.who)}</span>` : ""}<span class="faint">${t.status}${t.updated ? ` · ${ago(t.updated)}` : ""}</span></span></button></li>`).join("")}</ul>
            ${lane.length > LANE_MAX ? `<p class="faint small">${lane.length - LANE_MAX} more: narrow it with a filter or search</p>` : lane.length ? "" : `<p class="faint small axh-lane-empty">Nothing here</p>`}</section>`;
        }).join("")}</div>` : `<div class="card empty">No tasks yet: agents' tasks appear here as soon as a project plans them.</div>`}
        ${d.dropped ? `<p class="faint small">${d.dropped} cancelled or skipped task${d.dropped === 1 ? "" : "s"} not shown.</p>` : ""}`;
    },
  });

  // ---------- Agent evaluation ----------
  register("evaluation", {
    title: "Agent evaluation", kicker: "Learning", icon: "trophy",
    lead: "How well your agents work: evaluator scores and success rates, benchmarks and experiments, which models and routes they use, long-running tasks, and the knowledge and skills they build. Last 30 days.",
    load: (fresh, get) => get("/api/hub/evaluation", fresh),
    body(d, h) {
      const sc = d.scores.filter(x => x.avg != null), avg = sc.length ? sc.reduce((a, x) => a + x.avg * x.n, 0) / sc.reduce((a, x) => a + x.n, 0) : null;
      const ok = d.scores.reduce((a, x) => a + (x.ok || 0), 0), bad = d.scores.reduce((a, x) => a + (x.fail || 0), 0);
      const tokens = d.models.reduce((a, m) => a + (m.tokens || 0), 0), K = d.knowledge, mem = K.memory?.by_kind || [];
      return `<div class="stats occ-kpis">${h.kpi("users", "Agents evaluated", d.scores.length, "with runs in 30 days")}${h.kpi("star", "Average score", avg != null ? `${fmtNum(avg, 1)}/10` : "–", sc.length ? "weighted by runs" : "no scored work yet")}
          ${h.kpi("check", "Success rate", ok + bad ? `${Math.round(ok / (ok + bad) * 100)}%` : "–", ok + bad ? `${ok} ok · ${bad} failed` : "no finished runs", bad > ok ? "crit" : "")}
          ${h.kpi("chart", "Tokens (30 d)", h.tok(tokens), `${h.plural(d.models.length, "model")}`)}${h.kpi("flag", "Benchmarks", d.benchmarks.length + d.experiments.length, "benchmarks and experiments")}
          ${h.kpi("route", "Long tasks", d.long.filter(t => t.status === "running").length, `running of ${d.long.length}`, "", "infiagent")}</div>
        <div class="occ-grid">
          ${h.card("axh-span12", "star", "Agent scores", "", d.scores.length ? `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Agent</th><th>System</th><th>Team or role</th><th class="r">Runs</th><th>Score</th><th>Success</th></tr></thead><tbody>
            ${d.scores.map(x => { const r = (x.ok || 0) + (x.fail || 0); return `<tr><td><button type="button" class="linkbtn" ${h.go(x.go)}>${esc(x.name)}</button></td><td>${h.sysPill(x.system)}</td><td class="faint">${esc(x.role)}</td><td class="r num">${x.n}</td>
              <td>${x.avg != null ? `${h.meter(x.avg / (x.scale || 10), `${x.avg} of ${x.scale || 10}`)} <span class="num">${x.avg}</span>` : `<span class="faint">–</span>`}</td>
              <td>${r ? `${h.meter(x.ok / r, `${x.ok} of ${r} ok`, x.fail > x.ok ? "over" : "")} <span class="num">${Math.round(x.ok / r * 100)}%</span>` : `<span class="faint">–</span>`}</td></tr>`; }).join("")}</tbody></table></div>`
            : h.empty("No scored or finished agent work in the last 30 days."))}
          ${h.card("", "chip", "Model use", `<span class="faint small">tokens, 30 days</span>`, h.bars(d.models.map(m => ({ label: m.model || "unknown", value: m.tokens || 0, title: `${m.model}: ${h.tok(m.tokens)} tokens in ${m.calls} calls` }))))}
          ${h.card("", "apps", "Where tokens go", `<span class="faint small">by feature, 30 days</span>`, h.bars(d.sources.map(m => ({ label: m.source || "other", value: m.tokens || 0, title: `${m.source}: ${h.tok(m.tokens)} tokens in ${m.calls} calls` }))))}
          ${d.routes.length ? h.card("axh-span12", "route", "Model routing (Workforce)", "", `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Route</th><th>Model</th><th class="r">Runs</th><th class="r">Avg score</th><th class="r">Failed</th><th class="r">Tokens</th></tr></thead><tbody>
            ${d.routes.map(r => `<tr><td>${esc(r.route || "default")}</td><td>${esc(r.model || "–")}</td><td class="r num">${r.runs}</td><td class="r num">${r.avg ?? "–"}</td><td class="r num">${r.failed || 0}</td><td class="r num">${h.tok(r.tokens)}</td></tr>`).join("")}</tbody></table></div>`) : ""}
          ${h.card("axh-span12", "flag", "Benchmarks & experiments", "", d.benchmarks.length || d.experiments.length ? `${d.benchmarks.length ? `<h4 class="occ-h4">Workforce benchmarks</h4><ul class="occ-list">${d.benchmarks.map(b => `<li><button type="button" class="occ-row" ${h.go(b.go)}><span class="occ-need-t"><b>${esc(b.title)}</b><small>${h.plural(b.arms, "arm")} · ${h.plural(b.trials || 0, "trial")} · ${esc(b.goal)}</small></span>${h.pill(h.state(b.status), b.status)}</button></li>`).join("")}</ul>` : ""}
            ${d.experiments.length ? `<h4 class="occ-h4">Lab experiments (Workflow)</h4><div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Experiment</th><th>Team</th><th>Solved</th><th>Passed</th><th class="r">Cost</th><th>Decision</th></tr></thead><tbody>
              ${d.experiments.map(e => `<tr><td><button type="button" class="linkbtn" ${h.go(e.go)}>${esc(e.label)}</button></td><td class="faint">${esc(e.where)}</td><td>${e.tasks ? `${h.meter(e.solved / e.tasks)} <span class="num">${e.solved}/${e.tasks}</span>` : "–"}</td>
                <td>${e.runs ? `<span class="num">${e.passed}/${e.runs}</span>` : "–"}</td><td class="r num">${e.cost != null ? "$" + fmtNum(e.cost, 2) : "–"}</td><td>${e.decision ? h.pill(h.state(e.decision), e.decision) : h.pill(h.state(e.status), e.status)}</td></tr>`).join("")}</tbody></table></div>` : ""}`
            : h.empty("No benchmark or experiment yet. Workforce benchmarks compare mission setups; the Workflow's Lab scores each commit."))}
          ${h.card("axh-span12", "route", "Long-running tasks", `<button type="button" class="linkbtn" data-axh-to="infiagent">Long tasks</button>`, d.long.length ? `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Task</th><th>Status</th><th class="r">Runs</th><th>Tokens</th><th>Updated</th><th>Note</th></tr></thead><tbody>
            ${d.long.map(t => `<tr><td><button type="button" class="linkbtn" ${h.go(t.go)}>${esc(t.title)}</button></td><td>${h.pill(h.state(t.status), t.status)}</td><td class="r num">${t.runs}</td>
              <td>${t.budget ? `${h.meter(t.tokens / t.budget, `${h.tok(t.tokens)} of ${h.tok(t.budget)}`, t.tokens > t.budget ? "over" : "")} ` : ""}<span class="num">${h.tok(t.tokens)}${t.budget ? `/${h.tok(t.budget)}` : ""}</span></td><td class="faint">${ago(t.updated)}</td><td class="faint">${esc(t.note)}</td></tr>`).join("")}</tbody></table></div>`
            : h.empty("No long task yet."))}
          ${h.card("", "book", "Knowledge", "", `${mem.length ? `<h4 class="occ-h4">Workforce memory</h4>${h.bars(mem.map(m => ({ label: m.kind, value: m.n, title: `${m.kind}: ${m.n} items, cited ${m.cited || 0}, helped ${m.helped || 0}` })), x => String(x))}` : ""}
            ${(K.memory?.top || []).length ? `<h4 class="occ-h4">Most useful lessons</h4><ul class="axh-notes">${K.memory.top.map(t => `<li><span>${esc(t.text)}</span><small class="faint">${esc(t.kind)} · helped ${t.helped || 0} · cited ${t.cited || 0}</small></li>`).join("")}</ul>` : ""}
            ${(K.portfolio || []).length ? `<h4 class="occ-h4">Portfolio findings</h4><div class="axh-chiprow">${K.portfolio.map(x => h.pill("src", `${x.scope.replace(/_/g, " ")}: ${x.n}`)).join("")}</div>` : ""}
            ${(K.company || []).length ? `<h4 class="occ-h4">Company knowledge</h4><div class="axh-chiprow">${K.company.map(x => h.pill("src", `${x.scope}: ${x.n}`)).join("")}</div>` : ""}
            ${!mem.length && !(K.portfolio || []).length && !(K.company || []).length ? h.empty("No knowledge saved yet: agents add lessons as they finish work.") : ""}`)}
          ${h.card("", "sparkle", "Skills", `<button type="button" class="linkbtn" data-axh-to="agents">Skill hub</button>`, `<div class="occ-org">
            <button type="button" class="occ-orgi" data-axh-to="agents">${icon("sparkle")}<span><small>Skills</small><b class="num">${d.skills.skills ?? 0}</b><em>in your skill hub</em></span></button>
            <button type="button" class="occ-orgi" data-axh-to="agents">${icon("bot")}<span><small>Your agents</small><b class="num">${d.skills.agents ?? 0}</b><em>made in the agent hub</em></span></button>
            ${d.skills.loadouts != null ? `<button type="button" class="occ-orgi" data-axh-to="teams">${icon("sliders")}<span><small>Loadouts</small><b class="num">${d.skills.loadouts}</b><em>Workflow agent loadouts</em></span></button>` : ""}</div>`)}
        </div>
        ${d.errors.length ? `<p class="faint small occ-errs">${icon("info")}${esc(d.errors.join(" · "))}</p>` : ""}`;
    },
  });

  // ---------- Workspace home ----------
  const PAGES = [["workspace", "pickaxe", "Subnets & notes", "Your shortlist, briefs, notes and agents"], ["drive", "folder", "Drive", "Files and shared folders"], ["whiteboard", "sticky", "Whiteboard", "Boards, edited live"],
                 ["slack", "hash", "Slack", "The team's channel"], ["source", "github", "Source hub", "Repositories and CI"], ["study", "book", "Study", "Learning tracks"], ["profile", "card", "My profile", "Resume, CV, website"]];
  register("home", {
    title: "Home", kicker: "My workspace", icon: "inbox",
    lead: "Your own work in one place: notes and daily notes, files, whiteboards, study and what you share with the team.",
    load: (fresh, get) => get("/api/hub/workspace", fresh),
    act(a, el) {
      if (a === "note") { const n = el.dataset.netuid; if (el.dataset.kind === "daily") Notes.openView("daily"); return Workspace.show(n ? +n : null, "notes"); }
      if (a === "board") { store.set("wb.open", +el.dataset.id); return setView("whiteboard"); }
      if (a === "daily") { Notes.openView("daily"); return Workspace.show(null, "notes"); }
      if (a === "overview") { setView("workspace"); return Workspace.show(null, "overview"); }
    },
    body(d, h) {
      const N = d.notes, vis = PAGES.filter(([v]) => { const b = $(`nav.side [data-view="${v}"]`); return b && !b.hidden; });
      const days = (d.study.days || []).slice().reverse(), pdca = Object.values(N.stages || {}).some(Boolean);
      // the agent side of your work lives in two dashboards of its own: My workspace → Overview and Agents (operations side)
      const agentLinks = d.agents ? `<button type="button" class="occ-orgi" data-hub="overview">${icon("grid")}<span><b class="axh-ll">What waits for you</b><em>My workspace → Overview: approvals, teams, miners</em></span></button>`
        + ($("#tab-studio") && !$("#tab-studio").hidden ? `<button type="button" class="occ-orgi" data-axh-to="studio">${icon("radio")}<span><b class="axh-ll">Agents</b><em>Every agent, its profile and versions, live runs</em></span></button>` : "") : "";
      return `<div class="stats occ-kpis">${h.kpi("note", "Notes", N.total ?? 0, `${N.week ?? 0} this week · ${N.pinned ?? 0} pinned`)}${h.kpi("calendar", "Daily notes", N.daily ?? 0, "one page per day")}
          ${h.kpi("file", "Files", d.files.n ?? 0, d.files.size ? fmtBytes(d.files.size) : "in your workspace", "", "workspace")}${h.kpi("sticky", "Whiteboards", d.boards.length, `${d.boards.filter(b => !b.mine).length} shared with you`, "", "whiteboard")}
          ${h.kpi("pickaxe", "Workspace subnets", d.subnets, "on your shortlist", "", "workspace")}${h.kpi("chart", "AI tokens (7 d)", h.tok(d.tokens_week), "your own use")}</div>
        <div class="occ-grid">
          ${h.card("axh-span12", "apps", "Open", "", `<div class="axh-launch">${vis.map(([v, ic, l, s]) => `<button type="button" class="occ-orgi" data-axh-to="${v}">${icon(ic)}<span><b class="axh-ll">${esc(l)}</b><em>${esc(s)}</em></span></button>`).join("")}${agentLinks}</div>`)}
          ${h.card("", "note", "Recent notes", `<button type="button" class="linkbtn" data-hub="daily">Today's note</button>`, N.recent?.length ? `<ul class="occ-list">${N.recent.map(n => `<li><button type="button" class="occ-row" data-hub="note" data-netuid="${n.netuid ?? ""}" data-kind="${esc(n.kind || "")}">${icon(n.kind === "daily" ? "calendar" : "note")}<span class="occ-need-t"><b>${esc(n.text || "Untitled")}</b><small>${n.netuid != null ? `SN${n.netuid} · ` : ""}${esc(n.kind || "note")} · ${ago(n.updated)}</small></span></button></li>`).join("")}</ul>`
            : h.empty("No notes yet. Write one from My workspace."))}
          ${h.card("", "sticky", "Whiteboards", `<button type="button" class="linkbtn" data-axh-to="whiteboard">All boards</button>`, d.boards.length ? `<ul class="occ-list">${d.boards.map(b => `<li><button type="button" class="occ-row" data-hub="board" data-id="${b.id}">${icon(b.mine ? "sticky" : "users")}<span class="occ-need-t"><b>${esc(b.name || "Untitled board")}</b><small>${b.mine ? (b.shared ? `shared with ${h.plural(b.shared, "person")}` : "only you") : "shared with you"}${b.updated ? ` · ${ago(b.updated)}${b.by ? ` by ${esc(b.by)}` : ""}` : ""}</small></span></button></li>`).join("")}</ul>`
            : h.empty("No whiteboards yet."))}
          ${h.card("", "book", "Study", `<button type="button" class="linkbtn" data-axh-to="study">Open Study</button>`, (d.study.tracks || []).length ? `<ul class="occ-by">${d.study.tracks.map(t => `<li><span>${esc(t.track)}</span>${h.meter((t.done || 0) / (t.n || 1), `${t.done || 0} of ${t.n} topics`)}<b class="num">${t.done || 0}/${t.n}</b></li>`).join("")}</ul>
            ${days.length ? `<h4 class="occ-h4">Last ${days.length} study days</h4>${h.bars(days.map(x => ({ label: x.day, value: x.n || 0 })), x => String(x))}` : ""}` : h.empty("No study progress yet."))}
          ${pdca ? h.card("", "cycle", "Plan · Do · Check · Act", `<button type="button" class="linkbtn" data-hub="daily">Notes</button>`, `<div class="occ-org">${[["plan", "Plan"], ["do", "Do"], ["check", "Check"], ["act", "Act"]].map(([k, l]) => `<div class="occ-orgi">${icon("cycle")}<span><small>${l}</small><b class="num">${N.stages?.[k] ?? 0}</b><em>notes</em></span></div>`).join("")}</div>`) : ""}
        </div>`;
    },
  });
  const fmtBytes = n => n >= 1e9 ? `${fmtNum(n / 1e9, 1)} GB` : n >= 1e6 ? `${fmtNum(n / 1e6, 1)} MB` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)} kB` : `${n} B`;

  // ---------- Settings ----------
  register("settings", {
    title: "Settings", kicker: "Administration", icon: "gear",
    lead: "Your account's security, notifications and appearance; for administrators, users, sign-up and the system's audit trail. Changes are made where each setting lives.",
    load: async (fresh, get) => {
      const admin = Auth.me()?.role === "admin";
      const [me, ov, au] = await Promise.all([get("/api/hub/settings", fresh), admin ? get("/api/admin/overview", fresh).catch(() => null) : null, admin ? get("/api/admin/audit?limit=10", fresh).catch(() => null) : null]);
      return { ...me, adm: ov, aud: au };
    },
    act(a) {
      if (a === "security") return setTimeout(() => $("#account").click(), 0);
      if (a === "alerts") return Notify.settings ? Notify.settings() : setView("notifications");
      if (a === "theme") return setTimeout(() => $("#theme").click(), 0);
      if (a === "audit") return Platform.audit();
    },
    body(d, h) {
      const m = d.me, A = d.adm, au = Array.isArray(d.aud) ? d.aud : d.aud?.items || d.aud?.rows || [];
      const row = (label, val, tone) => `<li><span>${esc(label)}</span>${tone ? h.pill(tone, val) : `<b>${esc(val)}</b>`}</li>`;
      return `<div class="occ-grid">
          ${h.card("", "shield", "Account &amp; security", `<button type="button" class="btn sm" data-hub="security">${icon("key")}Manage</button>`, `<ul class="axh-kv">
            ${row("Signed in as", `${m.username} (${m.role === "admin" ? "administrator" : "member"})`)}${row("Two-factor authentication", m.totp ? "On" : "Off", m.totp ? "s-ok" : "s-crit")}
            ${m.totp ? row("Recovery codes left", String(m.recovery_left ?? "–"), (m.recovery_left ?? 0) < 3 ? "s-warn" : "s-ok") : ""}${row("Email", m.email ? "Set" : "Not set", m.email ? "s-ok" : "s-off")}
            ${row("Member since", m.created ? new Date(m.created * 1000).toLocaleDateString() : "–")}${row("Last sign-in", m.last_login ? `${ago(m.last_login)}${m.last_ip ? ` from ${m.last_ip}` : ""}` : "–")}</ul>
            ${!m.totp ? `<p class="small axh-warn">${icon("alert")}Turn on two-factor from <b>Manage</b>: a password alone is the only thing protecting your agents and wallets.</p>` : ""}`)}
          ${h.card("", "devices", "Signed-in sessions", `<span class="faint small">${h.plural(d.sessions.length, "session")}</span>`, d.sessions.length ? `<ul class="occ-list">${d.sessions.map(s => `<li class="occ-need"><span class="occ-need-t"><b>${esc(s.ua || "Unknown device")}</b><small>${esc(s.ip || "")} · last seen ${ago(s.last_seen)}${s.stage !== "full" ? ` · ${esc(s.stage)}` : ""}</small></span></li>`).join("")}</ul>
            <p class="faint small">Sign out everywhere from <button type="button" class="linkbtn" data-hub="security">the account menu</button>.</p>` : h.empty("No other sessions."))}
          ${h.card("", "bell", "Notifications", `<button type="button" class="btn sm" data-hub="alerts">${icon("sliders")}Settings</button>`, `<ul class="axh-kv">${row("Alert kinds on", d.alerts.total ? `${d.alerts.on} of ${d.alerts.total}` : "Defaults")}${row("Push to your devices", d.push ? "Set up" : "Not set up", d.push ? "s-ok" : "s-off")}</ul>
            <button type="button" class="linkbtn" data-axh-to="notifications">Activity &amp; alerts</button>`)}
          ${h.card("", "palette", "Appearance", `<button type="button" class="btn sm" data-hub="theme">${icon("palette")}Theme &amp; color</button>`, `<p class="faint small">Light or dark mode, the accent color and the Neural Renaissance background (off, subtle or vivid) are set per device from the theme panel.</p>`)}
          ${h.card("axh-span12", "clock", "Your recent account activity", "", d.recent.length ? `<ul class="occ-feed">${d.recent.map(r => `<li><span class="num faint">${ago(r.ts)}</span><span class="occ-feed-t">${icon("key")}<span>${esc(r.action.replace(/[._]/g, " "))}${r.ip ? ` · ${esc(r.ip)}` : ""}</span></span></li>`).join("")}</ul>` : h.empty("No activity recorded yet."))}
          ${A ? `${h.card("axh-span12", "users", "Users &amp; access", `<button type="button" class="btn sm" data-axh-to="admin">${icon("users")}Users &amp; permissions</button>`, `<div class="stats occ-kpis axh-inkpis">
              ${h.kpi("users", "Users", A.stats.users, `${A.stats.admins} admin${A.stats.admins === 1 ? "" : "s"}`)}${h.kpi("inbox", "Waiting for approval", A.stats.pending, A.approval_required ? "approval is required" : "approval is off", A.stats.pending ? "warn" : "", "admin")}
              ${h.kpi("shield", "Two-factor", A.stats.users ? `${Math.round(A.stats.with_2fa / A.stats.users * 100)}%` : "–", `${A.stats.with_2fa} of ${A.stats.users} accounts`, A.stats.with_2fa < A.stats.users ? "warn" : "ok")}
              ${h.kpi("lock", "Disabled or locked", A.stats.disabled + A.stats.locked, `${A.stats.locked} locked now`, A.stats.locked ? "warn" : "")}${h.kpi("devices", "Sessions", A.stats.sessions, `${A.stats.logins_24h ?? 0} sign-ins in 24 h`)}</div>
              <div class="axh-chiprow">${h.pill(A.registration_open ? "s-warn" : "s-ok", A.registration_open ? "Sign-up open" : "Sign-up closed")}${h.pill(A.approval_required ? "s-ok" : "s-warn", A.approval_required ? "New accounts need approval" : "No approval for new accounts")}${h.pill("src", `Sign-in: ${A.auth_method}`)}</div>`)}
            ${h.card("axh-span12", "clock", "System audit log", `<button type="button" class="btn sm" data-hub="audit">${icon("clock")}Full audit log</button>`, au.length ? `<ul class="occ-feed">${au.slice(0, 10).map(r => `<li><span class="num faint">${ago(r.ts)}</span><span class="occ-feed-t">${icon("shield")}<span><b>${esc((r.action || "").replace(/[._]/g, " "))}</b> by ${esc(r.actor || "–")}${r.target && r.target !== r.actor ? ` on ${esc(r.target)}` : ""}${r.ip ? ` · ${esc(r.ip)}` : ""}</span></span></li>`).join("")}</ul>` : h.empty("No events yet."))}
            ${h.card("axh-span12", "server", "System", "", `<div class="axh-launch">${[["infra", "server", "Platform overview", "Services, cluster, pipelines"], ["connectors", "key", "Connectors", "Keys AXoR holds"], ["system", "chip", "System", "CPU, memory, disk"], ["cluster", "layers", "Cluster", "Kubernetes and Updates"]]
              .filter(([v]) => { const b = $(`nav.side [data-view="${v}"]`); return b && !b.hidden; }).map(([v, ic, l, s]) => `<button type="button" class="occ-orgi" data-axh-to="${v}">${icon(ic)}<span><b class="axh-ll">${esc(l)}</b><em>${esc(s)}</em></span></button>`).join("")}</div>`)}` : ""}
        </div>`;
    },
  });

  function onData() { if (reg[view]?.chain) draw(); }  // a new chain snapshot: pages drawn from S.data redraw
  return { register, onView, onData, ui, reload: fresh => { sig = ""; return load(!!fresh); } };  // reload: a page's own second fetch changed (hub-layers.js trace); fresh after a change it made
})();
