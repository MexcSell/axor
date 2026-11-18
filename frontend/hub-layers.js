/* Intelligence layers (Control Hub → Intelligence layers; hubs.js page "layers", intel_layers.py /api/layers + /api/layers/trace,
   orchestrator.py /api/g5): AXoR's intelligence loop, in four sections.
   - Overview: the loop (Mission → Workforce → Execution → Evaluation → Adaptive → back to Mission) with Knowledge and Governance
     & Control as cross-layer bands; the handoffs from the one event ledger (the same rows and window the orchestrator counts);
     what to fix first; the mission lifecycle acceptance test (the review's eight steps, each with the records that show it), the
     controlled mission and its follow-up written into Mission Control for you to start, and the mission trace.
   - Layer inspection: one layer's parts, checks, dependencies, handoffs in and out, and its recent handoff events.
   - Performance: success and quality against the week before, evaluation coverage against its 95% target, dollars per validated
     deliverable and budgets (with suggested limits), retrieval quality, failures and their diagnosis, cost and quality by model.
   - Adaptive evolution: the nine-stage engine (observe … approve, promote, monitor, roll back), the proposals waiting for an experiment (approve runs it where its target can be
     measured; promotion stays a separate decision), the promotion monitor and the rollback history.
   The page acts only on a click: retry a dead letter, recover a failed run or a sandbox run, run the retrieval benchmark,
   approve an experiment, set a suggested limit. The eight-domain System architecture (Agents → Ecosystem) maps onto it. */
