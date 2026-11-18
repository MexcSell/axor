/* Sidebar layout (System → Sidebar layout; side-layout.css, prefix sbl-; API /api/sidebar-layout, side_layout.py).
   Three lists of sidebar items:
   - Advanced: the whole sidebar as index.html has it. Administrators in Advanced mode always see it in full.
   - Simple:   what administrators see in Simple mode, in this order.
   - User:     the one sidebar of every account that isn't an administrator, in this order. Those accounts have one mode, no
               Simple/Advanced switch (mission.js mode()), and none of the operator chrome: Progress, the sidebar's version and
               health, the status bar and the top bar's chain, price and unit (body.sbl-user, side-layout.css). A User list never
               saved falls back to the Simple list.
   A list that was never saved leaves that sidebar as it is (Simple mode then keeps its built-in CSS, mission.css).
   Applying a list moves nothing: the sections become `display: contents`, so every item turns into a direct flex item of
   #side, and each gets an `order` (or .sbl-out). Ids, routes, counts, access (`hidden`) and the other modules'
   observers keep working on the same tree. A list never grants access: an item hidden for an account stays hidden. */
const SideLayout = (() => {
  const DEFAULT_SIMPLE = ["nav-layers", "nav-alerts", "nav-approvals", "nav-mining", "nav-mos", "ctl-tree", "nav-help"];  // what mission.css showed in Simple mode
  const ADMIN_VIEWS = new Set(["infra", "admin", "docker", "devops", "system", "connectors", "cluster", "apps", "functions", "machines", "dns", "hq", "sidelayout"]);  // app.js: administrators only
  // items auth.js shows to users only while Agents → Models → Access → "Members can use agents" is on
  const AGENT_GATED = new Set(["tab-agents", "tab-studio", "nav-mining", "nav-teams", "nav-portfolio", "nav-company", "nav-workforce", "nav-infiagent", "nav-knowledge", "nav-market", "nav-mos"]);
  const gated = it => AGENT_GATED.has(it.k) || !!it.el.closest("#grp-tools");
  let membersAgents = null;  // that setting, read when the editor opens (/api/agents/hub)
  const HATCH = "nav-sidelayout", LAST = 99990;  // this page's own item, kept in reach for administrators (below the frame's 99999)
  const LISTS = { simple: ["Simple", "Administrators in Simple mode"], user: ["User", "Every account that isn't an administrator: their only sidebar, with no Simple/Advanced switch"] };
  let cat = null, byKey = new Map();
  let saved = { simple: null, user: null, ts: null, by: "" };
  let draft = null, touched = { simple: false, user: false }, preview = null, drag = null, root = null, wired = false;
  const side = () => $("#side");
  const simpleMode = () => document.body.dataset.axmode === "simple";

  // ---------- the catalog: every item the sidebar can show ----------
  function keyOf(el) {
    if (el.id) return el.id;
    if (el.dataset.view) return "v:" + el.dataset.view;
    if (el.dataset.axn) { try { return "a:" + Object.entries(JSON.parse(el.dataset.axn)).map(([a, b]) => a + "-" + b).join("-"); } catch { /* fall through */ } }
    return "";
  }
  const secName = sec => (sec?.querySelector(":scope > .side-group .plt-gl") || sec?.querySelector(":scope > .side-group"))?.textContent.trim() || "";
  function catalog() {
    if (cat) return cat;
    cat = [];
    $$("#side .side-sec").forEach(sec => {
      $$("button:not(.side-group), .ctl-tree", sec).forEach(el => {
        if (el.classList.contains("side-alias") || (el.tagName === "BUTTON" && el.closest(".ctl-tree"))) return;
        const k = keyOf(el); if (!k || byKey.has(k)) return;
        el.dataset.sbl = k;
        const it = { k, el, sec, sub: el.closest(".side-sub"), admin: ADMIN_VIEWS.has(el.dataset.view) };
        cat.push(it); byKey.set(k, it);
      });
    });
    return cat;
  }
  const label = it => it.el.classList.contains("ctl-tree") ? "Organization tree" : (it.el.querySelector(".lbl")?.textContent.trim() || it.el.title || it.k);
  // the item's own drawn icon (icons.js replaces the data-icon spans), so the editor shows what the sidebar shows
  const iconOf = it => it.el.classList.contains("ctl-tree") ? icon("sitemap") : (it.el.querySelector(":scope > svg.icon, :scope > span > svg.icon")?.outerHTML || icon(it.el.querySelector("[data-icon]")?.dataset.icon || "file"));
  const subName = it => it.sub?.querySelector(".side-subh")?.textContent.trim() || "";

  // the lists a never-saved sidebar starts from: today's sidebar, with its section names as headings
  function withHeadings(items) {
    const out = []; let last = null;
    items.forEach(it => { if (it.sec !== last) { last = it.sec; const h = secName(it.sec); if (h) out.push({ h }); } out.push({ k: it.k, on: true }); });
    return out;
  }
  // User's default is what users get with no User list: the Simple list (saved, else the built-in Simple sidebar)
  const defaults = (n, simple = saved.simple) => n === "user" && simple ? copy(simple) : withHeadings(catalog().filter(it => DEFAULT_SIMPLE.includes(it.k)));

  // ---------- apply a list to the sidebar ----------
  const member = () => { const me = typeof Auth !== "undefined" && Auth.me(); return !!me && me.role !== "admin"; };
  function active() {
    if (preview) return preview;
    const me = typeof Auth !== "undefined" && Auth.me();
    if (!me) return null;
    if (me.role !== "admin") return saved.user ?? saved.simple;  // users: one sidebar, whatever mode was stored
    return simpleMode() ? saved.simple : null;
  }
  let q = 0;
  function apply() {
    const s = side(); if (!s || !cat) return;
    $$(":scope > .sbl-h", s).forEach(h => h.remove());
    const list = active();
    s.classList.toggle("sbl-on", !!list);
    s.classList.toggle("sbl-preview", !!preview);
    document.body.classList.toggle("sbl-user", member() || (!!preview && preview === draft?.user));  // the user method: no operator chrome
    if (!list) { cat.forEach(it => { it.el.style.order = ""; it.el.classList.remove("sbl-out"); }); return; }
    const pos = new Map();
    list.forEach((e, i) => {
      if (e.h !== undefined) {
        const h = document.createElement("div");
        h.className = "sbl-h"; h.textContent = e.h; h.style.order = String(i + 1);
        s.append(h);
      } else if (e.on !== false && byKey.has(e.k)) pos.set(e.k, i + 1);
    });
    // administrators can always get back here: a list that leaves this page out still shows it, last
    if (Auth.me()?.role === "admin" && byKey.has(HATCH) && !pos.has(HATCH)) pos.set(HATCH, LAST);
    // …and Developer (dvp-*.js) stays the sidebar's last item for them, after it, unless the list places it itself
    if (Auth.me()?.role === "admin" && byKey.has("nav-developer") && !pos.has("nav-developer")) pos.set("nav-developer", LAST + 1);
    cat.forEach(it => { const p = pos.get(it.k); it.el.style.order = p ? String(p) : ""; it.el.classList.toggle("sbl-out", !p); });
    headings();
  }
  // a heading shows only while one of the items under it does (access can hide every one of them)
  function headings() {
    const s = side(); if (!s?.classList.contains("sbl-on")) return;
    const seen = el => !el.hidden && !el.classList.contains("sbl-out") && !el.closest(".side-sec[hidden], .side-sub[hidden]");
    const rows = [...$$(":scope > .sbl-h", s), ...cat.filter(it => it.el.style.order && +it.el.style.order < LAST).map(it => it.el)].sort((a, b) => +a.style.order - +b.style.order);
    let h = null, any = false;
    const close = () => { if (h && h.hidden === any) h.hidden = !any; };
    rows.forEach(el => { if (el.classList.contains("sbl-h")) { close(); h = el; any = false; } else if (seen(el)) any = true; });
    close();
  }

  async function load() {
    try { const d = await api("/api/sidebar-layout"); saved = { simple: d.simple ?? null, user: d.user ?? null, ts: d.ts, by: d.by || "" }; }
    catch { /* not signed in, or an older server: the normal sidebar */ }
    apply();
    if (!landed) { landed = true; land(); }
  }
  // a user whose saved session reopens a page their sidebar no longer has lands on the list's first item instead
  let landed = false;
  function land() {
    if (!member() || !side()?.classList.contains("sbl-on") || typeof S === "undefined" || !S.view) return;
    const here = cat.filter(it => it.el.dataset.view === S.view);
    if (!here.length || here.some(it => !it.el.classList.contains("sbl-out") && !it.el.hidden)) return;
    const first = cat.filter(it => it.el.tagName === "BUTTON" && !it.el.hidden && !it.el.classList.contains("sbl-out") && it.el.style.order)
      .sort((a, b) => +a.el.style.order - +b.el.style.order)[0];
    first?.el.click();
  }

  // app.js calls this once it knows who is signed in
  function init() {
    if (wired) return; wired = true;
    catalog();
    new MutationObserver(apply).observe(document.body, { attributes: true, attributeFilter: ["data-axmode"] });
    new MutationObserver(() => { cancelAnimationFrame(q); q = requestAnimationFrame(headings); })
      .observe(side(), { subtree: true, attributes: true, attributeFilter: ["hidden"] });
    const v = $("#view-sidelayout");
    if (v) new MutationObserver(() => v.hidden ? leave() : open()).observe(v, { attributes: true, attributeFilter: ["hidden"] });
    apply();  // the user method's chrome goes before the lists arrive
    if (Auth.me()) load();
  }

  // ---------- the editor ----------
  const copy = l => l.map(e => ({ ...e }));
  function start() {
    draft = { simple: copy(saved.simple || defaults("simple")), user: copy(saved.user || defaults("user")) };
    touched = { simple: false, user: false };
  }
  const dirty = () => touched.simple || touched.user;
  function open() {
    root = $("#sbl"); if (!root) return;
    catalog();
    if (!draft || !dirty()) start();
    render();
    load().then(() => { if (!dirty()) { start(); render(); } });
    api("/api/agents/hub").then(h => { const m = !!h.members_allowed; if (m !== membersAgents) { membersAgents = m; render(); } }).catch(() => {});
  }
  function leave() { if (preview) { preview = null; apply(); } }

  function render() {
    if (!root) return;
    const where = saved.ts ? `Saved ${new Date(saved.ts * 1000).toLocaleString()}${saved.by ? " by " + esc(saved.by) : ""}` : "Not saved yet: both sidebars are as built";
    root.innerHTML = `
      <div class="sbl-top">
        <div><h1 class="page">Sidebar layout</h1>
          <p class="lead">Choose which items the sidebar shows, and in what order. <b>Advanced</b> (left) is the whole sidebar: administrators in Advanced mode always see all of it.
            <b>Simple</b> is what administrators see in Simple mode. <b>User</b> is the only sidebar of every account that isn't an administrator: they have one mode, with no Simple/Advanced switch, and no Progress, status bar, version and health, chain, price or unit. With no User list saved, users get the Simple list.
            Drag items from Advanced into a list, drag to reorder, and use the eye to show or hide an entry. A list never grants access: a page an account can't open stays hidden. Sidebar layout itself always stays at the bottom of the sidebar for administrators.</p></div>
        <div class="sbl-acts">
          <span class="sbl-state ${dirty() ? "dirty" : ""}" aria-live="polite">${dirty() ? "Unsaved changes" : where}</span>
          <button type="button" class="btn" data-sbl-act="discard" ${dirty() ? "" : "disabled"}>Discard</button>
          <button type="button" class="btn primary" data-sbl-act="save" ${dirty() ? "" : "disabled"}>${icon("check")}Save</button>
        </div>
      </div>
      ${preview ? `<div class="sbl-banner" role="status">${icon("eye")}<span>The sidebar is showing the unsaved <b>${preview === draft.simple ? "Simple" : "User"}</b> list as a preview.</span><button type="button" class="btn" data-sbl-act="unpreview">End preview</button></div>` : ""}
      <div class="sbl-cols">
        <section class="card sbl-col sbl-adv" data-list="adv" aria-label="Advanced: every sidebar item">
          <header><h2>Advanced <small>${cat.length} items</small></h2><p class="muted">The whole sidebar. Drag an item into Simple or User, or use its buttons.</p></header>
          <div class="sbl-adv-list">${advanced()}</div>
        </section>
        ${Object.keys(LISTS).map(col).join("")}
      </div>`;
  }

  function advanced() {
    let out = "", sec = null, sub = null;
    catalog().forEach(it => {
      if (it.sec !== sec) { sec = it.sec; sub = null; out += `<p class="sbl-sec">${esc(secName(sec))}</p>`; }
      if (it.sub !== sub) { sub = it.sub; const n = subName(it); if (n) out += `<p class="sbl-sub">${esc(n)}</p>`; }
      const inS = draft.simple.some(e => e.k === it.k), inU = draft.user.some(e => e.k === it.k);
      out += `<div class="sbl-row sbl-item ${it.sub ? "sbl-nest" : ""}" draggable="true" data-src="adv" data-k="${esc(it.k)}">
        <span class="sbl-grip" aria-hidden="true">${icon("dots")}</span>${iconOf(it)}
        <span class="sbl-name">${esc(label(it))}${it.admin ? ' <span class="tag" title="Only administrators can open this page: adding it to User shows it to no one">Admins only</span>' : ""}</span>
        <span class="sbl-add">
          <button type="button" class="sbl-mini ${inS ? "on" : ""}" data-sbl-add="simple" data-k="${esc(it.k)}" ${inS ? "disabled" : ""} title="${inS ? "In the Simple list" : "Add to the Simple list"}" aria-label="${inS ? "In" : "Add to"} Simple: ${esc(label(it))}">${inS ? icon("check") : icon("plus")}Simple</button>
          <button type="button" class="sbl-mini ${inU ? "on" : ""}" data-sbl-add="user" data-k="${esc(it.k)}" ${inU ? "disabled" : ""} title="${inU ? "In the User list" : "Add to the User list"}" aria-label="${inU ? "In" : "Add to"} User: ${esc(label(it))}">${inU ? icon("check") : icon("plus")}User</button>
        </span></div>`;
    });
    return out;
  }

  function col(n) {
    const l = draft[n], [title, who] = LISTS[n];
    const items = l.filter(e => e.k !== undefined), shown = items.filter(e => e.on !== false).length;
    const state = !saved[n] && !touched[n] ? `<span class="tag" title="Not saved: this sidebar is as built until you save a list">Default</span>` : "";
    return `<section class="card sbl-col" data-list="${n}" aria-label="${title} list">
      <header><h2>${title} <small>${shown} shown${items.length > shown ? ` · ${items.length - shown} hidden` : ""}</small> ${state}</h2><p class="muted">${who}.</p>
        <div class="sbl-tools">
          <button type="button" class="btn" data-sbl-act="heading" data-n="${n}">${icon("plus")}Heading</button>
          <button type="button" class="btn" data-sbl-act="preview" data-n="${n}" aria-pressed="${preview === l}" title="Show this list in your sidebar now, without saving">${icon("eye")}${preview === l ? "Previewing" : "Preview"}</button>
          <button type="button" class="btn" data-sbl-act="reset" data-n="${n}" title="${n === "simple" ? "Back to the built-in Simple sidebar" : "Back to the Simple list: users get it while no User list is saved"}">${icon("reset")}Default</button>
        </div></header>
      <ol class="sbl-list" data-n="${n}">${l.map((e, i) => entry(n, e, i, l.length)).join("") || `<li class="sbl-empty">Nothing here: this sidebar would be empty. Drag items in from Advanced.</li>`}</ol>
    </section>`;
  }

  function entry(n, e, i, len) {
    const moves = `<button type="button" class="sbl-ib" data-sbl-mv="-1" ${i ? "" : "disabled"} title="Move up" aria-label="Move up">${icon("up")}</button>
      <button type="button" class="sbl-ib" data-sbl-mv="1" ${i < len - 1 ? "" : "disabled"} title="Move down" aria-label="Move down">${icon("down")}</button>
      <button type="button" class="sbl-ib" data-sbl-rm title="Remove from this list" aria-label="Remove">${icon("close")}</button>`;
    if (e.h !== undefined) return `<li class="sbl-row sbl-head" draggable="true" data-src="${n}" data-i="${i}">
      <span class="sbl-grip" aria-hidden="true">${icon("dots")}</span><input class="sbl-hin" value="${esc(e.h)}" maxlength="40" aria-label="Heading text" placeholder="Heading"><span class="sbl-ctl">${moves}</span></li>`;
    const it = byKey.get(e.k), on = e.on !== false;
    return `<li class="sbl-row ${on ? "" : "sbl-off"} ${it ? "" : "sbl-gone"}" draggable="true" data-src="${n}" data-i="${i}">
      <span class="sbl-grip" aria-hidden="true">${icon("dots")}</span>${it ? iconOf(it) : icon("alert")}
      <span class="sbl-name">${it ? esc(label(it)) : `Missing item <code>${esc(e.k)}</code>`}${it?.admin && n === "user" ? ' <span class="tag" title="Users can\'t open this page, so it never shows to them">Admins only</span>' : ""}${it && !it.admin && n === "user" && membersAgents === false && gated(it) ? ' <span class="tag" title="Users can\'t open this while Agents → Models → Access → Members can use agents is off, so it doesn\'t show to them">Needs member agents</span>' : ""}${on ? "" : ' <span class="sbl-hid">Hidden</span>'}</span>
      <span class="sbl-ctl"><button type="button" class="sbl-ib sbl-eye" data-sbl-eye aria-pressed="${on}" title="${on ? "Shown: click to hide" : "Hidden: click to show"}" aria-label="${on ? "Hide" : "Show"} ${it ? esc(label(it)) : ""}">${icon(on ? "eye" : "eyeoff")}</button>${moves}</span></li>`;
  }

  // ---------- changes ----------
  function change(n, fn) {
    fn(draft[n]); touched[n] = true;
    if (preview === draft[n]) apply();
    render();
  }
  function insert(n, e, at) {
    change(n, l => {
      const was = e.k !== undefined ? l.findIndex(x => x.k === e.k) : -1;
      if (was >= 0) { const [x] = l.splice(was, 1); if (at > was) at--; e = x; }
      l.splice(Math.max(0, Math.min(at, l.length)), 0, e);
    });
  }

  function onClick(ev) {
    const t = ev.target.closest("button"); if (!t || !root?.contains(t)) return;
    const li = t.closest("li[data-i]"), n = t.closest("[data-list]")?.dataset.list, i = li ? +li.dataset.i : -1;
    if (t.dataset.sblAdd) { const m = t.dataset.sblAdd; insert(m, { k: t.dataset.k, on: true }, draft[m].length); toast(`Added to ${LISTS[m][0]}`); return; }
    if (t.hasAttribute("data-sbl-eye")) return change(n, l => { l[i].on = l[i].on === false; });
    if (t.dataset.sblMv) {
      const j = i + +t.dataset.sblMv;
      change(n, l => { [l[i], l[j]] = [l[j], l[i]]; });
      root.querySelector(`[data-list="${n}"] li[data-i="${j}"] [data-sbl-mv="${t.dataset.sblMv}"]:not([disabled])`)?.focus();
      return;
    }
    if (t.hasAttribute("data-sbl-rm")) return change(n, l => { l.splice(i, 1); });
    const a = t.dataset.sblAct, m = t.dataset.n;
    if (a === "heading") { change(m, l => { l.push({ h: "New heading" }); }); const ins = $$(`[data-list="${m}"] .sbl-hin`, root); ins[ins.length - 1]?.select(); }
    else if (a === "reset") { const old = draft[m]; draft[m] = defaults(m); touched[m] = !!saved[m]; if (preview === old) preview = draft[m]; apply(); render(); }
    else if (a === "preview") { preview = preview === draft[m] ? null : draft[m]; apply(); render(); }
    else if (a === "unpreview") { preview = null; apply(); render(); }
    else if (a === "discard") { preview = null; start(); apply(); render(); }
    else if (a === "save") save(t);
  }

  async function save(b) {
    // a list you didn't change keeps what is saved; one that matches its default is stored as "not set" (null), so that
    // sidebar keeps its built-in form (folding sections and all) instead of a flat copy of it
    const body = {};
    for (const n of Object.keys(LISTS))  // simple first: User's default is the Simple list being saved
      body[n] = !touched[n] ? saved[n] : JSON.stringify(draft[n]) === JSON.stringify(defaults(n, body.simple ?? null)) ? null : draft[n];
    b.disabled = true;
    try {
      const d = await api("/api/sidebar-layout", { method: "PUT", body });
      saved = { simple: d.simple ?? null, user: d.user ?? null, ts: d.ts, by: d.by || "" };
      preview = null; start(); apply(); render();
      toast("Sidebar layout saved");
    } catch (e) { b.disabled = false; toast(e.message, { kind: "error" }); }
  }

  // heading text: kept as you type, drawn again when you leave the field
  function onInput(ev) {
    const t = ev.target; if (!t.classList?.contains("sbl-hin")) return;
    const n = t.closest("[data-list]").dataset.list, i = +t.closest("li").dataset.i;
    draft[n][i].h = t.value; touched[n] = true;
    if (preview === draft[n]) apply();
    const st = $(".sbl-state", root); if (st) { st.textContent = "Unsaved changes"; st.classList.add("dirty"); }
    $$('[data-sbl-act="save"], [data-sbl-act="discard"]', root).forEach(x => { x.disabled = false; });
  }
  function onChange(ev) {
    const t = ev.target; if (!t.classList?.contains("sbl-hin")) return;
    const n = t.closest("[data-list]").dataset.list, i = +t.closest("li").dataset.i;
    if (!t.value.trim()) change(n, l => { l.splice(i, 1); });  // an emptied heading goes
  }

  // ---------- drag and drop (every drag has a button twin above, for touch and keyboards) ----------
  let mark = null;
  function unmark() { mark?.remove(); mark = null; $$(".sbl-drop", root).forEach(x => x.classList.remove("sbl-drop")); }
  function slot(ol, y) {
    const rows = $$(":scope > li[data-i]", ol);
    for (const r of rows) { const b = r.getBoundingClientRect(); if (y < b.top + b.height / 2) return { at: +r.dataset.i, before: r }; }
    return { at: rows.length, before: null };
  }
  function onDragStart(ev) {
    const r = ev.target.closest?.(".sbl-row[draggable]"); if (!r || ev.target.closest("input")) return;
    drag = r.dataset.src === "adv" ? { src: "adv", k: r.dataset.k } : { src: r.dataset.src, i: +r.dataset.i };
    ev.dataTransfer.effectAllowed = "copyMove";
    try { ev.dataTransfer.setData("text/plain", r.textContent.trim()); } catch { /* some browsers refuse */ }
    requestAnimationFrame(() => r.classList.add("sbl-dragging"));
  }
  function onDragOver(ev) {
    if (!drag) return;
    const colEl = ev.target.closest?.("[data-list]"); if (!colEl) return;
    ev.preventDefault();
    unmark();
    if (colEl.dataset.list === "adv") { if (drag.src !== "adv") { colEl.classList.add("sbl-drop"); ev.dataTransfer.dropEffect = "move"; } return; }
    const ol = $("ol.sbl-list", colEl), s = slot(ol, ev.clientY);
    ev.dataTransfer.dropEffect = drag.src === colEl.dataset.list ? "move" : "copy";
    mark = document.createElement("li"); mark.className = "sbl-mark"; mark.setAttribute("aria-hidden", "true");
    ol.insertBefore(mark, s.before);
  }
  function onDrop(ev) {
    if (!drag) return;
    const colEl = ev.target.closest?.("[data-list]"); if (!colEl) return;
    ev.preventDefault();
    const n = colEl.dataset.list, d = drag;
    let at = 0;
    if (n !== "adv") { const ol = $("ol.sbl-list", colEl); mark?.remove(); mark = null; at = slot(ol, ev.clientY).at; }
    unmark(); drag = null;
    if (n === "adv") { if (d.src !== "adv") change(d.src, l => { l.splice(d.i, 1); }); return; }  // dropped back on Advanced: out of that list
    if (d.src === "adv") return insert(n, { k: d.k, on: true }, at);
    const e = draft[d.src][d.i]; if (!e) return;
    if (d.src === n) return change(n, l => { const [x] = l.splice(d.i, 1); l.splice(at > d.i ? at - 1 : at, 0, x); });
    insert(n, { ...e }, at);  // from the other list: a copy
  }
  function onDragEnd() { unmark(); drag = null; $$(".sbl-dragging", root).forEach(x => x.classList.remove("sbl-dragging")); }

  function wire() {
    const r = $("#sbl"); if (!r) return;
    r.addEventListener("click", onClick);
    r.addEventListener("input", onInput);
    r.addEventListener("change", onChange);
    r.addEventListener("dragstart", onDragStart);
    r.addEventListener("dragover", onDragOver);
    r.addEventListener("drop", onDrop);
    r.addEventListener("dragend", onDragEnd);
    r.addEventListener("dragleave", e => { if (!r.contains(e.relatedTarget)) unmark(); });
    // Firefox won't let you click or select text in a field inside a draggable row: the row stops dragging while you type
    r.addEventListener("focusin", e => { if (e.target.classList?.contains("sbl-hin")) e.target.closest("li").draggable = false; });
    r.addEventListener("focusout", e => { if (e.target.classList?.contains("sbl-hin")) { const li = e.target.closest("li"); if (li) li.draggable = true; } });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire); else wire();

  return { init, apply, open };
})();
