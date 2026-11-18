/* AXoR 2.0 Command Center and Approval Center (command.py, command.css; prefix occ-).
   - Command Center: the global operational overview: what needs you (critical alerts, requests waiting for approval), system
     health (the chain, AXoR's services, the server for administrators), active missions, the agent workforce, performance and
     resource use, and the latest activity. One call (/api/command) plus /api/platform-status and the live chain data.
   - Approval Center: every request waiting for your decision across My subnets, the Company, Workforce, Agent HQ,
     the Portfolio, Competition teams, the Workflow and the project team, with filters, and the latest decisions. Nothing is
     decided here: each request opens on its own page, where its evidence is, and that system records the decision.
   The sidebar counts (urgent on the Command Center, waiting on the Approval Center) refresh every minute; the pages every 20 s
   while they show, redrawing only when something changed. */
const Command = (() => {
  const SRC = { mining: ["trophy", "My subnets"], company: ["layers", "Company"], workforce: ["group", "Workforce"], hq: ["flag", "Agent HQ"],
                portfolio: ["target", "Portfolio"], teams: ["users", "Competition teams"], workflow: ["route", "Workflow"], projects: ["cycle", "Project team"],
                knowledge: ["book", "Knowledge Hub"], missions: ["target", "Mission Control"], market: ["apps", "Agent Marketplace"], org: ["branch", "Organization"] };
  const LEVEL = { stop: ["crit", "Urgent"], warn: ["warn", "Needs you"], info: ["info", "To review"] };
  const STATE = { working: ["ok", "Working"], stuck: ["crit", "Stuck"], waiting: ["warn", "Waiting for you"], idle: ["off", "Idle"] };
  const DONE = { done: "ok", approved: "ok", consumed: "ok", applied: "ok", promoted: "ok", rejected: "crit", declined: "crit", failed: "crit", expired: "off", cancelled: "off", dropped: "off" };
  const USAGE = { chat: "Agent chats", workspace: "Workspace", study: "Study tutors", practice: "Practice drills", lab: "Study lab", team: "Project team",
                  board: "Whiteboard AI", profile: "Profile AI review", mining: "My subnets", writing: "Writing help", hq: "Agent HQ", tech: "Technology Research" };  // chatkit.js's names, as overview.js
  const SVC = { ok: "Up", warn: "Needs a look", down: "Down", pending: "Starting", off: "Not set up" };
  const EVERY = 20000, BADGE_EVERY = 60000;
  let d = null, st = null, so = null, view = "", sig = "", failed = "", seq = 0, timer = null, badgeTimer = null, clockTimer = null, wired = false, gos = [];
  let filt = (() => { try { return localStorage.getItem("occ.filter") || "all"; } catch { return "all"; } })(), q = "";
  let aptab = (() => { try { return localStorage.getItem("occ.aptab") || "queue"; } catch { return "queue"; } })(), gv = null, gvErr = "";  // the Approval Center's governance tabs (/api/hub/governance)
  const go = x => x ? `data-occ-go="${gos.push(x) - 1}"` : "";
  const src = k => SRC[k] || ["info", k];
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : String(n);
  const host = () => view === "approvals" ? $("#occ-ap") : $("#occ");
  const pill = (cls, text, ic) => `<span class="occ-pill ${cls}">${ic ? icon(ic) : `<i></i>`}${esc(text)}</span>`;
  const card = (cls, ic, title, extra, body) => `<section class="card occ-card ${cls}"><div class="occ-ch"><h3>${icon(ic)}${title}</h3>${extra || ""}</div>${body}</section>`;
  const empty = text => `<p class="occ-empty">${text}</p>`;

  // ---------- data ----------
  async function load(fresh) {
    const s = ++seq;
    try {
      const [r, p, a] = await Promise.all([api("/api/command" + (fresh ? "?fresh=1" : "")), view === "command" ? Platform.status(fresh) : null,
                                           view === "command" && !$("#tab-studio").hidden ? api("/api/studio").catch(() => null) : null]);  // agents across every system
      if (s !== seq) return;
      d = r; if (p) st = p; if (a) so = a; failed = "";
      badge();
    } catch (e) { if (s !== seq) return; failed = e.message; }
    if (view === "approvals" && aptab !== "queue") await governance(fresh);
    if (s === seq) draw();
  }
  async function governance(fresh) {
    try { gv = await api("/api/hub/governance" + (fresh ? "?fresh=1" : "")); gvErr = ""; } catch (e) { gvErr = e.message; }
  }
  function draw() {
    const el = host(); if (!el) return;
    const k = JSON.stringify([view, failed, filt, q, aptab, gv, gvErr, d && { ...d, at: 0, overview: { ...d.overview, at: 0 } }, st?.services, S.data?.block, cctab, chart,
                              so && { ...so, at: 0 }, Notify.feed().items?.length, typeof Assist !== "undefined" && Assist.ready()]);
    if (view === "command" && k !== sig) { const f = host()?.querySelector("[data-axc-form] input"); if (f && document.activeElement === f && f.value) return stamp(); }  // don't wipe a question being typed
    if (k === sig) return stamp();
    sig = k; gos = [];
    const y = scrollY;
    el.innerHTML = !d ? (failed ? `<div class="card empty">${esc(failed)} <button type="button" class="linkbtn" data-occ="refresh">Try again</button></div>` : skeleton())
      : view === "approvals" ? approvals() : command();
    if (Math.abs(scrollY - y) > 1) scrollTo(0, y);
  }
  function stamp() { const t = host()?.querySelector("[data-occ-at]"); if (t && d) t.textContent = `Updated ${ago(d.at)}`; const c = host()?.querySelector("[data-axc-clock]"); if (c) c.textContent = clockText(); }
  const skeleton = () => `<div class="stats">${Loading.tiles(6)}</div><div class="occ-grid">${Loading.cards(4, "card")}</div>`;

  // ---------- Command Center (the AgentForge-style layout: KPIs, three rows of cards, the assistant beside them, tabs below) ----------
  const DAY_LABEL = i => new Date(Date.now() - (6 - i) * 86400000).toLocaleDateString(undefined, { weekday: "short" });
  const QUICK = [  // [icon, label, nav button that must be usable, where]
    ["bot", "Create agent", "#tab-agents", () => { Agents.wantNew(); setView("agents"); }],
    ["folder", "New project", "#nav-company", () => follow({ view: "company", tab: "projects" })],
    ["trophy", "Import competition", "#nav-teams", () => follow({ view: "teams", intake: true })],
    ["chart", "View reports", "#nav-evaluation", () => setView("evaluation")],
    ["pickaxe", "Open workspace", "#nav-ws", () => setView("workspace")],
    ["grid", "Explore subnets", null, () => setView("explore")],
    ["bell", "Notifications", "#nav-alerts", () => setView("notifications")],
    ["gear", "Settings", "#nav-settings", () => setView("settings")],
  ];
  const ASKS = ["Summarize today's activity", "What needs my approval?", "How are my competitions doing?", "How can I improve my miners' performance?"];
  let cctab = (() => { try { return localStorage.getItem("occ.cctab") || "missions"; } catch { return "missions"; } })();
  let chart = (() => { try { return localStorage.getItem("occ.chart") || "tasks"; } catch { return "tasks"; } })();
  let quick = [];
  const usable = sel => { if (!sel) return true; const b = $(sel); return !!b && !b.hidden && !b.closest(".side-sec")?.hidden; };

  function command() {
    const o = d.overview, c = o.counts, so = studio(), h = healthOf();
    const runningAll = c.working + (d.org.workforce?.running || 0) + (d.org.company?.running || 0) + (d.org.longtasks?.running || 0);
    const live = so ? Math.max(so.counts.running, runningAll) : runningAll;
    // done per day across every system (overview.py: teams + Company + Workforce + Mission Control); the teams' own sum before it had one
    const week = o.week || Array.from({ length: 7 }, (_, i) => o.teams.reduce((a, t) => a + (t.week?.[i] || 0), 0));
    const comps = new Set([...o.teams.map(t => t.netuid), ...o.miners.map(m => m.netuid)].filter(x => x != null));
    const P = d.pending, crit = o.needs.filter(n => n.level === "stop" && !P.some(p => p.title === n.title));  // critical alerts aren't requests: they come from the Overview
    const urgent = d.counts.urgent + crit.length;
    return `<div class="occ axc">
      <div class="axc-head"><div><h1 class="page">AXoR Command Center</h1>
          <p class="lead">Your AI agent operations at a glance. <span class="faint" data-occ-at>Updated ${ago(d.at)}</span></p></div>
        <div class="axc-status">${crit.length ? `<button type="button" class="axc-online s-down" data-occ-view="approvals" title="${esc(crit.map(n => n.title).join("\n"))}"><span class="plt-dot"></span>${plural(crit.length, "critical alert")}</button>`
            : `<span class="axc-online s-${h.level}" title="${esc(h.tip)}"><span class="plt-dot"></span>${esc(h.text)}</span>`}
          <button type="button" class="iconbtn" data-occ="refresh" title="Refresh" aria-label="Refresh">${icon("cycle")}</button>
          <time class="axc-clock" data-axc-clock>${clockText()}</time></div></div>

      <div class="axc-layout">
        <div class="axc-kpis">
          ${tile("bot", "Agents", so ? so.counts.agents : (d.org.company?.agents || 0) + (d.org.workforce?.agents || 0),
              so ? `${so.counts.working} working${so.counts.attention ? ` · ${so.counts.attention} need a look` : ""}` : d.agents ? "in Company and Workforce" : "agents aren't on for you",
              so ? mix(Object.values(so.systems).map(s => [s.label, s.agents])) : "", "ok", so ? "studio" : null)}
          ${tile("play", "Active", live, live ? "runs live now" : "nothing running right now",
              week.some(Boolean) ? `<div class="axc-spark" title="Tasks done per day, last 7 days">${spark(week, 120, 30)}</div>` : "", "info", usable("#nav-missions") ? "missions" : null)}
          ${tile("trophy", "Competitions", comps.size, `${plural(o.teams.length, "team")} · ${plural(o.miners.length, "miner")} tracked`,
              o.teams.length ? progress(o.teams.reduce((a, t) => a + t.done, 0), o.teams.reduce((a, t) => a + t.total, 0), "tasks done") : "", "gold", usable("#nav-teams") ? "teams" : null)}
          ${tile("inbox", "Approvals", P.length, crit.length ? `${plural(crit.length, "critical alert")} too` : P.length ? (urgent ? `${urgent} urgent` : "Action needed") : "all clear",
              P.length ? mix(Object.entries(d.counts.by_source).map(([k, n]) => [src(k)[1], n])) : "", P.length ? "warn" : "ok", "approvals")}
        </div>
        ${activityChart(week, o)}
        ${network(o)}
        ${healthCard(h)}
        ${approvalsCard(P, crit)}
        ${recent(o)}
        ${actions()}
        ${assistant(so, h, live, comps.size, crit.length)}
        ${tabs(o, so)}
        ${promo()}
      </div>
      ${(o.errors.length || d.errors.length) ? `<p class="faint small occ-errs">${icon("info")}Some sources couldn't be read: ${esc([...o.errors, ...d.errors].join(" · "))}</p>` : ""}
    </div>`;
  }
  const clockText = () => { const n = new Date(); return `${n.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" })} · ${n.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" })}`; };
  const studio = () => so || Shell.studio();
  function healthOf() {
    const svc = (st?.services || []).filter(s => s.state !== "off" && s.key !== "chain"), ch = S.data, err = ch?.status?.startsWith?.("error");
    const bad = svc.filter(s => s.state === "down" || s.state === "warn"), chain = err ? "down" : ch?.block ? "ok" : "pending";
    const w = st?.work, now = w?.failing_now || 0;  // availability apart from the work: runs failing now make it a warning
    const level = chain === "down" || bad.some(s => s.state === "down") ? "down" : bad.length || chain === "pending" || now ? "warn" : "ok";
    const text = chain === "down" ? "Chain unreachable" : bad.length ? `${plural(bad.length, "service")} need${bad.length === 1 ? "s" : ""} a look` : chain === "pending" ? "Connecting" : now ? `Platform up · ${plural(now, "run")} failing now` : "Platform online";
    const tip = [`Chain: ${err ? "can't be reached" : ch?.block ? `live, block ${ch.block.toLocaleString()}` : "connecting"}`, ...svc.map(s => `${s.label}: ${s.detail}`)].join("\n");
    return { level, text, tip, chain, svc, bad };
  }
  function tile(ic, label, value, sub, visual, tone, to) {
    const tag = to ? `button type="button" data-occ-view="${to}"` : "div";
    return `<${tag} class="card axc-kpi t-${tone}"><span class="axc-kpi-ic">${icon(ic)}</span><span class="axc-kpi-m"><small>${label}</small><b class="num">${esc(Number(value).toLocaleString())}</b><em>${esc(sub)}</em></span>
      <span class="axc-kpi-v">${visual}</span></${to ? "button" : "div"}>`;
  }
  // a share bar: what a total is made of (agents by system, approvals by system)
  function mix(parts) {
    parts = parts.filter(([, n]) => n > 0); const t = parts.reduce((a, [, n]) => a + n, 0); if (!t) return "";
    return `<span class="axc-mix" title="${esc(parts.map(([l, n]) => `${l}: ${n}`).join("\n"))}">${parts.map(([l, n], i) => `<i class="m${i % 6}" style="flex:${n}"></i>`).join("")}</span>`;
  }
  const progress = (n, t, what) => t ? `<span class="axc-prog" title="${n} of ${t} ${what}"><i style="width:${Math.round(n / t * 100)}%"></i></span><small class="faint">${Math.round(n / t * 100)}% ${what}</small>` : "";

  function activityChart(week, o) {
    const days = (o.spend?.days || []).slice(-7), toks = days.map(x => x.tokens || 0);
    const series = chart === "tokens" ? toks : week, has = series.some(Boolean);
    const total = series.reduce((a, b) => a + b, 0);
    const head = chart === "tokens" ? `${tok(total)} tokens · 7 days` : `${plural(total, "task")} done · 7 days`;
    return `<section class="card occ-card axc-act"><div class="occ-ch"><h3>${icon("zap")}Agent activity ${d.agents ? `<span class="axc-live"><i></i>Live</span>` : ""}</h3>
        <div class="seg sm" role="group" aria-label="Chart"><button type="button" data-axc-chart="tasks" aria-pressed="${chart === "tasks"}">Tasks</button><button type="button" data-axc-chart="tokens" aria-pressed="${chart === "tokens"}">Tokens</button></div></div>
      <p class="faint small axc-sub">${head}${chart === "tasks" && o.counts.ok_day + o.counts.failed_day ? ` · runs today ${o.counts.ok_day} ok, ${o.counts.failed_day} failed` : ""}</p>
      ${has ? area(series, chart === "tokens" ? tok : String) : empty(d.agents ? (chart === "tokens" ? "No model use in the last 7 days." : "No task finished in the last 7 days.") : "Agent activity shows here once agents are on for you.")}</section>`;
  }
  // a 7-day area chart with its own y axis (one series at a time: tasks and tokens don't share a scale)
  function area(v, fmt) {  // the line and area stretch with the card (SVG); labels and points are HTML, so text keeps its size
    // the y axis has quarter lines: a small top is rounded up to a multiple of 4 so they read 0 1 2 3 4, not 0 0 1 1 1
    const t0 = nice(Math.max(...v) || 1), top = t0 < 20 && t0 % 4 ? Math.ceil(t0 / 4) * 4 : t0, x = i => i / (v.length - 1) * 100, y = n => 100 - n / top * 100;
    const line = v.map((n, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(n).toFixed(2)}`).join("");
    return `<div class="axc-chart" role="img" aria-label="Per day, last 7 days: ${v.map((n, i) => `${DAY_LABEL(i)} ${fmt(n)}`).join(", ")}">
      <div class="axc-y">${[1, .75, .5, .25, 0].map(f => `<span>${esc(fmt(Math.round(top * f)))}</span>`).join("")}</div>
      <div class="axc-plot"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${[0, 25, 50, 75, 100].map(g => `<line x1="0" x2="100" y1="${g}" y2="${g}"/>`).join("")}
          <path class="a" d="${line}L100,100L0,100Z"/><path class="l" d="${line}"/></svg>
        ${v.map((n, i) => `<i style="left:${x(i)}%;top:${y(n)}%" title="${DAY_LABEL(i)}: ${esc(fmt(n))}"></i>`).join("")}</div>
      <div class="axc-x">${v.map((_, i) => `<span>${DAY_LABEL(i)}</span>`).join("")}</div></div>`;
  }
  const nice = m => { const p = 10 ** Math.floor(Math.log10(m)), f = m / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; };

  function network(o) {
    const m = o.miners[0], subs = S.data?.subnets || [], sn = m ? subs.find(r => r.netuid === m.netuid) : null;
    const go = usable("#nav-mining") ? `<button type="button" class="linkbtn" data-occ-to="mining">View details</button>` : `<button type="button" class="linkbtn" data-occ-to="explore">Explorer</button>`;
    if (!m) {
      const ch = S.data;
      return card("axc-net", "chart", "Bittensor network", `<button type="button" class="linkbtn" data-occ-to="explore">Explorer</button>`, ch?.block ? `<div class="axc-net-h"><div><b class="axc-big">${subs.length}</b><small>subnets live</small></div>
          <div class="r"><b class="axc-big">${ch.tao_usd ? usd(ch.tao_usd) : "–"}</b><small>TAO price</small></div></div>
        <div class="axc-net-s"><div><b class="num">#${ch.block.toLocaleString()}</b><small>latest block</small></div><div><b class="num">${subs.filter(r => r.registration_allowed).length}</b><small>open to register</small></div><div><b class="num">${ago(ch.updated) || "–"}</b><small>updated</small></div></div>
        <p class="faint small">Track a miner in My subnets to see its rank and rewards here.</p>` : empty(ch?.status?.startsWith?.("error") ? "The chain can't be reached right now." : "Connecting to the chain…"));
    }
    return card("axc-net", "chart", "Bittensor network", go, `<div class="axc-net-h"><div><b class="axc-big">SN${m.netuid}</b><small>${esc(m.name || sn?.name || "")}</small></div>
        <div class="r"><b class="axc-big">${m.rank != null ? `#${m.rank}` : "–"}</b><small>${m.rank != null ? `your rank${m.of ? ` of ${m.of}` : ""}` : "not ranked yet"}</small></div></div>
      <div class="axc-net-s"><div><b class="num">${sn?.miner_pool_day != null ? money(sn.miner_pool_day) : "–"}</b><small>to miners / day</small></div>
        <div><b class="num">${sn?.earning_miners ?? "–"}</b><small>earning miners</small></div>
        <div><b class="num">${sn?.median_miner_live != null ? money(sn.median_miner_live) : "–"}</b><small>median miner / day</small></div></div>
      <p class="faint small">${m.em != null ? `Your miner: ${fmtNum(m.em, 3)} τ/day${m.gap != null ? ` · ${fmtNum(m.gap, 3)} τ behind the top` : ""}` : esc(m.headline || "My subnets adds your miner's numbers after its first brief.")}${o.miners.length > 1 ? ` · ${o.miners.length - 1} more tracked` : ""}</p>`);
  }

  function healthCard(h) {
    const groups = [["Chain", ["chain"]], ["Agents", ["agents"]], ["Workspace", ["drive", "slack", "source", "push"]], ["Infrastructure", ["docker", "runner", "kubernetes", "dns"]]].map(([label, keys]) => {
      const all = (st?.services || []).filter(s => keys.includes(s.key)), on = all.filter(s => s.state !== "off");
      const state = label === "Chain" ? h.chain : !on.length ? "off" : on.some(s => s.state === "down") ? "down" : on.some(s => s.state === "warn") ? "warn" : on.some(s => s.state === "pending") ? "pending" : "ok";
      const detail = label === "Chain" ? (h.chain === "down" ? "unreachable" : h.chain === "ok" ? "live" : "connecting") : !on.length ? "not set up" : `${on.filter(s => s.state === "ok").length}/${on.length} up`;
      return `<li class="s-${state}" title="${esc(all.map(s => `${s.label}: ${s.detail}`).join("\n"))}"><span class="plt-dot"></span><b>${label}</b><small>${detail}</small></li>`;
    }).join("");
    const set = [...h.svc, ...(h.chain !== "pending" ? [{ state: h.chain }] : [])], up = set.filter(s => s.state === "ok").length, n = set.length;
    const pctUp = n ? up / n : 0, R = 34, C = 2 * Math.PI * R;
    const off = (st?.services || []).filter(s => s.state === "off").length;
    return card("axc-health", "heart", "System health", usable("#nav-infra") ? `<button type="button" class="linkbtn" data-occ-to="infra">View details</button>` : "",
      st ? `<div class="axc-health-b"><svg class="axc-ring s-${h.level}" viewBox="0 0 84 84" role="img" aria-label="${up} of ${n} up"><circle class="bg" cx="42" cy="42" r="${R}"/><circle class="fg" cx="42" cy="42" r="${R}" stroke-dasharray="${(C * pctUp).toFixed(1)} ${C.toFixed(1)}"/>
          <text x="42" y="40" text-anchor="middle">${up}/${n}</text><text class="s" x="42" y="54" text-anchor="middle">up</text></svg>
        <ul class="axc-groups">${groups}</ul></div>
        <p class="faint small">${off ? `${plural(off, "service")} not set up (not counted)` : "Every service is set up"}${h.bad.length ? ` · ${h.bad.map(s => esc(s.label)).join(", ")} need${h.bad.length === 1 ? "s" : ""} a look` : ""}</p>`
        : Loading.line("Checking services…"));
  }

  function approvalsCard(P, crit) {
    const top = [...crit.map(n => ({ ...n, level: "stop", alert: true })), ...P].slice(0, Math.max(3, Math.min(crit.length, 4)));
    return card("axc-ap", "shield", "Pending approvals", `<button type="button" class="linkbtn" data-occ-view="approvals">View all${P.length > 3 ? ` (${P.length})` : ""}</button>`,
      !d.agents && !top.length ? empty("Agents aren't turned on for your account, so nothing waits for you here.")
      : top.length ? `<ul class="axc-list">${top.map(x => { const [ic, name] = src(x.source), [lv, lvName] = LEVEL[x.level] || LEVEL.warn;
          return `<li class="l-${lv}"><span class="axc-ic">${icon(ic)}</span><span class="axc-li-t"><b>${esc(x.title)}</b><small>${esc(name)}${x.where && x.where !== name ? ` · ${esc(x.where)}` : ""}${x.ts ? ` · ${ago(x.ts)}` : ""}${x.risk ? ` · risk: ${esc(x.risk)}` : ""}</small></span>
            ${x.alert ? `<button type="button" class="btn sm primary" ${go(x.go)}>${esc(x.label || "Open")}</button>`
              : `<button type="button" class="btn sm ${x.level === "stop" ? "primary" : "axc-review"}" ${go(x.go)} title="${esc(x.label)}: decided on its own page, with its evidence">Review</button>`}</li>`; }).join("")}</ul>
          <p class="faint small axc-note">${icon("lock")}Each request is approved or rejected on its own page, where its evidence is.</p>`
      : empty(`${icon("check")}Nothing waits for you. Agents keep working inside their approved limits.`));
  }

  function recent(o) {
    const acts = o.activity.slice(0, 5).map(a => ({ ts: a.ts, ic: src(a.source)[0], text: a.text, where: a.where, go: a.go, tone: /fail|error|stuck/i.test(a.kind || a.text) ? "crit" : /done|merged|approved|passed/i.test(a.kind || a.text) ? "ok" : "info" }));
    const nt = acts.length < 5 ? (Notify.feed().items || []).slice(0, 5 - acts.length).map(n => ({ ts: n.ts, ic: "bell", text: n.title, where: n.netuid != null ? `SN${n.netuid}` : "", nt: n.id, tone: "warn" })) : [];
    const all = [...acts, ...nt].sort((a, b) => (b.ts || 0) - (a.ts || 0));
    return card("axc-recent", "clock", "Recent activity", `<button type="button" class="linkbtn" data-occ-to="notifications">View all</button>`,
      all.length ? `<ul class="axc-feed">${all.map(a => `<li><button type="button" class="axc-feed-i" ${a.go ? go(a.go) : a.nt != null ? `data-occ-to="notifications"` : ""}><span class="axc-dot t-${a.tone}">${icon(a.ic)}</span>
        <span class="axc-li-t"><b>${esc(a.text)}</b>${a.where ? `<small>${esc(a.where)}</small>` : ""}</span><span class="faint small num">${ago(a.ts)}</span></button></li>`).join("")}</ul>` : empty("Nothing has happened yet today."));
  }

  function actions() {
    quick = QUICK.filter(q => usable(q[2])).slice(0, 6);
    return card("axc-quick", "zap", "Quick actions", "", `<div class="axc-qa">${quick.map(([ic, l], i) => `<button type="button" class="axc-qa-b" data-axc-q="${i}">${icon(ic)}<span>${l}</span></button>`).join("")}</div>`);
  }

  function assistant(so, h, live, comps, crit) {
    const ready = typeof Assist !== "undefined" && Assist.ready();
    const now = [so && `${plural(so.counts.agents, "agent")}, ${so.counts.working} working`, `${plural(live, "run")} live`, crit && `${plural(crit, "critical alert")}`, `${plural(d.counts.pending, "approval")} pending`,
                 comps && `${plural(comps, "competition")} tracked`, h.text].filter(Boolean);
    return `<aside class="card occ-card axc-ai" aria-label="AI Assistant"><div class="occ-ch"><h3>${icon("sparkle")}AI Assistant</h3></div>
      <div class="axc-ai-sum"><span class="axc-ai-av">${icon("bot")}</span><div><b>Right now</b><ul>${now.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div></div>
      ${ready ? `<div class="axc-ai-q">${ASKS.map((q, i) => `<button type="button" class="axc-chip" data-axc-ask="${i}">${esc(q)}</button>`).join("")}</div>
        <form class="axc-ai-f" data-axc-form><input type="text" name="q" maxlength="2000" placeholder="Ask anything…" aria-label="Ask the assistant" autocomplete="off">
          <button type="submit" class="btn sm primary" aria-label="Send">${icon("send")}</button></form>
        <p class="faint small">Answers open in the Assist panel, in your chat with the Assistant. It reads live AXoR data.</p>`
        : `<p class="faint small">The assistant needs agents and a model. ${usable("#tab-agents") ? `Set one up under <button type="button" class="linkbtn" data-occ-to="agents">Agents</button>.` : "An administrator can turn agents on for your account."}</p>`}
    </aside>`;
  }

  function tabs(o, so) {
    const runs = so?.running?.length ? so.running.map(r => ({ title: r.title, who: r.agent, status: r.status, since: r.started, where: r.where, go: r.go }))
      : o.running.map(r => ({ title: r.what, who: r.who, status: "running", since: r.since, where: r.where, go: r.go }));
    const sys = so ? Object.entries(so.systems) : [];
    const T = [["missions", "Active missions", runs.length], ["agents", "Running agents", so ? so.counts.working : null], ["events", "System events", null], ["perf", "Performance", null]];
    if (!T.some(t => t[0] === cctab)) cctab = "missions";
    let body = "";
    if (cctab === "missions") body = runs.length ? `<div class="tablewrap flat"><table class="grid axc-table" data-plt-skip><thead><tr><th>Mission</th><th>Agent</th><th>Status</th><th>Where</th><th class="r">Started</th></tr></thead><tbody>
        ${runs.slice(0, 12).map(r => `<tr><td><button type="button" class="linkbtn" ${go(r.go)}>${esc(r.title)}</button></td><td>${esc(r.who || "")}</td><td>${pill("s-" + (/fail|error/.test(r.status) ? "crit" : /review|wait/.test(r.status) ? "warn" : "ok"), r.status || "running")}</td>
          <td class="faint">${esc(r.where || "")}</td><td class="r num faint">${r.since ? clock(r.since) : "–"}</td></tr>`).join("")}</tbody></table></div>`
      : empty(d.agents ? "No agent is working right now. Teams on autopilot start again on their own schedule." : "Agents aren't turned on for your account.");
    if (cctab === "agents") body = so ? `<div class="tablewrap flat"><table class="grid axc-table" data-plt-skip><thead><tr><th>System</th><th class="r">Agents</th><th class="r">Working</th><th></th></tr></thead><tbody>
        ${sys.map(([k, s]) => `<tr><td>${esc(s.label)}</td><td class="r num">${s.agents}</td><td class="r num">${s.working ? `<span class="axc-live"><i></i>${s.working}</span>` : "0"}</td><td class="r">${s.go ? `<button type="button" class="linkbtn" ${go(s.go)}>Open</button>` : ""}</td></tr>`).join("")}</tbody></table></div>
        ${o.teams.length ? `<ul class="occ-teams">${o.teams.slice(0, 6).map(x => { const [cls, name] = STATE[x.state] || ["off", x.state];
          return `<li><button type="button" class="occ-row" ${go({ view: "teams", wid: x.id, sub: "status" })}><span class="occ-need-t"><b>SN${x.netuid} · ${esc(x.label)}</b><small>${esc(x.line || "")}</small></span><span class="occ-prog" title="${x.done} of ${x.total} tasks done"><i style="width:${x.total ? Math.round(x.done / x.total * 100) : 0}%"></i></span>${pill("s-" + cls, name)}</button></li>`; }).join("")}</ul>` : ""}`
      : empty("Agent counts show here once agents are on for you.");
    if (cctab === "events") { const feed = Notify.feed(); body = `<div class="dash-alerts">${Notify.listHtml((feed.items || []).slice(0, 8), feed.last_read)}</div>`; }
    if (cctab === "perf") body = `<div class="axc-perf">${performance(o)}${resources(o)}</div>`;
    return `<section class="card axc-tabs"><nav class="axh-tabs" role="tablist" aria-label="Operations">${T.map(([k, l, n]) => `<button type="button" role="tab" data-axc-tab="${k}" aria-selected="${cctab === k}">${l}${n ? ` <b class="occ-n">${n}</b>` : ""}</button>`).join("")}</nav>
      <div class="axc-tab-b">${body}</div></section>`;
  }
  function promo() {
    return `<section class="card axc-promo"><img src="/static/brand/neural-portrait.webp" alt="" loading="lazy"><div><b>AXoR 2.0</b><span>Build · Orchestrate · Evolve</span>
      <button type="button" class="btn sm primary" data-axc-help>Learn more${icon("right")}</button></div></section>`;
  }
  function performance(o) {
    const m = o.miners;
    return `<div><h4 class="occ-h4">${icon("trophy")}Miners</h4>${m.length ? `<table class="grid mini-table occ-miners" data-plt-skip><thead><tr><th>Miner</th><th class="r">Rank</th><th class="r">τ / day</th><th class="r occ-gap">Gap</th></tr></thead><tbody>
      ${m.map(x => `<tr><td><button type="button" class="linkbtn" data-occ-to="mining">SN${x.netuid}${x.name ? ` · ${esc(x.name)}` : ""}</button>${x.critical ? ` ${pill("s-crit", "alert")}` : ""}</td>
        <td class="r num">${x.rank != null ? `${x.rank}${x.of ? `<span class="faint">/${x.of}</span>` : ""}` : "–"}</td><td class="r num">${x.em != null ? fmtNum(x.em, 3) : "–"}</td>
        <td class="r num occ-gap">${x.gap != null ? fmtNum(x.gap, 3) : "–"}</td></tr>`).join("")}</tbody></table>` : empty("No miner tracked yet: My subnets adds your miners' ranks after its first brief.")}</div>`;
  }
  function resources(o) {
    const sp = o.spend;
    if (!sp) return `<div><h4 class="occ-h4">${icon("chart")}Model use</h4>${empty("No agent spend to show.")}</div>`;
    const by = sp.by_source || [], bmax = Math.max(1, ...by.map(x => x.tokens || 0));
    return `<div><h4 class="occ-h4">${icon("chart")}Model use · ${tok(sp.month)} tokens this month</h4>
       ${by.length ? `<ul class="occ-by">${by.map(x => { const n = x.tokens || 0; return `<li><span>${esc(USAGE[x.id] || x.id || "")}</span><span class="occ-prog"><i style="width:${(n / bmax * 100).toFixed(0)}%"></i></span><b class="num">${tok(n)}</b></li>`; }).join("")}</ul>` : ""}
       ${sp.teams?.some(t => t.budget) ? `<h4 class="occ-h4">Team budgets today</h4><ul class="occ-by">${sp.teams.filter(t => t.budget).map(t => `<li><span>${esc(t.label)}</span><span class="occ-prog ${t.day > t.budget ? "over" : ""}"><i style="width:${Math.min(100, t.day / t.budget * 100).toFixed(0)}%"></i></span><b class="num">${tok(t.day)}/${tok(t.budget)}</b></li>`).join("")}</ul>` : ""}
       ${sp.workflow_usd_week != null ? `<p class="faint small">Workflow $${fmtNum(sp.workflow_usd_week, 2)} this week</p>` : ""}</div>`;
  }
  function kpi(ic, label, value, sub, tone, to) {
    const tag = to ? `button type="button" data-occ-view="${to}"` : "div";
    return `<${tag} class="stat occ-kpi ${tone ? "t-" + tone : ""}"><div class="label">${icon(ic)}${label}</div><div class="value">${esc(String(value))}</div><div class="sub">${esc(sub)}</div></${to ? "button" : "div"}>`;
  }

  // ---------- Approval Center ----------
  function approvals() {
    const P = d.pending, by = d.counts.by_source, keys = Object.keys(SRC).filter(k => by[k]);
    if (filt !== "all" && !by[filt]) filt = "all";
    const ql = q.trim().toLowerCase();
    const list = P.filter(p => (filt === "all" || p.source === filt) && (!ql || `${p.title} ${p.detail} ${p.where}`.toLowerCase().includes(ql)));
    const week = d.history.filter(h => h.ts > Date.now() / 1000 - 7 * 86400);
    const oldest = P.length ? Math.min(...P.map(p => p.ts || d.at)) : null;
    const admin = Auth.me()?.role === "admin";
    return `<div class="occ">
      <div class="occ-head"><div><p class="occ-kicker">${icon("shield")}AXoR 2.0 · Governance</p><h1 class="page">Approval Center</h1>
        <p class="lead">Every request waiting for your decision, from every agent system. Each opens on its own page with its evidence, where you approve or reject it: nothing runs in production without you. <span class="faint" data-occ-at>Updated ${ago(d.at)}</span></p></div>
        <div class="row"><button type="button" class="btn sm" data-occ="refresh">${icon("cycle")}Refresh</button>${admin ? `<button type="button" class="btn sm" data-occ="audit">${icon("clock")}Audit log</button><button type="button" class="btn sm" data-occ-to="admin">${icon("users")}Permissions</button>` : ""}</div></div>

      <div class="stats occ-kpis">
        ${kpi("inbox", "Waiting", P.length, P.length ? `${keys.length} system${keys.length === 1 ? "" : "s"}` : "all clear", P.length ? "warn" : "ok", null)}
        ${kpi("alert", "Urgent or high risk", d.counts.urgent + P.filter(p => p.level !== "stop" && /high|care/i.test(p.risk || "")).length, "decide these first", d.counts.urgent ? "crit" : "", null)}
        ${kpi("clock", "Oldest waiting", oldest ? ago(oldest) : "–", oldest ? `${d.counts.stale ? `${d.counts.stale} stale (over ${d.counts.stale_h} h)` : "since it was asked"}${d.counts.duplicates ? ` · ${d.counts.duplicates} repeat${d.counts.duplicates === 1 ? "" : "s"} folded` : ""}` : "nothing waits", d.counts.stale ? "warn" : "", null)}
        ${kpi("check", "Decided in 7 days", week.length, `${week.filter(h => DONE[h.status] === "ok").length} approved or done · ${week.filter(h => DONE[h.status] === "crit").length} rejected or failed`, "", null)}
      </div>

      <nav class="axh-tabs" role="tablist" aria-label="Governance">${[["queue", "inbox", "Waiting for you", P.length], ["recs", "bulb", "Recommendations", gv?.recs.length], ["runs", "play", "Executions", gv?.runs.length],
          ["audit", "clock", "Audit trail"], ["perms", "lock", "Permissions"]].map(([k, ic, l, n]) => `<button type="button" role="tab" data-occ-tab="${k}" aria-selected="${aptab === k}">${icon(ic)}${l}${n ? ` <b>${n}</b>` : ""}</button>`).join("")}</nav>
      ${aptab !== "queue" ? govBody() : `
      <div class="occ-ap-bar"><div class="occ-filters" role="group" aria-label="Filter by system">
          <button type="button" class="chip" data-occ-f="all" aria-pressed="${filt === "all"}">All <b>${P.length}</b></button>
          ${keys.map(k => `<button type="button" class="chip" data-occ-f="${k}" aria-pressed="${filt === k}">${icon(SRC[k][0])}${SRC[k][1]} <b>${by[k]}</b></button>`).join("")}</div>
        <label class="search occ-q"><span class="sr">Search requests</span>${icon("search")}<input type="search" id="occ-q" placeholder="Search requests…" value="${esc(q)}" autocomplete="off"></label></div>

      ${!d.agents ? `<div class="card empty">Agents aren't turned on for your account, so no agent asks you for anything.</div>`
        : list.length ? `<ul class="occ-ap">${list.map(apItem).join("")}</ul>`
        : `<div class="card empty">${P.length ? "No request matches." : `${icon("check")} Nothing waits for your decision.`}</div>`}

      <h2 class="section-title occ-sec">${icon("clock")}Decision history <span class="count faint">${d.history.length}</span></h2>
      ${d.history.length ? `<div class="tablewrap flat"><table class="grid occ-hist" data-plt-skip><thead><tr><th>When</th><th>System</th><th>Request</th><th>Decision</th><th>By</th><th>Note</th></tr></thead><tbody>
        ${d.history.map(h => `<tr><td class="num faint" title="${new Date(h.ts * 1000).toLocaleString()}">${ago(h.ts)}</td><td>${icon(src(h.source)[0])} ${esc(src(h.source)[1])}</td><td>${esc(h.title)}</td>
          <td>${pill("s-" + (DONE[h.status] || "off"), (h.status || "").replace(/_/g, " "))}</td><td>${esc(h.by)}</td><td class="faint occ-note">${esc(h.note)}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="card empty">No decisions yet.</div>`}`}
    </div>`;
  }
  // ---------- governance tabs: what agents recommend, what ran, who did what, who may do what ----------
  function govBody() {
    if (!gv) return gvErr ? `<div class="card empty">${esc(gvErr)}</div>` : `<div class="occ-grid">${Loading.cards(2, "card")}</div>`;
    const SYS = { ...SRC, agents: ["bot", "Your agents"], account: ["key", "Your account"] }, s = k => SYS[k] || ["info", k];
    const tone = x => "s-" + (DONE[x] || (/run/.test(x || "") ? "info" : /pend|wait/.test(x || "") ? "warn" : "off"));
    if (aptab === "recs") return gv.recs.length ? `<p class="faint small">What your agents suggest but haven't asked to run yet. Accept or dismiss each on its own page.</p><ul class="occ-ap">${gv.recs.map(r => `<li class="occ-ap-i l-info"><span class="occ-mark"></span>
        <div class="occ-ap-m"><div class="occ-ap-h">${pill("src", s(r.source)[1], s(r.source)[0])}${r.impact ? pill(/high|critical|better/i.test(r.impact) ? "s-ok" : "s-info", `Impact: ${r.impact}`) : ""}${r.effort ? pill("s-off", `Effort: ${r.effort}`) : ""}<span class="faint small">${esc(r.who || "")}</span></div>
        <b>${esc(r.title)}</b>${r.detail ? `<p>${esc(r.detail)}</p>` : ""}<small class="faint">${r.ts ? `suggested ${ago(r.ts)}` : ""}</small></div>
        <button type="button" class="btn sm" ${go(r.go)}>Open${icon("right")}</button></li>`).join("")}</ul>` : `<div class="card empty">${icon("bulb")} No open recommendations.</div>`;
    if (aptab === "runs") return gv.runs.length ? `<p class="faint small">Approved actions and what came of them.</p><div class="tablewrap flat"><table class="grid occ-hist" data-plt-skip><thead><tr><th>When</th><th>System</th><th>Action</th><th>Result</th><th>By</th><th>Outcome</th></tr></thead><tbody>
        ${gv.runs.map(r => `<tr><td class="num faint">${ago(r.ts)}</td><td>${icon(s(r.source)[0])} ${esc(s(r.source)[1])}</td><td>${esc(r.title)}</td><td>${pill(tone(r.status), r.status || "–")}${r.verified ? ` ${pill("s-ok", "verified")}` : ""}</td><td>${esc(r.by || "")}</td><td class="faint occ-note">${esc(r.result || "")}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="card empty">Nothing has been executed yet.</div>`;
    if (aptab === "audit") return `<p class="faint small">The Company's audit log and your own account's events.${gv.admin ? ` Everyone's sign-ins and changes are in the <button type="button" class="linkbtn" data-occ="audit">full audit log</button>.` : ""}</p>
      ${gv.audit.length ? `<div class="tablewrap flat"><table class="grid occ-hist" data-plt-skip><thead><tr><th>When</th><th>Where</th><th>Who</th><th>What</th><th>On</th></tr></thead><tbody>
        ${gv.audit.map(a => `<tr><td class="num faint" title="${new Date(a.ts * 1000).toLocaleString()}">${ago(a.ts)}</td><td>${icon(s(a.source)[0])} ${esc(s(a.source)[1])}</td><td>${esc(a.actor || "")}</td><td>${esc((a.action || "").replace(/[._]/g, " "))}</td><td class="faint occ-note">${esc(a.target || "")}${a.ip ? ` · ${esc(a.ip)}` : ""}</td></tr>`).join("")}</tbody></table></div>`
        : `<div class="card empty">No events yet.</div>`}`;
    const P = gv.perms, C = P.company;
    return `<div class="occ-grid">
      <section class="card occ-card axh-span12"><div class="occ-ch"><h3>${icon("key")}Who decides</h3>${gv.admin ? `<button type="button" class="linkbtn" data-occ-to="admin">Users &amp; permissions</button>` : ""}</div>
        <ul class="axh-kv"><li><span>Your role</span><b>${P.role === "admin" ? "Administrator" : "Member"}</b></li>
          ${C ? `<li><span>Company autonomy</span>${pill(C.autonomy === "autonomous" ? "s-warn" : "s-ok", C.autonomy || "managed")}</li><li><span>Company actions turned off</span><b>${C.actions_off.length ? esc(C.actions_off.map(k => C.actions[k] || k).join(", ")) : "none"}</b></li>
            <li><span>Actions that always need your approval</span><b>${esc(Object.values(C.actions).join(" · "))}</b></li>` : ""}</ul></section>
      ${P.teams.length ? `<section class="card occ-card axh-span12"><div class="occ-ch"><h3>${icon("users")}Competition teams' limits</h3></div><div class="tablewrap flat"><table class="grid occ-hist" data-plt-skip><thead><tr><th>Team</th><th>Autopilot</th><th>State</th><th class="r">Daily token budget</th><th></th></tr></thead><tbody>
        ${P.teams.map(t => `<tr><td>${esc(t.name)}</td><td>${pill(t.autopilot ? "s-warn" : "s-off", t.autopilot ? "on" : "off")}</td><td>${pill(t.paused ? "s-warn" : "s-ok", t.paused ? "paused" : "running")}</td><td class="r num">${t.budget ? fmtNum(t.budget, 0) : "–"}</td><td class="r"><button type="button" class="linkbtn" ${go(t.go)}>Settings</button></td></tr>`).join("")}</tbody></table></div></section>` : ""}
      ${P.agents.length ? `<section class="card occ-card axh-span12"><div class="occ-ch"><h3>${icon("layers")}Company agent contracts</h3><span class="faint small">${P.agents.length} agents</span></div><div class="tablewrap flat"><table class="grid occ-hist" data-plt-skip><thead><tr><th>Agent</th><th>Role</th><th>Stage</th><th class="r">Max load</th><th>Tools on</th><th>Contract</th></tr></thead><tbody>
        ${P.agents.map(a => `<tr><td><button type="button" class="linkbtn" ${go(a.go)}>${esc(a.name)}</button></td><td class="faint">${esc(a.role)}</td><td>${pill("s-info", a.stage || "–")}</td><td class="r num">${a.max_load ?? "–"}</td><td class="num">${a.tools ? `${a.tools[0]}/${a.tools[1]}` : "defaults"}</td><td class="faint occ-note" title="${esc(Object.entries(a.may || {}).map(([k, v]) => `${k}: ${v.join(", ") || "nothing"}`).join("\n"))}">${esc(Object.entries(a.may || {}).filter(([, v]) => v.length).map(([k, v]) => `${k} ${v.length}`).join(" · ") || "–")}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
      ${P.workforce.length ? `<section class="card occ-card axh-span12"><div class="occ-ch"><h3>${icon("group")}Workforce tool grants</h3></div><div class="tablewrap flat"><table class="grid occ-hist" data-plt-skip><thead><tr><th>Agent</th><th>Team</th><th>Level</th><th>Tools</th></tr></thead><tbody>
        ${P.workforce.map(a => `<tr><td>${esc(a.name)}</td><td>${esc(a.team)}</td><td>${esc(a.level || "")}</td><td class="faint occ-note" title="${esc((a.tools || []).join(", "))}">${(a.tools || []).length ? `${a.tools.length}: ${esc(a.tools.slice(0, 6).join(", "))}${a.tools.length > 6 ? "…" : ""}` : "none"}</td></tr>`).join("")}</tbody></table></div></section>` : ""}
      ${!C && !P.teams.length && !P.workforce.length ? `<div class="card empty axh-span12">No agent system is set up for you, so there are no agent permissions to show.</div>` : ""}
    </div>`;
  }
  function apItem(p) {
    const [ic, name] = src(p.source), [lv, lvName] = LEVEL[p.level] || LEVEL.warn, left = p.expires ? p.expires - Date.now() / 1000 : null;
    return `<li class="occ-ap-i l-${lv}"><span class="occ-mark" title="${lvName}"></span>
      <div class="occ-ap-m"><div class="occ-ap-h">${pill("src", name, ic)}${pill("s-" + lv, lvName)}${p.risk ? pill(/high|care/i.test(p.risk) ? "s-crit" : "s-warn", `Risk: ${p.risk}`) : ""}
          ${left != null ? `<span class="faint small">${left > 0 ? `expires ${until(p.expires)}` : "expired"}</span>` : ""}
          ${p.stale ? pill("s-warn", `Stale: waited ${p.age_h >= 48 ? `${Math.round(p.age_h / 24)} days` : `${Math.round(p.age_h)} h`}`, "clock") : ""}
          ${p.copies?.length ? pill("s-warn", `Asked ${p.copies.length + 1}×: shown once`, "copy") : ""}</div>
        <b>${esc(p.title)}</b>${p.detail ? `<p>${esc(p.detail)}</p>` : ""}
        <small class="faint">${esc(p.where || "")}${p.ts ? ` · asked ${ago(p.ts)}` : ""}</small></div>
      <span class="occ-ap-acts">${p.archive && (p.stale || p.copies?.length) ? `<button type="button" class="btn sm ghost" data-occ-archive="${[p.id, ...(p.copies || []).filter(c => c.archive).map(c => c.id)].join(",")}" title="Save ${p.copies?.length ? "these imports" : "this import"} for later (Import competitions → Drafts): out of the queue, not rejected">${icon("folder")}Archive</button>` : ""}
      <button type="button" class="btn sm ${p.level === "stop" ? "primary" : ""}" ${go(p.go)}>${esc(p.label)}${icon("right")}</button></span></li>`;
  }

  // ---------- where an item leads ----------
  function follow(g) {
    if (!g) return;
    if (g.view === "teams" && g.intake) { MiningWork.openPage(null); return MiningSources.open("queue"); }
    if (g.view === "teams") { MiningWork.openPage(g.wid); if (g.sub) MiningWork.go(g.sub); return; }
    if (g.view === "workspace") return Workspace.show(g.netuid, g.tab);
    if (g.view === "knowledge") return Knowledge.show(g.tab, g.id);
    if (g.view === "mos") return MissionOS.show(g.id);
    if (g.view === "market") return Market.show(g.id);
    if (g.view === "org" && typeof Organization !== "undefined") return Organization.show(g.tab);
    setView(g.view);
    if (g.view === "company" && g.tab) {  // the Company's own tab strip: pressed once it has drawn
      const t0 = Date.now(), tick = () => { const b = $(`#view-company [data-cotab="${g.tab}"]`); if (b) { if (b.getAttribute("aria-selected") !== "true") b.click(); } else if (Date.now() - t0 < 6000) setTimeout(tick, 150); };
      tick();
    }
  }
  function wire() {
    if (wired) return; wired = true;
    const click = e => {
      const t = e.target;
      const g = t.closest("[data-occ-go]"); if (g) return follow(gos[+g.dataset.occGo]);
      const ar = t.closest("[data-occ-archive]");
      if (ar) { const ids = ar.dataset.occArchive.split(",").map(Number);
        return UI.confirm({ title: `Archive ${ids.length === 1 ? "this import" : `${ids.length} imports`}?`, body: "They leave the queue as drafts in Import competitions, where you can put them back or reject them. Nothing is approved or rejected.", ok: "Archive", icon: "folder", danger: false,
          run: async () => { const r = await api("/api/command/archive", { method: "POST", body: { source: "mining", kind: "import", ids } }); d = r; badge(); draw(); Auth.toast(`${r.archived} archived`); } }).catch(e => Auth.toast(e.message)); }
      const v = t.closest("[data-occ-view]"); if (v) return setView(v.dataset.occView);
      const to = t.closest("[data-occ-to]"); if (to) return setView(to.dataset.occTo);
      const tb = t.closest("[data-occ-tab]"); if (tb) { aptab = tb.dataset.occTab; try { localStorage.setItem("occ.aptab", aptab); } catch {} draw(); if (aptab !== "queue" && !gv) governance(true).then(draw); return; }
      const f = t.closest("[data-occ-f]"); if (f) { filt = f.dataset.occF; try { localStorage.setItem("occ.filter", filt); } catch {} return draw(); }
      const ct = t.closest("[data-axc-tab]"); if (ct) { cctab = ct.dataset.axcTab; try { localStorage.setItem("occ.cctab", cctab); } catch {} return draw(); }
      const cc = t.closest("[data-axc-chart]"); if (cc) { chart = cc.dataset.axcChart; try { localStorage.setItem("occ.chart", chart); } catch {} return draw(); }
      const qa = t.closest("[data-axc-q]"); if (qa) return quick[+qa.dataset.axcQ]?.[3]();
      const ak = t.closest("[data-axc-ask]"); if (ak) return Assist.ask(ASKS[+ak.dataset.axcAsk]);
      if (t.closest("[data-axc-help]")) { Help.route("help/command-center"); return setView("help"); }
      const a = t.closest("[data-occ]")?.dataset.occ;
      if (a === "refresh") { sig = ""; return load(true); }
      if (a === "audit") return Platform.audit();
      const nt = t.closest("[data-nt]"); if (nt && !t.closest("button")) { const x = (Notify.feed().items || []).find(i => i.id === +nt.dataset.nt); if (x?.url) return window.open(x.url, "_blank", "noopener"); if (x?.netuid != null) return openDrawer(x.netuid); }
    };
    $("#view-command").addEventListener("click", click);
    $("#view-command").addEventListener("submit", e => {
      const f = e.target.closest("[data-axc-form]"); if (!f) return;
      e.preventDefault();
      const text = f.elements.q.value.trim(); if (!text) return;
      f.elements.q.value = "";
      Assist.ask(text);
    });
    $("#view-approvals").addEventListener("click", click);
    $("#view-approvals").addEventListener("input", e => {
      if (e.target.id !== "occ-q") return;
      q = e.target.value; const pos = e.target.selectionStart;
      draw(); const i = $("#occ-q"); if (i) { i.focus(); i.setSelectionRange(pos, pos); }
    });
  }

  // ---------- sidebar counts ----------
  function badge() {
    if (!d) return;
    const set = (id, n) => { const el = $(id); if (el && el.textContent !== (n ? String(n) : "")) el.textContent = n ? String(n) : ""; };
    set("#c-approvals", d.counts.pending);
    set("#c-command", d.overview.counts.stop);
    set("#c-knowledge", d.counts.by_source?.knowledge || 0);
    set("#c-market", d.counts.by_source?.market || 0);  // the Agent Marketplace's versions waiting for approval  // the Knowledge hub's proposals and imports in preview
    ["#nav-org", "#nav-projects", "#nav-missions", "#nav-evaluation"].forEach(id => { const b = $(id); if (b && b.hidden === d.agents) b.hidden = !d.agents; });  // the agent hubs, like the agent pages
  }
  async function poll() {
    if (!Auth.me() || document.hidden || view) return;  // an open page already refreshes it
    try { d = await api("/api/command"); badge(); } catch {}
  }

  function open(v) {
    wire();
    if (v !== view) sig = "";
    view = v;
    draw();
    load(true);
    clearInterval(timer);
    timer = setInterval(() => { if (!document.hidden) load(false); }, EVERY);
    clearInterval(clockTimer); clockTimer = setInterval(stamp, 30000);  // the clock and "Updated …", without a redraw
  }
  function stop() { clearInterval(timer); clearInterval(clockTimer); timer = clockTimer = null; view = ""; }
  function init() {
    if (!Auth.me() || badgeTimer) return;
    poll();
    badgeTimer = setInterval(poll, BADGE_EVERY);
  }
  // open the Approval Center filtered to one system (e.g. "mining" from My subnets: its approvals are a view of this one queue)
  function filter(k) { filt = k || "all"; try { localStorage.setItem("occ.filter", filt); } catch {} }
  return { init, open, stop, follow, filter, data: () => d };
})();
