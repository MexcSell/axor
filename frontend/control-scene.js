/* Control Hub scene (D-028; control-scene.css, prefix ctl-sc-): the Control Hub's Overview drawn as the AXoR command-room mock-up:
   a holographic hub (the AXoR core, its orbit of systems, the world wall, the dome rings, flowing links and chevrons), the
   Mona Lisa at the console (brand/scene-portrait.webp, built by tools/scene-portrait.py), and four glass panels, a rail and the
   mission path over it.
   - Presentation only: no new view, route, table or endpoint. It reads /api/control (control.js passes its answer) and
     /api/control/ops (the Mission operations console's answer) and every figure on it comes from them, as on the Command Center.
     Mission health = the share of active missions (competitions and custom missions, paused ones left out) that are on track or
     met; with no active mission it says so and shows agent run success instead, labelled as such.
   - Every link presses the real sidebar button (or a Control Hub section), so access and the Sidebar layout still decide what
     a person can open; an orbit system they can't open stays drawn but inert.
   - "Dashboard" (top right of the scene) switches back to the Command Center cards and "Scene" on the Command Center returns;
     the choice is per device (localStorage ctl.scene).
   - Lifecycle (control.js): view() → draw() → after() mounts once; the 20 s poll calls update(), which patches the panels in
     place so the animations never restart; leave() on any other section, node or page. While mounted on a wide screen the
     sidebar folds to icons (restored on leave unless the person pinned it themselves) and the global backdrop rests.
   - Motion: CSS + SMIL, paused while the tab is hidden; reduced motion holds a still frame. */
