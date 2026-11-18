/* Writing help (writing.py): an AI writing assistant in the text fields of every page. Click into a field and type a
   few words: when you pause, the model checks the text, and the small button in the field's corner shows how many
   mistakes it found. Leaving the field fixes small mistakes for you, with Undo (never anything that changes more than a
   few words or drops a line). The button opens the panel: the corrections, better wordings to use with one click, and a
   box to say what you mean ("friendlier", "mention my 4090") for new wordings that follow it. Alt+Shift+W opens it too.

   Password, key, seed, address, code and other technical fields are never checked, nor text that looks like a seed
   phrase, a key or code; a field (or an ancestor) with data-writer="off" opts out. Settings are per browser. */
const Writer = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("writer." + k)); localStorage.setItem("writer." + k, JSON.stringify(v)); } catch { return null; } };
  const DEFAULTS = { live: true, autofix: true };
  const on = k => pref(k) ?? DEFAULTS[k];
  const DELAY = 1200;  // ms of no typing before a check
  const TYPES = /^(text|)$/;
  // ids, names, labels and placeholders of fields that hold secrets, identifiers or code
  const RISKY = /pass|secret|token|seed|mnemonic|recovery|private|hotkey|coldkey|ss58|search|filter|key\b|\bkeys\b|\b(find|address|slug|user(name)?|login|host(name)?|domain|url|link|hash|otp|totp|2fa|code|cron|regex|path|branch|command|cmd|image|port|ip|email|phone|tag|sql|query|json|yaml|script)\b/i;
  const SEED = /^(?:[a-z]+\s+){11,23}[a-z]+$/;
  const SECRET = /sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-|AKIA[0-9A-Z]{16}|0x[0-9a-fA-F]{64}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|\beyJ[A-Za-z0-9_-]{20,}\./;
  const CODE = /```|^\s*[{[<]|^\s*(def|class|import|from|function|const|let|var|SELECT|INSERT|#!|\$ )\b/m;

  let live = false, el = null, chip = null, panel = null, notice = null, timer = 0, writing = false, gear = false;
  const sizes = new ResizeObserver(() => place());  // a textarea grows or is resized
  const state = new WeakMap();  // field -> { res, busy, err, idea }
  const cache = new Map();      // text|idea -> answer, for the last 40 checks
  const st = f => state.get(f) || (state.set(f, {}), state.get(f));
  const pageName = () => { const v = typeof S !== "undefined" ? S.view : ""; return $(`nav.side [data-view="${v}"]`)?.title || v || ""; };
  const key = (f = el) => `${typeof S !== "undefined" ? S.view : ""}|${f.id || f.name || f.placeholder || f.getAttribute("aria-label") || ""}`;
  const mine = n => !!n && [chip, panel, notice].some(x => x && x.contains(n));

  async function init() {
    if (live || !Auth.me()) return;
    try {
      const r = await fetch("/api/writing/status", { credentials: "same-origin" });
      if (!r.ok || !(await r.json()).available) return;  // no agents for this user, or no model set up
    } catch { return; }
    live = true;
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onBlur);
    document.addEventListener("input", onInput);
    document.addEventListener("keydown", onKey, true);
    addEventListener("scroll", place, { capture: true, passive: true });
    addEventListener("resize", place);
  }

  // ---------- which fields and which text ----------
  function labelOf(f) {
    const l = f.labels?.[0] || f.closest("label");
    return (l?.textContent || f.getAttribute("aria-label") || f.placeholder || f.title || "").replace(/\s+/g, " ").trim().slice(0, 120);
  }
  function eligible(f) {
    if (!f || !(f.tagName === "TEXTAREA" || (f.tagName === "INPUT" && TYPES.test(f.getAttribute("type") || "")))) return false;
    if (f.readOnly || f.disabled || mine(f) || f.closest("[data-writer=off]") || f.getAttribute("spellcheck") === "false") return false;
    if (!f.closest("main, dialog[open], #assist")) return false;
    if (f.tagName === "INPUT" && (f.pattern || (f.maxLength > 0 && f.maxLength < 24))) return false;
    const names = [f.id, f.name, f.placeholder, f.getAttribute("aria-label"), f.getAttribute("autocomplete"), labelOf(f)].filter(Boolean).join(" ");
    return !RISKY.test(names);
  }
  function worth(t) {
    const s = t.trim();
    if (s.length < 12 || s.length > 4000 || s.split(/\s+/).length < 3 || !/\p{L}/u.test(s)) return false;
    if (SEED.test(s) && [12, 15, 18, 21, 24].includes(s.split(/\s+/).length)) return false;
    return !SECRET.test(s) && !CODE.test(s) && (s.match(/[;{}=<>]/g) || []).length <= s.length / 40;
  }

  // ---------- events ----------
  function onFocus(e) {
    const f = e.target;
    if (mine(f)) return;
    if (f === el) return show();
    detach();
    if (!eligible(f) || (pref("off") || []).includes(key(f))) return;
    el = f;
    sizes.observe(f);
    show();
    if (on("live") && !st(f).res && worth(f.value)) schedule();
  }
  function onInput(e) {
    if (writing || e.target !== el) return;
    const s = st(el);
    if (s.res && s.res.text !== el.value) s.res = cache.get(`${el.value}|`) || null;
    s.err = null;
    clearTimeout(timer);
    if (on("live") && worth(el.value) && !s.res) schedule();
    paint();
    if (panel && !panel.hidden) render();
  }
  function onBlur(e) {
    if (!el || mine(e.relatedTarget) || e.relatedTarget === el || (e.target !== el && !mine(e.target))) return;
    const f = el;
    clearTimeout(timer);
    if (e.target === f) autofix(f);  // not when leaving the panel's own idea box
    setTimeout(() => { if (el === f && document.activeElement !== f && !mine(document.activeElement)) detach(); }, 150);
  }
  function onKey(e) {
    if (!el) return;
    const inField = e.target === el, inPanel = panel && panel.contains(e.target);
    if (inField && e.altKey && e.shiftKey && e.code === "KeyW") { e.preventDefault(); return toggle(true); }
    if (e.key === "Escape" && (inPanel || (inField && panel && !panel.hidden))) {
      e.preventDefault(); e.stopPropagation();  // close the panel, not the dialog
      toggle(false); el.focus({ preventScroll: true });
    }
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { if (el && worth(el.value)) check(el); }, DELAY);
  }

  // ---------- checking ----------
  async function check(f, idea = "") {
    const s = st(f), text = f.value, k = `${text}|${idea}`;
    if (cache.has(k)) { s.res = cache.get(k); s.idea = idea; return refresh(f); }
    if (s.busy) { s.again = idea; return; }
    s.busy = true; s.err = null; refresh(f);
    try {
      const r = await fetch("/api/writing/check", {
        method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "scout", "Content-Type": "application/json" },
        body: JSON.stringify({ text, idea, field: labelOf(f), page: pageName(), single_line: f.tagName === "INPUT" }) });
      const d = await r.json().catch(() => ({}));
      if (r.status === 401 || r.status === 403 || r.status === 503) { stop(); return; }  // signed out, no access, or no model
      if (r.status === 429 && !idea && f === el) {  // still checking another field: try again shortly
        setTimeout(() => { if (el === f && f.value === text && !st(f).res) check(f); }, 2500); return;
      }
      if (!r.ok) { if (r.status !== 429 || idea) s.err = typeof d.detail === "string" ? d.detail : "Writing help failed. Try again."; return; }
      cache.set(k, d); if (cache.size > 40) cache.delete(cache.keys().next().value);
      if (!idea) cache.set(`${d.text}|`, d);
      if (f.value === text) { s.res = d; s.idea = idea; }
    } catch { s.err = "Couldn't reach AXoR. Try again."; }
    finally {
      s.busy = false; refresh(f);
      if (s.again !== undefined) { const a = s.again; delete s.again; if (f === el && f.value !== s.res?.text) check(f, a); }
      else if (f === el && on("live") && !s.res && !s.err && worth(f.value) && f.value !== text) schedule();  // typed on while it ran
    }
  }
  function refresh(f) { if (f === el) { paint(); if (panel && !panel.hidden) render(); } }
  function stop() {  // writing help isn't available after all: quietly off until the next page load
    live = false; detach();
    document.removeEventListener("focusin", onFocus); document.removeEventListener("focusout", onBlur);
    document.removeEventListener("input", onInput); document.removeEventListener("keydown", onKey, true);
  }

  // ---------- word diff ----------
  function diff(a, b) {
    const x = a.split(/(\s+)/), y = b.split(/(\s+)/);
    if (x.length * y.length > 2e6) return null;
    const n = x.length, m = y.length, L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    const out = []; let i = 0, j = 0;
    const push = (t, v) => { const last = out[out.length - 1]; if (last && last.t === t) last.v += v; else out.push({ t, v }); };
    while (i < n && j < m) {
      if (x[i] === y[j]) { push("=", x[i]); i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) push("-", x[i++]);
      else push("+", y[j++]);
    }
    while (i < n) push("-", x[i++]);
    while (j < m) push("+", y[j++]);
    return out;
  }
  // small enough to apply without asking: a few words changed, none much longer, no lines added or dropped
  function small(res) {
    const d = diff(res.text, res.corrected);
    if (!d) return false;
    const words = t => t.split(/\s+/).filter(Boolean).length, lines = t => t.split("\n").length;
    const gone = d.filter(p => p.t === "-").reduce((n, p) => n + words(p.v), 0), added = d.filter(p => p.t === "+").reduce((n, p) => n + words(p.v), 0);
    return Math.max(gone, added) <= Math.min(15, Math.max(4, words(res.text) * 0.2)) && Math.abs(gone - added) <= 2 && lines(res.text) === lines(res.corrected);
  }
  const diffHtml = res => {
    const d = diff(res.text, res.corrected);
    return d ? d.map(p => p.t === "=" ? esc(p.v) : p.t === "-" ? `<del>${esc(p.v)}</del>` : `<ins>${esc(p.v)}</ins>`).join("") : esc(res.corrected);
  };

  // ---------- applying ----------
  function put(f, text) {
    writing = true;
    try {
      f.value = text;
      f.dispatchEvent(new Event("input", { bubbles: true }));
      f.dispatchEvent(new Event("change", { bubbles: true }));
    } finally { writing = false; }
  }
  function apply(f, text, msg) {
    const s = st(f), before = f.value, res = s.res;
    put(f, text);
    // the new text needs no check: its corrections are done, the other wordings still stand
    s.res = { text, corrected: text, changes: [], rewrites: (res?.rewrites || []).filter(r => r.text !== text), tip: res?.tip || "" };
    cache.set(`${text}|`, s.res);
    toast(f, msg, () => { put(f, before); s.res = res; if (f === el) { paint(); f.focus({ preventScroll: true }); } });
    refresh(f);
  }
  function autofix(f) {
    const res = st(f).res;
    if (!on("autofix") || !res || res.text !== f.value || res.corrected === res.text || !small(res)) return;
    const n = res.changes.length || 1;
    apply(f, res.corrected, `Fixed ${n} mistake${n === 1 ? "" : "s"}`);
  }

  // ---------- the button in the field ----------
  function host(f) { return f.closest("dialog[open]") || document.body; }  // inside an open dialog, or it's inert
  function pop(node, f) {
    const h = host(f);
    if (node.parentNode !== h) h.append(node);
    if (node.showPopover && !node.matches(":popover-open")) { node.popover = "manual"; try { node.showPopover(); } catch {} }  // the top layer: never clipped
    node.hidden = false;
  }
  function show() {
    if (!el) return;
    if (!chip) {
      chip = document.createElement("button");
      chip.type = "button"; chip.className = "wr-chip"; chip.tabIndex = -1;
      chip.addEventListener("pointerdown", e => e.preventDefault());  // keep the focus in the field
      chip.addEventListener("click", () => toggle());
    }
    pop(chip, el);
    paint(); place();
  }
  function paint() {
    if (!chip || !el) return;
    const s = st(el), res = s.res, n = res && res.text === el.value && res.corrected !== res.text ? res.changes.length || 1 : 0;
    const mode = s.busy ? "busy" : s.err ? "err" : n ? "fix" : res && res.text === el.value ? "ok" : "idle";
    chip.className = `wr-chip ${mode}`;
    chip.innerHTML = mode === "fix" ? `${icon("sparkle")}<b>${n}</b>` : mode === "ok" ? icon("check") : icon("sparkle");
    const say = { busy: "Writing help: checking…", err: "Writing help: the check failed", fix: `Writing help: ${n} fix${n === 1 ? "" : "es"} ready`,
                  ok: "Writing help: no mistakes, better wordings ready", idle: "Writing help: check and improve this text" }[mode];
    chip.title = `${say} (Alt+Shift+W)`; chip.setAttribute("aria-label", say);
    chip.setAttribute("aria-expanded", String(!!panel && !panel.hidden));
    place();  // its width changes with the count
  }
  function place() {
    if (!el) return;
    if (!el.isConnected || !el.getClientRects().length) return detach();
    const r = el.getBoundingClientRect();
    if (chip && !chip.hidden) {
      const size = 24, multi = el.tagName === "TEXTAREA";
      chip.style.left = `${Math.round(r.right - chip.offsetWidth - 6)}px`;
      chip.style.top = `${Math.round(multi ? r.bottom - size - 6 : r.top + (r.height - size) / 2)}px`;
      chip.style.visibility = r.bottom < 0 || r.top > innerHeight ? "hidden" : "";
    }
    if (panel && !panel.hidden) {
      const w = Math.min(Math.max(r.width, 320), 440, innerWidth - 16);
      panel.style.width = `${w}px`;
      // the page guide's suggestions hug the field: stack beyond them, on whichever side has more room
      const g = $(".gd-hint")?.getBoundingClientRect(), gh = g ? g.height + 6 : 0, gBelow = g && g.top >= r.bottom - 1;
      const up = r.top - 14 - (g && !gBelow ? gh : 0), down = innerHeight - r.bottom - 14 - (gBelow ? gh : 0);
      panel.style.maxHeight = "520px";
      const want = Math.min(panel.offsetHeight, innerHeight - 16), below = down >= want || down >= up;
      panel.style.maxHeight = `${Math.max(160, Math.min(520, below ? down : up))}px`;
      const h = panel.offsetHeight;
      panel.style.top = `${Math.round(below ? r.bottom + 6 + (gBelow ? gh : 0) : r.top - 6 - h - (g && !gBelow ? gh : 0))}px`;
      panel.style.left = `${Math.round(Math.max(8, Math.min(r.right - w, innerWidth - w - 8)))}px`;
    }
    if (notice && !notice.hidden && notice.field === el) placeNotice();
  }
  function detach() {
    clearTimeout(timer);
    sizes.disconnect();
    el = null;  // first: hiding repaints, and a repaint places
    if (chip) { chip.hidden = true; try { chip.hidePopover?.(); } catch {} }
    toggle(false);
  }

  // ---------- the panel ----------
  function toggle(open = !panel || panel.hidden) {
    if (!open) {
      if (panel && !panel.hidden) { panel.hidden = true; try { panel.hidePopover?.(); } catch {} }
      gear = false; paint();
      return;
    }
    if (!el) return;
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "wr-panel"; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Writing help");
      panel.addEventListener("pointerdown", e => { if (!e.target.closest("input, label")) e.preventDefault(); });
      panel.addEventListener("click", onPanel);
      panel.addEventListener("submit", e => {
        e.preventDefault();
        const idea = $("[name=idea]", panel).value.trim();
        if (!el || !worth(el.value)) return;
        el.focus({ preventScroll: true });  // the panel redraws while it works
        st(el).idea = idea; check(el, idea);
      });
      panel.addEventListener("change", e => {
        const k = e.target.dataset.pref; if (!k) return;
        pref(k, e.target.checked);
        if (k === "live" && e.target.checked && el && !st(el).res && worth(el.value)) check(el);
      });
    }
    pop(panel, el);
    render();
    const s = st(el);
    if (!s.res && !s.busy && worth(el.value)) check(el, s.idea || "");
  }
  function render() {
    if (!panel || !el) return;
    const s = st(el), res = s.res && s.res.text === el.value ? s.res : null, text = el.value;
    const fixes = res && res.corrected !== res.text;
    const idea = $("[name=idea]", panel)?.value ?? s.idea ?? "";
    const typing = !worth(text) ? (text.trim().length ? "This text isn't checked: it's too short, or looks like code or a key." : "Type a few words and I'll check them as you go.") : "";
    panel.innerHTML = `
      <div class="wr-head"><span class="wr-title">${icon("sparkle")}Writing help</span>
        <button type="button" class="wr-x" data-act="gear" aria-pressed="${gear}" title="Settings" aria-label="Settings">${icon("gear")}</button>
        <button type="button" class="wr-x" data-act="close" title="Close (Esc)" aria-label="Close">${icon("close")}</button></div>
      <div class="wr-body">
        ${gear ? `<div class="wr-set">
          <label><input type="checkbox" data-pref="live" ${on("live") ? "checked" : ""}> Check as I type</label>
          <label><input type="checkbox" data-pref="autofix" ${on("autofix") ? "checked" : ""}> Fix small mistakes when I leave a field (with Undo)</label>
          <button type="button" class="wr-link" data-act="mute">Don't help in this field</button></div>` : ""}
        ${typing ? `<p class="wr-note">${esc(typing)}</p>` : ""}
        ${s.busy ? `<p class="wr-note wr-busy"><span class="spinner"></span>${s.idea ? "Rewording…" : "Checking…"}</p>` : ""}
        ${s.err ? `<p class="wr-err" role="alert">${esc(s.err)}</p>` : ""}
        ${res && !s.busy ? `
          ${fixes ? `<section><h4>Corrections <small>${res.changes.length || 1}</small></h4>
              <div class="wr-diff">${diffHtml(res)}</div>
              ${res.changes.some(c => c.why) ? `<ul class="wr-why">${res.changes.filter(c => c.why).slice(0, 6).map(c => `<li><s>${esc(c.from)}</s> → <b>${esc(c.to)}</b> <span>${esc(c.why)}</span></li>`).join("")}</ul>` : ""}
              <button type="button" class="btn sm primary" data-act="fix">${icon("check")}Apply fixes</button></section>`
            : `<p class="wr-ok">${icon("check")}No spelling or grammar mistakes.</p>`}
          ${res.rewrites.length ? `<section><h4>${s.idea ? `Reworded: ${esc(s.idea)}` : "Better wording"}</h4>
              ${res.rewrites.map((r, i) => `<div class="wr-opt"><span class="wr-lbl">${esc(r.label)}</span><p>${esc(r.text)}</p>
                <button type="button" class="btn sm" data-use="${i}">Use this</button></div>`).join("")}</section>` : ""}
          ${res.tip ? `<p class="wr-tip">${icon("zap")}${esc(res.tip)}</p>` : ""}` : ""}
        <form class="wr-idea"><input name="idea" data-writer="off" maxlength="300" autocomplete="off" aria-label="Your idea for the wording"
            placeholder="Your idea: friendlier, shorter, mention my RTX 4090…" value="${esc(idea)}">
          <button class="btn sm" ${worth(text) && !s.busy ? "" : "disabled"}>${icon("edit")}Reword</button></form>
      </div>`;
    paint(); place();
  }
  function onPanel(e) {
    const b = e.target.closest("button"); if (!b || !el) return;
    const s = st(el), res = s.res, f = el;
    if (b.dataset.act === "close") { toggle(false); f.focus({ preventScroll: true }); }
    else if (b.dataset.act === "gear") { gear = !gear; render(); }
    else if (b.dataset.act === "mute") {
      pref("off", [...(pref("off") || []), key(f)].slice(-200));
      detach(); f.focus({ preventScroll: true });
      UI.toast("Writing help is off in this field. Clear the site's data for this browser to bring it back.");
    }
    else if (b.dataset.act === "fix" && res) { toggle(false); apply(f, res.corrected, "Fixes applied"); f.focus({ preventScroll: true }); }
    else if (b.dataset.use !== undefined && res) {
      const r = res.rewrites[+b.dataset.use]; if (!r) return;
      toggle(false); apply(f, r.text, `Used "${r.label}"`); f.focus({ preventScroll: true });
    }
  }

  // ---------- "Fixed 2 mistakes · Undo" beside the field ----------
  function toast(f, msg, undo) {
    if (!notice) {
      notice = document.createElement("div");
      notice.className = "wr-notice"; notice.setAttribute("role", "status");
      notice.addEventListener("pointerdown", e => e.preventDefault());
    }
    clearTimeout(notice._h);
    notice.field = f;
    notice.innerHTML = `${icon("check")}<span>${esc(msg)}</span><button type="button" class="wr-link">${icon("undo")}Undo</button>`;
    notice.querySelector("button").onclick = () => { hideNotice(); undo(); };
    pop(notice, f);
    placeNotice();
    notice._h = setTimeout(hideNotice, 7000);
  }
  function placeNotice() {
    const f = notice.field;
    if (!f.isConnected || !f.getClientRects().length) return hideNotice();
    const r = f.getBoundingClientRect(), w = notice.offsetWidth, h = notice.offsetHeight;
    notice.style.left = `${Math.round(Math.max(8, Math.min(r.right - w, innerWidth - w - 8)))}px`;
    notice.style.top = `${Math.round(r.top - h - 6 >= 8 ? r.top - h - 6 : r.bottom + 6)}px`;
  }
  function hideNotice() { if (notice) { clearTimeout(notice._h); notice.hidden = true; try { notice.hidePopover?.(); } catch {} } }

  return { init };
})();
