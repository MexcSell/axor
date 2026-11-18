/* Competition teams, Improvements (mining_improve.py): a part of the Loadouts tab (mining-loadout.js draws the frame).
   When an engineer's work loses eval tasks against the base it started from, the Improvement Engineer proposes a change to
   its loadout. A trial gives the task it was diagnosed on, and held-out tasks it never saw, to the engineer with the change
   and runs the same eval on each; it's better only when it wins by the margin and loses nothing on the held-out tasks. You
   promote it (only when it measured better) or reject it. An untested proposal can't be applied (Owner decision K-21): to
   make the change anyway, edit the engineer's loadout yourself in Loadouts, with your reason.
   - The top: whether proposals start on their own, and "Ask about <engineer>" with an optional note.
   - A card per proposal: what went wrong (root cause), the change (instructions word by word, skills, model), the trial's
     plan (tasks, margin, runs), its two sides per task and its result, and what you can do now. */
const MiningImprove = (() => {
  const P = "/api/mining/improve";
  const opened = new Set(), notes = {}, checks = {}, helds = {}, margins = {};
  let ask = null;
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const money = x => !x ? "" : x < 0.01 ? "<$0.01" : `$${fmtNum(x, 2)}`;
  const ago = ts => { const s = Date.now() / 1000 - ts; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(ts * 1000).toLocaleDateString(); };
  const ST = { diagnosing: ["run", "Diagnosing"], proposed: ["warn", "Proposed"], nothing: ["none", "No change found"], failed: ["bad", "Diagnosis failed"],
    testing: ["run", "Trial running"], better: ["ok", "Measured better"], same: ["none", "No better"], worse: ["bad", "Measured worse"], trial_failed: ["bad", "Trial failed"],
    promoted: ["ok", "Promoted"], applied: ["ok", "Applied untested"], rejected: ["none", "Rejected"] };
  const ARM = { working: "the engineer is at work", evaluating: "the eval is running", done: "scored", failed: "failed", reused: "the task's own eval" };
  const TESTABLE = ["proposed", "same", "worse", "trial_failed"];
  const signed = d => d > 0 ? `+${d}` : d < 0 ? `−${-d}` : "±0", trend = d => d > 0 ? "up" : d < 0 ? "down" : "";
  const tag = held => `<span class="mi-tag${held ? " held" : ""}">${held ? "Held out" : "Diagnosed"}</span>`;
  const chip = s => { const [c, l] = ST[s] || ["none", s]; return `<span class="hq-chip t-${c}">${["diagnosing", "testing"].includes(s) ? `<i class="mb-spin" aria-hidden="true"></i>` : ""}${l}</span>`; };
  const D = () => MiningLoadout.data();
  const go = (url, body, method = "POST") => api(`${P}${url}`, { method, body });

  // the instructions, word by word: kept words plain, dropped ones struck, new ones marked
  function words(a, b) {
    const A = (a || "").split(/(\s+)/), B = (b || "").split(/(\s+)/), n = A.length, m = B.length;
    if (n * m > 400000) return `<del>${esc(a)}</del> <ins>${esc(b)}</ins>`;
    const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    let i = 0, j = 0, out = "";
    while (i < n || j < m) {
      if (i < n && j < m && A[i] === B[j]) { out += esc(A[i]); i++; j++; }
      else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) out += /^\s+$/.test(B[j]) ? esc(B[j++]) : `<ins>${esc(B[j++])}</ins>`;
      else out += /^\s+$/.test(A[i]) ? esc(A[i++]) : `<del>${esc(A[i++])}</del>`;
    }
    return out;
  }

  // ---------- improve on its own (mining_evolve.py): test, promote, watch, roll back ----------
  const WST = { watching: ["run", "Watching"], kept: ["ok", "Kept"], rolled_back: ["bad", "Rolled back"], ended: ["none", "Ended"] };
  function selfPanel(im) {
    const ev = im.evolve;
    if (!ev) return "";
    const on = im.setting === "self";
    const sw = `<label class="mb-switch"><input type="checkbox" data-miself ${on ? "checked" : ""} ${im.setting === "ask" ? "disabled" : ""}><span><b>Test, promote and roll back on its own</b>
      <small>A proposal is tested at once. One that measures better is promoted, then watched over its next ${ev.window} real outcomes: it stays, or goes back to the version it replaced if it scores more than ${ev.tolerance} points lower.</small></span></label>`;
    if (!on) return sw;
    const pct = ev.cap ? Math.min(100, Math.round(100 * ev.spent / ev.cap)) : 100;
    const watch = w => { const [c, l] = WST[w.status] || ["none", w.status];
      const n = w.status === "watching" ? `${w.basis || 0} of ${ev.window} outcomes so far${w.score != null ? `, score ${w.score}` : ""}` : esc(w.result || "");
      return `<li><span class="hq-chip t-${c}">${w.status === "watching" ? `<i class="mb-spin" aria-hidden="true"></i>` : ""}${l}</span> <b>${esc(w.agent || "An engineer who left")}</b> version ${w.to_version}
        <span class="faint small">(replaced ${w.from_version}${w.baseline != null ? `, score ${w.baseline}` : ""}) · ${ago(w.started)}</span><div class="faint small">${n}</div></li>`; };
    return `${sw}<div class="mi-self">
      <div class="row mi-self-row"><label class="in"><span>Weekly limit for improvements</span><input type="number" min="0" max="${ev.cap_max}" step="1" value="${ev.cap}" data-micap></label>
        <div class="mi-spent"><span class="faint small">Spent in the last 7 days</span><b>${money(ev.spent) || "$0"}</b><span class="mi-bar" role="img" aria-label="${pct}% of the limit"><i style="width:${pct}%"></i></span></div>
        <label class="mb-switch"><input type="checkbox" data-mifreeze ${ev.frozen ? "checked" : ""}><span><b>Freeze</b><small>Nothing new is tested or promoted on its own. Watches still roll back a version that does worse.</small></span></label></div>
      ${ev.watches.length ? `<ul class="mi-watches">${ev.watches.map(watch).join("")}</ul>` : `<p class="faint small">No version promoted on its own yet.</p>`}</div>`;
  }

  // ---------- the part ----------
  function page(d) {
    const im = d.improve;
    if (!im) return `<section class="mh-card"><p class="faint">Improvements aren't running on this server.</p></section>`;
    const eng = d.agents.filter(a => a.role === "engineer");
    const busy = new Set(im.items.filter(x => ["diagnosing", "proposed", "testing", "better"].includes(x.status)).map(x => x.agent_id));
    const a = eng.find(x => x.id === ask);
    return `<section class="mh-card mi-top"><div class="mb-h"><h3>${icon("bulb")}Improvements</h3></div>
        <p class="faint small">When an engineer's work loses eval tasks against the base it started from, the Improvement Engineer (one read-only Claude Code run) looks for the cause in that engineer's loadout and proposes the smallest change. A trial gives the same task, and held-out tasks it never saw, to the engineer with the change, and runs the same eval on each. It measures better only when it wins by the margin and loses nothing on the held-out tasks. ${im.setting === "self" ? "It tests, promotes and rolls back on its own (below)." : "Nothing changes until you promote it."}</p>
        <label class="mb-switch"><input type="checkbox" data-miauto ${im.setting !== "ask" ? "checked" : ""}><span><b>Propose on its own when an eval loses tasks</b><small>Off: only when you ask about an engineer here or on its card.</small></span></label>
        ${selfPanel(im)}
        ${eng.length ? `<div class="row mi-ask-row">${eng.map(x => `<button type="button" class="btn sm" data-miaskopen="${x.id}" ${busy.has(x.id) ? `disabled title="${esc(x.name)} has an open proposal"` : ""} aria-expanded="${ask === x.id}">${icon("bulb")}Ask about ${esc(x.name)}</button>`).join("")}</div>` : ""}
        ${a ? `<div class="mi-ask" data-mbhold><label class="in"><span>Anything you noticed about ${esc(a.name)}'s work (optional)</span><textarea rows="2" data-minote="ask">${esc(notes.ask || "")}</textarea></label>
          <div class="row"><button type="button" class="btn sm primary" data-miask="${a.id}">${icon("send")}Ask the Improvement Engineer</button><button type="button" class="btn sm" data-miaskopen="${a.id}">Cancel</button>
          <span class="faint small">It reads ${esc(a.name)}'s latest work that lost eval tasks, was sent back, dropped or failed a check. One run on the workbench, under $1 of your Claude quota.</span></div></div>` : ""}</section>
      ${im.items.length ? im.items.map(x => card(x, im)).join("") : `<section class="mh-card"><p class="faint small">No proposals yet. They appear after an eval in Review loses tasks against its base, or when you ask.</p></section>`}`;
  }

  function card(x, im) {
    const c = x.candidate || {}, cur = x.current || {}, open = opened.has(x.id) || ["proposed", "better"].includes(x.status);
    const why = x.trigger === "eval" ? "its eval lost tasks" : "you asked";
    const change = Object.keys(c).length ? `<div class="mi-change">
        ${c.instructions ? `<details ${open ? "open" : ""} data-miopen="${x.id}"><summary>New instructions</summary><p class="mi-words">${words(cur.instructions, c.instructions)}</p></details>` : ""}
        ${c.add_skills?.length || c.drop_skills?.length ? `<div class="ml-line"><span class="ml-lbl">${icon("sparkle")}Skills</span><span class="ml-chips">${(c.add_skills || []).map(s => `<span class="ml-chip mi-add">+ ${esc(s)}</span>`).join("")}${(c.drop_skills || []).map(s => `<span class="ml-chip mi-drop">− ${esc(s)}</span>`).join("")}</span></div>` : ""}
        ${c.model ? `<div class="ml-line"><span class="ml-lbl">${icon("chip")}Model</span><span>${esc(cur.model || "?")} → <b>${esc(c.model)}</b></span></div>` : ""}</div>` : "";
    const t = x.trial;
    const groups = [];
    for (const r of x.arms || []) { let g = groups.find(y => y.id === r.task_id); if (!g) groups.push(g = { id: r.task_id, task: r.task, held: r.held, arms: [] }); g.arms.push(r); }
    const side = r => `<span class="mi-side"><b>${r.arm === "candidate" ? "With the change" : "As it is now"}</b> <span class="${r.status === "failed" ? "mh-err" : "faint"} small">${ARM[r.status] || esc(r.status)}${r.error ? `: ${esc(r.error)}` : ""}</span>${r.slug ? ` <code class="mb-branch">${icon("branch")}bench/${esc(r.slug)}</code>` : ""}</span>`;
    const armList = `<ul class="mi-arms">${groups.map(g => `<li>${tag(g.held)} <b>${esc(g.task || "A task that's gone")}</b><div class="mi-sides">${g.arms.sort((p, q) => (p.arm === "current" ? 0 : 1) - (q.arm === "current" ? 0 : 1)).map(side).join("")}</div></li>`).join("")}</ul>`;
    const arms = !groups.length ? "" : x.status === "testing" ? armList : `<details class="mi-runs"><summary>Runs and branches (${groups.length} ${groups.length === 1 ? "task" : "tasks"})</summary>${armList}</details>`;
    const tiles = t ? trialTiles(x, t) : "";
    const sel = im.checks.length > 1 && TESTABLE.includes(x.status) ? `<select data-micheck="${x.id}" aria-label="Eval">${im.checks.map(k => `<option value="${esc(k.id)}" ${(checks[x.id] || x.check_id) === k.id ? "selected" : ""}>${esc(k.label)}</option>`).join("")}</select>` : "";
    const acts = TESTABLE.includes(x.status) ? `${sel}<button type="button" class="btn sm primary" data-mitest="${x.id}" ${im.checks.length ? "" : `disabled title="The folder has no scored check"`}>${icon("play")}${x.status === "proposed" ? "Test it on the eval" : "Test again"}</button>
        <button type="button" class="btn sm" data-mido="reject" data-id="${x.id}">${icon("close")}Reject</button>`
      : x.status === "testing" ? `<button type="button" class="btn sm mw-danger" data-mido="cancel" data-id="${x.id}">${icon("stop")}Cancel the trial</button>`
      : x.status === "better" ? `<button type="button" class="btn sm primary" data-mido="promote" data-id="${x.id}">${icon("check")}Promote: ${esc(x.agent || "the engineer")}'s next version</button><button type="button" class="btn sm" data-mido="reject" data-id="${x.id}">${icon("close")}Reject</button>`
      : x.status === "diagnosing" ? `<button type="button" class="btn sm" data-mido="cancel" data-id="${x.id}">${icon("stop")}Cancel</button>` : `<button type="button" class="btn sm" data-midel="${x.id}">${icon("trash")}Delete</button>`;
    return `<article class="mh-card mi-card st-${esc(x.status)}"><div class="mb-h"><h3>${icon("bulb")}${esc(x.agent || "An engineer who left")}${x.task ? ` <span class="faint small">on “${esc(x.task)}”</span>` : ""}</h3>${chip(x.status)}</div>
      <p class="faint small">#${x.id} · ${why} · ${ago(x.created)}${x.base_version ? ` · proposed for version ${x.base_version}` : ""}${x.version ? ` · now version ${x.version}` : ""}${money(x.cost) ? ` · ${money(x.cost)}` : ""}${x.decided_by ? ` · ${esc(x.decided_by)}` : ""}</p>
      ${x.note ? `<p class="small">${icon("chat")}${esc(x.note)}</p>` : ""}
      ${x.status === "diagnosing" ? `<p>${icon("clock")}The Improvement Engineer is reading ${esc(x.agent || "the engineer")}'s instructions, the task, the diff and what the eval lost…</p>` : ""}
      ${x.root_cause ? `<p class="mi-root"><b>Root cause</b> ${esc(x.root_cause)}</p>` : ""}${x.change ? `<p class="mi-root"><b>The change</b> ${esc(x.change)}</p>` : ""}
      ${change}${TESTABLE.includes(x.status) ? plan(x, im) : ""}${arms}${tiles}${x.result ? `<p class="mi-result ${x.status === "better" ? "ok" : ["worse", "trial_failed", "failed"].includes(x.status) ? "bad" : ""}">${esc(x.result)}</p>` : ""}
      ${t ? `<p class="faint small"><button type="button" class="linkbtn" data-mwsub="lab">${(t.tasks?.length || 1) > 1 ? "Every eval is" : "Both evals are"} in the Lab</button>, as trials.</p>` : ""}
      ${acts ? `<div class="row mb-acts">${acts}</div>` : ""}</article>`;
  }

  // what a trial would run: the diagnosed task, the held-out ones, the margin, and how many runs that is
  const T = im => ({ held: 2, held_max: 4, margin: 2, margin_max: 20, ...(im.trial || {}) });
  function plan(x, im) {
    const p = x.plan, o = T(im);
    if (!p || !im.checks.length) return "";
    const ck = checks[x.id] || x.check_id || im.checks[0].id, most = Math.min(o.held_max, p.held.length);
    const n = Math.min(helds[x.id] ?? o.held, most), m = margins[x.id] ?? (x.margin || o.margin);
    const all = [p.seen, ...p.held.slice(0, n)], reuse = all.filter(y => y.reuse.includes(ck)).length, runs = 2 * all.length - reuse;
    const li = (y, held) => `<li>${tag(held)} ${esc(y.title)} <span class="faint small">${y.reuse.includes(ck) ? "its own eval stands for the current version" : "both versions run"}</span></li>`;
    const opts = (from, to, v, unit) => Array.from({ length: to - from + 1 }, (_, i) => from + i).map(k => `<option value="${k}" ${k === v ? "selected" : ""}>${unit(k)}</option>`).join("");
    return `<div class="mi-plan"><div class="row mi-plan-set">
        ${most ? `<label class="in"><span>Held-out tasks</span><select data-miheld="${x.id}">${opts(0, most, n, k => k ? String(k) : "None")}</select></label>` : ""}
        <label class="in"><span>Better when it wins by</span><select data-mimargin="${x.id}">${opts(1, Math.min(10, o.margin_max), m, k => `${k} eval ${k === 1 ? "task" : "tasks"}`)}</select></label></div>
      <ul class="mi-plan-list">${li(p.seen, false)}${p.held.slice(0, n).map(y => li(y, true)).join("")}</ul>
      <p class="faint small">${plural(runs, "engineer run")} and ${plural(runs, "eval")}${o.parallel ? `, ${o.parallel} at a time on the workbench, queued behind each other and the Workflow's own runs` : ""}.
        Better needs ${signed(m)} or more ${all.length === 1 ? "on the diagnosed task" : `over all ${all.length} tasks`}${n ? " and nothing lost on the held-out ones" : ""}.
        ${!p.held.length ? "The team has no other started task to hold out, so a win would rest on the task it was tuned on." : !n ? "Without held-out tasks, a win rests on the task it was tuned on." : ""}</p></div>`;
  }

  function trialTiles(x, t) {
    const tasks = t.tasks || [{ task: x.task_id, title: x.task, held: false, shared: t.shared, candidate: t.candidate, current: t.current, gained: t.gained, lost: t.lost, reused: t.reused }];
    const net = t.net ?? t.candidate - t.current, seen = t.seen_net ?? net, margin = t.margin || 1;  // an older trial: one task, better by any gain
    return `<div class="lab-tiles mi-tiles">
        <div class="lab-tile"><span>All tasks</span><b class="${trend(net)}">${signed(net)}</b><small>${t.candidate} vs ${t.current} of ${t.shared} eval tasks</small></div>
        <div class="lab-tile"><span>Diagnosed task</span><b class="${trend(seen)}">${signed(seen)}</b><small>what it was tuned on</small></div>
        <div class="lab-tile"><span>Held out</span><b class="${t.held_ran ? trend(t.held_net) : ""}">${t.held_ran ? signed(t.held_net) : "—"}</b><small>${t.held_ran ? `${plural(t.held_ran, "task")} it never saw` : t.held_planned ? "none finished" : "none in the trial"}</small></div>
        <div class="lab-tile"><span>Margin</span><b>${signed(margin)}</b><small>${net >= margin ? "cleared" : "not cleared"}</small></div></div>
      <ul class="mi-per">${tasks.map(p => { const d = p.candidate - p.current; return `<li>${tag(p.held)} <span class="mi-per-t">${esc(p.title || "A task that's gone")}</span>
        <b class="${trend(d)}">${signed(d)}</b> <span class="faint small">${p.candidate} vs ${p.current} of ${p.shared}${p.reused ? " · the task's own eval" : ""}${p.gained?.length ? ` · gained ${esc(p.gained.slice(0, 4).join(", "))}` : ""}${p.lost?.length ? ` · lost ${esc(p.lost.slice(0, 4).join(", "))}` : ""}</span></li>`; }).join("")}</ul>`;
  }

  // ---------- events (mining-loadout.js forwards the root's) ----------
  async function act(btn, fn, done) {
    const nv = await MiningBench.act(btn, fn);
    if (nv) { MiningLoadout.set(nv); if (done) Auth.toast(done); }
    return nv;
  }
  function wire(el) {
    el.addEventListener("input", e => { if (e.target.matches("[data-minote]")) notes[e.target.dataset.minote] = e.target.value; });
    el.addEventListener("change", async e => {
      const t = e.target;
      if (t.matches("[data-micheck]")) { checks[t.dataset.micheck] = t.value; return MiningWork.rerender(); }
      if (t.matches("[data-miheld]")) { helds[t.dataset.miheld] = +t.value; return MiningWork.rerender(); }
      if (t.matches("[data-mimargin]")) { margins[t.dataset.mimargin] = +t.value; return MiningWork.rerender(); }
      if (t.matches("[data-miauto]")) await act(null, () => go(`/flows/${D().flow}`, { improve: t.checked ? "auto" : "ask" }, "PATCH"), t.checked ? "Proposals start on their own" : "Proposals only when you ask");
      if (t.matches("[data-miself]")) await act(null, () => go(`/flows/${D().flow}`, { improve: t.checked ? "self" : "auto" }, "PATCH"), t.checked ? "Improvements now test, promote and roll back on their own" : "Proposals wait for you again");
      const evo = body => act(null, () => api(`/api/mining/evolve/flows/${D().flow}`, { method: "PATCH", body }));
      if (t.matches("[data-micap]")) { const v = Math.max(0, +t.value || 0); await evo({ cap: v }); Auth.toast(`Weekly limit: $${fmtNum(v, 2)}`); }
      if (t.matches("[data-mifreeze]")) { await evo({ frozen: t.checked }); Auth.toast(t.checked ? "Frozen: nothing new starts on its own" : "Unfrozen"); }
    });
    el.addEventListener("toggle", e => { const d = e.target.closest?.("[data-miopen]"); if (d) d.open ? opened.add(+d.dataset.miopen) : opened.delete(+d.dataset.miopen); }, true);
    el.addEventListener("click", async e => {
      const t = e.target;
      const ao = t.closest("[data-miaskopen]");
      if (ao) { const id = +ao.dataset.miaskopen; ask = ask === id ? null : id; MiningLoadout.show("improve"); return MiningWork.rerender(); }
      const ak = t.closest("[data-miask]");
      if (ak) { const nv = await act(ak, () => go(`/agents/${ak.dataset.miask}/ask`, { note: notes.ask || "" }), "The Improvement Engineer is on it"); if (nv) { ask = null; notes.ask = ""; } return; }
      const ts = t.closest("[data-mitest]");
      if (ts) {
        const id = +ts.dataset.mitest, x = D()?.improve?.items.find(y => y.id === id), o = T(D()?.improve || {});
        const held = Math.min(helds[id] ?? o.held, x?.plan?.held.length ?? 0);
        return act(ts, () => go(`/${id}/test`, { check: checks[id] || null, held, margin: margins[id] ?? (x?.margin || o.margin) }),
          held ? `Trial started: the candidate does the task and ${plural(held, "held-out task")}, then the eval scores each` : "Trial started: the candidate does the task again, then the eval scores it");
      }
      const dc = t.closest("[data-mido]");
      if (dc) {
        const k = dc.dataset.mido, id = +dc.dataset.id, x = D()?.improve?.items.find(y => y.id === id);
        const run = () => go(`/${id}/decide`, { decision: k });
        if (k === "reject") return UI.confirm({ title: "Reject this proposal?", ok: "Reject", body: "The trial's branches are deleted. The engineer's loadout stays as it is.", run: async () => MiningLoadout.set(await run()) }).catch(err);
        return act(dc, run, k === "promote" ? `${x?.agent || "The engineer"} has a new version` : k === "cancel" ? (x?.status === "diagnosing" ? "Diagnosis cancelled" : "Trial cancelled") : "");
      }
      const dl = t.closest("[data-midel]");
      if (dl) return act(dl, () => go(`/${dl.dataset.midel}`, undefined, "DELETE"), "Deleted");
    });
  }
  return { page, wire };
})();
