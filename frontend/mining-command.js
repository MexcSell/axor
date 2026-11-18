/* My subnets → Command center (mining_command.py): the Bittensor division's control room, competition-first. My subnets shows it
   instead of a campaign when you pick Command center in the campaigns row (mining.js mounts it into its body).
   - Dashboard: key numbers (the evaluator's score, on-chain rank and τ a day, miners up, experiments in flight, approvals and
     checks waiting), competition operations (a row per competition team), critical checks, the approval queue, the subnets.
   - Competitions: a competition's HQ: overview, intelligence, miners, agent team, performance, experiments, files, knowledge
     and strategy, each with where to go for more (the Competition teams page, the campaign's tabs).
   - Performance: the Performance Lab: every metric the evaluator, you or the Lab measured over time, the on-chain rank of your
     miners, the Lab's scored runs, how to connect the evaluator, and recording a measurement.
   - Experiments: the Experiment Center: idea → proposal → sandbox → evaluation → recommendation → approval → production →
     monitoring, as a board; an experiment opens in a dialog with each stage's work and its log.
   - Miners, Rewards, Approvals, Monitoring, Agents and Settings (ingest keys, the token rate, runs needed, primary metrics).
   Numbers nobody measured show as "–" with how to measure them; nothing here deploys, signs or stakes anything. */
