"use strict";
// Developer page (administrators): the host helpers the page's scripts (dvp-workspace/viewer/console/claude.js, ported
// from Agent Company's Developer page) were written against, made from AXoR's own. Loaded before them.
// - api(path, {method, body}): JSON fetch with AXoR's anti-CSRF header; a change the server answers with SUDO_REQUIRED
//   (opening a terminal, a Claude prompt) asks for the password / authenticator code once (Admin.withSudo) and retries.
//   No progress bar: the Claude panel polls every 600 ms.
// - store: raw strings in localStorage (AXoR's own store JSON-encodes); keys start with "dvp.".
// - icon(name, size), pickFolder(start), toast(msg), view() (the page's section), float (menus outside the page).
window.DevHost = (() => {
  const call = async (path, opts = {}) => {
    const method = opts.method || "GET";
    const res = await fetch(path, {
      method, credentials: "same-origin", cache: "no-store",
      headers: { "X-Requested-With": "scout", ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const e = new Error(typeof data.detail === "string" ? data.detail : res.statusText || "Something went wrong.");
      e.status = res.status; e.code = data.code;
      if (res.status === 401 && typeof Auth !== "undefined") Auth.expired?.();
      throw e;
    }
    return data;
  };
  // Admin and Auth are top-level consts of admin.js / auth.js (not window properties)
  const api = (path, opts = {}) => (!opts.method || opts.method === "GET" || typeof Admin === "undefined" || !Admin.withSudo)
    ? call(path, opts) : Admin.withSudo(() => call(path, opts));

  // A file's raw bytes (AXoR takes no multipart forms): explorer uploads and Claude attachments, with the same sudo retry.
  const send = (url, file, type) => {
    const go = async () => {
      const res = await fetch(url, { method: "POST", body: file, credentials: "same-origin",
        headers: { "X-Requested-With": "scout", "Content-Type": type || "application/octet-stream" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { const e = new Error(typeof data.detail === "string" ? data.detail : res.statusText); e.status = res.status; throw e; }
      return data;
    };
    return typeof Admin !== "undefined" && Admin.withSudo ? Admin.withSudo(go) : go();
  };

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, String(v)); } catch { /* private mode */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };

  const ALIAS = { files: "folder", workspace: "code", pulse: "activity", clock: "clock", plus: "plus" };
  const icon = (name, size) => {
    const svg = window.icon(ALIAS[name] || name, "dvp-ic");
    return size ? svg.replace("<svg ", `<svg width="${size}" height="${size}" `) : svg;
  };

  let float = null;  // context menus and the folder picker live in <body>, styled by dvp.css
  const floatEl = () => {
    if (!float) { float = document.createElement("div"); float.className = "dvp-float"; document.body.append(float); }
    return float;
  };

  // "Choose a folder": folder names anywhere on the server (admins), as on Agent Company's project form.
  function pickFolder(start) {
    return new Promise((resolve) => {
      const holder = document.createElement("div");
      holder.className = "dvp-modal";
      holder.innerHTML = `<div class="dvp-modal-card" role="dialog" aria-modal="true" aria-label="Choose a folder"><div class="dvp-pf"></div></div>`;
      floatEl().append(holder);
      const close = (v) => { holder.remove(); removeEventListener("keydown", onKey, true); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(null); } };
      addEventListener("keydown", onKey, true);
      holder.onclick = (e) => { if (e.target === holder) close(null); };
      const folderIcon = window.DVP?.fileIcon ? (n) => window.DVP.fileIcon(n, true, 16) : () => icon("folder", 16);
      const load = async (p) => {
        let d;
        try { d = await call(`/api/dev/files/folders?path=${encodeURIComponent(p || "")}`); } catch (e) { toast(e.message); return; }
        holder.querySelector(".dvp-pf").innerHTML = `<h3>Choose a folder</h3>
          <div class="row nowrap"><code class="grow ellipsis">${esc(d.path)}</code>${d.git ? '<span class="pill">git</span>' : ""}</div>
          <div class="flist">${d.parent ? `<div class="fitem" tabindex="0" data-p="${esc(d.parent)}">${folderIcon("..")} ..</div>` : ""}${d.folders.map((f) =>
            `<div class="fitem" tabindex="0" data-p="${esc(f.path)}">${folderIcon(f.name)}<span class="grow ellipsis">${esc(f.name)}</span>${f.git ? '<span class="pill">git</span>' : ""}</div>`).join("")}</div>
          <div class="row dvp-pf-acts"><button type="button" class="btn" data-pf="cancel">Cancel</button><button type="button" class="btn primary" data-pf="ok">Use this folder</button></div>`;
        holder.querySelectorAll("[data-p]").forEach((el) => {
          el.onclick = () => load(el.dataset.p);
          el.onkeydown = (e) => { if (e.key === "Enter") load(el.dataset.p); };
        });
        holder.querySelector('[data-pf="ok"]').onclick = () => close(d.path);
        holder.querySelector('[data-pf="cancel"]').onclick = () => close(null);
        holder.querySelector('[data-pf="ok"]').focus();
      };
      load(start);
    });
  }

  // The page fills the window below the top bar: each pane scrolls itself, the page never does (wide screens).
  const view = () => document.getElementById("view-developer");
  function fit() {
    const v = view();
    if (!v || v.hidden) return;
    if (matchMedia("(max-width: 900px)").matches) { v.style.height = ""; return; }
    const sb = document.getElementById("statusbar");
    const bottom = sb && !sb.hidden && getComputedStyle(sb).position === "fixed" ? sb.getBoundingClientRect().height : 0;
    v.style.height = Math.max(420, Math.floor(innerHeight - v.getBoundingClientRect().top - bottom - 4)) + "px";
  }
  addEventListener("resize", () => { fit(); window.DVP?.fitTerminals?.(); });

  function open() {
    view()?.classList.add("dvp-on");
    window.DVP.open();
    fit(); requestAnimationFrame(fit);
  }

  // The Claude panel's /status drawer (Agent Company's app.js): numbers, times, and the plan's limits as rings.
  const fmt = new Intl.NumberFormat();
  const inTz = (opts = {}) => opts;  // Agent Company could pin a company time zone; AXoR shows the browser's
  const LIMIT_SEV = { warning: "near the limit", critical: "at the limit", exceeded: "limit reached" };
  const timeLeft = (s) => { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`; };
  const limitRing = (pct, sev) => {
    const v = Math.max(0, Math.min(100, pct)), r = 15, len = 2 * Math.PI * r;
    return `<svg class="wc-ring ${LIMIT_SEV[sev] ? esc(sev) : "normal"}" viewBox="0 0 36 36" aria-hidden="true"><circle class="trk" cx="18" cy="18" r="${r}"/>`
      + (v > 0 ? `<circle class="val" cx="18" cy="18" r="${r}" stroke-dasharray="${(len * v / 100).toFixed(2)} ${len.toFixed(2)}" transform="rotate(-90 18 18)"/>` : "")
      + `<text x="18" y="18">${Math.round(v)}%</text></svg>`;
  };
  function limitCards(limits) {
    const now = Date.now();
    const card = (l) => {
      const at = Date.parse(l.resets_at || ""), pct = Math.round(l.percent);
      const when = at ? new Date(at).toLocaleString([], inTz({ weekday: "short", hour: "2-digit", minute: "2-digit" })) : "";
      return `<div class="wc-limit" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="${esc(l.label)}: ${pct}% used" title="${esc(l.label)}: ${pct}% of the limit used${at ? `\nResets ${esc(new Date(at).toLocaleString())}` : ""}">
        ${limitRing(l.percent, l.severity)}<div><b>${esc(l.label)}</b><div><b>${pct}%</b> <span class="muted">used</span>${LIMIT_SEV[l.severity] ? ` <span class="wc-badge ${esc(l.severity)}">${LIMIT_SEV[l.severity]}</span>` : ""}</div>
        ${at ? `<div class="muted">resets ${esc(when)} · in ${timeLeft(Math.max(0, (at - now) / 1000))}</div>` : ""}</div></div>`;
    };
    return `<div class="wc-limits">${limits.map(card).join("")}</div>`;
  }

  return { api, send, store, icon, fmt, inTz, limitCards, pickFolder, toast: (m) => window.toast(m), view, get float() { return floatEl(); }, open, fit };
})();
