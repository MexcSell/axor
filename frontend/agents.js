/* Agents page: one place for every agent. Its rail has two sides:
   - the operations side (agent-studio.js draws it in #aos): Directory of every agent in every system, each agent's profile
     (overview, instructions, skills, tools, memory, tasks, evaluations, versions, activity), Operations, Live runs, Connected, Ecosystem;
   - the hub side (this file, in #hub-main): New agent (from a description or a template), the editor, chat, the Shared catalog
     (agents others published), the skill hub, settings.
   The Directory replaced "My agents" (its "Only mine" filter) and the old Agent directory became the Shared catalog.
   Built-in agents (user administration, DevOps, Functions, Apps, Cluster, DNS) propose changes that need approval; custom agents only read subnet data.
   The Assistant (built in, for everyone) answers about any page; it and the others also open beside every page in the Assist panel (assist.js).
   Every chat runs on the model picked in the composer (Claude, OpenAI, OpenRouter, a local server or Terminal, the server's Claude Code CLI). */
const Agents = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("hub." + k)); localStorage.setItem("hub." + k, JSON.stringify(v)); } catch { return null; } };
  let hub = null, builtins = [], lists = { mine: [], from_directory: [], shared: [], directory: [] }, recents = [], skills = null;
  let page = "home", current = null, conv = null, wired = false, busy = false, busySince = 0, busyTimer = null;
  let homeCat = "All", draftBusy = false, editing = null;
  let mode = pref("mode") === "hub" ? "hub" : "ops", wantSec = null;  // which side of the page shows: ops = agent-studio.js, hub = this file
  const mine = { tab: "mine", q: "", status: "all", sort: pref("sort") || "newest", view: pref("view") || "list" };
  const dir = { creator: "all", status: "all" };

  const TOOL_LABEL = {
    security_overview: "Checked the security overview", list_users: "Listed users", get_user: "Looked up a user",
    search_audit_log: "Searched the audit log", propose_user_action: "Proposed an account change",
    propose_setting_change: "Proposed a setting change",
    market_overview: "Checked the market overview", search_subnets: "Searched subnets", get_subnet: "Looked up a subnet",
    recommend_subnets: "Ran recommendations", mining_plan: "Read the mining plan",
    study_progress: "Checked your study progress", mark_topic: "Updated your study path", my_subnets: "Checked your workspace",
    // operations agents (ops_agents.py)
    devops_overview: "Checked the pipelines", devops_run: "Read a run", devops_logs: "Read app logs",
    source_overview: "Checked the repositories", source_activity: "Read repository activity",
    propose_pipeline_run: "Proposed a run", propose_rollback: "Proposed a rollback", propose_run_cancel: "Proposed cancelling a run",
    propose_app_action: "Proposed an app action",
    list_functions: "Listed functions", get_function: "Read a function", function_logs: "Read function logs", function_stats: "Checked call statistics",
    propose_function_code: "Proposed a code change", propose_function_create: "Proposed a new function", propose_function_call: "Proposed a test call",
    propose_function_action: "Proposed a function action", propose_function_rollback: "Proposed a rollback",
    list_apps: "Listed apps", get_app: "Read an app", app_logs: "Read app logs", propose_app_deploy: "Proposed a deploy",
    propose_app_rollback: "Proposed a rollback",
    cluster_overview: "Checked the cluster", get_deployment: "Read a deployment", pod_logs: "Read pod logs", server_resources: "Checked server resources",
    propose_deployment_restart: "Proposed a restart", propose_deployment_scale: "Proposed scaling", propose_pod_recycle: "Proposed recycling a pod",
    dns_overview: "Checked the zones", get_zone: "Read a zone", dns_lookup: "Looked a name up", check_delegation: "Checked delegation",
    propose_record_add: "Proposed a new record", propose_record_change: "Proposed a record change", propose_record_delete: "Proposed removing a record",
  };
  const STATUS = {
    pending: ["Waiting for you", "caution"], approved: ["Approved · done", "clear"], rejected: ["Rejected", "new"],
    failed: ["Failed", "avoid"], expired: ["Expired", "new"],
  };

  // Small, safe markdown: escape first, then ``` code blocks, headings, **bold**, `code`, [links](https://…), bullet and
  // numbered lists, quotes, paragraphs. Subnets named like SN19 become links that open the subnet's details.
  const snLink = (m, n) => S.data?.subnets?.some(r => r.netuid === +n) ? `<button type="button" class="snlink" data-open="${n}" title="Open SN${n}">${m}</button>` : m;
  function md(text) {
    return String(text || "").split(/```([\w+#.-]*)[^\n]*\n?([\s\S]*?)(?:```|$)/g).map((x, i, a) => i % 3 === 0 ? mdText(x)
      : i % 3 === 2 ? `<pre data-lang="${esc(a[i - 1])}"><code>${esc(x.replace(/\n$/, ""))}</code></pre>` : "").join("");
  }
  function mdText(text) {
    const inline = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>").replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, `<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>`)
      .replace(/\bSN ?(\d{1,3})\b/g, snLink);
    const out = []; let list = null;
    for (const line of text.split("\n")) {
      const q = line.match(/^\s*>\s?(.*)/);
      if (q) { list = null; out.push(`<blockquote>${inline(q[1])}</blockquote>`); continue; }
      const m = line.match(/^\s*([-*]|\d+\.)\s+(.*)/);
      if (m) {
        const tag = /\d/.test(m[1]) ? "ol" : "ul";
        if (!list || list.tag !== tag) { list = { tag, items: [] }; out.push(list); }
        list.items.push(inline(m[2])); continue;
      }
      list = null;
      const h = line.match(/^(#{1,3})\s+(.*)/);
      if (h) out.push(`<h${h[1].length + 3}>${inline(h[2])}</h${h[1].length + 3}>`);
      else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    }
    return out.map(x => typeof x === "string" ? x : `<${x.tag}>${x.items.map(li => `<li>${li}</li>`).join("")}</${x.tag}>`).join("");
  }
  function describe(input) {
    const parts = Object.entries(input || {}).filter(([k, v]) => k !== "reason" && k !== "code" && v !== "" && v != null && !(Array.isArray(v) && !v.length))
      .map(([k, v]) => `${k}: ${String(v).length > 60 ? String(v).slice(0, 57) + "…" : v}`);
    return parts.length ? ` (${esc(parts.join(", "))})` : "";
  }
  const av = agentAvatar;  // faces.js: a portrait for agents, the icon tile for everything else
  const base = a => a.builtin ? `/api/agents/${a.id}` : `/api/agents/custom/${a.id}`;
  const fmtTokens = n => !n ? "–" : n < 1000 ? `${n}` : n < 1e6 ? `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k` : `${(n / 1e6).toFixed(1)}M`;
  const allAgents = () => [...lists.mine, ...lists.shared, ...lists.from_directory, ...lists.directory];
  const findAgent = id => builtins.find(b => b.id === id) || allAgents().find(a => a.id === +id);
  const skillName = id => [...(skills?.builtin || []), ...(skills?.custom || [])].find(s => s.id === id)?.name || id;

  async function open() {
    wire();
    if (mode === "ops" && !deepLink && !wantSettings) showOps(wantSec);
    wantSec = null;
    try { hub = await api("/api/agents/hub"); }
    catch (e) { $("#hub-main").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    // the Assistant for everyone; admins also get user admin and the operations agents
    builtins = (await api("/api/agents").catch(() => [])).map(a => ({ ...a, builtin: true, owner: "AXoR", status: "live" }));
    $("#hub-settings").hidden = !hub.is_admin;
    await Promise.all([loadLists(), loadRecents(), loadSkills(), Chat.loadModels()]);
    if (wantSettings && hub.is_admin) { wantSettings = false; return settings(); }
    if (deepLink) { const a = findAgent(deepLink), cid = deepConv; deepLink = deepConv = null; if (a) return startChat(a, cid); Auth.toast("That agent isn't available to you"); if (mode === "ops") return showOps(); }
    if (mode === "ops") return;
    if (page === "chat" && current) { current = findAgent(current.id) || current; showHub(); renderChatShell(); render(); }
    else go(page === "editor" || page === "mine" ? "home" : page);
  }
  async function loadLists() { lists = await api("/api/agents/custom").catch(() => lists); }
  async function loadSkills() { skills = await api("/api/agents/skills").catch(() => skills || { builtin: [], custom: [] }); }
  async function loadRecents() {
    recents = await api("/api/agents/recents").catch(() => []);
    $("#hub-recents").innerHTML = recents.map(r => `<button type="button" class="hub-recent" data-recent="${esc(String(r.agent_id))}" title="${esc(r.title)}">
        ${av(r, "sm")}<span><b>${esc(r.name)}</b><small>${esc(r.role || "")}</small></span></button>`).join("")
      || `<p class="faint hub-none">Chats you start show up here.</p>`;
  }

  function showHub() {
    if (mode !== "hub") { mode = "hub"; pref("mode", mode); }
    $("#aos").hidden = true; $("#hub-main").hidden = false;
    Studio.stop();
    $$("#view-agents [data-ops-sec]").forEach(b => b.setAttribute("aria-current", "false"));
    $("#hub-settings").setAttribute("aria-current", "false");
  }
  function showOps(sec) {
    if (mode !== "ops") { mode = "ops"; pref("mode", mode); }
    const was = !$("#aos").hidden;
    $("#hub-main").hidden = true; $("#aos").hidden = false;
    $$("#view-agents [data-hub]").forEach(b => b.setAttribute("aria-current", "false"));
    $("#hub-settings").setAttribute("aria-current", "false");
    if (was && sec) Studio.section(sec); else Studio.open(sec);
  }
  function go(p) {
    if (p === "mine") return showOps("directory");  // "My agents" is the Directory now (Only mine)
    if (p === "settings") return hub?.is_admin ? settings() : go("home");  // a page in the right pane, admins only
    showHub();
    page = p;
    $$("#view-agents .hub-side [data-hub]").forEach(b => b.setAttribute("aria-current", b.dataset.hub === p ? "page" : "false"));
    if (p === "home") renderHome();
    if (p === "mine") renderMine();
    if (p === "directory") renderDirectory();
    if (p === "tools") { if (typeof ToolsMcp !== "undefined") ToolsMcp.page($("#hub-main")); else $("#hub-main").innerHTML = `<div class="empty">Tools &amp; MCP isn't installed on this server.</div>`; }  // mcp.js
  }

  // ---------- home: create from a description or a template ----------
  function renderHome() {
    const cats = ["All", ...(builtins.length ? ["Built-in"] : []), ...hub.categories];
    // built-in agents: the Assistant, and for admins user admin, DevOps, Functions, Apps, Cluster, DNS; ready to chat, nothing to create
    const tops = builtins.length && (homeCat === "All" || homeCat === "Built-in") ? `<h3 class="hub-sec">${icon("shield")}Built-in agents
        <small class="faint">${hub.is_admin ? "They read AXoR's own services and propose changes you approve." : "Ready to chat on any page: open Assist in the top bar."}</small></h3>
      <div class="agent-grid">${builtins.map(a => card(a, `data-detail="${esc(a.id)}"`, a.unavailable ? `<span class="badge new" title="${esc(a.unavailable)}">Not set up</span>` : "")).join("")}</div>` : "";
    // "All" keeps to single agents: the project and study teams' members are made as a team from their own category
    const TEAMS = ["Project team", "Study"];
    const temps = hub.templates.filter(t => homeCat === "All" ? !TEAMS.includes(t.category) : t.category === homeCat);
    const teamNote = homeCat === "All" ? TEAMS.map(c => [c, hub.templates.filter(t => t.category === c).length]).filter(([, n]) => n) : [];
    const name = Auth.me()?.username;
    $("#hub-main").innerHTML = `
      <div class="hub-hero">
        <h1>Meet your <span class="grad">agents</span></h1>
        <p class="muted">${name ? `Hey ${esc(name)}, pick` : "Pick"} a pre-built agent or build one with just a simple description.</p>
        <form class="describe" id="describe">
          <textarea name="d" rows="3" maxlength="2000" placeholder="Describe what your agent should do, e.g. “Every week, find subnets I can mine with one RTX 4090 and under $300/month, and flag anything risky.”"></textarea>
          <div class="describe-foot">
            <button type="button" class="btn ghost sm" data-blank>${icon("plus")}Start from blank</button>
            <span class="describe-model">${Chat.modelButton()}</span>
            <button type="submit" class="btn primary icon-only" aria-label="Create agent" ${hub.configured ? "" : "disabled title=\"Connect a model in Models first\""}>${icon("up")}</button>
          </div>
          <p class="err" role="alert"></p>
        </form>
        ${hub.configured ? "" : `<p class="faint">${hub.is_admin ? `Describing an agent needs a model: <button type="button" class="linkbtn" data-settings>connect Claude, OpenAI, OpenRouter, a local server or Terminal</button>. You can still start from a template or a blank agent.` : "Describing an agent needs a model, which an administrator can connect."}</p>`}
      </div>
      <div class="chips hub-cats" role="group" aria-label="Categories">${cats.map(c => `<button type="button" class="chip" data-cat="${esc(c)}" aria-pressed="${c === homeCat}">${esc(c)}</button>`).join("")}</div>
      ${homeCat === "Project team" ? `<div class="card team-banner"><div><b>${icon("users")}Build on a subnet with a whole team</b>
        <p class="muted small">Seven senior engineers, one per stage, handing work over in order: plan, clone the sources, simulate locally, measure, study the competition, improve the miner, build practice tasks. They read your Source hub repos and CI (read-only). In your workspace, each one chats per subnet.</p></div>
        <button type="button" class="btn primary" data-team>${icon("plus")}Create project team</button></div>` : ""}
      ${homeCat === "Study" ? `<div class="card team-banner"><div><b>${icon("book")}Learn with a whole study team</b>
        <p class="muted small">Six tutors for the Study tab: a mentor and a tutor for becoming an AI engineer, an interview coach who runs mock interviews in English, and a conversation partner, a writing coach and a vocabulary and pronunciation coach for English at C1 and beyond. They see your progress and tick topics you've shown you know.</p></div>
        <button type="button" class="btn primary" data-study-team>${icon("plus")}Create study team</button></div>` : ""}
      ${tops}${tops && temps.length ? `<h3 class="hub-sec">${icon("bot")}Templates</h3>` : ""}
      <div class="agent-grid">${temps.map(t => card({ ...t, owner: "Template" }, `data-template="${t.id}"`, `<span class="tag">${esc(t.category)}</span>`)).join("")}</div>
      ${teamNote.length ? `<p class="faint hub-teamnote">Whole teams: ${teamNote.map(([c, n]) => `<button type="button" class="linkbtn" data-cat="${esc(c)}">${esc(c)} (${n} agents)</button>`).join(" · ")}. Every agent's work, runs and versions: <button type="button" class="linkbtn" data-ops-sec="directory">the Directory</button>.</p>` : ""}`;
    const ta = $("#describe textarea");
    ta.addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $("#describe").requestSubmit(); } });
    $("#describe").onsubmit = async e => {
      e.preventDefault();
      if (draftBusy) return;
      const text = ta.value.trim(), err = $("#describe .err"), btn = $("#describe button[type=submit]");
      if (text.length < 10) { err.textContent = "Describe what the agent should do in a sentence or two."; return; }
      draftBusy = true; err.textContent = ""; btn.disabled = true; btn.classList.add("loading");
      $("#describe").classList.add("drafting");
      err.innerHTML = Loading.line("Designing your agent…");
      try { const d = await api("/api/agents/custom/draft", { method: "POST", body: { description: text, model: Chat.chosen() } }); editor(null, d, true); }
      catch (x) { err.textContent = x.message; }
      finally { draftBusy = false; btn.disabled = false; btn.classList.remove("loading"); $("#describe")?.classList.remove("drafting"); }
    };
  }

  function card(a, attrs, extra = "") {
    return `<button type="button" class="agent-tile" ${attrs}>
      <div class="tile-head c-${esc(a.color || "blue")}">${av(a, "lg")}<div><span class="tile-name">${esc(a.name)}</span><b>${esc(a.role || "Agent")}</b></div></div>
      <p>${esc(a.description || "No description yet.")}</p>
      <div class="tile-foot"><span class="faint">${icon(a.builtin ? "shield" : "users")}${a.builtin ? "Built in to AXoR" : a.owner === "Template" ? "Template" : `Created by ${esc(a.owner)}`}</span>
        ${extra}${a.status === "paused" ? `<span class="badge new">Paused</span>` : ""}</div>
    </button>`;
  }

  // ---------- my agents ----------
  function renderMine() {
    const tabs = [["mine", "Created by me"], ["from_directory", "From directory"], ["shared", "Shared with me"]];
    $("#hub-main").innerHTML = `
      <div class="hub-top"><h1 class="page">My agents</h1>
        <div class="row"><label class="search sm">${icon("search")}<input id="mine-q" type="search" placeholder="Search agents…" value="${esc(mine.q)}"></label>
        <button type="button" class="btn ghost" data-skills>${icon("zap")}Skill hub</button>
        <button type="button" class="btn primary" data-new>${icon("plus")}New agent</button></div></div>
      <div class="hub-tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${mine.tab === k}">${l} / ${lists[k].length}</button>`).join("")}</div>
      <div class="toolbar hub-filters">
        <label class="faint">Filter by:</label>
        <select id="mine-status" aria-label="Status"><option value="all">Any status</option><option value="live">Live</option><option value="paused">Paused</option></select>
        <span class="spacer"></span>
        <select id="mine-sort" aria-label="Sort"><option value="newest">Newest</option><option value="activity">Last activity</option><option value="name">Name</option></select>
        <div class="seg" id="mine-view"><button type="button" data-v="list" aria-label="List view" title="List view">${icon("menu")}</button><button type="button" data-v="grid" aria-label="Grid view" title="Grid view">${icon("grid")}</button></div>
      </div>
      <div id="mine-body"></div>`;
    $("#mine-status").value = mine.status; $("#mine-sort").value = mine.sort;
    $$("#mine-view button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === mine.view));
    $("#mine-q").oninput = e => { mine.q = e.target.value; renderMineBody(); };
    $("#mine-status").onchange = e => { mine.status = e.target.value; renderMineBody(); };
    $("#mine-sort").onchange = e => { mine.sort = e.target.value; pref("sort", mine.sort); renderMineBody(); };
    $("#mine-view").onclick = e => { const v = e.target.closest("[data-v]")?.dataset.v; if (v) { mine.view = v; pref("view", v); renderMine(); } };
    renderMineBody();
  }
  function renderMineBody() {
    const q = mine.q.trim().toLowerCase();
    let rows = lists[mine.tab].filter(a => (mine.status === "all" || a.status === mine.status) && (!q || `${a.name} ${a.role} ${a.description}`.toLowerCase().includes(q)));
    const by = { newest: (a, b) => b.created - a.created, activity: (a, b) => (b.last_activity || 0) - (a.last_activity || 0), name: (a, b) => a.name.localeCompare(b.name) };
    rows = rows.sort(by[mine.sort]);
    const empty = {
      mine: `<div class="chat-empty"><span class="av c-violet lg">${icon("bot")}</span><h3>No agents yet</h3><p class="muted">Describe one in a sentence, or start from a template.</p><button type="button" class="btn primary" data-new>${icon("plus")}New agent</button></div>`,
      from_directory: `<div class="empty">Agents you add from the <button type="button" class="linkbtn" data-hub="directory">shared catalog</button> appear here.</div>`,
      shared: `<div class="empty">No one has shared an agent with you yet.</div>`,
    };
    if (!rows.length) { $("#mine-body").innerHTML = lists[mine.tab].length ? `<div class="empty">No agents match.</div>` : empty[mine.tab]; return; }
    if (mine.view === "grid") { $("#mine-body").innerHTML = `<div class="agent-grid">${rows.map(a => card(a, `data-detail="${a.id}"`)).join("")}</div>`; return; }
    $("#mine-body").innerHTML = `<div class="tablewrap"><table class="grid hub-table"><thead><tr><th></th><th>Agent name</th><th>Status</th><th>Shared with</th><th>Skills</th><th>Last activity</th><th class="r" title="Claude tokens used by all chats with this agent">Usage</th></tr></thead><tbody>
      ${rows.map(a => `<tr data-chat="${a.id}">
        <td class="r"><button type="button" class="iconbtn" data-amenu="${a.id}" aria-label="Actions for ${esc(a.name)}">${icon("columns")}</button></td>
        <td><div class="hub-agent">${av(a)}<div><b>${esc(a.name)}${a.role ? `, ${esc(a.role)}` : ""}</b><small class="faint">By ${esc(a.owner)}</small></div></div></td>
        <td>${a.status === "live" ? `<span class="live-dot"></span>Live` : `<span class="faint">Paused</span>`}</td>
        <td>${a.in_directory ? `<span title="In the shared catalog">${icon("globe")}</span> ` : ""}${a.shared_count ? `<span title="Shared with ${a.shared_count} account(s)">${icon("users")} ${a.shared_count}</span>` : a.in_directory ? "" : `<span class="faint">Only you</span>`}</td>
        <td>${a.skills.length ? a.skills.map(s => `<span class="tag">${esc(skillName(s))}</span>`).join(" ") : '<span class="faint">–</span>'}</td>
        <td>${a.last_activity ? `${icon("clock")} ${ago(a.last_activity)}` : '<span class="faint">Never</span>'}</td>
        <td class="r num">${fmtTokens(a.tokens)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function agentMenu(btn, a) {
    document.querySelector(".menu")?.remove();
    const acts = [["chat", "chat", "Chat"], a.mine && ["edit", "gear", "Edit"],
      a.mine && (a.status === "live" ? ["pause", "clock", "Pause"] : ["resume", "check", "Resume"]),
      a.mine && (a.in_directory ? ["unpublish", "close", "Remove from the shared catalog"] : ["publish", "globe", "Publish to the shared catalog"]),
      a.mine && ["dup", "copy", "Duplicate"], !a.mine && a.installed && ["uninstall", "close", "Remove from my agents"],
      a.mine && ["delete", "ban", "Delete"]].filter(Boolean);
    const pop = document.createElement("div"); pop.className = "popover menu";
    pop.innerHTML = acts.map(([k, ic, l]) => `<button type="button" class="mi ${k === "delete" ? "danger" : ""}" data-act="${k}">${icon(ic)}${l}</button>`).join("");
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = Math.min(b.bottom + scrollY + 6, scrollY + innerHeight - pop.offsetHeight - 10) + "px";
    pop.style.left = Math.max(16, Math.min(b.left, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.onclick = e => { const k = e.target.closest("[data-act]")?.dataset.act; if (k) { pop.remove(); act(a, k); } };
  }
  async function act(a, k) {
    try {
      if (k === "chat") return startChat(a);
      if (k === "edit") return editor(a);
      if (k === "dup") return editor(null, { ...a, name: a.name + " (copy)", shared_with: [], in_directory: false });
      if (k === "delete") {
        return Auth.modal(`<h3>${icon("ban")}Delete ${esc(a.name)}?</h3><p class="muted">This removes the agent and every chat with it, for everyone it's shared with. It can't be undone.</p>`,
          async () => { await api(`/api/agents/custom/${a.id}`, { method: "DELETE" }); $("#modal").close(); Auth.toast(`${a.name} deleted`); Studio.forget("hub:" + a.id); await refresh(); }, { submit: "Delete", danger: true });
      }
      if (k === "uninstall") await api(`/api/agents/custom/${a.id}/install`, { method: "POST", body: { installed: false } });
      else {
        const body = { pause: { status: "paused" }, resume: { status: "live" }, publish: { in_directory: true }, unpublish: { in_directory: false } }[k];
        await api(`/api/agents/custom/${a.id}`, { method: "PATCH", body });
      }
      const msg = { pause: "Paused", resume: "Live again", publish: "Published to the shared catalog", unpublish: "Removed from the shared catalog", uninstall: "Removed from your agents" }[k];
      const undo = { unpublish: () => api(`/api/agents/custom/${a.id}`, { method: "PATCH", body: { in_directory: true } }),
                     uninstall: () => api(`/api/agents/custom/${a.id}/install`, { method: "POST", body: { installed: true } }) }[k];
      if (undo) UI.undoable(`${a.name}: ${msg.toLowerCase()}`, async () => { await undo(); await refresh(); }); else Auth.toast(msg);
      await refresh();
    } catch (e) { Auth.toast(e.message); }
  }
  async function refresh() { await Promise.all([loadLists(), loadRecents()]); if (mode === "ops") return Studio.reload(); if (page === "chat" && current && !current.builtin) { current = findAgent(current.id); if (!current) go("mine"); else renderChatShell(), render(); } else go(page === "editor" ? "mine" : page); }

  // ---------- shared catalog: agents published for everyone (in_directory) ----------
  function renderDirectory() {
    const pool = [...builtins, ...lists.directory];
    const creators = [...new Set(pool.map(a => a.owner))].sort();
    const rows = pool.filter(a => (dir.creator === "all" || a.owner === dir.creator) && (dir.status === "all" || a.status === dir.status));
    $("#hub-main").innerHTML = `
      <div class="hub-top"><div><h1 class="page">Shared catalog</h1><p class="lead">Ready-to-use agents that people in your organization published for everyone. Add one to your agents to find it in the Directory.</p></div>
        <button type="button" class="btn" data-publish>${icon("globe")}Publish one of mine</button></div>
      <div class="toolbar hub-filters"><label class="faint">Filter by:</label>
        <select id="dir-creator" aria-label="Creator"><option value="all">Any creator</option>${creators.map(c => `<option>${esc(c)}</option>`).join("")}</select>
        <select id="dir-status" aria-label="Status"><option value="all">Any status</option><option value="live">Live</option><option value="paused">Paused</option></select></div>
      <div class="agent-grid">${rows.map(a => card(a, `data-detail="${a.builtin ? a.id : a.id}"`, a.installed ? `<span class="badge new">Added</span>` : a.mine ? `<span class="badge new">Yours</span>` : "")).join("")
        || `<div class="empty">Nothing in the shared catalog yet. Publish one of your agents so others can use it.</div>`}</div>`;
    $("#dir-creator").value = creators.includes(dir.creator) ? dir.creator : "all"; $("#dir-status").value = dir.status;
    $("#dir-creator").onchange = e => { dir.creator = e.target.value; renderDirectory(); };
    $("#dir-status").onchange = e => { dir.status = e.target.value; renderDirectory(); };
  }
  function publishPicker() {
    const cands = lists.mine.filter(a => !a.in_directory);
    if (!cands.length) return Auth.toast(lists.mine.length ? "All your agents are already in the shared catalog" : "Create an agent first");
    Auth.modal(`<h3>${icon("globe")}Publish to the shared catalog</h3><p class="muted">Everyone who can use agents will be able to find and chat with it. Only you can edit it.</p>
      <div class="pick-list">${cands.map((a, i) => `<label class="pick">${av(a, "sm")}<span><b>${esc(a.name)}</b><small class="faint">${esc(a.role)}</small></span><input type="radio" name="aid" value="${a.id}" ${i ? "" : "checked"}></label>`).join("")}</div>`,
      async f => { await api(`/api/agents/custom/${f.elements.aid.value}`, { method: "PATCH", body: { in_directory: true } }); $("#modal").close(); Auth.toast("Published to the shared catalog"); await refresh(); },
      { submit: "Publish" });
  }
  function detail(a) {
    const actions = [
      a.status === "live" || a.builtin ? `<button type="button" class="btn primary" data-dact="chat">${icon("chat")}Chat</button>` : `<span class="faint">Paused by its creator</span>`,
      a.mine && `<button type="button" class="btn" data-dact="edit">${icon("gear")}Edit</button>`,
      !a.mine && !a.builtin && a.in_directory && (a.installed ? `<button type="button" class="btn" data-dact="uninstall">${icon("close")}Remove from my agents</button>` : `<button type="button" class="btn" data-dact="install">${icon("plus")}Add to my agents</button>`),
    ].filter(Boolean).join("");
    const d = $("#agentdlg");
    d.innerHTML = `<div class="agent-detail">
      <div class="tile-head c-${esc(a.color)}">${av(a, "lg")}<div><span class="tile-name">${esc(a.name)}</span><b>${esc(a.role || "Agent")}</b></div>
        <button type="button" class="iconbtn" data-close aria-label="Close">${icon("close")}</button></div>
      <p>${esc(a.description)}</p>
      ${a.skills?.length ? `<h4>Skills</h4><div class="chips">${a.skills.map(s => `<span class="tag">${icon("zap")}${esc(skillName(s))}</span>`).join("")}</div>` : ""}
      <h4>Tools</h4><div class="chips">${(a.builtin ? a.abilities || [] : Object.values(hub.tools)).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
      ${a.unavailable ? `<p class="faint">${icon("alert")}${esc(a.unavailable)}</p>` : ""}
      ${a.examples?.length ? `<h4>Try asking</h4><ul class="ex-list">${a.examples.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      <p class="faint">Created by ${esc(a.owner)}${a.updated ? ` · updated ${ago(a.updated)}` : ""}</p>
      <div class="row end">${actions}</div></div>`;
    d.showModal();
    d.onclick = async e => {
      if (e.target.closest("[data-close]") || e.target === d) return d.close();
      const k = e.target.closest("[data-dact]")?.dataset.dact; if (!k) return;
      d.close();
      if (k === "chat") startChat(a);
      else if (k === "edit") editor(a);
      else { try { await api(`/api/agents/custom/${a.id}/install`, { method: "POST", body: { installed: k === "install" } }); Auth.toast(k === "install" ? `${a.name} added to your agents` : "Removed"); await refresh(); } catch (x) { Auth.toast(x.message); } }
    };
  }

  // ---------- editor ----------
  function editor(a, draft = null, fromDraft = false) {
    showHub();
    page = "editor"; editing = a;
    $$("#hub-nav [data-hub]").forEach(b => b.setAttribute("aria-current", "false"));
    const v = { name: "", role: "", description: "", instructions: "", icon: "bot", color: "violet", kind: "", skills: [], examples: [], shared_with: [], in_directory: false, status: "live", ...(a || {}), ...(draft || {}) };
    const tools = k => Object.values(k === "study" ? hub.study_tools : hub.tools).map(t => `<span class="tag">${esc(t)}</span>`).join("");
    const allSkills = [...skills.builtin, ...skills.custom];
    $("#hub-main").innerHTML = `
      <form class="editor" id="editor" novalidate>
        <div class="hub-top"><div><h1 class="page">${a ? `Edit ${esc(a.name)}` : "New agent"}</h1>
          <p class="lead">${fromDraft ? "Claude drafted this from your description. Review it, change anything, then create it." : a ? "Changes apply to every chat from now on." : v.kind === "study" ? "Give your tutor a job. It sees your progress in the Study tab and can tick topics you've shown you know." : "Give your agent a job. It can read live subnet data, but can't change anything."}</p></div></div>
        <div class="editor-grid">
          <div class="card editor-main">
            <div class="editor-id">
              <span id="ed-av">${av(v, "xl")}</span>
              <div class="editor-names">
                <label class="in"><span>Name</span><input name="name" maxlength="40" required value="${esc(v.name)}" placeholder="e.g. Rhea"></label>
                <label class="in"><span>Role</span><input name="role" maxlength="60" value="${esc(v.role)}" placeholder="e.g. Risk Guardian"></label>
              </div>
            </div>
            <div class="in"><span>Look <em class="opt">background colour, role badge and face</em></span>
              <div class="swatches" role="radiogroup" aria-label="Color">${hub.colors.map(c => `<label class="swatch c-${c}" title="${c}"><input type="radio" name="color" value="${c}" ${c === v.color ? "checked" : ""}><span class="sr">${c}</span></label>`).join("")}</div>
              <div class="icon-pick" role="radiogroup" aria-label="Icon">${hub.icons.map(i => `<label title="${i}"><input type="radio" name="icon" value="${i}" ${i === v.icon ? "checked" : ""}>${icon(i)}</label>`).join("")}</div>
              <div class="face-pick-head"><span class="faint small">Face</span><button type="button" class="linkbtn small" data-more-faces>${icon("reset")}More faces</button></div>
              <div class="face-pick" role="radiogroup" aria-label="Face" id="ed-faces"></div></div>
            <label class="in"><span>Description <em class="opt">shown on the agent's card</em></span><input name="description" maxlength="400" value="${esc(v.description)}" placeholder="I'll…"></label>
            <label class="in"><span>Instructions</span><textarea name="instructions" rows="9" maxlength="8000" required placeholder="What should the agent focus on, which data should it check, and how should it answer?">${esc(v.instructions)}</textarea>
              <small class="hint" id="ed-rules">${v.kind === "study" ? "Ground rules always apply on top of these: answers in English, teaching rather than lecturing, honest feedback." : "Ground rules always apply on top of these: read-only data, cite numbers from tools, no financial advice."}</small></label>
            <div class="in"><span>Example questions <em class="opt">shown as quick starts</em></span>
              ${[0, 1, 2].map(i => `<input name="ex${i}" maxlength="200" value="${esc(v.examples[i] || "")}" placeholder="${["Which subnets can I mine with one GPU?", "Is SN64 risky right now?", "What changed this week?"][i]}">`).join("")}</div>
          </div>
          <div class="editor-side">
            <div class="card"><h3>${icon("zap")}Skills</h3>
              <div class="skill-pick">${allSkills.map(s => `<label><input type="checkbox" name="skills" value="${esc(s.id)}" ${v.skills.includes(s.id) ? "checked" : ""}><span><b>${esc(s.name)}</b><small class="faint">${esc(s.description || "")}</small></span></label>`).join("") || '<p class="faint">No skills yet.</p>'}</div>
              <button type="button" class="linkbtn" data-skills>Open the skill hub</button></div>
            <div class="card"><h3>${icon("search")}Tools</h3><div class="chips" id="ed-tools">${tools(v.kind)}</div>
              <p class="faint small" id="ed-tools-note">${v.kind === "study" ? "Your study progress: read it, and tick or untick topics." : "Read-only access to the same live data you see in AXoR."}</p>
              <label class="toggle-row"><span><b>Study agent</b><small class="faint">A tutor for the Study tab: your progress instead of subnet data</small></span><span class="switch"><input type="checkbox" name="study" ${v.kind === "study" ? "checked" : ""}><span></span></span></label></div>
            <div class="card"><h3>${icon("users")}Sharing</h3>
              <label class="in"><span>Share with <em class="opt">usernames, comma-separated</em></span><input name="shared_with" value="${esc((v.shared_with || []).join(", "))}" placeholder="alice, bob" autocomplete="off" spellcheck="false"></label>
              <label class="toggle-row"><span><b>Shared catalog</b><small class="faint">Everyone who uses agents can find it</small></span><span class="switch"><input type="checkbox" name="in_directory" ${v.in_directory ? "checked" : ""}><span></span></span></label>
              <label class="toggle-row"><span><b>Live</b><small class="faint">Paused agents can't be chatted with</small></span><span class="switch"><input type="checkbox" name="live" ${v.status !== "paused" ? "checked" : ""}><span></span></span></label></div>
          </div>
        </div>
        <p class="err" role="alert"></p>
        <div class="row end editor-actions"><button type="button" class="btn" data-cancel>Cancel</button>
          <button type="submit" class="btn" value="save">${a ? "Save changes" : "Create agent"}</button>
          <button type="submit" class="btn primary" value="chat">${icon("chat")}${a ? "Save & chat" : "Create & chat"}</button></div>
      </form>`;
    const f = $("#editor");
    // face picker: "" = drawn from the name (follows it as you type), otherwise a picked seed; colour is the
    // background and the icon the badge
    let face = v.face || "", seeds = Face.seeds(11);
    const look = () => ({ name: f.elements.name.value.trim() || "agent", color: f.elements.color.value, icon: f.elements.icon.value });
    const preview = () => { $("#ed-av").innerHTML = av({ ...look(), face }, "xl"); };
    const faces = () => {
      const opts = ["", ...(face && !seeds.includes(face) ? [face] : []), ...seeds];
      $("#ed-faces").innerHTML = opts.map(s => `<label class="face-opt" title="${s ? "Pick this face" : "Drawn from the name"}"><input type="radio" name="face" value="${s}" ${s === face ? "checked" : ""}>${av({ ...look(), icon: "", face: s })}${s ? "" : `<span class="face-tag">Name</span>`}<span class="sr">${s ? "Face " + s : "Face drawn from the name"}</span></label>`).join("");
    };
    faces();
    f.addEventListener("change", e => {
      if (e.target.name === "face") { face = e.target.value; preview(); }
      if (e.target.name === "color") { preview(); faces(); }
      if (e.target.name === "icon") preview();
      if (e.target.name === "study") {
        const k = e.target.checked ? "study" : "";
        $("#ed-tools").innerHTML = tools(k);
        $("#ed-tools-note").textContent = k ? "Your study progress: read it, and tick or untick topics." : "Read-only access to the same live data you see in AXoR.";
        $("#ed-rules").textContent = k ? "Ground rules always apply on top of these: answers in English, teaching rather than lecturing, honest feedback." : "Ground rules always apply on top of these: read-only data, cite numbers from tools, no financial advice.";
      }
    });
    f.elements.name.addEventListener("input", () => { preview(); if (!face) faces(); else $("#ed-faces .face-opt").outerHTML = `<label class="face-opt" title="Drawn from the name"><input type="radio" name="face" value="">${av({ ...look(), icon: "", face: "" })}<span class="face-tag">Name</span><span class="sr">Face drawn from the name</span></label>`; });
    $("[data-more-faces]", f).onclick = () => { seeds = Face.seeds(11); faces(); };
    $("[data-cancel]", f).onclick = () => go(a ? "mine" : "home");
    f.onsubmit = async e => {
      e.preventDefault();
      const chat = e.submitter?.value === "chat", btns = $$("button[type=submit]", f);
      const body = {
        name: f.elements.name.value, role: f.elements.role.value, description: f.elements.description.value, instructions: f.elements.instructions.value,
        color: f.elements.color.value, icon: f.elements.icon.value, face, kind: f.elements.study.checked ? "study" : "", skills: $$("[name=skills]:checked", f).map(x => x.value),
        examples: [0, 1, 2].map(i => f.elements["ex" + i].value).filter(x => x.trim()),
        shared_with: f.elements.shared_with.value.split(/[\s,]+/).filter(Boolean), in_directory: f.elements.in_directory.checked,
        status: f.elements.live.checked ? "live" : "paused",
      };
      btns.forEach(b => b.disabled = true); e.submitter?.classList.add("loading");
      try {
        const saved = await api(a ? `/api/agents/custom/${a.id}` : "/api/agents/custom", { method: a ? "PUT" : "POST", body });
        Auth.toast(a ? "Saved" : `${saved.name} is ready`);
        await loadLists();
        if (chat) startChat(findAgent(saved.id) || saved); else { mine.tab = "mine"; go("mine"); }
      } catch (x) { $(".err", f).textContent = x.message; }
      finally { btns.forEach(b => { b.disabled = false; b.classList.remove("loading"); }); }
    };
    $("#hub-main").scrollTop = 0; f.elements.name.focus();
  }

  // ---------- chat ----------
  // Laid out like a chat with a teammate: chats & activity on the left (with Brain, channels and feedback), the
  // agent's name with Share / link / ⋯ on top, a greeting with reply suggestions, answers with read-aloud, copy,
  // ratings and usage, and a composer with @ (skills, tools, files), / commands, attachments and voice input.
  let convQ = "", speaking = null;
  const SLASH = [["new", "Start a new chat"], ["remember", "Save a fact to memory: /remember I mine on one RTX 4090", true], ["memory", "Open what the agent remembers"],
    ["rename", "Rename this chat: /rename Weekly plan", true], ["brain", "Open the agent's brain"], ["share", "Share this agent"], ["help", "Show what I can do"]];
  const greetName = () => Auth.me()?.username || "there";
  const ckey = () => `agents:${current.id}`;
  async function startChat(a, cid = null) {
    showHub();
    if (!a) return;
    current = a; page = "chat"; conv = null;
    $$("#hub-nav [data-hub]").forEach(b => b.setAttribute("aria-current", "false"));
    renderChatShell();
    if (cid) await openConv(cid); else render();
    Chat.focus(ckey());
  }
  function renderChatShell() {
    const a = current, custom = !a.builtin;
    $("#hub-main").innerHTML = `
      <div class="agents-layout ac ${pref("acCollapsed") ? "collapsed" : ""}">
        <aside class="agent-side ac-side">
          <div class="ac-side-top"><button type="button" class="ac-link" id="agent-new">${icon("note")}New chat</button>
            <button type="button" class="iconbtn sm" data-ac="collapse" title="Hide chats" aria-label="Hide chats">${icon("left")}</button></div>
          <div class="ac-group"><span>Chats and activity</span><button type="button" class="iconbtn sm" data-ac="filter" title="Search chats" aria-label="Search chats">${icon("search")}</button></div>
          <input class="ac-search" id="conv-q" type="search" placeholder="Search chats…" ${convQ ? "" : "hidden"} value="${esc(convQ)}">
          <div id="conv-list" class="conv-list"></div>
          <div class="ac-foot">
            ${custom ? `<button type="button" class="ac-link" data-ac="channels">${icon("hash")}Connect channels${typeof Slack !== "undefined" && Slack.ready() ? `<span class="ac-dot" title="Slack connected"></span>` : ""}</button>
            <button type="button" class="ac-link" data-ac="brain">${icon("bulb")}Brain</button>
            <button type="button" class="ac-link" data-ac="feedback">${icon("chat")}Give feedback</button>` : ""}
          </div>
        </aside>
        <div class="chat card ac-main">
          <div class="ac-top" id="chat-head"></div>
          <div class="ac-bar" id="ac-bar"></div>
          <div class="chat-log cx-log" id="chat-log" aria-live="polite"></div>
          <div class="approvals" id="approvals"></div>
          <div id="ac-compose"></div>
        </div>
      </div>`;
    $("#agent-new").onclick = newChat;
    $("#conv-q").oninput = e => { convQ = e.target.value; drawConvs(); };
    Chat.bind($("#hub-main .ac-main"), { items: () => conv?.items || [], onSay: text => send(text), onRate: rate, onSpeak: n => { speaking = n; } });
    renderHead(); loadConvs();
  }
  // the composer: + (upload, Drive, Source, a skill or a tool), / commands, @ mentions, voice, the model and usage
  function drawComposer() {
    const a = current, box = $("#ac-compose"); if (!a || !box) return;
    const custom = !a.builtin, items = conv?.items || [];
    const o = {
      key: ckey(), busy, disabled: !usable(), compact: false,
      placeholder: !hub.configured ? "Connect a model in Models to use agents" : !usable() ? `${a.name} is paused` : a.builtin ? a.placeholder || `Message ${a.name}…` : `Message ${a.name}… (+ to add files, / for commands)`,
      plus: custom ? [{ id: "skills", icon: "zap", label: "Skill", note: "Apply one of your skills to the answer" }, { id: "tools", icon: "search", label: "Tool", note: "Ask for a specific tool" }] : false,
      slash: custom ? SLASH : [], mic: custom, tokens: Chat.tokensOf(items), turns: items.filter(i => i.kind === "assistant" && i.tokens).length,
      onSend: (text, sent) => send(text, sent), onCommand: command,
      mention: custom ? mentionGroups : null, mentionTabs: [["skills", "Skills"], ["tools", "Tools"], ["files", "Files"]],
    };
    box.innerHTML = Chat.composer(o);
    Chat.mount(box.querySelector("form"), o);
  }
  function newChat() { conv = null; renderHead(); render(); loadConvs(); Chat.focus(ckey()); }
  function usable() { return hub.configured && (current.builtin || current.status === "live"); }
  function renderHead() {
    const a = current; if (!a || !$("#chat-head")) return;
    $("#chat-head").innerHTML = `${av(a)}<h2>${esc(a.name)}${a.role ? `<span>, ${esc(a.role)}</span>` : ""}</h2>${!a.builtin && a.status === "paused" ? `<span class="badge caution">Paused</span>` : ""}
      <span class="ac-spacer"></span>
      ${!a.builtin ? `<div class="ac-share">${a.mine ? `<button type="button" class="btn sm" data-ac="share">${icon("users")}Share</button>` : ""}<button type="button" class="btn sm" data-ac="link" title="Copy link to this agent" aria-label="Copy link to this agent">${icon("link")}</button></div>
        <button type="button" class="iconbtn" data-ac="menu" title="More" aria-label="More actions">${icon("dots")}</button>` : ""}
      ${a.builtin && hub.is_admin ? `<button type="button" class="btn sm" data-settings>${icon("chip")}Models</button>` : ""}`;
    $("#ac-bar").innerHTML = `<button type="button" class="ac-title" data-ac="conv-menu" ${conv?.id ? "" : "disabled"}>${esc(conv ? conv.title : "New chat")}${conv?.id ? icon("chev") : ""}</button>
      <span class="ac-spacer"></span>${Chat.displayButton()}${!a.builtin ? `<button type="button" class="iconbtn sm" data-ac="brain" title="Brain: instructions, skills, tools and memory" aria-label="Open brain">${icon("sliders")}</button>` : ""}`;
    drawComposer();
  }
  let convs = [];
  async function loadConvs() {
    const box = $("#conv-list"); if (!box) return;
    if (!box.children.length) box.innerHTML = Array.from({ length: 3 }, () => `<div class="skeleton conv-sk" aria-hidden="true"></div>`).join("");
    convs = await api(`${base(current)}/conversations`).catch(() => []);
    drawConvs();
  }
  function drawConvs() {
    const box = $("#conv-list"); if (!box) return;
    const q = convQ.trim().toLowerCase(), list = convs.filter(c => !q || c.title.toLowerCase().includes(q));
    box.innerHTML = list.map(c => `<button type="button" class="conv ${c.id === conv?.id ? "on" : ""}" data-conv="${c.id}" title="${esc(c.title)} · ${ago(c.updated)}">${icon("chat")}<span>${esc(c.title)}</span></button>`).join("")
      || `<p class="faint small" style="margin:6px 4px">${q ? "No chats match." : "No chats yet."}</p>`;
  }
  async function openConv(cid) {
    $("#approvals").innerHTML = ""; $("#chat-log").innerHTML = Loading.line("Loading conversation…");
    try { conv = await api(`${base(current)}/conversations/${cid}`); } catch (e) { conv = null; Auth.toast(e.message); }
    renderHead(); render(); drawConvs();
  }
  // the agent opens the chat itself, like a teammate saying hello, with its example questions as replies
  function renderEmpty() {
    const a = current;
    $("#approvals").innerHTML = "";
    if (!hub.configured) {
      $("#chat-log").innerHTML = `<div class="chat-empty">${av({ icon: "key", color: "slate" }, "xl")}<h3>Connect a model to use agents</h3>
        <p class="muted">Agents run on Claude, OpenAI, any model on OpenRouter, a model on your own server, or Terminal (the Claude Code CLI signed in on the server). ${hub.is_admin ? "Connect one in Models. Keys are verified, stored encrypted on the server, and never sent back to browsers." : "Ask an administrator to connect one."}</p>
        ${hub.is_admin ? `<button type="button" class="btn primary" data-settings>${icon("key")}Connect a model</button>` : ""}</div>`;
      return;
    }
    const paused = a.status === "paused" && !a.builtin;
    $("#chat-log").innerHTML = `<div class="msg bot ac-greet">${av(a, "sm")}<div class="bubble"><p>Hi ${esc(greetName())}! ${a.id === "assistant" ? "I'm your AXoR Assistant" : a.builtin ? `I'm the ${esc(a.name)} agent (${esc(a.role)})` :`I'm ${esc(a.name)}${a.role ? `, your ${esc(a.role)}` : ""}`}.</p>
        ${a.description ? `<p>${esc(a.description)}</p>` : ""}<p>${paused ? `I'm paused right now${a.mine ? ": resume me from the ⋯ menu" : ""}.` : "What should we work on?"}</p></div></div>
      ${paused ? "" : suggestions(a.examples || [])}`;
  }
  const suggestions = xs => xs.length ? `<div class="ac-suggest">${xs.map(x => `<button type="button" class="chip ac-chip" data-example="${esc(x)}">${icon("right")}${esc(x)}</button>`).join("")}</div>` : "";
  const toolHtml = i => `${icon(i.name.startsWith("propose") ? "shield" : i.name === "remember" ? "bulb" : "search")}${i.name === "remember" ? `Remembered: ${esc(i.input?.fact || "")}` : `${TOOL_LABEL[i.name] || esc(i.name)}${describe(i.input)}`}`;
  const shareHtml = (i, n) => i.index != null && conv.id && typeof Slack !== "undefined" && Slack.ready() ? `<button type="button" class="iconbtn sm" data-sl-share="agent:${current.id}:${esc(conv.id)}:${i.index}" data-sl-label="${esc(current.name)}'s answer" title="Share to Slack" aria-label="Share to Slack">${icon("hash")}</button>` : "";
  function render() {
    if (!$("#chat-log")) return;
    if (!conv) return renderEmpty();
    const log = $("#chat-log");
    log.innerHTML = Chat.log(conv.items, { agent: current, busy, busyLabel: busyLabel(), rate: !current.builtin, share: shareHtml, toolHtml, speaking });
    Chat.enhance(log);
    $("#approvals").innerHTML = proposalsHtml(conv.proposals);
  }
  // a chat's proposal cards, pending first (also in the Assist panel, assist.js)
  function proposalsHtml(list) {
    const props = [...(list || [])].sort((a, b) => (a.status === "pending") === (b.status === "pending") ? b.id - a.id : a.status === "pending" ? -1 : 1);
    return props.length ? `<h4>${icon("shield")}Proposed changes</h4>` + props.map(p => {
      const [label, lvl] = STATUS[p.status] || [p.status, "new"];
      return `<div class="proposal ${p.status}">
        <div><b>#${p.id} · ${esc(p.label)}</b><small>${esc(p.reason)}</small>${p.result?.message && p.status === "failed" ? `<small class="no">${esc(p.result.message)}</small>` : ""}
          ${p.detail ? `<details class="prop-more" ${p.status === "pending" ? "open" : ""}><summary>Changes</summary><pre class="diff">${diffHtml(p.detail)}</pre></details>` : ""}
          ${p.result?.output ? `<details class="prop-more" open><summary>Answer</summary><pre>${esc(p.result.output)}</pre></details>` : ""}</div>
        ${p.status === "pending" ? `<div class="row"><button type="button" class="btn" data-decide="${p.id}" data-approve="0">Reject</button><button type="button" class="btn primary ${p.danger || /delete|reset|disable/.test(p.label) ? "danger" : ""}" data-decide="${p.id}" data-approve="1">Approve</button></div>`
          : `<span class="badge ${lvl}">${label}</span>`}
      </div>`;
    }).join("") : "";
  }
  // a proposed code change's unified diff: added and removed lines coloured
  const diffHtml = text => text.split("\n").map(l => {
    const c = /^(\+\+\+|---)/.test(l) ? "f" : l[0] === "+" ? "add" : l[0] === "-" ? "del" : l.startsWith("@@") ? "hunk" : "";
    return c ? `<span class="${c}">${esc(l)}</span>` : esc(l);
  }).join("\n");
  async function rate(n, r, it) {
    const v = it.rating === r ? 0 : r;
    try { await api(`${base(current)}/conversations/${conv.id}/rate`, { method: "POST", body: { index: it.index, rating: v } }); it.rating = v; render(); if (v) Auth.toast(v > 0 ? "Thanks! Marked as a good answer" : "Thanks. Tell us more with Give feedback"); } catch (x) { Auth.toast(x.message); }
  }

  function busyLabel() {
    const s = Math.floor((Date.now() - busySince) / 1000);
    const what = s < 20 ? "Thinking…" : s < 60 ? "Still working: checking the data…" : "Taking longer than usual…";
    return s < 2 ? what : `${what} ${s}s`;
  }
  // "/" commands run here instead of being sent; true when handled
  async function command(cmd, rest) {
    if (cmd === "new") { newChat(); return true; }
    if (cmd === "memory") { memoryDlg(); return true; }
    if (cmd === "brain") { brain(); return true; }
    if (cmd === "share") { current.mine ? shareDlg() : copyLink(); return true; }
    if (cmd === "help") { Auth.toast("Commands: " + SLASH.map(([k]) => "/" + k).join(" ") + " · + adds files, Drive or Source code"); return true; }
    if (cmd === "remember") {
      if (!rest.trim()) { Auth.toast("Write the fact after /remember"); return true; }
      try { await api(`${base(current)}/memory`, { method: "POST", body: { text: rest } }); Auth.toast(`${current.name} will remember that`); } catch (e) { Auth.toast(e.message); }
      return true;
    }
    if (cmd === "rename") { if (!conv?.id) Auth.toast("Send a message first"); else renameConv(rest); return true; }
    return false;
  }
  async function send(text, sent = []) {
    if (busy || !text.trim()) return false;
    const a = current;
    busy = true; busySince = Date.now();
    busyTimer = setInterval(() => { const l = $("#chat-log .typing-label"); if (l) l.textContent = busyLabel(); }, 1000);
    if (!conv) conv = { id: null, title: text.slice(0, 80), items: [], proposals: [] };
    conv.items.push({ kind: "user", text, attachments: sent.map(x => ({ kind: x.kind, label: x.label })) });
    renderHead(); render();
    let ok = true;
    try {
      const r = await api(`${base(a)}/chat`, { method: "POST", body: { conversation_id: conv.id, message: text, ...Chat.choice(), ...(a.builtin ? {} : { attachments: sent.map(({ kind, id }) => ({ kind, id })) }) } });
      if (current === a) { conv = r; if (r.error) conv.items.push({ kind: "note", text: r.error }); }
    } catch (e) {
      if (current === a) { conv.items.push({ kind: "note", text: e.message }); ok = false; }
    } finally {
      busy = false; clearInterval(busyTimer);
      if (current === a && page === "chat") { renderHead(); render(); loadConvs(); Chat.focus(ckey()); }
      loadRecents(); loadLists();
    }
    if (!ok) { Chat.state(`agents:${a.id}`).atts = sent; drawComposer(); }
    return true;
  }

  // ---------- @ mentions: skills, tools and files ----------
  let mentionData = null;
  async function mentionGroups(q = "", tab = "all") {
    if (!mentionData) {
      const f = await api("/api/workspace/files").catch(() => ({ files: [] }));
      mentionData = { files: (f.files || []).slice(0, 40) };
      setTimeout(() => { mentionData = null; }, 60000);
    }
    const own = new Set(current.skills || []);
    const allSkills = [...(skills?.builtin || []), ...(skills?.custom || [])].sort((x, y) => own.has(y.id) - own.has(x.id));
    const ql = q.toLowerCase(), hit = s => !ql || s.toLowerCase().includes(ql);
    const groups = {
      skills: allSkills.filter(s => hit(s.name)).slice(0, 8).map(s => ({ kind: "skill", id: s.id, label: s.name, ic: s.icon || "zap", note: own.has(s.id) ? "this agent's skill" : "" })),
      tools: Object.entries(current.kind === "study" ? hub.study_tools : hub.tools).filter(([, l]) => hit(l)).map(([id, l]) => ({ kind: "tool", id, label: l, ic: "search" })),
      files: mentionData.files.filter(f => hit(f.name)).slice(0, 8).map(f => ({ kind: "file", id: f.id, label: f.name, ic: "file", note: f.netuid != null ? `SN${f.netuid}` : "" })),
    };
    return (tab === "all" ? ["skills", "tools", "files"] : [tab]).map(g => ({ title: g[0].toUpperCase() + g.slice(1), items: groups[g] }));
  }

  // ---------- agent: share, link, ⋯ menu, memory, brain, channels, feedback ----------
  const link = () => `${location.origin}${location.pathname}#agents/${current.id}`;
  async function copyLink() { try { await navigator.clipboard.writeText(link()); Auth.toast("Link copied: anyone it's shared with can open it"); } catch { Auth.toast(link()); } }
  function shareDlg() {
    const a = current;
    const f = Auth.modal(`<h3>${icon("users")}Share ${esc(a.name)}</h3>
      <label class="in"><span>Share with <em class="opt">usernames, comma-separated</em></span><input name="users" value="${esc((a.shared_with || []).join(", "))}" placeholder="alice, bob" autocomplete="off" spellcheck="false"></label>
      <label class="toggle-row"><span><b>Shared catalog</b><small class="faint">Everyone who uses agents can find it</small></span><span class="switch"><input type="checkbox" name="dir" ${a.in_directory ? "checked" : ""}><span></span></span></label>
      <p class="fine">People you share with chat with ${esc(a.name)} in their own chats; only you can change it. <button type="button" class="linkbtn" data-copy-link>Copy link</button></p>`,
      async f => {
        await api(`/api/agents/custom/${a.id}`, { method: "PATCH", body: { shared_with: f.elements.users.value.split(/[\s,]+/).filter(Boolean), in_directory: f.elements.dir.checked } });
        $("#modal").close(); Auth.toast("Sharing updated"); await refresh();
      }, { submit: "Save" });
    $("[data-copy-link]", f).onclick = copyLink;
  }
  function headMenu(btn) {
    const a = current;
    const acts = [["memory", "bulb", "Memory"], a.mine && (a.status === "live" ? ["pause", "clock", "Pause agent"] : ["resume", "check", "Resume agent"]),
      ["dup2", "copy", "Duplicate agent", !a.mine], a.mine && ["edit", "gear", "Edit agent"], a.mine && ["delete", "ban", "Delete agent"]].filter(Boolean);
    document.querySelector(".menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover menu";
    pop.innerHTML = acts.map(([k, ic, l, off]) => `<button type="button" class="mi ${k === "delete" ? "danger" : ""}" data-act="${k}" ${off ? 'disabled title="Only the creator can duplicate it"' : ""}>${icon(ic)}${l}</button>`).join("");
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px"; pop.style.left = Math.max(16, Math.min(b.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.onclick = async e => {
      const k = e.target.closest("[data-act]:not([disabled])")?.dataset.act; if (!k) return;
      pop.remove();
      if (k === "memory") return memoryDlg();
      if (k === "dup2") { try { const d = await api(`/api/agents/custom/${a.id}/duplicate`, { method: "POST" }); Auth.toast(`${d.name} created`); await loadLists(); return startChat(findAgent(d.id) || d); } catch (x) { return Auth.toast(x.message); } }
      act(a, k);
    };
  }
  async function memoryDlg() {
    const a = current, url = `${base(a)}/memory`;
    let items;
    try { items = await api(url); } catch (e) { return Auth.toast(e.message); }
    const draw = f => {
      $(".ac-mem", f).innerHTML = items.length ? items.map(m => `<li><span>${esc(m.text)}<small class="faint">${m.source === "agent" ? `Saved by ${esc(a.name)}` : "Added by you"} · ${ago(m.created)}</small></span><button type="button" class="iconbtn sm" data-forget="${m.id}" aria-label="Forget">${icon("close")}</button></li>`).join("")
        : `<li class="faint">${esc(a.name)} doesn't remember anything about you yet. It saves lasting facts you mention (your hardware, goals, preferences), or add one here.</li>`;
      $("[data-forget-all]", f).hidden = !items.length;
    };
    const f = Auth.modal(`<h3>${icon("bulb")}What ${esc(a.name)} remembers about you</h3><p class="muted">Used in every chat with ${esc(a.name)}. Only you see your memory; people ${esc(a.name)} is shared with have their own.</p>
      <ul class="ac-mem"></ul>
      <div class="ac-mem-add"><input name="fact" maxlength="300" placeholder="Add something to remember, e.g. I have one RTX 4090"><button type="button" class="btn sm" data-add-mem>${icon("plus")}Add</button></div>
      <p><button type="button" class="linkbtn danger-text" data-forget-all hidden>Forget everything</button></p>`, async () => $("#modal").close(), { submit: "Done" });
    $("[data-cancel]", f)?.remove(); $("[data-close]", f)?.remove();
    draw(f);
    const add = async () => { const v = f.elements.fact.value.trim(); if (!v) return; try { items = await api(url, { method: "POST", body: { text: v } }); f.elements.fact.value = ""; draw(f); } catch (e) { Auth.toast(e.message); } };
    $("[data-add-mem]", f).onclick = add;
    f.elements.fact.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); add(); } });
    f.addEventListener("click", async e => {
      const x = e.target.closest("[data-forget]");
      if (x) {
        const m = items.find(i => String(i.id) === x.dataset.forget);
        return UI.confirm({ title: `Forget this?`, body: `${esc(a.name)} stops using it in your chats. This can't be undone.`, items: m ? [esc(m.text)] : [], ok: "Forget", icon: "bulb",
          run: async () => { items = await api(`${url}/${x.dataset.forget}`, { method: "DELETE" }); draw(f); Auth.toast("Forgotten"); } });
      }
      if (e.target.closest("[data-forget-all]")) {
        UI.confirm({ title: `Forget everything ${esc(a.name)} remembers about you?`, body: `All ${items.length} fact${items.length === 1 ? "" : "s"} are deleted. ${esc(a.name)} starts from nothing in your next chat. This can't be undone.`,
          items: items.map(i => esc(i.text)), ok: "Forget everything", icon: "bulb",
          run: async () => { items = await api(url, { method: "DELETE" }); draw(f); Auth.toast("Memory cleared"); } });
      }
    });
  }
  async function brain() {
    const a = current;
    const mem = await api(`${base(a)}/memory`).catch(() => []);
    const all = [...(skills?.builtin || []), ...(skills?.custom || [])], sk = (a.skills || []).map(id => all.find(s => s.id === id)).filter(Boolean);
    const d = $("#modal");
    Auth.modal(`<h3>${av(a, "sm")}${esc(a.name)}'s brain</h3>
      <div class="ac-brain">
        <section><h4>${icon("note")}Instructions</h4>${a.mine || a.instructions ? `<pre>${esc(a.instructions || "Only the creator can see the instructions.")}</pre>` : `<p class="faint">Only the creator can see the instructions.</p>`}</section>
        <section><h4>${icon("zap")}Skills</h4>${sk.length ? sk.map(s => `<p><b>${esc(s.name)}</b> <span class="faint">${esc(s.description || "")}</span></p>`).join("") : `<p class="faint">No skills. Mention any skill with @ to use it for one message.</p>`}</section>
        <section><h4>${icon("search")}Tools</h4><div class="chips">${Object.values(a.kind === "study" ? hub.study_tools : hub.tools).map(t => `<span class="tag">${esc(t)}</span>`).join("")}<span class="tag">Memory</span></div></section>
        <section><h4>${icon("bulb")}Memory</h4><p>${mem.length ? `${mem.length} thing${mem.length > 1 ? "s" : ""} remembered about you.` : "Nothing remembered yet."} <button type="button" class="linkbtn" data-brain-mem>Open memory</button></p></section>
      </div>`, async () => { d.close(); if (a.mine) editor(a); }, { submit: a.mine ? "Edit agent" : "Close" });
    $("[data-brain-mem]", d).onclick = () => { d.close(); memoryDlg(); };
  }
  function channels() {
    const sl = typeof Slack !== "undefined" ? Slack : null, on = sl?.ready();
    Auth.modal(`<h3>${icon("hash")}Connect channels</h3><p class="muted">Bring ${esc(current.name)}'s answers to where your team talks.</p>
      <div class="ac-chan ${on ? "on" : ""}">${icon("hash")}<div><b>Slack</b><small class="faint">${on ? "Connected. Use the # button under any answer to share it to the team channel." : Auth.me()?.role === "admin" ? "Not connected yet. Connect your Slack app to share answers to a channel." : "Not connected yet. Ask an admin to connect Slack."}</small></div>
        ${!on && Auth.me()?.role === "admin" ? `<button type="button" class="btn sm" data-slack-connect>Connect</button>` : on ? `<span class="badge clear">${icon("check")}Connected</span>` : ""}</div>`,
      async () => $("#modal").close(), { submit: "Done" });
    $("[data-slack-connect]")?.addEventListener("click", () => { $("#modal").close(); sl.settings(); });
  }
  function feedbackDlg() {
    Auth.modal(`<h3>${icon("chat")}Give feedback on ${esc(current.name)}</h3><p class="muted">What worked, what didn't, what you'd like it to do. Administrators see it in the audit log.</p>
      <label class="in"><span>Your feedback</span><textarea name="text" rows="4" maxlength="1000" class="sl-comment" required></textarea></label>`,
      async f => { await api(`${base(current)}/feedback`, { method: "POST", body: { text: f.elements.text.value } }); $("#modal").close(); Auth.toast("Thanks for the feedback"); }, { submit: "Send" });
  }
  function convMenu(btn) {
    document.querySelector(".menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover menu";
    pop.innerHTML = `<button type="button" class="mi" data-act="rename">${icon("note")}Rename chat</button><button type="button" class="mi danger" data-act="delete">${icon("close")}Delete chat</button>`;
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px"; pop.style.left = b.left + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.onclick = e => { const k = e.target.closest("[data-act]")?.dataset.act; if (!k) return; pop.remove(); k === "rename" ? renameConv() : deleteConv(); };
  }
  function renameConv(title) {
    const go2 = async t => { await api(`${base(current)}/conversations/${conv.id}`, { method: "PATCH", body: { title: t } }); conv.title = t.trim(); renderHead(); loadConvs(); };
    if (title?.trim()) return go2(title).catch(e => Auth.toast(e.message));
    const f = Auth.modal(`<h3>${icon("note")}Rename chat</h3><label class="in"><span>Name</span><input name="t" maxlength="80" value="${esc(conv.title)}" required></label>`,
      async f => { await go2(f.elements.t.value); $("#modal").close(); }, { submit: "Rename" });
    f.elements.t.select();
  }
  function deleteConv() {
    Auth.modal(`<h3>${icon("close")}Delete this chat?</h3><p class="muted">“${esc(conv.title)}” is removed for good. ${esc(current.name)} keeps what it remembers about you.</p>`,
      async () => { await api(`${base(current)}/conversations/${conv.id}`, { method: "DELETE" }); $("#modal").close(); Auth.toast("Chat deleted"); newChat(); loadRecents(); }, { submit: "Delete", danger: true });
  }
  async function chatClick(e) {
    const t = e.target, b = t.closest("[data-ac]"); if (!b || !$("#hub-main")?.contains(b)) return false;
    const k = b.dataset.ac;
    if (k === "collapse") { const l = $(".ac"); l.classList.toggle("collapsed"); pref("acCollapsed", l.classList.contains("collapsed")); }
    else if (k === "filter") { const q = $("#conv-q"); q.hidden = !q.hidden; if (!q.hidden) q.focus(); else { convQ = ""; q.value = ""; drawConvs(); } }
    else if (k === "channels") channels();
    else if (k === "brain") brain();
    else if (k === "feedback") feedbackDlg();
    else if (k === "share") shareDlg();
    else if (k === "link") copyLink();
    else if (k === "menu") { e.stopPropagation(); headMenu(b); }
    else if (k === "conv-menu") { e.stopPropagation(); convMenu(b); }
    return true;
  }
  // links like #agents/12 open that agent's chat; the Assist panel also passes the conversation to continue
  let deepLink = null, deepConv = null;
  function openAgent(id, cid = null) { deepLink = String(id); deepConv = cid; }

  // ---------- model picker ----------
  // ---------- skill hub ----------
  function skillHub(selectId) {
    const d = $("#skillhub");
    let sel = selectId || skills.builtin[0]?.id, mode = "view";
    const all = () => [...skills.builtin, ...skills.custom];
    const draw = () => {
      const s = all().find(x => x.id === sel);
      const item = x => `<button type="button" class="skill-item ${x.id === sel && mode === "view" ? "on" : ""}" data-skill="${esc(x.id)}">${av({ icon: x.icon, color: x.builtin ? "amber" : "teal" }, "xs")}<span>${esc(x.name)}</span></button>`;
      d.innerHTML = `<div class="sh">
        <div class="sh-head"><h2>${icon("zap")}Skill hub</h2>
          <div class="row"><button type="button" class="btn ghost" data-sh="create">${icon("plus")}Create skill</button>
          <label class="btn ghost">${icon("download")}Upload skill<input type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden id="sh-upload"></label>
          <button type="button" class="iconbtn" data-sh="close" aria-label="Close">${icon("close")}</button></div></div>
        <div class="sh-body">
          <nav class="sh-list">
            <h4>Built-in skills</h4>${skills.builtin.map(item).join("")}
            <h4>Skills from your team</h4>${skills.custom.map(item).join("") || `<p class="faint small">None yet.</p>`}
            <div class="sh-promo"><b>Make your agents truly yours</b><p class="faint small">Create a skill to teach agents a checklist, a format or a playbook, then switch it on in any agent.</p>
              <button type="button" class="btn sm" data-sh="create">${icon("plus")}Create skill</button></div>
          </nav>
          <div class="sh-view">${mode === "view" && s ? `
            <div class="sh-meta"><div><h3>${esc(s.name)}</h3><p class="faint">${esc(s.description || "")}${s.builtin ? " · Built-in" : ` · by ${esc(s.owner)}`}</p></div>
              ${s.mine ? `<div class="row"><button type="button" class="btn sm" data-sh="edit">${icon("gear")}Edit</button><button type="button" class="btn sm danger-text" data-sh="delete">${icon("ban")}Delete</button></div>` : ""}</div>
            <div class="md">${md(s.body)}</div>` : mode !== "view" ? skillForm(mode === "edit" ? s : mode) : `<div class="empty">Pick a skill.</div>`}</div>
        </div></div>`;
      const f = $("#sh-form", d);
      if (f) {
        f.onsubmit = async e => {
          e.preventDefault();
          const body = { name: f.elements.name.value, description: f.elements.description.value, body: f.elements.body.value, icon: "zap" };
          const b = $("button[type=submit]", f); b.disabled = true; b.classList.add("loading");
          try {
            const r = await api(mode === "edit" ? `/api/agents/skills/${sel}` : "/api/agents/skills", { method: mode === "edit" ? "PUT" : "POST", body });
            await loadSkills(); sel = r.id; mode = "view"; draw(); Auth.toast("Skill saved");
          } catch (x) { $(".err", f).textContent = x.message; b.disabled = false; b.classList.remove("loading"); }
        };
        $("[data-sh=cancel]", f).onclick = () => { mode = "view"; draw(); };
      }
      $("#sh-upload", d).onchange = async e => {
        const file = e.target.files[0]; if (!file) return;
        if (file.size > 20000) return Auth.toast("Skills are limited to 20 KB of text.");
        const text = await file.text();
        const fm = text.match(/^---\s*\n([\s\S]*?)\n---\s*\n?/);
        const meta = Object.fromEntries((fm?.[1] || "").split("\n").map(l => l.match(/^(\w+):\s*(.*)$/)).filter(Boolean).map(m => [m[1], m[2].replace(/^["']|["']$/g, "")]));
        const body = fm ? text.slice(fm[0].length) : text;
        mode = { name: meta.name || file.name.replace(/\.\w+$/, "").replace(/[-_]+/g, " "), description: meta.description || "", body: body.trim() };
        draw();
      };
    };
    d.onclick = async e => {
      const s = e.target.closest("[data-skill]"); if (s) { sel = s.dataset.skill; mode = "view"; return draw(); }
      const k = e.target.closest("[data-sh]")?.dataset.sh;
      if (k === "close" || e.target === d) return d.close();
      if (k === "create") { mode = "create"; draw(); }
      if (k === "edit") { mode = "edit"; draw(); }
      if (k === "delete") {
        const sk = all().find(x => x.id === sel);
        UI.confirm({ title: `Delete the skill${sk ? ` “${esc(sk.name)}”` : ""}?`, body: "Agents using it stop following it. This can't be undone.",
          run: async () => { await api(`/api/agents/skills/${sel}`, { method: "DELETE" }); await loadSkills(); sel = skills.builtin[0]?.id; draw(); Auth.toast("Skill deleted"); } });
      }
    };
    d.onclose = () => { if (page === "editor") refreshSkillPick(); };
    draw(); d.showModal();
  }
  function skillForm(s) {
    const v = typeof s === "object" && s ? s : { name: "", description: "", body: "# Skill name\n\nWhen asked to …, do this:\n\n1. \n2. \n" };
    return `<form id="sh-form" class="sh-form" novalidate>
      <label class="in"><span>Name</span><input name="name" maxlength="60" required value="${esc(v.name)}"></label>
      <label class="in"><span>Description</span><input name="description" maxlength="200" value="${esc(v.description || "")}" placeholder="One line: what this skill teaches"></label>
      <label class="in"><span>Content <em class="opt">Markdown, added to the agent's instructions</em></span><textarea name="body" rows="14" maxlength="20000" required>${esc(v.body)}</textarea></label>
      <p class="err" role="alert"></p>
      <div class="row end"><button type="button" class="btn" data-sh="cancel">Cancel</button><button type="submit" class="btn primary">Save skill</button></div></form>`;
  }
  function refreshSkillPick() {
    const box = $("#editor .skill-pick"); if (!box) return;
    const on = new Set($$("[name=skills]:checked", box).map(x => x.value));
    box.innerHTML = [...skills.builtin, ...skills.custom].map(s => `<label><input type="checkbox" name="skills" value="${esc(s.id)}" ${on.has(s.id) ? "checked" : ""}><span><b>${esc(s.name)}</b><small class="faint">${esc(s.description || "")}</small></span></label>`).join("");
  }

  // ---------- settings (admins) ----------
  const PROVIDER_INFO = {
    anthropic: { name: "Claude", by: "Anthropic API", ph: "sk-ant-…", link: "https://console.anthropic.com/settings/keys", host: "console.anthropic.com" },
    openai: { name: "OpenAI", by: "OpenAI API", ph: "sk-…", link: "https://platform.openai.com/api-keys", host: "platform.openai.com" },
    openrouter: { name: "OpenRouter", by: "Gemini, Llama, DeepSeek, Mistral and more with one key", ph: "sk-or-…", link: "https://openrouter.ai/settings/keys", host: "openrouter.ai" },
    copilot: { name: "GitHub Copilot", by: "Claude, GPT and Gemini on your Copilot plan", ph: "github_pat_…", link: "https://github.com/settings/personal-access-tokens", host: "github.com" },
    local: { name: "Local", by: "Ollama, LM Studio, vLLM or any OpenAI-compatible server" },
    terminal: { name: "Terminal", by: "Claude Code CLI on the server, with its own login" },
    codex: { name: "Codex", by: "OpenAI's Codex CLI on the server, with its ChatGPT login" },
  };
  // Agents → Models (admins): the connected models as a list in the hub's right pane; Add opens a dialog
  // (type → model → name → key / server / CLI settings). The server side is the same provider API as before.
  const MODEL_TYPES = [
    { id: "key", label: "API Key", models: [["anthropic", "Claude"], ["openai", "OpenAI (Codex)"], ["copilot", "GitHub (Copilot)"], ["openrouter", "OpenRouter"]] },
    { id: "cli", label: "CLI", models: [["terminal", "Claude"], ["codex", "OpenAI (Codex)"], ["copilot-cli", "GitHub (Copilot)"]] },
    { id: "local", label: "Local", models: [["local", "Local"]] },
  ];
  // CLI: the token pasted in the Add dialog (the server's login for that CLI), checked with a real prompt before it's saved
  const CLI_TOKEN = {
    terminal: { ph: "sk-ant-oat…", hint: `Run <code>claude setup-token</code> on a machine signed in to your Claude plan and paste the token it prints. It's checked before saving.` },
    codex: { ph: "Access token or sk-…", hint: `A Codex access token, or an OpenAI API key from <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">platform.openai.com</a> (billed to the API, not the ChatGPT plan). It's checked before saving.` },
    "copilot-cli": { ph: "github_pat_…", hint: `Create one at <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer">github.com</a>. Use a fine-grained token (github_pat_…) with Account permissions → Copilot Requests: Read (classic ghp_ tokens don't work). It's checked with api.github.com/user and one real Copilot CLI prompt (one premium request); each agent turn uses the plan's premium requests too.` },
  };
  const DEFAULT_NAME = { anthropic: "Claude", openai: "OpenAI", openrouter: "OpenRouter", local: "Local", terminal: "Claude", codex: "OpenAI", copilot: "GitHub Copilot", "copilot-cli": "GitHub Copilot" };
  const typeOf = p => MODEL_TYPES.find(t => t.models.some(m => m[0] === p)) || MODEL_TYPES[0];
  const modelLabel = p => typeOf(p).models.find(m => m[0] === p)?.[1] || p;
  // display names live in this browser (hub.names): the server keeps no name per provider
  const modelName = p => { const n = (pref("names") || {})[p]; return typeof n === "string" && n.trim() ? n.trim() : DEFAULT_NAME[p] || p; };
  function setModelName(p, v) {
    const all = { ...(pref("names") || {}) }; v = (v || "").trim().slice(0, 60);
    if (v && v !== DEFAULT_NAME[p]) all[p] = v; else delete all[p];
    pref("names", all);
  }
  const LIMIT_RE = /limit|quota|rate.?limit|429|credit|billing|too many requests/i;
  // a model's connection state: `key` colours its card (ok / limit / error / off), `html` is the badge
  function modelStatus(s, p) {
    const st = s.providers[p], cat = s.catalog.find(c => c.id === p);
    if (!st?.configured) return { key: "off", html: `<span class="badge new">Not connected</span>` };
    if (st.off) return { key: "disabled", html: `<span class="badge muted">Off</span>` };  // switched off on its card (model_switch.py): connected, but nothing runs on it
    // the server's Claude Code / Codex plan hit its usage limit (llm.quota_until): runs wait until it resets
    if (st.limit_until * 1000 > Date.now()) return { key: "limit", html: `<span class="badge caution">${icon("alert")}Limit reached · until ${esc(new Date(st.limit_until * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}</span>` };
    if (cat?.error) return LIMIT_RE.test(cat.error) ? { key: "limit", html: `<span class="badge caution">${icon("alert")}Limit reached</span>` }
      : { key: "error", html: `<span class="badge avoid">${icon("alert")}Cannot be used</span>` };
    return { key: "ok", html: `<span class="badge clear">${icon("check")}Connected</span>` };
  }
  // the on/off switch in a card's header (model_switch.py): off keeps the key/token/login, but no agent, chat or team runs on it
  const switchHtml = (name, on) => `<label class="mdl-switch" title="${on ? "On: agents can use this model. Switch off to stop using it" : "Off: nothing runs on this model. Switch on to use it again"}">
    <span class="switch"><input type="checkbox" data-switch ${on ? "checked" : ""} aria-label="Use ${esc(name)}"><span></span></span></label>`;
  // `send(on)` saves it and answers with { message }; the page redraws after
  function wireSwitch(f, send, relist) {
    const box = $("[data-switch]", f); if (!box) return;
    box.onchange = async () => {
      const on = box.checked; box.disabled = true;
      try { const r = await send(on); modelsChanged(r.message, relist); }
      catch (x) { box.checked = !on; box.disabled = false; Auth.toast(x.message); }
    };
  }
  // The models a card's login offers: a few of them, and Show more for the whole list (kept open across redraws).
  // OpenRouter's free models carry a "free" tag.
  const FEW = 4, openLists = new Set();
  const moreLabel = (open, n) => open ? "Show less" : `Show more (${n - FEW} more)`;
  function modelsRow(key, models) {
    if (!models?.length) return "";
    const open = openLists.has(key);
    return `<div class="mdl-models${open ? " open" : ""}" data-models="${esc(key)}">
      <span class="mdl-models-h">Supported models · ${models.length}</span>
      <div class="mdl-chips">${models.map(m => `<span class="mdl-chip">${esc(m.label)}${m.free ? `<em>free</em>` : ""}</span>`).join("")}</div>
      ${models.length > FEW ? `<button type="button" class="linkbtn mdl-more" data-more aria-expanded="${open}">${moreLabel(open, models.length)}</button>` : ""}</div>`;
  }
  function wireModelsRow(f) {
    const box = $("[data-models]", f), b = box && $("[data-more]", box);
    if (b) b.onclick = () => {
      const key = box.dataset.models, open = !openLists.has(key);
      open ? openLists.add(key) : openLists.delete(key);
      box.classList.toggle("open", open); b.setAttribute("aria-expanded", open);
      b.textContent = moreLabel(open, $$(".mdl-chip", box).length);
      if (!open) $(".mdl-chips", box).scrollTop = 0;
    };
  }
  // a provider's models without the named logins' (each has its own card)
  const ownModels = (s, p) => (s.catalog.find(c => c.id === p)?.models || []).filter(m => !(s.logins || []).some(l => l.model === m.id));
  const modelDetail = (s, p) => {
    const st = s.providers[p] || {};
    return `${p === "local" ? esc(st.url || "") : (p === "terminal" || p === "codex") && !st.masked ? `<code>${esc(st.cli || (p === "codex" ? "codex" : "claude"))}</code>` : esc(st.masked || "")}${st.source === "env" ? " · from the server environment" : ""}`;
  };

  // a named Claude Code login on the server (Claude-37 on CLAUDE_CODE_OAUTH_TOKEN1, llm.TERMINAL_LOGINS): its own card,
  // offered in the model pickers as "terminal:<id>". Its token comes from the server environment (.env), so there's no
  // trash; its state is the last real check (Test: one tiny prompt), since a token being set proves nothing
  const loginKey = l => `terminal:${l.id}`;
  function loginState(l) {
    const c = l.check;
    if (!l.configured) return { key: "off", html: `<span class="badge new">Not connected</span>` };
    if (l.off) return { key: "disabled", html: `<span class="badge muted">Off</span>` };
    if (!c) return { key: "off", html: `<span class="badge new">Not checked yet</span>` };
    if (c.kind === "limit") return { key: "limit", html: `<span class="badge caution">${icon("alert")}Limit reached</span>` };
    if (c.kind === "error") return { key: "error", html: `<span class="badge avoid">${icon("alert")}Cannot be used</span>` };
    return { key: "ok", html: `<span class="badge clear">${icon("check")}Connected</span>` };
  }
  function loginCard(l, s) {
    const p = loginKey(l), st = loginState(l), c = l.check;
    DEFAULT_NAME[p] = l.label;  // the pencil renames it in this browser, like any card
    const alias = l.alias ? l.alias[0].toUpperCase() + l.alias.slice(1) : "";
    const checked = c ? `Checked ${esc(new Date(c.at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}.` : "";
    const how = "The refresh button on Usage checks this login with one tiny prompt (uses a little of its plan).";
    const note = !l.configured ? `Run <code>claude setup-token</code> on a machine signed in to the Claude plan, put the token in <code>.env</code> as <code>${esc(l.var)}</code> and redeploy.`
      : !c ? `Not checked yet. ${how}`
      : c.error ? `${checked} ${esc(c.error)}` : `${checked} Agents can pick it as ${esc(l.label)} in the model menu. ${how}`;
    const model = (s?.catalog.find(x => x.id === "terminal")?.models || []).filter(m => m.id === l.model);
    return `<form class="mdl-card" data-login="${esc(l.id)}" data-state="${st.key}" novalidate>
      <div class="mdl-card-head">${Chat.providerIcon("terminal:")}
        <div class="mdl-main">${nameBox(p)}<small class="faint">CLI · Claude${alias ? ` · ${esc(alias)}` : ""} · <code>${esc(l.var)}</code>${l.masked ? ` · ${esc(l.masked)}` : ""} · from the server environment</small></div>
        ${st.html}${l.configured ? switchHtml(modelName(p), !l.off) : ""}</div>
      ${l.off ? "" : modelsRow(p, model.length ? model : [{ id: l.model, label: `${l.label}${alias ? ` (${alias})` : ""}` }])}
      ${l.configured ? `<div class="mdl-usage" data-usage></div>` : ""}
      ${c?.error ? `<p class="no small mdl-login-note">${note}</p>` : `<small class="hint">${note}</small>`}
      <p class="err" role="alert"></p>
    </form>`;
  }
  // `s`: the Models page's settings (updated in place); `usage`: the card's Usage box to keep when it's redrawn
  function wireLoginCard(s, f, usage) {
    const id = f.dataset.login, p = loginKey({ id });
    hydrateIcons(f); wireModelsRow(f); tipify(f);
    const box = $("[data-usage]", f);
    if (box && usage) box.replaceWith(usage);
    // the Usage refresh also checks the login with one tiny prompt: its state (badge, colours) only comes from a real check
    // (the Usage box is kept across redraws, so this looks up the card that's on the page now)
    else if (box && typeof PlanUsage !== "undefined") PlanUsage.render(box, p, { onAgain: async () => {
      const now = () => page === "settings" ? $(`.mdl-card[data-login="${id}"]`) : null;
      const e0 = now() && $(".err", now()); if (e0) e0.textContent = "";
      try {
        const r = await api(`/api/agents/settings/login/${encodeURIComponent(id)}/test`, { method: "POST" });
        Object.assign(s, r); Auth.toast(r.message);
        const cur = now();
        if (cur) { const t = document.createElement("div"); t.innerHTML = loginCard(s.logins.find(x => x.id === id), s);
          const nf = t.firstElementChild, keep = $("[data-usage]", cur); cur.replaceWith(nf); wireLoginCard(s, nf, keep); }
        Chat.loadModels();
      } catch (x) { const cur = now(); if (cur) $(".err", cur).textContent = x.message; }
    } });
    wireSwitch(f, on => api("/api/agents/settings/switch", { method: "POST", body: { key: `login:${id}`, on } }), "terminal");
    f.onsubmit = e => e.preventDefault();
    f.onclick = e => { if (e.target.closest("[data-rename]")) renameModel(f, p); };
  }

  // A Claude Code / Codex login added by website sign-in (Add model → CLI → Login: Website sign-in; cli_accounts.py): a card
  // in the same list. Your runs use it first; everyone on the site may use it (cli_accounts.pick). The trash removes it.
  const OWN = { terminal: { name: "My Claude Code", label: "Claude", plan: "Claude plan" }, codex: { name: "My Codex", label: "OpenAI (Codex)", plan: "ChatGPT plan" } };
  function ownState(st) {
    if (st.off) return { key: "disabled", html: `<span class="badge muted">Off</span>` };
    if (!st.ok) return { key: "error", html: `<span class="badge avoid">${icon("alert")}Cannot be used</span>` };
    if (st.limit_until) return { key: "limit", html: `<span class="badge caution">${icon("alert")}Limit reached · until ${esc(new Date(st.limit_until * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}</span>` };
    return { key: "ok", html: `<span class="badge clear">${icon("check")}Connected</span>` };
  }
  function ownCard(s, p, st) {
    const key = `own:${p}`, o = OWN[p], state = ownState(st);
    DEFAULT_NAME[key] = o.name;
    return `<form class="mdl-card has-trash" data-own="${p}" data-state="${state.key}" novalidate>
      <div class="mdl-card-head">${Chat.providerIcon(p + ":")}
        <div class="mdl-main">${nameBox(key)}<small class="faint">CLI · ${esc(o.label)} · Website sign-in · shared with everyone</small></div>
        ${state.html}${switchHtml(modelName(key), !st.off)}</div>
      <button type="button" class="iconbtn sm mdl-trash" data-remove title="Remove" aria-label="Remove ${esc(modelName(key))}">${icon("trash")}</button>
      ${st.off ? "" : modelsRow(key, ownModels(s, p))}
      <div class="mdl-usage" data-usage></div>
      ${st.error ? `<p class="no small">${esc(st.error)}</p>` : ""}
      <small class="hint">Added by website sign-in on your ${esc(o.plan)}, with its own usage limit. Everyone on the site may use these models: your own agents, chats and teams run on it first, and teammates use it when the token login is off or at its limit. It's stored encrypted on the server.</small>
      <div class="mdl-body" data-body>${modeField(p)}${parField(p, s.providers[p] || {})}</div>
      <p class="err" role="alert"></p>
    </form>`;
  }
  // `s`: the Models page's settings. Usage reads this login's own plan; Tool calls and Runs at once are the provider's
  // settings (the same ones the server login's card shows: they apply to every login of that CLI)
  function wireOwnCard(s, f) {
    const p = f.dataset.own, key = `own:${p}`;
    hydrateIcons(f); wireModelsRow(f); tipify(f);
    if (typeof PlanUsage !== "undefined") PlanUsage.render($("[data-usage]", f), key);
    wireModelFields(s, f, { p, card: true, own: true });
    wireSwitch(f, on => api(`/api/cli-accounts/${p}/switch`, { method: "POST", body: { on } }), p);
    f.onsubmit = e => e.preventDefault();
    f.onclick = e => {
      if (e.target.closest("[data-rename]")) return renameModel(f, key);
      if (e.target.closest("[data-remove]")) UI.confirm({
        title: `Remove ${esc(modelName(key))}?`, body: "Your login is deleted from the server. Your runs on these models use the server's login (or a teammate's shared one) until you connect it again.", ok: "Remove", icon: "ban",
        run: async () => { const r = await api(`/api/cli-accounts/${p}`, { method: "DELETE" }); modelsChanged(r.message, p); } });
    };
  }

  async function settings() {
    showHub();
    page = "settings"; conv = null;
    $$("#view-agents .hub-side [data-hub]").forEach(b => b.setAttribute("aria-current", "false"));
    $("#hub-settings").setAttribute("aria-current", "page");
    const d = $("#hub-main");
    const top = `<div class="hub-top"><div><h1 class="page">Models</h1><p class="lead">Connected models, the default model and who can use agents.</p></div></div>`;
    if (!d.querySelector(".settings-page")) d.innerHTML = `${top}<div class="settings-dlg settings-page">${Loading.line("Loading models…")}</div>`;
    let s, mine;
    try { [s, mine] = await Promise.all([api("/api/agents/settings"), api("/api/cli-accounts").catch(() => null)]); } catch (e) { d.innerHTML = `${top}<div class="settings-dlg settings-page"><p class="err">${esc(e.message)}</p></div>`; return; }
    if (page !== "settings") return;  // moved on while it loaded
    const own = Object.keys(OWN).filter(p => mine?.providers?.[p]?.connected);
    const connected = MODEL_TYPES.flatMap(t => t.models.map(m => m[0])).filter(p => s.providers[p]?.configured);
    // each connected model is a card with its settings on it (no separate settings window); the pencil renames it.
    // Nothing on a card needs a Save: each setting saves when it changes, the brown trash (top right) removes the model,
    // and its border and name follow the connection state (data-state)
    const card = p => {
      const stt = modelStatus(s, p), rm = s.providers[p]?.source === "ui", acts = modelButtons(s, p, true);
      return `<form class="mdl-card${rm ? " has-trash" : ""}" data-mdl="${p}" data-state="${stt.key}" novalidate>
      <div class="mdl-card-head">${Chat.providerIcon(p + ":")}
        <div class="mdl-main">${nameBox(p)}<small class="faint">${esc(typeOf(p).label)} · ${esc(modelLabel(p))}${modelDetail(s, p) ? ` · ${modelDetail(s, p)}` : ""}</small></div>
        ${stt.html}${switchHtml(modelName(p), !s.providers[p]?.off)}</div>
      ${stt.key === "ok" ? modelsRow(p, ownModels(s, p)) : ""}
      ${rm ? `<button type="button" class="iconbtn sm mdl-trash" data-remove title="Remove" aria-label="Remove ${esc(modelName(p))}">${icon("trash")}</button>` : ""}
      <div class="mdl-usage" data-usage></div>
      <div class="mdl-body" data-body>${modelBody(s, p, typeOf(p).id, true)}</div>
      <p class="err" role="alert"></p>
      ${acts ? `<div class="row end mdl-actions">${acts}</div>` : ""}
    </form>`;
    };
    d.innerHTML = `${top}<div class="settings-dlg settings-page">
      <div class="mdl-head"><h4>Models</h4><button type="button" class="btn primary sm" data-mdl-add>${icon("plus")}Add model</button></div>
      <div class="mdl-list">${connected.length || s.logins?.length || own.length ? connected.map(card).join("") + (s.logins || []).map(l => loginCard(l, s)).join("") + own.map(p => ownCard(s, p, mine.providers[p])).join("") : `<div class="mdl-empty"><p class="muted">No model connected yet. Agents run on Claude, OpenAI, any model on OpenRouter, a model on your own server, or the Claude Code / Codex CLI signed in on the server.</p></div>`}</div>
      <h4 data-tip-at>Default model</h4>
      <small class="hint" data-tip-to="h4">Used when someone leaves the model picker on Auto. Automatic runs Claude when it's connected, else the first model any connected login offers.</small>
      <button type="button" class="mdl-default" id="sd-default" aria-haspopup="dialog">${defaultLabel(s)}<span class="mdl-default-go">Change${icon("down")}</span></button>
      <h4>Access</h4>
      <label class="toggle-row"><span><b>Members can use agents</b><small class="hint" data-tip-to="b">Non-admins can build and chat with custom agents. Chats use your connected providers' credits.</small></span>
        <span class="switch"><input type="checkbox" id="members-on" ${s.members_allowed ? "checked" : ""}><span></span></span></label>
    </div>`;
    hydrateIcons(d);
    $$("[data-mdl-add]", d).forEach(b => b.onclick = () => modelDialog(s));
    // usage = the card's Usage box when the card is redrawn (kept as it is, no second read)
    const wireCard = (f, usage) => {
      const p = f.dataset.mdl, ctx = { p, type: typeOf(p).id, card: true, rename: () => renameModel(f, p) };
      $$(".eye", f).forEach(b => b.innerHTML = icon("eye")); hydrateIcons(f); wireModelsRow(f); tipify(f);
      if (usage) $("[data-usage]", f).replaceWith(usage);
      else if (typeof PlanUsage !== "undefined") PlanUsage.render($("[data-usage]", f), p, { onAgain: () => refreshCard(p) });  // 5-hour / weekly / monthly use of the plan
      wireModelFields(s, f, ctx); wireModelActions(s, f, ctx);
      wireSwitch(f, on => api("/api/agents/settings/switch", { method: "POST", body: { key: p, on } }), p);
    };
    // the refresh button on a card's Usage also lists the model again, so its state badge, supported models,
    // colours, subtitle and error line are redrawn, not only the usage numbers
    const refreshCard = async p => {
      let r;
      try { r = await api(`/api/agents/settings?refresh=${encodeURIComponent(p)}`); } catch (e) { Auth.toast(e.message); return; }
      const f = $(`.mdl-card[data-mdl="${p}"]`, d);
      if (page !== "settings" || !f) return;
      Object.assign(s, r);  // the same object every handler on the page reads
      const t = document.createElement("div"); t.innerHTML = card(p);
      const nf = t.firstElementChild, usage = $("[data-usage]", f);
      f.replaceWith(nf); wireCard(nf, usage);
      Chat.loadModels();  // the model pickers follow
    };
    $$(".mdl-card[data-mdl]", d).forEach(f => wireCard(f));
    $$(".mdl-card[data-login]", d).forEach(f => wireLoginCard(s, f));
    $$(".mdl-card[data-own]", d).forEach(f => wireOwnCard(s, f));
    tipify($(".settings-page", d));
    $("#sd-default").onclick = () => defaultDialog(s);
    $("#members-on").onchange = async e => {
      const want = e.target.checked;
      try { await Admin.withSudo(() => api("/api/agents/settings/members", { method: "POST", body: { allowed: want } })); Auth.toast(want ? "Members can now use agents" : "Agents are admin-only again"); }
      catch (x) { e.target.checked = !want; if (x.message !== "cancelled") Auth.toast(x.message); }
    };
  }
  // after a change: close the dialog, reload the model menus and the hub, and redraw the Models page if it's still open
  async function modelsChanged(msg, relist) {
    if (msg) Auth.toast(msg);
    if (relist) await api(`/api/agents/settings?refresh=${encodeURIComponent(relist)}`).catch(() => {});  // list that provider again
    const dlg = $("#agentdlg"); if (dlg.open && dlg.querySelector(".mdl-dlg")) dlg.close();
    await Promise.all([Chat.loadModels(), api("/api/agents/hub").then(h => { hub = h; }).catch(() => {})]);
    if (page === "settings") settings();
  }

  // the name on a model's card, with a pencil to rename it (names live in this browser, see modelName)
  const nameBox = p => `<div class="mdl-name"><span class="mdl-name-box" data-name>${nameHtml(p)}</span></div>`;
  const nameHtml = p => `<b>${esc(modelName(p))}</b><button type="button" class="iconbtn sm mdl-rename" data-rename title="Rename" aria-label="Rename ${esc(modelName(p))}">${icon("edit")}</button>`;
  function renameModel(f, p) {
    const box = $("[data-name]", f); if (!box || $("input", box)) return;
    const was = modelName(p);
    box.innerHTML = `<input class="mdl-name-in" maxlength="60" autocomplete="off" spellcheck="false" aria-label="Name">`;
    const i = $("input", box); i.value = was; i.focus(); i.select();
    let done = false;
    const finish = save => {
      if (done) return; done = true;
      if (save) setModelName(p, i.value);
      box.innerHTML = nameHtml(p); hydrateIcons(box);
      $("[data-rename]", box).focus({ preventScroll: true });
      if (save && modelName(p) !== was) Auth.toast("Name saved");
    };
    i.onkeydown = e => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }  // renames, doesn't submit the card
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    };
    i.onblur = () => finish(true);
  }

  // one model's settings: key / token / server fields, a CLI's run settings and its buttons.
  // Used on the Models list's cards (card = true) and in the Add dialog.
  const parField = (p, st) => `<label class="in"><span>Runs at once, per login</span>
      <input type="number" data-par data-par-p="${p}" min="1" max="${st.parallel_max || 24}" step="1" value="${st.parallel || 2}" inputmode="numeric">
      <small class="hint">AXoR's limit, not ${p === "codex" ? "OpenAI's" : "Anthropic's"}: one login can run many at once. Higher finishes parallel work sooner but uses the plan's usage window sooner (your own ${p === "codex" ? "Codex" : "Claude Code"} shares it), and each run is a CLI process on the server (about 300 MB): the pod has room for about 24. Applies to the server's login and everyone's own, right away. Default ${st.parallel_default || 2}.</small></label>`;
  const modeField = p => p === "terminal" ? `<label class="in"><span>Tool calls</span><select data-tmode>
        <option value="text">Written as text, one CLI run per turn</option><option value="mcp">Native, one session per run (faster, cached)</option></select>
        <small class="hint">Native gives agents real tool calls through a private MCP connection and keeps the conversation in one Claude Code session.</small></label>`
    : `<label class="in"><span>Tool calls</span><select data-cmode>
        <option value="mcp">Native, one session per run (faster, cached)</option><option value="text">Written as text, one CLI run per turn</option></select>
        <small class="hint">Native gives agents real tool calls through a private MCP connection and keeps the conversation in one Codex session. Codex reports tokens when the run ends.</small></label>`;
  // the same key field for API keys and CLI tokens: password input + show/hide, one hint line
  const keyField = (label, opt, ph, hint) => `<label class="in"><span>${label}${opt ? ` <em class="opt">optional</em>` : ""}</span><div class="pw"><input name="key" type="password" placeholder="${esc(ph)}" autocomplete="off" spellcheck="false"><button type="button" class="eye" aria-label="Show"></button></div>
        <small class="hint">${hint}</small></label>`;
  function modelBody(s, p, type, card) {
    const info = PROVIDER_INFO[p];
    const localHint = `Ollama: <code>http://host.docker.internal:18100/v1</code> · LM Studio: <code>…:1234/v1</code>. Start the container with <code>--add-host=host.docker.internal:host-gateway</code> to reach this machine.`;
    if (!card) {  // Add model: only what a new model needs. Nothing about a model that's already connected is shown here
      if (type === "cli") return keyField("Token", false, CLI_TOKEN[p].ph, CLI_TOKEN[p].hint);
      if (p === "local") return `<label class="in"><span>Server URL</span><input name="url" placeholder="http://host.docker.internal:18100/v1" spellcheck="false" autocomplete="off"></label>
        <label class="in"><span>API key <em class="opt">optional</em></span><input name="key" type="password" autocomplete="off" spellcheck="false" placeholder="Only if your server needs one"></label>
        <small class="hint">${localHint}</small>`;
      return keyField("API key", false, info.ph, `Create one at <a href="${info.link}" target="_blank" rel="noopener noreferrer">${info.host}</a>. It's checked before saving.`);
    }
    // a connected model's card: its error (in sight) and the settings that can change; explanations go behind a "?"
    const st = s.providers[p] || {};
    const err = s.catalog.find(c => c.id === p)?.error;
    const errLine = err ? `<p class="no small">${esc(err)}</p>` : "";
    if (type === "cli") return `${errLine}
          ${p === "copilot-cli" ? `<small class="hint">Runs GitHub's Copilot CLI with this token (COPILOT_GITHUB_TOKEN), tools off; agents' tool calls are written as text. Copilot · Auto lets Copilot pick a model the plan offers.</small>`
            : `${modeField(p)}${parField(p, st)}`}`;
    if (p === "local") return `${errLine}<label class="in"><span>Server URL</span><input name="url" placeholder="http://host.docker.internal:18100/v1" value="${esc(st.url || "")}" spellcheck="false" autocomplete="off"></label>
        <small class="hint">Saved and checked as soon as you change it. ${localHint}</small>`;
    return errLine;  // a connected key model has nothing to change on its card
  }
  function modelButtons(s, p, card) {
    if (card) return "";  // no Save (each setting saves on change), no Remove (the trash in the card's corner), no Test
    return `<span class="mdl-gap"></span><button type="button" class="btn sm" data-close>Cancel</button>
        <button type="submit" class="btn primary sm">Connect</button>`;
  }
  // show/hide, Tool calls and Runs at once of the form's model (ctx.p); rerun after the form's fields are redrawn
  function wireModelFields(s, f, ctx) {
    const p = ctx.p, st = ctx.card ? s.providers[p] || {} : {};
    // the server login's card and your own login's card show the same provider setting: keep the other one in step
    const sync = (q, from) => { if (ctx.card) $$(`.settings-page .mdl-card ${q}`).forEach(x => { if (x !== from) x.value = from.value; }); };
    $(".eye", f)?.addEventListener("click", () => { const i = f.elements.key; i.type = i.type === "password" ? "text" : "password"; });
    const mode = (sel, prov, path, fallback, on, off) => {
      if (!sel) return;
      sel.value = s.providers[prov].mode || fallback;
      sel.onchange = async () => {
        if (!st.configured && !ctx.own) { ctx.pendingMode = { path, mode: sel.value }; return; }  // sent once Connect works
        try { await api(path, { method: "POST", body: { mode: sel.value } }); s.providers[prov].mode = sel.value; Auth.toast(sel.value === "mcp" ? on : off);
          sync(sel.matches("[data-tmode]") ? "[data-tmode]" : "[data-cmode]", sel); }
        catch (x) { sel.value = s.providers[prov].mode || fallback; Auth.toast(x.message); }
      };
    };
    mode($("[data-tmode]", f), "terminal", "/api/agents/settings/terminal-mode", "text", "Terminal agents now use native tool calls", "Terminal agents write tool calls as text again");
    mode($("[data-cmode]", f), "codex", "/api/agents/settings/codex-mode", "mcp", "Codex agents now use native tool calls", "Codex agents write tool calls as text");
    const pn = $("[data-par]", f);
    if (pn) pn.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); pn.blur(); } };  // saves, doesn't submit
    if (pn) pn.onchange = async () => {
      const n = Math.round(+pn.value), was = s.providers[p].parallel;
      if (!(n >= 1 && n <= (s.providers[p].parallel_max || 24))) { pn.value = was; Auth.toast(`Pick 1 to ${s.providers[p].parallel_max || 24}.`); return; }
      try { const r = await api("/api/agents/settings/parallel", { method: "POST", body: { provider: p, n } }); s.providers[p].parallel = r.providers[p].parallel; Auth.toast(`${modelName(p)}: ${n} at once per login`);
        sync(`[data-par][data-par-p="${p}"]`, pn); }
      catch (x) { pn.value = was; Auth.toast(x.message); }
    };
  }
  // Connect (Add dialog), a card's Server URL and Remove of the form's model. ctx: { p, type, pendingMode, name?, close?, rename? }
  function wireModelActions(s, f, ctx) {
    const err = $(".err", f);
    // the same check-before-save provider call as before
    const connect = async (btn, key, url) => {
      const p = ctx.p;
      err.textContent = ""; btn.disabled = true; btn.classList.add("loading");
      try {
        const r = await Admin.withSudo(() => api("/api/agents/settings/provider", { method: "POST", body: { provider: p, key: key || null, url: url || null } }));
        if (ctx.pendingMode) await api(ctx.pendingMode.path, { method: "POST", body: { mode: ctx.pendingMode.mode } }).catch(x => Auth.toast(x.message));
        if (ctx.name) setModelName(p, ctx.name());
        modelsChanged(r.message);
      } catch (x) { if (x.message !== "cancelled" && document.body.contains(f)) err.textContent = x.message; }
      finally { btn.disabled = false; btn.classList.remove("loading"); }
    };
    if (ctx.card && ctx.p === "local") {  // the card's Server URL: saved and checked as soon as it changes
      const u = f.elements.url;
      u.onchange = () => {
        const v = u.value.trim(), was = s.providers.local?.url || "";
        if (!v) { u.value = was; err.textContent = "Enter your server's URL."; return; }
        if (v !== was) connect(u, null, v);  // no key sent: the saved one stays
      };
    }
    f.onsubmit = async e => {
      e.preventDefault();
      if (ctx.card) { f.elements.url?.blur(); return; }  // Enter in a card's field: blurring saves it
      if (ctx.mine?.()) return;  // Add → CLI → Login: Website sign-in: its own Connect opens the sign-in page (ownConnect)
      const p = ctx.p, btn = $("button[type=submit]", f);
      const key = f.elements.key?.value.trim(), url = f.elements.url?.value.trim();
      err.textContent = "";
      if (p === "local" && !url) { err.textContent = "Enter your server's URL."; return; }
      if (p !== "local" && !key) { err.textContent = ctx.type === "cli" ? "Paste a token first." : "Paste an API key first."; return; }
      connect(btn, key, url);
    };
    f.onclick = e => {
      const p = ctx.p;
      if (e.target.closest("[data-rename]")) return ctx.rename?.();
      if (e.target.closest("[data-close]")) return ctx.close?.();
      if (e.target.closest("[data-remove]")) return UI.confirm({
        title: `Disconnect ${esc(modelName(p))}?`, body: "Its saved key is deleted, and agents using its models stop answering until you connect it again.", ok: "Disconnect", icon: "ban",
        run: async () => { await Admin.withSudo(() => api(`/api/agents/settings/provider/${p}`, { method: "DELETE" })); modelsChanged(`${modelName(p)} disconnected`); } });
    };
  }

  // The Models page's and the Add dialog's explanations as "?" icons: each hint is hidden (pagetip.css .ptip-src) and a
  // "?" goes after its field's label; hovering, focusing or pressing it shows the text in a framed tip (pagetip.js, which
  // also places the tip inside an open dialog). A loose hint goes to the first field above it, to the element it names
  // (data-tip-to: the nearest such element before it) or, on a card, after the card's name.
  let tipSeq = 0;
  function tipOne(src, at) {
    if (!src || !at || src.classList.contains("ptip-src") || !src.textContent.trim()) return;
    src.id ||= `mdl-tip${++tipSeq}`; src.classList.add("ptip-src");
    at.insertAdjacentHTML("beforeend", `<button type="button" class="ptip-btn mdl-tipbtn" data-ptip-for="${src.id}" aria-label="About this" aria-describedby="${src.id}" aria-expanded="false">${icon("help")}</button>`);
  }
  function tipify(root) {
    $$("label.in", root).forEach(l => tipOne($(":scope > small.hint", l), $(":scope > span", l)));
    $$("small.hint", root).filter(h => !h.classList.contains("ptip-src")).forEach(h => {
      const before = x => x.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING;
      const to = h.dataset.tipTo && $$(h.dataset.tipTo, h.parentElement).filter(before).pop();
      const l = $$("label.in > span", h.parentElement).find(x => before(x.closest("label")));
      tipOne(h, to || l || $(".mdl-name", h.closest(".mdl-card")));
    });
  }

  // Add model → CLI → Login: Website sign-in: Connect opens the provider's own sign-in page in a new tab, the server follows the
  // sign-in (cli_accounts.py) and, once it's through, the login is saved and the model appears in the list.
  // Claude: its page ends on a code, pasted here. Codex: the page asks for the code shown here.
  // The tab is opened inside the click (a tab opened later is blocked as a pop-up) and sent to the link when it arrives.
  function ownConnect(box, p, done) {
    const who = p === "codex" ? "ChatGPT" : "Claude", base = `/api/cli-accounts/${p}`;
    let tab = null, timer = null, shown = "", open = false, gone = false;
    const live = () => !gone && box.isConnected;
    const post = (path, body) => api(base + path, { method: "POST", body });
    const stop = () => { clearTimeout(timer); timer = null; };
    const leave = () => { stop(); if (open) post("/cancel").catch(() => {}); open = false; };  // the dialog closed mid sign-in
    const idle = error => {
      stop(); shown = "";
      box.innerHTML = `<div class="mdl-own-row"><button type="button" class="btn primary" data-own-go>${icon("external")}Connect</button>
          <span class="mdl-own-what">Sign in with your own ${who} plan<span data-own-tip></span></span></div>
        <small class="hint">Connect opens ${who}'s sign-in page in a new tab. ${p === "codex"
          ? "Sign in there with your ChatGPT account and enter the code shown here."
          : "Sign in there with your Claude account, then paste the code its last page shows here."}
          The login is checked, stored encrypted on the server and can be used by everyone on the site. You can remove it from its card at any time.</small>
        <p class="err small" role="alert">${error ? esc(error) : ""}</p>`;
      hydrateIcons(box);
      tipOne($("small.hint", box), $("[data-own-tip]", box));
      $("[data-own-go]", box).onclick = go;
    };
    const send = url => {
      if (tab && !tab.closed) { try { tab.opener = null; tab.location.replace(url); return true; } catch (e) { /* fall through to the link */ } }
      return false;
    };
    const linkLine = (url, sent) => `<p class="small">${sent ? `${who}'s sign-in page is open in a new tab.` : `Your browser didn't open the tab.`}
        <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${sent ? "Open it again" : `Open ${who}'s sign-in page`}</a></p>`;
    const waiting = L => {
      const key = `${L.url}|${L.code || ""}|${L.code_sent ? 1 : 0}`;
      if (key === shown) return;
      const sent = shown ? box.dataset.sent === "1" : send(L.url);
      shown = key; box.dataset.sent = sent ? "1" : "0";
      if (p === "codex") {
        box.innerHTML = `${linkLine(L.url, sent)}
          <p class="small">Enter this code there (it expires in ${Math.max(1, Math.ceil(L.expires_in / 60))} min):</p>
          <div class="mdl-own-code"><code>${esc(L.code)}</code><button type="button" class="btn sm" data-own-copy>${icon("copy")}Copy</button></div>
          ${Loading.line("Waiting for you to finish signing in…")}
          <p class="err small" role="alert"></p>`;
        $("[data-own-copy]", box).onclick = async () => { try { await navigator.clipboard.writeText(L.code); Auth.toast("Code copied"); } catch (e) { Auth.toast(L.code); } };
      } else if (L.code_sent) {
        box.innerHTML = Loading.line("Checking your sign-in with one short prompt…");
      } else {
        box.innerHTML = `${linkLine(L.url, sent)}
          <label class="in"><span>Code from ${who}'s page</span><input data-own-code autocomplete="off" spellcheck="false" placeholder="Paste the code the page shows after you sign in"></label>
          <div class="mdl-own-row"><button type="button" class="btn primary sm" data-own-finish>Finish</button></div>
          <p class="err small" role="alert"></p>`;
        const i = $("[data-own-code]", box), b = $("[data-own-finish]", box), err = $(".err", box);
        const finish = async () => {
          const code = i.value.trim();
          if (!code) { err.textContent = "Paste the code first."; return; }
          err.textContent = ""; b.disabled = true; b.classList.add("loading");
          try { const r = await post("/code", { code }); if (live()) step(r.login); }
          catch (x) { if (live()) { err.textContent = x.message; b.disabled = false; b.classList.remove("loading"); } }
        };
        b.onclick = finish;
        i.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); finish(); } };
        i.focus();
      }
      hydrateIcons(box);
    };
    // one look at the sign-in's state; polls while it's open
    const step = L => {
      stop();
      if (!live()) return leave();
      if (!L) return idle("The sign-in isn't open any more. Press Connect to start again.");
      if (L.state === "done") { open = false; return done(p === "codex" ? "Your Codex is connected: your runs on Codex models use your own plan." : "Your Claude Code is connected: your runs on Claude Code models use your own plan.", p); }
      if (L.state === "failed" || L.state === "expired" || L.state === "cancelled") { open = false; if (tab && !tab.closed && !shown) tab.close(); return idle(L.error || "The sign-in didn't finish. Press Connect to start again."); }
      if (L.url && (p !== "codex" || L.code)) waiting(L);
      timer = setTimeout(async () => {
        if (!live()) return leave();
        try { step((await api("/api/cli-accounts")).providers[p].login); } catch (e) { step(L); }
      }, p === "codex" || L.code_sent ? 2500 : 4000);
    };
    const go = async () => {
      tab = window.open("about:blank", "_blank");
      try { tab.document.title = `${who} sign-in`; tab.document.body.textContent = `Opening ${who}'s sign-in page…`; } catch (e) { /* blocked: the link is shown instead */ }
      box.innerHTML = Loading.line(`Opening ${who}'s sign-in page…`);
      open = true;
      try { const r = await post("/start"); if (live()) step(r.login); else leave(); }
      catch (x) { open = false; if (tab && !tab.closed) tab.close(); if (live()) idle(x.message); }
    };
    idle();
    return () => { if (gone) return; gone = true; leave(); };  // leaving the sign-in: stop polling, cancel it on the server
  }

  // The default model: a dialog instead of one long menu. First the connected model (the same names as the cards),
  // then what it offers; OpenRouter's are split into paid and free. Picking one saves it.
  const defaultRows = s => [
    ...s.catalog.filter(c => ownModels(s, c.id).length).map(c => ({ id: c.id, icon: c.id + ":", name: modelName(c.id), sub: `${typeOf(c.id).label} · ${modelLabel(c.id)}`, models: ownModels(s, c.id) })),
    ...(s.logins || []).filter(l => l.configured).map(l => ({ id: loginKey(l), icon: "terminal:", name: modelName(loginKey(l)), sub: "CLI · Claude · from the server environment", pick: l.model })),
  ];
  function defaultLabel(s) {
    const id = s.default_choice && s.default_choice === s.default_model ? s.default_model : null;  // a pick that's still offered
    const m = id && s.catalog.flatMap(c => c.models).find(x => x.id === id);
    if (!m) return `<span class="prov prov-auto" aria-hidden="true">${icon("zap")}</span><span class="mdl-default-txt"><b>Automatic</b><small class="faint">Claude when connected</small></span>`;
    const row = defaultRows(s).find(r => r.pick === id || r.models?.some(x => x.id === id));
    return `${Chat.providerIcon(id)}<span class="mdl-default-txt"><b>${esc(m.label)}</b><small class="faint">${esc(row?.name || "")}${m.free ? " · free" : ""}</small></span>`;
  }
  function defaultDialog(s) {
    const d = $("#agentdlg"), rows = defaultRows(s);
    const cur = s.default_choice && s.default_choice === s.default_model ? s.default_model : "auto";
    const save = async id => {
      try { await api("/api/agents/settings/default-model", { method: "POST", body: { model: id } }); modelsChanged("Default model saved"); }
      catch (e) { const err = $(".err", d); if (err) err.textContent = e.message; else Auth.toast(e.message); }
    };
    const shell = (title, back, body) => {
      d.innerHTML = `<div class="settings-dlg mdl-dlg mdl-pickdlg">
        <div class="sd-head"><h3>${back ? `<button type="button" class="iconbtn sm mdl-back" data-back aria-label="Back to the connected models">${icon("down")}</button>` : icon("chip")}${esc(title)}</h3>
          <button type="button" class="iconbtn" data-close aria-label="Close">${icon("close")}</button></div>
        ${body}<p class="err" role="alert"></p></div>`;
      hydrateIcons(d);
    };
    const row = (attr, ic, name, sub, on, go) => `<button type="button" class="mdl-opt${on ? " on" : ""}" ${attr} ${on ? `aria-current="true"` : ""}>${ic}
        <span class="mdl-opt-txt"><b>${esc(name)}</b>${sub ? `<small class="faint">${esc(sub)}</small>` : ""}</span>${on ? `<span class="mdl-opt-on">${icon("check")}</span>` : ""}${go ? `<span class="mdl-opt-go">${icon("down")}</span>` : ""}</button>`;
    const first = () => {
      shell("Default model", false, `<p class="muted small">Pick a connected model, then one of the models it offers.</p>
        <div class="mdl-opts">${row(`data-pick="auto"`, `<span class="prov prov-auto" aria-hidden="true">${icon("zap")}</span>`, "Automatic", "Claude when connected", cur === "auto")}
          ${rows.map((r, i) => { const on = r.pick ? r.pick === cur : r.models.some(m => m.id === cur);
            return row(r.pick ? `data-pick="${esc(r.pick)}"` : `data-row="${i}"`, Chat.providerIcon(r.icon), r.name, r.pick ? r.sub : `${r.sub} · ${r.models.length} model${r.models.length === 1 ? "" : "s"}`, on, !r.pick); }).join("")}</div>
        ${rows.length ? "" : `<p class="faint small">No model is connected yet: add one first.</p>`}`);
      $(".mdl-opt", d)?.focus();
    };
    const second = r => {
      const free = r.models.filter(m => m.free), paid = r.models.filter(m => !m.free), split = free.length && paid.length;
      let kind = split && free.some(m => m.id === cur) ? "free" : "paid", q = "";
      const list = () => (split ? (kind === "free" ? free : paid) : r.models).filter(m => !q || `${m.label} ${m.id}`.toLowerCase().includes(q));
      shell(r.name, true, `${split ? `<div class="seg full mdl-kind" role="group" aria-label="Free or paid models">
            <button type="button" data-kind="paid">Paid models · ${paid.length}</button><button type="button" data-kind="free">Free models · ${free.length}</button></div>` : ""}
        ${r.models.length > 10 ? `<input type="search" class="mdl-find" data-find placeholder="Find a model" aria-label="Find a model" autocomplete="off" spellcheck="false">` : ""}
        <div class="mdl-opts" data-list></div>`);
      const draw = () => {
        $$("[data-kind]", d).forEach(b => b.setAttribute("aria-pressed", b.dataset.kind === kind));
        const ms = list();
        $("[data-list]", d).innerHTML = ms.length ? ms.map(m => row(`data-pick="${esc(m.id)}"`, "", m.label, m.id.split(":").slice(1).join(":") === m.label ? "" : m.id.split(":").slice(1).join(":"), m.id === cur)).join("")
          : `<p class="faint small">No model matches.</p>`;
        hydrateIcons($("[data-list]", d));
      };
      $$("[data-kind]", d).forEach(b => b.onclick = () => { kind = b.dataset.kind; draw(); });
      const find = $("[data-find]", d);
      if (find) find.oninput = () => { q = find.value.trim().toLowerCase(); draw(); };
      draw();
      (find || $(".mdl-opt", d))?.focus();
    };
    d.onclick = e => {
      if (e.target === d || e.target.closest("[data-close]")) return d.close();
      if (e.target.closest("[data-back]")) return first();
      const pick = e.target.closest("[data-pick]"); if (pick) return save(pick.dataset.pick);
      const r = e.target.closest("[data-row]"); if (r) second(rows[+r.dataset.row]);
    };
    first();
    if (!d.open) d.showModal();
  }

  // Add a model: type → model → name → key / token / server. A connected model's settings are on its card in the list.
  function modelDialog(s) {
    const d = $("#agentdlg");
    const ctx = { p: "anthropic", type: typeOf("anthropic").id, pendingMode: null, close: () => d.close() };
    const typeOpts = () => MODEL_TYPES.map(t => `<option value="${t.id}">${t.label}</option>`).join("");
    const modelOpts = () => MODEL_TYPES.find(t => t.id === ctx.type).models.map(([id, label]) => `<option value="${id}">${esc(label)}</option>`).join("");
    d.innerHTML = `<form class="settings-dlg mdl-dlg" novalidate>
      <div class="sd-head"><h3>${icon("plus")}Add a model</h3><button type="button" class="iconbtn" data-close aria-label="Close">${icon("close")}</button></div>
      <div class="mdl-pick">
        <label class="in"><span>Type</span><select name="type">${typeOpts()}</select></label>
        <label class="in"><span>Model</span><select name="model"></select></label>
      </div>
      <label class="in" data-name-row><span>Name</span><input name="name" maxlength="60" autocomplete="off" spellcheck="false"></label>
      <label class="in" data-who-row><span>Login</span><select name="who">
          <option value="server">Token (paste a token)</option><option value="mine">Website sign-in (sign in on the website)</option></select>
        <small class="hint"><b>Token</b>: paste a token below; the server runs agents on it.
          <b>Website sign-in</b>: Connect opens Claude's or ChatGPT's sign-in page; when you've signed in there, the model is added to the list.
          Models added either way can be used by everyone on the site.</small></label>
      <div class="mdl-body" data-body></div>
      <p class="err" role="alert"></p>
      <div class="row end mdl-actions" data-actions></div>
    </form>`;
    const f = $("form", d), err = $(".err", f);
    const typeSel = f.elements.type, modelSel = f.elements.model, nameIn = f.elements.name, whoSel = f.elements.who;
    ctx.name = () => nameIn.value;
    const hasMine = () => ctx.type === "cli" && (ctx.p === "terminal" || ctx.p === "codex");  // My logins covers Claude Code and Codex
    ctx.mine = () => hasMine() && whoSel.value === "mine";
    typeSel.value = ctx.type;
    tipify(f);
    const draw = () => {
      modelSel.innerHTML = modelOpts(); modelSel.value = ctx.p;
      nameIn.value = DEFAULT_NAME[ctx.p] || "";  // a new model's name: nothing of a model that's already connected
      $("[data-who-row]", f).hidden = !hasMine();
      $("[data-name-row]", f).hidden = ctx.mine();  // a personal login isn't a model of its own: nothing to name
      const body = $("[data-body]", f);
      err.textContent = ""; ctx.pendingMode = null;
      ctx.stopOwn?.(); ctx.stopOwn = null;  // a sign-in that was open for another choice
      if (ctx.mine()) {  // your own plan: Connect opens Claude's / ChatGPT's sign-in page and the result comes back here
        body.innerHTML = `<div class="mdl-own" data-mine></div>`;
        $("[data-actions]", f).innerHTML = `<span class="mdl-gap"></span><button type="button" class="btn sm" data-close>Cancel</button>`;
        ctx.stopOwn = ownConnect($("[data-mine]", body), ctx.p, modelsChanged);
      } else {
        body.innerHTML = modelBody(s, ctx.p, ctx.type, false);
        $("[data-actions]", f).innerHTML = modelButtons(s, ctx.p, false);
      }
      hydrateIcons(f); $$(".eye", f).forEach(b => b.innerHTML = icon("eye"));
      tipify(body);
      wireModelFields(s, f, ctx);
    };
    whoSel.onchange = draw;
    d.addEventListener("close", () => { ctx.stopOwn?.(); ctx.stopOwn = null; }, { once: true });
    typeSel.onchange = () => { ctx.type = typeSel.value; ctx.p = MODEL_TYPES.find(t => t.id === ctx.type).models[0][0]; draw(); };
    modelSel.onchange = () => { ctx.p = modelSel.value; draw(); };
    wireModelActions(s, f, ctx);
    d.onclick = e => { if (e.target === d) d.close(); };
    draw();
    d.showModal();
    typeSel.focus();
  }

  async function decide(pid, approve) {
    try {
      const r = await Admin.withSudo(() => api(`/api/agents/proposals/${pid}`, { method: "POST", body: { approve } }));
      if (r.status === "failed") Auth.toast(r.message);
      else Auth.toast(approve ? "Approved and applied" : "Rejected");
      if (r.temp_password) Admin.showTemp({ username: conv.proposals.find(p => p.id === pid)?.payload.username || "" }, r.temp_password);
    } catch (e) { if (e.message !== "cancelled") Auth.toast(e.message); }
    conv = await api(`${base(current)}/conversations/${conv.id}`);
    render();
  }

  function wire() {
    if (wired) return; wired = true;
    hydrateIcons($("#view-agents"));
    $("#view-agents").addEventListener("click", async e => {
      const t = e.target;
      if (t.closest("#aos")) return;  // the operations side handles its own clicks (agent-studio.js)
      if (page === "chat" && await chatClick(e)) return;
      const mm = t.closest("[data-model-menu]"); if (mm) { e.stopPropagation(); return document.querySelector(".model-pop") ? document.querySelector(".model-pop").remove() : Chat.modelMenu(mm); }
      if (t.closest("[data-settings]")) return settings();
      if (t.closest("[data-skills]")) return skillHub();
      const os = t.closest("[data-ops-sec]"); if (os) return showOps(os.dataset.opsSec);
      if (t.closest("[data-ops]")) return showOps("overview");
      if (t.closest("[data-new]")) return go("home");
      if (t.closest("[data-blank]")) return editor(null);
      if (t.closest("[data-team]")) return Workspace.addTeam().then(r => { if (r) { loadLists(); Workspace.show(null); } });
      if (t.closest("[data-study-team]")) {
        try { const r = await api("/api/study/team", { method: "POST" }); Auth.toast(r.team_result.created ? `Study team ready: ${r.team_result.created} tutors created` : "Your study team is already complete"); loadLists(); return setView("study"); }
        catch (x) { return Auth.toast(x.message); }
      }
      if (t.closest("[data-publish]")) return publishPicker();
      if (t.closest("[data-edit]")) return editor(current);
      const nav = t.closest("[data-hub]"); if (nav) { conv = null; return go(nav.dataset.hub); }
      const cat = t.closest("[data-cat]"); if (cat) { homeCat = cat.dataset.cat; return renderHome(); }
      const tpl = t.closest("[data-template]"); if (tpl) { const x = hub.templates.find(y => y.id === tpl.dataset.template); return editor(null, { ...x, examples: x.examples || [] }); }
      const tab = t.closest("[data-tab]"); if (tab) { mine.tab = tab.dataset.tab; return renderMine(); }
      const m = t.closest("[data-amenu]"); if (m) { e.stopPropagation(); return agentMenu(m, findAgent(m.dataset.amenu)); }
      const det = t.closest("[data-detail]"); if (det) return detail(findAgent(det.dataset.detail));
      const row = t.closest("tr[data-chat]"); if (row) return startChat(findAgent(row.dataset.chat));
      const rc = t.closest("[data-recent]");
      if (rc) { const r = recents.find(x => String(x.agent_id) === rc.dataset.recent); const a = findAgent(rc.dataset.recent); if (a) return startChat(a, r?.id); return Auth.toast("That agent is no longer available"); }
      const ex = t.closest("[data-example]"); if (ex) return send(ex.dataset.example);
      const c = t.closest("[data-conv]"); if (c) return openConv(c.dataset.conv);
      const d = t.closest("[data-decide]"); if (d) return decide(+d.dataset.decide, d.dataset.approve === "1");
    });
  }

  // the model menu's "Set up" link: Models, once the tab has loaded
  let wantSettings = false;
  function openSettings() { if (hub && S.view === "agents") return settings(); wantSettings = true; setView("agents"); }

  // the operations side (agent-studio.js) and setView("studio") use these
  const need = id => { const a = findAgent(id); if (!a) Auth.toast("That agent isn't available to you"); return a; };
  const api_ = {
    ops: sec => { mode = "ops"; pref("mode", mode); wantSec = sec || null; },  // before setView("agents"): open on the operations side
    create: () => hub ? go("home") : api_.wantNew(),
    tools: () => { mode = "hub"; pref("mode", mode); page = "tools"; if (S.view === "agents" && hub) go("tools"); else setView("agents"); },  // Agents → Tools & MCP  // before the hub has loaded, open() shows New agent when it has
    wantNew: () => { mode = "hub"; pref("mode", mode); page = "home"; current = null; },  // before setView("agents"): open on New agent
    chat: id => { const a = need(id); if (a) startChat(a); },
    edit: id => { const a = need(id); if (a) editor(a); },
    menu: (btn, id) => { const a = need(id); if (a) agentMenu(btn, a); },
  };
  return { ...api_, open, openAgent, openSettings, md, toolLabel: name => TOOL_LABEL[name] || name, toolHtml, proposalsHtml };
})();
