/* Learning (Agents → Learning; hubs.js page "learning", learning.py /api/learning): how AXoR's agents get better from results,
   across every system that already learns. Knowledge is what AXoR knows (the sidebar's Knowledge section, the Knowledge hub),
   Intelligence is what it does with it (a mission's Intelligence brief), Learning is what it keeps from the results: mission
   lessons, Workforce and Workflow improvements, the watches that keep or roll back a promoted version, upgrade sprints.
   Every row leads to the page that owns it; the only action here is forgetting one of your own mission lessons. */
(() => {
  const KIND = { worked: ["check", "Worked"], failed: ["alert", "Failed"], strategy: ["route", "Strategy"] };
  // a lesson from a promoted trial is a technical result, not a verified mission: say so instead of showing the stored word
  const OUTCOME = { trial_verified: "from a promoted trial: a technical result", trial_rolled_back: "from a trial whose change was rolled back" };
  const SYSL = { workforce: ["group", "Workforce"], teams: ["users", "Competition teams"] };
  const TABS = d => [["lessons", "book", "Lessons", d.lessons.length], ["improvements", "sparkle", "Improvements", d.improvements.length],
                     ["after", "eye", "Watches & sprints", d.watches.length + d.sprints.length],
                     ...(d.experience ? [["recall", "search", "Experience recall", d.experience.week.recalls]] : [])];

  // the sidebar button shows whenever Benchmarks & evaluations does (command.js decides that for the agent hubs). Plain DOM
  // calls: app.js, which defines $, loads after this file.
  const ev = document.getElementById("nav-evaluation");
  const mirror = () => { const b = document.getElementById("nav-learning"); if (ev && b && b.hidden !== ev.hidden) b.hidden = ev.hidden; };
  mirror();
  if (ev) new MutationObserver(mirror).observe(ev, { attributes: true, attributeFilter: ["hidden"] });

  const step = (ic, cap, title, lines, to, toLabel) => `<div class="axl-step"><p class="axl-cap">${icon(ic)}${esc(cap)}</p><h3>${esc(title)}</h3>
      <ul>${lines.map(([n, t]) => `<li><b class="num">${esc(String(n))}</b> ${esc(t)}</li>`).join("")}</ul>
      ${to ? `<button type="button" class="linkbtn" data-axh-to="${to}">${esc(toLabel)}${icon("right")}</button>` : ""}</div>`;

  function loop(d) {
    const k = d.loop.knowledge, i = d.loop.intelligence, l = d.loop.learning;
    return `<section class="card occ-card axh-card axl-loop" aria-label="Knowledge, Intelligence and Learning">
      ${step("book", "Knowledge", "What AXoR knows", [[k.kb, "Knowledge hub items"], [k.memories, "Workforce memories"], [k.lessons, "mission lessons"]], "knowledge", "Knowledge hub")}
      <span class="axl-arrow" aria-hidden="true">${icon("right")}</span>
      ${step("bulb", "Intelligence", "What it does with it", [[i.briefs, `of ${i.missions} mission${i.missions === 1 ? "" : "s"} researched before planning`]], "mos", "Mission Control")}
      <span class="axl-arrow" aria-hidden="true">${icon("right")}</span>
      ${step("cycle", "Learning", "What it keeps from results", [[l.used, "times a lesson steered a later mission"], [l.adopted, "improvements adopted"], [l.kept, `promoted versions kept${l.rolled_back ? `, ${l.rolled_back} rolled back` : ""}`]])}
    </section>`;
  }

  function lessons(d, h) {
    const rows = d.lessons.filter(x => (h.st("learning").f === "all" || x.kind === h.st("learning").f) && h.match("learning", x.text, x.mission));
    return `<div class="axl-tools">${h.chips("learning", h.counts(d.lessons, "kind"), k => KIND[k] || ["info", k])}${h.search("learning", "Search lessons")}</div>
      ${!d.sources.missions ? h.empty("Mission Control isn't set up on this server, so there are no mission lessons.")
        : !d.lessons.length ? h.empty(`No lessons yet. Each mission keeps what worked and what failed when it finishes, and the next mission reads the relevant ones before it plans. <button type="button" class="linkbtn" data-axh-to="mos">Start a mission</button>`)
        : !rows.length ? h.empty("No lesson matches.")
        : `<ul class="axh-notes axl-lessons">${rows.map(x => `<li><span>${h.pill(x.kind === "failed" ? "s-crit" : x.kind === "strategy" ? "s-info" : "s-ok", (KIND[x.kind] || ["", x.kind])[1], (KIND[x.kind] || ["info"])[0])} ${esc(x.text)}</span>
            <small class="faint">${x.planners === false ? `<span title="${x.outcome === "trial_rolled_back" ? "The change this trial promoted was rolled back, so planners no longer receive this lesson. It stays here as an observation." : "Its mission wasn't verified, so planners don't receive this lesson. It stays here as an observation."}">observation, not given to planners</span> · ` : ""}${x.mission ? `${esc(x.mission)}${x.outcome ? ` (${esc(OUTCOME[x.outcome] || x.outcome)})` : ""} · ` : ""}${x.used ? `used by ${h.plural(x.used, "later mission")}` : "not used yet"} · ${ago(x.ts)}
            <button type="button" class="linkbtn axl-forget" data-hub="forget" data-id="${x.id}" title="Forget this lesson: later missions stop reading it">${icon("trash")}Forget</button></small></li>`).join("")}</ul>`}`;
  }

  function improvements(d, h) {
    const s = h.st("learning");
    const rows = d.improvements.filter(x => (s.f === "all" || x.system === s.f) && h.match("learning", x.who, x.where, x.why, x.change, x.result));
    const none = !d.sources.workforce && !d.sources.workflow;
    return `<div class="axl-tools">${h.chips("learning", h.counts(d.improvements, "system"), k => SYSL[k] || ["info", k])}${h.search("learning", "Search improvements")}</div>
      ${none ? h.empty("No improvement system is set up for your account: Workforce improvements, or (administrators) the Competition teams' Workflow.")
        : !d.improvements.length ? h.empty("No improvement yet. When an agent's work fails or scores low, its system diagnoses the cause, proposes a change and tests it against the current version before anything is adopted.")
        : !rows.length ? h.empty("No improvement matches.")
        : `<div class="tablewrap flat"><table class="grid axh-table axl-imp"><thead><tr><th>Agent</th><th>System</th><th>Why</th><th>Change</th><th>Result</th><th>Status</th><th>Updated</th></tr></thead><tbody>
          ${rows.map(x => `<tr><td><button type="button" class="linkbtn" ${h.go(x.go)}>${esc(x.who)}</button>${x.where && x.system === "teams" ? `<br><small class="faint">${esc(x.where)}</small>` : ""}</td>
            <td>${h.pill("src", (SYSL[x.system] || ["", x.system])[1], (SYSL[x.system] || ["info"])[0])}</td><td class="faint">${esc(x.why) || "–"}</td><td>${esc(x.change) || "–"}</td>
            <td class="faint">${esc(x.result) || "–"}</td><td>${h.pill(h.state(x.status), x.status.replace(/_/g, " "))}${x.version ? ` <small class="faint">v${x.version}</small>` : ""}</td><td class="faint">${ago(x.ts)}</td></tr>`).join("")}</tbody></table></div>`}`;
  }

  // Experience recall (experience.py, /api/experience): what agents recall from earlier work before they act, and how it went
  const OUT = { success: ["s-ok", "Succeeded", "check"], partial: ["s-warn", "Partly"], failure: ["s-crit", "Failed", "alert"] };
  const CTX = c => !c ? "" : c.startsWith("mx:") ? `Mission #${c.slice(3)}` : c.startsWith("wf:") ? `Workforce mission #${c.slice(3)}` : c.startsWith("mw:") ? `Team task #${c.slice(3)}` : c;
  let tried = { q: "", res: null, mode: "", err: "" };
  const expHit = (x, h) => `<li><span>${h.pill("src", x.kind)} <b>${esc(x.title)}</b>${x.outcome ? ` <small class="faint">outcome ${esc(x.outcome)}</small>` : ""}</span>
      <small class="faint">${esc(x.from)} · matched on ${esc(x.match || "?")} · ${x.record.success + x.record.partial + x.record.failure
        ? `used before: ${x.record.success} succeeded, ${x.record.partial} partly, ${x.record.failure} failed` : "not used on finished work yet"}${x.ts ? " · " + ago(x.ts) : ""}</small></li>`;
  const triedHtml = h => tried.err ? h.empty(esc(tried.err)) : !tried.res ? "" : !tried.res.length
    ? h.empty("Nothing from earlier work fits this. An agent asking the same would go on without recalled experience.")
    : `<ul class="axh-notes axl-exp-hits">${tried.res.map(x => expHit(x, h)).join("")}</ul>`;

  function recall(d, h) {
    const e = d.experience, w = e.week, settled = w.success + w.partial + w.failure;
    return `<div class="axl-exp-head"><p class="faint small">${icon("info")}Before they act, Mission Control, Workforce's planner and every Competition team task recall the experiences that fit the work: mission lessons, earlier missions, Workforce memories, team lessons and findings, finished Control Hub tasks and improvement trials. When the work ends, its outcome is kept with each experience it used, and the next recall ranks experiences with a better track record higher. That's an association, not proof the experience caused the outcome. Company project teams, your own agents and Agent HQ don't recall experiences yet.</p>
        <p class="small">${h.pill(e.mode === "meaning" ? "s-ok" : "s-warn", e.mode === "meaning" ? "Meaning search" : "Word forms only", e.mode === "meaning" ? "check" : "alert")} <span class="faint">${esc(e.embedder)}${e.mode === "meaning" ? "" : ": an OpenAI or OpenRouter key, or an embeddings endpoint, gives meaning search"} · ${e.indexed} of ${e.total} experiences indexed</span></p></div>
      <div class="stats occ-kpis">${h.kpi("search", "Recalls this week", w.recalls, `${h.plural(e.total, "experience")} to recall from`)}
        ${h.kpi("check", "On work that succeeded", w.success, settled ? `of ${settled} settled uses` : "no work has ended yet")}
        ${h.kpi("alert", "On work that failed", w.failure, w.partial ? `${w.partial} partly` : "", w.failure > w.success ? "warn" : "")}
        ${h.kpi("cycle", "Waiting for an outcome", w.open, "work still running or unverified")}</div>
      <div class="occ-grid">
        ${h.card("axh-span12", "search", "Try a recall", `<span class="faint small">what an agent about to do this would get; not logged</span>`,
          `<div class="axl-exp-try"><label class="sr" for="axl-exp-q">What is an agent about to do?</label><input id="axl-exp-q" type="search" maxlength="600" placeholder="e.g. register a validator on SN62" value="${esc(tried.q)}" autocomplete="off">
            <button type="button" class="btn sm" data-hub="exp-try">${icon("search")}Recall</button></div><div id="axl-exp-out">${triedHtml(h)}</div>`)}
        ${h.card("axh-span6", "layers", "What can be recalled", "", `<ul class="occ-list axl-exp-src">${e.sources.map(x => `<li><button type="button" class="occ-row" data-axh-to="${x.view}"><span class="occ-need-t"><b>${esc(x.label)}</b></span><b class="num">${x.count}</b></button></li>`).join("")}</ul>`)}
        ${h.card("axh-span6", "eye", "Latest recalls", "", !e.recent.length ? h.empty("No recall yet. The next mission, Workforce plan or team task recalls what fits it.")
          : `<ul class="axh-notes axl-exp-log">${e.recent.slice(0, 20).map(r => `<li><span><b>${esc(r.label || r.actor)}</b>${r.context ? ` <small class="faint">for ${esc(CTX(r.context))}</small>` : ""}: ${esc(r.query)}</span>
              <small class="faint">${r.found ? r.uses.map(u => u.outcome ? h.pill(OUT[u.outcome][0], `${u.kind}: ${OUT[u.outcome][1]}`, OUT[u.outcome][2]) : h.pill("s-off", u.kind)).join(" ") : "nothing fit"} · ${ago(r.ts)}</small></li>`).join("")}</ul>`)}
      </div>`;
  }

  // Enter in the recall box runs it (hubs.js wires clicks only)
  document.addEventListener("keydown", ev => { if (ev.key === "Enter" && ev.target?.id === "axl-exp-q") { ev.preventDefault(); document.querySelector('[data-hub="exp-try"]')?.click(); } });

  function after(d, h) {
    const w = d.watches.filter(x => h.match("learning", x.who, x.where, x.result)), sp = d.sprints.filter(x => h.match("learning", x.where, x.note));
    return `<div class="axl-tools">${h.search("learning", "Search")}</div><div class="occ-grid">
      ${h.card("axh-span12", "eye", "After a promotion", `<span class="faint small">kept or rolled back on real outcomes</span>`, !d.sources.workflow
        ? h.empty("Watches belong to the Competition teams' Workflow, which administrators run.")
        : !d.watches.length ? h.empty("No watch yet. When the Workflow promotes an improvement on its own, the new version's next real outcomes are compared with the one it replaced.")
        : `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Agent</th><th>Team</th><th>Version</th><th class="r">Score</th><th class="r">Before</th><th>Status</th><th>Result</th><th>When</th></tr></thead><tbody>
          ${w.map(x => `<tr><td><button type="button" class="linkbtn" ${h.go(x.go)}>${esc(x.who)}</button></td><td class="faint">${esc(x.where)}</td><td class="num">v${x.from ?? "?"} → v${x.to ?? "?"}</td>
            <td class="r num">${x.score ?? "–"}</td><td class="r num">${x.baseline ?? "–"}</td><td>${h.pill(x.status === "kept" ? "s-ok" : x.status === "rolled_back" ? "s-crit" : "s-warn", x.status.replace(/_/g, " "))}</td>
            <td class="faint">${esc(x.result) || "–"}</td><td class="faint">${ago(x.ts)}</td></tr>`).join("")}</tbody></table></div>`)}
      ${h.card("axh-span12", "sparkle", "Upgrade sprints", `<span class="faint small">Agent Upgrade Factory</span>`, !d.sources.upgrade
        ? h.empty("Upgrade sprints run on your open Competition teams; you have none, or the Upgrade Factory is off.")
        : !d.sprints.length ? h.empty("No upgrade sprint yet. A sprint diagnoses each agent, practises, and blind-tests the new version on held-out tasks before you promote it.")
        : `<ul class="occ-list">${sp.map(x => `<li><button type="button" class="occ-row" ${h.go(x.go)}><span class="occ-need-t"><b>${esc(x.where)}</b>
            <small>${Object.entries(x.agents).map(([k, n]) => `${n} ${k || "agents"}`).join(" · ") || "no agents"}${x.cap ? ` · ${h.tok(x.tokens)} of ${h.tok(x.cap)} tokens` : ""} · ${h.plural(x.versions, "version")} made on this team${x.note ? " · " + esc(x.note) : ""}</small></span>
            ${h.pill(h.state(x.status), x.status)}<small class="faint">${ago(x.ts)}</small></button></li>`).join("")}</ul>`)}
      </div>`;
  }

  Hubs.register("learning", {
    title: "Learning", kicker: "Learning", icon: "cycle",
    lead: "How your agents get better from results: the lessons missions keep and reuse, the improvements each system tested and adopted, and what happened after a new version went live. Knowledge is what AXoR knows; Intelligence is what it does with it; Learning is what it keeps.",
    load: async (fresh, get) => {
      const [l, e] = await Promise.all([get("/api/learning", fresh), get("/api/experience", fresh).catch(() => null)]);  // no Knowledge Hub: no recall tab
      return { ...l, experience: e };
    },
    actions: () => `<button type="button" class="btn sm" data-axh-to="evaluation">${icon("chart")}Benchmarks &amp; evaluations</button>`,
    body(d, h) {
      const l = d.loop.learning, tabs = h.tabs("learning", TABS(d)), tab = h.st("learning").tab;
      const mem = d.memory;
      return `<div class="stats occ-kpis">${h.kpi("book", "Mission lessons", d.loop.knowledge.lessons, `read back ${l.used} time${l.used === 1 ? "" : "s"}`)}
          ${h.kpi("sparkle", "Improvements", d.improvements.length, `${l.adopted} adopted`)}
          ${h.kpi("eye", "Kept after a watch", l.kept, l.rolled_back ? `${l.rolled_back} rolled back` : "none rolled back", l.rolled_back > l.kept ? "warn" : "")}
          ${h.kpi("cycle", "Upgrade sprints", d.sprints.length, `${d.sprints.filter(s => s.status === "running").length} running`)}
          ${mem ? h.kpi("bulb", "Workforce memory", mem.active, `cited ${mem.cited} · helped ${mem.helped}`, "", "workforce") : ""}</div>
        ${loop(d)}
        ${tabs}
        <div class="axl-tab">${tab === "improvements" ? improvements(d, h) : tab === "after" ? after(d, h) : tab === "recall" && d.experience ? recall(d, h) : lessons(d, h)}</div>
        ${d.errors.length ? `<p class="faint small occ-errs">${icon("info")}${esc(d.errors.join(" · "))}</p>` : ""}`;
    },
    async act(a, el) {
      if (a === "exp-try") {
        const q = (document.getElementById("axl-exp-q")?.value || "").trim(), out = document.getElementById("axl-exp-out");
        tried = { q, res: null, mode: "", err: "" };
        if (q.length < 3) tried.err = "Say in a sentence what an agent is about to do.";
        else {
          if (out) out.innerHTML = `<p class="faint small">Recalling…</p>`;
          try { const r = await api(`/api/experience/recall?q=${encodeURIComponent(q)}`); tried.res = r.results; tried.mode = r.mode; }
          catch (e) { tried.err = e.message; }
        }
        if (out) out.innerHTML = triedHtml(Hubs.ui);
        return;
      }
      if (a !== "forget") return;
      const ok = await UI.confirm({ title: "Forget this lesson?", body: "Later missions stop reading it when they plan. The mission and its report stay as they are.", ok: "Forget" });
      if (!ok) return;
      try { await api(`/api/learning/lessons/${el.dataset.id}`, { method: "DELETE" }); Auth.toast("Lesson forgotten."); }
      catch (e) { return Auth.toast(e.message); }
      $("#axh-learning [data-hub=refresh]")?.click();
    },
  });
})();
