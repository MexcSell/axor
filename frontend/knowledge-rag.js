/* Knowledge Hub · retrieval & answers (knowledge_rag.py; knowledge.js and knowledge-company.js call this; knowledge-rag.css; prefix kbr-).
   - askCard: Ask My Knowledge / Ask the Knowledge Hub with RAG: where to read from (both spaces, one, or only some My Knowledge
     folders: cross-space by choice), deeper multi-step research, an optional model rerank; the answer with its points marked
     as backed by evidence, inference or unverified, each citation checked against its passage, evidence with page/section.
   - tab: "Retrieval & quality" on both pages: How it works (the pipeline with this user's numbers, embedding models, index
     health), Try retrieval (any strategy, as any of your agents, teams or services: see exactly what they would get), the
     Evaluation center (test questions, strategies compared on recall/precision/MRR/nDCG, permission isolation) and the
     Retrieval log (who retrieved what, when, how fast). */
const KnowledgeRag = (() => {
  const K = "/api/knowledge/rag";
  const SUBS = [["how", "layers", "How it works"], ["try", "search", "Try retrieval"], ["eval", "trophy", "Evaluation"], ["log", "list", "Retrieval log"]];
  const BASIS = { evidence: ["ok", "Backed by evidence"], inference: ["run", "Inference"], unverified: ["warn", "Unverified"] };
  const MATCH = { both: "words + meaning", words: "words", meaning: "meaning", fuzzy: "fuzzy", linked: "linked" };
  const METRICS = [["recall", "Recall@k"], ["precision", "Precision@k"], ["mrr", "MRR"], ["ndcg", "nDCG@k"], ["hit1", "Top-1"], ["ms", "ms"]];
  const S = { sub: null, status: null, tried: null, evals: null, log: null, logActor: "", loading: {}, failed: {}, pick: new Set(), space: "personal", render: null };
  const h = () => Knowledge.h;
  const pct = v => v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`;
  const num = v => (v || 0).toLocaleString();
  const st = k => { try { return store.get("kbr." + k, null); } catch { return null; } };
  const sv = (k, v) => { try { store.set("kbr." + k, v); } catch { /* per-viewer convenience only */ } };
  const ref = (r, title) => r.startsWith("kb:") ? `<button type="button" class="linkbtn" data-kb-ref="${esc(r)}">${esc(title || r)}</button>` : `<span>${esc(title || r)}</span>`;
  const cite = r => r.startsWith("kb:") ? `<button type="button" class="kb-cite" data-kb-ref="${esc(r)}">${esc(r)}</button>` : `<span class="kb-cite">${esc(r)}</span>`;

  // ---------- data ----------
  async function load(what, url, opts) {
    if (S.loading[what]) return;
    S.loading[what] = true;
    try { S[what] = await api(url, opts); S.failed[what] = ""; } catch (e) { S.failed[what] = e.message; }
    S.loading[what] = false;
    S.render?.();
  }
  function after(space, render) {  // knowledge.js afterRender: the tab loads what it shows
    S.render = render; S.space = space;
    const sub = S.sub || st("sub") || "how";
    if (!S.status && !S.loading.status && !S.failed.status) load("status", `${K}/status`);
    if (sub === "eval" && !S.evals && !S.loading.evals && !S.failed.evals) load("evals", `${K}/evals`);
    if (sub === "log" && !S.log && !S.loading.log && !S.failed.log) load("log", `${K}/log${S.logActor ? `?actor=${encodeURIComponent(S.logActor)}` : ""}`);
  }

  // ---------- Ask ----------
  function askBody(F) {
    return { folders: F.getAll("folders").filter(Boolean), deep: F.get("deep") || "auto", rerank: F.get("rerank") === "on" };
  }
  function askCard(H, a, where, space, d) {
    const company = space === "company", folders = company ? [] : (d?.folders || []).map(f => f.path).filter(p => p !== "/");
    const chosen = new Set(a?.folders || []);
    const form = `<form class="kb-ask" data-kb-form="ask"><textarea name="question" rows="2" maxlength="2000" required placeholder="${company ? "e.g. What are our current agent architecture decisions?" : "e.g. Combine my latest research with the company's Bittensor knowledge: what should we improve?"}">${esc(a?.question || "")}</textarea>
      <div class="kb-row end">${company ? `<input type="hidden" name="where" value="company">` : `<label><span>From</span><select name="where">${[["both", "My Knowledge and the company"], ["mine", "My Knowledge only"], ["company", "Company knowledge only"]].map(([v, l]) => `<option value="${v}" ${(a?.where || where) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>`}
        ${company ? "" : `<details class="kbr-folders"${chosen.size ? " open" : ""}><summary>${icon("folder")}${chosen.size ? `${chosen.size} folder${chosen.size === 1 ? "" : "s"}` : "All folders"}</summary>
          <div class="kbr-fold-list" role="group" aria-label="Only these My Knowledge folders">${folders.map(p => `<label class="kb-check"><input type="checkbox" name="folders" value="${esc(p)}" ${chosen.has(p) ? "checked" : ""}><span>${esc(p)}</span></label>`).join("") || `<span class="kb-faint">No folders yet.</span>`}</div>
          <p class="kb-note">Tick folders to read only those from My Knowledge (company knowledge is read as chosen above). Nothing is shared: the answer stays on this page.</p></details>`}
        <label><span>Research</span><select name="deep">${[["auto", "Deeper when it has several parts"], ["on", "Always deeper (more searches)"], ["off", "One search"]].map(([v, l]) => `<option value="${v}" ${(st("deep") || "auto") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="kb-check kbr-inline"><input type="checkbox" name="rerank" ${st("rerank") ? "checked" : ""}><span>Rerank with the model</span></label>
        <button class="btn primary" ${d?.can_model ? "" : "disabled title='No model is connected'"}>${icon("sparkle")}Ask</button></div></form>`;
    return H.card("sparkle", company ? "Ask the Knowledge Hub" : "Ask My Knowledge", `<span class="kb-faint">Hybrid retrieval · cited answers</span>`, form + (a?.answer !== undefined ? answer(H, a) : ""), "kb-askcard");
  }
  function answer(H, a) {
    const ck = a.checks, tr = a.trace || {};
    const text = a.answer ? `<p class="kb-text">${esc(a.answer).replace(/\[((?:kb|mem|mk|wfm|cok):\d+)\]/g, (m, r) => cite(r))}</p>` : H.empty("No answer.");
    const points = (a.points || []).length ? `<h4>What it rests on</h4><ul class="kbr-points">${a.points.map(p => { const [tone, l] = BASIS[p.basis] || BASIS.unverified;
        return `<li><span class="kbr-point">${H.chip(tone, l)} ${esc(p.claim)}</span><small class="kb-faint">${p.refs.length ? p.refs.map(cite).join(" ") : "no source cited"}${p.support !== null && p.support !== undefined && p.basis !== "inference" ? ` · ${p.support >= 0.4 ? "wording found in the passage" : `<b class="kbr-weak">weak support (${pct(p.support)} of its words)</b>`}` : ""}</small></li>`; }).join("")}</ul>` : "";
    const ev = a.evidence.length ? `<h4>Evidence</h4><ul class="kb-ev kbr-ev">${a.evidence.map(e => `<li>${ref(e.ref, e.title)}<small class="kb-faint">${esc(e.kind)}${e.where ? ` · ${esc(e.where)}` : ""}${e.space ? ` · ${esc(e.space)}` : ""}${e.state ? ` · ${esc(e.state)}` : ""} · ${esc(e.ref)}${e.why ? ` — ${esc(e.why)}` : ""}</small>
        ${e.passage ? `<details><summary>Passage</summary><blockquote class="kbr-passage">${esc(e.passage)}</blockquote></details>` : ""}</li>`).join("")}</ul>` : "";
    const list = (t, xs) => xs?.length ? `<h4>${t}</h4><ul class="kb-plain">${xs.map(g => `<li>${esc(g)}</li>`).join("")}</ul>` : "";
    const hops = (a.hops || []).length ? `<p class="kb-note">${icon("route")}Deeper research: ${a.hops.map(x => `“${esc(x.query)}” (${x.found} more)`).join(", ")}.</p>` : "";
    const check = ck && ck.points ? `<p class="kb-note">${icon("shield")}Citation check: ${ck.supported} of ${ck.cited} cited point${ck.cited === 1 ? "" : "s"} found in their passages${ck.uncited ? `, ${ck.uncited} without a source` : ""}. ${esc(ck.how)}</p>` : "";
    const how = `<p class="kb-note">Searched ${num(tr.candidates)} record${tr.candidates === 1 ? "" : "s"} you may read${tr.filtered ? ` (${num(tr.filtered)} left out by the folders)` : ""} · ${esc(tr.strategy_label || "")}${tr.mode && tr.mode !== "words" ? ` · ${esc(tr.mode)}` : ""}${tr.intent ? ` · ${esc(tr.intent)}` : ""}${tr.time ? ` · ${esc(tr.time)}` : ""}${a.reranked ? " · reranked by the model" : ""} · ${h().plural(a.hits.length, "record")} given to the model${a.tokens ? ` · ${a.tokens.toLocaleString()} tokens` : ""}${a.ms ? ` · ${(a.ms / 1000).toFixed(1)} s` : ""}. Refs it cited that weren't among them are left out.</p>`;
    return `<div class="kb-answer">${a.confidence ? `<p class="kbr-conf">${H.chip(a.confidence === "high" ? "ok" : a.confidence === "medium" ? "run" : "warn", `Confidence: ${a.confidence}`)}</p>` : ""}${text}${points}${ev}${list("What's missing", a.gaps)}${list("Limits of this answer", a.limitations)}${list("Directions", a.directions)}${hops}${check}${how}</div>`;
  }

  // ---------- the tab ----------
  function tab(H, space) {
    S.space = space;
    const sub = S.sub || st("sub") || "how";
    const nav = `<div class="kb-subtabs" role="group" aria-label="Retrieval & quality">${SUBS.map(([k, ic, l]) => `<button type="button" class="chip" data-kbr-sub="${k}" aria-pressed="${sub === k}">${icon(ic)}${l}</button>`).join("")}</div>`;
    const lede = `<p class="kbr-lede">Every answer and every agent reads through one retrieval pipeline: what a reader may see is decided first, then only that is searched (keywords, meaning and links), ranked and handed over with its source and place. This page shows how well it works and lets you check it.</p>`;
    if (S.failed.status) return lede + nav + H.empty(`${esc(S.failed.status)} <button type="button" class="linkbtn" data-kbr="reload">Try again</button>`);
    if (!S.status) return lede + nav + Loading.line("Reading the index…");
    const body = sub === "try" ? tryView(H) : sub === "eval" ? evalView(H) : sub === "log" ? logView(H) : howView(H);
    return lede + nav + body;
  }

  function howView(H) {
    const s = S.status, hl = s.health, m = s.model;
    const steps = [["file", "Sources", num(s.items), "items you hold"], ["doc", "Extract", hl.unreadable.length ? `${hl.unreadable.length} unreadable` : "ok", "documents, pictures, audio"],
      ["layers", "Chunk", num(s.chunks), `passages · ${pct(s.items ? s.chunked / s.items : 1)} of items`], ["hash", "Keyword index", num(s.chunks), "BM25, porter stemming"],
      ["chips", "Vectors", s.embed_wanted ? `${num(s.embedded)}/${num(s.embed_wanted)}` : num(s.embedded), m.meaning ? "passages of long items" : "fuzzy, not meaning"],
      ["shield", "Permissions", "first", "filtered before search"], ["swap", "Fuse + rerank", "RRF", "entities, authority, time"], ["branch", "Graph", "1 hop", "typed links"],
      ["sparkle", "Cited answers", num(s.queries_30d), `retrievals in 30 days · ${num(s.avg_ms)} ms avg`]];
    const pipe = `<ol class="kbr-pipe">${steps.map(([ic, l, v, sub]) => `<li>${icon(ic)}<span>${l}</span><b>${v}</b><small>${sub}</small></li>`).join("")}</ol>`;
    const models = `<div class="kb-table kbr-models" role="table"><div class="kb-tr kb-th" role="row"><span>Embedding model</span><span>Dims</span><span>Passages</span><span>Items</span><span></span></div>
      ${s.models.map(x => `<div class="kb-tr" role="row"><span class="kb-cell-main"><span><b>${esc(x.label || x.model)}</b><small class="kb-faint">${esc(x.model)}</small></span></span><span>${x.dims || "–"}</span><span>${num(x.chunk_vectors)}</span><span>${num(x.item_vectors)}</span>
        <span>${x.current ? H.chip("ok", "In use") : `<button type="button" class="btn sm" data-kbr-drop="${esc(x.model)}" title="Remove this model's vectors">${icon("trash")}Remove</button>`}</span></div>`).join("")}</div>
      <p class="kb-note">Vectors are kept per model: changing the model never mixes them. ${m.meaning ? "" : "No embeddings endpoint is set, so vectors match word forms and spelling, not meaning: set an OpenAI or OpenRouter key in Agents → Models, or KNOWLEDGE_EMBED_URL on the server."}${s.note ? ` <b>${esc(s.note)}</b>` : ""}</p>`;
    const item = x => `<li><span>${ref(`kb:${x.id}`, x.title)}</span>${x.error ? `<small class="kb-faint">${esc(x.error)}</small>` : ""}</li>`;
    const health = [
      hl.duplicates.length ? `<h4>Duplicates</h4><ul class="kb-list">${hl.duplicates.map(d => `<li><span>${esc(d.title)}</span><small class="kb-faint">${d.n} copies: ${d.ids.map(i => ref(`kb:${i}`, `kb:${i}`)).join(" ")}</small></li>`).join("")}</ul>` : "",
      hl.unreadable.length ? `<h4>Couldn't be read</h4><ul class="kb-list">${hl.unreadable.map(item).join("")}</ul>` : "",
      hl.empty.length ? `<h4>Almost no text</h4><ul class="kb-list">${hl.empty.map(item).join("")}</ul>` : "",
      hl.connectors.length ? `<h4>Connectors failing</h4><ul class="kb-list">${hl.connectors.map(c => `<li><span>${esc(c.name || c.platform)}</span><small class="kb-faint">${esc(c.error)}</small></li>`).join("")}</ul>` : ""].join("");
    const L = s.learning, ev = L.eval;
    const verdict = ev ? { better: ["ok", "helped"], same: ["none", "made no difference"], worse: ["bad", "hurt"], mixed: ["warn", "was mixed"] }[ev.verdict] : null;
    const learn = `<label class="kb-check"><input type="checkbox" data-kbr-learn ${L.on ? "checked" : ""}><span><b>Use agents' ratings in ranking</b><small>Records agents rated useful after using them (knowledge_feedback) rank a little higher, ones rated not useful a little lower. Ratings from the last ${L.days} days.</small></span></label>
      <ul class="kb-bars"><li><span>Rated records</span><b>${num(L.rated_items)}</b></li><li><span>Rated useful / not useful</span><b>${num(L.useful)} / ${num(L.not_useful)}</b></li></ul>
      <p class="kb-note">${ev ? `In the last evaluation (${h().when(ev.ts)}) the ratings ${H.chip(verdict[0], verdict[1])}: recall ${ev.delta.recall >= 0 ? "+" : ""}${Math.round(ev.delta.recall * 100)}, MRR ${ev.delta.mrr >= 0 ? "+" : ""}${Math.round(ev.delta.mrr * 100)}, nDCG ${ev.delta.ndcg >= 0 ? "+" : ""}${Math.round(ev.delta.ndcg * 100)} points against the same ranking without them.` : "Run an evaluation to see whether the ratings help your questions before you turn this on."}</p>`;
    const readers = `<ul class="kb-bars kbr-readers">${s.readers.map(r => `<li><span>${esc(r.label)}</span><b>${r.n ? `${num(r.n)}<small class="kb-faint"> · ${h().when(r.last)}</small>` : `<span class="kb-faint">none</span>`}</b></li>`).join("")}</ul>
      <p class="kb-note">Searches in the last 30 days. Your agents, the Assistant, competition teams, Workforce and Mission Control's analyst search when they decide to (search_knowledge, research_knowledge for questions with several parts) and rate what helped; competition teams, Workforce and Mission Control also start with the records that fit their goal, and Company project runs get the records that fit their task. Each reads only what you let it.</p>`;
    return `${H.card("layers", "The pipeline, with your numbers", `<button type="button" class="btn sm" data-kbr="reindex" title="Make every passage again (vectors are made in the background)">${icon("cycle")}Rebuild passages</button>`, pipe +
        `<p class="kb-note">Passages of about ${num(s.settings.chunk)} characters follow headings, pages and timestamps; code blocks and tables stay whole. Originals stay where they are: passages and vectors are an index over them, and nothing an answer says is saved as knowledge unless you save it.</p>`)}
      <div class="kb-grid">${H.card("chips", "Embedding models", "", models)}
        ${H.card("shield", "Index health", hl.inbox ? `<span class="kb-faint">${num(hl.inbox)} in the inbox</span>` : "", health || H.empty("Nothing to fix: no duplicates, unreadable files or failing connectors."))}</div>
      <div class="kb-grid">${H.card("bot", "Who reads your knowledge", "", readers)}${H.card("cycle", "Learning from agents' ratings", L.on ? H.chip("ok", "On") : H.chip("none", "Off"), learn)}</div>`;
  }

  function tryView(H) {
    const s = S.status, t = S.tried, f = st("try") || {};
    const actors = [["", "You (everything you hold)"], ...(s.actors || []).map(a => [a.ref, a.label])];
    const form = `<form class="kb-form" data-kbr-form="try"><div class="kb-row"><label class="kb-grow"><span>Query</span><input name="query" required maxlength="1000" value="${esc(t?.query || "")}" placeholder="e.g. SN62 miner ranking experiments"></label>
        <label><span>From</span><select name="where">${[["both", "Both spaces"], ["mine", "My Knowledge"], ["company", "Company"]].map(([v, l]) => `<option value="${v}" ${(f.where || (S.space === "company" ? "company" : "both")) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label><span>Strategy</span><select name="strategy">${Object.entries(s.settings.strategies).map(([v, l]) => `<option value="${v}" ${(f.strategy || "full") === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label></div>
      <div class="kb-row"><label class="kb-grow"><span>Retrieve as</span><select name="actor">${actors.map(([v, l]) => `<option value="${esc(v)}" ${(f.actor || "") === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
        <label><span>Folder</span><select name="folder"><option value="">Any</option>${(s.folders || []).map(p => `<option ${f.folder === p ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>
        <label><span>Changed since</span><input type="date" name="since" value="${esc(f.since || "")}"></label><button class="btn primary">${icon("search")}Retrieve</button></div>
      <p class="kb-note">${icon("shield")}As an agent, team or service you see exactly what it would get: its permissions are applied before anything is searched.</p></form>`;
    let out = "";
    if (t) {
      const tr = t.trace || {};
      const legs = Object.entries(tr.legs || {}).map(([k, v]) => `${k} ${num(v)}`).join(" · ");
      out = `<p class="kb-note">${t.actor ? esc(t.actor_label) : "You"} may read ${num(tr.candidates)} record${tr.candidates === 1 ? "" : "s"}${tr.filtered ? `, ${num(tr.filtered)} left out by the filters` : ""} · ${esc(tr.strategy_label || "")} · intent ${esc(tr.intent || "–")}${(tr.entities || []).length ? ` · entities ${tr.entities.map(esc).join(", ")}` : ""}${tr.time ? ` · ${esc(tr.time)}` : ""}${legs ? ` · matches: ${legs}` : ""}${tr.expanded ? ` · ${tr.expanded} via links` : ""} · ${num(tr.ms)} ms</p>`;
      out += t.results.length ? `<ol class="kbr-results">${t.results.map((r, n) => `<li><label class="kbr-pick" title="Expected for a test question"><input type="checkbox" data-kbr-pick="${esc(r.ref)}" ${S.pick.has(r.ref) ? "checked" : ""}><span class="kbr-sr">Pick</span></label>
          <div><div class="kb-hit-h"><span class="kbr-rank">${n + 1}</span>${ref(r.ref, r.title)}${H.chip(r.match === "linked" ? "run" : r.match === "both" ? "ok" : "none", MATCH[r.match] || r.match)}${r.state_label ? H.chip(r.state_label === "Verified" ? "ok" : "warn", esc(r.state_label)) : ""}${r.stale ? H.chip("warn", "past review") : ""}</div>
          <small class="kb-faint">${esc(r.kind)}${r.where ? ` · ${esc(r.where)}` : ""}${r.space_label ? ` · ${esc(r.space_label)}` : ""}${r.scope_label ? ` · ${esc(r.scope_label)}` : ""} · score ${r.score}${Object.entries(r.legs || {}).map(([k, v]) => ` · ${k} #${v}`).join("")}${r.similarity !== undefined && r.similarity !== null ? ` · similarity ${r.similarity}` : ""}${r.via ? ` · linked from ${esc(r.via.title)} (${esc(r.via.rel)})` : ""}${r.ratings ? ` · rated ${r.ratings.useful}↑ ${r.ratings.not_useful}↓` : ""}</small>
          <p class="kbr-passage">${esc(r.text)}</p></div></li>`).join("")}</ol>
        <form class="kb-row end" data-kbr-form="case"><span class="kb-note">${S.pick.size ? `${S.pick.size} ticked` : "Tick the records that should come back"}</span><button class="btn" ${S.pick.size ? "" : "disabled"}>${icon("plus")}Save as a test question</button></form>`
        : H.empty(`Nothing ${t.actor ? "this reader may see " : ""}matches “${esc(t.query)}”.`);
    }
    return H.card("search", "Try retrieval", "", form + out);
  }

  function evalView(H) {
    if (S.failed.evals) return H.empty(`${esc(S.failed.evals)} <button type="button" class="linkbtn" data-kbr="reload">Try again</button>`);
    const e = S.evals; if (!e) return Loading.line("Opening the evaluation center…");
    const run = e.runs[0], prev = e.runs[1];
    const best = run ? Object.fromEntries(METRICS.map(([k]) => [k, Object.values(run.metrics).reduce((b, m) => k === "ms" ? Math.min(b, m[k]) : Math.max(b, m[k]), k === "ms" ? Infinity : -Infinity)])) : {};
    const delta = (k, v) => { if (!prev || k === "ms") return ""; const d = v - prev.metrics.full[k]; return Math.abs(d) < 0.0005 ? "" : `<small class="${d > 0 ? "kbr-up" : "kbr-down"}">${d > 0 ? "+" : ""}${Math.round(d * 100)}</small>`; };
    const table = run ? `<div class="kb-table kbr-metrics" role="table"><div class="kb-tr kb-th" role="row"><span>Strategy</span>${METRICS.map(([, l]) => `<span>${l.replace("@k", `@${run.k}`)}</span>`).join("")}<span>Stale in top</span></div>
        ${Object.entries(run.metrics).map(([s, m]) => `<div class="kb-tr${s === "full" ? " kbr-cur" : ""}" role="row"><span class="kb-cell-main"><b>${esc(m.label)}</b>${s === "full" ? `<small class="kb-faint">what answers and agents use</small>` : ""}</span>
          ${METRICS.map(([k]) => `<span class="${m[k] === best[k] ? "kbr-best" : ""}">${k === "ms" ? num(m[k]) : pct(m[k])}${s === "full" ? delta(k, m[k]) : ""}</span>`).join("")}<span>${pct(m.stale_share)}</span></div>`).join("")}</div>` : "";
    const iso = run?.isolation;
    const isoLine = iso ? `<p class="kbr-iso ${iso.ok ? "ok" : "bad"}">${icon(iso.ok ? "shield" : "alert")}${iso.ok ? `Permission isolation held: ${num(iso.checked)} results to an agent and a team with no grants, re-checked one by one, none outside their rules. ${num(iso.withheld)} records you could see were withheld from them.`
        : `Permission isolation FAILED: ${iso.violations.length} result(s) reached a reader that may not read them (${iso.violations.map(v => `${esc(v.ref)} → ${esc(v.probe)}`).join(", ")}). Stop sharing and report it.`}</p>` : "";
    const ans = run?.answers ? `<p class="kb-note">${icon("sparkle")}Answers to ${run.answers.asked} question${run.answers.asked === 1 ? "" : "s"}: faithfulness ${pct(run.answers.faithfulness)}, citation accuracy ${pct(run.answers.citation_accuracy)}, expected records cited ${pct(run.answers.cited_expected)} · ${num(run.answers.tokens)} tokens. ${esc(run.answers.how)}${run.answers.errors?.length ? ` Errors: ${run.answers.errors.map(esc).join("; ")}` : ""}</p>` : "";
    const per = e.last.length ? `<details class="kbr-per"><summary>Question by question (last run)</summary><div class="kb-table" role="table"><div class="kb-tr kb-th" role="row"><span>Question</span>${Object.keys(e.strategies).map(s => `<span>${esc(e.strategies[s].split(" (")[0])}</span>`).join("")}</div>
        ${e.last.map(c => `<div class="kb-tr" role="row"><span class="kb-cell-main">${esc(c.question)}</span>${Object.keys(e.strategies).map(s => { const r = c.by[s]; return `<span class="${r?.rank === 1 ? "kbr-best" : r?.rank ? "" : "kbr-miss"}">${r?.rank ? `#${r.rank}` : "missed"}</span>`; }).join("")}</div>`).join("")}</div></details>` : "";
    const runForm = `<form class="kb-row end" data-kbr-form="run"><label><span>k</span><select name="k">${[3, 5, 10].map(k => `<option ${k === (run?.k || 5) ? "selected" : ""}>${k}</option>`).join("")}</select></label>
      <label class="kb-check kbr-inline"><input type="checkbox" name="answers"><span>Also answer up to 10 questions (uses the model)</span></label><button class="btn primary" ${e.cases.length ? "" : "disabled"}>${icon("play")}Run evaluation</button></form>`;
    const cases = e.cases.length ? `<ul class="kb-list kbr-cases">${e.cases.map(c => `<li><span><b>${esc(c.question)}</b><small class="kb-faint">${c.expected.map(x => x.missing ? `<s>${esc(x.ref)}</s> (gone)` : ref(x.ref, x.title || x.ref)).join(" · ")}${c.spaces && c.spaces !== "both" ? ` · ${c.spaces === "mine" ? "My Knowledge" : "Company"} only` : ""}</small></span>
        <button type="button" class="iconbtn" data-kbr-rm="${c.id}" title="Remove this test question" aria-label="Remove this test question">${icon("trash")}</button></li>`).join("")}</ul>` : H.empty("No test questions yet. Add one below, tick results in Try retrieval, or take one from your Ask history.");
    const add = `<form class="kb-form" data-kbr-form="add"><div class="kb-row"><label class="kb-grow"><span>Question</span><input name="question" required minlength="3" maxlength="1000" placeholder="A real question you ask"></label>
        <label class="kb-grow"><span>Records that should come back</span><input name="expected" required placeholder="kb:12, kb:40"></label><label><span>From</span><select name="where"><option value="both">Both</option><option value="mine">My Knowledge</option><option value="company">Company</option></select></label>
        <button class="btn">${icon("plus")}Add</button></div></form>`;
    const sugg = e.suggestions.length ? `<h4>From your Ask history</h4><ul class="kb-list">${e.suggestions.map((x, i) => `<li><span><b>${esc(x.question)}</b><small class="kb-faint">cited ${x.expected.map(r => ref(r.ref, r.title)).join(" · ")}</small></span><button type="button" class="btn sm" data-kbr-sugg="${i}">${icon("plus")}Use</button></li>`).join("")}</ul>
        <p class="kb-note">Only use one when the cited records really are the right answer.</p>` : "";
    const hist = e.runs.length > 1 ? `<h4>Earlier runs</h4><ul class="kb-bars">${e.runs.slice(0, 10).map(r => `<li><span>${h().when(r.ts)} · ${r.cases} questions · ${esc(r.by_user)}</span><b>recall ${pct(r.metrics.full.recall)} · MRR ${pct(r.metrics.full.mrr)} · ${r.isolation.ok ? "isolation ok" : "isolation FAILED"}</b></li>`).join("")}</ul>` : "";
    return `${H.card("trophy", "Evaluation center", run ? `<span class="kb-faint">last run ${h().when(run.ts)} · ${run.cases} questions · ${(run.ms / 1000).toFixed(1)} s</span>` : "",
        `${run ? table + isoLine + ans + per : H.empty("No run yet: add test questions, then run the evaluation to compare the strategies.")}${runForm}
        <p class="kb-note">Run it again after you change how knowledge is captured, the embeddings model or these settings: the strategy in use is the bold row; the small numbers are the change since the run before.</p>`)}
      <div class="kb-grid">${H.card("list", "Test questions", `<span class="kb-faint">${e.cases.length}</span>`, cases + add)}${H.card("bulb", "Suggestions", "", sugg || H.empty("Questions you ask with Ask appear here with the records the answer cited."))}</div>${hist ? H.card("chart", "History", "", hist) : ""}`;
  }

  function logView(H) {
    if (S.failed.log) return H.empty(`${esc(S.failed.log)} <button type="button" class="linkbtn" data-kbr="reload">Try again</button>`);
    const l = S.log; if (!l) return Loading.line("Reading the retrieval log…");
    const who = `<div class="kb-chiprow" role="group" aria-label="Who retrieved"><button type="button" class="chip" data-kbr-actor="" aria-pressed="${!S.logActor}">Everyone</button>${l.actors.map(a => `<button type="button" class="chip" data-kbr-actor="${esc(a.actor)}" aria-pressed="${S.logActor === a.actor}">${esc(a.label)} <em>${a.n}</em></button>`).join("")}</div>`;
    const rows = l.rows.length ? `<div class="kb-table kbr-log" role="table"><div class="kb-tr kb-th" role="row"><span>When</span><span>Who</span><span>Query</span><span>Found</span><span>Top records</span><span>ms</span></div>
      ${l.rows.map(x => `<div class="kb-tr" role="row"><span class="kb-faint">${h().when(x.ts)}</span><span>${esc(x.label)}</span><span class="kb-cell-main"><span>${esc(x.query)}<small class="kb-faint">${esc(x.strategy === "ask" ? "Ask" : (S.status?.settings.strategies[x.strategy] || x.strategy))}${x.intent ? ` · ${esc(x.intent)}` : ""} · of ${num(x.candidates)}</small></span></span>
        <span>${x.results}</span><span class="kbr-refs">${x.refs.slice(0, 3).map(r => ref(r.ref, r.title || r.ref)).join("")}${x.cited ? `<small class="kb-faint">cited ${x.cited.length}</small>` : ""}</span><span>${num(x.ms)}</span></div>`).join("")}</div>` : H.empty("Nothing retrieved yet.");
    return H.card("list", "Retrieval log", `<button type="button" class="btn sm" data-kbr="log-refresh">${icon("cycle")}Refresh</button>`, who + rows + `<p class="kb-note">Every retrieval: by you, your agents, competition teams, Workforce and Mission Control, with what they were allowed to search and what came back. Evaluation runs aren't logged as use.</p>`);
  }

  // ---------- events ----------
  const inPage = el => el.closest("#knowledge, #myknowledge");
  document.addEventListener("click", async e => {
    const b = e.target.closest("[data-kbr],[data-kbr-sub],[data-kbr-drop],[data-kbr-rm],[data-kbr-sugg],[data-kbr-actor]");
    if (!b || !inPage(b)) return;
    const ds = b.dataset;
    if (ds.kbrSub) { S.sub = ds.kbrSub; sv("sub", ds.kbrSub); S.render?.(); return; }
    if (ds.kbr === "reload") { S.failed = {}; S.status = S.evals = S.log = null; S.render?.(); return; }
    if (ds.kbr === "reindex") { const r = await h().busy(b, () => api(`${K}/reindex`, { method: "POST" })); if (r) { S.status = r; toast(`Passages rebuilt: ${r.chunks.toLocaleString()}`, { kind: "success" }); S.render?.(); } return; }
    if (ds.kbr === "log-refresh") { S.log = null; S.render?.(); return; }
    if (ds.kbrDrop !== undefined) {
      if (!await UI.confirm({ title: "Remove these vectors?", body: "Search by meaning keeps using the model in use; this model's vectors are deleted.", ok: "Remove", icon: "trash" })) return;
      const r = await h().busy(b, () => api(`${K}/models?model=${encodeURIComponent(ds.kbrDrop)}`, { method: "DELETE" })); if (r) { S.status = r; S.render?.(); } return;
    }
    if (ds.kbrRm) { const r = await h().busy(b, () => api(`${K}/evals/${ds.kbrRm}`, { method: "DELETE" })); if (r) { S.evals = r; S.render?.(); } return; }
    if (ds.kbrSugg !== undefined) {
      const x = S.evals.suggestions[+ds.kbrSugg];
      const r = await h().busy(b, () => api(`${K}/evals`, { method: "POST", body: { question: x.question, expected: x.expected.map(r => r.ref) } }));
      if (r) { S.evals = r; S.render?.(); toast("Test question added", { kind: "success" }); } return;
    }
    if (ds.kbrActor !== undefined) { S.logActor = ds.kbrActor; S.log = null; S.render?.(); }
  });
  document.addEventListener("change", e => {
    const el = e.target;
    if (!inPage(el)) return;
    if (el.matches("[data-kbr-learn]")) {
      el.disabled = true;
      api(`${K}/settings`, { method: "POST", body: { learn: el.checked } }).then(r => { S.status = r; toast(r.learning.on ? "Agents' ratings now move the ranking" : "Ratings no longer move the ranking", { kind: "success" }); S.render?.(); })
        .catch(err => { toast(err.message, { kind: "error" }); el.checked = !el.checked; el.disabled = false; });
      return;
    }
    if (el.dataset.kbrPick) { el.checked ? S.pick.add(el.dataset.kbrPick) : S.pick.delete(el.dataset.kbrPick); S.render?.(); return; }
    if (el.closest(".kb-ask")) { if (el.name === "deep") sv("deep", el.value); if (el.name === "rerank") sv("rerank", el.checked); }
  });
  document.addEventListener("submit", async e => {
    const fm = e.target.closest("form[data-kbr-form]"); if (!fm || !inPage(fm)) return;
    e.preventDefault();
    const F = new FormData(fm), kind = fm.dataset.kbrForm, btn = fm.querySelector("button:not([type=button])");
    if (kind === "try") {
      const f = { where: F.get("where"), strategy: F.get("strategy"), actor: F.get("actor"), folder: F.get("folder"), since: F.get("since") };
      sv("try", f);
      const r = await h().busy(btn, () => api(`${K}/try`, { method: "POST", body: { query: F.get("query"), where: f.where, strategy: f.strategy, actor: f.actor, folders: f.folder ? [f.folder] : [], since: f.since || "" } }));
      if (r) { S.tried = r; S.pick = new Set(); S.render?.(); }
      return;
    }
    if (kind === "case") {
      const r = await h().busy(btn, () => api(`${K}/evals`, { method: "POST", body: { question: S.tried.query, expected: [...S.pick], where: (st("try") || {}).where || "both" } }));
      if (r) { S.evals = r; S.pick = new Set(); toast("Test question saved", { kind: "success" }); S.render?.(); }
      return;
    }
    if (kind === "add") {
      const expected = String(F.get("expected") || "").split(/[\s,;]+/).map(x => x.trim()).filter(Boolean);
      const r = await h().busy(btn, () => api(`${K}/evals`, { method: "POST", body: { question: F.get("question"), expected, where: F.get("where") } }));
      if (r) { S.evals = r; S.render?.(); }
      return;
    }
    if (kind === "run") {
      const r = await h().busy(btn, () => api(`${K}/evals/run`, { method: "POST", body: { k: +F.get("k"), answers: F.get("answers") === "on" } }));
      if (r) { S.evals = r; S.render?.(); const iso = r.runs[0]?.isolation; toast(iso?.ok ? "Evaluation done" : "Evaluation done: isolation FAILED", { kind: iso?.ok ? "success" : "error" }); }
    }
  });
  return { askCard, askBody, tab, after, invalidate: () => { S.status = S.evals = S.log = null; } };
})();
