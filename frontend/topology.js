/* Unified control panel (topology.py, /api/topology, view #topology; prefix tpo-): AXoR as one interactive graph with seven
   synchronized projections over one shared identity per entity: organization, missions & workflow, agent execution, infrastructure,
   network, knowledge & lineage, observability. The projections are filters over one graph, so a sandbox selected in the execution
   graph stays selected when you switch to the network or infrastructure projection.
   - Levels: Global (the company), Operational (agents, tasks, runs, pods, hosts), Deep (tool calls, mission stages, containers, events).
   - Interactions: zoom and pan, drag, select (inspector), double-click to collapse/expand a node's children, trace (the whole path
     through a node), impact (what depends on it: dependency analysis), search, compare two nodes, replay the time window (time
     travel), live updates with animated edges on running work.
   Rendering: Cytoscape.js (vendor/cytoscape, MIT), canvas; colors come from the theme tokens and follow light/dark. */
const Topology = (() => {
  const B = "/api/topology";
  const LAYERS = [["org", "users", "Organization"], ["mission", "target", "Missions & workflow"], ["exec", "zap", "Agent execution"], ["infra", "server", "Infrastructure"],
                  ["net", "globe", "Network"], ["knowledge", "book", "Knowledge & lineage"], ["obs", "alert", "Observability"]];
  const LNAME = Object.fromEntries(LAYERS.map(([k, , l]) => [k, l]));
  const LEVELS = [["global", "Global", "The company: departments, teams, missions, clusters, gateways, sources"],
                  ["operational", "Operational", "Agents, tasks, runs, sandboxes, pods, hosts, knowledge items"],
                  ["deep", "Deep", "Every tool call, mission stage, container and event"]];
  const LV = { global: 0, operational: 1, deep: 2 };
  const TYPE = {  // label, shape, size
    org: ["Organization", "round-octagon", 54], division: ["Division", "round-rectangle", 44], department: ["Department", "round-rectangle", 40],
    team: ["Team", "round-hexagon", 38], agent: ["Agent", "ellipse", 28], mission: ["Mission", "round-diamond", 44], task: ["Task", "round-rectangle", 22],
    stage: ["Mission stage", "round-tag", 18], run: ["Run", "ellipse", 18], model: ["Model", "hexagon", 28], tool: ["Tool", "round-triangle", 22],
    api: ["External API", "barrel", 32], span: ["Call", "ellipse", 11], sandbox: ["Sandbox", "cut-rectangle", 26], cluster: ["Cluster", "octagon", 50],
    "k8s-node": ["Node", "rectangle", 36], namespace: ["Namespace", "round-rectangle", 34], deployment: ["Deployment", "rhomboid", 28], pod: ["Pod", "ellipse", 20],
    container: ["Container", "rectangle", 12], gateway: ["Gateway", "diamond", 40], host: ["Host", "round-pentagon", 22], internet: ["Internet", "ellipse", 52],
    source: ["Source", "barrel", 30], knowledge: ["Knowledge item", "round-rectangle", 20], consumer: ["Reader", "ellipse", 24], person: ["Person", "ellipse", 26],
    alert: ["Alert", "triangle", 22], event: ["Event", "triangle", 14] };
  const STL = { ok: ["clear", "Healthy"], busy: ["new", "Running"], warn: ["caution", "Needs attention"], fail: ["scam", "Failing"], idle: ["muted", "Idle"], off: ["muted", "Off"] };
  const STRUCT = new Set(["contains", "member", "leads", "unplaced", "has_task", "subtask", "stage", "span", "owns_task"]);  // what collapsing hides
  const FLOW = new Set(["ran", "called", "invoked", "sandboxed", "via", "reached", "executed_as", "span", "calls", "served_by", "over"]);
  const FLOWING = new Set(["run", "sandbox", "span", "pod"]);
  const EDGE = { contains: "contains", member: "member of", leads: "leads", unplaced: "not placed", staffed_by: "staffed by", supported_by: "supported by",
                 has_task: "task", subtask: "subtask", owns_task: "owns", assigned: "assigned to", sent_to: "sent to", executed_as: "executed as", stage: "stage",
                 then: "then", ran: "ran", called: "called", served_by: "served by", invoked: "invoked", span: "call", calls: "calls", sandboxed: "sandbox",
                 runs_on: "runs on", via: "via", reached: "reached", blocked: "blocked", routes: "routes", on: "on", over: "over", reaches: "reaches",
                 produced: "produced", used_by: "used by", related: "related", similar: "similar", about: "about" };
  const S_ = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("tpo." + k)); localStorage.setItem("tpo." + k, JSON.stringify(v)); } catch { return null; } };
  let on = false, wired = false, cy = null, data = null, loading = false, timer = null, anim = null, err = null;
  let level = S_("level") || "operational", hours = S_("hours") || 24, layout = S_("layout") || "auto";
  let layers = new Set(S_("layers") || []);  // empty = every projection (the unified graph)
  let sel = null, mode = null, cmp = null, cmpPick = false, T = null, playing = null, query = "", hits = [], hitI = -1, pendingFocus = null;
  let xv = null;   // the execution view in the inspector (exec_env.py, /api/exec): {kind: "runs" | "run" | "events", …} or null
  const collapsed = new Set();
  const root = () => document.getElementById("tpo-root");
  const q = s => root()?.querySelector(s);
  const plural = (n, w, s = "s") => `${n} ${w}${n === 1 ? "" : s}`;
  const num = n => n == null ? "–" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k` : String(Math.round(n * 100) / 100);
  const bytes = n => !n ? "0 B" : n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} kB` : `${n} B`;
  const when = t => t ? new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
  const dur = s => s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`;
  const badge = (tone, text) => `<span class="badge ${tone}">${esc(text)}</span>`;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- colors from the theme ----------
  function tokens() {
    const cs = getComputedStyle(document.documentElement), v = k => cs.getPropertyValue(k).trim();
    const dark = (() => { const m = /#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(v("--bg")); return m ? (parseInt(m[1], 16) + parseInt(m[2], 16) + parseInt(m[3], 16)) / 3 < 100 : false; })();
    const L = dark ? { org: "#3987e5", mission: "#b297f7", exec: "#3cc4b4", infra: "#9aa3b2", net: "#e06cbf", knowledge: "#d9a441", obs: "#ef6b6b" }
                   : { org: "#2a78d6", mission: "#6b3fcf", exec: "#0b7a70", infra: "#5b6472", net: "#b8338f", knowledge: "#9a6a12", obs: "#c93434" };
    return { dark, L, bg: v("--bg"), surface: v("--surface"), s2: v("--surface-2"), line: v("--line"), text: v("--text"), t2: v("--text-2"), t3: v("--text-3"),
             accent: v("--accent"), good: v("--good"), warn: v("--warn"), crit: v("--crit") };
  }
  let C = null;
  const alpha = (hex, a) => { const m = /#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(hex || "") || [0, "88", "88", "88"]; return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})`; };
  function style() {
    C = tokens();
    const st = { busy: C.accent, warn: C.warn, fail: C.crit, off: C.t3, idle: C.t3 };
    return [
      { selector: "node", style: { "shape": "data(shape)", "width": "data(size)", "height": "data(size)", "background-color": "data(fill)", "border-width": 2, "border-color": "data(ring)",
        "label": "data(lbl)", "font-size": 10, "font-family": "system-ui, sans-serif", "color": C.t2, "text-valign": "bottom", "text-margin-y": 4, "text-wrap": "ellipsis",
        "text-max-width": 130, "min-zoomed-font-size": 7, "text-background-color": C.bg, "text-background-opacity": .7, "text-background-padding": 1, "text-background-shape": "round-rectangle",
        "transition-property": "opacity", "transition-duration": "150ms" } },
      { selector: "node[lv = 0]", style: { "font-size": 12, "font-weight": 600, "color": C.text } },
      ...Object.entries(st).map(([k, c]) => ({ selector: `node[st = "${k}"]`, style: { "border-color": c, "border-width": k === "fail" || k === "busy" ? 3 : 2, ...(k === "off" || k === "idle" ? { "border-style": "dashed" } : {}) } })),
      { selector: "node[st = \"fail\"]", style: { "underlay-color": C.crit, "underlay-opacity": .14, "underlay-padding": 5 } },
      { selector: "node.busy-pulse", style: { "underlay-color": C.accent, "underlay-opacity": .22, "underlay-padding": 7 } },
      { selector: "node[shared > 1]", style: { "border-style": "double", "border-width": 4 } },
      { selector: "node.collapsed", style: { "border-style": "dashed", "border-width": 3 } },
      { selector: "edge", style: { "width": "data(w)", "line-color": alpha(C.t2, C.dark ? .38 : .32), "target-arrow-color": alpha(C.t2, C.dark ? .5 : .45), "target-arrow-shape": "triangle",
        "arrow-scale": .6, "curve-style": "bezier", "opacity": .9 } },
      { selector: "edge[dep = \"\"]", style: { "line-style": "dotted", "target-arrow-shape": "none" } },
      { selector: "edge[kind = \"blocked\"]", style: { "line-color": C.crit, "target-arrow-color": C.crit, "line-style": "dashed", "target-arrow-shape": "tee" } },
      { selector: "edge[st = \"fail\"]", style: { "line-color": alpha(C.crit, .7), "target-arrow-color": C.crit } },
      { selector: "edge.live", style: { "line-color": C.accent, "target-arrow-color": C.accent, "line-style": "dashed", "line-dash-pattern": [6, 4], "width": 2.5 } },
      { selector: ".dim", style: { "opacity": .1 } },
      { selector: "edge.path", style: { "line-color": C.accent, "target-arrow-color": C.accent, "width": 3, "opacity": 1, "z-index": 9 } },
      { selector: "edge.impact", style: { "line-color": C.warn, "target-arrow-color": C.warn, "width": 3, "opacity": 1, "z-index": 9 } },
      { selector: "node.impact", style: { "underlay-color": C.warn, "underlay-opacity": .3, "underlay-padding": 6 } },
      { selector: "node.match", style: { "underlay-color": C.warn, "underlay-opacity": .45, "underlay-padding": 8 } },
      { selector: "node.cmpA", style: { "underlay-color": C.L.org, "underlay-opacity": .35, "underlay-padding": 7 } },
      { selector: "node.cmpB", style: { "underlay-color": C.L.mission, "underlay-opacity": .35, "underlay-padding": 7 } },
      { selector: "node:selected", style: { "underlay-color": C.accent, "underlay-opacity": .4, "underlay-padding": 9, "color": C.text, "font-weight": 600, "z-index": 10 } },
      { selector: ".hide", style: { "display": "none" } } ];
  }

  // ---------- data → elements ----------
  const hasKids = new Map();
  function nodeData(n) {
    const t = TYPE[n.type] || [n.type, "ellipse", 20], home = n.layers[0], col = C.L[home] || C.t2;
    return { ...n, shape: t[1], size: t[2], fill: alpha(col, C.dark ? .38 : .22), ring: col, base: col, st: n.status, shared: n.layers.length, lbl: n.label };
  }
  const edgeData = e => ({ ...e, w: Math.min(1 + Math.log2(1 + (e.n || 1)), 5), st: e.status || "" });

  function build() {
    if (!window.cytoscape) { err = "The graph library didn't load (vendor/cytoscape)."; return drawAside(); }
    const el = q("#tpo-cy");
    const first = !cy;
    if (!cy) {
      cy = cytoscape({ container: el, elements: [], style: style(), minZoom: .05, maxZoom: 4, boxSelectionEnabled: false, selectionType: "single" });
      cy.on("tap", "node", e => { const n = e.target; if (cmpPick && cmp && n.id() !== cmp.a) { cmp.b = n.id(); cmpPick = false; select(cmp.a, false); return; } select(n.id(), false); });
      cy.on("tap", e => { if (e.target === cy) { if (cmpPick) { cmpPick = false; } select(null); } });
      cy.on("dbltap", "node", e => toggle(e.target.id()));
      cy.on("mouseover", "node", e => { el.title = `${e.target.data("label")} · ${(TYPE[e.target.data("type")] || [e.target.data("type")])[0]}`; });
    }
    merge(first);
  }

  function merge(first) {
    if (!cy || !data) return;
    const keepN = new Set(data.nodes.map(n => n.id)), keepE = new Set(data.edges.map(e => e.id));
    let added = 0;
    cy.batch(() => {
      cy.elements().filter(x => !(x.isNode() ? keepN : keepE).has(x.id())).remove();
      for (const n of data.nodes) {
        const d = nodeData(n), ex = cy.getElementById(n.id);
        if (ex.nonempty()) ex.data(d); else { cy.add({ group: "nodes", data: d }); added++; }
      }
      for (const e of data.edges) { const d = edgeData(e), ex = cy.getElementById(e.id); if (ex.nonempty()) ex.data(d); else cy.add({ group: "edges", data: d }); }
    });
    hasKids.clear();
    cy.edges().forEach(e => { if (STRUCT.has(e.data("kind"))) hasKids.set(e.data("source"), (hasKids.get(e.data("source")) || 0) + 1); });
    applyView(first || added > Math.max(8, cy.nodes().length * .25));
    if (!first && added) cy.nodes().filter(n => !n.data("placed")).forEach(n => {  // a few new nodes go next to what they connect to
      const nb = n.neighborhood("node").filter(x => x.data("placed"))[0];
      if (nb) { const p = nb.position(); n.position({ x: p.x + (Math.random() - .5) * 90, y: p.y + 40 + Math.random() * 40 }); }
      n.data("placed", 1);
    });
  }

  // which elements this projection, level, time and the collapsed nodes show
  function applyView(relayout) {
    if (!cy) return;
    const lvl = LV[level], all = !layers.size;
    const hidden = new Set();
    for (const id of collapsed) {  // a collapsed node hides everything under it
      const stack = [id];
      while (stack.length) { const x = cy.getElementById(stack.pop()); x.outgoers("edge").forEach(e => { if (STRUCT.has(e.data("kind")) && !hidden.has(e.data("target"))) { hidden.add(e.data("target")); stack.push(e.data("target")); } }); }
    }
    cy.batch(() => {
      cy.nodes().forEach(n => {
        const d = n.data();
        let show = d.lv <= lvl && (all || d.layers.some(l => layers.has(l))) && !hidden.has(d.id);
        if (show && T && d.t0 && d.t0 > T) show = false;
        n.toggleClass("hide", !show);
        // status at the replayed moment: work that had started and not yet ended was running then
        n.data("st", T && d.t0 && d.t0 <= T && d.t1 && d.t1 > T ? "busy" : d.status);
        n.toggleClass("collapsed", collapsed.has(d.id));
        const k = hasKids.get(d.id);
        n.data("lbl", collapsed.has(d.id) && k ? `${d.label} (+${k})` : d.label);
      });
      cy.edges().forEach(e => {
        const show = !e.source().hasClass("hide") && !e.target().hasClass("hide") && !(T && e.data("t0") && e.data("t0") > T);
        e.toggleClass("hide", !show);
        // live: work moving right now, along execution paths, from a run, sandbox or call that is running (not a busy team's org chart)
        const busyEnd = [e.source(), e.target()].some(x => x.data("st") === "busy" && FLOWING.has(x.data("type")));
        e.toggleClass("live", show && busyEnd && FLOW.has(e.data("kind")));
      });
    });
    if (relayout) runLayout();
    paintMarks(); animate();
    const vis = cy.nodes(":visible").length;
    const em = q("#tpo-empty");
    if (em) { em.hidden = vis > 0 || loading; em.innerHTML = vis ? "" : emptyText(); }
  }
  function emptyText() {
    const off = (data?.layers || []).filter(l => (!layers.size || layers.has(l.key)) && !l.ok);
    return `<b>Nothing to show here${T ? " at this moment" : ""}.</b><p>${off.length ? off.map(l => `${esc(l.label)}: ${esc(l.why)}`).join("<br>") :
      level === "global" ? "Try the Operational level: agents, tasks and runs live there." : `Nothing ran in the last ${hours} h in this projection. Pick a longer window or another projection.`}</p>`;
  }

  function runLayout() {
    const els = cy.elements(":visible");
    if (!els.length) return;
    const one = layers.size === 1 ? [...layers][0] : null;
    const kind = layout === "auto" ? (one && ["org", "mission", "infra"].includes(one) ? "hierarchy" : els.nodes().length > 260 ? "concentric" : "force") : layout;
    const roots = els.nodes().filter(n => !n.incomers("edge:visible").filter(e => e.data("dep") !== "").length);
    const opts = {
      hierarchy: { name: "breadthfirst", directed: true, roots, spacingFactor: .9, avoidOverlap: true, nodeDimensionsIncludeLabels: false },
      force: { name: "cose", animate: false, randomize: true, nodeRepulsion: () => 9000, idealEdgeLength: () => 60, edgeElasticity: () => 80, gravity: .5, numIter: 1200, nodeDimensionsIncludeLabels: false, padding: 30 },
      concentric: { name: "concentric", concentric: n => 3 - n.data("lv") + (n.data("shared") > 1 ? .5 : 0), levelWidth: () => 1, minNodeSpacing: 8, avoidOverlap: true },
      grid: { name: "grid", avoidOverlap: true, condense: true, sort: (a, b) => a.data("lv") - b.data("lv") || a.data("type").localeCompare(b.data("type")) } }[kind] || { name: "cose", animate: false };
    try { els.layout({ ...opts, fit: true, padding: 30 }).run(); } catch (e) { els.layout({ name: "grid", fit: true }).run(); }
    cy.nodes().forEach(n => n.data("placed", 1));
  }

  // trace / impact / search / compare marks
  function paintMarks() {
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass("dim path impact match cmpA cmpB");
      if (query) hits.forEach(id => cy.getElementById(id).addClass("match"));
      const n = sel ? cy.getElementById(sel) : null;
      if (cmp?.b) {
        const a = cy.getElementById(cmp.a), b = cy.getElementById(cmp.b);
        const na = a.closedNeighborhood().union(a.successors()), nb = b.closedNeighborhood().union(b.successors());
        cy.elements(":visible").difference(na.union(nb)).addClass("dim");
        na.nodes().addClass("cmpA"); nb.nodes().addClass("cmpB");
      } else if (n && n.nonempty() && mode === "trace") {
        const path = n.predecessors().union(n.successors()).union(n);
        cy.elements(":visible").difference(path).addClass("dim");
        path.edges().addClass("path");
      } else if (n && n.nonempty() && mode === "impact") {
        const imp = impactOf(n);
        cy.elements(":visible").difference(imp.els.union(n)).addClass("dim");
        imp.els.nodes().addClass("impact"); imp.els.edges().addClass("impact");
      }
    });
  }
  // dependency analysis: what stops working if this node fails. An edge's dep says which end depends on the other.
  function impactOf(n) {
    let els = cy.collection(), front = [n], seen = new Set([n.id()]);
    while (front.length) {
      const next = [];
      for (const x of front) {
        x.connectedEdges().forEach(e => {
          const dep = e.data("dep"); if (!dep) return;
          const other = dep === "fwd" ? (e.target().same(x) ? e.source() : null) : (e.source().same(x) ? e.target() : null);
          if (!other || seen.has(other.id())) return;
          seen.add(other.id()); els = els.union(e).union(other); next.push(other);
        });
      }
      front = next;
    }
    return { els, nodes: els.nodes() };
  }

  function toggle(id) {
    if (!hasKids.get(id)) return;
    collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id);
    applyView(false); drawBar();
    if (sel === id) drawAside();
  }

  function select(id, center = true) {
    sel = id;
    if (!id) { mode = null; cmp = null; }
    if (cy) { cy.$(":selected").unselect(); if (id) { const n = cy.getElementById(id); if (n.nonempty()) { n.select(); if (center && n.visible()) cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: reduced() ? 0 : 300 }); } } }
    try { history.replaceState(null, "", id ? `#topology/${encodeURIComponent(id)}` : "#topology"); } catch { /* sandboxed frame */ }
    paintMarks(); drawAside();
  }

  // ---------- live edges ----------
  function animate() {
    clearInterval(anim); anim = null;
    if (!on || !cy || reduced()) return;
    let off = 0;
    anim = setInterval(() => {
      const live = cy.edges(".live:visible"), busy = cy.nodes(":visible").filter(n => n.data("st") === "busy");
      if (!live.length && !busy.length) return;
      off = (off + 1) % 40;
      cy.batch(() => { live.style("line-dash-offset", -off); busy.toggleClass("busy-pulse", off % 20 < 10); });
    }, 90);
  }

  // ---------- markup ----------
  function skeleton() {
    const r = root(); if (!r || r.dataset.ready) return;
    r.dataset.ready = "1";
    r.innerHTML = `<div class="tpo">
      <div class="tpo-head"><div><h1 class="page">Unified Agent Control Panel</h1>
        <p class="lead">AXoR as one graph in seven synchronized projections, each entity with one identity across them. Double-click a node to collapse it; select one to trace it, see its impact or compare it.</p></div>
        <div class="tpo-stats" id="tpo-stats" aria-live="polite"></div></div>
      <div class="tpo-bar" id="tpo-bar"></div>
      <div class="tpo-main">
        <div class="tpo-canvas"><div id="tpo-cy" class="tpo-cy" role="application" aria-label="System graph. Use search and the inspector's lists to move between nodes with the keyboard."></div>
          <div class="tpo-empty" id="tpo-empty" hidden></div><div class="tpo-legend" id="tpo-legend"></div>
          <div class="tpo-zoom" role="group" aria-label="Zoom"><button type="button" class="iconbtn" data-tz="in" aria-label="Zoom in">${icon("plus")}</button><button type="button" class="iconbtn" data-tz="out" aria-label="Zoom out">${icon("minus")}</button><button type="button" class="iconbtn" data-tz="fit" aria-label="Fit the graph">${icon("fit")}</button></div></div>
        <aside class="tpo-aside card" id="tpo-aside" aria-label="Inspector"></aside></div>
      <div class="tpo-time card" id="tpo-time"></div></div>`;
    wire();
  }

  function drawBar() {
    const b = q("#tpo-bar"); if (!b || !data) return;
    const cnt = Object.fromEntries((data.layers || []).map(l => [l.key, l]));
    const focusId = document.activeElement?.id;
    b.innerHTML = `<div class="tpo-row">
        <div class="seg tpo-seg" role="group" aria-label="Level of detail">${LEVELS.map(([k, l, t]) => `<button type="button" data-tl="${k}" aria-pressed="${level === k}" title="${esc(t)}">${l}</button>`).join("")}</div>
        <div class="tpo-layers" role="group" aria-label="Projections">
          <button type="button" class="tpo-chip ${!layers.size ? "on" : ""}" data-tp="" aria-pressed="${!layers.size}" title="Every projection at once: the unified graph">${icon("layers")}Unified</button>
          ${LAYERS.map(([k, ic, l]) => { const c = cnt[k] || {}; const a = layers.has(k);
            return `<button type="button" class="tpo-chip L-${k} ${a ? "on" : ""} ${c.ok === false ? "off" : ""}" data-tp="${k}" aria-pressed="${a}" title="${esc(l)}${c.ok === false ? `: ${esc(c.why)}` : ""}. Shift-click to add it to the others.">${icon(ic)}<span>${esc(l)}</span><b>${c.count ?? 0}</b></button>`; }).join("")}</div></div>
      <div class="tpo-row">
        <label class="tpo-search">${icon("search")}<input id="tpo-q" type="search" placeholder="Find an agent, sandbox, tool, mission…" value="${esc(query)}" aria-label="Search the graph" autocomplete="off"><small id="tpo-hits">${query ? `${hits.length ? hitI + 1 : 0}/${hits.length}` : ""}</small></label>
        <label class="tpo-sel">Window <select id="tpo-hours" aria-label="Time window">${[[1, "1 hour"], [6, "6 hours"], [24, "24 hours"], [72, "3 days"], [168, "7 days"]].map(([h, l]) => `<option value="${h}" ${+hours === h ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="tpo-sel">Layout <select id="tpo-layout" aria-label="Layout">${[["auto", "Automatic"], ["hierarchy", "Hierarchy"], ["force", "Force"], ["concentric", "By level"], ["grid", "Grid"]].map(([k, l]) => `<option value="${k}" ${layout === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <button type="button" class="btn ghost sm" data-ta="relayout">${icon("reset")}Re-arrange</button>
        <button type="button" class="btn ghost sm" data-ta="expand" ${collapsed.size ? "" : "disabled"}>${icon("expand")}Expand all</button>
        <button type="button" class="btn ghost sm" data-ta="refresh">${icon("cycle")}Refresh</button></div>`;
    if (focusId === "tpo-q") { const i = q("#tpo-q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
    const s = q("#tpo-stats"), st = data.stats || {};
    if (s) s.innerHTML = `<span><b>${num(st.nodes)}</b> nodes</span><span><b>${num(st.edges)}</b> links</span><span title="Entities that appear in more than one projection with the same identity"><b>${num(st.shared)}</b> shared identities</span>
      <span class="${st.running ? "busy" : ""}"><b>${num(st.running)}</b> running</span><span class="${st.failing ? "bad" : ""}"><b>${num(st.failing)}</b> failing</span>`;
    const lg = q("#tpo-legend");
    if (lg) lg.innerHTML = LAYERS.filter(([k]) => !layers.size || layers.has(k)).map(([k, , l]) => `<span><i style="background:${C.L[k]}"></i>${esc(l)}</span>`).join("") +
      `<span><i class="ring busy"></i>running</span><span><i class="ring fail"></i>failing</span><span><i class="ring dbl"></i>in several projections</span>`;
    drawTime();
  }

  function drawTime() {
    const el = q("#tpo-time"); if (!el || !data) return;
    const lo = Math.floor(data.since), hi = Math.ceil(data.at), v = T || hi;
    el.innerHTML = `<button type="button" class="iconbtn" data-ta="play" aria-label="${playing ? "Pause the replay" : "Replay the window"}" title="${playing ? "Pause" : "Replay the window"}">${icon(playing ? "stop" : "play")}</button>
      <label class="tpo-range"><span class="sr">Moment shown</span><input type="range" id="tpo-t" min="${lo}" max="${hi}" step="60" value="${v}" aria-valuetext="${T ? when(T) : "Now (live)"}"></label>
      <span class="tpo-when">${T ? `${icon("clock")}${esc(when(T))}` : `<b class="tpo-live">●</b> Live`}</span>
      <button type="button" class="btn ghost sm" data-ta="now" ${T ? "" : "disabled"}>Now</button>`;
  }

  // ---------- the inspector ----------
  function rowsOf(m) {
    if (!m) return "";
    const L = { tokens: ["Tokens", num], cost: ["Cost", x => `$${(+x).toFixed(3)}`], runs: ["Runs", num], failures: ["Failures", num], calls: ["Calls", num], up: ["Sent", bytes],
                down: ["Received", bytes], conns: ["Connections", num], agents: ["Agents", num], working: ["Working now", num], pending: ["Waiting for you", num],
                cpu_s: ["CPU time", x => `${num(x)} s`], mem_mb: ["Peak memory", x => `${num(x)} MB`], procs: ["Processes at most", num], disk_mb: ["Disk used", x => `${num(x)} MB`],
                events: ["Security events", num] };
    return Object.entries(m).filter(([k]) => L[k]).map(([k, v]) => `<div><dt>${L[k][0]}</dt><dd>${esc(L[k][1](v))}</dd></div>`).join("");
  }
  const nodeBtn = (n, extra = "") => `<button type="button" class="tpo-nb" data-tn="${esc(n.id())}"><i style="background:${C.L[n.data("layers")[0]] || C.t2}"></i><span>${esc(n.data("label"))}</span><small>${esc((TYPE[n.data("type")] || [n.data("type")])[0])}${extra}</small>${n.data("st") && n.data("st") !== "ok" ? `<em class="s-${n.data("st")}">${esc(STL[n.data("st")]?.[1] || "")}</em>` : ""}</button>`;

  function drawAside() {
    const a = q("#tpo-aside"); if (!a) return;
    if (err && !data) { a.innerHTML = `<div class="tpo-in"><h2>Can't show the graph</h2><p class="muted">${esc(err)}</p><button type="button" class="btn sm" data-ta="refresh">Try again</button></div>`; return; }
    if (!data || !cy) { a.innerHTML = `<div class="tpo-in"><p class="muted">Loading the graph…</p></div>`; return; }
    const n = sel ? cy.getElementById(sel) : null;
    if (xv) return drawExec(a);
    if (cmp?.b) return drawCompare(a);
    if (!n || n.empty()) return drawSummary(a);
    const d = n.data(), t = TYPE[d.type] || [d.type], st = STL[d.st] || STL.ok;
    const groups = {};
    n.connectedEdges().forEach(e => {
      const out = e.source().same(n), other = out ? e.target() : e.source(), k = `${out ? "" : "← "}${EDGE[e.data("kind")] || e.data("kind")}`;
      (groups[k] = groups[k] || []).push([other, e]);
    });
    const hidden = n.connectedEdges().filter(e => e.hasClass("hide")).length;
    const imp = mode === "impact" ? impactOf(n) : null;
    const span = d.t0 ? `${when(d.t0)}${d.t1 ? ` → ${when(d.t1)} (${dur(d.t1 - d.t0)})` : d.status === "busy" ? " → running" : ""}` : "";
    a.innerHTML = `<div class="tpo-in">
      <div class="tpo-ih"><span class="tpo-type"><i style="background:${C.L[d.layers[0]]}"></i>${esc(t[0])}</span><button type="button" class="iconbtn" data-ta="close" aria-label="Close the inspector">${icon("close")}</button></div>
      <h2>${esc(d.label)}</h2>${d.sub ? `<p class="muted">${esc(d.sub)}</p>` : ""}
      <p>${badge(st[0], st[1])}${T ? ` <small class="muted">at ${esc(when(T))}</small>` : ""}</p>
      <div class="tpo-in-sec"><h3>Appears in</h3><div class="tpo-in-layers">${d.layers.map(l => `<button type="button" class="tpo-chip L-${l} sm" data-tp1="${l}" title="Show the ${esc(LNAME[l])} projection, keeping this node selected">${esc(LNAME[l])}</button>`).join("")}</div>
        ${d.layers.length > 1 ? `<p class="muted small">One identity in ${d.layers.length} projections.</p>` : ""}</div>
      ${d.m || span ? `<dl class="tpo-dl">${span ? `<div><dt>When</dt><dd>${esc(span)}</dd></div>` : ""}${rowsOf(d.m)}${d.exit != null ? `<div><dt>Exit code</dt><dd>${esc(d.exit)}</dd></div>` : ""}${d.size ? `<div><dt>Size</dt><dd>${esc(d.size)}</dd></div>` : ""}${d.mission ? `<div><dt>Mission</dt><dd>${esc(d.mission)}</dd></div>` : ""}${d.egress ? `<div><dt>Internet policy</dt><dd>${esc(d.egress)}</dd></div>` : ""}${d.ws ? `<div><dt>Workspace snapshot</dt><dd>${esc(d.ws)}</dd></div>` : ""}${d.ip ? `<div><dt>Address</dt><dd>${esc(d.ip)}</dd></div>` : ""}${d.cpu_used != null ? `<div><dt>CPU</dt><dd>${esc(d.cpu_used)}${d.cpu ? ` / ${esc(d.cpu)}` : ""} cores</dd></div>` : ""}${d.memory_used ? `<div><dt>Memory</dt><dd>${esc(bytes(d.memory_used))}${d.memory ? ` / ${esc(bytes(d.memory))}` : ""}</dd></div>` : ""}</dl>` : ""}
      ${[["error", "Error"], ["problem", "Problem"], ["why", "Refused because"], ["message", "Status"], ["body", "Details"], ["output", "Output"]].filter(([k]) => d[k]).map(([k, l]) => `<div class="tpo-in-sec"><h3>${l}</h3><pre class="tpo-pre">${esc(d[k])}</pre></div>`).join("")}
      <div class="tpo-acts">
        <button type="button" class="btn sm ${mode === "trace" ? "on" : "ghost"}" data-ta="trace" aria-pressed="${mode === "trace"}" title="Highlight the whole path through this node">${icon("route")}Trace</button>
        <button type="button" class="btn sm ${mode === "impact" ? "on" : "ghost"}" data-ta="impact" aria-pressed="${mode === "impact"}" title="What depends on this node: what stops if it fails">${icon("alert")}Impact</button>
        <button type="button" class="btn sm ghost" data-ta="compare" title="Pick a second node to compare with">${icon("swap")}${cmpPick ? "Pick a node…" : "Compare"}</button>
        ${hasKids.get(d.id) ? `<button type="button" class="btn sm ghost" data-ta="toggle">${icon(collapsed.has(d.id) ? "expand" : "shrink")}${collapsed.has(d.id) ? "Expand" : "Collapse"}</button>` : ""}
        ${d.type === "sandbox" && /^sbx:\d+$/.test(d.id) ? `<button type="button" class="btn sm ghost" data-tx="${esc(d.id.slice(4))}" title="What this run was asked, what it used, what it reached and what it changed">${icon("list")}Execution record</button>` : ""}
        ${d.link ? `<button type="button" class="btn sm ghost" data-go="${esc(d.link)}">${icon("external")}Open</button>` : ""}</div>
      ${imp ? `<div class="tpo-in-sec"><h3>Impact: ${plural(imp.nodes.length, "dependent")}</h3>${imp.nodes.length ? `<p class="muted small">If this fails, these depend on it (directly or through others).</p>
        <div class="tpo-nbs">${imp.nodes.sort((x, y) => x.data("lv") - y.data("lv")).slice(0, 40).map(x => nodeBtn(x)).join("")}</div>` : `<p class="muted small">Nothing in this window depends on it.</p>`}</div>` : ""}
      <div class="tpo-in-sec"><h3>Connections</h3>${Object.keys(groups).length ? Object.entries(groups).map(([k, list]) => `<details ${list.length <= 6 ? "open" : ""}><summary>${esc(k)} <b>${list.length}</b></summary>
        <div class="tpo-nbs">${list.slice(0, 30).map(([o, e]) => nodeBtn(o, e.data("n") > 1 ? ` · ×${e.data("n")}` : "")).join("")}${list.length > 30 ? `<p class="muted small">and ${list.length - 30} more</p>` : ""}</div></details>`).join("") : `<p class="muted small">No connections.</p>`}
        ${hidden ? `<p class="muted small">${plural(hidden, "link")} hidden by the projection, level or time.</p>` : ""}</div></div>`;
  }

  function drawSummary(a) {
    const shared = cy.nodes().filter(n => n.data("layers").length >= 3 && n.visible()).sort((x, y) => y.data("layers").length - x.data("layers").length).slice(0, 8);
    // the same set the header's "failing" counts (every failing node of the graph), visible ones listed, the rest named by number
    const failAll = cy.nodes().filter(n => n.data("st") === "fail"), failing = failAll.filter(n => n.visible()).slice(0, 40);
    const failKinds = Object.entries(failAll.toArray().reduce((a, n) => { const t = n.data("type") || "node"; a[t] = (a[t] || 0) + 1; return a; }, {}))
      .sort((x, y) => y[1] - x[1]).map(([t, k]) => plural(k, String((TYPE[t] || [t])[0]).toLowerCase(), /(x|s|ch|sh)$/i.test((TYPE[t] || [t])[0]) ? "es" : "s")).join(", ");
    const failHidden = failAll.length - failAll.filter(n => n.visible()).length;
    const running = cy.nodes(":visible").filter(n => n.data("st") === "busy" && ["run", "sandbox", "span", "pod", "task", "stage"].includes(n.data("type"))).slice(0, 10);  // work, as topology.py's RUNNING
    const off = (data.layers || []).filter(l => !l.ok);
    a.innerHTML = `<div class="tpo-in"><h2>${layers.size === 1 ? esc(LNAME[[...layers][0]]) : layers.size ? `${layers.size} projections` : "Unified graph"}</h2>
      <p class="muted">${plural(cy.nodes(":visible").length, "node")} and ${plural(cy.edges(":visible").length, "link")} at the ${esc(level)} level, last ${hours < 24 ? plural(hours, "hour") : plural(hours / 24, "day")}${T ? `, as of ${esc(when(T))}` : ""}.</p>
      ${failAll.length ? `<div class="tpo-in-sec"><h3>Failing <b>${failAll.length}</b></h3><p class="muted small">${esc(failKinds)}${failHidden ? `; ${failHidden} hidden by the projection, level or a collapsed group` : ""}${failing.length < failAll.length - failHidden ? `; the first ${failing.length} listed` : ""}.</p>
        ${failing.length ? `<div class="tpo-nbs">${failing.map(n => nodeBtn(n)).join("")}</div>` : ""}</div>` : ""}
      ${running.length ? `<div class="tpo-in-sec"><h3>Running now</h3><div class="tpo-nbs">${running.map(n => nodeBtn(n)).join("")}</div></div>` : ""}
      ${shared.length ? `<div class="tpo-in-sec"><h3>Shared identities</h3><p class="muted small">The same entity in several projections.</p><div class="tpo-nbs">${shared.map(n => nodeBtn(n, ` · ${n.data("layers").length} projections`)).join("")}</div></div>` : ""}
      <div class="tpo-in-sec"><h3>Execution history</h3><p class="muted small">Every sandbox run and VM job of your teams: search by command, output or host.</p>
        <form class="tpo-x-form" data-xf><input id="tpo-xq" type="search" placeholder="pytest, github.com, timeout…" aria-label="Search the execution history"><button type="submit" class="btn sm">${icon("search")}Search</button></form>
        <div class="tpo-acts"><button type="button" class="btn sm ghost" data-ta="xruns">${icon("list")}Latest runs</button><button type="button" class="btn sm ghost" data-ta="xevents">${icon("alert")}Security events</button></div></div>
      ${off.length ? `<div class="tpo-in-sec"><h3>Not available</h3><ul class="tpo-off">${off.map(l => `<li><b>${esc(l.label)}</b>: ${esc(l.why)}</li>`).join("")}</ul></div>` : ""}
      <div class="tpo-in-sec"><h3>How to use it</h3><ul class="tpo-help"><li>Scroll to zoom from the company down to single tool calls; drag nodes to rearrange.</li>
        <li>Double-click a node to collapse or expand what's under it.</li><li>Select a node, then <b>Trace</b> its path, see its <b>Impact</b>, or <b>Compare</b> it with another.</li>
        <li>Drag the time bar to see the window at an earlier moment, or press play to replay it.</li></ul></div></div>`;
  }

  function drawCompare(a) {
    const A = cy.getElementById(cmp.a), Bn = cy.getElementById(cmp.b);
    if (A.empty() || Bn.empty()) { cmp = null; return drawAside(); }
    const facts = n => { const s = n.successors().nodes(), m = n.data("m") || {};
      return { type: (TYPE[n.data("type")] || [n.data("type")])[0], status: STL[n.data("st")]?.[1] || "", layers: n.data("layers").length, links: n.connectedEdges().length,
               downstream: s.length, runs: m.runs ?? s.filter(x => x.data("type") === "run").length, tokens: m.tokens || 0, cost: m.cost || 0,
               failures: (m.failures || 0) + s.filter(x => x.data("st") === "fail").length, tools: new Set(s.filter(x => x.data("type") === "tool").map(x => x.data("label"))).size,
               duration: n.data("t0") && n.data("t1") ? n.data("t1") - n.data("t0") : null }; };
    const fa = facts(A), fb = facts(Bn);
    const R = [["type", "Type"], ["status", "Status"], ["layers", "Projections"], ["links", "Links"], ["downstream", "Downstream nodes"], ["runs", "Runs"], ["tokens", "Tokens"],
               ["cost", "Cost ($)"], ["failures", "Failures (incl. downstream)"], ["tools", "Distinct tools"], ["duration", "Duration"]];
    const fmt = (k, v) => v == null ? "–" : k === "duration" ? dur(v) : k === "cost" ? (+v).toFixed(3) : typeof v === "number" ? num(v) : v;
    a.innerHTML = `<div class="tpo-in"><div class="tpo-ih"><span class="tpo-type">${icon("swap")}Compare</span><button type="button" class="iconbtn" data-ta="close" aria-label="Close the comparison">${icon("close")}</button></div>
      <table class="tpo-cmp"><thead><tr><th scope="col"></th><th scope="col"><button type="button" class="tpo-nb A" data-tn="${esc(cmp.a)}">${esc(A.data("label"))}</button></th><th scope="col"><button type="button" class="tpo-nb B" data-tn="${esc(cmp.b)}">${esc(Bn.data("label"))}</button></th></tr></thead>
      <tbody>${R.map(([k, l]) => `<tr><th scope="row">${l}</th><td>${esc(fmt(k, fa[k]))}</td><td class="${typeof fa[k] === "number" && typeof fb[k] === "number" && fa[k] !== fb[k] ? "diff" : ""}">${esc(fmt(k, fb[k]))}</td></tr>`).join("")}</tbody></table>
      <p class="muted small">Each side's neighbourhood and everything downstream of it is highlighted in its own color on the graph.</p></div>`;
  }

  // ---------- events ----------
  // ---- execution history and run records (exec_env.py): read from /api/exec, shown in the inspector
  const X = "/api/exec";
  const isAdmin = () => Auth.me()?.role === "admin";
  const xstat = r => r.status === "running" ? badge("info", "Running") : r.status === "done" ? badge("ok", "Done") : badge(r.status === "timeout" ? "warn" : "bad", r.status === "failed" ? `Failed${r.exit != null ? ` (exit ${r.exit})` : ""}` : r.status === "timeout" ? "Timed out" : r.status === "error" ? "Error" : r.status);
  async function xload(next) {
    xv = { ...next, loading: true }; drawAside();
    try {
      if (next.kind === "runs") xv = { ...next, rows: (await api(`${X}/runs?limit=40${next.q ? `&q=${encodeURIComponent(next.q)}` : ""}${next.host ? `&host=${encodeURIComponent(next.host)}` : ""}`)).runs };
      else if (next.kind === "events") xv = { ...next, rows: (await api(`${X}/events`)).events };
      else if (next.kind === "run") xv = { ...next, rec: await api(`${X}/runs/${next.id}`) };
    } catch (e) { xv = { ...next, error: e.message }; }
    drawAside();
  }
  function drawExec(a) {
    const head = (title, back) => `<div class="tpo-ih"><span class="tpo-type">${icon("list")}${esc(title)}</span><span>${back ? `<button type="button" class="btn sm ghost" data-ta="xback">${icon("back")}Back</button>` : ""}<button type="button" class="iconbtn" data-ta="xclose" aria-label="Close">${icon("close")}</button></span></div>`;
    if (xv.loading) { a.innerHTML = `<div class="tpo-in">${head("Execution", false)}<p class="muted">Loading…</p></div>`; return; }
    if (xv.error) { a.innerHTML = `<div class="tpo-in">${head("Execution", !!xv.from)}<p class="muted">${esc(xv.error)}</p></div>`; return; }
    if (xv.kind === "runs") {
      a.innerHTML = `<div class="tpo-in">${head("Execution history", false)}<h2>${xv.q ? `Runs matching “${esc(xv.q)}”` : "Latest runs"}</h2>
        <form class="tpo-x-form" data-xf><input id="tpo-xq" type="search" value="${esc(xv.q || "")}" placeholder="Command, output or host" aria-label="Search the execution history"><button type="submit" class="btn sm">${icon("search")}Search</button></form>
        ${xv.rows.length ? `<ul class="tpo-x-list">${xv.rows.map(r => `<li><button type="button" data-tx="${r.id}"><span class="tpo-x-top"><b>#${r.id}</b> ${xstat(r)} <small class="muted">${esc(when(r.started))}${r.kind === "vm" ? " · VM job" : ""}${r.size ? ` · size ${esc(r.size)}` : ""}</small></span>
          <code>${esc(r.command || "")}</code><small class="muted">${esc(r.mission)}${r.cpu_seconds != null ? ` · ${num(r.cpu_seconds)} s CPU · ${num(r.peak_rss_mb)} MB` : ""}${r.hosts ? ` · ${plural(r.hosts, "host")}` : ""}${r.refused ? ` · ${r.refused} refused` : ""}${r.ws_to ? ` · snapshot #${r.ws_to}` : ""}</small></button></li>`).join("")}</ul>`
          : `<p class="muted">No run matches.</p>`}</div>`;
      return;
    }
    if (xv.kind === "events") {
      a.innerHTML = `<div class="tpo-in">${head("Security events", false)}<h2>Security events, last 7 days</h2><p class="muted small">Refused connections, files refused from a save, conflicts, credentials given or refused, stops.</p>
        ${xv.rows.length ? `<ul class="tpo-x-list">${xv.rows.map(e => `<li><${e.run ? `button type="button" data-tx="${e.run}"` : "div"}><span class="tpo-x-top"><b>${esc(e.what)}</b> <small class="muted">${esc(when(e.at))}${e.run ? ` · run #${e.run}` : ""}${e.mission ? ` · ${esc(e.mission)}` : ""}</small></span><small>${esc(e.detail || "")}</small></${e.run ? "button" : "div"}></li>`).join("")}</ul>` : `<p class="muted">Nothing in the last 7 days.</p>`}</div>`;
      return;
    }
    const r = xv.rec, st = r.stats, m = r.manifest, res = m?.result || {}, net = r.net || {}, hosts = Object.entries(net.hosts || {}), wc = r.workspace_changes, c = wc?.counts;
    const row = (k, v) => v == null || v === "" ? "" : `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
    a.innerHTML = `<div class="tpo-in">${head(r.kind === "vm" ? "VM job" : "Sandbox run", !!xv.from)}<h2>Run #${r.id}</h2><p>${xstat(r)} <small class="muted">${esc(when(r.started))}${r.finished ? ` → ${esc(when(r.finished))} (${dur(r.finished - r.started)})` : ""}</small></p>
      <pre class="tpo-pre">${esc(m?.inputs?.command || r.command || "")}</pre>
      <dl class="tpo-dl">${row("Mission", esc(r.mission))}${row("Team", r.team)}${row("Task", r.task)}${row("Started by", esc(r.by || (r.agent ? `agent ${r.agent}` : "")))}${row("Size", esc(r.size))}${row("Internet policy", esc(r.egress))}${row("Exit code", r.exit)}</dl>
      ${st ? `<div class="tpo-in-sec"><h3>${st.live ? "What it has used so far" : "What it used"}</h3><dl class="tpo-dl">${row("CPU time", `${num(st.cpu_seconds)} s`)}${st.live ? row("Memory now", `${num(st.rss_mb)} MB`) + row("Processes now", st.procs) : ""}${row("Peak memory", `${num(st.peak_rss_mb)} MB`)}${row("Processes at most", st.peak_procs)}${row("Disk used", st.disk_mb ? `${num(st.disk_mb.work)} MB` : null)}${row("Command ran for", st.wall_s != null ? dur(st.wall_s) : null)}${st.timed_out ? row("Time limit", "reached") : ""}${st.cgroup?.oom_kills ? row("Killed for memory", st.cgroup.oom_kills) : ""}</dl>
        <p class="muted small">${st.live ? "Still running: reported from inside the run every few seconds, last at " + new Date((st.at || 0) * 1000).toLocaleTimeString() + "." : st.partial ? "The run ended without its final report: these are the last figures it sent while running." : "Reported from inside the run: its own word, sampled every few seconds."}</p>
        ${st.tree_at_peak?.length ? `<details><summary>Processes at the memory peak <b>${st.tree_at_peak.length}</b></summary><table class="tpo-x-t"><thead><tr><th>Process</th><th>Memory</th><th>CPU</th></tr></thead><tbody>${st.tree_at_peak.slice(0, 15).map(p => `<tr><td><code>${esc((p.cmd || "").slice(0, 70))}</code></td><td>${num(p.rss_mb)} MB</td><td>${num(p.cpu_s)} s</td></tr>`).join("")}</tbody></table></details>` : ""}</div>`
        : r.planned ? "" : `<p class="muted small">This run wasn't planned by the execution fabric, so it has no measurements or manifest.</p>`}
      ${hosts.length || net.refused?.length ? `<div class="tpo-in-sec"><h3>Network</h3><p class="muted small">${bytes(net.down_bytes || 0)} received, ${bytes(net.up_bytes || 0)} sent${net.conns ? `, ${plural(net.conns.length, "connection")} recorded` : ""}.</p>
        ${hosts.length ? `<table class="tpo-x-t"><thead><tr><th>Host</th><th>Connections</th><th>Received</th><th>Sent</th></tr></thead><tbody>${hosts.slice(0, 20).map(([h, v]) => `<tr><td>${esc(h)}</td><td>${v.conns}</td><td>${bytes(v.down)}</td><td>${bytes(v.up)}</td></tr>`).join("")}</tbody></table>` : ""}
        ${net.refused?.length ? `<details open><summary>Refused <b>${net.refused.length}</b></summary><ul class="tpo-off">${net.refused.slice(0, 20).map(x => `<li><b>${esc(x.host)}</b>: ${esc(x.why)}</li>`).join("")}</ul></details>` : ""}</div>` : ""}
      ${r.ws_from || r.ws_to ? `<div class="tpo-in-sec"><h3>Workspace</h3><p>${r.ws_to ? `Started from snapshot #${r.ws_from || 0}, left snapshot <b>#${r.ws_to}</b>.` : `Started from snapshot #${r.ws_from}; changed nothing.`}</p>
        ${c ? `<p class="muted small">${c.added} added, ${c.changed} changed, ${c.removed} removed${c.conflicts ? `, ${c.conflicts} conflict${c.conflicts === 1 ? "" : "s"}` : ""}${c.refused ? `, ${c.refused} left out` : ""}.</p>` : ""}
        ${wc?.conflicts?.length ? `<ul class="tpo-off">${wc.conflicts.slice(0, 10).map(x => `<li><b>${esc(x.path)}</b>: another run changed it too; this run's is kept as ${esc(x.kept_as || "(nothing: it had deleted the file)")}</li>`).join("")}</ul>` : ""}
        ${wc?.refused?.length ? `<ul class="tpo-off">${wc.refused.slice(0, 10).map(x => `<li><b>${esc(x.path)}</b>: ${esc(x.why)}</li>`).join("")}</ul>` : ""}</div>` : ""}
      ${res.events?.length ? `<div class="tpo-in-sec"><h3>Security events</h3><ul class="tpo-off">${res.events.slice(0, 20).map(e => `<li><b>${esc(e.kind.replace(/_/g, " "))}</b>${Object.entries(e).filter(([k]) => !["at", "kind"].includes(k)).map(([k, v]) => ` ${esc(k)}: ${esc(v)}`).join(",")}</li>`).join("")}</ul></div>` : ""}
      ${m ? `<div class="tpo-in-sec"><h3>Manifest</h3><dl class="tpo-dl">${row("Image", `<code>${esc((res.image_id || m.inputs.image || "").slice(0, 26))}…</code>`)}${row("Request", `<code>${esc((m.sha256 || "").slice(0, 16))}…</code>`)}${row("Output", res.output_sha256 ? `<code>${esc(res.output_sha256.slice(0, 16))}…</code>` : null)}${row("Workspace after", res.workspace_tree ? `<code>${esc(res.workspace_tree.slice(0, 16))}…</code>` : null)}${row("Credentials named", esc((m.plan.secrets || []).join(", ")))}</dl>
        ${res.replay ? `<p>${res.replay.same_output && res.replay.same_workspace ? badge("ok", "Reproduced") : badge("warn", "Differs")} <small class="muted">Run again from run #${res.replay.of}: output ${res.replay.same_output ? "the same" : "differs"}, workspace ${res.replay.same_workspace ? "the same" : "differs"}, image ${res.replay.same_image ? "the same" : "differs"}.</small></p>` : ""}
        <p class="muted small">Two runs with the same request were asked to do the same thing in the same environment.</p></div>` : ""}
      ${r.output ? `<div class="tpo-in-sec"><details><summary>Output</summary><pre class="tpo-pre">${esc(r.output.slice(-6000))}</pre></details></div>` : ""}${r.error ? `<div class="tpo-in-sec"><h3>Error</h3><pre class="tpo-pre">${esc(r.error)}</pre></div>` : ""}
      <div class="tpo-acts">${cy?.getElementById(`sbx:${r.id}`).nonempty() ? `<button type="button" class="btn sm ghost" data-tn="sbx:${r.id}" data-xkeep="1">${icon("target")}Show in the graph</button>` : ""}
        ${isAdmin() && m && r.kind !== "vm" && r.status !== "running" ? `<button type="button" class="btn sm ghost" data-ta="xreplay" title="The same command on the same image, from the workspace content this run started from">${icon("refresh")}Run it again</button>` : ""}
        ${isAdmin() && r.status === "running" ? `<button type="button" class="btn sm danger" data-ta="xstop" title="Ends every running run of this mission and refuses new ones until it is lifted">${icon("alert")}Stop this mission's runs</button>` : ""}</div></div>`;
  }

  function wire() {
    if (wired) return; wired = true;
    const r = root();
    r.addEventListener("click", e => {
      const t = e.target;
      const lv = t.closest("[data-tl]"); if (lv) { const was = level; level = lv.dataset.tl; S_("level", level); if ((was === "deep") !== (level === "deep")) load({ relayout: true }); else { applyView(true); drawBar(); } return drawAside(); }
      const p = t.closest("[data-tp]");
      if (p) { const k = p.dataset.tp; if (!k) layers.clear(); else if (e.shiftKey || e.ctrlKey || e.metaKey) { layers.has(k) ? layers.delete(k) : layers.add(k); } else layers = layers.size === 1 && layers.has(k) ? new Set() : new Set([k]);
               S_("layers", [...layers]); applyView(true); drawBar(); return drawAside(); }
      const p1 = t.closest("[data-tp1]"); if (p1) { layers = new Set([p1.dataset.tp1]); S_("layers", [...layers]); applyView(true); drawBar(); return select(sel); }
      const tx = t.closest("[data-tx]"); if (tx) return xload({ kind: "run", id: +tx.dataset.tx, from: xv && xv.kind !== "run" ? xv : null });
      if (t.closest("[data-xkeep]")) xv = null;
      const nb = t.closest("[data-tn]"); if (nb) { const id = nb.dataset.tn; const n = cy?.getElementById(id); if (n && n.hasClass("hide")) { layers.clear(); collapsed.clear(); if (LV[level] < n.data("lv")) level = n.data("lv") === 2 ? "deep" : "operational"; applyView(true); drawBar(); } cmp = null; return select(id); }
      const go = t.closest("[data-go]"); if (go) { const l = go.dataset.go; if (l.startsWith("#control/")) location.hash = l; else setView(l.slice(1)); return; }
      const z = t.closest("[data-tz]"); if (z && cy) { const k = z.dataset.tz; if (k === "fit") cy.fit(cy.elements(":visible"), 30); else cy.zoom({ level: cy.zoom() * (k === "in" ? 1.3 : 1 / 1.3), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }); return; }
      const ac = t.closest("[data-ta]"); if (!ac || ac.disabled) return;
      const k = ac.dataset.ta;
      if (k === "relayout") runLayout();
      else if (k === "expand") { collapsed.clear(); applyView(true); drawBar(); drawAside(); }
      else if (k === "refresh") load({ fresh: true });
      else if (k === "close") { cmp = null; cmpPick = false; select(null); }
      else if (k === "xruns") xload({ kind: "runs" });
      else if (k === "xevents") xload({ kind: "events" });
      else if (k === "xclose") { xv = null; drawAside(); }
      else if (k === "xback") { xv = xv?.from ? { ...xv.from, loading: false } : null; drawAside(); }
      else if (k === "xreplay" && xv?.rec) api(`${X}/runs/${xv.rec.id}/replay`, { method: "POST" }).then(o => { Auth.toast?.(`Started as run #${o.run}. Its record shows the comparison when it ends.`); xload({ kind: "run", id: o.run, from: xv.from }); }).catch(e => Auth.toast?.(e.message));
      else if (k === "xstop" && xv?.rec && window.confirm(`Stop every running run of ${xv.rec.mission}? New runs of it are refused until an administrator lifts the stop.`))
        api(`${X}/stop`, { method: "POST", body: { mission: xv.rec.mission, why: "stopped from the control panel" } }).then(o => { Auth.toast?.(`Stopped: ${o.ended.length} run${o.ended.length === 1 ? "" : "s"} ended.`); xload({ kind: "run", id: xv.rec.id, from: xv.from }); }).catch(e => Auth.toast?.(e.message));
      else if (k === "trace" || k === "impact") { mode = mode === k ? null : k; paintMarks(); drawAside(); }
      else if (k === "compare") { cmp = { a: sel, b: null }; cmpPick = true; drawAside(); Auth.toast?.("Now select the node to compare with."); }
      else if (k === "toggle") toggle(sel);
      else if (k === "play") play();
      else if (k === "now") { stopPlay(); T = null; applyView(false); drawTime(); drawAside(); load(); }
    });
    r.addEventListener("submit", e => {
      if (e.target.matches("[data-xf]")) { e.preventDefault(); const v = e.target.querySelector("input").value.trim(); xload({ kind: "runs", q: v }); }
    });
    r.addEventListener("input", e => {
      if (e.target.id === "tpo-q") { query = e.target.value.trim(); search(); }
      if (e.target.id === "tpo-t") { stopPlay(); const v = +e.target.value; T = v >= Math.floor(data.at) - 60 ? null : v; applyView(false); const w = q(".tpo-when"); if (w) w.innerHTML = T ? `${icon("clock")}${esc(when(T))}` : `<b class="tpo-live">●</b> Live`; q("#tpo-t")?.setAttribute("aria-valuetext", T ? when(T) : "Now (live)"); q('[data-ta="now"]') && (q('[data-ta="now"]').disabled = !T); }
    });
    r.addEventListener("change", e => {
      if (e.target.id === "tpo-hours") { hours = +e.target.value; S_("hours", hours); T = null; load({ fresh: true, relayout: true }); }
      if (e.target.id === "tpo-layout") { layout = e.target.value; S_("layout", layout); runLayout(); }
      if (e.target.id === "tpo-t") drawTime();
    });
    r.addEventListener("keydown", e => {
      if (e.target.id === "tpo-q" && e.key === "Enter") { e.preventDefault(); if (!hits.length) return; hitI = (hitI + 1) % hits.length; const n = cy.getElementById(hits[hitI]); if (n.hasClass("hide")) { layers.clear(); collapsed.clear(); applyView(false); drawBar(); } select(hits[hitI]); const h = q("#tpo-hits"); if (h) h.textContent = `${hitI + 1}/${hits.length}`; }
      if (e.target.id === "tpo-q" && e.key === "Escape") { query = ""; e.target.value = ""; search(); }
    });
    let rt = null;
    const restyle = () => { clearTimeout(rt); rt = setTimeout(() => { if (cy && on) { cy.style(style()); merge(false); drawBar(); } }, 150); };
    new MutationObserver(restyle).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style"] });
    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", restyle);
    document.addEventListener("visibilitychange", () => { if (on && !document.hidden && !T) load(); });
  }
  function search() {
    hits = []; hitI = -1;
    if (query && cy) { const w = query.toLowerCase(); cy.nodes().forEach(n => { const d = n.data(); if (`${d.label} ${d.sub || ""} ${d.id}`.toLowerCase().includes(w)) hits.push(d.id); }); }
    hits.sort((a, b) => cy.getElementById(a).data("lv") - cy.getElementById(b).data("lv"));
    const h = q("#tpo-hits"); if (h) h.textContent = query ? `${hits.length} found` : "";
    paintMarks();
  }

  // time travel: replay the window from its start (or the moment shown) to now in about 20 seconds
  function play() {
    if (playing) return stopPlay();
    const lo = data.since, hi = data.at;
    let t = T && T < hi - 60 ? T : lo;
    const step = (hi - lo) / 160;
    playing = setInterval(() => {
      t += step;
      if (t >= hi) { stopPlay(); T = null; applyView(false); drawTime(); return; }
      T = t; applyView(false);
      const s = q("#tpo-t"); if (s) s.value = Math.round(t);
      const w = q(".tpo-when"); if (w) w.innerHTML = `${icon("clock")}${esc(when(T))}`;
    }, 125);
    drawTime();
  }
  function stopPlay() { if (playing) { clearInterval(playing); playing = null; drawTime(); } }

  // ---------- loading ----------
  async function load({ fresh = false, relayout = false } = {}) {
    if (!on || loading) return;
    loading = true;
    try {
      const d = await api(`${B}?hours=${hours}&level=${level === "deep" ? "deep" : "operational"}${fresh ? `&_=${Date.now()}` : ""}`);
      err = null;
      data = d;
      if (!C) C = tokens();
      const had = !!cy;
      build();
      if (had && relayout) runLayout();
      drawBar();
      if (pendingFocus) { const id = pendingFocus; pendingFocus = null; const n = cy.getElementById(id); if (n.nonempty()) { if (n.hasClass("hide")) { layers.clear(); applyView(true); } select(id); } }
      if (query) search();
      drawAside();
    } catch (e) {
      err = e.status === 403 ? "The system graph covers your agents, and agents are available to administrators only on this server." : e.message || "The graph didn't load.";
      if (!data) drawAside(); else Auth.toast?.(err);
    } finally {
      loading = false;
      const em = q("#tpo-empty"); if (em && cy) em.hidden = cy.nodes(":visible").length > 0;
    }
    schedule();
  }
  function schedule() {  // live: every 15 s while the page shows, not while you look at an earlier moment
    clearTimeout(timer);
    if (on) timer = setTimeout(() => { if (!T && !playing && !document.hidden) load(); else schedule(); }, 15000);
  }

  function open() {
    on = true; skeleton();
    if (!C) C = tokens();
    if (cy) { cy.resize(); applyView(false); }
    drawAside(); load();
  }
  function stop() { on = false; clearTimeout(timer); clearInterval(anim); anim = null; stopPlay(); }
  function route(h) { const m = /^topology\/(.+)$/.exec(h || ""); pendingFocus = m ? decodeURIComponent(m[1]) : null; }
  // show a node from elsewhere (a Control Hub agent, a sandbox): Topology.show("agent:teams:3")
  function show(id) { pendingFocus = id; if (S.view === "topology" && cy) { const n = cy.getElementById(id); if (n.nonempty()) { pendingFocus = null; select(id); return; } } setView("topology"); }

  // a pasted or clicked #topology/<node> link on an open page
  addEventListener("hashchange", () => {
    const m = /^#topology\/(.+)$/.exec(location.hash);
    if (m && Auth.me?.()) { try { show(decodeURIComponent(m[1])); } catch { /* a malformed link: ignore */ } }
  });
  // the sidebar entry shows whenever the Control Hub's does
  const hub = document.getElementById("nav-command");
  const mirror = () => { const b = document.getElementById("nav-topology"); if (hub && b && b.hidden !== hub.hidden) b.hidden = hub.hidden; };
  mirror();
  if (hub) new MutationObserver(mirror).observe(hub, { attributes: true, attributeFilter: ["hidden"] });
  return { open, stop, route, show };
})();
