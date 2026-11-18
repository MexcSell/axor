/* Connectors (admins): every outside service AXoR holds a key for, and OpenRouter's API keys managed from here.
   With an OpenRouter management key connected, the page lists the account's keys with what each has spent (all time,
   today, this week, this month) against its credit limit, and an admin can create a key, rename it, change or clear
   its limit, disable it (paused, can be turned back on) or delete it (revoked for good). The key AXoR's own agents
   use is marked, and disabling or deleting it asks for its name typed out. A new key is shown once and can go
   straight to the agents. Every change needs the admin code (Admin.withSudo). */
const Connectors = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const RESETS = { "": "Never", daily: "Daily", weekly: "Weekly", monthly: "Monthly" };
  const MANAGE = { agents: "Agents settings", slack: "Slack", source: "Source hub", connectors: "Above" };
  let d = null, all = null, wired = false, q = "", show = "all";

  const cost = x => x == null ? "–" : "$" + fmtNum(x, x >= 100 ? 0 : !x || x >= 0.01 ? 2 : 4);
  const date = s => s ? new Date(s).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "";
  const since = s => { if (!s) return "never"; const t = Date.parse(s) / 1000, x = Date.now() / 1000 - t; return x < 86400 ? ago(t) : x < 86400 * 30 ? `${Math.floor(x / 86400)}d ago` : date(s); };
  const sudo = fn => Admin.withSudo(fn);

  async function open() {
    wire();
    const root = $("#conn");
    if (!root.dataset.built) {
      root.dataset.built = "1";
      root.innerHTML = `<div class="dash-top"><div><h1 class="page">Keys</h1><p class="lead">The model providers and outside services your agents use, the keys AXoR holds for them, and your OpenRouter API keys: what each has spent, its credit limit, and whether it's on.</p></div>
          <button type="button" class="btn sm" data-cn="reload">${icon("reset")}Refresh</button></div>
        <h2 class="section-title">${icon("key")}OpenRouter API keys</h2><div id="cn-or">${Loading.tiles(4)}</div>
        <h2 class="section-title">${icon("link")}All keys and connectors</h2><div class="card" id="cn-all">${Loading.line("Reading connectors…")}</div>`;
    }
    await load();
  }
  async function load() {
    const [o, c] = await Promise.allSettled([api("/api/connectors/openrouter"), api("/api/connectors")]);
    d = o.status === "fulfilled" ? o.value : { failed: o.reason.message };
    all = c.status === "fulfilled" ? c.value.connectors : null;
    render();
  }
  function render() {
    if (S.view !== "connectors") return;
    $("#cn-or").innerHTML = openrouter();
    $("#cn-all").innerHTML = overview();
  }

  // ---------- OpenRouter ----------
  function openrouter() {
    if (d.failed) return `<div class="card"><p class="no">${esc(d.failed)}</p></div>`;
    if (!d.connected) return `<div class="card cn-connect">
        <p>Connect an OpenRouter <b>management key</b> to see what each API key has spent and to create, edit, disable and delete keys from here. A management key can't call models; it only manages keys.</p>
        <ol class="fine"><li>On <a href="https://openrouter.ai/settings/management-keys" target="_blank" rel="noopener noreferrer">openrouter.ai/settings/management-keys</a>, choose <b>Create New Key</b>. An expiry date is a good idea.</li>
          <li>Paste it here. AXoR checks it with OpenRouter, then stores it encrypted.</li></ol>
        <p><button type="button" class="btn primary" data-cn="connect">${icon("link")}Connect OpenRouter</button></p></div>`;
    const ks = d.keys || [], on = ks.filter(k => !k.disabled), cr = d.credits;
    const sum = f => ks.reduce((a, k) => a + (k[f] || 0), 0);
    const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value num">${v}</div><div class="sub">${sub}</div></div>`;
    const rows = ks.filter(k => (show === "all" || (show === "on") === !k.disabled) && (!q || `${k.name} ${k.label}`.toLowerCase().includes(q)))
      .sort((a, b) => a.disabled - b.disabled || (b.usage_monthly || 0) - (a.usage_monthly || 0) || (b.usage || 0) - (a.usage || 0));
    return `<div class="cn-mgmt">${icon("lock")}<span>Management key <code>${esc(d.masked)}</code> <span class="faint">${d.source === "env" ? "from OPENROUTER_MANAGEMENT_KEY" : "saved in AXoR, encrypted"}</span></span>
        <span class="cn-sp"></span><button type="button" class="btn sm" data-cn="connect">Replace</button>${d.source === "app" ? `<button type="button" class="btn sm danger-text" data-cn="disconnect">Disconnect</button>` : ""}</div>
      ${d.error ? `<div class="card cn-err">${icon("alert")}<span>${esc(d.error)}</span></div>` : `
      <div class="stats">
        ${cr ? tile("coins", "Credits left", cost(cr.total_credits - cr.total_usage), `of ${cost(cr.total_credits)} bought · ${cost(cr.total_usage)} used`) : tile("coins", "Credits left", "–", "OpenRouter didn't share the balance")}
        ${tile("calendar", "Spent this month", cost(sum("usage_monthly")), `${cost(sum("usage_weekly"))} this week · ${cost(sum("usage_daily"))} today`)}
        ${tile("chart", "Spent, all time", cost(sum("usage")), "by the keys listed here")}
        ${tile("key", "Keys", on.length, `${ks.length - on.length} disabled${d.agent_key && !ks.some(k => k.agents) ? " · agents' key not on this account" : ""}`)}
      </div>
      <div class="cn-bar"><input type="search" id="cn-q" placeholder="Find a key by name or label" value="${esc(q)}" aria-label="Find a key">
        <div class="seg" role="group" aria-label="Show">${[["all", "All"], ["on", "Active"], ["off", "Disabled"]].map(([v, l]) => `<button type="button" data-cn-show="${v}" aria-pressed="${show === v}">${l}</button>`).join("")}</div>
        <span class="cn-sp"></span><button type="button" class="btn primary sm" data-cn="new">${icon("plus")}New key</button></div>
      ${!rows.length ? `<div class="card empty">${ks.length ? "No key matches." : "This account has no API keys yet."}</div>` : `
      <div class="tablewrap flat cn-table"><table class="grid mini-table"><thead><tr><th>Key</th><th class="r">Spent</th><th class="r">Today</th><th class="r">Week</th><th class="r">Month</th><th>Credit limit</th><th>Last used</th><th></th></tr></thead>
        <tbody>${rows.map(row).join("")}</tbody></table></div>`}`}`;
  }
  function row(k) {
    const used = k.limit != null ? k.limit - (k.limit_remaining ?? k.limit) : 0, p = k.limit ? used / k.limit * 100 : 0;
    const lvl = p >= 90 ? "lv-crit" : p >= 75 ? "lv-warn" : "lv-ok";
    const expired = k.expires_at && Date.parse(k.expires_at) < Date.now();
    return `<tr class="${k.disabled ? "cn-off" : ""}" data-h="${esc(k.hash)}">
      <td><b>${esc(k.name)}</b> ${k.agents ? `<span class="badge new" title="AXoR's agents call OpenRouter with this key">${icon("bot")}AXoR agents</span>` : ""}
        ${k.disabled ? `<span class="badge caution">Disabled</span>` : ""}${expired ? `<span class="badge avoid">Expired</span>` : k.expires_at ? `<span class="badge clear" title="Expires ${esc(date(k.expires_at))}">${icon("clock")}${esc(date(k.expires_at))}</span>` : ""}
        <small class="faint cn-label"><code>${esc(k.label)}</code> · created ${esc(date(k.created_at))}</small></td>
      <td class="r num"><b>${cost(k.usage)}</b>${k.byok_usage ? `<small class="faint">+ ${cost(k.byok_usage)} BYOK</small>` : ""}</td>
      <td class="r num">${cost(k.usage_daily)}</td><td class="r num">${cost(k.usage_weekly)}</td><td class="r num">${cost(k.usage_monthly)}</td>
      <td class="cn-limit">${k.limit == null ? `<span class="faint">No limit</span>` : `<span class="num">${cost(used)} / ${cost(k.limit)}</span>
        <span class="sys-bar ${lvl}"><i style="width:${Math.min(100, p).toFixed(1)}%"></i></span>
        <small class="faint">${cost(k.limit_remaining)} left${k.limit_reset ? ` · resets ${esc(k.limit_reset)}` : ""}</small>`}</td>
      <td class="faint">${esc(since(k.last_used_at))}</td>
      <td class="cn-acts"><button type="button" class="btn sm" data-cn-act="edit" title="Edit name and credit limit">${icon("edit")}Edit</button>
        <button type="button" class="btn sm" data-cn-act="toggle" title="${k.disabled ? "Turn this key back on" : "Pause this key; it can be turned back on"}">${icon(k.disabled ? "play" : "ban")}${k.disabled ? "Enable" : "Disable"}</button>
        <button type="button" class="btn sm danger-text" data-cn-act="delete" title="Revoke this key for good" aria-label="Delete ${esc(k.name)}">${icon("trash")}</button></td></tr>`;
  }

  // the name, limit and reset fields, shared by the new-key and edit dialogs
  const limitFields = (k = {}) => `
    <label class="in"><span>Name</span><input name="name" maxlength="256" required value="${esc(k.name || "")}" placeholder="e.g. Research notebook"></label>
    <div class="cn-two"><label class="in"><span>Credit limit (USD)</span><input name="limit" type="number" min="0" step="0.01" value="${k.limit ?? ""}" placeholder="No limit"></label>
      <label class="in"><span>Limit resets</span><select name="reset">${Object.entries(RESETS).map(([v, l]) => `<option value="${v}" ${(k.limit_reset || "") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
    <label class="chk"><input type="checkbox" name="byok" ${k.include_byok_in_limit ? "checked" : ""}> Count spend on your own provider keys (BYOK) toward the limit</label>`;
  function readLimit(f) {
    const v = f.elements.limit.value.trim(), n = v === "" ? null : +v;
    if (n != null && !(n >= 0 && n < 1e6)) throw new Error("The credit limit is a dollar amount from 0 to 999,999.");
    return { name: f.elements.name.value.trim(), limit: n, limit_reset: n == null ? null : f.elements.reset.value || null, include_byok_in_limit: f.elements.byok.checked };
  }

  function connect() {
    Auth.modal(`<h3>${icon("key")}OpenRouter management key</h3>
      <p class="muted">Create one at <a href="https://openrouter.ai/settings/management-keys" target="_blank" rel="noopener noreferrer">openrouter.ai/settings/management-keys</a>. It's checked with OpenRouter before it's saved.</p>
      <label class="in"><span>Management key</span><input name="key" type="password" autocomplete="off" spellcheck="false" placeholder="sk-or-v1-…" required></label>
      ${d?.connected ? `<p class="fine">Replaces the key in use (${esc(d.masked)}).</p>` : ""}`,
      async f => {
        d = await sudo(() => api("/api/connectors/openrouter", { method: "PUT", body: { key: f.elements.key.value.trim() } }));
        $("#modal").close(); toast(`OpenRouter connected: ${d.keys?.length ?? 0} key${d.keys?.length === 1 ? "" : "s"} on the account`, { kind: "success" });
        load();
      }, { submit: "Connect" });
  }
  function disconnect() {
    UI.confirm({ title: "Disconnect OpenRouter key management?", ok: "Disconnect", icon: "ban",
      body: "AXoR forgets the management key. The account's API keys keep working, AXoR's agents included; you just can't see or manage them here until you connect again.",
      run: async () => { d = await sudo(() => api("/api/connectors/openrouter", { method: "DELETE" })); toast("OpenRouter disconnected"); load(); } });
  }

  function create() {
    const f = Auth.modal(`<h3>${icon("plus")}New OpenRouter key</h3>${limitFields()}
      <label class="in"><span>Expires (optional)</span><input name="expires" type="date" min="${new Date(Date.now() + 864e5).toISOString().slice(0, 10)}"></label>
      <label class="chk"><input type="checkbox" name="agents" ${d.agent_key ? "" : "checked"}> Use it for AXoR's agents${d.agent_key ? " (replaces the key they use now)" : ""}</label>`,
      async f => {
        const body = readLimit(f);
        if (!body.name) throw new Error("Give the key a name.");
        if (f.elements.expires.value) body.expires_at = `${f.elements.expires.value}T23:59:59Z`;
        const r = await sudo(() => api("/api/connectors/openrouter/keys", { method: "POST", body }));
        let note = "";
        if (f.elements.agents.checked) {
          try { await sudo(() => api("/api/agents/settings/provider", { method: "POST", body: { provider: "openrouter", key: r.key } })); note = "AXoR's agents now use this key."; }
          catch (e) { note = `The key was created, but the agents couldn't switch to it: ${e.message}`; }
        }
        reveal(r, note); load();
      }, { submit: "Create key" });
    f.elements.name.focus();
  }
  // OpenRouter shows a new key once; so does AXoR
  function reveal(r, note) {
    Auth.modal(`<h3>${icon("check")}Key “${esc(r.data.name)}” created</h3>
      <p class="muted">Copy it now: OpenRouter won't show it again and AXoR doesn't keep it.</p>
      <div class="cn-secret"><code id="cn-secret">${esc(r.key)}</code><button type="button" class="btn sm" id="cn-copy">${icon("copy")}Copy</button></div>
      ${note ? `<p class="fine">${esc(note)}</p>` : ""}`, async () => $("#modal").close(), { submit: "Done", forced: true });
    $("#cn-copy").onclick = async () => { try { await navigator.clipboard.writeText(r.key); toast("Copied", { kind: "success" }); } catch { getSelection().selectAllChildren($("#cn-secret")); toast("Select and copy it"); } };
  }

  function edit(k) {
    Auth.modal(`<h3>${icon("edit")}Edit ${esc(k.name)}</h3>${limitFields(k)}
      <p class="fine">${cost(k.usage)} spent so far${k.limit_reset ? `, ${cost(k.limit != null ? k.limit - (k.limit_remaining ?? k.limit) : 0)} of it in this ${{ daily: "day", weekly: "week", monthly: "month" }[k.limit_reset]}` : ""}. A limit lower than that stops the key until it resets.</p>`,
      async f => {
        const v = readLimit(f), body = {};
        if (!v.name) throw new Error("A key needs a name.");
        for (const x of ["name", "limit", "limit_reset", "include_byok_in_limit"]) if (v[x] !== (k[x] ?? (x === "include_byok_in_limit" ? false : null))) body[x] = v[x];
        if (!Object.keys(body).length) return $("#modal").close();
        put(await sudo(() => api(`/api/connectors/openrouter/keys/${encodeURIComponent(k.hash)}`, { method: "PATCH", body })));
        $("#modal").close(); toast("Key updated", { kind: "success" });
      });
  }
  async function toggle(k) {
    const go = async () => {
      put(await sudo(() => api(`/api/connectors/openrouter/keys/${encodeURIComponent(k.hash)}`, { method: "PATCH", body: { disabled: !k.disabled } })));
      toast(k.disabled ? `${k.name} enabled` : `${k.name} disabled`, { kind: "success" });
    };
    if (k.disabled) { try { await go(); } catch (e) { toast(e.message, { kind: "error" }); } return; }
    UI.confirm({ title: `Disable ${esc(k.name)}?`, ok: "Disable", icon: "ban", typed: k.agents ? k.name : "",
      body: `${k.agents ? "<b>AXoR's agents use this key</b>: their OpenRouter models stop answering until it's enabled again. " : ""}Requests with this key are refused while it's off. Nothing is lost: enable it again any time.`,
      run: go });
  }
  function remove(k) {
    UI.confirm({ title: `Delete ${esc(k.name)} for good?`, ok: "Delete key", typed: k.name,
      body: `${k.agents ? "<b>AXoR's agents use this key</b>: their OpenRouter models stop working until another key is set in Agents → Models. " : ""}The key is revoked and can't be restored; anything using it stops working. To pause it instead, disable it.`,
      items: [`<code>${esc(k.label)}</code> · ${cost(k.usage)} spent`],
      run: async () => {
        await sudo(() => api(`/api/connectors/openrouter/keys/${encodeURIComponent(k.hash)}`, { method: "DELETE" }));
        d.keys = d.keys.filter(x => x.hash !== k.hash); render(); toast(`${k.name} deleted`, { kind: "success" });
      } });
  }
  // swap one edited key into the list
  function put(k) { d.keys = d.keys.map(x => x.hash === k.hash ? k : x); render(); }

  // ---------- every connector ----------
  function overview() {
    if (!all) return `<p class="faint">Couldn't read the connectors.</p>`;
    const groups = [...new Set(all.map(c => c.group))];
    return `<div class="tablewrap flat"><table class="grid mini-table cn-all"><thead><tr><th>Connector</th><th>Status</th><th>Key</th><th>Changed in</th></tr></thead><tbody>
      ${groups.map(g => `<tr class="cn-group"><th colspan="4">${esc(g)}</th></tr>` + all.filter(c => c.group === g).map(c => `<tr>
        <td><b>${esc(c.name)}</b><small class="faint">${esc(c.note)}</small></td>
        <td>${c.configured ? `<span class="badge clear">${icon("check")}${c.source === "app" ? "Set in AXoR" : "From environment"}</span>` : `<span class="badge">Not set</span>`}</td>
        <td>${c.masked ? `<code>${esc(c.masked)}</code>` : c.configured ? `<span class="faint">hidden</span>` : `<small class="faint"><code>${esc(c.env)}</code></small>`}</td>
        <td>${c.manage ? `<button type="button" class="linkbtn" data-cn-go="${esc(c.manage)}">${esc(MANAGE[c.manage] || c.manage)}</button>` : `<span class="faint">Environment</span>`}</td></tr>`).join("")).join("")}
      </tbody></table></div>
      <p class="fine cn-foot">Keys set in AXoR are stored encrypted on the server and only ever shown masked. One saved in AXoR is used over the environment variable.</p>`;
  }

  function wire() {
    if (wired) return; wired = true;
    const root = $("#view-connectors");
    root.addEventListener("click", e => {
      const t = e.target, a = t.closest("[data-cn]")?.dataset.cn;
      if (a === "reload") return load();
      if (a === "connect") return connect();
      if (a === "disconnect") return disconnect();
      if (a === "new") return create();
      const s = t.closest("[data-cn-show]"); if (s) { show = s.dataset.cnShow; return render(); }
      const g = t.closest("[data-cn-go]")?.dataset.cnGo;
      if (g) return g === "connectors" ? $("#cn-or").scrollIntoView({ behavior: "smooth" }) : setView(g);
      const act = t.closest("[data-cn-act]"), k = act && d.keys.find(x => x.hash === act.closest("tr").dataset.h);
      if (!k) return;
      ({ edit, toggle, delete: remove })[act.dataset.cnAct](k);
    });
    root.addEventListener("input", e => {
      if (e.target.id !== "cn-q") return;
      q = e.target.value.trim().toLowerCase();
      const at = e.target.selectionStart; render();
      const i = $("#cn-q"); i.focus(); i.setSelectionRange(at, at);
    });
  }

  return { open };
})();
