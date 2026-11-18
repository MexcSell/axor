/* Agent workspaces (company_agents.py): Company → Agents. company.js draws the page and hands this module its kit (the data,
   its chips and formatters, render/take/busy) for the Agents tab.
   - Directory: search, filter (group, status, skill, project, model profile), sort, compare in a table, register, open a workspace.
   - Workspace: the same template for every agent, its tabs chosen by the server from the contract: overview, chat, instructions,
     tasks, memory, knowledge, skills, tools, files, workflows, performance, activity, settings.
   - Chat runs in the background: it polls every 1.5 s while an answer is coming and redraws only the messages while you type.
     What an answer suggests (save, remember, task, approval, hand off) is a button: nothing happens until you press it. */
const CompanyAgents = (() => {
  const C = "/api/company";
  const TABS = { overview: ["dash", "Overview"], chat: ["chat", "Chat"], instructions: ["note", "Instructions"], tasks: ["list", "Tasks"], memory: ["bulb", "Memory"],
                 knowledge: ["book", "Knowledge"], skills: ["star", "Skills"], tools: ["wrench", "Tools"], files: ["doc", "Files"], workflows: ["route", "Workflows"],
                 performance: ["chart", "Performance"], activity: ["clock", "Activity"], settings: ["gear", "Settings"] };
  const ACTK = { chat: "run", tool: "ok", config: "warn", error: "bad", status: "none", memory: "none", handoff: "run", rating: "none", assignment: "none" };
  let K = null, wired = false, sel = null, wtab = "overview", poll = null, sig = null;
  let ws = {}, conv = {}, draft = {}, refs = {}, atts = {}, ctxNew = {}, openFile = {}, dir = null, dirAt = 0;
  let q = "", fGroup = "all", fStatus = "active", fSkill = "", fProject = "", fProfile = "", sort = "name", compare = false;
  const root = () => document.getElementById("company");
  const typing = () => !!document.activeElement?.closest?.("#company form, #company textarea, #company input[type=text], #company input[type=number], #company select");
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const ms = n => n == null ? "–" : n < 1000 ? `${n} ms` : `${fmtNum(n / 1000, 1)} s`;
  const pct = n => n == null ? "–" : `${n}%`;
  const W = () => ws[sel];
  const group = a => a.category === "leadership" ? "Leadership" : a.category === "shared" ? "Shared specialist" : esc(K.DIV(a.division_id)?.name || "");
  const role = a => a.lead ? "Lead" : a.evaluator ? "Evaluator" : a.category === "leadership" ? "Leadership" : "Specialist";

  // ---------- data ----------
  function open(aid) { if (sel !== aid) { sel = aid; wtab = "overview"; } fetchWs(aid); }
  function refresh(aid) { if (aid === sel || ws[aid]) fetchWs(aid); dirAt = 0; }
  async function fetchWs(aid, opts = {}) {
    const cv = conv[aid], was = !!ws[aid]?.running;
    try { ws[aid] = await api(`${C}/agents/${aid}/workspace${cv != null ? `?conversation=${cv}` : ""}`); if (cv == null) conv[aid] = ws[aid].conversation_id; }
    catch (e) { K?.err(e); if (e.message && /no such agent/i.test(e.message)) { sel = null; delete ws[aid]; } }
    draw(opts.msgsOnly, was && !ws[aid]?.running);
    schedule();
  }
  async function fetchDir() {
    if (Date.now() - dirAt < 20000 && dir) return;
    dirAt = Date.now();
    try { dir = await api(`${C}/directory`); } catch { dir = dir || { config: {}, assignments: [], profiles: {}, autonomy: {} }; }
    if (!sel && !typing()) K.render();
  }
  // finished: an answer just arrived. Redraw it all then (Send, Stop and the status are outside the messages), even while you
  // type in the composer, which keeps its text (draft) and gets the focus back; typing anywhere else only gets the messages
  function draw(msgsOnly, finished) {
    if (!K || !root()) return;
    const inDraft = !!document.activeElement?.matches?.("[data-cawdraft]");
    if (!(finished && (inDraft || !typing())) && (typing() || msgsOnly)) {
      const el = document.getElementById("caw-msgs"); if (el && W()) { put(el, messages(W())); scrollMsgs(); return; } if (typing()) return; }
    K.render(); scrollMsgs();
    if (finished && inDraft) { const n = root().querySelector("[data-cawdraft]"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }
  }
  function scrollMsgs() { const el = document.getElementById("caw-msgs"); if (el && el.dataset.at !== String(W()?.messages.at(-1)?.id || 0) + (W()?.running ? "r" : "")) { el.scrollTop = el.scrollHeight; el.dataset.at = String(W()?.messages.at(-1)?.id || 0) + (W()?.running ? "r" : ""); } }
  function schedule() {
    clearTimeout(poll);
    if (!sel || !W()?.running) return;
    poll = setTimeout(() => { if (!sel || $("#view-company")?.hidden || document.visibilityState !== "visible") return schedule(); fetchWs(sel, { msgsOnly: typing() }); }, 1500);
  }
  function take(r, aid = sel) { if (r?.agent) { ws[aid] = r; if (r.conversation_id != null) conv[aid] = r.conversation_id; dirAt = 0; draw(); schedule(); } else if (r) K.take(r); return r; }

  // ---------- the Agents tab ----------
  function tab(kit) {
    K = kit; wire();
    if (sel && !K.A(sel)) sel = null;
    if (!dir || Date.now() - dirAt > 20000) fetchDir();
    // a team run started or ended: its tasks, files and numbers changed
    const now = `${K.d.counts.running}:${K.d.tasks.filter(t => ["done", "failed"].includes(t.status)).length}`;
    if (now !== sig) { const first = sig === null; sig = now; if (!first && sel && W()) fetchWs(sel); }
    if (!sel) return directory();
    const w = W();
    if (!w) return `<div class="caw-back"><button type="button" class="btn sm ghost" data-caw="back">${icon("left")}Directory</button></div>${Loading.line("Opening the workspace…")}`;
    return workspace(w);
  }

  function directory() {
    const d = K.d, cfg = id => dir?.config?.[id] || {};
    const groups = [["all", "All"], ["leadership", "Leadership"], ...d.divisions.map(x => [`d${x.id}`, x.name.replace(" Division", "")]), ["shared", "Shared"]];
    const assigned = (aid, pid) => (dir?.assignments || []).some(x => x.agent_id === aid && x.project_id === pid);
    const onProject = (a, p) => a.category !== "division" || a.division_id === p.division_id || assigned(a.id, p.id)
      || d.teams.some(t => t.project_id === p.id && t.status === "active" && t.members.some(m => m.agent_id === a.id));
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let list = d.agents.filter(a => (fGroup === "all" || a.category === fGroup || `d${a.division_id}` === fGroup)
      && (fStatus === "all" ? true : fStatus === "active" ? a.status !== "archived" : a.status === fStatus)
      && (!fSkill || a.skills[fSkill]) && (!fProject || (K.P(+fProject) && onProject(a, K.P(+fProject))))
      && (!fProfile || (cfg(a.id).profile || "standard") === fProfile)
      && words.every(w => `${a.name} ${a.title} ${a.about} ${Object.keys(a.skills).join(" ")} ${role(a)}`.toLowerCase().includes(w)));
    const key = { name: a => a.name.toLowerCase(), score: a => -(a.outcomes.avg ?? -1), tasks: a => -a.outcomes.tasks, load: a => -a.load / a.max_load, tokens: a => -(cfg(a.id).month || 0) }[sort];
    list = list.sort((x, y) => { const a = key(x), b = key(y); return a < b ? -1 : a > b ? 1 : x.id - y.id; });
    const opt = (v, l, cur) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(l)}</option>`;
    return `<div class="co-filter">${groups.map(([k, l]) => `<button type="button" class="co-chip ${fGroup === k ? "on" : ""}" data-cawg="${k}">${esc(l)}</button>`).join("")}
        <details class="co-add"><summary class="btn sm">${icon("plus")}Register an agent</summary>${K.newAgent()}</details></div>
      <div class="caw-tools">
        <label class="in caw-search"><span class="sr">Search agents</span>${icon("search")}<input type="text" data-cawq value="${esc(q)}" placeholder="Search name, role, skill…" maxlength="80"></label>
        <label class="in"><span class="sr">Status</span><select data-cawf="status">${[["active", "Not archived"], ["all", "Any status"], ["available", "Available"], ["paused", "Paused"], ["disabled", "Disabled"], ["archived", "Archived"]].map(([v, l]) => opt(v, l, fStatus)).join("")}</select></label>
        <label class="in"><span class="sr">Skill</span><select data-cawf="skill">${opt("", "Any skill", fSkill)}${Object.keys(d.catalog.skills).map(k => opt(k, k.replace(/_/g, " "), fSkill)).join("")}</select></label>
        <label class="in"><span class="sr">Project</span><select data-cawf="project">${opt("", "Any project", fProject)}${d.projects.filter(p => p.status !== "archived").map(p => opt(p.id, p.name, fProject)).join("")}</select></label>
        <label class="in"><span class="sr">Model profile</span><select data-cawf="profile">${opt("", "Any model profile", fProfile)}${Object.entries(dir?.profiles || {}).map(([k, l]) => opt(k, l, fProfile)).join("")}</select></label>
        <label class="in"><span class="sr">Sort</span><select data-cawf="sort">${[["name", "Sort: name"], ["score", "Sort: average score"], ["tasks", "Sort: tasks"], ["load", "Sort: workload"], ["tokens", "Sort: tokens this month"]].map(([v, l]) => opt(v, l, sort)).join("")}</select></label>
        <button type="button" class="btn sm ${compare ? "primary" : ""}" data-caw="compare" aria-pressed="${compare}">${icon("table")}Compare</button>
        <span class="faint small">${K.plural(list.length, "agent")}</span></div>
      ${!list.length ? `<section class="card"><p class="faint">No agent matches.</p></section>` : compare ? compareTable(list, cfg) : `<div class="caw-grid">${list.map(a => card(a, cfg(a.id))).join("")}</div>`}`;
  }
  function card(a, cf) {
    const sk = Object.entries(a.skills).sort((x, y) => y[1] - x[1]);
    return `<button type="button" class="card co-agent caw-card st-${a.status}" data-cawopen="${a.id}">
      <div class="co-agent-h"><b>${a.lead ? icon("star") : a.evaluator ? icon("check") : icon("bot")}${esc(a.name)}</b>${K.chip(K.AG[a.status] || "none", esc(a.status))}</div>
      <span class="small">${esc(a.title)}</span><span class="faint small">${group(a)} · ${role(a)}</span>
      ${cf.mission ? `<span class="small caw-mission">${esc(cf.mission)}</span>` : ""}
      <div>${sk.slice(0, 4).map(([k, v]) => `<span class="co-skill">${esc(k)} ${v}</span>`).join("")}</div>
      <div class="co-load"><div class="co-bar"><i style="width:${Math.min(100, 100 * a.load / a.max_load)}%"></i></div><span class="faint small num">${a.load}/${a.max_load} teams · ${a.outcomes.tasks} tasks${a.outcomes.avg != null ? ` · avg ${a.outcomes.avg}` : ""}${cf.month ? ` · ${K.tok(cf.month)} this month` : ""}</span></div></button>`;
  }
  function compareTable(list, cfg) {
    return `<section class="card"><div class="co-tablewrap"><table class="co-table caw-compare"><thead><tr><th>Agent</th><th>Group</th><th>Status</th><th>Model profile</th><th>Autonomy</th>
        <th class="num">Tasks</th><th class="num">Avg score</th><th class="num">Chat answers</th><th class="num">Ratings</th><th class="num">Workload</th><th class="num">Tokens (month)</th></tr></thead><tbody>
      ${list.map(a => { const c = cfg(a.id); return `<tr><td><button type="button" class="linkbtn" data-cawopen="${a.id}">${esc(a.name)}</button> <span class="faint small">${esc(a.title)}</span></td>
        <td class="small">${group(a)}</td><td>${K.chip(K.AG[a.status] || "none", esc(a.status))}</td><td class="small">${esc(dir?.profiles?.[c.profile || "standard"] || "")}${c.model ? ` <code class="small">${esc(c.model)}</code>` : ""}</td>
        <td class="small">${esc(dir?.autonomy?.[c.autonomy || "advisory"] || "")}</td><td class="num">${a.outcomes.tasks}</td><td class="num">${a.outcomes.avg ?? "–"}</td><td class="num">${c.answers || 0}</td>
        <td class="num">${c.up || c.down ? `${icon("thumbup")}${c.up} ${icon("thumbdown")}${c.down}` : "–"}</td><td class="num">${a.load}/${a.max_load}</td>
        <td class="num">${K.tok(c.month || 0)}${c.budget ? ` <span class="faint small">of ${K.tok(c.budget)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table></div></section>`;
  }

  // ---------- the workspace ----------
  function workspace(w) {
    const a = w.agent, cf = w.config, pf = w.performance;
    if (!w.tabs.includes(wtab)) wtab = "overview";
    const body = { chat, instructions, tasks, memory, knowledge, skills, tools, files, workflows, performance, activity, settings }[wtab] || overview;
    const live = a.status === "available";
    return `<div class="caw-back"><button type="button" class="btn sm ghost" data-caw="back">${icon("left")}Directory</button></div>
      <section class="card caw-head">
        <div class="caw-id"><span class="caw-avatar ${live ? "on" : ""}" aria-hidden="true">${icon(a.lead ? "star" : a.evaluator ? "check" : "bot")}</span>
          <div><h2>${esc(a.name)} <span class="faint">· ${esc(a.title)}</span></h2>
            <p class="faint small">${group(a)}${w.contexts.length ? ` · ${w.contexts.slice(0, 3).map(x => esc(x.name)).join(", ")}${w.contexts.length > 3 ? ` +${w.contexts.length - 3}` : ""}` : ""}</p>
            <div class="caw-chips">${K.chip(K.AG[a.status] || "none", a.status === "available" ? "Active" : esc(a.status))}${K.chip("none", role(a))}${K.chip("none", esc(w.catalog.profiles[cf.profile]?.label || cf.profile), "chip")}${K.chip(cf.autonomy === "advisory" ? "none" : "run", esc(w.catalog.autonomy[cf.autonomy]?.label || cf.autonomy), "shield")}</div></div></div>
        <div class="caw-kpis">
          ${kpi("Tasks done", pf.done, `${K.plural(pf.tasks, "task")} worked on`)}${kpi("Success", pct(pf.pass_rate), pf.avg_score != null ? `avg score ${pf.avg_score}` : "no scored work yet")}
          ${kpi("Tokens this month", K.tok(cf.month_spent), cf.budget ? `of ${K.tok(cf.budget)} budget` : "no monthly cap", cf.budget && cf.month_spent >= cf.budget ? "t-warn" : "")}
          ${kpi("Chat answers", pf.chat.answers, pf.chat.up || pf.chat.down ? `${pf.chat.up} helpful · ${pf.chat.down} not` : "not rated yet")}</div>
        <div class="row co-act caw-life">${a.status === "available" ? `<button type="button" class="btn sm" data-cawlife="pause">${icon("stop")}Pause</button>`
          : `<button type="button" class="btn sm" data-cawlife="resume">${icon("play")}${a.status === "archived" ? "Restore" : "Resume"}</button>`}
          <button type="button" class="btn sm ghost" data-cawlife="clone">${icon("copy")}Clone</button>
          ${a.status !== "archived" ? `<button type="button" class="btn sm ghost" data-cawlife="archive" ${a.load ? `disabled title="On a team at work"` : ""}>${icon("inbox")}Archive</button>` : ""}</div></section>
      <nav class="co-tabs caw-tabs" role="tablist" aria-label="${esc(a.name)}'s workspace">${w.tabs.map(t => `<button type="button" role="tab" class="co-tab ${wtab === t ? "on" : ""}" aria-selected="${wtab === t}" data-cawtab="${t}">${icon(TABS[t][0])}${TABS[t][1]}${t === "chat" && w.running ? ` <span class="badge new">…</span>` : ""}</button>`).join("")}</nav>
      <div class="caw-body">${body(w)}</div>`;
  }
  const kpi = (l, v, sub, cls = "") => `<div class="stat ${cls}"><div class="label">${l}</div><div class="value num">${v}</div><div class="sub">${sub}</div></div>`;
  const projName = id => id ? esc(K.P(id)?.name || `project ${id}`) : "the company (no project)";

  function overview(w) {
    const a = w.agent, cf = w.config;
    return `<div class="co-two">
      <section class="card"><h3 class="caw-h">${icon("target")}Current mission</h3><p>${esc(cf.mission || a.about || "No mission set.")}</p>
        ${cf.mission && a.about ? `<p class="faint small">${esc(a.about)}</p>` : ""}
        <button type="button" class="btn sm ghost" data-cawtab="instructions">${icon("edit")}Edit the mission and instructions</button></section>
      <section class="card"><h3 class="caw-h">${icon("folder")}Works on</h3>
        ${w.contexts.length ? `<ul class="co-list">${w.contexts.map(x => `<li><button type="button" class="linkbtn" data-coproj="${x.id}">${esc(x.name)}</button><span class="faint small">${esc(x.division)} · ${esc(x.why)}</span></li>`).join("")}</ul>` : `<p class="faint small">No project yet: assign it to one under Settings.</p>`}</section></div>
      <div class="co-two">
        <section class="card"><h3 class="caw-h">${icon("shield")}How it works</h3>
          <dl class="co-dl"><dt>Model</dt><dd>${cf.model_id ? `<code>${esc(cf.model_id)}</code> · effort ${esc(cf.effort)}` : `<span class="co-fail">${esc(cf.model_error || "none")}</span>`}</dd>
            <dt>Autonomy</dt><dd>${esc(w.catalog.autonomy[cf.autonomy]?.means || "")}</dd>
            <dt>Tools on</dt><dd>${Object.entries(cf.tools).filter(([, v]) => v).map(([k]) => esc(w.catalog.tools[k].label)).join(" · ") || "none"}</dd>
            <dt>Never</dt><dd>${Object.keys(w.contract.restrictions).map(k => `<span class="co-skill off">${esc(k.replace(/_/g, " "))}</span>`).join("")}</dd></dl></section>
        <section class="card"><div class="co-h"><h3 class="caw-h">${icon("clock")}Recent activity</h3><button type="button" class="btn sm" data-cawtab="activity">All activity</button></div>
          <ul class="co-list">${w.activity.slice(0, 6).map(actRow).join("") || `<li class="faint">Nothing yet.</li>`}</ul></section></div>`;
  }

  // ---------- chat ----------
  function chat(w) {
    const a = w.agent, cid = conv[a.id], c = w.conversations.find(x => x.id === cid), live = a.status === "available";
    const pid = c ? c.project_id : (ctxNew[a.id] ?? w.contexts[0]?.id ?? 0) || null;
    const files = pid ? K.d.artifacts.filter(x => x.project_id === pid) : [];
    const myRefs = (refs[a.id] || []).filter(id => files.some(f => f.id === id)), myAtts = atts[a.id] || [];
    const team = pid && K.d.teams.find(t => t.project_id === pid && t.status === "active" && t.members.some(m => m.agent_id === a.id));
    return `<div class="caw-chat">
      <aside class="card caw-convs"><button type="button" class="btn sm ${cid ? "" : "primary"}" data-cawconv="0">${icon("plus")}New conversation</button>
        <ul>${w.conversations.map(x => `<li><button type="button" class="caw-conv ${x.id === cid ? "on" : ""}" data-cawconv="${x.id}"><b>${esc(x.title || "Conversation")}</b><span class="faint small">${projName(x.project_id)} · ${K.when(x.updated)}</span></button></li>`).join("") || `<li class="faint small">No conversation yet.</li>`}</ul></aside>
      <section class="card caw-room">
        <div class="caw-room-h"><div><b>${esc(a.name)}</b> ${w.running ? K.chip("run", "Answering…", "cycle") : live ? K.chip("ok", "Ready") : K.chip("warn", esc(a.status))}
            <p class="faint small">${c ? `Project: ${projName(c.project_id)}` : `<label class="caw-ctx">Context <select data-cawctx>${w.contexts.map(x => `<option value="${x.id}" ${x.id === pid ? "selected" : ""}>${esc(x.name)}</option>`).join("")}<option value="0" ${!pid ? "selected" : ""}>The company (no project)</option></select></label>`}${team ? ` · Team: ${esc(team.name)}` : ""}</p></div>
          ${K.chip("none", "Analysis only", "shield")}</div>
        <div class="caw-msgs" id="caw-msgs" aria-live="polite">${messages(w)}</div>
        <form class="caw-compose" data-cawform="chat">
          ${myRefs.length || myAtts.length ? `<div class="caw-refs">${myRefs.map(id => `<span class="co-skill">${icon("doc")}${esc(files.find(f => f.id === id)?.title || id)} <button type="button" class="linkbtn" data-cawunref="${id}" aria-label="Remove">×</button></span>`).join("")}${myAtts.map((x, i) => `<span class="co-skill">${icon("clip")}${esc(x.name)} <button type="button" class="linkbtn" data-cawunatt="${i}" aria-label="Remove">×</button></span>`).join("")}</div>` : ""}
          <label class="in"><span class="sr">Message ${esc(a.name)}</span><textarea name="text" rows="3" maxlength="8000" data-cawdraft placeholder="Message ${esc(a.name)}… (Ctrl+Enter sends)" ${live ? "" : "disabled"}>${esc(draft[a.id] || "")}</textarea></label>
          <div class="row caw-compose-act">
            ${files.length ? `<label class="in"><span class="sr">Reference a project file</span><select data-cawref><option value="">Reference a file…</option>${files.filter(f => !myRefs.includes(f.id)).map(f => `<option value="${f.id}">${esc(f.title)}</option>`).join("")}</select></label>` : ""}
            <label class="btn sm ghost caw-attach">${icon("clip")}Attach<input type="file" data-cawattach accept=".txt,.md,.py,.json,.csv,.log,.yaml,.yml,.toml,.js,.ts,.rs,.go,.sql,.sh,text/*" hidden></label>
            <span class="caw-grow"></span>
            ${w.running ? `<button type="button" class="btn sm" data-cawstop="${w.running.id}">${icon("stop")}Stop</button>` : ""}
            <button type="submit" class="btn sm primary" ${live && !w.running ? "" : "disabled"}>${icon("send")}Send</button></div>
          <p class="faint small">${esc(w.catalog.autonomy[w.config.autonomy]?.means || "")} Production and outside actions always need your approval.</p></form></section></div>`;
  }
  function messages(w) {
    const a = w.agent;
    if (!w.messages.length) return `<div class="caw-empty"><p>${icon("chat")}Ask ${esc(a.name)} to analyze, plan or draft something.</p><p class="faint small">It answers from its role, its contract and what it may read in this conversation's context. It runs nothing.</p></div>`;
    return w.messages.map(m => m.role === "user" ? `<div class="caw-msg me"><div class="caw-bub">${esc(m.body).replace(/\n/g, "<br>")}${(m.meta.files || []).length || (m.meta.attachments || []).length ? `<p class="faint small">${[...(m.meta.files || []).map(f => `${icon("doc")}${esc(f.title)}`), ...(m.meta.attachments || []).map(x => `${icon("clip")}${esc(x.name)}`)].join(" · ")}</p>` : ""}</div><span class="faint small">You · ${K.when(m.ts)}</span></div>`
      : m.role === "handoff" ? `<div class="caw-msg hand"><div class="caw-bub"><p class="small"><b>${icon("send")}Handed over by ${esc(m.meta.from || "another agent")}</b></p><div class="md">${Agents.md(m.body)}</div></div><span class="faint small">${K.when(m.ts)}</span></div>`
      : agentMsg(w, m)).join("");
  }
  function agentMsg(w, m) {
    const a = w.agent, mt = m.meta || {}, ap = mt.applied || {}, t = w.config.tools, c = w.conversations.find(x => x.id === conv[a.id]);
    if (m.status === "running") return `<div class="caw-msg ag"><div class="caw-bub"><p class="co-going">${icon("cycle")}${esc(a.name)} is reading the context and thinking…</p></div></div>`;
    if (m.status !== "done") return `<div class="caw-msg ag"><div class="caw-bub"><p class="${m.status === "failed" ? "co-fail" : "faint"}">${icon(m.status === "failed" ? "alert" : "stop")}${esc(m.body)}</p></div></div>`;
    const others = c?.project_id ? K.d.agents.filter(x => x.id !== a.id && x.status !== "archived" && (x.category !== "division" || x.division_id === K.P(c.project_id)?.division_id)) : [];
    const sugg = [];
    if (t.files && c?.project_id) sugg.push(ap.file ? `<span class="co-skill">${icon("check")}Saved as file #${ap.file}</span> <button type="button" class="linkbtn" data-cawtab="files">open</button>`
      : `<button type="button" class="btn sm ghost" data-cawdo="save" data-m="${m.id}" data-kind="report">${icon("doc")}Save as report</button><button type="button" class="btn sm ghost" data-cawdo="save" data-m="${m.id}" data-kind="code">${icon("code")}Save as code draft</button>`);
    if (mt.memory) sugg.push(ap.memory ? `<span class="co-skill">${icon("bulb")}Remembered: ${esc(mt.memory)}</span>` : `<button type="button" class="btn sm ghost" data-cawdo="remember" data-m="${m.id}" title="${esc(mt.memory)}">${icon("bulb")}Remember: ${esc(mt.memory.slice(0, 60))}${mt.memory.length > 60 ? "…" : ""}</button>`);
    if (mt.task) sugg.push(ap.task ? `<span class="co-skill">${icon("list")}Task #${ap.task}</span> <button type="button" class="linkbtn" data-cotask="${ap.task}" data-goproj="1">open</button>` : `<button type="button" class="btn sm ghost" data-cawdo="task" data-m="${m.id}">${icon("list")}Make it a task: ${esc(mt.task.title)}</button>`);
    if (mt.proposal) sugg.push(ap.approval ? `<span class="co-skill">${icon("shield")}Approval #${ap.approval} waits for you</span> <button type="button" class="linkbtn" data-cotab="approvals">Approvals</button>` : `<button type="button" class="btn sm" data-cawdo="propose" data-m="${m.id}">${icon("shield")}Ask for approval: ${esc(K.d.catalog.actions[mt.proposal.type]?.label || mt.proposal.type)}</button>`);
    if (t.handoff && others.length) sugg.push(`<span class="caw-send"><label class="in"><span class="sr">Hand it to</span><select data-cawto="${m.id}">${others.map(x => `<option value="${x.id}">${esc(x.name)} · ${esc(x.title)}</option>`).join("")}</select></label><button type="button" class="btn sm ghost" data-cawdo="send" data-m="${m.id}">${icon("send")}Send</button>${(ap.sent || []).length ? `<span class="faint small">sent to ${ap.sent.map(id => esc(K.A(id)?.name || id)).join(", ")}</span>` : ""}</span>`);
    const rd = mt.read || {};
    return `<div class="caw-msg ag"><div class="caw-bub">
        <div class="md">${Agents.md(m.body)}</div>
        ${(mt.plan || []).length ? `<details class="caw-plan" open><summary class="small"><b>Plan</b></summary><ol>${mt.plan.map(s => `<li>${esc(s)}</li>`).join("")}</ol></details>` : ""}
        ${mt.proposal && !ap.approval ? `<div class="caw-prop"><p class="small"><b>${icon("shield")}Proposes: ${esc(mt.proposal.title || "")}</b> ${esc(mt.proposal.reason || "")}</p><pre class="co-pre">${esc(mt.proposal.details || "")}</pre>${mt.proposal.expected ? `<p class="faint small"><b>Expected:</b> ${esc(mt.proposal.expected)}</p>` : ""}${mt.proposal.rollback ? `<p class="faint small"><b>Rollback:</b> ${esc(mt.proposal.rollback)}</p>` : ""}</div>` : ""}
        ${(mt.dropped || []).length ? `<p class="faint small">${icon("ban")}Not offered: ${mt.dropped.map(esc).join("; ")}.</p>` : ""}
        <details class="caw-read"><summary class="faint small">What it read · ${K.tok(m.tokens)} tokens · ${ms(m.ms)}</summary><p class="small">${(rd.knowledge || []).length ? `<b>Knowledge:</b> ${rd.knowledge.map(esc).join(" · ")}` : "No knowledge."} ${rd.memory ? `· ${K.plural(rd.memory, "memory note")}` : ""} ${(rd.files || []).length ? `· <b>Files:</b> ${rd.files.map(esc).join(", ")}` : ""} ${(rd.attachments || []).length ? `· <b>Attached:</b> ${rd.attachments.map(esc).join(", ")}` : ""}</p><p class="faint small">${esc(m.model || "")}</p></details>
        ${sugg.length ? `<div class="row caw-sugg">${sugg.join("")}</div>` : ""}</div>
      <div class="caw-meta"><span class="faint small">${esc(a.name)} · ${K.when(m.ts)}</span>
        <button type="button" class="caw-rate ${m.rating === 1 ? "on" : ""}" data-cawrate="${m.rating === 1 ? 0 : 1}" data-m="${m.id}" aria-label="Helpful" aria-pressed="${m.rating === 1}">${icon("thumbup")}</button>
        <button type="button" class="caw-rate ${m.rating === -1 ? "on" : ""}" data-cawrate="${m.rating === -1 ? 0 : -1}" data-m="${m.id}" aria-label="Not helpful" aria-pressed="${m.rating === -1}">${icon("thumbdown")}</button></div></div>`;
  }

  // ---------- instructions, tasks, memory, knowledge ----------
  function instructions(w) {
    const cf = w.config;
    return `<section class="card"><form class="co-form" data-cawform="instructions">
        <label class="in"><span>Current mission</span><input type="text" name="mission" maxlength="600" value="${esc(cf.mission)}" placeholder="${esc(w.agent.about || "What it's working towards")}"></label>
        <label class="in"><span>Standing instructions</span><textarea name="instructions" rows="8" maxlength="6000" placeholder="How it should work: what to focus on, what to always check, how to report.">${esc(cf.instructions)}</textarea></label>
        <p class="faint small">They go into every call it makes, in chat and on teams. They don't widen its contract: what it may read, write and execute stays as the contract says.</p>
        <button type="submit" class="btn sm primary">Save: a new configuration version</button></form></section>
      ${versions(w)}`;
  }
  function versions(w) {
    const v = w.versions;
    return `<section class="card"><h3 class="caw-h">${icon("list")}Versions</h3>
      <details><summary class="small">Configuration (${v.config.length})</summary><ul class="co-list">${v.config.map(x => `<li><span>v${x.version} · ${esc(w.catalog.profiles[x.config.profile]?.label || "")} · ${esc(w.catalog.autonomy[x.config.autonomy]?.label || "")}${x.config.budget ? ` · ${K.tok(x.config.budget)}/month` : ""}</span><span class="faint small">${K.when(x.ts)} · ${esc(x.by_actor)}</span></li>`).join("") || `<li class="faint small">Never changed.</li>`}</ul></details>
      <details><summary class="small">Contract (${v.contract.length})</summary><ul class="co-list">${v.contract.map(x => `<li><span>v${x.version}</span><span class="faint small">${K.when(x.ts)} · ${esc(x.by_actor)}</span></li>`).join("")}</ul></details>
      <details><summary class="small">The contract as data</summary><pre class="co-pre">${esc(JSON.stringify(w.contract, null, 2))}</pre></details></section>`;
  }
  function tasks(w) {
    const G = [["Running", t => ["running", "evaluating"].includes(t.status)], ["Assigned", t => t.status === "proposed" || t.team_status === "proposed"],
               ["Blocked", t => t.status === "failed"], ["Completed", t => t.status === "done"], ["Cancelled", t => t.status === "cancelled"]];
    const rows = w.tasks;
    if (!rows.length) return `<section class="card"><p class="faint">No task yet. The team builder puts ${esc(w.agent.name)} on a team when a task needs its skills; or ask it in Chat and make its answer a task.</p></section>`;
    return G.map(([l, f]) => { const ts = rows.filter(f); return ts.length ? `<section class="card"><h3 class="caw-h">${l} <span class="faint small">${ts.length}</span></h3><ul class="co-list">${ts.map(t => {
      const [sc, sl] = K.TASK[t.status] || ["none", t.status];
      return `<li><span><button type="button" class="linkbtn" data-cotask="${t.task_id}" data-goproj="1">${esc(t.title)}</button> <span class="faint small">${projName(t.project_id)} · ${t.lead_id === w.agent.id ? "lead" : esc(t.role)}</span>${t.error ? `<br><span class="co-fail small">${esc(t.error)}</span>` : ""}</span>
        <span>${t.score != null ? K.chip(K.VERD[t.verdict] || "none", `${t.score}/100`) : ""}${K.chip(sc, sl)}</span></li>`; }).join("")}</ul></section>` : ""; }).join("");
  }
  function memory(w) {
    const a = w.agent;
    return `<section class="card"><div class="co-h"><h3 class="caw-h">${icon("bulb")}Its memory</h3><span class="faint small">Read in later conversations of the same context: notes without a project everywhere, a project's notes only there</span></div>
        ${w.memory.length ? `<ul class="co-list">${w.memory.map(x => `<li><span>${esc(x.body)}</span><span class="faint small">${projName(x.project_id)} · ${x.source === "you" ? "by you" : esc(x.source)} · ${K.when(x.created)} <button type="button" class="btn sm ghost" data-cawforget="${x.id}" aria-label="Delete">${icon("trash")}</button></span></li>`).join("")}</ul>` : `<p class="faint small">Nothing yet. ${w.config.autonomy === "managed" ? "It keeps notes from chat by itself." : "Press Remember on an answer to keep its note."}</p>`}
        ${w.config.tools.memory ? `<details class="co-add"><summary class="btn sm">${icon("plus")}Add a note</summary><form class="co-form" data-cawform="memory">
          <label class="in"><span>Note</span><textarea name="body" rows="2" maxlength="2000" required></textarea></label>
          <label class="in"><span>For</span><select name="project_id"><option value="">Every context</option>${w.contexts.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
          <button type="submit" class="btn sm primary">Add</button></form></details>` : `<p class="faint small">Its Keep memory tool is off.</p>`}</section>
      <section class="card"><h3 class="caw-h">${icon("chat")}From its team work</h3><p class="faint small">What ${esc(a.name)} reported to its leads: kept with each task.</p>
        ${w.notes.length ? `<ul class="co-list">${w.notes.map(n => `<li><span>${esc(n.payload.summary || n.type)}</span><span class="faint small"><button type="button" class="linkbtn" data-cotask="${n.task_id}" data-goproj="1">${esc(n.task)}</button> · ${K.when(n.ts)}</span></li>`).join("")}</ul>` : `<p class="faint small">No team messages yet.</p>`}</section>`;
  }
  function knowledge(w) {
    const SC = { company: "Company", division: "Division", project: "Project" };
    const by = {};
    for (const k of w.knowledge) { const key = k.scope === "project" ? `Project: ${K.P(k.project_id)?.name || k.project_id}` : k.scope === "division" ? `Division: ${K.DIV(k.owner_id)?.name || k.owner_id}` : SC[k.scope]; (by[key] = by[key] || []).push(k); }
    return `<section class="card co-tiers"><p class="small"><b>What ${esc(w.agent.name)} may read.</b> In a conversation it reads the company's knowledge, the division's and the conversation's project's: never another project's, never restricted items.${w.config.tools.knowledge ? "" : " <b>Its Read knowledge tool is off: none of it goes into its prompts.</b>"}</p>
        ${w.knowledge_hidden ? `<p class="faint small">${icon("lock")}${K.plural(w.knowledge_hidden, "item")} it can't read (other projects', restricted).</p>` : ""}</section>
      ${Object.entries(by).map(([g, ks]) => `<section class="card"><h3 class="caw-h">${icon("book")}${esc(g)} <span class="faint small">${ks.length}</span></h3><ul class="co-know">${ks.map(k => `<li><div class="co-kh"><b>${esc(k.title)}</b><span class="faint small">${k.source === "you" ? "by you" : esc(k.source || "")}</span></div>${k.body !== k.title ? `<p class="small">${esc(k.body)}</p>` : ""}</li>`).join("")}</ul></section>`).join("")
        || `<section class="card"><p class="faint">No knowledge it may read yet.</p></section>`}`;
  }

  // ---------- skills, tools, files, workflows ----------
  function skills(w) {
    const a = K.A(w.agent.id) || w.agent, sk = Object.entries(a.skills).sort((x, y) => y[1] - x[1]);
    return `<section class="card"><h3 class="caw-h">${icon("star")}Skills</h3>
        <ul class="caw-skills">${sk.map(([k, v]) => `<li><span><b>${esc(k.replace(/_/g, " "))}</b> <span class="faint small">${esc(K.d.catalog.skills[k] || "")}</span></span>
          <span class="caw-dots" aria-label="${v} of 5">${[1, 2, 3, 4, 5].map(i => `<i class="${i <= v ? "on" : ""}"></i>`).join("")}</span>
          <button type="button" class="btn sm ghost" data-cawtest="${k}" ${a.status === "available" ? "" : "disabled"}>${icon("chat")}Test</button></li>`).join("")}</ul>
        <p class="faint small">Test opens Chat with a question that exercises the skill on its work.</p></section>
      <section class="card"><h3 class="caw-h">${icon("edit")}Change skills and workload</h3>
        <form class="co-form co-contract" data-coform="contract" data-agent="${a.id}">
          <div class="co-skedit">${sk.map(([k, v]) => `<label><span>${esc(k)}</span><input type="number" name="sk_${k}" min="0" max="5" value="${v}"></label>`).join("")}
            <label><span>add</span><select name="sk_new"><option value="">a skill…</option>${Object.keys(K.d.catalog.skills).filter(k => !a.skills[k]).map(k => `<option>${k}</option>`).join("")}</select></label></div>
          <dl class="co-dl"><dt>Writes</dt><dd><input type="text" name="write" value="${esc((a.permissions.write || []).join(", "))}" maxlength="300"></dd>
            <dt>Executes</dt><dd><input type="text" name="execute" value="${esc((a.permissions.execute || []).join(", "))}" maxlength="300" placeholder="nothing"></dd>
            <dt>Teams at once</dt><dd><input type="number" name="max_load" min="1" max="10" value="${a.max_load}"></dd></dl>
          <p class="faint small">This is its contract: a change is a new contract version, kept with who made it. 0 removes a skill.</p>
          <button type="submit" class="btn sm">Save the contract</button></form></section>`;
  }
  function tools(w) {
    const cf = w.config, perm = w.contract.permissions;
    return `<section class="card"><form class="co-form" data-cawform="tools"><h3 class="caw-h">${icon("wrench")}Chat tools</h3>
        <p class="faint small">What its answers may suggest. Each suggestion is a button you press; switched off, it isn't offered and the server refuses it.</p>
        <div class="caw-toolgrid">${Object.entries(w.catalog.tools).map(([k, v]) => `<label class="co-check caw-tool"><input type="checkbox" name="tool" value="${k}" ${cf.tools[k] ? "checked" : ""}><span><b>${esc(v.label)}</b> <span class="badge muted">${esc(v.kind)}</span><br><span class="faint small">${esc(v.means)}</span></span></label>`).join("")}</div>
        <button type="submit" class="btn sm primary">Save the tools</button></form></section>
      <section class="card"><h3 class="caw-h">${icon("shield")}Contract permissions</h3>
        <dl class="co-dl"><dt>Reads</dt><dd>${(perm.read || []).map(esc).join(", ") || "nothing"}</dd><dt>Writes</dt><dd>${(perm.write || []).map(esc).join(", ") || "nothing"}</dd>
          <dt>Executes</dt><dd>${(perm.execute || []).map(esc).join(", ") || "nothing"}${(perm.execute || []).length ? ` <span class="faint small">described in its work, never run here: there's no sandbox runner</span>` : ""}</dd>
          <dt>Never</dt><dd>${Object.keys(w.contract.restrictions).map(k => `<span class="co-skill off">${esc(k.replace(/_/g, " "))}</span>`).join("")}</dd>
          <dt>Needs you for</dt><dd class="small">${Object.values(K.d.catalog.actions).map(x => esc(x.label)).join(" · ")}</dd></dl>
        <button type="button" class="btn sm ghost" data-cawtab="skills">${icon("edit")}Change the contract</button></section>`;
  }
  function files(w) {
    if (!w.files.length) return `<section class="card"><p class="faint">No files yet. Deliverables it writes as a team lead, and answers you save from Chat, land here.</p></section>`;
    const off = K.d.company.settings.actions_off || [];
    return `<section class="card"><div class="co-arts">${w.files.map(f => { const o = openFile[f.id], e = f.eval;
      return `<div class="caw-file"><div class="co-art-row"><div><b>${icon(f.kind === "code" ? "code" : "doc")}${esc(f.title)}</b> <span class="faint small">${projName(f.project_id)} · ${K.when(f.created)} · ${K.short(f.sha)} · ${f.task_id ? "team deliverable" : "from chat"}</span>${f.status === "released" ? K.chip("ok", "Released", "check") : ""}
          <p class="small faint">${esc(f.summary || "")}</p></div>
        <div class="co-art-side">${e ? K.chip(K.VERD[e.verdict], `${e.score}/100 · ${esc(e.verdict)}`) : K.chip("none", "not evaluated")}
          <button type="button" class="btn sm ghost" data-cawfile="${f.id}">${icon(o ? "up" : "down")}${o ? "Hide" : "Read"}</button></div></div>
        ${o ? `<div class="md co-md">${Agents.md(f.body || "")}</div>
          <div class="row co-act">${f.task_id ? `<button type="button" class="btn sm ghost" data-cotask="${f.task_id}" data-goproj="1">${icon("folder")}Open in the project</button>` : ""}
          ${f.status !== "released" && K.d.artifacts.some(x => x.id === f.id) ? `<label class="in"><span class="sr">Action</span><select data-coreqsel="${f.id}">${Object.entries(K.d.catalog.actions).filter(([k]) => !["knowledge_promotion", "permission_change"].includes(k) && !off.includes(k)).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("")}</select></label>
            <button type="button" class="btn sm" data-coreq="${f.id}">${icon("shield")}Ask for approval</button>` : ""}</div>` : ""}</div>`; }).join("")}</div></section>`;
  }
  function workflows(w) {
    const teams = w.tasks.filter(t => t.team_status !== "proposed");
    return `<section class="card"><h3 class="caw-h">${icon("route")}Teams it worked in</h3><p class="faint small">A task's team: members report in stage order (research, design, engineering, testing, review), the lead writes the deliverable, an independent evaluator scores it.</p>
      ${teams.length ? `<div class="co-tablewrap"><table class="co-table"><thead><tr><th>Task</th><th>Project</th><th>Team</th><th>Its role</th><th>Team status</th><th>When</th></tr></thead><tbody>
        ${teams.map(t => `<tr><td><button type="button" class="linkbtn" data-cotask="${t.task_id}" data-goproj="1">${esc(t.title)}</button></td><td class="small">${projName(t.project_id)}</td>
          <td class="small">${esc({ dynamic: "Dynamic team", taskforce: "Task force", permanent: "Permanent team" }[t.team_kind] || t.team_kind)}</td><td class="small">${t.lead_id === w.agent.id ? `${icon("star")}lead` : esc(t.role)}</td>
          <td>${K.chip(t.team_status === "active" ? "run" : "none", esc(t.team_status))}</td><td class="num faint small">${K.when(t.activated)}</td></tr>`).join("")}</tbody></table></div>` : `<p class="faint small">No team yet.</p>`}
      ${w.evaluated.length ? `<h3 class="caw-h">${icon("check")}Work it evaluated</h3><ul class="co-list">${w.evaluated.map(e => `<li><button type="button" class="linkbtn" data-cotask="${e.task_id}" data-goproj="1">${esc(e.title)}</button>${K.chip(K.VERD[e.verdict] || "none", `${e.score}/100`)}</li>`).join("")}</ul>` : ""}</section>`;
  }

  // ---------- performance, activity, settings ----------
  function performance(w) {
    const p = w.performance, top = Math.max(1, ...p.tokens.weeks.map(x => x.tokens));
    return `<div class="stats caw-perf">${kpi("Tasks", p.tasks, `${p.done} done · ${p.failed} failed`)}${kpi("Led", p.led, "deliverables written")}
        ${kpi("Average score", p.avg_score ?? "–", "by the independent evaluator")}${kpi("Pass rate", pct(p.pass_rate), "deliverables passed")}
        ${kpi("Chat answers", p.chat.answers, `${p.chat.failed} failed`)}${kpi("Answer time", ms(p.chat.avg_ms), "average")}
        ${kpi("Ratings", `${p.chat.up}/${p.chat.down}`, "helpful / not")}${kpi("Tokens this month", K.tok(p.tokens.month), p.tokens.budget ? `of ${K.tok(p.tokens.budget)}` : "no cap")}</div>
      <div class="co-two">
        <section class="card"><h3 class="caw-h">${icon("coins")}Tokens per week</h3><div class="caw-bars">${p.tokens.weeks.map(x => `<div title="${K.tok(x.tokens)} tokens"><i style="height:${Math.round(100 * x.tokens / top)}%"></i><span class="faint small">${new Date(x.from * 1000 + 6 * 864e5).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span></div>`).join("")}</div>
          ${p.tokens.by_model.length ? `<ul class="co-list">${p.tokens.by_model.map(m => `<li><code class="small">${esc(m.model)}</code><span class="faint small num">${K.tok(m.n)} · ${K.plural(m.calls, "call")}</span></li>`).join("")}</ul>` : ""}
          <p class="faint small">Tokens, not money: AXoR doesn't price models.</p></section>
        <section class="card"><h3 class="caw-h">${icon("chart")}Scores</h3>${p.scores.length ? `<ul class="caw-scores">${p.scores.map(s => `<li><span class="small">${esc(s.title)}</span><span class="co-bar"><i style="width:${s.score}%" class="${s.verdict === "fail" ? "hot" : ""}"></i></span><span class="num small">${s.score}</span></li>`).join("")}</ul>` : `<p class="faint small">No scored work yet.</p>`}
          ${p.evaluator ? `<p class="small"><b>As evaluator:</b> ${K.plural(p.evaluator.given, "score")} given${p.evaluator.avg != null ? `, average ${p.evaluator.avg}` : ""}.</p>` : ""}</section></div>`;
  }
  const actRow = r => `<li><span>${K.chip(r.source === "audit" ? "none" : ACTK[r.kind] || "none", esc(r.source === "audit" ? "audit" : r.kind))} ${r.source === "audit" ? `${K.actor(r)} ${esc(K.act(r))}` : esc(r.summary)}</span><span class="faint small num">${r.tokens ? `${K.tok(r.tokens)} · ` : ""}${r.ms != null ? `${ms(r.ms)} · ` : ""}${K.when(r.ts)}</span></li>`;
  function activity(w) {
    return `<section class="card"><div class="co-h"><h3 class="caw-h">${icon("clock")}Activity</h3><span class="faint small">Its answers, what was applied, errors, configuration and status changes, and its audit entries</span></div>
      <ul class="co-list">${w.activity.map(r => actRow(r) + (r.source !== "audit" && (r.meta?.dropped || []).length ? `<li class="faint small">Not offered: ${r.meta.dropped.map(esc).join("; ")}</li>` : "")).join("") || `<li class="faint">Nothing yet.</li>`}</ul></section>`;
  }
  function settings(w) {
    const cf = w.config, a = w.agent, cat = w.catalog;
    const budgets = [...new Set([...cat.budgets, cf.budget])].sort((x, y) => x - y);
    const ctxIds = new Set(w.assignments.map(x => x.project_id));
    return `<section class="card"><form class="co-form" data-cawform="settings">
        <fieldset class="co-policy"><legend>Model profile</legend><div class="caw-opts">${Object.entries(cat.profiles).map(([k, v]) => `<label class="caw-opt"><input type="radio" name="profile" value="${k}" ${cf.profile === k ? "checked" : ""}><span><b>${esc(v.label)}</b><span class="faint small">${esc(v.means)}</span></span></label>`).join("")}</div>
          <label class="in"><span>Its own model (optional)</span><input type="text" name="model" maxlength="120" value="${esc(cf.model)}" placeholder="the company's model (${esc(K.d.company.model_id || "none connected")})"><small class="faint">A provider:model id from Agents → Models. Now: ${cf.model_id ? `<code>${esc(cf.model_id)}</code>, effort ${esc(cf.effort)}` : `<span class="co-fail">${esc(cf.model_error || "")}</span>`}</small></label></fieldset>
        <fieldset class="co-policy"><legend>Autonomy</legend>${Object.entries(cat.autonomy).map(([k, v]) => `<label class="co-check"><input type="radio" name="autonomy" value="${k}" ${cf.autonomy === k ? "checked" : ""} ${v.available ? "" : "disabled"}><span><b>${esc(v.label)}</b>${v.available ? "" : ` <span class="badge muted">not available</span>`}<br><span class="faint small">${esc(v.means)}</span></span></label>`).join("")}
          <p class="faint small">${icon("shield")}Production and important outside actions always need your approval, whatever the autonomy.</p></fieldset>
        <label class="in"><span>Monthly token budget</span><select name="budget">${budgets.map(b => `<option value="${b}" ${b === cf.budget ? "selected" : ""}>${b ? `${K.tok(b)} tokens` : "No cap"}</option>`).join("")}</select>
          <small class="faint">${K.tok(cf.month_spent)} used this month, in chat and on teams. At the cap, its calls stop until next month or until you raise it.</small></label>
        <button type="submit" class="btn sm primary">Save the settings</button></form></section>
      <section class="card"><h3 class="caw-h">${icon("folder")}Project assignments</h3>
        <p class="faint small">${a.category === "division" ? `It works on its division's projects. Assign it to another project to let it work there: in chat that project's knowledge becomes readable to it, and it can receive hand-offs about it.` : "It works across the company already; an assignment names its role on a project."}</p>
        ${w.assignments.length ? `<ul class="co-list">${w.assignments.map(x => `<li><span>${projName(x.project_id)}${x.role ? ` <span class="faint small">· ${esc(x.role)}</span>` : ""}</span><button type="button" class="btn sm ghost" data-cawunassign="${x.project_id}">${icon("close")}Unassign</button></li>`).join("")}</ul>` : ""}
        <form class="co-form caw-assign" data-cawform="assign"><div class="row"><label class="in"><span>Project</span><select name="project_id">${K.d.projects.filter(p => p.status !== "archived" && !ctxIds.has(p.id)).map(p => `<option value="${p.id}">${esc(p.name)} · ${esc(K.DIV(p.division_id)?.name || "")}</option>`).join("")}</select></label>
          <label class="in"><span>Role there</span><input type="text" name="role" maxlength="60" placeholder="e.g. security review"></label></div><button type="submit" class="btn sm">${icon("plus")}Assign</button></form></section>
      ${versions(w)}`;
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    const v = $("#view-company");
    const go = async (btn, path, opts, msg) => { const r = await K.busy(btn, () => api(`${C}/agents/${sel}${path}`, opts)); if (r) { if (msg) Auth.toast(msg); take(r); } return r; };
    v.addEventListener("click", async e => {
      const t = e.target;
      const op = t.closest("[data-cawopen]"); if (op) { open(+op.dataset.cawopen); return K.render(); }
      if (!K) return;
      const b = t.closest("[data-caw]");
      if (b?.dataset.caw === "back") { sel = null; clearTimeout(poll); dirAt = 0; fetchDir(); return K.render(); }
      if (b?.dataset.caw === "compare") { compare = !compare; return K.render(); }
      const g = t.closest("[data-cawg]"); if (g) { fGroup = g.dataset.cawg; return K.render(); }
      const tb = t.closest("[data-cawtab]"); if (tb && sel) { wtab = tb.dataset.cawtab; return K.render(); }
      if (!sel) return;
      const cv = t.closest("[data-cawconv]"); if (cv) { conv[sel] = +cv.dataset.cawconv; return fetchWs(sel); }
      const lf = t.closest("[data-cawlife]");
      if (lf) { const what = lf.dataset.cawlife;
        if (what === "clone") { const r = await K.busy(lf, () => api(`${C}/agents/${sel}/clone`, { method: "POST", body: {} })); if (r) { Auth.toast("Cloned: here's the copy"); K.take(r); open(r.agent_id); } return; }
        if (what === "archive") return UI.confirm({ title: `Archive ${W().agent.name}?`, body: "It leaves the directory and joins no team. Its history, files and memory stay; Restore brings it back.", ok: "Archive", icon: "inbox",
          run: async () => { take(await api(`${C}/agents/${sel}/archive`, { method: "POST" })); K.load?.(); Auth.toast("Archived"); } }).catch(K.err);
        await go(lf, `/${what}`, { method: "POST" }, what === "pause" ? "Paused: it joins no new team and can't be messaged" : "Available again"); return K.load?.(); }
      const st = t.closest("[data-cawstop]"); if (st) return go(st, `/chat/${st.dataset.cawstop}/stop`, { method: "POST" }, "Stopped");
      const dd = t.closest("[data-cawdo]");
      if (dd) { const what = dd.dataset.cawdo, mid = dd.dataset.m;
        const body = what === "save" ? { kind: dd.dataset.kind, title: "" } : what === "send" ? { agent_id: +v.querySelector(`[data-cawto="${mid}"]`)?.value } : undefined;
        const r = await go(dd, `/chat/${mid}/${what}`, { method: "POST", body }, { save: "Saved in the project's files", remember: "Remembered", task: "Task added: propose a team for it in Projects", propose: "Asked: it waits in Approvals", send: "Handed over" }[what]);
        if (r && ["save", "task", "propose"].includes(what)) K.load?.(); return; }
      const rt = t.closest("[data-cawrate]"); if (rt) return go(rt, `/chat/${rt.dataset.m}/rate`, { method: "POST", body: { score: +rt.dataset.cawrate } });
      const fg = t.closest("[data-cawforget]");
      if (fg) return UI.confirm({ title: "Delete this memory note?", body: "It won't be in its prompts any more. Its activity keeps that it existed.", ok: "Delete",
        run: async () => take(await api(`${C}/agents/${sel}/memory/${fg.dataset.cawforget}`, { method: "DELETE" })) }).catch(K.err);
      const un = t.closest("[data-cawunassign]"); if (un) return go(un, `/assignments/${un.dataset.cawunassign}`, { method: "DELETE" }, "Unassigned");
      const fl = t.closest("[data-cawfile]"); if (fl) { openFile[fl.dataset.cawfile] = !openFile[fl.dataset.cawfile]; return K.render(); }
      const ts = t.closest("[data-cawtest]");
      if (ts) { const sk = ts.dataset.cawtest; draft[sel] = `Show me how you'd use your ${sk.replace(/_/g, " ")} skill on your current work: what you'd look at, what you'd conclude, and what you'd need measured.`; conv[sel] = 0; wtab = "chat"; return fetchWs(sel); }
      const ur = t.closest("[data-cawunref]"); if (ur) { refs[sel] = (refs[sel] || []).filter(id => id !== +ur.dataset.cawunref); return K.render(); }
      const ua = t.closest("[data-cawunatt]"); if (ua) { (atts[sel] || []).splice(+ua.dataset.cawunatt, 1); return K.render(); }
    });
    v.addEventListener("keydown", e => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && e.target.matches?.("[data-cawdraft]")) { e.preventDefault(); e.target.form?.requestSubmit(); }
    });
    v.addEventListener("input", e => {
      const t = e.target;
      if (t.matches("[data-cawdraft]") && sel) draft[sel] = t.value;
      if (t.matches("[data-cawq]")) { q = t.value; const pos = t.selectionStart; K.render(); const n = v.querySelector("[data-cawq]"); if (n) { n.focus(); n.setSelectionRange(pos, pos); } }
    });
    v.addEventListener("change", async e => {
      const t = e.target;
      if (t.matches("[data-cawf]")) { const k = t.dataset.cawf, val = t.value; if (k === "status") fStatus = val; if (k === "skill") fSkill = val; if (k === "project") fProject = val; if (k === "profile") fProfile = val; if (k === "sort") sort = val; t.blur(); return K.render(); }
      if (t.matches("[data-cawctx]")) { ctxNew[sel] = +t.value; t.blur(); return K.render(); }
      if (t.matches("[data-cawref]") && t.value) { (refs[sel] = refs[sel] || []).push(+t.value); t.blur(); return K.render(); }
      if (t.matches("[data-cawattach]")) {
        const f = t.files?.[0]; t.value = ""; if (!f) return;
        if ((atts[sel] || []).length >= 3) return Auth.toast("Three attachments at most");
        if (f.size > 200000) return Auth.toast("Attach a text file under 200 kB");
        const text = await f.text();
        if (/\u0000/.test(text.slice(0, 2000))) return Auth.toast("That isn't a text file");
        (atts[sel] = atts[sel] || []).push({ name: f.name.slice(0, 120), text: text.slice(0, 40000) });
        if (text.length > 40000) Auth.toast("Attached its first 40,000 characters");
        return K.render();
      }
    });
    v.addEventListener("submit", async e => {
      const fm = e.target.closest("[data-cawform]"); if (!fm || !sel) return;
      e.preventDefault();
      const kind = fm.dataset.cawform, btn = e.submitter || fm.querySelector("[type=submit]"), F = new FormData(fm), w = W();
      const cfg = (body, msg) => go(btn, "/configuration", { method: "PATCH", body }, msg);
      if (kind === "chat") {
        const text = String(F.get("text") || "").trim(); if (!text) return;
        const cid = conv[sel] || null, c = w.conversations.find(x => x.id === cid);
        const pid = c ? null : (ctxNew[sel] ?? w.contexts[0]?.id ?? 0) || null;
        const body = { text, conversation_id: cid, project_id: pid, files: refs[sel] || [], attachments: atts[sel] || [] };
        document.activeElement?.blur();
        const r = await go(btn, "/chat", { method: "POST", body });
        if (r) { draft[sel] = ""; refs[sel] = []; atts[sel] = []; conv[sel] = r.conversation_id; take(r); }
      }
      if (kind === "instructions") { document.activeElement?.blur(); cfg({ mission: F.get("mission") || "", instructions: F.get("instructions") || "" }, "Saved: a new configuration version"); }
      if (kind === "tools") { const on = F.getAll("tool"); document.activeElement?.blur(); cfg({ tools: Object.fromEntries(Object.keys(w.catalog.tools).map(k => [k, on.includes(k)])) }, "Tools saved"); }
      if (kind === "settings") { document.activeElement?.blur(); cfg({ profile: F.get("profile"), model: F.get("model") || "", autonomy: F.get("autonomy"), budget: +F.get("budget") }, "Settings saved"); }
      if (kind === "memory") { document.activeElement?.blur(); go(btn, "/memory", { method: "POST", body: { body: F.get("body"), project_id: F.get("project_id") ? +F.get("project_id") : null } }, "Noted"); }
      if (kind === "assign") { document.activeElement?.blur(); if (!F.get("project_id")) return Auth.toast("It works on every project already");
        const r = await go(btn, "/assignments", { method: "POST", body: { project_id: +F.get("project_id"), role: F.get("role") || "" } }, "Assigned"); if (r) dirAt = 0; }
    });
  }

  return { tab, open, refresh };
})();
