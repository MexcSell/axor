/* Progress navigation (journey.css; prefix jny-), from the 2026-11-10 operations review ("simplify navigation around
   Goal → Work → Evidence → Approval → Result"): five stages at the top of the sidebar, in the order work turns into a result.
   Each stage opens the pages that answer it; they are the pages the sidebar already has, opened through their own buttons and
   routes, so roles, counts and Simple mode keep deciding what you can reach. Nothing here is a page of its own.
   - Goal: what the company wants (missions, each competition's target, projects)
   - Work: what is being done for it (task board, team boards, live operations, agents)
   - Evidence: what shows it worked (the frozen release candidate and its comparable benchmarks, the Lab, evaluation)
   - Approval: what waits for your decision (Approval Center, contracts, findings to share)
   - Result: what was achieved and checked (verified results, miner rank and rewards, cost per validated deliverable)
   The stage of the page on screen is marked and open; a stage whose pages you can't open isn't shown. */
const Journey = (() => {
  // [label, icon, the sidebar button it needs (id), the view it lands on, how to open it (default: that button's view), tooltip]
  const T = (fn) => () => { if (typeof MiningShell !== "undefined") MiningShell.go(fn); };
  const SEC = s => () => { if (typeof Control !== "undefined") Control.showSec(s); else setView("control"); };
  const STAGES = [
    ["goal", "Goal", "What the company wants: missions with a target, a budget and a deadline", [
      ["Missions", "target", "nav-mos", "mos", null, "Mission Control: goals with a budget, a deadline and deliverables"],
      ["Competition objectives", "trophy", "nav-command", "control", SEC("missions"), "Control Hub → Missions: each competition's target rank, objective and the gap to it"],
      ["Projects", "layers", "nav-projects", "projects", null, "Long-running initiatives and their objectives"]]],
    ["work", "Work", "What is being done for the goals: tasks, team boards and agents at work", [
      ["Task board", "list", "nav-missions", "missions", null, "Every task of every system on one board"],
      ["Team boards", "users", "nav-teams", "teams", T({ teams: "tasks" }), "Competition teams: each team's board of tasks"],
      ["Live operations", "radio", "nav-mining", "mining", T({ ops: "live" }), "Every team run as it happens"],
      ["Agents", "bot", "tab-agents", "agents", null, "Every agent, what it is doing and its runs"]]],
    ["evidence", "Evidence", "What shows the work did what it should: the frozen candidate, comparable benchmarks, evaluations", [
      ["Release & benchmarks", "shield", "nav-teams", "teams", T({ teams: "status" }), "Competition teams → Status: the frozen release candidate, its benchmark suite and the results comparable with it"],
      ["Performance lab", "chart", "nav-mining", "mining", T({ cmd: "perf" }), "Ingested results, runs compared side by side"],
      ["Agent evaluation", "check", "nav-evaluation", "evaluation", null, "Scores and benchmarks of the agents themselves"],
      ["Evolution Lab", "bulb", "nav-evolution", "evolution", null, "Changes tested against the current version; promoted only with evidence"]]],
    ["approval", "Approval", "What waits for your decision", [
      ["Approval Center", "inbox", "nav-approvals", "approvals", null, "Every request waiting for your decision, oldest and repeated ones marked"],
      ["Contracts & approvals", "layers", "nav-company", "company", null, "Agent contracts and project approvals"],
      ["Findings to share", "piechart", "nav-portfolio", "portfolio", null, "Lessons from one team waiting for your approval to be shared"]]],
    ["result", "Result", "What was achieved and checked, not just run", [
      ["Verified results", "check", "nav-command", "control", () => { SEC("overview")(); flash(); }, "Missions verified, releases frozen, changes promoted and benchmark change, beside the run success rate"],
      ["Miner performance", "pickaxe", "nav-mining", "mining", T({ cmd: "miners" }), "Rank, rewards and health of each miner"],
      ["Rewards & costs", "coins", "nav-mining", "mining", T({ cmd: "rewards" }), "What the miners earned against what they cost"],
      ["Analytics", "piechart", "nav-analytics", "analytics", null, "Company, mission and financial performance: cost per validated deliverable"]]],
  ];
  // the pages Simple mode keeps (mission.js setMode): the other links wait for Advanced mode
  const SIMPLE = ["mos", "approvals", "notifications", "help", "mining", "teams", "control"];
  const LINKS = STAGES.flatMap(([stage, , , links]) => links.map(l => ({ stage, label: l[0], icon: l[1], of: l[2], view: l[3], run: l[4], tip: l[5] })));
  let root = null, open = null, last = null, wired = false, q = 0;

  const simple = () => document.body.dataset.axmode === "simple";
  const hide = (el, h) => { if (el.hidden !== h) el.hidden = h; };  // only real changes: the sidebar's observers (and this one) watch "hidden"
  const usable = l => { const b = document.getElementById(l.of); return !!b && !b.hidden && !b.closest(".side-sec")?.hidden && (!simple() || SIMPLE.includes(l.view)); };

  function init() {
    if (wired) return; const side = $("#side"); if (!side) return; wired = true;
    root = document.createElement("div");
    root.className = "jny"; root.id = "jny";
    root.setAttribute("role", "navigation"); root.setAttribute("aria-label", "Progress: Goal, Work, Evidence, Approval, Result");
    root.innerHTML = `<p class="jny-h" title="Follow work from what the company wants to what it achieved">Progress</p><ol class="jny-steps">${STAGES.map(([k, name, about, links], i) => `
      <li class="jny-step" data-stage="${k}">
        <button type="button" class="jny-btn" aria-expanded="false" title="${esc(name)}: ${esc(about)}"><span class="jny-n" aria-hidden="true">${i + 1}</span><span class="lbl">${esc(name)}</span><span class="jny-c" hidden></span>${icon("chev", "jny-chev")}</button>
        <div class="jny-kids">${links.map(l => { const j = LINKS.findIndex(x => x.stage === k && x.label === l[0]);
          return `<button type="button" class="jny-go" data-j="${j}" title="${esc(l[5])}">${icon(l[1])}<span class="lbl">${esc(l[0])}</span></button>`; }).join("")}</div></li>`).join("")}</ol>`;
    const head = $(".sdb-head", side);
    if (head) head.after(root); else side.prepend(root);
    root.addEventListener("click", e => {
      const g = e.target.closest(".jny-go");
      if (g) return go(LINKS[+g.dataset.j]);
      const b = e.target.closest(".jny-btn"); if (!b) return;
      const k = b.closest(".jny-step").dataset.stage;
      const folded = side.classList.contains("collapsed") && innerWidth > 900;
      if (open === k && !folded) { open = null; return draw(); }  // a second click folds it
      open = k; draw();
      const first = LINKS.find(l => l.stage === k && usable(l));
      if (first && (folded || !curStage() || curStage() !== k)) go(first);  // a stage opens its first page; the folded sidebar has nothing else to show
    });
    // what may be opened changes after sign-in, with the role and the agents check (auth.js), and with Simple mode
    const sync = () => { cancelAnimationFrame(q); q = requestAnimationFrame(draw); };
    new MutationObserver(sync).observe(side, { subtree: true, attributes: true, attributeFilter: ["hidden"] });
    new MutationObserver(sync).observe(document.body, { attributes: true, attributeFilter: ["data-axmode"] });
    const c = $("#c-approvals"); if (c) new MutationObserver(sync).observe(c, { childList: true, characterData: true, subtree: true });
    onView(S.view);
  }

  function go(l) {
    if (!l || !usable(l)) return;
    last = l; open = l.stage;
    if (innerWidth <= 900) sideOpen(false);
    if (l.run) l.run(); else setView(l.view);
    draw();
  }
  // the link on screen: the one you used while its page shows, else the one link to this page. Pages more than one link opens
  // (the Control Hub is Goal's objectives and Result's figures; My subnets has screens in three stages) mark no stage when
  // reached some other way: a guess would point at the wrong one.
  function cur() {
    if (last && last.view === S.view) return last;
    const m = LINKS.filter(l => l.view === S.view && usable(l));
    return m.length === 1 ? m[0] : null;
  }
  const curStage = () => cur()?.stage || null;

  function onView(v) {
    if (!root) return;
    if (last && last.view !== v) last = null;
    const s = curStage(); if (s) open = s;
    draw();
  }

  function draw() {
    if (!root) return;
    const c = cur(), any = LINKS.some(usable);
    hide(root, !any);
    if (!any) return;
    $$(".jny-step", root).forEach(st => {
      const k = st.dataset.stage, kids = $$(".jny-go", st);
      let n = 0;
      kids.forEach(b => { const l = LINKS[+b.dataset.j], ok = usable(l); hide(b, !ok); n += ok; b.classList.toggle("jny-cur", l === c); });
      hide(st, !n);
      const on = c?.stage === k, shown = open === k;
      st.classList.toggle("jny-on", on); st.classList.toggle("jny-open", shown);
      const btn = $(".jny-btn", st); btn.setAttribute("aria-expanded", String(shown));
      if (on) btn.setAttribute("aria-current", "step"); else btn.removeAttribute("aria-current");
      if (k === "approval") {  // the Approval Center's own count (app.js), so the stage shows what waits without opening it
        const t = ($("#c-approvals")?.textContent || "").trim(), cnt = $(".jny-c", st);
        if (cnt.textContent !== t) cnt.textContent = t; hide(cnt, !t || t === "0");
      }
    });
  }

  // the Verified results figure sits among the Control Hub's headline figures: show where
  function flash() {
    const t0 = Date.now();
    const tick = () => {
      const k = $$("#ctl .ctl-cc-kpi").find(x => /Verified results/.test(x.textContent));
      if (k) { k.scrollIntoView({ block: "center", behavior: "smooth" }); k.classList.add("jny-flash"); setTimeout(() => k.classList.remove("jny-flash"), 2400); return; }
      if (Date.now() - t0 < 6000) setTimeout(tick, 150);
    };
    setTimeout(tick, 80);
  }

  return { init, onView, stages: () => STAGES.map(([k, name, about]) => ({ key: k, name, about })) };
})();
