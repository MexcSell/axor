/* Competition teams, the Lab (mining_lab.py): the eval score of every checked commit, so a change is judged on what it solves.
   A tab beside Workflow, Files and Loadouts (mining-bench.js draws the frame), with four parts:
   - The top: which eval (a scored check of the folder), Measure the base (the same eval on the branch you merge into), Import
     earlier evals (the folder's eval/results/<label>/runs.jsonl).
   - Tasks solved over time: one dot per experiment, its share of tasks solved; shape says what it measured (a task's branch,
     the base, an imported eval). Hover for the numbers; the table below is the same data.
   - Compare: two experiments task by task on the tasks both ran: solved, gained, lost, runs passed, cost per run.
   - Every experiment: commit, eval, score, what became of the task; pick A/B, note, delete. */
const MiningLab = (() => {
  const L = "/api/mining/lab";
  let d = null, dFid = null, dAt = 0, loading = false, failed = "", sel = null, A = null, Bx = null, cmp = null, cmpKey = "", past = null, pastPath = "eval/results";
  const shown = new Set(), picked = new Set();
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const money = x => x == null ? "–" : x > 0 && x < 0.01 ? "<$0.01" : `$${fmtNum(x, x >= 10 ? 0 : 3)}`;
  const pct = (a, b) => b ? `${fmtNum(100 * a / b, 0)}%` : "–";
  const when = ts => ts ? new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const KIND = { task: ["Task branch", "code"], base: ["Base", "target"], import: ["Earlier eval", "download"], trial: ["Trial", "bulb"] };  // trial: mining_improve.py's
  const DEC = { merged: "ok", "sent back": "warn", dropped: "none", superseded: "none" };
  const done = () => (d?.experiments || []).filter(e => e.status === "done");
  const byId = id => (d?.experiments || []).find(e => e.id === id);
  const name = e => e.kind === "task" ? (e.task || e.label) : e.label;

  // ---------- data ----------
  function need(fid, force = false) {
    if (dFid !== fid) { d = null; dFid = fid; dAt = 0; failed = ""; sel = null; A = Bx = null; cmp = null; cmpKey = ""; past = null; picked.clear(); }
    const live = d?.experiments.some(e => e.status === "running");
    if (loading || (!force && Date.now() - dAt < (live ? 4000 : 20000))) return;
    loading = true;
    api(`${L}/flows/${fid}`).then(x => { if (dFid === fid) { d = x; failed = ""; } }).catch(e => { if (dFid === fid) failed = e.message; })
      .finally(() => { loading = false; dAt = Date.now(); if (dFid === fid) MiningBench.apply(MiningBench.view()); });
  }
  function set(x) { d = x; dAt = Date.now(); MiningBench.apply(MiningBench.view()); }
  const post = (url, body = {}, method = "POST") => api(`${L}${url}`, { method, body });

  // which experiments the chart and the defaults look at: one eval (check id), the imported ones, or all
  function scope() {
    const checks = d.checks || [], ex = done();
    if (sel == null) sel = checks.find(c => ex.some(e => e.check_id === c.id))?.id || (ex.some(e => e.kind === "import") ? "import" : "all");
    return sel === "all" ? ex : sel === "import" ? ex.filter(e => e.kind === "import") : ex.filter(e => e.check_id === sel);
  }
  function defaults(list) {
    if (A && !byId(A)) A = null; if (Bx && !byId(Bx)) Bx = null;
    if (!A) A = (list.find(e => e.kind === "task") || list[0])?.id || null;
    if (!Bx) Bx = (list.find(e => e.kind === "base" && e.id !== A) || list.find(e => e.id !== A))?.id || null;
  }
  function loadCmp() {
    const k = A && Bx && A !== Bx ? `${A}-${Bx}` : "";
    if (k === cmpKey) return; cmpKey = k; cmp = null;
    if (!k) return;
    api(`${L}/compare?a=${A}&b=${Bx}`).then(x => { if (cmpKey === k) { cmp = x; MiningBench.apply(MiningBench.view()); } }).catch(e => { if (cmpKey === k) { cmp = { error: e.message }; MiningBench.apply(MiningBench.view()); } });
  }

  // ---------- the page ----------
  function page(bv) {
    if (!bv?.flow) return "";
    need(bv.flow.id);
    if (failed && !d) return `<div class="mh-card"><p class="mh-err">${icon("alert")}${esc(failed)}</p></div>`;
    if (!d) return Loading.line("Opening the Lab…");
    const list = scope(); defaults(list); loadCmp();
    return `<div class="lab-root">${top()}${shown.has("import") ? importBox() : ""}${chart(list)}${compare()}${table()}</div>`;
  }
  function top() {
    const checks = d.checks || [], running = d.experiments.filter(e => e.status === "running"), n = d.experiments.length;
    const opts = [...checks.map(c => [c.id, c.label]), ["import", "Earlier evals"], ["all", "Everything"]];
    return `<section class="mh-card lab-top"><div class="lab-top-h"><div><h3>${icon("chart")}Lab</h3>
        <p class="faint">Every eval of a commit, scored the way validators count: a task is solved only when all its runs pass. A change wins when it solves more than the base on the same tasks. Nothing here blocks a merge: you decide.</p></div>
        <div class="row lab-acts">${checks.length ? `<label class="in lab-pick"><span>Eval</span><select data-labsel>${opts.map(([k, l]) => `<option value="${esc(k)}" ${k === sel ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
          ${checks.map(c => `<button type="button" class="btn sm" data-labbase="${esc(c.id)}" title="Run “${esc(c.label)}” on ${esc(d.flow.into_branch)} as it is now">${icon("target")}Measure the base${checks.length > 1 ? `: ${esc(c.label)}` : ""}</button>`).join("")}` : ""}
          <button type="button" class="btn sm" data-labimp aria-expanded="${shown.has("import")}">${icon("download")}Import earlier evals</button></div></div>
      ${!d.connected ? `<p class="mh-err small">${icon("alert")}The workbench doesn't answer, so new evals can't run; what's recorded is below.</p>`
        : !checks.length ? `<p class="lab-hint">${icon("info")}The folder has no scored check yet. Add an eval with <code>"results"</code> to its checks in <code>/etc/axor-workbench.json</code> (workbench/README.md, “Scored checks”), then <code>systemctl restart axor-workbench</code>. Imported evals work without one.</p>` : ""}
      ${running.length ? `<ul class="lab-running">${running.map(e => `<li><span class="ci ci-run"></span>${esc(KIND[e.kind][0])}: ${esc(name(e))} · started ${when(e.created)}</li>`).join("")}</ul>` : ""}
      ${!n ? `<p class="faint small">No experiments yet. Run a scored check on a task in Review, measure the base, or import earlier evals.</p>` : ""}</section>`;
  }
  function importBox() {
    const items = past?.items || [];
    return `<section class="mh-card lab-import"><h3>${icon("download")}Import earlier evals</h3>
      <p class="faint small">Reads <code>&lt;folder&gt;/&lt;label&gt;/runs.jsonl</code> in the repo (eval/eval.py's results) and scores each one. Labels named <code>bench-…</code> came from checks here and are already in the Lab.</p>
      <div class="row"><label class="in lab-path"><span>Folder in the repo</span><input data-labpath value="${esc(pastPath)}" data-mbhold></label><button type="button" class="btn sm" data-lablist>${icon("folder")}List</button></div>
      ${past?.error ? `<p class="mh-err small">${icon("alert")}${esc(past.error)}</p>` : ""}
      ${past && !past.error ? items.length ? `<div class="lab-labels">${items.map(i => `<label class="lab-label ${i.imported ? "done" : ""}"><input type="checkbox" data-labck="${esc(i.label)}" ${i.imported ? "disabled checked" : picked.has(i.label) ? "checked" : ""}>
          <span>${esc(i.label)}</span>${i.imported ? `<small>imported</small>` : i.bench ? `<small>from a check</small>` : ""}</label>`).join("")}</div>
        <div class="row"><button type="button" class="linkbtn" data-laball>Select all new</button><button type="button" class="btn sm primary" data-labgo ${picked.size ? "" : "disabled"}>${icon("download")}Import ${picked.size ? plural(picked.size, "eval") : ""}</button></div>`
        : `<p class="faint small">No result folders there.</p>` : ""}</section>`;
  }

  // one dot per experiment: x in time order, y the share of its tasks solved
  function chart(list) {
    const pts = [...list].sort((a, b) => (a.finished || a.created) - (b.finished || b.created));
    if (!pts.length) return "";
    const room = document.querySelector("#teams .mb-root")?.clientWidth || 0;  // drawn at the card's width, so text stays at its real size on a phone
    const W = room ? Math.max(300, Math.min(1100, room - 34)) : 760, H = 210, Lm = 40, R = 14, T = 14, Bm = 26, n = pts.length;
    const X = i => n === 1 ? (Lm + W - R) / 2 : Lm + i * (W - Lm - R) / (n - 1), Y = f => T + (1 - f) * (H - T - Bm);
    const grid = [0, .25, .5, .75, 1].map(f => `<line class="lab-grid" x1="${Lm}" x2="${W - R}" y1="${Y(f)}" y2="${Y(f)}"/><text class="lab-ax" x="${Lm - 6}" y="${Y(f) + 4}" text-anchor="end">${f * 100}%</text>`).join("");
    const mark = (e, i) => {
      const x = X(i), y = Y(e.tasks ? e.solved / e.tasks : 0), on = e.id === A || e.id === Bx;
      const m = e.kind === "base" ? `<circle class="lab-m ring" cx="${x}" cy="${y}" r="5.5"/>` : e.kind === "import" ? `<rect class="lab-m" x="${x - 5}" y="${y - 5}" width="10" height="10" rx="1.5" transform="rotate(45 ${x} ${y})"/>`
        : e.kind === "trial" ? `<path class="lab-m" d="M${x} ${y - 7.5}L${x + 7} ${y + 5}H${x - 7}Z"/>` : `<circle class="lab-m" cx="${x}" cy="${y}" r="5.5"/>`;
      return `<g class="lab-pt ${on ? "on" : ""}">${on ? `<circle class="lab-halo" cx="${x}" cy="${y}" r="10"/>` : ""}${m}<rect class="lab-hit" data-labpt="${i}" x="${x - 14}" y="${T}" width="28" height="${H - T - Bm}"/></g>`;
    };
    const at = i => new Date((pts[i].finished || pts[i].created) * 1000), oneDay = at(0).toDateString() === at(n - 1).toDateString();
    const lab = i => `<text class="lab-ax" x="${X(i)}" y="${H - 8}" text-anchor="${n === 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${oneDay
      ? at(i).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : at(i).toLocaleDateString([], { month: "short", day: "numeric" })}</text>`;
    const xl = n === 1 ? [0] : n === 2 ? [0, 1] : [0, Math.floor((n - 1) / 2), n - 1];
    const kinds = [...new Set(pts.map(e => e.kind))];
    const key = { task: `<svg viewBox="0 0 12 12" aria-hidden="true"><circle class="lab-m" cx="6" cy="6" r="4.5"/></svg>`, base: `<svg viewBox="0 0 12 12" aria-hidden="true"><circle class="lab-m ring" cx="6" cy="6" r="4"/></svg>`,
      import: `<svg viewBox="0 0 12 12" aria-hidden="true"><rect class="lab-m" x="2.5" y="2.5" width="7" height="7" rx="1" transform="rotate(45 6 6)"/></svg>`,
      trial: `<svg viewBox="0 0 12 12" aria-hidden="true"><path class="lab-m" d="M6 .5L11.5 10.5H.5Z"/></svg>` };
    setTimeout(() => hover(pts), 0);
    return `<section class="mh-card lab-chart-card"><h3>${icon("chart")}Tasks solved over time</h3>
      <div class="lab-legend">${kinds.map(k => `<span>${key[k]}${KIND[k][0]}</span>`).join("")}<span class="faint small">· the share of each eval's tasks it solved; A and B are ringed</span></div>
      <div class="lab-chart" data-labchart><svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Share of tasks solved per experiment, oldest first">${grid}${xl.map(lab).join("")}${pts.map(mark).join("")}</svg></div></section>`;
  }
  function hover(pts) {
    const el = document.querySelector("[data-labchart]"); if (!el || el.dataset.wired) return; el.dataset.wired = "1";
    let tp = el.querySelector(".mh-tip"); if (!tp) { tp = document.createElement("div"); tp.className = "mh-tip"; tp.hidden = true; el.append(tp); }
    const svg = el.querySelector("svg");
    svg.addEventListener("pointermove", e => {
      const i = +e.target.dataset?.labpt; if (isNaN(i)) return;
      const p = pts[i], r = svg.getBoundingClientRect(), hit = e.target.getBoundingClientRect();
      tp.innerHTML = `<div><b>${esc(name(p))}</b></div><div>${esc(KIND[p.kind][0])}${p.head ? ` · <code>${esc(p.head.slice(0, 8))}</code>` : ""} · ${when(p.finished || p.created)}</div>
        <div><b>${p.solved}/${p.tasks}</b> solved · ${p.passed}/${p.runs} runs · ${money(p.runs ? p.cost / p.runs : null)} a run</div>${p.decision ? `<div>${esc(p.decision)}</div>` : ""}`;
      tp.style.left = `${hit.left - r.left + hit.width / 2}px`; tp.style.top = `${e.clientY - r.top - 8}px`; tp.hidden = false;
    });
    svg.addEventListener("pointerleave", () => { tp.hidden = true; });
    svg.addEventListener("click", e => { const i = +e.target.dataset?.labpt; if (!isNaN(i)) { A = pts[i].id; MiningBench.apply(MiningBench.view()); } });
  }

  function compare() {
    const ex = done();
    if (ex.length < 2) return "";
    const opt = cur => ex.map(e => `<option value="${e.id}" ${e.id === cur ? "selected" : ""}>${esc(KIND[e.kind][0])}: ${esc(name(e))}${e.head ? ` (${esc(e.head.slice(0, 8))})` : ""} · ${e.solved}/${e.tasks}</option>`).join("");
    let body = "";
    if (A === Bx) body = `<p class="faint small">Pick two different experiments.</p>`;
    else if (!cmp) body = Loading.line("Comparing…");
    else if (cmp.error) body = `<p class="mh-err small">${icon("alert")}${esc(cmp.error)}</p>`;
    else if (!cmp.shared) body = `<p class="faint small">${icon("info")}These two ran no task in common, so there's nothing to compare.</p>`;
    else {
      const ds = cmp.solved_a - cmp.solved_b, tone = ds > 0 ? "up" : ds < 0 ? "down" : "";
      const tile = (l, a, b, c = "") => `<div class="lab-tile"><span>${l}</span><b class="${c}">${a}</b><small>B: ${b}</small></div>`;
      const cell = p => p ? `<span class="lab-runs ${p.passed === p.runs ? "all" : p.passed ? "some" : "none"}">${p.passed}/${p.runs}</span>` : `<span class="faint">–</span>`;
      const CH = { gained: ["ok", "Gained"], lost: ["bad", "Lost"], same: ["none", "Same"] };
      const rows = [...cmp.rows].sort((x, y) => ["lost", "gained", "same", null].indexOf(x.change) - ["lost", "gained", "same", null].indexOf(y.change) || x.task.localeCompare(y.task));
      const suite = cmp.same_suite === false ? `<p class="mh-err small">${icon("alert")}Not the same suite: ${cmp.only_a ? `${plural(cmp.only_a, "task")} only A ran` : ""}${cmp.only_a && cmp.only_b ? ", " : ""}${cmp.only_b ? `${plural(cmp.only_b, "task")} only B ran` : ""}${!cmp.only_a && !cmp.only_b ? "the tasks ran a different number of times" : ""}. Only the ${plural(cmp.shared, "shared task")} below compare; the two experiments' totals don't.</p>` : "";
      body = suite + `<div class="lab-tiles">${tile(`Solved on ${plural(cmp.shared, "shared task")}`, `${cmp.solved_a} <small>(${ds > 0 ? "+" : ds < 0 ? "−" : "±"}${Math.abs(ds)})</small>`, cmp.solved_b, tone)}
          ${tile("Gained / lost", `+${cmp.gained} / −${cmp.lost}`, "tasks A solves that B doesn't, and back", cmp.lost ? "down" : cmp.gained ? "up" : "")}
          ${tile("Runs passed", `${cmp.passed_a}/${cmp.runs_a} <small>${pct(cmp.passed_a, cmp.runs_a)}</small>`, `${cmp.passed_b}/${cmp.runs_b} (${pct(cmp.passed_b, cmp.runs_b)})`)}
          ${tile("Cost a run", money(cmp.cost_a), money(cmp.cost_b))}</div>
        <div class="lab-scroll"><table class="lab-tbl"><thead><tr><th>Task</th><th>A runs passed</th><th>B runs passed</th><th>Solved</th></tr></thead><tbody>
          ${rows.map(r => `<tr><td><code>${esc(r.task)}</code></td><td>${cell(r.a)}</td><td>${cell(r.b)}</td><td>${r.change ? `<span class="hq-chip t-${CH[r.change][0]}">${CH[r.change][1]}</span>` : `<span class="faint small">only in ${r.a ? "A" : "B"}</span>`}</td></tr>`).join("")}</tbody></table></div>`;
    }
    return `<section class="mh-card"><h3>${icon("eye")}Compare</h3>
      <div class="lab-ab"><label class="in"><span>A</span><select data-laba>${opt(A)}</select></label><button type="button" class="btn sm" data-labswap title="Swap A and B" aria-label="Swap A and B">${icon("undo")}</button><label class="in"><span>B</span><select data-labb>${opt(Bx)}</select></label></div>${body}</section>`;
  }

  function table() {
    const ex = d.experiments; if (!ex.length) return "";
    const checks = Object.fromEntries((d.checks || []).map(c => [c.id, c.label]));
    return `<section class="mh-card"><h3>${icon("list")}Every experiment</h3><div class="lab-scroll"><table class="lab-tbl lab-all"><thead><tr><th>When</th><th>What</th><th>Commit</th><th>Eval</th><th>Solved</th><th>Runs passed</th><th>A run</th><th>Then</th><th></th></tr></thead><tbody>
      ${ex.map(e => `<tr class="${e.id === A ? "is-a" : e.id === Bx ? "is-b" : ""}"><td class="nowrap">${when(e.finished || e.created)}</td>
        <td><span class="lab-kind">${icon(KIND[e.kind][1])}${esc(KIND[e.kind][0])}</span> ${esc(name(e))}${e.note ? `<div class="faint small">${esc(e.note)}</div>` : ""}${e.error ? `<div class="${e.status === "done" ? "faint" : "mh-err"} small lab-err" title="${esc(e.error)}">${esc(e.error.replace(/\/[^\s'"]*\/([^/\s'"]+)/g, "…/$1"))}</div>` : ""}</td>
        <td class="nowrap">${e.head ? `<code>${esc(e.head.slice(0, 8))}</code>` : "–"}</td><td class="small">${esc(e.check_id ? checks[e.check_id] || e.check_id : e.kind === "import" ? "imported" : "–")}</td>
        <td>${e.status === "done" ? `<b>${e.solved}/${e.tasks}</b>` : e.status === "running" ? `<span class="hq-chip t-run">Running</span>` : `<span class="hq-chip t-bad">${e.status === "stopped" ? "Stopped" : "No score"}</span>`}</td>
        <td>${e.status === "done" ? `${e.passed}/${e.runs} <span class="faint small">${pct(e.passed, e.runs)}</span>` : ""}</td>
        <td class="nowrap">${e.status === "done" ? `${money(e.runs ? e.cost / e.runs : null)}${e.secs ? ` · ${fmtNum(e.secs, 0)} s` : ""}` : ""}</td>
        <td>${e.decision ? `<span class="hq-chip t-${DEC[e.decision] || "none"}">${esc(e.decision)}</span>` : ""}</td>
        <td class="nowrap">${e.status === "done" ? `<button type="button" class="linkbtn" data-labseta="${e.id}">A</button> <button type="button" class="linkbtn" data-labsetb="${e.id}">B</button> ` : ""}<button type="button" class="linkbtn" data-labnote="${e.id}">Note</button>${e.status !== "running" ? ` <button type="button" class="linkbtn" data-labdel="${e.id}">Delete</button>` : ""}</td></tr>`).join("")}</tbody></table></div></section>`;
  }

  // ---------- events ----------
  let wired = false;
  function wire(el) {
    if (wired) return; wired = true;
    el.addEventListener("change", e => {
      const t = e.target;
      if (t.matches("[data-labsel]")) { sel = t.value; A = Bx = null; t.blur(); return MiningBench.apply(MiningBench.view()); }
      if (t.matches("[data-laba]")) { A = +t.value; t.blur(); return MiningBench.apply(MiningBench.view()); }
      if (t.matches("[data-labb]")) { Bx = +t.value; t.blur(); return MiningBench.apply(MiningBench.view()); }
      if (t.matches("[data-labck]")) { t.checked ? picked.add(t.dataset.labck) : picked.delete(t.dataset.labck); return MiningBench.apply(MiningBench.view()); }
    });
    el.addEventListener("input", e => { if (e.target.matches("[data-labpath]")) pastPath = e.target.value; });
    el.addEventListener("click", async e => {
      const t = e.target, fid = d?.flow.id;
      if (!fid) return;
      const bs = t.closest("[data-labbase]");
      if (bs) { const x = await MiningBench.act(bs, () => post(`/flows/${fid}/baseline`, { check: bs.dataset.labbase })); if (x) { set(x); Auth.toast(`Measuring ${d.flow.into_branch}: it runs on the workbench`); } return; }
      if (t.closest("[data-labimp]")) { shown.has("import") ? shown.delete("import") : shown.add("import"); if (shown.has("import") && !past) list(fid); return MiningBench.apply(MiningBench.view()); }
      const ls = t.closest("[data-lablist]"); if (ls) return list(fid, ls);
      if (t.closest("[data-laball]")) { (past?.items || []).forEach(i => { if (!i.imported && !i.bench) picked.add(i.label); }); return MiningBench.apply(MiningBench.view()); }
      const go = t.closest("[data-labgo]");
      if (go) {
        const x = await MiningBench.act(go, () => post(`/flows/${fid}/import`, { path: pastPath, labels: [...picked] }));
        if (x) { picked.clear(); past = null; shown.delete("import"); sel = "import"; A = Bx = null; set(x); Auth.toast(`Imported ${plural(x.imported, "eval")}${x.skipped.length ? `; skipped ${x.skipped.length}` : ""}`); }
        return;
      }
      if (t.closest("[data-labswap]")) { [A, Bx] = [Bx, A]; return MiningBench.apply(MiningBench.view()); }
      const sa = t.closest("[data-labseta]"); if (sa) { A = +sa.dataset.labseta; return MiningBench.apply(MiningBench.view()); }
      const sb = t.closest("[data-labsetb]"); if (sb) { Bx = +sb.dataset.labsetb; return MiningBench.apply(MiningBench.view()); }
      const nt = t.closest("[data-labnote]");
      if (nt) { const x = byId(+nt.dataset.labnote); const note = prompt("A note on this experiment (what changed, why it matters):", x?.note || ""); if (note == null) return;
        try { set(await post(`/experiments/${x.id}`, { note }, "PATCH")); } catch (er) { err(er); } return; }
      const dl = t.closest("[data-labdel]");
      if (dl) { const x = byId(+dl.dataset.labdel);
        return UI.confirm({ title: `Delete the experiment “${esc(name(x))}”?`, body: "Its score leaves the Lab. The eval's files and the task stay.", ok: "Delete",
          run: async () => { set(await post(`/experiments/${x.id}`, {}, "DELETE")); } }).catch(err); }
    });
  }
  async function list(fid, btn) {
    const x = await MiningBench.act(btn, () => api(`${L}/flows/${fid}/past?path=${encodeURIComponent(pastPath)}`).catch(e => ({ error: e.message })));
    past = x; MiningBench.apply(MiningBench.view());
  }
  return { page, wire };
})();
