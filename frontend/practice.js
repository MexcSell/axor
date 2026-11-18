/* Practice: the Study tab's drills as exercises in the page. The model writes each exercise for the learner (POST
   /api/study/practice); the page runs it. Modes: lesson (then check questions), quiz (graded as you go: choices and exact
   answers here, free answers by the model), cards (flashcards with spaced repetition), pron (say a sentence, scored word by
   word from speech recognition), dictation (listen and type), writing (corrections as a diff), code (exercise, editor, a
   Run that runs it in the browser through the Lab's Python, and a line-by-line review), plan and project (saved to notes), and dialogue (a hands-free voice session with a tutor, then a
   feedback report). Study (study.js) hosts it in the Practice tab and passes `env`: the track, the picked topic, tutors,
   the model, and hooks back into the page. */

// English speech for both tabs: read text aloud with an English voice, and the browser's speech recognition
const Voice = (() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function pick() {
    if (!("speechSynthesis" in window)) return null;
    const vs = speechSynthesis.getVoices().filter(v => /^en[-_]/i.test(v.lang));
    return vs.find(v => /natural|neural|google/i.test(v.name) && /en[-_](us|gb)/i.test(v.lang)) || vs.find(v => /en[-_](us|gb)/i.test(v.lang)) || vs[0];
  }
  function speak(text, { rate = 1, onend } = {}) {
    if (!("speechSynthesis" in window)) { onend?.(); return false; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text), v = pick();
    u.lang = v?.lang || "en-US"; if (v) u.voice = v; u.rate = rate;
    u.onend = u.onerror = () => onend?.();
    speechSynthesis.speak(u);
    return true;
  }
  const stop = () => { if ("speechSynthesis" in window) speechSynthesis.cancel(); };
  const plain = html => { const d = document.createElement("div"); d.innerHTML = html; return d.textContent; };
  return { SR, pick, speak, stop, plain };
})();

