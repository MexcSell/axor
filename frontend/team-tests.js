/* Team tests (team_eval.py /api/teameval; a hubs.js page, prefix tt-, styles in team-tests.css): the fixed library of test problems
   the whole agent team is tested on (T01-T10 + your own), runs through Mission Control, and each run's graded results. What the team
   sees (the problem, its criteria) is kept apart from what it never sees (the expected answer, the hidden checks). */
(() => {
  const BASE = "/api/teameval";
  const pick = new Set(), open = new Set();
  let run = null, picked = false;  // the run shown in Results; pick starts as the page's default once the library has loaded
  const money = n => `$${fmtNum(n || 0, 2)}`;
  const mins = s => s == null ? "–" : s < 90 ? `${Math.round(s)} s` : `${fmtNum(s / 60, 0)} min`;
  const ST = { waiting: ["s-off", "Waiting"], running: ["s-info", "Running"], grading: ["s-info", "Grading"], done: ["s-ok", "Graded"],
               failed: ["s-crit", "Failed"], skipped: ["s-off", "Skipped"], stopped: ["s-off", "Stopped"] };
  const RUNST = { running: ["s-info", "Running"], done: ["s-ok", "Finished"], stopped: ["s-off", "Stopped"] };
  const CK = { met: ["s-ok", "Met", "check"], partly: ["s-warn", "Partly", "minus"], not_met: ["s-crit", "Not met", "x"] };
  const tone = sc => sc == null ? "" : sc >= 70 ? "tt-good" : sc >= 50 ? "tt-mid" : "tt-bad";
  const score = sc => sc == null ? `<span class="faint">–</span>` : `<b class="num tt-score ${tone(sc)}">${fmtNum(sc, 0)}</b>`;

  // the sidebar button shows whenever Benchmarks & evaluations does (command.js decides that for the agent hubs)
  const ev = document.getElementById("nav-evaluation");
  const mirror = () => { const b = document.getElementById("nav-teamtests"); if (ev && b && b.hidden !== ev.hidden) b.hidden = ev.hidden; };
  mirror();
  if (ev) new MutationObserver(mirror).observe(ev, { attributes: true, attributeFilter: ["hidden"] });

  function selected(d) { return d.cases.filter(c => pick.has(c.key)); }

  function library(d, h) {
    const last = d.runs.find(r => r.status !== "running" && Object.keys(r.scores || {}).length) || null;
    const sel = selected(d), total = sel.reduce((a, c) => a + c.budget, 0);
    const rows = d.cases.map(c => `<tr>
        <td class="tt-pick"><input type="checkbox" data-tt-pick="${esc(c.key)}" ${pick.has(c.key) ? "checked" : ""} aria-label="Include ${esc(c.code)} in the next run"></td>
        <td><b class="num">${esc(c.code)}</b></td>
        <td><button type="button" class="linkbtn tt-title" data-hub="case" data-key="${esc(c.key)}">${esc(c.title)}</button><small class="faint">${esc(c.area)}</small></td>
        <td>${c.split === "benchmark" ? h.pill("s-info", "Benchmark", "lock") : h.pill("s-off", "Practice", "book")}</td>
        <td class="r num">${money(c.budget)}</td><td class="r num">${c.minutes} min</td>
        <td class="r">${score(last?.scores?.[c.key])}</td></tr>`).join("");
    return `<div class="tt-tools"><p class="faint small">${icon("lock")}Benchmark cases run blind: no lessons, memory or earlier missions, and the team never sees the hidden checks. Practice cases are ordinary missions the team may learn from.</p></div>
      <div class="tablewrap flat"><table class="grid axh-table tt-lib"><thead><tr><th><span class="sr">Pick</span></th><th>Case</th><th>Problem</th><th>Split</th>
        <th class="r">Budget</th><th class="r">Time limit</th><th class="r" title="${last ? esc(`Score in ${last.name}`) : "No finished run yet"}">Last score</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="tt-runbar"><span><b class="num">${sel.length}</b> of ${d.cases.length} cases picked · up to <b class="num">${money(total)}</b> of model spend</span>
        <span class="row"><button type="button" class="btn sm" data-hub="none">Clear</button><button type="button" class="btn sm" data-hub="all">Pick all</button>
        <button type="button" class="btn sm primary" data-hub="run" ${sel.length && d.enabled ? "" : "disabled"}>${icon("play")}Run ${sel.length || ""} test${sel.length === 1 ? "" : "s"}</button></span></div>`;
  }

  function history(d, h) {
    if (!d.runs.length) return h.empty("No test runs yet. Pick cases in the Library and run them.");
    return `<div class="tablewrap flat"><table class="grid axh-table tt-runs"><thead><tr><th>Run</th><th>Started</th><th>Status</th><th class="r">Passed</th>
        <th class="r" title="Mean score of the graded cases">Mean</th><th class="r" title="Mean over benchmark cases only">Benchmark</th><th class="r">Spent</th><th>Library</th></tr></thead><tbody>
      ${d.runs.map(r => { const s = r.summary, st = RUNST[r.status] || ["s-off", r.status]; return `<tr>
        <td><button type="button" class="linkbtn" data-hub="open" data-id="${r.id}">${esc(r.name)}</button>${r.error ? `<small class="tt-err">${esc(r.error)}</small>` : ""}</td>
        <td class="faint">${ago(r.created)}</td><td>${h.pill(st[0], st[1])}</td>
        <td class="r num">${s.passed} / ${s.cases}</td><td class="r">${score(s.mean)}</td><td class="r">${score(s.benchmark_mean)}</td><td class="r num">${money(s.spent)}</td>
        <td class="faint small">${r.dataset_version ? `v${r.dataset_version} · ${esc(String(r.dataset_sha || "").slice(0, 8))}` : "–"}</td></tr>`; }).join("")}</tbody></table></div>
      <p class="faint small">Compare runs on the same library version: a changed case gives the library a new version.</p>`;
  }

  function checks(g) {
    if (!g?.checks?.length) return "";
    return `<ul class="tt-checks">${g.checks.map(c => { const k = CK[c.status] || CK.not_met; return `<li><span class="occ-pill ${k[0]}">${icon(k[2])}${k[1]}</span>
        <span><b>${esc(c.check)}</b><small class="faint">${esc(c.evidence || "")}</small></span></li>`; }).join("")}</ul>
      ${g.wrong?.length ? `<p class="tt-sub">${icon("alert")}Wrong or invented in the deliverable</p><ul class="tt-wrong">${g.wrong.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      ${g.summary ? `<p class="faint small">${esc(g.summary)}${g.independent === false ? " · graded on the same model that did the work (only one model in the pool)" : ""}</p>` : ""}`;
  }

  function results(d, h) {
    const R = d.detail;
    if (!R) return h.empty(d.runs.length ? "Open a run from History to see its results." : "No test runs yet.");
    const r = R.run, s = r.summary, st = RUNST[r.status] || ["s-off", r.status];
    const kp = `<div class="stats occ-kpis tt-kpis">
        ${h.kpi("trophy", "Passed", `${s.passed} / ${s.cases}`, `score ${d.pass}+ on a delivered mission`, s.finished && s.passed === s.finished ? "ok" : "")}
        ${h.kpi("target", "Mean score", s.mean == null ? "–" : fmtNum(s.mean, 0), s.benchmark_mean == null ? "hidden checks met" : `benchmark cases ${fmtNum(s.benchmark_mean, 0)}`)}
        ${h.kpi("coins", "Spent", money(s.spent), `cap ${money(r.cap)} · ${h.tok(s.tokens)} tokens`)}
        ${h.kpi("help", "Questions asked", s.questions, s.waits ? `${s.waits} waited for a person` : "answered with “state your assumptions”")}
        ${h.kpi("alert", "Reviewer too lenient", s.lenient, "verified work the hidden checks failed", s.lenient ? "warn" : "")}</div>`;
    const rows = R.results.map(x => {
      const t = ST[x.status] || ["s-off", x.status], isOpen = open.has(x.id);
      const crit = x.criteria_total ? `${fmtNum(x.criteria_met, 1).replace(/\.0$/, "")} / ${x.criteria_total}` : "–";
      return `<tr class="${isOpen ? "tt-open" : ""}"><td><b class="num">${esc(x.code)}</b></td>
          <td><button type="button" class="linkbtn tt-title" data-hub="row" data-id="${x.id}" aria-expanded="${isOpen}">${icon(isOpen ? "down" : "right")}${esc(x.title)}</button>
            ${x.note ? `<small class="faint">${esc(x.note)}</small>` : ""}</td>
          <td>${h.pill(t[0], t[1])}${x.lenient ? ` ${h.pill("s-warn", "Lenient review", "alert")}` : ""}</td>
          <td class="r">${score(x.score)}</td><td class="r num" title="Acceptance criteria Mission Control's own reviewer found met">${crit}</td>
          <td class="r num">${x.questions.length || "–"}</td><td class="r num">${x.spent || x.grade_usd ? money((x.spent || 0) + (x.grade_usd || 0)) : "–"}</td><td class="r num">${mins(x.seconds)}</td>
          <td>${x.mission_id ? `<button type="button" class="linkbtn" ${h.go({ view: "mos", id: x.mission_id })}>#${x.mission_id}</button>` : "–"}</td></tr>
        ${isOpen ? `<tr class="tt-detail"><td></td><td colspan="8">
          ${x.questions.length ? `<p class="tt-sub">${icon("help")}Questions the team asked</p><ul class="tt-wrong">${x.questions.map(q => `<li>${esc(q)}</li>`).join("")}</ul>` : ""}
          ${checks(x.grade) || `<p class="faint small">${x.status === "done" ? "No hidden checks graded." : "Not graded yet."}</p>`}
          <p class="faint small">${[x.engine && `engine ${x.engine}`, x.attempts && `${x.attempts} attempt${x.attempts === 1 ? "" : "s"}`, x.reviewer_model && `reviewer ${x.reviewer_model}`, x.grader_model && `grader ${x.grader_model}`, x.tokens && `${h.tok(x.tokens)} tokens`].filter(Boolean).map(esc).join(" · ")}</p></td></tr>` : ""}`;
    }).join("");
    return `<div class="tt-head"><div><h3>${esc(r.name)}</h3><p class="faint small">${h.pill(st[0], st[1])} started ${ago(r.created)} by ${esc(r.by_user || "?")}
        · library v${r.dataset_version ?? "?"} · autonomy ${esc(r.config?.autonomy || "L2")}${r.config?.pool?.length ? ` · pool ${esc(r.config.pool.join(", "))}` : ""}</p></div>
        <span class="row">${r.status === "running" ? `<button type="button" class="btn sm danger" data-hub="stop" data-id="${r.id}">${icon("stop")}Stop</button>`
          : `<button type="button" class="btn sm" data-hub="del" data-id="${r.id}">${icon("trash")}Delete</button>`}</span></div>
      ${kp}${r.error ? `<p class="tt-err">${icon("alert")}${esc(r.error)}</p>` : ""}
      <div class="tablewrap flat"><table class="grid axh-table tt-res" data-plt-skip><thead><tr><th>Case</th><th>Problem</th><th>Status</th><th class="r">Score</th>
        <th class="r">Criteria</th><th class="r">Questions</th><th class="r">Spent</th><th class="r">Time</th><th>Mission</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  // ---------- the case dialog: read a case (built-in), or add and edit your own ----------
  function dialog() {
    let d = document.getElementById("tt-dialog");
    if (!d) { d = document.createElement("dialog"); d.id = "tt-dialog"; d.className = "modal tt-dialog"; document.body.append(d); }
    return d;
  }
  function showCase(c) {
    const d = dialog(), mine = !c || !c.builtin, v = c || { title: "", area: "Custom", split: "practice", goal: "", criteria: [], expected: "", checks: [], budget: 3, minutes: 40 };
    const ro = mine ? "" : "readonly";
    d.innerHTML = `<form method="dialog" novalidate>
      <div class="tt-dh"><h3>${c ? `${esc(c.code)} · ${esc(c.title)}` : "New test case"}</h3>${c?.builtin ? `<p class="faint small">${icon("lock")}Built-in cases can't be changed, so every run measures the same thing. Copy one to make your own variant.</p>` : ""}</div>
      <div class="tt-grid">
        <label class="in"><span>Title</span><input name="title" maxlength="120" value="${esc(v.title)}" ${ro} required></label>
        <label class="in"><span>Area</span><input name="area" maxlength="40" value="${esc(v.area)}" ${ro}></label>
        <label class="in"><span>Split</span><select name="split" ${mine ? "" : "disabled"}><option value="practice" ${v.split === "practice" ? "selected" : ""}>Practice: the team may learn from it</option><option value="benchmark" ${v.split === "benchmark" ? "selected" : ""}>Benchmark: runs blind</option></select></label>
        <label class="in"><span>Budget ($)</span><input name="budget" type="number" min="0.05" max="50" step="0.05" value="${v.budget}" ${ro}></label>
        <label class="in"><span>Time limit (minutes)</span><input name="minutes" type="number" min="5" max="240" step="5" value="${v.minutes}" ${ro}></label>
      </div>
      <p class="tt-sub">${icon("eye")}What the team sees</p>
      <label class="in"><span>Problem</span><textarea name="goal" rows="${mine ? 6 : 10}" maxlength="4000" ${ro}>${esc(v.goal)}</textarea></label>
      <label class="in"><span>Acceptance criteria, one per line (up to 6)</span><textarea name="criteria" rows="3" ${ro}>${esc((v.criteria || []).join("\n"))}</textarea></label>
      <p class="tt-sub">${icon("lock")}What the team never sees</p>
      <label class="in"><span>Expected answer</span><textarea name="expected" rows="3" maxlength="3000" ${ro}>${esc(v.expected || "")}</textarea></label>
      <label class="in"><span>Hidden checks, one per line (up to 10)</span><textarea name="checks" rows="6" ${ro}>${esc((v.checks || []).join("\n"))}</textarea></label>
      ${c?.within_budget ? `<p class="faint small">${icon("coins")}AXoR also checks the case finished within its budget.</p>` : ""}
      <p class="err" role="alert"></p>
      <div class="row end">
        ${c && !c.builtin ? `<button type="button" class="btn danger" data-tt="delete">${icon("trash")}Delete</button>` : ""}
        ${c ? `<button type="button" class="btn" data-tt="copy">${icon("copy")}Copy as new</button>` : ""}
        <button type="button" class="btn" data-tt="close">Close</button>
        ${mine ? `<button type="submit" class="btn primary">${c ? "Save" : "Add case"}</button>` : ""}
      </div></form>`;
    const f = d.querySelector("form"), err = f.querySelector(".err"), F = n => f.elements[n];  // f.title would be the form's own title
    const lines = s => s.split("\n").map(x => x.trim()).filter(Boolean);
    const body = () => ({ title: F("title").value.trim(), area: F("area").value.trim(), split: F("split").value, goal: F("goal").value.trim(), criteria: lines(F("criteria").value),
                          expected: F("expected").value.trim(), checks: lines(F("checks").value), budget: +F("budget").value || 3, minutes: +F("minutes").value || 40 });
    const done = () => { d.close(); Hubs.reload(true); };
    f.onclick = async e => {
      const b = e.target.closest("[data-tt]"); if (!b) return;
      if (b.dataset.tt === "close") return d.close();
      if (b.dataset.tt === "copy") { const v = body(); showCase(null); return prefill(v, c); }
      if (b.dataset.tt === "delete") {
        try { await api(`${BASE}/cases/${c.id}`, { method: "DELETE" }); pick.delete(c.key); toast("Case deleted."); done(); } catch (x) { err.textContent = x.message; }
      }
    };
    f.onsubmit = async e => {
      e.preventDefault(); err.textContent = "";
      const go = f.querySelector("[type=submit]"); go.disabled = true;
      try {
        await api(c ? `${BASE}/cases/${c.id}` : `${BASE}/cases`, { method: c ? "PUT" : "POST", body: body() });
        toast(c ? "Case saved." : "Case added to the library."); done();
      } catch (x) { err.textContent = x.message; } finally { go.disabled = false; }
    };
    if (!d.open) d.showModal();
  }
  function prefill(v, from) {
    const F = n => dialog().querySelector("form").elements[n];
    for (const k of ["area", "goal", "expected", "budget", "minutes"]) F(k).value = v[k];
    F("title").value = `${v.title} (copy)`; F("criteria").value = v.criteria.join("\n"); F("checks").value = v.checks.join("\n");
    F("split").value = from?.split === "benchmark" ? "benchmark" : "practice";
  }

  Hubs.register("teamtests", {
    title: "Team tests", kicker: "Evaluation", icon: "trophy", every: 10000,
    lead: "A fixed library of problems the whole agent team is tested on. Each case runs as a real Mission Control mission and is graded against hidden checks the team never sees.",
    async load(fresh, get) {
      const d = await get(BASE, fresh);
      if (!picked) { (d.default || []).forEach(k => pick.add(k)); picked = true; }
      const live = d.runs.find(r => r.status === "running");
      if (run == null && d.runs.length) run = (live || d.runs[0]).id;
      if (run != null && !d.runs.some(r => r.id === run)) run = d.runs[0]?.id ?? null;
      return { ...d, detail: run != null ? await get(`${BASE}/runs/${run}`, true).catch(() => null) : null };
    },
    actions: () => `<button type="button" class="btn sm" data-hub="new">${icon("plus")}New case</button>`,
    act(a, el, s) {
      const d = s.d;
      if (a === "new") return showCase(null);
      if (a === "case") return showCase(d.cases.find(c => c.key === el.dataset.key));
      if (a === "none") { pick.clear(); return Hubs.reload(); }
      if (a === "all") { d.cases.forEach(c => pick.add(c.key)); return Hubs.reload(); }
      if (a === "open") { run = +el.dataset.id; s.tab = "results"; return Hubs.reload(true); }
      if (a === "row") { const id = +el.dataset.id; open.has(id) ? open.delete(id) : open.add(id); return Hubs.reload(); }
      if (a === "run") {
        const sel = selected(d), total = sel.reduce((x, c) => x + c.budget, 0);
        return UI.confirm({ title: `Run ${sel.length} test${sel.length === 1 ? "" : "s"}?`, icon: "play", danger: false, ok: "Start run",
          body: `Each case is a real Mission Control mission at autonomy L2, one after another, using up to <b>${money(total)}</b> of model spend in all, plus a grading call per case. You can stop the run at any time.`,
          items: sel.map(c => `<b>${esc(c.code)}</b> ${esc(c.title)} · ${money(c.budget)} · ${c.minutes} min${c.split === "benchmark" ? " · blind" : ""}`),
          run: async () => { const r = await api(`${BASE}/runs`, { method: "POST", body: { cases: sel.map(c => c.key) } }); run = r.run.id; s.tab = "results"; toast("Test run started."); Hubs.reload(true); } });
      }
      if (a === "stop") return UI.confirm({ title: "Stop this run?", body: "The running mission is cancelled and the cases not yet started are skipped. Graded results stay.", ok: "Stop run", icon: "stop",
        run: async () => { await api(`${BASE}/runs/${el.dataset.id}/stop`, { method: "POST" }); Hubs.reload(true); } });
      if (a === "del") return UI.confirm({ title: "Delete this run?", body: "Its results are removed from the history. The missions stay in Mission Control.", ok: "Delete",
        run: async () => { await api(`${BASE}/runs/${el.dataset.id}`, { method: "DELETE" }); run = null; Hubs.reload(true); } });
    },
    body(d, h) {
      if (!d.enabled) return h.empty("Mission Control is turned off on this server, and team tests run through it.");
      const live = d.runs.filter(r => r.status === "running").length;
      return `${h.tabs("teamtests", [["library", "list", "Library", d.cases.length], ["results", "trophy", "Results", live ? "live" : ""], ["history", "clock", "History", d.runs.length]])}
        <div class="tt-body">${{ library, results, history }[h.st("teamtests").tab](d, h)}</div>`;
    },
  });

  // picking a case changes no data, so the page doesn't redraw by itself: count and button follow here
  document.addEventListener("change", e => {
    const c = e.target.closest?.("[data-tt-pick]"); if (!c) return;
    c.checked ? pick.add(c.dataset.ttPick) : pick.delete(c.dataset.ttPick);
    Hubs.reload();
  });
})();
