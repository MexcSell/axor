/* My subnets operations (mining_ops.py, mining-ops.css): the screens the My subnets shell (mining-shell.js) shows in place of
   the My subnets page, and the project assistant.
   - Live operations: who is working on what right now across every team, the queues, and one event stream from every
     competition team and campaign team (polled every 4 s while it shows).
   - Team builder: a team's squads as columns; drag an agent to another squad (or onto another team to move it), drag a role in
     to add an agent; every card also has a menu for the same moves without dragging.
   - Deployment history: every recorded deploy and rollback of your miners, with its experiment and approval.
   - Budgets & alerts: today's spend per team against its budget (edit the budgets here), a daily dollar cap, the performance
     drop that raises an alert, and the alert history. The same alerts show in the Command center's Monitoring.
   - Ask AI: a drawer that answers about one team, one campaign or the whole division from a snapshot of it. */
const MiningOps = (() => {
  const O = "/api/mining/ops", W = "/api/mining/work";
  let host = null, screen = null, timer = null, wired = false;
  let live = null, seen = new Set(), fresh = new Set(), paused = false, lf = { src: "", where: "", q: "" };
  let bld = null, bwid = null, bview = null, extra = [], drag = null;
  let deps = null, df = { team: "", miner: "", status: "", q: "" };
  let alerts = null;
  let scope = null, thread = null, asking = false;
  const err = e => e && e.message !== "cancelled" && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : fmtNum(n || 0, 0);
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
  const span = s => s < 60 ? `${Math.max(0, Math.round(s))}s` : s < 3600 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
  const av = (a, size = "sm") => `<span class="av ${size} c-${esc(a?.color || "slate")}" aria-hidden="true">${icon(a?.icon || "bot")}</span>`;
  const kpi = (cls, ic, label, value, small) => `<div class="mh-kpi ${cls}">${icon(ic)}<span class="mh-kpi-l">${label}</span><b>${value}</b><small>${small}</small></div>`;
  const panel = (title, ic, inner, extra = "") => `<section class="mh-card mo-panel"><h2 class="hq-h">${icon(ic)}${title}${extra}</h2>${inner}</section>`;
  const SCREENS = { live: ["Live operations", "radio"], builder: ["Team builder", "users"], deploys: ["Deployment history", "rocket"], budgets: ["Budgets & alerts", "coins"] };
  const LEVEL = { stop: ["bad", "alert"], warn: ["warn", "info"], info: ["none", "info"] };
  const DSTATUS = { active: ["ok", "Running"], replaced: ["none", "Replaced"], rolled_back: ["bad", "Rolled back"] };

  // ---------- showing a screen (the shell calls show/hide; the host sits beside #mining) ----------
  function show(s, node) {
    wire();
    host = node; screen = s;
    const [title, ic] = SCREENS[s];
    if (!$(".mo-body", host) || host.dataset.screen !== s) {
      host.dataset.screen = s;
      host.innerHTML = `<div class="mo"><header class="mo-top"><h2>${icon(ic)}${title}</h2><div class="mo-act"></div></header><div class="mo-body">${Loading.line("Loading…")}</div></div>`;
    }
    load();
  }
  function hide() { screen = null; clearTimeout(timer); }
  const shown = () => screen && host?.isConnected && !host.hidden && !$("#view-mining")?.hidden;
  async function load() {
    clearTimeout(timer);
    const s = screen;
    try {
      if (s === "live") {
        const since = live ? Math.max(0, live.at - 30) : 0, r = await api(`${O}/live${since ? `?since=${since}` : ""}`);
        const old = live?.events || [];
        for (const e of r.events) { const k = `${e.src}:${e.id}`; if (!seen.has(k)) { seen.add(k); if (live) fresh.add(k); } }
        const byKey = new Map([...r.events, ...old].map(e => [`${e.src}:${e.id}`, e]));
        live = { ...r, events: [...byKey.values()].sort((a, b) => b.ts - a.ts).slice(0, 400) };
      }
      if (s === "builder") {
        bld = await api(`${O}/builder`);
        if (!bld.teams.some(t => t.id === bwid)) bwid = store.get("mo.bw", null);
        if (!bld.teams.some(t => t.id === bwid)) bwid = bld.teams[0]?.id ?? null;
        bview = bwid ? await api(`${W}/comps/${bwid}`) : null;
      }
      if (s === "deploys") deps = await api(`${O}/deploys`);
      if (s === "budgets") alerts = await api(`${O}/alerts`);
    } catch (e) { if (s === screen) put($(".mo-body", host), `<div class="empty">${esc(e.message)} <button type="button" class="linkbtn" data-mo="reload">Try again</button></div>`); return; }
    if (s !== screen) return;
    if (!typing() && !drag) render();
    if (s === "live") timer = setTimeout(function tick() { if (!shown()) return; if (paused || document.visibilityState !== "visible") { timer = setTimeout(tick, 4000); return; } load(); }, 4000);
    if (s === "budgets") timer = setTimeout(() => { if (shown() && !typing()) load(); }, 60000);
  }
  const typing = () => !!document.activeElement?.closest?.(".mo form");
  function render() {
    if (!shown()) return;
    const body = { live: liveView, builder: builderView, deploys: deploysView, budgets: budgetsView }[screen];
    put($(".mo-act", host), actions());
    put($(".mo-body", host), body());
    $$("time[data-ts]", host).forEach(t => { t.textContent = ago(+t.dataset.ts); });
    fresh.clear();
  }
  function actions() {
    if (screen === "live") return `<button type="button" class="btn sm" data-mo="pause" aria-pressed="${paused}">${icon(paused ? "play" : "stop")}${paused ? "Resume the stream" : "Pause the stream"}</button>`;
    if (screen === "builder") return `<button type="button" class="btn sm" data-mo="teampage">${icon("external")}Open the team's page</button>`;
    return "";
  }

  // ---------- live operations ----------
  function liveView() {
    const r = live, now = Date.now() / 1000;
    const q = r.queue.reduce((a, x) => ({ queued: a.queued + x.queued, checking: a.checking + x.checking, waiting: a.waiting + x.waiting }), { queued: 0, checking: 0, waiting: 0 });
    const tiles = `<div class="mh-kpis mo-kpis">${kpi(r.working.length ? "run" : "", "zap", "Working now", r.working.length, r.working.length ? plural(new Set(r.working.map(w => w.team)).size, "team") : "nobody at work")}
      ${kpi(q.queued ? "info" : "", "list", "Queued", q.queued, "tasks about to start")}${kpi(q.checking ? "info" : "", "eye", "In review", q.checking, "squad leads checking")}
      ${kpi(q.waiting ? "warn" : "ok", "hand", "Waiting for you", q.waiting, q.waiting ? "reviews and blocked tasks" : "nothing blocked on you")}
      ${kpi(r.cycles.length ? "run" : "", "cycle", "Campaign cycles", r.cycles.length, r.cycles.length ? r.cycles.map(c => esc(c.where)).join(", ") : "none running")}</div>`;
    const working = r.working.length ? `<ul class="mo-working">${r.working.map(w => `<li><button type="button" data-moteam="${w.team}" ${w.task_id ? `data-motask="${w.task_id}"` : ""}>
        ${av(w.agent)}<span class="mo-w-main"><b>${esc(w.agent.name)}</b> <span class="faint small">${esc(w.agent.title)}</span><span class="mo-w-task">${w.task ? esc(w.task) : w.kind === "plan" ? "Planning the next tasks" : esc(w.kind)}</span></span>
        <span class="mo-w-side"><span class="hq-chip t-none">${esc(w.where)}</span><span class="num small" data-since="${w.since}">${span(now - w.since)}</span>${w.tokens ? `<span class="faint small">${short(w.tokens)} tokens</span>` : ""}</span></button></li>`).join("")}</ul>`
      : `<p class="faint small mo-none">${icon("check")} Nobody is working right now. Autopilot teams start work on their own; others wait for <b>Plan now</b> or a task you start.</p>`;
    const cyc = r.cycles.map(c => `<li><span class="ci ci-run"></span><b>${esc(c.where)}</b> <span class="faint small">cycle at ${esc(c.step || "…")}${Object.keys(c.activity).length ? ` · ${esc(Object.entries(c.activity).map(([a, t]) => `${a}: ${t}`).join(" · "))}` : ""}</span></li>`).join("");
    const list = r.events.filter(e => (!lf.src || e.src === lf.src) && (!lf.where || `${e.src}:${e.team ?? e.campaign}` === lf.where)
      && (!lf.q || `${e.text} ${e.agent?.name || e.staff || ""} ${e.where}`.toLowerCase().includes(lf.q.toLowerCase())));
    const opts = [...r.teams.map(t => [`team:${t.id}`, t.label]), ...r.campaigns.map(c => [`campaign:${c.id}`, `${c.label} (campaign)`])];
    const stream = `<div class="mo-filters"><div class="seg" role="group" aria-label="Source">${[["", "Everything"], ["team", "Competition teams"], ["campaign", "Campaign teams"]].map(([k, l]) =>
        `<button type="button" data-molsrc="${k}" aria-pressed="${lf.src === k}">${l}</button>`).join("")}</div>
      <select data-molwhere aria-label="Team or campaign"><option value="">Every team and campaign</option>${opts.map(([k, l]) => `<option value="${k}" ${lf.where === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
      <input type="search" data-molq placeholder="Filter the stream" value="${esc(lf.q)}" aria-label="Filter the stream"></div>
      ${list.length ? `<ol class="mo-stream">${list.slice(0, 200).map(e => { const k = `${e.src}:${e.id}`;
        return `<li class="${fresh.has(k) ? "new" : ""}" ${e.src === "team" ? `data-moteam="${e.team}" ${e.task ? `data-motask="${e.task}"` : ""}` : `data-mocamp="${e.campaign}"`} tabindex="0">
          <time data-ts="${e.ts}" title="${esc(when(e.ts))}">${ago(e.ts)}</time>${e.agent ? av(e.agent, "xs") : `<span class="av xs c-slate" aria-hidden="true">${icon(e.src === "campaign" ? "pickaxe" : "bot")}</span>`}
          <span class="mo-ev"><span class="mo-ev-h"><b>${esc(e.agent?.name || e.staff || "Team")}</b><span class="hq-chip t-none">${esc(e.where)}</span><span class="faint small">${esc(e.kind)}</span></span><span class="mo-ev-t">${esc(e.text)}</span></span></li>`; }).join("")}</ol>`
        : `<p class="faint small mo-none">Nothing in the last three days${lf.src || lf.where || lf.q ? " matches the filter" : ""}.</p>`}`;
    return `${tiles}<div class="mo-grid">${panel("Working now", "zap", working + (cyc ? `<ul class="mo-cycles">${cyc}</ul>` : ""), `<span class="hq-live ${r.working.length ? "on" : ""}">${r.working.length ? "live" : ""}</span>`)}
      ${panel("Queues", "list", r.queue.length ? `<ul class="mo-queue">${r.queue.map(x => `<li><button type="button" data-moteam="${x.team}"><b>${esc(x.where)}</b><span>${x.queued ? `${x.queued} queued` : ""}${x.checking ? ` · ${x.checking} in review` : ""}${x.waiting ? ` · <span class="mo-warn">${x.waiting} waiting for you</span>` : ""}</span></button></li>`).join("")}</ul>`
        : `<p class="faint small mo-none">No queues.</p>`)}</div>
      ${panel("Event stream", "radio", stream, `<span class="faint">${paused ? "paused" : "updates every 4 seconds"} · ${plural(list.length, "event")}</span>`)}`;
  }
  // the elapsed times tick between polls
  setInterval(() => { if (screen !== "live" || !shown()) return; const now = Date.now() / 1000; $$("[data-since]", host).forEach(x => { x.textContent = span(now - +x.dataset.since); }); }, 1000);

  // ---------- team builder ----------
  function builderView() {
    if (!bld.teams.length) return `<section class="mh-card mo-empty"><h3>${icon("users")}No competition team yet</h3><p>Open a campaign's <b>Team control room</b> and put a team on its competition; then build it here.</p></section>`;
    const v = bview, S = bld.squads;
    const teams = `<div class="mo-teams" role="tablist" aria-label="Competition teams">${bld.teams.map(t => `<button type="button" class="mw-tab ${t.id === bwid ? "on" : ""}" data-mobw="${t.id}" data-modrop="team" data-team="${t.id}" aria-selected="${t.id === bwid}" role="tab">
      <b>${esc(t.label)}</b><small>${esc(t.name || "")}</small></button>`).join("")}</div>`;
    if (!v) return teams + Loading.line("Opening the team…");
    const present = [...new Set(v.agents.map(a => a.squad || ""))];
    const cols = [...present.filter(Boolean).sort((a, b) => (a === "command" ? -1 : b === "command" ? 1 : (S[a] || a).localeCompare(S[b] || b))), ...extra.filter(k => !present.includes(k)), ...(present.includes("") ? [""] : [])];
    const others = bld.teams.filter(t => t.id !== bwid);
    const card = a => `<li class="mo-card ${a.on ? "" : "off"}" data-modrag="agent" data-agent="${a.id}" tabindex="0">
        <div class="mo-card-h">${av(a)}<div><b>${esc(a.name)}</b><span class="faint small">${esc(a.title)}</span></div><span class="mo-grip" aria-hidden="true">${icon("dots")}</span></div>
        <div class="mo-card-tags">${a.lead ? chip(["run", "Team lead"]) : ""}${a.head ? chip(["none", "Squad lead"]) : ""}${a.on ? "" : chip(["off", "Off"])}${a.working ? chip(["run", "Working"]) : ""}</div>
        <details class="mo-card-m"><summary>Change</summary><div class="mo-card-menu">
          <label class="in"><span>Squad</span><select data-mosquad="${a.id}"><option value="">No squad</option>${Object.entries(S).map(([k, l]) => `<option value="${k}" ${a.squad === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
          ${others.length ? `<label class="in"><span>Another team</span><select data-moto="${a.id}"><option value="">Pick a team…</option>${others.map(t => `<option value="${t.id}">${esc(t.label)}</option>`).join("")}</select></label>
            <div class="row"><button type="button" class="btn sm" data-momove="${a.id}">${icon("right")}Move</button><button type="button" class="btn sm" data-mocopy="${a.id}">${icon("copy")}Copy</button></div>` : ""}
          <div class="row">${a.squad && !a.lead ? `<button type="button" class="btn sm" data-mohead="${a.id}" data-on="${!a.head}">${a.head ? "Not squad lead" : "Make squad lead"}</button>` : ""}
            <button type="button" class="btn sm" data-moon="${a.id}" data-on="${!a.on}">${a.on ? "Switch off" : "Switch on"}</button>
            ${a.lead ? "" : `<button type="button" class="btn sm danger" data-morm="${a.id}">${icon("trash")}Remove</button>`}</div></div></details></li>`;
    const col = k => { const list = v.agents.filter(a => (a.squad || "") === k);
      return `<section class="mo-col" data-modrop="squad" data-squad="${k}" aria-label="${esc(S[k] || "No squad")}"><h3>${esc(k ? S[k] || k : "No squad")}<span class="faint">${list.length}</span></h3>
        <ul>${list.map(card).join("") || `<li class="mo-col-empty faint small">Drop an agent or a role here</li>`}</ul></section>`; };
    const free = Object.entries(S).filter(([k]) => !cols.includes(k));
    const roles = `<aside class="mo-roles" aria-label="Roles"><h3>${icon("plus")}Add an agent</h3><p class="faint small">Drag a role onto a squad, or pick one and a squad.</p>
      <ul>${bld.roles.map(r => `<li class="mo-role" data-modrag="role" data-role="${r.id}" tabindex="0" title="${esc(r.job)}">${av(r, "xs")}<span><b>${esc(r.title || "Custom agent")}</b><small>${esc(r.name || "you name it")}</small></span><span class="mo-grip" aria-hidden="true">${icon("dots")}</span></li>`).join("")}</ul>
      <form class="mo-addf" data-moadd><select name="role" aria-label="Role">${bld.roles.map(r => `<option value="${r.id}">${esc(r.title || "Custom agent")}</option>`).join("")}</select>
        <select name="squad" aria-label="Squad"><option value="">No squad</option>${Object.entries(S).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select>
        <button type="submit" class="btn sm primary">${icon("plus")}Add</button></form></aside>`;
    return `${teams}<p class="faint small mo-hint">${icon("info")}<span>${plural(v.agents.length, "agent")} of at most ${v.limits.agents}. Drag a card to another squad, or onto another team above to move it there; the <b>Change</b> menu does the same without dragging. A moved agent keeps its job and instructions; team and squad leads don't carry over.</span></p>
      <div class="mo-builder">${roles}<div class="mo-board">${cols.map(col).join("")}
        ${free.length ? `<section class="mo-col mo-col-add"><label class="in"><span>Show another squad</span><select data-moextra><option value="">Pick a squad…</option>${free.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select></label></section>` : ""}</div></div>`;
  }
  async function patchAgent(id, body) { try { bview = await api(`${W}/comps/${bwid}/agents/${id}`, { method: "PATCH", body }); render(); } catch (e) { err(e); render(); } }
  async function addAgent(role, squad) {
    // a role's usual name is often taken on a pack team: number it instead (Iris 2, Iris 3…)
    const r = bld.roles.find(x => x.id === role), taken = new Set(bview.agents.map(a => a.name.toLowerCase()));
    let name = r?.name || "", n = 1;
    while (name && taken.has(name.toLowerCase())) name = `${r.name} ${++n}`;
    try { bview = await api(`${W}/comps/${bwid}/agents`, { method: "POST", body: { role, squad, name } }); render(); Auth.toast(`${name || "Agent"} added`); } catch (e) { err(e); }
  }
  async function moveAgent(id, to, copy) {
    const a = bview.agents.find(x => x.id === id), t = bld.teams.find(x => x.id === to);
    if (!a || !t) return;
    const ok = await UI.confirm({ title: `${copy ? "Copy" : "Move"} ${esc(a.name)} to ${esc(t.label)}?`, body: copy ? "A copy joins that team with the same job and instructions." :
      "They join that team with the same job and instructions and leave this one; their open tasks here become yours to reassign.", ok: copy ? "Copy" : "Move", icon: copy ? "copy" : "right", danger: false,
      run: async () => { const r = await api(`${O}/agents/move`, { method: "POST", body: { from_team: bwid, agent: id, to_team: to, copy_only: copy } }); bview = r.from; } });
    if (ok) { Auth.toast(copy ? `${a.name} copied to ${t.label}` : `${a.name} moved to ${t.label}`); render(); }
  }
  // dragging: pointer events (mouse, pen and touch); a ghost follows the pointer and the drop target lights up
  function dragStart(e) {
    const src = e.target.closest("[data-modrag]");
    if (!src || e.button || screen !== "builder" || e.target.closest("details, select, button, input, summary")) return;
    if (e.pointerType === "touch" && !e.target.closest(".mo-grip")) return;  // on a touch screen a swipe scrolls; the grip drags
    drag = { src, kind: src.dataset.modrag, x: e.clientX, y: e.clientY, on: false, ghost: null, over: null };
  }
  function dragMove(e) {
    if (!drag) return;
    if (!drag.on) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return;
      drag.on = true; drag.src.classList.add("mo-dragging");
      drag.ghost = drag.src.cloneNode(true); drag.ghost.className = "mo-ghost"; document.body.append(drag.ghost);
      document.body.classList.add("mo-drag-on");
    }
    e.preventDefault();
    drag.ghost.style.transform = `translate(${e.clientX + 10}px, ${e.clientY + 8}px)`;
    const t = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-modrop]");
    const ok = t && (t.dataset.modrop === "squad" || (drag.kind === "agent" && t.dataset.modrop === "team" && +t.dataset.team !== bwid));
    if (drag.over && drag.over !== t) drag.over.classList.remove("mo-over");
    drag.over = ok ? t : null; drag.over?.classList.add("mo-over");
  }
  function dragEnd() {
    if (!drag) return;
    const d = drag; drag = null;
    d.src.classList.remove("mo-dragging"); d.ghost?.remove(); d.over?.classList.remove("mo-over"); document.body.classList.remove("mo-drag-on");
    if (!d.on || !d.over) return;
    if (d.kind === "role") return addAgent(d.src.dataset.role, d.over.dataset.squad);
    const id = +d.src.dataset.agent, a = bview.agents.find(x => x.id === id);
    if (d.over.dataset.modrop === "team") return moveAgent(id, +d.over.dataset.team, false);
    if (a && (a.squad || "") !== d.over.dataset.squad) patchAgent(id, { squad: d.over.dataset.squad });
  }

  // ---------- deployment history ----------
  function deploysView() {
    const r = deps, list = r.deploys.filter(x => (!df.team || x.team === df.team) && (!df.miner || String(x.miner?.id) === df.miner) && (!df.status || x.status === df.status)
      && (!df.q || `${x.version} ${x.ref || ""} ${x.note || ""} ${x.experiment?.title || ""}`.toLowerCase().includes(df.q.toLowerCase())));
    const miners = [...new Map(r.deploys.filter(x => x.miner).map(x => [x.miner.id, x.miner])).values()], teams = [...new Set(r.deploys.map(x => x.team).filter(Boolean))];
    const last = r.deploys.find(x => !x.rollback_of);
    const tiles = `<div class="mh-kpis mo-kpis">${kpi("", "rocket", "Deploys", r.deploys.filter(x => !x.rollback_of && x.exp_id).length, "through approved experiments")}
      ${kpi(r.active ? "ok" : "", "pickaxe", "Running versions", r.active, "one per miner")}${kpi(r.rollbacks ? "warn" : "", "undo", "Rollbacks", r.rollbacks, r.rollbacks ? "restored an earlier version" : "none")}
      ${kpi("", "clock", "Last deploy", last ? `<span class="mh-kpi-txt">${esc(ago(last.ts))}</span>` : "–", last ? esc(last.version) : "nothing recorded")}</div>`;
    if (!r.deploys.length) return tiles + `<section class="mh-card mo-empty"><h3>${icon("rocket")}No deploy recorded yet</h3><p>A deploy is recorded when an approved experiment reaches <b>Production</b> in the Experiment center and you record the version you shipped. AXoR never deploys by itself.</p>
      <button type="button" class="btn sm" data-mogo="exp">${icon("bulb")}Open the Experiment center</button></section>`;
    const sel = (k, label, opts) => `<select data-modf="${k}" aria-label="${label}"><option value="">${label}: all</option>${opts.map(([v, l]) => `<option value="${esc(v)}" ${df[k] === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    return `${tiles}<section class="mh-card mo-panel"><h2 class="hq-h">${icon("list")}Every deploy and rollback <span class="faint">${plural(list.length, "entry", "es")}</span></h2>
      <div class="mo-filters">${sel("team", "Team", teams.map(t => [t, t]))}${sel("miner", "Miner", miners.map(m => [m.id, m.name || m.hotkey.slice(0, 10)]))}${sel("status", "Status", Object.entries(DSTATUS).map(([k, v]) => [k, v[1]]))}
        <input type="search" data-modq placeholder="Version, ref or note" value="${esc(df.q)}" aria-label="Search deploys"></div>
      <ol class="mo-deploys">${list.map(x => `<li class="s-${x.status}">
        <span class="mo-d-dot" aria-hidden="true">${icon(x.rollback_of ? "undo" : x.exp_id ? "rocket" : "pickaxe")}</span>
        <div class="mo-d-main"><div class="mo-d-h"><code>${esc(x.version)}</code>${chip(DSTATUS[x.status] || ["none", x.status])}${x.rollback_of ? chip(["warn", `rollback of #${x.rollback_of}`]) : ""}${x.ref ? `<span class="faint small">ref <code>${esc(x.ref.slice(0, 12))}</code></span>` : ""}</div>
          <div class="faint small">${x.miner ? `<button type="button" class="linkbtn" data-mominer="${x.miner.id}">${esc(x.miner.name || x.miner.hotkey.slice(0, 10))}</button>` : "no miner"} · ${esc(x.team || "no team")} · ${esc(x.by_user || "")} · ${esc(when(x.ts))}</div>
          ${x.note ? `<p class="small">${esc(x.note)}</p>` : ""}
          ${x.experiment ? `<div class="mo-d-exp">${icon("bulb")}<button type="button" class="linkbtn" data-moexp="${x.experiment.id}">${esc(x.experiment.title)}</button><span class="faint small">${esc(x.experiment.stage || "")} · ${esc(x.experiment.status || "")}${x.approval_id ? ` · approval #${x.approval_id}` : ""}</span>
            ${x.status === "active" && x.experiment.stage === "monitoring" && x.experiment.status === "open" ? `<button type="button" class="btn sm" data-moexp="${x.experiment.id}">${icon("undo")}Keep or roll back</button>` : ""}</div>` : ""}</div>
        <span class="faint small mo-d-id">#${x.id}</span></li>`).join("")}</ol></section>`;
  }

  // ---------- budgets & alerts ----------
  function budgetsView() {
    const a = alerts, s = a.settings, sp = a.spend, open = a.checks.filter(c => c.level !== "info");
    const over = sp.teams.filter(t => t.pct != null && t.pct >= 1).length;
    const tiles = `<div class="mh-kpis mo-kpis">${kpi(s.usd_day_cap && sp.usd != null && sp.usd >= s.usd_day_cap ? "bad" : "", "coins", "Spend, last 24 h", sp.usd != null ? usd(sp.usd) : `${short(sp.tokens)}`, sp.usd != null ? `${short(sp.tokens)} tokens${sp.sandbox_usd ? ` · ${usd(sp.sandbox_usd)} sandbox` : ""}` : "tokens · no token rate set")}
      ${kpi(s.usd_day_cap ? "info" : "", "target", "Daily cap", s.usd_day_cap ? usd(s.usd_day_cap) : "–", s.usd_day_cap ? `alerts at ${s.warn_pct}%` : "not set")}
      ${kpi(over ? "bad" : "ok", "users", "Teams over budget", over, `of ${sp.teams.length} open`)}${kpi(open.length ? "warn" : "ok", "shield", "Open alerts", open.length, open.length ? "budget and performance" : "all clear")}</div>`;
    const checks = a.checks.length ? `<ul class="mcx-checks big">${a.checks.map(c => { const [cls, ic] = LEVEL[c.level]; const g = c.go || {};
        return `<li class="t-${cls}">${icon(ic)}<div><b>${esc(c.title)}</b><span class="faint small">${esc(c.detail || "")}</span></div>${g.team ? `<button type="button" class="btn sm" data-moteam="${g.team}">Open the team</button>` : g.perf ? `<button type="button" class="btn sm" data-moperf="${g.perf}">Performance</button>` : c.key === "usd" && c.level === "info" ? `<button type="button" class="btn sm" data-mogo="settings">Settings</button>` : ""}</li>`; }).join("")}</ul>`
      : `<p class="faint small mo-none">${icon("check")} No budget or performance alert. The Command center's Monitoring lists these with the miner and evaluator checks.</p>`;
    const rows = sp.teams.map(t => { const pct = t.pct == null ? null : Math.min(1, t.pct), tone = t.pct == null ? "" : t.pct >= 1 ? "bad" : t.pct >= s.warn_pct / 100 ? "warn" : "ok";
      return `<tr><td><b>${esc(t.label)}</b> <span class="faint small">${esc(t.name || "")}</span></td><td>${t.paused ? chip(["wait", "Paused"]) : t.autopilot ? chip(["run", "Autopilot"]) : chip(["none", "Manual"])}</td>
        <td class="r num">${t.share != null ? `${fmtNum(t.share * 100, 1)}%` : "–"}</td>
        <td><form class="mo-budget" data-mobudget="${t.id}"><input name="budget" type="number" min="0" max="20000000" step="50000" value="${t.budget}" aria-label="Token budget for ${esc(t.label)}"><button type="submit" class="btn sm">Save</button></form></td>
        <td class="mo-use">${pct == null ? `<span class="faint small">no budget</span>` : `<span class="mo-bar ${tone}"><i style="width:${(pct * 100).toFixed(1)}%"></i></span><span class="num small">${short(t.tokens)} · ${fmtNum(t.pct * 100, 0)}%</span>`}</td>
        <td class="r num">${t.usd != null ? usd(t.usd) : "–"}</td></tr>`; }).join("");
    const camps = sp.campaigns.map(c => `<tr><td><b>${esc(c.label)}</b> <span class="faint small">analyst team</span></td><td colspan="3" class="faint small">snapshots and alerts cost nothing; cycles, answers and briefs use tokens</td><td class="num small">${short(c.tokens)}</td><td class="r num">${c.usd != null ? usd(c.usd) : "–"}</td></tr>`).join("");
    const form = `<form class="mo-set" data-moset>
      <label class="in"><span>Daily cap, every team and campaign together ($)</span><input name="usd_day_cap" type="number" min="0" step="0.5" value="${s.usd_day_cap ?? ""}" placeholder="No cap"></label>
      <label class="in"><span>Warn at (% of a budget or the cap)</span><input name="warn_pct" type="number" min="10" max="100" value="${s.warn_pct}"></label>
      <label class="in"><span>Performance alert when the primary metric falls (%)</span><input name="drop_pct" type="number" min="1" max="90" step="1" value="${s.drop_pct}"></label>
      <label class="mo-check"><input type="checkbox" name="push" ${s.push ? "checked" : ""}> Push alerts to my devices (at most once a day each)</label>
      <p class="fine">Dollars use the token rate from <button type="button" class="linkbtn" data-mogo="settings">Command center → Settings</button>${sp.rate ? ` (now ${usd(sp.rate)} per million tokens)` : " (not set yet)"}. A performance alert needs at least four evaluator reports in 14 days and a fall larger than the noise between them.</p>
      <div class="row"><button type="submit" class="btn primary sm">${icon("check")}Save the alert rules</button></div></form>`;
    const hist = a.history.length ? `<ol class="mo-hist">${a.history.map(h => `<li class="t-${LEVEL[h.level]?.[0] || "none"}"><span class="ci ci-${h.status === "open" ? (h.level === "stop" ? "bad" : "warn") : "none"}"></span>
        <div><b>${esc(h.title)}</b><span class="faint small">${h.status === "open" ? `open since ${esc(when(h.first_seen))}` : `${esc(when(h.first_seen))} – ${esc(when(h.resolved))}`}</span></div></li>`).join("")}</ol>` : `<p class="faint small mo-none">No alert yet.</p>`;
    return `${tiles}<div class="mo-grid">${panel("Alerts now", "shield", checks)}${panel("Alert rules", "sliders", form)}</div>
      ${panel("Budgets by team", "coins", `<div class="tablewrap flat"><table class="grid mini-table mo-table"><thead><tr><th>Team</th><th>Mode</th><th class="r">Emissions</th><th>Tokens / 24 h</th><th>Used, last 24 h</th><th class="r">$ / 24 h</th></tr></thead>
        <tbody>${rows}${camps}</tbody></table></div><p class="fine">A team that reaches its budget starts nothing new until older runs leave the 24-hour window. To share one budget by emission share, use a campaign's <button type="button" class="linkbtn" data-mogo="control">Team control room</button>.</p>`)}
      ${panel("Alert history", "clock", hist)}`;
  }

  // ---------- the project assistant ----------
  function scopes() {
    const out = [["division", "The whole division"]];
    const d = MiningShell.data?.();
    for (const c of d?.campaigns || []) out.push([`campaign:${c.id}`, `Campaign SN${c.netuid} ${c.subnet || ""}`]);
    for (const c of d?.comps || []) out.push([`team:${c.id}`, `Team ${c.label}`]);
    return out;
  }
  async function ask(sc) {
    wire();
    scope = sc || scope || "division";
    let p = $("#mo-ask");
    if (!p) {
      p = document.createElement("aside"); p.id = "mo-ask"; p.className = "mo-ask"; p.setAttribute("aria-label", "Ask AI about this project");
      document.body.append(p);
      p.addEventListener("click", askClick); p.addEventListener("submit", askSubmit); p.addEventListener("change", e => { if (e.target.matches("[data-moscope]")) { scope = e.target.value; loadThread(); } });
      p.addEventListener("keydown", e => { if (e.key === "Escape") closeAsk(); if (e.key === "Enter" && !e.shiftKey && e.target.matches("textarea")) { e.preventDefault(); e.target.form.requestSubmit(); } });
    }
    p.classList.add("open"); document.body.classList.add("mo-ask-on");
    thread = null; drawAsk(); loadThread();
    setTimeout(() => $("textarea", p)?.focus(), 50);
  }
  function closeAsk() { $("#mo-ask")?.classList.remove("open"); document.body.classList.remove("mo-ask-on"); }
  async function loadThread() { try { thread = await api(`${O}/ask?scope=${encodeURIComponent(scope)}`); } catch (e) { err(e); thread = { messages: [] }; } drawAsk(); }
  function drawAsk() {
    const p = $("#mo-ask"); if (!p) return;
    const opts = scopes(); if (!opts.some(([k]) => k === scope)) opts.push([scope, scope]);
    const msgs = thread?.messages || [], lastA = [...msgs].reverse().find(m => m.role === "assistant");
    const draft = $("textarea", p)?.value || "";
    p.innerHTML = `<header class="mo-ask-h"><span class="mxs-mark sm" aria-hidden="true">${icon("sparkle")}</span><div><b>Ask AI</b><span class="faint small">answers from a snapshot of the project; it reads, never changes</span></div>
        <button type="button" class="iconbtn" data-moask="close" aria-label="Close">${icon("close")}</button></header>
      <label class="in mo-ask-scope"><span>About</span><select data-moscope>${opts.map(([k, l]) => `<option value="${esc(k)}" ${k === scope ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
      <div class="mo-ask-list" aria-live="polite">${!thread ? Loading.line("Loading the conversation…") : msgs.length ? msgs.map(m => `<div class="mo-msg ${m.role}">${m.role === "assistant" ? `<div class="md">${Agents.md(m.text)}</div><span class="faint small">${esc(String(m.model || "").split(":").pop())}${m.tokens ? ` · ${short(m.tokens)} tokens` : ""} · ${esc(when(m.ts))}</span>` : `<p>${esc(m.text)}</p>`}</div>`).join("")
        : `<div class="mo-ask-empty"><p>Ask about ${esc(opts.find(([k]) => k === scope)?.[1] || "this project")}: what's blocking it, what changed today, where the budget goes, what to do next.</p></div>`}
        ${asking ? `<div class="mo-msg assistant">${Loading.line("Reading the project…")}</div>` : ""}</div>
      ${!asking && (lastA?.suggestions?.length || !msgs.length) ? `<div class="mo-sugg">${(lastA?.suggestions?.length ? lastA.suggestions : ["What needs me today?", "Why is work stuck?", "Where do the tokens go?"]).map(x => `<button type="button" class="btn sm" data-mosugg="${esc(x)}">${esc(x)}</button>`).join("")}</div>` : ""}
      <form class="mo-ask-f" data-moaskf><textarea name="q" rows="2" maxlength="2000" placeholder="Ask about this project…" aria-label="Your question" ${asking ? "disabled" : ""}>${esc(draft)}</textarea>
        <div class="row"><button type="button" class="linkbtn" data-moask="clear" ${msgs.length ? "" : "hidden"}>Clear the conversation</button><button type="submit" class="btn primary sm" ${asking ? "disabled" : ""}>${icon("send")}Ask</button></div></form>`;
    const l = $(".mo-ask-list", p); l.scrollTop = l.scrollHeight;
  }
  async function send(q) {
    q = (q || "").trim(); if (!q || asking) return;
    asking = true; thread = { ...(thread || {}), messages: [...(thread?.messages || []), { role: "user", text: q }] }; drawAsk();
    const ta = $("#mo-ask textarea"); if (ta) ta.value = "";
    try { thread = await api(`${O}/ask`, { method: "POST", body: { scope, message: q } }); }
    catch (e) { err(e); thread.messages.pop(); }
    asking = false; drawAsk(); $("#mo-ask textarea")?.focus();
  }
  function askClick(e) {
    const a = e.target.closest("[data-moask]");
    if (a?.dataset.moask === "close") return closeAsk();
    if (a?.dataset.moask === "clear") return api(`${O}/ask?scope=${encodeURIComponent(scope)}`, { method: "DELETE" }).then(r => { thread = r; drawAsk(); }).catch(err);
    const s = e.target.closest("[data-mosugg]"); if (s) return send(s.dataset.mosugg);
  }
  function askSubmit(e) { e.preventDefault(); send(e.target.elements.q.value); }

  // ---------- events ----------
  function openTeam(id, sub, task) {
    if (sub) store.set("mw.sub2", sub);
    MiningShell.leave(); MiningWork.openPage(id);
    if (task) setTimeout(() => MiningWork.openTask(task), 600);
  }
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("pointerdown", dragStart);
    document.addEventListener("pointermove", dragMove, { passive: false });
    document.addEventListener("pointerup", dragEnd);
    document.addEventListener("pointercancel", dragEnd);
    document.addEventListener("click", e => {
      if (!host?.contains(e.target)) return;
      const t = e.target;
      if (t.closest("[data-mo=reload]")) return load();
      if (t.closest("[data-mo=pause]")) { paused = !paused; render(); if (!paused) load(); return; }
      if (t.closest("[data-mo=teampage]")) return bwid && openTeam(bwid, "team");
      const ls = t.closest("[data-molsrc]"); if (ls) { lf.src = ls.dataset.molsrc; return render(); }
      const tk = t.closest("[data-motask]"); if (tk && screen === "live") return openTeam(+tk.closest("[data-moteam]").dataset.moteam, "tasks", +tk.dataset.motask);
      const tm = t.closest("[data-moteam]"); if (tm) return openTeam(+tm.dataset.moteam, "tasks");
      const cp = t.closest("[data-mocamp]"); if (cp) { MiningShell.leave(); return Mining.nav({ camp: +cp.dataset.mocamp, tab: "activity" }); }
      const pf = t.closest("[data-moperf]"); if (pf) { MiningShell.leave(); return Mining.nav({ cmd: "perf", wid: +pf.dataset.moperf }); }
      const go = t.closest("[data-mogo]");
      if (go) { MiningShell.leave(); const k = go.dataset.mogo; return Mining.nav(k === "control" ? { tab: "work" } : { cmd: k }); }
      const ex = t.closest("[data-moexp]"); if (ex) return MiningCommand.openExp(+ex.dataset.moexp);
      const mn = t.closest("[data-mominer]"); if (mn) return MiningCommand.openMiner(+mn.dataset.mominer);
      const bw = t.closest("[data-mobw]"); if (bw && !drag) { bwid = +bw.dataset.mobw; store.set("mo.bw", bwid); bview = null; extra = []; render(); return load(); }
      const mv = t.closest("[data-momove], [data-mocopy]");
      if (mv) { const id = +(mv.dataset.momove || mv.dataset.mocopy), to = +$(`[data-moto="${id}"]`, host)?.value; if (!to) return Auth.toast("Pick a team first"); return moveAgent(id, to, !!mv.dataset.mocopy); }
      const hd = t.closest("[data-mohead]"); if (hd) return patchAgent(+hd.dataset.mohead, { head: hd.dataset.on === "true" });
      const on = t.closest("[data-moon]"); if (on) return patchAgent(+on.dataset.moon, { on: on.dataset.on === "true" });
      const rm = t.closest("[data-morm]");
      if (rm) { const a = bview.agents.find(x => x.id === +rm.dataset.morm);
        return UI.confirm({ title: `Take ${esc(a.name)} off the team?`, body: "Their open tasks become yours to reassign.", ok: "Remove",
          run: async () => { bview = await api(`${W}/comps/${bwid}/agents/${a.id}`, { method: "DELETE" }); } }).then(ok => ok && render()); }
    });
    document.addEventListener("change", e => {
      if (!host?.contains(e.target)) return;
      const t = e.target;
      if (t.matches("[data-molwhere]")) { lf.where = t.value; return render(); }
      if (t.matches("[data-mosquad]")) return patchAgent(+t.dataset.mosquad, { squad: t.value });
      if (t.matches("[data-moextra]")) { if (t.value) extra.push(t.value); return render(); }
      if (t.matches("[data-modf]")) { df[t.dataset.modf] = t.value; return render(); }
    });
    document.addEventListener("input", e => {
      if (!host?.contains(e.target)) return;
      if (e.target.matches("[data-molq]")) { lf.q = e.target.value; keep(e.target, "[data-molq]"); }
      if (e.target.matches("[data-modq]")) { df.q = e.target.value; keep(e.target, "[data-modq]"); }
    });
    document.addEventListener("submit", async e => {
      if (!host?.contains(e.target)) return;
      const f = e.target; e.preventDefault();
      const btn = f.querySelector("[type=submit]");
      try {
        btn?.classList.add("loading");
        if (f.matches("[data-moadd]")) await addAgent(f.elements.role.value, f.elements.squad.value);
        if (f.matches("[data-mobudget]")) { await api(`${W}/comps/${f.dataset.mobudget}`, { method: "PATCH", body: { budget: +f.elements.budget.value } }); Auth.toast("Budget saved"); f.blur(); document.activeElement?.blur(); alerts = await api(`${O}/alerts`); render(); MiningShell.refresh(); }
        if (f.matches("[data-moset]")) {
          const v = n => f.elements[n].value;
          alerts = await api(`${O}/alerts/settings`, { method: "PATCH", body: { usd_day_cap: v("usd_day_cap") === "" ? 0 : +v("usd_day_cap"), warn_pct: +v("warn_pct"), drop_pct: +v("drop_pct"), push: f.elements.push.checked } });
          document.activeElement?.blur(); Auth.toast("Alert rules saved"); render(); MiningShell.refresh();
        }
      } catch (x) { err(x); } finally { btn?.classList.remove("loading"); }
    });
  }
  // a filter box keeps its focus and caret through the re-render
  function keep(el, sel) { const [a, b] = [el.selectionStart, el.selectionEnd]; render(); const n = $(sel, host); if (n && document.activeElement !== n) { n.focus(); n.setSelectionRange(a, b); } }

  return { show, hide, ask, closeAsk, SCREENS };
})();
