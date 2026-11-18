/* Cluster view (admins only): the Kubernetes cluster AXoR runs on, and the domain and HTTPS its platform uses.
   Workloads: the node's capacity and use, then each AXoR namespace with its deployments (restart, scale, logs) and pods
   (logs, recycle), and recent warnings. Domain & HTTPS: the platform domain and AXoR's address on it, Let's Encrypt,
   AXoR's own certificate authority (download its root), the edge certificate, whether the domain is delegated to AXoR
   DNS, and a sync. Updates: the updater on the host that deploys each new commit (updates.js). Changes ask for sudo;
   the server and the cluster's admission policies enforce every rule. */
const Cluster = (() => {
  let d = null, pf = null, tab = "workloads", wired = false, timer = null, deleg = null, logsFor = null;
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const withSudo = fn => Admin.withSudo(fn);
  const bytes = n => n == null ? "–" : n < 1073741824 ? `${fmtNum(n / 1048576, 0)} MB` : `${fmtNum(n / 1073741824, 1)} GB`;
  const age = ts => { if (!ts) return "–"; const s = Date.now() / 1000 - ts; return s < 3600 ? `${Math.max(1, Math.floor(s / 60))}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`; };
  const when = ts => ts ? new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "–";
  const root = () => $("#k8s");
  // names Let's Encrypt can't sign (the server refuses them too)
  const PRIVATE = /\.(internal|local|test|localhost|example|invalid|lan|home\.arpa)$/;
  const acmeNote = priv => priv ? "Needs a public domain you own: set one above first. Until then AXoR's own certificate authority signs everything."
    : "Needs this domain delegated to AXoR DNS (or custom domains pointed here), and ports 53 and 443 open (they are after the cutover).";
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };

  async function open() {
    wire();
    if (!d && !pf) root().innerHTML = `<h1 class="page">Cluster</h1>${Loading.line("Reading the cluster…")}`;
    await load();
    clearTimeout(timer);
    // only Workloads refreshes on its own: a poll must never replace the Domain form while it's being edited
    const tick = async () => {
      if ($("#view-cluster").hidden) return;
      if (tab === "workloads") await load();
      timer = setTimeout(tick, d?.namespaces?.some(n => n.deployments.some(x => x.rolling)) ? 3000 : 15000);
    };
    timer = setTimeout(tick, 15000);
  }
  async function load() {
    const [a, b] = await Promise.allSettled([api("/api/cluster"), api("/api/platform")]);
    d = a.status === "fulfilled" ? a.value : { error: a.reason.message };
    pf = b.status === "fulfilled" ? b.value : { error: b.reason.message };
    render();
  }

  function render() {
    if (!$(".k8-body", root())) root().innerHTML = `<h1 class="page">Cluster</h1>
      <p class="lead">The Kubernetes cluster AXoR, its edge and DNS, and your apps and functions run on, and the domain and HTTPS they're served with. Changes ask you to confirm it's you once every 10 minutes and are recorded in the audit log.</p>
      <div class="seg k8-tabs" role="tablist">${[["workloads", "Workloads", "layers"], ["https", "Domain & HTTPS", "lock"], ["updates", "Updates", "rocket"]].map(([k, l, ic]) =>
        `<button type="button" role="tab" data-k8tab="${k}" aria-pressed="${tab === k}">${icon(ic)}${l}</button>`).join("")}</div>
      <div class="k8-body"></div>`;
    $$(".k8-tabs button", root()).forEach(b => b.setAttribute("aria-pressed", b.dataset.k8tab === tab));
    const body = $(".k8-body", root());
    if (tab === "updates") { put(body, `<div class="up-root"></div>`); return Updates.show($(".up-root", body)); }  // it loads and refreshes itself
    put(body, tab === "workloads" ? workloads() : https());
  }

  // ---------- workloads ----------
  function workloads() {
    if (d.error) return `<div class="empty">${esc(d.error)}</div>`;
    const tile = (ic, l, v, sub, pct) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div>${pct == null ? "" : `<div class="bar"><i style="width:${Math.min(100, pct)}%"></i></div>`}</div>`;
    const nodes = d.nodes.map(n => {
      const cpu = n.cpu_used != null ? n.cpu_used / n.cpu * 100 : null, mem = n.memory_used != null ? n.memory_used / n.memory * 100 : null;
      return [tile("server", "Node", `<span class="k8-node">${n.ready ? '<span class="ci ci-ok"></span>' : '<span class="ci ci-bad"></span>'}${esc(n.name)}</span>`,
        `${esc(n.version || "")} · ${esc(n.address || "")}${n.pressure.length ? ` · <b class="k8-warn">${esc(n.pressure.join(", "))}</b>` : ""}`),
      tile("chip", "CPU", n.cpu_used == null ? "–" : `${fmtNum(n.cpu_used, 1)}`, `of ${fmtNum(n.cpu, 0)} cores in use`, cpu),
      tile("chips", "Memory", bytes(n.memory_used), `of ${bytes(n.memory)}`, mem),
      tile("layers", "Pods", fmtNum(d.pods_total, 0), `AXoR's, of ${n.pods_max} the node takes`)].join("");
    }).join("");
    const spaces = d.namespaces.filter(ns => ns.deployments.length || ns.system && ns.name !== "axor-host").map(ns => {
      const rows = ns.deployments.map(x => {
        const pods = ns.pods.filter(p => p.deployment === x.name), restarts = pods.reduce((a, p) => a + p.restarts, 0);
        const problem = pods.map(p => p.problem).find(Boolean);
        const cls = x.replicas === 0 ? "off" : x.failed || (problem && x.ready < x.replicas) ? "bad" : x.rolling ? "run" : x.ready >= x.replicas ? "ok" : "wait";
        const self = ns.name === d.self.namespace && x.name === d.self.deployment;
        const cpu = pods.reduce((a, p) => a + (p.cpu || 0), 0), mem = pods.reduce((a, p) => a + (p.memory || 0), 0);
        return `<tr data-ns="${esc(ns.name)}" data-dep="${esc(x.name)}"><td><span class="ci ci-${cls}"></span> <b>${esc(x.name)}</b>${self ? ' <span class="badge new">AXoR</span>' : ""}
            ${problem ? `<small class="pk-problem">${esc(problem)}</small>` : ""}</td>
          <td class="num">${x.ready}/${x.replicas}${x.rolling ? ' <span class="faint">rolling</span>' : ""}</td>
          <td class="k8-img" title="${esc(x.images.join(", "))}">${esc(x.images.map(i => i.replace(/^docker\.io\//, "")).join(", "))}</td>
          <td class="r num">${restarts || '<span class="faint">0</span>'}</td><td class="r num">${pods.some(p => p.cpu != null) ? fmtNum(cpu, 3) : "–"}</td><td class="r num">${pods.some(p => p.memory != null) ? bytes(mem) : "–"}</td>
          <td class="num">${age(x.restarted || x.created)}</td>
          <td class="r k8-acts"><button class="iconbtn" data-k8="logs" title="Logs" aria-label="Logs of ${esc(x.name)}">${icon("terminal")}</button>${ns.read_only ? "" : `
            <button class="iconbtn" data-k8="restart" title="Restart" aria-label="Restart ${esc(x.name)}">${icon("reset")}</button>
            ${self ? "" : `<button class="iconbtn" data-k8="scale" title="${x.replicas ? "Stop" : "Start"}" aria-label="${x.replicas ? "Stop" : "Start"} ${esc(x.name)}">${icon(x.replicas ? "stop" : "play")}</button>`}`}</td></tr>`;
      }).join("") || `<tr><td colspan="8"><div class="empty">Nothing here yet.</div></td></tr>`;
      const pods = ns.pods.map(p => `<tr data-ns="${esc(ns.name)}" data-pod="${esc(p.name)}"><td><code>${esc(p.name)}</code></td><td>${esc(p.deleting ? "Stopping" : p.phase)}${p.ready ? "" : ' <span class="faint">not ready</span>'}</td>
          <td class="r num">${p.restarts}</td><td class="num">${esc(p.ip || "–")}</td><td class="num">${age(p.created)}</td>
          <td class="r k8-acts"><button class="iconbtn" data-k8="podlogs" title="Logs" aria-label="Logs of ${esc(p.name)}">${icon("terminal")}</button>${ns.read_only ? "" :
            `<button class="iconbtn danger" data-k8="recycle" title="Recycle" aria-label="Recycle ${esc(p.name)}">${icon("cycle")}</button>`}</td></tr>`).join("");
      return `<h2 class="section-title">${icon(ns.system ? "shield" : ns.read_only ? "gear" : "apps")}${esc(ns.title)} <span class="faint k8-ns">${esc(ns.name)}</span>${ns.read_only ? ' <span class="tag">read-only</span>' : ""}</h2>
        <div class="tablewrap flat"><table class="grid k8-table"><thead><tr><th>Deployment</th><th>Ready</th><th>Image</th><th class="r">Restarts</th><th class="r">CPU</th><th class="r">Memory</th><th>Age</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
        ${pods ? `<details class="k8-pods"><summary>${ns.pods.length} pod${ns.pods.length === 1 ? "" : "s"}</summary><div class="tablewrap flat"><table class="grid k8-table"><thead><tr><th>Pod</th><th>Phase</th><th class="r">Restarts</th><th>IP</th><th>Age</th><th></th></tr></thead><tbody>${pods}</tbody></table></div></details>` : ""}`;
    }).join("");
    const events = d.events.length ? `<h2 class="section-title">${icon("alert")}Warnings</h2><ul class="pk-events k8-events">${d.events.slice(0, 20).map(e =>
      `<li class="warn"><span class="num faint">${age(e.time)}</span><b>${esc(e.reason)}</b><span><code>${esc(e.namespace)}/${esc(e.name)}</code> ${esc(e.message)}</span></li>`).join("")}</ul>` : "";
    return `<div class="stats">${nodes}</div>${spaces}${events}`;
  }

  // ---------- domain & HTTPS ----------
  function https() {
    if (pf.error) return `<div class="empty">${esc(pf.error)}</div>`;
    const s = pf.settings, ca = pf.ca, leaf = pf.leaf, e = pf.edge;
    const internal = PRIVATE.test(s.domain);
    const row = (k, v) => `<div class="kv-row"><span>${k}</span><b>${v}</b></div>`;
    const days = t => t ? Math.round((t - Date.now() / 1000) / 86400) : null;
    const dl = deleg ? (deleg.error ? `<div class="sl-err">${icon("alert")}<span>${esc(deleg.error)}</span></div>` : `
      <div class="k8-deleg ${deleg.delegated ? "ok" : ""}">${icon(deleg.delegated ? "check" : "info")}<span>${deleg.delegated ? `Public resolvers send ${esc(deleg.zone)} to AXoR DNS.` : `Public resolvers don't send ${esc(deleg.zone)} here yet.`}</span></div>
      <table class="grid k8-table"><thead><tr><th>Resolver</th><th>Name servers it sees</th><th></th></tr></thead><tbody>${deleg.public.map(r => `<tr><td class="num">${esc(r.resolver)}</td>
        <td>${r.error ? `<span class="faint">${esc(r.error)}</span>` : r.nameservers.map(n => `<code>${esc(n)}</code>`).join(" ") || `<span class="faint">${esc(r.rcode || "none")}</span>`}</td><td>${r.match ? '<span class="badge clear">matches</span>' : ""}</td></tr>`).join("")}</tbody></table>`) : "";
    return `<div class="k8-grid">
      <section class="card k8-card"><h3>${icon("globe")}Domain</h3>
        <form class="dv-form k8-form" data-part="domain">
          <label class="in"><span>Platform domain</span><input name="domain" value="${esc(s.domain)}" required autocapitalize="none" spellcheck="false" maxlength="253">
            <small class="faint">Apps answer at <code>&lt;app&gt;.apps.${esc(s.domain)}</code>, functions at <code>&lt;fn&gt;.fn.${esc(s.domain)}</code>. ${internal ? "This is a private name: only AXoR DNS knows it." : ""}</small></label>
          <label class="in"><span>AXoR's address</span><input name="console" value="${esc(s.console)}" autocapitalize="none" spellcheck="false" maxlength="253" placeholder="${esc(s.domain)}">
            <small class="faint">The domain itself, or a name under it such as <code>axor.${esc(s.domain)}</code>.</small></label>
          <label class="in"><span>This server's public address <small class="faint">(optional)</small></span><input name="public_ip" value="${esc(s.public_ip)}" placeholder="${esc(pf.public_ip || "")} (detected)" autocapitalize="none" spellcheck="false" maxlength="45"></label>
          <label class="toggle-row"><span><b>Let's Encrypt certificates</b><small class="faint" data-part="acme-note">${acmeNote(internal)}</small></span>
            <span class="switch"><input type="checkbox" name="acme" ${s.acme && !internal ? "checked" : ""} ${internal ? "disabled" : ""}><span></span></span></label>
          <div class="dv-two" data-part="acme" ${s.acme ? "" : "hidden"}><label class="in"><span>Contact email <small class="faint">(optional)</small></span><input name="acme_email" type="email" value="${esc(s.acme_email)}" maxlength="254"></label>
            <label class="chk k8-staging"><input type="checkbox" name="acme_staging" ${s.acme_staging ? "checked" : ""}> Staging <small class="faint">(test certificates browsers don't trust, with generous limits)</small></label></div>
          <div class="row"><button class="btn primary">${icon("check")}Save</button><span class="faint">Saving updates DNS, the certificate and every app's and function's address.</span></div>
        </form></section>
      <section class="card k8-card"><h3>${icon("lock")}HTTPS</h3>
        ${row("Certificates", s.acme ? `Let's Encrypt${s.acme_staging ? " (staging)" : ""}, AXoR's CA as fallback` : "AXoR's own certificate authority")}
        ${row("AXoR", `<code>https://${esc(s.console)}/</code>`)}
        ${row("Apps", `<code>https://${esc(pf.hosts.apps)}/</code>`)}
        ${row("Functions", `<code>https://${esc(pf.hosts.functions)}/</code>`)}
        ${row("Edge", e ? (e.error ? esc(e.error) : `${e.ready}/${e.replicas} ready <small class="faint">${esc(e.images[0] || "")}</small>`) : "–")}
        ${leaf ? row("Edge certificate", `${leaf.names.length} names, renews in ${days(leaf.not_after) - 30} days <small class="faint">${esc(leaf.fp.slice(0, 16))}…</small>`) : ""}
        ${ca ? row("Certificate authority", `${esc((ca.subject.match(/CN=([^,]+)/) || [, ca.subject])[1])} <small class="faint">until ${when(ca.not_after)}</small>`) : ""}
        <div class="row k8-btns">${ca ? `<a class="btn" href="/api/platform/ca.crt" download>${icon("download")}Download AXoR's root certificate</a>` : ""}
          <button type="button" class="btn" data-k8="renew">${icon("reset")}Renew now</button></div>
        <p class="faint">Until the domain is public, trust that root certificate on your devices to open the platform's HTTPS addresses without warnings. It can only vouch for names under ${esc(s.domain)}.</p>
        ${pf.sync?.error ? `<div class="sl-err">${icon("alert")}<span>${esc(pf.sync.error)}</span></div>` : ""}
        <div class="row"><button type="button" class="btn" data-k8="sync">${icon("cycle")}Sync DNS, certificate and routes</button>
          <span class="faint">${pf.sync?.synced ? `Last synced ${ago(pf.sync.synced)}` : "Not synced yet"}</span></div></section>
      <section class="card k8-card k8-wide"><h3>${icon("route")}Point ${esc(s.domain)} at AXoR DNS</h3>
        ${internal ? `<p class="muted">${esc(s.domain)} is a private name. Set a domain you own above to serve the platform publicly.</p>` : `
        <p class="muted">At your registrar (or the DNS of the parent domain), set ${esc(s.domain)}'s name servers to <code>ns1.${esc(s.domain)}</code> and <code>ns2.${esc(s.domain)}</code>, with glue records pointing both at <code>${esc(pf.public_ip || "this server")}</code>. Then open port 53 with k8s/cutover.sh.</p>`}
        <div class="row"><button type="button" class="btn" data-k8="deleg">${icon("search")}Check delegation</button></div>${dl}</section>
    </div>`;
  }

  // ---------- actions ----------
  async function act(b) {
    const tr = b.closest("tr"), ns = tr?.dataset.ns, a = b.dataset.k8;
    const x = ns && d.namespaces.find(n => n.name === ns);
    if (a === "logs") return logs(ns, x.pods.filter(p => p.deployment === tr.dataset.dep));
    if (a === "podlogs") return logs(ns, x.pods.filter(p => p.name === tr.dataset.pod));
    if (a === "restart") {
      const dep = tr.dataset.dep, self = ns === d.self.namespace && dep === d.self.deployment;
      return Auth.modal(`<h3>${icon("reset")}Restart ${esc(dep)}?</h3><p class="muted">${self ? "This is AXoR itself: the page reconnects in a minute or so." : "Its pod is replaced by a fresh one. AXoR's own services run one pod each, so it's briefly unavailable."}</p>`,
        async () => { $("#modal").close(); try { await withSudo(() => api(`/api/cluster/deployments/${ns}/${dep}`, { method: "POST", body: { action: "restart" } })); Auth.toast(`Restarting ${dep}`); load(); } catch (e) { err(e); } },
        { submit: "Restart" });
    }
    if (a === "scale") {
      const dep = x.deployments.find(y => y.name === tr.dataset.dep), n = dep.replicas ? 0 : 1;
      const go = async () => { try { await withSudo(() => api(`/api/cluster/deployments/${ns}/${dep.name}`, { method: "POST", body: { action: "scale", replicas: n } })); Auth.toast(`${n ? "Starting" : "Stopping"} ${dep.name}`); load(); } catch (e) { err(e); } };
      if (n) return go();
      return Auth.modal(`<h3>${icon("stop")}Stop ${esc(dep.name)}?</h3><p class="muted">Its pods are removed until you start it again. Anything that depends on it stops working.</p>`,
        async () => { $("#modal").close(); await go(); }, { submit: "Stop", danger: true });
    }
    if (a === "recycle") {
      const pod = tr.dataset.pod;
      return Auth.modal(`<h3>${icon("cycle")}Recycle ${esc(pod)}?</h3><p class="muted">The pod is deleted and its deployment starts a fresh one.</p>`,
        async () => { $("#modal").close(); try { await withSudo(() => api(`/api/cluster/pods/${ns}/${pod}`, { method: "DELETE" })); Auth.toast(`Recycling ${pod}`); load(); } catch (e) { err(e); } },
        { submit: "Recycle", danger: true });
    }
    if (a === "renew" || a === "sync") {
      try { pf = await withSudo(() => api(`/api/platform/${a === "renew" ? "certificate" : "sync"}`, { method: "POST" })); Auth.toast(a === "renew" ? "New edge certificate signed (the edge picks it up within a minute or two)" : pf.sync.error ? "Synced, with errors" : "Synced"); render(); }
      catch (e) { err(e); }
    }
    if (a === "deleg") {
      deleg = null; b.disabled = true;
      try { deleg = await api("/api/platform/delegation"); } catch (e) { deleg = { error: e.message }; }
      b.disabled = false; render();
    }
  }

  async function logs(ns, pods, tail = 300, previous = false) {
    if (!pods.length) return Auth.toast("No pods to read: it's stopped.");
    const pod = pods[0];
    logsFor = pod.name;
    const dlg = $("#modal");
    Auth.modal(`<h3>${icon("terminal")}Logs <span class="faint">${esc(pod.name)}</span></h3>
      <div class="toolbar">${pods.length > 1 ? `<select name="pod" aria-label="Pod">${pods.map(p => `<option>${esc(p.name)}</option>`).join("")}</select>` : ""}
        ${pod.containers.length > 1 ? `<select name="container" aria-label="Container">${pod.containers.map(c => `<option>${esc(c)}</option>`).join("")}</select>` : ""}
        <select name="tail" aria-label="Lines"><option>100</option><option selected>300</option><option>1000</option><option>5000</option></select>
        <label class="chk"><input type="checkbox" name="previous"> Before the last restart</label>
        <button type="button" class="btn" data-reload>${icon("reset")}Refresh</button></div>
      <pre class="dk-logs" tabindex="0">${Loading.line("Reading logs…")}</pre>`, async () => dlg.close(), { submit: "Close" });
    dlg.classList.add("dk-wide");
    dlg.addEventListener("close", () => dlg.classList.remove("dk-wide"), { once: true });
    const f = $("form", dlg), pre = $(".dk-logs", dlg);
    const read = async () => {
      const name = f.elements.pod?.value || pod.name; logsFor = name;
      const q = new URLSearchParams({ tail: f.elements.tail.value, previous: f.elements.previous.checked, container: f.elements.container?.value || "" });
      pre.textContent = "Reading logs…";
      try { const r = await api(`/api/cluster/pods/${ns}/${name}/logs?${q}`); if (logsFor === name) { pre.textContent = r.text || "No output yet."; pre.scrollTop = pre.scrollHeight; } }
      catch (e) { pre.textContent = e.message; }
    };
    f.addEventListener("change", read);
    $("[data-reload]", dlg).onclick = read;
    read();
  }

  async function save(f) {
    const el = f.elements;
    const body = { domain: el.domain.value.trim(), console: el.console.value.trim(), public_ip: el.public_ip.value.trim(), acme: el.acme.checked,
      acme_email: el.acme_email.value.trim(), acme_staging: el.acme_staging.checked };
    const changed = body.domain !== pf.settings.domain;
    const go = async () => {
      const btn = $("button.primary", f); btn.disabled = true;
      try { pf = await withSudo(() => api("/api/platform/settings", { method: "PUT", body })); deleg = null; Auth.toast(pf.sync?.error ? "Saved, but: " + pf.sync.error : "Saved: DNS, certificate and routes updated"); render(); }
      catch (e) { err(e); } finally { btn.disabled = false; }
    };
    if (!changed) return go();
    Auth.modal(`<h3>${icon("globe")}Move the platform to ${esc(body.domain)}?</h3><p class="muted">Every app and function moves to its address under ${esc(body.domain)}, and AXoR makes a new certificate authority for it: devices that trusted the old root need the new one. AXoR DNS keeps the old zone, without the platform's records.</p>`,
      async () => { $("#modal").close(); await go(); }, { submit: "Move" });
  }

  function wire() {
    if (wired) return; wired = true;
    const v = $("#view-cluster");
    v.addEventListener("click", e => {
      const t = e.target.closest("[data-k8tab]"); if (t) { tab = t.dataset.k8tab; render(); return tab === "updates" ? null : load(); }
      const b = e.target.closest("[data-k8]"); if (b) act(b);
    });
    v.addEventListener("submit", e => { if (e.target.dataset.part === "domain") { e.preventDefault(); save(e.target); } });
    v.addEventListener("change", e => { if (e.target.name === "acme") $("[data-part=acme]", v).hidden = !e.target.checked; });
    v.addEventListener("input", e => {  // the switch follows the domain as it's typed
      if (e.target.name !== "domain") return;
      const f = e.target.form, priv = PRIVATE.test(e.target.value.trim().replace(/\.$/, "").toLowerCase()) || !e.target.value.includes(".");
      f.elements.acme.disabled = priv;
      if (priv && f.elements.acme.checked) { f.elements.acme.checked = false; $("[data-part=acme]", f).hidden = true; }
      $("[data-part=acme-note]", f).textContent = acmeNote(priv);
    });
  }

  return { open };
})();
