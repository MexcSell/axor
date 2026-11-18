/* AXoR sidebar frame (sidebar.css; prefix sdb-), after the "AXoR Mission Control Sidebar" mock-up (ChatGPT /s/m_6aee3f27…):
   - the brand at the top of the sidebar ("AXoR · Agent Company OS") with the pin: pinned keeps the sidebar open, unpinned folds
     it to icons (it is app.js's #side-collapse, moved here, so its shortcut "[" and remembered state are unchanged)
   - no search or + New in the sidebar (removed 11-10 at the user's request): search is Ctrl/⌘ K only
   - an icon before each section's name (Platform.sections() draws the header text, so this runs after Platform.init())
   - Primary initiative → Bittensor (formerly Ecosystems, moved up under Control Hub on 11-08): a tree that folds (remembered)
   - the foot: AXoR's version beside Shell's health line ("System online")
   - the sidebar runs the full height of the window on wide screens: the top bar starts beside it (--sdb-top = its height)
   Every page keeps its button, id and route in index.html; this only frames them. */
Object.assign(ICONS, {
  home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5.5h4V20"/>',
  building: '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M9.5 21v-3.5h5V21"/><path d="M8.5 7h1M14.5 7h1M8.5 10.5h1M14.5 10.5h1M8.5 14h1M14.5 14h1"/>',
  sitemap: '<rect x="9" y="2.5" width="6" height="5" rx="1"/><rect x="2.5" y="16.5" width="6" height="5" rx="1"/><rect x="15.5" y="16.5" width="6" height="5" rx="1"/><path d="M12 7.5v4.5M5.5 16.5V12h13v4.5"/>',
  brain: '<path d="M12 5.5a3 3 0 0 0-5.6-1.4A3.5 3.5 0 0 0 4 9.6a3.6 3.6 0 0 0 .8 6.2A3.5 3.5 0 0 0 9 20.5a3 3 0 0 0 3-2.2"/><path d="M12 5.5a3 3 0 0 1 5.6-1.4A3.5 3.5 0 0 1 20 9.6a3.6 3.6 0 0 1-.8 6.2 3.5 3.5 0 0 1-4.2 4.7 3 3 0 0 1-3-2.2"/><path d="M12 5.5v12.8M8.5 9.5a2.5 2.5 0 0 0 3.5 0M12 13a2.5 2.5 0 0 1 3.5 0"/>',
  nodes: '<circle cx="5" cy="5" r="2.3"/><circle cx="19" cy="5" r="2.3"/><circle cx="5" cy="19" r="2.3"/><circle cx="19" cy="19" r="2.3"/><circle cx="12" cy="12" r="2.3"/><path d="m6.7 6.7 3.6 3.6M17.3 6.7l-3.6 3.6M6.7 17.3l3.6-3.6M17.3 17.3l-3.6-3.6"/>',
  compass: '<circle cx="12" cy="12" r="9"/><path d="m15.8 8.2-2.3 5.3-5.3 2.3 2.3-5.3z"/>',
  database: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13"/><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
});

