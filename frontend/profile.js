/* My profile: an AI engineer's profile (profile.py), made into a resume, a full CV and a portfolio website that
   publishes at /u/<slug> or deploys to Netlify. Edits save as you type. The previews are the server's own pages in
   frames, so what you see is what visitors and the PDF get. */
const Profile = (() => {
  let v = null, p = null, tab = "edit", doc = "resume", timer = null, saving = null, dirty = false, wired = false, seq = 0;
  const openIds = new Set();  // list entries shown expanded
  const uid = () => Math.random().toString(36).slice(2, 10);
  const root = () => $("#profile");

  // fields: [key, label, placeholder, max length (of each item for lists), type, max items, hint]
  // types: text (default), month, url, email, area (a textarea), lines (one item per line), csv (comma-separated), check
  const LISTS = {
    links: { title: "Links", icon: "link", add: "Add link", one: "link", max: 10, inline: true,
      empty: "GitHub, LinkedIn, Hugging Face, Google Scholar, a blog…", blank: () => ({ label: "", url: "" }), head: x => x.label || x.url,
      fields: [["label", "Label", "GitHub", 40], ["url", "URL", "github.com/you", 300, "url"]] },
    skills: { title: "Skills", icon: "zap", add: "Add group", one: "skill group", max: 12, inline: true,
      empty: "Group your skills, e.g. LLMs & agents · Machine learning · Infrastructure.", blank: () => ({ name: "", items: [] }), head: x => x.name,
      fields: [["name", "Group", "LLMs & agents", 60], ["items", "Skills, comma-separated", "RAG, tool calling, evals, fine-tuning", 60, "csv", 40]] },
    experience: { title: "Experience", icon: "clock", add: "Add role", one: "role", max: 20, untitled: "New role",
      empty: "Your roles, newest first.", head: x => [x.title, x.company].filter(Boolean).join(" · "), sub: x => span(x.start, x.end),
      blank: () => ({ title: "", company: "", location: "", start: "", end: "", bullets: [], tech: [] }),
      fields: [["title", "Title", "Senior AI Engineer", 100], ["company", "Company", "Acme AI", 100], ["location", "Location", "Remote", 80],
        ["start", "Start", "YYYY-MM", 20, "month"], ["end", "End", "YYYY-MM", 20, "month", 0, "Leave empty while you work there."],
        ["bullets", "Highlights, one per line", "Shipped a RAG assistant that answers 40% of support tickets", 400, "lines", 12],
        ["tech", "Tech, comma-separated", "Python, PyTorch, vLLM, pgvector", 40, "csv", 20]] },
    projects: { title: "Projects", icon: "repo", add: "Add project", one: "project", max: 24, untitled: "New project",
      empty: "Things you built: demos, open-source, research code. Feature the best on your resume and site.", head: x => x.name, sub: x => x.featured ? "Featured" : "",
      blank: () => ({ name: "", url: "", repo: "", description: "", tech: [], featured: false }),
      fields: [["name", "Name", "Agentic code reviewer", 100], ["url", "Live URL", "demo.example.com", 300, "url"], ["repo", "Code", "github.com/you/project", 300, "url"],
        ["description", "Description", "What it does, how it works, and what it achieved.", 600, "area"],
        ["tech", "Tech, comma-separated", "LangGraph, FastAPI, Postgres", 40, "csv", 20], ["featured", "Featured on the resume and site", "", 0, "check"]] },
    education: { title: "Education", icon: "book", add: "Add school", one: "school", max: 10, untitled: "New school",
      empty: "Degrees, bootcamps, notable courses.", head: x => [x.degree, x.school].filter(Boolean).join(" · "), sub: x => span(x.start, x.end),
      blank: () => ({ school: "", degree: "", start: "", end: "", detail: "" }),
      fields: [["degree", "Degree", "MSc Computer Science", 120], ["school", "School", "TU Berlin", 120], ["start", "Start", "YYYY-MM", 20, "month"],
        ["end", "End", "YYYY-MM", 20, "month"], ["detail", "Details", "Thesis on retrieval-augmented generation", 300]] },
    publications: { title: "Publications & talks", icon: "news", add: "Add", one: "publication", max: 40, untitled: "New publication",
      empty: "Papers, preprints, conference talks, notable blog posts. Shown on the CV and the site.", head: x => x.title, sub: x => [x.venue, x.year].filter(Boolean).join(", "),
      blank: () => ({ title: "", venue: "", year: "", url: "" }),
      fields: [["title", "Title", "Evaluating agents with LLM judges", 240], ["venue", "Venue", "NeurIPS workshop", 120], ["year", "Year", "2026", 10], ["url", "URL", "arxiv.org/abs/…", 300, "url"]] },
    certifications: { title: "Certifications", icon: "trophy", add: "Add", one: "certification", max: 20, untitled: "New certification",
      empty: "Cloud, ML or security certifications and awards. Shown on the CV and the site.", head: x => x.name, sub: x => [x.issuer, x.year].filter(Boolean).join(", "),
      blank: () => ({ name: "", issuer: "", year: "", url: "" }),
      fields: [["name", "Name", "AWS Certified Machine Learning", 160], ["issuer", "Issuer", "Amazon Web Services", 120], ["year", "Year", "2025", 10], ["url", "URL", "", 300, "url"]] },
  };
  const BASICS = [["name", "Full name", "Ada Lovelace", 80], ["headline", "Headline", "AI engineer · LLM agents, RAG and evals", 140],
    ["location", "Location", "Berlin · Remote", 80], ["availability", "Availability", "Open to senior AI engineer roles", 120],
    ["email", "Email", "you@example.com", 120, "email"], ["phone", "Phone", "+49 30 1234567", 40],
    ["photo", "Photo URL", "https://github.com/you.png", 500, "url", 0, "An https link to a square photo. Empty: line art."]];
  const CHECKS = [
    [x => x.name && x.headline, "Name and headline", "basics"],
    [x => x.summary.length >= 120, "A 2–4 sentence summary", "basics"],
    [x => x.email, "A contact email", "basics"],
    [x => x.links.length, "Links: GitHub, LinkedIn…", "links"],
    [x => x.skills.some(g => g.items.length >= 3), "Grouped skills", "skills"],
    [x => x.experience.some(j => j.bullets.length >= 2), "Roles with highlights", "experience"],
    [x => x.projects.length >= 2, "Two or more projects", "projects"],
    [x => x.projects.some(j => j.featured), "A featured project", "projects"],
    [x => x.education.length, "Education", "education"],
  ];
  const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
  const when = s => { const m = /^(\d{4})-(\d{2})$/.exec(s || ""); return m && +m[2] >= 1 && +m[2] <= 12 ? `${MONTHS[m[2] - 1]} ${m[1]}` : s || ""; };
  function span(a, b) { a = when(a); b = when(b); return a ? `${a} – ${b || "Present"}` : b; }
  const clean = () => JSON.parse(JSON.stringify(p, (k, x) => k === "_id" ? undefined : x));
  const bare = u => (u || "").replace(/^https?:\/\//, "").replace(/\/$/, "");

  function init() { $("#nav-profile").hidden = !Auth.me(); tab = store.get("pf.tab", "edit"); doc = store.get("pf.doc", "resume"); }

  async function open() {
    wire();
    if (dirty || saving) await flush();
    const s = ++seq;
    if (!v) root().innerHTML = `<div class="card empty">${Loading.line("Loading your profile…")}</div>`;
    try { const r = await api("/api/profile"); if (s !== seq) return; adopt(r, true); }
    catch (e) { if (s === seq && !v) root().innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    render();
  }
  // the server's view; `p` (what's being edited) is only replaced on a fresh load
  function adopt(r, fresh) {
    if (fresh) { p = r.profile; for (const k of Object.keys(LISTS)) p[k].forEach(x => x._id = uid()); }
    v = r;
  }

  // ---------- saving ----------
  function state(msg = "", bad = false) {
    const el = $("#pf-state"); if (!el) return;
    el.textContent = msg || (v?.updated ? "All changes saved" : "Not saved yet");
    el.classList.toggle("bad", bad);
  }
  function schedule() { dirty = true; clearTimeout(timer); state("Editing…"); timer = setTimeout(flush, 700); }
  async function flush() {
    clearTimeout(timer); timer = null;
    if (saving) await saving;
    if (!dirty) return;
    dirty = false; state("Saving…");
    saving = api("/api/profile", { method: "PUT", body: clean() })
      .then(r => { v.updated = r.updated; state(); }, e => { dirty = true; state("Couldn't save: " + e.message, true); })
      .finally(() => { saving = null; });
    return saving;
  }

  // ---------- page ----------
  function render() {
    const TABS = [["edit", "card", "Profile"], ["docs", "doc", "Resume & CV"], ["site", "globe", "Website"]];
    root().innerHTML = `
      <div class="pf-top"><div><h1 class="page">My profile</h1><p class="lead">Your AI engineer profile in one place, turned into a resume, a full CV and a personal website you can publish here or deploy to Netlify.</p></div>
        <div class="pf-top-acts"><span class="pf-state faint small" id="pf-state" role="status"></span>
          <button type="button" class="btn" data-pf="ai">${icon("sparkle")}AI review</button>
          ${v.published ? `<a class="btn" href="/u/${esc(v.slug)}" target="_blank" rel="noopener">${icon("external")}View site</a>` : ""}</div></div>
      <div class="seg pf-tabs" role="tablist" aria-label="Profile">${TABS.map(([k, ic, l]) => `<button type="button" role="tab" data-tab="${k}" aria-pressed="${tab === k}" aria-selected="${tab === k}">${icon(ic)}${l}</button>`).join("")}</div>
      <div id="pf-body"></div>`;
    state(); body();
  }
  function body() {
    $("#pf-body").innerHTML = tab === "docs" ? docs() : tab === "site" ? site() : editor();
    const f = $("#pf-frame");
    if (f && tab === "docs") f.addEventListener("load", () => { try { f.style.height = f.contentDocument.documentElement.scrollHeight + "px"; } catch {} });
  }
  async function setTab(t) {
    tab = t; store.set("pf.tab", t);
    $$(".pf-tabs button").forEach(b => { b.setAttribute("aria-pressed", b.dataset.tab === t); b.setAttribute("aria-selected", b.dataset.tab === t); });
    if (t !== "edit") await flush();  // previews show what's saved
    body();
  }

  // ---------- the editor ----------
  function field(at, f, value, inline) {
    const [k, label, ph = "", max = 0, type = "text", n = 0, hint] = f;
    const a = `${at} data-k="${k}"${type === "csv" || type === "lines" ? ` data-type="${type}" data-max="${max}" data-n="${n}"` : ""}`;
    if (type === "check") return `<label class="chk pf-check"><input type="checkbox" ${a} ${value ? "checked" : ""}>${label}</label>`;
    const val = type === "csv" ? (value || []).join(", ") : type === "lines" ? (value || []).join("\n") : value || "";
    const ml = max && type !== "csv" && type !== "lines" ? ` maxlength="${max}"` : "";
    const name = inline ? ` aria-label="${esc(label)}"` : "";
    const ctl = type === "area" || type === "lines"
      ? `<textarea ${a} rows="${type === "lines" ? 4 : 3}" placeholder="${esc(ph)}"${ml}${name}>${esc(val)}</textarea>`
      : `<input ${a} type="${type === "email" ? "email" : "text"}"${type === "url" ? ' inputmode="url" autocapitalize="none" spellcheck="false"' : ""} value="${esc(val)}" placeholder="${esc(ph)}"${ml}${name}>`;
    if (inline) return ctl;
    const wide = type === "area" || type === "lines" || type === "csv" ? " wide" : "";
    return `<label class="in${wide}"><span>${label}</span>${ctl}${hint ? `<small class="hint">${hint}</small>` : ""}</label>`;
  }
  function read(el) {
    if (el.type === "checkbox") return el.checked;
    const t = el.dataset.type;
    if (t === "csv" || t === "lines")
      return el.value.split(t === "csv" ? "," : "\n").map(s => s.trim().slice(0, +el.dataset.max)).filter(Boolean).slice(0, +el.dataset.n || 50);
    return el.value;
  }
  function item(key, x, i) {
    const L = LISTS[key], n = p[key].length, at = `data-l="${key}" data-i="${i}"`;
    const acts = `<span class="pf-acts">
      <button type="button" class="iconbtn" data-move="${key}:${i}:-1" title="Move up" aria-label="Move up" ${i ? "" : "disabled"}>${icon("up")}</button>
      <button type="button" class="iconbtn" data-move="${key}:${i}:1" title="Move down" aria-label="Move down" ${i < n - 1 ? "" : "disabled"}>${icon("down")}</button>
      <button type="button" class="iconbtn danger" data-del="${key}:${i}" title="Remove" aria-label="Remove">${icon("trash")}</button></span>`;
    if (L.inline) return `<div class="pf-row pf-row-${key}">${L.fields.map(f => field(at, f, x[f[0]], true)).join("")}${acts}</div>`;
    const sub = L.sub?.(x) || "";
    return `<details class="pf-item" data-id="${x._id}" ${openIds.has(x._id) ? "open" : ""}><summary>
      <span class="pf-item-t">${icon("chev")}<b>${esc(L.head(x) || L.untitled)}</b><small class="faint">${esc(sub)}</small></span>${acts}</summary>
      <div class="pf-grid">${L.fields.map(f => field(at, f, x[f[0]])).join("")}</div></details>`;
  }
  function section(key) {
    const L = LISTS[key], xs = p[key];
    return `<section class="card pf-sec" id="pf-${key}"><div class="pf-sec-head"><h3>${icon(L.icon)}${L.title}${xs.length ? `<span class="pf-n">${xs.length}</span>` : ""}</h3>
      <button type="button" class="btn sm" data-add="${key}" ${xs.length >= L.max ? "disabled" : ""}>${icon("plus")}${L.add}</button></div>
      <div class="pf-items">${xs.length ? xs.map((x, i) => item(key, x, i)).join("") : `<p class="pf-empty">${L.empty}</p>`}</div></section>`;
  }
  function editor() {
    return `<div class="pf-edit"><div class="pf-forms">
      <section class="card pf-sec" id="pf-basics"><div class="pf-sec-head"><h3>${icon("card")}Basics</h3></div>
        <div class="pf-grid">${BASICS.map(f => field("", f, p[f[0]])).join("")}
          ${field("", ["summary", "Summary", "AI engineer with 5 years shipping ML products. I build retrieval and agent systems, with evals that keep them honest in production.", 1500, "area", 0, "2–4 sentences: what you build, with which tools, and what it changed."], p.summary)}
          ${field("", ["languages", "Languages, comma-separated", "English (C1), Spanish (native)", 60, "csv", 10], p.languages)}</div></section>
      ${Object.keys(LISTS).map(section).join("")}</div>
      <aside class="pf-aside"><div class="card pf-strength" id="pf-strength">${strength()}</div></aside></div>`;
  }
  function strength() {
    const ok = CHECKS.map(([f]) => !!f(p)), pc = Math.round(ok.filter(Boolean).length / CHECKS.length * 100);
    return `<h3>${icon("target")}Profile strength</h3><div class="pf-meter"><b>${pc}%</b><span class="pf-bar"><i style="width:${pc}%"></i></span></div>
      <ul class="pf-checks">${CHECKS.map(([, label, sec], i) => `<li class="${ok[i] ? "ok" : ""}"><button type="button" data-jump="${sec}">${icon(ok[i] ? "check" : "plus")}${label}</button></li>`).join("")}</ul>
      <p class="fine">Recruiters skim: specific results, numbers you can stand behind, and links they can check.</p>`;
  }
  function redraw(key) { $("#pf-" + key).outerHTML = section(key); $("#pf-strength").innerHTML = strength(); }
  function add(key) {
    const x = { ...LISTS[key].blank(), _id: uid() };
    p[key].push(x); openIds.add(x._id); redraw(key); schedule();
    const rows = $$(`#pf-${key} .pf-item, #pf-${key} .pf-row`);
    rows[rows.length - 1]?.querySelector("input, textarea")?.focus();
  }
  function move(key, i, d) {
    const j = i + d, xs = p[key]; if (j < 0 || j >= xs.length) return;
    [xs[i], xs[j]] = [xs[j], xs[i]]; redraw(key); schedule();
  }
  function del(key, i) {
    const L = LISTS[key], [x] = p[key].splice(i, 1), name = L.head(x);
    redraw(key); schedule();
    UI.undoable(`Removed ${L.one}${name ? ` “${name}”` : ""}.`, () => { p[key].splice(i, 0, x); if (tab === "edit") redraw(key); schedule(); }, "Restored");
  }

  // ---------- resume and CV ----------
  function docs() {
    const pub = v.published ? `/u/${v.slug}/${doc}` : "";
    return `<div class="pf-docs"><div class="pf-ctl"><section class="card">
        <h3>${icon("doc")}Document</h3>
        <div class="seg full">${[["resume", "Resume"], ["cv", "CV"]].map(([k, l]) => `<button type="button" data-doc="${k}" aria-pressed="${doc === k}">${l}</button>`).join("")}</div>
        <p class="faint small">${doc === "cv" ? "Everything: all projects, publications, certifications and languages." : "One or two pages: summary, experience, featured projects, skills and education."}</p>
        <h3>${icon("layers")}Template</h3>
        <div class="pf-tpls">${Object.entries(v.templates).map(([k, t]) => `<button type="button" class="pf-tpl" data-set="template" data-v="${k}" aria-pressed="${p.template === k}">
          <span class="pf-tpl-pic ${k}" aria-hidden="true"><i></i><i></i><i></i><i></i></span><span><b>${esc(t.label)}</b><small>${esc(t.hint)}</small></span></button>`).join("")}</div>
        <div class="pf-dl"><button type="button" class="btn primary" data-pf="print">${icon("download")}Download PDF</button>
          <a class="btn" href="/api/profile/download/${doc}" download title="A standalone page you can host or email">${icon("file")}HTML</a></div>
        <p class="fine">In the print dialog pick “Save as PDF” and turn off headers and footers.</p>
        ${pub ? `<p class="small pf-pub">${icon("globe")}<a href="${esc(pub)}" target="_blank" rel="noopener">${esc(location.host + pub)}</a></p>` : ""}
      </section></div>
      <div class="pf-paper"><iframe id="pf-frame" title="${doc === "cv" ? "CV" : "Resume"} preview" src="/api/profile/preview/${doc}"></iframe></div></div>`;
  }
  async function print() {
    await flush();
    const f = $("#pf-frame"); if (!f) return;
    if (f.contentDocument?.readyState !== "complete") await new Promise(r => f.addEventListener("load", r, { once: true }));
    f.contentWindow.focus(); f.contentWindow.print();
  }

  // ---------- the website ----------
  function site() {
    const th = v.themes[p.theme] || Object.values(v.themes)[0], live = v.netlify.site?.url;
    const addr = `${location.host}/u/`;
    return `<div class="pf-site"><div class="pf-ctl">
      <section class="card"><h3>${icon("palette")}Look</h3>
        <div class="pf-themes">${Object.entries(v.themes).map(([k, t]) => `<button type="button" class="pf-theme" data-set="theme" data-v="${k}" aria-pressed="${p.theme === k}" style="--tb:${t.bg};--tt:${t.text};--ta:${t.accent}">
          <span class="pf-theme-pic" aria-hidden="true"><i></i><i></i><i></i></span><b>${esc(t.label)}</b></button>`).join("")}</div>
        <div class="pf-accent"><label class="pf-color" style="--c:${esc(p.accent || th.accent)}"><input type="color" data-set="accent" value="${esc(p.accent || th.accent)}" aria-label="Accent colour"></label>
          <span><b>Accent colour</b><small class="faint">${p.accent ? "Your own" : "The theme's"}; resumes use a darker shade so it prints well.</small></span>
          ${p.accent ? `<button type="button" class="btn sm" data-set="accent" data-v="">Reset</button>` : ""}</div>
        <label class="pf-switch"><span><b>Show email and phone</b><small class="faint">On the public site, its resume and CV, and Netlify. Downloads from here always include them.</small></span>
          <span class="switch"><input type="checkbox" data-set="public_contact" ${p.public_contact ? "checked" : ""}><span></span></span></label>
      </section>
      <section class="card"><h3>${icon("globe")}Publish on AXoR</h3>
        <label class="pf-switch"><span><b>${v.published ? "Published" : "Not published"}</b><small class="faint">Anyone with the link can see it, without signing in.</small></span>
          <span class="switch"><input type="checkbox" id="pf-pub" ${v.published ? "checked" : ""}><span></span></span></label>
        <label class="in"><span>Address</span><span class="pf-addr"><span>${esc(addr)}</span><input id="pf-slug" value="${esc(v.slug)}" maxlength="40" autocapitalize="none" spellcheck="false"></span></label>
        ${v.published ? `<div class="row"><a class="btn sm" href="/u/${esc(v.slug)}" target="_blank" rel="noopener">${icon("external")}Open</a><button type="button" class="btn sm" data-pf="copy">${icon("copy")}Copy link</button></div>` : ""}
      </section>
      <section class="card"><h3>${icon("rocket")}Deploy to Netlify</h3>${netlify()}</section>
      <section class="card"><h3>${icon("download")}Any static host</h3>
        <p class="faint small">The same site as files: unzip and drop the folder on Netlify Drop, or upload it to Cloudflare Pages, GitHub Pages or any web server.</p>
        <a class="btn" href="/api/profile/site.zip" download>${icon("download")}Download site (.zip)</a></section>
    </div>
    <div class="pf-browser"><div class="pf-chrome"><span class="pf-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="pf-url">${icon("lock")}${esc(live ? bare(live) : addr + v.slug)}</span><span class="faint small">Preview</span></div>
      <iframe id="pf-frame" title="Website preview" src="/api/profile/preview/site"></iframe></div></div>`;
  }
  function netlify() {
    const n = v.netlify, s = n.site;
    if (!n.token) return `<p class="faint small">Deploy the site to your own Netlify account, at <i>name</i>.netlify.app or your own domain. In Netlify, create a token under User settings → Applications →
        <a href="https://app.netlify.com/user/applications#personal-access-tokens" target="_blank" rel="noopener noreferrer">Personal access tokens</a> and paste it here. It's stored encrypted and only used to deploy this site.</p>
      <form class="pf-token" id="pf-token" novalidate><input type="password" name="token" placeholder="nfp_…" autocomplete="off" aria-label="Netlify personal access token" required><button class="btn primary" type="submit">Connect</button></form>`;
    return `<div class="pf-nl"><span class="badge clear">${icon("check")}Connected</span><code>${esc(n.token)}</code><button type="button" class="btn sm" data-pf="nl-off">Disconnect</button></div>
      ${s?.url ? `<div class="pf-live"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer"><b>${esc(bare(s.url))}</b>${icon("external")}</a>
          <small class="faint">Deployed ${esc(new Date(s.deployed * 1000).toLocaleString())}${s.state && s.state !== "ready" ? ` · ${esc(s.state)}` : ""}${s.admin_url ? ` · <a href="${esc(s.admin_url)}" target="_blank" rel="noopener noreferrer">Netlify dashboard</a>` : ""}</small></div>`
        : `<label class="in"><span>Site name <em class="opt">optional</em></span><span class="pf-addr"><input id="pf-nl-name" maxlength="63" placeholder="ada-ai" autocapitalize="none" spellcheck="false"><span>.netlify.app</span></span></label>`}
      <button type="button" class="btn primary" data-pf="deploy">${icon("rocket")}${s ? "Deploy again" : "Deploy"}</button>`;
  }
  async function set(k, val) {
    p[k] = val; dirty = true;
    await flush();
    body();
  }
  async function publish(on, el) {
    await flush();
    try {
      adopt(await api("/api/profile/publish", { method: "PUT", body: { published: on, slug: $("#pf-slug").value.trim().toLowerCase() } }));
    } catch (e) { UI.toast(e.message); if (el.type === "checkbox") el.checked = !on; return; }
    UI.toast(on ? `Your site is live at ${location.host}/u/${v.slug}` : "Your site is offline.", { kind: "success" });
    render();
  }
  async function connect(form) {
    const t = form.elements.token.value.trim(); if (!t) return form.elements.token.focus();
    try { adopt(await api("/api/profile/netlify/token", { method: "PUT", body: { token: t } })); }
    catch (e) { return UI.toast(e.message); }
    UI.toast("Netlify connected.", { kind: "success" }); body();
  }
  async function deploy() {
    await flush();
    try { adopt(await api("/api/profile/netlify/deploy", { method: "POST", body: { name: $("#pf-nl-name")?.value.trim() || "" } })); }
    catch (e) { return UI.toast(e.message); }
    UI.toast(`Deployed to ${bare(v.netlify.site?.url)}`, { kind: "success" }); render();
  }
  async function disconnect() {
    await UI.confirm({ title: "Disconnect Netlify?", body: "AXoR forgets your token and the link to your Netlify site. The site stays online on Netlify; delete it there if you want it gone.",
      ok: "Disconnect", icon: "logout", run: async () => adopt(await api("/api/profile/netlify/token", { method: "DELETE" })) }) && body();
  }

  // ---------- AI review ----------
  async function review() {
    if (!v.ai) return UI.toast("AI review needs agents, which aren't set up on this server.");
    await flush();
    Auth.modal(`<h3>${icon("sparkle")}AI review</h3>
      <p class="muted">Stronger, impact-first wording for your headline, summary and role highlights. Paste a job post to tailor it and see which keywords you're missing. Your facts stay yours: nothing changes until you apply it.</p>
      <label class="in"><span>Job description <em class="opt">optional</em></span><textarea name="job" rows="8" maxlength="8000" placeholder="Paste the job post here…"></textarea></label>
      <p class="fine">Uses your agents' model (Auto unless changed in the Agents tab).</p>`, async f => {
      const r = await api("/api/profile/ai", { method: "POST", body: { job: f.elements.job.value, model: Chat.chosen() } });
      suggestions(r);
    }, { submit: "Review" });
    wide();
  }
  function wide() { const d = $("#modal"); d.classList.add("pf-wide"); d.addEventListener("close", () => d.classList.remove("pf-wide"), { once: true }); }
  function suggestions(r) {
    $("#modal").close();
    const rows = [];
    if (r.headline && r.headline !== p.headline) rows.push({ k: "headline", label: "Headline", was: p.headline, now: r.headline });
    if (r.summary && r.summary !== p.summary) rows.push({ k: "summary", label: "Summary", was: p.summary, now: r.summary });
    for (const x of r.experience) {
      const j = p.experience[x.index];
      if (j && x.bullets.join("\n") !== j.bullets.join("\n")) rows.push({ k: "exp" + x.index, i: x.index, label: [j.title, j.company].filter(Boolean).join(" · ") || "Role", was: j.bullets, now: x.bullets });
    }
    const show = s => Array.isArray(s) ? (s.length ? `<ul>${s.map(b => `<li>${esc(b)}</li>`).join("")}</ul>` : `<p class="faint">Nothing yet</p>`) : s ? `<p>${esc(s)}</p>` : `<p class="faint">Nothing yet</p>`;
    Auth.modal(`<h3>${icon("sparkle")}Suggestions</h3>
      <p class="muted">${rows.length ? "Tick what to apply. You can still edit everything afterwards." : "No wording changes this time."}</p>
      ${rows.length ? `<div class="pf-sugs">${rows.map(x => `<label class="pf-sug"><input type="checkbox" name="${x.k}" checked><span><b>${esc(x.label)}</b>
        <span class="pf-diff"><span><small>Now</small>${show(x.was)}</span><span><small>Suggested</small>${show(x.now)}</span></span></span></label>`).join("")}</div>` : ""}
      ${r.keywords.length ? `<div class="field"><span class="lbl">Keywords to add where they're true</span><div class="chips">${r.keywords.map(k => `<span class="tag">${esc(k)}</span>`).join("")}</div></div>` : ""}
      ${r.tips.length ? `<div class="field"><span class="lbl">Tips</span><ul class="pf-tips">${r.tips.map(t => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}`, async f => {
      let n = 0;
      for (const x of rows) if (f.elements[x.k]?.checked) { n++; if (x.i != null) p.experience[x.i].bullets = x.now; else p[x.k] = x.now; }
      $("#modal").close();
      if (!n) return;
      dirty = true; await flush(); body();
      UI.toast(`Applied ${n} suggestion${n === 1 ? "" : "s"}.`, { kind: "success" });
    }, { submit: rows.length ? "Apply selected" : "Close" });
    wide();
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    const r = root();
    r.addEventListener("input", e => {
      const el = e.target;
      if (el.type === "color") { el.parentElement.style.setProperty("--c", el.value); return; }  // saved on change
      if (!el.matches("[data-k]")) return;
      const val = read(el);
      if (el.dataset.l) {
        const L = LISTS[el.dataset.l], x = p[el.dataset.l][+el.dataset.i]; x[el.dataset.k] = val;
        const s = el.closest("details")?.querySelector(".pf-item-t");
        if (s) { $("b", s).textContent = L.head(x) || L.untitled; $("small", s).textContent = L.sub?.(x) || ""; }
      } else p[el.dataset.k] = val;
      $("#pf-strength").innerHTML = strength();
      schedule();
    });
    r.addEventListener("change", e => {
      const el = e.target;
      if (el.matches("input[data-set]")) return set(el.dataset.set, el.type === "checkbox" ? el.checked : el.value);
      if (el.id === "pf-pub") return publish(el.checked, el);
      if (el.id === "pf-slug" && v.published) return publish(true, el);
    });
    r.addEventListener("click", e => {
      const t = e.target.closest("button"); if (!t || t.disabled) return;
      const d = t.dataset;
      if (d.tab) return setTab(d.tab);
      if (d.doc) { doc = d.doc; store.set("pf.doc", doc); return body(); }
      if (d.set) return set(d.set, d.v);
      if (d.add) return add(d.add);
      if (d.move) { e.preventDefault(); const [k, i, s] = d.move.split(":"); return move(k, +i, +s); }
      if (d.del) { e.preventDefault(); const [k, i] = d.del.split(":"); return del(k, +i); }
      if (d.jump) {
        const go = () => { const s = $("#pf-" + d.jump); s?.scrollIntoView({ behavior: "smooth", block: "start" }); s?.querySelector("input, textarea")?.focus({ preventScroll: true }); };
        return tab === "edit" ? go() : setTab("edit").then(go);
      }
      if (d.pf === "ai") review();
      if (d.pf === "print") print();
      if (d.pf === "deploy") deploy();
      if (d.pf === "nl-off") disconnect();
      if (d.pf === "copy") navigator.clipboard.writeText(`${location.origin}/u/${v.slug}`).then(() => UI.toast("Link copied.", { kind: "success" }), () => UI.toast("Couldn't copy the link."));
    });
    r.addEventListener("submit", e => { if (e.target.id === "pf-token") { e.preventDefault(); connect(e.target); } });
    r.addEventListener("toggle", e => { const x = e.target; if (x.matches?.("details.pf-item")) x.open ? openIds.add(x.dataset.id) : openIds.delete(x.dataset.id); }, true);
    // closing the tab mid-edit: send what's pending without waiting for the debounce
    addEventListener("pagehide", () => {
      if (!dirty || !p) return;
      fetch("/api/profile", { method: "PUT", keepalive: true, credentials: "same-origin",
        headers: { "X-Requested-With": "scout", "Content-Type": "application/json" }, body: JSON.stringify(clean()) }).catch(() => {});
    });
  }

  return { init, open };
})();
