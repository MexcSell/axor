/* Competition teams, release discipline (mining_release.py), a card on the Status sub-tab (mining-status.js puts
   MiningRelease.card(v) in its grid):
   - The release manifest: the one frozen candidate (a team file and its sha256, or a commit), its benchmark suite and reference
     score, whether the file changed since; freeze one (again) from the form. Open tasks naming another candidate are listed.
   - Benchmarks the agents filed with record_benchmark: comparable ones against the reference, the rest with why they aren't.
   - Duplicate tasks on the board: each group with the copy that stays; Merge removes the unstarted copies.
   - Tasks the duplicate check left off the board (a lead's plan or an agent's follow-up that repeated an open task): the check
     compares words, so it can be wrong; Add anyway puts one on the board and that title is never held back over that task again. */
const MiningRelease = (() => {
  const W = "/api/mining/work";
  let data = null, wid = null, at = 0, loading = false, failed = "", wired = false;
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const num = x => x == null ? "–" : fmtNum(x, Math.abs(x) < 10 && x % 1 ? 1 : x % 1 ? 1 : 0);

  function need(v) {
    if (wid !== v.comp.id) { data = null; wid = v.comp.id; at = 0; failed = ""; }
    if (loading || Date.now() - at < 15000) return;
    loading = true;
    const me = wid;
    api(`${W}/comps/${me}/release`).then(r => { if (wid === me) { data = r; failed = ""; } })
      .catch(e => { failed = e.message; }).finally(() => { at = Date.now(); loading = false; if (wid === me) MiningWork.rerender(); });
  }
  const task = (t, extra = "") => `<button type="button" class="linkbtn" data-mwtask="${t.id}">#${t.id} ${esc(t.title)}</button>${extra}`;

  function manifest(m) {
    if (!m) return `<p class="mrl-none">${icon("alert")}<span><b>No release candidate is frozen.</b> Agents are told to name the exact hash they measure, but nothing keeps audits and benchmarks on one candidate until you freeze it below.</span></p>`;
    const cand = m.path ? `<code>${esc(m.path)}</code> <code class="small" title="${esc(m.sha256)}">${esc(m.sha256.slice(0, 12))}</code>` : `commit <code title="${esc(m.commit)}">${esc(m.commit.slice(0, 12))}</code>`;
    const set = Object.entries(m.settings || {}).map(([k, x]) => `${esc(k)} ${esc(String(x))}`).join(" · ");
    return `<dl class="ms-dl mrl-dl">
        <dt>Candidate</dt><dd>${cand} <span class="hq-chip t-${m.drift ? "warn" : "ok"}">${m.drift ? `${icon("alert")}Changed since frozen` : `${icon("check")}v${m.version}`}</span></dd>
        <dt>Suite</dt><dd><b>${esc(m.suite)}</b> <code class="small">${esc(m.suite_id.split("@")[1] || "")}</code> · ${plural(m.suite_tasks, "task")} × ${plural(m.repeats, "repeat")}${set ? ` · ${set}` : ""}</dd>
        <dt>Reference</dt><dd>${m.reference_score != null ? `<b>${num(m.reference_score)}</b>${m.reference_note ? ` <span class="faint small">${esc(m.reference_note)}</span>` : ""}` : `<span class="faint">none yet: results show without a delta</span>`}</dd>
        <dt>Measuring job</dt><dd>${m.measure ? `<b>Frozen</b> from job #${m.measure.from_job}: candidate under <code>${esc(m.measure.candidate_root)}/</code>, job <code class="small" title="${esc(m.measure.job_sha256)}">${esc(m.measure.job_sha256.slice(0, 12))}</code>, harness <code class="small" title="${esc(m.measure.harness_sha256)}">${esc(m.measure.harness_sha256.slice(0, 12))}</code>, ${plural(m.measure.images.length, "pulled image")}, score file <code class="small">${esc(m.measure.score_file)}</code>. <span class="faint small">Only that job's scores count as measured for this release.</span>`
          : `<span class="faint">none: any job's score file counts under this suite's name</span>`}</dd>
        <dt>Frozen</dt><dd>${ago(m.frozen)} by ${esc(m.by || "?")}${m.note ? ` · ${esc(m.note)}` : ""}</dd></dl>
      ${m.drift ? `<p class="mh-err small">${icon("alert")}${esc(m.path)} changed after the freeze: results measured on it aren't the frozen candidate. Freeze again if the change is the new candidate.</p>` : ""}`;
  }

  function form(d) {
    const m = d.manifest;
    const files = (d.files || []).filter(p => !p.startsWith("data/web/"));
    return `<details class="mrl-form"${m ? "" : " open"}><summary>${icon("lock")}${m ? "Freeze a new candidate" : "Freeze the release candidate"}</summary>
      <form data-mrl-form>
        <div class="mrl-row"><label>Candidate file<select name="path"><option value="">— a commit / artifact hash instead —</option>${files.map(p => `<option ${m?.path === p || (!m && /(^|\/)agent\.py$/.test(p)) ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
          <label>or hash<input name="commit" pattern="[0-9a-fA-F]{7,64}" placeholder="abc1234…" value="${esc(m?.commit || "")}" list="mrl-seen"></label></div>
        ${d.seen?.length ? `<datalist id="mrl-seen">${d.seen.map(s => `<option value="${esc(s.hash)}">${plural(s.tasks, "open task")}</option>`).join("")}</datalist>
          <p class="faint small">Hashes the open board names: ${d.seen.map(s => `<code>${esc(s.hash)}</code> (${s.tasks})`).join(", ")}</p>` : ""}
        <div class="mrl-row"><label>Suite<input name="suite" required maxlength="80" value="${esc(m?.suite || "")}" placeholder="polyglot-29"></label>
          <label>Tasks<input name="tasks" type="number" min="1" required value="${m?.suite_tasks || ""}"></label>
          <label>Repeats<input name="repeats" type="number" min="1" max="100" value="${m?.repeats || 1}"></label>
          <label>Reference score<input name="reference_score" type="number" step="any" value="${m?.reference_score ?? ""}"></label></div>
        <label>Task ids <span class="faint small">(optional, one per line or comma-separated: fixes the exact task set)</span><textarea name="task_ids" rows="2"></textarea></label>
        <div class="mrl-row"><label>Measuring job <span class="faint small">(optional: the number of a finished VM job that scored this suite)</span><input name="measure_job" type="number" min="1" value="${m?.measure?.from_job ?? ""}" placeholder="e.g. 412"></label>
          <label>Candidate folder <span class="faint small">(what a candidate may change; the rest of that job's files is its harness)</span><input name="candidate_root" maxlength="200" pattern="[A-Za-z0-9_][A-Za-z0-9._/@+\-]*" value="${esc(m?.measure?.candidate_root || "")}" placeholder="miner"></label></div>
        <p class="faint small">With a measuring job frozen, a score counts as measured for this release only when that same job gave it: the same command, harness files, pulled images and score file. Another job's score, your own validator's for example, is kept and not counted. Give both fields or neither.</p>
        <label>Note<input name="note" maxlength="1000" placeholder="Why this candidate"></label>
        <p class="row"><button type="submit" class="btn primary sm">${icon("lock")}Freeze</button><span class="faint small">Every agent's context names this candidate and suite from its next run.</span></p>
      </form></details>`;
  }

  function card(v) {
    need(v); wire();
    if (failed) return `<section class="mh-card ms-card ms-wide"><h3>${icon("lock")}Release & benchmarks</h3><p class="mh-err small">${esc(failed)}</p></section>`;
    if (!data) return `<section class="mh-card ms-card ms-wide"><h3>${icon("lock")}Release & benchmarks</h3><p class="faint small">Loading…</p></section>`;
    const d = data;
    const conflicts = d.conflicts.length ? `<h4>${icon("alert")}${plural(d.conflicts.length, "open task")} name another candidate</h4>
      <ul class="mrl-list">${d.conflicts.slice(0, 12).map(c => `<li>${task(c, ` <span class="faint small">names ${c.names.map(h => `<code>${esc(h)}</code>`).join(", ")}</span>`)}</li>`).join("")}</ul>` : "";
    const res = d.results.length ? `<h4>${icon("chart")}Benchmarks <span class="faint small">${d.comparable} comparable · ${d.other} not</span></h4>
      <div class="lab-scroll"><table class="mini-table mrl-tbl"><thead><tr><th>Result</th><th>Candidate</th><th>Suite</th><th>Against the reference</th><th>By</th></tr></thead><tbody>
      ${d.results.map(r => `<tr class="${r.current ? "" : "faint"}"><td><b>${num(r.score)}</b>${r.solved != null ? ` <span class="small">${r.solved}/${r.tasks}</span>` : ""}</td>
        <td><code class="small">${esc(r.candidate || "?")}</code></td><td class="small">${esc(r.suite)} · ${r.tasks}×${r.repeats}</td>
        <td>${r.current ? (r.delta != null ? `<span class="hq-chip t-${r.delta > 0 ? "ok" : r.delta < 0 ? "bad" : "none"}">${r.delta > 0 ? "+" : ""}${num(r.delta)}</span>` : `<span class="hq-chip t-ok">comparable</span>`)
          : `<span class="hq-chip t-warn" title="${esc(r.why || "")}">not comparable</span> <span class="small">${esc(r.why || "an earlier manifest")}</span>`}</td>
        <td class="small">${esc(r.agent || "")}${r.task ? ` · <button type="button" class="linkbtn" data-mwtask="${r.task}">#${r.task}</button>` : ""} · ${ago(r.ts)}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="faint small">No benchmark filed yet. Agents file them with <b>record_benchmark</b>.</p>`;
    const mergeable = d.dupes.reduce((n, g) => n + g.mergeable, 0);
    const dupes = d.dupes.length ? `<h4>${icon("copy")}${plural(d.dupe_tasks, "duplicate task")} on the board</h4>
      <ul class="mrl-list">${d.dupes.slice(0, 15).map(g => `<li><span>${task(g.keep, ` <span class="hq-chip t-none">stays${g.keep.agent ? ` · ${esc(g.keep.agent)}` : ""}</span>`)}
        <span class="faint small">repeated by ${g.copies.map(c => `#${c.id}${c.status !== "todo" ? ` (${esc(c.status)})` : ""}`).join(", ")}${g.under_way ? ` · ${plural(g.under_way, "copy", "ies")} already under way stay${g.under_way === 1 ? "s" : ""}` : ""}</span></span></li>`).join("")}</ul>
      ${mergeable ? `<p class="row"><button type="button" class="btn sm" data-mrl="merge">${icon("branch")}Merge ${plural(mergeable, "duplicate")}</button><span class="faint small">Unstarted copies go; the one that stays lists them and keeps one owner.</span></p>` : ""}`
      : `<p class="ms-ok small">${icon("check")}No duplicate tasks on the board. New repeats the lead plans are left out by themselves.</p>`;
    const sk = d.skipped || [];
    const skipped = sk.length ? `<details class="mrl-skip"${sk.some(x => Date.now() / 1000 - x.ts < 86400) ? " open" : ""}><summary>${icon("ban")}${plural(sk.length, "task")} left off the board as repeats <span class="faint small">last 14 days</span></summary>
      <p class="faint small">The check compares a new task's words, the candidate hash it names and its acceptance criteria with the open board. If one isn't really a repeat, add it back.</p>
      <ul class="mrl-list">${sk.map(x => `<li class="mrl-sk"><span><b>${esc(x.title)}</b> <span class="faint small">${esc(x.by || "An agent")}'s ${x.origin} · ${ago(x.ts)}</span><br>
        <span class="small">repeats ${x.dup.title ? task(x.dup, x.dup.status ? ` <span class="faint">(${esc(x.dup.status)})</span>` : "") : `#${x.dup.id} <span class="faint">(no longer on the board)</span>`}</span></span>
        <button type="button" class="btn sm" data-mrl="restore" data-sid="${x.id}" title="Put it on the board as it was asked for">${icon("plus")}Add anyway</button></li>`).join("")}</ul></details>` : "";
    return `<section class="mh-card ms-card ms-wide mrl"><h3>${icon("lock")}Release & benchmarks</h3>
      ${manifest(d.manifest)}${conflicts}${form(d)}${res}${dupes}${skipped}
      ${d.history.length ? `<details class="mrl-hist"><summary class="small">${plural(d.history.length, "earlier manifest")}</summary><ul class="mrl-list">${d.history.map(h => `<li class="small">v${h.version} · <code>${esc(h.candidate)}</code> · ${esc(h.suite_id)} · ${ago(h.frozen)} by ${esc(h.by || "?")}</li>`).join("")}</ul></details>` : ""}
    </section>`;
  }

  async function freeze(f) {
    const fd = new FormData(f), n = k => fd.get(k) === "" || fd.get(k) == null ? null : +fd.get(k);
    const body = { path: fd.get("path") || "", commit: (fd.get("commit") || "").trim(), suite: (fd.get("suite") || "").trim(), tasks: n("tasks"),
      repeats: n("repeats") || 1, reference_score: n("reference_score"), note: (fd.get("note") || "").trim(),
      task_ids: (fd.get("task_ids") || "").split(/[\n,]+/).map(s => s.trim()).filter(Boolean),
      measure_job: n("measure_job"), candidate_root: (fd.get("candidate_root") || "").trim().replace(/^\/+|\/+$/g, "") };
    if (body.path) body.commit = "";
    const b = f.querySelector("[type=submit]"); b.disabled = true;
    try { data = await api(`${W}/comps/${wid}/release`, { method: "POST", body }); at = Date.now(); Auth.toast(`Release v${data.manifest.version} frozen`); MiningWork.rerender(); }
    catch (e) { err(e); } finally { if (b.isConnected) b.disabled = false; }
  }

  function merge() {
    const n = data.dupes.reduce((k, g) => k + g.mergeable, 0);
    UI.confirm({ title: `Merge ${plural(n, "duplicate task")}?`, body: "The unstarted copies are removed; the task that stays lists them and keeps one owner. Copies already under way aren't touched.",
      ok: "Merge", icon: "branch", danger: false,
      run: async () => { const r = await api(`${W}/comps/${wid}/dedupe`, { method: "POST", body: {} }); data = r; at = Date.now(); Auth.toast(`${plural(r.merged, "duplicate")} merged`); MiningWork.reload(); } }).catch(err);
  }

  async function restore(b) {
    b.disabled = true;
    try { const r = await api(`${W}/comps/${wid}/skipped/${b.dataset.sid}/restore`, { method: "POST", body: {} }); data = r; at = Date.now(); Auth.toast(`Added back as #${r.task}`); MiningWork.reload(); }
    catch (e) { err(e); if (b.isConnected) b.disabled = false; }
  }

  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const b = e.target.closest("[data-mrl]"); if (!b || !data) return;
      if (b.dataset.mrl === "merge") merge();
      if (b.dataset.mrl === "restore") restore(b);
    });
    document.addEventListener("submit", e => { const f = e.target.closest("[data-mrl-form]"); if (f) { e.preventDefault(); freeze(f); } });
  }
  const fresh = () => { at = 0; };
  return { card, fresh };
})();
