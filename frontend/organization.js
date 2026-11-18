/* Organization HQ (organization.py + organization_hq.py, #org, sidebar → Agents): one organization over the Company, Workforce,
   Competition teams and your own agents. Eight sections, each one question:
   - Organization chart: you (owner · chairman) → the CEO → Executive Office, business divisions and shared departments; solid
     lines report, dashed lines sponsor, dotted lines are assignments. Drag an agent onto a unit to move it.
   - Executive Office: the CEO and the executives, one company-wide portfolio each, the departments each one sponsors.
   - Business divisions: each division's general manager, leadership and Competition teams as operational environments
     (Director, squads, goal, board, budget, knowledge, experiments, the Director's report, specialists on loan).
   - Workforce departments: the eight shared departments: sponsor, manager, members, affiliated agents, who's on loan where.
   - Agent directory: one identity per agent: home, department, manager, assignments, authority, availability; and runtime.
   - Teams & squads: assignments (one identity, many scoped assignments), missions, delegation.
   - Knowledge & experience: knowledge read through from its systems, lessons learned, expertise, performance.
   - Governance & authority: approvals, the authority ladder, safeguards, reserved decisions, levels, policies, budgets, audit.
   The old tab names (overview, agents, missions, delegation, authority, performance, runtime, approvals) still open their place. */
