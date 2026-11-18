// Agents → My logins: your own Claude Code / Codex plan for Terminal and Codex models (backend: cli_accounts.py).
// Optional: every model on the site is shared, so without one your runs use the server's login (or a teammate's when
// that's off); with one, your runs use yours first. Requests to connect and the
// admins' team list (who connected, who was asked) are cli-invites.js.
const CliAccounts = (() => {
  let poll = null;
  const ago = t => t ? new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
  const at = t => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  function badge(st) {
    if (!st.connected) return st.uses === "server" ? `<span class="badge new">Using the server's login</span>`
      : st.uses === "shared" ? `<span class="badge new">Using a shared login</span>` : `<span class="badge new">Not connected</span>`;
    if (!st.ok) return `<span class="badge avoid">${icon("alert")}Not working</span>`;
    if (st.limit_until) return `<span class="badge avoid">${icon("clock")}Usage limit until ${at(st.limit_until)}</span>`;
    return `<span class="badge clear">${icon("check")}Connected</span>`;
  }

  // tag "div" when the card sits inside another form (Agents → Models → Add model): forms can't nest
  function claudeCard(st, tag = "form") {
    return `<${tag} class="prov-card cla-card" data-cla="terminal"${tag === "form" ? " novalidate" : ""}>
      <div class="cla-top"><b>Claude Code</b>${badge(st)}</div>
      <p class="faint small">Terminal models (Claude Code · Opus, Sonnet…) run on your own Claude plan.${st.connected ? ` Connected ${esc(ago(st.connected_at))}.` : ""}</p>
      ${st.connected ? "" : `<ol class="cla-steps small">
        <li>On your own computer, where Claude Code is signed in, run <code>claude setup-token</code>.</li>
        <li>Paste the <code>sk-ant-oat…</code> token it prints. It's stored encrypted, never shown again, and you can remove it any time.</li></ol>
        <label class="in"><span class="faint small">Token</span><input type="password" name="token" autocomplete="off" spellcheck="false" placeholder="sk-ant-oat01-…"></label>`}
      ${st.error ? `<p class="err small">${esc(st.error)}</p>` : ""}<p class="err small" data-err></p>
      <div class="cla-actions">${st.connected
        ? `<button type="button" class="btn sm" data-test>Test</button><button type="button" class="btn sm danger-text" data-remove>Remove</button>`
        : `<button type="${tag === "form" ? "submit" : "button"}" class="btn primary sm" data-connect>Connect</button>`}</div>
    </${tag}>`;
  }

  function codexCard(st) {
    const L = st.login && ["starting", "waiting"].includes(st.login.state) ? st.login : null;
    const failed = st.login && ["failed", "expired"].includes(st.login.state) ? st.login.error : "";
    return `<div class="prov-card cla-card" data-cla="codex">
      <div class="cla-top"><b>Codex</b>${badge(st)}</div>
      <p class="faint small">Codex models run on your own ChatGPT plan.${st.connected ? ` Connected ${esc(ago(st.connected_at))}.` : ""}</p>
      ${L && !L.code ? `<div class="cla-device">${Loading.line("Getting a sign-in code from OpenAI…")}</div>` : ""}
      ${L && L.code ? `<div class="cla-device">
          <p class="small">1. Open <a href="${esc(L.url || "")}" target="_blank" rel="noopener noreferrer">${esc(L.url || "")}</a> and sign in with your ChatGPT account.</p>
          <p class="small">2. Enter this code (it expires in <span data-left>${Math.ceil(L.expires_in / 60)}</span> min):</p>
          <div class="cla-code">${esc(L.code)}</div>
          <p class="faint small">You started this sign-in from AXoR just now, so this code is yours. Never enter a code someone else sends you.</p>
        </div>` : ""}
      ${st.error ? `<p class="err small">${esc(st.error)}</p>` : ""}${failed ? `<p class="err small">${esc(failed)}</p>` : ""}<p class="err small" data-err></p>
      <div class="cla-actions">${L ? `<button type="button" class="btn sm" data-cancel>Cancel</button>`
        : st.connected ? `<button type="button" class="btn sm" data-test>Test</button><button type="button" class="btn sm danger-text" data-remove>Remove</button>`
        : `<button type="button" class="btn primary sm" data-start>Sign in with ChatGPT</button>`}</div>
    </div>`;
  }

  async function open() {
    const d = $("#agentdlg");
    d.innerHTML = `<div class="settings-dlg">${Loading.line("Loading your logins…")}</div>`;
    if (!d.open) d.showModal();
    d.onclick = e => { if (e.target.closest("[data-close]") || e.target === d) d.close(); };
    d.addEventListener("close", stop, { once: true });
    await render();
  }

  function stop() { clearTimeout(poll); poll = null; }

  async function render(msg) {
    const d = $("#agentdlg");
    if (!d.open) return stop();
    let s;
    try { s = await api("/api/cli-accounts"); } catch (e) { d.innerHTML = `<div class="settings-dlg"><p class="err">${esc(e.message)}</p></div>`; return; }
    const P = s.providers;
    d.innerHTML = `<div class="settings-dlg">
      <div class="sd-head"><h3>${icon("key")}My logins</h3><button type="button" class="iconbtn" data-close aria-label="Close">${icon("close")}</button></div>
      <p class="muted small">Optional. Every model on this site is shared, so you can give missions without connecting anything:
        your runs use the server's login, or a teammate's when the server has none. Connect your own Claude Code or Codex to run
        your agents, chats and teams on <b>your</b> plan first, with its own usage limit; teammates without a login may share it
        when the server's login is off.</p>
      <div data-cli-asked></div>
      <div class="prov-grid">${claudeCard(P.terminal)}${codexCard(P.codex)}</div>
      ${s.is_admin ? `<div data-cli-team></div>` : ""}
    </div>`;
    hydrateIcons(d);
    if (msg) Auth.toast(msg);
    wire(d, P);
    CliInvites.fill(d, s, render);  // the requests you were sent; admins: the team's logins and asking people to connect
    stop();
    const L = P.codex.login;
    if (L && ["starting", "waiting"].includes(L.state)) poll = setTimeout(() => render(), 3000);
    else if (L && L.state === "done" && !render.doneShown) { render.doneShown = true; Auth.toast("Your Codex is connected"); }
  }

  // again(msg): redraw after a change (the My logins dialog, or a card mounted elsewhere)
  function wire(d, P, again = render) {
    const busy = async (btn, fn) => {
      const card = btn.closest(".cla-card"), err = $("[data-err]", card);
      btn.disabled = true; btn.classList.add("loading"); err.textContent = "";
      try { await fn(); } catch (e) { if (e.message !== "cancelled") err.textContent = e.message; btn.disabled = false; btn.classList.remove("loading"); }
    };
    const f = $('[data-cla="terminal"]', d), tin = f && $("input[name=token]", f);
    const go = () => {
      const token = tin.value.trim(), btn = $("[data-connect]", f);
      if (!token) { $("[data-err]", f).textContent = "Paste the token first."; return; }
      busy(btn, async () => { const r = await api("/api/cli-accounts/terminal", { method: "POST", body: { token } }); again(r.message); });
    };
    if (f && tin) {
      if (f.tagName === "FORM") f.onsubmit = e => { e.preventDefault(); go(); };
      else { $("[data-connect]", f).onclick = go; tin.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); go(); } }; }
    }
    $$("[data-test]", d).forEach(b => b.onclick = () => busy(b, async () => {
      const p = b.closest(".cla-card").dataset.cla;
      const r = await api(`/api/cli-accounts/${p}/test`, { method: "POST" }); again(r.message);
    }));
    $$("[data-remove]", d).forEach(b => b.onclick = () => {
      const p = b.closest(".cla-card").dataset.cla;
      UI.confirm({ title: `Remove your ${esc(P[p].name)} login?`, body: "It's deleted from the server. Your runs on these models stop until you connect it again.", ok: "Remove", icon: "ban",
        run: async () => { const r = await api(`/api/cli-accounts/${p}`, { method: "DELETE" }); again(r.message); } });
    });
    $("[data-start]", d)?.addEventListener("click", e => busy(e.currentTarget, async () => {
      render.doneShown = false;
      await api("/api/cli-accounts/codex/start", { method: "POST" }); again();
    }));
    $("[data-cancel]", d)?.addEventListener("click", e => busy(e.currentTarget, async () => { await api("/api/cli-accounts/codex/cancel", { method: "POST" }); again(); }));
  }

  // one of your login cards inside another view (Agents → Models → Add model → CLI → My own login).
  // onDraw(box) runs after every redraw; a Codex sign-in in progress is polled while the box is on the page.
  let mpoll = null;
  async function mount(box, p, onDraw, msg) {
    clearTimeout(mpoll);
    let s;
    try { s = await api("/api/cli-accounts"); } catch (e) { if (box.isConnected) box.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    if (!box.isConnected) return;
    const P = s.providers, again = m => mount(box, p, onDraw, m);
    box.innerHTML = p === "codex" ? codexCard(P.codex) : claudeCard(P.terminal, "div");
    hydrateIcons(box);
    if (msg) Auth.toast(msg);
    wire(box, P, again);
    onDraw?.(box);
    const L = P[p].login;
    if (p === "codex" && L && ["starting", "waiting"].includes(L.state)) mpoll = setTimeout(() => { if (box.isConnected) again(); }, 3000);
  }

  document.addEventListener("click", e => { if (e.target.closest("[data-cli-logins]")) open(); });
  return { open, mount };
})();
