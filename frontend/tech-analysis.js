/* Technology Research analysis (tech_analysis.py), on top of Tech Daily (tech.js):
   - brief(el, ctx): the edition's research brief, for the day or the last seven days: a headline, the overview, themes
     with the stories behind each (a story in this edition opens its sheet, others link out), takeaways and what to watch.
     The day's brief is written with the edition; a missing one can be written from here, admins can write either again.
   - story(el, s, ctx): a story sheet's analysis: kept analyses show at once, else "Analyze" reads the article and writes one
     (verdict, maturity, summary, what/how, key points, audience, uses, limits, labelled background).
   ctx: {day, admin, signed, mark(ids)}. Each mount guards against a newer one (← → in the sheet, a day change). */
const TechAnalysis = (() => {
  const VERDICT = { adopt: ["Adopt", "Mature and useful now"], try: ["Try", "Worth an experiment"], watch: ["Watch", "Promising, too early"], skip: ["Skip", "Hype, niche or not new"] };
  const MATURITY = { research: "Research", announced: "Announced", preview: "Preview", beta: "Beta", available: "Available now", unclear: "Maturity unclear" };
  let scope = (() => { try { return localStorage.getItem("tech.brief") === "week" ? "week" : "day"; } catch { return "day"; } })();
  let briefSeq = 0, storySeq = 0;
  const when = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const list = (xs, cls = "") => xs?.length ? `<ul class="tan-list ${cls}">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";

  // ---------- the brief ----------
  async function brief(el, ctx, force = null) {
    if (!el) return;
    const n = ++briefSeq;
    el.innerHTML = frame(ctx, `<div class="tan-sk"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div>`);
    let r;
    try {
      r = force ? await api("/api/tech/brief", { method: "POST", body: { day: ctx.day, scope, force: force === "again" } })
                : await api(`/api/tech/brief?scope=${scope}&day=${encodeURIComponent(ctx.day)}`);
    } catch (e) { if (n === briefSeq) el.innerHTML = frame(ctx, `<p class="tan-empty">${icon("alert")}${esc(e.message)}</p>`); return; }
    if (n !== briefSeq) return;
    ctx.mark?.(r.analyzed || []);
    el.innerHTML = frame(ctx, r.brief ? body(r.brief, ctx) : empty(r, ctx));
    el.onclick = e => {
      const t = e.target.closest("[data-tan-scope],[data-tan-write]");
      if (!t) return;
      if (t.dataset.tanScope) { scope = t.dataset.tanScope; try { localStorage.setItem("tech.brief", scope); } catch {} brief(el, ctx); return; }
      t.disabled = true; t.innerHTML = Loading.line(scope === "week" ? "Reading the week…" : "Reading the edition…");
      brief(el, ctx, t.dataset.tanWrite);
    };
  }
  function frame(ctx, inner) {
    return `<header class="tan-head"><div><span class="tan-eyebrow">${icon("bulb")}Research brief</span>
        <h2>${scope === "week" ? "The week in tech." : "The day in tech."}<span> Analyzed and summarized.</span></h2></div>
      <div class="tan-scope" role="group" aria-label="Brief period">
        <button type="button" class="chip" data-tan-scope="day" aria-pressed="${scope === "day"}">This edition</button>
        <button type="button" class="chip" data-tan-scope="week" aria-pressed="${scope === "week"}">Last 7 days</button></div></header>
      <div class="tan-body">${inner}</div>`;
  }
  function empty(r, ctx) {
    if (!r.ai) return `<p class="tan-empty">${icon("info")}No model is connected for Tech Daily, so there's no brief. ${ctx.admin ? "Connect one in Agents → Models." : "An administrator can connect one."}</p>`;
    const what = scope === "week" ? "the last seven days" : "this edition";
    return `<p class="tan-empty">${icon("info")}There's no brief for ${what} yet.</p>
      ${ctx.signed ? `<button type="button" class="btn primary sm" data-tan-write="new">${icon("sparkle")}Write the brief</button>` : ""}`;
  }
  function body(b, ctx) {
    const chip = s => s.id ? `<button type="button" class="tan-story c-${esc(s.category)}" data-story="${s.id}">${esc(s.headline)}</button>`
      : `<a class="tan-story c-${esc(s.category)}" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.headline)}${icon("external")}</a>`;
    return `${b.stale ? `<p class="notice small">${icon("info")}<span>The edition was rebuilt after this brief was written.</span></p>` : ""}
      ${b.headline ? `<h3 class="tan-hl">${esc(b.headline)}</h3>` : ""}
      <p class="tan-sum">${esc(b.summary)}</p>
      ${b.themes?.length ? `<div class="tan-themes">${b.themes.map((t, i) => `<section class="tan-theme">
          <span class="tan-n">${String(i + 1).padStart(2, "0")}</span><h4>${esc(t.title)}</h4><p>${esc(t.summary)}</p>
          ${t.stories?.length ? `<div class="tan-stories">${t.stories.map(chip).join("")}</div>` : ""}</section>`).join("")}</div>` : ""}
      <div class="tan-cols">
        ${b.takeaways?.length ? `<div><h4>${icon("check")}Takeaways</h4>${list(b.takeaways, "good")}</div>` : ""}
        ${b.watch?.length ? `<div><h4>${icon("eye")}What to watch</h4>${list(b.watch)}</div>` : ""}</div>
      <p class="tan-foot faint small">${icon("info")}<span>Written by AI (${esc(b.model || "a model")}) from ${b.stories} ${b.stories === 1 ? "story" : "stories"}' headlines and summaries, ${esc(when(b.ts))}. Check the sources before relying on a detail.</span>
        ${ctx.admin ? `<button type="button" class="link" data-tan-write="again">Write again</button>` : ""}</p>`;
  }

  // ---------- a story's analysis ----------
  async function story(el, s, ctx) {
    if (!el) return;
    const n = ++storySeq;
    el.innerHTML = `<div class="tan-sk"><span class="skeleton"></span></div>`;
    const r = await api(`/api/tech/stories/${s.id}/analysis`).catch(e => ({ error: e.message }));
    if (n !== storySeq) return;
    show(el, s, ctx, r, n);
  }
  function show(el, s, ctx, r, n) {
    if (r.error) { el.innerHTML = `<p class="tan-empty">${icon("alert")}${esc(r.error)}</p>`; return; }
    const a = r.analysis;
    if (!a) {
      el.innerHTML = `<div class="tan-cta"><div><b>${icon("bulb")}Analyze this technology</b>
          <p class="faint small">${r.ai ? "AXoR reads the article and writes what it is, how it works, who it's for, its limits and a verdict." : "No model is connected for Tech Daily, so stories can't be analyzed."}</p></div>
          ${r.ai && ctx.signed ? `<button type="button" class="btn primary" data-tan="run">${icon("sparkle")}Analyze</button>` : ""}</div>`;
    } else el.innerHTML = analysis(a, ctx);
    el.onclick = async e => {
      const b = e.target.closest("[data-tan]"); if (!b) return;
      if (b.dataset.tan === "note") return note(s, a);
      const force = b.dataset.tan === "again";
      el.innerHTML = `<div class="tan-cta">${Loading.line("Reading the article and analyzing it…")}</div>`;
      const out = await api(`/api/tech/stories/${s.id}/analysis`, { method: "POST", body: { force } }).catch(err => ({ error: err.message }));
      if (n !== storySeq) return;
      if (!out.error) ctx.mark?.([s.id], true);
      show(el, s, ctx, out.error ? { error: out.error } : out, n);
    };
  }
  function analysis(a, ctx) {
    const [v, vline] = VERDICT[a.verdict] || VERDICT.watch;
    return `<div class="tan-an">
      <div class="tan-badges"><span class="tan-verdict v-${esc(a.verdict)}" title="${esc(vline)}">${icon(a.verdict === "skip" ? "ban" : a.verdict === "watch" ? "eye" : "check")}${esc(v)}</span>
        <span class="tan-pill">${esc(MATURITY[a.maturity] || a.maturity)}</span>
        <span class="tan-pill conf-${esc(a.confidence)}" title="How sure the analysis is">${esc(a.confidence)} confidence</span></div>
      ${a.verdict_why ? `<p class="tan-why">${esc(a.verdict_why)}</p>` : ""}
      <p>${esc(a.summary)}</p>
      <dl class="tan-dl">
        ${a.what ? `<dt>What it is</dt><dd>${esc(a.what)}</dd>` : ""}
        ${a.how ? `<dt>How it works</dt><dd>${esc(a.how)}</dd>` : ""}
        ${a.audience ? `<dt>Who it's for</dt><dd>${esc(a.audience)}</dd>` : ""}</dl>
      ${a.points?.length ? `<h4>Key points</h4>${list(a.points)}` : ""}
      ${a.uses?.length ? `<h4>What you could do with it</h4>${list(a.uses, "good")}` : ""}
      ${a.limits?.length ? `<h4>Limits and open questions</h4>${list(a.limits, "warn")}` : ""}
      ${a.background ? `<div class="tan-bg"><b>Background</b> <span class="faint small">(the model's general knowledge, not the article)</span><p>${esc(a.background)}</p></div>` : ""}
      <p class="tan-foot faint small">${icon("info")}<span>${a.based_on === "article" ? "Analyzed from the article" : "The article couldn't be read: analyzed from the outlet's summary only"} by ${esc(a.model || "AI")}, ${esc(when(a.ts))}.</span></p>
      <div class="row">${ctx.signed ? `<button type="button" class="btn sm" data-tan="note">${icon("note")}Save analysis to notes</button>` : ""}
        ${ctx.admin ? `<button type="button" class="btn sm" data-tan="again">${icon("reset")}Analyze again</button>` : ""}</div></div>`;
  }
  async function note(s, a) {
    const bullets = (h, xs) => xs?.length ? `\n${h}:\n${xs.map(x => `- ${x}`).join("\n")}` : "";
    const text = (`**${s.headline}** (${(VERDICT[a.verdict] || VERDICT.watch)[0]}, ${MATURITY[a.maturity] || a.maturity})\n${a.summary}`
      + bullets("Key points", a.points) + bullets("Limits", a.limits) + `\n[${s.source}: ${s.title}](${s.url})`).slice(0, 4000);
    try { await api("/api/workspace/notes", { method: "POST", body: { text, color: "blue" } }); UI.toast("Saved to your notes"); if (typeof Notes !== "undefined") Notes.load(); }
    catch (err) { UI.toast(err.message); }
  }

  return { brief, story };
})();
