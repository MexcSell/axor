/* Workspace: your shortlist of subnets, each with a mining brief (task, what you do, budget, low-cost plan,
   how to become a top miner, competition), sticky notes, files from Scout Drive, and the agents you work
   with. The selected agent answers questions about the open subnet; its chats are kept per agent and subnet.
   Notes (notes.js, private) and Files (shared by every user) have their own sections in the sidebar and
   open in the main panel; each item belongs to one subnet or is general (shown with every subnet). The News
   tab lists GitHub releases, commits and on-chain changes for the open subnet. */
const Workspace = (() => {
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("ws." + k)); localStorage.setItem("ws." + k, JSON.stringify(v)); } catch { return null; } };
  let ws = { subnets: [], agents: [], agents_enabled: false }, loaded = false, wired = false;
  let sel = pref("sel"), brief = null, briefSeq = 0, chat = null, busy = false;
  let tab = pref("tab") || "brief", scope = pref("scope") || "here", files = { enabled: false, files: [] };
  let fileGeneral = false, uploads = [], upSeq = 0, newsSeq = 0, focusChat = false, wideChat = pref("wideChat") || false;
  // Team: PDCA cycles run by the project team; Reports: what waits for the user's approval (team.js). Both need agents.
  const TABS = [["brief", "info", "Brief"], ["news", "news", "News"], ["team", "users", "Team"], ["reports", "bell", "Reports"]];
  const TEAM_TABS = new Set(["team", "reports"]);
  const SIDE = new Set(["notes", "files", "overview", "everywhere"]);  // panes opened from the sidebar rather than the subnet's tabs (everywhere: All files, file-catalog.js)
  const SIDE_MAX = 6;
  const setup = { hardware: pref("hw"), own: pref("own") };
  const HW = [["", "Not set"], ["none", "None"], ["cpu", "CPU"], ["gpu1", "1 GPU"], ["gpu2", "Pro GPU"], ["gpu3", "Cluster"]];
  const EXAMPLES = ["What will this cost me per month?", "How do I become a top miner here?", "How strong is the competition right now?", "Give me a step-by-step plan to start mining"];
  const LEVEL = { "No earners": "avoid", "Winner-take-all": "avoid", Concentrated: "caution", Competitive: "new", Broad: "clear" };

  const enabled = () => !!Auth.me();
  const has = n => ws.subnets.some(s => s.netuid === +n);
  const row = n => S.data?.subnets?.find(r => r.netuid === +n);
  const agent = () => ws.agents.find(a => a.selected);
  const usdOr = (x, d = "–") => x == null ? d : usd(x);
  const range = (lo, hi) => lo == null ? "Not published" : hi ? `${usd(lo)}–${usd(hi)}` : usd(lo);
  // the chat uses the model picked in the Agents tab (Auto unless changed there)
  const modelChoice = () => Chat.choice();  // the model menu is shared by every chat (chatkit.js)

  async function init() {
    $("#nav-ws").hidden = !enabled();
    if (!enabled()) return;
    await load();
  }
  async function load() {
    const [v, f] = await Promise.all([api("/api/workspace").catch(() => ws), api("/api/workspace/files").catch(() => null), Notes.load()]);
    ws = v; if (f) files = f; loaded = true;
    if (ws.agents_enabled) api("/api/workspace/pdca/pending").then(r => setPending(r.pending_total)).catch(() => {});
    if (ws.agents_enabled) Overview.peek();  // the sidebar's Overview count
    if (!has(sel)) sel = ws.subnets[0]?.netuid ?? null;
    $("#c-ws").textContent = ws.subnets.length || "";
    syncButtons();
  }
  async function open() {
    wire();
    if (!loaded) { $("#ws-main").innerHTML = Loading.cards(3, "card"); await load(); }
    else api("/api/workspace/files").then(f => {  // files can change in the Drive view too
      files = f; if (S.view === "workspace") { renderSide(); if (tab === "files") renderFiles(); }
    }).catch(() => {});
    render();
  }
  // live data landed: refresh the open brief without touching the chat
  function onData() { if (S.view === "workspace" && loaded) { renderSide(); if (sel != null && tab === "brief") loadBrief(true); } }

  // ---------- add / remove from anywhere ----------
  function addButton(n, cls = "btn") {
    if (!enabled()) return "";
    const on = has(n);
    return `<button type="button" class="${cls} ws-add ${on ? "on" : ""}" data-ws-add="${n}" aria-pressed="${on}" title="${on ? "In your workspace (click to remove)" : "Add to your workspace"}">${icon(on ? "check" : "plus")}${on ? "In workspace" : "Add to workspace"}</button>`;
  }
  // "Ask an agent" on a subnet's details: open it here with the selected agent's chat ready
  function askButton(n, cls = "btn") {
    return enabled() && ws.agents_enabled ? `<button type="button" class="${cls}" data-ws-ask="${n}" title="Chat with your workspace agent about this subnet">${icon("bot")}Ask an agent</button>` : "";
  }
  async function ask(n) {
    if (!has(n)) { await toggle(n); if (!has(n)) return; }  // toggle explains why it couldn't add (e.g. the workspace is full)
    closeDrawer();
    focusChat = true;
    show(n, "brief");
  }
  function syncButtons() { $$("[data-ws-add]").forEach(b => b.outerHTML = addButton(b.dataset.wsAdd, [...b.classList].filter(c => !["ws-add", "on"].includes(c)).join(" "))); }
  async function toggle(n) {
    n = +n;
    const r = row(n);
    if (has(n)) {  // removing also deletes your chats about it, so it asks first
      const ok = await UI.confirm({ title: `Remove SN${n}${r?.name ? ` ${esc(r.name)}` : ""} from your workspace?`, body: "Your agent chats about it are deleted. Your notes about it stay, and you can add it again any time.",
        ok: "Remove", icon: "close", run: async () => { ws = await api(`/api/workspace/subnets/${n}`, { method: "DELETE" }); } });
      if (!ok) return;
      toast(`SN${n} removed from your workspace`, { kind: "success" });
    } else {
      try { ws = await api("/api/workspace/subnets", { method: "POST", body: { netuid: n } }); } catch (e) { return toast(e.message); }
      toast(`SN${n} ${r?.name || ""} added to your workspace`);
      if (!sel) sel = n;
    }
    if (!has(sel)) { sel = ws.subnets[0]?.netuid ?? null; pref("sel", sel); }
    $("#c-ws").textContent = ws.subnets.length || "";
    syncButtons();
    if (S.view === "workspace") render();
  }

  // ---------- layout ----------
  function render() {
    const root = $("#view-workspace .ws");
    if (tab === "overview" && !ws.agents_enabled) setTab("brief");  // a remembered Overview after agents were switched off
    root.classList.toggle("no-chat", !ws.agents_enabled || tab === "overview" || tab === "everywhere"); root.classList.toggle("wide-chat", wideChat);
    Chat.resizer(root, "--chat-w", "wsChatW");
    renderSide();
    if (SIDE.has(tab) && (sel == null || tab === "overview" || tab === "everywhere")) {  // notes and shared files work without any subnet; the overview spans them all
      $("#ws-main").innerHTML = `<div class="ws-pane" id="ws-pane"></div>`;
      $("#ws-chat").innerHTML = "";
      return renderPane();
    }
    if (sel == null) {
      $("#ws-main").innerHTML = `<div class="card chat-empty">${av({ icon: "pickaxe", color: "amber" }, "xl")}<h3>Your workspace is empty</h3>
        <p class="muted">Add the subnets you're considering. Each one gets a mining brief: the task, what you'd do, a budget for hardware, inference and registration, how to keep costs low, how to become a top miner and how strong the competition is.</p>
        <div class="row" style="justify-content:center"><button type="button" class="btn primary" data-ws="add-subnet">${icon("plus")}Add subnets</button><button type="button" class="btn" data-goto="recommend">${icon("target")}Get recommendations</button></div></div>`;
      $("#ws-chat").innerHTML = "";
      return;
    }
    $("#ws-main").innerHTML = head() + `<div class="ws-pane" id="ws-pane"></div>`;
    renderPane();
    loadChat();
  }
  // title and tabs stay put while the pane below switches between brief, news, notes and files
  function head() {
    const r = row(sel) || { netuid: sel, name: brief?.netuid === sel ? brief.name : "Not in current data", field: brief?.netuid === sel ? brief.field : "" };
    return `<div class="ws-title">${row(sel) ? logo(r) : `<span class="logo">${sel}</span>`}<div><h1>SN${sel} · ${esc(r.name)}</h1><span class="muted">${esc(r.field || "")}${r.created_date ? ` · created ${r.created_date}` : ""}</span></div>
        <div class="row">${r.flags ? riskBadge(r) : ""}${row(sel) ? `<button type="button" class="btn sm" data-open="${sel}">${icon("chart")}Details &amp; trends</button>${Slack.shareButton("subnet", sel)}` : ""}
        <button type="button" class="btn sm danger-text" data-ws-remove="${sel}">${icon("close")}Remove</button></div></div>
      <div class="hub-tabs ws-tabs" role="tablist" id="ws-tabs">${tabsHtml()}</div>`;
  }
  function tabsHtml() {
    return TABS.filter(([k]) => !TEAM_TABS.has(k) || ws.agents_enabled).map(([k, ic, l]) => `<button type="button" role="tab" data-ws-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}${k === "reports" && pending ? `<span class="tab-count" title="${pending} waiting for your approval">${pending}</span>` : ""}</button>`).join("");
  }
  const syncTabs = () => { const t = $("#ws-tabs"); if (t) t.innerHTML = tabsHtml(); };
  // decisions waiting for the user, on every subnet (kept current by the Team and Reports tabs' live stream)
  let pending = 0;
  function setPending(k) { if (k === pending || k == null) return; pending = k; syncTabs(); }
  function setTab(t) { if (t !== tab) { tab = t; pref("tab", t); } }
  function renderPane() {
    if (tab !== "notes") Notes.settle();
    if (!TEAM_TABS.has(tab)) Team.stop();
    if (TEAM_TABS.has(tab) && !ws.agents_enabled) setTab("brief");
    if (tab === "team") return Team.render($("#ws-pane"), sel, modelChoice);
    if (tab === "reports") return Team.reports($("#ws-pane"), sel);
    if (tab === "everywhere") return FileCatalog.render($("#ws-pane"));
    if (tab === "notes") return Notes.render($("#ws-pane"), { sel, scope: sel == null ? "all" : scope, scopeSeg: sel == null ? () => "" : scopeSeg, onChange: renderSide });
    if (tab === "files") return renderFiles();
    if (tab === "overview") return Overview.render($("#ws-pane"));  // overview.js
    if (tab === "news") return renderNews();
    loadBrief();
  }
  const mine = x => sel == null || x.netuid == null || x.netuid === sel;
  const notesHere = () => sel == null ? Notes.all() : Notes.forSubnet(sel);
  const filesHere = () => files.files.filter(mine);
  const scopeSeg = what => `<div class="seg" data-ws-scope-seg><button type="button" data-ws-scope="here" aria-pressed="${scope === "here"}">SN${sel} &amp; general</button><button type="button" data-ws-scope="all" aria-pressed="${scope === "all"}">All ${what}</button></div>`;
  const tagOf = x => `<span class="ws-tag" title="${x.netuid == null ? "Shown with every subnet" : `Only shown with SN${x.netuid}`}">${x.netuid == null ? "General" : `SN${x.netuid}`}</span>`;
  const av = agentAvatar;  // faces.js
  function renderSide() {
    const items = ws.subnets.map(s => {
      const r = row(s.netuid);
      return `<div class="ws-item ${s.netuid === sel ? "on" : ""}" data-ws-sel="${s.netuid}" role="button" tabindex="0">
        ${r ? logo(r) : `<span class="logo">${s.netuid}</span>`}
        <span class="ws-item-txt"><b>SN${s.netuid} · ${esc(r?.name || "Not in current data")}</b><small class="faint">${r ? `${money(r.top_miner)}/d top · reg ${money(r.reg_cost)}` : ""}</small></span>
        ${r?.risk_level ? `<span class="ws-dot ${r.risk_level}" title="${esc(RISK[r.risk_level].label)}"></span>` : ""}
        <button type="button" class="iconbtn sm" data-ws-remove="${s.netuid}" aria-label="Remove SN${s.netuid} from workspace" title="Remove">${icon("close")}</button></div>`;
    }).join("");
    const agents = !ws.agents_enabled ? `<p class="faint small">Agents are available to administrators${Auth.me()?.role === "admin" ? "" : " (ask one to let members use them)"}.</p>`
      : ws.agents.map(a => `<div class="ws-item agent ${a.selected ? "on" : ""}" data-ws-agent="${a.id}" role="button" tabindex="0" title="${a.selected ? "Selected" : "Select"}">
          ${av(a, "sm")}<span class="ws-item-txt"><b>${esc(a.name)}</b><small class="faint">${esc(a.role || "Agent")}${a.status === "paused" ? " · paused" : ""}</small></span>
          ${a.selected ? `<span class="badge clear" title="Selected: answers questions about the open subnet">${icon("check")}</span>` : ""}
          <button type="button" class="iconbtn sm" data-ws-amenu="${a.id}" aria-label="Actions for ${esc(a.name)}">${icon("columns")}</button></div>`).join("")
        || `<p class="faint small">Add an agent to ask it about the open subnet.</p>`;
    // notes: the open subnet's and general ones; files: shared by everyone, same filter
    const nts = notesHere(), fls = files.enabled ? filesHere() : [];
    const title = t => (t || "").split("\n").map(l => l.replace(/^\s*(?:#+|[-*+] \[[ xX]\]|[-*+•]|\d+[.)]|>)\s*/, "").replace(/\*\*|==|~~|`/g, "").trim()).find(Boolean) || "Empty note";
    const noteItems = nts.slice(0, SIDE_MAX).map(x => {
      const t = (x.text.match(/^\s*[-*+] \[( |x|X)\]/gm) || []), done = t.filter(c => !/\[ \]/.test(c)).length;
      return `<div class="ws-item ws-nitem" data-ws-note="${x.id}" role="button" tabindex="0" title="Open note">
        <span class="ws-swatch ${x.color?.startsWith("#") ? "n-custom" : `n-${esc(x.color)}`}" style="${x.color?.startsWith("#") ? `--c:${esc(x.color)}` : ""}">${x.pinned ? icon("pin") : ""}</span>
        <span class="ws-item-txt"><b>${esc(title(x.text))}</b><small class="faint">${x.netuid == null ? "General" : `SN${x.netuid}`}${x.stage ? ` · ${x.stage.toUpperCase()}` : ""}${t.length ? ` · ${done}/${t.length} done` : ""}</small></span></div>`;
    }).join("");
    const fileItems = fls.slice(0, SIDE_MAX).map(x => `<div class="ws-item ws-fitem" data-ws-file="${esc(x.id)}" role="button" tabindex="0" title="Show in Files">
        <span class="ws-fico">${icon("file")}</span>
        <span class="ws-item-txt"><b>${esc(x.name)}</b><small class="faint">${bytes(x.size)} · ${x.mine ? "you" : esc(x.uploader)}${x.netuid != null ? ` · SN${x.netuid}` : ""}</small></span>
        <a class="iconbtn sm" href="/api/workspace/files/${esc(x.id)}" download aria-label="Download ${esc(x.name)}" title="Download">${icon("download")}</a></div>`).join("");
    const more = (n, k, what) => n > SIDE_MAX ? `<button type="button" class="linkbtn ws-more" data-ws-side="${k}">View all ${n} ${what}</button>` : "";
    $("#ws-side").innerHTML = `
      ${ws.agents_enabled ? `<button type="button" class="ws-ov ${tab === "overview" ? "on" : ""}" data-ws-side="overview" aria-current="${tab === "overview" ? "page" : "false"}" title="What waits for you and what your agents are doing">${icon("grid")}<span>Overview</span><span class="count" id="ws-ov-n" title="Waiting for you" ${Overview.count() ? "" : "hidden"}>${Overview.count() || ""}</span></button>` : ""}
      <div class="ws-head"><span>Subnets <span class="faint">${ws.subnets.length}</span></span><button type="button" class="btn sm" data-ws="add-subnet">${icon("plus")}Add</button></div>
      <div class="ws-list">${items || `<p class="faint small">No subnets yet.</p>`}</div>
      <div class="ws-head"><span>Agents <span class="faint">${ws.agents.length}</span></span>${ws.agents_enabled ? `<button type="button" class="btn sm" data-ws="add-agent">${icon("plus")}Add</button>` : ""}</div>
      <div class="ws-list">${agents}</div>
      <div class="ws-head ${tab === "notes" ? "on" : ""}"><button type="button" class="ws-head-link" data-ws-side="notes" title="Open notes">${icon("note")}Notes <span class="faint">${nts.length}</span></button><button type="button" class="btn sm" data-ws="add-note">${icon("plus")}Add</button></div>
      <div class="ws-list">${noteItems || `<p class="faint small">${sel == null ? "No notes yet." : `No notes for SN${sel} yet.`}</p>`}${more(nts.length, "notes", "notes")}</div>
      ${files.enabled ? `<div class="ws-head ${tab === "files" ? "on" : ""}" id="ws-side-files"><button type="button" class="ws-head-link" data-ws-side="files" title="Open shared files">${icon("file")}Files <span class="faint">${fls.length}</span></button>
          <label class="btn sm" title="Upload files (shared with everyone)"><input type="file" multiple class="sr" data-ws-upload>${icon("plus")}Add</label></div>
        <div class="ws-list ws-drop-side" data-ws-dropside>${fileItems || `<p class="faint small">No files yet. Drop files here to share them with everyone.</p>`}${more(fls.length, "files", "files")}</div>` : ""}
      <button type="button" class="ws-ov ws-all ${tab === "everywhere" ? "on" : ""}" data-ws-side="everywhere" aria-current="${tab === "everywhere" ? "page" : "false"}" title="Every file and work product AXoR keeps for you: drive, Competition teams, missions, long tasks, knowledge">${icon("layers")}<span>All files</span></button>`;
  }

  // ---------- mining brief ----------
  async function loadBrief(quiet = false) {
    const n = sel, seq = ++briefSeq, pane = () => tab === "brief" && seq === briefSeq ? $("#ws-pane") : null;
    if (!quiet || !brief) $("#ws-pane").innerHTML = Loading.cards(4, "card");
    const q = new URLSearchParams({ own: setup.own ? "true" : "false", ...(setup.hardware ? { hardware: setup.hardware } : {}) });
    try { const b = await api(`/api/workspace/subnets/${n}/brief?${q}`); if (!pane()) return; brief = b; renderBrief(); }
    catch (e) { if (pane()) pane().innerHTML = `<div class="card empty">${esc(e.message)}${e.status === 404 ? ` <button type="button" class="linkbtn" data-ws-remove="${n}">Remove it from your workspace</button>` : ""}</div>`; }
  }
  function renderBrief() {
    const b = brief, r = row(b.netuid) || { name: b.name, netuid: b.netuid, links: b.links }, B = b.budget, C = b.competition, E = B.earnings;
    const tile = (label, val, sub, cls = "") => `<div class="${cls}"><span>${label}</span><b>${val}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;
    const kv = (label, val) => `<div><span>${label}</span><b>${val}</b></div>`;
    const list = xs => `<ul class="ws-ul">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
    const s1 = C.top_share, s3 = Math.max(0, C.top3_share - s1), s10 = Math.max(0, C.top10_share - C.top3_share);
    const rest = Math.max(0, 1 - C.owner_burn_share - s1 - s3 - s10);
    const seg = (w, cls, t) => w > 0.004 ? `<i class="${cls}" style="width:${(w * 100).toFixed(1)}%" title="${t}: ${pct(w, 0)}"></i>` : "";
    const payees = (C.top_payees || []).slice(0, 15).map((m, i) => `<tr><td class="num">${i + 1}</td><td class="num">${m.uid}</td>
      <td><a class="num" href="https://taostats.io/hotkey/${esc(m.hotkey)}" target="_blank" rel="noopener noreferrer" title="${esc(m.hotkey)}">${short(m.hotkey)}</a><br><span class="faint num" title="Coldkey ${esc(m.coldkey)}">${short(m.coldkey)}</span></td>
      <td class="r num">${money(m.tao_day)}</td><td class="r num">${pct(m.incentive, 2)}</td>
      <td class="num">${new Date(m.registered_at * 1000).toLocaleDateString()}${m.immune ? ' <span class="badge new">New</span>' : ""}</td></tr>`).join("");
    $("#ws-pane").innerHTML = `
      <div class="ws-grid2">
        <div class="card"><h3>${icon("info")}Task</h3><p class="ws-p">${esc(b.task) || "Not documented."}</p>
          ${b.description && b.description !== b.task ? `<p class="faint ws-p">“${esc(b.description)}”</p>` : ""}${r.links ? `<div style="margin-top:8px">${linkIcons(r)}</div>` : ""}</div>
        <div class="card"><h3>${icon("pickaxe")}What you do</h3><p class="ws-p">${esc(b.miner_role) || "Not documented."}</p>
          ${b.conditions ? `<p class="muted ws-p"><b>Rules:</b> ${esc(b.conditions)}</p>` : ""}
          <p class="muted ws-p"><b>Hardware:</b> ${esc(b.hardware) || "Not published"}</p>
          <div class="tags" style="max-width:none">${b.software.map(s => `<span class="tag">${esc(s)}</span>`).join("")}</div></div>
      </div>

      <div class="card"><div class="ws-card-head"><h3>${icon("wallet")}Budget</h3>
          <form class="ws-setup" id="ws-setup"><label>My hardware <select name="hardware">${HW.map(([k, l]) => `<option value="${k}" ${k === (setup.hardware || "") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="chk"><input type="checkbox" name="own" ${setup.own ? "checked" : ""}> I own it</label></form></div>
        <div class="money ws-money">
          ${tile(`Hardware / month${B.hardware.owned ? " (owned)" : ""}`, usdOr(B.hardware.typical, "Unknown"), `${range(B.hardware.owned ? B.hardware.low * 0.25 : B.hardware.low, B.hardware.owned ? B.hardware.high * 0.25 : B.hardware.high)} · ${esc(B.hardware.label)}`)}
          ${tile("Inference / API / month", usd(B.inference.typical), B.inference.high ? range(B.inference.low, B.inference.high) : "Not needed")}
          ${tile("Registration (one-time)", `${fmtNum(B.registration.tao)} τ`, usdOr(B.registration.usd, ""))}
          ${tile("Running cost / month", usdOr(B.monthly.typical, "Unknown"), B.monthly.low != null ? `${usd(B.monthly.low)}–${usd(B.monthly.high)}` : "")}
          ${tile("First month total", usdOr(B.first_month, "Unknown"), "running cost + registration")}
        </div>
        <div class="money ws-money">
          ${tile("Top miner / day", money(E.top_day), usdOr(E.top_day * (S.data?.tao_usd || 0), ""))}
          ${tile("2nd miner / day", money(E.second_day))}
          ${tile("Median earner / day", money(E.median_day))}
          ${tile("Realistic for you / day", money(E.realistic_day), `${pct(E.earn_chance, 0)} of miners earn`)}
          ${tile("Expected gross / month", usdOr(E.gross_month_usd))}
          ${tile("Net / month", usdOr(B.net_month_usd), B.first_month_net_usd != null ? `first month ${usd(B.first_month_net_usd)}` : "", B.net_month_usd < 0 ? "neg" : B.net_month_usd > 0 ? "pos" : "")}
          ${tile("Registration break-even", B.break_even_days == null ? "Not at current rates" : B.break_even_days < 1 ? "< 1 day" : `${fmtNum(B.break_even_days, 1)} days`)}
        </div>
        <p class="fine">Hardware: ${esc(B.hardware.spec)}. Inference: ${esc(B.inference.what)}.${B.capital_at_risk ? " <b>Also needs trading capital, collateral or stake that can be lost.</b>" : ""}
          "Realistic" is the median earner's pay (or half of #2's where one miner dominates) times the share of miners who earn. Typical cloud prices, not quotes.</p></div>

      <div class="ws-grid2">
        <div class="card"><h3>${icon("coins")}How to keep costs low</h3>${list(b.low_cost)}</div>
        <div class="card"><h3>${icon("trophy")}How to become a top miner</h3>${list(b.top_miner)}</div>
      </div>

      <div class="card"><div class="ws-card-head"><h3>${icon("users")}Competition</h3><span class="badge ${LEVEL[C.level] || "new"}">${esc(C.level)}</span></div>
        <p class="ws-p">${esc(C.summary)}</p>
        <div class="ws-share" aria-label="Who gets miner rewards">${seg(s1, "s1", "Top miner")}${seg(s3, "s2", "#2–3")}${seg(s10, "s3", "#4–10")}${seg(rest, "s4", "Everyone else")}${seg(C.owner_burn_share, "s5", "Owner / burn")}</div>
        <div class="ws-legend faint"><span><i class="s1"></i>Top miner ${pct(s1, 0)}</span><span><i class="s2"></i>#2–3 ${pct(s3, 0)}</span><span><i class="s3"></i>#4–10 ${pct(s10, 0)}</span><span><i class="s4"></i>Others ${pct(rest, 0)}</span><span><i class="s5"></i>Owner / burn ${pct(C.owner_burn_share, 0)}</span></div>
        <div class="kv" style="margin-top:12px">
          ${kv("UIDs registered", `${C.registered} / ${C.max}`)}${kv("Miners earning", `${C.earning} of ${C.miners} (${pct(C.earning_share, 0)})`)}${kv("Validators", C.validators)}
          ${kv("Open / prunable slots", `${C.open_slots} / ${C.prunable}`)}${kv("Can register now", C.uid_available ? `<span class="ok">${icon("check")}Yes</span>` : `<span class="no">${icon("ban")}${C.registration_allowed ? "Full / rate-limited" : "Closed"}</span>`)}
          ${C.reg_rate_limit != null ? kv("Registrations this interval", `${C.regs_this_interval} / ${C.reg_rate_limit}`) : ""}
          ${kv("Operators in top 15", C.operators ? `${C.operators}${C.biggest_operator_uids > 1 ? ` (largest runs ${C.biggest_operator_uids} UIDs)` : ""}` : "–")}
          ${kv("Newcomers in top 15", C.new_in_top)}${kv("Immunity", `${fmtNum(C.immunity_hours, 0)} h`)}
          ${C.reg_cost_7d ? kv("Reg. cost 7d low / median / high", `${fmtNum(C.reg_cost_7d.low)} / ${fmtNum(C.reg_cost_7d.median)} / ${fmtNum(C.reg_cost_7d.high)} τ`) : ""}
          ${kv("Reg. cost 7d", pct(C.reg_cost_change_7d))}${kv("Emission 7d", pct(C.emission_change_7d))}${kv("Alpha price 7d", pct(C.price_change_7d))}
        </div>
        ${payees ? `<h4 class="sub">Top paid miners now</h4><div class="tablewrap flat"><table class="grid mini-table"><thead><tr><th>#</th><th>UID</th><th>Hotkey / coldkey</th><th class="r">Per day</th><th class="r">Incentive</th><th>Registered</th></tr></thead><tbody>${payees}</tbody></table></div>` : ""}
      </div>
      ${b.flags.length ? `<div class="card"><h3>${icon("alert")}Risk flags</h3><ul class="flags">${b.flags.map(f => `<li><span class="badge ${f.level}">${icon(RISK[f.level].icon)}${RISK[f.level].label}</span><span>${esc(f.text)}</span></li>`).join("")}</ul></div>` : ""}`;
    $("#ws-setup").onchange = e => {
      const f = e.currentTarget;
      setup.hardware = f.elements.hardware.value || null; setup.own = f.elements.own.checked;
      pref("hw", setup.hardware); pref("own", setup.own); loadBrief(true);
    };
  }

  // ---------- news ----------
  const SOURCE = { release: ["download", "Release"], commits: ["github", "Commits"], chain: ["chip", "On-chain"] };
  async function renderNews() {
    const n = sel, seq = ++newsSeq, pane = $("#ws-pane");
    pane.innerHTML = Loading.cards(3, "card");
    let r;
    try { r = await api(`/api/news?netuid=${n}&limit=40`); } catch (e) { if (seq === newsSeq) pane.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    if (seq !== newsSeq || tab !== "news") return;
    pane.innerHTML = `<div class="card"><div class="ws-card-head"><h3>${icon("news")}News for SN${n}</h3><span class="faint small">GitHub releases and commits, and changes seen on chain</span></div>
      ${r.items.length ? `<ul class="news-list">${r.items.map(newsItem).join("")}</ul>` : `<p class="faint ws-none">Nothing yet. Releases and commits from the subnet's GitHub repository${row(n)?.links?.github ? "" : " (none is registered on chain for this subnet)"} and on-chain changes appear here as they happen.</p>`}</div>`;
  }
  const newsItem = x => { const [ic, l] = SOURCE[x.source] || ["info", x.source];
    return `<li class="news-item"><span class="news-ic">${icon(ic)}</span><div><div class="news-top"><span class="ws-tag">${l}</span><span class="faint small" title="${esc(stamp(x.ts))}">${ago(x.ts)}</span></div>
      <b>${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>` : esc(x.title)}</b>${x.body ? `<p class="faint">${esc(x.body)}</p>` : ""}</div></li>`; };

  // ---------- files (Scout Drive: the Shared drive plus your My drive) ----------
  const bytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : n < 1073741824 ? `${fmtNum(n / 1048576, 1)} MB` : `${fmtNum(n / 1073741824, 2)} GB`;
  function renderFiles() {
    const pane = $("#ws-pane");
    if (!files.enabled) { pane.innerHTML = `<div class="card empty">File storage isn't available on this server.</div>`; return; }
    if (files.error) { pane.innerHTML = `<div class="card empty">${icon("alert")} ${esc(files.error)}</div>`; return; }
    const list = scope === "all" || sel == null ? files.files : filesHere(), used = files.used / files.quota;
    pane.innerHTML = `<div class="card"><div class="ws-card-head"><h3>${icon("file")}Files</h3><div class="row">${sel == null ? "" : scopeSeg("files")}<button type="button" class="btn sm" data-open-drive>${icon("external")}Open Drive</button></div></div>
        <p class="faint small ws-shared-note">${icon("users")}Files from AXoR Drive: the Shared drive (everyone signed in) and your own My drive (only you). Uploads here go to Shared drive › Workspace.</p>
        <label class="ws-drop" id="ws-drop"><input type="file" id="ws-file" multiple class="sr">${icon("upload")}<b>Drop files here or click to upload</b>
          <small class="faint">Up to ${bytes(files.max_file)} each: configs, scripts, logs, results to share with the team.</small></label>
        <div class="ws-file-opts">${sel == null ? "" : `<label class="chk"><input type="checkbox" id="ws-file-general" ${fileGeneral ? "checked" : ""}> Show with every subnet</label>`}
          <div class="ws-usage" title="${pct(used, 1)} of your upload space used"><div class="ws-bar ${used > 0.9 ? "full" : ""}"><i style="width:${Math.min(100, used * 100).toFixed(1)}%"></i></div><small class="faint">You use ${bytes(files.used)} of ${bytes(files.quota)} in the drive · ${bytes(files.total || 0)} in the Shared drive</small></div></div>
        ${uploads.length ? `<div class="ws-uploads">${uploads.map(u => `<div class="ws-up" data-up="${u.id}"><span>${icon("upload")}${esc(u.name)}</span><div class="ws-bar"><i style="width:${(u.pct * 100).toFixed(0)}%"></i></div></div>`).join("")}</div>` : ""}
        ${list.length ? `<div class="tablewrap flat"><table class="grid mini-table ws-files"><thead><tr><th>Name</th><th>Subnet</th><th class="r">Size</th><th>Updated</th><th></th></tr></thead><tbody>
          ${list.map(x => `<tr><td><div class="ws-fname">${icon("file")}<a href="/api/workspace/files/${esc(x.id)}" download title="Download ${esc(x.name)}">${esc(x.name)}</a></div><small class="faint">${x.space === "mine" ? "My drive" : "Shared drive"}${x.path ? ` › ${esc(x.path)}` : ""}</small></td><td>${tagOf(x)}</td><td class="r num">${bytes(x.size)}</td><td title="${esc(stamp(x.added))}">${x.mine ? "You" : esc(x.uploader)} <span class="faint">· ${ago(x.added)}</span></td>
            <td class="r"><a class="iconbtn sm" href="/api/workspace/files/${esc(x.id)}" download aria-label="Download ${esc(x.name)}" title="Download">${icon("download")}</a>${x.can_delete ? `<button type="button" class="iconbtn sm" data-file-del="${esc(x.id)}" aria-label="Delete ${esc(x.name)}" title="Delete">${icon("close")}</button>` : ""}</td></tr>`).join("")}
          </tbody></table></div>` : `<p class="faint ws-none">No files ${scope === "all" || sel == null ? "yet" : `for SN${sel} yet`}.</p>`}</div>
        <div id="ws-mf"></div>`;
    MiningFiles.mountWs($("#ws-mf"), sel);  // a competition team's files beside these (mining-files.js)
    $("#ws-file").onchange = e => { upload([...e.target.files]); e.target.value = ""; };
    const g = $("#ws-file-general"); if (g) g.onchange = e => { fileGeneral = e.target.checked; };
  }
  // raw-body uploads (passed on to the drive); XHR rather than fetch for progress events
  function upload(list) {
    for (const file of list) {
      if (file.size > files.max_file) { toast(`${file.name} is over the ${bytes(files.max_file)} limit`); continue; }
      const u = { id: ++upSeq, name: file.name, pct: 0 }, netuid = fileGeneral || sel == null ? null : sel;
      uploads.push(u);
      const x = new XMLHttpRequest();
      x.open("POST", `/api/workspace/files?${new URLSearchParams({ name: file.name, ...(netuid == null ? {} : { netuid }) })}`);
      x.setRequestHeader("X-Requested-With", "scout");
      x.setRequestHeader("Content-Type", "application/octet-stream");
      x.upload.onprogress = e => { if (!e.lengthComputable) return; u.pct = e.loaded / e.total; const b = $(`[data-up="${u.id}"] i`); if (b) b.style.width = `${(u.pct * 100).toFixed(0)}%`; };
      const done = msg => {
        uploads = uploads.filter(y => y !== u);
        if (msg) toast(msg);
        if (S.view === "workspace") { renderSide(); if (tab === "files") renderFiles(); }
      };
      x.onload = () => {
        let d = {}; try { d = JSON.parse(x.responseText); } catch {}
        if (x.status < 300) { files = d; return done(`${file.name} uploaded`); }
        if (x.status === 401) Auth.expired();
        done(typeof d.detail === "string" ? d.detail : x.status === 413 ? `${file.name} is too large` : `Couldn't upload ${file.name}`);
      };
      x.onerror = () => done(`Couldn't upload ${file.name}: connection lost`);
      x.send(file);
    }
    if (tab === "files") renderFiles();
  }
  function deleteFile(id) {
    const x = files.files.find(f => f.id === id); if (!x) return;
    Auth.modal(`<h3>${icon("file")}Delete ${esc(x.name)}?</h3><p class="muted">It moves to the drive's trash${x.space === "shared" ? " for everyone" : ""}. You can restore it from Drive › Trash for a while.</p>`,
      async () => { files = await api(`/api/workspace/files/${id}`, { method: "DELETE" }); $("#modal").close(); toast(`${x.name} moved to the trash`); renderSide(); renderFiles(); },
      { submit: "Delete", danger: true });
  }

  // ---------- agents ----------
  async function loadChat() {
    const a = agent(), n = sel;
    chat = null;
    if (!ws.agents_enabled || !a) return renderChat();
    $("#ws-chat").innerHTML = `<div class="card">${Loading.line("Loading chat…")}</div>`;
    try { const c = await api(`/api/workspace/chat?agent_id=${a.id}&netuid=${n}`); if (agent() === a && sel === n) chat = c; } catch (e) { toast(e.message); }
    renderChat();
  }
  const ckey = () => `ws:${sel}:${agent()?.id}`;
  function renderChat() {
    const box = $("#ws-chat"); if (!box) return;
    const wantFocus = focusChat && !!chat; if (chat || !agent()) focusChat = false;  // no agent yet: the "Add agent" card shows instead
    const a = agent(), r = row(sel);
    if (!ws.agents_enabled) { box.innerHTML = ""; return; }
    if (!a) {
      box.innerHTML = `<div class="card chat-empty">${av({ icon: "bot", color: "violet" }, "lg")}<h3>Add an agent</h3><p class="muted">Pick one of your agents (or start from a template) to ask about ${r ? `SN${r.netuid} ${esc(r.name)}` : "this subnet"}.</p>
        <div class="row"><button type="button" class="btn" data-ws="add-agent">${icon("plus")}Add agent</button><button type="button" class="btn primary" data-ws="add-team">${icon("users")}Add project team</button></div>
        <p class="faint small">The project team is eight senior engineers, one per stage of building on this subnet: plan, sources, local simulation, measurement, competition, the miner itself, practice tasks and shipping it (CI/CD). In the Team tab they run Plan-Do-Check-Act cycles on their own.</p></div>`;
      return;
    }
    const items = chat?.items || [], paused = a.status === "paused";
    const o = { key: ckey(), busy, disabled: paused, compact: true, mic: true, tokens: Chat.tokensOf(items), turns: items.filter(i => i.kind === "assistant" && i.tokens).length,
                placeholder: paused ? `${a.name} is paused` : wideChat ? `Ask ${a.name} about SN${sel}… (+ adds files or code, / for commands)` : `Ask ${a.name} about SN${sel}…`,
                slash: [["new", "Start a new chat"], ["brief", "Open the subnet's mining brief"], ["news", "Open the subnet's news"]],
                onSend: (text, sent) => send(text, sent), onCommand: command, mention: Chat.defaultMention };
    box.innerHTML = `<div class="chat card ws-chatbox" data-cx-panel>${Chat.grip()}
      <div class="chat-head">${av(a)}<div class="ws-chat-who"><b>${esc(a.name)}${a.role ? ` · ${esc(a.role)}` : ""}</b><small>About SN${sel}${r ? ` ${esc(r.name)}` : ""}</small></div>
        ${Chat.displayButton()}
        <button type="button" class="iconbtn sm" data-ws="chat-wide" title="${wideChat ? "Narrow the chat" : "Widen the chat"}" aria-label="${wideChat ? "Narrow the chat" : "Widen the chat"}" aria-pressed="${wideChat}">${icon(wideChat ? "shrink" : "expand")}</button>
        <button type="button" class="btn sm head-btn" data-ws="new-chat" ${items.length ? "" : "disabled"}>${icon("plus")}New chat</button></div>
      <div class="chat-log cx-log" id="ws-log" aria-live="polite">${Chat.log(items, { agent: a, busy, toolHtml: i => `${icon("search")}${esc(Agents.toolLabel(i.name))}`,
        empty: `<div class="chat-empty">${av(a, "lg")}<p class="muted">Ask ${esc(a.name)} about this subnet. It reads the same live data and mining brief you see here.</p>
           <div class="chips">${EXAMPLES.map(x => `<button type="button" class="chip" data-ws-ex="${esc(x)}">${esc(x)}</button>`).join("")}</div></div>` })}</div>
      ${Chat.composer(o)}</div>`;
    Chat.enhance($("#ws-log"));
    Chat.mount(box.querySelector(".cx-composer"), o);
    Chat.bind(box, { items: () => chat?.items || [], onSay: t => send(t) });
    if (wantFocus) { box.scrollIntoView({ block: "nearest" }); Chat.focus(ckey()); }
  }
  async function command(cmd) {
    if (cmd === "new") { newChat(); return true; }
    if (cmd === "brief" || cmd === "news") { setTab(cmd); syncTabs(); renderSide(); renderPane(); return true; }
    return false;
  }
  async function newChat() {
    const a = agent(), n = sel; if (!a) return;
    if (chat?.items?.length && !await UI.confirm({ title: "Start a new chat?", body: `This chat with ${esc(a.name)} about SN${n} is cleared. This can't be undone.`, ok: "Clear and start new", icon: "chat" })) return;
    api(`/api/workspace/chat?agent_id=${a.id}&netuid=${n}`, { method: "DELETE" }).then(c => { if (agent() === a && sel === n) { chat = c; renderChat(); } }).catch(x => toast(x.message));
  }
  async function send(text, sent = []) {
    const a = agent(), n = sel;
    if (busy || !a || !text.trim()) return false;
    busy = true;
    chat = { ...(chat || {}), items: [...(chat?.items || []), { kind: "user", text, attachments: sent.map(x => ({ kind: x.kind, label: x.label })) }] };
    renderChat();
    let ok = true;
    try {
      const r = await api("/api/workspace/chat", { method: "POST", body: { agent_id: a.id, netuid: n, message: text, ...Chat.choice(), attachments: sent.map(({ kind, id }) => ({ kind, id })) } });
      if (agent() === a && sel === n) { chat = r; if (r.error) chat.items.push({ kind: "note", text: r.error }); }
    } catch (e) { if (agent() === a && sel === n) chat.items.push({ kind: "note", text: e.message }); ok = false; }
    busy = false;
    if (S.view === "workspace") { renderChat(); Chat.focus(ckey()); }
    return ok;
  }

  // the project team: created from its templates (or reused) and added in one go, the engineering manager selected
  async function addTeam() {
    try {
      const r = await api("/api/workspace/team", { method: "POST" });
      ws = r; const t = r.team;
      toast(t.added ? `Project team ready: ${t.added} agent${t.added === 1 ? "" : "s"} added${t.skipped ? `, ${t.skipped} didn't fit (workspace holds 12)` : ""}`
        : t.skipped ? "Your workspace is full (12 agents). Remove some to add the team." : "The project team is already in your workspace");
      if (S.view === "workspace") { renderSide(); loadChat(); }
      return r;
    } catch (e) { toast(e.message); }
  }
  async function pickAgent() {
    let lists, hub;
    try { [lists, hub] = await Promise.all([api("/api/agents/custom"), api("/api/agents/hub")]); } catch (e) { return toast(e.message); }
    const inWs = new Set(ws.agents.map(a => a.id)), seen = new Set();
    const group = (title, xs) => {
      xs = xs.filter(a => a.kind !== "study" && !inWs.has(a.id) && !seen.has(a.id) && seen.add(a.id));  // study tutors don't read subnet data
      return xs.length ? `<h4>${title}</h4>` + xs.map(a => `<label class="pick">${av(a, "sm")}<span><b>${esc(a.name)}</b><small class="faint">${esc(a.role || "")}${a.status === "paused" ? " · paused" : ""}</small></span><input type="radio" name="pick" value="a:${a.id}"></label>`).join("") : "";
    };
    const html = group("Your agents", lists.mine) + group("Shared with you", lists.shared) + group("Shared catalog", [...lists.from_directory, ...lists.directory])
      + `<h4>Templates <span class="faint">(creates an agent you own)</span></h4>` + hub.templates.filter(t => t.kind !== "study").map(t => `<label class="pick">${av(t, "sm")}<span><b>${esc(t.name)}</b><small class="faint">${esc(t.role)}</small></span><input type="radio" name="pick" value="t:${esc(t.id)}"></label>`).join("");
    const f = Auth.modal(`<h3>${icon("bot")}Add an agent to your workspace</h3><p class="muted">The selected agent answers questions about the subnet you have open.</p><div class="pick-list ws-pick">${html}</div>`, async f => {
      const v = $$("[name=pick]", f).find(x => x.checked)?.value;
      if (!v) throw new Error("Pick an agent.");
      let id = +v.slice(2);
      if (v.startsWith("t:")) {
        const t = hub.templates.find(x => x.id === v.slice(2));
        id = (await api("/api/agents/custom", { method: "POST", body: { name: t.name, role: t.role, description: t.description, instructions: t.instructions, icon: t.icon, color: t.color, skills: t.skills, examples: t.examples || [] } })).id;
      }
      ws = await api("/api/workspace/agents", { method: "POST", body: { agent_id: id } });
      if (ws.agents.length > 1) ws = await api("/api/workspace/agents/selected", { method: "PUT", body: { agent_id: id } });
      $("#modal").close(); toast(`${ws.agents.find(a => a.id === id)?.name || "Agent"} added and selected`);
      renderSide(); loadChat();
    }, { submit: "Add" });
    $("[name=pick]", f)?.setAttribute("checked", "");
  }
  async function select(id) {
    if (agent()?.id === id) return;
    try { ws = await api("/api/workspace/agents/selected", { method: "PUT", body: { agent_id: id } }); renderSide(); loadChat(); } catch (e) { toast(e.message); }
  }
  function agentMenu(btn, a) {
    document.querySelector(".menu")?.remove();
    const acts = [!a.selected && ["select", "check", "Select"], ["remove", "close", "Remove from workspace"], a.mine && ["delete", "ban", "Delete agent"]].filter(Boolean);
    const pop = document.createElement("div"); pop.className = "popover menu";
    pop.innerHTML = acts.map(([k, ic, l]) => `<button type="button" class="mi ${k === "delete" ? "danger" : ""}" data-act="${k}">${icon(ic)}${l}</button>`).join("");
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px";
    pop.style.left = Math.max(16, Math.min(b.left, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.onclick = async e => {
      const k = e.target.closest("[data-act]")?.dataset.act; if (!k) return;
      pop.remove();
      if (k === "select") return select(a.id);
      if (k === "remove") {
        return UI.confirm({ title: `Remove ${esc(a.name)} from your workspace?`, body: `Your chats with ${esc(a.name)} here are deleted, on every subnet. The agent itself stays in Agents, and you can add it again.`, ok: "Remove", icon: "close",
          run: async () => { ws = await api(`/api/workspace/agents/${a.id}`, { method: "DELETE" }); toast(`${a.name} removed from your workspace`); renderSide(); loadChat(); } });
      }
      Auth.modal(`<h3>${icon("ban")}Delete ${esc(a.name)}?</h3><p class="muted">This deletes the agent and every chat with it, for everyone it's shared with. To only take it out of your workspace, use Remove instead.</p>`,
        async () => { await api(`/api/agents/custom/${a.id}`, { method: "DELETE" }); $("#modal").close(); toast(`${a.name} deleted`); await load(); renderSide(); loadChat(); },
        { submit: "Delete", danger: true });
    };
  }

  function pickSubnets() {
    const all = (S.data?.subnets || []).filter(r => !has(r.netuid)).sort((a, b) => a.netuid - b.netuid);
    const f = Auth.modal(`<h3>${icon("plus")}Add subnets</h3>
      <div class="search"><span>${icon("search")}</span><input id="ws-q" type="search" placeholder="Search name, number, field…" autocomplete="off"></div>
      <div class="pick-list ws-pick">${all.map(r => `<label class="pick" data-hay="${esc(`sn${r.netuid} ${r.netuid} ${r.name} ${r.field} ${r.task}`.toLowerCase())}">${logo(r)}<span><b>SN${r.netuid} · ${esc(r.name)}</b><small class="faint">${esc(r.field)} · top ${money(r.top_miner)}/d · reg ${money(r.reg_cost)}</small></span>${r.risk_level ? `<span class="ws-dot ${r.risk_level}" title="${esc(RISK[r.risk_level].label)}"></span>` : ""}<input type="checkbox" name="n" value="${r.netuid}"></label>`).join("") || `<p class="faint">Every subnet is already in your workspace.</p>`}</div>`,
      async f => {
        const picked = $$("[name=n]:checked", f).map(x => +x.value);
        if (!picked.length) throw new Error("Tick at least one subnet.");
        for (const n of picked) ws = await api("/api/workspace/subnets", { method: "POST", body: { netuid: n } });
        $("#modal").close();
        sel = picked[0]; pref("sel", sel);
        toast(picked.length === 1 ? `SN${picked[0]} added to your workspace` : `${picked.length} subnets added to your workspace`);
        $("#c-ws").textContent = ws.subnets.length; syncButtons(); render();
      }, { submit: "Add" });
    $("#ws-q", f).oninput = e => { const q = e.target.value.trim().toLowerCase(); $$("[data-hay]", f).forEach(l => l.hidden = !!q && !l.dataset.hay.includes(q)); };
    $("#ws-q", f).focus();
  }

  function wire() {
    if (wired) return; wired = true;
    Notes.wire();
    const root = $("#view-workspace");
    root.addEventListener("click", e => {
      if (Team.click(e)) return;
      const t = e.target;
      const k = t.closest("[data-ws]")?.dataset.ws;
      if (k === "add-subnet") return pickSubnets();
      if (k === "add-agent") return pickAgent();
      if (k === "add-team") return addTeam();
      if (k === "new-chat") return newChat();
      if (k === "chat-wide") { wideChat = !wideChat; pref("wideChat", wideChat); $("#view-workspace .ws").classList.toggle("wide-chat", wideChat); return renderChat(); }
      const g = t.closest("[data-goto]"); if (g) return setView(g.dataset.goto);
      const rm = t.closest("[data-ws-remove]"); if (rm) { e.stopPropagation(); return toggle(rm.dataset.wsRemove); }
      const m = t.closest("[data-ws-amenu]"); if (m) { e.stopPropagation(); return agentMenu(m, ws.agents.find(a => a.id === +m.dataset.wsAmenu)); }
      const s = t.closest("[data-ws-sel]"); if (s) { if (+s.dataset.wsSel !== sel || SIDE.has(tab)) { sel = +s.dataset.wsSel; pref("sel", sel); brief = null; if (SIDE.has(tab)) setTab("brief"); render(); } return; }
      const a = t.closest("[data-ws-agent]"); if (a) return select(+a.dataset.wsAgent);
      const ex = t.closest("[data-ws-ex]"); if (ex) return send(ex.dataset.wsEx);
      const tb = t.closest("[data-ws-tab]"); if (tb) { if (tb.dataset.wsTab !== tab) { setTab(tb.dataset.wsTab); syncTabs(); renderSide(); renderPane(); } return; }
      const sd = t.closest("[data-ws-side]"); if (sd) { setTab(sd.dataset.wsSide); return render(); }
      if (k === "add-note") { setTab("notes"); Notes.openView("board"); render(); return $("#ws-note-new textarea")?.focus(); }
      const ni = t.closest("[data-ws-note]"); if (ni) { const x = Notes.all().find(n => n.id === +ni.dataset.wsNote); setTab("notes"); if (Notes.view() === "daily" || (Notes.view() === "pdca" && !x?.stage)) Notes.openView("board"); render();
        // after this click has finished bubbling, or the notes "click outside closes the editor" handler would close it
        return setTimeout(() => { Notes.edit(+ni.dataset.wsNote); $(`.ws-note[data-note="${ni.dataset.wsNote}"]`)?.scrollIntoView({ block: "nearest" }); }); }
      const fi = t.closest("[data-ws-file]"); if (fi && !t.closest("a")) { setTab("files"); render(); const r = $(`[data-file-del="${fi.dataset.wsFile}"], .ws-files a[href$="${fi.dataset.wsFile}"]`)?.closest("tr"); r?.classList.add("flash"); r?.scrollIntoView({ block: "center" }); return; }
      const sc = t.closest("[data-ws-scope]"); if (sc) { scope = sc.dataset.wsScope; pref("scope", scope); return renderPane(); }
      const fd = t.closest("[data-file-del]"); if (fd) return deleteFile(fd.dataset.fileDel);
    });
    root.addEventListener("mousemove", Team.hover);
    root.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-ws-sel], [data-ws-agent], [data-ws-note], [data-ws-file]")) { e.preventDefault(); e.target.click(); } });
    root.addEventListener("change", e => { if (Team.change(e)) return; if (e.target.matches("[data-ws-upload]")) { upload([...e.target.files]); e.target.value = ""; } });
    const drop = e => e.target.closest?.("#ws-drop, [data-ws-dropside]");
    root.addEventListener("dragover", e => { if (drop(e)) { e.preventDefault(); drop(e).classList.add("over"); } });
    root.addEventListener("dragleave", e => drop(e)?.classList.remove("over"));
    root.addEventListener("drop", e => { if (!drop(e)) return; e.preventDefault(); drop(e).classList.remove("over"); upload([...e.dataTransfer.files]); });
  }

  // jump straight to a subnet's tab (used by the dashboard and notifications)
  function show(n, t) { if (n != null && has(n)) { sel = +n; pref("sel", sel); brief = null; } if (t) setTab(t); setView("workspace"); }
  return { init, open, onData, toggle, addButton, askButton, ask, addTeam, has, show, newsItem, setPending, subnets: () => ws.subnets, tab: () => tab };
})();
