/* My subnets ⇄ Mission Control, on a Competition team's page (mining-work.js draws the page, missions.py runs the missions):
   a strip above the sub-tabs with the missions that run or ran on this team, "Start mission" (a new mission in Mission Control,
   already aimed at this team), and the team's chain of command (command-map.js), shut until opened. */
const MissionTeam = (() => {
  const TTL = 10000, cache = {};
  const OUTCOME = { verified: "verified", partial: "partly done", failed: "not achieved", unverified: "not verifiable" };
  const live = m => ["queued", "running", "needs_input", "paused"].includes(m.status);

  function load(wid) {
    const c = cache[wid] ||= { rows: null, at: 0, busy: false, off: false };
    if (c.busy || c.off || Date.now() - c.at < TTL) return;
    c.busy = true;
    api(`/api/mos/teams/${wid}`).then(r => { c.rows = r.missions; }).catch(() => { c.off = true; })  // missions off, or not for this user: no strip
      .finally(() => { c.at = Date.now(); c.busy = false; paint(wid); });
  }
  function paint(wid) {
    $$(`[data-mtm-slot="${wid}"]`).forEach(el => { el.innerHTML = line(wid); hydrateIcons(el); });
    if (cache[wid]?.off) $$(`[data-mtm-team="${wid}"], [data-mtm-map="${wid}"]`).forEach(el => el.remove());
  }
  function line(wid) {
    const c = cache[wid];
    if (!c?.rows) return `<span class="mtm-line faint">Looking for missions on this team…</span>`;
    const now = c.rows.find(live), last = c.rows.find(m => !live(m));
    const text = now ? `<b>Mission “${esc(now.title)}”</b> ${now.status === "needs_input" ? "waits for you" : "runs on this team"}: ${esc(now.doing)}`
      : c.rows.length ? `${c.rows.length} mission${c.rows.length === 1 ? "" : "s"} ran on this team${last ? ` · last: <b>${esc(last.title)}</b>${last.outcome ? ` (${esc(OUTCOME[last.outcome] || last.outcome)})` : ""}` : ""}`
      : "No mission has run on this team yet. A mission gives the team one goal with a budget and a deadline, and checks the result independently.";
    return `<span class="mtm-line">${text}</span><span class="mtm-acts">
      ${now ? `<button type="button" class="btn sm" data-mtm-open="${now.id}">${icon("external")}Open the mission</button>` : ""}
      <button type="button" class="btn sm primary" data-mtm="start">${icon("rocket")}Start mission</button></span>`;
  }

  function strip(v) {
    const wid = v.comp.id;
    load(wid);
    if (cache[wid]?.off) return "";
    return `<div class="mtm-strip" data-mtm-team="${wid}" data-mtm-label="${esc(v.comp.label)}" data-mtm-net="${esc(v.campaign?.netuid ?? "")}">${icon("target")}
        <span class="mtm-slot" data-mtm-slot="${wid}" style="display:contents">${line(wid)}</span></div>
      <div class="mtm-map" data-mtm-map="${wid}">${CommandMap.slot(`t${wid}`, { team: wid, toggle: "team", closed: true, title: "Chain of command: you → missions → this team" })}</div>`;
  }

  function wire(el) {
    if (!el || el.dataset.mtmWired) return;
    el.dataset.mtmWired = "1";
    CommandMap.wire(el);
    el.addEventListener("click", e => {
      const o = e.target.closest("[data-mtm-open]");
      if (o) return MissionOS.show(+o.dataset.mtmOpen);
      const s = e.target.closest("[data-mtm='start']");
      if (s) {
        const b = s.closest("[data-mtm-team]");
        MissionOS.start({ id: +b.dataset.mtmTeam, label: b.dataset.mtmLabel, netuid: b.dataset.mtmNet ? +b.dataset.mtmNet : null });
      }
    });
  }

  return { strip, wire };
})();
