/* Page guide: a tour of each page and suggested values in its fields (the content is guide-pages.js).
   The Guide button in the top bar starts the tour of the page you're on and holds the switches. The first time you open
   a page, a card offers its tour, once. A tour spotlights what the page shows right now: the page's own steps whose
   element is on screen, then its tabs, main buttons, search and a field with suggestions, then Assist. Focusing a field
   shows suggested values under it (GuideFields, else an "e.g." in its placeholder) and what you entered there before;
   a click (or Alt+Down, then Enter) fills the field, it never submits. Everything stays in this browser, per account,
   and nothing typed in a secret, address, amount or long-text field is kept. */
const Guide = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const pref = (k, v) => {
    const key = `guide.${Auth.me()?.id ?? "anon"}.${k}`;
    try { if (v === undefined) return JSON.parse(localStorage.getItem(key)); localStorage.setItem(key, JSON.stringify(v)); } catch { return null; }
  };
  const on = k => pref(k) !== false;  // "auto" (offer tours) and "hints" (suggest values) start on
  const MAX = 9;  // steps in a tour, the intro and the end included
  // fields whose values are never kept or guessed at
  const SECRET = /pass|secret|token|api.?key|\bkey\b|mnemonic|seed|otp|code|coldkey|hotkey|ss58|address|\bdest\b|amount|card|cvc|iban|recovery/i;
  const SECRETISH = v => /^(sk-|ghp_|gho_|github_pat_|xox[abp]-|nfp_|AKIA)/.test(v) || /^5[1-9A-HJ-NP-Za-km-z]{46,47}$/.test(v) || /^[A-Za-z0-9+/_=-]{32,}$/.test(v);
  let view = "explore", tour = null, offerT = null, offerEl = null, menuEl = null, hint = null, filling = false;

  const title = v => $(`nav.side [data-view="${v}"]`)?.title || ({ admin: "User administration" }[v] || v);
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const visible = el => {
    if (!el?.isConnected) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };
  // a button's or tab's words, without its counts and icons
  const words = b => { const c = b.cloneNode(true); $$(".count, .hq-n, .badge, .icon, svg", c).forEach(x => x.remove()); return c.textContent.trim().replace(/\s+/g, " "); };
  const seen = () => pref("seen") || {};
  const markSeen = v => pref("seen", { ...seen(), [v]: Date.now() });

  // ---------- the Guide button and its menu ----------
  function init() {
    if ($("#guide-btn")) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "iconbtn"; b.id = "guide-btn"; b.title = "Page guide"; b.setAttribute("aria-label", "Page guide");
    b.setAttribute("aria-haspopup", "menu"); b.setAttribute("aria-expanded", "false");
    b.innerHTML = icon("map");
    b.onclick = () => menu();
    const top = $(".top-right");
    top.insertBefore(b, $("#assist-btn") || $("#bell") || null);
    // phones have no room in the top bar: the same menu from the slide-out sidebar
    const side = document.createElement("button");
    side.type = "button"; side.id = "guide-side"; side.title = "Page guide";
    side.innerHTML = `${icon("map")}<span class="lbl">Page guide</span>`;
    side.onclick = () => { sideOpen(false); menu(true); };
    $("nav.side").insertBefore(side, $("nav.side .side-foot"));
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onBlur);
    document.addEventListener("input", e => { if (hint && e.target === hint.el && !filling && !/range|date|time/.test(e.target.type)) hideHint(); });
    document.addEventListener("change", remember, true);
    document.addEventListener("keydown", onKey, true);
    addEventListener("resize", () => { placeHint(); place(); });
    addEventListener("scroll", () => { placeHint(); place(); }, true);
    onView(S.view || "explore");  // the page shown before any setView (signed out: the Explorer)
  }
  function menu(sheet = false) {  // sheet: from the phone sidebar, docked at the bottom of the screen
    if (menuEl) return closeMenu();
    const doc = GuidePages[view]?.doc, kept = Object.keys(pref("recent") || {}).length;
    const m = menuEl = document.createElement("div");
    m.className = "gd-menu"; m.setAttribute("role", "menu"); m.setAttribute("aria-label", "Page guide");
    m.innerHTML = `<button type="button" role="menuitem" data-gd="tour">${icon("map")}<span>Tour this page<small>${esc(title(view))}</small></span></button>
      ${doc != null ? `<button type="button" role="menuitem" data-gd="doc">${icon("book")}<span>Read its guide<small>Help &amp; docs</small></span></button>` : ""}
      <hr>
      <label class="gd-sw"><input type="checkbox" role="menuitemcheckbox" data-gd="hints" ${on("hints") ? "checked" : ""}><span>Suggest values in fields<small>Shown under a field when you click into it</small></span></label>
      <label class="gd-sw"><input type="checkbox" role="menuitemcheckbox" data-gd="auto" ${on("auto") ? "checked" : ""}><span>Offer a tour on new pages<small>Once per page</small></span></label>
      <hr>
      <button type="button" role="menuitem" data-gd="reset">${icon("reset")}<span>Offer every tour again</span></button>
      ${kept ? `<button type="button" role="menuitem" data-gd="forget">${icon("trash")}<span>Forget values I entered<small>${kept} field${kept === 1 ? "" : "s"} remembered in this browser</small></span></button>` : ""}`;
    document.body.append(m);
    const r = $("#guide-btn").getBoundingClientRect();
    if (sheet || !r.width) m.classList.add("sheet");
    else {
      m.style.top = `${r.bottom + 8}px`;
      m.style.left = `${Math.max(16, Math.min(r.right - m.offsetWidth, innerWidth - m.offsetWidth - 16))}px`;
    }
    $("#guide-btn").setAttribute("aria-expanded", "true");
    m.addEventListener("click", e => {
      const a = e.target.closest("button[data-gd]")?.dataset.gd; if (!a) return;
      closeMenu();
      if (a === "tour") start();
      else if (a === "doc") openDoc(view);
      else if (a === "reset") { pref("seen", {}); toast("Each page offers its tour again the next time you open it."); }
      else if (a === "forget") { pref("recent", {}); toast("Forgot the values you entered."); }
    });
    m.addEventListener("change", e => {
      const k = e.target.dataset.gd; if (!k) return;
      pref(k, e.target.checked);
      if (k === "hints" && !e.target.checked) hideHint();
    });
    m.querySelector("button").focus();
    setTimeout(() => document.addEventListener("pointerdown", outside), 0);
  }
  function outside(e) { if (menuEl && !menuEl.contains(e.target) && !e.target.closest("#guide-btn, #guide-side")) closeMenu(); }
  function closeMenu() {
    menuEl?.remove(); menuEl = null;
    document.removeEventListener("pointerdown", outside);
    $("#guide-btn")?.setAttribute("aria-expanded", "false");
  }
  function openDoc(v) { const d = GuidePages[v]?.doc; Help.route(d ? "help/" + d : "help"); setView("help"); }

  // ---------- following the page ----------
  function onView(v) {
    const was = view; view = v;
    if (tour && tour.v !== v) end();
    if (was !== v) hideHint();
    closeMenu(); clearOffer();
    if (!on("auto") || !GuidePages[v] || seen()[v]) return;
    offerT = setTimeout(() => offer(v), 1200);  // after the page has drawn itself
  }
  function offer(v) {
    if (S.view !== v || tour || $("#app")?.hidden || $("dialog[open]")) return;
    const steps = build(v); if (steps.length < 3) return;  // nothing but the intro and the end: not worth a card
    const first = !Object.keys(seen()).length;
    markSeen(v);
    const o = offerEl = document.createElement("div");
    o.className = "gd-offer"; o.setAttribute("role", "dialog"); o.setAttribute("aria-label", "Page tour");
    o.innerHTML = `<span class="gd-ico">${icon("map")}</span>
      <div><b>${first ? "Welcome to AXoR" : `New to ${esc(title(v))}?`}</b>
        <p>${first ? `Every page has a short tour. Take the one for ${esc(title(v))}: ${steps.length} stops.` : `Take a quick tour: ${steps.length} stops.`}</p>
        <div class="gd-acts"><button type="button" class="btn sm primary" data-gd="go">Show me around</button><button type="button" class="btn sm" data-gd="later">Not now</button>
          <button type="button" class="gd-link" data-gd="never">Don't offer tours</button></div></div>
      <button type="button" class="gd-x" data-gd="later" aria-label="Close">${icon("close")}</button>`;
    document.body.append(o);
    requestAnimationFrame(() => o.classList.add("show"));
    o.addEventListener("click", e => {
      const a = e.target.closest("[data-gd]")?.dataset.gd; if (!a) return;
      clearOffer();
      if (a === "go") start(v);
      if (a === "never") { pref("auto", false); toast("Tours won't be offered. The Guide button in the top bar still has every page's tour."); }
    });
  }
  function clearOffer() { clearTimeout(offerT); offerEl?.remove(); offerEl = null; }

  // ---------- building a tour from what the page shows ----------
  function build(v) {
    const P = GuidePages[v] || {}, R = document.getElementById("view-" + v);
    if (!R) return [];
    const steps = [], used = [], labels = new Set();
    const free = el => !used.some(u => u === el || u.contains(el) || el.contains(u));
    const add = (el, t, body, extra) => {
      if (!el || !visible(el) || !free(el) || steps.length >= MAX - 1) return false;
      used.push(el); steps.push({ el, title: t, body, ...extra }); return true;
    };
    const tips = P.tips?.length ? `<ul>${P.tips.map(t => `<li>${t}</li>`).join("")}</ul>` : "";
    steps.push({ title: title(v), body: `<p>${P.intro || `A quick look at what's on ${esc(title(v))}.`}</p>${tips}` });
    for (const s of P.steps || []) {
      let el = $(s.sel, R);
      if (el && s.up) el = el.closest(s.up) || el;
      add(el, s.title, `<p>${s.body}</p>`);
    }
    // tabs: each one with what it's for
    for (const t of $$("[role=tablist], nav.src-tabs, .hub-tabs, .seg[class*=tabs]", R).filter(visible).slice(0, 2)) {
      const names = [...new Set($$("button, [role=tab]", t).map(words).filter(Boolean))];
      if (names.length < 2) continue;
      const known = names.filter(n => P.tabs?.[n]);
      const body = (P.tabs?._ ? `<p>${P.tabs._}</p>` : "") + (known.length
        ? `<ul>${names.map(n => `<li><b>${esc(n)}</b>${P.tabs[n] ? `: ${P.tabs[n]}` : ""}</li>`).join("")}</ul>`
        : P.tabs?._ ? "" : `<p>Switch between ${names.map(n => `<b>${esc(n)}</b>`).join(", ")}.</p>`);
      add(t, P.tabs?._ ? "Switch the view" : "Sections", body);
    }
    // the main buttons: an empty page's call to action reads as "start here", with the page's own words
    let n = 0;
    for (const b of $$(".btn.primary, button.primary", R).filter(visible)) {
      if (n >= 2 || b.type === "submit" || b.closest("form")) continue;
      const l = words(b) || b.getAttribute("aria-label") || b.title;
      if (!l || labels.has(l)) continue;
      labels.add(l);
      const box = b.closest(".empty, [class*=empty], [class*=onboard], [class*=welcome]");
      const said = box && $("p", box)?.textContent.trim().replace(/\s+/g, " ");
      const what = P.buttons?.[l] || (said ? esc(said.length > 220 ? said.slice(0, 217) + "…" : said) : "");
      if (add(b, box ? "Start here" : l, `${what ? `<p>${what}</p>` : ""}<p>Click <b>${esc(l)}</b>${box ? " to begin" : ""}.</p>`)) n++;
    }
    for (const s of $$("input[type=search]", R).filter(visible).slice(0, 1))
      add(s.closest(".search") || s, "Search", `<p>${esc((s.placeholder || "Search this page").replace(/[….\s]+$/, ""))}.</p>`);
    // a field with suggestions, filled from the tour itself
    if (on("hints")) {
      for (const f of $$("input, select, textarea", R).filter(x => visible(x) && fillable(x) && x.type !== "search")) {
        const s = suggest(f); if (!s?.values.length) continue;
        const name = fieldName(f), fill = { el: f, s };
        const host = steps.find(st => st.el && (st.el === f || st.el.contains(f)));
        const say = `<p>AXoR suggests values for fields like <b>${esc(name)}</b>. Click into any field to see its suggestions; a click fills it in, nothing is sent until you save.</p>`;
        if (host) { host.fill = fill; host.body += say; }
        else add(f.closest(".field, label, .in") || f, "Suggested values", say, { fill });
        break;
      }
    }
    const a = $("#assist-btn");
    if (a && visible(a)) add(a, "Ask Assist", `<p>Questions about ${esc(title(v))}? Assist answers beside the page and reads live data.</p>`);
    const where = visible($("#guide-btn")) ? "the Guide button" : "<b>Page guide</b> in the menu";
    steps.push({ el: $("#guide-btn"), title: "You're set", end: true,
                 body: `<p>Open this tour again from ${where}, and switch suggestions or tour offers off there.</p>${P.doc != null && v !== "help" ? `<p><button type="button" class="gd-link" data-gd="doc">Read the ${esc(title(v))} guide in Help &amp; docs</button></p>` : ""}` });
    return steps;
  }

  // ---------- running a tour ----------
  function start(v = view) {
    end(); clearOffer(); closeMenu(); hideHint();
    const steps = build(v); if (!steps.length) return;
    markSeen(v);
    const layer = document.createElement("div"), pop = document.createElement("div");
    layer.className = "gd-layer"; layer.innerHTML = `<div class="gd-dim"></div><div class="gd-spot"></div>`;
    pop.className = "gd-pop"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-labelledby", "gd-title");
    document.body.append(layer, pop);
    tour = { v, steps, i: 0, layer, pop, back: document.activeElement };
    pop.addEventListener("click", e => {
      const ch = e.target.closest("[data-v]");
      if (ch) { const f = tour.steps[tour.i].fill; fill(f.el, ch.dataset.v); $$("[data-v]", pop).forEach(c => c.setAttribute("aria-pressed", c === ch)); return; }
      const a = e.target.closest("[data-gd]")?.dataset.gd;
      if (a === "next") tour.i < tour.steps.length - 1 ? show(tour.i + 1) : end();
      else if (a === "prev") show(tour.i - 1);
      else if (a === "end") end();
      else if (a === "doc") { const tv = tour.v; end(); openDoc(tv); }
    });
    show(0);
  }
  function show(i) {
    const t = tour, s = t.steps[i], last = i === t.steps.length - 1;
    t.i = i;
    const cur = s.fill ? String(s.fill.el.value) : null;
    t.pop.innerHTML = `<div class="gd-head"><span class="gd-n">${i + 1} of ${t.steps.length}</span><button type="button" class="gd-x" data-gd="end" aria-label="End the tour">${icon("close")}</button></div>
      <h3 id="gd-title">${esc(s.title)}</h3><div class="gd-body">${s.body}</div>
      ${s.fill ? `<div class="gd-chips" aria-label="Suggested values for ${esc(fieldName(s.fill.el))}">${s.fill.s.values.map(x => `<button type="button" class="chip" data-v="${esc(x.v)}" aria-pressed="${x.v === cur}">${esc(x.label)}</button>`).join("")}</div>
        ${s.fill.s.why ? `<p class="gd-why">${esc(s.fill.s.why)}</p>` : ""}` : ""}
      <div class="gd-foot"><span class="gd-dots" aria-hidden="true">${t.steps.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("")}</span>
        ${i ? `<button type="button" class="btn sm" data-gd="prev">Back</button>` : `<button type="button" class="btn sm" data-gd="end">Skip</button>`}
        <button type="button" class="btn sm primary" data-gd="next">${last ? "Done" : "Next"}</button></div>`;
    if (s.el && visible(s.el)) {
      const r = s.el.getBoundingClientRect();
      if (r.top < 64 || r.bottom > innerHeight - 24) s.el.scrollIntoView({ block: r.height > innerHeight * .6 ? "start" : "center", behavior: reduced() ? "auto" : "smooth" });
    }
    place();
    setTimeout(place, reduced() ? 0 : 380);  // again once a smooth scroll has landed
    t.pop.querySelector("[data-gd=next]").focus({ preventScroll: true });
  }
  function place() {
    if (!tour) return;
    const s = tour.steps[tour.i], [dim, spot] = tour.layer.children, pop = tour.pop, G = 16;
    const lit = s.el && visible(s.el) ? s.el.getBoundingClientRect() : null;
    spot.classList.toggle("none", !lit);
    pop.classList.toggle("center", !lit);
    if (!lit) { dim.style.clipPath = ""; pop.style.left = `${(innerWidth - pop.offsetWidth) / 2}px`; pop.style.top = `${Math.max(G, (innerHeight - pop.offsetHeight) / 2)}px`; return; }
    const P = 6, top = Math.max(lit.top - P, 2), left = Math.max(lit.left - P, 2);
    const sw = Math.min(lit.right + P, innerWidth - 2) - left, sh = Math.min(lit.bottom + P, innerHeight - 2) - top, r = Math.min(10, sw / 2, sh / 2);
    Object.assign(spot.style, { top: `${top}px`, left: `${left}px`, width: `${sw}px`, height: `${sh}px` });
    // the dim with a rounded hole over the step's element (a clip path: huge box-shadows don't paint everywhere)
    dim.style.clipPath = `path(evenodd, "M0 0H${innerWidth}V${innerHeight}H0Z M${left + r} ${top}H${left + sw - r}A${r} ${r} 0 0 1 ${left + sw} ${top + r}V${top + sh - r}`
      + `A${r} ${r} 0 0 1 ${left + sw - r} ${top + sh}H${left + r}A${r} ${r} 0 0 1 ${left} ${top + sh - r}V${top + r}A${r} ${r} 0 0 1 ${left + r} ${top}Z")`;
    const w = pop.offsetWidth, h = pop.offsetHeight;
    if (innerWidth < 640) { pop.style.left = `${G}px`; pop.style.top = `${lit.top > innerHeight / 2 ? G : innerHeight - h - G}px`; return; }  // a phone: top or bottom, away from the spot
    let x, y;
    if (lit.bottom + 12 + h < innerHeight - G) { y = lit.bottom + 12; x = lit.left; }
    else if (lit.top - 12 - h > G) { y = lit.top - 12 - h; x = lit.left; }
    else if (lit.right + 12 + w < innerWidth - G) { x = lit.right + 12; y = lit.top; }
    else if (lit.left - 12 - w > G) { x = lit.left - 12 - w; y = lit.top; }
    else { x = innerWidth - w - G; y = innerHeight - h - G; }  // the spot fills the screen: the corner
    pop.style.left = `${Math.max(G, Math.min(x, innerWidth - w - G))}px`;
    pop.style.top = `${Math.max(G, Math.min(y, innerHeight - h - G))}px`;
  }
  function end() {
    if (!tour) return;
    const back = tour.back;
    tour.layer.remove(); tour.pop.remove(); tour = null;
    if (back?.isConnected && back !== document.body) back.focus({ preventScroll: true });
  }

  // ---------- suggested values in fields ----------
  function fillable(el) {
    if (!el.matches?.("input, select, textarea") || el.disabled || el.readOnly) return false;
    if (/^(hidden|file|checkbox|radio|color|submit|button|reset|image|password)$/.test(el.type)) return false;
    return !el.closest("#auth, .gd-pop, .gd-hint, .gd-menu, [data-gd-off]");
  }
  const ident = el => el.name || el.id || [...el.attributes].filter(a => a.name.startsWith("data-")).map(a => a.name.slice(5) + (a.value ? "=" + a.value : "")).join(" ")
    || el.getAttribute("aria-label") || el.placeholder || "";
  const secret = el => /new-password|one-time-code|cc-/.test(el.autocomplete) || SECRET.test(`${ident(el)} ${el.getAttribute("aria-label") || ""}`);
  function fieldName(el) {  // its label's words, without the field, hints and outputs inside the label
    const l = el.labels?.[0] || el.closest("label") || el.closest(".field, .in")?.querySelector("label, .lbl");
    let t = "";
    if (l) { const c = l.cloneNode(true); $$("input, select, textarea, small, output, .icon, svg", c).forEach(x => x.remove()); t = c.textContent; }
    return (t.trim() || el.getAttribute("aria-label") || el.placeholder || el.name || "this field").replace(/\s+/g, " ").slice(0, 60);
  }
  function ctx(el) {
    const form = el.form || el.closest("form");
    return {
      view, form, me: Auth.me(), data: typeof S !== "undefined" ? S.data : null,
      val: n => String(form?.elements[n]?.value ?? ""),
      workspace: () => (Workspace.subnets?.() || []).map(s => s.netuid),
      name: n => S.data?.subnets?.find(r => r.netuid === +n)?.name || "",
    };
  }
  // { values: [{ v, label }], why, recent: [...] } for a field, or null when there's nothing worth showing
  function suggest(el) {
    const c = ctx(el), cur = String(el.value);
    let values = null, why = "";
    const mine = GuideFields.filter(r => r.v !== "*" && [].concat(r.v).includes(view)), all = GuideFields.filter(r => r.v === "*");
    for (const r of [...mine, ...all]) {
      let out = null;
      try { if (!el.matches(r.sel)) continue; out = r.get(el, c); } catch { continue; }
      const list = Array.isArray(out) ? out : out?.values;
      if (!list?.length) continue;
      values = list; why = Array.isArray(out) ? "" : out.why || ""; break;
    }
    if (!values && !secret(el) && el.tagName !== "SELECT") {  // the form's own example: "e.g. Rhea", "…, e.g. “every week, …”"
      const m = /(?:^|[\s,(])e\.g\.?\s+(.+)$/i.exec((el.placeholder || "").trim());
      if (m) {
        const quoted = [...m[1].matchAll(/[“"]([^”"]{2,})[”"]/g)].map(q => q[1].trim());
        values = quoted.length ? quoted : [m[1].replace(/[“”]/g, "").trim()];
        why = "The form's own example.";
      }
    }
    values = (values || []).map(x => typeof x === "object" ? { v: String(x.v), label: String(x.label ?? x.v) } : { v: String(x), label: String(x) })
      .filter(x => x.v !== "")
      .map(x => {  // a select only takes one of its options
        if (el.tagName !== "SELECT") return x;
        const o = [...el.options].find(o => o.value === x.v || o.text.trim() === x.v);
        return o ? { v: o.value, label: x.label === x.v ? o.text.trim() : x.label } : null;
      }).filter(Boolean);
    values = values.filter((x, i) => values.findIndex(y => y.v === x.v) === i).slice(0, 4);
    const recent = secret(el) ? [] : ((pref("recent") || {})[`${view}|${ident(el)}`]?.vals || []).filter(r => r !== cur && !values.some(x => x.v === r)).slice(0, 3);
    if (!recent.length && !values.some(x => x.v !== cur)) return null;  // the field already holds the only suggestion
    return { values, why, recent };
  }
  function fill(el, v) {
    filling = true;
    try {
      if (el.tagName === "SELECT" && ![...el.options].some(o => o.value === v)) return;
      el.value = v;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } finally { filling = false; }
  }
  function onFocus(e) {
    const el = e.target;
    if (hint && (hint.box.contains(el) || hint.el === el)) return;
    hideHint();
    if (!on("hints") || tour || !fillable(el) || !el.closest("main, dialog[open]")) return;
    const s = suggest(el); if (!s) return;
    showHint(el, s);
  }
  function onBlur(e) {
    if (!hint) return;
    const to = e.relatedTarget;
    if (to && (hint.box.contains(to) || to === hint.el)) return;
    setTimeout(() => { if (hint && !hint.box.contains(document.activeElement) && document.activeElement !== hint.el) hideHint(); }, 120);
  }
  function showHint(el, s) {
    const cur = String(el.value), id = "gd-hint-" + Math.random().toString(36).slice(2, 8);
    const chip = (x, k) => `<button type="button" class="chip" tabindex="-1" data-v="${esc(x.v)}" aria-pressed="${x.v === cur}" data-k="${k}">${esc(x.label)}</button>`;
    const box = document.createElement("div");
    box.className = "gd-hint"; box.id = id; box.setAttribute("role", "group"); box.setAttribute("aria-label", `Suggestions for ${fieldName(el)}`);
    box.innerHTML = `${s.values.length ? `<div class="gd-row"><span class="gd-lbl">${icon("sparkle")}Suggested</span>${s.values.map(x => chip(x, "s")).join("")}</div>` : ""}
      ${s.why ? `<p class="gd-why">${esc(s.why)}</p>` : ""}
      ${s.recent.length ? `<div class="gd-row"><span class="gd-lbl">${icon("clock")}Used before</span>${s.recent.map(r => chip({ v: r, label: r }, "r")).join("")}</div>` : ""}
      <span class="sr-only">Press Alt+Down to pick a suggestion.</span>
      <button type="button" class="gd-x" tabindex="-1" data-gd="off" title="Turn suggestions off (the Guide button turns them back on)" aria-label="Turn suggestions off">${icon("close")}</button>`;
    const host = el.closest("dialog[open]") || document.body;
    host.append(box);
    if (box.showPopover) { box.popover = "manual"; try { box.showPopover(); } catch {} }  // the top layer: above an open dialog, never clipped by it
    hint = { el, box, prev: el.getAttribute("aria-describedby") };
    el.setAttribute("aria-describedby", [hint.prev, id].filter(Boolean).join(" "));
    box.addEventListener("pointerdown", e => e.preventDefault());  // keep the focus in the field
    box.addEventListener("click", e => {
      if (e.target.closest("[data-gd=off]")) { pref("hints", false); hideHint(); return toast("Suggestions are off. Turn them back on from the Guide button."); }
      const c = e.target.closest("[data-v]"); if (!c) return;
      pick(c);
    });
    box.addEventListener("keydown", e => {
      const chips = $$("[data-v]", box), k = chips.indexOf(document.activeElement);
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); chips[(k + 1) % chips.length]?.focus(); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); chips[(k - 1 + chips.length) % chips.length]?.focus(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); hint.el.focus(); }
    });
    placeHint();
  }
  function pick(c) {
    const el = hint.el;
    fill(el, c.dataset.v);
    hideHint();
    el.focus({ preventScroll: true });
  }
  function placeHint() {
    if (!hint) return;
    const { el, box } = hint;
    if (!visible(el)) return hideHint();
    const r = el.getBoundingClientRect(), w = Math.min(Math.max(r.width, 260), 420, innerWidth - 16);
    box.style.width = `${w}px`;
    const h = box.offsetHeight, below = r.bottom + 6 + h <= innerHeight - 8;
    box.style.top = `${below ? r.bottom + 6 : Math.max(8, r.top - 6 - h)}px`;
    box.style.left = `${Math.max(8, Math.min(r.left, innerWidth - w - 8))}px`;
  }
  function hideHint() {
    if (!hint) return;
    const { el, box, prev } = hint;
    hint = null;
    if (prev) el.setAttribute("aria-describedby", prev); else el.removeAttribute("aria-describedby");
    box.remove();
  }
  function onKey(e) {
    if (menuEl && e.key === "Escape") { closeMenu(); $("#guide-btn").focus(); return; }
    if (tour && !e.target.closest?.("input, textarea, select, [contenteditable]")) {
      if (e.key === "Escape") { e.preventDefault(); end(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); tour.i < tour.steps.length - 1 ? show(tour.i + 1) : end(); }
      else if (e.key === "ArrowLeft" && tour.i) { e.preventDefault(); show(tour.i - 1); }
      return;
    }
    if (!hint || e.target !== hint.el) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); hideHint(); }  // the suggestion goes, not the dialog
    else if (e.altKey && e.key === "ArrowDown") { e.preventDefault(); $("[data-v]", hint.box)?.focus(); }
  }
  // what you typed, for the next time: short single-line values only, never secrets, addresses or amounts
  function remember(e) {
    const el = e.target;
    if (filling || !fillable(el) || secret(el) || el.tagName !== "INPUT" || /^(search|range|date|time)$/.test(el.type) || !el.closest("main, dialog[open]")) return;
    const v = el.value.trim();
    if (!v || v.length > 80 || SECRETISH(v)) return;
    const all = pref("recent") || {}, k = `${view}|${ident(el)}`;
    all[k] = { t: Date.now(), vals: [v, ...(all[k]?.vals || []).filter(x => x !== v)].slice(0, 4) };
    const keys = Object.keys(all).sort((a, b) => all[b].t - all[a].t);
    for (const old of keys.slice(150)) delete all[old];
    pref("recent", all);
  }

  return { init, onView, start };
})();
