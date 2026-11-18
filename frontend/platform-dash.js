/* The Dashboard's platform parts (platform.css): under the title, which AXoR services are set up (/api/platform-status)
   and for administrators the latest audit events; at the end, every module you can open, grouped as in the sidebar with
   its counts. dashboard.js rebuilds #dash on every snapshot; both are kept nodes moved back in each time. */
const PlatformDash = (() => {
  let band = null, mods = null, act = null, seq = 0;
  const STATE = { ok: "Set up", warn: "Needs a look", down: "Down", pending: "Starting", off: "Not set up" };

  function services(st) {
    if (!st) return `<div class="plt-svc-grid">${Loading.line("Checking services…")}</div>`;
    const list = st.services, ok = list.filter(s => s.state === "ok").length;
    return `<div class="ws-card-head"><h3>${icon("server")}Services</h3><span class="faint small">${ok} of ${list.length} set up</span></div>
      <div class="plt-svc-grid">${list.map(s => {
        const b = $(`nav.side [data-view="${s.view}"]`), go = b && !b.hidden && !b.closest(".side-sec")?.hidden;
        return `<${go ? `button type="button" data-plt-go="${s.view}"` : "div"} class="plt-svc-i s-${s.state}" title="${esc(STATE[s.state] || s.state)}: ${esc(s.detail)}">
          <span class="plt-dot" aria-hidden="true"></span><span class="plt-svc-t"><b>${esc(s.label)}</b><small>${esc(s.detail)}</small></span></${go ? "button" : "div"}>`;
      }).join("")}</div>`;
  }
  function modules() {
    const groups = $$("nav.side .side-sec").filter(s => !s.hidden && s.dataset.sec !== "command").map(sec => {
      const pages = $$("button[data-view]", sec).filter(b => !b.hidden && !b.classList.contains("side-alias") && !b.closest(".side-sub")?.hidden);
      if (!pages.length) return "";
      return `<div class="plt-mod"><h4>${esc(sec.querySelector(".plt-gl")?.textContent || "")}</h4><div>${pages.map(b => {
        const c = b.querySelector(".count")?.textContent.trim(), alert = b.querySelector(".count.alert") && c;
        return `<button type="button" class="plt-mod-i" data-plt-go="${b.dataset.view}">${b.querySelector("svg")?.outerHTML || ""}<span>${esc(b.querySelector(".lbl")?.textContent.trim() || b.title)}</span>${c ? `<em class="${alert ? "alert" : ""}">${esc(c)}</em>` : ""}</button>`;
      }).join("")}</div></div>`;
    }).join("");
    return `<div class="ws-card-head"><h3>${icon("apps")}All modules</h3><button type="button" class="linkbtn" data-plt-pal>Search all <kbd>Ctrl K</kbd></button></div><div class="plt-mods">${groups}</div>`;
  }
  function activity(rows) {
    const nice = a => a.replace(/[._]/g, " ").replace(/^./, c => c.toUpperCase());
    return `<div class="ws-card-head"><h3>${icon("clock")}Recent activity</h3><button type="button" class="linkbtn" data-plt-audit>Audit log</button></div>
      ${rows == null ? Loading.line("Loading the audit log…") : rows.length ? `<ul class="plt-act">${rows.map(r => `<li><span class="num faint" title="${new Date(r.ts * 1000).toLocaleString()}">${ago(r.ts)}</span>
        <span><b>${esc(nice(r.action))}</b> <span class="faint">by</span> ${esc(r.actor || "–")}${r.target && r.target !== r.actor ? ` <span class="faint">on</span> ${esc(r.target)}` : ""}</span></li>`).join("")}</ul>` : `<p class="faint">No events yet.</p>`}`;
  }
  function paint(st) {
    if (!band) return;
    const admin = Auth.me()?.role === "admin";
    band.classList.toggle("with-act", admin);
    band.innerHTML = `<div class="card plt-svc">${services(st)}</div>${admin ? `<div class="card plt-actc">${activity(act)}</div>` : ""}`;
    mods.innerHTML = modules();
  }
  function place() {
    const top = $("#dash .dash-top"), grid = $("#dash .dash-grid");
    if (top && band && top.nextElementSibling !== band) top.after(band);
    if (grid && mods && grid.nextElementSibling !== mods) grid.after(mods);
  }
  async function open() {
    if (!Auth.me()) return;
    if (!band) {
      band = document.createElement("section"); band.className = "plt-dash"; band.id = "plt-dash"; band.setAttribute("aria-label", "Platform");
      mods = document.createElement("section"); mods.className = "card plt-modc"; mods.setAttribute("aria-label", "All modules");
      const click = e => {
        const g = e.target.closest("[data-plt-go]"); if (g) return setView(g.dataset.pltGo);
        if (e.target.closest("[data-plt-pal]")) return Platform.open();
        if (e.target.closest("[data-plt-audit]")) return Platform.audit();
      };
      band.addEventListener("click", click); mods.addEventListener("click", click);
      new MutationObserver(place).observe($("#dash"), { childList: true });
    }
    const s = ++seq;
    paint(Platform.statusNow()); place();
    const [st, rows] = await Promise.all([Platform.status(), Auth.me()?.role === "admin" ? api("/api/admin/audit?limit=6").catch(() => []) : null]);
    if (s !== seq) return;
    act = rows; paint(st); place();
  }
  return { open };
})();
