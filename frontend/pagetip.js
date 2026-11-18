// Page descriptions as a tip: the explanation under a page heading (p.lead and the like) is hidden and a "?"
// icon goes right after the heading text; hovering, focusing or pressing it shows the explanation in a framed tip.
// One pass over <main> after every render, so no page file has to change. The original paragraph stays in the
// DOM (hidden), so code that updates it by id or attribute (#sys-lead, data-occ-at …) keeps working; the tip
// copies it each time it opens.
(() => {
  const DESC = "p.lead, p.aos-lede, p.kb-lede, p.amp-lede, p.hp-lead, p.faint, p.muted";
  // content, not a page explanation: stays where it is
  const KEEP = ".mx-dhead, #editor, [data-tip=keep]";
  // live "Updated …" stamps inside a description stay visible next to the heading
  const STAMP = "[data-occ-at], [data-axh-at]";
  let seq = 0, pop = null, anchor = null, pinned = false, hideT = 0;

  function descOf(h) {
    const p = h.nextElementSibling;
    if (!p || !p.matches(DESC) || p.closest(KEEP) || !p.textContent.trim()) return null;
    if (p.matches(".hp-lead") && p.nextElementSibling?.matches(".hp-doc")) return null;  // a help article's summary
    return p;
  }

  function enhance(h) {
    h.dataset.ptip = "";
    const p = descOf(h);
    if (!p) return;
    const stamps = [...p.querySelectorAll(STAMP)];
    if (stamps.length) {
      const s = document.createElement("p");
      s.className = "ptip-stamp";
      stamps.forEach(x => s.append(x));
      h.after(s);
    }
    p.id ||= `ptip-d${++seq}`;
    p.classList.add("ptip-src");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ptip-btn";
    b.setAttribute("aria-label", "About this page");
    b.setAttribute("aria-expanded", "false");
    b.setAttribute("aria-describedby", p.id);
    b.dataset.ptipFor = p.id;
    b.innerHTML = typeof icon === "function" ? icon("help") : "?";
    h.append(b);
  }

  function scan(root) {
    (root || document).querySelectorAll("main h1:not([data-ptip])").forEach(enhance);
    if (anchor && !anchor.isConnected) hide(true);   // the page redrew under an open tip
  }

  // ---------- the tip ----------
  function ensurePop() {
    if (pop) return pop;
    pop = document.createElement("div");
    pop.className = "ptip-pop";
    pop.id = "ptip-pop";
    pop.setAttribute("role", "tooltip");
    pop.hidden = true;
    pop.addEventListener("mouseenter", () => clearTimeout(hideT));
    pop.addEventListener("mouseleave", () => { if (!pinned) later(); });
    document.body.append(pop);
    return pop;
  }
  function place() {
    if (!anchor || pop.hidden) return;
    const r = anchor.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const w = pop.offsetWidth, ht = pop.offsetHeight, gap = 8, edge = 12;
    let left = r.left + r.width / 2 - 22;                       // the arrow sits under the icon
    left = Math.max(edge, Math.min(left, vw - w - edge));
    let top = r.bottom + gap, below = true;
    if (top + ht > vh - edge && r.top - gap - ht > edge) { top = r.top - gap - ht; below = false; }
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    pop.classList.toggle("up", !below);
    pop.style.setProperty("--ptip-arrow", `${Math.max(12, Math.min(w - 20, r.left + r.width / 2 - left))}px`);
  }
  function show(b, pin) {
    const src = document.getElementById(b.dataset.ptipFor);
    if (!src) return;
    clearTimeout(hideT);
    ensurePop();
    const host = b.closest("dialog[open]") || document.body;  // a modal dialog is on the top layer: the tip has to be inside it
    if (pop.parentNode !== host) host.append(pop);
    if (anchor && anchor !== b) anchor.setAttribute("aria-expanded", "false");
    anchor = b;
    pinned = !!pin;
    pop.innerHTML = src.innerHTML;
    pop.hidden = false;
    b.setAttribute("aria-expanded", "true");
    b.classList.toggle("on", pinned);
    place();
  }
  function hide(force) {
    clearTimeout(hideT);
    if (!pop || (pinned && !force)) return;
    pop.hidden = true;
    anchor?.setAttribute("aria-expanded", "false");
    anchor?.classList.remove("on");
    anchor = null; pinned = false;
  }
  const later = () => { clearTimeout(hideT); hideT = setTimeout(() => hide(), 160); };
  const btnOf = e => e.target instanceof Element ? e.target.closest(".ptip-btn") : null;

  document.addEventListener("mouseover", e => { const b = btnOf(e); if (b && !(pinned && anchor === b)) show(b, pinned && anchor === b); });
  document.addEventListener("mouseout", e => { const b = btnOf(e); if (b && b === anchor && !pinned && !b.contains(e.relatedTarget)) later(); });
  document.addEventListener("focusin", e => { const b = btnOf(e); if (b && anchor !== b) show(b, false); });
  document.addEventListener("focusout", e => { const b = btnOf(e); if (b && b === anchor && !pinned) later(); });
  document.addEventListener("click", e => {
    const b = btnOf(e);
    if (b) { e.preventDefault(); e.stopPropagation(); if (anchor === b && pinned) hide(true); else show(b, true); return; }
    if (pop && !pop.hidden && !pop.contains(e.target)) hide(true);
  }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && pop && !pop.hidden) { e.preventDefault(); const b = anchor; hide(true); b?.focus?.(); } });  // closes the tip, not its dialog
  window.addEventListener("resize", () => place());
  document.addEventListener("scroll", () => place(), true);

  // ---------- run after every render ----------
  let queued = false;
  const mo = new MutationObserver(() => { if (!queued) { queued = true; queueMicrotask(() => { queued = false; scan(); }); } });
  function start() {
    scan();
    const m = document.querySelector("main");
    mo.observe(m || document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  window.PageTip = { scan };
})();
