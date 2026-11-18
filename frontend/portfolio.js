/* Portfolio (mining_portfolio.py, mining_knowledge.py): Global HQ over your competition teams (#portfolio, sidebar → Workspace).
   - Teams: every open team side by side with its measured numbers (standing and rank, the Lab's eval, done and failed in 7 days,
     tokens per done task, sandbox dollars, emission share, days left, knowledge shared and read). Review the portfolio asks the
     Portfolio Manager for a call on each team (invest, optimize, investigate, hold, pause), a focus, a budget and task forces;
     each suggestion is one click: apply the budget, send the focus to the team's Director, start the task force.
   - Knowledge: what each notebook entry may reach (private and restricted stay with the team; shared on the subnet; global
     candidates wait for you; shared everywhere). The Knowledge Manager classifies new entries; you change any scope or lesson.
   - Task forces: extra specialists who join a team for a goal and some days, then switch off (their findings stay).
   It polls every 15 seconds while it shows (every 2.5 while the Portfolio Manager reviews) and redraws only what changed. */
const Portfolio = (() => {
  const P = "/api/mining/portfolio", K = "/api/mining/knowledge";
  const CALL = { invest: ["ok", "Invest", "trophy"], optimize: ["run", "Optimize", "wrench"], investigate: ["warn", "Investigate", "search"],
                 hold: ["none", "Hold", "check"], pause: ["off", "Pause", "stop"] };
  const STATE = { working: ["run", "Working"], stuck: ["bad", "Stuck"], waiting: ["warn", "Waiting for you"], idle: ["none", "Idle"] };
  const STAND = { green: ["ok", "On track"], amber: ["warn", "Needs attention"], red: ["bad", "At risk"] };
  const SCOPE = { private: ["none", "lock"], restricted: ["bad", "ban"], subnet_shared: ["run", "users"], global_candidate: ["warn", "clock"], global_approved: ["ok", "globe"] };
  const TIERS = [["Tier 1 · the team's own", "Private and restricted entries stay in the team's notebook. Restricted ones never leave it: scoring internals, tasks and their answers, your own plans."],
                 ["Tier 2 · the subnet", "Shared on the subnet: your other teams on the same subnet read the lesson, never the raw entry."],
                 ["Tier 3 · every subnet", "A global candidate is shared on its subnet while it waits for you. Approve it and every team of yours reads it."]];
  let d = null, k = null, failed = "", tab = null, on = false, wired = false, timer = null, loading = false, filter = "all";
  const root = () => document.getElementById("portfolio");
  const err = e => e && Auth.toast(e.message);
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const tok = n => n == null ? "–" : n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const entries = n => n === 1 ? "1 entry" : `${n} entries`;
  const TONE = { ok: "clear", run: "new", wait: "new", warn: "caution", bad: "scam", none: "muted", off: "muted" };  // styles.css's badges
  const chip = (cls, text, ic = "") => `<span class="badge ${TONE[cls] || "muted"}">${ic ? icon(ic) : ""}${text}</span>`;
  const when = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const label = t => `SN${t.netuid} · ${t.number ?? esc(t.label)}`;
  const sugg = i => i.suggested && i.suggested !== i.scope;  // the Knowledge Manager's word, when it differs from the scope kept
  const latest = () => d?.reviews.find(r => r.status === "done") || null;
  const running = () => d?.reviews.some(r => r.status === "running");
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  // ---------- data ----------
  function open() {
    on = true; wire();
    if (tab === null) { try { tab = store.get("pf.tab", "teams"); } catch { tab = "teams"; } }
    if (!d) put(root(), Loading.line("Opening your portfolio…"));
    load();
  }
  function stop() { on = false; clearTimeout(timer); }
  async function load() {
    if (loading) return; loading = true;
    try { [d, k] = await Promise.all([api(P), api(K)]); failed = ""; }
    catch (e) { failed = e.message; }
    finally { loading = false; }
    badge();
    if (!typing()) render();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (!on) return;
    const quick = running() || k?.running?.length;
    timer = setTimeout(() => { if (!on || $("#view-portfolio")?.hidden || document.visibilityState !== "visible") return schedule(); load(); }, quick ? 2500 : 15000);
  }
  // a poll never redraws under someone typing a goal, a note or a lesson
  const typing = () => !!document.activeElement?.closest?.("#portfolio form, #portfolio textarea, #portfolio input[type=text]");
  function badge() {
    const n = k?.counts?.global_candidate || 0, el = $("#c-portfolio");
    if (el) el.textContent = n || "";
  }
  function take(r) { if (r?.teams) d = r; else if (r?.items) k = r; badge(); render(); schedule(); }

  // ---------- the page ----------
  function render() {
    const el = root(); if (!el) return;
    if (!d || !k) { put(el, failed ? `<div class="empty">${esc(failed)} <button type="button" class="linkbtn" data-pf="reload">Try again</button></div>` : Loading.line("Opening your portfolio…")); return; }
    const cands = k.counts.global_candidate, live = d.forces.filter(f => ["active", "dissolving"].includes(f.status)).length;
    const tabs = [["teams", "users", "Teams", d.teams.length], ["knowledge", "book", "Knowledge sharing", cands ? `<span class="hq-n alert" title="Global candidates waiting for you">${cands}</span>` : ""],
                  ["forces", "zap", "Task forces", live || ""]];
    put(el, `<div class="pf">
      <header class="pf-top"><div><h1>${icon("target")}Portfolio</h1>
        <p class="faint">Global HQ: your competition teams side by side, how far their findings travel, reviews, priorities and task forces. Nothing here changes a team until you press its button.</p></div>
        <div class="pf-top-act"><button type="button" class="btn sm" data-pf="teams">${icon("users")}Competition teams</button></div></header>
      <nav class="pf-tabs" role="tablist" aria-label="Portfolio">${tabs.map(([id, ic, l, n]) => `<button type="button" role="tab" class="pf-tab ${tab === id ? "on" : ""}" aria-selected="${tab === id}" data-pftab="${id}">${icon(ic)}${l}${n !== "" && n != null ? ` <span class="faint">${n}</span>` : ""}</button>`).join("")}</nav>
      <div class="pf-body">${!d.teams.length && tab !== "knowledge" ? welcome() : tab === "knowledge" ? knowledge() : tab === "forces" ? forces() : teams()}</div></div>`);
  }
  const welcome = () => `<section class="card pf-empty"><h2>No open competition team yet</h2>
      <p>The portfolio compares your competition teams. Add a subnet in My subnets, import its competitions on the Competition teams page and approve a team for each: they show up here.</p>
      <button type="button" class="btn primary" data-pf="teams">${icon("users")}Open Competition teams</button></section>`;

  // ---------- teams ----------
  function teams() {
    const T = d.totals, r = latest(), going = running(), last = d.reviews[0];
    const tile = (ic, l, v, sub, cls = "") => `<div class="stat ${cls}"><div class="label">${icon(ic)}${l}</div><div class="value num">${v}</div><div class="sub">${sub}</div></div>`;
    const calls = Object.fromEntries((r?.out?.teams || []).map(t => [t.id, t]));
    return `<div class="stats pf-kpis">
        ${tile("users", "Open teams", d.teams.length, `${d.teams.filter(t => t.autopilot && !t.paused).length} on autopilot`)}
        ${tile("check", "Done (7 days)", T.done_week, "tasks across the teams")}
        ${tile("alert", "Failed runs (7 days)", T.failed_week, `of ${T.runs_week} runs`, T.runs_week && T.failed_week / T.runs_week > .25 ? "t-warn" : "")}
        ${tile("coins", "Tokens (7 days)", tok(T.tokens_week), T.done_week ? `${tok(Math.round(T.tokens_week / T.done_week))} per done task` : "nothing done yet")}
        ${tile("terminal", "Sandbox (7 days)", usd(T.sandbox_usd_week), "inference in sandbox runs")}
        ${tile("inbox", "Waiting for you", T.waiting, "across the teams", T.waiting ? "t-warn" : "")}</div>
      <section class="card pf-review">
        <div class="pf-h"><h2>${icon("sparkle")}The Portfolio Manager</h2>
          <form class="pf-ask" data-pfform="review"><label class="in"><span class="sr">A note for the review</span><input type="text" name="note" maxlength="600" placeholder="A note for the review (optional), e.g. the SQL competition matters most" ${going ? "disabled" : ""}></label>
            <button type="submit" class="btn sm primary" ${going || !d.model ? "disabled" : ""} title="${d.model ? "One model call compares every open team" : "Connect a model in Agents → Models"}">${icon(going ? "cycle" : "sparkle")}${going ? "Reviewing…" : "Review the portfolio"}</button></form></div>
        ${going ? `<p class="pf-going">${icon("cycle")}Reading every team's numbers and deciding where effort should go…</p>` : ""}
        ${last?.status === "failed" ? `<p class="pf-fail">${icon("alert")}The last review failed: ${esc(last.error || "no reason given")}</p>` : ""}
        ${r ? review(r) : !going ? `<p class="faint">Ask for a review when you want a second opinion on where to spend. It reads only the numbers below and suggests; you decide team by team.</p>` : ""}
      </section>
      <div class="pf-grid">${d.teams.map(t => team(t, calls[t.id], r)).join("")}</div>
      ${d.reviews.filter(x => x.status === "done" && x !== r).length ? `<details class="pf-past"><summary>Earlier reviews</summary><ul>${d.reviews.filter(x => x.status === "done" && x !== r).map(x => `<li><time class="faint num">${when(x.ts)}</time> ${esc(x.headline || "")}</li>`).join("")}</ul></details>` : ""}`;
  }
  function review(r) {
    const o = r.out, applied = r.applied || {};
    const tf = (o.taskforces || []).map((f, i) => { const t = d.teams.find(x => x.id === f.team);
      return `<li class="pf-tf"><div><b>${icon("zap")}Task force for ${t ? label(t) : "a team"}</b> <span class="faint small">${plural(f.days, "day")} · ${plural(f.members.length, "member")}</span>
          <p>${esc(f.goal)}</p><p class="faint small">${f.members.map(m => esc(m.title)).join(" · ")}</p></div>
        <button type="button" class="btn sm" data-pfforce="${i}" data-rid="${r.id}" ${t?.force ? "disabled title=\"This team has a task force already\"" : ""}>${icon("play")}Start it</button></li>`; }).join("");
    return `<div class="pf-out"><p class="pf-head"><b>${esc(o.headline || r.headline || "")}</b> <span class="faint small">${when(r.finished || r.ts)} · ${tok(r.tokens)} tokens${r.by_user ? ` · asked by ${esc(r.by_user)}` : ""}</span></p>
        ${o.summary ? `<div class="md">${Agents.md(o.summary)}</div>` : ""}
        ${(o.spending || []).length ? `<h4 class="pf-sub">${icon("coins")}Spend ahead of results</h4><ul class="pf-spend">${o.spending.map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
        ${tf ? `<h4 class="pf-sub">${icon("zap")}Suggested task forces</h4><ul class="pf-tfs">${tf}</ul>` : ""}
        ${Object.keys(applied).length ? `<p class="faint small">${icon("check")}${plural(Object.keys(applied).length, "suggestion")} applied.</p>` : ""}</div>`;
  }
  function team(t, c, r) {
    const [sc, sl] = STATE[t.state] || ["none", esc(t.state)], st = STAND[t.standing], ev = t.eval, applied = r?.applied || {};
    const fig = (l, v, sub = "") => `<div><span>${l}</span><b>${v}</b>${sub ? `<small class="faint">${sub}</small>` : ""}</div>`;
    const evalv = !ev ? "–" : ev.solved != null ? `${ev.solved} / ${ev.tasks}` : "no base";
    const evsub = ev ? [ev.gained && `<em class="up">+${ev.gained} gained</em>`, ev.lost && `<em class="down">${ev.lost} lost</em>`].filter(Boolean).join(" ") : "";
    const call = c ? (() => { const [cc, cl, ci] = CALL[c.call] || CALL.hold;
      return `<div class="pf-call c-${c.call}"><p>${chip(cc, cl, ci)} ${esc(c.why || "")}</p>
        ${c.focus ? `<p class="pf-focus"><b>Focus:</b> ${esc(c.focus)}</p>` : ""}
        <div class="row pf-call-act">${c.focus ? `<button type="button" class="btn sm" data-pfapply="focus" data-team="${t.id}" data-rid="${r.id}" ${applied[`${t.id}:focus`] ? "disabled" : ""}>${icon(applied[`${t.id}:focus`] ? "check" : "send")}${applied[`${t.id}:focus`] ? "Sent to the Director" : "Send to the Director"}</button>` : ""}
          ${c.budget ? `<button type="button" class="btn sm" data-pfapply="budget" data-team="${t.id}" data-rid="${r.id}" ${applied[`${t.id}:budget`] || c.budget === t.budget ? "disabled" : ""}>${icon(applied[`${t.id}:budget`] ? "check" : "coins")}${applied[`${t.id}:budget`] || c.budget === t.budget ? `Budget ${tok(c.budget)} a day` : `Budget ${tok(t.budget)} → ${tok(c.budget)} a day`}</button>` : ""}</div></div>`; })() : "";
    return `<article class="card pf-team s-${t.state}">
      <div class="pf-team-h"><div class="pf-id"><b>${label(t)}</b><small class="faint">${esc(t.number != null ? t.label : t.subnet)}${t.paused ? " · paused" : t.autopilot ? " · autopilot" : ""}</small></div>${chip(sc, sl)}</div>
      <p class="pf-line faint small">${esc(t.line || "")}</p>
      <div class="mini pf-mini">
        ${fig("Standing", st ? chip(st[0], st[1]) : "–", t.rank ? `rank ${t.rank} of ${t.of}` : "no brief yet")}
        ${fig("Eval", evalv, evsub || (ev?.on ? esc(ev.on) : "the Lab"))}
        ${fig("Done (7 d)", t.done_week, `${t.done} of ${t.tasks} in all`)}
        ${fig("Failed runs", t.failed_week, `of ${t.runs_week} in 7 d`)}
        ${fig("Tokens (7 d)", tok(t.tokens_week), t.per_done ? `${tok(t.per_done)} per done task` : "")}
        ${fig("Sandbox", usd(t.sandbox_usd_week), "7 days")}
        ${fig("Emissions", t.share != null ? pct(t.share, 0) : "–", "of the subnet")}
        ${fig("Ends", t.left != null ? (t.left < 0 ? "ended" : plural(t.left, "day")) : "–", t.ends ? esc(t.ends) : "no end date")}
        ${fig("Knowledge", `${t.shared} ↑ · ${t.reads} ↓`, "shared · read")}</div>
      ${t.force ? `<p class="pf-force">${icon("zap")}<span><b>Task force:</b> ${esc(t.force.goal)} <span class="faint small">${plural(t.force.members, "member")}${t.force.status === "dissolving" ? ", dissolving" : `, until ${when(t.force.ends)}`}</span></span></p>` : ""}
      ${call}
      <div class="row end pf-act"><button type="button" class="btn sm ghost" data-pfopen="${t.id}">${icon("external")}Open the team</button></div></article>`;
  }

  // ---------- knowledge ----------
  function knowledge() {
    const L = k.labels, C = k.counts, cands = k.items.filter(i => i.scope === "global_candidate");
    const list = k.items.filter(i => filter === "all" || i.scope === filter || (filter === "suggested" && sugg(i)));
    const opts = i => Object.keys(L).map(s => `<option value="${s}" ${i.scope === s ? "selected" : ""}>${L[s]}</option>`).join("");
    const item = i => { const [cls, ic] = SCOPE[i.scope] || SCOPE.private;
      return `<li class="pf-k s-${i.scope}"><div class="pf-k-h"><span class="pf-k-t"><b>${esc(i.title || "A notebook entry")}</b><small class="faint">${esc(i.where)} · ${i.by ? esc(i.by) : ""}${i.updated ? ` · ${ago(i.updated)}` : ""}</small></span>
          ${chip(cls, L[i.scope], ic)}</div>
        ${i.lesson ? `<p class="pf-lesson">${esc(i.lesson)}</p>` : ""}
        ${i.why ? `<p class="faint small">${esc(i.why)}${i.reach ? ` · read by ${plural(i.reach, "other team")}` : ""}</p>` : i.reach ? `<p class="faint small">Read by ${plural(i.reach, "other team")}</p>` : ""}
        ${i.suggested && i.suggested !== i.scope ? `<p class="pf-sugg">${icon("bulb")}The Knowledge Manager suggests <b>${L[i.suggested]}</b> but wasn't sure. <button type="button" class="btn sm" data-pfscope="${i.suggested}" data-item="${i.id}">${icon("check")}Accept</button></p>` : ""}
        <div class="row pf-k-act"><label class="in pf-k-sel"><span class="sr">Who may read it</span><select data-pfsel="${i.id}">${opts(i)}</select></label>
          <details class="pf-k-edit"><summary class="linkbtn">${i.lesson ? "Edit the lesson" : "Write a lesson"}</summary>
            <form data-pfform="lesson" data-item="${i.id}"><label class="in"><span>The lesson other teams read <em class="opt">stand-alone, without task names or answers</em></span>
              <textarea name="lesson" rows="3" maxlength="700">${esc(i.lesson)}</textarea></label><button type="submit" class="btn sm">${icon("check")}Save the lesson</button></form></details></div></li>`; };
    const waiting = k.waiting.filter(w => w.n);
    const hub = $('nav.side [data-view="knowledge"]:not([hidden])');
    return `<p class="faint small pf-kwhere">${icon("info")}This tab only sets how far a team's notebook entries travel between your competition teams. The company's shared knowledge lives in the ${hub ? `<button type="button" class="linkbtn" data-pfview="knowledge">Knowledge Hub</button>` : "Knowledge Hub"}.</p>
      <div class="pf-tiers">${TIERS.map(([h, p]) => `<div class="card"><b>${h}</b><p class="faint small">${p}</p></div>`).join("")}</div>
      <section class="card pf-kset"><label class="mh-check"><input type="checkbox" data-pfauto ${k.auto ? "checked" : ""}><span><b>The Knowledge Manager classifies new findings by itself</b> <span class="faint">one short model call per batch, on the team's model and within its daily budget. It shares only what it's sure of; anything tied to an evaluator's tasks stays restricted.</span></span></label>
        ${k.running.length ? `<p class="pf-going">${icon("cycle")}Reading ${k.running.map(esc).join(", ")}…</p>` : ""}
        ${waiting.length ? `<ul class="pf-wait">${waiting.map(w => `<li><span>${esc(w.where)}: ${entries(w.n)} not classified${w.older ? ` (${w.older} from before sharing started)` : ""}</span>
            <button type="button" class="btn sm" data-pfclassify="${w.team}" data-older="${w.older && w.older === w.n ? 1 : 0}">${icon("sparkle")}Classify now</button></li>`).join("")}</ul>` : ""}</section>
      ${k.promote && (k.promote.ready || k.promote.sent) ? `<section class="card pf-kset"><p><b>${icon("book")}Company memory</b> <span class="faint small">Shared lessons stay team knowledge until they pass review in Company Knowledge, where verified records are read by every agent and each read counts as reuse.</span></p>
          <p class="row">${k.promote.ready && k.promote.can ? `<button type="button" class="btn sm" data-pfpromote>${icon("send")}Send ${k.promote.ready} shared lesson${k.promote.ready === 1 ? "" : "s"} for review</button>` : ""}
          <span class="faint small">${k.promote.sent ? `${k.promote.sent} sent so far, with their notebook entry, team and reviewer as provenance.` : "Private and restricted entries are never sent."}${hub && k.promote.sent ? ` <button type="button" class="linkbtn" data-pfview="knowledge">Review them</button>` : ""}</span></p></section>` : ""}
      ${cands.length ? `<section class="card pf-cands"><h2>${icon("clock")}Waiting for you <span class="hq-n alert">${cands.length}</span></h2>
          <p class="faint small">Global candidates are shared on their subnet already. Approve one and every team of yours reads it.</p>
          <ul class="pf-klist">${cands.map(i => `<li class="pf-k"><div class="pf-k-h"><span class="pf-k-t"><b>${esc(i.title || "")}</b><small class="faint">${esc(i.where)}</small></span></div>
            <p class="pf-lesson">${esc(i.lesson)}</p><div class="row pf-k-act"><button type="button" class="btn sm primary" data-pfscope="global_approved" data-item="${i.id}">${icon("globe")}Share everywhere</button>
            <button type="button" class="btn sm" data-pfscope="subnet_shared" data-item="${i.id}">${icon("users")}Keep it on the subnet</button></div></li>`).join("")}</ul></section>` : ""}
      <section class="card"><div class="pf-h"><h2>${icon("book")}Every classified entry</h2>
        <div class="pf-filter" role="group" aria-label="Show">${[["all", "All", k.items.length], ...Object.keys(L).map(s => [s, L[s], C[s]]), ["suggested", "Suggestions", k.items.filter(sugg).length]]
          .map(([id, l, n]) => `<button type="button" class="pf-f ${filter === id ? "on" : ""}" aria-pressed="${filter === id}" data-pffilter="${id}">${l} <span class="faint">${n}</span></button>`).join("")}</div></div>
        ${list.length ? `<ul class="pf-klist">${list.map(item).join("")}</ul>` : `<p class="faint">${k.items.length ? "Nothing here with this filter." : "Nothing classified yet. Entries reach the notebook when work is approved; the Knowledge Manager reads them within a minute or two."}</p>`}</section>`;
  }

  // ---------- task forces ----------
  function forces() {
    const live = d.forces.filter(f => ["active", "dissolving"].includes(f.status)), past = d.forces.filter(f => !["active", "dissolving"].includes(f.status));
    const free = d.teams.filter(t => !t.force);
    const one = f => `<article class="card pf-fc s-${f.status}"><div class="pf-team-h"><div class="pf-id"><b>${esc(d.labels[f.comp_id] || "")}</b><small class="faint">since ${when(f.created)}${f.by_user ? ` · ${esc(f.by_user)}` : ""}${f.review_id ? " · from a review" : ""}</small></div>
        ${chip(f.status === "active" ? "run" : f.status === "dissolving" ? "wait" : f.status === "kept" ? "ok" : "off", { active: "Active", dissolving: "Dissolving", kept: "Kept", dissolved: "Dissolved" }[f.status] || f.status)}</div>
      <p>${esc(f.goal)}</p>
      <ul class="pf-members">${f.members.map(m => `<li class="${m.active ? "" : "off"}"><span class="av sm c-${m.color}" aria-hidden="true">${icon(m.icon || "zap")}</span><span><b>${esc(m.name)}</b> <small class="faint">${esc(m.title)}${m.active ? "" : " · off"}</small></span></li>`).join("")}</ul>
      <p class="faint small">${plural(f.done, "task")} done · ${entries(f.notes)} in the notebook${f.status === "active" ? ` · ends ${when(f.ends)}` : f.closed ? ` · ended ${when(f.closed)}` : ""}${f.note ? ` · ${esc(f.note)}` : ""}</p>
      ${f.status === "active" ? `<div class="row end pf-act"><button type="button" class="btn sm" data-pfkeep="${f.id}">${icon("check")}Keep them for good</button><button type="button" class="btn sm" data-pfdissolve="${f.id}">${icon("stop")}Dissolve now</button></div>` : ""}</article>`;
    return `<p class="faint pf-intro">A task force is a few extra specialists who join a team for a goal and a number of days. The first one leads it and reviews the others; the Director plans their work. When the days are up they switch off: their findings stay in the notebook, their unstarted tasks go to the Director.</p>
      ${live.length ? `<div class="pf-grid">${live.map(one).join("")}</div>` : ""}
      <section class="card pf-new"><h2>${icon("plus")}New task force</h2>
        ${free.length ? `<form data-pfform="force" class="pf-form">
          <div class="pf-row"><label class="in"><span>Team</span><select name="team">${free.map(t => `<option value="${t.id}">${label(t)} ${esc(t.number != null ? t.label : "")}</option>`).join("")}</select></label>
            <label class="in pf-days"><span>Days</span><input type="number" name="days" min="1" max="${d.limits.days}" value="7" required></label></div>
          <label class="in"><span>Goal</span><input type="text" name="goal" minlength="4" maxlength="600" required placeholder="e.g. Lift the SQL tasks the base doesn't solve"></label>
          <fieldset class="pf-tpl"><legend>Members <em class="opt">up to ${d.limits.members}</em></legend>${d.templates.map((t, i) => `<label class="mh-check"><input type="checkbox" name="m" value="${t.id}" ${i < 2 ? "checked" : ""}><span><b>${esc(t.title)}</b> <span class="faint">${esc(t.job)}</span></span></label>`).join("")}</fieldset>
          <div class="row end"><button type="submit" class="btn sm primary">${icon("zap")}Start the task force</button></div></form>`
        : `<p class="faint">${d.teams.length ? "Every open team has a task force already." : "There's no open team to send one to."}</p>`}</section>
      ${past.length ? `<details class="pf-past"><summary>Ended task forces <span class="faint">${past.length}</span></summary><div class="pf-grid">${past.map(one).join("")}</div></details>` : ""}`;
  }

  // ---------- actions ----------
  function wire() {
    if (wired) return; wired = true;
    const v = $("#view-portfolio");
    v.addEventListener("click", async e => {
      const t = e.target;
      const tb = t.closest("[data-pftab]"); if (tb) { tab = tb.dataset.pftab; try { store.set("pf.tab", tab); } catch { /* only the tab isn't remembered */ } return render(); }
      const pv = t.closest("[data-pfview]"); if (pv) return setView(pv.dataset.pfview);
      const f = t.closest("[data-pffilter]"); if (f) { filter = f.dataset.pffilter; return render(); }
      const o = t.closest("[data-pfopen]"); if (o) return MiningWork.openPage(+o.dataset.pfopen);
      const a = t.closest("[data-pfapply]");
      if (a) { const r = await busy(a, () => api(`${P}/reviews/${a.dataset.rid}/apply`, { method: "POST", body: { team: +a.dataset.team, what: a.dataset.pfapply } }));
        if (r) { Auth.toast(a.dataset.pfapply === "budget" ? "Budget changed" : "Sent: the Director is planning with it"); take(r); } return; }
      const fc = t.closest("[data-pfforce]");
      if (fc) { const r = await busy(fc, () => api(`${P}/reviews/${fc.dataset.rid}/force`, { method: "POST", body: { index: +fc.dataset.pfforce } }));
        if (r) { Auth.toast("The task force joined the team"); take(r); } return; }
      const sc = t.closest("[data-pfscope]");
      if (sc) { const r = await busy(sc, () => api(`${K}/items/${sc.dataset.item}`, { method: "PATCH", body: { scope: sc.dataset.pfscope } }));
        if (r) { Auth.toast(sc.dataset.pfscope === "global_approved" ? "Shared with every team of yours" : "Saved"); take(r); } return; }
      const pr = t.closest("[data-pfpromote]");
      if (pr) { const r = await busy(pr, () => api(`${K}/promote`, { method: "POST" }));
        if (r) { Auth.toast(r.sent ? `${r.sent} lesson${r.sent === 1 ? "" : "s"} sent to Company Knowledge for review${r.left ? ` (${r.left} more next time)` : ""}` : r.stopped || "Nothing to send"); take(await api(K)); } return; }
      const cl = t.closest("[data-pfclassify]");
      if (cl) { const r = await busy(cl, () => api(`${K}/teams/${cl.dataset.pfclassify}/classify`, { method: "POST", body: { older: cl.dataset.older === "1" } }));
        if (r) { Auth.toast("The Knowledge Manager is reading the notebook"); take(r); } return; }
      const ds = t.closest("[data-pfdissolve]");
      if (ds) return UI.confirm({ title: "Dissolve this task force?", body: "Its members switch off once they finish the task at hand. Their findings stay in the notebook and their unstarted tasks go to the Director.", ok: "Dissolve",
        run: async () => { take(await api(`${P}/forces/${ds.dataset.pfdissolve}/dissolve`, { method: "POST" })); Auth.toast("Dissolved"); } }).catch(err);
      const kp = t.closest("[data-pfkeep]");
      if (kp) { const r = await busy(kp, () => api(`${P}/forces/${kp.dataset.pfkeep}/keep`, { method: "POST" })); if (r) { Auth.toast("They stay on the team"); take(r); } return; }
      const b = t.closest("[data-pf]"); if (!b) return;
      if (b.dataset.pf === "teams") return setView("teams");
      if (b.dataset.pf === "reload") return load();
    });
    v.addEventListener("change", async e => {
      const t = e.target;
      if (t.matches("[data-pfsel]")) { const r = await busy(null, () => api(`${K}/items/${t.dataset.pfsel}`, { method: "PATCH", body: { scope: t.value } })); if (r) { Auth.toast(`Now: ${r.labels[t.value]}`); take(r); } else render(); }
      if (t.matches("[data-pfauto]")) { const r = await busy(null, () => api(`${K}/settings`, { method: "POST", body: { auto: t.checked } })); if (r) { Auth.toast(t.checked ? "Classifies new findings by itself" : "Only when you ask"); take(r); } else t.checked = !t.checked; }
    });
    v.addEventListener("submit", async e => {
      const fm = e.target.closest("[data-pfform]"); if (!fm) return;
      e.preventDefault();
      const kind = fm.dataset.pfform, btn = fm.querySelector("[type=submit]"), F = new FormData(fm);
      if (kind === "review") { const r = await busy(btn, () => api(`${P}/review`, { method: "POST", body: { note: F.get("note") || "" } })); if (r) { fm.reset(); document.activeElement?.blur(); Auth.toast("The Portfolio Manager is reviewing your teams"); take(r); } }
      if (kind === "lesson") { const r = await busy(btn, () => api(`${K}/items/${fm.dataset.item}`, { method: "PATCH", body: { lesson: F.get("lesson") || "" } })); if (r) { document.activeElement?.blur(); Auth.toast("Lesson saved"); take(r); } }
      if (kind === "force") {
        const members = F.getAll("m").map(template => ({ template }));
        if (!members.length) return Auth.toast("Pick at least one member");
        if (members.length > d.limits.members) return Auth.toast(`A task force has at most ${d.limits.members} members`);
        const r = await busy(btn, () => api(`${P}/forces`, { method: "POST", body: { team: +F.get("team"), goal: F.get("goal"), days: +F.get("days"), members } }));
        if (r) { document.activeElement?.blur(); Auth.toast("The task force joined the team"); take(r); }
      }
    });
  }

  return { open, stop };
})();
