/* Auth screens, account menu, theme panel and per-account settings sync. */

// Every API call goes through here: adds the anti-CSRF header, surfaces server messages, and shows its progress (ui.js).
async function api(path, { method = "GET", body } = {}) {
  const end = UI.begin(method);
  try {
    const res = await fetch(path, {
      method, credentials: "same-origin",
      headers: { "X-Requested-With": "scout", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data?.detail;
      const validation = Array.isArray(detail) ? detail.filter(e => typeof e?.msg === "string").map(e => {
        const field = Array.isArray(e.loc) ? e.loc.filter(k => !["body", "query", "path"].includes(k)).join(".") : "";
        return field ? `${field}: ${e.msg}` : e.msg;
      }).join("; ") : "";
      const err = new Error(typeof detail === "string" ? detail : validation || "Something went wrong. Please try again.");
      err.status = res.status; err.data = data;  // the whole body, for callers that need more than the message (e.g. a 409's current state)
      if (res.status === 401 && !path.startsWith("/api/auth/")) Auth.expired();
      throw err;
    }
    end(true);
    return data;
  } catch (e) { end(false, e.message); throw e; }
}

// Placeholders shown while data loads (fixed markup only: callers pass no user text).
const Loading = {
  rows: (cols, n = 6) => Array.from({ length: n }, () => `<tr aria-hidden="true"><td colspan="${cols}"><div class="skeleton"></div></td></tr>`).join(""),
  cards: (n = 6, cls = "scard") => Array.from({ length: n }, () => `<div class="${cls} sk-card" aria-hidden="true"><div class="skeleton w60"></div><div class="skeleton"></div><div class="skeleton w80"></div></div>`).join(""),
  tiles: n => Array.from({ length: n }, () => `<div class="stat sk-card" aria-hidden="true"><div class="skeleton w40"></div><div class="skeleton tall w60"></div><div class="skeleton w80"></div></div>`).join(""),
  line: text => `<div class="loading-line" role="status"><span class="spinner"></span>${text}</div>`,
};

const Settings = (() => {
  let timer, pending = {}, signedIn = false;
  const read = k => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } };
  return {
    get: read,
    signedIn(v) { signedIn = v; },
    // Server copy wins after sign-in, so your theme and profile follow you across devices.
    adopt(s = {}) { for (const k of ["theme", "accent", "unit", "profile"]) if (s[k] != null) try { localStorage.setItem(k, JSON.stringify(s[k])); } catch {} Theme.apply(); },
    save(patch) {
      for (const [k, v] of Object.entries(patch)) try { localStorage.setItem(k, JSON.stringify(v)); } catch {}
      if (!signedIn) return;
      Object.assign(pending, patch); clearTimeout(timer);
      timer = setTimeout(() => { const b = pending; pending = {}; api("/api/auth/settings", { method: "PUT", body: b }).catch(() => {}); }, 600);
    },
  };
})();

