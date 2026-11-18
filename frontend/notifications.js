/* Notifications page: everything about notifications in one place (sidebar › Notifications, or #notifications).
   - Inbox: every alert in the bell, filtered by kind or unread, with older ones on demand.
   - Devices: Web Push on this browser (turn on, test, turn off) and every device you get pushes on (rename, test,
     remove). Pushes come from AXoR Push, this server's own push server (push/), through the browser's push service,
     encrypted for each device; sw.js shows them, even with no AXoR tab open.
   - Settings: per kind, whether it shows in the bell and whether it's pushed; workspace-only moves; quiet hours in
     your time zone; an hourly push cap; browser notifications while AXoR is open.
   - History: every push sent to your devices and whether it arrived.
   - Server (admins): the push server's state, announcements to everyone, admins or chosen users (sudo), recent
     messages with their deliveries, and every device on the server. */
const NotifyPage = (() => {
  const TABS = [["inbox", "Inbox", "inbox"], ["devices", "Devices", "devices"], ["settings", "Settings", "sliders"], ["history", "History", "clock"], ["server", "Server", "server"]];
  const SERVICE = { "fcm.googleapis.com": "Google (Chrome, Edge, Android)", "android.googleapis.com": "Google", "jmt17.google.com": "Google (Chromium)", "web.push.apple.com": "Apple (Safari)" };
  const STATUS = { sent: ["Delivered", "clear"], failed: ["Failed", "avoid"], gone: ["Removed", "caution"] };
  const PER_HOUR = [1, 3, 6, 10, 20, 60];
  let tab = null, wired = false;  // the last tab, read on first open (store lives in app.js, loaded after this file)
  let inbox = null, kind = "", unreadOnly = false, push = null, hist = null, srv = null, here = null, deliv = null;

  const admin = () => Auth.me()?.role === "admin";
  const err = e => e.message !== "cancelled" && toast(e.message, { kind: "error" });
  const service = h => SERVICE[h] || (/mozilla/.test(h || "") ? "Mozilla (Firefox)" : /windows/.test(h || "") ? "Microsoft (Windows)" : /apple/.test(h || "") ? "Apple (Safari)" : h || "–");
  const since = ts => !ts ? "never" : Date.now() / 1000 - ts < 86400 ? ago(ts) : new Date(ts * 1000).toLocaleDateString();
  const empty = html => `<div class="empty">${html}</div>`;
  const sw = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const unb64 = s => Uint8Array.from(atob((s + "=".repeat(-s.length & 3)).replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
  const sameKey = (sub, key) => { const k = sub.options?.applicationServerKey; return !k || new Uint8Array(k).join() === key.join(); };
  // tag "label" for a switch that isn't already inside a <label> (the table cells): the checkbox is invisible and zero-sized,
  // so without a label around it a click on the drawn track never reaches it
  const toggle = (attrs, on, disabled = false, tag = "span") => `<${tag} class="switch"><input type="checkbox" ${attrs} ${on ? "checked" : ""} ${disabled ? "disabled" : ""}><span></span></${tag}>`;

  // ---------- app-wide: messages from the service worker ----------
  function init() {
    if (!Auth.me() || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.addEventListener("message", e => {
      if (e.data?.type === "push") { Notify.refresh(); if (S.view === "notifications" && tab === "inbox") loadInbox(); }
      if (e.data?.type === "open") go(e.data.url);
    });
    navigator.serviceWorker.startMessages();
  }
  function go(h) {  // where a clicked notification points: #sn12, #notifications, #drive…
    h = String(h || "").replace(/^\//, "");
    if (/^#sn\d+$/.test(h)) return openDrawer(+h.slice(3));
    if (/^#[a-z]+$/.test(h) && $("#view-" + h.slice(1))) setView(h.slice(1));
  }

  // ---------- this browser's push subscription ----------
  async function registration() {
    return navigator.serviceWorker.getRegistration("/static/");
  }
  async function local() {
    if (!window.isSecureContext) return { state: "insecure" };
    if (!sw()) return { state: "unsupported" };
    const reg = await registration().catch(() => null);
    const sub = reg && await reg.pushManager.getSubscription().catch(() => null);
    const dev = sub && push?.devices.find(d => sub.endpoint.endsWith(d.endpoint_tail));
    if (Notification.permission === "denied") return { state: "denied", sub, dev };
    return { state: dev ? "on" : "off", sub, dev };
  }
  async function active(reg) {
    if (reg.active) return reg;
    const w = reg.installing || reg.waiting;
    await new Promise(r => { const f = () => w.state === "activated" && r(); w.addEventListener("statechange", f); f(); });
    return reg;
  }
  async function enable(label) {
    if (!push?.public_key) throw new Error(push?.error || "The push server isn't reachable.");
    if (await Notification.requestPermission() !== "granted")
      throw new Error(Notification.permission === "denied" ? "The browser blocked notifications for AXoR. Allow them in this site's settings, then try again." : "Notifications weren't allowed.");
    const reg = await active(await navigator.serviceWorker.register("/static/sw.js", { scope: "/static/" }));
    const key = unb64(push.public_key);
    let sub = await reg.pushManager.getSubscription();
    if (sub && !sameKey(sub, key)) { await sub.unsubscribe(); sub = null; }  // made for an earlier key pair of the push server
    sub ||= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    const { endpoint, keys } = sub.toJSON();
    await api("/api/push/devices", { method: "PUT", body: { endpoint, p256dh: keys.p256dh, auth: keys.auth, label } });
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (tz && push.prefs.tz === "UTC" && tz !== "UTC") await api("/api/push/prefs", { method: "PUT", body: { tz } }).catch(() => {});
  }
  async function disable() {
    if (here?.dev) await api(`/api/push/devices/${here.dev.id}`, { method: "DELETE" });
    await here?.sub?.unsubscribe().catch(() => {});
  }

  // ---------- loading ----------
  async function open(t) {
    tab = t || tab || store.get("ntp.tab", "inbox");
    if (t) store.set("ntp.tab", tab);
    if (tab === "server" && !admin()) tab = "inbox";
    if (S.view !== "notifications") return setView("notifications");  // setView calls back here
    wire();
    render();
    await load();
  }
  async function load() {
    if (tab === "inbox") await loadInbox();
    else if (tab === "devices" || tab === "settings") await loadPush();
    else if (tab === "history") await loadHistory();
    else if (tab === "server") await loadServer();
  }
  async function loadInbox(older = false) {
    try {
      const r = await api(`/api/alerts?limit=50${older && inbox?.items.length ? `&before=${inbox.items.at(-1).id}` : ""}`);
      if (older) { inbox.items.push(...r.items); inbox.more = r.more; }
      else inbox = { ...r, seen: inbox?.seen ?? r.last_read };  // keep this visit's "unread" highlight while it's open
    } catch (e) { inbox ||= { error: e.message }; }
    paint();
    const top = inbox.items?.[0]?.id;
    if (top && top > (inbox.last_read || 0)) {
      api("/api/alerts/read", { method: "POST", body: { id: top } }).then(() => { inbox.last_read = top; Notify.refresh(); }).catch(() => {});
    }
  }
  async function loadPush() {
    const [p, f] = await Promise.all([api("/api/push").catch(e => ({ error: e.message, devices: [], prefs: null })), api("/api/alerts?limit=1").catch(() => null)]);
    push = p;
    if (f) inbox = inbox ? { ...inbox, prefs: f.prefs } : { prefs: f.prefs, items: null };
    here = await local();
    paint();
  }
  async function loadHistory(older = false) {
    try {
      const r = await api(`/api/push/history?limit=50${older && hist?.items.length ? `&before=${hist.items.at(-1).id}` : ""}`);
      hist = older ? { items: hist.items.concat(r.items), more: r.more } : r;
    } catch (e) { hist = { error: e.message }; }
    paint();
  }
  async function loadServer() {
    try { srv = await api("/api/push/admin"); } catch (e) { srv = { error: e.message }; }
    paint();
  }

  // ---------- rendering ----------
  function render() {
    const tabs = TABS.filter(([k]) => k !== "server" || admin());
    $("#ntp").innerHTML = `<div class="ntp-head"><div><h1 class="page">Notifications</h1>
        <p class="muted">Alerts in the bell, push notifications on your devices, and what reaches you when.</p></div></div>
      <div class="card ntp-card"><nav class="src-tabs" role="tablist">${tabs.map(([k, l, ic]) => `<button type="button" role="tab" data-ntp-tab="${k}" aria-selected="${tab === k}">${icon(ic)}<span>${l}</span></button>`).join("")}</nav>
      <div class="ntp-body" id="ntp-body">${Loading.line("Loading…")}</div></div>`;
  }
  function paint() {
    const box = $("#ntp-body"); if (!box || S.view !== "notifications") return;
    $$("[data-ntp-tab]").forEach(b => b.setAttribute("aria-selected", b.dataset.ntpTab === tab));
    box.innerHTML = tab === "inbox" ? inboxHtml() : tab === "devices" ? devicesHtml() : tab === "settings" ? settingsHtml() : tab === "history" ? historyHtml() : serverHtml();
  }

  function inboxHtml() {
    if (!inbox?.items) return inbox?.error ? empty(esc(inbox.error)) : Loading.line("Loading notifications…");
    const K = Notify.kinds(), seen = inbox.seen ?? inbox.last_read;
    const items = inbox.items.filter(a => (!kind || a.kind === kind) && (!unreadOnly || a.id > seen));
    const unread = inbox.items.filter(a => a.id > seen).length;
    return `<div class="toolbar ntp-tools"><div class="chips" role="group" aria-label="Kind">
        <button type="button" class="chip" data-ntp-kind="" aria-pressed="${!kind}">All</button>
        ${Object.entries(K).map(([k, [ic, l]]) => `<button type="button" class="chip" data-ntp-kind="${k}" aria-pressed="${kind === k}">${l}</button>`).join("")}</div>
        <span class="spacer"></span>
        <label class="chk"><input type="checkbox" data-ntp-unread ${unreadOnly ? "checked" : ""}> Unread only${unread ? ` (${unread})` : ""}</label></div>
      ${items.length ? Notify.listHtml(items, seen) : empty(kind || unreadOnly ? "Nothing here with these filters." : "No notifications yet.")}
      ${inbox.more ? `<button type="button" class="btn sm wide" data-ntp="older">Show older</button>` : ""}`;
  }

  function hereHtml() {
    const st = here?.state, d = here?.dev;
    const ios = /iPhone|iPad/.test(navigator.userAgent) && !navigator.standalone;
    if (push?.error && !push.public_key) return `<div class="ntp-here off">${icon("alert")}<div><b>Push isn't available</b><p class="muted">${esc(push.error)}</p></div></div>`;
    const msg = {
      insecure: ["lock", "Push needs a secure connection", `Browsers only allow push on HTTPS pages (or localhost). You're on <code>${esc(location.origin)}</code>: open AXoR over HTTPS to turn push on here. The bell still works.`],
      unsupported: ["ban", "This browser can't receive push", ios ? "On iPhone and iPad, add AXoR to your Home Screen (Share › Add to Home Screen), open it from there and turn push on." : "Try a current Chrome, Edge, Firefox or Safari."],
      denied: ["ban", "Notifications are blocked for AXoR", "Allow notifications in this site's settings (the icon left of the address), then reload this page."],
    }[st];
    if (msg) return `<div class="ntp-here off">${icon(msg[0])}<div><b>${msg[1]}</b><p class="muted">${msg[2]}</p></div></div>`;
    if (st === "on") return `<div class="ntp-here on">${icon("check")}<div><b>Push is on for this device</b>
        <p class="muted">${esc(d.label || d.ua)} · ${esc(service(d.service))} · added ${since(d.created)}${push.quiet_now ? " · <b>quiet hours now</b>, so pushes are skipped" : ""}</p></div>
        <span class="spacer"></span><button type="button" class="btn sm" data-ntp="test-here">${icon("send")}Send a test</button>
        <button type="button" class="btn sm" data-ntp="off">Turn off</button></div>`;
    return `<div class="ntp-here">${icon("bell")}<div><b>Get notifications on this device</b>
        <p class="muted">Alerts you choose under Settings arrive here even when AXoR isn't open. Your browser will ask for permission.</p></div>
        <span class="spacer"></span><button type="button" class="btn primary" data-ntp="on">${icon("bell")}Turn on push</button></div>`;
  }
  function devicesHtml() {
    if (!push) return Loading.line("Checking push…");
    const devs = push.devices || [];
    return `${hereHtml()}
      <h3 class="ntp-h">${icon("devices")}Your devices <span class="faint">${devs.length || ""}</span><span class="spacer"></span>
        ${devs.length ? `<button type="button" class="btn sm" data-ntp="test-all">${icon("send")}Test all</button>` : ""}</h3>
      ${devs.length ? `<div class="tablewrap flat"><table class="grid ntp-table"><thead><tr><th>Device</th><th>Push service</th><th>Added</th><th>Last delivered</th><th class="r">Sent</th><th>Status</th><th></th></tr></thead><tbody>
        ${devs.map(d => `<tr><td><b>${esc(d.label || d.ua)}</b>${here?.dev?.id === d.id ? ` <span class="badge new">This device</span>` : ""}${d.label ? `<br><small class="faint">${esc(d.ua)}</small>` : ""}</td>
          <td>${esc(service(d.service))}</td><td>${since(d.created)}</td><td>${since(d.last_ok)}</td><td class="r num">${d.sent}</td>
          <td>${d.fails ? `<span class="badge avoid" title="${esc(d.last_error)}">${d.fails} failed</span>` : `<span class="badge clear">OK</span>`}</td>
          <td class="ntp-acts"><button type="button" class="iconbtn sm" data-ntp-test="${d.id}" title="Send a test" aria-label="Send a test">${icon("send")}</button>
            <button type="button" class="iconbtn sm" data-ntp-rename="${d.id}" title="Rename" aria-label="Rename">${icon("edit")}</button>
            <button type="button" class="iconbtn sm" data-ntp-remove="${d.id}" title="Remove" aria-label="Remove">${icon("trash")}</button></td></tr>`).join("")}
        </tbody></table></div>` : `<p class="faint">No devices yet. Turn push on above, on every browser or phone you want notifications on.</p>`}
      <p class="fine ntp-note">${icon("lock")}Each notification is encrypted for the device it goes to. AXoR's own push server sends it through the browser maker's push service, which only relays the ciphertext.</p>`;
  }

  function settingsHtml() {
    if (!push || !inbox?.prefs) return Loading.line("Loading settings…");
    const K = Notify.kinds(), a = inbox.prefs, p = push.prefs, q = p?.quiet;
    const zones = (Intl.supportedValuesOf?.("timeZone") || []).concat(p?.tz || [], Intl.DateTimeFormat().resolvedOptions().timeZone);
    const noPush = !push.public_key;
    return `<div class="tablewrap flat ntp-kinds"><table class="grid"><thead><tr><th>Notification</th><th class="c">In the bell</th><th class="c">Push</th></tr></thead><tbody>
        ${Object.entries(K).map(([k, [ic, l, d]]) => {
          const ann = k === "announcement", bell = ann || a[k] !== false;
          return `<tr><td><div class="ntp-kind"><span class="nt-ic k-${k}">${icon(ic)}</span><span><b>${l}</b><small class="faint">${d}</small></span></div></td>
            <td class="c">${toggle(`data-ntp-bell="${k}" aria-label="${l} in the bell"`, bell, ann, "label")}</td>
            <td class="c">${p ? toggle(`data-ntp-push="${k}" aria-label="Push ${l}"`, ann ? p.announcements : bell && p.kinds[k], noPush || !bell, "label") : "–"}</td></tr>`;
        }).join("")}</tbody></table></div>
      <p class="fine">Push only sends what also shows in your bell. Alerts that land together after a chain update arrive as one push.${noPush ? ` ${esc(push.error || "")}` : ""}</p>
      <div class="ntp-grid">
        <label class="toggle-row card"><span><b>Only my workspace subnets</b><small class="faint">Emission and fund moves only for subnets in My workspace (news always is)</small></span>${toggle(`data-ntp-alert="workspace_only"`, a.workspace_only)}</label>
        <label class="toggle-row card"><span><b>Browser notifications while AXoR is open</b><small class="faint">Pop-ups from an open tab, without push</small></span>${toggle(`data-ntp-alert="browser"`, a.browser, !("Notification" in window))}</label>
        ${p ? `<div class="card ntp-quiet"><label class="toggle-row"><span><b>Quiet hours</b><small class="faint">No pushes in this window, every day. The bell still fills.${push.quiet_now ? " <b>Quiet now.</b>" : ""}</small></span>${toggle(`data-ntp-quiet`, q.on)}</label>
          <div class="ntp-quiet-row"><label>From <input type="time" data-ntp-time="quiet_start" value="${esc(q.start)}" ${q.on ? "" : "disabled"}></label>
            <label>to <input type="time" data-ntp-time="quiet_end" value="${esc(q.end)}" ${q.on ? "" : "disabled"}></label>
            <label class="ntp-tz">Time zone <select data-ntp-tz>${[...new Set(zones)].sort().map(z => `<option ${z === p.tz ? "selected" : ""}>${esc(z)}</option>`).join("")}</select></label></div></div>
        <label class="toggle-row card"><span><b>At most</b><small class="faint">Pushes per hour; more wait in the bell</small></span>
          <select data-ntp-cap>${PER_HOUR.map(n => `<option value="${n}" ${n === p.per_hour ? "selected" : ""}>${n} an hour</option>`).join("")}</select></label>` : ""}
      </div>`;
  }

  function historyHtml() {
    if (!hist) return Loading.line("Loading history…");
    if (hist.error) return empty(esc(hist.error));
    if (!hist.items.length) return empty("Nothing pushed to your devices yet.");
    return `<div class="tablewrap flat"><table class="grid ntp-table"><thead><tr><th>When</th><th>Notification</th><th>Device</th><th>Result</th></tr></thead><tbody>
      ${hist.items.map(h => { const [l, c] = STATUS[h.status] || [h.status, ""]; return `<tr><td title="${esc(stamp(h.ts))}">${since(h.ts)}</td>
        <td><b>${esc(h.title || "")}</b>${h.body ? `<br><small class="faint ntp-clip">${esc(h.body)}</small>` : ""}${h.sender ? `<br><small class="faint">from ${esc(h.sender)}</small>` : ""}</td>
        <td>${esc(h.device)}</td><td><span class="badge ${c}">${l}</span>${h.detail ? `<br><small class="faint ntp-clip" title="${esc(h.detail)}">${esc(h.detail)}</small>` : ""}</td></tr>`; }).join("")}
      </tbody></table></div>${hist.more ? `<button type="button" class="btn sm wide" data-ntp="older-history">Show older</button>` : ""}`;
  }

  function serverHtml() {
    if (!srv) return Loading.line("Reading the push server…");
    if (srv.error) return empty(esc(srv.error));
    const i = srv.info, tile = (ic, l, v, sub = "") => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value num">${v}</div><div class="sub">${sub}</div></div>`;
    return `<div class="stats">${tile("devices", "Devices", i.devices, `${i.users} user${i.users === 1 ? "" : "s"}`)}${tile("send", "Delivered, 24 h", i.sent_24h, `${i.messages_24h} messages`)}
        ${tile("alert", "Failed, 24 h", i.failed_24h, `${i.gone_24h} ended by the browser`)}${tile("cycle", "Queue", i.queue, `${i.workers} senders`)}</div>
      <div class="ntp-grid2">
        <form class="card ntp-send" id="ntp-send" novalidate><h3 class="ntp-h">${icon("send")}Send an announcement</h3>
          <label class="in"><span>Title</span><input name="title" maxlength="120" required></label>
          <label class="in"><span>Message <em class="opt">optional</em></span><textarea name="body" maxlength="1000" rows="3"></textarea></label>
          <label class="in"><span>Link <em class="opt">optional</em></span><input name="url" maxlength="500" placeholder="/#drive or https://…"></label>
          <div class="seg full" role="group" aria-label="Audience">${[["all", "Everyone"], ["admins", "Admins"], ["users", "Chosen users"]].map(([v, l], n) => `<button type="button" data-ntp-aud="${v}" aria-pressed="${!n}">${l}</button>`).join("")}</div>
          <div class="ntp-users" hidden><input type="search" placeholder="Filter users" data-ntp-ufilter>
            <div class="ntp-ulist">${srv.users.map(u => `<label class="chk"><input type="checkbox" name="u" value="${u.id}"> ${esc(u.username)}${u.role === "admin" ? ` <span class="faint">admin</span>` : ""}</label>`).join("")}</div></div>
          <label class="chk" data-ntp-inapp><input type="checkbox" name="in_app"> Also show it in everyone's bell</label>
          <label class="chk"><input type="checkbox" name="urgent"> Urgent: through quiet hours and hourly limits</label>
          <p class="err" role="alert"></p>
          <div class="row end"><button class="btn primary" type="submit">${icon("send")}Send</button></div></form>
        <div class="card ntp-info"><h3 class="ntp-h">${icon("server")}Push server</h3>
          <dl class="ntp-dl"><dt>Public key (VAPID)</dt><dd><code class="ntp-key">${esc(i.public_key)}</code> <button type="button" class="iconbtn sm" data-ntp-copy="${esc(i.public_key)}" title="Copy" aria-label="Copy the public key">${icon("copy")}</button></dd>
            <dt>Contact (VAPID subject)</dt><dd>${esc(i.subject)}${/localhost/.test(i.subject) ? ` <span class="badge caution" title="Apple's push service rejects it; set PUSH_SUBJECT to a mailto: or https: address">set PUSH_SUBJECT</span>` : ""}</dd>
            <dt>Push services allowed</dt><dd>${i.hosts.map(h => `<code>${esc(h)}</code>`).join(" ")}</dd>
            <dt>Devices by service</dt><dd>${Object.entries(i.services).map(([h, n]) => `${esc(service(h))}: ${n}`).join(" · ") || "none"}</dd>
            <dt>Kept</dt><dd>${i.keep_days} days of deliveries · devices removed after ${i.max_fails} failures in a row</dd>
            <dt>Running since</dt><dd>${esc(stamp(i.started))}</dd></dl></div>
      </div>
      <h3 class="ntp-h">${icon("inbox")}Recent messages</h3>
      ${srv.messages.length ? `<div class="tablewrap flat"><table class="grid ntp-table"><thead><tr><th>When</th><th>Message</th><th>From</th><th class="r">Devices</th><th class="r">Delivered</th><th class="r">Failed</th><th></th></tr></thead><tbody>
        ${srv.messages.map(m => `<tr><td title="${esc(stamp(m.ts))}">${since(m.ts)}</td><td><b>${esc(m.title)}</b><br><small class="faint">${esc(m.kind || "")}</small></td><td>${esc(m.sender || "AXoR")}</td>
          <td class="r num">${m.targets}</td><td class="r num">${m.sent}</td><td class="r num">${m.failed + m.gone}</td>
          <td><button type="button" class="btn sm" data-ntp-msg="${m.id}" aria-expanded="${deliv?.id === m.id}">Deliveries</button></td></tr>
          ${deliv?.id === m.id ? `<tr class="ntp-deliv"><td colspan="7">${delivHtml()}</td></tr>` : ""}`).join("")}</tbody></table></div>` : `<p class="faint">Nothing sent yet.</p>`}
      <h3 class="ntp-h">${icon("devices")}All devices</h3>
      ${srv.devices.length ? `<div class="tablewrap flat"><table class="grid ntp-table"><thead><tr><th>User</th><th>Device</th><th>Push service</th><th>Added</th><th>Last delivered</th><th>Status</th><th></th></tr></thead><tbody>
        ${srv.devices.map(d => `<tr><td>${esc(d.username)}</td><td>${esc(d.label || d.ua)}</td><td>${esc(service(d.service))}</td><td>${since(d.created)}</td><td>${since(d.last_ok)}</td>
          <td>${d.fails ? `<span class="badge avoid" title="${esc(d.last_error)}">${d.fails} failed</span>` : `<span class="badge clear">OK</span>`}</td>
          <td><button type="button" class="iconbtn sm" data-ntp-adrop="${d.id}" data-name="${esc(`${d.username}: ${d.label || d.ua}`)}" title="Remove" aria-label="Remove">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>` : `<p class="faint">No one has turned push on yet.</p>`}`;
  }

  // ---------- actions ----------
  function wire() {
    if (wired) return; wired = true;
    $("#ntp").addEventListener("click", click);
    $("#ntp").addEventListener("change", change);
    $("#ntp").addEventListener("input", e => {
      if (e.target.matches("[data-ntp-ufilter]")) { const q = e.target.value.toLowerCase(); $$(".ntp-ulist .chk").forEach(l => l.hidden = !l.textContent.toLowerCase().includes(q)); }
    });
    $("#ntp").addEventListener("submit", e => { if (e.target.id === "ntp-send") { e.preventDefault(); send(e.target); } });
  }
  async function click(e) {
    const t = e.target, d = k => t.closest(`[data-${k}]`)?.dataset;
    if (d("ntp-tab")) { tab = d("ntp-tab").ntpTab; store.set("ntp.tab", tab); paint(); return load(); }
    if (d("ntp-kind")) { kind = d("ntp-kind").ntpKind; return paint(); }
    if (d("ntp-aud")) {
      const v = d("ntp-aud").ntpAud;
      $$("[data-ntp-aud]").forEach(b => b.setAttribute("aria-pressed", b.dataset.ntpAud === v));
      $(".ntp-users").hidden = v !== "users"; $("[data-ntp-inapp]").hidden = v !== "all";
      return;
    }
    if (d("ntp-copy")) { navigator.clipboard?.writeText(d("ntp-copy").ntpCopy).then(() => toast("Copied")); return; }
    if (t.closest("[data-sl-share]")) return;  // Slack's own handler shares it
    const nt = t.closest("[data-nt]");
    if (nt) {
      const a = inbox?.items?.find(i => i.id === +nt.dataset.nt);
      if (a?.url) return window.open(a.url, "_blank", "noopener");
      if (a?.netuid != null) return openDrawer(a.netuid);
      return;
    }
    const act = d("ntp")?.ntp;
    try {
      if (act === "older") return loadInbox(true);
      if (act === "older-history") return loadHistory(true);
      if (act === "on") { await busyBtn(t, () => enable("")); toast("Push is on for this device", { kind: "success" }); return loadPush(); }
      if (act === "off") { await busyBtn(t, disable); toast("Push is off for this device"); return loadPush(); }
      if (act === "test-here") return sent(await api(`/api/push/devices/${here.dev.id}/test`, { method: "POST" }));
      if (act === "test-all") return sent(await api("/api/push/test", { method: "POST" }));
      if (d("ntp-test")) return sent(await api(`/api/push/devices/${d("ntp-test").ntpTest}/test`, { method: "POST" }));
      if (d("ntp-rename")) return rename(push.devices.find(x => x.id === +d("ntp-rename").ntpRename));
      if (d("ntp-remove")) {
        const x = push.devices.find(v => v.id === +d("ntp-remove").ntpRemove);
        const mine = here?.dev?.id === x.id;
        return UI.confirm({ title: "Remove this device?", body: `It stops getting push notifications${mine ? ". It's the device you're using now" : ""}. You can turn push on there again later.`,
          items: [esc(x.label || x.ua)], ok: "Remove", run: async () => { if (mine) await disable(); else await api(`/api/push/devices/${x.id}`, { method: "DELETE" }); await loadPush(); } });
      }
      if (d("ntp-msg")) return deliveries(+d("ntp-msg").ntpMsg);
      if (d("ntp-adrop")) {
        const { ntpAdrop: id, name } = d("ntp-adrop");
        return UI.confirm({ title: "Remove this device?", body: "That person stops getting push notifications there until they turn push on again.", items: [esc(name)], ok: "Remove",
          run: () => Admin.withSudo(() => api(`/api/push/admin/devices/${id}`, { method: "DELETE" })).then(loadServer) });
      }
    } catch (x) { err(x); }
  }
  async function busyBtn(b, fn) { b.disabled = true; try { return await fn(); } finally { b.disabled = false; } }
  const sent = r => toast(r.devices ? `Test sent to ${r.devices} device${r.devices > 1 ? "s" : ""}. It should pop up in a few seconds.` : "No device to send to.", { kind: r.devices ? "success" : undefined });

  async function change(e) {
    const t = e.target, ds = t.dataset;
    try {
      if (ds.ntpUnread !== undefined) { unreadOnly = t.checked; return paint(); }
      if (ds.ntpBell) { inbox.prefs = await api("/api/alerts/prefs", { method: "PUT", body: { [ds.ntpBell]: t.checked } }); Notify.refresh(); }
      else if (ds.ntpAlert) {
        let on = t.checked;
        if (ds.ntpAlert === "browser" && on && Notification.permission !== "granted" && await Notification.requestPermission() !== "granted") { on = false; toast("The browser blocked notifications; the bell still works."); }
        inbox.prefs = await api("/api/alerts/prefs", { method: "PUT", body: { [ds.ntpAlert]: on } });
      }
      else if (ds.ntpPush) push.prefs = await api("/api/push/prefs", { method: "PUT", body: ds.ntpPush === "announcement" ? { announcements: t.checked } : { kinds: { [ds.ntpPush]: t.checked } } });
      else if (ds.ntpQuiet !== undefined) push.prefs = await api("/api/push/prefs", { method: "PUT", body: { quiet_on: t.checked, tz: push.prefs.tz === "UTC" ? Intl.DateTimeFormat().resolvedOptions().timeZone : undefined } });
      else if (ds.ntpTime) push.prefs = await api("/api/push/prefs", { method: "PUT", body: { [ds.ntpTime]: t.value } });
      else if (ds.ntpTz !== undefined) push.prefs = await api("/api/push/prefs", { method: "PUT", body: { tz: t.value } });
      else if (ds.ntpCap !== undefined) push.prefs = await api("/api/push/prefs", { method: "PUT", body: { per_hour: +t.value } });
      else return;
      if (push && ("ntpQuiet" in ds || "ntpTime" in ds || "ntpTz" in ds)) push.quiet_now = (await api("/api/push").catch(() => push)).quiet_now;
      toast("Saved", { kind: "success" });
    } catch (x) { err(x); }
    paint();
  }

  function rename(x) {
    Auth.modal(`<h3>${icon("edit")}Rename device</h3><label class="in"><span>Name</span><input name="label" maxlength="60" value="${esc(x.label)}" placeholder="${esc(x.ua)}"></label>`, async f => {
      await api(`/api/push/devices/${x.id}`, { method: "PATCH", body: { label: f.elements.label.value.trim() } });
      $("#modal").close(); loadPush();
    });
  }
  async function send(f) {
    const aud = $("[data-ntp-aud][aria-pressed=true]").dataset.ntpAud, e = $(".err", f);
    const users = [...f.querySelectorAll("input[name=u]:checked")].map(i => +i.value);
    const body = { title: f.elements.title.value.trim(), body: f.elements.body.value.trim(), url: f.elements.url.value.trim(), audience: aud, users,
                   in_app: aud === "all" && f.elements.in_app.checked, urgent: f.elements.urgent.checked };
    e.textContent = !body.title ? "Give it a title." : aud === "users" && !users.length ? "Pick at least one user." : "";
    if (e.textContent) return;
    const b = $("[type=submit]", f);
    try {
      const r = await busyBtn(b, () => Admin.withSudo(() => api("/api/push/admin/broadcast", { method: "POST", body })));
      toast(`Sent to ${r.devices} device${r.devices === 1 ? "" : "s"} of ${r.users} user${r.users === 1 ? "" : "s"}${r.held ? `; ${r.held} held back by their quiet hours or settings` : ""}${r.in_app ? ", and posted to the bell" : ""}.`, { kind: "success" });
      f.reset(); loadServer();
    } catch (x) { if (x.message !== "cancelled") e.textContent = x.message; }
  }
  async function deliveries(id) {  // opens under the message's row; a second click closes it
    if (deliv?.id === id) { deliv = null; return paint(); }
    deliv = { id, items: null }; paint();
    deliv = { id, ...(await api(`/api/push/admin/messages/${id}`).catch(e => ({ error: e.message }))) }; paint();
  }
  function delivHtml() {
    if (deliv.error) return `<p class="faint">${esc(deliv.error)}</p>`;
    if (!deliv.items) return Loading.line("Loading deliveries…");
    if (!deliv.items.length) return `<p class="faint">No deliveries recorded yet: they may still be in the queue.</p>`;
    return `<ul class="ntp-dlist">${deliv.items.map(h => { const [l, c] = STATUS[h.status] || [h.status, ""];
      return `<li><span class="badge ${c}">${l}</span><b>${esc(h.username)}</b><span class="faint">${esc(h.device)} · ${since(h.ts)}</span>${h.detail ? `<small class="faint ntp-clip" title="${esc(h.detail)}">${esc(h.detail)}</small>` : ""}</li>`; }).join("")}</ul>`;
  }

  return { init, open, go };
})();
