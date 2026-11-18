/* Machines view (admins only): Linux and Windows virtual machines on the server's KVM (backend/app/machines.py).
   A list on the left; the selected machine on the right with Console (its screen, through noVNC and AXoR's relay),
   Overview (system, resources, disk, pods, events) and Logs (its download and setup). New and Edit open a form;
   changes and the console ask for sudo first. Polls faster while a machine sets up, stops or waits for a KVM slot. */
const Machines = (() => {
  const API = "/api/machines";
  const ST = { running: ["Running", "ok"], starting: ["Setting up", "run"], waiting: ["Waiting", "wait"], failing: ["Failing", "bad"],
    stopping: ["Stopping", "run"], stopped: ["Stopped", "off"] };
  const FAMILY = { linux: "Linux", windows: "Windows" };
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const withSudo = fn => Admin.withSudo(fn);
  const bytes = n => n == null ? "–" : n < 1048576 ? `${fmtNum(n / 1024, 0)} KB` : n < 1073741824 ? `${fmtNum(n / 1048576, 0)} MB` : `${fmtNum(n / 1073741824, 2)} GB`;
  const since = ts => !ts ? "–" : Date.now() / 1000 - ts < 86400 ? ago(ts) : new Date(ts * 1000).toLocaleDateString();
  const dot = st => `<span class="ci ci-${(ST[st] || [, "off"])[1]}" role="img" aria-label="${esc((ST[st] || [st])[0])}"></span>`;
  const pill = st => `<span class="ci-pill ci-${(ST[st] || [, "off"])[1]}">${esc((ST[st] || [st])[0])}</span>`;
  const put = (el, html) => { if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; } };
  const root = () => $("#machines");
  const busy = x => x && ["starting", "stopping", "waiting"].includes(x.status);
  let d = null, sel = null, cur = null, tab = "console", wired = false, timer = null, logTail = 300;
  // the console: noVNC's RFB on a WebSocket to AXoR's relay
  let RFB = null, rfb = null, conn = { name: null, state: "idle", note: "" }, fit = true;

  async function open() {
    wire();
    if (!d) root().innerHTML = `<h1 class="page">Machines</h1>${Loading.line("Loading machines…")}`;
    await load();
    schedule();
  }
  function close() { clearTimeout(timer); disconnect(); }
  async function load() {
    try { d = await api(API); }
    catch (e) { d = null; disconnect(); root().innerHTML = `<h1 class="page">Machines</h1><p class="lead">${lead}</p><div class="empty">${esc(e.message)}</div>`; return; }
    if (!d.items.some(x => x.name === sel)) sel = store.get("machines.sel", null);
    if (!d.items.some(x => x.name === sel)) sel = d.items[0]?.name ?? null;
    cur = sel ? await api(`${API}/${sel}`).catch(() => cur) : null;
    render();
  }
  function schedule() {
    clearTimeout(timer);
    const hot = d?.items.some(busy) || busy(cur);
    timer = setTimeout(async () => { if ($("#view-machines").hidden) return close(); await load(); schedule(); }, hot ? 3000 : 15000);
  }
  async function select(name) {
    disconnect();
    sel = name; store.set("machines.sel", name); cur = null; render();
    cur = await api(`${API}/${name}`).catch(e => (err(e), null)); render();
  }
  const lead = "Linux and Windows virtual machines on this server's KVM: pick a system and use its screen right here.";

  // ---------- page ----------
  function render() {
    if (!d) return;
    if (!$(".pk-main", root())) root().innerHTML = `<h1 class="page">Machines</h1><p class="lead">${lead}</p>
      <div data-part="kvm"></div>
      <div class="stats" data-part="stats"></div>
      <div class="src dv pk mc">
        <aside class="card src-repos"><div class="src-side-head"><b>Machines</b><span class="spacer"></span>
          <button type="button" class="btn sm primary" data-mc="new">${icon("plus")}New</button></div>
          <div class="src-list" data-part="list"></div></aside>
        <div class="card src-main pk-main" data-part="main"></div>
      </div>`;
    const on = d.items.filter(x => x.status !== "stopped"), run = d.items.filter(x => x.status === "running").length;
    put($("[data-part=kvm]", root()), d.kvm === 0 ? `<div class="sl-err mc-kvm">${icon("alert")}<span>This server's KVM isn't offered to the cluster yet, so machines can't start. Deploy <code>k8s/base/55-machines.yaml</code> (<code>k8s/deploy.sh</code>), which runs the KVM device plugin.</span></div>` : "");
    const tile = (ic, l, v, sub) => `<div class="stat"><div class="label">${icon(ic)}${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`;
    put($("[data-part=stats]", root()), [
      tile("monitor", "Machines", `${run}/${d.items.length}`, `${d.items.length - run} not running`),
      tile("chip", "CPU", `${on.reduce((a, x) => a + (x.cores || 0), 0)}`, `virtual cores; ${fmtNum(d.items.reduce((a, x) => a + x.cpu, 0), 2)} in use`),
      tile("chips", "Memory", `${on.reduce((a, x) => a + (x.ram || 0), 0)} GB`, `given to machines; ${bytes(d.items.reduce((a, x) => a + x.memory, 0))} in use`),
      tile("server", "KVM slots", d.kvm == null ? "–" : `${on.length}/${d.kvm}`, "machines that can run at once"),
    ].join(""));
    put($("[data-part=list]", root()), d.items.map(x => `<button type="button" class="src-item" data-sel="${esc(x.name)}" aria-current="${x.name === sel}">
        ${dot(x.status)}<span class="src-item-main"><b>${esc(x.name)}</b><small class="faint">${esc(x.title || x.os)} · ${x.cores} CPU · ${x.ram} GB</small></span></button>`).join("")
      || `<div class="empty pk-first">No machines yet.<br><button type="button" class="btn sm primary" data-mc="new">${icon("plus")}New machine</button></div>`);
    renderMain();
  }

  function renderMain() {
    const el = $("[data-part=main]", root()); if (!el) return;
    if (!sel) return put(el, `<div class="empty">A machine is a whole computer: Ubuntu, Debian, Fedora, Rocky, Arch and other Linux systems, or Windows 10, 11 and Server. Make one, then use its screen in the Console.</div>`);
    if (!cur) return put(el, Loading.line("Loading…"));
    const x = cur, on = !["stopped", "stopping"].includes(x.status);
    const TABS = [["console", "Console", "monitor"], ["overview", "Overview", "info"], ["logs", "Logs", "terminal"]];
    if (!TABS.some(t => t[0] === tab)) tab = "console";
    const head = `<div class="pk-head"><div class="pk-title"><h2>${esc(x.name)}</h2>${pill(x.status)}
        <span class="mc-fam mc-${esc(x.family || "linux")}">${esc(x.title || x.os)}</span></div>
      <div class="pk-acts">
        <button type="button" class="btn sm" data-mc="restart" ${x.status === "running" || x.status === "failing" ? "" : "disabled"}>${icon("reset")}Restart</button>
        <button type="button" class="btn sm" data-mc="${on ? "stop" : "start"}" ${x.status === "stopping" ? "disabled" : ""}>${icon(on ? "stop" : "play")}${on ? "Stop" : "Start"}</button>
        <button type="button" class="btn sm" data-mc="edit">${icon("edit")}Edit</button>
        <button type="button" class="iconbtn danger" data-mc="delete" title="Delete" aria-label="Delete ${esc(x.name)}">${icon("trash")}</button></div></div>
      ${x.message ? `<div class="sl-err">${icon("alert")}<span>${esc(x.message)}</span></div>` : ""}
      <div class="src-tabs" role="tablist">${TABS.map(([k, l, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${icon(ic)}${l}</button>`).join("")}</div>`;
    const live = tab === "console" && x.status === "running";
    // keep the console's screen (and the log's scroll position) through polls: only the head is redrawn
    if (el.dataset.showing === x.name && el.dataset.showtab === tab && el.dataset.live === String(live) && ["console", "logs"].includes(tab) && $(".pk-head", el)) {
      el.querySelectorAll(":scope > .sl-err, :scope > .src-tabs").forEach(n => n.remove());
      const h = $(".pk-head", el), tmp = document.createElement("div");
      tmp.innerHTML = head; h.replaceWith(...tmp.children); el.dataset.html = "";
      if (tab === "console" && !live) put($(".mc-wait", el), waitHtml());
    } else {  // a new screen element: the old connection goes with the old one (a manual disconnect stays one)
      const was = conn;
      disconnect();
      if (live && was.state === "manual" && was.name === x.name) conn = was;
      put(el, head + `<div class="src-body pk-body ${live ? "mc-console" : ""}">${{ console: consoleTab, overview, logs: logsTab }[tab]()}</div>`);
    }
    el.dataset.showing = x.name; el.dataset.showtab = tab; el.dataset.live = String(live);
    if (tab === "logs" && !$(".pk-log", el).dataset.loaded) loadLogs();
    if (live && conn.name !== x.name && conn.state !== "manual") connect();
    else if (live) showConn();
  }

  // ---------- console ----------
  function consoleTab() {
    const x = cur;
    if (x.status !== "running") return `<div class="mc-wait">${waitHtml()}</div>`;
    return `<div class="mc-bar"><span class="mc-state" data-part="conn" role="status"></span><span class="spacer"></span>
        <button type="button" class="btn sm" data-mc="cad" title="Send Ctrl+Alt+Del">${icon("keyboard")}Ctrl+Alt+Del</button>
        <button type="button" class="btn sm" data-mc="fit" aria-pressed="${fit}" title="Fit the screen to the page, or show it at its own size">${icon(fit ? "shrink" : "expand")}${fit ? "Fit" : "100%"}</button>
        <button type="button" class="btn sm" data-mc="full">${icon("expand")}Full screen</button>
        <button type="button" class="btn sm" data-mc="conn"></button></div>
      <div class="mc-screen ${fit ? "" : "mc-native"}" data-part="screen"></div>
      <p class="faint pk-note">Click the screen to type into the machine. ${x.family === "windows"
        ? `Windows signs in as <b>${esc(x.settings.username || "")}</b> with the password set when it was made; the first start installs it, which takes 10 to 20 minutes after the download.`
        : esc(x.note || "A new machine boots its system's installer or live image: install it from here as on a new PC.")}</p>`;
  }
  function waitHtml() {
    const x = cur;
    if (["stopped", "stopping"].includes(x.status)) return `<div class="empty">${icon("monitor")}<p>${esc(x.name)} is ${x.status === "stopping" ? "shutting down" : "stopped"}.</p>
      ${x.status === "stopped" ? `<button type="button" class="btn primary" data-mc="start">${icon("play")}Start</button>` : ""}</div>`;
    if (x.status === "waiting") return `<div class="empty">${icon("clock")}<p>Waiting to start.</p></div>`;
    if (x.status === "failing") return `<div class="empty">${icon("alert")}<p>It isn't running: see the message above and the Logs.</p></div>`;
    return `<div class="empty">${icon("clock")}<p>Setting up ${esc(x.title || "")}. The screen opens here once the virtual machine runs.</p>
      ${x.progress ? `<code class="mc-progress">${esc(x.progress)}</code>` : ""}<p class="faint">The first start downloads the system${x.family === "windows" ? " from Microsoft (several GB)" : ""}.</p></div>`;
  }
  async function connect() {
    const x = cur, name = x.name;
    disconnect();
    conn = { name, state: "connecting", note: "" }; showConn();
    try {
      await withSudo(() => api(`${API}/${encodeURIComponent(name)}/console`));
      if (!RFB) RFB = (await import("/static/vendor/novnc/core/rfb.js")).default;
    } catch (e) {
      if (conn.name === name) { conn = { name, state: "manual", note: e.message === "cancelled" ? "Not connected." : e.message }; showConn(); }
      return;
    }
    const scr = $("[data-part=screen]", root());
    if (!scr || conn.name !== name || cur?.name !== name || tab !== "console") return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${API}/${encodeURIComponent(name)}/console`, ["binary"]);
    ws.addEventListener("close", e => { if (e.code >= 4000 && conn.name === name) conn.note = e.reason; });
    const r = new RFB(scr, ws, { shared: true });
    rfb = r;
    r.scaleViewport = fit; r.clipViewport = false; r.resizeSession = false; r.focusOnClick = true; r.background = "#000";
    r.addEventListener("connect", () => { if (rfb === r) { conn.state = "on"; conn.note = ""; showConn(); r.focus({ preventScroll: true }); } });
    r.addEventListener("disconnect", e => {
      if (rfb !== r) return;
      rfb = null;
      conn = { name, state: "manual", note: conn.note || (e.detail.clean ? "Disconnected." : "The connection dropped: the machine may have restarted.") };
      showConn();
    });
    r.addEventListener("desktopname", e => { if (rfb === r) { conn.desktop = e.detail.name; showConn(); } });
  }
  function disconnect() {
    const r = rfb; rfb = null;
    if (r) try { r.disconnect(); } catch { /* already closed */ }
    conn = { name: null, state: "idle", note: "" };
  }
  function showConn() {
    const s = $("[data-part=conn]", root()), b = $("[data-mc=conn]", root());
    if (!s || !b) return;
    const on = conn.state === "on";
    s.innerHTML = on ? `${dot("running")}Connected${conn.desktop ? ` <small class="faint">${esc(conn.desktop)}</small>` : ""}`
      : conn.state === "connecting" ? `${dot("starting")}Connecting…` : `${dot("stopped")}${esc(conn.note || "Not connected.")}`;
    b.innerHTML = on || conn.state === "connecting" ? `${icon("close")}Disconnect` : `${icon("reset")}Connect`;
    $$("[data-mc=cad], [data-mc=full]", root()).forEach(x => x.disabled = !on);
  }

  // ---------- overview and logs ----------
  function overview() {
    const x = cur, s = x.settings;
    const cpu = x.pods.reduce((a, p) => a + (p.cpu || 0), 0), mem = x.pods.reduce((a, p) => a + (p.memory || 0), 0);
    const fact = (l, v) => `<div><span>${l}</span><b>${v}</b></div>`;
    const lang = d?.languages?.[s.language] || s.language;
    const facts = [
      fact("System", `${esc(x.title || s.os)} <small class="faint">${esc(FAMILY[x.family] || "")}</small>`),
      ...(s.url ? [fact("Image", `<code>${esc(s.url)}</code>`)] : []),
      fact("CPU", `${s.cores} cores <small class="faint">${fmtNum(cpu, 2)} in use</small>`),
      fact("Memory", `${s.ram} GB <small class="faint">${bytes(mem)} in use, with QEMU</small>`),
      fact("Disk", `${s.disk} GB <small class="faint">volume ${esc(x.volume.name)}${x.volume.phase ? `, ${esc(x.volume.phase.toLowerCase())}` : ""}</small>`),
      ...(x.family === "windows" ? [fact("Windows account", `${esc(s.username || "")} <small class="faint">${esc(lang || "")}</small>`)] : []),
      fact("Network", `Internet <small class="faint">not this server or private networks; only the console reaches it</small>`),
      fact("Runs on", `<code>${esc(x.image || "")}</code>`),
      fact("Started", since(x.started)),
      ...(x.change ? [fact("Last change", esc(x.change))] : []),
    ];
    return `${x.status === "starting" && x.progress ? `<div class="mc-now">${icon("clock")}<span><b>Setting up:</b> ${esc(x.progress)}</span></div>` : ""}
      <div class="kv pk-facts">${facts.join("")}</div>
      <h3 class="pk-h">${icon("server")}Pod</h3>
      ${x.pods.length ? `<div class="tablewrap flat"><table class="grid pk-pods"><thead><tr><th>Pod</th><th>State</th><th class="r">Restarts</th><th class="r">CPU</th><th class="r">Memory</th><th>Started</th></tr></thead><tbody>
        ${x.pods.map(p => `<tr><td><code>${esc(p.name)}</code></td><td>${esc(p.deleting ? "Stopping" : p.phase)} ${p.ready ? `<span class="badge clear">ready</span>` : ""}${p.problem ? `<small class="pk-problem">${esc(p.problem)}</small>` : ""}</td>
          <td class="r num">${p.restarts}</td><td class="r num">${p.cpu == null ? "–" : fmtNum(p.cpu, 3)}</td><td class="r num">${bytes(p.memory)}</td><td class="num">${since(p.created)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="empty">No pod: it's stopped.</div>`}
      <h3 class="pk-h">${icon("bell")}Events</h3>
      ${x.events.length ? `<ul class="pk-events">${x.events.slice(0, 12).map(e => `<li class="${e.type === "Warning" ? "warn" : ""}"><span class="num faint">${since(e.time)}</span><b>${esc(e.reason)}</b><span>${esc(e.message)}</span></li>`).join("")}</ul>`
        : `<p class="faint">Nothing recent.</p>`}`;
  }
  function logsTab() {
    return `<div class="src-logbar"><select data-part="tail" aria-label="Lines">${[100, 300, 1000, 5000].map(n => `<option ${n === logTail ? "selected" : ""}>${n}</option>`).join("")}</select>
        <button type="button" class="btn sm" data-mc="logs">${icon("reset")}Refresh</button>
        <span class="faint">The download, setup and QEMU's own messages, oldest first.</span></div>
      <pre class="src-log pk-log" tabindex="0">${Loading.line("Reading logs…")}</pre>`;
  }
  async function loadLogs() {
    const pre = $("#machines .pk-log"); if (!pre) return;
    pre.dataset.loaded = 1;
    try { const r = await api(`${API}/${sel}/logs?tail=${logTail}`); pre.textContent = r.text || "No output yet."; pre.scrollTop = pre.scrollHeight; }
    catch (e) { pre.textContent = e.message; }
  }

  // ---------- actions ----------
  async function act(a) {
    const x = cur;
    const go = async () => {
      if (a !== "start") disconnect();
      await withSudo(() => api(`${API}/${x.name}/action`, { method: "POST", body: { action: a } }));
      Auth.toast(`${{ stop: "Shutting down", start: "Starting", restart: "Restarting" }[a]} ${x.name}`); await load(); schedule();
    };
    if (a === "start") return go().catch(err);
    Auth.modal(`<h3>${icon(a === "stop" ? "stop" : "reset")}${a === "stop" ? "Stop" : "Restart"} ${esc(x.name)}?</h3>
      <p class="muted">${a === "stop" ? "The system is asked to shut down (up to about two minutes), then the machine stops. Its disk stays; start it again any time."
        : "The system is asked to shut down, then the machine starts again. Unsaved work in it is lost."}</p>`,
      async () => { $("#modal").close(); await go().catch(err); }, { submit: a === "stop" ? "Stop" : "Restart", danger: a === "stop" });
  }
  function remove() {
    const x = cur;
    Auth.modal(`<h3>${icon("trash")}Delete ${esc(x.name)}?</h3><p class="muted">The machine and its ${x.settings.disk} GB disk are deleted, with everything installed or saved on it. This can't be undone.</p>
      <label class="chk"><input type="checkbox" name="sure" required> Delete ${esc(x.name)} and its disk</label>`,
      async f => {
        if (!f.elements.sure.checked) throw new Error("Tick the box to confirm.");
        disconnect();
        await withSudo(() => api(`${API}/${x.name}`, { method: "DELETE" }));
        $("#modal").close(); Auth.toast(`Deleted ${x.name}`); sel = null; cur = null; store.set("machines.sel", null); await load(); schedule();
      }, { submit: "Delete", danger: true });
  }
  function fullScreen() {
    const s = $("[data-part=screen]", root());
    if (s?.requestFullscreen) s.requestFullscreen().then(() => rfb?.focus()).catch(() => Auth.toast("This browser won't show it full screen."));
  }

  // ---------- the form ----------
  async function form(x) {
    try { await withSudo(() => api("/api/platform/sudo", { method: "POST" })); } catch (e) { return err(e); }
    if (!d) return;
    const OS = d.os, L = d.limits, s = x?.settings || {};
    const v = { os: "ubuntu", cores: 2, ram: OS.ubuntu.ram, disk: OS.ubuntu.disk, username: "admin", language: "en", url: "", ...s };
    const opts = fam => Object.entries(OS).filter(([, o]) => o.family === fam).map(([k, o]) => `<option value="${k}" ${k === v.os ? "selected" : ""}>${esc(o.title)}</option>`).join("");
    const f = Auth.modal(`<h3>${icon("monitor")}${x ? `Edit ${esc(x.name)}` : "New machine"}</h3>
      <div class="dv-form">
      <label class="in"><span>Name</span><input name="name" value="${esc(x?.name || "")}" ${x ? "readonly" : "required"} pattern="[a-z]([a-z0-9\\-]{0,28}[a-z0-9])?" placeholder="dev-box" autocapitalize="none" spellcheck="false" maxlength="30">
        <small class="faint">Lowercase letters, digits and dashes. It's also the machine's host name.</small></label>
      <label class="in"><span>Operating system</span><select name="os" ${x ? "disabled" : ""}><optgroup label="Linux">${opts("linux")}</optgroup><optgroup label="Windows">${opts("windows")}</optgroup></select>
        <small class="faint" data-part="os-note"></small></label>
      <label class="in" data-part="url"><span>Image address</span><input name="url" value="${esc(v.url)}" ${x ? "readonly" : ""} placeholder="https://example.org/distro.iso" autocapitalize="none" spellcheck="false" maxlength="500">
        <small class="faint">An ISO, or a disk image (qcow2, img, raw, vhd, vhdx, vmdk; also zipped). It's downloaded at the first start.</small></label>
      <div data-part="win" class="dv-form">
        <div class="dv-two"><label class="in"><span>Windows account</span><input name="username" value="${esc(v.username)}" ${x ? "readonly" : ""} maxlength="20" autocapitalize="none" spellcheck="false" autocomplete="off"></label>
          ${x ? `<label class="in"><span>Language</span><input value="${esc(d.languages[v.language] || v.language)}" readonly></label>`
              : `<label class="in"><span>Password</span><input name="password" type="password" minlength="4" maxlength="127" autocomplete="new-password"></label>`}</div>
        ${x ? `<small class="faint">Set when Windows was installed. Change them in Windows.</small>` : `<label class="in"><span>Language</span><select name="language">${Object.entries(d.languages).map(([k, l]) => `<option value="${k}" ${k === v.language ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`}
      </div>
      <div class="mc-three"><label class="in"><span>CPU cores</span><input name="cores" type="number" min="1" max="${L.cores}" value="${v.cores}"></label>
        <label class="in"><span>Memory (GB)</span><input name="ram" type="number" min="1" max="${L.ram}" value="${v.ram}"></label>
        <label class="in"><span>Disk (GB)</span><input name="disk" type="number" min="8" max="${L.disk}" value="${v.disk}" ${x ? "readonly" : ""}></label></div>
      <small class="faint">${x ? "Saving restarts the machine (its system is asked to shut down first). The disk's size is set when it's made." : "The disk's size can't change later. The machine reaches the internet but not this server or private networks."}</small>
      </div>`,
      async f => {
        const el = f.elements, os = x ? v.os : el.os.value, win = OS[os].family === "windows";
        const body = { name: el.name.value.trim(), os, cores: +el.cores.value, ram: +el.ram.value, disk: +el.disk.value };
        // Installation settings are fixed at creation. Linux machines have no Windows language to send back on edit.
        if (!x && os === "custom") body.url = el.url.value.trim();
        if (!x && win) Object.assign(body, { username: el.username.value.trim(), password: el.password.value, language: el.language.value });
        if (!body.name) throw new Error("Name the machine.");
        if (!x && win && body.password.length < 4) throw new Error("Give the Windows account a password (at least 4 characters).");
        const r = await withSudo(() => api(x ? `${API}/${x.name}` : API, { method: x ? "PUT" : "POST", body }));
        $("#modal").close(); Auth.toast(x ? `Saved ${r.name}` : `Made ${r.name}: setting it up`);
        if (x) disconnect();
        sel = r.name; store.set("machines.sel", sel); tab = x ? tab : "console"; await load(); schedule();
      }, { submit: x ? "Save" : "Make machine" });
    $("#modal").classList.add("dv-wide");
    $("#modal").addEventListener("close", () => $("#modal").classList.remove("dv-wide"), { once: true });
    const el = f.elements;
    const sync = (fresh) => {
      const os = x ? v.os : el.os.value, o = OS[os], win = o.family === "windows";
      $("[data-part=url]", f).hidden = os !== "custom";
      $("[data-part=win]", f).hidden = !win;
      el.ram.min = o.min_ram;
      if (fresh) { el.ram.value = o.ram; el.disk.value = o.disk; el.disk.min = win ? 20 : 8; }
      $("[data-part=os-note]", f).textContent = win
        ? "Downloaded from Microsoft and installed unattended. Windows 10 and 11 run unactivated, Server as a 180-day evaluation: activate them in Windows with your own licence."
        : os === "custom" ? "Any distribution: boot its installer or a ready-made disk image." : o.note || "Boots the installer (or live system). Install it from the Console as on a new PC.";
    };
    if (!x) el.os.onchange = () => sync(true);
    sync(false);
    setTimeout(() => (x ? el.cores : el.name).focus(), 30);
  }

  function wire() {
    if (wired) return; wired = true;
    sel = store.get("machines.sel", null);
    const v = $("#view-machines");
    v.addEventListener("click", e => {
      const b = e.target.closest("[data-mc], [data-sel], [data-tab]"); if (!b) return;
      if (b.dataset.sel) return b.dataset.sel !== sel && select(b.dataset.sel);
      if (b.dataset.tab) { tab = b.dataset.tab; return renderMain(); }
      const a = b.dataset.mc;
      if (a === "new") form(null);
      else if (a === "edit") form(cur);
      else if (a === "delete") remove();
      else if (["restart", "stop", "start"].includes(a)) act(a);
      else if (a === "logs") loadLogs();
      else if (a === "cad") { rfb?.sendCtrlAltDel(); rfb?.focus({ preventScroll: true }); }
      else if (a === "full") fullScreen();
      else if (a === "fit") {
        fit = !fit; if (rfb) rfb.scaleViewport = fit;
        $("[data-part=screen]", root())?.classList.toggle("mc-native", !fit);
        b.setAttribute("aria-pressed", fit); b.innerHTML = `${icon(fit ? "shrink" : "expand")}${fit ? "Fit" : "100%"}`;
      }
      else if (a === "conn") {
        if (conn.state === "on" || conn.state === "connecting") { const n = cur?.name; disconnect(); conn = { name: n, state: "manual", note: "Disconnected." }; showConn(); }
        else connect();
      }
    });
    v.addEventListener("change", e => { if (e.target.dataset.part === "tail") { logTail = +e.target.value; loadLogs(); } });
    window.addEventListener("pagehide", disconnect);
  }
  return { open, close };
})();
