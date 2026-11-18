/* Notifications: a bell in the header with an unread count, a panel of alerts (new subnets, emission moves,
   opportunities, fund moves, news for workspace subnets), per-user settings, a toast when new ones land
   and, if allowed, a browser notification. The server raises alerts after every chain update. */
const Notify = (() => {
  let feed = { items: [], unread: 0, last_read: 0, prefs: {} }, seen = 0, open = false, more = false;
  const KIND = {
    new_subnet: ["sprout", "New subnets", "A subnet is registered on chain"],
    emission: ["chart", "Emission moves", "A subnet's emission rises or falls 25% or more in 24 hours"],
    opportunity: ["target", "Opportunities", "A subnet starts paying at least 2× its running cost with a good top-miner chance and an open UID"],
    fund: ["coins", "Fund moves", "TAO and alpha price swings, registration cost halving or doubling, and a daily TAO-flow digest"],
    news: ["news", "Subnet news", "Releases and on-chain changes for subnets in your workspace"],
    announcement: ["send", "Announcements", "Messages from this server's admins"],
  };
  const enabled = () => !!Auth.me();
  const TITLE = document.title;

  async function init() {
    $("#bell").hidden = $("#nav-alerts").hidden = !enabled();
    if (!enabled()) return;
    $("#bell").onclick = e => { e.stopPropagation(); open ? close() : panel(); };
    NotifyPage.init();  // the sidebar item opens the Notifications page (notifications.js)
    await refresh(true);
  }
  async function refresh(first = false) {
    if (!enabled()) return;
    try { feed = await api("/api/alerts?limit=30"); more = feed.more; } catch { return; }
    badge();
    const top = feed.items[0]?.id || 0;
    // new since the last look, beyond what's already read: toast and (if allowed) a browser notification
    const fresh = first ? [] : feed.items.filter(a => a.id > Math.max(seen, feed.last_read));
    seen = Math.max(seen, top);
    if (fresh.length) {
      toast(fresh.length === 1 ? fresh[0].title : `${fresh.length} new notifications: ${fresh[0].title}`);
      if (feed.prefs.browser && "Notification" in window && Notification.permission === "granted")
        fresh.slice(0, 3).forEach(a => { try { new Notification(a.title, { body: a.body || "", tag: "scout-" + a.id }); } catch {} });
    }
    if (open) list();
  }
  // unread status in red: bell badge, Dashboard nav count, the dashboard card and the tab title
  function badge() {
    const n = feed.unread || 0, txt = n > 99 ? "99+" : String(n), b = $("#bell-n");
    b.textContent = txt; b.hidden = !n;
    $("#bell").classList.toggle("unread", !!n);
    $("#bell").setAttribute("aria-label", n ? `Notifications, ${n} unread` : "Notifications");
    $("#bell").title = n ? `${n} unread notification${n > 1 ? "s" : ""}` : "Notifications";
    const c = $("#c-alerts"); if (c) c.textContent = n ? txt : "";
    $$("[data-unread]").forEach(el => { el.textContent = n ? `${txt} new` : ""; el.hidden = !n; });
    document.title = n ? `(${txt}) ${TITLE}` : TITLE;
  }

  const itemIcon = a => a.kind === "emission" ? (a.level === "warn" ? "down" : "up") : KIND[a.kind]?.[0] || "info";
  function item(a, last) {
    return `<li class="nt ${a.id > last ? "unread" : ""} lv-${esc(a.level)}" data-nt="${a.id}" tabindex="0">
      <span class="nt-ic k-${esc(a.kind)}">${icon(itemIcon(a))}</span>
      <div><b>${esc(a.title)}</b>${a.body ? `<p>${esc(a.body)}</p>` : ""}<small class="faint" title="${esc(stamp(a.ts))}">${ago(a.ts)}${a.netuid != null ? ` · SN${a.netuid}` : ""}</small></div>
      ${Slack.ready() ? `<button type="button" class="iconbtn sm nt-share" data-sl-share="alert:${a.id}" data-sl-label="${esc(a.title)}" title="Share to Slack" aria-label="Share to Slack">${icon("hash")}</button>` : ""}</li>`;
  }
  const listHtml = (items, last) => items.length ? `<ul class="nt-list">${items.map(a => item(a, last)).join("")}</ul>`
    : `<div class="nt-empty">${icon("bell")}<p class="faint">No notifications yet. You'll hear about new subnets, emission moves, opportunities, fund moves and news here.</p></div>`;

  // opens under the header bell, or beside the sidebar's Notifications item
  function panel(anchor = $("#bell")) {
    document.querySelector(".popover.menu")?.remove();
    const pop = document.createElement("div");
    pop.className = "popover nt-pop"; pop.id = "nt-pop"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Notifications");
    document.body.appendChild(pop);
    open = true;
    list();
    const b = anchor.getBoundingClientRect(), side = anchor.id === "nav-alerts" && innerWidth > 900;
    pop.style.top = (side ? Math.min(b.top, innerHeight - pop.offsetHeight - 12) + scrollY : b.bottom + scrollY + 8) + "px";
    pop.style.left = (side ? b.right + 10 : Math.max(12, Math.min(b.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 12))) + "px";
    setTimeout(() => document.addEventListener("click", outside), 0);
    pop.addEventListener("click", click);
    pop.addEventListener("keydown", e => { if (e.key === "Escape") close(); if (e.key === "Enter" && e.target.matches("[data-nt]")) e.target.click(); });
    markRead();
  }
  function list() {
    const pop = $("#nt-pop"); if (!pop) return;
    const last = pop.dataset.last ? +pop.dataset.last : feed.last_read;
    pop.dataset.last = last;  // keep this opening's "unread" highlight while it's open
    pop.innerHTML = `<div class="nt-head"><b>Notifications</b><span class="spacer"></span>
        <button type="button" class="iconbtn sm" data-nt-act="settings" title="Notification settings" aria-label="Notification settings">${icon("gear")}</button>
        <button type="button" class="iconbtn sm" data-nt-act="all" title="Open the Notifications page" aria-label="Open the Notifications page">${icon("expand")}</button></div>
      ${listHtml(feed.items, last)}
      ${more ? `<button type="button" class="btn sm wide" data-nt-act="more">Show older</button>` : ""}`;
  }
  function outside(e) { if (!e.target.closest("#nt-pop, #bell, #nav-alerts, dialog")) close(); }
  function close() { $("#nt-pop")?.remove(); open = false; document.removeEventListener("click", outside); }
  async function markRead() {
    const top = feed.items[0]?.id; if (!top || top <= feed.last_read) return;
    try { await api("/api/alerts/read", { method: "POST", body: { id: top } }); feed.last_read = top; feed.unread = 0; badge(); } catch {}
  }
  async function click(e) {
    const a = e.target.closest("[data-nt-act]")?.dataset.ntAct;
    if (a === "settings") return settings();
    if (a === "all") { close(); return NotifyPage.open("inbox"); }
    if (a === "more") {
      try { const r = await api(`/api/alerts?limit=30&before=${feed.items[feed.items.length - 1].id}`); feed.items.push(...r.items); more = r.more; list(); } catch (x) { toast(x.message); }
      return;
    }
    const it = e.target.closest("[data-nt]"); if (!it) return;
    const x = feed.items.find(i => i.id === +it.dataset.nt); if (!x) return;
    if (x.url) return window.open(x.url, "_blank", "noopener");
    if (x.netuid != null) { close(); openDrawer(x.netuid); }
  }

  function settings() { close(); return NotifyPage.open("settings"); }

  return { init, refresh, listHtml, item, panel, settings, badge, feed: () => feed, kinds: () => KIND };
})();
