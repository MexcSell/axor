/* Platform pages, two shared pieces (platform.css):
   - Page tabs: every Developer and Infrastructure page opens with a tab strip of its group's pages, each with a dot for
     whether its service is set up (/api/platform/status).
   - Tables: on the platform pages, a table.grid that doesn't sort itself gets sortable headers, a filter box and a Columns
     menu once it has enough rows or columns. The modules keep re-rendering their tables; a sort, filter or hidden column
     is re-applied to the new rows, and remembered per table. Explorer, Drive and tables marked data-plt-skip keep their own. */
const PlatformTables = (() => {
  const TAB_GROUPS = ["developer", "infra"];
  const SERVICE = { docker: "docker", devops: "runner", apps: "kubernetes", functions: "kubernetes", cluster: "kubernetes", machines: "kubernetes", dns: "dns" };
  const MIN_ROWS = 10, MIN_COLS = 7;  // a filter and Columns from this size up (never on small .mini-table summaries)
  let view = "", obs = null, raf = 0;
  const saved = (k, v) => { const all = store.get("plt.tables", {}); if (v === undefined) return all[k] || {}; all[k] = v; store.set("plt.tables", all); };

  // a view name goes into selectors: escaped, and looked up by id, so a name with ":", "/" or "." can't throw "not a valid selector"
  const cssq = v => (window.CSS?.escape ? CSS.escape(String(v)) : String(v).replace(/["\\]/g, "\\$&"));
  const viewEl = v => (v ? document.getElementById("view-" + v) : null);

  // ---------- page tabs ----------
  async function tabs(v) {
    if (!v) return;
    const b = $(`nav.side [data-view="${cssq(v)}"]`), sec = b?.closest(".side-sub");  // Platform → Developer, Platform → Infrastructure
    $$(".plt-tabs").forEach(t => { if (t.parentElement.id !== "view-" + v) t.remove(); });
    if (!sec || !TAB_GROUPS.includes(sec.dataset.sub)) return;
    const pages = $$("button[data-view]", sec).filter(x => !x.hidden);
    if (pages.length < 2) return;
    const host = viewEl(v); if (!host) return;
    let nav = $(":scope > .plt-tabs", host);
    if (!nav) { nav = document.createElement("nav"); nav.className = "plt-tabs"; host.prepend(nav); nav.onclick = e => { const t = e.target.closest("[data-plt-tab]"); if (t) setView(t.dataset.pltTab); }; }
    nav.setAttribute("aria-label", `${sec.querySelector(".side-subh")?.textContent || ""} pages`);
    const draw = st => {
      const svc = k => st?.services?.find(s => s.key === SERVICE[k]);
      nav.innerHTML = pages.map(p => { const s = svc(p.dataset.view);
        return `<button type="button" data-plt-tab="${p.dataset.view}" aria-current="${p.dataset.view === v ? "page" : "false"}" ${s ? `title="${esc(s.label)}: ${esc(s.detail)}"` : ""}>${p.querySelector("svg")?.outerHTML || ""}<span>${esc(p.querySelector(".lbl")?.textContent.trim() || p.title)}</span>${s ? `<i class="plt-dot s-${s.state}" aria-label="${s.state === "ok" ? "set up" : "not set up"}"></i>` : ""}</button>`;
      }).join("");
    };
    draw(Platform.statusNow());
    draw(await Platform.status());
  }

  // ---------- tables ----------
  const SKIP = "#grid, [data-plt-skip], .drawer table, dialog table";
  const cellText = td => (td?.dataset.sort ?? td?.textContent ?? "").trim();
  const UNIT = { b: 1, kb: 1e3, kib: 1024, mb: 1e6, mib: 2 ** 20, gb: 1e9, gib: 2 ** 30, tb: 1e12, tib: 2 ** 40 };
  const AGO = { s: 1, m: 60, h: 3600, d: 86400, w: 604800, mo: 2592000, y: 31536000 };
  function value(t) {
    if (!t || t === "–" || t === "-") return null;
    let m = t.match(/^(\d+(?:\.\d+)?)\s*(s|m|h|d|w|mo|y)\s+ago$/i); if (m) return -m[1] * AGO[m[2].toLowerCase()];  // "9m ago": newer first when descending
    m = t.replace(/,/g, "").replace(/^[$€£τ]\s*/, "").match(/^([-+−]?\d+(?:\.\d+)?)\s*(%|[kmgt]i?b|b)?\b/i);
    if (m) return parseFloat(m[1].replace("−", "-")) * (m[2] && m[2] !== "%" ? UNIT[m[2].toLowerCase()] || 1 : 1);
    return t.toLowerCase();
  }
  const cmp = (a, b) => a == null ? 1 : b == null ? -1 : typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), undefined, { numeric: true });
  const rowsOf = t => $$(":scope > tbody > tr", t);
  const real = tr => !(tr.children.length === 1 && tr.firstElementChild?.colSpan > 1);  // not an empty-state row
  const heads = t => $$(":scope > thead > tr:last-child > th", t);
  function key(t) {
    if (t.dataset.plt) return t.dataset.plt;
    const v = t.closest(".view")?.id || "", all = $$("table.grid", t.closest(".view") || document);
    return `${v}:${t.id || t.querySelector("tbody")?.id || t.className.split(/\s+/).filter(c => !c.startsWith("plt-")).join(".")}:${all.indexOf(t)}`;
  }
  function enhance(t) {
    const hs = heads(t); if (!hs.length || hs.some(h => h.dataset.key)) return;  // sorts itself
    const k = key(t), st = saved(k), rows = rowsOf(t).filter(real);
    if (!t.dataset.plt) {
      t.dataset.plt = k;
      hs.forEach((h, i) => { if (h.textContent.trim()) { h.tabIndex = 0; h.dataset.pltCol = i; h.setAttribute("aria-sort", "none"); } });
      const go = h => h && t.classList.contains("plt-sortable") && sortBy(t, +h.dataset.pltCol);
      t.querySelector("thead").addEventListener("click", e => go(e.target.closest("th[data-plt-col]")));
      t.querySelector("thead").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { const h = e.target.closest("th[data-plt-col]"); if (h) { e.preventDefault(); go(h); } } });
    }
    // a filter and Columns above the table once it's worth it
    const wrap = t.closest(".tablewrap") || t;
    let bar = wrap.previousElementSibling?.classList.contains("plt-tbar") ? wrap.previousElementSibling : null;
    const want = !t.classList.contains("mini-table") && (rows.length >= MIN_ROWS || hs.length >= MIN_COLS || st.q || st.hide?.length);
    // the page already has a search for this table: only add Columns to its toolbar
    const own = !bar && [wrap.previousElementSibling, wrap.previousElementSibling?.previousElementSibling].find(x => x?.matches?.(".toolbar") && x.querySelector("input[type=search]"));
    if (want && own) {
      if (!own.querySelector("[data-plt-cols]")) {
        own.insertAdjacentHTML("beforeend", `<button type="button" class="btn sm" data-plt-cols>${icon("columns")}Columns</button>`);
        $("[data-plt-cols]", own).onclick = e => { e.stopPropagation(); columns(t, e.currentTarget); };
      }
    } else if (want && !bar) {
      bar = document.createElement("div"); bar.className = "plt-tbar";
      bar.innerHTML = `<div class="search"><span>${icon("search")}</span><input type="search" placeholder="Filter rows" aria-label="Filter this table" value="${esc(st.q || "")}"></div>
        <button type="button" class="btn sm" data-plt-cols>${icon("columns")}Columns</button><span class="result-count"></span>`;
      wrap.before(bar);
      $("input", bar).oninput = e => { saved(k, { ...saved(k), q: e.target.value }); apply(t); };
      $("[data-plt-cols]", bar).onclick = e => { e.stopPropagation(); columns(t, e.currentTarget); };
    }
    apply(t);
  }
  function sortBy(t, i) {
    const k = t.dataset.plt, st = saved(k);
    const dir = st.col === i ? (st.dir === 1 ? -1 : st.dir === -1 ? 0 : 1) : (typeof value(cellText(rowsOf(t).filter(real)[0]?.children[i])) === "number" ? -1 : 1);
    saved(k, { ...st, col: dir ? i : null, dir });
    apply(t);
  }
  function apply(t) {
    const k = t.dataset.plt; if (!k) return;
    const st = saved(k), all = rowsOf(t), rows = all.filter(real), hide = new Set(st.hide || []);
    // rows grouped under heading rows (one cell across the table) keep the module's order: filter and Columns only
    const grouped = all.some(r => !real(r) && !r.querySelector(".empty") && r.textContent.trim());
    t.classList.toggle("plt-sortable", !grouped);
    heads(t).forEach((h, i) => { if (h.dataset.pltCol != null) h.setAttribute("aria-sort", st.col === i && st.dir ? (st.dir > 0 ? "ascending" : "descending") : "none"); });
    // rows remember the module's order when they first show, so "no sort" can put it back
    let n = rows.reduce((m, r) => Math.max(m, +(r.dataset.pltI ?? -1)), -1);
    rows.forEach(r => { if (r.dataset.pltI == null) r.dataset.pltI = ++n; });
    // sort: move rows only when the order differs, so re-applying after a re-render settles at once
    const by = st.col != null && st.dir ? (a, b) => st.dir * cmp(value(cellText(a.children[st.col])), value(cellText(b.children[st.col]))) : (a, b) => a.dataset.pltI - b.dataset.pltI;
    const sorted = grouped ? rows : [...rows].sort(by);
    if (sorted.some((r, i) => r !== rows[i])) { const tb = t.tBodies[0]; sorted.forEach(r => tb.appendChild(r)); all.filter(r => !real(r)).forEach(r => tb.appendChild(r)); }
    // filter
    const q = (st.q || "").trim().toLowerCase(); let shown = 0;
    rows.forEach(r => { const ok = !q || r.textContent.toLowerCase().includes(q); if (r.hidden !== !ok) r.hidden = !ok; if (ok) shown++; });
    const bar = (t.closest(".tablewrap") || t).previousElementSibling;
    if (bar?.classList.contains("plt-tbar")) $(".result-count", bar).textContent = q ? `${shown} of ${rows.length} rows` : hide.size ? `${hide.size} column${hide.size > 1 ? "s" : ""} hidden` : "";
    // hidden columns (cells spanning several columns are left alone)
    [...t.rows].forEach(r => { if (r.cells.length === heads(t).length) [...r.cells].forEach((c, i) => { const h = hide.has(i); if (c.hidden !== h) c.hidden = h; }); });
  }
  function columns(t, btn) {
    $("#plt-colpop")?.remove();
    const k = t.dataset.plt, hide = new Set(saved(k).hide || []);
    const pop = document.createElement("div"); pop.id = "plt-colpop"; pop.className = "popover";
    pop.innerHTML = heads(t).map((h, i) => h.textContent.trim() ? `<label><input type="checkbox" data-c="${i}" ${hide.has(i) ? "" : "checked"}> ${esc(h.textContent.trim())}</label>` : "").join("");
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px"; pop.style.left = Math.max(16, Math.min(b.left, innerWidth - 260)) + "px";
    document.body.appendChild(pop);
    pop.onchange = e => { const i = +e.target.dataset.c; e.target.checked ? hide.delete(i) : hide.add(i); saved(k, { ...saved(k), hide: [...hide] }); apply(t); };
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
  }
  function scan() {
    if (!document.body.classList.contains("plt-zone")) return;
    const host = viewEl(view); if (!host || host.hidden) return;
    $$("table.grid", host).forEach(t => { if (!t.matches(SKIP) && !t.closest(SKIP)) enhance(t); });
  }

  function onView(v) { view = v; tabs(v); requestAnimationFrame(scan); }
  function init() {
    // the modules re-render their tables: look again once per frame at most, on the page that shows
    obs = new MutationObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(scan); });
    obs.observe($("main"), { childList: true, subtree: true });
  }
  return { init, onView };
})();
