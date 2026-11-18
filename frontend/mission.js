/* Mission Control (missions.py), AXoR 3.0's Simple Mode, goal first: describe the goal, attach any documents, pictures and links
   (GitHub repositories too), and start. AXoR picks the engine, the models, the budget (missions.AUTO_BUDGET) and the timing; Advanced
   mode keeps those as optional overrides under "Fine-tune". The page answers what AXoR is doing, the current objective, progress, time and money used, what's blocked,
   what needs you and what's been delivered; one mission opens with its lifecycle, plan, spend, timeline, verification and report.
   Simple and Advanced mode: a body attribute (data-axmode) the sidebar's CSS reads; Advanced shows the whole app as before. */
const MissionOS = (() => {
  let home = null, sel = null, d = null, wired = false, timer = null, busy = false, extra = false;
  let mineOpen = false;  // Simple mode: the folded "Your missions" list is open
  let prefill = null;  // {id, label, netuid}: My subnets' "Start mission" on a team (mission-team.js)
  let atts = [], links = [], fixedBudget = null;  // the composer's attached files (staged uploads), links, and a budget a draft set (Intelligence layers)
  const root = () => $("#mos");
  const shown = () => !$("#view-mos").hidden;
  const err = e => e && Auth.toast(e.message);
  const money = x => `$${(x || 0) < 10 ? (x || 0).toFixed(2) : fmtNum(x || 0, 0)}`;
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 1)}k` : fmtNum(n || 0, 0);
  const dur = s => s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : s < 172800 ? `${fmtNum(s / 3600, 1)} h` : `${fmtNum(s / 86400, 1)} days`;
  const when = ts => new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  const STAGE = { understand: "Understand", discover: "Discover", plan: "Plan", allocate: "Allocate", execute: "Execute", verify: "Verify", deliver: "Deliver", learn: "Learn" };
  const STATUS = { queued: ["run", "Starting"], running: ["run", "Working"], needs_input: ["wait", "Needs you"], paused: ["warn", "Paused"],
    delivered: ["ok", "Delivered"], failed: ["bad", "Stopped"], cancelled: ["off", "Cancelled"] };
  const OUTCOME = { verified: ["ok", "Verified", "check"], partial: ["warn", "Partly done", "hand"], failed: ["bad", "Not achieved", "alert"],
    unverified: ["off", "Not verifiable", "info"] };
  const CRIT = { met: ["ok", "Met"], partly: ["warn", "Partly"], not_met: ["bad", "Not met"], unverifiable: ["off", "Can't check"] };
  // D-004 D4.2: a persistent mission's measures. Only valid external evidence can pass the competition outcome; the rest is UNKNOWN.
  const DIM = { PASS: ["ok", "PASS"], FAIL: ["bad", "FAIL"], UNKNOWN: ["off", "UNKNOWN"], "n/a": ["off", "n/a"] };
  // D-004 D4.3: a persistent mission's cycles. One decision per cycle by fixed rules; effects only record, request or advise.
  const DEC = { criteria_met: ["ok", "Criteria met"], ended: ["warn", "Ended"], request: ["wait", "Needs you"], correct: ["bad", "Correct"],
    replan_advice: ["warn", "Replan advice"], continue: ["off", "Continue"] };
  const EVST = { valid: "Valid", stale: "Stale", unverifiable: "Unverifiable", conflicting: "Conflicting", missing: "Missing", self_reported: "Self-reported" };
  const ENGINE_ICON = { direct: "zap", workforce: "group", longtask: "route", mining: "trophy", swarm: "sparkle" };
  const DEADLINES = [["", "None: AXoR estimates the time"], ["3600", "1 hour"], ["28800", "Today (8 h)"], ["86400", "1 day"], ["259200", "3 days"], ["604800", "7 days"], ["custom", "Pick a date…"]];
  const EXAMPLES = ["Compare the five subnets with the highest emissions for a new miner and recommend one, with the risks",
    "Write a one-page plan to cut my agents' model costs by 30% without losing quality",
    "Research how top miners on my competition score and list the three changes most likely to raise my rank"];
  const chip = (tone, text, ic) => `<span class="mx-chip t-${tone}">${ic ? icon(ic) : ""}${esc(text)}</span>`;
  const active = m => ["queued", "running", "needs_input", "paused"].includes(m.status);

  // ---------- Simple / Advanced ----------
  // accounts that aren't administrators have one mode: Simple, with the sidebar from the User list (side-layout.js) and no switch
  const admin = () => Auth.me()?.role === "admin";
  const mode = () => { if (Auth.me() && !admin()) return "simple"; try { return localStorage.getItem("axor.mode") === "advanced" ? "advanced" : "simple"; } catch { return "simple"; } };
  function applyMode() {
    const m = mode();
    if (Auth.me()) document.body.dataset.axmode = m; else delete document.body.dataset.axmode;  // signed out: the public pages stay as they are
    $$(".mx-mode [data-axmode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.axmode === m)));
  }
  function setMode(m) {
    try { localStorage.setItem("axor.mode", m); } catch { /* private window: the mode lasts this visit */ }
    applyMode();
    if (m === "simple" && !["mos", "approvals", "notifications", "help", "mining", "teams", "control"].includes(S.view)) setView("mos");
    if (shown()) render();
  }
  const landing = () => mode() === "simple" && Auth.me() ? "mos" : "command";
  function init() {
    const seg = $("#mx-mode");
    if (seg && !seg.dataset.wired) {
      seg.dataset.wired = "1"; seg.hidden = !admin();
      // phones have no room in the top bar: the same switch sits at the foot of the sidebar instead (mission.css)
      const foot = $("#side .side-foot");
      if (foot && admin()) {
        const side = seg.cloneNode(true);
        side.id = ""; side.hidden = false; side.classList.add("mx-side-mode");
        foot.before(side);
      }
      $$(".mx-mode").forEach(s => s.addEventListener("click", e => { const b = e.target.closest("[data-axmode]"); if (b) { setMode(b.dataset.axmode); if (s.classList.contains("mx-side-mode")) sideOpen(false); } }));
    }
    applyMode();
  }

  // ---------- loading ----------
  async function open() {
    wire();
    if (!home) root().innerHTML = `${head()}${Loading.line("Loading your missions…")}`;
    try { home = await api("/api/mos"); }
    catch (e) {
      root().innerHTML = `${head()}<div class="empty">${esc(e.message)}${mode() === "simple" ? `<p><button type="button" class="btn" data-mx="advanced">Switch to Advanced mode</button></p>` : ""}</div>`;
      return;
    }
    if (sel != null) await loadOne();
    render(); schedule();
  }
  async function loadOne() {
    try { d = await api(`/api/mos/missions/${sel}`); }
    catch { sel = null; d = null; }
  }
  function stop() { clearTimeout(timer); timer = null; }
  function schedule() {
    clearTimeout(timer);
    if (!shown()) return;
    const live = (home?.missions || []).some(m => ["queued", "running"].includes(m.status));
    timer = setTimeout(refresh, live ? 4000 : 20000);
  }
  async function refresh() {
    if (!shown()) return;
    if (busy || root().contains(document.activeElement) && document.activeElement.matches("textarea, input, select")) return schedule();  // don't redraw under typing
    try { home = await api("/api/mos"); if (sel != null) await loadOne(); render(); } catch { /* a missed beat: the next one catches up */ }
    schedule();
  }
  async function act(path, opts = {}, ok = "") {
    busy = true;
    try {
      const r = await api(path, { method: "POST", ...opts });
      if (r.mission) { d = r; sel = r.mission.id; }
      if (ok) Auth.toast(ok);
      home = await api("/api/mos");
      render(); schedule();
      return r;
    } catch (e) { err(e); } finally { busy = false; }
  }

  // ---------- drawing ----------
  const head = () => `<header class="mx-head"><div><p class="mx-eyebrow">${icon("target")}Mission Control</p><h1 class="page">What should AXoR do?</h1>
    <p class="lead">Describe the goal, and add any documents, pictures or links it needs. AXoR understands it, researches, plans, picks the agents, models and budget, does the work, checks it independently and delivers a report. It asks only when it must, and never deploys, uploads, pays or touches keys without your approval.</p></div></header>`;

  function render() {
    if (!home) return;
    const keep = keepComposer();
    // Simple mode: only the goal box and Start mission; "Needs you" only when something waits, and the missions folded below
    root().innerHTML = sel != null && d ? detail() : mode() === "advanced" ? `${head()}${answers()}${composer()}${needs()}${CommandMap.slot("home", { toggle: "home" })}${lists()}`
      : `${head()}${composer()}${needs()}${mine()}`;
    restoreComposer(keep);
    hydrateIcons(root());
  }
  // a redraw (the refresh beat, a decision elsewhere on the page) mustn't lose what's being written in the composer
  function keepComposer() {
    const f = root()?.querySelector("[data-mxform=new]");
    if (!f) return null;
    return { values: [...f.elements].filter(e => e.name && e.type !== "file").map(e => [e.name, e.value]), tune: f.querySelector(".mx-tune")?.open,
             link: !f.querySelector(".mx-linkin")?.hidden };
  }
  function restoreComposer(k) {
    const f = root()?.querySelector("[data-mxform=new]");
    if (!k || !f) return;
    for (const [n, v] of k.values) if (f.elements[n] && !(f.elements[n] instanceof RadioNodeList)) f.elements[n].value = v;
    if (k.tune && f.querySelector(".mx-tune")) f.querySelector(".mx-tune").open = true;
    if (k.link) f.querySelector(".mx-linkin").hidden = false;
    if (f.custom && f.deadline) { f.custom.hidden = f.deadline.value !== "custom"; f.custom.required = !f.custom.hidden; }
    detect(f);
  }

  function answers() {
    const ms = home.missions, now = ms.find(m => ["running", "queued"].includes(m.status)), st = home.stats;
    const work = home.work || [], tw = work[0];  // Competition teams at work: their predefined missions (comp:N), the same identity as the Control Hub
    const blocked = ms.filter(m => m.status === "paused"), waiting = ms.filter(m => m.status === "needs_input").length + home.requests.length;
    const last = ms.find(m => m.status === "delivered");
    const cell = (q, a, sub, tone = "") => `<div class="mx-q ${tone}"><span class="mx-qq">${esc(q)}</span><b>${a}</b>${sub ? `<span class="mx-qs">${sub}</span>` : ""}</div>`;
    const prog = now ? `${STAGES_DONE(now)} of 8 stages` : "—";
    return `<section class="mx-answers" aria-label="Where things stand">
      ${cell("What is AXoR doing?", now ? esc(now.doing) : tw ? `${tw.working ? `${tw.working} agent${tw.working === 1 ? "" : "s"} working` : `${tw.busy} task${tw.busy === 1 ? "" : "s"} under way`}` : "Nothing right now",
        now ? esc(now.title) : tw ? `<button type="button" class="linkbtn" data-mxteam="${tw.team}" title="Predefined mission ${esc(tw.ref)}">${esc(tw.title)}</button>${work.length > 1 ? ` + ${work.length - 1} more team${work.length > 2 ? "s" : ""}` : ""}` : "Start a mission below", now || tw ? "t-run" : "")}
      ${cell("Current objective", now ? esc(now.objective || now.goal).slice(0, 140) : tw ? esc(tw.title) : "—", now?.engine ? esc(home.engines[now.engine]) : tw ? "Predefined mission (Bittensor competition)" : "")}
      ${cell("Is it progressing?", prog, now ? `<span class="mx-steps sm">${steps(now)}</span>` : "", now ? "t-run" : "")}
      ${cell("Time and money", `${money(st.spent_active)} of ${money(st.budget_active)}`, `${money(st.week_usd)} this week across missions`)}
      ${cell("Is anything blocked?", blocked.length ? `${blocked.length} paused` : "No", blocked[0] ? esc(blocked[0].doing) : "", blocked.length ? "t-warn" : "")}
      ${cell("Does AXoR need you?", waiting ? `${waiting} waiting` : "No", waiting ? "See “Needs you” below" : "", waiting ? "t-wait" : "")}
      ${cell("What's been delivered?", `${st.delivered} mission${st.delivered === 1 ? "" : "s"}`, last ? `Latest: ${esc(last.title)} · ${esc(OUTCOME[last.outcome]?.[1] || "")}` : `${st.verified} verified`, st.delivered ? "t-ok" : "")}
    </section>`;
  }
  const STAGES_DONE = m => Math.max(0, Object.keys(STAGE).indexOf(m.stage) + (m.status === "delivered" ? 1 : 0));
  function steps(m) {
    const at = Object.keys(STAGE).indexOf(m.stage);
    return Object.entries(STAGE).map(([k, label], i) => {
      const s = m.status === "delivered" || i < at ? "done" : i === at ? (["paused", "failed", "cancelled"].includes(m.status) ? "stuck" : m.status === "needs_input" ? "wait" : "now") : "todo";
      return `<span class="mx-step s-${s}" title="${esc(label)}${s === "now" ? ": now" : ""}"><i></i><em>${esc(label)}</em></span>`;
    }).join("");
  }

  // ---------- the composer: the goal, what it brings along, and (Advanced) optional overrides ----------
  const ATT_ICON = { document: "doc", image: "image" };
  const repoOf = u => { const m = /^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9-]{1,39})\/([A-Za-z0-9._-]{1,100}?)(?:\.git)?(?:[/?#].*)?$/i.exec(u.trim());
    return m && !["orgs", "settings", "marketplace", "topics", "features", "sponsors", "apps", "login", "about", "pricing", "collections", "explore"].includes(m[1].toLowerCase()) ? `${m[1]}/${m[2]}` : null; };
  const urlsIn = t => [...new Set((t.match(/https?:\/\/[^\s<>"'`)\]]+/gi) || []).map(u => u.replace(/[.,;:!?]+$/, "")))];
  function attChips() {
    return [...atts.map((a, i) => `<span class="mx-attc ${a.state === "error" ? "t-bad" : ""}" title="${esc(a.error || a.about || a.name)}">${a.state === "up" ? `<span class="spin" aria-hidden="true"></span>` : icon(ATT_ICON[a.kind] || "file")}
        <span class="mx-attn">${esc(a.name)}</span>${a.state === "error" ? `<em>${esc(a.error)}</em>` : a.kind === "image" ? "<em>read when it starts</em>" : a.chars ? `<em>${short(a.chars)} chars</em>` : ""}
        <button type="button" class="mx-attx" data-mxunatt="${i}" aria-label="Remove ${esc(a.name)}">${icon("close")}</button></span>`),
      ...links.map((u, i) => `<span class="mx-attc" title="${esc(u)}">${icon(repoOf(u) ? "github" : "link")}<span class="mx-attn">${esc(repoOf(u) || u.replace(/^https?:\/\//, ""))}</span>
        <button type="button" class="mx-attx" data-mxunlink="${i}" aria-label="Remove the link">${icon("close")}</button></span>`)].join("");
  }
  function drawAtts(f) {
    const box = f?.querySelector(".mx-att");
    if (!box) return;
    box.innerHTML = attChips(); box.hidden = !atts.length && !links.length;
    hydrateIcons(box);
    detect(f);
  }
  function detect(f) {  // the GitHub repositories the goal or its links name: agents read them, read-only
    const el = f?.querySelector(".mx-detect");
    if (!el) return;
    const repos = [...new Set([...urlsIn(f.goal.value), ...links].map(repoOf).filter(Boolean))];
    el.hidden = !repos.length;
    el.innerHTML = repos.length ? `${icon("github")}<span><b>${repos.map(esc).join(", ")}</b>: AXoR's agents read ${repos.length > 1 ? "these repositories" : "this repository"} (structure, languages, README), read-only.
      A private one must be in <button type="button" class="linkbtn" data-mxview="source">Source control</button>; never paste a token. Pushes and merges always wait for your approval.</span>` : "";
    hydrateIcons(el);
  }
  async function addFiles(f, files) {
    const L = home.limits || {}, max = L.files || 10;
    for (const file of [...files]) {
      if (atts.length >= max) { toast(`At most ${max} files on one mission.`); break; }
      const a = { name: file.name || "pasted.png", kind: /^image\//.test(file.type) ? "image" : "document", state: "up" };
      const cap = (a.kind === "image" ? L.image_mb || 5 : L.file_mb || 20) * 1e6;
      if (file.size > cap) { toast(`${a.name} is too big: ${a.kind === "image" ? "pictures" : "documents"} up to ${cap / 1e6} MB.`); continue; }
      atts.push(a); drawAtts(f);
      try {
        const data = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] || ""); r.onerror = () => no(new Error("The file couldn't be read.")); r.readAsDataURL(file); });
        Object.assign(a, await api("/api/mos/uploads", { method: "POST", body: { filename: a.name, data } }), { state: "ok" });
      } catch (e) { Object.assign(a, { state: "error", error: e.message }); }
      drawAtts(root()?.querySelector("[data-mxform=new]") || f);
    }
  }
  function addLink(f) {
    const inp = f.querySelector("[name=link]"), v = inp.value.trim();
    if (!v) return;
    if (!/^https?:\/\/\S+\.\S+/i.test(v)) return toast("Enter a web address starting with https://");
    if (!links.includes(v)) links.push(v);
    inp.value = ""; drawAtts(f); inp.focus();
  }
  function resetComposer() {
    atts = []; links = []; fixedBudget = null;
  }

  function composer() {
    const adv = mode() === "advanced", av = home.available || {}, L = home.limits || {};
    const teams = prefill ? [...(home.teams || [])].sort((a, b) => (b.id === prefill.id) - (a.id === prefill.id)) : home.teams || [];
    const tmpl = [...teams.slice(0, 2).map(t => `Improve my SN${t.netuid} ${t.label} miner: analyze its current performance, find its weaknesses, research stronger approaches, draft improvements, benchmark them against the baseline and recommend the best candidate. Don't upload anything.`), ...EXAMPLES].slice(0, 4);
    const accept = (L.accept || []).join(",");
    return `<form class="card mx-new" data-mxform="new" autocomplete="off">
      <div class="mx-goalbox" data-mxdrop>
        <label class="in mx-goal"><span>Goal</span><textarea name="goal" rows="4" minlength="12" maxlength="4000" required placeholder="What do you want achieved? Describe it in your own words: what “done” looks like, links, a GitHub repository. Drop documents or pictures here."></textarea></label>
        <div class="mx-att" ${atts.length || links.length ? "" : "hidden"}>${attChips()}</div>
        <div class="mx-attbar">
          <button type="button" class="mx-attb" data-mx="files" title="PDF, Word, PowerPoint, Excel, text, Markdown, CSV, JSON, code (up to ${L.file_mb || 20} MB each)">${icon("doc")}<span>Documents</span></button>
          <button type="button" class="mx-attb" data-mx="pictures" title="PNG, JPEG, GIF, WebP (up to ${L.image_mb || 5} MB each): screenshots, designs, diagrams, charts">${icon("image")}<span>Pictures</span></button>
          <button type="button" class="mx-attb" data-mx="link" title="A web page, a document online or a GitHub repository">${icon("link")}<span>Link</span></button>
          <span class="mx-atthint">Text, documents, pictures and links: all optional</span>
          <input type="file" name="files" multiple hidden accept="${esc(accept)}"><input type="file" name="pictures" multiple hidden accept="image/png,image/jpeg,image/gif,image/webp">
        </div>
        <div class="mx-linkin" hidden><input name="link" type="url" inputmode="url" placeholder="https://… a page, a document or a GitHub repository" aria-label="Link to add"><button type="button" class="btn sm" data-mx="addlink">Add</button></div>
      </div>
      <p class="mx-detect" hidden></p>
      ${prefill && !adv ? `<div class="mx-onteam">${icon("trophy")}<span>Runs on your Competition team <b>SN${esc(prefill.netuid ?? "?")} · ${esc(prefill.label)}</b></span>
        <button type="button" class="linkbtn" data-mx="unteam">Let AXoR decide instead</button></div>` : ""}
      ${fixedBudget && !adv ? `<div class="mx-onteam">${icon("coins")}<span>Budget <b>${money(fixedBudget)}</b>, set by the acceptance test</span>
        <button type="button" class="linkbtn" data-mx="unbudget">Let AXoR decide instead</button></div>` : ""}
      ${adv ? `<div class="mx-tmpl" aria-label="Examples">${tmpl.map((t, i) => `<button type="button" class="mx-tchip" data-mxtmpl="${i}" title="${esc(t)}">${icon(i < teams.length ? "trophy" : "bulb")}<span class="mx-tchipt">${esc(t.length > 64 ? t.slice(0, 62) + "…" : t)}</span></button>`).join("")}</div>` : ""}
      ${adv ? `<details class="mx-tune"${prefill || fixedBudget ? " open" : ""}><summary>Fine-tune <em class="opt">optional: left alone, AXoR decides all of this</em></summary>
        <div class="mx-row">
          <label class="in mx-budget"><span>Budget <em class="opt">hard limit, in dollars</em></span>
            <div class="mx-money"><span>$</span><input name="budget" type="number" min="${L.budget[0]}" max="${L.budget[1]}" step="0.01" placeholder="AXoR decides" value="${fixedBudget ?? ""}"></div>
            <div class="mx-presets">${[1, 5, 20, 100].map(v => `<button type="button" data-mxbudget="${v}">$${v}</button>`).join("")}</div></label>
          <label class="in"><span>Deadline</span><select name="deadline">${DEADLINES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select>
            <input name="custom" type="datetime-local" hidden aria-label="Deadline date and time"></label>
          <label class="in"><span>Engine</span><select name="engine"><option value="">AXoR decides</option>${Object.entries(home.engines).map(([k, l]) => `<option value="${k}"${av[k] ? "" : " disabled"}${prefill && k === "mining" ? " selected" : ""}>${esc(l)}${av[k] ? k === "mining" && !teams.length ? " (AXoR offers to create one)" : "" : " (not available)"}</option>`).join("")}</select></label>
          ${teams.length ? `<label class="in"><span>Competition team</span><select name="team"><option value="">AXoR decides</option>${teams.map(t => `<option value="${t.id}"${prefill?.id === t.id ? " selected" : ""}>SN${t.netuid} · ${esc(t.label)}</option>`).join("")}</select></label>` : ""}
          ${autonomyField(true)}
        </div>
        <label class="in"><span>Your experience <em class="opt">what you know, what you tried, what worked</em></span><textarea name="experience" rows="2" maxlength="6000"></textarea></label>
        <label class="in"><span>Constraints <em class="opt">quality bar, things to avoid, rules</em></span><textarea name="constraints" rows="2" maxlength="3000"></textarea></label>
      </details>` : ""}
      <div class="mx-go">${adv ? `<p class="muted">${icon("shield")}AXoR picks the engine, the models, the budget (up to ${money(L.auto_budget || 20)} without asking you) and the timing. Deploys, uploads, payments and keys never run by themselves.</p>` : ""}
        <button type="submit" class="btn primary">${icon("rocket")}Start mission</button></div>
    </form>`;
  }

  // autonomy per mission (mission_autonomy.py): a level, and in Advanced mode a choice per kind of action
  function autonomyField(adv, cur) {
    const A = home.autonomy; if (!A) return "";
    const lv = cur?.level || A.default, about = A.levels.find(l => l.level === lv)?.about || "";
    return `<label class="in mx-auto"><span>Autonomy <em class="opt">what AXoR may do without asking</em></span>
        <select name="autonomy">${A.levels.map(l => `<option value="${l.level}"${l.level === lv ? " selected" : ""}>${l.level} · ${esc(l.name)}</option>`).join("")}</select>
        <small class="muted mx-auto-about">${esc(about)}</small></label>
      ${adv ? `<details class="mx-auto-kinds"><summary>Per kind of action <em class="opt">Advanced</em></summary>${A.kinds.map(k => `<label class="in"><span>${esc(k.label)}</span>
          <select name="ak_${k.kind}"><option value="">From the level</option>${Object.entries(k.choices).map(([c, l]) => `<option value="${c}"${cur?.[k.kind] === c && cur.custom?.includes(k.kind) ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`).join("")}
        <p class="muted small">${icon("lock")}Deploys, uploads, payments and keys never run by themselves at any level.</p></details>` : ""}`;
  }
  const autonomyOf = f => {
    if (!f.autonomy) return null;
    const a = { level: f.autonomy.value };
    (home.autonomy?.kinds || []).forEach(k => { const v = f[`ak_${k.kind}`]?.value; if (v) a[k.kind] = v; });
    return a;
  };

  function needs() {
    // a mission waiting on a Competition team shows its team request (below), not an empty questions form
    const qs = home.missions.filter(m => m.status === "needs_input" && m.questions?.length && !m.team_request), rq = home.requests;
    if (!qs.length && !rq.length) return "";
    return `<section class="card mx-needs"><h3>${icon("inbox")}Needs you</h3>
      ${qs.map(m => `<form class="mx-ask" data-mxform="answer" data-id="${m.id}"><p><b>${esc(m.title)}</b> can't start without these answers:</p>
        ${m.questions.map((q, i) => `<label class="in"><span>${esc(q)}</span><input name="a${i}" required maxlength="1000" placeholder="Your answer, or “you decide”"></label>`).join("")}
        <div class="mx-acts"><button type="submit" class="btn primary">${icon("send")}Answer and continue</button><button type="button" class="btn" data-mxopen="${m.id}">Open</button></div></form>`).join("")}
      ${rq.map(requestRow).join("")}
    </section>`;
  }
  // a team request: approving creates the team (unlike the others, which AXoR never carries out), or use a team you have, or go on without
  function teamRow(r) {
    const teams = home?.teams || [], at = `data-mxdecide="${r.id}" data-hash="${esc(r.hash)}" data-kind="team"`;
    return `<div class="mx-req mx-teamreq" data-req="${r.id}"><div><span class="mx-kind">${icon("trophy")}Competition team needed</span><p>${esc(r.action)}</p>
        <span class="muted">From “${esc(r.title || "")}” · undecided by ${esc(until(r.expires))}, the mission goes on without a team · bound to <code title="${esc(r.hash)}">${esc(r.hash.slice(0, 12))}</code></span></div>
      <div class="mx-acts"><button type="button" class="btn primary" ${at} data-ok="1">${icon("check")}Create team and continue</button>
        ${teams.length ? `<span class="mx-teamuse"><select data-mxteamsel aria-label="One of your Competition teams">${teams.map(t => `<option value="${t.id}">SN${t.netuid} · ${esc(t.label)}</option>`).join("")}</select>
          <button type="button" class="btn" ${at} data-ok="0" data-team="pick">Use this team</button></span>` : ""}
        <button type="button" class="btn" ${at} data-ok="0">${icon("close")}Go on without a team</button></div></div>`;
  }
  // a plan to approve (or decline with a note: AXoR plans again), or another attempt after a failure (or deliver what's done)
  function gateRow(r) {
    const plan = r.kind === "plan", at = `data-mxdecide="${r.id}" data-hash="${esc(r.hash)}" data-kind="${r.kind}"`;
    return `<div class="mx-req mx-gatereq" data-req="${r.id}"><div><span class="mx-kind">${icon(plan ? "list" : "cycle")}${plan ? "Plan to approve" : "Try again?"}</span><p>${esc(r.action)}</p>
        <span class="muted">From “${esc(r.title || "")}” · undecided by ${esc(until(r.expires))}, the mission pauses · bound to <code title="${esc(r.hash)}">${esc(r.hash.slice(0, 12))}</code></span>
        ${plan ? `<label class="in mx-gatenote"><span>Note if you decline <em class="opt">what to change: AXoR plans again with it</em></span><input data-mxnote maxlength="500"></label>` : ""}</div>
      <div class="mx-acts"><button type="button" class="btn primary" ${at} data-ok="1">${icon(plan ? "check" : "cycle")}${plan ? "Run this plan" : "Try again"}</button>
        <button type="button" class="btn" ${at} data-ok="0">${icon(plan ? "edit" : "check")}${plan ? "Plan again" : "Deliver what's done"}</button></div></div>`;
  }
  const requestRow = r => r.kind === "team" && r.status === "pending" ? teamRow(r) : ["plan", "recover"].includes(r.kind) && r.status === "pending" ? gateRow(r) : `<div class="mx-req" data-req="${r.id}"><div><span class="mx-kind">${icon("shield")}${esc(r.label)}</span><p>${esc(r.action)}</p>
      <span class="muted">From “${esc(r.title || "")}” · expires ${esc(until(r.expires))} · bound to <code title="${esc(r.hash)}">${esc(r.hash.slice(0, 12))}</code></span></div>
    ${r.status === "pending" ? `<div class="mx-acts"><button type="button" class="btn" data-mxdecide="${r.id}" data-ok="1" data-kind="${esc(r.kind)}" data-hash="${esc(r.hash)}">${icon("check")}Approve</button>
      <button type="button" class="btn" data-mxdecide="${r.id}" data-ok="0" data-kind="${esc(r.kind)}" data-hash="${esc(r.hash)}">${icon("close")}Reject</button></div>` : chip(r.status === "approved" ? "ok" : r.status === "rejected" ? "bad" : "off", r.status)}</div>`;

  // a delivered mission with an empty deliverable says so, instead of "Delivered" + "Not verifiable"
  // D4.4: a delivered persistent mission carries its own label ("Criteria met" or "Ended without meeting its criteria") everywhere
  const resultChip = (m, tone, label, o) => m.outcome_label ? chip(m.outcome === "verified" ? "ok" : "warn", m.outcome_label, m.outcome === "verified" ? "check" : "alert")
    : m.empty ? chip("off", "Nothing produced", "info") : o && m.status === "delivered" ? chip(o[0], o[1], o[2]) : chip(tone, label);

  function card(m) {
    const [tone, label] = STATUS[m.status] || ["off", m.status], o = OUTCOME[m.outcome];
    const pct = Math.min(100, m.budget ? m.spent / m.budget * 100 : 0);
    return `<article class="mx-card" data-mxopen="${m.id}" tabindex="0" role="button" aria-label="Open mission ${esc(m.title)}">
      <div class="mx-ctop"><h4>${esc(m.title)}</h4>${resultChip(m, tone, label, o)}</div>
      <p class="mx-doing">${m.engine ? icon(ENGINE_ICON[m.engine] || "bot") : icon("sparkle")}${esc(m.doing)}</p>
      ${m.parent ? `<p class="muted small">Corrective mission for persistent mission #${esc(m.parent.split(":")[1])} · runs under the team's account, which approves its plan</p>` : ""}
      ${active(m) ? `<div class="mx-steps">${steps(m)}</div>` : m.summary ? `<p class="mx-sum">${esc(m.summary.slice(0, 220))}</p>` : m.error ? `<p class="mx-sum bad">${esc(m.error.slice(0, 220))}</p>` : ""}
      <div class="mx-meter" title="${money(m.spent)} of ${money(m.budget)}"><span style="width:${pct.toFixed(1)}%" class="${pct > 85 ? "hot" : ""}"></span></div>
      <div class="mx-cfoot"><span>${money(m.spent)} of ${money(m.budget)}</span><span>${m.deadline ? (m.deadline > Date.now() / 1000 && active(m) ? `due ${esc(until(m.deadline))}` : `deadline ${esc(when(m.deadline))}`) : m.estimate?.hours && active(m) ? `about ${esc(fmtNum(m.estimate.hours, 1))} h of work` : "no deadline"}</span></div>
    </article>`;
  }

  // Simple mode's missions: folded under the composer, one line until opened (open state kept across the refresh redraws)
  function mine() {
    const n = home.missions.length;
    if (!n) return "";
    return `<details class="mx-mine" data-mxmine${mineOpen ? " open" : ""}><summary>Your missions <span class="count">${n}</span></summary>${lists()}</details>`;
  }

  function lists() {
    const ms = home.missions, on = ms.filter(active), off = ms.filter(m => !active(m));
    return `<section class="mx-sec"><h3>Active missions <span class="count">${on.length}</span></h3>
        ${on.length ? `<div class="mx-grid">${on.map(card).join("")}</div>` : `<div class="empty">No mission is running. Describe a goal above to start one.</div>`}</section>
      <section class="mx-sec"><h3>Results <span class="count">${off.length}</span></h3>
        ${off.length ? `<div class="mx-grid">${off.slice(0, 24).map(card).join("")}</div>` : `<div class="empty">Delivered missions and their reports appear here.</div>`}
        ${home.lessons ? `<p class="muted mx-lessons">${icon("book")}AXoR keeps ${home.lessons} lesson${home.lessons === 1 ? "" : "s"} from earlier missions and reads the relevant ones when it plans.</p>` : ""}</section>`;
  }

  // ---------- one mission ----------
  function attached(m) {  // what the goal brought: documents, pictures, pages and GitHub repositories, and whether each was read
    const xs = m.attachments || [];
    if (!xs.length) return "";
    const IC = { document: "doc", image: "image", link: "link", repo: "github" };
    const st = a => a.status === "read" ? chip("ok", "Read") : a.status === "failed" ? chip("bad", "Not read") : chip("off", a.status === "reading" ? "Reading" : "Read when it starts");
    return `<section class="card mx-attached"><h3>${icon("upload")}What the goal brought</h3>
      <ul class="mx-attl">${xs.map(a => `<li>${icon(IC[a.kind] || "file")}<div><b>${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.name)}</a>` : esc(a.name)}</b>
        <span class="muted">${esc(a.about || "")}</span>${a.error ? `<p class="mx-atterr">${esc(a.error)}</p>` : ""}</div>${st(a)}</li>`).join("")}</ul>
      <p class="muted small">${icon("lock")}Read-only: what's attached is material for the agents, never instructions they follow. Planning reads up to about 8,000 characters of it; Long tasks get the full texts as files.</p></section>`;
  }

  function detail() {
    const m = d.mission, u = m.understanding || {}, v = m.verification, rep = m.report, a = m.allocation, adv = mode() === "advanced";
    const [tone, label] = STATUS[m.status] || ["off", m.status], o = OUTCOME[m.outcome];
    const left = m.budget - m.spent;
    const actions = [
      ["queued", "running"].includes(m.status) && `<button type="button" class="btn" data-mxact="pause">${icon("stop")}Pause</button>`,
      m.status === "paused" && `<button type="button" class="btn primary" data-mxact="resume">${icon("play")}Resume</button>`,
      m.stage === "execute" && ["running", "paused"].includes(m.status) && `<button type="button" class="btn" data-mxact="deliver">${icon("check")}Deliver what's done</button>`,
      active(m) && `<button type="button" class="btn" data-mxact="cancel">${icon("close")}Cancel</button>`,
      !active(m) && !(m.persistent && m.status === "monitoring") && `<button type="button" class="btn" data-mxact="again">${icon("cycle")}Run again</button>`,
      !active(m) && !(m.persistent && m.status === "monitoring") && `<button type="button" class="btn danger" data-mxact="delete">${icon("trash")}Delete</button>`,
    ].filter(Boolean).join("");
    const crit = (v?.results || []).length ? v.results : (u.criteria || []).map(c => ({ criterion: c, status: null }));
    return `<div class="mx-detail">
      <button type="button" class="mx-back" data-mx="back">${icon("left")}All missions</button>
      <header class="mx-dhead"><div><h1 class="page">${esc(m.title)}</h1><p class="lead">${esc(m.objective || m.goal)}</p></div>
        <div class="mx-dchips">${resultChip(m, tone, label, o)}${m.engine ? chip("off", home.engines[m.engine], ENGINE_ICON[m.engine]) : ""}</div></header>
      <div class="mx-steps lg">${steps(m)}</div>
      <p class="mx-doing big">${esc(m.doing)}${m.error ? ` · <span class="bad">${esc(m.error)}</span>` : ""}</p>
      <div class="mx-acts">${actions}</div>
      ${m.status === "needs_input" ? needs() : ""}
      ${adv ? CommandMap.slot(`m${m.id}`, { mission: m.id, toggle: "mission", title: "This mission's chain of command" }) : ""}
      <div class="mx-cols">
        <section class="card"><h3>${icon("coins")}Budget and time</h3>
          <div class="mx-meter lg"><span style="width:${Math.min(100, m.budget ? m.spent / m.budget * 100 : 0).toFixed(1)}%"></span></div>
          <dl class="mx-dl"><dt>Spent</dt><dd>${money(m.spent)} of ${money(m.budget)}${m.budget_auto ? ` <span class="muted">(set by AXoR from the mission's size)</span>` : ""} · ${short(m.tokens)} tokens</dd>
            <dt>AXoR's own calls</dt><dd>${money(d.mission.costs.own_usd)}</dd><dt>${esc(home.engines[m.engine] || "The engine")}</dt><dd>${money(d.mission.costs.child_usd)}</dd>
            <dt>Left</dt><dd>${money(left)}</dd>
            <dt>Deadline</dt><dd>${m.deadline ? `${esc(when(m.deadline))}${active(m) && m.deadline > Date.now() / 1000 ? ` (${esc(until(m.deadline))})` : ""}` : m.estimate?.hours ? `none · AXoR estimates about ${esc(fmtNum(m.estimate.hours, 1))} h of work` : "none"}</dd>
            <dt>Time so far</dt><dd>${m.started ? dur((m.finished || Date.now() / 1000) - m.started) : "—"}</dd>
            ${m.autonomy && !m.persistent ? `<dt>Autonomy</dt><dd>${esc(m.autonomy.level)} · ${esc(m.autonomy.name)}${m.autonomy.custom?.length ? " (customized)" : ""}<br><span class="muted small">Plan: ${esc(m.autonomy.lines.plan)} · After a failure: ${esc(m.autonomy.lines.recover)} · Deploys and the like: ${esc(m.autonomy.lines.external)}</span></dd>` : ""}
            ${m.estimate ? `<dt>Estimate</dt><dd>${m.estimate.hours != null ? `${fmtNum(m.estimate.hours, 1)} h` : "—"} · ${m.estimate.success != null ? `${m.estimate.success}% chance of success` : ""}</dd>` : ""}</dl>
          ${(active(m) || m.status === "paused") && home.autonomy ? `<form class="mx-inline mx-auto-change" data-mxform="autonomy">${autonomyField(adv, m.autonomy)}<button type="submit" class="btn">Set autonomy</button></form>` : ""}
          ${active(m) ? `<form class="mx-inline" data-mxform="budget"><label class="in"><span>Raise the budget to</span><div class="mx-money"><span>$</span><input name="budget" type="number" step="0.01" min="${Math.max(m.spent, 0.05).toFixed(2)}" value="${(m.budget * 2).toFixed(2)}"></div></label>
            <button type="submit" class="btn">Set</button></form>` : ""}</section>
        <section class="card"><h3>${icon("target")}Acceptance criteria</h3>
          <ul class="mx-crit">${crit.map(r => `<li>${r.status ? chip(...CRIT[r.status]) : chip("off", "To check")}<div><b>${esc(r.criterion)}</b>${r.evidence ? `<p>${esc(r.evidence)}</p>` : ""}</div></li>`).join("") || `<li class="muted">Written once AXoR understands the goal.</li>`}</ul>
          ${v ? `<p class="muted">${v.model ? `Checked by ${esc(v.model)}${v.independent === false ? " (the same model as the work: the pool has no other)" : ", not the model that did the work"}` : ""}${v.score != null ? ` · quality ${v.score}/100` : ""}</p>` : ""}</section>
      </div>
      ${evidence(m.evidence, m.persistent)}
      ${cycles(m)}
      ${attached(m)}
      ${rep ? report(rep, m) : ""}
      ${intel(m.discovery?.brief)}
      ${m.plan?.tasks?.length ? `<section class="card"><h3>${icon("list")}Plan</h3><ol class="mx-plan">${m.plan.tasks.map(t => `<li><b>${esc(t.title)}</b> <span class="muted">${esc(t.owner || "")}</span>${t.done_when ? `<p>Done when: ${esc(t.done_when)}</p>` : ""}</li>`).join("")}</ol>
        ${m.plan.risks?.length ? `<h4>Risks</h4><ul>${m.plan.risks.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</section>` : ""}
      ${(reqs => reqs.length ? `<section class="card"><h3>${icon("shield")}Waiting for your approval</h3>${reqs.map(r => requestRow({ ...r, title: m.title })).join("")}</section>` : "")(
        d.requests.filter(r => !(["team", "plan", "recover"].includes(r.kind) && r.status === "pending" && m.status === "needs_input")))}
      ${m.deliverable?.text ? `<section class="card mx-deliv"><h3>${icon("doc")}Deliverable</h3>${m.deliverable.link && adv ? `<p><button type="button" class="btn" data-mxview="${esc(m.deliverable.link.view)}" data-mxid="${esc(m.deliverable.link.id ?? "")}">${icon("external")}Open in ${esc(home.engines[m.engine])}</button></p>` : ""}
        ${m.deliverable.files?.length ? `<p class="muted">Files: ${m.deliverable.files.map(f => `<code>${esc(f)}</code>`).join(" ")}</p>` : ""}
        <div class="md mx-md">${Agents.md(m.deliverable.text)}</div></section>` : ""}
      <section class="card"><h3>${icon("clock")}Timeline</h3><ol class="mx-tl">${d.events.slice().reverse().map(e => `<li class="k-${esc(e.kind)}"><time>${esc(when(e.ts))}</time><span class="mx-st">${esc(STAGE[e.stage] || e.stage)}</span><p>${esc(e.text)}</p></li>`).join("")}</ol></section>
      ${adv ? `<section class="card mx-adv"><h3>${icon("sliders")}Advanced</h3>
        <dl class="mx-dl"><dt>Engine</dt><dd>${esc(home.engines[m.engine] || "—")}${m.child != null ? ` #${m.child}` : ""}${u.engine_why ? ` · ${esc(u.engine_why)}` : ""}${u.engine_switch ? `<br><span class="muted">Switched by track record: ${esc(u.engine_switch)}</span>` : ""}</dd>
          ${Object.keys(u.engine_record || {}).length ? `<dt>Track record</dt><dd>${Object.entries(u.engine_record).sort((x, y) => y[1].score - x[1].score).map(([k, e]) => `${esc(home.engines[k] || k)}: ${e.score}/100 over ${e.n} similar (${e.verified} verified, ${e.partial} partial, ${e.failed} failed)`).join("<br>")}</dd>` : ""}
          ${a ? `<dt>Model</dt><dd>${esc(a.model)} · $${a.price}/M tokens</dd><dt>Engine budget</dt><dd>${a.child_budget ? `${short(a.child_budget)} tokens` : "one call"} · reserve ${money(a.reserve)}</dd>` : ""}
          <dt>Attempts</dt><dd>${m.attempts || 0}${m.failure ? ` · last failure: ${esc(m.failure.replace("_", " "))}` : ""}</dd></dl>
        ${(m.history || []).length ? `<table class="mx-hist"><thead><tr><th>Attempt</th><th>Engine</th><th>Spent</th><th>Ended</th></tr></thead><tbody>${m.history.map(h => `<tr><td>${h.attempt}</td><td>${esc(home.engines[h.engine] || h.engine)} #${esc(h.child)}</td><td>${money(h.usd)}</td><td>${h.failed ? `${esc(h.failed)}: ${esc(h.error || "")}` : "—"}</td></tr>`).join("")}</tbody></table>` : ""}
        ${m.discovery ? `<h4>Found before planning</h4><ul>${[...(m.discovery.lessons || []).map(x => `Lesson (${x.kind}): ${x.text}`), ...(m.discovery.missions || []).map(x => `Earlier mission: ${x.title} (${x.outcome})`), ...(m.discovery.memories || []).map(x => `Workforce memory: ${x.text}`)].map(x => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>Nothing related yet.</li>"}</ul>` : ""}</section>` : ""}
    </div>`;
  }
  // the Intelligence Analyst's brief (mission_intel.py): researched in Discover, before the plan
  function intel(b) {
    if (!b) return "";
    if (b.skipped) return `<section class="card mx-intel"><h3>${icon("search")}Intelligence brief</h3><p class="muted">${esc(b.skipped)}</p></section>`;
    const conf = { high: "ok", medium: "warn", low: "off" };
    const src = x => x ? `<span class="mx-src">${esc(x)}</span>` : "";
    const facts = (b.facts || []).map(f => `<li>${f.confidence ? chip(conf[f.confidence] || "off", f.confidence) : ""}<div><b>${esc(f.claim)}</b>${src([f.source, f.as_of].filter(Boolean).join(" · "))}</div></li>`).join("");
    const comps = (b.competitors || []).map(c => `<li><b>${esc(c.name)}</b>${c.position ? ` <span class="muted">${esc(c.position)}</span>` : ""}${c.edge ? `<p>Edge: ${esc(c.edge)}</p>` : ""}${c.opening ? `<p>Opening: ${esc(c.opening)}</p>` : ""}</li>`).join("");
    const latest = (b.latest || []).map(x => `<li>${esc(x.item)}${src([x.source, x.date].filter(Boolean).join(" · "))}</li>`).join("");
    const unk = (b.unknowns || []).map(x => `<li>${esc(x)}</li>`).join("");
    return `<section class="card mx-intel"><h3>${icon("search")}Intelligence brief</h3>
      ${b.summary ? `<p class="mx-rsum">${esc(b.summary)}</p>` : ""}
      <div class="mx-rcols">
        ${facts ? `<div><h4>${icon("check")}Facts</h4><ul class="mx-crit">${facts}</ul></div>` : ""}
        ${comps ? `<div><h4>${icon("trophy")}Competitors</h4><ul>${comps}</ul></div>` : ""}
        ${latest ? `<div><h4>${icon("clock")}Latest</h4><ul>${latest}</ul></div>` : ""}
        ${unk ? `<div><h4>${icon("alert")}Not found or unverified</h4><ul>${unk}</ul></div>` : ""}
      </div>
      <p class="muted">Gathered before planning with ${b.lookups || 0} lookup${b.lookups === 1 ? "" : "s"} · web search ${b.web ? "on" : "off"}${b.model ? ` · ${esc(b.model)}` : ""}</p></section>`;
  }
  function evidence(ev, p) {
    if (!ev) return "";
    const chainStale = ev.measures.some(x => x.source === "chain" && x.status === "stale");
    const val = x => x.value == null ? "—" : typeof x.value === "boolean" ? (x.value ? "yes" : "no") : fmtNum(x.value, Number.isInteger(x.value) ? 0 : 4);
    const ref = r => !r ? "" : r.sample ? `sample #${r.sample}, block ${r.block}${r.uid != null ? `, UID ${r.uid}` : ""}` : r.metric_row ? `report #${r.metric_row}${r.key_id != null ? `, key #${r.key_id}` : ""}` : "";
    const basis = b => !b || !b.note ? "" : `<p class="muted small">${esc(b.note)}${b.attested_by ? ` · attested by ${esc(b.attested_by)}${b.attested_at ? ` on ${esc(when(b.attested_at))}` : ""}` : ""}${b.designated_by ? ` · designated by ${esc(b.designated_by)}${b.designated_at ? ` on ${esc(when(b.designated_at))}` : ""}` : ""}</p>`;
    const dim = (name, d) => `<span>${esc(name)}: ${chip(...DIM[d.value] || DIM.UNKNOWN)}</span>`;
    return `<section class="card mx-evidence"><h3>${icon("target")}Measures and evidence</h3>
      <p class="mx-dims">${dim("Competition outcome", ev.dimensions.competition)} ${dim("Technical benchmark", ev.dimensions.technical)}</p>
      <ul class="mx-crit">${ev.measures.map(x => `<li>${x.status === "valid" ? chip(x.pass ? "ok" : "bad", x.pass ? "Passes" : "Fails") : chip("off", "UNKNOWN")}
        <div><b>${esc(x.text)}</b> <span class="muted">${esc(x.category === "self_reported" ? "self-reported" : x.tier)} · ${esc(x.source)} · ${esc(x.metric)} ${esc(x.op)} ${esc(String(x.target))}</span>
        <p>${esc(EVST[x.status] || x.status)}: ${esc(val(x))}${x.reason ? ` · ${esc(x.reason)}` : ""}${x.evidence_ref ? ` <span class="muted">(${esc(ref(x.evidence_ref))})</span>` : ""}</p>
        ${basis(x.basis)}</div></li>`).join("")}</ul>
      <p class="muted small">Read only. Self-reported and internal evidence never decide the competition outcome; missing, stale, unverifiable or conflicting evidence is UNKNOWN.${ev.trust_note ? ` ${esc(ev.trust_note)}` : ""}${p && chainStale ? ` Sampling for paused campaigns: ${p.sample_paused ? "on (only while the team's board is paused too)" : "off"}.` : ""}</p></section>`;
  }

  function cycles(m) {
    const p = m.persistent;
    if (!p) return "";
    const cs = m.cycles || [], fx = p.failed_effects || [], hold = p.hold || { consecutive_pass: 0, required: p.hold_cycles };
    const dims = c => ["competition", "technical", "readiness"].map(k => `${k} ${esc(c.dimensions?.[k]?.value || "UNKNOWN")}`).join(" · ");
    // L5.5: a "correct" cycle records the gap it measured as a proposal in the Evolution Lab; later cycles name its answers (ids and states only)
    const gapLine = c => {
      const out = [];
      for (const e of (c.effects || []).filter(x => x.kind === "proposal")) {  // a rule-4 gap, and (IC-7 revision 2) a technical gap with its own key
        const r = e.result || {}, what = String(e.key || "").endsWith(":technical") ? "measured technical gap (internal, not a competition result)" : "measured gap";
        out.push(r.proposal ? `The ${what} is proposal #${r.proposal} in the Evolution Lab${r.linked ? " (already open: this cycle was added to it)" : ""}. The team's account answers it with a change to one of its agents.`
          : r.note ? `${r.note.charAt(0).toUpperCase()}${r.note.slice(1)}.` : `The ${what}'s proposal isn't recorded yet.`);
      }
      for (const g of c.proposals?.rows || []) for (const a of g.answers || []) if (a.status === "promoted")
        out.push(`Gap #${g.id} was answered by proposal #${a.id}: ${a.agent} v${a.before_version} → v${a.after_version}. ` + (h => !h ? "Whether the measure improved is read from the cycles after it."
          : h.verdict === "held" ? `It held: better than the reading that opened the gap in ${h.needed} measured cycles since (${h.rests_on} evidence).`
          : h.verdict === "not_held" ? `It did not hold: cycle ${h.cycles[h.cycles.length - 1].n} measured no better than the reading that opened the gap (${h.rests_on} evidence).`
          : `${h.counted} of ${h.needed} measured cycles since the promotion so far (${h.rests_on} evidence).`)(g.held));
      return out.map(t => `<p class="muted small">${esc(t)}</p>`).join("");
    };
    return `<section class="card mx-cycles"><h3>${icon("cycle")}Cycles</h3>
      <p class="muted small">Evaluated every ${esc(fmtNum(p.cycle_hours || 24, 1))} h, and early when the evidence changes. Passing cycles in a row: ${hold.consecutive_pass} of ${hold.required}${p.evaluation_paused ? " · evaluation paused" : p.next_due ? ` · next by ${esc(when(p.next_due))}` : ""}.
        Each decision follows fixed rules; Mission Control never plans, starts or cancels the team's work.</p>
      ${fx.map(e => `<p class="mx-warn">${icon("alert")}Cycle effect <code>${esc(e.key)}</code> failed${e.error ? `: ${esc(e.error)}` : ""}. Later cycles wait for it. <button type="button" class="btn" data-mxretry="${e.id}">Retry</button></p>`).join("")}
      <ol class="mx-tl mx-cyc">${cs.map(c => `<li><time>${esc(when(c.at))}</time><span class="mx-st">Cycle ${c.n}</span><div>${chip(...(DEC[c.decision?.kind] || ["off", c.decision?.kind || "?"]))} <span class="muted small">${esc(c.trigger)}</span>
        <p>${esc(c.decision?.reason || "")}</p><p class="muted small">${dims(c)} · hold ${c.hold?.consecutive_pass ?? 0}/${c.hold?.required ?? "?"}${c.decision?.rests_on?.length ? ` · rests on ${esc(c.decision.rests_on.join(", ").replaceAll("_", " "))}` : ""}</p>
        ${c.advice ? `<p>${esc(c.advice)}</p>` : ""}${gapLine(c)}</div></li>`).join("") || `<li class="muted">No cycle yet: the first one records the starting values.</li>`}</ol>
      ${(p.corrective || []).length ? `<h4>Corrective missions</h4><ul>${p.corrective.map(x => `<li>#${x.id} ${esc(x.title || "")} · ${esc(x.status)}${x.outcome ? ` · ${esc(x.outcome)}` : ""}</li>`).join("")}</ul>` : ""}
      ${m.status === "monitoring" ? `<div class="mx-inline"><label class="chk"><input type="checkbox" data-mxdirnote ${p.director_context ? "checked" : ""}> Show this mission to the team's Director (its plan and report read the latest cycle)</label>
        <button type="button" class="btn" data-mxfinal>${icon("check")}Deliver now: evaluate a final cycle</button></div>` : ""}
    </section>`;
  }

  function report(r, m) {
    const list = (title, xs, ic) => xs?.length ? `<div><h4>${icon(ic)}${title}</h4><ul>${xs.map(x => `<li>${esc(typeof x === "string" ? x : x.text || x.title)}</li>`).join("")}</ul></div>` : "";
    if (r.kind === "persistent") return `<section class="card mx-report"><h3>${icon("flag")}Report</h3>
      ${r.summary ? `<p class="mx-rsum">${esc(r.summary)}</p>` : ""}
      <div class="mx-rgrid">
        <div class="mx-kpi"><span>Outcome</span><b>${esc(r.label || r.outcome)}</b><em>${esc(r.outcome)}</em></div>
        <div class="mx-kpi"><span>Final cycle</span><b>${r.cycle}</b><em>${r.rule === 1 ? "criteria met" : "ended"}</em></div>
        <div class="mx-kpi"><span>Rests on</span><b>${esc((r.rests_on || []).join(", ").replaceAll("_", " ") || "—")}</b></div>
        <div class="mx-kpi"><span>Time</span><b>${dur(r.time?.seconds || 0)}</b>${r.time?.late ? `<em class="bad">past the deadline</em>` : ""}</div>
      </div>
      <div class="mx-rcols">${list("Limitations", r.limitations, "alert")}${list("Lessons kept", r.lessons, "book")}
        ${list("Corrective missions", (r.corrective || []).map(c => `#${c.id} ${c.title || ""}: ${c.status}`), "route")}</div>
    </section>`;
    return `<section class="card mx-report"><h3>${icon("flag")}Report</h3>
      ${r.summary ? `<p class="mx-rsum">${esc(r.summary)}</p>` : ""}
      <div class="mx-rgrid">
        <div class="mx-kpi"><span>Outcome</span><b>${esc(OUTCOME[r.outcome]?.[1] || r.outcome)}</b></div>
        <div class="mx-kpi"><span>Cost</span><b>${money(r.cost.usd)}</b><em>of ${money(r.cost.budget)}</em></div>
        <div class="mx-kpi"><span>Time</span><b>${dur(r.time.seconds)}</b>${r.time.late ? `<em class="bad">past the deadline</em>` : ""}</div>
        <div class="mx-kpi"><span>Attempts</span><b>${(r.attempts || []).length || 1}</b><em>${(r.attempts || []).filter(x => x.failed).length} failed</em></div>
      </div>
      <div class="mx-rcols">${list("Completed", r.completed, "check")}${list("Not finished", r.open, "clock")}${list("Limitations", r.limitations, "alert")}
        ${list("Recommended next", r.recommendations, "rocket")}${list("Lessons kept", r.lessons, "book")}${list("Only you can do", r.approvals, "shield")}</div>
    </section>`;
  }

  // ---------- events ----------
  function deadlineOf(f) {
    const v = f.deadline.value;
    if (!v) return null;
    if (v === "custom") { const t = Date.parse(f.custom.value); return Number.isFinite(t) ? t / 1000 : null; }
    return Date.now() / 1000 + +v;
  }
  function wire() {
    if (wired) return;
    wired = true;
    CommandMap.wire(root());  // the chain of command (command-map.js)
    root().addEventListener("toggle", e => { if (e.target.matches?.("[data-mxmine]")) mineOpen = e.target.open; }, true);
    root().addEventListener("click", async e => {
      const t = e.target;
      const rt = t.closest("[data-mxretry]");  // D4.3: a failed cycle effect, retried by the Owner or a delegate
      if (rt && d) {
        busy = true;
        try { await api(`/api/mos/missions/${d.mission.id}/effects/${rt.dataset.mxretry}/retry`, { method: "POST" }); Auth.toast("Retrying the effect"); await loadOne(); render(); }
        catch (x) { err(x); } finally { busy = false; }
        return;
      }
      if (t.closest("[data-mxfinal]") && d) {
        if (!confirm("Evaluate a final cycle now? Its decision asks you to confirm delivery; the team and its work are untouched.")) return;
        return act(`/api/mos/missions/${d.mission.id}/deliver`, {}, "A final cycle is evaluated next");
      }
      const b = t.closest("[data-mx]");
      if (b) {
        const k = b.dataset.mx;
        if (k === "advanced") return setMode("advanced"), setView("command");
        if (k === "back") { sel = null; d = null; return render(); }
        if (k === "unteam") { prefill = null; return render(); }
        if (k === "unbudget") { fixedBudget = null; return render(); }
        if (k === "files" || k === "pictures") return b.closest("form").querySelector(`input[name=${k}]`).click();
        if (k === "link") { const li = b.closest("form").querySelector(".mx-linkin"); li.hidden = !li.hidden; if (!li.hidden) li.querySelector("input").focus(); return; }
        if (k === "addlink") return addLink(b.closest("form"));
        if (k === "more") { extra = !extra; const f = b.closest("form"); f.querySelector(".mx-extra").hidden = !extra; b.setAttribute("aria-expanded", extra); b.querySelector("[data-icon], svg")?.remove(); b.insertAdjacentHTML("afterbegin", icon(extra ? "chev" : "right")); return; }
      }
      const tm = t.closest("[data-mxtmpl]");
      if (tm) { const f = tm.closest("form"); f.goal.value = tm.title; f.goal.focus(); return detect(f); }
      const ua = t.closest("[data-mxunatt]");
      if (ua) {
        const a = atts.splice(+ua.dataset.mxunatt, 1)[0], f = ua.closest("form");
        if (a?.id) api(`/api/mos/uploads/${a.id}`, { method: "DELETE" }).catch(() => {});  // a staged file nobody claims goes after a day anyway
        return drawAtts(f);
      }
      const ul = t.closest("[data-mxunlink]");
      if (ul) { links.splice(+ul.dataset.mxunlink, 1); return drawAtts(ul.closest("form")); }
      const bu = t.closest("[data-mxbudget]");
      if (bu) { bu.closest("form").budget.value = bu.dataset.mxbudget; return; }
      const op = t.closest("[data-mxopen]");
      if (op && !t.closest("button:not([data-mxopen]), a, input, textarea")) { sel = +op.dataset.mxopen; await loadOne(); render(); window.scrollTo({ top: 0 }); return; }
      const tmw = t.closest("[data-mxteam]");
      if (tmw && typeof MiningWork !== "undefined") return MiningWork.openPage(+tmw.dataset.mxteam);  // a Competition team at work
      const dv = t.closest("[data-mxview]");
      if (dv) return dv.dataset.mxview === "swarm" && dv.dataset.mxid && typeof Swarm !== "undefined" ? Swarm.show(+dv.dataset.mxid) : setView(dv.dataset.mxview);
      const dc = t.closest("[data-mxdecide]");
      if (dc) {
        const ok = dc.dataset.ok === "1", team = dc.dataset.kind === "team", gate = ["plan", "recover"].includes(dc.dataset.kind), body = { approve: ok, hash: dc.dataset.hash };
        if (dc.dataset.team === "pick") body.team = +dc.closest(".mx-req").querySelector("[data-mxteamsel]").value;
        const note = dc.closest(".mx-req")?.querySelector("[data-mxnote]")?.value.trim(); if (note) body.note = note;
        const ask = team ? (ok ? "Create this Competition team now? It starts with autopilot off; the mission then runs on it." :
          body.team ? "" : "Go on without a Competition team? The mission runs on the Workforce instead: you get a report, not team work.")
          : gate ? (dc.dataset.kind === "plan" ? (ok ? "" : note ? "" : "Plan again without a note? AXoR can only guess what to change.") : ok ? "" : "Stop trying and deliver what's done so far?")
          : dc.dataset.kind === "corrective" ? (ok ? "Start this corrective mission? It runs on the team under the team's account, with a hard budget, and waits for its plan's approval before any work runs." : "")
          : dc.dataset.kind === "deliver" ? (ok ? ((dc.closest(".mx-req")?.querySelector(".mx-kind")?.textContent || "").includes("Deliver:") ? "Deliver this mission now? It ends with this outcome, verified from the cycle's evidence, and frees the team's slot." : "Confirm? This older request is recorded only; the next cycle asks again to deliver.") : "")
          : dc.dataset.kind === "selfedit" ? (ok ? "Merge this exact commit into AXoR's self-edit branch? It is not deployed: putting it live stays your own step." : "Reject this code change? Nothing is merged and its branch is dropped.")  // D-040
          : ok ? "Approve this? AXoR records your decision; it doesn't carry the action out. You do it yourself, outside the mission." : "";
        if (ask && !confirm(ask)) return;
        busy = true; dc.disabled = true;
        try {
          await api(`/api/mos/requests/${dc.dataset.mxdecide}`, { method: "POST", body });
          Auth.toast(team ? (ok ? "Team created: the mission goes on, on it" : body.team ? "The mission goes on, on your team" : "The mission goes on without a team")
            : dc.dataset.kind === "plan" ? (ok ? "Approved: the plan runs" : "AXoR plans again") : dc.dataset.kind === "recover" ? (ok ? "Trying again" : "Delivering what's done")
            : dc.dataset.kind === "corrective" ? (ok ? "Corrective mission started: it waits for its plan's approval" : "Refused: nothing starts")
            : dc.dataset.kind === "selfedit" ? (ok ? "Merged (not deployed)" : "Rejected: nothing merged")
            : ok ? "Approved and recorded" : "Rejected");
        }
        catch (x) { err(x); } finally { busy = false; dc.disabled = false; }
        home = await api("/api/mos"); if (sel != null) await loadOne(); return render();
      }
      const ac = t.closest("[data-mxact]");
      if (ac && d) {
        const k = ac.dataset.mxact, id = d.mission.id;
        if (k === "cancel" && !confirm("Cancel this mission? Work in progress stops.")) return;
        if (k === "deliver") {
          const p = d.mission.progress || {}, ran = p.since ? dur(Date.now() / 1000 - p.since) : "";
          const msg = p.outputs === 0
            ? `Nothing has been produced yet${ran ? ` (the work started ${ran} ago)` : ""}.\n\nIf you deliver now, the work stops and the result will be empty. To let it keep working, press Cancel here.\n\nStop and deliver anyway?`
            : `Stop the work and deliver what's done so far?${ran ? ` It has been working for ${ran}.` : ""} Anything unfinished is lost.`;
          if (!confirm(msg)) return;
        }
        if (k === "delete") {
          if (!confirm("Delete this mission and its report?")) return;
          busy = true;
          try { await api(`/api/mos/missions/${id}`, { method: "DELETE" }); sel = null; d = null; home = await api("/api/mos"); render(); } catch (x) { err(x); } finally { busy = false; }
          return;
        }
        if (k === "again") {
          const m = d.mission;
          return act("/api/mos/missions", { body: { goal: m.goal, ...(m.budget_auto ? {} : { budget: m.budget }), again_of: m.id, deadline: m.deadline && m.deadline > Date.now() / 1000 + 600 ? m.deadline : null,
            experience: m.experience || "", resources: m.resources || "", constraints: m.constraints || "",
            ...(m.autonomy ? { autonomy: { level: m.autonomy.level, plan: m.autonomy.plan, recover: m.autonomy.recover, external: m.autonomy.external } } : {}) } }, "Mission started again");
        }
        return act(`/api/mos/missions/${id}/${k}`, {}, { pause: "Paused", resume: "Resumed", cancel: "Cancelled", deliver: "Delivering what's done" }[k]);
      }
    });
    root().addEventListener("keydown", e => {
      if (e.key === "Enter" && e.target.matches("[data-mxopen]")) e.target.click();
      if (e.key === "Enter" && e.target.matches("[data-mxform=new] [name=link]")) { e.preventDefault(); addLink(e.target.form); }
    });
    root().addEventListener("input", e => { if (e.target.matches("[data-mxform=new] [name=goal]")) detect(e.target.form); });
    // documents and pictures dropped on, or pasted into, the goal
    const dropBox = e => e.target.closest?.("[data-mxdrop]");
    root().addEventListener("dragover", e => { const b = dropBox(e); if (b && [...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); b.classList.add("drop"); } });
    root().addEventListener("dragleave", e => { const b = dropBox(e); if (b && !b.contains(e.relatedTarget)) b.classList.remove("drop"); });
    root().addEventListener("drop", e => { const b = dropBox(e); if (!b || !e.dataTransfer?.files?.length) return; e.preventDefault(); b.classList.remove("drop"); addFiles(b.closest("form"), e.dataTransfer.files); });
    root().addEventListener("paste", e => {
      const f = e.target.closest?.("[data-mxform=new]"), files = [...(e.clipboardData?.files || [])];
      if (f && files.length) { e.preventDefault(); addFiles(f, files); }
    });
    root().addEventListener("change", async e => {
      if (e.target.matches("[data-mxdirnote]") && d) {  // D4.3 (K-32b): off by default, per team
        try { d = await api(`/api/mos/missions/${d.mission.id}`, { method: "PATCH", body: { director_context: e.target.checked } });
          Auth.toast(e.target.checked ? "The Director sees the mission from its next plan or report" : "The Director no longer sees the mission"); render(); }
        catch (x) { err(x); e.target.checked = !e.target.checked; }
        return;
      }
      if (e.target.type === "file" && e.target.closest("[data-mxform=new]")) { const fs = [...e.target.files]; e.target.value = ""; return addFiles(e.target.form, fs); }
      if (e.target.name === "deadline") { const c = e.target.form.custom; c.hidden = e.target.value !== "custom"; c.required = !c.hidden; }
      if (e.target.name === "autonomy") { const ab = e.target.closest(".mx-auto")?.querySelector(".mx-auto-about"); if (ab) ab.textContent = home.autonomy?.levels.find(l => l.level === e.target.value)?.about || ""; }
    });
    root().addEventListener("submit", async e => {
      const f = e.target.closest("[data-mxform]");
      if (!f) return;
      e.preventDefault();
      const k = f.dataset.mxform;
      if (k === "new") {
        if (atts.some(a => a.state === "up")) return Auth.toast("Wait a moment: a file is still uploading.");
        const pend = f.querySelector("[name=link]")?.value.trim();
        if (pend) addLink(f);  // a link typed but not added yet
        const body = { goal: f.goal.value.trim(), attachments: atts.filter(a => a.state === "ok").map(a => a.id), resources: links.join("\n") };
        if (f.deadline) {  // Advanced: the optional overrides under Fine-tune
          const dl = deadlineOf(f);
          if (f.deadline.value === "custom" && !dl) return Auth.toast("Pick the deadline's date and time.");
          if (dl) body.deadline = dl;
          body.experience = f.experience.value; body.constraints = f.constraints.value;
          const au = autonomyOf(f); if (au && (au.level !== home.autonomy?.default || Object.keys(au).length > 1)) body.autonomy = au;
        }
        const bud = f.budget?.value ? +f.budget.value : fixedBudget;
        if (bud) body.budget = bud;
        if (f.engine?.value) body.engine = f.engine.value;
        if (f.team?.value) body.team = +f.team.value;
        if (prefill && !f.engine) { body.engine = "mining"; body.team = prefill.id; }  // Simple mode: the team the mission was started from
        const r = await act("/api/mos/missions", { body }, "Mission started: AXoR is on it");
        if (r) { extra = false; prefill = null; resetComposer(); window.scrollTo({ top: 0 }); }
      } else if (k === "answer") {
        const n = f.querySelectorAll("input").length;
        await act(`/api/mos/missions/${f.dataset.id}/answer`, { body: { answers: [...Array(n).keys()].map(i => f[`a${i}`].value) } }, "Thanks: the mission goes on");
      } else if (k === "autonomy" && d) {
        busy = true;
        try { d = await api(`/api/mos/missions/${d.mission.id}`, { method: "PATCH", body: { autonomy: autonomyOf(f) } }); Auth.toast("Autonomy set: it applies from the next step"); home = await api("/api/mos"); render(); }
        catch (x) { err(x); } finally { busy = false; }
      } else if (k === "budget" && d) {
        busy = true;
        try { d = await api(`/api/mos/missions/${d.mission.id}`, { method: "PATCH", body: { budget: +f.budget.value } }); Auth.toast("Budget raised"); home = await api("/api/mos"); render(); }
        catch (x) { err(x); } finally { busy = false; }
      }
    });
  }

  function show(id) {  // a deep link (the Approval Center): one mission, or the page
    sel = id ?? null; d = null;
    setView("mos");
  }

  function start(team) {  // My subnets' "Start mission" on a team: a new mission, already aimed at that team
    prefill = team ? { id: team.id, label: team.label, netuid: team.netuid } : null;
    sel = null; d = null;
    setView("mos");
    setTimeout(() => root()?.querySelector("[data-mxform=new] textarea[name=goal]")?.focus(), 400);
  }

  function draft(goal, budget, netuid) {  // Intelligence layers' acceptance test: a controlled mission written into the composer for you to check and start
    // budget: kept for the start (a chip in Simple mode, the Fine-tune field in Advanced); netuid: run it on that subnet's Competition
    // team (engine "mining"), when the composer offers one
    prefill = null; sel = null; d = null; fixedBudget = budget ? +budget : null;
    setView("mos");
    setTimeout(() => {
      if (shown()) render();  // the budget chip / field
      const f = root()?.querySelector("[data-mxform=new]");
      if (!f) return;
      f.goal.value = goal;
      if (netuid && f.team) {
        const o = [...f.team.options].find(x => x.textContent.startsWith(`SN${netuid} `));
        if (o) { f.team.value = o.value; if (f.engine && [...f.engine.options].some(x => x.value === "mining" && !x.disabled)) f.engine.value = "mining"; f.querySelector(".mx-tune")?.setAttribute("open", ""); }
        else toast(`No SN${netuid} Competition team: the mission runs where AXoR decides.`);
      } else if (netuid) toast(mode() === "advanced" ? "You have no Competition team: the mission runs where AXoR decides."
                                                     : `Switch to Advanced to put it on your SN${netuid} Competition team; in Simple mode AXoR decides.`);
      detect(f);
      f.goal.focus();
    }, 400);
  }

  return { open, stop, init, landing, mode, setMode, show, start, draft };
})();
