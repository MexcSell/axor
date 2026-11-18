/* Feedback for every action, app-wide:
   - a progress bar along the top while a page or an action loads (requests the person started, not background refreshes);
   - the control that started a request shows it: it dips when pressed, spins while the request runs (and ignores
     repeat clicks), then settles with a tick when something was saved or a shake when it failed;
   - toasts say what kind of news they are (done, failed, info) and can offer Undo;
   - one warning dialog in front of every removal (UI.confirm), which can keep its button spinning until the work is done.
   api() in auth.js reports each request through UI.begin. */
const UI = (() => {
  const now = () => performance.now();
  const WRITES = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  const escape = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- the progress bar ----------
  let foreground = now() + 15000, live = 0, width = 0, showT, hideT, trickle;  // the first seconds are the page loading
  for (const ev of ["pointerdown", "keydown", "hashchange", "popstate"]) addEventListener(ev, () => { foreground = now() + 1500; }, true);
  const bar = () => document.getElementById("progress");
  const grow = w => { width = w; bar()?.style.setProperty("--p", (w / 100).toFixed(3)); };
  function barStart() {
    if (live++) return;
    clearTimeout(hideT);
    showT = setTimeout(() => {  // quick requests never flash the bar
      const b = bar(); if (!b) return;
      if (!b.classList.contains("on")) { b.classList.add("on", "reset"); grow(0); b.offsetWidth; b.classList.remove("reset"); }
      grow(Math.max(width, 14)); clearInterval(trickle); trickle = setInterval(() => grow(width + (90 - width) * .1), 300);
    }, 150);
  }
  function barEnd() {
    if (--live > 0) return;
    live = 0; clearTimeout(showT); clearInterval(trickle);
    const b = bar(); if (!b?.classList.contains("on")) return;
    grow(100); hideT = setTimeout(() => b.classList.remove("on"), 260);
  }

  // ---------- the control that started a request ----------
  let pressed = null;
  const CONTROL = "button, a.btn, [role=button], [role=tab], [role=menuitem]";
  document.addEventListener("click", e => {
    const el = e.target.closest?.(CONTROL); if (!el) return;
    if (el.classList.contains("pending")) { e.preventDefault(); e.stopImmediatePropagation(); return; }  // already working: no double submits
    pressed = { el, t: now() };
  }, true);
  document.addEventListener("submit", e => { if (e.submitter) pressed = { el: e.submitter, t: now() }; }, true);
  const runs = new WeakMap();
  function claim(method) {
    const p = pressed;
    if (!p || now() - p.t > 600 || !p.el.isConnected || p.el.disabled || p.el.classList.contains("loading")) return null;  // .loading: it shows its own progress
    const el = p.el, r = runs.get(el) || { n: 0 };
    if (!r.n) {
      Object.assign(r, { failed: false, wrote: false });
      el.classList.remove("done", "failed"); el.classList.add("pending"); el.setAttribute("aria-busy", "true");
      clearTimeout(r.cap); r.cap = setTimeout(() => unbusy(el), 15000);  // a long request (a chat reply) stops blocking the control
    }
    r.n++; if (WRITES.has(method)) r.wrote = true;
    runs.set(el, r);
    return el;
  }
  const unbusy = el => { el.classList.remove("pending"); el.removeAttribute("aria-busy"); };
  function release(el, outcome) {
    const r = runs.get(el); if (!r) return;
    if (outcome === "failed") r.failed = true;
    if (--r.n > 0) return;
    clearTimeout(r.cap); unbusy(el);
    const k = r.failed ? "failed" : r.wrote && outcome !== "neutral" ? "done" : null;
    if (!k || !el.isConnected) return;
    el.classList.add(k); clearTimeout(r.flash); r.flash = setTimeout(() => el.classList.remove(k), k === "done" ? 1100 : 600);
  }

  // One request: returns end(ok, message), which is safe to call twice.
  let lastErr = null, lastWrite = -1e9;
  function begin(method = "GET") {
    method = method.toUpperCase();
    const fg = now() < foreground, el = claim(method);
    if (fg) barStart();
    let over = false;
    return (ok, msg) => {
      if (over) return; over = true;
      if (fg) barEnd();
      const neutral = msg === "SUDO_REQUIRED";  // asking to confirm it's you isn't a failure
      if (el) release(el, ok ? "ok" : neutral ? "neutral" : "failed");
      if (!ok && !neutral) lastErr = { msg, t: now() };
      if (ok && WRITES.has(method)) lastWrite = now();
    };
  }

  // ---------- toasts ----------
  const KIND = { success: "check", error: "alert", warn: "alert", info: "zap" };
  function toast(msg, { kind, action, onAction, ms } = {}) {
    const t = document.getElementById("toast"); if (!t) return;
    msg = String(msg ?? "");
    // Callers pass a plain message: a request's error text is a failure, news right after a save is a success.
    kind ||= lastErr && lastErr.msg === msg && now() - lastErr.t < 5000 ? "error" : now() - lastWrite < 2500 ? "success" : "info";
    t.className = `toast show ${kind}`;
    t.setAttribute("role", kind === "error" ? "alert" : "status");
    t.innerHTML = `${icon(KIND[kind] || "zap")}<span>${escape(msg)}</span>${action ? `<button type="button" class="toast-act">${escape(action)}</button>` : ""}`;
    const hide = () => t.classList.remove("show");
    if (action) t.querySelector(".toast-act").onclick = () => { hide(); onAction?.(); };
    clearTimeout(t._h); t._h = setTimeout(hide, ms || (action ? 7000 : kind === "error" ? 5000 : 2600));
  }
  // A removal that can be taken back: say it's done and offer Undo for a few seconds.
  function undoable(msg, undo, done = "Undone") {
    toast(msg, { kind: "success", action: "Undo", onAction: async () => {
      try { await undo(); toast(done, { kind: "success" }); } catch (e) { toast(e.message, { kind: "error" }); }
    } });
  }

  // ---------- the warning dialog ----------
  // title, body and items are HTML: escape anything a person typed. With run, the dialog stays open, its button
  // spinning, until run resolves; an error shows in the dialog so it can be retried. Resolves true once confirmed (and done).
  function confirm({ title, body = "", items = [], ok = "Delete", icon: ic = "trash", danger = true, typed = "", run } = {}) {
    let d = document.getElementById("confirm");
    if (!d) { d = document.createElement("dialog"); d.id = "confirm"; d.className = "modal confirm"; document.body.append(d); }
    d.dispatchEvent(new Event("supersede"));
    return new Promise(resolve => {
      let settled = false, working = false;
      const finish = v => { if (!settled) { settled = true; resolve(v); } };
      const more = items.length > 6 ? `<li class="faint">and ${items.length - 6} more</li>` : "";
      d.innerHTML = `<form method="dialog" novalidate>
        <div class="cf-head"><span class="cf-ico ${danger ? "danger" : ""}">${icon(ic)}</span><div><h3>${title}</h3>${body ? `<p class="muted">${body}</p>` : ""}</div></div>
        ${items.length ? `<ul class="cf-items">${items.slice(0, 6).map(x => `<li>${x}</li>`).join("")}${more}</ul>` : ""}
        ${typed ? `<label class="in"><span>Type <b>${escape(typed)}</b> to confirm</span><input name="typed" autocomplete="off" spellcheck="false"></label>` : ""}
        <p class="err" role="alert"></p>
        <div class="row end"><button type="button" class="btn" data-cf-no>Cancel</button><button type="submit" class="btn primary ${danger ? "danger" : ""}" ${typed ? "disabled" : ""}>${ok}</button></div>
      </form>`;
      const f = d.querySelector("form"), go = f.querySelector("[type=submit]"), no = f.querySelector("[data-cf-no]"), err = f.querySelector(".err");
      const off = () => { d.removeEventListener("supersede", off); finish(false); };
      d.addEventListener("supersede", off);
      d.onclose = () => { if (!d.open) off(); };
      d.oncancel = e => { if (working) e.preventDefault(); };  // Esc doesn't abandon work in flight
      no.onclick = () => { if (!working) d.close(); };
      const matches = () => !typed || f.elements.typed.value.trim() === typed;
      if (typed) f.elements.typed.oninput = () => { go.disabled = !matches(); };
      f.onsubmit = async e => {
        e.preventDefault();
        if (working || !matches()) return;
        if (!run) { finish(true); return d.close(); }
        working = true; err.textContent = ""; go.disabled = no.disabled = true; go.classList.add("loading");
        try { await run(); finish(true); d.close(); }
        catch (x) { if (x?.message !== "cancelled") err.textContent = x?.message || "Something went wrong. Please try again."; }
        finally { working = false; go.classList.remove("loading"); go.disabled = !matches(); no.disabled = false; }
      };
      d.showModal();
      (typed ? f.elements.typed : no).focus();  // a removal starts on Cancel: Enter alone never deletes
    });
  }

  return { begin, toast, undoable, confirm };
})();
