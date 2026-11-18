/* All files (artifacts.py /api/artifacts; file-catalog.css; prefix fc-): one catalog over Drive, Competition team files and
   notebooks, mission deliverables, long-task files and knowledge, shown in My workspace beside its own Files. Read only: each
   item opens where it lives, and each store keeps its own permissions, versions and history. Scopes: Personal, Company, Team,
   Mission, Agent; Division and Project are said not to be tracked yet rather than guessed. */
const FileCatalog = (() => {
  const SRC_IC = { drive: "folder", teams: "trophy", missions: "target", longtasks: "route", knowledge: "book" };
  const KIND_IC = { file: "file", folder: "folder", finding: "bulb", deliverable: "doc", plan: "list", record: "book" };
  let d = null, q = "", scope = "", source = "", seq = 0, timer = null, el = null, wired = false;
  const size = n => n == null ? "" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)} MB` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)} kB` : `${n} B`;
  const when = ts => ts ? ago(ts) : "";

  function render(host) {
    el = host; wire();
    el.innerHTML = `<div class="fc">${head()}<div class="fc-body">${d ? "" : Loading.line("Reading every place your files live…")}</div></div>`;
    if (d) draw(); else load();
  }
  function head() {
    return `<header class="fc-head"><div><h2>${icon("layers")}All files</h2>
        <p class="muted">Everything AXoR keeps for you, in one list: your drive, your Competition teams' files and notebooks, mission deliverables, long-task files and knowledge. Each opens where it lives, with that place's own permissions, versions and history.</p></div></header>
      <div class="fc-bar"><label class="fc-q">${icon("search")}<input type="search" data-fc="q" value="${esc(q)}" placeholder="Search every place: names, paths, findings, knowledge…" aria-label="Search all files"></label>
        <select data-fc="source" aria-label="Where">${[["", "Every place"], ...Object.entries({ drive: "Drive", teams: "Competition teams", missions: "Missions", longtasks: "Long tasks", knowledge: "Knowledge" })].map(([k, l]) => `<option value="${k}"${k === source ? " selected" : ""}>${l}</option>`).join("")}</select></div>`;
  }
  function draw() {
    const body = el?.isConnected && el.querySelector(".fc-body"); if (!body) return;
    const S_ = d.scopes, n = d.counts, all = Object.values(n).reduce((a, b) => a + b, 0);
    const chips = `<div class="fc-scopes" role="group" aria-label="Scope"><button type="button" class="chip" data-fcscope="" aria-pressed="${!scope}">All <b>${all}</b></button>
      ${S_.map(s => `<button type="button" class="chip" data-fcscope="${s.key}" aria-pressed="${scope === s.key}">${esc(s.label)} <b>${n[s.key] || 0}</b></button>`).join("")}
      <span class="muted small fc-untracked" title="No store records these scopes yet, except company knowledge records (shown in their place)">${esc(d.untracked.join(" and "))}: not tracked yet</span></div>`;
    const bad = Object.values(d.sources).filter(s => !s.ok);
    const rows = d.items.map(i => `<li><button type="button" class="fc-row" data-fcopen="${esc(JSON.stringify(i.open))}" title="Open in ${esc(d.sources[i.source]?.label || i.source)}">
        <span class="fc-ic">${icon(KIND_IC[i.kind] || "file")}</span>
        <span class="fc-t"><b>${esc(i.title)}</b><small>${icon(SRC_IC[i.source] || "folder")}${esc(i.where)}${i.snippet ? ` · <span class="fc-snip">${esc(String(i.snippet).replace(/[\u0002\u0003]/g, ""))}</span>` : ""}</small></span>
        <span class="fc-m"><span class="fc-scope s-${i.scope}">${esc(d.scopes.find(s => s.key === i.scope)?.label || i.scope)}</span>${i.state ? `<span class="muted small">${esc(i.state)}</span>` : ""}
          <span class="muted small">${[size(i.size), i.versions > 1 ? `${i.versions} versions` : "", when(i.updated)].filter(Boolean).join(" · ")}</span></span></button></li>`).join("");
    body.innerHTML = `${chips}
      ${bad.length ? `<p class="muted small fc-bad">${icon("info")}${bad.map(s => `${esc(s.label)}: ${esc(s.error)}`).join(" · ")}</p>` : ""}
      ${d.items.length ? `<ul class="fc-list">${rows}</ul>${d.total > d.items.length ? `<p class="muted small">Showing the newest ${d.items.length} of ${d.total}: search to narrow it down.</p>` : ""}`
        : `<div class="empty">${q ? "Nothing matches that anywhere." : "Nothing yet. Files you add to the drive, your teams' files and your missions' results show up here."}</div>`}
      ${!q && d.sources.knowledge?.ok ? `<p class="muted small">${icon("book")}Knowledge shows when you search: type two letters or more.</p>` : ""}`;
  }
  async function load() {
    const my = ++seq;
    try {
      const r = await api(`/api/artifacts?${new URLSearchParams({ q, scope, source })}`);
      if (my !== seq) return;
      d = r; draw();
    } catch (e) { const b = el?.isConnected && el.querySelector(".fc-body"); if (my === seq && b) b.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
  function open(o) {
    if (o.view === "drive") {
      setView("drive");
      if (o.folder || o.space) setTimeout(() => Drive.go?.("folder", { space: o.space === "with" ? "with" : o.space || "mine", folder: o.folder || null }), 250);
    } else if (o.view === "teams") { MiningWork.go(o.sub); MiningWork.openPage(o.team); }
    else if (o.view === "mos") MissionOS.show(o.id);
    else if (o.view === "infiagent") { store.set("ia.tid", o.id); setView("infiagent"); }
    else if (o.view === "knowledge") Knowledge.show("records", o.id);
    else if (o.view === "myknowledge") Knowledge.show("workspace", o.id);
    else setView(o.view);
  }
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("input", e => {
      if (!e.target.matches?.(".fc [data-fc=q]")) return;
      q = e.target.value; clearTimeout(timer);
      timer = setTimeout(load, 280);
    });
    document.addEventListener("change", e => { if (e.target.matches?.(".fc [data-fc=source]")) { source = e.target.value; load(); } });
    document.addEventListener("click", e => {
      const s = e.target.closest?.(".fc [data-fcscope]"); if (s) { scope = s.dataset.fcscope; return load(); }
      const o = e.target.closest?.(".fc [data-fcopen]"); if (o) { try { open(JSON.parse(o.dataset.fcopen)); } catch { /* a malformed row: nothing to open */ } }
    });
  }
  return { render, reload: () => { d = null; } };
})();
