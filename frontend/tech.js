/* Tech Daily: the day's new technology (AI, software, Android, devices, IoT and security), told like ads. One edition
   a day from /api/tech (techboard.py): the cover line, today's spotlight, a bento of each category's lead story, then a
   rail per category; a category chip shows that category alone. A story opens its sheet (← → move through the
   edition, Esc closes). Earlier editions are one tap away, admins can rebuild today's, and the sidebar says "New" until
   you've seen the latest edition. Pictures load from the stories' own sites and fall back to the category's art. */
const Tech = (() => {
  let d = null, cat = "all", day = null, seq = 0, wired = false, timer = null, order = [], at = -1, io = null;
  const pref = (k, v) => { try { if (v === undefined) return localStorage.getItem("tech." + k); localStorage.setItem("tech." + k, v); } catch { return null; } };
  const CAT = id => d?.categories.find(c => c.id === id) || { id, label: id, line: "", icon: "news" };
  const byId = id => d?.stories.find(s => s.id === +id);
  const hash = t => { let h = 2166136261; for (const ch of String(t)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return h >>> 0; };
  const utcDay = (offset = 0) => new Date(Date.now() - offset * 86400000).toISOString().slice(0, 10);
  const asDate = dd => new Date(dd + "T12:00:00Z");
  const dayLabel = dd => dd === utcDay() ? "Today" : dd === utcDay(1) ? "Yesterday"
    : asDate(dd).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
  const longDay = dd => asDate(dd).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
  const short = n => n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n);
  function age(ts) {
    const h = (Date.now() / 1000 - ts) / 3600;
    return h < 1 ? `${Math.max(1, Math.round(h * 60))}m ago` : h < 24 ? `${Math.round(h)}h ago` : h < 24 * 7 ? `${Math.round(h / 24)}d ago`
      : new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  const meta = s => s.source === "GitHub" && s.stars ? `GitHub · ★ ${short(s.stars)}` : `${esc(s.source)} · ${age(s.ts)}${s.points ? ` · ▲ ${short(s.points)}` : ""}`;

  // ---------- pieces ----------
  // a story's picture, over its category's art (the art shows when there's no picture or it fails to load)
  function art(s) {
    const h = hash(s.url);
    const pos = `--x1:${8 + h % 55}%;--y1:${6 + (h >>> 6) % 45}%;--x2:${45 + (h >>> 12) % 50}%;--y2:${40 + (h >>> 18) % 50}%;--rot:${(h >>> 4) % 360}deg`;
    return `<div class="tb-art c-${esc(s.category)}${s.image ? "" : " noimg"}" style="${pos}">
      <span class="tb-glyph">${icon(CAT(s.category).icon)}</span>
      ${s.image ? `<img class="tb-img" src="${esc(s.image)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ""}</div>`;
  }
  function card(s, cls = "") {
    const c = CAT(s.category);
    return `<article class="tb-card ${cls} tb-reveal" data-story="${s.id}" tabindex="0" role="button" aria-label="${esc(s.headline)}">
      ${art(s)}<div class="tb-scrim"></div>
      <div class="tb-copy">
        <span class="tb-kicker">${icon(c.icon)}${esc(c.label)}</span>
        <h3 class="tb-hl">${esc(s.headline)}</h3>
        ${s.tagline ? `<p class="tb-tagline">${esc(s.tagline)}</p>` : ""}
        <span class="tb-src">${meta(s)}</span>
      </div></article>`;
  }
  function hero(s) {
    const c = CAT(s.category);
    return `<section class="tb-hero tb-reveal" data-story="${s.id}" aria-label="Today's spotlight">
      ${art(s)}<div class="tb-hero-scrim"></div>
      <div class="tb-hero-copy">
        <span class="tb-eyebrow">${icon("star")}Spotlight · ${esc(c.label)}</span>
        <h2 class="tb-hero-hl">${esc(s.headline)}</h2>
        ${s.tagline ? `<p class="tb-hero-tag">${esc(s.tagline)}</p>` : ""}
        <div class="tb-cta">
          <a class="tb-btn light" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">Read the story${icon("external")}</a>
          <button type="button" class="tb-btn glass" data-story="${s.id}">Details${icon("right")}</button>
        </div>
        <span class="tb-src">${meta(s)}</span>
      </div></section>`;
  }
  // the cover line, one sentence per line, the last one in the accent gradient
  function cover(text) {
    const parts = (text || "Today in tech.").match(/[^.!?]+[.!?]*/g)?.map(x => x.trim()).filter(Boolean) || [text];
    return parts.map((p, i) => `<span class="${i === parts.length - 1 ? "tb-grad" : ""}">${esc(p)}</span>`).join(" ");
  }
  function skeleton(text) {
    return `<div class="tb"><header class="tb-mast"><div class="tb-brandline"><span class="tb-wordmark">Tech<b>Daily</b></span></div>
      <h1 class="tb-cover"><span class="skeleton tb-sk-cover"></span></h1>${text ? `<p class="tb-sub">${Loading.line(esc(text))}</p>` : ""}</header>
      <div class="tb-hero tb-sk"><div class="tb-art"></div></div>
      <div class="tb-bento">${Array.from({ length: 6 }, (_, i) => `<div class="tb-card tb-sk ${["b-xl", "b-wide", "", "", "b-wide", "b-wide"][i]}"><div class="tb-art"></div></div>`).join("")}</div></div>`;
  }

  // ---------- page ----------
  async function open() {
    wire();
    const s = ++seq;
    if (!d) $("#tech").innerHTML = skeleton();
    try { const r = await api("/api/tech" + (day ? `?day=${encodeURIComponent(day)}` : "")); if (s !== seq) return; d = r; }
    catch (e) { if (s !== seq) return; if (e.status === 404 && day) { day = null; return open(); } $("#tech").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    if (d.edition && d.edition.day === d.days[0]?.day) { pref("seen", d.edition.day); badge(false); }
    render();
    watch();
  }

  function render() {
    const ed = d.edition, st = d.state, root = $("#tech");
    if (!ed) {
      root.innerHTML = st.building ? skeleton(st.step ? `Writing the first edition: ${st.step.toLowerCase()}…` : "Writing the first edition…")
        : `<div class="tb"><header class="tb-mast"><div class="tb-brandline"><span class="tb-wordmark">Tech<b>Daily</b></span></div>
            <h1 class="tb-cover"><span>New technology,</span> <span class="tb-grad">every morning.</span></h1>
            <p class="tb-sub">${!st.enabled ? "Tech Daily is turned off on this server (TECH_DAILY=0)."
              : `The first edition is written a minute after AXoR starts, then every day after ${new Date(st.next * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}.`}</p>
            ${st.error ? `<div class="notice">${icon("alert")}<div>${esc(st.error)}</div></div>` : ""}
            ${d.admin && st.enabled ? `<div class="tb-cta"><button type="button" class="btn primary" data-tb-rebuild>${icon("sparkle")}Build it now</button></div>` : ""}
          </header></div>`;
      return;
    }
    const stories = d.stories, cats = d.categories.filter(c => stories.some(s => s.category === c.id));
    if (cat !== "all" && !cats.some(c => c.id === cat)) cat = "all";
    const spot = byId(ed.spotlight) || stories[0];
    const sources = new Set(stories.map(s => s.source)).size;
    const days = d.days.slice(0, 7), older = d.days.slice(7);
    root.innerHTML = `<div class="tb${matchMedia("(prefers-reduced-motion: no-preference)").matches ? " tb-anim" : ""}">
      ${st.building ? `<div class="tb-banner">${Loading.line(`Rebuilding today's edition${st.step ? `: ${esc(st.step.toLowerCase())}` : ""}…`)}</div>` : ""}
      ${d.admin && st.error ? `<div class="notice">${icon("alert")}<div><b>The last build failed.</b> ${esc(st.error)}</div></div>` : ""}
      <header class="tb-mast">
        <div class="tb-brandline"><span class="tb-wordmark">Tech<b>Daily</b></span><span class="tb-sep"></span><time datetime="${esc(ed.day)}">${esc(longDay(ed.day))}</time></div>
        <h1 class="tb-cover">${cover(ed.cover)}</h1>
        <p class="tb-sub">${stories.length} stories from ${sources} sources · ${ed.model ? "copy written by AI from each outlet's own summary" : "in the outlets' own words"} · updated ${esc(new Date(ed.ts * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))}</p>
        <div class="tb-tools">
          <div class="tb-days" role="group" aria-label="Edition">${days.map(x => `<button type="button" class="chip" data-tb-day="${esc(x.day)}" aria-pressed="${x.day === ed.day}">${esc(dayLabel(x.day))}</button>`).join("")}
            ${older.length ? `<select class="tb-older" aria-label="Older editions"><option value="">Older…</option>${older.map(x => `<option value="${esc(x.day)}" ${x.day === ed.day ? "selected" : ""}>${esc(dayLabel(x.day))}</option>`).join("")}</select>` : ""}</div>
          ${d.admin ? `<span class="tb-admin">${ed.model ? `<span class="faint small" title="Model and tokens for this edition's copy">${esc(ed.model)} · ${short(ed.tokens || 0)} tokens</span>` : ""}
            <button type="button" class="btn sm" data-tb-rebuild ${st.building || !st.enabled ? "disabled" : ""}>${icon("reset")}Rebuild today</button></span>` : ""}
        </div>
      </header>
      <nav class="tb-nav" aria-label="Categories">
        <button type="button" data-tb-cat="all" aria-pressed="${cat === "all"}">All<small>${stories.length}</small></button>
        ${cats.map(c => `<button type="button" data-tb-cat="${esc(c.id)}" class="c-${esc(c.id)}" aria-pressed="${cat === c.id}">${icon(c.icon)}${esc(c.label)}<small>${stories.filter(s => s.category === c.id).length}</small></button>`).join("")}
      </nav>
      ${cat === "all" ? everything(spot, cats) : category(CAT(cat))}
      <footer class="tb-foot">${icon("info")}<span>Stories link to their sources. ${ed.model ? "Headlines and summaries are written by AI from each outlet's own summary, so check the source before you rely on a detail." : ""} A new edition arrives every morning.</span></footer>
    </div>`;
    order = [...$$("[data-story].tb-card, .tb-hero[data-story]", root)].map(el => +el.dataset.story).filter((v, i, a) => a.indexOf(v) === i);
    reveal(root);
    if (typeof TechAnalysis !== "undefined") TechAnalysis.brief($("[data-tan-brief]", root), research());
  }
  // what the analysis (tech-analysis.js) needs from the page; mark() badges the cards of analyzed stories
  function research() {
    const mark = ids => ids.forEach(id => $$(`.tb-card[data-story="${id}"] .tb-kicker`, $("#tech")).forEach(k => {
      if (!k.querySelector(".tan-mark")) k.insertAdjacentHTML("beforeend", `<span class="tan-mark">${icon("bulb")}Analyzed</span>`);
    }));
    return { day: d.edition.day, admin: d.admin, signed: !!Auth.me(), mark };
  }

  // All: the spotlight, each category's lead story in a bento, then the rest of each category on a rail
  function everything(spot, cats) {
    const leads = cats.map(c => d.stories.filter(s => s.category === c.id && s.id !== spot.id)[0]).filter(Boolean);
    const shown = new Set([spot.id, ...leads.map(s => s.id)]);
    const sizes = ["b-xl", "b-wide", "", "", "b-wide", "b-wide"];
    return `${hero(spot)}
      ${typeof TechAnalysis !== "undefined" ? `<section class="tan tb-reveal" data-tan-brief aria-label="Research brief"></section>` : ""}
      <h2 class="tb-h2 tb-reveal">The day's leads.<span> One from every corner of tech.</span></h2>
      <div class="tb-bento">${leads.map((s, i) => card(s, sizes[i] || "")).join("")}</div>
      ${cats.map(c => {
        const rest = d.stories.filter(s => s.category === c.id && !shown.has(s.id));
        if (!rest.length) return "";
        return `<section class="tb-sec c-${esc(c.id)}" aria-label="${esc(c.label)}">
          <header class="tb-sec-head tb-reveal"><div><h2>${esc(c.label)}.</h2><p>${esc(c.line)}</p></div>
            <div class="tb-sec-tools"><button type="button" class="link" data-tb-cat="${esc(c.id)}">See all ${esc(c.label)}</button>
              <button type="button" class="tb-arrow" data-tb-rail="${esc(c.id)}" data-dir="-1" aria-label="Scroll back">${icon("left")}</button>
              <button type="button" class="tb-arrow" data-tb-rail="${esc(c.id)}" data-dir="1" aria-label="Scroll on">${icon("right")}</button></div></header>
          <div class="tb-rail" data-rail="${esc(c.id)}">${rest.map(s => card(s, "poster")).join("")}</div></section>`;
      }).join("")}`;
  }
  // one category: its banner, then every story, the first one wide
  function category(c) {
    const list = d.stories.filter(s => s.category === c.id);
    return `<section class="tb-band c-${esc(c.id)} tb-reveal"><span class="tb-band-glyph">${icon(c.icon)}</span><div><h2>${esc(c.label)}.</h2><p>${esc(c.line)}</p></div>
        <span class="tb-band-n">${list.length} ${list.length === 1 ? "story" : "stories"} today</span></section>
      <div class="tb-grid">${list.map((s, i) => card(s, i === 0 ? "b-feature" : "poster")).join("")}</div>`;
  }

  // ---------- the story sheet ----------
  function sheet(id) {
    const s = byId(id); if (!s) return;
    at = order.indexOf(s.id);
    let dlg = $("#tb-sheet");
    if (!dlg) {
      dlg = document.createElement("dialog"); dlg.id = "tb-sheet"; dlg.className = "tb-sheet"; document.body.append(dlg);
      dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });  // the backdrop
      dlg.addEventListener("keydown", e => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); step(e.key === "ArrowRight" ? 1 : -1); }
      });
      dlg.addEventListener("click", sheetAction);
    }
    const c = CAT(s.category), signed = !!Auth.me();
    dlg.innerHTML = `<article class="tb-sh">
      <div class="tb-sh-art">${art(s)}<div class="tb-scrim"></div><span class="tb-kicker">${icon(c.icon)}${esc(c.label)}</span>
        <button type="button" class="tb-sh-x" data-sh="close" aria-label="Close">${icon("close")}</button></div>
      <div class="tb-sh-body">
        <span class="tb-sh-meta">${meta(s)}</span>
        <h2>${esc(s.headline)}</h2>
        ${s.tagline ? `<p class="tb-sh-tag">${esc(s.tagline)}</p>` : ""}
        ${s.pitch ? `<p>${esc(s.pitch)}</p>` : ""}
        ${s.why?.length ? `<h4>Why it matters</h4><ul class="tb-why">${s.why.map(w => `<li>${icon("check")}<span>${esc(w)}</span></li>`).join("")}</ul>` : ""}
        ${s.tags?.length ? `<div class="tags">${s.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
        ${s.headline !== s.title ? `<p class="faint small tb-sh-orig">On ${esc(s.site)}: “${esc(s.title)}”</p>` : ""}
        <div class="row tb-sh-actions">
          <a class="btn primary" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">Read on ${esc(s.site)}${icon("external")}</a>
          <button type="button" class="btn" data-sh="copy">${icon("link")}Copy link</button>
          ${navigator.share ? `<button type="button" class="btn" data-sh="share">${icon("send")}Share</button>` : ""}
          ${signed ? `<button type="button" class="btn" data-sh="note">${icon("note")}Save to notes</button>` : ""}
        </div>
        ${typeof TechAnalysis !== "undefined" ? `<section class="tan-sheet" data-tan-story aria-label="Analysis"><h4>Analysis</h4><div></div></section>` : ""}
        <div class="tb-sh-nav"><button type="button" class="btn sm" data-sh="prev" ${at <= 0 ? "disabled" : ""}>${icon("left")}Previous</button>
          <span class="faint small">${at + 1} of ${order.length}</span>
          <button type="button" class="btn sm" data-sh="next" ${at >= order.length - 1 ? "disabled" : ""}>Next${icon("right")}</button></div>
      </div></article>`;
    dlg.dataset.id = s.id;
    if (!dlg.open) dlg.showModal();
    $(".tb-sh-body", dlg).scrollTop = 0;
    if (typeof TechAnalysis !== "undefined") TechAnalysis.story($("[data-tan-story] > div", dlg), s, research());
  }
  function step(dir) { const n = order[at + dir]; if (n != null) sheet(n); }
  async function sheetAction(e) {
    const b = e.target.closest("[data-sh]"); if (!b) return;
    const dlg = $("#tb-sheet"), s = byId(dlg.dataset.id), act = b.dataset.sh;
    if (act === "close") return dlg.close();
    if (act === "prev" || act === "next") return step(act === "next" ? 1 : -1);
    if (act === "copy") { try { await navigator.clipboard.writeText(s.url); UI.toast("Link copied"); } catch { UI.toast("Couldn't copy the link"); } return; }
    if (act === "share") { try { await navigator.share({ title: s.headline, text: s.tagline || s.title, url: s.url }); } catch {} return; }
    if (act === "note") {
      const text = `**${s.headline}**\n${s.tagline || s.title}\n[${s.source}: ${s.title}](${s.url})`.slice(0, 4000);
      try { await api("/api/workspace/notes", { method: "POST", body: { text, color: "blue" } }); UI.toast("Saved to your notes"); Notes.load(); }
      catch (err) { UI.toast(err.message); }
    }
  }

  // ---------- behaviour ----------
  function reveal(root) {
    const els = $$(".tb-reveal", root);
    if (!root.querySelector(".tb-anim") || !("IntersectionObserver" in window)) { els.forEach(el => el.classList.add("in")); return; }
    io?.disconnect();
    io = new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
    els.forEach(el => io.observe(el));
  }
  // while an edition is being built, check every few seconds and show it once it's written
  function watch() {
    clearTimeout(timer);
    if (!d?.state.building) return;
    timer = setTimeout(async () => {
      if (S.view !== "tech") return;
      const st = await api("/api/tech/status").catch(() => null);
      if (!st) return watch();
      if (st.building) { d.state = st; const b = $(".tb-banner"); if (b) b.innerHTML = Loading.line(`Rebuilding today's edition${st.step ? `: ${esc(st.step.toLowerCase())}` : ""}…`); else if (!d.edition) render(); return watch(); }
      day = null; open();
      if (st.error && d.admin) UI.toast("The edition couldn't be built: " + st.error);
    }, 3000);
  }
  async function rebuild() {
    const ok = await UI.confirm({ title: "Rebuild today's edition?", icon: "reset", danger: false, ok: "Rebuild",
      body: "AXoR reads every source again and replaces today's stories. With a model connected, the copy is written again too, which takes a minute or two and uses tokens.",
      run: async () => { d.state = await api("/api/tech/rebuild", { method: "POST" }); } });
    if (!ok) return;
    day = null; open();
  }
  function wire() {
    if (wired) return; wired = true;
    const root = $("#tech");
    root.addEventListener("click", e => {
      const t = e.target;
      const c = t.closest("[data-tb-cat]"); if (c) { cat = c.dataset.tbCat; render(); $("#view-tech").scrollIntoView({ block: "start" }); return; }
      const dd = t.closest("[data-tb-day]"); if (dd) { day = dd.dataset.tbDay; cat = "all"; open(); return; }
      const r = t.closest("[data-tb-rail]");
      if (r) { const rail = $(`.tb-rail[data-rail="${r.dataset.tbRail}"]`, root); rail?.scrollBy({ left: +r.dataset.dir * rail.clientWidth * 0.85, behavior: "smooth" }); return; }
      if (t.closest("[data-tb-rebuild]")) return rebuild();
      if (t.closest("a")) return;  // the hero's link opens the story itself
      const s = t.closest("[data-story]"); if (s) sheet(s.dataset.story);
    });
    root.addEventListener("keydown", e => {
      const s = e.target.closest?.(".tb-card[data-story]");
      if (s && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); sheet(s.dataset.story); }
    });
    root.addEventListener("change", e => { if (e.target.matches(".tb-older") && e.target.value) { day = e.target.value; cat = "all"; open(); } });
    // a picture that won't load leaves the category's art showing; one that loads fades in
    root.ownerDocument.addEventListener("error", e => {
      const img = e.target;
      if (img.classList?.contains("tb-img")) { img.parentElement.classList.add("noimg"); img.remove(); }
    }, true);
    root.ownerDocument.addEventListener("load", e => { if (e.target.classList?.contains("tb-img")) e.target.classList.add("loaded"); }, true);
  }

  // the sidebar says "New" until you've opened the latest edition
  function badge(on) { const b = $("#c-tech"); if (b) { b.textContent = on ? "New" : ""; b.classList.toggle("tb-new", on); } }
  async function init() {
    const r = await api("/api/tech/latest").catch(() => null);
    if (r?.day && r.day !== pref("seen") && S.view !== "tech") badge(true);
  }

  return { init, open };
})();
