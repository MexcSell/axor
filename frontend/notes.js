/* Sticky notes: light markdown (checklists, bold, italic, strike, ==highlight==, headings, lists, code, links,
   SN mentions that open the subnet), any color, resizable cards, a formatting toolbar, Beautify, a PDCA
   board and one Daily note per day that carries over unchecked items. Used by the workspace's Notes tab
   and the dashboard; event handling is delegated from the document so a card works wherever it's shown. */
const Notes = (() => {
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("notes." + k)); localStorage.setItem("notes." + k, JSON.stringify(v)); } catch { return null; } };
  let notes = [], daily = [], view = pref("view") || "board", editing = null, day = null, wired = false;
  let ctx = { sel: null, scope: "here", scopeSeg: () => "", onChange: () => {} }, color = pref("color") || "yellow";
  const saving = {}, inflight = new Set();  // note id -> pending autosave; saves on the wire
  const COLORS = ["yellow", "pink", "blue", "green", "violet"];
  const STAGES = [["plan", "Plan", "Set a goal and how you'll measure it"], ["do", "Do", "Run the change on a small scale"],
                  ["check", "Check", "Compare the results with the plan"], ["act", "Act", "Adopt it, adjust it or drop it"]];
  const TEMPLATES = {
    checklist: "## Checklist\n- [ ] ",
    pdca: "## Plan\nGoal: \nMeasure: \n\n## Do\n- [ ] \n\n## Check\nResult: \n\n## Act\n- [ ] Adopt / adjust / drop",
    run: "## Mining run\nHotkey: \nModel / config: \nStarted: \n\n- [ ] Registered\n- [ ] Miner up and serving\n- [ ] First incentive seen\n\nNotes: ",
  };
  const today = () => new Date().toLocaleDateString("en-CA");  // local YYYY-MM-DD
  const byId = id => notes.find(n => n.id === id) || daily.find(n => n.id === id);
  const apply = r => { if (r.notes) notes = r.notes; if (r.daily) daily = r.daily; };

  async function load() { try { apply(await api("/api/workspace/notes")); } catch {} }
  const forSubnet = n => notes.filter(x => x.netuid == null || x.netuid === n);
  const visible = () => ctx.scope === "all" ? notes : forSubnet(ctx.sel);

  // ---------- markdown ----------
  function inline(s) {
    const code = [];
    s = esc(s).replace(/`([^`]+)`/g, (_, c) => `\u0000${code.push(c) - 1}\u0000`);
    s = s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/~~(.+?)~~/g, "<s>$1</s>").replace(/==(.+?)==/g, "<mark>$1</mark>")
      .replace(/(^|[^\w*])\*(?!\s)([^*]+?)\*(?!\w)/g, "$1<i>$2</i>").replace(/(^|[^\w])_(?!\s)([^_]+?)_(?!\w)/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    let skip = 0;  // SN12 mentions open the subnet, except inside links
    s = s.split(/(<[^>]+>)/).map(p => {
      if (p.startsWith("<")) { if (/^<a\b/.test(p)) skip++; else if (p === "</a>") skip--; return p; }
      return skip ? p : p.replace(/\bSN(\d{1,3})\b/g, '<button type="button" class="ws-snref" data-open="$1">SN$1</button>');
    }).join("");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${code[i]}</code>`);
  }
  function md(text) {
    let html = "", list = null;
    const close = () => { if (list) { html += list === "ol" ? "</ol>" : "</ul>"; list = null; } };
    const open = t => { if (list !== t) { close(); html += t === "ol" ? "<ol>" : t === "check" ? '<ul class="ck">' : "<ul>"; list = t; } };
    (text || "").split("\n").forEach((l, i) => {
      let m;
      if ((m = l.match(/^\s*[-*+] \[( |x|X)\]\s?(.*)$/))) {
        open("check"); const done = m[1] !== " ";
        html += `<li class="${done ? "done" : ""}"><label><input type="checkbox" data-line="${i}" ${done ? "checked" : ""}><span>${inline(m[2]) || "&nbsp;"}</span></label></li>`;
      } else if ((m = l.match(/^\s*[-*+•] (.*)$/))) { open("ul"); html += `<li>${inline(m[1])}</li>`; }
      else if ((m = l.match(/^\s*\d+[.)] (.*)$/))) { open("ol"); html += `<li>${inline(m[1])}</li>`; }
      else {
        close();
        if ((m = l.match(/^(#{1,3}) (.*)$/))) html += `<h${m[1].length + 3}>${inline(m[2])}</h${m[1].length + 3}>`;
        else if ((m = l.match(/^> ?(.*)$/))) html += `<blockquote>${inline(m[1])}</blockquote>`;
        else if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) html += "<hr>";
        else html += l.trim() ? `<p>${inline(l)}</p>` : '<p class="gap"></p>';
      }
    });
    close();
    return html;
  }
  const tasks = text => { const all = (text || "").match(/^\s*[-*+] \[( |x|X)\]/gm) || []; return { total: all.length, done: all.filter(t => !/\[ \]/.test(t)).length }; };

  // tidy a note: one bullet style, real checkboxes for "[]"/"todo:"/"☐", numbered lists renumbered,
  // capitalised items, short "Label:" lines turned into headings, spacing normalised
  function beautify(text) {
    const cap = s => s.replace(/^([a-z])/, c => c.toUpperCase());
    let n = 0;
    const out = text.replace(/\r\n?/g, "\n").replace(/\t/g, "  ").split("\n").map(l => {
      l = l.replace(/\s+$/, "");
      const ind = (l.match(/^\s*/)[0].length >= 2) ? "  " : "", body = l.trim().replace(/ {2,}/g, " ");
      let m;
      if (!/^\d+[.)]/.test(body)) n = 0;
      if (!body) return "";
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(body)) return "---";
      if ((m = body.match(/^(?:[-*+•]\s*)?(?:\[[xX✓✔]\]|☑|✅|done:)\s*(.+)$/i))) return `${ind}- [x] ${cap(m[1])}`;
      if ((m = body.match(/^(?:[-*+•]\s*)?(?:\[\s?\]|☐|todo:)\s*(.+)$/i))) return `${ind}- [ ] ${cap(m[1])}`;
      if ((m = body.match(/^[-*+•–·]\s*(.+)$/))) return `${ind}- ${cap(m[1])}`;
      if ((m = body.match(/^\d+[.)]\s*(.+)$/))) return `${ind}${++n}. ${cap(m[1])}`;
      if ((m = body.match(/^(#{1,6})\s*(.+?)\s*#*$/))) return `${"#".repeat(Math.min(3, m[1].length))} ${cap(m[2])}`;
      if ((m = body.match(/^([^:]{1,40}):$/)) && m[1].split(" ").length <= 5) return `## ${cap(m[1])}`;
      return cap(body);
    });
    const tidy = [];
    out.forEach(l => {
      if (l.startsWith("#") && tidy.length && tidy[tidy.length - 1] !== "") tidy.push("");
      if (l === "" && (tidy.length === 0 || tidy[tidy.length - 1] === "")) return;
      tidy.push(l);
    });
    while (tidy.length && tidy[tidy.length - 1] === "") tidy.pop();
    return tidy.join("\n");
  }

  // ---------- one card ----------
  const colorOf = x => x.color?.startsWith("#") ? { cls: "n-custom", style: `--c:${esc(x.color)};` } : { cls: `n-${esc(x.color || "yellow")}`, style: "" };
  const stageLabel = s => STAGES.find(x => x[0] === s)?.[1];
  function card(x, mode = "board") {
    const c = colorOf(x), t = tasks(x.text), ed = editing === x.id;
    const size = mode === "board" ? `${x.w ? `width:${x.w}px;` : ""}${x.h ? `height:${x.h}px;` : ""}` : "";
    const i = STAGES.findIndex(s => s[0] === x.stage);
    return `<div class="ws-note ${c.cls} ${x.pinned ? "pinned" : ""} ${ed ? "editing" : ""} m-${mode} ${x.w || x.h ? "sized" : ""}" data-note="${x.id}" style="${c.style}${size}" ${mode === "pdca" && !ed ? 'draggable="true"' : ""}>
      <div class="ws-note-bar">${x.kind === "daily" ? `<span class="ws-tag">Daily</span>` : `<span class="ws-tag" title="${x.netuid == null ? "Shown with every subnet" : `Only shown with SN${x.netuid}`}">${x.netuid == null ? "General" : `SN${x.netuid}`}</span>`}
        ${x.stage && mode !== "pdca" ? `<span class="ws-stage s-${x.stage}" title="PDCA stage">${stageLabel(x.stage)}</span>` : ""}
        <span class="ws-bar-gap"></span>
        ${mode === "pdca" ? `${i > 0 ? `<button type="button" class="iconbtn sm" data-note-act="prev" title="Back to ${STAGES[i - 1][1]}" aria-label="Back to ${STAGES[i - 1][1]}">${icon("left")}</button>` : ""}
          <button type="button" class="iconbtn sm" data-note-act="next" title="${i === 3 ? "Start the next cycle (back to Plan)" : `Move to ${STAGES[i + 1][1]}`}" aria-label="${i === 3 ? "Next cycle" : `Move to ${STAGES[i + 1][1]}`}">${icon(i === 3 ? "cycle" : "right")}</button>` : ""}
        ${x.kind !== "daily" ? `<button type="button" class="iconbtn sm ${x.pinned ? "on" : ""}" data-note-act="pin" aria-pressed="${x.pinned}" title="${x.pinned ? "Unpin" : "Pin to the top"}">${icon("pin")}</button>` : ""}
        <button type="button" class="iconbtn sm" data-note-act="color" title="Color" aria-label="Change color">${icon("palette")}</button>
        <button type="button" class="iconbtn sm" data-note-act="more" title="More" aria-label="More actions">${icon("dots")}</button></div>
      ${ed ? `<div class="ws-fmt" role="toolbar" aria-label="Formatting">
          <button type="button" data-fmt="bold" title="Bold (Ctrl+B)"><b>B</b></button><button type="button" data-fmt="italic" title="Italic (Ctrl+I)"><i>I</i></button>
          <button type="button" data-fmt="strike" title="Strikethrough"><s>S</s></button><button type="button" data-fmt="mark" title="Highlight (Ctrl+E)"><mark>A</mark></button>
          <span class="sep"></span><button type="button" data-fmt="h" title="Heading">H</button><button type="button" data-fmt="ul" title="Bullet list">${icon("menu")}</button>
          <button type="button" data-fmt="check" title="Checklist">${icon("check")}</button><button type="button" data-fmt="ol" title="Numbered list">1.</button>
          <button type="button" data-fmt="code" title="Code">&lt;/&gt;</button><button type="button" data-fmt="link" title="Link">${icon("link")}</button>
          <span class="sep"></span><button type="button" data-fmt="beautify" title="Beautify: tidy lists, checkboxes, headings and spacing">${icon("sparkle")}</button>
          <button type="button" class="done" data-note-act="done" title="Done (Esc)">Done</button></div>
        <textarea aria-label="Note text" maxlength="4000" spellcheck="true">${esc(x.text)}</textarea>`
      : `<div class="ws-note-body md" tabindex="0" title="Click to edit">${md(x.text) || `<p class="faint">Empty note: click to write.</p>`}</div>`}
      <div class="ws-note-foot">${t.total ? `<span class="ws-prog" title="${t.done} of ${t.total} done"><i style="width:${(t.done / t.total * 100).toFixed(0)}%"></i></span><span>${t.done}/${t.total}</span>` : ""}
        <small class="ws-note-time" title="${esc(stamp(x.updated))}">${x.kind === "daily" ? "" : `Edited ${ago(x.updated)}`}</small></div></div>`;
  }
  // a card can be on the workspace and the dashboard at once: redraw every copy, focus the visible editor
  function redraw(id) {
    const x = byId(id); if (!x) return;
    $$(`.ws-note[data-note="${id}"]`).forEach(el => el.outerHTML = card(x, [...el.classList].find(c => c.startsWith("m-")).slice(2)));
    if (editing === id) {
      const ta = $$(`.ws-note[data-note="${id}"] textarea`).find(t => t.offsetParent);
      if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    }
  }
  async function ensureToday() {
    let x = daily.find(n => n.day === today());
    if (!x) { x = (await api(`/api/workspace/notes/daily?day=${today()}&create=true`)).note; if (x) daily = [x, ...daily.filter(n => n.id !== x.id)]; }
    return x;
  }

  // ---------- saving ----------
  function queueSave(id, el, now = false) {
    clearTimeout(saving[id]?.t);
    const go = () => {
      delete saving[id];
      const x = byId(id); if (!x || x.text === el.value) return;
      x.text = el.value;
      const time = el.closest(".ws-note")?.querySelector(".ws-note-time");
      if (time && x.kind !== "daily") time.textContent = "Saving…";
      const p = api(`/api/workspace/notes/${id}`, { method: "PATCH", body: { text: el.value } })
        .then(r => { const y = (r.notes || []).concat(r.daily || []).find(n => n.id === id); if (y) Object.assign(x, y); if (time && x.kind !== "daily") time.textContent = "Saved"; })
        .catch(e => { if (time) time.textContent = "Not saved"; toast(e.message); })
        .finally(() => inflight.delete(p));
      inflight.add(p);
    };
    if (now) go(); else saving[id] = { t: setTimeout(go, 700), go };
  }
  const settle = () => { Object.values(saving).forEach(p => { clearTimeout(p.t); p.go(); }); return Promise.all([...inflight]); };
  async function patch(id, body, rerender = true) {
    await settle();
    apply(await api(`/api/workspace/notes/${id}`, { method: "PATCH", body }));
    ctx.onChange();
    if (rerender) { refresh(); redraw(id); }
  }
  function edit(id) {
    if (editing === id) return;
    const prev = editing; editing = id;
    if (prev != null) finish(prev);
    redraw(id);
  }
  function finish(id = editing) {
    if (id == null) return;
    // the same card can sit on a hidden view too: save from the copy being typed in, not the first in the DOM
    const tas = $$(`.ws-note[data-note="${id}"] textarea`), ta = tas.find(t => t === document.activeElement) || tas.find(t => t.offsetParent);
    if (ta) queueSave(id, ta, true);
    if (editing === id) editing = null;
    redraw(id);
  }

  // ---------- formatting ----------
  function fmt(ta, k) {
    const { selectionStart: a, selectionEnd: b, value: v } = ta;
    const wrap = (pre, post = pre, ph = "text") => {
      const s = v.slice(a, b) || ph;
      ta.setRangeText(pre + s + post, a, b, "end");
      ta.setSelectionRange(a + pre.length, a + pre.length + s.length);
    };
    const lines = (test, add, strip) => {
      const s = v.lastIndexOf("\n", a - 1) + 1, e0 = v.indexOf("\n", b), e = e0 < 0 ? v.length : e0;
      const ls = v.slice(s, e).split("\n"), all = ls.every(l => test.test(l));
      ta.setRangeText(ls.map((l, i) => all ? l.replace(strip, "") : add(l.replace(strip, ""), i)).join("\n"), s, e, "select");
    };
    if (k === "bold") wrap("**");
    else if (k === "italic") wrap("*");
    else if (k === "strike") wrap("~~");
    else if (k === "mark") wrap("==");
    else if (k === "code") wrap("`", "`", "code");
    else if (k === "link") { const s = v.slice(a, b) || "link"; ta.setRangeText(`[${s}](https://)`, a, b, "end"); ta.setSelectionRange(a + s.length + 3, a + s.length + 11); }
    else if (k === "h") lines(/^#{1,3} /, l => "## " + l, /^#{1,3} /);
    else if (k === "ul") lines(/^\s*[-*+] (?!\[)/, l => "- " + l, /^\s*(?:[-*+] (?:\[[ xX]\] )?|\d+[.)] )/);
    else if (k === "check") lines(/^\s*[-*+] \[[ xX]\] /, l => "- [ ] " + l, /^\s*(?:[-*+] (?:\[[ xX]\] )?|\d+[.)] )/);
    else if (k === "ol") lines(/^\s*\d+[.)] /, (l, i) => `${i + 1}. ${l}`, /^\s*(?:[-*+] (?:\[[ xX]\] )?|\d+[.)] )/);
    else if (k === "beautify") { const t = beautify(v); if (t === v) return toast("Already tidy"); ta.value = t; toast("Note beautified"); }
    ta.focus();
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  // Enter inside a list continues it; Enter on an empty item ends the list
  function enter(ta, e) {
    const v = ta.value, a = ta.selectionStart, s = v.lastIndexOf("\n", a - 1) + 1, line = v.slice(s, a);
    const m = line.match(/^(\s*)([-*+] \[[ xX]\] |[-*+] |(\d+)[.)] )(.*)$/);
    if (!m || ta.selectionStart !== ta.selectionEnd) return;
    e.preventDefault();
    if (!m[4].trim()) { ta.setRangeText("", s, a, "end"); }
    else ta.setRangeText("\n" + m[1] + (m[3] ? `${+m[3] + 1}. ` : m[2].replace(/\[[xX]\]/, "[ ]")), a, a, "end");
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  async function toggleLine(id, i, on) {
    const x = byId(id); if (!x) return;
    const ls = x.text.split("\n");
    ls[i] = ls[i].replace(/\[( |x|X)\]/, on ? "[x]" : "[ ]");
    x.text = ls.join("\n");
    redraw(id);
    try { await patch(id, { text: x.text }, false); redraw(id); } catch (e) { toast(e.message); }
  }

  // ---------- menus ----------
  function popover(btn, html, onPick) {
    document.querySelector(".popover.menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover menu ws-pop";
    pop.innerHTML = html;
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px";
    pop.style.left = Math.max(16, Math.min(b.left + scrollX, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.addEventListener("click", e => { const k = e.target.closest("[data-pick]")?.dataset.pick; if (k) { pop.remove(); onPick(k); } });
    return pop;
  }
  function colorMenu(btn, x) {
    const pop = popover(btn, `<div class="ws-pop-colors">${COLORS.map(c => `<button type="button" class="ws-sw n-${c} ${x.color === c ? "on" : ""}" data-pick="${c}" title="${c[0].toUpperCase() + c.slice(1)}" aria-label="${c}"></button>`).join("")}</div>
      <label class="ws-pop-custom">${icon("palette")}Custom color<input type="color" value="${x.color?.startsWith("#") ? esc(x.color) : "#f2c94c"}"></label>`, c => patch(x.id, { color: c }).catch(e => toast(e.message)));
    $("input[type=color]", pop).onchange = e => { pop.remove(); patch(x.id, { color: e.target.value }).catch(er => toast(er.message)); };
  }
  function moreMenu(btn, x) {
    const daily = x.kind === "daily";
    const items = [
      ["edit", "note", "Edit"],
      ["beautify", "sparkle", "Beautify"],
      !daily && ["dup", "copy", "Duplicate"],
      ["copy", "copy", "Copy text"],
      !daily && (x.netuid == null ? ctx.sel != null && ["here", "pickaxe", `Only show with SN${ctx.sel}`] : ["general", "globe", "Show with every subnet"]),
      !daily && (x.w || x.h) && ["resize", "reset", "Reset size"],
      Slack.ready() && ["slack", "hash", "Share to Slack"],
      !daily && "sep",
      ...(!daily ? STAGES.map(([k, l]) => [`stage:${k}`, x.stage === k ? "check" : "cycle", `PDCA: ${l}`]) : []),
      !daily && x.stage && ["stage:", "close", "Remove from PDCA"],
      "sep",
      ["delete", "close", "Delete"],
    ].filter(Boolean);
    popover(btn, items.map(i => i === "sep" ? '<div class="mi-sep"></div>' : `<button type="button" class="mi ${i[0] === "delete" ? "danger" : ""}" data-pick="${i[0]}">${icon(i[1])}${esc(i[2])}</button>`).join(""), k => act(x, k));
  }
  async function act(x, k) {
    try {
      if (k === "edit") return edit(x.id);
      if (k === "beautify") { const t = beautify(x.text); if (t === x.text) return toast("Already tidy"); await patch(x.id, { text: t }); return toast("Note beautified"); }
      if (k === "copy") { await navigator.clipboard.writeText(x.text); return toast("Copied"); }
      if (k === "slack") { await settle(); return Slack.share("note", x.id, x.kind === "daily" ? `Your daily note for ${x.day}` : `Your note: “${x.text.split("\n").find(l => l.trim())?.replace(/^\s*(?:#+|[-*+] \[[ xX]\]|[-*+])\s*/, "").slice(0, 80) || "Empty note"}”`); }
      if (k === "dup") { await settle(); apply(await api("/api/workspace/notes", { method: "POST", body: { text: x.text, color: x.color, netuid: x.netuid, stage: x.stage, w: x.w, h: x.h } })); ctx.onChange(); refresh(); return toast("Note duplicated"); }
      if (k === "here") return await patch(x.id, { netuid: ctx.sel });
      if (k === "general") return await patch(x.id, { netuid: null });
      if (k === "resize") return await patch(x.id, { w: null, h: null });
      if (k.startsWith("stage:")) return await patch(x.id, { stage: k.slice(6) || null });
      if (k === "delete") return remove(x);
    } catch (e) { toast(e.message); }
  }
  function remove(x) {
    clearTimeout(saving[x.id]?.t); delete saving[x.id];
    const go = async () => { await settle(); apply(await api(`/api/workspace/notes/${x.id}`, { method: "DELETE" })); if (editing === x.id) editing = null; ctx.onChange(); refresh(); };
    if (!x.text.trim()) return go().catch(e => toast(e.message));
    Auth.modal(`<h3>${icon("note")}Delete this note?</h3><p class="muted ws-quote">${esc(x.text.slice(0, 240))}${x.text.length > 240 ? "…" : ""}</p>`,
      async () => { await go(); $("#modal").close(); toast("Note deleted"); }, { submit: "Delete", danger: true });
  }

  // ---------- views ----------
  let host = null;
  function render(el, c) { host = el; ctx = { ...ctx, ...c }; refresh(); }
  function refresh() {
    if (!host || !host.isConnected) return;
    const seg = `<div class="seg" role="tablist" aria-label="Notes view">${[["board", "note", "Board"], ["pdca", "cycle", "PDCA"], ["daily", "calendar", "Daily"]].map(([k, ic, l]) => `<button type="button" data-nv="${k}" aria-pressed="${view === k}">${icon(ic)}${l}</button>`).join("")}</div>`;
    if (view === "daily") return renderDaily(seg);
    const list = visible().filter(x => view !== "pdca" || x.stage);
    const head = `<div class="ws-notes-head">${seg}${ctx.scopeSeg("notes")}</div>`;
    if (view === "pdca") {
      host.innerHTML = `${head}<p class="faint ws-pdca-lead">Run each idea through Plan → Do → Check → Act. Drag cards between columns or use the arrows; from Act, start the next cycle.</p>
        <div class="ws-pdca">${STAGES.map(([k, l, hint]) => {
          const xs = list.filter(x => x.stage === k);
          return `<section class="ws-col s-${k}" data-stage="${k}"><header><b>${l}</b><span class="faint">${xs.length}</span><small class="faint">${hint}</small></header>
            <div class="ws-col-list">${xs.map(x => card(x, "pdca")).join("")}</div>
            <form class="ws-col-add" data-add-stage="${k}"><input name="text" maxlength="300" placeholder="Add to ${l}…" aria-label="Add a note to ${l}"></form></section>`;
        }).join("")}</div>`;
      return;
    }
    host.innerHTML = `${head}<div class="card ws-note-new-card"><form class="ws-note-new" id="ws-note-new">
        <textarea name="text" rows="2" maxlength="4000" placeholder="Jot something down${ctx.sel == null ? "" : ` about SN${ctx.sel}`}… (markdown: - [ ] task, **bold**, ==highlight==)" aria-label="New note"></textarea>
        <div class="row"><div class="ws-colors" role="radiogroup" aria-label="Note color">${COLORS.map(c => `<label class="ws-sw n-${c}" title="${c[0].toUpperCase() + c.slice(1)}"><input type="radio" name="color" value="${c}" ${c === color ? "checked" : ""}><span class="sr">${c}</span></label>`).join("")}
          <label class="ws-sw ws-sw-custom ${color.startsWith("#") ? "n-custom" : ""}" style="${color.startsWith("#") ? `--c:${esc(color)}` : ""}" title="Custom color"><input type="color" name="custom" value="${color.startsWith("#") ? esc(color) : "#f2c94c"}"><span class="sr">Custom color</span></label></div>
          <select name="tpl" aria-label="Start from a template"><option value="">Blank</option><option value="checklist">Checklist</option><option value="pdca">PDCA cycle</option><option value="run">Mining run log</option></select>
          ${ctx.sel == null ? "" : `<label class="chk"><input type="checkbox" name="general"> Every subnet</label>`}
          <button class="btn primary sm" type="submit">${icon("plus")}Add note</button></div></form></div>
      <div class="ws-notes">${list.map(x => card(x)).join("") || `<p class="faint ws-none">No notes ${ctx.scope === "all" || ctx.sel == null ? "yet" : `for SN${ctx.sel} yet`}. Ideas, hotkeys, to-dos, results from your last run: they're private to you.</p>`}</div>`;
    const f = $("#ws-note-new");
    f.elements.text.addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); f.requestSubmit(); } });
    f.onchange = e => {
      if (e.target.name === "color") { color = e.target.value; pref("color", color); $(".ws-sw-custom", f).classList.remove("n-custom"); }
      if (e.target.name === "custom") { color = e.target.value; pref("color", color); $$("[name=color]", f).forEach(r => r.checked = false); const l = $(".ws-sw-custom", f); l.classList.add("n-custom"); l.style.setProperty("--c", color); }
      if (e.target.name === "tpl" && e.target.value) { if (!f.elements.text.value.trim()) f.elements.text.value = TEMPLATES[e.target.value]; e.target.value = ""; f.elements.text.focus(); }
    };
    f.onsubmit = async e => {
      e.preventDefault();
      const text = f.elements.text.value.trim(); if (!text) return f.elements.text.focus();
      try {
        await settle();
        apply(await api("/api/workspace/notes", { method: "POST", body: { text, color, netuid: f.elements.general?.checked ? null : ctx.sel, stage: /^## Plan/m.test(text) && /^## Act/m.test(text) ? "plan" : null } }));
        ctx.onChange(); refresh(); $("#ws-note-new textarea")?.focus();
      } catch (x) { toast(x.message); }
    };
  }
  const dayLabel = d => { const t = new Date(d + "T12:00:00"); return t.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", ...(t.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) }); };
  const shift = (d, n) => { const t = new Date(d + "T12:00:00"); t.setDate(t.getDate() + n); return t.toLocaleDateString("en-CA"); };
  function streak() {
    const have = new Set(daily.filter(x => x.text.replace(/^## Today\n- \[ \] ?$/m, "").trim()).map(x => x.day));
    let n = 0, d = have.has(today()) ? today() : shift(today(), -1);
    while (have.has(d)) { n++; d = shift(d, -1); }
    return n;
  }
  async function renderDaily(seg) {
    day = day || today();
    const d = day, isToday = d === today();
    let x = daily.find(n => n.day === d);
    if (!x) {
      host.innerHTML = `<div class="ws-notes-head">${seg}</div>${Loading.cards(1, "card")}`;
      try { const r = await api(`/api/workspace/notes/daily?day=${d}&create=${isToday}`); x = r.note; if (x) { daily = [x, ...daily.filter(n => n.id !== x.id)].sort((a, b) => b.day.localeCompare(a.day)); ctx.onChange(); } }
      catch (e) { toast(e.message); }
      if (day !== d || view !== "daily") return;
    }
    const recent = daily.slice(0, 14), st = streak();
    host.innerHTML = `<div class="ws-notes-head">${seg}<span class="faint small">Shared across all subnets</span></div>
      <div class="ws-daily-head"><button type="button" class="iconbtn" data-day="${shift(d, -1)}" aria-label="Previous day" title="Previous day">${icon("left")}</button>
        <h3>${isToday ? "Today · " : ""}${dayLabel(d)}</h3>
        <button type="button" class="iconbtn" data-day="${shift(d, 1)}" aria-label="Next day" title="Next day" ${d >= today() ? "disabled" : ""}>${icon("right")}</button>
        ${isToday ? "" : `<button type="button" class="btn sm" data-day="${today()}">Today</button>`}
        ${st ? `<span class="badge clear" title="Days in a row with a daily note">${icon("zap")}${st}-day streak</span>` : ""}</div>
      <div class="ws-daily">${x ? card(x, "daily") : `<div class="card empty">No daily note for ${dayLabel(d)}.</div>`}</div>
      ${recent.length ? `<h4 class="sub">Recent days</h4><div class="ws-days">${recent.map(n => { const t = tasks(n.text); return `<button type="button" class="ws-day ${n.day === d ? "on" : ""}" data-day="${n.day}"><b>${dayLabel(n.day)}</b><small class="faint">${t.total ? `${t.done}/${t.total} done` : "Notes"}</small></button>`; }).join("")}</div>` : ""}`;
  }

  // dashboard summary: open tasks, PDCA stages, today's daily progress
  function stats() {
    const t = notes.reduce((a, x) => { const k = tasks(x.text); a.done += k.done; a.total += k.total; return a; }, { done: 0, total: 0 });
    const td = daily.find(n => n.day === today());
    return { notes: notes.length, tasks: t, pdca: Object.fromEntries(STAGES.map(([k]) => [k, notes.filter(x => x.stage === k).length])),
             today: td ? tasks(td.text) : null, streak: streak(), recent: notes.slice(0, 4) };
  }
  function openView(v) { view = v; pref("view", v); }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const t = e.target;
      const nv = t.closest("[data-nv]"); if (nv) { openView(nv.dataset.nv); return refresh(); }
      const dy = t.closest("[data-day]"); if (dy && host?.contains(dy)) { day = dy.dataset.day; return refresh(); }
      const note = t.closest(".ws-note");
      if (editing != null && !t.closest(`.ws-note[data-note="${editing}"]`) && !t.closest(".popover, dialog")) finish();
      if (!note) return;
      const id = +note.dataset.note, x = byId(id);
      const a = t.closest("[data-note-act]")?.dataset.noteAct;
      if (a === "pin") return patch(id, { pinned: !x.pinned }).catch(er => toast(er.message));
      if (a === "color") return colorMenu(t.closest("button"), x);
      if (a === "more") return moreMenu(t.closest("button"), x);
      if (a === "done") return finish(id);
      if (a === "next" || a === "prev") { const i = STAGES.findIndex(s => s[0] === x.stage); return patch(id, { stage: STAGES[a === "next" ? (i + 1) % 4 : Math.max(0, i - 1)][0] }).catch(er => toast(er.message)); }
      const f = t.closest("[data-fmt]"); if (f) return fmt($("textarea", note), f.dataset.fmt);
      if (t.closest(".ws-note-body") && !t.closest("a, input, label, button")) edit(id);
    });
    document.addEventListener("change", e => { const c = e.target.closest(".ws-note input[data-line]"); if (c) toggleLine(+c.closest(".ws-note").dataset.note, +c.dataset.line, c.checked); });
    document.addEventListener("input", e => { const ta = e.target.closest(".ws-note textarea"); if (ta) queueSave(+ta.closest(".ws-note").dataset.note, ta); });
    document.addEventListener("keydown", e => {
      const ta = e.target.closest?.(".ws-note textarea");
      if (ta) {
        const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); return finish(+ta.closest(".ws-note").dataset.note); }
        if (mod && ["b", "i", "e"].includes(k)) { e.preventDefault(); return fmt(ta, { b: "bold", i: "italic", e: "mark" }[k]); }
        if (e.key === "Enter" && !e.shiftKey && !mod) return enter(ta, e);
      }
      if (e.key === "Enter" && e.target.matches?.(".ws-note-body")) { e.preventDefault(); edit(+e.target.closest(".ws-note").dataset.note); }
    }, true);
    document.addEventListener("submit", async e => {
      const f = e.target.closest("[data-add-stage]"); if (!f) return;
      e.preventDefault();
      const text = f.elements.text.value.trim(); if (!text) return;
      try { await settle(); apply(await api("/api/workspace/notes", { method: "POST", body: { text, color: { plan: "blue", do: "yellow", check: "violet", act: "green" }[f.dataset.addStage], netuid: ctx.sel, stage: f.dataset.addStage } })); ctx.onChange(); refresh(); $(`[data-add-stage="${f.dataset.addStage}"] input`)?.focus(); }
      catch (x) { toast(x.message); }
    });
    // resizing: the browser's corner handle changes the card's size; keep it once the pointer lets go
    let rs = null;
    document.addEventListener("pointerdown", e => { const n = e.target.closest(".ws-note.m-board"); rs = n ? { n, w: n.offsetWidth, h: n.offsetHeight } : null; });
    document.addEventListener("pointerup", () => {
      if (!rs) return;
      const { n, w, h } = rs; rs = null;
      if (Math.abs(n.offsetWidth - w) > 2 || Math.abs(n.offsetHeight - h) > 2) {
        const x = byId(+n.dataset.note); if (!x) return;
        x.w = n.offsetWidth; x.h = n.offsetHeight; n.classList.add("sized");
        api(`/api/workspace/notes/${x.id}`, { method: "PATCH", body: { w: x.w, h: x.h } }).catch(er => toast(er.message));
      }
    });
    // PDCA drag and drop
    document.addEventListener("dragstart", e => { const n = e.target.closest?.(".ws-note.m-pdca"); if (n) { e.dataTransfer.setData("text/x-note", n.dataset.note); e.dataTransfer.effectAllowed = "move"; n.classList.add("dragging"); } });
    document.addEventListener("dragend", e => e.target.closest?.(".ws-note")?.classList.remove("dragging"));
    document.addEventListener("dragover", e => { const c = e.target.closest?.(".ws-col"); if (c && e.dataTransfer.types.includes("text/x-note")) { e.preventDefault(); $$(".ws-col.over").forEach(x => x !== c && x.classList.remove("over")); c.classList.add("over"); } });
    document.addEventListener("dragleave", e => { const c = e.target.closest?.(".ws-col"); if (c && !c.contains(e.relatedTarget)) c.classList.remove("over"); });
    document.addEventListener("drop", e => {
      const c = e.target.closest?.(".ws-col"), id = +e.dataTransfer.getData("text/x-note"); if (!c || !id) return;
      e.preventDefault(); c.classList.remove("over");
      if (byId(id)?.stage !== c.dataset.stage) patch(id, { stage: c.dataset.stage }).catch(er => toast(er.message));
    });
  }

  return { load, render, refresh, wire, stats, settle, forSubnet, card, md, beautify, openView, ensureToday, edit, view: () => view, all: () => notes };
})();
