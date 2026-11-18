/* General Manager chat (gm_chat.py, D-039): the chat button at the top right of every page opens a chat with the company's General
   Manager. Write, paste or attach pictures and documents; an assignment (fix or update a page, change a feature, build a program,
   any work) becomes a mission in Mission Control, shown here as a card that follows its status; a mission waiting for answers is
   answered right in the card. Changes to AXoR itself come back as a proposed change and an approval request: missions never deploy.
   Same people as Mission Control (anyone who may use agents); the button stays hidden for everyone else. */
const GMChat = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("gm." + k)); localStorage.setItem("gm." + k, JSON.stringify(v)); } catch { return null; } };
  const ACTIVE = ["queued", "running", "needs_input", "paused"];
  const TONE = { queued: "run", running: "run", needs_input: "wait", paused: "warn", delivered: "ok", failed: "bad", cancelled: "off" };
  let msgs = [], cards = {}, limits = null, files = [], busy = false, ready = false, timer = null, slow = null, uploading = 0;
  const isOpen = () => !!$("#gm-chat") && !$("#gm-chat").hidden;
  const pageName = () => { const v = typeof S !== "undefined" ? S.view : ""; return ($(`nav.side [data-view="${v}"] .lbl`)?.textContent || v || "").trim(); };
  const when = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  // "#12" links to mission 12: split on the raw text first, then escape each piece (escaping first would turn ' into &#39; and link "#39")
  const text = t => String(t ?? "").split(/(#\d+)\b/).map((p, i) => i % 2 ? `<a href="#" data-gm-open="${p.slice(1)}">${p}</a>` : esc(p)).join("").replace(/\n/g, "<br>");

  async function init() {
    if (ready || !Auth.me()) return;
    let d;
    try { d = await api("/api/gm"); } catch { return; }  // missions off, or agents not open to this account: no button
    ready = true; take(d, true);
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "iconbtn gm-btn"; btn.id = "gm-btn";
    btn.title = "Chat with the General Manager"; btn.setAttribute("aria-label", "Chat with the General Manager");
    btn.setAttribute("aria-controls", "gm-chat"); btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = `${icon("chat")}<span class="gm-dot" hidden></span>`;
    btn.onclick = () => toggle();
    $(".top-right").insertBefore(btn, $("#theme"));
    const p = document.createElement("section");
    p.className = "gm-chat"; p.id = "gm-chat"; p.hidden = true; p.setAttribute("role", "dialog"); p.setAttribute("aria-label", "General Manager chat");
    document.body.appendChild(p);
    draw(); wire(p); render(); dot();
    timer = setInterval(() => refresh(false), 60000);
    if (pref("open")) toggle(true);
  }

  function take(d, all) {
    if (all) msgs = d.messages || [];
    else for (const m of d.messages || []) if (!msgs.some(x => x.id === m.id)) msgs.push(m);
    Object.assign(cards, d.missions || {});
    if (d.limits) limits = d.limits;
  }

  function toggle(on) {
    const p = $("#gm-chat"), b = $("#gm-btn"); if (!p) return;
    on = on ?? p.hidden;
    p.hidden = !on; b.classList.toggle("on", on); b.setAttribute("aria-expanded", String(on)); pref("open", on);
    clearInterval(slow); slow = null;
    if (on) {
      render(); $("#gm-text")?.focus();
      refresh(true);
      slow = setInterval(() => refresh(false), 8000);  // while open: the cards follow their missions
    }
  }

  // ---------- data ----------
  async function refresh(full) {
    try {
      if (full) { take(await api("/api/gm"), true); render(); dot(); return; }
      const ids = Object.values(cards).filter(c => ACTIVE.includes(c.status) || c.approval).map(c => c.id);
      if (!ids.length) return;
      const got = await api("/api/gm/missions", { method: "POST", body: { ids } });
      const changed = ids.some(i => JSON.stringify(got[i]) !== JSON.stringify(cards[i]));
      Object.assign(cards, got);
      if (changed && isOpen() && !$("#gm-chat .gm-answer:focus-within")) render();
      dot();
    } catch {}
  }

  function dot() {
    const n = Object.values(cards).filter(c => c.status === "needs_input" || c.approval).length, d = $("#gm-btn .gm-dot");
    if (!d) return;
    d.hidden = !n; $("#gm-btn").title = n ? `Chat with the General Manager: ${n} mission(s) need you` : "Chat with the General Manager";
  }

  async function send(extra) {
    const box = $("#gm-text"), t = box.value.trim();
    if (busy || uploading || (!t && !files.length)) return;
    busy = true;
    const att = files.map(f => f.id);
    msgs.push({ id: -1, role: "user", text: t, files: files.map(f => ({ id: f.id, name: f.name, kind: f.kind })), at: Date.now() / 1000, pending: true });
    box.value = ""; const keep = files; files = []; render(true);
    try {
      const d = await api("/api/gm/messages", { method: "POST", body: { text: t, attachments: att, page: pageName(), path: location.pathname + location.hash, ...extra } });
      msgs = msgs.filter(m => !m.pending); take(d);
      if (d.kept_files) files = keep;  // not used yet (the General Manager asked for more): they go with the next message
    } catch (e) {
      msgs = msgs.filter(m => !m.pending); box.value = t; files = keep;
      Auth.toast(e.message);
    } finally { busy = false; render(); dot(); box.focus(); }
  }

  async function asMission(id) {
    if (busy) return; busy = true; render(true);
    try { take(await api(`/api/gm/messages/${id}/mission`, { method: "POST", body: { page: pageName(), path: location.pathname + location.hash } })); }
    catch (e) { Auth.toast(e.message); }
    finally { busy = false; render(); dot(); }
  }

  async function answer(form) {
    const mid = form.dataset.gmAnswer, answers = [...form.querySelectorAll("textarea")].map(x => x.value.trim());
    if (answers.some(a => !a)) { Auth.toast("Answer every question (\"you decide\" is an answer)."); return; }
    form.querySelector("button").disabled = true;
    try { await api(`/api/mos/missions/${mid}/answer`, { method: "POST", body: { answers } }); Auth.toast(`Mission #${mid} goes on`); }
    catch (e) { Auth.toast(e.message); form.querySelector("button").disabled = false; return; }
    Object.assign(cards, await api("/api/gm/missions", { method: "POST", body: { ids: [Number(mid)] } }).catch(() => ({})));
    render(); dot();
  }

  async function addFiles(list) {
    const max = limits?.files || 10;
    for (const f of [...list]) {
      if (files.length + uploading >= max) { Auth.toast(`Up to ${max} files with one message.`); break; }
      const isImg = f.type.startsWith("image/");
      if (f.size > ((isImg ? limits?.image_mb : limits?.file_mb) || 20) * 1e6) { Auth.toast(`${f.name}: too large.`); continue; }
      const name = f.name && f.name !== "image.png" ? f.name : `pasted-${Date.now()}.${(f.type.split("/")[1] || "png").replace("jpeg", "jpg")}`;
      uploading++; render(true);
      try {
        const url = await new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = bad; r.readAsDataURL(f); });
        const u = await api("/api/mos/uploads", { method: "POST", body: { filename: name, data: url.split(",")[1] || "" } });
        // the preview is the data: URL itself (the page's CSP allows data: pictures, not blob:)
        files.push({ id: u.id, name: u.name || name, kind: u.kind || (isImg ? "image" : "document"), url: isImg && /^data:image\/(png|jpe?g|gif|webp);base64,/.test(url) ? url : null });
      } catch (e) { Auth.toast(e.message); }
      finally { uploading--; render(true); }
    }
  }

  async function unfile(id) {
    files = files.filter(f => f.id !== id); render(true);
    try { await api(`/api/mos/uploads/${id}`, { method: "DELETE" }); } catch {}
  }

  async function clear() {
    if (!confirm("Clear this chat? Your missions stay in Mission Control.")) return;
    try { await api("/api/gm", { method: "DELETE" }); msgs = []; cards = {}; render(); dot(); } catch (e) { Auth.toast(e.message); }
  }

  // ---------- drawing ----------
  function draw() {
    $("#gm-chat").innerHTML = `
      <header class="gm-head">
        <span class="gm-av" aria-hidden="true">GM</span>
        <span class="gm-who"><b>General Manager</b><small>Give an assignment: it becomes a mission</small></span>
        <button type="button" class="iconbtn sm" data-gm="clear" title="Clear this chat" aria-label="Clear this chat">${icon("reset")}</button>
        <button type="button" class="iconbtn sm" data-gm="close" title="Close" aria-label="Close the chat">${icon("close")}</button>
      </header>
      <div class="gm-log" id="gm-log" aria-live="polite"></div>
      <form class="gm-compose" id="gm-compose">
        <div class="gm-files" id="gm-files"></div>
        <div class="gm-row">
          <button type="button" class="iconbtn sm" data-gm="attach" title="Attach pictures or documents" aria-label="Attach pictures or documents">${icon("clip")}</button>
          <input type="file" id="gm-file" multiple hidden>
          <textarea id="gm-text" rows="2" maxlength="4000" placeholder="Tell the General Manager what you need… (paste a screenshot, Enter to send)" aria-label="Message to the General Manager"></textarea>
          <button type="submit" class="btn primary sm gm-send" title="Send" aria-label="Send">${icon("send")}</button>
        </div>
      </form>`;
  }

  function card(c) {
    if (!c) return "";
    if (c.gone) return `<div class="gm-card"><span class="gm-st off">Removed</span> Mission #${c.id} is no longer in Mission Control.</div>`;
    const q = c.questions || [];
    return `<div class="gm-card">
      <div class="gm-card-top"><span class="gm-st ${TONE[c.status] || "off"}">${esc(c.status_label || c.status)}</span>
        <b>#${c.id} ${esc(c.title || "")}</b></div>
      ${c.doing ? `<p class="gm-doing">${esc(c.doing)}</p>` : c.stage && ACTIVE.includes(c.status) ? `<p class="gm-doing">Stage: ${esc(c.stage)}</p>` : ""}
      ${c.pause_reason ? `<p class="gm-doing warn">${esc(c.pause_reason)}</p>` : ""}
      ${c.summary && !ACTIVE.includes(c.status) ? `<p class="gm-doing">${esc(c.summary)}</p>` : ""}
      ${c.error && c.status === "failed" ? `<p class="gm-doing bad">${esc(c.error)}</p>` : ""}
      ${q.length ? `<form class="gm-answer" data-gm-answer="${c.id}">${q.map((x, i) => `<label>${esc(typeof x === "string" ? x : x.question || x.text || "")}
          <textarea rows="2" maxlength="1000" name="a${i}" placeholder="Your answer (or: you decide)"></textarea></label>`).join("")}
          <button type="submit" class="btn primary sm">Send answers</button></form>` : ""}
      ${c.status === "needs_input" && !q.length ? `<p class="gm-doing warn">A decision waits for you in Mission Control.</p>` : ""}
      ${c.approval && c.status !== "needs_input" ? `<p class="gm-doing warn">Waiting for your approval in Mission Control: ${esc(c.approval)}.</p>` : ""}
      <button type="button" class="btn sm" data-gm-open="${c.id}">${icon("target")} Open in Mission Control</button>
    </div>`;
  }

  function bubble(m, i) {
    const mine = m.role === "user";
    const fl = (m.files || []).map(f => `<span class="gm-chip">${icon(f.kind === "image" ? "image" : "file")}${esc(f.name)}</span>`).join("");
    const prev = msgs[i - 1];
    const offer = m.role === "gm" && m.kind === "reply" && prev?.role === "user" && !prev.mission_id && prev.id > 0 && i === msgs.length - 1;
    return `<div class="gm-msg ${mine ? "me" : "gm"} ${m.kind === "error" ? "err" : ""}">
      ${mine ? "" : `<span class="gm-av sm" aria-hidden="true">GM</span>`}
      <div class="gm-bub">${m.text ? `<p>${text(m.text)}</p>` : ""}${fl ? `<div class="gm-chips">${fl}</div>` : ""}
        ${m.kind === "mission" && m.mission_id ? card(cards[m.mission_id]) : ""}
        ${offer ? `<button type="button" class="btn sm" data-gm-mission="${prev.id}">${icon("target")} Start as a mission</button>` : ""}
        <small class="gm-at">${m.pending ? "Sending…" : when(m.at)}</small></div></div>`;
  }

  function render(composerOnly) {
    const log = $("#gm-log"); if (!log) return;
    if (!composerOnly) {
      log.innerHTML = msgs.length ? msgs.map(bubble).join("") : `<div class="gm-msg gm"><span class="gm-av sm" aria-hidden="true">GM</span><div class="gm-bub">
        <p>Hi ${esc(Auth.me()?.username || "there")}! I'm the General Manager. Tell me what you need: update or fix a page, correct an error,
        add a feature, build a program, research something. Each assignment becomes a mission the company plans, builds and checks; you'll
        see its progress here.</p><p class="gm-note">Changes to AXoR itself come back ready to review; putting them on the live site needs the Owner's approval.</p></div></div>`;
      if (busy) log.insertAdjacentHTML("beforeend", `<div class="gm-msg gm"><span class="gm-av sm" aria-hidden="true">GM</span><div class="gm-bub"><p class="gm-typing">Thinking<span>.</span><span>.</span><span>.</span></p></div></div>`);
      log.scrollTop = log.scrollHeight;
    } else if (busy && !$("#gm-log .gm-typing")) {
      log.innerHTML = msgs.map(bubble).join("") + `<div class="gm-msg gm"><span class="gm-av sm" aria-hidden="true">GM</span><div class="gm-bub"><p class="gm-typing">Thinking<span>.</span><span>.</span><span>.</span></p></div></div>`;
      log.scrollTop = log.scrollHeight;
    }
    $("#gm-files").innerHTML = files.map(f => `<span class="gm-chip">${f.url ? `<img src="${f.url}" alt="">` : icon("file")}${esc(f.name)}
      <button type="button" data-gm-unfile="${f.id}" aria-label="Remove ${esc(f.name)}">${icon("close")}</button></span>`).join("")
      + (uploading ? `<span class="gm-chip">${Loading.line("Uploading…")}</span>` : "");
    const s = $("#gm-chat .gm-send"); if (s) s.disabled = busy || uploading > 0;
  }

  function wire(p) {
    p.addEventListener("click", e => {
      const t = e.target.closest("[data-gm],[data-gm-open],[data-gm-mission],[data-gm-unfile]"); if (!t) return;
      e.preventDefault();
      if (t.dataset.gm === "close") { toggle(false); $("#gm-btn").focus(); }
      else if (t.dataset.gm === "clear") clear();
      else if (t.dataset.gm === "attach") $("#gm-file").click();
      else if (t.dataset.gmOpen) { MissionOS.show(Number(t.dataset.gmOpen)); if (innerWidth < 760) toggle(false); }
      else if (t.dataset.gmMission) asMission(Number(t.dataset.gmMission));
      else if (t.dataset.gmUnfile) unfile(Number(t.dataset.gmUnfile));
    });
    p.addEventListener("submit", e => {
      e.preventDefault();
      if (e.target.id === "gm-compose") send();
      else if (e.target.dataset.gmAnswer) answer(e.target);
    });
    p.addEventListener("keydown", e => {
      if (e.key === "Escape") { toggle(false); $("#gm-btn").focus(); }
      if (e.target.id === "gm-text" && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    p.addEventListener("change", e => { if (e.target.id === "gm-file") { addFiles(e.target.files); e.target.value = ""; } });
    p.addEventListener("paste", e => {
      const imgs = [...(e.clipboardData?.files || [])];
      if (imgs.length) { e.preventDefault(); addFiles(imgs); }
    });
    p.addEventListener("dragover", e => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); p.classList.add("drop"); } });
    p.addEventListener("dragleave", e => { if (!p.contains(e.relatedTarget)) p.classList.remove("drop"); });
    p.addEventListener("drop", e => { if (e.dataTransfer?.files?.length) { e.preventDefault(); p.classList.remove("drop"); addFiles(e.dataTransfer.files); } });
  }

  return { init, toggle, refresh };
})();