const CtlScene = (() => {
  const W = 1672, H = 941;
  const OPS = "/api/control/ops";
  let ops = null, opsBusy = false, hub = null, el = null, ro = null, autoFold = false, flow = null, onVis = null, onPin = null;
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const S_ = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("ctl." + k)); localStorage.setItem("ctl." + k, JSON.stringify(v)); } catch { return null; } };
  // peek: a readiness row opened the Dashboard for a look; the saved choice stays, and the scene comes back on ✦, another area or leaving
  let peek = false, toGate = false;
  const wanted = () => !peek && S_("scene") !== false;
  const e_ = s => (typeof esc === "function" ? esc(String(s ?? "")) : String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`));
  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  const clamp = v => Math.max(0, Math.min(100, v || 0));
  const tok = n => n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(n);
  const $ = s => document.querySelector(s);
  const usable = sel => { const b = $(sel); return !!b && !b.hidden && !b.closest(".side-sec")?.hidden && !b.classList.contains("sbl-out"); };
  const firstUsable = sels => sels.find(usable) || null;

  // ---------- icons (24 × 24, stroked) ----------
  const P = {
    home: `<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h5v-5.5h3V20h5V9.5"/>`,
    missions: `<circle cx="12" cy="12" r="8.6"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/>`,
    topology: `<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="18.5" r="2.2"/><circle cx="19" cy="18.5" r="2.2"/><path d="M11 7 6 16.6M13 7l5 9.6M7.2 18.5h9.6"/>`,
    layers: `<path d="M12 3.5 21 8l-9 4.5L3 8z"/><path d="M3 12l9 4.5 9-4.5"/><path d="M3 16l9 4.5 9-4.5"/>`,
    pulse: `<path d="M2 12.5h4.2l2.3-5.5 3.6 11 2.8-8 1.7 2.5H22"/><path d="M17.5 4.5l.8 1.7 1.7.8-1.7.8-.8 1.7-.8-1.7-1.7-.8 1.7-.8z"/>`,
    shield: `<path d="M12 2.8 19.5 6v5.8c0 4.7-3.2 7.9-7.5 9.4-4.3-1.5-7.5-4.7-7.5-9.4V6z"/><path d="m8.6 12 2.4 2.4 4.6-4.8"/>`,
    team: `<circle cx="12" cy="8.2" r="2.8"/><circle cx="5.6" cy="10" r="2.1"/><circle cx="18.4" cy="10" r="2.1"/><path d="M7 19c0-3 2.2-5.2 5-5.2s5 2.2 5 5.2"/><path d="M2.4 18.2c0-2.2 1.4-3.8 3.4-3.8M21.6 18.2c0-2.2-1.4-3.8-3.4-3.8"/>`,
    chip: `<rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/><path d="M10 10h4v4h-4zM9 3v3.5M12 3v3.5M15 3v3.5M9 17.5V21M12 17.5V21M15 17.5V21M3 9h3.5M3 12h3.5M3 15h3.5M17.5 9H21M17.5 12H21M17.5 15H21"/>`,
    gear: `<circle cx="12" cy="12" r="3"/><path d="M12 2.5v2.6M12 18.9v2.6M4.6 4.6l1.9 1.9M17.5 17.5l1.9 1.9M2.5 12h2.6M18.9 12h2.6M4.6 19.4l1.9-1.9M17.5 6.5l1.9-1.9"/><circle cx="12" cy="12" r="6.4"/>`,
    atom: `<circle cx="12" cy="12" r="1.7" fill="currentColor"/><ellipse cx="12" cy="12" rx="9.5" ry="3.8"/><ellipse cx="12" cy="12" rx="9.5" ry="3.8" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9.5" ry="3.8" transform="rotate(120 12 12)"/>`,
    code: `<path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.8 4.5l-3.6 15"/>`,
    database: `<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8v-13M4.5 12c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8"/>`,
    bars: `<path d="M5 20v-5M10 20v-9M15 20v-6M20 20V6" stroke-width="2.6"/>`,
    analytics: `<path d="M3.5 20.5h17"/><rect x="5" y="13" width="3" height="5"/><rect x="10.5" y="10" width="3" height="8"/><rect x="16" y="7" width="3" height="11"/><path d="m4.5 10 5-4.5 3.5 2.5 6.5-5"/>`,
    target: `<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.4"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/>`,
    cube: `<path d="M12 2.8 20.5 7.4v9.2L12 21.2l-8.5-4.6V7.4z"/><path d="m3.5 7.4 8.5 4.6 8.5-4.6M12 12v9.2"/><path d="m8 5 8.4 4.6" opacity=".6"/>`,
    network: `<circle cx="12" cy="13" r="2"/><circle cx="12" cy="4" r="1.6"/><circle cx="4" cy="18.5" r="1.6"/><circle cx="20" cy="18.5" r="1.6"/><circle cx="4.5" cy="9" r="1.4"/><circle cx="19.5" cy="9" r="1.4"/><path d="M12 11V5.6M10.4 14.2l-5 3.4M13.6 14.2l5 3.4M10.2 12.2 5.8 9.7M13.8 12.2l4.4-2.5"/>`,
    rocket: `<path d="M12.5 3.2c3.6 1.7 5.6 5.2 5.4 9.2l-2.8 2.9h-4.8L7.5 12.4c-.2-4 1.4-7.4 5-9.2z"/><circle cx="12.7" cy="9.3" r="1.6"/><path d="M7.4 12.5 4.5 14l1.4 2.6 2.7-.6M17.8 12.5l2.9 1.5-1.4 2.6-2.7-.6M10.3 17.5l-2.8 3.3M13.2 18l-.9 3.2"/>`,
    search: `<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.4 15.4 5.1 5.1"/>`,
    bell: `<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.6 2H4.4z"/><path d="M10 20.5a2.1 2.1 0 0 0 4 0"/>`,
    play: `<path d="M7 4.5v15l12-7.5z"/>`,
    bolt: `<path d="M13.2 2.5 5 13.6h6.2l-1.2 7.9 8.4-11.3h-6.3z"/>`,
    agents: `<circle cx="12" cy="7" r="3"/><path d="M6.5 19.5c0-3.2 2.4-5.6 5.5-5.6s5.5 2.4 5.5 5.6"/><circle cx="4.5" cy="16" r="1.3"/><circle cx="19.5" cy="16" r="1.3"/><path d="M5.6 15.2 8 13.5M18.4 15.2 16 13.5"/>`,
    globebrain: `<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2M12 3.4c2.8 2.6 2.8 14.6 0 17.2M12 3.4c-2.8 2.6-2.8 14.6 0 17.2M5 7.5h14M5 16.5h14"/>`,
    doc: `<path d="M6 2.8h8.5l3.5 3.5v14.9H6z"/><path d="M14.5 2.8v3.5H18M8.8 11h6.4M8.8 14.2h6.4M8.8 17.4h4"/>`,
    stack: `<rect x="4" y="3.5" width="16" height="5" rx="1"/><rect x="4" y="9.5" width="16" height="5" rx="1"/><rect x="4" y="15.5" width="16" height="5" rx="1"/><path d="M7 6h2M7 12h2M7 18h2"/>`,
    radar: `<circle cx="12" cy="12" r="8.6"/><circle cx="12" cy="12" r="4.4"/><path d="M12 12l6-6"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/>`,
    poly: `<path d="M12 3 20 8v8l-8 5-8-5V8z"/><path d="M12 3v18M4 8l16 8M20 8 4 16"/>`,
    chev: `<path d="m9 5 7 7-7 7"/>`,
    dash: `<rect x="3" y="3" width="7.5" height="9" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="5.5" rx="1.5"/><rect x="13.5" y="11.5" width="7.5" height="9.5" rx="1.5"/><rect x="3" y="15" width="7.5" height="6" rx="1.5"/>`,
    spark: `<path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z"/>`,
  };
  const ic = (k, cls = "") => `<svg class="ctl-sc-i ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[k] || ""}</svg>`;
  // the same icon inside the stage's own SVG (x, y = centre, s = size)
  const gi = (k, x, y, s = 26) => `<g transform="translate(${x - s / 2} ${y - s / 2}) scale(${s / 24})" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${P[k] || ""}</g>`;
  // the AXoR "A" mark of the mock-up (blade + wedge)
  const MARK = `<path d="M11.2 1.4 15.8 9.8 13.3 11.9 10.8 7.4 5.4 21.6H1.5z"/><path d="M14.3 13.1 17.7 11.1 22.5 21.6H9.1l2.4-3h5.2z"/>`;

  // ---------- where things lead (the real sidebar buttons; access rules stay theirs) ----------
  const RAIL = [
    ["home", "Control Hub", null],
    ["missions", "Missions", ["#nav-mos"], "missions"],
    ["topology", "Agent Topology", ["#nav-topology"]],
    ["layers", "Knowledge Hub", ["#nav-knowledge", "#nav-myknowledge"]],
    ["pulse", "Intelligence", ["#nav-layers", "#nav-dash", "#nav-tech", "#nav-analytics"]],
    ["shield", "Governance", ["#nav-governance"], "approvals"],
  ];
  // orbit systems around the core: [icon, x, y, label, sidebar buttons | a Control Hub section]
  const ORBIT = [
    ["team", 885, 245, "Organization", ["#nav-org"], "org"],
    ["shield", 672, 290, "Governance", ["#nav-governance"], "approvals"],
    ["chip", 1097, 290, "Intelligence layers", ["#nav-layers"]],
    ["gear", 543, 355, "Workforce", ["#tab-agents", "#nav-workforce"], "agents"],
    ["code", 1226, 350, "Developer", ["#nav-developer"]],
    ["atom", 535, 430, "Agent marketplace", ["#nav-market", "#tab-agents"]],
    ["database", 1236, 430, "Drive", ["#nav-drive", "#nav-myknowledge"]],
    ["layers", 395, 452, "Knowledge Hub", ["#nav-knowledge"]],
    ["target", 1387, 455, "Mission Control", ["#nav-mos"], "missions"],
    ["bars", 575, 515, "Analytics", ["#nav-analytics"], "performance"],
    ["analytics", 1197, 515, "Benchmarks & evaluations", ["#nav-evaluation"], "performance"],
  ];
  // the mission path: the Mission operations console's five path states (every task of every engine)
  const PATH = [["target", "PLANNED", "Planned"], ["cube", "READY", "Ready"], ["network", "RUNNING", "Running"], ["layers", "REVIEW", "Review"], ["shield", "VERIFIED", "Verified"]];
  const PATH_X = [681, 826, 978, 1124, 1278];
  const linkAttr = (sels, sec) => {
    const b = sels && firstUsable(sels);
    if (b) return `data-sc-nav="${e_(b)}"`;
    if (sec === "org") return `data-go="org"`;
    if (sec) return `data-sec="${sec}"`;
    return "";
  };

  // ---------- the world wall: Natural Earth 110 m land (public domain, via world-atlas), 110 × 44 dots, run-length coded ----------
  const MAP = "2b.4.3f|19.8.1.g.a.3.6.1.d.2.19|12.2.1.1.3.2.2.1.1.3.2.10.1a.1.a.1.a.3.15|11.3.2.1.1.1.1.1.1.3.7.b.16.1.8.b.2.1.4.1.b|5.6.8.5.1.2.2.5.4.a.d.3.b.2.1.2.1.1a.6|1.1.1.38.9.1.8.1.20|2.1.3.15.1.1.1.2.2.4.4.6.1.8.3.1.30|5.15.5.3.7.1.f.4.1.1.1.26.2.2.4|e.e.4.4.11.1.5.1.25.5.2.5|e.10.1.7.e.1.1.2.29.5.1.6|10.16.f.1.1.2c.b|11.10.1.1.3.1.f.2b.1.1.b|11.11.14.3.1.1.1.4.3.2.2.19.2.1.b|11.10.13.3.2.1.1.1.1.7.1.18.f|12.e.14.3.4.1.3.7.1.15.2.1.2.1.c|13.c.16.5.8.1a.4.1.d|14.a.16.28.12|14.5.5.1.14.e.1.4.1.15.12|16.3.19.10.1.6.3.f.13|17.2.2.2.2.1.12.10.1.6.4.5.1.6.15|18.4.16.11.1.4.5.3.4.4.16|1b.3.14.14.8.2.5.3.4.1.11|1d.1.2.2.10.12.1.2.7.1.8.1.3.2.11|1e.7.e.13.9.1.5.1.6.2.10|1f.8.13.c.e.1.1.1.3.1.13|1f.9.12.a.11.1.2.3.1.1.11|1e.b.11.9.13.1.2.3.5.1.c|1e.e.f.8.1e.4.9|1f.d.f.8.1a.1.4.1.b|1f.d.f.8.1c.2.1.1.b|20.b.10.8.2.1.17.4.1.1.b|21.a.10.7.2.2.16.8.a|22.8.11.7.2.2.14.b.9|21.7.13.6.19.c.8|21.7.14.5.19.c.8|21.6.15.4.1a.4.1.7.8|21.5.31.4.d|20.5.33.1.8.2|20.4.33.1.7.1.2|20.3.34.1.3|20.3.2e|20.2.2.1.2a|21.1.2c|6e";
  function mapDots() {
    const rows = MAP.split("|"), cw = 425 / 110, ch = 160 / 44;
    let out = "";
    rows.forEach((r, j) => {
      let x = 0, land = false;
      for (const n of r.split(".").map(v => parseInt(v, 16))) {
        if (land) for (let i = x; i < x + n; i++) out += `M${(668 + (i + .5) * cw).toFixed(1)} ${(72 + (j + .5) * ch).toFixed(1)}h.01`;
        x += n; land = !land;
      }
    });
    return out;
  }
  // a few cities (lon, lat) for the wall's arcs
  const CITY = [[-74, 40.7], [-122.4, 37.8], [-46.6, -23.5], [-0.1, 51.5], [2.35, 48.85], [13.4, 52.5], [37.6, 55.75], [55.3, 25.2], [77.2, 28.6],
                [103.8, 1.35], [121.5, 31.2], [139.7, 35.7], [151.2, -33.9], [18.4, -33.9], [-99.1, 19.4], [126.98, 37.57]];
  const ll = ([lo, la]) => [668 + (lo + 180) / 360 * 425, 72 + (85 - la) / 145 * 160];
  const ARCS = [[0, 3], [3, 7], [7, 9], [9, 11], [1, 11], [3, 8], [4, 6], [10, 12], [0, 2], [2, 13], [13, 7], [5, 10], [14, 0], [8, 15]];

  // ---------- geometry helpers ----------
  const hexPts = (cx, cy, r) => Array.from({ length: 6 }, (_, i) => { const a = Math.PI / 180 * (60 * i - 90); return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`; }).join(" ");
  // a link from the core to an orbit system: leaves the core along the ray, bends in the dome's perspective
  const coreLink = (x, y) => {
    const cx = 885, cy = 400, dx = x - cx, dy = y - cy, L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L;
    const sx = cx + ux * 112, sy = cy + uy * 100, ex = x - ux * 34, ey = y - uy * 34;
    return `M${sx.toFixed(1)} ${sy.toFixed(1)} C${(sx + dx * .35).toFixed(1)} ${(sy + dy * .05).toFixed(1)} ${(ex - dx * .3).toFixed(1)} ${(ey + dy * .1).toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`;
  };
  // the long glowing streams (rail → panels, panels → hub, the loops down to the mission path)
  const STREAMS = [
    ["c", "M196 141 C226 141 222 178 246 182"],
    ["c", "M196 198 C238 198 226 300 262 360 S330 520 330 600"],
    ["v", "M196 250 C232 250 226 330 250 400 S300 540 300 604"],
    ["c", "M196 301 C230 301 222 380 236 440 S262 560 262 604"],
    ["v", "M196 352 C226 352 214 420 220 480 S226 560 214 604"],
    ["c", "M196 399 C222 399 200 470 196 520 S186 580 176 604"],
    ["c", "M512 172 C540 172 548 130 575 128"],
    ["v", "M430 258 C440 300 470 320 512 344"],
    ["c", "M1331 172 C1290 172 1236 150 1195 140"],
    ["v", "M1430 258 C1420 300 1330 286 1124 290"],
    ["c", "M1660 300 C1600 360 1480 420 1420 455"],
    ["c", "M466 640 C500 610 440 520 418 476"],
    ["v", "M1317 640 C1290 600 1380 520 1387 488"],
    ["c", "M300 800 C300 840 340 868 400 868"],
    ["v", "M1480 800 C1480 850 1440 868 1400 868"],
    ["c", "M10 520 C120 560 160 700 250 800 S360 880 380 868"],
    ["v", "M1672 560 C1580 640 1560 760 1480 830 S1420 868 1400 868"],
    ["c", "M330 560 C420 640 520 690 600 700"],
    ["v", "M1440 560 C1360 640 1260 690 1180 700"],
  ];
  // chevron triplets: [x, y, angle]
  const CHEVS = [[598, 868, 0], [755, 868, 0], [903, 868, 0], [1051, 868, 0], [1200, 868, 0], [1396, 858, 0], [285, 386, 15], [612, 378, 0], [1155, 378, 180],
                 [470, 452, 0], [1308, 452, 180], [630, 476, 20], [1144, 476, 160], [1296, 176, 0], [362, 860, 0], [1428, 852, 180], [252, 610, 90], [1560, 520, 135]];

  // ---------- the scene ----------
  function art() {
    const orbit = ORBIT.map(([k, x, y, label, sels, sec], i) => {
      const at = linkAttr(sels, sec);
      return `<g class="ctl-sc-hex ${at ? "go" : "off"} ${i % 3 === 1 ? "v" : ""}" ${at} ${at ? `role="button" tabindex="0"` : ""} aria-label="${e_(label)}${at ? "" : " (not available to you)"}" style="--d:${(i * .37).toFixed(2)}s">
        <title>${e_(label)}${at ? "" : " · not available to you"}</title>
        <polygon class="halo" points="${hexPts(x, y, 38)}"/><polygon class="cell" points="${hexPts(x, y, 30)}"/>${gi(k, x, y, 24)}</g>`;
    }).join("");
    // two layers: lines (static, with the base) and their moving light (live); the live dashes carry the ids the motes follow
    const lk = ORBIT.map(([, x, y], i) => [coreLink(x, y), i % 3 === 1 ? "v" : "", `l${i}`, (i * .41).toFixed(2), "ctl-sc-lk"]);
    const sk = STREAMS.map(([t, d], i) => [d, t, `s${i}`, (i * .53).toFixed(2), "ctl-sc-st"]);
    const lines = [...sk, ...lk].map(([d, t, , , c]) => `<path class="ctl-sc-glw ${t}" d="${d}"/><path class="${c} ${t}" d="${d}"/>`).join("");
    const runs = [...sk, ...lk].map(([d, t, id, dl]) => `<path id="ctl-sc-${id}" class="ctl-sc-run ${t}" d="${d}" style="--d:${dl}s"/>`).join("");
    const motes = still.matches ? "" : [...ORBIT.map((_, i) => [`l${i}`, 2.6 + (i % 4) * .5, i % 3 === 1 ? "v" : ""]), ...STREAMS.map(([t], i) => [`s${i}`, 4.5 + (i % 5) * .8, t === "v" ? "v" : ""])]
      .map(([id, dur, t], i) => `<circle class="ctl-sc-mote ${t}" r="${i % 2 ? 2.4 : 3.2}"><animateMotion dur="${dur.toFixed(1)}s" begin="${(-(i * .7) % dur).toFixed(2)}s" repeatCount="indefinite" rotate="auto"><mpath href="#ctl-sc-${id}"/></animateMotion></circle>`).join("");
    const chevs = CHEVS.map(([x, y, a], i) => `<g class="ctl-sc-chev ${i % 2 ? "v" : ""}" transform="translate(${x} ${y}) rotate(${a})">${[0, 1, 2].map(k => `<path d="M${k * 7 - 9} -5 l5 5 -5 5" style="--k:${k}"/>`).join("")}</g>`).join("");
    const arcs = ARCS.map(([a, b], i) => {
      const [x1, y1] = ll(CITY[a]), [x2, y2] = ll(CITY[b]), mx = (x1 + x2) / 2, my = Math.min(y1, y2) - Math.abs(x2 - x1) * .28 - 6;
      return `<path class="ctl-sc-arc ${i % 3 === 0 ? "v" : ""}" pathLength="100" d="M${x1.toFixed(1)} ${y1.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}" style="--d:${(i * .45).toFixed(2)}s"/>`;
    }).join("");
    const cities = CITY.map((c, i) => { const [x, y] = ll(c); return `<circle class="ctl-sc-city ${i % 4 === 0 ? "v" : ""}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" style="--d:${(i * .3).toFixed(1)}s"/>`; }).join("");
    // the console's monitors (both sides of her), each with a small live-looking chart
    const monsBase = [], monsLive = [];
    [[468, "bars"], [560, "map"], [652, "line"], [744, "bars"], [1012, "line"], [1104, "bars"], [1196, "map"], [1288, "radar"]].forEach(([x, kind], i) => {
      const y = 556 + Math.abs(x - 880) * .05, w = 84, h = 58, sk = (x - 880) * .012;
      let g = "", live = "";
      if (kind === "bars") live = Array.from({ length: 9 }, (_, k) => `<rect class="ctl-sc-mb" x="${x + 8 + k * 8}" y="${y + 14}" width="5" height="${h - 22}" style="--h:${(.25 + ((k * 37 + i * 11) % 70) / 100).toFixed(2)};--d:${(k * .2 + i * .1).toFixed(1)}s"/>`).join("");
      else if (kind === "line") g = `<path class="ctl-sc-ml" d="M${x + 6} ${y + h - 12} ${Array.from({ length: 9 }, (_, k) => `L${x + 6 + k * 9} ${y + 14 + ((k * 53 + i * 17) % 30)}`).join(" ")}"/>`;
      else if (kind === "map") g = `<ellipse cx="${x + w / 2}" cy="${y + h / 2}" rx="26" ry="18" class="ctl-sc-mm"/><path class="ctl-sc-mm" d="M${x + 16} ${y + h / 2}h52M${x + w / 2} ${y + 12}v34"/>`;
      else { g = `<circle class="ctl-sc-mm" cx="${x + w / 2}" cy="${y + h / 2}" r="20"/><circle class="ctl-sc-mm" cx="${x + w / 2}" cy="${y + h / 2}" r="10"/>`;
             live = `<path class="ctl-sc-sweep" d="M${x + w / 2} ${y + h / 2} l20 0 A20 20 0 0 0 ${x + w / 2 + 14.1} ${y + h / 2 - 14.1}z" style="transform-origin:${x + w / 2}px ${y + h / 2}px"/>`; }
      const tf = `transform="skewY(${sk.toFixed(2)})" style="transform-origin:${x + w / 2}px ${y + h / 2}px"`;
      monsBase.push(`<g class="ctl-sc-mon" ${tf}><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3"/>${g}</g>`);
      if (live) monsLive.push(`<g class="ctl-sc-mon" ${tf}>${live}</g>`);
    });
    // the globe's lights (deterministic)
    const lights = Array.from({ length: 110 }, (_, i) => { const a = (i * 137.5) % 360 * Math.PI / 180, r = 40 + (i * 53) % 170; return `<circle cx="${(30 + Math.cos(a) * r * .95).toFixed(1)}" cy="${(690 + Math.sin(a) * r * .85).toFixed(1)}" r="${i % 5 ? 1 : 1.8}"/>`; }).join("");
    const rings = [[180, 0], [236, 1], [298, 0], [372, 1], [450, 0]].map(([rx, v], i) => `<ellipse class="ctl-sc-orb ${v ? "v" : ""} r${i}" cx="885" cy="408" rx="${rx}" ry="${(rx * .4).toFixed(0)}"/>`).join("");
    const svg = (cls, body, label) => `<svg class="ctl-sc-art ${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" ${label ? `role="group" aria-label="${label}"` : `aria-hidden="true"`}>${body}</svg>`;
    // the base: everything that holds still, filters included, painted once on its own layer
    const base = svg("ctl-sc-base", `
      <defs>
        <linearGradient id="ctl-sc-gc" x1="0" x2="1"><stop offset="0" stop-color="#0cf6f6"/><stop offset="1" stop-color="#2f8cff"/></linearGradient>
        <linearGradient id="ctl-sc-gv" x1="0" x2="1"><stop offset="0" stop-color="#9d64fa"/><stop offset="1" stop-color="#ee86fc"/></linearGradient>
        <linearGradient id="ctl-sc-dome" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1287c8" stop-opacity=".5"/><stop offset=".55" stop-color="#073566" stop-opacity=".3"/><stop offset="1" stop-color="#020b18" stop-opacity="0"/></linearGradient>
        <radialGradient id="ctl-sc-coreg"><stop offset="0" stop-color="#6d3df5" stop-opacity=".95"/><stop offset=".55" stop-color="#2a1a8a" stop-opacity=".9"/><stop offset="1" stop-color="#0a1440" stop-opacity=".95"/></radialGradient>
        <radialGradient id="ctl-sc-glow"><stop offset="0" stop-color="#22d3ee" stop-opacity=".55"/><stop offset=".45" stop-color="#1d4ed8" stop-opacity=".18"/><stop offset="1" stop-color="#1d4ed8" stop-opacity="0"/></radialGradient>
        <radialGradient id="ctl-sc-earth" cx=".66" cy=".32" r=".8"><stop offset="0" stop-color="#2a7fd0"/><stop offset=".45" stop-color="#0f3f7a"/><stop offset=".85" stop-color="#061d40"/><stop offset="1" stop-color="#0b4f86"/></radialGradient>
        <linearGradient id="ctl-sc-wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#05254a" stop-opacity=".92"/><stop offset="1" stop-color="#031a36" stop-opacity=".88"/></linearGradient>
        <linearGradient id="ctl-sc-desk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#071a33"/><stop offset="1" stop-color="#01060f"/></linearGradient>
        <linearGradient id="ctl-sc-mark" x1="0" y1="0" x2=".4" y2="1"><stop offset="0" stop-color="#e8ffff"/><stop offset=".45" stop-color="#2ee8f5"/><stop offset="1" stop-color="#1e9bd7"/></linearGradient>
        <linearGradient id="ctl-sc-scang" x1="0" x2="1"><stop offset="0" stop-color="#22d3ee" stop-opacity="0"/><stop offset=".7" stop-color="#22d3ee" stop-opacity=".22"/><stop offset="1" stop-color="#e0fdff" stop-opacity=".5"/></linearGradient>
        <filter id="ctl-sc-blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
        <filter id="ctl-sc-soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        <clipPath id="ctl-sc-wallclip"><rect x="668" y="72" width="425" height="160" rx="4"/></clipPath>
      </defs>
      <g class="ctl-sc-wallg">
        <rect x="560" y="58" width="650" height="190" rx="8" class="ctl-sc-bezel"/>
        <rect x="575" y="72" width="88" height="76" rx="4" class="ctl-sc-scr"/><rect x="575" y="155" width="88" height="77" rx="4" class="ctl-sc-scr"/>
        <rect x="668" y="72" width="425" height="160" rx="4" class="ctl-sc-scr main"/>
        <rect x="1100" y="72" width="95" height="76" rx="4" class="ctl-sc-scr"/><rect x="1100" y="155" width="95" height="77" rx="4" class="ctl-sc-scr"/>
        <g clip-path="url(#ctl-sc-wallclip)"><rect x="668" y="72" width="425" height="160" class="ctl-sc-wallglow"/><path class="ctl-sc-dots halo" d="${mapDots()}" filter="url(#ctl-sc-blur)"/><path class="ctl-sc-dots" d="${mapDots()}"/><g class="ctl-sc-arcbase">${arcs}</g></g>
        <g class="ctl-sc-mini">${[0, 1, 2, 3, 4, 5].map(k => `<path d="M583 ${84 + k * 9}h${[56, 38, 64, 30, 50, 42][k]}"/>`).join("")}<rect x="583" y="134" width="22" height="6" class="fill"/><rect x="609" y="130" width="22" height="10" class="fill v"/></g>
        <g class="ctl-sc-miniglobe"><circle cx="619" cy="193" r="27"/><ellipse cx="619" cy="193" rx="12" ry="27"/><path d="M592 193h54M596 180h46M596 206h46"/></g>
        <g class="ctl-sc-miniradar"><circle cx="1147" cy="193" r="28"/><circle cx="1147" cy="193" r="18"/><circle cx="1147" cy="193" r="8"/><path d="M1119 193h56M1147 165v56"/></g>
      </g>
      <g class="ctl-sc-earth"><circle cx="30" cy="690" r="206" class="atmo"/><circle cx="30" cy="690" r="192" fill="url(#ctl-sc-earth)"/><g class="lights">${lights}</g>
        <path class="rim" d="M-150 600 A192 192 0 0 1 218 650"/></g>
      <path class="ctl-sc-dome" d="M290 330 Q885 200 1470 330 L1452 566 Q885 640 312 566 Z"/>
      <path class="ctl-sc-domeedge" d="M290 330 Q885 200 1470 330"/>
      <g class="ctl-sc-domemap"><path class="ctl-sc-dots faint" d="${mapDots()}" transform="translate(-715 230) scale(1.95 1.3) translate(-60 -40)"/></g>
      <ellipse cx="885" cy="410" rx="330" ry="150" fill="url(#ctl-sc-glow)"/>
      <g class="ctl-sc-orbglow" filter="url(#ctl-sc-blur)">${rings}</g>
      <ellipse cx="885" cy="640" rx="520" ry="60" class="ctl-sc-floorglow" filter="url(#ctl-sc-blur)"/>
      <path class="ctl-sc-desk" d="M0 690 Q885 560 1672 690 L1672 941 L0 941 Z"/>
      <path class="ctl-sc-orange" d="M40 640 Q520 700 760 650"/><path class="ctl-sc-orange" d="M1010 650 Q1250 700 1672 630"/>
      <path class="ctl-sc-orange thin" d="M150 941 Q300 790 620 735"/><path class="ctl-sc-orange thin" d="M1150 735 Q1470 790 1600 941"/>
      <path class="ctl-sc-orange wide" d="M330 820 Q885 760 1440 820"/>
      <g class="ctl-sc-mons">${monsBase.join("")}</g>
      <path class="ctl-sc-deskedge" d="M380 640 Q885 590 1390 640"/>
      <g class="ctl-sc-links">${lines}</g>
      <g class="ctl-sc-corebase"><polygon class="o2" points="${hexPts(885, 400, 112)}"/><polygon class="o1" points="${hexPts(885, 400, 96)}"/>
        <circle cx="885" cy="400" r="60" fill="url(#ctl-sc-coreg)" class="ball"/>
        <g transform="translate(857 372) scale(2.35)" fill="url(#ctl-sc-mark)" class="mark">${MARK}</g></g>`);
    // the live layer: only what moves, and what you can press
    const live = svg("ctl-sc-live", `
      <g clip-path="url(#ctl-sc-wallclip)" class="ctl-sc-wallg">${arcs}${cities}<rect class="ctl-sc-scan" x="608" y="72" width="60" height="160" fill="url(#ctl-sc-scang)"/></g>
      <g class="ctl-sc-wallg ctl-sc-ministack">${[0, 1, 2, 3].map(k => `<path class="${k % 2 ? "v" : ""}" d="M1147 ${86 + k * 13}l26 9-26 9-26-9z" style="--d:${k * .4}s"/>`).join("")}</g>
      <g class="ctl-sc-wallg"><path class="ctl-sc-sweep" d="M1147 193 l28 0 A28 28 0 0 0 1166.8 173.2z" style="transform-origin:1147px 193px"/></g>
      <g class="ctl-sc-mons">${monsLive.join("")}</g>
      ${rings}
      <g class="ctl-sc-links">${runs}</g>
      <g class="ctl-sc-chevs">${chevs}</g>
      <g class="ctl-sc-core" ${linkAttr(["#nav-topology"], "")} role="button" tabindex="0" aria-label="AXoR core: the whole system as one graph">
        <title>AXoR core · open the Agent Topology</title>
        <polygon class="o3" points="${hexPts(885, 400, 128)}"/><polygon class="hit" points="${hexPts(885, 400, 112)}"/>
        <circle cx="885" cy="400" r="60" class="plasma"/><circle cx="885" cy="400" r="66" class="plasma b"/>
      </g>
      <g class="ctl-sc-orbit">${orbit}</g>
      <g class="ctl-sc-motes">${motes}</g>`, "AXoR systems around the core");
    return base + live;
  }

  // ---------- figures ----------
  function missions() {
    if (!ops || ops.error) return null;
    const ms = [...(ops.competitions || []), ...(ops.custom || []).filter(c => !["VERIFIED", "FAILED", "CANCELLED"].includes(c.state))];
    return ms.filter(m => m.health !== "paused");
  }
  const HEALTH = { met: ["c", "Objective met"], on_track: ["b", "On track"], unmeasurable: ["v", "Not measurable yet"], blocked: ["m", "Blocked"], paused: ["g", "Paused"] };
  function healthPanel() {
    const d = hub, ms = missions(), r24 = d.runs24 || { done: 0, failed: 0 }, fin = r24.done + r24.failed;
    const wk = (d.week || []).map(x => x.done + x.failed ? x.done / (x.done + x.failed) * 100 : null);
    let val = null, cap = "", tip = "", dots = [];
    // "not measurable yet" is not a failure (Mission operations shows it as a caution): it stays out of the share and is counted apart
    const measured = (ms || []).filter(m => m.health !== "unmeasurable"), unm = (ms || []).length - measured.length;
    if (measured.length) {
      const good = measured.filter(m => m.health === "met" || m.health === "on_track").length;
      val = pct(good, measured.length);
      cap = `${good} of ${measured.length} measured mission${measured.length === 1 ? "" : "s"} on track or met${unm ? ` · ${unm} not measurable yet` : ""}`;
      tip = `Mission health: active missions (Bittensor competitions and custom missions; paused ones and those not measurable yet left out) whose objective is on track or met. ${ms.map(m => `${m.title}: ${(HEALTH[m.health] || [, m.health])[1]}`).join("; ")}. The line is agent run success per day, last 7 days.`;
      dots = ms.slice(0, 5).map(m => [(HEALTH[m.health] || ["g"])[0], `${m.title}: ${(HEALTH[m.health] || [, m.health])[1]}`]);
    } else {
      val = fin ? Math.round(r24.done / fin * 100) : null;
      cap = unm ? `${unm} mission${unm === 1 ? "" : "s"}, none measurable yet · agent run success, 24 h` : ops && !ops.error ? "No active mission · agent run success, 24 h" : "Agent run success, 24 h";
      tip = `No active mission to measure${fin ? `: the ring shows agent runs that finished without failing in the last 24 hours (${r24.failed} failed of ${fin})` : " and no finished agent run in 24 hours"}. The line is run success per day, last 7 days.`;
      dots = (d.week || []).slice(-5).map(x => { const n = x.done + x.failed, r = n ? x.done / n : null; return [r == null ? "g" : r >= .9 ? "c" : r >= .7 ? "b" : r >= .5 ? "v" : "m", `${new Date(x.day * 1000).toLocaleDateString(undefined, { weekday: "short" })}: ${n ? `${Math.round(r * 100)}% of ${n} runs` : "no run"}`]; });
    }
    const C = 2 * Math.PI * 36, off = C * (1 - clamp(val) / 100);
    const series = wk.filter(v => v != null);
    let line = "", pts = "";
    if (series.length > 1) {
      const lo = Math.min(...series, 60), hi = 100, xs = i => 4 + i * (112 / (series.length - 1)), ys = v => 46 - (v - lo) / (hi - lo || 1) * 40;
      line = series.map((v, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)} ${ys(v).toFixed(1)}`).join(" ");
      pts = series.map((v, i) => `<circle cx="${xs(i).toFixed(1)}" cy="${ys(v).toFixed(1)}" r="2.6"/>`).join("");
    }
    return `<div class="ctl-sc-ph"><span class="ctl-sc-phi">${ic("spark")}</span><h3>Mission health</h3></div>
      <div class="ctl-sc-health" title="${e_(tip)}">
        <div class="ctl-sc-ring" role="img" aria-label="${e_(val == null ? "No figure yet" : `${val} percent. ${cap}`)}"><svg viewBox="0 0 90 90"><circle class="trk" cx="45" cy="45" r="36"/><circle class="val" cx="45" cy="45" r="36" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 45 45)"/></svg><b>${val == null ? "–" : `${val}%`}</b></div>
        <div class="ctl-sc-spark">${line ? `<svg viewBox="0 0 120 50" preserveAspectRatio="none"><path class="ln" d="${line}"/>${pts}</svg>` : `<p>No run line yet</p>`}
          <ul class="ctl-sc-hd">${dots.map(([t, l]) => `<li class="t-${t}" title="${e_(l)}"></li>`).join("")}</ul></div>
      </div><p class="ctl-sc-cap">${e_(cap)}</p>`;
  }
  function statusPanel() {
    const o = hub.overview, r24 = hub.runs24 || { done: 0, failed: 0 }, fin = r24.done + r24.failed, wk = hub.week || [];
    const util = o.agents ? pct(o.working, o.agents) : null;
    const peak = Math.max(o.spent || 0, ...wk.map(x => x.tokens || 0));
    const rows = [
      ["gear", "Operations", fin ? Math.round(r24.done / fin * 100) : null, fin ? `${Math.round(r24.done / fin * 100)}%` : "–", fin ? `Agent runs that finished without failing, 24 h: ${r24.failed} failed of ${fin}` : "No finished agent run in 24 hours", "agents", "c"],
      ["agents", "Workforce", util, util == null ? "–" : `${util}%`, `${o.working} of ${o.agents} agent${o.agents === 1 ? "" : "s"} working now`, "agents", "c"],
      ["bolt", "Budget", o.cap ? pct(o.spent, o.cap) : peak ? pct(o.spent, peak) : 0, tok(o.spent), o.cap ? `${tok(o.spent)} of the ${tok(o.cap)} token limit used today` : `${tok(o.spent)} tokens today · no daily limit (bar: share of the busiest day this week)`, "resources", "v"],
    ];
    return `<div class="ctl-sc-ph"><span class="ctl-sc-phi">${ic("layers")}</span><h3>Company status</h3></div>
      <div class="ctl-sc-status"><div class="ctl-sc-holo" aria-hidden="true"><i></i><i></i><i></i><i></i><span></span></div>
        <ul>${rows.map(([k, l, v, txt, tip, sec, tone]) => `<li><button type="button" data-sec="${sec}" title="${e_(`${l}: ${tip}`)}"><span class="ctl-sc-si">${ic(k)}</span><span class="ctl-sc-bar t-${tone}" role="img" aria-label="${e_(`${l}: ${txt}`)}"><i style="width:${clamp(v)}%"></i></span><small>${e_(txt)}</small></button></li>`).join("")}</ul></div>
      <p class="ctl-sc-cap">${e_(o.approvals ? `${o.approvals} approval${o.approvals === 1 ? "" : "s"} waiting` : "No approval waiting")} · ${e_(`${o.alerts || 0} alert${o.alerts === 1 ? "" : "s"}`)}</p>`;
  }
  const KIND = { infra: "radar", human: "target", regression: "poly", budget: "bolt", promotion: "bolt", milestone: "target" };
  const LEVEL = { stop: [100, "m"], crit: [100, "m"], warn: [70, "v"], info: [40, "c"] };
  // G5-2's readiness gate (ops.gate, when the server has it): blocked missions and open critical risks aren't in the decision queue,
  // so they lead here and open the Dashboard's Mission readiness card, where they are decided
  function gateRows() {
    const g = ops && !ops.error ? ops.gate : null;
    if (!g || g.error) return [];
    const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
    const rows = (g.missions || []).filter(m => m.state === "BLOCKED").map(m => {
      const i = m.blocked?.[0]?.items?.[0];
      return { ic: "shield", t: `${m.title || m.ref}: ${plural(m.blocked_n || 0, "task")} blocked by readiness`, s: i ? `${i.cap}${i.value ? `:${i.value}` : ""} · ${i.remedy || i.evidence || ""}` : "", lv: "crit", at: `data-sc-gate="1"` };
    });
    const crit = (g.risks || []).filter(r => r.critical && r.status === "open");
    if (crit.length) rows.push({ ic: "shield", t: `${plural(crit.length, "critical risk")} open`, s: crit.map(r => r.title).join(" · "), lv: "crit", at: `data-sc-gate="1"` });
    return rows.slice(0, 2);  // leaves room for the decision queue
  }
  function actionsPanel() {
    let rows = gateRows();
    if (ops && !ops.error && ops.queue?.length) {
      rows = [...rows, ...[...ops.queue].sort((a, b) => (b.owner === "you") - (a.owner === "you")).slice(0, 3).map(x => ({ ic: KIND[x.kind] || "target", t: x.title, s: x.detail, lv: x.level,
        at: x.ref && /^(comp|mx):/.test(x.ref) && typeof CtlOps !== "undefined" ? `data-sc-mission="${e_(x.ref)}"` : x.go ? `data-goview="${e_(x.go)}"` : `data-sec="approvals"` }))].slice(0, 3);
    }
    if (rows.length < 3) {
      const ap = (hub.approvals?.all || []).map(a => ({ ic: "target", t: a.title || a.kind || "Approval", s: a.why || a.detail || "Waiting for your decision", lv: "warn", at: `data-sec="approvals"` }));
      const al = (hub.alerts || []).filter(a => a.level !== "info").map(a => ({ ic: a.level === "stop" ? "poly" : "bolt", t: a.title, s: a.detail, lv: a.level, at: a.act === "budget" ? `data-goview="studio"` : `data-sec="alerts"` }));
      rows = [...rows, ...ap, ...al].slice(0, 3);
    }
    const body = rows.length ? rows.map(r => { const [w, t] = LEVEL[r.lv] || LEVEL.info;
      return `<li><button type="button" ${r.at} title="${e_(`${r.t}${r.s ? ` · ${r.s}` : ""}`)}"><span class="ctl-sc-ni">${ic(r.ic)}</span><span class="ctl-sc-nt"><b>${e_(r.t)}</b><span class="ctl-sc-bar t-${t}"><i style="width:${w}%"></i></span></span>${ic("chev", "ctl-sc-nc")}</button></li>`; }).join("")
      : `<li class="ctl-sc-none">${ic("shield")}<span>Nothing waits for you: no decision, approval or alert.</span></li>`;
    return `<div class="ctl-sc-ph"><span class="ctl-sc-phi">${ic("play")}</span><h3>Next actions</h3></div><ul class="ctl-sc-next">${body}</ul>`;
  }
  function layersPanel() {
    const L = [["globebrain", "Intelligence layers", ["#nav-layers"]], ["topology", "Agent topology", ["#nav-topology"]], ["doc", "Knowledge Hub", ["#nav-knowledge", "#nav-myknowledge"]], ["stack", "Analytics", ["#nav-analytics", "#nav-dash"]]];
    return `<div class="ctl-sc-ph"><span class="ctl-sc-phi">${ic("layers")}</span><h3>Intelligence layers</h3></div>
      <div class="ctl-sc-layers"><div class="ctl-sc-stack" aria-hidden="true">${[0, 1, 2, 3].map(k => `<i class="l${k}"><u></u></i>`).join("")}<b></b></div>
        <ul>${L.map(([k, l, sels]) => { const at = linkAttr(sels, ""); return `<li><button type="button" ${at || "disabled"} title="${e_(l)}${at ? "" : " · not available to you"}" aria-label="${e_(l)}">${ic(k)}</button></li>`; }).join("")}</ul></div>`;
  }
  function pathBand() {
    const a = ops && !ops.error ? ops.activity || {} : null;
    return `<div class="ctl-sc-path" role="group" aria-label="Mission path: every task of every engine by state">
      <span class="ctl-sc-pl">${ic("rocket")}<b>Missions</b></span>
      ${PATH.map(([k, key, l], i) => `<button type="button" class="ctl-sc-ph6" style="left:${PATH_X[i] - 380 - 40}px" data-sec="tasks" title="${e_(`${l}: ${a ? `${a[key] || 0} task${a[key] === 1 ? "" : "s"}` : "not loaded"}`)}">
        <svg viewBox="0 0 80 80" aria-hidden="true"><polygon class="halo" points="${hexPts(40, 40, 38)}"/><polygon class="cell" points="${hexPts(40, 40, 31)}"/>${gi(k, 40, 40, 28)}</svg>
        <span class="ctl-sc-pc"><b>${a ? a[key] || 0 : "–"}</b><small>${e_(l)}</small></span></button>`).join("")}</div>`;
  }

  function view(d) {
    hub = d;
    const rail = RAIL.map(([k, l, sels, sec], i) => {
      const at = i === 0 ? "" : linkAttr(sels, sec);
      return `<li><button type="button" class="${i === 0 ? "on" : ""}" ${i === 0 ? `aria-current="page"` : at || "disabled"} title="${e_(l)}${i === 0 || at ? "" : " · not available to you"}">${ic(k)}<span>${e_(l)}</span><i aria-hidden="true"></i></button></li>`;
    }).join("");
    const bell = usable("#nav-alerts"), alerts = (d.overview?.alerts || 0) > 0;
    return `<div class="ctl-sc ${still.matches ? "is-still" : ""}" data-sc>
      <div class="ctl-sc-fit"><div class="ctl-sc-stage">
        <canvas class="ctl-sc-room" width="${W}" height="${H}" aria-hidden="true"></canvas>
        ${art()}
        <div class="ctl-sc-lisa" aria-hidden="true"><img src="/static/brand/scene-portrait.webp" alt="" decoding="async"><span class="ctl-sc-mesh"></span></div>
        <header class="ctl-sc-head"><span class="ctl-sc-logo"><svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="ctl-sc-mk2" x1="0" y1="0" x2=".4" y2="1"><stop offset="0" stop-color="#e8ffff"/><stop offset=".45" stop-color="#2ee8f5"/><stop offset="1" stop-color="#1e9bd7"/></linearGradient></defs><g fill="url(#ctl-sc-mk2)">${MARK}</g></svg><b>AXoR</b></span>
          <span class="ctl-sc-tools">
            <span class="ctl-sc-seg" role="group" aria-label="Overview style"><button type="button" aria-pressed="true" data-sc-mode="scene">Scene</button><button type="button" aria-pressed="false" data-sc-mode="dash">Dashboard</button></span>
            <button type="button" class="ctl-sc-tb" data-sc-act="search" title="Search and commands (Ctrl K)" aria-label="Search">${ic("search")}</button>
            ${bell ? `<button type="button" class="ctl-sc-tb" data-sc-nav="#nav-alerts" title="Notifications" aria-label="Notifications">${ic("bell")}${alerts ? `<i class="ping" aria-hidden="true"></i>` : ""}</button>` : ""}
            <button type="button" class="ctl-sc-tb ctl-sc-me" data-sc-act="account" title="Account" aria-label="Account menu"><i></i></button></span></header>
        <nav class="ctl-sc-rail" aria-label="Control Hub"><ul>${rail}</ul></nav>
        <section class="ctl-sc-p p-health" data-sc-p="health" aria-label="Mission health">${healthPanel()}</section>
        <section class="ctl-sc-p p-status" data-sc-p="status" aria-label="Company status">${statusPanel()}</section>
        <section class="ctl-sc-p p-layers" data-sc-p="layers" aria-label="Intelligence layers">${layersPanel()}</section>
        <section class="ctl-sc-p p-next" data-sc-p="next" aria-label="Next actions">${actionsPanel()}</section>
        <div data-sc-p="path">${pathBand()}</div>
      </div></div>
      <div class="ctl-sc-flow" hidden><div class="ctl-sc-flowh"><span class="ctl-sc-seg" role="group" aria-label="Overview style"><button type="button" aria-pressed="true" data-sc-mode="scene">Scene</button><button type="button" aria-pressed="false" data-sc-mode="dash">Dashboard</button></span></div></div>
      ${d.errors?.length ? `<p class="ctl-warn ctl-sc-warn">${e_(d.errors.join(" · "))}</p>` : ""}
    </div>`;
  }

  // ---------- mount, fit, motion ----------
  function room(cv) {  // the command room behind the hologram: screens and ceiling lights out of focus (drawn once)
    const c = cv.getContext("2d"); if (!c) return;
    const g = c.createLinearGradient(0, 0, 0, H); g.addColorStop(0, "#03101f"); g.addColorStop(.35, "#061830"); g.addColorStop(.62, "#040d1c"); g.addColorStop(1, "#01050c");
    c.fillStyle = g; c.fillRect(0, 0, W, H);
    let s = 7; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
    c.filter = "blur(5px)";
    for (const [cx, cy, r, col] of [[180, 120, 260, "255,150,60"], [1500, 110, 300, "255,150,60"], [880, 200, 420, "40,140,255"], [1420, 330, 220, "40,170,255"], [260, 330, 200, "40,170,255"]]) {
      const rg = c.createRadialGradient(cx, cy, 0, cx, cy, r); rg.addColorStop(0, `rgba(${col},.22)`); rg.addColorStop(1, `rgba(${col},0)`);
      c.fillStyle = rg; c.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
    for (let i = 0; i < 380; i++) {  // rows of desks with screens, receding to the horizon
      const row = rnd(), y = 140 + row * 230, sc = .4 + row * 1.1, x = rnd() * W, warm = rnd() < .42;
      c.fillStyle = warm ? `rgba(255,${150 + (rnd() * 60 | 0)},70,${.14 + rnd() * .34})` : `rgba(${40 + (rnd() * 60 | 0)},${150 + (rnd() * 80 | 0)},255,${.12 + rnd() * .3})`;
      c.fillRect(x, y, (10 + rnd() * 26) * sc, (5 + rnd() * 10) * sc);
    }
    c.filter = "blur(2px)";
    for (let i = 0; i < 90; i++) { const x = rnd() * W, y = 18 + rnd() * 70; c.fillStyle = `rgba(255,${170 + (rnd() * 50 | 0)},90,${.15 + rnd() * .35})`; c.fillRect(x, y, 14 + rnd() * 30, 3); }  // ceiling lights
    c.filter = "none";
    const v = c.createRadialGradient(W / 2, H * .45, H * .2, W / 2, H * .45, W * .7); v.addColorStop(0, "rgba(1,6,14,0)"); v.addColorStop(1, "rgba(1,6,14,.55)");
    c.fillStyle = v; c.fillRect(0, 0, W, H);
  }
  function fit() {
    if (!el) return;
    const box = el.querySelector(".ctl-sc-fit"), st = el.querySelector(".ctl-sc-stage"); if (!box || !st) return;
    const w = el.clientWidth, narrow = w < 860;
    if (narrow !== flow) layout(narrow);
    if (narrow) {  // phones and narrow windows: the hub alone (cropped around the core), the panels below it
      const k = w / 1000;
      st.style.transform = `scale(${k}) translate(-380px, -40px)`;
      box.style.height = `${Math.round(890 * k)}px`;
    } else {
      const top = box.getBoundingClientRect().top + scrollY, availH = Math.max(560, innerHeight - Math.max(48, top) - 8);
      const k = Math.min(w / W, availH / H);
      st.style.transform = `translateX(${Math.max(0, (w - W * k) / 2)}px) scale(${k})`;
      box.style.height = `${Math.round(H * k)}px`;
    }
  }
  function layout(narrow) {  // moves the four panels between the stage and the stacked list (the same nodes: no re-render)
    flow = narrow;
    const list = el.querySelector(".ctl-sc-flow"), st = el.querySelector(".ctl-sc-stage");
    for (const k of ["health", "status", "next", "layers"]) { const p = el.querySelector(`[data-sc-p="${k}"]`); if (p) (narrow ? list : st).appendChild(p); }
    list.hidden = !narrow;
    el.classList.toggle("is-flow", narrow);
  }
  function fold(on) {  // the sidebar to icons while the scene shows on a wide screen, put back as it was
    const side = $("#side"); if (!side) return;
    if (on && innerWidth >= 1280 && !side.classList.contains("collapsed") && S_("scene.fold") !== false) { side.classList.add("collapsed"); autoFold = true; }
    else if (!on && autoFold) { side.classList.remove("collapsed"); autoFold = false; }
  }
  function after(root) {
    const sc = root?.querySelector(".ctl-sc");
    if (!sc) {
      unmount(); injectToggle(root);
      if (peek && !root?.querySelector(".ctl-area.on[data-sec='overview']")) peek = false;  // another area: the next Overview is the scene again
      if (toGate) { toGate = false; findGate(root, 0); }
      return;
    }
    el = sc; flow = null;
    document.body.classList.add("ctl-sc-on");
    room(sc.querySelector(".ctl-sc-room"));
    lisaMesh(sc.querySelector(".ctl-sc-mesh"));
    fit();
    ro?.disconnect(); ro = new ResizeObserver(() => fit()); ro.observe(sc);
    fold(true);
    if (!onPin) { onPin = () => { if (autoFold) { autoFold = false; S_("scene.fold", false); } }; $("#side-collapse")?.addEventListener("click", onPin); }
    if (!onVis) { onVis = () => motion(!document.hidden); document.addEventListener("visibilitychange", onVis); }
    motion(!document.hidden);
    wire(sc);
    loadOps();
  }
  function motion(run) {
    const svg = el?.querySelector(".ctl-sc-live"); if (!svg) return;
    const go = run && !still.matches;
    try { go ? svg.unpauseAnimations() : svg.pauseAnimations(); } catch { /* no SMIL */ }
    el.classList.toggle("is-paused", !go);
  }
  // Mission operations draws its readiness card once its own data is in: wait for it (up to ~6 s), then bring it into view
  function findGate(root, n) {
    const c = root?.querySelector(".ctlo-gate");
    if (c) { c.style.scrollMarginTop = "76px"; c.scrollIntoView({ block: "start", behavior: still.matches ? "auto" : "smooth" }); return; }  // clear of the sticky top bar
    if (n < 30) setTimeout(() => findGate(root, n + 1), 200);
  }
  function leave() { peek = false; unmount(); }  // the Control view stopped
  function unmount() {
    if (!el && !autoFold) return;
    ro?.disconnect(); ro = null;
    if (onVis) { document.removeEventListener("visibilitychange", onVis); onVis = null; }
    if (onPin) { $("#side-collapse")?.removeEventListener("click", onPin); onPin = null; }
    fold(false);
    document.body.classList.remove("ctl-sc-on");
    el = null; flow = null;
  }
  function wire(sc) {
    sc.addEventListener("click", e => {
      const t = e.target;
      const m = t.closest("[data-sc-mode]"); if (m) { e.stopPropagation(); return setMode(m.dataset.scMode === "scene"); }
      const n = t.closest("[data-sc-nav]"); if (n) { e.stopPropagation(); return $(n.dataset.scNav)?.click(); }
      const ms = t.closest("[data-sc-mission]"); if (ms) { e.stopPropagation(); return CtlOps.mission(ms.dataset.scMission); }
      if (t.closest("[data-sc-gate]")) { e.stopPropagation(); peek = true; toGate = true; unmount(); if (typeof Control !== "undefined") Control.rerender(); return; }
      const a = t.closest("[data-sc-act]"); if (a) { e.stopPropagation();
        if (a.dataset.scAct === "search") return typeof Platform !== "undefined" && Platform.open ? Platform.open() : null;
        if (a.dataset.scAct === "account") return $("#account")?.click(); }
    });
    sc.addEventListener("keydown", e => {  // the SVG's orbit systems and core act like buttons
      if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("g[role=button]")) { e.preventDefault(); e.target.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
    });
  }
  function setMode(scene) {
    S_("scene", scene); peek = false;
    if (!scene) unmount();
    if (typeof Control !== "undefined") Control.rerender();
  }
  // the Command Center's head gets the way back to the scene
  function injectToggle(root) {
    const tools = root?.querySelector(".ctl-cc-tools");
    if (!tools || tools.querySelector("[data-sc-back]") || !root.querySelector(".ctl-area.on[data-sec='overview'], .ctl-area.on[data-sec='performance'], .ctl-area.on[data-sec='resources'], .ctl-area.on[data-sec='routing']")) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "ctl-cc-ib"; b.dataset.scBack = "1"; b.dataset.sec = "overview";  // control.js's own handler opens Overview
    b.title = "Scene: the Control Hub as the command room"; b.setAttribute("aria-label", "Show the scene");
    b.innerHTML = ic("spark");
    b.onclick = () => { S_("scene", true); peek = false; };
    tools.prepend(b);
  }
  // the neural mesh over her robe (drawn once per mount; masked to the portrait in CSS)
  function lisaMesh(m) {
    if (!m || m.firstChild) return;
    let s = 11; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
    const pts = [];
    // her robe only: not her face, the skin of her chest, or her hands (fractions of the portrait)
    const skin = (x, y) => y < 40 || (x > 33 && x < 63 && y < 57) || (x > 18 && x < 70 && y > 74);
    while (pts.length < 56) { const x = 4 + rnd() * 92, y = 38 + rnd() * 60; if (!skin(x, y)) pts.push([x, y]); }
    let ln = "";
    pts.forEach((p, i) => { pts.map((q, j) => [j, Math.hypot(p[0] - q[0], p[1] - q[1])]).filter(([j]) => j > i).sort((a, b) => a[1] - b[1]).slice(0, 2).forEach(([j]) => { ln += `M${p[0].toFixed(1)} ${p[1].toFixed(1)}L${pts[j][0].toFixed(1)} ${pts[j][1].toFixed(1)}`; }); });
    m.innerHTML = `<svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="${ln}"/>${pts.map(([x, y], i) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${i % 4 ? .45 : .8}" style="--d:${(i * .23 % 4).toFixed(2)}s"/>`).join("")}</svg>`;
  }

  // ---------- data ----------
  function loadOps() {
    if (opsBusy) return;
    opsBusy = true;
    (typeof api === "function" ? api(OPS) : Promise.reject(new Error("no api"))).then(d => { ops = d; }).catch(e => { ops = { error: e?.message || "unavailable" }; })
      .finally(() => { opsBusy = false; patch(); });
  }
  function put(k, html) {
    const p = el?.querySelector(`[data-sc-p="${k}"]`); if (!p) return;
    if (p.dataset.h === html) return;  // unchanged: leave it (and its animation) alone
    p.dataset.h = html; p.innerHTML = html;
  }
  function patch() {
    if (!el || !hub) return;
    put("health", healthPanel()); put("status", statusPanel()); put("next", actionsPanel()); put("path", pathBand());
  }
  function update(d) { hub = d; patch(); loadOps(); }
  const live = root => wanted() && !!el && !!root?.contains(el);

  return { wanted, view, after, update, leave, live };
})();
