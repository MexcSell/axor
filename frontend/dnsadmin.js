/* DNS view (admins only): the zones AXoR DNS, this server's own name server, answers for. Zones on the left; the
   selected zone's records (add, edit, delete; the platform's and the name servers' records are marked and kept by
   AXoR), its settings, BIND import and export, a query tool that asks the server as a resolver would, a delegation
   check against public resolvers, and recent queries. Changes ask for sudo; the name server checks every record. */
const DNSAdmin = (() => {
  let d = null, sel = null, zone = null, tab = "records", wired = false, timer = null, q = "", tq = "", query = null, deleg = null;
  const TYPES = ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"];
  const HINT = { A: "203.0.113.10", AAAA: "2001:db8::10", CNAME: "target.example.com", MX: "10 mail.example.com", TXT: "v=spf1 mx -all",
    NS: "ns1.other-dns.net", SRV: "10 5 5060 sip.example.com", CAA: '0 issue "letsencrypt.org"' };
  const OWNER = { platform: ["Platform", "Kept by the platform (Cluster → Domain & HTTPS, and apps' custom domains)"], zone: ["Name server", "Glue for the zone's own name servers"],
    acme: ["Challenge", "A Let's Encrypt challenge, removed by itself"] };
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const withSudo = fn => Admin.withSudo(fn);
  const root = () => $("#dnsp");
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const fq = n => n === "@" ? zone.name : `${n}.${zone.name}`;

  async function open() {
    wire();
    if (!d) root().innerHTML = `<h1 class="page">DNS</h1>${Loading.line("Loading zones…")}`;
    await load();
    clearTimeout(timer);
    const tick = async () => { if ($("#view-dns").hidden) return; if (tab === "activity") await load(); timer = setTimeout(tick, 10000); };
    timer = setTimeout(tick, 10000);
  }
  async function load() {
    try { d = await api("/api/dns"); }
    catch (e) { d = null; root().innerHTML = `<h1 class="page">DNS</h1><p class="lead">${lead}</p><div class="empty">${esc(e.message)}</div>`; return; }
    if (!d.zones.some(z => z.name === sel)) sel = store.get("dns.sel", null);
    if (!d.zones.some(z => z.name === sel)) sel = d.platform_zone && d.zones.some(z => z.name === d.platform_zone) ? d.platform_zone : d.zones[0]?.name ?? null;
    zone = sel ? await api(`/api/dns/zones/${encodeURIComponent(sel)}`).catch(() => zone) : null;
    render();
  }
  const lead = "AXoR DNS is this server's own authoritative name server: it answers for the zones below and nothing else (no recursion, rate-limited, zone transfers refused). Changes ask you to confirm it's you once every 10 minutes and are recorded in the audit log.";
  async function select(name) { sel = name; store.set("dns.sel", name); zone = null; query = null; deleg = null; render(); zone = await api(`/api/dns/zones/${encodeURIComponent(name)}`).catch(e => (err(e), null)); render(); }

  function render() {
    if (!d) return;
    if (!$(".dn-main", root())) root().innerHTML = `<h1 class="page">DNS</h1><p class="lead">${lead}</p>
      <div class="stats" data-part="stats"></div>
      <div class="src dv dn">
        <aside class="card src-repos"><div class="src-side-head"><b>Zones</b><span class="spacer"></span>
          <button type="button" class="btn sm primary" data-dn="new">${icon("plus")}New</button></div>
          <div class="src-list" data-part="list"></div></aside>
        <div class="card src-main dn-main" data-part="main"></div>
      </div>`;
    const st = d.stats || {}, total = d.zones.reduce((a, z) => a + z.records, 0);
    const recent = (st.per_sec || []).filter(([t]) => Date.now() / 1000 - t < 300).reduce((a, [, n]) => a + n, 0);
    const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
    put($("[data-part=stats]", root()), [
      tile("globe", "Zones", fmtNum(d.zones.length, 0), `${fmtNum(total, 0)} records`),
      tile("chart", "Queries", fmtNum(st.total || 0, 0), st.since ? `since ${new Date(st.since * 1000).toLocaleString()}` : "since start"),
      tile("clock", "Last 5 minutes", fmtNum(recent, 0), `${fmtNum(recent / 300, 2)} a second`),
      tile("shield", "Rate-limited", fmtNum(st.limited || 0, 0), `over ${d.rate} answers/s per network`),
    ].join(""));
    put($("[data-part=list]", root()), d.zones.map(z => `<button type="button" class="src-item" data-sel="${esc(z.name)}" aria-current="${z.name === sel}">
        ${icon(z.name === d.platform_zone ? "rocket" : "globe")}<span class="src-item-main"><b>${esc(z.name)}</b><small class="faint">${z.records} record${z.records === 1 ? "" : "s"}${z.name === d.platform_zone ? " · platform" : ""}</small></span></button>`).join("")
      || `<div class="empty">No zones yet.</div>`);
    renderMain();
  }

  function renderMain() {
    const el = $("[data-part=main]", root()); if (!el) return;
    if (!sel) return put(el, `<div class="empty">A zone is a domain this server answers for. Create one, then point the domain's name servers here.</div>`);
    if (!zone) return put(el, Loading.line("Loading…"));
    const z = zone, platform = z.name === d.platform_zone;
    const TABS = [["records", "Records", "list"], ["query", "Query", "search"], ["activity", "Activity", "chart"]];
    const head = `<div class="pk-head"><div class="pk-title"><h2>${esc(z.name)}</h2>${platform ? '<span class="badge new">Platform</span>' : ""}
        <span class="faint num">serial ${z.serial}</span></div>
      <div class="pk-acts"><button type="button" class="btn sm" data-dn="settings">${icon("gear")}Settings</button>
        <button type="button" class="btn sm" data-dn="import">${icon("upload")}Import</button>
        <button type="button" class="btn sm" data-dn="export">${icon("download")}Export</button>
        ${platform ? "" : `<button type="button" class="iconbtn danger" data-dn="delete" title="Delete zone" aria-label="Delete ${esc(z.name)}">${icon("trash")}</button>`}</div></div>
      <div class="src-facts"><span>${icon("server")}Name servers ${z.nameservers.map(n => `<code>${esc(n)}</code>`).join(" ")}</span><span>${icon("clock")}TTL ${z.ttl}s</span><span>${icon("mail")}${esc(z.email)}</span></div>
      <div class="src-tabs" role="tablist">${TABS.map(([k, l, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}</button>`).join("")}</div>`;
    put(el, head + `<div class="src-body">${{ records, query: queryTab, activity }[tab]()}</div>`);
  }

  function records() {
    const rows = zone.records.filter(r => (!tq || r.type === tq) && (!q || [r.name, r.value, r.note].some(x => (x || "").toLowerCase().includes(q))));
    const apex = [["@", "SOA", `${zone.nameservers[0]}. ${zone.email.replace("@", ".")}. ${zone.serial}`], ...zone.nameservers.map(n => ["@", "NS", n + "."])];
    return `<div class="src-filters"><div class="search">${icon("search")}<input data-part="q" type="search" placeholder="Search name, value or note" value="${esc(q)}"></div>
        <select data-part="tq" aria-label="Type"><option value="">All types</option>${TYPES.map(t => `<option ${t === tq ? "selected" : ""}>${t}</option>`).join("")}</select>
        <span class="spacer"></span><button type="button" class="btn sm primary" data-dn="add">${icon("plus")}Add record</button></div>
      <div class="tablewrap flat dn-table"><table class="grid"><thead><tr><th>Name</th><th>Type</th><th>Value</th><th class="r">TTL</th><th>Note</th><th></th></tr></thead><tbody>
        ${!q && !tq ? apex.map(([n, t, v]) => `<tr class="dn-sys"><td><code>${esc(n)}</code></td><td><span class="tag">${t}</span></td><td class="dn-val"><code>${esc(v)}</code></td><td class="r num">${zone.ttl}</td>
          <td><span class="faint">From the zone's settings</span></td><td></td></tr>`).join("") : ""}
        ${rows.map(r => { const o = OWNER[r.owner];
          return `<tr data-rid="${r.id}"><td><code title="${esc(fq(r.name))}">${esc(r.name)}</code></td><td><span class="tag">${esc(r.type)}</span></td><td class="dn-val"><code>${esc(r.value)}</code></td>
            <td class="r num">${r.ttl}</td><td>${o ? `<span class="badge muted" title="${esc(o[1])}">${esc(o[0])}</span> ` : ""}<span class="faint">${esc(r.note)}</span></td>
            <td class="r k8-acts">${r.owner && r.owner !== "zone" ? "" : `<button class="iconbtn" data-dn="edit" title="Edit" aria-label="Edit ${esc(r.name)} ${esc(r.type)}">${icon("edit")}</button>
              <button class="iconbtn danger" data-dn="remove" title="Delete" aria-label="Delete ${esc(r.name)} ${esc(r.type)}">${icon("trash")}</button>`}</td></tr>`; }).join("")
          || (q || tq ? `<tr><td colspan="6"><div class="empty">No records match.</div></td></tr>` : "")}
      </tbody></table></div>`;
  }

  function queryTab() {
    const r = query?.result;
    const sec = (title, rows) => rows?.length ? `<div class="dn-sec"><b>${title}</b><pre class="src-log">${esc(rows.join("\n"))}</pre></div>` : "";
    return `<form class="pk-test dn-query" data-part="query"><div class="pk-reqline"><input name="name" value="${esc(query?.name || zone.name)}" spellcheck="false" autocapitalize="none" aria-label="Name">
        <select name="type" aria-label="Type">${[...TYPES, "SOA", "ANY"].map(t => `<option ${t === (query?.type || "A") ? "selected" : ""}>${t}</option>`).join("")}</select>
        <button class="btn primary">${icon("search")}Ask</button></div>
      <p class="faint">Asks AXoR DNS directly, the way a resolver on the internet would, and shows its answer like <code>dig</code>.</p>
      ${query?.error ? `<div class="sl-err">${icon("alert")}<span>${esc(query.error)}</span></div>` : ""}
      ${r ? `<div class="pk-resp-head"><span class="ci-pill ci-${r.rcode === "NOERROR" ? "ok" : r.rcode === "NXDOMAIN" ? "wait" : "bad"}">${esc(r.rcode)}</span>
        <span class="faint">${r.aa ? "authoritative" : "not authoritative (a delegation)"}</span></div>
        ${sec("Answer", r.answer)}${sec("Authority", r.authority)}${sec("Additional", r.additional)}${!r.answer.length && !r.authority.length ? `<p class="faint">No records.</p>` : ""}` : ""}</form>
      <h3 class="pk-h">${icon("route")}Delegation</h3>
      <p class="faint">Whether public resolvers send ${esc(zone.name)} to this server, by its NS records at the parent zone.</p>
      <div class="row"><button type="button" class="btn" data-dn="deleg">${icon("search")}Check now</button></div>
      ${deleg ? (deleg.error ? `<div class="sl-err">${icon("alert")}<span>${esc(deleg.error)}</span></div>` : `<div class="k8-deleg ${deleg.delegated ? "ok" : ""}">${icon(deleg.delegated ? "check" : "info")}
        <span>${deleg.delegated ? "Delegated here." : `Not delegated here yet: set the name servers at your registrar to ${deleg.nameservers.map(n => `<code>${esc(n)}</code>`).join(" and ")}${d.public_ip ? `, with glue records for <code>${esc(d.public_ip)}</code>` : ""}.`}</span></div>
        <table class="grid k8-table"><tbody>${deleg.public.map(p => `<tr><td class="num">${esc(p.resolver)}</td><td>${p.error ? `<span class="faint">${esc(p.error)}</span>` : p.nameservers.map(n => `<code>${esc(n)}</code>`).join(" ") || `<span class="faint">${esc(p.rcode)}</span>`}</td>
          <td>${p.match ? '<span class="badge clear">matches</span>' : ""}</td></tr>`).join("")}</tbody></table>`) : ""}`;
  }

  function activity() {
    const st = d.stats;
    if (!st) return `<div class="empty">No statistics from the name server.</div>`;
    const mine = st.recent.filter(x => x.name.toLowerCase().replace(/\.$/, "").endsWith(zone.name));
    const per = Array(60).fill(0), now = Math.floor(Date.now() / 1000);
    for (const [t, n] of st.per_sec) { const i = 59 - Math.floor((now - t) / 10); if (i >= 0 && i < 60) per[i] += n; }
    const max = Math.max(1, ...per);
    return `<div class="dn-act"><div class="pk-spark" role="img" aria-label="Queries over the last ten minutes">${per.map((n, i) => `<i style="height:${Math.max(n ? 6 : 2, n / max * 100)}%" title="${n} quer${n === 1 ? "y" : "ies"}"></i>`).join("")}</div>
      <div class="pk-spark-axis faint"><span>10 minutes ago</span><span>now (every zone)</span></div>
      <div class="dn-counts">${Object.entries(st.rcodes).map(([k, n]) => `<span class="tag">${esc(k)} ${fmtNum(n, 0)}</span>`).join(" ")} ${Object.entries(st.types).map(([k, n]) => `<span class="tag">${esc(k)} ${fmtNum(n, 0)}</span>`).join(" ")}</div>
      <h3 class="pk-h">${icon("list")}Recent queries for ${esc(zone.name)}</h3>
      ${mine.length ? `<div class="tablewrap flat"><table class="grid"><thead><tr><th>Time</th><th>Client</th><th>Name</th><th>Type</th><th>Answer</th></tr></thead><tbody>${mine.slice(0, 100).map(x =>
        `<tr><td class="num">${new Date(x.t * 1000).toLocaleTimeString()}</td><td class="num">${esc(x.client)} <span class="faint">${esc(x.proto)}</span></td><td><code>${esc(x.name)}</code></td><td>${esc(x.type)}</td><td>${esc(x.rcode)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="faint">None in the last ${st.recent.length} queries.</p>`}</div>`;
  }

  // ---------- forms ----------
  async function unlock() { await withSudo(() => api("/api/platform/sudo", { method: "POST" })); }

  async function recordForm(r) {
    try { await unlock(); } catch (e) { return err(e); }
    const v = { name: "@", type: "A", value: "", ttl: zone.ttl, note: "", ...(r || {}) };
    const f = Auth.modal(`<h3>${icon("globe")}${r ? "Edit record" : "Add record"} <span class="faint">${esc(zone.name)}</span></h3>
      <div class="dv-form">
      <div class="dv-two"><label class="in"><span>Name</span><input name="name" value="${esc(v.name)}" required spellcheck="false" autocapitalize="none" maxlength="253">
          <small class="faint"><code>@</code> for ${esc(zone.name)} itself, <code>www</code>, or <code>*.apps</code> for a wildcard. Full name: <code data-part="fq">${esc(fq(v.name))}</code></small></label>
        <label class="in"><span>Type</span><select name="type">${TYPES.map(t => `<option ${t === v.type ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
      <label class="in"><span>Value</span><input name="value" value="${esc(v.value)}" required spellcheck="false" autocapitalize="none" maxlength="4100" placeholder="${esc(HINT[v.type])}"></label>
      <div class="dv-two"><label class="in"><span>TTL (seconds)</span><input name="ttl" type="number" min="30" max="604800" value="${v.ttl}"></label>
        <label class="in"><span>Note <small class="faint">(optional, only shown here)</small></span><input name="note" value="${esc(v.note)}" maxlength="200"></label></div>
      </div>`,
      async f => {
        const el = f.elements, body = { name: el.name.value.trim() || "@", type: el.type.value, value: el.value.value.trim(), ttl: Number(el.ttl.value) || null, note: el.note.value.trim() };
        const z = encodeURIComponent(zone.name);
        await withSudo(() => api(r ? `/api/dns/zones/${z}/records/${r.id}` : `/api/dns/zones/${z}/records`, { method: r ? "PUT" : "POST", body }));
        $("#modal").close(); Auth.toast(r ? "Record saved" : `Added ${body.type} ${body.name}`); await load();
      }, { submit: r ? "Save" : "Add" });
    const el = f.elements;
    el.type.onchange = () => el.value.placeholder = HINT[el.type.value];
    el.name.oninput = () => $("[data-part=fq]", f).textContent = fq(el.name.value.trim().replace(/\.$/, "") || "@");
    setTimeout(() => (r ? el.value : el.name).focus(), 30);
  }

  async function zoneForm() {
    try { await unlock(); } catch (e) { return err(e); }
    const f = Auth.modal(`<h3>${icon("globe")}New zone</h3><div class="dv-form">
      <label class="in"><span>Domain</span><input name="name" required placeholder="example.com" spellcheck="false" autocapitalize="none" maxlength="253"></label>
      <label class="in"><span>Name servers <small class="faint">(optional, one per line)</small></span><textarea name="ns" rows="2" spellcheck="false" placeholder="ns1.<domain>&#10;ns2.<domain>"></textarea>
        <small class="faint">By default ns1 and ns2 under the domain, with glue records for ${esc(d.public_ip || "this server")}.</small></label>
      </div>`,
      async f => {
        const el = f.elements, body = { name: el.name.value.trim(), nameservers: el.ns.value.split(/\s+/).filter(Boolean) };
        const z = await withSudo(() => api("/api/dns/zones", { method: "POST", body }));
        $("#modal").close(); Auth.toast(`Created ${z.name}`); sel = z.name; store.set("dns.sel", sel); await load();
      }, { submit: "Create" });
    setTimeout(() => f.elements.name.focus(), 30);
  }

  async function settingsForm() {
    try { await unlock(); } catch (e) { return err(e); }
    Auth.modal(`<h3>${icon("gear")}${esc(zone.name)} settings</h3><div class="dv-form">
      <label class="in"><span>Name servers <small class="faint">(one per line: the apex's NS records, and the SOA's first)</small></span><textarea name="ns" rows="3" spellcheck="false">${esc(zone.nameservers.join("\n"))}</textarea></label>
      <div class="dv-two"><label class="in"><span>Contact</span><input name="email" value="${esc(zone.email)}" maxlength="253"></label>
        <label class="in"><span>Default TTL (seconds)</span><input name="ttl" type="number" min="30" max="86400" value="${zone.ttl}"></label></div></div>`,
      async f => {
        const el = f.elements;
        await withSudo(() => api(`/api/dns/zones/${encodeURIComponent(zone.name)}`, { method: "PATCH", body: { nameservers: el.ns.value.split(/\s+/).filter(Boolean), email: el.email.value.trim(), ttl: Number(el.ttl.value) } }));
        $("#modal").close(); Auth.toast("Zone saved"); await load();
      });
  }

  async function importForm() {
    try { await unlock(); } catch (e) { return err(e); }
    Auth.modal(`<h3>${icon("upload")}Import into ${esc(zone.name)}</h3><div class="dv-form">
      <label class="in"><span>BIND zone file</span><textarea name="text" rows="10" spellcheck="false" placeholder="$ORIGIN ${esc(zone.name)}.&#10;www  300  IN  A  203.0.113.10"></textarea>
        <small class="faint">SOA lines are skipped; NS records at the apex become the zone's name servers. Records that clash with existing ones are skipped.</small></label>
      <label class="chk"><input type="checkbox" name="replace"> Replace the records added by hand first <small class="faint">(the platform's stay)</small></label></div>`,
      async f => {
        const r = await withSudo(() => api(`/api/dns/zones/${encodeURIComponent(zone.name)}/import`, { method: "POST", body: { text: f.elements.text.value, replace: f.elements.replace.checked } }));
        $("#modal").close(); Auth.toast(`Imported ${r.added} record${r.added === 1 ? "" : "s"}${r.skipped ? `, skipped ${r.skipped}` : ""}`); await load();
      }, { submit: "Import" });
  }

  async function exportZone() {
    try {
      const r = await api(`/api/dns/zones/${encodeURIComponent(zone.name)}/export`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([r.text], { type: "text/plain" })); a.download = `${zone.name}.zone`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) { err(e); }
  }

  function removeRecord(r) {
    Auth.modal(`<h3>${icon("trash")}Delete this record?</h3><p><code>${esc(fq(r.name))}</code> <span class="tag">${esc(r.type)}</span> <code>${esc(r.value)}</code></p><p class="muted">Resolvers may keep answering with it for up to its TTL (${r.ttl}s).</p>`,
      async () => { await withSudo(() => api(`/api/dns/zones/${encodeURIComponent(zone.name)}/records/${r.id}`, { method: "DELETE" })); $("#modal").close(); Auth.toast("Record deleted"); await load(); },
      { submit: "Delete", danger: true });
  }

  function removeZone() {
    Auth.modal(`<h3>${icon("trash")}Delete ${esc(zone.name)}?</h3><p class="muted">Every record in it goes, and this server stops answering for it. This can't be undone (export it first to keep a copy).</p>`,
      async () => { await withSudo(() => api(`/api/dns/zones/${encodeURIComponent(zone.name)}`, { method: "DELETE" })); $("#modal").close(); Auth.toast(`Deleted ${zone.name}`); sel = null; zone = null; await load(); },
      { submit: "Delete", danger: true });
  }

  function wire() {
    if (wired) return; wired = true;
    const v = $("#view-dns");
    v.addEventListener("click", e => {
      const b = e.target.closest("[data-dn], [data-sel], [data-tab]"); if (!b) return;
      if (b.dataset.sel) return select(b.dataset.sel);
      if (b.dataset.tab) { tab = b.dataset.tab; return renderMain(); }
      const a = b.dataset.dn, r = zone?.records.find(x => x.id === +b.closest("tr")?.dataset.rid);
      if (a === "new") zoneForm();
      else if (a === "add") recordForm(null);
      else if (a === "edit") recordForm(r);
      else if (a === "remove") removeRecord(r);
      else if (a === "settings") settingsForm();
      else if (a === "import") importForm();
      else if (a === "export") exportZone();
      else if (a === "delete") removeZone();
      else if (a === "deleg") { deleg = null; b.disabled = true; api(`/api/dns/zones/${encodeURIComponent(zone.name)}/delegation`).then(x => deleg = x, e => deleg = { error: e.message }).finally(renderMain); }
    });
    v.addEventListener("input", e => {
      if (e.target.dataset.part === "q") { q = e.target.value.trim().toLowerCase(); const pos = e.target.selectionStart; renderMain(); const i = $("[data-part=q]", v); i.focus(); i.setSelectionRange(pos, pos); }
    });
    v.addEventListener("change", e => { if (e.target.dataset.part === "tq") { tq = e.target.value; renderMain(); } });
    v.addEventListener("submit", async e => {
      if (e.target.dataset.part !== "query") return;
      e.preventDefault();
      const el = e.target.elements; query = { name: el.name.value.trim(), type: el.type.value };
      try { query.result = await api(`/api/dns/resolve?${new URLSearchParams({ name: query.name, type: query.type })}`); } catch (x) { query.error = x.message; }
      renderMain();
    });
  }

  return { open };
})();
