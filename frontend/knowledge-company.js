/* Knowledge Hub · Company Knowledge (knowledge.js draws the frame and calls this; knowledge_spaces.py; prefix kb-).
   Tabs: Overview (ask, the lifecycle in numbers, what waits for review, recent knowledge, connected sources, the rules),
   Company knowledge (every record, filtered), Divisions & projects (the scope tree, who reads each scope, grants),
   Agent contributions, Skills & procedures, Experiences & experiments, Review & governance (the queue: submitted,
   contested, due for review, reported not useful), Knowledge graph and Analytics (reuse, usefulness, acceptance).
   A record's page: its text, type, scope and owner; the automatic checks and an optional model review; approve or
   reject the exact version you read; outcomes; who read it and whether it helped; connections and versions. */
const KnowledgeCo = (() => {
  const TABS = [["overview", "dash", "Overview"], ["knowledge", "book", "Knowledge"], ["scopes", "layers", "Divisions & projects"], ["contributions", "bot", "Contributions"],
                ["procedures", "route", "Skills & procedures"], ["experiences", "trophy", "Experiences"], ["review", "shield", "Review"], ["graph", "branch", "Graph"], ["analytics", "chart", "Analytics"],
                ["retrieval", "target", "Retrieval & quality"]];  // knowledge-rag.js
  const ST = { submitted: "warn", verified: "ok", contested: "bad", rejected: "none", superseded: "none" };
  const WHY = { submitted: ["warn", "Waiting for review"], contested: ["bad", "Contested"], due: ["run", "Due for review"], reported: ["warn", "Reported not useful"] };
  const KIND = { company: "Company", division: "Division", project: "Project", team: "Team", agent: "Agent" };
  let scopeSel = "company", adding = false, sugg = null, sLoading = false;  // sugg: suggested connections (knowledge_improve.py)
  const H = () => Knowledge.h;

  const counts = c => { const d = c.d; return { review: d.counts.queue + (d.counts.requests || 0) ? `<span class="hq-n alert">${d.counts.queue + (d.counts.requests || 0)}</span>` : "", knowledge: d.counts.records, contributions: d.counts.agent_contributions }; };
  const actions = () => `<button type="button" class="btn" data-kb-tab="review">${icon("shield")}Review queue</button><button type="button" class="btn primary" data-kb-co="add">${icon("plus")}Add knowledge</button>`;
  function kpis(c) {
    const n = c.d.counts, kpi = (label, v, sub, to, tone = "") => `<button type="button" class="kb-kpi ${tone}" data-kb-tab="${to}"><span>${label}</span><b>${(v || 0).toLocaleString()}</b><small>${sub}</small></button>`;
    return `<div class="kb-kpis">${kpi("Knowledge items", n.records, `${n.verified} verified`, "knowledge")}${kpi("Pending review", n.pending, `${n.queue} in the queue in all`, "review", n.pending ? "t-warn" : "")}
      ${kpi("Agent contributions", n.agent_contributions, "submitted by your agents", "contributions")}${kpi("Reuse events", n.uses_month, `last 30 days · ${n.uses.toLocaleString()} in all`, "analytics")}</div>`;
  }
  const stateChip = (c, s) => H().chip(ST[s] || "none", c.labels.states[s] || s || "–");
  const ktChip = (c, k) => `<span class="kb-kt kb-kt-${k}">${(c.labels.ktypes[k] || [k])[0]}</span>`;
  const conf = v => v === null || v === undefined ? "" : `<span class="kb-conf" title="Confidence"><i style="--v:${Math.round(v * 100)}%"></i>${Math.round(v * 100)}%</span>`;
  const who = r => (r.contributor || "").startsWith("agent:") ? `${icon("bot")}${esc(r.owner || "an agent")}` : `${icon("users")}${esc(r.contributor || "you")}`;
  function table(c, list, empty) {
    const { when } = H();
    if (!list.length) return H().empty(empty);
    return `<div class="kb-table kb-ctable" role="table"><div class="kb-tr kb-th" role="row"><span>Knowledge</span><span>Type</span><span>Scope</span><span>State</span><span>Reuse</span><span>Updated</span></div>
      ${list.slice(0, 400).map(r => `<button type="button" class="kb-tr" role="row" data-kb-item="${r.id}"><span class="kb-cell-main"><span><b>${esc(r.title)}</b><small>${who(r)} · ${esc(r.body)}</small></span></span>
        <span>${ktChip(c, r.ktype)}</span><span class="kb-faint">${esc(r.scope_label)}</span><span>${stateChip(c, r.state)}${r.status === "archived" ? " " + H().chip("none", "archived") : ""}${conf(r.confidence)}</span>
        <span class="kb-faint">${r.uses.n ? `${r.uses.n}×${r.uses.good || r.uses.bad ? ` · ${r.uses.good}↑ ${r.uses.bad}↓` : ""}` : "–"}</span><span class="kb-faint">${when(r.updated)}</span></button>`).join("")}</div>
      ${list.length > 400 ? `<p class="kb-note">Showing 400 of ${list.length}: narrow the filters.</p>` : ""}`;
  }
  function filters(c, list, fixedK) {
    const f = c.f, t = (f.text || "").toLowerCase();
    const out = list.filter(r => (!f.ktype || fixedK || r.ktype === f.ktype) && (!f.state || r.state === f.state) && (!f.scope || (r.scope || "company") === f.scope)
      && (!f.who || (f.who === "agents") === (r.contributor || "").startsWith("agent:")) && (f.archived ? true : r.status === "kept") && (!t || (r.title + " " + r.body).toLowerCase().includes(t)));
    const sel = (name, label, opts) => `<label><span>${label}</span><select data-kb-cf="${name}"><option value="">All</option>${opts.map(([v, l]) => `<option value="${esc(v)}" ${f[name] === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
    const bar = `<div class="kb-filterbar">${fixedK ? "" : sel("ktype", "Type", Object.entries(c.labels.ktypes).map(([k, [l]]) => [k, l]))}${sel("state", "State", Object.entries(c.labels.states))}
      ${sel("scope", "Scope", c.d.scopes.map(s => [s.ref, `${KIND[s.kind]}: ${s.label}`]))}${sel("who", "From", [["agents", "Agents"], ["people", "People"]])}
      <label class="kb-check kb-arch"><input type="checkbox" data-kb-cf="archived" ${f.archived ? "checked" : ""}> Archived too</label>
      <label class="kb-grow"><span>Filter</span><input type="search" data-kb-cf="text" value="${esc(f.text || "")}" placeholder="Words in the title or text"></label></div>`;
    return [bar, out];
  }

  // ---------- tabs ----------
  function body(c) {
    if (c.rec) return recordView(c);
    const t = c.tab;
    return (adding ? addForm(c) : "") + (t === "knowledge" ? knowledge(c) : t === "scopes" ? scopes(c) : t === "contributions" ? contributions(c) : t === "procedures" ? byKind(c, ["procedural", "technical"], "Skills & procedures",
      "How to do things, and the code, architecture and configuration behind them: what your agents follow.") : t === "experiences" ? H().card("trophy", "Latest outcomes", `<span class="kb-faint">30 days</span>`, outcomesList(c.d.improve)) + byKind(c, ["episodic", "evaluative"], "Experiences & experiments",
      "What happened and what the tests showed: successes and failures are both kept, so no one repeats a failed experiment.") : t === "review" ? review(c) : t === "graph" ? H().graphCard() + suggestCards(c)
      : t === "analytics" ? analytics(c) : t === "retrieval" && typeof KnowledgeRag === "object" ? KnowledgeRag.tab(H(), "company") : overview(c));
  }
  function overview(c) {
    const d = c.d, n = d.counts, h = H(), a = d.analytics;
    const rate = a.useful.rated ? Math.round(100 * a.useful.good / a.useful.rated) : null;
    const steps = [["search", "Discovery", n.uses_month, "reads by agents and you (30 days)"], ["upload", "Contribution", n.pending, "waiting: from agents and from My Knowledge"],
                   ["shield", "Validation & review", n.queue, "in the review queue"], ["check", "Approval", n.verified, "verified records"],
                   ["layers", "Distribution", d.scopes.filter(s => s.n).length, `scopes holding knowledge · ${d.grants.length} grants`], ["cycle", "Reuse & feedback", a.useful.rated, rate === null ? "rated by agents" : `rated · ${rate}% useful`]];
    const q = d.queue.slice(0, 6), byId = Object.fromEntries(d.records.map(r => [r.id, r]));
    const ex = d.exchange, cp = (ex.company_projects || []).reduce((s, x) => s + x.n, 0);
    return `${h.askCard("company")}${c.hits ? h.card("search", `Results for “${esc(c.hits.q)}”`, `<button type="button" class="linkbtn" data-kb="clear-search">Clear</button>`, h.results(c.hits)) : ""}
      ${h.card("cycle", "The knowledge lifecycle", "", `<ol class="kb-cycle">${steps.map(([ic, l, v, s], i) => `<li><span class="kb-cycle-n">${i + 1}</span>${icon(ic)}<b>${(v || 0).toLocaleString()}</b><span>${l}</span><small>${s}</small></li>`).join("")}</ol>
        <p class="kb-note">Agents search what they may read, contribute what they learn, and say whether it helped; nothing they write is trusted until you approve it, and outcomes update the record.</p>`)}
      ${d.company ? "" : `<p class="kb-banner">${icon("info")}No Company yet: the company scope works now; divisions and projects appear once you set up the Company page.${document.querySelector('nav.side [data-view="company"]:not([hidden])') ? ` <button type="button" class="linkbtn" ${h.go({ view: "company" })}>Open Company</button>` : ""}</p>`}
      <div class="kb-grid">
        ${h.card("shield", "Waiting for review", `<button type="button" class="linkbtn" data-kb-tab="review">All ${n.queue}</button>`, q.length ? `<ul class="kb-list">${q.map(x => `<li><span>${h.chip(...WHY[x.why])} <button type="button" class="linkbtn" data-kb-item="${x.id}">${esc(byId[x.id]?.title || "")}</button></span><small class="kb-faint">${byId[x.id] ? who(byId[x.id]) : ""}</small></li>`).join("")}</ul>` : h.empty("Nothing waits for review."))}
        ${h.card("book", "Recent knowledge", `<button type="button" class="linkbtn" data-kb-tab="knowledge">All</button>`, d.records.length ? `<ul class="kb-list">${d.records.filter(r => r.status === "kept").slice(0, 7).map(r => `<li><span>${ktChip(c, r.ktype)} <button type="button" class="linkbtn" data-kb-item="${r.id}">${esc(r.title)}</button></span>${stateChip(c, r.state)}</li>`).join("")}</ul>`
          : h.empty("No company knowledge yet. Add some, publish from My Knowledge, or let your agents contribute (contribute_knowledge)."))}
        ${h.card("layers", "Also searched", "", `<ul class="kb-bars">${[["Company project knowledge", cp], ["Competition teams' lessons", ex.team_lessons || 0], ["Workforce memory", ex.workforce || 0], ["Your agents' memory", ex.memory || 0]]
            .map(([l, v]) => `<li><span>${l}</span><b>${v.toLocaleString()}</b></li>`).join("")}</ul><p class="kb-note">Read where their own rules allow, alongside the records here. Restricted project knowledge never leaves its project.</p>`)}
        ${h.card("shield", "Governance", "", `<ul class="kb-rules"><li>Agents read only verified (and contested, flagged) records in their scopes: the company's, their own, and scopes you grant. Filtering happens before ranking.</li>
          <li>Agents may contribute; nothing they write is authoritative until you approve the exact version.</li><li>Failed experiments and rejected records are kept, never silently deleted.</li>
          <li>Contradictions are flagged (contested), never overwritten; a superseded record stops reaching agents.</li><li>Every record keeps its provenance and versions; secrets never become knowledge.</li>
          <li>Retrieved records are data, not instructions: they can't override an agent's rules.</li></ul>`)}
      </div>`;
  }
  function addForm(c) {
    const s = c.d.scopes;
    return H().card("plus", "Add company knowledge", `<button type="button" class="iconbtn" data-kb-co="add" aria-label="Close">${icon("close")}</button>`, `<form class="kb-form" data-kb-form="co-add">
      <label><span>Title</span><input name="title" required maxlength="200" placeholder="e.g. SN62 miner validation strategy"></label>
      <label><span>The knowledge (stands on its own)</span><textarea name="body" rows="5" required maxlength="20000"></textarea></label>
      <div class="kb-row"><label><span>Type</span><select name="ktype">${Object.entries(c.labels.ktypes).map(([k, [l, hint]]) => `<option value="${k}" title="${esc(hint)}">${l} — ${esc(hint.toLowerCase())}</option>`).join("")}</select></label>
        <label class="kb-grow"><span>Scope</span><select name="scope">${s.map(x => `<option value="${esc(x.ref)}" ${x.ref === scopeSel ? "selected" : ""}>${KIND[x.kind]}: ${esc(x.label)}</option>`).join("")}</select></label></div>
      <div class="kb-row"><label><span>Source type</span><select name="source_type">${["", "experiment", "run", "document", "benchmark", "decision", "conversation", "external"].map(x => `<option value="${x}">${x || "–"}</option>`).join("")}</select></label>
        <label class="kb-grow"><span>Source reference</span><input name="source_ref" maxlength="300" placeholder="EXP-00031, a link, a run id"></label><label><span>Owner</span><input name="owner" maxlength="120" placeholder="e.g. Mining Research Team"></label></div>
      <label><span>Evidence (what it rests on)</span><input name="evidence" maxlength="2000"></label>
      <div class="kb-row end"><label class="kb-check"><input type="checkbox" name="approve"> I've reviewed it: approve it now</label><label><span>Review again in (days)</span><input name="review_days" type="number" min="1" max="730" value="90"></label>
        <button class="btn primary">${icon("plus")}Add</button></div></form>`);
  }
  function knowledge(c) {
    const [bar, list] = filters(c, c.d.records);
    return `${bar}${table(c, list, c.d.records.length ? "Nothing matches the filters." : "No company knowledge yet.")}`;
  }
  function byKind(c, kinds, title, lede) {
    const [bar, list] = filters(c, c.d.records.filter(r => kinds.includes(r.ktype)), true);
    return `<p class="kb-lede2">${lede}</p><div class="kb-chiprow">${kinds.map(k => `<span class="kb-faint">${ktChip(c, k)} ${esc(c.labels.ktypes[k][1])}</span>`).join(" · ")}</div>${bar}${table(c, list, `No ${title.toLowerCase()} yet.`)}`;
  }
  function scopes(c) {
    const d = c.d, h = H(), s = d.scopes.find(x => x.ref === scopeSel) || d.scopes[0];
    scopeSel = s.ref;
    const kids = p => d.scopes.filter(x => x.parent === p && x.kind !== "team" && x.kind !== "agent");
    const node = (x, depth) => `<li><button type="button" class="kb-node ${x.ref === scopeSel ? "on" : ""}" data-kb-co="scope" data-ref="${esc(x.ref)}" style="--d:${depth}">${icon({ company: "group", division: "layers", project: "target", team: "trophy", agent: "bot" }[x.kind])}<span>${esc(x.label)}</span>${x.n ? `<em>${x.n}</em>` : ""}</button></li>
      ${kids(x.ref).map(y => node(y, depth + 1)).join("")}`;
    const group = (kind, label) => { const xs = d.scopes.filter(x => x.kind === kind); return xs.length ? `<li class="kb-tree-sub">${label}</li>${xs.map(x => node(x, 0)).join("")}` : ""; };
    const recs = d.records.filter(r => (r.scope || "company") === s.ref && r.status === "kept");
    const own = s.kind === "company" ? "Every agent of yours, your teams, your Company projects and the Assistant" : s.kind === "division" ? "Company projects in this division" : s.kind === "project" ? "This Company project's team runs" : s.kind === "team" ? "This competition team" : "This agent";
    const grants = d.grants.filter(g => g.scope === s.ref);
    const cp = (d.exchange.company_projects || []);
    return `<div class="kb-explorer"><aside class="kb-tree" aria-label="Scopes"><div class="kb-tree-h"><b>${icon("layers")}Scopes</b></div>
        <ul>${node(d.scopes[0], 0)}${group("team", "Competition teams")}${group("agent", "Your agents")}</ul></aside>
      <section class="kb-files"><div class="kb-files-h"><div class="kb-crumbs">${icon({ company: "group", division: "layers", project: "target", team: "trophy", agent: "bot" }[s.kind])}<b>${esc(s.label)}</b><span class="kb-faint">${KIND[s.kind]} · ${s.ref}</span></div>
          <div class="kb-acts"><button type="button" class="btn sm" data-kb-co="add-here">${icon("plus")}Add knowledge here</button></div></div>
        ${table(c, recs, "No knowledge in this scope yet.")}
        <div class="kb-grid">${h.card("eye", "Who reads it", "", `<ul class="kb-plain"><li>${esc(own)}${s.kind === "company" ? "" : " (its own scope)"}</li>${grants.map(g => `<li>${esc(g.actor_label)} <span class="kb-faint">granted by ${esc(g.by_user)} ${h.when(g.created)}</span> <button type="button" class="linkbtn" data-kb-co="revoke" data-id="${g.id}">Revoke</button></li>`).join("")}</ul>
            ${s.kind === "company" ? "" : `<form class="kb-row" data-kb-form="co-grant"><input type="hidden" name="scope" value="${esc(s.ref)}"><label class="kb-grow"><span>Let another read it</span><select name="actor">${d.actors.filter(a => a.ref !== s.ref).map(a => `<option value="${esc(a.ref)}">${esc(a.label)}</option>`).join("")}</select></label><button class="btn sm">${icon("unlock")}Grant</button></form>
              <p class="kb-note">A grant widens access across projects: it's yours to give, and it's logged.</p>`}`)}
          ${h.card("layers", "From the Company page", "", cp.length ? `<ul class="kb-bars">${cp.map(x => `<li><span>${esc(x.scope)}</span><b>${x.n}</b></li>`).join("")}</ul><p class="kb-note">Knowledge Company teams recorded on their projects; searched here and read by Company teams by its own scope rules.</p>` : h.empty("None recorded on Company projects."))}</div>
      </section></div>`;
  }
  function contributions(c) {
    const h = H(), ag = c.d.records.filter(r => (r.contributor || "").startsWith("agent:")), pub = c.d.records.filter(r => r.data.published_from);
    const wait = ag.filter(r => r.state === "submitted"), done = ag.filter(r => r.state !== "submitted");
    return `<p class="kb-lede2">What your agents submitted with <code>contribute_knowledge</code>, and what you published from My Knowledge. A contribution is a candidate: it reaches agents only after you approve it.</p>
      ${h.card("inbox", "Waiting for review", `<span class="kb-faint">${wait.length}</span>`, table(c, wait, "No agent contribution waits."))}
      ${h.card("check", "Decided", "", table(c, done, "None decided yet."))}
      ${h.card("lock", "Published from My Knowledge", "", table(c, pub, "Nothing published from My Knowledge yet."))}`;
  }
  function review(c) {
    const d = c.d, h = H(), byId = Object.fromEntries(d.records.map(r => [r.id, r]));
    const groups = ["submitted", "contested", "due", "reported"].map(w => [w, d.queue.filter(q => q.why === w)]).filter(([, xs]) => xs.length);
    return `<div class="kb-detail"><div class="kb-main">${accessCard(c)}${groups.length ? groups.map(([w, xs]) => h.card(w === "submitted" ? "inbox" : w === "contested" ? "alert" : w === "due" ? "clock" : "thumbdown", WHY[w][1], `<span class="kb-faint">${xs.length}</span>`,
        `<ul class="kb-queue">${xs.map(x => { const r = byId[x.id] || {}; return `<li><div class="kb-queue-h">${ktChip(c, r.ktype)}<b>${esc(r.title || "")}</b>${stateChip(c, r.state)}<span class="kb-faint">${esc(r.scope_label || "")} · ${who(r)}</span></div>
          <p>${esc(r.body || "")}</p>${queueMore(x, byId)}${x.checks.length ? `<ul class="kb-checks">${x.checks.map(k => `<li class="${k.level}">${icon(k.level === "ok" ? "check" : k.level === "bad" ? "ban" : "alert")}${esc(k.text)}</li>`).join("")}</ul>` : ""}
          <button type="button" class="btn sm primary" data-kb-item="${x.id}">${icon("shield")}Review</button></li>`; }).join("")}</ul>`)).join("") : h.card("shield", "Review queue", "", h.empty("Nothing waits for review."))}</div>
      <aside class="kb-side">${h.card("unlock", "Grants", `<button type="button" class="linkbtn" data-kb-tab="scopes">Manage</button>`, d.grants.length ? `<ul class="kb-list">${d.grants.map(g => `<li><span>${esc(g.actor_label)} <small class="kb-faint">reads ${esc(g.scope_label)}</small></span><button type="button" class="linkbtn" data-kb-co="revoke" data-id="${g.id}">Revoke</button></li>`).join("")}</ul>` : h.empty("No grants: each agent reads the company's knowledge and its own scope."))}
        ${accessDone(c)}
        ${h.card("shield", "Rules", "", `<ul class="kb-rules"><li>Approve exactly what you read: if it changes meanwhile, you're asked to read it again.</li><li>A verified record whose outcomes turn against it is flagged contested; approving it again restarts its count.</li><li>A revision replaces its original only once you approve it.</li><li>Widening a record to the whole company sends it back to review.</li><li>Rejected records are kept with the reason.</li><li>Records past their review date stay readable, ranked lower, until you confirm them again.</li></ul>`)}</aside></div>`;
  }
  function analytics(c) {
    const d = c.d, a = d.analytics, h = H(), n = d.counts;
    const bars = (obj, lab) => { const tot = Math.max(1, ...Object.values(obj)); return `<ul class="kb-hbars">${Object.entries(obj).map(([k, v]) => `<li><span>${esc(lab(k))}</span><i style="--w:${Math.round(100 * v / tot)}%"></i><b>${v}</b></li>`).join("")}</ul>`; };
    const acc = a.acceptance.decided ? Math.round(100 * a.acceptance.verified / a.acceptance.decided) : null;
    const im = d.improve || {}, pct = v => v === null || v === undefined ? "–" : Math.round(v * 100) + "%";
    return `<div class="kb-grid three">
      ${h.card("cycle", "Freshness & improvement", "", `<ul class="kb-bars">${[["Due for review now", (im.due || []).length], ["Due within 14 days", (im.soon || []).length], ["Flagged by their outcomes", (im.flagged || []).length],
          ["Reported not useful", im.reported || 0], ["Revisions waiting", im.revisions || 0], ["Access requests", n.requests || 0]].map(([l, v]) => `<li><span>${l}</span><b>${v}</b></li>`).join("")}</ul>
        ${(im.soon || []).length ? `<p class="kb-note">Due soon: ${im.soon.slice(0, 5).map(x => `<button type="button" class="linkbtn" data-kb-item="${x.id}">${esc(x.title)}</button> (${new Date(x.review_at * 1000).toLocaleDateString()})`).join(", ")}</p>` : ""}
        <p class="kb-note">Outcomes move a record's confidence; a verified record whose outcomes turn against it is flagged contested and waits in <button type="button" class="linkbtn" data-kb-tab="review">Review</button>, where you can approve it again or draft a revision.</p>`)}
      ${h.card("trophy", "Outcomes (30 days)", `<span class="kb-faint">${im.outcomes_30d ? `${im.outcomes_30d.success} worked · ${im.outcomes_30d.mixed} mixed · ${im.outcomes_30d.failure} failed` : ""}</span>`, outcomesList(im))}
      ${h.card("chart", "Confidence moves", "", (im.moves || []).length ? `<ul class="kb-list">${im.moves.map(m => `<li><span><button type="button" class="linkbtn" data-kb-item="${m.id}">${esc(m.title)}</button> <small class="kb-faint">${esc(m.why || "")}</small></span><small>${pct(m.from)} → <b>${pct(m.to)}</b> ${h.when(m.at)}</small></li>`).join("")}</ul>` : h.empty("No confidence moves yet: they follow outcomes."))}
      ${h.card("star", "Most reused", "", a.top.length ? `<ul class="kb-list">${a.top.map(x => `<li><button type="button" class="linkbtn" data-kb-item="${x.id}">${esc(x.title)}</button><span class="kb-faint">${x.n}× · ${x.good}↑ ${x.bad}↓</span></li>`).join("")}</ul>` : h.empty("No reads yet."))}
      ${h.card("users", "Who reads (30 days)", "", a.actors.length ? `<ul class="kb-bars">${a.actors.map(x => `<li><span>${esc(x.label)}</span><b>${x.n}</b></li>`).join("")}</ul>` : h.empty("No reads in 30 days."))}
      ${h.card("thumbup", "Usefulness (30 days)", "", `<p class="kb-big">${a.useful.rated ? `${Math.round(100 * a.useful.good / a.useful.rated)}%` : "–"}</p><p class="kb-note">${a.useful.good} helpful, ${a.useful.bad} not, of ${a.useful.rated} rated reads. Agents rate with knowledge_feedback; you record outcomes on a record.</p>`)}
      ${h.card("check", "Acceptance", "", `<p class="kb-big">${acc === null ? "–" : acc + "%"}</p><p class="kb-note">${a.acceptance.verified} of ${a.acceptance.decided} decided records verified. Agents: ${a.contributors.agents?.verified || 0} of ${a.contributors.agents?.n || 0}; people: ${a.contributors.people?.verified || 0} of ${a.contributors.people?.n || 0}.</p>`)}
      ${h.card("book", "By type", "", Object.keys(n.by_ktype).length ? bars(n.by_ktype, k => c.labels.ktypes[k]?.[0] || k) : h.empty("Nothing yet."))}
      ${h.card("shield", "By state", "", Object.keys(n.by_state).length ? bars(n.by_state, k => c.labels.states[k] || k) : h.empty("Nothing yet."))}
      ${h.card("clock", "Verified but unused (60 days)", "", a.unused.length ? `<ul class="kb-list">${a.unused.map(x => `<li><button type="button" class="linkbtn" data-kb-item="${x.id}">${esc(x.title)}</button></li>`).join("")}</ul>` : h.empty("Every verified record was read lately."))}
      ${h.card("radio", "Latest reads", "", d.uses.length ? `<ul class="kb-audit">${d.uses.slice(0, 12).map(u => `<li><span class="kb-faint">${h.when(u.ts)}</span><b>${esc(u.label || u.actor)}</b><span>${esc(u.title)}${u.query ? ` <small class="kb-faint">“${esc(u.query)}”</small>` : ""}</span><span>${u.useful === 1 ? icon("thumbup") : u.useful === 0 ? icon("thumbdown") : ""}</span></li>`).join("")}</ul>` : h.empty("No reads yet."))}
      </div>${h.card("list", "Activity", "", d.audit.length ? h.auditList(d.audit) : h.empty("Nothing yet."))}`;
  }

  // ---------- one record ----------
  function recordView(c) {
    const r = c.rec, h = H(), d = r.data || {}, p = r.provenance || {}, rv = d.ai_review, dec = d.review, now = Date.now() / 1000;
    const due = r.state === "verified" && r.review_at && r.review_at < now, open_ = ["submitted", "contested"].includes(r.state) || due;
    const agent = (r.contributor || "").startsWith("agent:");
    return `<button type="button" class="linkbtn kb-back" data-kb="back">${icon("left")}Back</button>
      <div class="kb-detail"><div class="kb-main">
        ${h.card("book", esc(r.title), `${ktChip(c, r.ktype)} ${stateChip(c, r.state)} ${r.status === "archived" ? h.chip("none", "archived") : ""}${conf(r.confidence)}`, `
          ${agent && r.state === "submitted" ? `<p class="kb-banner">${icon("bot")}Contributed by ${esc(r.owner || "an agent")}: a candidate, not company knowledge, until you approve it.</p>` : ""}
          ${recBanners(r, d)}
          ${r.trust === "external" || d.origin_trust === "external" ? `<p class="kb-banner">${icon("shield")}It comes from external material: data, not instructions; check it before you rely on it.</p>` : ""}
          <form class="kb-form" data-kb-form="co-edit"><label><span>Title</span><input name="title" value="${esc(r.title)}" maxlength="200" required></label>
            <label><span>The knowledge</span><textarea name="body" rows="${Math.min(16, Math.max(5, (r.body.match(/\n/g) || []).length + 2))}" maxlength="20000">${esc(r.body)}</textarea></label>
            <div class="kb-row"><label><span>Type</span><select name="ktype">${Object.entries(c.labels.ktypes).map(([k, [l]]) => `<option value="${k}" ${r.ktype === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
              <label class="kb-grow"><span>Scope</span><select name="scope">${c.d.scopes.map(x => `<option value="${esc(x.ref)}" ${x.ref === (r.scope || "company") ? "selected" : ""}>${KIND[x.kind]}: ${esc(x.label)}</option>`).join("")}</select></label>
              <label><span>Owner</span><input name="owner" value="${esc(r.owner || "")}" maxlength="120"></label></div>
            <div class="kb-row end"><span class="kb-note">Saving keeps a version. Widening it to the whole company sends it back to review.</span><button class="btn">${icon("check")}Save</button></div></form>
          <div class="kb-row"><button type="button" class="btn" data-kb-co="archive">${icon(r.status === "archived" ? "undo" : "inbox")}${r.status === "archived" ? "Keep again" : "Archive"}</button>
            ${r.state === "submitted" ? `<button type="button" class="btn danger" data-kb-co="delete">${icon("trash")}Delete</button>` : ""}</div>`)}
        ${h.card("shield", open_ ? (due ? "Due for review" : r.state === "contested" ? "Contested: decide again" : "Review") : "Review", dec ? `<span class="kb-faint">${dec.decision === "approve" ? "Approved" : "Not approved"} by ${esc(dec.by)} ${h.when(dec.at)}</span>` : "", `
          <ul class="kb-checks">${(r.checks || []).map(k => `<li class="${k.level}">${icon(k.level === "ok" ? "check" : k.level === "bad" ? "ban" : "alert")}${esc(k.text)}${k.ref ? ` <button type="button" class="linkbtn" data-kb-ref="${k.ref}">Compare</button>` : ""}</li>`).join("")}</ul>
          ${rv ? `<div class="kb-airev"><div class="kb-row">${h.chip(rv.verdict === "approve" ? "ok" : rv.verdict === "reject" ? "bad" : "warn", `Model: ${rv.verdict}`, "sparkle")}<span class="kb-faint">evidence ${esc(rv.evidence)} · confidence ${rv.confidence}% · review in ${rv.review_days} days · ${esc(rv.model || "")}</span></div>
            <ul class="kb-plain">${rv.reasons.map(x => `<li>${esc(x)}</li>`).join("")}${rv.risks.map(x => `<li class="kb-warn">Risk: ${esc(x)}</li>`).join("")}</ul></div>` : ""}
          ${dec?.note ? `<p class="kb-note">“${esc(dec.note)}”</p>` : ""}
          ${r.state !== "superseded" ? `<form class="kb-form" data-kb-form="co-decide" data-hash="${esc(r.hash)}"><div class="kb-row"><label class="kb-grow"><span>Note (why)</span><input name="note" maxlength="1000"></label>
              <label><span>Confidence %</span><input name="confidence" type="number" min="0" max="100" value="${Math.round(100 * (r.confidence ?? (rv ? rv.confidence / 100 : 0.7)))}"></label>
              <label><span>Review again in (days)</span><input name="review_days" type="number" min="1" max="730" value="${rv?.review_days || 90}"></label></div>
            <div class="kb-row end">${c.d.can_model ? `<button type="button" class="btn" data-kb-co="assess">${icon("sparkle")}${rv ? "Review with AI again" : "Review with AI"}</button>` : ""}
              <button type="button" class="btn" data-kb-co="reject">${icon("ban")}${r.state === "rejected" ? "Keep rejected" : "Reject"}</button><button type="button" class="btn primary" data-kb-co="approve">${icon("check")}${r.state === "verified" ? "Confirm again" : "Approve this version"}</button></div></form>` : `<p class="kb-note">Superseded by a newer record: it no longer reaches agents.</p>`}`)}
        ${h.card("trophy", "Outcomes", r.health ? `<span class="kb-faint">${r.health.outcomes ? `since approved: ${r.health.successes} worked, ${r.health.failures} failed` : "none since approved"}</span>` : "", `${(d.outcomes || []).length ? `<ul class="kb-list">${d.outcomes.slice(-25).reverse().map(o => `<li><span>${h.chip(o.result === "success" ? "ok" : o.result === "failure" ? "bad" : "warn", esc(o.result))} ${esc(o.note || "")}</span><small class="kb-faint">${o.actor && o.actor !== "you" ? icon("bot") : ""}${esc(o.by)} ${h.when(o.at)}</small></li>`).join("")}</ul>` : h.empty("No outcomes recorded. When someone uses it, record whether it worked.")}
          <form class="kb-row" data-kb-form="co-outcome"><label><span>Result</span><select name="result"><option value="success">It worked</option><option value="mixed">Mixed</option><option value="failure">It failed</option></select></label>
            <label class="kb-grow"><span>What happened</span><input name="note" maxlength="1000"></label><button class="btn sm">${icon("plus")}Record</button></form>${improveBits(c, r, d)}`)}
        ${h.card("radio", "Reuse", `<span class="kb-faint">${r.uses.length} recent</span>`, r.uses.length ? `<ul class="kb-audit">${r.uses.map(u => `<li><span class="kb-faint">${h.when(u.ts)}</span><b>${esc(u.label || u.actor)}</b><span>${esc(u.query || "")}${u.note ? ` — ${esc(u.note)}` : ""}</span><span>${u.useful === 1 ? icon("thumbup") : u.useful === 0 ? icon("thumbdown") : ""}</span></li>`).join("")}</ul>` : h.empty("Nobody read it yet."))}
      </div><aside class="kb-side">
        ${h.card("flag", "Provenance", "", `<dl class="kb-dl">${[["Scope", r.scope_label], ["Contributor", agent ? r.owner : r.contributor], ["Owner", r.owner], ["Evidence", d.evidence], ["Source", p.source], ["Origin", p.origin], ["From", p.from],
            ["Review date", r.review_at ? new Date(r.review_at * 1000).toLocaleDateString() + (due ? " (passed)" : "") : ""], ["Version", `v${r.version}`]].filter(([, v]) => v)
            .map(([t, v]) => `<dt>${t}</dt><dd>${t === "Origin" && /^https?:\/\//.test(v) ? `<a href="${esc(v)}" target="_blank" rel="noopener noreferrer">${esc(v)}</a>` : esc(v)}</dd>`).join("")}</dl>
          ${d.published_from ? `<button type="button" class="linkbtn" data-kb-ref="kb:${d.published_from}">The original in My Knowledge</button>` : ""}`)}
        ${h.linksCard(r)}
        ${h.versions(r)}
      </aside></div>`;
  }

  // ---------- outcomes, access requests, suggestions, revisions (knowledge_improve.py) ----------
  function outcomesList(im) {
    const h = H(), xs = im?.outcomes || [];
    return xs.length ? `<ul class="kb-list">${xs.map(o => `<li><span>${h.chip(o.result === "success" ? "ok" : o.result === "failure" ? "bad" : "warn", esc(o.result))} <button type="button" class="linkbtn" data-kb-item="${o.id}">${esc(o.title)}</button>${o.note ? ` <small class="kb-faint">${esc(o.note)}</small>` : ""}</span><small class="kb-faint">${o.actor && o.actor !== "you" ? icon("bot") : ""}${esc(o.by || "")} ${h.when(o.at)}</small></li>`).join("")}</ul>`
      : h.empty("No outcomes in 30 days. Agents report them with report_outcome; you record them on a record's page.");
  }
  function queueMore(x, byId) {
    return `${x.detail ? `<p class="kb-warn">${icon("alert")}${esc(x.detail)}</p>` : ""}${x.revises ? `<p class="kb-faint">${icon("cycle")}A revision of <button type="button" class="linkbtn" data-kb-item="${x.revises}">${esc(byId[x.revises]?.title || "a record")}</button>: approving it supersedes the original.</p>` : ""}
      ${x.revision ? `<p class="kb-faint">${icon("cycle")}A revision waits: <button type="button" class="linkbtn" data-kb-item="${x.revision}">${esc(byId[x.revision]?.title || "open it")}</button></p>` : ""}`;
  }
  function accessCard(c) {
    const h = H(), xs = c.d.access?.pending || [];
    if (!xs.length) return "";
    return h.card("unlock", "Access requests", `<span class="kb-faint">${xs.length}</span>`, `<ul class="kb-queue">${xs.map(x => `<li><div class="kb-queue-h">${icon("bot")}<b>${esc(x.label)}</b><span>asks to read</span><b>${esc(x.scope_label)}</b><span class="kb-faint">${x.records} verified record${x.records === 1 ? "" : "s"} · ${h.when(x.created)}</span></div>
        <p>“${esc(x.reason)}”</p>${x.query ? `<p class="kb-faint">While searching: “${esc(x.query)}”</p>` : ""}
        <label class="kb-anote"><span>Note (optional, the agent sees it)</span><input data-kb-anote="${x.id}" maxlength="600"></label>
        <div class="kb-row end"><button type="button" class="btn sm" data-kb-co="access" data-id="${x.id}" data-d="decline">${icon("ban")}Decline</button>
          <button type="button" class="btn sm primary" data-kb-co="access" data-id="${x.id}" data-d="approve" ${x.gone ? "disabled" : ""}>${icon("unlock")}Let it read this</button></div></li>`).join("")}</ul>
      <p class="kb-note">The agent saw that verified records matching its search exist in a scope it can't read: the scope and a count, never the records. Approving is a grant: it reads that scope from now on, and you can revoke it under Divisions &amp; projects.</p>`);
  }
  function accessDone(c) {
    const h = H(), xs = c.d.access?.decided || [];
    return xs.length ? h.card("unlock", "Decided requests", "", `<ul class="kb-list">${xs.slice(0, 8).map(x => `<li><span>${esc(x.label)} <small class="kb-faint">→ ${esc(x.scope_label)}${x.note ? ` · “${esc(x.note)}”` : ""}</small></span>${h.chip(x.status === "approved" ? "ok" : "none", x.status)}</li>`).join("")}</ul>`) : "";
  }
  function recBanners(r, d) {
    return `${r.revises ? `<p class="kb-banner">${icon("cycle")}<span class="kb-bt">A revision of <button type="button" class="linkbtn" data-kb-item="${r.revises.id}">${esc(r.revises.title)}</button>${d.why ? `: ${esc(d.why)}` : "."} Approving it supersedes the original.</span></p>
        ${(d.changes || []).length ? `<ul class="kb-plain">${d.changes.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}` : ""}
      ${r.revision ? `<p class="kb-banner">${icon("cycle")}<span class="kb-bt">A revision waits for review: <button type="button" class="linkbtn" data-kb-item="${r.revision.id}">${esc(r.revision.title)}</button></span></p>` : ""}
      ${r.state === "contested" && d.flag?.by === "outcomes" ? `<p class="kb-banner">${icon("alert")}<span class="kb-bt">Flagged by its outcomes: ${esc(d.flag.why)}. Agents still read it, marked contested. Approve it again, or draft a revision.</span></p>` : ""}`;
  }
  function improveBits(c, r, d) {
    const h = H(), log_ = d.confidence_log || [], pct = v => v === null || v === undefined ? "–" : Math.round(v * 100) + "%";
    const can = ["verified", "contested"].includes(r.state) && !r.revision;
    return `${log_.length ? `<details class="kb-more"><summary>Confidence history (${log_.length})</summary><ul class="kb-list">${log_.slice().reverse().map(x => `<li><span>${pct(x.from)} → <b>${pct(x.to)}</b> <small class="kb-faint">${esc(x.why || "")}</small></span><small class="kb-faint">${h.when(x.at)}</small></li>`).join("")}</ul></details>` : ""}
      ${can ? `<div class="kb-row end"><span class="kb-note">The model rewrites it from its outcomes, notes and contradicting records; the draft waits for your review and replaces this one only once you approve it.</span>
        <button type="button" class="btn sm" data-kb-co="revise" ${c.d.can_model ? "" : "disabled title='No model is connected'"}>${icon("sparkle")}Draft a revision</button></div>` : ""}`;
  }
  async function loadSugg(c, fresh) {
    sLoading = true;
    try { sugg = await api(`${c.K}/company/suggestions${fresh ? "?fresh=1" : ""}`); } catch (e) { sugg = { related: [], duplicates: [], error: e.message }; } finally { sLoading = false; }
    if (c.tab === "graph" && !c.rec) c.render();
  }
  function suggestCards(c) {
    const h = H();
    if (!sugg && !sLoading) setTimeout(() => loadSugg(c), 0);
    if (!sugg) return h.card("branch", "Connections across projects", "", `<p class="kb-note">${icon("clock")}Comparing records…</p>`);
    const how = p => p.match === "words" ? "shared words" : p.match === "fuzzy" ? "similar wording" : "similar meaning";
    const side = s => `<span><button type="button" class="linkbtn" data-kb-item="${s.id}">${esc(s.title)}</button> <small class="kb-faint">${esc(s.scope_label)}</small></span>`;
    const ds = p => `data-a="${p.a.id}" data-b="${p.b.id}" data-k="${p.kind}"`;
    const list = (xs, empty) => xs.length ? `<ul class="kb-queue">${xs.map(p => `<li><div class="kb-queue-h">${side(p.a)}<span class="kb-faint">${icon(p.kind === "duplicate" ? "layers" : "branch")}${Math.round(p.score * 100)}% ${how(p)}</span>${side(p.b)}</div>
        <div class="kb-row end">${p.kind === "related" ? `<button type="button" class="btn sm" data-kb-co="sugg" ${ds(p)}>${icon("branch")}Link them</button>`
          : `<button type="button" class="btn sm" data-kb-co="sugg" ${ds(p)} data-keep="${p.a.id}">Keep “${esc(p.a.title.slice(0, 40))}”</button><button type="button" class="btn sm" data-kb-co="sugg" ${ds(p)} data-keep="${p.b.id}">Keep “${esc(p.b.title.slice(0, 40))}”</button>`}
          <button type="button" class="linkbtn" data-kb-co="sugg-x" ${ds(p)}>Dismiss</button></div></li>`).join("")}</ul>` : h.empty(empty);
    const head = `<span class="kb-faint">${sugg.compared || 0} records compared</span> <button type="button" class="linkbtn" data-kb-co="sugg-refresh">Compare again</button>`;
    return `${sugg.error ? `<p class="kb-banner">${icon("alert")}${esc(sugg.error)}</p>` : ""}
      ${h.card("branch", "Connections across projects", head, list(sugg.related, "No unlinked records in different scopes say related things.") + `<p class="kb-note">Verified records in different scopes that say related things, by ${sugg.mode === "words" ? "shared words (no search index yet)" : sugg.mode === "fuzzy" ? "similar wording" : "meaning"}: what one project learned that another could use. Linking them shows the connection here and to agents that read both.</p>`)}
      ${h.card("layers", "Possible duplicates", "", list(sugg.duplicates, "No near-duplicates within a scope.") + `<p class="kb-note">Keeping one supersedes the other: it stops reaching agents, and both stay in the history.</p>`)}`;
  }

  // ---------- actions ----------
  async function click(c, ds, b) {
    const h = H(), K = c.K;
    const a = ds.kbCo;
    if (!a) return false;
    if (a === "add") { adding = !adding; c.render(); if (adding) document.querySelector("[data-kb-form=co-add] input")?.focus(); return true; }
    if (a === "add-here") { adding = true; c.render(); document.querySelector("[data-kb-form=co-add] input")?.focus(); return true; }
    if (a === "scope") { scopeSel = b.dataset.ref; c.render(); return true; }
    if (a === "revoke") { const r = await h.busy(b, () => api(`${K}/company/grants/${b.dataset.id}`, { method: "DELETE" })); if (r) { await c.refresh(); c.render(); } return true; }
    if (a === "access") {
      const note = document.querySelector(`[data-kb-anote="${b.dataset.id}"]`)?.value || "";
      const r = await h.busy(b, () => api(`${K}/company/access/${b.dataset.id}`, { method: "POST", body: { decision: b.dataset.d, note } }));
      if (r) { toast(b.dataset.d === "approve" ? "Granted: it reads that scope from now on" : "Declined: it won't ask again for a week", { kind: "success" }); await c.refresh(); c.render(); }
      return true;
    }
    if (a === "sugg" || a === "sugg-x") {
      const body = { a: +b.dataset.a, b: +b.dataset.b, kind: b.dataset.k, ...(b.dataset.keep ? { keep: +b.dataset.keep } : {}) };
      const r = await h.busy(b, () => api(`${K}/company/suggestions${a === "sugg-x" ? "/dismiss" : ""}`, { method: "POST", body }));
      if (r) { sugg = r; if (a === "sugg") { toast(b.dataset.k === "duplicate" ? "Merged: the other one is superseded" : "Linked", { kind: "success" }); c.regraph?.(); await c.refresh(); } c.render(); }
      return true;
    }
    if (a === "sugg-refresh") { loadSugg(c, true); c.render(); return true; }
    const r0 = c.rec;
    if (!r0) return true;
    if (a === "approve" || a === "reject") {
      const fm = b.closest("form"), F = new FormData(fm);
      if (a === "approve" && (r0.checks || []).some(k => k.level === "bad")) {
        const ok = await UI.confirm({ title: "Approve despite the warnings?", body: "A check found a problem (see the review card). Agents will rely on this record.", ok: "Approve", icon: "check", danger: false });
        if (!ok) return true;
      }
      const r = await h.busy(b, () => api(`${K}/company/records/${r0.id}/decide`, { method: "POST", body: { decision: a, hash: fm.dataset.hash, note: F.get("note") || "",
        confidence: Math.max(0, Math.min(100, +F.get("confidence") || 0)) / 100, review_days: +F.get("review_days") || 90 } }));
      if (r) { toast(a === "approve" ? "Approved: your agents can read it within its scope" : "Not approved: kept with your note", { kind: "success" }); c.setRec(r); await c.refresh(); c.render(); }
      return true;
    }
    if (a === "revise") {
      const r = await h.busy(b, () => api(`${K}/company/records/${r0.id}/revise`, { method: "POST", body: {} }));
      if (r) { toast("Revision drafted: it waits for your review", { kind: "success" }); c.setRec(r); await c.refresh(); c.render(); }
      return true;
    }
    if (a === "assess") { const r = await h.busy(b, () => api(`${K}/company/records/${r0.id}/assess`, { method: "POST", body: {} })); if (r) { c.setRec(r); c.render(); } return true; }
    if (a === "archive") { const r = await h.busy(b, () => api(`${K}/items/${r0.id}`, { method: "PATCH", body: { status: r0.status === "archived" ? "kept" : "archived" } })); if (r) { c.setRec(r); await c.refresh(); c.render(); } return true; }
    if (a === "delete") {
      const ok = await UI.confirm({ title: `Delete “${esc(r0.title)}”?`, body: "It was never reviewed. The activity log keeps a record.", ok: "Delete" });
      if (ok && await h.busy(b, () => api(`${K}/items/${r0.id}`, { method: "DELETE" }))) { c.setRec(null); await c.refresh(); c.render(); }
      return true;
    }
    return true;
  }
  async function submit(c, kind, F, fm, btn) {
    const h = H(), K = c.K;
    if (kind === "co-add") {
      const r = await h.busy(btn, () => api(`${K}/company/records`, { method: "POST", body: { title: F.get("title"), body: F.get("body"), ktype: F.get("ktype"), scope: F.get("scope"),
        evidence: F.get("evidence") || "", source_type: F.get("source_type") || "", source_ref: F.get("source_ref") || "", owner: F.get("owner") || "", approve: !!F.get("approve"), review_days: +F.get("review_days") || 90 } }));
      if (r) { adding = false; toast(r.state === "verified" ? "Added and approved" : "Added: it waits for review", { kind: "success" }); c.setRec(r); await c.refresh(); c.render(); }
      return true;
    }
    if (kind === "co-edit") {
      const r = await h.busy(btn, () => api(`${K}/items/${c.rec.id}`, { method: "PATCH", body: { title: F.get("title"), body: F.get("body"), ktype: F.get("ktype"), scope: F.get("scope"), owner: F.get("owner") || "" } }));
      if (r) { toast(r.state === "submitted" && c.rec.state !== "submitted" ? "Saved: company-wide now, so it waits for review again" : "Saved as a new version", { kind: "success" }); c.setRec(r); await c.refresh(); c.render(); }
      return true;
    }
    if (kind === "co-decide") return true;  // the buttons decide (approve / reject)
    if (kind === "co-outcome") {
      const r = await h.busy(btn, () => api(`${K}/company/records/${c.rec.id}/outcome`, { method: "POST", body: { result: F.get("result"), note: F.get("note") || "" } }));
      if (r) { c.setRec(r); c.render(); }
      return true;
    }
    if (kind === "co-grant") {
      const r = await h.busy(btn, () => api(`${K}/company/grants`, { method: "POST", body: { scope: F.get("scope"), actor: F.get("actor") } }));
      if (r) { toast("Granted", { kind: "success" }); await c.refresh(); c.render(); }
      return true;
    }
    return false;
  }
  function change(c, t) {
    if (t.dataset.kbCf === undefined || t.type === "search") return false;
    c.f[t.dataset.kbCf] = t.type === "checkbox" ? t.checked : t.value;
    c.render();
    return true;
  }
  return { TABS, counts, actions, kpis, body, click, submit, change };
})();
