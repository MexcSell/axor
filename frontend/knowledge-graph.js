/* Knowledge graph (knowledge.js's Connections and the Knowledge Hub's Knowledge graph; knowledge.css .kb-graph).
   A small force layout (seeded, so the same records land in the same places), drawn once into an SVG: a node per record
   (its size from its number of links, its color from its group: a top-level folder, or a scope kind), a line per link
   (red: contradicts, dashed: supersedes). Clicking a node opens the record (data-kb-node, handled by knowledge.js). */
const KGraph = (() => {
  const W = 960, H = 560, PAD = 40;
  const NS = "http://www.w3.org/2000/svg";
  function rng(seed) { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
  function layout(nodes, edges) {
    const r = rng(nodes.length * 7919 + edges.length), n = nodes.length, idx = new Map(nodes.map((x, i) => [x.id, i]));
    const P = nodes.map(() => ({ x: PAD + r() * (W - 2 * PAD), y: PAD + r() * (H - 2 * PAD), dx: 0, dy: 0 }));
    const E = edges.map(e => [idx.get(e.from), idx.get(e.to)]).filter(([a, b]) => a !== undefined && b !== undefined);
    const k = Math.sqrt((W * H) / Math.max(1, n)) * 0.75;
    let t = W / 8;
    for (let it = 0; it < 260; it++) {
      for (const p of P) { p.dx = 0; p.dy = 0; }
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
        let dx = P[i].x - P[j].x, dy = P[i].y - P[j].y, d = Math.hypot(dx, dy) || 0.01;
        const f = (k * k) / d; dx /= d; dy /= d;
        P[i].dx += dx * f; P[i].dy += dy * f; P[j].dx -= dx * f; P[j].dy -= dy * f;
      }
      for (const [a, b] of E) {
        let dx = P[a].x - P[b].x, dy = P[a].y - P[b].y, d = Math.hypot(dx, dy) || 0.01;
        const f = (d * d) / k; dx /= d; dy /= d;
        P[a].dx -= dx * f; P[a].dy -= dy * f; P[b].dx += dx * f; P[b].dy += dy * f;
      }
      for (const p of P) {  // a pull to the middle keeps unlinked records on the canvas
        p.dx += (W / 2 - p.x) * 0.02; p.dy += (H / 2 - p.y) * 0.02;
        const d = Math.hypot(p.dx, p.dy) || 1, m = Math.min(d, t);
        p.x = Math.max(PAD, Math.min(W - PAD, p.x + (p.dx / d) * m)); p.y = Math.max(PAD, Math.min(H - PAD, p.y + (p.dy / d) * m));
      }
      t *= 0.985;
    }
    return { P, E };
  }
  const el = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const [a, v] of Object.entries(attrs)) e.setAttribute(a, v); if (text) e.textContent = text; return e; };
  function draw(svg, g) {
    svg.dataset.drawn = "1";
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.replaceChildren();
    if (!g.nodes.length) return;
    const { P, E } = layout(g.nodes, g.edges);
    const groups = [...new Set(g.nodes.map(x => x.group))];
    const lines = el("g", { class: "kb-g-edges" });
    E.forEach(([a, b], i) => {
      const rel = g.edges[i]?.rel || "";
      lines.append(el("line", { x1: P[a].x, y1: P[a].y, x2: P[b].x, y2: P[b].y, class: `kb-g-e kb-g-${rel}` }));
    });
    svg.append(lines);
    const dots = el("g", { class: "kb-g-nodes" });
    g.nodes.forEach((x, i) => {
      const r = 5 + Math.min(10, Math.sqrt(x.degree || 0) * 2.4);
      const node = el("g", { class: `kb-g-n kb-g-c${groups.indexOf(x.group) % 8}${x.space === "company" ? " co" : ""}`, transform: `translate(${P[i].x.toFixed(1)},${P[i].y.toFixed(1)})`,
                             "data-kb-node": x.id, tabindex: "0", role: "button", "aria-label": x.title });
      node.append(el("title", {}, `${x.title}${x.state ? ` (${x.state})` : ""}`));
      node.append(el("circle", { r }));
      if ((x.degree || 0) >= 2 || g.nodes.length <= 30) node.append(el("text", { x: r + 4, y: 4 }, x.title.length > 34 ? x.title.slice(0, 33) + "…" : x.title));
      dots.append(node);
    });
    svg.append(dots);
    svg.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-kb-node]")) { e.preventDefault(); e.target.closest("[data-kb-node]").dispatchEvent(new MouseEvent("click", { bubbles: true })); } });
    const legend = svg.parentElement?.parentElement?.querySelector(".kb-g-legend");
    if (!legend && svg.parentElement) {
      const ul = document.createElement("ul"); ul.className = "kb-g-legend";
      ul.innerHTML = groups.map((x, i) => `<li><i class="kb-g-c${i % 8}"></i>${esc(String(x).replace(/^\d\d-/, "").replace(/-/g, " "))}</li>`).join("");
      svg.parentElement.after(ul);
    }
  }
  return { draw };
})();
