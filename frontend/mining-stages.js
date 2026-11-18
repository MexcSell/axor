/* Competition teams, the five stages of a team's workspace (mining-stages.css), from the 11-07 AXoR evaluation: "group the tabs
   around the actual working process: Overview · Plan · Run · Evaluate · Deliver; everything else becomes a contextual tool".
   Nothing moves or disappears: every earlier tab keeps its key (data-mwsub), its page and its route (My subnets' rail, the
   guided tours, links inside the pages), it is only filed under one stage. The stage row picks a stage (it opens the tool you
   last used there); the row under it lists that stage's tools. MiningBench.tabs() draws this in place of the old tabs + More.
   Counts are the ones the old tabs showed (waiting tasks, GitHub mentions, the Director's asks). */
const MiningStages = (() => {
  // [key, label, about]; the tools: [sub key, label, icon, tooltip?]. A sub key that isn't listed lands in Run (a future tab stays reachable).
  const STAGES = [
    ["overview", "Overview", "Status, the team and what happened", [["status", "Status", "info"], ["team", "Agents", "users"], ["diagram", "Diagram", "route"],
      ["activity", "Activity", "clock"], ["levels", "Levels", "trophy"], ["desk", "Desk", "grid"]]],
    ["plan", "Plan", "Objective, roadmap and how agents work", [["topminer", "Top miner", "trophy"], ["roadmap", "Roadmap", "map"], ["loadout", "Loadouts", "sliders"],
      ["prompts", "Prompts", "chat"], ["notes", "Notebook", "book"], ["links", "Links", "link"]]],
    ["run", "Run", "The work itself, on the folder and the board", [["tasks", "Board", "list"], ["autoloop", "Autoloop", "cycle", "Autoloop: repeat change → test → refine on one bounded task, within iteration, time and token limits"],
      ["files", "Files", "folder"], ["sandbox", "Files & sandbox", "terminal"]]],
    ["evaluate", "Evaluate", "Scores against the baseline, upgrades", [["lab", "Lab", "chart"], ["upgrade", "Upgrade", "sparkle", "Upgrade: practice and a held-out exam for a new agent version; promote only with evidence, roll back any time"]]],
    ["deliver", "Deliver", "Reports, branches and submission", [["report", "Report", "inbox"], ["github", "GitHub", "github"]]],
  ];
  const STAGE_OF = Object.fromEntries(STAGES.flatMap(([k, , , tools]) => tools.map(t => [t[0], k])));
  const stageOf = sub => STAGE_OF[sub] || "run";
  const last = k => { const s = store.get(`mst.last.${k}`, null); return STAGE_OF[s] === k ? s : null; };

  // counts: {sub: [alert, plain]} from the old More list ([k, label, icon, alert, count]) and the two counted tabs
  function counts(more, extra) {
    const out = {};
    for (const [k, , , a, n] of more || []) out[k] = [a || 0, n || 0];
    for (const [k, a] of Object.entries(extra || {})) out[k] = [a || 0, out[k]?.[1] || 0];
    return out;
  }
  const badge = ([a, n] = [0, 0]) => a ? `<span class="hq-n alert">${a}</span>` : n ? `<span class="hq-n">${n}</span>` : "";

  function tabs(sub, more, extra) {
    const cur = stageOf(sub), c = counts(more, extra);
    store.set(`mst.last.${cur}`, sub);
    const stage = STAGES.map(([k, label, about, tools], i) => {
      const alerts = tools.reduce((s, t) => s + (c[t[0]]?.[0] || 0), 0), go = k === cur ? sub : last(k) || tools[0][0];
      return `<button type="button" role="tab" class="mst-stage" data-mwsub="${go}" aria-selected="${k === cur}" title="${esc(about)}">
        <span class="mst-n" aria-hidden="true">${i + 1}</span><span class="mst-t"><b>${label}</b><small>${esc(about)}</small></span>${alerts ? `<span class="hq-n alert">${alerts}</span>` : ""}</button>`;
    }).join("");
    const tools = STAGES.find(s => s[0] === cur)[3];
    const unknown = STAGE_OF[sub] ? [] : [[sub, sub, "dots"]];
    return `<nav class="mst" aria-label="Team workspace stages"><div class="mst-row" role="tablist">${stage}</div></nav>
      <div class="mb-tabs mst-tools" role="tablist" aria-label="${esc(STAGES.find(s => s[0] === cur)[1])} tools">${[...tools, ...unknown].map(([k, l, ic, tip]) =>
        `<button type="button" role="tab" data-mwsub="${k}" aria-pressed="${k === sub}" aria-selected="${k === sub}"${tip ? ` title="${esc(tip)}"` : ""}>${icon(ic)}${esc(l)}${badge(c[k])}</button>`).join("")}</div>`;
  }

  // the team header's Advanced menu (mining-work.js) shuts on a click outside it or Escape
  const openMenus = () => Array.from(document.querySelectorAll(".mw-adv[open]"));
  document.addEventListener("click", e => { openMenus().forEach(d => { if (!d.contains(e.target)) d.open = false; }); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") openMenus().forEach(d => { d.open = false; d.querySelector("summary")?.focus(); }); });

  return { tabs, stageOf, STAGES };
})();
