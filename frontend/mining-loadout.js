/* Competition teams, Loadouts (mining_loadout.py): what each Workflow agent brings to its runs, and how each version did.
   A tab beside Workflow and Files (mining-bench.js draws the frame), with four parts:
   - Agents: a card per agent (model, effort, memory, skills, MCP, its version and score, suggestions to apply) and the editor.
   - Scores: every version of every agent with what its runs led to (review, checks, merged, sent back), and the recent runs
     with what each one was given.
   - Library: the skills (built-in and yours) and plugins (bundles of skills and MCP servers) loadouts pick from.
   - Memory: the notes agents get in their prompt, the team's and each agent's; written as the work goes, or by you. */
const MiningLoadout = (() => {
  const L = "/api/mining/loadout";
  let d = null, dFid = null, dAt = 0, loading = false, failed = "", sec = "agents", ed = null, sk = null, pl = null, memFor = "all";
  const shown = new Set(), noteDraft = {};
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const money = x => x == null ? "–" : x > 0 && x < 0.01 ? "<$0.01" : `$${fmtNum(x || 0, x >= 10 ? 0 : 2)}`;
  const ago = ts => { const s = Date.now() / 1000 - ts; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(ts * 1000).toLocaleDateString(); };
  const ROLE = { director: ["Director", "star", "violet"], engineer: ["Engineer", "code", "blue"], reviewer: ["Reviewer", "shield", "amber"] };
  const KIND = { director: "plan", reviewer: "review", engineer: "engineer" };
  const SRC = { manual: "you", suggestion: "suggestion", template: "template", restore: "restore", team: "Team card", auto: "start" };
  const av = a => { const [, ic, c] = ROLE[a.role] || ["", "bot", "slate"]; return `<span class="av sm c-${c}" aria-hidden="true">${icon(ic)}</span>`; };
  const SKILL = () => Object.fromEntries((d?.skills || []).map(s => [s.name, s]));
  const PLUG = () => Object.fromEntries((d?.plugins || []).map(p => [p.name, p]));
  const scoreChip = s => s?.score == null ? `<span class="hq-chip t-none" title="${s ? `Rests on ${plural(s.basis, "outcome")}: it takes 3 to score` : "No runs yet"}">No score yet</span>`
    : `<span class="hq-chip t-${s.score >= 70 ? "ok" : s.score >= 45 ? "warn" : "bad"}" title="From ${plural(s.basis, "outcome")} of version ${s.version}">Score ${s.score}</span>`;

  // ---------- data ----------
  function need(fid, force = false) {
    if (dFid !== fid) { d = null; dFid = fid; dAt = 0; failed = ""; ed = null; sk = null; pl = null; }
    if (loading || (!force && Date.now() - dAt < 15000) || (d && (ed || sk || pl) && !force)) return;
    loading = true;
    api(`${L}/flows/${fid}`).then(x => { if (dFid === fid) { d = x; failed = ""; } }).catch(e => { if (dFid === fid) failed = e.message; })
      .finally(() => { dAt = Date.now(); loading = false; MiningWork.rerender(); });
  }
  function set(x) { if (x?.flow === dFid) { d = x; dAt = Date.now(); } MiningWork.rerender(); }
  async function act(btn, fn) {
    if (btn) { btn.disabled = true; btn.classList.add("loading"); }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.disabled = false; btn.classList.remove("loading"); } }
  }
  const call = (url, body, method = "POST") => api(`${L}${url}`, { method, body });

  // ---------- the tab ----------
  function page(bv) {
    if (!bv?.flow) return `<section class="mh-card"><p class="faint">Set up the Workflow first (Goal): loadouts belong to its agents.</p></section>`;
    need(bv.flow.id);
    if (failed && !d) return `<section class="mh-card"><p class="mh-err">${icon("alert")}${esc(failed)}</p></section>`;
    if (!d) return Loading.line("Opening the loadouts…");
    const nSugg = d.agents.reduce((n, a) => n + a.suggestions.filter(s => Object.keys(s.change).length).length, 0);
    const nImp = (d.improve?.items || []).filter(x => ["proposed", "better"].includes(x.status)).length;
    const secs = [["agents", "Agents", "users", nSugg], ["improve", "Improvements", "bulb", nImp], ["scores", "Scores", "chart", 0], ["library", "Library", "layers", 0], ["memory", "Memory", "book", d.notes.length]];
    const old = d.connected && !["skills", "mcp", "effort"].every(f => d.features.includes(f));
    return `<div class="ml-root" data-mbhold>
      <div class="ml-intro"><p>Each agent's <b>loadout</b>: its model, effort, memory, skills, plugins and MCP servers. Every change is a new version, every run records the version it ran with, and what the work led to (the review, the checks, merge or send back) is scored against it. New agents start on their role's template.</p>
        ${old ? `<p class="mb-warn small">${icon("alert")}The workbench on the host is older and ignores skills, MCP and effort: reinstall it with <code>sudo ./workbench/install.sh /home/thomas/bit</code>.</p>` : ""}
        ${!d.connected ? `<p class="mb-warn small">${icon("info")}The workbench doesn't answer right now: you can edit loadouts, but MCP servers can't be checked.</p>` : ""}</div>
      <nav class="ml-secs" role="tablist">${secs.map(([k, l, ic, n]) => `<button type="button" role="tab" data-mlsec="${k}" aria-pressed="${sec === k}">${icon(ic)}${l}${n ? `<span class="hq-n">${n}</span>` : ""}</button>`).join("")}</nav>
      ${{ agents, scores, library, memory, improve: () => MiningImprove.page(d) }[sec]()}</div>`;
  }

  // ---------- agents ----------
  function agents() {
    const cards = d.agents.map(card).join("");
    return `<div class="ml-cards">${cards}</div>${ed ? editor() : ""}`;
  }
  function card(a) {
    const lo = a.loadout, s = a.scores[0], fromPlug = new Set(lo.plugins.flatMap(p => PLUG()[p]?.skills || []));
    const sug = a.suggestions, imp = (d.improve?.items || []).find(x => x.agent_id === a.id && ["diagnosing", "proposed", "testing", "better"].includes(x.status));
    return `<article class="mh-card ml-card ${a.on ? "" : "off"} ${ed?.aid === a.id ? "editing" : ""}">
      <header>${av(a)}<span class="ml-who"><b>${esc(a.name)}</b><small>${ROLE[a.role]?.[0] || esc(a.role)}${a.version ? ` · version ${a.version}` : ""}${lo.default ? " · role template" : ""}${a.on ? "" : " · off"}</small></span>${s?.score == null && a.scores.find(x => x.score != null) ? (p => `<span class="hq-chip t-none" title="This version has no score yet: version ${p.version} scored ${p.score} from ${plural(p.basis, "outcome")}">v${p.version} scored ${p.score}</span>`)(a.scores.find(x => x.score != null)) : scoreChip(s)}</header>
      <dl class="ml-specs"><div><dt>Model</dt><dd>${esc(a.model)}</dd></div><div><dt>Effort</dt><dd>${esc(lo.effort || "default")}</dd></div>
        <div><dt>Memory</dt><dd title="${esc(d.memory[lo.memory] || "")}">${lo.memory === "off" ? "off" : lo.memory === "team" ? "own + team" : "own"}${a.notes ? ` · ${a.notes}` : ""}</dd></div><div><dt>Budget/run</dt><dd>${lo.budget ? money(lo.budget) : "flow's"}</dd></div></dl>
      <div class="ml-line"><span class="ml-lbl">${icon("sparkle")}Skills</span><span class="ml-chips">${a.resolved.skills.length ? a.resolved.skills.map(n => `<span class="ml-chip ${fromPlug.has(n) && !lo.skills.includes(n) ? "p" : ""}" title="${esc(SKILL()[n]?.description || "")}${fromPlug.has(n) && !lo.skills.includes(n) ? " (from a plugin)" : ""}">${esc(n)}</span>`).join("") : `<span class="faint small">none</span>`}</span></div>
      ${lo.plugins.length ? `<div class="ml-line"><span class="ml-lbl">${icon("layers")}Plugins</span><span class="ml-chips">${lo.plugins.map(p => `<span class="ml-chip k">${esc(PLUG()[p]?.title || p)}</span>`).join("")}</span></div>` : ""}
      <div class="ml-line"><span class="ml-lbl">${icon("server")}MCP</span><span class="ml-chips">${a.resolved.mcp.length ? a.resolved.mcp.map(m => `<span class="ml-chip m">${esc(m)}</span>`).join("") : `<span class="faint small">none</span>`}</span></div>
      ${sug.length ? `<ul class="ml-sugg">${sug.map(x => `<li><span>${icon(Object.keys(x.change).length ? "zap" : "info")}<b>${esc(x.title)}</b><small>${esc(x.why)}</small></span>
        ${Object.keys(x.change).length ? `<button type="button" class="btn sm" data-mlapply="${esc(x.id)}">${icon("check")}Apply</button>` : `<button type="button" class="btn sm" data-mledit="${a.id}">${icon("edit")}Set up</button>`}</li>`).join("")}</ul>` : ""}
      <footer><button type="button" class="btn sm ${ed?.aid === a.id ? "" : "primary"}" data-mledit="${a.id}">${icon("edit")}${ed?.aid === a.id ? "Close" : "Edit loadout"}</button>
        ${lo.default ? "" : `<button type="button" class="btn sm" data-mltemplate="${a.id}" title="Back to the ${esc(a.role)} template">${icon("undo")}Role template</button>`}
        ${a.role !== "engineer" || !d.improve ? "" : imp ? `<button type="button" class="btn sm" data-mlsec="improve" title="${esc(imp.change || "")}">${icon("bulb")}${imp.status === "diagnosing" ? "Being diagnosed…" : imp.status === "testing" ? "Trial running…" : "A proposal waits"}</button>`
          : `<button type="button" class="btn sm" data-miaskopen="${a.id}" title="The Improvement Engineer looks at its latest work that went wrong and proposes a change to this loadout">${icon("bulb")}Ask for an improvement</button>`}
        <button type="button" class="linkbtn small" data-mlscores="${a.id}">${a.scores.length ? `${plural(a.scores.length, "version")}, ${plural(a.scores.reduce((n, x) => n + x.runs, 0), "run")}` : "No versions yet"}</button></footer></article>`;
  }
  function editor() {
    const a = d.agents.find(x => x.id === ed.aid); if (!a) return "";
    const roleOf = s => (s.roles || []).includes(a.role);
    const skills = [...d.skills].sort((x, y) => (roleOf(y) - roleOf(x)) || x.name.localeCompare(y.name));
    const fromPlug = new Set([...ed.plugins].flatMap(p => PLUG()[p]?.skills || []));
    const kind = KIND[a.role] || "engineer", mcp = d.mcp.filter(m => (m.kinds || [kind]).includes(kind));
    const box = (grp, val, on, label, desc, extra = "") => `<label class="ml-opt ${on ? "on" : ""}"><input type="checkbox" data-mlbox="${grp}" value="${esc(val)}" ${on ? "checked" : ""}><span><b>${label}</b>${extra}<small>${desc}</small></span></label>`;
    return `<section class="mh-card ml-editor" aria-label="Edit ${esc(a.name)}'s loadout"><div class="mb-h"><h3>${av(a)}${esc(a.name)}'s loadout</h3><button type="button" class="iconbtn" data-mledit="${a.id}" aria-label="Close">${icon("close")}</button></div>
      <div class="ml-ed-grid">
        <label class="in"><span>Model</span><select data-mlf="model">${d.models.map(m => `<option ${ed.model === m ? "selected" : ""}>${m}</option>`).join("")}</select></label>
        <label class="in"><span>Effort</span><select data-mlf="effort">${d.efforts.map(e => `<option value="${e}" ${ed.effort === e ? "selected" : ""}>${e || "Claude Code's default"}</option>`).join("")}</select></label>
        <label class="in"><span>Budget per run (USD)</span><input type="number" min="0.1" max="5" step="0.1" data-mlf="budget" value="${ed.budget ?? ""}" placeholder="the flow's"></label>
        <label class="in"><span>Memory</span><select data-mlf="memory">${Object.entries(d.memory).map(([k, l]) => `<option value="${k}" ${ed.memory === k ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <label class="in"><span>Role and instructions (part of every prompt)</span><textarea rows="3" data-mlf="instructions">${esc(ed.instructions)}</textarea></label>
      <h4>${icon("layers")}Plugins</h4><p class="faint small">A plugin is a bundle of skills and MCP servers. Make your own in Library.</p>
      <div class="ml-opts">${d.plugins.map(p => box("plugins", p.name, ed.plugins.has(p.name), esc(p.title), esc(p.description || ""), `<span class="ml-sub">${[...p.skills, ...p.mcp.map(m => `MCP ${m}`)].map(esc).join(" · ")}</span>`)).join("")}</div>
      <h4>${icon("sparkle")}Skills</h4><p class="faint small">Claude Code loads them as skills and uses each when its description fits the work. Skills for ${esc(ROLE[a.role]?.[0].toLowerCase() || a.role)}s come first.</p>
      <div class="ml-opts">${skills.map(s => fromPlug.has(s.name) && !ed.skills.has(s.name)
        ? `<div class="ml-opt in-plug"><span>${icon("check")}</span><span><b>${esc(s.title)}</b><span class="ml-sub">${esc(s.name)} · from a plugin</span><small>${esc(s.description)}</small></span></div>`
        : box("skills", s.name, ed.skills.has(s.name), esc(s.title), esc(s.description), `<span class="ml-sub">${esc(s.name)}${s.builtin ? "" : " · yours"}${roleOf(s) ? ` · for ${esc(a.role)}s` : ""}</span>`)).join("")}</div>
      <h4>${icon("server")}MCP servers</h4>
      ${mcp.length ? `<div class="ml-opts">${mcp.map(m => box("mcp", m.id, ed.mcp.has(m.id), esc(m.label), esc(m.note || ""), `<span class="ml-sub">${esc(m.id)}</span>`)).join("")}</div>`
        : `<p class="faint small">The workbench offers no MCP server${d.mcp.length ? ` to ${esc(a.role)}s` : ""}. An administrator adds them to <code>/etc/axor-workbench.json</code> under <code>"mcp"</code> (id, command, args, the kinds of run allowed) and restarts <code>axor-workbench</code>. Agents can never add one themselves.</p>`}
      <label class="in ml-note"><span>What you're trying (shown in the version history)</span><input data-mlf="note" value="${esc(ed.note)}" placeholder="e.g. opus for the hard refactors"></label>
      <div class="row"><button type="button" class="btn primary" data-mlsave>${icon("check")}Save as a new version</button><button type="button" class="btn" data-mledit="${a.id}">Cancel</button>
        <span class="faint small">Applies from the next run. Runs already going keep what they started with.</span></div></section>`;
  }
  function openEditor(a) {
    const lo = a.loadout;
    ed = { aid: a.id, model: a.model, instructions: a.instructions, effort: lo.effort || "", budget: lo.budget, memory: lo.memory,
      skills: new Set(lo.skills), plugins: new Set(lo.plugins), mcp: new Set(lo.mcp), note: "" };
  }
  async function apply(btn, a, x) {
    if (x.change.restore) { const nv = await act(btn, () => call(`/agents/${a.id}/restore`, { version: x.change.restore })); if (nv) { set(nv); Auth.toast(`${a.name} is back on version ${x.change.restore}`); } return; }
    const lo = a.loadout, c = x.change;
    const body = { model: c.model ?? a.model, skills: c.skills ?? lo.skills, plugins: c.plugins ?? lo.plugins, mcp: lo.mcp, memory: c.memory ?? lo.memory, effort: c.effort ?? lo.effort ?? "",
      budget: c.budget ?? lo.budget, note: `Suggestion: ${x.title}`, source: "suggestion" };
    const nv = await act(btn, () => call(`/agents/${a.id}`, body, "PUT"));
    if (nv) { set(nv); Auth.toast(`Applied to ${a.name}: a new version`); }
  }

  // ---------- scores ----------
  function scores() {
    const A = Object.fromEntries(d.agents.map(a => [a.id, a]));
    const rows = d.agents.map(a => `<section class="mh-card ml-score ${shown.has(`s${a.id}`) ? "" : ""}" id="ml-s${a.id}"><div class="mb-h"><h3>${av(a)}${esc(a.name)}</h3>${scoreChip(a.scores[0])}</div>
      ${a.scores.length ? `<div class="ml-table-wrap"><table class="ml-table"><thead><tr><th>Version</th><th>Runs</th><th>Cost</th>${a.role === "reviewer" ? "" : `<th title="Eval tasks solved against the base the task started from: tasks that gained, kept, lost">Eval vs base</th>`}${a.role === "director" ? "<th>Tasks kept</th>" : "<th>Review</th><th>Checks</th><th>Merged</th><th>Sent back</th>"}<th>Score</th><th></th></tr></thead><tbody>
        ${a.scores.map((s, i) => `<tr class="${i === 0 ? "cur" : ""}"><td><b>v${s.version}</b>${i === 0 ? ` <span class="hq-chip t-run">now</span>` : ""}<small>${esc(s.note || "")} · ${esc(SRC[s.source] || s.source)} · ${ago(s.created)}</small><small class="ml-snap">${esc(s.snap.model)}${s.snap.effort ? ` · ${esc(s.snap.effort)}` : ""} · ${plural(s.snap.skills.length + s.snap.plugins.length, "skill/plugin", "s")}${s.snap.mcp.length ? ` · MCP ${s.snap.mcp.map(esc).join(", ")}` : ""} · memory ${esc(s.snap.memory)}</small></td>
          <td>${s.runs}${s.failed ? ` <span class="ml-bad">(${s.failed} failed)</span>` : ""}</td><td>${money(s.cost)}${s.avg_cost != null ? `<small>${money(s.avg_cost)}/run</small>` : ""}</td>
          ${a.role === "reviewer" ? "" : `<td>${s.eval_up + s.eval_same + s.eval_down ? `<span class="ml-good">${s.eval_up} ↑</span> ${s.eval_same} = <span class="ml-bad">${s.eval_down} ↓</span><small>${s.eval_net > 0 ? "+" : ""}${s.eval_net} task${Math.abs(s.eval_net) === 1 ? "" : "s"} in all</small>` : "–"}</td>`}
          ${a.role === "director" ? `<td>${s.proposed ? `${s.kept} of ${s.proposed}` : "–"}</td>`
            : `<td>${s.approve + s.changes ? `<span class="ml-good">${s.approve} ✓</span> <span class="ml-bad">${s.changes} ✗</span>` : "–"}</td><td>${s.check_pass + s.check_fail ? `<span class="ml-good">${s.check_pass} pass</span> <span class="ml-bad">${s.check_fail} fail</span>` : "–"}</td><td>${s.merged || "–"}</td><td>${s.sent_back || "–"}${s.dropped ? `<small>${s.dropped} dropped</small>` : ""}</td>`}
          <td>${s.score ?? "–"}${s.score != null ? `<small>${plural(s.basis, "outcome")}</small>` : ""}</td>
          <td>${i > 0 ? `<button type="button" class="btn sm" data-mlrestore="${a.id}" data-v="${s.version}">${icon("undo")}Use again</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="faint small">No runs yet.</p>`}</section>`).join("");
    const runs = d.runs.length ? `<section class="mh-card"><h3>${icon("clock")}Recent runs and what each got</h3><div class="ml-table-wrap"><table class="ml-table"><thead><tr><th>Run</th><th>Agent</th><th>Status</th><th>Cost</th><th>Given</th></tr></thead><tbody>
      ${d.runs.map(r => `<tr><td>${esc(r.label || r.kind)}<small>${esc(r.kind)} · ${ago(r.created)}</small></td><td>${esc(A[r.agent_id]?.name || "?")} <small>v${r.version}</small></td><td>${esc(r.status || "")}</td><td>${money(r.cost)}</td>
        <td><small>${[r.applied.skills?.length ? plural(r.applied.skills.length, "skill") : "", r.applied.mcp?.length ? `MCP ${r.applied.mcp.map(esc).join(", ")}` : "", r.applied.effort ? `effort ${esc(r.applied.effort)}` : "", r.applied.memory ? "notes" : ""].filter(Boolean).join(" · ") || "nothing extra"}${r.applied.dropped?.length ? ` <span class="ml-bad">· without ${r.applied.dropped.map(esc).join(", ")} (old workbench)</span>` : ""}</small></td></tr>`).join("")}</tbody></table></div></section>` : "";
    return `<p class="faint small ml-how">How the score works: engineers by the eval against the base their task started from (50%: a task that gained eval tasks counts fully, one that kept the score half), checks passed (20%), work merged rather than sent back or dropped (15%), the reviewer's approvals (10%) and runs that finished (5%); the Director by the eval of the tasks it planned and the share of them you kept. An eval compared with another commit's base isn't counted. It shows once there are 3 outcomes, and compares versions of the same agent, not agents with each other.</p>${rows}${runs}`;
  }

  // ---------- library ----------
  function library() {
    const skills = d.skills, plugs = d.plugins;
    const skForm = sk ? `<div class="ml-form"><h4>${sk.id ? "Edit skill" : "New skill"}</h4>
      <div class="ml-ed-grid"><label class="in"><span>Name (lower-case, dashes)</span><input data-mlsk="name" value="${esc(sk.name)}" placeholder="calc-rules"></label><label class="in"><span>Title</span><input data-mlsk="title" value="${esc(sk.title)}"></label></div>
      <label class="in"><span>When to use it (Claude Code reads this to decide)</span><input data-mlsk="description" value="${esc(sk.description)}" placeholder="Use when changing the scoring code."></label>
      <div class="ml-roles">${Object.entries(ROLE).map(([r, [l]]) => `<label><input type="checkbox" data-mlskrole value="${r}" ${sk.roles.includes(r) ? "checked" : ""}> For ${l.toLowerCase()}s</label>`).join("")}</div>
      <label class="in"><span>The skill (Markdown: steps, rules, examples)</span><textarea rows="10" data-mlsk="body">${esc(sk.body)}</textarea></label>
      <div class="row"><button type="button" class="btn primary sm" data-mlsksave>${icon("check")}Save skill</button><button type="button" class="btn sm" data-mlskcancel>Cancel</button></div></div>` : "";
    const plForm = pl ? `<div class="ml-form"><h4>${pl.id ? "Edit plugin" : "New plugin"}</h4>
      <div class="ml-ed-grid"><label class="in"><span>Name</span><input data-mlpl="name" value="${esc(pl.name)}" placeholder="my-kit"></label><label class="in"><span>Title</span><input data-mlpl="title" value="${esc(pl.title)}"></label></div>
      <label class="in"><span>What it's for</span><input data-mlpl="description" value="${esc(pl.description)}"></label>
      <p class="small"><b>Skills</b></p><div class="ml-pick">${skills.map(s => `<label><input type="checkbox" data-mlplbox="skills" value="${esc(s.name)}" ${pl.skills.includes(s.name) ? "checked" : ""}> ${esc(s.name)}</label>`).join("")}</div>
      <p class="small"><b>MCP servers</b></p>${d.mcp.length ? `<div class="ml-pick">${d.mcp.map(m => `<label><input type="checkbox" data-mlplbox="mcp" value="${esc(m.id)}" ${pl.mcp.includes(m.id) ? "checked" : ""}> ${esc(m.label)}</label>`).join("")}</div>` : `<p class="faint small">The workbench offers none.</p>`}
      <div class="row"><button type="button" class="btn primary sm" data-mlplsave>${icon("check")}Save plugin</button><button type="button" class="btn sm" data-mlplcancel>Cancel</button></div></div>` : "";
    return `<div class="ml-lib"><section class="mh-card"><div class="mb-h"><h3>${icon("sparkle")}Skills</h3><button type="button" class="btn sm" data-mlsknew>${icon("plus")}New skill</button></div>
        <p class="faint small">A skill is written guidance Claude Code pulls in when its description fits the work. It can't run anything: agents still have no shell.</p>${skForm}
        <ul class="ml-items">${skills.map(s => `<li><button type="button" class="ml-item" data-mlopen="sk-${esc(s.name)}" aria-expanded="${shown.has(`sk-${s.name}`)}"><b>${esc(s.title)}</b><span class="ml-sub">${esc(s.name)} · ${s.builtin ? "built in" : "yours"}${s.roles?.length ? ` · ${s.roles.map(esc).join(", ")}` : ""}</span><small>${esc(s.description)}</small></button>
          ${shown.has(`sk-${s.name}`) ? `<pre class="ml-body">${esc(s.body)}</pre><div class="row">${s.builtin ? `<button type="button" class="btn sm" data-mlskcopy="${esc(s.name)}">${icon("copy")}Copy to edit</button>` : `<button type="button" class="btn sm" data-mlskedit="${esc(s.name)}">${icon("edit")}Edit</button><button type="button" class="btn sm mw-danger" data-mlskdel="${s.id}">${icon("trash")}Delete</button>`}</div>` : ""}</li>`).join("")}</ul></section>
      <section class="mh-card"><div class="mb-h"><h3>${icon("layers")}Plugins</h3><button type="button" class="btn sm" data-mlplnew>${icon("plus")}New plugin</button></div>
        <p class="faint small">A bundle of skills and MCP servers to give an agent in one tick. Claude Code plugins with hooks aren't loaded: hooks would run as root on the host.</p>${plForm}
        <ul class="ml-items">${plugs.map(p => `<li><div class="ml-item"><b>${esc(p.title)}</b><span class="ml-sub">${esc(p.name)} · ${p.builtin ? "built in" : "yours"}</span><small>${esc(p.description || "")}</small>
          <span class="ml-chips">${p.skills.map(n => `<span class="ml-chip">${esc(n)}</span>`).join("")}${p.mcp.map(m => `<span class="ml-chip m">${esc(m)}</span>`).join("")}</span></div>
          ${p.builtin ? "" : `<div class="row"><button type="button" class="btn sm" data-mlpledit="${esc(p.name)}">${icon("edit")}Edit</button><button type="button" class="btn sm mw-danger" data-mlpldel="${p.id}">${icon("trash")}Delete</button></div>`}</li>`).join("")}</ul></section>
      <section class="mh-card"><h3>${icon("server")}MCP servers on the workbench</h3>
        ${d.mcp.length ? `<ul class="ml-items">${d.mcp.map(m => `<li><div class="ml-item"><b>${esc(m.label)}</b><span class="ml-sub">${esc(m.id)} · for ${(m.kinds || []).map(esc).join(", ")}</span><small>${esc(m.note || "")}</small></div></li>`).join("")}</ul>` : `<p class="faint small">None yet.</p>`}
        <p class="faint small">Only an administrator adds them, on the host, in <code>/etc/axor-workbench.json</code>: <code>"mcp": {"id": {"label": "…", "command": "…", "args": [], "env": {}, "kinds": ["engineer"]}}</code>, then <code>systemctl restart axor-workbench</code>. A server runs as root with the agent's run, so add only ones you trust.</p></section></div>`;
  }

  // ---------- memory ----------
  function memory() {
    const A = Object.fromEntries(d.agents.map(a => [a.id, a]));
    const list = d.notes.filter(n => memFor === "all" || (memFor === "team" ? n.agent_id == null : n.agent_id === +memFor));
    return `<section class="mh-card ml-mem"><div class="mb-h"><h3>${icon("book")}Memory</h3>
        <select data-mlmemfor aria-label="Whose notes"><option value="all" ${memFor === "all" ? "selected" : ""}>Everyone's</option><option value="team" ${memFor === "team" ? "selected" : ""}>The team's</option>${d.agents.map(a => `<option value="${a.id}" ${memFor === String(a.id) ? "selected" : ""}>${esc(a.name)}'s</option>`).join("")}</select></div>
      <p class="faint small">An agent with memory on gets its newest notes in its prompt (and the team's, when set to “own and team”). Notes are written as the work goes: what a review asked for, why you sent work back, which check failed, what got merged, which planned tasks you kept. You can add, edit, share with the team or delete any of them.</p>
      <div class="ml-addnote"><select data-mlnf="agent" aria-label="For">${[["", "For the team"], ...d.agents.map(a => [a.id, `For ${a.name}`])].map(([v, l]) => `<option value="${v}" ${String(noteDraft.agent ?? "") === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
        <input data-mlnf="text" value="${esc(noteDraft.text || "")}" placeholder="e.g. The eval penalises answers over 2 000 tokens"><button type="button" class="btn sm primary" data-mlnoteadd>${icon("plus")}Add</button></div>
      ${list.length ? `<ul class="ml-notes">${list.map(n => `<li>${n.agent_id == null ? `<span class="hq-chip t-run">Team</span>` : `<span class="hq-chip t-none">${esc(A[n.agent_id]?.name || "?")}</span>`}
        ${shown.has(`n${n.id}`) ? `<textarea rows="3" data-mlnedit="${n.id}">${esc(noteDraft[`n${n.id}`] ?? n.text)}</textarea>` : `<span class="ml-ntext">${esc(n.text)}<small>${n.source === "you" ? "by you" : "written by the Workflow"} · ${ago(n.created)}</small></span>`}
        <span class="row">${shown.has(`n${n.id}`) ? `<button type="button" class="btn sm primary" data-mlnsave="${n.id}">${icon("check")}Save</button>` : `<button type="button" class="iconbtn" data-mlnopen="${n.id}" aria-label="Edit" title="Edit">${icon("edit")}</button>`}
          ${n.agent_id != null ? `<button type="button" class="iconbtn" data-mlnteam="${n.id}" aria-label="Share with the team" title="Share with the team">${icon("users")}</button>` : ""}
          <button type="button" class="iconbtn" data-mlndel="${n.id}" aria-label="Delete" title="Delete">${icon("trash")}</button></span></li>`).join("")}</ul>` : `<p class="faint small">No notes yet.</p>`}</section>`;
  }

  // ---------- events (mining-bench.js forwards its root's events) ----------
  function wire(el) {
    MiningImprove.wire(el);
    el.addEventListener("input", e => {
      const t = e.target;
      if (t.matches("[data-mlf]") && ed) ed[t.dataset.mlf] = t.dataset.mlf === "budget" ? (t.value === "" ? null : +t.value) : t.value;
      if (t.matches("[data-mlsk]") && sk) sk[t.dataset.mlsk] = t.value;
      if (t.matches("[data-mlpl]") && pl) pl[t.dataset.mlpl] = t.value;
      if (t.matches("[data-mlnf]")) noteDraft[t.dataset.mlnf] = t.value;
      if (t.matches("[data-mlnedit]")) noteDraft[`n${t.dataset.mlnedit}`] = t.value;
    });
    el.addEventListener("change", e => {
      const t = e.target;
      if (t.matches("[data-mlbox]") && ed) { ed[t.dataset.mlbox][t.checked ? "add" : "delete"](t.value); t.closest(".ml-opt")?.classList.toggle("on", t.checked); if (t.dataset.mlbox === "plugins") MiningWork.rerender(); }
      if (t.matches("[data-mlskrole]") && sk) sk.roles = t.checked ? [...sk.roles, t.value] : sk.roles.filter(r => r !== t.value);
      if (t.matches("[data-mlplbox]") && pl) pl[t.dataset.mlplbox] = t.checked ? [...pl[t.dataset.mlplbox], t.value] : pl[t.dataset.mlplbox].filter(x => x !== t.value);
      if (t.matches("[data-mlmemfor]")) { memFor = t.value; t.blur(); MiningWork.rerender(); }
      if (t.matches("select[data-mlf]")) t.blur();
    });
    el.addEventListener("click", async e => {
      const t = e.target, A = () => Object.fromEntries((d?.agents || []).map(a => [a.id, a]));
      const s = t.closest("[data-mlsec]"); if (s) { sec = s.dataset.mlsec; return MiningWork.rerender(); }
      const edb = t.closest("[data-mledit]");
      if (edb) { const a = A()[+edb.dataset.mledit]; if (ed?.aid === a.id) ed = null; else openEditor(a); MiningWork.rerender(); if (ed) requestAnimationFrame(() => el.querySelector(".ml-editor")?.scrollIntoView({ block: "nearest", behavior: "smooth" })); return; }
      if (t.closest("[data-mlsave]") && ed) {
        const body = { model: ed.model, instructions: ed.instructions, skills: [...ed.skills], plugins: [...ed.plugins], mcp: [...ed.mcp], memory: ed.memory, effort: ed.effort, budget: ed.budget || null, note: ed.note, source: "manual" };
        const name = A()[ed.aid]?.name, nv = await act(t.closest("[data-mlsave]"), () => call(`/agents/${ed.aid}`, body, "PUT"));
        if (nv) { ed = null; set(nv); Auth.toast(`${name}'s loadout saved`); }
        return;
      }
      const tp = t.closest("[data-mltemplate]");
      if (tp) { const a = A()[+tp.dataset.mltemplate]; const nv = await act(tp, () => call(`/agents/${a.id}/template`)); if (nv) { if (ed?.aid === a.id) ed = null; set(nv); Auth.toast(`${a.name} is back on the ${a.role} template`); } return; }
      const ap = t.closest("[data-mlapply]");
      if (ap) { for (const a of d.agents) { const x = a.suggestions.find(y => y.id === ap.dataset.mlapply); if (x) return apply(ap, a, x); } return; }
      const sc = t.closest("[data-mlscores]"); if (sc) { sec = "scores"; MiningWork.rerender(); requestAnimationFrame(() => document.getElementById(`ml-s${sc.dataset.mlscores}`)?.scrollIntoView({ block: "start", behavior: "smooth" })); return; }
      const rs = t.closest("[data-mlrestore]");
      if (rs) { const a = A()[+rs.dataset.mlrestore]; const nv = await act(rs, () => call(`/agents/${a.id}/restore`, { version: +rs.dataset.v })); if (nv) { set(nv); Auth.toast(`${a.name} uses version ${rs.dataset.v}'s loadout again (as a new version)`); } return; }
      // library
      const op = t.closest("[data-mlopen]"); if (op) { const k = op.dataset.mlopen; shown.has(k) ? shown.delete(k) : shown.add(k); return MiningWork.rerender(); }
      if (t.closest("[data-mlsknew]")) { sk = { id: null, name: "", title: "", description: "", body: "", roles: [] }; return MiningWork.rerender(); }
      const cp = t.closest("[data-mlskcopy]"); if (cp) { const s0 = SKILL()[cp.dataset.mlskcopy]; sk = { id: null, name: `my-${s0.name}`, title: s0.title, description: s0.description, body: s0.body, roles: [...(s0.roles || [])] }; MiningWork.rerender(); return requestAnimationFrame(() => el.querySelector(".ml-form")?.scrollIntoView({ block: "nearest", behavior: "smooth" })); }
      const se = t.closest("[data-mlskedit]"); if (se) { const s0 = SKILL()[se.dataset.mlskedit]; sk = { id: s0.id, name: s0.name, title: s0.title, description: s0.description, body: s0.body, roles: [...(s0.roles || [])] }; MiningWork.rerender(); return requestAnimationFrame(() => el.querySelector(".ml-form")?.scrollIntoView({ block: "nearest", behavior: "smooth" })); }
      if (t.closest("[data-mlskcancel]")) { sk = null; return MiningWork.rerender(); }
      if (t.closest("[data-mlsksave]") && sk) {
        const r = await act(t.closest("[data-mlsksave]"), () => sk.id ? call(`/skills/${sk.id}`, sk, "PUT") : call("/skills", sk));
        if (r) { Auth.toast(`Skill ${sk.name} saved`); sk = null; need(dFid, true); }
        return;
      }
      const sd = t.closest("[data-mlskdel]");
      if (sd) return UI.confirm({ title: "Delete this skill?", body: "It comes out of every loadout and plugin that uses it; their next run is a new version.", ok: "Delete",
        run: async () => { await call(`/skills/${sd.dataset.mlskdel}`, undefined, "DELETE"); need(dFid, true); } }).catch(err);
      if (t.closest("[data-mlplnew]")) { pl = { id: null, name: "", title: "", description: "", skills: [], mcp: [] }; return MiningWork.rerender(); }
      const pe = t.closest("[data-mlpledit]"); if (pe) { const p0 = PLUG()[pe.dataset.mlpledit]; pl = { id: p0.id, name: p0.name, title: p0.title, description: p0.description, skills: [...p0.skills], mcp: [...p0.mcp] }; return MiningWork.rerender(); }
      if (t.closest("[data-mlplcancel]")) { pl = null; return MiningWork.rerender(); }
      if (t.closest("[data-mlplsave]") && pl) {
        const r = await act(t.closest("[data-mlplsave]"), () => pl.id ? call(`/plugins/${pl.id}`, pl, "PUT") : call("/plugins", pl));
        if (r) { Auth.toast(`Plugin ${pl.name} saved`); pl = null; need(dFid, true); }
        return;
      }
      const pd = t.closest("[data-mlpldel]");
      if (pd) return UI.confirm({ title: "Delete this plugin?", body: "It comes out of every loadout that uses it.", ok: "Delete",
        run: async () => { await call(`/plugins/${pd.dataset.mlpldel}`, undefined, "DELETE"); need(dFid, true); } }).catch(err);
      // memory
      if (t.closest("[data-mlnoteadd]")) {
        const text = (noteDraft.text || "").trim(); if (text.length < 2) return Auth.toast("Write the note first");
        const nv = await act(t.closest("[data-mlnoteadd]"), () => call(`/flows/${dFid}/notes`, { text, agent: noteDraft.agent ? +noteDraft.agent : null }));
        if (nv) { noteDraft.text = ""; set(nv); Auth.toast("Note added"); }
        return;
      }
      const no = t.closest("[data-mlnopen]"); if (no) { shown.add(`n${no.dataset.mlnopen}`); return MiningWork.rerender(); }
      const ns = t.closest("[data-mlnsave]");
      if (ns) { const id = ns.dataset.mlnsave, text = (noteDraft[`n${id}`] ?? d.notes.find(n => n.id === +id)?.text ?? "").trim(); if (text.length < 2) { shown.delete(`n${id}`); return MiningWork.rerender(); }
        const nv = await act(ns, () => call(`/notes/${id}`, { text }, "PATCH")); if (nv) { shown.delete(`n${id}`); delete noteDraft[`n${id}`]; set(nv); } return; }
      const nt = t.closest("[data-mlnteam]"); if (nt) { const nv = await act(nt, () => call(`/notes/${nt.dataset.mlnteam}`, { team: true }, "PATCH")); if (nv) { set(nv); Auth.toast("Shared with the team"); } return; }
      const nd = t.closest("[data-mlndel]"); if (nd) { const nv = await act(nd, () => call(`/notes/${nd.dataset.mlndel}`, undefined, "DELETE")); if (nv) set(nv); return; }
    });
  }
  // the Workflow's view changed (an agent added, a run finished): fetch again unless you're editing
  function stale() { dAt = 0; }
  function show(s) { sec = s; dAt = 0; }  // the Workflow's "What happens now" opens a part (Improvements)
  return { page, wire, stale, show, set, data: () => d };
})();
