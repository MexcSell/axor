/* Agents → Ecosystem (ecosystem.py), a section of the Agents page's operations side (agent-studio.js draws it):
   - The eight layers of an AI ecosystem, mission interface down to governance, each with live figures from the AXoR systems
     that do its work, a status (active this week, ready, not set up) and a link to the page.
   - Interoperability: MCP, A2A, agent identity, and where AXoR stands on each.
   - External agents: paste an A2A Agent Card to keep it for discovery; untrusted until you mark it reviewed. AXoR never
     fetches or calls them. */
const Ecosystem = (() => {
  let d = null, at = 0, loading = false, failed = "", wired = false, adding = false;
  const err = e => e && Auth.toast(e.message);
  const ST = { active: ["Active this week", "ok"], ready: ["Ready", "info"], missing: ["Not set up", "none"] };
  const TRUST = { untrusted: ["Untrusted", "warn"], reviewed: ["Reviewed", "ok"], blocked: ["Blocked", "bad"] };
  const IO = { partial: ["Partly", "info"], discovery: ["Discovery only", "warn"], internal: ["Inside AXoR", "ok"] };
  const num = v => v == null ? "–" : typeof v === "number" ? fmtNum(v, 0) : esc(String(v));
  const holding = () => !!document.activeElement?.closest?.(".eco-form");

  function need() {
    if (loading || Date.now() - at < 30000) return;
    loading = true; wire();
    api("/api/ecosystem").then(x => { d = x; failed = ""; }).catch(e => { failed = e.message; })
      .finally(() => { at = Date.now(); loading = false; if (!holding()) Studio.redraw(); });
  }

  function layers() {
    return `<ol class="eco-stack">${d.layers.map((l, i) => { const [s, tone] = ST[l.status];
      return `<li class="eco-layer s-${l.status}"><div class="eco-lh"><span class="eco-n">${i + 1}</span><div><b>${esc(l.title)}</b><small>${esc(l.about)}</small></div><span class="hq-chip t-${tone}">${s}</span></div>
        <div class="eco-items">${l.items.map(it => `<button type="button" class="eco-item" ${it.view ? `data-eco-view="${esc(it.view)}"` : "disabled"} ${it.detail ? `title="${esc(it.detail)}"` : ""}>
          <b>${num(it.value)}</b><span>${esc(it.label)}</span>${it.detail ? `<small>${esc(it.detail)}</small>` : ""}</button>`).join("")}</div></li>`; }).join("")}</ol>`;
  }
  function interop() {
    return `<div class="eco-io">${d.interop.map(x => { const [s, tone] = IO[x.status] || [x.status, "none"];
      return `<div class="eco-io-c"><div class="eco-io-h"><b>${esc(x.title)}</b><span class="hq-chip t-${tone}">${s}</span></div><p class="small">${esc(x.text)}</p>
        ${x.view ? `<button type="button" class="aos-link" data-eco-view="${esc(x.view)}">Open${icon("right")}</button>` : ""}</div>`; }).join("")}</div>`;
  }
  function registry() {
    const r = d.registry;
    return `<section class="aos-card eco-reg"><header><h3>${icon("globe")}External agents <span class="hq-n">${r.length}</span></h3>
        <button type="button" class="btn sm" data-eco="add">${icon("plus")}Add an Agent Card</button></header>
      <p class="small faint">Agents outside AXoR that publish an A2A Agent Card (at <code>/.well-known/agent-card.json</code>). Paste the card to keep its skills for discovery. AXoR never fetches the card or calls the agent, and an entry stays untrusted until you review it.</p>
      ${adding ? `<form class="eco-form" data-eco-form><label><span>Agent Card (JSON)</span><textarea name="card" rows="7" required placeholder='{"name": "…", "description": "…", "url": "https://…", "skills": [{"id": "…", "name": "…"}]}'></textarea></label>
        <div class="eco-form-row"><label><span>Where you found it</span><input name="url" maxlength="500" placeholder="https://example.com/.well-known/agent-card.json"></label>
          <label><span>Note</span><input name="note" maxlength="400" placeholder="Why it might help"></label></div>
        <div class="row"><button type="submit" class="btn primary sm">Add as untrusted</button><button type="button" class="btn sm" data-eco="cancel">Cancel</button></div></form>` : ""}
      ${r.length ? `<ul class="eco-agents">${r.map(a => { const [t, tone] = TRUST[a.trust] || [a.trust, "none"], i = a.info;
        return `<li><div class="eco-ah"><b>${esc(a.name)}</b><span class="hq-chip t-${tone}">${t}</span>${i.version ? `<small class="faint">v${esc(i.version)}</small>` : ""}${i.provider ? `<small class="faint">${esc(i.provider)}</small>` : ""}</div>
          ${i.description ? `<p class="small">${esc(i.description)}</p>` : ""}
          ${i.skills.length ? `<div class="eco-skills">${i.skills.map(s => `<span class="eco-skill" title="${esc(s.description)}">${esc(s.name)}</span>`).join("")}</div>` : ""}
          <p class="small faint">${i.endpoint ? `Endpoint in the card: <code>${esc(i.endpoint)}</code> · ` : ""}${i.capabilities.length ? `${esc(i.capabilities.join(", "))} · ` : ""}${i.auth.length ? `auth: ${esc(i.auth.join(", "))} · ` : ""}${a.url ? `from ${esc(a.url)}` : "pasted"}${a.note ? ` · ${esc(a.note)}` : ""}</p>
          <div class="row eco-acts"><label class="small">Trust <select data-eco-trust="${a.id}">${Object.entries(TRUST).map(([k, [l]]) => `<option value="${k}" ${k === a.trust ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <button type="button" class="iconbtn" data-eco-del="${a.id}" aria-label="Remove ${esc(a.name)}" title="Remove">${icon("trash")}</button></div></li>`; }).join("")}</ul>`
        : adding ? "" : `<p class="faint small">None yet.</p>`}</section>`;
  }

  function view() {
    need();
    if (!d) return failed ? `<p class="aos-warnline">${icon("alert")}${esc(failed)}</p>` : `<div class="aos-loading">${icon("layers")} Reading the ecosystem…</div>`;
    const s = d.score;
    return `<div class="eco">
      <section class="aos-card eco-head"><header><h3>${icon("layers")}AXoR as one ecosystem</h3><span class="small faint">${s.active} of ${s.total} layers active this week · ${s.ready} ready</span></header>
        <p class="small">You manage missions; AXoR manages the intelligence, workforce, tools, execution and learning. Each layer shows the parts of AXoR doing that job, with this week's figures for your account. A big number of agents isn't the goal: shared context, clear ownership, independent verification and budget control are.</p></section>
      ${layers()}
      <section class="aos-card"><header><h3>${icon("link")}Interoperability</h3></header>${interop()}</section>
      ${registry()}</div>`;
  }

  async function send(path, opts, msg) {
    try { d = await api(path, opts); at = Date.now(); adding = false; if (msg) Auth.toast(msg); document.activeElement?.blur?.(); Studio.redraw(); }
    catch (e) { err(e); }
  }
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const t = e.target; if (!t.closest(".eco")) return;
      const v = t.closest("[data-eco-view]"); if (v) return setView(v.dataset.ecoView);
      const del = t.closest("[data-eco-del]");
      if (del) return UI.confirm({ title: "Remove this agent from the registry?", ok: "Remove", body: "Only the saved card goes; nothing else changes.",
        run: () => send(`/api/ecosystem/agents/${del.dataset.ecoDel}`, { method: "DELETE" }, "Removed") }).catch(err);
      const b = t.closest("[data-eco]"); if (!b) return;
      if (b.dataset.eco === "add") { adding = true; Studio.redraw(); setTimeout(() => document.querySelector(".eco-form textarea")?.focus(), 0); }
      if (b.dataset.eco === "cancel") { adding = false; document.activeElement?.blur?.(); Studio.redraw(); }
    });
    document.addEventListener("change", e => {
      const s = e.target.closest?.("[data-eco-trust]");
      if (s) send(`/api/ecosystem/agents/${s.dataset.ecoTrust}`, { method: "PATCH", body: { trust: s.value } }, "Saved");
    });
    document.addEventListener("submit", e => {
      const f = e.target.closest?.("[data-eco-form]"); if (!f) return;
      e.preventDefault();
      send("/api/ecosystem/agents", { method: "POST", body: { card: f.elements.card.value, url: f.elements.url.value, note: f.elements.note.value } }, "Added as untrusted");
    });
  }
  return { view, holding };
})();
