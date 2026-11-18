/* Competition teams, the Director's report (mining_director.py), as the Report sub-tab of a team (mining-work.js draws the page):
   with "Only the Director contacts me" on, agents' questions, finished work and failed tasks go to the Director, who settles what
   the team can and sends you one report: what got done, where things stand, and the asks, merged, with a recommendation each.
   You answer the whole report in one reply; the Director settles the asks' tasks with it. The board and the diagram count the
   report's asks as what waits for you, and the tasks still with the Director as with the Director. */
const MiningDirector = (() => {
  const W = "/api/mining/work";
  const err = e => e && Auth.toast(e.message);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const when = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const span = s => s < 3600 ? `${Math.max(1, Math.round(s / 60))}m` : `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m`;
  const SETTLED = { approve: "approved", answer: "answered", redo: "sent back", assign: "handed to a teammate", done: "done by you", drop: "dropped" };
  const D = v => v?.director;
  const relaying = v => !!D(v)?.relaying;
  const direct = t => ["review", "blocked"].includes(t.status) || (t.status === "todo" && t.agent == null);
  // what waits for you: the open report's asks when the Director relays, else every task waiting on you
  const waiting = v => relaying(v) ? D(v).waiting || 0 : v.tasks.filter(direct).length;
  const open = v => D(v)?.reports.find(r => r.status === "new") || null;
  const lead = v => v.agents.find(a => a.id === v.lead);
  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try { return await fn(); } catch (e) { err(e); return null; } finally { if (btn?.isConnected) { btn.classList.remove("loading"); btn.disabled = false; } }
  }

  function asks(v, r, T) {
    if (!r.asks.length) return `<p class="md-none small">${icon("check")} Nothing needs you: the team settled everything itself.</p>`;
    return `<ol class="md-asks">${r.asks.map(x => `<li class="md-ask k-${x.kind}">
        <span class="md-ask-top"><span class="hq-chip t-${x.kind === "todo" ? "wait" : "warn"}">${x.kind === "todo" ? "For you to do" : "Your decision"}</span><b>${esc(x.title)}</b></span>
        ${x.detail ? `<div class="md">${Agents.md(x.detail)}</div>` : ""}
        ${x.tasks.length ? `<span class="md-ask-t faint small">${icon("list")}${x.tasks.map(id => T[id] ? `<button type="button" class="linkbtn" data-mwtask="${id}">${esc(T[id].title)}</button>` : "").filter(Boolean).join(" · ")}</span>` : ""}</li>`).join("")}</ol>`;
  }
  function settled(r) {
    const s = Object.entries(r.settled || {}).filter(([, n]) => n);
    return s.length ? `<p class="md-settled faint small">${icon("check")}Settled with the team: ${s.map(([k, n]) => `${n} ${SETTLED[k] || k}`).join(", ")}</p>` : "";
  }
  function card(v, r, T, A, latest) {
    const by = A[r.agent_id];
    return `<article class="mh-card md-report ${r.status === "new" ? "is-new" : ""}">
      <header class="md-report-h">${by ? `<span class="av sm c-${by.color}" aria-hidden="true">${icon(by.icon)}</span>` : ""}
        <span><b>${esc(r.headline)}</b><span class="faint small">${esc(by?.name || "The Director")} · ${when(r.ts)}${r.status === "new" ? "" : r.status === "read" ? " · read" : r.status === "answered" ? " · you answered" : r.status === "superseded" ? " · replaced by a newer report" : " · settled"}</span></span>
        ${r.status === "new" ? `<button type="button" class="btn sm ghost" data-mdread="${r.id}">${icon("check")}Mark read</button>` : ""}</header>
      ${settled(r)}
      ${r.body ? `<div class="md md-body">${Agents.md(r.body)}</div>` : ""}
      <h4 class="md-h">${icon("hand")}What ${esc(by?.name || "the Director")} needs from you${r.asks.length ? ` <span class="hq-n alert">${r.asks.length}</span>` : ""}</h4>
      ${asks(v, r, T)}
      ${r.reply ? `<p class="md-reply">${icon("chat")}<span><b>You answered${r.by_user ? ` (${esc(r.by_user)})` : ""}:</b> ${esc(r.reply)}</span></p>` : ""}
      ${latest && ["new", "read"].includes(r.status) ? `<form class="md-form" data-mdform="${r.id}">
          <label class="in"><span>Your answer to the whole report <em class="opt">${esc(by?.name || "the Director")} settles the asks' tasks with it and reports back</em></span>
            <textarea name="text" rows="3" maxlength="4000" required placeholder="e.g. 1: go with option B. 2: I uploaded it. 3: skip it for now."></textarea></label>
          <span class="row"><button type="submit" class="btn sm primary">${icon("send")}Send to ${esc(by?.name || "the Director")}</button></span></form>` : ""}
    </article>`;
  }

  function report(v) {
    const d = D(v), L = lead(v), c = v.comp, closed = c.status === "closed";
    if (!d) return `<div class="empty">The Director's report isn't available on this server.</div>`;
    const T = Object.fromEntries(v.tasks.map(t => [t.id, t])), A = Object.fromEntries(v.agents.map(a => [a.id, a]));
    const name = L ? esc(L.name) : "the Director", next = (d.last_report || 0) + 3600 - Date.now() / 1000;
    const state = !d.relay ? `Agents come to you directly: ${plural(v.tasks.filter(direct).length, "task")} wait on the board.`
      : !L ? "Make someone on the team the lead (Team → an agent → Lead): without a Director, agents come to you directly."
      : d.reporting ? `${name} is going through the team's work for your report…`
      : d.with_director ? `${plural(d.with_director, "item")} with ${name}; ${c.paused || closed ? "the next report waits until the team is resumed" : `the next report ${next > 0 ? `in about ${span(next)}` : "soon"}, sooner if they pile up or the board runs dry`}.`
      : `Nothing new for ${name} to report.`;
    const [latest, ...older] = d.reports;
    return `<section class="mh-card md-head">
        <label class="mw-switch" title="Agents don't contact you one by one: the Director settles what the team can and sends you one report">
          <input type="checkbox" data-mdrelay ${d.relay ? "checked" : ""}><span aria-hidden="true"></span><b>Only the Director contacts me</b></label>
        <p class="small md-state">${icon(d.reporting ? "cycle" : d.relaying ? "inbox" : "info")}<span>${state}</span></p>
        <span class="row"><button type="button" class="btn sm" data-mdask ${!L || d.reporting || closed ? "disabled" : ""}>${icon(d.reporting ? "cycle" : "note")}${d.reporting ? "Writing…" : "Report now"}</button></span></section>
      ${latest ? card(v, latest, T, A, true) : `<div class="empty">${icon("inbox")} No report yet.${L && d.relay ? ` ${name} writes one as soon as there's something for you: questions, finished work, decisions.` : ""}</div>`}
      ${older.length ? `<details class="md-older"><summary>${plural(older.length, "earlier report")}</summary>${older.map(r => card(v, r, T, A, false)).join("")}</details>` : ""}`;
  }

  function wire(el) {
    el.addEventListener("click", async e => {
      const t = e.target, v = MiningWork.view(); if (!v) return;
      const ask = t.closest("[data-mdask]");
      if (ask) { const nv = await busy(ask, () => api(`${W}/comps/${v.comp.id}/report`, { method: "POST", body: {} })); if (nv) { MiningWork.apply(nv); Auth.toast(`${lead(nv)?.name || "The Director"} is writing a report`); } return; }
      const rd = t.closest("[data-mdread]");
      if (rd) { const nv = await busy(rd, () => api(`${W}/reports/${rd.dataset.mdread}/read`, { method: "POST" })); if (nv) MiningWork.apply(nv); }
    });
    el.addEventListener("change", async e => {
      if (!e.target.matches("[data-mdrelay]")) return;
      const v = MiningWork.view(), want = e.target.checked;
      const nv = await busy(null, () => api(`${W}/comps/${v.comp.id}`, { method: "PATCH", body: { relay: want } }));
      if (nv) { MiningWork.apply(nv); Auth.toast(want ? "Only the Director contacts you now" : "Agents come to you directly again"); } else e.target.checked = !want;
    });
    el.addEventListener("submit", async e => {
      const f = e.target.closest("[data-mdform]"); if (!f) return;
      e.preventDefault();
      const text = f.elements.text.value.trim(); if (!text) return;
      const nv = await busy($("button[type=submit]", f), () => api(`${W}/reports/${f.dataset.mdform}/reply`, { method: "POST", body: { text } }));
      if (nv) { MiningWork.apply(nv); Auth.toast(`Sent to ${lead(nv)?.name || "the Director"}`); }
    });
  }

  return { relaying, waiting, open, report, wire, direct };
})();
