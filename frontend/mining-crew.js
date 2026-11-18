/* Competition teams, the crew (mining_crew.py), as sub-tabs of a team on the Competition teams page (mining-work.js draws the page):
   - Diagram: the team as a live map you control: You, the Director, each squad under its lead. Nodes show who works, who's free
     and who's off; live lines show work going to its reviewer and work waiting for you. Drag agents where you want them (the
     layout is saved for the team), pan, zoom, fit; click an agent for its controls (on/off, give a task, start its next task,
     stop what it's doing, write to it, its history), and the team's controls (autopilot, pause, stop, plan) sit on top.
   - Roadmap: the competition from start to end: milestones on a timeline with today's line, each with its dates, owner,
     status and the tasks finished in its window. A default roadmap comes from the competition's dates.
   - Prompts: every agent's prompt history: what each run was asked and answered, and your messages. Pick agents (one, several,
     all), filter, search; select entries one by one, several or all, then remember, forget, export or delete them; open one to
     read or edit it; write a prompt to the agents you picked: a message for their next run, or a task they start now.
   - Levels: every agent's engineer level from its experience on the team (XP from tasks done, findings approved, first-time
     approvals, reviews, plans, failures), with its record: hours, tokens, days on the team, its most used tools.
   - Links: the team's Source repository, Drive folder, DevOps pipeline, cluster deployment, apps and functions, each with its
     live state from its own page (admins' pages say so to others); the notebook and the prompt histories save to Drive.
   - Desk: any of the team's views side by side, arranged your way (flex.js). */
