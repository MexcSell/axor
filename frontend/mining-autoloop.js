/* Competition teams, the Autoloop (mining_autoloop.py), a sub-tab of the Competition teams page (mining-work.js draws the page):
   - The cycle: observe → plan → execute → verify → learn → optimize → repeat, each step with what it's doing now, what it did
     today and whether the governor holds it.
   - The governor's five checks before work starts (team budget with its reserve, competition budget, model provider, does
     the next task fit, a free slot), with the budget meter.
   - The queue: slots, queued, open, free agents, why the queue is as long as it is, long queues to spread over idle
     squad-mates, near-duplicate tasks to delete.
   - Failures by class (what each class does: back in the queue, retried, counted), retries waiting, tasks held for the user.
   - Economics: tokens per run, per filed task, per verified task, and the week.
   - Suggestions, the rules in force and the policy form.
   - Autopilot mode: act, or observe only (it logs what it would start, plan and review; each entry is matched against what
     you did, which gives an agreement rate). */
const MiningAutoloop = (() => {
  const W = "/api/mining/work";
  let d = null, dWid = null, dAt = 0, loading = false, failed = "", wired = false, polOpen = false;
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const short = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n || 0, 0);
  const at = ts => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const STAGE = { observe: ["Observe", "eye"], plan: ["Plan", "route"], execute: ["Execute", "play"], verify: ["Verify", "check"],
    learn: ["Learn", "book"], optimize: ["Optimize", "sliders"], repeat: ["Repeat", "cycle"] };
  const LEVEL = { stop: "bad", warn: "warn", info: "none", ok: "ok" };

  function need(v) {
    const wid = v.comp.id;
    if (dWid !== wid) { d = null; dWid = wid; dAt = 0; failed = ""; }
    if (loading || Date.now() - dAt < 5000) return;
    loading = true;
    api(`${W}/comps/${wid}/autoloop`).then(x => { if (dWid === wid) { d = x; failed = ""; } })
      .catch(e => { failed = e.message; }).finally(() => { dAt = Date.now(); loading = false; if (dWid === wid && !holding()) MiningWork.rerender(); });
  }
  // the policy form keeps what's typed: no re-render while it has focus
  const holding = () => !!document.activeElement?.closest?.(".mal-policy");

  // ---------- the cycle ----------
  function cycle() {
    const s = d.stages;
    const nodes = d.stage_order.map((k, i) => { const x = s[k], [label, ic] = STAGE[k];
      const state = x.held ? "held" : x.active ? "on" : "off";
      return `<li class="mal-st s-${state}" ${x.held ? `title="Held by the governor or the backlog"` : ""}>
        <span class="mal-st-n" aria-hidden="true">${i + 1}</span>
        <span class="mal-st-ic" aria-hidden="true">${icon(ic)}</span>
        <b>${label}</b>
        <span class="mal-st-v"><em>${fmtNum(x.n, 0)}</em> ${esc(x.unit)}</span>
        <span class="mal-st-l">${esc(x.line)}</span></li>`; }).join("");
    const st = !d.autopilot ? ["none", "Autopilot off"] : d.observe?.mode === "observe" && !d.paused ? ["wait", "Observing"] : d.paused ? ["warn", "Paused"] : d.status === "closed" ? ["off", "Closed"] : !d.gate.tasks ? ["warn", "Holding new work"] : ["run", "Running"];
    return `<section class="mh-card mal-cycle"><div class="mal-head"><div><h3>${icon("cycle")}Autoloop</h3>
        <p class="faint small">The team's loop improves the miner's own loop (one task: read, patch, test, return a diff). More activity isn't the goal: verified work at a sustainable cost is.</p></div>
        <span class="hq-chip t-${st[0]}">${esc(st[1])}</span></div>
      <ol class="mal-stages" aria-label="The Autoloop's steps">${nodes}</ol></section>`;
  }

  // ---------- the governor ----------
  function governor() {
    const g = d.gate, p = d.policy;
    const used = g.budget ? Math.min(1, g.day / g.budget) : 0, line = g.budget ? 1 - p.reserve / 100 : 1;
    const meter = g.budget ? `<div class="mal-meter" role="img" aria-label="${short(g.day)} of ${short(g.budget)} tokens used in 24 hours, new tasks stop at ${short(g.line)}">
        <i class="${used >= 1 ? "full" : used >= line ? "res" : ""}" style="--w:${(used * 100).toFixed(1)}%"></i><s style="--x:${(line * 100).toFixed(1)}%" title="New tasks stop here; the rest is kept for reviews"></s></div>
      <p class="mal-meter-l"><span>${short(g.day)} of ${short(g.budget)} tokens, last 24 h</span><span class="faint">reserve ${fmtNum(p.reserve, 0)}% for reviews</span></p>` : "";
    const checks = g.checks.map(c => `<li class="l-${c.level}"><span class="mal-ci" aria-hidden="true">${icon(c.ok ? "check" : c.level === "stop" ? "ban" : c.level === "info" ? "clock" : "alert")}</span>
        <span><b>${esc(c.label)}</b><span class="faint">${esc(c.until ? c.detail.replace(/\b\d{2}:\d{2} (?:[A-Z][A-Za-z]{1,5}|[+-]\d{2,4})\b/, at(c.until)) : c.detail)}</span></span>${!c.ok && c.key === "budget" ? `<button type="button" class="btn sm" data-mw="edit">Raise it</button>` : ""}${!c.ok && c.key === "provider" ? `<button type="button" class="btn sm" data-mal="cool">Resume now</button>` : ""}</li>`).join("");
    const rec = d.recovery;
    return `<section class="mh-card mal-card"><h3>${icon("shield")}Budget governor</h3>
      <p class="faint small">Five checks before anything starts. When one fails, work waits in the queue; it doesn't start, fail and count against the task.</p>
      ${meter}<ul class="mal-checks">${checks}</ul>
      <p class="faint small mal-cap">${icon("coins")}Each task run stops using tools at ${p.task_cap ? `<b>${short(p.task_cap)}</b> tokens${p.task_cap_auto ? " (automatic: 15% of the day's budget)" : ""}` : "no cap"} and must file what it has.</p>
      ${rec.recovered && rec.at ? `<p class="faint small">${icon("reset")}After the restart at ${at(rec.at)}, ${plural(rec.recovered, "task")} went back in the queue.</p>` : ""}</section>`;
  }

  // ---------- the queue ----------
  function queue() {
    const q = d.queue;
    const why = q.running >= q.slots && q.queued > q.slots
      ? `All ${q.slots} slots are busy with ${q.queued} queued and ${plural(q.free_agents, "agent")} free: the slot limit sets the pace, not the size of the team.`
      : q.queued && !d.gate.tasks ? "The governor holds the queue: see its checks." : q.queued ? "The queue moves as slots free up." : "Nothing is queued.";
    const piles = q.piles.map(x => `<li><span><b>${esc(x.name)}</b> has ${x.n} waiting${x.squad ? ` <span class="faint">· ${esc(x.squad)}</span>` : ""}</span>
        ${x.mates.length ? `<button type="button" class="btn sm" data-mal="spread" data-agent="${x.agent}" title="Idle in the squad: ${esc(x.mates.join(", "))}">${icon("swap")}Spread</button>` : `<span class="faint small">no idle squad-mate</span>`}</li>`).join("");
    const dupes = q.dupes.map(g => `<li class="mal-dupe"><span class="faint small">${g.length} alike</span>${g.map((t, i) => `<span class="mal-dupe-t">
        <button type="button" class="linkbtn" data-mwtask="${t.id}">${esc(t.title)}</button> <span class="faint small">${esc(t.agent)}</span>
        ${i ? `<button type="button" class="iconbtn sm" data-mal="drop" data-id="${t.id}" aria-label="Delete this copy" title="Delete this copy">${icon("trash")}</button>` : ""}</span>`).join("")}</li>`).join("");
    return `<section class="mh-card mal-card"><h3>${icon("list")}Queue</h3>
      <div class="mal-nums">
        <span><b>${q.running}<small>/${q.slots}</small></b>at work</span><span><b>${q.queued}</b>queued</span>
        <span><b>${q.ready}</b>ready</span><span><b>${q.free_agents}<small>/${q.agents}</small></b>agents free</span></div>
      <p class="small">${esc(why)}${q.oldest ? ` <span class="faint">Oldest in the queue: ${ago(q.oldest)}.</span>` : ""}</p>
      <p class="faint small">Autopilot keeps ${q.queue_cap ? `at most ${q.queue_cap}` : "every ready task"} queued; the Director waits to plan while ${q.backlog_cap ? `${q.backlog_cap} or more` : "any number of"} tasks are open (${q.open} now).</p>
      ${piles ? `<h4>Long queues</h4><ul class="mal-list">${piles}</ul>` : ""}
      ${dupes ? `<h4>Look like duplicates</h4><ul class="mal-list">${dupes}</ul>` : ""}</section>`;
  }

  // ---------- failures ----------
  function failures() {
    const f = d.failures;
    const rows = f.classes.map(c => `<tr><td><b>${esc(c.label)}</b>${c.example ? `<span class="faint small mal-ex">${esc(c.example)}</span>` : ""}</td><td class="num">${c.n}</td><td class="small">${esc(c.policy)}</td></tr>`).join("");
    const retry = f.retrying.map(t => `<li><button type="button" class="linkbtn" data-mwtask="${t.id}">${esc(t.title)}</button> <span class="faint small">${esc(t.agent)} · retry ${t.n} at ${t.at ? at(t.at) : "–"}</span></li>`).join("");
    const held = f.held.map(t => `<li><button type="button" class="linkbtn" data-mwtask="${t.id}">${esc(t.title)}</button> <span class="faint small">${esc(t.agent)}</span></li>`).join("");
    return `<section class="mh-card mal-card"><h3>${icon("ban")}Failures, last 24 hours</h3>
      ${rows ? `<div class="mal-tw"><table class="mal-table"><thead><tr><th>Class</th><th class="num">Runs</th><th>What happens</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : `<p class="ms-ok">${icon("check")}No failed runs.</p>`}
      ${retry ? `<h4>Retrying on their own</h4><ul class="mal-list">${retry}</ul>` : ""}
      ${held ? `<h4>Left to ${MiningDirector.relaying(MiningWork.view()) ? "the Director" : "you"} after failing twice</h4><ul class="mal-list">${held}</ul>` : ""}</section>`;
  }

  // ---------- economics ----------
  function economics() {
    const e = d.economics, max = Math.max(1, ...e.week.map(x => x.tokens));
    const bars = e.week.map((x, i) => { const dd = new Date(Date.now() - (6 - i) * 86400000);
      return `<span class="mal-day" title="${short(x.tokens)} tokens, ${x.verified} verified, ${dd.toLocaleDateString(undefined, { weekday: "long" })}"><em>${x.verified || ""}</em><i style="--h:${(x.tokens / max * 100).toFixed(0)}%"></i><small>${dd.toLocaleDateString(undefined, { weekday: "narrow" })}</small></span>`; }).join("");
    return `<section class="mh-card mal-card"><h3>${icon("coins")}Cost of the work</h3>
      <div class="mal-nums">
        <span><b>${short(e.tokens)}</b>tokens today</span><span><b>${short(e.per_run)}</b>per run</span>
        <span><b>${short(e.per_filed)}</b>per filed task</span><span class="mal-key"><b>${short(e.per_verified)}</b>per verified task</span></div>
      <p class="faint small">${e.runs} runs, ${e.filed} tasks filed, ${e.verified} approved by a reviewer, the Director or you.${e.fail_share ? ` ${fmtNum(e.fail_share * 100, 0)}% of runs failed (${short(e.wasted)} tokens).` : ""}</p>
      <div class="mal-week" aria-label="Tokens per day, last 7 days; the number is tasks verified that day">${bars}</div></section>`;
  }

  // ---------- observe mode ----------
  const OUT = { agreed: ["ok", "You did it"], differed: ["none", "You didn't"], yours: ["none", "You reviewed it"], gone: ["none", "Task gone"], ended: ["none", "Mode changed"] };
  const KIND = { start: "play", plan: "route", review: "check" };
  function observe() {
    const o = d.observe; if (!o) return "";
    const on = o.mode === "observe";
    const rate = o.rate == null ? "–" : `${fmtNum(o.rate * 100, 0)}%`;
    const rows = o.entries.slice(0, 12).map(x => { const out = x.outcome ? OUT[x.outcome] || ["none", x.outcome] : ["wait", "Open"];
      return `<li><span class="mal-ob">${icon(KIND[x.kind] || "eye")}${x.task_id ? `<button type="button" class="linkbtn" data-mwtask="${x.task_id}">${esc(x.text)}</button>` : esc(x.text)}
        <span class="faint small">${ago(x.ts)}</span></span><span class="hq-chip t-${out[0]}">${esc(out[1])}</span></li>`; }).join("");
    return `<section class="mh-card mal-card mal-wide mal-obs"><div class="mal-head"><div><h3>${icon("eye")}Autopilot mode</h3>
        <p class="faint small">${on ? "Observe only: autopilot logs what it would start, plan and send to review, and starts nothing. Each entry is checked against what you did; when you agree with it often enough, let it act."
          : "Autopilot starts work on its own. Switch to observe only to see what it would do first, without it starting anything."}${d.autopilot ? "" : " Autopilot is off for this team: switch it on in Team settings for either mode to run."}</p></div>
        <div class="mal-seg" role="group" aria-label="Autopilot mode">
          <button type="button" class="btn sm ${on ? "" : "primary"}" data-mal="mode" data-mode="act" aria-pressed="${!on}">Act</button>
          <button type="button" class="btn sm ${on ? "primary" : ""}" data-mal="mode" data-mode="observe" aria-pressed="${on}">Observe only</button></div></div>
      ${o.entries.length ? `<div class="mal-nums">
          <span class="mal-key"><b>${rate}</b>agreement, 7 days</span><span><b>${o.agreed}</b>you did too</span>
          <span><b>${o.differed}</b>you didn't (in a day)</span><span><b>${o.open}</b>open</span></div>
        <ul class="mal-list mal-oblist">${rows}</ul>` : on ? `<p class="faint small">Nothing logged yet: entries appear when autopilot would have started or planned something (it checks every 15 s).</p>` : ""}</section>`;
  }

  // ---------- suggestions, rules and the policy ----------
  function advice() {
    if (!d.advice.length) return "";
    const btn = a => { const k = a.act?.kind;
      return k === "parallel" ? `<button type="button" class="btn sm" data-mal="parallel" data-n="${a.act.value}">Let ${a.act.value} work at once</button>`
        : k === "edit" ? `<button type="button" class="btn sm" data-mw="edit">Team settings</button>`
        : k === "spread" ? `<button type="button" class="btn sm" data-mal="spread" data-agent="${a.act.agent}">Spread the queue</button>`
        : k === "agent" ? `<button type="button" class="btn sm" data-mwsub="team">Open the team</button>`
        : k === "errors" ? `<button type="button" class="btn sm" data-mst="errors">See the errors</button>`
        : k === "policy" ? `<button type="button" class="btn sm" data-mal="policy">Edit the rules</button>` : ""; };
    return `<section class="mh-card mal-card mal-wide"><h3>${icon("bulb")}Optimize</h3>
      <ul class="ms-blockers">${d.advice.map(a => `<li class="l-${a.level}"><span class="ms-bi">${icon(a.level === "warn" ? "alert" : "info")}</span>
        <span><b>${esc(a.title)}</b><span class="faint">${esc(a.detail)}</span></span>${btn(a)}</li>`).join("")}</ul></section>`;
  }
  function rules() {
    const p = d.policy;
    const num = (k, label, hint, opts = {}) => `<label class="in"><span>${label} <em class="opt">${hint}</em></span>
      <input name="${k}" type="number" min="0" ${opts.max ? `max="${opts.max}"` : ""} step="${opts.step || 1}" value="${opts.auto ? "" : p[k] ?? ""}" placeholder="${opts.auto ? `auto: ${p[k]}` : ""}"></label>`;
    return `<section class="mh-card mal-card mal-wide"><h3>${icon("flag")}Rules in force</h3>
      <ul class="mal-rules">${d.rules.map(r => `<li class="${r.on ? "on" : "off"}"><span class="mal-ci">${icon(r.on ? "check" : "minus")}</span><span><b>${esc(r.text)}</b><span class="faint">${esc(r.detail)}</span></span>
        ${r.go ? `<button type="button" class="linkbtn" data-mwsub="${r.go}">Open</button>` : ""}</li>`).join("")}</ul>
      <details class="mal-pol" id="mal-pol" ${polOpen ? "open" : ""}><summary>${icon("sliders")}Change the limits</summary>
        <form class="mal-policy" data-malform="policy">
          <div class="mal-grid">
            ${num("reserve", "Reserve", "% of the day kept for reviews", { max: 50, step: 1 })}
            ${num("retries", "Retries", "of a passing failure", { max: 5 })}
            ${num("task_cap", "Per-task cap", "tokens; 0 = none, empty = auto", { auto: p.task_cap_auto, step: 1000 })}
            ${num("total_cap", "Competition cap", "tokens over its life; 0 = none", { step: 100000 })}
            ${num("queue_cap", "Queue cap", "tasks queued at once; 0 = no cap, empty = auto", { auto: p.queue_cap_auto, max: 400 })}
            ${num("backlog_cap", "Backlog cap", "open tasks that hold the plan; 0 = no cap, empty = auto", { auto: p.backlog_cap_auto, max: 400 })}</div>
          <div class="row"><button type="submit" class="btn primary sm">Save the limits</button><span class="faint small">The daily budget and how many work at once are in Team settings.</span></div></form></details></section>`;
  }

  function view(v) {
    need(v);
    if (!d) return failed ? `<p class="mh-err">${icon("alert")}${esc(failed)}</p>` : Loading.line("Reading the Autoloop…");
    return `<div class="mal">${cycle()}<div class="mal-grid2">${observe()}${governor()}${queue()}${failures()}${economics()}${advice()}${rules()}</div></div>`;
  }

  async function act(b) {
    const v = MiningWork.view(); if (!v) return;
    const k = b.dataset.mal, wid = v.comp.id;
    if (k === "policy") { const p = $("#mal-pol"); if (p) { p.open = true; p.scrollIntoView({ behavior: "smooth", block: "center" }); } return; }
    b.disabled = true;
    try {
      if (k === "spread") { d = await api(`${W}/comps/${wid}/autoloop/spread`, { method: "POST", body: { agent: +b.dataset.agent } }); Auth.toast("Queue spread over the squad"); MiningWork.reload(); }
      else if (k === "mode") { d = await api(`${W}/comps/${wid}/autoloop/mode`, { method: "PUT", body: { mode: b.dataset.mode } });
        Auth.toast(b.dataset.mode === "observe" ? "Autopilot observes: it starts nothing" : "Autopilot acts on its own"); MiningWork.reload(); }
      else if (k === "cool") { d = await api(`${W}/comps/${wid}/autoloop/cooldown/clear`, { method: "POST" }); Auth.toast("Cooldown ended"); }
      else if (k === "parallel") { MiningWork.apply(await api(`${W}/comps/${wid}`, { method: "PATCH", body: { parallel: +b.dataset.n } })); dAt = 0; Auth.toast(`${b.dataset.n} work at once`); }
      else if (k === "drop") {
        const t = v.tasks.find(x => x.id === +b.dataset.id);
        return UI.confirm({ title: "Delete this copy?", body: `“${esc(t?.title || "The task")}” looks like another open task. It goes, with its result and runs. This can't be undone.`, ok: "Delete",
          run: async () => { await api(`${W}/tasks/${b.dataset.id}`, { method: "DELETE" }); dAt = 0; Auth.toast("Deleted"); MiningWork.reload(); } }).catch(err);
      }
      dAt = Date.now(); MiningWork.rerender();
    } catch (e) { err(e); } finally { if (b.isConnected) b.disabled = false; }
  }
  async function save(f) {
    const v = MiningWork.view(); if (!v) return;
    const body = {};
    for (const k of ["reserve", "retries", "task_cap", "total_cap", "queue_cap", "backlog_cap"]) {
      const x = f.elements[k].value.trim();
      body[k] = x === "" ? null : +x;  // empty: the automatic value
    }
    try { d = await api(`${W}/comps/${v.comp.id}/autoloop/policy`, { method: "PUT", body }); dAt = Date.now(); document.activeElement?.blur(); Auth.toast("Limits saved"); MiningWork.rerender(); }
    catch (e) { err(e); }
  }

  function wire(el) {
    if (wired) return; wired = true;
    el.addEventListener("click", e => { const b = e.target.closest("[data-mal]"); if (b) act(b); });
    el.addEventListener("toggle", e => { if (e.target.id === "mal-pol") polOpen = e.target.open; }, true);
    el.addEventListener("submit", e => { const f = e.target.closest("[data-malform]"); if (f) { e.preventDefault(); save(f); } });
  }
  const fresh = () => { dAt = 0; };
  return { view, wire, holding, fresh };
})();
