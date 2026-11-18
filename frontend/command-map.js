/* The chain of command (mission_link.py's /api/mos/map), drawn in Mission Control (the overview and each mission) and on a
   Competition team's page in My subnets: you → Mission Control → your missions → the engines → (a Competition team) its Director →
   the squads' heads → the agents, with what each is doing right now, what waits for you, and what's missing (a team a mission
   needs and doesn't have yet, drawn dashed with the way to create it).
   A slot draws from its cache at once and refreshes itself in place (no page redraw, so typing elsewhere is never interrupted). */
const CommandMap = (() => {
  const TTL = 4000, cache = {};
  const ENGINE_ICON = { direct: "zap", workforce: "group", longtask: "route", mining: "trophy", swarm: "sparkle" };
  const ENGINE_NOTE = { direct: "one careful answer", workforce: "CEO, teams and reviewers: a report", longtask: "one agent with files and checkpoints",
    mining: "a Competition team does the work", swarm: "a temporary team of Workforce agents, checked and replanned" };
  const STATE = { working: "Working", queued: "Queued", idle: "Idle", off: "Switched off" };
  const STATUS = { queued: "run", running: "run", needs_input: "wait", paused: "warn", delivered: "ok", failed: "bad", cancelled: "off" };
  const money = x => `$${(x || 0) < 10 ? (x || 0).toFixed(2) : fmtNum(x || 0, 0)}`;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const isOpen = (k, def = true) => { try { const v = localStorage.getItem(`cmap.open.${k}`); return v == null ? def : v !== "0"; } catch { return def; } };
  const setOpen = (k, on) => { try { localStorage.setItem(`cmap.open.${k}`, on ? "1" : "0"); } catch { /* private window */ } };

  // ---------- data ----------
  function url(o) {
    const q = new URLSearchParams();
    if (o.mission != null) q.set("mission", o.mission);
    if (o.team != null) q.set("team", o.team);
    return `/api/mos/map${q.toString() ? `?${q}` : ""}`;
  }
  function load(key, o) {
    const c = cache[key] ||= { data: null, at: 0, busy: false, err: "" };
    if (c.busy || Date.now() - c.at < TTL) return;
    c.busy = true;
    api(url(o)).then(d => { c.data = d; c.err = ""; }).catch(e => { c.err = e.message; })
      .finally(() => { c.at = Date.now(); c.busy = false; paint(key, o); });
  }
  function paint(key, o) {
    $$(`[data-cmap-slot="${key}"]`).forEach(el => {
      if (el.contains(document.activeElement) && document.activeElement.matches("select, input")) return;
      el.innerHTML = body(cache[key], o); hydrateIcons(el);
    });
  }

  // ---------- drawing ----------
  /* A collapsible card holding the map. key: the cache key (one per place); o: {mission, team, title, toggle (shares the open
     state), closed (shut until opened once)}. */
  function slot(key, o = {}) {
    load(key, o);
    const open = isOpen(o.toggle || key, !o.closed);
    return `<section class="card cmap" aria-label="Chain of command"><details ${open ? "open" : ""} data-cmap-toggle="${esc(o.toggle || key)}">
      <summary><span class="cmap-title">${icon("route")}${esc(o.title || "Chain of command")}</span>
        <span class="cmap-legend" aria-hidden="true"><i class="s-working"></i>working<i class="s-queued"></i>queued<i class="s-idle"></i>idle<i class="s-missing"></i>missing</span></summary>
      <div class="cmap-slot" data-cmap-slot="${esc(key)}">${body(cache[key], o)}</div></details></section>`;
  }
  function body(c, o) {
    if (!c?.data) return c?.err ? `<p class="mh-err">${icon("alert")}${esc(c.err)}</p>` : Loading.line("Drawing the chain of command…");
    const d = c.data;
    return `<div class="cmap-chain">
      ${tier("you", you(d))}
      ${tier("mc", `<div class="cmap-node n-mc">${icon("target")}<div><b>Mission Control</b><small>understand · plan · pick the engine · verify · deliver</small></div></div>`)}
      ${tier("missions", missions(d, o))}
      ${tier("engines", engines(d))}
      ${teams(d, o)}
    </div>`;
  }
  const tier = (k, inner) => `<div class="cmap-tier t-${k}">${inner}</div>`;

  function you(d) {
    const n = d.you.requests;
    return `<div class="cmap-node n-you">${icon("star")}<div><b>You</b><small>the only one who creates teams and repos, approves, deploys, uploads and pays</small></div>
      ${n ? `<span class="cmap-chip t-wait">${plural(n, "request")} for you</span>` : ""}</div>`;
  }
  /* A predefined mission: a Competition team's own (Control Hub, comp:<id>). Its tasks go to the team's board through the
     Control Hub's dispatcher, researched first when a fixed task needs it; Mission Control's custom missions are drawn after. */
  function predefined(p) {
    const tone = p.running || p.working ? "run" : p.waiting ? "wait" : p.open ? "warn" : "off";
    const bits = [p.open ? `${plural(p.open, "open task")}${p.fixed ? ` (${p.fixed} fixed)` : ""}` : "no open task",
      p.running ? `${p.running} under way` : "", p.researching ? `${p.researching} being researched` : "", p.waiting ? `<em>${p.waiting} wait for you</em>` : ""].filter(Boolean);
    return `<button type="button" class="cmap-node n-mission t-${tone}" data-cmap-ref="${esc(p.ref)}" title="Open the mission in the Control Hub">
      ${icon("trophy")}<div><b>${esc(p.title)}</b><small>Predefined mission · runs on the team's board</small>
      <small class="cmap-meta">${bits.join(" · ")}</small></div></button>`;
  }
  function missions(d, o) {
    const pre = d.predefined || [];
    if (!d.missions.length && !pre.length) {
      return `<div class="cmap-node n-ghost">${icon("rocket")}<div><b>${o.team != null ? "No mission has run on this team" : "No mission running"}</b>
        <small>${o.team != null ? "Start one from here: it goes straight to this team." : "Start one in Mission Control: AXoR picks the engine."}</small></div></div>`;
    }
    return pre.map(predefined).join("") + d.missions.map(m => {
      const tone = STATUS[m.status] || "off";
      return `<button type="button" class="cmap-node n-mission t-${tone}" data-cmap-mission="${m.id}" title="Open the mission">
        ${icon(ENGINE_ICON[m.engine] || "sparkle")}<div><b>${esc(m.title)}</b><small>${esc(m.doing)}</small>
        <small class="cmap-meta">${money(m.spent)} of ${money(m.budget)}${m.requests ? ` · <em>${plural(m.requests, "request")} for you</em>` : ""}</small></div></button>`;
    }).join("");
  }
  function engines(d) {
    return `<div class="cmap-engines">${d.engines.map(e => {
      const pre = e.key === "mining" ? (d.predefined || []).length : 0;
      const n = e.missions.length + pre, wanted = e.key === "mining" && d.wanted.length;
      return `<div class="cmap-node n-engine ${n ? "on" : ""} ${e.available ? "" : "off"}">${icon(ENGINE_ICON[e.key])}<div><b>${esc(e.label)}</b>
        <small>${esc(ENGINE_NOTE[e.key] || "")}</small>
        <small class="cmap-meta">${n ? `${plural(n, "mission")} here${pre ? ` (${pre} predefined)` : ""}` : e.available ? "idle" : "not on this server"}${e.key === "mining" ? ` · ${plural(d.team_count, "team")}` : ""}${wanted ? ` · <em>${plural(d.wanted.length, "team")} wanted</em>` : ""}</small></div></div>`;
    }).join("")}</div>`;
  }
  function teams(d, o) {
    const wanted = d.wanted.map(w => `<div class="cmap-team missing">
        <div class="cmap-thead">${icon("trophy")}<div><b>SN${w.netuid}${w.number != null ? ` · competition ${w.number}` : ` · ${esc(w.name)}`}</b>
          <small>Doesn't exist yet. Mission #${w.mission} needs it: ${esc(w.pack_label)}, ${w.agents} agents${w.campaign == null ? `, and your SN${w.netuid} campaign starts too` : ""}.</small></div>
          <button type="button" class="btn sm primary" data-cmap-mission="${w.mission}">${icon("shield")}Review the request</button></div></div>`).join("");
    const list = d.teams.map(t => t.director !== undefined ? team(t) : `<button type="button" class="cmap-tchip" data-cmap-team="${t.id}" title="Open the team">
        ${icon("trophy")}SN${t.netuid ?? "?"} · ${esc(t.label)} <small>${plural(t.agent_count, "agent")}${t.missions.length ? ` · ${plural(t.missions.length, "mission")}` : ""}</small></button>`).join("");
    if (!wanted && !list) {
      return o.team == null && !d.team_count ? tier("teams", `<div class="cmap-node n-ghost">${icon("trophy")}<div><b>No Competition team yet</b>
        <small>Start a mission about a subnet (e.g. “Improve my SN62 competition 28 miner”): AXoR offers to create the team. Or use My subnets → Import competitions.</small></div></div>`) : "";
    }
    const deep = d.teams.some(t => t.director !== undefined);
    return tier("teams", `${wanted}${deep ? list : `<div class="cmap-tchips">${list}</div>`}`);
  }
  function team(t) {
    const tk = t.tasks, dir = t.director;
    const flags = [t.autopilot ? (t.paused ? "autopilot paused" : "autopilot on") : "autopilot off", t.planning ? "planning now" : "",
      `${tk.done}/${tk.total} tasks done`, tk.busy ? `${tk.busy} in progress` : ""].filter(Boolean).join(" · ");
    return `<div class="cmap-team">
      <div class="cmap-thead">${icon("trophy")}<div><b>SN${t.netuid ?? "?"} · ${esc(t.label)}</b><small>${esc(flags)}</small></div>
        <button type="button" class="btn sm" data-cmap-team="${t.id}">${icon("external")}Open the team</button></div>
      ${dir ? `<div class="cmap-dir">${agent(dir, "cmap-big")}<small>${t.relay ? "Director: settles the team's work and sends you one report" : "Lead: plans the team's tasks"}${t.report ? ` · <em>a report waits for you</em>` : ""}</small></div>`
        : `<p class="cmap-none">${icon("alert")}No lead: nobody plans this team's work. Pick one in the team's Agents tab.</p>`}
      ${t.squads.length ? `<div class="cmap-squads">${t.squads.map(squad).join("")}</div>` : `<p class="cmap-none">No agents yet.</p>`}
    </div>`;
  }
  function squad(s) {
    const shown = s.agents.slice(0, 8), more = s.count - (s.head ? 1 : 0) - shown.length;
    return `<div class="cmap-squad"><div class="cmap-sh"><b>${esc(s.label)}</b><small>${s.working ? `${s.working} working` : plural(s.count, "agent")}</small></div>
      ${s.head ? `<div class="cmap-head">${agent(s.head)}<small>head</small></div>` : ""}
      <div class="cmap-ags">${shown.map(a => agent(a)).join("")}${more > 0 ? `<span class="cmap-more">+${more}</span>` : ""}</div></div>`;
  }
  const agent = (a, size = "") => `<span class="cmap-ag s-${a.state} ${size}" title="${esc(`${a.name} · ${a.title || ""} — ${STATE[a.state] || a.state}${a.doing ? `: ${a.doing}` : ""}`)}"><i></i>${esc(a.name)}${a.doing && size ? `<em>${esc(a.doing)}</em>` : ""}</span>`;

  // ---------- events ----------
  function wire(el) {
    if (!el || el.dataset.cmapWired) return;
    el.dataset.cmapWired = "1";
    el.addEventListener("click", e => {
      const m = e.target.closest("[data-cmap-mission]");
      if (m) { e.preventDefault(); return MissionOS.show(+m.dataset.cmapMission); }
      const p = e.target.closest("[data-cmap-ref]");
      if (p) { e.preventDefault(); return CtlMissions.openMission(p.dataset.cmapRef); }
      const t = e.target.closest("[data-cmap-team]");
      if (t) { e.preventDefault(); return MiningWork.openPage(+t.dataset.cmapTeam); }
    });
    el.addEventListener("toggle", e => { const d = e.target.closest?.("[data-cmap-toggle]"); if (d && d === e.target) setOpen(d.dataset.cmapToggle, d.open); }, true);
  }
  const drop = key => { delete cache[key]; };

  return { slot, wire, drop };
})();
