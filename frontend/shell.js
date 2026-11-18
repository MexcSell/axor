/* AXoR application shell (shell.css; prefix axs-), the AgentForge-style frame around every page:
   - the sidebar's seven sections (index.html) and its links into My subnets screens (Live operations, Performance lab,
     Experiments, Miner performance, Rewards & costs): buttons with data-axn = a MiningShell route, shown only while the page
     they open (data-of) may be opened, and listed in the command palette like any page
   - the search in the middle of the top bar, the signed-in user's name beside the avatar
   - one health line at the foot of the sidebar (the chain and AXoR's set-up services; "not set up" isn't unhealthy)
   - the status bar along the bottom for everyone: version, chain, agents, projects and approvals waiting, with the
     server's meters after them for administrators (system.js draws those into #sb-sys)
   Counts come from /api/studio (agents across every system), /api/command (approvals, projects) and /api/platform-status;
   nothing is illustrative, and a count that can't be read is left out. */
const Shell = (() => {
  const EVERY = 60000;
  let me = null, studio = null, timer = null, wired = false, ver = "";
  const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;

  // ---------- the sidebar's links into My subnets ----------
  function links() {
    const sync = () => $$("nav.side .axs-go").forEach(b => { const of = $("#" + b.dataset.of), h = !of || of.hidden; if (b.hidden !== h) b.hidden = h; });
    sync();
    $$("nav.side [data-of]").map(b => b.dataset.of).filter((x, i, a) => a.indexOf(x) === i).forEach(id => {
      const of = $("#" + id); if (of) new MutationObserver(sync).observe(of, { attributes: true, attributeFilter: ["hidden"] });
    });
    $("#side").addEventListener("click", e => {
      const b = e.target.closest(".axs-go"); if (!b) return;
      go(b);
    });
  }
  function go(b) {
    let r; try { r = JSON.parse(b.dataset.axn); } catch { return; }
    $$("nav.side .axs-go.axs-cur").forEach(x => x.classList.remove("axs-cur"));
    b.classList.add("axs-cur");
    if (innerWidth <= 900) sideOpen(false);
    MiningShell.go(r);
  }
  const entries = () => $$("nav.side .axs-go").filter(b => !b.hidden).map(b => ({ name: b.querySelector(".lbl").textContent.trim(), group: b.closest(".side-sec")?.querySelector(".plt-gl")?.textContent || "",
    ico: b.querySelector("svg")?.outerHTML || icon("grid"), title: b.title, run: () => go(b) }));

  // ---------- a page head for the pages whose module draws no title (design.css .axd-ph) ----------
  // Placed before the module's root inside the view's section, so the module's redraws leave it alone. The title is the
  // sidebar's label, the eyebrow its section.
  const HEADS = {
    wallet: "Your Bittensor wallets, tracked by public address: balances, stake and registrations. Send, Stake and Move are signed in your browser wallet.",
    slack: "Your team's Slack channel: read and post messages and threads, and share subnets, notes and notifications into it.",
    drive: "AXoR Drive: your private and shared files and folders, share links and the trash.",
    source: "Your team's GitHub repositories: branches, commits with their CI status, code, pull requests, workflow runs and deployments.",
    study: "Learning tracks with a roadmap, topics to tick off, practice drills, a code lab and study tutors.",
    explore: "Every subnet on the chain: what its miners do, what they earn, open UIDs and risk flags. Search, filter, sort and export to CSV.",
    workspace: "Your shortlist of subnets, each with a mining brief, with the notes, files, agents and project team that work on it.",
  };
  function heads() {
    Object.entries(HEADS).forEach(([v, lead]) => {
      const sec = $("#view-" + v), b = $(`nav.side button[data-view="${v}"]`);
      if (!sec || !b || sec.querySelector(":scope > .axd-ph")) return;
      const k = b.closest(".side-sec")?.querySelector(".plt-gl")?.textContent || "";
      const h = document.createElement("header");
      h.className = "axd-ph";
      h.innerHTML = `<div>${k ? `<p class="axd-ph-k">${b.querySelector("svg")?.outerHTML || ""}${esc(k)}</p>` : ""}<h1 class="page">${esc(b.querySelector(".lbl").textContent.trim())}</h1><p class="lead">${esc(lead)}</p></div>`;
      sec.prepend(h);
    });
  }

  // ---------- recently visited pages, listed first in the command palette ----------
  function visit(v) {
    if (!v || !$(`nav.side button[data-view="${v}"]`)) return;
    store.set("axs.recent", [v, ...store.get("axs.recent", []).filter(x => x !== v)].slice(0, 6));
  }
  const recent = () => store.get("axs.recent", []).filter(v => v !== S.view);

  // ---------- top bar ----------
  function chrome() {
    const s = $("#plt-search");
    if (s && !$(".axs-mid")) { const mid = document.createElement("div"); mid.className = "axs-mid"; $(".top-right").before(mid); mid.appendChild(s); s.querySelector("span").textContent = "Search anything in AXoR…"; }
    if (!$("#axs-who")) {
      const w = document.createElement("button");
      w.type = "button"; w.id = "axs-who"; w.className = "axs-who"; w.setAttribute("aria-label", "Account menu");
      w.onclick = e => { e.stopPropagation(); $("#account").click(); };
      $("#account").after(w);
    }
    who();
  }
  function who() {
    const w = $("#axs-who"); if (!w) return;
    w.hidden = !me;
    if (me) { w.innerHTML = `<b>${esc(me.username)}</b><small>${me.role === "admin" ? "Administrator" : "Member"}</small>${icon("chev")}`; w.title = `Signed in as ${me.username}`; }
  }

  // ---------- health: the chain and the services that are set up ----------
  function health(st) {
    const ch = S.data, err = ch?.status?.startsWith?.("error");
    const svc = (st?.services || []).filter(s => s.state !== "off" && s.key !== "chain");
    const bad = svc.filter(s => s.state === "down" || s.state === "warn");
    const chain = err ? "down" : ch?.block ? "ok" : "pending";
    const level = chain === "down" || bad.some(s => s.state === "down") ? "down" : bad.length || chain === "pending" ? "warn" : "ok";
    const plat = chain === "down" ? "Chain unreachable" : bad.length ? `${plural(bad.length, "service")} need${bad.length === 1 ? "s" : ""} a look`
      : chain === "pending" ? "Connecting to the chain" : "Platform up";
    // availability is one thing, the work another: runs failing now (last hour) change the line; history and missions go in the tip
    const w = st?.work, now = w?.failing_now || 0;
    const text = now ? `${plat} · ${plural(now, "run")} failing now` : plat;
    const lvl = level === "ok" && now ? "warn" : level;
    const tip = [`Platform availability: ${plat}`, `Chain: ${err ? "can't be reached" : ch?.block ? `live, block ${ch.block.toLocaleString()}` : "connecting"}`,
                 ...svc.map(s => `${s.label}: ${s.detail}`), (st?.services || []).some(s => s.state === "off") ? `Not set up: ${st.services.filter(s => s.state === "off").map(s => s.label).join(", ")}` : "",
                 w ? `Failing now (last hour): ${now}` : "", w ? `Failed in 24 hours: ${w.failed_24h}${w.restarted_24h ? ` (${w.restarted_24h} cut off by a restart)` : ""}${w.success_pct != null ? ` · ${w.success_pct}% of finished runs succeeded (execution, not verified results)` : ""}` : "",
                 w && w.missions_going != null ? `Missions: ${w.missions_going} going, ${w.missions_held} waiting on a decision or paused` : ""].filter(Boolean).join("\n");
    return { level: lvl, text, tip, up: svc.filter(s => s.state === "ok").length, of: svc.length };
  }
  function foot(h) {
    let b = $("#axs-health");
    if (!b) {
      b = document.createElement("button");
      b.type = "button"; b.id = "axs-health"; b.className = "axs-health";
      b.onclick = () => setView(me?.role === "admin" && !$("#nav-infra").hidden ? "infra" : "command");
      $(".side-foot").prepend(b);
    }
    b.hidden = !me;
    b.className = `axs-health s-${h.level}`; b.title = h.tip;
    b.innerHTML = `<span class="plt-dot"></span><span class="lbl">${esc(h.text)}</span>`;
  }

  // ---------- the status bar ----------
  function bar(h) {
    const sb = $("#statusbar"), app = $("#sb-app"); if (!sb || !app) return;
    const on = !!me;
    if (sb.hidden === on) { sb.hidden = !on; document.body.classList.toggle("has-sb", on); }
    if (!on) return;
    const c = Command.data(), ch = S.data;
    const items = [
      studio && `<button type="button" class="sb-it" data-axs-to="studio" title="Agents across every AXoR system"><b class="num">${studio.counts.agents.toLocaleString()}</b><span>agents registered</span> <span class="${studio.counts.working ? "axs-sb-live" : ""}">${studio.counts.working || 0} running</span></button>`,
      c?.org?.company && `<button type="button" class="sb-it" data-axs-to="projects" title="Company projects that aren't archived"><b class="num">${c.org.company.projects}</b><span>project${c.org.company.projects === 1 ? "" : "s"}</span></button>`,
      c && `<button type="button" class="sb-it ${c.counts.pending ? "lv-warn" : ""}" data-axs-to="approvals" title="Requests waiting for your decision"><b class="num">${c.counts.pending}</b><span>pending approval${c.counts.pending === 1 ? "" : "s"}</span></button>`,
    ].filter(Boolean);
    app.innerHTML = `<span class="axs-sb-ver" title="AXoR version">AXoR${ver ? ` v${esc(ver)}` : ""}</span><span class="axs-sb-by">Adaptive Agent Company OS</span>
      <button type="button" class="sb-it axs-sb-h s-${h.level}" data-axs-to="command" title="${esc(h.tip)}"><span class="plt-dot"></span><span>${esc(h.text)}</span></button>
      ${ch?.block ? `<span class="sb-it minor" title="Bittensor ecosystem: the chain's latest block (not AXoR's health)"><span>Bittensor block</span><b class="num">${ch.block.toLocaleString()}</b></span>` : ""}
      ${items.length ? `<span class="axs-sb-sep"></span>${items.join("")}` : ""}`;
  }

  async function refresh() {
    if (!me || document.hidden) return;
    const [st, so] = await Promise.all([Platform.status(), $("#tab-studio").hidden ? null : api("/api/studio").catch(() => null)]);
    if (so) studio = so;
    paint(st);
  }
  function paint(st = Platform.statusNow()) {
    if (!me) return;
    const h = health(st);
    foot(h); bar(h);
  }

  function wire() {
    if (wired) return; wired = true;
    $("#statusbar").addEventListener("click", e => { const t = e.target.closest("[data-axs-to]"); if (t) setView(t.dataset.axsTo); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  }
  async function init() {
    me = Auth.me();
    links(); chrome(); heads(); wire();
    if (!me) return;
    try { ver = (await api("/api/health")).version || ""; } catch {}
    refresh();
    clearInterval(timer); timer = setInterval(refresh, EVERY);
  }
  // the chain's state changes the health line; called by app.js when new chain data arrives and on every page change
  function onView(v) {
    if (v !== "mining") $$("nav.side .axs-go.axs-cur").forEach(x => x.classList.remove("axs-cur"));
    if (me) visit(v);
    paint();
  }
  return { init, onView, paint, entries, recent, studio: () => studio };
})();
