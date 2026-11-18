/* Competition teams, importing earlier work (mining_import.py), as a dialog on a team (the Import button by Plan now):
   1. tools/mining-import.py packs a folder on the user's machine (files, git history, Claude Code conversations and memory,
      secrets taken out) into a bundle; the user uploads it here.
   2. The preview lists what's in it with what fits ticked: files by folder against the workspace's room, notebook entries,
      conversations (the model reads each once; ones read for another team already cost nothing), and what was left out and why.
   3. The import runs: files and notes go in at once, then the conversations are read one by one (waiting when the team's token
      budget is spent) and the Director reads it all and sets the team up: a Start here entry, the roadmap, tasks and a report.
   Any import can be undone. */
const MiningImport = (() => {
  const W = "/api/mining/work";
  const RUNNING = ["importing", "digesting", "waiting", "onboarding"];
  const STATE = { preview: ["none", "Not imported"], importing: ["run", "Importing"], digesting: ["run", "Reading conversations"], waiting: ["wait", "Waiting for budget"],
    onboarding: ["run", "The Director is reading"], done: ["ok", "Imported"], failed: ["bad", "Stopped by an error"], undone: ["off", "Undone"] };
  const GROUP = { code: "Code", plan: "Plan", eval: "Eval", docs: "Docs", data: "Data" };
  const unfolded = new Set();  // folders open in the preview: a re-render keeps them
  let dlg = null, wid = null, list = null, cur = null, sel = new Set(), opts = { digest: true, onboard: true, overwrite: false }, timer = null, failed = "";
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${fmtNum(n, 0)} ${w}${n === 1 ? "" : s}`;
  const size = b => b >= 1e6 ? `${fmtNum(b / 1e6, 1)} MB` : b >= 1e3 ? `${fmtNum(b / 1e3, 0)} kB` : `${b || 0} B`;
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 0)}k` : fmtNum(n || 0, 0);
  const day = ts => ts ? new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "?";
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;
  const x = `<button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>`;
  const top = p => p.includes("/") ? p.split("/")[0] : "";
  const imp = () => cur?.import;
  const man = () => imp()?.manifest || {};
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- opening ----------
  function open(id) {
    wid = id; cur = null; list = null; failed = "";
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "imp-dlg"; document.body.append(dlg);
      dlg.addEventListener("click", click); dlg.addEventListener("change", change);
      dlg.addEventListener("close", () => clearTimeout(timer));
      dlg.addEventListener("dragover", e => { if (!cur && e.dataTransfer?.types.includes("Files")) { e.preventDefault(); $(".imp-drop", dlg)?.classList.add("on"); } });
      dlg.addEventListener("dragleave", e => { if (e.target.closest?.(".imp-drop")) $(".imp-drop", dlg)?.classList.remove("on"); });
      dlg.addEventListener("drop", e => { if (cur || !e.dataTransfer?.files.length) return; e.preventDefault(); upload(e.dataTransfer.files[0]); });
    }
    dlg.className = "modal mw-dlg wide imp-dlg";
    render(); dlg.showModal();
    load();
  }
  async function load() {
    try {
      list = await api(`${W}/comps/${wid}/imports`);
      const live = list.imports.find(i => RUNNING.includes(i.status)) || list.imports.find(i => i.status === "preview");
      if (live) return show(live.id);
    } catch (e) { failed = e.message; }
    render();
  }
  async function show(iid) {
    try { set(await api(`${W}/imports/${iid}`)); } catch (e) { err(e); }
  }
  function set(d) {
    const fresh = d.import.id !== imp()?.id || d.import.status !== imp()?.status;
    cur = d;
    if (fresh && d.import.status === "preview") {
      const m = d.import.manifest;
      sel = new Set([...m.files, ...m.notes, ...m.sessions].filter(i => i.pick).map(i => i.key));
      if (m.git.pick) sel.add("git");
      opts = { digest: true, onboard: !!d.lead && d.model, overwrite: false };
    }
    render(); poll();
  }
  function poll() {
    clearTimeout(timer);
    if (!dlg?.open || !RUNNING.includes(imp()?.status)) return;
    timer = setTimeout(async () => {
      try {
        const d = await api(`${W}/imports/${imp().id}`);
        const was = imp()?.status;
        cur = d; render();
        if (!RUNNING.includes(d.import.status) && was !== d.import.status) MiningWork.reload();
      } catch { /* the next look tries again */ }
      poll();
    }, 2000);
  }

  // ---------- drawing ----------
  function render() {
    if (!dlg) return;
    const s = dlg.scrollTop, i = imp();
    dlg.innerHTML = `<div class="hq-dlg-in imp">${x}<h3>${icon("upload")} Import earlier work</h3>
      ${!i ? start() : i.status === "preview" ? preview() : progress()}</div>`;
    if (i?.status === "preview") refresh();
    dlg.scrollTop = s;
  }

  function start() {
    const past = (list?.imports || []).filter(i => i.status !== "preview");
    return `<p>Bring in what you did on this competition before the team existed: your agent's code, eval sets and results, plans, notes, git history and your Claude Code conversations. The team carries on from there instead of starting over.</p>
      <ol class="imp-steps">
        <li><b>Pack the folder</b> on the machine where the work is. It only reads, and takes secrets out (API keys, tokens, <code>.env</code> files) before anything is written:
          <div class="imp-cmd"><code>python3 tools/mining-import.py <i>/path/to/folder</i> --out work.json</code><button type="button" class="iconbtn" data-mi="copy" aria-label="Copy the command" title="Copy">${icon("copy")}</button></div>
          <span class="faint small">It finds the Claude Code conversations held in that folder by itself. Add <code>--no-sessions</code> to leave them out.</span></li>
        <li><b>Upload the bundle</b> here. Nothing is imported until you've seen what's in it and picked.</li></ol>
      <label class="imp-drop">${icon("upload")}<span><b>Choose work.json</b> or drop it here</span><input type="file" accept=".json,application/json" data-mi="file"></label>
      ${failed ? `<p class="mh-err small">${icon("alert")}${esc(failed)}</p>` : ""}
      ${past.length ? `<h4>Earlier imports on this team</h4><ul class="imp-past">${past.map(i => `<li>${chip(STATE[i.status] || STATE.done)}<span><b>${esc(i.name)}</b>
          <span class="faint small">${esc(i.by_user)} · ${when(i.created)} · ${added(i.added)}${i.tokens ? ` · ${short(i.tokens)} tokens` : ""}</span></span>
          <button type="button" class="btn sm" data-miopen="${i.id}">Open</button></li>`).join("")}</ul>` : ""}`;
  }
  function added(a) {
    const parts = [plural(a.files || 0, "file"), plural(a.notes || 0, "notebook entr", a.notes === 1 ? "y" : "ies"), plural(a.milestones || 0, "milestone"),
      plural(a.tasks || 0, "task"), plural(a.reports || 0, "report")];
    return parts.filter(p => !p.startsWith("0 ")).join(", ") || "nothing";
  }

  function preview() {
    const i = imp(), m = man(), known = new Set(cur.digested || []);
    const folders = {};
    for (const f of m.files) (folders[top(f.path)] ||= []).push(f);
    const order = Object.keys(folders).sort((a, b) => (a === "") - (b === "") || a.localeCompare(b));
    const files = order.map(k => { const fs = folders[k], b = fs.reduce((s, f) => s + f.bytes, 0);
      const on = unfolded.has(k);
      return `<li class="imp-folder"><div class="imp-frow"><label class="mh-check"><input type="checkbox" data-mifolder="${esc(k)}" aria-label="Import ${esc(k || "the folder's own files")}"></label>
          <button type="button" class="imp-fbtn" data-mifold="${esc(k)}" aria-expanded="${on}">${icon(on ? "down" : "right")}${icon("folder")}<b>${esc(k || "(the folder itself)")}</b>
          <span class="faint small" data-mi-fc="${esc(k)}"></span><span class="faint small imp-fsize">${size(b)}</span></button></div>
        <ul class="imp-files" ${on ? "" : "hidden"}>${fs.map(f => `<li><label class="mh-check ${f.bad ? "is-off" : ""}"><input type="checkbox" data-mikey="${esc(f.key)}" ${f.bad ? "disabled" : ""}>
          <span class="imp-path">${esc(f.path)}</span></label><span class="imp-tags">${f.tracked ? `<span class="hq-chip" title="Tracked by git">${icon("branch")}git</span>` : ""}
          <span class="hq-chip">${GROUP[f.group] || esc(f.group)}</span>${f.exists ? `<span class="hq-chip t-warn" title="The workspace has a file at this path">in the workspace</span>` : ""}
          ${f.bad ? `<span class="hq-chip t-bad">${esc(f.bad)}</span>` : ""}<span class="faint small">${size(f.bytes)}</span></span></li>`).join("")}</ul></li>`; }).join("");
    const notes = m.notes.map(n => `<li><label class="mh-check"><input type="checkbox" data-mikey="${esc(n.key)}"><span><b>${esc(n.title)}</b> <span class="faint small">${esc(n.source || n.kind)}</span></span></label></li>`).join("");
    const sess = m.sessions.map(s => `<li><label class="mh-check"><input type="checkbox" data-mikey="${esc(s.key)}"><span class="imp-sess"><span class="faint small imp-when">${day(s.started)}</span>
        <span class="imp-first">${esc(s.first || "(no text)")}</span><span class="faint small">${plural(s.asks, "message")}${known.has(s.id) ? ` · <span class="imp-free">read already: free</span>` : ""}</span></span></label></li>`).join("");
    const skipped = m.skipped.map(s => `<li><span class="imp-path">${esc(s.path)}</span><span class="faint small">${esc(s.why)}${s.bytes ? ` · ${size(s.bytes)}` : ""}</span></li>`).join("");
    const g = m.git;
    return `<p class="imp-src">${icon("folder")}<span><b>${esc(i.name)}</b> <span class="faint small">${esc(i.source)} · packed ${when(i.made)}</span></span></p>
      <p class="imp-safe small">${icon("shield")}<span>${m.redacted ? `${plural(m.redacted, "secret")} taken out (API keys, tokens, passwords); ` : "No secrets found in the text; "}${plural(m.skipped_n, "thing")} left out (secret files, caches, other repositories, bulk data). Nothing is in the team until you import.</span></p>
      <section class="imp-sec"><h4>${icon("file")}Files <span class="faint" data-mi="files-sum"></span><span class="imp-acts"><button type="button" class="linkbtn" data-misel="files:all">All</button><button type="button" class="linkbtn" data-misel="files:none">None</button><button type="button" class="linkbtn" data-misel="files:reset">Suggested</button></span></h4>
        <p class="faint small">Into the workspace, where agents read them and run them in the sandbox. Ticked to start with: files git tracks, plans, eval sets and logs; not downloaded data.</p>
        <div class="imp-room" data-mi="room"></div>
        <ul class="imp-tree">${files || `<li class="faint small">No files.</li>`}</ul></section>
      <section class="imp-sec"><h4>${icon("book")}Notebook <span class="faint" data-mi="notes-sum"></span></h4>
        <p class="faint small">Every agent reads the notebook before it works. Eval scores are pulled from the eval logs you import into one entry.</p>
        <ul class="imp-list">${notes}${g.n ? `<li><label class="mh-check"><input type="checkbox" data-mikey="git"><span><b>Git history: ${plural(g.n, "commit")}</b> <span class="faint small">${day(g.first)} to ${day(g.last)}${g.remote ? ` · ${esc(g.remote)}, linked to the team` : ""}</span></span></label></li>` : ""}</ul></section>
      ${m.sessions.length ? `<section class="imp-sec"><h4>${icon("chat")}Claude Code conversations <span class="faint" data-mi="sess-sum"></span><span class="imp-acts"><button type="button" class="linkbtn" data-misel="sess:all">All</button><button type="button" class="linkbtn" data-misel="sess:none">None</button></span></h4>
        <p class="faint small">Each one becomes a dated notebook entry: what you asked, what was tried and found, and what was decided. Greetings and one-liners are left unticked.</p>
        <ul class="imp-list imp-sessions">${sess}</ul></section>` : ""}
      ${skipped ? `<details class="imp-sec imp-skip"><summary>${icon("ban")}Left out by the script <span class="faint">${plural(m.skipped_n, "item")}${m.skipped_n > m.skipped.length ? `, the ${m.skipped.length} biggest shown` : ""}</span></summary><ul class="imp-list">${skipped}</ul></details>` : ""}
      <section class="imp-sec imp-opts"><h4>${icon("sliders")}How</h4>
        <label class="mh-check"><input type="checkbox" data-miopt="digest" ${opts.digest ? "checked" : ""} ${cur.model ? "" : "disabled"}><span><b>Have the model read the conversations</b> <span class="faint" data-mi="tokens"></span></span></label>
        <label class="mh-check"><input type="checkbox" data-miopt="onboard" ${opts.onboard ? "checked" : ""} ${cur.lead && cur.model ? "" : "disabled"}><span><b>Then ${esc(cur.lead || "the Director")} reads it all and sets the team up</b> <span class="faint">a Start here entry, the roadmap (what's done marked done), the open work as tasks (not started) and a report to you</span></span></label>
        <label class="mh-check"><input type="checkbox" data-miopt="overwrite" ${opts.overwrite ? "checked" : ""}><span><b>Replace files the workspace already has</b> <span class="faint">otherwise the team's own version stays</span></span></label>
        ${!cur.model ? `<p class="mh-err small">${icon("info")}No model is connected, so conversations go in as they are and nobody reads them. Connect one in Agents → Models first for the full import.</p>` : !cur.lead ? `<p class="faint small">${icon("info")}The team has no Director (Team → an agent → Lead), so nobody sets the team up afterwards.</p>` : ""}</section>
      <div class="row end imp-foot"><span class="faint small" data-mi="foot"></span><button type="button" class="btn mw-danger" data-mi="discard">${icon("trash")}Throw away</button>
        <button type="button" class="btn primary" data-mi="apply">${icon("upload")}Import</button></div>`;
  }

  function stats() {
    const m = man(), known = new Set(cur.digested || []);
    const fs = m.files.filter(f => sel.has(f.key));
    const ss = m.sessions.filter(s => sel.has(s.key));
    const fresh = fs.filter(f => !f.exists).length;
    const bytes = fs.reduce((s, f) => s + f.bytes, 0);
    const reading = ss.filter(s => !known.has(s.id));
    const tokens = opts.digest ? reading.reduce((t, s) => t + s.chars / 3.2 + 600, 0) : 0;
    return { fs, ss, fresh, bytes, reading, tokens: tokens + (opts.onboard ? 30000 : 0), notes: m.notes.filter(n => sel.has(n.key)).length + (sel.has("git") ? 1 : 0) };
  }
  function refresh() {
    if (!dlg || imp()?.status !== "preview") return;
    const m = man(), s = stats(), r = cur.room;
    const over = s.fresh > r.files || s.bytes > r.bytes;
    const put = (k, html) => { const el = $(`[data-mi="${k}"]`, dlg); if (el) el.innerHTML = html; };
    put("files-sum", `${plural(s.fs.length, "file")} · ${size(s.bytes)}`);
    put("room", `<div class="imp-bar ${over ? "over" : ""}"><i style="--w:${Math.min(100, s.bytes / Math.max(1, r.bytes) * 100).toFixed(1)}%"></i></div>
      <span class="small ${over ? "mw-late" : "faint"}">${over ? `${icon("alert")}Too much for the workspace: it has room for ${plural(r.files, "more file")} and ${size(r.bytes)}. Untick some.` : `${size(s.bytes)} of the ${size(r.bytes)} free, ${s.fresh} of ${plural(r.files, "free file slot")}`}</span>`);
    put("notes-sum", plural(s.notes, "entr", s.notes === 1 ? "y" : "ies"));
    put("sess-sum", `${s.ss.length} of ${m.sessions.length}`);
    const left = cur.budget ? Math.max(0, cur.budget - cur.day) : null;
    put("tokens", s.reading.length ? `about ${short(s.tokens)} tokens for ${plural(s.reading.length, "conversation")}${opts.onboard ? " and the Director" : ""}${left != null ? `; ${short(left)} of today's budget left${s.tokens > left ? ", so it carries on as the budget allows" : ""}` : ""}` : s.ss.length ? `already read for another team: free${opts.onboard ? "; about 30k tokens for the Director" : ""}` : "");
    put("foot", over ? "" : `${plural(s.fs.length, "file")}, ${plural(s.notes + (opts.digest ? 0 : s.ss.length), "entr", (s.notes + (opts.digest ? 0 : s.ss.length)) === 1 ? "y" : "ies")}${opts.digest && s.ss.length ? ` and up to ${plural(s.ss.length, "conversation")}` : ""}`);
    $$("[data-mikey]", dlg).forEach(cb => { cb.checked = sel.has(cb.dataset.mikey); });
    $$("[data-mifolder]", dlg).forEach(cb => {
      const fs = m.files.filter(f => top(f.path) === cb.dataset.mifolder && !f.bad), n = fs.filter(f => sel.has(f.key)).length;
      cb.checked = !!n && n === fs.length; cb.indeterminate = !!n && n < fs.length; cb.disabled = !fs.length;
      const c = $(`[data-mi-fc="${CSS.escape(cb.dataset.mifolder)}"]`, dlg); if (c) c.textContent = `${n} of ${fs.length}`;
    });
    const go = $('[data-mi="apply"]', dlg); if (go) go.disabled = over || !sel.size;
  }

  function progress() {
    const i = imp(), p = i.progress || {}, a = i.added || {}, run = RUNNING.includes(i.status);
    const share = p.total ? p.done / p.total : i.status === "done" ? 1 : 0;
    const line = i.status === "importing" ? "Putting the files and notes in…"
      : i.status === "digesting" ? `Reading conversation ${Math.min(p.done + 1, p.total)} of ${p.total}${p.now ? `: “${esc(p.now)}”` : ""}`
      : i.status === "waiting" ? `Today's token budget for this team is spent: it carries on by itself when there's room (${p.done} of ${p.total} read). Raise the budget in the team's settings to go faster.`
      : i.status === "onboarding" ? `${esc(cur.lead || "The Director")} is reading everything and setting the team up…`
      : i.status === "done" ? `Done${i.finished ? ` ${when(i.finished)}` : ""}${p.stopped ? ", stopped before every conversation was read" : ""}.`
      : i.status === "failed" ? `It stopped: ${esc(i.error || "an error")}. What it imported stays; undo takes it out.`
      : `Undone: what it added was taken out${p.kept_files?.length ? `, except ${plural(p.kept_files.length, "file")} the team changed since` : ""}${p.kept_tasks ? ` and ${plural(p.kept_tasks, "task")} that had already run` : ""}.`;
    return `<p class="imp-src">${icon("folder")}<span><b>${esc(i.name)}</b> <span class="faint small">${esc(i.source)} · ${esc(i.by_user)} · ${when(i.created)}</span></span>${chip(STATE[i.status] || STATE.done)}</p>
      ${run || i.status === "done" ? `<div class="imp-bar ${run ? "run" : ""}"><i style="--w:${(share * 100).toFixed(1)}%"></i></div>` : ""}
      <p class="imp-line">${run ? icon("cycle") : i.status === "failed" ? icon("alert") : icon("check")}<span>${line}</span></p>
      <ul class="imp-added">${[["file", a.files, "Files in the workspace"], ["book", a.notes, "Notebook entries"], ["map", a.milestones, "Milestones"], ["list", a.tasks, "Tasks (not started)"], ["inbox", a.reports, "Report"], ["link", a.links, "Linked repository"]]
        .filter(([, n]) => n).map(([ic, n, l]) => `<li>${icon(ic)}<b>${fmtNum(n, 0)}</b><span>${l}</span></li>`).join("") || `<li class="faint small">Nothing yet.</li>`}</ul>
      ${p.total ? `<p class="faint small">${p.done} of ${plural(p.total, "conversation")} read, ${p.kept || 0} kept (the rest had nothing for the team)${i.tokens ? ` · ${short(i.tokens)} tokens so far` : ""}.</p>` : i.tokens ? `<p class="faint small">${short(i.tokens)} tokens.</p>` : ""}
      ${p.problems?.length ? `<details class="imp-sec"><summary>${icon("info")}${plural(p.problems.length, "thing")} that didn't go in</summary><ul class="imp-list">${p.problems.map(t => `<li class="small">${esc(t)}</li>`).join("")}</ul></details>` : ""}
      <div class="row end imp-foot">
        ${run && i.status !== "importing" ? `<button type="button" class="btn" data-mi="stop">${icon("stop")}Stop</button>` : ""}
        ${["done", "failed"].includes(i.status) ? `<button type="button" class="btn mw-danger" data-mi="undo">${icon("undo")}Undo the import</button>` : ""}
        ${a.notes ? `<button type="button" class="btn" data-migo="notes">${icon("book")}Open the notebook</button>` : ""}
        ${a.reports && !run ? `<button type="button" class="btn primary" data-migo="report">${icon("inbox")}Read the report</button>` : ""}
        ${run ? "" : `<button type="button" class="btn" data-mi="again">${icon("upload")}Import something else</button>`}</div>`;
  }

  // ---------- acting ----------
  async function upload(file) {
    if (!file) return;
    if (file.size > 40e6) { Auth.toast("That bundle is over 40 MB: pack it with --no-sessions, or a smaller folder."); return; }
    const drop = $(".imp-drop", dlg); drop?.classList.add("loading");
    try {
      let body;
      try { body = JSON.parse(await file.text()); } catch { throw new Error("That file isn't a bundle: make one with tools/mining-import.py."); }
      set(await api(`${W}/comps/${wid}/imports`, { method: "POST", body }));
    } catch (e) { failed = e.message; cur = null; render(); }
    finally { drop?.classList.remove("loading"); }
  }
  function pick(kind, how) {
    const m = man(), items = kind === "files" ? m.files.filter(f => !f.bad) : m.sessions;
    items.forEach(i => { const on = how === "all" || (how === "reset" && i.pick); if (on) sel.add(i.key); else sel.delete(i.key); });
    refresh();
  }
  async function click(e) {
    const t = e.target;
    if (t.closest("[data-close]")) { dlg.close(); return; }
    const b = t.closest("[data-mi]"), k = b?.dataset.mi;
    if (k === "copy") { const text = "python3 tools/mining-import.py /path/to/folder --out work.json"; navigator.clipboard?.writeText(text).then(() => Auth.toast("Copied"), () => Auth.toast(text)); return; }
    if (k === "apply") {
      const i = imp(), d = await busy(b, () => api(`${W}/imports/${i.id}/apply`, { method: "POST", body: { keys: [...sel], ...opts } }));
      if (d) { set(d); MiningWork.reload(); Auth.toast(RUNNING.includes(d.import.status) ? "Imported: the conversations are being read now" : "Imported"); }
      return;
    }
    if (k === "discard") { const d = await busy(b, () => api(`${W}/imports/${imp().id}`, { method: "DELETE" })); if (d) { list = d; cur = null; render(); } return; }
    if (k === "stop") { const d = await busy(b, () => api(`${W}/imports/${imp().id}/stop`, { method: "POST" })); if (d) set(d); return; }
    if (k === "undo") {
      await UI.confirm({ title: "Undo this import?", ok: "Undo", icon: "undo",
        body: "What it added goes again: its files (unless the team changed them since), notebook entries, milestones, tasks that haven't run, the linked repository and its report.",
        run: async () => { set(await api(`${W}/imports/${imp().id}/undo`, { method: "POST" })); MiningWork.reload(); Auth.toast("The import was undone"); } }).catch(err);
      return;
    }
    if (k === "again") { cur = null; failed = ""; render(); load(); return; }
    const fo = t.closest("[data-mifold]");
    if (fo) {
      const k = fo.dataset.mifold, on = !unfolded.has(k), ul = fo.closest(".imp-folder").querySelector(".imp-files");
      if (on) unfolded.add(k); else unfolded.delete(k);
      ul.hidden = !on; fo.setAttribute("aria-expanded", on); fo.querySelector(".icon").outerHTML = icon(on ? "down" : "right");
      return;
    }
    const o = t.closest("[data-miopen]"); if (o) { show(+o.dataset.miopen); return; }
    const s = t.closest("[data-misel]"); if (s) { const [kind, how] = s.dataset.misel.split(":"); pick(kind, how); return; }
    const g = t.closest("[data-migo]"); if (g) { dlg.close(); MiningWork.go(g.dataset.migo); }
  }
  function change(e) {
    const t = e.target;
    if (t.matches('[data-mi="file"]')) { upload(t.files[0]); return; }
    if (t.dataset.mikey) { if (t.checked) sel.add(t.dataset.mikey); else sel.delete(t.dataset.mikey); refresh(); return; }
    if (t.dataset.mifolder !== undefined) {
      man().files.filter(f => top(f.path) === t.dataset.mifolder && !f.bad).forEach(f => { if (t.checked) sel.add(f.key); else sel.delete(f.key); });
      refresh(); return;
    }
    if (t.dataset.miopt) { opts[t.dataset.miopt] = t.checked; refresh(); }
  }

  return { open };
})();
