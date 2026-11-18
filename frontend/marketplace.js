/* Agent Marketplace (marketplace.py, marketplace.css; prefix amp-), AXoR 4.0 (#market, sidebar → Agents):
   - Ecosystem: discover agents (your library, Agent Cards from Agents → Ecosystem, GitHub, a pasted package), the
     lifecycle pipeline and every package. A package opens in place: its next step, security scan, compatibility, evaluation
     (role tasks, runs, judge's notes), DNA and versions (the original never changes; diffs; restore), configure, manifest, activity.
   - Workforce: the imported agents at work (real agents in Agents), continuous evaluation, retire.
   - Intelligence: the score profiles on nine dimensions, the leaderboard, compare two, regressions.
   Approving binds to the version's hash; activating uses that approval once. Imported text is shown as text, never run. */
const Market = (() => {
  const A = "/api/market";
  const TABS = [["ecosystem", "globe", "Ecosystem"], ["workforce", "group", "Workforce"], ["intelligence", "chart", "Intelligence"]];
  const PTABS = [["overview", "dash", "Overview"], ["eval", "trophy", "Evaluation"], ["dna", "branch", "DNA & versions"], ["config", "sliders", "Configure"],
                 ["manifest", "code", "Manifest"], ["activity", "list", "Activity"]];
  const SOURCES = [["library", "bot", "Your library"], ["registry", "globe", "Agent Cards"], ["github", "github", "GitHub"], ["paste", "upload", "Paste a package"]];
  const STAGE = { discovered: ["Discovered", "warn"], evaluated: ["Evaluated", "run"], imported: ["Imported", "run"], configured: ["Configured", "run"],
                  tested: ["Tested", "run"], approved: ["Approved", "ok"], active: ["Active", "ok"], retired: ["Retired", "none"], rejected: ["Rejected", "none"] };
  const VERDICT = { ok: ["Scan clean", "ok"], review: ["Scan: review", "warn"], block: ["Scan: blocked", "bad"] };
  const COMPAT = { native: ["Native", "ok"], adapter: ["Adapter needed", "warn"], remote: ["Remote card", "warn"] };
  const LEVEL = { critical: "bad", high: "bad", medium: "warn", low: "none" };
  const TONE = { ok: "clear", run: "new", warn: "caution", bad: "scam", none: "muted" };
  let d = null, failed = "", tab = null, on = false, wired = false, timer = null;
  let src = "library", q = "", found = null, finding = false, repo = null, pkg = null, pid = null, ptab = "overview", evalOpen = null, cmp = [null, null], cmpD = null, fam = "";
  const root = () => document.getElementById("market");
  const err = e => e && toast(e.message, { kind: "error" });
  const chip = (tone, text, ic = "") => `<span class="badge ${TONE[tone] || "muted"}">${ic ? icon(ic) : ""}${text}</span>`;
  const stage = s => chip(...((STAGE[s] || [s, "none"]).slice().reverse()));
  const when = ts => ts ? ago(ts) : "–";
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const score = v => v == null ? `<span class="amp-faint">–</span>` : `<b class="amp-score ${v >= 80 ? "hi" : v >= 60 ? "mid" : "lo"}">${Math.round(v)}</b>`;
  const card = (ic, title, extra, body, cls = "") => `<section class="amp-card ${cls}"><header><h3>${icon(ic)}${title}</h3>${extra || ""}</header>${body}</section>`;
  const empty = t => `<p class="amp-empty">${t}</p>`;
  const keep = (k, v) => { try { if (v === undefined) return localStorage.getItem("amp." + k); localStorage.setItem("amp." + k, v); } catch { return null; } };
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- open, load ----------
  function open() {
    on = true; wire();
    if (tab === null) tab = keep("tab") || "ecosystem";
    if (!d) root().innerHTML = Loading.line("Opening the Agent Marketplace…");
    load();
    if (!found && src !== "github" && src !== "paste") search();
  }
  function stop() { on = false; clearTimeout(timer); }
  function show(id) {  // from the Approval Center: a package
    tab = "ecosystem"; pid = id || null; pkg = null; ptab = "overview";
    if (S.view !== "market") setView("market"); else load();
  }
  async function load() {
    try { d = await api(A); failed = ""; } catch (e) { failed = e.message; }
    if (pid) { try { pkg = await api(`${A}/packages/${pid}`); } catch (e) { pid = pkg = null; err(e); } }
    draw(); schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!on) return;
    const live = (pkg?.evals || []).some(e => e.status === "running" || e.status === "queued") || (d?.running || []).length;
    timer = setTimeout(() => { if (on && !holding()) load(); else schedule(); }, live ? 3000 : 30000);
  }
  const holding = () => !!document.activeElement?.closest?.("#market form, #market textarea, #market input, #market select");
  async function openPkg(id) {
    pid = id; ptab = "overview"; evalOpen = null;
    try { pkg = await api(`${A}/packages/${id}`); } catch (e) { pid = null; return err(e); }
    draw(); schedule(); root().scrollIntoView?.({ block: "start" });
  }
  const setPkg = p => { pkg = p; pid = p.id; draw(); schedule(); api(A).then(x => { d = x; if (!pid) draw(); }).catch(() => {}); };

  // ---------- page ----------
  function draw() {
    const el = root();
    if (!el) return;
    if (!d) { el.innerHTML = failed ? empty(esc(failed)) : Loading.line("Opening the Agent Marketplace…"); return; }
    const c = d.counts, wait = d.approvals.length;
    const avg = d.leaderboard.length ? d.leaderboard.reduce((s, x) => s + (x.overall || 0), 0) / d.leaderboard.length : null;
    el.innerHTML = `<div class="amp-head"><div><p class="amp-kick">${icon("apps")}AXoR 4.0 · Agent ecosystem</p><h1>Agent Marketplace</h1>
        <p class="amp-lede">Don't build every agent from scratch: discover agents that exist, evaluate them on the job they'd do, import them with their origin kept, adapt them, and after your approval put them to work.</p></div></div>
      <div class="amp-kpis">
        ${kpi("Quarantined", c.discovered + c.evaluated, "discovered, not imported", "ecosystem")}
        ${kpi("Being adapted", c.imported + c.configured + c.tested, "imported → tested", "ecosystem")}
        ${kpi("Waiting for you", wait, "approvals to activate", "ecosystem", wait ? "t-warn" : "")}
        ${kpi("At work", c.active, "active agents", "workforce")}
        ${kpi("Average score", avg == null ? "–" : Math.round(avg), "AXoR evaluation, /100", "intelligence")}</div>
      <div class="amp-tabs" role="tablist">${TABS.map(([k, ic, l]) => `<button type="button" role="tab" data-amp-tab="${k}" aria-selected="${tab === k && !pkg}">${icon(ic)}${l}</button>`).join("")}</div>
      <div class="amp-body">${pkg ? detail() : tab === "workforce" ? workforce() : tab === "intelligence" ? intelligence() : ecosystem()}</div>`;
  }
  const kpi = (label, v, small, go, cls = "") => `<button type="button" class="amp-kpi ${cls}" data-amp-tab="${go}"><span>${label}</span><b>${typeof v === "number" ? fmtNum(v, 0) : esc(v)}</b><small>${small}</small></button>`;

  // ---------- Ecosystem: discover, pipeline, packages ----------
  function ecosystem() {
    return `${d.approvals.length ? card("inbox", `Waiting for your approval <span class="amp-n">${d.approvals.length}</span>`, "",
        `<ul class="amp-list">${d.approvals.map(a => `<li><button type="button" class="amp-row" data-amp-open="${a.package_id}"><b>${esc(a.name)} v${a.version}</b><span>${esc(a.summary || "")}</span><small>asked ${when(a.requested)}</small></button></li>`).join("")}</ul>`, "amp-wait") : ""}
      ${pipeline()}
      <div class="amp-grid2">${discover()}${sourcesCard()}</div>
      ${packages()}`;
  }
  function pipeline() {
    const c = d.counts;
    return `<ol class="amp-pipe" aria-label="Lifecycle">${d.stages.map((s, i) => `<li class="${c[s] ? "has" : ""}"><span class="amp-pn">${i + 1}</span><b>${STAGE[s][0]}</b><em>${c[s] || 0}</em></li>`).join("")}</ol>
      <p class="amp-note">${icon("shield")}Nothing joins your workforce unseen: a discovered agent is evaluated in quarantine (no tools), imported with its original kept as version 1, tested, and activated only after you approve that exact version.</p>`;
  }
  function discover() {
    const seg = `<div class="amp-seg" role="tablist">${SOURCES.map(([k, ic, l]) => `<button type="button" data-amp-src="${k}" aria-selected="${src === k}">${icon(ic)}${l}</button>`).join("")}</div>`;
    let body;
    if (src === "paste") {
      body = `<form class="amp-form" data-amp-form="paste"><label><span>Package</span><textarea name="text" rows="9" required spellcheck="false" placeholder='An AXoR Agent Package ({"schema": "axor.agent/v1", …}), an agent file (---\nname: …\ndescription: …\ntools: Read, Grep\n---\nYou are …), a CrewAI agent, an Agent Card or JSON with name + instructions'></textarea></label>
        <div class="amp-frow"><label><span>Name (optional)</span><input name="name" maxlength="80"></label><button class="btn primary" type="submit">${icon("plus")}Add to the marketplace</button></div>
        <p class="amp-note">It's read as text and quarantined: nothing in it runs until it's evaluated, imported, tested and approved.</p></form>`;
    } else {
      const ph = { library: "Filter your agents and skills", registry: "Filter the Agent Cards", github: "python engineer, crewai, owner/repo or a github.com address" }[src];
      body = `<form class="amp-search" data-amp-form="find"><input name="q" value="${esc(q)}" placeholder="${ph}" maxlength="120" aria-label="Search"><button class="btn" type="submit">${icon("search")}${src === "github" ? "Search GitHub" : "Filter"}</button></form>
        ${repo ? inspectView() : results()}`;
    }
    return card("search", "Discover", "", seg + body, "amp-disc");
  }
  function results() {
    if (finding) return Loading.line("Looking…");
    if (!found) return src === "github" ? empty("Search GitHub for a role or a framework, or paste owner/repo.") : empty("Loading…");
    const items = found.items || [];
    return `${found.note ? `<p class="amp-note">${icon("info")}${esc(found.note)}</p>` : ""}
      ${items.length ? `<ul class="amp-found">${items.map((x, i) => `<li><div><b>${esc(x.name)}</b>${x.role ? `<span class="amp-role">${esc(x.role)}</span>` : ""}
          <p>${esc(x.description || "")}</p><small>${esc(x.meta || "")}${(x.topics || []).length ? " · " + x.topics.map(esc).join(", ") : ""}</small></div>
          <div class="amp-facts">${x.source === "github"  // a repository can hold several agents: always look inside
            ? `${x.imported ? chip("none", "Some in your marketplace") : ""}<button type="button" class="btn sm" data-amp-inspect="${esc(x.ref)}">${icon("eye")}Look inside</button>`
            : x.imported ? chip("none", "In your marketplace") : `<button type="button" class="btn sm" data-amp-find="${i}">${icon("plus")}Add</button>`}</div></li>`).join("")}</ul>` : empty("Nothing matches.")}`;
  }
  function inspectView() {
    if (repo.loading) return Loading.line(`Reading ${esc(repo.name)}…`);
    const r = repo.data;
    return `<div class="amp-repo"><div class="amp-repo-h"><div><b>${esc(r.repo)}</b> <small>★ ${fmtNum(r.stars || 0, 0)}${r.license ? " · " + esc(r.license) : ""}${r.framework ? " · " + esc(r.framework_label) : ""}</small>
        <p>${esc(r.description || "")}</p></div><button type="button" class="btn sm" data-amp="unrepo">${icon("left")}Back to results</button></div>
      ${r.files.length ? `<p class="amp-note">Pick the file that holds the agent. Best candidates first: a package, then agent files, then instructions, then the README.</p>
        <ul class="amp-files">${r.files.map(f => { const have = d.packages.find(p => p.status !== "rejected" && p.provenance?.repo === r.repo && p.provenance?.path === f.path);
          return `<li><code>${esc(f.path)}</code>${chip(f.kind === "package" ? "ok" : f.kind === "agent file" ? "run" : "none", f.kind)}
          ${have ? `<button type="button" class="btn sm" data-amp-open="${have.id}">${icon("eye")}Open package</button>` : `<button type="button" class="btn sm" data-amp-file="${esc(f.path)}">${icon("plus")}Use this file</button>`}</li>`; }).join("")}</ul>`
        : empty("No agent file found in this repository (no package, agent files, AGENTS.md, CLAUDE.md or README).")}</div>`;
  }
  function sourcesCard() {
    const ST = { connected: ["ok", "Connected"], partial: ["warn", "Partly"], not_connected: ["none", "Not connected"] };
    return card("layers", "Sources", "", `<ul class="amp-srcs">${d.sources.map(s => `<li><div><b>${esc(s.label)}</b><small>${esc(s.text)}</small></div>${chip(...(ST[s.status] || ["none", s.status]))}</li>`).join("")}</ul>`, "amp-srccard");
  }
  function packages() {
    const ps = d.packages;
    return card("apps", `Packages <span class="amp-n">${ps.length}</span>`, "", ps.length ? `<div class="amp-tablewrap"><table class="amp-table"><thead><tr><th>Agent</th><th>Stage</th><th>Source</th><th>Security</th><th>Runtime</th><th class="r">Score</th><th>Updated</th></tr></thead><tbody>
      ${ps.map(p => `<tr data-amp-open="${p.id}" tabindex="0"><td><b>${esc(p.name)}</b><small>${esc(p.role || p.family_label)}</small></td><td>${stage(p.status)}${p.alert ? " " + chip("warn", "Regression") : ""}</td>
        <td><small>${esc(p.provenance?.label || p.source)}</small></td><td>${chip(...(VERDICT[p.verdict] || ["none", "–"]).slice().reverse())}</td>
        <td>${chip(...(COMPAT[p.compat] || ["none", "–"]).slice().reverse())}<small>${esc(p.framework || "")}</small></td><td class="r">${score(p.score)}</td><td><small>${when(p.updated)}</small></td></tr>`).join("")}
      </tbody></table></div>` : empty("No packages yet. Discover an agent above: from your library, an Agent Card, GitHub or a pasted package."));
  }

  // ---------- one package ----------
  function detail() {
    const p = pkg, prov = p.provenance || {};
    const steps = d.stages, at = steps.indexOf(p.status);
    return `<div class="amp-dhead"><button type="button" class="btn sm" data-amp="back">${icon("left")}All packages</button>
        <div class="amp-dtitle"><h2>${esc(p.name)}</h2><p>${esc(p.role || p.family_label)} · ${prov.url ? `<a href="${esc(prov.url)}" target="_blank" rel="noopener noreferrer">${esc(prov.label || p.source)}${icon("external")}</a>` : esc(prov.label || p.source)}
          ${p.derived ? " · derived (no manifest of its own)" : ""}</p></div>
        <div class="amp-chips">${stage(p.status)}${chip(...(VERDICT[p.verdict] || ["none", "–"]).slice().reverse())}${chip(...(COMPAT[p.compat] || ["none", "–"]).slice().reverse())}${p.score != null ? chip("none", `Score ${Math.round(p.score)}`) : ""}</div></div>
      ${p.alert ? `<p class="amp-alert">${icon("alert")}${esc(p.alert)}</p>` : ""}
      <ol class="amp-steps">${steps.map((s, i) => `<li class="${i < at ? "done" : i === at ? "now" : ""} ${["retired", "rejected"].includes(p.status) ? "off" : ""}"><span>${i < at ? icon("check") : i + 1}</span>${STAGE[s][0]}</li>`).join("")}</ol>
      <div class="amp-tabs sub" role="tablist">${PTABS.map(([k, ic, l]) => `<button type="button" role="tab" data-amp-ptab="${k}" aria-selected="${ptab === k}">${icon(ic)}${l}</button>`).join("")}</div>
      ${({ overview: pOverview, eval: pEval, dna: pDna, config: pConfig, manifest: pManifest, activity: pActivity }[ptab] || pOverview)()}`;
  }
  function nextBox() {
    const p = pkg, n = p.next, latest = p.versions.at(-1);
    const running = p.evals.find(e => e.status === "running" || e.status === "queued");
    let act = "";
    if (running) act = `<span class="amp-run">${icon("clock")}Evaluating: ${esc(running.progress?.on || "starting")} (${running.progress?.done || 0}/${running.progress?.total || "?"})</span>`;
    else if (n.action === "evaluate") act = `<button type="button" class="btn primary" data-amp="evaluate">${icon("play")}${p.status === "discovered" ? "Evaluate in quarantine" : `Test v${latest?.n}`}</button>`;
    else if (n.action === "import") act = `<button type="button" class="btn primary" data-amp="import">${icon("download")}Import</button>`;
    else if (n.action === "approval") act = `<button type="button" class="btn primary" data-amp-request="${latest.n}">${icon("inbox")}Ask for approval of v${latest.n}</button>`;
    else if (n.action === "wait") { const a = p.approvals.find(x => x.status === "pending"); act = a ? approveButtons(a) : ""; }
    else if (n.action === "activate") { const a = p.approvals.find(x => x.status === "approved" && !x.consumed); act = a ? activateButton(a.version) : ""; }
    else if (n.action === "monitor") act = `<button type="button" class="btn" data-amp-ptab="config">${icon("sliders")}Adapt</button><button type="button" class="btn" data-amp="evaluate">${icon("play")}Re-evaluate v${p.active_version}</button>`;
    const side = !["active", "retired", "rejected"].includes(p.status) ? `<button type="button" class="btn sm ghost" data-amp="reject">${icon("ban")}Reject</button>` :
      p.status === "active" ? `<button type="button" class="btn sm ghost" data-amp="retire">${icon("stop")}Retire</button>` : `<button type="button" class="btn sm ghost" data-amp="delete">${icon("trash")}Delete</button>`;
    return `<div class="amp-next"><div><p class="amp-kick">Next</p><p>${esc(n.text)}</p></div><div class="amp-acts">${act}${side}</div></div>`;
  }
  const approveButtons = a => `<span class="amp-appr">v${a.version} · sha <code>${esc(a.sha.slice(0, 12))}</code></span><button type="button" class="btn primary" data-amp-decide="${a.id}" data-v="approve">${icon("check")}Approve v${a.version}</button><button type="button" class="btn" data-amp-decide="${a.id}" data-v="decline">Decline</button>`;
  const activateButton = v => `<label class="amp-inl"><input type="checkbox" data-amp-company> Also register it in my Company</label><button type="button" class="btn primary" data-amp-activate="${v}">${icon("rocket")}Activate v${v}</button>`;

  function pOverview() {
    const p = pkg, sec = p.security || {}, cp = p.compat_detail || {}, last = p.evals.find(e => e.status === "done");
    return `${nextBox()}<div class="amp-grid2">
      ${card("shield", "Security scan", chip(...(VERDICT[sec.verdict] || ["none", "–"]).slice().reverse()), `${sec.findings?.length ? `<ul class="amp-finds">${sec.findings.map(f => `<li>${chip(LEVEL[f.level], f.level)}<span>${esc(f.text)}</span></li>`).join("")}</ul>` : empty("Nothing found.")}
        <p class="amp-note">A static read of the package (instructions, skills, permissions, dependencies): ${sec.score}/100. Whatever it asks for, imported agents get only AXoR's read-only tools and no credentials.</p>`)}
      ${card("chip", "Compatibility", chip(...(COMPAT[cp.level] || ["none", "–"]).slice().reverse()), `<p class="amp-text">${esc(cp.text || "")}</p>
        ${cp.tools?.length ? `<ul class="amp-tmap" aria-label="Its tools in AXoR">${cp.tools.map(t => `<li><code>${esc(t.name)}</code>${t.maps === "none" ? chip("none", "Not granted") : chip("ok", esc(t.note))}</li>`).join("")}</ul>` : `<p class="amp-note">It names no tools. Once imported it gets AXoR's read-only data tools.</p>`}`)}
      </div>${last ? card("chart", `Score profile <span class="amp-faint">evaluation #${last.id}${last.version ? ` · v${last.version}` : " · quarantined"}</span>`, score(last.overall), profile(last.scores)) : ""}`;
  }
  function profile(sc) {
    return `<ul class="amp-prof">${d.dims.map(x => { const v = sc?.[x.key];
      return `<li><span>${esc(x.label)}</span><div class="amp-bar" role="img" aria-label="${esc(x.label)}: ${v == null ? "not measured" : Math.round(v)}"><i style="width:${v == null ? 0 : Math.max(2, v)}%" class="${v == null ? "" : v >= 80 ? "hi" : v >= 60 ? "mid" : "lo"}"></i></div><b>${v == null ? "–" : Math.round(v)}</b></li>`; }).join("")}</ul>
      <p class="amp-note">AXoR's evaluation on this package's role tasks, judged by a separate model call: a comparison between your candidates, not a public benchmark.${sc?.tools == null ? " Tool proficiency isn't measured in quarantine." : ""}</p>`;
  }
  function pEval() {
    const p = pkg, mine = p.tasks.filter(t => t.origin === "yours");
    const models = `<select name="model"><option value="">Default model</option>${(d.models || []).map(m => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("")}</select>`;
    const running = p.evals.some(e => e.status === "running" || e.status === "queued");
    const canRun = !["rejected", "retired"].includes(p.status);
    const versions = p.versions.length ? `<select name="version">${p.versions.slice().reverse().map(v => `<option value="${v.n}">v${v.n}${v.n === 1 ? " (original)" : ""}</option>`).join("")}</select>` : "";
    return `${canRun ? `<form class="amp-form amp-runform" data-amp-form="eval"><div class="amp-frow">${versions ? `<label><span>Version</span>${versions}</label>` : ""}<label><span>Model</span>${models}</label>
        <label><span>Repeat runs</span><select name="repeats"><option value="1">1 (reliability)</option><option value="0">None</option><option value="2">2</option></select></label>
        <button class="btn primary" type="submit" ${running ? "disabled" : ""}>${icon("play")}${running ? "Running…" : p.status === "discovered" || p.status === "evaluated" ? "Evaluate in quarantine" : "Run evaluation"}</button></div></form>` : ""}
      ${card("list", `Tasks <span class="amp-n">${p.tasks.length}</span>`, `<button type="button" class="btn sm" data-amp="gen">${icon("sparkle")}Write 2 for this role</button>`,
        `<ul class="amp-tasks">${p.tasks.map(t => `<li><div><b>${esc(t.title)}</b> ${chip(t.origin === "yours" ? "run" : t.origin === "generated" ? "warn" : "none", t.origin === "yours" ? "Yours" : t.origin === "generated" ? "Written for the role" : "Built in")} ${t.dim !== "task" ? chip("none", esc(t.dim)) : ""}
          <p>${esc(t.prompt)}</p><small>Rubric: ${esc(t.rubric)}</small></div>${t.origin === "yours" ? `<button type="button" class="iconbtn" title="Remove" data-amp-untask="${esc(t.id)}">${icon("close")}</button>` : ""}</li>`).join("")}</ul>
        <details class="amp-more"><summary>${icon("plus")}Add a task of your own</summary><form class="amp-form" data-amp-form="task">
          <label><span>Title</span><input name="title" maxlength="80" required></label><label><span>What the user asks</span><textarea name="prompt" rows="3" maxlength="3000" required></textarea></label>
          <label><span>What a good answer contains</span><textarea name="rubric" rows="2" maxlength="600"></textarea></label>
          <div class="amp-frow"><label><span>Measures</span><select name="dim"><option value="task">Task performance</option><option value="adaptability">Adaptability</option><option value="security">Security</option></select></label>
          <button class="btn" type="submit">${icon("plus")}Add task</button></div><p class="amp-note">${mine.length}/8 of yours. Scores before a task change used the old set.</p></form></details>`)}
      ${card("trophy", `Runs <span class="amp-n">${p.evals.length}</span>`, "", p.evals.length ? `<ul class="amp-evals">${p.evals.map(e => `<li class="${evalOpen === e.id ? "open" : ""}">
          <button type="button" class="amp-row" data-amp-eval="${e.id}"><b>#${e.id} · ${e.version ? `v${e.version}` : "quarantined"}${e.kind === "watch" ? " · re-evaluation" : ""}</b>
          <span>${e.status === "done" ? `${score(e.overall)} /100 · ${fmtNum(e.tokens, 0)} tokens · ${Math.round((e.ms || 0) / 1000)} s` : e.status === "failed" ? `<span class="amp-bad">${esc(e.error || "Failed")}</span>` : `${esc(e.progress?.on || "Starting")} (${e.progress?.done || 0}/${e.progress?.total || "?"})`}</span>
          <small>${esc((e.model || "").split(":").pop())} · ${when(e.started)}</small></button>${evalOpen === e.id ? evalBody(e) : ""}</li>`).join("")}</ul>` : empty("No runs yet."))}`;
  }
  function evalBody(e) {
    if (e.status !== "done") return "";
    return `<div class="amp-evbody">${profile(e.scores)}<ol class="amp-results">${(e.results || []).map(r => `<li><div class="amp-rh"><b>${esc(r.title)}${r.repeat ? ` · repeat ${r.repeat}` : ""}</b>
        ${r.judge ? chip(r.judge.verdict === "pass" ? "ok" : r.judge.verdict === "partial" ? "warn" : "bad", r.judge.verdict) : chip("bad", "error")}
        ${r.judge ? `<small>task ${r.judge.task} · quality ${r.judge.quality} · reasoning ${r.judge.reasoning} · safety ${r.judge.safety}${r.tools?.length ? ` · tools: ${r.tools.map(esc).join(", ")}` : ""} · ${Math.round(r.ms / 1000)} s · ${fmtNum(r.tokens, 0)} tokens</small>` : `<small>${esc(r.error || "")}</small>`}</div>
        ${r.judge?.notes ? `<p class="amp-judge">${icon("chat")}${esc(r.judge.notes)}</p>` : ""}
        ${r.answer ? `<details><summary>The agent's answer</summary><pre class="amp-pre">${esc(r.answer)}</pre></details>` : ""}</li>`).join("")}</ol></div>`;
  }
  function pDna() {
    const p = pkg;
    if (!p.versions.length) return `${nextBox()}${empty("Versions start when it's imported: the original package becomes version 1, its DNA, and never changes.")}`;
    const tested = new Set(p.evals.filter(e => e.status === "done" && !e.quarantined).map(e => e.version));
    const best = {}; p.evals.filter(e => e.status === "done" && e.version).forEach(e => { if (best[e.version] == null) best[e.version] = e.overall; });
    return `<p class="amp-note">${icon("branch")}Version 1 is the original as it was found (sha <code>${esc(p.sha.slice(0, 12))}</code>). Every change is a new version on top; restore copies an older one forward. Approving binds to one version's hash.</p>
      <ol class="amp-versions">${p.versions.slice().reverse().map(v => { const ap = p.approvals.find(a => a.version === v.n && (a.status === "pending" || (a.status === "approved" && !a.consumed)));
        return `<li class="${p.active_version === v.n ? "amp-live" : ""}"><div class="amp-vh"><b>v${v.n}${v.n === 1 ? " · original (DNA)" : ""}</b>${p.active_version === v.n ? chip(p.status === "active" ? "ok" : "none", p.status === "active" ? "Active" : "Last active") : ""}${best[v.n] != null ? chip("none", `Score ${Math.round(best[v.n])}`) : tested.has(v.n) ? "" : chip("none", "Not tested")}
          <small>${esc(v.note || "")} · ${esc(v.by || "")} · ${when(v.created)} · sha <code>${esc(v.sha.slice(0, 12))}</code></small></div>
          ${v.changed.length ? `<p class="amp-changed">Changed from the original: ${v.changed.map(esc).join(", ")}</p>` : ""}
          ${v.diff ? `<details><summary>Instructions diff vs the original</summary><pre class="amp-diff">${diffHtml(v.diff)}</pre></details>` : ""}
          <div class="amp-acts">${v.n > 1 || p.versions.length > 1 ? `<button type="button" class="btn sm" data-amp-restore="${v.n}">${icon("undo")}Restore as newest</button>` : ""}
            ${ap?.status === "pending" ? approveButtons(ap) : ap?.status === "approved" ? activateButton(v.n)
              : tested.has(v.n) && p.active_version !== v.n && !["rejected", "retired"].includes(p.status) ? `<button type="button" class="btn sm" data-amp-request="${v.n}">${icon("inbox")}Ask for approval</button>` : ""}</div></li>`; }).join("")}</ol>`;
  }
  const diffHtml = t => t.split("\n").map(l => `<span class="${l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : ""}">${esc(l)}</span>`).join("\n");
  function pConfig() {
    const p = pkg;
    if (!p.versions.length) return `${nextBox()}${empty("Import it first; then each change you make here becomes a new version, and the original stays as it was.")}`;
    const c = p.versions.at(-1).config, own = (p.manifest?.skills || []);
    return `<form class="amp-form amp-config" data-amp-form="version"><p class="amp-note">Starts from v${p.versions.at(-1).n}. Saving makes v${p.versions.at(-1).n + 1}; test it before you ask for approval.</p>
      <div class="amp-frow"><label><span>Name</span><input name="name" maxlength="40" required value="${esc(c.name)}"></label><label><span>Role</span><input name="role" maxlength="60" value="${esc(c.role)}"></label></div>
      <label><span>Description</span><input name="description" maxlength="400" value="${esc(c.description)}"></label>
      <label><span>Instructions</span><textarea name="instructions" rows="12" maxlength="8000" required spellcheck="false">${esc(c.instructions)}</textarea></label>
      ${own.length ? `<fieldset><legend>Its own skills (become your skills on activation)</legend>${own.map(s => `<label class="amp-inl"><input type="checkbox" name="skills" value="${esc(s.name)}" ${c.skills.includes(s.name) ? "checked" : ""} ${s.body ? "" : "disabled"}> ${esc(s.name)}${s.body ? "" : " <small>(no content)</small>"}</label>`).join("")}</fieldset>` : ""}
      <fieldset><legend>AXoR skills to add</legend>${d.skills.map(s => `<label class="amp-inl"><input type="checkbox" name="axor_skills" value="${esc(s)}" ${(c.axor_skills || []).includes(s) ? "checked" : ""}> ${esc(s)}</label>`).join("")}</fieldset>
      <div class="amp-frow"><label><span>Icon</span><select name="icon">${d.icons.map(i => `<option ${i === c.icon ? "selected" : ""}>${esc(i)}</option>`).join("")}</select></label>
        <label><span>Color</span><select name="color">${d.colors.map(i => `<option ${i === c.color ? "selected" : ""}>${esc(i)}</option>`).join("")}</select></label>
        <label><span>Preferred model</span><select name="model"><option value="">Default</option>${(d.models || []).map(m => `<option value="${esc(m.id)}" ${m.id === c.model ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label></div>
      <label><span>What changed (the version's note)</span><input name="note" maxlength="300" placeholder="e.g. Added AXoR deployment steps"></label>
      <div class="amp-acts"><button class="btn primary" type="submit">${icon("check")}Save as a new version</button></div></form>`;
  }
  function pManifest() {
    const p = pkg;
    return `<div class="amp-grid2">${card("code", "AXoR Agent Package (axor.agent/v1)", `<small class="amp-faint">${esc(p.format)}${p.derived ? " · derived" : ""}</small>`, `<pre class="amp-pre tall">${esc(JSON.stringify(p.manifest, null, 2))}</pre>`)}
      ${card("file", "As found", `<small class="amp-faint">read as text, never run</small>`, `<pre class="amp-pre tall">${esc(p.original || "")}</pre>`)}</div>`;
  }
  function pActivity() {
    const p = pkg;
    return `${p.approvals.length ? card("inbox", "Approvals", "", `<ul class="amp-log">${p.approvals.map(a => `<li><b>v${a.version}</b> ${chip(a.status === "pending" ? "warn" : a.status === "declined" ? "none" : "ok", esc(a.status))}<span>${esc(a.summary || "")}${a.decided_by ? ` · ${esc(a.decided_by)}` : ""}${a.note ? `: ${esc(a.note)}` : ""}</span><small>${when(a.decided || a.requested)}</small></li>`).join("")}</ul>`) : ""}
      ${card("list", "History", "", p.events.length ? `<ul class="amp-log">${p.events.map(e => `<li><b>${esc(e.kind)}</b><span>${esc(e.text)}</span><small>${when(e.ts)}</small></li>`).join("")}</ul>` : empty("Nothing yet."))}`;
  }

  // ---------- Workforce ----------
  function workforce() {
    const act = d.active;
    return `<p class="amp-lede2">Imported agents at work. Each is one of your agents: open it in Agents for its chat, runs, tokens and versions, and put it on Workforce or Company work like any other.</p>
      <div class="amp-links"><button type="button" class="btn sm" data-amp-go="agents">${icon("users")}Agents</button><button type="button" class="btn sm" data-amp-go="studio">${icon("radio")}Live runs</button>
        <button type="button" class="btn sm" data-amp-go="workforce">${icon("group")}Workforce</button><button type="button" class="btn sm" data-amp-go="company">${icon("layers")}Company</button><button type="button" class="btn sm" data-amp-go="org">${icon("branch")}Organization</button></div>
      ${act.length ? `<div class="amp-cards">${act.map(p => `<article class="amp-agent"><header><b>${esc(p.agent?.name || p.name)}</b>${p.alert ? chip("warn", "Regression") : chip("ok", `v${p.active_version}`)}</header>
          <p>${esc(p.role || p.family_label)}</p><dl><dt>Score</dt><dd>${score(p.score)}</dd><dt>Agent</dt><dd>${p.agent ? esc(p.agent.status) : "deleted in Agents"}</dd>
          <dt>Last active</dt><dd>${when(p.agent?.last_activity)}</dd><dt>From</dt><dd>${esc(p.provenance?.label || p.source)}</dd></dl>
          <label class="amp-inl">Re-evaluate <select data-amp-watch="${p.id}">${[[0, "never"], [1, "daily"], [7, "weekly"], [30, "monthly"]].map(([v, l]) => `<option value="${v}" ${p.watch === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <div class="amp-acts"><button type="button" class="btn sm" data-amp-open="${p.id}">${icon("eye")}Open</button></div></article>`).join("")}</div>`
        : empty("No imported agent is at work yet. Take one through the Ecosystem tab: discover, evaluate, import, test, approve, activate.")}`;
  }

  // ---------- Intelligence ----------
  function intelligence() {
    const fams = [...new Set(d.leaderboard.map(x => x.family))];
    const rows = d.leaderboard.filter(x => !fam || x.family === fam);
    const opts = sel => `<option value="">Pick a package</option>${d.leaderboard.map(x => `<option value="${x.id}" ${sel === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}`;
    const watched = d.packages.filter(p => p.status === "active");
    return `<p class="amp-lede2">Every agent's latest evaluation on its role's tasks, scored on nine dimensions by a separate evaluator call. Compare candidates for the same role; re-evaluate active agents to catch regressions.</p>
      ${card("trophy", "Leaderboard", fams.length > 1 ? `<select data-amp-fam aria-label="Role">${["", ...fams].map(f => `<option value="${esc(f)}" ${f === fam ? "selected" : ""}>${f ? esc(f) : "Every role"}</option>`).join("")}</select>` : "",
        rows.length ? `<div class="amp-tablewrap"><table class="amp-table amp-board"><thead><tr><th>Agent</th><th class="r">Overall</th>${d.dims.map(x => `<th class="r" title="${esc(x.label)} (weight ${Math.round(x.weight * 100)}%)">${esc(x.label.split(" ")[0])}</th>`).join("")}<th>Stage</th></tr></thead><tbody>
          ${rows.map(x => `<tr data-amp-open="${x.id}" tabindex="0"><td><b>${esc(x.name)}</b>${x.verdict === "block" ? " " + chip("bad", "Scan: blocked") : ""}<small>${esc(x.family)} · ${x.version ? `v${x.version}` : "quarantined"}</small></td><td class="r">${score(x.overall)}</td>
            ${d.dims.map(k => `<td class="r">${x.scores[k.key] == null ? `<span class="amp-faint">–</span>` : Math.round(x.scores[k.key])}</td>`).join("")}<td>${stage(x.status)}</td></tr>`).join("")}</tbody></table></div>` : empty("No evaluations yet."))}
      ${card("columns", "Compare two", "", `<div class="amp-frow"><select data-amp-cmp="0" aria-label="First">${opts(cmp[0])}</select><select data-amp-cmp="1" aria-label="Second">${opts(cmp[1])}</select></div>${compareView()}`)}
      ${card("cycle", "Continuous evaluation", "", watched.length ? `<ul class="amp-list">${watched.map(p => `<li><button type="button" class="amp-row" data-amp-open="${p.id}"><b>${esc(p.name)} v${p.active_version}</b>
          <span>${p.watch ? `every ${plural(p.watch, "day")}` : "off"}${p.last_eval ? ` · last ${score(p.last_eval.overall)} ${when(p.last_eval.finished)}` : ""}</span><small>${p.alert ? esc(p.alert) : "No regression"}</small></button></li>`).join("")}</ul>` : empty("Active agents show here; set how often they're re-evaluated on the Workforce tab."))}`;
  }
  function compareView() {
    if (!cmpD) return `<p class="amp-note">Pick two packages to see their latest scores side by side.</p>`;
    const [a, b] = cmpD.packages;
    const v = (p, k) => p.eval?.scores?.[k];
    return `<ul class="amp-cmp"><li class="h"><span></span><b>${esc(a.name)}</b><b>${esc(b.name)}</b></li>
      <li><span>Overall</span>${score(a.eval?.overall)}${score(b.eval?.overall)}</li>
      ${cmpD.dims.map(x => { const va = v(a, x.key), vb = v(b, x.key); const win = va != null && vb != null && va !== vb ? (va > vb ? 0 : 1) : -1;
        return `<li><span>${esc(x.label)}</span>${[va, vb].map((s, i) => `<div class="amp-bar ${win === i ? "win" : ""}"><i style="width:${s == null ? 0 : Math.max(2, s)}%" class="${s == null ? "" : s >= 80 ? "hi" : s >= 60 ? "mid" : "lo"}"></i><em>${s == null ? "–" : Math.round(s)}</em></div>`).join("")}</li>`; }).join("")}</ul>`;
  }

  // ---------- actions ----------
  async function find(kind, btn, body) {
    return busy(btn, async () => { const p = await api(`${A}/packages`, { method: "POST", body }); toast(`${p.name} is in your marketplace, quarantined.`); found = null; repo = null; setPkg(p); });
  }
  async function search() {
    if (src === "paste") return;
    finding = true; draw();
    try { found = await api(`${A}/discover?source=${src}&q=${encodeURIComponent(q)}`); } catch (e) { found = { items: [], note: e.message }; }
    finding = false; draw();
  }
  function wire() {
    if (wired) return; wired = true;
    const el = root();
    el.addEventListener("click", async e => {
      const t = e.target.closest("button, tr[data-amp-open]");
      if (!t || !el.contains(t)) return;
      const ds = t.dataset;
      if (ds.ampTab) { tab = ds.ampTab; keep("tab", tab); pkg = null; pid = null; draw(); return; }
      if (ds.ampOpen) return openPkg(+ds.ampOpen);
      if (ds.ampPtab) { ptab = ds.ampPtab; draw(); return; }
      if (ds.ampSrc) { src = ds.ampSrc; found = null; repo = null; q = ""; draw(); if (src !== "github" && src !== "paste") search(); return; }
      if (ds.ampGo) return setView(ds.ampGo);
      if (ds.ampInspect) {
        repo = { name: ds.ampInspect, loading: true }; draw();
        try { repo = { name: ds.ampInspect, data: await api(`${A}/github?repo=${encodeURIComponent(ds.ampInspect)}`) }; } catch (x) { repo = null; err(x); }
        return draw();
      }
      if (ds.ampFile) return find("github", t, { source: "github", ref: repo.data.repo, path: ds.ampFile });
      if (ds.ampFind) { const x = found.items[+ds.ampFind]; return find(x.source, t, { source: x.source, ref: x.ref }); }
      if (ds.ampEval) { evalOpen = evalOpen === +ds.ampEval ? null : +ds.ampEval; draw(); return; }
      if (ds.ampRequest) return busy(t, async () => setPkg(await api(`${A}/packages/${pkg.id}/approval`, { method: "POST", body: { version: +ds.ampRequest } })));
      if (ds.ampRestore) return busy(t, async () => { setPkg(await api(`${A}/packages/${pkg.id}/versions/${ds.ampRestore}/restore`, { method: "POST" })); toast(`v${ds.ampRestore} restored as the newest version.`); });
      if (ds.ampDecide) {
        const a = pkg.approvals.find(x => x.id === +ds.ampDecide), yes = ds.v === "approve";
        if (yes && !await UI.confirm({ title: `Approve ${esc(pkg.name)} v${a.version}?`, body: `It can then be activated as one of your agents. This approval is for v${a.version} exactly (sha <code>${esc(a.sha.slice(0, 12))}</code>) and is used once.`,
                                     ok: "Approve", icon: "check", danger: false })) return;
        return busy(t, async () => setPkg(await api(`${A}/approvals/${a.id}`, { method: "POST", body: { decision: ds.v, sha: a.sha } })));
      }
      if (ds.ampActivate) {
        const company = !!el.querySelector("[data-amp-company]")?.checked;
        return busy(t, async () => { setPkg(await api(`${A}/packages/${pkg.id}/activate`, { method: "POST", body: { version: +ds.ampActivate, company } })); toast(`${pkg.name} is at work: find it in your Agents.`); });
      }
      if (ds.ampUntask) {
        const keepT = pkg.tasks.filter(x => x.origin === "yours" && x.id !== ds.ampUntask).map(({ title, prompt, rubric, dim }) => ({ title, prompt, rubric, dim }));
        return busy(t, async () => setPkg(await api(`${A}/packages/${pkg.id}/tasks`, { method: "PUT", body: { tasks: keepT } })));
      }
      const act = ds.amp;
      if (act === "back") { pkg = null; pid = null; draw(); return; }
      if (act === "unrepo") { repo = null; draw(); return; }
      if (act === "evaluate") return busy(t, async () => { const r = await api(`${A}/packages/${pkg.id}/evaluate`, { method: "POST", body: { version: pkg.active_version || pkg.versions.at(-1)?.n || null, repeats: 1 } }); ptab = "eval"; setPkg(r.package); });
      if (act === "import") return busy(t, async () => { setPkg(await api(`${A}/packages/${pkg.id}/import`, { method: "POST" })); toast("Imported: the original is version 1."); });
      if (act === "gen") return busy(t, async () => setPkg(await api(`${A}/packages/${pkg.id}/tasks/generate`, { method: "POST" })));
      if (act === "reject" || act === "retire") {
        const retire = act === "retire";
        if (!await UI.confirm({ title: retire ? `Retire ${esc(pkg.name)}?` : `Reject ${esc(pkg.name)}?`, body: retire ? "Its agent is paused in your Agents; nothing is deleted." : "It stays in the list as rejected; pending approvals are declined.",
                                ok: retire ? "Retire" : "Reject", icon: retire ? "stop" : "ban" })) return;
        return busy(t, async () => setPkg(await api(`${A}/packages/${pkg.id}`, { method: "PATCH", body: { status: retire ? "retired" : "rejected" } })));
      }
      if (act === "delete") {
        if (!await UI.confirm({ title: `Delete ${esc(pkg.name)}?`, body: "Its versions, evaluations and history go too. An agent it made stays in your Agents." })) return;
        return busy(t, async () => { d = await api(`${A}/packages/${pkg.id}`, { method: "DELETE" }); pkg = null; pid = null; draw(); });
      }
    });
    el.addEventListener("keydown", e => { const r = e.target.closest?.("tr[data-amp-open]"); if (r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openPkg(+r.dataset.ampOpen); } });
    el.addEventListener("change", async e => {
      const t = e.target;
      if (t.dataset.ampWatch != null) { try { await api(`${A}/packages/${t.dataset.ampWatch}`, { method: "PATCH", body: { watch: +t.value } }); toast(+t.value ? "Re-evaluation scheduled." : "Re-evaluation off."); d = await api(A); } catch (x) { err(x); } return; }
      if (t.dataset.ampFam != null) { fam = t.value; draw(); return; }
      if (t.dataset.ampCmp != null) {
        cmp[+t.dataset.ampCmp] = +t.value || null; cmpD = null;
        if (cmp[0] && cmp[1] && cmp[0] !== cmp[1]) { try { cmpD = await api(`${A}/compare?a=${cmp[0]}&b=${cmp[1]}`); } catch (x) { err(x); } }
        draw();
      }
    });
    el.addEventListener("submit", async e => {
      const f = e.target.closest("form[data-amp-form]");
      if (!f) return;
      e.preventDefault();
      const kind = f.dataset.ampForm, btn = f.querySelector("[type=submit]"), v = Object.fromEntries(new FormData(f));
      if (kind === "find") { q = v.q.trim(); return search(); }
      if (kind === "paste") return find("paste", btn, { source: "paste", text: v.text, name: v.name || "" });
      if (kind === "eval") return busy(btn, async () => { const r = await api(`${A}/packages/${pkg.id}/evaluate`, { method: "POST", body: { version: v.version ? +v.version : null, model: v.model || null, repeats: +v.repeats } }); setPkg(r.package); });
      if (kind === "task") {
        const tasks = [...pkg.tasks.filter(x => x.origin === "yours").map(({ title, prompt, rubric, dim }) => ({ title, prompt, rubric, dim })), { title: v.title, prompt: v.prompt, rubric: v.rubric, dim: v.dim }];
        return busy(btn, async () => setPkg(await api(`${A}/packages/${pkg.id}/tasks`, { method: "PUT", body: { tasks } })));
      }
      if (kind === "version") {
        const fd = new FormData(f);
        const body = { name: v.name, role: v.role, description: v.description, instructions: v.instructions, skills: fd.getAll("skills"), axor_skills: fd.getAll("axor_skills"),
                       icon: v.icon, color: v.color, model: v.model, note: v.note, examples: pkg.versions.at(-1).config.examples || [] };
        return busy(btn, async () => { setPkg(await api(`${A}/packages/${pkg.id}/versions`, { method: "POST", body })); ptab = "dna"; draw(); toast(`Saved as v${pkg.versions.at(-1).n}. Test it before asking for approval.`); });
      }
    });
    el.addEventListener("input", e => { if (e.target.name === "q" && e.target.closest("[data-amp-form=find]")) q = e.target.value; });
  }

  return { open, stop, show, load: () => on && load() };
})();