const MiningCommand = (() => {
  const C = "/api/mining/command";
  const SECS = [["dash", "Dashboard", "dash"], ["comp", "Competitions", "trophy"], ["perf", "Performance", "chart"], ["exp", "Experiments", "bulb"],
                ["miners", "Miners", "pickaxe"], ["rewards", "Rewards", "coins"], ["approvals", "Approvals", "hand"], ["monitor", "Monitoring", "radio"],
                ["agents", "Agents", "users"], ["settings", "Settings", "gear"]];
  const FLOW = [["Subnet", "dash"], ["Competition", "comp"], ["Performance", "perf"], ["Team", "agents"], ["Experiments", "exp"], ["Evaluate", "exp"],
                ["Approve", "approvals"], ["Monitor", "monitor"], ["Rewards", "rewards"]];
  const STATE = { working: ["run", "Working"], stuck: ["bad", "Stuck"], waiting: ["warn", "Waiting for you"], idle: ["none", "Idle"], closed: ["off", "Closed"] };
  const HEALTH = { up: ["ok", "Up"], erroring: ["warn", "Errors"], down: ["bad", "Down"], silent: ["bad", "Silent"], unknown: ["none", "Not reporting"] };
  const EVAL = { live: ["ok", "Evaluator live"], stale: ["warn", "Evaluator quiet"], none: ["none", "No evaluator"] };
  const VERDICT = { better: ["ok", "Better"], worse: ["bad", "Worse"], noise: ["none", "Within noise"], too_few: ["warn", "Too few runs"] };
  const REC = { recommend: ["ok", "Recommend"], hold: ["warn", "Hold"], reject: ["bad", "Reject"] };
  const APPR = { pending: ["warn", "Waiting for you"], approved: ["ok", "Approved"], consumed: ["run", "Authorized"], rejected: ["bad", "Rejected"],
                 changes: ["warn", "Changes asked"], expired: ["off", "Expired"] };
  const MON = { waiting: ["none", "Waiting for evaluator data"], holding: ["ok", "Holding"], regressed: ["bad", "Regressed"], constraint: ["warn", "A constraint got worse"],
                no_baseline: ["none", "No baseline to compare"] };
  const LEVEL = { stop: ["bad", "alert"], warn: ["warn", "info"], info: ["none", "info"] };
  const SRC = { experiment: ["Deploy approval", "rocket"], company: ["Company approval", "shield"], miner_action: ["Miner action", "pickaxe"], merge: ["Workflow merge", "branch"] };
  let el = null, sec = null, wid = null, d = null, cache = {}, failed = "", timer = null, wired = false, eid = null, ex = null, mid = null, mn = null, newKey = null;
  let af = { q: "", net: "", team: "", squad: "", status: "" }, days = 30;
  const err = e => e && Auth.toast(e.message);
  const put = (node, html) => { if (node && node.dataset.html !== html) { node.innerHTML = html; node.dataset.html = html; } };
  const chip = ([cls, text], ic = "") => `<span class="hq-chip t-${cls}">${ic ? icon(ic) : ""}${text}</span>`;
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const hk = s => s ? `${s.slice(0, 6)}…${s.slice(-4)}` : "–";
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
  const M = () => d?.metrics || cache.perf?.metrics || {};
  // a metric's value in its unit: shares as %, latency in ms, dollars, ranks with #
  function val(k, v) {
    if (v == null) return "–";
    const u = (M()[k] || [])[1];
    return u === "%" ? `${fmtNum(v * 100, 1)}%` : u === "ms" ? `${fmtNum(v, 0)} ms` : u === "$" ? usd(v) : u === "#" ? `#${fmtNum(v, 0)}` : u === "/min" ? `${fmtNum(v)}/min` : fmtNum(v, 3);
  }
  const mlabel = k => (M()[k] || [k])[0];
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- mounting (My subnets calls mount() while Command center is picked, and stop() when it isn't) ----------
  function mount(node) {
    const fresh = node !== el;  // My subnets re-renders often: only a new mount loads
    el = node; wire();
    if (sec === null) { sec = store.get("mc.sec", "dash"); wid = store.get("mc.wid", null); }
    if (fresh) { render(); load(); }
  }
  function stop() { clearTimeout(timer); el = null; }
  const shown = () => el?.isConnected && !$("#view-mining")?.hidden;
  async function load(force) {
    try {
      if (!d || force || sec === "dash") d = await api(force ? `${C}?fresh=1` : C);
      if (!wid || !d.comps.some(c => c.id === wid)) wid = d.comps[0]?.id ?? null;  // before the paths: a stored team may be gone
      const want = { dash: [""], comp: ["", `/comps/${wid}`], perf: ["", `/comps/${wid}/performance?days=${days}`], exp: ["/experiments"], miners: ["/miners"], rewards: ["/rewards"],
                     approvals: ["/approvals"], monitor: ["/monitoring"], agents: ["/agents"], settings: ["/settings"] }[sec] || [""];
      for (const p of want.slice(sec === "dash" ? 1 : 0)) {
        if (p === "") continue;
        if (p.includes("/comps/") && !wid) continue;
        cache[sec] = await api(C + p);
      }
      failed = "";
    } catch (e) { failed = e.message; }
    if (!typing()) render();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { if (!shown()) return; if (document.visibilityState !== "visible") return schedule(); load(); }, ["dash", "approvals", "monitor"].includes(sec) ? 20000 : 60000);
  }
  const typing = () => !!document.activeElement?.closest?.(".mcx form, .mcx input, .mcx textarea, .mcx select");
  function go(s, w) {
    if (sec === null) wid = store.get("mc.wid", null);  // from the shell's rail before the first mount
    sec = s; store.set("mc.sec", s);
    if (w != null) { wid = w; store.set("mc.wid", w); cache.comp = cache.perf = null; }
    if (el) { render(); load(); }
  }

  // ---------- the frame ----------
  function render() {
    if (!el) return;
    if (!d) { put(el, failed ? `<div class="empty">${esc(failed)} <button type="button" class="linkbtn" data-mc="reload">Try again</button></div>` : Loading.line("Opening the command center…")); return; }
    const n = { approvals: d.approvals_n, monitor: d.critical.length };
    const at = { dash: 0, comp: 1, perf: 2, agents: 3, exp: 4, approvals: 6, monitor: 7, rewards: 8 }[sec];
    const body = { dash, comp: compHQ, perf, exp: experiments, miners, rewards, approvals, monitor, agents, settings }[sec] || dash;
    put(el, `<div class="mcx">
      <div class="mcx-flow" aria-label="The operating loop">${FLOW.map(([l, s], i) => `<button type="button" class="${i === at ? "on" : ""}" data-mcgo="${s}">${i ? icon("right") : ""}<span>${l}</span></button>`).join("")}</div>
      <div class="seg hq-tabs mcx-tabs" role="tablist" aria-label="Command center">${SECS.map(([k, l, ic]) => `<button type="button" role="tab" data-mcgo="${k}" aria-pressed="${sec === k}">${icon(ic)}${l}${n[k] ? `<span class="hq-n alert">${n[k]}</span>` : ""}</button>`).join("")}</div>
      <div class="mcx-body">${failed ? `<p class="mh-err small">${icon("info")}${esc(failed)}</p>` : ""}${body()}</div></div>`);
    if (sec === "perf") drawCharts();
  }
  function compPicker(target) {
    if (!d.comps.length) return "";
    return `<div class="mcx-picker" role="tablist" aria-label="Competition teams">${d.comps.map(c => `<button type="button" class="mh-camp ${c.id === wid ? "on" : ""}" data-mcw="${c.id}" data-mct="${target}" aria-pressed="${c.id === wid}">
      <span class="ci ci-${c.state === "working" ? "run" : c.state === "stuck" ? "bad" : c.state === "waiting" ? "warn" : "none"}"></span><b>SN${c.netuid}</b><span>${esc(c.number ?? c.name)}</span></button>`).join("")}</div>`;
  }
  const noTeams = () => `<section class="mh-card mcx-empty"><h3>${icon("trophy")}No competition team yet</h3>
    <p>The command center runs on competition teams: open a campaign below the row of campaigns, then <b>Teams</b>, and put a team on its competition (Import competitions brings them in for your approval).</p></section>`;
  const kpi = (cls, ic, label, value, small, goTo) => `<${goTo ? `button type="button" data-mcgo="${goTo}"` : "div"} class="mh-kpi ${cls}">${icon(ic)}<span class="mh-kpi-l">${label}</span><b>${value}</b><small>${small}</small></${goTo ? "button" : "div"}>`;
  const panel = (title, ic, inner, extra = "") => `<section class="mh-card mcx-panel"><h2 class="hq-h">${icon(ic)}${title}${extra}</h2>${inner}</section>`;

  // ---------- dashboard ----------
  function dash() {
    if (!d.campaigns.length) return `<section class="mh-card mcx-empty"><h3>${icon("pickaxe")}No campaign yet</h3><p>Start with <b>New campaign</b> in the row above: pick a subnet and add your miner's hotkey. The command center fills in as My subnets takes snapshots and your teams, evaluator and miners report.</p></section>`;
    const s = d.score, ex = Object.values(d.experiments).reduce((a, b) => a + b, 0), best = d.campaigns.filter(c => c.best_rank).sort((a, b) => a.best_rank - b.best_rank)[0];
    const tiles = [
      kpi(s ? "ok" : "", "target", "Evaluator score", s ? val(s.primary, s.score) : "–", s ? `${esc(s.label)} · ${ago(s.score_ts)}` : "Connect the evaluator", s ? "perf" : "settings"),
      kpi(best ? (best.best_rank <= best.target ? "ok" : "warn") : "", "trophy", "Best on-chain rank", best ? `#${best.best_rank}<span class="mh-kpi-of"> / ${best.of || "?"}</span>` : "–", best ? `SN${best.netuid} · goal top ${best.target}` : "No ranked miner", "miners"),
      kpi(d.tau_day ? "run" : "", "coins", "Rewards a day", d.tau_day ? `${fmtNum(d.tau_day)} τ` : "–", d.tao_usd && d.tau_day ? `≈ ${usd(d.tau_day * d.tao_usd)} on chain` : "on-chain emissions", "rewards"),
      kpi(d.miners.silent ? "bad" : d.miners.up ? "ok" : "", "pickaxe", "Miners up", `${d.miners.up}<span class="mh-kpi-of"> / ${d.miners.n}</span>`, d.miners.silent ? `${d.miners.silent} silent or down` : d.miners.unknown ? `${d.miners.unknown} not reporting health` : "reporting", "miners"),
      kpi(ex ? "info" : "", "bulb", "Experiments", ex, ex ? Object.entries(d.experiments).map(([k, n]) => `${n} ${k}`).join(" · ") : "none open", "exp"),
      kpi(d.approvals_n ? "warn" : "", "hand", "Approvals", d.approvals_n, d.critical.length ? `${plural(d.critical.length, "critical check")}` : "production stays yours", "approvals")];
    return `<div class="mh-kpis mcx-kpis">${tiles.join("")}</div>
      <div class="mcx-grid">
        ${panel("Competition operations", "trophy", opsTable(), `<span class="faint">${plural(d.comps.length, "team")} · ${d.evaluators} with an evaluator</span>`)}
        <div class="mcx-side">
          ${panel("Critical", "alert", d.critical.length ? `<ul class="mcx-checks">${d.critical.map(check).join("")}</ul>` : `<p class="faint small">${icon("check")} Nothing critical.</p>`, `<button type="button" class="linkbtn" data-mcgo="monitor">All checks (${d.checks_n})</button>`)}
          ${panel("Approval queue", "hand", d.approvals.length ? `<ul class="mcx-queue">${d.approvals.slice(0, 5).map(a => `<li><span>${icon(SRC[a.source][1])}</span><div><b>${esc(a.title)}</b><span class="faint small">${SRC[a.source][0]}${a.where ? ` · ${esc(a.where)}` : ""} · ${ago(a.created)}</span></div>${chip(APPR[a.status] || APPR.pending)}</li>`).join("")}</ul>`
            : `<p class="faint small">Nothing waits for you.</p>`, `<button type="button" class="linkbtn" data-mcgo="approvals">Open</button>`)}
        </div>
      </div>
      ${panel("Subnets", "globe", `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Subnet</th><th>Competition</th><th class="r">Rank</th><th class="r">τ / day</th><th>Standing</th><th class="r">Teams</th></tr></thead><tbody>
        ${d.campaigns.map(c => `<tr data-mccamp="${c.id}" tabindex="0"><td><b>SN${c.netuid}</b> ${esc(c.subnet)}</td><td>${esc(c.comp)}</td><td class="r num">${c.best_rank ? `#${c.best_rank} / ${c.of || "?"}` : "–"}</td>
          <td class="r num">${fmtNum(c.tau_day)}</td><td>${c.standing ? chip({ green: ["ok", "On track"], amber: ["warn", "Needs a look"], red: ["bad", "Action needed"] }[c.standing] || ["none", c.standing]) : `<span class="faint">no brief</span>`} <span class="faint small">${esc(c.headline || "")}</span></td><td class="r num">${c.teams}</td></tr>`).join("")}</tbody></table></div>`,
        `<span class="faint">open one to see its Competition, My miners and Activity tabs</span>`)}`;
  }
  function opsTable() {
    if (!d.comps.length) return `<p class="faint small">No competition team yet: open a campaign, then Teams.</p>`;
    return `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Competition</th><th>Team</th><th class="r">Score</th><th>Evaluator</th><th>Experiments</th><th class="r">Agents</th></tr></thead><tbody>
      ${d.comps.map(c => { const dl = c.score != null && c.score_prev != null ? c.score - c.score_prev : null, up = (M()[c.primary] || [])[2] !== "down";
        return `<tr data-mcopen="${c.id}" tabindex="0"><td><b>${esc(c.label)}</b>${c.share ? ` <span class="faint small">${fmtNum(c.share * 100, 0)}% of emissions</span>` : ""}</td>
        <td title="${esc(c.line)}">${chip(STATE[c.state] || STATE.idle)}</td>
        <td class="r num">${c.score != null ? `${val(c.primary, c.score)}${dl ? ` <span class="${(dl > 0) === up ? "mcx-up" : "mcx-down"}">${dl > 0 ? "▲" : "▼"}</span>` : ""}` : "–"}</td>
        <td>${chip(EVAL[c.evaluator] || EVAL.none)}</td><td>${pips(c.experiments)}</td><td class="r num">${c.working ? `<b>${c.working}</b> at work · ` : ""}${c.active}/${c.agents}</td></tr>`; }).join("")}</tbody></table></div>`;
  }
  function pips(by) {
    const total = Object.values(by || {}).reduce((a, b) => a + b, 0);
    if (!total) return `<span class="faint small">none</span>`;
    return `<span class="mcx-pips" title="${esc(Object.entries(by).map(([k, n]) => `${n} at ${k}`).join(", "))}">${d.stages.map(([k]) => `<i class="${by[k] ? "on" : ""}">${by[k] || ""}</i>`).join("")}</span>`;
  }
  function check(c) {
    const [cls, ic] = LEVEL[c.level];
    const g = c.go || {};
    const btn = g.miner ? `data-mcminer="${g.miner}"` : g.exp ? `data-mcexp="${g.exp}"` : g.perf ? `data-mcw="${g.perf}" data-mct="perf"` : g.team ? `data-mcteam="${g.team}"` : g.campaign ? `data-mccamp="${g.campaign}"` : "";
    return `<li class="t-${cls}">${icon(ic)}<div><b>${esc(c.title)}</b><span class="faint small">${esc(c.detail || "")}</span></div>${btn ? `<button type="button" class="btn sm" ${btn}>Open</button>` : ""}</li>`;
  }

  // ---------- a competition's HQ ----------
  function compHQ() {
    if (!d.comps.length) return noTeams();
    const h = cache.comp;
    if (!h || h.id !== wid) return compPicker("comp") + Loading.line("Opening the competition…");
    const lt = h.latest, prim = lt[h.primary];
    const tile = (ic, title, inner, btns = "") => `<section class="mh-card mcx-tile"><h2 class="hq-h">${icon(ic)}${title}</h2>${inner}${btns ? `<div class="row mcx-tile-act">${btns}</div>` : ""}</section>`;
    const b = h.brief;
    return `${compPicker("comp")}
      <section class="mh-card mcx-comp-head"><div class="mw-kicker">${icon("folder")}SN${h.netuid} · ${esc(h.subnet)}${h.number != null ? ` · competition ${h.number}` : ""}</div>
        <h2>${esc(h.name || h.label)} ${chip(STATE[h.state] || STATE.idle)} ${chip(EVAL[h.evaluator] || EVAL.none)}${h.share ? ` <span class="hq-chip t-run">${icon("coins")}${fmtNum(h.share * 100, 0)}% of emissions</span>` : ""}</h2>
        <div class="mw-meta">${h.starts || h.ends ? `<span>${icon("calendar")}${esc(h.starts || "…")} – ${esc(h.ends || "…")}</span>` : ""}${h.link ? `<a href="${esc(h.link)}" target="_blank" rel="noopener noreferrer">${icon("external")}Competition page</a>` : ""}<span>${icon("users")}${h.active} of ${plural(h.agents, "agent")} on${h.lead ? `, led by ${esc(h.lead.name)}` : ""}</span></div>
        ${h.goal ? `<p class="mw-goal">${icon("target")}<span>${esc(h.goal)}</span></p>` : ""}</section>
      <div class="mcx-tiles">
        ${tile("dash", "Overview", `<p>${esc(h.line || "")}</p><div class="kv">${kv("Primary metric", mlabel(h.primary))}${kv("Latest", prim ? `${val(h.primary, prim.v)} · ${ago(prim.ts)}` : "not measured")}${kv("Waiting for you", h.waiting)}${kv("Agents at work", h.working)}</div>`,
          `<button type="button" class="btn sm" data-mcteam="${h.id}">${icon("users")}Open the team</button>`)}
        ${tile("search", "Intelligence", b ? `<p><b>${esc(b.headline)}</b></p>${b.summary ? `<p class="faint small">${esc(b.summary)}</p>` : ""}<div class="kv">${kv("Field", b.stats.of ? `${b.stats.of} miners` : "–")}${kv("Leader", b.stats.top1 != null ? `${fmtNum(b.stats.top1)} τ/day` : "–")}${kv("Earning", b.stats.earners ?? "–")}</div><p class="fine">Brief ${ago(b.ts)}</p>`
          : `<p class="faint small">No brief yet: My subnets' analysts write one after the first snapshots.</p>`, `<button type="button" class="btn sm" data-mccamp="${h.campaign}" data-mctab="competition">${icon("chart")}Competition tab</button>`)}
        ${tile("pickaxe", "Miner", h.miners.length ? `<ul class="mcx-mini">${h.miners.map(m => `<li><button type="button" class="linkbtn" data-mcminer="${m.id}">${esc(m.name || hk(m.hotkey))}</button> ${chip(HEALTH[m.health])} <span class="faint small">${m.onchain.rank ? `#${m.onchain.rank} on chain` : m.onchain.registered ? "" : "not on chain"}${m.version ? ` · ${esc(m.version)}` : ""}</span></li>`).join("")}</ul>`
          : `<p class="faint small">No miner on this campaign: add the hotkey to the campaign's settings, or add one in Miners.</p>`, `<button type="button" class="btn sm" data-mcgo="miners">${icon("pickaxe")}Miners</button>`)}
        ${tile("users", "Agent team", `<ul class="mcx-mini">${h.squads.map(s => `<li><b>${esc(s.squad || "Team")}</b> <span class="faint small">${s.on} of ${s.n} on</span></li>`).join("") || `<li class="faint small">No agents yet.</li>`}</ul><p class="fine">The competition manager plans; company governance still applies: production waits for you.</p>`,
          `<button type="button" class="btn sm" data-mcteam="${h.id}" data-mcsub="team">${icon("users")}Agents</button><button type="button" class="btn sm" data-mcgo="agents">${icon("search")}Directory</button>`)}
        ${tile("chart", "Performance", Object.keys(lt).length ? `<div class="kv">${Object.entries(lt).slice(0, 6).map(([k, x]) => kv(mlabel(k), val(k, x.v))).join("")}</div>` : `<p class="faint small">No measurements yet. Connect the evaluator (Settings → ingest key) or record one.</p>`,
          `<button type="button" class="btn sm" data-mcw="${h.id}" data-mct="perf">${icon("chart")}Performance Lab</button>`)}
        ${tile("bulb", "Experiments", h.exps.length ? `<ul class="mcx-mini">${h.exps.slice(0, 5).map(e => `<li><button type="button" class="linkbtn" data-mcexp="${e.id}">${esc(e.title)}</button> ${stageChip(e)}</li>`).join("")}</ul>` : `<p class="faint small">None yet.</p>`,
          `<button type="button" class="btn sm" data-mcnew="${h.id}">${icon("plus")}New experiment</button>`)}
        ${tile("folder", "Files", `<p>${plural(h.files, "file")} in the team's sandbox.</p>`, `<button type="button" class="btn sm" data-mcteam="${h.id}" data-mcsub="sandbox">${icon("terminal")}Files & sandbox</button>`)}
        ${tile("book", "Knowledge", `<p>${plural(h.notes, "notebook entry", "")}${h.notes === 1 ? "" : ""}, ${h.shared} shared with your other teams.</p><p class="fine">Private research and lessons stay with the competition unless they're shared on purpose.</p>`,
          `<button type="button" class="btn sm" data-mcteam="${h.id}" data-mcsub="notes">${icon("book")}Notebook</button>`)}
        ${tile("map", "Strategy", (b && b.priorities.length ? `<ol class="mcx-mini">${b.priorities.map(p => `<li>${esc(p)}</li>`).join("")}</ol>` : "") + (h.recs.length ? `<ul class="mcx-mini">${h.recs.map(r => `<li>${esc(r.title)} <span class="faint small">${esc(r.impact || "")}</span></li>`).join("")}</ul>` : "") || `<p class="faint small">No priorities or recommendations yet.</p>`,
          `<button type="button" class="btn sm" data-mcteam="${h.id}" data-mcsub="roadmap">${icon("map")}Roadmap</button><button type="button" class="btn sm" data-mccamp="${h.campaign}" data-mctab="overview">${icon("star")}Recommendations</button>`)}
      </div>`;
  }
  const kv = (k, v) => `<div><span>${esc(k)}</span><b>${typeof v === "number" ? fmtNum(v, 0) : v}</b></div>`;
  const stageChip = e => e.status !== "open" ? chip(["off", { kept: "Kept", rolled_back: "Rolled back", abandoned: "Abandoned" }[e.status] || e.status])
    : chip([e.stage === "approval" ? "warn" : e.stage === "monitoring" ? "ok" : "run", (d.stages.find(s => s[0] === e.stage) || [0, e.stage])[1]]);

  // ---------- the Performance Lab ----------
  function perf() {
    if (!d.comps.length) return noTeams();
    const p = cache.perf;
    if (!p || p.comp.id !== wid) return compPicker("perf") + Loading.line("Reading the measurements…");
    const keys = Object.keys(p.metrics).filter(k => p.series[k]?.length);
    const ev = p.evaluator;
    const prim = p.latest[p.primary];
    return `${compPicker("perf")}
      <div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("chart")}Performance Lab <span class="faint">${esc(p.comp.label)}</span></h2>
        <p class="faint small">Optimize the competition's own metric first (<b>${esc(mlabel(p.primary))}</b>); latency, errors and cost are the constraints next to it. Team id for the evaluator: <code>${p.comp.id}</code>.</p></div>
        <div class="row"><div class="seg" role="group" aria-label="Range">${[7, 30, 90].map(n => `<button type="button" data-mcdays="${n}" aria-pressed="${days === n}">${n} days</button>`).join("")}</div>
        <button type="button" class="btn sm" data-mc="measure">${icon("plus")}Record a measurement</button></div></div>
      <div class="mh-kpis mcx-kpis">
        ${kpi(prim ? "ok" : "", "target", mlabel(p.primary), prim ? val(p.primary, prim.v) : "–", prim ? `${prim.src} · ${ago(prim.ts)}` : "not measured", "")}
        ${kpi(p.onchain_now.best ? "run" : "", "trophy", "On-chain rank", p.onchain_now.best ? `#${p.onchain_now.best}` : "–", `${plural(p.onchain_now.miners, "miner")} · ${fmtNum(p.onchain_now.em)} τ/day`, "")}
        ${["latency_p95", "error_rate", "cost_task", "uptime"].map(k => kpi("", { latency_p95: "clock", error_rate: "alert", cost_task: "coins", uptime: "radio" }[k], mlabel(k), val(k, p.latest[k]?.v), p.latest[k] ? `${p.latest[k].src} · ${ago(p.latest[k].ts)}` : "not measured", "")).join("")}
      </div>
      ${ev.state === "none" ? `<section class="mh-card mcx-connect"><h3>${icon("link")}Connect the competition's evaluator</h3>
        <p>Scores here come only from measurements: the evaluator (or your miner) posts them with an ingest key. Nothing is filled in until it does.</p>
        <ol><li>Make a key in <button type="button" class="linkbtn" data-mcgo="settings">Settings</button>.</li><li>Post each evaluation:</li></ol>
        <pre class="mcx-pre">curl -X POST ${esc(location.origin)}${C}/ingest \\
  -H "Authorization: Bearer mcx_…" -H "X-Requested-With: scout" -H "Content-Type: application/json" \\
  -d '{"competition": ${p.comp.id}, "run": "eval-2026-11-02", "metrics": {"score": 0.71, "latency_p95": 880, "error_rate": 0.02}}'</pre>
        <p class="fine">Metrics: ${Object.entries(p.metrics).map(([k, m]) => `<code>${k}</code> (${esc(m[0])}${m[1] === "%" ? ", 0–1" : m[1] ? `, ${esc(m[1])}` : ""})`).join(", ")}. Add <code>"miner": "&lt;hotkey&gt;"</code> for per-miner numbers and <code>"health": {…}</code> for its health.</p></section>` : ""}
      <div class="mcx-charts">${keys.map(k => `<section class="mh-card mcx-chart"><h2 class="hq-h">${esc(mlabel(k))}${k === p.primary ? ` ${chip(["run", "primary"])}` : ""}<span class="faint">${p.series[k].length} points · latest ${val(k, p.series[k].at(-1).v)}</span></h2>
          <div class="mcx-svg" data-mcchart="${k}"></div></section>`).join("")}
        ${p.onchain.length ? `<section class="mh-card mcx-chart"><h2 class="hq-h">On-chain rank<span class="faint">best of your miners, from My subnets' snapshots</span></h2><div class="mcx-svg" data-mcchart="__rank"></div></section>` : ""}
        ${!keys.length && !p.onchain.length ? `<p class="faint small">Nothing measured in the last ${days} days.</p>` : ""}</div>
      ${p.lab.length ? panel("The Lab's scored runs", "chart", `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>When</th><th>Run</th><th class="r">Solved</th><th class="r">Success</th><th class="r">P50</th><th class="r">P95</th><th class="r">P99</th><th class="r">$ / solved</th></tr></thead><tbody>
        ${p.lab.slice().reverse().map(r => `<tr><td>${when(r.ts)}</td><td>${chip([r.kind === "base" ? "run" : "none", r.kind])} ${esc(r.label || "")}</td><td class="r num">${r.solved}/${r.tasks}</td><td class="r num">${val("success_rate", r.metrics.success_rate)}</td>
          <td class="r num">${val("latency_p50", r.metrics.latency_p50)}</td><td class="r num">${val("latency_p95", r.metrics.latency_p95)}</td><td class="r num">${val("latency_p99", r.metrics.latency_p99)}</td><td class="r num">${val("cost_task", r.metrics.cost_task)}</td></tr>`).join("")}</tbody></table></div>`,
        `<span class="faint">latency across tasks, from the Workflow's checks</span>`) : ""}
      ${p.comparison ? panel("Baseline against candidate", "columns", compareTable(p.comparison), `<button type="button" class="linkbtn" data-mcexp="${p.comparison.id}">${esc(p.comparison.title)}</button>`) : ""}
      ${measuredList(p)}`;
  }
  function measuredList(p) {
    const rows = Object.entries(p.series).flatMap(([k, s]) => s.map(x => ({ ...x, k }))).sort((a, b) => b.ts - a.ts).slice(0, 40);
    if (!rows.length) return "";
    return `<details class="mh-card mcx-raw"><summary>${icon("list")}Every measurement <span class="faint">(${rows.length} latest)</span></summary><div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>When</th><th>Metric</th><th class="r">Value</th><th>Source</th><th>Run</th><th></th></tr></thead><tbody>
      ${rows.map(r => `<tr><td>${when(r.ts)}</td><td>${esc(mlabel(r.k))}</td><td class="r num">${val(r.k, r.v)}</td><td>${esc(r.src)}</td><td>${esc(r.run || "")}${r.note ? ` <span class="faint small">${esc(r.note)}</span>` : ""}</td>
        <td>${r.src === "manual" ? `<button type="button" class="iconbtn" data-mcdelm="${r.id}" aria-label="Delete">${icon("trash")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></details>`;
  }
  // a line per series, drawn to the box's width; ranks and "lower is better" metrics keep up = good
  function drawCharts() {
    const p = cache.perf; if (!p) return;
    $$("[data-mcchart]", el).forEach(box => {
      const k = box.dataset.mcchart;
      const pts = k === "__rank" ? p.onchain.map(x => ({ ts: x.ts, v: x.rank })) : p.series[k] || [];
      const down = k === "__rank" || (p.metrics[k] || [])[2] === "down";
      box.innerHTML = line(pts, box.clientWidth || 320, 120, down, k === "__rank" ? v => `#${fmtNum(v, 0)}` : v => val(k, v));
    });
  }
  function line(pts, w, h, invert, fmt) {
    if (!pts.length) return "";
    const pad = { l: 6, r: 6, t: 10, b: 18 }, xs = pts.map(p => p.ts), ys = pts.map(p => p.v);
    let lo = Math.min(...ys), hi = Math.max(...ys); if (lo === hi) { lo -= Math.abs(lo) * 0.05 || 1; hi += Math.abs(hi) * 0.05 || 1; }
    const x0 = Math.min(...xs), x1 = Math.max(...xs) === x0 ? x0 + 1 : Math.max(...xs);
    const X = t => pad.l + (t - x0) / (x1 - x0) * (w - pad.l - pad.r), Y = v => { const f = (v - lo) / (hi - lo); return pad.t + (invert ? f : 1 - f) * (h - pad.t - pad.b); };
    const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p.ts).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
    const dots = pts.length <= 60 ? pts.map(p => `<circle cx="${X(p.ts).toFixed(1)}" cy="${Y(p.v).toFixed(1)}" r="2.6"><title>${esc(fmt(p.v))} · ${esc(when(p.ts))}${p.src ? ` · ${esc(p.src)}` : ""}</title></circle>`).join("") : "";
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img" aria-label="${pts.length} points from ${esc(fmt(Math.min(...ys)))} to ${esc(fmt(Math.max(...ys)))}">
      <line x1="${pad.l}" x2="${w - pad.r}" y1="${h - pad.b}" y2="${h - pad.b}" class="ax"/><path d="${path}" class="ln"/>${dots}
      <text x="${pad.l}" y="${h - 4}" class="tk">${esc(when(x0))}</text><text x="${w - pad.r}" y="${h - 4}" class="tk" text-anchor="end">${esc(when(x1))}</text>
      <text x="${w - pad.r}" y="${pad.t + 2}" class="tk" text-anchor="end">${esc(fmt(invert ? lo : hi))}</text></svg>`;
  }
  function compareTable(x) {
    const rows = Object.entries(x.compare);
    if (!rows.length) return `<p class="faint small">Nothing measured on both sides yet: add baseline and candidate runs (${x.min_runs} a side).</p>`;
    const ms = s => s ? `${val0(s.mean)}${s.sd != null ? ` <span class="faint">± ${val0(s.sd)}</span>` : ""} <span class="faint">n ${s.n}</span>` : "–";
    let val0 = v => fmtNum(v, 3);
    return `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Metric</th><th class="r">Baseline</th><th class="r">Candidate</th><th class="r">Difference</th><th class="r">Noise band</th><th>Reading</th></tr></thead><tbody>
      ${rows.map(([k, c]) => { val0 = v => val(k, v); return `<tr class="${c.primary ? "mcx-prim" : ""}"><td>${esc(mlabel(k))}${c.primary ? ` ${chip(["run", "primary"])}` : ""}</td><td class="r num">${ms(c.base)}</td><td class="r num">${ms(c.cand)}</td>
        <td class="r num">${c.diff > 0 ? "+" : ""}${val(k, c.diff)}${c.rel != null ? ` <span class="faint">(${c.rel > 0 ? "+" : ""}${fmtNum(c.rel * 100, 1)}%)</span>` : ""}</td><td class="r num">${c.band != null ? `± ${val(k, c.band)}` : "–"}</td>
        <td>${chip(VERDICT[c.verdict])}${c.enough ? "" : ` <span class="faint small">needs ${x.min_runs} a side</span>`}</td></tr>`; }).join("")}</tbody></table></div>`;
  }

  // ---------- the Experiment Center ----------
  function experiments() {
    const x = cache.exp;
    if (!x) return Loading.line("Reading the experiments…");
    const open = x.experiments.filter(e => e.status === "open"), closed = x.experiments.filter(e => e.status !== "open");
    return `<div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("bulb")}Experiment Center</h2>
        <p class="faint small">Idea → proposal → isolated trial → evaluation against a reproducible baseline → an independent review → your approval → you deploy → monitoring. One benchmark run never recommends anything.</p></div>
        <div class="row">${d.comps.length ? `<button type="button" class="btn primary sm" data-mcnew="${wid || d.comps[0].id}">${icon("plus")}New experiment</button>` : ""}</div></div>
      ${!d.comps.length ? noTeams() : ""}
      <div class="mcx-board">${x.stages.map(([k, l], i) => { const list = open.filter(e => e.stage === k);
        return `<section class="mcx-col"><h4><span class="mcx-n">${i + 1}</span>${l}<span class="faint">${list.length || ""}</span></h4>
          ${list.map(e => `<button type="button" class="mcx-card" data-mcexp="${e.id}"><b>${esc(e.title)}</b><span class="faint small">${esc(e.comp)}</span>
            <span class="mcx-card-meta">${e.runs.base || e.runs.cand ? `${e.runs.base}/${e.runs.cand} runs` : ""}${e.review ? ` ${chip(REC[e.review.verdict])}` : ""}${e.approval ? ` ${chip(APPR[e.approval.status] || APPR.pending)}` : ""}</span></button>`).join("") || `<p class="faint small mcx-none">–</p>`}</section>`; }).join("")}</div>
      ${closed.length ? panel("Closed", "check", `<ul class="mcx-mini">${closed.map(e => `<li><button type="button" class="linkbtn" data-mcexp="${e.id}">${esc(e.title)}</button> ${stageChip(e)} <span class="faint small">${esc(e.comp)} · ${ago(e.updated)}${e.outcome_reason ? ` · ${esc(e.outcome_reason)}` : ""}</span></li>`).join("")}</ul>`) : ""}`;
  }
  function dlg(id, cls = "") {
    let g = document.getElementById(id);
    if (!g) {
      g = document.createElement("dialog"); g.id = id; document.body.append(g);
      g.addEventListener("click", dlgClick); g.addEventListener("submit", dlgSubmit);
      g.addEventListener("close", () => { if (id === "mcx-exp") { eid = ex = null; load(true); } if (id === "mcx-miner") { mid = mn = null; } });
    }
    g.className = `modal mw-dlg wide mcx-dlg ${cls}`;
    return g;
  }
  const X = `<button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>`;
  async function openExp(id) {
    eid = id; const g = dlg("mcx-exp");
    if (!g.open) { g.innerHTML = `<div class="hq-dlg-in">${X}${Loading.line("Opening the experiment…")}</div>`; g.showModal(); }
    try { if (!d) d = await api(C); ex = await api(`${C}/experiments/${id}`); drawExp(); } catch (e) { err(e); g.close(); return; }  // d: the stages, when opened from outside (mining-ops.js)
    if (["sandbox", "evaluation", "recommendation"].includes(ex.stage)) reports();  // the evaluator's run labels for the add-run form
  }
  function drawExp() {
    const g = document.getElementById("mcx-exp"); if (!g || !ex) return;
    const e = ex, at = d.stages.findIndex(s => s[0] === e.stage), closed = e.status !== "open";
    const field = (name, label, v, rows = 3, ph = "") => `<label class="in"><span>${label}</span><textarea name="${name}" rows="${rows}" maxlength="3000" placeholder="${esc(ph)}">${esc(v || "")}</textarea></label>`;
    const step = (to, label, ic = "right") => `<button type="button" class="btn sm" data-mcstep="${to}">${icon(ic)}${label}</button>`;
    const S = {};
    S.idea = `<form class="mcx-form" data-mcpatch>${`<label class="in"><span>Title</span><input name="title" maxlength="160" value="${esc(e.title)}" required></label>`}${field("idea", "The idea: the opportunity and why it should help", e.idea, 3)}
      <div class="row"><button type="submit" class="btn sm">${icon("check")}Save</button>${e.stage === "idea" ? step("proposal", "Write the proposal") : ""}</div></form>`;
    S.proposal = `<form class="mcx-form" data-mcpatch>${field("benefit", "Expected benefit (on the competition's metric)", e.benefit, 2, "e.g. +3 to 5 points of score on the SQL tasks")}${field("risks", "Risks", e.risks, 2, "What could go wrong, and how you'd notice")}
      <label class="in"><span>Cost <small class="faint">tokens, compute, time</small></span><input name="cost" maxlength="600" value="${esc(e.cost || "")}"></label>
      <div class="row"><button type="submit" class="btn sm">${icon("check")}Save</button>${e.stage === "proposal" ? step("sandbox", "Try it in isolation") : ""}</div></form>`;
    S.sandbox = `<ul class="mcx-mini">${e.sandbox.map(r => `<li>${chip(["none", r.kind])} #${r.id} ${esc(r.what || "")} <span class="faint small">${esc(r.status || "")}${r.solved != null ? ` · ${r.solved}/${r.tasks} solved` : ""}</span></li>`).join("") || `<li class="faint small">No isolated run linked yet.</li>`}</ul>
      <form class="mcx-form row" data-mclink><select name="ref" aria-label="Run to link"><option value="">Link a run…</option>
        ${e.sandboxes.map(s => `<option value="sandbox:${s.id}">Sandbox #${s.id} · ${esc((s.command || "").slice(0, 60))} · ${esc(s.status)}</option>`).join("")}
        ${e.labs.map(l => `<option value="lab:${l.id}">Lab #${l.id} · ${esc((l.label || "").slice(0, 60))} · ${l.solved}/${l.tasks}</option>`).join("")}</select>
        <button type="submit" class="btn sm">${icon("link")}Link</button></form>
      <form class="mcx-form" data-mcpatch>${field("sandbox_note", "Or note where it was tried in isolation", e.sandbox_note, 2)}<div class="row"><button type="submit" class="btn sm">${icon("check")}Save</button>${e.stage === "sandbox" ? step("evaluation", "Evaluate it") : ""}</div></form>`;
    const runsTable = side => { const list = e[side]; return `<div class="mcx-runs"><h4>${side === "base" ? "Baseline" : "Candidate"} <span class="faint">${list.length} run${list.length === 1 ? "" : "s"}</span></h4>
      ${list.length ? `<ul>${list.map((r, i) => `<li><span>${esc(r.label || `run ${i + 1}`)}</span><span class="faint small">${Object.keys(d.metrics).filter(k => r[k] != null).map(k => `${esc(mlabel(k))} ${val(k, r[k])}`).join(" · ")}</span>
        ${editable ? `<button type="button" class="iconbtn" data-mcdelrun="${side}:${i}" aria-label="Remove">${icon("trash")}</button>` : ""}</li>`).join("")}</ul>` : `<p class="faint small">None yet.</p>`}</div>`; };
    const editable = !closed && ["evaluation", "recommendation"].includes(e.stage) && !(e.approval && ["pending", "approved", "consumed"].includes(e.approval.status));
    S.evaluation = `<form class="mcx-form mcx-art" data-mcpatch><label class="in"><span>Primary metric</span><select name="primary">${Object.entries(d.metrics).map(([k, m]) => `<option value="${k}" ${k === e.primary ? "selected" : ""}>${esc(m[0])}</option>`).join("")}</select></label>
        <label class="in"><span>Artifact</span><select name="akind">${["commit", "version", "image"].map(k => `<option ${e.artifact.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></label>
        <label class="in"><span>Reference</span><input name="aref" maxlength="300" placeholder="a1b2c3d or v1.5.0" value="${esc(e.artifact.ref || "")}"></label>
        <label class="in"><span>Repository</span><input name="arepo" maxlength="300" placeholder="owner/miner" value="${esc(e.artifact.repo || "")}"></label>
        <label class="in"><span>Miner</span><select name="miner"><option value="">none</option>${e.miners.map(m => `<option value="${m.id}" ${m.id === e.miner_id ? "selected" : ""}>${esc(m.name || hk(m.hotkey))}</option>`).join("")}</select></label>
        <div class="row"><button type="submit" class="btn sm" ${editable || e.stage === "sandbox" ? "" : "disabled"}>${icon("check")}Save</button></div></form>
      <div class="mcx-sides">${runsTable("base")}${runsTable("cand")}</div>
      ${editable ? `<form class="mcx-form mcx-addrun" data-mcrun><div class="row"><select name="side" aria-label="Side"><option value="base">Baseline run</option><option value="cand">Candidate run</option></select>
          <input name="label" maxlength="80" placeholder="label (optional)" aria-label="Label"></div>
        <div class="mcx-mgrid">${Object.entries(d.metrics).map(([k, m]) => `<label class="in"><span>${esc(m[0])}${m[1] ? ` <small class="faint">${m[1] === "%" ? "0–1" : esc(m[1])}</small>` : ""}</span><input name="m_${k}" type="number" step="any" inputmode="decimal"></label>`).join("")}</div>
        <div class="row"><button type="submit" class="btn sm">${icon("plus")}Add the run</button>
          <select name="report" aria-label="From the evaluator's reports"><option value="">…or an evaluator run</option>${(e.reports || []).map(r => `<option value="${esc(r.run)}">${esc(r.run)} · ${r.n} metrics · ${esc(when(r.ts))}</option>`).join("")}</select>
          <select name="lab" aria-label="From the Lab"><option value="">…or a Lab run</option>${e.labs.map(l => `<option value="${l.id}">Lab #${l.id} · ${esc((l.label || "").slice(0, 50))} · ${l.solved}/${l.tasks}</option>`).join("")}</select></div></form>` : ""}
      ${compareTable(e)}
      <p class="mcx-rule">${chip(REC[e.rule.verdict])} <span class="small">${e.rule.reasons.map(esc).join(" ")}</span></p>
      ${editable || e.stage === "evaluation" ? `<div class="row"><button type="button" class="btn primary sm" data-mc="review" ${closed ? "disabled" : ""}>${icon("eye")}Ask the Evidence Reviewer</button></div>` : ""}`;
    const rv = e.review;
    S.recommendation = rv ? `<div class="mcx-review">${chip(REC[rv.verdict])} <span class="faint small">${esc(rv.by)}, independent of ${esc((rv.independent_of || "").replace("user:", ""))} · ${ago(rv.ts)}${e.review_current ? "" : ` · ${chip(["warn", "evidence changed since"])}`}</span>
        <h4>Rule checks</h4><ul>${rv.rule.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
        ${rv.model?.summary ? `<h4>Reading of the evidence <span class="faint small">${esc(rv.model.model || "")}</span></h4><p>${esc(rv.model.summary)}</p>${rv.model.concerns?.length ? `<p class="faint small"><b>Concerns:</b> ${rv.model.concerns.map(esc).join(" · ")}</p>` : ""}${rv.model.checks?.length ? `<p class="faint small"><b>Checked:</b> ${rv.model.checks.map(esc).join(" · ")}</p>` : ""}`
          : rv.model?.error ? `<p class="faint small">The model review failed (${esc(rv.model.error)}): the rule checks stand.</p>` : `<p class="faint small">No model connected: the rule checks stand.</p>`}
        ${e.stage === "recommendation" && !closed ? `<form class="mcx-form row" data-mcapprove>${rv.verdict === "recommend" && e.review_current ? `<input name="note" maxlength="600" placeholder="A note for the approval (optional)" aria-label="Note"><button type="submit" class="btn primary sm">${icon("hand")}Ask for approval</button>` : `<span class="faint small">Not recommended as it stands: add runs or change the candidate, then ask again.</span>`}</form>` : ""}</div>`
      : `<p class="faint small">The Evidence Reviewer hasn't read it yet.</p>`;
    const a = e.approval;
    S.approval = a ? `<div class="mcx-review">${chip(APPR[a.status] || APPR.pending)} <span class="faint small">Company approval #${a.id} · bound to <code>${esc(a.hash.slice(0, 12))}</code>${a.expires_at && ["pending", "approved"].includes(a.status) ? ` · expires ${esc(when(a.expires_at))}` : ""}${a.decided_by ? ` · ${esc(a.decided_by)} ${ago(a.decided_at)}` : ""}</span>
        ${a.reason ? `<p>${esc(a.reason)}</p>` : ""}
        ${e.stage === "approval" && a.status === "pending" && !closed ? `<form class="mcx-form" data-mcdecide><input name="reason" maxlength="1000" placeholder="Why (needed to reject or ask for changes)" aria-label="Reason">
          <div class="row"><button type="submit" class="btn primary sm" data-dec="approve">${icon("check")}Approve</button><button type="submit" class="btn sm" data-dec="changes">${icon("edit")}Ask for changes</button><button type="submit" class="btn sm mw-danger" data-dec="reject">${icon("ban")}Reject</button></div></form>` : ""}
        ${e.stage === "approval" && a.status === "approved" && !closed ? `<p class="small">Approved. Authorizing consumes the approval once and hands the deploy to you: AXoR never deploys.</p><div class="row"><button type="button" class="btn primary sm" data-mc="authorize">${icon("shield")}Authorize and hand off</button></div>` : ""}
        ${e.stage === "approval" && a.status === "consumed" && !closed ? `<p class="small">Authorized on the Company page and handed off.</p><div class="row"><button type="button" class="btn primary sm" data-mc="authorize">${icon("rocket")}Move to production</button></div>` : ""}
        ${e.stage === "approval" && ["rejected", "changes", "expired"].includes(a.status) && !closed ? `<div class="row"><button type="button" class="btn sm" data-mc="revise">${icon("undo")}Revise the evidence</button></div>` : ""}
        ${e.stage === "approval" && ["pending", "approved"].includes(a.status) && !closed ? `<p class="fine"><button type="button" class="linkbtn" data-mc="revise">Withdraw and revise</button></p>` : ""}</div>`
      : `<p class="faint small">Not asked for yet.</p>`;
    S.production = e.stage === "production" ? `<div class="mcx-review"><p>Deploy exactly <b>${esc(e.artifact.kind || "artifact")} ${esc(e.artifact.ref || "")}</b>${e.artifact.repo ? ` from ${esc(e.artifact.repo)}` : ""}, then record it here. Monitoring starts when you do.</p>
        <form class="mcx-form row" data-mcdeploy><input name="version" maxlength="120" required placeholder="version deployed (e.g. v1.5.0)" aria-label="Version"><select name="miner" aria-label="Miner"><option value="">miner…</option>${e.miners.map(m => `<option value="${m.id}" ${m.id === e.miner_id ? "selected" : ""}>${esc(m.name || hk(m.hotkey))}</option>`).join("")}</select>
          <input name="note" maxlength="600" placeholder="note" aria-label="Note"><button type="submit" class="btn primary sm">${icon("rocket")}Record the deploy</button></form></div>`
      : e.deploy ? `<p class="small">Deployed <b>${esc(e.deploy.version)}</b> by ${esc(e.deploy.by_user)} ${ago(e.deploy.ts)} ${chip(["none", e.deploy.status])}</p>` : `<p class="faint small">Not deployed.</p>`;
    const mon = e.monitor;
    S.monitoring = mon ? `<div class="mcx-review">${chip(MON[mon.verdict])} <span class="faint small">since ${esc(when(mon.since))}</span>
        ${Object.keys(mon.metrics).length ? `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Metric</th><th class="r">Since the deploy</th><th class="r">vs baseline</th><th class="r">vs candidate</th></tr></thead><tbody>
          ${Object.entries(mon.metrics).map(([k, m]) => `<tr class="${m.worse ? "mcx-bad" : ""}"><td>${esc(mlabel(k))}</td><td class="r num">${val(k, m.live.mean)} <span class="faint">n ${m.live.n}</span></td><td class="r num">${m.vs_base != null ? `${m.vs_base > 0 ? "+" : ""}${val(k, m.vs_base)}` : "–"}</td><td class="r num">${m.vs_cand != null ? `${m.vs_cand > 0 ? "+" : ""}${val(k, m.vs_cand)}` : "–"}</td></tr>`).join("")}</tbody></table></div>`
          : `<p class="faint small">No evaluator report since the deploy yet.</p>`}
        ${!closed ? `<form class="mcx-form row" data-mcclose><input name="reason" maxlength="600" placeholder="Why" aria-label="Reason"><button type="submit" class="btn sm" data-out="kept">${icon("check")}Keep it</button><button type="submit" class="btn sm mw-danger" data-out="rolled_back">${icon("undo")}Roll back</button></form>
          <p class="fine">A rollback is recorded here and the previous version becomes the active one; carry it out on the miner.</p>` : ""}</div>` : `<p class="faint small">Starts with the deploy.</p>`;
    const open = new Set([e.stage]);
    g.innerHTML = `<div class="hq-dlg-in mcx-exp">${X}
      <div class="mw-kicker">${icon("bulb")}${esc(e.comp)} · experiment #${e.id}${e.source ? ` · from ${esc(e.source)}` : ""}</div>
      <h3>${esc(e.title)} ${stageChip({ ...e })}</h3>
      <ol class="mcx-steps">${d.stages.map(([k, l], i) => `<li class="${i < at || (closed && i <= at) ? "done" : i === at && !closed ? "now" : ""}">${i < at ? icon("check") : `<i>${i + 1}</i>`}<span>${l}</span></li>`).join("")}</ol>
      ${d.stages.map(([k, l], i) => `<details class="mcx-stage" ${open.has(k) ? "open" : ""} ${i > at ? "data-later" : ""}><summary><b>${i + 1}. ${l}</b>${i < at ? ` <span class="faint small">${icon("check")}done</span>` : ""}</summary>${i <= at || k === "proposal" && at === 0 ? S[k] : `<p class="faint small">Comes after ${esc(d.stages[i - 1][1].toLowerCase())}.</p>`}</details>`).join("")}
      <details class="mcx-stage"><summary><b>Log</b> <span class="faint small">${e.log.length}</span></summary><ol class="mcx-log">${e.log.map(l => `<li><span class="faint small">${esc(when(l.ts))} · ${esc(l.who)}</span> ${esc(l.text)}</li>`).join("")}</ol></details>
      ${!closed ? `<div class="row end"><button type="button" class="btn sm" data-mc="abandon">${icon("ban")}Abandon</button>${e.deploy_id ? "" : `<button type="button" class="iconbtn" data-mc="delexp" aria-label="Delete the experiment" title="Delete">${icon("trash")}</button>`}</div>` : ""}</div>`;
  }
  async function expCall(btn, path, body, method = "POST") {
    const r = await busy(btn, () => api(`${C}/experiments/${eid}${path}`, { method, body }));
    if (r) { ex = { ...r, reports: ex?.reports }; drawExp(); }
    return r;
  }
  async function reports() {
    if (!ex) return;
    try { ex.reports = (await api(`${C}/comps/${ex.comp_id}/reports`)).runs; drawExp(); } catch (e) { err(e); }
  }
  function newExp(w) {
    const g = dlg("mcx-new", "mcx-small");
    g.innerHTML = `<form class="hq-dlg-in mcx-form" data-mcnewexp>${X}<h3>${icon("bulb")} New experiment</h3>
      <label class="in"><span>Competition team</span><select name="comp">${d.comps.map(c => `<option value="${c.id}" ${c.id === w ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></label>
      <label class="in"><span>Title</span><input name="title" maxlength="160" minlength="3" required placeholder="Cache schema lookups"></label>
      <label class="in"><span>The idea</span><textarea name="idea" rows="3" maxlength="3000" placeholder="The opportunity an agent or you spotted, and why it should help"></textarea></label>
      <label class="in"><span>Where it came from <small class="faint">optional: a task, a recommendation, a note</small></span><input name="source" maxlength="200"></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("plus")}Create</button></div></form>`;
    g.showModal();
  }

  // ---------- miners ----------
  function miners() {
    const x = cache.miners;
    if (!x) return Loading.line("Reading your miners…");
    return `<div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("pickaxe")}Miners</h2><p class="faint small">On-chain state comes from My subnets' snapshots; health, versions and logs come from what the miner reports with an ingest key. Hotkeys are public; secrets never come here.</p></div>
      <div class="row">${d.campaigns.length ? `<button type="button" class="btn sm" data-mc="addminer">${icon("plus")}Add a miner</button>` : ""}</div></div>
      ${x.miners.length ? `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Miner</th><th>Subnet</th><th>Health</th><th>Version</th><th class="r">Up 24 h</th><th class="r">UID</th><th class="r">Rank</th><th class="r">τ / day</th><th>Last report</th></tr></thead><tbody>
        ${x.miners.map(m => `<tr data-mcminer="${m.id}" tabindex="0"><td><b>${esc(m.name || "miner")}</b> <code class="faint">${hk(m.hotkey)}</code></td><td>SN${m.netuid}</td><td>${chip(HEALTH[m.health])}</td><td>${esc(m.version || "–")}</td>
          <td class="r num">${m.uptime_24h != null ? `${fmtNum(m.uptime_24h * 100, 1)}%` : "–"}</td><td class="r num">${m.onchain.uid ?? "–"}</td><td class="r num">${m.onchain.rank ? `#${m.onchain.rank}` : m.onchain.registered ? "–" : `<span class="faint">off chain</span>`}</td>
          <td class="r num">${m.onchain.em != null ? fmtNum(m.onchain.em) : "–"}</td><td>${m.last_seen ? ago(m.last_seen) : `<span class="faint">never</span>`}</td></tr>`).join("")}</tbody></table></div>`
        : `<section class="mh-card mcx-empty"><p>No miner yet. Add your miner's hotkey to a campaign (its Settings), or add one here.</p></section>`}`;
  }
  async function openMiner(id) {
    mid = id; const g = dlg("mcx-miner");
    if (!g.open) { g.innerHTML = `<div class="hq-dlg-in">${X}${Loading.line("Opening the miner…")}</div>`; g.showModal(); }
    try { mn = await api(`${C}/miners/${id}`); drawMiner(); } catch (e) { err(e); g.close(); }
  }
  function drawMiner() {
    const g = document.getElementById("mcx-miner"); if (!g || !mn) return;
    const m = mn, o = m.onchain, hist = m.history.map(p => ({ ts: p.ts, v: p.rank }));
    g.innerHTML = `<div class="hq-dlg-in mcx-exp">${X}<div class="mw-kicker">${icon("pickaxe")}SN${m.netuid} · ${esc(m.subnet)}${m.manual ? " · added by hand" : ""}</div>
      <h3>${esc(m.name || "Miner")} ${chip(HEALTH[m.health])}</h3>
      <p class="small"><code>${esc(m.hotkey)}</code> <button type="button" class="linkbtn" data-copy="${esc(m.hotkey)}">copy</button>${o.coldkey ? ` <span class="faint">coldkey ${hk(o.coldkey)}</span>` : ""}</p>
      <div class="mcx-sides">
        <section class="mh-card"><h4>${icon("globe")}On chain <span class="faint small">${m.snapshot ? `snapshot ${ago(m.snapshot.ts)}` : "no snapshot"}</span></h4>
          ${o.registered ? `<div class="kv">${kv("UID", o.uid)}${kv("Rank", o.rank ? `#${o.rank}` : "–")}${kv("τ / day", fmtNum(o.em))}${kv("Incentive", fmtNum(o.inc, 4))}${kv("Trust", fmtNum(o.trust, 3))}${kv("Consensus", fmtNum(o.consensus, 3))}</div>
            ${hist.length > 1 ? `<div class="mcx-svg">${line(hist, 360, 90, true, v => `#${fmtNum(v, 0)}`)}</div>` : ""}` : `<p class="faint small">Not in the latest snapshot under the campaign's keys.</p>`}</section>
        <section class="mh-card"><h4>${icon("radio")}Off chain <span class="faint small">what it and the evaluator report</span></h4>
          <div class="kv">${kv("Version", esc(m.version || "–"))}${kv("Up 24 h", m.uptime_24h != null ? `${fmtNum(m.uptime_24h * 100, 1)}%` : "–")}${kv("CPU", m.cpu != null ? `${fmtNum(m.cpu * 100, 0)}%` : "–")}${kv("Memory", m.mem != null ? `${fmtNum(m.mem * 100, 0)}%` : "–")}${kv("GPU", m.gpu != null ? `${fmtNum(m.gpu * 100, 0)}%` : "–")}${kv("Errors", m.errors ?? "–")}</div>
          <p class="fine">Last report ${m.last_seen ? ago(m.last_seen) : "never"}${m.evaluator ? ` · ${EVAL[m.evaluator.state][1].toLowerCase()}` : ""}.</p></section></div>
      <form class="mcx-form mcx-mgrid2" data-mcminerform>
        <label class="in"><span>Name</span><input name="name" maxlength="80" value="${esc(m.name)}"></label>
        <label class="in"><span>Competition team</span><select name="comp"><option value="">none</option>${m.comps.map(c => `<option value="${c.id}" ${c.id === m.comp ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></label>
        <label class="in"><span>Version</span><input name="version" maxlength="120" value="${esc(m.version)}"></label>
        <label class="in"><span>Hardware</span><input name="hardware" maxlength="600" value="${esc(m.hardware)}" placeholder="1× A100 80 GB, 32 vCPU"></label>
        <label class="in mcx-wide"><span>Configuration <small class="faint">no secrets: keys, seeds and passwords stay on the miner</small></span><textarea name="config" rows="3" maxlength="4000">${esc(m.config)}</textarea></label>
        <label class="in mcx-wide"><span>Notes</span><textarea name="notes" rows="2" maxlength="2000">${esc(m.notes)}</textarea></label>
        <div class="row mcx-wide"><button type="submit" class="btn sm">${icon("check")}Save</button>${m.manual ? `<button type="button" class="btn sm mw-danger" data-mc="delminer">${icon("trash")}Remove</button>` : ""}</div></form>
      <details class="mcx-stage" ${m.deploys.length ? "open" : ""}><summary><b>Deployments and rollbacks</b> <span class="faint small">${m.deploys.length}</span></summary>
        ${m.deploys.length ? `<ol class="mcx-log">${m.deploys.map(x => `<li>${chip([x.status === "active" ? "ok" : x.status === "rolled_back" ? "bad" : "none", x.status])} <b>${esc(x.version)}</b>${x.ref ? ` <code>${esc(x.ref)}</code>` : ""} <span class="faint small">${esc(when(x.ts))} · ${esc(x.by_user || "")}${x.exp_id ? ` · <button type="button" class="linkbtn" data-mcexp="${x.exp_id}">experiment #${x.exp_id}</button>` : ""}${x.rollback_of ? " · rollback" : ""}${x.note ? ` · ${esc(x.note)}` : ""}</span></li>`).join("")}</ol>` : `<p class="faint small">Nothing recorded: deploys come through an experiment's approval.</p>`}</details>
      <details class="mcx-stage"><summary><b>Logs</b> <span class="faint small">${m.logs.length} reports</span></summary>${m.logs.length ? m.logs.map(l => `<div class="mcx-logbox"><span class="faint small">${esc(when(l.ts))}</span><pre class="mcx-pre">${esc(l.lines.join("\n"))}</pre></div>`).join("") : `<p class="faint small">The miner hasn't sent log lines. Add <code>"health": {"log": […]}</code> to its reports.</p>`}</details>
      <details class="mcx-stage"><summary><b>Metrics for this miner</b> <span class="faint small">${m.metrics.length}</span></summary>${m.metrics.length ? `<ul class="mcx-mini">${m.metrics.slice(0, 30).map(x => `<li>${esc(mlabel(x.metric))} <b>${val(x.metric, x.value)}</b> <span class="faint small">${esc(x.source)} · ${esc(when(x.ts))}</span></li>`).join("")}</ul>` : `<p class="faint small">None reported with this miner's hotkey.</p>`}</details></div>`;
  }
  function addMiner() {
    const g = dlg("mcx-new", "mcx-small");
    g.innerHTML = `<form class="hq-dlg-in mcx-form" data-mcaddminer>${X}<h3>${icon("pickaxe")} Add a miner</h3><p class="faint small">Miners under a campaign's keys appear by themselves; add one here that isn't registered yet, or runs under another key.</p>
      <label class="in"><span>Campaign</span><select name="campaign">${d.campaigns.map(c => `<option value="${c.id}">SN${c.netuid} · ${esc(c.subnet)} · ${esc(c.comp)}</option>`).join("")}</select></label>
      <label class="in"><span>Hotkey <small class="faint">public SS58 address, starts with 5</small></span><input name="hotkey" required minlength="46" maxlength="48" autocomplete="off" spellcheck="false"></label>
      <label class="in"><span>Name</span><input name="name" maxlength="80" placeholder="node-2"></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("plus")}Add</button></div></form>`;
    g.showModal();
  }

  // ---------- rewards ----------
  function rewards() {
    const r = cache.rewards;
    if (!r) return Loading.line("Adding up rewards and costs…");
    const t = r.totals, price = r.tao_usd;
    return `<div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("coins")}Rewards and economics <span class="faint">last ${r.days} days, a day</span></h2>
      <p class="faint small">On-chain rewards from the snapshots, at ${price ? `${usd(price)} a τ` : "no τ price (the collector hasn't one)"}; costs are what you enter, plus sandbox and Workflow dollars${r.settings.usd_per_mtok ? ` and tokens at ${usd(r.settings.usd_per_mtok)} per million` : ", and tokens once you set a rate in Settings"}. A high score isn't profit.</p></div></div>
      <div class="mh-kpis mcx-kpis">${kpi(t.tau_day ? "run" : "", "coins", "On-chain rewards", `${fmtNum(t.tau_day)} τ`, price ? `≈ ${usd(t.usd_day)}` : "no price", "")}
        ${kpi("", "coins", "Payouts", usd(t.payout_day), "competition payouts you entered", "")}
        ${kpi(t.cost_day ? "warn" : "", "wallet", "Costs", usd(t.cost_day), `${fmtNum(t.tokens_day / 1000, 0)}k tokens a day`, "")}
        ${kpi(t.net_day == null ? "" : t.net_day >= 0 ? "ok" : "bad", "chart", "Net", t.net_day == null ? "–" : usd(t.net_day), t.net_day == null ? "needs a τ price" : "rewards + payouts − costs", "")}</div>
      ${panel("By subnet competition", "globe", r.campaigns.length ? `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Competition</th><th class="r">τ / day</th><th class="r">$ / day</th><th class="r">Payouts</th><th class="r">Costs</th><th class="r">Net</th><th class="r">ROI</th><th>Expected / month</th><th class="r">Realized / month</th><th>30 days</th></tr></thead><tbody>
        ${r.campaigns.map(c => `<tr><td><b>SN${c.netuid}</b> ${esc(c.comp)} <span class="faint small">${plural(c.miners, "miner")}${c.best_rank ? ` · best #${c.best_rank}` : ""}</span></td><td class="r num">${fmtNum(c.tau_day)}</td><td class="r num">${usd(c.usd_day)}</td><td class="r num">${usd(c.payout_day)}</td>
          <td class="r num" title="${esc(Object.entries(c.costs_day).filter(([, v]) => v).map(([k, v]) => `${(r.kinds[k] || k)}: ${usd(v)}`).join("\n") || "none")}">${usd(c.cost_day)}</td><td class="r num ${c.net_day < 0 ? "mcx-down" : ""}">${usd(c.net_day)}</td><td class="r num">${c.roi != null ? `${fmtNum(c.roi, 2)}×` : "–"}</td>
          <td><form class="mcx-inline" data-mcexpect="${c.campaign}"><input name="v" type="number" min="0" step="any" value="${c.expected_month ?? ""}" placeholder="$" aria-label="Expected dollars a month"><button type="submit" class="iconbtn" aria-label="Save">${icon("check")}</button></form></td>
          <td class="r num">${usd(c.realized_month)}</td><td class="mcx-spark">${c.history.length > 1 ? line(c.history.map(h => ({ ts: h.day, v: h.tau })), 140, 34, false, v => `${fmtNum(v)} τ`) : ""}</td></tr>`).join("")}</tbody></table></div>` : `<p class="faint small">No campaign yet.</p>`)}
      <div class="mcx-sides">
        ${panel("Costs and payouts you entered", "wallet", `${r.costs.length ? `<ul class="mcx-mini">${r.costs.map(x => `<li>${chip([x.kind === "payout" ? "ok" : "none", r.kinds[x.kind]])} <b>${esc(x.label)}</b> ${usd(x.usd)} / ${x.period}${x.starts ? ` <span class="faint small">from ${esc(x.starts)}</span>` : ""}${x.ends ? ` <span class="faint small">to ${esc(x.ends)}</span>` : ""}
            <button type="button" class="iconbtn" data-mcdelcost="${x.id}" aria-label="Delete">${icon("trash")}</button></li>`).join("")}</ul>` : `<p class="faint small">None yet: add compute, hosting and infrastructure, and any competition payouts.</p>`}
          <form class="mcx-form mcx-costform" data-mccost><select name="kind" aria-label="Kind">${Object.entries(r.kinds).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select>
            <input name="label" required maxlength="120" placeholder="What (e.g. GPU box)" aria-label="What"><input name="usd" type="number" min="0" step="any" required placeholder="$" aria-label="Dollars">
            <select name="period" aria-label="Per"><option value="month">a month</option><option value="day">a day</option><option value="once">once</option></select>
            <select name="campaign" aria-label="For"><option value="">all</option>${r.campaigns.map(c => `<option value="${c.campaign}">SN${c.netuid} · ${esc(c.comp)}</option>`).join("")}</select>
            <input name="starts" type="date" aria-label="From"><button type="submit" class="btn sm">${icon("plus")}Add</button></form>`)}
        ${panel("Where to put effort", "target", r.teams.length ? `<div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Team</th><th class="r">Share</th><th class="r">Score</th><th class="r">Tokens / day</th></tr></thead><tbody>
          ${r.teams.map(x => `<tr data-mcopen="${x.id}" tabindex="0"><td>${esc(x.label)}</td><td class="r num">${x.share != null ? `${fmtNum(x.share * 100, 0)}%` : "–"}</td><td class="r num">${x.score != null ? val(x.primary, x.score) : "–"}</td><td class="r num">${fmtNum(x.tokens_day, 0)}</td></tr>`).join("")}</tbody></table></div>
          <p class="fine">Compare a team's measured score and emission share with what it costs; the Portfolio's manager can suggest budgets.</p>` : `<p class="faint small">No team yet.</p>`, `<button type="button" class="linkbtn" data-mcview="portfolio">Portfolio</button>`)}</div>`;
  }

  // ---------- approvals ----------
  function approvals() {
    const x = cache.approvals;
    if (!x) return Loading.line("Gathering what waits for you…");
    const card = a => { const [l, ic] = SRC[a.source], ev = a.evidence || {}, p = ev.primary;
      return `<li class="mh-card mcx-appr"><div class="mcx-appr-h">${icon(ic)}<div><b>${esc(a.title)}</b><span class="faint small">${l}${a.where ? ` · ${esc(a.where)}` : ""}${a.requested_by ? ` · by ${esc(a.requested_by.replace(/^\w+:/, ""))}` : ""} · ${ago(a.created)}${a.expires_at && a.status !== "consumed" ? ` · expires ${esc(when(a.expires_at))}` : ""}</span></div>
          ${chip(a.status === "consumed" && a.experiment ? ["run", "Deploy to record"] : APPR[a.status] || APPR.pending)}${a.risk ? ` ${chip([a.risk === "high" ? "bad" : a.risk === "medium" ? "warn" : "none", `${a.risk} risk`])}` : ""}</div>
        ${a.reason ? `<p class="small">${esc(a.reason)}</p>` : ""}
        ${a.source === "experiment" ? `<dl class="mcx-dl">${p ? `<dt>Evidence</dt><dd>${esc(mlabel(p.metric))}: ${val(p.metric, p.base)} → <b>${val(p.metric, p.cand)}</b>${p.band != null ? ` (noise ± ${val(p.metric, p.band)})` : ""} over ${p.runs[0]} + ${p.runs[1]} runs</dd>` : ""}
          ${ev.review ? `<dt>Review</dt><dd>${chip(REC[ev.review.verdict])} ${ev.review.reasons.map(esc).join(" ")}</dd>` : ""}
          <dt>Artifact</dt><dd>${esc(a.payload?.artifact?.kind || "")} <code>${esc(a.payload?.artifact?.ref || "–")}</code>${a.payload?.artifact?.repo ? ` · ${esc(a.payload.artifact.repo)}` : ""}${a.payload?.miner ? ` → ${esc(a.payload.miner.name || hk(a.payload.miner.hotkey))}` : ""}</dd>
          <dt>Rollback</dt><dd>${esc(a.rollback || "–")}</dd><dt>Bound to</dt><dd><code>${esc((a.hash || "").slice(0, 16))}</code></dd></dl>` : ""}
        <div class="row">${a.source === "experiment" ? `<button type="button" class="btn sm primary" data-mcexp="${a.experiment.id}">${icon("eye")}Review</button>`
          : a.source === "company" ? `<button type="button" class="btn sm" data-mcview="company">${icon("shield")}Open in Company</button>`
          : a.source === "miner_action" ? `<button type="button" class="btn sm" data-mccamp="${a.campaign}" data-mctab="overview">${icon("pickaxe")}Open in My subnets</button>`
          : `<button type="button" class="btn sm" data-mcteam="${a.team}" data-mcsub="flow">${icon("branch")}Open the Workflow</button>`}</div></li>`; };
    return `<div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("hand")}Approval Center</h2><p class="faint small">Production and external actions wait here, wherever they come from. Deploy approvals go through the Company's gateway: bound to the exact evidence, they expire and are used once; AXoR never deploys.</p></div></div>
      ${x.gateway ? "" : `<p class="mh-err small">${icon("info")}The Company is off on this server, so deploy approvals can't be asked for.</p>`}
      ${x.approvals.length ? `<ul class="mcx-apprs">${x.approvals.map(card).join("")}</ul>` : `<section class="mh-card mcx-empty"><p>${icon("check")} Nothing waits for you.</p></section>`}`;
  }

  // ---------- monitoring ----------
  function monitor() {
    const x = cache.monitor;
    if (!x) return Loading.line("Running the checks…");
    return `<div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("radio")}Monitoring</h2><p class="faint small">Silent or failing miners, quiet evaluators, regressions after a deploy, critical My subnets alerts and stuck teams. Checked ${ago(x.at)}.</p></div>
      <button type="button" class="btn sm" data-mc="reload">${icon("cycle")}Check now</button></div>
      ${x.checks.length ? `<ul class="mcx-checks big">${x.checks.map(check).join("")}</ul>` : `<section class="mh-card mcx-empty"><p>${icon("check")} All clear.</p></section>`}`;
  }

  // ---------- agents ----------
  function agents() {
    const x = cache.agents;
    if (!x) return Loading.line("Calling the roll…");
    const all = x.agents, uniq = k => [...new Set(all.map(a => a[k]).filter(v => v != null && v !== ""))];
    const q = af.q.trim().toLowerCase();
    const list = all.filter(a => (!af.net || String(a.netuid) === af.net) && (!af.team || String(a.team) === af.team) && (!af.squad || a.squad === af.squad) && (!af.status || a.status === af.status)
      && (!q || `${a.name} ${a.title} ${a.job} ${a.role}`.toLowerCase().includes(q)));
    const sel = (k, label, opts) => `<select data-mcaf="${k}" aria-label="${label}"><option value="">${label}: all</option>${opts.map(([v, l]) => `<option value="${esc(v)}" ${af[k] === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    const teams = [...new Map(all.map(a => [a.team, a.team_label])).entries()];
    return `<div class="mcx-perf-top"><div><h2 class="mcx-h2">${icon("users")}Team agents <span class="faint">${list.length} of ${all.length}</span></h2><p class="faint small">Every competition-team agent. Agents are the workforce; open one in its team to chat, assign and read its runs.</p></div></div>
      <div class="row mcx-filters"><input type="search" data-mcaf="q" value="${esc(af.q)}" placeholder="Search name, role, skill…" aria-label="Search">
        ${sel("net", "Subnet", uniq("netuid").map(n => [n, `SN${n}`]))}${sel("team", "Competition", teams)}${sel("squad", "Squad", uniq("squad").map(s => [s, s]))}${sel("status", "Status", [["working", "Working"], ["on", "On"], ["off", "Off"]])}</div>
      <div class="tablewrap flat"><table class="grid mini-table mcx-table"><thead><tr><th>Agent</th><th>Competition</th><th>Squad</th><th>Status</th><th class="r">Done</th><th class="r">Runs 7 d</th><th class="r">Failed</th><th class="r">Tokens 7 d</th><th>Last run</th></tr></thead><tbody>
        ${list.slice(0, 400).map(a => `<tr data-mcteam="${a.team}" data-mcsub="team" tabindex="0"><td><span class="av xs c-${esc(a.color || "slate")}" aria-hidden="true">${icon(a.icon || "bot")}</span> <b>${esc(a.name)}</b> <span class="faint small">${esc(a.title)}</span>${a.lead ? ` ${chip(["run", "lead"])}` : a.head ? ` ${chip(["none", "squad lead"])}` : ""}</td>
          <td>${esc(a.team_label)}${a.team_open ? "" : ` <span class="faint small">closed</span>`}</td><td>${esc(a.squad || "–")}</td><td>${chip(a.status === "working" ? ["run", "Working"] : a.status === "on" ? ["ok", "On"] : ["off", "Off"])}</td>
          <td class="r num">${a.done}</td><td class="r num">${a.runs_week}</td><td class="r num">${a.failed_week || ""}</td><td class="r num">${fmtNum(a.tokens_week, 0)}</td><td>${a.last ? ago(a.last) : "–"}</td></tr>`).join("") || `<tr><td colspan="9" class="faint">No agent matches.</td></tr>`}</tbody></table></div>`;
  }

  // ---------- settings ----------
  function settings() {
    const x = cache.settings;
    if (!x) return Loading.line("Opening the settings…");
    const s = x.settings;
    return `<div class="mcx-sides">
      ${panel("Ingest keys", "key", `<p class="small">The evaluator and your miners post measurements and health with a key: <code>Authorization: Bearer mcx_…</code> on <code>POST ${C}/ingest</code> (with <code>X-Requested-With: scout</code>). A key can only add reports to your teams and miners; it can't read anything.</p>
        ${newKey ? `<div class="mcx-newkey"><b>${icon("key")}Copy it now: it won't be shown again.</b><pre class="mcx-pre">${esc(newKey)}</pre><button type="button" class="btn sm" data-copy="${esc(newKey)}">${icon("copy")}Copy</button></div>` : ""}
        <ul class="mcx-mini">${x.keys.map(k => `<li><b>${esc(k.label)}</b> <code>${esc(k.prefix)}${String(k.prefix || "").startsWith("sha256:") ? "" : "…"}</code> <span class="faint small">${k.revoked ? "revoked" : `${k.uses} reports${k.last_used ? `, last ${ago(k.last_used)}` : ""}`}</span>${k.revoked ? "" : ` <button type="button" class="linkbtn" data-mcrevoke="${k.id}">Revoke</button>`}</li>`).join("") || `<li class="faint small">No key yet.</li>`}</ul>
        <form class="mcx-form row" data-mckey><input name="label" required maxlength="60" placeholder="evaluator, node-1…" aria-label="Key name"><button type="submit" class="btn sm">${icon("plus")}Make a key</button></form>`)}
      ${panel("How it judges", "sliders", `<form class="mcx-form" data-mcsettings>
        <label class="in"><span>Runs a side before an evaluation can recommend</span><input name="min_runs" type="number" min="2" max="50" value="${s.min_runs}"></label>
        <label class="in"><span>Model tokens: dollars per million <small class="faint">for the costs; empty = tokens only</small></span><input name="usd_per_mtok" type="number" min="0" step="any" value="${s.usd_per_mtok ?? ""}"></label>
        ${d.comps.map(c => `<label class="in"><span>${esc(c.label)}: primary metric</span><select name="p_${c.id}">${Object.entries(x.metrics).map(([k, m]) => `<option value="${k}" ${(s.primary[c.id] || "score") === k ? "selected" : ""}>${esc(m[0])}</option>`).join("")}</select></label>`).join("")}
        <div class="row"><button type="submit" class="btn sm">${icon("check")}Save</button></div></form>`)}</div>`;
  }

  // ---------- events ----------
  function openTeam(w, sub) { if (sub) store.set("mw.sub2", sub); MiningWork.openPage(w); if (sub) setTimeout(() => MiningWork.go(sub), 0); }
  async function dlgClick(e) {
    const t = e.target, g = e.currentTarget;
    if (t === g || t.closest("[data-close]")) return g.close();
    const cp = t.closest("[data-copy]"); if (cp) { navigator.clipboard?.writeText(cp.dataset.copy).then(() => Auth.toast("Copied")); return; }
    const st = t.closest("[data-mcstep]"); if (st) return expCall(st, "/step", { to: st.dataset.mcstep });
    const dr = t.closest("[data-mcdelrun]"); if (dr) { const [side, i] = dr.dataset.mcdelrun.split(":"); return expCall(dr, `/runs/${side}/${i}`, undefined, "DELETE"); }
    const xp = t.closest("[data-mcexp]"); if (xp) { g.close(); return openExp(+xp.dataset.mcexp); }
    const b = t.closest("[data-mc]"); if (!b) return;
    const k = b.dataset.mc;
    if (k === "review") return expCall(b, "/review", {});
    if (k === "authorize") return expCall(b, "/authorize", {});
    if (k === "revise") return expCall(b, "/revise", { note: "" });
    if (k === "abandon") return UI.confirm({ title: "Abandon the experiment?", body: "It closes; a pending approval is rejected. Its record stays.", ok: "Abandon", icon: "ban",
      run: async () => { await api(`${C}/experiments/${eid}/close`, { method: "POST", body: { outcome: "abandoned", reason: "" } }); await openExp(eid); } }).catch(err);
    if (k === "delexp") return UI.confirm({ title: "Delete the experiment?", body: "It and its log go. This can't be undone.", ok: "Delete",
      run: async () => { await api(`${C}/experiments/${eid}`, { method: "DELETE" }); g.close(); } }).catch(err);
    if (k === "delminer") return UI.confirm({ title: "Remove the miner?", body: "Its workspace and health reports go; its deploy record stays.", ok: "Remove",
      run: async () => { await api(`${C}/miners/${mid}`, { method: "DELETE" }); g.close(); cache.miners = null; load(); } }).catch(err);
  }
  async function dlgSubmit(e) {
    e.preventDefault();
    const f = e.target, btn = e.submitter || $("button[type=submit]", f), v = n => f.elements[n]?.value ?? "";
    if (f.matches("[data-mcnewexp]")) {
      const r = await busy(btn, () => api(`${C}/experiments`, { method: "POST", body: { comp_id: +v("comp"), title: v("title").trim(), idea: v("idea").trim(), source: v("source").trim() } }));
      if (r) { f.closest("dialog").close(); cache.exp = null; load(); openExp(r.id); }
      return;
    }
    if (f.matches("[data-mcaddminer]")) {
      const r = await busy(btn, () => api(`${C}/miners`, { method: "POST", body: { campaign_id: +v("campaign"), hotkey: v("hotkey").trim(), name: v("name").trim() } }));
      if (r) { f.closest("dialog").close(); cache.miners = null; load(); openMiner(r.id); }
      return;
    }
    if (f.matches("[data-mcminerform]")) {
      const r = await busy(btn, () => api(`${C}/miners/${mid}`, { method: "PATCH", body: { name: v("name"), version: v("version"), hardware: v("hardware"), config: v("config"), notes: v("notes"), comp_id: v("comp") ? +v("comp") : null } }));
      if (r) { mn = r; drawMiner(); cache.miners = null; Auth.toast("Saved"); }
      return;
    }
    if (f.matches("[data-mcmeasure]")) {
      const metrics = {}; for (const k of Object.keys(d.metrics)) { const x = v(`m_${k}`); if (x !== "") metrics[k] = +x; }
      const r = await busy(btn, () => api(`${C}/metrics`, { method: "POST", body: { comp_id: +v("comp"), metrics, run: v("run").trim(), note: v("note").trim() } }));
      if (r) { f.closest("dialog").close(); Auth.toast(`Stored ${r.stored}`); cache.perf = null; load(); }
      return;
    }
    if (!ex) return;
    if (f.matches("[data-mcpatch]")) {
      const body = {};
      for (const n of ["title", "idea", "benefit", "risks", "cost", "sandbox_note"]) if (f.elements[n]) body[n] = v(n);
      if (f.elements.primary) { body.primary = v("primary"); body.artifact = { kind: v("akind"), ref: v("aref").trim(), repo: v("arepo").trim() }; body.miner_id = v("miner") ? +v("miner") : null; }
      return expCall(btn, "", body, "PATCH");
    }
    if (f.matches("[data-mclink]")) { if (!v("ref")) return; const [kind, id] = v("ref").split(":"); return expCall(btn, "/link", { kind, id: +id }); }
    if (f.matches("[data-mcrun]")) {
      const side = v("side");
      if (v("report")) return expCall(btn, `/runs/report?side=${side}&label=${encodeURIComponent(v("report"))}`, {});
      if (v("lab")) return expCall(btn, "/link", { kind: "lab", id: +v("lab"), side });
      const run = { label: v("label").trim() }; for (const k of Object.keys(d.metrics)) { const x = v(`m_${k}`); if (x !== "") run[k] = +x; }
      if (Object.keys(run).length < 2) return Auth.toast("Give at least one metric");
      return expCall(btn, "/runs", { side, runs: [run] });
    }
    if (f.matches("[data-mcapprove]")) return expCall(btn, "/approval", { note: v("note") });
    if (f.matches("[data-mcdecide]")) return expCall(btn, "/decide", { decision: btn.dataset.dec, reason: v("reason") });
    if (f.matches("[data-mcdeploy]")) return expCall(btn, "/deployed", { version: v("version").trim(), miner_id: v("miner") ? +v("miner") : null, note: v("note").trim() });
    if (f.matches("[data-mcclose]")) {
      const out = btn.dataset.out;
      if (out === "rolled_back") return UI.confirm({ title: "Record a rollback?", body: "The previous version becomes the active one in the record and the experiment closes. Carry the rollback out on the miner.", ok: "Roll back", icon: "undo",
        run: () => expCall(btn, "/close", { outcome: out, reason: v("reason") }) }).catch(err);
      return expCall(btn, "/close", { outcome: out, reason: v("reason") });
    }
  }
  function measure() {
    const g = dlg("mcx-new", "mcx-small");
    g.innerHTML = `<form class="hq-dlg-in mcx-form" data-mcmeasure>${X}<h3>${icon("plus")} Record a measurement</h3><p class="faint small">From a run you measured yourself. Shares are 0–1, latency in milliseconds, cost in dollars.</p>
      <label class="in"><span>Competition team</span><select name="comp">${d.comps.map(c => `<option value="${c.id}" ${c.id === wid ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></label>
      <div class="mcx-mgrid">${Object.entries(d.metrics).map(([k, m]) => `<label class="in"><span>${esc(m[0])}</span><input name="m_${k}" type="number" step="any" inputmode="decimal"></label>`).join("")}</div>
      <div class="row"><input name="run" maxlength="80" placeholder="run label (optional)" aria-label="Run label"><input name="note" maxlength="300" placeholder="note" aria-label="Note"></div>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("check")}Store</button></div></form>`;
    g.showModal();
  }
  function wire() {
    if (wired) return; wired = true;
    const host = $("#mining");
    host.addEventListener("click", async e => {
      if (!el?.contains(e.target)) return;
      const t = e.target;
      const g = t.closest("[data-mcgo]"); if (g) return go(g.dataset.mcgo);
      const w = t.closest("[data-mcw]"); if (w) return go(w.dataset.mct || sec, +w.dataset.mcw);
      const o = t.closest("[data-mcopen]"); if (o) return go("comp", +o.dataset.mcopen);
      const xp = t.closest("[data-mcexp]"); if (xp) return openExp(+xp.dataset.mcexp);
      const nw = t.closest("[data-mcnew]"); if (nw) return newExp(+nw.dataset.mcnew);
      const mi = t.closest("[data-mcminer]"); if (mi) return openMiner(+mi.dataset.mcminer);
      const tm = t.closest("[data-mcteam]"); if (tm) return openTeam(+tm.dataset.mcteam, tm.dataset.mcsub);
      const cp = t.closest("[data-mccamp]"); if (cp) return Mining.camp(+cp.dataset.mccamp, cp.dataset.mctab || "overview");
      const vw = t.closest("[data-mcview]"); if (vw) return setView(vw.dataset.mcview);
      const dy = t.closest("[data-mcdays]"); if (dy) { days = +dy.dataset.mcdays; cache.perf = null; render(); return load(); }
      const dm = t.closest("[data-mcdelm]"); if (dm) { await busy(dm, () => api(`${C}/metrics/${dm.dataset.mcdelm}`, { method: "DELETE" })); cache.perf = null; return load(); }
      const dc = t.closest("[data-mcdelcost]"); if (dc) { const r = await busy(dc, () => api(`${C}/costs/${dc.dataset.mcdelcost}`, { method: "DELETE" })); if (r) { cache.rewards = r; render(); } return; }
      const rv = t.closest("[data-mcrevoke]"); if (rv) return UI.confirm({ title: "Revoke the key?", body: "Whatever posts with it is refused from now on.", ok: "Revoke", icon: "key",
        run: async () => { cache.settings = { ...cache.settings, ...(await api(`${C}/keys/${rv.dataset.mcrevoke}`, { method: "DELETE" })) }; render(); } }).catch(err);
      const b = t.closest("[data-mc]"); if (!b) return;
      const k = b.dataset.mc;
      if (k === "reload") { cache[sec] = null; return load(true); }
      if (k === "measure") return measure();
      if (k === "addminer") return addMiner();
    });
    host.addEventListener("keydown", e => {
      if (e.key !== "Enter" || !el?.contains(e.target)) return;
      const tr = e.target.closest("tr[data-mcopen], tr[data-mcminer], tr[data-mccamp], tr[data-mcteam]"); if (tr) tr.click();
    });
    host.addEventListener("input", e => {
      const f = e.target.closest("[data-mcaf]"); if (!f || !el?.contains(f)) return;
      af[f.dataset.mcaf] = f.value;
      const pos = f.selectionStart; render(); const n = $(`[data-mcaf="${f.dataset.mcaf}"]`, el); if (n) { n.focus(); if (n.setSelectionRange && pos != null) try { n.setSelectionRange(pos, pos); } catch { /* select */ } }
    });
    host.addEventListener("submit", async e => {
      const f = e.target; if (!el?.contains(f)) return;
      e.preventDefault();
      const btn = e.submitter || $("button[type=submit]", f), v = n => f.elements[n]?.value ?? "";
      if (f.matches("[data-mckey]")) { const r = await busy(btn, () => api(`${C}/keys`, { method: "POST", body: { label: v("label").trim() } })); if (r) { newKey = r.token; cache.settings = { ...cache.settings, keys: r.keys }; f.reset(); render(); } return; }
      if (f.matches("[data-mcsettings]")) {
        const primary = {}; for (const c of d.comps) if (f.elements[`p_${c.id}`]) primary[c.id] = v(`p_${c.id}`);
        const r = await busy(btn, () => api(`${C}/settings`, { method: "PATCH", body: { min_runs: +v("min_runs"), usd_per_mtok: v("usd_per_mtok") === "" ? 0 : +v("usd_per_mtok"), primary } }));
        if (r) { cache.settings.settings = r.settings; Auth.toast("Saved"); d = null; load(true); } return;
      }
      if (f.matches("[data-mccost]")) {
        const r = await busy(btn, () => api(`${C}/costs`, { method: "POST", body: { kind: v("kind"), label: v("label").trim(), usd: +v("usd"), period: v("period"), campaign_id: v("campaign") ? +v("campaign") : null, starts: v("starts") } }));
        if (r) { cache.rewards = r; render(); } return;
      }
      if (f.matches("[data-mcexpect]")) {
        const r = await busy(btn, () => api(`${C}/settings`, { method: "PATCH", body: { expected: { [f.dataset.mcexpect]: +v("v") || 0 } } }));
        if (r) { cache.rewards = null; load(); } return;
      }
    });
    let resized;
    window.addEventListener("resize", () => { if (!shown() || sec !== "perf") return; clearTimeout(resized); resized = setTimeout(drawCharts, 150); });
  }
  return { mount, stop, go, openExp, openMiner };
})();