const Practice = (() => {
  let s = null, env = null, sayId = 0;
  const SR = Voice.SR;
  const pane = () => env?.pane();
  const T = () => env.track();
  const inl = t => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  // Agents.md plus fenced code blocks
  const mdx = t => String(t || "").split(/```[\w+.-]*\n?([\s\S]*?)```/g).map((x, i) => i % 2 ? `<pre class="pr-pre"><code>${esc(x.replace(/\n$/, ""))}</code></pre>` : Agents.md(x)).join("");
  const topicById = id => { for (const m of T().modules) for (const x of m.topics) if (x.id === id) return { id, title: x.title, done: x.done }; return null; };
  const norm = t => String(t || "").toLowerCase().replace(/[’‘`]/g, "'").replace(/[“”"]/g, "").replace(/\s+/g, " ").replace(/^[\s.,;:!?]+|[\s.,;:!?]+$/g, "");
  const words = t => String(t || "").replace(/[’‘]/g, "'").replace(/[-–—/]/g, " ").split(/\s+/).filter(Boolean);
  const wkey = w => w.toLowerCase().replace(/[^a-z0-9']/g, "");
  const pctOf = (a, b) => b ? Math.round(a / b * 100) : 0;

  // ---------- the session ----------
  // opts.step: a roadmap step to cover whole (testing out of it); the drill is then about all its topics
  function start(drill, e, opts = {}) {
    leave(); env = e;
    const picked = !opts.step && env.topic() && topicById(env.topic());
    s = { drill, mode: drill.mode, phase: "start", topic: opts.step ? null : picked || (drill.topic && topicById(drill.topic.id)), tutor: env.tutor(drill.agent), step: opts.step || null,
          seq: 0, loading: "", error: "", text: "", task: null, recorded: false,
          opts: { hands: !!SR, speak: "speechSynthesis" in window, minutes: 10 } };
    if (s.mode === "cards") loadDeck();
    if (s.mode === "writing" || s.mode === "code") s.phase = "edit";
    draw();
  }
  // stop everything that runs on its own: speech, listening, the session timer
  function quiet() { if (!s) return; stopListen(); hush(); clearInterval(s.timer); s.timer = null; }
  function leave() { quiet(); if (s?.wide) env?.wide(false); s = null; }
  const active = () => !!s;
  function back() { leave(); env.back(); }

  async function call(kind, extra, label, retry) {
    const mine = s, seq = ++s.seq;
    if (label) { s.loading = label; s.error = ""; draw(); }
    try {
      const r = await api("/api/study/practice", { method: "POST", body: { track: T().id, drill: s.drill.id, kind, topic: s.topic?.id || null, step: s.step?.id || null,
        material: env.material().map(x => ({ kind: x.kind, id: x.id })), model: env.model().model, ...extra } });
      if (s !== mine || seq !== s.seq) return null;
      s.loading = ""; return r;
    } catch (e) {
      if (s !== mine || seq !== s.seq) return null;
      s.loading = ""; if (label) { s.error = e.message; s.retry = retry; draw(); } else toast(e.message);
      return null;
    }
  }
  async function record(score = null, total = null) {
    if (s.recorded) return; s.recorded = true;
    try { env.recorded(await api("/api/study/practice/done", { method: "POST", body: { track: T().id, drill: s.drill.id, topic: s.topic?.id || null, score, total, today: env.today() } })); } catch {}
  }
  async function saveNote(text) {
    try {
      await api("/api/workspace/notes", { method: "POST", body: { text: text.slice(0, 4000), netuid: null, color: "blue" } });
      toast(text.length > 4000 ? "Saved to notes (cut to 4,000 characters)" : "Saved to notes"); Notes.load().catch(() => {});
    } catch (e) { toast(e.message); }
  }

  // ---------- drawing ----------
  function draw() {
    const el = pane(); if (!s || !el) return;
    const d = s.drill, t = s.topic;
    env.wide(!!s.wide);
    if (s.mode === "dialogue" && s.phase === "run" && !s.timer) startTimer();  // back from another tab mid-session
    el.innerHTML = `<div class="pr pr-${s.mode}">
      <div class="pr-head"><button type="button" class="btn sm" data-pr="back">${icon("left")}Drills</button>
        <span class="st-drill-ic">${icon(d.icon)}</span>
        <div class="pr-title"><b>${esc(s.step ? `Test out: step ${s.step.n}` : d.title)}</b><small class="faint">${s.step ? esc(s.step.title) : t ? esc(t.title) : esc(T().title)}${s.tutor ? ` · with ${esc(s.tutor.name)}` : ""}</small>
          ${env.material().length ? `<small class="pr-mats" title="${esc(env.material().map(x => x.label).join(", "))}">${icon("clip")}From your material: ${esc(env.material().map(x => x.label.split("/").pop()).join(", "))}</small>` : ""}</div>
${headExtra()}</div>
      <div class="card pr-body">${s.loading ? Loading.line(esc(s.loading)) : s.error ? `<div class="pr-error">${icon("alert")}<p>${esc(s.error)}</p>
        <div class="row">${s.retry ? `<button type="button" class="btn primary" data-pr="retry-call">${icon("reset")}Try again</button>` : ""}<button type="button" class="btn" data-pr="back">Back to drills</button></div></div>` : body()}</div></div>`;
    after();
  }
  function headExtra() {
    if (s.mode === "dialogue" && s.phase === "run") return `<span class="pr-timer" title="Session time">${icon("clock")}<span>${clock()}</span>${s.opts.minutes ? ` / ${s.opts.minutes}:00` : ""}</span>`;
    if (s.q && !s.q.finished && (s.mode === "quiz" || s.mode === "lesson")) return `<span class="faint small">${s.q.i + 1} / ${s.q.items.length}</span>`;
    if (s.list && s.phase === "run") return `<span class="faint small">${s.list.i + 1} / ${s.list.items.length}</span>`;
    return "";
  }
  function body() {
    const m = MODES[s.mode];
    return (m[s.phase] || m.start)();
  }
  function after() {  // focus where the learner types next
    const f = pane()?.querySelector("[data-pr-focus]");
    if (f && !f.disabled) { f.focus(); if (f.setSelectionRange && f.value) f.setSelectionRange(f.value.length, f.value.length); }
    const log = pane()?.querySelector(".pr-log"); if (log) log.scrollTop = log.scrollHeight;
  }
  // the topic the drill is about: any topic on the track, or none for drills that work without one
  function topicPicker(none = false) {
    if (s.step) return `<p class="pr-field pr-step">${icon("route")}<span>Covers all of step ${s.step.n}, <b>${esc(s.step.title)}</b>: ${esc(s.step.list.map(x => x.title).join("; "))}. Score 80% or more to pass it.</span></p>`;
    const cur = s.topic?.id || "";
    return `<label class="pr-field"><span>Topic</span><select data-pr-topic>${none ? `<option value="">${T().id === "english" ? "Anything useful for my level" : "Pick for me"}</option>` : ""}
      ${T().modules.map(m => `<optgroup label="${esc(m.title)}">${m.topics.map(x => `<option value="${esc(x.id)}" ${x.id === cur ? "selected" : ""}>${x.done ? "✓ " : ""}${esc(x.title)}</option>`).join("")}</optgroup>`).join("")}</select></label>`;
  }
  const startCard = (what, action, label, extra = "", none = false) => `<div class="pr-start"><p>${what}</p>${topicPicker(none)}${extra}
    <div class="row"><button type="button" class="btn primary" data-pr="${action}">${icon("sparkle")}${label}</button></div>
    ${s.tutor ? "" : `<p class="faint small">${env.agentsOn() ? "Create the study team to give this drill its tutor; it still works without one." : ""}</p>`}</div>`;
  const resultHead = (score, total, label) => {
    const p = pctOf(score, total);
    return `<div class="pr-result-top"><div class="pr-score ${p >= 80 ? "good" : p >= 50 ? "mid" : "low"}"><b>${fmtNum(score, score % 1 ? 1 : 0)}</b><span>/ ${total}</span></div>
      <div><h3>${p >= 90 ? "Excellent!" : p >= 80 ? "Great work" : p >= 50 ? "Good effort" : "Keep practising"}</h3><p class="muted">${label} · ${p}%</p></div></div>`;
  };
  const tickButton = p => s.step ? (p >= 80 ? `<button type="button" class="btn primary" data-pr="pass-step">${icon("check")}Pass step ${s.step.n}: tick its topics</button>` : `<span class="faint small">80% passes the step. You're ${80 - p} points away.</span>`)
    : s.topic && !topicById(s.topic.id)?.done && p >= 80 ? `<button type="button" class="btn primary" data-pr="tick">${icon("check")}Tick “${esc(s.topic.title)}”</button>` : "";

  // ---------- questions (quiz, and the lesson's check) ----------
  const runner = items => ({ items, i: 0, answers: items.map(() => ({ given: "", verdict: null })), finished: false, round: 1 });
  function drawQuestion() {
    const q = s.q, it = q.items[q.i], a = q.answers[q.i], done = !!a.verdict;
    const dots = q.items.map((_, k) => `<i class="${q.answers[k].verdict || ""} ${k === q.i ? "now" : ""}"></i>`).join("");
    const label = { choice: "Choose one", gap: "Fill the gap", transform: "Rewrite", short: "Answer in your own words" }[it.type];
    const input = it.type === "choice"
      ? `<div class="pr-opts">${it.options.map((o, k) => `<button type="button" class="pr-opt ${done ? (k === it.correct ? "right" : k === a.pick ? "wrong" : "") : ""}" data-pr-opt="${k}" ${done ? "disabled" : ""}><span>${"ABCDEF"[k]}</span><span>${inl(o)}</span></button>`).join("")}</div>`
      : `<${it.type === "short" ? "textarea rows=\"4\"" : "input"} class="pr-answer" data-pr-answer ${done || a.checking ? "disabled" : "data-pr-focus"} placeholder="${it.type === "short" ? "Type your answer (Ctrl+Enter to check)" : "Type your answer and press Enter"}" ${it.type === "short" ? "" : `value="${esc(a.given)}"`}>${it.type === "short" ? `${esc(a.given)}</textarea>` : ""}
         ${done ? "" : `<div class="row"><button type="button" class="btn primary ${a.checking ? "loading" : ""}" data-pr="check" ${a.checking ? "disabled" : ""}>${a.checking ? "Checking…" : "Check"}</button><button type="button" class="btn" data-pr="skip" ${a.checking ? "disabled" : ""}>I don't know</button></div>`}`;
    const right = it.type === "choice" ? it.options[it.correct] : a.better || it.answers?.[0] || "";
    return `<div class="pr-progress" aria-hidden="true">${dots}</div>
      <div class="pr-q"><small class="faint">Question ${q.i + 1} of ${q.items.length} · ${label}</small>
        <div class="pr-prompt">${mdx(it.prompt)}</div>${input}
        ${done ? `<div class="pr-fb ${a.verdict}">${icon(a.verdict === "correct" ? "check" : a.verdict === "partly" ? "info" : "close")}<div>
            <b>${a.verdict === "correct" ? "Correct" : a.verdict === "partly" ? "Partly right" : "Not quite"}</b>${a.feedback ? ` ${inl(a.feedback)}` : ""}
            ${a.verdict !== "correct" && right ? `<p><span class="faint">Answer:</span> ${inl(right)}</p>` : ""}
            ${it.explanation ? `<p class="muted">${inl(it.explanation)}</p>` : ""}</div></div>
          <div class="row end"><button type="button" class="btn primary" data-pr="next-q" data-pr-focus>${q.i + 1 < q.items.length ? `Next${icon("right")}` : "See results"}</button></div>` : ""}</div>`;
  }
  async function check(skip = false) {
    const q = s.q, it = q.items[q.i], a = q.answers[q.i], mine = s;
    if (a.verdict || a.checking) return;
    if (!skip) a.given = pane().querySelector("[data-pr-answer]")?.value.trim() || "";
    if (!skip && !a.given) return toast("Type an answer first, or press I don't know");
    if (skip) { a.verdict = "wrong"; return draw(); }
    if ((it.type === "gap" || it.type === "transform") && (it.answers || []).some(x => norm(x) === norm(a.given))) { a.verdict = "correct"; return draw(); }
    a.checking = true; draw();
    const r = await call("grade", { question: it.prompt, answers: it.answers || [], text: a.given });
    if (s !== mine) return;
    a.checking = false;
    if (r) Object.assign(a, { verdict: r.data.verdict, feedback: r.data.feedback, better: r.data.better });
    draw();
  }
  function pickOption(k) {
    const q = s.q, it = q.items[q.i], a = q.answers[q.i];
    if (a.verdict) return;
    Object.assign(a, { pick: k, given: it.options[k], verdict: k === it.correct ? "correct" : "wrong" });
    draw();
  }
  function nextQuestion() {
    const q = s.q;
    if (q.i + 1 < q.items.length) { q.i++; return draw(); }
    q.finished = true;
    const { score, total } = quizScore();
    if (q.round === 1) record(score, total);
    draw();
  }
  const quizScore = () => ({ score: s.q.answers.reduce((n, a) => n + (a.verdict === "correct" ? 1 : a.verdict === "partly" ? 0.5 : 0), 0), total: s.q.items.length });
  function drawQuizResult() {
    const q = s.q, { score, total } = quizScore(), p = pctOf(score, total);
    const missed = q.items.map((it, k) => ({ it, a: q.answers[k] })).filter(x => x.a.verdict !== "correct");
    return resultHead(score, total, q.round > 1 ? "Retry round" : `${total} questions`) + `
      ${missed.length ? `<h4>Review</h4><ol class="pr-review">${missed.map(({ it, a }) => `<li><div class="pr-prompt small">${mdx(it.prompt)}</div>
          <p><span class="faint">You:</span> ${a.given ? inl(a.given) : "<i>no answer</i>"}</p><p><span class="faint">Answer:</span> ${inl(it.type === "choice" ? it.options[it.correct] : a.better || it.answers?.[0] || "")}</p></li>`).join("")}</ol>` : ""}
      <div class="row">${tickButton(p)}${missed.length ? `<button type="button" class="btn" data-pr="retry-missed">${icon("reset")}Retry the ${missed.length} I missed</button>` : ""}
        ${missed.length && s.tutor ? `<button type="button" class="btn" data-pr="ask-missed">${icon("chat")}Ask ${esc(s.tutor.name)} about them</button>` : ""}
        <button type="button" class="btn" data-pr="again">${icon("sparkle")}New ${s.mode === "lesson" ? "lesson" : "set"}</button></div>`;
  }
  function retryMissed() {
    const q = s.q, items = q.items.filter((_, k) => q.answers[k].verdict !== "correct");
    s.q = { ...runner(items), round: q.round + 1 }; draw();
  }
  function askMissed() {
    const q = s.q, missed = q.items.map((it, k) => ({ it, a: q.answers[k] })).filter(x => x.a.verdict !== "correct");
    env.ask(s.tutor, `I got these wrong in a ${s.drill.title.toLowerCase()} on "${s.topic?.title || T().title}". Can you help me understand them?\n\n`
      + missed.map(({ it, a }, k) => `${k + 1}. ${it.prompt.replace(/\s+/g, " ").slice(0, 300)}\n   My answer: ${a.given || "(none)"}\n   The answer: ${it.type === "choice" ? it.options[it.correct] : a.better || it.answers?.[0] || ""}`).join("\n"));
  }

  // ---------- word matching (pronunciation and dictation) ----------
  // the target's words, each marked heard or missed, plus words that weren't in the target; score = share of target words matched
  function align(target, got) {
    const a = words(target).map(w => ({ w, k: wkey(w) })).filter(x => x.k), b = words(got).map(w => ({ w, k: wkey(w) })).filter(x => x.k);
    const n = a.length, m = b.length, dp = new Uint16Array((n + 1) * (m + 1)), at = (i, j) => i * (m + 1) + j;
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[at(i, j)] = a[i].k === b[j].k ? dp[at(i + 1, j + 1)] + 1 : Math.max(dp[at(i + 1, j)], dp[at(i, j + 1)]);
    const out = []; let i = 0, j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && a[i].k === b[j].k) { out.push({ w: a[i].w, t: "ok" }); i++; j++; }
      else if (j < m && (i >= n || dp[at(i, j + 1)] >= dp[at(i + 1, j)])) { out.push({ w: b[j].w, t: "extra" }); j++; }
      else { out.push({ w: a[i].w, t: "miss" }); i++; }
    }
    return { out, score: n ? dp[0] / n : 0 };
  }
  const aligned = r => `<p class="pr-heard">${r.out.map(x => `<span class="${x.t}">${esc(x.w)}</span>`).join(" ")}</p>`;
  const stressed = t => esc(t).replace(/([A-Z]{2,})/g, `<b class="pr-st">$1</b>`);

  // ---------- modes ----------
  const MODES = {
    // a short lesson, then three questions
    lesson: {
      start: () => startCard("A short lesson: the idea, how it works and how it's used, with a misconception to avoid and three questions at the end.", "gen-lesson", "Teach me"),
      run: () => {
        const L = s.data;
        return `<article class="pr-lesson"><h2>${esc(L.title)}</h2><p class="lead">${inl(L.summary)}</p>
          ${L.sections.map(x => `<section><h3>${esc(x.heading)}</h3>${mdx(x.body)}</section>`).join("")}
          ${L.code ? `<section><h3>Example${L.code_language ? ` <span class="tag">${esc(L.code_language)}</span>` : ""}</h3><pre class="pr-pre"><code>${esc(L.code)}</code></pre>
            <button type="button" class="btn sm" data-pr="copy-code">${icon("copy")}Copy code</button></section>` : ""}
          ${L.misconception ? `<div class="pr-callout">${icon("alert")}<div><b>Common misconception</b><p>${inl(L.misconception)}</p></div></div>` : ""}</article>
          <div class="pr-check">${!s.q ? `<div class="row"><button type="button" class="btn primary" data-pr="lesson-check" ${L.check.length ? "" : "disabled"}>${icon("target")}Check your understanding</button>
              ${s.tutor ? `<button type="button" class="btn" data-pr="lesson-ask">${icon("chat")}Ask ${esc(s.tutor.name)} a question</button>` : ""}
              <button type="button" class="btn" data-pr="save-lesson">${icon("note")}Save to notes</button></div>`
            : s.q.finished ? drawQuizResult() : drawQuestion()}</div>`;
      },
    },
    quiz: {
      start: () => startCard(s.drill.id === "grammar" ? "Eight sentences to rewrite and complete, checked as you go. Exact answers are checked here; anything else, your tutor model judges, so other correct answers count." : "Six questions: multiple choice, short answers and spot-the-gap, graded as you go.", "gen-quiz", "Start"),
      run: () => s.q.finished ? drawQuizResult() : drawQuestion(),
    },
    // flashcards: a deck per track with spaced repetition
    cards: {
      start: () => {
        const D = s.deck;
        if (!D) return Loading.line("Loading your deck…");
        return `<div class="pr-deckhead"><div><b>${D.due}</b> due today <span class="faint">· ${D.total} card${D.total === 1 ? "" : "s"} in your ${esc(T().title)} deck</span></div>
            <button type="button" class="btn primary" data-pr="review" ${D.due ? "" : "disabled"}>${icon("cycle")}Review ${D.due || ""}</button></div>
          ${env.agentsOn() ? `<div class="pr-gen"><p class="muted small">${T().id === "english" ? "New words and phrases come with IPA, register, an example and collocations. Cards you know come back less often; ones you miss come back soon." : "New cards cover the key terms of a topic, with an example and a common pitfall. Cards you know come back less often; ones you miss come back soon."}</p>
            <div class="pr-gen-row">${topicPicker(T().id === "english")}<button type="button" class="btn" data-pr="gen-cards">${icon("sparkle")}Write 6 new cards</button></div></div>` : ""}
          ${s.fresh ? `<div class="pr-fresh"><h4>New cards <span class="faint">untick any you don't want</span></h4>${s.fresh.map((c, k) => `<label class="pr-fresh-card"><input type="checkbox" data-pr-keep="${k}" ${c.keep ? "checked" : ""}>
              <span><b>${esc(c.front)}</b>${c.ipa ? ` <span class="pr-ipa">${esc(c.ipa)}</span>` : ""}<small>${inl(c.back)}</small></span></label>`).join("")}
              <div class="row"><button type="button" class="btn primary" data-pr="add-cards">${icon("plus")}Add ${s.fresh.filter(c => c.keep).length} to my deck</button><button type="button" class="btn" data-pr="drop-cards">Discard</button></div></div>` : ""}
          ${D.total ? `<details class="pr-decklist"><summary>All cards (${D.total})</summary><ul>${D.cards.map(c => `<li><span><b>${esc(c.front)}</b> <small class="faint">${esc(c.back)}</small></span>
              <small class="faint" title="Next review">${c.due <= env.today() ? "due" : esc(c.due)}</small><button type="button" class="iconbtn sm" data-pr-del="${c.id}" aria-label="Delete ${esc(c.front)}" title="Delete">${icon("trash")}</button></li>`).join("")}</ul></details>` : ""}`;
      },
      run: () => {
        const L = s.list, c = L.items[L.i];
        if (!c) {
          return resultHead(L.ok, L.reviewed, `${L.reviewed} review${L.reviewed === 1 ? "" : "s"}`) + `<p class="muted">Cards you knew come back in a few days; the ones you missed, sooner.</p>
            <div class="row"><button type="button" class="btn primary" data-pr="deck">${icon("book")}Back to the deck</button></div>`;
        }
        const iv = g => { const n = nextInterval(c, g); return n === 0 ? "today" : n === 1 ? "1 day" : n < 30 ? `${n} days` : `${Math.round(n / 30)} mo`; };
        return `<div class="pr-flash ${L.flipped ? "flipped" : ""}">
          <div class="pr-flash-front"><b>${esc(c.front)}</b>${c.ipa ? `<span class="pr-ipa">${esc(c.ipa)}</span>` : ""}
            <button type="button" class="iconbtn sm" data-pr="say-card" title="Hear it" aria-label="Hear it">${icon("speaker")}</button></div>
          ${L.flipped ? `<div class="pr-flash-back"><p>${inl(c.back)}</p>${c.example ? `<p class="pr-ex">“${inl(c.example)}”</p>` : ""}${c.extra ? `<p class="faint small">${inl(c.extra)}</p>` : ""}</div>
            <div class="pr-grades">${[["again", "Again"], ["hard", "Hard"], ["good", "Good"], ["easy", "Easy"]].map(([g, l], k) => `<button type="button" class="btn pr-g-${g}" data-pr-grade="${g}" title="Key ${k + 1}"><b>${l}</b><small>${iv(g)}</small></button>`).join("")}</div>`
          : `<button type="button" class="btn primary" data-pr="flip" data-pr-focus>Show answer <span class="faint">Space</span></button>`}</div>
          <p class="faint small pr-keys">${L.items.length - L.i} left · Space shows the answer, 1–4 grade it</p>`;
      },
    },
    pron: {
      start: () => startCard(`Six sentences to say out loud. Listen first, then press <b>Say it</b> and read the sentence: the words the speech recognition heard are matched to the sentence, so a missed word is usually a sound to work on.${SR ? "" : `</p><p class="pr-warn">${icon("alert")}Your browser has no speech recognition. Use Chrome or Edge to be scored; you can still listen and practise.`}`, "gen-pron", "Start", "", true),
      run: () => {
        const L = s.list, x = L.items[L.i];
        if (!x) {
          const total = L.items.length, score = L.best.reduce((n, b) => n + (b || 0), 0) / 100;
          return resultHead(Math.round(score * 10) / 10, total, "best attempt per sentence") + `<ol class="pr-review">${L.items.map((it, k) => `<li><p>${esc(it.text)}</p><p class="faint small">Best: ${L.best[k] ?? 0}% · ${esc(it.focus)}</p></li>`).join("")}</ol>
            <div class="row"><button type="button" class="btn primary" data-pr="again">${icon("sparkle")}New sentences</button></div>`;
        }
        const r = L.heard[L.i];
        return `<div class="pr-say-box"><p class="pr-say">${esc(x.text)}</p><p class="pr-stress" title="Stressed syllables in capitals">${stressed(x.stressed)}</p>
            <p class="small"><span class="tag">Focus</span> ${inl(x.focus)}</p>
            <div class="row"><button type="button" class="btn" data-pr="listen">${icon("speaker")}Listen</button><button type="button" class="btn" data-pr="listen-slow">${icon("speaker")}Slowly</button>
              ${SR ? `<button type="button" class="btn primary pr-rec ${s.rec ? "on" : ""}" data-pr="record">${s.rec ? `${icon("stop")}Stop` : `${micSvg()}Say it`}</button>` : ""}</div>
            ${s.rec ? `<p class="faint small">Listening… read the sentence, then pause.</p>` : ""}
            ${r ? `${aligned(r)}<p class="pr-attempt ${r.score >= 0.9 ? "good" : r.score >= 0.6 ? "mid" : "low"}"><b>${Math.round(r.score * 100)}%</b> of the words came through${L.best[L.i] != null ? ` · best ${L.best[L.i]}%` : ""}</p>
              <p class="faint small">Words in red weren't heard${r.out.some(w => w.t === "extra") ? "; struck-through words were heard instead" : ""}.</p>` : ""}
            <p class="muted small">${icon("bulb")} ${inl(x.tip)}</p></div>
          <div class="row end"><button type="button" class="btn ${r ? "primary" : ""}" data-pr="next-item">${L.i + 1 < L.items.length ? `Next sentence${icon("right")}` : "See results"}</button></div>`;
      },
    },
    dictation: {
      start: () => startCard("Listen to a short passage of natural speech, one sentence at a time, and type what you hear. Replay as often as you like, slowly if you need to.", "gen-dictation", "Start", "", true),
      run: () => {
        const L = s.list, x = L.items[L.i];
        if (!x) {
          const score = L.scores.reduce((n, v) => n + (v || 0), 0);
          return resultHead(Math.round(score * 10) / 10, L.items.length, "words caught per sentence") + `<ol class="pr-review">${L.items.map((it, k) => `<li><p>${esc(it)}</p><p class="faint small">You: ${esc(L.typed[k] || "—")}</p></li>`).join("")}</ol>
            ${s.data.glossary?.length ? `<h4>Words to know</h4><ul class="pr-gloss">${s.data.glossary.map(g => `<li><b>${esc(g.term)}</b>: ${esc(g.meaning)}</li>`).join("")}</ul>` : ""}
            <div class="row"><button type="button" class="btn primary" data-pr="again">${icon("sparkle")}New passage</button></div>`;
        }
        const r = L.checked[L.i];
        return `<div class="pr-say-box"><p class="faint small">${esc(s.data.title)} · sentence ${L.i + 1} of ${L.items.length}</p>
            <div class="row"><button type="button" class="btn primary" data-pr="play">${icon("play")}Play</button><button type="button" class="btn" data-pr="play-slow">${icon("speaker")}Slowly</button></div>
            <input class="pr-answer" data-pr-dict ${r ? "disabled" : "data-pr-focus"} placeholder="Type what you hear, then press Enter" value="${esc(L.typed[L.i] || "")}" autocomplete="off" spellcheck="false">
            ${r ? `${aligned(r)}<p class="pr-attempt ${r.score >= 0.9 ? "good" : r.score >= 0.6 ? "mid" : "low"}"><b>${Math.round(r.score * 100)}%</b> · ${esc(x)}</p>` : `<div class="row"><button type="button" class="btn" data-pr="check-dict">Check</button></div>`}</div>
          ${r ? `<div class="row end"><button type="button" class="btn primary" data-pr="next-item" data-pr-focus>${L.i + 1 < L.items.length ? `Next sentence${icon("right")}` : "See results"}</button></div>` : ""}`;
      },
    },
    writing: {
      edit: () => {
        const n = words(s.text).length, w = s.task?.words;
        return `${s.task ? `<div class="pr-task"><div class="row"><span class="tag">${esc(s.task.kind)}</span><span class="faint small">about ${w} words</span></div>${mdx(s.task.task)}
            ${s.task.tips?.length ? `<ul class="ws-ul">${s.task.tips.map(x => `<li>${inl(x)}</li>`).join("")}</ul>` : ""}</div>` : `<p class="muted">Paste something you wrote (an email, a message, an essay, a design doc) or get a task to write to. You'll see every correction with the reason, and your CEFR level.</p>`}
          <textarea class="pr-editor prose" data-pr-text data-pr-focus rows="12" maxlength="6000" placeholder="Write or paste your text here…">${esc(s.text)}</textarea>
          <div class="row"><span class="faint small" data-pr-count>${n} word${n === 1 ? "" : "s"}${w ? ` of about ${w}` : ""}</span><span class="ac-spacer"></span>
            <button type="button" class="btn" data-pr="gen-task">${icon("sparkle")}${s.task ? "Another task" : "Give me a task"}</button>
            <button type="button" class="btn primary" data-pr="check-writing">${icon("check")}Check my writing</button></div>`;
      },
      result: () => {
        const R = s.data, ops = diff(s.sent, R.corrected);
        return `<div class="pr-result-top"><span class="pr-level">${esc(R.level)}</span><div><h3>Your level for this text: ${esc(R.level)}</h3><p class="muted">${inl(R.next_level)}</p></div></div>
          <div class="seg pr-seg"><button type="button" data-pr-view="diff" aria-pressed="${s.view !== "clean"}">Changes</button><button type="button" data-pr-view="clean" aria-pressed="${s.view === "clean"}">Corrected text</button></div>
          <div class="pr-diff">${s.view === "clean" ? esc(R.corrected).replace(/\n/g, "<br>") : ops}</div>
          ${R.changes.length ? `<h4>Why</h4><ul class="pr-changes">${R.changes.map(c => `<li><span class="tag">${esc(c.kind)}</span><span><del>${esc(c.original)}</del> → <ins>${esc(c.fixed)}</ins><small>${inl(c.why)}</small></span></li>`).join("")}</ul>` : `<p class="muted">Nothing to fix. Impressive!</p>`}
          ${R.strengths.length ? `<h4>What works</h4><ul class="ws-ul">${R.strengths.map(x => `<li>${inl(x)}</li>`).join("")}</ul>` : ""}
          <div class="row"><button type="button" class="btn primary" data-pr="edit">${icon("edit")}Edit and check again</button><button type="button" class="btn" data-pr="copy-corrected">${icon("copy")}Copy corrected text</button>
            <button type="button" class="btn" data-pr="save-writing">${icon("note")}Save to notes</button><button type="button" class="btn" data-pr="new-writing">${icon("sparkle")}New task</button></div>`;
      },
    },
    code: {
      edit: () => `${s.task ? `<div class="pr-task"><h3>${esc(s.task.title)}</h3>${mdx(s.task.task)}
            ${s.task.hints?.length ? `<details><summary>Hints (${s.task.hints.length})</summary><ul class="ws-ul">${s.task.hints.map(x => `<li>${inl(x)}</li>`).join("")}</ul></details>` : ""}
            ${s.task.checks?.length ? `<details><summary>What a good solution handles</summary><ul class="ws-ul">${s.task.checks.map(x => `<li>${inl(x)}</li>`).join("")}</ul></details>` : ""}</div>`
          : `<p class="muted">Get an exercise on the topic, or paste your own code for a senior engineer's review: correctness, failure modes, security and cost, line by line.</p>${topicPicker()}`}
        <textarea class="pr-editor" data-pr-text data-pr-focus rows="16" maxlength="12000" spellcheck="false" placeholder="# Write or paste Python here…">${esc(s.text)}</textarea>
        <div class="row"><span class="faint small">${s.text ? `${s.text.split("\n").length} lines` : "Tab indents"}${env.run ? " · Ctrl+Enter runs" : ""}</span><span class="ac-spacer"></span>
          ${env.run ? `<button type="button" class="btn ${s.run?.live ? "loading" : ""}" data-pr="run-code" title="Run it in your browser (Ctrl+Enter)" ${s.run?.live ? "disabled" : ""}>${icon("play")}Run</button>` : ""}
          ${env.openLab ? `<button type="button" class="btn" data-pr="code-lab" title="Keep working on it in the Lab's Python tab">${icon("terminal")}Open in Lab</button>` : ""}
          <button type="button" class="btn" data-pr="gen-code-task">${icon("sparkle")}${s.task ? "Another exercise" : "Give me an exercise"}</button>
          <button type="button" class="btn primary" data-pr="review-code">${icon("search")}Review my code</button></div>
        ${s.run ? runPanel() : ""}`,
      result: () => {
        const R = s.data, lines = s.sent.split("\n"), byLine = {};
        R.issues.forEach((x, k) => { if (x.line > 0) (byLine[x.line] = byLine[x.line] || []).push(k); });
        const sev = x => ({ critical: "scam", major: "avoid", minor: "caution", nit: "new" }[x] || "new");
        return resultHead(R.score, 10, "review score") + `<p>${inl(R.summary)}</p>
          ${R.issues.length ? `<ol class="pr-issues">${R.issues.map((x, k) => `<li id="pr-issue-${k}"><span class="badge ${sev(x.severity)}">${esc(x.severity)}</span>${x.line > 0 ? `<button type="button" class="linkbtn" data-pr-line="${x.line}">line ${x.line}</button>` : ""}
              <span>${inl(x.issue)}<small>${inl(x.fix)}</small></span></li>`).join("")}</ol>` : ""}
          <div class="pr-lines">${lines.map((l, k) => `<div class="${byLine[k + 1] ? `hl ${sev(R.issues[byLine[k + 1][0]].severity)}` : ""}" id="pr-line-${k + 1}"><span>${k + 1}</span><code>${esc(l) || " "}</code></div>`).join("")}</div>
          ${R.improved ? `<h4>Improved</h4><pre class="pr-pre"><code>${esc(R.improved)}</code></pre>` : ""}
          <div class="row"><button type="button" class="btn primary" data-pr="edit">${icon("edit")}Revise and review again</button>${R.improved ? `<button type="button" class="btn" data-pr="copy-improved">${icon("copy")}Copy improved code</button>` : ""}
            <button type="button" class="btn" data-pr="gen-code-task">${icon("sparkle")}New exercise</button></div>`;
      },
    },
    plan: {
      start: () => `<div class="pr-start"><p>A seven-day plan from your next topics on the ${esc(T().title)} path${T().goal ? ` and your goal (${esc(T().goal)})` : ""}: a task a day, one build task, and how you'll prove it at the end of the week.</p>
        <div class="row"><button type="button" class="btn primary" data-pr="gen-plan">${icon("sparkle")}Make my plan</button></div></div>`,
      run: () => {
        const P = s.data;
        return `<h3 class="pr-h">${inl(P.goal)}</h3><div class="tablewrap"><table class="grid pr-table"><thead><tr><th>Day</th><th>Topic</th><th>Task</th><th class="r">Min</th><th>Done when</th></tr></thead>
          <tbody>${P.days.map(x => `<tr><td><b>${esc(x.day)}</b></td><td>${esc(x.topic)}</td><td>${inl(x.task)}</td><td class="r num">${x.minutes}</td><td class="faint">${inl(x.done_when)}</td></tr>`).join("")}</tbody></table></div>
          <div class="ws-grid2"><div class="pr-callout">${icon("zap")}<div><b>Build task</b><p>${inl(P.build_task)}</p></div></div><div class="pr-callout">${icon("target")}<div><b>Prove it</b><p>${inl(P.check)}</p></div></div></div>
          <div class="row"><button type="button" class="btn primary" data-pr="save-plan">${icon("note")}Save to notes</button><button type="button" class="btn" data-pr="gen-plan">${icon("reset")}Make another</button></div>`;
      },
    },
    project: {
      start: () => startCard("A portfolio project sized for one or two weekends that shows real AI engineering: evaluation, cost and failure handling, not just a demo.", "gen-project", "Suggest a project"),
      run: () => {
        const P = s.data;
        return `<h2 class="pr-h">${esc(P.title)}</h2><p class="lead">${inl(P.pitch)}</p>
          <div class="chips">${P.skills.map(x => `<span class="tag">${esc(x)}</span>`).join("")}</div>
          <p class="small"><span class="faint">Stack:</span> ${P.stack.map(esc).join(" · ")}</p>
          <ol class="pr-milestones">${P.milestones.map(m => `<li><b>${esc(m.title)}</b><ul class="ws-ul">${m.tasks.map(x => `<li>${inl(x)}</li>`).join("")}</ul><p class="faint small">Done when: ${inl(m.done_when)}</p></li>`).join("")}</ol>
          <div class="pr-callout">${icon("chart")}<div><b>How to measure it</b><p>${inl(P.evaluation)}</p></div></div>
          ${P.stretch.length ? `<h4>Stretch</h4><ul class="ws-ul">${P.stretch.map(x => `<li>${inl(x)}</li>`).join("")}</ul>` : ""}
          <div class="row"><button type="button" class="btn primary" data-pr="save-project">${icon("note")}Save to notes</button><button type="button" class="btn" data-pr="gen-project">${icon("reset")}Another idea</button></div>`;
      },
    },
    // a voice session with a tutor, then a feedback report
    dialogue: {
      start: () => {
        const a = s.tutor;
        if (!a) return `<div class="pr-start"><p class="muted">${env.agentsOn() ? "This drill is a spoken session with a tutor: create the study team first (the button is in the chat panel)." : "This drill is a spoken session with a tutor agent, and agents are available to administrators."}</p></div>`;
        return `<div class="pr-start pr-dlg-start">${agentAvatar(a, "xl")}<div><h3>${esc(a.name)} <span class="faint">· ${esc(a.role)}</span></h3><p>${esc(s.drill.blurb)}</p>
          ${SR ? `<label class="toggle-row"><span><b>Hands-free</b><small class="faint">Talk, pause, and it sends; ${esc(a.name)} answers out loud and listens again</small></span><span class="switch"><input type="checkbox" data-pr-opt-hands ${s.opts.hands ? "checked" : ""}><span></span></span></label>`
            : `<p class="pr-warn">${icon("alert")}No speech recognition in this browser (try Chrome or Edge): you can type your side.</p>`}
          <label class="toggle-row"><span><b>Read replies aloud</b><small class="faint">Hear natural English as you go</small></span><span class="switch"><input type="checkbox" data-pr-opt-speak ${s.opts.speak ? "checked" : ""}><span></span></span></label>
          <label class="pr-field"><span>Length</span><select data-pr-minutes>${[5, 10, 15, 20].map(m => `<option value="${m}" ${m === s.opts.minutes ? "selected" : ""}>${m} minutes</option>`).join("")}</select></label>
          ${s.drill.id !== "talk" && s.drill.id !== "debate" ? "" : topicPicker(true)}
          <p class="faint small">Each session starts a fresh chat with ${esc(a.name)}; earlier chats stay in the Agents tab. At the end you get a report on what you said.</p>
          <div class="row"><button type="button" class="btn primary" data-pr="dlg-start">${micSvg()}Start session</button></div></div></div>`;
      },
      run: () => {
        const a = s.tutor, items = s.items || [];
        const firstUser = items.findIndex(i => i.kind === "user");
        return `<div class="pr-log" aria-live="polite">${items.map((i, n) => n === firstUser ? `<div class="note">${icon("info")}<span>Session started: ${esc(a.name)} opens.</span></div>`
            : i.kind === "user" ? `<div class="msg me"><div class="bubble">${esc(i.text)}</div></div>`
            : i.kind === "assistant" ? `<div class="msg bot">${agentAvatar(a, "sm")}<div class="bubble">${mdx(i.text)}</div><button type="button" class="iconbtn sm pr-say-btn" data-pr-say="${n}" title="Hear it again" aria-label="Hear it again">${icon("speaker")}</button></div>`
            : i.kind === "note" ? `<div class="note">${icon("info")}<span>${esc(i.text)}</span></div>` : "").join("")}
            ${s.busy ? `<div class="msg bot">${agentAvatar(a, "sm")}<div class="bubble typing" role="status"><span class="dots"><i></i><i></i><i></i></span></div></div>` : ""}</div>
          <div class="pr-dlg-bar">${micHtml()}
            <textarea class="pr-draft" data-pr-draft rows="2" maxlength="4000" placeholder="${SR ? "Speak, or type here (Enter to send)" : "Type your answer (Enter to send)"}" ${s.busy ? "disabled" : ""}>${esc(s.draft || "")}</textarea>
            <button type="button" class="btn primary" data-pr="dlg-send" ${s.busy ? "disabled" : ""} aria-label="Send">${icon("send")}</button></div>
          <div class="row pr-dlg-foot">${SR ? `<label class="chk"><input type="checkbox" data-pr-opt-hands ${s.opts.hands ? "checked" : ""}> Hands-free</label>` : ""}
            <label class="chk"><input type="checkbox" data-pr-opt-speak ${s.opts.speak ? "checked" : ""}> Read replies aloud</label><span class="ac-spacer"></span>
            ${s.drill.id === "design" ? `<button type="button" class="btn" data-pr="dlg-board" title="Sketch your design in Whiteboard, then add it here as text">${icon("sticky")}Add my whiteboard</button>` : ""}
            <button type="button" class="btn" data-pr="dlg-end" ${items.some((i, n) => i.kind === "user" && n !== firstUser) ? "" : "disabled title=\"Say something first\""}>${icon("check")}End &amp; get feedback</button></div>`;
      },
      report: () => {
        const R = s.data;
        const total = R.scores.reduce((n, x) => n + (x.score || 0), 0), max = R.scores.reduce((n, x) => n + (x.max || 0), 0);
        return `<div class="pr-result-top"><span class="pr-level">${esc(R.level)}</span><div><h3>${inl(R.verdict)}</h3><p class="muted">${inl(R.summary)}</p></div></div>
          <div class="pr-scores">${R.scores.map(x => `<div><span>${esc(x.criterion)}</span><div class="bar big"><i style="width:${pctOf(x.score, x.max)}%"></i></div><b>${x.score}/${x.max}</b><small class="faint">${inl(x.note)}</small></div>`).join("")}</div>
          ${R.fixes.length ? `<h4>Fix these</h4><div class="tablewrap"><table class="grid pr-table"><thead><tr><th>You said</th><th>Better</th><th>Why</th></tr></thead>
            <tbody>${R.fixes.map(f => `<tr><td><del>${esc(f.said)}</del></td><td><ins>${esc(f.better)}</ins></td><td class="faint">${inl(f.why)}</td></tr>`).join("")}</tbody></table></div>` : ""}
          ${R.upgrades.length ? `<h4>Level up</h4><ul class="pr-upgrades">${R.upgrades.map(u => `<li><b>${esc(u.phrase)}</b><button type="button" class="iconbtn sm" data-pr-hear="${esc(u.example)}" title="Hear it" aria-label="Hear the example">${icon("speaker")}</button><small>${inl(u.example)}</small></li>`).join("")}</ul>` : ""}
          <div class="ws-grid2">${R.strengths.length ? `<div><h4>Strengths</h4><ul class="ws-ul">${R.strengths.map(x => `<li>${inl(x)}</li>`).join("")}</ul></div>` : ""}
            ${R.next_steps.length ? `<div><h4>Next steps</h4><ol class="ws-ul">${R.next_steps.map(x => `<li>${inl(x)}</li>`).join("")}</ol></div>` : ""}</div>
          <p class="faint small">Session: ${clock()} · ${max ? `${total}/${max} points` : ""}</p>
          <div class="row"><button type="button" class="btn primary" data-pr="save-report">${icon("note")}Save to notes</button><button type="button" class="btn" data-pr="again">${icon("reset")}New session</button></div>`;
      },
    },
  };

  // the coding drill's Run: output from the Lab's Python (lab.js), in the browser
  const runPanel = () => `<div class="wl-term lab-run" id="pr-run"><div class="wl-term-head">${icon("terminal")}<b>Output</b><span class="faint small">${s.run.live ? "running… Ctrl+C stops" : `${s.run.code ? `exit code ${s.run.code}` : "done"} · ${s.run.took}s`}</span></div>
    <div class="wl-term-out lab-run-out">${Lab.outHtml(s.run) || `<span class="faint">${s.run.live ? "" : "No output."}</span>`}</div></div>`;
  async function runCode() {
    if (!s.text.trim()) return toast("Write or paste some code first");
    if (s.run?.live) return;
    const mine = s, e = s.run = { out: "", imgs: [], live: true, t0: performance.now() };
    e.draw = () => { const el = pane()?.querySelector("#pr-run"); if (el && s === mine && s.run === e) { el.outerHTML = runPanel(); const o = pane().querySelector("#pr-run .lab-run-out"); if (o) o.scrollTop = o.scrollHeight; } };
    draw();
    try { e.code = (await env.run(s.text, (st, t) => Lab.chunk(e, st, t))).code; }
    catch (x) { e.code = 1; e.out += `\x1b[31m${x.message}\x1b[0m\n`; }
    e.live = false; e.took = Math.round((performance.now() - e.t0) / 100) / 10;
    if (s === mine) draw();
  }

  // ---------- mode actions ----------
  async function gen(kind, label, then) {
    const r = await call(kind, {}, label, () => gen(kind, label, then));
    if (r) { then(r.data); draw(); }
  }
  const startQuiz = d => { s.data = d; s.q = runner(d.items); s.phase = "run"; s.recorded = false; };
  const startList = (items, extra = {}) => { s.list = { items, i: 0, ...extra }; s.phase = "run"; s.recorded = false; };

  async function loadDeck() {
    const mine = s;
    try { const d = await api(`/api/study/cards?track=${T().id}&today=${env.today()}`); if (s === mine) { s.deck = d; env.deck(d); } }
    catch (e) { if (s === mine) s.error = e.message; }
    if (s === mine) draw();
  }
  function nextInterval(c, g) {
    const ease = c.ease || 2.5, iv = c.interval || 0, reps = c.reps || 0;
    if (g === "again") return 0;
    if (g === "hard") return Math.max(1, Math.round(iv * 1.2));
    if (g === "good") return reps === 0 ? 1 : reps === 1 ? 3 : Math.max(iv + 1, Math.round(iv * ease));
    return reps === 0 ? 3 : Math.max(iv + 2, Math.round(Math.max(iv, 1) * ease * 1.3));
  }
  async function grade(g) {
    const L = s.list, c = L.items[L.i], mine = s;
    if (!c || !L.flipped) return;
    L.reviewed++; if (g !== "again") L.ok++; else L.items.push(c);  // missed cards come back at the end of the session
    L.i++; L.flipped = false; draw();
    try { const r = await api(`/api/study/cards/${c.id}`, { method: "PUT", body: { grade: g, today: env.today() } }); if (s === mine) Object.assign(s.deck, { due: r.due, total: r.total }); env.deck(r); }
    catch (e) { toast(e.message); }
    if (s === mine && L.i >= L.items.length) record(L.ok, L.reviewed);
  }

  // speech: a session-scoped "say" whose end is ignored once something else speaks or it's stopped
  function say(text, rate = 1, then) {
    const id = ++sayId;
    if (s) s.speaking = true; drawStatus();
    Voice.speak(text, { rate, onend: () => { if (id !== sayId) return; if (s) s.speaking = false; drawStatus(); then?.(); } });
  }
  function hush() { sayId++; Voice.stop(); if (s) s.speaking = false; }
  const micSvg = () => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>`;

  // pronunciation: one utterance, matched to the sentence
  function record1() {
    if (!SR) return;
    if (s.rec) return stopListen();
    hush();
    const L = s.list, i = L.i, rec = new SR(), mine = s;
    rec.lang = "en-US"; rec.interimResults = false; rec.continuous = false; rec.maxAlternatives = 1;
    rec.onresult = e => {
      if (s !== mine) return;
      const got = [...e.results].map(r => r[0].transcript).join(" "), r = align(L.items[i].text, got);
      L.heard[i] = r; L.best[i] = Math.max(L.best[i] ?? 0, Math.round(r.score * 100));
    };
    rec.onerror = e => { if (e.error === "not-allowed") toast("Microphone access was blocked"); else if (e.error === "no-speech") toast("Didn't hear anything: try again a bit louder"); };
    rec.onend = () => { if (s === mine && s.rec === rec) { s.rec = null; draw(); } };
    s.rec = rec;
    try { rec.start(); } catch { s.rec = null; toast("The microphone is busy: try again"); }
    draw();
  }
  // dialogue: listen continuously; hands-free sends after a pause
  function listen() {
    if (!SR || !s || s.rec || s.busy || s.phase !== "run") return;
    hush();
    const rec = new SR(), mine = s, base = s.draft ? s.draft.replace(/\s*$/, " ") : "";
    rec.lang = "en-US"; rec.continuous = true; rec.interimResults = true;
    rec.onresult = e => {
      if (s !== mine) return;
      const said = [...e.results].map(r => r[0].transcript).join("");
      s.draft = base + said;
      const ta = pane()?.querySelector("[data-pr-draft]"); if (ta) ta.value = s.draft;
      clearTimeout(s.silence);
      if (s.opts.hands && said.trim()) s.silence = setTimeout(() => { if (s === mine && s.rec === rec) { stopListen(); if (s.draft.trim()) dlgSend(s.draft.trim()); } }, 1700);
    };
    rec.onerror = e => { if (e.error === "not-allowed" && s === mine) { s.opts.hands = false; toast("Microphone access was blocked"); } };
    rec.onend = () => { if (s === mine && s.rec === rec) { s.rec = null; drawStatus(); } };
    s.rec = rec;
    try { rec.start(); } catch { s.rec = null; }
    drawStatus();
  }
  function stopListen() { if (!s) return; clearTimeout(s.silence); const r = s.rec; if (r) { s.rec = null; try { r.stop(); } catch {} } }
  function micHtml() {
    const st = s.busy ? ["Thinking…", "busy"] : s.speaking ? ["Speaking… tap to interrupt", "speaking"] : s.rec ? ["Listening…", "on"] : [SR ? "Tap to talk" : "Type below", ""];
    return `<div class="pr-mic-wrap">${SR ? `<button type="button" class="pr-mic ${st[1]}" data-pr="mic" aria-label="${s.rec ? "Stop listening" : "Talk"}" aria-pressed="${!!s.rec}" ${s.busy ? "disabled" : ""}>${micSvg()}</button>` : ""}<small class="faint">${st[0]}</small></div>`;
  }
  function drawStatus() { const w = pane()?.querySelector(".pr-mic-wrap"); if (w && s) w.outerHTML = micHtml(); }
  function startTimer() { const mine = s; s.timer = setInterval(() => { const el = pane()?.querySelector(".pr-timer span"); if (el && s === mine) el.textContent = clock(); }, 1000); }
  const clock = () => { const sec = Math.floor(((s.ended || Date.now()) - (s.started || Date.now())) / 1000); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; };

  async function dlgStart() {
    const a = s.tutor, mine = s; if (!a) return;
    // The drill runs in the tutor chat, so it starts that chat over: say so when there's something to lose.
    const had = (await api(`/api/study/chat?agent_id=${a.id}&track=${T().id}`).catch(() => null))?.items?.length;
    if (s !== mine) return;
    if (had && !await UI.confirm({ title: `Clear your chat with ${esc(a.name)}?`, body: `The conversation drill runs in your chat with ${esc(a.name)} on this track, so the chat so far is cleared first. This can't be undone.`,
      ok: "Clear and start", icon: "chat" })) return;
    if (s !== mine) return;
    s.phase = "run"; s.items = []; s.draft = ""; s.started = Date.now(); s.ended = null; s.busy = true; s.recorded = false;
    s.wide = true;
    draw();
    try { await api(`/api/study/chat?agent_id=${a.id}&track=${T().id}`, { method: "DELETE" }); } catch {}
    if (s !== mine) return;
    dlgSend(s.drill.prompt.replace("{about}", s.topic ? ` about ${s.topic.title}` : ""), true);
  }
  async function dlgSend(text, opener = false) {
    const mine = s, a = s.tutor;
    stopListen(); hush();
    if (!text.trim()) return;
    s.busy = true; s.draft = "";
    if (!opener) s.items.push({ kind: "user", text });
    draw();
    try {
      const { model, effort } = env.model();
      const r = await api("/api/study/chat", { method: "POST", body: { agent_id: a.id, track: T().id, topic: s.topic?.id || null, message: text, model, effort, today: env.today() } });
      if (s !== mine) return;
      s.items = r.items; if (r.error) s.items.push({ kind: "note", text: r.error });
    } catch (e) {
      if (s !== mine) return;
      s.items.push({ kind: "note", text: e.message }); if (!opener) s.draft = text;
    }
    s.busy = false; draw(); env.chatChanged(a);
    const last = [...s.items].reverse().find(i => i.kind === "assistant");
    const resume = () => { if (s === mine && s.opts.hands && s.phase === "run") listen(); };
    if (last && s.opts.speak) say(Voice.plain(Agents.md(last.text)), 1, resume); else resume();
  }
  async function dlgEnd() {
    quiet(); s.ended = s.ended || Date.now(); s.phase = "report";
    const mine = s;
    const r = await call("report", { agent_id: s.tutor.id }, "Writing your feedback report…", dlgEnd);
    if (!r || s !== mine) return;
    s.data = r.data;
    if (s.wide) { s.wide = false; env.wide(false); }
    const total = r.data.scores.reduce((n, x) => n + (x.score || 0), 0), max = r.data.scores.reduce((n, x) => n + (x.max || 0), 0);
    record(total, max || null); draw();
  }

  // ---------- writing diff: word by word, line breaks kept ----------
  function diff(a, b) {
    const tok = t => String(t || "").replace(/\n/g, " \n ").split(/ +/).filter(x => x !== "");
    const x = tok(a), y = tok(b), n = x.length, m = y.length;
    if (n * m > 4e6) return esc(b).replace(/\n/g, "<br>");  // too long to diff: show the corrected text
    const dp = new Uint16Array((n + 1) * (m + 1)), at = (i, j) => i * (m + 1) + j;
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[at(i, j)] = x[i] === y[j] ? dp[at(i + 1, j + 1)] + 1 : Math.max(dp[at(i + 1, j)], dp[at(i, j + 1)]);
    const out = [], w = (t, cls) => t === "\n" ? "<br>" : cls ? `<${cls}>${esc(t)}</${cls}>` : esc(t);
    let i = 0, j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && x[i] === y[j]) { out.push(w(x[i])); i++; j++; }
      else if (j < m && (i >= n || dp[at(i, j + 1)] >= dp[at(i + 1, j)])) { out.push(w(y[j], "ins")); j++; }
      else { out.push(w(x[i], "del")); i++; }
    }
    return out.join(" ").replace(/ ?<br> ?/g, "<br>");
  }

  // ---------- notes ----------
  function noteFor(kind) {
    const d = s.data, head = `## ${s.drill.title}${s.topic ? `: ${s.topic.title}` : ""}\n`;
    if (kind === "plan") return head + `**${d.goal}**\n\n${d.days.map(x => `- [ ] **${x.day}** · ${x.topic}: ${x.task} (${x.minutes} min). Done when: ${x.done_when}`).join("\n")}\n- [ ] **Build:** ${d.build_task}\n- [ ] **Prove it:** ${d.check}`;
    if (kind === "project") return `## ${d.title}\n${d.pitch}\n\nStack: ${d.stack.join(", ")}\n\n${d.milestones.map(m => `**${m.title}**\n${m.tasks.map(x => `- [ ] ${x}`).join("\n")}\nDone when: ${m.done_when}`).join("\n\n")}\n\n**Measure:** ${d.evaluation}`;
    if (kind === "lesson") return `## ${d.title}\n${d.summary}\n\n${d.sections.map(x => `### ${x.heading}\n${x.body}`).join("\n\n")}${d.misconception ? `\n\n**Misconception:** ${d.misconception}` : ""}`;
    if (kind === "writing") return head + `Level: ${d.level}\n\n${d.corrected}\n\n${d.changes.map(c => `- ~~${c.original}~~ → **${c.fixed}**: ${c.why}`).join("\n")}`;
    if (kind === "report") return head + `**${d.level}** · ${d.verdict}\n${d.summary}\n\n${d.scores.map(x => `- ${x.criterion}: ${x.score}/${x.max}`).join("\n")}\n\n**Fix these**\n${d.fixes.map(f => `- ~~${f.said}~~ → **${f.better}** (${f.why})`).join("\n")}\n\n**Level up**\n${d.upgrades.map(u => `- **${u.phrase}**: ${u.example}`).join("\n")}\n\n**Next steps**\n${d.next_steps.map(x => `- [ ] ${x}`).join("\n")}`;
    return head;
  }

  // ---------- events (called by Study's listeners on the view) ----------
  function click(e) {
    if (!s) return false;
    const t = e.target, el = t.closest("[data-pr], [data-pr-opt], [data-pr-grade], [data-pr-del], [data-pr-view], [data-pr-say], [data-pr-hear], [data-pr-line]");
    if (!el || !pane()?.contains(el)) return false;
    const k = el.dataset.pr, L = s.list;
    if (el.dataset.prOpt != null && !el.matches("input")) { pickOption(+el.dataset.prOpt); return true; }
    if (el.dataset.prGrade) { grade(el.dataset.prGrade); return true; }
    if (el.dataset.prDel) { delCard(+el.dataset.prDel); return true; }
    if (el.dataset.prView) { s.view = el.dataset.prView; draw(); return true; }
    if (el.dataset.prSay != null) { say(Voice.plain(Agents.md(s.items[+el.dataset.prSay].text))); return true; }
    if (el.dataset.prHear != null) { say(el.dataset.prHear); return true; }
    if (el.dataset.prLine) { const ln = pane().querySelector(`#pr-line-${el.dataset.prLine}`); ln?.scrollIntoView({ block: "center", behavior: "smooth" }); ln?.classList.add("flash"); setTimeout(() => ln?.classList.remove("flash"), 1200); return true; }
    const A = {
      back, "retry-call": () => { const r = s.retry; s.error = ""; s.retry = null; r ? r() : draw(); },
      again: () => { quiet(); s.phase = "start"; s.data = null; s.q = null; s.list = null; s.recorded = false; draw(); },
      tick: async () => { await env.tick(s.topic.id); s.topic = topicById(s.topic.id); draw(); },
      "pass-step": async () => { if (await env.passStep(s.step.id)) back(); },
      // lesson and quiz
      "gen-lesson": () => gen("lesson", "Writing your lesson…", d => { s.data = d; s.q = null; s.phase = "run"; s.recorded = false; }),
      "lesson-check": () => { s.q = runner(s.data.check); draw(); pane().querySelector(".pr-check")?.scrollIntoView({ block: "start", behavior: "smooth" }); },
      "lesson-ask": () => env.ask(s.tutor, `I just read your lesson on "${s.data.title}". My question: `),
      "save-lesson": () => saveNote(noteFor("lesson")),
      "gen-quiz": () => gen("quiz", s.drill.id === "grammar" ? "Writing your workout…" : "Writing your quiz…", startQuiz),
      check: () => check(), skip: () => check(true), "next-q": nextQuestion, "retry-missed": retryMissed, "ask-missed": askMissed,
      // flashcards
      review: () => { if (!s.deck?.queue.length) return; startList([...s.deck.queue], { flipped: false, reviewed: 0, ok: 0 }); draw(); },
      flip: () => { L.flipped = true; draw(); },
      "say-card": () => say(L.items[L.i].front, 0.9),
      deck: () => { s.phase = "start"; s.list = null; loadDeck(); },
      "gen-cards": () => gen("cards", "Writing new cards…", d => { s.fresh = d.cards.map(c => ({ ...c, keep: true })); }),
      "add-cards": addCards, "drop-cards": () => { s.fresh = null; draw(); },
      // pronunciation and dictation
      "gen-pron": () => gen("pron", "Writing your sentences…", d => startList(d.sentences, { heard: [], best: [] })),
      listen: () => say(L.items[L.i].text, 0.95), "listen-slow": () => say(L.items[L.i].text, 0.7), record: record1,
      "next-item": () => { stopListen(); hush(); L.i++; draw(); if (L.i >= L.items.length) finishList(); else if (s.mode === "dictation") say(L.items[L.i], 0.95); },
      "gen-dictation": () => gen("dictation", "Writing your passage…", d => { s.data = d; startList(d.sentences, { typed: [], checked: [], scores: [] }); setTimeout(() => say(d.sentences[0], 0.95), 300); }),
      play: () => say(L.items[L.i], 0.95), "play-slow": () => say(L.items[L.i], 0.7), "check-dict": checkDict,
      // writing
      "gen-task": () => gen("writing_task", "Setting a task…", d => { s.task = d; s.phase = "edit"; }),
      "check-writing": async () => {
        if (!s.text.trim()) return toast("Write something first");
        s.sent = s.text;
        const r = await call("writing", { text: s.text, task: s.task?.task || "" }, "Reading your text…", A["check-writing"]);
        if (r) { s.data = r.data; s.phase = "result"; s.view = "diff"; record(); draw(); }
      },
      edit: () => { s.phase = "edit"; draw(); },
      "copy-corrected": () => copy(s.data.corrected), "save-writing": () => saveNote(noteFor("writing")),
      "new-writing": () => { s.task = null; s.text = ""; s.phase = "edit"; s.recorded = false; A["gen-task"](); },
      // code
      "gen-code-task": () => gen("code_task", "Writing an exercise…", d => { s.task = d; s.text = d.starter || ""; s.phase = "edit"; s.recorded = false; }),
      "review-code": async () => {
        if (!s.text.trim()) return toast("Write or paste some code first");
        s.sent = s.text;
        const r = await call("code", { text: s.text, task: s.task ? `${s.task.title}\n${s.task.task}` : "" }, "Reviewing your code…", A["review-code"]);
        if (r) { s.data = r.data; s.phase = "result"; record(r.data.score, 10); draw(); }
      },
      "copy-improved": () => copy(s.data.improved), "copy-code": () => copy(s.data.code),
      "run-code": runCode, "code-lab": () => env.openLab(s.text),
      // plan and project
      "gen-plan": () => gen("plan", "Planning your week…", d => { s.data = d; s.phase = "run"; s.recorded = false; record(); }),
      "save-plan": () => saveNote(noteFor("plan")),
      "gen-project": () => gen("project", "Thinking of a project…", d => { s.data = d; s.phase = "run"; s.recorded = false; record(); }),
      "save-project": () => saveNote(noteFor("project")),
      // dialogue
      "dlg-start": dlgStart, "dlg-end": dlgEnd, "save-report": () => saveNote(noteFor("report")),
      "dlg-board": async () => {  // the design sketched on a whiteboard, as text the interviewer can read
        stopListen(); const mine = s, text = await Whiteboard.pickOutline();
        if (!text || s !== mine) return;
        s.draft = ((s.draft ? s.draft.trimEnd() + "\n\n" : "") + "Here's my design on the whiteboard:\n\n" + text).slice(0, 3900); draw();
      },
      "dlg-send": () => { const v = pane().querySelector("[data-pr-draft]")?.value || ""; if (v.trim()) dlgSend(v.trim()); },
      mic: () => { if (s.speaking) { hush(); drawStatus(); return listen(); } s.rec ? stopListen() : listen(); drawStatus(); },
    };
    if (A[k]) { A[k](); return true; }
    return false;
  }
  function finishList() {
    const L = s.list;
    if (s.mode === "pron") record(Math.round(L.best.reduce((n, b) => n + (b || 0), 0)) / 100, L.items.length);
    if (s.mode === "dictation") record(Math.round(L.scores.reduce((n, v) => n + (v || 0), 0) * 10) / 10, L.items.length);
  }
  function checkDict() {
    const L = s.list, v = pane().querySelector("[data-pr-dict]")?.value.trim() || "";
    if (!v) return toast("Type what you heard first");
    const r = align(L.items[L.i], v);
    L.typed[L.i] = v; L.checked[L.i] = r; L.scores[L.i] = r.score; draw();
  }
  async function addCards() {
    const keep = s.fresh.filter(c => c.keep).map(({ keep, ...c }) => c), mine = s;
    if (!keep.length) return toast("Tick at least one card");
    try {
      const d = await api("/api/study/cards", { method: "POST", body: { track: T().id, cards: keep, today: env.today() } });
      if (s !== mine) return;
      s.deck = d; s.fresh = null; env.deck(d);
      toast(d.added ? `${d.added} card${d.added === 1 ? "" : "s"} added: they're due today` : "Those cards are already in your deck");
      draw();
    } catch (e) { toast(e.message); }
  }
  async function delCard(id) {
    const mine = s, c = s.deck?.cards?.find(x => x.id === id);
    if (!await UI.confirm({ title: "Delete this flashcard?", body: "Its review history goes with it. This can't be undone.", items: c ? [esc(c.front)] : [] })) return;
    if (s !== mine) return;
    try { const r = await api(`/api/study/cards/${id}`, { method: "DELETE" }); if (s !== mine) return; s.deck.cards = s.deck.cards.filter(c => c.id !== id); s.deck.queue = s.deck.queue.filter(c => c.id !== id); Object.assign(s.deck, r); env.deck(r); draw(); }
    catch (e) { toast(e.message); }
  }
  async function copy(text) { try { await navigator.clipboard.writeText(text); toast("Copied"); } catch { toast("Couldn't copy"); } }

  function change(e) {
    if (!s || !pane()?.contains(e.target)) return false;
    const t = e.target;
    if (t.matches("[data-pr-topic]")) { s.topic = t.value ? topicById(t.value) : null; draw(); return true; }
    if (t.matches("[data-pr-keep]")) { s.fresh[+t.dataset.prKeep].keep = t.checked; draw(); return true; }
    if (t.matches("[data-pr-opt-hands]")) { s.opts.hands = t.checked; if (s.phase === "run" && t.checked && !s.busy && !s.speaking) listen(); draw(); return true; }
    if (t.matches("[data-pr-opt-speak]")) { s.opts.speak = t.checked; if (!t.checked) hush(); draw(); return true; }
    if (t.matches("[data-pr-minutes]")) { s.opts.minutes = +t.value; return true; }
    return false;
  }
  function input(e) {
    if (!s || !pane()?.contains(e.target)) return;
    const t = e.target;
    if (t.matches("[data-pr-text]")) {
      s.text = t.value;
      const c = pane().querySelector("[data-pr-count]");
      if (c) { const n = words(t.value).length; c.textContent = `${n} word${n === 1 ? "" : "s"}${s.task?.words ? ` of about ${s.task.words}` : ""}`; }
    }
    if (t.matches("[data-pr-draft]")) s.draft = t.value;
    if (t.matches("[data-pr-answer]") && s.q) s.q.answers[s.q.i].given = t.value;
  }
  function key(e) {
    if (!s || S.view !== "study") return false;
    const t = e.target, typing = /INPUT|TEXTAREA|SELECT/.test(t.tagName);
    if (t.matches?.("[data-pr-answer]") && e.key === "Enter" && (t.tagName === "INPUT" || e.ctrlKey || e.metaKey)) { e.preventDefault(); check(); return true; }
    if (t.matches?.("[data-pr-dict]") && e.key === "Enter") { e.preventDefault(); checkDict(); return true; }
    if (t.matches?.("[data-pr-draft]") && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (t.value.trim()) dlgSend(t.value.trim()); return true; }
    if (t.matches?.("textarea.pr-editor:not(.prose)") && e.key === "Enter" && (e.ctrlKey || e.metaKey) && env.run) { e.preventDefault(); runCode(); return true; }
    if (t.matches?.("textarea.pr-editor:not(.prose)") && e.key === "c" && e.ctrlKey && s.run?.live && t.selectionStart === t.selectionEnd) { e.preventDefault(); Lab.stop(); return true; }
    if (t.matches?.("textarea.pr-editor:not(.prose)") && e.key === "Tab") {  // code editor: Tab indents
      e.preventDefault(); const a = t.selectionStart, b = t.selectionEnd; t.setRangeText("    ", a, b, "end"); s.text = t.value; return true;
    }
    if (s.mode === "cards" && s.phase === "run" && !typing && s.list?.items[s.list.i]) {
      if (e.key === " " && !s.list.flipped) { e.preventDefault(); s.list.flipped = true; draw(); return true; }
      const g = { 1: "again", 2: "hard", 3: "good", 4: "easy" }[e.key];
      if (g && s.list.flipped) { e.preventDefault(); grade(g); return true; }
    }
    return false;
  }

  return { start, draw, active, leave, quiet, click, change, input, key };
})();