(() => {
  const ST = { operational: ["s-ok", "Operational", "check"], partial: ["s-info", "Partly working", "zap"], degraded: ["s-crit", "Degraded", "alert"], idle: ["s-off", "Idle", "clock"],
               incomplete: ["s-warn", "Incomplete", "alert"] };
  const PST = { ok: ["s-ok", "This week", "check"], degraded: ["s-crit", "Degraded", "alert"], idle: ["s-off", "Quiet", ""], missing: ["s-off", "Not set up", "alert"] };
  const TST = { done: ["s-ok", "Recorded", "check"], empty: ["s-off", "Nothing recorded", ""], broken: ["s-crit", "Broke here", "alert"] };
  const EST = { flowing: ["s-ok", "Flowing", "check"], partial: ["s-warn", "Partial", "alert"], retrying: ["s-warn", "Retrying", "clock"],
                broken: ["s-crit", "Broken", "alert"], quiet: ["s-off", "Quiet", ""] };
  const AST = { pass: ["s-ok", "Pass", "check"], fail: ["s-crit", "Fail", "alert"], pending: ["s-warn", "Pending", "clock"], na: ["s-off", "Not exercised", ""] };
  const val = v => v == null ? "–" : typeof v === "number" ? fmtNum(v, Number.isInteger(v) ? 0 : 1) : String(v);
  const secs = s => s == null ? "–" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${fmtNum(s / 3600, 1)} h`;
  const usd = v => v == null ? "–" : `$${fmtNum(v, v < 1 ? 4 : 2)}`;
  // the operational loop, in order, and what each layer does (the review's architecture); Knowledge runs across all of it
  const LOOP = ["mission", "workforce", "execution", "evaluation", "adaptive"];
  const DOES = { mission: "Understand · Research · Plan · Prioritize", workforce: "Discover · Select · Build teams · Coordinate swarms",
                 execution: "Models · Tools · Sandboxes · Runtime · Orchestration", evaluation: "Verify · Benchmark · Score · Compare",
                 adaptive: "Diagnose · Learn · Improve · Experiment · Evolve", knowledge: "Shared memory · RAG · Research · Experience · Organizational knowledge" };
  // System architecture (Agents → Ecosystem, ecosystem.py): its eight domains against these layers
  const DOMAINS = [["Mission interface", "mission"], ["Mission intelligence", "mission"], ["Agent workforce", "workforce"], ["Model intelligence", "execution"],
                   ["Execution system", "execution"], ["Knowledge system", "knowledge"], ["Verification and evolution", "evaluation", "adaptive"], ["Governance and control", "governance"]];
  let sel = null, lay = null;  // the mission being traced; the layer being inspected

  // the sidebar entry shows whenever the Control Hub's does (as the Unified control panel's does). Plain DOM calls: app.js,
  // which defines $, loads after this file.
  const hub = document.getElementById("nav-command");
  const mirror = () => { const b = document.getElementById("nav-layers"); if (hub && b && b.hidden !== hub.hidden) b.hidden = hub.hidden; };
  mirror();
  if (hub) new MutationObserver(mirror).observe(hub, { attributes: true, attributeFilter: ["hidden"] });
  document.addEventListener("change", e => {
    if (!e.target.matches?.(".ilr-pick")) return;
    sel = +e.target.value || null; Hubs.reload?.();
  });

  // Tools & MCP is a page inside Agents: everything else is a view of its own
  const to = (view, label, cls = "linkbtn") => view === "tools" ? `<button type="button" class="${cls}" data-hub="tools" title="Agents → Tools & MCP">${label}</button>`
    : `<button type="button" class="${cls}" data-axh-to="${esc(view)}" title="Open the page that owns it">${label}</button>`;
  const T = (d, k) => k === "*" ? "every layer" : k === "governance" ? "Governance & control" : d.layers.find(l => l.key === k)?.title || k;
  const edgeName = (d, x) => `${esc(T(d, x.from))} → ${esc(T(d, x.to))}`;

  // ---------- Overview ----------
  function architecture(d, h) {
    const L = Object.fromEntries(d.layers.map(l => [l.key, l]));
    const E = Object.fromEntries((d.links || []).map(x => [x.key, x]));
    const node = (k, i) => {
      const l = L[k]; if (!l) return "";
      const out = (d.links || []).find(x => x.from === k && x.to !== "*" && LOOP.includes(x.to));
      return `<li class="ilr-node ilr-s-${l.status}"><button type="button" data-hub="inspect" data-id="${k}" title="Inspect ${esc(l.title)}">
          <span class="ilr-st"><span class="ilr-n">${i + 1}</span>${icon(l.icon)}<b>${esc(l.title)}</b></span>${h.pill(...ST[l.status])}
          <small class="faint">${esc(DOES[k])}</small><small>${l.working} of ${h.plural(l.required, "required part")} working</small></button>
        ${out ? `<span class="ilr-arrow ilr-e-${out.state}" title="${esc(out.label)}: ${out.done} this week (${EST[out.state][1].toLowerCase()})">${icon(out.feedback ? "cycle" : "arrow")}<b class="num">${fmtNum(out.done, 0)}</b></span>` : ""}</li>`;
    };
    const K = L.knowledge, kn = E["knowledge>*"], g = d.g5;
    const lims = g?.limits?.length || 0, blocked = g?.blocked_7d || 0;
    const gov = lims ? h.pill("s-ok", `${h.plural(lims, "hard limit")}`, "check") : h.pill("s-warn", "No hard limit", "alert");
    return h.card("axh-span12 ilr-arch", "cycle", "The intelligence loop", `<span class="faint small">click a layer to inspect it</span>`,
      `<ol class="ilr-ring" aria-label="The operational loop, in order">${LOOP.map(node).join("")}</ol>
       <p class="ilr-back small ${E["adaptive>mission"]?.state === "broken" ? "ilr-warnline" : "faint"}">${icon("cycle")}<span>Adaptive intelligence feeds back into Mission intelligence:
         ${E["adaptive>mission"] ? `${fmtNum(E["adaptive>mission"].done, 0)} this week, ${EST[E["adaptive>mission"].state][1].toLowerCase()}` : "not recorded"}.
         ${E["adaptive>mission"]?.why ? `${esc(E["adaptive>mission"].why)}.` : "Every mission should leave AXoR better at the next one."}</span></p>
       <div class="ilr-bands">
         ${K ? `<button type="button" class="ilr-band ilr-s-${K.status}" data-hub="inspect" data-id="knowledge"><span>${icon("book")}<b>Knowledge intelligence</b> <small class="faint">across every layer</small></span>
           <small class="faint">${esc(DOES.knowledge)}</small><span>${h.pill(...ST[K.status])} <small>${kn ? `${fmtNum(kn.done, 0)} searches and recalls this week` : ""}</small></span></button>` : ""}
         <div class="ilr-band ilr-gov"><span>${icon("shield")}<b>Governance &amp; control</b> <small class="faint">across every layer</small></span>
           <small class="faint">Budgets · Permissions · Human approvals · Audit · Rollback</small>
           <span>${gov} ${h.pill(g?.policy?.mode === "recommend" ? "s-info" : "s-ok", `Evolution: ${g?.policy?.label || "–"}`, "flag")} <small>${h.plural(blocked, "call")} refused at a limit this week</small></span></div>
       </div>`);
  }

  function handoffs(d, h) {
    const g = d.g5, E = d.links || [];
    if (!E.length) return h.card("axh-span12 ilr-g5", "route", "Handoffs", "", h.empty("The orchestrator isn't running, so no handoff is recorded."));
    const sub = (x, k) => `<small class="faint ilr-sub">${x.kinds.map(k => `${esc(k.kind)} ${fmtNum(k.done, 0)}${k.dead ? ` · ${k.dead} dead` : ""}`).join(" · ")}</small>`;
    const rows = E.map(x => `<tr><th scope="row">${x.shared ? `${esc(T(d, x.from))} → every layer` : edgeName(d, x)}<small class="ilr-sub">${esc(x.label)}</small>${sub(x)}</th>
        <td class="r num">${fmtNum(x.done, 0)}</td><td class="r num">${fmtNum(x.pending + x.retrying, 0)}</td><td class="r num">${fmtNum(x.dead, 0)}</td>
        <td class="r num">${esc(secs(x.lag_s))}</td><td>${h.pill(...EST[x.state])}</td></tr>`).join("");
    const steps = (g?.steps || []).filter(k => k.done || k.dead || k.pending).map(k => `<li><b>${esc(T(d, k.from))}: ${esc(k.step)}</b> <small class="faint">${fmtNum(k.done, 0)} done${k.dead ? `, ${k.dead} dead` : ""}</small></li>`).join("");
    const dead = g?.dead?.length ? `<h4 class="occ-h4">Dead letters</h4><ul class="ilr-dl">${g.dead.map(e => `<li><span><b>${esc(e.event_type)}</b> <small class="faint">${esc(e.correlation_id || "")} · ${h.plural(e.retry_count, "attempt")} · ${ago(e.created_at)}</small>
          <small class="ilr-err">${esc(e.error || "")}</small></span><button type="button" class="btn sm" data-hub="g5retry" data-id="${e.event_id}">${icon("cycle")}Retry</button></li>`).join("")}</ul>` : "";
    const broken = E.filter(x => x.state === "broken").length;
    return h.card("axh-span12 ilr-g5", "route", "Handoffs this week",
      `<span class="faint small">${broken ? `${h.plural(broken, "handoff")} broken · ` : ""}${g?.tick ? `orchestrator round ${ago(g.tick)}, every ${g.tick_every} s` : "orchestrator not run yet"}${g?.error ? ` · last error: ${esc(g.error)}` : ""}</span>`,
      `<div class="tablewrap flat"><table class="grid axh-table ilr-ho"><thead><tr><th scope="col">Handoff</th><th scope="col" class="r">Done</th><th scope="col" class="r">Waiting</th>
        <th scope="col" class="r">Dead</th><th scope="col" class="r">Max lag</th><th scope="col">State</th></tr></thead><tbody>${rows}</tbody></table></div>
       ${steps ? `<ul class="ilr-steps small">${steps}</ul>` : ""}${dead}
       <p class="faint small">One ledger: every handoff is an event with a correlation id and an idempotency key, recorded when it happens or read from the record it left, at that record's time. This table, the loop above and the orchestrator count the same rows. Broken: nothing crossed though work reached the layer it leaves, or a dead letter. Partial: the step that completes it didn't happen.</p>`);
  }

  function fix(d, h) {
    const lv = { fail: ["s-crit", "Failing", "alert"], warn: ["s-warn", "Check", "info"], idle: ["s-off", "Quiet", ""] };
    return h.card("ilr-fix", "flag", "Fix first", `<span class="faint small">evaluation, adaptive and mission first</span>`,
      d.fix.length ? `<ol class="ilr-fixl">${d.fix.map(x => `<li><span class="ilr-pr">${esc(x.priority)}</span><span class="ilr-fx"><b>${esc(x.text)}</b>
          <small class="faint">${esc(x.layer_title)} · ${to(x.view, esc(x.part))}</small></span>${h.pill(...lv[x.level])}</li>`).join("")}</ol>`
        : h.empty("Nothing to fix: every required part worked this week and no check failed."));
  }

  // the review's controlled mission: real, cheap, and checkable against dated sources; written into Mission Control, never started from here
  const CONTROLLED = "Write a one-page brief on the three most important changes to Bittensor (subnets, emissions or validator rules) in the last 30 days, "
    + "each with a dated source link, and say what each one means for my competition teams.";
  // the review's SN62 acceptance run: research, plan, the team's agents, sandbox execution against the baseline, independent check
  const SN62 = "Acceptance run for my SN62 Competition team: research the current Ridges competition rules and what the top miners do (dated sources), "
    + "plan one concrete improvement to our miner agent with acceptance criteria, have the team implement it, run it and the current baseline on the "
    + "practice tasks in the sandbox (python .axor/ridges_run.py), keeping progress in $AXOR_STATE, and report both scores with the sandbox run numbers. "
    + "Don't upload, register or submit anything.";
  function acceptance(d, h) {
    const A = d.acceptance;
    if (!A) return "";
    const row = (r, what) => r ? `<li><span><b>#${r.id} ${esc(r.title || "Mission")}</b><small class="faint">${what}${r.engine === "mining" ? (r.sandbox ? " · with sandbox runs" : " · no sandbox run") : ""} · ${r.finished ? ago(r.finished) : "still running"}</small></span>
        <button type="button" class="btn sm" data-hub="trace" data-id="${r.id}">${icon("route")}Trace</button></li>` : "";
    const fu = A.follow_up;
    const life = A.lifecycle && ![A.loop?.id, fu?.id].includes(A.lifecycle.id) ? A.lifecycle : null;
    const note = A.loop ? "" : fu ? `Step 8 is next: start a follow-up mission on #${fu.id}'s goal. Its plan should take #${fu.id}'s lessons, and the trace then shows which.`
      : A.lifecycle ? "A mission passed steps 1–6, and no later mission has taken its lessons yet."
      : `No mission has passed steps 1–6 yet (understand, plan, assemble, execute, independent evaluation, learn).${A.open ? ` ${h.plural(A.open, "mission")} running now.` : " Run the controlled mission below."}`;
    return h.card("ilr-acc", "check", "Mission lifecycle acceptance test", `<span class="faint small">of your last ${A.checked} missions</span>`,
      `<ul class="ilr-why ilr-accl">${row(A.loop, "went through all eight steps")}${row(fu, "passed steps 1–6 · waiting for step 8")}${row(life, "passed steps 1–6")}</ul>
       ${note ? `<p class="small ilr-warnline">${icon("alert")}<span>${esc(note)}</span></p>` : ""}
       <div class="ilr-accb">${fu ? `<button type="button" class="btn sm primary" data-hub="mxfollow" data-id="${fu.id}" data-goal="${esc(fu.goal || "")}" title="Opens Mission Control with the follow-up written in: you check it and press Start">${icon("play")}Write the follow-up mission</button>` : ""}
         <button type="button" class="btn sm${fu ? "" : " primary"}" data-hub="mxdraft" title="Opens Mission Control with the controlled mission written in: you check it and press Start">${icon("play")}Write the controlled mission</button>
         <button type="button" class="btn sm" data-hub="mxsn62" title="Opens Mission Control with the SN62 run written in, on your SN62 Competition team: you check it and press Start">${icon("play")}Write the SN62 acceptance run</button></div>
       <p class="faint small">Eight steps, each read from the records it leaves: understand (research), plan (deliverables, budget, deadline, criteria), assemble, execute, evaluate (an independent check against the criteria frozen before the work), learn, evolve (only the work's own weak points; promotion waits for you) and improve the next mission. The controlled mission gets a $1 hard budget, the SN62 run $5 (research, the team's agents and sandbox runs on the practice tasks); both are written into Mission Control and nothing runs until you press Start there.</p>`);
  }

  function trace(d, h) {
    const Tr = d.trace || {}, list = Tr.missions || [], t = Tr.trace;
    if (!list.length) return h.card("axh-span12 ilr-trace", "route", "Mission trace", "", h.empty("No Mission Control mission yet: start one to see how the layers carry it."));
    if (sel && !list.some(m => m.id === sel) && !t) sel = null;
    const opt = list.map(m => `<option value="${m.id}"${m.id === sel ? " selected" : ""}>#${m.id} ${esc(m.title || "Mission")} · ${esc(m.outcome || m.status || "")}</option>`).join("");
    const acc = t?.acceptance?.length ? `<h4 class="occ-h4">Acceptance test</h4><ol class="ilr-acc10">${t.acceptance.map(x => `<li class="ilr-a-${x.state}"><span class="ilr-n">${x.n}</span>
        <span><b>${esc(x.label)}</b><small class="faint">${esc(x.detail)}</small>${x.evidence?.length ? `<small class="ilr-ev">${icon("link")}${x.evidence.map(esc).join(" · ")}</small>` : ""}</span>${h.pill(...AST[x.state])}</li>`).join("")}</ol>` : "";
    return h.card("axh-span12 ilr-trace", "route", "Mission trace", `<label class="ilr-pickl"><span class="sr">Mission to trace</span><select class="ilr-pick"><option value="">Pick a mission…</option>${opt}</select></label>`,
      t ? `<p class="faint small ilr-tg">${esc(t.goal || "")} ${t.created ? `· started ${ago(t.created)}` : ""} <button type="button" class="linkbtn" data-hub="mission" data-id="${t.id}">Open the mission</button></p>
          ${acc}<h4 class="occ-h4">Through the layers</h4>
          <ol class="ilr-tl">${t.layers.map((x, i) => `<li class="ilr-t-${x.state}"><span class="ilr-n">${i + 1}</span><div><div class="ilr-ph"><b>${esc(x.title)}</b>${h.pill(...TST[x.state])}</div>
            <ul>${x.lines.map(s => `<li>${esc(s)}</li>`).join("")}</ul></div></li>`).join("")}</ol>${g5trace(t, h)}`
        : h.empty("Pick a mission to see its acceptance test and what each layer contributed, from the records each one left."));
  }

  function g5trace(t, h) {
    const g = t?.g5;
    if (!g || g.error) return "";
    const by = {};
    for (const r of g.runs) { const k = r.ref?.split(":")[0] || "?"; by[k] = by[k] || { n: 0, tok: 0, scored: 0, failed: 0 }; by[k].n++; by[k].tok += r.tokens || 0; by[k].scored += r.score != null; by[k].failed += ["failed", "error", "lost"].includes(r.status); }
    return `<div class="ilr-tg5"><h4 class="occ-h4">Correlated as ${esc(g.corr)}</h4>
      <p class="small">${g.runs.length ? Object.entries(by).map(([k, v]) => `<b>${esc(k)}:</b> ${h.plural(v.n, "run")}, ${h.tok(v.tok)} tokens, ${v.scored} scored${v.failed ? `, ${v.failed} failed` : ""}`).join(" · ") : "No run carries this correlation id yet (missions before G5 don't)."}
      ${g.children.length ? `<br><span class="faint">Child work: ${esc(g.children.join(", "))}</span>` : ""}</p>
      ${g.events.length ? `<ol class="ilr-hist">${g.events.map(e => `<li><span class="faint">${ago(e.created_at)}</span><span><b>${esc(e.event_type)}</b> <small class="faint">${esc(e.source_layer || "")} → ${esc(e.target_layer || "")}</small> ${h.pill(...(e.status === "done" ? ["s-ok", "Done", "check"] : e.status === "dead" ? ["s-crit", "Dead letter", "alert"] : ["s-warn", e.status, "clock"]))}
        ${e.error ? `<small class="ilr-err">${esc(e.error)}</small>` : ""}</span></li>`).join("")}</ol>` : ""}</div>`;
  }

  // ---------- Layer inspection ----------
  function part(p, h) {
    const s = PST[p.state];
    return `<li class="ilr-part${p.present ? "" : " ilr-off"} ilr-p-${p.state}">
      <div class="ilr-ph">${to(p.view, `${esc(p.name)}${icon("right")}`, "linkbtn ilr-name")}<span class="ilr-pp">${p.required ? `<span class="ilr-req" title="The layer needs this part">Required</span>` : ""}${h.pill(s[0], s[1], s[2])}</span></div>
      <p class="ilr-what">${esc(p.what)}</p>
      ${p.figures.length ? `<dl class="ilr-figs">${p.figures.map(f => `<div><dt>${esc(f.label)}</dt><dd class="num">${esc(val(f.value))}</dd></div>`).join("")}</dl>` : ""}
      ${p.checks.length ? `<ul class="ilr-checks">${p.checks.map(c => `<li class="ilr-c-${c.level}">${icon(c.level === "fail" ? "alert" : "info")}<span>${esc(c.text)}</span></li>`).join("")}</ul>` : ""}
      ${p.note ? `<p class="ilr-note faint small">${esc(p.note)}</p>` : ""}</li>`;
  }

  function inspect(d, h) {
    const order = [...LOOP, "knowledge"];
    const Ls = order.map(k => d.layers.find(l => l.key === k)).filter(Boolean);
    const rank = { degraded: 0, incomplete: 1, idle: 2, partial: 3, operational: 4 };
    if (!lay || !Ls.some(l => l.key === lay)) lay = [...Ls].sort((a, b) => rank[a.status] - rank[b.status])[0]?.key;
    const l = Ls.find(x => x.key === lay);
    if (!l) return "";
    const s = ST[l.status];
    const pick = `<nav class="ilr-lpick" aria-label="Layer">${Ls.map(x => `<button type="button" class="ilr-s-${x.status}" data-hub="inspect" data-id="${x.key}" aria-pressed="${x.key === lay}">${icon(x.icon)}${esc(x.title)} ${h.pill(...ST[x.status])}</button>`).join("")}</nav>`;
    const dep = l.depends.length ? `<p class="ilr-deps"><span class="faint">Depends on</span>${l.depends.map(x => `<button type="button" class="ilr-dep ilr-s-${x.status}" data-hub="inspect" data-id="${x.key}" title="${esc(x.why)}">${esc(x.title)} ${h.pill(...ST[x.status])}</button>`).join("")}</p>` : "";
    const io = (d.links || []).filter(x => x.from === l.key || x.to === l.key || (x.shared && l.key !== "knowledge"));
    const ioRows = io.length ? `<ul class="ilr-why">${io.map(x => `<li><b class="num">${fmtNum(x.done, 0)}</b><span><b>${x.from === l.key ? "Out" : "In"}: ${x.shared ? `${esc(T(d, x.from))} → every layer` : edgeName(d, x)}</b> ${h.pill(...EST[x.state])}<small class="faint">${esc(x.label)}</small></span></li>`).join("")}</ul>` : h.empty("No handoff in or out.");
    const ev = d.events || [];
    const log = ev.length ? `<ol class="ilr-hist">${ev.map(e => `<li><span class="faint">${ago(e.created_at)}</span><span><b>${esc(e.event_type)}</b> <small class="faint">${esc(e.correlation_id || "")} · ${esc(e.source_layer)} → ${esc(e.target_layer)}</small>
        ${e.status !== "done" ? h.pill(e.status === "dead" ? "s-crit" : "s-warn", e.status, e.status === "dead" ? "alert" : "clock") : ""}${e.error ? `<small class="ilr-err">${esc(e.error)}</small>` : ""}</span></li>`).join("")}</ol>` : h.empty("No handoff event of this layer's yet.");
    return `${pick}<section class="card occ-card axh-card axh-span12 ilr-layer ilr-${l.status}" id="ilr-${l.key}" aria-labelledby="ilr-h-${l.key}">
      <div class="ilr-lh"><span class="ilr-n">${icon(l.icon)}</span><div><h2 id="ilr-h-${l.key}">${esc(l.title)}</h2><p class="faint">${esc(l.about)}</p><p class="small">${esc(DOES[l.key] || "")}</p></div>
        <div class="ilr-ls">${h.pill(s[0], s[1], s[2])}<small class="faint">${l.working} of ${h.plural(l.required, "required part")} working · ${l.present} of ${l.total} set up</small></div></div>
      ${dep}<ul class="ilr-parts">${l.parts.map(p => part(p, h)).join("")}</ul></section>
      ${h.card("ilr-io", "route", "Handoffs in and out", `<span class="faint small">this week</span>`, ioRows)}
      ${h.card("ilr-log", "list", "Recent handoff events", `<span class="faint small">newest first</span>`, log)}`;
  }

  // ---------- Performance ----------
  function perfKpis(d, h) {
    const a = d.evidence?.now || {}, b = d.evidence?.before || {}, c = d.g5?.coverage, sp = d.g5?.spend, rb = d.g5?.retrieval?.metrics;
    const delta = a.score != null && b.score != null ? a.score - b.score : null;
    return `<div class="stats occ-kpis">${h.kpi("check", "Success rate", a.fail_rate == null ? "–" : `${fmtNum(100 - a.fail_rate, 1)}%`, `${val(a.runs)} finished runs this week`)}
      ${h.kpi("star", "Average score", val(a.score), delta == null ? "no week before to compare" : `${delta >= 0 ? "+" : ""}${fmtNum(delta, 1)} on the week before`, delta == null ? "" : delta >= 0 ? "ok" : "warn")}
      ${h.kpi("trophy", "Evaluation coverage", c?.scored_pct == null ? "–" : `${c.scored_pct}%`, `target ${c?.target ?? 95}% of scoreable runs`, c?.scored_pct == null ? "" : c.scored_pct >= (c.target ?? 95) ? "ok" : c.scored_pct < 50 ? "crit" : "warn")}
      ${h.kpi("coins", "Per validated result", sp?.usd_per_validated != null ? usd(sp.usd_per_validated) : sp?.tokens_per_validated != null ? `${h.tok(sp.tokens_per_validated)} tok` : "–", sp ? `${sp.validated} validated this week` : "")}
      ${h.kpi("book", "Retrieval recall@5", rb ? val(rb["recall@" + (rb.k || 5)]) : "–", rb ? `pass line ${rb.pass_line}` : "benchmark not run yet", rb ? (d.g5.retrieval.passed ? "ok" : "crit") : "")}
      ${h.kpi("cycle", "Regression rate", d.evidence?.regression?.rate == null ? "–" : `${d.evidence.regression.rate}%`, d.evidence?.regression?.decided ? `of ${h.plural(d.evidence.regression.decided, "promotion")}` : "no promotion decided yet")}</div>`;
  }

  function evidence(d, h) {
    const E = d.evidence || {}, a = E.now || {}, b = E.before || {}, R = E.regression || {}, P = E.last_promotion;
    const fmt = { score: v => fmtNum(v, 1), fail_rate: v => `${fmtNum(v, 1)}%`, tokens_per_run: v => h.tok(v), usd_per_run: v => `$${fmtNum(v, 4)}` };
    const row = (k, label, up) => {
      const x = a[k], y = b[k], f = fmt[k];
      let ch = "–", tone = "";
      if (x != null && y != null && y !== 0) {
        const p = (x - y) / Math.abs(y) * 100;
        ch = `${p > 0 ? "+" : ""}${fmtNum(p, 0)}%`;
        tone = Math.abs(p) < 1 ? "" : (p > 0) === up ? "ilr-good" : "ilr-bad";
      }
      return `<tr><th scope="row">${esc(label)}</th><td class="r num">${y == null ? "–" : esc(f(y))}</td><td class="r num">${x == null ? "–" : esc(f(x))}</td><td class="r num ${tone}">${esc(ch)}</td></tr>`;
    };
    return h.card("ilr-ev", "chart", "Improvement evidence", `<span class="faint small">this week against the week before</span>`,
      `<div class="tablewrap flat"><table class="grid axh-table ilr-evt"><thead><tr><th scope="col">Measure</th><th scope="col" class="r">Week before</th><th scope="col" class="r">This week</th><th scope="col" class="r">Change</th></tr></thead><tbody>
        ${row("score", "Average run score", true)}${row("fail_rate", "Failed or lost runs", false)}${row("tokens_per_run", "Tokens per finished run", false)}${row("usd_per_run", "Dollars per costed run", false)}
        <tr><th scope="row">Finished runs</th><td class="r num">${val(b.runs)}</td><td class="r num">${val(a.runs)}</td><td></td></tr></tbody></table></div>
       <ul class="axh-kv ilr-kv"><li><span>Regression rate</span><b>${R.rate == null ? "–" : `${R.rate}%`} <small class="faint">${R.decided ? `${R.rolled_back} of ${h.plural(R.decided, "promotion")} rolled back` : "no promotion decided yet"}</small></b></li>
        <li><span>Last successful promotion</span><b>${P ? `${esc(P.what)} <small class="faint">${esc(P.where)} · ${ago(P.when)}${P.before != null && P.after != null ? ` · ${esc(val(P.before))} → ${esc(val(P.after))}${P.cases ? ` on ${P.cases} cases` : ""}` : ""}</small>` : "None yet"}</b></li></ul>
       <p class="faint small">Scores come from evaluators and verifiers on scored runs only; a change in the mix of work moves these too.</p>`);
  }

  function coverage(g, h) {
    const c = g?.coverage;
    if (!c) return "";
    const li = (a, f) => a.length ? `<ul class="ilr-why">${a.map(f).join("")}</ul>` : "";
    const ok = c.scored_pct != null && c.scored_pct >= c.target;
    return h.card("ilr-cov", "trophy", "Evaluation coverage", `<span class="faint small">finished runs this week</span>`,
      `<p class="ilr-rqh">${h.pill(...(c.scored_pct == null ? ["s-off", "Nothing to score yet", ""] : ok ? ["s-ok", `${c.scored_pct}% scored`, "check"] : ["s-warn", `${c.scored_pct}% scored`, "alert"]))}
        ${c.scored_pct != null ? h.meter(c.scored_pct / 100, `${c.scored_pct}% of scoreable runs`) : ""} <span class="faint small">target ${c.target}%</span></p>
       <p class="small">${fmtNum(c.scored, 0)} scored of ${fmtNum(c.finished, 0)} finished runs (${c.of_finished_pct ?? "–"}%). The ${c.scored_pct ?? "–"}% counts only the ${fmtNum(c.scoreable ?? c.scored + c.gap, 0)} runs that can be scored: the ${fmtNum(c.excluded, 0)} excluded ones have a stated reason not to be. Under Final outcomes, excluded runs that failed are counted by their cause instead.</p>
       <dl class="ilr-figs ilr-covf"><div><dt>Finished</dt><dd class="num">${fmtNum(c.finished, 0)}</dd></div><div><dt>Scored</dt><dd class="num">${fmtNum(c.scored, 0)}</dd></div>
        <div><dt>Reviewed, unmeasured</dt><dd class="num">${fmtNum(c.reviewed || 0, 0)}</dd></div>
        <div><dt>Excluded, with a reason</dt><dd class="num">${fmtNum(c.excluded, 0)}</dd></div><div><dt>No verdict</dt><dd class="num">${fmtNum(c.gap, 0)}</dd></div>
        <div><dt>Waiting for a verdict</dt><dd class="num">${fmtNum(c.waiting, 0)}</dd></div><div><dt>Accounted for</dt><dd class="num">${c.accounted_pct == null ? "–" : c.accounted_pct + "%"}</dd></div></dl>
       ${outcomes(c.outcomes, h)}
       ${c.gaps.length ? `<h4 class="occ-h4">Without a verdict</h4>${li(c.gaps, x => `<li><b class="num">${x.n}</b><span>${esc(x.label)} · ${esc(x.kind)}<small class="faint">${esc(x.reason)}</small></span></li>`)}` : ""}
       ${c.reasons.length ? `<h4 class="occ-h4">Excluded</h4>${li(c.reasons, x => `<li><b class="num">${x.n}</b><span>${esc(x.reason)}</span></li>`)}` : ""}
       ${c.sources.length ? `<h4 class="occ-h4">Where scores come from</h4>${li(c.sources, x => `<li><b class="num">${x.n}</b><span>${esc(x.source)}</span></li>`)}` : ""}
       ${c.scored_by ? `<p class="small ilr-kinds">Of the scored runs, ${fmtNum(c.scored_by.model_judged || 0, 0)} are <b>model-judged</b> (a model evaluator or verifier scored the output) and ${fmtNum(c.scored_by.derived || 0, 0)} are <b>derived</b> (a fixed number for a decision or a status). <b>None is measured.</b> Measured values are a mission's measures. A board task's review is counted as reviewed, with no score; runs scored before that rule keep their score.</p>` : ""}
       <p class="faint small">Every run type has an evaluator: its own system's verifier, a decision you make (accept, approve, merge), an evaluator agent, or an explicit exclusion (evaluation tooling, reporting, chats you rate). A verdict that comes after the deadline still turns a gap into a score.</p>`);
  }

  // every finished run in exactly one final outcome (orchestrator.outcomes), and how the recalled experiences settled
  function outcomes(o, h) {
    if (!o) return "";
    const R = o.runs, L = [["success", `Success (scored ${o.good}+)`, "s-ok"], ["partial", `Partial (${o.low}–${o.good - 1})`, "s-info"],
      ["failure", `The work failed (the task itself, over its cap, or under ${o.low})`, "s-crit"], ["environment", "Failed for the environment (restart, quota, provider, rate limit, sandbox…)", "s-warn"],
      ["stopped", "Stopped by a person", "s-off"], ["reviewed", "Reviewed, unmeasured (a board review: no score)", "s-info"],
      ["excluded", "Excluded, with a reason", "s-off"], ["unsettled", "No verdict yet", "s-warn"]];
    const tot = L.reduce((n, [k]) => n + (R[k] || 0), 0);
    const r = o.recalls;
    return `<h4 class="occ-h4">Final outcomes</h4><div class="tablewrap flat"><table class="grid axh-table ilr-out"><tbody>
        ${L.map(([k, l, c]) => `<tr><th scope="row"><span class="ilr-dot ${c}"></span>${esc(l)}</th><td class="r num">${fmtNum(R[k] || 0, 0)}</td></tr>`).join("")}
        <tr class="ilr-tot"><th scope="row">Finished runs</th><td class="r num">${fmtNum(tot, 0)}</td></tr></tbody></table></div>
      ${r ? `<p class="faint small">Recalled experiences this week: ${fmtNum(r.success, 0)} settled on success, ${fmtNum(r.partial, 0)} partial, ${fmtNum(r.failure, 0)} on failure, ${fmtNum(r.excluded, 0)} excluded (cancelled, unverified or gone), ${fmtNum(r.open, 0)} still open. The ranking learns only from success, partial and failure.</p>` : ""}`;
  }

  function spend(g, h) {
    const s = g?.spend;
    if (!s) return "";
    const rows = s.by_system.map(b => `<tr><td>${esc(b.label)}</td><td class="r num">${fmtNum(b.runs, 0)}</td><td class="r num">${h.tok(b.tokens)}</td><td class="r num">${usd(b.usd)}${b.estimated ? `<small class="faint"> est.</small>` : ""}</td></tr>`).join("");
    return h.card("ilr-spend", "coins", "Spending", `<span class="faint small">this week</span>`,
      `<dl class="ilr-figs"><div><dt>Dollars</dt><dd class="num">${usd(s.usd)}</dd></div><div><dt>Of which estimated</dt><dd class="num">${usd(s.estimated_usd)}</dd></div>
        <div><dt>Tokens</dt><dd class="num">${h.tok(s.tokens)}</dd></div><div><dt>On plans (no per-token price)</dt><dd class="num">${h.tok(s.plan_tokens)}</dd></div>
        <div><dt>Validated results</dt><dd class="num">${fmtNum(s.validated, 0)}</dd></div><div><dt>Per validated result</dt><dd class="num">${s.usd_per_validated != null ? usd(s.usd_per_validated) : "–"}</dd></div></dl>
       ${rows ? `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th scope="col">System</th><th scope="col" class="r">Runs</th><th scope="col" class="r">Tokens</th><th scope="col" class="r">Dollars</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
       <p class="faint small">${esc(s.basis)} A validated result is a run scored ${s.valid_at}+ or a verified mission.</p>`);
  }

  function budgets(g, h) {
    if (!g) return "";
    const rows = g.limits.map(x => `<tr><th scope="row">${esc(x.scope_label)}<small class="faint ilr-sub">${esc(x.label || x.key)}</small></th>
        <td class="r num">${x.tokens ? `${h.tok(x.spent)} / ${h.tok(x.tokens)}` : "–"}${x.used_pct != null ? `<br>${h.meter(x.used_pct / 100, `${x.used_pct}%`, x.used_pct >= 100 ? "over" : "")}` : ""}</td>
        <td>${x.tokens ? (x.period === "day" ? "a day" : "in all") : "–"}</td><td class="r num">${x.per_call ? h.tok(x.per_call) : "–"}</td>
        <td class="r num">${x.tokens ? `${x.warn_at}%` : "–"}</td><td>${x.mode === "alert" ? h.pill("s-warn", "Alerts only", "bell") : h.pill("s-ok", "Stops", "ban")}</td>
        <td class="r num">${fmtNum(x.blocked_7d, 0)}</td></tr>`).join("");
    const al = g.alerts, rec = (al?.recent || []).slice(0, 6);
    const alertBox = al ? `<form class="ilr-alertset" data-ilr-alerts><h4 class="occ-h4">Alerts</h4>
        <label><span>Warn at</span><input type="number" name="warn_pct" min="1" max="100" step="1" inputmode="numeric" value="${al.warn_pct}" aria-label="Warn at this percent of a limit"><span>% of a limit</span></label>
        <label class="ilr-chk"><input type="checkbox" name="notify" ${al.notify ? "checked" : ""}><span>Push it to my devices${al.push ? "" : " <small class=\"faint\">(no push server on this server)</small>"}</span></label>
        <button type="button" class="btn sm" data-hub="alerts">${icon("check")}Save</button>
        <p class="faint small">The default for your daily limit and every limit without its own share. Each crossing is recorded once per period; reaching a limit pushes even in quiet hours.</p></form>
      ${rec.length ? `<ul class="ilr-why ilr-alerts">${rec.map(x => `<li>${h.pill(...(x.level === "limit" ? ["s-crit", "Limit", "ban"] : ["s-warn", "Warning", "alert"]))}<span><b>${esc(x.label || x.ref)}</b>
          <small class="faint">${h.tok(x.spent)} of ${h.tok(x.tokens)}${x.period !== "total" ? ` on ${esc(x.period)}` : ""} · ${ago(x.ts)}</small></span></li>`).join("")}</ul>` : ""}` : "";
    const sg = (g.suggested_limits || []).length ? `<h4 class="occ-h4">Suggested limits${g.suggested_limits.length > 1 ? ` <button type="button" class="btn sm" data-hub="setall" title="Set every suggested limit, after you confirm">${icon("check")}Set all ${g.suggested_limits.length}</button>` : ""}</h4><ul class="ilr-why">${g.suggested_limits.map(x => `<li><b class="num">${h.tok(x.tokens)}</b><span><b>${esc(x.label)}</b> <small class="faint">a day · ${esc(x.why)}</small></span>
        <button type="button" class="btn sm" data-hub="setlimit" data-scope="${esc(x.scope)}" data-key="${esc(x.key)}" data-label="${esc(x.label)}" data-tokens="${x.tokens}" title="Set a hard limit of ${fmtNum(x.tokens, 0)} tokens a day">${icon("check")}Set</button></li>`).join("")}</ul>` : "";
    return h.card("ilr-bud", "coins", "Budgets", `<button type="button" class="linkbtn" data-axh-to="studio">Agent Operations → Budget</button>`,
      (g.limits.length ? `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th scope="col">Limit</th><th scope="col" class="r">Spent</th><th scope="col">Period</th>
          <th scope="col" class="r">Per call</th><th scope="col" class="r">Warns at</th><th scope="col">At the limit</th><th scope="col" class="r">Refused (7 d)</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : h.empty("No hard limit. A mission's dollar budget becomes one while it runs.")) + sg + alertBox +
      `<p class="faint small">Checked before every model call at the gateway: the work stops at the limit, and the refusal is classed as a budget stop, not the task's fault. ${h.plural(g.blocked_7d, "call")} refused this week. Suggestions are 1.5× your busiest day of the last 14; nothing is set until you click.</p>`);
  }

  function retrieval(g, h) {
    if (!g) return "";
    const r = g.retrieval, m = r?.metrics || {};
    const k = m.k || 5;
    return h.card("ilr-rq", "book", "Retrieval quality", `<button type="button" class="btn sm" data-hub="g5rb">${icon("play")}Run the benchmark</button>`,
      r ? `<p class="ilr-rqh">${h.pill(...(r.passed ? ["s-ok", "Passes", "check"] : ["s-crit", "Fails", "alert"]))} <span class="faint small">dataset v${esc(r.version)} (${esc(r.sha)}) · ${ago(r.ts)} · ${esc(r.by || "")}</span></p>
          <dl class="ilr-figs"><div><dt>Recall@${k}</dt><dd class="num">${esc(val(m[`recall@${k}`]))}</dd></div><div><dt>MRR</dt><dd class="num">${esc(val(m.mrr))}</dd></div>
            <div><dt>Cases</dt><dd class="num">${esc(val(m.cases))}</dd></div><div><dt>Pass line</dt><dd class="num">${esc(val(m.pass_line))}</dd></div>
            <div><dt>Not indexed</dt><dd class="num">${esc(val(m.not_indexed))}</dd></div><div><dt>Ranked out</dt><dd class="num">${esc(val(m.ranked_out))}</dd></div></dl>
          ${r.misses.length ? `<h4 class="occ-h4">Misses</h4><ul class="ilr-why">${r.misses.map(x => `<li><span>“${esc(x.query)}”<small class="faint">${esc(x.case)} · ${esc(x.why || "")}</small></span></li>`).join("")}</ul>` : ""}`
        : h.empty("Not run yet. It takes a sentence from each of up to 25 of your kept items and checks the Knowledge Hub finds that item in its top 5 (no chat model; one embedding per query when an embeddings endpoint is set). It runs by itself once a day."));
  }

  function failures(d, h) {
    const f = d.failures || [];
    return h.card("ilr-fails", "alert", "Why runs failed", `<span class="faint small">this week</span>`,
      h.bars(f.map(x => ({ label: x.label, value: x.n, tone: x.key === "low" ? "ilr-bar-low" : "" })), v => fmtNum(v, 0), { none: "No failed run this week." }) +
      `<p class="faint small">Classified from each failed run's error. Tool and sandbox failures only count when the error names them; "the task itself" is what's left. Finished runs scored under 50 are poor output, not errors.</p>`);
  }

  function diag(g, h) {
    if (!g) return "";
    const rec = ok => ok ? h.pill("s-ok", "Recoverable", "cycle") : h.pill("s-warn", "Needs a fix", "alert");
    const runs = g.diagnosis.length ? `<ul class="ilr-why ilr-diag">${g.diagnosis.map(x => `<li><b class="num">${x.n}</b><span><b>${esc(x.system_label)} · ${esc(x.label)}</b> ${rec(x.recoverable)}
        <small>${esc(x.recovery)}</small><small class="faint ilr-err">${esc(x.example || "")}</small></span></li>`).join("")}</ul>` : h.empty("No failed run this week.");
    const sbx = g.sandbox.length ? `<h4 class="occ-h4">Sandbox runs that couldn't run or timed out</h4><ul class="ilr-why ilr-diag">${g.sandbox.map(x => `<li><b class="num">${x.n}</b><span><b>${esc(x.label)}</b> ${rec(x.recoverable)}
        <small>${esc(x.recovery)}</small>${x.retried ? `<small class="faint">${h.plural(x.retried, "run")} retried</small>` : ""}</span>
        ${x.recoverable ? `<button type="button" class="btn sm" data-hub="g5sbx" data-id="${x.last_id}" title="Run the latest one of these again">${icon("cycle")}Retry latest</button>` : ""}</li>`).join("")}</ul>` : "";
    const rv = (g.recoverable || []).length ? `<h4 class="occ-h4">Failed runs a retry can fix</h4><ul class="ilr-why ilr-diag">${g.recoverable.map(x => `<li><span class="ilr-n0"></span><span><b>${esc(x.title || x.ref)}</b>
        <small class="faint">${esc(x.ref)} · ${esc(x.cls)} · ${ago(x.started)}</small><small>${esc(x.how)}</small></span>
        <button type="button" class="btn sm" data-hub="g5rec" data-id="${x.run_id}">${icon("cycle")}Recover</button></li>`).join("")}</ul>` : "";
    return h.card("ilr-diagc", "alert", "Root-cause diagnostics", `<span class="faint small">failed runs this week, by system and class</span>`, runs + rv + sbx);
  }

  function compare(g, h) {
    if (!g?.compare?.length) return "";
    return h.card("axh-span12 ilr-cmp", "chart", "Cost and quality by model", `<span class="faint small">this week, systems with 2+ runs per model</span>`,
      `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th scope="col">System</th><th scope="col">Model</th><th scope="col" class="r">Runs</th><th scope="col" class="r">Scored</th>
        <th scope="col" class="r">Avg score</th><th scope="col" class="r">Failed</th><th scope="col" class="r">Tokens per run</th><th scope="col" class="r">Dollars</th></tr></thead><tbody>
        ${g.compare.map(x => `<tr><td>${esc(x.label)}</td><td>${esc(x.model)}</td><td class="r num">${x.runs}</td><td class="r num">${x.scored}</td><td class="r num">${x.avg == null ? "–" : fmtNum(x.avg, 0)}</td>
          <td class="r num">${x.failed || 0}</td><td class="r num">${h.tok(x.tok)}</td><td class="r num">${x.usd == null ? "–" : "$" + fmtNum(x.usd, 2)}</td></tr>`).join("")}</tbody></table></div>`);
  }

  function optimize(g, h) {
    const o = g?.optimize;
    if (!o) return "";
    const K = { under: ["s-crit", "Underperforming", "alert"], failing: ["s-crit", "Failing", "alert"], costly: ["s-warn", "Costly", "coins"], strong: ["s-ok", "Strong", "check"] };
    const ag = o.agents.length ? `<ul class="ilr-why">${o.agents.map(x => `<li><b class="num">${x.avg ?? "–"}</b><span><b>${esc(x.name)}</b> ${h.pill(...K[x.kind])}
        <small class="faint">${esc(x.system)} · ${h.plural(x.runs, "run")}${x.scored ? `, ${x.scored} scored` : ""}${x.tokens ? ` · ${h.tok(x.tokens)} tokens per run` : ""}</small><small>${esc(x.advice)}</small></span></li>`).join("")}</ul>`
      : h.empty("No agent stands out from its system yet: it takes 5 runs, scored, to compare.");
    const md = o.models.length ? `<h4 class="occ-h4">Models</h4><ul class="ilr-why">${o.models.map(m => `<li><b class="num">+${m.best_avg - m.used_avg}</b><span><b>${esc(m.system)} · ${esc(m.kind)}</b><small>${esc(m.advice)}</small></span></li>`).join("")}</ul>` : "";
    const idle = o.idle ? `<p class="faint small">${h.plural(o.idle, "registered agent")} did no work in 30 days${o.idle_names.length ? `: ${esc(o.idle_names.join(", "))}${o.idle > o.idle_names.length ? "…" : ""}` : ""}. Retire or merge the ones you don't need.</p>` : "";
    return h.card("axh-span12 ilr-opt", "group", "Workforce optimization", `<span class="faint small">last 30 days, from the run ledger · recommendations only</span>`, ag + md + idle);
  }

  // ---------- Adaptive evolution ----------
  function pipeline(d, h) {
    if (!d.pipeline?.length) return "";
    const stall = d.pipeline.find(p => p.stall);
    return h.card("axh-span12 ilr-pipe", "rocket", "Evolution engine", `<span class="faint small">this week, by stage</span>`,
      `<ol class="ilr-stages">${d.pipeline.map((p, i) => `<li class="${p.n ? "" : "ilr-zero"}${p.stall ? " ilr-stall" : ""}"><span class="ilr-n">${i + 1}</span>
          <span>${to(p.view, `<b>${esc(p.label)}</b>`, "linkbtn ilr-sl")}<small class="faint">${esc(p.what)}</small></span><b class="num">${fmtNum(p.n, 0)}</b></li>`).join("")}</ol>
       <p class="small ${stall ? "ilr-warnline" : "faint"}">${stall ? `${icon("alert")}<span>The loop stops at <b>${esc(stall.label)}</b>: work reaches the stage before it but nothing moves on.${stall.key === "experiment" ? " Approve an experiment below, or let the Evolution policy run them (Governance)." : stall.key === "approve" ? " A measured change waits for your decision in the Evolution Lab." : ""}</span>` : "Observe → diagnose → propose → experiment → evaluate → approve → promote → monitor → roll back. Nothing is promoted on an agent's own say-so: the approve step is yours."}</p>`);
  }

  function proposals(g, h) {
    if (!g) return "";
    const P = g.proposals || [], pol = g.policy;
    const WHERE = { evolution: "Evolution Lab experiment", workforce: "Workforce trial", upgrade: "Upgrade sprint (Competition teams)", "own page": "Measured on its own page" };
    const can = p => ["proposed", "not_better", "failed"].includes(p.status) && (p.runs_in === "evolution" || (p.runs_in === "workforce" && !["testing", "better"].includes(p.trial?.status)));
    const row = p => `<li><span class="ilr-n0"></span><span><b>${esc(p.title)}</b> ${h.pill(h.state(p.status), p.status.replace(/_/g, " "))}
        <small class="faint">${esc(p.target_name || p.target_key)} · ${esc(p.origin)} · ${esc(WHERE[p.runs_in])}${p.baseline != null ? ` · ${val(p.baseline)} → ${val(p.candidate)} on ${p.cases} cases${p.dataset_version ? ` (dataset v${p.dataset_version})` : ""}` : ""}</small>
        ${p.trial ? `<small>Workforce improvement #${p.trial.id}: ${esc(p.trial.status.replace(/_/g, " "))}${p.trial.status === "better" ? " · promote it in the Workforce" : ""}</small>` : p.note ? `<small>${esc(p.note)}</small>` : ""}</span>
        ${can(p) ? `<button type="button" class="btn sm" data-hub="approve" data-id="${p.id}" title="Draft what it lacks (benchmark, candidate) and measure it against the current version">${icon("play")}Approve experiment</button>`
          : p.status === "verified" ? `<button type="button" class="btn sm" data-axh-to="evolution">${icon("check")}Decide in the Lab</button>` : ""}</li>`;
    return h.card("axh-span12 ilr-props", "sparkle", "Proposals", `<button type="button" class="linkbtn" data-axh-to="evolution">Evolution Lab${icon("right")}</button>`,
      `<p class="small ${pol?.mode === "recommend" ? "ilr-warnline" : "faint"}">${icon(pol?.mode === "recommend" ? "info" : "check")}<span>Evolution policy: <b>${esc(pol?.label || "–")}</b>.
        ${pol?.mode === "recommend" ? "Experiments wait for your approval here; set the policy to “Experiment in the sandbox” (Governance) to let the engine run them within its daily tokens." : "The engine runs experiments by itself within its daily tokens."}
        Promotion to production always needs you, except low-risk configuration under “Auto”.</span></p>
       ${P.length ? `<ul class="ilr-why ilr-diag">${P.map(row).join("")}</ul>` : h.empty("No open proposal. Diagnosed weak agents become proposals here.")}`);
  }

  function history(g, h) {
    if (!g) return "";
    const MST = { watching: ["s-info", "Watching", "clock"], kept: ["s-ok", "Kept", "check"], rolled_back: ["s-warn", "Rolled back", "cycle"], regressed: ["s-crit", "Regressed", "alert"], ended: ["s-off", "Ended", ""],
                  no_baseline: ["s-off", "Nothing to compare", "info"] };
    const mon = g.monitor.length ? `<ul class="ilr-why">${g.monitor.map(m => `<li><span><b>${esc(m.title)}</b> ${h.pill(...(MST[m.state] || MST.ended))}
        <small class="faint">${esc(m.target_name || m.target_key)} · experiment ${esc(val(m.exp_before))} → ${esc(val(m.exp_after))}${m.cases ? ` on ${m.cases} cases` : ""}${m.dataset_version ? ` (dataset v${m.dataset_version})` : ""}
        · ${m.basis === "ratings" ? "thumbs-up %" : "live runs"} ${esc(val(m.base_avg != null ? Math.round(m.base_avg) : null))} before → ${esc(val(m.after_avg != null ? Math.round(m.after_avg) : null))} after (${m.after_n || 0} ${m.basis === "ratings" ? "rated" : "scored"})</small>
        ${m.note ? `<small>${esc(m.note)}</small>` : ""}</span></li>`).join("")}</ul>` : h.empty("No promoted change watched yet.");
    const hist = g.history.length ? `<h4 class="occ-h4">Promotions and rollbacks</h4><ol class="ilr-hist">${g.history.map(x => `<li><span class="faint">${ago(x.ts)}</span><span><b>${esc(x.action.replace(/^(proposal|monitor|promotion)\./, "").replace(/_/g, " "))}</b> · ${esc(x.actor)}<small class="faint">${esc(x.detail || "")}</small></span></li>`).join("")}</ol>` : "";
    return h.card("axh-span12 ilr-hst", "cycle", "Promotion monitor and history", `<button type="button" class="linkbtn" data-axh-to="evolution">Evolution Lab</button>`, mon + hist);
  }

  Hubs.register("layers", {
    title: "Intelligence layers", kicker: "Control Hub", icon: "layers",
    lead: "AXoR's intelligence loop: Mission → Workforce → Execution → Evaluation → Adaptive, and back to Mission, with Knowledge and Governance across all of it. A layer is operational when every part it needs worked this week, work crossed into or out of it on the handoff ledger, and no check failed; partly working when some of that happened but not all; idle when none of it did; degraded when a check failed; incomplete when a part it needs is missing.",
    load: async (fresh, get) => {
      const [d, t, g, ev] = await Promise.all([get("/api/layers", fresh), get("/api/layers/trace" + (sel ? `?mission=${sel}` : ""), fresh).catch(() => ({ missions: [], trace: null })),
                                               get("/api/g5", fresh).catch(() => null), get(`/api/g5/events?limit=25${lay ? `&layer=${lay}` : ""}`, fresh).catch(() => [])]);
      return { ...d, trace: t, g5: g, events: ev };
    },
    actions: () => `<button type="button" class="btn sm" data-hub="eco" title="Agents → Ecosystem: the same systems as eight technical domains">${icon("layers")}System architecture (8 domains)</button>`,
    body(d, h) {
      const sc = d.score, cov = d.g5?.coverage, broken = (d.links || []).filter(x => x.state === "broken").length;
      const tabs = h.tabs("layers", [["overview", "layers", "Overview"], ["inspect", "search", "Layer inspection"], ["perf", "chart", "Performance"],
                                     ["adaptive", "cycle", "Adaptive evolution", (d.g5?.proposals || []).filter(p => ["proposed", "verified"].includes(p.status)).length || ""]]);
      const now = h.st("layers").tab;
      const kpis = `<div class="stats occ-kpis">${h.kpi("check", "Operational", `${sc.operational} of ${d.layers.length}`, "its parts worked and work crossed it", sc.operational === d.layers.length ? "ok" : "")}
          ${h.kpi("alert", "Degraded", sc.degraded, sc.degraded ? "a check failed" : "no failed check", sc.degraded ? "crit" : "")}
          ${h.kpi("zap", "Partly working", sc.partial ?? 0, "some of it worked this week, not all")}
          ${h.kpi("clock", "Idle", sc.idle, "nothing went through it this week")}
          ${h.kpi("alert", "Incomplete", sc.incomplete, sc.incomplete ? "a required part is missing" : "every required part is there", sc.incomplete ? "warn" : "")}
          ${h.kpi("route", "Broken handoffs", broken, broken ? "work reached a layer and stopped" : "nothing stopped this week", broken ? "crit" : "ok")}
          ${h.kpi("trophy", "Runs scored", cov?.scored_pct == null ? "–" : `${cov.scored_pct}%`, `of scoreable, target ${cov?.target ?? 95}%${cov?.of_finished_pct != null ? ` · ${cov.of_finished_pct}% of all finished` : ""}`, cov?.scored_pct == null ? "" : cov.scored_pct >= (cov.target ?? 95) ? "ok" : "warn")}</div>`;
      let main;
      if (now === "inspect") main = `<div class="occ-grid ilr-grid">${inspect(d, h)}</div>`;
      else if (now === "perf") main = `${perfKpis(d, h)}<div class="occ-grid ilr-grid">${evidence(d, h)}${coverage(d.g5, h)}${spend(d.g5, h)}${budgets(d.g5, h)}${retrieval(d.g5, h)}${failures(d, h)}${diag(d.g5, h)}${compare(d.g5, h)}${optimize(d.g5, h)}</div>`;
      else if (now === "adaptive") main = `<div class="occ-grid ilr-grid">${pipeline(d, h)}${proposals(d.g5, h)}${history(d.g5, h)}</div>`;
      else main = `${kpis}<div class="occ-grid ilr-grid">${architecture(d, h)}${handoffs(d, h)}${fix(d, h)}${acceptance(d, h)}${domains(h)}${trace(d, h)}</div>`;
      return `${tabs}${main}${d.errors.length ? `<p class="faint small occ-errs">${icon("info")}${esc(d.errors.join(" · "))}</p>` : ""}`;
    },
    act(a, el) {
      if (a === "inspect") { lay = el.dataset.id; setTab("inspect"); Hubs.reload?.(); }  // its events are fetched for the layer picked
      else if (a === "trace") { sel = +el.dataset.id; setTab("overview"); setTimeout(() => document.querySelector(".ilr-trace")?.scrollIntoView({ behavior: "smooth", block: "start" }), 300); }
      else if (a === "tools") Agents.tools();
      else if (a === "mission") MissionOS.show(+el.dataset.id);
      else if (a === "eco") { Agents.ops("ecosystem"); setView("agents"); }
      else if (a === "mxdraft") MissionOS.draft(CONTROLLED, 1);
      else if (a === "mxsn62") MissionOS.draft(SN62, 5, 62);
      else if (a === "mxfollow") MissionOS.draft(`Follow-up to mission #${el.dataset.id}: ${(el.dataset.goal || CONTROLLED).slice(0, 3900)}`, 1);
      else if (a === "setlimit") {
        const x = { scope: el.dataset.scope, key: el.dataset.key, label: el.dataset.label, tokens: +el.dataset.tokens, period: "day" };
        el.disabled = true;
        api("/api/g5/limits", { method: "PUT", body: { scope: x.scope, key: x.key, label: x.label, tokens: x.tokens, period: x.period } })
          .then(() => { toast(`Limit set: ${x.label}, ${fmtNum(x.tokens, 0)} tokens a day`); Hubs.reload?.(true); })
          .catch(e => { el.disabled = false; toast(e.message, { kind: "error" }); });
      }
      else if (a === "alerts") {
        const f = el.closest("[data-ilr-alerts]"), w = Math.round(+f.elements.warn_pct.value);
        if (!(w >= 1 && w <= 100)) return toast("Warn at 1 to 100 percent.", { kind: "error" });
        el.disabled = true;
        api("/api/g5/alerts", { method: "PUT", body: { warn_pct: w, notify: f.elements.notify.checked } })
          .then(() => { toast(`Alerts: warn at ${w}%${f.elements.notify.checked ? ", pushed to your devices" : ""}`); Hubs.reload?.(true); })
          .catch(e => { el.disabled = false; toast(e.message, { kind: "error" }); });
      }
      else if (a === "setall") {
        const L = [...(el.closest(".ilr-bud")?.querySelectorAll("[data-hub=setlimit]") || [])].map(b => ({ scope: b.dataset.scope, key: b.dataset.key, label: b.dataset.label, tokens: +b.dataset.tokens, period: "day" }));
        if (!L.length) return;
        UI.confirm({ title: `Set ${L.length} hard limits?`, body: "Each is checked before every model call: work under it stops at the limit until the next day. Change or remove them in Agent Operations → Budget.",
                     items: L.map(x => `${esc(x.label)}: ${fmtNum(x.tokens, 0)} tokens a day`), ok: "Set them", icon: "coins", danger: false,
                     run: () => Promise.all(L.map(x => api("/api/g5/limits", { method: "PUT", body: x }))) })
          .then(y => { if (y) { toast(`${L.length} limits set`); Hubs.reload?.(true); } });
      }
      else if (["g5retry", "g5sbx", "g5rb", "g5rec", "approve"].includes(a)) {
        const id = +el.dataset.id;
        const url = { g5retry: `/api/g5/events/${id}/retry`, g5sbx: `/api/g5/sandbox/${id}/retry`, g5rec: `/api/g5/runs/${id}/recover`,
                      approve: `/api/g5/proposals/${id}/approve`, g5rb: "/api/g5/retrieval/run" }[a];
        el.disabled = true;
        api(url, { method: "POST" }).then(r => {
          toast(a === "g5retry" ? (r.status === "done" ? "Retried: it went through" : `Retried: ${r.status}${r.error ? ` (${r.error})` : ""}`)
            : a === "g5sbx" ? `Running it again as sandbox run #${r.retried_as}` : a === "g5rec" ? `Recovered: ${r.recovered}`
            : a === "approve" ? (r.routed === "workforce" ? `Workforce trial started for improvement #${r.improvement}` : "Experiment started: the current and the candidate version answer the same frozen cases")
            : `Retrieval benchmark: ${r?.passed ? "passes" : "fails"}`);
          Hubs.reload?.(true);
        }).catch(e => { el.disabled = false; toast(e.message, { kind: "error" }); });
      }
    },
  });

  // the overview's map of the eight-domain System architecture onto these layers
  function domains(h) {
    return h.card("ilr-dom", "layers", "System architecture, mapped", `<button type="button" class="linkbtn" data-hub="eco">8 domains${icon("right")}</button>`,
      `<ul class="ilr-map">${DOMAINS.map(([name, ...ks]) => `<li><span>${esc(name)}</span><span class="faint">→</span><b>${ks.map(k => k === "governance" ? "Governance &amp; control (across)" : k === "knowledge" ? "Knowledge (across)" : esc(k[0].toUpperCase() + k.slice(1))).join(" + ")}</b></li>`).join("")}</ul>
       <p class="faint small">The eight domains are the technical system; the loop here is how a mission moves through it. Neither replaces the other.</p>`);
  }

  // switching tabs from a click inside the page: the same path as the tab bar (it keeps the choice per browser)
  const setTab = k => document.querySelector(`[data-axh-tab="${k}"]`)?.click();
})();
