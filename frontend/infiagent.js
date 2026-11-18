/* Long tasks (infiagent.py): InfiAgent's file-centric agents. The task list, and one task: its status and token meter,
   the agent-call tree (Alpha → domain → atomic) with each agent's tool calls and thinking rewrites, the selected agent's
   thinking record (to-do list, file descriptions, pinned state, next steps), its action window and earlier records, the
   live trace, the result, the workspace's files and the coverage audit. While the page is open it follows the task over
   server-sent events. */
const InfiAgent = (() => {
  let home = null, tid = null, d = null, wired = false, es = null, timer = null, models = null;
  let sel = null, frame = null, cov = null, covPattern = "", preview = null;
  const root = () => $("#infiagent");
  const shown = () => !$("#view-infiagent").hidden;
  const err = e => e && Auth.toast(e.message);
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 1)}k` : fmtNum(n || 0, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const role = k => (home?.roles || []).find(r => r.key === k) || { key: k, name: k, title: "", icon: "bot", color: "slate", level: 0 };
  const av = (r, size = "sm") => `<span class="av ${size} c-${esc(r.color)}" aria-hidden="true">${icon(r.icon)}</span>`;
  const chip = (tone, text, ic) => `<span class="ia-chip t-${tone}">${ic ? icon(ic) : ""}${esc(text)}</span>`;
  const TSTATUS = { running: ["run", "Running", "play"], paused: ["warn", "Paused", "hand"], done: ["ok", "Done", "check"], failed: ["bad", "Failed", "alert"],
    cancelled: ["off", "Cancelled", "stop"], idle: ["wait", "Starting", "clock"] };
  const FSTATUS = { running: ["run", "Working"], done: ["ok", "Done"], failed: ["bad", "Failed"], stopped: ["warn", "Stopped at its limit"], cancelled: ["off", "Cancelled"] };
  const TODO = { done: ["ok", "check"], ongoing: ["run", "cycle"], waiting: ["wait", "clock"] };
  const TOOL_ICON = { list_files: "folder", read_file: "file", write_file: "edit", append_file: "plus", search_files: "search", answer_from_documents: "book",
    subnet_data: "chart", final_output: "check", "(reply)": "chat" };
  const EXAMPLES = ["Read every paper in docs/, score each against rubric.md and write a review table to review.md",
    "Compare the ten biggest subnets by emissions and write a newcomer's guide to guide.md",
    "Turn the notes in notes/ into a structured report with a summary and open questions"];

  // ---------- loading ----------
  async function open() {
    wire();
    if (tid === null) tid = store.get("ia.tid", null);
    if (!home) root().innerHTML = `<h1 class="page">Long tasks</h1>${Loading.line("Loading your tasks…")}`;
    try { home = await api("/api/infiagent"); }
    catch (e) { root().innerHTML = `<h1 class="page">Long tasks</h1><div class="empty">${esc(e.message)}</div>`; return; }
    if (tid != null && !home.tasks.some(t => t.id === tid)) tid = null;
    if (tid == null) tid = home.tasks[0]?.id ?? null;
    if (tid && (!d || d.task.id !== tid)) d = await api(`/api/infiagent/tasks/${tid}`).catch(() => null);
    render(); follow();
  }
  function stop() { es?.close(); es = null; clearTimeout(timer); }
  function follow() {
    es?.close(); es = null; clearTimeout(timer);
    if (!shown()) return;
    es = new EventSource(`/api/infiagent/stream${tid ? `?task=${tid}` : ""}`);
    es.addEventListener("state", e => {
      const s = JSON.parse(e.data);
      home.tasks = s.tasks;
      if (s.state && s.state.task.id === tid) {
        const byId = new Map((d?.actions || []).map(x => [x.id, x])), fresh = s.state.actions;
        for (const a of fresh) byId.set(a.id, a);  // new steps, and earlier ones whose result has arrived
        const changed = d && JSON.stringify(d.frames) !== JSON.stringify(s.state.frames);
        d = { ...s.state, actions: [...byId.values()].sort((a, b) => a.id - b.id).slice(-200) };
        if (changed || fresh.length) { loadFrame(true); if (cov) loadCoverage(); }
      }
      render();
    });
    es.addEventListener("gone", () => { tid = null; d = null; store.set("ia.tid", null); open(); });
    es.addEventListener("auth", stop);
    es.onerror = () => { es?.close(); es = null; clearTimeout(timer); timer = setTimeout(() => { if (shown()) follow(); }, 5000); };
  }
  async function select(id) {
    tid = id; store.set("ia.tid", id); d = null; sel = null; frame = null; cov = null; preview = null;
    render();
    try { d = await api(`/api/infiagent/tasks/${id}`); } catch (e) { err(e); }
    render(); follow();
  }
  // the agent whose record is shown: the one you picked, else the deepest agent at work, else the run's Alpha
  function focus() {
    if (!d) return null;
    const run = d.frames.filter(f => f.run_id === d.task.run_id);
    if (sel && d.frames.some(f => f.id === sel)) return sel;
    const working = run.filter(f => f.status === "running");
    return (working[working.length - 1] || run[0] || d.frames[d.frames.length - 1])?.id ?? null;
  }
  let frameBusy = false, frameFailed = null;
  async function loadFrame(quiet) {
    const fid = focus();
    if (!fid || frameBusy || (quiet && frameFailed === fid)) return;  // a record that failed to load isn't retried on every render
    frameBusy = true;
    try { frame = await api(`/api/infiagent/tasks/${tid}/frames/${fid}`); frameFailed = null; } catch (e) { frameFailed = fid; if (!quiet) err(e); }
    frameBusy = false;
    render();
  }
  async function loadCoverage() {
    try { cov = await api(`/api/infiagent/tasks/${tid}/coverage?pattern=${encodeURIComponent(covPattern)}`); } catch (e) { err(e); }
    render();
  }

  // ---------- frame ----------
  function put(el, html) {
    if (!el || el.dataset.html === html) return;
    const typed = $$("[data-keep] input, [data-keep] textarea", el).filter(x => x.dataset.dirty).map(x => ({ name: x.name, value: x.value, focus: document.activeElement === x }));
    el.innerHTML = html; el.dataset.html = html;
    for (const t of typed) { const x = $(`[data-keep] [name="${t.name}"]`, el); if (!x) continue; x.value = t.value; x.dataset.dirty = "1"; if (t.focus) x.focus(); }
  }
  function render() {
    if (!home) return;
    if (!$(".ia-body", root())) root().innerHTML = `<div class="ia-top"><div><h1 class="page">Long tasks</h1>
        <p class="lead">Agents for work that takes hundreds of steps, after InfiAgent (ACL 2026). The task's state lives in a workspace of files, and each agent's prompt is rebuilt at every step from a thinking record and a short window of its latest actions, so it never grows however long the task runs. An Alpha agent plans and delegates to domain agents, which call atomic agents; documents are read outside the agents' context.</p></div>
        <div class="ia-actions"></div></div><div class="ia-body"><aside class="ia-list" aria-label="Tasks"></aside><section class="ia-detail"></section></div>`;
    put($(".ia-actions", root()), `<button type="button" class="btn primary" data-ia="new" ${home.model_ready ? "" : "disabled title=\"Connect a model in Agents → Models first\""}>${icon("plus")}New task</button>`);
    put($(".ia-list", root()), listHtml());
    put($(".ia-detail", root()), detailHtml());
    $$("time[data-ts]", root()).forEach(t => { t.textContent = ago(+t.dataset.ts); });
  }
  function listHtml() {
    if (!home.tasks.length) return `<p class="faint small ia-pad">No tasks yet.</p>`;
    return `<ol class="ia-tlist">${home.tasks.map(t => {
      const [tone, label] = TSTATUS[t.status] || ["wait", t.status];
      return `<li><button type="button" class="ia-trow ${t.id === tid ? "on" : ""}" data-task="${t.id}" aria-pressed="${t.id === tid}">
        <span class="ia-dot t-${tone}" aria-hidden="true"></span><span class="ia-trow-t">${esc(t.title)}</span>
        <span class="ia-trow-m">${esc(t.status === "running" && t.doing ? t.doing : label)} · ${plural(t.actions, "step")} · ${short(t.tokens)} tokens · <time data-ts="${t.created}">${ago(t.created)}</time></span></button></li>`; }).join("")}</ol>`;
  }
  function detailHtml() {
    if (!tid) return welcome();
    if (!d || d.task.id !== tid) return `<div class="ia-card">${Loading.line("Opening the task…")}</div>`;
    return [header(), `<div class="ia-grid"><div class="ia-col">${treeCard()}${recordCard()}${traceCard()}</div><div class="ia-col">${resultCard()}${filesCard()}${coverageCard()}${runsCard()}</div></div>`].join("");
  }
  function welcome() {
    return `<div class="ia-card ia-welcome"><h2>Start a long task</h2>
      <p>Describe the work and attach the documents it needs. The Alpha agent writes a plan to the workspace and hands subtasks to domain agents (data collection, analysis, coding, writing), checking each result. Everything the agents learn goes into files, so a task can go through dozens of documents without losing its place, and it can be paused, resumed, or picked up again after a restart from its last checkpoint.</p>
      <p class="faint small">Agents read and write only the task's workspace and AXoR's subnet data. They can't run code or browse the web.</p>
      <ul class="ia-examples">${EXAMPLES.map(x => `<li><button type="button" class="linkbtn" data-example="${esc(x)}">${esc(x)}</button></li>`).join("")}</ul>
      <button type="button" class="btn primary" data-ia="new" ${home.model_ready ? "" : "disabled"}>${icon("plus")}New task</button>
      ${home.model_ready ? "" : `<p class="faint small">An administrator needs to connect a model in Agents → Models first.</p>`}</div>`;
  }
  function header() {
    const t = d.task, [tone, label, ic] = TSTATUS[t.status] || ["wait", t.status, "info"];
    const used = Math.min(100, t.tokens / t.budget * 100);
    const btn = (act, ic2, text, cls = "") => `<button type="button" class="btn ${cls}" data-act="${act}">${icon(ic2)}${text}</button>`;
    const acts = [t.status === "running" ? btn("pause", "hand", t.stopping === "pause" ? "Pausing…" : "Pause") : "",
      t.status === "paused" ? btn("resume", "play", "Resume", "primary") : "",
      ["running", "paused"].includes(t.status) ? btn("cancel", "stop", t.stopping === "cancel" ? "Cancelling…" : "Cancel") : "",
      !["running"].includes(t.status) ? btn("delete", "trash", "Delete") : ""].join("");
    return `<div class="ia-card ia-head"><div class="ia-head-top"><div class="ia-head-t"><h2>${esc(t.title)}</h2>
        <div class="ia-meta">${chip(tone, label, ic)}<span class="ia-mono">${esc((t.model || "auto").split(":").pop())}</span>${t.thinking_model ? `<span class="faint small">thinking on <span class="ia-mono">${esc(t.thinking_model.split(":").pop())}</span></span>` : ""}
          <span class="faint small">window ${t.window} · rewrite every ${t.interval} calls · ${t.steps}-step plans · ${esc(t.effort)} effort</span></div></div>
        <div class="ia-head-a">${acts}</div></div>
      ${t.status === "running" && d.doing ? `<p class="ia-doing">${icon("zap")}${esc(d.doing.text)}</p>` : ""}
      ${t.status === "paused" && t.pause_reason ? `<p class="ia-note t-warn">${icon("info")}${esc(t.pause_reason)}</p>` : ""}
      ${t.status === "failed" && t.error ? `<p class="ia-note t-bad">${icon("alert")}${esc(t.error)}</p>` : ""}
      <div class="ia-meter" role="img" aria-label="${fmtNum(t.tokens, 0)} of ${fmtNum(t.budget, 0)} tokens used"><div class="ia-meter-bar"><span style="width:${used}%" class="${used > 90 ? "hot" : ""}"></span></div>
        <span class="small"><b>${short(t.tokens)}</b> of ${short(t.budget)} tokens</span>
        <label class="small faint">Budget <select data-budget aria-label="Token budget">${home.budgets.map(b => `<option value="${b}" ${b === t.budget ? "selected" : ""}>${short(b)}</option>`).join("")}</select></label></div></div>`;
  }
  function treeCard() {
    const run = d.frames.filter(f => f.run_id === d.task.run_id), fid = focus();
    const depth = f => { let n = 0, p = f; while (p?.parent_id) { p = d.frames.find(x => x.id === p.parent_id); n++; } return n; };
    const atomic = f => [...new Set(d.actions.filter(a => a.frame_id === f.id && role(a.tool).level === 1).map(a => a.tool))];
    const rows = run.map(f => {
      const r = role(f.role), [tone, label] = FSTATUS[f.status] || ["wait", f.status];
      const next = d.task.interval - f.counter % d.task.interval;
      return `<li style="--depth:${depth(f)}"><button type="button" class="ia-frow ${f.id === fid ? "on" : ""}" data-frame="${f.id}" aria-pressed="${f.id === fid}">
        ${av(r)}<span class="ia-frow-t"><b>${esc(r.name)}</b> <span class="faint small">level ${r.level} · ${esc(r.title)}</span><small>${esc(f.input.length > 140 ? f.input.slice(0, 138) + "…" : f.input)}</small>
          ${atomic(f).length ? `<small class="ia-atomic">${atomic(f).map(k => `${icon(role(k).icon)}${esc(role(k).name)}`).join(" ")}</small>` : ""}</span>
        <span class="ia-frow-s">${chip(tone, label)}<small>${plural(f.counter, "call")} · ${plural(f.thoughts, "rewrite")}${f.status === "running" ? ` · next in ${next}` : ""}</small><small>${short(f.tokens)} tokens</small></span></button></li>`;
    });
    return `<div class="ia-card"><h3 class="ia-h">${icon("users")}Agents <span class="faint">run ${d.runs.find(r => r.id === d.task.run_id)?.seq ?? ""} · pick one to see its thinking record</span></h3>
      ${rows.length ? `<ol class="ia-tree">${rows.join("")}</ol>` : `<p class="faint small">The Alpha agent is starting.</p>`}</div>`;
  }
  function recordCard() {
    const fid = focus();
    if (!fid) return "";
    if (!frame || frame.id !== fid) {
      if (frameFailed === fid) return `<div class="ia-card"><p class="faint small">The thinking record couldn't be loaded. <button type="button" class="linkbtn" data-frame="${fid}">Try again</button></p></div>`;
      if (!frameBusy) setTimeout(() => loadFrame(true));
      return `<div class="ia-card">${Loading.line("Loading the thinking record…")}</div>`;
    }
    const r = role(frame.role), t = frame.thinking;
    const block = (title, ic, body) => `<section class="ia-block"><h4>${icon(ic)}${title}</h4>${body}</section>`;
    const rec = !t ? `<p class="faint small">No record yet: the thinking model writes the first one before the agent's first step.</p>` : `<div class="ia-blocks">
      ${block("To-do list", "list", (t.todo_list || []).length ? `<ul class="ia-todo">${t.todo_list.map(i => { const [tone, ic] = TODO[i.status] || TODO.waiting; return `<li class="t-${tone}">${icon(ic)}<span>${esc(i.item)}</span></li>`; }).join("")}</ul>` : `<p class="faint small">Empty.</p>`)}
      ${block("Next steps", "route", (t.next_steps || []).length ? `<ol class="ia-steps">${t.next_steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol>` : `<p class="faint small">None.</p>`)}
      ${block("Pinned state", "pin", `<pre class="ia-pre">${esc(t.persistent_state || "–")}</pre>`)}
      ${block("Files worth reusing", "folder", (t.file_descriptions || []).length ? `<ul class="ia-fdesc">${t.file_descriptions.map(f => `<li><button type="button" class="linkbtn ia-mono" data-preview="${esc(f.path)}">${esc(f.path)}</button> ${esc(f.purpose)}<small class="faint">${esc(f.when)}</small></li>`).join("")}</ul>` : `<p class="faint small">None.</p>`)}</div>`;
    const recs = frame.records || [];
    return `<div class="ia-card"><h3 class="ia-h">${av(r, "xs")}${esc(r.name)}'s thinking record <span class="faint">${plural(recs.length, "version")}, last at call ${recs[recs.length - 1]?.n ?? 0}</span></h3>
      ${rec}
      <details class="ia-more"><summary>Action window <span class="faint">${plural(frame.window_actions.length, "action")} since the last rewrite: the only history the agent sees</span></summary>
        ${frame.window_actions.length ? `<ol class="ia-trace">${frame.window_actions.map(actionRow).join("")}</ol>` : `<p class="faint small">Empty: the window was just reset.</p>`}</details>
      ${recs.length > 1 ? `<details class="ia-more"><summary>Earlier records</summary><ol class="ia-recs">${recs.slice(0, -1).reverse().map(x => `<li><b>At call ${x.n}</b> · ${(x.record.todo_list || []).filter(i => i.status === "done").length}/${(x.record.todo_list || []).length} done<pre class="ia-pre">${esc(x.record.persistent_state || "")}</pre></li>`).join("")}</ol></details>` : ""}
      <details class="ia-more"><summary>System prompt</summary><pre class="ia-pre">${esc(frame.system || "")}</pre></details></div>`;
  }
  function actionRow(a, who = "") {
    let input = a.input || "";
    try { const o = JSON.parse(input); input = o.path || o.task || o.question && `${o.question} ${(o.paths || []).join(", ")}` || o.query || o.result || input; } catch { /* plain text */ }
    const r = role(a.tool), isAgent = r.level > 0;
    return `<li class="${a.error ? "bad" : ""}">${isAgent ? av(r, "xs") : `<span class="ia-ticon">${icon(TOOL_ICON[a.tool] || "wrench")}</span>`}
      <span>${who ? `<span class="faint small">${esc(who)} →</span> ` : ""}<b>${esc(a.tool.replace(/_/g, " "))}</b> <span class="ia-mono">${esc(String(input).slice(0, 160))}</span>
        ${a.result != null ? `<small>${esc(String(a.result).slice(0, 240))}</small>` : `<small class="faint">waiting for the result…</small>`}</span><span class="faint small">#${a.n}</span></li>`;
  }
  function traceCard() {
    const acts = d.actions.slice(-40).reverse();
    return `<div class="ia-card"><h3 class="ia-h">${icon("list")}Trace <span class="faint">latest steps of every agent · ${plural(d.thinking_count, "thinking rewrite")} so far</span></h3>
      ${acts.length ? `<ol class="ia-trace">${acts.map(a => actionRow(a, role(d.frames.find(x => x.id === a.frame_id)?.role).name)).join("")}</ol>` : `<p class="faint small">No steps yet.</p>`}</div>`;
  }
  function resultCard() {
    const run = d.runs.find(r => r.id === d.task.run_id);
    if (!run) return "";
    const followable = ["done", "failed", "cancelled"].includes(d.task.status);
    return `<div class="ia-card"><h3 class="ia-h">${icon("target")}${run.status === "running" ? "Working on" : "Result"}</h3>
      <p class="ia-instr">${esc(run.instruction)}</p>
      ${run.result ? `<div class="ia-result">${esc(run.result)}</div>` : ""}
      ${run.files.length ? `<div class="ia-filechips">${run.files.map(f => `<button type="button" class="chip" data-preview="${esc(f)}">${icon("file")}${esc(f)}</button>`).join("")}</div>` : ""}
      ${followable ? `<form class="ia-follow" data-keep="follow"><label class="ia-sr" for="ia-follow">Follow-up instruction</label><textarea id="ia-follow" name="instruction" rows="2" maxlength="8000" placeholder="A follow-up on the same workspace, e.g. Add a comparison table" required></textarea>
        <button class="btn" type="submit">${icon("send")}Follow up</button></form>` : ""}</div>`;
  }
  function filesCard() {
    const files = d.files, n = files.length, bytes = files.reduce((s, f) => s + f.size, 0);
    const pv = preview ? `<div class="ia-preview"><div class="ia-row"><b class="ia-mono">${esc(preview.path)}</b><span class="faint small">${fmtNum(preview.size, 0)} bytes</span>
        <a class="btn sm" href="/api/infiagent/tasks/${tid}/download?path=${encodeURIComponent(preview.path)}">${icon("download")}Download</a><button type="button" class="iconbtn" data-closepv aria-label="Close the preview">${icon("close")}</button></div>
        ${preview.binary ? `<p class="faint small">A binary file: download it to open it.</p>` : `<pre class="ia-pre tall">${esc(preview.text)}</pre>`}</div>` : "";
    return `<div class="ia-card"><h3 class="ia-h">${icon("folder")}Workspace <span class="faint">${plural(n, "file")} · ${short(bytes)}B</span>
        <label class="btn sm ia-upload">${icon("upload")}Add files<input type="file" multiple data-upload hidden></label></h3>
      ${pv}
      ${n ? `<ul class="ia-files">${files.map(f => `<li><button type="button" class="linkbtn ia-mono" data-preview="${esc(f.path)}">${esc(f.path)}</button>
        <span class="faint small">${f.source === "user" ? "yours" : "agents"} · ${short(f.size)}B</span></li>`).join("")}</ul>` : `<p class="faint small">Empty.</p>`}</div>`;
  }
  function coverageCard() {
    const body = !cov ? `<button type="button" class="btn sm" data-cov>${icon("check")}Check coverage</button>` : `
      <p class="ia-cov"><b>${cov.covered}</b> of ${cov.total} documents covered <span class="faint small">(${cov.read} read)</span></p>
      ${cov.total ? `<div class="ia-meter-bar"><span style="width:${cov.covered / cov.total * 100}%"></span></div>` : ""}
      <ul class="ia-covlist">${cov.files.map(f => `<li class="${f.covered ? "t-ok" : f.read ? "t-warn" : "t-bad"}">${icon(f.covered ? "check" : f.read ? "info" : "close")}<span class="ia-mono">${esc(f.path)}</span>
        <small class="faint">${f.covered ? "read and noted" : f.read ? "read, no note found" : "not read"}</small></li>`).join("")}</ul>
      <p class="faint small">${esc(cov.rule)}</p>`;
    return `<div class="ia-card"><h3 class="ia-h">${icon("chart")}Coverage <span class="faint">the paper's long-horizon audit</span></h3>
      <form class="ia-row" data-keep="cov" data-covform><label class="ia-sr" for="ia-covp">Which files count</label><input id="ia-covp" name="pattern" placeholder="Files to check (regex): your uploads if empty" value="${esc(covPattern)}"><button class="btn sm" type="submit">Check</button></form>
      ${body}</div>`;
  }
  function runsCard() {
    if (d.runs.length < 2) return "";
    return `<div class="ia-card"><h3 class="ia-h">${icon("clock")}Runs on this workspace</h3><ol class="ia-runs">${d.runs.slice().reverse().map(r => { const [tone, label] = TSTATUS[r.status] || ["wait", r.status];
      return `<li>${chip(tone, `Run ${r.seq} · ${label}`)}<span>${esc(r.instruction.slice(0, 160))}</span><small class="faint">${short(r.tokens)} tokens · <time data-ts="${r.started}">${ago(r.started)}</time></small></li>`; }).join("")}</ol></div>`;
  }

  // ---------- new task ----------
  function loadModels() { return api("/api/agents/models").then(m => { models = m; }).catch(() => { models = { providers: [], default: null }; }); }
  function modelOptions(cur, blank) {
    return [blank ? `<option value="">${blank}</option>` : `<option value="auto">Auto (the default model${models?.default ? `: ${esc(models.default.split(":").pop())}` : ""})</option>`,
      ...(models?.providers || []).filter(p => p.models.length).map(p => `<optgroup label="${esc(p.label)}">${p.models.map(m => `<option value="${esc(m.id)}" ${cur === m.id ? "selected" : ""}>${esc(m.label || m.id)}</option>`).join("")}</optgroup>`)].join("");
  }
  function dialog() {
    let dlg = $("#ia-new");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "ia-new"; dlg.className = "modal ia-modal"; document.body.append(dlg);
      dlg.addEventListener("click", e => { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); });
    }
    return dlg;
  }
  async function newTask(prefill = "") {
    if (!models) await loadModels();
    const df = home.defaults, dlg = dialog();
    const num = (name, label, hint) => `<label class="ia-field"><span>${label} <em class="faint">${hint}</em></span><input type="number" name="${name}" min="4" max="60" value="${df[name]}"></label>`;
    dlg.innerHTML = `<form class="ia-dlg"><button type="button" class="iconbtn ia-x" data-close aria-label="Close">${icon("close")}</button><h3>${icon("target")}New long task</h3>
      <label class="ia-field"><span>What should the agents do?</span><textarea name="instruction" rows="4" maxlength="8000" required placeholder="Describe the work and what the result should be">${esc(prefill)}</textarea></label>
      <label class="ia-field"><span>Title <em class="faint">optional</em></span><input name="title" maxlength="120"></label>
      <div class="ia-two"><label class="ia-field"><span>Model</span><select name="model">${modelOptions("auto")}</select></label>
        <label class="ia-field"><span>Thinking model <em class="faint">rewrites the records</em></span><select name="thinking_model">${modelOptions("", "Same as the task's model")}</select></label></div>
      <div class="ia-two"><label class="ia-field"><span>Token budget <em class="faint">the task pauses when it's used up</em></span><select name="budget">${home.budgets.map(b => `<option value="${b}" ${b === df.budget ? "selected" : ""}>${fmtNum(b, 0)}</option>`).join("")}</select></label>
        <label class="ia-field"><span>Effort</span><select name="effort">${home.efforts.map(x => `<option ${x === df.effort ? "selected" : ""}>${x}</option>`).join("")}</select></label></div>
      <div class="ia-field"><span>Documents <em class="faint">text, Markdown, code, CSV, JSON${home.limits.pdf ? ", PDF" : " (PDFs need pypdf on the server)"}; up to ${short(home.limits.file)}B each</em></span>
        <div class="ia-row"><input type="file" name="files" multiple aria-label="Documents"><label class="ia-inline">into <input name="folder" value="docs" size="8" aria-label="Folder"></label></div></div>
      <details class="ia-more"><summary>Context window settings <span class="faint">${df.window}, ${df.interval}, ${df.steps}; the paper used ${df.paper}</span></summary>
        <div class="ia-three">${num("window", "Action window", "recent actions in the prompt")}${num("interval", "Thinking interval", "tool calls between rewrites")}${num("steps", "Plan length", "next steps per record")}</div>
        <p class="faint small">Every step's prompt carries the whole window, so a bigger window costs more per step: at the paper's ${df.paper} a step is about twice the tokens of ${df.window}. Smaller numbers rewrite the record more often.</p></details>
      <div class="ia-row end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">${icon("play")}Start</button></div></form>`;
    dlg.showModal(); $("[name=instruction]", dlg).focus();
    dlg.onsubmit = async e => {
      e.preventDefault();
      const f = e.target, btn = $("[type=submit]", f);
      const folder = f.folder.value.trim().replace(/^\/+|\/+$/g, "");
      btn.disabled = true;
      try {
        const files = [];
        for (const file of f.files.files) {
          if (file.size > home.limits.file) { Auth.toast(`${file.name} is too big.`); btn.disabled = false; return; }
          files.push({ path: (folder ? `${folder}/` : "") + file.name, ...await readFile(file) });
        }
        const body = { instruction: f.instruction.value.trim(), title: f.title.value.trim(), model: f.model.value, thinking_model: f.thinking_model.value, budget: +f.budget.value,
          effort: f.effort.value, window: +f.window.value, interval: +f.interval.value, steps: +f.steps.value, files };
        const s = await api("/api/infiagent/tasks", { method: "POST", body });
        dlg.close();
        home = await api("/api/infiagent");
        tid = s.task.id; store.set("ia.tid", tid); d = s; sel = null; frame = null; cov = null; preview = null;
        render(); follow();
      } catch (x) { err(x); btn.disabled = false; }
    };
  }
  // text as text, anything else (PDFs) as base64
  function readFile(file) {
    return new Promise((ok, fail) => {
      const r = new FileReader(), text = /^text\/|json|xml|csv|javascript|yaml|markdown/.test(file.type) || /\.(txt|md|csv|tsv|json|ya?ml|py|js|ts|sql|html?|css|log|tex|bib|rst|ini|toml|sh|go|rs|java|c|h|cpp)$/i.test(file.name);
      r.onerror = () => fail(new Error(`Couldn't read ${file.name}.`));
      r.onload = () => ok(text ? { content: r.result } : { base64: String(r.result).split(",")[1] || "" });
      if (text) r.readAsText(file); else r.readAsDataURL(file);
    });
  }
  async function upload(files) {
    for (const file of files) {
      try {
        const res = await fetch(`/api/infiagent/tasks/${tid}/files?path=${encodeURIComponent(file.name)}`, { method: "PUT", credentials: "same-origin", headers: { "X-Requested-With": "scout" }, body: file });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Couldn't upload ${file.name}.`);
      } catch (e) { err(e); }
    }
    d = await api(`/api/infiagent/tasks/${tid}`).catch(() => d); render();
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    root().addEventListener("click", async e => {
      const t = e.target;
      if (t.closest("[data-ia=new]")) return newTask();
      const ex = t.closest("[data-example]"); if (ex) return newTask(ex.dataset.example);
      const row = t.closest("[data-task]"); if (row) return select(+row.dataset.task);
      const fr = t.closest("[data-frame]"); if (fr) { sel = +fr.dataset.frame; frame = null; render(); return loadFrame(); }
      const pv = t.closest("[data-preview]");
      if (pv) { try { preview = await api(`/api/infiagent/tasks/${tid}/file?path=${encodeURIComponent(pv.dataset.preview)}`); render(); $(".ia-preview", root())?.scrollIntoView({ block: "nearest" }); } catch (x) { err(x); } return; }
      if (t.closest("[data-closepv]")) { preview = null; return render(); }
      if (t.closest("[data-cov]")) return loadCoverage();
      const act = t.closest("[data-act]")?.dataset.act;
      if (!act) return;
      if (act === "delete" && !(await UI.confirm({ title: "Delete this task?", body: "Its workspace, trace and thinking records go for good.", ok: "Delete" }))) return;
      if (act === "cancel" && !(await UI.confirm({ title: "Cancel this run?", body: "It stops for good and can't be resumed. The workspace's files stay, and you can follow up on them.", ok: "Cancel the run", icon: "stop" }))) return;
      try {
        if (act === "delete") { await api(`/api/infiagent/tasks/${tid}`, { method: "DELETE" }); tid = null; d = null; store.set("ia.tid", null); return open(); }
        await api(`/api/infiagent/tasks/${tid}/${act}`, { method: "POST" });
        d = await api(`/api/infiagent/tasks/${tid}`); render();
      } catch (x) { err(x); }
    });
    root().addEventListener("change", async e => {
      if (e.target.matches("[data-budget]")) {
        try { await api(`/api/infiagent/tasks/${tid}`, { method: "PATCH", body: { budget: +e.target.value } }); d = await api(`/api/infiagent/tasks/${tid}`); render(); } catch (x) { err(x); }
      }
      if (e.target.matches("[data-upload]")) upload([...e.target.files]);
    });
    root().addEventListener("input", e => { if (e.target.closest("[data-keep]")) e.target.dataset.dirty = "1"; });
    root().addEventListener("submit", async e => {
      e.preventDefault();
      const f = e.target;
      if (f.matches("[data-covform]")) { covPattern = f.pattern.value.trim(); return loadCoverage(); }
      if (f.matches(".ia-follow")) {
        try { await api(`/api/infiagent/tasks/${tid}/follow-up`, { method: "POST", body: { instruction: f.instruction.value.trim() } }); f.instruction.value = ""; delete f.instruction.dataset.dirty;
          sel = null; frame = null; d = await api(`/api/infiagent/tasks/${tid}`); render(); } catch (x) { err(x); }
      }
    });
  }
  return { open, stop };
})();
