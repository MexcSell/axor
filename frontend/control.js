/* Control Hub (control_hub.py, /api/control, view #control; prefix ctl-): AXoR run from one place, over one hierarchy:
   Organization → Departments → Teams → Agents.
   - The sidebar's Organization tree: expand and collapse each level, status dots, the ⋯ menu (or right-click) for a node's actions.
     A subnet is a department (Bittensor), a Competition team is a team; every other top unit of the organization is a department.
   - Selecting a node opens its context here: the organization → its departments; a department → its teams; a team → its agents,
     its mission (a Competition team's predefined mission: target rank and the gap), its tasks and history; an agent → its workspace (conversation, execution,
     knowledge, profile) with text, voice, pictures, camera, video, files, web search and context to inject.
   - The hub itself (no node, or the Control Hub entry): overview, missions, tasks, agents, teams, resources, approvals, alerts,
     performance and audit, from every system at once. Missions (predefined: a Bittensor competition; custom: Mission Control)
     and tasks (fixed / dynamic) are control-missions.js; Bittensor is the primary initiative.
   - The mission wizard (a Bittensor mission): subnet → discover → select → configure → workforce → validate → activate.
   - Manual / Hybrid / Auto: how much AXoR staffs on its own (the top right switch). */
const Control = (() => {
  const B = "/api/control";
  const SECTIONS = [["overview", "dash", "Overview"], ["missions", "target", "Missions"], ["tasks", "list", "Tasks"], ["agents", "bot", "Agent operations"], ["teams", "users", "Team operations"],
                    ["resources", "coins", "Resources"], ["approvals", "inbox", "Approvals"], ["alerts", "alert", "Monitoring & alerts"],
                    ["performance", "chart", "Performance"], ["audit", "clock", "Audit"],
                    ["journeys", "route", "Journeys"], ["routing", "chips", "Model routing"]];  // control-journey.js
  // [key, icon, label, its sections, the full page it also opens]
  const AREAS = [["overview", "dash", "Overview", ["overview", "performance", "resources", "routing"]], ["live", "radio", "Live operations", ["missions", "tasks", "journeys", "agents", "teams"]],
                 ["notify", "bell", "Notifications", ["alerts"], "notifications"], ["approve", "inbox", "Approval Center", ["approvals", "audit"], "approvals"]];
  const SYS = { company: "Company", workforce: "Workforce", hub: "Your agents", teams: "Competition team" };
  const MODE = { manual: ["hand", "Manual"], hybrid: ["users", "Hybrid"], auto: ["zap", "Auto"] };
  const TSTAT = { proposed: ["new", "Proposed"], skipped: ["muted", "Skipped"], todo: ["new", "To do"], running: ["clear", "Running"], review: ["caution", "For your review"], needs_input: ["caution", "Needs you"],
                  done: ["clear", "Done"], failed: ["scam", "Failed"], cancelled: ["muted", "Cancelled"] };
  const REQS = ["Sandbox tests pass before review", "Your approval before any deploy", "A daily report to you", "Stay within the daily budget"];
  let tree = null, hubD = null, cur = null, sec = "overview", nodeD = null, wsD = null, wsTab = "chat", on = false, timer = null, poll = null, treeTimer = null;
  const media = { images: [], audio: null, video: "", web: false, ctx: new Set(["team"]), speak: false };
  let lastSpoken = 0, rec = null;
  const S_ = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("ctl." + k)); localStorage.setItem("ctl." + k, JSON.stringify(v)); } catch { return null; } };
  const open_ = new Set(S_("open") || ["org", "bittensor"]);
  const root = () => document.getElementById("ctl");
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const tok = n => n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(n);
  const badge = (tone, text, ic = "") => `<span class="badge ${tone}">${ic ? icon(ic) : ""}${esc(text)}</span>`;
  const initials = s => String(s || "?").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const av = (a, cls = "") => `<span class="ctl-av s-${esc(a?.system || "x")} ${cls}" aria-hidden="true">${esc(initials(a?.name))}</span>`;
  const dot = st => `<i class="ctl-dot d-${esc(st || "idle")}" aria-hidden="true"></i>`;
  const STL = { ok: "Active", busy: "Working now", warn: "Something failed lately", stop: "Its last run failed", idle: "Nobody yet", off: "Off" };
  const when = ts => ts ? ago(ts) : "";
  const md = t => (typeof Agents !== "undefined" && Agents.md) ? Agents.md(t || "") : `<p>${esc(t || "")}</p>`;
  const shortTeam = (name, d) => d && d.kind === "subnet" ? name.replace(/^SN\d+ · /, "") : name;

  // ---------- data ----------
  // someone who may not use agents (or a server without the Organization) keeps the classic Command Center as the overview
  let off = false;
  function unavailable(e) {
    if (e?.status !== 403 && e?.status !== 409) return false;
    off = true;
    const b = $("#nav-command"); if (b) { b.dataset.view = "command"; b.querySelector(".lbl").textContent = "Overview"; }
    return true;
  }
  async function loadTree(fresh) {
    try { tree = await api(`${B}/tree${fresh ? "?fresh=1" : ""}`); drawTree(); }
    catch (e) { tree = null; const t = $("#ctl-tree"); if (t) t.innerHTML = ""; if (unavailable(e) && S.view === "control" && !cur) setView("command"); }
    return tree;
  }
  const allDepts = () => tree ? [...(tree.bittensor?.departments || []), ...tree.departments] : [];
  const findTeam = ref => { for (const d of allDepts().concat(tree?.bittensor ? [tree.bittensor] : [])) for (const t of d.teams || []) if (t.id === ref) return [t, d]; return [null, null]; };
  const findAgent = key => { for (const d of allDepts()) { for (const t of d.teams) { const a = t.agents.find(x => x.key === key); if (a) return a; } const s = (d.staff || []).find(x => x.key === key); if (s) return s; }
                             return (tree?.bittensor?.staff || []).concat(tree?.unplaced || []).find(x => x.key === key) || (tree?.org.ceo?.key === key ? tree.org.ceo : null); };

  // ---------- the sidebar tree ----------
  function row(id, depth, label, { kids = false, st = null, count = "", ic = "", sub = "", menu = true, title = "" } = {}) {
    const isOpen = open_.has(id), sel = cur === id;
    return `<div class="ctl-row ${sel ? "on" : ""}" style="--d:${depth}">
      ${kids ? `<button type="button" class="ctl-tw" data-tw="${esc(id)}" aria-label="${isOpen ? "Collapse" : "Expand"} ${esc(label)}" aria-expanded="${isOpen}">${icon("chev")}</button>` : `<span class="ctl-tw-gap"></span>`}
      <button type="button" class="ctl-node" data-node="${esc(id)}" role="treeitem" aria-level="${depth + 1}" aria-selected="${sel}" ${kids ? `aria-expanded="${isOpen}"` : ""} title="${esc(title || label)}">
        ${ic ? icon(ic) : ""}<span class="ctl-lbl">${esc(label)}</span>${sub ? `<small>${esc(sub)}</small>` : ""}${st ? dot(st) : ""}${count !== "" && count != null ? `<b class="ctl-n">${esc(String(count))}</b>` : ""}</button>
      ${menu ? `<button type="button" class="ctl-more" data-menu="${esc(id)}" aria-label="Actions for ${esc(label)}" aria-haspopup="menu">${icon("dots")}</button>` : ""}</div>`;
  }
  const kidsWrap = (id, html) => open_.has(id) ? `<div class="ctl-kids" role="group">${html}</div>` : "";
  function agentRows(list, depth) {
    return list.map(a => row(`agent:${a.key}`, depth, a.name, { st: a.status, ic: "", sub: a.assigned ? "assigned" : "", title: `${a.name} · ${a.title}${a.assigned ? " (assigned here)" : ""} · ${STL[a.status] || ""}` })).join("");
  }
  function teamRows(t, depth, d) {
    const id = t.id;
    return row(id, depth, shortTeam(t.name, d), { kids: t.agents.length > 0, st: t.status, ic: t.kind === "competition" ? "trophy" : "users",
                                                  count: t.agents.length || "", title: `${t.name}${t.fixed?.target_rank ? ` · target top ${t.fixed.target_rank}` : ""}` })
      + kidsWrap(id, agentRows(t.agents, depth + 1));
  }
  function deptRows(d, depth) {
    const staffId = `staff:${d.id}`;
    const inner = d.teams.map(t => teamRows(t, depth + 1, d)).join("")
      + (d.staff?.length ? row(staffId, depth + 1, "Department staff", { kids: true, ic: "group", count: d.staff.length, menu: false, title: "Placed in the department, in no team" }) + kidsWrap(staffId, agentRows(d.staff, depth + 2)) : "");
    return row(d.id, depth, d.name, { kids: !!inner, st: d.status, ic: d.kind === "subnet" ? "pickaxe" : d.kind === "exec" ? "star" : d.kind === "division" ? "layers" : "group",
                                      count: d.teams.length || "", title: `${d.name} · ${plural(d.teams.length, "team")}` }) + kidsWrap(d.id, inner);
  }
  function drawTree() {
    const el = $("#ctl-tree"); if (!el) return;
    if (!tree) { el.innerHTML = ""; return; }
    const bt = tree.bittensor;
    let h = row("org", 0, tree.org.name || "Organization", { kids: true, ic: "branch", count: tree.org.pending || "", title: "The organization: its departments" });
    let inner = "";
    if (bt) {
      const bin = bt.departments.map(d => deptRows(d, 2)).join("") + bt.teams.map(t => teamRows(t, 2, null)).join("")
        + (bt.staff.length ? row("staff:bittensor", 2, "Division staff", { kids: true, ic: "group", count: bt.staff.length, menu: false }) + kidsWrap("staff:bittensor", agentRows(bt.staff, 3)) : "");
      inner += row("bittensor", 1, bt.name, { kids: true, ic: "layers", title: `${bt.name}: ${plural(bt.departments.length, "subnet")}, a department per subnet and a team per competition` }) + kidsWrap("bittensor", bin);
    }
    inner += tree.departments.map(d => deptRows(d, 1)).join("");
    if (tree.unplaced.length) inner += row("staff:unplaced", 1, "Not placed", { kids: true, ic: "users", count: tree.unplaced.length, menu: false, title: "Agents in no department yet" }) + kidsWrap("staff:unplaced", agentRows(tree.unplaced, 2));
    h += kidsWrap("org", inner);
    if (el.dataset.html !== h) { el.innerHTML = h; el.dataset.html = h; }
  }
  function toggle(id) { open_.has(id) ? open_.delete(id) : open_.add(id); S_("open", [...open_]); drawTree(); }
  function wireTree() {
    const el = $("#ctl-tree"); if (!el || el.dataset.wired) return;
    el.dataset.wired = "1";
    el.addEventListener("click", e => {
      const tw = e.target.closest("[data-tw]"); if (tw) return toggle(tw.dataset.tw);
      const m = e.target.closest("[data-menu]"); if (m) { e.stopPropagation(); return menu(m.dataset.menu, m); }
      const n = e.target.closest("[data-node]"); if (!n) return;
      const id = n.dataset.node;
      if (id.startsWith("staff:")) return toggle(id);
      if (!open_.has(id) && n.hasAttribute("aria-expanded")) { open_.add(id); S_("open", [...open_]); }
      go(id);
    });
    el.addEventListener("contextmenu", e => { const n = e.target.closest("[data-node]"); if (!n || n.dataset.node.startsWith("staff:")) return; e.preventDefault(); menu(n.dataset.node, n); });
    el.addEventListener("keydown", e => {  // arrows walk the tree, ← / → fold and unfold
      const n = e.target.closest("[data-node]"); if (!n) return;
      const all = $$("[data-node]", el), i = all.indexOf(n);
      if (e.key === "ArrowDown" && all[i + 1]) { e.preventDefault(); all[i + 1].focus(); }
      else if (e.key === "ArrowUp" && all[i - 1]) { e.preventDefault(); all[i - 1].focus(); }
      else if ((e.key === "ArrowRight" && !open_.has(n.dataset.node)) || (e.key === "ArrowLeft" && open_.has(n.dataset.node))) {
        if (n.hasAttribute("aria-expanded")) { e.preventDefault(); toggle(n.dataset.node); requestAnimationFrame(() => $(`[data-node="${CSS.escape(n.dataset.node)}"]`, el)?.focus()); }
      }
    });
  }
  // the node's actions (⋯ or right-click)
  function menu(id, btn) {
    document.querySelector(".ctl-menu")?.remove();
    const items = [];
    const add = (ic, label, fn) => items.push([ic, label, fn]);
    if (id === "org") { add("dash", "Open Control Hub", () => go(null)); add("plus", "New department", deptDlg); add("trophy", "New Bittensor mission", () => wizard()); }
    else if (id === "bittensor") { add("eye", "Open", () => go(id)); add("trophy", "New Bittensor mission", () => wizard()); }
    else if (id.startsWith("sn:")) { const n = +id.slice(3); add("eye", "Open", () => go(id)); add("trophy", "New competition team", () => wizard({ netuid: n })); add("pickaxe", "Open in My subnets", () => setView("mining")); }
    else if (id.startsWith("u:")) {
      const [t] = findTeam(id);
      add("eye", "Open", () => go(id));
      if (t) {
        add("userplus", "Add an agent", () => memberDlg(id)); add("sparkle", "Recommend agents", () => recDlg(id)); add("list", "New task", () => taskDlg(id));
        if (t.comp_id) { add("target", "Configure mission", () => fixedDlg(t)); add("eye", "Open mission", () => CtlMissions.openMission(`comp:${t.comp_id}`)); add("external", "Open the team's board", () => MiningWork.openPage(t.comp_id)); }
        add("edit", "Rename", () => renameDlg(id, t.name));
      } else { add("plus", "New team", () => teamDlg(id)); add("edit", "Rename", () => renameDlg(id, allDepts().find(d => d.id === id)?.name || "")); add("trash", "Dissolve", () => dissolve(id)); }
    }
    else if (id.startsWith("agent:")) { const k = id.slice(6); add("chat", "Open workspace", () => go(id)); add("list", "Execution", () => { wsTab = "exec"; go(id); }); }
    const pop = document.createElement("div");
    pop.className = "popover ctl-menu"; pop.setAttribute("role", "menu");
    pop.innerHTML = items.map(([ic, l], i) => `<button type="button" class="mi" role="menuitem" data-i="${i}">${icon(ic)}<span><b>${esc(l)}</b></span></button>`).join("");
    document.body.append(pop);
    const r = btn.getBoundingClientRect();
    pop.style.top = `${Math.min(r.bottom + scrollY + 4, scrollY + innerHeight - pop.offsetHeight - 8)}px`;
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 16))}px`;
    pop.querySelector("button")?.focus();
    pop.onclick = e => { const b = e.target.closest("[data-i]"); if (!b) return; pop.remove(); items[+b.dataset.i][2](); };
    pop.onkeydown = e => { if (e.key === "Escape") { pop.remove(); btn.focus(); } };
    setTimeout(() => document.addEventListener("click", function off(ev) { if (!pop.contains(ev.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
  }

  // ---------- navigation ----------
  function go(id) {
    cur = id || null;
    const h = cur ? `#control/${cur}` : "#control";
    if (location.hash !== h) history.replaceState(null, "", h);
    if (S.view !== "control") setView("control"); else render(true);
    drawTree();
    if (innerWidth <= 900) sideOpen(false);
  }
  function route(h) { const m = /^control\/(.+)$/.exec(h || ""); cur = m ? decodeURIComponent(m[1]) : null; }
  let classicNext = false;
  const classic = () => { const c = classicNext || off; classicNext = false; return c; };  // one setView("command") that opens the classic Command Center
  async function open() {
    on = true;
    if (cur) history.replaceState(null, "", `#control/${cur}`);  // setView wrote #control: keep the node in the link
    if (!tree) await loadTree();
    render(true);
    clearInterval(timer); timer = setInterval(() => { if (on && !document.hidden && !dlgOpen()) render(false); }, 20000);
    clearInterval(clockT); clockT = setInterval(tick, 1000);  // the Command Center's clock
  }
  function stop() { on = false; clearInterval(timer); clearInterval(clockT); clearTimeout(poll); stopMedia(); if (typeof CtlScene !== "undefined") CtlScene.leave(); }
  let clockT = null;
  function tick() {
    const el = root(); if (!on || !el || cur) return;
    const c = el.querySelector("[data-ctl-clock]"); if (c) c.textContent = clockText();
    const t = el.querySelector("[data-ctl-at]"); if (t && hubD) t.textContent = `Updated ${ago(hubD.at)}`;
  }
  const dlgOpen = () => document.getElementById("ctl-dlg")?.open;

  async function render(full) {
    const el = root(); if (!el) return;
    if (full && !el.innerHTML) el.innerHTML = `<div class="ctl"><div class="ctl-loading">${icon("cycle")}Loading…</div></div>`;
    try {
      if (!cur) { hubD = await api(B); if (!full && sec === "overview" && typeof CtlScene !== "undefined" && CtlScene.live(root())) return CtlScene.update(hubD); return draw(hubView()); }  // the scene (control-scene.js) patches itself in place
      if (cur.startsWith("agent:")) {
        const k = cur.slice(6);
        if (full || !wsD || wsD.agent.key !== k) { wsD = await api(`${B}/agents/${encodeURIComponent(k)}`); }
        else { wsD.messages = await api(`${B}/agents/${encodeURIComponent(k)}/messages`); }
        return draw(agentView(), true);
      }
      if (cur === "org") { await loadTree(); return draw(orgView()); }
      nodeD = await api(`${B}/node/${encodeURIComponent(cur)}`);
      draw(nodeD.kind === "team" ? teamView() : nodeD.kind === "group" ? groupView() : deptView());
    } catch (e) {
      if (!cur && unavailable(e)) return setView("command");
      // a passing failure (the server restarting, a gateway timeout, a dropped connection) is tried again before an error screen shows
      const passing = !e?.status || [502, 503, 504].includes(e.status);
      if (passing && (render.retries = (render.retries || 0) + 1) <= 3) { setTimeout(() => { if (S.view === "control") render(false); }, 1500 * render.retries); return; }
      render.retries = 0;
      draw(`${head([])}<div class="card empty">${icon("alert")}<p>${esc(e.message)}</p><p><button type="button" class="btn" data-go="">Back to the Control Hub</button></p></div>`);
    }
  }
  function draw(html, chat) {
    render.retries = 0;
    const el = root(); if (!el) return;
    const keep = chat && el.querySelector(".cx-composer");
    if (keep && el.dataset.agent === cur) {  // the composer keeps what's being typed: only the parts around it change
      const fresh = document.createElement("div"); fresh.innerHTML = html;
      for (const k of ["ctl-ahead", "ctl-ctx", "ctl-log", "ctl-wsbody"]) {
        const a = el.querySelector("." + k), b = fresh.querySelector("." + k);
        if (a && b && a.innerHTML !== b.innerHTML) { a.innerHTML = b.innerHTML; if (k === "ctl-log") afterLog(); }
      }
      return;
    }
    el.innerHTML = `<div class="ctl">${html}</div>`;
    if (typeof CtlScene !== "undefined") CtlScene.after(el);  // mounts the scene, or leaves it and offers it on the Command Center
    el.dataset.agent = chat ? cur : "";
    if (chat) mountChat();
  }
  function crumbs() {
    const out = [["", "Control Hub"]];
    if (!cur) return out;
    out.push(["org", tree?.org.name || "Organization"]);
    if (cur === "org") return out;
    if (cur === "bittensor") { out.push(["bittensor", tree?.bittensor?.name || "Bittensor"]); return out; }
    if (cur.startsWith("sn:")) { out.push(["bittensor", tree?.bittensor?.name || "Bittensor"]); out.push([cur, allDepts().find(d => d.id === cur)?.name || cur]); return out; }
    if (cur.startsWith("u:")) {
      const [t, d] = findTeam(cur);
      if (t) { if (d?.kind === "subnet" || d?.kind === "bittensor") out.push(["bittensor", tree.bittensor.name]); if (d && d.kind !== "bittensor") out.push([d.id, d.name]); out.push([cur, shortTeam(t.name, d)]); }
      else out.push([cur, allDepts().find(x => x.id === cur)?.name || "Department"]);
      return out;
    }
    if (cur.startsWith("agent:")) {
      const p = wsD?.agent;
      if (p?.unit) { const [t, d] = findTeam(p.unit.ref); if (t && d) { if (d.kind === "subnet") out.push(["bittensor", tree.bittensor.name]); if (d.kind !== "bittensor") out.push([d.id, d.name]); out.push([t.id, shortTeam(t.name, d)]); } else out.push([p.unit.ref, p.unit.name]); }
      out.push([cur, p?.name || findAgent(cur.slice(6))?.name || "Agent"]);
    }
    return out;
  }
  function head(actions, sub = "") {
    const mode = tree?.mode || hubD?.mode || "hybrid";
    return `<header class="ctl-top">
      <nav class="ctl-crumbs" aria-label="Where you are">${crumbs().map(([id, l], i, a) => i === a.length - 1 ? `<span aria-current="page">${esc(l)}</span>` : `<button type="button" class="linkbtn" data-go="${esc(id)}">${esc(l)}</button>${icon("right")}`).join("")}</nav>
      <div class="ctl-topr">
        <div class="ctl-mode" role="group" aria-label="Automation: how much AXoR staffs on its own">${Object.entries(MODE).map(([k, [ic, l]]) => `<button type="button" data-mode="${k}" aria-pressed="${mode === k}" title="${esc(tree?.modes?.[k] || "")}">${icon(ic)}${l}</button>`).join("")}</div>
        <button type="button" class="iconbtn" data-act="refresh" title="Refresh" aria-label="Refresh">${icon("reset")}</button></div>
      ${actions.length ? `<div class="ctl-acts">${actions.join("")}</div>` : ""}${sub ? `<p class="ctl-sub faint">${sub}</p>` : ""}</header>`;
  }
  const btn = (act, ic, label, primary = false, extra = "") => `<button type="button" class="btn ${primary ? "primary" : ""} sm" data-act="${act}" ${extra}>${icon(ic)}${esc(label)}</button>`;
  const kpi = (ic, label, val, sub, tone = "", goSec = "") => `<button type="button" class="ctl-kpi ${tone}" ${goSec ? `data-sec="${goSec}"` : "disabled"}>${icon(ic)}<span><small>${esc(label)}</small><b>${esc(String(val))}</b><em>${esc(sub || "")}</em></span></button>`;

  // ---------- the hub ----------
  function hubView() {
    if (sec === "overview" && typeof CtlScene !== "undefined" && CtlScene.wanted()) return CtlScene.view(hubD);  // D-028: the Overview as the command-room scene
    const d = hubD, o = d.overview;
    // four areas (the 11-07 evaluation): Overview · Live operations · Notifications · Approval Center; each files the sections
    // it always had, and Notifications / Approval Center also open their full pages
    const count = k => k === "approvals" ? o.approvals : k === "alerts" ? o.alerts : 0;
    const area = AREAS.find(a => a[3].includes(sec)) || AREAS[0];
    const areas = `<div class="ctl-areas" role="tablist" aria-label="Control Hub areas">${AREAS.map(([k, ic, l, secs]) => {
      const n = secs.reduce((s, x) => s + count(x), 0), on = area[0] === k;
      return `<button type="button" role="tab" class="ctl-area ${on ? "on" : ""}" aria-selected="${on}" data-sec="${on ? sec : secs[0]}">${icon(ic)}<span>${l}</span>${n ? `<b class="${secs.includes("alerts") ? "warn" : ""}">${n}</b>` : ""}</button>`; }).join("")}</div>`;
    const page = area[4] && usable(`#nav-${area[4] === "notifications" ? "alerts" : "approvals"}`)
      ? `<button type="button" class="ctl-tab ctl-tab-go" data-goview="${area[4]}">${icon("external")}${area[4] === "notifications" ? "All notifications" : "Open the Approval Center"}</button>` : "";
    const tabs = `${areas}<div class="ctl-tabs" role="tablist" aria-label="${esc(area[2])}">${SECTIONS.filter(([k]) => area[3].includes(k)).map(([k, ic, l]) => {
      const n = count(k);
      return `<button type="button" role="tab" class="ctl-tab ${sec === k ? "on" : ""}" aria-selected="${sec === k}" data-sec="${k}">${icon(ic)}${l}${n ? `<b class="${k === "alerts" ? "warn" : ""}">${n}</b>` : ""}</button>`; }).join("")}${page}</div>`;
    // Overview with Mission operations (control-ops.js): the console comes first, right under the tabs; the figures it doesn't
    // already hold follow it (secOverview). Every other section keeps the KPI row on top.
    const opsFirst = sec === "overview" && typeof CtlOps !== "undefined";
    return `<div class="ctl-cc">${ccHead(d)}
      ${d.errors.length ? `<p class="ctl-warn">${icon("alert")}${esc(d.errors.join(" · "))}</p>` : ""}${opsFirst ? "" : ccKpis(d)}${tabs}<div class="ctl-sec" role="tabpanel">${({
        overview: secOverview, missions: () => typeof CtlMissions !== "undefined" ? CtlMissions.missionsSec() : secMissions(),
        tasks: () => typeof CtlMissions !== "undefined" ? CtlMissions.tasksSec() : secMissions(), agents: secAgents, teams: secTeams, resources: secResources, approvals: secApprovals,
        journeys: () => CtlJourney.journeysSec(), routing: () => CtlJourney.routingSec(),
        alerts: secAlerts, performance: secPerformance, audit: secAudit })[sec]()}</div></div>`;
  }

  // ---------- the Command Center (the hub's head, KPI row and Overview): every figure comes from /api/control, nothing is made up ----------
  const usable = sel => { const b = $(sel); return !!b && !b.hidden && !b.closest(".side-sec")?.hidden; };
  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  const clockText = () => { const n = new Date(); return `UTC ${n.toISOString().slice(11, 19)}`; };
  const dateText = () => new Date().toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  function ccHead(d) {
    const mode = d.mode || "hybrid", alerts = d.overview.alerts;
    return `<header class="ctl-cc-head">
      <div class="ctl-cc-title"><h1 class="page">Command Center</h1>
        <p class="lead">Monitor the entire AXoR organization, missions, approvals and system health in one place.</p>
        <p class="ctl-cc-meta faint small">${icon("branch")}${esc(d.org.name)} · <span title="${esc(`${d.modes[mode] || ""} ${d.always || ""}`.trim())}">${esc((MODE[mode] || [, mode])[1])} mode</span> · <span data-ctl-at>Updated ${esc(ago(d.at))}</span></p></div>
      <div class="ctl-cc-tools">
        <span class="ctl-cc-clock" title="${esc(new Date().toString())}"><i aria-hidden="true"></i><b data-ctl-clock>${clockText()}</b><span class="sep" aria-hidden="true"></span><span data-ctl-date>${esc(dateText())}</span></span>
        <div class="ctl-mode" role="group" aria-label="Automation: how much AXoR staffs on its own">${Object.entries(MODE).map(([k, [ic, l]]) => `<button type="button" data-mode="${k}" aria-pressed="${mode === k}" title="${esc(d.modes?.[k] || "")}">${icon(ic)}${l}</button>`).join("")}</div>
        <button type="button" class="ctl-cc-ib" data-act="refresh" title="Refresh" aria-label="Refresh">${icon("reset")}</button>
        ${usable("#nav-alerts") ? `<button type="button" class="ctl-cc-ib" data-goview="notifications" title="Notifications" aria-label="Notifications">${icon("bell")}${alerts ? `<i class="ctl-cc-ping" aria-hidden="true"></i>` : ""}</button>` : ""}
        ${usable("#nav-mos") ? `<button type="button" class="btn primary ctl-cc-new" data-goview="mos">${icon("plus")}New mission</button>` : `<button type="button" class="btn primary ctl-cc-new" data-act="task">${icon("plus")}New task</button>`}</div></header>`;
  }
  function spark(vals, w = 84, h = 30) {
    if (vals.length < 2 || !vals.some(Boolean)) return "";
    const mx = Math.max(...vals), mn = Math.min(...vals), r = mx - mn || 1;
    const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 3 - (v - mn) / r * (h - 6)).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }
  const ccKpi = (ic, tone, label, val, sub, vis, goSec, tip = "") => `<button type="button" class="ctl-cc-kpi t-${tone}" data-sec="${goSec}" title="${esc(tip)}">
      <span class="ctl-cc-ki">${icon(ic)}</span><small>${esc(label)}</small>
      <b class="ctl-cc-kv">${esc(String(val))}</b>${vis ? `<span class="ctl-cc-kvis">${vis}</span>` : ""}${sub ? `<em class="ctl-cc-ke">${esc(sub)}</em>` : ""}</button>`;
  function ccKpis(d, slim = false) {  // slim: without the two figures Mission operations shows itself (missions, verified results)
    const o = d.overview, wk = d.week || [], r24 = d.runs24 || { done: 0, failed: 0 };
    const fin = r24.done + r24.failed, crit = d.alerts.filter(a => a.level === "stop").length, warn = d.alerts.filter(a => a.level === "warn").length;
    const util = o.agents ? pct(o.working, o.agents) : null;
    const rates = wk.map(x => x.done + x.failed ? x.done / (x.done + x.failed) * 100 : null);
    const rateSeries = rates.filter(x => x != null);
    return `<div class="ctl-cc-kpis">
      ${slim ? "" : d.structure ? ccKpi("target", "cyan", "Active missions", d.structure.counts.active, `${d.structure.counts.predefined} Bittensor · ${d.structure.counts.custom} custom · ${d.structure.counts.tasks_open} open tasks, ${d.structure.counts.in_progress ?? 0} under way`, "", "missions",
              "Missions are what the company wants to achieve: predefined (a Bittensor competition, the primary initiative) and custom (Mission Control). Tasks are what agents do for them, counted apart")
        : ccKpi("target", "cyan", "Active missions", o.fixed + o.dynamic, `${o.fixed} fixed · ${o.dynamic} dynamic`, "", "missions", "Competition teams' objectives and open work")}
      ${ccKpi("inbox", o.approvals ? "amber" : "green", "Pending approvals", o.approvals, o.approvals ? (d.approvals.org.length ? `${d.approvals.org.length} to decide here` : "waiting for you") : "all clear", "", "approvals")}
      ${ccKpi("users", "violet", "Agent utilization", util == null ? "–" : `${util}%`, `${o.working} of ${plural(o.agents, "agent")} working`,
              util == null ? "" : `<span class="ctl-cc-bar"><i style="width:${util}%"></i></span>`, "agents")}
      ${ccKpi("coins", o.cap && o.spent >= o.cap * (o.warn_pct || 80) / 100 ? "amber" : "green", "Budget burn", tok(o.spent), o.cap ? `${pct(o.spent, o.cap)}% of ${tok(o.cap)} today` : "tokens today · no limit",
              spark(wk.map(x => x.tokens)), "resources", "Tokens your agents used today; the line is the last 7 days")}
      ${ccKpi("shield", fin && r24.failed / fin > .2 ? "amber" : "green", "Run success (execution)", fin ? `${(r24.done / fin * 100).toFixed(1)}%` : "–",
              fin ? `${r24.failed} failed of ${fin} · 24 h` : "no finished run in 24 h", rateSeries.length > 1 ? spark(rateSeries) : "", "agents",
              `Agent runs that finished without failing, last 24 hours (rolling); the line is per day over the last 7 days.${r24.total != null ? ` All ${r24.total} runs of the 24 hours, each counted once: ${r24.success} succeeded, ${r24.failed - (r24.timeout || 0) - (r24.restarted || 0)} failed, ${r24.timeout} timed out, ${r24.restarted} cut off by a restart, ${r24.cancelled} cancelled, ${r24.running} still running${r24.other ? `, ${r24.other} other` : ""}. Cancelled and running runs are left out of the rate.` : ""}`)}
      ${(() => { const R = d.results; if (!R || slim) return "";  // what the runs achieved, beside how many ended without an error
        const bm = R.benchmarks || [], up = bm.filter(b => b.delta > 0).length, best = bm.reduce((m, b) => b.delta != null && (m == null || b.delta > m) ? b.delta : m, null);
        const n = R.verified_missions + R.releases + R.promoted;
        return ccKpi("check", n || up ? "green" : "amber", "Verified results", `${n}`, `${R.verified_missions}/${R.delivered_missions} missions verified · ${plural(R.releases, "release")} · ${R.promoted} promoted`
          + (bm.length && best != null ? ` · bench ${best > 0 ? "+" : ""}${best}` : ""), "", "missions",
          `Last 7 days. Results, not runs: missions delivered and verified, release candidates frozen (Competition teams → Status → Release & benchmarks), changes promoted by the Evolution Lab. Benchmarks count only on the frozen candidate and suite, against its reference${bm.length ? `: ${bm.map(b => `${b.suite} ${b.score}${b.delta != null ? ` (${b.delta > 0 ? "+" : ""}${b.delta})` : ""}`).join(", ")}` : ": none filed yet"}.`); })()}
      ${ccKpi("alert", crit ? "red" : warn ? "amber" : "green", "Critical alerts", crit, warn ? plural(warn, "warning") : crit ? "need you" : "none open", "", "alerts")}</div>`;
  }
  // a status bucket for anything that moves: Control Hub tasks, team board tasks, Mission Control missions
  const BUCKETS = [["progress", "In progress"], ["queued", "Queued"], ["review", "Review"], ["waiting", "Waiting on you"], ["done", "Completed (24h)"], ["failed", "Failed (24h)"]];
  function bucketOf(status, ts) {
    const s = String(status || "").toLowerCase(), recent = !ts || Date.now() / 1000 - ts < 86400;
    if (["running", "working", "doing", "active", "in_progress", "planning", "executing"].includes(s)) return "progress";
    if (["todo", "queued", "open", "backlog", "new", "pending"].includes(s)) return "queued";
    if (["review", "checking", "verifying"].includes(s)) return "review";
    if (["needs_input", "paused", "blocked", "waiting"].includes(s)) return "waiting";
    if (["done", "completed", "delivered", "accepted", "success"].includes(s)) return recent ? "done" : null;
    if (["failed", "error", "lost"].includes(s)) return recent ? "failed" : null;
    return null;
  }
  function missionCard(d) {
    const m = d.missions, n = Object.fromEntries(BUCKETS.map(([k]) => [k, 0]));
    const linked = new Set(m.dynamic.map(t => /^mw_task:(\d+)$/.exec(t.ref || "")?.[1]).filter(Boolean).map(Number));
    for (const t of m.dynamic) { const b = bucketOf(t.status, t.updated); if (b) n[b]++; }
    for (const t of m.board) { if (linked.has(t.id)) continue; const b = bucketOf(t.status, t.updated); if (b) n[b]++; }
    for (const x of m.mission_control) { const b = bucketOf(x.status, x.updated); if (b) n[b]++; }
    const total = Object.values(n).reduce((a, b) => a + b, 0), active = n.progress + n.queued + n.review + n.waiting;
    let off = 0;
    const segs = BUCKETS.filter(([k]) => n[k]).map(([k, l]) => {
      const len = n[k] / total * 100, gap = total > n[k] ? 1.2 : 0, dash = Math.max(len - gap, .4);
      const c = `<circle class="b-${k}" cx="21" cy="21" r="15.915" pathLength="100" stroke-dasharray="${dash.toFixed(2)} ${(100 - dash).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}"><title>${esc(l)}: ${n[k]}</title></circle>`;
      off += len; return c;
    }).join("");
    return `<section class="ctl-cc-card ctl-cc-mis"><div class="ctl-cc-ch"><h3>${icon("target")}Mission overview</h3><button type="button" class="ctl-cc-more" data-sec="missions">View all${icon("right")}</button></div>
      <p class="ctl-cc-cap">Tasks and custom missions by status</p>
      <div class="ctl-cc-donut"><div class="ctl-cc-ring"><svg viewBox="0 0 42 42" aria-hidden="true"><circle class="trk" cx="21" cy="21" r="15.915"/><g transform="rotate(-90 21 21)">${segs}</g></svg>
          <span><b>${active}</b><small>Active</small></span></div>
        <ul class="ctl-cc-legend">${BUCKETS.map(([k, l]) => `<li><i class="b-${k}"></i><span>${esc(l)}</span><b>${n[k]}</b><small>(${total ? pct(n[k], total) : 0}%)</small></li>`).join("")}</ul></div>
      ${stallLine(d)}
      ${total ? "" : `<p class="ctl-cc-empty">Nothing is running. ${usable("#nav-mos") ? `<button type="button" class="linkbtn" data-goview="mos">Start a mission</button> or ` : ""}<button type="button" class="linkbtn" data-act="task">give a team a task</button>.</p>`}</section>`;
  }
  // why open tasks aren't moving (control_dispatch.py): the dispatcher's state and the commonest reasons
  function stallLine(d) {
    const x = d.structure?.dispatch;
    if (!x) return "";
    const head = x.on ? `AXoR dispatches open tasks every ${x.every >= 60 ? plural(Math.round(x.every / 60), "minute") : `${x.every} s`}${x.last ? ` · last pass ${ago(x.last)}` : ""}`
                      : "Nothing dispatches tasks by itself (Manual mode or dispatcher off)";
    return `<div class="ctl-cc-stall ${x.stuck ? "is-stuck" : ""}"><p class="small">${icon(x.stuck ? "alert" : "route")}<span>${esc(head)}.${x.held ? ` ${esc(x.held)}` : ""}</span></p>
      ${x.stuck ? `<p class="small"><b>${plural(x.stuck, "open task")} not moving for over an hour:</b> ${x.reasons.map(r => `${esc(r.why)} (${r.n}${r.owner ? `, next: ${esc(r.owner)}` : ""})`).join("; ")}.${x.yours ? ` <b>${x.yours} wait${x.yours === 1 ? "s" : ""} for you.</b>` : ""}
        <button type="button" class="linkbtn" data-sec="missions">See each reason</button></p>` : ""}</div>`;
  }
  const SRCI = { mining: "trophy", company: "layers", workforce: "group", hq: "flag", portfolio: "target", teams: "users", workflow: "route", projects: "cycle",
                 knowledge: "book", missions: "target", market: "apps", org: "branch" };
  const PRI = { stop: ["crit", "High"], warn: ["warn", "Medium"], info: ["info", "Low"] };
  function approvalCard(d) {
    const a = d.approvals, rows = [
      ...a.org.map(r => ({ ic: "branch", t: r.title, s: `Organization · ${r.why || r.kind || ""}`, pri: ["info", "Decide here"],
                           act: `<button type="button" class="btn sm primary" data-req="${r.id}" data-ok="1">Approve</button><button type="button" class="btn sm" data-req="${r.id}" data-ok="0">Decline</button>` })),
      ...a.all.filter(p => p.source !== "org").map(p => ({ ic: SRCI[p.source] || "inbox", t: p.title, s: `${p.where || p.source}${p.detail ? ` · ${p.detail}` : ""}`, pri: PRI[p.level] || PRI.info,
                           act: p.go ? `<button type="button" class="btn sm" data-goview="${esc(p.go)}">${esc(p.label || "Review")}</button>` : "" }))];
    const n = d.overview.approvals;
    return `<section class="ctl-cc-card ctl-cc-ap"><div class="ctl-cc-ch"><h3>${icon("inbox")}Approval queue</h3><button type="button" class="ctl-cc-more" data-sec="approvals">View all (${n})${icon("right")}</button></div>
      ${rows.length ? `<ul class="ctl-cc-list">${rows.slice(0, 4).map(r => `<li><span class="ctl-cc-li">${icon(r.ic)}</span><span class="ctl-cc-lt"><b>${esc(r.t)}</b><small>${esc(r.s)}</small></span>
          <span class="ctl-cc-pill p-${r.pri[0]}">${esc(r.pri[1])}</span><span class="ctl-cc-ra">${r.act}</span></li>`).join("")}</ul>`
        : `<p class="ctl-cc-empty">${icon("check")}Nothing is waiting for your approval.</p>`}</section>`;
  }
  const human = s => { const t = String(s || "").replace(/^control\./, "").replace(/[._]/g, " ").trim(); return t ? t[0].toUpperCase() + t.slice(1) : ""; };
  function activityCard(d) {
    const ev = [
      ...d.agents.running.map(r => ({ ts: r.started, ic: "play", tone: "cyan", t: `${r.name} started work`, s: r.title || r.kind })),
      ...d.agents.failed.map(r => ({ ts: r.started, ic: "alert", tone: "red", t: `${r.name}: run failed`, s: r.title || r.error || r.kind })),
      ...d.missions.mission_control.filter(x => x.updated).map(x => ({ ts: x.updated, ic: "rocket", tone: "violet", t: `Mission ${String(x.status || "").replace(/_/g, " ")}`, s: x.title || `Mission ${x.id}` })),
      ...d.missions.dynamic.filter(t => t.updated).map(t => ({ ts: t.updated, ic: bucketOf(t.status) === "done" ? "check" : "list", tone: bucketOf(t.status) === "done" ? "green" : "cyan",
                                                                t: `Task ${(TSTAT[t.status] || [, t.status])[1].toLowerCase()}`, s: `${t.title}${t.agent ? ` · ${t.agent}` : ""}` })),
      ...d.audit.map(a => ({ ts: a.ts, ic: "clock", tone: "muted", t: human(a.action), s: [a.target, a.actor && `by ${a.actor}`].filter(Boolean).join(" · ") || a.detail || "" })),
    ].filter(e => e.ts).sort((a, b) => b.ts - a.ts).slice(0, 5);
    return `<section class="ctl-cc-card ctl-cc-act"><div class="ctl-cc-ch"><h3>${icon("radio")}Live activity feed</h3><button type="button" class="ctl-cc-more" data-sec="audit">View all${icon("right")}</button></div>
      ${ev.length ? `<ul class="ctl-cc-feed">${ev.map(e => `<li><span class="ctl-cc-fi t-${e.tone}">${icon(e.ic)}</span><span class="ctl-cc-lt"><b>${esc(e.t)}</b><small>${esc(e.s || "")}</small></span><time>${esc(when(e.ts))}</time></li>`).join("")}</ul>`
        : `<p class="ctl-cc-empty">No activity yet: runs, missions, tasks and organization changes show up here.</p>`}</section>`;
  }
  const HEALTH = { busy: ["ok", "Working"], ok: ["ok", "Healthy"], warn: ["warn", "Needs a look"], stop: ["crit", "Failing"], idle: ["off", "Idle"] };
  function orgCard() {
    const deps = allDepts();
    const rows = deps.slice(0, 6).map(dp => {
      const ags = [...dp.teams.flatMap(t => t.agents), ...(dp.staff || [])], bad = ags.filter(a => a.status === "stop").length;
      const h = ags.length ? pct(ags.length - bad, ags.length) : null, [tone, l] = HEALTH[dp.status] || HEALTH.idle;
      const nm = dp.kind === "subnet" ? dp.name.replace(/^SN\d+ · /, "") || dp.name : dp.name;  // a named subnet shows its name, its number goes below
      return `<li><button type="button" data-go="${esc(dp.id)}"><span class="ctl-cc-dic">${dp.kind === "subnet" ? `<small>SN</small>` : icon("branch")}</span>
        <span class="ctl-cc-lt"><b>${esc(nm)}</b><small><span class="ctl-cc-st s-${tone}"><i></i>${esc(l)}</span> · ${nm !== dp.name ? `SN${dp.netuid} · ` : ""}${dp.teams.length ? `${plural(dp.teams.length, "team")} · ` : ""}${plural(ags.length, "agent")}</small></span>
        <span class="ctl-cc-hb" title="${h == null ? "No agents yet" : `${ags.length - bad} of ${ags.length} agents' last run didn't fail`}"><span class="ctl-cc-bar"><i style="width:${h || 0}%"></i></span><b>${h == null ? "–" : `${h}%`}</b></span></button></li>`;
    }).join("");
    return `<section class="ctl-cc-card ctl-cc-org"><div class="ctl-cc-ch"><h3>${icon("branch")}Organization map · team health</h3><button type="button" class="ctl-cc-more" data-go="org">View org${icon("right")}</button></div>
      ${rows ? `<ul class="ctl-cc-depts">${rows}</ul>${deps.length > 6 ? `<p class="faint small">and ${deps.length - 6} more</p>` : ""}`
        : `<p class="ctl-cc-empty">No department yet. <button type="button" class="linkbtn" data-act="dept">Add one</button> or <button type="button" class="linkbtn" data-act="wizard">start a Bittensor mission</button>.</p>`}</section>`;
  }
  // a smooth line through the points (Catmull-Rom as cubic Béziers), clamped inside the box
  function curve(pts, top, bottom) {
    const cl = y => Math.min(bottom, Math.max(top, y)), f = p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    let s = `M${f(pts[0])}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      s += ` C${f([p1[0] + (p2[0] - p0[0]) / 6, cl(p1[1] + (p2[1] - p0[1]) / 6)])} ${f([p2[0] - (p3[0] - p1[0]) / 6, cl(p2[1] - (p3[1] - p1[1]) / 6)])} ${f(p2)}`;
    }
    return s;
  }
  function resourceCard(d) {
    const r = d.resources, wk = d.week || [], r24 = d.runs24 || {}, total = wk.reduce((a, x) => a + x.tokens, 0);
    const runs = r24.total != null ? r24.total : r.by_system.reduce((a, s) => a + (s.runs || 0), 0);  // the same 24 hours as the success rate
    const W = 300, H = 74, mx = Math.max(...wk.map(x => x.tokens), 1);
    const pts = wk.map((x, i) => [i / Math.max(wk.length - 1, 1) * W, H - 4 - x.tokens / mx * (H - 12)]);
    const line = wk.length > 1 ? curve(pts, 2, H - 2) : "", last = pts[pts.length - 1];
    const label = x => new Date((x.day + 43200) * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const mini = (ic, l, v, s) => `<div class="ctl-cc-mini"><small>${icon(ic)}${esc(l)}</small><b>${esc(v)}</b><em>${esc(s)}</em></div>`;
    return `<section class="ctl-cc-card ctl-cc-res"><div class="ctl-cc-ch"><h3>${icon("coins")}Resource &amp; budget monitor</h3><button type="button" class="ctl-cc-more" data-sec="resources">Details${icon("right")}</button></div>
      <div class="ctl-cc-minis">${mini("zap", "Tokens today", tok(r.spent), r.cap ? `${pct(r.spent, r.cap)}% of the daily limit` : "no daily limit")}
        ${mini("play", r24.total != null ? "Runs · 24 h" : "Runs today", runs.toLocaleString(), r24.total != null ? `${r24.running} running · ${r24.cancelled} cancelled` : plural(r.by_system.length, "system"))}
        ${mini("wallet", "Remaining today", r.cap ? tok(Math.max(r.cap - r.spent, 0)) : "–", r.cap ? `${100 - Math.min(100, pct(r.spent, r.cap))}% of ${tok(r.cap)}` : r.policy?.state === "unlimited" ? "no cap, by your choice" : r.policy?.state === "scoped" ? "scoped limits only" : "no boundary decided")}</div>
      ${r.coverage?.tokens ? `<p class="faint small">Cost accounting, 24 h: ${r.coverage.priced_pct ?? 0}% of ${tok(r.coverage.tokens)} tokens priced${r.coverage.unpriced ? ` · ${tok(r.coverage.unpriced)} unpriced` : ""}${r.coverage.runs_without_tokens ? ` · ${r.coverage.runs_without_tokens} runs without a token count` : ""}</p>` : ""}
      <div class="ctl-cc-chart"><div class="ctl-cc-chh"><span>Token spend (7d)</span><b>${tok(total)}</b></div>
        ${total ? `<div class="ctl-cc-plot"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="Tokens per day, last 7 days: ${esc(wk.map(x => `${label(x)} ${tok(x.tokens)}`).join(", "))}">
            <defs><linearGradient id="ctl-cc-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".28"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
            <path d="${line} L${W},${H} L0,${H} Z" fill="url(#ctl-cc-fill)" stroke="none"/><path d="${line}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
          <i class="ctl-cc-pt" style="left:100%;top:${(last[1] / H * 100).toFixed(1)}%"></i></div>`
          : `<p class="ctl-cc-empty">No agent run in the last 7 days.</p>`}
        <div class="ctl-cc-days">${wk.map(x => `<span>${esc(label(x))}</span>`).join("")}</div></div></section>`;
  }
  function alertsCard(d) {
    const a = [...d.alerts].sort((x, y) => (x.level === "stop" ? 0 : 1) - (y.level === "stop" ? 0 : 1));
    return `<section class="ctl-cc-card ctl-cc-al"><div class="ctl-cc-ch"><h3>${icon("alert")}Alerts &amp; risks</h3><button type="button" class="ctl-cc-more" data-sec="alerts">View all${icon("right")}</button></div>
      ${a.length ? `<ul class="ctl-cc-list">${a.slice(0, 4).map(x => `<li class="l-${x.level === "stop" ? "crit" : "warn"}"><span class="ctl-cc-ai">${icon("alert")}</span><span class="ctl-cc-lt"><b>${esc(x.title)}</b><small>${esc(x.detail || "")}${x.ts ? ` · ${esc(when(x.ts))}` : ""}</small>${x.act === "budget" ? `<button type="button" class="linkbtn" data-goview="studio">Decide the budget</button>` : ""}</span>
          <span class="ctl-cc-pill p-${x.level === "stop" ? "crit" : "warn"}">${x.level === "stop" ? "Critical" : "Warning"}</span></li>`).join("")}</ul>`
        : `<p class="ctl-cc-empty">${icon("check")}No alert: no failures in 24 hours, budgets in bounds.</p>`}</section>`;
  }
  function quickCard() {
    const Q = [["rocket", "Create mission", "Define and launch a new mission", `data-goview="mos"`, "#nav-mos"],
               ["inbox", "Review approvals", "Process pending requests", `data-sec="approvals"`, null],
               ["trophy", "New Bittensor mission", "A competition with a top-N target and its team", `data-act="wizard"`, null],
               ["list", "New task", "Dynamic work for a mission, a team or an agent", `data-act="task"`, null],
               ["users", "Open Workforce", "Manage agents and teams", `data-goview="workforce"`, "#nav-workforce"],
               ["book", "View Knowledge Hub", "Research and company knowledge", `data-goview="knowledge"`, "#nav-knowledge"]].filter(q => !q[4] || usable(q[4]));
    return `<section class="ctl-cc-card ctl-cc-quick"><div class="ctl-cc-qh"><h3>${icon("zap")}Quick actions</h3><p>Common operations to run and manage the AXoR agent company.</p></div>
      <div class="ctl-cc-qs">${Q.map(([ic, l, s, at], i) => `<button type="button" class="ctl-cc-q ${i ? "" : "on"}" ${at}><span>${icon(ic)}</span><b>${esc(l)}</b><small>${esc(s)}</small>${icon("right")}</button>`).join("")}</div></section>`;
  }
  const table = (cols, rows, empty) => rows.length ? `<div class="ctl-tw-wrap"><table class="ctl-table"><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>` : `<p class="faint">${esc(empty)}</p>`;
  const rankCell = f => { const s = f.standing; return s?.rank ? `${s.rank}${s.of ? ` <span class="faint">of ${s.of}</span>` : ""}` : `<span class="faint">no rank yet</span>`; };
  const gapCell = f => { const r = f.standing?.rank, t = f.target_rank; if (!t) return badge("muted", "No target"); if (!r) return badge("muted", `Target top ${t}`);
                         return r <= t ? badge("clear", `In the top ${t}`, "check") : badge("caution", `${r - t} to go · top ${t}`); };
  function fixedTable(rows) {
    return table(["Mission (team)", "Target", "Rank now", "Gap", "Budget today", "Deadline"], rows.map(f => `<tr><td><button type="button" class="linkbtn" data-go="${esc(f.unit || "")}">${esc(f.name)}</button></td>
      <td>${f.target_rank ? `Top ${f.target_rank}` : `<button type="button" class="linkbtn" data-fixed="${f.comp_id}">Set a target</button>`}</td><td>${rankCell(f)}</td><td>${gapCell(f)}</td>
      <td>${meter(f.used_today, f.budget)}</td><td>${esc(f.deadline || "–")}</td></tr>`), "No Bittensor mission yet: start one on a subnet's competition.");
  }
  const meter = (used, cap) => cap ? `<span class="ctl-meter ${used > cap * .9 ? "hot" : ""}" title="${tok(used)} of ${tok(cap)}"><i style="width:${Math.min(100, Math.round(used / cap * 100))}%"></i></span><small>${tok(used)} / ${tok(cap)}</small>` : `<small>${tok(used)}</small>`;
  function secOverview() {
    const d = hubD;
    // one view of missions, not three: with Mission operations the primary-initiative band, the mission status card and the top
    // miner table are left out here (the console's competition cards and activity hold them; Missions keeps the full lists)
    if (typeof CtlOps !== "undefined") return `${CtlOps.section()}<h3 class="ctl-cc-rest">Organization, approvals and resources</h3>${ccKpis(d, true)}
      <div class="ctl-cc-grid">${approvalCard(d)}${activityCard(d)}${orgCard()}${resourceCard(d)}${alertsCard(d)}${quickCard()}</div>`;
    return `${typeof CtlMissions !== "undefined" ? CtlMissions.band(d) : ""}<div class="ctl-cc-grid">${missionCard(d)}${approvalCard(d)}${activityCard(d)}${orgCard()}${resourceCard(d)}${alertsCard(d)}
      ${d.missions.fixed.length ? `<section class="ctl-cc-card ctl-cc-wide"><div class="ctl-cc-ch"><h3>${icon("trophy")}Bittensor missions · top miner targets</h3><button type="button" class="ctl-cc-more" data-sec="missions">Missions${icon("right")}</button></div>${fixedTable(d.missions.fixed)}</section>` : ""}
      ${quickCard()}</div>`;
  }
  function taskList(ts, team) {
    return ts.length ? `<ul class="ctl-list">${ts.map(t => { const [tone, l] = TSTAT[t.status] || ["muted", t.status];
      return `<li><span><button type="button" class="linkbtn ctl-tt" data-task="${t.id}">${esc(t.title)}</button><small>${esc(t.route === "board" ? "Team board" : t.route === "mission" ? "Runs as a custom mission" : "Agent run")}${t.kind === "fixed" ? " · fixed" : ""}${t.agent ? ` · ${esc(t.agent)}` : ""}${team && t.team ? "" : ""}${t.summary ? ` · ${esc(t.summary)}` : ""}</small></span>${badge(tone, l)}</li>`; }).join("")}</ul>` : `<p class="faint">No dynamic task yet.</p>`;
  }
  function secMissions() {
    const m = hubD.missions;
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("trophy")}Bittensor missions</h3><p class="faint small">Predefined: each Competition team holds a top-N miner objective on its competition.</p>${btn("wizard", "plus", "New Bittensor mission")}</div>${fixedTable(m.fixed)}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("list")}Dynamic tasks from the Control Hub</h3>${btn("task", "plus", "New dynamic task")}</div>${taskList(m.dynamic)}</section>
      <div class="ctl-grid2"><section class="card ctl-card"><div class="ctl-h"><h3>${icon("columns")}Open on team boards</h3></div>
        ${table(["Task", "Status", "Updated"], m.board.map(b => `<tr><td><button type="button" class="linkbtn" data-go="${esc(b.unit || "")}">${esc(b.title)}</button></td><td>${esc(b.status)}</td><td>${esc(when(b.updated))}</td></tr>`), "Nothing open on the boards.")}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("target")}Mission Control</h3><button type="button" class="linkbtn" data-goview="mos">Open</button></div>
        ${table(["Mission", "Status", ""], m.mission_control.map(x => `<tr><td>${esc(x.title || `Mission ${x.id}`)}</td><td>${esc(x.status)}</td><td><button type="button" class="linkbtn" data-ctlj-open="mx:${esc(x.id)}">Journey</button></td></tr>`), "No mission yet.")}</section></div>`;
  }
  function secAgents() {
    const a = hubD.agents;
    return `<div class="ctl-grid2"><section class="card ctl-card"><div class="ctl-h"><h3>${icon("radio")}Running now</h3></div>
        ${table(["Agent", "Work", "Since"], a.running.map(r => `<tr><td>${r.agent_key ? `<button type="button" class="linkbtn" data-go="agent:${esc(r.agent_key)}">${esc(r.name)}</button>` : esc(r.name)}</td><td>${esc(r.title || r.kind)}</td><td>${esc(when(r.started))}</td></tr>`), "No agent is running.")}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("ban")}Failed · 24 hours</h3></div>
        ${table(["Agent", "Work", "Why"], a.failed.map(r => `<tr><td>${r.agent_key ? `<button type="button" class="linkbtn" data-go="agent:${esc(r.agent_key)}">${esc(r.name)}</button>` : esc(r.name)}</td><td>${esc(r.title || r.kind)}</td><td class="small">${esc(r.error || "")}</td></tr>`), "No failure in the last 24 hours.")}</section></div>
      <p class="faint small">Activity, governance limits and the assistant: <button type="button" class="linkbtn" data-act="classic">Command Center (classic)</button> · every agent's runs and traces: <button type="button" class="linkbtn" data-goview="studio">Agent operations</button> · the registry: <button type="button" class="linkbtn" data-goview="agents">Agents</button> · new ones: <button type="button" class="linkbtn" data-goview="market">Agent Marketplace</button></p>`;
  }
  function secTeams() {
    return `<section class="card ctl-card">${table(["Team", "Department", "Agents", "Working", "Open tasks", "Tokens · week"], hubD.teams.map(t => `<tr><td><button type="button" class="linkbtn" data-go="${esc(t.id)}">${esc(t.name)}</button></td>
      <td>${esc(t.department)}</td><td>${t.agents}</td><td>${t.working ? badge("clear", String(t.working)) : "0"}</td><td>${t.open}</td><td>${tok(t.tokens_week)}</td></tr>`), "No team yet.")}</section>`;
  }
  function secResources() {
    const r = hubD.resources;
    return `<div class="ctl-grid2"><section class="card ctl-card"><div class="ctl-h"><h3>${icon("coins")}Tokens today</h3><button type="button" class="linkbtn" data-goview="workforce">Daily limit &amp; model pool</button></div>
        <p class="ctl-big">${tok(r.spent)} <small class="faint">${r.cap ? `of your ${tok(r.cap)} daily limit` : "no daily limit set"}</small></p>${r.cap ? meter(r.spent, r.cap) : ""}
        ${table(["System", "Runs", "Tokens"], r.by_system.map(s => `<tr><td>${esc(s.system)}</td><td>${s.runs}</td><td>${tok(s.tokens)}</td></tr>`), "No run today.")}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("trophy")}Competition teams · daily budgets</h3></div>
        ${table(["Team", "Today"], r.teams.map(t => `<tr><td><button type="button" class="linkbtn" data-go="${esc(t.unit || "")}">${esc(t.name)}</button></td><td>${meter(t.used, t.budget)}</td></tr>`), "No Competition team yet.")}
        <p class="faint small">Each team's governor holds new work at its budget; concurrency per login is set in Agents → Models.</p></section></div>`;
  }
  function secApprovals() {
    const a = hubD.approvals;
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("branch")}Organization requests</h3><p class="faint small">Staffing AXoR proposed in Hybrid mode, and other organization changes. Decide here.</p></div>
        ${a.org.length ? `<ul class="ctl-list">${a.org.map(r => `<li><span><b>${esc(r.title)}</b><small>${esc(r.why || "")} · by ${esc(r.by || "")} · ${esc(when(r.created))}</small></span><span class="ctl-ra"><button type="button" class="btn sm primary" data-req="${r.id}" data-ok="1">Approve</button><button type="button" class="btn sm" data-req="${r.id}" data-ok="0">Decline</button></span></li>`).join("")}</ul>` : `<p class="faint">No organization request is waiting.</p>`}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("inbox")}Everything else waiting for you</h3><button type="button" class="linkbtn" data-goview="approvals">Approval Center</button></div>
        ${a.all.filter(p => p.source !== "org").length ? `<ul class="ctl-list">${a.all.filter(p => p.source !== "org").map(p => `<li class="${p.level === "stop" ? "crit" : ""}"><span><b>${esc(p.title)}</b><small>${esc(p.where || p.source)}${p.detail ? ` · ${esc(p.detail)}` : ""}</small></span>${p.go ? `<button type="button" class="btn sm" data-goview="${esc(p.go)}">${esc(p.label || "Open")}</button>` : ""}</li>`).join("")}</ul>` : `<p class="faint">Nothing else is waiting.</p>`}</section>`;
  }
  function secAlerts() {
    const a = hubD.alerts;
    return `<section class="card ctl-card">${a.length ? `<ul class="ctl-list">${a.map(x => `<li class="${x.level === "stop" ? "crit" : ""}">${icon(x.level === "stop" ? "ban" : "alert")}<span><b>${esc(x.title)}</b><small>${esc(x.detail || "")}${x.ts ? ` · ${esc(when(x.ts))}` : ""}</small></span></li>`).join("")}</ul>` : `<p class="faint">${icon("check")} No alert: no failures in 24 hours, budgets in bounds.</p>`}</section>`;
  }
  function secPerformance() {
    const p = hubD.performance;
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("trophy")}Against the targets</h3></div>${fixedTable(p.fixed)}</section>
      <div class="ctl-grid2"><section class="card ctl-card"><div class="ctl-h"><h3>${icon("up")}Best scores</h3><button type="button" class="linkbtn" data-goview="org">Scores in Organization HQ</button></div>
        ${table(["Agent", "Score", "Evidence"], p.agents.map(a => `<tr><td><button type="button" class="linkbtn" data-go="agent:${esc(a.key)}">${esc(a.name)}</button> <small class="faint">${esc(a.title)}</small></td><td>${Math.round(a.score)}</td><td>${a.evidence ?? "–"}</td></tr>`), "No agent has enough finished work for a score yet.")}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("down")}Needs attention</h3></div>
        ${table(["Agent", "Score"], p.low.map(a => `<tr><td><button type="button" class="linkbtn" data-go="agent:${esc(a.key)}">${esc(a.name)}</button></td><td>${Math.round(a.score)}</td></tr>`), "No agent scores under 50.")}</section></div>`;
  }
  function secAudit() {
    return `<section class="card ctl-card">${table(["When", "Who", "What", "Detail"], hubD.audit.map(a => `<tr><td class="nowrap">${esc(when(a.ts))}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td class="small">${esc(a.detail || "")}</td></tr>`), "Nothing recorded yet.")}</section>`;
  }

  // ---------- organization, group, department ----------
  function deptCard(d) {
    const ag = d.teams.reduce((n, t) => n + t.agents.length, 0) + (d.staff?.length || 0);
    return `<button type="button" class="ctl-dcard big" data-go="${esc(d.id)}">${dot(d.status)}<span class="ctl-dk">${icon(d.kind === "subnet" ? "pickaxe" : d.kind === "exec" ? "star" : d.kind === "division" ? "layers" : "group")}${esc(d.kind === "subnet" ? "Subnet" : d.kind === "exec" ? "Executive" : d.kind === "division" ? "Division" : "Department")}</span>
      <b>${esc(d.name)}</b><small>${plural(d.teams.length, "team")} · ${plural(ag, "agent")}</small>${d.purpose ? `<em>${esc(d.purpose)}</em>` : ""}</button>`;
  }
  function orgView() {
    const bt = tree.bittensor, c = tree.org.counts;
    return `${head([btn("dept", "plus", "New department", true), btn("wizard", "trophy", "New Bittensor mission")], `${plural(c.departments, "department")} · ${plural(c.teams, "team")} · ${plural(c.agents, "active agent")}. Organization defines structure; teams hold the work; agents can serve several teams.`)}
      <section class="ctl-lv"><h3 class="ctl-lvh">${icon("star")}Leadership</h3><div class="ctl-chips">${tree.org.ceo ? agentChip(tree.org.ceo, "CEO") : `<span class="faint">No CEO yet: pick one in Organization HQ.</span>`}<span class="ctl-you">${icon("star")}${esc(tree.org.owner || "You")} <small>owner · final authority</small></span></div></section>
      ${bt ? `<section class="ctl-lv"><h3 class="ctl-lvh">${icon("layers")}${esc(bt.name)} <small class="faint">department = subnet · team = competition</small><button type="button" class="linkbtn small" data-act="wizard">${icon("plus")}Mission</button></h3>
        <div class="ctl-dgrid">${bt.departments.map(deptCard).join("") || `<p class="faint">No subnet yet: start a Bittensor mission to add one.</p>`}</div></section>` : ""}
      <section class="ctl-lv"><h3 class="ctl-lvh">${icon("branch")}Departments<button type="button" class="linkbtn small" data-act="dept">${icon("plus")}Department</button></h3>
        <div class="ctl-dgrid">${tree.departments.map(deptCard).join("")}</div></section>
      ${tree.unplaced.length ? `<section class="ctl-lv"><h3 class="ctl-lvh">${icon("users")}Not placed <small class="faint">${tree.unplaced.length}</small></h3><div class="ctl-chips">${tree.unplaced.map(a => agentChip(a)).join("")}</div></section>` : ""}`;
  }
  function groupView() {
    const g = nodeD.group;
    return `${head([btn("wizard", "trophy", "New Bittensor mission", true), btn("goview", "pickaxe", "My subnets", false, `data-v="mining"`)], "AXoR's primary initiative. Each subnet you mine is a department; each competition on it is a predefined mission, carried by a team with its own workforce, board, files and budget.")}
      <div class="ctl-dgrid">${g.departments.map(deptCard).join("") || `<p class="faint">No subnet yet.</p>`}</div>
      ${g.teams.length ? `<section class="ctl-lv"><h3 class="ctl-lvh">${icon("users")}Other teams in the division</h3><div class="ctl-dgrid">${g.teams.map(t => teamCard(t, null)).join("")}</div></section>` : ""}
      ${g.staff.length ? `<section class="ctl-lv"><h3 class="ctl-lvh">${icon("group")}Division staff</h3><div class="ctl-chips">${g.staff.map(a => agentChip(a)).join("")}</div></section>` : ""}`;
  }
  function teamCard(t, d) {
    return `<button type="button" class="ctl-dcard big" data-go="${esc(t.id)}">${dot(t.status)}<span class="ctl-dk">${icon(t.kind === "competition" ? "trophy" : "users")}${t.kind === "competition" ? "Competition team" : "Team"}</span>
      <b>${esc(shortTeam(t.name, d))}</b><small>${plural(t.agents.length, "agent")} · ${t.agents.filter(a => a.status === "busy").length} working · ${plural(t.open_tasks, "open task")}</small>
      ${t.fixed?.target_rank ? `<em>${icon("target")}Target: top ${t.fixed.target_rank}</em>` : t.comp_id ? `<em class="faint">No target rank yet</em>` : t.purpose ? `<em>${esc(t.purpose)}</em>` : ""}</button>`;
  }
  const agentChip = (a, role) => `<button type="button" class="ctl-chip" data-go="agent:${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(role || a.title || "")}</small></span>${dot(a.status)}</button>`;
  function deptView() {
    const d = nodeD.department, sub = d.kind === "subnet";
    const camps = sub ? (d.campaigns || []).map(c => `<span class="ctl-pill">${icon("pickaxe")}${esc(c.comp)} · ${esc(c.status)}${c.target ? ` · campaign target top ${c.target}` : ""}</span>`).join("") : "";
    return `${head(sub ? [btn("wizard", "trophy", "New competition team", true, `data-netuid="${d.netuid}"`), btn("goview", "pickaxe", "Open in My subnets", false, `data-v="mining"`)]
                       : [btn("team", "plus", "New team", true), btn("rename", "edit", "Rename"), btn("dissolve", "trash", "Dissolve")],
                 sub ? `A subnet department: each of its competitions is a team. ${camps ? "" : "No campaign yet."}` : esc(d.purpose || ""))}
      ${camps ? `<div class="ctl-pills">${camps}</div>` : ""}
      <section class="ctl-lv"><h3 class="ctl-lvh">${icon("users")}Teams <small class="faint">${d.teams.length}</small></h3>
        <div class="ctl-dgrid">${d.teams.map(t => teamCard(t, d)).join("") || `<p class="faint">${sub ? "No competition team yet." : "No team yet: make one, then add agents to it."}</p>`}</div></section>
      ${d.staff?.length ? `<section class="ctl-lv"><h3 class="ctl-lvh">${icon("group")}Department staff <small class="faint">in no team</small></h3><div class="ctl-chips">${d.staff.map(a => agentChip(a)).join("")}</div></section>` : ""}`;
  }

  // ---------- team ----------
  function teamView() {
    const t = nodeD.team, f = nodeD.fixed, comp = !!t.comp_id;
    const acts = [btn("member", "userplus", "Add an agent", true), btn("recommend", "sparkle", "Recommend agents"), btn("task", "list", "New task")];
    if (comp) acts.push(btn("board", "external", "Open the board"));
    else acts.push(btn("rename", "edit", "Rename"), btn("dissolve", "trash", "Dissolve"));
    const fixed = f ? `<section class="card ctl-card ctl-fixed ${f.gap.state}"><div class="ctl-h"><h3>${icon("target")}Mission <span class="badge new">Predefined</span></h3><span class="ctl-acts">${btn("fixed", "edit", f.configured ? "Edit" : "Configure")}<button type="button" class="btn sm" data-ctlm-open="comp:${f.comp_id}">${icon("eye")}Open mission</button></span></div>
        <div class="ctl-fx"><div><small>Target</small><b>${f.target_rank ? `Top ${f.target_rank}` : "–"}</b></div><div><small>Rank now</small><b>${f.standing?.rank ?? "–"}${f.standing?.of ? `<span class="faint"> / ${f.standing.of}</span>` : ""}</b></div>
          <div><small>Today's budget</small>${meter(f.used_today, f.budget)}</div><div><small>Deadline</small><b>${esc(f.deadline || f.ends || "–")}</b></div></div>
        <p class="ctl-gap">${icon(f.gap.state === "met" ? "check" : f.gap.state === "behind" ? "up" : "info")}${esc(f.gap.text)}</p>
        ${f.objectives ? `<p class="small"><b>Objectives</b> ${esc(f.objectives)}</p>` : ""}${f.constraints ? `<p class="small"><b>Constraints</b> ${esc(f.constraints)}</p>` : ""}
        ${f.requirements.length ? `<p class="small"><b>Requirements</b> ${f.requirements.map(esc).join(" · ")}</p>` : ""}
        <p class="faint small">SN${f.netuid} · ${esc(f.name || (f.number != null ? `Competition ${f.number}` : ""))}${f.link ? ` · <a href="${esc(f.link)}" target="_blank" rel="noopener">competition page</a>` : ""} · <button type="button" class="linkbtn" data-act="topminer">Top miner plan</button></p></section>` : "";
    const agents = `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("bot")}Agents <small class="faint">${t.agents.length}</small></h3></div>
      ${t.agents.length ? `<ul class="ctl-list ctl-agents">${t.agents.map(a => `<li><button type="button" class="ctl-arow" data-go="agent:${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(a.title)} · ${esc(SYS[a.system] || a.system)}${a.current ? ` · ${esc(a.current)}` : ""}</small></span></button>
          <span class="ctl-ra">${a.assigned ? badge("new", "assigned") : ""}${a.key === t.manager ? badge("clear", t.kind === "competition" ? "Director" : "Lead") : ""}<span class="ctl-load" title="Assignments and work in progress, of its capacity">${a.load}/${a.cap}</span>${dot(a.status)}
          ${a.assigned || (a.system !== "teams" && a.key !== t.manager) ? `<button type="button" class="iconbtn sm" data-unassign="${esc(a.key)}" title="Take ${esc(a.name)} off this team" aria-label="Take ${esc(a.name)} off this team">${icon("close")}</button>` : ""}</span></li>`).join("")}</ul>` : `<p class="faint">No agent yet: add one, or let AXoR recommend.</p>`}</section>`;
    const tasks = `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("list")}Tasks</h3>${btn("task", "plus", "New")}</div>${taskList(nodeD.tasks)}
      ${nodeD.board?.length ? `<h4 class="ctl-h4">${icon("columns")}On the team's board</h4><ul class="ctl-list">${nodeD.board.slice(0, 10).map(b => `<li><span><b>${esc(b.title)}</b><small>${esc(b.priority || "")} · ${esc(when(b.updated))}</small></span>${badge(b.status === "done" ? "clear" : b.status === "working" ? "clear" : "muted", b.status)}</li>`).join("")}</ul>` : ""}</section>`;
    const hist = `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("clock")}History</h3></div>${(nodeD.history || []).length ? `<ul class="ctl-list ctl-hist">${nodeD.history.map(h => `<li><span><b>${esc(h.text || h.action || "")}</b><small>${esc(h.actor || h.kind || "")} · ${esc(when(h.ts))}</small></span></li>`).join("")}</ul>` : `<p class="faint">Nothing yet.</p>`}</section>`;
    return `${head(acts, `${comp ? "Competition team" : "Team"} in ${esc(nodeD.department.name)}${t.purpose && !comp ? ` · ${esc(t.purpose)}` : ""}`)}
      ${typeof CtlMissions !== "undefined" ? CtlMissions.teamLine(t.id) : ""}${fixed}<div class="ctl-grid2">${agents}${tasks}</div>${hist}`;
  }

  // ---------- agent workspace ----------
  function agentView() {
    const p = wsD.agent, rt = p.runtime || {};
    const tabs = [["chat", "chat", "Conversation"], ["exec", "list", "Execution"], ["know", "book", "Knowledge"], ["profile", "card", "Profile"]];
    const ahead = `<div class="ctl-ahead">${av(p, "lg")}<div><h2>${esc(p.name)} ${dot(p.status === "active" ? (rt.running ? "busy" : "ok") : "off")}</h2><p>${esc(p.title)} · ${esc(SYS[p.system] || p.system)}${p.unit ? ` · <button type="button" class="linkbtn" data-go="${esc(p.unit.ref)}">${esc(p.unit.name)}</button>` : ""}</p>
        ${p.assignments.length ? `<p class="small">Also serves ${p.assignments.map(a => `<button type="button" class="linkbtn" data-go="${esc(a.ref)}">${esc(a.unit)}</button>`).join(", ")}</p>` : ""}
        <p class="small faint">${rt.running ? `Working now${rt.current ? `: ${esc(rt.current)}` : ""} · ` : ""}${p.load} of ${p.cap} busy · L${p.autonomy}${p.perf?.score != null ? ` · score ${Math.round(p.perf.score)}` : ""}${p.manager ? ` · reports to ${esc(p.manager)}` : ""}</p></div></div>`;
    const tabsH = `<div class="ctl-tabs" role="tablist">${tabs.map(([k, ic, l]) => `<button type="button" role="tab" class="ctl-tab ${wsTab === k ? "on" : ""}" aria-selected="${wsTab === k}" data-ws="${k}">${icon(ic)}${l}</button>`).join("")}</div>`;
    const body = wsTab === "chat" ? chatPane() : `<div class="ctl-wsbody">${wsTab === "exec" ? execPane() : wsTab === "know" ? knowPane() : profilePane()}</div>`;
    return `${head([btn("agenttask", "list", "Give a task"), typeof CtlOps !== "undefined" ? `<button type="button" class="btn sm" data-ctlo-agent="${esc(p.key)}" title="Its objective, task, last run, failures, scores, versions, cost and next action, from its own records">${icon("eye")}Operational status</button>` : ""])}${ahead}${tabsH}${body}`;
  }
  const items = () => (wsD?.messages || []).filter(m => m.status !== "running" || m.role === "user").map(m => m.role === "user"
    ? { kind: "user", text: m.body, attachments: [...(m.meta.files || []).map(f => ({ kind: f.kind || "file", label: f.label })), ...(m.meta.images || []).map(n => ({ kind: "file", label: `🖼 ${n}` })),
                                                  ...(m.meta.audio ? [{ kind: "file", label: `🎙 ${m.meta.video || m.meta.audio}` }] : []), ...(m.meta.web ? [{ kind: "file", label: "🌐 web search" }] : [])] }
    : m.status === "failed" ? { kind: "note", text: `${wsD.agent.name} couldn't answer: ${m.body}` } : { kind: "assistant", text: m.body, tokens: m.tokens, model: m.model, suggestions: m.meta.suggestions, id: m.id });
  const busyNow = () => (wsD?.messages || []).some(m => m.status === "running");
  function chatPane() {
    const c = [["team", "Team brief"], ["fixed", "Mission"], ["tasks", "My tasks"]];
    const pend = [...media.images.map((x, i) => `<span class="ac-att"><img src="${x.thumb}" alt=""><span>${esc(x.name)}</span><button type="button" data-unmedia="i${i}" aria-label="Remove ${esc(x.name)}">${icon("close")}</button></span>`),
                  ...(media.audio ? [`<span class="ac-att">${icon("speaker")}<span>${esc(media.video || media.audio.name)}${media.audio.secs ? ` · ${media.audio.secs}s` : ""}</span><button type="button" data-unmedia="a" aria-label="Remove the recording">${icon("close")}</button></span>`] : [])].join("");
    return `<div class="ctl-chat" data-cx-panel>
      <div class="ctl-log chat-log cx-log" aria-live="polite">${Chat.log(items(), { busy: busyNow(), agent: { name: wsD.agent.name }, empty: `<div class="empty ctl-empty">${icon("chat")}<p>Talk to ${esc(wsD.agent.name)}: ask, attach a file, a picture or a video, record your voice, or search the web together. A task ${esc(wsD.agent.name)} proposes runs only once you approve it.</p></div>` })}</div>
      <div class="ctl-ctx">${c.map(([k, l]) => `<button type="button" class="chip ${media.ctx.has(k) ? "on" : ""}" data-ctx="${k}" aria-pressed="${media.ctx.has(k)}" title="Inject this into the agent's context">${icon("pin")}${l}</button>`).join("")}
        <button type="button" class="chip ${media.web ? "on" : ""}" data-web aria-pressed="${media.web}" ${wsD.media.search ? "" : "disabled title='Web search is off on this server'"}>${icon("globe")}Web search</button>
        <button type="button" class="chip ${media.speak ? "on" : ""}" data-speak aria-pressed="${media.speak}" title="Read the agent's answers aloud">${icon("speaker")}Read answers aloud</button>
        <span class="ctl-pend">${pend}</span></div>
      <div class="ctl-composer"></div></div>`;
  }
  function execPane() {
    const runs = wsD.runs, ts = wsD.tasks;
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("list")}Tasks from the Control Hub</h3>${btn("agenttask", "plus", "Give a task")}</div>${taskList(ts)}</section>
      ${wsD.board.length ? `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("columns")}On its team's board</h3></div><ul class="ctl-list">${wsD.board.map(b => `<li><span><b>${esc(b.title)}</b><small>${esc(when(b.updated))}</small></span>${badge(b.status === "working" ? "clear" : "muted", b.status)}</li>`).join("")}</ul></section>` : ""}
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("radio")}Runs</h3><button type="button" class="linkbtn" data-goview="studio">Traces in Agent operations</button></div>
        ${table(["Work", "Status", "Tokens", "Model", "When"], runs.map(r => `<tr><td>${esc(r.title || r.kind)}${r.error ? `<br><small class="ctl-errt">${esc(r.error)}</small>` : ""}</td><td>${esc(r.status)}</td><td>${tok(r.tokens)}</td><td class="small">${esc(r.model || "")}</td><td class="nowrap">${esc(when(r.started))}</td></tr>`), "No run recorded yet.")}</section>`;
  }
  function knowPane() {
    const k = wsD.knowledge, p = wsD.agent;
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("book")}What ${esc(p.name)} knows and works from</h3></div>
      <ul class="ctl-list">${p.team ? `<li><span><b>Team objective</b><small>${esc(p.team.name)}: ${esc(p.team.goal || "–")}</small></span></li>` : ""}
        ${p.fixed ? `<li><span><b>Mission</b><small>Top ${p.fixed.target_rank}${p.fixed.objectives ? ` · ${esc(p.fixed.objectives)}` : ""}</small></span></li>` : ""}
        ${k.notes ? `<li><span><b>Team notebook</b><small>${plural(k.notes, "note")} the team wrote</small></span></li>` : ""}
        ${k.memory.filter(Boolean).map(m => `<li><span><b>Memory</b><small>${esc(m)}</small></span></li>`).join("")}</ul>
      <p class="small">Inject context into a message with the chips above the message box (team brief, the team's mission, its tasks), attach Drive or Source files with +, or turn on web search.</p>
      <p>${k.links.map(l => `<button type="button" class="btn sm" data-goview="${esc(l.view)}" ${l.comp ? `data-comp="${l.comp}"` : ""}>${icon("external")}${esc(l.label)}</button>`).join(" ")}</p></section>`;
  }
  function profilePane() {
    const p = wsD.agent, sk = Object.entries(p.skills || {});
    return `<section class="card ctl-card"><dl class="ctl-kv">
      <div><dt>System</dt><dd>${esc(SYS[p.system] || p.system)}</dd></div><div><dt>Model</dt><dd>${esc(p.model || "Automatic")}</dd></div>
      <div><dt>Authority</dt><dd>L${p.autonomy}</dd></div><div><dt>Capacity</dt><dd>${p.load} of ${p.cap}</dd></div>
      <div><dt>Reports to</dt><dd>${esc(p.manager || "you")}</dd></div><div><dt>Score</dt><dd>${p.perf?.score != null ? Math.round(p.perf.score) : "not enough finished work yet"}</dd></div></dl>
      ${sk.length ? `<h4 class="ctl-h4">Skills</h4><div class="ctl-pills">${sk.map(([s, v]) => `<span class="ctl-pill">${esc(s)} <b>${v}/5</b></span>`).join("")}</div>` : ""}
      ${p.job ? `<h4 class="ctl-h4">Job</h4><p class="small">${esc(p.job)}</p>` : ""}${p.instructions ? `<h4 class="ctl-h4">Instructions</h4><pre class="ctl-pre">${esc(p.instructions)}</pre>` : ""}
      <p class="faint small">Edit an agent where it lives: ${p.system === "teams" ? `<button type="button" class="linkbtn" data-act="board">its Competition team</button>` : p.system === "company" ? `<button type="button" class="linkbtn" data-goview="company">the Company</button>` : p.system === "workforce" ? `<button type="button" class="linkbtn" data-goview="workforce">Workforce</button>` : `<button type="button" class="linkbtn" data-goview="agents">Agents</button>`}; its place and authority in <button type="button" class="linkbtn" data-goview="org">Organization HQ</button>.</p></section>`;
  }
  // proposals and web sources sit under the answer they came with
  function afterLog() {
    const log = root()?.querySelector(".ctl-log"); if (!log) return;
    Chat.enhance(log, true);
    const its = items();
    its.forEach((it, n) => {
      if (it.kind !== "assistant") return;
      const m = wsD.messages.find(x => x.id === it.id); if (!m) return;
      const at = log.querySelector(`.cx-msg[data-n="${n}"]`); if (!at) return;
      const extra = [];
      if (m.meta.web?.length) extra.push(`<div class="ctl-src">${icon("globe")}${m.meta.web.map(w => `<a href="${esc(w.url)}" target="_blank" rel="noopener noreferrer">${esc(w.title)}</a>`).join("")}</div>`);
      if (m.meta.transcript) extra.push(`<details class="ctl-tr"><summary>${icon("speaker")}What was heard</summary><p>${esc(m.meta.transcript)}</p></details>`);
      if (m.meta.notes?.length) extra.push(`<p class="ctl-noteline">${icon("info")}${esc(m.meta.notes.join(" · "))}</p>`);
      const pr = m.meta.proposal;
      if (pr) extra.push(`<div class="ctl-prop ${pr.status}">${icon("list")}<span><b>Proposed task: ${esc(pr.title)}</b><small>${esc(pr.detail || "")}</small></span>
        ${pr.status === "proposed" ? `<span class="ctl-ra"><button type="button" class="btn sm primary" data-prop="${m.id}" data-ok="1">Approve and run</button><button type="button" class="btn sm" data-prop="${m.id}" data-ok="0">Decline</button></span>` : badge(pr.status === "approved" ? "clear" : "muted", pr.status === "approved" ? "Approved" : "Declined")}</div>`);
      if (extra.length) { const box = document.createElement("div"); box.className = "ctl-extra"; box.innerHTML = extra.join(""); (at.nextElementSibling?.classList.contains("cx-acts") ? at.nextElementSibling : at).after(box); }
    });
    if (media.speak) {  // read new answers aloud
      const last = [...wsD.messages].reverse().find(m => m.role === "agent" && m.status === "done");
      if (last && last.id > lastSpoken && lastSpoken) { try { speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(last.body.replace(/[#*_`>]/g, ""))); } catch { /* no voices */ } }
      if (last) lastSpoken = last.id;
    }
  }
  function mountChat() {
    const box = root().querySelector(".ctl-composer"); if (!box) return;
    const key = "ctl:" + wsD.agent.key, off = wsD.agent.status !== "active";
    const extra = `<button type="button" class="iconbtn sm" data-media="picture" title="Attach a picture" aria-label="Attach a picture" ${off ? "disabled" : ""}>${icon("image")}</button>
      <button type="button" class="iconbtn sm" data-media="camera" title="Take a picture with your camera" aria-label="Take a picture with your camera" ${off ? "disabled" : ""}>${icon("eye")}</button>
      <button type="button" class="iconbtn sm" data-media="video" title="Attach a video: its frames are seen, its sound transcribed" aria-label="Attach a video" ${off ? "disabled" : ""}>${icon("film")}</button>
      <button type="button" class="iconbtn sm ${rec ? "on" : ""}" data-media="record" title="${rec ? "Stop recording" : "Record your voice (transcribed on the server)"}" aria-label="Record your voice" aria-pressed="${!!rec}" ${off ? "disabled" : ""}><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="${rec ? 5 : 7}" ${rec ? 'fill="currentColor"' : ""}/></svg></button>`;
    box.innerHTML = Chat.composer({ key, mic: true, plus: true, extra, busy: busyNow(), disabled: off, placeholder: off ? `${wsD.agent.name} is off` : `Message ${wsD.agent.name}…`, usage: false });
    Chat.mount(box.querySelector("form"), { key, mic: true, onSend: send });
    Chat.bind(root().querySelector(".ctl-chat"), { items, onSay: t => { Chat.setDraft(key, t); Chat.focus(key); } });
    afterLog();
    if (busyNow()) watch();
  }
  async function send(text, atts) {
    const key = wsD.agent.key;
    const body = { text, files: atts.filter(a => a.kind === "file" || a.kind === "source").map(a => ({ kind: a.kind, id: String(a.id) })),
                   images: media.images.map(x => ({ name: x.name, mime: x.mime, data: x.data })), audio: media.audio ? { name: media.audio.name, mime: media.audio.mime, data: media.audio.data } : null,
                   video: media.video, web: media.web, context: [...media.ctx], ...Chat.choice() };
    try { await api(`${B}/agents/${encodeURIComponent(key)}/chat`, { method: "POST", body }); }
    catch (e) { err(e); return false; }
    media.images = []; media.audio = null; media.video = "";
    wsD.messages = await api(`${B}/agents/${encodeURIComponent(key)}/messages`);
    draw(agentView(), true);
    const f = root().querySelector(".cx-composer textarea"); if (f) f.disabled = true;
    watch();
  }
  function watch() {
    clearTimeout(poll);
    poll = setTimeout(async () => {
      if (!on || !cur?.startsWith("agent:") || !wsD) return;
      try { wsD.messages = await api(`${B}/agents/${encodeURIComponent(wsD.agent.key)}/messages`); } catch { return watch(); }
      if (busyNow()) { draw(agentView(), true); return watch(); }
      el_rerender();
    }, 1500);
  }
  function el_rerender() { const el = root(); if (el) el.dataset.agent = ""; draw(agentView(), true); }

  // ---------- media: pictures, camera, video frames and sound, voice recording ----------
  const b64 = blob => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.onerror = no; r.readAsDataURL(blob); });
  function frame(src, w, h, max = 1600) {
    const s = Math.min(1, max / Math.max(w, h)), c = document.createElement("canvas");
    c.width = Math.round(w * s); c.height = Math.round(h * s);
    c.getContext("2d").drawImage(src, 0, 0, c.width, c.height);
    const url = c.toDataURL("image/jpeg", .85);
    return { mime: "image/jpeg", data: url.split(",")[1], thumb: url };
  }
  function addImage(x) { if (media.images.length >= 4) return Auth.toast("Up to four pictures on a message"); media.images.push(x); refreshCtx(); }
  function refreshCtx() { const el = root()?.querySelector(".ctl-ctx"); if (!el) return; const f = document.createElement("div"); f.innerHTML = chatPane(); el.innerHTML = f.querySelector(".ctl-ctx").innerHTML; }
  function pick(accept) { return new Promise(ok => { const i = document.createElement("input"); i.type = "file"; i.accept = accept; i.multiple = accept.startsWith("image"); i.onchange = () => ok([...i.files]); i.click(); }); }
  async function picture() {
    for (const f of (await pick("image/png,image/jpeg,image/gif,image/webp")).slice(0, 4)) {
      if (f.size <= 12_000_000 && f.type !== "image/gif") {  // drawn smaller as a JPEG (a data: URL: the page's CSP allows those for pictures)
        const url = `data:${f.type};base64,${await b64(f)}`;
        const img = await new Promise((ok, no) => { const im = new Image(); im.onload = () => ok(im); im.onerror = no; im.src = url; }).catch(() => null);
        if (img) { addImage({ name: f.name, ...frame(img, img.naturalWidth, img.naturalHeight) }); continue; }
      }
      if (f.size > 5_000_000) { Auth.toast(`${f.name} is over 5 MB`); continue; }
      addImage({ name: f.name, mime: f.type, data: await b64(f), thumb: "" });
    }
  }
  async function camera() {
    if (!navigator.mediaDevices?.getUserMedia) return Auth.toast("This browser can't use a camera here");
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 } }, audio: false }); }
    catch { return Auth.toast("Camera access was blocked"); }
    dlg("Take a picture", `<video class="ctl-cam" autoplay playsinline muted></video><p class="faint small">The picture goes to ${esc(wsD.agent.name)} with your next message.</p>`, "Take the picture", async (_, f) => {
      const v = f.querySelector("video"); if (!v.videoWidth) throw new Error("The camera isn't ready yet.");
      addImage({ name: `camera ${new Date().toLocaleTimeString()}.jpg`, ...frame(v, v.videoWidth, v.videoHeight) });
    }, false, () => stream.getTracks().forEach(t => t.stop()));
    const v = $("#ctl-dlg video"); v.srcObject = stream;
  }
  async function video() {
    const [f] = await pick("video/*"); if (!f) return;
    const v = document.createElement("video"); v.muted = true; v.preload = "auto"; v.src = URL.createObjectURL(f);
    try {
      await new Promise((ok, no) => { v.onloadedmetadata = ok; v.onerror = () => no(new Error("This browser can't read that video.")); });
      const n = Math.min(4, 4 - media.images.length), dur = v.duration || 0;
      for (let i = 0; i < n; i++) {
        v.currentTime = dur ? dur * (i + .5) / n : 0;
        await new Promise(ok => { v.onseeked = ok; setTimeout(ok, 3000); });
        if (v.videoWidth) media.images.push({ name: `${f.name} @ ${Math.round(v.currentTime)}s`, ...frame(v, v.videoWidth, v.videoHeight, 1280) });
      }
      media.video = f.name;
      if (f.size <= 25_000_000) media.audio = { name: f.name, mime: f.type, data: await b64(f), secs: Math.round(dur) };
      else Auth.toast("The video is over 25 MB: its frames go, its sound isn't transcribed");
      refreshCtx();
    } catch (e) { err(e); } finally { URL.revokeObjectURL(v.src); }
  }
  async function record() {
    if (rec) { rec.stop(); return; }
    if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) return Auth.toast("This browser can't record here");
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return Auth.toast("Microphone access was blocked"); }
    const chunks = [], t0 = Date.now();
    rec = new MediaRecorder(stream);
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" }); rec = null;
      media.audio = { name: `voice ${new Date().toLocaleTimeString()}.webm`, mime: blob.type, data: await b64(blob), secs: Math.round((Date.now() - t0) / 1000) };
      media.video = "";
      mountChat(); refreshCtx();
    };
    rec.start(); mountChat();
  }
  function stopMedia() { if (rec) { try { rec.stop(); } catch { /* already stopped */ } } try { speechSynthesis.cancel(); } catch { /* none */ } }

  // ---------- dialogs ----------
  function dlg(title, body, ok, run, wide = false, onclose = null) {
    let el = document.getElementById("ctl-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "ctl-dlg"; document.body.append(el); }
    el.className = `modal ctl-dlg ${wide ? "wide" : ""}`;
    el.innerHTML = `<form method="dialog" class="ctl-form co-form" novalidate><div class="ctl-h"><h3>${title}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      <div class="ctl-dbody">${body}</div><p class="err" role="alert"></p>${ok ? `<div class="row end"><button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn primary">${ok}</button></div>` : ""}</form>`;
    const f = el.querySelector("form"), e = f.querySelector(".err");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    el.onclose = () => { onclose?.(); };
    f.onsubmit = async ev => {
      ev.preventDefault(); if (!run) return el.close();
      const b = f.querySelector("[type=submit]"); b.classList.add("loading"); b.disabled = true; e.textContent = "";
      try { const r = await run(new FormData(f), f); if (r !== false) el.close(); }
      catch (x) { e.textContent = x?.message || "Something went wrong."; }
      finally { b.classList.remove("loading"); b.disabled = false; }
    };
    el.showModal();
    return el;
  }
  const field = (label, html, hint = "") => `<label class="ctl-field"><span>${label}</span>${html}${hint ? `<small class="faint">${hint}</small>` : ""}</label>`;
  async function changed(goTo) { await loadTree(true); if (goTo !== undefined) go(goTo); else if (on) render(true); }

  function deptDlg() {
    dlg("New department", `${field("Name", `<input type="text" name="name" maxlength="80" required placeholder="Handshake, Research & Development…">`)}
      ${field("Kind", `<select name="kind"><option value="division">Business division: owns results and its teams</option><option value="department">Shared department: a capability others draw on</option></select>`)}
      ${field("Purpose", `<textarea name="purpose" rows="2" maxlength="300"></textarea>`)}<p class="faint small">A subnet becomes a department on its own when you start a Bittensor mission on it.</p>`, "Create", async fd => {
      const r = await api(`${B}/departments`, { method: "POST", body: { name: fd.get("name"), kind: fd.get("kind"), purpose: fd.get("purpose") } });
      Auth.toast(r.ok); changed(r.id);
    });
  }
  function teamDlg(dept) {
    dlg("New team", `${field("Name", `<input type="text" name="name" maxlength="80" required>`)}${field("Purpose", `<textarea name="purpose" rows="2" maxlength="300"></textarea>`)}
      <p class="faint small">Then add agents to it, by hand or with AXoR's recommendation.</p>`, "Create", async fd => {
      const r = await api(`${B}/teams`, { method: "POST", body: { dept, name: fd.get("name"), purpose: fd.get("purpose") } });
      Auth.toast(r.ok); changed(r.id);
    });
  }
  function renameDlg(ref, name) {
    dlg("Rename", field("Name", `<input type="text" name="name" maxlength="80" required value="${esc(name)}">`), "Save", async fd => {
      await api(`${B}/units/${encodeURIComponent(ref)}`, { method: "PATCH", body: { name: fd.get("name") } }); changed();
    });
  }
  async function dissolve(ref) {
    await UI.confirm({ title: "Dissolve this unit?", body: "Its teams and people move up to the unit above it (or become unplaced). Missions and reporting lines stay valid.", ok: "Dissolve",
      run: async () => { await api(`${B}/units/${encodeURIComponent(ref)}`, { method: "DELETE" }); Auth.toast("Dissolved"); changed(null); } }).catch(err);
  }
  async function memberDlg(ref) {
    const [t] = findTeam(ref);
    const on_ = new Set((t?.agents || []).map(a => a.key));
    const all = [];
    for (const d of allDepts()) { d.teams.forEach(tm => tm.agents.forEach(a => all.push({ ...a, where: tm.name }))); (d.staff || []).forEach(a => all.push({ ...a, where: d.name })); }
    (tree.bittensor?.staff || []).forEach(a => all.push({ ...a, where: tree.bittensor.name })); tree.unplaced.forEach(a => all.push({ ...a, where: "not placed" }));
    if (tree.org.ceo) all.push({ ...tree.org.ceo, where: "CEO" });
    const seen = new Set(), list = all.filter(a => !on_.has(a.key) && a.status !== "off" && !seen.has(a.key) && seen.add(a.key) && a.key !== tree.org.ceo?.key);
    dlg(`Add an agent to ${esc(t?.name || "the team")}`, `<input type="search" class="ctl-find" placeholder="Find an agent…" aria-label="Find an agent">
      <div class="ctl-pickl" role="radiogroup">${list.map(a => `<label class="ctl-pick" data-q="${esc((a.name + " " + a.title + " " + a.where).toLowerCase())}"><input type="radio" name="key" value="${esc(a.key)}" required>${av(a)}<span><b>${esc(a.name)}</b><small>${esc(a.title)} · ${esc(a.where)} · ${a.load}/${a.cap} busy</small></span>${dot(a.status)}</label>`).join("") || `<p class="faint">Every agent is on this team already.</p>`}</div>
      ${field("How", `<select name="how"><option value="assign">Assign: serves this team too, keeps its home (one agent, several teams)</option><option value="home">Move here: this team becomes its home</option></select>`)}
      ${field("Role here", `<input type="text" name="role" maxlength="80" placeholder="Python engineer, reviewer…">`)}`, "Add", async fd => {
      if (!fd.get("key")) throw new Error("Pick an agent.");
      const r = await api(`${B}/units/${encodeURIComponent(ref)}/members`, { method: "POST", body: { key: fd.get("key"), how: fd.get("how"), role: fd.get("role") || "" } });
      Auth.toast(r.ok); changed();
    }, true);
    const find = $("#ctl-dlg .ctl-find");
    find.oninput = () => $$("#ctl-dlg .ctl-pick").forEach(l => l.hidden = !l.dataset.q.includes(find.value.toLowerCase().trim()));
  }
  function recDlg(ref) {
    const mode = tree.mode;
    const el = dlg("Recommend agents", `${field("Skills the team needs", `<input type="text" name="skills" placeholder="python, benchmarking, research" maxlength="200">`, "Separate with commas. Leave empty for the best general fit.")}
      ${field("How many", `<input type="number" name="size" min="1" max="8" value="2">`)}<div class="ctl-recs"></div>
      <p class="faint small">${esc(tree.modes[mode])}</p>`, mode === "manual" ? "Recommend" : mode === "hybrid" ? "Recommend, then ask me" : "Recommend and assign", async (fd, f) => {
      const body = { skills: String(fd.get("skills") || "").split(",").map(s => s.trim()).filter(Boolean), size: +fd.get("size") || 2 };
      const box = f.querySelector(".ctl-recs");
      if (!f.dataset.shown) {
        const r = await api(`${B}/units/${encodeURIComponent(ref)}/recommend`, { method: "POST", body });
        box.innerHTML = recHtml(r);
        f.dataset.shown = "1";
        f.querySelector("[type=submit]").textContent = mode === "manual" ? "Done" : mode === "hybrid" ? "Ask for my approval" : "Assign them";
        return false;
      }
      if (mode === "manual") return true;
      const r = await api(`${B}/units/${encodeURIComponent(ref)}/staff`, { method: "POST", body });
      Auth.toast(r.done.map(d => `${d.name}: ${d.result}`).join(" · ") || "Nobody fits");
      changed();
    }, true);
    el.querySelector("[name=skills]").oninput = () => { delete el.querySelector("form").dataset.shown; };
  }
  function recHtml(r) {
    const bar = (k, v) => `<span class="ctl-fbar" title="${esc(k)} ${Math.round(v * 100)}%"><i style="width:${Math.round(v * 100)}%"></i></span>`;
    const picks = new Set(r.picks.map(p => p.key));
    return `<p class="small"><b>${plural(r.picks.length, "pick")}</b>, expected about ${tok(r.expected_tokens_day)} tokens a day together.</p>
      <div class="ctl-tw-wrap"><table class="ctl-table ctl-rec"><thead><tr><th>Agent</th><th>Score</th>${Object.keys(r.weights).map(k => `<th title="weight ${r.weights[k]}">${esc(k)}</th>`).join("")}<th>Tokens/day</th></tr></thead>
      <tbody>${r.candidates.slice(0, 10).map(c => `<tr class="${picks.has(c.key) ? "ctl-picked" : ""} ${c.full ? "ctl-full" : ""}"><td><b>${esc(c.name)}</b>${picks.has(c.key) ? ` ${badge("clear", "pick")}` : c.full ? ` ${badge("muted", "full")}` : ""}<br><small class="faint">${esc(c.why)}</small></td><td><b>${c.score}</b></td>
        ${Object.keys(r.weights).map(k => `<td>${bar(k, c.factors[k])}</td>`).join("")}<td>${tok(c.expected_tokens_day)}${c.estimated ? "*" : ""}</td></tr>`).join("")}</tbody></table></div>
      <p class="faint small">* estimated: no finished runs of this agent in 30 days.</p>`;
  }
  function taskDlg(team, agent, opt = {}) {  // opt: { mission: "comp:N" | "mx:N", parent: a task (a subtask), done: called after }
    const [t] = team ? findTeam(team) : [null];
    const teams = []; for (const d of allDepts()) for (const tm of d.teams) teams.push([tm.id, tm.name]);
    if (!teams.length) return Auth.toast("Make a team first: a task belongs to a team.");
    const people = t ? t.agents : [];
    const par = opt.parent;
    dlg(par ? `New subtask · ${esc(par.title)}` : "New dynamic task", `${field("Team", `<select name="team">${teams.map(([id, n]) => `<option value="${esc(id)}" ${id === (team || "") ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`)}
      ${par ? `<input type="hidden" name="parent" value="${par.id}"><p class="faint small">A subtask serves the same mission as its parent task.</p>`
        : field("Serves", `<select name="mission">${opt.mission ? `<option value="${esc(opt.mission)}" selected>This mission</option>` : ""}<option value="">Its team's mission (a Competition team's task serves its Bittensor mission)</option><option value="none">No mission: a standalone task (routine work)</option></select>`)}
      ${field("Title", `<input type="text" name="title" maxlength="160" required placeholder="Research a new technology, investigate a failure…">`)}
      ${field("Detail", `<textarea name="detail" rows="4" maxlength="4000"></textarea>`)}
      <div class="ctl-row2">${field("Who", `<select name="agent"><option value="auto">Automatic: AXoR picks</option><option value="">Nobody yet</option>${people.map(a => `<option value="${esc(a.key)}" ${a.key === agent ? "selected" : ""}>${esc(a.name)} · ${esc(a.title)}</option>`).join("")}${agent && !people.some(a => a.key === agent) ? `<option value="${esc(agent)}" selected>${esc(findAgent(agent)?.name || agent)}</option>` : ""}</select>`)}
      ${field("Runs as", `<select name="route"><option value="auto">Automatic</option><option value="board">The team's board (Competition teams)</option><option value="agent">The agent's own run, for your review</option><option value="mission">Its own custom mission (Mission Control), when it's too big for one owner</option></select>`)}</div>
      <div class="ctl-row2">${field("Priority", `<select name="priority"><option value="medium">Medium</option><option value="high">High</option><option value="low">Low</option></select>`)}
      ${field("Custom mission budget ($)", `<input type="number" name="budget" min="0.05" max="200" step="0.05" value="2">`, "Only when it runs as a custom mission")}</div>
      <label class="ctl-check"><input type="checkbox" name="start" checked> Start now</label>`, "Create", async fd => {
      const r = await api(`${B}/tasks`, { method: "POST", body: { team: fd.get("team"), title: fd.get("title"), detail: fd.get("detail"), agent: fd.get("agent"), route: fd.get("route"),
                                                                  priority: fd.get("priority"), budget: +fd.get("budget") || 2, start: fd.get("start") === "on",
                                                                  mission: fd.get("mission") || "", parent: +fd.get("parent") || null } });
      Auth.toast(`Task created${r.agent ? ` for ${r.agent}` : ""} · ${r.route === "board" ? "on the team's board" : r.route === "mission" ? "as a custom mission" : "as an agent run"}`);
      if (typeof CtlMissions !== "undefined") CtlMissions.invalidate();
      opt.done ? opt.done() : changed();
    }, true);
  }
  async function taskView(id) {
    const t = await api(`${B}/tasks/${id}`).catch(err); if (!t) return;
    const [tone, l] = TSTAT[t.status] || ["muted", t.status];
    const el = dlg(`${esc(t.title)} ${badge(tone, l)}`, `<p class="faint small">${t.kind === "fixed" ? "Fixed task · " : ""}${esc(t.route === "board" ? "On the team's board" : t.route === "mission" ? "Runs as a custom mission (Mission Control)" : "Agent run")}${t.agent ? ` · ${esc(t.agent)}` : ""} · from ${esc(t.origin || "you")}</p>
      ${t.detail ? `<p>${esc(t.detail)}</p>` : ""}${t.result ? `<div class="ctl-result">${md(t.result)}</div>` : t.summary ? `<p>${esc(t.summary)}</p>` : ""}
      ${t.route === "agent" && ["review", "needs_input", "failed", "todo"].includes(t.status) ? `${field("Send it back with a note", `<textarea name="feedback" rows="2" maxlength="2000"></textarea>`)}
        ${field("Or delegate to", `<select name="agent"><option value="">Keep ${esc(t.agent || "")}</option>${allDepts().flatMap(d => d.teams.flatMap(tm => tm.agents)).filter((a, i, xs) => xs.findIndex(x => x.key === a.key) === i).map(a => `<option value="${esc(a.key)}">${esc(a.name)} · ${esc(a.title)}</option>`).join("")}</select>`)}` : ""}
      <div class="ctlj-slot"></div>
      <details><summary>History</summary><ul class="ctl-list">${t.history.map(h => `<li><span><b>${esc(h.what)}</b><small>${esc(h.by)} · ${esc(when(h.ts))}</small></span></li>`).join("")}</ul></details>
      <div class="row end ctl-tacts">${t.route === "board" ? `<button type="button" class="btn" data-x data-tboard>Open the board</button>` : ""}
        ${t.route === "agent" && t.status === "review" ? `<button type="button" class="btn primary" data-tdo="done">Accept</button>` : ""}
        ${t.route === "agent" && ["review", "needs_input", "failed", "todo"].includes(t.status) ? `<button type="button" class="btn" data-tdo="again">${t.status === "todo" ? "Start" : "Run again"}</button>` : ""}
        ${t.route === "agent" && !["done", "cancelled"].includes(t.status) ? `<button type="button" class="btn" data-tdo="cancelled">Cancel</button>` : ""}</div>`, null, null, true);
    el.querySelector(".ctl-result") && Chat.enhance(el.querySelector(".ctl-result"), false);
    if (typeof CtlJourney !== "undefined") CtlJourney.strip(el.querySelector(".ctlj-slot"), `ctl:t${t.id}`);  // where it started → where it is now
    el.querySelector("[data-tboard]")?.addEventListener("click", () => { const [tm] = findTeam(t.team); if (tm?.comp_id) MiningWork.openPage(tm.comp_id); });
    el.querySelectorAll("[data-tdo]").forEach(b => b.onclick = async () => {
      const k = b.dataset.tdo, fd = new FormData(el.querySelector("form"));
      try {
        if (k === "again") {
          const ag = fd.get("agent");
          if (t.status === "todo" && !fd.get("feedback") && !ag) await api(`${B}/tasks/${id}/start`, { method: "POST", body: {} });
          else await api(`${B}/tasks/${id}`, { method: "PATCH", body: { status: "todo", feedback: fd.get("feedback") || "", ...(ag ? { agent: ag } : {}) } });
        } else await api(`${B}/tasks/${id}`, { method: "PATCH", body: { status: k } });
        el.close(); Auth.toast(k === "done" ? "Accepted" : k === "cancelled" ? "Cancelled" : "Running again"); render(false);
      } catch (e) { el.querySelector(".err").textContent = e.message; }
    });
  }
  function fixedDlg(t) {
    const f = nodeD?.fixed?.comp_id === t.comp_id ? nodeD.fixed : { target_rank: t.fixed?.target_rank, objectives: t.fixed?.objectives || "", constraints: "", requirements: [], deadline: "" };
    dlg(`Mission · ${esc(t.name)}`, `${field("Target", `<div class="ctl-ranks">${Array.from({ length: 10 }, (_, i) => i + 1).map(n => `<label><input type="radio" name="target" value="${n}" ${n === (f.target_rank || 10) ? "checked" : ""}><span>Top ${n}</span></label>`).join("")}</div>`, "Reach and hold this miner rank on the competition.")}
      ${field("Objectives", `<textarea name="objectives" rows="2" maxlength="600">${esc(f.objectives || "")}</textarea>`)}
      ${field("Constraints", `<textarea name="constraints" rows="2" maxlength="3000">${esc(f.constraints || "")}</textarea>`)}
      ${field("Requirements", REQS.map(r => `<label class="ctl-check"><input type="checkbox" name="req" value="${esc(r)}" ${(f.requirements || []).includes(r) ? "checked" : ""}> ${esc(r)}</label>`).join(""))}
      ${field("Deadline", `<input type="date" name="deadline" value="${esc(f.deadline || "")}">`)}`, "Save", async fd => {
      await api(`${B}/fixed/${t.comp_id}`, { method: "PATCH", body: { target_rank: +fd.get("target"), objectives: fd.get("objectives"), constraints: fd.get("constraints"), requirements: fd.getAll("req"), deadline: fd.get("deadline") || "" } });
      Auth.toast("Saved: the team's goal follows"); changed();
    }, true);
  }

  // ---------- the fixed-task wizard: subnet → discover → select → configure → workforce → validate → activate ----------
  const STEPS = ["Subnet", "Discover", "Select", "Configure", "Workforce", "Validate", "Activate"];
  async function wizard(pre = {}) {
    const w = { step: 0, netuid: pre.netuid ?? null, subnets: null, found: null, mech: 0, comp: null, own: { number: "", name: "" }, target: 10, objectives: "", constraints: "", requirements: [REQS[1]],
                budget: 150000, deadline: "", team: "auto", agents: [], autostaff: false, checks: null };
    const el = dlg("New mission · Bittensor", `<ol class="ctl-steps"></ol><div class="ctl-wz"></div>`, null, null, true);
    el.classList.add("ctl-wizard");
    const box = el.querySelector(".ctl-wz"), steps = el.querySelector(".ctl-steps"), e = el.querySelector(".err");
    const body = () => {
      const b = { netuid: w.netuid, mech: w.mech, target_rank: w.target, objectives: w.objectives, constraints: w.constraints, requirements: w.requirements, budget: w.budget, deadline: w.deadline,
                  team: w.team, agents: w.agents, autostaff: w.autostaff };
      if (w.comp) Object.assign(b, { number: w.comp.number ?? null, name: w.comp.name || "", link: w.comp.link || "", starts: w.comp.starts || "", ends: w.comp.ends || "", share: w.comp.share ?? null,
                                     status: ["upcoming", "active", "closed"].includes(w.comp.state) ? w.comp.state : "active" });
      else Object.assign(b, { number: w.own.number === "" ? null : +w.own.number, name: w.own.name || (w.own.number === "" ? `Competition ${w.mech + 1}` : "") });
      return b;
    };
    const nav = (back, next, label = "Next") => `<div class="row end ctl-wnav">${back ? `<button type="button" class="btn" data-wz="back">Back</button>` : ""}${next ? `<button type="button" class="btn primary" data-wz="next">${label}</button>` : ""}</div>`;
    async function show() {
      e.textContent = "";
      steps.innerHTML = STEPS.map((s, i) => `<li class="${i < w.step ? "done" : i === w.step ? "on" : ""}" ${i === w.step ? 'aria-current="step"' : ""}><b>${i < w.step ? icon("check") : i + 1}</b>${s}</li>`).join("");
      if (w.step === 0) {
        if (!w.subnets) { box.innerHTML = `<p class="faint">${icon("cycle")}Loading the subnets…</p>`; w.subnets = await api(`${B}/wizard/subnets`).catch(x => ({ subnets: [], note: x.message })); }
        box.innerHTML = `<p class="small">Pick the subnet. It becomes the department; the competition you pick next becomes the team.</p>
          <input type="search" class="ctl-find" placeholder="Find a subnet by name or number…" aria-label="Find a subnet">${w.subnets.note ? `<p class="faint small">${esc(w.subnets.note)}</p>` : ""}
          <div class="ctl-pickl ctl-subs">${w.subnets.subnets.map(s => `<label class="ctl-pick" data-q="${esc(`sn${s.netuid} ${s.netuid} ${s.name}`.toLowerCase())}"><input type="radio" name="sn" value="${s.netuid}" ${s.netuid === w.netuid ? "checked" : ""}>
            <span class="ctl-snb">SN${s.netuid}</span><span><b>${esc(s.name || `Subnet ${s.netuid}`)}</b><small>${s.mine ? `${plural(s.mine, "campaign")} of yours` : s.emission != null ? `emission ${(+s.emission * 100).toFixed(2)}%` : ""}</small></span></label>`).join("")}</div>
          ${field("Or its number", `<input type="number" name="snn" min="1" max="4096" value="${w.netuid ?? ""}">`)}${nav(false, true)}`;
        const find = box.querySelector(".ctl-find");
        find.oninput = () => box.querySelectorAll(".ctl-pick").forEach(l => l.hidden = !l.dataset.q.includes(find.value.toLowerCase().trim()));
        box.querySelectorAll("[name=sn]").forEach(r => r.onchange = () => { box.querySelector("[name=snn]").value = r.value; });
      } else if (w.step === 1) {
        box.innerHTML = `<p class="faint">${icon("cycle")}Reading SN${w.netuid}'s competitions…</p>`;
        try { w.found = await api(`${B}/wizard/subnets/${w.netuid}`); } catch (x) { box.innerHTML = `<p class="err">${esc(x.message)}</p>${nav(true, false)}`; return; }
        const f = w.found;
        box.innerHTML = `<h4>SN${f.netuid}${f.name ? ` · ${esc(f.name)}` : ""}</h4>
          <p class="small"><b>${plural(f.chain.length, "chain competition")}</b> (the subnet's mechanisms, each with its own share of emission)${f.named.length ? ` and <b>${plural(f.named.length, "named competition")}</b>` : ""}.</p>
          <ul class="ctl-list">${f.chain.map(c => `<li><span><b>${esc(c.name)}</b><small>share ${Math.round((c.share || 0) * 100)}%${c.campaign ? " · in My subnets already" : ""}</small></span></li>`).join("")}</ul>
          ${f.named.length ? `<ul class="ctl-list">${f.named.map(n => `<li><span><b>${esc(n.name || `#${n.number}`)}${n.number != null ? ` <span class="faint">#${n.number}</span>` : ""}</b><small>${esc(n.state || "")}${n.starts ? ` · ${esc(n.starts)}` : ""}${n.ends ? ` → ${esc(n.ends)}` : ""} · from ${esc(n.source)}${n.team ? " · has a team" : ""}</small>${n.description ? `<small class="faint">${esc(n.description.slice(0, 220))}</small>` : ""}</span></li>`).join("")}</ul>` : `<p class="faint small">No named competition was found: you'll name it yourself.</p>`}
          ${f.note ? `<p class="faint small">${esc(f.note)}</p>` : ""}${nav(true, true)}`;
      } else if (w.step === 2) {
        const f = w.found, open_n = f.named.filter(n => !n.team);
        box.innerHTML = `${f.chain.length > 1 ? field("Chain competition", `<div class="ctl-pickl">${f.chain.map(c => `<label class="ctl-pick"><input type="radio" name="mech" value="${c.mech}" ${c.mech === w.mech ? "checked" : ""}><span><b>${esc(c.name)}</b><small>share ${Math.round((c.share || 0) * 100)}%</small></span></label>`).join("")}</div>`) : ""}
          ${field("Competition", `<div class="ctl-pickl">${open_n.map((n, i) => `<label class="ctl-pick"><input type="radio" name="comp" value="${i}" ${w.comp && w.comp.number === n.number && w.comp.name === n.name ? "checked" : ""}><span><b>${esc(n.name || `#${n.number}`)}</b><small>${esc(n.state || "")}${n.ends ? ` · ends ${esc(n.ends)}` : ""}</small></span></label>`).join("")}
            <label class="ctl-pick"><input type="radio" name="comp" value="own" ${!w.comp ? "checked" : ""}><span><b>Name it myself</b><small>For a subnet without named competitions, or one not listed</small></span></label></div>`)}
          <div class="ctl-row2">${field("Number", `<input type="number" name="num" min="0" value="${esc(w.own.number)}">`)}${field("Name", `<input type="text" name="nm" maxlength="80" value="${esc(w.own.name)}" placeholder="Competition ${w.mech + 1}">`)}</div>${nav(true, true)}`;
        box._open = open_n;
      } else if (w.step === 3) {
        box.innerHTML = `${field("Target miner rank", `<div class="ctl-ranks">${Array.from({ length: 10 }, (_, i) => i + 1).map(n => `<label><input type="radio" name="target" value="${n}" ${n === w.target ? "checked" : ""}><span>Top ${n}</span></label>`).join("")}</div>`, "The team's persistent objective: reach and hold this rank.")}
          ${field("Objectives", `<textarea name="obj" rows="2" maxlength="600" placeholder="Beat the median score by 5%, cut latency…">${esc(w.objectives)}</textarea>`)}
          ${field("Constraints", `<textarea name="con" rows="2" maxlength="3000" placeholder="No paid APIs, Python 3.11, keep the miner's memory under 8 GB…">${esc(w.constraints)}</textarea>`)}
          ${field("Execution requirements", REQS.map(r => `<label class="ctl-check"><input type="checkbox" name="req" value="${esc(r)}" ${w.requirements.includes(r) ? "checked" : ""}> ${esc(r)}</label>`).join(""))}
          <div class="ctl-row2">${field("Budget (tokens a day)", `<input type="number" name="budget" min="10000" max="20000000" step="10000" value="${w.budget}">`, "The team's governor holds new work at it.")}${field("Deadline", `<input type="date" name="deadline" value="${esc(w.deadline)}">`)}</div>${nav(true, true)}`;
      } else if (w.step === 4) {
        if (!tree) await loadTree();
        const people = []; const seen = new Set();
        for (const d of allDepts()) { for (const tm of d.teams) tm.agents.forEach(a => { if (a.system !== "teams" && !seen.has(a.key)) { seen.add(a.key); people.push({ ...a, where: tm.name }); } }); (d.staff || []).forEach(a => { if (!seen.has(a.key)) { seen.add(a.key); people.push({ ...a, where: d.name }); } }); }
        (tree.bittensor?.staff || []).forEach(a => { if (!seen.has(a.key)) { seen.add(a.key); people.push({ ...a, where: tree.bittensor.name }); } });
        box.innerHTML = `${field("The team's own workforce", `<select name="team"><option value="auto" ${w.team === "auto" ? "selected" : ""}>Automatic: the agent pack that fits the competition</option><option value="default" ${w.team === "default" ? "selected" : ""}>The default five</option><option value="empty" ${w.team === "empty" ? "selected" : ""}>Empty: I'll add them</option></select>`)}
          ${field("Assign specialists from your organization", `<input type="search" class="ctl-find" placeholder="Find…" aria-label="Find an agent"><div class="ctl-pickl ctl-multi">${people.filter(a => a.status !== "off").map(a => `<label class="ctl-pick" data-q="${esc((a.name + " " + a.title + " " + a.where).toLowerCase())}"><input type="checkbox" name="ag" value="${esc(a.key)}" ${w.agents.includes(a.key) ? "checked" : ""}>${av(a)}<span><b>${esc(a.name)}</b><small>${esc(a.title)} · ${esc(a.where)} · ${a.load}/${a.cap} busy</small></span></label>`).join("") || `<p class="faint">No other agent yet.</p>`}</div>`, "They keep their home and serve this team too.")}
          <label class="ctl-check"><input type="checkbox" name="auto" ${w.autostaff ? "checked" : ""}> Let AXoR recommend two more (${esc(tree.modes[tree.mode])})</label>${nav(true, true)}`;
        const find = box.querySelector(".ctl-find");
        find.oninput = () => box.querySelectorAll(".ctl-pick").forEach(l => l.hidden = !l.dataset.q.includes(find.value.toLowerCase().trim()));
      } else if (w.step === 5) {
        box.innerHTML = `<p class="faint">${icon("cycle")}Checking dependencies, resources, the sandbox and permissions…</p>`;
        try { w.checks = await api(`${B}/wizard/validate`, { method: "POST", body: body() }); } catch (x) { box.innerHTML = `<p class="err">${esc(x.message)}</p>${nav(true, false)}`; return; }
        box.innerHTML = `<ul class="ctl-checks">${w.checks.checks.map(c => `<li class="c-${c.level}">${icon(c.level === "ok" ? "check" : c.level === "warn" ? "alert" : "ban")}<span>${esc(c.text)}</span></li>`).join("")}</ul>
          ${w.checks.ok ? `<p class="small">${icon("check")} Ready. Activating is your approval.</p>` : `<p class="err">Fix what's marked before activating.</p>`}${nav(true, w.checks.ok, "Review and activate")}`;
      } else {
        const b = body();
        box.innerHTML = `<dl class="ctl-kv"><div><dt>Department</dt><dd>SN${b.netuid}${w.found?.name ? ` · ${esc(w.found.name)}` : ""}</dd></div><div><dt>Team</dt><dd>${esc(b.name || `Competition ${b.number}`)}</dd></div>
          <div><dt>Objective</dt><dd>Top ${b.target_rank}${b.objectives ? ` · ${esc(b.objectives)}` : ""}</dd></div><div><dt>Budget</dt><dd>${tok(b.budget)} tokens a day</dd></div>
          <div><dt>Workforce</dt><dd>${esc({ auto: "Automatic pack", default: "Default five", empty: "Empty" }[b.team])}${b.agents.length ? ` + ${plural(b.agents.length, "specialist")}` : ""}${b.autostaff ? " + AXoR's picks" : ""}</dd></div>
          <div><dt>Deadline</dt><dd>${esc(b.deadline || "none")}</dd></div></dl>
          <p class="faint small">This makes the My subnets campaign if there's none yet, opens the Competition team with its workforce and starts controlled execution under the team's governor.</p>${nav(true, true, "Activate")}`;
      }
    }
    box.addEventListener("click", async ev => {
      const b = ev.target.closest("[data-wz]"); if (!b) return;
      if (b.dataset.wz === "back") { w.step = Math.max(0, w.step - 1); return show(); }
      try {
        if (w.step === 0) { const n = +(box.querySelector("[name=sn]:checked")?.value || box.querySelector("[name=snn]").value); if (!n) throw new Error("Pick a subnet."); if (n !== w.netuid) { w.found = null; w.comp = null; } w.netuid = n; }
        if (w.step === 2) {
          const m = box.querySelector("[name=mech]:checked"); if (m) w.mech = +m.value;
          const c = box.querySelector("[name=comp]:checked")?.value;
          w.own = { number: box.querySelector("[name=num]").value, name: box.querySelector("[name=nm]").value.trim() };
          w.comp = c && c !== "own" ? box._open[+c] : null;
          if (!w.comp && w.own.number === "" && !w.own.name && w.found.chain.length < 1) throw new Error("Name the competition.");
        }
        if (w.step === 3) {
          w.target = +(box.querySelector("[name=target]:checked")?.value || 10); w.objectives = box.querySelector("[name=obj]").value; w.constraints = box.querySelector("[name=con]").value;
          w.requirements = [...box.querySelectorAll("[name=req]:checked")].map(x => x.value); w.budget = +box.querySelector("[name=budget]").value || 150000; w.deadline = box.querySelector("[name=deadline]").value;
        }
        if (w.step === 4) { w.team = box.querySelector("[name=team]").value; w.agents = [...box.querySelectorAll("[name=ag]:checked")].map(x => x.value); w.autostaff = box.querySelector("[name=auto]").checked; }
        if (w.step === 6) {
          b.classList.add("loading"); b.disabled = true;
          const r = await api(`${B}/wizard/activate`, { method: "POST", body: body() });
          el.close();
          Auth.toast(`Activated: ${r.staffed?.length ? r.staffed.map(s => `${s.name || s.key}: ${s.result}`).join(" · ") : "the team is assembling"}`);
          open_.add("bittensor"); open_.add(r.department); S_("open", [...open_]);
          return changed(r.team || r.department);
        }
        w.step++; show();
      } catch (x) { e.textContent = x.message; b.classList.remove("loading"); b.disabled = false; }
    });
    show();
  }

  // ---------- events ----------
  function wire() {
    const el = root(); if (!el || el.dataset.wired) return;
    el.dataset.wired = "1";
    el.addEventListener("click", async e => {
      const t = e.target;
      const g = t.closest("[data-go]"); if (g) return go(g.dataset.go || null);
      const s = t.closest("[data-sec]"); if (s && !cur) { sec = s.dataset.sec; return draw(hubView()); }
      const gv = t.closest("[data-goview]"); if (gv) { if (gv.dataset.comp) return MiningWork.openPage(+gv.dataset.comp); return setView(gv.dataset.goview); }
      const md_ = t.closest("[data-mode]"); if (md_) {
        try { await api(`${B}/settings`, { method: "POST", body: { mode: md_.dataset.mode } }); if (tree) tree.mode = md_.dataset.mode; if (hubD) hubD.mode = md_.dataset.mode; Auth.toast(tree?.modes?.[md_.dataset.mode] || "Saved"); render(false); } catch (x) { err(x); }
        return;
      }
      const rq = t.closest("[data-req]"); if (rq) { try { await api(`${B}/requests/${rq.dataset.req}`, { method: "POST", body: { ok: rq.dataset.ok === "1" } }); Auth.toast(rq.dataset.ok === "1" ? "Approved" : "Declined"); changed(); } catch (x) { err(x); } return; }
      const tk = t.closest("[data-task]"); if (tk) return taskView(+tk.dataset.task);
      const fx = t.closest("[data-fixed]"); if (fx) { const tm = allDepts().flatMap(d => d.teams).find(x => x.comp_id === +fx.dataset.fixed); return tm && fixedDlg(tm); }
      const un = t.closest("[data-unassign]"); if (un) {
        return UI.confirm({ title: "Take this agent off the team?", body: "An assigned agent goes back to serving only its home; one placed here moves up to the department.", ok: "Take off",
          run: async () => { const r = await api(`${B}/units/${encodeURIComponent(cur)}/members/${encodeURIComponent(un.dataset.unassign)}`, { method: "DELETE" }); Auth.toast(r.ok); changed(); } }).catch(err);
      }
      const ws = t.closest("[data-ws]"); if (ws) { wsTab = ws.dataset.ws; const r = root(); r.dataset.agent = ""; return draw(agentView(), true); }
      const cx = t.closest("[data-ctx]"); if (cx) { media.ctx.has(cx.dataset.ctx) ? media.ctx.delete(cx.dataset.ctx) : media.ctx.add(cx.dataset.ctx); return refreshCtx(); }
      if (t.closest("[data-web]")) { media.web = !media.web; return refreshCtx(); }
      if (t.closest("[data-speak]")) { media.speak = !media.speak; if (!media.speak) try { speechSynthesis.cancel(); } catch { /* none */ } return refreshCtx(); }
      const um = t.closest("[data-unmedia]"); if (um) { const k = um.dataset.unmedia; if (k === "a") { media.audio = null; media.video = ""; } else media.images.splice(+k.slice(1), 1); return refreshCtx(); }
      const mm = t.closest("[data-media]"); if (mm) { const k = mm.dataset.media; return (k === "picture" ? picture : k === "camera" ? camera : k === "video" ? video : record)().catch(err); }
      const pr = t.closest("[data-prop]"); if (pr) {
        try { const r = await api(`${B}/agents/${encodeURIComponent(wsD.agent.key)}/messages/${pr.dataset.prop}/proposal`, { method: "POST", body: { ok: pr.dataset.ok === "1" } });
              Auth.toast(r.task ? `Task started: ${r.task.title}` : "Declined"); render(true); } catch (x) { err(x); }
        return;
      }
      const a = t.closest("[data-act]"); if (!a) return;
      const k = a.dataset.act;
      if (k === "refresh") { await loadTree(true); return render(true); }
      if (k === "wizard") return wizard(a.dataset.netuid ? { netuid: +a.dataset.netuid } : {});
      if (k === "dept") return deptDlg();
      if (k === "team") return teamDlg(cur);
      if (k === "rename") return renameDlg(cur, nodeD?.team?.name || nodeD?.department?.name || "");
      if (k === "dissolve") return dissolve(cur);
      if (k === "member") return memberDlg(cur);
      if (k === "recommend") return recDlg(cur);
      if (k === "task") return taskDlg(cur?.startsWith("u:") ? cur : null);
      if (k === "agenttask") { const p = wsD?.agent; return taskDlg(p?.unit?.ref || p?.assignments?.[0]?.ref || null, p?.key); }
      if (k === "fixed") return fixedDlg(nodeD.team);
      if (k === "board") { const c = nodeD?.team?.comp_id || wsD?.agent?.team?.comp_id; if (c) MiningWork.openPage(c); return; }
      if (k === "topminer") {  // the team's own Top miner tab: roadmap, validation set, scorecard, elite team
        try { store.set("mw.sub2", "topminer"); } catch { /* storage off: the page opens on its last tab */ }
        MiningWork.openPage(nodeD.team.comp_id); try { MiningWork.go("topminer"); } catch { /* the page draws it when it loads */ }
        return;
      }
      if (k === "goview") return setView(a.dataset.v);
      if (k === "classic") { classicNext = true; return setView("command"); }
    });
  }

  function init() {
    wireTree(); wire();
    if (!Auth.me()) return;
    // the sidebar's Control Hub entry opens the hub itself, not the last node (capture: before app.js's setView runs)
    $("#side")?.addEventListener("click", e => { if (e.target.closest("#nav-command")) { cur = null; drawTree(); } }, true);
    addEventListener("hashchange", () => {  // a pasted or clicked #control/<node> link on an open page
      const h = decodeURIComponent(location.hash.slice(1));
      if (!/^control(\/|$)/.test(h)) return;
      route(h);
      if (S.view !== "control") setView("control"); else render(true);
      drawTree();
    });
    loadTree();
    clearInterval(treeTimer); treeTimer = setInterval(() => { if (!document.hidden) loadTree(); }, 60000);
  }
  return { init, open, stop, route, go, classic, refresh: () => loadTree(true), taskDlg, taskView, rerender: () => render(false),
           teams: () => allDepts().flatMap(d => (d.teams || []).map(t => ({ id: t.id, name: t.name, kind: t.kind, dept: d.name }))),
           showSec: s => { sec = s; if (cur) go(null); else if (on && hubD) draw(hubView()); else go(null); } };
})();
