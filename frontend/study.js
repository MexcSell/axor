/* Study: two learning tracks, AI Engineer and English C1+.
   - Roadmap: the fast track, the path re-ordered into steps that get you to a high level soonest. Each step is marked
     done, current ("you are here"), next or later, with its hours, a date at your pace, its build task, a checkpoint
     drill and a test-out to skip it. Today's sprint says what to do next. The full path adds the optional topics.
   - All topics: the modules and topics you tick off. Practice: drills in the page (practice.js), built from your own
     material (Scout Drive files, Source code) when you add some. Lab (AI Engineer track, lab.js): a terminal, a Python
     editor, a SQL playground and a prompt playground, with hands-on tasks checked by tests; Python runs in the browser.
   - The study team (six tutor agents) chats per track next to it, in the shared chat (chatkit.js): picking a topic fills
     in the message for the right tutor; + attaches Drive files or Source code; answers can be read aloud and messages
     spoken (in English). Tutors see your progress and fast-track step, and tick topics you've shown you know. */
const Study = (() => {
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("study." + k)); localStorage.setItem("study." + k, JSON.stringify(v)); } catch { return null; } };
  let d = null, wired = false, track = pref("track") || "ai", tab = pref("tab") || "roadmap", topic = null, back = null;
  let chat = null, busy = false, chatSeq = 0, speaking = null, wideChat = pref("wideChat") || false;
  const picked = pref("agents") || {};  // the selected tutor per track
  const modes = pref("mode") || {};     // fast or full, per track
  const mats = pref("mats") || {};      // material per track: [{kind, id, label}]
  const flipped = new Set();            // roadmap steps folded or unfolded by hand (the current one starts open)
  const TABS = [["roadmap", "route", "Roadmap"], ["path", "book", "All topics"], ["practice", "target", "Practice"], ["lab", "terminal", "Lab"]];
  const tabs = () => TABS.filter(([k]) => k !== "lab" || Lab.available(T()));
  const GOAL = { ai: "e.g. Land an AI engineer role by June", english: "e.g. Lead meetings in English with confidence" };
  const START = { ai: t => `Teach me "${t}". Start from what I already know, then check my understanding.`,
                  english: t => `Let's practise "${t}". Explain it briefly, then give me exercises one at a time.` };
  const av = agentAvatar;  // faces.js
  const today = () => { const t = new Date(); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`; };
  const T = () => d.tracks.find(t => t.id === track) || d.tracks[0];
  const agents = () => d.agents.filter(a => a.track === track || a.track === "both");
  const agent = () => agents().find(a => a.id === picked[track]) || agents()[0];
  const tutorFor = template => agents().find(a => a.template === template) || agent();
  const topicOf = id => { for (const m of T().modules) for (const x of m.topics) if (x.id === id) return { ...x, module: m }; return null; };
  const moduleOf = id => T().modules.find(m => id && id.startsWith(m.id + "."));
  const pctOf = t => t.total ? Math.round(t.done / t.total * 100) : 0;
  const missing = () => d.agents_enabled && d.team.some(t => !d.agents.some(a => a.template === t.id));
  const mode = () => modes[track] === "full" ? "full" : "fast";
  const material = () => mats[track] || [];
  const ckey = a => `study:${track}:${a?.id}`;

  function init() { $("#nav-study").hidden = !Auth.me(); }
  async function open() {
    wire();
    if (!d) { $("#st-main").innerHTML = Loading.cards(3, "card"); $("#st-side").innerHTML = ""; $("#st-chat").innerHTML = ""; }
    try { await load(); } catch (e) { if (!d) return void ($("#st-main").innerHTML = `<div class="card empty">${esc(e.message)}</div>`); }
    render();
  }
  async function load() {
    d = await api(`/api/study?today=${today()}`);
    if (!d.tracks.some(t => t.id === track)) track = d.tracks[0].id;
  }
  // leaving the view: stop reading aloud, listening and any practice session's voice
  function stop() { Voice.stop(); Chat.quiet(); Chat.stopMic(); speaking = null; Practice.quiet(); Lab.leave(); }
  // a voice session takes the chat panel's room; otherwise the panel shows when tutors are available
  const wide = on => $("#view-study .ws").classList.toggle("no-chat", on || !d.agents_enabled);
  // what a practice session needs from the page
  const env = {
    pane: () => $("#st-pane"), track: () => T(), topic: () => topic, today, model: Chat.choice, agentsOn: () => d.agents_enabled, material,
    tutor: template => d.agents.find(a => a.template === template) || null,
    back: () => { if (back) { tab = back; back = null; pref("tab", tab); } renderPane(); }, wide,
    tick: async id => { try { d = await api("/api/study/topics", { method: "PUT", body: { track, topic: id, done: true, today: today() } }); renderSide(); renderProg(); toast("Ticked"); } catch (e) { toast(e.message); } },
    passStep: id => setStep(id, true),
    ask: (a, text) => { picked[track] = a.id; pref("agents", picked); Chat.state(ckey(a)).text = text; renderSide(); loadChat(true); },
    chatChanged: a => { if (agent()?.id === a.id) loadChat(); },
    recorded: r => { T().recent = r.recent; d.activity = r.activity; renderSide(); },
    deck: r => { T().deck = { due: r.due, total: r.total }; },
    // the Lab: Pyodide's pinned URL, and the coding drill running its code there or opening it in the Python tab
    runtime: () => d.lab.runtime, home: () => d.lab.home, run: (text, out) => Lab.runCode(text, out),
    openLab: async text => { await Lab.openCode(text); showLab(); },
  };
  function showLab(task = false) {
    if (!Lab.available(T())) return;
    tab = "lab"; pref("tab", tab); back = null; Practice.quiet(); renderTabs(); Lab.draw(env);
    if (task) Lab.ask();
    $("#st-tabs")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  // ---------- the fast track ----------
  // steps on the chosen line: the topics that count, done of total, hours left, and the marker
  function steps() {
    const full = mode() === "full";
    let cur = false, nxt = false;
    return T().roadmap.map(st => {
      const list = full ? [...st.topics, ...st.extra] : st.topics, per = st.hours / Math.max(1, st.topics.length);
      const done = list.filter(x => x.done).length;
      const status = done === list.length ? "done" : !cur ? "current" : !nxt ? "next" : "later";
      if (status === "current") cur = true; else if (status === "next") nxt = true;
      return { ...st, list, done, total: list.length, left: (list.length - done) * per, per, status };
    });
  }
  const dateIn = days => new Date(Date.now() + days * 864e5);
  const fmtDate = (t, year) => t.toLocaleDateString(undefined, { month: "short", day: "numeric", ...(year ? { year: "numeric" } : {}) });
  // when each step and the whole line finish at the learner's pace
  function plan(list) {
    const pace = T().pace;
    let cum = 0;
    for (const s of list) { cum += s.left; s.by = s.status === "done" ? null : dateIn(Math.ceil(cum / pace * 7)); }
    return { hours: cum, weeks: cum / pace, end: dateIn(Math.ceil(cum / pace * 7)), daily: Math.round(pace * 60 / 7) };
  }
  const hrs = h => h < 1 ? `${Math.max(10, Math.round(h * 12) * 5)} min` : `${Math.round(h)} h`;
  const isOpen = s => flipped.has(s.id) !== (s.status === "current");

  // ---------- layout ----------
  function render() {
    const root = $("#view-study .ws");
    root.classList.toggle("wide-chat", wideChat);
    Chat.resizer(root, "--chat-w", "stChatW");
    wide(false); Lab.attach(env);
    renderSide(); renderMain(); loadChat();
  }
  function renderSide() {
    const tracks = d.tracks.map(t => `<div class="ws-item ${t.id === track ? "on" : ""}" data-st-track="${t.id}" role="button" tabindex="0">
        ${av({ icon: t.icon, color: t.color }, "sm")}<span class="ws-item-txt"><b>${esc(t.title)}</b><small class="faint">${t.done}/${t.total} topics · ${pctOf(t)}%</small></span></div>`).join("");
    const A = d.activity, now = today();
    const day = x => new Date(x + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    const tutors = !d.agents_enabled ? `<p class="faint small">Tutors are agents, which are available to administrators${Auth.me()?.role === "admin" ? "" : " (ask one to let members use them)"}. The roadmap, streak and goals work without them.</p>`
      : agents().map(a => `<div class="ws-item agent ${a.id === agent()?.id ? "on" : ""}" data-st-agent="${a.id}" role="button" tabindex="0" title="Chat with ${esc(a.name)}">
          ${av(a, "sm")}<span class="ws-item-txt"><b>${esc(a.name)}</b><small class="faint">${esc(a.role || "Tutor")}${a.status === "paused" ? " · paused" : ""}</small></span>
          ${a.id === agent()?.id ? `<span class="badge clear" title="Selected">${icon("check")}</span>` : ""}</div>`).join("")
        || `<p class="faint small">No tutors for this track yet.</p>`;
    $("#st-side").innerHTML = `
      <div class="ws-head"><span>Tracks</span></div>
      <div class="ws-list">${tracks}</div>
      <div class="ws-head"><span>Streak</span></div>
      <div class="st-streak">
        <div class="st-streak-n">${icon("zap")}<b>${A.streak}</b><span>day${A.streak === 1 ? "" : "s"} in a row</span></div>
        <small class="faint">${A.today ? "You've studied today. See you tomorrow!" : A.streak ? "Study today to keep it going." : "Tick a topic or chat with a tutor to start one."}</small>
        <div class="st-days" aria-label="Last 14 days: ${A.active_14} with study">${A.days.map(x => `<i class="${x.n ? "on" : ""} ${x.day === now ? "today" : ""}" title="${esc(day(x.day))}: ${x.n ? "studied" : "no study"}"></i>`).join("")}</div>
      </div>
      <div class="ws-head"><span>Study team <span class="faint">${d.agents_enabled ? agents().length : ""}</span></span>${missing() ? `<button type="button" class="btn sm" data-st="team" title="Create the tutors you don't have yet">${icon("plus")}Create</button>` : ""}</div>
      <div class="ws-list">${tutors}</div>`;
  }
  function renderMain() {
    const t = T();
    $("#st-main").innerHTML = `
      <div class="ws-title">${av({ icon: t.icon, color: t.color }, "lg")}<div><h1>${esc(t.title)}</h1><span class="muted">${esc(t.blurb)}</span></div></div>
      <div class="card st-overview">
        <div id="st-prog"></div>
        <div class="st-profile">
          <label class="in"><span>Your level</span><select data-st-level><option value="">Not set</option>${t.levels.map(([k, l]) => `<option value="${k}" ${k === t.level ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
          <label class="in"><span>Your goal</span><input data-st-goal maxlength="200" value="${esc(t.goal)}" placeholder="${esc(GOAL[t.id] || "")}"></label>
          <label class="in"><span>Time you'll put in</span><select data-st-pace>${t.paces.map(h => `<option value="${h}" ${h === t.pace ? "selected" : ""}>${h} hours a week${h >= 20 ? " (intensive)" : h <= 3 ? " (light)" : ""}</option>`).join("")}</select></label>
        </div>
      </div>
      <div class="hub-tabs ws-tabs" role="tablist" id="st-tabs"></div>
      <div class="ws-pane" id="st-pane"></div>`;
    renderProg(); renderPane();
  }
  function renderProg() {
    const t = T(), el = $("#st-prog"); if (!el) return;
    const list = steps(), p = plan(list), done = list.filter(s => s.status === "done").length, cur = list.find(s => s.status === "current");
    const pct = Math.round(list.reduce((n, s) => n + s.done, 0) / Math.max(1, list.reduce((n, s) => n + s.total, 0)) * 100);
    el.innerHTML = `<div class="st-prog-top"><b>${mode() === "fast" ? "Fast track" : "Full path"}: ${done} of ${list.length} steps</b><span class="faint">${pct}%</span></div>
      <div class="rm-rail" role="list" aria-label="Roadmap steps" style="--p:${cur ? list.indexOf(cur) / Math.max(1, list.length - 1) : 1}">${list.map(s => `<button type="button" role="listitem" class="rm-dot ${s.status}" data-st-step="${esc(s.id)}" title="Step ${s.n}: ${esc(s.title)} · ${s.status === "current" ? "you are here" : s.status}" aria-label="Step ${s.n}, ${esc(s.title)}, ${s.status === "current" ? "you are here" : s.status}">${s.status === "done" ? icon("check") : s.n}</button>`).join("")}</div>
      ${cur ? `<p class="st-next">${icon("flag")}<span>Step ${cur.n}: <b>${esc(cur.title)}</b> · ${cur.done}/${cur.total}</span><span class="faint">· finish line ${fmtDate(p.end, p.weeks > 40)} at ${t.pace} h/week (${hrs(p.hours)} left)</span></p>`
        : `<p class="st-next">${icon("trophy")}Every step of the ${mode() === "fast" ? "fast track" : "full path"} is done. Keep it sharp with mock interviews, projects and quizzes${mode() === "fast" ? ", or switch to the full path for the extras" : ""}.</p>`}`;
  }
  function renderTabs() {
    const el = $("#st-tabs"); if (!el) return;
    el.innerHTML = tabs().map(([k, ic, l]) => `<button type="button" role="tab" data-st-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}</button>`).join("");
  }
  function renderPane() {
    if (!tabs().some(([k]) => k === tab)) tab = "roadmap";  // the Lab is on the AI track only
    renderTabs();
    if (tab === "lab") return Lab.draw(env);
    if (tab === "practice") return renderPractice();
    if (tab === "roadmap") return renderRoadmap();
    $("#st-pane").innerHTML = `<div class="st-mods">${T().modules.map(m => `<section class="card st-mod ${m.done === m.total ? "done" : ""}">
        <div class="st-mod-head"><h3>${m.done === m.total ? icon("check") : ""}${esc(m.title)}</h3><span class="faint small">${m.done}/${m.total}</span></div>
        <div class="bar"><i style="width:${m.total ? m.done / m.total * 100 : 0}%"></i></div>
        <ul class="st-topics">${m.topics.map(x => `<li class="${x.id === topic ? "on" : ""}">
          <label class="st-chk"><input type="checkbox" data-st-tick="${esc(x.id)}" ${x.done ? "checked" : ""}><span>${esc(x.title)}</span></label>
          ${d.agents_enabled ? `<button type="button" class="iconbtn sm" data-st-topic="${esc(x.id)}" title="Study this with a tutor" aria-label="Study ${esc(x.title)} with a tutor">${icon("chat")}</button>` : ""}</li>`).join("")}</ul>
      </section>`).join("")}</div>`;
  }

  // ---------- roadmap ----------
  const MARK = { done: ["Done", "clear"], current: ["You are here", "new"], next: ["Next", "muted"] };
  const short = (x, n = 38) => x.length > n ? x.slice(0, n - 2) + "…" : x;
  function renderRoadmap() {
    const t = T(), list = steps(), p = plan(list), cur = list.find(s => s.status === "current"), on = d.agents_enabled;
    const drillOf = id => t.drills.find(x => x.id === id);
    const nextTopic = s => s.list.find(x => !x.done);
    const extraOf = s => mode() === "fast" ? t.roadmap.find(r => r.id === s.id).extra : [];
    const optional = new Set(t.roadmap.flatMap(r => r.extra.map(x => x.id)));
    let sprint = "";
    if (cur) {
      const x = nextTopic(cur), dr = drillOf(cur.drill), due = t.deck.due, who = tutorFor(moduleOf(x?.id)?.tutor);
      const learn = Math.round(p.daily * 0.5), prac = Math.round(p.daily * 0.3), rest = Math.max(5, p.daily - learn - prac);
      sprint = `<section class="card rm-sprint" aria-label="Today's sprint">
        <div class="rm-sprint-head"><b>${icon("zap")}Today's sprint</b><span class="faint small">about ${p.daily} min a day at ${t.pace} h/week</span></div>
        <ol class="rm-sprint-list">
          <li><span class="rm-n">1</span><span class="rm-what"><b>Learn: ${esc(x?.title || cur.title)}</b><small class="faint">${on && who ? `with ${esc(who.name)} · ` : ""}~${learn} min · then explain it back in your own words</small></span>
            ${on && x ? `<button type="button" class="btn sm primary" data-st-topic="${esc(x.id)}">${icon("chat")}Start</button>` : ""}</li>
          <li><span class="rm-n">2</span><span class="rm-what"><b>Practise: ${esc(dr?.title || "a drill")}</b><small class="faint">~${prac} min · ${dr?.mode === "dialogue" ? "out loud, scored at the end" : "graded as you go"}</small></span>
            ${on && dr ? `<button type="button" class="btn sm" data-st-run="${esc(cur.id)}" data-drill="${esc(dr.id)}">${icon("target")}Go</button>` : ""}</li>
          <li><span class="rm-n">3</span>${due ? `<span class="rm-what"><b>Review ${due} flashcard${due === 1 ? "" : "s"}</b><small class="faint">~${rest} min · spaced repetition makes it stick</small></span>
              <button type="button" class="btn sm" data-st-cards>${icon("book")}Review</button>`
            : `<span class="rm-what"><b>Build</b><small class="faint">${esc(cur.build)} ~${rest} min a day.</small></span>`}</li>
        </ol></section>`;
    }
    $("#st-pane").innerHTML = `<div class="rm">
      <div class="rm-top">
        <div class="seg" role="group" aria-label="Which line">${[["fast", "Fast track"], ["full", "Full path"]].map(([k, l]) => `<button type="button" data-st-mode="${k}" aria-pressed="${mode() === k}">${l}</button>`).join("")}</div>
        <span class="rm-sum faint small" title="${mode() === "fast" ? `The fast track skips ${t.roadmap.reduce((n, r) => n + r.extra.length, 0)} optional topics; the full path has every topic` : "Every topic on the track"}">${list.length} steps · ${hrs(list.reduce((n, s) => n + s.list.length * s.per, 0))}</span>
        <span class="ac-spacer"></span>
        ${cur ? `<span class="rm-eta" title="At ${t.pace} hours a week">${icon("flag")}<span><b>${fmtDate(p.end, p.weeks > 40)}</b><small class="faint">${hrs(p.hours)} left · ${p.weeks < 1 ? "under a week" : `${Math.ceil(p.weeks)} week${Math.ceil(p.weeks) === 1 ? "" : "s"}`}</small></span></span>` : ""}
      </div>
      ${sprint}
      <ol class="rm-steps">${list.map(s => {
        const open = isOpen(s), x = nextTopic(s), dr = drillOf(s.drill), extra = extraOf(s), mark = MARK[s.status];
        return `<li class="rm-step ${s.status} ${open ? "open" : ""}" data-step="${esc(s.id)}">
          <span class="rm-marker" aria-hidden="true">${s.status === "done" ? icon("check") : s.n}</span>
          <div class="card rm-card">
            <button type="button" class="rm-head" data-st-fold="${esc(s.id)}" aria-expanded="${open}">
              <span class="rm-title"><small class="faint">Step ${s.n}</small><b>${esc(s.title)}</b></span>
              ${mark ? `<span class="badge ${mark[1]}">${mark[0]}</span>` : ""}
              <span class="ac-spacer"></span>
              <span class="rm-meta"><b>${s.done}/${s.total}</b><small class="faint">${s.status === "done" ? "complete" : `~${hrs(s.left)}${s.by ? ` · by ${fmtDate(s.by)}` : ""}`}</small></span>${icon("down")}</button>
            <div class="bar rm-bar"><i style="width:${s.total ? s.done / s.total * 100 : 0}%"></i></div>
            ${open ? `<div class="rm-body">
              <p class="rm-outcome">${icon("target")}<span>${esc(s.outcome)}</span></p>
              <ul class="rm-topics">${s.list.map(y => `<li class="${y.done ? "done" : y === x ? "now" : ""}">
                <label class="st-chk"><input type="checkbox" data-st-tick="${esc(y.id)}" ${y.done ? "checked" : ""}><span>${esc(y.title)}${optional.has(y.id) ? ` <small class="faint">optional</small>` : ""}</span></label>
                ${y === x ? `<span class="badge new rm-now">Next</span>` : ""}
                ${on ? `<button type="button" class="iconbtn sm" data-st-topic="${esc(y.id)}" title="Learn it with a tutor" aria-label="Learn ${esc(y.title)} with a tutor">${icon("chat")}</button>
                  <button type="button" class="iconbtn sm" data-st-quiz="${esc(y.id)}" title="Quiz me on it" aria-label="Quiz me on ${esc(y.title)}">${icon("target")}</button>` : ""}</li>`).join("")}</ul>
              ${extra.length ? `<details class="rm-extra"><summary>${extra.length} optional topic${extra.length === 1 ? "" : "s"} on the full path</summary><ul>${extra.map(y => `<li>${y.done ? icon("check") : ""}${esc(y.title)}</li>`).join("")}</ul></details>` : ""}
              <p class="rm-build">${icon("zap")}<span><b>Build:</b> ${esc(s.build)}</span></p>
              <div class="row rm-acts">
                ${on && x ? `<button type="button" class="btn primary" data-st-topic="${esc(x.id)}">${icon("chat")}${s.done ? "Continue" : "Start"}: ${esc(short(x.title))}</button>` : ""}
                ${on && dr ? `<button type="button" class="btn" data-st-run="${esc(s.id)}" data-drill="${esc(dr.id)}">${icon(dr.icon)}Checkpoint: ${esc(dr.title)}</button>` : ""}
                ${on && s.status !== "done" ? `<button type="button" class="btn" data-st-testout="${esc(s.id)}" title="Eight questions on the whole step: 80% ticks it">${icon("trophy")}Test out</button>` : ""}
                ${on ? `<button type="button" class="btn ghost" data-st-help="${esc(s.id)}">${icon("calendar")}Plan it with a tutor</button>` : ""}
                ${s.status === "done" ? `<button type="button" class="linkbtn" data-st-undo="${esc(s.id)}">Untick the step</button>` : !on ? `<button type="button" class="linkbtn" data-st-all="${esc(s.id)}">Mark the step done</button>` : ""}
              </div></div>` : ""}
          </div></li>`;
      }).join("")}</ol>
      <p class="faint small rm-foot">The fast track teaches what gets you working at a high level first and leaves the rest for later; your level changes what it includes. Hours are for focused study with practice. Your tutors know your step and pace.</p></div>`;
  }
  async function setStep(id, done) {
    const was = steps().find(s => s.id === id);
    try {
      d = await api("/api/study/step", { method: "PUT", body: { track, step: id, done, today: today() } });
      toast(done ? `Step ${was?.n} done: ${was?.title}` : "Step unticked");
      flipped.clear();
      renderSide(); renderProg(); if (!Practice.active()) renderPane();
      return true;
    } catch (e) { toast(e.message); return false; }
  }
  // a drill opened from the roadmap goes back to the roadmap when it's left
  function runDrill(drillId, { topicId = null, step = null } = {}) {
    const x = T().drills.find(y => y.id === drillId); if (!x) return;
    if (topicId) topic = topicId;
    if (x.mode === "lab") return showLab(true);
    back = tab === "practice" ? null : tab; tab = "practice"; renderTabs();
    Practice.start(x, env, step ? { step } : {});
    $("#st-tabs")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  const quizDrill = () => T().drills.find(x => x.mode === "quiz");
  function testOut(id) {
    const s = steps().find(x => x.id === id), q = quizDrill();
    if (s && q) runDrill(q.id, { step: s });
  }
  function stepHelp(id) {
    const s = steps().find(x => x.id === id); if (!s) return;
    const left = s.list.filter(x => !x.done).map(x => x.title);
    const who = track === "ai" ? (agents().find(a => a.template === "study-mentor") || agent()) : tutorFor(moduleOf(s.list[0]?.id)?.tutor);
    if (!who) return toast("Create the study team first");
    env.ask(who, `I'm on step ${s.n} of my fast track, "${s.title}" (${s.outcome}) ${left.length ? `Left: ${left.join("; ")}.` : "I've ticked all of it."} I have about ${T().pace} hours a week. Give me the fastest plan to finish this step, day by day, then start me on the first topic.`);
  }

  // ---------- practice: drills, built from your material ----------
  function renderPractice() {
    if (Practice.active()) return Practice.draw();
    const t = T(), pane = $("#st-pane"), m = material();
    const about = x => (topic && topicOf(topic)?.title) || x.topic?.title;
    const ago2 = ts => { const days = Math.floor((Date.now() / 1000 - ts) / 86400); return days < 1 ? ago(ts) : days === 1 ? "yesterday" : `${days} days ago`; };
    pane.innerHTML = `
      <section class="card st-mats ${m.length ? "on" : ""}">
        <div class="st-mats-txt"><b>${icon("clip")}Practise from your own material</b>
          <small class="muted">${m.length ? "Lessons, quizzes, flashcards, exercises and reviews are built from these. Attach them in the chat (+ or Material) for your tutor." : "Add your notes, docs or code from AXoR Drive or a Source repository, and drills are built from them."}</small></div>
        ${m.length ? `<div class="st-mat-chips">${m.map((x, i) => `<span class="ac-att" title="${esc(x.label)}">${icon(Chat.ATT_ICON[x.kind] || "file")}<span>${esc(x.label)}</span><button type="button" data-st-unmat="${i}" aria-label="Remove ${esc(x.label)}">${icon("close")}</button></span>`).join("")}</div>` : ""}
        <div class="row st-mat-add">
          <button type="button" class="btn sm" data-st-mat="drive">${icon("folder")}AXoR Drive</button>
          <button type="button" class="btn sm" data-st-mat="source">${icon("code")}Source code</button>
          <button type="button" class="btn sm" data-st-mat="upload">${icon("upload")}Upload</button>
          ${m.length ? `<button type="button" class="linkbtn" data-st-mat="clear">Clear</button>` : ""}
        </div>
      </section>
      <div class="st-drills">${t.drills.map(x => {
          const who = env.tutor(x.agent), live = d.agents_enabled || (x.mode === "cards" && t.deck.total);
          return `<button type="button" class="card st-drill" data-st-drill="${x.id}" ${live ? "" : "disabled"}>
            <span class="st-drill-top"><span class="st-drill-ic">${icon(x.icon)}</span>${x.mode === "cards" && t.deck.due ? `<span class="badge new" title="Cards due for review today">${t.deck.due} due</span>` : ""}${m.length && x.mode !== "dialogue" && x.mode !== "pron" && x.mode !== "dictation" ? `<span class="badge muted" title="Built from your material">${icon("clip")}Yours</span>` : ""}</span>
            <b>${esc(x.title)}</b><p class="muted small">${esc(x.blurb.replace("{topic}", about(x) || "a topic for your level"))}</p>
            <span class="st-drill-who">${who ? `${av(who, "sm")}${esc(who.name)}` : `${icon("users")}${d.agents_enabled ? "Study team" : "Needs agents"}`}</span></button>`;
        }).join("")}</div>
      ${d.agents_enabled ? "" : `<p class="faint small">Drills are written for you by a model, so they need agents, which are available to administrators${Auth.me()?.role === "admin" ? "" : " (ask one to let members use them)"}. Flashcards you already have can still be reviewed.</p>`}
      ${t.recent.length ? `<h3 class="st-recent-h">Recent practice</h3><ul class="st-recent">${t.recent.map(r => `<li><span><b>${esc(r.title)}</b>${r.topic ? `<small class="faint">${esc(r.topic)}</small>` : ""}</span>
          ${r.total ? `<span class="st-recent-score ${r.score / r.total >= 0.8 ? "good" : r.score / r.total >= 0.5 ? "mid" : "low"}">${fmtNum(r.score, r.score % 1 ? 1 : 0)}/${fmtNum(r.total, r.total % 1 ? 1 : 0)}</span>` : `<span class="faint small">done</span>`}
          <small class="faint">${ago2(r.created)}</small></li>`).join("")}</ul>` : ""}`;
  }
  function addMaterial(kind) {
    if (kind === "clear") {
      const was = mats[track] || [], tr = track, put = m => { mats[tr] = m; pref("mats", mats); renderChat(); renderPane(); };
      put([]);
      return UI.undoable(`${was.length} material${was.length === 1 ? "" : "s"} cleared`, () => put(was), "Material back");
    }
    Chat.picker(kind, xs => {
      const list = material();
      for (const x of xs) if (!list.some(y => y.kind === x.kind && y.id === x.id)) list.push(x);
      if (list.length > 6) toast("Up to six pieces of material: the oldest were dropped");
      mats[track] = list.slice(-6); pref("mats", mats);
      renderPane(); renderChat();
    }, { title: "Material to practise from", note: `Drills on the ${T().title} track are built from what you add here.` });
  }

  // ---------- progress ----------
  async function tick(box) {
    const id = box.dataset.stTick, done = box.checked, m = topicOf(id)?.module, was = m && m.done;
    const before = steps().find(s => s.list.some(x => x.id === id));
    try {
      d = await api("/api/study/topics", { method: "PUT", body: { track, topic: id, done, today: today() } });
      const now = T().modules.find(x => x.id === m?.id), after = before && steps().find(s => s.id === before.id);
      if (done && after?.status === "done" && before.status !== "done") { toast(`Step ${after.n} done: ${after.title}. On to the next one!`); flipped.clear(); }
      else if (done && now && now.done === now.total && was < now.total) toast(`Module complete: ${now.title}`);
      renderSide(); renderProg(); renderPane();
    } catch (e) { box.checked = !done; toast(e.message); }
  }
  async function saveProfile() {
    const level = $("[data-st-level]")?.value ?? "", goal = $("[data-st-goal]")?.value ?? "", pace = +($("[data-st-pace]")?.value || T().pace);
    try { d = await api(`/api/study/profile?today=${today()}`, { method: "PUT", body: { track, level, goal, pace } }); toast("Saved"); renderProg(); if (!Practice.active()) renderPane(); }
    catch (e) { toast(e.message); }
  }
  // after a tutor answers: the streak, and topics it may have ticked
  async function refresh() {
    const before = JSON.stringify(T().modules.map(m => m.done));
    try { await load(); } catch { return; }
    renderSide();
    if (JSON.stringify(T().modules.map(m => m.done)) !== before) { renderProg(); if (!Practice.active()) renderPane(); }
  }

  // ---------- the study team ----------
  async function createTeam() {
    try {
      const r = await api(`/api/study/team?today=${today()}`, { method: "POST" });
      d = r; const t = r.team_result;
      toast(t.created ? `Study team ready: ${t.created} tutor${t.created === 1 ? "" : "s"} created` : "Your study team is already complete");
      if (S.view === "study") render();
    } catch (e) { toast(e.message); }
  }
  function select(id) {
    if (picked[track] === id && chat) return;
    picked[track] = id; pref("agents", picked);
    renderSide(); loadChat();
  }
  // a topic: its module's tutor, the topic as the chat's focus, a first message ready to send
  function studyTopic(id) {
    const x = topicOf(id); if (!x) return;
    if (!d.agents.length) return toast("Create the study team first: the button is in the chat panel");
    topic = id;
    const who = tutorFor(x.module.tutor);
    if (who) { picked[track] = who.id; pref("agents", picked); }
    Chat.state(ckey(agent())).text = START[track](x.title);
    renderSide(); if (tab === "path") renderPane(); loadChat(true);
  }
  function drill(id) {
    const x = T().drills.find(y => y.id === id); if (!x) return;
    if (x.mode === "lab") return showLab(true);  // its tasks are worked on in the Lab
    Practice.start(x, env);
  }

  // ---------- chat ----------
  async function loadChat(focus = false) {
    const a = agent(), seq = ++chatSeq;
    chat = null;
    if (!d.agents_enabled || !a) return renderChat(focus);
    $("#st-chat").innerHTML = `<div class="card">${Loading.line("Loading chat…")}</div>`;
    try { const c = await api(`/api/study/chat?agent_id=${a.id}&track=${track}`); if (seq === chatSeq) chat = c; } catch (e) { toast(e.message); }
    if (seq === chatSeq) renderChat(focus);
  }
  const SLASH = [["new", "Start a new chat"], ["next", "Learn the next topic on the roadmap"], ["quiz", "Quiz me on the topic"], ["plan", "Plan my week from the roadmap"],
    ["testout", "Test out of the current step"], ["material", "Attach my practice material"], ["lab", "Open the Lab: terminal, Python, SQL and prompts"]];
  async function command(cmd) {
    const cur = steps().find(s => s.status === "current"), x = cur?.list.find(y => !y.done);
    if (cmd === "new") { newChat(); return true; }
    if (cmd === "next") { if (x) studyTopic(x.id); else toast("Every step is done"); return true; }
    if (cmd === "quiz") { const q = quizDrill(); if (q) runDrill(q.id, { topicId: topic || x?.id }); return true; }
    if (cmd === "plan") { const p = T().drills.find(y => y.mode === "plan"); if (p) runDrill(p.id); else if (cur) stepHelp(cur.id); return true; }
    if (cmd === "testout") { if (cur) testOut(cur.id); else toast("Every step is done"); return true; }
    if (cmd === "lab") { if (Lab.available(T())) showLab(); else toast("The Lab is on the AI Engineer track"); return true; }
    if (cmd === "material") { if (!material().length) toast("Add material in Practice first, or use + to attach a file"); else material().forEach(m => Chat.add(ckey(agent()), m)); return true; }
    return false;
  }
  async function newChat() {
    const a = agent(), tr = track; if (!a) return;
    if (chat?.items?.length && !await UI.confirm({ title: "Start a new chat?", body: `This chat with ${esc(a.name)} is cleared. Your progress, flashcards and notes stay. This can't be undone.`, ok: "Clear and start new", icon: "chat" })) return;
    api(`/api/study/chat?agent_id=${a.id}&track=${tr}`, { method: "DELETE" }).then(c => { if (agent() === a && track === tr) { chat = c; renderChat(); } }).catch(x => toast(x.message)); }
  function renderChat(focus = false) {
    const box = $("#st-chat"); if (!box) return;
    if (!d.agents_enabled) { box.innerHTML = ""; return; }
    const a = agent(), t = T();
    if (!a) {
      const team = d.team.filter(x => x.track === track || x.track === "both");
      box.innerHTML = `<div class="card chat-empty st-team">
        <div class="st-faces">${team.map(x => av(x, "lg")).join("")}</div>
        <h3>Meet your study team</h3>
        <p class="muted">${team.map(x => `<b>${esc(x.name)}</b>, ${esc(x.role)}`).join(" · ")}</p>
        <p class="muted small">Six tutors in all: a mentor who plans your path to AI engineer, a tutor for concepts, code and quizzes, an interview coach who runs mock interviews in English, a conversation partner, a writing and grammar coach, and a vocabulary and pronunciation coach.</p>
        <button type="button" class="btn primary" data-st="team">${icon("users")}Create study team</button>
        <p class="faint small">They see your progress and roadmap step and tick topics once you've shown you know them. Chats are kept per tutor and track.</p></div>`;
      return;
    }
    const items = chat?.items || [], x = topic && topicOf(topic), paused = a.status === "paused", m = material();
    const o = { key: ckey(a), busy, disabled: paused, compact: !wideChat, mic: "en-US", slash: SLASH, onCommand: command, mention: Chat.defaultMention,
                tokens: Chat.tokensOf(items), turns: items.filter(i => i.kind === "assistant" && i.tokens).length,
                placeholder: paused ? `${a.name} is paused` : wideChat ? `Message ${a.name}… (+ adds files or code, / for commands)` : `Message ${a.name}…`,
                extra: m.length ? `<button type="button" class="cx-chip-btn" data-st="attach-mats" title="Attach your practice material: ${esc(m.map(y => y.label).join(", "))}" ${busy || paused ? "disabled" : ""}>${icon("clip")}${m.length}</button>` : "",
                onSend: (text, sent) => send(text, sent) };
    box.innerHTML = `<div class="chat card ws-chatbox st-chatbox" data-cx-panel>${Chat.grip()}
      <div class="chat-head">${av(a)}<div class="st-chat-who"><b>${esc(a.name)}${a.role ? ` · ${esc(a.role)}` : ""}</b>
          <small>${esc(t.title)} track</small></div>
        ${Chat.displayButton()}
        <button type="button" class="iconbtn sm" data-st="chat-wide" title="${wideChat ? "Narrow the chat" : "Widen the chat"}" aria-label="${wideChat ? "Narrow the chat" : "Widen the chat"}" aria-pressed="${wideChat}">${icon(wideChat ? "shrink" : "expand")}</button>
        <button type="button" class="iconbtn sm" data-st="open-agent" title="Open in Agents: memory, brain and past chats" aria-label="Open ${esc(a.name)} in Agents">${icon("external")}</button>
        <button type="button" class="btn sm head-btn" data-st="new-chat" ${items.length ? "" : "disabled"}>${icon("plus")}New</button></div>
      <div class="st-topicbar">${x ? `${icon("book")}<span title="${esc(x.title)}">Topic: ${esc(x.title)}</span><button type="button" class="iconbtn sm" data-st="clear-topic" aria-label="Clear the topic" title="Clear the topic">${icon("close")}</button>` : ""}</div>
      <div class="chat-log cx-log" id="st-log" aria-live="polite">${Chat.log(items, { agent: a, busy, toolHtml: i => `${icon(i.name === "mark_topic" ? "check" : i.name === "remember" ? "bulb" : "book")}${toolText(i)}`, speaking,
        empty: `<div class="chat-empty">${av(a, "lg")}<p class="muted">${esc(a.description || `Ask ${a.name} anything.`)}</p>
           <div class="chips">${(a.examples || []).map(e => `<button type="button" class="chip" data-cx-say="${esc(e)}">${esc(e)}</button>`).join("")}</div></div>` })}</div>
      ${Chat.composer(o)}</div>`;
    Chat.enhance($("#st-log"));
    Chat.mount(box.querySelector(".cx-composer"), o);
    Chat.bind(box, { items: () => chat?.items || [], onSay: text => send(text), lang: "en-US", voice: () => Voice.pick(), onSpeak: n => { speaking = n; } });
    if (focus) { box.scrollIntoView({ block: "nearest" }); Chat.focus(ckey(a)); }
  }
  function toolText(i) {
    if (i.name === "mark_topic") { const x = topicOf(i.input?.topic); return `${i.input?.done === false ? "Unticked" : "Ticked"}: ${esc(x?.title || i.input?.topic || "a topic")}`; }
    if (i.name === "remember") return `Remembered: ${esc(i.input?.fact || "")}`;
    return esc(Agents.toolLabel(i.name));
  }
  async function send(text, sent = []) {
    const a = agent(), tr = track, tp = topic;
    if (busy || !a || !text.trim()) return false;
    Chat.stopMic();
    busy = true;
    chat = { ...(chat || {}), items: [...(chat?.items || []), { kind: "user", text, attachments: sent.map(x => ({ kind: x.kind, label: x.label })) }] };
    renderChat();
    let ok = true;
    try {
      const r = await api("/api/study/chat", { method: "POST", body: { agent_id: a.id, track: tr, topic: tp, message: text, ...Chat.choice(), today: today(), attachments: sent.map(x => ({ kind: x.kind, id: x.id })) } });
      if (agent() === a && track === tr) { chat = r; if (r.error) chat.items.push({ kind: "note", text: r.error }); }
    } catch (e) { if (agent() === a && track === tr) chat.items.push({ kind: "note", text: e.message }); ok = false; }
    busy = false;
    if (S.view === "study") { renderChat(); Chat.focus(ckey(a)); refresh(); }
    return ok;
  }

  function wire() {
    if (wired) return; wired = true;
    const root = $("#view-study");
    root.addEventListener("click", e => {
      if (tab === "lab" && Lab.click(e)) return;
      if (Practice.click(e)) return;
      const t = e.target, k = t.closest("[data-st]")?.dataset.st;
      if (k === "team") return createTeam();
      if (k === "clear-topic") { topic = null; renderChat(); if (tab === "path") renderPane(); return; }
      if (k === "open-agent") { Agents.openAgent(agent().id); return setView("agents"); }
      if (k === "new-chat") return newChat();
      if (k === "chat-wide") { wideChat = !wideChat; pref("wideChat", wideChat); $("#view-study .ws").classList.toggle("wide-chat", wideChat); return renderChat(); }
      if (k === "attach-mats") { material().forEach(m => Chat.add(ckey(agent()), m)); return Chat.focus(ckey(agent())); }
      const tr = t.closest("[data-st-track]"); if (tr) { if (tr.dataset.stTrack !== track) { Practice.leave(); if (tab === "lab") Lab.leave(); track = tr.dataset.stTrack; pref("track", track); topic = null; back = null; flipped.clear(); render(); } return; }
      const tb = t.closest("[data-st-tab]"); if (tb) {
        if (tab === "lab" && tb.dataset.stTab !== "lab") Lab.leave();
        tab = tb.dataset.stTab; pref("tab", tab); back = null; if (tab !== "practice") { Practice.quiet(); wide(false); } return renderPane();
      }
      const md = t.closest("[data-st-mode]"); if (md) { modes[track] = md.dataset.stMode; pref("mode", modes); flipped.clear(); renderProg(); return renderPane(); }
      const sd = t.closest("[data-st-step]"); if (sd) return showStep(sd.dataset.stStep);
      const fd = t.closest("[data-st-fold]"); if (fd) { const id = fd.dataset.stFold; flipped.has(id) ? flipped.delete(id) : flipped.add(id); return renderPane(); }
      const run = t.closest("[data-st-run]"); if (run) { const s = steps().find(x => x.id === run.dataset.stRun); return runDrill(run.dataset.drill, { topicId: s?.list.find(y => !y.done)?.id || null }); }
      const qz = t.closest("[data-st-quiz]"); if (qz) { const q = quizDrill(); return q && runDrill(q.id, { topicId: qz.dataset.stQuiz }); }
      if (t.closest("[data-st-cards]")) { const c = T().drills.find(x => x.mode === "cards"); return c && runDrill(c.id); }
      const to = t.closest("[data-st-testout]"); if (to) return testOut(to.dataset.stTestout);
      const hp = t.closest("[data-st-help]"); if (hp) return stepHelp(hp.dataset.stHelp);
      const un = t.closest("[data-st-undo]"); if (un) return setStep(un.dataset.stUndo, false);
      const al = t.closest("[data-st-all]"); if (al) return setStep(al.dataset.stAll, true);
      const mt = t.closest("[data-st-mat]"); if (mt) return addMaterial(mt.dataset.stMat);
      const um = t.closest("[data-st-unmat]"); if (um) { material().splice(+um.dataset.stUnmat, 1); pref("mats", mats); renderChat(); return renderPane(); }
      const a = t.closest("[data-st-agent]"); if (a) return select(+a.dataset.stAgent);
      const tp = t.closest("[data-st-topic]"); if (tp) return studyTopic(tp.dataset.stTopic);
      const dr = t.closest("[data-st-drill]"); if (dr) return drill(dr.dataset.stDrill);
    });
    root.addEventListener("change", e => {
      if (tab === "lab" && Lab.change(e)) return;
      if (Practice.change(e)) return;
      if (e.target.matches("[data-st-tick]")) return tick(e.target);
      if (e.target.matches("[data-st-level], [data-st-goal], [data-st-pace]")) return saveProfile();
    });
    root.addEventListener("input", e => { if (tab === "lab" && Lab.input(e)) return; Practice.input(e); });
    root.addEventListener("scroll", e => { if (tab === "lab") Lab.scroll(e); }, true);  // the editor's line numbers follow it
    document.addEventListener("keydown", e => { if (tab === "lab" && Lab.key(e)) return; Practice.key(e); });  // flashcard keys work wherever the focus is
    root.addEventListener("keydown", e => {
      if (e.key === "Enter" && e.target.matches("[data-st-goal]")) { e.preventDefault(); e.target.blur(); }  // blur fires change, which saves
      if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-st-track], [data-st-agent]")) { e.preventDefault(); e.target.click(); }
    });
  }
  // a dot on the rail: that step, unfolded, on the roadmap
  function showStep(id) {
    const s = steps().find(x => x.id === id); if (!s) return;
    if (!isOpen(s)) flipped.has(id) ? flipped.delete(id) : flipped.add(id);
    if (tab !== "roadmap") { if (tab === "lab") Lab.leave(); tab = "roadmap"; pref("tab", tab); back = null; Practice.quiet(); wide(false); }
    renderPane();
    $(`#st-pane .rm-step[data-step="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  return { init, open, stop };
})();
