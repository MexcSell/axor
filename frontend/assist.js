/* Assist: an agent beside every page. The Assist button in the top bar opens a panel on the right (docked beside the
   page on wide screens, over it on narrow ones) with the agent for the page you're on: for administrators the matching
   built-in agent (DevOps on DevOps and Source, Functions, Apps, Cluster on Cluster, System and Machines, DNS, User admin
   on user administration), and the Assistant everywhere else (assistant.py: it knows AXoR's pages and reads live data).
   The menu in its header switches to another built-in agent or one of your own, kept per page. Every message says which
   page it's sent from, so "this page" means the one you're on. Chats are the Agents tab's (Open in Agents continues one
   there, and the panel reopens your last chat with each agent); proposals are approved right in the panel. */
const Assist = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("assist." + k)); localStorage.setItem("assist." + k, JSON.stringify(v)); } catch { return null; } };
  // the built-in agent for each page; the Assistant everywhere else
  const FOR = { admin: "user-admin", devops: "devops", source: "devops", functions: "functions", apps: "apps", cluster: "cluster",
                system: "cluster", machines: "cluster", dns: "dns" };
  // the Assistant's first suggestions on a page, after "What can I do on this page?"
  const ASK = {
    explore: "Which subnets are open for registration?", recommend: "What fits one RTX 4090 and $300 a month?", new: "Which new subnets look promising?",
    caution: "Why are these subnets flagged?", scam: "What counts as a scam signal?", dashboard: "What's moving in the market today?",
    workspace: "How are my workspace subnets doing?", study: "What should I study next?", wallet: "How do I stake on a subnet?",
    source: "Which repositories have failing CI?", drive: "How do I share a folder?", notifications: "How do I get alerts on my phone?",
  };
  let hub = null, builtins = [], mine = [], agent = null, view = "explore", busy = false, sending = null, busySince = 0, timer = null;
  const convs = {};  // agent key -> its chat in the panel ({ id: null, items: [] } until the first answer)
  const keyOf = a => a.builtin ? a.id : `custom:${a.id}`;
  const base = a => a.builtin ? `/api/agents/${a.id}` : `/api/agents/custom/${a.id}`;
  const all = () => [...builtins, ...mine];
  const conv = () => agent && convs[keyOf(agent)];
  const ckey = () => `assist:${agent ? keyOf(agent) : ""}`;
  const isOpen = () => !!$("#assist") && !$("#assist").hidden;
  const pageTitle = v => $(`nav.side [data-view="${v}"]`)?.title || ({ admin: "User administration" }[v] || v);
  const fallback = v => FOR[v] && builtins.some(a => a.id === FOR[v]) ? FOR[v] : "assistant";

  // signed-in users who can use agents get the button; the panel opens again if it was open
  async function init() {
    if (!Auth.me()) return;
    try { hub = await api("/api/agents/hub"); } catch { return; }
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "btn sm assist-btn"; btn.id = "assist-btn";
    btn.setAttribute("aria-controls", "assist"); btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = `${icon("sparkle")}<span>Assist</span>`;
    btn.onclick = () => toggle();
    $(".top-right").insertBefore(btn, $("#bell"));
    const p = document.createElement("aside");
    p.className = "assist"; p.id = "assist"; p.hidden = true; p.dataset.cxPanel = ""; p.setAttribute("aria-label", "Assist");
    $(".shell").appendChild(p);
    Chat.resizer(p, "--assist-w", "assistW", 340, 720);
    wire(p);
    await load();
    label();
    if (pref("open")) toggle(true);
  }
  async function load() {
    const [b, lists] = await Promise.all([api("/api/agents").catch(() => null), api("/api/agents/custom").catch(() => null)]);
    if (b) builtins = b.map(a => ({ ...a, builtin: true, status: "live" }));
    if (lists) { const seen = new Set(); mine = [...lists.mine, ...lists.shared, ...lists.from_directory].filter(a => a.status === "live" && !seen.has(a.id) && seen.add(a.id)); }
    if (agent) agent = all().find(a => keyOf(a) === keyOf(agent)) || agent;
  }
  // the agent for a page: your pick there, else the page's own
  function pick(v) {
    const want = pref(`pick.${v}`) || fallback(v);
    return all().find(a => keyOf(a) === want) || all().find(a => keyOf(a) === fallback(v)) || builtins[0] || mine[0] || null;
  }
  function label() {
    const b = $("#assist-btn"), a = pick(view); if (!b) return;
    b.title = a ? `Ask ${a.id === "assistant" ? "the Assistant" : a.name} about ${pageTitle(view)}` : "Assist";
  }
  function onView(v) {
    view = v;
    if (!hub) return;
    label();
    if (!isOpen()) return;
    const a = pick(v);
    if (a && a !== agent) select(a); else { drawCtx(); if (!conv()?.items.length) render(); }
  }

  function toggle(on = !isOpen()) {
    const p = $("#assist"), b = $("#assist-btn"); if (!p) return;
    p.hidden = !on; document.body.classList.toggle("assist-on", on); pref("open", on);
    b.setAttribute("aria-expanded", on); b.classList.toggle("on", on);
    dispatchEvent(new Event("resize"));  // docked, it narrows the page: let charts and boards fit again
    if (!on) { Chat.quiet(); return; }
    if (!p.firstChild) draw();
    const a = pick(view);
    if (a && a !== agent) select(a); else { drawHead(); render(); }
    Chat.focus(ckey());
    // agents created or a model connected since: picked up in the background
    Promise.all([load(), api("/api/agents/hub").then(h => { hub = h; }).catch(() => {})]).then(() => { if (isOpen() && !busy) { drawHead(); render(); } });
  }
  async function select(a) {
    agent = a;
    if (!a) { drawHead(); return render(); }
    const k = keyOf(a);
    if (!convs[k]) {
      convs[k] = { id: null, items: [], proposals: [] };
      const cid = pref(`conv.${k}`);  // your last chat with this agent, continued
      if (cid) {
        drawHead(); $("#assist-log").innerHTML = Loading.line("Loading chat…");
        try { const c = await api(`${base(a)}/conversations/${cid}`); if (!convs[k].items.length) convs[k] = c; } catch { pref(`conv.${k}`, null); }
      }
    }
    if (agent === a) { drawHead(); render(); Chat.focus(ckey()); }
  }

  // ---------- drawing ----------
  function draw() {
    const p = $("#assist");
    p.innerHTML = `${Chat.grip()}<div class="chat assist-box">
      <div class="assist-head" id="assist-head"></div>
      <div class="assist-ctx" id="assist-ctx"></div>
      <div class="chat-log cx-log" id="assist-log" aria-live="polite"></div>
      <div class="approvals" id="assist-props"></div>
      <div id="assist-compose"></div></div>`;
    Chat.bind(p, { items: () => conv()?.items || [], onSay: t => send(t) });
  }
  function drawHead() {
    const a = agent, head = $("#assist-head"); if (!head) return;
    head.innerHTML = `${a ? `<button type="button" class="assist-who" data-as="menu" aria-haspopup="true" title="Switch agent">${agentAvatar(a, "sm")}
        <span><b>${esc(a.name)}</b><small>${esc(a.role || "Agent")}</small></span>${icon("chev")}</button>` : `<b class="assist-none">Assist</b>`}
      <span class="ac-spacer"></span>
      ${a ? `<button type="button" class="iconbtn sm" data-as="new" title="New chat" aria-label="New chat" ${conv()?.id ? "" : "disabled"}>${icon("plus")}</button>
      <button type="button" class="iconbtn sm" data-as="full" title="Open in the Agents tab" aria-label="Open in the Agents tab">${icon("expand")}</button>` : ""}
      <button type="button" class="iconbtn sm" data-as="close" title="Close (Esc)" aria-label="Close Assist">${icon("close")}</button>`;
    drawCtx(); drawComposer();
  }
  function drawCtx() {
    const box = $("#assist-ctx"), a = agent; if (!box) return;
    const own = a && keyOf(a) === fallback(view);
    box.innerHTML = `${icon("map")}<span class="assist-where">On <b>${esc(pageTitle(view))}</b>${a && !own ? ` · <button type="button" class="linkbtn" data-as="reset">use this page's agent</button>` : ""}</span>
      ${a?.unavailable ? `<span class="badge new" title="${esc(a.unavailable)}">Not set up</span>` : ""}`;
  }
  function drawComposer() {
    const box = $("#assist-compose"), a = agent; if (!box) return;
    if (!a) { box.innerHTML = ""; return; }
    const items = conv()?.items || [];
    const o = {
      key: ckey(), busy, disabled: !hub.configured, compact: true, plus: false, mic: true,
      placeholder: !hub.configured ? "Connect a model to use agents" : a.placeholder || `Ask ${a.name} about ${pageTitle(view)}…`,
      slash: [["new", "Start a new chat"]], tokens: Chat.tokensOf(items), turns: items.filter(i => i.kind === "assistant" && i.tokens).length,
      onSend: text => send(text), onCommand: cmd => { if (cmd !== "new") return false; newChat(); return true; },
    };
    box.innerHTML = Chat.composer(o);
    Chat.mount(box.querySelector("form"), o);
  }
  const busyLabel = () => { const s = Math.floor((Date.now() - busySince) / 1000); return s < 2 ? "Thinking…" : `${s < 20 ? "Thinking…" : s < 60 ? "Still working: checking the data…" : "Taking longer than usual…"} ${s}s`; };
  function examples(a) {
    if (a.id !== "assistant") return (a.examples || []).slice(0, 3);
    return [...new Set(["What can I do on this page?", ...(ASK[view] ? [ASK[view]] : []), ...(a.examples || [])])].slice(0, 3);
  }
  function greet(a) {
    const who = a.id === "assistant" ? "I'm your AXoR Assistant" : a.builtin ? `I'm the ${esc(a.name)} agent` : `I'm ${esc(a.name)}`;
    return `<div class="msg bot ac-greet">${agentAvatar(a, "sm")}<div class="bubble"><p>Hi ${esc(Auth.me()?.username || "there")}! ${who}. You're on <b>${esc(pageTitle(view))}</b>: ask me about it, or anything else.</p>
        ${a.description ? `<p class="muted">${esc(a.description)}</p>` : ""}</div></div>
      <div class="ac-suggest">${examples(a).map(x => `<button type="button" class="chip ac-chip" data-cx-say="${esc(x)}">${icon("right")}${esc(x)}</button>`).join("")}</div>`;
  }
  function render() {
    const log = $("#assist-log"), props = $("#assist-props"), a = agent; if (!log) return;
    props.innerHTML = "";
    if (!a) { log.innerHTML = `<div class="chat-empty"><p class="muted">No agents are available to you yet.</p></div>`; return; }
    if (!hub.configured) {
      log.innerHTML = `<div class="chat-empty">${agentAvatar({ icon: "key", color: "slate" }, "lg")}<h3>Connect a model to use agents</h3>
        <p class="muted">Agents run on Claude, OpenAI, any model on OpenRouter, a model on your own server, or Terminal. ${hub.is_admin ? "" : "Ask an administrator to connect one."}</p>
        ${hub.is_admin ? `<button type="button" class="btn primary" data-as="settings">${icon("key")}Connect a model</button>` : ""}</div>`;
      return;
    }
    const c = conv();
    log.innerHTML = Chat.log(c.items, { agent: a, busy: busy && sending === keyOf(a), busyLabel: busyLabel(), toolHtml: Agents.toolHtml, empty: greet(a) });
    Chat.enhance(log);
    props.innerHTML = Agents.proposalsHtml(c.proposals);
  }

  // ---------- chatting ----------
  async function send(text) {
    const a = agent;
    if (busy || !a || !text.trim()) return false;
    const k = keyOf(a), c = convs[k];
    busy = true; sending = k; busySince = Date.now();
    timer = setInterval(() => { const l = $("#assist-log .typing-label"); if (l) l.textContent = busyLabel(); }, 1000);
    c.items = [...c.items, { kind: "user", text }];
    drawHead(); render();
    let ok = true;
    try {
      const r = await api(`${base(a)}/chat`, { method: "POST", body: { conversation_id: c.id, message: text, page: view, ...Chat.choice() } });
      convs[k] = r; pref(`conv.${k}`, r.id);
      if (r.error) r.items.push({ kind: "note", text: r.error });
    } catch (e) { c.items.push({ kind: "note", text: e.message }); ok = false; }
    busy = false; sending = null; clearInterval(timer);
    if (isOpen()) { drawHead(); render(); if (agent === a) Chat.focus(ckey()); }
    return ok;
  }
  // a question asked from a page (the Command Center's assistant card): sent in the panel, so it lands in the agent's own chat
  async function ask(text) {
    if (!hub) return false;
    if (!isOpen()) toggle(true);
    const a = pick(view);
    if (a && a !== agent) await select(a);
    return send(text);
  }
  function newChat() {
    const k = keyOf(agent);
    convs[k] = { id: null, items: [], proposals: [] }; pref(`conv.${k}`, null);
    drawHead(); render(); Chat.focus(ckey());
  }
  async function decide(pid, approve) {
    const a = agent, k = keyOf(a), c = convs[k];
    try {
      const r = await Admin.withSudo(() => api(`/api/agents/proposals/${pid}`, { method: "POST", body: { approve } }));
      Auth.toast(r.status === "failed" ? r.message : approve ? "Approved and applied" : "Rejected");
      if (r.temp_password) Admin.showTemp({ username: c.proposals.find(p => p.id === pid)?.payload.username || "" }, r.temp_password);
    } catch (e) { if (e.message !== "cancelled") Auth.toast(e.message); }
    try { convs[k] = await api(`${base(a)}/conversations/${c.id}`); } catch {}
    if (agent === a) render();
  }
  // continue this chat in the Agents tab, with its history and the agent's other chats
  function full() {
    const a = agent, c = conv();
    toggle(false);
    Agents.openAgent(a.builtin ? a.id : String(a.id), c?.id || null);
    setView("agents");
  }
  async function menu(btn) {
    await load();
    document.querySelector(".assist-menu")?.remove();
    const own = fallback(view);
    const row = a => `<button type="button" class="mi ${a === agent ? "on" : ""}" data-as-pick="${esc(keyOf(a))}">${agentAvatar(a, "xs")}
      <span><b>${esc(a.name)}</b><small class="faint">${esc(a.role || "Agent")}</small></span>${keyOf(a) === own ? `<span class="tag">This page</span>` : ""}</button>`;
    const pop = document.createElement("div"); pop.className = "popover menu assist-menu";
    pop.innerHTML = `<h4>Built in</h4>${builtins.map(row).join("")}${mine.length ? `<h4>Your agents</h4>${mine.map(row).join("")}` : ""}`;
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px"; pop.style.left = Math.max(16, Math.min(b.left, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); pop.remove(); btn.focus(); } });
    pop.onclick = e => {
      const k = e.target.closest("[data-as-pick]")?.dataset.asPick; if (!k) return;
      pop.remove();
      const a = all().find(x => keyOf(x) === k); if (!a) return;
      pref(`pick.${view}`, k === own ? null : k); label(); select(a);
    };
    pop.querySelector(".mi.on, .mi")?.focus();
  }
  function wire(p) {
    p.addEventListener("click", e => {
      const as = e.target.closest("[data-as]");
      if (as) {
        const k = as.dataset.as;
        if (k === "menu") { e.stopPropagation(); return document.querySelector(".assist-menu") ? document.querySelector(".assist-menu").remove() : menu(as); }
        if (k === "new") return newChat();
        if (k === "full") return full();
        if (k === "close") return toggle(false);
        if (k === "settings") return Agents.openSettings();
        if (k === "reset") { pref(`pick.${view}`, null); label(); return select(pick(view)); }
      }
      const d = e.target.closest("[data-decide]"); if (d) return decide(+d.dataset.decide, d.dataset.approve === "1");
    });
    p.addEventListener("keydown", e => {
      if (e.key !== "Escape" || e.defaultPrevented || document.querySelector(".popover, dialog[open]")) return;  // a composer popup closes first
      toggle(false); $("#assist-btn").focus();
    });
  }

  return { init, onView, toggle, ask, ready: () => !!hub };
})();
