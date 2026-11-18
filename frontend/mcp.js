/* Tools & MCP (mcp_hub.py; mcp.css, prefix tmc-).
   - page(el): the Agents page's "Tools & MCP": the MCP servers AXoR knows, their tools and which are allowed. Administrators add
     a server (remote over HTTP, or a command inside AXoR's container), test the connection, tick the tools agents may call and
     say who may use it; header and environment values are secrets, written once and never shown again. Everyone else sees the
     servers and tools they may give their agents.
   - Grant pickers: any element with data-tmc-scope="hub:<agent id>" or "team:<workspace id>" becomes a picker of the servers
     and tools that agent or Competition team gets (mounted by a MutationObserver, so pages that redraw keep unsaved ticks). */
const ToolsMcp = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const sudo = fn => Admin.withSudo(fn);
  let d = null, host = null, editing = null, allowEdits = {}, busy = new Set(), wired = false, catOpen = null, catBusy = null;
  const openTools = new Set();  // servers whose tool list is unfolded
  const picks = {};  // scope → { data, sel: {server id: Set(tool) | null}, dirty, err }

  const ago_ = ts => ts ? ago(ts) : "never";
  const stat = s => !s.enabled ? ["off", "Off"] : s.status === "ok" ? ["ok", "Connected"] : s.status === "error" ? ["err", "Can't connect"] : ["new", "Not tested"];
  const pill = (cls, text, ic) => `<span class="tmc-pill ${cls}">${ic ? icon(ic) : ""}${esc(text)}</span>`;
  const where = s => s.transport === "http" ? (s.url ? (() => { try { return new URL(s.url).host; } catch { return s.url; } })() : "Remote") : (s.command ? s.command.split("/").pop() : "Local");

  // ---------- the page ----------
  async function page(el) {
    host = el; wire();
    el.innerHTML = `<div class="tmc-loading">${icon("server")} Loading tools…</div>`;
    try { d = await api("/api/mcp"); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    draw();
  }
  async function reload() {
    try { d = await api("/api/mcp"); } catch (e) { toast(e.message); }
    Object.keys(picks).forEach(k => delete picks[k]);  // servers changed: pickers fetch again
    draw();
  }
  function draw() {
    if (!host || !d) return;
    host.innerHTML = `<div class="tmc">
      <div class="hub-top"><div><h1 class="page">Tools &amp; MCP</h1>
        <p class="lead">MCP servers give agents more tools: GitHub, a database, a search engine, your own services. ${d.admin ? "Add a server, test it and tick the tools agents may call;" : "An administrator adds servers and picks their tools;"} then give them to an agent in its profile (Tools tab) or to a Competition team on its Agents tab.</p></div>
        ${d.admin && !editing ? `<button type="button" class="btn primary" data-tmc="add">${icon("plus")}Add MCP server</button>` : ""}</div>
      ${editing ? form(editing) : ""}
      ${d.admin && d.catalog ? catalog() : ""}
      ${d.servers.length ? `<h2 class="tmc-h2">${icon("server")}Servers <span class="faint">${d.servers.length}</span></h2><div class="tmc-list">${d.servers.map(card).join("")}</div>`
        : `<div class="empty tmc-none">${icon("server")}<p><b>No MCP servers yet.</b> ${d.admin ? "Add one from the catalog above, or by its URL (remote) or the command that starts it (local)." : "An administrator can add them here."}</p></div>`}
      ${d.me ? `<section class="card tmc-missions"><h2 class="tmc-h2">${icon("target")}Mission tools</h2>
        <p class="muted small">What your missions may use. Mission Control runs a mission on Workforce, Long tasks or a Competition team, and all three get these tools for your work (also when you start them outside a mission). A mission small enough for a single answer runs without tools.</p>
        <div data-tmc-scope="missions:${d.me}"></div></section>` : ""}
      ${d.admin && d.calls?.length ? calls() : ""}
      <section class="card tmc-builtin"><h3>${icon("shield")}Built in to AXoR</h3>
        <p class="muted small">Every agent also has AXoR's own tools, which read data and never change anything: subnets and the market, mining plans, your workspace, GitHub through Source, DevOps (administrators), the Knowledge hub, and Remember. Competition teams add their board, files and sandbox.</p></section>
    </div>`;
  }
  function card(s) {
    const [tone, label] = stat(s), edits = allowEdits[s.id], allowedNow = edits || new Set(s.tools.filter(t => t.allowed).map(t => t.name));
    const changed = edits && (edits.size !== s.tools.filter(t => t.allowed).length || s.tools.some(t => t.allowed !== edits.has(t.name)));
    return `<section class="card tmc-srv" data-sid="${s.id}">
      <header><span class="tmc-ico">${icon(s.transport === "http" ? "globe" : "terminal")}</span>
        <div class="tmc-t"><h3>${esc(s.name)}</h3><p class="faint small">${s.transport === "http" ? "Remote" : "Local"} · ${esc(where(s))}${s.server?.name ? ` · ${esc(s.server.name)}${s.server.version ? " " + esc(s.server.version) : ""}` : ""} · checked ${esc(ago_(s.checked))}</p></div>
        <div class="tmc-pills">${pill("t-" + tone, label)}${pill("", s.audience === "everyone" ? "Everyone" : "Admins' agents", s.audience === "everyone" ? "users" : "lock")}${d.admin && s.grants ? pill("", `${s.grants} agent${s.grants === 1 ? "" : "s"} / teams`, "bot") : ""}</div>
        ${d.admin ? `<div class="tmc-acts"><button type="button" class="btn sm" data-tmc="test" ${busy.has(s.id) ? "disabled" : ""}>${icon(busy.has(s.id) ? "cycle" : "radio")}${busy.has(s.id) ? "Testing…" : "Test connection"}</button>
          <button type="button" class="btn sm" data-tmc="edit">${icon("edit")}Edit</button><button type="button" class="iconbtn" data-tmc="del" title="Remove" aria-label="Remove ${esc(s.name)}">${icon("trash")}</button></div>` : ""}</header>
      ${s.error ? `<p class="tmc-err">${icon("alert")}${esc(s.error)}</p>` : ""}
      ${s.tools.length ? `<details class="tmc-tools" data-tmc-open="${s.id}" ${openTools.has(s.id) || changed ? "open" : ""}>
        <summary class="tmc-th">${d.admin ? `${allowedNow.size} of ${s.tools.length} tools allowed` : `${s.tools.length} tools agents may use`}${d.admin ? `<span class="faint"> · read-only tools start allowed; tick the others only if agents should use them</span>` : ""}</summary>
        <ul>${s.tools.map(t => `<li>${d.admin ? `<label class="tmc-chk"><input type="checkbox" data-tmc-allow="${esc(t.name)}" ${allowedNow.has(t.name) ? "checked" : ""}>` : `<span class="tmc-chk">`}
            <span><b>${esc(t.title || t.name)}</b>${t.title ? ` <code>${esc(t.name)}</code>` : ""} ${t.read_only ? pill("t-ok", "read-only") : pill("t-warn", "not marked read-only")}
            <small class="faint">${esc(t.description || "No description.")}</small></span>${d.admin ? "</label>" : "</span>"}</li>`).join("")}</ul>
        ${d.admin ? `<div class="row end"><button type="button" class="btn sm" data-tmc="allow-reset" ${changed ? "" : "disabled"}>Undo</button><button type="button" class="btn sm primary" data-tmc="allow-save" ${changed ? "" : "disabled"}>${icon("check")}Save allowed tools</button></div>` : ""}
      </details>` : s.status === "ok" ? `<p class="faint small">The server offers no tools.</p>` : ""}
    </section>`;
  }
  // the catalog (mcp_hub.CATALOG): GitHub, DeepWiki, Context7, Exa, Research papers, Database; one click, plus a key where one is needed
  function catalog() {
    const free = d.catalog.filter(c => c.keyless && !c.added.length);
    return `<section class="tmc-cat"><div class="tmc-cat-head"><h2 class="tmc-h2">${icon("apps")}Catalog</h2>
        ${free.length ? `<button type="button" class="btn sm" data-tmc="add-free" ${catBusy ? "disabled" : ""}>${icon(catBusy === "free" ? "cycle" : "plus")}${catBusy === "free" ? "Adding…" : `Add the free ones (${free.map(c => esc(c.name)).join(", ")})`}</button>` : ""}</div>
      <div class="tmc-cards">${d.catalog.map(c => `<article class="tmc-cc ${c.added.length ? "added" : ""}" data-tmc-cat="${c.key}">
        <header><b>${esc(c.name)}</b><span class="tmc-tags">${c.for.map(f => `<span class="tmc-tag">${esc(f)}</span>`).join("")}</span></header>
        <p class="small muted">${esc(c.about)}</p>
        ${catOpen === c.key ? catForm(c) : `<div class="tmc-cc-foot">${c.added.length ? `${pill("t-ok", "Added", "check")}<button type="button" class="linkbtn" data-tmc="cat-again">Add another</button>`
          : `<button type="button" class="btn sm ${c.keyless ? "" : "primary"}" data-tmc="cat-add" ${catBusy ? "disabled" : ""}>${icon(catBusy === c.key ? "cycle" : "plus")}${catBusy === c.key ? "Adding…" : c.fields.some(f => !f.optional) ? "Set up" : "Add"}</button>`}
          <span class="faint small">${c.keyless ? "No key needed" : "Needs a key"}${c.transport === "stdio" ? " · built in" : ""}</span></div>`}
      </article>`).join("")}</div></section>`;
  }
  function catForm(c) {
    return `<form class="tmc-cf" data-cf="${c.key}" autocomplete="off">
      ${c.fields.map(f => `<label class="in"><span>${esc(f.label)}${f.optional ? ` <small class="faint">(optional)</small>` : ""}</span>
        <input name="${esc(f.key)}" type="${f.key === "DATABASE_URL" ? "text" : "password"}" spellcheck="false" autocomplete="new-password" placeholder="${esc(f.placeholder || "")}">
        ${f.help ? `<small class="faint">${esc(f.help)}</small>` : ""}</label>
        ${f.source_token ? `<label class="tmc-chk"><input type="checkbox" name="use_source" ${d.source_token ? "" : "disabled"}><span>Use the GitHub token Source already has${d.source_token ? "" : " <small class=\"faint\">(Source has none yet)</small>"}</span></label>` : ""}`).join("")}
      <label class="in"><span>Who may give it to their agents</span><select name="audience"><option value="admins">Administrators only</option><option value="everyone">Everyone who uses agents</option></select></label>
      <p class="err" role="alert"></p>
      <div class="row end"><button type="button" class="btn sm" data-tmc="cat-cancel">Cancel</button><button type="submit" class="btn sm primary">${icon("check")}Add and test</button></div>
    </form>`;
  }
  async function install(key, values = {}, audience = "admins") {
    const r = await sudo(() => api(`/api/mcp/catalog/${key}`, { method: "POST", body: { values, audience } }));
    toast(r.status === "ok" ? `${r.name}: connected, ${r.tools.length} tools` : `${r.name} added, but it can't connect: ${r.error}`, { kind: r.status === "ok" ? "" : "error" });
    return r;
  }
  function calls() {
    return `<section class="card tmc-calls"><h3>${icon("clock")}Recent calls</h3><div class="tablewrap"><table class="grid"><thead><tr><th>When</th><th>Server · tool</th><th>For</th><th>Who</th><th class="r">Time</th><th>Result</th></tr></thead><tbody>
      ${d.calls.map(c => `<tr><td>${esc(ago(c.ts))}</td><td>${esc(c.server || "removed")} · <code>${esc(c.tool)}</code></td><td><small>${esc(c.scope)}</small></td><td>${esc(c.who || "")}</td>
        <td class="r num">${c.ms} ms</td><td>${c.ok ? pill("t-ok", "ok") : `${pill("t-err", "failed")} <small class="faint">${esc(c.error || "")}</small>`}</td></tr>`).join("")}</tbody></table></div></section>`;
  }
  function pairs(name, list, isNew) {
    const rows = (list.length ? list : [""]).map(k => `<div class="tmc-pair"><input name="${name}-k" placeholder="${name === "hdr" ? "Header, e.g. Authorization" : "VARIABLE_NAME"}" value="${esc(k)}" autocomplete="off" spellcheck="false">
      <input name="${name}-v" type="password" placeholder="${k && !isNew ? "Unchanged (type to replace)" : name === "hdr" ? "Value, e.g. Bearer …" : "Value"}" autocomplete="new-password">
      <button type="button" class="iconbtn sm" data-tmc="pair-del" aria-label="Remove">${icon("close")}</button></div>`).join("");
    return `<div class="tmc-pairs" data-pairs="${name}">${rows}</div><button type="button" class="linkbtn" data-tmc="pair-add" data-for="${name}">${icon("plus")}Add another</button>`;
  }
  function form(e) {
    const s = e.server || {}, t = e.transport || s.transport || "http", isNew = !s.id;
    return `<form class="card tmc-form" id="tmc-form" autocomplete="off">
      <h3>${icon(isNew ? "plus" : "edit")}${isNew ? "Add an MCP server" : `Edit ${esc(s.name)}`}</h3>
      <label class="in"><span>Name</span><input name="name" maxlength="60" required value="${esc(s.name || "")}" placeholder="e.g. GitHub, Postgres, Search"></label>
      <div class="seg tmc-seg" role="radiogroup" aria-label="Where it runs"><button type="button" role="radio" data-tmc-t="http" aria-checked="${t === "http"}">${icon("globe")}Remote (HTTP)</button><button type="button" role="radio" data-tmc-t="stdio" aria-checked="${t === "stdio"}">${icon("terminal")}Local (command)</button></div>
      ${t === "http" ? `<label class="in"><span>Server URL</span><input name="url" type="url" required value="${esc(s.url || "")}" placeholder="https://example.com/mcp"></label>
        <div class="in"><span>Headers <small class="faint">(values are secrets: stored encrypted, never shown again)</small></span>${pairs("hdr", s.headers || [], isNew)}</div>`
      : `<p class="tmc-note">${icon("info")}A local server runs inside AXoR's container, so its command must exist there. AXoR's image has Python but not Node or uv: <code>npx</code> and <code>uvx</code> servers need the image changed. Remote servers work as they are.</p>
        <label class="in"><span>Command</span><input name="command" required value="${esc(s.command || "")}" placeholder="python" spellcheck="false"></label>
        <label class="in"><span>Arguments <small class="faint">(one per line)</small></span><textarea name="args" rows="3" spellcheck="false" placeholder="-m&#10;my_mcp_server">${esc((s.args || []).join("\n"))}</textarea></label>
        <div class="in"><span>Environment <small class="faint">(values are secrets: stored encrypted, never shown again)</small></span>${pairs("env", s.env || [], isNew)}</div>`}
      <label class="in"><span>Who may give it to their agents</span><select name="audience"><option value="admins" ${s.audience !== "everyone" ? "selected" : ""}>Administrators only</option><option value="everyone" ${s.audience === "everyone" ? "selected" : ""}>Everyone who uses agents (they use these credentials)</option></select></label>
      ${isNew ? "" : `<label class="toggle-row"><span><b>On</b><small class="faint">Off: no agent can call it; grants are kept</small></span><span class="switch"><input type="checkbox" name="enabled" ${s.enabled ? "checked" : ""}><span></span></span></label>`}
      <p class="err" role="alert"></p>
      <div class="row end"><button type="button" class="btn" data-tmc="cancel">Cancel</button><button type="submit" class="btn primary">${icon("check")}${isNew ? "Add and test" : "Save"}</button></div>
    </form>`;
  }
  function body(f) {
    const t = $(".tmc-seg [aria-checked=true]", f).dataset.tmcT;
    const read = n => $$(`.tmc-pairs[data-pairs=${n}] .tmc-pair`, f).map(p => ({ key: p.querySelector(`[name=${n}-k]`).value.trim(), value: p.querySelector(`[name=${n}-v]`).value })).filter(x => x.key);
    return { name: f.elements.name.value.trim(), transport: t, url: f.elements.url?.value.trim() || null, command: f.elements.command?.value.trim() || null,
             args: (f.elements.args?.value || "").split("\n").map(x => x.trim()).filter(Boolean), headers: t === "http" ? read("hdr") : [], env: t === "stdio" ? read("env") : [],
             audience: f.elements.audience.value, enabled: f.elements.enabled ? f.elements.enabled.checked : true };
  }
  const server = el => d.servers.find(s => s.id === +el.closest("[data-sid]")?.dataset.sid);

  // ---------- grant pickers ----------
  function mountAll() { $$("[data-tmc-scope]").forEach(el => { if (el.dataset.tmcOn !== el.dataset.tmcScope) mount(el); }); }
  async function mount(el) {
    const scope = el.dataset.tmcScope; el.dataset.tmcOn = scope; wire();
    const p = picks[scope];
    if (p?.data) return drawPick(el, scope);
    el.innerHTML = `<p class="faint small">${icon("server")} Loading MCP tools…</p>`;
    try { load(scope, await api("/api/mcp/grants?scope=" + encodeURIComponent(scope))); }
    catch (e) { picks[scope] = { err: e.message }; }
    $$(`[data-tmc-scope="${scope}"]`).forEach(x => drawPick(x, scope));
  }
  function load(scope, data) {
    picks[scope] = { data, dirty: false, sel: Object.fromEntries(data.servers.filter(s => s.granted).map(s => [s.id, s.picked ? new Set(s.picked) : null])) };
  }
  function drawPick(el, scope) {
    const p = picks[scope];
    if (!p || p.err) { el.innerHTML = `<p class="faint small">${esc(p?.err || "")}</p>`; return; }
    const team = scope.startsWith("team:"), list = p.data.servers.filter(s => s.usable || s.granted);
    const n = Object.keys(p.sel).length;
    el.innerHTML = `<section class="tmc-pick">
      <header><h4>${icon("server")}MCP tools${team ? " for the whole team" : ""}</h4><span class="faint small">${n ? `${n} server${n === 1 ? "" : "s"} given` : "None given"}</span></header>
      ${list.length ? `<ul>${list.map(s => { const on = s.id in p.sel, pick = p.sel[s.id];
          return `<li class="${on ? "on" : ""}"><label class="tmc-chk"><input type="checkbox" data-tmc-g="${s.id}" ${on ? "checked" : ""} ${s.usable ? "" : "disabled"}>
            <span><b>${esc(s.name)}</b> ${s.status !== "ok" ? pill("t-err", s.status === "error" ? "can't connect" : "not tested") : ""}${s.usable ? "" : pill("t-warn", "not available to you")}
            <small class="faint">${s.tools.length} allowed tool${s.tools.length === 1 ? "" : "s"}</small></span></label>
            ${on && s.tools.length ? `<div class="tmc-tl">${s.tools.map(t => `<label class="tmc-tool"><input type="checkbox" data-tmc-gt="${s.id}" value="${esc(t.name)}" ${!pick || pick.has(t.name) ? "checked" : ""}><code>${esc(t.name)}</code></label>`).join("")}
              <small class="faint">${!pick ? "All allowed tools, and ones allowed later." : `${pick.size} of ${s.tools.length}.`}</small></div>` : ""}</li>`; }).join("")}</ul>
        <div class="row end"><button type="button" class="btn sm" data-tmc-gundo ${p.dirty ? "" : "disabled"}>Undo</button><button type="button" class="btn sm primary" data-tmc-gsave ${p.dirty ? "" : "disabled"}>${icon("check")}Save tools</button></div>
        <p class="faint small">${team ? "Every agent of the team can call these while it works. " : scope.startsWith("missions:") ? "Your missions' engines can call these while they work. " : "The agent can call these in its chats. "}Calls use the server's credentials; each is logged under Agents → Tools &amp; MCP.</p>`
      : `<p class="faint small">No MCP servers ${p.data.servers.length ? "are available to you" : "yet"}. ${Auth.me()?.role === "admin" ? `Add one under <button type="button" class="linkbtn" data-tmc-go>Agents → Tools &amp; MCP</button>.` : "An administrator adds them under Agents → Tools &amp; MCP."}</p>`}
    </section>`;
  }
  async function savePick(scope) {
    const p = picks[scope];
    const usable = new Set(p.data.servers.filter(s => s.usable).map(s => s.id));  // one you may not use any more is dropped, not re-sent
    const grants = Object.entries(p.sel).filter(([sid]) => usable.has(+sid)).map(([sid, pick]) => ({ server_id: +sid, tools: pick ? [...pick] : null }));
    try { load(scope, await api("/api/mcp/grants", { method: "PUT", body: { scope, grants } })); toast("Tools saved. The next run uses them."); }
    catch (e) { toast(e.message, { kind: "error" }); }
    $$(`[data-tmc-scope="${scope}"]`).forEach(x => drawPick(x, scope));
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", async e => {
      const t = e.target;
      const pk = t.closest("[data-tmc-scope]");
      if (pk) {
        const scope = pk.dataset.tmcScope, p = picks[scope];
        if (t.closest("[data-tmc-go]")) return Agents.tools();
        if (t.closest("[data-tmc-gsave]")) return savePick(scope);
        if (t.closest("[data-tmc-gundo]")) { load(scope, p.data); return drawPick(pk, scope); }
        return;
      }
      if (!host || !t.closest(".tmc")) return;
      const b = t.closest("[data-tmc]"); if (!b) return;
      const k = b.dataset.tmc, s = server(b);
      if (k === "add") { editing = { server: null, transport: "http" }; draw(); return $("#tmc-form [name=name]")?.focus(); }
      if (k === "cat-add" || k === "cat-again") {
        const c = d.catalog.find(x => x.key === b.closest("[data-tmc-cat]").dataset.tmcCat);
        if (c.fields.length) { catOpen = c.key; draw(); return $(`[data-cf=${c.key}] input`)?.focus(); }
        catBusy = c.key; draw();
        try { await install(c.key); } catch (x) { if (x.message !== "cancelled") toast(x.message, { kind: "error" }); }
        catBusy = null; return reload();
      }
      if (k === "cat-cancel") { catOpen = null; return draw(); }
      if (k === "add-free") {
        const free = d.catalog.filter(c => c.keyless && !c.added.length);
        catBusy = "free"; draw();
        try { for (const c of free) await install(c.key); } catch (x) { if (x.message !== "cancelled") toast(x.message, { kind: "error" }); }
        catBusy = null; return reload();
      }
      if (k === "cancel") { editing = null; return draw(); }
      if (k === "edit") { editing = { server: s }; draw(); return $("#tmc-form")?.scrollIntoView({ block: "nearest" }); }
      if (k === "pair-add") { const box = $(`.tmc-pairs[data-pairs=${b.dataset.for}]`, host); box.insertAdjacentHTML("beforeend", $(".tmc-pair", box).outerHTML.replace(/value="[^"]*"/g, 'value=""').replace(/Unchanged \(type to replace\)/, "Value")); return; }
      if (k === "pair-del") { const row = b.closest(".tmc-pair"), box = row.parentElement; if (box.children.length > 1) row.remove(); else $$("input", row).forEach(i => i.value = ""); return; }
      if (k === "test") {
        busy.add(s.id); draw();
        try { const r = await api(`/api/mcp/${s.id}/test`, { method: "POST" }); toast(r.status === "ok" ? `${r.name}: connected, ${r.tools.length} tools` : `${r.name}: ${r.error}`, { kind: r.status === "ok" ? "" : "error" }); }
        catch (x) { toast(x.message, { kind: "error" }); }
        busy.delete(s.id); delete allowEdits[s.id]; return reload();
      }
      if (k === "del") {
        return UI.confirm({ title: `Remove ${s.name}?`, body: `Agents and teams it was given to lose its tools (${s.grants || 0}). Its stored secrets are deleted.`, ok: "Remove",
          run: async () => { await sudo(() => api(`/api/mcp/${s.id}`, { method: "DELETE" })); toast(`${s.name} removed`); reload(); } }).catch(x => x && x.message !== "cancelled" && toast(x.message));
      }
      if (k === "allow-reset") { delete allowEdits[s.id]; return draw(); }
      if (k === "allow-save") {
        try { await sudo(() => api(`/api/mcp/${s.id}/allowed`, { method: "PUT", body: { allowed: [...allowEdits[s.id]] } })); delete allowEdits[s.id]; toast("Allowed tools saved"); reload(); }
        catch (x) { if (x.message !== "cancelled") toast(x.message, { kind: "error" }); }
      }
    });
    document.addEventListener("click", e => {  // where a server runs: switch the form, keeping what was typed
      const sw = e.target.closest(".tmc-seg [data-tmc-t]"); if (!sw || !editing) return;
      const f = $("#tmc-form"), cur = body(f);
      editing = { server: { ...(editing.server || {}), ...cur, id: editing.server?.id, headers: cur.headers.map(h => h.key), env: cur.env.map(x => x.key) }, transport: sw.dataset.tmcT };
      draw();
    });
    document.addEventListener("toggle", e => {  // remember which tool lists are open across redraws (toggle doesn't bubble: capture)
      const dt = e.target.closest?.("[data-tmc-open]"); if (!dt) return;
      dt.open ? openTools.add(+dt.dataset.tmcOpen) : openTools.delete(+dt.dataset.tmcOpen);
    }, true);
    document.addEventListener("change", e => {
      const t = e.target;
      const al = t.closest("[data-tmc-allow]");
      if (al) { const s = server(al), set = allowEdits[s.id] || new Set(s.tools.filter(x => x.allowed).map(x => x.name)); al.checked ? set.add(al.dataset.tmcAllow) : set.delete(al.dataset.tmcAllow); allowEdits[s.id] = set; return draw(); }
      const pk = t.closest("[data-tmc-scope]"); if (!pk) return;
      const scope = pk.dataset.tmcScope, p = picks[scope];
      if (t.dataset.tmcG) { const id = +t.dataset.tmcG; if (t.checked) p.sel[id] = null; else delete p.sel[id]; p.dirty = true; return drawPick(pk, scope); }
      if (t.dataset.tmcGt) {
        const id = +t.dataset.tmcGt, all = p.data.servers.find(s => s.id === id).tools.map(x => x.name);
        const set = p.sel[id] ? new Set(p.sel[id]) : new Set(all);
        t.checked ? set.add(t.value) : set.delete(t.value);
        if (!set.size) delete p.sel[id]; else p.sel[id] = set.size === all.length ? null : set;
        p.dirty = true; return drawPick(pk, scope);
      }
    });
    document.addEventListener("submit", async e => {  // a catalog entry's key form
      const cf = e.target.closest?.("[data-cf]"); if (!cf) return;
      e.preventDefault();
      const key = cf.dataset.cf, err = $(".err", cf), btn = $("[type=submit]", cf), values = {};
      $$("input:not([type=checkbox])", cf).forEach(i => { if (i.value.trim()) values[i.name] = i.value.trim(); });
      if (cf.elements.use_source?.checked) values.use_source = true;
      err.textContent = ""; btn.disabled = true; btn.classList.add("loading");
      try { await install(key, values, cf.elements.audience.value); catOpen = null; await reload(); }
      catch (x) { if (x.message !== "cancelled") { err.textContent = x.message; btn.disabled = false; btn.classList.remove("loading"); } }
    });
    document.addEventListener("submit", async e => {
      if (e.target.id !== "tmc-form") return;
      e.preventDefault();
      const f = e.target, b = body(f), err = $(".err", f), btn = $("[type=submit]", f), id = editing?.server?.id;
      err.textContent = ""; btn.disabled = true; btn.classList.add("loading");
      try {
        const r = await sudo(() => api(id ? `/api/mcp/${id}` : "/api/mcp", { method: id ? "PUT" : "POST", body: b }));
        editing = null;
        toast(r.status === "ok" ? `${r.name}: connected, ${r.tools.length} tools` : r.status === "error" ? `${r.name} saved, but it can't connect: ${r.error}` : `${r.name} saved`, { kind: r.status === "error" ? "error" : "" });
        await reload();
      } catch (x) { if (x.message !== "cancelled") { err.textContent = x.message; btn.disabled = false; btn.classList.remove("loading"); } }
    });
    let frame = 0;  // one look per frame, however many nodes a redraw adds
    new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(mountAll); }).observe(document.body, { childList: true, subtree: true });
    mountAll();
  }

  // the pickers mount themselves wherever one appears, from the start
  if (document.body) wire(); else document.addEventListener("DOMContentLoaded", wire);
  return { page, forget: scope => { delete picks[scope]; } };
})();
