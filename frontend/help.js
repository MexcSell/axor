/* Help: AXoR's documentation (helpdocs.py). The home page searches everything; a doc page has the library on the left,
   the doc in the middle and "On this page" on the right. Docs are Markdown from /api/help, rendered here by a small,
   safe renderer: text is escaped first, then headings (with anchors), lists, tables, callouts (> [!NOTE], [!TIP],
   [!WARNING]), code blocks with Copy, **bold**, *italic*, `code`, [[keys]] and links (https, mailto, and #view or
   #help/<doc> links inside AXoR). The API reference is built from /api/help/api: every endpoint you may call, with
   its access level, parameters, body fields, a curl example and, for GET, Try it. Links: #help, #help/<doc>,
   #help/<doc>/<heading>; reading moves through browser history, so Back returns to the last doc. Press / to search. */
const Help = (() => {
  let lib = null, ref = null, slug = "", anchor = "", wired = false, spy = null, results = [], sel = -1;
  const API = "api-reference";
  const ACCESS = { public: ["No sign-in", "Anyone can call it"], user: ["Signed in", "Any signed-in account"],
    admin: ["Admin", "Administrators only"], sudo: ["Admin + sudo", "Administrators who confirmed it's them in the last 10 minutes"] };
  const slugify = t => String(t).toLowerCase().replace(/<[^>]+>/g, "").replace(/&[a-z]+;/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "section";
  const docOf = s => lib?.docs.find(d => d.slug === s);
  const sectionOf = id => lib?.sections.find(s => s.id === id);
  const viewOk = v => { const b = $(`nav.side [data-view="${v}"]`); return b && !b.hidden; };

  // ---------- Markdown ----------
  function inline(t) {
    const codes = [];
    let s = esc(t).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    s = s.replace(/\[\[([^\]]+)\]\]/g, "<kbd>$1</kbd>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*\w])\*([^*\s](?:[^*]*[^*\s])?)\*(?!\w)/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:|#)[^\s)]*)\)/g, (_, label, href) => href.startsWith("#")
        ? `<a href="${href}" data-hp-link>${label}</a>` : `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}${icon("external", "hp-ext")}</a>`);
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
  }
  function md(text, toc = [], ids = new Set()) {
    const lines = String(text || "").replace(/\r/g, "").split("\n"), out = [];
    let i = 0, para = [];
    const flush = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
    const uid = t => { let id = slugify(t), n = 2; while (ids.has(id)) id = `${slugify(t)}-${n++}`; ids.add(id); return id; };
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^```\s*([\w+#.-]*)/);
      if (fence) {
        flush(); const body = []; i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++]);
        i++;
        out.push(`<div class="hp-code"><button type="button" class="hp-copy" data-hp-copy title="Copy">${icon("copy")}<span>Copy</span></button><pre data-lang="${esc(fence[1])}"><code>${esc(body.join("\n"))}</code></pre></div>`);
        continue;
      }
      const h = line.match(/^(#{2,4})\s+(.*)/);
      if (h) {
        flush(); const lvl = h[1].length, id = uid(h[2]);
        if (lvl <= 3) toc.push({ id, text: h[2].replace(/[`*]/g, ""), lvl });
        out.push(`<h${lvl} id="hp-${id}">${inline(h[2])}<a class="hp-anchor" href="#help/${esc(slug)}/${id}" data-hp-link aria-label="Link to this section">#</a></h${lvl}>`);
        i++; continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || "")) {
        flush();
        const cells = l => l.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
        const head = cells(line), rows = []; i += 2;
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
        out.push(`<div class="hp-table"><table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if (/^\s*>/.test(line)) {
        flush(); const body = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
        const kind = (body[0].match(/^\[!(NOTE|TIP|WARNING|IMPORTANT)\]/i) || [])[1]?.toLowerCase();
        if (kind) body.shift();
        const label = { note: "Note", tip: "Tip", warning: "Warning", important: "Important" }[kind];
        const ic = { note: "info", tip: "bulb", warning: "alert", important: "shield" }[kind] || "info";
        out.push(`<div class="hp-callout ${kind || "quote"}">${kind ? `<b class="hp-callout-t">${icon(ic)}${label}</b>` : ""}${md(body.join("\n"), [], ids)}</div>`);
        continue;
      }
      const li = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)/);
      if (li) {
        flush();
        const tag = /\d/.test(li[2]) ? "ol" : "ul", items = [];
        while (i < lines.length) {
          const m = lines[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)/);
          if (m && m[1].length < 2) { items.push({ text: m[3], sub: [] }); i++; continue; }
          if (m && items.length) { items.at(-1).sub.push({ text: m[3], tag: /\d/.test(m[2]) ? "ol" : "ul" }); i++; continue; }
          if (/^\s{2,}\S/.test(lines[i]) && items.length) { const last = items.at(-1); (last.sub.length ? last.sub.at(-1) : last).text += " " + lines[i].trim(); i++; continue; }
          break;
        }
        const task = t => t.replace(/^\[( |x|X)\]\s+/, (_, x) => `<span class="hp-task${x.trim() ? " on" : ""}" aria-hidden="true">${x.trim() ? icon("check") : ""}</span>`);
        out.push(`<${tag}>${items.map(it => `<li${/^\[( |x|X)\]\s/.test(it.text) ? ' class="hp-li-task"' : ""}>${task(inline(it.text))}${it.sub.length ? `<${it.sub[0].tag}>${it.sub.map(s => `<li>${inline(s.text)}</li>`).join("")}</${it.sub[0].tag}>` : ""}</li>`).join("")}</${tag}>`);
        continue;
      }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
      if (!line.trim()) { flush(); i++; continue; }
      para.push(line.trim()); i++;
    }
    flush();
    return out.join("");
  }
  const plain = t => String(t || "").replace(/```[\s\S]*?```/g, " ").replace(/[#>*`|[\]()_-]+/g, " ").replace(/\s+/g, " ");

  // ---------- search ----------
  let idx = null;  // the search index, rebuilt once the API reference arrives
  function index() {
    if (idx) return idx;
    const items = (lib?.docs || []).map(d => ({ kind: "doc", slug: d.slug, title: d.title, section: sectionOf(d.section)?.title || "", summary: d.summary,
      heads: [...d.text.matchAll(/^#{2,3}\s+(.*)$/gm)].map(m => m[1].replace(/[`*]/g, "")), body: plain(d.text) }));
    for (const g of ref?.groups || []) for (const e of g.endpoints)
      items.push({ kind: "api", slug: API, anchor: "api-" + g.id, title: `${e.method} ${e.path}`, section: `API reference · ${g.title}`, summary: e.summary, heads: [], body: g.blurb });
    if (ref) idx = items;
    return items;
  }
  function search(q) {
    const terms = q.toLowerCase().split(/\s+/).filter(t => t.length > 1 || /\d/.test(t));
    if (!terms.length) return [];
    return index().map(it => {
      let score = 0, head = null;
      for (const t of terms) {
        const inTitle = it.title.toLowerCase().includes(t), h = it.heads.find(x => x.toLowerCase().includes(t)), n = (it.body.toLowerCase().split(t).length - 1);
        if (!inTitle && !h && !n && !it.summary.toLowerCase().includes(t)) return null;  // every word must appear somewhere
        score += (inTitle ? 10 : 0) + (h ? 5 : 0) + (it.summary.toLowerCase().includes(t) ? 3 : 0) + Math.min(n, 5);
        if (h && !head) head = h;
      }
      if (it.kind === "api") score -= 2;  // docs first, endpoints after
      const at = it.body.toLowerCase().indexOf(terms[0]);
      const snip = it.summary || (at >= 0 ? (at > 60 ? "…" : "") + it.body.slice(Math.max(0, at - 60), at + 120) + "…" : "");
      return { ...it, score, head, snip };
    }).filter(Boolean).sort((a, b) => b.score - a.score).slice(0, 8);
  }
  const mark = (text, q) => { let s = esc(text); for (const t of q.toLowerCase().split(/\s+/).filter(x => x.length > 1)) s = s.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>"); return s; };
  function showResults(input) {
    const box = input.closest(".hp-search").querySelector(".hp-results"), q = input.value.trim();
    results = q ? search(q) : []; sel = results.length ? 0 : -1;
    box.hidden = !q;
    box.innerHTML = results.length ? results.map((r, i) => `<button type="button" class="hp-result" data-hp-go="${esc(r.slug)}" data-hp-anchor="${esc(r.anchor || (r.head ? slugify(r.head) : ""))}" aria-selected="${i === sel}">
        <span class="hp-r-sec">${esc(r.section)}</span><b>${r.kind === "api" ? `<code>${mark(r.title, q)}</code>` : mark(r.title, q)}${r.head ? ` <span class="faint">› ${mark(r.head, q)}</span>` : ""}</b>
        ${r.snip ? `<span class="hp-r-snip">${mark(r.snip, q)}</span>` : ""}</button>`).join("")
      : `<div class="hp-noresult">Nothing matches “${esc(q)}”. Try fewer words, or ask Assist.</div>`;
  }
  const searchBox = (big = false) => `<div class="hp-search${big ? " big" : ""}"><span class="hp-s-ic">${icon("search")}</span>
    <input type="search" placeholder="Search the docs${ref ? " and the API" : ""}…" aria-label="Search the docs" autocomplete="off" spellcheck="false"><kbd>/</kbd>
    <div class="hp-results" hidden role="listbox"></div></div>`;

  // ---------- pages ----------
  async function open() {
    wire();
    if (!lib) {
      $("#help").innerHTML = `<div class="hp-home"><section class="hp-hero">${Loading.line("Loading the docs…")}</section></div>`;
      try { lib = await api("/api/help"); } catch (e) { $("#help").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
      api("/api/help/api").then(r => { ref = r; if (slug === API) render(); }).catch(() => {});
    }
    render();
  }
  function route(path) {  // "help", "help/<doc>" or "help/<doc>/<heading>"
    const [, s = "", a = ""] = String(path || "").split("/");
    slug = s === API || docOf(s) || !lib ? s : ""; anchor = a;
  }
  function go(s, a = "", push = true) {
    slug = s; anchor = a;
    const hash = "#help" + (s ? "/" + s : "") + (a ? "/" + a : "");
    if (push && location.hash !== hash) history.pushState(null, "", hash);
    if (S.view !== "help") setView("help"); else render();
  }
  function render() {
    spy?.disconnect();
    const root = $("#help");
    if (slug && slug !== API && !docOf(slug)) slug = "";
    if (!slug) { root.innerHTML = home(); history.replaceState(null, "", "#help"); return; }
    const toc = [];
    const body = slug === API ? reference(toc) : doc(docOf(slug), toc);
    root.innerHTML = `<div class="hp">
      <aside class="hp-side" aria-label="Help">${searchBox()}<details class="hp-browse" open><summary>Browse the docs</summary>${library()}</details></aside>
      <article class="hp-main">${body}</article>
      <aside class="hp-toc" aria-label="On this page">${toc.length ? `<b>On this page</b><nav>${toc.map(t => `<a href="#help/${esc(slug)}/${t.id}" data-hp-link data-hp-toc="${t.id}" class="l${t.lvl}">${esc(t.text)}</a>`).join("")}</nav>` : ""}</aside>
    </div>`;
    if (innerWidth < 900) $(".hp-browse", root).open = false;
    history.replaceState(null, "", "#help/" + slug + (anchor ? "/" + anchor : ""));
    const target = anchor && document.getElementById("hp-" + anchor);
    if (target) target.scrollIntoView({ block: "start" }); else $("#view-help").scrollIntoView({ block: "start" });
    watchToc(root);
  }
  function home() {
    const quick = ["welcome", "account", "first-subnet", "api-overview"].map(docOf).filter(Boolean);
    return `<div class="hp-home">
      <section class="hp-hero">
        <span class="hp-eyebrow">${icon("help")}AXoR Help Center</span>
        <h1>How can we help?</h1>
        <p class="hp-lead">Guides for every page, administration, the API and building on AXoR.</p>
        ${searchBox(true)}
        ${quick.length ? `<div class="hp-quick"><span class="faint">Popular:</span>${quick.map(d => `<button type="button" class="chip" data-hp-go="${esc(d.slug)}">${esc(d.title)}</button>`).join("")}</div>` : ""}
      </section>
      <div class="hp-cards">${lib.sections.map(s => {
        const docs = lib.docs.filter(d => d.section === s.id);
        return `<section class="hp-card">
          <span class="hp-card-ic">${icon(s.icon)}</span><h2>${esc(s.title)}</h2><p>${esc(s.line)}</p>
          <ul>${docs.map(d => `<li><button type="button" class="link" data-hp-go="${esc(d.slug)}">${esc(d.title)}</button></li>`).join("")}
            ${s.id === "api" ? `<li><button type="button" class="link" data-hp-go="${API}">API reference</button></li>` : ""}</ul></section>`;
      }).join("")}</div>
      <section class="hp-band"><div><h2>Still stuck?</h2><p>Open <b>Assist</b> in the top bar: the agent beside every page knows AXoR's pages and can look things up for you.${lib.admin ? "" : " For your account or access, ask an administrator."}</p></div></section>
    </div>`;
  }
  function library() {
    return `<nav class="hp-lib"><button type="button" class="hp-l" data-hp-go="">${icon("help")}Help home</button>
      ${lib.sections.map(s => `<div class="hp-group">${esc(s.title)}</div>
        ${lib.docs.filter(d => d.section === s.id).map(d => `<button type="button" class="hp-l" data-hp-go="${esc(d.slug)}" aria-current="${d.slug === slug ? "page" : "false"}">${esc(d.title)}</button>`).join("")}
        ${s.id === "api" ? `<button type="button" class="hp-l" data-hp-go="${API}" aria-current="${slug === API ? "page" : "false"}">API reference</button>` : ""}`).join("")}</nav>`;
  }
  function pager(cur) {
    const list = [...lib.docs.map(d => d.slug)];
    const ai = list.indexOf("api-overview"); if (ai >= 0) list.splice(ai + 1, 0, API);
    const i = list.indexOf(cur), title = s => s === API ? "API reference" : docOf(s)?.title;
    const prev = list[i - 1], next = list[i + 1];
    return `<nav class="hp-pager">${prev ? `<button type="button" data-hp-go="${esc(prev)}"><small>Previous</small><b>${icon("left")}${esc(title(prev))}</b></button>` : "<span></span>"}
      ${next ? `<button type="button" class="next" data-hp-go="${esc(next)}"><small>Next</small><b>${esc(title(next))}${icon("right")}</b></button>` : ""}</nav>`;
  }
  function doc(d, toc) {
    const sec = sectionOf(d.section);
    return `<div class="hp-crumbs"><button type="button" class="link" data-hp-go="">Help</button>${icon("chev")}<span>${esc(sec?.title || "")}</span>
        ${d.audience === "admin" ? `<span class="hp-badge">${icon("shield")}Admins</span>` : ""}</div>
      <h1 class="hp-title">${esc(d.title)}</h1>${d.summary ? `<p class="hp-lead">${esc(d.summary)}</p>` : ""}
      <div class="hp-doc">${md(d.text, toc)}</div>${pager(d.slug)}`;
  }

  // ---------- API reference ----------
  const path = p => esc(p).replace(/\{(\w+)(:\w+)?\}/g, "<em>{$1}</em>");
  function example(f) {
    if (f.default !== undefined && f.default !== null) return f.default;
    const t = f.type || "";
    if (t.includes(" | ")) return t.split(" | ")[0];
    if (t.startsWith("array")) return [];
    if (/^(integer|number)/.test(t)) return 0;
    if (t.startsWith("boolean")) return false;
    if (t === "object") return {};
    return t.startsWith("string") ? "…" : null;
  }
  function curl(e) {
    const q = e.params.filter(p => p.in === "query" && p.required).map(p => `${p.name}=…`).join("&");
    const url = `${location.origin}${e.path}${q ? "?" + q : ""}`;
    const lines = [`curl -s -b cookies.txt${e.method !== "GET" ? ` -X ${e.method}` : ""} '${url}'`];
    if (e.method !== "GET") lines.push(`  -H 'X-Requested-With: scout'`);
    if (e.body) {
      const body = Object.fromEntries(e.body.fields.filter(f => f.required || e.body.fields.length <= 6).map(f => [f.name, example(f)]));
      lines.push(`  -H 'Content-Type: application/json'`, `  -d '${JSON.stringify(body).replace(/'/g, "'\\''")}'`);
    }
    return lines.join(" \\\n");
  }
  function fieldRows(rows, where = true) {
    return `<div class="hp-table"><table><thead><tr><th>Name</th>${where ? "<th>In</th>" : ""}<th>Type</th><th>Required</th><th>Notes</th></tr></thead><tbody>${rows.map(f => {
      const notes = [f.default !== undefined && f.default !== null && f.default !== "" ? `default <code>${esc(JSON.stringify(f.default))}</code>` : "",
        f.maxLength ? `up to ${f.maxLength} characters` : "", f.maximum != null ? `at most ${f.maximum}` : "", f.minimum != null ? `at least ${f.minimum}` : "", f.description ? esc(f.description) : ""].filter(Boolean).join(" · ");
      return `<tr><td><code>${esc(f.name)}</code></td>${where ? `<td>${esc(f.in)}</td>` : ""}<td><span class="hp-type">${esc(f.type)}</span></td><td>${f.required ? "yes" : ""}</td><td>${notes}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  }
  function endpoint(e, gid, n) {
    const acc = ACCESS[e.access] || ["", ""], id = `${gid}-${n}`;
    const tryable = e.method === "GET" && !e.stream;
    return `<details class="hp-ep" data-path="${esc((e.method + " " + e.path).toLowerCase())}" data-method="${esc(e.method)}">
      <summary><span class="hp-m m-${esc(e.method.toLowerCase())}">${esc(e.method)}</span><code class="hp-path">${path(e.path)}</code>
        <span class="hp-acc a-${esc(e.access)}" title="${esc(acc[1])}">${esc(acc[0])}</span>${e.summary ? `<span class="hp-sum">${esc(e.summary)}</span>` : ""}</summary>
      <div class="hp-ep-body">
        ${e.stream ? `<p class="faint small">${e.method === "WS" ? "A WebSocket." : "A stream (server-sent events or a download)"}: open it from a client rather than here.</p>` : ""}
        ${e.params.length ? `<h4>Parameters</h4>${fieldRows(e.params)}` : ""}
        ${e.body ? `<h4>Body <span class="faint">JSON · ${esc(e.body.type)}</span></h4>${e.body.fields.length ? fieldRows(e.body.fields, false) : `<p class="faint small">Any JSON value.</p>`}` : ""}
        ${e.method !== "WS" ? `<h4>Example</h4><div class="hp-code"><button type="button" class="hp-copy" data-hp-copy title="Copy">${icon("copy")}<span>Copy</span></button><pre data-lang="bash"><code>${esc(curl(e))}</code></pre></div>` : ""}
        ${tryable ? `<form class="hp-try" data-hp-try="${esc(e.path)}" novalidate><h4>Try it <span class="faint">as you, on this server</span></h4>
          <div class="hp-try-in">${e.params.filter(p => p.in === "path" || p.in === "query").map(p => `<label class="in"><span><code>${esc(p.name)}</code> ${p.in}${p.required ? " · required" : ""}</span>
            <input name="${esc(p.name)}" data-in="${esc(p.in)}" ${p.required ? "required" : ""} placeholder="${esc(p.default !== undefined ? String(p.default) : p.type)}" autocomplete="off" spellcheck="false"></label>`).join("")}</div>
          <button class="btn primary sm" type="submit">${icon("play")}Send</button><output class="hp-out" id="hp-out-${id}" hidden></output></form>` : ""}
      </div></details>`;
  }
  function reference(toc) {
    if (!ref) return `<h1 class="hp-title">API reference</h1>${Loading.line("Reading the routes…")}`;
    for (const g of ref.groups) toc.push({ id: "api-" + g.id, text: g.title, lvl: 2 });
    const n = ref.groups.reduce((a, g) => a + g.endpoints.length, 0);
    return `<div class="hp-crumbs"><button type="button" class="link" data-hp-go="">Help</button>${icon("chev")}<span>API</span></div>
      <h1 class="hp-title">API reference</h1>
      <p class="hp-lead">${n} endpoints ${ref.admin ? "on this server" : "you can call"}, read from the running server, so this page always matches the code. Start with the <a href="#help/api-overview" data-hp-link>API overview</a> for signing in, the CSRF header and errors.</p>
      <div class="hp-legend">${Object.entries(ACCESS).filter(([k]) => ref.admin || k === "public" || k === "user").map(([k, [l, t]]) => `<span><span class="hp-acc a-${k}">${l}</span> ${esc(t)}</span>`).join("")}</div>
      <div class="hp-api-tools"><div class="search">${icon("search")}<input type="search" class="hp-filter" placeholder="Filter by path, e.g. wallet/quote" autocomplete="off"></div>
        <div class="seg hp-methods">${["All", "GET", "POST", "PUT", "PATCH", "DELETE"].map(m => `<button type="button" data-hp-method="${m}" aria-pressed="${m === "All"}">${m}</button>`).join("")}</div></div>
      ${ref.groups.map(g => `<section class="hp-api-group" id="hp-api-${esc(g.id)}"><h2>${esc(g.title)}<a class="hp-anchor" href="#help/${API}/api-${esc(g.id)}" data-hp-link aria-label="Link to this group">#</a></h2>
        ${g.blurb ? `<p class="muted">${esc(g.blurb)}</p>` : ""}${g.endpoints.map((e, i) => endpoint(e, g.id, i)).join("")}</section>`).join("")}
      ${pager(API)}`;
  }
  function filterRef(root) {
    const q = ($(".hp-filter", root)?.value || "").trim().toLowerCase(), m = $(".hp-methods [aria-pressed=true]", root)?.dataset.hpMethod || "All";
    $$(".hp-api-group", root).forEach(g => {
      let any = false;
      $$(".hp-ep", g).forEach(e => { const ok = (!q || e.dataset.path.includes(q)) && (m === "All" || e.dataset.method === m); e.hidden = !ok; any ||= ok; });
      g.hidden = !any;
    });
  }
  async function tryIt(f) {
    const out = $("output", f), params = new URLSearchParams();
    let p = f.dataset.hpTry, missing = null;
    for (const inp of $$("input", f)) {
      const v = inp.value.trim();
      if (!v && inp.required) { missing ||= inp; continue; }
      if (inp.dataset.in === "path") p = p.replace(new RegExp(`\\{${inp.name}(:\\w+)?\\}`), encodeURIComponent(v));
      else if (v) params.set(inp.name, v);
    }
    out.hidden = false;
    if (missing) { out.innerHTML = `<span class="hp-st bad">Fill in ${esc(missing.name)} first.</span>`; missing.focus(); return; }
    const url = p + (params.toString() ? "?" + params : ""), t0 = performance.now(), ctl = new AbortController(), stop = setTimeout(() => ctl.abort(), 20000);
    out.innerHTML = Loading.line(`GET ${esc(url)}`);
    try {
      const res = await fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "scout" }, signal: ctl.signal });
      const text = await res.text(), ms = Math.round(performance.now() - t0);
      let body = text; try { body = JSON.stringify(JSON.parse(text), null, 2); } catch {}
      const cut = body.length > 60000;
      out.innerHTML = `<span class="hp-st ${res.ok ? "ok" : "bad"}">${res.status} ${esc(res.statusText)}</span><span class="faint small"> · ${ms} ms · ${(text.length / 1024).toFixed(1)} KB · <code>GET ${esc(url)}</code></span>
        <pre><code>${esc(cut ? body.slice(0, 60000) + "\n… (cut at 60,000 characters)" : body)}</code></pre>`;
    } catch (e) { out.innerHTML = `<span class="hp-st bad">${e.name === "AbortError" ? "No answer within 20 seconds." : esc(e.message)}</span>`; }
    finally { clearTimeout(stop); }
  }

  // ---------- behaviour ----------
  function watchToc(root) {
    const links = $$("[data-hp-toc]", root);
    if (!links.length || !("IntersectionObserver" in window)) return;
    const heads = links.map(a => document.getElementById("hp-" + a.dataset.hpToc)).filter(Boolean);
    spy = new IntersectionObserver(es => {
      const vis = es.filter(x => x.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (vis) links.forEach(a => a.classList.toggle("on", "hp-" + a.dataset.hpToc === vis.target.id));
    }, { rootMargin: "-70px 0px -65% 0px" });
    heads.forEach(h => spy.observe(h));
  }
  function follow(href) {
    const h = href.replace(/^#/, "");
    if (h === "help" || h.startsWith("help/")) { const [, s = "", a = ""] = h.split("/"); go(s, a); return true; }
    const v = h.split("/")[0];
    if (viewOk(v)) { setView(v); return true; }
    return false;
  }
  function wire() {
    if (wired) return; wired = true;
    const root = $("#help");
    root.addEventListener("click", async e => {
      const t = e.target;
      const g = t.closest("[data-hp-go]");
      if (g) { e.preventDefault(); return go(g.dataset.hpGo, g.dataset.hpAnchor || ""); }
      const a = t.closest("a[data-hp-link]");
      if (a) { if (follow(a.getAttribute("href"))) e.preventDefault(); return; }
      const c = t.closest("[data-hp-copy]");
      if (c) {
        const code = c.parentElement.querySelector("code").textContent;
        try { await navigator.clipboard.writeText(code); c.classList.add("done"); c.querySelector("span").textContent = "Copied"; setTimeout(() => { c.classList.remove("done"); c.querySelector("span").textContent = "Copy"; }, 1600); }
        catch { UI.toast("Couldn't copy"); }
        return;
      }
      const m = t.closest("[data-hp-method]");
      if (m) { $$(".hp-methods button", root).forEach(b => b.setAttribute("aria-pressed", b === m)); return filterRef(root); }
      if (!t.closest(".hp-search")) $$(".hp-results", root).forEach(r => r.hidden = true);
    });
    root.addEventListener("input", e => {
      if (e.target.matches(".hp-search input")) showResults(e.target);
      if (e.target.matches(".hp-filter")) filterRef(root);
    });
    root.addEventListener("focusin", e => { if (e.target.matches(".hp-search input") && e.target.value.trim()) showResults(e.target); });
    root.addEventListener("keydown", e => {
      if (!e.target.matches(".hp-search input")) return;
      const box = e.target.closest(".hp-search").querySelector(".hp-results"), items = $$(".hp-result", box);
      if (e.key === "Escape") { e.target.value = ""; box.hidden = true; return; }
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && items.length) {
        e.preventDefault(); sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((b, i) => b.setAttribute("aria-selected", i === sel)); items[sel].scrollIntoView({ block: "nearest" });
      }
      if (e.key === "Enter" && items[sel]) { e.preventDefault(); items[sel].click(); }
    });
    root.addEventListener("submit", e => { if (e.target.matches("[data-hp-try]")) { e.preventDefault(); tryIt(e.target); } });
    // "/" searches the docs on this page (before the app's own "/", which jumps to the explorer)
    addEventListener("keydown", e => {
      if (S.view !== "help" || e.key !== "/" || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) || document.activeElement.isContentEditable) return;
      const inp = $("#help .hp-search input"); if (!inp) return;
      e.preventDefault(); e.stopImmediatePropagation(); inp.focus();
    }, true);
    // Back and Forward move between docs
    addEventListener("popstate", () => {
      const h = location.hash.slice(1);
      if (h === "help" || h.startsWith("help/")) { route(h); if (S.view !== "help") setView("help"); else render(); }
    });
  }

  return { open, route, md };
})();