const MiningCrew = (() => {
  const W = "/api/mining/work";
  let cs = null, csWid = null, csAt = 0, csLoading = false, wired = false;
  const P = { wid: null, entries: [], total: 0, more: false, sel: new Set(), all: false, agents: new Set(), kind: "", q: "", loading: false, at: 0, failed: "", open: new Set(), full: {} };
  const D = { wid: null, z: 1, x: 20, y: 20, sel: null, act: null, flow: true, fitted: false, live: {} };
  const H = {};  // the other hubs' state, for Links: kind → { at, data, error }
  const NW = 176, NH = 64;
  const err = e => e && Auth.toast(e.message);
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, n >= 1e5 ? 0 : 1)}k` : fmtNum(n || 0, 0);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const entries = (n, w = "") => `${n} ${w}${n === 1 ? "entry" : "entries"}`;
  const chip = ([cls, text]) => `<span class="hq-chip t-${cls}">${text}</span>`;
  const av = (a, size = "sm") => a ? `<span class="av ${size} c-${a.color}" aria-hidden="true">${icon(a.icon)}</span>` : `<span class="av ${size} mw-you" aria-hidden="true">${icon("smile")}</span>`;
  const V = () => MiningWork.view();
  const AG = () => Object.fromEntries((V()?.agents || []).map(a => [a.id, a]));
  const iso = d => d.toISOString().slice(0, 10);
  const dts = s => new Date(`${s}T00:00:00`).getTime();
  const day = s => new Date(`${s}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }
  function go(view) { const b = $(`#nav-${view}`); if (b && !b.hidden) b.click(); else location.hash = `#${view}`; }

  // ---------- the crew's state: levels, roadmap, links, layout, history counts ----------
  function need(v) {
    const wid = v.comp.id;
    if (csWid !== wid) { cs = null; csWid = wid; csAt = 0; D.sel = null; D.fitted = false; D.live = {}; }
    if (csLoading || Date.now() - csAt < 8000) return;
    csLoading = true;
    api(`${W}/comps/${wid}/crew`).then(s => { if (csWid === wid) { cs = s; csAt = Date.now(); MiningWork.rerender(); } })
      .catch(e => { csAt = Date.now(); err(e); }).finally(() => { csLoading = false; });
  }
  function set(s) { if (s?.comp === csWid) { cs = s; csAt = Date.now(); } MiningWork.rerender(); }
  const fresh = () => { csAt = 0; };
  const loading = () => Loading.line("Reading the team's records…");

  // an agent's level, as a small badge (the org chart and the diagram)
  function badge(aid) {
    const l = cs?.levels?.[aid]?.level; if (!l) return "";
    return `<span class="mc-lvl l-${l.n}" title="Level ${l.n}: ${esc(l.name)} · ${fmtNum(l.xp, 0)} XP">L${l.n}</span>`;
  }

  // ---------- Diagram ----------
  function auto(v) {
    const lead = v.agents.find(a => a.lead), groups = [];
    for (const a of v.agents) {
      if (a === lead) continue;
      const k = a.squad || ""; let g = groups.find(x => x.k === k);
      if (!g) groups.push(g = { k, list: [] });
      g.list.push(a);
    }
    for (const g of groups) g.list.sort((x, y) => y.head - x.head);
    const pos = {}, GX = 26, top = (NH + 54) * 2;
    groups.forEach((g, gi) => { let y = top; g.list.forEach(a => { pos[a.id] = [gi * (NW + GX), y]; y += NH + (a.head ? 34 : 16); }); });
    const width = Math.max(NW, groups.length * (NW + GX) - GX);
    if (lead) pos[lead.id] = [width / 2 - NW / 2, NH + 54];
    pos[0] = [width / 2 - NW / 2, 0];
    return { pos, groups, lead };
  }
  function positions(v) {
    const a = auto(v), saved = cs?.layout || {};
    const pos = { ...a.pos };
    for (const k of Object.keys(pos)) { const s = D.live[k] || saved[k]; if (s) pos[k] = s; }
    return { ...a, pos };
  }
  function edges(v, L) {
    const { pos, lead } = L, out = [], A = AG(), heads = {};
    for (const a of v.agents) if (a.head && a.squad) heads[a.squad] = a;
    const path = (p, c, cls, label = "") => {
      if (!p || !c) return;
      const x1 = p[0] + NW / 2, y1 = p[1] + NH, x2 = c[0] + NW / 2, y2 = c[1], my = (y1 + y2) / 2;
      out.push(`<path class="${cls}" d="M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}"${label ? ` data-n="${label}"` : ""}/>`);
    };
    if (lead) path(pos[0], pos[lead.id], "e-you");
    for (const a of v.agents) {
      if (a === lead) continue;
      const up = a.head || !a.squad || !heads[a.squad] ? lead : heads[a.squad];
      if (up) path(pos[up.id], pos[a.id], `e-org ${a.on ? "" : "off"}`);
    }
    if (!D.flow) return out.join("");
    // live: work on its way to its reviewer, and work waiting for you
    const waitBy = {};
    for (const t of v.tasks) {
      if (t.status === "checking" && t.reviewer && pos[t.agent] && pos[t.reviewer]) {
        const a = pos[t.agent], r = pos[t.reviewer], x1 = a[0] + NW / 2, y1 = a[1], x2 = r[0] + NW / 2, y2 = r[1] + NH;
        out.push(`<path class="e-flow" d="M${x1},${y1} C${x1 + 40},${(y1 + y2) / 2} ${x2 + 40},${(y1 + y2) / 2} ${x2},${y2}" marker-end="url(#mc-arrow)"><title>${esc(`${A[t.agent]?.name} → ${A[t.reviewer]?.name}: ${t.title}`)}</title></path>`);
      }
      if ((["review", "blocked"].includes(t.status)) && t.agent != null) waitBy[t.agent] = (waitBy[t.agent] || 0) + 1;
    }
    // with the Director relaying, the waiting work goes to the Director, and only the report comes to you
    const relay = MiningDirector.relaying(v) && lead && pos[lead.id];
    if (relay) {
      for (const [aid, n] of Object.entries(waitBy)) {
        const a = pos[aid], d = pos[lead.id]; if (!a || +aid === lead.id) continue;
        const x1 = a[0] + NW / 2, y1 = a[1], x2 = d[0] + NW - 18, y2 = d[1] + NH;
        out.push(`<path class="e-relay" d="M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2 + 40} ${x2},${y2}" marker-end="url(#mc-arrow)"><title>${esc(`${A[aid]?.name}: ${plural(n, "task")} with ${lead.name}`)}</title></path>`);
      }
      const r = MiningDirector.open(v), d = pos[lead.id], y = pos[0];
      if (r?.asks.length && y) out.push(`<path class="e-wait" d="M${d[0] + NW - 18},${d[1]} C${d[0] + NW - 18},${(d[1] + y[1] + NH) / 2} ${y[0] + NW - 18},${(d[1] + y[1] + NH) / 2} ${y[0] + NW - 18},${y[1] + NH}" marker-end="url(#mc-arrow-w)"><title>${esc(`${lead.name}'s report: ${plural(r.asks.length, "ask")} for you`)}</title></path>`);
      return out.join("");
    }
    for (const [aid, n] of Object.entries(waitBy)) {
      const a = pos[aid], y = pos[0]; if (!a || !y) continue;
      const x1 = a[0] + NW / 2, y1 = a[1], x2 = y[0] + NW - 18, y2 = y[1] + NH;
      out.push(`<path class="e-wait" d="M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2 + 40} ${x2},${y2}" marker-end="url(#mc-arrow-w)"><title>${esc(`${A[aid]?.name}: ${plural(n, "task")} waiting for you`)}</title></path>`);
    }
    return out.join("");
  }
  function node(v, a, p, T) {
    const st = !a.on ? ["off", "Off"] : a.doing === "review" ? ["run", "Reviewing"] : a.doing === "plan" ? ["run", "Planning"] : a.working ? ["run", T[a.working]?.title || "Working"]
      : a.queued ? ["wait", `${a.queued} queued`] : ["ok", "Free"];
    return `<button type="button" class="mc-n s-${st[0]} ${D.sel === a.id ? "sel" : ""} ${a.lead ? "lead" : a.head ? "head" : ""}" data-mcn="${a.id}" style="left:${p[0]}px;top:${p[1]}px"
        aria-pressed="${D.sel === a.id}" aria-label="${esc(`${a.name}, ${a.title}: ${st[1]}`)}">
      ${av(a)}<span class="mc-n-t"><b>${esc(a.name)}${badge(a.id)}</b><span class="faint">${esc(a.title)}</span>
        <span class="mc-n-s"><span class="ci ci-${st[0]}"></span>${esc(st[1])}</span></span></button>`;
  }
  function diagram(v) {
    need(v);
    if (!cs) return loading();
    if (D.wid !== v.comp.id) { D.wid = v.comp.id; D.fitted = false; D.sel = null; }
    const L = positions(v), T = Object.fromEntries(v.tasks.map(t => [t.id, t])), A = AG();
    const xs = Object.values(L.pos), w = Math.max(...xs.map(p => p[0])) + NW + 40, h = Math.max(...xs.map(p => p[1])) + NH + 40;
    const waiting = MiningDirector.waiting(v), relay = MiningDirector.relaying(v);
    const you = L.pos[0], c = v.comp, closed = c.status === "closed", running = v.tasks.some(t => ["queued", "working", "checking"].includes(t.status));
    const lead = A[v.lead];
    if (!D.fitted) requestAnimationFrame(fit);
    return `<div class="mc-dia-wrap">
      <div class="mc-dia-bar" role="toolbar" aria-label="Control the team">
        <label class="mw-switch" title="Autopilot"><input type="checkbox" data-mwpilot ${c.autopilot ? "checked" : ""} ${closed ? "disabled" : ""}><span aria-hidden="true"></span><b>Autopilot</b></label>
        ${(c.autopilot || c.paused) && !closed ? `<button type="button" class="btn sm" data-mw="${c.paused ? "resume" : "pause"}">${icon(c.paused ? "play" : "stop")}${c.paused ? "Resume" : "Pause"}</button>` : ""}
        ${running ? `<button type="button" class="btn sm mw-danger" data-mw="stop">${icon("ban")}Stop now</button>` : ""}
        <button type="button" class="btn sm" data-mw="plan" ${!lead || v.planning || closed ? "disabled" : ""}>${icon(v.planning ? "cycle" : "route")}${v.planning ? "Planning…" : "Plan now"}</button>
        ${c.autopilot ? "" : `<button type="button" class="btn sm" data-mw="startall" ${closed ? "disabled" : ""}>${icon("play")}Start assigned</button>`}
        <button type="button" class="btn sm" data-mcwrite="">${icon("send")}Write to the team</button>
        <span class="mc-dia-z"><button type="button" class="iconbtn" data-mcz="-1" aria-label="Zoom out" title="Zoom out">${icon("minus")}</button>
          <button type="button" class="iconbtn" data-mcz="1" aria-label="Zoom in" title="Zoom in">${icon("plus")}</button>
          <button type="button" class="iconbtn" data-mcz="0" aria-label="Fit the team in view" title="Fit">${icon("fit")}</button>
          <button type="button" class="iconbtn" data-mc="flow" aria-pressed="${D.flow}" title="${D.flow ? "Hide" : "Show"} live work lines" aria-label="Live work lines">${icon("zap")}</button>
          <button type="button" class="iconbtn" data-mc="relayout" ${Object.keys(cs.layout || {}).length ? "" : "disabled"} aria-label="Back to the automatic layout" title="Automatic layout">${icon("reset")}</button></span></div>
      <div class="mc-dia">
        <div class="mc-view" data-mcview data-hold tabindex="0" aria-label="The team diagram: drag agents to move them, drag the background to pan, Ctrl + wheel to zoom">
          <div class="mc-canvas" style="width:${w}px;height:${h}px;transform:translate(${D.x}px,${D.y}px) scale(${D.z})">
            <svg class="mc-edges" width="${w}" height="${h}" aria-hidden="true"><defs>
              <marker id="mc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z"/></marker>
              <marker id="mc-arrow-w" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z"/></marker></defs>
              <g data-mcedges>${edges(v, L)}</g></svg>
            ${L.groups.filter(g => g.k).map(g => { const ps = g.list.map(a => L.pos[a.id]), x = Math.min(...ps.map(p => p[0])), y = Math.min(...ps.map(p => p[1]));
              return `<span class="mc-sq" style="left:${x}px;top:${y - 22}px">${esc(v.squads[g.k] || g.k)}</span>`; }).join("")}
            <button type="button" class="mc-n you ${D.sel === 0 ? "sel" : ""}" data-mcn="0" style="left:${you[0]}px;top:${you[1]}px" aria-pressed="${D.sel === 0}">
              ${av(null)}<span class="mc-n-t"><b>You</b><span class="faint">${c.autopilot ? "Autopilot on" : "You run the team"}</span>
              <span class="mc-n-s">${waiting ? `<span class="ci ci-warn"></span><b class="mw-waiting">${relay ? `${plural(waiting, "ask")} for you` : `${waiting} waiting for you`}</b>` : `<span class="ci ci-ok"></span>${relay ? "No report waiting" : "Nothing waits"}`}</span></span></button>
            ${v.agents.map(a => node(v, a, L.pos[a.id], T)).join("")}
          </div></div>
        ${inspector(v, T)}</div>
      <p class="faint small mc-legend"><span><i class="lg org"></i>reports to</span><span><i class="lg flow"></i>work going to its reviewer</span>${relay ? `<span><i class="lg relay"></i>work going to ${esc(lead?.name || "the Director")}</span><span><i class="lg wait"></i>the report to you</span>` : `<span><i class="lg wait"></i>work waiting for you</span>`}
        <span>Drag agents to arrange them, drag the background to pan, Ctrl + wheel to zoom.</span></p></div>`;
  }
  function inspector(v, T) {
    if (D.sel === 0 && MiningDirector.relaying(v)) {
      const r = MiningDirector.open(v), L = AG()[v.lead];
      return `<aside class="mc-insp">${av(null, "lg")}<h3>You</h3><p class="faint small">Agents don't contact you one by one: ${esc(L?.name || "the Director")} settles what the team can and sends you one report.</p>
        ${r ? `<p class="small"><b>${esc(r.headline)}</b></p>${r.asks.length ? `<ul class="mc-insp-l">${r.asks.slice(0, 8).map(x => `<li><span>${esc(x.title)}</span><span class="faint small">${x.kind === "todo" ? "to do" : "decision"}</span></li>`).join("")}</ul>` : `<p class="small">${icon("check")} Nothing in it needs you.</p>`}`
          : `<p class="small">${icon("check")} No report waiting${v.director.with_director ? `; ${plural(v.director.with_director, "item")} with ${esc(L?.name || "the Director")}` : ""}.</p>`}
        <div class="mc-insp-act"><button type="button" class="btn sm" data-mwsub="report">${icon("inbox")}Open the report</button><button type="button" class="btn sm" data-mcwrite="">${icon("send")}Write to everyone</button></div></aside>`;
    }
    if (D.sel === 0) {
      const mine = v.tasks.filter(t => ["review", "blocked"].includes(t.status) || (t.status === "todo" && t.agent == null)), A = AG();
      return `<aside class="mc-insp">${av(null, "lg")}<h3>You</h3><p class="faint small">What waits for you: reviews, agents' questions and your own tasks.</p>
        ${mine.length ? `<ul class="mc-insp-l">${mine.slice(0, 12).map(t => `<li><button type="button" class="linkbtn" data-mwtask="${t.id}">${esc(t.title)}</button><span class="faint small">${t.status === "blocked" ? "a question" : t.status === "review" ? `review · ${esc(A[t.agent]?.name || "")}` : "your task"}</span></li>`).join("")}</ul>` : `<p class="small">${icon("check")} Nothing waits for you.</p>`}
        <div class="mc-insp-act"><button type="button" class="btn sm" data-mw="addtask">${icon("plus")}Task</button><button type="button" class="btn sm" data-mcwrite="">${icon("send")}Write to everyone</button></div></aside>`;
    }
    const a = AG()[D.sel];
    if (!a) return `<aside class="mc-insp empty-insp"><p class="faint small">${icon("pointer")} Click an agent for its controls; click <b>You</b> for what waits for you.</p>
      <ul class="mc-insp-sum small"><li><b>${v.agents.filter(x => x.working || x.doing).length}</b> at work</li><li><b>${v.agents.filter(x => x.on && !x.working && !x.doing).length}</b> free</li><li><b>${v.agents.filter(x => !x.on).length}</b> off</li>
        <li><b>${v.tasks.filter(t => t.status === "checking").length}</b> in review</li></ul></aside>`;
    const lv = cs?.levels?.[a.id], next = v.tasks.find(t => t.agent === a.id && t.status === "todo"), cur = a.working ? T[a.working] : null;
    const h = cs?.prompts?.[a.id];
    return `<aside class="mc-insp">${av(a, "lg")}<h3>${esc(a.name)} ${badge(a.id)}</h3><p class="faint small">${esc(a.title)}${a.lead ? " · Director" : a.head ? " · squad lead" : ""}${a.squad ? ` · ${esc(v.squads[a.squad] || a.squad)}` : ""}</p>
      ${lv ? `<div class="mc-xp"><span>${esc(lv.level.name)}</span><span class="mc-xp-bar"><i style="--w:${(lv.level.progress * 100).toFixed(0)}%"></i></span><span class="faint small">${fmtNum(lv.level.xp, 0)} XP${lv.level.next ? ` · ${fmtNum(lv.level.next - lv.level.xp, 0)} to the next level` : ""}</span></div>` : ""}
      <p class="small">${cur ? `${icon("cycle")}On <button type="button" class="linkbtn" data-mwtask="${cur.id}">${esc(cur.title)}</button>` : a.doing === "review" ? `${icon("eye")}Reviewing a teammate's work` : a.doing === "plan" ? `${icon("route")}Planning` : a.on ? `${icon("check")}Free${a.queued ? `, ${plural(a.queued, "task")} queued` : ""}` : `${icon("ban")}Switched off: starts nothing new`}</p>
      <p class="faint small">${a.done} done · ${a.open} open · ${short(a.tokens_day)} tokens today${h ? ` · ${entries(h.n, "history ")}${h.waiting ? `, ${h.waiting} unread from you` : ""}` : ""}</p>
      <div class="mc-insp-act">
        <button type="button" class="btn sm" data-mwon="${a.id}">${icon(a.on ? "ban" : "play")}${a.on ? "Switch off" : "Switch on"}</button>
        <button type="button" class="btn sm" data-mwnewfor="${a.id}" ${a.on ? "" : "disabled"}>${icon("plus")}Give a task</button>
        ${next && !a.working && a.on ? `<button type="button" class="btn sm" data-mcstart="${next.id}" title="${esc(next.title)}">${icon("play")}Start next task</button>` : ""}
        ${cur ? `<button type="button" class="btn sm mw-danger" data-mccancel="${cur.id}">${icon("stop")}Stop it</button>` : ""}
        <button type="button" class="btn sm" data-mcwrite="${a.id}">${icon("send")}Write to ${esc(a.name)}</button>
        <button type="button" class="btn sm" data-mchist="${a.id}">${icon("clock")}History</button>
        <button type="button" class="btn sm ghost" data-mwedit="${a.id}">${icon("edit")}Edit</button></div></aside>`;
  }
  function paint() {  // redraws the canvas in place while you drag, without re-rendering the page
    const v = V(), view = $("[data-mcview]"); if (!v || !view) return;
    const L = positions(v), cv = $(".mc-canvas", view);
    cv.style.transform = `translate(${D.x}px,${D.y}px) scale(${D.z})`;
    for (const [k, p] of Object.entries(D.live)) { const n = $(`[data-mcn="${k}"]`, cv); if (n) { n.style.left = `${p[0]}px`; n.style.top = `${p[1]}px`; } }
    const g = $("[data-mcedges]", cv); if (g) g.innerHTML = edges(v, L);
  }
  function fit() {
    const v = V(), view = $("[data-mcview]"); if (!v || !view || !cs) return;
    const ps = Object.values(positions(v).pos), w = Math.max(...ps.map(p => p[0])) + NW, h = Math.max(...ps.map(p => p[1])) + NH;
    const vw = view.clientWidth - 30, vh = view.clientHeight - 30;
    D.z = Math.max(0.35, Math.min(1.15, Math.min(vw / w, vh / h)));
    D.x = (view.clientWidth - w * D.z) / 2; D.y = 15; D.fitted = true;
    paint();
  }
  function zoom(by, cx, cy) {
    const view = $("[data-mcview]"); if (!view) return;
    const r = view.getBoundingClientRect(), x = cx ?? r.width / 2, y = cy ?? r.height / 2, z = Math.max(0.3, Math.min(2, D.z * by));
    D.x = x - (x - D.x) * (z / D.z); D.y = y - (y - D.y) * (z / D.z); D.z = z; D.fitted = true; paint();
  }
  function saveLayout() {
    const v = V(); if (!v || !cs) return;
    const pos = { ...(cs.layout || {}), ...D.live };
    cs.layout = pos; D.live = {};
    api(`${W}/comps/${v.comp.id}/layout`, { method: "PUT", body: { pos } }).catch(err);
  }

  // ---------- Roadmap ----------
  function roadmap(v) {
    need(v);
    if (!cs) return loading();
    const R = cs.roadmap, c = v.comp, A = AG();
    if (!R.length) return `<section class="mh-welcome mc-empty"><div><h2>${icon("map")}A roadmap from start to end</h2>
        <p>Milestones on the competition's timeline, each with its dates, an owner and a status. Agents read the current milestone and the next one before they work, so they aim at the same thing you do.</p>
        <p class="faint small">${c.starts || c.ends ? `The default spreads five milestones from ${c.starts ? day(c.starts) : "today"} to ${c.ends ? day(c.ends) : "two weeks on"}.` : "The competition has no dates: the default runs two weeks from today. Add its dates in the team's settings for a better one."}</p>
        <div class="row"><button type="button" class="btn primary" data-mc="seed">${icon("sparkle")}Set up the default roadmap</button><button type="button" class="btn" data-mc="addms">${icon("plus")}Add a milestone</button></div></div></section>`;
    const today = iso(new Date());
    const start = c.starts || R.map(m => m.starts || m.due).filter(Boolean).sort()[0] || today;
    let end = c.ends || R.map(m => m.due).filter(Boolean).sort().pop() || iso(new Date(dts(start) + 14 * 864e5));
    if (dts(end) <= dts(start)) end = iso(new Date(dts(start) + 864e5));
    const t0 = dts(start), span = dts(end) - t0, at = s => Math.max(0, Math.min(100, (dts(s) - t0) / span * 100));
    const done = R.filter(m => m.status === "done").length;
    const ticks = Array.from({ length: 5 }, (_, i) => iso(new Date(t0 + span * i / 4)));
    let prev = start;
    const rows = R.map(m => { const a = m.starts || prev, b = m.due || end; prev = m.due || prev; return { m, a, b }; });
    const ST = { todo: ["none", "To do"], doing: ["run", "In progress"], done: ["ok", "Done"] };
    const inWin = (a, b) => v.tasks.filter(t => t.status === "done" && !t.dropped && t.done_at && t.done_at * 1000 >= dts(a) && t.done_at * 1000 < dts(b) + 864e5).length;
    const late = m => m.status !== "done" && m.due && m.due < today;
    return `<div class="mc-road">
      <div class="mc-road-head"><div><b>${done} of ${plural(R.length, "milestone")} done</b> <span class="faint small">${day(start)} → ${day(end)}${today >= start && today <= end ? ` · ${Math.round((dts(end) - dts(today)) / 864e5)} days left` : today > end ? " · past its end" : ` · starts in ${Math.round((dts(start) - dts(today)) / 864e5)} days`}</span></div>
        <div class="row"><button type="button" class="btn sm" data-mc="addms">${icon("plus")}Milestone</button><button type="button" class="btn sm ghost" data-mc="reseed">${icon("reset")}Start over</button></div></div>
      <div class="mc-tl" role="img" aria-label="The roadmap on a timeline">
        <div class="mc-tl-ticks">${ticks.map((t, i) => `<span style="left:${i * 25}%">${day(t)}</span>`).join("")}</div>
        ${today >= start && today <= end ? `<span class="mc-today" style="left:${at(today)}%"><b>Today</b></span>` : ""}
        ${rows.map(({ m, a, b }) => `<button type="button" class="mc-bar st-${m.status} ${late(m) ? "late" : ""}" data-mcmedit="${m.id}" style="left:${at(a)}%;width:max(${Math.max(1.5, at(b) - at(a))}%, 8px)" title="${esc(`${m.title}: ${day(a)} – ${day(b)}`)}"><span>${esc(m.title)}</span></button>`).join("")}</div>
      <ol class="mc-ms">${rows.map(({ m, a, b }, i) => { const o = A[m.agent], n = inWin(a, b);
        return `<li class="st-${m.status} ${late(m) ? "late" : ""}"><span class="mc-ms-n">${m.status === "done" ? icon("check") : i + 1}</span>
          <div class="mc-ms-main"><div class="mc-ms-top"><b>${esc(m.title)}</b>${chip(ST[m.status])}${late(m) ? chip(["bad", "Late"]) : ""}<span class="faint small">${icon("calendar")}${day(a)} – ${day(b)}</span>
            ${o ? `<span class="small">${av(o, "xs")} ${esc(o.name)}</span>` : ""}${n ? `<span class="faint small">· ${plural(n, "task")} done in this window</span>` : ""}</div>
            ${m.detail ? `<p class="small">${esc(m.detail)}</p>` : ""}</div>
          <div class="mc-ms-act"><select data-mcmst="${m.id}" aria-label="Status of ${esc(m.title)}">${Object.entries(ST).map(([k, [, l]]) => `<option value="${k}" ${m.status === k ? "selected" : ""}>${l}</option>`).join("")}</select>
            <button type="button" class="iconbtn" data-mcmedit="${m.id}" aria-label="Edit ${esc(m.title)}" title="Edit">${icon("edit")}</button>
            <button type="button" class="iconbtn mw-danger" data-mcmdel="${m.id}" aria-label="Delete ${esc(m.title)}" title="Delete">${icon("trash")}</button></div></li>`; }).join("")}</ol>
      <p class="faint small">Agents read the milestone in progress (or the first one not done) and the next one before they work.</p></div>`;
  }
  function msForm(m) {
    const v = V(), dlg = dialog();
    dlg.innerHTML = `<form class="hq-dlg-in mh-new" data-mcform="ms" data-id="${m?.id || ""}" autocomplete="off">${X}
      <h3>${icon("flag")} ${m ? "Edit the milestone" : "New milestone"} <span class="faint small">${esc(v.comp.label)}</span></h3>
      <label class="in"><span>Milestone</span><input name="title" required minlength="2" maxlength="160" value="${esc(m?.title || "")}" placeholder="e.g. A baseline agent that passes the practice set"></label>
      <label class="in"><span>What done looks like <em class="opt">optional</em></span><textarea name="detail" rows="3" maxlength="2000">${esc(m?.detail || "")}</textarea></label>
      <div class="mh-row3"><label class="in"><span>Starts <em class="opt">optional</em></span><input name="starts" type="date" value="${esc(m?.starts || "")}"></label>
        <label class="in"><span>Due</span><input name="due" type="date" value="${esc(m?.due || "")}"></label>
        <label class="in"><span>Status</span><select name="status">${[["todo", "To do"], ["doing", "In progress"], ["done", "Done"]].map(([k, l]) => `<option value="${k}" ${(m?.status || "todo") === k ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <label class="in"><span>Owner <em class="opt">optional</em></span><select name="agent"><option value="">Nobody in particular</option>${v.agents.map(a => `<option value="${a.id}" ${m?.agent === a.id ? "selected" : ""}>${esc(a.name)} · ${esc(a.title)}</option>`).join("")}</select></label>
      <div class="row end">${m ? `<button type="button" class="btn mw-danger" data-mcmdel="${m.id}">${icon("trash")}Delete</button><span class="grow"></span>` : ""}<button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("check")}Save</button></div></form>`;
    dlg.showModal(); $("[name=title]", dlg).focus();
  }

  // ---------- Prompts ----------
  function loadPrompts(reset = true) {
    const v = V(); if (!v || P.loading) return;
    if (P.wid !== v.comp.id) { Object.assign(P, { wid: v.comp.id, entries: [], sel: new Set(), all: false, agents: new Set(), open: new Set(), full: {}, at: 0 }); }
    const before = reset ? 0 : P.entries.at(-1)?.id || 0;
    P.loading = true;
    const qs = new URLSearchParams({ agents: [...P.agents].join(","), kind: P.kind, q: P.q, limit: 60, ...(before ? { before } : {}) });
    api(`${W}/comps/${v.comp.id}/prompts?${qs}`).then(r => {
      P.entries = reset ? r.entries : [...P.entries, ...r.entries]; P.total = r.total; P.more = r.more; P.failed = ""; P.at = Date.now();
      if (reset) { const ids = new Set(P.entries.map(e => e.id)); P.sel = new Set([...P.sel].filter(i => ids.has(i))); }
    }).catch(e => { P.failed = e.message; P.at = Date.now(); }).finally(() => { P.loading = false; MiningWork.rerender(); });
  }
  const KINDS = [["", "All"], ["task", "Tasks"], ["review", "Reviews"], ["plan", "Plans"], ["user", "From you"], ["kept", "Remembered"]];
  const KCHIP = { task: ["run", "Task"], review: ["ok", "Review"], plan: ["wait", "Plan"], user: ["warn", "From you"] };
  function prompts(v) {
    need(v);
    if (P.wid !== v.comp.id || (!P.at && !P.loading) || (Date.now() - P.at > 20000 && !P.loading && !P.sel.size && !P.open.size)) loadPrompts();
    const A = AG(), counts = cs?.prompts || {}, n = P.sel.size, allShown = P.entries.length && P.entries.every(e => P.sel.has(e.id));
    const picked = [...P.agents].map(id => A[id]).filter(Boolean);
    const agents = `<aside class="mc-pa"><div class="mc-pa-h"><label class="mh-check"><input type="checkbox" data-mcpagall ${!P.agents.size ? "checked" : ""}><span><b>Everyone</b> <span class="faint small">${cs ? entries(cs.prompts_total) : ""}</span></span></label></div>
      <ul>${v.agents.map(a => { const c = counts[a.id] || {};
        return `<li><label class="mh-check ${P.agents.has(a.id) ? "on" : ""}"><input type="checkbox" data-mcpag="${a.id}" ${P.agents.has(a.id) ? "checked" : ""}>${av(a, "xs")}<span class="mc-pa-n"><b>${esc(a.name)}</b><span class="faint small">${c.n || 0}${c.waiting ? ` · ${c.waiting} unread` : ""}${c.kept ? ` · ${c.kept} kept` : ""}</span></span></label></li>`; }).join("")}</ul></aside>`;
    const rows = P.entries.map(e => { const a = A[e.agent], open = P.open.has(e.id), full = P.full[e.id] || e;
      return `<li class="mc-pe ${P.sel.has(e.id) ? "sel" : ""} k-${e.kind}"><div class="mc-pe-row">
        <input type="checkbox" data-mcpsel="${e.id}" ${P.sel.has(e.id) ? "checked" : ""} aria-label="Select this entry">
        <button type="button" class="mc-pe-main" data-mcpopen="${e.id}" aria-expanded="${open}">${av(a, "xs")}<span class="mc-pe-t"><b>${esc(e.title || "(untitled)")}</b>
          <span class="faint small">${a ? esc(a.name) : "a former teammate"} · <time data-ts="${e.ts}" title="${stamp(e.ts)}"></time>${e.tokens ? ` · ${short(e.tokens)} tokens` : ""}${e.by_user ? ` · by ${esc(e.by_user)}` : ""}${e.edited ? " · edited" : ""}</span></span>
          ${chip(KCHIP[e.kind] || ["none", e.kind])}${e.kind === "user" && !e.seen ? chip(["warn", "Not read yet"]) : ""}${e.status === "failed" ? chip(["bad", "Failed"]) : ""}${e.keep ? `<span class="mc-kept" title="Remembered: the agent reads it in every run">${icon("pin")}</span>` : ""}</button></div>
        ${open ? `<div class="mc-pe-body">
          ${full.system ? `<details><summary>System prompt</summary><pre>${esc(full.system)}</pre></details>` : ""}
          <b class="small">${e.kind === "user" ? "Your message" : "Prompt"}</b><pre>${esc(full.prompt)}</pre>
          ${e.kind === "user" ? "" : `<b class="small">Reply</b><pre>${esc(full.reply || "(none)")}</pre>`}
          ${e.cut && !P.full[e.id] ? `<button type="button" class="linkbtn" data-mcpfull="${e.id}">Show all of it</button>` : ""}
          <div class="row"><button type="button" class="btn sm" data-mcpedit="${e.id}">${icon("edit")}Edit</button>
            <button type="button" class="btn sm" data-mcpkeep="${e.id}">${icon("pin")}${e.keep ? "Forget" : "Remember"}</button>
            ${e.task ? `<button type="button" class="btn sm" data-mwtask="${e.task}">${icon("note")}Task</button>` : ""}
            <button type="button" class="btn sm mw-danger" data-mcpdel="${e.id}">${icon("trash")}Delete</button></div></div>` : ""}</li>`; }).join("");
    const canAll = !P.kind && !P.q && P.total > P.entries.length;
    return `<p class="faint small mw-note">Every run's prompt and reply, and your messages. An agent re-reads your messages it hasn't seen, the entries you remember and its latest replies before it works: what you edit or delete here is what it remembers.</p>
      <div class="mc-prompts">${agents}<section class="mc-pl">
        <div class="mc-pl-bar"><div class="seg" role="tablist">${KINDS.map(([k, l]) => `<button type="button" data-mcpkind="${k}" aria-pressed="${P.kind === k}">${l}</button>`).join("")}</div>
          <input type="search" data-mcpq data-hold value="${esc(P.q)}" placeholder="Search prompts and replies" aria-label="Search the histories">
          <button type="button" class="btn sm primary" data-mcwrite="${picked.length === 1 ? picked[0].id : ""}">${icon("send")}Write${picked.length ? ` to ${picked.length === 1 ? esc(picked[0].name) : plural(picked.length, "agent")}` : " to everyone"}</button></div>
        <div class="mc-sel-bar ${n || P.all ? "on" : ""}"><label class="mh-check"><input type="checkbox" data-mcpselall ${allShown ? "checked" : ""} ${P.entries.length ? "" : "disabled"}><span>${P.all ? `All ${P.total} selected` : n ? `${n} selected` : "Select all shown"}</span></label>
          ${canAll && allShown && !P.all ? `<button type="button" class="linkbtn" data-mc="pall">Select all ${P.total}${P.agents.size ? ` of ${plural(P.agents.size, "agent")}` : ""}</button>` : ""}
          ${n || P.all ? `<span class="row"><button type="button" class="btn sm" data-mcpbulk="keep">${icon("pin")}Remember</button><button type="button" class="btn sm" data-mcpbulk="forget">Forget</button>
            <button type="button" class="btn sm" data-mcpbulk="export">${icon("download")}Export</button><button type="button" class="btn sm mw-danger" data-mcpbulk="delete">${icon("trash")}Delete</button>
            <button type="button" class="linkbtn" data-mc="pnone">Clear the selection</button></span>` : `<span class="faint small">${P.total ? `${P.total} shown by this filter` : ""}</span>`}</div>
        ${P.failed ? `<p class="mh-err small">${esc(P.failed)}</p>` : ""}
        ${rows ? `<ol class="mc-pes">${rows}</ol>` : P.loading ? Loading.line("Reading the histories…") : `<div class="empty small">${P.kind || P.q || P.agents.size ? "Nothing matches." : "No history yet. Every run an agent makes lands here; so does what you write to them."}</div>`}
        ${P.more ? `<button type="button" class="btn sm" data-mc="pmore" ${P.loading ? "disabled" : ""}>Show more</button>` : ""}</section></div>`;
  }
  function writeForm(aid) {
    const v = V(), dlg = dialog(), pre = aid != null && aid !== "" ? new Set([+aid]) : P.agents.size ? new Set(P.agents) : new Set();
    dlg.innerHTML = `<form class="hq-dlg-in mh-new mc-write" data-mcform="write" autocomplete="off">${X}
      <h3>${icon("send")} Write a prompt <span class="faint small">${esc(v.comp.label)}</span></h3>
      <fieldset class="mc-to"><legend>To</legend><label class="mh-check"><input type="checkbox" name="all" ${pre.size ? "" : "checked"}><span><b>Every agent on the team</b> <span class="faint">(${v.agents.filter(a => a.on).length} switched on)</span></span></label>
        <div class="mc-to-l" ${pre.size ? "" : "hidden"}>${v.agents.map(a => `<label class="mh-check"><input type="checkbox" name="to" value="${a.id}" ${pre.has(a.id) ? "checked" : ""}>${av(a, "xs")}<span>${esc(a.name)}${a.on ? "" : " (off)"}</span></label>`).join("")}</div></fieldset>
      <fieldset class="mc-mode"><legend>As</legend><label class="mh-check"><input type="radio" name="mode" value="note" checked><span><b>A message for their next run</b> <span class="faint">they read it before they next work</span></span></label>
        <label class="mh-check"><input type="radio" name="mode" value="task"><span><b>A task they start now</b> <span class="faint">one task for each of them, on the board</span></span></label></fieldset>
      <div class="mc-taskf" hidden><div class="mh-row3"><label class="in mc-wide"><span>Task title <em class="opt">the first line otherwise</em></span><input name="title" maxlength="160"></label>
        <label class="in"><span>Priority</span><select name="priority"><option value="high">High</option><option value="medium" selected>Medium</option><option value="low">Low</option></select></label></div></div>
      <label class="in"><span>Prompt</span><textarea name="text" rows="6" required maxlength="8000" placeholder="e.g. From now on, test every change on the ClickHouse practice tasks before you file it."></textarea></label>
      <label class="mh-check"><input type="checkbox" name="keep"><span>Remember it <span class="faint">they re-read it in every run until you forget it</span></span></label>
      <div class="row end"><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("send")}Send</button></div></form>`;
    dlg.showModal(); $("[name=text]", dlg).focus();
  }
  async function editForm(id) {
    const v = V(), dlg = dialog();
    dlg.innerHTML = `<div class="hq-dlg-in">${X}${Loading.line("Opening the entry…")}</div>`; dlg.showModal();
    let e; try { e = (await api(`${W}/prompts/${id}`)).entry; } catch (er) { dlg.close(); return err(er); }
    P.full[id] = e;
    const a = AG()[e.agent];
    dlg.innerHTML = `<form class="hq-dlg-in mh-new mc-edit" data-mcform="pedit" data-id="${id}">${X}
      <div class="hq-dlg-head">${av(a, "lg")}<div><h3>${esc(e.title || "History entry")}</h3><div class="faint">${a ? esc(a.name) : "a former teammate"} · ${stamp(e.ts)}${e.edited ? " · edited" : ""}</div></div></div>
      <p class="faint small">${e.kind === "user" ? "Your message: the agent reads it in its next run (and in every run, if you remember it)." : `${esc(a?.name || "The agent")} re-reads its latest replies and the ones you remember: change the reply to change what it remembers.`}</p>
      ${e.kind === "user" ? "" : `<label class="in"><span>System prompt</span><textarea name="system" rows="5" maxlength="60000">${esc(e.system)}</textarea></label>`}
      <label class="in"><span>${e.kind === "user" ? "Message" : "Prompt"}</span><textarea name="prompt" rows="${e.kind === "user" ? 6 : 8}" maxlength="60000">${esc(e.prompt)}</textarea></label>
      ${e.kind === "user" ? "" : `<label class="in"><span>Reply</span><textarea name="reply" rows="8" maxlength="60000">${esc(e.reply)}</textarea></label>`}
      <label class="mh-check"><input type="checkbox" name="keep" ${e.keep ? "checked" : ""}><span>Remember it <span class="faint">read in every run</span></span></label>
      <div class="row end"><button type="button" class="btn mw-danger" data-mcpdel="${id}">${icon("trash")}Delete</button><span class="grow"></span><button type="button" class="btn" data-close>Cancel</button><button type="submit" class="btn primary">${icon("check")}Save</button></div></form>`;
  }
  function selection() {
    if (P.all) return P.agents.size ? { agents: [...P.agents] } : { all: true };
    return { ids: [...P.sel] };
  }
  async function bulk(action, btn) {
    const v = V(), n = P.all ? P.total : P.sel.size; if (!n) return;
    const send = () => api(`${W}/comps/${v.comp.id}/prompts/bulk`, { method: "POST", body: { ...selection(), action } });
    if (action === "export") {
      const r = await busy(btn, send); if (!r) return;
      download(`${v.comp.label}-prompts.md`, historyMd(v, r.entries));
      return Auth.toast(`Exported ${entries(r.entries.length)}`);
    }
    const go = async () => { const r = await send(); P.sel.clear(); P.all = false; fresh(); loadPrompts(); need(v); Auth.toast(`${action === "delete" ? "Deleted" : action === "keep" ? "Remembered" : "Forgotten"}: ${r.changed}`); };
    if (action === "delete") return UI.confirm({ title: `Delete ${entries(n, "history ")}?`, body: "The agents stop remembering them. Tasks, results and traces stay. This can't be undone.", ok: "Delete", run: go }).catch(err);
    await busy(btn, go);
  }
  function historyMd(v, list) {
    return [`# ${v.comp.label}: prompt histories`, "", `Exported ${new Date().toLocaleString()}, ${list.length} entries.`, "",
      ...list.flatMap(e => [`## ${e.agent_name}: ${e.title || e.kind} (${new Date(e.ts * 1000).toLocaleString()})`, "", `*${e.kind}${e.keep ? ", remembered" : ""}${e.tokens ? `, ${e.tokens} tokens` : ""}*`, "",
        ...(e.system ? ["### System prompt", "", "```", e.system, "```", ""] : []), `### ${e.kind === "user" ? "Message" : "Prompt"}`, "", "```", e.prompt, "```", "",
        ...(e.kind === "user" ? [] : ["### Reply", "", e.reply || "(none)", ""])])].join("\n");
  }
  function download(name, text) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" })); a.download = name.replace(/[^\w.-]+/g, "-");
    document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // ---------- Levels ----------
  let lsort = "xp";
  function levels(v) {
    need(v);
    if (!cs) return loading();
    const L = cs.levels, rows = v.agents.filter(a => L[a.id]).map(a => ({ a, r: L[a.id] }));
    const key = { xp: x => x.r.level.xp, done: x => x.r.done, approval: x => x.r.approval ?? -1, reviews: x => x.r.reviews, hours: x => x.r.hours, tokens: x => x.r.tokens, days: x => x.r.days }[lsort] || (x => x.r.level.xp);
    rows.sort((x, y) => key(y) - key(x) || x.a.id - y.a.id);
    const top = rows[0], sum = k => rows.reduce((s, x) => s + (x.r[k] || 0), 0);
    const th = (k, l) => `<th><button type="button" class="linkbtn ${lsort === k ? "on" : ""}" data-mclsort="${k}">${l}${lsort === k ? " ↓" : ""}</button></th>`;
    return `<div class="mc-levels">
      <div class="mc-lv-tiles"><div class="hq-tile"><b>${rows.length}</b><span>engineers</span></div><div class="hq-tile"><b>${fmtNum(sum("done"), 0)}</b><span>tasks done</span></div>
        <div class="hq-tile"><b>${fmtNum(sum("notes"), 0)}</b><span>findings approved</span></div><div class="hq-tile"><b>${fmtNum(sum("hours"), 1)} h</b><span>worked</span></div>
        ${top ? `<div class="hq-tile ok"><b>${esc(top.a.name)}</b><span>${lsort === "xp" ? "most experienced" : "top of this column"}</span></div>` : ""}</div>
      <div class="mc-lv-scroll"><table class="mc-lv"><thead><tr><th>Engineer</th>${th("xp", "Level")}${th("done", "Done")}${th("approval", "First-time")}<th>Findings</th>${th("reviews", "Reviews")}<th>Plans</th><th>Failed</th>${th("hours", "Hours")}${th("tokens", "Tokens")}${th("days", "On the team")}<th>Most used</th></tr></thead>
        <tbody>${rows.map(({ a, r }) => `<tr class="${a.on ? "" : "off"}"><td><button type="button" class="mc-lv-who" data-mwedit="${a.id}">${av(a, "xs")}<span><b>${esc(a.name)}</b><span class="faint small">${esc(a.title)}${a.lead ? " · Director" : a.head ? " · squad lead" : ""}</span></span></button></td>
          <td><span class="mc-lv-l">${badge(a.id)}<span>${esc(r.level.name)}<span class="mc-xp-bar"><i style="--w:${(r.level.progress * 100).toFixed(0)}%"></i></span><span class="faint small">${fmtNum(r.level.xp, 0)} XP</span></span></span></td>
          <td>${r.done}</td><td>${r.approval == null ? "–" : `${fmtNum(r.approval * 100, 0)}%`}</td><td>${r.notes}</td><td>${r.reviews}</td><td>${r.plans}</td><td class="${r.failed ? "mw-late" : ""}">${r.failed}</td>
          <td>${fmtNum(r.hours, r.hours < 10 ? 1 : 0)}</td><td>${short(r.tokens)}</td><td>${r.days ? plural(r.days, "day") : "new"}</td>
          <td class="small">${r.tools.length ? r.tools.slice(0, 3).map(([t, n]) => `<code>${esc(t)}</code> ×${n}`).join(", ") : `<span class="faint">–</span>`}</td></tr>`).join("")}</tbody></table></div>
      <details class="mc-ladder"><summary>How levels work</summary><p class="small">Experience comes from the work on this team: ${Object.entries({ done: "a task done", note: "a finding approved into the notebook", first_time: "approved without being sent back", review: "a review", plan: "a plan", run: "a finished task run", failed: "a failed run" }).map(([k, l]) => `${l} ${cs.xp[k] > 0 ? "+" : ""}${cs.xp[k]}`).join(" · ")} XP.</p>
        <ol class="mc-ladder-l">${cs.ladder.map((l, i) => `<li><span class="mc-lvl l-${i + 1}">L${i + 1}</span>${esc(l.name)} <span class="faint small">from ${fmtNum(l.floor, 0)} XP</span></li>`).join("")}</ol></details></div>`;
  }

  // ---------- Links ----------
  const HUBS = [
    ["source", "Source", "github", "source", "The repository the team's code goes to.", "/api/source"],
    ["drive", "Drive", "folder", "drive", "Where the notebook and the prompt histories are saved.", "/api/drive/status"],
    ["devops", "DevOps", "rocket", "devops", "The pipeline that builds, tests and deploys the team's code.", "/api/devops"],
    ["cluster", "Cluster", "server", "cluster", "The deployment the team's work runs as.", "/api/cluster"],
    ["app", "Apps", "apps", "apps", "Apps the team's work serves.", "/api/platform/apps"],
    ["function", "Functions", "zap", "functions", "Functions the team's work calls.", "/api/platform/functions"]];
  function hub(kind, url) {
    const h = H[kind];
    if (h && (h.loading || Date.now() - h.at < 60000)) return h;
    H[kind] = { ...(h || {}), loading: true };
    api(url).then(d => { H[kind] = { at: Date.now(), data: d }; }).catch(e => { H[kind] = { at: Date.now(), error: e.message, status: e.status }; }).finally(() => MiningWork.rerender());
    return H[kind];
  }
  function options(kind, d) {  // what you can link, from the hub's own list: [ref, label, url, state]
    if (!d) return [];
    if (kind === "source") return (d.repos || []).map(r => [r.repo, r.repo, r.url || "#source", r.error ? ["bad", "Error"] : r.last_run ? [r.last_run.conclusion === "success" ? "ok" : r.last_run.conclusion ? "bad" : "run", r.last_run.conclusion || r.last_run.status] : ["none", "No CI runs"],
      `${r.open_prs || 0} open PRs${r.pushed ? ` · pushed ${ago(Date.parse(r.pushed) / 1000)}` : ""}`]);
    if (kind === "devops") return (d.pipelines || []).map(p => [String(p.id), p.app, "#devops", p.last ? [p.last.status === "success" ? "ok" : ["failed", "error"].includes(p.last.status) ? "bad" : "run", p.last.status] : ["none", "Never run"], `${p.repo} · ${p.branch}`]);
    if (kind === "cluster") return (d.namespaces || []).flatMap(n => n.deployments.map(x => [`${n.name}/${x.name}`, `${x.name} (${n.name})`, "#cluster", x.failed ? ["bad", "Failed"] : x.ready >= x.replicas ? ["ok", `${x.ready}/${x.replicas} ready`] : ["warn", `${x.ready}/${x.replicas} ready`], (x.images || [])[0] || ""]));
    if (kind === "app" || kind === "function") return (Array.isArray(d) ? d : d.items || []).map(x => [x.name, x.name, x.url || `#${kind === "app" ? "apps" : "functions"}`, [x.status === "running" ? "ok" : x.status === "failed" ? "bad" : "warn", x.status || "?"], x.url || x.runtime || x.image || ""]);
    return [];
  }
  function links(v) {
    need(v);
    if (!cs) return loading();
    const cards = HUBS.map(([kind, title, ic, view, about, url]) => {
      const h = hub(kind, url), mine = cs.links.filter(l => l.kind === kind), opts = options(kind, h.data), byRef = Object.fromEntries(opts.map(o => [o[0], o]));
      const denied = h.status === 403, off = kind === "drive" ? h.data && !h.data.enabled : kind === "source" ? h.data && !h.data.configured : false;
      const linked = mine.map(l => { const o = byRef[l.ref];
        return `<li>${o ? chip(o[3]) : kind === "drive" ? chip(["ok", "Folder"]) : h.data && !off ? chip(["bad", "Gone"]) : ""}<a href="${esc(l.url || `#${view}`)}" ${l.url?.startsWith("http") ? `target="_blank" rel="noopener noreferrer"` : `data-mcgo="${view}"`}>${esc(l.label || l.ref)}</a>
          ${o?.[4] ? `<span class="faint small">${esc(o[4])}</span>` : ""}<button type="button" class="iconbtn" data-mcunlink="${l.id}" aria-label="Unlink ${esc(l.label || l.ref)}" title="Unlink">${icon("close")}</button></li>`; }).join("");
      const free = opts.filter(o => !mine.some(l => l.ref === o[0]));
      const picker = kind === "drive" ? (h.data?.enabled ? `<div class="row"><button type="button" class="btn sm" data-mcdrive="notebook">${icon("upload")}Save the notebook</button><button type="button" class="btn sm" data-mcdrive="prompts">${icon("upload")}Save the prompt histories</button></div>` : "")
        : free.length ? `<form class="mc-link-f" data-mclink="${kind}"><select name="ref" aria-label="Pick one to link">${free.map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("")}</select><button type="submit" class="btn sm">${icon("link")}Link</button></form>` : "";
      const state = h.loading && !h.data && !h.error ? `<p class="faint small">${icon("cycle")}Reading ${title}…</p>` : denied ? `<p class="faint small">${icon("lock")}${title} is for administrators: ask one to link it, or open it if you are one.</p>`
        : h.error ? `<p class="mh-err small">${esc(h.error)}</p>` : off ? `<p class="faint small">${icon("info")}${kind === "drive" ? (h.data.error || "Drive isn't connected.") : "GitHub isn't connected in Source."}</p>`
        : !opts.length && kind !== "drive" ? `<p class="faint small">Nothing in ${title} yet.</p>` : "";
      return `<section class="mh-card mc-hub"><h3>${icon(ic)}${title}<button type="button" class="linkbtn" data-mcgo="${view}">Open ${title}</button></h3><p class="faint small">${about}</p>
        ${linked ? `<ul class="mc-linked">${linked}</ul>` : ""}${state}${denied || off ? "" : picker}</section>`;
    }).join("");
    return `<p class="faint small mw-note">What the team works with elsewhere in AXoR. Each card shows the live state from its own page; agents read the list of what's linked.</p><div class="mc-hubs">${cards}</div>`;
  }
  async function toDrive(what, btn) {
    const v = V();
    await busy(btn, async () => {
      let name, text, folder;
      if (what === "notebook") ({ name, text, folder } = await api(`${W}/comps/${v.comp.id}/notebook.md`));
      else {
        const r = await api(`${W}/comps/${v.comp.id}/prompts/bulk`, { method: "POST", body: { all: true, action: "export" } });
        folder = `SN${v.campaign.netuid} ${v.comp.label}`.slice(0, 80); name = `${folder.replace(/[^\w.-]+/g, "-")}-prompts.md`; text = historyMd(v, r.entries);
      }
      const dir = await api("/api/drive/folders/ensure", { method: "POST", body: { space: "mine", path: ["Competition teams", folder] } });
      const res = await fetch(`/api/drive/files?${new URLSearchParams({ space: "mine", name, parent: dir.id })}`, { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "scout", "Content-Type": "text/markdown" }, body: text });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Drive didn't take the file.");
      if (!cs.links.some(l => l.kind === "drive" && l.ref === dir.id)) set(await api(`${W}/comps/${v.comp.id}/links`, { method: "POST", body: { kind: "drive", ref: dir.id, label: `Competition teams / ${folder}`, url: "#drive" } }));
      Auth.toast(`Saved ${name} to Drive`);
    });
  }

  // ---------- Desk: the team's views side by side ----------
  const DESK = [["board", "Board", "list", 4], ["diagram", "Diagram", "route", 6], ["roadmap", "Roadmap", "map", 2], ["team", "Team", "users", 3], ["levels", "Levels", "trophy", 3],
    ["prompts", "Prompts", "chat", 6], ["notes", "Notebook", "book", 3], ["activity", "Activity", "clock", 3], ["links", "Links", "link", 6], ["sandbox", "Sandbox", "terminal", 6]];
  const PRESETS = [
    { id: "control", label: "Control room", layout: { order: ["diagram", "board", "roadmap", "activity", "levels"], size: { diagram: 6, board: 4, roadmap: 2, activity: 3, levels: 3 }, hide: ["team", "prompts", "notes", "links", "sandbox"] } },
    { id: "plan", label: "Planning", layout: { order: ["roadmap", "board", "notes"], size: { roadmap: 6, board: 4, notes: 2 }, hide: ["diagram", "team", "levels", "prompts", "activity", "links", "sandbox"] } },
    { id: "people", label: "People", layout: { order: ["levels", "team", "prompts"], size: { levels: 3, team: 3, prompts: 6 }, hide: ["diagram", "board", "roadmap", "notes", "activity", "links", "sandbox"] } },
    { id: "ops", label: "Operations", layout: { order: ["links", "sandbox", "activity"], size: { links: 4, sandbox: 2, activity: 6 }, hide: ["diagram", "board", "roadmap", "team", "levels", "prompts", "notes"] } }];
  function desk(v) {
    Flex.register("mw.desk", { render: () => MiningWork.rerender(), presets: PRESETS });
    const L = Flex.layout("mw.desk"), ed = Flex.editing("mw.desk");
    const view = { diagram, roadmap, prompts, levels, links };
    return Flex.grid("mw.desk", DESK.map(([k, title, ic, size]) => ({ k, title, icon: ic, size, head: true,
      html: L.hide.includes(k) && !ed ? "" : L.fold.includes(k) ? " " : view[k] ? view[k](v) : MiningWork.panel(k) })));
  }

  // ---------- dialogs and events ----------
  const X = `<button type="button" class="iconbtn hq-x" data-close aria-label="Close">${icon("close")}</button>`;
  function dialog() {
    let dlg = document.getElementById("mc-dlg");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "mc-dlg"; dlg.className = "modal mw-dlg mh-new-dlg"; document.body.append(dlg);
      dlg.addEventListener("click", dlgClick); dlg.addEventListener("submit", dlgSubmit); dlg.addEventListener("change", dlgChange);
    }
    return dlg;
  }
  async function dlgClick(e) {
    const dlg = e.currentTarget, t = e.target;
    if (t === dlg || t.closest("[data-close]")) return dlg.close();
    const md = t.closest("[data-mcmdel]"); if (md) { dlg.close(); return delMilestone(+md.dataset.mcmdel); }
    const pd = t.closest("[data-mcpdel]"); if (pd) { dlg.close(); return delEntry(+pd.dataset.mcpdel); }
  }
  function dlgChange(e) {
    const f = e.target.form; if (!f) return;
    if (f.dataset.mcform === "write") {
      if (e.target.name === "all") $(".mc-to-l", f).hidden = e.target.checked;
      if (e.target.name === "mode") $(".mc-taskf", f).hidden = f.elements.mode.value !== "task";
    }
  }
  async function dlgSubmit(e) {
    e.preventDefault();
    const f = e.target, dlg = e.currentTarget, btn = $("button[type=submit]", f), val = n => f.elements[n]?.value ?? "", v = V();
    const send = (path, body, method = "POST") => busy(btn, () => api(`${W}${path}`, { method, body }));
    if (f.dataset.mcform === "ms") {
      const body = { title: val("title").trim(), detail: val("detail"), starts: val("starts"), due: val("due"), status: val("status") };
      const id = f.dataset.id, ag = val("agent");
      const s = id ? await send(`/milestones/${id}`, { ...body, ...(ag === "" ? { unassign: true } : { agent: +ag }) }, "PATCH") : await send(`/comps/${v.comp.id}/roadmap`, { ...body, agent: ag === "" ? null : +ag });
      if (s) { dlg.close(); set(s); Auth.toast("Saved"); } return;
    }
    if (f.dataset.mcform === "write") {
      const all = f.elements.all.checked, to = all ? [] : $$("[name=to]:checked", f).map(x => +x.value);
      if (!all && !to.length) return Auth.toast("Pick at least one agent");
      const mode = f.elements.mode.value;
      const r = await send(`/comps/${v.comp.id}/prompts`, { agents: to, text: val("text"), mode, title: val("title"), priority: val("priority"), keep: f.elements.keep.checked });
      if (!r) return;
      dlg.close(); fresh(); P.at = 0; MiningWork.reload();
      Auth.toast(mode === "task" ? `${plural(r.tasks, "task")} started` : `Sent to ${plural(r.written, "agent")}: they read it in their next run`); return;
    }
    if (f.dataset.mcform === "pedit") {
      const id = +f.dataset.id, body = { prompt: val("prompt"), keep: f.elements.keep.checked };
      if (f.elements.system) Object.assign(body, { system: val("system"), reply: val("reply") });
      const r = await send(`/prompts/${id}`, body, "PATCH");
      if (r) { dlg.close(); P.full[id] = r.entry; const i = P.entries.findIndex(x => x.id === id); if (i >= 0) P.entries[i] = { ...P.entries[i], ...r.entry, cut: false }; fresh(); MiningWork.rerender(); Auth.toast("Saved: that's what the agent remembers now"); }
    }
  }
  function delMilestone(id) {
    const m = cs?.roadmap.find(x => x.id === id); if (!m) return;
    return UI.confirm({ title: `Delete the milestone “${esc(m.title)}”?`, body: "Tasks stay on the board.", ok: "Delete", run: async () => set(await api(`${W}/milestones/${id}`, { method: "DELETE" })) }).catch(err);
  }
  function delEntry(id) {
    return UI.confirm({ title: "Delete this history entry?", body: "The agent stops remembering it. The task, its result and its trace stay.", ok: "Delete",
      run: async () => { await api(`${W}/prompts/${id}`, { method: "DELETE" }); P.entries = P.entries.filter(x => x.id !== id); P.sel.delete(id); P.total = Math.max(0, P.total - 1); fresh(); MiningWork.rerender(); } }).catch(err);
  }

  function wire(el) {
    if (wired || !el) return; wired = true;
    el.addEventListener("click", async e => {
      const t = e.target, v = V(); if (!v) return;
      const n = t.closest("[data-mcn]"); if (n && !D.moved) { const id = +n.dataset.mcn; D.sel = D.sel === id ? null : id; return MiningWork.rerender(); }
      const z = t.closest("[data-mcz]"); if (z) return +z.dataset.mcz ? zoom(+z.dataset.mcz > 0 ? 1.2 : 1 / 1.2) : fit();
      const w = t.closest("[data-mcwrite]"); if (w) return writeForm(w.dataset.mcwrite);
      const hi = t.closest("[data-mchist]"); if (hi) { P.agents = new Set([+hi.dataset.mchist]); P.sel.clear(); P.all = false; P.at = 0; return MiningWork.go("prompts"); }
      const st = t.closest("[data-mcstart]"); if (st) { const nv = await busy(st, () => api(`${W}/tasks/${st.dataset.mcstart}/start`, { method: "POST", body: {} })); if (nv) { MiningWork.apply(nv); Auth.toast("Started"); } return; }
      const ca = t.closest("[data-mccancel]"); if (ca) { const nv = await busy(ca, () => api(`${W}/tasks/${ca.dataset.mccancel}/cancel`, { method: "POST" })); if (nv) { MiningWork.apply(nv); Auth.toast("Stopping"); } return; }
      const me = t.closest("[data-mcmedit]"); if (me) return msForm(cs?.roadmap.find(x => x.id === +me.dataset.mcmedit));
      const md = t.closest("[data-mcmdel]"); if (md) return delMilestone(+md.dataset.mcmdel);
      const pk = t.closest("[data-mcpkind]"); if (pk) { P.kind = pk.dataset.mcpkind; P.sel.clear(); P.all = false; return loadPrompts(); }
      const po = t.closest("[data-mcpopen]"); if (po) { const id = +po.dataset.mcpopen; P.open.has(id) ? P.open.delete(id) : P.open.add(id); return MiningWork.rerender(); }
      const pf = t.closest("[data-mcpfull]"); if (pf) { const id = +pf.dataset.mcpfull; const r = await busy(pf, () => api(`${W}/prompts/${id}`)); if (r) { P.full[id] = r.entry; MiningWork.rerender(); } return; }
      const pe = t.closest("[data-mcpedit]"); if (pe) return editForm(+pe.dataset.mcpedit);
      const pkp = t.closest("[data-mcpkeep]");
      if (pkp) { const id = +pkp.dataset.mcpkeep, e0 = P.entries.find(x => x.id === id); const r = await busy(pkp, () => api(`${W}/prompts/${id}`, { method: "PATCH", body: { keep: !e0?.keep } }));
        if (r) { Object.assign(e0, { keep: r.entry.keep }); fresh(); MiningWork.rerender(); Auth.toast(r.entry.keep ? "Remembered: read in every run" : "Forgotten"); } return; }
      const pd = t.closest("[data-mcpdel]"); if (pd) return delEntry(+pd.dataset.mcpdel);
      const pb = t.closest("[data-mcpbulk]"); if (pb) return bulk(pb.dataset.mcpbulk, pb);
      const ls = t.closest("[data-mclsort]"); if (ls) { lsort = ls.dataset.mclsort; return MiningWork.rerender(); }
      const gv = t.closest("[data-mcgo]"); if (gv) { e.preventDefault(); return go(gv.dataset.mcgo); }
      const ul = t.closest("[data-mcunlink]"); if (ul) { const s = await busy(ul, () => api(`${W}/links/${ul.dataset.mcunlink}`, { method: "DELETE" })); if (s) set(s); return; }
      const dr = t.closest("[data-mcdrive]"); if (dr) return toDrive(dr.dataset.mcdrive, dr);
      const b = t.closest("[data-mc]"); if (!b) return;
      const k = b.dataset.mc;
      if (k === "flow") { D.flow = !D.flow; return MiningWork.rerender(); }
      if (k === "relayout") { D.live = {}; cs.layout = {}; D.fitted = false; api(`${W}/comps/${v.comp.id}/layout`, { method: "PUT", body: { pos: {} } }).catch(err); return MiningWork.rerender(); }
      if (k === "seed") { const s = await busy(b, () => api(`${W}/comps/${v.comp.id}/roadmap/seed`, { method: "POST" })); if (s) { set(s); Auth.toast("Roadmap ready: agents work toward its current milestone"); } return; }
      if (k === "reseed") return UI.confirm({ title: "Start the roadmap over?", body: "Every milestone goes and the default roadmap takes its place.", ok: "Start over", icon: "reset",
        run: async () => set(await api(`${W}/comps/${v.comp.id}/roadmap/seed?replace=true`, { method: "POST" })) }).catch(err);
      if (k === "addms") return msForm(null);
      if (k === "pmore") return loadPrompts(false);
      if (k === "pall") { P.all = true; return MiningWork.rerender(); }
      if (k === "pnone") { P.sel.clear(); P.all = false; return MiningWork.rerender(); }
    });
    el.addEventListener("change", e => {
      const t = e.target;
      if (t.matches("[data-mcpsel]")) { const id = +t.dataset.mcpsel; t.checked ? P.sel.add(id) : P.sel.delete(id); P.all = false; return MiningWork.rerender(); }
      if (t.matches("[data-mcpselall]")) { P.all = false; if (t.checked) P.entries.forEach(x => P.sel.add(x.id)); else P.sel.clear(); return MiningWork.rerender(); }
      if (t.matches("[data-mcpagall]")) { P.agents.clear(); P.sel.clear(); P.all = false; return loadPrompts(); }
      if (t.matches("[data-mcpag]")) { const id = +t.dataset.mcpag; t.checked ? P.agents.add(id) : P.agents.delete(id); P.sel.clear(); P.all = false; return loadPrompts(); }
      if (t.matches("[data-mcmst]")) { const id = t.dataset.mcmst; busy(null, () => api(`${W}/milestones/${id}`, { method: "PATCH", body: { status: t.value } })).then(s => s && set(s)); }
    });
    el.addEventListener("submit", async e => {
      const f = e.target.closest("[data-mclink]"); if (!f) return;
      e.preventDefault();
      const kind = f.dataset.mclink, ref = f.elements.ref.value, o = options(kind, H[kind]?.data).find(x => x[0] === ref); if (!o) return;
      const s = await busy($("button", f), () => api(`${W}/comps/${V().comp.id}/links`, { method: "POST", body: { kind, ref, label: o[1], url: o[2] } }));
      if (s) { set(s); Auth.toast(`Linked ${o[1]}`); }
    });
    let qt = null;
    el.addEventListener("input", e => { if (!e.target.matches("[data-mcpq]")) return; clearTimeout(qt); qt = setTimeout(() => { P.q = e.target.value; P.sel.clear(); P.all = false; loadPrompts(); }, 300); });
    // the diagram: drag an agent to move it, drag the background to pan, Ctrl + wheel to zoom
    el.addEventListener("pointerdown", e => {
      const view = e.target.closest("[data-mcview]"); if (!view || e.button) return;
      const n = e.target.closest("[data-mcn]"), v = V();
      D.moved = false;
      if (n) { const k = n.dataset.mcn, p = positions(v).pos[k]; D.act = { kind: "node", k, sx: e.clientX, sy: e.clientY, p0: [...p] }; }
      else D.act = { kind: "pan", sx: e.clientX, sy: e.clientY, x0: D.x, y0: D.y };
      D.act.view = view; D.act.pid = e.pointerId;
    });
    el.addEventListener("pointermove", e => {
      const a = D.act; if (!a) return;
      const dx = e.clientX - a.sx, dy = e.clientY - a.sy;
      if (!D.moved && Math.hypot(dx, dy) < 4) return;
      if (!D.moved) a.view.setPointerCapture?.(a.pid);  // only once it moves: a plain click stays a click on the agent
      D.moved = true;
      if (a.kind === "node") D.live[a.k] = [Math.round(a.p0[0] + dx / D.z), Math.round(a.p0[1] + dy / D.z)];
      else { D.x = a.x0 + dx; D.y = a.y0 + dy; D.fitted = true; }
      paint();
    });
    const up = () => {
      const a = D.act; if (!a) return;
      D.act = null;
      if (D.moved && a.kind === "node") saveLayout();
      if (D.moved) { setTimeout(() => { D.moved = false; }, 0); MiningWork.rerender(); }
    };
    el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
    el.addEventListener("wheel", e => {
      const view = e.target.closest("[data-mcview]"); if (!view || !(e.ctrlKey || e.metaKey)) return;
      e.preventDefault(); const r = view.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
  }
  // while you drag on the diagram or type in a search box, the page's live updates wait
  const holding = () => !!D.act || !!document.activeElement?.closest?.("[data-hold]") && document.activeElement.matches("input, textarea");

  return { diagram, roadmap, prompts, levels, links, desk, badge, wire, holding, need };
})();
