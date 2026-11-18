/* Drive: AXoR Drive (the separate file server) in the sidebar, working like Google Drive, Dropbox or OneDrive.
   My drive (private), the Shared drive, Shared with me (what others shared with you as viewer or editor), Recent,
   Starred, share links, the trash and storage. Items show in a list or a grid with thumbnails, sorted by name, date or
   size. Select several (checkboxes, Ctrl/⌘- and Shift-click, Ctrl+A, arrow keys) to download them as a zip, move,
   copy, star or delete them; drag them onto a folder to move them; right-click for actions. Uploads (files or whole
   folders, by button or drag-and-drop) run three at a time in a tray with progress. Files open full screen (images,
   PDFs, video, audio, text, Markdown and Office text) with ← → between them; text files can be edited in place, each
   save a version. The details panel shows who has access, links, versions and activity. Every request goes through
   AXoR (/api/drive). */
const Drive = (() => {
  let st = { enabled: false }, space = "shared", view = "folder", folder = null, data = null, err = null, seq = 0, wired = false;
  let sel = new Set(), anchor = null, reveal = null, q = "", qTimer = null, trashSpace = "shared", allLinks = false;
  let detail = null, detailFor = null, tab = "info", acts = null, dragging = null, viewer = null;
  let layout = pref("drive.layout", "list"), sort = pref("drive.sort", { by: "name", dir: 1 }), info = pref("drive.info", false);
  const ups = [], dirs = new Map(), PARALLEL = 3, EDIT_MAX = 2 * 1048576;
  let upSeq = 0, running = 0, trayOpen = true, reloadTimer = null, foldTimer = null;

  const NAV = [["mine", "My drive", "lock"], ["shared", "Shared drive", "users"], ["with", "Shared with me", "inbox"], ["recent", "Recent", "clock"],
    ["starred", "Starred", "star"], ["links", "Share links", "link"], ["trash", "Trash", "trash"]];
  const SPACES = ["mine", "shared", "with"], SPACE_ICON = { mine: "lock", shared: "users", with: "inbox" };
  const TITLES = { recent: "Recent", starred: "Starred", trash: "Trash", links: "Share links", storage: "Storage" };
  const SORTS = { name: "Name", updated: "Modified", size: "Size" };
  const PREVIEW = { "image/png": "image", "image/jpeg": "image", "image/gif": "image", "image/webp": "image", "image/avif": "image", "application/pdf": "pdf",
    "video/mp4": "video", "video/webm": "video", "audio/mpeg": "audio", "audio/ogg": "audio", "audio/wav": "audio", "audio/webm": "audio", "audio/mp4": "audio" };
  const THUMBS = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp", "image/tiff"]);
  const TEXT = /\.(txt|md|markdown|csv|tsv|json|jsonl|ya?ml|toml|ini|cfg|conf|log|py|js|ts|tsx|jsx|rs|go|java|c|h|cpp|hpp|cs|rb|php|sh|bash|sql|html?|css|xml|svg|env|dockerfile|r|ipynb|tex|rst|proto|sol)$/i;
  const OFFICE = /\.(docx|pptx|xlsx|odt|ods|odp)$/i, MD = /\.(md|markdown)$/i;
  const isText = n => n.kind === "file" && ((n.mime || "").startsWith("text/") || TEXT.test(n.name) || ["application/json", "application/xml"].includes(n.mime));
  const kindOf = n => n.kind === "folder" ? "folder" : PREVIEW[n.mime] || (OFFICE.test(n.name) ? "doc" : isText(n) ? "text" : "file");
  const ICON = { folder: "folder", image: "image", pdf: "file", video: "film", audio: "speaker", doc: "doc", text: "note", file: "file" };
  const canEdit = n => isText(n) && n.can_write && n.size <= EDIT_MAX && !n.trashed;
  const canShare = n => !n.trashed && (n.role === "owner" || (st.links && n.role !== "viewer"));
  const bytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : n < 1073741824 ? `${fmtNum(n / 1048576, 1)} MB` : `${fmtNum(n / 1073741824, 2)} GB`;
  const when = ts => !ts ? "" : Date.now() / 1000 - ts < 86400 ? ago(ts) : new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  const expires = ts => { if (!ts) return "never expires"; const d = Math.ceil((ts - Date.now() / 1000) / 86400); return d <= 1 ? "expires within a day" : `expires in ${d} days`; };
  const content = (id, o = {}) => `/api/drive/nodes/${id}/content${o.version || o.download ? "?" + new URLSearchParams({ ...(o.version ? { version: o.version } : {}), ...(o.download ? { download: "true" } : {}) }) : ""}`;
  const spaceLabel = s => ({ mine: "My drive", shared: "Shared drive", with: "Shared with me" })[s] || "Drive";
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const label = ns => ns.length === 1 ? `“${ns[0].name}”` : plural(ns.length, "item");
  function pref(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }
  function keep(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }

  const setupHelp = () => `<details class="sl-help" open><summary>How to start the drive</summary><ol>
      <li><b>docker compose:</b> <code>docker compose up -d --build</code> starts AXoR and the drive together; nothing else to set.</li>
      <li><b>docker run:</b> build and start the drive on a network AXoR joins, sharing its secret volume:<br>
        <code>docker build -t scout-drive drive</code><br><code>docker network create scout-net</code><br>
        <code>docker run -d --name scout-drive --network scout-net --restart unless-stopped -v scout-drive-data:/data -v scout-drive-secret:/secret scout-drive</code><br>
        then start AXoR with <code>--network scout-net -v scout-drive-secret:/drive-secret:ro -e DRIVE_URL=http://scout-drive:8100 -e DRIVE_SECRET_FILE=/drive-secret/drive.key</code>.</li>
      <li>Reload this page. Files from the old workspace file hub move into the drive automatically.</li></ol></details>`;

  // ---------- loading ----------
  async function init() {
    $("#nav-drive").hidden = true;
    if (!Auth.me()) return;
    try { st = await api("/api/drive/status"); } catch { return; }
    $("#nav-drive").hidden = !st.enabled && !st.is_admin;  // admins see it even before it's set up, to find the setup steps
  }
  async function open() {
    wire();
    try { st = await api("/api/drive/status"); } catch (e) { st = { enabled: true, error: e.message }; }
    render();
    if (st.enabled && !st.error) load();
  }
  async function load() {
    const my = ++seq;
    data = null; err = null; renderList();
    try {
      const r = view === "folder" ? await api(`/api/drive/list?${new URLSearchParams({ space, ...(folder ? { folder } : {}) })}`)
        : view === "recent" ? { items: await api("/api/drive/recent") }
        : view === "starred" ? { items: await api("/api/drive/starred") }
        : view === "search" ? { items: await api(`/api/drive/search?q=${encodeURIComponent(q)}`) }
        : view === "trash" ? { items: await api(`/api/drive/trash?space=${trashSpace}`) }
        : view === "storage" ? { storage: await api("/api/drive/storage") }
        : { links: await api(`/api/drive/shares${allLinks ? "?all=true" : ""}`) };
      if (my !== seq) return;
      data = r;
    } catch (e) {
      if (my !== seq) return;
      err = e.message;
      if (view === "folder" && folder && e.status === 404) { folder = null; return load(); }  // the folder went away
    }
    const ids = new Set(items().map(n => n.id));
    sel = new Set([...sel].filter(id => ids.has(id)));  // a reload keeps what's still there selected
    if (reveal && ids.has(reveal)) { sel = new Set([reveal]); anchor = reveal; }
    renderList(); renderCrumbs(); renderSub(); renderDetail();
    if (reveal) { const r = $(`#drv-list [data-node="${reveal}"]`); r?.scrollIntoView({ block: "center" }); r?.focus({ preventScroll: true }); reveal = null; }
  }
  const reloadSoon = () => { clearTimeout(reloadTimer); reloadTimer = setTimeout(() => { if (S.view === "drive") load(); usage(); }, 400); };
  async function usage() { try { st = await api("/api/drive/status"); renderNav(); } catch {} }
  function go(v, opts = {}) {
    view = v; sel = new Set(); anchor = null;
    if (opts.space) space = opts.space;
    if ("folder" in opts) folder = opts.folder;
    if (v !== "search") { q = ""; const i = $("#drv-q"); if (i) i.value = ""; }
    renderNav(); renderBar(); load();
  }
  const items = () => data?.items || data?.storage?.largest || [];
  const node = id => items().find(n => n.id === id) || (detail?.id === id ? detail : null) || (viewer?.n.id === id ? viewer.n : null);
  const picked = () => shown().filter(n => sel.has(n.id));
  const canSort = () => view === "starred" || (view === "folder" && !(space === "with" && !folder));
  const writable = () => view === "folder" && (data?.folder ? data.folder.can_write : space !== "with");
  function shown() {
    const xs = [...items()];
    if (!canSort()) return xs;
    const name = (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
    const cmp = sort.by === "name" ? name : sort.by === "size" ? (a, b) => a.size - b.size || name(a, b) : (a, b) => (a.updated || 0) - (b.updated || 0);
    return xs.sort((a, b) => (b.kind === "folder") - (a.kind === "folder") || cmp(a, b) * sort.dir);
  }

  // ---------- rendering ----------
  function render() {
    const box = $("#drive");
    if (!st.enabled || st.error) {
      box.innerHTML = `<div class="card chat-empty sl-setup"><span class="av c-violet xl" aria-hidden="true">${icon("folder")}</span><h3>Drive isn't available</h3>
        <p class="muted">${esc(st.error || "File storage isn't set up on this server.")}</p>${st.is_admin ? setupHelp() : ""}</div>`;
      return;
    }
    box.innerHTML = `<div class="drv ${info ? "with-detail" : ""}">
      <aside class="card drv-nav" id="drv-nav"></aside>
      <section class="card drv-main" id="drv-main"><div class="drv-bar" id="drv-bar"></div><div class="drv-sub" id="drv-sub" hidden></div>
        <div class="drv-list" id="drv-list" tabindex="-1"></div></section>
      <aside class="card drv-detail" id="drv-detail" ${info ? "" : "hidden"}></aside>
      <input type="file" id="drv-file" multiple class="sr" tabindex="-1" aria-hidden="true"><input type="file" id="drv-dir" webkitdirectory class="sr" tabindex="-1" aria-hidden="true">
      <input type="file" id="drv-ver" class="sr" tabindex="-1" aria-hidden="true"></div>`;
    renderNav(); renderBar(); renderList(); renderDetail();
  }
  function renderNav() {
    const box = $("#drv-nav"); if (!box) return;
    const cur = view === "folder" ? space : view === "search" ? "" : view, used = st.quota ? st.used / st.quota : 0;
    box.innerHTML = `<button type="button" class="btn primary drv-new" data-dv="new" aria-haspopup="menu">${icon("plus")}New</button>
      <nav class="drv-navlist" aria-label="Drive">${NAV.map(([k, l, ic]) => `<button type="button" data-nav="${k}" aria-current="${cur === k}" ${["mine", "shared"].includes(k) ? `data-drop="${k}:"` : ""}>${icon(ic)}<span>${l}</span></button>`).join("")}</nav>
      <button type="button" class="drv-usage" data-nav="storage" aria-current="${cur === "storage"}" title="${pct(used, 1)} of your drive space used. See what takes it.">
        <span class="drv-usage-t">${icon("piechart")}Storage</span><span class="ws-bar ${used > 0.9 ? "full" : ""}"><i style="width:${Math.min(100, used * 100).toFixed(1)}%"></i></span>
        <small class="faint">${bytes(st.used || 0)} of ${bytes(st.quota || 0)} used</small></button>`;
  }
  function renderBar() {
    const box = $("#drv-bar"); if (!box) return;
    const listy = !["links", "storage"].includes(view);
    box.innerHTML = `<div id="drv-crumbs" class="drv-crumbs-box"></div>
      <div class="search drv-search"><span>${icon("search")}</span><input id="drv-q" type="search" placeholder="Search in Drive" value="${esc(q)}" autocomplete="off" aria-label="Search names and contents (/)"></div>
      <div class="drv-tools">${listy ? `<div class="seg" role="group" aria-label="Layout"><button type="button" data-layout="list" aria-pressed="${layout === "list"}" title="List" aria-label="List">${icon("list")}</button><button type="button" data-layout="grid" aria-pressed="${layout === "grid"}" title="Grid" aria-label="Grid">${icon("grid")}</button></div>` : ""}
        ${canSort() ? `<button type="button" class="btn sm" data-dv="sort" aria-haspopup="menu" title="Sort">${icon(sort.dir > 0 ? "up" : "down")}${SORTS[sort.by]}</button>` : ""}
        <button type="button" class="iconbtn" data-dv="info" aria-pressed="${info}" title="Details" aria-label="Details">${icon("info")}</button></div>`;
    renderCrumbs(); renderSub();
  }
  function renderCrumbs() {
    const box = $("#drv-crumbs"); if (!box) return;
    if (view !== "folder") { box.innerHTML = `<nav class="drv-crumbs"><b>${view === "search" ? `Results for “${esc(q)}”` : TITLES[view]}</b></nav>`; return; }
    const path = data?.path || [], drop = id => space === "with" && !id ? "" : `data-drop="${space}:${esc(id)}"`;
    box.innerHTML = `<nav class="drv-crumbs" aria-label="Folder path"><button type="button" data-crumb="" ${drop("")}>${icon(SPACE_ICON[space])}${spaceLabel(space)}</button>${path.map(p => `${icon("right")}<button type="button" data-crumb="${esc(p.id)}" ${drop(p.id)}>${esc(p.name)}</button>`).join("")}</nav>`;
  }
  function renderSub() {
    const box = $("#drv-sub"); if (!box) return;
    const list = picked();
    let html = "";
    if (list.length) {
      html = `<div class="drv-selbar"><button type="button" class="iconbtn sm" data-dv="clear" aria-label="Clear selection" title="Clear selection (Esc)">${icon("close")}</button><b>${list.length} selected</b>
        <span class="drv-selacts">${bulkActions(list).map(([a, ic, l, cls]) => `<button type="button" class="btn sm ${cls || ""}" data-bulk="${a}" title="${l}" aria-label="${l}">${icon(ic)}${l}</button>`).join("")}</span></div>`;
    } else if (view === "folder") {
      html = writable() ? `<button type="button" class="btn sm" data-dv="folder">${icon("folderplus")}New folder</button><button type="button" class="btn sm" data-dv="upload">${icon("upload")}Upload files</button>
          <button type="button" class="btn sm" data-dv="updir">${icon("folderup")}Upload folder</button><button type="button" class="btn sm" data-dv="doc">${icon("doc")}New text file</button>`
        : !folder ? `<p class="faint small drv-note">${icon("info")}Files and folders other people shared with you. Ask the owner for edit access to add to a folder.</p>`
        : `<p class="faint small drv-note">${icon("eye")}You can view this folder, but not add to it.</p>`;
    } else if (view === "trash") {
      html = `<div class="seg">${["shared", "mine"].map(s => `<button type="button" data-tspace="${s}" aria-pressed="${trashSpace === s}">${spaceLabel(s)}</button>`).join("")}</div>
        ${data?.items?.some(i => i.can_modify) ? `<button type="button" class="btn sm danger-text" data-dv="empty">${icon("trash")}Empty trash</button>` : ""}
        <p class="faint small drv-note">${icon("info")}Items in the trash are deleted for good after ${st.trash_days} days.</p>`;
    } else if (view === "links" && st.is_admin) {
      html = `<label class="chk"><input type="checkbox" id="drv-all" ${allLinks ? "checked" : ""}> Everyone's links</label>
        <label class="chk" title="When off, only admins can create share links"><input type="checkbox" id="drv-members" ${st.links_for_members ? "checked" : ""}> Members can share</label>`;
    }
    box.innerHTML = html; box.hidden = !html;
  }
  function bulkActions(list) {
    const all = k => list.every(n => n[k]);
    if (view === "trash") return [all("can_modify") && ["restore", "reset", "Restore"], all("can_modify") && ["purge", "trash", "Delete forever", "danger-text"]].filter(Boolean);
    return [list.length === 1 && canShare(list[0]) && ["share", "userplus", "Share"], ["download", "download", "Download"],
      all("can_modify") && ["move", "right", "Move"], ["copy", "copy", "Make a copy"], all("starred") ? ["unstar", "star", "Unstar"] : ["star", "star", "Star"],
      view === "folder" && space === "with" && !folder && ["leave", "close", "Remove"], all("can_modify") && ["trash", "trash", "Delete", "danger-text"]].filter(Boolean);
  }

  function badges(n) {
    return `${n.netuid != null ? `<span class="ws-tag">SN${n.netuid}</span>` : ""}${n.shared ? `<span title="Shared with ${plural(n.shared, "person")}">${icon("users")}${n.shared}</span>` : ""}
      ${n.links ? `<span title="Has an active share link">${icon("link")}</span>` : ""}${n.versions > 1 ? `<span title="${n.versions} versions">${icon("clock")}${n.versions}</span>` : ""}`;
  }
  const owner = n => view === "trash" ? `by ${esc(n.trashed_by || "")}` : n.shared_by ? esc(n.shared_by) : n.mine ? "You" : esc(n.owner || "");
  const stampOf = n => view === "trash" ? n.trashed : n.shared_at || n.updated;
  const trail = n => esc([spaceLabel(n.space), ...(n.path ? n.path.split("/") : [])].join(" › "));  // names can't hold "/"
  const where = n => view !== "folder" && n.path !== undefined ? `<small class="faint">${trail(n)}</small>` : "";
  const snip = n => n.snippet ? `<small class="drv-snip">${esc(n.snippet).replace(/\x02/g, "<mark>").replace(/\x03/g, "</mark>")}</small>` : "";
  const nameBtn = n => `<button type="button" class="drv-go" data-go tabindex="-1">${esc(n.name)}</button>${n.starred ? `<span class="drv-star" title="Starred">${icon("star")}</span>` : ""}`;
  const attrs = n => `data-node="${esc(n.id)}" role="row" tabindex="0" aria-selected="${sel.has(n.id)}" draggable="${n.can_modify && view !== "trash"}"`;
  const check = n => `<input type="checkbox" data-check ${sel.has(n.id) ? "checked" : ""} aria-label="Select ${esc(n.name)}" tabindex="-1">`;
  function row(n) {
    const k = kindOf(n);
    return `<div class="drv-row ${sel.has(n.id) ? "on" : ""}" ${attrs(n)}><span class="drv-chk">${check(n)}</span>
      <span class="drv-ico k-${k}">${icon(ICON[k])}</span>
      <span class="drv-name"><span class="drv-nm">${nameBtn(n)}</span>${where(n)}${snip(n)}</span>
      <span class="drv-badges">${badges(n)}</span><span class="drv-owner faint">${owner(n)}</span>
      <span class="drv-when faint" title="${esc(stamp(stampOf(n)))}">${when(stampOf(n))}</span>
      <span class="drv-size faint">${n.kind === "folder" ? "–" : bytes(n.size)}</span>
      <button type="button" class="iconbtn sm" data-menu aria-label="Actions for ${esc(n.name)}" tabindex="-1">${icon("dots")}</button></div>`;
  }
  function table(xs, sortable = canSort()) {
    const all = xs.length > 0 && xs.every(n => sel.has(n.id));
    const col = (by, l, cls) => sortable ? `<button type="button" class="drv-sort ${cls}" data-sortby="${by}" aria-label="Sort by ${l.toLowerCase()}">${l}${sort.by === by ? icon(sort.dir > 0 ? "up" : "down") : ""}</button>` : `<span class="${cls}">${l}</span>`;
    return `<div class="drv-row drv-head" role="row"><span class="drv-chk"><input type="checkbox" data-checkall ${all ? "checked" : ""} aria-label="Select all"></span><span></span>
      ${col("name", "Name", "drv-hname")}<span class="drv-badges"></span><span class="drv-owner">${view === "folder" && space === "with" && !folder ? "Shared by" : "Owner"}</span>
      ${col("updated", view === "trash" ? "Deleted" : view === "folder" && space === "with" && !folder ? "Shared" : "Modified", "drv-when")}${col("size", "Size", "drv-size")}<span></span></div>
      <div role="rowgroup">${xs.map(row).join("")}</div>`;
  }
  function tile(n) {
    const k = kindOf(n);
    if (n.kind === "folder") return `<div class="drv-tile drv-ftile ${sel.has(n.id) ? "on" : ""}" ${attrs(n)}>${check(n)}<span class="drv-ico k-folder">${icon("folder")}</span>
      <span class="drv-tname">${nameBtn(n)}</span><button type="button" class="iconbtn sm" data-menu aria-label="Actions for ${esc(n.name)}" tabindex="-1">${icon("dots")}</button></div>`;
    const pic = st.thumbnails && THUMBS.has(n.mime) ? `<img class="drv-thumb" src="/api/drive/nodes/${esc(n.id)}/thumb?v=${esc(n.version || "")}" alt="" loading="lazy" decoding="async">`
      : `<span class="drv-tico k-${k}">${icon(ICON[k])}</span>`;
    return `<div class="drv-tile ${sel.has(n.id) ? "on" : ""}" ${attrs(n)}><div class="drv-pic k-${k}">${pic}${check(n)}</div>
      <div class="drv-tfoot"><span class="drv-ico sm k-${k}">${icon(ICON[k])}</span><span class="drv-tname"><span class="drv-nm">${nameBtn(n)}</span>
        <small class="faint">${view === "folder" ? `${owner(n)} · ${when(stampOf(n))}` : trail(n)}</small></span>
      <button type="button" class="iconbtn sm" data-menu aria-label="Actions for ${esc(n.name)}" tabindex="-1">${icon("dots")}</button></div></div>`;
  }
  function grid(xs) {
    const fs = xs.filter(n => n.kind === "folder"), files = xs.filter(n => n.kind !== "folder");
    return `<div class="drv-grid" role="grid">${fs.length ? `<h5 class="drv-gh">Folders</h5><div class="drv-folders" role="rowgroup">${fs.map(tile).join("")}</div>` : ""}
      ${files.length ? `<h5 class="drv-gh">Files</h5><div class="drv-tiles" role="rowgroup">${files.map(tile).join("")}</div>` : ""}</div>`;
  }
  function renderList() {
    const box = $("#drv-list"); if (!box) return;
    box.classList.toggle("is-grid", layout === "grid");
    if (err) { box.innerHTML = `<div class="sl-err">${icon("alert")}${esc(err)}</div>`; return; }
    if (!data) { box.innerHTML = Loading.line("Loading…"); return; }
    if (view === "links") {
      box.innerHTML = data.links.length ? `<div class="drv-links">${data.links.map(l => `<div class="drv-link">
          <span class="drv-ico k-${l.kind === "folder" ? "folder" : "file"}">${icon(l.kind === "folder" ? "folder" : "link")}</span><span class="drv-name"><b>${esc(l.name)}</b><small class="faint">${l.mine ? "You" : esc(l.by)} · ${when(l.created)} · ${expires(l.expires)}${l.password ? " · password" : ""} · ${plural(l.downloads, "download")}${l.trashed ? " · in the trash" : ""}</small></span>
          <button type="button" class="btn sm" data-copy="${esc(l.token)}">${icon("copy")}Copy</button><button type="button" class="btn sm danger-text" data-revoke="${esc(l.token)}">Revoke</button></div>`).join("")}</div>`
        : `<div class="empty">No active share links${allLinks ? "" : " of yours"}. Share a file or folder to make one.</div>`;
      return;
    }
    if (view === "storage") { box.innerHTML = storageView(data.storage); return; }
    const xs = shown();
    if (!xs.length) {
      const e = view === "folder" && writable() ? `<label class="drv-empty" for="drv-file">${icon("upload")}<b>Drop files or folders here</b><small class="faint">or click to upload. New folder and New text file are above.</small></label>`
        : `<div class="drv-empty is-quiet">${icon({ folder: space === "with" ? "inbox" : "folder", recent: "clock", starred: "star", search: "search", trash: "trash" }[view])}<b>${{
          folder: space === "with" && !folder ? "Nothing is shared with you yet" : "This folder is empty", recent: "No files yet", starred: "Nothing starred yet",
          search: "Nothing matches", trash: "The trash is empty" }[view]}</b><small class="faint">${{
          folder: space === "with" && !folder ? "When someone shares a file or folder from their My drive with you, it shows here." : "",
          recent: "Files you and others add or change show here.", starred: "Star files and folders you use often to find them here.",
          search: "Search looks in names and in the text of documents, code, PDFs and Office files.", trash: "" }[view]}</small></div>`;
      box.innerHTML = e; return;
    }
    box.innerHTML = layout === "grid" ? grid(xs) : table(xs);
  }
  function storageView(s) {
    const used = s.quota ? s.used / s.quota : 0, IC = { Images: "image", Videos: "film", Audio: "speaker", Documents: "doc", Archives: "layers", Other: "file" };
    const K = { Images: "image", Videos: "video", Audio: "audio", Documents: "doc", Archives: "file", Other: "file" };
    return `<div class="drv-storage"><div class="drv-meter"><p><b>${bytes(s.used)}</b> <span class="faint">of ${bytes(s.quota)} used · ${pct(used, 1)}</span></p>
        <div class="ws-bar ${used > 0.9 ? "full" : ""}"><i style="width:${Math.min(100, used * 100).toFixed(1)}%"></i></div></div>
      <ul class="drv-kinds">${s.kinds.map(k => `<li><span class="drv-ico sm k-${K[k.kind]}">${icon(IC[k.kind])}</span><span>${k.kind}</span><span class="ws-bar"><i style="width:${s.used ? (k.size / s.used * 100).toFixed(1) : 0}%"></i></span><b>${bytes(k.size)}</b></li>`).join("")}
        <li><span class="drv-ico sm">${icon("clock")}</span><span>Older versions</span><span class="faint small">kept for each file, ${st.versions} at most</span><b>${bytes(s.old_versions)}</b></li>
        <li><span class="drv-ico sm">${icon("trash")}</span><span>In the trash</span><span>${s.trash ? `<button type="button" class="btn sm" data-nav="trash">Open trash</button>` : ""}</span><b>${bytes(s.trash)}</b></li></ul>
      <p class="faint small">Your space counts every version of each file you uploaded, edited or copied, trash included, until it's emptied. Up to ${bytes(st.max_file || 0)} per file.</p>
      <h4 class="drv-h4">Your largest files</h4>${s.largest.length ? table(s.largest, false) : `<div class="empty">You haven't added any files yet.</div>`}</div>`;
  }
  // selection changes repaint in place, keeping scroll and focus
  function paintSel() {
    $$("#drv-list [data-node]").forEach(r => { const on = sel.has(r.dataset.node); r.classList.toggle("on", on); r.setAttribute("aria-selected", on); const c = $("[data-check]", r); if (c) c.checked = on; });
    const all = $("#drv-list [data-checkall]");
    if (all) { const xs = shown(); all.checked = xs.length > 0 && xs.every(n => sel.has(n.id)); all.indeterminate = sel.size > 0 && !all.checked; }
    renderSub(); renderDetail();
  }
  function selectOnly(id) { sel = new Set(id ? [id] : []); anchor = id; paintSel(); }
  function toggle(id) { sel.has(id) ? sel.delete(id) : sel.add(id); anchor = id; paintSel(); }
  function range(to, add) {
    const ids = shown().map(n => n.id), a = ids.indexOf(anchor), b = ids.indexOf(to);
    if (a < 0 || b < 0) return selectOnly(to);
    if (!add) sel = new Set();
    ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(i => sel.add(i)); paintSel();
  }
  function clearSel() { if (sel.size) { sel = new Set(); paintSel(); } }

  // ---------- details panel ----------
  function renderDetail() {
    const box = $("#drv-detail"); if (!box) return;
    $(".drv")?.classList.toggle("with-detail", info);
    box.hidden = !info; if (!info) return;
    const list = picked(), id = list.length === 1 ? list[0].id : !list.length && view === "folder" && folder ? folder : null;
    const head = (ic, title, sub = "") => `<div class="sl-head drv-dhead">${ic}<div><b>${title}</b>${sub ? `<small class="faint">${sub}</small>` : ""}</div><span class="spacer"></span>
      <button type="button" class="iconbtn sm" data-dv="info" aria-label="Close details">${icon("close")}</button></div>`;
    if (list.length > 1) {
      const size = list.reduce((s, n) => s + (n.kind === "file" ? n.size : 0), 0), fs = list.filter(n => n.kind === "folder").length;
      box.innerHTML = head(`<span class="drv-ico">${icon("copy")}</span>`, `${list.length} items selected`) + `<div class="drv-dbody"><dl class="drv-info">
        <dt>Files</dt><dd>${list.length - fs}${list.length - fs ? ` · ${bytes(size)}` : ""}</dd><dt>Folders</dt><dd>${fs}</dd></dl>
        <p class="faint small">Use the bar above the list to download them as one zip, move, copy, star or delete them.</p></div>`;
      return;
    }
    if (!id) {
      detailFor = null;
      box.innerHTML = head(`<span class="drv-ico">${icon("info")}</span>`, view === "folder" ? spaceLabel(space) : TITLES[view] || "Details") +
        `<div class="drv-dbody drv-dempty">${icon("folder")}<p class="faint">Select a file or folder to see its details, who has access, its versions and activity.</p></div>`;
      return;
    }
    if (detailFor !== id) { detailFor = id; detail = null; acts = null; fetchDetail(id); }
    if (!detail || detail.error) { box.innerHTML = head("", "Details") + (detail?.error ? `<div class="sl-err">${icon("alert")}${esc(detail.error)}</div>` : Loading.line("Loading…")); return; }
    const d = detail, k = kindOf(d);
    box.innerHTML = head(`<span class="drv-ico k-${k}">${icon(ICON[k])}</span>`, esc(d.name), esc([spaceLabel(d.space), ...d.path.map(p => p.name)].join(" › "))) +
      `<div class="seg full drv-tabs" role="tablist">${[["info", "Details"], ["activity", "Activity"]].map(([t, l]) => `<button type="button" role="tab" data-tab="${t}" aria-pressed="${tab === t}" aria-selected="${tab === t}">${l}</button>`).join("")}</div>
      <div class="drv-dbody">${tab === "info" ? infoTab(d) : activityTab(d)}</div>`;
  }
  async function fetchDetail(id) {
    try { const d = await api(`/api/drive/nodes/${id}`); if (detailFor === id) { detail = d; renderDetail(); } }
    catch (e) { if (detailFor === id) { detail = { error: e.message }; renderDetail(); } }
  }
  function refreshDetail() { if (detailFor) { detailFor = null; renderDetail(); } }
  function infoTab(d) {
    const file = d.kind === "file", trashed = !!d.trashed, k = kindOf(d);
    const pv = file && !trashed && st.thumbnails && THUMBS.has(d.mime) ? `<img src="/api/drive/nodes/${esc(d.id)}/thumb?v=${esc(d.version || "")}" alt="">`
      : `<span class="drv-tico k-${k}">${icon(ICON[k])}</span>`;
    const people = d.space === "shared" ? `<p class="small">${icon("users")}Everyone signed in to AXoR can open the Shared drive.</p>`
      : `<ul class="drv-people">${d.space === "mine" ? `<li><span class="drv-av">${esc(((Auth.me()?.username) || "Y")[0].toUpperCase())}</span><span><b>You</b></span><span class="faint small">Owner</span></li>`
          : `<li><span class="drv-av">${esc((d.shared_by || "?")[0].toUpperCase())}</span><span><b>${esc(d.shared_by || "Its owner")}</b></span><span class="faint small">Owner</span></li>`}
        ${d.people.map(p => `<li><span class="drv-av">${esc(p.name[0].toUpperCase())}</span><span><b>${p.me ? "You" : esc(p.name)}</b>${p.via ? `<small class="faint">through ${esc(p.via)}</small>` : ""}</span><span class="faint small">${p.role === "editor" ? "Editor" : "Viewer"}</span></li>`).join("")}</ul>`;
    return `<div class="drv-dpv" ${file && !trashed ? `data-preview="${esc(d.id)}" role="button" tabindex="0" aria-label="Open ${esc(d.name)}"` : ""}>${pv}</div>
      <div class="row">${!trashed ? `<button type="button" class="btn sm" data-act="open">${icon(file ? "eye" : "folder")}Open</button>
          <a class="btn sm" href="${file ? content(d.id, { download: true }) : `/api/drive/zip?ids=${esc(d.id)}`}">${icon("download")}Download</a>
          ${canShare(d) ? `<button type="button" class="btn sm" data-act="share">${icon("userplus")}Share</button>` : ""}` : ""}
        ${trashed && d.can_modify ? `<button type="button" class="btn sm" data-act="restore">${icon("reset")}Restore</button><button type="button" class="btn sm danger-text" data-act="purge">Delete forever</button>` : ""}</div>
      <h4>${icon("users")}Who has access</h4>${people}
      ${d.shares.length ? `<h4>${icon("link")}Share links</h4><ul class="drv-shares">${d.shares.map(s => `<li><span><b>${(e => e[0].toUpperCase() + e.slice(1))(expires(s.expires))}</b><small class="faint">${s.mine ? "You" : esc(s.by)} · ${plural(s.downloads, "download")}${s.password ? " · password" : ""}</small></span>
          <button type="button" class="iconbtn sm" data-copy="${esc(s.token)}" title="Copy link" aria-label="Copy link">${icon("copy")}</button><button type="button" class="iconbtn sm" data-revoke="${esc(s.token)}" title="Revoke" aria-label="Revoke link">${icon("close")}</button></li>`).join("")}</ul>` : ""}
      <h4>${icon("info")}Details</h4><dl class="drv-info"><dt>Type</dt><dd>${file ? esc(d.mime || "File") : "Folder"}</dd>
        <dt>Size</dt><dd>${file ? bytes(d.size) : `${bytes(d.size || 0)} · ${plural(d.files || 0, "file")}${d.contains > (d.files || 0) ? `, ${plural(d.contains - d.files, "folder")}` : ""}`}</dd>
        <dt>Location</dt><dd>${esc([spaceLabel(d.space), ...d.path.map(p => p.name)].join(" › "))}</dd>
        <dt>${file ? "Added by" : "Created by"}</dt><dd>${d.mine ? "You" : esc(d.owner || "")}</dd>
        <dt>Modified</dt><dd>${esc(stamp(d.updated))}</dd><dt>Created</dt><dd>${esc(stamp(d.created))}</dd>${d.netuid != null ? `<dt>Subnet</dt><dd>SN${d.netuid}</dd>` : ""}
        <dt>Your access</dt><dd>${{ owner: "Owner", member: d.can_modify ? "Shared drive, can change it" : "Shared drive, can view and add versions", editor: "Editor", viewer: "Viewer" }[d.role] || ""}</dd></dl>
      ${file ? `<h4>${icon("clock")}Versions</h4><ol class="drv-versions">${d.versions_list.map(v => `<li><span><b>${esc(stamp(v.created))}</b><small class="faint">${esc(v.by_name || "")} · ${bytes(v.size)}</small></span>
          ${v.current ? `<span class="badge clear">Current</span>` : `<a class="iconbtn sm" href="${content(d.id, { version: v.id, download: true })}" title="Download this version" aria-label="Download this version">${icon("download")}</a>${(d.can_modify || d.role === "editor") && !trashed ? `<button type="button" class="btn sm" data-vrestore="${esc(v.id)}">Restore</button>` : ""}`}</li>`).join("")}</ol>
        ${d.can_write && !trashed ? `<button type="button" class="btn sm" data-act="version">${icon("upload")}Upload new version</button>` : ""}
        <p class="faint small">Editing the file or uploading one with the same name adds a version. The last ${st.versions} are kept.</p>` : ""}`;
  }
  const PHRASE = {
    created: a => `created ${a.b}`, uploaded: a => `uploaded ${a.b}`, new_version: a => `uploaded a new version of ${a.b}`, edited: a => `edited ${a.b}`,
    renamed: a => `renamed ${esc(a.detail.split(" → ")[0])} to ${a.b}`, moved: a => `moved ${a.b} to ${esc(a.detail)}`, trashed: a => `moved ${a.b} to the trash`,
    restored: a => `restored ${a.b} from the trash`, version_restored: a => `restored a version of ${a.b} from ${esc(a.detail)}`, copied: a => `made ${a.b}, a copy of ${esc(a.detail)}`,
    shared: a => `shared ${a.b}: ${esc(a.detail)}`, unshared: a => a.detail === "left" ? `left ${a.b}` : `stopped sharing ${a.b} with ${esc(a.detail)}`,
    link_created: a => `made a share link for ${a.b} (${esc(a.detail)})`, link_revoked: a => `revoked a share link for ${a.b}`,
  };
  function activityTab(d) {
    if (!acts || acts.id !== d.id) {
      acts = { id: d.id, items: null };
      api(`/api/drive/nodes/${d.id}/activity`).then(r => { if (acts?.id === d.id) { acts.items = r; renderDetail(); } })
        .catch(e => { if (acts?.id === d.id) { acts.items = []; acts.error = e.message; renderDetail(); } });
    }
    if (!acts.items) return Loading.line("Loading activity…");
    if (acts.error) return `<div class="sl-err">${icon("alert")}${esc(acts.error)}</div>`;
    if (!acts.items.length) return `<p class="faint small">No activity recorded yet.</p>`;
    return `<ol class="drv-acts">${acts.items.map(a => `<li><span class="drv-av">${esc((a.mine ? "Y" : (a.user_name || "?")[0]).toUpperCase())}</span><div>
      <p><b>${a.mine ? "You" : esc(a.user_name || "")}</b> ${(PHRASE[a.action] || (x => `${esc(x.action)} ${x.b}`))({ ...a, detail: a.detail || "", b: `<b>${esc(a.name || "an item now deleted")}</b>` })}</p>
      <small class="faint" title="${esc(stamp(a.ts))}">${when(a.ts)}</small></div></li>`).join("")}</ol>`;
  }

  // ---------- opening and viewing ----------
  function openItem(id) {
    const n = node(id); if (!n) return;
    if (view === "trash") return selectOnly(id);
    if (n.kind === "folder") return go("folder", { space: n.space, folder: n.id });
    openViewer(n);
  }
  function openViewer(n, o = {}) {
    let d = $("#drv-viewer");
    if (!d) { d = document.createElement("dialog"); d.id = "drv-viewer"; d.className = "drv-viewer"; d.setAttribute("aria-label", "File viewer"); document.body.append(d); wireViewer(d); }
    const list = shown().filter(x => x.kind === "file");
    viewer = { n, list: list.some(x => x.id === n.id) ? list : [n], edit: !!o.edit && canEdit(n), text: null, loaded: false, err: null, dirty: false, base: n.version, src: false };
    drawViewer();
    if (!d.open) d.showModal();
    if (isText(n) || OFFICE.test(n.name) || kindOf(n) === "file") loadText();
  }
  async function loadText() {
    const v = viewer, n = v.n;
    try {
      if (isText(n) && n.size <= EDIT_MAX) {  // the whole file, for reading and editing (its version is known from the list, from before it was read)
        const r = await fetch(content(n.id), { credentials: "same-origin" });
        if (r.status === 401) Auth.expired();
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Couldn't open this file.");
        v.text = await r.text(); v.full = true;
      } else { const r = await api(`/api/drive/nodes/${n.id}/text`); v.text = r.text; v.full = false; }
    } catch (e) { v.err = e.message; }
    v.loaded = true;
    if (viewer === v) drawViewer();
  }
  function viewerBody(v) {
    const n = v.n, k = kindOf(n), src = content(n.id);
    if (k === "image") return `<img class="drv-vimg" src="${src}" alt="${esc(n.name)}">`;
    if (k === "pdf") return `<iframe class="drv-vpdf" src="${src}" title="${esc(n.name)}"></iframe>`;
    if (k === "video") return `<video class="drv-vmedia" src="${src}" controls autoplay preload="metadata"></video>`;
    if (k === "audio") return `<div class="drv-vaudio">${icon("speaker")}<audio src="${src}" controls autoplay preload="metadata"></audio></div>`;
    const none = msg => `<div class="drv-vnone">${icon(ICON[k])}<b>${esc(n.name)}</b><span class="faint">${msg}</span><a class="btn primary" href="${content(n.id, { download: true })}">${icon("download")}Download ${bytes(n.size)}</a></div>`;
    if (v.err) return none(esc(v.err));
    if (!v.loaded) return `<div class="drv-vnone">${Loading.line(k === "file" ? "Looking for text to show…" : "Loading…")}</div>`;
    if (!v.text && k !== "text") return none("No preview for this type of file.");
    const note = !v.full ? `<p class="drv-vnote faint small">${icon("info")}${k === "doc" || k === "file" ? "The text of this document, without its layout. Download it to see it as made." : "The start of a long file."}</p>` : "";
    return `<div class="drv-vpage">${note}${MD.test(n.name) && !v.src ? `<article class="md drv-md">${Agents.md(v.text)}</article>` : `<pre class="drv-vpre">${esc(v.text)}</pre>`}</div>`;
  }
  function drawViewer() {
    const d = $("#drv-viewer"), v = viewer; if (!d || !v) return;
    const n = v.n, k = kindOf(n), i = v.list.findIndex(x => x.id === n.id);
    d.innerHTML = `<header class="drv-vhead"><button type="button" class="iconbtn" data-v="close" aria-label="Close (Esc)" title="Close (Esc)">${icon("left")}</button>
        <span class="drv-ico k-${k}">${icon(ICON[k])}</span><b class="drv-vname" title="${esc(n.name)}">${esc(n.name)}</b><span class="spacer"></span>
        ${v.edit ? `<span class="faint small drv-vstate" id="drv-vstate" role="status">${v.dirty ? "Unsaved changes" : v.saved ? "Saved" : ""}</span>
            <button type="button" class="btn sm" data-v="done">Done</button><button type="button" class="btn sm primary" data-v="save" ${v.dirty ? "" : "disabled"} title="Save (Ctrl+S)">Save</button>`
          : `${canEdit(n) ? `<button type="button" class="btn sm" data-v="edit">${icon("edit")}Edit</button>` : ""}
            ${MD.test(n.name) && v.loaded && typeof v.text === "string" ? `<button type="button" class="btn sm" data-v="src">${v.src ? "Preview" : "Source"}</button>` : ""}
            ${canShare(n) ? `<button type="button" class="iconbtn" data-v="share" title="Share" aria-label="Share">${icon("userplus")}</button>` : ""}
            <button type="button" class="iconbtn ${n.starred ? "drv-on" : ""}" data-v="star" aria-pressed="${!!n.starred}" title="${n.starred ? "Remove from Starred" : "Add to Starred"}" aria-label="Star">${icon("star")}</button>
            <a class="iconbtn" href="${content(n.id, { download: true })}" title="Download" aria-label="Download">${icon("download")}</a>`}</header>
      <div class="drv-vbody">${v.edit ? (v.err ? `<div class="sl-err">${icon("alert")}${esc(v.err)}</div>` : v.loaded ? `<textarea class="drv-editor" spellcheck="false" aria-label="Edit ${esc(n.name)}">${esc(v.text || "")}</textarea>` : Loading.line("Loading…")) : viewerBody(v)}</div>
      ${!v.edit && v.list.length > 1 ? `<button type="button" class="drv-vnav prev" data-v="prev" aria-label="Previous file" ${i <= 0 ? "disabled" : ""}>${icon("left")}</button>
        <button type="button" class="drv-vnav next" data-v="next" aria-label="Next file" ${i >= v.list.length - 1 ? "disabled" : ""}>${icon("right")}</button>
        <footer class="drv-vfoot">${i + 1} of ${v.list.length}</footer>` : ""}`;
    const ta = $(".drv-editor", d); if (ta) { ta.focus(); ta.setSelectionRange(0, 0); ta.scrollTop = 0; }
  }
  async function closeViewer() {
    const d = $("#drv-viewer"), v = viewer;
    if (v?.dirty && !(await UI.confirm({ title: "Discard your changes?", body: `Your edits to ${esc(v.n.name)} aren't saved.`, ok: "Discard", icon: "alert" }))) return;
    viewer = null; d?.close(); if (d) d.innerHTML = "";
  }
  function step(dir) {
    const v = viewer; if (!v || v.edit) return;
    const i = v.list.findIndex(x => x.id === v.n.id) + dir; if (i < 0 || i >= v.list.length) return;
    viewer = { ...v, n: v.list[i], text: null, loaded: false, err: null, base: v.list[i].version, src: false, full: false };
    drawViewer();
    const n = viewer.n; if (isText(n) || OFFICE.test(n.name) || kindOf(n) === "file") loadText();
  }
  async function save() {
    const v = viewer, ta = $(".drv-editor"); if (!v?.edit || !ta || v.saving) return;
    v.saving = true; const text = ta.value, state = $("#drv-vstate"); if (state) state.textContent = "Saving…";
    try {
      const r = await fetch(`/api/drive/nodes/${v.n.id}/content`, { method: "PUT", credentials: "same-origin", body: new Blob([text]),
        headers: { "X-Requested-With": "scout", "Content-Type": "application/octet-stream", "X-Drive-Edit": "1", ...(v.base ? { "X-Drive-Base-Version": v.base } : {}) } });
      const d = await r.json().catch(() => ({}));
      if (r.status === 401) Auth.expired();
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Couldn't save. Try again.");
      v.text = text; v.base = d.version; v.n = { ...v.n, ...d }; v.saved = true;
      v.dirty = ta.value !== text;  // typing while it saved
      const old = items().find(x => x.id === d.id); if (old) Object.assign(old, d);
      if (state) state.textContent = v.dirty ? "Unsaved changes" : "Saved";
      $("[data-v=save]")?.toggleAttribute("disabled", !v.dirty);
      reloadSoon();
    } catch (e) { toast(e.message, { kind: "error" }); if (state) state.textContent = "Not saved"; }
    finally { v.saving = false; }
  }
  function wireViewer(d) {
    d.addEventListener("cancel", e => { e.preventDefault(); closeViewer(); });
    d.addEventListener("input", e => { if (!e.target.matches(".drv-editor") || !viewer) return; if (!viewer.dirty) { viewer.dirty = true; $("#drv-vstate").textContent = "Unsaved changes"; $("[data-v=save]")?.removeAttribute("disabled"); } });
    d.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); return save(); }
      if (viewer?.edit || e.target.matches("video, audio, input, textarea")) return;
      if (e.key === "ArrowLeft") step(-1);
      if (e.key === "ArrowRight") step(1);
    });
    d.addEventListener("click", async e => {
      const a = e.target.closest("[data-v]")?.dataset.v, v = viewer; if (!a || !v) return;
      if (a === "close") return closeViewer();
      if (a === "prev" || a === "next") return step(a === "prev" ? -1 : 1);
      if (a === "edit") { v.edit = true; if (!v.full) { v.text = null; v.loaded = false; loadText(); } return drawViewer(); }
      if (a === "src") { v.src = !v.src; return drawViewer(); }
      if (a === "save") return save();
      if (a === "share") return shareDialog(v.n.id);
      if (a === "star") { await star([v.n], !v.n.starred); v.n = { ...v.n, starred: !v.n.starred }; return drawViewer(); }
      if (a === "done") {
        if (v.dirty && !(await UI.confirm({ title: "Discard your changes?", body: "They aren't saved.", ok: "Discard", icon: "alert" }))) return;
        v.edit = false; v.dirty = false; drawViewer();  // back to the last saved text
      }
    });
  }
  addEventListener("beforeunload", e => { if (viewer?.dirty || ups.some(u => ["queued", "uploading"].includes(u.status))) { e.preventDefault(); e.returnValue = ""; } });

  // ---------- uploads ----------
  const here = () => view === "folder" && writable() ? { space, folder } : { space: "mine", folder: null };
  async function upload(files, target = here()) {
    const ok = files.filter(f => { if (st.max_file && f.size > st.max_file) { toast(`${f.name} is over the ${bytes(st.max_file)} limit`, { kind: "error" }); return false; } return true; });
    if (!ok.length) return;
    let keep = false;
    const shownHere = view === "folder" && target.space === space && (target.folder || null) === (folder || null);
    const names = new Set(shownHere ? (data?.items || []).filter(n => n.kind === "file").map(n => n.name.toLowerCase()) : []);
    const clash = ok.filter(f => names.has(f.name.toLowerCase()));
    if (clash.length) {
      const choice = await new Promise(res => {
        Auth.modal(`<h3>${icon("copy")}${clash.length === 1 ? `“${esc(clash[0].name)}” is already here` : `${clash.length} files are already here`}</h3>
          <label class="drv-radio"><input type="radio" name="how" value="version" checked><span><b>Replace</b><small class="faint">The file there keeps its name and history; what's there now becomes an older version you can restore.</small></span></label>
          <label class="drv-radio"><input type="radio" name="how" value="keep"><span><b>Keep both</b><small class="faint">The new ${clash.length === 1 ? "file gets" : "files get"} a numbered name, like “${esc(clash[0].name.replace(/(\.[^.]*)?$/, " (1)$1"))}”.</small></span></label>`,
          async f => { res(f.elements.how.value); $("#modal").close(); }, { submit: "Upload" });
        $("#modal").addEventListener("close", () => res(null), { once: true });
      });
      if (!choice) return;
      keep = choice === "keep";
    }
    enqueue(ok.map(file => ({ file, dir: [] })), target, { keep });
  }
  function enqueue(list, target, { keep = false, node: nid = null } = {}) {
    for (const { file, dir } of list) ups.push({ id: ++upSeq, file, dir, target, keep, node: nid, status: "queued", pct: 0 });
    trayOpen = true; pump();
  }
  function pump() {
    while (running < PARALLEL) {
      const u = ups.find(x => x.status === "queued"); if (!u) break;
      running++; u.status = "uploading";
      send(u).finally(() => { running--; pump(); });
    }
    renderTray();
  }
  function ensureDir(target, dir) {
    const key = `${target.space}:${target.folder || ""}:${dir.join("/")}`;
    if (!dirs.has(key)) dirs.set(key, api("/api/drive/folders/ensure", { method: "POST", body: { space: target.space, parent: target.folder, path: dir } }).then(r => r.id)
      .catch(e => { dirs.delete(key); throw e; }));
    return dirs.get(key);
  }
  function xhr(method, url, body, onPct, keepX) {
    return new Promise((ok, no) => {
      const x = new XMLHttpRequest(); keepX(x);
      x.open(method, url);
      x.setRequestHeader("X-Requested-With", "scout");
      x.setRequestHeader("Content-Type", "application/octet-stream");
      x.upload.onprogress = e => { if (e.lengthComputable) onPct(e.loaded / e.total); };
      x.onload = () => {
        let d = {}; try { d = JSON.parse(x.responseText); } catch {}
        if (x.status < 300) return ok(d);
        if (x.status === 401) Auth.expired();
        no(new Error(typeof d.detail === "string" ? d.detail : x.status === 413 ? "Too large" : `Failed (HTTP ${x.status})`));
      };
      x.onerror = () => no(new Error("Connection lost"));
      x.onabort = () => no(Object.assign(new Error("Cancelled"), { aborted: true }));
      x.send(body);
    });
  }
  async function send(u) {
    try {
      const parent = u.dir.length ? await ensureDir(u.target, u.dir) : u.target.folder;
      if (u.status !== "uploading") return;  // cancelled while its folder was made
      const url = u.node ? `/api/drive/nodes/${u.node}/content`
        : `/api/drive/files?${new URLSearchParams({ space: u.target.space, name: u.file.name, ...(parent ? { parent } : {}), ...(u.keep ? { conflict: "keep" } : {}) })}`;
      u.result = await xhr(u.node ? "PUT" : "POST", url, u.file, p => { u.pct = p; const b = $(`#drv-tray [data-up="${u.id}"] .ws-bar i`); if (b) b.style.width = `${(p * 100).toFixed(0)}%`; }, x => u.x = x);
      u.status = "done"; u.folder = parent || null;
    } catch (e) { u.status = e.aborted ? "cancelled" : "error"; u.msg = e.message; }
    u.x = null; renderTray();
    if (u.status === "done") { reloadSoon(); if (u.node && detailFor === u.node) refreshDetail(); }
    clearTimeout(foldTimer);  // all done without errors: fold the tray away after a moment
    if (ups.every(x => ["done", "cancelled"].includes(x.status))) foldTimer = setTimeout(() => { if (ups.every(x => ["done", "cancelled"].includes(x.status))) { trayOpen = false; renderTray(); } }, 5000);
  }
  function renderTray() {
    let t = $("#drv-tray");
    if (!ups.length) { t?.remove(); return; }
    if (!t) {
      t = document.createElement("section"); t.id = "drv-tray"; t.className = "drv-tray"; t.setAttribute("aria-label", "Uploads"); document.body.append(t);
      t.addEventListener("click", trayClick);
    }
    const active = ups.filter(u => ["queued", "uploading"].includes(u.status)).length, failed = ups.filter(u => u.status === "error").length;
    const title = active ? `Uploading ${plural(active, "item")}` : failed ? `${plural(failed, "upload")} failed` : `${plural(ups.filter(u => u.status === "done").length, "upload")} complete`;
    const state = u => u.status === "uploading" ? `<span class="ws-bar"><i style="width:${(u.pct * 100).toFixed(0)}%"></i></span><button type="button" class="iconbtn sm" data-tray="cancel" aria-label="Cancel">${icon("close")}</button>`
      : u.status === "queued" ? `<span class="faint small">Waiting</span><button type="button" class="iconbtn sm" data-tray="cancel" aria-label="Cancel">${icon("close")}</button>`
      : u.status === "done" ? `<span class="drv-ok" title="Uploaded">${icon("check")}</span>${u.node ? "" : `<button type="button" class="btn sm" data-tray="show">Show</button>`}`
      : u.status === "error" ? `<button type="button" class="btn sm" data-tray="retry">Retry</button>` : `<span class="faint small">Cancelled</span>`;
    t.innerHTML = `<header><b role="status">${title}</b><span class="spacer"></span>
        <button type="button" class="iconbtn sm" data-tray="fold" aria-expanded="${trayOpen}" aria-label="${trayOpen ? "Collapse" : "Expand"}">${icon(trayOpen ? "chev" : "up")}</button>
        <button type="button" class="iconbtn sm" data-tray="close" aria-label="${active ? "Cancel uploads" : "Close"}">${icon("close")}</button></header>
      ${trayOpen ? `<ul>${ups.slice(-60).reverse().map(u => `<li data-up="${u.id}" class="${u.status}"><span class="drv-ico sm k-${kindOf({ kind: "file", name: u.file.name, mime: u.file.type })}">${icon(ICON[kindOf({ kind: "file", name: u.file.name, mime: u.file.type })])}</span>
          <span class="drv-upname"><b>${esc(u.file.name)}</b>${u.status === "error" ? `<small class="no">${esc(u.msg)}</small>` : u.dir.length ? `<small class="faint">${esc(u.dir.join(" › "))}</small>` : u.node ? `<small class="faint">New version</small>` : ""}</span>${state(u)}</li>`).join("")}</ul>` : ""}`;
  }
  async function trayClick(e) {
    const a = e.target.closest("[data-tray]")?.dataset.tray; if (!a) return;
    const u = ups.find(x => x.id === +e.target.closest("[data-up]")?.dataset.up);
    if (a === "fold") { trayOpen = !trayOpen; return renderTray(); }
    if (a === "cancel" && u) { if (u.x) u.x.abort(); else { u.status = "cancelled"; renderTray(); } return; }
    if (a === "retry" && u) { u.status = "queued"; u.pct = 0; return pump(); }
    if (a === "show" && u) { setView("drive"); reveal = u.result?.id; return go("folder", { space: u.result?.space === "with" ? "with" : u.target.space, folder: u.folder }); }
    if (a === "close") {
      const active = ups.filter(x => ["queued", "uploading"].includes(x.status));
      if (active.length && !(await UI.confirm({ title: `Cancel ${plural(active.length, "upload")}?`, body: "Files that finished stay in the drive.", ok: "Cancel uploads", icon: "upload" }))) return;
      active.forEach(x => { x.status = "cancelled"; x.x?.abort(); });
      ups.length = 0; dirs.clear(); renderTray();
    }
  }
  async function walk(entries) {  // dropped folders: every file with the folders it's in
    const out = [];
    const visit = async (en, dir) => {
      if (en.isFile) return out.push({ file: await new Promise((ok, no) => en.file(ok, no)), dir });
      const r = en.createReader(); let batch;
      do { batch = await new Promise((ok, no) => r.readEntries(ok, no)); for (const c of batch) await visit(c, [...dir, en.name]); } while (batch.length);
    };
    for (const en of entries) await visit(en, []);
    return out;
  }

  // ---------- actions ----------
  function newFolder() {
    Auth.modal(`<h3>${icon("folderplus")}New folder</h3><label class="in"><span>Name</span><input name="name" maxlength="200" required autocomplete="off" value="Untitled folder"></label>`,
      async f => { const r = await api("/api/drive/folders", { method: "POST", body: { space, parent: folder, name: f.elements.name.value } }); $("#modal").close(); reveal = r.id; load(); },
      { submit: "Create" });
    setTimeout(() => $("#modal [name=name]")?.select(), 30);
  }
  function newDoc() {
    Auth.modal(`<h3>${icon("doc")}New text file</h3><label class="in"><span>Name</span><input name="name" maxlength="200" required autocomplete="off" value="Untitled.md"></label>
      <p class="faint small">Markdown (.md) shows formatted; .txt, .csv, .json, code and other text files open as text. Each save keeps a version.</p>`,
      async f => {
        const r = await fetch(`/api/drive/files?${new URLSearchParams({ space, name: f.elements.name.value.trim(), conflict: "keep", ...(folder ? { parent: folder } : {}) })}`,
          { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "scout", "Content-Type": "application/octet-stream" }, body: "" });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Couldn't create the file.");
        $("#modal").close(); reveal = d.id; load(); usage();
        openViewer(d, { edit: true });
      }, { submit: "Create" });
    setTimeout(() => { const i = $("#modal [name=name]"); i?.focus(); i?.setSelectionRange(0, 8); }, 30);
  }
  function rename(id) {
    const n = node(id); if (!n) return;
    Auth.modal(`<h3>${icon("edit")}Rename</h3><label class="in"><span>Name</span><input name="name" maxlength="200" required autocomplete="off" value="${esc(n.name)}"></label>`,
      async f => { await api(`/api/drive/nodes/${id}`, { method: "PATCH", body: { name: f.elements.name.value } }); $("#modal").close(); toast("Renamed"); load(); refreshDetail(); },
      { submit: "Rename" });
    const i = $("#modal [name=name]"), dot = n.kind === "file" ? n.name.lastIndexOf(".") : -1;
    setTimeout(() => { i.focus(); i.setSelectionRange(0, dot > 0 ? dot : n.name.length); }, 30);
  }
  // a folder to move or copy into: My drive, the Shared drive, or a folder shared with you that you can edit
  function pickFolder({ title, submit, exclude = [] }) {
    return new Promise(resolve => {
      let to = { space: space === "with" && !writable() ? "mine" : view === "folder" ? space : "mine", folder: view === "folder" && writable() ? folder : null, path: data?.path || [], can: true };
      const f = Auth.modal(`<h3>${title}</h3><div class="seg full" id="mv-space">${SPACES.map(s => `<button type="button" data-s="${s}">${spaceLabel(s)}</button>`).join("")}</div>
        <div class="drv-mv" id="mv-box"></div>`,
        async () => {
          if (!to.can) throw new Error(to.space === "with" && !to.folder ? "Open a folder shared with you to put it there." : "You can view this folder, but not add to it.");
          $("#modal").close(); resolve(to);
        }, { submit });
      $("#modal").addEventListener("close", () => resolve(null), { once: true });
      const draw = async () => {
        $$("#mv-space button", f).forEach(b => b.setAttribute("aria-pressed", b.dataset.s === to.space));
        const box = $("#mv-box", f); box.innerHTML = Loading.line("Loading folders…");
        try {
          const r = await api(`/api/drive/list?${new URLSearchParams({ space: to.space, ...(to.folder ? { folder: to.folder } : {}) })}`);
          to.path = r.path; to.can = r.folder ? r.folder.can_write : to.space !== "with";
          const fs = r.items.filter(x => x.kind === "folder" && !exclude.includes(x.id));
          box.innerHTML = `<div class="drv-crumbs"><button type="button" data-mv="">${spaceLabel(to.space)}</button>${r.path.map(p => `${icon("right")}<button type="button" data-mv="${esc(p.id)}">${esc(p.name)}</button>`).join("")}</div>
            <div class="drv-mv-list">${fs.map(x => `<button type="button" data-mv="${esc(x.id)}">${icon("folder")}<span>${esc(x.name)}</span>${x.can_write ? "" : `<small class="faint">view only</small>`}</button>`).join("") || `<p class="faint small">No folders here.</p>`}</div>
            ${to.can ? "" : `<p class="faint small">${to.space === "with" && !to.folder ? "Pick a folder shared with you." : "You can't add to this folder."}</p>`}`;
        } catch (e) { box.innerHTML = `<p class="no small">${esc(e.message)}</p>`; to.can = false; }
        $("button[type=submit]", f).disabled = !to.can;
      };
      f.addEventListener("click", e => {
        const s = e.target.closest("[data-s]"); if (s) { to = { space: s.dataset.s, folder: null, path: [] }; return draw(); }
        const m = e.target.closest("[data-mv]"); if (m) { to.folder = m.dataset.mv || null; draw(); }
      });
      draw();
    });
  }
  async function moveTo(ns, to) {
    const done = [], errs = [];
    for (const n of ns) {
      try { await api(`/api/drive/nodes/${n.id}`, { method: "PATCH", body: { space: to.space, parent: to.folder || "" } }); done.push(n); }
      catch (e) { errs.push(`${n.name}: ${e.message}`); }
    }
    const dest = to.path?.length ? to.path[to.path.length - 1].name : spaceLabel(to.space);
    if (done.length) UI.undoable(`${label(done)} moved to ${dest}`, async () => {
      for (const n of done) await api(`/api/drive/nodes/${n.id}`, { method: "PATCH", body: { space: n.space === "with" ? undefined : n.space, parent: n.parent || "" } });
      load();
    }, "Moved back");
    if (errs.length) toast(errs[0] + (errs.length > 1 ? ` (and ${errs.length - 1} more)` : ""), { kind: "error" });
    sel = new Set(); load(); refreshDetail();
  }
  async function move(ns) {
    const to = await pickFolder({ title: `${icon("right")}Move ${esc(label(ns))}`, submit: "Move here", exclude: ns.map(n => n.id) });
    if (to) moveTo(ns, to);
  }
  async function copy(ns, to = null) {
    let made = 0;
    for (const n of ns) {
      try { await api(`/api/drive/nodes/${n.id}/copy`, { method: "POST", body: to ? { space: to.space === "with" ? null : to.space, parent: to.folder } : {} }); made++; }
      catch (e) { toast(`${n.name}: ${e.message}`, { kind: "error" }); }
    }
    if (made) toast(`${plural(made, "copy")} made${to ? ` in ${to.path?.length ? to.path[to.path.length - 1].name : spaceLabel(to.space)}` : ""}`, { kind: "success" });
    load(); usage();
  }
  async function copyTo(ns) {
    const to = await pickFolder({ title: `${icon("copy")}Copy ${esc(label(ns))} to…`, submit: "Copy here" });
    if (to) copy(ns, to);
  }
  async function star(ns, on) {
    try {
      await Promise.all(ns.map(n => api(`/api/drive/nodes/${n.id}/star`, { method: "PUT", body: { on } })));
      ns.forEach(n => { const x = items().find(y => y.id === n.id); if (x) x.starred = on; });
      toast(on ? `${label(ns)} added to Starred` : `${label(ns)} removed from Starred`);
      if (view === "starred") load(); else { renderList(); paintSel(); }
    } catch (e) { toast(e.message); }
  }
  async function trash(ns) {
    const done = [];
    for (const n of ns) { try { await api(`/api/drive/nodes/${n.id}/trash`, { method: "POST" }); done.push(n); } catch (e) { toast(`${n.name}: ${e.message}`, { kind: "error" }); } }
    if (done.length) UI.undoable(`${label(done)} moved to the trash`, async () => { for (const n of done) await api(`/api/drive/nodes/${n.id}/restore`, { method: "POST" }); load(); }, `${label(done)} restored`);
    sel = new Set(); load();
  }
  async function restore(ns) {
    let n = 0;
    for (const x of ns) { try { await api(`/api/drive/nodes/${x.id}/restore`, { method: "POST" }); n++; } catch (e) { toast(e.message); } }
    if (n) toast(`${ns.length === 1 ? ns[0].name : plural(n, "item")} restored`);
    sel = new Set(); load(); usage();
  }
  function purge(ns) {
    UI.confirm({ title: `Delete ${esc(label(ns))} forever?`, body: ns.some(n => n.kind === "folder") ? "Folders and everything in them, and every version of each file, are deleted for good. This can't be undone."
      : `${ns.length === 1 ? "The file and all its versions are" : "The files and all their versions are"} deleted for good. This can't be undone.`, ok: "Delete forever",
      run: async () => { for (const n of ns) await api(`/api/drive/nodes/${n.id}`, { method: "DELETE" }); toast("Deleted forever"); sel = new Set(); load(); usage(); } });
  }
  function emptyTrash() {
    UI.confirm({ title: `Empty the ${spaceLabel(trashSpace)} trash?`, body: "Everything in it that you're allowed to delete is removed for good.", ok: "Empty trash",
      run: async () => { const r = await api(`/api/drive/trash?space=${trashSpace}`, { method: "DELETE" }); toast(`${plural(r.deleted, "item")} deleted`); load(); usage(); } });
  }
  async function leave(ns) {
    for (const n of ns) { try { await api(`/api/drive/nodes/${n.id}/people/me`, { method: "DELETE" }); } catch (e) { toast(e.message, { kind: "error" }); } }
    toast(`${label(ns)} removed from Shared with me`); sel = new Set(); load();
  }
  function download(ns) {
    if (ns.length === 1 && ns[0].kind === "file") location.href = content(ns[0].id, { download: true });
    else if (ns.length > 200) toast("Download up to 200 items at a time, or download their folder.", { kind: "error" });
    else { location.href = `/api/drive/zip?ids=${ns.map(n => n.id).join(",")}`; toast("Preparing your zip…"); }
  }
  function newVersion(id) { const i = $("#drv-ver"); i.dataset.node = id; i.click(); }
  async function copyLink(token) {
    const url = `${location.origin}/s/${token}`;
    try { await navigator.clipboard.writeText(url); toast("Link copied"); } catch { prompt("Copy this link:", url); }
  }
  function revoke(token) {
    UI.confirm({ title: "Revoke this share link?", body: "Anyone who has it gets “link not found” from now on. A new link gets a new address.", ok: "Revoke", icon: "link",
      run: async () => { await api(`/api/drive/shares/${encodeURIComponent(token)}`, { method: "DELETE" }); toast("Link revoked"); if (view === "links") load(); refreshDetail(); } });
  }
  async function shareDialog(id) {
    let d;
    try { d = await api(`/api/drive/nodes/${id}`); } catch (e) { return toast(e.message); }
    const f = Auth.modal(`<h3>${icon("userplus")}Share “${esc(d.name)}”</h3><div class="drv-sh" id="sh-body"></div>`, async () => { $("#modal").close(); load(); refreshDetail(); }, { submit: "Done" });
    $("#modal").classList.add("drv-share");
    $("#modal").addEventListener("close", () => $("#modal").classList.remove("drv-share"), { once: true });
    const draw = () => {
      const role = r => `<select data-role aria-label="Access"><option value="viewer" ${r === "viewer" ? "selected" : ""}>Viewer</option><option value="editor" ${r === "editor" ? "selected" : ""}>Editor</option></select>`;
      $("#sh-body", f).innerHTML = `<section><h4>People with access</h4>
        ${d.can_share ? `<div class="drv-sh-add"><input name="who" placeholder="Username or email" autocomplete="off" maxlength="200" aria-label="Username or email">${role("viewer").replace("data-role", 'name="role"')}<button type="button" class="btn sm primary" data-sh="add">Share</button></div>` : ""}
        <ul class="drv-people">${d.space === "shared" ? `<li><span class="drv-av">${icon("users")}</span><span><b>Everyone signed in</b><small class="faint">It's in the Shared drive</small></span><span class="faint small">Can open</span></li>`
          : `<li><span class="drv-av">${esc((d.space === "mine" ? "Y" : (d.shared_by || "?")[0]).toUpperCase())}</span><span><b>${d.space === "mine" ? "You" : esc(d.shared_by || "Its owner")}</b></span><span class="faint small">Owner</span></li>`}
          ${d.people.map(p => `<li data-uid="${p.uid}"><span class="drv-av">${esc(p.name[0].toUpperCase())}</span><span><b>${p.me ? "You" : esc(p.name)}</b>${p.via ? `<small class="faint">Through the folder ${esc(p.via)}</small>` : ""}</span>
            ${d.can_share && !p.via ? `${role(p.role)}<button type="button" class="iconbtn sm" data-sh="remove" aria-label="Stop sharing with ${esc(p.name)}" title="Remove">${icon("close")}</button>`
              : `<span class="faint small">${p.role === "editor" ? "Editor" : "Viewer"}</span>${p.me && !p.via ? `<button type="button" class="btn sm" data-sh="leave">Leave</button>` : ""}`}</li>`).join("")}</ul>
        <p class="faint small">${d.can_share ? `Viewers can open, download and copy it. Editors can also add and edit files${d.kind === "folder" ? " in it, and rename, move or delete what's inside" : ""}. Only you can share it or delete it.`
          : d.space === "shared" ? "Move it to My drive to share it with only some people." : "Only its owner can change who has access."}</p></section>
        <section><h4>Links</h4>${d.shares.length ? `<ul class="drv-shares">${d.shares.map(s => `<li><span><b>${(e => e[0].toUpperCase() + e.slice(1))(expires(s.expires))}</b><small class="faint">${s.mine ? "You" : esc(s.by)} · ${plural(s.downloads, "download")}${s.password ? " · password" : ""}</small></span>
            <button type="button" class="iconbtn sm" data-copy="${esc(s.token)}" title="Copy link" aria-label="Copy link">${icon("copy")}</button><button type="button" class="iconbtn sm" data-sh="revoke" data-token="${esc(s.token)}" title="Revoke" aria-label="Revoke link">${icon("close")}</button></li>`).join("")}</ul>` : ""}
          ${st.links && d.role !== "viewer" ? `<div class="drv-sh-add"><select name="days" aria-label="Expires"><option value="1">1 day</option><option value="7" selected>7 days</option><option value="30">30 days</option><option value="90">90 days</option><option value="">Never</option></select>
            <input name="password" type="password" placeholder="Password (optional)" autocomplete="new-password" maxlength="200" aria-label="Link password"><button type="button" class="btn sm" data-sh="link">${icon("link")}Create link</button></div>
            <p class="faint small">Anyone with a link can download ${d.kind === "folder" ? "this folder as a .zip" : "this file"} without signing in.</p>`
            : `<p class="faint small">${d.role === "viewer" ? "Viewers can't make links." : "Only admins can create share links."}</p>`}</section>`;
    };
    const run = async (b, fn) => { b.disabled = true; b.classList.add("loading"); try { await fn(); draw(); } catch (e) { toast(e.message, { kind: "error" }); b.disabled = false; b.classList.remove("loading"); } };
    const add = b => { const who = f.elements.who.value.trim(); if (!who) return f.elements.who.focus();
      run(b, async () => { d.people = (await api(`/api/drive/nodes/${id}/people`, { method: "PUT", body: { user: who, role: f.elements.role.value } })).people; toast(`Shared with ${who}`); }); };
    f.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.name === "who") { e.preventDefault(); add($("[data-sh=add]", f)); } });
    f.addEventListener("change", e => {
      if (!e.target.matches("[data-role]")) return;
      const p = d.people.find(x => x.uid === +e.target.closest("[data-uid]")?.dataset.uid); if (!p) return;
      api(`/api/drive/nodes/${id}/people`, { method: "PUT", body: { user: p.name, role: e.target.value } }).then(r => { d.people = r.people; toast(`${p.name} is now ${e.target.value === "editor" ? "an editor" : "a viewer"}`); })
        .catch(x => { toast(x.message, { kind: "error" }); draw(); });
    });
    f.addEventListener("click", e => {
      const b = e.target.closest("[data-sh]"); if (!b) return;
      const a = b.dataset.sh, uid = +b.closest("[data-uid]")?.dataset.uid;
      if (a === "add") return add(b);
      if (a === "remove") return run(b, async () => { await api(`/api/drive/nodes/${id}/people/${uid}`, { method: "DELETE" }); d.people = d.people.filter(p => p.uid !== uid); });
      if (a === "leave") return run(b, async () => { await api(`/api/drive/nodes/${id}/people/me`, { method: "DELETE" }); $("#modal").close(); toast(`You left “${d.name}”`); load(); });
      if (a === "revoke") return run(b, async () => { await api(`/api/drive/shares/${encodeURIComponent(b.dataset.token)}`, { method: "DELETE" }); d.shares = d.shares.filter(s => s.token !== b.dataset.token); toast("Link revoked"); });
      if (a === "link") return run(b, async () => {
        const r = await api(`/api/drive/nodes/${id}/shares`, { method: "POST", body: { days: f.elements.days.value ? +f.elements.days.value : null, password: f.elements.password.value || null } });
        await copyLink(r.token); d = await api(`/api/drive/nodes/${id}`);
      });
    });
    draw();
    setTimeout(() => f.elements.who?.focus(), 30);
  }

  // ---------- menus ----------
  function popup(html, at) {
    $(".drv-menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover menu drv-menu"; pop.setAttribute("role", "menu");
    pop.innerHTML = html; document.body.appendChild(pop);
    const x = at.left ?? at.x, y = at.bottom != null ? at.bottom + 4 : at.y;  // under a button, or at the pointer
    pop.style.left = `${Math.max(8, Math.min(x, innerWidth - pop.offsetWidth - 8))}px`;
    pop.style.top = `${Math.max(8 + scrollY, Math.min(y + scrollY, scrollY + innerHeight - pop.offsetHeight - 8))}px`;
    $("button", pop)?.focus();
    const off = e => { if (!pop.contains(e.target)) close(); }, key = e => { if (e.key === "Escape") { close(); } };
    const close = () => { pop.remove(); document.removeEventListener("pointerdown", off, true); document.removeEventListener("keydown", key, true); };
    setTimeout(() => { document.addEventListener("pointerdown", off, true); document.addEventListener("keydown", key, true); });
    pop.addEventListener("keydown", e => {
      if (!["ArrowDown", "ArrowUp"].includes(e.key)) return;
      e.preventDefault(); const bs = $$("button", pop), i = bs.indexOf(document.activeElement);
      bs[(i + (e.key === "ArrowDown" ? 1 : -1) + bs.length) % bs.length]?.focus();
    });
    return { pop, close };
  }
  const menuHtml = items => items.filter(Boolean).filter((x, i, a) => !(x === "-" && (i === 0 || a[i - 1] === "-" || i === a.length - 1)))
    .map(x => x === "-" ? `<hr>` : `<button type="button" role="menuitem" data-mact="${x[0]}" class="mi ${x[3] || ""}">${icon(x[1])}${x[2]}</button>`).join("");
  function menu(id, at) {
    const n = node(id); if (!n) return;
    if (sel.size > 1 && sel.has(id)) {
      const { pop, close } = popup(menuHtml(bulkActions(picked()).map(([a, ic, l, cls]) => [a, ic, l, cls === "danger-text" ? "danger" : ""])), at);
      pop.onclick = e => { const a = e.target.closest("[data-mact]")?.dataset.mact; if (!a) return; close(); bulk(a); };
      return;
    }
    const file = n.kind === "file", located = view !== "folder";
    const items = view === "trash" ? [n.can_modify && ["restore", "reset", "Restore"], n.can_modify && ["purge", "trash", "Delete forever", "danger"]]
      : [file ? ["preview", "eye", "Open"] : ["open", "folder", "Open"], canEdit(n) && ["edit", "edit", "Edit"], ["download", "download", file ? "Download" : "Download as .zip"],
         canShare(n) && ["share", "userplus", "Share"], "-",
         ["star", "star", n.starred ? "Remove from Starred" : "Add to Starred"], n.can_modify && ["rename", "edit", "Rename"], n.can_modify && ["move", "right", "Move"],
         ["copy", "copy", "Make a copy"], ["copyto", "copy", "Copy to…"], file && n.can_write && ["version", "upload", "Upload new version"],
         located && ["locate", "folder", "Show in folder"], ["details", "info", "Details"], ["activity", "clock", "Activity"],
         view === "folder" && space === "with" && !folder && ["leave", "close", "Remove from Shared with me"], "-", n.can_modify && ["trash", "trash", "Delete", "danger"]];
    const { pop, close } = popup(menuHtml(items) || `<p class="faint small">Nothing you can do here.</p>`, at);
    pop.onclick = e => {
      const a = e.target.closest("[data-mact]")?.dataset.mact; if (!a) return;
      close(); act(a, n);
    };
  }
  function act(a, n) {
    const one = [n];
    if (a === "open" || a === "preview") return openItem(n.id);
    if (a === "edit") return openViewer(n, { edit: true });
    if (a === "details" || a === "activity") { tab = a === "activity" ? "activity" : "info"; info = true; keep("drive.info", true); if (!sel.has(n.id) || sel.size > 1) selectOnly(n.id); renderBar(); return renderDetail(); }
    if (a === "locate") { reveal = n.id; return go("folder", { space: n.space, folder: n.parent || null }); }
    if (a === "version") return newVersion(n.id);
    if (a === "rename") return rename(n.id);
    if (a === "copyto") return copyTo(one);
    if (a === "share") return shareDialog(n.id);
    return bulk(a, one);
  }
  function bulk(a, ns = picked()) {
    if (!ns.length) return;
    if (a === "download") return download(ns);
    if (a === "move") return move(ns);
    if (a === "copy") return copy(ns);
    if (a === "star" || a === "unstar") return star(ns, a === "star");
    if (a === "trash") return ns.every(n => n.can_modify) ? trash(ns) : toast("You can't delete some of these.", { kind: "error" });
    if (a === "restore") return restore(ns);
    if (a === "purge") return purge(ns);
    if (a === "leave") return leave(ns);
    if (a === "share") return shareDialog(ns[0].id);
  }
  function newMenu(btn) {
    const w = writable() || view !== "folder";
    const { pop, close } = popup(menuHtml([["folder", "folderplus", "New folder"], ["doc", "doc", "New text file"], "-", ["upload", "upload", "Upload files"], ["updir", "folderup", "Upload folder"]]), btn.getBoundingClientRect());
    pop.onclick = e => {
      const a = e.target.closest("[data-mact]")?.dataset.mact; if (!a) return;
      close();
      if (!w || view !== "folder") go("folder", { space: "mine", folder: null });  // like the big drives: new things land in My drive unless you're in a folder you can add to
      ({ folder: newFolder, doc: newDoc, upload: () => $("#drv-file").click(), updir: () => $("#drv-dir").click() })[a]();
    };
  }
  function sortMenu(btn) {
    const { pop, close } = popup(Object.entries(SORTS).map(([k, l]) => `<button type="button" role="menuitemradio" aria-checked="${sort.by === k}" data-sort="${k}" class="mi">${sort.by === k ? icon("check") : `<span class="icon"></span>`}${l}</button>`).join("") +
      `<hr><button type="button" role="menuitem" class="mi" data-sort="dir">${icon(sort.dir > 0 ? "down" : "up")}${sort.dir > 0 ? "Descending" : "Ascending"}</button>`, btn.getBoundingClientRect());
    pop.onclick = e => { const k = e.target.closest("[data-sort]")?.dataset.sort; if (!k) return; close(); setSort(k); };
  }
  function setSort(k) {
    sort = k === "dir" ? { ...sort, dir: -sort.dir } : sort.by === k ? { by: k, dir: -sort.dir } : { by: k, dir: k === "name" ? 1 : -1 };
    keep("drive.sort", sort); renderBar(); renderList();
  }

  // ---------- events ----------
  function wire() {
    if (wired) return; wired = true;
    const root = $("#view-drive"), list = () => $("#drv-list");
    root.addEventListener("click", e => {
      const t = e.target, g = s => t.closest(s);
      let x;
      if ((x = g("[data-menu]"))) { e.stopPropagation(); const id = x.closest("[data-node]").dataset.node; if (!sel.has(id)) selectOnly(id); return menu(id, x.getBoundingClientRect()); }
      if ((x = g("[data-nav]"))) { const k = x.dataset.nav; return SPACES.includes(k) ? go("folder", { space: k, folder: null }) : go(k); }
      if ((x = g("[data-crumb]"))) return go("folder", { folder: x.dataset.crumb || null });
      if ((x = g("[data-tspace]"))) { trashSpace = x.dataset.tspace; renderSub(); return load(); }
      if ((x = g("[data-layout]"))) { layout = x.dataset.layout; keep("drive.layout", layout); renderBar(); return renderList(); }
      if ((x = g("[data-sortby]"))) return setSort(x.dataset.sortby);
      if ((x = g("[data-tab]"))) { tab = x.dataset.tab; return renderDetail(); }
      if ((x = g("[data-copy]"))) return copyLink(x.dataset.copy);
      if ((x = g("[data-revoke]"))) return revoke(x.dataset.revoke);
      if ((x = g("[data-bulk]"))) return bulk(x.dataset.bulk);
      if ((x = g("[data-preview]"))) return openViewer(detail);
      if ((x = g("[data-vrestore]"))) return api(`/api/drive/nodes/${detail.id}/versions/${x.dataset.vrestore}/restore`, { method: "POST" }).then(() => { toast("Version restored"); refreshDetail(); load(); }).catch(e2 => toast(e2.message));
      if ((x = g("[data-act]"))) {
        const a = x.dataset.act, d = detail;
        if (a === "open") return d.kind === "folder" ? go("folder", { space: d.space, folder: d.id }) : openViewer(d);
        if (a === "restore") return restore([d]);
        if (a === "purge") return purge([d]);
        return act(a, d);
      }
      if ((x = g("[data-checkall]"))) { const xs = shown(); sel = x.checked ? new Set(xs.map(n => n.id)) : new Set(); return paintSel(); }
      const a = g("[data-dv]")?.dataset.dv;
      if (a === "new") return newMenu(g("[data-dv]"));
      if (a === "sort") return sortMenu(g("[data-dv]"));
      if (a === "info") { info = !info; keep("drive.info", info); renderBar(); return renderDetail(); }
      if (a === "clear") return clearSel();
      if (a === "upload") return $("#drv-file").click();
      if (a === "updir") return $("#drv-dir").click();
      if (a === "folder") return newFolder();
      if (a === "doc") return newDoc();
      if (a === "empty") return emptyTrash();
      if ((x = g("[data-node]"))) {
        const id = x.dataset.node;
        if (g("[data-check]")) return toggle(id);
        if (e.shiftKey) return range(id, e.ctrlKey || e.metaKey);
        if (e.ctrlKey || e.metaKey) return toggle(id);
        if (g("[data-go]")) return openItem(id);
        return selectOnly(id);
      }
      if (g("#drv-list") && !g("a, button, input, label")) clearSel();  // a click on empty space
    });
    root.addEventListener("dblclick", e => { const r = e.target.closest("[data-node]"); if (r && !e.target.closest("[data-check], [data-menu]")) openItem(r.dataset.node); });
    root.addEventListener("contextmenu", e => {
      const r = e.target.closest("#drv-list [data-node]"); if (!r) return;
      e.preventDefault();
      if (!sel.has(r.dataset.node)) selectOnly(r.dataset.node);
      menu(r.dataset.node, { x: e.clientX, y: e.clientY });
    });
    root.addEventListener("error", e => {  // a thumbnail that couldn't be made: show the file's icon
      if (!e.target.matches?.("img.drv-thumb")) return;
      const s = document.createElement("span"); s.className = "drv-tico"; s.innerHTML = icon("image"); e.target.replaceWith(s);
    }, true);
    root.addEventListener("keydown", e => {
      if (e.target.matches("input, textarea, select")) { if (e.key === "Escape" && e.target.id === "drv-q" && q) { e.target.value = ""; go("folder"); } return; }
      const r = e.target.closest?.("[data-node]"), id = r?.dataset.node, mod = e.ctrlKey || e.metaKey;
      if (r && e.key === "Enter") { e.preventDefault(); return openItem(id); }
      if (r && e.key === " ") { e.preventDefault(); return toggle(id); }
      if (r && (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10"))) { e.preventDefault(); if (!sel.has(id)) selectOnly(id); return menu(id, r.getBoundingClientRect()); }
      const rows = $$("#drv-list [data-node]");
      if (["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(e.key) && rows.length && (r || e.target === list())) {
        e.preventDefault();
        const i = rows.indexOf(r), dir = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : -1;
        let j = i < 0 ? 0 : i + dir;
        if (layout === "grid" && r && (e.key === "ArrowDown" || e.key === "ArrowUp")) {  // straight down or up in the grid
          const box = r.getBoundingClientRect(), same = rows.filter(o => o.parentElement === r.parentElement);
          const next = same.filter(o => dir > 0 ? o.getBoundingClientRect().top > box.bottom - 4 : o.getBoundingClientRect().bottom < box.top + 4)
            .sort((a, b) => Math.abs(a.getBoundingClientRect().left - box.left) - Math.abs(b.getBoundingClientRect().left - box.left) || (dir > 0 ? a.getBoundingClientRect().top - b.getBoundingClientRect().top : b.getBoundingClientRect().top - a.getBoundingClientRect().top))[0];
          j = next ? rows.indexOf(next) : i;
        }
        const to = rows[Math.max(0, Math.min(rows.length - 1, j))];
        to.focus(); to.scrollIntoView({ block: "nearest" });
        if (e.shiftKey) range(to.dataset.node, true); else if (!mod) selectOnly(to.dataset.node);
        return;
      }
      if (mod && e.key.toLowerCase() === "a" && (r || e.target === list())) { e.preventDefault(); sel = new Set(shown().map(n => n.id)); return paintSel(); }
      if (e.key === "Escape" && sel.size) return clearSel();
      if ((e.key === "Delete" || (e.key === "Backspace" && e.metaKey)) && sel.size && view !== "trash" && r) { e.preventDefault(); return bulk("trash"); }
      if (e.key === "F2" && sel.size === 1 && r) { e.preventDefault(); const n = node([...sel][0]); return n?.can_modify && rename(n.id); }
    });
    document.addEventListener("keydown", e => {  // "/" searches, as in the big drives
      if (e.key !== "/" || S.view !== "drive" || e.target.matches("input, textarea, select, [contenteditable]") || $("dialog[open]")) return;
      e.preventDefault(); $("#drv-q")?.focus();
    });
    root.addEventListener("input", e => {
      if (e.target.id !== "drv-q") return;
      clearTimeout(qTimer);
      qTimer = setTimeout(() => {
        q = e.target.value.trim();
        if (q.length >= 2) { if (view !== "search") { view = "search"; sel = new Set(); renderNav(); renderBar(); } renderCrumbs(); load(); const i = $("#drv-q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
        else if (view === "search" && !q) go("folder");
      }, 300);
    });
    root.addEventListener("change", async e => {
      const t = e.target;
      if (t.id === "drv-file") { upload([...t.files]); t.value = ""; return; }
      if (t.id === "drv-dir") {
        const list = [...t.files].map(file => ({ file, dir: file.webkitRelativePath.split("/").slice(0, -1) })); t.value = "";
        if (list.length) enqueue(list, here());
        return;
      }
      if (t.id === "drv-ver") { const f = t.files[0], nid = t.dataset.node; t.value = ""; if (f && nid) enqueue([{ file: f, dir: [] }], here(), { node: nid }); return; }
      if (t.id === "drv-all") { allLinks = t.checked; return load(); }
      if (t.id === "drv-members") {
        try { await api("/api/drive/settings", { method: "PUT", body: { links_for_members: t.checked } }); toast(t.checked ? "Members can create share links" : "Only admins can create share links"); usage(); }
        catch (x) { t.checked = !t.checked; toast(x.message); }
      }
    });
    // dragging items onto a folder moves them; files and folders dropped from the computer upload
    const ours = e => e.dataTransfer?.types?.includes("application/x-axor-drive");
    const dropTarget = e => {
      const z = e.target.closest?.("[data-drop]"); if (z) return z;
      const r = e.target.closest?.("#drv-list [data-node]"), n = r && node(r.dataset.node);
      return n?.kind === "folder" && n.can_write && !dragging?.includes(n.id) ? r : null;
    };
    const unmark = () => { $$(".drv-dropto").forEach(x => x.classList.remove("drv-dropto")); $("#drv-main")?.classList.remove("drop"); };
    root.addEventListener("dragstart", e => {
      const r = e.target.closest?.("#drv-list [data-node]"); if (!r) return;
      if (!sel.has(r.dataset.node)) selectOnly(r.dataset.node);
      const ns = picked().filter(n => n.can_modify);
      if (!ns.length) return e.preventDefault();
      dragging = ns.map(n => n.id);
      e.dataTransfer.setData("application/x-axor-drive", dragging.join(","));
      e.dataTransfer.effectAllowed = "move";
      const ghost = document.createElement("div"); ghost.className = "drv-ghost"; ghost.textContent = label(ns); document.body.append(ghost);
      e.dataTransfer.setDragImage(ghost, -10, -10); setTimeout(() => ghost.remove());
    });
    root.addEventListener("dragend", () => { dragging = null; unmark(); });
    root.addEventListener("dragover", e => {
      if (ours(e)) {
        const z = dropTarget(e); unmark(); if (!z) return;
        e.preventDefault(); e.dataTransfer.dropEffect = "move"; z.classList.add("drv-dropto"); return;
      }
      if (!e.dataTransfer?.types?.includes("Files") || view !== "folder") return;
      const z = dropTarget(e)?.matches("[data-node]") ? dropTarget(e) : null;
      if (!z && !writable()) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "copy";
      unmark(); z ? z.classList.add("drv-dropto") : $("#drv-main")?.classList.add("drop");
    });
    root.addEventListener("dragleave", e => { if (!e.relatedTarget || !root.contains(e.relatedTarget)) unmark(); });
    root.addEventListener("drop", async e => {
      const z = dropTarget(e); unmark();
      if (ours(e)) {
        e.preventDefault(); if (!z || !dragging) return;
        const ns = dragging.map(node).filter(Boolean); dragging = null;
        if (z.dataset.drop !== undefined) {
          const [s, f] = z.dataset.drop.split(":");
          const path = s === space && view === "folder" ? (data?.path || []).slice(0, (data?.path || []).findIndex(p => p.id === f) + 1) : [];
          return moveTo(ns, { space: s, folder: f || null, path });
        }
        const n = node(z.dataset.node);
        return moveTo(ns, { space: n.space, folder: n.id, path: [{ id: n.id, name: n.name }] });
      }
      if (view !== "folder" || !e.dataTransfer?.files?.length) return;
      e.preventDefault();
      const n = z?.matches("[data-node]") ? node(z.dataset.node) : null, target = n ? { space: n.space, folder: n.id } : here();
      const entries = [...e.dataTransfer.items || []].map(i => i.webkitGetAsEntry?.()).filter(Boolean);  // read before anything awaits
      if (entries.some(en => en.isDirectory)) {
        try { const list = await walk(entries); if (list.length) enqueue(list, target); } catch (x) { toast(`Couldn't read that folder: ${x.message}`, { kind: "error" }); }
      } else upload([...e.dataTransfer.files], target);
    });
  }
  // "Open Drive" buttons elsewhere (the workspace's Files panel); data-open-drive="<space>:<folder id>" opens that folder
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-open-drive]"); if (!b) return;
    const [sp, f] = (b.dataset.openDrive || "").split(":");
    if (f && SPACES.includes(sp)) { view = "folder"; space = sp; folder = f; sel = new Set(); }
    setView("drive");
  });

  return { init, open, go };  // go: other pages open a folder here (file-catalog.js)
})();
