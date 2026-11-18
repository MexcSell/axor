/* Model routing and journeys in the Control Hub (control_journey.py: /api/control/routing, /journeys, /journey/{ref}). Prefix ctlj-.
   - routingSec(): the Overview area's "Model routing" tab: pool health, what each kind of work ran on last and why, what the
     router would pick now, fallbacks, each model's record and the latest decisions with their candidates.
   - journeysSec(): the Live operations area's "Journeys" tab: work in flight, each with its steps as dots; a row opens its journey.
   - strip(el, ref): one task's or mission's journey from where it started to where it is now (the task dialog uses it).
   - open(ref): the same in a dialog of its own (Mission Control rows, the Journeys tab), refreshed while it's open.
   control.js draws the hub synchronously, so each section renders from its last answer and refreshes in the background. */
const CtlJourney = (() => {
  const B = "/api/control";
  const SRC = { routed: ["clear", "Routed"], picked: ["new", "Picked"], fallback: ["caution", "Fell back"], no_pool: ["muted", "Default model"] };
  const SRC_ABOUT = { routed: "The router chose it from your model pool", picked: "Someone picked this model for the work, so it wasn't routed",
                      fallback: "The router's pick wasn't available, so the default model ran", no_pool: "No usable model pool, so the default model ran" };
  const STEP = { done: ["check", "Done"], current: ["play", "Under way"], waiting: ["hand", "Waiting"], failed: ["alert", "Failed"], pending: ["", "Not yet"], skipped: ["minus", "Skipped"] };
  const BADGED = new Set(["done", "running", "failed", "lost", "stopped", "cancelled", "error", "todo", "queued", "working", "review", "checking"]);  // run and board states; mission event kinds aren't shown as one
  const RUNST = { done: "clear", running: "new", failed: "scam", lost: "scam", stopped: "muted", cancelled: "muted" };
  const cache = { routing: null, journeys: null }, busy = {}, at = {};
  const sel = {};  // ref → the step shown in detail
  let dlgRef = null, dlgTimer = null;

  const badge = (tone, text, title = "") => `<span class="badge ${tone}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</span>`;
  const tok = n => n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(n);
  const usd = n => n == null ? "–" : n === 0 ? "$0" : n < 0.01 ? "<$0.01" : `$${n.toFixed(2)}`;
  const secs = s => s == null ? "–" : s < 60 ? `${s.toFixed(s < 10 ? 1 : 0)} s` : `${Math.round(s / 60)} min`;
  const when = ts => ts ? ago(ts) : "";
  const short = m => String(m || "").split(":").slice(1).join(":") || String(m || "");
  const mdl = m => m ? `<code class="ctlj-model" title="${esc(m)}">${esc(short(m))}</code>` : `<span class="faint">–</span>`;
  const src = s => s && SRC[s] ? badge(SRC[s][0], SRC[s][1], SRC_ABOUT[s]) : `<span class="faint small">not recorded</span>`;
  const pct = x => x == null ? "–" : `${Math.round(x * 100)}%`;

  async function load(key, path, then) {
    if (busy[key]) return;
    busy[key] = true;
    try { cache[key] = await api(path); at[key] = Date.now(); then?.(); }
    catch (e) { cache[key] = { error: e.message }; then?.(); }
    finally { busy[key] = false; }
  }
  function refreshInto(key, path, id, draw) {
    if (!busy[key] && (!cache[key] || Date.now() - (at[key] || 0) > 15000))
      load(key, path, () => { const el = document.getElementById(id); if (el) el.innerHTML = draw(); });
  }

  // ---------- Model routing ----------
  function routingSec() {
    refreshInto("routing", `${B}/routing`, "ctlj-routing", routingHtml);
    return `<div id="ctlj-routing" class="ctlj">${routingHtml()}</div>`;
  }
  function routingHtml() {
    const d = cache.routing;
    if (!d) return `<p class="ctlj-wait faint">${icon("cycle")}Reading the router…</p>`;
    if (d.error) return `<p class="ctl-warn">${icon("alert")}${esc(d.error)}</p>`;
    const c = d.counts, total = Object.values(c).reduce((a, b) => a + b, 0) + d.unrecorded;
    const w = d.weights_about;
    const tiles = [
      ["chips", "Usable pool models", d.pool_size ? `${d.usable} of ${d.pool_size}` : "No pool", d.pool_size ? (d.usable === d.pool_size ? "every model can run" : `${d.pool_size - d.usable} can't run now`) : "every Auto run uses the default model", d.pool_size && d.usable < d.pool_size ? "warn" : ""],
      ["swap", "Routed (24h)", c.routed, total ? `${pct(c.routed / total)} of ${total} runs` : "no runs today", ""],
      ["alert", "Fell back (24h)", c.fallback, c.fallback ? "the pick wasn't available" : "none", c.fallback ? "warn" : ""],
      ["sliders", "Weights", d.weights, `quality ${w.quality} · cost ${w.cost} · time ${w.time} · failures ${w.failures}`, "cap"]];
    return `<div class="ctlj-tiles">${tiles.map(([ic, l, v, sub, tone]) => `<div class="ctlj-tile ${tone}">${icon(ic)}<span><small>${esc(l)}</small><b>${esc(String(v))}</b><em>${esc(sub)}</em></span></div>`).join("")}</div>
      ${d.fallbacks.length ? `<section class="card ctl-card ctlj-alert"><div class="ctl-h"><h3>${icon("alert")}Fallbacks in the last 24 hours</h3></div>
        <ul class="ctl-list">${d.fallbacks.map(x => `<li><span><b>${esc(x.label)} · ${esc(x.kind)}</b><small>${esc(x.decision?.from ? short(x.decision.from) : "?")} → ${esc(short(x.model))} · ${esc(when(x.started))} · ${esc(x.decision?.reason || "")}</small></span></li>`).join("")}</ul></section>` : ""}
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("chips")}Model pool, now</h3><span class="faint small">Runs, failures and spend over the last 7 days</span>
        <button type="button" class="linkbtn ctlj-right" data-goview="workforce" title="The pool and weights are edited on Workforce → Settings">Edit the pool</button></div>
        ${d.pool.length ? `<div class="ctl-tw-wrap"><table class="ctl-table ctlj-pool"><thead><tr><th>Model</th><th>Can run</th><th>Runs</th><th>Failed</th><th>Avg time</th><th>Tokens</th><th>Cost</th><th>Score</th><th>Last used</th></tr></thead><tbody>
          ${d.pool.map(p => `<tr class="${p.in_pool ? "" : "ctlj-off"}"><td>${mdl(p.model)} <span class="faint small">tier ${p.tier}${p.in_pool ? "" : " · not in the pool"}</span></td>
            <td>${!p.in_pool ? `<span class="faint small">${p.model === "auto" ? "" : "used directly"}</span>` : p.usable ? badge("clear", "Yes") : badge(p.connected ? "caution" : "scam", p.connected ? "Not for you" : "Not connected", p.why)}${p.in_pool && !p.usable && p.why ? `<small class="ctlj-why">${esc(p.why)}</small>` : ""}</td>
            <td>${p.runs}${p.running ? ` <span class="faint small">(${p.running} now)</span>` : ""}</td><td>${p.runs ? `${p.failed} <span class="faint small">${pct(p.fail_rate)}</span>` : "–"}</td>
            <td>${secs(p.latency)}</td><td>${tok(p.tokens)}</td><td>${usd(p.cost)}</td><td>${p.score != null ? `${p.score} <span class="faint small">(${p.scored})</span>` : "–"}</td><td>${esc(when(p.last)) || "–"}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="faint">No model pool and nothing ran in the last 7 days. Without a pool, every Auto run uses the default model; add models in Workforce → Settings → Model pool to let the router choose.</p>`}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("route")}What each kind of work runs on</h3><span class="faint small">Last run and why · what the router would pick now</span></div>
        ${d.lanes.length ? `<div class="ctl-tw-wrap"><table class="ctl-table ctlj-lanes"><thead><tr><th>Work</th><th>Last ran on</th><th>Why</th><th>If it routed now</th></tr></thead><tbody>
          ${d.lanes.map(l => `<tr><td><b>${esc(l.label)}</b> <span class="faint">· ${esc(l.kind)}</span><small class="ctlj-sub">${l.runs} run${l.runs === 1 ? "" : "s"} in 30 days</small></td>
            <td>${mdl(l.last.model)} ${src(l.last.source)}<small class="ctlj-sub">${esc(when(l.last.started))}</small></td>
            <td class="ctlj-reason">${esc(l.last.decision?.reason || "")}</td>
            <td>${l.now ? (l.now.model ? `${mdl(l.now.model)} ${l.now.changed ? badge("caution", "Would change", l.now.reason) : badge("muted", "Same", l.now.reason)}${l.now.estimate ? `<small class="ctlj-sub">estimate</small>` : ""}` : `<small class="faint">${esc(l.now.reason)}</small>`) : `<small class="faint">${l.last.source === "picked" ? "Picked, not routed" : "No usable pool"}</small>`}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="faint">No routing decision is recorded yet. They're kept from now on, with every agent run that picks a model.</p>`}</section>
      <section class="card ctl-card"><div class="ctl-h"><h3>${icon("list")}Latest decisions</h3><span class="faint small">Open one for the candidates the router weighed</span></div>
        ${d.recent.length ? `<div class="ctlj-recent">${d.recent.map(decisionRow).join("")}</div>` : `<p class="faint">None yet.</p>`}</section>`;
  }
  function decisionRow(x) {
    return `<details class="ctlj-dec"><summary><span class="ctlj-dec-main"><b>${esc(x.title || `${x.label} · ${x.kind}`)}</b><small>${esc(x.label)} · ${esc(x.kind)} · ${esc(when(x.started))}</small></span>
      <span class="ctlj-dec-side">${mdl(x.model)} ${src(x.source)} ${badge(RUNST[x.status] || "muted", x.status)}</span></summary>${decisionBody(x)}</details>`;
  }
  function decisionBody(x) {
    const d = x.decision || {};
    const cands = d.candidates || [];
    return `<div class="ctlj-decbody"><p>${esc(d.reason || SRC_ABOUT[x.source] || "")}</p>
      ${d.from ? `<p class="small">The router picked ${mdl(d.from)}, which couldn't run.</p>` : ""}
      ${cands.length ? `<div class="ctl-tw-wrap"><table class="ctl-table ctlj-cands"><thead><tr><th>Candidate</th><th>Score</th><th>Quality</th><th>Cost a call</th><th>Time</th><th>Failures</th><th>Runs</th></tr></thead><tbody>
        ${cands.map((c, i) => `<tr class="${i === 0 ? "ctlj-win" : ""}"><td>${mdl(c.model)}${i === 0 ? ` ${badge("clear", "Chosen")}` : ""}</td><td>${c.score != null ? c.score.toFixed(3) : "–"}</td><td>${c.quality != null ? Math.round(c.quality) : "–"}${c.scored ? ` <span class="faint small">(${c.scored} scored)</span>` : ""}</td>
          <td>${c.cost != null ? `$${c.cost.toFixed(4)}` : "–"}</td><td>${secs(c.latency)}</td><td>${c.risk != null ? pct(c.risk) : "–"}</td><td>${c.runs ?? "–"}</td></tr>`).join("")}</tbody></table></div>` : ""}
      ${x.tokens || x.secs ? `<p class="faint small">${tok(x.tokens)} tokens · ${secs(x.secs)}</p>` : ""}</div>`;
  }

  // ---------- Journeys ----------
  function journeysSec() {
    refreshInto("journeys", `${B}/journeys`, "ctlj-journeys", journeysHtml);
    return `<div id="ctlj-journeys" class="ctlj">${journeysHtml()}</div>`;
  }
  function journeysHtml() {
    const d = cache.journeys;
    if (!d) return `<p class="ctlj-wait faint">${icon("cycle")}Tracing the work…</p>`;
    if (d.error) return `<p class="ctl-warn">${icon("alert")}${esc(d.error)}</p>`;
    const KIND = { agent: "Agent run", board: "Team board", mission: "Mission Control" };
    return `<section class="card ctl-card"><div class="ctl-h"><h3>${icon("route")}Work in flight</h3><span class="faint small">Control Hub tasks and missions, in progress or finished in the last two days. Open one to follow it from where it started.</span></div>
      ${d.items.length ? `<ul class="ctlj-items">${d.items.map(x => `<li><button type="button" class="ctlj-item" data-ctlj-open="${esc(x.ref)}">
        <span class="ctlj-item-main"><b>${esc(x.title)}</b><small>${esc(x.kind === "mission" ? "Mission" : KIND[x.route] || "Task")}${x.unit ? ` · ${esc(x.unit)}` : ""} · ${esc(when(x.updated))}</small></span>
        <span class="ctlj-mini" aria-label="${x.done} of ${x.total} steps done">${x.dots.map(s => `<i class="ctlj-d s-${esc(s)}"></i>`).join("")}</span>
        <span class="ctlj-item-now"><span class="ctlj-now-l s-${esc(x.step_status || "pending")}">${esc(x.step || x.label)}</span><small>${esc(x.waiting_on ? `Waiting on ${x.waiting_on}` : x.label)}</small></span></button></li>`).join("")}</ul>`
        : `<p class="faint">Nothing in flight. A task (Tasks tab) or a custom mission (Mission Control) shows up here with each step it goes through.</p>`}</section>`;
  }

  // ---------- one journey ----------
  async function strip(el, ref) {
    if (!el) return;
    if (!el.innerHTML) el.innerHTML = `<p class="ctlj-wait faint">${icon("cycle")}Tracing it…</p>`;
    try { const j = await api(`${B}/journey/${encodeURIComponent(ref)}`); el.innerHTML = journeyHtml(j); el._j = j; wireStrip(el); }
    catch (e) { el.innerHTML = `<p class="ctl-warn">${icon("alert")}${esc(e.message)}</p>`; }
  }
  function journeyHtml(j) {
    const now = j.now || {};
    const pick = sel[j.ref] && j.steps.some(s => s.key === sel[j.ref]) ? sel[j.ref] : now.step || j.steps[0]?.key;
    const tone = { waiting: "warn", failed: "crit", current: "busy" }[(j.steps.find(s => s.key === now.step) || {}).status] || ((now.done === now.total) ? "done" : "");
    return `<div class="ctlj-j">
      <div class="ctlj-nowbar ${tone}">${icon(tone === "warn" ? "hand" : tone === "crit" ? "alert" : tone === "done" ? "check" : "radio")}
        <span><b>${esc(now.label || "")}</b>${now.text ? ` · ${esc(now.text)}` : ""}${now.waiting_on ? `<small>Waiting on ${esc(now.waiting_on)}</small>` : ""}</span>
        <em>${now.done} of ${now.total} steps${now.spent != null && now.budget ? ` · $${(+now.spent).toFixed(2)} of $${(+now.budget).toFixed(2)}` : ""}</em></div>
      <ol class="ctlj-steps" role="list">${j.steps.map((s, i) => `<li class="ctlj-step s-${esc(s.status)} ${s.key === pick ? "on" : ""} ${s.key === now.step ? "now" : ""}">
        <button type="button" data-ctlj-step="${esc(s.key)}" aria-pressed="${s.key === pick}" title="${esc(`${s.label}: ${STEP[s.status]?.[1] || s.status}${s.about ? ` · ${s.about}` : ""}`)}">
          <span class="ctlj-node">${STEP[s.status]?.[0] ? icon(STEP[s.status][0]) : `<i>${i + 1}</i>`}</span>
          <span class="ctlj-lab"><b>${esc(s.label)}</b><small>${esc(s.status === "pending" ? "Not yet" : s.ts ? when(s.ts) : STEP[s.status]?.[1] || "")}</small></span></button></li>`).join("")}</ol>
      <div class="ctlj-detail">${stepDetail(j.steps.find(s => s.key === pick))}</div></div>`;
  }
  function stepDetail(s) {
    if (!s) return "";
    const st = STEP[s.status] || ["", s.status];
    return `<div class="ctlj-dh"><h4>${esc(s.label)}</h4>${badge({ done: "clear", current: "new", waiting: "caution", failed: "scam" }[s.status] || "muted", st[1])}
        ${s.who ? `<span class="faint small">${icon("users")}${esc(s.who)}</span>` : ""}${s.ts ? `<span class="faint small">${icon("clock")}${esc(new Date(s.ts * 1000).toLocaleString())}</span>` : ""}</div>
      ${s.about && s.about !== s.text ? `<p class="faint small">${esc(s.about)}</p>` : ""}
      ${s.text ? `<p>${esc(s.text)}</p>` : ""}${s.note ? `<p class="ctlj-note">${icon("info")}${esc(s.note)}</p>` : ""}
      ${s.runs.length ? `<h5>Model runs <span class="faint small">· which model each ran on, and why</span></h5><div class="ctlj-recent">${s.runs.map(decisionRow).join("")}</div>` : ""}
      ${s.items.length ? `<h5>What happened</h5><ul class="ctlj-log">${s.items.map(x => `<li><time>${esc(when(x.ts))}</time><span>${esc(x.label)}${x.by ? ` <span class="faint">· ${esc(x.by)}</span>` : ""}${x.error ? `<small class="ctlj-err">${esc(x.error)}</small>` : ""}</span>${BADGED.has(x.status) ? badge(RUNST[x.status] || "muted", x.status) : ""}</li>`).join("")}</ul>` : ""}
      ${!s.text && !s.note && !s.runs.length && !s.items.length ? `<p class="faint">${s.status === "pending" ? "It hasn't got here yet." : "Nothing recorded for this step."}</p>` : ""}`;
  }
  function wireStrip(el) {
    el.querySelectorAll("[data-ctlj-step]").forEach(b => b.onclick = () => {
      const j = el._j; if (!j) return;
      sel[j.ref] = b.dataset.ctljStep;
      el.querySelectorAll(".ctlj-step").forEach(li => { const on = li.querySelector("button").dataset.ctljStep === sel[j.ref]; li.classList.toggle("on", on); li.querySelector("button").setAttribute("aria-pressed", on); });
      el.querySelector(".ctlj-detail").innerHTML = stepDetail(j.steps.find(s => s.key === sel[j.ref]));
    });
  }

  function open(ref) {
    let d = document.getElementById("ctlj-dlg");
    if (!d) { d = document.createElement("dialog"); d.id = "ctlj-dlg"; d.className = "modal ctl-dlg wide ctlj-dlg"; document.body.append(d); }
    dlgRef = ref;
    const mission = ref.startsWith("mx:");
    d.innerHTML = `<div class="ctl-h"><h3>${icon("route")}<span class="ctlj-dt">Journey</span></h3>
        <span class="ctlj-right">${mission && typeof setView === "function" ? `<button type="button" class="btn sm" data-ctlj-mos>${icon("external")}Mission Control</button>` : ""}
        <button type="button" class="iconbtn" data-ctlj-close aria-label="Close">${icon("close")}</button></span></div>
      <div class="ctlj-body"></div>`;
    d.querySelector("[data-ctlj-close]").onclick = () => d.close();
    d.querySelector("[data-ctlj-mos]")?.addEventListener("click", () => { d.close(); setView("mos"); });
    d.onclose = () => { clearInterval(dlgTimer); dlgRef = null; };
    if (!d.open) d.showModal();
    const body = d.querySelector(".ctlj-body");
    const fill = async () => { await strip(body, ref); if (body._j) d.querySelector(".ctlj-dt").textContent = body._j.title; };
    fill();
    clearInterval(dlgTimer); dlgTimer = setInterval(() => { if (dlgRef === ref && !document.hidden) fill(); }, 10000);
  }

  document.addEventListener("click", e => {
    const o = e.target.closest?.("[data-ctlj-open]"); if (o) { e.preventDefault(); open(o.dataset.ctljOpen); }
  });

  return { routingSec, journeysSec, strip, open, reset: () => { at.routing = at.journeys = 0; } };
})();
