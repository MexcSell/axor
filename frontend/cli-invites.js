// Connect requests (backend: cli_invites.py), inside Agents → My logins (cli-accounts.js) and as a banner on any page.
// Admins: everyone's Claude Code / Codex status (connected, asked, seen, declined, expired), ask people to connect, remind,
// cancel, remove a login, copy the link. Members: "<admin> asked you to connect …" and the one step only they can do
// (connect their own login in the cards below). An admin never sees a member's token or sign-in code.
const CliInvites = (() => {
  const P = ["terminal", "codex"];
  const NAMES = { terminal: "Claude Code", codex: "Codex" };
  const rel = t => {
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
  };
  const day = t => new Date(t * 1000).toLocaleDateString([], { dateStyle: "medium" });
  const both = ps => ps.map(p => NAMES[p] || p).join(" and ");
  const store = (k, v) => { try { return v === undefined ? sessionStorage.getItem(k) : sessionStorage.setItem(k, v); } catch { return null; } };
  let team = null, pick = new Set(), want = new Set(P), had = false;

  // ---------- the member's side ----------
  function askedNote(reqs) {
    const by = [...new Set(reqs.map(r => r.by))].join(", ");
    const ps = reqs.map(r => r.provider);
    return `<div class="cli-asked" role="status">
      <p class="small"><b>${esc(by)}</b> asked you to connect your own ${esc(both(ps))}. Connect it in the card${ps.length > 1 ? "s" : ""} below:
        agents you use then run on your own plan first, with its own usage limit (it's shared with teammates who have none while the server's login is off).</p>
      ${ps.includes("terminal") ? `<p class="faint small">No Claude Code on your computer yet? Install it (<code>npm install -g @anthropic-ai/claude-code</code>), sign in, then run <code>claude setup-token</code>.</p>` : ""}
      <div class="cli-asked-actions">${reqs.map(r => `<button type="button" class="btn sm ghost" data-decline="${esc(r.provider)}">Decline ${esc(r.name)}</button>`).join("")}</div>
    </div>`;
  }

  async function fillMine(d, render) {
    const box = $("[data-cli-asked]", d);
    if (!box) return;
    let reqs = [];
    try { reqs = (await api("/api/cli-accounts/requests")).requests; } catch { return; }
    if (!reqs.length) { box.innerHTML = ""; return; }
    box.innerHTML = askedNote(reqs);
    reqs.forEach(r => $(`[data-cla="${r.provider}"]`, d)?.classList.add("cla-asked"));
    if (reqs.some(r => !r.seen)) api("/api/cli-accounts/requests/seen", { method: "POST" }).catch(() => {});
    $$("[data-decline]", box).forEach(b => b.onclick = () => {
      const p = b.dataset.decline;
      UI.confirm({ title: `Decline connecting your ${esc(NAMES[p])}?`, body: "Your administrator sees that you declined. Agents won't run these models for you until you connect it.", ok: "Decline", icon: "ban",
        run: async () => { const r = await api(`/api/cli-accounts/requests/${p}/decline`, { method: "POST" }); render(r.message); } });
    });
  }

  // ---------- the admin's side ----------
  function cell(c, row, p) {
    const id = `${row.user_id}/${p}`, inv = c.state === "asked" || c.state === "declined" || c.state === "expired";
    const b = {
      connected: `<span class="badge clear">${icon("check")}Connected</span><span class="faint">since ${esc(day(c.connected))}</span>`,
      not_working: `<span class="badge avoid" title="${esc(c.error || "")}">${icon("alert")}Not working</span>`,
      asked: `<span class="badge new">${icon("send")}Asked ${esc(rel(c.asked))}</span><span class="faint">${c.seen ? `seen ${esc(rel(c.seen))}` : "not seen yet"}${c.reminded ? ` · reminded ${esc(rel(c.reminded))}` : ""}</span>`,
      declined: `<span class="badge avoid">${icon("ban")}Declined ${esc(rel(c.declined))}</span>`,
      expired: `<span class="badge">Request expired</span>`,
      none: `<span class="faint">Not connected</span>`,
    }[c.state] || "";
    const acts = [];
    if (c.state === "asked" || c.invite) acts.push(`<button type="button" class="linkbtn" data-remind="${id}">Remind</button>`, `<button type="button" class="linkbtn" data-uninvite="${id}">Cancel</button>`);
    if ((["none", "declined", "expired"].includes(c.state) || (c.state === "not_working" && !c.invite)) && row.can_use && !row.disabled && !row.pending_approval)
      acts.push(`<button type="button" class="linkbtn" data-ask="${id}">${c.state === "none" ? "Ask" : "Ask again"}</button>`);
    if (c.state === "connected" || c.state === "not_working") acts.push(`<button type="button" class="linkbtn danger-text" data-unlink="${id}">Remove</button>`);
    if (c.invite) acts.unshift(`<span class="faint">asked ${esc(rel(c.invite.asked))}</span>`);
    return `<td data-label="${NAMES[p]}"><div class="cli-cell">${b}${acts.length ? `<span class="cli-acts">${acts.join("")}</span>` : ""}</div>${inv && c.by ? `<span class="faint cli-by">by ${esc(c.by)}</span>` : ""}</td>`;
  }

  const askable = r => r.can_use && !r.disabled && !r.pending_approval;
  const busy = r => Object.values(r.providers).some(c => c.state !== "none");

  function teamHtml(t) {
    const shown = t.people.filter(r => (!r.disabled && !r.pending_approval) || busy(r));
    const hidden = t.people.length - shown.length;
    pick = new Set([...pick].filter(uid => shown.some(r => r.user_id === uid && askable(r))));
    const done = shown.filter(r => P.every(p => r.providers[p].state === "connected")).length;
    return `<div class="cli-team">
      <div class="cli-team-head"><h4>${icon("users")}Team logins</h4>
        <button type="button" class="btn sm" data-copy-link title="The link opens My logins for whoever is signed in">${icon("link")}Copy link</button></div>
      <p class="faint small">Ask teammates to connect their own Claude Code or Codex. They get a banner in AXoR${t.push ? " and a push notification" : ""}
        and connect it themselves in a minute; you see the status here. You never see their token or sign-in code, and nothing you do here runs on their plan.
        ${done} of ${shown.length} ${shown.length === 1 ? "person has" : "people have"} both connected.</p>
      ${t.members_allowed ? "" : `<p class="cli-warn small">${icon("alert")}Agents are for administrators only, so members can't open My logins and can't be asked.
        Open Agents to members in Agents → Models first.</p>`}
      <div class="cli-table-wrap"><table class="cli-table small">
        <thead><tr><th class="cli-check"><input type="checkbox" data-pick-all aria-label="Select everyone who can be asked"></th><th>Person</th><th>Claude Code</th><th>Codex</th></tr></thead>
        <tbody>${shown.map(r => `<tr class="${r.disabled ? "cli-off" : ""}">
          <td class="cli-check"><input type="checkbox" data-pick="${r.user_id}" ${pick.has(r.user_id) ? "checked" : ""} ${askable(r) ? "" : "disabled"} aria-label="Select ${esc(r.username)}"></td>
          <td><b>${esc(r.username)}</b>${r.role === "admin" ? ` <span class="faint">admin</span>` : ""}${r.disabled ? ` <span class="faint">disabled</span>` : r.pending_approval ? ` <span class="faint">waiting for approval</span>` : !r.can_use ? ` <span class="faint">can't use Agents</span>` : ""}</td>
          ${P.map(p => cell(r.providers[p], r, p)).join("")}</tr>`).join("") || `<tr><td colspan="4" class="faint">No accounts yet.</td></tr>`}</tbody>
      </table></div>
      ${hidden ? `<p class="faint small">${hidden} disabled or not-yet-approved account${hidden === 1 ? "" : "s"} not shown.</p>` : ""}
      <div class="cli-askbar">
        <span class="small"><b data-pick-n>${pick.size}</b> selected · ask to connect</span>
        ${P.map(p => `<label class="small cli-want"><input type="checkbox" data-want="${p}" ${want.has(p) ? "checked" : ""}> ${NAMES[p]}</label>`).join("")}
        <button type="button" class="btn primary sm" data-ask-picked ${pick.size && want.size ? "" : "disabled"}>${icon("send")}Ask to connect</button>
      </div>
      <p class="err small" data-team-err></p>
    </div>`;
  }

  async function fillTeam(d, render) {
    const box = $("[data-cli-team]", d);
    if (!box) return;
    if (!team) box.innerHTML = Loading.line("Loading the team's logins…");
    try { team = await api("/api/cli-accounts/team"); } catch (e) { box.innerHTML = `<p class="err small">${esc(e.message)}</p>`; return; }
    draw(box, render);
  }

  function draw(box, render, msg) {
    box.innerHTML = teamHtml(team);
    hydrateIcons(box);
    if (msg) Auth.toast(msg);
    const err = $("[data-team-err]", box);
    const run = async (btn, fn) => {
      btn.disabled = true; err.textContent = "";
      try { await fn(); } catch (e) { if (e.message !== "cancelled") err.textContent = e.message; btn.disabled = false; }
    };
    const sync = () => {
      $("[data-pick-n]", box).textContent = pick.size;
      $("[data-ask-picked]", box).disabled = !(pick.size && want.size);
    };
    const send = async (users, providers) => {
      const r = await api("/api/cli-accounts/invites", { method: "POST", body: { users, providers } });
      team = r; pick.clear();
      const n = r.asked.length, why = r.skipped.filter(s => s.why);
      draw(box, render, n ? `Asked ${n} ${n === 1 ? "person" : "people"} to connect` : "Nobody was asked");
      if (why.length) $("[data-team-err]", box).textContent = why.map(s => `${s.username || "#" + s.user_id}: ${s.why}`).join(" ");
    };
    $$("[data-pick]", box).forEach(c => c.onchange = () => { c.checked ? pick.add(+c.dataset.pick) : pick.delete(+c.dataset.pick); sync(); });
    $("[data-pick-all]", box).onchange = e => {
      $$("[data-pick]:not(:disabled)", box).forEach(c => { c.checked = e.target.checked; e.target.checked ? pick.add(+c.dataset.pick) : pick.delete(+c.dataset.pick); });
      sync();
    };
    $$("[data-want]", box).forEach(c => c.onchange = () => { c.checked ? want.add(c.dataset.want) : want.delete(c.dataset.want); sync(); });
    $("[data-ask-picked]", box).onclick = e => run(e.currentTarget, () => send([...pick], P.filter(p => want.has(p))));
    $$("[data-ask]", box).forEach(b => b.onclick = () => { const [uid, p] = b.dataset.ask.split("/"); run(b, () => send([+uid], [p])); });
    $$("[data-remind]", box).forEach(b => b.onclick = () => run(b, async () => {
      const [uid, p] = b.dataset.remind.split("/");
      const r = await api(`/api/cli-accounts/invites/${uid}/${p}/remind`, { method: "POST" }); team = r; draw(box, render, r.message);
    }));
    $$("[data-uninvite]", box).forEach(b => b.onclick = () => run(b, async () => {
      const [uid, p] = b.dataset.uninvite.split("/");
      const r = await api(`/api/cli-accounts/invites/${uid}/${p}`, { method: "DELETE" }); team = r; draw(box, render, r.message);
    }));
    $$("[data-unlink]", box).forEach(b => b.onclick = () => {
      const [uid, p] = b.dataset.unlink.split("/");
      const who = team.people.find(r => r.user_id === +uid)?.username || "this person";
      UI.confirm({ title: `Remove ${esc(who)}'s ${esc(NAMES[p])} login?`, body: "Their token or Codex sign-in is deleted from the server. They can connect again.", ok: "Remove", icon: "ban",
        run: async () => { await Admin.withSudo(() => api(`/api/cli-accounts/all/${uid}/${p}`, { method: "DELETE" })); render("Login removed"); } });
    });
    $("[data-copy-link]", box).onclick = async e => {
      const url = location.origin + team.link;
      try { await navigator.clipboard.writeText(url); Auth.toast("Link copied"); }
      catch { err.textContent = `Copy this link: ${url}`; }
      e.currentTarget.blur();
    };
  }

  function fill(d, s, render) {
    fillMine(d, render);
    if (s.is_admin) fillTeam(d, render);
  }

  // ---------- the banner, on any page ----------
  async function banner() {
    $(".cli-ask-banner")?.remove();
    let reqs = [];
    try { reqs = (await api("/api/cli-accounts/requests")).requests; } catch { return; }
    had = reqs.length > 0;
    const key = reqs.map(r => r.provider + r.asked).join(",");
    if (!reqs.length || store("cli-ask-later") === key || $("#agentdlg")?.open) return;
    const ps = reqs.map(r => r.provider), by = [...new Set(reqs.map(r => r.by))].join(", ");
    const el = document.createElement("div");
    el.className = "cli-ask-banner"; el.setAttribute("role", "status");
    el.innerHTML = `<div class="cli-ask-icon">${icon("key")}</div>
      <div class="cli-ask-text"><b>Connect your ${esc(both(ps))}</b>
        <p class="small">${esc(by)} asked you to connect your own ${esc(both(ps))} so agents run on your own plan. It takes a minute.</p></div>
      <div class="cli-ask-actions"><button type="button" class="btn primary sm" data-go>Connect</button><button type="button" class="btn sm ghost" data-later>Not now</button></div>`;
    document.body.append(el);
    hydrateIcons(el);
    $("[data-go]", el).onclick = () => { el.remove(); CliAccounts.open(); };
    $("[data-later]", el).onclick = () => { store("cli-ask-later", key); el.remove(); };
  }

  function ready(fn) {  // after the app has booted and someone is signed in (app.js loads last)
    const ok = () => typeof S !== "undefined" && S.view && typeof Auth !== "undefined" && Auth.me();
    if (ok()) return fn();
    setTimeout(() => ready(fn), 1500);
  }

  function boot() {
    if (location.hash === "#agents/logins") { setView("agents"); CliAccounts.open(); }  // the link in requests and pushes
    else banner();
    $("#agentdlg")?.addEventListener("close", () => { if (had) setTimeout(banner, 300); });  // gone once they've connected
  }

  addEventListener("hashchange", () => { if (location.hash === "#agents/logins" && Auth.me?.()) { setView("agents"); CliAccounts.open(); } });
  addEventListener("load", () => ready(boot));
  return { fill, banner };
})();
