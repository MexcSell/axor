/* Competition teams, the Workflow's GitHub tab (mining_github.py): people you allow ask the team for work by mentioning it on
   an issue or pull request of a Source hub repository, and hear back in the same thread.
   - The link: repository, the handle people mention, who may ask, whether a request waits for you or starts by itself, and
     whether replies include the agent's summary. Last check and any error (reading, or replying without permission).
   - Tasks from GitHub: each with who asked, where, the thread's step and the mandate it was taken under.
   - Intake: every mention read, with what became of it and why (not on the list, a bot, too many open…).
   - Replies: the outbox, oldest first per thread, with errors and Send again. */
const MiningGitHub = (() => {
  const G = "/api/mining/github";
  let d = null, dFid = null, dAt = 0, loading = false, failed = "", wired = false, note = "";
  const err = e => e && Auth.toast(e.message);
  const when = ts => ts ? new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const DEC = { task: ["ok", "Task"], sent_back: ["run", "Sent back"], noted: ["none", "Noted"], stop: ["warn", "Stopped"], ignored: ["none", "Ignored"], error: ["bad", "Error"] };
  const STAGE = { queued: ["none", "Waiting to start"], working: ["run", "Working"], finished: ["warn", "Finished"], reviewing: ["run", "Reviewing"],
    reviewed: ["warn", "Reviewed"], failed: ["bad", "Stopped"], merged: ["ok", "Merged"], dropped: ["none", "Dropped"], unlinked: ["none", "Unlinked"] };
  const OUT = { pending: ["wait", "Sending"], sent: ["ok", "Sent"], failed: ["bad", "Failed"] };
  const chip = (m, k) => { const [c, l] = m[k] || ["none", k]; return `<span class="hq-chip t-${c}">${esc(l)}</span>`; };

  function need(fid, force = false) {
    if (dFid !== fid) { d = null; dFid = fid; dAt = 0; failed = ""; note = ""; }
    if (loading || (!force && Date.now() - dAt < 15000)) return;
    loading = true;
    api(`${G}/flows/${fid}`).then(x => { if (dFid === fid) { d = x; failed = ""; } }).catch(e => { if (dFid === fid) failed = e.message; })
      .finally(() => { dAt = Date.now(); loading = false; if (dFid === fid && !MiningBench.holding()) MiningWork.rerender(); });
  }

  function linkCard() {
    const l = d.link, on = !l || !!l.enabled;
    const repos = d.repos.map(r => `<option value="${esc(r)}" ${l && l.repo.toLowerCase() === r.toLowerCase() ? "selected" : ""}>${esc(r)}</option>`).join("");
    const status = !l ? "" : `<p class="small mgh-st">${l.enabled ? `${icon("check")}Reads ${esc(l.repo)} every ${d.poll >= 60 ? `${Math.round(d.poll / 60)} min` : `${d.poll} s`}${l.polled ? `, last ${ago(l.polled)}` : ""}.` : `${icon("minus")}Paused: no mention is read.`}
        ${l.handle !== l.login ? ` <span class="faint">Replies come from @${esc(l.login)}.</span>` : ""}</p>
      ${l.error ? `<p class="mh-err small">${icon("alert")}Reading GitHub: ${esc(l.error)}</p>` : ""}
      ${l.reply_error ? `<p class="mh-err small">${icon("alert")}Replying: ${esc(l.reply_error)}</p>` : ""}`;
    if (!d.connected) return `<section class="mh-card"><h3>${icon("github")}GitHub</h3><p class="faint small">GitHub isn't connected. An administrator adds a source and its repositories in the Source view; then link one here.</p></section>`;
    if (!d.repos.length) return `<section class="mh-card"><h3>${icon("github")}GitHub</h3><p class="faint small">No repository is on the Source hub list yet: add one in the Source view, then link it here.</p></section>`;
    return `<section class="mh-card mgh-link"><div class="mgh-head"><div><h3>${icon("github")}Requests from GitHub</h3>
        <p class="faint small">Someone on the list mentions the handle on an issue or pull request; the request becomes a task here and the replies go to the same thread. Quoted lines and code don't count; bots and anyone not on the list are ignored. Merging stays yours.</p></div>
        ${l ? chip({ 1: ["ok", "Linked"], 0: ["none", "Paused"] }, l.enabled ? 1 : 0) : ""}</div>
      ${status}
      <form class="mgh-form" data-mghform="link" data-mbhold>
        <div class="mgh-grid">
          <label class="in"><span>Repository</span><select name="repo" required>${l ? "" : `<option value="">Pick one…</option>`}${repos}</select></label>
          <label class="in"><span>Handle <em class="opt">what people mention; empty = the token's account${l?.login ? ` (@${esc(l.login)})` : ""}</em></span>
            <input name="handle" maxlength="39" value="${esc(l && l.handle !== l.login ? l.handle : "")}" placeholder="${esc(l?.login || "the token's login")}" autocomplete="off"></label>
          <label class="in mgh-wide"><span>Who may ask <em class="opt">GitHub logins, separated by spaces or commas</em></span>
            <textarea name="allowed" rows="2" placeholder="alice, bob">${esc((l?.allowed || []).join(", "))}</textarea></label></div>
        <fieldset class="mgh-mode"><legend>A new request</legend>
          <label><input type="radio" name="start" value="ask" ${!l || l.start === "ask" ? "checked" : ""}> <span><b>Waits for you</b> <span class="faint">it appears in Work; you start it</span></span></label>
          <label><input type="radio" name="start" value="auto" ${l?.start === "auto" ? "checked" : ""}> <span><b>Starts by itself</b> <span class="faint">its engineer starts at once; a later comment sends finished work back</span></span></label></fieldset>
        <label class="mgh-check"><input type="checkbox" name="summaries" ${l?.summaries ? "checked" : ""}> <span>Include the agent's summary in replies <span class="faint">(off: replies say only what happened; on: what the agent wrote, with token-like text removed. Mind public repositories.)</span></span></label>
        ${l ? `<label class="mgh-check"><input type="checkbox" name="on" ${on ? "checked" : ""}> <span>Read mentions</span></label>` : ""}
        ${note ? `<p class="small mh-warn">${icon("info")}${esc(note)}</p>` : ""}
        <div class="row"><button type="submit" class="btn primary sm">${l ? "Save" : "Link it"}</button>
          ${l ? `<button type="button" class="btn sm" data-mgh="poll">${icon("reset")}Check now</button><button type="button" class="btn sm ghost" data-mgh="unlink">Unlink</button>` : ""}
          <span class="faint small">Replying needs the source's token to have Issues: read and write.</span></div></form></section>`;
  }

  function tasksCard() {
    if (!d.tasks.length) return "";
    const rows = d.tasks.map(t => `<li><span class="mgh-t"><b>${esc(t.title || `Task #${t.task_id}`)}</b>
        <span class="faint small">@${esc(t.by_login)} · <a href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">#${t.number}</a> · ${when(t.created)} · taken under rules v${t.mandate?.version ?? "?"}, ${t.mandate?.start === "auto" ? "started by itself" : "waited for you"}</span></span>
        ${chip(STAGE, t.status === "merged" ? "merged" : t.status === "dropped" ? "dropped" : t.stage)}</li>`).join("");
    return `<section class="mh-card"><h3>${icon("list")}Tasks from GitHub</h3><p class="faint small">At most ${d.max_open} open at once; more requests are turned away with a reply until one is merged or dropped.</p>
      <ul class="mal-list mgh-list">${rows}</ul></section>`;
  }

  function intakeCard() {
    const rows = d.items.slice(0, 25).map(x => `<li><span class="mgh-t"><span>${chip(DEC, x.decision)} <b>@${esc(x.author || "?")}</b> on <a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">#${x.number}</a> <span class="faint small">${ago(x.ts)}</span></span>
        <span class="small mgh-q">${esc(x.text || "")}</span><span class="faint small">${esc(x.reason || "")}</span></span></li>`).join("");
    return `<section class="mh-card"><h3>${icon("inbox")}Intake</h3><p class="faint small">Every mention read, and what became of it.</p>
      ${rows ? `<ul class="mal-list mgh-list">${rows}</ul>` : `<p class="faint small">Nothing yet.</p>`}</section>`;
  }

  function outboxCard() {
    if (!d.outbox.length) return "";
    const rows = d.outbox.map(o => `<li><span class="mgh-t"><span>${chip(OUT, o.status)} <b>#${o.number}</b> <span class="faint small">${ago(o.created)}${o.tries ? ` · ${o.tries} tr${o.tries === 1 ? "y" : "ies"}` : ""}</span>
        ${o.url ? `<a class="small" href="${esc(o.url)}" target="_blank" rel="noopener noreferrer">Open</a>` : ""}</span>
        <span class="small mgh-q">${esc(o.body)}</span>${o.error ? `<span class="mh-err small">${esc(o.error)}</span>` : ""}</span>
        ${o.status === "failed" ? `<button type="button" class="btn sm" data-mgh="retry" data-id="${o.id}">Send again</button>` : ""}</li>`).join("");
    return `<section class="mh-card"><h3>${icon("send")}Replies</h3><p class="faint small">Sent in order per thread; GitHub's passing errors are retried (5 s, doubling to 5 min).</p>
      <ul class="mal-list mgh-list">${rows}</ul></section>`;
  }

  function page(v) {
    if (!v?.flow) return `<div class="mh-card"><p class="faint">Set up the workflow first: GitHub requests become its tasks.</p></div>`;
    need(v.flow.id);
    if (!d) return failed ? `<div class="mh-card"><p class="mh-err">${icon("alert")}${esc(failed)}</p></div>` : Loading.line("Reading the GitHub link…");
    return `<div class="mgh">${linkCard()}<div class="mal-grid2 mgh-cols">${tasksCard()}${outboxCard()}</div>${intakeCard()}</div>`;
  }

  async function save(f) {
    const fid = dFid; if (!fid) return;
    const body = { repo: f.elements.repo.value, handle: f.elements.handle.value.trim(), allowed: f.elements.allowed.value.split(/[\s,]+/).filter(Boolean),
      start: f.querySelector("[name=start]:checked")?.value || "ask", summaries: f.elements.summaries.checked, on: f.elements.on ? f.elements.on.checked : true };
    if (!body.repo) return Auth.toast("Pick a repository.");
    const b = f.querySelector("[type=submit]"); if (b) b.disabled = true;
    try { d = await api(`${G}/flows/${fid}`, { method: "PUT", body }); note = d.note || ""; dAt = Date.now(); document.activeElement?.blur(); Auth.toast("GitHub link saved"); MiningWork.rerender(); }
    catch (e) { err(e); } finally { if (b?.isConnected) b.disabled = false; }
  }
  async function act(b) {
    const fid = dFid, k = b.dataset.mgh; if (!fid) return;
    if (k === "unlink") return UI.confirm({ title: "Unlink GitHub?", body: "Mentions stop becoming tasks and replies that haven't gone out are dropped. The tasks stay in the Workflow.", ok: "Unlink",
      run: async () => { d = await api(`${G}/flows/${fid}`, { method: "DELETE" }); dAt = Date.now(); Auth.toast("Unlinked"); MiningWork.rerender(); } }).catch(err);
    b.disabled = true;
    try {
      if (k === "poll") { d = await api(`${G}/flows/${fid}/poll`, { method: "POST" }); Auth.toast("Checked GitHub"); MiningWork.reload(); }
      else if (k === "retry") { d = await api(`${G}/outbox/${b.dataset.id}/retry`, { method: "POST" }); Auth.toast("Queued again"); }
      dAt = Date.now(); MiningWork.rerender();
    } catch (e) { err(e); } finally { if (b.isConnected) b.disabled = false; }
  }
  function wire(el) {
    if (wired) return; wired = true;
    el.addEventListener("click", e => { const b = e.target.closest("[data-mgh]"); if (b) act(b); });
    el.addEventListener("submit", e => { const f = e.target.closest("[data-mghform]"); if (f) { e.preventDefault(); save(f); } });
  }
  const count = () => d?.tasks?.filter(t => ["finished", "reviewed", "failed"].includes(t.stage)).length || 0;
  return { page, wire, count };
})();
