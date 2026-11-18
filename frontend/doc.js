/* Doc: one toolbar for every long Markdown block the team produces (plans and requests waiting for approval, task
   outputs, check results, cycle reports). Formatted or Source view, Copy, Read (a wide reading view), Download as .md,
   Save to notes, and Edit where the owner of the block says what editing means (Doc.editText is the plain-text editor,
   with Beautify and a preview). Blocks are redrawn often by live updates, so each one is kept by key and keeps its view. */
const Doc = (() => {
  const docs = {};
  const btn = (act, ic, label, extra = "") => `<button type="button" class="iconbtn sm" data-doc-act="${act}" title="${label}" aria-label="${label}" ${extra}>${icon(ic)}</button>`;
  const body = d => d.raw ? `<pre class="doc-src">${esc(d.text)}</pre>` : `<div class="md">${Agents.md(d.text)}</div>`;

  // key: stable id for the block; edit: () => void, opens whatever editor fits (none = read-only)
  function block({ key, title, text, netuid = null, edit = null, cls = "" }) {
    const d = docs[key] = { title, text: text || "", netuid, edit, raw: docs[key]?.raw || false };
    return `<div class="doc ${cls}" data-doc="${esc(key)}"><div class="doc-bar">
        <div class="seg doc-seg"><button type="button" data-doc-act="fmt" aria-pressed="${!d.raw}">Formatted</button><button type="button" data-doc-act="raw" aria-pressed="${d.raw}">Source</button></div>
        <span class="spacer"></span>
        ${edit ? `<button type="button" class="btn sm" data-doc-act="edit">${icon("edit")}Edit</button>` : ""}
        ${btn("copy", "copy", "Copy")}${btn("read", "expand", "Read in a wide view")}${btn("download", "download", "Download as Markdown")}${btn("note", "note", "Save to notes")}</div>
      <div class="doc-body">${body(d)}</div></div>`;
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); }
    catch {  // plain http: no clipboard API
      const t = document.createElement("textarea"); t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.select(); const ok = document.execCommand("copy"); t.remove();
      if (!ok) return toast("Couldn't copy");
    }
    toast("Copied");
  }
  const slug = s => (s || "document").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "document";
  function download(d) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([`# ${d.title}\n\n${d.text}\n`], { type: "text/markdown" }));
    a.download = slug(d.title) + ".md"; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  async function note(d) {
    const text = `## ${d.title}\n\n${d.text}`;
    try {
      await api("/api/workspace/notes", { method: "POST", body: { text: text.slice(0, 4000), netuid: d.netuid, color: "blue" } });
      toast(text.length > 4000 ? "Saved to notes (cut to 4,000 characters)" : "Saved to notes");
      Notes.load().catch(() => {});
    } catch (e) { toast(e.message); }
  }
  // a wide reading view, in the page's own dialog
  function read(d) {
    const m = $("#modal");
    Auth.modal(`<div class="doc-read"><h3>${esc(d.title)}</h3><div class="md">${Agents.md(d.text)}</div></div>`, async () => m.close(), { submit: "Close" });
    $("[data-close]", m)?.remove();
    m.classList.add("doc-wide"); m.addEventListener("close", () => m.classList.remove("doc-wide"), { once: true });
  }
  // plain-text editor with Beautify (tidies lists, headings and spacing) and a preview; onSave(text) saves it
  function editText({ title, text, hint = "", onSave }) {
    const m = $("#modal");
    const f = Auth.modal(`<div class="doc-edit"><h3>${icon("edit")}${esc(title)}</h3>${hint ? `<p class="muted small">${hint}</p>` : ""}
        <div class="doc-bar"><div class="seg"><button type="button" data-ed="write" aria-pressed="true">Write</button><button type="button" data-ed="preview" aria-pressed="false">Preview</button></div>
          <span class="spacer"></span><button type="button" class="btn sm" data-ed="beautify">${icon("sparkle")}Beautify</button></div>
        <textarea name="text" rows="16" spellcheck="true">${esc(text || "")}</textarea><div class="md doc-preview" hidden></div></div>`,
      async f => { await onSave(f.elements.text.value); m.close(); }, { submit: "Save" });
    m.classList.add("doc-wide"); m.addEventListener("close", () => m.classList.remove("doc-wide"), { once: true });
    const ta = f.elements.text, pv = $(".doc-preview", f);
    f.addEventListener("click", e => {
      const k = e.target.closest("[data-ed]")?.dataset.ed; if (!k) return;
      if (k === "beautify") { const t = Notes.beautify(ta.value); if (t === ta.value) return toast("Already tidy"); ta.value = t; return toast("Beautified"); }
      const p = k === "preview";
      $$("[data-ed=write], [data-ed=preview]", f).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.ed === k)));
      if (p) pv.innerHTML = Agents.md(ta.value);
      ta.hidden = p; pv.hidden = !p;
    });
    ta.focus();
    return f;
  }
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-doc-act]"); if (!b) return;
    const el = b.closest("[data-doc]"), d = docs[el?.dataset.doc]; if (!d) return;
    const k = b.dataset.docAct;
    if (k === "fmt" || k === "raw") {
      d.raw = k === "raw";
      $$(`[data-doc="${CSS.escape(el.dataset.doc)}"]`).forEach(x => {
        $(".doc-body", x).innerHTML = body(d);
        $$(".doc-seg button", x).forEach(s => s.setAttribute("aria-pressed", String((s.dataset.docAct === "raw") === d.raw)));
      });
    }
    else if (k === "copy") copy(d.text);
    else if (k === "read") read(d);
    else if (k === "download") download(d);
    else if (k === "note") note(d);
    else if (k === "edit" && d.edit) d.edit(d);
  });
  return { block, editText, copy };
})();
