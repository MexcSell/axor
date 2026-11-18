/* User administration view (admins only; the server enforces every rule shown here). */
const Admin = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  let data = null, wired = false, aTimer;

  const EVENTS = {
    "login.ok": ["Signed in", "clear"], "login.fail": ["Failed sign-in", "caution"], "login.blocked": ["Blocked sign-in", "avoid"],
    "mfa.fail": ["Wrong 2FA code", "caution"], "register": ["Registered", "new"], "2fa.enabled": ["2FA enabled", "clear"],
    "password.changed": ["Password changed", "new"], "sudo": ["Admin confirmed", "new"], "sudo.fail": ["Admin code failed", "avoid"],
    "registration.open": ["Registration opened", "caution"], "registration.closed": ["Registration closed", "clear"],
    "role.admin": ["Made admin", "caution"], "admin.disable": ["Disabled user", "avoid"], "admin.enable": ["Enabled user", "clear"],
    "admin.unlock": ["Unlocked user", "new"], "admin.logout": ["Signed user out", "new"], "admin.promote": ["Made admin", "caution"],
    "admin.demote": ["Removed admin", "caution"], "admin.reset_2fa": ["Reset 2FA", "avoid"], "admin.reset_password": ["Reset password", "avoid"],
    "admin.delete": ["Deleted user", "scam"], "admin.created": ["Admin created", "caution"],
    "admin.approve": ["Approved account", "clear"], "admin.reject": ["Rejected sign-up", "avoid"],
    "approval.on": ["Approval required", "clear"], "approval.off": ["Approval not required", "caution"],
    "auth_method.basic": ["Sign-in: password only", "caution"], "auth_method.2fa": ["Sign-in: 2FA required", "clear"],
    "docker.start": ["Started container", "new"], "docker.stop": ["Stopped container", "caution"], "docker.restart": ["Restarted container", "caution"],
    "docker.remove": ["Removed container", "avoid"], "docker.pull": ["Pulled image", "new"], "docker.rmi": ["Removed image", "avoid"],
    "docker.prune": ["Pruned images", "avoid"],
    "connector.openrouter_connect": ["OpenRouter connected", "caution"], "connector.openrouter_disconnect": ["OpenRouter disconnected", "caution"],
    "connector.key_create": ["Created API key", "new"], "connector.key_edit": ["Edited API key", "new"], "connector.key_enable": ["Enabled API key", "clear"],
    "connector.key_disable": ["Disabled API key", "caution"], "connector.key_delete": ["Deleted API key", "avoid"],
  };
  const ACTIONS = {
    approve: { label: "Approve", icon: "check", done: "Approved" },
    reject: { label: "Reject", icon: "close", done: "Rejected", confirm: "The sign-up request is deleted. They can register again while registration is open.", danger: true },
    promote: { label: "Make admin", icon: "shield", confirm: "They'll be able to manage every account, including yours." },
    demote: { label: "Remove admin", icon: "users", confirm: "They'll become a regular user." },
    unlock: { label: "Unlock sign-in", icon: "lock" },
    logout: { label: "Sign out all devices", icon: "devices" },
    reset_password: { label: "Reset password", icon: "key", confirm: "Their password is replaced by a temporary one you'll hand them; they must change it at next sign-in. Their sessions end now.", danger: true },
    reset_2fa: { label: "Reset two-factor", icon: "shield", confirm: "Their authenticator and recovery codes stop working. At next sign-in they'll set up a new authenticator with their password alone, so only do this after verifying who's asking.", danger: true },
    disable: { label: "Disable account", icon: "ban", confirm: "They're signed out everywhere and can't sign in until re-enabled.", danger: true },
    enable: { label: "Enable account", icon: "check" },
    delete: { label: "Delete account", icon: "close", confirm: "The account is removed permanently. This can't be undone.", danger: true },
  };

  // Run fn; if the server asks for a fresh authenticator code ("sudo"), ask once and retry.
  async function withSudo(fn) {
    try { return await fn(); }
    catch (e) {
      if (e.message !== "SUDO_REQUIRED") throw e;
      await new Promise((resolve, reject) => {
        const d = $("#modal");
        let settled = false;
        // A close event queued by the previous dialog can arrive after this one opens: ignore it while open.
        const onClose = () => { if (d.open || settled) return; settled = true; d.removeEventListener("close", onClose); reject(new Error("cancelled")); };
        const totp = Auth.me()?.totp_enabled;
        Auth.modal(`<h3>${icon("lock")}Confirm it's you</h3><p class="muted">Enter your ${totp ? "authenticator code" : "password"}. Admin changes then stay unlocked for 10 minutes.</p>
          ${totp ? `<label class="in"><span>Authenticator code</span><input name="code" class="code" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required></label>`
                 : `<label class="in"><span>Password</span><input name="password" type="password" autocomplete="current-password" required></label>`}`,
          async f => {
            await api("/api/admin/sudo", { method: "POST", body: { code: f.elements.code?.value || "", password: f.elements.password?.value || "" } });
            settled = true; d.removeEventListener("close", onClose); d.close(); resolve();
          },
          { submit: "Confirm" });
        d.addEventListener("close", onClose);
        setTimeout(() => $("#modal input")?.focus(), 30);
      });
      return fn();
    }
  }

  async function open() {
    wire();
    if (!data) { $("#adm-stats").innerHTML = Loading.tiles(4); $("#adm-users").innerHTML = Loading.rows(8, 5); $("#adm-audit").innerHTML = Loading.rows(6, 5); }
    try { data = await api("/api/admin/overview"); }
    catch (e) { $("#adm-users").innerHTML = `<tr><td colspan="8"><div class="empty">${esc(e.message)}</div></td></tr>`; return; }
    render(); loadAudit();
  }

  function render() {
    const s = data.stats;
    const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
    $("#adm-stats").innerHTML = [
      tile("users", "Accounts", s.users, `${s.admins} admin${s.admins === 1 ? "" : "s"}${s.pending ? ` · <b>${s.pending} awaiting approval</b>` : ""}`),
      tile("shield", "Two-factor on", `${s.with_2fa}/${s.users}`, s.users - s.with_2fa ? `${s.users - s.with_2fa} still setting up` : "everyone protected"),
      tile("devices", "Active sessions", s.sessions, `${s.logins_24h} sign-ins in 24h`),
      tile("alert", "Failed attempts 24h", s.fails_24h, `${s.locked} locked · ${s.disabled} disabled`),
    ].join("");
    $("#adm-reg").checked = data.registration_open;
    document.querySelectorAll("#adm-method button").forEach(b => b.setAttribute("aria-pressed", b.dataset.method === data.auth_method));
    $("#adm-method-text").textContent = data.auth_method === "2fa"
      ? "Everyone signs in with a password and an authenticator code. Users without 2FA set it up at their next sign-in."
      : "Users sign in with username and password. Anyone who has turned on 2FA is still asked for their code.";
    $("#adm-reg-text").textContent = data.registration_open
      ? "Open: anyone with the link can create an account. Close it once your team is in."
      : "Closed: new people can't sign up. Accounts that already exist keep working.";
    $("#adm-appr").checked = data.approval_required;
    $("#adm-appr-text").textContent = data.approval_required
      ? "On: people who sign up can't sign in until an admin approves them here."
      : "Off: new accounts can sign in as soon as they're created.";
    const sudo = data.sudo_until * 1000 - Date.now();
    $("#adm-sudo").innerHTML = sudo > 0 ? `${icon("lock")} Admin changes unlocked for ${Math.ceil(sudo / 60000)} min` : "";
    renderPending(); renderUsers();
  }

  function renderPending() {
    const rows = data.users.filter(u => !u.approved), box = $("#adm-pending");
    box.hidden = !rows.length;
    box.innerHTML = rows.length ? `<h3>${icon("clock")}Waiting for approval <span class="badge caution">${rows.length}</span></h3>
      <p class="muted">They registered and continue as soon as you approve them: their sign-up page shows AXoR's certificate to install, then signs them in${data.auth_method === "2fa" ? " (they set up two-factor at first sign-in)" : ""}.</p>` +
      rows.map(u => `<div class="adm-pending-row" data-uid="${u.id}">
        <div class="adm-user"><span class="avatar sm">${esc(u.username[0].toUpperCase())}</span><div><b>${esc(u.username)}</b>
          <small class="faint">${[u.email && esc(u.email), u.signup_ip && `<span class="num">${esc(u.signup_ip)}</span>`, `signed up ${ago(u.created)}`].filter(Boolean).join(" · ")}</small></div></div>
        <div class="adm-pending-acts"><button type="button" class="btn" data-act="reject">${icon("close")}Reject</button><button type="button" class="btn primary" data-act="approve">${icon("check")}Approve</button></div></div>`).join("") : "";
  }

  function renderUsers() {
    const q = $("#adm-q").value.trim().toLowerCase(), f = $("#adm-filter").value;
    const rows = data.users.filter(u =>
      (!q || u.username.includes(q) || (u.email || "").includes(q) || (u.last_ip || "").includes(q)) &&
      (!f || (f === "pending" && !u.approved) || (f === "admin" && u.role === "admin") || (f === "disabled" && u.disabled) || (f === "locked" && u.locked) || (f === "no2fa" && !u.totp_enabled)));
    $("#adm-users").innerHTML = rows.map(u => {
      const status = !u.approved ? `<span class="badge caution">${icon("clock")}Awaiting approval</span>`
        : u.disabled ? `<span class="badge avoid">${icon("ban")}Disabled</span>`
        : u.locked ? `<span class="badge caution">${icon("lock")}Locked</span>`
        : u.must_change ? `<span class="badge caution">${icon("key")}Temp password</span>`
        : `<span class="badge clear">${icon("check")}Active</span>`;
      return `<tr data-uid="${u.id}">
        <td><div class="adm-user"><span class="avatar sm">${esc(u.username[0].toUpperCase())}</span><div><b>${esc(u.username)}</b>${u.you ? ' <span class="badge new">You</span>' : ""}<small class="faint">${esc(u.email || "")}${u.email && u.last_ip ? " · " : ""}<span class="num">${esc(u.last_ip || "")}</span></small></div></div></td>
        <td>${u.role === "admin" ? `<span class="badge caution">${icon("shield")}Admin</span>` : '<span class="tag">User</span>'}</td>
        <td>${status}</td>
        <td>${u.totp_enabled ? `<span class="ok">${icon("check")}On</span> <span class="faint">· ${u.recovery_left} codes</span>`
              : data.auth_method === "2fa" ? `<span class="no">${icon("clock")}Not set up</span>` : `<span class="faint">Off (optional)</span>`}</td>
        <td>${u.last_login ? `${ago(u.last_login)}<br><span class="faint num">${new Date(u.last_login * 1000).toLocaleString()}</span>` : '<span class="faint">Never</span>'}</td>
        <td class="r num">${u.sessions}</td>
        <td class="num">${new Date(u.created * 1000).toLocaleDateString()}</td>
        <td class="r">${u.you ? '<span class="faint">Use account menu</span>' : `<button class="iconbtn" data-menu="${u.id}" aria-label="Actions for ${esc(u.username)}">${icon("columns")}</button>`}</td></tr>`;
    }).join("") || `<tr><td colspan="8"><div class="empty">No users match.</div></td></tr>`;
  }

  function menu(btn, u) {
    document.querySelector(".menu")?.remove();
    const acts = !u.approved ? ["approve", "reject"] : [
      u.role === "admin" ? "demote" : "promote", u.locked && "unlock", u.sessions && "logout",
      "reset_password", u.totp_enabled && "reset_2fa", u.disabled ? "enable" : "disable", "delete",
    ].filter(Boolean);
    const pop = document.createElement("div"); pop.className = "popover menu";
    pop.innerHTML = `<div class="acct"><span class="avatar">${esc(u.username[0].toUpperCase())}</span><div><b>${esc(u.username)}</b></div></div>` +
      acts.map(a => `<button type="button" class="mi ${ACTIONS[a].danger ? "danger" : ""}" data-act="${a}">${icon(ACTIONS[a].icon)}${ACTIONS[a].label}</button>`).join("");
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = Math.min(b.bottom + scrollY + 6, scrollY + innerHeight - pop.offsetHeight - 10) + "px";
    pop.style.left = Math.max(16, b.right - pop.offsetWidth) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.onclick = e => { const a = e.target.closest("[data-act]")?.dataset.act; if (a) { pop.remove(); run(u, a); } };
  }

  async function run(u, a) {
    const A = ACTIONS[a];
    const go = async () => {
      const r = await withSudo(() => api(`/api/admin/users/${u.id}`, { method: "POST", body: { action: a } }));
      if (r.temp_password) showTemp(u, r.temp_password); else Auth.toast(A.done ? `${A.done} ${u.username}` : `${A.label}: ${u.username}`);
      await open();
    };
    if (!A.confirm) return go().catch(e => e.message !== "cancelled" && Auth.toast(e.message));
    Auth.modal(`<h3>${icon(A.icon)}${A.label}?</h3><p><b>${esc(u.username)}</b></p><p class="muted">${A.confirm}</p>`,
      async () => { $("#modal").close(); await go().catch(e => e.message !== "cancelled" && Auth.toast(e.message)); },
      { submit: A.label, danger: A.danger });
  }

  function showTemp(u, pw) {
    Auth.modal(`<h3>${icon("key")}Temporary password</h3><p class="muted">Give this to <b>${esc(u.username)}</b> through a private channel. It's shown only once; they must replace it when they sign in.</p>
      <code class="temp-pw">${esc(pw)}</code><button type="button" class="btn" id="temp-copy">${icon("copy")}Copy</button>`,
      async () => $("#modal").close(), { submit: "Done", forced: true });
    $("#temp-copy").onclick = () => { navigator.clipboard?.writeText(pw); Auth.toast("Copied"); };
  }

  async function loadAudit() {
    const q = $("#adm-aq").value.trim();
    $("#adm-audit").classList.add("updating");
    const rows = await api(`/api/admin/audit?limit=300&q=${encodeURIComponent(q)}`).catch(() => []);
    $("#adm-audit").classList.remove("updating");
    $("#adm-audit").innerHTML = rows.map(r => {
      const [label, lvl] = EVENTS[r.action] || [r.action, "new"];
      return `<tr><td class="num" title="${new Date(r.ts * 1000).toLocaleString()}">${ago(r.ts)}</td>
        <td><span class="badge ${lvl}">${esc(label)}</span></td><td>${esc(r.actor)}</td><td>${esc(r.target)}</td>
        <td class="num">${esc(r.ip)}</td><td class="faint">${esc(r.detail)}</td></tr>`;
    }).join("") || `<tr><td colspan="6"><div class="empty">No events yet.</div></td></tr>`;
  }

  function wire() {
    if (wired) return; wired = true;
    hydrateIcons($("#view-admin"));
    $("#adm-q").oninput = renderUsers; $("#adm-filter").onchange = renderUsers;
    $("#adm-aq").oninput = () => { clearTimeout(aTimer); aTimer = setTimeout(loadAudit, 250); };
    $("#adm-pending").onclick = e => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      run(data.users.find(u => u.id === +b.closest("[data-uid]").dataset.uid), b.dataset.act);
    };
    $("#adm-users").onclick = e => {
      const b = e.target.closest("[data-menu]"); if (!b) return;
      e.stopPropagation(); menu(b, data.users.find(u => u.id === +b.dataset.menu));
    };
    $("#adm-method").onclick = async e => {
      const b = e.target.closest("[data-method]"); if (!b || b.dataset.method === data.auth_method) return;
      const go = async () => {
        try { await withSudo(() => api("/api/admin/auth-method", { method: "POST", body: { method: b.dataset.method } })); Auth.toast("Sign-in method updated"); }
        catch (err) { if (err.message !== "cancelled") Auth.toast(err.message); }
        open();
      };
      if (b.dataset.method === "basic")
        Auth.modal(`<h3>${icon("alert")}Switch to username + password?</h3><p class="muted">New accounts won't need an authenticator, and users who haven't turned on 2FA will sign in with a password alone. Existing 2FA stays on for those who have it.</p>`,
          async () => { $("#modal").close(); await go(); }, { submit: "Switch to basic", danger: true });
      else go();
    };
    $("#adm-appr").onchange = async e => {
      const want = e.target.checked;
      try { await withSudo(() => api("/api/admin/approval", { method: "POST", body: { required: want } })); Auth.toast(want ? "New accounts need approval" : "New accounts no longer need approval"); }
      catch (err) { if (err.message !== "cancelled") Auth.toast(err.message); }
      open();
    };
    $("#adm-reg").onchange = async e => {
      const want = e.target.checked;
      try { await withSudo(() => api("/api/admin/registration", { method: "POST", body: { open: want } })); Auth.toast(want ? "Registration opened" : "Registration closed"); }
      catch (err) { if (err.message !== "cancelled") Auth.toast(err.message); }
      open();
    };
  }

  return { open, withSudo, showTemp };
})();