const Organization = (() => {
  const B = "/api/org";
  const TABS = [["chart", "branch", "Organization chart"], ["exec", "star", "Executive Office"], ["divisions", "layers", "Business divisions"],
                ["departments", "group", "Workforce departments"], ["directory", "users", "Agent directory"], ["teams", "target", "Teams & squads"],
                ["knowledge", "book", "Knowledge & experience"], ["governance", "shield", "Governance & authority"]];
  const ALIAS = { overview: ["chart"], agents: ["directory", "profiles"], runtime: ["directory", "runtime"], missions: ["teams", "missions"],
                  delegation: ["teams", "delegation"], authority: ["governance"], approvals: ["governance"], performance: ["knowledge"] };
  const SYS = { company: ["layers", "Company", "company"], workforce: ["group", "Workforce", "workforce"], hub: ["bot", "Your agents", "agents"],
                teams: ["trophy", "Competition teams", "teams"] };
  const KIND = { division: ["layers", "Division"], department: ["group", "Department"], team: ["users", "Team"], squad: ["pickaxe", "Squad"] };
  const TASK = { awaiting: ["caution", "Waiting for you"], open: ["new", "Open"], blocked: ["caution", "Blocked"], escalated: ["avoid", "Escalated"],
                 done: ["clear", "Done"], cancelled: ["muted", "Cancelled"] };
  const REQ = { pending: ["caution", "Waiting for you"], applied: ["clear", "Applied"], approved: ["clear", "Approved"], rejected: ["scam", "Rejected"],
                expired: ["muted", "Expired"], failed: ["scam", "Couldn't apply"] };
  let d = null, failed = "", tab = null, sub = {}, on = false, wired = false, timer = null, loading = false;
  let q = "", sysF = "all", tierF = "all", recs = null, recFor = {}, audit = null, dragKey = null, know = null, knowing = false;
  const root = () => document.getElementById("ogz");
  const err = e => e && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const A = k => d?.agents.find(a => a.key === k);
  const U = id => d?.units.find(u => u.id === id);
  const M = id => d?.missions.find(m => m.id === id);
  const P = k => d?.portfolios.find(p => p.key === k);
  const nm = k => k ? esc(d?.names[k] || A(k)?.name || "an agent") : "you";
  const badge = (tone, text, ic = "") => `<span class="badge ${tone}">${ic ? icon(ic) : ""}${text}</span>`;
  const lvl = n => `<span class="ogz-lvl l${n}" title="${esc(d.levels[n].about)}">L${n} ${esc(d.levels[n].name)}</span>`;
  const initials = s => String(s || "?").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const av = a => `<span class="ogz-av s-${a?.system || "x"}" aria-hidden="true">${esc(initials(a?.name))}</span>`;
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const typing = () => { const a = document.activeElement; return !!a && root()?.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName); };
  const dlgOpen = () => document.getElementById("ogz-dlg")?.open;
  const isComp = u => (u?.link || "").startsWith("mw_comp:");
  const kids = (id, kind) => d.units.filter(u => u.parent_id === id && (!kind || u.kind === kind));
  const members = (id, skip) => d.agents.filter(a => a.unit_id === id && a.key !== skip);
  const subtree = id => { const out = new Set(), todo = [id]; while (todo.length) { const x = todo.pop(); if (out.has(x)) continue; out.add(x); kids(x).forEach(k => todo.push(k.id)); } return out; };
  const people = id => { const ids = subtree(id); return d.agents.filter(a => ids.has(a.unit_id)); };
  const tierName = t => d.tiers.find(x => x.tier === t)?.name || t;
  const titleOf = a => a.portfolio && P(a.portfolio) && a.title !== P(a.portfolio).title ? `${a.title} · ${P(a.portfolio).short}` : a.title;
  const exec = () => d.units.find(u => u.link === "exec");
  const deptName = id => U(id)?.name || "";

  // ---------- data ----------
  function open() {
    on = true; wire();
    if (tab === null) { let t = "chart"; try { t = store.get("ogz.tab", "chart"); } catch {} setTab(t); }
    if (!d) put(root(), Loading.line("Opening Organization HQ…"));
    load();
  }
  function stop() { on = false; clearTimeout(timer); }
  function setTab(t) {
    const [to, s] = ALIAS[t] || [t];
    tab = TABS.some(([k]) => k === to) ? to : "chart";
    if (s) sub[tab] = s;
    try { store.set("ogz.tab", tab); } catch {}
    if (tab === "knowledge" && !know && d) loadKnow();
  }
  function show(t) { if (t) setTab(t); if (S.view !== "org") setView("org"); else render(); }
  async function load() {
    if (loading) return; loading = true;
    try { d = await api(B); failed = ""; } catch (e) { failed = e.message; } finally { loading = false; }
    count();
    if (tab === "knowledge" && !know) loadKnow();
    if (!typing() && !dlgOpen()) render();
    clearTimeout(timer);
    if (on) timer = setTimeout(() => { if (!document.hidden) load(); else timer = setTimeout(load, 20000); }, 20000);
  }
  async function loadKnow() {
    if (knowing) return; knowing = true;
    try { know = await api(`${B}/knowledge`); } catch (e) { know = { error: e.message }; } finally { knowing = false; }
    if (on && !typing() && !dlgOpen()) render();
  }
  function count() {
    const c = document.getElementById("c-org"); if (!c || !d) return;
    const n = d.counts.pending + d.counts.escalated;
    c.textContent = n ? String(n) : ""; c.hidden = !n;
  }
  async function change(op, p, btn) {
    return busy(btn, async () => {
      const r = await api(`${B}/change`, { method: "POST", body: { op, p } });
      d = r.view; count(); render();
      const msg = typeof r.result === "string" ? r.result : r.result?.msg;
      if (msg) toast(msg.charAt(0).toUpperCase() + msg.slice(1));
      return r;
    });
  }
  async function propose(kind, p, btn) {
    return busy(btn, async () => {
      const r = await api(`${B}/propose`, { method: "POST", body: { kind, p } });
      d = r.view; count(); render();
      toast(r.request_id ? "Sent to Governance → Approvals: it applies once you approve it." : (r.applied || "Done"));
      return r;
    });
  }
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- frame ----------
  function render() {
    const el = root(); if (!el || !on) return;
    if (!d) return put(el, failed ? `<div class="card empty">${esc(failed)} <button type="button" class="linkbtn" data-ogz="reload">Try again</button></div>` : Loading.line("Opening Organization HQ…"));
    const c = d.counts, o = d.org;
    const badges = { directory: c.agents, teams: c.assignments + c.missions + c.open_tasks, governance: c.pending + c.escalated };
    const spine = [["chart", "star", "You", o.owner_title], ["exec", "target", A(o.ceo)?.name || "No CEO", "CEO · Mission Control"],
                   ["exec", "star", plural(c.executives, "executive"), "Executive Office"], ["divisions", "layers", plural(c.divisions, "division"), `${plural(c.teams, "team")} · ${plural(c.squads, "squad")}`],
                   ["departments", "group", plural(d.units.filter(u => u.kind === "department" && u.link !== "exec").length, "department"), "shared service layer"],
                   ["directory", "users", plural(c.agents, "agent"), `${c.busy} carrying work${c.working ? ` · ${c.working} working now` : ""}`]];
    const y = scrollY;
    put(el, `<div class="ogz">
      <div class="ogz-top">
        <div><p class="ogz-kick">${icon("branch")}Organization HQ</p>
          <h1>${esc(o.name)} <button type="button" class="iconbtn" data-ogz="settings" title="Name, owner and title" aria-label="Organization settings">${icon("edit")}</button></h1>
          <p class="muted">One company, many divisions. One permanent identity per agent, many scoped assignments. Shared specialist departments, not duplicated agents. Autonomous execution inside the authority you grant.</p></div>
        <div class="ogz-top-act"><button type="button" class="btn sm" data-ogz="reload">${icon("cycle")}Refresh</button></div>
      </div>
      <nav class="ogz-spine" aria-label="Organization structure">${spine.map(([t, ic, l, s], i) => `${i ? `<span class="ogz-sp-arr" aria-hidden="true">${icon("right")}</span>` : ""}<button type="button" class="ogz-sp" data-ogz-tab="${t}">${icon(ic)}<span><b>${esc(l)}</b><small>${esc(s)}</small></span></button>`).join("")}</nav>
      <nav class="ogz-tabs" role="tablist">${TABS.map(([k, ic, l]) => `<button type="button" role="tab" class="ogz-tab ${tab === k ? "on" : ""}" aria-selected="${tab === k}" data-ogz-tab="${k}">${icon(ic)}${l}${badges[k] ? ` <b class="${k === "governance" ? "warn" : ""}">${badges[k]}</b>` : ""}</button>`).join("")}</nav>
      <div class="ogz-body">${({ chart, exec: execView, divisions, departments, directory, teams, knowledge, governance })[tab]()}</div>
    </div>`);
    if (Math.abs(scrollY - y) > 1) scrollTo(0, y);
  }
  const seg = (name, items) => { const cur = sub[name] || items[0][0]; return `<div class="seg ogz-seg" role="tablist">${items.map(([k, l, n]) => `<button type="button" role="tab" aria-pressed="${cur === k}" data-ogz-sub="${name}:${k}">${l}${n ? ` <b>${n}</b>` : ""}</button>`).join("")}</div>`; };
  const kpi = (ic, l, v, s, to = "", tone = "") => `<${to ? `button type="button" data-ogz-tab="${to}"` : "div"} class="stat ${tone ? "t-" + tone : ""}"><div class="label">${icon(ic)}${l}</div><div class="value">${esc(String(v))}</div><div class="sub">${esc(s || "")}</div></${to ? "button" : "div"}>`;
  const agentNode = (a, rank, label) => `<button type="button" class="ogz-node ${rank || ""}" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(label || titleOf(a))}</small></span>${a.runtime?.running ? `<span class="ogz-live" title="Working now"></span>` : ""}</button>`;
  const hit = a => !q || `${a.name} ${a.title} ${a.ident} ${a.unit_role || ""}`.toLowerCase().includes(q.toLowerCase());
  const search = ph => `<label class="search ogz-q"><span class="sr">Find an agent</span>${icon("search")}<input type="search" data-ogz-q placeholder="${ph}" value="${esc(q)}" autocomplete="off"></label>`;
  function chip(a, extra = "") {
    const m = a.missions.length + a.work.length + a.assignments.length;
    const mgr = U(a.unit_id)?.manager_key;
    const off = a.manager && mgr && a.manager !== mgr && a.manager !== a.key;
    const role = extra || a.unit_role || titleOf(a);
    return `<button type="button" class="ogz-chip ${a.status !== "active" ? "paused" : ""}" draggable="true" data-ogz-agent="${esc(a.key)}" data-ogz-drag="${esc(a.key)}" title="${esc(`${a.name} · ${titleOf(a)} · ${a.ident}`)}">
      ${av(a)}<span><b>${esc(a.name)}</b><small>${esc(role)}${off ? ` · reports to ${nm(a.manager)}` : ""}</small></span>
      ${a.runtime?.running ? `<span class="ogz-live" title="Working now"></span>` : ""}${m ? `<em class="ogz-on" title="${plural(m, "assignment")}, mission or job">${m}</em>` : ""}</button>`;
  }
  const meter = (used, of, label = "") => {
    if (of == null) return `<span class="faint small">${label}${tok(used)} in 24 h · no allocation</span>`;
    const pct = of ? Math.min(100, Math.round(used / of * 100)) : 100;
    return `<span class="ogz-meter ${used > of ? "over" : pct > 80 ? "high" : ""}" title="${tok(used)} of ${tok(of)} tokens in the last 24 hours"><i style="width:${pct}%"></i></span><span class="small">${label}<b class="num">${tok(used)}</b> <span class="faint">of ${tok(of)} a day</span></span>`;
  };
  const avail = a => { const pct = Math.min(100, Math.round(a.load / Math.max(1, a.cap) * 100)); return `<span class="ogz-meter ${a.load >= a.cap ? "over" : pct >= 67 ? "high" : ""}" title="${a.load} of ${a.cap}"><i style="width:${pct}%"></i></span><span class="num small">${a.load}/${a.cap}</span>`; };

  // ---------- 1. organization chart ----------
  function chart() {
    const c = d.counts, ceo = A(d.org.ceo), act = Math.max(1, c.active);
    const needs = [
      ...d.requests.filter(r => r.status === "pending").map(r => ({ ic: "inbox", t: r.title, s: r.why || `Proposed by ${r.by}`, go: "governance" })),
      ...d.tasks.filter(t => t.status === "escalated" && !t.holder_key).map(t => ({ ic: "alert", t: `Escalated to you: ${t.title}`, s: "Nobody below you could resolve it.", go: "teams" })),
      ...d.issues.filter(i => i.level !== "info").map(i => ({ ic: i.level === "stop" ? "ban" : "alert", t: i.title, s: i.detail, go: /budget|alloc|cap/.test(i.kind) ? "governance" : "chart" }))];
    const unplaced = d.agents.filter(a => !a.unit_id && a.key !== d.org.ceo);
    const ex = exec();
    const divs = d.units.filter(u => u.kind === "division" && !u.parent_id);
    const depts = d.units.filter(u => u.kind === "department" && !u.parent_id && u.link !== "exec");
    const b = d.budget;
    return `<div class="stats ogz-kpis">
        ${kpi("users", "Agents", c.agents, `${c.active} active`, "directory")}${kpi("zap", "Utilization", `${Math.round(c.busy / act * 100)}%`, `${c.busy} of ${c.active} carry work`)}
        ${kpi("target", "Assignments", c.assignments + c.missions, `${plural(c.missions, "mission")} open`, "teams")}
        ${kpi("inbox", "Waiting for you", c.pending + c.escalated, c.escalated ? `${c.escalated} escalated` : "approvals", "governance", c.pending + c.escalated ? "warn" : "")}
        ${kpi("coins", "Tokens today", tok(b.today ?? 0), b.cap ? `of your ${tok(b.cap)} limit` : "no daily limit set", "governance", b.cap && b.today > b.cap * .8 ? "warn" : "")}
        ${kpi("alert", "Structure", c.issues ? plural(c.issues, "issue") : "Sound", c.issues ? "see below" : "no cycles, no broken lines", "", c.issues ? "warn" : "")}</div>
      ${needs.length ? `<section class="card ogz-needs"><div class="ogz-h"><h3>${icon("inbox")}Needs you</h3>${badge("caution", String(needs.length))}</div>
        <ul class="ogz-list">${needs.slice(0, 6).map(x => `<li><button type="button" class="ogz-row" data-ogz-tab="${x.go}">${icon(x.ic)}<span><b>${esc(x.t)}</b><small>${esc(x.s)}</small></span></button></li>`).join("")}</ul></section>` : ""}
      <div class="ogz-bar">${search("Find an agent…")}<span class="ogz-legend"><span><i class="l-solid"></i>reports to</span><span><i class="l-dash"></i>sponsors</span><span><i class="l-dot"></i>assigned to</span><span class="faint">${icon("hand")}drag an agent onto a unit to move it</span></span></div>
      <div class="ogz-tree">
        <div class="ogz-lv ogz-lv-top">
          <span class="ogz-node you">${icon("star")}<span><b>${esc(d.org.owner)}</b><small>${esc(d.org.owner_title)} · vision, strategy, investment, final authority</small></span></span>
          <span class="ogz-vl" aria-hidden="true"></span>
          ${ceo ? agentNode(ceo, "ceo", "CEO · organization-wide execution and accountability") : `<button type="button" class="ogz-node empty" data-ogz="ceo">${icon("plus")}Pick a CEO</button>`}
          ${ceo && d.org.mission_control ? (mc => `<button type="button" class="ogz-mc" data-ogz-view="mos" title="Mission Control: the missions you give, which the CEO owns and routes">${icon("target")}<span><b>Owns Mission Control</b><small>${plural(mc.running, "mission")} running${mc.waiting ? ` · ${mc.waiting} waiting for you` : ""}${mc.delivered_week ? ` · ${mc.delivered_week} delivered this week` : ""}</small></span></button>`)(d.org.mission_control) : ""}
        </div>
        <span class="ogz-vl" aria-hidden="true"></span>
        ${ex ? `<section class="ogz-lv ogz-execrow" data-ogz-drop="${ex.id}"><h3 class="ogz-lvh">${icon("star")}Executive Office <button type="button" class="linkbtn small" data-ogz-tab="exec">Open</button></h3>
          <div class="ogz-ports">${d.portfolios.map(p => { const a = A(p.holder); return a ? `<button type="button" class="ogz-port" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(p.short)} · ${esc(p.title)}</small></span></button>`
            : `<button type="button" class="ogz-port empty" data-ogz="portfolio" data-port="${p.key}">${icon("userplus")}<span><b>${esc(p.short)}</b><small>Assign an executive</small></span></button>`; }).join("")}
            ${members(ex.id).filter(a => !a.portfolio).map(a => chip(a)).join("")}</div></section>` : ""}
        <span class="ogz-vl" aria-hidden="true"></span>
        <div class="ogz-split">
          <section class="ogz-lv"><h3 class="ogz-lvh">${icon("layers")}Business divisions <span class="faint">${divs.length}</span><button type="button" class="linkbtn small" data-ogz="add-unit" data-kind="division">${icon("plus")}Division</button></h3>
            <div class="ogz-divs">${divs.map(divNode).join("") || `<p class="faint">No division yet.</p>`}</div></section>
          <section class="ogz-lv"><h3 class="ogz-lvh">${icon("group")}Shared departments · Workforce <span class="faint">${depts.length}</span><button type="button" class="linkbtn small" data-ogz="add-unit" data-kind="department">${icon("plus")}Department</button></h3>
            <p class="faint small">Professional capabilities every division draws on. Specialists are lent through assignments, never copied.</p>
            <div class="ogz-depts">${depts.map(deptNode).join("")}</div></section>
        </div>
        <section class="ogz-band ogz-loose" data-ogz-drop=""><div class="ogz-h"><h3>${icon("users")}Not placed yet <span class="faint">${unplaced.length}</span></h3></div>
          <p class="faint small">They report to you directly until you place them. Drop an agent here to take it out of its unit.</p>
          <div class="ogz-chips">${unplaced.filter(hit).map(a => chip(a)).join("") || `<span class="faint">Everyone has a place.</span>`}</div></section>
      </div>`;
  }
  function divNode(u) {
    const m = A(u.manager_key), lead = members(u.id, u.manager_key).filter(a => a.unit_role), rest = members(u.id, u.manager_key).filter(a => !a.unit_role);
    const teamsIn = kids(u.id, "team");
    if (q && ![m, ...lead, ...rest].some(a => a && hit(a)) && !teamsIn.some(t => people(t.id).some(hit))) return "";
    return `<div class="ogz-unit k-division" data-ogz-drop="${u.id}">
      <div class="ogz-uhead"><span class="ogz-uh">${icon("layers")}<b>${esc(u.name)}</b></span><span class="ogz-uact"><button type="button" class="iconbtn" data-ogz-tab="divisions" title="Open in Business divisions" aria-label="Open">${icon("external")}</button><button type="button" class="iconbtn" data-ogz="edit-unit" data-unit="${u.id}" title="Edit ${esc(u.name)}" aria-label="Edit">${icon("edit")}</button></span></div>
      <div class="ogz-mgr">${m ? `<span class="ogz-role">General manager</span>${chip(m, "General Manager")}` : `<button type="button" class="ogz-node empty sm" data-ogz="set-manager" data-unit="${u.id}">${icon("userplus")}Pick a general manager</button>`}</div>
      ${lead.length ? `<div class="ogz-chips ogz-ln">${lead.filter(hit).map(a => chip(a)).join("")}</div>` : ""}
      ${teamsIn.length ? `<div class="ogz-teams">${teamsIn.map(t => { const dir = A(t.manager_key), ppl = people(t.id); return `<div class="ogz-tmini ${isComp(t) ? "comp" : ""}" data-ogz-drop="${t.id}">
        <span class="ogz-uh">${icon(isComp(t) ? "trophy" : "users")}<b>${esc(t.name)}</b></span>
        <small>${dir ? `${isComp(t) ? "Director" : "Leader"} <button type="button" class="linkbtn" data-ogz-agent="${esc(dir.key)}">${esc(dir.name)}</button> · ` : ""}${plural(ppl.length, "agent")}${t.squads.length ? ` · ${plural(t.squads.length, "squad")}` : ""}${t.loaned_in.length ? ` · <span class="ogz-dotl">${t.loaned_in.length} on loan</span>` : ""}</small></div>`; }).join("")}</div>` : ""}
      ${rest.length ? `<details class="ogz-fold" ${q && rest.some(hit) ? "open" : ""}><summary>${plural(rest.length, "more agent")}</summary><div class="ogz-chips">${rest.filter(hit).map(a => chip(a)).join("")}</div></details>` : ""}</div>`;
  }
  function deptNode(u) {
    const m = A(u.manager_key), sp = A(u.sponsor_key), ppl = members(u.id, u.manager_key);
    const out = ppl.filter(a => a.assignments.length || a.missions.length).length;
    if (q && ![m, ...ppl].some(a => a && hit(a))) return "";
    return `<div class="ogz-unit k-department" data-ogz-drop="${u.id}">
      <div class="ogz-uhead"><span class="ogz-uh">${icon("group")}<b>${esc(u.name)}</b></span><span class="ogz-uact"><button type="button" class="iconbtn" data-ogz="edit-unit" data-unit="${u.id}" title="Edit ${esc(u.name)}" aria-label="Edit">${icon("edit")}</button></span></div>
      <p class="small ogz-spon">${sp ? `<span class="ogz-dashl">Sponsor</span> <button type="button" class="linkbtn" data-ogz-agent="${esc(sp.key)}">${esc(sp.name)}</button> <span class="faint">${esc(P(sp.portfolio)?.short || "")}</span>` : `<button type="button" class="linkbtn" data-ogz="sponsor" data-unit="${u.id}">Pick a sponsor</button>`}
        · ${m ? `managed by <button type="button" class="linkbtn" data-ogz-agent="${esc(m.key)}">${esc(m.name)}</button>` : `<span class="faint">no manager</span>`}</p>
      <p class="small faint ogz-tline">${plural(ppl.length + (m ? 1 : 0), "member")}${u.affiliated ? ` · ${u.affiliated} affiliated elsewhere` : ""}${out ? ` · <span class="ogz-dotl">${out} on assignment</span>` : ""}</p>
      ${ppl.length && (q || ppl.length <= 6) ? `<div class="ogz-chips">${ppl.filter(hit).map(a => chip(a)).join("")}</div>` : ppl.length ? `<details class="ogz-fold"><summary>${plural(ppl.length, "member")}</summary><div class="ogz-chips">${ppl.map(a => chip(a)).join("")}</div></details>` : ""}</div>`;
  }

  // ---------- 2. executive office ----------
  function execView() {
    const ceo = A(d.org.ceo), mc = d.org.mission_control, ex = exec();
    const others = ex ? members(ex.id).filter(a => !a.portfolio) : [];
    return `<div class="ogz-two">
      <section class="card ogz-seat"><div class="ogz-h"><h3>${icon("star")}${esc(d.org.owner)} · ${esc(d.org.owner_title)}</h3><button type="button" class="linkbtn" data-ogz="settings">Edit</button></div>
        <p class="small">Vision, strategy, investment and final authority. You are the human owner: the CEO coordinates, but these stay yours.</p>
        <h4 class="ogz-sub">Reserved decisions</h4><ul class="ogz-list">${d.reserved.map(r => `<li><span class="ogz-row">${icon("lock")}<span>${esc(r)}</span></span></li>`).join("")}</ul></section>
      <section class="card ogz-seat"><div class="ogz-h"><h3>${icon("target")}CEO · Mission Control</h3>${ceo ? `<button type="button" class="linkbtn" data-ogz="ceo">Change</button>` : ""}</div>
        ${ceo ? agentNode(ceo, "ceo", "CEO · organization-wide execution, resource allocation, accountability") : `<button type="button" class="ogz-node empty" data-ogz="ceo">${icon("plus")}Pick a CEO</button>`}
        <p class="small">Coordinates the executives and allocates people across ${plural(d.counts.divisions, "division")} and ${plural(d.units.filter(u => u.kind === "department" && u.link !== "exec").length, "department")}. The executives lead their functions; they don't each control every division.</p>
        ${mc ? `<button type="button" class="ogz-mc" data-ogz-view="mos">${icon("target")}<span><b>Mission Control</b><small>${plural(mc.running, "mission")} running${mc.waiting ? ` · ${mc.waiting} waiting for you` : ""} · ${mc.delivered_week} delivered this week</small></span></button>` : ""}</section></div>
      <h2 class="ogz-sec">${icon("star")}Executive staff · one portfolio each</h2>
      <div class="ogz-pgrid">${d.portfolios.map(p => { const a = A(p.holder); return `<section class="card ogz-pcard ${a ? "" : "vacant"}">
        <div class="ogz-h"><h3><span class="ogz-pshort">${esc(p.short)}</span>${esc(p.title)}</h3><button type="button" class="linkbtn" data-ogz="portfolio" data-port="${p.key}">${a ? "Change" : "Assign"}</button></div>
        <p class="faint small">${esc(p.about)}</p>
        ${a ? `<button type="button" class="ogz-who" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(a.title)}${a.title !== p.title ? ` · ${esc(p.short)}` : ""} · ${esc(SYS[a.system]?.[1] || a.system)}</small></span></button>` : `<p class="faint">Vacant.</p>`}
        <h4 class="ogz-sub">Sponsors</h4>${p.sponsors.length ? `<p class="small">${p.sponsors.map(id => `<span class="co-skill ogz-dashl">${esc(deptName(id))}</span>`).join("")}</p>` : `<p class="faint small">${p.key === "cfo" ? "Owns the budgets (Governance → Budgets)." : p.key === "cso" ? "Owns priorities across the divisions." : "No department yet."}</p>`}</section>`; }).join("")}</div>
      ${others.length ? `<section class="card"><div class="ogz-h"><h3>${icon("users")}Executive staff without a portfolio</h3></div><div class="ogz-chips">${others.map(a => chip(a)).join("")}</div>
        <p class="faint small">Give each a portfolio, or move them to a division or department.</p></section>` : ""}`;
  }

  // ---------- 3. business divisions ----------
  function divisions() {
    const divs = d.units.filter(u => u.kind === "division");
    return `<div class="ogz-bar"><p class="faint small">A division owns its results, resources and competition portfolio. Each Competition team is its own operational environment: Competition 28 and Competition 29 never share a board, files or budget, even when they borrow the same specialist.</p>
      <button type="button" class="btn sm" data-ogz="add-unit" data-kind="division">${icon("plus")}Division</button></div>
      ${divs.map(u => {
        const m = A(u.manager_key), lead = members(u.id, u.manager_key).filter(a => a.unit_role), rest = members(u.id, u.manager_key).filter(a => !a.unit_role);
        const comps = kids(u.id, "team").filter(isComp), other = kids(u.id, "team").filter(t => !isComp(t));
        return `<section class="card ogz-division"><div class="ogz-h"><div><h3 class="ogz-mt">${icon("layers")}${esc(u.name)}</h3>${u.purpose ? `<p class="faint small">${esc(u.purpose)}</p>` : ""}</div>
            <div class="row ogz-act"><button type="button" class="btn sm" data-ogz="request" data-unit="${u.id}">${icon("userplus")}Request a specialist</button><button type="button" class="btn sm" data-ogz="budget" data-unit="${u.id}">${icon("coins")}Budget</button><button type="button" class="btn sm" data-ogz="add-unit" data-kind="team" data-parent="${u.id}">${icon("plus")}Team</button><button type="button" class="iconbtn" data-ogz="edit-unit" data-unit="${u.id}" aria-label="Edit">${icon("edit")}</button></div></div>
          <div class="ogz-dhead">
            <div class="ogz-mgr"><span class="ogz-role">General manager</span>${m ? chip(m, "General Manager · owns the division's results") : `<button type="button" class="ogz-node empty sm" data-ogz="set-manager" data-unit="${u.id}">${icon("userplus")}Pick a general manager</button>`}</div>
            <div class="ogz-mgr"><span class="ogz-role">Budget</span><span class="ogz-mline">${meter(u.spent_day, u.allocation)}</span>${u.allocation != null && u.allocated_below ? `<small class="faint">${tok(u.allocated_below)} of it allocated to its teams</small>` : ""}</div></div>
          ${lead.length ? `<div><span class="ogz-role">Leadership</span><div class="ogz-leads">${lead.map(a => `<button type="button" class="ogz-leadc" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(a.unit_role)}</small>${a.dept_id ? `<em>${esc(deptName(a.dept_id))}</em>` : ""}</span></button>`).join("")}</div></div>` : ""}
          ${comps.length ? `<div class="ogz-envs">${comps.map(env).join("")}</div>` : u.link === "og:bittensor" || /bittensor/i.test(u.name) ? `<p class="faint">No Competition team is open. Start one from My subnets → Competition teams.</p>` : ""}
          ${other.length ? `<div class="ogz-units">${other.map(unitBox).join("")}</div>` : ""}
          ${rest.length ? `<details class="ogz-fold"><summary>${plural(rest.length, "specialist")} in the division</summary><div class="ogz-chips">${rest.map(a => chip(a)).join("")}</div></details>` : ""}
          ${u.loaned_in.length ? `<p class="small"><span class="ogz-dotl">On loan here</span> ${u.loaned_in.map(x => `<button type="button" class="linkbtn" data-ogz-agent="${esc(x.key)}">${nm(x.key)}</button> <span class="faint">(${esc(x.role)}, L${x.scope})</span>`).join(", ")}</p>` : ""}</section>`;
      }).join("") || `<div class="card empty">No division yet.</div>`}`;
  }
  function env(t) {  // a Competition team as an operational environment
    const dir = A(t.manager_key), e = t.team || {}, r = e.report;
    const sq = t.squads.map(U).filter(Boolean);
    const loose = members(t.id, t.manager_key);
    const working = people(t.id).filter(a => a.runtime?.running).length;
    const k = [["Board", `${e.open || 0} open, ${e.done_week || 0} done`], ["Knowledge", `${e.notes || 0} notes, ${e.lessons || 0} lessons`], ["Workspace", plural(e.files || 0, "file")],
               ["Experiments", e.experiments ? `${e.experiments} · ${e.adopted || 0} adopted` : "none yet"], ["Sandbox · 7 days", plural(e.sandbox_week || 0, "run")], ["Approvals", r?.asks ? `${plural(r.asks, "ask")} for you` : "none waiting"]];
    return `<article class="ogz-env" data-ogz-drop="${t.id}">
      <div class="ogz-uhead"><span class="ogz-uh">${icon("trophy")}<b>${esc(t.name)}</b>${working ? badge("clear", `${working} working`) : ""}</span>
        <span class="ogz-uact"><button type="button" class="iconbtn" data-ogz-team="${e.comp || ""}" title="Open this Competition team" aria-label="Open the team">${icon("external")}</button><button type="button" class="iconbtn" data-ogz="request" data-unit="${t.id}" title="Request a specialist for this team" aria-label="Request a specialist">${icon("userplus")}</button><button type="button" class="iconbtn" data-ogz="edit-unit" data-unit="${t.id}" aria-label="Edit">${icon("edit")}</button></span></div>
      ${e.goal ? `<p class="small ogz-goal">${icon("target")}${esc(e.goal)}</p>` : ""}
      <div class="ogz-envtop"><div class="ogz-mgr"><span class="ogz-role">Competition director</span>${dir ? chip(dir, "Director · competition delivery") : `<span class="faint small">No Director yet: make one of the team's agents its lead on the Competition teams page.</span>`}</div>
        <div class="ogz-mgr"><span class="ogz-role">Budget (its governor enforces it)</span><span class="ogz-mline">${meter(t.spent_day, t.allocation)}</span></div></div>
      <dl class="ogz-kv">${k.map(([a, b]) => `<div><dt>${a}</dt><dd>${esc(b)}</dd></div>`).join("")}</dl>
      ${sq.length ? `<div class="ogz-squads">${sq.map(s => { const l = A(s.manager_key), ppl = members(s.id, s.manager_key); return `<div class="ogz-squad" data-ogz-drop="${s.id}"><span class="ogz-uh">${icon("pickaxe")}<b>${esc(s.name)}</b><span class="faint small">${ppl.length + (l ? 1 : 0)}</span></span>
        ${l ? `<small>Lead <button type="button" class="linkbtn" data-ogz-agent="${esc(l.key)}">${esc(l.name)}</button></small>` : `<small class="faint">No lead</small>`}
        ${q && ppl.some(hit) ? `<div class="ogz-chips">${ppl.filter(hit).map(a => chip(a)).join("")}</div>` : ""}</div>`; }).join("")}</div>` : ""}
      ${loose.length ? `<details class="ogz-fold"><summary>${plural(loose.length, "agent")} outside a squad</summary><div class="ogz-chips">${loose.map(a => chip(a)).join("")}</div></details>` : ""}
      ${t.loaned_in.length ? `<p class="small"><span class="ogz-dotl">Specialists on loan</span> ${t.loaned_in.map(x => `<button type="button" class="linkbtn" data-ogz-agent="${esc(x.key)}">${nm(x.key)}</button> <span class="faint">(${esc(x.role)}, L${x.scope})</span>`).join(", ")}</p>` : ""}
      ${r ? `<div class="ogz-report ${r.status === "new" ? "new" : ""}" title="The Director's latest report">${icon("inbox")}<span><b>${esc(r.headline || "Report")}</b><small>${r.status === "new" ? "Unread" : esc(r.status || "")} · ${esc(ago(r.ts))}</small></span></div>` : ""}</article>`;
  }
  function unitBox(u) {
    const m = A(u.manager_key), ppl = members(u.id, u.manager_key), ks = kids(u.id);
    return `<div class="ogz-unit k-${u.kind}" data-ogz-drop="${u.id}">
      <div class="ogz-uhead"><span class="ogz-uh">${icon(KIND[u.kind]?.[0] || "users")}<b>${esc(u.name)}</b></span>
        <span class="ogz-uact"><button type="button" class="iconbtn" data-ogz="edit-unit" data-unit="${u.id}" title="Edit ${esc(u.name)}" aria-label="Edit">${icon("edit")}</button>
          <button type="button" class="iconbtn" data-ogz="add-unit" data-kind="team" data-parent="${u.id}" title="Add a team inside ${esc(u.name)}" aria-label="Add a team">${icon("plus")}</button></span></div>
      ${u.purpose ? `<p class="faint small ogz-purpose">${esc(u.purpose)}</p>` : ""}
      <div class="ogz-mgr">${m ? `<span class="ogz-role">${u.kind === "squad" ? "Squad lead" : u.kind === "team" ? "Team leader" : "Manager"}</span>${chip(m)}` : `<button type="button" class="ogz-node empty sm" data-ogz="set-manager" data-unit="${u.id}">${icon("userplus")}Pick a ${u.kind === "team" ? "team leader" : "manager"}</button>`}</div>
      ${ppl.length ? `<div class="ogz-chips">${ppl.filter(hit).map(a => chip(a)).join("")}</div>` : `<p class="faint small">Nobody here yet.</p>`}
      ${ks.length ? `<div class="ogz-kids">${ks.map(unitBox).join("")}</div>` : ""}</div>`;
  }

  // ---------- 4. workforce departments ----------
  function departments() {
    const ds = d.units.filter(u => u.kind === "department" && u.link !== "exec");
    return `<div class="ogz-bar"><p class="faint small">The company-wide service layer. Each department has an executive sponsor (a dashed line: oversight, not a new manager) and lends its specialists to divisions, teams and squads through assignments. One identity, separate scoped contexts.</p>
      <button type="button" class="btn sm" data-ogz="add-unit" data-kind="department">${icon("plus")}Department</button></div>
      <div class="ogz-dgrid">${ds.map(u => {
        const m = A(u.manager_key), sp = A(u.sponsor_key), home = members(u.id, u.manager_key), aff = d.agents.filter(a => a.dept_id === u.id && a.unit_id !== u.id);
        const lent = [...home, ...(m ? [m] : []), ...aff].flatMap(a => a.assignments.map(s => ({ a, s })));
        const sk = {}; [...home, ...(m ? [m] : []), ...aff].forEach(a => Object.entries(a.skills).forEach(([k, v]) => { if (v >= 3) sk[k] = (sk[k] || 0) + 1; }));
        const top = Object.entries(sk).sort((x, y) => y[1] - x[1]).slice(0, 6);
        return `<section class="card ogz-dcard" data-ogz-drop="${u.id}"><div class="ogz-h"><h3>${icon("group")}${esc(u.name)}</h3><button type="button" class="iconbtn" data-ogz="edit-unit" data-unit="${u.id}" aria-label="Edit">${icon("edit")}</button></div>
          ${u.purpose ? `<p class="faint small">${esc(u.purpose)}</p>` : ""}
          <dl class="ogz-dl"><dt><span class="ogz-dashl">Sponsor</span></dt><dd>${sp ? `<button type="button" class="linkbtn" data-ogz-agent="${esc(sp.key)}">${esc(sp.name)}</button> <span class="faint">${esc(P(sp.portfolio)?.title || "")}</span>` : `<span class="faint">none</span>`} <button type="button" class="linkbtn small" data-ogz="sponsor" data-unit="${u.id}">Change</button></dd>
            <dt>Manager</dt><dd>${m ? `<button type="button" class="linkbtn" data-ogz-agent="${esc(m.key)}">${esc(m.name)}</button>` : `<button type="button" class="linkbtn" data-ogz="set-manager" data-unit="${u.id}">Pick one</button>`}</dd>
            <dt>Allocation</dt><dd class="ogz-mline">${meter(u.spent_day, u.allocation)}</dd></dl>
          ${top.length ? `<p class="small">${top.map(([k, n]) => `<span class="co-skill">${esc(k.replace(/_/g, " "))} <b>${n}</b></span>`).join("")}</p>` : ""}
          <div><span class="ogz-role">Members · home here</span><div class="ogz-chips">${home.filter(hit).map(a => chip(a)).join("") || `<span class="faint small">Nobody yet. Drop an agent here.</span>`}</div></div>
          ${aff.length ? `<details class="ogz-fold"><summary>${plural(aff.length, "affiliated agent")} with a home elsewhere</summary><div class="ogz-chips">${aff.map(a => chip(a, `${a.unit_role || a.title} · ${U(a.unit_id)?.name || "not placed"}`)).join("")}</div></details>` : ""}
          ${lent.length ? `<div><span class="ogz-role"><span class="ogz-dotl">On assignment</span></span><ul class="ogz-list">${lent.map(({ a, s }) => `<li><span class="ogz-row">${av(a)}<span><b>${esc(a.name)}</b> → ${esc(U(s.unit_id)?.name || "")}<small>${esc(s.role)} · L${s.scope} inside</small></span></span></li>`).join("")}</ul></div>` : ""}</section>`;
      }).join("")}</div>`;
  }

  // ---------- 5. agent directory ----------
  function directory() {
    const s = sub.directory || "profiles";
    const sysC = {}, tierC = {};
    d.agents.forEach(a => { sysC[a.system] = (sysC[a.system] || 0) + 1; tierC[a.tier] = (tierC[a.tier] || 0) + 1; });
    if (sysF !== "all" && !sysC[sysF]) sysF = "all";
    if (tierF !== "all" && !tierC[tierF]) tierF = "all";
    const order = d.tiers.map(t => t.tier);
    const rows = d.agents.filter(a => (sysF === "all" || a.system === sysF) && (tierF === "all" || a.tier === tierF) && hit(a))
      .sort((a, b) => order.indexOf(a.tier) - order.indexOf(b.tier) || a.name.localeCompare(b.name));
    const chipsF = (cur, counts, label, attr, keys) => `<div class="ogz-filter" role="group">${[["all", "All", Object.values(counts).reduce((x, y) => x + y, 0)], ...(keys || Object.keys(counts)).filter(k => counts[k]).map(k => [k, label(k), counts[k]])]
      .map(([k, l, n]) => `<button type="button" class="co-chip ${cur === k ? "on" : ""}" ${attr}="${k}" aria-pressed="${cur === k}">${esc(l)} <b>${n}</b></button>`).join("")}</div>`;
    const top = `<div class="ogz-bar">${search("Find an agent, title or id…")}${seg("directory", [["profiles", "Profiles"], ["runtime", "Runtime"]])}</div>
      <div class="ogz-bar">${chipsF(tierF, tierC, tierName, "data-ogz-tier", order)}${chipsF(sysF, sysC, k => SYS[k]?.[1] || k, "data-ogz-sys")}</div>`;
    if (s === "runtime") return top + runtime(rows);
    return top + (rows.length ? `<div class="tablewrap flat"><table class="grid ogz-table"><thead><tr><th>Agent</th><th>Position</th><th>Home</th><th>Department</th><th>Manager</th><th>Assignments</th><th>Authority</th><th>Availability</th><th class="r">Score</th><th>Now</th></tr></thead><tbody>
        ${rows.map(a => `<tr><td><button type="button" class="ogz-who" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(titleOf(a))} · <code>${esc(a.ident)}</code></small></span></button></td>
          <td>${esc(d.ranks[a.rank] || a.rank)}${a.unit_role && a.unit_role !== titleOf(a) ? `<small class="faint"> · ${esc(a.unit_role)}</small>` : ""}</td>
          <td>${a.unit_id ? esc(U(a.unit_id)?.name || "") : `<span class="faint">–</span>`}</td><td>${a.dept_id ? esc(deptName(a.dept_id)) : `<span class="faint">–</span>`}</td>
          <td>${a.manager ? nm(a.manager) : `<span class="faint">you</span>`}</td>
          <td>${[...a.assignments.map(s => `<span class="co-skill ogz-dotl" title="${esc(s.role)}, L${s.scope} inside">${esc(U(s.unit_id)?.name || "")}</span>`), ...a.missions.map(m => `<span class="co-skill" title="Mission manager: ${nm(m.manager)}">${esc(m.name)}</span>`)].join("") || (a.work.length ? `<span class="faint small">${plural(a.work.length, "job")} in ${esc(SYS[a.system]?.[1] || "")}</span>` : `<span class="faint">–</span>`)}</td>
          <td>${lvl(a.autonomy)}</td><td class="ogz-av2">${avail(a)}</td><td class="r num">${a.perf?.score != null ? Math.round(a.perf.score) : `<span class="faint" title="Not enough finished work yet">–</span>`}</td>
          <td>${state(a)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="card empty">No agent matches.</div>`);
  }
  const state = a => a.status === "paused" ? badge("caution", "Paused") : a.runtime?.running ? badge("clear", "Working") : a.runtime?.failed_week ? badge("avoid", `${a.runtime.failed_week} failed`) : badge("muted", "Idle");
  function runtime(list) {
    const rows = list.slice().sort((a, b) => (b.runtime?.running ? 1 : 0) - (a.runtime?.running ? 1 : 0) || (b.runtime?.last || 0) - (a.runtime?.last || 0));
    const admin = Auth.me()?.role === "admin";
    return `<div class="ogz-bar"><p class="faint small">From the run ledger every agent system writes to. Agents run inside AXoR's web pod, so CPU and memory are the pod's, not per agent${admin ? `: see Cluster. Agent HQ watches the services themselves.` : "."}</p>
        ${admin ? `<button type="button" class="btn sm" data-ogz-view="hq">${icon("flag")}Agent HQ</button>` : ""}</div>
      <div class="tablewrap flat"><table class="grid ogz-table"><thead><tr><th>Agent</th><th>Now</th><th>Current run</th><th>Last activity</th><th class="r">Runs 7 d</th><th class="r">Failed 7 d</th><th class="r">Tokens 24 h</th><th class="r">Tokens 7 d</th><th>Last error</th></tr></thead><tbody>
      ${rows.map(a => { const r = a.runtime || {}; return `<tr><td><button type="button" class="ogz-who" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(SYS[a.system]?.[1] || a.system)}</small></span></button></td>
        <td>${state(a)}</td><td class="small">${esc(r.current || "")}</td><td class="faint small">${r.last ? ago(r.last) : "never"}</td><td class="r num">${r.runs_week || 0}</td>
        <td class="r num">${r.failed_week ? `<b class="ogz-bad">${r.failed_week}</b>` : 0}</td><td class="r num">${tok(a.tokens_day || 0)}</td><td class="r num">${tok(r.tokens_week || 0)}</td><td class="small faint ogz-err">${esc(r.last_error || "")}</td></tr>`; }).join("")}</tbody></table></div>`;
  }

  // ---------- 6. teams & squads ----------
  function teams() {
    const s = sub.teams || "assignments", c = d.counts;
    return `<div class="ogz-bar">${seg("teams", [["assignments", "Assignments", c.assignments], ["squads", "Squads", c.squads], ["missions", "Missions", c.missions], ["delegation", "Delegation", c.open_tasks]])}</div>
      ${({ assignments, squads, missions, delegation })[s]()}`;
  }
  function assignments() {
    const on = d.agents.filter(a => a.assignments.length || a.missions.length);
    const reqs = d.requests.filter(r => r.status === "pending" && r.kind === "assign_unit");
    return `<div class="ogz-bar"><p class="faint small">Two relationships, kept apart: the <b>home</b> (permanent unit, manager, department) and <b>assignments</b> (temporary memberships with their own authority scope). An assignment never moves the home or changes the manager; releasing it ends that context only.</p>
        <div class="row ogz-act"><button type="button" class="btn sm" data-ogz="request">${icon("userplus")}Request a specialist</button><button type="button" class="btn sm primary" data-ogz="assign-unit">${icon("plus")}Assign</button></div></div>
      ${reqs.length ? `<section class="card"><div class="ogz-h"><h3>${icon("inbox")}Specialist requests waiting for you</h3><button type="button" class="linkbtn" data-ogz-tab="governance">Decide in Governance</button></div><ul class="ogz-list">${reqs.map(r => `<li><span class="ogz-row">${icon("userplus")}<span><b>${esc(r.title)}</b><small>${esc(r.why || "")}</small></span></span></li>`).join("")}</ul></section>` : ""}
      ${on.length ? `<div class="tablewrap flat"><table class="grid ogz-table"><thead><tr><th>Agent</th><th>Home (permanent)</th><th>Manager</th><th>Department</th><th>Active assignments</th></tr></thead><tbody>
        ${on.map(a => `<tr><td><button type="button" class="ogz-who" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(titleOf(a))} · ${lvl(a.autonomy)}</small></span></button></td>
          <td>${esc(U(a.unit_id)?.name || "not placed")}</td><td>${a.manager ? nm(a.manager) : "you"}</td><td>${a.dept_id ? esc(deptName(a.dept_id)) : `<span class="faint">–</span>`}</td>
          <td><ul class="ogz-asg">${a.assignments.map(s => `<li><span class="ogz-dotl">${esc(U(s.unit_id)?.name || "")}</span> <span class="small">${esc(s.role)}</span> ${lvl(s.scope)} <button type="button" class="linkbtn small" data-ogz="release-unit" data-unit="${s.unit_id}" data-key="${esc(a.key)}">Release</button></li>`).join("")}
            ${a.missions.map(m => `<li><span>${icon("target")}${esc(m.name)}</span> <span class="small">${esc(m.role)} · under ${nm(m.manager)}</span></li>`).join("")}</ul></td></tr>`).join("")}</tbody></table></div>`
        : `<div class="card empty">No assignment yet. Lend a specialist to a team ("Request a specialist" picks the best fit from a department), or start a mission.</div>`}`;
  }
  function squads() {
    const comps = d.units.filter(isComp);
    return comps.length ? comps.map(t => { const sq = t.squads.map(U).filter(Boolean); return `<section class="card"><div class="ogz-h"><h3>${icon("trophy")}${esc(t.name)}</h3><span class="small faint">Director ${t.manager_key ? nm(t.manager_key) : "–"}</span></div>
      ${sq.length ? `<div class="tablewrap flat"><table class="grid ogz-table compact"><thead><tr><th>Squad</th><th>Lead</th><th class="r">Agents</th><th class="r">Working</th><th class="r">Jobs</th><th>Members</th></tr></thead><tbody>${sq.map(s => { const ppl = members(s.id, s.manager_key), all = [...(A(s.manager_key) ? [A(s.manager_key)] : []), ...ppl]; return `<tr>
        <td><b>${esc(s.name)}</b></td><td>${s.manager_key ? `<button type="button" class="linkbtn" data-ogz-agent="${esc(s.manager_key)}">${nm(s.manager_key)}</button>` : `<span class="faint">no lead</span>`}</td>
        <td class="r num">${all.length}</td><td class="r num">${all.filter(a => a.runtime?.running).length}</td><td class="r num">${all.reduce((n, a) => n + a.work.length, 0)}</td>
        <td><div class="ogz-chips">${ppl.slice(0, 8).map(a => chip(a)).join("")}${ppl.length > 8 ? `<span class="faint small">+${ppl.length - 8}</span>` : ""}</div></td></tr>`; }).join("")}</tbody></table></div>`
        : `<p class="faint small">This team's agents have no squads (a small team works directly under its Director).</p>`}</section>`; }).join("")
      : `<div class="card empty">No Competition team is open. Squads come from each team's own roster (My subnets → Competition teams).</div>`;
  }
  function missions() {
    const card = m => {
      const r = recFor[m.id];
      return `<section class="card ogz-mission"><div class="ogz-h"><div><h3 class="ogz-mt">${icon("target")}${esc(m.name)}</h3>
          <p class="faint small">${m.unit_id ? `${esc(U(m.unit_id)?.name || "")} · ` : ""}Mission manager ${m.manager_key ? `<b>${nm(m.manager_key)}</b>` : `<button type="button" class="linkbtn" data-ogz="mission-manager" data-mission="${m.id}">pick one</button>`} · started ${ago(m.created)}${m.due ? ` · due ${until(m.due)}` : ""}</p></div>
          <div class="row ogz-act"><button type="button" class="btn sm" data-ogz="recommend" data-mission="${m.id}">${icon("sparkle")}Ask the CEO for a team</button><button type="button" class="btn sm" data-ogz="assign" data-mission="${m.id}">${icon("userplus")}Assign</button>
          <button type="button" class="btn sm" data-ogz="task" data-mission="${m.id}">${icon("route")}Delegate</button><button type="button" class="btn sm" data-ogz="end-mission" data-mission="${m.id}">${icon("check")}End</button></div></div>
        ${m.objective ? `<p class="ogz-obj">${esc(m.objective)}</p>` : ""}
        ${m.skills.length ? `<p class="small">${m.skills.map(s => `<span class="co-skill">${esc(s.replace(/_/g, " "))}</span>`).join("")}</p>` : ""}
        ${m.people.length ? `<div class="tablewrap flat"><table class="grid ogz-table compact"><thead><tr><th>Agent</th><th>Mission role</th><th>Permanent manager</th><th></th></tr></thead><tbody>${m.people.map(p => { const a = A(p.key); return `<tr>
            <td><button type="button" class="ogz-who" data-ogz-agent="${esc(p.key)}">${av(a)}<span><b>${nm(p.key)}</b><small>${esc(a ? U(a.unit_id)?.name || "not placed" : "")}</small></span></button></td>
            <td>${esc(p.role)}${p.duty ? `<small class="faint"> · ${esc(p.duty)}</small>` : ""}</td><td>${a?.manager ? nm(a.manager) : "you"} <span class="faint small">(unchanged)</span></td>
            <td class="r"><button type="button" class="linkbtn" data-ogz="release" data-mission="${m.id}" data-key="${esc(p.key)}">Release</button></td></tr>`; }).join("")}</tbody></table></div>`
          : `<p class="faint">Nobody assigned yet. Ask the CEO for a team, or assign people yourself.</p>`}
        ${r ? recBox(m, r) : ""}</section>`;
    };
    const work = d.agents.filter(a => a.work.length);
    return `<div class="ogz-bar"><p class="faint small">A mission borrows people from their departments for one objective. Joining one never changes an agent's permanent manager: ending it sends everyone back.</p>
        <button type="button" class="btn sm primary" data-ogz="add-mission">${icon("plus")}New mission</button></div>
      ${d.missions.length ? d.missions.map(card).join("") : `<div class="card empty">No mission is open. Start one: for example "Bittensor Competition 29", managed by Gus, with engineers from Software Engineering and an evaluator from Data & Evaluation.</div>`}
      <section class="card"><div class="ogz-h"><h3>${icon("layers")}Work in their own systems</h3><span class="faint small">read live, not copied</span></div>
        ${work.length ? `<ul class="ogz-list">${work.map(a => a.work.map(w => `<li><span class="ogz-row">${av(a)}<span><b>${esc(a.name)}</b> · ${esc(w.what)}<small>${esc(SYS[w.system]?.[1] || "")}${w.lead ? ` · led by ${nm(w.lead)}` : ""}</small></span></span></li>`).join("")).join("")}</ul>`
          : `<p class="faint">No Company team, Workforce assignment or Competition team task is running.</p>`}</section>
      ${d.past.length ? `<section class="card"><div class="ogz-h"><h3>${icon("clock")}Ended missions</h3></div><ul class="ogz-list">${d.past.map(m => `<li><span class="ogz-row">${icon(m.status === "done" ? "check" : "close")}<span><b>${esc(m.name)}</b><small>${esc(m.status)} ${ago(m.ended)}${m.manager_key ? ` · managed by ${nm(m.manager_key)}` : ""}</small></span></span></li>`).join("")}</ul></section>` : ""}`;
  }
  function recBox(m, r) {
    const row = c => `<li><span class="ogz-row">${av(A(c.key))}<span><b>${esc(c.name)}</b> <span class="faint">${esc(c.title)}${c.unit ? ` · ${esc(c.unit)}` : ""}</span><small>${esc(c.why)}${c.manager ? ` · supplied by ${nm(c.manager)}` : ""}</small></span><b class="num">${Math.round(c.score)}</b></span></li>`;
    const pick = [...r.team, ...(r.evaluator ? [r.evaluator] : [])];
    return `<div class="ogz-rec"><div class="ogz-h"><h4>${icon("sparkle")}${nm(d.org.ceo)} recommends</h4><button type="button" class="linkbtn" data-ogz="close-rec" data-mission="${m.id}">Close</button></div>
      <p class="faint small">Skill match, free capacity, performance and the mission's division; no model call. ${r.missing.length ? `Nobody covers: ${r.missing.map(esc).join(", ")}.` : ""}</p>
      ${pick.length ? `<ul class="ogz-list">${r.team.map(row).join("")}${r.evaluator ? `<li class="faint small">Independent evaluator (not on the team it evaluates):</li>${row(r.evaluator)}` : ""}</ul>
        <div class="row ogz-act"><button type="button" class="btn sm primary" data-ogz="take-rec" data-mission="${m.id}">${icon("check")}${d.org.policies.assign === "direct" ? "Assign these" : "Propose these"} (${pick.length})</button></div>`
        : `<p class="faint">Nobody available fits. Give the mission skills, or free some people.</p>`}
      ${r.candidates.length > pick.length ? `<details class="ogz-more"><summary>All candidates (${r.candidates.length})</summary><ul class="ogz-list">${r.candidates.map(row).join("")}</ul></details>` : ""}</div>`;
  }
  function delegation() {
    const groups = [["awaiting", "Waiting for your approval"], ["escalated", "Escalated"], ["blocked", "Blocked"], ["open", "Open"], ["done", "Done (14 days)"], ["cancelled", "Cancelled"]];
    const row = t => {
      const late = t.due && t.due * 1000 < Date.now() && ["open", "blocked"].includes(t.status);
      const acts = t.status === "awaiting" ? [["cancel", "Cancel"]] : ["done", "cancelled"].includes(t.status) ? [] :
        [["done", "Done"], t.status === "blocked" ? ["resume", "Resume"] : ["block", "Blocked"], t.holder_key ? ["escalate", "Escalate"] : null, ["assign", "Reassign"], ["cancel", "Cancel"]].filter(Boolean);
      return `<li class="ogz-task"><div><span class="ogz-tline"><b>${esc(t.title)}</b> ${badge(TASK[t.status][0], TASK[t.status][1])} ${lvl(t.level)}${t.sensitive ? ` ${badge("scam", esc(d.locked[t.sensitive] || t.sensitive), "lock")}` : ""}${late ? ` ${badge("avoid", "overdue")}` : ""}</span>
          <small class="faint">from ${nm(t.from_key)} to ${nm(t.to_key)} · now with <b>${nm(t.holder_key)}</b>${t.mission_id ? ` · ${esc(M(t.mission_id)?.name || "a mission")}` : ""}${t.due ? ` · due ${when(t.due)}` : ""}</small>
          ${t.detail ? `<p class="small">${esc(t.detail)}</p>` : ""}
          ${t.history.length > 1 ? `<details class="ogz-more"><summary>History</summary><ol class="ogz-hist">${t.history.map(h => `<li>${esc(h.what)} · ${esc(h.by)} · ${ago(h.ts)}${h.note ? ` · ${esc(h.note)}` : ""}</li>`).join("")}</ol></details>` : ""}</div>
        ${acts.length ? `<div class="row ogz-act">${acts.map(([a, l]) => `<button type="button" class="btn sm" data-ogz="task-act" data-task="${t.id}" data-act="${a}">${l}</button>`).join("")}</div>` : ""}</li>`;
    };
    return `<div class="ogz-bar"><p class="faint small">Managers hand work down their own reporting line; a mission manager to the mission's people. A task needs its level of authority from whoever gets it. Blocked or overdue work escalates: the mission manager, then each manager up the line, then you.</p>
        <button type="button" class="btn sm primary" data-ogz="task">${icon("plus")}Delegate a task</button></div>
      ${d.tasks.length ? groups.map(([s, l]) => { const ts = d.tasks.filter(t => t.status === s); return ts.length ? `<section class="card"><div class="ogz-h"><h3>${l} <span class="faint">${ts.length}</span></h3></div><ul class="ogz-tasks">${ts.map(row).join("")}</ul></section>` : ""; }).join("")
        : `<div class="card empty">No task delegated yet.</div>`}`;
  }

  // ---------- 7. knowledge & experience ----------
  function knowledge() {
    const k = know;
    const depts = d.units.filter(u => u.kind === "department" && u.link !== "exec");
    const expertise = depts.map(u => {
      const ppl = d.agents.filter(a => a.dept_id === u.id || a.unit_id === u.id), sk = {};
      ppl.forEach(a => Object.entries(a.skills).forEach(([s, v]) => { if (v >= 3) (sk[s] = sk[s] || []).push([a, v]); }));
      return [u, Object.entries(sk).sort((x, y) => y[1].length - x[1].length).slice(0, 5)];
    }).filter(([, s]) => s.length);
    return `<div class="ogz-bar"><p class="faint small">Read through from where it lives: the Knowledge hub, each team's notebook, lessons and files, experiments and evaluations. Nothing is copied.</p>
        <button type="button" class="btn sm" data-ogz="know">${icon("cycle")}Refresh</button></div>
      ${!k ? Loading.line("Reading knowledge…") : k.error ? `<div class="card empty">${esc(k.error)}</div>` : `<div class="ogz-two">
        <section class="card"><div class="ogz-h"><h3>${icon("book")}Company knowledge</h3><button type="button" class="linkbtn" data-ogz-view="knowledge">Knowledge hub</button></div>
          ${k.company ? `<p class="small"><b class="num">${k.company.total}</b> items kept${Object.entries(k.company.by_type).map(([t, n]) => ` · ${n} ${esc(t)}`).join("")}</p>
            <ul class="ogz-list">${k.company.latest.map(i => `<li><span class="ogz-row">${icon("doc")}<span><b>${esc(i.title || "Untitled")}</b><small>${esc(i.type || "")}${i.trust ? ` · ${esc(i.trust)}` : ""}</small></span></span></li>`).join("") || `<li class="faint small">Nothing kept yet.</li>`}</ul>` : `<p class="faint">The Knowledge hub isn't set up on this server.</p>`}</section>
        <section class="card"><div class="ogz-h"><h3>${icon("bulb")}Lessons learned</h3><span class="faint small">from the teams' work</span></div>
          ${k.lessons.length ? `<ul class="ogz-list">${k.lessons.map(l => `<li><span class="ogz-row">${icon("sprout")}<span><b>${esc(l.lesson)}</b><small>${esc(l.team || "")}${l.sure ? ` · ${esc(l.sure)}` : ""}${l.ts ? ` · ${ago(l.ts)}` : ""}${l.why ? ` · ${esc(l.why)}` : ""}</small></span></span></li>`).join("")}</ul>` : `<p class="faint">No lessons yet: they come from the teams' reviewed notes.</p>`}</section></div>
      ${k.teams.length ? `<section class="card"><div class="ogz-h"><h3>${icon("trophy")}Team knowledge and experiments</h3><span class="faint small">each team's own, isolated</span></div>
        <div class="tablewrap flat"><table class="grid ogz-table compact"><thead><tr><th>Team</th><th class="r">Notes</th><th class="r">Lessons</th><th class="r">Files</th><th class="r">Experiments</th><th class="r">Adopted</th><th class="r">Sandbox runs 7 d</th><th></th></tr></thead><tbody>
        ${k.teams.map(t => `<tr><td><b>${esc(t.name)}</b>${t.goal ? `<small class="faint"> · ${esc(t.goal)}</small>` : ""}</td><td class="r num">${t.notes || 0}</td><td class="r num">${t.lessons || 0}</td><td class="r num">${t.files || 0}</td><td class="r num">${t.experiments || 0}</td><td class="r num">${t.adopted || 0}</td><td class="r num">${t.sandbox_week || 0}</td>
          <td class="r"><button type="button" class="linkbtn" data-ogz-team="${t.comp}">Open</button></td></tr>`).join("")}</tbody></table></div></section>` : ""}`}
      <section class="card"><div class="ogz-h"><h3>${icon("key")}Expertise by department</h3><span class="faint small">skills at 3/5 or more, home and affiliated members</span></div>
        ${expertise.length ? `<div class="ogz-exp">${expertise.map(([u, s]) => `<div><h4 class="ogz-sub">${esc(u.name)}</h4><ul class="ogz-list">${s.map(([sk, xs]) => `<li><span class="ogz-row"><span><b>${esc(sk.replace(/_/g, " "))}</b> <span class="faint small">${xs.length}</span><small>${xs.sort((a, b) => b[1] - a[1]).slice(0, 4).map(([a, v]) => `${esc(a.name)} ${v}/5`).join(" · ")}</small></span></span></li>`).join("")}</ul></div>`).join("")}</div>`
          : `<p class="faint">No skills recorded yet.</p>`}</section>
      ${performance()}`;
  }
  function performance() {
    const scored = d.agents.filter(a => a.perf);
    const pct = x => x == null ? `<span class="faint">–</span>` : `${Math.round(x * 100)}%`;
    const list = recs?.recommendations || [];
    return `<section class="card"><div class="ogz-h"><h3>${icon("trophy")}Experience and performance</h3><button type="button" class="btn sm primary" data-ogz="perf">${icon("cycle")}${scored.length ? "Update scores" : "Score agents"}</button></div>
      <p class="faint small">Scores come from finished work only: runs done vs failed, evaluation scores, delegated tasks done without escalation. Under 5 finished pieces of work, no score. Promotions are proposals; a promotion never raises execution authority.</p>
      ${list.length ? `<ul class="ogz-list">${list.map((r, i) => `<li><span class="ogz-row ogz-pol">${icon(r.kind === "promote" ? "up" : r.kind === "review" ? "alert" : "userplus")}<span><b>${esc(r.title)}</b><small>${esc(r.why)}</small></span>
          ${r.payload ? `<button type="button" class="btn sm" data-ogz="take-perf" data-i="${i}">${r.kind === "review" ? "Lower one level" : "Propose"}</button>` : ""}</span></li>`).join("")}</ul>` : recs ? `<p class="faint">No recommendation: nobody stands out either way yet.</p>` : ""}
      ${scored.length ? `<div class="tablewrap flat"><table class="grid ogz-table"><thead><tr><th>Agent</th><th>Position</th><th class="r">Score</th><th class="r">Evidence</th><th class="r">Success</th><th class="r">Quality</th><th class="r">Reliability</th><th class="r">Assignments done</th><th class="r">Missions led</th></tr></thead><tbody>
        ${scored.sort((a, b) => (b.perf.score ?? -1) - (a.perf.score ?? -1)).filter(hit).map(a => `<tr><td><button type="button" class="ogz-who" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(titleOf(a))}</small></span></button></td><td>${esc(d.ranks[a.rank] || a.rank)}</td>
          <td class="r num">${a.perf.score != null ? `<b>${Math.round(a.perf.score)}</b>` : `<span class="faint" title="Fewer than 5 finished pieces of work">–</span>`}</td><td class="r num">${a.perf.evidence}</td><td class="r num">${pct(a.perf.success)}</td><td class="r num">${pct(a.perf.quality)}</td><td class="r num">${pct(a.perf.reliability)}</td>
          <td class="r num">${a.experience?.assignments_done || 0}</td><td class="r num">${a.experience?.missions_led || 0}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="faint">No scores yet. Press "Score agents" to score everyone from their finished work.</p>`}</section>`;
  }

  // ---------- 8. governance & authority ----------
  function governance() {
    const pend = d.requests.filter(r => r.status === "pending"), done = d.requests.filter(r => r.status !== "pending");
    const at = n => d.agents.filter(a => a.autonomy === n);
    const pol = d.org.policies, b = d.budget;
    const tops = d.units.filter(u => !u.parent_id && u.link !== "exec");
    const brow = (u, depth) => `<tr><td style="padding-left:${10 + depth * 18}px">${icon(KIND[u.kind]?.[0] || "users")} ${esc(u.name)}</td><td class="ogz-mline">${meter(u.spent_day, u.allocation)}</td>
      <td class="r num">${u.allocated_below ? tok(u.allocated_below) : `<span class="faint">–</span>`}</td>
      <td class="r">${isComp(u) ? `<button type="button" class="linkbtn small" data-ogz-team="${u.team?.comp || ""}">On its page</button>` : `<button type="button" class="linkbtn small" data-ogz="budget" data-unit="${u.id}">Set</button>`}</td></tr>
      ${kids(u.id).filter(k => k.kind !== "squad").map(k => brow(k, depth + 1)).join("")}`;
    return `<section class="card"><div class="ogz-h"><h3>${icon("inbox")}Approvals</h3>${pend.length ? badge("caution", String(pend.length)) : ""}</div>
        <p class="faint small">Proposals from the CEO, the performance review, specialist requests, budgets and task go-aheads. Each is bound to its exact contents and applies once; a changed or expired (7 days) request can't be applied.</p>
        ${pend.length ? `<ul class="ogz-tasks">${pend.map(r => `<li class="ogz-task"><div><span class="ogz-tline"><b>${esc(r.title)}</b> ${badge("caution", esc(r.kind.replace(/_/g, " ")))}</span>
            <small class="faint">proposed by ${esc(r.by)} · ${ago(r.created)} · expires ${until(r.expires)}</small>${r.why ? `<p class="small">${esc(r.why)}</p>` : ""}</div>
            <div class="row ogz-act"><button type="button" class="btn sm primary" data-ogz="decide" data-req="${r.id}" data-ok="1">${icon("check")}Approve</button><button type="button" class="btn sm" data-ogz="decide" data-req="${r.id}" data-ok="0">Reject</button></div></li>`).join("")}</ul>`
          : `<p class="faint">Nothing waits for your decision.</p>`}
        ${done.length ? `<details class="ogz-more"><summary>${plural(done.length, "decided request")}</summary><ul class="ogz-list">${done.map(r => `<li><span class="ogz-row"><span><b>${esc(r.title)}</b> ${badge(REQ[r.status]?.[0] || "muted", REQ[r.status]?.[1] || r.status)}<small>${esc(r.decided_by || "")} ${r.decided ? ago(r.decided) : ""}${r.result ? ` · ${esc(r.result)}` : ""}${r.note ? ` · ${esc(r.note)}` : ""}</small></span></span></li>`).join("")}</ul></details>` : ""}</section>
      <div class="ogz-two">
        <section class="card"><div class="ogz-h"><h3>${icon("branch")}Authority ladder</h3><span class="faint small">organizational authority, by position</span></div>
          <ol class="ogz-ladder">${d.tiers.map(t => `<li><button type="button" class="ogz-row" data-ogz-tier-go="${t.tier}"><span class="ogz-rung">${t.count}</span><span><b>${esc(t.name)}</b><small>${esc(t.authority)}</small></span></button></li>`).join("")}</ol>
          <p class="faint small">Position never raises execution authority (below): making an agent a manager leaves its level where it was.</p></section>
        <section class="card"><div class="ogz-h"><h3>${icon("shield")}Safeguards</h3></div>
          <ul class="ogz-list">${d.safeguards.map(s => `<li><span class="ogz-row">${icon("check")}<span><b>${esc(s.rule)}</b><small>${esc(s.how)}</small><em class="ogz-where">${esc(s.where)}</em></span></span></li>`).join("")}</ul></section></div>
      <div class="ogz-two">
        <section class="card"><div class="ogz-h"><h3>${icon("shield")}Execution authority</h3></div>
          <p class="faint small">What an agent may do, separate from whom it manages. Raising one to L${d.approval_from} or more needs your approval. An assignment can narrow it inside a unit, never raise it.</p>
          <div class="tablewrap flat"><table class="grid ogz-table compact"><tbody>${d.levels.map(l => `<tr><td>${lvl(l.level)}</td><td class="small">${esc(l.about)}</td><td class="r num">${at(l.level).length}</td></tr>`).join("")}</tbody></table></div></section>
        <section class="card"><div class="ogz-h"><h3>${icon("lock")}Always needs you</h3></div>
          <p class="faint small">Locked: no level, position or setting turns these off.</p>
          <ul class="ogz-list">${Object.values(d.locked).map(l => `<li><span class="ogz-row">${icon("lock")}<span><b>${esc(l)}</b></span></span></li>`).join("")}</ul>
          <h4 class="ogz-sub">Policies for proposals</h4>
          <ul class="ogz-list">${Object.entries(d.org_actions).map(([k, l]) => `<li><span class="ogz-row ogz-pol"><span><b>${esc(l)}${k === "assign" ? " and specialist requests" : ""}</b><small>${pol[k] === "direct" ? "Applied at once" : "Waits for your approval"}</small></span>
            <span class="seg" role="group"><button type="button" aria-pressed="${pol[k] !== "direct"}" data-ogz="policy" data-k="${k}" data-v="owner">Ask me</button><button type="button" aria-pressed="${pol[k] === "direct"}" data-ogz="policy" data-k="${k}" data-v="direct">Apply</button></span></span></li>`).join("")}</ul>
          <p class="faint small">Your own edits on this page always apply at once.</p></section></div>
      <section class="card"><div class="ogz-h"><h3>${icon("coins")}Budgets</h3><span class="small">${b.cap ? `Your daily limit <b class="num">${tok(b.cap)}</b> · today <b class="num">${tok(b.today || 0)}</b> · allocated <b class="num">${tok(b.allocated)}</b>` : `No daily limit set · allocated <b class="num">${tok(b.allocated)}</b>`} <button type="button" class="linkbtn small" data-ogz-view="studio">Agent Operations → Budget</button></span></div>
        <p class="faint small">Daily tokens, the same unit as your limit and each team's 24-hour budget. A unit can't be allocated more than its parent has; the top units not more than your limit. Spend is the last 24 hours of the unit's people, its own units included.</p>
        <div class="tablewrap flat"><table class="grid ogz-table compact"><thead><tr><th>Unit</th><th>Spent / allocation</th><th class="r">Allocated below</th><th></th></tr></thead><tbody>${tops.map(u => brow(u, 0)).join("")}</tbody></table></div></section>
      <section class="card"><div class="ogz-h"><h3>${icon("users")}Levels by agent</h3>${search("Find an agent…")}</div>
        <details class="ogz-fold" ${q ? "open" : ""}><summary>${plural(d.agents.filter(hit).length, "agent")}: change one's execution level</summary><div class="tablewrap flat"><table class="grid ogz-table compact"><thead><tr><th>Agent</th><th>Position</th><th>Level</th></tr></thead><tbody>
        ${d.agents.filter(hit).map(a => `<tr><td><button type="button" class="ogz-who" data-ogz-agent="${esc(a.key)}">${av(a)}<span><b>${esc(a.name)}</b><small>${esc(titleOf(a))}</small></span></button></td><td>${esc(tierName(a.tier))}</td>
          <td><select data-ogz-level="${esc(a.key)}" aria-label="Authority of ${esc(a.name)}">${d.levels.map(l => `<option value="${l.level}" ${l.level === a.autonomy ? "selected" : ""}>L${l.level} ${esc(l.name)}${l.level >= d.approval_from && l.level > a.autonomy ? " (asks you)" : ""}</option>`).join("")}</select></td></tr>`).join("")}</tbody></table></div></details></section>
      <section class="card"><div class="ogz-h"><h3>${icon("clock")}Audit log</h3><button type="button" class="linkbtn" data-ogz="audit">${audit ? "Refresh" : "Show"}</button></div>
        ${audit ? (audit.length ? `<ul class="ogz-list">${audit.slice(0, 30).map(a => `<li><span class="ogz-row">${icon(a.actor === "system" ? "cycle" : "users")}<span><b>${esc(a.action.replace(/_/g, " "))}</b> <span class="faint">${esc(a.actor)} · ${ago(a.ts)}</span><small>${esc(a.detail || a.target)}</small></span></span></li>`).join("")}</ul>` : `<p class="faint">No changes yet.</p>`) : `<p class="faint small">Every change (yours, approved proposals, the sync and escalations) is kept.</p>`}</section>`;
  }

  // ---------- dialogs ----------
  function dlg(title, body, ok, run, wide = false) {
    let el = document.getElementById("ogz-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "ogz-dlg"; document.body.append(el); }
    el.className = `modal ogz-dlg ${wide ? "wide" : ""}`;
    el.innerHTML = `<form method="dialog" class="co-form" novalidate><div class="ogz-h"><h3>${title}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      ${body}<p class="err" role="alert"></p>${ok ? `<div class="row end"><button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn primary">${ok}</button></div>` : ""}</form>`;
    const f = el.querySelector("form"), e = f.querySelector(".err");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    el.onclose = () => { if (on) render(); };
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
  const post = async (op, p) => { const r = await api(`${B}/change`, { method: "POST", body: { op, p } }); d = r.view; count(); const m = typeof r.result === "string" ? r.result : r.result?.msg; if (m) toast(m.charAt(0).toUpperCase() + m.slice(1)); return r; };
  const agentOpts = (sel, { none = "", only = null, skip = [] } = {}) => `${none ? `<option value="">${esc(none)}</option>` : ""}${d.agents.filter(a => a.status === "active" && !skip.includes(a.key) && (!only || only(a)))
    .sort((a, b) => a.name.localeCompare(b.name)).map(a => `<option value="${esc(a.key)}" ${a.key === sel ? "selected" : ""}>${esc(a.name)} · ${esc(titleOf(a))}${dupe(a) ? ` (${esc(a.ident)})` : ""}</option>`).join("")}`;
  const dupe = a => d.agents.filter(x => x.name === a.name).length > 1;
  const unitOpts = (sel, { none = "", kinds = null, skip = null } = {}) => {
    const out = [];
    const walk = (u, depth) => { if (skip && u.id === skip) return; if (!kinds || kinds.includes(u.kind)) out.push(`<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${"  ".repeat(depth)}${depth ? "↳ " : ""}${esc(u.name)} (${(KIND[u.kind]?.[1] || u.kind).toLowerCase()})</option>`); kids(u.id).forEach(k => walk(k, depth + 1)); };
    d.units.filter(u => !u.parent_id).forEach(u => walk(u, 0));
    return `${none ? `<option value="">${esc(none)}</option>` : ""}${out.join("")}`;
  };
  const field = (label, html, hint = "") => `<label class="in"><span>${label}</span>${html}${hint ? `<small class="faint">${hint}</small>` : ""}</label>`;
  const levelOpts = (sel, max = 4) => d.levels.filter(l => l.level <= max).map(l => `<option value="${l.level}" ${l.level === sel ? "selected" : ""}>L${l.level} ${esc(l.name)}</option>`).join("");

  function profile(key) {
    const a = A(key); if (!a) return;
    const u = U(a.unit_id), sys = SYS[a.system];
    const skills = Object.entries(a.skills).sort((x, y) => y[1] - x[1]);
    const p = a.perf, r = a.runtime || {}, port = P(a.portfolio);
    const scope = (a.scope || []).map(U).filter(Boolean);
    const { el } = dlg(`${av(a)} ${esc(a.name)} <span class="faint">· ${esc(titleOf(a))}</span>`, `
      <div class="ogz-prof">
        <section class="ogz-matrix"><h4 class="ogz-sub">Permanent identity</h4>
          <div class="ogz-mx"><span class="ogz-mxl">Home</span><b>${u ? esc(u.name) : "Not placed"}</b><small>${u ? `${esc((KIND[u.kind]?.[1] || u.kind).toLowerCase())}` : "reports to you"}${a.unit_role ? ` · ${esc(a.unit_role)}` : ""}</small></div>
          <div class="ogz-mx"><span class="ogz-mxl">Manager</span><b>${a.manager ? nm(a.manager) : "You"}</b><small>${a.since ? `since ${when(a.since)} · ` : ""}${esc(tierName(a.tier))}</small></div>
          <div class="ogz-mx dept"><span class="ogz-mxl">Department</span><b>${a.dept_id ? esc(deptName(a.dept_id)) : "–"}</b><small>its profession, separate from its home</small></div>
          ${port ? `<div class="ogz-mx exec"><span class="ogz-mxl">Portfolio</span><b>${esc(port.title)}</b><small>${esc(port.about)}</small></div>` : ""}
          <div class="row ogz-act"><button type="button" class="btn sm" data-ogz="move" data-key="${esc(a.key)}">${icon("swap")}Move or change manager</button><button type="button" class="btn sm" data-ogz="affiliation" data-key="${esc(a.key)}">${icon("edit")}Department and role</button>${a.tier === "executive" || !a.unit_id || u?.link === "exec" ? `<button type="button" class="btn sm" data-ogz="portfolio" data-key="${esc(a.key)}">${icon("star")}Portfolio</button>` : ""}</div></section>
        <section class="ogz-matrix"><h4 class="ogz-sub">Active assignments</h4>
          ${a.assignments.map(s => `<div class="ogz-mx assign"><span class="ogz-mxl">Assigned to</span><b>${esc(U(s.unit_id)?.name || "")}</b><small>${esc(s.role)} · ${lvl(s.scope)} inside · since ${when(s.since)}</small></div>`).join("")}
          ${a.missions.map(m => `<div class="ogz-mx mission"><span class="ogz-mxl">Mission</span><b>${esc(m.name)}</b><small>${esc(m.role)} · under ${nm(m.manager)}</small></div>`).join("")}
          ${a.work.map(w => `<div class="ogz-mx engine"><span class="ogz-mxl">In ${esc(SYS[w.system]?.[1] || "")}</span><b>${esc(w.what)}</b><small>${w.lead ? `led by ${nm(w.lead)}` : ""}</small></div>`).join("")}
          ${a.assignments.length + a.missions.length + a.work.length ? "" : `<p class="faint small">None: it works in its home only.</p>`}
          <div class="row ogz-act"><button type="button" class="btn sm" data-ogz="assign-unit" data-key="${esc(a.key)}">${icon("plus")}Assign to a unit</button></div></section>
        <section><h4 class="ogz-sub">Authority</h4><p>${lvl(a.autonomy)}</p>
          <label class="in"><span>Change level</span><select data-ogz-level="${esc(a.key)}">${d.levels.map(l => `<option value="${l.level}" ${l.level === a.autonomy ? "selected" : ""}>L${l.level} ${esc(l.name)}${l.level >= d.approval_from && l.level > a.autonomy ? " (asks you)" : ""}</option>`).join("")}</select></label>
          <p class="small">Data scope: ${scope.length ? scope.slice(0, 8).map(x => esc(x.name)).join(", ") + (scope.length > 8 ? ` +${scope.length - 8}` : "") : "its home only"}.</p></section>
        <section><h4 class="ogz-sub">Expertise and availability</h4><p>${skills.map(([k, v]) => `<span class="co-skill">${esc(k.replace(/_/g, " "))} ${v}/5</span>`).join("") || `<span class="faint">None recorded.</span>`}</p>
          <p class="small ogz-mline">${avail(a)} <span>carries ${a.load} of ${a.cap} at once</span></p><div class="row ogz-act"><button type="button" class="btn sm" data-ogz="edit-profile" data-key="${esc(a.key)}">${icon("edit")}Title, skills, capacity</button>
          <button type="button" class="btn sm" data-ogz="pause" data-key="${esc(a.key)}" title="Paused agents get no new missions or tasks here; their own system is unchanged">${icon(a.status === "paused" ? "play" : "stop")}${a.status === "paused" ? "Resume" : "Pause"}</button></div></section>
        <section><h4 class="ogz-sub">Experience</h4><p class="small">${a.experience?.assignments_done || 0} assignments finished · ${a.experience?.missions_led || 0} missions led${a.experience?.since ? ` · in the organization since ${when(a.experience.since)}` : ""}</p>
          ${p ? `<p><b class="num">${p.score != null ? Math.round(p.score) : "–"}</b> <span class="faint small">score over ${plural(p.evidence, "finished piece")} of work · ${ago(p.ts)}</span></p>` : `<p class="faint small">Not scored yet (Knowledge & experience → Score agents).</p>`}</section>
        <section><h4 class="ogz-sub">Runtime</h4><p class="small">${state(a)} ${r.current ? esc(r.current) : ""}<br>Last activity ${r.last ? ago(r.last) : "never"} · ${r.runs_week || 0} runs, ${r.failed_week || 0} failed, ${tok(r.tokens_week || 0)} tokens in 7 days</p>
          <p class="small">Lives in ${sys ? `<button type="button" class="linkbtn" data-ogz-view="${sys[2]}">${icon(sys[0])}${esc(sys[1])}</button>` : esc(a.system)} · <code>${esc(a.ident)}</code>${a.status !== "active" ? ` ${badge("caution", esc(a.status))}` : ""}</p></section>
        <section class="ogz-span"><h4 class="ogz-sub">History</h4><div data-ogz-hist><button type="button" class="linkbtn" data-ogz="hist" data-key="${esc(a.key)}">Show reporting and mission history</button></div></section>
      </div>`, "", null, true);
    el.dataset.key = key;
  }
  function move(key) {
    const a = A(key);
    dlg(`Move ${esc(a.name)}`, `${field("Home unit", `<select name="unit">${unitOpts(a.unit_id, { none: "Not placed (reports to you)" })}</select>`)}
      ${field("Permanent manager", `<select name="manager"><option value="auto">By position: the unit's manager</option><option value="">You</option>${agentOpts(a.manager, { skip: [a.key] })}</select>`, "Changing the manager by hand is checked for reporting cycles. Assignments and missions are not affected.")}
      ${field("Why (kept in the audit log)", `<input type="text" name="reason" maxlength="200">`)}`, "Move", async fd => {
      await post("move_agent", { key, unit_id: fd.get("unit") ? +fd.get("unit") : null, manager: fd.get("manager") === "auto" ? "auto" : (fd.get("manager") || null), reason: fd.get("reason") });
    });
    const s = document.querySelector("#ogz-dlg [name=manager]"); if (s) s.value = "auto";
  }
  function affiliationDlg(key) {
    const a = A(key), home = U(a.unit_id);
    dlg(`${esc(a.name)}: department and role`, `${field("Department (profession)", `<select name="dept" ${home?.kind === "department" ? "disabled" : ""}>${unitOpts(a.dept_id, { none: "None", kinds: ["department"] })}</select>`,
        home?.kind === "department" ? "Its home is a department: that is its department." : "Hana's home can be the Bittensor Division while her department is Research & Intelligence. Departments lend their affiliated agents too.")}
      ${field("Role in its unit", `<input type="text" name="role" maxlength="80" value="${esc(a.unit_role || "")}" placeholder="e.g. Engineering Lead">`, "Shown as the division's leadership when set.")}`, "Save", async fd => {
      await post("affiliation", { key, ...(home?.kind === "department" ? {} : { dept_id: fd.get("dept") ? +fd.get("dept") : null }), unit_role: fd.get("role") || "" });
    });
  }
  function portfolioDlg({ key, port } = {}) {
    const a = key ? A(key) : null;
    dlg(a ? `${esc(a.name)}'s portfolio` : `${esc(P(port).title)}`, `${a ? "" : field("Executive", `<select name="key">${agentOpts(P(port).holder, { skip: [d.org.ceo] })}</select>`, "They join Executive staff and sponsor the portfolio's departments. Someone who manages a unit hands it over first.")}
      ${field("Portfolio", `<select name="port"><option value="">None</option>${d.portfolios.map(p => `<option value="${p.key}" ${(a ? a.portfolio : port) === p.key ? "selected" : ""}>${esc(p.short)} · ${esc(p.title)}${p.holder && p.holder !== key ? ` (now ${nm(p.holder)})` : ""}</option>`).join("")}</select>`, "One holder each: giving it to someone takes it from its holder.")}`,
      "Save", async fd => post("portfolio", { key: a ? key : fd.get("key"), portfolio: fd.get("port") || "" }));
  }
  function sponsorDlg(uid) {
    const u = U(uid);
    dlg(`${esc(u.name)}'s sponsor`, field("Executive sponsor", `<select name="key"><option value="">Nobody</option>${agentOpts(u.sponsor_key, { only: a => !!a.portfolio })}</select>`, "Oversight across the organization: the department's manager keeps reporting where they do."),
      "Save", async fd => post("sponsor", { unit_id: uid, key: fd.get("key") || "" }));
  }
  function budgetDlg(uid) {
    const u = U(uid), par = u.parent_id ? U(u.parent_id) : null;
    dlg(`${esc(u.name)}'s budget`, `${field("Tokens a day", `<input type="number" name="b" min="0" step="1000" value="${u.budget ?? ""}" placeholder="No allocation">`,
        `${par?.allocation != null ? `${esc(par.name)} has ${tok(par.allocation)} a day.` : !par && d.budget.cap ? `Your daily limit is ${tok(d.budget.cap)}.` : ""} ${u.allocated_below ? `Its own units already get ${tok(u.allocated_below)}.` : ""} Spent in the last 24 hours: ${tok(u.spent_day)}.`)}`,
      "Save", async fd => post("budget", { unit_id: uid, budget: fd.get("b") === "" ? null : +fd.get("b") }));
  }
  function assignUnitDlg({ key, unit } = {}) {
    const a = key ? A(key) : null;
    dlg(a ? `Assign ${esc(a.name)}` : "Assign an agent to a unit", `${a ? "" : field("Agent", `<select name="key">${agentOpts(null, { skip: [d.org.ceo] })}</select>`)}
      ${field("To", `<select name="unit">${unitOpts(unit, { kinds: ["division", "team", "squad", "department"] })}</select>`, "A squad, a team, a division or a department. Its home and manager don't change.")}
      <div class="row">${field("Role there", `<input type="text" name="role" maxlength="80" placeholder="e.g. Python engineer">`)}${field("Authority inside", `<select name="scope">${levelOpts(a ? a.autonomy : 1, a ? a.autonomy : 4)}</select>`, "Never above the agent's own level.")}</div>
      ${field("Responsibility", `<input type="text" name="duty" maxlength="300">`)}`, "Assign", async fd => post("assign_unit", { key: a ? key : fd.get("key"), unit_id: +fd.get("unit"), role: fd.get("role"), duty: fd.get("duty"), scope: +fd.get("scope") }));
  }
  function requestDlg(unit) {
    const depts = d.units.filter(u => u.kind === "department" && u.link !== "exec");
    const skills = [...new Set(d.agents.flatMap(a => Object.keys(a.skills)))].sort();
    const { el, f } = dlg("Request a specialist", `${field("For", `<select name="unit">${unitOpts(unit, { kinds: ["division", "team", "squad"] })}</select>`)}
      <div class="row">${field("From department", `<select name="dept">${depts.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select>`)}${field("Role there", `<input type="text" name="role" maxlength="80" placeholder="e.g. Python engineer">`)}</div>
      <fieldset class="co-skills"><legend>Skills it needs</legend>${skills.map(s => `<label><input type="checkbox" name="skills" value="${esc(s)}">${esc(s.replace(/_/g, " "))}</label>`).join("")}</fieldset>
      <div class="row"><button type="button" class="btn sm" data-find>${icon("search")}Find candidates</button></div>
      <div data-cands class="ogz-cands"><p class="faint small">Pick the department and skills, then find candidates: its members and affiliated agents, ranked by skill match, free capacity and performance.</p></div>
      ${field("Authority inside", `<select name="scope">${levelOpts(1)}</select>`, "Capped at the specialist's own level.")}`, d.org.policies.assign === "direct" ? "Assign" : "Send for approval", async fd => {
      const key = fd.get("cand");
      if (!key) throw new Error("Find candidates and pick one.");
      const c = A(key), u = U(+fd.get("unit"));
      const scope = Math.min(+fd.get("scope"), c.autonomy);
      const r = await api(`${B}/propose`, { method: "POST", body: { kind: "assign_unit", p: { unit_id: u.id, key, role: fd.get("role") || "", scope,
        title: `Lend ${c.name} (${deptName(+fd.get("dept"))}) to ${u.name}${fd.get("role") ? ` as ${fd.get("role")}` : ""}`,
        why: `Requested for ${u.name}${u.manager_key ? ` (managed by ${d.names[u.manager_key] || ""})` : ""}: ${fd.getAll("skills").join(", ") || "general fit"}. Authority inside L${scope}; home and manager unchanged.` } } });
      d = r.view; count(); toast(r.request_id ? "Sent to Governance → Approvals." : "Assigned.");
    });
    f.querySelector("[data-find]").onclick = async ev => busy(ev.currentTarget, async () => {
      const fd = new FormData(f);
      const r = await api(`${B}/units/${fd.get("unit")}/specialists?dept=${fd.get("dept")}&skills=${encodeURIComponent(fd.getAll("skills").join(","))}`);
      f.querySelector("[data-cands]").innerHTML = r.candidates.length ? `<ul class="ogz-list">${r.candidates.map((c, i) => `<li><label class="ogz-row"><input type="radio" name="cand" value="${esc(c.key)}" ${i === 0 && !c.full ? "checked" : ""} ${c.full ? "disabled" : ""}>
        <span><b>${esc(c.name)}</b> <span class="faint">${esc(c.title)}${c.home ? ` · ${esc(c.home)}` : ""}</span><small>${esc(c.why)} · L${c.level}${c.full ? " · at capacity" : ""}</small></span><b class="num">${Math.round(c.score)}</b></label></li>`).join("")}</ul>`
        : `<p class="faint small">Nobody in that department is free to lend: try another department, or fewer skills.</p>`;
    });
    return el;
  }
  function unitDlg({ kind, parent, id } = {}) {
    const u = id ? U(id) : null;
    kind = u?.kind || kind;
    dlg(u ? `Edit ${esc(u.name)}` : `New ${KIND[kind][1].toLowerCase()}`, `${field("Name", `<input type="text" name="name" maxlength="80" required value="${esc(u?.name || "")}">`)}
      ${field("Purpose", `<textarea name="purpose" rows="2" maxlength="300">${esc(u?.purpose || "")}</textarea>`)}
      ${kind === "team" || kind === "squad" ? field("Inside", `<select name="parent">${unitOpts(u ? u.parent_id : parent, { skip: u?.id, kinds: kind === "squad" ? ["team"] : ["division", "department", "team"] })}</select>`) : ""}
      ${field(kind === "team" ? "Team leader" : kind === "squad" ? "Squad lead" : kind === "division" ? "General manager" : "Manager", `<select name="manager">${agentOpts(u?.manager_key, { none: "Nobody yet", skip: [d.org.ceo] })}</select>`, "The manager moves into this unit and its people report to them. Their authority level stays as it is.")}
      ${u ? `<div class="ogz-danger"><button type="button" class="btn sm danger" data-ogz="dissolve" data-unit="${u.id}">${icon("trash")}Dissolve ${esc(u.name)}</button><small class="faint">Its people and teams move up to ${u.parent_id ? esc(U(u.parent_id)?.name || "the parent") : "not placed"}${u.squads?.length ? "; its squads dissolve with it" : ""}.</small></div>` : ""}`,
      u ? "Save" : "Create", async fd => {
        const name = String(fd.get("name") || "").trim(), mgr = fd.get("manager") || null;
        if (u) {
          await post("edit_unit", { unit_id: u.id, name, purpose: fd.get("purpose"), ...(kind === "team" || kind === "squad" ? { parent_id: +fd.get("parent") } : {}) });
          if ((mgr || null) !== (u.manager_key || null)) await post("set_manager", { unit_id: u.id, key: mgr });
        } else await post("add_unit", { kind, name, purpose: fd.get("purpose"), parent_id: kind === "team" || kind === "squad" ? +fd.get("parent") : null, manager_key: mgr });
      });
  }
  function missionDlg() {
    const skills = [...new Set(d.agents.flatMap(a => Object.keys(a.skills)))].sort();
    dlg("New mission", `${field("Name", `<input type="text" name="name" maxlength="120" required placeholder="Bittensor Competition 29">`)}
      ${field("Objective", `<textarea name="objective" rows="3" maxlength="1000" placeholder="What done looks like"></textarea>`)}
      <div class="row">${field("Owned by", `<select name="unit">${unitOpts(null, { none: "The whole organization", kinds: ["division", "department"] })}</select>`)}
        ${field("Mission manager", `<select name="manager">${agentOpts(null, { none: "Pick later" })}</select>`)}</div>
      <fieldset class="co-skills"><legend>Skills it needs (the CEO staffs by these)</legend>${skills.map(s => `<label><input type="checkbox" name="skills" value="${esc(s)}">${esc(s.replace(/_/g, " "))}</label>`).join("")}</fieldset>
      ${field("Due in (days, optional)", `<input type="number" name="due" min="1" max="365">`)}`, "Start mission", async fd => {
      const r = await post("add_mission", { name: fd.get("name"), objective: fd.get("objective"), unit_id: fd.get("unit") ? +fd.get("unit") : null, manager_key: fd.get("manager") || null,
                                           skills: fd.getAll("skills"), due: fd.get("due") ? Date.now() / 1000 + (+fd.get("due")) * 86400 : null });
      tab = "teams"; sub.teams = "missions"; return r;
    });
  }
  function assignDlg(mid) {
    const m = M(mid);
    dlg(`Assign to ${esc(m.name)}`, `${field("Agent", `<select name="key">${agentOpts(null, { skip: m.people.map(p => p.key) })}</select>`, "Their permanent manager doesn't change.")}
      ${field("Mission role", `<input type="text" name="role" maxlength="80" placeholder="e.g. Miner engineer">`)}${field("Responsibility", `<input type="text" name="duty" maxlength="300">`)}`, "Assign",
      async fd => post("assign", { mission_id: mid, key: fd.get("key"), role: fd.get("role"), duty: fd.get("duty") }));
  }
  function taskDlg(mid) {
    const m = mid ? M(mid) : null;
    dlg("Delegate a task", `${field("Task", `<input type="text" name="title" maxlength="200" required>`)}${field("Details", `<textarea name="detail" rows="3" maxlength="2000"></textarea>`)}
      <div class="row">${field("From", `<select name="from"><option value="">You</option>${agentOpts(m?.manager_key)}</select>`, "A manager hands work down its own line; a mission manager to the mission's people.")}
        ${field("To", `<select name="to">${agentOpts(null, m ? { only: a => m.people.some(p => p.key === a.key) } : {})}</select>`)}</div>
      <div class="row">${field("Mission", `<select name="mission"><option value="">None</option>${d.missions.map(x => `<option value="${x.id}" ${x.id === mid ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>`)}
        ${field("Authority it needs", `<select name="level">${levelOpts(1)}</select>`)}</div>
      <div class="row">${field("Sensitive action", `<select name="sensitive"><option value="">None</option>${Object.entries(d.locked).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("")}</select>`, "A sensitive task, or one at L3+, waits for your approval.")}
        ${field("Due in (days, optional)", `<input type="number" name="due" min="1" max="365">`, "Overdue work escalates one step a day.")}</div>`, "Delegate", async fd => {
      await post("delegate", { title: fd.get("title"), detail: fd.get("detail"), from_key: fd.get("from") || null, to_key: fd.get("to"), mission_id: fd.get("mission") ? +fd.get("mission") : null,
                               level: +fd.get("level"), sensitive: fd.get("sensitive") || null, due: fd.get("due") ? Date.now() / 1000 + (+fd.get("due")) * 86400 : null });
      tab = "teams"; sub.teams = "delegation";
    });
  }
  function settingsDlg() {
    dlg("Organization", `${field("Name", `<input type="text" name="name" maxlength="80" value="${esc(d.org.name)}">`)}
      <div class="row">${field("Owner (you)", `<input type="text" name="owner_name" maxlength="80" value="${esc(d.org.owner)}">`, "The name at the top of the chart, e.g. your Chairman persona. You remain the human owner and final authority.")}${field("Owner title", `<input type="text" name="owner_title" maxlength="80" value="${esc(d.org.owner_title)}">`)}</div>`,
      "Save", async fd => post("settings", { name: fd.get("name"), owner_name: fd.get("owner_name"), owner_title: fd.get("owner_title") }));
  }
  function profileEdit(key) {
    const a = A(key);
    dlg(`Edit ${esc(a.name)}`, `${field("Org title", `<input type="text" name="title" maxlength="80" value="${esc(a.title === a.role || (a.portfolio && a.title === P(a.portfolio)?.title) ? "" : a.title)}" placeholder="${esc(a.portfolio ? P(a.portfolio).title : a.role)}">`, "Shown in the organization; the agent's own system keeps its role.")}
      ${field("Skills", `<input type="text" name="skills" value="${esc(Object.entries(a.skills).map(([k, v]) => `${k}:${v}`).join(", "))}">`, "skill:level, comma-separated, levels 1-5 (e.g. python:5, testing:3).")}
      ${field("Capacity", `<input type="number" name="cap" min="1" max="12" value="${a.cap}">`, "Assignments, missions and jobs at once; nobody recommends a full agent.")}`, "Save", async fd => {
      const sk = {};
      for (const part of String(fd.get("skills") || "").split(",").map(s => s.trim()).filter(Boolean)) {
        const [k, v] = part.split(":").map(s => s.trim());
        if (!k || !(+v >= 1 && +v <= 5)) throw new Error(`"${part}": write skill:level with a level from 1 to 5.`);
        sk[k] = +v;
      }
      await post("profile", { key, title: fd.get("title") || "", skills: sk, cap: +fd.get("cap") });
    });
  }
  function ceoDlg() {
    dlg("Pick the CEO", `${field("CEO", `<select name="key">${agentOpts(d.org.ceo)}</select>`, "Coordinates the organization and allocates people. Top units' managers report to the CEO; the CEO reports to you.")}`, "Make CEO",
      async fd => post("set_ceo", { key: fd.get("key") }));
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    const close = () => document.getElementById("ogz-dlg")?.close();
    document.addEventListener("click", async e => {
      const t = e.target, inDlg = t.closest("#ogz-dlg");
      if (!t.closest("#ogz") && !inDlg) return;
      const tb = t.closest("[data-ogz-tab]"); if (tb && !inDlg) { setTab(tb.dataset.ogzTab); return render(); }
      const sb = t.closest("[data-ogz-sub]"); if (sb) { const [n, v] = sb.dataset.ogzSub.split(":"); sub[n] = v; return render(); }
      const v = t.closest("[data-ogz-view]"); if (v) { close(); return setView(v.dataset.ogzView); }
      const tm = t.closest("[data-ogz-team]"); if (tm) { close(); return MiningWork.openPage(+tm.dataset.ogzTeam || null); }
      const s = t.closest("[data-ogz-sys]"); if (s) { sysF = s.dataset.ogzSys; return render(); }
      const tr = t.closest("[data-ogz-tier]"); if (tr) { tierF = tr.dataset.ogzTier; return render(); }
      const tg = t.closest("[data-ogz-tier-go]"); if (tg) { if (tg.dataset.ogzTierGo === "owner") return; tierF = tg.dataset.ogzTierGo; setTab("directory"); sub.directory = "profiles"; return render(); }
      const b = t.closest("[data-ogz]"), act = b?.dataset.ogz;
      const ag = t.closest("[data-ogz-agent]"); if (ag && !act) { if (inDlg) close(); return profile(ag.dataset.ogzAgent); }
      if (!act) return;
      const mid = +b.dataset.mission || null, unit = +b.dataset.unit || null;
      if (act === "reload") { know = null; return load(); }
      if (act === "know") return busy(b, async () => { know = null; render(); await loadKnow(); });
      if (act === "settings") return settingsDlg();
      if (act === "ceo") return ceoDlg();
      if (act === "audit") return busy(b, async () => { audit = (await api(`${B}/audit`)).audit; render(); });
      if (act === "add-unit") return unitDlg({ kind: b.dataset.kind, parent: +b.dataset.parent || null });
      if (act === "edit-unit" || act === "set-manager") return unitDlg({ id: unit });
      if (act === "sponsor") return sponsorDlg(unit);
      if (act === "budget") return budgetDlg(unit);
      if (act === "request") { close(); return requestDlg(unit); }
      if (act === "assign-unit") { close(); return assignUnitDlg({ key: b.dataset.key || null, unit }); }
      if (act === "release-unit") return change("release_unit", { unit_id: unit, key: b.dataset.key }, b);
      if (act === "portfolio") { close(); return portfolioDlg({ key: b.dataset.key || null, port: b.dataset.port || null }); }
      if (act === "affiliation") { close(); return affiliationDlg(b.dataset.key); }
      if (act === "dissolve") {
        const u = U(unit);
        if (!(await UI.confirm({ title: `Dissolve ${esc(u.name)}?`, body: "Its people and teams move up a level. Missions and reporting lines stay valid; the audit log keeps the change.", ok: "Dissolve" }))) return;
        close();
        return change("dissolve", { unit_id: u.id });  // your own edit: applies at once (the policy is for proposals)
      }
      if (act === "move") { close(); return move(b.dataset.key); }
      if (act === "edit-profile") { close(); return profileEdit(b.dataset.key); }
      if (act === "pause") { const a = A(b.dataset.key); close(); return change("profile", { key: a.key, status: a.status === "paused" ? "active" : "paused" }, b); }
      if (act === "hist") return busy(b, async () => {
        const h = await api(`${B}/agents/${encodeURIComponent(b.dataset.key)}/history`), box = t.closest("[data-ogz-hist]");
        box.innerHTML = `<ol class="ogz-hist">${h.lines.map(l => `<li>Reports to <b>${l.manager_key ? nm(l.manager_key) : "you"}</b> from ${when(l.since)}${l.ended ? ` to ${when(l.ended)}` : " (now)"} · ${esc(l.reason || "")} <span class="faint">${esc(l.by || "")}</span></li>`).join("")}
          ${h.missions.map(m => `<li>Mission <b>${esc(m.name)}</b> as ${esc(m.role)} under ${nm(m.manager_key)}, ${when(m.since)}${m.released ? ` – ${when(m.released)}` : " (now)"}</li>`).join("")}</ol>`;
      });
      if (act === "add-mission") return missionDlg();
      if (act === "assign") return assignDlg(mid);
      if (act === "task") return taskDlg(mid);
      if (act === "mission-manager") return dlg("Mission manager", field("Agent", `<select name="key">${agentOpts(null)}</select>`), "Set", async fd => post("mission_manager", { mission_id: mid, key: fd.get("key") }));
      if (act === "release") return change("release", { mission_id: mid, key: b.dataset.key }, b);
      if (act === "end-mission") {
        const m = M(mid);
        if (!(await UI.confirm({ title: `End ${esc(m.name)}?`, body: `${plural(m.people.length, "agent")} return to their departments; its open tasks are cancelled.`, ok: "End mission", icon: "check", danger: false }))) return;
        recFor[mid] = null; return change("end_mission", { mission_id: mid });
      }
      if (act === "recommend") return busy(b, async () => { recFor[mid] = await api(`${B}/missions/${mid}/recommend`); render(); });
      if (act === "close-rec") { recFor[mid] = null; return render(); }
      if (act === "take-rec") {
        const r = recFor[mid], keys = [...r.team, ...(r.evaluator ? [r.evaluator] : [])].map(c => c.key);
        recFor[mid] = null;
        return propose("assign", { mission_id: mid, keys, title: `Staff ${M(mid).name}: ${keys.map(k => d.names[k]).join(", ")}`, why: "The CEO's recommendation: skill match, free capacity and performance.", by: "atlas" }, b);
      }
      if (act === "task-act") {
        const tid = +b.dataset.task, a = b.dataset.act;
        if (a === "assign") {
          const tk = d.tasks.find(x => x.id === tid);
          return dlg("Reassign the task", field("To", `<select name="to">${agentOpts(null, { only: x => x.autonomy >= tk.level })}</select>`, `Only agents with L${tk.level} or more.`), "Reassign",
            async fd => post("task", { task_id: tid, action: "assign", to_key: fd.get("to") }));
        }
        return change("task", { task_id: tid, action: a }, b);
      }
      if (act === "policy") return change("settings", { policies: { [b.dataset.k]: b.dataset.v } }, b);
      if (act === "perf") return busy(b, async () => { const r = await api(`${B}/performance`, { method: "POST" }); recs = { recommendations: r.recommendations }; d = r.view; render(); toast("Scores updated"); });
      if (act === "take-perf") {
        const r = recs.recommendations[+b.dataset.i];
        const kind = r.kind === "review" ? "autonomy" : r.kind === "manager" ? "set_manager" : "promote";
        const res = await propose(kind, { ...r.payload, title: r.title, why: r.why, by: "performance" }, b);
        if (res) recs.recommendations.splice(+b.dataset.i, 1), render();
        return;
      }
      if (act === "decide") {
        const ok = b.dataset.ok === "1";
        return busy(b, async () => {
          const r = await api(`${B}/requests/${b.dataset.req}`, { method: "POST", body: { ok, note: "" } });
          d = r.view; count(); render(); toast(ok ? (r.result ? `Applied: ${r.result}` : "Approved") : "Rejected");
        });
      }
    });
    document.addEventListener("change", e => {
      const s = e.target.closest?.("[data-ogz-level]"); if (!s) return;
      const a = A(s.dataset.ogzLevel), lv = +s.value;
      if (!a || lv === a.autonomy) return;
      document.getElementById("ogz-dlg")?.close();
      propose("autonomy", { key: a.key, level: lv, why: `${a.name} from L${a.autonomy} to L${lv}.` });
    });
    document.addEventListener("input", e => {
      const i = e.target; if (!i.matches?.("#ogz [data-ogz-q]")) return;
      q = i.value; const pos = i.selectionStart; render();
      const n = document.querySelector("#ogz [data-ogz-q]"); if (n) { n.focus(); n.setSelectionRange(pos, pos); }
    });
    // drag an agent onto a unit (or "Not placed yet") to move its home
    document.addEventListener("dragstart", e => { const c = e.target.closest?.("#ogz [data-ogz-drag]"); if (!c) return; dragKey = c.dataset.ogzDrag; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragKey); });
    document.addEventListener("dragend", () => { dragKey = null; document.querySelectorAll("#ogz .drop").forEach(x => x.classList.remove("drop")); });
    document.addEventListener("dragover", e => { const z = dragKey && e.target.closest?.("#ogz [data-ogz-drop]"); if (!z) return; e.preventDefault(); document.querySelectorAll("#ogz .drop").forEach(x => x !== z && x.classList.remove("drop")); z.classList.add("drop"); });
    document.addEventListener("drop", async e => {
      const z = dragKey && e.target.closest?.("#ogz [data-ogz-drop]"); if (!z) return;
      e.preventDefault(); z.classList.remove("drop");
      const key = dragKey, unit = z.dataset.ogzDrop ? +z.dataset.ogzDrop : null, a = A(key); dragKey = null;
      if (!a || (a.unit_id || null) === unit) return;
      const to = unit ? U(unit) : null;
      if (!(await UI.confirm({ title: `Move ${esc(a.name)} to ${to ? esc(to.name) : "Not placed"}?`, body: `${esc(a.name)}'s home becomes ${to ? esc(to.name) : "none"} and it reports to ${to?.manager_key && to.manager_key !== key ? nm(to.manager_key) : to ? "the manager above " + esc(to.name) : "you"}. Assignments and missions are not affected. To lend it instead, use Assign in its profile.`, ok: "Move", icon: "swap", danger: false }))) return;
      change("move_agent", { key, unit_id: unit, manager: "auto", reason: "dragged on the org chart" });
    });
  }

  return { open, stop, show, load, data: () => d };
})();
