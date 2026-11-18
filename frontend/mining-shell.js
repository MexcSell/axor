/* My subnets shell (mining-shell.css): one frame around My subnets (#mining) and Competition teams (#teams). A header band with
   the platform's status and three headline counts, a rail that walks the work in five numbered steps (choose, build, run, test, ship) with the other screens folded under More, and a
   search across competitions, teams, agents, experiments, tasks and files. The rail only opens screens that already exist: the
   Command center's sections (mining-command.js), the open campaign's tabs (mining.js), the Competition teams page's tabs
   (mining-work.js), a few platform pages, and the operations screens (mining-ops.js: live operations, team builder, deployment
   history, budgets & alerts), which show in a host beside #mining. Counts come from /api/mining/command; nothing here is
   illustrative. Ask AI opens mining-ops.js's assistant about whatever you're looking at. */
const MiningShell = (() => {
  // [key, label, icon, route, needs]: route is {cmd: section} | {tab: campaign tab} | {teams: sub-tab} | {view: page} | {ops: screen} | {find: true};
  // needs "camp" = only with a campaign, "teams"/a view name = only when that page may be opened
  // Five numbered steps in the order the work happens, then "More" (folded) for everything else. Screens the app sidebar
  // already lists (Subnet explorer, Portfolio) are left out, and Search lives in the band. k values feed counts(): keep them.
  // [num, step, items, more]
  const AREAS = [
    ["1", "Choose a competition", [
      ["dash", "Overview", "dash", { cmd: "dash" }],
      ["comp", "Competitions", "trophy", { cmd: "comp" }],
      ["strategy", "Strategy", "target", { tab: "overview" }, "camp"]]],
    ["2", "Build the team", [
      ["agents", "Your agents", "users", { cmd: "agents" }],
      ["builder", "Team builder", "columns", { ops: "builder" }]]],
    ["3", "Run", [
      ["live", "Live operations", "radio", { ops: "live" }],
      ["teams", "Team tasks", "list", { teams: "tasks" }, "teams"],
      ["control", "Control room", "sliders", { tab: "work" }, "camp"]]],
    ["4", "Test & improve", [
      ["exp", "Experiments", "bulb", { cmd: "exp" }],
      ["lab", "Team evals", "target", { teams: "lab" }, "teams"]]],
    ["5", "Ship & review", [
      ["miners", "Miners", "pickaxe", { cmd: "miners" }],
      ["rewards", "Rewards & costs", "coins", { cmd: "rewards" }]]],
    ["+", "More", [
      ["approvals", "Competition approvals", "hand", { cmd: "approvals" }],
      ["apcenter", "In the Approval Center", "inbox", { view: "approvals", filter: "mining" }, "approvals"],
      ["monitor", "Monitoring", "monitor", { cmd: "monitor" }],
      ["budgets", "Budgets & alerts", "shield", { ops: "budgets" }],
      ["activity", "Campaign activity", "list", { tab: "activity" }, "camp"],
      ["intel", "Competition intelligence", "chart", { tab: "competition" }, "camp"],
      ["mine", "My miners vs goal", "trophy", { tab: "mine" }, "camp"],
      ["perf", "Performance Lab", "chart", { cmd: "perf" }],
      ["collab", "Collaboration diagram", "route", { teams: "diagram" }, "teams"],
      ["analysts", "Analyst workflow", "branch", { tab: "team" }, "camp"],
      ["deploys", "Deployment history", "rocket", { ops: "deploys" }],
      ["files", "File manager", "folder", { teams: "sandbox" }, "teams"],
      ["settings", "Settings", "gear", { cmd: "settings" }],
      ["campset", "Campaign settings", "sliders", { tab: "settings" }, "camp"]], true]];
  const ITEMS = AREAS.flatMap(([n, area, list, more]) => list.map(([k, label, ic, route, needs]) => ({ k, label, ic, route, needs, n, area, more: !!more })));
  const PAGES = ["mining", "teams"];
  let d = null, failed = false, at = 0, req = null, timer = null, frame = 0, agents = null, exps = null, hit = 0, results = [];
  let ops = null, pending = false, wasShown = false, booted = false;  // the operations screen showing in place of #mining (pending: go() asked for it across a page change)

  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const shownPage = () => PAGES.find(p => !$(`#view-${p}`)?.hidden) || null;
  const may = v => { const b = $(`nav.side [data-view="${v}"]`); return !!b && !b.hidden; };
  const keyOf = r => r.cmd ? `cmd:${r.cmd}` : r.tab ? `tab:${r.tab}` : r.teams ? `teams:${r.teams}` : r.view ? `view:${r.view}` : r.ops ? `ops:${r.ops}` : "find";
  const opsHost = () => $("#mo-host");
  const usable = it => it.needs === "camp" ? !!d?.campaigns?.length : it.needs ? may(it.needs) : true;

  // ---------- the frame: built once around each page; the pages render into #mining / #teams as before ----------
  function build() {
    for (const p of PAGES) {
      const sec = $(`#view-${p}`), page = $(`#${p}`);
      if (!sec || !page || $(".mxs", sec)) continue;
      const shell = document.createElement("div");
      shell.className = `mxs${store.get("mxs.fold", false) ? " fold" : ""}`; shell.dataset.page = p;
      shell.innerHTML = `<aside class="mxs-rail" aria-label="My subnets areas"><div class="mxs-rail-in"></div></aside><div class="mxs-scrim" data-mxs="sheet"></div>
        <div class="mxs-main"><header class="mxs-head"></header></div>`;
      sec.prepend(shell);
      $(".mxs-main", shell).append(page);
      if (p === "mining") { const h = document.createElement("div"); h.id = "mo-host"; h.hidden = true; $(".mxs-main", shell).append(h); }
      shell.addEventListener("click", click);
    }
    // a page showing or hiding: sync the frame and start or stop the counts
    const watch = new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(sync); });
    PAGES.forEach(p => { const s = $(`#view-${p}`); if (s) watch.observe(s, { subtree: true, childList: true, attributes: true, attributeFilter: ["hidden", "aria-pressed"] }); });
  }

  // where you are, read from the page itself so the pages need not report it
  function here() {
    const p = shownPage();
    if (p === "mining") {
      if (ops) return `ops:${ops}`;
      const c = $("#mining .mcx-tabs [aria-pressed=true]"); if (c) return `cmd:${c.dataset.mcgo}`;
      const t = $("#mining .mh-tabs-wrap [aria-pressed=true]"); if (t) return `tab:${t.dataset.mhtab}`;
      return $("#mining .mh-camp-cmd.on") ? "cmd:dash" : "";
    }
    if (p === "teams") { const s = `teams:${store.get("mw.sub2", "status")}`; return ITEMS.some(i => keyOf(i.route) === s) ? s : "teams:tasks"; }
    return "";
  }

  function sync() {
    const p = shownPage();
    // My subnets opening: an operations screen stays only when go() asked for it (or, on the first load, when it was open last time)
    // first: My subnets opening as the page loads (a reload), not later from another page
    const arrived = p === "mining" && !wasShown, first = arrived && !booted && performance.now() < 15000;
    wasShown = p === "mining"; if (arrived) booted = true;
    if (arrived) {
      if (pending) { pending = false; return openOps(ops); }
      const last = store.get("mxs.ops", null);
      if (first && last) return openOps(last);
      leave();
    }
    if (!p) { clearTimeout(timer); timer = null; return; }
    if (!timer || Date.now() - at > 60000) load();
    const now = here(), cur = ITEMS.find(i => keyOf(i.route) === now);
    for (const shell of $$(".mxs")) {
      if (shell.dataset.page !== p) continue;
      put($(".mxs-rail-in", shell), rail(now));
      put($(".mxs-head", shell), head(cur));
    }
  }

  function rail(now) {
    const n = counts(), fold = $(".mxs")?.classList.contains("fold");
    const btn = i => { const on = keyOf(i.route) === now, ok = usable(i), c = n[i.k];
      return `<button type="button" class="mxs-item${on ? " on" : ""}" data-mxsgo="${i.k}" ${on ? `aria-current="page"` : ""} ${ok ? `title="${esc(i.label)}${i.route.view ? " (opens its page)" : ""}"` : `disabled title="Start a campaign first"`}>
        ${icon(i.ic)}<span class="mxs-l">${esc(i.label)}</span>${i.route.view ? `<span class="mxs-out" aria-hidden="true">${icon("external")}</span>` : ""}${c ? `<span class="mxs-c ${c[1]}">${c[0]}</span>` : ""}</button>`; };
    return `<div class="mxs-rail-top"><span class="mxs-rail-t">Workflow</span>
        <button type="button" class="mxs-fold" data-mxs="fold" title="${fold ? "Expand the rail" : "Fold the rail to icons"}" aria-label="${fold ? "Expand the rail" : "Fold the rail to icons"}">${icon("sidebar")}</button></div>
      ${AREAS.map(([num, area, list, more]) => {
        const items = ITEMS.filter(i => i.area === area && (i.needs === "camp" || !i.needs || may(i.needs)));
        if (!items.length) return "";
        if (!more) return `<div class="mxs-area"><div class="mxs-area-h"><span class="mxs-num">${num}</span><span>${esc(area)}</span></div>${items.map(btn).join("")}</div>`;
        // More: folded unless opened, or unless you're on one of its screens; folded, it carries the sum of its counts in the worst tone
        const open = store.get("mxs.more", false) || items.some(i => keyOf(i.route) === now);
        const cs = items.map(i => n[i.k]).filter(Boolean), sum = cs.reduce((t, c) => t + c[0], 0);
        const tone = ["bad", "warn", "run", "info"].find(t => cs.some(c => c[1] === t));
        return `<div class="mxs-area mxs-more${open ? " open" : ""}"><button type="button" class="mxs-area-h mxs-more-h" data-mxs="more" aria-expanded="${open}" title="${open ? "Hide" : "Show"} the other ${items.length} screens">
            <span class="mxs-num">+</span><span>More</span>${!open && sum ? `<span class="mxs-c ${tone}">${sum}</span>` : ""}<span class="mxs-chev" aria-hidden="true">${icon(open ? "chev" : "right")}</span></button>
          ${open ? items.map(btn).join("") : ""}</div>`;
      }).join("")}`;
  }
  // a rail item's count: [n, tone]
  function counts() {
    if (!d) return {};
    const waiting = d.comps.reduce((s, c) => s + (c.waiting || 0), 0), working = d.comps.reduce((s, c) => s + (c.working || 0), 0);
    const out = {};
    if (d.approvals_n) out.approvals = [d.approvals_n, "warn"];
    if (d.critical.length) out.monitor = [d.critical.length, "bad"];
    const money = d.critical.filter(c => ["budget", "performance"].includes(c.kind)).length;
    if (money) out.budgets = [money, "bad"];
    if (waiting) out.teams = [waiting, "warn"];
    if (working) out.agents = [working, "run"];
    const ex = Object.values(d.experiments || {}).reduce((a, b) => a + b, 0);
    if (ex) out.exp = [ex, "info"];
    // the open campaign's own counts, from its tab row (hidden on wide screens, where the rail replaces it)
    for (const [k, t] of [["strategy", "overview"], ["mine", "mine"], ["control", "work"]]) {
      const n = parseInt($(`#mining .mh-tabs-wrap [data-mhtab="${t}"] .hq-n`)?.textContent, 10);
      if (n) out[k] = [n, k === "mine" ? "bad" : "warn"];
    }
    return out;
  }

  // ---------- the header band ----------
  function status() {
    if (failed && !d) return ["bad", "Offline", "Can't reach the server"];
    if (!d) return ["none", "Connecting", "Reading the division…"];
    if (failed) return ["warn", "Reconnecting", `Last update ${ago(at / 1000)}`];
    const live = d.campaigns.filter(c => c.status === "live").length, working = d.comps.reduce((s, c) => s + (c.working || 0), 0);
    if (!d.campaigns.length) return ["none", "Standby", "No campaign yet"];
    if (!live) return ["warn", "Paused", `${plural(d.campaigns.length, "campaign")}, all paused`];
    return ["ok", "Online", `${plural(live, "campaign")} live${working ? ` · ${plural(working, "agent")} working` : ""}${d.evaluators ? ` · ${plural(d.evaluators, "evaluator")}` : ""}`];
  }
  function head(cur) {
    const [tone, word, line] = status(), open = d ? d.comps.filter(c => c.status !== "closed") : [];
    const active = open.reduce((s, c) => s + (c.active || 0), 0), working = open.reduce((s, c) => s + (c.working || 0), 0);
    const camp = cur?.needs === "camp" ? d?.campaigns.find(c => c.id === store.get("mh.cid", null)) || d?.campaigns[0] : null;
    const two = n => n == null ? "–" : String(n).padStart(2, "0");
    const stat = (label, v, sub, go, t = "") => `<button type="button" class="mxs-stat ${t}" data-mxsgo="${go}"><span>${label}</span><b>${v}</b><small>${sub}</small></button>`;
    return `<div class="mxs-hg"><div class="mxs-brand"><button type="button" class="mxs-menu" data-mxs="sheet" aria-label="My subnets areas">${icon("menu")}</button>
        <span class="mxs-mark" aria-hidden="true">${icon("pickaxe")}</span>
        <div class="mxs-id"><h1>My subnets</h1><span class="mxs-tag">AI mining operations platform</span></div></div>
      <div class="mxs-stats">
        ${stat("Active competitions", d ? two(open.length) : "–", d ? `${plural(d.campaigns.length, "campaign")}` : "", "comp")}
        ${stat("Agents assigned", d ? two(active) : "–", d ? `${working} running now · open competitions` : "", "agents", working ? "run" : "")}
        ${stat("Competition approvals", d ? two(d.approvals_n) : "–", d ? `${d.critical.length ? plural(d.critical.length, "critical check") : "0 critical"} · My subnets only` : "", "approvals", d?.approvals_n ? "warn" : d?.critical.length ? "bad" : "")}</div>
      <nav class="mxs-crumb" aria-label="You are here">${shownPage() === "teams" ? teamCrumb() : cur ? `<span class="mxs-num">${cur.n}</span>${esc(AREAS.find(a => a[0] === cur.n)[1])}${icon("right")}<b>${esc(cur.label)}</b>${camp ? `<span class="mxs-crumb-c">SN${camp.netuid} ${esc(camp.comp || camp.subnet || "")}</span>` : ""}` : `<b>My subnets</b>`}</nav>
      <div class="mxs-tools"><span class="mxs-status t-${tone}" title="${esc(line)}"><i></i>${word}<span class="mxs-status-l">${esc(line)}</span></span>
        <button type="button" class="mxs-find" data-mxsgo="find">${icon("search")}<span>Find a competition, agent, task…</span></button>
        <button type="button" class="mxs-ask" data-mxs="ask" title="Ask AI about what's on screen">${icon("sparkle")}<span>Ask AI</span></button></div></div>`;
  }

  // the one path to a team (the 11-07 evaluation): My subnets › SN62 subnet › Competition 28 (the app's crumb adds Ecosystems › Bittensor)
  function teamCrumb() {
    const v = typeof MiningWork !== "undefined" && MiningWork.view ? MiningWork.view() : null;
    if (!v?.comp) return `<span>My subnets</span>${icon("right")}<b>Competition teams</b>`;
    const sn = v.campaign ? `SN${v.campaign.netuid}${v.campaign.subnet ? ` ${v.campaign.subnet}` : ""}` : "";
    return `<span>My subnets</span>${icon("right")}${sn ? `<span>${esc(sn)}</span>${icon("right")}` : ""}<b>${esc(v.comp.number != null ? `Competition ${v.comp.number}` : v.comp.label || "Team")}</b>`;
  }

  // ---------- the counts ----------
  function load() {
    clearTimeout(timer);
    timer = setTimeout(() => { if (shownPage() && document.visibilityState === "visible") load(); else timer = null; }, 60000);
    if (req || !Auth.me()) return req;
    return req = api("/api/mining/command").then(r => { d = r; failed = false; }).catch(() => { failed = true; })
      .finally(() => { req = null; at = Date.now(); sync(); });
  }

  // ---------- going somewhere ----------
  function go(r) {
    closeSheet();
    if (r.find) return find();
    if (r.ops) {
      store.set("mxs.ops", r.ops);
      if (shownPage() !== "mining") { pending = true; ops = r.ops; return setView("mining"); }
      return openOps(r.ops);
    }
    leave();
    if (r.view) { if (r.filter && typeof Command !== "undefined" && Command.filter) Command.filter(r.filter); return setView(r.view); }
    if (r.teams) { MiningWork.go(r.teams); if (r.team) return MiningWork.openPage(r.team); return shownPage() === "teams" ? null : MiningWork.openPage(); }
    return Mining.nav(r);
  }
  function click(e) {
    const g = e.target.closest("[data-mxsgo]");
    if (g) { if (g.dataset.mxsgo === "find") return find(); const it = ITEMS.find(i => i.k === g.dataset.mxsgo); if (it && usable(it)) go(it.route); return; }
    const a = e.target.closest("[data-mxs]"); if (!a) return;
    if (a.dataset.mxs === "fold") {
      const fold = !$(".mxs").classList.contains("fold");
      $$(".mxs").forEach(s => s.classList.toggle("fold", fold)); store.set("mxs.fold", fold);
      $$(".mxs-rail-in").forEach(r => { r.dataset.html = ""; }); sync();
    }
    if (a.dataset.mxs === "more") { store.set("mxs.more", a.getAttribute("aria-expanded") !== "true"); $$(".mxs-rail-in").forEach(r => { r.dataset.html = ""; }); sync(); }
    if (a.dataset.mxs === "sheet") $$(".mxs").forEach(s => s.classList.toggle("sheet"));
    if (a.dataset.mxs === "ask") MiningOps.ask(askScope());
  }
  const closeSheet = () => $$(".mxs.sheet").forEach(s => s.classList.remove("sheet"));
  function openOps(s) {
    const h = opsHost(); if (!h || !MiningOps.SCREENS[s]) return leave();
    ops = s; $("#mining").hidden = true; h.hidden = false;
    MiningOps.show(s, h); sync(); scrollTo({ top: 0 });
  }
  // back to the My subnets page itself: every route that isn't an operations screen calls this
  function leave() {
    if (!ops && opsHost()?.hidden !== false) return;
    ops = null; store.set("mxs.ops", null); MiningOps.hide();
    const h = opsHost(); if (h) h.hidden = true;
    const m = $("#mining"); if (m) m.hidden = false;
  }
  // what Ask AI is about: the team or campaign on screen, else the whole division
  function askScope() {
    const p = shownPage();
    if (p === "teams") { const v = MiningWork.view(); return v ? `team:${v.comp.id}` : "division"; }
    const now = here();
    if (["cmd:comp", "cmd:perf"].includes(now) && store.get("mc.wid", null)) return `team:${store.get("mc.wid", null)}`;
    if (now.startsWith("tab:") && store.get("mh.cid", null)) return `campaign:${store.get("mh.cid", null)}`;
    return "division";
  }

  // ---------- search: screens, campaigns, competition teams, agents, experiments, and the open team's tasks and files ----------
  function find() {
    let dlg = $("#mxs-find");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "mxs-find"; dlg.className = "mxs-find-dlg";
      dlg.innerHTML = `<div class="mxs-find-in"><label class="mxs-q">${icon("search")}<input type="search" placeholder="Find a competition, agent, experiment, task, file or screen" aria-label="Search My subnets" autocomplete="off" role="combobox" aria-controls="mxs-res" aria-expanded="true"></label>
        <div class="mxs-res" id="mxs-res" role="listbox"></div><p class="mxs-find-f faint small"><kbd>↑</kbd><kbd>↓</kbd> choose · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close</p></div>`;
      document.body.append(dlg);
      const q = $("input", dlg);
      q.addEventListener("input", () => { hit = 0; list(q.value); });
      q.addEventListener("keydown", e => {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); hit = (hit + (e.key === "ArrowDown" ? 1 : -1) + results.length) % Math.max(1, results.length); list(q.value); }
        if (e.key === "Enter") { e.preventDefault(); pick(hit); }
      });
      dlg.addEventListener("click", e => { if (e.target === dlg) return dlg.close(); const o = e.target.closest("[data-mxsr]"); if (o) pick(+o.dataset.mxsr); });
    }
    const q = $("input", dlg); q.value = ""; hit = 0; list("");
    dlg.showModal(); q.focus();
    // agents and experiments load on the first search, then refresh at most every two minutes
    if (!agents || Date.now() - agents.at > 120000) Promise.all([api("/api/mining/command/agents").catch(() => null), api("/api/mining/command/experiments").catch(() => null)])
      .then(([a, x]) => { agents = { at: Date.now(), list: a?.agents || [] }; exps = x?.experiments || []; if (dlg.open) list(q.value); });
  }
  function entries(q) {
    q = q.trim().toLowerCase();
    const has = (...t) => !q || t.some(x => String(x ?? "").toLowerCase().includes(q));
    const out = [];
    for (const i of ITEMS) if (i.k !== "find" && usable(i) && (i.needs === "camp" || !i.needs || may(i.needs)) && has(i.label, i.area))
      out.push({ sec: "Screens", ic: i.ic, name: i.label, hint: `${i.n} · ${i.area}`, run: () => go(i.route) });
    for (const c of d?.campaigns || []) if (has(`sn${c.netuid}`, c.netuid, c.subnet, c.comp))
      out.push({ sec: "Campaigns", ic: "trophy", name: `SN${c.netuid} ${c.subnet || ""}`, hint: `${c.comp || ""}${c.best_rank ? ` · #${c.best_rank}` : ""}`, run: () => Mining.nav({ camp: c.id, tab: "overview" }) });
    for (const c of d?.comps || []) if (has(`sn${c.netuid}`, c.label, c.name, c.number, c.subnet)) {
      out.push({ sec: "Competition teams", ic: "users", name: c.label, hint: `SN${c.netuid} · ${plural(c.agents || 0, "agent")}${c.working ? ` · ${c.working} working` : ""}`, run: () => go({ teams: "tasks", team: c.id }) });
      if (q) out.push({ sec: "Competition teams", ic: "trophy", name: `${c.label}: My subnets`, hint: "Command center", run: () => Mining.nav({ cmd: "comp", wid: c.id }) });
    }
    if (q) {
      for (const a of agents?.list || []) if (has(a.name, a.title, a.squad, a.role)) out.push({ sec: "Agents", ic: a.icon || "bot", name: a.name, hint: `${a.title || ""} · ${a.team_label}${a.status === "working" ? " · working" : ""}`, run: () => go({ teams: "team", team: a.team }) });
      for (const x of exps || []) if (has(x.title, x.comp, x.stage)) out.push({ sec: "Experiments", ic: "bulb", name: x.title || `Experiment #${x.id}`, hint: `${x.comp || ""} · ${x.stage || x.status || ""}`, run: () => Mining.nav({ cmd: "exp" }) });
      const v = MiningWork.view();
      if (v) {
        for (const t of v.tasks || []) if (has(t.title)) out.push({ sec: `Tasks · ${v.comp.label}`, ic: "list", name: t.title, hint: t.status, run: () => { go({ teams: "tasks", team: v.comp.id }); MiningWork.openTask(t.id); } });
        for (const f of v.files || []) if (has(f.path)) out.push({ sec: `Files · ${v.comp.label}`, ic: "file", name: f.path, hint: "", run: () => go({ teams: "sandbox", team: v.comp.id }) });
      }
    }
    return out.slice(0, 60);
  }
  function list(q) {
    results = entries(q);
    let last = "";
    put($("#mxs-res"), results.length ? results.map((r, i) => {
      const h = r.sec !== last ? `<div class="mxs-res-h">${esc(r.sec)}</div>` : ""; last = r.sec;
      return `${h}<button type="button" class="mxs-r${i === hit ? " on" : ""}" role="option" aria-selected="${i === hit}" data-mxsr="${i}">${icon(r.ic)}<span>${esc(r.name)}</span><small>${esc(r.hint || "")}</small></button>`;
    }).join("") : `<p class="faint small mxs-none">Nothing matches “${esc(q)}”.${agents ? "" : " Agents are still loading."}</p>`);
    $("#mxs-res .mxs-r.on")?.scrollIntoView({ block: "nearest" });
  }
  function pick(i) { const r = results[i]; if (!r) return; $("#mxs-find").close(); r.run(); }

  // app.js (store, setView) loads last: build once every script has run
  const start = () => { build(); sync(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else setTimeout(start, 0);
  return { sync, find, refresh: () => load(), leave, data: () => d, go };
})();
