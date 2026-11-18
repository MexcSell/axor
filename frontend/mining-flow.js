/* My subnets' workflow diagram (mining.js draws it on the Team tab): the team as the cycle runs through it.
   Rio's snapshot → Kit's checks → Ellis and Finley side by side → Sage's plan → Avery's brief, with Quinn (Scribe) saving
   each step to the repository on a lane below. Each node shows its state in the running cycle (or the last one), what it's
   doing or found, and quick controls: run from here, switch it off. Below it, the last cycles as a grid (a row per cycle, a
   cell per step). Plain HTML and inline SVG on the app's tokens; mining.js owns the data and the clicks. */
const MiningFlow = (() => {
  const FLOW = [["scout", "Snapshot"], ["sentinel", "Checks"], ["analyst", "Field analysis"], ["tracker", "Your miners"], ["strategist", "Plan"], ["captain", "Brief"]];
  const LABEL = Object.fromEntries(FLOW);
  const FROM = { analyst: ["analyst", "strategist", "captain"], tracker: ["tracker", "strategist", "captain"], strategist: ["strategist", "captain"], captain: ["captain"], scout: ["scout"] };
  // a step's state: [tone class, label]
  const STEP = { working: ["run", "Working…"], done: ["ok", "Done"], reused: ["reuse", "Reused"], skipped: ["skip", "Skipped"], failed: ["bad", "Failed"],
    cancelled: ["off", "Stopped"], off: ["off", "Off the team"], nomodel: ["none", "Needs a model"], idle: ["wait", "Waiting"], paused: ["off", "Paused"], queued: ["wait", "Next"] };
  const SAVE = { saved: ["ok", "Saved"], pending: ["run", "Saving…"], failed: ["bad", "Not saved"] };
  const dur = s => s == null ? "" : s < 1 ? `${Math.round(s * 1000)} ms` : s < 60 ? `${fmtNum(s, 1)} s` : `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  const short = n => n >= 1e6 ? `${fmtNum(n / 1e6, 1)}M` : n >= 1e3 ? `${fmtNum(n / 1e3, 1)}k` : fmtNum(n || 0, 0);
  const av = a => `<span class="av sm c-${a?.color || "slate"}" aria-hidden="true">${icon(a?.icon || "bot")}</span>`;

  // each agent's state in the diagram: what it's doing now, else what it did in the flow's cycle, else its standing state
  function states(d) {
    const f = d.flow, run = d.running, out = {};
    const cards = Object.fromEntries(d.staff.map(a => [a.id, a]));
    for (const [id] of [...FLOW, ["scribe"]]) {
      const a = cards[id] || {}, x = f?.steps?.[id] || {};
      let st = x.status || "idle";
      if (run && run.activity?.[id]) st = "working";
      else if (a.status === "off") st = "off";
      else if (d.campaign.status !== "live" && !run) st = x.status ? st : "paused";
      else if (a.status === "nomodel" && !x.status) st = "nomodel";
      if (run && f?.status === "running" && !x.status && st !== "off") st = "queued";
      out[id] = { ...x, st, card: a, activity: run?.activity?.[id] };
    }
    const saved = Object.values(f?.saved || {});
    out.scribe.st = cards.scribe?.status === "off" && !saved.length ? "off" : saved.some(s => s.status === "pending") ? "working"
      : saved.some(s => s.status === "failed") ? "failed" : saved.length ? "done" : cards.scribe?.status === "off" ? "off" : "idle";
    return out;
  }

  function node(id, s, d, cls = "") {
    const a = s.card, [tone, label] = STEP[s.st] || STEP.idle, live = d.campaign.status === "live", busy = !!d.running;
    const save = d.flow?.saved?.[id], [stone, slabel] = save ? SAVE[save.status] || SAVE.failed : [];
    const meta = ["done", "failed", "working"].includes(s.st) ? [s.t1 && s.t0 ? dur(s.t1 - s.t0) : "", s.tokens ? `${short(s.tokens)} tokens` : ""].filter(Boolean).join(" · ") : "";
    const note = s.st === "working" ? s.activity || a.activity || "" : s.note || (s.st === "off" ? "Switched off: sits out every cycle" : s.st === "nomodel" ? "Connect a model in Agents → Models" : "");
    const runnable = FROM[id] && live && !busy, sw = a.switchable;
    return `<div class="mf-node t-${tone} ${cls}" data-step="${id}">
      <button type="button" class="mf-main" data-agent="${id}" aria-label="${esc(a.name || id)}, ${esc(LABEL[id] || a.title || "")}: ${label}. Open its controls">
        <span class="mf-top">${av(a)}<span class="mf-who"><b>${esc(a.name || id)}</b><span>${esc(LABEL[id] || a.title || "")}</span></span></span>
        <span class="mf-state"><span class="mf-dot"></span>${label}${meta ? `<span class="mf-meta">${meta}</span>` : ""}</span>
        ${note ? `<span class="mf-note">${esc(note)}</span>` : ""}
        ${save ? `<span class="mf-saved t-${stone}">${icon("commit")}${slabel}</span>` : ""}</button>
      ${runnable || sw ? `<span class="mf-tools">${runnable ? `<button type="button" class="iconbtn" data-mfrun="${id}" title="${id === "scout" ? "Take a snapshot now" : id === "captain" ? "Write a new brief now" : `Run from ${esc(a.name)} on`}" aria-label="${id === "scout" ? "Take a snapshot now" : `Run from ${esc(a.name)} on`}">${icon("play")}</button>` : ""}
        ${sw ? `<button type="button" class="iconbtn ${a.on ? "" : "on"}" data-mfoff="${id}" aria-pressed="${!a.on}" title="${a.on ? `Switch ${esc(a.name)} off` : `Put ${esc(a.name)} back on the team`}" aria-label="${a.on ? `Switch ${esc(a.name)} off` : `Put ${esc(a.name)} back on`}">${icon(a.on ? "ban" : "check")}</button>` : ""}</span>` : ""}
    </div>`;
  }

  // the arrows: a straight one, the fork into Ellis and Finley, the join into Sage; "on" while data flows down it
  const tone = (a, b) => b.st === "working" ? "flow" : ["done", "reused"].includes(a.st) && ["done", "reused", "working", "failed"].includes(b.st) ? "done" : "";
  function edge(cls, kind, t) {
    const H = { line: "M0 50 L100 50", fork: "M0 50 C45 50 45 25 100 25 M0 50 C45 50 45 75 100 75", join: "M0 25 C55 25 55 50 100 50 M0 75 C55 75 55 50 100 50" }[kind];
    const V = { line: "M50 0 L50 100", fork: "M50 0 C50 45 25 45 25 100 M50 0 C50 45 75 45 75 100", join: "M25 0 C25 55 50 55 50 100 M75 0 C75 55 50 55 50 100" }[kind];
    const svg = (dir, p) => `<svg class="mf-svg ${dir}" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="${p}" vector-effect="non-scaling-stroke"/></svg>`;
    return `<div class="mf-edge ${cls} ${t}">${svg("h", H)}${svg("v", V)}</div>`;
  }

  function diagram(d) {
    const s = states(d), f = d.flow, j = d.journal || {};
    const tAn = [s.analyst, s.tracker].some(x => x.st === "working") ? "flow" : ["done", "reused"].includes(s.sentinel.st) && [s.analyst, s.tracker].some(x => ["done", "reused", "failed"].includes(x.st)) ? "done" : "";
    const tSage = s.strategist.st === "working" ? "flow" : [s.analyst, s.tracker].some(x => ["done", "reused"].includes(x.st)) && ["done", "failed"].includes(s.strategist.st) ? "done" : "";
    const files = FLOW.map(([id]) => { const x = f?.saved?.[id]; if (!x) return "";
      const [t, lab] = SAVE[x.status] || SAVE.failed;
      return x.url ? `<a class="mf-file t-${t}" href="${esc(x.url)}" target="_blank" rel="noopener" title="${esc(lab)}${x.error ? `: ${esc(x.error)}` : ""}">${icon("doc")}${esc(LABEL[id])}</a>`
        : `<span class="mf-file t-${t}" title="${esc(lab)}${x.error ? `: ${esc(x.error)}` : ""}">${icon(x.status === "failed" ? "alert" : "doc")}${esc(LABEL[id])}</span>`; }).join("");
    const idx = f?.saved?.index;
    const scribe = s.scribe.card, [stn, stl] = STEP[s.scribe.st] || STEP.idle;
    return `<div class="mf" role="group" aria-label="The team's workflow">
        ${node("scout", s.scout, d, "c-rio")}${edge("e1", "line", tone(s.scout, s.sentinel))}${node("sentinel", s.sentinel, d, "c-kit")}${edge("e2", "fork", tAn)}
        ${node("analyst", s.analyst, d, "c-ellis")}${node("tracker", s.tracker, d, "c-finley")}${edge("e3", "join", tSage)}
        ${node("strategist", s.strategist, d, "c-sage")}${edge("e4", "line", tone(["skipped", "off"].includes(s.strategist.st) ? s.sentinel : s.strategist, s.captain))}${node("captain", s.captain, d, "c-avery")}</div>
      <div class="mf-lane t-${stn}"><button type="button" class="mf-lane-who" data-agent="scribe" aria-label="${esc(scribe?.name || "Quinn")}, Scribe: ${stl}. Open its controls">${av(scribe)}<span class="mf-who"><b>${esc(scribe?.name || "Quinn")}</b><span>Saves each step</span></span></button>
        <div class="mf-lane-body">${j.on ? `<span class="mf-lane-to">${icon("repo")}<a href="${esc(j.url || "#")}" target="_blank" rel="noopener">${esc(j.repo)}</a> <span class="faint">on</span> ${icon("branch")}<code>${esc(j.branch)}</code></span>
            <span class="mf-files">${files || `<span class="faint small">${f ? "Nothing saved from this cycle." : "Files appear here as each step finishes."}</span>`}${idx ? `<span class="mf-file t-${(SAVE[idx.status] || SAVE.failed)[0]}">${icon("book")}README</span>` : ""}</span>`
          : `<span class="faint small">Saving to a repository is off. ${d.journal?.can ? "Turn it on in Settings: each step's results are committed as the step finishes." : d.journal?.connected ? "An administrator's campaign can turn it on." : "Connect GitHub in the Source view, then turn it on in Settings."}</span>`}
          ${s.scribe.card?.note && j.on ? `<span class="mf-note">${esc(s.scribe.card.note)}</span>` : ""}</div></div>`;
  }

  // the last cycles: a row per cycle, a cell per step; a cell with a run opens its trace
  function grid(list, d) {
    if (!list) return Loading.line("Reading the cycles…");
    if (!list.length) return `<div class="empty small">No cycles yet.</div>`;
    const P = Object.fromEntries(d.staff.map(a => [a.id, a])), why = { schedule: "Scheduled", manual: "You", alert: "Alert", kickoff: "First" };
    const cell = (c, id) => {
      const x = c.steps[id]; if (!x) return `<td class="mf-c t-none"><span class="mf-dot"></span><span class="mh-sr">Not run</span></td>`;
      const [t, l] = STEP[x.status] || STEP.idle, sv = c.saved[id];
      const tip = `${P[id]?.name || id}: ${l}${x.note ? ` - ${x.note}` : ""}${x.t1 && x.t0 ? ` (${dur(x.t1 - x.t0)})` : ""}${sv ? ` · ${(SAVE[sv.status] || SAVE.failed)[1]}` : ""}`;
      return `<td class="mf-c t-${t}" title="${esc(tip)}" ${x.run && x.status !== "reused" ? `data-trace="${x.run}" tabindex="0"` : ""}><span class="mf-dot"></span><span class="mf-c-l">${l}</span>${sv ? `<span class="mf-c-s t-${(SAVE[sv.status] || SAVE.failed)[0]}">${icon("commit")}</span>` : ""}</td>`;
    };
    return `<div class="tablewrap mh-table-wrap"><table class="mh-table mf-grid"><thead><tr><th>Cycle</th>${FLOW.map(([id, l]) => `<th title="${esc(P[id]?.name || "")}">${l}</th>`).join("")}<th class="r">Saved</th><th class="r">Tokens</th><th class="r">Time</th></tr></thead>
      <tbody>${list.map(c => { const sv = Object.values(c.saved), ok = sv.filter(x => x.status === "saved").length, bad = sv.filter(x => x.status === "failed").length;
        return `<tr><td><b>#${c.id}</b> <span class="faint">${why[c.trigger] || esc(c.trigger)} · ${clock(c.started)}</span>${c.status === "running" ? ` <span class="hq-live on">live</span>` : c.status !== "done" ? ` <span class="faint">(${esc(c.status)})</span>` : ""}</td>
          ${FLOW.map(([id]) => cell(c, id)).join("")}<td class="r num">${sv.length ? `${ok}${bad ? ` <span class="t-bad-text" title="${esc(sv.find(x => x.error)?.error || "")}">· ${bad} failed</span>` : ""}` : "–"}</td>
          <td class="r num">${short(c.tokens)}</td><td class="r num">${c.finished ? dur(c.finished - c.started) : "…"}</td></tr>`; }).join("")}</tbody></table></div>`;
  }

  // what an agent card shows about this step in the flow's cycle
  function stepDetail(d, id) {
    const x = d.flow?.steps?.[id], sv = d.flow?.saved?.[id];
    if (!x && !sv) return "";
    const [t, l] = STEP[x?.status] || STEP.idle;
    return `<div class="mf-detail t-${t}"><div><b>Cycle #${d.flow.cycle}:</b> <span class="mf-dot"></span>${l}${x?.t1 && x?.t0 ? ` · ${dur(x.t1 - x.t0)}` : ""}${x?.tokens ? ` · ${short(x.tokens)} tokens` : ""}</div>
      ${x?.note ? `<p>${esc(x.note)}</p>` : ""}
      <div class="row">${x?.run ? `<button type="button" class="btn sm" data-trace="${x.run}">${icon("layers")}Open the trace</button>` : ""}
        ${sv?.url ? `<a class="btn sm" href="${esc(sv.url)}" target="_blank" rel="noopener">${icon("commit")}The saved file</a>` : sv ? `<span class="faint small">${icon("commit")}${(SAVE[sv.status] || SAVE.failed)[1]}${sv.error ? `: ${esc(sv.error)}` : ""}</span>` : ""}</div></div>`;
  }

  return { diagram, grid, stepDetail, FROM, LABEL };
})();
