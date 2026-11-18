/* Competition teams → Import competitions (mining_sources.py), a dialog with four tabs:
   - Review: every imported competition waiting for the user. Each shows its fields with how each was found (from the source's
     own data, read from the page by the model with its quote, from a file, typed by the user), the checks, possible duplicates
     side by side with the team, changes a source found for an existing team, and on request an AI assessment (an estimate).
     The user edits, approves (a new team on a campaign of the competition's subnet, autopilot off; or an update to an existing
     team, field by field), saves it for later, rejects or deletes it.
   - Import: a URL (the adapter is picked from the address), JSON (pasted or a file), CSV (columns mapped to fields first), or
     the New competition form for typing one in.
   - Sources: what's checked on a schedule (Ridges, web pages, GitHub repositories, JSON feeds, a subnet's on-chain competitions).
   - History: every import, edit and decision. */
const MiningSources = (() => {
  const I = "/api/mining/work/intake";
  const STATUS = { extracting: ["run", "Reading…"], ready: ["warn", "To review"], draft: ["none", "Saved for later"], failed: ["bad", "Failed"],
    approved: ["ok", "Approved"], rejected: ["off", "Rejected"] };
  const VERDICT = { pass: ["ok", "Checks pass"], warning: ["warn", "Needs a look"], fail: ["bad", "Fails a check"] };
  const HOW = { source: ["ok", "From the source"], ai: ["acc", "Read by AI"], user: ["none", "Typed by you"], file: ["ok", "From the file"] };
  const LEVEL = { "very high": "bad", high: "warn", medium: "none" };
  const ORIGIN = { url: "URL", json: "JSON", csv: "CSV", auto: "Source" };
  const KIND_ICON = { ridges: "trophy", page: "globe", github: "github", json: "code", bittensor: "layers" };
  const LOG_ICON = { import: "download", extract: "sparkle", edit: "edit", assess: "sparkle", approved: "check", rejected: "ban", draft: "pin", ready: "inbox",
    source: "link", sync: "cycle", error: "alert" };
  const TEAM_LABEL = { name: "Name", number: "Number", status: "Status", starts: "Starts", ends: "Ends", link: "Page", description: "Description", share: "Emission share" };
  let dlg = null, home = null, tab = "queue", sel = null, cur = null, failed = "", timer = null, editing = false, rejecting = false, csv = null, hist = null, waiting = 0;
  let dirty = false, shown = "";  // a form in the dialog has input the user hasn't sent: background refreshes don't redraw over it
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;
  const x = `<button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>`;
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const label = f => f.name || f.url || "Unnamed competition";
  const show = v => v == null || v === "" || (Array.isArray(v) && !v.length) ? `<span class="faint">Unknown</span>`
    : Array.isArray(v) ? v.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>`).join("<br>")
    : typeof v === "string" && /^https?:\/\//.test(v) ? `<a href="${esc(v)}" target="_blank" rel="noopener noreferrer">${esc(v)}</a>` : esc(String(v));
  const fieldShow = (k, v) => k === "share" && v != null ? `${fmtNum(v * 100, 1)}%` : k === "netuid" && v != null ? `SN${v}` : show(v);
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- opening and loading ----------
  function open(t) {
    if (t) tab = t;
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "cin-dlg"; document.body.append(dlg);
      dlg.addEventListener("click", click); dlg.addEventListener("change", change); dlg.addEventListener("submit", submit);
      dlg.addEventListener("input", e => { if (e.target.closest("form")) dirty = true; });
      dlg.addEventListener("close", () => { clearTimeout(timer); MiningWork.reload?.(); });
    }
    dlg.className = "modal mw-dlg wide cin-dlg";
    render(); if (!dlg.open) dlg.showModal();
    load();
  }
  async function load(quiet) {
    try { set(await api(I), quiet); failed = ""; } catch (e) { failed = e.message; if (!quiet) render(); }
    if (tab === "history" && !quiet) loadHistory();
  }
  function set(h, quiet) {
    home = h; waiting = h.waiting; badge();
    if (quiet && (dirty || editing || rejecting || csv)) {  // keep what the user is typing; only the counts move
      $$(".cin-tab .hq-n.alert", dlg).forEach(n => { n.textContent = h.waiting || ""; });
      return poll();
    }
    if (sel && !h.queue.some(c => c.id === sel) && cur?.status !== "approved" && cur?.status !== "rejected") { sel = null; cur = null; }
    if (!sel && h.queue.length && matchMedia("(min-width: 900px)").matches) pick(h.queue.find(c => c.status !== "draft")?.id ?? h.queue[0].id, false);
    else if (sel && cur && h.queue.find(c => c.id === sel)?.updated !== cur.updated) pick(sel, false);
    render(); poll();
  }
  function poll() {
    clearTimeout(timer);
    if (!dlg?.open || !home) return;
    const live = home.queue.some(c => c.status === "extracting") || home.sources.some(s => s.running);
    timer = setTimeout(() => { if (dlg?.open && document.visibilityState === "visible") load(true); else poll(); }, live ? 1500 : 15000);
  }
  async function pick(id, draw = true) {
    sel = id; editing = false; rejecting = false;
    try { cur = (await api(`${I}/candidates/${id}`)).candidate; } catch (e) { err(e); cur = null; }
    if (draw || !dirty) render();
  }
  async function loadHistory() {
    try { hist = await api(`${I}/history`); } catch (e) { err(e); }
    if (tab === "history") render();
  }
  async function peek() {  // the waiting count, for the buttons that open this
    try { waiting = (await api(`${I}/count`)).waiting; badge(); } catch { /* not signed in, or no My subnets */ }
  }
  function badge() {
    $$(".cin-badge").forEach(s => { s.textContent = waiting || ""; s.hidden = !waiting; });
  }
  const count = () => waiting;

  // ---------- drawing ----------
  function render() {
    if (!dlg) return;
    const q = home?.queue || [];
    const tabs = [["queue", "inbox", "Review", home ? home.waiting : 0], ["import", "download", "Import"], ["sources", "link", "Sources", home?.sources.length || 0], ["history", "clock", "History"]];
    const body = !home ? (failed ? `<div class="empty">${esc(failed)}</div>` : Loading.line("Opening the import center…"))
      : tab === "queue" ? queue(q) : tab === "import" ? importer() : tab === "sources" ? sources() : history();
    const at = `${tab}:${tab === "queue" ? sel : ""}`, keep = at === shown ? dlg.querySelector(".cin-body")?.scrollTop : 0;
    shown = at; dirty = false;
    dlg.innerHTML = `<div class="hq-dlg-in cin">${x}
      <header class="cin-head"><h3>${icon("download")} Import competitions</h3>
        <p class="faint small">Competitions found automatically or imported by hand wait here until you approve them. Approving makes a team (autopilot off); nothing starts, deploys or spends by itself.</p>
        <nav class="cin-tabs" role="tablist">${tabs.map(([k, ic, t, n]) => `<button type="button" role="tab" class="cin-tab ${tab === k ? "on" : ""}" aria-selected="${tab === k}" data-cintab="${k}">${icon(ic)}${t}${n ? `<span class="hq-n ${k === "queue" ? "alert" : ""}">${n}</span>` : ""}</button>`).join("")}</nav></header>
      <div class="cin-body">${body}</div></div>`;
    $$("time[data-ts]", dlg).forEach(t => { t.textContent = ago(+t.dataset.ts); });
    if (keep) { const b = dlg.querySelector(".cin-body"); if (b) b.scrollTop = keep; }
  }

  // the review queue
  function queue(q) {
    if (!q.length) return `<div class="cin-empty"><span class="av c-teal" aria-hidden="true">${icon("inbox")}</span><div><b>Nothing to review</b>
        <p class="faint">Import a competition from its page, a JSON or CSV file, or follow a source and new competitions show up here.</p>
        <div class="row"><button type="button" class="btn primary sm" data-cintab="import">${icon("download")}Import</button>
          <button type="button" class="btn sm" data-cintab="sources">${icon("link")}Follow a source</button></div></div></div>`;
    const item = c => {
      const f = c.fields, top = c.dups.find(d => d.type === "team");
      return `<li><button type="button" class="cin-item ${c.id === sel ? "on" : ""}" data-cinpick="${c.id}" aria-current="${c.id === sel}">
        <span class="cin-item-t"><b>${esc(label(f))}</b><span class="faint small">${[f.netuid != null ? `SN${f.netuid}` : "", f.platform, ORIGIN[c.origin] || c.origin, c.created ? `<time data-ts="${c.created}"></time>` : ""].filter(Boolean).join(" · ")}</span></span>
        <span class="cin-item-c">${c.status === "ready" ? (c.kind === "update" ? chip(["acc", "Update"]) : c.verdict ? chip(VERDICT[c.verdict]) : "") : chip(STATUS[c.status])}
          ${top ? `<span class="hq-chip t-${LEVEL[top.level]}" title="${esc(top.why)}">${icon("copy")}Duplicate?</span>` : ""}</span></button></li>`;
    };
    return `<div class="cin-split ${sel ? "has-sel" : ""}"><ul class="cin-list" aria-label="Imported competitions">${q.map(item).join("")}</ul>
      <section class="cin-detail" aria-live="polite">${sel && cur ? detail(cur) : `<div class="empty small">Pick a competition to review it.</div>`}</section></div>`;
  }

  function detail(c) {
    const f = c.fields, back = `<button type="button" class="linkbtn cin-back" data-cinback>${icon("left")}All imports</button>`;
    if (c.status === "extracting") return `${back}<div class="cin-reading">${Loading.line(`Reading ${esc(f.url || "the source")}…`)}<p class="faint small">The page is fetched, its text read, and the competition's details pulled out with the sentence each came from.</p></div>`;
    const head = `<header class="cin-dhead"><div><h4>${esc(label(f))}</h4>
        <p class="faint small">${[chip(STATUS[c.status]), c.kind === "update" ? chip(["acc", "Update for an existing team"]) : "", c.verdict && c.status !== "failed" ? chip(VERDICT[c.verdict]) : "",
          c.confidence != null && Object.values(c.evidence).some(e => e.how === "ai") ? `<span>Extraction confidence ${fmtNum(c.confidence * 100, 0)}%</span>` : "",
          c.source ? `<span>${icon(KIND_ICON[c.source.kind] || "link")}${esc(c.source.label)}</span>` : `<span>Imported by hand (${ORIGIN[c.origin] || c.origin})</span>`].filter(Boolean).join(" ")}</p></div></header>`;
    if (c.status === "failed") return `${back}${head}<p class="mh-err">${icon("alert")}${esc(c.error || "It failed.")}</p>
      <div class="row">${f.url ? `<button type="button" class="btn sm" data-cinact="retry">${icon("cycle")}Try again</button>` : ""}<button type="button" class="btn sm" data-cinact="edit">${icon("edit")}Fill it in by hand</button>
        <button type="button" class="btn sm mw-danger" data-cinact="delete">${icon("trash")}Delete</button></div>${editing ? editForm(c) : ""}`;
    const decided = ["approved", "rejected"].includes(c.status);
    return `${back}${head}${checks(c)}${c.kind === "update" ? changes(c) : ""}${dups(c)}
      ${editing ? editForm(c) : fields(c)}
      ${assessment(c, decided)}
      ${decided ? outcome(c) : decide(c)}
      ${c.raw ? `<details class="cin-raw"><summary>${icon("doc")}The source text the model read <span class="faint">(${fmtNum(c.raw.length, 0)} characters, data only)</span></summary><pre>${esc(c.raw.slice(0, 20000))}</pre></details>` : ""}
      ${c.history?.length ? `<details class="cin-raw"><summary>${icon("clock")}History</summary><ul class="cin-log">${c.history.map(logLine).join("")}</ul></details>` : ""}`;
  }
  function checks(c) {
    const rows = c.checks.filter(k => k.level !== "info"), info = c.checks.filter(k => k.level === "info");
    if (!rows.length && !info.length) return `<p class="cin-ok">${icon("check")}Every check passes.</p>`;
    return `<ul class="cin-checks">${rows.map(k => `<li class="cin-${k.level}">${icon(k.level === "fail" ? "ban" : "alert")}<span>${esc(k.text)}</span></li>`).join("")}
      ${info.map(k => `<li class="cin-info">${icon("info")}<span>${esc(k.text)}</span></li>`).join("")}</ul>`;
  }
  function changes(c) {
    const ch = Object.entries(c.changes || {});
    if (!ch.length) return "";
    const team = home.teams.find(t => t.id === c.comp_id);
    return `<div class="cin-box"><h5>${icon("cycle")}The source changed ${team ? esc(team.label) : "a team"}</h5>
      <table class="cin-cmp"><thead><tr><th>Field</th><th>The team has</th><th>The source says</th></tr></thead>
      <tbody>${ch.map(([k, [a, b]]) => `<tr><th scope="row">${TEAM_LABEL[k] || k}</th><td>${fieldShow(k, a)}</td><td class="cin-new">${fieldShow(k, b)}</td></tr>`).join("")}</tbody></table>
      <p class="faint small">Nothing changes on the team until you approve it below, field by field.</p></div>`;
  }
  function dups(c) {
    if (!c.dups.length || c.kind === "update") return "";
    const f = c.fields, team = c.dups.find(d => d.type === "team");
    const val = (k, v) => k === "number" ? (v ?? "") : v;
    const cmp = team ? `<table class="cin-cmp"><thead><tr><th>Field</th><th>This import</th><th>${esc(team.label)}</th></tr></thead><tbody>
        ${Object.entries(home.team_fields).map(([col, fld]) => { const a = col === "number" ? f.external_id : f[fld], b = team.fields[col];
          const same = String(val(col, a) ?? "") === String(b ?? "");
          return `<tr class="${same ? "" : "cin-diff"}"><th scope="row">${TEAM_LABEL[col]}</th><td>${fieldShow(col === "share" ? "share" : col, a)}</td><td>${fieldShow(col === "share" ? "share" : col, b)}</td></tr>`; }).join("")}</tbody></table>` : "";
    return `<div class="cin-box cin-dup"><h5>${icon("copy")}It may be a duplicate</h5>
      <ul class="cin-duplist">${c.dups.map(d => `<li><span class="hq-chip t-${LEVEL[d.level]}">${d.level}</span><b>${esc(d.label)}</b><span class="faint small">${esc(d.why)}${d.type === "team" ? ` · SN${d.netuid} team` : " · in the queue"}</span>
        ${d.type === "candidate" ? `<button type="button" class="linkbtn" data-cinpick="${d.id}">Open</button>` : `<button type="button" class="linkbtn" data-cinteam="${d.id}">Open team</button>`}</li>`).join("")}</ul>
      ${cmp}${team ? `<p class="faint small">Approve below as an update to ${esc(team.label)}, or as a separate competition if you've checked it's a different one.</p>` : ""}</div>`;
  }
  function fields(c) {
    const f = c.fields, ev = c.evidence;
    const how = k => { const e = ev[k]; if (!e || f[k] == null) return "";
      const bad = e.how === "ai" && c.checks.some(x => x.field === k && x.level === "warn");
      return `<span class="hq-chip t-${bad ? "warn" : HOW[e.how]?.[0] || "none"}" ${e.quote ? `title="${esc(`“${e.quote}”`)}"` : ""}>${HOW[e.how]?.[1] || e.how}${bad ? " · unverified" : ""}</span>`; };
    const rows = home.fields.map(({ id, label: l }) => `<tr><th scope="row">${l}</th><td>${fieldShow(id, f[id])}${ev[id]?.quote ? `<q class="cin-quote">${esc(ev[id].quote)}</q>` : ""}</td><td>${how(id)}</td></tr>`).join("");
    return `<div class="cin-box"><h5>${icon("list")}What the import found <button type="button" class="btn sm cin-h-act" data-cinact="edit" ${["approved", "rejected"].includes(c.status) ? "hidden" : ""}>${icon("edit")}Edit</button></h5>
      <div class="cin-tablewrap"><table class="cin-fields"><tbody>${rows}</tbody></table></div>
      <p class="faint small">Unknown means the source didn't say: nothing is guessed. Fields read by AI show the sentence they came from.</p></div>`;
  }
  function editForm(c) {
    const f = c.fields;
    const inp = (k, l, extra = "") => `<label class="in"><span>${l}</span><input name="${k}" value="${esc(f[k] ?? "")}" ${extra}></label>`;
    const ta = (k, l, rows = 2) => `<label class="in"><span>${l}</span><textarea name="${k}" rows="${rows}">${esc(f[k] ?? "")}</textarea></label>`;
    return `<form class="cin-box cin-edit" data-cinform="edit"><h5>${icon("edit")}Edit the import</h5>
      <div class="mh-row">${inp("name", "Name", 'maxlength="80"')}${inp("platform", "Platform", 'maxlength="40"')}</div>
      <div class="mh-row3">${inp("netuid", "Subnet", 'type="number" min="0" max="4096"')}${inp("external_id", "Competition ID", 'maxlength="40"')}
        <label class="in"><span>Status</span><select name="status"><option value="">Unknown</option>${["upcoming", "active", "closed"].map(s => `<option value="${s}" ${f.status === s ? "selected" : ""}>${s[0].toUpperCase() + s.slice(1)}</option>`).join("")}</select></label></div>
      <div class="mh-row">${inp("starts", "Starts", 'type="date"')}${inp("ends", "Ends", 'type="date"')}</div>
      ${inp("url", "Source URL", 'type="url" maxlength="300"')}
      <div class="mh-row">${inp("registration_url", "Registration", 'type="url" maxlength="300"')}${inp("organizer", "Organizer", 'maxlength="80"')}</div>
      ${ta("description", "Description", 3)}${ta("scoring", "Scoring")}${ta("rewards", "Rewards")}${ta("requirements", "Requirements")}
      <div class="mh-row">${ta("submission", "Submission")}${ta("evaluation", "Evaluation")}</div>
      <label class="in"><span>Emission share <em class="opt">%</em></span><input name="share" type="number" min="0" max="100" step="0.1" value="${f.share != null ? +(f.share * 100).toFixed(2) : ""}"></label>
      <div class="row end"><button type="button" class="btn" data-cinact="noedit">Cancel</button><button type="submit" class="btn primary">${icon("check")}Save</button></div></form>`;
  }
  function assessment(c, decided) {
    const a = c.analysis;
    if (!a) return decided || !home.model ? "" : `<div class="cin-box cin-ai"><h5>${icon("sparkle")}AI assessment <span class="hq-chip t-acc">estimate</span></h5>
      <p class="faint small">The model reads the record and suggests a team, the skills and hardware it needs, risks and what to check. It's an estimate, not verified.</p>
      <div class="row"><button type="button" class="btn sm" data-cinact="assess">${icon("sparkle")}Assess with AI</button></div></div>`;
    const pack = home.packs.find(p => p.id === a.team);
    const list = xs => xs?.length ? `<ul>${xs.map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : `<p class="faint small">None given.</p>`;
    return `<div class="cin-box cin-ai"><h5>${icon("sparkle")}AI assessment <span class="hq-chip t-acc">estimate, not verified</span><span class="faint small">${esc(a.model || "")} · ${when(a.ts)}</span></h5>
      <p>${esc(a.summary)}</p>
      <div class="cin-ai-grid"><div><h6>Rules</h6>${list(a.rules)}</div><div><h6>Skills</h6>${list(a.skills)}</div>
        <div><h6>Deadlines</h6><p>${esc(a.deadlines)}</p><h6>Hardware</h6><p>${esc(a.hardware)}</p></div>
        <div><h6>Suggested team</h6><p><b>${esc(pack?.label || a.team)}</b> ${esc(a.team_why)}</p><h6>Opportunity</h6><p>${esc(a.opportunity)}</p></div>
        <div><h6>Risks</h6>${list(a.risks)}</div><div><h6>Check before approving</h6>${list(a.questions)}</div></div>
      ${decided ? "" : `<div class="row"><button type="button" class="btn sm" data-cinact="assess">${icon("cycle")}Assess again</button></div>`}</div>`;
  }
  function decide(c) {
    const f = c.fields, camps = home.campaigns, fit = camps.filter(k => f.netuid == null || k.netuid === f.netuid);
    const team = c.dups.find(d => d.type === "team"), strong = c.dups.some(d => d.type === "team" && d.level === "very high");
    const upd = c.kind === "update" || !!team;
    const targetId = c.kind === "update" ? c.comp_id : team?.id;
    const want = c.campaign_id && fit.some(k => k.id === c.campaign_id) ? c.campaign_id : fit[0]?.id;
    const suggest = c.analysis?.team;
    const teams = [["auto", "The team for this competition", "picked from its name: a Ridges niche team for a Ridges competition, else the 37-agent top miner team"],
      ...home.packs.map(p => [p.id, p.label, `${p.count} agents`]), ["default", "A small team", "5 agents"], ["empty", "Start empty", "add agents yourself"]];
    const ch = Object.keys(c.changes || {});
    const diff = col => { if (c.kind === "update") return ch.includes(col); const fld = home.team_fields[col], a = col === "number" ? f.external_id : f[fld];
      return a != null && a !== "" && String(a) !== String(team?.fields[col] ?? ""); };
    const create = `<div class="cin-mode" data-mode="create">
        ${fit.length ? `<label class="in"><span>Campaign <em class="opt">the team works for it${f.netuid != null ? `: campaigns on SN${f.netuid}` : ""}</em></span>
          <select name="campaign_id">${fit.map(k => `<option value="${k.id}" ${k.id === want ? "selected" : ""}>SN${k.netuid} · ${esc(k.title)}${k.mech ? ` · competition ${k.mech + 1}` : ""}</option>`).join("")}</select></label>`
          : `<p class="mh-err">${icon("alert")}${f.netuid != null ? `You have no subnet in My subnets on SN${f.netuid}: start one in My subnets, or edit the subnet.` : "You haven't added a subnet in My subnets yet: start one in My subnets first."}</p>`}
        <label class="in"><span>Team</span><select name="team">${teams.map(([id, l, d]) => `<option value="${id}" ${(suggest ? suggest === id : id === "auto") ? "selected" : ""}>${esc(l)} (${esc(d)})${suggest === id ? " · AI suggestion" : ""}</option>`).join("")}</select></label>
        ${strong ? `<label class="mh-check"><input type="checkbox" name="separate"><span>I've checked: it's a separate competition from ${esc(team.label)}</span></label>` : ""}</div>`;
    const update = upd ? `<div class="cin-mode" data-mode="update">
        <label class="in"><span>Team to update</span><select name="target">${home.teams.map(t => `<option value="${t.id}" ${t.id === targetId ? "selected" : ""}>SN${t.netuid} · ${esc(t.label)}</option>`).join("")}</select></label>
        <fieldset class="cin-apply"><legend>Take these from the import</legend>${Object.keys(home.team_fields).map(col => `<label class="mh-check"><input type="checkbox" name="apply" value="${col}" ${diff(col) ? "checked" : ""}><span>${TEAM_LABEL[col]}</span></label>`).join("")}</fieldset></div>` : "";
    const mode = c.kind === "update" ? "update" : strong ? "update" : "create";
    return `<form class="cin-box cin-decide" data-cinform="approve" data-mode="${mode}"><h5>${icon("check")}Your decision</h5>
      ${upd && c.kind !== "update" ? `<div class="cin-modes" role="radiogroup"><label class="mh-check"><input type="radio" name="mode" value="create" ${mode === "create" ? "checked" : ""}><span><b>New team</b></span></label>
        <label class="mh-check"><input type="radio" name="mode" value="update" ${mode === "update" ? "checked" : ""}><span><b>Update an existing team</b></span></label></div>` : `<input type="hidden" name="mode" value="${mode}">`}
      ${c.kind === "update" ? update : create + update}
      <p class="faint small">Approving ${mode === "update" ? "changes the team's details only" : "makes the team with autopilot off"}: nothing runs, deploys, registers or spends until you start it.</p>
      ${rejecting ? `<div class="cin-reject"><label class="in"><span>Why reject it? <em class="opt">optional, kept in the history</em></span><input name="note" maxlength="600" placeholder="e.g. Not a competition we enter"></label>
          <div class="row end"><button type="button" class="btn" data-cinact="noreject">Cancel</button><button type="button" class="btn mw-danger" data-cinact="reject">${icon("ban")}Reject</button></div></div>`
        : `<div class="row end cin-btns"><button type="button" class="btn sm mw-danger" data-cinact="delete">${icon("trash")}Delete</button>
          <button type="button" class="btn sm" data-cinact="askreject">${icon("ban")}Reject</button>
          <button type="button" class="btn sm" data-cinact="${c.status === "draft" ? "undraft" : "draft"}">${icon(c.status === "draft" ? "inbox" : "pin")}${c.status === "draft" ? "Back to review" : "Save for later"}</button>
          <button type="submit" class="btn primary" ${c.verdict === "fail" ? "disabled title=\"Fix what fails first\"" : ""}>${icon("check")}${mode === "update" ? "Approve update" : "Approve and create team"}</button></div>`}</form>`;
  }
  function outcome(c) {
    const t = home.teams.find(k => k.id === c.comp_id);
    return `<div class="cin-box"><h5>${icon(c.status === "approved" ? "check" : "ban")}${c.status === "approved" ? "Approved" : "Rejected"} by ${esc(c.reviewer || "?")} · ${when(c.reviewed)}</h5>
      ${c.note ? `<p>${esc(c.note)}</p>` : ""}${c.status === "approved" && c.comp_id ? `<div class="row"><button type="button" class="btn sm primary" data-cinteam="${c.comp_id}">${icon("external")}Open ${esc(t?.label || "the team")}</button></div>` : ""}</div>`;
  }

  // manual import
  function importer() {
    const camps = home.campaigns;
    const csvBox = csv ? `<div class="cin-csvmap"><p class="small">${plural(csv.count, "row")} · map each column to a field (Name is needed):</p>
        <div class="cin-tablewrap"><table class="cin-cmp"><thead><tr>${csv.headers.map(h => `<th>${esc(h)}<select data-cincol="${esc(h)}" aria-label="Field for ${esc(h)}"><option value="">Skip</option>${csv.fields.map(f => `<option value="${f.id}" ${csv.mapping[h] === f.id ? "selected" : ""}>${f.label}</option>`).join("")}</select></th>`).join("")}</tr></thead>
          <tbody>${csv.rows.map(r => `<tr>${csv.headers.map(h => `<td>${esc(r[h])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <div class="row end"><button type="button" class="btn sm" data-cinact="csvcancel">Cancel</button><button type="button" class="btn sm primary" data-cinact="csvgo">${icon("download")}Import ${plural(csv.count, "competition")}</button></div></div>` : "";
    return `<div class="cin-imports">
      <form class="cin-card" data-cinform="url"><h5>${icon("globe")}From a URL</h5>
        <p class="faint small">A competition page, a GitHub repository or issue, a ridges.ai page, a JSON address, or a subnet number. Only public addresses are read; the page is data, never instructions.</p>
        <label class="in"><span>Address</span><input name="url" required maxlength="1000" placeholder="https://… or 62" autocomplete="off"></label>
        <div class="mh-row"><label class="in"><span>Read it as</span><select name="kind"><option value="auto">Detect from the address</option><option value="page">Competition web page</option><option value="github">GitHub repository or issue</option>
            <option value="ridges">Ridges competitions</option><option value="bittensor">Bittensor subnet</option><option value="json">JSON</option></select></label>
          <label class="in"><span>Campaign <em class="opt">optional</em></span><select name="campaign_id"><option value="">Pick when approving</option>${camps.map(k => `<option value="${k.id}">SN${k.netuid} · ${esc(k.title)}</option>`).join("")}</select></label></div>
        <label class="in"><span>Note <em class="opt">optional, kept with the import</em></span><input name="note" maxlength="600" placeholder="e.g. Found on the subnet's Discord"></label>
        ${home.model ? "" : `<p class="mh-err small">${icon("info")}No model is connected: only a page's title and description can be read; you fill in the rest.</p>`}
        <div class="row end"><button type="submit" class="btn primary sm">${icon("download")}Import</button></div></form>
      <form class="cin-card" data-cinform="json"><h5>${icon("code")}JSON</h5>
        <p class="faint small">A list of competitions, <code>{"competitions": [...]}</code> or one object. Columns like name, subnet, id, start, end, url, scoring, rewards are recognized.</p>
        <label class="in"><span>Paste JSON <em class="opt">or pick a file</em></span><textarea name="text" rows="5" class="mw-code" spellcheck="false" placeholder='[{"name": "…", "subnet": 62, "id": "31", "start": "2026-11-10", "url": "https://…"}]'></textarea></label>
        <div class="row"><label class="btn sm cin-file">${icon("upload")}File<input type="file" accept=".json,application/json" data-cinfile="json"></label><span class="grow"></span><button type="submit" class="btn primary sm">${icon("download")}Import</button></div></form>
      <form class="cin-card" data-cinform="csv"><h5>${icon("table")}CSV</h5>
        <p class="faint small">Up to 100 competitions, one per row, with a header row. You map the columns to fields before anything is imported.</p>
        ${csv ? csvBox : `<label class="in"><span>Paste CSV <em class="opt">or pick a file</em></span><textarea name="text" rows="5" class="mw-code" spellcheck="false" placeholder="name,subnet,start,end,url"></textarea></label>
        <div class="row"><label class="btn sm cin-file">${icon("upload")}File<input type="file" accept=".csv,text/csv" data-cinfile="csv"></label><span class="grow"></span><button type="submit" class="btn primary sm">${icon("columns")}Map columns</button></div>`}</form>
      <div class="cin-card"><h5>${icon("edit")}Type it in</h5>
        <p class="faint small">You know the competition already: the New competition form makes its team straight away.</p>
        <div class="row end"><button type="button" class="btn sm" data-cinact="newcomp">${icon("folderplus")}New competition</button></div></div></div>`;
  }

  // sources
  function sources() {
    const s = home.sources, camps = home.campaigns, ridges = s.some(x => x.kind === "ridges");
    const row = x => `<li class="cin-src"><span class="av sm c-${x.kind === "ridges" ? "violet" : x.kind === "github" ? "slate" : x.kind === "bittensor" ? "teal" : "blue"}" aria-hidden="true">${icon(KIND_ICON[x.kind] || "link")}</span>
      <div class="cin-src-t"><b>${esc(x.label)}</b><span class="faint small">${esc(x.kind_label)} · ${x.kind === "bittensor" ? `SN${esc(x.url)}` : `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.url)}</a>`}</span>
        <span class="small">${x.running ? `${icon("cycle")}Checking…` : x.ok ? `Checked <time data-ts="${x.ok}"></time>${x.found != null ? ` · ${plural(x.found, "competition")} found` : ""}` : x.last ? "Not read yet" : "Not checked yet"}
          ${x.error ? `<span class="mh-err">${icon("alert")}${esc(x.error)}</span>` : ""}</span></div>
      <div class="cin-src-act"><label class="mw-switch sm" title="Check it by itself"><input type="checkbox" data-cinauto="${x.id}" ${x.auto ? "checked" : ""} aria-label="Check ${esc(x.label)} automatically"><span aria-hidden="true"></span></label>
        <select data-cinevery="${x.id}" aria-label="How often">${home.every.map(h => `<option value="${h}" ${x.every_h === h ? "selected" : ""}>${h < 1 ? "every 30 min" : h === 1 ? "every hour" : h === 24 ? "every day" : `every ${h} h`}</option>`).join("")}</select>
        <button type="button" class="btn sm" data-cinrun="${x.id}" ${x.running ? "disabled" : ""}>${icon("cycle")}Check now</button>
        <button type="button" class="iconbtn" data-cindelsrc="${x.id}" aria-label="Remove ${esc(x.label)}">${icon("trash")}</button></div></li>`;
    return `<div class="cin-sources">
      <p class="faint small">Sources are checked on their schedule. New competitions go to Review; a change to a competition that already has a team is shown there as an update (Ridges' own dates and status update teams made from Ridges directly). Ended competitions nobody tracks are skipped.</p>
      ${s.length ? `<ul class="cin-srclist">${s.map(row).join("")}</ul>` : `<div class="empty small">No sources yet.</div>`}
      ${ridges ? "" : `<div class="cin-preset"><span class="av sm c-violet" aria-hidden="true">${icon("trophy")}</span><div><b>Ridges competitions</b><p class="faint small">ridges.ai's competitions page (SN62): each competition it lists, with its dates and emission share.</p></div>
        <button type="button" class="btn sm primary" data-cinact="ridges">${icon("plus")}Follow Ridges</button></div>`}
      <form class="cin-card" data-cinform="source"><h5>${icon("plus")}Add a source</h5>
        <div class="mh-row"><label class="in"><span>Kind</span><select name="kind">${Object.entries(home.kinds).map(([k, l]) => `<option value="${k}" ${k === "page" ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
          <label class="in"><span>Address <em class="opt">a URL, or the subnet number</em></span><input name="url" maxlength="1000" placeholder="https://…" autocomplete="off"></label></div>
        <div class="mh-row3"><label class="in"><span>Name <em class="opt">optional</em></span><input name="label" maxlength="80"></label>
          <label class="in"><span>Check</span><select name="every_h">${home.every.map(h => `<option value="${h}" ${h === 6 ? "selected" : ""}>${h < 1 ? "every 30 min" : h === 1 ? "every hour" : h === 24 ? "every day" : `every ${h} hours`}</option>`).join("")}</select></label>
          <label class="in"><span>Campaign <em class="opt">suggested on approval</em></span><select name="campaign_id"><option value="">None</option>${camps.map(k => `<option value="${k.id}">SN${k.netuid} · ${esc(k.title)}</option>`).join("")}</select></label></div>
        <p class="faint small">Web pages are read by the model only when they change (${fmtNum(home.day / 1000, 0)}k of ${fmtNum(home.day_cap / 1000, 0)}k import tokens used today).</p>
        <div class="row end"><button type="submit" class="btn primary sm">${icon("plus")}Add source</button></div></form></div>`;
  }

  // history
  function logLine(l) { return `<li>${icon(LOG_ICON[l.kind] || "dots")}<span><b>${esc(l.who || "")}</b> ${esc(l.text)}</span><span class="faint small">${when(l.ts)}</span></li>`; }
  function history() {
    if (!hist) return Loading.line("Reading the history…");
    return `<div class="cin-hist"><div><h5>${icon("check")}Decisions</h5>${hist.decided.length ? `<ul class="cin-list cin-decided">${hist.decided.map(c => `<li><button type="button" class="cin-item" data-cinpick="${c.id}" data-cinkeep>
        <span class="cin-item-t"><b>${esc(label(c.fields))}</b><span class="faint small">${esc(c.reviewer || "")} · ${when(c.reviewed)}${c.note ? ` · ${esc(c.note)}` : ""}</span></span>${chip(STATUS[c.status])}</button></li>`).join("")}</ul>` : `<p class="faint small">No decisions yet.</p>`}</div>
      <div><h5>${icon("clock")}Everything that happened</h5>${hist.log.length ? `<ul class="cin-log">${hist.log.map(logLine).join("")}</ul>` : `<p class="faint small">Nothing yet.</p>`}</div></div>`;
  }

  // ---------- acting ----------
  async function act(k, btn) {
    const c = cur;
    if (k === "edit") { editing = true; return render(); }
    if (k === "noedit") { editing = false; return render(); }
    if (k === "askreject") { rejecting = true; render(); return $("input[name=note]", dlg)?.focus(); }
    if (k === "noreject") { rejecting = false; return render(); }
    if (k === "newcomp") { dlg.close(); return MiningWork.newComp(); }
    if (k === "csvcancel") { csv = null; return render(); }
    if (k === "csvgo") {
      const r = await busy(btn, () => api(`${I}/csv`, { method: "POST", body: { text: csv.text, mapping: csv.mapping } }));
      if (r) { csv = null; Auth.toast(`${plural(r.created.length, "competition")} to review`); tab = "queue"; sel = null; set(r); }
      return;
    }
    if (k === "ridges") {
      const r = await busy(btn, () => api(`${I}/sources`, { method: "POST", body: { kind: "ridges", every_h: 6, auto: true, campaign_id: home.campaigns.find(x => x.netuid === 62)?.id ?? null } }));
      if (r) { Auth.toast("Following Ridges: its competitions come to Review"); set(r); }
      return;
    }
    if (!c) return;
    const go = async (path, body, method = "POST") => {
      const r = await busy(btn, () => api(`${I}/candidates/${c.id}${path}`, { method, body }));
      if (r?.candidate) { cur = r.candidate; editing = false; rejecting = false; }
      return r;
    };
    if (k === "retry") { if (await go("/retry")) load(); return; }
    if (k === "assess") { if (await go("/assess")) render(); return; }
    if (k === "draft" || k === "undraft") { if (await go("/draft", { on: k === "draft" })) { Auth.toast(k === "draft" ? "Saved for later" : "Back in review"); load(); } return; }
    if (k === "reject") {
      const note = $("input[name=note]", dlg)?.value || "";
      if (await go("/reject", { note })) { Auth.toast("Rejected"); sel = null; cur = null; load(); }
      return;
    }
    if (k === "delete") {
      return UI.confirm({ title: `Delete ${esc(label(c.fields))}?`, body: "It leaves the queue; the history keeps a line about it. A source that finds it again queues it again.", ok: "Delete",
        run: async () => { const r = await api(`${I}/candidates/${c.id}`, { method: "DELETE" }); sel = null; cur = null; set(r); Auth.toast("Deleted"); } }).catch(err);
    }
  }
  async function approve(form, btn) {
    const fd = new FormData(form), mode = fd.get("mode") || "create";
    const body = mode === "update" ? { mode, target: +fd.get("target"), apply: fd.getAll("apply") }
      : { mode, campaign_id: fd.get("campaign_id") ? +fd.get("campaign_id") : null, team: fd.get("team") || "auto", separate: !!fd.get("separate") };
    if (mode === "update" && !body.apply.length) return Auth.toast("Tick at least one field to take from the import");
    const r = await busy(btn, () => api(`${I}/candidates/${cur.id}/approve`, { method: "POST", body }));
    if (!r) return;
    cur = r.candidate;
    Auth.toast(mode === "update" ? "Team updated" : "Team created: autopilot is off until you switch it on");
    MiningWork.reload?.();
    load();
  }
  function click(e) {
    const t = e.target;
    if (t.closest("[data-close]")) return dlg.close();
    const tb = t.closest("[data-cintab]");
    if (tb) { tab = tb.dataset.cintab; if (tab === "history") { hist = null; loadHistory(); } return render(); }
    const p = t.closest("[data-cinpick]");
    if (p) { if (p.hasAttribute("data-cinkeep")) tab = "queue"; return pick(+p.dataset.cinpick); }
    if (t.closest("[data-cinback]")) { sel = null; cur = null; return render(); }
    const tm = t.closest("[data-cinteam]");
    if (tm) { dlg.close(); return MiningWork.openPage(+tm.dataset.cinteam); }
    const a = t.closest("[data-cinact]"); if (a) return act(a.dataset.cinact, a);
    const run = t.closest("[data-cinrun]");
    if (run) return busy(run, () => api(`${I}/sources/${run.dataset.cinrun}/run`, { method: "POST" })).then(r => { if (r) { Auth.toast("Checking now"); set(r); } });
    const del = t.closest("[data-cindelsrc]");
    if (del) {
      const s = home.sources.find(x => x.id === +del.dataset.cindelsrc);
      return UI.confirm({ title: `Stop following ${esc(s?.label || "this source")}?`, body: "Competitions it already found stay where they are.", ok: "Remove",
        run: async () => set(await api(`${I}/sources/${del.dataset.cindelsrc}`, { method: "DELETE" })) }).catch(err);
    }
  }
  async function change(e) {
    const t = e.target;
    if (t.matches("[data-cinauto]")) {
      const r = await busy(null, () => api(`${I}/sources/${t.dataset.cinauto}`, { method: "PATCH", body: { auto: t.checked } }));
      if (r) set(r); else t.checked = !t.checked;
      return;
    }
    if (t.matches("[data-cinevery]")) { const r = await busy(null, () => api(`${I}/sources/${t.dataset.cinevery}`, { method: "PATCH", body: { every_h: +t.value } })); if (r) set(r); return; }
    if (t.matches("[data-cincol]") && csv) { csv.mapping[t.dataset.cincol] = t.value; return; }
    if (t.matches("[name=mode]")) { const f = t.closest("form"); f.dataset.mode = t.value; const s = $("button[type=submit]", f); if (s) s.innerHTML = `${icon("check")}${t.value === "update" ? "Approve update" : "Approve and create team"}`; return; }
    if (t.matches("[data-cinfile]") && t.files?.[0]) {
      const file = t.files[0];
      if (file.size > 2_000_000) { t.value = ""; return Auth.toast("The file is over 2 MB"); }
      const ta = $("textarea[name=text]", t.closest("form")); if (ta) { ta.value = await file.text(); dirty = true; }
    }
  }
  async function submit(e) {
    e.preventDefault();
    const f = e.target, kind = f.dataset.cinform, btn = $("button[type=submit]", f), fd = new FormData(f);
    if (kind === "url") {
      const r = await busy(btn, () => api(`${I}/url`, { method: "POST", body: { url: fd.get("url").trim(), kind: fd.get("kind"), note: fd.get("note") || "", campaign_id: fd.get("campaign_id") ? +fd.get("campaign_id") : null } }));
      if (r) { tab = "queue"; sel = r.id; cur = null; set(r); pick(r.id); }
    } else if (kind === "json") {
      const r = await busy(btn, () => api(`${I}/json`, { method: "POST", body: { text: fd.get("text") } }));
      if (r) { Auth.toast(`${plural(r.created.length, "competition")} to review${r.skipped ? ` (${r.skipped} empty skipped)` : ""}`); tab = "queue"; sel = null; set(r); }
    } else if (kind === "csv") {
      const text = fd.get("text");
      const r = await busy(btn, () => api(`${I}/csv`, { method: "POST", body: { text, preview: true } }));
      if (r) { csv = { ...r, text }; render(); }
    } else if (kind === "source") {
      const r = await busy(btn, () => api(`${I}/sources`, { method: "POST", body: { kind: fd.get("kind"), url: fd.get("url").trim(), label: fd.get("label") || "", every_h: +fd.get("every_h"),
        campaign_id: fd.get("campaign_id") ? +fd.get("campaign_id") : null, auto: true } }));
      if (r) { Auth.toast("Source added: checking it now"); set(r); }
    } else if (kind === "edit") {
      const fields = {};
      for (const [k, v] of fd.entries()) fields[k] = k === "share" ? (v === "" ? null : +v / 100) : k === "netuid" ? (v === "" ? null : +v) : v;
      const r = await busy(btn, () => api(`${I}/candidates/${cur.id}`, { method: "PATCH", body: { fields } }));
      if (r) { cur = r.candidate; editing = false; Auth.toast("Saved"); load(); }
    } else if (kind === "approve") approve(f, btn);
  }

  return { open, peek, count };
})();
