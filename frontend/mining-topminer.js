/* Competition teams, Top miner (mining_topminer.py), a sub-tab of the Competition teams page (mining-work.js draws the page):
   - Roadmap M0-M5 (contract, reliability, validation infrastructure, quality, cost and speed, submission), each with its time box, success criterion, the evidence read from the Lab and the Command center, and a
     status the user can set by hand.
   - Scorecard from the newest Lab eval on the validation set: correctness, reliability, efficiency, generalization, quality per
     dollar-hour; competition performance (official score and rank) apart. Per-category correctness and the eval trend.
   - Validation set: coverage per category, held-out share and edge cases; add, import from the Lab or a list, edit, delete.
   - Elite team: the 13 critical-path roles filled from the team.
   - The first 30-minute mission: put it on the board, follow its tasks against the clock. */
const MiningTopMiner = (() => {
  const W = "/api/mining/work";
  let d = null, dWid = null, dAt = 0, loading = false, failed = "", wired = false, setOpen = false;
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const pct = x => x == null ? "–" : `${fmtNum(x * 100, x < 0.1 && x > 0 ? 1 : 0)}%`;
  const usd = x => x == null ? "–" : `$${fmtNum(x, x < 1 ? 3 : 2)}`;
  const mmss = s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const when = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const ST = { done: ["Done", "ok", "check"], doing: ["In progress", "info", "cycle"], todo: ["To do", "none", "dots"] };
  const TS = { todo: "To do", queued: "Queued", working: "Working", checking: "Checking", review: "For you", blocked: "Blocked", done: "Done", deleted: "Deleted" };

  function need(v) {
    const wid = v.comp.id;
    if (dWid !== wid) { d = null; dWid = wid; dAt = 0; failed = ""; }
    if (loading || Date.now() - dAt < (d?.mission?.status === "running" ? 5000 : 15000)) return;
    loading = true;
    api(`${W}/comps/${wid}/topminer`).then(x => { if (dWid === wid) { d = x; failed = ""; } })
      .catch(e => { failed = e.message; }).finally(() => { dAt = Date.now(); loading = false; if (dWid === wid && !holding() && document.querySelector(".tpm")) MiningWork.rerender(); });
  }
  const holding = () => !!document.activeElement?.closest?.(".tpm-form, .tpm-note");

  // ---------- roadmap ----------
  function roadmap() {
    return `<section class="mh-card tpm-card"><h3>${icon("map")}Top miner roadmap</h3>
      <p class="faint small">Understand the contract, make the miner reliable, build the validation set, then improve correctness against its baseline, then speed and cost. Each step reads its evidence from the Lab and the Command center; you can also set it by hand.</p>
      <ol class="tpm-road">${d.roadmap.map(m => { const [l, tone, ic] = ST[m.status];
        return `<li class="tpm-ms s-${m.status}"><div class="tpm-ms-top"><span class="tpm-ms-ic">${icon(ic)}</span><b><span class="tpm-num">${esc(m.num || "")}</span>${esc(m.name || m.title)}</b><span class="faint small">${esc(m.time)}</span></div>
          <p class="small">${esc(m.success)}</p><p class="tpm-ev small">${icon("info")}${esc(m.evidence)}</p>
          <div class="tpm-ms-foot"><span class="hq-chip t-${tone}">${l}${m.mark && m.mark.status !== "auto" ? " · set by hand" : ""}</span>
            <select class="tpm-note" data-tpmmark="${m.key}" aria-label="Status of ${esc(m.title)}">${[["auto", `From evidence (${ST[m.auto][0].toLowerCase()})`], ["todo", "To do"], ["doing", "In progress"], ["done", "Done"]]
              .map(([k, t]) => `<option value="${k}" ${(m.mark?.status || "auto") === k ? "selected" : ""}>${t}</option>`).join("")}</select></div>
          ${m.mark?.note ? `<p class="faint small">${esc(m.mark.by_user || "")}: ${esc(m.mark.note)}</p>` : ""}</li>`; }).join("")}</ol></section>`;
  }

  // ---------- scorecard ----------
  function scorecard() {
    const s = d.scorecard, p = d.previous, o = d.official;
    const delta = (a, b, fmt, down) => { if (a == null || b == null || a === b) return ""; const up = a > b; return `<em class="${up !== !!down ? "up" : "down"}">${up ? "▲" : "▼"} ${fmt(Math.abs(a - b))}</em>`; };
    const tile = (label, value, sub, extra = "", cls = "") => `<div class="tpm-tile ${cls}"><span class="tpm-lbl">${label}</span><b>${value}</b>${extra}<span class="faint small">${sub}</span></div>`;
    const official = `<div class="tpm-tile tpm-official"><span class="tpm-lbl">${icon("trophy")}Competition performance</span>
        <b>${o.rank ? `#${fmtNum(o.rank.value, 0)}` : o.score ? fmtNum(o.score.value, 3) : "–"}</b><span class="faint small">${o.rank ? `official rank${o.score ? ` · score ${fmtNum(o.score.value, 3)}` : ""} · ${when(o.last || o.rank.ts)}` : o.score ? `official score · ${when(o.score.ts)}` : "Not measured: connect the evaluator in the Command center"}</span>
        <span class="tpm-sep small">Official, kept apart from the internal scores: see Official results.</span></div>`;
    if (!s) return `<section class="mh-card tpm-card"><h3>${icon("chart")}Miner quality scorecard</h3>
      <p class="faint small">No Lab eval has run tasks of the validation set yet. Add tasks below, then run a scored check from the Lab tab (or import an earlier eval there).</p><div class="tpm-tiles">${official}</div></section>`;
    const a = s.all, pa = p?.all;
    const cats = Object.entries(s.categories).filter(([, x]) => x);
    return `<section class="mh-card tpm-card"><h3>${icon("chart")}Miner quality scorecard</h3>
      <p class="faint small">From eval “${esc(s.eval.label || `#${s.eval.id}`)}”${s.eval.head ? ` at ${esc(s.eval.head.slice(0, 8))}` : ""}, ${when(s.eval.finished)}, on ${plural(a.tasks, "task")} of the set${s.missing ? ` (${s.missing} not in this eval)` : ""}${p ? `; arrows compare it with “${esc(p.eval.label || `#${p.eval.id}`)}”` : ""}.</p>
      <div class="tpm-tiles">
        ${tile("Correctness", pct(a.correct), `${a.solved} of ${a.tasks} solved, every run passing`, pa ? delta(a.correct, pa.correct, pct) : "", "tpm-first")}
        ${tile("Reliability", pct(a.pass_rate), `of ${plural(a.runs, "run")} passed${a.finished != null ? ` · ${pct(a.finished)} finished` : ""}`, pa ? delta(a.pass_rate, pa.pass_rate, pct) : "")}
        ${tile("Efficiency", usd(a.cost_solved), a.cost_solved != null ? `per solved task · ${fmtNum(a.secs_solved, 0)} s` : `${usd(a.cost)} spent, nothing solved`, pa ? delta(a.cost_solved, pa.cost_solved, usd, true) : "")}
        ${tile("Generalization", s.held ? pct(s.held.correct) : "–", s.held ? `held out (${s.held.tasks}) vs ${s.dev ? pct(s.dev.correct) : "–"} dev${s.gap != null && s.gap > 0.15 ? " · a big gap: fitted to dev?" : ""}` : "No held-out tasks in this eval")}
        ${tile("Quality", a.quality != null ? fmtNum(a.quality, 2) : "–", "solved ÷ (dollars × hours) · internal only")}
        ${official}</div>
      ${cats.length ? `<table class="tpm-cats"><thead><tr><th>Category</th><th>Tasks</th><th>Solved</th><th>Correct</th><th>Per solved</th></tr></thead><tbody>${cats.map(([k, x]) => `<tr><td>${esc(d.categories[k].label)}</td><td class="num">${x.tasks}</td><td class="num">${x.solved}</td><td class="num">${pct(x.correct)}</td><td class="num">${usd(x.cost_solved)}</td></tr>`).join("")}</tbody></table>` : ""}
      ${d.trend.length > 1 ? `<div class="tpm-trend" aria-label="Correctness by eval">${d.trend.map(t => `<span title="${esc(t.eval.label || `#${t.eval.id}`)}: ${pct(t.correct)} correct${t.held != null ? `, ${pct(t.held)} held out` : ""}"><i style="--h:${Math.max(2, t.correct * 100)}%"></i><em>${esc((t.eval.label || `#${t.eval.id}`).slice(0, 10))}</em></span>`).join("")}</div>` : ""}</section>`;
  }

  // ---------- official results: what the competition itself measured, never the Lab's scores ----------
  function officialCard() {
    const o = d.official || {}, n = x => x == null ? "–" : fmtNum(x, 3);
    const v = (k, f) => o[k] ? f(o[k].value) : null;
    const rows = [
      ["Official miner rank", v("rank", x => `#${fmtNum(x, 0)}`)],
      ["Leader's score", v("leader_score", n)],
      ["Our latest official score", v("score", n)],
      ["Gap to the leader", o.gap ? n(o.gap.value) : null],
      ["Approved submissions", o.submissions != null ? String(o.submissions) : null],
      ["Latest submission", o.submission ? `${esc(o.submission.version || "?")} · ${esc(o.submission.status || "")} · ${when(o.submission.ts)}` : null],
      ["Correctness (official)", v("correctness", pct)],
      ["Reliability (task success)", v("success_rate", pct)],
      ["Cost per solved task", v("cost_task", usd)],
      ["Time per task (P50)", v("latency_p50", x => `${fmtNum(x / 1000, 1)} s`)],
      ["Latest official evaluation", o.last ? when(o.last) : null]];
    const got = rows.filter(r => r[1] != null).length;
    return `<section class="mh-card tpm-card tpm-off"><h3>${icon("trophy")}Official results <span class="hq-n">${got}/${rows.length}</span></h3>
      <p class="faint small">What the competition's evaluator reported (Command center → Performance Lab, or entered by hand there). The competition judges miners on hidden test sets in its own sandbox, so the internal scorecard is never shown as a rank.${o.evaluations ? ` ${plural(o.evaluations, "evaluator report")} so far.` : ""}</p>
      <dl class="tpm-dl">${rows.map(([k, x]) => `<div><dt>${k}</dt><dd>${x ?? `<span class="faint">Not reported</span>`}</dd></div>`).join("")}</dl>
      ${got ? "" : `<p class="tpm-warn small">${icon("info")}The objective is a top miner rank, but nothing official is measured yet: connect the evaluator in the Command center.</p>`}</section>`;
  }

  // ---------- validation set ----------
  function setCard() {
    const t = d.targets, n = d.set.length, held = d.set.filter(r => r.split === "held").length;
    const sel = (name, opts, cur, attrs = "") => `<select name="${name}" ${attrs}>${Object.entries(opts).map(([k, l]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${esc(l.label || l)}</option>`).join("")}</select>`;
    const cats = Object.fromEntries(Object.entries(d.categories).map(([k, x]) => [k, x.label]));
    return `<section class="mh-card tpm-card tpm-set"><h3>${icon("list")}Validation set <span class="hq-n">${n}</span></h3>
      <p class="faint small">${t.total} tasks: ${t.per_category} per category (${t.dev_per_category} development to improve on, ${t.held_per_category} held out to judge with), PostgreSQL and ClickHouse, real repository tasks. Held-out tasks judge a change and are never used to make one. Names match the eval's task names, so the Lab scores them. A suggested start, not the competition's official test distribution.</p>
      ${d.gaps?.length && n ? `<ul class="tpm-gaps small">${d.gaps.map(g => `<li>${icon(/No development|No held-out/.test(g) ? "alert" : "info")}${esc(g)}</li>`).join("")}</ul>` : ""}
      <div class="tpm-cov">${Object.entries(d.categories).map(([k, c]) => `<div class="tpm-cv"><span class="small">${esc(c.label)}</span><span class="tpm-bar"><i style="--w:${Math.min(100, c.count / t.per_category * 100)}%"></i></span><span class="faint small">${c.count}/${t.per_category} · ${c.count - c.held} dev · ${c.held} held</span></div>`).join("")}</div>
      <p class="small tpm-edges">${n ? `${pct(held / n)} held out${held / n < t.held || held / n > t.held_max ? ` <b class="tpm-warn">(aim for ${pct(t.held)}–${pct(t.held_max)})</b>` : ""} · ` : ""}Edge cases: ${Object.entries(d.edges).map(([k, l]) => `<span class="hq-chip ${d.coverage[k] ? "t-ok" : "t-none"}">${esc(l)} ${d.coverage[k]}</span>`).join(" ")}</p>
      <div class="row tpm-acts"><button type="button" class="btn sm" data-tpm="lab">${icon("download")}Import from the Lab's evals</button>
        <details class="tpm-paste" ${setOpen ? "open" : ""}><summary class="btn sm">${icon("plus")}Add tasks</summary>
          <form class="tpm-form" data-tpmform="one"><input name="name" placeholder="Task name, as in the eval (e.g. ch-top-pages-pruning-001)" required maxlength="200">
            ${sel("category", cats, "generation")}${sel("engine", d.engines, "postgres")}${sel("split", { dev: "Dev", held: "Held out" }, "dev")}<button type="submit" class="btn sm primary">Add</button></form>
          <form class="tpm-form" data-tpmform="many"><textarea name="names" rows="3" placeholder="Or paste many names, one per line: category and engine are guessed from the name, one in five held out"></textarea><button type="submit" class="btn sm">Add the list</button></form></details></div>
      ${n ? `<div class="tpm-tablewrap"><table class="tpm-tbl"><thead><tr><th>Task</th><th>Category</th><th>Database</th><th>Split</th><th>Edge cases</th><th></th></tr></thead><tbody>${d.set.map(r => `<tr>
          <td class="tpm-nm" title="${esc(r.name)}">${esc(r.name)}</td>
          <td>${sel("category", cats, r.category, `data-tpmset="${r.id}" aria-label="Category"`)}</td>
          <td>${sel("engine", d.engines, r.engine, `data-tpmset="${r.id}" aria-label="Database"`)}</td>
          <td>${sel("split", { dev: "Dev", held: "Held out" }, r.split, `data-tpmset="${r.id}" aria-label="Split"`)}</td>
          <td class="small">${r.edges.map(e => esc(d.edges[e] || e)).join(", ") || `<span class="faint">–</span>`}</td>
          <td><button type="button" class="iconbtn" data-tpmdel="${r.id}" aria-label="Remove ${esc(r.name)}" title="Remove">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>` : ""}</section>`;
  }

  // ---------- elite team and the first mission ----------
  function elite() {
    const n = d.elite.reduce((s, r) => s + r.agents.length, 0), need_ = d.elite.reduce((s, r) => s + r.need, 0);
    return `<section class="mh-card tpm-card"><h3>${icon("users")}Elite miner team <span class="hq-n">${n}/${need_}</span></h3>
      <p class="faint small">The roles on the miner's critical path, filled from this team by squad and title. The other ${plural(d.support.length, "agent")} support: research, knowledge, work on demand.</p>
      <div class="tpm-roles">${d.elite.map(r => `<div class="tpm-role"><b>${esc(r.label)} <span class="faint small">${r.agents.length}/${r.need}</span></b><span class="faint small">${esc(r.about)}</span>
        <span class="tpm-ags">${r.agents.map(a => `<span class="hq-chip t-none" title="${esc(a.title)}">${esc(a.name)}</span>`).join("")}${r.agents.length < r.need ? `<span class="hq-chip t-warn">${r.need - r.agents.length} open</span>` : ""}</span></div>`).join("")}</div></section>`;
  }
  function mission() {
    const m = d.mission, live = m?.status === "running";
    const head = `<h3>${icon("rocket")}First mission: top miner first milestone</h3>
      <p class="faint small">A bounded ${d.mission_minutes}-minute investigation with a prioritized result: find the highest-impact weaknesses that keep the miner from reliable submissions and prepare fixes. ${d.mission_plan.length} tasks for the elite team; finishing all of them in the time box isn't promised, and what's left is reported. Nothing is uploaded or submitted, no secrets are exposed, the production miner stays as it is; the team works on an isolated candidate and reports what's unfinished at the deadline.</p>`;
    if (!m) return `<section class="mh-card tpm-card">${head}<ol class="tpm-plan small">${d.mission_plan.map(t => `<li>${esc(t.title)} <span class="faint">· ${esc(t.role)}</span></li>`).join("")}</ol>
      <div class="row"><button type="button" class="btn primary sm" data-tpm="mission">${icon("play")}Start the first mission</button><span class="faint small">Its tasks go on the team's board; the team runs them like any task (Run stage, or autopilot).</span></div></section>`;
    const left = m.deadline - Date.now() / 1000;
    return `<section class="mh-card tpm-card">${head}
      <div class="tpm-mhead"><span class="hq-chip t-${m.status === "done" ? "ok" : m.status === "late" ? "warn" : "info"}">${m.status === "done" ? "Done" : m.status === "late" ? "Past the deadline" : `${mmss(left)} left`}</span>
        <span class="small">${m.done} of ${m.tasks.length} done · started ${when(m.started)} by ${esc(m.by_user || "")}</span>
        <button type="button" class="linkbtn" data-mwsub="tasks">Open the board</button></div>
      ${m.contract ? `<dl class="tpm-dl tpm-contract">${[["Time allocated", `${m.contract.minutes} min`], ["Tasks attempted", `${m.contract.attempted} of ${m.tasks.length}`], ["Completed", String(m.contract.completed)],
          ["Unfinished", String(m.contract.unfinished)], ["Agent runs", String(m.contract.runs)], ["Tokens used", fmtNum(m.contract.tokens, 0)]].map(([k, x]) => `<div><dt>${k}</dt><dd>${x}</dd></div>`).join("")}</dl>
        <p class="faint small">Tests passed and candidate quality come from the Lab's eval of the candidate (Evaluate stage), not from tasks marked done.</p>` : ""}
      ${live ? "" : `<div class="tpm-mhead"><button type="button" class="btn sm" data-tpm="mission">${icon("cycle")}Run it again</button></div>`}
      <ol class="tpm-mt">${m.tasks.map(t => `<li class="st-${t.status}"><span class="hq-chip t-${t.status === "done" ? "ok" : ["working", "checking", "queued"].includes(t.status) ? "info" : ["review", "blocked"].includes(t.status) ? "warn" : "none"}">${TS[t.status] || esc(t.status)}</span>
        <button type="button" class="linkbtn" ${t.status === "deleted" ? "disabled" : `data-mwtask="${t.id}"`}>${esc(t.title)}</button><span class="faint small">${esc(t.agent || "you")}</span></li>`).join("")}</ol></section>`;
  }

  function view(v) {
    need(v);
    if (!d) return failed ? `<p class="mh-err">${icon("alert")}${esc(failed)}</p>` : Loading.line("Opening Top miner…");
    return `<div class="tpm">${roadmap()}<div class="tpm-grid">${scorecard()}${officialCard()}</div>${mission()}${setCard()}${elite()}</div>`;
  }

  // ---------- actions ----------
  async function send(path, body, method = "POST", msg = "") {
    try { d = await api(`${W}${path}`, { method, body }); dAt = Date.now(); if (msg) Auth.toast(msg); MiningWork.rerender(); return true; }
    catch (e) { err(e); return false; }
  }
  function wire(el) {
    if (wired) return; wired = true;
    el.addEventListener("click", e => {
      if (!e.target.closest(".tpm")) return;
      const del = e.target.closest("[data-tpmdel]"); if (del) return send(`/topminer/set/${del.dataset.tpmdel}`, undefined, "DELETE", "Removed from the set");
      const b = e.target.closest("[data-tpm]"); if (!b) return;
      if (b.dataset.tpm === "lab") return send(`/comps/${dWid}/topminer/set/bulk`, { from_lab: true, held_share: 0.2 }, "POST", "Imported from the Lab");
      if (b.dataset.tpm === "mission") return UI.confirm({ title: "Start the first mission?", ok: "Start the mission", icon: "rocket", danger: false,
        body: `${d.mission_plan.length} high-priority tasks for the elite team, due today, with a ${d.mission_minutes}-minute clock. They start when you start them (or autopilot does).`,
        run: async () => { if (await send(`/comps/${dWid}/topminer/mission`, undefined, "POST", "The mission is on the board")) MiningWork.reload(); } }).catch(err);
    });
    el.addEventListener("toggle", e => { if (e.target.classList?.contains("tpm-paste")) setOpen = e.target.open; }, true);
    el.addEventListener("change", e => {
      const s = e.target.closest("[data-tpmset]"); if (s) return send(`/topminer/set/${s.dataset.tpmset}`, { [s.name]: s.value }, "PATCH");
      const m = e.target.closest("[data-tpmmark]"); if (m) return send(`/comps/${dWid}/topminer/milestones/${m.dataset.tpmmark}`, { status: m.value, note: "" }, "PUT", "Saved");
    });
    el.addEventListener("submit", async e => {
      const f = e.target.closest("[data-tpmform]"); if (!f) return;
      e.preventDefault();
      if (f.dataset.tpmform === "one") {
        const body = { name: f.elements.name.value.trim(), category: f.elements.category.value, engine: f.elements.engine.value, split: f.elements.split.value, edges: [] };
        if (await send(`/comps/${dWid}/topminer/set`, body, "POST", "Added")) document.activeElement?.blur();
      } else {
        const names = f.elements.names.value.split(/\n/).map(x => x.trim()).filter(Boolean);
        if (names.length && await send(`/comps/${dWid}/topminer/set/bulk`, { names, held_share: 0.2 }, "POST", `Added ${plural(names.length, "task")}`)) document.activeElement?.blur();
      }
    });
  }
  const fresh = () => { dAt = 0; };
  return { view, wire, holding, fresh };
})();
