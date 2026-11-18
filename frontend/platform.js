/* AXoR platform shell (platform.css): the grouped sidebar that folds, where-you-are in the top bar, the command palette (Ctrl/⌘ K)
   and "g then a key" shortcuts. Every page keeps its own id and route; this only finds and opens them. */
const Platform = (() => {
  // Pages outside the agent systems get the platform component look (body.plt-zone)
  const AGENT_VIEWS = new Set(["mining", "teams", "portfolio", "company", "workforce", "infiagent", "agents", "hq", "studio", "knowledge", "myknowledge"]);
  const KEYS = { o: "command", v: "approvals", i: "intel", z: "org", j: "projects", k: "missions", l: "evaluation", q: "home", x: "settings", d: "dashboard", n: "notifications", e: "explore", r: "recommend", t: "tech", c: "caution", s: "scam", w: "workspace", f: "drive",
    b: "whiteboard", m: "mining", y: "system", p: "profile", a: "admin", h: "help" };
  let pal = null, sel = 0, items = [], chord = 0, recalc = 0, stat = null, statAt = 0, statReq = null;

  const typing = () => { const a = document.activeElement; return a && (/INPUT|SELECT|TEXTAREA/.test(a.tagName) || a.isContentEditable); };
  const button = v => $(`nav.side [data-view="${v}"]`);
  const visible = b => b && !b.hidden && !b.closest(".side-sec")?.hidden;
  const label = b => (b.querySelector(".lbl")?.textContent || b.title || "").trim();
  const group = b => b.closest(".side-sec")?.querySelector(".plt-gl")?.textContent || "";
  const sub = b => b.closest(".side-sub")?.querySelector(".side-subh")?.textContent || "";  // Platform → Developer → Docker

  // ---------- sidebar sections ----------
  function sections() {
    const closed = new Set(store.get("plt.closed", ["agents", "knowledge", "intel", "workspace", "system"]));  // the Mission Control sidebar's default: the working sections open
    $$("nav.side .side-sec").forEach(sec => {
      const h = sec.querySelector(".side-group");
      h.innerHTML = `<span class="plt-gl">${esc(h.textContent.trim())}</span><span class="plt-n"></span>${icon("chev", "plt-chev")}`;
      h.type = "button";
      const set = shut => { sec.classList.toggle("closed", shut); h.setAttribute("aria-expanded", !shut); };
      set(closed.has(sec.dataset.sec));
      h.onclick = () => {
        if ($("#side").classList.contains("collapsed") && innerWidth > 900) return;  // icon-only: the headers are just rules
        set(!sec.classList.contains("closed"));
        store.set("plt.closed", $$("nav.side .side-sec.closed").map(s => s.dataset.sec));
      };
    });
    // a section shows while any of its pages may be opened; a folded one sums its pages' alert counts on its header
    new MutationObserver(() => { cancelAnimationFrame(recalc); recalc = requestAnimationFrame(refresh); })
      .observe($("#side"), { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["hidden"] });
    refresh();
  }
  function refresh() {
    $$("nav.side .side-sec").forEach(sec => {
      const pages = $$("button:not(.side-group)", sec);
      const hide = pages.every(b => b.hidden);
      if (sec.hidden !== hide) sec.hidden = hide;
      $$(".side-sub", sec).forEach(s => { const h = $$("button", s).every(b => b.hidden); if (s.hidden !== h) s.hidden = h; });
      const n = $$(".count.alert", sec).reduce((t, c) => t + (parseInt(c.textContent, 10) || 0), 0), pn = sec.querySelector(".plt-n");
      if (pn && pn.textContent !== (n ? String(n) : "")) pn.textContent = n ? String(n) : "";
    });
  }

  // ---------- which services are set up (platform_status.py), shared by the Dashboard and the page tabs ----------
  function status(fresh) {
    if (!Auth.me()) return Promise.resolve(null);
    if (!fresh && stat && Date.now() - statAt < 60000) return Promise.resolve(stat);
    return statReq ||= api("/api/platform-status").then(r => { stat = r; statAt = Date.now(); return r; }).catch(() => stat).finally(() => { statReq = null; });
  }

  // ---------- top bar ----------
  function chrome() {
    const crumb = document.createElement("div");
    crumb.className = "plt-crumb"; crumb.id = "plt-crumb"; crumb.setAttribute("aria-live", "polite");
    const s = document.createElement("button");
    s.type = "button"; s.className = "plt-search"; s.id = "plt-search"; s.title = "Search pages and subnets (Ctrl K)";
    s.setAttribute("aria-label", "Search pages and subnets"); s.setAttribute("aria-haspopup", "dialog");
    s.innerHTML = `${icon("search")}<span>Search or jump to…</span><kbd>${/Mac|iP/.test(navigator.platform) ? "⌘" : "Ctrl"} K</kbd>`;
    s.onclick = () => open();
    $(".brand").after(crumb);
    $(".top-right").prepend(s);
    // phones have no room in the top bar: the same search from the slide-out sidebar
    const side = document.createElement("button");
    side.type = "button"; side.id = "plt-side-search"; side.title = "Search pages and subnets";
    side.innerHTML = `${icon("search")}<span class="lbl">Search pages and subnets</span>`;
    side.onclick = () => { sideOpen(false); open(); };
    $("nav.side").prepend(side);
  }
  function onView(v) {
    document.body.classList.toggle("plt-zone", !AGENT_VIEWS.has(v));
    const b = button(v), c = $("#plt-crumb");
    if (!c) return;
    const g = b ? [group(b), sub(b)].filter(Boolean) : [], name = b ? label(b) : ({ admin: "Users & permissions" }[v] || "");
    c.innerHTML = name ? `${g.map(x => `<span>${esc(x)}</span>${icon("chev")}`).join("")}<b>${esc(name)}</b>` : "";
    if (v === "dashboard") PlatformDash.open();
    Discover.onView(v);  // the compare tray shows on the subnet pages only
    PlatformTables.onView(v);  // the group's page tabs, and sortable tables on the platform pages
  }

  // ---------- extra links: audit log, appearance ----------
  function links() {
    const admin = Auth.me()?.role === "admin";
    $("#nav-admin").hidden = $("#nav-audit").hidden = !admin;
    $("#nav-audit").onclick = audit;
    $("#nav-appearance").onclick = appearance;
  }
  function audit() {
    setView("admin");
    const go = () => $$("#view-admin h2.section-title").find(h => /audit/i.test(h.textContent))?.scrollIntoView({ block: "start", behavior: "smooth" });
    go(); setTimeout(go, 400);
  }
  function appearance() {
    sideOpen(false);
    setTimeout(() => $("#theme").click(), 0);  // the theme panel, under its top-bar button
  }

  // ---------- command palette ----------
  function entries(q) {
    q = q.trim().toLowerCase();
    const hit = (...t) => !q || t.some(x => String(x || "").toLowerCase().includes(q));
    const out = [];
    if (!q) Shell.recent().map(button).filter(visible).forEach(b => out.push({ sec: "Recent", ico: b.querySelector("svg")?.outerHTML || icon("clock"), name: label(b), hint: group(b), run: () => setView(b.dataset.view) }));
    $$("nav.side button[data-view]").filter(visible).forEach(b => {
      const v = b.dataset.view, key = Object.keys(KEYS).find(k => KEYS[k] === v);
      if (hit(label(b), group(b), sub(b), b.title, v)) out.push({ sec: "Pages", ico: b.querySelector("svg")?.outerHTML || icon("grid"), name: label(b), hint: key ? `g ${key}` : sub(b) || group(b), run: () => setView(v) });
    });
    Shell.entries().forEach(x => { if (hit(x.name, x.group, x.title)) out.push({ sec: "Pages", ico: x.ico, name: x.name, hint: x.group, run: x.run }); });  // Performance lab, Experiments…
    if (visible($("#nav-audit")) && hit("audit log", "administration")) out.push({ sec: "Pages", ico: icon("clock"), name: "Audit log", hint: "Administration", run: audit });
    const acts = [
      ["Appearance: theme and accent color", "palette", appearance],
      [`Switch to ${Theme.isDark() ? "light" : "dark"} mode`, Theme.isDark() ? "sun" : "moon", () => { Settings.save({ theme: Theme.isDark() ? "light" : "dark" }); Theme.apply(); document.dispatchEvent(new Event("themechange")); }],
      [$("#side").classList.contains("collapsed") ? "Expand the sidebar" : "Collapse the sidebar to icons", "sidebar", () => $("#side-collapse").click(), "["],
    ];
    if (innerWidth > 900) acts.forEach(([name, ic, run, hint]) => { if (hit(name, "settings")) out.push({ sec: "Actions", ico: icon(ic), name, hint: hint || "", run }); });
    else acts.slice(0, 2).forEach(([name, ic, run]) => { if (hit(name, "settings")) out.push({ sec: "Actions", ico: icon(ic), name, hint: "", run }); });
    if (q && S.data?.subnets?.length) {
      const sn = q.replace(/^sn\s*/, "");
      S.data.subnets.filter(r => String(r.netuid) === sn || (r.name || "").toLowerCase().includes(q) || (r.field || "").toLowerCase().includes(q))
        .slice(0, 8).forEach(r => out.push({ sec: "Subnets", ico: icon("layers"), name: `SN${r.netuid} ${r.name || ""}`, hint: r.field || "", run: () => openDrawer(r.netuid) }));
    }
    return out;
  }
  function render() {
    items = entries($("#plt-q").value);
    sel = Math.min(sel, Math.max(0, items.length - 1));
    let last = "";
    $("#plt-list").innerHTML = items.map((it, i) => {
      const head = it.sec !== last ? `<h5>${esc(it.sec)}</h5>` : ""; last = it.sec;
      return `${head}<button type="button" class="plt-item" role="option" id="plt-o${i}" data-i="${i}" aria-selected="${i === sel}">${it.ico}<b>${esc(it.name)}</b><small>${esc(it.hint)}</small></button>`;
    }).join("") || `<div class="plt-none">Nothing matches. Try a page name, a subnet name or its number.</div>`;
    $("#plt-q").setAttribute("aria-activedescendant", items.length ? "plt-o" + sel : "");
    $(`#plt-o${sel}`)?.scrollIntoView({ block: "nearest" });
  }
  function build() {
    pal = document.createElement("div");
    pal.className = "plt-pal"; pal.hidden = true;
    pal.innerHTML = `<div class="plt-box" role="dialog" aria-modal="true" aria-label="Search pages and subnets">
      <div class="plt-in">${icon("search")}<input id="plt-q" type="text" placeholder="Search pages, actions and subnets…" autocomplete="off" spellcheck="false" role="combobox" aria-expanded="true" aria-controls="plt-list"><kbd>Esc</kbd></div>
      <div class="plt-list" id="plt-list" role="listbox"></div>
      <div class="plt-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span><span><kbd>g</kbd> then a letter jumps straight to a page</span><span><kbd>/</kbd> search subnets</span></div></div>`;
    document.body.appendChild(pal);
    pal.addEventListener("mousedown", e => { if (e.target === pal) close(); });
    pal.addEventListener("click", e => { const b = e.target.closest(".plt-item"); if (b) pick(+b.dataset.i); });
    pal.addEventListener("mousemove", e => { const b = e.target.closest(".plt-item"); if (b && +b.dataset.i !== sel) { sel = +b.dataset.i; $$(".plt-item", pal).forEach(x => x.setAttribute("aria-selected", +x.dataset.i === sel)); } });
    const q = $("#plt-q", pal);
    q.addEventListener("input", () => { sel = 0; render(); });
    q.addEventListener("keydown", e => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % Math.max(1, items.length); render(); }
      else if (e.key === "Enter") { e.preventDefault(); pick(sel); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === "Tab") e.preventDefault();  // focus stays in the dialog
    });
  }
  let back = null;
  function open() {
    if (!pal) build();
    back = document.activeElement;
    pal.hidden = false; $("#plt-q").value = ""; sel = 0; render(); $("#plt-q").focus();
    $("#plt-search")?.setAttribute("aria-expanded", "true");
  }
  function close() {
    if (!pal || pal.hidden) return;
    pal.hidden = true; $("#plt-search")?.setAttribute("aria-expanded", "false");
    if (back?.isConnected) back.focus();
  }
  function pick(i) { const it = items[i]; if (!it) return; close(); it.run(); }

  function keys(e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") { e.preventDefault(); return pal && !pal.hidden ? close() : open(); }
    if (e.ctrlKey || e.metaKey || e.altKey || typing() || (pal && !pal.hidden) || document.querySelector("dialog[open]")) return;
    if (e.defaultPrevented || S.view === "whiteboard") { chord = 0; return; }  // a page's own keys win: the whiteboard's tools, [ and ]
    if (chord && Date.now() - chord < 1200) {
      chord = 0;
      const v = KEYS[e.key.toLowerCase()], b = v && button(v);
      if (b && visible(b)) { e.preventDefault(); setView(v); }
      return;
    }
    if (e.key === "g") chord = Date.now();
    else if (e.key === "[" && innerWidth > 900) $("#side-collapse").click();
  }

  function init() {
    if ($("#plt-search")) return;
    sections(); chrome(); links(); Discover.init(); PlatformTables.init();
    document.addEventListener("keydown", keys);
    onView(S.view || "explore");
  }
  return { init, onView, open, close, audit, status, statusNow: () => stat };
})();
