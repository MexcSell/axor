/* Apps (PaaS) and Functions (FaaS) views (admins only): what runs on AXoR's Kubernetes platform. One module serves both
   pages: a list on the left; the selected app or function on the right with Overview (status, pods, events), Code
   (functions), Test / Invoke (a request sent from inside the cluster), Logs, Revisions (roll back) and, for functions,
   Stats. New and Edit open a form; changes ask for sudo first and the server enforces every rule. Polls faster while
   something is deploying. */
const Paas = (() => {
  const KIND = {
    apps: { view: "apps", root: "#apps", title: "Apps", one: "app", icon: "apps", api: "/api/platform/apps",
      lead: "Run any container image on AXoR's Kubernetes cluster with HTTPS, a name under the platform domain, custom domains, secrets, autoscaling and one-click rollback." },
    functions: { view: "functions", root: "#fns", title: "Functions", one: "function", icon: "zap", api: "/api/platform/functions",
      lead: "Write a Python or Node.js function here and it answers HTTPS requests at its own address. Packages, secrets, timeouts, replicas and rollback included." },
  };
  const ST = { running: ["Running", "ok"], deploying: ["Deploying", "run"], starting: ["Starting", "run"], degraded: ["Degraded", "bad"],
    failing: ["Failing", "bad"], failed: ["Failed", "bad"], stopped: ["Stopped", "off"] };
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const withSudo = fn => Admin.withSudo(fn);
  const bytes = n => n == null ? "–" : n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : n < 1073741824 ? `${fmtNum(n / 1048576, 0)} MB` : `${fmtNum(n / 1073741824, 2)} GB`;
  const since = ts => !ts ? "–" : Date.now() / 1000 - ts < 86400 ? ago(ts) : new Date(ts * 1000).toLocaleDateString();
  const dot = st => `<span class="ci ci-${(ST[st] || [, "off"])[1]}" role="img" aria-label="${esc((ST[st] || [st])[0])}"></span>`;
  const pill = st => `<span class="ci-pill ci-${(ST[st] || [, "off"])[1]}">${esc((ST[st] || [st])[0])}</span>`;
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  let tpl = null;  // function templates and runtimes, loaded once

  function page(kind) {
    const K = KIND[kind], root = () => $(K.root);
    let d = null, sel = null, cur = null, tab = "overview", wired = false, timer = null, logTail = 300, lastReq = null, stats = null, statsLoading = false;
    const busy = x => x && ["deploying", "starting"].includes(x.status);

    async function open() {
      wire();
      if (!d) root().innerHTML = `<h1 class="page">${K.title}</h1>${Loading.line(`Loading ${K.title.toLowerCase()}…`)}`;
      await load();
      schedule();
    }
    async function load() {
      try { d = await api(K.api); }
      catch (e) { d = null; root().innerHTML = `<h1 class="page">${K.title}</h1><p class="lead">${esc(K.lead)}</p><div class="empty">${esc(e.message)}</div>`; return; }
      if (!d.items.some(x => x.name === sel)) sel = store.get(`paas.${kind}.sel`, null);
      if (!d.items.some(x => x.name === sel)) sel = d.items[0]?.name ?? null;
      cur = sel ? await api(`${K.api}/${sel}`).catch(() => cur) : null;
      render();
    }
    function schedule() {
      clearTimeout(timer);
      const hot = d?.items.some(busy) || busy(cur);
      timer = setTimeout(async () => { if ($(`#view-${K.view}`).hidden) return; await load(); schedule(); }, hot ? 3000 : 15000);
    }
    async function select(name) {
      sel = name; store.set(`paas.${kind}.sel`, name); cur = null; stats = null; lastReq = null; render();
      cur = await api(`${K.api}/${name}`).catch(e => (err(e), null)); render();
    }

    // ---------- page ----------
    function render() {
      if (!d) return;
      if (!$(".pk-main", root())) root().innerHTML = `<h1 class="page">${K.title}</h1><p class="lead">${esc(K.lead)}</p>
        <div class="stats" data-part="stats"></div>
        <div class="src dv pk">
          <aside class="card src-repos"><div class="src-side-head"><b>${K.title}</b><span class="spacer"></span>
            <button type="button" class="btn sm primary" data-pf="new">${icon("plus")}New</button></div>
            <div class="src-list" data-part="list"></div></aside>
          <div class="card src-main pk-main" data-part="main"></div>
        </div>`;
      const run = d.items.filter(x => x.status === "running").length;
      const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
      put($("[data-part=stats]", root()), [
        tile(K.icon, K.title, `${run}/${d.items.length}`, `${d.items.length - run} not running`),
        tile("chip", "CPU in use", `${fmtNum(d.items.reduce((a, x) => a + x.cpu, 0), 2)}`, `cores, of ${fmtNum(d.items.reduce((a, x) => a + (x.status === "stopped" ? 0 : (x.cpu_limit || 0) * x.replicas), 0), 2)} allowed`),
        tile("chips", "Memory in use", bytes(d.items.reduce((a, x) => a + x.memory, 0)), "across every pod"),
        tile("globe", "Addresses", `<span class="pk-suffix">*${esc(d.suffix)}</span>`, "HTTPS through the edge"),
      ].join(""));
      put($("[data-part=list]", root()), d.items.map(x => `<button type="button" class="src-item" data-sel="${esc(x.name)}" aria-current="${x.name === sel}">
          ${dot(x.status)}<span class="src-item-main"><b>${esc(x.name)}</b><small class="faint">${esc(kind === "apps" ? x.image : (tpl?.runtimes[x.runtime]?.title || x.runtime || ""))} · ${x.ready}/${x.replicas}</small></span></button>`).join("")
        || `<div class="empty pk-first">No ${K.title.toLowerCase()} yet.<br><button type="button" class="btn sm primary" data-pf="new">${icon("plus")}New ${K.one}</button></div>`);
      renderMain();
    }

    function renderMain() {
      const el = $("[data-part=main]", root()); if (!el) return;
      if (!sel) return put(el, `<div class="empty">${kind === "apps" ? "An app is a container image: say which, the port it listens on, and AXoR runs it with HTTPS." : "A function is a handler you write here; AXoR runs it and gives it an HTTPS address."}</div>`);
      if (!cur) return put(el, Loading.line("Loading…"));
      const x = cur, s = x.settings, on = x.status !== "stopped";
      const TABS = [["overview", "Overview", "info"], ...(kind === "functions" ? [["code", "Code", "code"]] : []), ["test", kind === "apps" ? "Test" : "Invoke", "send"],
        ["logs", "Logs", "terminal"], ["revisions", "Revisions", "commit"], ...(kind === "functions" ? [["stats", "Stats", "chart"]] : [])];
      if (!TABS.some(t => t[0] === tab)) tab = "overview";
      const head = `<div class="pk-head"><div class="pk-title"><h2>${esc(x.name)}</h2>${pill(x.status)}
          ${x.url ? `<a class="pk-url" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${icon("lock")}${esc(x.url.replace(/^https:\/\//, "").replace(/\/$/, ""))}</a>` : `<span class="faint">${icon("lock")}Not public</span>`}</div>
        <div class="pk-acts">
          <button type="button" class="btn sm" data-pf="restart" ${on ? "" : "disabled"}>${icon("reset")}Restart</button>
          <button type="button" class="btn sm" data-pf="${on ? "stop" : "start"}">${icon(on ? "stop" : "play")}${on ? "Stop" : "Start"}</button>
          <button type="button" class="btn sm" data-pf="edit">${icon("edit")}Edit</button>
          <button type="button" class="iconbtn danger" data-pf="delete" title="Delete" aria-label="Delete ${esc(x.name)}">${icon("trash")}</button></div></div>
        ${x.message ? `<div class="sl-err">${icon("alert")}<span>${esc(x.message)}</span></div>` : ""}
        <div class="src-tabs" role="tablist">${TABS.map(([k, l, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}</button>`).join("")}</div>`;
      const body = { overview, code, test, logs: logsTab, revisions, stats: statsTab }[tab]();
      // (what's shown is kept in data-showing, not data-sel: clicks look for data-sel to pick an item)
      if (el.dataset.showing !== x.name || el.dataset.showtab !== tab || !["test", "code", "logs"].includes(tab) || !$(".pk-head", el)) {
        put(el, head + `<div class="src-body pk-body">${body}</div>`);
      } else {  // keep what's typed in Test / Code, and the log's scroll position, through polls
        el.querySelectorAll(":scope > .sl-err, :scope > .src-tabs").forEach(n => n.remove());
        const h = $(".pk-head", el), tmp = document.createElement("div");
        tmp.innerHTML = head; h.replaceWith(...tmp.children); el.dataset.html = "";
      }
      el.dataset.showing = x.name; el.dataset.showtab = tab;
      if (tab === "logs" && !$(".src-log", el).dataset.loaded) loadLogs();
      if (tab === "stats" && !stats && !statsLoading) loadStats();
    }

    function overview() {
      const x = cur, s = x.settings;
      const cpu = x.pods.reduce((a, p) => a + (p.cpu || 0), 0), mem = x.pods.reduce((a, p) => a + (p.memory || 0), 0);
      const fact = (l, v) => `<div><span>${l}</span><b>${v}</b></div>`;
      const facts = [
        kind === "apps" ? fact("Image", `<code>${esc(s.image)}</code>`) : fact("Runtime", esc(tpl?.runtimes[s.runtime]?.title || s.runtime) + ` <small class="faint">${esc(s.handler)}()</small>`),
        fact("Replicas", `${x.ready}/${x.replicas}${s.autoscale_max > s.replicas ? ` <small class="faint">autoscaled ${s.replicas}–${s.autoscale_max}</small>` : ""}`),
        fact("CPU", `${fmtNum(cpu, 3)} <small class="faint">of ${s.cpu} per pod</small>`),
        fact("Memory", `${bytes(mem)} <small class="faint">of ${s.memory} MB per pod</small>`),
        kind === "apps" ? fact("Port", `${s.port}${s.health ? ` <small class="faint">health ${esc(s.health)}</small>` : ""}`) : fact("Timeout", `${s.timeout}s`),
        ...(kind === "apps" && s.volume ? [fact("Volume", `<code>${esc(s.volume)}</code> <small class="faint">${s.volume_gb} GB</small>`)] : []),
        fact("Environment", `${x.env.length} <small class="faint">${x.env.filter(e => e.secret).length} secret</small>`),
        ...(x.domains.length ? [fact("Custom domains", x.domains.map(h => `<code>${esc(h)}</code>`).join(" "))] : []),
      ];
      return `<div class="kv pk-facts">${facts.join("")}</div>
        <h3 class="pk-h">${icon("server")}Pods</h3>
        ${x.pods.length ? `<div class="tablewrap flat"><table class="grid pk-pods"><thead><tr><th>Pod</th><th>State</th><th class="r">Restarts</th><th class="r">CPU</th><th class="r">Memory</th><th>Started</th></tr></thead><tbody>
          ${x.pods.map(p => `<tr><td><code>${esc(p.name)}</code></td><td>${esc(p.deleting ? "Stopping" : p.phase)} ${p.ready ? `<span class="badge clear">ready</span>` : ""}${p.problem ? `<small class="pk-problem">${esc(p.problem)}</small>` : ""}</td>
            <td class="r num">${p.restarts}</td><td class="r num">${p.cpu == null ? "–" : fmtNum(p.cpu, 3)}</td><td class="r num">${bytes(p.memory)}</td><td class="num">${since(p.created)}</td></tr>`).join("")}
          </tbody></table></div>` : `<div class="empty">No pods: it's stopped.</div>`}
        <h3 class="pk-h">${icon("bell")}Events</h3>
        ${x.events.length ? `<ul class="pk-events">${x.events.slice(0, 12).map(e => `<li class="${e.type === "Warning" ? "warn" : ""}"><span class="num faint">${since(e.time)}</span><b>${esc(e.reason)}</b><span>${esc(e.message)}</span></li>`).join("")}</ul>`
          : `<p class="faint">Nothing recent.</p>`}`;
    }

    function code() {
      return `<div class="pk-code"><textarea class="pk-editor" name="code" spellcheck="false" aria-label="Code">${esc(cur.code)}</textarea>
        <label class="in"><span>Packages <small class="faint">(${cur.settings.runtime.startsWith("python") ? "requirements, one per line, e.g. requests==2.32.3" : "one per line, e.g. lodash@4.17.21"}; installed when it starts)</small></span>
          <textarea name="packages" rows="3" spellcheck="false">${esc(cur.packages)}</textarea></label>
        <div class="row"><button type="button" class="btn primary" data-pf="deploy-code">${icon("rocket")}Deploy</button>
          <span class="faint">Deploying makes a new revision; the old one keeps answering until the new one is ready.</span></div></div>`;
    }

    function test() {
      const r = lastReq;
      return `<form class="pk-test" data-part="req"><div class="pk-reqline">
          <select name="method" aria-label="Method">${["GET", "POST", "PUT", "PATCH", "DELETE"].map(m => `<option ${m === (r?.method || (kind === "functions" ? "POST" : "GET")) ? "selected" : ""}>${m}</option>`).join("")}</select>
          <input name="path" value="${esc(r?.path || "/")}" spellcheck="false" autocapitalize="none" aria-label="Path">
          <button class="btn primary">${icon("send")}Send</button></div>
        <details ${r?.headers ? "open" : ""}><summary>Headers and body</summary>
          <label class="in"><span>Headers <small class="faint">(Name: value, one per line; Content-Type, Accept, Authorization and X-…)</small></span>
            <textarea name="headers" rows="2" spellcheck="false">${esc(r?.headers ?? (kind === "functions" ? "Content-Type: application/json" : ""))}</textarea></label>
          <label class="in"><span>Body</span><textarea name="body" rows="5" spellcheck="false">${esc(r?.body ?? (kind === "functions" ? '{"name": "AXoR"}' : ""))}</textarea></label></details>
        <p class="faint">Sent from inside the cluster to its service, so it works before the domain is public.</p>
        <div data-part="resp">${r?.resp ? respHtml(r.resp) : ""}</div></form>`;
    }
    const respHtml = x => `<div class="pk-resp"><div class="pk-resp-head"><span class="ci-pill ci-${x.status < 400 ? "ok" : x.status < 500 ? "wait" : "bad"}">${x.status}</span>
        <span class="num faint">${fmtNum(x.ms, 1)} ms</span><span class="faint">${esc(x.headers["Content-Type"] || x.headers["content-type"] || "")}</span></div>
      <pre class="src-log pk-resp-body">${esc(x.binary ? x.body : prettify(x.body))}${x.truncated ? "\n… (first 1 MB)" : ""}</pre></div>`;
    const prettify = t => { try { return JSON.stringify(JSON.parse(t), null, 2); } catch { return t; } };

    function logsTab() {
      return `<div class="src-logbar"><select data-part="tail" aria-label="Lines">${[100, 300, 1000, 5000].map(n => `<option ${n === logTail ? "selected" : ""}>${n}</option>`).join("")}</select>
          <button type="button" class="btn sm" data-pf="logs">${icon("reset")}Refresh</button>
          <span class="faint">Every pod${kind === "functions" ? ", and package installs" : ""}, oldest first.</span></div>
        <pre class="src-log pk-log" tabindex="0">${Loading.line("Reading logs…")}</pre>`;
    }
    async function loadLogs() {
      const pre = $(`${K.root} .pk-log`); if (!pre) return;
      pre.dataset.loaded = 1;
      try { const r = await api(`${K.api}/${sel}/logs?tail=${logTail}`); pre.textContent = r.text || "No output yet."; pre.scrollTop = pre.scrollHeight; }
      catch (e) { pre.textContent = e.message; }
    }

    function revisions() {
      return `<p class="faint pk-note">Each deploy is a revision with its own ${kind === "functions" ? "code, packages, " : "image, "}settings and environment; the last 10 are kept. Rolling back brings them all back; replicas and domains stay as they are now.</p>
        <div class="src-rows">${cur.history.map(h => `<div class="src-row"><span class="pk-rev num">#${h.revision}</span>
          <span class="src-row-main"><b>${esc(h.change || "–")}</b><small class="faint">${esc(kind === "apps" ? h.image || "" : tpl?.runtimes[h.runtime]?.title || h.runtime || "")} · ${since(h.created)}</small></span>
          ${h.current ? `<span class="badge clear">Live</span>` : `<button type="button" class="btn sm" data-rollback="${h.revision}">${icon("undo")}Roll back</button>`}</div>`).join("")}</div>`;
    }

    function statsTab() {
      if (!stats) return Loading.line("Counting calls…");
      const s = stats, max = Math.max(1, ...s.per_minute);
      const tile = (l, v, sub = "") => `<div class="stat"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
      return `<div class="stats pk-stats">${tile("Calls", fmtNum(s.calls, 0), s.last ? `last ${ago(s.last)}` : "none yet")}
          ${tile("Errors", fmtNum(s.errors, 0), `${fmtNum(s.client_errors, 0)} client errors (4xx)`)}
          ${tile("Median", s.p50_ms == null ? "–" : `${fmtNum(s.p50_ms, 1)} ms`, s.p95_ms == null ? "" : `95% under ${fmtNum(s.p95_ms, 1)} ms`)}
          ${tile("Slowest", s.max_ms == null ? "–" : `${fmtNum(s.max_ms, 1)} ms`, s.avg_ms == null ? "" : `average ${fmtNum(s.avg_ms, 1)} ms`)}</div>
        <div class="pk-spark" role="img" aria-label="Calls per minute over the last hour">${s.per_minute.map((n, i) => `<i style="height:${Math.max(n ? 6 : 2, n / max * 100)}%" title="${n} call${n === 1 ? "" : "s"}, ${60 - i} min ago"></i>`).join("")}</div>
        <div class="pk-spark-axis faint"><span>an hour ago</span><span>now</span></div>
        <p class="faint">Counted from the function's own log lines since its pods last started. <button type="button" class="btn sm" data-pf="stats">${icon("reset")}Refresh</button></p>`;
    }
    async function loadStats() {
      statsLoading = true;
      stats = await api(`${K.api}/${sel}/stats`).catch(e => ({ calls: 0, errors: 0, client_errors: 0, per_minute: Array(60).fill(0), error: e.message }));
      statsLoading = false;
      if (tab === "stats") renderMain();
    }

    // ---------- actions ----------
    async function act(a) {
      const x = cur;
      const go = async () => { await withSudo(() => api(`${K.api}/${x.name}/action`, { method: "POST", body: { action: a } })); Auth.toast(`${a[0].toUpperCase() + a.slice(1)}: ${x.name}`); await load(); schedule(); };
      if (a !== "stop") return go().catch(err);
      Auth.modal(`<h3>${icon("stop")}Stop ${esc(x.name)}?</h3><p class="muted">Its pods are removed and its address answers 503 until you start it again. Settings, revisions${kind === "apps" && x.settings.volume ? " and its volume" : ""} stay.</p>`,
        async () => { $("#modal").close(); await go().catch(err); }, { submit: "Stop", danger: true });
    }
    function remove() {
      const x = cur;
      Auth.modal(`<h3>${icon("trash")}Delete ${esc(x.name)}?</h3><p class="muted">Its pods, address, revisions and environment are deleted. This can't be undone.</p>
        ${kind === "apps" && x.settings.volume ? `<label class="chk"><input type="checkbox" name="volume"> Also delete its volume (the data in <code>${esc(x.settings.volume)}</code>)</label>` : ""}`,
        async f => {
          const vol = !!f.elements.volume?.checked;
          await withSudo(() => api(`${K.api}/${x.name}?volume=${vol}`, { method: "DELETE" }));
          $("#modal").close(); Auth.toast(`Deleted ${x.name}`); sel = null; cur = null; await load();
        }, { submit: "Delete", danger: true });
    }
    function rollback(rev) {
      Auth.modal(`<h3>${icon("undo")}Roll back ${esc(cur.name)} to #${rev}?</h3><p class="muted">Revision #${rev}'s ${kind === "functions" ? "code, packages" : "image"}, settings and environment come back as a new revision. The current one keeps answering until it's ready.</p>`,
        async () => {
          await withSudo(() => api(`${K.api}/${cur.name}/rollback`, { method: "POST", body: { revision: rev } }));
          $("#modal").close(); Auth.toast(`Rolling back to #${rev}`); tab = "overview"; await load(); schedule();
        }, { submit: "Roll back" });
    }
    async function send(f) {
      const el = f.elements, headers = {};
      for (const ln of el.headers.value.split("\n").map(x => x.trim()).filter(Boolean)) {
        const i = ln.indexOf(":"); if (i < 1) return Auth.toast(`“${ln}” isn't Name: value.`);
        headers[ln.slice(0, i).trim()] = ln.slice(i + 1).trim();
      }
      lastReq = { method: el.method.value, path: el.path.value.trim() || "/", headers: el.headers.value, body: el.body.value };
      const out = $("[data-part=resp]", f); out.innerHTML = Loading.line("Waiting for the answer…");
      try { lastReq.resp = await api(`${K.api}/${cur.name}/request`, { method: "POST", body: { method: lastReq.method, path: lastReq.path, headers, body: lastReq.body } }); out.innerHTML = respHtml(lastReq.resp); }
      catch (e) { out.innerHTML = `<div class="sl-err">${icon("alert")}<span>${esc(e.message)}</span></div>`; }
    }
    async function deployCode() {
      const m = $("[data-part=main]", root()), x = cur;
      const body = { ...fnBody(x), code: $("[name=code]", m).value, packages: $("[name=packages]", m).value };
      try {
        await withSudo(() => api(`${K.api}/${x.name}`, { method: "PUT", body }));
        Auth.toast(`Deploying ${x.name}`); m.dataset.showtab = ""; tab = "overview"; await load(); schedule();
      } catch (e) { err(e); }
    }
    const envBody = x => x.env.map(e => ({ key: e.key, value: e.secret ? null : e.value, secret: e.secret }));
    const fnBody = x => ({ name: x.name, runtime: x.settings.runtime, code: x.code, handler: x.settings.handler, packages: x.packages, env: envBody(x),
      cpu: x.settings.cpu, memory: x.settings.memory, timeout: x.settings.timeout, replicas: x.settings.replicas, autoscale_max: x.settings.autoscale_max, public: x.public });

    // ---------- the form ----------
    const envRow = (e = {}) => `<div class="dv-secret pk-env"><input name="ek" value="${esc(e.key || "")}" placeholder="NAME" autocapitalize="characters" spellcheck="false" maxlength="64" ${e.saved ? "readonly" : ""}>
      <input name="ev" ${e.secret ? `type="password" autocomplete="new-password" placeholder="${e.saved ? "saved: leave empty to keep" : "secret value"}"` : `value="${esc(e.value || "")}" placeholder="value"`} spellcheck="false">
      <label class="pk-secret" title="Secret: never shown again"><input type="checkbox" name="es" ${e.secret ? "checked" : ""} ${e.saved ? "disabled" : ""}>${icon("lock")}</label>
      <button type="button" class="iconbtn sm" data-rm aria-label="Remove variable">${icon("close")}</button></div>`;

    async function form(x) {
      try { await withSudo(() => api("/api/platform/sudo", { method: "POST" })); } catch (e) { return err(e); }
      if (kind === "functions" && !tpl) tpl = await api("/api/platform/templates").catch(() => null);
      const s = x?.settings || {};
      const v = kind === "apps"
        ? { image: "", port: 8080, replicas: 1, autoscale_max: 0, cpu: 0.5, memory: 256, health: "", command: "", volume: "", volume_gb: 1, ...s }
        : { runtime: "python3.12", handler: "", replicas: 1, autoscale_max: 0, cpu: 0.25, memory: 128, timeout: 30, ...s };
      const pub = x ? x.public : true;
      const fields = kind === "apps" ? `
        <label class="in"><span>Image</span><input name="image" value="${esc(v.image)}" required placeholder="nginx:1.27 or ghcr.io/org/app:1.2" autocapitalize="none" spellcheck="false" maxlength="300">
          <small class="faint">From any registry the server can pull from without signing in.</small></label>
        <div class="dv-two"><label class="in"><span>The app listens on port</span><input name="port" type="number" min="1" max="65535" value="${v.port}"></label>
          <label class="in"><span>Health check path <small class="faint">(optional)</small></span><input name="health" value="${esc(v.health)}" placeholder="/health" autocapitalize="none" spellcheck="false"></label></div>
        <label class="in"><span>Command <small class="faint">(optional: arguments that replace the image's default command)</small></span><input name="command" value="${esc(v.command)}" placeholder="gunicorn app:app -b 0.0.0.0:8080" autocapitalize="none" spellcheck="false"></label>`
        : `<div class="dv-two"><label class="in"><span>Runtime</span><select name="runtime" ${x ? "disabled" : ""}>${Object.entries(tpl?.runtimes || { "python3.12": { title: "Python 3.12" } }).map(([k, r]) => `<option value="${k}" ${k === v.runtime ? "selected" : ""}>${esc(r.title)}</option>`).join("")}</select></label>
          <label class="in"><span>Handler</span><input name="handler" value="${esc(v.handler)}" placeholder="${esc(tpl?.runtimes[v.runtime]?.handler || "handle")}" autocapitalize="none" spellcheck="false" maxlength="64"></label></div>
        ${x ? "" : `<label class="in"><span>Code <small class="faint">(edit it later on the Code tab)</small></span><textarea name="code" rows="9" spellcheck="false" class="pk-editor sm">${esc(tpl?.templates[v.runtime] || "")}</textarea></label>
        <label class="in"><span>Packages <small class="faint">(optional, one per line)</small></span><textarea name="packages" rows="2" spellcheck="false" placeholder="requests==2.32.3"></textarea></label>`}
        <label class="in"><span>Timeout (s) <small class="faint">(longest a call may take)</small></span><input name="timeout" type="number" min="1" max="900" value="${v.timeout}"></label>`;
      const f = Auth.modal(`<h3>${icon(K.icon)}${x ? `Edit ${esc(x.name)}` : `New ${K.one}`}</h3>
        <div class="dv-form">
        <label class="in"><span>Name</span><input name="name" value="${esc(x?.name || "")}" ${x ? "readonly" : "required"} pattern="[a-z]([a-z0-9\\-]{0,28}[a-z0-9])?" placeholder="${kind === "apps" ? "shop" : "hello"}" autocapitalize="none" spellcheck="false" maxlength="30">
          <small class="faint">Lowercase letters, digits and dashes. It answers at <code>https://<span data-part="nm">${esc(x?.name || "name")}</span>${esc(d?.suffix || "")}/</code></small></label>
        ${fields}
        <div class="dv-two"><label class="in"><span>CPU per pod <small class="faint">(cores)</small></span><input name="cpu" type="number" min="0.05" max="${kind === "apps" ? 8 : 4}" step="0.05" value="${v.cpu}"></label>
          <label class="in"><span>Memory per pod (MB)</span><input name="memory" type="number" min="${kind === "apps" ? 32 : 64}" max="${kind === "apps" ? 16384 : 4096}" step="32" value="${v.memory}"></label></div>
        <div class="dv-two"><label class="in"><span>Replicas</span><input name="replicas" type="number" min="${kind === "apps" ? 0 : 1}" max="20" value="${v.replicas}"></label>
          <label class="in"><span>Autoscale up to <small class="faint">(0 = off; on CPU)</small></span><input name="autoscale_max" type="number" min="0" max="${kind === "apps" ? 20 : 50}" value="${v.autoscale_max}"></label></div>
        ${kind === "apps" ? `<div class="dv-two"><label class="in"><span>Volume path <small class="faint">(optional: kept across deploys)</small></span><input name="volume" value="${esc(v.volume)}" placeholder="/data" autocapitalize="none" spellcheck="false" ${x?.settings.volume ? "readonly" : ""}></label>
          <label class="in"><span>Volume size (GB)</span><input name="volume_gb" type="number" min="1" max="100" value="${v.volume_gb}" ${x?.settings.volume ? "readonly" : ""}></label></div>
        <label class="in"><span>Custom domains <small class="faint">(optional, one per line; point them at this server)</small></span><textarea name="domains" rows="2" spellcheck="false" placeholder="shop.example.com">${esc((x?.domains || []).join("\n"))}</textarea></label>` : ""}
        <div class="in"><span>Environment <small class="faint">(tick the lock for secrets: stored encrypted, never shown again)</small></span><div class="dv-secrets" data-part="env">${(x?.env || []).map(e => envRow({ ...e, saved: e.secret })).join("")}</div>
          <button type="button" class="btn sm" data-add-env>${icon("plus")}Add variable</button></div>
        <label class="chk"><input type="checkbox" name="public" ${pub ? "checked" : ""}> Public: answer at its HTTPS address <small class="faint">(otherwise only Test / Invoke and other ${K.title.toLowerCase()} reach it)</small></label>
        </div>`,
        async f => {
          const el = f.elements, num = n => Number(el[n].value);
          const env = $$(".pk-env", f).map(r => {
            const key = $("[name=ek]", r).value.trim(), val = $("[name=ev]", r).value, secret = $("[name=es]", r).checked, saved = $("[name=ek]", r).readOnly;
            return key ? { key, value: saved && !val ? null : val, secret } : null;
          }).filter(Boolean);
          const common = { name: el.name.value.trim(), cpu: num("cpu"), memory: num("memory"), replicas: num("replicas"), autoscale_max: num("autoscale_max"), env, public: el.public.checked };
          const body = kind === "apps"
            ? { ...common, image: el.image.value.trim(), port: num("port"), health: el.health.value.trim(), command: el.command.value.trim(), volume: el.volume.value.trim(),
                volume_gb: num("volume_gb"), domains: el.domains.value.split(/\s+/).map(h => h.trim()).filter(Boolean) }
            : { ...common, runtime: x ? v.runtime : el.runtime.value, handler: el.handler.value.trim(), timeout: num("timeout"),
                code: x ? x.code : el.code.value, packages: x ? x.packages : el.packages.value };
          if (!body.name) throw new Error(`Name the ${K.one}.`);
          const r = await withSudo(() => api(x ? `${K.api}/${x.name}` : K.api, { method: x ? "PUT" : "POST", body }));
          $("#modal").close(); Auth.toast(x ? `Deploying ${r.name}` : `Created ${r.name}: starting`);
          sel = r.name; store.set(`paas.${kind}.sel`, sel); tab = "overview"; await load(); schedule();
        }, { submit: x ? "Deploy" : "Create" });
      $("#modal").classList.add("dv-wide");
      $("#modal").addEventListener("close", () => $("#modal").classList.remove("dv-wide"), { once: true });
      const el = f.elements;
      el.name.oninput = () => $("[data-part=nm]", f).textContent = el.name.value || "name";
      if (el.runtime && !x) el.runtime.onchange = () => { el.code.value = tpl?.templates[el.runtime.value] || ""; el.handler.placeholder = tpl?.runtimes[el.runtime.value]?.handler || ""; };
      $("[data-add-env]", f).onclick = () => { $("[data-part=env]", f).insertAdjacentHTML("beforeend", envRow()); $(".pk-env:last-child [name=ek]", f).focus(); };
      $("[data-part=env]", f).addEventListener("click", e => e.target.closest("[data-rm]")?.closest(".pk-env").remove());
      $("[data-part=env]", f).addEventListener("change", e => {  // the lock turns the value field into a password field
        if (e.target.name !== "es") return;
        const v2 = $("[name=ev]", e.target.closest(".pk-env")); v2.type = e.target.checked ? "password" : "text";
      });
      f.querySelectorAll(".pk-editor").forEach(tabKey);
      setTimeout(() => (x ? (el.image || el.handler) : el.name).focus(), 30);
    }

    // Tab in a code box inserts four spaces (Escape, then Tab, leaves it)
    function tabKey(ta) {
      let esc_ = false;
      ta.addEventListener("keydown", e => {
        if (e.key === "Escape") { esc_ = true; return; }
        if (e.key !== "Tab" || esc_ || e.shiftKey) { esc_ = false; return; }
        e.preventDefault();
        const a = ta.selectionStart;
        ta.setRangeText("    ", a, ta.selectionEnd, "end");
      });
    }

    function wire() {
      if (wired) return; wired = true;
      sel = store.get(`paas.${kind}.sel`, null);
      if (!tpl) api("/api/platform/templates").then(t => { tpl = t; if (d) render(); }).catch(() => {});
      const v = $(`#view-${K.view}`);
      v.addEventListener("click", e => {
        const b = e.target.closest("[data-pf], [data-sel], [data-tab], [data-rollback]"); if (!b) return;
        if (b.dataset.sel) return select(b.dataset.sel);
        if (b.dataset.tab) { tab = b.dataset.tab; if (tab === "stats") stats = null; return renderMain(); }
        if (b.dataset.rollback) return rollback(+b.dataset.rollback);
        const a = b.dataset.pf;
        if (a === "new") form(null);
        else if (a === "edit") form(cur);
        else if (a === "delete") remove();
        else if (["restart", "stop", "start"].includes(a)) act(a);
        else if (a === "logs") loadLogs();
        else if (a === "stats") { stats = null; loadStats(); renderMain(); }
        else if (a === "deploy-code") deployCode();
      });
      v.addEventListener("submit", e => { if (e.target.dataset.part === "req") { e.preventDefault(); send(e.target); } });
      v.addEventListener("change", e => { if (e.target.dataset.part === "tail") { logTail = +e.target.value; loadLogs(); } });
      v.addEventListener("focusin", e => { if (e.target.classList?.contains("pk-editor") && !e.target.dataset.tabkey) { e.target.dataset.tabkey = 1; tabKey(e.target); } });
    }
    return { open };
  }
  const apps = page("apps"), functions = page("functions");
  return { apps, functions };
})();
