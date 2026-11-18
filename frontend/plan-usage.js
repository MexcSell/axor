/* Agents → Models → a connected model → Usage: how much of the model's plan is used. One ring per window
   (5-hour session, weekly, monthly), % used, when it resets (in this browser's time zone) and how long until then.
   The server reads it where the plan keeps it (backend/app/plan_usage.py): GET /api/agents/settings/usage/{provider}. */
const PlanUsage = (() => {
  const GROUPS = ["weekly", "monthly"];  // shown after the session window; a window the plan doesn't have isn't drawn
  let seq = 0;

  const left = s => {  // seconds → "1 h 33 min", "3 d 19 h", "12 min"
    if (s <= 0) return "now";
    const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return d ? `${d} d${h ? ` ${h} h` : ""}` : h ? `${h} h${m ? ` ${m} min` : ""}` : `${Math.max(1, m)} min`;
  };
  const when = t => {
    const d = new Date(t * 1000), now = new Date();
    const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const sameDay = d.toDateString() === now.toDateString();
    const soon = t * 1000 - now < 6 * 86400e3;
    return sameDay ? `today ${time}` : soon ? `${d.toLocaleDateString([], { weekday: "short" })} ${time}`
      : `${d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })} ${time}`;
  };
  const ago = t => { const s = Date.now() / 1000 - t; return s < 60 ? "just now" : `${left(s)} ago`; };

  function ring(used) {
    const r = 15.5, c = 2 * Math.PI * r, p = used == null ? 0 : Math.min(100, used);
    const tone = used == null ? "na" : p >= 90 ? "crit" : p >= 75 ? "warn" : "ok";
    return `<span class="pu-ring pu-${tone}" role="img" aria-label="${used == null ? "No percent" : `${Math.round(p)} percent used`}">
      <svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="${r}" class="pu-track"/>
      <circle cx="18" cy="18" r="${r}" class="pu-bar" stroke-dasharray="${(p / 100 * c).toFixed(2)} ${c.toFixed(2)}"/></svg>
      <b>${used == null ? "–" : `${Math.round(p)}%`}</b></span>`;
  }
  function tile(w) {
    const now = Date.now() / 1000;
    const reset = w.resets_at > now ? `resets ${esc(when(w.resets_at))} · <span class="pu-left">in ${esc(left(w.resets_at - now))}</span>` : "";
    return `<div class="pu-tile">${ring(w.used)}<div class="pu-txt"><b>${esc(w.label)}</b>
      <span>${w.used != null ? `<strong>${Math.round(w.used)}%</strong> used${w.detail ? ` · ${esc(w.detail)}` : ""}` : esc(w.detail || "")}</span>
      ${reset ? `<small class="faint">${reset}</small>` : ""}</div></div>`;
  }
  function view(u, provider) {
    const ws = u.windows || [];
    const tiles = [...ws.filter(w => !GROUPS.includes(w.group)).map(tile), ...GROUPS.flatMap(g => ws.filter(w => w.group === g).map(tile))];
    const head = [u.plan, u.account].filter(Boolean).map(esc).join(" · ");
    const probe = u.can_probe && /^(own:)?terminal(:|$)/.test(provider);
    // explanations sit behind a "?" (pagetip.js), like everywhere on the Models page; errors stay in sight
    const about = [u.note ? esc(u.note) : "", "The refresh button reads the usage again and lists the model again.",
      probe ? "Check with a short prompt runs one tiny Claude Code prompt to read the plan's windows; it uses a little of the plan." : ""].filter(Boolean).join(" ");
    const tid = `pu-tip${++seq}`;
    return `<div class="pu-head"><span class="pu-title">Usage<button type="button" class="ptip-btn mdl-tipbtn" data-ptip-for="${tid}" aria-label="About usage" aria-describedby="${tid}" aria-expanded="false">${icon("help")}</button></span>
        <span class="ptip-src" id="${tid}">${about}</span>${head ? `<span class="faint small">${head}</span>` : ""}
        <button type="button" class="iconbtn sm pu-again" data-pu-again title="Check again" aria-label="Check usage again">${icon("cycle")}</button></div>
      ${u.error ? `<p class="no small">${esc(u.error)}</p>` : ""}
      ${tiles.length ? `<div class="pu-grid">${tiles.join("")}</div>` : ""}
      <p class="faint small pu-foot">Checked ${esc(ago(u.checked_at))}.
        ${probe ? `<button type="button" class="linkbtn" data-pu-probe>Check with a short prompt</button>` : ""}</p>`;
  }

  // draws into `box` (a div on the model's card in Agents → Models); never throws: a failed read only shows its error
  // onAgain: also called by the refresh button (the model card redraws its state with it)
  async function render(box, provider, { fresh = false, probe = false, onAgain = null } = {}) {
    if (!box) return;
    box.classList.add("pu");
    if (!box.innerHTML.trim() || probe || fresh) box.innerHTML = `<div class="pu-head"><span class="pu-title">Usage</span></div><p class="faint small">${probe ? "Running one short Claude Code prompt…" : "Reading the plan's usage…"}</p>`;
    let u;
    try {
      u = probe ? await api(`/api/agents/settings/usage/${encodeURIComponent(provider)}/probe`, { method: "POST" })
        : await api(`/api/agents/settings/usage/${encodeURIComponent(provider)}${fresh ? "?fresh=1" : ""}`);
    } catch (e) { u = { windows: [], error: e.message, checked_at: Date.now() / 1000 }; }
    if (!document.body.contains(box)) return;  // the dialog closed or moved on meanwhile
    box.innerHTML = view(u, provider);
    hydrateIcons(box);
    box.querySelector("[data-pu-again]").onclick = () => { onAgain?.(); render(box, provider, { fresh: true, onAgain }); };
    const pb = box.querySelector("[data-pu-probe]"); if (pb) pb.onclick = () => render(box, provider, { probe: true, onAgain });
  }
  return { render, left, when };
})();