const Sidebar = (() => {
  // the icon before each section's name (data-sec in index.html)
  const SEC = { command: "grid", projects: "target", org: "sitemap", agents: "users", knowledge: "layers", intel: "brain", eco: "nodes", workspace: "folder", system: "gear" };
  let wired = false, ver = "";
  const side = () => $("#side");

  function init() {
    if (wired) return; wired = true;
    head(); sections(); tree(); foot(); layout();
  }

  // ---------- brand and pin ----------
  function head() {
    const h = document.createElement("div");
    h.className = "sdb-head";
    h.innerHTML = `<div class="sdb-brand">
        <button type="button" class="sdb-home" title="Home" aria-label="AXoR home"><span class="mark sdb-mark"><img class="logo-light" src="/static/brand/logo-light-96.png" alt=""><img class="logo-dark" src="/static/brand/logo-dark-96.png" alt=""></span>
          <span class="sdb-name"><b>AXoR</b><small>Adaptive Agent Company OS</small></span></button>
      </div>`;
    side().prepend(h);
    // the pin is the old Collapse button: same id, click handler (app.js) and keyboard shortcut
    const pin = $("#side-collapse");
    if (pin) {
      pin.classList.add("sdb-pin");
      pin.innerHTML = icon("pin");
      $(".sdb-brand", h).append(pin);
      const sync = () => {
        const folded = side().classList.contains("collapsed");
        pin.setAttribute("aria-pressed", String(!folded));
        pin.title = folded ? "Pin the sidebar open" : "Unpin: fold the sidebar to icons";
        pin.setAttribute("aria-label", pin.title);
      };
      new MutationObserver(sync).observe(side(), { attributes: true, attributeFilter: ["class"] });
      sync();
    }
    $("#plt-side-search")?.remove();  // platform.js's phone search: the sidebar has no search row any more
    $(".sdb-home", h).onclick = () => {
      const v = typeof MissionOS !== "undefined" && MissionOS.landing ? MissionOS.landing() : "command";
      setView(Auth.me() ? v : "explore");
    };
  }

  // ---------- section icons ----------
  function sections() {
    $$("nav.side .side-sec").forEach(sec => {
      const h = sec.querySelector(":scope > .side-group"), ic = SEC[sec.dataset.sec];
      if (!h || !ic || h.querySelector(".sdb-ic")) return;
      h.insertAdjacentHTML("afterbegin", icon(ic, "sdb-ic"));
    });
  }

  // ---------- Primary initiative → Bittensor ----------
  function tree() {
    $$("nav.side .sdb-tog").forEach(t => {
      const sub = t.closest(".sdb-tree"), key = "sdb.fold." + (sub.dataset.sub || "");
      const label = t.textContent.trim();
      t.innerHTML = `${icon("chev", "sdb-chev")}${icon("nodes", "sdb-ic")}<span>${esc(label)}</span>`;
      const set = shut => { sub.classList.toggle("sdb-shut", shut); t.setAttribute("aria-expanded", String(!shut)); t.setAttribute("aria-label", `${shut ? "Expand" : "Collapse"} ${label}`); };
      set(!!store.get(key, false));
      const flip = () => { if (side().classList.contains("collapsed") && innerWidth > 900) return; set(!sub.classList.contains("sdb-shut")); store.set(key, sub.classList.contains("sdb-shut")); };
      t.onclick = flip;
      t.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(); } };
    });
    // Mining HQ and My Subnets open the same page: only the one clicked shows as current
    const sync = () => side().classList.toggle("sdb-mhq-on", !!$("nav.side .sdb-mhq.axs-cur"));
    new MutationObserver(sync).observe($("nav.side .sdb-kids") || side(), { subtree: true, attributes: true, attributeFilter: ["class", "aria-current"] });
    side().addEventListener("click", e => { if (e.target.closest("button[data-view]")) $$("nav.side .axs-go.axs-cur").forEach(x => x.classList.remove("axs-cur")); });
  }

  // ---------- foot: version + health ----------
  function foot() {
    const f = $("nav.side .side-foot"); if (!f) return;
    const v = document.createElement("a");  // 5.1: the version links to the React front end (/app: Stack & migration, Analytics, Activity)
    v.className = "sdb-ver"; v.id = "sdb-ver"; v.textContent = "AXoR"; v.href = "/app";
    v.style.color = "inherit"; v.style.textDecoration = "none";
    f.prepend(v);
    fetch("/api/health", { credentials: "same-origin" }).then(r => r.ok ? r.json() : null).then(j => {
      ver = j?.version ? String(j.version) : "";
      v.textContent = ver ? `AXoR v${ver}` : "AXoR";
      v.title = ver ? `AXoR version ${ver}: the stack, the migration and the React pages` : "";
    }).catch(() => {});
  }

  // ---------- full-height sidebar: the top bar's height, for its overlap ----------
  function layout() {
    const top = $("header.top"); if (!top) return;
    const set = () => document.documentElement.style.setProperty("--sdb-top", top.offsetHeight + "px");
    set();
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(set).observe(top);
  }

  return { init, close, version: () => ver };
})();