const Auth = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  let onReady, me = null, recoveryMode = false, setupMode = "signin", config = { auth_method: "2fa", registration_open: true };

  function show(step) {
    if (step !== "pending") stopWaiting();
    $("#app").hidden = true; $("#auth").hidden = false;
    $$(".auth-step").forEach(f => f.hidden = f.id !== "f-" + step);
    $$(".err").forEach(e => e.textContent = "");
    const first = $(`#f-${step} input`); if (first) setTimeout(() => first.focus(), 30);
  }
  function err(form, e) { $(".err", form).textContent = e.message || e; }

  // ---------- waiting for an administrator's approval ----------
  // Registration left a "pending" session cookie; /api/auth/pending answers "pending" until an admin approves,
  // then signs this browser in (or moves it to 2FA setup / code) — no second password entry.
  let waitTimer = null, waitBusy = false;
  function stopWaiting() {
    clearInterval(waitTimer); waitTimer = null;
    document.removeEventListener("visibilitychange", checkApproval); window.removeEventListener("focus", checkApproval);
  }
  function waitForApproval(name) {
    stopWaiting();
    $("#pending-name").textContent = name || ""; $("#pending-2fa").hidden = config.auth_method !== "2fa";
    $("#pending-wait").hidden = false;
    show("pending");
    waitTimer = setInterval(checkApproval, 4000);
    document.addEventListener("visibilitychange", checkApproval); window.addEventListener("focus", checkApproval);
    checkApproval();  // coming back after approval: the window opens now, not on the first tick
  }
  async function checkApproval() {
    if (!waitTimer || waitBusy || document.hidden) return;
    waitBusy = true;
    let r;
    try { r = await api("/api/auth/pending", { method: "POST", body: { claim: false } }); }
    catch { return; }  // offline or rate-limited: the next tick tries again
    finally { waitBusy = false; }
    if (!waitTimer || r.stage === "pending") return;
    stopWaiting();
    if (r.stage === "approved") {  // the certificate window first; its OK signs in (still on the 7-day pending session)
      if (!(await AuthCert.load())) return claimApproval();  // no certificate authority yet: nothing to install
      $("#acert-ok").onclick = () => claimApproval();
      return show("cert");
    }
    approvalGone();
  }
  function approvalGone() {  // rejected, expired or disabled
    show("pending"); stopWaiting();
    $("#pending-wait").hidden = true;
    $("#f-pending .err").textContent = "This request is no longer waiting: an administrator declined it, or it expired. Ask an administrator, or create the account again.";
  }
  async function claimApproval() {
    const ok = $("#acert-ok"); ok.disabled = true; ok.classList.add("loading");
    let r;
    try { r = await api("/api/auth/pending", { method: "POST", body: { claim: true } }); }
    catch (e) {  // window open: say why and let OK try again; called straight from the wait: keep waiting, it retries
      if (!$("#f-cert").hidden) err($("#f-cert"), e); else waitForApproval($("#pending-name").textContent);
      return;
    }
    finally { ok.disabled = false; ok.classList.remove("loading"); }
    if (r.stage === "done") return enter();
    if (r.stage === "setup") return setup(r);
    if (r.stage === "mfa") { recoveryMode = false; mfaMode(); return show("mfa"); }
    if (r.stage === "pending") return waitForApproval(r.username);  // approval was taken back meanwhile
    approvalGone();
  }
  async function busy(form, fn) {
    const b = $("button[type=submit]", form); if (b) { b.disabled = true; b.classList.add("loading"); }
    try { await fn(); } catch (e) { err(form, e); } finally { if (b) { b.disabled = false; b.classList.remove("loading"); } }
  }
  // mode "signin": finishing a sign-in that requires 2FA; "enroll": a signed-in user turning 2FA on
  function setup(p, mode = "signin") {
    setupMode = mode;
    $("#qr").innerHTML = p.qr_svg; // server-generated QR SVG
    $("#totp-secret").textContent = p.secret.match(/.{1,4}/g).join(" ");
    $("#setup-title").textContent = mode === "enroll" ? "Turn on two-factor authentication" : "Set up two-factor authentication";
    show("setup");
  }
  function backToApp() { $("#auth").hidden = true; $("#app").hidden = false; }
  function showCodes(codes, after) {
    $("#codes").innerHTML = codes.map(c => `<code>${c}</code>`).join("");
    $("#codes-ok").checked = false; $("#codes-done").disabled = true;
    $("#codes-copy").onclick = () => navigator.clipboard?.writeText(codes.join("\n"));
    $("#codes-dl").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([`AXoR recovery codes (${me?.username || ""})\nEach code works once.\n\n${codes.join("\n")}\n`], { type: "text/plain" }));
      a.download = "axor-recovery-codes.txt"; a.click();
    };
    $("#codes-done").onclick = after;
    show("codes");
  }

  // ---------- password strength ----------
  const RULES = [
    ["len", "At least 12 characters", p => p.length >= 12],
    ["mix", "3 of: lowercase, uppercase, digit, symbol (or 16+ characters)", p => p.length >= 16 || [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter(r => r.test(p)).length >= 3],
    ["rep", "No character repeated 4+ times in a row", p => p && !/(.)\1{3,}/.test(p)],
    ["srv", "Not a common or breached password", null],
  ];
  let checkTimer, srv = { pw: null, ok: null, msg: "" };
  function renderRules(form) {
    const pw = form.elements.password.value;
    const ok = pw ? [...RULES.slice(0, 3).map(([, , f]) => f(pw)), srv.pw === pw ? srv.ok : null] : RULES.map(() => null);
    $(".rules", form).innerHTML = RULES.map(([k, label], i) => {
      const st = ok[i] === true ? "ok" : ok[i] === false ? "bad" : "";
      const text = k === "srv" && ok[i] === false && srv.msg ? srv.msg : label;
      return `<li class="${st}">${icon(st === "ok" ? "check" : st === "bad" ? "close" : "clock")}${text}</li>`;
    }).join("");
    const score = pw ? ok.filter(x => x === true).length : 0;
    $$(".meter i", form).forEach((el, i) => el.className = i < score ? `on s${score}` : "");
    return ok;
  }
  function strength(form) {
    const ok = renderRules(form), pw = form.elements.password.value;
    clearTimeout(checkTimer);
    if (ok.slice(0, 3).every(x => x === true) && srv.pw !== pw) checkTimer = setTimeout(async () => {
      try {
        const r = await api("/api/auth/password-check", { method: "POST", body: { username: form.elements.username?.value || "", password: pw } });
        srv = { pw, ok: !r.problems.length, msg: r.problems.join(" ") };
      } catch { return; }
      if (form.elements.password.value === pw) renderRules(form);
    }, 450);
  }

  function wire() {
    $$("#auth [data-tab]").forEach(b => b.onclick = () => show(b.dataset.tab));  // "Create account" link under Continue
    document.addEventListener("input", e => { const er = e.target.form && $(".err", e.target.form); if (er) er.textContent = ""; });
    $$("[data-back]").forEach(b => b.onclick = () => show("login"));
    document.addEventListener("click", e => {
      const eye = e.target.closest(".eye"); if (!eye) return;
      const inp = eye.previousElementSibling, vis = inp.type === "password";
      inp.type = vis ? "text" : "password"; eye.innerHTML = icon(vis ? "eyeoff" : "eye");
      eye.setAttribute("aria-label", vis ? "Hide password" : "Show password");
    });
    $$(".eye").forEach(b => b.innerHTML = icon("eye"));
    const reg = $("#f-register");
    reg.elements.password.addEventListener("input", () => strength(reg));
    reg.elements.username.addEventListener("change", () => strength(reg));
    strength(reg);

    $("#f-login").onsubmit = e => { e.preventDefault(); const f = e.target; busy(f, async () => {
      const r = await api("/api/auth/login", { method: "POST", body: { login: f.elements.login.value, password: f.elements.password.value } });
      f.elements.password.value = "";
      if (r.stage === "setup") setup(r);
      else if (r.stage === "mfa") { recoveryMode = false; mfaMode(); show("mfa"); }
      else enter();
    }); };
    reg.onsubmit = e => { e.preventDefault(); busy(reg, async () => {
      if (reg.elements.password.value !== reg.elements.confirm.value) throw new Error("Passwords don't match.");
      const r = await api("/api/auth/register", { method: "POST", body: { username: reg.elements.username.value, email: reg.elements.email.value || null, password: reg.elements.password.value } });
      const name = reg.elements.username.value.trim().toLowerCase();
      reg.reset(); strength(reg);
      if (r.stage === "pending") return waitForApproval(r.username || name);  // signs in by itself once an admin approves
      if (r.stage === "setup") setup(r); else enter();
    }); };
    $("#f-setup").onsubmit = e => { e.preventDefault(); const f = e.target; busy(f, async () => {
      if (setupMode === "enroll") {
        const r = await api("/api/auth/2fa/enable", { method: "POST", body: { code: f.elements.code.value } });
        f.reset(); me.totp_enabled = true; me.recovery_left = r.recovery_codes.length;
        return showCodes(r.recovery_codes, () => { backToApp(); toastMsg("Two-factor authentication is on."); });
      }
      const r = await api("/api/auth/register/verify", { method: "POST", body: { code: f.elements.code.value } });
      f.reset(); me = await api("/api/auth/me"); showCodes(r.recovery_codes, enter);
    }); };
    $("#use-recovery").onclick = () => { recoveryMode = !recoveryMode; mfaMode(); };
    $("#f-mfa").onsubmit = e => { e.preventDefault(); const f = e.target; busy(f, async () => {
      await api("/api/auth/mfa", { method: "POST", body: { code: f.elements.code.value } });
      f.reset(); enter();
    }); };
    $("#codes-ok").onchange = e => $("#codes-done").disabled = !e.target.checked;
  }
  function mfaMode() {
    $("#mfa-hint").textContent = recoveryMode ? "Enter one of your 10-character recovery codes. Each code works once." : "Enter the 6-digit code from your authenticator app.";
    $("#mfa-label").textContent = recoveryMode ? "Recovery code" : "Authenticator code";
    const inp = $("#f-mfa").elements.code;
    inp.inputMode = recoveryMode ? "text" : "numeric"; inp.placeholder = recoveryMode ? "ABCDE-12345" : "123456"; inp.value = ""; inp.focus();
    $("#use-recovery").textContent = recoveryMode ? "Use authenticator code" : "Use a recovery code";
  }

  async function enter() {
    me = await api("/api/auth/me");
    if (!me.authenticated) return start(onReady);
    if (me.must_change) { $("#auth").hidden = true; $("#app").hidden = false; return passwordModal(true); }
    Settings.signedIn(true); Settings.adopt(me.settings);
    openApp();
  }
  function openApp() {
    $("#auth").hidden = true; $("#app").hidden = false;
    $("#account").textContent = (me?.username || "?")[0].toUpperCase();
    $("#account").hidden = !me;
    $("#tab-agents").hidden = $("#tab-studio").hidden = $("#grp-tools").hidden = $("#tab-docker").hidden = $("#tab-devops").hidden = $("#tab-system").hidden = $("#tab-connectors").hidden =
      $("#tab-cluster").hidden = $("#tab-apps").hidden = $("#tab-functions").hidden = $("#tab-machines").hidden = $("#tab-dns").hidden = $("#tab-hq").hidden =
      $("#nav-mining").hidden = $("#nav-teams").hidden = $("#nav-portfolio").hidden = $("#nav-company").hidden = $("#nav-workforce").hidden = $("#nav-infiagent").hidden = $("#nav-knowledge").hidden = $("#nav-market").hidden = $("#nav-mos").hidden = me?.role !== "admin";
    if (me && me.role !== "admin") api("/api/agents/hub").then(() => { $("#tab-agents").hidden = $("#tab-studio").hidden = $("#grp-tools").hidden = $("#nav-mining").hidden = $("#nav-teams").hidden = $("#nav-portfolio").hidden = $("#nav-company").hidden = $("#nav-workforce").hidden = $("#nav-infiagent").hidden = $("#nav-knowledge").hidden = $("#nav-market").hidden = $("#nav-mos").hidden = false; }).catch(() => {});
    const cb = onReady; onReady = null; if (cb) cb();

  }

  async function start(cb) {
    onReady = cb;
    hydrateIcons($("#auth")); wire(); wireChrome();
    config = await api("/api/auth/config").catch(() => config);
    $("#reg-fine").textContent = config.approval_required
      ? "An administrator reviews new accounts. This page moves on by itself as soon as yours is approved."
      : config.auth_method === "2fa"
      ? "Two-factor authentication is required. You'll set up an authenticator app next."
      : "You can turn on two-factor authentication later from your account menu.";
    $("#auth-to-register").hidden = !config.registration_open;
    let meta;
    try { meta = await api("/api/meta"); }
    catch (e) {
      if (e.status === 403) {  // signed in with a temporary password: replace it before anything else
        me = await api("/api/auth/me");
        if (me.must_change) { $("#auth").hidden = true; $("#app").hidden = false; return passwordModal(true); }
      }
      if (e.status !== 401) throw e;
      const s = await api("/api/auth/me");
      if (s.stage === "setup") return setup(s);
      if (s.stage === "mfa") { mfaMode(); return show("mfa"); }
      if (s.stage === "pending") return waitForApproval(s.username);  // came back while still waiting for approval
      return show("login");
    }
    Auth.meta = meta;
    if (meta.login) { me = await api("/api/auth/me"); Settings.signedIn(true); Settings.adopt(me.settings); }
    openApp();
  }
  function expired() { if (!$("#app").hidden) { location.reload(); } }

  // ---------- header chrome: theme panel + account menu ----------
  function popover(btn, html, cls = "") {
    document.querySelector(".menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover menu " + cls; pop.innerHTML = html;
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 8) + "px";
    pop.style.left = Math.max(16, Math.min(b.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) {
      if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); }
    }), 0);
    return pop;
  }
  const backdrop = () => Settings.get("backdrop") || "subtle";
  function themePanel(btn) {
    const cur = Theme.accent().toLowerCase(), mode = Theme.mode();
    const pop = popover(btn, `
      <h4>Mode</h4>
      <div class="seg full" id="tp-mode">${["system", "light", "dark"].map(m => `<button type="button" data-mode="${m}" aria-pressed="${m === mode}">${icon({ system: "devices", light: "sun", dark: "moon" }[m])}${m[0].toUpperCase() + m.slice(1)}</button>`).join("")}</div>
      <h4>Accent color</h4>
      <div class="swatches" id="tp-sw">${Theme.SWATCHES.map(([n, c]) => `<button type="button" class="sw" data-c="${c}" title="${n}" aria-label="${n}" aria-pressed="${c === cur}" style="--c:${c}"></button>`).join("")}
        <label class="sw custom" title="Custom color" aria-pressed="${!Theme.SWATCHES.some(([, c]) => c === cur)}" style="--c:${cur}"><input type="color" value="${cur}" aria-label="Custom color">${icon("palette")}</label></div>
      <h4>Background</h4>
      <div class="seg full" id="tp-bg">${[["off", "eyeoff"], ["subtle", "sparkle"], ["vivid", "zap"]].map(([v, ic]) => `<button type="button" data-bg="${v}" aria-pressed="${v === backdrop()}">${icon(ic)}${v[0].toUpperCase() + v.slice(1)}</button>`).join("")}</div>
      <div class="tp-preview"><a>Link</a><span class="chip" aria-pressed="true">Selected</span><span class="bar"><i style="width:62%"></i></span></div>
      <p class="fine">Colors are adjusted automatically to stay readable in light and dark mode.</p>
      <button type="button" class="btn" id="tp-reset">${icon("reset")}Reset to default</button>`, "theme-panel");
    const refresh = () => {
      const a = Theme.accent().toLowerCase();
      $$("#tp-sw .sw[data-c]", pop).forEach(b => b.setAttribute("aria-pressed", b.dataset.c === a));
      const custom = $(".custom", pop); custom.setAttribute("aria-pressed", !Theme.SWATCHES.some(([, c]) => c === a)); custom.style.setProperty("--c", a);
      $$("#tp-mode button", pop).forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === Theme.mode()));
      $$("#tp-bg button", pop).forEach(b => b.setAttribute("aria-pressed", b.dataset.bg === backdrop()));
      $("#theme").innerHTML = icon("palette");
      document.dispatchEvent(new Event("themechange"));
    };
    pop.addEventListener("click", e => {
      const m = e.target.closest("[data-mode]"); if (m) { Settings.save({ theme: m.dataset.mode }); Theme.apply(); refresh(); }
      const s = e.target.closest("[data-c]"); if (s) { Settings.save({ accent: s.dataset.c }); Theme.apply(); refresh(); }
      const g = e.target.closest("[data-bg]"); if (g) { try { localStorage.setItem("backdrop", JSON.stringify(g.dataset.bg)); } catch {} refresh(); }  // per device: backdrop.js
      if (e.target.closest("#tp-reset")) { Settings.save({ accent: Theme.DEFAULT, theme: "system" }); Theme.apply(); refresh(); }
    });
    $("input[type=color]", pop).addEventListener("input", e => { Settings.save({ accent: e.target.value }); Theme.apply(); refresh(); });
  }
  function accountMenu(btn) {
    const pop = popover(btn, `
      <div class="acct"><span class="avatar big">${(me?.username || "?")[0].toUpperCase()}</span><div><b>${esc(me?.username || "")}</b>${me?.email ? `<small>${esc(me.email)}</small>` : ""}<small>${me?.role === "admin" ? `<span class="badge caution">${icon("shield")}Admin</span>` : '<span class="tag">User</span>'} ${me?.totp_enabled ? `${icon("lock")}2FA on · ${me.recovery_left} codes left` : `<span class="no">2FA off</span>`}</small></div></div>
      <button type="button" class="mi" data-act="profile">${icon("card")}My profile</button><div class="mi-sep"></div>
      ${me?.role === "admin" ? `<button type="button" class="mi" data-act="admin">${icon("users")}Administration</button><button type="button" class="mi" data-act="docker">${icon("server")}Docker</button><div class="mi-sep"></div>` : ""}
      <button type="button" class="mi" data-act="password">${icon("key")}Change password</button>
      ${me?.totp_enabled ? `<button type="button" class="mi" data-act="codes">${icon("shield")}New recovery codes</button>`
                         : `<button type="button" class="mi" data-act="enroll">${icon("shield")}Turn on two-factor</button>`}
      <button type="button" class="mi" data-act="all">${icon("devices")}Sign out of all devices</button>
      <button type="button" class="mi" data-act="out">${icon("logout")}Sign out</button>`, "account-menu");
    pop.addEventListener("click", async e => {
      const a = e.target.closest("[data-act]")?.dataset.act; if (!a) return;
      pop.remove();
      if (a === "out" || a === "all") { await api(a === "out" ? "/api/auth/logout" : "/api/auth/logout-all", { method: "POST" }).catch(() => {}); location.reload(); }
      if (a === "password") passwordModal();
      if (a === "codes") codesModal();
      if (a === "admin" || a === "docker" || a === "profile") setView(a);
      if (a === "enroll") { try { setup(await api("/api/auth/2fa/setup", { method: "POST" }), "enroll"); } catch (err) { toastMsg(err.message); } }
    });
  }
  function modal(html, onSubmit, { forced = false, submit = "Save", danger = false } = {}) {
    const d = $("#modal");
    d.classList.toggle("is-danger", danger);  // removals get the warning look (styles.css)
    d.innerHTML = `<form method="dialog" novalidate>${html}<p class="err" role="alert"></p><div class="row end">${forced ? "" : `<button type="button" class="btn" value="cancel" data-close>Cancel</button>`}<button class="btn primary ${danger ? "danger" : ""}" type="submit">${submit}</button></div></form>`;
    d.oncancel = e => { if (forced) e.preventDefault(); };
    const f = $("form", d);
    if (!forced) $("[data-close]", d).onclick = () => d.close();
    $$(".eye", d).forEach(b => b.innerHTML = icon("eye"));
    f.onsubmit = e => { e.preventDefault(); busy(f, () => onSubmit(f)); };
    d.showModal();
    return f;
  }
  function passwordModal(forced = false) {
    const f = modal(`<h3>${icon("key")}${forced ? "Choose a new password" : "Change password"}</h3>
      ${forced ? `<p class="muted">An administrator reset your password. Replace the temporary password before continuing.</p>` : ""}
      <label class="in"><span>Current password</span><div class="pw"><input name="current" type="password" autocomplete="current-password" required><button type="button" class="eye" aria-label="Show password"></button></div></label>
      <input name="username" type="hidden" value="${esc(me?.username || "")}">
      <label class="in"><span>New password</span><div class="pw"><input name="password" type="password" autocomplete="new-password" required><button type="button" class="eye" aria-label="Show password"></button></div></label>
      <div class="meter"><i></i><i></i><i></i><i></i></div><ul class="rules"></ul>
      ${me?.totp_enabled ? `<label class="in"><span>Authenticator code</span><input name="code" class="code" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required></label>` : ""}
      <p class="fine">All other devices will be signed out.</p>`, async f => {
      await api("/api/auth/password", { method: "POST", body: { current: f.elements.current.value, new: f.elements.password.value, code: f.elements.code?.value || "" } });
      $("#modal").close();
      if (forced) return location.reload();
      toastMsg("Password changed. Other devices were signed out.");
    }, { forced });
    f.elements.password.addEventListener("input", () => strength(f)); strength(f);
  }
  function codesModal() {
    modal(`<h3>${icon("shield")}New recovery codes</h3><p class="muted">Your old codes stop working. Confirm with your authenticator.</p>
      <label class="in"><span>Authenticator code</span><input name="code" class="code" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required></label>`, async f => {
      const r = await api("/api/auth/recovery-codes", { method: "POST", body: { code: f.elements.code.value } });
      $("#modal").close();
      me.recovery_left = r.recovery_codes.length;
      showCodes(r.recovery_codes, backToApp);
    });
  }
  const toastMsg = (m, o) => UI.toast(m, o);
  let chromeWired = false;
  function wireChrome() {
    if (chromeWired) return; chromeWired = true;
    $("#theme").innerHTML = icon("palette");
    $("#theme").onclick = e => { e.stopPropagation(); themePanel(e.currentTarget); };
    $("#account").onclick = e => { e.stopPropagation(); accountMenu(e.currentTarget); };
  }

  return { start, expired, meta: null, modal, toast: toastMsg, me: () => me };
})();
