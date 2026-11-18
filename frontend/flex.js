/* Flexible layouts: a page's panels on a six-column grid that each viewer arranges for themselves (My subnets' overview, a
   competition team's Desk). Customize shows a bar on every panel: drag it by its grip (or use the arrows) to move it, pick its
   width (or drag its corner), fold it to its title or hide it; hidden panels wait in the toolbar to come back. Presets set the
   whole arrangement at once; Compact tightens the spacing. Layouts live in this browser (store), per page.
   A page calls Flex.grid(page, panels) where it would write its panels, after Flex.register(page, { render, presets }) once:
   panels are [{ k, title, icon, html, size (1–6 columns), head (always show the title bar) }]; render() redraws the page. */
const Flex = (() => {
  const views = {}, editing = new Set();
  const WIDTHS = [[2, "Third"], [3, "Half"], [4, "Two thirds"], [6, "Full width"]];
  let wired = false, drag = null;

  function register(page, opts) { views[page] = { presets: [], ...views[page], ...opts }; wire(); }
  const saved = page => store.get(`flex.${page}`, null);
  function layout(page) {
    const v = views[page] || {}, s = saved(page);
    const base = s || v.presets?.[0]?.layout || {};
    return { order: [], size: {}, hide: [], fold: [], density: "cozy", preset: s ? s.preset ?? null : v.presets?.[0]?.id ?? null, ...base, ...(s || {}) };
  }
  function save(page, L) { store.set(`flex.${page}`, L); views[page]?.render?.(); }
  function change(page, fn) { const L = layout(page); fn(L); L.preset = null; save(page, L); }

  function sorted(panels, L) {
    const at = k => { const i = L.order.indexOf(k); return i < 0 ? 1000 + panels.findIndex(p => p.k === k) : i; };
    return [...panels].sort((a, b) => at(a.k) - at(b.k));
  }

  function grid(page, panels) {
    const L = layout(page), ed = editing.has(page);
    const list = sorted(panels.filter(p => p.html || ed), L);
    const shown = list.filter(p => !L.hide.includes(p.k)), hidden = list.filter(p => L.hide.includes(p.k));
    // outside Customize, the last panel of a row widens into the gap the next one can't fit in (a hidden or empty panel leaves one)
    const fill = [], width = p => Math.min(6, Math.max(1, +(L.size[p.k] ?? p.size ?? 3)));
    let col = 0;
    shown.forEach((p, i) => { const w = width(p); if (col + w > 6) { fill[i - 1] = 6 - col; col = 0; } col += w; });
    if (shown.length) fill[shown.length - 1] = 6 - col;
    return `<div class="flex ${L.density === "compact" ? "compact" : ""} ${ed ? "editing" : ""}" data-flex="${page}">
      ${bar(page, L, ed, hidden)}
      <div class="flex-grid">${shown.map((p, i) => panel(p, L, ed, i, shown.length, ed ? 0 : fill[i])).join("") || `<div class="empty small flex-none">Every panel is hidden. ${ed ? "Bring one back from the bar above." : `<button type="button" class="linkbtn" data-flexact="edit">Customize</button> to bring them back.`}</div>`}</div></div>`;
  }
  function bar(page, L, ed, hidden) {
    const P = views[page]?.presets || [];
    return `<div class="flex-bar" role="toolbar" aria-label="Layout">
      ${P.length ? `<label class="flex-preset"><span class="faint small">${icon("grid")}Layout</span><select data-flexpreset aria-label="Layout preset">
        ${P.map(p => `<option value="${esc(p.id)}" ${L.preset === p.id ? "selected" : ""}>${esc(p.label)}</option>`).join("")}${L.preset == null ? `<option value="" selected>Custom</option>` : ""}</select></label>` : ""}
      <button type="button" class="btn sm ${ed ? "primary" : ""}" data-flexact="edit" aria-pressed="${ed}">${icon(ed ? "check" : "sliders")}${ed ? "Done" : "Customize"}</button>
      <button type="button" class="iconbtn" data-flexact="density" aria-pressed="${L.density === "compact"}" title="${L.density === "compact" ? "Comfortable spacing" : "Compact spacing"}" aria-label="Compact spacing">${icon(L.density === "compact" ? "expand" : "shrink")}</button>
      ${ed ? `<button type="button" class="btn sm ghost" data-flexact="reset">${icon("reset")}Reset</button>
        ${hidden.length ? `<span class="flex-hidden"><span class="faint small">Hidden:</span>${hidden.map(p => `<button type="button" class="flex-chip" data-flexact="show" data-k="${esc(p.k)}">${icon("plus")}${esc(p.title)}</button>`).join("")}</span>` : ""}
        <span class="faint small flex-tip">Drag a panel by its grip to move it; drag its corner to resize.</span>` : ""}</div>`;
  }
  function panel(p, L, ed, i, n, extra = 0) {
    const size = Math.min(6, Math.max(1, +(L.size[p.k] ?? p.size ?? 3))), fold = L.fold.includes(p.k);
    const head = ed || p.head || fold;
    return `<section class="flex-p w-${Math.min(6, size + (extra || 0))} ${fold ? "folded" : ""}" data-flexp="${esc(p.k)}" aria-label="${esc(p.title)}">
      ${head ? `<header class="flex-ph">${ed ? `<span class="flex-grip" data-flexgrip title="Drag to move" aria-hidden="true">${icon("dots")}</span>` : ""}
        <b>${p.icon ? icon(p.icon) : ""}${esc(p.title)}</b>
        <span class="flex-pa">${ed ? `<button type="button" class="iconbtn" data-flexact="left" ${i ? "" : "disabled"} title="Move earlier" aria-label="Move ${esc(p.title)} earlier">${icon("left")}</button>
            <button type="button" class="iconbtn" data-flexact="right" ${i < n - 1 ? "" : "disabled"} title="Move later" aria-label="Move ${esc(p.title)} later">${icon("right")}</button>
            <select data-flexsize aria-label="Width of ${esc(p.title)}">${WIDTHS.map(([w, l]) => `<option value="${w}" ${w === size ? "selected" : ""}>${l}</option>`).join("")}${WIDTHS.some(([w]) => w === size) ? "" : `<option value="${size}" selected>${size} of 6</option>`}</select>
            <button type="button" class="iconbtn" data-flexact="hide" title="Hide" aria-label="Hide ${esc(p.title)}">${icon("eyeoff")}</button>` : ""}
          <button type="button" class="iconbtn" data-flexact="fold" title="${fold ? "Unfold" : "Fold to its title"}" aria-label="${fold ? "Unfold" : "Fold"} ${esc(p.title)}" aria-expanded="${!fold}">${icon(fold ? "down" : "up")}</button></span></header>` : ""}
      ${fold ? "" : `<div class="flex-pb">${p.html || `<p class="faint small">Nothing to show here right now.</p>`}</div>`}
      ${ed && !fold ? `<span class="flex-rs" data-flexrs title="Drag to resize" aria-hidden="true"></span>` : ""}</section>`;
  }

  // ---------- events (one set for every page) ----------
  const where = el => { const f = el.closest("[data-flex]"); return f && views[f.dataset.flex] ? f.dataset.flex : null; };
  const keys = f => $$(":scope > .flex-grid > [data-flexp]", f).map(x => x.dataset.flexp);
  function move(page, f, k, to) {
    change(page, L => {
      const order = keys(f).filter(x => x !== k);  // the panels as shown; hidden ones keep their place after them
      order.splice(Math.max(0, Math.min(order.length, to)), 0, k);
      L.order = [...order, ...L.order.filter(x => !order.includes(x))];
    });
  }
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const b = e.target.closest("[data-flexact]"); if (!b) return;
      const page = where(b); if (!page) return;
      const k = b.dataset.k || b.closest("[data-flexp]")?.dataset.flexp, f = b.closest("[data-flex]"), act = b.dataset.flexact;
      if (act === "edit") { editing.has(page) ? editing.delete(page) : editing.add(page); return views[page].render(); }
      if (act === "density") return change(page, L => { L.density = L.density === "compact" ? "cozy" : "compact"; });
      if (act === "reset") { store.set(`flex.${page}`, null); return views[page].render(); }
      if (act === "show") return change(page, L => { L.hide = L.hide.filter(x => x !== k); });
      if (act === "hide") return change(page, L => { L.hide = [...new Set([...L.hide, k])]; });
      if (act === "fold") return change(page, L => { L.fold = L.fold.includes(k) ? L.fold.filter(x => x !== k) : [...L.fold, k]; });
      if (act === "left" || act === "right") { const ks = keys(f), i = ks.indexOf(k); return move(page, f, k, i + (act === "left" ? -1 : 1)); }
    });
    document.addEventListener("change", e => {
      const page = where(e.target); if (!page) return;
      if (e.target.matches("[data-flexpreset]")) {
        const p = views[page].presets.find(x => x.id === e.target.value); if (!p) return;
        const d = layout(page).density;
        return save(page, { order: [], size: {}, hide: [], fold: [], density: d, ...p.layout, preset: p.id });
      }
      if (e.target.matches("[data-flexsize]")) { const k = e.target.closest("[data-flexp]").dataset.flexp; change(page, L => { L.size = { ...L.size, [k]: +e.target.value }; }); }
    });
    // moving: the grip drags its panel; it lands before the panel under the pointer (after it, past its middle)
    document.addEventListener("pointerdown", e => {
      const g = e.target.closest("[data-flexgrip], [data-flexrs]"); if (!g || e.button) return;
      const page = where(g); if (!page) return;
      const p = g.closest("[data-flexp]"), f = g.closest("[data-flex]"), gridEl = $(".flex-grid", f);
      e.preventDefault();
      drag = { page, f, k: p.dataset.flexp, el: p, rs: g.matches("[data-flexrs]"), x0: e.clientX, left: p.getBoundingClientRect().left,
               col: (gridEl.getBoundingClientRect().width + 12) / 6, size: null, to: null };
      p.classList.add(drag.rs ? "sizing" : "moving");
      g.setPointerCapture?.(e.pointerId);
    });
    document.addEventListener("pointermove", e => {
      if (!drag) return;
      if (drag.rs) {
        const n = Math.max(1, Math.min(6, Math.round((e.clientX - drag.left) / drag.col)));
        if (n !== drag.size) { drag.size = n; drag.el.className = drag.el.className.replace(/\bw-\d\b/, `w-${n}`); }
        return;
      }
      $$(".flex-p.drop-b, .flex-p.drop-a", drag.f).forEach(x => x.classList.remove("drop-b", "drop-a"));
      const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-flexp]");
      if (!over || over === drag.el || over.closest("[data-flex]") !== drag.f) { drag.to = null; return; }
      const r = over.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
      over.classList.add(after ? "drop-a" : "drop-b");
      const ks = keys(drag.f).filter(x => x !== drag.k), i = ks.indexOf(over.dataset.flexp);
      drag.to = i + (after ? 1 : 0);
    });
    const end = () => {
      if (!drag) return;
      const d = drag; drag = null;
      d.el.classList.remove("moving", "sizing");
      $$(".flex-p.drop-b, .flex-p.drop-a", d.f).forEach(x => x.classList.remove("drop-b", "drop-a"));
      if (d.rs && d.size) change(d.page, L => { L.size = { ...L.size, [d.k]: d.size }; });
      else if (!d.rs && d.to != null) move(d.page, d.f, d.k, d.to);
    };
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  }

  return { register, grid, layout, editing: page => editing.has(page) };
})();
