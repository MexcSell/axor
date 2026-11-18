/* Cluster → Updates (admins only): AXoR's updater on the k3s host (k8s/auto-update.sh). It deploys each new commit on
   its branch, rolls back when the rollout or the health check fails, and only moves forward. This tab shows what it
   last saw and did (the running and newest commits, what's waiting, the last updates and the last log) and asks it for
   things it picks up within a minute: check now, update now, pause, or deploy the branch anyway. Updating and pausing
   ask for sudo; the updater on the host does the work, never AXoR itself. */
const Updates = (() => {
  let s = null, el = null, timer = null, wired = false, logOpen = null, offline = false;
  const err = e => e.message !== "cancelled" && Auth.toast(e.message);
  const withSudo = fn => Admin.withSudo(fn);
  const short = sha => esc((sha || "").slice(0, 7));
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const since = ts => {
    if (!ts) return "–";
    const x = Date.now() / 1000 - ts;
    return x < 60 ? "just now" : x < 3600 ? `${Math.floor(x / 60)} min ago` : x < 86400 ? `${Math.floor(x / 3600)} h ago` : `${Math.floor(x / 86400)} d ago`;
  };
  const took = r => { const t = r.finished - r.started; return !r.started || !r.finished ? "–" : t < 60 ? `${t}s` : `${Math.round(t / 60)} min`; };
  const link = sha => s.repo ? `<a href="https://github.com/${esc(s.repo)}/commit/${esc(sha)}" target="_blank" rel="noopener"><code>${short(sha)}</code></a>` : `<code>${short(sha)}</code>`;
  const busy = () => s?.installed && (s.activity !== "idle" || s.request);
  const put = (node, html) => { if (node && node.dataset.html !== html) { node.innerHTML = html; node.dataset.html = html; } };
  const RESULTS = { ok: ["ok", "Deployed"], "rolled-back": ["bad", "Rolled back"], "rollback-failed": ["bad", "Rollback failed"],
    skipped: ["none", "Nothing to do"], interrupted: ["wait", "Interrupted"], blocked: ["bad", "Checks failed"] };
  // "auto", or "update by <admin>" / "force by <admin>" from the updater's history
  const who = by => { const m = /^(update|force) by (.+)$/.exec(by || ""); return m ? `${esc(m[2])} <small class="faint">${m[1] === "force" ? "deploy anyway" : "update now"}</small>` : by === "auto" ? "Automatic" : esc(by || "–"); };

  async function show(root) {
    el = root; wire();
    if (!s) el.innerHTML = Loading.line("Reading the updater…");
    await load();
  }
  async function load() {
    try { s = await api("/api/cluster/updates"); offline = false; }
    catch (e) {
      // AXoR restarts during its own update: keep what we knew and say we're reconnecting
      if (s?.installed && s.activity !== "idle") offline = true;
      else s = { error_page: e.message };
    }
    render();
    clearTimeout(timer);
    timer = setTimeout(() => { if (el?.isConnected && !$("#view-cluster").hidden) load(); }, busy() || offline ? 4000 : 20000);
  }

  function head() {
    const b = esc(s.branch), n = s.pending_count, latest = s.latest?.sha;
    if (s.activity === "updating") return ["run", `Updating to ${short(s.target)}…`, `Started ${since(s.started)}. It builds the images, rolls them out and checks AXoR's health; AXoR restarts on the new version and this page reconnects by itself.`];
    if (s.activity === "checking") return ["run", `Checking ${short(s.target)} before it deploys…`, `Started ${since(s.started)}. It builds the images, boots the new version offline and runs the unit tests on it. If any check fails, nothing is deployed.`];
    if (s.activity === "waiting") return ["run", `Waiting for agents to finish before updating to ${short(s.target)}…`, "Agents are mid-task in AXoR. The update waits up to 10 minutes for them, then deploys anyway."];
    if (s.activity === "rolling-back") return ["run", "Rolling back…", `${short(s.target)} failed: putting ${esc(s.running.tag || "the earlier version")} back.`];
    if (!s.relation) return ["bad", "The updater can't tell where AXoR stands", esc(s.error || "It hasn't reported a full check yet.")];
    if (s.relation === "current") return ["ok", "Up to date", `AXoR runs the newest commit on ${b}.`];
    if (s.relation === "behind") {
      if (s.failed && s.failed === latest) return ["bad", `The update to ${short(latest)} failed`, `${s.history?.[0]?.result === "blocked" ? "Its checks failed, so it was never deployed" : "It was rolled back"}, so AXoR still runs ${short(s.running.sha)}. The updater tries again when a newer commit lands on ${b}, or when you choose Update now. The log is below.`];
      if (s.paused) return ["wait", `Paused, ${plural(n, "commit")} waiting`, `Automatic updates are paused. Update now still deploys ${b}'s newest commit.`];
      return ["wait", `${plural(n, "commit")} to deploy`, `The updater deploys ${b}'s newest commit on its next pass, within a minute.`];
    }
    if (s.relation === "ahead") return ["wait", `Production is ${plural(s.ahead_count, "commit")} ahead of ${b}`, `It runs ${short(s.running.sha)}, deployed by hand from work ${b} doesn't include yet. Updates resume by themselves once ${b} includes it, for example when you merge it.`];
    if (s.relation === "diverged") return ["wait", `Production isn't on ${b}`, `It runs ${short(s.running.sha)}, which ${b}'s history doesn't contain (a deploy from another branch, or squash-merged). Updates resume once ${b} includes it, or deploy ${b} anyway.`];
    return ["wait", "Production runs a commit GitHub doesn't have", `It was deployed by hand (${esc(s.running.tag || "unknown version")}), probably from a working tree. Updates resume once ${b} includes that commit, or deploy ${b} anyway.`];
  }

  function render() {
    if (!el) return;
    if (s.error_page) return put(el, `<div class="empty">${esc(s.error_page)}</div>`);
    if (!s.installed) return put(el, `<section class="card k8-card"><h3>${icon("rocket")}Automatic updates are off</h3>
      <p class="muted">The updater runs on the k3s host and deploys each new commit on <code>main</code> by itself, rolling back if the update fails. To turn it on, run this as root in AXoR's folder:</p>
      <pre class="up-cmd">sudo ./k8s/auto-update.sh --install</pre><p class="faint">Add <code>--branch &lt;name&gt;</code> to follow another branch. Its settings live in <code>/etc/axor/auto-update.env</code>.</p></section>`);
    const [cls, title, text] = head(), b = esc(s.branch);
    const idle = s.activity === "idle", other = ["ahead", "diverged", "unknown"].includes(s.relation);
    const notes = [
      offline && ["info", "AXoR is restarting on the new version. Reconnecting…"],
      s.stale && !offline && ["alert", `The updater last reported ${since(s.checked)}. Is its timer running? On the host: <code>systemctl status axor-auto-update.timer</code>`, "warn"],
      s.request && ["clock", `Asked for ${s.request.kind === "check" ? "a check" : s.request.kind === "force" ? `a deploy of ${b} anyway` : "an update"}${s.request.by ? ` by ${esc(s.request.by)}` : ""}: the updater picks it up within a minute.`],
      s.error && s.relation && ["alert", esc(s.error), "warn"],
    ].filter(Boolean).map(([ic, t, c]) => `<div class="up-note ${c || ""}">${icon(ic)}<span>${t}</span></div>`).join("");
    const row = (k, v) => `<div class="kv-row"><span>${k}</span><b>${v}</b></div>`;
    const commit = c => c?.sha ? `${link(c.sha)} ${esc(c.subject || "")}${c.time ? ` <small class="faint">${since(c.time)}</small>` : ""}` : "–";
    const pending = s.pending.length ? `<section class="card k8-card k8-wide"><h3>${icon("commit")}${s.relation === "behind" ? "Waiting to deploy" : `On ${b}, not in production`} <span class="faint">${s.pending_count}</span></h3>
      <ul class="up-commits">${s.pending.map(c => `<li>${link(c.sha)}<span class="up-subj" title="${esc(c.subject)}">${esc(c.subject)}</span><small class="faint">${esc(c.author)} · ${since(c.time)}</small></li>`).join("")}</ul>
      ${s.pending_count > s.pending.length ? `<p class="faint">and ${s.pending_count - s.pending.length} older.</p>` : ""}</section>` : "";
    const hist = s.history.length ? `<div class="tablewrap flat"><table class="grid k8-table"><thead><tr><th>When</th><th>Commit</th><th>Result</th><th>Started by</th><th class="r">Took</th><th>Note</th></tr></thead><tbody>${s.history.map(r => {
      const [c, l] = RESULTS[r.result] || ["none", r.result];
      return `<tr><td class="num">${since(r.started)}</td><td>${r.sha ? link(r.sha) : "–"}</td><td><span class="ci-pill ci-${c}">${esc(l)}</span></td>
        <td>${who(r.by)}</td><td class="r num">${took(r)}</td><td class="up-notecell">${esc(r.note)}</td></tr>`;
    }).join("")}</tbody></table></div>` : `<p class="faint">No updates yet.</p>`;
    const open = logOpen ?? !idle;
    put(el, `<div class="k8-grid">
      <section class="card k8-card k8-wide up-head"><div class="up-state"><span class="ci ci-${cls}"></span><div><h3>${title}</h3><p class="muted">${text}</p></div></div>
        ${notes}
        <div class="row k8-btns"><button type="button" class="btn" data-up="check" ${s.request || !idle ? "disabled" : ""}>${icon("reset")}Check now</button>
          ${s.relation === "behind" && idle ? `<button type="button" class="btn primary" data-up="update">${icon("rocket")}Update now</button>` : ""}
          ${other && idle ? `<button type="button" class="btn" data-up="force">${icon("rocket")}Deploy ${b} anyway</button>` : ""}</div></section>
      <section class="card k8-card"><h3>${icon("branch")}Version</h3>
        ${row("Running", commit(s.running))}
        ${row("Image tag", s.running.tag ? `<code>${esc(s.running.tag)}</code>` : "–")}
        ${row(`Newest on ${b}`, commit(s.latest))}
        ${row("Following", `${s.repo ? `<code>${esc(s.repo)}</code> · ` : ""}<code>${b}</code>`)}
        ${row("Checked GitHub", `${since(s.fetched)} <small class="faint">every ${Math.round(s.check_every / 60) || 1} min</small>`)}</section>
      <section class="card k8-card"><h3>${icon("gear")}Automatic updates</h3>
        <label class="toggle-row"><span><b>Deploy new commits on ${b} by themselves</b><small class="faint">${s.paused ? "Paused: new commits wait until you resume, or choose Update now." : "On: the updater checks every few minutes."}</small></span>
          <span class="switch"><input type="checkbox" data-up="auto" ${s.paused ? "" : "checked"}><span></span></span></label>
        <p class="faint">Each update builds the images from a clean checkout of ${b}, rolls them out and checks that AXoR answers. If any step fails it rolls back to the version before, and that commit isn't tried again until a newer one lands. AXoR runs one pod, so it's unavailable for a few seconds while it restarts.</p>
        <p class="faint">Change the branch in <code>/etc/axor/auto-update.env</code> on the host.</p></section>
      ${pending}
      <section class="card k8-card k8-wide"><h3>${icon("clock")}Recent updates</h3>${hist}
        ${s.log ? `<details class="up-log" ${open ? "open" : ""}><summary>${idle ? "The last update's log" : "Live log"}</summary><pre class="dk-logs" tabindex="0">${esc(s.log)}</pre></details>` : ""}</section>
    </div>`);
    const pre = $(".up-log pre", el);
    if (pre && !idle) pre.scrollTop = pre.scrollHeight;  // follow the live log
  }

  // ---------- actions ----------
  async function act(b) {
    const a = b.dataset.up, br = esc(s.branch);
    if (a === "check") {
      b.disabled = true;
      try { s = await api("/api/cluster/updates/check", { method: "POST" }); Auth.toast("Asked: the updater checks GitHub within a minute"); load(); }
      catch (e) { b.disabled = false; err(e); }
    }
    if (a === "update") {
      return Auth.modal(`<h3>${icon("rocket")}Update AXoR to ${short(s.latest?.sha)}?</h3>
        <p class="muted">${plural(s.pending_count, "commit")} from ${br} go live. The updater builds and rolls out the new version within a minute or two, and rolls back if it fails. AXoR restarts, so this page reconnects.</p>`,
        async () => { $("#modal").close(); await send(false); }, { submit: "Update" });
    }
    if (a === "force") {
      const lose = s.relation === "unknown" ? "the changes in the version running now" : plural(s.ahead_count, "commit") + ` production has that ${br} doesn't`;
      return Auth.modal(`<h3>${icon("rocket")}Deploy ${br} anyway?</h3>
        <p class="muted">Production runs ${esc(s.running.tag || short(s.running.sha))}, which ${br} doesn't contain. Deploying ${short(s.latest?.sha)} from ${br} takes away ${lose} until they're in ${br}. After that, updates follow ${br} again.</p>`,
        async () => { $("#modal").close(); await send(true); }, { submit: `Deploy ${br}`, danger: true });
    }
  }
  async function send(force) {
    try { s = await withSudo(() => api("/api/cluster/updates/update", { method: "POST", body: { force } })); Auth.toast("Asked: the update starts within a minute"); load(); }
    catch (e) { err(e); }
  }
  async function auto(box) {
    const paused = !box.checked;
    try { s = await withSudo(() => api("/api/cluster/updates/settings", { method: "PUT", body: { paused } })); Auth.toast(paused ? "Automatic updates paused" : "Automatic updates on"); render(); }
    catch (e) { box.checked = !paused; err(e); }
  }

  function wire() {
    if (wired) return; wired = true;
    const v = $("#view-cluster");
    v.addEventListener("click", e => { const b = e.target.closest("button[data-up]"); if (b) act(b); });
    v.addEventListener("change", e => { if (e.target.dataset.up === "auto") auto(e.target); });
    v.addEventListener("toggle", e => { if (e.target.classList?.contains("up-log")) logOpen = e.target.open; }, true);
  }

  return { show };
})();
