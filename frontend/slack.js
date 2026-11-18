/* Slack: the team's Slack channel inside Subnet Scout, opened from the sidebar. Read the channel and its threads,
   post messages and replies (sent by the app under your name), share a subnet, note or notification, and see an
   unread count in the sidebar. Admins connect the Slack app and choose which alerts are posted automatically.
   The server polls Slack once for everyone; this page polls the server. */
const Slack = (() => {
  let d = { configured: false }, thread = null, wired = false, timer = null, bg = null, sending = false;
  const seenKey = () => "slack.seen." + (Auth.me()?.username || "");
  const seen = v => { try { if (v === undefined) return localStorage.getItem(seenKey()) || "0"; localStorage.setItem(seenKey(), v); } catch { return "0"; } };
  const ready = () => d.configured && d.can_post && !!d.channel;
  const KINDS = { new_subnet: "New subnets", emission: "Emission moves", opportunity: "Opportunities", fund: "Fund moves", news: "Subnet news" };

  async function init() {
    const on = !!Auth.me();
    $("#nav-slack").hidden = !on;
    if (!on) return;
    await load();
    clearInterval(bg); bg = setInterval(() => { if (S.view !== "slack") load(); }, 45000);
  }
  async function load() {
    try { d = await api("/api/slack"); } catch { return; }
    side();
  }
  function side() {
    $("#nav-slack").hidden = !Auth.me() || (!d.configured && !d.is_admin);
    $("#slack-lbl").textContent = d.channel ? `#${d.channel.name}` : d.configured ? "Slack" : "Connect Slack";
    const n = unread();
    $("#c-slack").textContent = n ? (n > 99 ? "99+" : n) : "";
  }
  const unread = () => (d.messages || []).filter(m => +m.ts > +seen() && m.scout_user !== d.me).length;

  // ---------- Slack mrkdwn -> safe HTML ----------
  const unent = s => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  function fmt(s) {
    return s.replace(/```([\s\S]+?)```/g, (_, c) => `<pre>${c.replace(/^\n/, "")}</pre>`)
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, "$1<b>$2</b>")
      .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?:;]|$)/g, "$1<i>$2</i>")
      .replace(/(^|[\s(])~([^~\n]+)~(?=[\s).,!?:;]|$)/g, "$1<s>$2</s>")
      .replace(/^&gt; ?(.*)$/gm, "<blockquote>$1</blockquote>")
      .replace(/\n/g, "<br>");
  }
  function html(text) {
    // Slack escapes &, < and > in text; <...> are links and mentions
    return (text || "").split(/(<[^<>]+>)/).map(p => {
      if (!p.startsWith("<")) return fmt(p.replace(/"/g, "&quot;").replace(/'/g, "&#39;"));
      const [target, label] = p.slice(1, -1).split("|");
      if (target.startsWith("@")) return `<span class="sl-mention">@${esc(unent(label || target.slice(1)))}</span>`;
      if (target.startsWith("#")) return `<span class="sl-mention">#${esc(unent(label || target.slice(1)))}</span>`;
      if (target.startsWith("!")) return `<span class="sl-mention">@${esc(target.slice(1).split("^")[0])}</span>`;
      const url = unent(target);
      if (!/^(https?:|mailto:)/i.test(url)) return esc(unent(label || target));
      return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(unent(label || url))}</a>`;
    }).join("");
  }

  // ---------- rendering ----------
  const time = ts => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const dayOf = ts => new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  const initials = n => esc((n || "?").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase());
  function msg(m, inThread = false) {
    const av = m.avatar ? `<img class="sl-av" src="${esc(m.avatar)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="${initials(m.name)}">` : `<span class="sl-av">${initials(m.name)}</span>`;
    return `<div class="sl-msg ${m.scout_user === d.me ? "mine" : ""}" data-ts="${esc(m.ts)}">${av}<div class="sl-body">
      <div class="sl-meta"><b>${esc(m.name)}</b>${m.scout_user ? `<span class="sl-tag">via AXoR</span>` : m.bot ? `<span class="sl-tag">app</span>` : ""}<span class="faint" title="${esc(new Date(m.ts * 1000).toLocaleString())}">${time(m.ts)}</span>${m.edited ? `<span class="faint">(edited)</span>` : ""}</div>
      <div class="sl-text">${html(m.text)}</div>
      ${m.files?.length ? `<div class="sl-files">${m.files.map(f => f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener noreferrer">${icon("file")}${esc(f.name)}</a>` : `<span>${icon("file")}${esc(f.name)}</span>`).join("")}</div>` : ""}
      ${!inThread && m.reply_count ? `<button type="button" class="sl-replies" data-thread="${esc(m.ts)}">${icon("chat")}${m.reply_count} repl${m.reply_count > 1 ? "ies" : "y"}${m.latest_reply ? `<span class="faint">Last ${ago(+m.latest_reply)}</span>` : ""}</button>` : ""}
    </div>${!inThread && ready() ? `<button type="button" class="iconbtn sm sl-act" data-thread="${esc(m.ts)}" title="Reply in thread" aria-label="Reply in thread">${icon("chat")}</button>` : ""}</div>`;
  }
  function log(items, mark) {
    let out = "", day = "", marked = false;
    for (const m of items) {
      const k = dayOf(m.ts);
      if (k !== day) { out += `<div class="sl-day"><span>${k}</span></div>`; day = k; }
      if (mark && !marked && +m.ts > +mark && m.scout_user !== d.me) { out += `<div class="sl-new"><span>New</span></div>`; marked = true; }
      out += msg(m);
    }
    return out;
  }
  const composer = (id, ph) => !ready() ? `<div class="sl-cant faint">${icon("lock")}${d.configured ? "Posting to Slack is limited to admins." : ""}</div>`
    : `<form class="composer sl-composer" id="${id}"><textarea name="text" rows="1" maxlength="3000" placeholder="${esc(ph)}"></textarea>
        <div class="composer-foot"><span class="faint small">Sent by the AXoR app as ${esc(d.me)} · Enter to send, Shift+Enter for a new line</span><button class="btn primary" type="submit" aria-label="Send">${icon("send")}</button></div></form>`;

  async function open() {
    wire();
    if (!d.configured && d.messages === undefined) $("#slack").innerHTML = Loading.cards(2, "card");
    await load();
    render(true);
    clearInterval(timer);
    timer = setInterval(async () => { if (S.view !== "slack") return clearInterval(timer); await load(); render(false); if (thread) loadThread(thread.ts, true); }, 8000);
  }
  function render(first) {
    const box = $("#slack");
    if (!d.configured) {
      box.innerHTML = `<div class="card chat-empty sl-setup"><span class="av c-violet xl" aria-hidden="true">${icon("hash")}</span><h3>Talk to your Slack channel from here</h3>
        <p class="muted">Read and post in one Slack channel, reply in threads, and share subnets, notes and notifications with your team.</p>
        ${d.is_admin ? `<button type="button" class="btn primary" data-sl="settings">${icon("plus")}Connect Slack</button>${help()}` : `<p class="faint">An admin hasn't connected Slack yet.</p>`}</div>`;
      return;
    }
    const log0 = $("#sl-log"), stick = !log0 || log0.scrollHeight - log0.scrollTop - log0.clientHeight < 80, keep = log0?.scrollTop;
    const draft = $("#sl-composer textarea")?.value, focus = document.activeElement?.closest("#sl-composer");
    const ch = d.channel || {}, url = d.team_url && ch.id ? `${d.team_url.replace(/\/$/, "")}/archives/${ch.id}` : null;
    const mark = first ? seen() : (box.dataset.mark || seen());
    box.dataset.mark = mark;
    box.innerHTML = `<div class="sl ${thread ? "with-thread" : ""}">
      <div class="card sl-main">
        <div class="sl-head"><span class="sl-hash">${icon("hash")}</span><div><b>${esc(ch.name || "…")}</b><small class="faint">${esc(ch.topic || "")}${d.team ? ` · ${esc(d.team)}` : ""}</small></div>
          <span class="spacer"></span>${url ? `<a class="btn sm" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${icon("external")}Open in Slack</a>` : ""}
          ${d.is_admin ? `<button type="button" class="iconbtn sm" data-sl="settings" title="Slack settings" aria-label="Slack settings">${icon("gear")}</button>` : ""}</div>
        ${d.error ? `<div class="sl-err">${icon("alert")}${esc(d.error)}</div>` : ""}
        <div class="sl-log" id="sl-log" aria-live="polite">${(d.messages || []).length ? log(d.messages, mark) : `<div class="chat-empty"><p class="muted">${d.updated ? "No messages in this channel yet. Say hello!" : "Loading the channel…"}</p></div>`}</div>
        ${composer("sl-composer", `Message #${ch.name || "channel"}`)}
      </div>
      ${thread ? `<div class="card sl-thread"><div class="sl-head"><b>Thread</b><span class="spacer"></span><button type="button" class="iconbtn sm" data-sl="close-thread" aria-label="Close thread">${icon("close")}</button></div>
        <div class="sl-log" id="sl-tlog">${thread.items ? thread.items.map((m, i) => msg(m, true) + (i === 0 && thread.items.length > 1 ? `<div class="sl-day"><span>${thread.items.length - 1} repl${thread.items.length > 2 ? "ies" : "y"}</span></div>` : "")).join("") : Loading.line("Loading thread…")}</div>
        ${composer("sl-tcomposer", "Reply…")}</div>` : ""}
    </div>`;
    const log1 = $("#sl-log");
    log1.scrollTop = stick ? log1.scrollHeight : keep;
    const ta = $("#sl-composer textarea");
    if (ta && draft) ta.value = draft;
    if (ta && (focus || first)) ta.focus();
    const tl = $("#sl-tlog"); if (tl) tl.scrollTop = tl.scrollHeight;
    if (S.view === "slack" && document.visibilityState === "visible" && d.messages?.length) { seen(d.messages[d.messages.length - 1].ts); side(); }
  }
  async function loadThread(ts, quiet = false) {
    if (!quiet) { thread = { ts, items: null }; render(false); }
    try { const r = await api(`/api/slack/thread?ts=${encodeURIComponent(ts)}`); if (thread?.ts === ts) { const draft = $("#sl-tcomposer textarea")?.value; thread.items = r.items; render(false); if (draft) $("#sl-tcomposer textarea").value = draft; } }
    catch (e) { toast(e.message); }
  }
  async function send(form, thread_ts) {
    const ta = form.elements.text, text = ta.value.trim();
    if (!text || sending) return;
    sending = true; form.querySelector("button[type=submit]").classList.add("loading");
    try {
      await api("/api/slack/messages", { method: "POST", body: { text, ...(thread_ts ? { thread_ts } : {}) } });
      ta.value = "";
      await load(); render(false);
      if (thread_ts) await loadThread(thread_ts, true);
      $(thread_ts ? "#sl-tcomposer textarea" : "#sl-composer textarea")?.focus();
    } catch (e) { toast(e.message); }
    finally { sending = false; form.querySelector("button[type=submit]")?.classList.remove("loading"); }
  }

  // ---------- sharing from elsewhere in the app ----------
  const shareButton = (kind, id, cls = "btn sm") => ready() ? `<button type="button" class="${cls}" data-sl-share="${kind}:${esc(String(id))}" title="Share to #${esc(d.channel.name)}">${icon("hash")}Share to Slack</button>` : "";
  function share(kind, id, label) {
    if (!ready()) return toast("Slack isn't connected.");
    Auth.modal(`<h3>${icon("hash")}Share to #${esc(d.channel.name)}</h3><p class="muted">${esc(label || "")}</p>
      <label class="in"><span>Add a comment (optional)</span><textarea name="comment" rows="3" maxlength="1000" class="sl-comment"></textarea></label>
      <p class="fine">Posted by the AXoR app as ${esc(d.me)}.</p>`,
      async f => { const r = await api("/api/slack/share", { method: "POST", body: { kind, id: String(id), comment: f.elements.comment.value } }); $("#modal").close(); toast(`Shared to #${r.channel || d.channel.name}`); load(); },
      { submit: "Share" });
  }

  // ---------- admin settings ----------
  const help = () => `<details class="sl-help"><summary>How to set up the Slack app</summary><ol>
      <li>Go to <a href="https://api.slack.com/apps" target="_blank" rel="noopener noreferrer">api.slack.com/apps</a> → <b>Create New App</b> → From scratch, pick your workspace.</li>
      <li>Under <b>OAuth &amp; Permissions</b>, add bot scopes: <code>channels:history</code>, <code>channels:read</code>, <code>chat:write</code>, <code>users:read</code>. Optional: <code>chat:write.customize</code> (posts show each member's name), <code>channels:join</code> (joins public channels by itself), <code>groups:history</code> + <code>groups:read</code> (private channels).</li>
      <li><b>Install to Workspace</b> and copy the <b>Bot User OAuth Token</b> (starts with <code>xoxb-</code>).</li>
      <li>For a private channel, type <code>/invite @your-app</code> in it. Then paste the token and channel here.</li></ol></details>`;
  async function settings() {
    let c;
    try { c = await api("/api/slack/config"); } catch (e) { return toast(e.message); }
    const st = c.status;
    const f = Auth.modal(`<h3>${icon("hash")}Slack</h3>
      ${st ? `<div class="sl-status ok">${icon("check")}<span>Connected to <b>${esc(st.team || "")}</b> as <b>@${esc(st.bot || "")}</b>, channel <b>#${esc(st.channel?.name || "")}</b>${st.missing?.length ? `<br><span class="no">Missing scopes: ${st.missing.map(esc).join(", ")}</span>` : ""}${st.customize ? "" : `<br><span class="faint">Without chat:write.customize, posts start with the member's name.</span>`}</span></div>`
        : c.configured ? `<div class="sl-status">${icon("info")}<span>Configured${c.token_source === "env" ? " from environment variables" : ""}; connecting…${c.error ? `<br><span class="no">${esc(c.error)}</span>` : ""}</span></div>` : ""}
      <label class="in"><span>Bot User OAuth Token</span><input name="token" type="password" autocomplete="off" placeholder="${c.token ? `Saved (${esc(c.token)}): leave empty to keep` : "xoxb-…"}"></label>
      <label class="in"><span>Channel</span><input name="channel" value="${esc(st?.channel ? "#" + st.channel.name : c.channel || "")}" placeholder="#mining or C0123456789"></label>
      <div class="field"><span class="lbl">Post these notifications to the channel automatically</span>
        <div class="sl-kinds">${c.kinds.map(k => `<label class="chk"><input type="checkbox" name="ap" value="${k}" ${c.autopost.includes(k) ? "checked" : ""}> ${KINDS[k] || k}</label>`).join("")}</div></div>
      <label class="chk"><input type="checkbox" name="members_post" ${c.members_post ? "checked" : ""}> Members can post and share (not only admins)</label>
      ${help()}
      ${c.configured ? `<p><button type="button" class="linkbtn danger-text" data-sl-disconnect>Disconnect Slack</button></p>` : ""}`,
      async f => {
        const body = { autopost: $$("[name=ap]:checked", f).map(x => x.value), members_post: f.elements.members_post.checked };
        const token = f.elements.token.value.trim(), channel = f.elements.channel.value.trim();
        const was = st?.channel ? "#" + st.channel.name : c.channel || "";
        if (token) body.token = token;
        if (token || channel !== was) body.channel = channel;
        await Admin.withSudo(() => api("/api/slack/config", { method: "PUT", body }));
        $("#modal").close(); toast(body.channel || body.token ? "Slack connected" : "Slack settings saved");
        await load(); if (S.view === "slack") render(true);
      }, { submit: c.configured ? "Save" : "Connect" });
    $("[data-sl-disconnect]", f)?.addEventListener("click", () => UI.confirm({
      title: "Disconnect Slack?", body: "The bot token is deleted and the channel leaves the sidebar for everyone. Messages in Slack stay. You can connect again with a token.", ok: "Disconnect", icon: "ban",
      run: async () => { await Admin.withSudo(() => api("/api/slack/config", { method: "DELETE" })); $("#modal").close(); toast("Slack disconnected"); thread = null; await load(); if (S.view === "slack") render(true); } }));
  }

  function wire() {
    if (wired) return; wired = true;
    const root = $("#view-slack");
    root.addEventListener("click", e => {
      const t = e.target, a = t.closest("[data-sl]")?.dataset.sl;
      if (a === "settings") return settings();
      if (a === "close-thread") { thread = null; return render(false); }
      const th = t.closest("[data-thread]"); if (th) return loadThread(th.dataset.thread);
    });
    root.addEventListener("submit", e => {
      e.preventDefault();
      if (e.target.id === "sl-composer") send(e.target);
      if (e.target.id === "sl-tcomposer") send(e.target, thread?.ts);
    });
    root.addEventListener("keydown", e => {
      const ta = e.target.closest?.(".sl-composer textarea"); if (!ta) return;
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ta.form.requestSubmit(); }
    });
    root.addEventListener("input", e => { const ta = e.target.closest?.(".sl-composer textarea"); if (ta) { ta.style.height = "auto"; ta.style.height = Math.min(180, ta.scrollHeight) + "px"; } });
  }
  // share buttons anywhere in the app
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-sl-share]"); if (!b) return;
    e.stopPropagation();
    const [kind, id] = b.dataset.slShare.split(":");
    share(kind, id, b.dataset.slLabel || (kind === "subnet" ? `SN${id} ${S.data?.subnets?.find(r => r.netuid === +id)?.name || ""}: task, earnings, registration, emission and risk` : ""));
  }, true);
  document.addEventListener("visibilitychange", () => { if (S.view === "slack" && document.visibilityState === "visible" && d.messages?.length) { seen(d.messages[d.messages.length - 1].ts); side(); } });

  return { init, open, load, share, shareButton, ready, settings };
})();
