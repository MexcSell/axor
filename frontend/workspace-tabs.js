/* My workspace as one page (the 11-07 evaluation: "Workspace home and My workspace should become one workspace"): the sidebar
   keeps one entry, My workspace; Workspace home (#home, hubs.js) becomes its Home tab, the subnets, notes and agents its second tab,
   and All files (file-catalog.js) its third. Every route stays: #home and #workspace still open, Ctrl+K still finds both, and
   My workspace shows as the current page on either. Styles in file-catalog.css (wst-). Loaded after app.js. */
(() => {
  const TABS = [["home", "home", "Home", "Notes, files, boards and study at a glance"], ["ws", "pickaxe", "Subnets & notes", "Your shortlist, briefs, notes and agents"],
                ["all", "layers", "All files", "Every file and work product AXoR keeps for you"]];
  const home = document.getElementById("view-home"), work = document.getElementById("view-workspace"), nav = document.getElementById("nav-ws");
  if (!home || !work || !nav) return;
  const current = () => !home.hidden ? "home" : typeof Workspace !== "undefined" && Workspace.tab?.() === "everywhere" ? "all" : "ws";
  function draw() {
    const sec = !home.hidden ? home : !work.hidden ? work : null;
    document.querySelectorAll(".wst").forEach(t => { if (t.parentElement !== sec) t.remove(); });
    if (!sec) return;
    let bar = sec.querySelector(":scope > .wst");
    if (!bar) {
      bar = document.createElement("nav"); bar.className = "wst"; bar.setAttribute("aria-label", "My workspace");
      sec.prepend(bar);
      bar.addEventListener("click", e => {
        const b = e.target.closest("[data-wst]"); if (!b) return;
        const k = b.dataset.wst;
        if (k === "home") return setView("home");
        Workspace.show(null, k === "all" ? "everywhere" : ["everywhere", "overview"].includes(Workspace.tab?.()) ? "brief" : Workspace.tab?.() || "brief");
      });
    }
    const cur = current();
    const html = TABS.map(([k, ic, l, tip]) => `<button type="button" data-wst="${k}" aria-current="${k === cur ? "page" : "false"}" title="${tip}">${icon(ic)}<span>${l}</span></button>`).join("");
    if (bar.dataset.html !== html) { bar.innerHTML = html; bar.dataset.html = html; }
    // the one sidebar entry is current on all three tabs (Workspace home's own entry is an alias now)
    if (sec === home) nav.setAttribute("aria-current", "page");
  }
  let f = 0;
  const later = () => { cancelAnimationFrame(f); f = requestAnimationFrame(draw); };
  const mo = new MutationObserver(later);
  mo.observe(home, { attributes: true, attributeFilter: ["hidden"] });
  mo.observe(work, { attributes: true, attributeFilter: ["hidden"] });
  const side = document.getElementById("ws-side"); if (side) new MutationObserver(later).observe(side, { childList: true });
  draw();
})();
