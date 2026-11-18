/* Knowledge Hub (knowledge_hub.py + knowledge_spaces.py; knowledge-company.js, knowledge-graph.js, knowledge.css; prefix kb-).
   One module draws two spaces, each its own page:
   - My Knowledge (#myknowledge): private by default. Overview (Ask My Knowledge, search, the inbox, what waits for you),
     Workspace (a folder tree and what each folder holds), Sources (files and web pages; imports of earlier workspaces and
     external agents; adopting what they hold into your agents), Communications (Slack, Discord and Telegram messages in one
     inbox), Ideas (proposed → evaluated, with AI analysis), Connections (typed links and their graph), Company sharing
     (publish for company review) and Settings & connectors.
   - Knowledge Hub (#knowledge): the agent company's governed knowledge; knowledge-company.js draws its tabs.
   Imported text, messages and pages are shown as text, never run; nothing reaches your agents or the company until you
   share or publish it, and company knowledge is trusted only after you approve the exact version. */
const Knowledge = (() => {
  const K = "/api/knowledge";
  const VIEW = { personal: "myknowledge", company: "knowledge" };
  const PTABS = [["overview", "dash", "Overview"], ["workspace", "folder", "Workspace"], ["sources", "file", "Sources"], ["comms", "chat", "Communications"],
                 ["ideas", "bulb", "Ideas"], ["connections", "branch", "Connections"], ["sharing", "group", "Company sharing"], ["retrieval", "target", "Retrieval & quality"], ["settings", "gear", "Settings & connectors"]];  // retrieval: knowledge-rag.js
  const LEGACY = { import: ["sources", "imports"], adopt: ["sources", "adopt"], items: ["workspace"], ideas: ["ideas"], history: ["settings"] };  // old tab names (Approval Center links)
  const TONE = { ok: "clear", run: "new", warn: "caution", bad: "scam", none: "muted" };  // styles.css's badges
  const TRUST = { yours: ["ok", "Yours"], workspace: ["run", "Earlier workspace"], external: ["warn", "External · untrusted"], shared: ["run", "Shared by a teammate"] };
  const REACH = { page: ["lock", "Only you"], agents: ["bot", "You and your agents"], teams: ["users", "Your agents and teams"] };
  const STAGE = { proposed: "none", analyzed: "run", planned: "run", doing: "warn", done: "ok", evaluated: "ok", dropped: "none" };
  const VERDICT = { adopt: ["ok", "Adopt"], adapt: ["run", "Adapt"], reject: ["none", "Reject"] };
  const PSTATUS = { pending: ["warn", "Waiting for you"], applied: ["ok", "Applied"], declined: ["none", "Declined"], noted: ["none", "Recommendation"],
                    rolled_back: ["none", "Rolled back"], applying: ["run", "Applying"] };
  const OWNER = { me: "You", agents: "Your agents", workforce: "Workforce", company: "Company", teams: "Competition teams" };
  const OWNER_GO = { agents: "agents", workforce: "workforce", company: "company", teams: "teams" };
  const VIS = { "Private": ["none", "lock"], "Shared with your agents": ["run", "bot"], "Shared with your agents and teams": ["run", "users"], "Company candidate": ["warn", "group"],
                "Approved for the company": ["ok", "check"], "Not approved for the company": ["none", "ban"], "Archived": ["none", "inbox"] };
  const KIND_IC = { file: "file", code: "code", dataset: "table", url: "globe", bookmark: "pin", paste: "note", conversation: "chat", message: "chat", document: "doc", image: "image", audio: "speaker", video: "film" };
  const KIND_L = { file: "File", code: "Code", dataset: "Dataset", url: "Web page", bookmark: "Bookmark", paste: "Pasted text", conversation: "Conversation", message: "Message",
                   document: "Document", image: "Picture", audio: "Audio", video: "Video" };
  const TEXT_EXT = /\.(md|markdown|txt|rst|csv|tsv|json|jsonl|xml|py|js|ts|tsx|jsx|go|rs|java|kt|c|h|cpp|rb|php|sh|sql|yaml|yml|toml|ini|css)$/i;
  const FILE_ACCEPT = ".md,.markdown,.txt,.rst,.csv,.tsv,.json,.jsonl,.xml,.html,.htm,.py,.js,.ts,.go,.rs,.java,.sh,.sql,.yaml,.yml,.toml,.docx,.pptx,.xlsx,.odt,.odp,.ods,.epub,.rtf,.pdf,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.m4a,.ogg,.flac,.mp4,.mov,.webm";
  const CAPS = [["note", "note", "Note"], ["idea", "bulb", "Idea"], ["url", "globe", "Web page"], ["file", "upload", "File"], ["paste", "clip", "Paste"], ["conversation", "chat", "Conversation"]];
  const PLAT = { slack: "Slack", discord: "Discord", telegram: "Telegram" };
  let space = "personal", on = false, wired = false;
  const D = { personal: null, company: null }, failed = { personal: "", company: "" }, tabs = { personal: null, company: null };
  let item = null, src = null, idea = null, rec = null, hits = null, q = "", asked = null, sub = "assets", folder = "/00-Inbox", find = "", sel = new Set(),
      comms = null, cf = { platform: "", channel: "", q: "" }, csel = new Set(), graph = null, cap = null, f = { type: "", trust: "", reach: "", status: "kept", text: "" },
      stageF = "all", gos = [], picked = null, pubSel = new Set(), cof = {}, fedit = null, gLoading = false, cLoading = false, shared = null, sharing_ = false, people = null, connEdit = null;
  const root = () => document.getElementById(VIEW[space]);
  const d_ = () => D[space];
  const err = e => e && toast(e.message, { kind: "error" });
  const chip = (cls, text, ic = "") => `<span class="badge ${TONE[cls] || "muted"}">${ic ? icon(ic) : ""}${text}</span>`;
  const when = ts => ts ? ago(ts) : "–";
  const plural = (n, w, s = "s") => `${(n || 0).toLocaleString()} ${w}${n === 1 ? "" : s}`;
  const trust = t => chip(...(TRUST[t] || ["none", esc(t || "")]));
  const vis = v => chip(...((VIS[v] || ["none", "lock"]).slice(0, 1)), esc(v || "Private"), (VIS[v] || ["none", "lock"])[1]);
  const empty = t => `<p class="kb-empty">${t}</p>`;
  const go = x => x ? `data-kb-go="${gos.push(x) - 1}"` : "";
  const card = (ic, title, extra, body, cls = "") => `<section class="kb-card ${cls}"><header><h3>${icon(ic)}${title}</h3>${extra ? `<span class="kb-card-x">${extra}</span>` : ""}</header>${body}</section>`;
  const store_ = (k, v) => { try { if (v === undefined) return store.get("kb." + k, null); store.set("kb." + k, v); } catch { return null; } };
  const kt = k => d_()?.labels?.ktypes?.[k]?.[0] || k || "";
  const navOk = v => { const b = document.querySelector(`nav.side [data-view="${v}"]`); return b && !b.hidden; };
  const relLabel = l => { const r = (D.personal || D.company)?.labels?.rels?.[l.rel]; if (r) return l.back ? r[1] : r[0];
    return ({ related: "Related", part_of: l.back ? "Contains" : "Part of", similar: "Similar to", compares_to: "Compared with", adopted_as: l.back ? "Adopted from" : "Adopted as",
              published_as: l.back ? "Published from" : "Published as" })[l.rel] || l.rel; };
  const folderOpts = (cur, all = true) => (D.personal?.folders || []).map(x => `<option value="${esc(x.path)}" ${x.path === cur ? "selected" : ""}>${esc(x.path)}</option>`).join("") + (all ? "" : "");
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- open, load ----------
  function open(v) {
    space = v === "knowledge" ? "company" : "personal";
    on = true; wire();
    if (tabs[space] === null) tabs[space] = store_(space + ".tab") || "overview";
    if (!d_()) root().innerHTML = Loading.line(space === "company" ? "Opening the Knowledge Hub…" : "Opening My Knowledge…");
    load();
  }
  function stop() { on = false; }
  function show(t, id) {  // from the Approval Center and other pages: a tab, and the import, proposal, item or record to open
    const company = ["review", "records", "knowledge", "contributions", "analytics"].includes(t);
    item = src = idea = rec = null;
    if (company) { space = "company"; tabs.company = t === "records" ? "knowledge" : t; }
    else { space = "personal"; const [tb, s] = LEGACY[t] || [t || "overview"]; tabs.personal = tb; if (s) sub = s; }
    if (S.view !== VIEW[space]) setView(VIEW[space]); else load();
    if (!id) return;
    if (t === "import") openSource(id);
    else if (t === "adopt") picked = id;
    else openItem(id);
  }
  async function load() {
    const sp = space;
    try { D[sp] = await api(`${K}?space=${sp}`); failed[sp] = ""; } catch (e) { failed[sp] = e.message; }
    if (sp === space) { badge(); render(); }
  }
  function badge() {
    const p = D.personal, el = document.getElementById("c-myknowledge");
    if (el && p) el.textContent = (p.counts.pending + p.counts.previews) || "";
    const c = D.company, el2 = document.getElementById("c-knowledge");
    if (el2 && c && p) el2.textContent = (c.counts.pending + p.counts.pending + p.counts.previews) || "";
  }
  async function refresh() { try { D[space] = await api(`${K}?space=${space}`); badge(); } catch (e) { err(e); } }
  const ctx = () => ({ K, d: D.company, labels: D.company?.labels, get tab() { return tabs.company; }, rec, hits, q, f: cof, h: H, render, refresh, openItem, setRec: r => { rec = r; }, regraph: () => { graph = null; },
                       setTab: t => { tabs.company = t; rec = null; store_("company.tab", t); } });

  // ---------- the page ----------
  function render() {
    const el = root(); if (!el) return;
    gos = [];
    const d = d_();
    if (!d) { el.innerHTML = failed[space] ? `<div class="empty">${esc(failed[space])} <button type="button" class="linkbtn" data-kb="reload">Try again</button></div>` : Loading.line("Opening…"); return; }
    const tab = tabs[space], company = space === "company";
    const T = company ? KnowledgeCo.TABS : PTABS;
    const n = company ? KnowledgeCo.counts(ctx()) : { workspace: d.counts.items, ideas: d.counts.ideas, comms: d.counts.messages || "",
      sources: d.counts.pending + d.counts.previews ? `<span class="hq-n alert">${d.counts.pending + d.counts.previews}</span>` : d.counts.sources };
    el.innerHTML = `<div class="kb kb-${space}">
      <div class="kb-top">
        <div class="kb-spaces" role="group" aria-label="Knowledge spaces"><button type="button" data-kb-space="personal" aria-pressed="${!company}">${icon("lock")}My Knowledge</button>
          <button type="button" data-kb-space="company" aria-pressed="${company}">${icon("group")}Company Knowledge</button></div>
        <span class="kb-faint">${company ? "Governed: shared by review, read by your agents within their scopes" : "Private by default: you decide what your agents read and what the company sees"}</span>
      </div>
      <div class="kb-head"><div class="kb-head-t"><p class="kb-kick">${icon(company ? "group" : "lock")} ${company ? "Shared intelligence for the agent company" : "Personal · private by default"}</p>
          <h1>${company ? "Knowledge Hub" : "My Knowledge"}</h1>
          <p class="kb-lede">${company ? "The company's shared memory: facts, procedures, experiences, decisions, technical knowledge and test results, each with its scope, evidence, review state and version. Agents contribute; nothing they write is trusted until you approve it." :
            "Your notes, files, web pages, messages and ideas in one directory, connected to each other. Capture anything; turn it into knowledge; share it with your agents or publish it for company review when you choose."}</p></div>
        <div class="kb-acts">${company ? KnowledgeCo.actions(ctx()) : `<button type="button" class="btn" data-kb="export" title="Download this workspace as an axor-workspace/1 file">${icon("download")}Export</button>
          <button type="button" class="btn primary" data-kb-cap="note">${icon("plus")}Capture</button>`}</div></div>
      <form class="kb-searchbar" data-kb-form="search" role="search"><label class="kb-sfield"><span class="kb-search-ic">${icon("search")}</span>
        <input type="search" name="q" value="${esc(q)}" placeholder="${company ? "Search all company knowledge you hold…" : "Search files, messages, ideas and connections…"}" aria-label="Search"></label>
        <button class="btn">${icon("search")}Search</button><button type="button" class="btn" data-kb="ask-open" ${d.can_model ? "" : "disabled title='No model is connected'"}>${icon("sparkle")}Ask</button></form>
      ${company ? KnowledgeCo.kpis(ctx()) : kpis()}
      <nav class="kb-tabs" role="tablist" aria-label="${company ? "Knowledge Hub" : "My Knowledge"}">${T.map(([k, ic, l]) => `<button type="button" role="tab" data-kb-tab="${k}" aria-selected="${tab === k}">${icon(ic)}<span>${l}</span>${n[k] !== undefined && n[k] !== "" && n[k] !== 0 ? `<em>${n[k]}</em>` : ""}</button>`).join("")}</nav>
      ${cap && !company ? captureCard() : ""}
      <div class="kb-body">${company ? KnowledgeCo.body(ctx()) : body()}</div></div>`;
    if (tab === "ideas" && !idea && !company) $("#kb-idea-title")?.focus?.({ preventScroll: true });
    afterRender();
  }
  function afterRender() {  // tabs that load their own data, and the graph's drawing
    if (space === "personal" && tabs.personal === "comms" && !comms && !item && !cLoading) loadComms();
    if (tabs[space] === (space === "company" ? "graph" : "connections") && (!graph || graph.space !== space) && !gLoading) loadGraph();
    const svg = root()?.querySelector(".kb-graph");
    if (svg && graph?.space === space && !svg.dataset.drawn) KGraph.draw(svg, graph);
    if (tabs[space] === "retrieval" && !item && !rec && typeof KnowledgeRag === "object") KnowledgeRag.after(space, render);  // it loads its own data
    if (space === "personal" && tabs.personal === "settings" && !item && typeof KnowledgeLinked === "object") KnowledgeLinked.after(render);  // knowledge-linked.js, the same
  }
  function kpis() {
    const c = D.personal.counts;
    const kpi = (label, v, sub_, to, tone = "") => `<button type="button" class="kb-kpi ${tone}" ${to ? `data-kb-tab="${to}"` : "disabled"}><span>${label}</span><b>${(v || 0).toLocaleString()}</b><small>${sub_}</small></button>`;
    return `<div class="kb-kpis">${kpi("Workspace", c.items + c.ideas, `${plural(D.personal.folders.length, "folder")} · ${c.inbox} in the inbox`, "workspace")}
      ${kpi("Sources", c.sources, `files, web pages and pastes`, "sources")}${kpi("Communications", c.messages, `messages in ${plural(c.channels, "channel")}`, "comms")}
      ${kpi("Connections", c.links, "links between records", "connections")}${kpi("Waiting for you", c.pending + c.previews, "proposals and import previews", c.pending ? "sources" : "sources", c.pending + c.previews ? "t-warn" : "")}</div>`;
  }
  function body() {
    const t = tabs.personal;
    if (item) return itemView();
    if (t === "ideas") return idea ? ideaView() : ideas();
    if (t === "workspace") return workspace();
    if (t === "sources") return sources();
    if (t === "comms") return commsView();
    if (t === "connections") return connections();
    if (t === "sharing") return sharing();
    if (t === "settings") return settings();
    if (t === "retrieval" && typeof KnowledgeRag === "object") return KnowledgeRag.tab(H, "personal");
    return overview();
  }

  // ---------- capture (any tab) ----------
  function captureCard() {
    const k = cap, d = D.personal;
    const dflt = { note: "/00-Inbox/Quick-Notes", idea: "/06-Ideas-and-Connections/Ideas", url: "", file: "", paste: "/00-Inbox/Unprocessed", conversation: "/05-Communications/Pasted" }[k];
    const where = tabs.personal === "workspace" && folder !== "/" ? folder : dflt;
    return card("plus", "Capture", `<button type="button" class="iconbtn" data-kb="cap-close" aria-label="Close">${icon("close")}</button>`, `
      <div class="kb-chiprow" role="group" aria-label="What to capture">${CAPS.map(([v, ic, l]) => `<button type="button" class="chip" data-kb-cap="${v}" aria-pressed="${k === v}">${icon(ic)}${l}</button>`).join("")}</div>
      <form class="kb-form" data-kb-form="capture" data-kind="${k}">
        ${k === "url" ? `<label><span>Web address</span><input name="url" type="url" required maxlength="2000" placeholder="https://…"></label>
          <p class="kb-note">${icon("shield")}The page is read once from a public address and kept as a source (text only). If it can't be read, the address is saved as a bookmark.</p>` : ""}
        ${k === "file" ? `<label class="kb-file"><input type="file" name="file" accept="${FILE_ACCEPT}"><span>${icon("upload")}Choose a file</span><em class="kb-faint">Text and code (1 MB); Word, PowerPoint, Excel, OpenDocument, PDF, EPUB, HTML, RTF; pictures (5 MB, read by a model that sees images); audio and video (25 MB, transcribed when a transcription endpoint is set).</em></label>
          <p class="kb-note">${icon("info")}${(D.personal.media || {}).transcribe ? `Audio and video are transcribed by ${esc(D.personal.media.transcribe)}.` : "No transcription endpoint is set: audio and video are kept, to be read once one is."}
            ${(D.personal.media || {}).pictures ? ` Pictures are read by ${esc(D.personal.media.pictures)}.` : " No model that sees pictures is set: pictures are kept, to be read once one is."}</p>` : ""}
        <div class="kb-row"><label class="kb-grow"><span>Title${k === "note" || k === "idea" ? "" : " (optional)"}</span><input name="title" maxlength="200" ${k === "idea" ? "required" : ""} placeholder="${k === "idea" ? "e.g. Reuse last competition's eval harness" : ""}"></label>
          ${k === "url" || k === "file" ? "" : `<label><span>Folder</span><select name="path">${folderOpts(where)}</select></label>`}</div>
        ${k === "url" || k === "file" ? `<label><span>Folder (empty: where its kind belongs)</span><select name="path"><option value="">Automatic</option>${folderOpts(where)}</select></label>` : ""}
        ${["note", "idea", "paste", "conversation"].includes(k) ? `<label><span>${{ note: "Note", idea: "Details", paste: "Text", conversation: "The conversation" }[k]}</span><textarea name="text" rows="${k === "note" || k === "idea" ? 4 : 8}" ${k === "paste" || k === "conversation" ? "required" : ""}></textarea></label>` : ""}
        <div class="kb-row end"><label class="kb-grow"><span>Tags (comma-separated)</span><input name="tags" maxlength="300" placeholder="bittensor, miner"></label><button class="btn primary">${icon("plus")}Capture</button></div>
        <p class="kb-note">${icon("lock")}Private: only you see it until you share it with your agents or publish it. Secrets (keys, tokens) are taken out.</p></form>`, "kb-capture");
  }

  // ---------- Overview ----------
  function overview() {
    const d = D.personal, c = d.counts;
    const inbox = [...d.items, ...d.ideas].filter(k => (k.path || "").startsWith("/00-Inbox") && k.status === "kept").slice(0, 6);
    const waiting = [...d.proposals.filter(p => p.status === "pending").map(p => `<li><span>${chip("warn", "Proposal", "check")} ${esc(p.title)}</span><button type="button" class="linkbtn" data-kb-prop-go="${p.id}">Review</button></li>`),
                     ...d.sources.filter(s => s.status === "preview").map(s => `<li><span>${chip("run", "Import", "upload")} ${esc(s.name)}</span><button type="button" class="linkbtn" data-kb-src="${s.id}">Pick what to keep</button></li>`)];
    return `${askCard("both")}${hits ? card("search", `Results for “${esc(hits.q)}”`, `<button type="button" class="linkbtn" data-kb="clear-search">Clear</button>`, results(hits)) : ""}
      <div class="kb-grid">
        ${card("inbox", "Inbox", `<span class="kb-faint">${plural(c.inbox, "item")} to organize</span>`, inbox.length ? `<ul class="kb-list">${inbox.map(k => `<li><span>${icon(KIND_IC[k.data.kind] || (k.type === "idea" ? "bulb" : "note"))}<button type="button" class="linkbtn" data-kb-item="${k.id}">${esc(k.title)}</button><small class="kb-faint">${esc(k.path)}</small></span>
            ${d.can_model ? `<button type="button" class="btn sm" data-kb-process="${k.id}">${icon("sparkle")}Organize</button>` : ""}</li>`).join("")}</ul>` : empty("The inbox is empty. Capture a note, a link or a file."))}
        ${card("inbox", "Waiting for you", "", waiting.length ? `<ul class="kb-list">${waiting.join("")}</ul>` : empty("Nothing waits for you."))}
        ${(d.shared_with_me || []).length ? card("users", "Shared with you", `<button type="button" class="linkbtn" data-kb-folder="@shared">All ${d.shared_with_me.length}</button>`, `<ul class="kb-list">${d.shared_with_me.slice(0, 5).map(x => `<li><span><button type="button" class="linkbtn" data-kb-shared="${x.id}">${esc(x.title)}</button></span><small class="kb-faint">${esc(x.owner)} · ${when(x.shared)}</small></li>`).join("")}</ul>`) : ""}
        ${card("layers", "What you hold", "", `<ul class="kb-bars">${[["Notes and records", c.items - c.sources], ["Sources (files, pages, pastes)", c.sources], ["Messages", c.messages], ["Ideas", c.ideas],
            ["Shared with your agents", c.items + c.ideas - c.private], ["Published to the company", c.published], ["Your agents' memory", d.internal.memory || 0], ["Teams' lessons", d.internal.team_lessons || 0]]
            .map(([l, v]) => `<li><span>${l}</span><b>${(v || 0).toLocaleString()}</b></li>`).join("")}</ul>`)}
        ${card("clock", "Recent activity", `<button type="button" class="linkbtn" data-kb-tab="settings">All</button>`, d.audit.length ? auditList(d.audit.slice(0, 8)) : empty("Nothing yet."))}
      </div>
      ${card("shield", "How My Knowledge stays private", "", `<ul class="kb-rules"><li>Everything you capture is private: only you see it. Your agents read an item only when you share it with them; competition teams only when you say so.</li>
        <li>Publishing to the company is a separate step: a copy goes to the Knowledge Hub's review, and nothing is company knowledge until you approve it there.</li>
        <li>Files, pages and messages are kept as text and never run; secrets are taken out on the way in. Imported messages and pages are marked untrusted.</li>
        <li>Originals stay apart from what you learn from them: a record made from a source links back to it, so the evidence survives edits.</li></ul>`)}`;
  }
  function askCard(where) {
    const a = asked, d = d_();
    if (typeof KnowledgeRag === "object") return KnowledgeRag.askCard(H, a, where, space, d);  // knowledge-rag.js: RAG options, points, citation checks
    return card("sparkle", space === "company" ? "Ask the Knowledge Hub" : "Ask My Knowledge", "", `<form class="kb-ask" data-kb-form="ask"><textarea name="question" rows="2" maxlength="2000" required placeholder="${space === "company" ? "e.g. What do we know about improving SN62 miner ranking?" : "e.g. Find everything I collected about autonomous AI agents and what's missing"}">${esc(a?.question || "")}</textarea>
        <div class="kb-row end">${space === "company" ? `<input type="hidden" name="where" value="company">` : `<label><span>From</span><select name="where">${[["both", "My Knowledge and the company"], ["mine", "My Knowledge only"], ["company", "Company knowledge only"]].map(([v, l]) => `<option value="${v}" ${(a?.where || where) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>`}
        <button class="btn primary" ${d.can_model ? "" : "disabled title='No model is connected'"}>${icon("sparkle")}Ask</button></div></form>
      ${a?.answer !== undefined ? `<div class="kb-answer">${a.answer ? `<p class="kb-text">${esc(a.answer).replace(/\[((?:kb|mem|mk|wfm|cok):\d+)\]/g, (m, r) => r.startsWith("kb:") ? `<button type="button" class="kb-cite" data-kb-ref="${r}">${r}</button>` : `<span class="kb-cite">${r}</span>`)}</p>` : empty("No answer.")}
        ${a.evidence.length ? `<h4>Evidence</h4><ul class="kb-ev">${a.evidence.map(e => `<li><button type="button" class="linkbtn" data-kb-ref="${e.ref}">${esc(e.title)}</button><small class="kb-faint">${esc(e.kind)} · ${esc(e.ref)}${e.why ? ` — ${esc(e.why)}` : ""}</small></li>`).join("")}</ul>` : ""}
        ${a.gaps.length ? `<h4>What's missing</h4><ul class="kb-plain">${a.gaps.map(g => `<li>${esc(g)}</li>`).join("")}</ul>` : ""}
        ${a.directions?.length ? `<h4>Directions</h4><ul class="kb-plain">${a.directions.map(g => `<li>${esc(g)}</li>`).join("")}</ul>` : ""}
        <p class="kb-note">Answered from ${plural(a.hits.length, "record")} it was given${a.tokens ? ` · ${a.tokens.toLocaleString()} tokens` : ""}. Refs it cited that weren't among them are left out.</p></div>` : ""}`, "kb-askcard");
  }
  function results(r) {
    if (!r.results.length) return empty(`Nothing matches “${esc(r.q)}”.`) + (r.mode ? `<p class="kb-note">Search: ${esc(r.mode)}.</p>` : "");
    return `<ul class="kb-hits">${r.results.map(x => `<li><div class="kb-hit-h"><b>${esc(x.title)}</b>${chip(x.space === "company" ? (x.state === "verified" ? "ok" : "warn") : x.trust === "external" ? "warn" : x.trust === "workspace" ? "run" : "ok", esc(x.kind))}
      ${x.state_label ? chip(x.state === "verified" ? "ok" : "none", esc(x.state_label)) : ""}${x.match === "meaning" || x.match === "fuzzy" ? chip("run", x.match === "meaning" ? "Matched by meaning" : "Close spelling", "sparkle") : ""}${x.scope_label ? `<span class="kb-faint">${esc(x.scope_label)}</span>` : ""}<span class="kb-faint">${esc(x.from)}${x.platform ? ` · ${esc(x.platform)}` : ""}</span>
      ${x.ref.startsWith("kb:") ? `<button type="button" class="linkbtn" data-kb-ref="${x.ref}">Open</button>` : ""}</div><p>${esc(x.text)}</p></li>`).join("")}</ul>`;
  }
  const auditList = rows => `<ul class="kb-audit">${rows.map(a => `<li><span class="kb-faint">${when(a.ts)}</span><b>${esc(a.action)}</b><span>${esc(a.detail || a.target)}</span><span class="kb-faint">${esc(a.actor)}</span></li>`).join("")}</ul>`;

  // ---------- Workspace: the folder tree ----------
  function workspace() {
    const d = D.personal, fs = d.folders, all = [...d.items, ...d.ideas];
    if (folder === "@shared" && (d.shared_with_me || []).length) return sharedView();
    if (!fs.some(x => x.path === folder)) folder = fs[0]?.path || "/00-Inbox";
    const open_ = p => folder === p || folder.startsWith(p + "/");
    const shown = fs.filter(x => x.depth <= 1 || fs.some(y => y.path === x.path.slice(0, x.path.lastIndexOf("/")) && open_(y.path)));
    const t = find.trim().toLowerCase();
    const list = t ? all.filter(k => (k.title + " " + k.body + " " + (k.tags || []).join(" ")).toLowerCase().includes(t)) : all.filter(k => k.path === folder);
    const kids = t ? [] : fs.filter(x => x.path.startsWith(folder + "/") && x.depth === folder.split("/").length);
    const crumbs = folder.split("/").filter(Boolean).map((p, i, a) => `<button type="button" class="linkbtn" data-kb-folder="/${a.slice(0, i + 1).join("/")}">${esc(p)}</button>`).join(`<span class="kb-faint">/</span>`);
    const msgs = (fs.find(x => x.path === folder)?.n || 0) - all.filter(k => k.path === folder).length;
    return `<div class="kb-explorer">
      <aside class="kb-tree" aria-label="Folders"><div class="kb-tree-h"><b>${icon("folder")}My-Knowledge</b><button type="button" class="iconbtn" data-kb="new-folder" title="New folder" aria-label="New folder">${icon("folderplus")}</button></div>
        <ul>${(D.personal.shared_with_me || []).length ? `<li><button type="button" class="kb-node ${folder === "@shared" ? "on" : ""}" data-kb-folder="@shared" style="--d:0">${icon("users")}<span>Shared with me</span><em>${D.personal.shared_with_me.length}</em></button></li>` : ""}
          ${shown.map(x => `<li><button type="button" class="kb-node ${x.path === folder ? "on" : ""}" data-kb-folder="${esc(x.path)}" style="--d:${x.depth - 1}" ${x.path === folder ? 'aria-current="true"' : ""}>${icon(open_(x.path) && fs.some(y => y.path.startsWith(x.path + "/")) ? "folderup" : "folder")}<span>${esc(x.name)}</span>${x.total ? `<em>${x.total}</em>` : ""}</button></li>`).join("")}</ul></aside>
      <section class="kb-files">
        <div class="kb-files-h"><div class="kb-crumbs">${icon("folder")}<span class="kb-faint">My-Knowledge /</span>${crumbs}</div>
          <div class="kb-acts"><input type="search" class="kb-find" data-kb-find value="${esc(find)}" placeholder="Find in My Knowledge" aria-label="Find in My Knowledge">
            <button type="button" class="btn sm" data-kb-cap="note">${icon("plus")}Capture here</button><button type="button" class="btn sm" data-kb="new-folder">${icon("folderplus")}Subfolder</button>
            <button type="button" class="btn sm" data-kb="move-folder">${icon("edit")}Rename / move</button><button type="button" class="btn sm" data-kb="delete-folder">${icon("trash")}Delete</button></div></div>
        ${fedit ? `<form class="kb-applybar" data-kb-form="folder" data-mode="${fedit}"><label class="kb-grow"><span>${fedit === "new" ? `New folder inside ${esc(folder)}` : "The folder's new path"}</span>
          <input name="name" required maxlength="300" value="${fedit === "move" ? esc(folder) : ""}" placeholder="${fedit === "new" ? "e.g. Validators" : ""}"></label><button class="btn sm primary">${icon("check")}Save</button><button type="button" class="linkbtn" data-kb="folder-cancel">Cancel</button></form>` : ""}
        ${sel.size && sharing_ ? `<form class="kb-applybar" data-kb-form="share-many"><span>Share ${sel.size} with</span><label class="kb-grow"><span>Usernames (comma-separated)</span><input name="who" list="kb-people" required data-kb-people></label>
          <datalist id="kb-people">${(people || []).map(u => `<option value="${esc(u.username)}"></option>`).join("")}</datalist><button class="btn sm primary">${icon("userplus")}Share</button><button type="button" class="linkbtn" data-kb="people-cancel">Cancel</button></form>` : ""}
        ${sel.size ? `<div class="kb-applybar"><span>${sel.size} selected</span><label><span>Move to</span><select id="kb-move-to">${folderOpts(folder)}</select></label><button type="button" class="btn sm" data-kb="move-sel">${icon("folderup")}Move</button>
          <button type="button" class="btn sm" data-kb="share-sel">${icon("bot")}Share with my agents</button><button type="button" class="btn sm" data-kb="people-sel">${icon("userplus")}Share with people…</button><button type="button" class="btn sm" data-kb="private-sel">${icon("lock")}Make private</button>
          <button type="button" class="btn sm primary" data-kb="publish-sel">${icon("group")}Publish to the company…</button><button type="button" class="linkbtn" data-kb="clear-sel">Clear</button></div>` : ""}
        ${kids.length ? `<ul class="kb-subdirs">${kids.map(x => `<li><button type="button" data-kb-folder="${esc(x.path)}">${icon("folder")}<span>${esc(x.name)}</span><em>${x.total}</em></button></li>`).join("")}</ul>` : ""}
        ${list.length ? `<div class="kb-table kb-ftable" role="table"><div class="kb-tr kb-th" role="row"><span></span><span>Name</span><span>Kind</span><span>Visibility</span><span>Updated</span></div>
          ${list.slice(0, 400).map(k => `<div class="kb-tr" role="row"><span><input type="checkbox" data-kb-sel="${k.id}" ${sel.has(k.id) ? "checked" : ""} aria-label="Select ${esc(k.title)}"></span>
            <button type="button" class="kb-cell-main" data-kb-item="${k.id}">${icon(k.type === "idea" ? "bulb" : KIND_IC[k.data.kind] || "note")}<span><b>${esc(k.title)}</b><small>${t ? `${esc(k.path)} · ` : ""}${(k.tags || []).map(x => `#${esc(x)}`).join(" ")} ${esc(k.body)}</small></span></button>
            <span class="kb-faint">${esc(k.type === "source" ? KIND_L[k.data.kind] || "Source" : k.type_label)}<small>${esc(kt(k.ktype))}</small></span>
            <span>${vis(k.visibility)}${k.people ? chip("run", `${k.people} ${k.people === 1 ? "person" : "people"}`, "users") : ""}</span><span class="kb-faint">${when(k.updated)}</span></div>`).join("")}</div>`
          : empty(t ? `Nothing matches “${esc(find)}”.` : kids.length ? "" : msgs > 0 ? `${plural(msgs, "message")} live here: <button type="button" class="linkbtn" data-kb-tab="comms">open Communications</button>.` : "This folder is empty. Capture something here or move items into it.")}
      </section></div>`;
  }

  function sharedView() {
    const xs = D.personal.shared_with_me;
    if (shared) return `<button type="button" class="linkbtn kb-back" data-kb="shared-back">${icon("left")}Shared with me</button>
      <div class="kb-detail"><div class="kb-main">${card(KIND_IC[shared.data.kind] || "book", esc(shared.title), `${chip("run", `Shared by ${esc(shared.owner)}`, "users")} ${chip("none", "Read only", "lock")}`,
        `${shared.data.about ? `<p class="kb-note">${esc(shared.data.about)}</p>` : ""}<pre class="kb-pre kb-orig">${esc(shared.body)}</pre>
         ${(shared.data.sections || []).length ? `<h4>Key sections</h4><ol class="kb-sections">${shared.data.sections.map(x => `<li>${x.start ? `<span class="kb-cite">${esc(x.start)}</span>` : ""}<b>${esc(x.title)}</b><small>${esc(x.summary)}</small></li>`).join("")}</ol>` : ""}
         <form class="kb-row" data-kb-form="copy-shared"><label><span>Save a copy in</span><select name="path">${folderOpts("/00-Inbox/Unprocessed")}</select></label><button class="btn primary">${icon("plus")}Save a copy to My Knowledge</button></form>
         <p class="kb-note">A copy is yours and private: share it with your agents if you want them to read it. ${esc(shared.owner)} can stop sharing the original at any time.</p>`)}</div>
        <aside class="kb-side">${card("flag", "Provenance", "", `<dl class="kb-dl">${[["Owner", shared.owner], ["Source", shared.provenance.source], ["Platform", shared.provenance.platform], ["Updated", new Date(shared.updated * 1000).toLocaleString()], ["Version", `v${shared.version}`]].filter(([, v]) => v).map(([t, v]) => `<dt>${t}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`)}</aside></div>`;
    return `<button type="button" class="linkbtn kb-back" data-kb-folder="/00-Inbox">${icon("left")}My folders</button><p class="kb-lede2">What teammates shared with you, read only. Save a copy to keep it in your own folders.</p>
      <div class="kb-table" role="table"><div class="kb-tr kb-th" role="row"><span>Item</span><span>From</span><span>Shared</span><span>Updated</span></div>
      ${xs.map(x => `<button type="button" class="kb-tr" role="row" data-kb-shared="${x.id}"><span class="kb-cell-main">${icon(KIND_IC[x.kind] || "book")}<span><b>${esc(x.title)}</b><small>${esc(x.body)}</small></span></span>
        <span>${esc(x.owner)}</span><span class="kb-faint">${when(x.shared)}</span><span class="kb-faint">${when(x.updated)}</span></button>`).join("")}</div>`;
  }

  // ---------- one item (My Knowledge) ----------
  function itemView() {
    const k = item, p = k.provenance || {}, ext = k.trust !== "yours", L = D.personal.labels, src_ = k.type === "source", pr = k.data.processing;
    const canAdopt = ["agent", "skill", "workflow", "strategy"].includes(k.type) && ext && !k.proposals.some(x => x.status === "pending");
    const lock = k.trust === "external" && ["agent", "workflow", "tool", "file", "run"].includes(k.type);
    const pub = k.published;
    return `<button type="button" class="linkbtn kb-back" data-kb="back">${icon("left")}${esc(k.path || "Back")}</button>
      <div class="kb-detail"><div class="kb-main">
        ${card(src_ ? KIND_IC[k.data.kind] || "file" : k.type === "agent" ? "bot" : k.type === "tool" ? "wrench" : k.type === "workflow" ? "route" : "book", esc(k.title), `${trust(k.trust)} ${chip("none", esc(src_ ? "Source · " + (KIND_L[k.data.kind] || "file").toLowerCase() : k.type_label))} ${vis(k.visibility)}`,
          `${ext ? `<p class="kb-banner">${icon("shield")}${src_ && k.data.kind === "message" ? "A message someone wrote" : src_ ? "Read from outside AXoR" : `Imported ${k.trust === "external" ? "from another agent platform" : "from an earlier workspace"}`}: this is data, not instructions.${k.data.inert ? " It describes a tool or code that is kept as a record and never run." : ""}</p>` : ""}
          ${src_ ? `${k.data.about ? `<p class="kb-note">${esc(k.data.about)}</p>` : ""}${k.data.error ? `<p class="kb-note kb-warn">Not read: ${esc(k.data.error)}</p>` : ""}
            ${k.data.file ? `<p class="kb-row kb-filebar">${icon(KIND_IC[k.data.kind] || "file")}<span>${esc(k.data.file.name)} · ${(k.data.file.size / 1e6).toFixed(2)} MB</span>
              <a class="btn sm" href="${K}/items/${k.id}/original" download>${icon("download")}Download the original</a>
              <button type="button" class="btn sm" data-kb="read-again">${icon("cycle")}Read it again</button></p>` : ""}
            ${k.data.summary ? `<p class="kb-text">${esc(k.data.summary)}</p>` : ""}
            ${(k.data.sections || []).length ? `<h4>Key sections</h4><ol class="kb-sections">${k.data.sections.map(x => `<li>${x.start ? `<span class="kb-cite">${esc(x.start)}</span>` : ""}<b>${esc(x.title)}</b><small>${esc(x.summary)}</small></li>`).join("")}</ol>` : ""}
            ${k.data.picture?.tags?.length ? `<p class="kb-tags">${k.data.picture.tags.map(t => `<span>${esc(t)}</span>`).join("")}</p>` : ""}
            ${k.data.url ? `<p class="kb-note"><a href="${esc(k.data.url)}" target="_blank" rel="noopener noreferrer">${esc(k.data.url)}</a>${k.data.fetched_at ? ` · read ${esc(k.data.fetched_at)}` : ""}${k.data.truncated ? " · cut at 200,000 characters" : ""}</p>` : ""}
            ${k.data.kind === "message" ? `<p class="kb-note">${esc(PLAT[k.data.platform] || "")}${k.data.workspace ? ` · ${esc(k.data.workspace)}` : ""} · #${esc(k.data.channel || "")} · ${esc(k.data.author || "")}${k.data.ts ? ` · ${new Date(k.data.ts * 1000).toLocaleString()}` : ""}${k.data.thread ? " · in a thread" : ""}</p>` : ""}
            <details ${k.body.length < 1500 ? "open" : ""}><summary>The original text (${k.body.length.toLocaleString()} characters)</summary><pre class="kb-pre kb-orig">${esc(k.body)}</pre></details>` : ""}
          <form class="kb-form" data-kb-form="item"><label><span>Title</span><input name="title" value="${esc(k.title)}" maxlength="200" required></label>
          ${src_ ? "" : `<label><span>Text</span><textarea name="body" rows="${Math.min(18, Math.max(5, (k.body.match(/\n/g) || []).length + 2))}" maxlength="20000">${esc(k.body)}</textarea></label>`}
          <div class="kb-row"><label><span>Folder</span><select name="path">${folderOpts(k.path)}</select></label><label><span>Knowledge type</span><select name="ktype">${Object.entries(L.ktypes).map(([x, [l, h]]) => `<option value="${x}" ${k.ktype === x ? "selected" : ""} title="${esc(h)}">${l}</option>`).join("")}</select></label>
            <label class="kb-grow"><span>Tags</span><input name="tags" value="${esc((k.tags || []).join(", "))}" maxlength="300"></label></div>
          <div class="kb-row end"><label><span>Who reads it</span><select name="reach">${Object.entries(REACH).map(([r, [, l]]) => `<option value="${r}" ${k.reach === r ? "selected" : ""} ${r === "teams" && lock ? "disabled" : ""}>${l}${r === "teams" && lock ? " (not for imported configs)" : ""}</option>`).join("")}</select></label>
          <button class="btn primary">${icon("check")}Save</button></div></form>
          <div class="kb-row">${D.personal.can_model ? `<button type="button" class="btn" data-kb-process="${k.id}">${icon("sparkle")}${pr ? "Organize again" : "Organize with AI"}</button>` : ""}
            <button type="button" class="btn" data-kb="derive-open">${icon("book")}Make a knowledge record</button>
            ${pub ? "" : `<button type="button" class="btn" data-kb="publish-one">${icon("group")}Publish to the company…</button>`}
            ${canAdopt ? `<button type="button" class="btn" data-kb="propose">${icon("check")}Adopt as mine…</button>` : ""}
            <button type="button" class="btn" data-kb="archive">${icon(k.status === "archived" ? "undo" : "inbox")}${k.status === "archived" ? "Keep again" : "Archive"}</button>
            <button type="button" class="btn danger" data-kb="delete">${icon("trash")}Delete</button></div>
          <div id="kb-derive" hidden>${deriveForm(k)}</div>`)}
        ${pr ? processingCard(k, pr) : ""}
        ${k.data.fields ? card("code", "The original's other fields", "", `<pre class="kb-pre">${esc(k.data.fields)}</pre>`) : ""}
        ${k.proposals.length ? card("check", "Proposals", "", k.proposals.map(proposal).join("")) : ""}
      </div><aside class="kb-side">
        ${pub ? card("group", "In the company", "", `<p class="kb-text">${vis(k.visibility)}</p><button type="button" class="linkbtn" data-kb-ref="kb:${pub.id}">Open the company record</button>`) : ""}
        ${peopleCard(k)}
        ${linksCard(k)}
        ${card("flag", "Provenance", "", `<dl class="kb-dl">${[["Source", p.source || (k.trust === "yours" ? "You" : "–")], ["Platform", p.platform], ["Original", p.origin], ["Original id", p.original_id], ["Parent", p.parent],
            ["File", p.file], ["Imported", p.imported ? `${new Date(p.imported * 1000).toLocaleString()} by ${p.imported_by}` : ""], ["How", p.derived]].filter(([, v]) => v)
            .map(([t, v]) => `<dt>${t}</dt><dd>${t === "Original" && /^https?:\/\//.test(v) ? `<a href="${esc(v)}" target="_blank" rel="noopener noreferrer">${esc(v)}</a>` : esc(v)}</dd>`).join("")}</dl>
          ${k.data.quote ? `<p class="kb-note">Quote from the source${k.data.verified ? " (found in the file)" : " (not found in the file: check it)"}: “${esc(k.data.quote)}”</p>` : ""}
          ${k.source ? `<button type="button" class="linkbtn" data-kb-src="${k.source.id}">Open the import</button>` : ""}`)}
        ${versions(k)}
        <p class="kb-note">Read by agents ${plural(k.used || 0, "time")}.</p>
      </aside></div>`;
  }
  function peopleCard(k) {
    const P = k.people || [];
    return card("users", "People", `<span class="kb-faint">${P.length ? `${P.length} can read it` : "only you"}</span>`, `${P.length ? `<ul class="kb-list">${P.map(u => `<li><span>${icon("users")}${esc(u.username)}<small class="kb-faint">since ${when(u.since)}</small></span><button type="button" class="linkbtn" data-kb-unshare="${u.id}">Stop sharing</button></li>`).join("")}</ul>` : ""}
      <form class="kb-row" data-kb-form="share"><label class="kb-grow"><span>Share with (usernames, comma-separated)</span><input name="who" list="kb-people" required placeholder="Type a name" data-kb-people></label><button class="btn sm">${icon("userplus")}Share</button></form>
      <datalist id="kb-people">${(people || []).map(u => `<option value="${esc(u.username)}"></option>`).join("")}</datalist>
      <p class="kb-note">They read it, read only, under Shared with me, and can save their own copy. Their agents never read it.${k.data.kind === "message" ? " It's someone's message: share it only if they'd agree." : ""}</p>`);
  }
  async function loadPeople() { if (people) return; try { people = await api(`${K}/people`); } catch { people = []; } const dl = document.getElementById("kb-people"); if (dl) dl.innerHTML = people.map(u => `<option value="${esc(u.username)}"></option>`).join(""); }
  const deriveForm = k => `<form class="kb-form kb-card kb-inset" data-kb-form="derive"><h4>A knowledge record from “${esc(k.title)}”</h4><p class="kb-note">A record of its own, linked back to this one as its source.</p>
    <label><span>Title</span><input name="title" required maxlength="200" value="${esc(k.data.processing?.record?.title || "")}"></label>
    <label><span>What it says (stands on its own)</span><textarea name="body" rows="5" required maxlength="20000">${esc(k.data.processing?.record?.body || "")}</textarea></label>
    <div class="kb-row end"><label><span>Type</span><select name="ktype">${Object.entries(D.personal.labels.ktypes).map(([x, [l]]) => `<option value="${x}" ${k.ktype === x ? "selected" : ""}>${l}</option>`).join("")}</select></label><button class="btn primary">${icon("plus")}Make it</button></div></form>`;
  function processingCard(k, pr) {
    return card("sparkle", "Suggestions", `<span class="kb-faint">${esc(pr.model || "")} · ${when(pr.at)}</span>`, `<form class="kb-form" data-kb-form="organize">
      ${pr.summary ? `<p class="kb-text">${esc(pr.summary)}</p>` : ""}
      ${pr.folder ? `<label class="kb-check"><input type="checkbox" name="folder" checked> Move to <b>${esc(pr.folder)}</b></label>` : ""}
      ${pr.tags?.length ? `<label class="kb-check"><input type="checkbox" name="tags" checked> Tag it ${pr.tags.map(t => `<span class="kb-tag">#${esc(t)}</span>`).join(" ")}</label>` : ""}
      <label class="kb-check"><input type="checkbox" name="ktype" ${pr.ktype !== k.ktype ? "checked" : ""}> Knowledge type: <b>${esc(kt(pr.ktype))}</b></label>
      ${pr.links?.length ? `<h4>Connections</h4>${pr.links.map((l, i) => `<label class="kb-check"><input type="checkbox" name="link" value="${i}" checked> <span>${esc(relLabel(l))} <b>${esc(l.label)}</b> <small class="kb-faint">${esc(l.why)}</small></span></label>`).join("")}` : ""}
      ${pr.record ? `<h4>A record to derive</h4><label class="kb-check"><input type="checkbox" name="record" checked> <span><b>${esc(pr.record.title)}</b><small class="kb-faint">${esc(pr.record.body)}</small></span></label>` : ""}
      ${pr.claims?.length ? `<h4>Claims to check</h4><ul class="kb-plain">${pr.claims.map(c => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
      <div class="kb-row end"><button class="btn primary">${icon("check")}Apply what's ticked</button></div></form>`);
  }
  function linksCard(k) {
    const opts = [...(D.personal?.items || []), ...(D.personal?.ideas || [])].filter(x => x.id !== k.id).slice(0, 600);
    const R = (D.personal || D.company).labels.rels;
    return card("link", "Connections", "", `${k.links.length ? `<ul class="kb-links">${k.links.map(l => `<li><span class="kb-faint">${esc(relLabel(l))}</span>${l.item ? `<button type="button" class="linkbtn" data-kb-ref="kb:${l.item}">${esc(l.label)}</button>` : l.go && navOk(l.go.view) ? `<button type="button" class="linkbtn" ${go(l.go)}>${esc(l.label)}</button>` : `<b>${esc(l.label)}</b>`}
        <small>${esc(l.kind || "")}${l.why ? ` · ${esc(l.why)}` : ""}</small>${l.id && R[l.rel] ? `<button type="button" class="iconbtn" data-kb-unlink="${l.id}" title="Remove the link" aria-label="Remove the link">${icon("close")}</button>` : ""}</li>`).join("")}</ul>` : empty("No connections yet.")}
      <form class="kb-form kb-linkform" data-kb-form="link"><div class="kb-row"><label><span>This record</span><select name="rel">${Object.entries(R).map(([x, [l]]) => `<option value="${x}">${l.toLowerCase()}</option>`).join("")}</select></label>
        <label class="kb-grow"><span>Record</span><input name="to" list="kb-recs" required placeholder="Type to find a record"></label></div>
        <datalist id="kb-recs">${opts.map(x => `<option value="${esc(x.title)} · kb:${x.id}"></option>`).join("")}${(D.company?.records || []).filter(x => x.id !== k.id).slice(0, 300).map(x => `<option value="${esc(x.title)} · company · kb:${x.id}"></option>`).join("")}</datalist>
        <div class="kb-row end"><input name="why" maxlength="300" placeholder="Why (optional)" aria-label="Why"><button class="btn sm">${icon("link")}Connect</button></div></form>`);
  }
  const versions = k => card("undo", "Versions", "", `<ul class="kb-versions">${k.versions.map(v => `<li><b>v${v.version}</b><span>${esc(v.note || "")}</span><span class="kb-faint">${when(v.ts)} · ${esc(v.by || "")}</span>${v.version !== k.version ? `<button type="button" class="linkbtn" data-kb-restore="${v.version}">Restore</button>` : `<span class="kb-faint">current</span>`}</li>`).join("")}</ul>`);

  // ---------- Sources: files and web pages, imports, adopt ----------
  function sources() {
    const d = D.personal, w = d.proposals.filter(p => p.status === "pending").length, pv = d.sources.filter(s => s.status === "preview").length;
    const subs = [["assets", "file", "Files & web pages", d.counts.sources], ["imports", "upload", "Imports", pv ? `<span class="hq-n alert">${pv}</span>` : d.sources.filter(s => s.kind !== "comms").length], ["adopt", "check", "Adopt", w ? `<span class="hq-n alert">${w}</span>` : ""]];
    const nav = `<div class="kb-subtabs" role="group" aria-label="Sources">${subs.map(([k, ic, l, n]) => `<button type="button" class="chip" data-kb-sub="${k}" aria-pressed="${sub === k}">${icon(ic)}${l}${n ? ` <em>${n}</em>` : ""}</button>`).join("")}</div>`;
    if (sub === "imports") return nav + (src ? sourceView() : imports());
    if (sub === "adopt") return nav + adopt();
    const list = d.items.filter(k => k.type === "source");
    return `${nav}<p class="kb-lede2">Originals, kept with where they came from: a file, a web page, pasted text or a conversation. What you learn from one becomes a record of its own that links back to it.</p>
      <div class="kb-row kb-capbar">${CAPS.filter(c => ["url", "file", "paste", "conversation"].includes(c[0])).map(([v, ic, l]) => `<button type="button" class="btn" data-kb-cap="${v}">${icon(ic)}Add ${l.toLowerCase()}</button>`).join("")}</div>
      ${list.length ? `<div class="kb-table kb-stable" role="table"><div class="kb-tr kb-th" role="row"><span>Source</span><span>Folder</span><span>Visibility</span><span>Added</span></div>
        ${list.map(k => `<button type="button" class="kb-tr" role="row" data-kb-item="${k.id}"><span class="kb-cell-main">${icon(KIND_IC[k.data.kind] || "file")}<span><b>${esc(k.title)}</b><small>${esc(KIND_L[k.data.kind] || "Source")}${k.data.about ? ` · ${esc(k.data.about)}` : ""}${k.data.error ? " · not read" : ""}</small></span></span>
          <span class="kb-faint">${esc(k.path)}</span><span>${vis(k.visibility)}</span><span class="kb-faint">${when(k.created)}</span></button>`).join("")}</div>` : empty("No sources yet. Add a web page, a text file or paste a conversation.")}`;
  }
  function imports() {
    const form = (kind, ic, title, lede) => card(ic, title, "", `<p class="kb-lede2">${lede}</p><form class="kb-form" data-kb-form="upload" data-kind="${kind}">
        <label class="kb-file"><input type="file" name="file" accept=".json,.jsonl,.csv,.tsv,.md,.markdown,.txt,application/json,text/*"><span>${icon("upload")}Choose a file</span><em class="kb-faint">JSON, JSONL, CSV, Markdown or text, up to 10 MB</em></label>
        <details><summary class="kb-faint">…or paste text</summary><textarea name="text" rows="5" placeholder="Paste an export, notes or a lessons-learned document"></textarea></details>
        <div class="kb-row"><label class="kb-grow"><span>Name</span><input name="name" maxlength="120" placeholder="${kind === "external" ? "e.g. CrewAI research crew, March" : "e.g. My old AXoR workspace"}"></label>
          ${kind === "external" ? `<label><span>Platform</span><input name="platform" maxlength="80" placeholder="e.g. LangGraph, AutoGen"></label>` : ""}</div>
        <label><span>Where the original lives (link or path, kept on every item)</span><input name="origin" maxlength="500" placeholder="https://… or /path/to/workspace"></label>
        <div class="kb-row end"><button class="btn primary">${icon("upload")}Read the file</button></div></form>`);
    const rows = D.personal.sources.filter(s => s.kind !== "comms");
    return `<div class="kb-grid two">${form("workspace", "folder", "An earlier workspace", "Projects, agent configurations, task histories, files, workflows and notes. Takes the <b>Export</b> file (from here or another AXoR), a bundle from <code>tools/mining-import.py</code>, or any export with lists such as agents, tasks, runs, workflows, skills, notes or files.")}
        ${form("external", "globe", "External agents' experience", "Agent histories, successful and failed tasks, workflows, skills, tools, lessons and performance reports from other agent platforms. Kept private until you share it; compare it with your agents after you apply it.")}</div>
      ${card("list", "Imports", "", rows.length ? `<div class="kb-table" role="table"><div class="kb-tr kb-th" role="row"><span>Import</span><span>Kind</span><span>Status</span><span>When</span></div>
        ${rows.map(s => `<button type="button" class="kb-tr" role="row" data-kb-src="${s.id}"><span class="kb-cell-main"><span><b>${esc(s.name)}</b><small>${esc(s.format)}${s.platform ? ` · ${esc(s.platform)}` : ""}${s.status === "applied" ? ` · ${s.counts.created} added${s.counts.replaced ? `, ${s.counts.replaced} replaced` : ""}` : ""}${s.redacted ? ` · ${s.redacted} secrets taken out` : ""}</small></span></span>
          <span>${s.kind === "external" ? chip("warn", "External") : chip("run", "Workspace")}</span><span>${chip({ preview: "warn", applied: "ok", undone: "none" }[s.status] || "none", esc(s.status))}</span><span class="kb-faint">${when(s.created)}</span></button>`).join("")}</div>` : empty("No imports yet."))}`;
  }
  function sourceView() {
    const s = src, prev = s.status === "preview", sel_ = picked instanceof Set ? picked : new Set(s.candidates.filter(c => c.pick).map(c => c.key));
    picked = sel_;
    const types = Object.entries(s.by_type);
    const dupBadge = c => !c.dup ? "" : c.dup.kind === "same" ? chip("none", "Already kept") : c.dup.kind === "repeat" ? chip("none", "Repeated in the file")
      : `${chip("warn", "Similar")}<small class="kb-faint">to “${esc(c.dup.title)}”</small>${prev ? `<select data-kb-resolve="${c.key}" aria-label="What to do with it"><option value="both" ${c.resolve !== "replace" && c.resolve !== "skip" ? "selected" : ""}>Keep both</option><option value="replace" ${c.resolve === "replace" ? "selected" : ""}>Replace it</option><option value="skip" ${c.resolve === "skip" ? "selected" : ""}>Skip</option></select>` : ""}`;
    return `<button type="button" class="linkbtn kb-back" data-kb="back">${icon("left")}All imports</button>
      ${card(s.kind === "external" ? "globe" : "folder", esc(s.name), `${chip({ preview: "warn", applied: "ok", undone: "none" }[s.status] || "none", esc(s.status))}`,
        `<p class="kb-note">${esc(s.format)} · ${plural(s.candidates.length, "record")}${s.platform ? ` · ${esc(s.platform)}` : ""}${s.origin ? ` · original: ${esc(s.origin)}` : ""} · by ${esc(s.by_user)} ${when(s.created)}${s.redacted ? ` · <b>${s.redacted} secrets taken out</b>` : ""}${s.tokens ? ` · ${s.tokens.toLocaleString()} tokens` : ""}</p>
        ${s.summary ? `<p class="kb-text">${esc(s.summary)}</p>` : ""}${s.warnings.length ? `<ul class="kb-plain kb-warn">${s.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
        ${prev ? `<div class="kb-applybar"><span>${sel_.size} of ${s.candidates.length} picked</span>
            <span class="kb-chiprow">${[["all", "All"], ["none", "None"], ...types.map(([t, n]) => [t, `${D.personal.labels.types[t] || t} (${n})`])].map(([v, l]) => `<button type="button" class="chip" data-kb-pick="${v}">${esc(l)}</button>`).join("")}</span>
            <label><span>Who reads it</span><select id="kb-reach">${Object.entries(REACH).map(([r, [, l]]) => `<option value="${r}" ${r === s.default_reach ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <button type="button" class="btn" data-kb="extract" ${D.personal.can_model ? "" : "disabled title='No model is connected'"}>${icon("sparkle")}Pull out lessons with AI</button>
            <button type="button" class="btn primary" data-kb="apply" ${sel_.size ? "" : "disabled"}>${icon("check")}Apply ${sel_.size}</button><button type="button" class="btn" data-kb="discard">${icon("trash")}Discard</button></div>
            ${s.kind === "external" ? `<p class="kb-note">${icon("shield")} External records start private; imported agents, workflows, tools, files and runs never reach competition teams.</p>` : ""}`
          : `<div class="kb-row">${s.status === "applied" ? `<button type="button" class="btn" data-kb="compare" ${D.personal.can_model && s.capabilities ? "" : "disabled"} title="${s.capabilities ? "Ask the model whether to adopt, adapt or reject each capability" : "No agents, skills, workflows, tools, strategies or lessons in this import"}">${icon("swap")}Compare with my agents</button>
            <button type="button" class="btn" data-kb="undo">${icon("undo")}Undo the import</button>` : ""}${s.counts.kept ? `<span class="kb-note">${s.counts.kept} items you changed were kept when it was undone.</span>` : ""}</div>`}`)}
      ${s.proposals.length ? card("check", "Recommendations", "", s.proposals.map(proposal).join("")) : ""}
      ${card("list", prev ? "What's in it" : "What was in it", "", `<ul class="kb-cands">${s.candidates.map(c => `<li class="${c.derived ? "derived" : ""}">
          ${prev ? `<input type="checkbox" data-kb-cand="${c.key}" ${sel_.has(c.key) ? "checked" : ""} aria-label="Import ${esc(c.title)}">` : ""}
          <div><div class="kb-cand-h"><b>${esc(c.title)}</b>${chip("none", esc(D.personal.labels.types[c.type] || c.type))}${c.derived ? chip(c.verified ? "ok" : "warn", c.verified ? "AI · quote checked" : "AI · quote not found", "sparkle") : ""}
            ${c.outcome && c.outcome !== "unknown" ? chip(c.outcome === "success" ? "ok" : "bad", esc(c.outcome)) : ""}${c.inert ? chip("none", "Never run", "ban") : ""}${dupBadge(c)}</div>
            <p>${esc(c.body)}${c.size > 500 ? ` <span class="kb-faint">(${c.size.toLocaleString()} characters)</span>` : ""}</p>${c.applies_when ? `<small class="kb-faint">Applies when: ${esc(c.applies_when)}</small>` : ""}
            ${c.parent ? `<small class="kb-faint">Part of: ${esc(c.parent)}</small>` : ""}</div></li>`).join("")}</ul>`)}`;
  }
  function proposal(p) {
    const c = p.change || {}, pend = p.status === "pending", [vt, vl] = VERDICT[p.verdict] || ["none", p.verdict], [st, sl] = PSTATUS[p.status] || ["none", p.status];
    const field = (k, label, rows = 1) => c[k] === undefined ? "" : rows > 1 ? `<label><span>${label}</span><textarea name="${k}" rows="${rows}" ${pend ? "" : "readonly"}>${esc(c[k])}</textarea></label>`
      : `<label><span>${label}</span><input name="${k}" value="${esc(c[k])}" ${pend ? "" : "readonly"}></label>`;
    return `<article class="kb-prop ${picked === p.id ? "focus" : ""}" id="kb-prop-${p.id}"><div class="kb-prop-h">${chip(vt, vl)}<b>${esc(p.title)}</b>${chip(st, sl)}<span class="kb-faint">${when(p.created)}</span></div>
      ${p.why ? `<p class="kb-text">${esc(p.why)}</p>` : ""}${p.compare ? `<p class="kb-note">${icon("swap")} ${esc(p.compare)}</p>` : ""}
      ${c.kind ? `<form class="kb-form" data-kb-form="approve" data-pid="${p.id}" data-hash="${esc(p.hash || "")}">
        ${pend ? `<p class="kb-banner">${icon("shield")}${c.kind === "extend_agent" ? `This text will be added to ${esc(c.agent)}'s instructions` : c.kind === "new_agent" ? "This becomes a new agent's instructions (it starts paused)" : "This becomes a skill your agents can be given"}. It came from imported material: read it, edit it if you like, then approve.</p>` : ""}
        ${field("name", "Name")}${field("role", "Role")}${field("description", "Description")}${field("instructions", "Instructions", 8)}${field("body", "Skill text", 8)}${field("addition", "Addition to the instructions", 5)}
        ${pend ? `<div class="kb-row end"><button type="button" class="btn" data-kb-decline="${p.id}">${icon("ban")}Decline</button><button class="btn primary">${icon("check")}Approve and apply</button></div>` : ""}</form>` : ""}
      ${p.result ? `<p class="kb-note">${esc(p.result)}${p.decided_by ? ` — ${esc(p.decided_by)}, ${when(p.decided)}` : ""}</p>` : ""}
      <div class="kb-row">${p.status === "applied" ? `<button type="button" class="btn" data-kb-rollback="${p.id}">${icon("undo")}Roll back</button>${p.applied_ref?.startsWith("hub:") ? `<button type="button" class="linkbtn" ${go({ view: "agents" })}>Open in Agents</button>` : ""}` : ""}
        ${p.status === "noted" ? `<button type="button" class="btn sm" data-kb-decline="${p.id}">Dismiss</button>` : ""}${p.item_id && !item ? `<button type="button" class="linkbtn" data-kb-item="${p.item_id}">The imported item</button>` : ""}</div></article>`;
  }
  function adopt() {
    const P = D.personal.proposals, pend = P.filter(p => p.status === "pending"), rest = P.filter(p => p.status !== "pending");
    return `<p class="kb-lede2">Recommendations from comparing imported capabilities with your agents (Imports → an applied import → <b>Compare with my agents</b>), and items you chose to adopt. Approving applies exactly the change shown.</p>
      ${card("check", "Waiting for you", `<span class="kb-faint">${pend.length}</span>`, pend.length ? pend.map(proposal).join("") : empty("Nothing waits for your approval."))}
      ${rest.length ? card("clock", "Decided and recommendations", "", rest.map(proposal).join("")) : ""}`;
  }

  // ---------- Communications ----------
  async function loadComms() {
    const p = new URLSearchParams(Object.entries(cf).filter(([, v]) => v));
    cLoading = true;
    try { comms = await api(`${K}/comms?${p}`); } catch (e) { comms = { error: e.message }; } finally { cLoading = false; }
    if (space === "personal" && tabs.personal === "comms" && !item) render();
  }
  function commsView() {
    if (!comms) return Loading.line("Reading your messages…");
    if (comms.error) return `<div class="empty">${esc(comms.error)}</div>`;
    const c = comms, by = {};
    c.channels.forEach(x => (by[x.platform] = by[x.platform] || []).push(x));
    const sl = c.slack || {};
    return `<div class="kb-comms"><aside class="kb-tree">
        <div class="kb-tree-h"><b>${icon("chat")}Channels</b></div>
        <ul><li><button type="button" class="kb-node ${!cf.platform ? "on" : ""}" data-kb-chan="" style="--d:0">${icon("inbox")}<span>All messages</span><em>${c.channels.reduce((a, x) => a + x.n, 0)}</em></button></li>
          ${Object.entries(PLAT).map(([p, l]) => `<li><button type="button" class="kb-node ${cf.platform === p && !cf.channel ? "on" : ""}" data-kb-chan="${p}" style="--d:0">${icon("hash")}<span>${l}</span><em>${(by[p] || []).reduce((a, x) => a + x.n, 0) || ""}</em></button></li>
            ${(by[p] || []).map(x => `<li><button type="button" class="kb-node ${cf.platform === p && cf.channel === x.channel ? "on" : ""}" data-kb-chan="${p}|${esc(x.channel)}" style="--d:1"><span>#${esc(x.channel)}</span><em>${x.n}</em></button></li>`).join("")}`).join("")}</ul>
        ${card("radio", "Connectors", `<button type="button" class="linkbtn" data-kb-tab="settings">Manage</button>`, connList(sl, D.personal.connectors || [], true))}
      </aside><section>
        <form class="kb-row kb-commsbar" data-kb-form="comms-search"><input type="search" name="q" value="${esc(cf.q)}" placeholder="Search messages and authors" aria-label="Search messages" class="kb-grow"><button class="btn sm">${icon("search")}Search</button></form>
        ${csel.size ? `<form class="kb-applybar" data-kb-form="comms-note"><span>${csel.size} selected</span><label class="kb-grow"><span>Save as a note titled</span><input name="title" required maxlength="200" placeholder="e.g. Embedding cache discussion"></label>
          <label><span>In</span><select name="path">${folderOpts("/07-Knowledge/Concepts")}</select></label><button class="btn sm primary">${icon("note")}Save as a note</button><button type="button" class="linkbtn" data-kb="comms-clear">Clear</button></form>` : ""}
        ${c.messages.length ? `<ul class="kb-msgs">${c.messages.map(m => `<li class="${m.thread ? "reply" : ""}"><input type="checkbox" data-kb-csel="${m.id}" ${csel.has(m.id) ? "checked" : ""} aria-label="Select the message">
            <div><div class="kb-msg-h"><b>${esc(m.author || "")}</b><span class="kb-faint">${esc(PLAT[m.platform] || "")} · #${esc(m.channel || "")}${m.ts ? ` · ${new Date(m.ts * 1000).toLocaleString()}` : ""}${m.thread ? " · reply" : ""}</span>
              <button type="button" class="linkbtn" data-kb-item="${m.id}">Open</button></div><p>${esc(m.text)}</p>
              ${m.attachments.length ? `<small class="kb-faint">${icon("clip")}${m.attachments.map(esc).join(", ")}</small>` : ""}${m.urls.length ? `<small class="kb-faint">${m.urls.map(u => esc(u)).join(" · ")}</small>` : ""}</div></li>`).join("")}</ul>
          ${c.total > c.messages.length ? `<p class="kb-note">Showing ${c.messages.length} of ${c.total}: search or pick a channel.</p>` : ""}` : empty(c.channels.length ? "No messages match." : "No messages yet. Import an export or sync the connected Slack channel.")}
        ${card("upload", "Import an export", "", `<form class="kb-form" data-kb-form="comms-import"><div class="kb-row"><label><span>Platform</span><select name="platform"><option value="auto">Tell from the file</option>${Object.entries(PLAT).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
            <label class="kb-grow"><span>Channel name (Slack day files don't hold it)</span><input name="channel" maxlength="120" placeholder="e.g. sn62-dev"></label></div>
          <label class="kb-file"><input type="file" name="file" accept=".json,application/json" required><span>${icon("upload")}Choose the export (JSON)</span><em class="kb-faint">Read only: messages, authors, times, threads, attachments' names and links are kept. Up to 20 MB.</em></label>
          <div class="kb-row end"><button class="btn primary">${icon("upload")}Import</button></div></form>
          ${c.imports.length ? `<ul class="kb-list">${c.imports.map(s => `<li><span>${esc(s.name)} <small class="kb-faint">${esc(s.summary || "")} · ${when(s.created)}</small></span>${s.status === "applied" ? `<button type="button" class="btn sm" data-kb-comms-undo="${s.id}">${icon("undo")}Undo</button>` : chip("none", esc(s.status))}</li>`).join("")}</ul>` : ""}`)}
      </section></div>`;
  }

  // ---------- Ideas ----------
  function ideas() {
    const d = D.personal, by = d.counts.by_stage, list = d.ideas.filter(i => stageF === "all" || i.stage === stageF);
    return `${card("bulb", "Add an idea", "", `<form class="kb-form kb-idea-form" data-kb-form="idea">
        <div class="kb-row"><label><span>Kind</span><select name="kind">${Object.entries(d.labels.kinds).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
        <label class="kb-grow"><span>Title</span><input id="kb-idea-title" name="title" required maxlength="200" placeholder="e.g. Let the Director reuse last competition's eval harness"></label></div>
        <label><span>Details</span><textarea name="body" rows="3" maxlength="20000" placeholder="What you want, why, constraints, what you've tried"></textarea></label>
        <div class="kb-row end"><label class="kb-check"><input type="checkbox" name="analyze" ${d.can_model ? "checked" : "disabled"}> Analyze it now with AI</label><button class="btn primary">${icon("plus")}Add</button></div></form>`)}
      <div class="kb-filters" role="group" aria-label="Stage">${["all", ...d.labels.stages].map(s => `<button type="button" class="chip" data-kb-stage="${s}" aria-pressed="${stageF === s}">${s === "all" ? "All" : s[0].toUpperCase() + s.slice(1)} <em>${s === "all" ? d.ideas.length : by[s] || 0}</em></button>`).join("")}</div>
      ${list.length ? `<div class="kb-ideas">${list.map(i => { const a = i.data.analysis, t = i.data.tasks || [];
        return `<button type="button" class="kb-idea" data-kb-idea="${i.id}"><div class="kb-idea-h">${chip(STAGE[i.stage] || "none", esc(i.stage))}<span class="kb-faint">${esc(d.labels.kinds[i.data.kind] || "Idea")}</span>${a ? `<span class="kb-faint">${esc(a.value)} value · effort ${esc(a.effort)}</span>` : ""}</div>
          <b>${esc(i.title)}</b><p>${esc(a?.summary || i.body || "No details yet.")}</p><div class="kb-idea-f"><span>${t.length ? `${t.filter(x => x.done).length}/${t.length} tasks` : "No tasks yet"}</span><span class="kb-faint">${when(i.updated)}</span></div></button>`; }).join("")}</div>`
        : empty(d.ideas.length ? "No ideas at this stage." : "No ideas yet. Write one above: the model links it to your work and suggests the first tasks.")}`;
  }
  function ideaView() {
    const i = idea, a = i.data.analysis, tasks = i.data.tasks || [], sug = i.data.suggested_tasks || [], hist = i.data.history || [], L = D.personal.labels;
    const at = L.stages.indexOf(i.stage);
    return `<button type="button" class="linkbtn kb-back" data-kb="back">${icon("left")}All ideas</button>
      <div class="kb-detail"><div class="kb-main">
        ${card("bulb", esc(i.title), `${chip(STAGE[i.stage] || "none", esc(i.stage))} ${vis(i.visibility)}`, `<p class="kb-text">${esc(i.body || "No details.")}</p>
          <div class="kb-stepper" role="group" aria-label="Stage">${L.stages.map((s, n) => `<button type="button" data-kb-move="${s}" class="${n < at && s !== "dropped" ? "past" : ""}" aria-pressed="${s === i.stage}">${s}</button>`).join("")}</div>
          <form class="kb-row" data-kb-form="stage-note"><input name="note" maxlength="1000" placeholder="A note for the next stage change (optional)" aria-label="Note for the stage change"></form>
          <div class="kb-row"><button type="button" class="btn" data-kb="analyze" ${D.personal.can_model ? "" : "disabled title='No model is connected'"}>${icon("sparkle")}${a ? "Analyze again" : "Analyze with AI"}</button>
            <button type="button" class="btn" data-kb-edit-idea>${icon("edit")}Edit</button>${i.published ? "" : `<button type="button" class="btn" data-kb="publish-one">${icon("group")}Publish to the company…</button>`}</div>`)}
        ${a ? card("sparkle", "Analysis", `<span class="kb-faint">${esc(a.category)} · ${esc(a.value)} value · effort ${esc(a.effort)} · ${when(a.at)}</span>`, `<p class="kb-text">${esc(a.summary)}</p>
          ${a.tags?.length ? `<p class="kb-tags">${a.tags.map(t => `<span>${esc(t)}</span>`).join("")}</p>` : ""}
          ${a.plan?.length ? `<h4>Plan</h4><ol class="kb-plan">${a.plan.map(p => `<li><b>${esc(p.step)}</b>${p.detail ? ` — ${esc(p.detail)}` : ""}</li>`).join("")}</ol>` : ""}
          ${a.risks?.length ? `<h4>Risks</h4><ul class="kb-plain">${a.risks.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
          ${a.measure ? `<h4>How you'll know it worked</h4><p class="kb-text">${esc(a.measure)}</p>` : ""}`) : ""}
        ${card("list", "Tasks", `<span class="kb-faint">${tasks.filter(t => t.done).length}/${tasks.length} done</span>`, `${tasks.length ? `<ul class="kb-tasks">${tasks.map((t, n) => `<li><label class="kb-check"><input type="checkbox" data-kb-task="${n}" ${t.done ? "checked" : ""}><span><b>${esc(t.title)}</b>${t.detail ? `<small>${esc(t.detail)}</small>` : ""}</span></label>
            <span class="kb-owner">${esc(OWNER[t.owner] || "You")}${OWNER_GO[t.owner] && navOk(OWNER_GO[t.owner]) ? ` <button type="button" class="linkbtn" ${go({ view: OWNER_GO[t.owner] })}>Open</button>` : ""}</span><button type="button" class="iconbtn" data-kb-task-rm="${n}" title="Remove task" aria-label="Remove task">${icon("close")}</button></li>`).join("")}</ul>` : empty("No tasks yet.")}
          ${sug.length ? `<h4>New suggestions</h4><ul class="kb-tasks">${sug.map((t, n) => `<li><span><b>${esc(t.title)}</b><small>${esc(t.detail)}</small></span><span class="kb-owner">${esc(OWNER[t.owner] || "You")}</span><button type="button" class="btn sm" data-kb-task-add="${n}">${icon("plus")}Add</button></li>`).join("")}</ul>` : ""}
          <form class="kb-row" data-kb-form="task"><input name="title" maxlength="200" placeholder="Add a task" aria-label="New task" required><select name="owner" aria-label="Who does it">${Object.entries(OWNER).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select><button class="btn sm">${icon("plus")}Add</button></form>`)}
        ${["done", "evaluated"].includes(i.stage) || i.data.outcome ? card("trophy", "Evaluation", "", `<form class="kb-form" data-kb-form="evaluate"><label><span>What happened (results, numbers, what you'd do differently)</span><textarea name="outcome" rows="3" maxlength="3000">${esc(i.data.outcome || "")}</textarea></label>
          <div class="kb-row end"><label><span>Score</span><select name="score">${[0, 1, 2, 3, 4, 5].map(n => `<option ${i.data.score === n ? "selected" : ""}>${n}</option>`).join("")}</select></label><button class="btn primary">${icon("check")}${i.stage === "evaluated" ? "Save" : "Save and mark evaluated"}</button></div></form>`) : ""}
      </div><aside class="kb-side">
        ${linksCard(i)}
        ${card("clock", "Journey", "", hist.length ? `<ol class="kb-journey">${hist.map(h => `<li><b>${esc(h.stage)}</b><span class="kb-faint">${when(h.ts)} · ${esc(h.by)}</span>${h.note ? `<p>${esc(h.note)}</p>` : ""}</li>`).join("")}</ol>` : empty("Proposed."))}
        ${versions(i)}
      </aside></div>`;
  }

  // ---------- Connections ----------
  async function loadGraph() {
    const sp = space;
    gLoading = true;
    try { graph = await api(`${K}/graph?space=${sp}`); graph.space = sp; } catch (e) { graph = { nodes: [], edges: [], space: sp, error: e.message }; } finally { gLoading = false; }
    if (sp === space && tabs[sp] === (sp === "company" ? "graph" : "connections") && !item && !rec) render();
  }
  function graphCard() {
    if (!graph || graph.space !== space) return card("branch", "Graph", "", Loading.line("Drawing the connections…"));
    if (graph.error) return card("branch", "Graph", "", `<div class="empty">${esc(graph.error)}</div>`);
    return card("branch", "Graph", `<span class="kb-faint">${plural(graph.nodes.length, "record")} · ${plural(graph.edges.length, "link")}${graph.nodes.length >= 160 ? " · the 160 most connected" : ""}</span>`,
      graph.nodes.length ? `<div class="kb-graphwrap"><svg class="kb-graph" role="img" aria-label="Knowledge graph: records and their links"></svg></div><p class="kb-note">Click a record to open it. Colors are ${space === "company" ? "scopes" : "top-level folders"}; red lines contradict, dashed lines supersede.</p>`
        : empty("No connections yet. Connect two records from either one's page, or let “Organize with AI” suggest links."));
  }
  function connections() {
    const g = graph?.space === "personal" ? graph : null, byId = {};
    (g?.nodes || []).forEach(n => byId[n.id] = n);
    const R = D.personal.labels.rels;
    return `${graphCard()}
      <div class="kb-grid">${card("link", "Connect two records", "", `<form class="kb-form" data-kb-form="link2"><label><span>From</span><input name="from" list="kb-recs2" required placeholder="Type to find a record"></label>
          <label><span>Relationship</span><select name="rel">${Object.entries(R).map(([x, [l]]) => `<option value="${x}">${l}</option>`).join("")}</select></label>
          <label><span>To</span><input name="to" list="kb-recs2" required placeholder="Type to find a record"></label><label><span>Why (optional)</span><input name="why" maxlength="300"></label>
          <datalist id="kb-recs2">${[...D.personal.items, ...D.personal.ideas].slice(0, 800).map(x => `<option value="${esc(x.title)} · kb:${x.id}"></option>`).join("")}</datalist>
          <div class="kb-row end"><button class="btn primary">${icon("link")}Connect</button></div></form>`)}
        ${card("list", "Relationships", "", g?.edges.length ? `<ul class="kb-rels">${g.edges.slice(0, 120).map(e => `<li><button type="button" class="linkbtn" data-kb-ref="kb:${e.from}">${esc(byId[e.from]?.title || "")}</button><span class="kb-rel kb-rel-${e.rel}">${esc((R[e.rel] || [e.rel])[0].toLowerCase())}</span><button type="button" class="linkbtn" data-kb-ref="kb:${e.to}">${esc(byId[e.to]?.title || "")}</button></li>`).join("")}</ul>` : empty("None yet."))}</div>`;
  }

  // ---------- Company sharing ----------
  function sharing() {
    const d = D.personal, all = [...d.items.filter(k => k.data.kind !== "message"), ...d.ideas], t = (f.text || "").toLowerCase();
    const cand = all.filter(k => !k.published && k.status === "kept" && (!t || k.title.toLowerCase().includes(t)));
    const pub = all.filter(k => k.published);
    const scopes = d.scopes || [];
    return `<p class="kb-lede2">Publishing is separate from keeping: a copy of what you pick goes to the Knowledge Hub's review, with its provenance. It becomes company knowledge, read by your agents within its scope, only when you approve it there.</p>
      <div class="kb-detail"><div class="kb-main">${card("group", "Publish for company review", `<span class="kb-faint">${pubSel.size} picked</span>`, `<form class="kb-form" data-kb-form="publish">
          <div class="kb-row"><label class="kb-grow"><span>Where it applies</span><select name="scope">${scopes.map(s => `<option value="${esc(s.ref)}">${s.kind === "company" ? "The whole company" : `${({ division: "Division", project: "Project", team: "Team", agent: "Agent" })[s.kind]}: ${esc(s.label)}`}</option>`).join("")}</select></label>
            <label><span>Knowledge type</span><select name="ktype"><option value="">Keep each one's</option>${Object.entries(d.labels.ktypes).map(([x, [l]]) => `<option value="${x}">${l}</option>`).join("")}</select></label></div>
          <label><span>A note for the reviewer (optional)</span><input name="note" maxlength="600"></label>
          <input type="search" data-kb-f="text" value="${esc(f.text)}" placeholder="Filter by title" aria-label="Filter by title">
          <ul class="kb-picklist">${cand.slice(0, 300).map(k => `<li><label class="kb-check"><input type="checkbox" data-kb-pub="${k.id}" ${pubSel.has(k.id) ? "checked" : ""}><span><b>${esc(k.title)}</b><small class="kb-faint">${esc(k.path || "")} · ${esc(kt(k.ktype))}${k.trust !== "yours" ? " · untrusted origin" : ""}</small></span></label>${vis(k.visibility)}</li>`).join("") || `<li>${empty("Nothing left to publish.")}</li>`}</ul>
          <div class="kb-row end"><button class="btn primary" ${pubSel.size ? "" : "disabled"}>${icon("group")}Submit ${pubSel.size || ""} for review</button></div></form>`)}</div>
        <aside class="kb-side">${card("check", "Published", "", pub.length ? `<ul class="kb-list">${pub.map(k => `<li><span><button type="button" class="linkbtn" data-kb-ref="kb:${k.published.id}">${esc(k.title)}</button></span>${vis(k.visibility)}</li>`).join("")}</ul>` : empty("Nothing published yet."))}
          ${card("shield", "Rules", "", `<ul class="kb-rules"><li>Private messages and other people's words are published only if you pick them; the review shows where each came from.</li><li>Secrets are taken out again on the way.</li><li>A narrow scope (a project, a team, an agent) reaches only that scope's agents; the whole company reaches every agent of yours.</li></ul>`)}</aside></div>`;
  }

  // ---------- Settings & connectors ----------
  function connList(sl, cs, compact) {
    return `<ul class="kb-conn"><li><b>${icon("hash")}Slack</b>${sl.configured ? `<span class="kb-faint">#${esc(sl.channel)}${sl.team ? ` · ${esc(sl.team)}` : ""} · ${sl.synced ? `synced ${when(sl.synced)}` : "not synced yet"} · the channel an administrator connected, read only</span><button type="button" class="btn sm" data-kb="slack-sync">${icon("cycle")}Sync now</button>`
        : `<span class="kb-faint">No channel connected: an administrator connects one on the Slack page. Channel exports can be imported in Communications.</span>`}</li>
      ${cs.map(c => `<li class="kb-connrow"><b>${icon(c.platform === "telegram" ? "send" : "hash")}${esc(c.name)}</b>
        <span class="kb-faint">${c.platform === "discord" ? `${c.channels.length} channel${c.channels.length === 1 ? "" : "s"}${Object.keys(c.names || {}).length ? `: ${Object.values(c.names).map(x => "#" + esc(x)).join(", ")}` : ""}` : c.channels.length ? `chats ${c.channels.map(esc).join(", ")}` : "every chat the bot sees"}
          · token ${esc(c.masked || "")} · ${c.last_sync ? `synced ${when(c.last_sync)}` : "not synced yet"} · ${c.added} messages${c.auto ? " · syncs every 15 min" : ""}</span>
        ${c.status === "error" ? `<span class="kb-warn kb-note">${esc(c.error || "")}</span>` : ""}
        <span class="kb-row"><button type="button" class="btn sm" data-kb-conn-sync="${c.id}">${icon("cycle")}Sync now</button>${compact ? "" : `<button type="button" class="btn sm" data-kb-conn-edit="${c.id}">${icon("edit")}Edit</button>
          <button type="button" class="btn sm danger" data-kb-conn-rm="${c.id}">${icon("trash")}Remove</button>`}</span>
        ${!compact && connEdit === c.id ? connForm(c) : ""}</li>`).join("")}
      ${compact && !cs.length ? `<li><span class="kb-faint">Discord and Telegram: connect a bot of yours in Settings & connectors, or import an export below.</span></li>` : ""}</ul>`;
  }
  const connForm = c => `<form class="kb-form kb-card kb-inset" data-kb-form="conn" data-id="${c ? c.id : ""}">
      ${c ? "" : `<label><span>Platform</span><select name="platform"><option value="discord">Discord (a bot in your server)</option><option value="telegram">Telegram (a bot of yours)</option></select></label>`}
      <div class="kb-row"><label class="kb-grow"><span>Name (optional)</span><input name="name" maxlength="80" value="${esc(c?.name || "")}"></label>
        <label class="kb-grow"><span>Bot token${c ? " (empty: keep the current one)" : ""}</span><input name="token" type="password" autocomplete="off" ${c ? "" : "required"} minlength="20" maxlength="200"></label></div>
      <label><span>${!c || c.platform === "discord" ? "Discord: channel ids, comma-separated (right-click a channel → Copy Channel ID). " : ""}${!c || c.platform === "telegram" ? "Telegram: chat ids to keep (empty: every chat the bot sees)" : ""}</span>
        <input name="channels" maxlength="1200" value="${esc((c?.channels || []).join(", "))}" placeholder="e.g. 1234567890123456789"></label>
      <label class="kb-check"><input type="checkbox" name="auto" ${c?.auto ? "checked" : ""}> Sync automatically every 15 minutes</label>
      <div class="kb-row end"><button class="btn primary">${icon("check")}${c ? "Save" : "Connect"}</button></div>
      <p class="kb-note">${icon("lock")}Read only. The token is encrypted on the server and never shown again. Discord: the bot needs View Channel, Read Message History and the Message Content intent. Telegram: the bot sees group messages only with privacy mode off (or as an admin); use a bot that does nothing else, since each update is handed out once.</p></form>`;
  function settings() {
    const d = D.personal, sl = d.slack || {}, m = d.media || { search: {} }, se = m.search;
    return `<div class="kb-grid">${card("radio", "Connectors", `<button type="button" class="btn sm" data-kb="conn-new">${icon("plus")}Connect Discord or Telegram</button>`, `${connEdit === "new" ? connForm(null) : ""}${connList(sl, d.connectors || [], false)}`)}
        ${typeof KnowledgeLinked === "object" ? KnowledgeLinked.card() : ""}
        ${card("search", "Search and reading", "", `<ul class="kb-bars"><li><span>Search</span><b>${esc(se.label || "")}</b></li><li><span>Indexed</span><b>${se.indexed || 0} of ${se.total || 0}</b></li>
            <li><span>PDF</span><b>${esc(m.pdf || "")}</b></li><li><span>Office and e-books</span><b>${esc(m.office || "")}</b></li><li><span>Pictures</span><b>${esc(m.pictures || "no model that sees images")}</b></li>
            <li><span>Audio and video</span><b>${esc(m.transcribe || "no transcription endpoint")}</b></li></ul>
          ${se.note ? `<p class="kb-note kb-warn">${esc(se.note)}</p>` : ""}
          <p class="kb-note">${se.meaning ? "Records are found by meaning as well as words." : "Without an embeddings endpoint (an OpenAI or OpenRouter key in Agents → Models, or KNOWLEDGE_EMBED_URL), search matches words and close spellings, not meaning."} The index updates by itself in the background.</p>
          <div class="kb-row"><button type="button" class="btn sm" data-kb="reindex">${icon("cycle")}Rebuild the index</button></div>`)}
        ${card("lock", "Visibility", "", `<ul class="kb-bars">${[["Private (only you)", d.counts.private], ["Shared with your agents", d.counts.items + d.counts.ideas - d.counts.private], ["Published to the company", d.counts.published]].map(([l, v]) => `<li><span>${l}</span><b>${v || 0}</b></li>`).join("")}</ul>
          <p class="kb-note">New captures start private. Change who reads an item on its page, or for many at once in Workspace.</p>`)}
        ${card("download", "Export", "", `<p class="kb-lede2">Download this workspace (agents, skills, memories, notes, projects, ideas and knowledge) as an <code>axor-workspace/1</code> file another AXoR, or this one, can import.</p><button type="button" class="btn" data-kb="export">${icon("download")}Export workspace</button>`)}
        ${card("shield", "Safety", "", `<ul class="kb-rules"><li>Files, pages and messages are kept as text: nothing in them runs. Secrets are taken out on the way in.</li><li>Agents read only what you share, and company knowledge only after review, within its scope.</li><li>Every edit is a version; imports can be undone; every step is in the activity log.</li></ul>`)}</div>
      ${card("list", "Activity", "", d.audit.length ? auditList(d.audit) : empty("Nothing yet."))}`;
  }

  // ---------- opening things ----------
  async function openItem(id) {
    const r = await busy(null, () => api(`${K}/items/${id}`)); if (!r) return;
    if (r.space === "company") {
      rec = r; item = idea = src = null;
      if (space !== "company") { space = "company"; if (tabs.company === null || tabs.company === "overview") tabs.company = "knowledge"; setView(VIEW.company); return; }
      render(); return root()?.scrollIntoView?.({ block: "start" });
    }
    rec = null;
    if (space !== "personal") { space = "personal"; if (r.type === "idea") { idea = r; tabs.personal = "ideas"; } else item = r; setView(VIEW.personal); return; }
    if (r.type === "idea") { idea = r; item = null; tabs.personal = "ideas"; } else { item = r; idea = null; loadPeople(); }
    render(); root()?.scrollIntoView?.({ block: "start" });
  }
  async function openSource(id) {
    const r = await busy(null, () => api(`${K}/imports/${id}`)); if (!r) return;
    src = r; picked = null; tabs.personal = "sources"; sub = "imports"; item = null; render();
  }
  function takeItem(r) { if (!r) return; if (r.space === "company") rec = r; else if (r.type === "idea") idea = r; else item = r; graph = null; refresh().then(render); }
  function takeSource(r) { if (!r) return; src = r; picked = null; refresh().then(render); }

  // ---------- actions ----------
  async function readFile(file, max = 10e6) {
    if (file.size > max) throw new Error(`The file is over ${Math.round(max / 1e6)} MB.`);
    return await file.text();
  }
  function download(name, obj) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }));
    a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const refOf = v => (String(v || "").match(/kb:(\d+)\s*$/) || [])[1];
  const tagsOf = v => String(v || "").split(",").map(x => x.trim().replace(/^#/, "")).filter(Boolean).slice(0, 10);
  async function submit(e) {
    const fm = e.target.closest("form[data-kb-form]"); if (!fm || !root().contains(fm)) return;
    e.preventDefault();
    const F = new FormData(fm), kind = fm.dataset.kbForm, btn = fm.querySelector("button:not([type=button])");
    if (space === "company" && await KnowledgeCo.submit(ctx(), kind, F, fm, btn)) return;
    if (kind === "search") {
      q = (F.get("q") || "").trim(); item = idea = src = rec = null;
      hits = q ? await busy(btn, () => api(`${K}/search?q=${encodeURIComponent(q)}&space=${space === "company" ? "company" : "both"}`)) : null;
      tabs[space] = "overview"; return render();
    }
    if (kind === "ask") {
      const where = F.get("where") || "both";
      const r = await busy(btn, () => api(`${K}/ask`, { method: "POST", body: { question: F.get("question"), where, ...(typeof KnowledgeRag === "object" ? KnowledgeRag.askBody(F) : {}) } }));
      if (r) { asked = { ...r, where }; render(); }
      return;
    }
    if (kind === "capture") {
      const k = fm.dataset.kind, file = fm.elements.file?.files?.[0];
      if (k === "file" && !file) return toast("Choose a file.", { kind: "error" });
      const body = { kind: k, title: F.get("title") || "", text: F.get("text") || "", url: F.get("url") || "", path: F.get("path") || "", tags: tagsOf(F.get("tags")), filename: file?.name || "" };
      const binary = file && !TEXT_EXT.test(file.name);
      const r = await busy(btn, async () => {
        if (binary) {
          if (file.size > 25e6) throw new Error("Files up to 25 MB.");
          const bytes = new Uint8Array(await file.arrayBuffer()); let bin = "";
          for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          return api(`${K}/capture/file`, { method: "POST", body: { filename: file.name, data: btoa(bin), title: body.title, path: body.path, tags: body.tags } });
        }
        if (file) body.text = await readFile(file, 1e6);
        return api(`${K}/capture`, { method: "POST", body });
      });
      if (!r) return;
      cap = null; folder = r.path || folder; await refresh();
      toast(r.data?.kind === "bookmark" ? "Saved as a bookmark: the page couldn't be read" : `Captured in ${r.path}`, { kind: r.data?.kind === "bookmark" ? "info" : "success" });
      return openItem(r.id);
    }
    if (kind === "idea") {
      const r = await busy(btn, () => api(`${K}/ideas`, { method: "POST", body: { kind: F.get("kind"), title: F.get("title"), body: F.get("body") } })); if (!r) return;
      idea = r; tabs.personal = "ideas"; await refresh(); render(); toast("Idea added", { kind: "success" });
      if (F.get("analyze")) analyze($("[data-kb=analyze]"));
      return;
    }
    if (kind === "stage-note") return;
    if (kind === "task") {
      const tasks = [...(idea.data.tasks || []), { title: F.get("title"), detail: "", owner: F.get("owner"), done: false }];
      return takeItem(await busy(btn, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { tasks } })));
    }
    if (kind === "evaluate") {
      const b = { outcome: F.get("outcome"), score: +F.get("score") };
      if (idea.stage !== "evaluated") Object.assign(b, { stage: "evaluated", note: "Evaluated" });
      return takeItem(await busy(btn, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: b })));
    }
    if (kind === "item") {
      const b = { title: F.get("title"), reach: F.get("reach"), path: F.get("path"), ktype: F.get("ktype"), tags: tagsOf(F.get("tags")) };
      if (F.has("body")) b.body = F.get("body");
      const r = await busy(btn, () => api(`${K}/items/${item.id}`, { method: "PATCH", body: b }));
      if (r) { toast("Saved", { kind: "success" }); takeItem(r); }
      return;
    }
    if (kind === "edit-idea") return takeItem(await busy(btn, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { title: F.get("title"), body: F.get("body") } })));
    if (kind === "derive") {
      const k = item || idea;
      const r = await busy(btn, () => api(`${K}/items/${k.id}/derive`, { method: "POST", body: { title: F.get("title"), body: F.get("body"), ktype: F.get("ktype") } }));
      if (r) { toast(`Record made in ${r.path}`, { kind: "success" }); await refresh(); return openItem(r.id); }
      return;
    }
    if (kind === "organize") {
      const k = item || idea, pr = k.data.processing, links = F.getAll("link").map(i => pr.links[+i]).filter(Boolean);
      const b = { path: F.get("folder") ? pr.folder : null, tags: F.get("tags") ? [...new Set([...(k.tags || []), ...pr.tags])] : null, ktype: F.get("ktype") ? pr.ktype : null,
                  links: links.map(l => ({ ref: l.ref, rel: l.rel, why: l.why })), record: F.get("record") ? pr.record : null };
      const r = await busy(btn, () => api(`${K}/items/${k.id}/organize`, { method: "POST", body: b }));
      if (r) { toast("Organized", { kind: "success" }); folder = r.path || folder; takeItem(r); }
      return;
    }
    if (kind === "link" || kind === "link2") {
      const from = kind === "link" ? (item || idea || rec).id : +refOf(F.get("from")), to = refOf(F.get("to"));
      if (!from || !to) return toast("Pick records from the list.", { kind: "error" });
      const r = await busy(btn, () => api(`${K}/links`, { method: "POST", body: { item_id: from, ref: `kb:${to}`, rel: F.get("rel"), why: F.get("why") || "" } }));
      if (!r) return;
      toast("Connected", { kind: "success" }); graph = null;
      if (kind === "link") return takeItem(r);
      await refresh(); return render();
    }
    if (kind === "publish") {
      const ids = [...pubSel];
      const r = await busy(btn, () => api(`${K}/publish`, { method: "POST", body: { ids, scope: F.get("scope"), ktype: F.get("ktype") || "", note: F.get("note") || "" } }));
      if (r) { pubSel.clear(); D.company = null; toast(`${plural(r.n, "record")} waiting for review in the Knowledge Hub`, { kind: "success" }); await refresh(); render(); }
      return;
    }
    if (kind === "folder") {
      const name = String(F.get("name") || "").trim().replace(/^\/+|\/+$/g, ""); if (!name) return;
      const to = fm.dataset.mode === "new" ? `${folder}/${name}` : "/" + name;
      if (fm.dataset.mode === "move" && to === folder) { fedit = null; return render(); }
      const r = await busy(btn, () => fm.dataset.mode === "new" ? api(`${K}/folders`, { method: "POST", body: { path: to } }) : api(`${K}/folders/move`, { method: "POST", body: { path: folder, to } }));
      if (r) { fedit = null; folder = to; await refresh(); render(); }
      return;
    }
    if (kind === "share" || kind === "share-many") {
      const usernames = String(F.get("who") || "").split(",").map(x => x.trim()).filter(Boolean);
      const id = kind === "share" ? item.id : [...sel][0], ids = kind === "share" ? [] : [...sel].slice(1);
      const r = await busy(btn, () => api(`${K}/items/${id}/share`, { method: "POST", body: { usernames, ids } }));
      if (!r) return;
      toast(`Shared with ${usernames.join(", ")}`, { kind: "success" });
      if (kind === "share") return takeItem(r.item);
      sel.clear(); sharing_ = false; await refresh(); return render();
    }
    if (kind === "copy-shared") {
      const r = await busy(btn, () => api(`${K}/shared/${shared.id}/copy`, { method: "POST", body: { path: F.get("path") || "" } }));
      if (r) { toast(`Copied to ${r.path}`, { kind: "success" }); shared = null; await refresh(); return openItem(r.id); }
      return;
    }
    if (kind === "conn") {
      const chans = String(F.get("channels") || "").split(/[\s,]+/).filter(Boolean), id = fm.dataset.id;
      const b = { name: F.get("name") || "", channels: chans, auto: !!F.get("auto") };
      if (F.get("token")) b.token = F.get("token");
      const r = await busy(btn, () => id ? api(`${K}/connectors/${id}`, { method: "PATCH", body: b }) : api(`${K}/connectors`, { method: "POST", body: { ...b, platform: F.get("platform") } }));
      if (r) { toast(id ? "Saved" : `Connected ${r.name}: sync it to read the messages`, { kind: "success" }); connEdit = null; await refresh(); render(); }
      return;
    }
    if (kind === "comms-search") { cf.q = (F.get("q") || "").trim(); comms = null; return loadComms(); }
    if (kind === "comms-import") {
      const file = fm.elements.file.files[0]; if (!file) return;
      const r = await busy(btn, async () => api(`${K}/comms/import`, { method: "POST", body: { platform: F.get("platform"), channel: F.get("channel") || "", filename: file.name, text: await readFile(file, 20e6) } }));
      if (r) { toast(`${plural(r.added, "message")} imported from ${PLAT[r.platform]}${r.skipped ? `, ${r.skipped} already kept` : ""}`, { kind: "success" }); comms = null; await refresh(); loadComms(); }
      return;
    }
    if (kind === "comms-note") {
      const r = await busy(btn, () => api(`${K}/comms/note`, { method: "POST", body: { ids: [...csel], title: F.get("title"), path: F.get("path") || "" } }));
      if (r) { csel.clear(); toast("Saved as a note, linked to its messages", { kind: "success" }); await refresh(); return openItem(r.id); }
      return;
    }
    if (kind === "upload") {
      const file = fm.elements.file.files[0], pasted = (F.get("text") || "").trim();
      if (!file && !pasted) return toast("Choose a file or paste some text.", { kind: "error" });
      const r = await busy(btn, async () => api(`${K}/imports`, { method: "POST", body: { kind: fm.dataset.kind, name: F.get("name") || "", platform: F.get("platform") || "",
        origin: F.get("origin") || "", filename: file ? file.name : "", text: file ? await readFile(file) : pasted } }));
      if (r) { src = r; picked = null; await refresh(); render(); toast(`Read ${plural(r.candidates.length, "record")}: pick what to keep`, { kind: "success" }); }
      return;
    }
    if (kind === "approve") {
      const pid = +fm.dataset.pid, change = {};
      for (const el of fm.querySelectorAll("input[name], textarea[name]")) change[el.name] = el.value;
      const ok = await UI.confirm({ title: "Apply this change?", body: "It changes your agents exactly as shown. You can roll it back afterwards.", ok: "Approve and apply", icon: "check", danger: false });
      if (!ok) return;
      const r = await busy(btn, () => api(`${K}/proposals/${pid}/approve`, { method: "POST", body: { hash: fm.dataset.hash, change } }));
      if (r) { toast(r.result || "Applied", { kind: "success" }); await afterProposal(); }
    }
  }
  async function afterProposal() {
    await refresh();
    if (src) src = await api(`${K}/imports/${src.id}`).catch(() => src);
    if (item) item = await api(`${K}/items/${item.id}`).catch(() => item);
    render();
  }
  async function analyze(btn) {
    const r = await busy(btn, () => api(`${K}/items/${idea.id}/analyze`, { method: "POST", body: {} }));
    if (r) { toast("Analyzed", { kind: "success" }); takeItem(r); }
  }
  async function bulk(b, patch, msg) {
    const ids = [...sel];
    const r = await busy(b, async () => { for (const id of ids) await api(`${K}/items/${id}`, { method: "PATCH", body: patch }); return true; });
    if (r) { sel.clear(); toast(msg(ids.length), { kind: "success" }); await refresh(); render(); }
  }
  async function click(e) {
    const t = e.target;
    const b = t.closest("[data-kb-shared],[data-kb-unshare],[data-kb-conn-sync],[data-kb-conn-edit],[data-kb-conn-rm],[data-kb],[data-kb-tab],[data-kb-item],[data-kb-ref],[data-kb-src],[data-kb-idea],[data-kb-go],[data-kb-stage],[data-kb-move],[data-kb-task],[data-kb-task-rm],[data-kb-task-add],[data-kb-pick],[data-kb-cand],[data-kb-restore],[data-kb-decline],[data-kb-rollback],[data-kb-prop-go],[data-kb-edit-idea],[data-kb-space],[data-kb-cap],[data-kb-folder],[data-kb-sel],[data-kb-sub],[data-kb-process],[data-kb-unlink],[data-kb-chan],[data-kb-csel],[data-kb-comms-undo],[data-kb-pub],[data-kb-node],[data-kb-co]");
    if (!b || !root().contains(b)) return;
    const ds = b.dataset;
    if (ds.kbSpace) { if (ds.kbSpace !== space) setView(VIEW[ds.kbSpace]); return; }
    if (ds.kbTab) { tabs[space] = ds.kbTab; item = src = idea = rec = null; picked = null; store_(space + ".tab", ds.kbTab); return render(); }
    if (space === "company" && await KnowledgeCo.click(ctx(), ds, b, e)) return;
    if (ds.kbItem) return openItem(+ds.kbItem);
    if (ds.kbNode) return openItem(+ds.kbNode);
    if (ds.kbRef) { const m = ds.kbRef.match(/^kb:(\d+)$/); return m && openItem(+m[1]); }
    if (ds.kbIdea) return openItem(+ds.kbIdea);
    if (ds.kbSrc) return openSource(+ds.kbSrc);
    if (ds.kbGo) { const g = gos[+ds.kbGo]; return g && Command.follow(g); }
    if (ds.kbCap) { cap = ds.kbCap; render(); return root().querySelector(".kb-capture input:not([type=file]), .kb-capture textarea")?.focus(); }
    if (ds.kbFolder !== undefined) { folder = ds.kbFolder; find = ""; item = null; shared = null; tabs.personal = "workspace"; return render(); }
    if (ds.kbSel) { b.checked ? sel.add(+ds.kbSel) : sel.delete(+ds.kbSel); return render(); }
    if (ds.kbPub) { b.checked ? pubSel.add(+ds.kbPub) : pubSel.delete(+ds.kbPub); return render(); }
    if (ds.kbCsel) { b.checked ? csel.add(+ds.kbCsel) : csel.delete(+ds.kbCsel); return render(); }
    if (ds.kbSub) { sub = ds.kbSub; src = null; return render(); }
    if (ds.kbChan !== undefined) { const [p, c] = ds.kbChan.split("|"); cf.platform = p || ""; cf.channel = c || ""; comms = null; csel.clear(); return loadComms(); }
    if (ds.kbCommsUndo) {
      const ok = await UI.confirm({ title: "Undo this import?", body: "Its messages are removed (ones you changed since stay).", ok: "Undo", icon: "undo" });
      if (ok && await busy(b, () => api(`${K}/imports/${ds.kbCommsUndo}/undo`, { method: "POST" }))) { comms = null; await refresh(); loadComms(); }
      return;
    }
    if (ds.kbProcess) {
      const r = await busy(b, () => api(`${K}/items/${ds.kbProcess}/process`, { method: "POST", body: {} }));
      if (r) { toast("Suggestions ready: tick what to apply", { kind: "success" }); item = r.type === "idea" ? null : r; if (r.type === "idea") { idea = r; tabs.personal = "ideas"; } render(); }
      return;
    }
    if (ds.kbShared) { const r = await busy(b, () => api(`${K}/shared/${ds.kbShared}`)); if (r) { shared = r; folder = "@shared"; item = null; tabs.personal = "workspace"; render(); } return; }
    if (ds.kbUnshare) return takeItem(await busy(b, () => api(`${K}/items/${item.id}/share/${ds.kbUnshare}`, { method: "DELETE" })));
    if (ds.kbConnSync) {
      const r = await busy(b, () => api(`${K}/connectors/${ds.kbConnSync}/sync`, { method: "POST" }));
      if (r) toast(r.added ? `${plural(r.added, "message")} synced` : "No new messages", { kind: "success" });
      comms = null; await refresh(); return render();
    }
    if (ds.kbConnEdit) { connEdit = connEdit === +ds.kbConnEdit ? null : +ds.kbConnEdit; return render(); }
    if (ds.kbConnRm) {
      const ok = await UI.confirm({ title: "Remove this connector?", body: "Its token is deleted. The messages it brought stay in My Knowledge.", ok: "Remove" });
      if (ok && await busy(b, () => api(`${K}/connectors/${ds.kbConnRm}`, { method: "DELETE" }))) { await refresh(); render(); }
      return;
    }
    if (ds.kbUnlink) return takeItem(await busy(b, () => api(`${K}/links/${ds.kbUnlink}`, { method: "DELETE" })));
    if (ds.kbPropGo) { tabs.personal = "sources"; sub = "adopt"; picked = +ds.kbPropGo; render(); return $(`#kb-prop-${ds.kbPropGo}`)?.scrollIntoView({ block: "center" }); }
    if (ds.kbStage) { stageF = ds.kbStage; return render(); }
    if (ds.kbCand !== undefined) { if (!(picked instanceof Set)) return; b.checked ? picked.add(ds.kbCand) : picked.delete(ds.kbCand); return applyCount(); }
    if (ds.kbPick) {
      const all = src.candidates;
      picked = new Set(ds.kbPick === "all" ? all.filter(c => !c.dup || c.dup.kind === "similar").map(c => c.key) : ds.kbPick === "none" ? [] : [...picked, ...all.filter(c => c.type === ds.kbPick && (!c.dup || c.dup.kind === "similar")).map(c => c.key)]);
      return render();
    }
    if (ds.kbMove) {
      const note = root().querySelector("[data-kb-form=stage-note] input")?.value || "";
      if (ds.kbMove === "evaluated" && !idea.data.outcome) { const r = await busy(b, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { stage: "done", note } })); if (r) { takeItem(r); toast("Write what happened, then save the evaluation."); } return; }
      return takeItem(await busy(b, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { stage: ds.kbMove, note } })));
    }
    if (ds.kbTask !== undefined) {
      const tasks = (idea.data.tasks || []).map((x, n) => n === +ds.kbTask ? { ...x, done: b.checked } : x);
      return takeItem(await busy(null, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { tasks } })));
    }
    if (ds.kbTaskRm !== undefined) return takeItem(await busy(b, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { tasks: (idea.data.tasks || []).filter((_, n) => n !== +ds.kbTaskRm) } })));
    if (ds.kbTaskAdd !== undefined) return takeItem(await busy(b, () => api(`${K}/items/${idea.id}`, { method: "PATCH", body: { tasks: [...(idea.data.tasks || []), idea.data.suggested_tasks[+ds.kbTaskAdd]] } })));
    if (ds.kbEditIdea !== undefined) {
      const c = b.closest(".kb-card");
      c.querySelector(".kb-text").outerHTML = `<form class="kb-form" data-kb-form="edit-idea"><label><span>Title</span><input name="title" value="${esc(idea.title)}" maxlength="200" required></label>
        <label><span>Details</span><textarea name="body" rows="5" maxlength="20000">${esc(idea.body)}</textarea></label><div class="kb-row end"><button class="btn primary">${icon("check")}Save</button></div></form>`;
      return b.remove();
    }
    if (ds.kbRestore) {
      const k = idea || item || rec;
      const r = await busy(b, () => api(`${K}/items/${k.id}/restore`, { method: "POST", body: { version: +ds.kbRestore } }));
      if (r) { toast(`Restored version ${ds.kbRestore}`, { kind: "success" }); takeItem(r); }
      return;
    }
    if (ds.kbDecline) { if (await busy(b, () => api(`${K}/proposals/${ds.kbDecline}/decline`, { method: "POST", body: { note: "" } }))) await afterProposal(); return; }
    if (ds.kbRollback) {
      const p = [...D.personal.proposals, ...(src?.proposals || []), ...(item?.proposals || [])].find(x => x.id === +ds.kbRollback);
      const ok = await UI.confirm({ title: "Roll this back?", body: p?.change?.kind === "new_agent" ? "The adopted agent is deleted, with its chats." : p?.change?.kind === "new_skill" ? "The adopted skill is deleted." : "The addition is taken out of the agent's instructions (as a new version).", ok: "Roll back", icon: "undo" });
      if (!ok) return;
      const r = await busy(b, () => api(`${K}/proposals/${ds.kbRollback}/rollback`, { method: "POST" }));
      if (r) { toast(r.result || "Rolled back", { kind: "success" }); await afterProposal(); }
      return;
    }
    const a = ds.kb;
    if (a === "reload") return load();
    if (a === "back") { item = src = idea = rec = null; picked = null; await refresh(); return render(); }
    if (a === "cap-close") { cap = null; return render(); }
    if (a === "conn-new") { connEdit = connEdit === "new" ? null : "new"; return render(); }
    if (a === "shared-back") { shared = null; return render(); }
    if (a === "people-sel") { sharing_ = true; render(); loadPeople(); return root().querySelector("[data-kb-form=share-many] input")?.focus(); }
    if (a === "people-cancel") { sharing_ = false; return render(); }
    if (a === "read-again") { const r = await busy(b, () => api(`${K}/items/${item.id}/read`, { method: "POST", body: {} })); if (r) { toast("Read again", { kind: "success" }); takeItem(r); } return; }
    if (a === "reindex") { const r = await busy(b, () => api(`${K}/reindex`, { method: "POST" })); if (r) { toast(`${plural(r.made, "record")} indexed`, { kind: "success" }); D.personal.media = r.status; render(); } return; }
    if (a === "clear-search") { hits = null; q = ""; return render(); }
    if (a === "ask-open") { item = idea = src = rec = null; tabs[space] = "overview"; render(); return root().querySelector(".kb-ask textarea")?.focus(); }
    if (a === "export") { const r = await busy(b, () => api(`${K}/export`)); if (r) { download(`axor-workspace-${new Date().toISOString().slice(0, 10)}.json`, r); toast("Exported", { kind: "success" }); } return; }
    if (a === "analyze") return analyze(b);
    if (a === "derive-open") { const el = $("#kb-derive"); el.hidden = !el.hidden; return el.querySelector("input")?.focus(); }
    if (a === "publish-one") { pubSel = new Set([(item || idea).id]); item = idea = null; tabs.personal = "sharing"; return render(); }
    if (a === "publish-sel") { pubSel = new Set(sel); sel.clear(); tabs.personal = "sharing"; return render(); }
    if (a === "move-sel") { const to = $("#kb-move-to").value; return bulk(b, { path: to }, n => `${plural(n, "item")} moved to ${to}`); }
    if (a === "share-sel") return bulk(b, { reach: "agents" }, n => `${plural(n, "item")} shared with your agents`);
    if (a === "private-sel") return bulk(b, { reach: "page" }, n => `${plural(n, "item")} made private`);
    if (a === "clear-sel") { sel.clear(); return render(); }
    if (a === "comms-clear") { csel.clear(); return render(); }
    if (a === "slack-sync") {
      const r = await busy(b, () => api(`${K}/comms/slack`, { method: "POST" }));
      if (r) { toast(r.added ? `${plural(r.added, "message")} synced from Slack` : "No new messages", { kind: "success" }); comms = null; await refresh(); if (tabs.personal === "comms") loadComms(); else render(); }
      return;
    }
    if (a === "new-folder" || a === "move-folder") { fedit = a === "new-folder" ? "new" : "move"; tabs.personal = "workspace"; item = null; render(); return root().querySelector("[data-kb-form=folder] input")?.focus(); }
    if (a === "folder-cancel") { fedit = null; return render(); }
    if (a === "delete-folder") {
      const ok = await UI.confirm({ title: `Delete ${esc(folder)}?`, body: "Only an empty folder (with empty subfolders) can be deleted.", ok: "Delete" });
      if (!ok) return;
      const r = await busy(b, () => api(`${K}/folders/delete`, { method: "POST", body: { path: folder } }));
      if (r) { D.personal.folders = r.folders; folder = folder.slice(0, folder.lastIndexOf("/")) || "/00-Inbox"; render(); }
      return;
    }
    if (a === "extract") return takeSource(await busy(b, () => api(`${K}/imports/${src.id}/extract`, { method: "POST", body: {} })));
    if (a === "apply") {
      const resolve = {};
      root().querySelectorAll("[data-kb-resolve]").forEach(s => resolve[s.dataset.kbResolve] = s.value);
      const r = await busy(b, () => api(`${K}/imports/${src.id}/apply`, { method: "POST", body: { keys: [...picked], resolve, reach: $("#kb-reach")?.value || "" } }));
      if (r) { toast(`Applied: ${plural(r.counts.created, "item")} added${r.counts.replaced ? `, ${r.counts.replaced} replaced` : ""}`, { kind: "success", action: "Undo", onAction: () => undoSource(r.id) }); takeSource(r); }
      return;
    }
    if (a === "discard") { if (await busy(b, () => api(`${K}/imports/${src.id}`, { method: "DELETE" }))) { src = null; await refresh(); render(); } return; }
    if (a === "undo") {
      const ok = await UI.confirm({ title: "Undo this import?", body: "What it added is removed (items you changed since stay), what it replaced is restored, and its waiting proposals are declined.", ok: "Undo the import", icon: "undo" });
      if (ok) undoSource(src.id, b);
      return;
    }
    if (a === "compare") return takeSource(await busy(b, () => api(`${K}/imports/${src.id}/compare`, { method: "POST", body: {} })));
    if (a === "propose") { const r = await busy(b, () => api(`${K}/items/${item.id}/propose`, { method: "POST" })); if (r) { tabs.personal = "sources"; sub = "adopt"; item = null; picked = r.id; await refresh(); render(); } return; }
    if (a === "archive") return takeItem(await busy(b, () => api(`${K}/items/${item.id}`, { method: "PATCH", body: { status: item.status === "archived" ? "kept" : "archived" } })));
    if (a === "delete") {
      const ok = await UI.confirm({ title: `Delete “${esc(item.title)}”?`, body: "It leaves My Knowledge and your agents stop reading it. The activity log keeps a record.", ok: "Delete" });
      if (!ok) return;
      if (await busy(b, () => api(`${K}/items/${item.id}`, { method: "DELETE" }))) { item = null; await refresh(); render(); }
    }
  }
  async function undoSource(id, btn) {
    const r = await busy(btn, () => api(`${K}/imports/${id}/undo`, { method: "POST" }));
    if (r) { toast("Import undone", { kind: "success" }); takeSource(r); }
  }
  function applyCount() {
    const n = picked.size, b = root().querySelector("[data-kb=apply]"), s = root().querySelector(".kb-applybar > span");
    if (b) { b.disabled = !n; b.lastChild.textContent = `Apply ${n}`; }
    if (s) s.textContent = `${n} of ${src.candidates.length} picked`;
  }
  function change(e) {
    const t = e.target; if (!root().contains(t)) return;
    if (t.type === "file") { const l = t.closest(".kb-file"); if (l) { l.classList.toggle("has", !!t.files[0]); l.querySelector("span").lastChild.textContent = t.files[0]?.name || "Choose a file"; } return; }
    if (space === "company" && KnowledgeCo.change?.(ctx(), t)) return;
    if (t.dataset.kbF !== undefined && t.type !== "search") { f[t.dataset.kbF] = t.value; return render(); }
  }
  function input(e) {
    const t = e.target; if (!root().contains(t)) return;
    const k = t.dataset.kbFind !== undefined ? "find" : t.dataset.kbF !== undefined ? "f" : t.dataset.kbCf !== undefined ? "cof" : null;
    if (!k) return;
    if (k === "find") find = t.value; else if (k === "f") f[t.dataset.kbF] = t.value; else cof[t.dataset.kbCf] = t.value;
    clearTimeout(input.t); input.t = setTimeout(() => {
      const sel_ = k === "find" ? "[data-kb-find]" : k === "f" ? `[data-kb-f="${t.dataset.kbF}"]` : `[data-kb-cf="${t.dataset.kbCf}"]`, pos = t.selectionStart;
      render(); const el = root().querySelector(sel_); if (el) { el.focus(); el.setSelectionRange(pos, pos); }
    }, 250);
  }
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => { if (on && root()?.contains(e.target)) click(e); });
    document.addEventListener("submit", e => { if (on && root()?.contains(e.target)) submit(e); });
    document.addEventListener("change", e => { if (on && root()?.contains(e.target)) change(e); });
    document.addEventListener("input", e => { if (on && root()?.contains(e.target)) input(e); });
  }
  // the sidebar's My Knowledge entry is shown whenever the Knowledge Hub's is (auth.js decides that)
  function mirror() {
    const a = document.getElementById("nav-knowledge"), b = document.getElementById("nav-myknowledge");
    if (!a || !b) return;
    const sync = () => { if (b.hidden !== a.hidden) b.hidden = a.hidden; };
    sync(); new MutationObserver(sync).observe(a, { attributes: true, attributeFilter: ["hidden"] });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mirror); else mirror();
  const H = { chip, card, empty, when, plural, trust, vis, go, busy, err, versions, linksCard, results, auditList, askCard, graphCard, kt, store_, relLabel, afterRender: () => afterRender(), openSpace: s => setView(VIEW[s]) };
  return { open, stop, show, h: H };
})();
