/* Whiteboard: Miro-style infinite boards (whiteboard.py stores them and runs the live channel).
   A board fills the screen, with floating toolbars: board name, settings, export and find (top left); templates, cursors,
   celebrate, who's here, Present and Share (top right); tools and undo (left); frames (bottom left); zoom, help and the AI
   assistant (bottom right). Without a board open, the view lists your boards with thumbnails and templates.
   Items: sticky notes (13 colours, text that shrinks to fit, author, reactions, quick add), text, shapes (rectangle,
   rounded, ellipse, diamond, triangle, database), connectors that stay attached (straight, elbow, curved, arrowheads,
   labels), lines, pen, highlighter, eraser, frames that carry what's inside them, images, tables, charts (pie, donut, bar,
   line), cards, documents, link cards and comment threads. Most of them rotate.
   Select, marquee, move with smart guides, resize, rotate, group, lock, align and distribute, layer order, copy/paste
   between boards, duplicate, undo/redo, zoom and pan, minimap, grid, find, templates, export (PNG, SVG, JSON, outline),
   import, and Present mode over frames.
   Live: people on a board see each other's cursors and selections move, who's here (go to them or follow them),
   celebrations, and changes the moment they're saved; edits made at the same time merge item by item. */
const Whiteboard = (() => {
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("wb." + k)); localStorage.setItem("wb." + k, JSON.stringify(v)); } catch { return null; } };
  const STICKY = { yellow: "#fff9b1", gold: "#f5d128", orange: "#ffc078", red: "#ffa8a8", pink: "#fcc2d7", violet: "#d0bfff", blue: "#a5d8ff",
    cyan: "#99e9f2", teal: "#96f2d7", lime: "#d8f5a2", green: "#b2f2bb", gray: "#e9ecef", white: "#ffffff" };
  const LEGACY = { purple: "violet" };
  const INK = ["ink", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#4262ff", "#7048e8", "#c2255c", "#868e96"];  // "ink": the theme's text colour
  const FILL = ["none", "#ffffff", "#fff9b1", "#ffc078", "#ffa8a8", "#fcc2d7", "#d0bfff", "#a5d8ff", "#96f2d7", "#d8f5a2", "#e9ecef"];
  const FRAME = ["#ffffff", "#f8f9fa", "#fff9db", "#fff0f6", "#f3f0ff", "#e7f5ff", "#e6fcf5", "#ebfbee"];
  const HL = ["#ffd43b", "#69db7c", "#74c0fc", "#f783ac", "#ffa94d"];
  const CARD = ["#4262ff", "#12a37f", "#f58a07", "#e5387b", "#8c3ef0", "#f5d128", "#868e96"];
  const CHART = ["#4262ff", "#ffd02f", "#ff7a59", "#8fd14f", "#da0063", "#12cdd4", "#9510ac", "#808080"];
  const SHAPES = [["rect", "square", "Rectangle"], ["round", "roundrect", "Rounded rectangle"], ["ellipse", "circle", "Ellipse"], ["diamond", "diamond", "Diamond"], ["triangle", "triangle", "Triangle"], ["cylinder", "cylinder", "Database"]];
  const SIZES = [["S", 14], ["M", 20], ["L", 28], ["XL", 40]];
  const REACT = ["👍", "❤️", "🎉", "💡", "❓", "👀"];
  const CELEBRATE = ["🎉", "👏", "❤️", "🔥", "😂", "👍", "🚀", "💡"];
  const TOOLS = [["select", "pointer", "Select", "V"], ["text", "type", "Text", "T"], ["sticky", "sticky", "Sticky note", "N"], ["shape", "shapes", "Shapes", "R"],
    ["arrow", "arrow", "Connection line", "L"], ["pen", "pen", "Pen", "P"], ["frame", "frame", "Frame", "F"], ["more", "plus", "More tools", ""]];
  const PARENT = { hand: "select", line: "arrow", marker: "pen", eraser: "pen", comment: "more" };
  const KEYS = { v: "select", h: "hand", t: "text", n: "sticky", s: "sticky", r: "shape", o: "shape", l: "arrow", a: "arrow", p: "pen", m: "marker", e: "eraser", f: "frame", c: "comment" };
  const MORE = [["comment", "chat", "Comment", "C"], ["table", "table", "Table"], ["chart", "piechart", "Chart"], ["card", "card", "Card"], ["doc", "doc", "Document"],
    ["link", "link", "Link"], ["image", "image", "Image", "I"], ["mindmap", "globe", "Mind map"], ["templates", "apps", "Templates"]];
  const ROT = new Set(["sticky", "text", "shape", "image", "card", "doc", "link", "chart"]);
  const EDIT_IN_DIALOG = new Set(["card", "doc", "link", "chart"]);
  const CLIP = "subnet-scout-whiteboard:";
  const GRID = 32, MIN_Z = 0.1, MAX_Z = 4, HEX = /^#[0-9a-f]{3,8}$/i, IMG = /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+/=]+$/i;
  const TYPES = new Set(["sticky", "text", "shape", "frame", "draw", "line", "image", "table", "chart", "card", "doc", "link", "comment"]);

  let wired = false, list = { mine: [], shared: [] }, board = null, items = [], base = new Map(), version = 0, dashQ = "";
  let view = { x: 0, y: 0, z: 1 }, tool = "select", shapeKind = "rect", stickyColor = pref("sticky") || "yellow";
  const pen = { color: "ink", sw: 3 }, marker = { color: HL[0], sw: 18 };
  let sel = new Set(), editing = null, editCell = null, editBefore = null, drag = null, spaceDown = false, ctxPop = null, toolPop = null, guides = [], hover = null, find = null, cellSel = null;
  const undo = [], redo = [], els = new Map(), fits = new Map(), pointers = new Map(), curEls = new Map();
  let lastNudge = 0, saving = false, saveTimer = null, pollTimer = null, viewTimer = null, state = "saved", miniRaf = 0;
  let live = null, liveOk = false, others = [], viewers = [], showCursors = pref("cursors") ?? true, following = null, curTimer = 0, curLast = 0, lastPt = null, lastSelKey = "", beat = null, peopleKey = "";
  let grid = pref("grid") ?? true, mini = pref("mini") ?? false, present = null, aiBusy = false, panelOpen = false, threadKey = "", threadDraft = "";

  // ---------- small helpers ----------
  const stage = () => $("#wb-stage");
  const uid = () => Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-4);
  const me = () => Auth.me()?.username || "";
  const num = (v, d = 0) => Number.isFinite(+v) ? +v : d;
  const r1 = v => Math.round(v * 10) / 10;
  const col = (v, d) => v === "ink" || v === "none" || HEX.test(v || "") ? v : d;
  // on the page: "ink" is the theme's text colour and white is the theme's paper, so boards read well in dark mode too
  const paint = v => v === "ink" ? "var(--wb-ink)" : v === "none" || !v ? "transparent" : /^#fff(fff)?$/i.test(v) ? "var(--wb-paper)" : col(v, "transparent");
  const paintX = v => v === "ink" ? "#1e1e1e" : v === "none" || !v ? "none" : col(v, "none");  // in exports
  const light = v => { const m = /^#([0-9a-f]{6})$/i.exec(v || ""); if (!m) return false; const n = parseInt(m[1], 16); return ((n >> 16) * 0.299 + ((n >> 8) & 255) * 0.587 + (n & 255) * 0.114) / 255 > 0.72; };
  const inkOn = (color, fill) => color && color !== "ink" ? paint(col(color, "ink")) : light(fill) && !/^#ffffff$/i.test(fill) ? "#1e1e1e" : "var(--wb-ink)";
  const stickyBg = c => STICKY[c] || STICKY[LEGACY[c]] || (HEX.test(c || "") ? c : STICKY.yellow);
  const safeUrl = u => { u = String(u || "").trim(); if (!/^https?:\/\/[^\s<>"']{1,2000}$/i.test(u)) return ""; try { return new URL(u).href; } catch { return ""; } };
  const byId = id => items.find(x => x.id === id);
  const selected = () => items.filter(x => sel.has(x.id));
  const union = bs => { if (!bs.length) return { x: 0, y: 0, w: 0, h: 0 }; const x = Math.min(...bs.map(b => b.x)), y = Math.min(...bs.map(b => b.y)); return { x, y, w: Math.max(...bs.map(b => b.x + b.w)) - x, h: Math.max(...bs.map(b => b.y + b.h)) - y }; };
  const rectOf = (a, b) => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) });
  const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  const inside = (a, b) => a.x >= b.x && a.y >= b.y && a.x + a.w <= b.x + b.w && a.y + a.h <= b.y + b.h;
  const center = b => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 });
  const grow = (b, n) => ({ x: b.x - n, y: b.y - n, w: b.w + 2 * n, h: b.h + 2 * n });
  const clampZ = z => Math.min(MAX_Z, Math.max(MIN_Z, z));
  const when = ts => { const s = Date.now() / 1000 - ts; return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : s < 172800 ? "yesterday" : new Date(ts * 1000).toLocaleDateString(); };
  const initials = n => esc((n || "?").slice(0, 2).toUpperCase());
  const hue = n => [...(n || "")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  const person = (n, color, cls = "") => `<span class="wb-person ${cls}" style="${color ? `background:${color}` : `--h:${hue(n)}`}" title="${esc(n)}">${initials(n)}</span>`;
  const world = e => { const r = stage().getBoundingClientRect(); return { x: (e.clientX - r.left - view.x) / view.z, y: (e.clientY - r.top - view.y) / view.z }; };
  const viewRect = () => { const r = stage().getBoundingClientRect(); return { x: -view.x / view.z, y: -view.y / view.z, w: r.width / view.z, h: r.height / view.z }; };
  const viewCenter = () => center(viewRect());
  const collab = () => board && (board.shared || !board.mine);
  const dueText = d => /^\d{4}-\d{2}-\d{2}$/.test(d || "") ? new Date(d + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
  // board content can come from other people: keep only the item kinds we draw, with unique ids
  function clean(xs) {
    const seen = new Set();
    return (Array.isArray(xs) ? xs : []).filter(x => x && TYPES.has(x.type)).map(x => { const it = { ...x }; if (!it.id || seen.has(it.id)) it.id = uid(); seen.add(it.id); return it; });
  }
  // a table's shape, whatever was saved: row heights and column widths as weights, and text and fill per cell
  function tbl(it) {
    const R = Math.max(1, Math.min(60, Array.isArray(it.rows) ? it.rows.length : 3)), C = Math.max(1, Math.min(24, Array.isArray(it.cols) ? it.cols.length : 3));
    const w = (a, n) => Array.from({ length: n }, (_, i) => Math.max(0.2, num(a?.[i], 1)));
    const grid2 = (a, f) => Array.from({ length: R }, (_, r) => Array.from({ length: C }, (_, c) => f(a?.[r]?.[c])));
    return { rows: w(it.rows, R), cols: w(it.cols, C), cells: grid2(it.cells, v => String(v ?? "").slice(0, 2000)), fills: grid2(it.fills, v => col(v, "")) };
  }

  // ---------- geometry ----------
  function box(it) {
    if (it.type === "line") return rectOf(...ends(it));
    if (it.type === "comment") { const s = 34 / view.z; return { x: num(it.x), y: num(it.y) - s, w: s, h: s }; }  // a pin that keeps its size on screen
    return { x: num(it.x), y: num(it.y), w: Math.max(1, num(it.w, 1)), h: Math.max(1, num(it.h, 1)) };
  }
  const anchor = end => { const t = end?.id && byId(end.id); return t && t.type !== "line" && t.type !== "comment" ? t : null; };
  function boundary(t, toward) {
    const b = box(t), c = center(b), dx = toward.x - c.x, dy = toward.y - c.y, g = 6;
    if (!dx && !dy) return c;
    if (t.type === "shape" && t.shape === "ellipse") { const k = 1 / Math.hypot(dx / (b.w / 2 + g), dy / (b.h / 2 + g)); return { x: c.x + dx * k, y: c.y + dy * k }; }
    const k = Math.min((b.w / 2 + g) / (Math.abs(dx) || 1e-9), (b.h / 2 + g) / (Math.abs(dy) || 1e-9));
    return { x: c.x + dx * k, y: c.y + dy * k };
  }
  function sideOf(t, toward) {
    const b = box(t), c = center(b), dx = toward.x - c.x, dy = toward.y - c.y, g = 6;
    return Math.abs(dx) >= Math.abs(dy) ? { x: dx > 0 ? b.x + b.w + g : b.x - g, y: c.y } : { x: c.x, y: dy > 0 ? b.y + b.h + g : b.y - g };
  }
  function ends(it) {
    const A = anchor(it.a), B = anchor(it.b);
    const pa = A ? center(box(A)) : { x: num(it.a?.x), y: num(it.a?.y) }, pb = B ? center(box(B)) : { x: num(it.b?.x), y: num(it.b?.y) };
    const at = it.route === "elbow" ? sideOf : boundary;
    return [A ? at(A, pb) : pa, B ? at(B, pa) : pb];
  }
  const bez = (a, c1, c2, b, t) => { const u = 1 - t; return { x: u * u * u * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * b.x, y: u * u * u * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * b.y }; };
  // a connector's path, the points its arrowheads point away from, and where its label goes
  function route(it) {
    const [a, b] = ends(it), dx = b.x - a.x, dy = b.y - a.y, hz = Math.abs(dx) >= Math.abs(dy);
    if (it.route === "elbow") {
      if (hz) { const mx = (a.x + b.x) / 2; return { d: `M${r1(a.x)} ${r1(a.y)}H${r1(mx)}V${r1(b.y)}H${r1(b.x)}`, a, b, fa: { x: mx, y: a.y }, fb: { x: mx, y: b.y }, mid: { x: mx, y: (a.y + b.y) / 2 }, pts: [a, b] }; }
      const my = (a.y + b.y) / 2; return { d: `M${r1(a.x)} ${r1(a.y)}V${r1(my)}H${r1(b.x)}V${r1(b.y)}`, a, b, fa: { x: a.x, y: my }, fb: { x: b.x, y: my }, mid: { x: (a.x + b.x) / 2, y: my }, pts: [a, b] };
    }
    if (it.route === "curve") {
      const k = (hz ? Math.abs(dx) : Math.abs(dy)) / 2;
      const c1 = hz ? { x: a.x + Math.sign(dx) * k, y: a.y } : { x: a.x, y: a.y + Math.sign(dy) * k }, c2 = hz ? { x: b.x - Math.sign(dx) * k, y: b.y } : { x: b.x, y: b.y - Math.sign(dy) * k };
      return { d: `M${r1(a.x)} ${r1(a.y)}C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(b.x)} ${r1(b.y)}`, a, b, fa: c1, fb: c2, mid: bez(a, c1, c2, b, 0.5), pts: [a, b, c1, c2] };
    }
    return { d: `M${r1(a.x)} ${r1(a.y)}L${r1(b.x)} ${r1(b.y)}`, a, b, fa: b, fb: a, mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, pts: [a, b] };
  }
  function head(from, to, size) {
    if (Math.hypot(to.x - from.x, to.y - from.y) < 0.5) return "";
    const ang = Math.atan2(to.y - from.y, to.x - from.x), p = s => ({ x: to.x - size * Math.cos(ang + s), y: to.y - size * Math.sin(ang + s) });
    const p1 = p(0.45), p2 = p(-0.45);
    return `M${r1(to.x)} ${r1(to.y)}L${r1(p1.x)} ${r1(p1.y)}L${r1(p2.x)} ${r1(p2.y)}Z`;
  }
  function smooth(pts) {
    if (!pts.length) return "";
    if (pts.length < 3) return `M${pts[0][0]} ${pts[0][1]}` + pts.slice(1).map(p => `L${p[0]} ${p[1]}`).join("") + (pts.length === 1 ? `l0.1 0` : "");
    let d = `M${pts[0][0]} ${pts[0][1]}`;
    for (let i = 1; i < pts.length - 1; i++) d += `Q${pts[i][0]} ${pts[i][1]} ${r1((pts[i][0] + pts[i + 1][0]) / 2)} ${r1((pts[i][1] + pts[i + 1][1]) / 2)}`;
    const l = pts[pts.length - 1]; return d + `L${l[0]} ${l[1]}`;
  }
  function shapeSvg(it, w, h, P) {
    const sw = num(it.sw, 2), i = sw / 2 + 0.5, dash = it.dash ? `stroke-dasharray:${sw * 3} ${sw * 2};` : "";
    const st = `style="fill:${P(col(it.fill, "#ffffff"))};stroke:${P(col(it.stroke, "ink"))};stroke-width:${sw};${dash}stroke-linejoin:round"`;
    switch (it.shape) {
      case "ellipse": return `<ellipse cx="${w / 2}" cy="${h / 2}" rx="${Math.max(1, w / 2 - i)}" ry="${Math.max(1, h / 2 - i)}" ${st}/>`;
      case "diamond": return `<polygon points="${w / 2},${i} ${w - i},${h / 2} ${w / 2},${h - i} ${i},${h / 2}" ${st}/>`;
      case "triangle": return `<polygon points="${w / 2},${i} ${w - i},${h - i} ${i},${h - i}" ${st}/>`;
      case "cylinder": { const ry = Math.min(h * 0.14, 18), rx = Math.max(1, w / 2 - i);
        return `<path d="M${i} ${ry + i}V${h - ry - i}A${rx} ${ry} 0 0 0 ${w - i} ${h - ry - i}V${ry + i}A${rx} ${ry} 0 0 0 ${i} ${ry + i}Z" ${st}/><path d="M${i} ${ry + i}A${rx} ${ry} 0 0 0 ${w - i} ${ry + i}" style="fill:none;stroke:${P(col(it.stroke, "ink"))};stroke-width:${sw}"/>`; }
      case "round": return `<rect x="${i}" y="${i}" width="${Math.max(1, w - 2 * i)}" height="${Math.max(1, h - 2 * i)}" rx="${Math.min(18, h / 4, w / 4)}" ${st}/>`;
      default: return `<rect x="${i}" y="${i}" width="${Math.max(1, w - 2 * i)}" height="${Math.max(1, h - 2 * i)}" rx="2" ${st}/>`;
    }
  }
  const fmtV = v => Math.abs(v) >= 1000 ? `${r1(v / 1000)}k` : `${r1(v)}`;
  // a chart in a w×h box: pie, donut, bar or line, with a title and labels
  function chartSvg(it, w, h, P) {
    const data = (Array.isArray(it.data) ? it.data : []).slice(0, 12).map((d, i) => ({ label: String(d?.label ?? "").slice(0, 40), value: Math.max(0, num(d?.value)), color: col(d?.color, CHART[i % CHART.length]) }));
    const ink = P("ink"), t = it.title ? `<text x="14" y="24" font-size="14" font-weight="650" style="fill:${ink}">${esc(String(it.title).slice(0, 80))}</text>` : "";
    const top = it.title ? 36 : 12, H = Math.max(20, h - top - 10), total = data.reduce((n, d) => n + d.value, 0);
    if (!data.length || (!total && it.kind !== "bar" && it.kind !== "line")) return t + `<text x="${w / 2}" y="${top + H / 2}" text-anchor="middle" font-size="13" style="fill:${ink};opacity:.5">Double-click to add data</text>`;
    if (it.kind === "bar" || it.kind === "line") {
      const left = 38, right = 12, bottom = 24, cw = Math.max(10, w - left - right), ch = Math.max(10, H - bottom), max = Math.max(...data.map(d => d.value), 1), step = cw / data.length;
      const y = v => top + ch - ch * v / max;
      const ticks = [0, 0.5, 1].map(f => `<line x1="${left}" x2="${w - right}" y1="${r1(y(max * f))}" y2="${r1(y(max * f))}" style="stroke:${ink};opacity:.12"/><text x="${left - 6}" y="${r1(y(max * f) + 4)}" text-anchor="end" font-size="10" style="fill:${ink};opacity:.6">${fmtV(max * f)}</text>`).join("");
      const labels = data.map((d, i) => `<text x="${r1(left + step * (i + 0.5))}" y="${r1(top + ch + 16)}" text-anchor="middle" font-size="10" style="fill:${ink};opacity:.75">${esc(d.label.slice(0, 14))}</text>`).join("");
      if (it.kind === "bar") return t + ticks + data.map((d, i) => { const bw = Math.max(4, step * 0.62); return `<rect x="${r1(left + step * (i + 0.5) - bw / 2)}" y="${r1(y(d.value))}" width="${r1(bw)}" height="${r1(top + ch - y(d.value))}" rx="3" style="fill:${P(d.color)}"/>`; }).join("") + labels;
      const pts = data.map((d, i) => [r1(left + step * (i + 0.5)), r1(y(d.value))]);
      return t + ticks + `<polyline points="${pts.map(p => p.join(",")).join(" ")}" style="fill:none;stroke:${P(data[0].color)};stroke-width:2.5;stroke-linejoin:round"/>` + pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" style="fill:${P(data[i].color)}"/>`).join("") + labels;
    }
    const side = w > H * 1.25, R = Math.max(10, (side ? Math.min(H, w * 0.55) : Math.min(w - 24, H * 0.66)) / 2 - 4), cx = side ? 14 + R : w / 2, cy = top + (side ? H / 2 : R + 2);
    const at = (an, r) => [r1(cx + r * Math.cos(an)), r1(cy + r * Math.sin(an))];
    let a = -Math.PI / 2;
    const slices = data.filter(d => d.value > 0).map(d => {
      const da = d.value / total * Math.PI * 2, a2 = a + da, [x1, y1] = at(a, R), [x2, y2] = at(a2, R), mid = a + da / 2, [lx, ly] = at(mid, R * (it.kind === "donut" ? 0.78 : 0.62));
      const path = da > Math.PI * 2 - 1e-6 ? `<circle cx="${cx}" cy="${cy}" r="${R}" style="fill:${P(d.color)}"/>` : `<path d="M${cx} ${cy}L${x1} ${y1}A${R} ${R} 0 ${da > Math.PI ? 1 : 0} 1 ${x2} ${y2}Z" style="fill:${P(d.color)};stroke:${P("#ffffff")};stroke-width:1.5"/>`;
      a = a2;
      return path + (d.value / total >= 0.07 ? `<text x="${lx}" y="${r1(ly + 4)}" text-anchor="middle" font-size="11" font-weight="650" style="fill:#1e1e1e">${Math.round(d.value / total * 100)}%</text>` : "");
    }).join("");
    const hole = it.kind === "donut" ? `<circle cx="${cx}" cy="${cy}" r="${r1(R * 0.56)}" style="fill:${P("#ffffff")}"/>` : "";
    const legend = data.map((d, i) => {
      const [x, y] = side ? [cx + R + 18, cy - data.length * 9 + i * 18 + 4] : [14 + (i % 2) * (w / 2), cy + R + 18 + Math.floor(i / 2) * 18];
      return `<rect x="${r1(x)}" y="${r1(y - 9)}" width="10" height="10" rx="2" style="fill:${P(d.color)}"/><text x="${r1(x + 15)}" y="${r1(y)}" font-size="11" style="fill:${ink}">${esc(d.label.slice(0, 22))} <tspan style="opacity:.6">${fmtV(d.value)}</tspan></text>`;
    }).join("");
    return t + slices + hole + legend;
  }

  // ---------- rendering ----------
  const reacts = it => {
    const r = Object.entries(it.react || {}).filter(([k, v]) => REACT.includes(k) && Array.isArray(v) && v.length);
    return r.length ? `<div class="wb-reacts">${r.map(([k, v]) => `<span class="${v.includes(me()) ? "mine" : ""}" data-react="${k}" title="${esc(v.join(", "))}">${k}<b>${v.length}</b></span>`).join("")}</div>` : "";
  };
  const align = (v, d) => ["left", "center", "right"].includes(v) ? v : d;
  function html(it) {
    const b = box(it), rot = ROT.has(it.type) ? num(it.rot) : 0, rs = rot ? `;transform:rotate(${rot}deg)` : "";
    const pos = `left:${r1(b.x)}px;top:${r1(b.y)}px;width:${r1(b.w)}px;height:${r1(b.h)}px${rs}`, cls = `wb-it wb-${it.type}${it.locked ? " locked" : ""}`, id = esc(it.id);
    switch (it.type) {
      case "sticky": return `<div class="${cls}" data-id="${id}" style="${pos};--sticky:${stickyBg(it.color)}"><div class="wb-txt" style="text-align:${align(it.align, "center")}">${esc(it.text || "")}</div>${collab() && it.by ? `<span class="wb-by">${esc(it.by)}</span>` : ""}${reacts(it)}</div>`;
      case "text": return `<div class="${cls}" data-id="${id}" style="left:${r1(b.x)}px;top:${r1(b.y)}px;width:${r1(b.w)}px${rs};color:${paint(col(it.color, "ink"))};font-size:${num(it.fs, 20)}px;font-weight:${it.bold ? 700 : 400};text-align:${align(it.align, "left")}"><div class="wb-txt">${esc(it.text || "")}</div>${reacts(it)}</div>`;
      case "shape": return `<div class="${cls}" data-id="${id}" style="${pos}"><svg class="wb-svg" width="${r1(b.w)}" height="${r1(b.h)}">${shapeSvg(it, b.w, b.h, paint)}</svg><div class="wb-txt" style="font-size:${num(it.fs, 16)}px;color:${inkOn(it.color, col(it.fill, "#ffffff"))};font-weight:${it.bold ? 700 : 400};text-align:${align(it.align, "center")}">${esc(it.text || "")}</div>${reacts(it)}</div>`;
      case "frame": return `<div class="${cls}" data-id="${id}" style="${pos};--fill:${paint(col(it.fill, "#ffffff"))}"><div class="wb-frame-title">${esc(it.title || "Frame")}</div></div>`;
      case "image": return `<div class="${cls}" data-id="${id}" style="${pos}">${IMG.test(it.src || "") ? `<img src="${it.src}" alt="" draggable="false">` : `<span class="wb-broken">${icon("image")}</span>`}${reacts(it)}</div>`;
      case "table": {
        const T = tbl(it), headRow = it.head !== false;
        return `<div class="${cls}" data-id="${id}" style="${pos}"><div class="wb-grid" style="grid-template-columns:${T.cols.map(c => r1(c) + "fr").join(" ")};grid-template-rows:${T.rows.map(r => r1(r) + "fr").join(" ")}">${T.cells.map((row, r) => row.map((t, c) =>
          `<div class="wb-cell${headRow && r === 0 ? " head" : ""}" data-cell="${r},${c}" style="${T.fills[r][c] ? `background:${paint(T.fills[r][c])};color:${inkOn("ink", T.fills[r][c])}` : ""}">${esc(t)}</div>`).join("")).join("")}</div></div>`;
      }
      case "chart": return `<div class="${cls}" data-id="${id}" style="${pos}"><svg class="wb-svg" viewBox="0 0 ${r1(b.w)} ${r1(b.h)}">${chartSvg(it, b.w, b.h, paint)}</svg>${reacts(it)}</div>`;
      case "card": return `<div class="${cls}" data-id="${id}" style="${pos};--c:${col(it.color, CARD[0])}"><div class="wb-card-title">${esc(it.title || "Card")}</div>${it.text ? `<div class="wb-card-text">${esc(it.text)}</div>` : ""}
        ${it.who || dueText(it.due) ? `<div class="wb-card-foot">${it.who ? person(it.who, "", "sm") : ""}${dueText(it.due) ? `<span class="wb-due">${icon("calendar")}${esc(dueText(it.due))}</span>` : ""}</div>` : ""}${reacts(it)}</div>`;
      case "doc": return `<div class="${cls}" data-id="${id}" style="${pos}"><div class="wb-doc-title">${esc(it.title || "Untitled document")}</div><div class="wb-doc-body">${Agents.md(String(it.text || "").slice(0, 8000))}</div>${reacts(it)}</div>`;
      case "link": {
        const url = safeUrl(it.url), host = url ? new URL(url).hostname.replace(/^www\./, "") : "";
        return `<div class="${cls}" data-id="${id}" style="${pos}"><div class="wb-link-top"><span class="wb-link-ic">${icon("link")}</span><span class="wb-link-host">${esc(host || "No link yet")}</span>
          ${url ? `<a class="wb-link-open" href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-href title="Open in a new tab" aria-label="Open link">${icon("external")}</a>` : ""}</div>
          <div class="wb-link-title">${esc(it.title || url || "Double-click to add a link")}</div>${it.text ? `<div class="wb-link-text">${esc(it.text)}</div>` : ""}${reacts(it)}</div>`;
      }
      case "comment": { const n = (it.thread || []).length; return `<div class="wb-it wb-comment${it.resolved ? " resolved" : ""}" data-id="${id}" style="left:${r1(num(it.x))}px;top:${r1(num(it.y))}px"><span class="wb-pin" title="${n} comment${n === 1 ? "" : "s"}">${icon("chat")}${n ? `<b>${n}</b>` : ""}</span></div>`; }
      case "draw": {
        const sw = num(it.sw, 3), p = sw + 4, pts = (it.pts || []).filter(q => Array.isArray(q)).map(q => [r1(num(q[0])), r1(num(q[1]))]), d = smooth(pts);
        return `<div class="${cls}" data-id="${id}" style="left:${r1(b.x - p)}px;top:${r1(b.y - p)}px;width:${r1(b.w + 2 * p)}px;height:${r1(b.h + 2 * p)}px"><svg class="wb-svg" viewBox="${-p} ${-p} ${r1(b.w + 2 * p)} ${r1(b.h + 2 * p)}">
          <path d="${d}" style="fill:none;stroke:${paint(col(it.color, "ink"))};stroke-width:${sw};stroke-linecap:round;stroke-linejoin:round;opacity:${it.hl ? 0.45 : 1}"/><path class="wb-hit" d="${d}" style="stroke-width:${Math.max(sw, 14)}"/></svg></div>`;
      }
      case "line": {
        const R = route(it), sw = num(it.sw, 2), pad = 22 + sw * 2, bb = union(R.pts.concat([R.mid]).map(q => ({ x: q.x, y: q.y, w: 0, h: 0 })));
        const ox = bb.x - pad, oy = bb.y - pad, w = bb.w + 2 * pad, h = bb.h + 2 * pad, c = paint(col(it.color, "ink")), size = 9 + sw * 2;
        const heads = (it.end === "arrow" ? head(R.fb, R.b, size) : "") + (it.start === "arrow" ? head(R.fa, R.a, size) : "");
        return `<div class="${cls}" data-id="${id}" style="left:${r1(ox)}px;top:${r1(oy)}px;width:${r1(w)}px;height:${r1(h)}px"><svg class="wb-svg" viewBox="${r1(ox)} ${r1(oy)} ${r1(w)} ${r1(h)}">
          <path d="${R.d}" style="fill:none;stroke:${c};stroke-width:${sw};stroke-linecap:round;stroke-linejoin:round;${it.dash ? `stroke-dasharray:${sw * 3} ${sw * 2};` : ""}"/>${heads ? `<path d="${heads}" style="fill:${c};stroke:${c};stroke-width:1;stroke-linejoin:round"/>` : ""}<path class="wb-hit" d="${R.d}" style="stroke-width:${Math.max(sw, 14)}"/></svg>
          <div class="wb-label" style="left:${r1(R.mid.x - ox)}px;top:${r1(R.mid.y - oy)}px">${esc(it.text || "")}</div></div>`;
      }
    }
    return "";
  }
  // shrink a sticky's text until it fits; words break only at the smallest size
  function fit(el, it, force = false) {
    const t = el.querySelector(".wb-txt"), key = `${it.text}|${it.w}|${it.h}`, f = fits.get(it.id);
    if (!t || !t.clientHeight) return;
    if (!force && f?.key === key) { t.style.fontSize = f.fs + "px"; t.style.overflowWrap = f.wrap; return; }
    const over = () => t.scrollHeight > t.clientHeight + 1 || t.scrollWidth > t.clientWidth + 1;
    t.style.overflowWrap = "normal";
    let lo = 10, hi = Math.max(12, Math.min(32, Math.round(num(it.h, 200) / 6)));
    t.style.fontSize = hi + "px";
    if (!over()) lo = hi;
    while (lo < hi) { const m = Math.ceil((lo + hi) / 2); t.style.fontSize = m + "px"; if (over()) hi = m - 1; else lo = m; }
    t.style.fontSize = lo + "px";
    const wrap = over() ? "anywhere" : "normal"; t.style.overflowWrap = wrap;
    fits.set(it.id, { key, fs: lo, wrap });
  }
  function render() {
    const w = $("#wb-world"); if (!w) return;
    const seen = new Set();
    items.forEach((it, i) => {
      seen.add(it.id);
      let el = els.get(it.id);
      const h = it.id === editing && el ? null : html(it);
      if (h === null) {
        const b = box(it); Object.assign(el.style, { left: b.x + "px", top: b.y + "px", width: b.w + "px", ...(it.type === "text" ? {} : { height: b.h + "px" }) });
      } else if (!el || el._html !== h) {
        const tmp = document.createElement("div"); tmp.innerHTML = h;
        const nel = tmp.firstElementChild; if (!nel) return;
        nel._html = h; if (el) el.replaceWith(nel); else w.appendChild(nel);
        els.set(it.id, nel); el = nel;
        if (it.type === "sticky") fit(el, it);
        if (it.type === "text") {  // its height follows its text; a different measurement here isn't a change to save
          const hh = el.offsetHeight;
          if (hh && Math.abs(hh - num(it.h)) > 0.5) { const was = JSON.stringify(it); it.h = hh; if (base.get(it.id) === was) base.set(it.id, JSON.stringify(it)); }
        }
      }
      el.style.zIndex = (it.type === "frame" ? 1 : it.type === "comment" ? 30000 : 10000) + i;  // frames under everything, comments on top
      el.classList.toggle("sel", sel.has(it.id));
    });
    for (const [id, el] of els) if (!seen.has(id)) { el.remove(); els.delete(id); }
    if (cellSel && (!sel.has(cellSel.id) || !byId(cellSel.id))) cellSel = null;
    $$("#wb-world .wb-cell.on").forEach(c => c.classList.remove("on"));  // the picked cell is a class, not a redraw: double-clicks still land
    if (cellSel) els.get(cellSel.id)?.querySelector(`[data-cell="${cellSel.r},${cellSel.c}"]`)?.classList.add("on");
    drawOverlay(); drawThread(); drawCursors(); queueMini(); hint(); syncTop();
    const k = [...sel].join(","); if (k !== lastSelKey) { lastSelKey = k; if (others.length) sendCursor(lastPt); }
  }

  // ---------- overlay: selection, handles, guides, the selection toolbar ----------
  const scr = b => ({ x: b.x * view.z + view.x, y: b.y * view.z + view.y, w: b.w * view.z, h: b.h * view.z });
  const div = (b, cls) => `<div class="${cls}" style="left:${r1(b.x)}px;top:${r1(b.y)}px;width:${r1(b.w)}px;height:${r1(b.h)}px"></div>`;
  const hpos = (d, w, h) => `left:${r1(d.includes("w") ? 0 : d.includes("e") ? w : w / 2)}px;top:${r1(d.includes("n") ? 0 : d.includes("s") ? h : h / 2)}px`;
  const DIRS = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  function drawOverlay() {
    const ov = $("#wb-overlay"); if (!ov) return;
    const list = present ? [] : selected(), out = [];
    if (hover && byId(hover)) out.push(div(grow(scr(box(byId(hover))), 4), "wb-bind"));
    (find?.hits || []).forEach((id, k) => { const t = byId(id); if (t) out.push(div(grow(scr(box(t)), 3), `wb-hitbox${k === find.i ? " now" : ""}`)); });
    const moving = drag && (drag.mode === "rotate" || (drag.mode === "move" && drag.moved)), one = list.length === 1 ? list[0] : null;
    if (one && ROT.has(one.type) && !editing) {  // the selection frame turns with the item, with a rotate knob
      const b = scr(box(one)), dirs = one.type === "text" ? ["e", "w"] : DIRS, rot = num(one.rot);
      out.push(`<div class="wb-rotbox${one.locked ? " locked" : ""}" style="left:${r1(b.x)}px;top:${r1(b.y)}px;width:${r1(b.w)}px;height:${r1(b.h)}px;transform:rotate(${rot}deg)">
        ${one.locked ? `<span class="wb-lockmark">${icon("lock")}</span>` : moving ? "" : dirs.map(d => `<div class="wb-h" data-h="${d}" style="${hpos(d, b.w, b.h)}"></div>`).join("") + `<div class="wb-rot" data-rot title="Rotate (Shift: 15° steps)">${icon("reset")}</div>`}</div>`);
    } else list.forEach(it => { if (it.type !== "line") out.push(div(grow(scr(box(it)), it.type === "comment" ? 2 : 0), `wb-selbox${it.locked ? " locked" : ""}`)); });
    if (one?.type === "line" && !one.locked && !editing) { const [a, b] = ends(one); [["a", a], ["b", b]].forEach(([k, p]) => out.push(`<div class="wb-end ${one[k]?.id ? "bound" : ""}" data-end="${k}" style="left:${r1(p.x * view.z + view.x)}px;top:${r1(p.y * view.z + view.y)}px"></div>`)); }
    const boxes = list.filter(x => x.type !== "line" && x.type !== "comment");
    if (boxes.length && !editing && !(one && ROT.has(one.type))) {
      const ub = scr(union(boxes.map(box)));
      if (list.length > 1) out.push(div(grow(ub, 4), "wb-selbox multi"));
      if (boxes.some(x => x.locked)) out.push(`<span class="wb-lockmark" style="left:${r1(ub.x + ub.w)}px;top:${r1(ub.y)}px">${icon("lock")}</span>`);
      else if (!moving) DIRS.forEach(d => out.push(`<div class="wb-h" data-h="${d}" style="left:${r1(ub.x + (d.includes("w") ? 0 : d.includes("e") ? ub.w : ub.w / 2))}px;top:${r1(ub.y + (d.includes("n") ? 0 : d.includes("s") ? ub.h : ub.h / 2))}px;cursor:${d}-resize"></div>`));
    }
    if (one && ["sticky", "shape"].includes(one.type) && !one.locked && !drag && !editing) {
      const ub = scr(box(one));
      [["n", ub.x + ub.w / 2, ub.y - 30], ["e", ub.x + ub.w + 30, ub.y + ub.h / 2], ["s", ub.x + ub.w / 2, ub.y + ub.h + 30], ["w", ub.x - 30, ub.y + ub.h / 2]]
        .forEach(([d, x, y]) => out.push(`<button type="button" class="wb-plus" data-plus="${d}" style="left:${r1(x)}px;top:${r1(y)}px" title="${one.type === "sticky" ? "Add a sticky here" : "Add a connected shape"}" aria-label="Add next to it">${icon("plus")}</button>`));
    }
    if (drag?.mode === "marquee") out.push(div(scr(rectOf(drag.start, drag.cur)), "wb-marquee"));
    if (drag?.mode === "create" && ["shape", "frame"].includes(drag.kind)) out.push(div(scr(rectOf(drag.start, drag.cur)), "wb-marquee create"));
    guides.forEach(g => out.push(g.x != null ? `<div class="wb-guide v" style="left:${r1(g.x * view.z + view.x)}px"></div>` : `<div class="wb-guide h" style="top:${r1(g.y * view.z + view.y)}px"></div>`));
    if (list.length && !drag && !editing && one?.type !== "comment") out.push(ctx(list));
    ov.innerHTML = out.join("");
    const c = ov.querySelector(".wb-ctx");
    if (c) { const W = stage().clientWidth, half = c.offsetWidth / 2, x = parseFloat(c.style.left); c.style.left = Math.min(W - half - 8, Math.max(half + 8, x)) + "px"; }
  }
  const cbtn = (act, ic, title, on = false, v = "") => `<button type="button" class="wb-cb ${on ? "on" : ""}" data-act="${act}" ${v !== "" ? `data-v="${esc(String(v))}"` : ""} title="${esc(title)}" aria-label="${esc(title)}" ${on ? 'aria-pressed="true"' : ""}>${icon(ic)}</button>`;
  const tbtn = (act, label, title, on = false, v = "") => `<button type="button" class="wb-cb txt ${on ? "on" : ""}" data-act="${act}" ${v ? `data-v="${esc(v)}"` : ""} title="${esc(title)}" ${on ? 'aria-pressed="true"' : ""}>${label}</button>`;
  const swatch = (act, v, cur, css, title) => `<button type="button" class="wb-sw ${v === cur ? "on" : ""}" data-act="${act}" data-v="${esc(v)}" style="--c:${css}" title="${esc(title)}" aria-label="${esc(title)}"></button>`;
  const popBtn = (name, inner, title) => `<button type="button" class="wb-cb ${ctxPop === name ? "on" : ""}" data-pop="${name}" title="${esc(title)}" aria-label="${esc(title)}" aria-expanded="${ctxPop === name}">${inner}</button>`;
  const dot = (c, kind = "") => `<span class="wb-dot ${kind}" style="--c:${paint(c)}"></span>`;
  const palette = (act, cols, cur) => cols.map(c => swatch(act, c, cur, c === "none" ? "transparent" : paint(c), c === "ink" ? "Default" : c === "none" ? "No fill" : c)).join("");
  const widths = f => [1, 2, 4].map((w, k) => `<button type="button" class="wb-cb ${num(f.sw, 2) === w || (k === 2 && num(f.sw, 2) > 4) ? "on" : ""}" data-act="sw" data-v="${w}" title="${["Thin", "Medium", "Thick"][k]}" aria-label="${["Thin", "Medium", "Thick"][k]} line"><span class="wb-wline" style="height:${w + 1}px"></span></button>`).join("");
  function ctx(list) {
    const ub = scr(union(list.map(box))), types = new Set(list.map(x => x.type)), only = t => types.size === 1 && types.has(t), f = list[0], g = [];
    if (only("sticky")) g.push(popBtn("sticky", dot(stickyBg(f.color), "fill"), "Colour"));
    if ([...types].every(t => t === "text" || t === "shape")) {
      const al = align(f.align, f.type === "text" ? "left" : "center");
      g.push(`${popBtn("ink", dot(col(f.color, "ink")), "Text colour")}<select class="wb-fs" data-act="fs" aria-label="Font size">${SIZES.map(([l, v]) => `<option value="${v}" ${num(f.fs, f.type === "text" ? 20 : 16) === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        ${cbtn("bold", "bold", "Bold", !!f.bold)}${[["left", "textL"], ["center", "textC"], ["right", "textR"]].map(([a, ic]) => cbtn("align", ic, `Align ${a}`, al === a, a)).join("")}`);
    }
    if (only("shape")) g.push(`${popBtn("shape", icon(SHAPES.find(s => s[0] === f.shape)?.[1] || "square"), "Shape")}${popBtn("fill", dot(col(f.fill, "#ffffff"), "fill"), "Fill")}${popBtn("stroke", dot(col(f.stroke, "ink"), "ring"), "Border colour")}${widths(f)}${cbtn("dash", "dash", "Dashed", !!f.dash)}`);
    if (only("line")) g.push(`${popBtn("stroke", dot(col(f.color, "ink"), "ring"), "Colour")}${widths(f)}${cbtn("dash", "dash", "Dashed", !!f.dash)}<span class="wb-csep"></span>
      ${cbtn("start", "left", "Arrow at the start", f.start === "arrow")}${cbtn("end", "right", "Arrow at the end", f.end === "arrow")}<span class="wb-csep"></span>
      ${[["straight", "line"], ["elbow", "elbow"], ["curve", "curve"]].map(([r, ic]) => cbtn("route", ic, r[0].toUpperCase() + r.slice(1), (f.route || "straight") === r, r)).join("")}`);
    if (only("draw")) g.push(`${popBtn("stroke", dot(col(f.color, "ink"), "ring"), "Colour")}${widths(f)}`);
    if (only("frame")) g.push(`${popBtn("fill", dot(col(f.fill, "#ffffff"), "fill"), "Background")}${cbtn("present-frame", "present", "Present from this frame")}`);
    if (only("card")) g.push(`${CARD.map(c => swatch("card-color", c, col(f.color, CARD[0]), c, "Colour")).join("")}${cbtn("edit", "edit", "Edit the card")}`);
    if (list.length === 1 && ["doc", "link"].includes(f.type)) g.push(cbtn("edit", "edit", `Edit the ${f.type === "doc" ? "document" : "link"}`));
    if (list.length === 1 && f.type === "chart") g.push(cbtn("edit", "edit", "Edit the data") + ["pie", "donut", "bar", "line"].map(k => tbtn("chart-kind", k[0].toUpperCase() + k.slice(1), `${k} chart`, (f.kind || "pie") === k, k)).join(""));
    if (only("table") && list.length === 1) g.push(`${tbtn("row-add", "+ Row", "Add a row")}${tbtn("col-add", "+ Column", "Add a column")}${cellSel ? tbtn("row-del", "− Row", "Delete the selected row") + tbtn("col-del", "− Column", "Delete the selected column") : ""}
      ${popBtn("cellfill", dot(cellSel ? tbl(f).fills[cellSel.r][cellSel.c] || "none" : "none", "fill"), cellSel ? "Cell colour" : "Header row colour (pick a cell to colour just that)")}${cbtn("head", "bold", "Header row", f.head !== false)}`);
    if (list.length === 1 && ["sticky", "shape", "text", "image", "card", "doc", "chart"].includes(f.type)) g.push(popBtn("react", icon("smile"), "React"));
    if (list.length > 1) g.push(`${popBtn("align", icon("alignL"), "Align and distribute")}${list.some(x => x.group) ? cbtn("ungroup", "group", "Ungroup (Ctrl+Shift+G)", true) : cbtn("group", "group", "Group (Ctrl+G)")}`);
    const locked = list.every(x => x.locked);
    g.push(`${cbtn("lock", locked ? "lock" : "unlock", locked ? "Unlock (Ctrl+L)" : "Lock (Ctrl+L)", locked)}${cbtn("delete", "trash", "Delete (Del)")}${popBtn("more", icon("dots"), "More")}`);
    let p = "";
    if (ctxPop === "sticky") p = Object.keys(STICKY).map(k => swatch("color", k, STICKY[f.color] ? f.color : LEGACY[f.color] || "yellow", STICKY[k], k)).join("");
    if (ctxPop === "ink") p = palette("color", INK, col(f.color, "ink"));
    if (ctxPop === "fill") p = palette("fill", f.type === "frame" ? FRAME : FILL, col(f.fill, "#ffffff"));
    if (ctxPop === "stroke") p = palette("stroke", f.type === "draw" && f.hl ? HL : INK, col(f.type === "shape" ? f.stroke : f.color, "ink"));
    if (ctxPop === "cellfill") p = palette("cellfill", FILL, "");
    if (ctxPop === "shape") p = SHAPES.map(([k, ic, l]) => cbtn("shape", ic, l, f.shape === k, k)).join("");
    if (ctxPop === "react") p = REACT.map(r => `<button type="button" class="wb-emoji ${(f.react?.[r] || []).includes(me()) ? "on" : ""}" data-act="react" data-v="${r}" aria-label="React ${r}">${r}</button>`).join("");
    if (ctxPop === "align") p = [["l", "alignL", "Left"], ["c", "alignC", "Centre"], ["r", "alignR", "Right"], ["t", "alignT", "Top"], ["m", "alignM", "Middle"], ["b", "alignB", "Bottom"]].map(([k, ic, l]) => cbtn("align-items", ic, `Align ${l.toLowerCase()}`, false, k)).join("")
      + (list.length > 2 ? `<span class="wb-csep"></span>${cbtn("distribute", "distH", "Distribute horizontally", false, "h")}${cbtn("distribute", "distV", "Distribute vertically", false, "v")}` : "");
    if (ctxPop === "more") p = `<div class="wb-more">${[["duplicate", "copy", "Duplicate", "Ctrl+D"], ["copy", "file", "Copy", "Ctrl+C"], ["front", "front", "Bring to front", "Ctrl+]"], ["forward", "up", "Bring forward", "]"],
      ["backward", "down", "Send backward", "["], ["back", "back", "Send to back", "Ctrl+["], list.some(x => num(x.rot)) && ["unrotate", "reset", "Reset rotation", ""], ["comment-here", "chat", "Comment on this", ""], ["zoomsel", "fit", "Zoom to selection", "Shift+2"], ["png-sel", "download", "Export selection as PNG", ""]]
      .filter(Boolean).map(([a, ic, l, k]) => `<button type="button" class="mi" data-act="${a}">${icon(ic)}<span>${l}</span><kbd>${k}</kbd></button>`).join("")}</div>`;
    const top = ub.y - 60 < 70 ? ub.y + ub.h + 18 : ub.y - 56;
    return `<div class="wb-ctx" style="left:${r1(ub.x + ub.w / 2)}px;top:${r1(top)}px" role="toolbar" aria-label="Selection">${g.map(x => `<div class="wb-cg">${x}</div>`).join('<span class="wb-csep"></span>')}${p ? `<div class="wb-cpop ${ctxPop === "more" ? "menuish" : ""}">${p}</div>` : ""}</div>`;
  }

  // ---------- comments: a thread next to its pin ----------
  function threadPos(it) {
    const p = scr(box(it)), st = stage();
    return { left: r1(Math.max(8, Math.min(st.clientWidth - 336, p.x + p.w + 10))) + "px", top: r1(Math.max(70, Math.min(st.clientHeight - 320, p.y))) + "px" };
  }
  function drawThread() {
    const holder = $("#wb-thread"); if (!holder) return;
    const it = sel.size === 1 && !present ? byId([...sel][0]) : null;
    if (!it || it.type !== "comment") { if (threadKey) { holder.innerHTML = ""; threadKey = ""; } return; }
    const key = `${it.id}|${JSON.stringify(it.thread || [])}|${!!it.resolved}`;
    if (key === threadKey && holder.firstElementChild) return void Object.assign(holder.firstElementChild.style, threadPos(it));
    const focused = document.activeElement?.matches?.("[data-thread-input]");
    threadKey = key;
    const msgs = it.thread || [], pos = threadPos(it);
    holder.innerHTML = `<div class="wb-thread" style="left:${pos.left};top:${pos.top}">
      <div class="wb-th-head"><b>${msgs.length ? `Comment${msgs.length > 1 ? `s · ${msgs.length}` : ""}` : "New comment"}</b>${it.resolved ? `<span class="badge clear">Resolved</span>` : ""}<span class="ac-spacer"></span>
        ${msgs.length ? `<button type="button" class="wb-cb ${it.resolved ? "on" : ""}" data-act="resolve" title="${it.resolved ? "Reopen" : "Resolve"}" aria-label="${it.resolved ? "Reopen" : "Resolve"}">${icon("check")}</button><button type="button" class="wb-cb" data-act="delete" title="Delete the thread" aria-label="Delete the thread">${icon("trash")}</button>` : ""}
        <button type="button" class="wb-cb" data-act="close-thread" title="Close" aria-label="Close">${icon("close")}</button></div>
      ${msgs.length ? `<div class="wb-th-list">${msgs.map(m => `<div class="wb-th-msg">${person(m.by)}<div><b>${esc(m.by || "someone")}</b> <small class="faint">${m.ts ? when(m.ts) : ""}</small><p>${esc(m.text || "")}</p></div></div>`).join("")}</div>` : ""}
      <div class="wb-th-form"><textarea data-thread-input rows="2" maxlength="2000" placeholder="${msgs.length ? "Reply…" : "Write a comment…"} (Enter to send)">${esc(threadDraft)}</textarea><button type="button" class="btn sm primary" data-act="reply" aria-label="Send">${icon("send")}</button></div></div>`;
    const ta = holder.querySelector("[data-thread-input]");
    if (focused || !msgs.length) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
  }
  function reply() {
    const it = byId([...sel][0]), ta = $("[data-thread-input]"), text = (ta?.value || "").trim();
    if (!it || it.type !== "comment" || !text) return;
    snap(); it.thread = [...(it.thread || []), { by: me(), text: text.slice(0, 2000), ts: Math.round(Date.now() / 1000) }]; delete it.resolved;
    threadDraft = ""; threadKey = ""; render(); changed();
    $("[data-thread-input]")?.focus();
  }
  function closeThread() {
    const it = byId([...sel][0]);
    if (it?.type === "comment" && !(it.thread || []).length) { items = items.filter(x => x !== it); undo.pop(); }  // a pin nobody wrote in goes away
    sel.clear(); threadDraft = ""; render();
  }

  // ---------- others: cursors and selections ----------
  function drawCursors() {
    const c = $("#wb-cursors"); if (!c) return;
    const show = showCursors && !present, seen = new Set();
    for (const o of show ? others : []) {
      if (o.x == null || o.y == null) continue;
      seen.add(o.name);
      let el = curEls.get(o.name);
      if (!el) { el = document.createElement("div"); el.className = "wb-cur"; el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 2.5l15.5 8-7 2.2L9.8 20z"/></svg><span></span>`; c.appendChild(el); curEls.set(o.name, el); }
      el.style.setProperty("--c", o.color); el.querySelector("span").textContent = o.name;
      el.style.transform = `translate(${r1(o.x * view.z + view.x)}px, ${r1(o.y * view.z + view.y)}px)`;
    }
    for (const [n, el] of curEls) if (!seen.has(n)) { el.remove(); curEls.delete(n); }
    const os = $("#wb-osel"); if (!os) return;
    os.innerHTML = show ? others.map(o => (o.sel || []).map(byId).filter(Boolean).map((it, k) => { const b = grow(scr(box(it)), 3);
      return `<div class="wb-osel" style="left:${r1(b.x)}px;top:${r1(b.y)}px;width:${r1(b.w)}px;height:${r1(b.h)}px;--c:${o.color}">${k ? "" : `<span>${esc(o.name)}</span>`}</div>`; }).join("")).join("") : "";
  }
  function sendCursor(p) {
    lastPt = p;
    const wait = 80 - (Date.now() - curLast);
    if (wait > 0) { if (!curTimer) curTimer = setTimeout(flushCursor, wait); return; }
    flushCursor();
  }
  function flushCursor() {
    clearTimeout(curTimer); curTimer = 0; curLast = Date.now();
    if (!board || S.view !== "whiteboard" || !stage()) return;
    const v = viewRect();
    api(`/api/boards/${board.id}/cursor`, { method: "POST", body: { x: lastPt ? r1(lastPt.x) : null, y: lastPt ? r1(lastPt.y) : null, sel: [...sel].slice(0, 200), view: [r1(v.x), r1(v.y), r1(v.w), r1(v.h)] } }).catch(() => {});
  }
  function goTo(name, keep = false) {
    const o = others.find(x => x.name === name);
    if (!o) { if (!keep) toast(`${name} isn't looking at the board right now`); return; }
    if (o.view?.length === 4 && o.view[2] > 0) fitTo({ x: o.view[0], y: o.view[1], w: o.view[2], h: o.view[3] }, MAX_Z, 0);
    else if (o.x != null) { const st = stage(); view.x = st.clientWidth / 2 - o.x * view.z; view.y = st.clientHeight / 2 - o.y * view.z; applyView(); }
    if (!keep) { following = null; drawFollow(); }
  }
  function drawFollow() {
    const f = $("#wb-follow"); if (!f) return;
    f.hidden = !following;
    const o = others.find(x => x.name === following);
    f.innerHTML = following ? `<span class="wb-follow-dot" style="background:${o?.color || "#4262ff"}"></span>Following ${esc(following)}<button type="button" class="btn sm" data-wb="unfollow">Stop</button>` : "";
    $("#wbb")?.style.setProperty("--follow", o?.color || "#4262ff"); $("#wbb")?.classList.toggle("following", !!following);
  }

  // ---------- view: zoom, pan, grid, minimap ----------
  function applyView() {
    const w = $("#wb-world"), st = stage(); if (!w || !st) return;
    w.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.z})`;
    w.style.setProperty("--iz", 1 / view.z);
    const g = GRID * view.z; st.style.backgroundSize = `${g}px ${g}px`; st.style.backgroundPosition = `${view.x}px ${view.y}px`;
    st.classList.toggle("no-grid", !grid || g < 10);
    const zl = $("#wb-zl"); if (zl) zl.textContent = Math.round(view.z * 100) + "%";
    drawOverlay(); drawThread(); drawCursors(); queueMini();
    clearTimeout(viewTimer); viewTimer = setTimeout(() => { if (board && !present) { pref("view." + board.id, view); if (others.length) sendCursor(lastPt); } }, 300);
  }
  function zoomAt(z, sx, sy) { z = clampZ(z); const wx = (sx - view.x) / view.z, wy = (sy - view.y) / view.z; view = { z, x: sx - wx * z, y: sy - wy * z }; applyView(); }
  const zoomBy = f => { const st = stage(); zoomAt(view.z * f, st.clientWidth / 2, st.clientHeight / 2); };
  function fitTo(b, maxZ = 1, pad = 120) {
    const st = stage(); if (!st) return;
    if (!b.w && !b.h) { view = { x: st.clientWidth / 2, y: st.clientHeight / 2, z: 1 }; return applyView(); }
    const z = clampZ(Math.min(maxZ, (st.clientWidth - pad) / Math.max(b.w, 1), (st.clientHeight - pad) / Math.max(b.h, 1)));
    view = { z, x: st.clientWidth / 2 - (b.x + b.w / 2) * z, y: st.clientHeight / 2 - (b.y + b.h / 2) * z }; applyView();
  }
  const fitAll = () => fitTo(union(items.filter(x => x.type !== "comment").map(box)));
  const queueMini = () => { if (!miniRaf) miniRaf = requestAnimationFrame(() => { miniRaf = 0; drawMini(); }); };
  let miniMap = null;
  function drawMini() {
    const c = $("#wb-mini"), st = stage(); if (!c || !st) return;
    c.hidden = !mini || !items.length || !board || !!present;
    if (c.hidden) return;
    const dpr = devicePixelRatio || 1, W = 200, H = 130;
    if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr; }
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const cs = getComputedStyle(st), vr = viewRect(), all = grow(union([...items.map(box), vr]), 40), s = Math.min(W / all.w, H / all.h);
    const ox = (W - all.w * s) / 2 - all.x * s, oy = (H - all.h * s) / 2 - all.y * s;
    miniMap = { s, ox, oy };
    for (const it of [...items].sort((a, b) => (a.type === "frame" ? 0 : 1) - (b.type === "frame" ? 0 : 1))) {
      const b = box(it), x = b.x * s + ox, y = b.y * s + oy, w = Math.max(1.5, b.w * s), h = Math.max(1.5, b.h * s);
      g.fillStyle = it.type === "frame" ? cs.getPropertyValue("--wb-frame-mini") : it.type === "sticky" ? stickyBg(it.color) : ["shape", "table", "card", "doc", "link", "chart"].includes(it.type) ? cs.getPropertyValue("--wb-shape-mini") : cs.getPropertyValue("--wb-ink-mini");
      g.fillRect(x, y, w, h);
    }
    g.strokeStyle = "#4262ff"; g.lineWidth = 1.5; g.strokeRect(vr.x * s + ox, vr.y * s + oy, vr.w * s, vr.h * s);
  }
  function miniGo(e) {
    if (!miniMap) return;
    const r = $("#wb-mini").getBoundingClientRect(), wx = (e.clientX - r.left - miniMap.ox) / miniMap.s, wy = (e.clientY - r.top - miniMap.oy) / miniMap.s, st = stage();
    view.x = st.clientWidth / 2 - wx * view.z; view.y = st.clientHeight / 2 - wy * view.z; applyView();
  }

  // ---------- changes, undo, saving and live sync ----------
  function snap() { undo.push(JSON.stringify(items)); if (undo.length > 100) undo.shift(); redo.length = 0; }
  function restore(json) { items = clean(JSON.parse(json)); sel = new Set([...sel].filter(id => items.some(x => x.id === id))); render(); changed(); }
  function doUndo() { finishEdit(); if (!undo.length) return; redo.push(JSON.stringify(items)); restore(undo.pop()); }
  function doRedo() { finishEdit(); if (!redo.length) return; undo.push(JSON.stringify(items)); restore(redo.pop()); }
  const pending = () => items.some(x => base.get(x.id) !== JSON.stringify(x)) || [...base.keys()].some(id => !items.some(x => x.id === id));
  function changed() {
    if (!board) return;
    state = "unsaved"; syncTop();
    clearTimeout(saveTimer); saveTimer = setTimeout(save, collab() || others.length ? 250 : 700);  // shared boards save quickly so others see it
  }
  async function save() {
    clearTimeout(saveTimer); saveTimer = null;
    if (!board || saving) return;
    if (!pending()) { state = "saved"; return syncTop(); }
    saving = true; state = "saving"; syncTop();
    const bid = board.id, sent = JSON.parse(JSON.stringify(items));
    try {
      const r = await api(`/api/boards/${bid}`, { method: "PUT", body: { data: { items: sent }, version } });
      saving = false;
      if (board?.id !== bid) return;
      version = r.version; base = new Map(sent.map(x => [x.id, JSON.stringify(x)]));
      const row = [...list.mine, ...list.shared].find(x => x.id === bid);
      if (row) { row.items = sent.length; row.updated = r.updated; row.preview = sent.filter(x => x.type !== "line" && x.type !== "comment").slice(0, 160).map(x => [x.type, x.x, x.y, x.w, x.h, x.type === "sticky" || x.type === "card" ? x.color : x.fill]); }
    } catch (e) {
      saving = false;
      if (board?.id !== bid) return;
      if (e.status === 409 && e.data?.detail?.data) { merge(e.data.detail); return save(); }
      state = "error"; syncTop(e.message); saveTimer = setTimeout(save, 4000); return;
    }
    state = pending() ? "unsaved" : "saved"; syncTop();
    if (state === "unsaved") changed();
  }
  // someone saved in between: theirs for everything we didn't touch, ours for what we changed, added or deleted
  function merge(srv) {
    const local = new Map(items.map(x => [x.id, x])), theirs = clean(srv.data.items);
    const dirty = new Set(items.filter(x => base.get(x.id) !== JSON.stringify(x)).map(x => x.id));
    const gone = new Set([...base.keys()].filter(id => !local.has(id)));
    const out = theirs.filter(x => !gone.has(x.id)).map(x => dirty.has(x.id) ? local.get(x.id) : x), have = new Set(out.map(x => x.id));
    items.forEach(x => { if (dirty.has(x.id) && !have.has(x.id)) out.push(x); });
    items = out; version = srv.version; base = new Map(theirs.map(x => [x.id, JSON.stringify(x)]));
    sel = new Set([...sel].filter(id => items.some(x => x.id === id)));
    render();
  }
  function applyRemote(r) {
    if (!r.data || saving || drag || editing || pending()) return false;
    items = clean(r.data.items); version = r.version; base = new Map(items.map(x => [x.id, JSON.stringify(x)]));
    sel = new Set([...sel].filter(id => items.some(x => x.id === id))); threadKey = ""; render();
    return true;
  }
  let fetching = false;
  async function fetchLatest() {
    if (!board || fetching) return;
    fetching = true; const bid = board.id;
    try { const r = await api(`/api/boards/${bid}/sync?version=${version}`); if (board?.id === bid) { applyRemote(r); syncName(r.name); } } catch {}
    fetching = false;
  }
  function syncName(name) { if (name && board && name !== board.name) { board.name = name; const n = $("[data-wb-name]"); if (n && document.activeElement !== n) n.value = name; } }
  function connectLive() {
    live?.close(); live = null; liveOk = false;
    if (!board || typeof EventSource === "undefined") return;
    const bid = board.id, src = new EventSource(`/api/boards/${bid}/live`);
    src.addEventListener("state", e => { if (board?.id !== bid) return; liveOk = true; try { onLive(JSON.parse(e.data)); } catch {} });
    src.addEventListener("gone", () => { src.close(); if (board?.id === bid) { toast("This board was deleted or is no longer shared with you"); board = null; goHome(); } });
    src.onerror = () => { liveOk = false; };
    live = src;
  }
  function onLive(st) {
    others = st.cursors || [];
    const key = JSON.stringify(st.viewers) + others.map(o => o.name + o.color).join();
    if (key !== peopleKey) { peopleKey = key; viewers = st.viewers || []; people(); }
    drawCursors();
    if (following) goTo(following, true);
    if (st.version && st.version !== version && !saving) fetchLatest();
    for (const ev of st.events || []) {
      if (ev.kind === "react") burst(ev.emoji, ev.by);
      if (ev.kind === "name") syncName(ev.name);
    }
  }
  async function poll() {  // the fallback for browsers or networks without the live stream, and a safety net
    clearTimeout(pollTimer);
    if (!board || S.view !== "whiteboard") return;
    if (!liveOk && document.visibilityState === "visible") {
      const bid = board.id;
      try {
        const r = await api(`/api/boards/${bid}/sync?version=${version}`);
        if (board?.id === bid) { if (JSON.stringify(r.viewers) !== JSON.stringify(viewers)) { viewers = r.viewers; people(); } syncName(r.name); applyRemote(r); }
      } catch (e) { if (e.status === 404) { toast("This board is no longer available"); board = null; return goHome(); } }
    }
    pollTimer = setTimeout(poll, liveOk ? 15000 : 3000);
  }

  // ---------- creating, editing and changing items ----------
  function mk(kind, b, extra = {}) {
    const id = uid();
    if (kind === "sticky") return { id, type: "sticky", x: b.x, y: b.y, w: b.w, h: b.h, color: stickyColor, text: "", by: me(), ...extra };
    if (kind === "text") return { id, type: "text", x: b.x, y: b.y, w: b.w, h: b.h, text: "", color: "ink", fs: 20, ...extra };
    if (kind === "shape") return { id, type: "shape", x: b.x, y: b.y, w: b.w, h: b.h, shape: shapeKind, fill: "#ffffff", stroke: "ink", sw: 2, text: "", fs: 16, ...extra };
    if (kind === "frame") return { id, type: "frame", x: b.x, y: b.y, w: b.w, h: b.h, title: `Frame ${items.filter(x => x.type === "frame").length + 1}`, fill: "#ffffff", ...extra };
    if (kind === "table") return { id, type: "table", x: b.x, y: b.y, w: 480, h: 160, rows: [1, 1, 1, 1], cols: [1, 1, 1], cells: [["Item", "Owner", "Status"], ["", "", ""], ["", "", ""], ["", "", ""]], fills: [], head: true, ...extra };
    if (kind === "chart") return { id, type: "chart", x: b.x, y: b.y, w: 360, h: 220, kind: "pie", title: "Chart", data: [{ label: "A", value: 45 }, { label: "B", value: 30 }, { label: "C", value: 25 }], ...extra };
    if (kind === "card") return { id, type: "card", x: b.x, y: b.y, w: 240, h: 110, title: "New card", text: "", color: CARD[0], who: "", due: "", ...extra };
    if (kind === "doc") return { id, type: "doc", x: b.x, y: b.y, w: 320, h: 380, title: "Untitled document", text: "Write here.\n\n- A point\n- Another point", ...extra };
    if (kind === "link") return { id, type: "link", x: b.x, y: b.y, w: 260, h: 110, url: "", title: "", text: "", ...extra };
    if (kind === "comment") return { id, type: "comment", x: b.x, y: b.y, thread: [], ...extra };
    return { id, ...extra };
  }
  function add(it, opts = {}) { if (it.type === "frame") items.unshift(it); else items.push(it); if (opts.select !== false) sel = new Set([it.id]); }
  // the middle of the view, or the nearest free spot around it, so new things don't land on each other
  function freeSpot(w, h) {
    const c = viewCenter(), taken = items.filter(x => !["frame", "line", "comment", "draw"].includes(x.type)).map(box);
    for (let ring = 0; ring < 6; ring++) for (let k = 0; k < Math.max(1, ring * 8); k++) {
      const a = ring ? k / (ring * 8) * Math.PI * 2 : 0, x = c.x - w / 2 + Math.cos(a) * ring * (w * 0.7 + 30), y = c.y - h / 2 + Math.sin(a) * ring * (h * 0.7 + 30);
      if (!taken.some(b => overlap(b, { x: x - 12, y: y - 12, w: w + 24, h: h + 24 }))) return { x, y };
    }
    return { x: c.x - w / 2, y: c.y - h / 2 };
  }
  function placeAtCenter(kind) {
    const it = mk(kind, { x: 0, y: 0, w: 0, h: 0 }), at = freeSpot(num(it.w), num(it.h));
    it.x = at.x; it.y = at.y;
    snap(); add(it); setTool("select"); render(); changed();
    if (EDIT_IN_DIALOG.has(kind)) editDialog(it);
  }
  function startEdit(id, cell = null) {
    const it = byId(id); if (!it || it.locked || present) return;
    if (EDIT_IN_DIALOG.has(it.type)) return editDialog(it);
    if (it.type === "comment") { sel = new Set([id]); return render(); }
    if (!["sticky", "text", "shape", "frame", "line", "table"].includes(it.type)) return;
    if (it.type === "table" && !cell) cell = cellSel?.id === id ? [cellSel.r, cellSel.c] : [0, 0];
    finishEdit(); sel = new Set([id]); if (it.type === "table") cellSel = { id, r: cell[0], c: cell[1] }; render();
    const el = els.get(id); if (!el) return;
    const t = el.querySelector(it.type === "frame" ? ".wb-frame-title" : it.type === "line" ? ".wb-label" : it.type === "table" ? `[data-cell="${cell[0]},${cell[1]}"]` : ".wb-txt"); if (!t) return;
    editing = id; editCell = it.type === "table" ? cell : null; editBefore = JSON.stringify(it); el.classList.add("wb-editing");
    try { t.contentEditable = "plaintext-only"; } catch { t.contentEditable = "true"; }
    if (t.contentEditable !== "plaintext-only") t.contentEditable = "true";
    t.focus();
    const rg = document.createRange(); rg.selectNodeContents(t); const s = getSelection(); s.removeAllRanges(); s.addRange(rg);
    t.oninput = () => { if (it.type === "sticky") { it.text = t.innerText; fit(el, it, true); } };
    t.onkeydown = ev => {
      ev.stopPropagation();
      if (ev.key === "Escape") { ev.preventDefault(); finishEdit(); stage().focus({ preventScroll: true }); }
      else if (it.type === "sticky" && (ev.key === "Tab" || (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)))) { ev.preventDefault(); finishEdit(); quickAdd(ev.shiftKey ? "s" : "e", true); }
      else if (it.type === "table" && (ev.key === "Tab" || (ev.key === "Enter" && !ev.shiftKey))) {  // next cell
        ev.preventDefault(); const T = tbl(it), [r, c] = editCell; finishEdit();
        let nr = r, nc = c; if (ev.key === "Tab") { nc += ev.shiftKey ? -1 : 1; if (nc >= T.cols.length) { nc = 0; nr++; } if (nc < 0) { nc = T.cols.length - 1; nr--; } } else nr++;
        if (nr >= 0 && nr < T.rows.length) startEdit(id, [nr, nc]);
      }
      else if ((it.type === "frame" || it.type === "line") && ev.key === "Enter") { ev.preventDefault(); finishEdit(); }
    };
    t.onblur = () => setTimeout(() => { if (editing === id) finishEdit(); });
    drawOverlay();
  }
  function finishEdit() {
    if (!editing) return;
    const id = editing, it = byId(id), el = els.get(id), cell = editCell; editing = null; editCell = null;
    if (!it || !el) return render();
    const t = el.querySelector("[contenteditable]"), val = (t?.innerText || "").replace(/ /g, " ").replace(/\n+$/, "");
    if (it.type === "frame") it.title = val.trim().slice(0, 120) || "Frame";
    else if (it.type === "table" && cell) { const T = tbl(it); T.cells[cell[0]][cell[1]] = val.slice(0, 2000); Object.assign(it, { rows: T.rows, cols: T.cols, cells: T.cells, fills: T.fills }); }
    else it.text = val.slice(0, 5000);
    t?.removeAttribute("contenteditable"); el.classList.remove("wb-editing"); el._html = null;
    if (it.type === "text" && !val.trim()) {
      items = items.filter(x => x !== it); sel.delete(id);
      if (!JSON.parse(editBefore || "{}").text) { undo.pop(); render(); return changed(); }  // never typed in: as if it was never made
    }
    const same = JSON.stringify(it) === editBefore && items.includes(it);
    if (!same) { undo.push(editBefore ? JSON.stringify(items.map(x => x === it ? JSON.parse(editBefore) : x)) : JSON.stringify(items)); redo.length = 0; }
    render(); if (!same) changed();
  }
  // cards, documents, links and charts are edited in a dialog
  function editDialog(it) {
    if (!it || it.locked) return;
    const done = fn => { snap(); fn(); $("#modal").close(); render(); changed(); };
    if (it.type === "card") {
      const f = Auth.modal(`<h3>${icon("card")}Card</h3><label class="in"><span>Title</span><input name="title" maxlength="200" value="${esc(it.title || "")}" required></label>
        <label class="in"><span>Description <em class="opt">optional</em></span><textarea name="text" rows="3" maxlength="2000">${esc(it.text || "")}</textarea></label>
        <div class="wb-form-row"><label class="in"><span>Assignee <em class="opt">optional</em></span><input name="who" maxlength="40" value="${esc(it.who || "")}" placeholder="e.g. ${esc(me())}"></label>
        <label class="in"><span>Due date <em class="opt">optional</em></span><input name="due" type="date" value="${esc(dueText(it.due) ? it.due : "")}"></label></div>
        <div class="in"><span>Colour</span><div class="wb-form-sw">${CARD.map(c => `<label class="wb-sw-lbl" style="--c:${c}"><input type="radio" name="color" value="${c}" ${col(it.color, CARD[0]) === c ? "checked" : ""} class="sr"><span></span></label>`).join("")}</div></div>`,
        f => done(() => { Object.assign(it, { title: f.elements.title.value.trim().slice(0, 200) || "Card", text: f.elements.text.value.slice(0, 2000), who: f.elements.who.value.trim().slice(0, 40), due: f.elements.due.value || "", color: f.querySelector("[name=color]:checked")?.value || CARD[0] }); }), { submit: "Save" });
      return f.elements.title.select();
    }
    if (it.type === "doc") {
      const f = Auth.modal(`<h3>${icon("doc")}Document</h3><label class="in"><span>Title</span><input name="title" maxlength="200" value="${esc(it.title || "")}"></label>
        <label class="in"><span>Text <em class="opt">**bold**, \`code\`, - lists, # headings</em></span><textarea name="text" rows="12" maxlength="8000">${esc(it.text || "")}</textarea></label>`,
        f => done(() => { it.title = f.elements.title.value.trim().slice(0, 200) || "Untitled document"; it.text = f.elements.text.value.slice(0, 8000); }), { submit: "Save" });
      return f.elements.text.focus();
    }
    if (it.type === "link") {
      const f = Auth.modal(`<h3>${icon("link")}Link</h3><label class="in"><span>Address</span><input name="url" type="url" maxlength="2000" value="${esc(it.url || "")}" placeholder="https://…" required></label>
        <label class="in"><span>Title <em class="opt">optional</em></span><input name="title" maxlength="200" value="${esc(it.title || "")}"></label>
        <label class="in"><span>Description <em class="opt">optional</em></span><input name="text" maxlength="400" value="${esc(it.text || "")}"></label>`,
        f => { const u = safeUrl(f.elements.url.value); if (!u) throw new Error("Use an address starting with http:// or https://"); done(() => { it.url = u; it.title = f.elements.title.value.trim().slice(0, 200); it.text = f.elements.text.value.trim().slice(0, 400); }); }, { submit: "Save" });
      return f.elements.url.focus();
    }
    if (it.type === "chart") {
      const rows = (Array.isArray(it.data) && it.data.length ? it.data : [{ label: "", value: "" }]).slice(0, 12);
      const row = (d, i) => `<div class="wb-data-row"><input name="l${i}" maxlength="40" value="${esc(d.label ?? "")}" placeholder="Label" aria-label="Label"><input name="v${i}" type="number" step="any" value="${esc(String(d.value ?? ""))}" placeholder="Value" aria-label="Value"><input name="c${i}" type="color" value="${col(d.color, CHART[i % CHART.length]).slice(0, 7)}" aria-label="Colour"></div>`;
      const f = Auth.modal(`<h3>${icon("piechart")}Chart</h3><div class="wb-form-row"><label class="in"><span>Title</span><input name="title" maxlength="80" value="${esc(it.title || "")}"></label>
        <label class="in"><span>Kind</span><select name="kind">${["pie", "donut", "bar", "line"].map(k => `<option ${(it.kind || "pie") === k ? "selected" : ""}>${k}</option>`).join("")}</select></label></div>
        <div class="in"><span>Data</span><div class="wb-data" id="wb-data">${rows.map(row).join("")}</div><button type="button" class="btn sm" data-add-row>${icon("plus")}Add a row</button></div>`,
        f => done(() => {
          const data = []; for (let i = 0; i < 12; i++) { const l = f.elements["l" + i], v = f.elements["v" + i]; if (!l) break; if (l.value.trim() || v.value !== "") data.push({ label: l.value.trim().slice(0, 40), value: Math.max(0, num(v.value)), color: f.elements["c" + i].value }); }
          Object.assign(it, { title: f.elements.title.value.trim().slice(0, 80), kind: f.elements.kind.value, data });
        }), { submit: "Save" });
      $("[data-add-row]", f).onclick = () => { const n = f.querySelectorAll(".wb-data-row").length; if (n >= 12) return toast("Up to 12 rows"); $("#wb-data", f).insertAdjacentHTML("beforeend", row({}, n)); };
    }
  }
  // a new sticky next to the selected one, or a new shape joined to the selected shape by an arrow
  function quickAdd(dir, edit = false) {
    const src = selected()[0]; if (!src || !["sticky", "shape"].includes(src.type)) return;
    const b = box(src), gap = src.type === "sticky" ? 24 : 90, [dx, dy] = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] }[dir];
    let x = b.x + dx * (b.w + gap), y = b.y + dy * (b.h + gap);
    for (let k = 0; k < 20 && items.some(o => !["line", "frame", "comment"].includes(o.type) && overlap(grow(box(o), -1), { x, y, w: b.w, h: b.h })); k++) { if (dx) y += b.h + gap; else x += b.w + gap; }
    snap();
    const { id, react, by, text, group, locked, rot, ...rest } = src, it = { ...rest, id: uid(), x, y, text: "", ...(src.type === "sticky" ? { by: me() } : {}) };
    add(it);
    if (src.type === "shape") items.push({ id: uid(), type: "line", a: { id: src.id }, b: { id: it.id }, color: "ink", sw: 2, end: "arrow", start: "none", route: "elbow" });
    render(); changed();
    if (!inside(box(it), viewRect())) fitTo(union([box(src), box(it)]), view.z);
    if (edit || src.type === "sticky") startEdit(it.id);
  }
  function remove(ids) {
    const gone = new Set(ids);
    items.filter(x => x.type === "line" && !gone.has(x.id)).forEach(l => {  // connectors keep their place when what they joined goes
      const [a, b] = ends(l); if (gone.has(l.a?.id)) l.a = { x: a.x, y: a.y }; if (gone.has(l.b?.id)) l.b = { x: b.x, y: b.y };
    });
    items = items.filter(x => !gone.has(x.id)); ids.forEach(id => sel.delete(id));
  }
  function del() {
    const ids = selected().filter(x => !x.locked).map(x => x.id); if (!ids.length) return;
    snap(); const mark = undo.length; remove(ids); ctxPop = null; render(); changed();
    UI.undoable(`Deleted ${ids.length} item${ids.length === 1 ? "" : "s"}`, () => {  // only while nothing else changed since
      if (undo.length !== mark) throw new Error("The board changed since then: use Undo (Ctrl+Z) to step back.");
      doUndo();
    }, "Restored");
  }
  // copies with new ids; connectors between copied items join the copies, connectors to anything else keep their place
  function clone(src, dx = 0, dy = 0) {
    const map = new Map(src.map(x => [x.id, uid()])), groups = new Map();
    return src.map(x => {
      const c = JSON.parse(JSON.stringify(x)); c.id = map.get(x.id);
      if (c.group) { if (!groups.has(c.group)) groups.set(c.group, uid()); c.group = groups.get(c.group); }
      delete c.react;
      if (c.type === "line") {
        const [a, b] = byId(x.id) ? ends(x) : [c.a, c.b];
        c.a = c.a?.id && map.has(c.a.id) ? { id: map.get(c.a.id) } : { x: num(a?.x) + dx, y: num(a?.y) + dy };
        c.b = c.b?.id && map.has(c.b.id) ? { id: map.get(c.b.id) } : { x: num(b?.x) + dx, y: num(b?.y) + dy };
      } else { c.x = num(c.x) + dx; c.y = num(c.y) + dy; }
      return c;
    });
  }
  function duplicate() { const src = selected(); if (!src.length) return; snap(); const copies = clone(src, 24, 24); copies.forEach(c => add(c, { select: false })); sel = new Set(copies.map(c => c.id)); render(); changed(); }
  function pasteItems(src) {
    src = clean(src); if (!src.length) return;
    const bb = union(src.map(x => x.type === "line" ? rectOf({ x: num(x.a?.x), y: num(x.a?.y) }, { x: num(x.b?.x), y: num(x.b?.y) }) : box(x)));
    const c = viewCenter(), [dx, dy] = overlap(bb, viewRect()) ? [24, 24] : [c.x - bb.x - bb.w / 2, c.y - bb.y - bb.h / 2];
    snap(); const copies = clone(src, dx, dy); copies.forEach(x => add(x, { select: false })); sel = new Set(copies.map(x => x.id)); render(); changed();
  }
  let clip = null;
  function copySel(e) {
    const src = selected(); if (!src.length) return false;
    clip = JSON.parse(JSON.stringify(src.map(x => x.type === "line" ? { ...x, a: x.a?.id && sel.has(x.a.id) ? x.a : { ...ends(x)[0] }, b: x.b?.id && sel.has(x.b.id) ? x.b : { ...ends(x)[1] } } : x)));
    const text = CLIP + JSON.stringify(clip);
    if (e?.clipboardData) { e.clipboardData.setData("text/plain", text); e.preventDefault(); } else navigator.clipboard?.writeText(text).catch(() => {});
    return true;
  }
  function setProp(key, v) {
    const list = selected().filter(x => !x.locked); if (!list.length) return;
    snap();
    for (const it of list) {
      if (key === "color" && it.type === "sticky") { it.color = STICKY[v] ? v : it.color; stickyColor = it.color; pref("sticky", stickyColor); }
      else if (key === "color" && ["text", "shape"].includes(it.type)) it.color = col(v, "ink");
      else if (key === "card-color" && it.type === "card") it.color = col(v, CARD[0]);
      else if (key === "stroke") { if (it.type === "shape") it.stroke = col(v, "ink"); else if (["line", "draw"].includes(it.type)) it.color = col(v, "ink"); }
      else if (key === "fill" && ["shape", "frame"].includes(it.type)) it.fill = col(v, "#ffffff");
      else if (key === "fs" && ["text", "shape"].includes(it.type)) it.fs = num(v, 20);
      else if (key === "sw" && ["shape", "line", "draw"].includes(it.type)) it.sw = it.type === "draw" && it.hl ? num(v, 2) * 8 : num(v, 2);
      else if (key === "bold" && ["text", "shape"].includes(it.type)) it.bold = !list[0].bold;
      else if (key === "align" && ["text", "shape", "sticky"].includes(it.type)) it.align = v;
      else if (key === "dash" && ["shape", "line"].includes(it.type)) it.dash = !list[0].dash;
      else if (key === "shape" && it.type === "shape") it.shape = v;
      else if (key === "start" && it.type === "line") it.start = list[0].start === "arrow" ? "none" : "arrow";
      else if (key === "end" && it.type === "line") it.end = list[0].end === "arrow" ? "none" : "arrow";
      else if (key === "route" && it.type === "line") it.route = v;
      else if (key === "chart-kind" && it.type === "chart") it.kind = v;
      else if (key === "unrotate") delete it.rot;
    }
    render(); changed();
  }
  // tables: rows and columns in and out, and cell colours
  function tableEdit(k, v) {
    const it = selected()[0]; if (!it || it.type !== "table" || it.locked) return;
    snap(); const T = tbl(it), R = T.rows.length, C = T.cols.length, at = cellSel?.id === it.id ? cellSel : null;
    if (k === "row-add") { const r = at ? at.r + 1 : R; T.rows.splice(r, 0, T.rows[Math.min(r, R - 1)]); T.cells.splice(r, 0, Array(C).fill("")); T.fills.splice(r, 0, Array(C).fill("")); it.h = num(it.h) + num(it.h) / R; }
    if (k === "col-add") { const c = at ? at.c + 1 : C; T.cols.splice(c, 0, T.cols[Math.min(c, C - 1)]); T.cells.forEach(row => row.splice(c, 0, "")); T.fills.forEach(row => row.splice(c, 0, "")); it.w = num(it.w) + num(it.w) / C; }
    if (k === "row-del" && at && R > 1) { it.h = num(it.h) * (1 - T.rows[at.r] / T.rows.reduce((a, b) => a + b, 0)); T.rows.splice(at.r, 1); T.cells.splice(at.r, 1); T.fills.splice(at.r, 1); cellSel = null; }
    if (k === "col-del" && at && C > 1) { it.w = num(it.w) * (1 - T.cols[at.c] / T.cols.reduce((a, b) => a + b, 0)); T.cols.splice(at.c, 1); T.cells.forEach(row => row.splice(at.c, 1)); T.fills.forEach(row => row.splice(at.c, 1)); cellSel = null; }
    if (k === "cellfill") { const c = v === "none" ? "" : col(v, ""); if (at) T.fills[at.r][at.c] = c; else T.fills[0] = T.fills[0].map(() => c); }
    if (k === "head") it.head = it.head === false;
    Object.assign(it, { rows: T.rows, cols: T.cols, cells: T.cells, fills: T.fills });
    render(); changed();
  }
  function toggleReact(id, emoji) {
    const it = byId(id); if (!it || !REACT.includes(emoji)) return;
    snap();
    const r = it.react = { ...(it.react || {}) }, who = new Set(r[emoji] || []);
    who.has(me()) ? who.delete(me()) : who.add(me());
    if (who.size) r[emoji] = [...who]; else delete r[emoji];
    if (!Object.keys(r).length) delete it.react;
    render(); changed();
  }
  function order(kind) {
    const s = sel; if (!s.size) return;
    snap();
    if (kind === "front") items = [...items.filter(x => !s.has(x.id)), ...items.filter(x => s.has(x.id))];
    else if (kind === "back") items = [...items.filter(x => s.has(x.id)), ...items.filter(x => !s.has(x.id))];
    else {
      const a = [...items], dir = kind === "forward" ? 1 : -1, idx = a.map((x, i) => s.has(x.id) ? i : -1).filter(i => i >= 0);
      for (const i of dir > 0 ? idx.reverse() : idx) { const j = i + dir; if (j >= 0 && j < a.length && !s.has(a[j].id)) [a[i], a[j]] = [a[j], a[i]]; }
      items = a;
    }
    render(); changed();
  }
  function alignItems(k) {
    const list = selected().filter(x => x.type !== "line" && !x.locked); if (list.length < 2) return;
    snap(); const ub = union(list.map(box));
    list.forEach(it => { const b = box(it);
      if (k === "l") it.x = ub.x; if (k === "c") it.x = ub.x + ub.w / 2 - b.w / 2; if (k === "r") it.x = ub.x + ub.w - b.w;
      if (k === "t") it.y = ub.y; if (k === "m") it.y = ub.y + ub.h / 2 - b.h / 2; if (k === "b") it.y = ub.y + ub.h - b.h; });
    render(); changed();
  }
  function distribute(k) {
    const list = selected().filter(x => x.type !== "line" && !x.locked); if (list.length < 3) return;
    snap(); const X = k === "h" ? "x" : "y", W = k === "h" ? "w" : "h";
    list.sort((a, b) => box(a)[X] - box(b)[X]);
    const total = list.reduce((n, it) => n + box(it)[W], 0), first = box(list[0]), last = box(list[list.length - 1]);
    const gap = (last[X] + last[W] - first[X] - total) / (list.length - 1);
    let at = first[X]; list.forEach(it => { it[X] = at; at += box(it)[W] + gap; });
    render(); changed();
  }
  function group() { const list = selected(); if (list.length < 2) return; snap(); const g = uid(); list.forEach(x => x.group = g); render(); changed(); }
  function ungroup() { const list = selected().filter(x => x.group); if (!list.length) return; snap(); list.forEach(x => delete x.group); render(); changed(); }
  function toggleLock() { const list = selected(); if (!list.length) return; snap(); const on = !list.every(x => x.locked); list.forEach(x => on ? x.locked = true : delete x.locked); render(); changed(); }
  const groupOf = it => it.group ? items.filter(x => x.group === it.group).map(x => x.id) : [it.id];
  function nudge(dx, dy) {
    const list = selected().filter(x => !x.locked); if (!list.length) return;
    if (Date.now() - lastNudge > 800) snap();
    lastNudge = Date.now();
    list.forEach(it => { if (it.type === "line") { if (!it.a?.id) it.a = { x: num(it.a?.x) + dx, y: num(it.a?.y) + dy }; if (!it.b?.id) it.b = { x: num(it.b?.x) + dx, y: num(it.b?.y) + dy }; } else { it.x = num(it.x) + dx; it.y = num(it.y) + dy; } });
    render(); changed();
  }
  async function addImage(file, at, k = 0) {
    if (!file?.type?.startsWith("image/")) return;
    if (file.size > 15e6) return toast("That image is too big (over 15 MB)");
    const url = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); }).catch(() => null);
    if (!url) return toast("Couldn't read that image");
    const img = new Image(); img.src = url;
    try { await img.decode(); } catch { return toast("Couldn't read that image"); }
    const max = 1600, s = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight)), cw = Math.round(img.naturalWidth * s), ch = Math.round(img.naturalHeight * s);
    const c = document.createElement("canvas"); c.width = cw; c.height = ch; c.getContext("2d").drawImage(img, 0, 0, cw, ch);
    const png = /png|gif|webp/.test(file.type) && cw * ch < 600000, src = c.toDataURL(png ? "image/png" : "image/jpeg", 0.85);
    if (!IMG.test(src)) return toast("Couldn't read that image");
    const ws = Math.min(1, 480 / Math.max(cw, ch)), w = cw * ws, h = ch * ws;
    snap(); add({ id: uid(), type: "image", x: at.x - w / 2 + k * 24, y: at.y - h / 2 + k * 24, w, h, src }); render(); changed();
  }

  // ---------- pointer ----------
  const chrome = t => t.closest(".wb-tl, .wb-tr, .wb-left, .wb-bl, .wb-br, .wb-mini, .wb-ctx, .wb-thread, .wb-panel, .wb-ai, .wb-present, .wb-hint-card, .wb-follow");
  function hitAt(e, exclude) {
    for (const el of document.elementsFromPoint(e.clientX, e.clientY)) {
      const id = el.closest?.("#wb-world [data-id]")?.dataset.id, it = id && byId(id);
      if (it && it.type !== "line" && it.type !== "comment" && it !== exclude && it.id !== exclude?.id) return it;
    }
    return null;
  }
  function closePops() { if (toolPop) { toolPop = null; renderLeft(); } }
  function onDown(e) {
    if (!board || chrome(e.target)) return;
    if (following) { following = null; drawFollow(); }
    if (present) { if (e.button === 0) slide(e.clientX < stage().clientWidth / 3 ? -1 : 1); return; }
    if (e.target.closest("a[data-href]")) return;  // a link card's open button
    const re = e.target.closest("[data-react]");
    if (re && e.button === 0) { e.preventDefault(); toggleReact(re.closest("[data-id]").dataset.id, re.dataset.react); return; }
    if (editing) { if (e.target.closest(".wb-editing")) return; finishEdit(); }
    ctxPop = null; closePops();
    stage().focus({ preventScroll: true });
    if (e.button === 2) return;  // the context menu
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { stage().setPointerCapture(e.pointerId); } catch {}
    if (pointers.size === 2) { const [a, b] = [...pointers.values()]; if (drag?.mode === "draw" || drag?.mode === "line") cancelDrag(); drag = { mode: "pinch", d: Math.hypot(a.x - b.x, a.y - b.y), c: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, view: { ...view } }; return; }
    if (pointers.size > 2) return;
    const p = world(e), h = e.target.closest("[data-h]"), rotH = e.target.closest("[data-rot]"), plus = e.target.closest("[data-plus]"), end = e.target.closest("[data-end]");
    const hitEl = e.target.closest("#wb-world [data-id]"), hit = hitEl && byId(hitEl.dataset.id), cellEl = e.target.closest("[data-cell]");
    const t = spaceDown || e.button === 1 ? "hand" : tool;
    if (e.button === 1) e.preventDefault();
    if (t === "hand" || (t === "select" && e.pointerType === "touch" && !hit && !h && !end && !plus && !rotH)) { drag = { mode: "pan", sx: e.clientX, sy: e.clientY, view: { ...view } }; return cursor(); }
    if (plus) { e.preventDefault(); return quickAdd(plus.dataset.plus); }
    if (rotH) { const it = selected()[0]; if (!it || it.locked) return; snap(); drag = { mode: "rotate", it, c: center(box(it)) }; return; }
    if (h) {
      const list = selected().filter(x => !x.locked && x.type !== "line" && x.type !== "comment"); if (!list.length) return;
      snap(); drag = { mode: "resize", dir: h.dataset.h, start: p, bb: union(list.map(box)), single: list.length === 1, orig: list.map(x => ({ it: x, b: box(x), pts: x.pts && x.pts.map(q => [num(q[0]), num(q[1])]) })) }; return;
    }
    if (end) { const it = selected()[0]; if (!it || it.locked) return; snap(); drag = { mode: "end", it, which: end.dataset.end }; return; }
    if (t === "select") {
      if (hit) {
        const ids = groupOf(hit);
        if (e.shiftKey || e.metaKey || e.ctrlKey) { const on = ids.every(id => sel.has(id)); ids.forEach(id => on ? sel.delete(id) : sel.add(id)); }
        else if (!sel.has(hit.id)) sel = new Set(ids);
        if (hit.type === "table" && cellEl && sel.has(hit.id)) { const [r, c] = cellEl.dataset.cell.split(",").map(Number); cellSel = { id: hit.id, r, c }; }
        drag = { mode: "move", start: p, sx: e.clientX, sy: e.clientY, alt: e.altKey, moved: false, hit: hit.id, toggled: e.shiftKey || e.metaKey || e.ctrlKey };
        return render();
      }
      if (!e.shiftKey) sel.clear();
      drag = { mode: "marquee", start: p, cur: p, keep: new Set(sel) };
      return render();
    }
    if (t === "comment") { snap(); const it = mk("comment", { x: p.x, y: p.y }); add(it); threadDraft = ""; setTool("select"); return render(); }
    if (t === "eraser") { snap(); drag = { mode: "erase", erased: 0 }; return eraseAt(e); }
    if (t === "pen" || t === "marker") { drag = { mode: "draw", pts: [[p.x, p.y]], o: t === "pen" ? pen : marker, hl: t === "marker" }; return drawPreview(); }
    if (t === "arrow" || t === "line") {
      const from = hit && !["line", "comment"].includes(hit.type) ? hit : null; snap();
      const it = { id: uid(), type: "line", a: from ? { id: from.id } : { x: p.x, y: p.y }, b: { x: p.x, y: p.y }, color: "ink", sw: 2, start: "none", end: t === "arrow" ? "arrow" : "none", route: t === "arrow" ? (pref("route") || "elbow") : "straight" };
      items.push(it); drag = { mode: "line", it, sx: e.clientX, sy: e.clientY }; return render();
    }
    if (["sticky", "text", "shape", "frame"].includes(t)) { drag = { mode: "create", kind: t, start: p, cur: p, sx: e.clientX, sy: e.clientY }; return; }
  }
  function onMove(e) {
    if (!board) return;
    const p = world(e);
    if (!present && (others.length || viewers.length)) sendCursor(p); else lastPt = p;
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (!drag) return;
    switch (drag.mode) {
      case "pinch": {
        if (pointers.size < 2) return;
        const [a, b] = [...pointers.values()], d = Math.hypot(a.x - b.x, a.y - b.y), c = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, r = stage().getBoundingClientRect(), v = drag.view;
        const z = clampZ(v.z * d / drag.d), wx = (drag.c.x - r.left - v.x) / v.z, wy = (drag.c.y - r.top - v.y) / v.z;
        view = { z, x: c.x - r.left - wx * z, y: c.y - r.top - wy * z }; return applyView();
      }
      case "pan": view.x = drag.view.x + e.clientX - drag.sx; view.y = drag.view.y + e.clientY - drag.sy; return applyView();
      case "move": return moveSel(e, p);
      case "marquee": {
        drag.cur = p; const r = rectOf(drag.start, p);
        sel = new Set(drag.keep); items.forEach(it => { if (!it.locked && overlap(box(it), r)) groupOf(it).forEach(id => sel.add(id)); });
        return render();
      }
      case "resize": return resizeTo(p, e.shiftKey);
      case "rotate": {
        let a = Math.atan2(p.y - drag.c.y, p.x - drag.c.x) * 180 / Math.PI + 90;
        if (e.shiftKey) a = Math.round(a / 15) * 15; else for (const s of [0, 90, 180, 270, 360, -90]) if (Math.abs(a - s) < 4) a = s;
        a = ((a + 180) % 360 + 360) % 360 - 180;
        if (Math.abs(a) < 0.5) delete drag.it.rot; else drag.it.rot = r1(a);
        return render();
      }
      case "end": { const other = drag.which === "a" ? drag.it.b : drag.it.a, tgt = hitAt(e, drag.it); drag.it[drag.which] = tgt && tgt.id !== other?.id ? { id: tgt.id } : { x: p.x, y: p.y }; hover = tgt?.id || null; return render(); }
      case "erase": return eraseAt(e);
      case "draw": { const l = drag.pts[drag.pts.length - 1]; if (Math.hypot(p.x - l[0], p.y - l[1]) * view.z < 2) return; drag.pts.push([p.x, p.y]); return drawPreview(); }
      case "line": { const tgt = hitAt(e, anchor(drag.it.a)); drag.it.b = tgt ? { id: tgt.id } : { x: p.x, y: p.y }; hover = tgt?.id || null; return render(); }
      case "create": drag.cur = p; return drawOverlay();
    }
  }
  function onUp(e) {
    pointers.delete(e.pointerId);
    if (!drag) return;
    if (drag.mode === "pinch") { if (pointers.size < 2) drag = null; return; }
    if (pointers.size) return;
    const d = drag; drag = null; hover = null; guides = [];
    switch (d.mode) {
      case "move": if (d.moved) changed(); else if (!d.toggled && byId(d.hit) && sel.size > 1) sel = new Set(groupOf(byId(d.hit))); break;
      case "resize": case "end": case "rotate": changed(); break;
      case "erase": if (d.erased) changed(); else undo.pop(); break;
      case "draw": finishDraw(d); break;
      case "line": {
        const [a, b] = ends(d.it);
        if (Math.hypot(a.x - b.x, a.y - b.y) * view.z < 8 && !d.it.b.id) { items = items.filter(x => x !== d.it); undo.pop(); }
        else { sel = new Set([d.it.id]); setTool("select"); changed(); }
        break;
      }
      case "create": finishCreate(d, e); break;
    }
    $("#wb-preview")?.remove();
    render(); cursor();
  }
  function cancelDrag() { if (drag?.mode === "line") { items = items.filter(x => x !== drag.it); undo.pop(); } $("#wb-preview")?.remove(); drag = null; hover = null; guides = []; render(); }
  function moveSel(e, p) {
    if (!drag.moved) {
      if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 3) return;
      let list = selected().filter(x => !x.locked);
      if (!list.length) { drag = null; return; }
      snap();
      if (drag.alt) { const copies = clone(list); copies.forEach(c => add(c, { select: false })); sel = new Set(copies.map(c => c.id)); list = copies; }
      const ids = new Set(list.map(x => x.id));
      list.filter(x => x.type === "frame").forEach(f => { const fb = box(f); items.forEach(x => { if (!ids.has(x.id) && x.type !== "frame" && !x.locked && inside(box(x), fb)) ids.add(x.id); }); });
      drag.orig = [...ids].map(byId).filter(Boolean).map(x => ({ it: x, x: num(x.x), y: num(x.y), a: x.a && { ...x.a }, b: x.b && { ...x.b } }));
      drag.bb = union(drag.orig.map(o => box(o.it))); drag.ids = ids; drag.moved = true;
    }
    let dx = p.x - drag.start.x, dy = p.y - drag.start.y;
    if (!e.ctrlKey && !e.metaKey) [dx, dy] = smartSnap(drag.bb, dx, dy, drag.ids); else guides = [];
    for (const o of drag.orig) {
      const it = o.it;
      if (it.type === "line") { if (!it.a?.id && o.a) it.a = { x: num(o.a.x) + dx, y: num(o.a.y) + dy }; if (!it.b?.id && o.b) it.b = { x: num(o.b.x) + dx, y: num(o.b.y) + dy }; }
      else { it.x = o.x + dx; it.y = o.y + dy; }
    }
    render();
  }
  function smartSnap(bb, dx, dy, moving) {
    const th = 6 / view.z, xs = [], ys = [], v = viewRect();
    for (const it of items) {
      if (moving.has(it.id) || ["line", "draw", "comment"].includes(it.type)) continue;
      const b = box(it); if (!overlap(b, v)) continue;
      xs.push(b.x, b.x + b.w / 2, b.x + b.w); ys.push(b.y, b.y + b.h / 2, b.y + b.h);
    }
    const nb = { x: bb.x + dx, y: bb.y + dy };
    const best = (cands, own) => { let r = null; for (const o of own) for (const c of cands) { const d = c - o; if (Math.abs(d) <= th && (!r || Math.abs(d) < Math.abs(r.d))) r = { d, at: c }; } return r; };
    const bx = best(xs, [nb.x, nb.x + bb.w / 2, nb.x + bb.w]), by = best(ys, [nb.y, nb.y + bb.h / 2, nb.y + bb.h]);
    guides = [];
    if (bx) { dx += bx.d; guides.push({ x: bx.at }); }
    if (by) { dy += by.d; guides.push({ y: by.at }); }
    return [dx, dy];
  }
  function resizeTo(p, shift) {
    const { dir, bb, start } = drag;
    if (drag.single) {  // in the item's own frame, so rotated items resize along their sides; the opposite side stays put
      const o = drag.orig[0], it = o.it, b = o.b, rot = num(it.rot) * Math.PI / 180, cos = Math.cos(rot), sin = Math.sin(rot);
      const dx0 = p.x - start.x, dy0 = p.y - start.y, lx = dx0 * cos + dy0 * sin, ly = -dx0 * sin + dy0 * cos;
      let w = b.w, h = b.h;
      if (dir.includes("e")) w = b.w + lx; if (dir.includes("w")) w = b.w - lx; if (dir.includes("s")) h = b.h + ly; if (dir.includes("n")) h = b.h - ly;
      w = Math.max(16, w); h = Math.max(16, h);
      if ((it.type === "image") !== shift && dir.length === 2) { const s = Math.max(w / b.w, h / b.h); w = b.w * s; h = b.h * s; }  // images keep their ratio unless Shift
      if (it.type === "text") h = b.h;
      const ax = dir.includes("w") ? 1 : dir.includes("e") ? -1 : 0, ay = dir.includes("n") ? 1 : dir.includes("s") ? -1 : 0, R = (vx, vy) => ({ x: vx * cos - vy * sin, y: vx * sin + vy * cos });
      const A0 = R(ax * b.w / 2, ay * b.h / 2), A1 = R(ax * w / 2, ay * h / 2), c = { x: b.x + b.w / 2 + A0.x - A1.x, y: b.y + b.h / 2 + A0.y - A1.y };
      it.x = c.x - w / 2; it.y = c.y - h / 2; it.w = w; if (it.type !== "text") it.h = h;
      if (o.pts) it.pts = o.pts.map(([px, py]) => [r1(px * w / b.w), r1(py * h / b.h)]);
      return render();
    }
    const dx = p.x - start.x, dy = p.y - start.y;
    let x = bb.x, y = bb.y, w = bb.w, h = bb.h;
    if (dir.includes("e")) w = bb.w + dx; if (dir.includes("w")) w = bb.w - dx;
    if (dir.includes("s")) h = bb.h + dy; if (dir.includes("n")) h = bb.h - dy;
    w = Math.max(16, w); h = Math.max(16, h);
    if (!shift && dir.length === 2) { const s = Math.max(w / bb.w, h / bb.h); w = bb.w * s; h = bb.h * s; }  // a group keeps its proportions unless Shift
    if (dir.includes("w")) x = bb.x + bb.w - w; if (dir.includes("n")) y = bb.y + bb.h - h;
    const sx = w / bb.w, sy = h / bb.h;
    for (const o of drag.orig) {
      const it = o.it, b = o.b;
      it.x = x + (b.x - bb.x) * sx; it.y = y + (b.y - bb.y) * sy; it.w = Math.max(8, b.w * sx);
      if (it.type !== "text") it.h = Math.max(8, b.h * sy);
      if (o.pts) it.pts = o.pts.map(([px, py]) => [r1(px * sx), r1(py * sy)]);
    }
    render();
  }
  function eraseAt(e) {
    for (const el of document.elementsFromPoint(e.clientX, e.clientY)) {
      const id = el.closest?.("#wb-world [data-id]")?.dataset.id, x = id && byId(id);
      if (x && x.type !== "frame" && !x.locked) { remove([x.id]); drag.erased++; return render(); }
    }
  }
  function drawPreview() {
    let el = $("#wb-preview");
    if (!el) { el = document.createElement("div"); el.id = "wb-preview"; el.className = "wb-it wb-draw wb-preview"; $("#wb-world").appendChild(el); }
    const o = drag.o, d = smooth(drag.pts.map(q => [r1(q[0]), r1(q[1])])), bb = union(drag.pts.map(q => ({ x: q[0], y: q[1], w: 0, h: 0 }))), p = o.sw + 4;
    Object.assign(el.style, { left: bb.x - p + "px", top: bb.y - p + "px", width: bb.w + 2 * p + "px", height: bb.h + 2 * p + "px", zIndex: 99999 });
    el.innerHTML = `<svg class="wb-svg" viewBox="${bb.x - p} ${bb.y - p} ${bb.w + 2 * p} ${bb.h + 2 * p}"><path d="${d}" style="fill:none;stroke:${paint(o.color)};stroke-width:${o.sw};stroke-linecap:round;stroke-linejoin:round;opacity:${drag.hl ? 0.45 : 1}"/></svg>`;
  }
  function finishDraw(d) {
    const pts = d.pts.length === 1 ? [d.pts[0], [d.pts[0][0] + 0.5, d.pts[0][1] + 0.5]] : d.pts;
    const bb = union(pts.map(q => ({ x: q[0], y: q[1], w: 0, h: 0 })));
    snap();
    add({ id: uid(), type: "draw", x: bb.x, y: bb.y, w: Math.max(1, bb.w), h: Math.max(1, bb.h), pts: pts.map(q => [r1(q[0] - bb.x), r1(q[1] - bb.y)]), color: d.o.color, sw: d.o.sw, ...(d.hl ? { hl: true } : {}) }, { select: false });
    changed();
  }
  function finishCreate(d, e) {
    const small = Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 6;
    const def = { sticky: [200, 200], text: [260, 32], shape: [180, 110], frame: [720, 460] }[d.kind];
    let b;
    if (small || d.kind === "sticky" || d.kind === "text") b = d.kind === "text" ? { x: d.start.x, y: d.start.y - 16, w: def[0], h: def[1] } : { x: d.start.x - def[0] / 2, y: d.start.y - def[1] / 2, w: def[0], h: def[1] };
    else { b = rectOf(d.start, d.cur); if (b.w < 16 || b.h < 16) b = { x: d.start.x, y: d.start.y, w: def[0], h: def[1] }; }
    snap(); const it = mk(d.kind, b); add(it);
    setTool("select"); render(); changed();
    if (d.kind === "sticky" || d.kind === "text") startEdit(it.id);
  }
  // what's under the pointer: the canvas captures the pointer on press, so clicks after it are aimed at the canvas itself
  const under = e => { const top = document.elementsFromPoint(e.clientX, e.clientY); return { chrome: !!top[0] && !!chrome(top[0]), el: top.find(x => x.closest?.("#wb-world [data-id]"))?.closest("#wb-world [data-id]"), cell: top.find(x => x.matches?.("[data-cell]")) }; };
  function onDbl(e) {
    if (!board || present) return;
    const u = under(e); if (u.chrome) return;
    if (u.el) return startEdit(u.el.dataset.id, u.cell ? u.cell.dataset.cell.split(",").map(Number) : null);
    if (tool !== "select") return;
    const p = world(e); snap(); const it = mk("sticky", { x: p.x - 100, y: p.y - 100, w: 200, h: 200 }); add(it); render(); changed(); startEdit(it.id);
  }
  function onWheel(e) {
    if (!board || e.target.closest(".wb-cpop, .wb-left, .wb-thread, .wb-panel, .wb-ai")) return;
    e.preventDefault();
    if (present) return;
    if (following) { following = null; drawFollow(); }
    const r = stage().getBoundingClientRect(), k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    if (e.ctrlKey || e.metaKey) zoomAt(view.z * Math.exp(-Math.max(-60, Math.min(60, e.deltaY * k)) * 0.0075), e.clientX - r.left, e.clientY - r.top);
    else { view.x -= (e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX) * k; view.y -= (e.shiftKey && !e.deltaX ? 0 : e.deltaY) * k; applyView(); }
  }
  function cursor() { const st = stage(); if (!st) return; st.dataset.tool = spaceDown ? "hand" : tool; st.classList.toggle("panning", drag?.mode === "pan"); }
  function setTool(t) {
    if (t === "image") { $("#wb-file")?.click(); t = "select"; }
    tool = t; if (t !== "select" && t !== "hand") { sel.clear(); ctxPop = null; }
    renderLeft(); cursor(); render();
  }

  // ---------- keyboard, clipboard ----------
  function onKey(e) {
    if (S.view !== "whiteboard" || !board || $("dialog[open]")) return;
    const t = e.target;
    if (t.closest?.("[contenteditable]") || /INPUT|TEXTAREA|SELECT/.test(t.tagName)) return;
    const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
    if (present) {
      if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); return slide(1); }
      if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); return slide(-1); }
      if (e.key === "Escape") { e.preventDefault(); return stopPresent(); }
      return;
    }
    if (e.key === " ") { e.preventDefault(); if (!spaceDown) { spaceDown = true; cursor(); } return; }
    if (mod && k === "z") { e.preventDefault(); return e.shiftKey ? doRedo() : doUndo(); }
    if (mod && k === "y") { e.preventDefault(); return doRedo(); }
    if (mod && k === "a") { e.preventDefault(); sel = new Set(items.filter(x => !x.locked).map(x => x.id)); return render(); }
    if (mod && k === "d") { e.preventDefault(); return duplicate(); }
    if (mod && k === "g") { e.preventDefault(); return e.shiftKey ? ungroup() : group(); }
    if (mod && k === "l") { e.preventDefault(); return toggleLock(); }
    if (mod && k === "f") { e.preventDefault(); return openFind(); }
    if (mod && (k === "=" || k === "+")) { e.preventDefault(); return zoomBy(1.25); }
    if (mod && k === "-") { e.preventDefault(); return zoomBy(0.8); }
    if (mod && k === "0") { e.preventDefault(); const st = stage(); return zoomAt(1, st.clientWidth / 2, st.clientHeight / 2); }
    if (e.key === "]" || e.key === "[") { e.preventDefault(); return order(e.key === "]" ? (mod ? "front" : "forward") : (mod ? "back" : "backward")); }
    if (e.shiftKey && e.code === "Digit1") { e.preventDefault(); return fitAll(); }
    if (e.shiftKey && e.code === "Digit2") { e.preventDefault(); return sel.size && fitTo(union(selected().map(box)), 2); }
    if (e.shiftKey && e.code === "Digit0") { e.preventDefault(); const st = stage(); return zoomAt(1, st.clientWidth / 2, st.clientHeight / 2); }
    if (mod) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); return del(); }
    if (e.key === "Escape") {
      if (drag) return cancelDrag();
      ctxPop = null; closePops(); if (find) closeFind();
      if (!$("#wb-ai").hidden) return toggleAi(false);
      if (tool !== "select") return setTool("select");
      if (sel.size === 1 && byId([...sel][0])?.type === "comment") return closeThread();
      sel.clear(); cellSel = null; return render();
    }
    if (e.key === "Enter" && sel.size === 1 && !t.closest?.("button")) { e.preventDefault(); return startEdit([...sel][0]); }
    const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (arrows && sel.size) { e.preventDefault(); const s = e.shiftKey ? 10 : 1; return nudge(arrows[0] * s, arrows[1] * s); }
    if (e.key === "?") return help();
    if (e.altKey) return;
    if (k === "i") { e.preventDefault(); return $("#wb-file").click(); }
    if (KEYS[k]) { if (k === "r") shapeKind = "rect"; if (k === "o") shapeKind = "ellipse"; return setTool(KEYS[k]); }
  }
  function onKeyUp(e) { if (e.key === " " && spaceDown) { spaceDown = false; cursor(); } }
  const typing = t => t.closest?.("[contenteditable]") || /INPUT|TEXTAREA|SELECT/.test(t?.tagName || "");
  function onCopy(e) { if (S.view === "whiteboard" && board && !typing(e.target) && !editing) copySel(e); }
  function onCut(e) { if (S.view === "whiteboard" && board && !typing(e.target) && !editing && copySel(e)) del(); }
  function onPaste(e) {
    if (S.view !== "whiteboard" || !board || editing || typing(e.target) || $("dialog[open]")) return;
    const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith("image/"));
    if (files.length) { e.preventDefault(); const c = viewCenter(); return files.forEach((f, i) => addImage(f, c, i)); }
    const text = e.clipboardData?.getData("text/plain") || "";
    if (text.startsWith(CLIP)) { e.preventDefault(); try { return pasteItems(JSON.parse(text.slice(CLIP.length))); } catch { return; } }
    if (!text.trim()) { if (clip) { e.preventDefault(); pasteItems(clip); } return; }
    e.preventDefault();
    const c = viewCenter(); snap();
    const url = safeUrl(text.trim());
    if (url && !/\s/.test(text.trim())) { add(mk("link", { x: c.x - 130, y: c.y - 55, w: 0, h: 0 }, { url, title: new URL(url).hostname.replace(/^www\./, "") })); render(); return changed(); }
    const lines = text.split(/\n/).map(x => x.trim()).filter(Boolean);
    if (lines.length > 1 && lines.length <= 30 && lines.every(l => l.length < 160)) {  // a list: one sticky per line, in a grid
      const cols = Math.ceil(Math.sqrt(lines.length)), made = lines.map((l, i) => mk("sticky", { x: c.x + (i % cols) * 224 - cols * 112, y: c.y + Math.floor(i / cols) * 224 - 100, w: 200, h: 200 }, { text: l.replace(/^[-*•]\s*/, "") }));
      made.forEach(m => add(m, { select: false })); sel = new Set(made.map(m => m.id));
    } else add(mk(text.length > 280 ? "text" : "sticky", text.length > 280 ? { x: c.x - 200, y: c.y - 40, w: 400, h: 80 } : { x: c.x - 100, y: c.y - 100, w: 200, h: 200 }, { text: text.slice(0, 5000) }));
    render(); changed();
  }

  // ---------- present: frames as slides ----------
  const framesInOrder = () => items.filter(x => x.type === "frame").sort((a, b) => Math.round(num(a.y) / 300) - Math.round(num(b.y) / 300) || num(a.x) - num(b.x));
  function startPresent(fromId) {
    const frames = framesInOrder();
    if (!frames.length) return toast("Add frames to present: each frame is a slide (press F to draw one)");
    finishEdit(); sel.clear(); ctxPop = null; toolPop = null; following = null; drawFollow();
    present = { frames, i: Math.max(0, frames.findIndex(f => f.id === fromId)), saved: { ...view } };
    $("#wbb").classList.add("presenting");
    $("#wbb").requestFullscreen?.().catch(() => {});
    slide(0);
  }
  function slide(d) {
    if (!present) return;
    present.i = Math.max(0, Math.min(present.frames.length - 1, present.i + d));
    const f = present.frames[present.i];
    render(); drawPresent();
    setTimeout(() => { if (present) fitTo(grow(box(f), 30), MAX_Z, 40); }, d === 0 ? 150 : 0);
  }
  function stopPresent() {
    if (!present) return;
    const v = present.saved; present = null;
    $("#wbb").classList.remove("presenting");
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    view = v; applyView(); drawPresent(); render(); renderLeft();
  }
  function drawPresent() {
    const p = $("#wb-present"); if (!p) return;
    p.hidden = !present;
    if (!present) return;
    p.innerHTML = `<button type="button" class="wb-cb" data-pv="-1" ${present.i ? "" : "disabled"} aria-label="Previous frame">${icon("left")}</button>
      <span><b>${esc(present.frames[present.i].title || "Frame")}</b> · ${present.i + 1} / ${present.frames.length}</span>
      <button type="button" class="wb-cb" data-pv="1" ${present.i < present.frames.length - 1 ? "" : "disabled"} aria-label="Next frame">${icon("right")}</button>
      <span class="wb-csep"></span><button type="button" class="btn sm" data-pv="exit">Exit</button>`;
  }

  // ---------- celebrate ----------
  function burst(emoji, by) {
    const fx = $("#wb-fx"); if (!fx || !CELEBRATE.includes(emoji)) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    for (let i = 0; i < (reduce ? 3 : 18); i++) {
      const s = document.createElement("span"); s.className = "wb-fly"; s.textContent = emoji;
      s.style.left = (8 + Math.random() * 84) + "%"; s.style.animationDelay = (Math.random() * 0.7) + "s"; s.style.fontSize = (22 + Math.random() * 26) + "px"; s.style.setProperty("--dx", (Math.random() * 160 - 80) + "px");
      fx.appendChild(s); setTimeout(() => s.remove(), 3600);
    }
    const t = document.createElement("div"); t.className = "wb-fx-who"; t.textContent = `${by || "You"} ${emoji}`; fx.appendChild(t); setTimeout(() => t.remove(), 2600);
  }
  function celebrate(emoji) { burst(emoji, null); if (board) api(`/api/boards/${board.id}/react`, { method: "POST", body: { emoji } }).catch(() => {}); }

  // ---------- AI assistant ----------
  function toggleAi(on = $("#wb-ai")?.hidden) {
    const a = $("#wb-ai"); if (!a) return;
    a.hidden = !on; $("[data-wb=ai]")?.classList.toggle("on", !!on);
    if (on) { drawAi(); a.querySelector("textarea")?.focus(); }
  }
  function drawAi(status = "") {
    const a = $("#wb-ai"); if (!a || a.hidden) return;
    const texty = aiItems(true), stickies = aiItems(true, true), prompt = a.querySelector("textarea")?.value ?? (pref("aiPrompt") || "");
    a.innerHTML = `<div class="wb-ai-head"><span class="wb-ai-ic">${icon("sparkle")}</span><b>AI assistant</b><span class="ac-spacer"></span><button type="button" class="wb-cb" data-ai="close" aria-label="Close">${icon("close")}</button></div>
      <textarea rows="3" maxlength="2000" data-ai-prompt placeholder="What's it about? e.g. “ways to get our first 100 miners” or “the order flow of a shop”">${esc(prompt)}</textarea>
      <div class="wb-ai-acts"><button type="button" class="btn sm primary" data-ai="ideas" ${aiBusy ? "disabled" : ""}>${icon("sticky")}Sticky ideas</button><button type="button" class="btn sm" data-ai="diagram" ${aiBusy ? "disabled" : ""}>${icon("elbow")}Flowchart</button></div>
      <div class="wb-ai-sel"><span class="faint small">${texty.length ? `${texty.length} item${texty.length === 1 ? "" : "s"} with text ${sel.size ? "selected" : "on the board"}` : "Select stickies or text to summarise or group them"}</span>
        <div class="wb-ai-acts"><button type="button" class="btn sm" data-ai="summary" ${aiBusy || !texty.length ? "disabled" : ""}>${icon("doc")}Summarise</button><button type="button" class="btn sm" data-ai="cluster" ${aiBusy || !stickies.length ? "disabled" : ""}>${icon("group")}Group by theme</button></div></div>
      ${aiBusy ? Loading.line("Thinking…") : status ? `<p class="wb-ai-status">${esc(status)}</p>` : `<p class="faint small wb-ai-status">Uses your agents' model (Auto unless changed in the Agents tab).</p>`}`;
  }
  const textOf = it => it.type === "frame" ? it.title : it.type === "card" || it.type === "doc" ? [it.title, it.text].filter(Boolean).join(": ") : it.type === "link" ? it.title || it.url : it.type === "table" ? tbl(it).cells.map(r => r.filter(Boolean).join(" | ")).filter(Boolean).join("; ") : it.type === "chart" ? it.title : it.type === "comment" ? (it.thread || []).map(m => m.text).join(" / ") : it.text;
  function aiItems(withText, stickiesOnly = false) {
    const src = sel.size ? selected() : items;
    return src.filter(x => (!stickiesOnly || x.type === "sticky") && (!withText || String(textOf(x) || "").trim()) && !["line", "draw", "image", "frame"].includes(x.type)).map(x => ({ id: x.id, text: String(textOf(x) || "").slice(0, 300) }));
  }
  async function runAi(action) {
    if (aiBusy || !board) return;
    const prompt = ($("[data-ai-prompt]")?.value || "").trim(); pref("aiPrompt", prompt);
    const its = action === "cluster" ? aiItems(true, true) : aiItems(true);
    if ((action === "ideas" || action === "diagram") && !prompt && !(sel.size && its.length)) return drawAi("Write what it's about first.");
    aiBusy = true; drawAi();
    const model = Chat.chosen();  // the model menu every chat shares
    let status = "";
    try {
      const r = await api(`/api/boards/${board.id}/ai`, { method: "POST", body: { action, prompt, items: action === "ideas" || action === "diagram" ? (sel.size ? its : []) : its, model } });
      status = applyAi(action, r.data);
    } catch (e) { status = e.message; }
    aiBusy = false; drawAi(status);
  }
  function applyAi(action, d) {
    const c = viewCenter(), sb = sel.size ? union(selected().map(box)) : null;
    if (action === "ideas") {
      const notes = (d.notes || []).map(n => String(n?.text || "").trim()).filter(Boolean).slice(0, 16); if (!notes.length) return "No ideas came back. Try rephrasing.";
      const cols = Math.min(4, Math.ceil(Math.sqrt(notes.length))), spot = sb ? { x: sb.x + sb.w + 80, y: sb.y } : freeSpot(cols * 224, Math.ceil(notes.length / cols) * 224), x0 = spot.x, y0 = spot.y, colors = ["yellow", "lime", "blue", "pink", "orange", "violet"];
      snap(); const made = notes.map((t, i) => mk("sticky", { x: x0 + (i % cols) * 224, y: y0 + Math.floor(i / cols) * 224, w: 200, h: 200 }, { text: t, color: colors[i % colors.length] }));
      made.forEach(m => add(m, { select: false })); sel = new Set(made.map(m => m.id)); render(); changed(); fitTo(union(made.map(box)), view.z);
      return `Added ${made.length} sticky notes.`;
    }
    if (action === "summary") {
      const text = [String(d.summary || "").trim(), ...(d.points || []).map(p => `- ${String(p).trim()}`)].filter(Boolean).join("\n\n");
      if (!text) return "No summary came back. Try again.";
      const spot = sb ? { x: sb.x + sb.w + 80, y: sb.y } : freeSpot(320, 380);
      snap(); const it = mk("doc", { x: spot.x, y: spot.y, w: 0, h: 0 }, { title: String(d.title || "Summary").slice(0, 200), text: text.slice(0, 8000) });
      add(it); render(); changed(); fitTo(union([box(it), ...(sb ? [sb] : [])]), view.z);
      return "Added a summary document.";
    }
    if (action === "cluster") {
      const ids = new Set(aiItems(true, true).map(x => x.id)), groups = (d.groups || []).map(g => ({ theme: String(g?.theme || "Theme").slice(0, 60), ids: [...new Set((g?.ids || []).map(String))].filter(id => ids.has(id)) })).filter(g => g.ids.length);
      const used = new Set(), clean2 = groups.map(g => ({ ...g, ids: g.ids.filter(id => !used.has(id) && used.add(id)) })).filter(g => g.ids.length), rest = [...ids].filter(id => !used.has(id));
      if (rest.length) clean2.push({ theme: "Other", ids: rest });
      if (!clean2.length) return "No groups came back. Try again.";
      snap(); const x0 = sb ? sb.x : c.x - clean2.length * 280, y0 = (sb ? sb.y + sb.h : c.y) + 80, made = [];
      let x = x0;
      clean2.forEach((g, gi) => {
        const n = g.ids.length, cols = Math.min(3, n), w = cols * 224 + 24, h = Math.ceil(n / cols) * 224 + 24;
        const f = mk("frame", { x, y: y0, w, h }, { title: g.theme, fill: FRAME[(gi + 2) % FRAME.length] }); items.unshift(f); made.push(f);
        g.ids.forEach((id, k) => { const it = byId(id); if (!it) return; it.x = x + 24 + (k % cols) * 224; it.y = y0 + 24 + Math.floor(k / cols) * 224; it.w = 200; it.h = 200; delete it.rot; });
        x += w + 60;
      });
      sel = new Set(made.map(f => f.id)); render(); changed(); fitTo(union(made.map(box)), view.z);
      return `Grouped into ${clean2.length} theme${clean2.length === 1 ? "" : "s"}.`;
    }
    if (action === "diagram") {
      const nodes = (d.nodes || []).filter(n => n && String(n.text || "").trim()).slice(0, 20), map = new Map();
      if (!nodes.length) return "No diagram came back. Try describing the steps.";
      const edges = (d.edges || []).filter(e => e && nodes.some(n => n.id === e.from) && nodes.some(n => n.id === e.to));
      const level = new Map(), incoming = new Set(edges.map(e => e.to)), queue = nodes.filter(n => n.kind === "start" || !incoming.has(n.id)).map(n => n.id);
      if (!queue.length) queue.push(nodes[0].id);
      queue.forEach(id => level.set(id, 0));
      for (let i = 0; i < queue.length; i++) for (const e of edges.filter(x => x.from === queue[i])) if (!level.has(e.to)) { level.set(e.to, level.get(queue[i]) + 1); queue.push(e.to); }
      nodes.forEach(n => { if (!level.has(n.id)) level.set(n.id, Math.max(0, ...level.values()) + 1); });
      const rows = new Map(); nodes.forEach(n => { if ([...rows.values()].some(r => r.some(m => m.id === n.id))) return; const l = level.get(n.id); rows.set(l, [...(rows.get(l) || []), n]); });
      snap(); const made = [], top = c.y - rows.size * 85;
      for (const [l, ns] of [...rows.entries()].sort((a, b) => a[0] - b[0])) ns.forEach((n, k) => {
        const kind = n.kind, w = 200, h = kind === "decision" ? 120 : 80, x = c.x - (ns.length * 240) / 2 + k * 240 + 20, y = top + l * 170;
        const it = { id: uid(), type: "shape", x, y, w, h, shape: kind === "decision" ? "diamond" : kind === "start" || kind === "end" ? "round" : "rect", fill: kind === "decision" ? "#fff9b1" : kind === "start" || kind === "end" ? "#d0bfff" : "#a5d8ff", stroke: "ink", sw: 2, text: String(n.text).slice(0, 200), fs: 15 };
        map.set(n.id, it); items.push(it); made.push(it);
      });
      edges.forEach(e => { const A = map.get(e.from), B = map.get(e.to); if (A && B && A !== B) { const l = { id: uid(), type: "line", a: { id: A.id }, b: { id: B.id }, color: "ink", sw: 2, start: "none", end: "arrow", route: "elbow", ...(String(e.label || "").trim() ? { text: String(e.label).slice(0, 60) } : {}) }; items.push(l); made.push(l); } });
      sel = new Set(made.map(x => x.id)); render(); changed(); fitTo(union(made.map(box)), 1);
      return `Drew a flowchart with ${map.size} steps.`;
    }
    return "";
  }

  // ---------- layout: the full-screen board and its floating toolbars ----------
  function layout() {
    $("#wb").innerHTML = `<div class="wbx" id="wbx"></div>
      <div class="wbb" id="wbb" hidden>
        <div class="wb-stage" id="wb-stage" tabindex="0" aria-label="Whiteboard canvas">
          <div class="wb-world" id="wb-world"></div>
          <div class="wb-osel-layer" id="wb-osel"></div>
          <div class="wb-overlay" id="wb-overlay"></div>
          <div class="wb-cursors" id="wb-cursors"></div>
          <div id="wb-thread"></div>
          <div class="wb-tl" id="wb-tl"></div>
          <div class="wb-tr" id="wb-tr"></div>
          <div class="wb-left" id="wb-left"></div>
          <div class="wb-bl" id="wb-bl"></div>
          <div class="wb-br" id="wb-br"></div>
          <canvas class="wb-mini" id="wb-mini" title="Minimap: click to move there"></canvas>
          <div class="wb-panel" id="wb-panel" hidden></div>
          <div class="wb-ai" id="wb-ai" hidden></div>
          <div class="wb-present" id="wb-present" hidden></div>
          <div class="wb-follow" id="wb-follow" hidden></div>
          <div class="wb-fx" id="wb-fx" aria-hidden="true"></div>
          <div id="wb-hint"></div>
          <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" id="wb-file" class="sr" multiple tabindex="-1">
        </div>
      </div>`;
    const st = stage();
    st.addEventListener("pointerdown", onDown);
    st.addEventListener("pointermove", onMove);
    st.addEventListener("pointerup", onUp);
    st.addEventListener("pointercancel", onUp);
    st.addEventListener("pointerleave", () => { if (others.length) sendCursor(null); else lastPt = null; });
    st.addEventListener("dblclick", onDbl);
    st.addEventListener("wheel", onWheel, { passive: false });
    st.addEventListener("click", onClick);
    st.addEventListener("change", onChange);
    st.addEventListener("input", e => { if (e.target.matches("[data-thread-input]")) threadDraft = e.target.value; if (e.target.matches("[data-wb-find]")) runFind(e.target.value); });
    st.addEventListener("keydown", e => {
      if (e.target.matches("[data-thread-input]") && e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); reply(); }
      if (e.target.matches("[data-thread-input]") && e.key === "Escape") { e.preventDefault(); closeThread(); stage().focus(); }
      if (e.target.matches("[data-ai-prompt]") && e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runAi("ideas"); }
      if (e.target.matches("[data-wb-name]") && (e.key === "Enter" || e.key === "Escape")) { if (e.key === "Escape") e.target.value = board?.name || ""; e.target.blur(); stage().focus(); }
      if (e.target.matches("[data-wb-find]")) { if (e.key === "Enter") { e.preventDefault(); findNext(e.shiftKey ? -1 : 1); } if (e.key === "Escape") { closeFind(); stage().focus(); } }
    });
    st.addEventListener("focusout", e => { if (e.target.matches("[data-wb-name]")) rename(e.target.value); });
    st.addEventListener("contextmenu", onContext);
    st.addEventListener("dragover", e => { if (board && [...(e.dataTransfer?.items || [])].some(i => i.kind === "file")) { e.preventDefault(); st.classList.add("drop"); } });
    st.addEventListener("dragleave", () => st.classList.remove("drop"));
    st.addEventListener("drop", e => { st.classList.remove("drop"); if (!board) return; const fs = [...(e.dataTransfer?.files || [])]; if (!fs.length) return; e.preventDefault(); const p = world(e); fs.forEach((f, i) => f.type === "application/json" || f.name.endsWith(".json") ? importJson(f) : addImage(f, p, i)); });
    $("#wb-file").addEventListener("change", e => { const c = viewCenter(); [...e.target.files].forEach((f, i) => addImage(f, c, i)); e.target.value = ""; });
    const mc = $("#wb-mini");
    mc.addEventListener("pointerdown", e => { e.stopPropagation(); mc.setPointerCapture(e.pointerId); miniGo(e); });
    mc.addEventListener("pointermove", e => { if (e.buttons) miniGo(e); });
    new ResizeObserver(() => { if (board) applyView(); }).observe(st);
    $("#wbx").addEventListener("click", onDashClick);
    $("#wbx").addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-board]")) { e.preventDefault(); openBoard(+e.target.dataset.board); } });
    $("#wbx").addEventListener("input", e => { if (e.target.matches("[data-wbd-q]")) { dashQ = e.target.value; renderDash(true); } });
    document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && present) stopPresent(); });
  }
  const tb = (k, ic, title, extra = "") => `<button type="button" class="wb-cb" data-wb="${k}" title="${esc(title)}" aria-label="${esc(title)}" ${extra}>${icon(ic)}</button>`;
  function renderTL() {
    const t = $("#wb-tl"); if (!t || !board) return;
    t.innerHTML = `<div class="wb-pill"><button type="button" class="wb-home mark" data-wb="home" title="All boards" aria-label="All boards"><img class="logo-light" src="/static/brand/logo-light-96.png" alt=""><img class="logo-dark" src="/static/brand/logo-dark-96.png" alt=""></button>
      <span class="wb-csep"></span><input class="wb-name" data-wb-name value="${esc(board.name)}" maxlength="80" aria-label="Board name" spellcheck="false" size="${Math.max(6, Math.min(28, board.name.length + 1))}">
      ${tb("settings", "gear", "Board settings")}${tb("export", "upload", "Export")}
      ${find ? `<span class="wb-find"><input data-wb-find placeholder="Find on board" value="${esc(find.q)}" aria-label="Find on board"><span class="faint small" id="wb-find-n"></span>${tb("find-close", "close", "Close find")}</span>` : tb("find", "search", "Find (Ctrl+F)")}
      <span class="wb-status ${state}" id="wb-status">${statusText()}</span></div>`;
  }
  const statusText = () => ({ saved: icon("check"), saving: `<span class="spinner"></span>`, unsaved: `<span class="wb-dotx"></span>`, error: icon("alert") }[state]);
  function syncTop(err) {
    const s = $("#wb-status"); if (s) { s.className = `wb-status ${state}`; s.innerHTML = statusText(); s.title = err || { saved: "All changes saved", saving: "Saving…", unsaved: "Unsaved changes", error: "Couldn't save, retrying" }[state]; }
    const u = $("[data-wb=undo]"), r = $("[data-wb=redo]"); if (u) u.disabled = !undo.length; if (r) r.disabled = !redo.length;
  }
  function renderTR() {
    const t = $("#wb-tr"); if (!t || !board) return;
    t.innerHTML = `<div class="wb-pill">${tb("apps", "apps", "Templates")}<button type="button" class="wb-cb ${showCursors ? "" : "off"}" data-wb="cursors" title="${showCursors ? "Hide" : "Show"} collaborators' cursors" aria-label="Collaborators' cursors" aria-pressed="${showCursors}">${icon("cursors")}</button>${tb("celebrate", "party", "Celebrate with everyone here")}</div>
      <div class="wb-pill wb-people" id="wb-people"></div>
      <div class="wb-pill wb-presentbox"><button type="button" class="wb-present-btn" data-wb="present">${icon("present")}Present</button><button type="button" class="wb-cb" data-wb="present-menu" aria-label="Present from a frame">${icon("chev")}</button></div>
      <button type="button" class="wb-share" data-wb="share">${icon("users")}Share</button>`;
    people();
  }
  function people() {
    const p = $("#wb-people"); if (!p) return;
    const colorOf = n => others.find(o => o.name === n)?.color;
    p.innerHTML = viewers.slice(0, 3).map(v => `<button type="button" class="wb-pbtn" data-person="${esc(v)}" title="${esc(v)} is here: go to them or follow">${person(v, colorOf(v))}</button>`).join("")
      + (viewers.length > 3 ? `<span class="wb-person more" title="${esc(viewers.slice(3).join(", "))}">${viewers.length - 3}</span>` : "")
      + `<span class="wb-me" title="You">${person(me(), "", "me")}</span>`;
  }
  function renderLeft() {
    const l = $("#wb-left"); if (!l || !board) return;
    const active = PARENT[tool] || tool, at = TOOLS.findIndex(t => t[0] === (toolPop || active));
    l.innerHTML = `<div class="wb-pill col">${TOOLS.map(([k, ic, label, key]) => `<button type="button" class="wb-tool ${active === k ? "on" : ""}" data-tool="${k}" title="${label}${key ? ` (${key})` : ""}" aria-label="${label}" aria-pressed="${active === k}">${k === "sticky" ? `<span class="wb-tool-sticky" style="--c:${STICKY[stickyColor] || STICKY.yellow}"></span>` : icon(k === "shape" ? SHAPES.find(s => s[0] === shapeKind)[1] : k === "pen" ? (tool === "marker" ? "marker" : tool === "eraser" ? "eraser" : "pen") : k === "select" && tool === "hand" ? "hand" : k === "more" && tool === "comment" ? "chat" : ic)}</button>`).join("")}</div>
      <div class="wb-pill col">${tb("undo", "undo", "Undo (Ctrl+Z)", undo.length ? "" : "disabled")}${tb("redo", "redo", "Redo (Ctrl+Shift+Z)", redo.length ? "" : "disabled")}</div>
      ${toolPop ? `<div class="wb-topt" style="top:${8 + at * 42}px">${toolOptions(toolPop)}</div>` : ""}`;
  }
  function toolOptions(k) {
    const opt = (o, v, inner, title, on) => `<button type="button" class="wb-cb ${on ? "on" : ""}" data-opt="${o}" data-v="${esc(String(v))}" title="${esc(title)}" aria-label="${esc(title)}">${inner}</button>`;
    if (k === "select") return opt("tool", "select", icon("pointer"), "Select (V)", tool === "select") + opt("tool", "hand", icon("hand"), "Hand (H or hold Space)", tool === "hand");
    if (k === "sticky") return `<div class="wb-topt-grid">${Object.keys(STICKY).map(c => `<button type="button" class="wb-stk ${c === stickyColor ? "on" : ""}" data-opt="sticky" data-v="${c}" style="--c:${STICKY[c]}" title="${c}" aria-label="${c} sticky"></button>`).join("")}</div>`;
    if (k === "shape") return SHAPES.map(([s, ic, l]) => opt("shape", s, icon(ic), l, s === shapeKind)).join("");
    if (k === "arrow") { const r = pref("route") || "elbow"; return opt("tool", "arrow", icon("arrow"), "Connector (L)", tool === "arrow") + opt("tool", "line", icon("line"), "Plain line", tool === "line") + `<span class="wb-csep"></span>` + [["straight", "line"], ["elbow", "elbow"], ["curve", "curve"]].map(([s, ic]) => opt("route", s, icon(ic), `${s} connectors`, r === s)).join(""); }
    if (k === "pen") {
      const o = tool === "marker" ? marker : pen, cols = tool === "marker" ? HL : INK, ws = tool === "marker" ? [12, 18, 28] : [2, 3, 6];
      return opt("tool", "pen", icon("pen"), "Pen (P)", tool === "pen") + opt("tool", "marker", icon("marker"), "Highlighter (M)", tool === "marker") + opt("tool", "eraser", icon("eraser"), "Eraser (E)", tool === "eraser")
        + (tool === "eraser" ? "" : `<span class="wb-csep"></span>${cols.map(c => `<button type="button" class="wb-sw ${c === o.color ? "on" : ""}" data-opt="color" data-v="${c}" style="--c:${paint(c)}" title="${c === "ink" ? "Default" : c}" aria-label="Colour ${c}"></button>`).join("")}<span class="wb-csep"></span>
        ${ws.map((w, i) => opt("sw", w, `<span class="wb-wline" style="height:${Math.min(8, Math.round(w / (tool === "marker" ? 4 : 1)) + 1)}px"></span>`, ["Thin", "Medium", "Thick"][i], o.sw === w)).join("")}`);
    }
    if (k === "more") return `<div class="wb-more-grid">${MORE.map(([m, ic, l, key]) => `<button type="button" class="wb-moreb" data-more="${m}" title="${l}${key ? ` (${key})` : ""}">${icon(ic)}<span>${l}</span></button>`).join("")}</div>`;
    return "";
  }
  function renderBL() {
    const b = $("#wb-bl"); if (!b || !board) return;
    b.innerHTML = `<div class="wb-pill"><button type="button" class="wb-cb ${panelOpen ? "on" : ""}" data-wb="panel" title="Frames" aria-label="Frames" aria-pressed="${panelOpen}">${icon("sidebar")}</button></div>`;
    const p = $("#wb-panel"); p.hidden = !panelOpen;
    if (!panelOpen) return;
    const fr = framesInOrder();
    p.innerHTML = `<div class="wb-panel-head"><b>Frames</b><span class="ac-spacer"></span>${tb("panel", "close", "Close")}</div>
      ${fr.length ? `<ol class="wb-frames">${fr.map((f, i) => `<li><button type="button" class="wb-framebtn" data-frame="${esc(f.id)}"><span class="wb-frame-n">${i + 1}</span><span>${esc(f.title || "Frame")}</span></button><button type="button" class="wb-cb" data-present-from="${esc(f.id)}" title="Present from here" aria-label="Present from ${esc(f.title || "this frame")}">${icon("present")}</button></li>`).join("")}</ol>`
        : `<p class="faint small">No frames yet. Frames are sections of the board and the slides of Present mode: press F and drag.</p>`}
      <button type="button" class="btn sm wb-allboards" data-wb="home">${icon("left")}All boards</button>`;
  }
  function renderBR() {
    const b = $("#wb-br"); if (!b || !board) return;
    b.innerHTML = `<div class="wb-pill"><button type="button" class="wb-cb" data-z="out" title="Zoom out (Ctrl −)" aria-label="Zoom out">${icon("minus")}</button>
        <button type="button" class="wb-zl" id="wb-zl" data-z="menu" title="Zoom options">${Math.round(view.z * 100)}%</button>
        <button type="button" class="wb-cb" data-z="in" title="Zoom in (Ctrl +)" aria-label="Zoom in">${icon("plus")}</button></div>
      <div class="wb-pill"><button type="button" class="wb-cb wb-help" data-z="help" title="Help and keyboard shortcuts (?)" aria-label="Help">?</button></div>
      <button type="button" class="wb-aibtn" data-wb="ai" title="AI assistant" aria-label="AI assistant">${icon("sparkle")}</button>`;
  }
  function renderChrome() { renderTL(); renderTR(); renderLeft(); renderBL(); renderBR(); drawPresent(); drawFollow(); }
  // an empty board: a hint near the bottom, never in the way of placing the first item
  function hint() {
    const h = $("#wb-hint"); if (!h) return;
    if (!board || items.length || tool !== "select" || present) { h.className = ""; h.innerHTML = ""; return; }
    if (h.className === "wb-hint") return;
    h.className = "wb-hint";
    h.innerHTML = `<div class="wb-hint-card"><b>This board is empty</b><span class="faint small">Double-click for a sticky note, pick a tool on the left, paste text or images, or start from a template.</span>
      <div class="row"><button type="button" class="btn sm primary" data-wb="add-sticky">${icon("sticky")}Add a sticky</button><button type="button" class="btn sm" data-wb="apps">${icon("apps")}Templates</button><button type="button" class="btn sm" data-wb="ai">${icon("sparkle")}Ask AI</button></div></div>`;
  }

  // ---------- clicks on the board's chrome ----------
  function onClick(e) {
    const t = e.target;
    const tl = t.closest(".wb-tool[data-tool]");  // (the canvas has data-tool too, for its cursor)
    if (tl) {
      const k = tl.dataset.tool;
      if (k === "more") { toolPop = toolPop === "more" ? null : "more"; return renderLeft(); }
      const has = ["select", "sticky", "shape", "arrow", "pen"].includes(k), was = PARENT[tool] || tool;
      if (was === k && has) { toolPop = toolPop === k ? null : k; return renderLeft(); }
      toolPop = has && k !== "select" ? k : null;
      return setTool(k);
    }
    const op = t.closest("[data-opt]");
    if (op) {
      const v = op.dataset.v, o = tool === "marker" ? marker : pen;
      if (op.dataset.opt === "tool") { if (["select", "hand"].includes(v)) toolPop = null; return setTool(v); }
      if (op.dataset.opt === "sticky") { stickyColor = v; pref("sticky", v); toolPop = null; if (tool !== "sticky") return setTool("sticky"); }
      if (op.dataset.opt === "shape") { shapeKind = v; toolPop = null; if (tool !== "shape") return setTool("shape"); }
      if (op.dataset.opt === "route") pref("route", v);
      if (op.dataset.opt === "color") o.color = v;
      if (op.dataset.opt === "sw") o.sw = +v;
      return renderLeft();
    }
    const mo = t.closest("[data-more]");
    if (mo) {
      const k = mo.dataset.more; toolPop = null;
      if (k === "comment") return setTool("comment");
      if (k === "image") { renderLeft(); return $("#wb-file").click(); }
      if (k === "mindmap") { renderLeft(); return insertTemplate("mindmap"); }
      if (k === "templates") { renderLeft(); return templatePicker(true); }
      return placeAtCenter(k);
    }
    const zb = t.closest("[data-z]"), z = zb?.dataset.z;
    if (z) {
      const st = stage();
      if (z === "in") return zoomBy(1.25);
      if (z === "out") return zoomBy(0.8);
      if (z === "help") return help();
      if (z === "menu") return menu(above(zb), [["Zoom to fit", "fit", fitAll, "Shift+1"], ["Zoom to 50%", "minus", () => zoomAt(0.5, st.clientWidth / 2, st.clientHeight / 2)], ["Zoom to 100%", "search", () => zoomAt(1, st.clientWidth / 2, st.clientHeight / 2), "Shift+0"], ["Zoom to 200%", "plus", () => zoomAt(2, st.clientWidth / 2, st.clientHeight / 2)], "-",
        [`${grid ? "Hide" : "Show"} grid`, "grid", () => { grid = !grid; pref("grid", grid); applyView(); }], [`${mini ? "Hide" : "Show"} minimap`, "map", () => { mini = !mini; pref("mini", mini); drawMini(); }]]);
      return;
    }
    const pv = t.closest("[data-pv]")?.dataset.pv; if (pv) return pv === "exit" ? stopPresent() : slide(+pv);
    const fr = t.closest("[data-frame]"); if (fr) { const f = byId(fr.dataset.frame); if (f) { sel = new Set([f.id]); fitTo(box(f), 2); render(); } return; }
    const pf = t.closest("[data-present-from]"); if (pf) return startPresent(pf.dataset.presentFrom);
    const pr = t.closest("[data-person]"); if (pr) { const n = pr.dataset.person; return menu(below(pr), [[`Go to ${n}`, "target", () => goTo(n)], [`Follow ${n}`, "eye", () => { following = n; goTo(n, true); drawFollow(); }]]); }
    const ai = t.closest("[data-ai]")?.dataset.ai; if (ai) return ai === "close" ? toggleAi(false) : runAi(ai);
    const w = t.closest("[data-wb]");
    if (w) return chromeAction(w.dataset.wb, w);
    const pp = t.closest("[data-pop]"); if (pp) { ctxPop = ctxPop === pp.dataset.pop ? null : pp.dataset.pop; return drawOverlay(); }
    const a = t.closest("[data-act]");
    if (a && a.tagName !== "SELECT") {
      const k = a.dataset.act, v = a.dataset.v;
      if (["color", "fill", "stroke", "sw", "shape", "route", "card-color", "chart-kind"].includes(k)) { if (!["sw", "route", "card-color", "chart-kind"].includes(k)) ctxPop = null; return setProp(k, v); }
      if (["bold", "align", "dash", "start", "end"].includes(k)) return setProp(k, v);
      if (["row-add", "col-add", "row-del", "col-del", "head"].includes(k)) return tableEdit(k);
      if (k === "cellfill") { ctxPop = null; return tableEdit("cellfill", v); }
      if (k === "react") { ctxPop = null; return toggleReact(selected()[0]?.id, v); }
      if (k === "reply") return reply();
      if (k === "close-thread") return closeThread();
      if (k === "resolve") { const it = selected()[0]; if (!it) return; snap(); if (it.resolved) delete it.resolved; else it.resolved = true; render(); return changed(); }
      ctxPop = null;
      if (k === "edit") return editDialog(selected()[0]);
      if (k === "present-frame") return startPresent(selected()[0]?.id);
      if (k === "align-items") return alignItems(v);
      if (k === "distribute") return distribute(v);
      if (k === "group") return group();
      if (k === "ungroup") return ungroup();
      if (k === "lock") return toggleLock();
      if (k === "delete") { threadDraft = ""; return del(); }
      if (k === "duplicate") return duplicate();
      if (k === "unrotate") return setProp("unrotate");
      if (k === "copy") { copySel(); toast("Copied: paste with Ctrl+V, here or on another board"); return drawOverlay(); }
      if (["front", "back", "forward", "backward"].includes(k)) return order(k);
      if (k === "comment-here") { const b = union(selected().map(box)); snap(); add(mk("comment", { x: b.x + b.w, y: b.y })); threadDraft = ""; return render(); }
      if (k === "zoomsel") { drawOverlay(); return fitTo(union(selected().map(box)), 2); }
      if (k === "png-sel") return exportImage("png", selected());
    }
  }
  function chromeAction(k, el) {
    if (k === "home") return goHome();
    if (k === "undo") return doUndo();
    if (k === "redo") return doRedo();
    if (k === "find") return openFind();
    if (k === "find-close") return closeFind();
    if (k === "settings") return menu(below(el), [["Rename", "edit", () => { const n = $("[data-wb-name]"); n?.focus(); n?.select(); }], ["Duplicate board", "copy", () => dupBoard(board)], ["Share", "users", shareDlg], "-",
      [`${grid ? "Hide" : "Show"} grid`, "grid", () => { grid = !grid; pref("grid", grid); applyView(); }], [`${mini ? "Hide" : "Show"} minimap`, "map", () => { mini = !mini; pref("mini", mini); drawMini(); }],
      [`${showCursors ? "Hide" : "Show"} collaborators' cursors`, "cursors", toggleCursors], ["Keyboard shortcuts", "keyboard", help, "?"], "-",
      ["All boards", "left", goHome], board.mine ? ["Delete board", "trash", () => deleteDlg(board), "", true] : ["Leave board", "logout", () => deleteDlg(board), "", true]]);
    if (k === "export") return menu(below(el), [["PNG image", "image", () => exportImage("png", items)], sel.size && ["PNG of the selection", "image", () => exportImage("png", selected())], ["SVG image", "file", () => exportImage("svg", items)],
      ["Copy as text outline", "note", copyOutline], "-", ["Board file (.json)", "download", exportJson], ["Import a board file…", "upload", () => pickFile(".json,application/json", importJson)]]);
    if (k === "apps") return templatePicker(true);
    if (k === "cursors") return toggleCursors();
    if (k === "celebrate") return emojiPop(below(el));
    if (k === "present") return startPresent();
    if (k === "present-menu") { const fr = framesInOrder(); return menu(below(el), fr.length ? fr.map(f => [`Present from “${f.title || "Frame"}”`, "present", () => startPresent(f.id)]) : [["Add frames to present (F)", "frame", () => setTool("frame")]]); }
    if (k === "share") return shareDlg();
    if (k === "panel") { panelOpen = !panelOpen; return renderBL(); }
    if (k === "ai") return toggleAi();
    if (k === "unfollow") { following = null; return drawFollow(); }
    if (k === "add-sticky") { const c = viewCenter(); snap(); const it = mk("sticky", { x: c.x - 100, y: c.y - 100, w: 200, h: 200 }); add(it); render(); changed(); return startEdit(it.id); }
  }
  function toggleCursors() { showCursors = !showCursors; pref("cursors", showCursors); renderTR(); drawCursors(); }
  function onChange(e) { if (e.target.matches("select[data-act=fs]")) { setProp("fs", e.target.value); stage().focus({ preventScroll: true }); } }
  function onContext(e) {
    if (!board || present) return;
    const u = under(e); if (u.chrome) return;
    e.preventDefault();
    const el = u.el;
    if (el && !sel.has(el.dataset.id)) { sel = new Set(groupOf(byId(el.dataset.id))); render(); }
    const has = sel.size > 0, p = world(e);
    const here = kind => () => { snap(); const it = mk(kind, kind === "sticky" ? { x: p.x - 100, y: p.y - 100, w: 200, h: 200 } : kind === "text" ? { x: p.x, y: p.y, w: 260, h: 32 } : { x: p.x, y: p.y }); add(it); render(); if (kind === "comment") { threadDraft = ""; return; } changed(); startEdit(it.id); };
    const comment = () => { const b = union(selected().map(box)); snap(); add(mk("comment", { x: b.x + b.w, y: b.y })); threadDraft = ""; render(); };
    menu({ x: e.clientX, y: e.clientY }, has ? [
      ["Duplicate", "copy", duplicate, "Ctrl+D"], ["Copy", "file", () => { copySel(); toast("Copied"); }, "Ctrl+C"], clip && ["Paste", "upload", () => pasteItems(clip), "Ctrl+V"], "-",
      ["Bring to front", "front", () => order("front"), "Ctrl+]"], ["Send to back", "back", () => order("back"), "Ctrl+["], "-",
      sel.size > 1 && ["Group", "group", group, "Ctrl+G"], selected().some(x => x.group) && ["Ungroup", "group", ungroup, "Ctrl+Shift+G"],
      [selected().every(x => x.locked) ? "Unlock" : "Lock", "lock", toggleLock, "Ctrl+L"], ["Comment on this", "chat", comment], ["Zoom to selection", "fit", () => fitTo(union(selected().map(box)), 2), "Shift+2"], "-",
      ["Delete", "trash", del, "Del", true]] : [
      ["Add a sticky here", "sticky", here("sticky"), "Double-click"], ["Add text here", "type", here("text"), "T"], ["Comment here", "chat", here("comment"), "C"],
      clip && ["Paste", "upload", () => pasteItems(clip), "Ctrl+V"], ["Select all", "pointer", () => { sel = new Set(items.filter(x => !x.locked).map(x => x.id)); render(); }, "Ctrl+A"], "-",
      ["Fit everything", "fit", fitAll, "Shift+1"], ["Insert a template", "apps", () => templatePicker(true), ""]]);
  }
  function menu(at, entries) {
    document.querySelector(".wb-menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover menu wb-menu"; pop.setAttribute("role", "menu");
    const acts = [];
    pop.innerHTML = entries.filter(Boolean).map(x => x === "-" ? `<div class="mi-sep"></div>` : (acts.push(x[2]), `<button type="button" class="mi ${x[4] ? "danger" : ""}" data-mi="${acts.length - 1}" role="menuitem">${icon(x[1])}<span>${esc(x[0])}</span>${x[3] ? `<kbd>${esc(x[3])}</kbd>` : ""}</button>`)).join("");
    document.body.appendChild(pop);
    place(pop, at);
    const close = () => { pop.remove(); document.removeEventListener("pointerdown", off, true); document.removeEventListener("keydown", esc2, true); };
    const off = ev => { if (!pop.contains(ev.target)) close(); }, esc2 = ev => { if (ev.key === "Escape") { ev.stopPropagation(); close(); } };
    setTimeout(() => { document.addEventListener("pointerdown", off, true); document.addEventListener("keydown", esc2, true); });
    pop.onclick = ev => { const b = ev.target.closest("[data-mi]"); if (!b) return; close(); acts[+b.dataset.mi](); };
    pop.querySelector(".mi")?.focus();
  }
  function emojiPop(at) {
    document.querySelector(".wb-menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover wb-menu wb-emojis";
    pop.innerHTML = `<b class="small">Celebrate with everyone here</b><div>${CELEBRATE.map(e => `<button type="button" class="wb-emoji" data-e="${e}" aria-label="${e}">${e}</button>`).join("")}</div>`;
    document.body.appendChild(pop); place(pop, at);
    const close = () => { pop.remove(); document.removeEventListener("pointerdown", off, true); };
    const off = ev => { if (!pop.contains(ev.target)) close(); };
    setTimeout(() => document.addEventListener("pointerdown", off, true));
    pop.onclick = ev => { const b = ev.target.closest("[data-e]"); if (b) { close(); celebrate(b.dataset.e); } };
  }
  function place(pop, at) {
    const x = Math.max(8, Math.min(at.x - (at.right ? pop.offsetWidth : 0), innerWidth - pop.offsetWidth - 8)), y = at.up ? at.y - pop.offsetHeight - 6 : at.y;
    pop.style.position = "fixed"; pop.style.left = x + "px"; pop.style.top = Math.max(8, Math.min(y, innerHeight - pop.offsetHeight - 8)) + "px";
  }
  const below = el => { const r = el.getBoundingClientRect(); return { x: r.right, y: r.bottom + 6, right: true }; };
  const above = el => { const r = el.getBoundingClientRect(); return { x: r.right, y: r.top, right: true, up: true }; };

  // ---------- the board list (no board open) ----------
  async function loadList() { try { list = await api("/api/boards"); } catch (e) { toast(e.message); } }
  function thumb(pv) {
    const boxes = (pv || []).filter(a => Array.isArray(a) && a.length >= 5);
    if (!boxes.length) return `<span class="wbd-blank">${icon("sticky")}</span>`;
    const bb = grow(union(boxes.map(a => ({ x: num(a[1]), y: num(a[2]), w: Math.max(1, num(a[3])), h: Math.max(1, num(a[4])) }))), 30);
    const order = [...boxes].sort((a, b) => (a[0] === "frame" ? 0 : 1) - (b[0] === "frame" ? 0 : 1));
    return `<svg viewBox="${r1(bb.x)} ${r1(bb.y)} ${r1(bb.w)} ${r1(bb.h)}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${order.map(([t, x, y, w, h, c]) => {
      const fill = t === "sticky" ? stickyBg(c) : t === "frame" || t === "shape" ? (HEX.test(c || "") ? c : "#ffffff") : t === "draw" ? "none" : "#ffffff";
      const stroke = t === "sticky" ? "none" : t === "card" && HEX.test(c || "") ? c : "#c9c9c4";
      return `<rect x="${num(x)}" y="${num(y)}" width="${Math.max(1, num(w))}" height="${Math.max(1, num(h))}" rx="${t === "frame" ? 6 : 3}" fill="${fill}" stroke="${stroke}" vector-effect="non-scaling-stroke"/>`;
    }).join("")}</svg>`;
  }
  const tplPreview = t => t.make().filter(x => x.type !== "line" && x.type !== "comment").map(x => [x.type, x.x, x.y, x.w, x.h, x.type === "sticky" || x.type === "card" ? x.color : x.fill]);
  function renderDash(listOnly = false) {
    const x = $("#wbx"); if (!x) return;
    const q = dashQ.trim().toLowerCase(), f = b => !q || b.name.toLowerCase().includes(q);
    const card = b => `<div class="wbd-card" data-board="${b.id}" role="button" tabindex="0" title="Open ${esc(b.name)}">
        <div class="wbd-thumb">${thumb(b.preview)}</div>
        <div class="wbd-meta"><b>${esc(b.name)}</b><small class="faint">${b.mine ? "" : `${esc(b.owner)} · `}Edited ${when(b.updated)}${b.updated_by && b.updated_by !== me() ? ` by ${esc(b.updated_by)}` : ""}</small></div>
        <div class="wbd-foot"><span class="wbd-people">${(b.people || []).slice(0, 4).map(n => person(n, "", "sm")).join("")}</span><button type="button" class="iconbtn sm" data-bmenu="${b.id}" aria-label="Actions for ${esc(b.name)}">${icon("dots")}</button></div></div>`;
    const mine = list.mine.filter(f), shared = list.shared.filter(f);
    const body = `<h2 class="wbd-sec">My boards <span class="faint">${list.mine.length}</span></h2>${mine.length ? `<div class="wbd-grid">${mine.map(card).join("")}</div>` : `<p class="faint">${q ? "No boards match." : "No boards yet: start from a template above."}</p>`}
      ${shared.length ? `<h2 class="wbd-sec">Shared with me <span class="faint">${shared.length}</span></h2><div class="wbd-grid">${shared.map(card).join("")}</div>` : ""}`;
    if (listOnly && $(".wbd-boards", x)) { $(".wbd-boards", x).innerHTML = body; return; }
    x.innerHTML = `<div class="wbd"><div class="wbd-head"><div><h1 class="page">Whiteboards</h1><p class="lead">Think together on an infinite canvas: sticky notes, diagrams, tables, charts and more, with live cursors for everyone on the board.</p></div>
        <div class="wbd-actions"><div class="search"><span>${icon("search")}</span><input type="search" placeholder="Search boards" value="${esc(dashQ)}" data-wbd-q aria-label="Search boards"></div><button type="button" class="btn primary" data-wbd="new">${icon("plus")}New board</button></div></div>
      <h2 class="wbd-sec">Start from a template</h2>
      <div class="wbd-tpls">${TEMPLATES.map(t => `<button type="button" class="wbd-tpl" data-tpl="${t.id}"><span class="wbd-thumb">${t.id === "blank" ? `<span class="wbd-blank">${icon("plus")}</span>` : thumb(tplPreview(t))}</span><b>${esc(t.name)}</b><small class="faint">${esc(t.blurb)}</small></button>`).join("")}</div>
      <div class="wbd-boards">${body}</div></div>`;
  }
  function onDashClick(e) {
    const m = e.target.closest("[data-bmenu]");
    if (m) { e.stopPropagation(); const b = [...list.mine, ...list.shared].find(x => x.id === +m.dataset.bmenu); return b && menu(below(m), [["Open", "external", () => openBoard(b.id)], ["Rename", "edit", () => renameDlg(b)], ["Duplicate", "copy", () => dupBoard(b)], b.mine && ["Share", "users", () => openBoard(b.id).then(shareDlg)], "-", b.mine ? ["Delete board", "trash", () => deleteDlg(b), "", true] : ["Leave board", "logout", () => deleteDlg(b), "", true]]); }
    const tp = e.target.closest("[data-tpl]"); if (tp) return newBoard(tp.dataset.tpl);
    if (e.target.closest("[data-wbd=new]")) return templatePicker(false);
    const c = e.target.closest("[data-board]"); if (c) return openBoard(+c.dataset.board);
  }

  // ---------- boards ----------
  async function openBoard(id) {
    if (board?.id === id && !$("#wbb").hidden) return;
    await leaveBoard();
    let b; try { b = await api(`/api/boards/${id}`); } catch (e) { toast(e.message); board = null; return goHome(); }
    board = { id: b.id, name: b.name, mine: b.mine, owner: b.owner, shared: b.shared, shared_with: b.shared_with || [], updated: b.updated };
    items = clean(b.data?.items); version = b.version; base = new Map(items.map(x => [x.id, JSON.stringify(x)]));
    viewers = b.viewers || []; others = []; peopleKey = ""; sel = new Set(); undo.length = redo.length = 0; editing = null; drag = null; ctxPop = null; toolPop = null; find = null; state = "saved"; following = null; cellSel = null; threadKey = ""; panelOpen = false;
    els.forEach(el => el.remove()); els.clear(); fits.clear(); curEls.forEach(el => el.remove()); curEls.clear();
    $("#wbx").hidden = true; $("#wbb").hidden = false; document.body.classList.add("wb-full");
    if (S.view === "whiteboard") history.replaceState(null, "", `#whiteboard/${id}`);
    tool = "select"; renderChrome(); cursor(); render();
    const v = pref("view." + id);
    if (v && Number.isFinite(v.x) && Number.isFinite(v.z)) { view = { x: v.x, y: v.y, z: clampZ(v.z) }; applyView(); } else fitAll();
    stage()?.focus({ preventScroll: true });
    connectLive(); poll(); flushCursor();
    clearInterval(beat); beat = setInterval(() => { if (board && S.view === "whiteboard" && document.visibilityState === "visible") flushCursor(); }, 5000);  // presence
  }
  async function leaveBoard() {
    finishEdit(); clearTimeout(pollTimer); clearInterval(beat); live?.close(); live = null; liveOk = false;
    if (present) stopPresent();
    if (board && (saveTimer || pending())) await save();
    if (board) api(`/api/boards/${board.id}/cursor`, { method: "POST", body: { x: null, y: null, sel: [], view: [] } }).catch(() => {});
  }
  async function goHome() {
    await leaveBoard();
    board = null; items = []; els.forEach(el => el.remove()); els.clear(); others = []; curEls.forEach(el => el.remove()); curEls.clear(); toggleAi(false);
    $("#wbb").hidden = true; $("#wbx").hidden = false; document.body.classList.remove("wb-full");
    if (S.view === "whiteboard") history.replaceState(null, "", "#whiteboard");
    await loadList(); renderDash();
  }
  async function newBoard(tpl = "blank", name) {
    const t = TEMPLATES.find(x => x.id === tpl) || TEMPLATES[0];
    try {
      const b = await api("/api/boards", { method: "POST", body: { name: name || (t.id === "blank" ? "Untitled board" : t.name), data: { items: t.make() } } });
      await loadList(); await openBoard(b.id); fitAll();
      if (t.id === "blank") { const n = $("[data-wb-name]"); n?.focus(); n?.select(); }
    } catch (e) { toast(e.message); }
  }
  function insertTemplate(tpl) {
    const t = TEMPLATES.find(x => x.id === tpl); if (!t) return;
    const c = viewCenter(), made = t.make(), bb = union(made.filter(x => x.type !== "line").map(box));
    const dx = c.x - bb.x - bb.w / 2, dy = c.y - bb.y - bb.h / 2;
    made.forEach(x => { if (x.type === "line") { if (!x.a.id) x.a = { x: x.a.x + dx, y: x.a.y + dy }; if (!x.b.id) x.b = { x: x.b.x + dx, y: x.b.y + dy }; } else { x.x += dx; x.y += dy; } });
    snap(); made.forEach(x => add(x, { select: false })); sel = new Set(made.map(x => x.id)); render(); changed();
    fitTo(union(made.map(box)), Math.max(view.z, 0.6));
  }
  function templatePicker(into) {
    const f = Auth.modal(`<h3>${icon("apps")}${into ? "Insert a template" : "New board"}</h3><p class="muted">${into ? "It's added to this board, in the middle of what you see." : "Start blank or from a template; you can change everything."}</p>
      ${into ? "" : `<label class="in"><span>Name</span><input name="name" maxlength="80" placeholder="Untitled board"></label>`}
      <div class="wbd-tpls in-modal">${TEMPLATES.filter(t => !into || t.id !== "blank").map((t, i) => `<label class="wbd-tpl"><input type="radio" name="tpl" value="${t.id}" ${i === 0 ? "checked" : ""} class="sr"><span class="wbd-thumb">${t.id === "blank" ? `<span class="wbd-blank">${icon("plus")}</span>` : thumb(tplPreview(t))}</span><b>${esc(t.name)}</b><small class="faint">${esc(t.blurb)}</small></label>`).join("")}</div>`,
      async f => { const tpl = f.querySelector("[name=tpl]:checked")?.value; $("#modal").close(); if (into) insertTemplate(tpl); else await newBoard(tpl, f.elements.name.value.trim()); }, { submit: into ? "Insert" : "Create board" });
    f.elements.name?.focus();
  }
  async function rename(name) {
    name = name.trim(); if (!board || !name || name === board.name) { const n = $("[data-wb-name]"); if (n) n.value = board?.name || ""; return; }
    try { await api(`/api/boards/${board.id}`, { method: "PATCH", body: { name } }); board.name = name; loadList(); } catch (e) { toast(e.message); }
  }
  function renameDlg(b) {
    const f = Auth.modal(`<h3>${icon("edit")}Rename board</h3><label class="in"><span>Name</span><input name="name" maxlength="80" value="${esc(b.name)}" required></label>`, async f => {
      await api(`/api/boards/${b.id}`, { method: "PATCH", body: { name: f.elements.name.value } }); $("#modal").close();
      if (board?.id === b.id) { board.name = f.elements.name.value.trim(); renderTL(); } await loadList(); if (!board) renderDash();
    }, { submit: "Rename" });
    f.elements.name.select();
  }
  async function dupBoard(b) { try { if (board) await save(); const n = await api(`/api/boards/${b.id}/duplicate`, { method: "POST" }); await loadList(); await openBoard(n.id); toast("Board duplicated"); } catch (e) { toast(e.message); } }
  function deleteDlg(b) {
    Auth.modal(b.mine ? `<h3>${icon("trash")}Delete “${esc(b.name)}”?</h3><p class="muted">This deletes the board for everyone it's shared with. It can't be undone.</p>`
      : `<h3>${icon("logout")}Leave “${esc(b.name)}”?</h3><p class="muted">It stays with ${esc(b.owner)} and anyone else it's shared with; you'll need them to share it again.</p>`,
      async () => {
        await api(`/api/boards/${b.id}`, { method: "DELETE" }); $("#modal").close();
        if (board?.id === b.id) { clearTimeout(saveTimer); base = new Map(); items = []; board = null; }
        goHome();
      }, { submit: b.mine ? "Delete" : "Leave", danger: true });
  }
  function shareDlg() {
    if (!board) return;
    if (!board.mine) return Auth.modal(`<h3>${icon("users")}Shared by ${esc(board.owner)}</h3><p class="muted">Everyone the owner shares this board with can see and edit it, with live cursors.</p>`, async () => $("#modal").close(), { submit: "Done" });
    const f = Auth.modal(`<h3>${icon("users")}Share “${esc(board.name)}”</h3>
      <label class="in"><span>People who can edit <em class="opt">usernames, comma-separated</em></span><input name="users" value="${esc((board.shared_with || []).join(", "))}" placeholder="alice, bob" autocomplete="off" spellcheck="false"></label>
      <p class="fine">They'll find it under <b>Shared with me</b> in Whiteboard. On the board you see each other's cursors and selections live, changes show up as they're made, and sticky notes carry their author's name.</p>
      <p class="fine"><button type="button" class="linkbtn" data-copy-link>${icon("link")}Copy the board's link</button></p>`,
      async f => {
        const r = await api(`/api/boards/${board.id}`, { method: "PATCH", body: { shared_with: f.elements.users.value.split(/[\s,]+/).filter(Boolean) } });
        board.shared_with = r.shared_with || []; board.shared = r.shared; $("#modal").close(); toast(board.shared ? "Sharing updated" : "The board is private again");
        els.forEach(el => el._html = null); render(); loadList();
      }, { submit: "Save" });
    $("[data-copy-link]", f).onclick = async () => { const url = `${location.origin}${location.pathname}#whiteboard/${board.id}`; try { await navigator.clipboard.writeText(url); toast("Link copied: it opens for people the board is shared with"); } catch { toast(url); } };
    f.elements.users.focus();
  }

  // ---------- find ----------
  function openFind() { find = find || { q: "", hits: [], i: -1 }; renderTL(); const i = $("[data-wb-find]"); i?.focus(); i?.select(); }
  function closeFind() { find = null; renderTL(); drawOverlay(); }
  function runFind(q) {
    const s = q.trim().toLowerCase();
    find = { q, i: -1, hits: s ? items.filter(x => String(textOf(x) || "").toLowerCase().includes(s)).map(x => x.id) : [] };
    const n = $("#wb-find-n"); if (n) n.textContent = s ? `${find.hits.length} found` : "";
    if (find.hits.length) findNext(1); else drawOverlay();
  }
  function findNext(dir) {
    if (!find?.hits.length) return;
    find.i = (find.i + dir + find.hits.length) % find.hits.length;
    const it = byId(find.hits[find.i]); if (it) fitTo(grow(box(it), 120), Math.max(view.z, 0.8));
    const n = $("#wb-find-n"); if (n) n.textContent = `${find.i + 1} of ${find.hits.length}`;
    drawOverlay();
  }

  // ---------- export, import, outline ----------
  let measurer = null;
  function wrap(text, width, font) {
    measurer = measurer || document.createElement("canvas").getContext("2d"); measurer.font = font;
    const out = [];
    for (const para of String(text || "").split("\n")) {
      let line = "";
      for (const word of para.split(/(\s+)/)) {
        const t = line + word;
        if (measurer.measureText(t).width <= width || !line.trim()) { line = t; continue; }
        out.push(line.trimEnd()); line = word.trimStart();
        while (measurer.measureText(line).width > width && line.length > 1) { let k = line.length; while (k > 1 && measurer.measureText(line.slice(0, k)).width > width) k--; out.push(line.slice(0, k)); line = line.slice(k); }
      }
      out.push(line.trimEnd());
    }
    return out;
  }
  const FONT = `Inter, system-ui, -apple-system, "Segoe UI", sans-serif`;
  function textSvg(text, b, fs, { color = "#1e1e1e", anchor = "middle", vcenter = true, bold = false, pad = 12, max = 0 } = {}) {
    const font = `${bold ? 700 : 400} ${fs}px ${FONT}`, lh = fs * 1.3;
    let lines = wrap(text, Math.max(10, b.w - 2 * pad), font); if (max) lines = lines.slice(0, max);
    const top = vcenter ? b.y + (b.h - lines.length * lh) / 2 : b.y + pad / 2, x = anchor === "start" ? b.x + pad : anchor === "end" ? b.x + b.w - pad : b.x + b.w / 2;
    return `<text font-family='${FONT}' font-size="${fs}" font-weight="${bold ? 700 : 400}" fill="${color}" text-anchor="${anchor}">${lines.map((l, i) => `<tspan x="${r1(x)}" y="${r1(top + (i + 0.8) * lh)}">${esc(l) || " "}</tspan>`).join("")}</text>`;
  }
  const anchorOf = a => ({ left: "start", right: "end" }[a] || "middle");
  function svgItem(it) {
    const b = box(it), rot = ROT.has(it.type) ? num(it.rot) : 0, turn = s => rot ? `<g transform="rotate(${rot} ${r1(b.x + b.w / 2)} ${r1(b.y + b.h / 2)})">${s}</g>` : s;
    const card = (fill = "#ffffff", stroke = "#dee2e6") => `<rect x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="${r1(b.h)}" rx="6" fill="${fill}" stroke="${stroke}"/>`;
    switch (it.type) {
      case "sticky": return turn(`<rect x="${r1(b.x)}" y="${r1(b.y + 3)}" width="${r1(b.w)}" height="${r1(b.h)}" rx="2" fill="#000" opacity=".08"/><rect x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="${r1(b.h)}" rx="2" fill="${stickyBg(it.color)}"/>${textSvg(it.text, b, fits.get(it.id)?.fs || 20, { anchor: anchorOf(it.align || "center"), pad: 16 })}`);
      case "text": return turn(textSvg(it.text, { ...b, x: b.x - 2 }, num(it.fs, 20), { color: paintX(col(it.color, "ink")), anchor: anchorOf(it.align || "left"), vcenter: false, bold: it.bold, pad: 2 }));
      case "shape": return turn(`<g transform="translate(${r1(b.x)} ${r1(b.y)})">${shapeSvg(it, b.w, b.h, paintX)}</g>${textSvg(it.text, b, num(it.fs, 16), { color: paintX(col(it.color, "ink")), anchor: anchorOf(it.align || "center"), bold: it.bold })}`);
      case "frame": return `<rect x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="${r1(b.h)}" rx="6" fill="${paintX(col(it.fill, "#ffffff"))}" stroke="#ced4da"/>${textSvg(it.title || "Frame", { x: b.x, y: b.y - 26, w: b.w, h: 24 }, 14, { color: "#495057", anchor: "start", bold: true, pad: 2 })}`;
      case "image": return IMG.test(it.src || "") ? turn(`<image href="${it.src}" x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="${r1(b.h)}" preserveAspectRatio="none"/>`) : "";
      case "draw": return `<path transform="translate(${r1(b.x)} ${r1(b.y)})" d="${smooth((it.pts || []).map(q => [num(q[0]), num(q[1])]))}" fill="none" stroke="${paintX(col(it.color, "ink"))}" stroke-width="${num(it.sw, 3)}" stroke-linecap="round" stroke-linejoin="round" opacity="${it.hl ? 0.45 : 1}"/>`;
      case "chart": return turn(card() + `<g transform="translate(${r1(b.x)} ${r1(b.y)})">${chartSvg(it, b.w, b.h, paintX)}</g>`);
      case "card": { const c = col(it.color, CARD[0]); return turn(card("#ffffff", c) + `<rect x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="5" rx="2" fill="${c}"/>` + textSvg(it.title || "Card", { x: b.x, y: b.y + 8, w: b.w, h: 24 }, 14, { anchor: "start", vcenter: false, bold: true, max: 2 }) + (it.text ? textSvg(it.text, { x: b.x, y: b.y + 34, w: b.w, h: b.h - 40 }, 12, { color: "#555", anchor: "start", vcenter: false, max: 4 }) : "")); }
      case "doc": return turn(card() + textSvg(it.title || "Document", { x: b.x, y: b.y + 10, w: b.w, h: 26 }, 17, { anchor: "start", vcenter: false, bold: true, pad: 18, max: 2 }) + textSvg(it.text, { x: b.x, y: b.y + 46, w: b.w, h: b.h - 52 }, 13, { color: "#444", anchor: "start", vcenter: false, pad: 18, max: Math.max(1, Math.floor((b.h - 60) / 17)) }));
      case "link": { const u = safeUrl(it.url); return turn(card() + textSvg(u ? new URL(u).hostname : "link", { x: b.x, y: b.y + 8, w: b.w, h: 20 }, 11, { color: "#666", anchor: "start", vcenter: false }) + textSvg(it.title || it.url || "", { x: b.x, y: b.y + 30, w: b.w, h: 24 }, 14, { anchor: "start", vcenter: false, bold: true, max: 2 })); }
      case "table": {
        const T = tbl(it), W = T.cols.reduce((a, c) => a + c, 0), H = T.rows.reduce((a, c) => a + c, 0), out = [card("#ffffff", "#ced4da")];
        let y = b.y;
        T.rows.forEach((rh, r) => { const h = b.h * rh / H; let x = b.x; T.cols.forEach((cw, c) => { const w = b.w * cw / W, fill = T.fills[r][c] || (r === 0 && it.head !== false ? "#f1f3f5" : "");
          out.push(`<rect x="${r1(x)}" y="${r1(y)}" width="${r1(w)}" height="${r1(h)}" fill="${fill || "none"}" stroke="#dee2e6"/>${T.cells[r][c] ? textSvg(T.cells[r][c], { x, y, w, h }, 12, { anchor: "start", pad: 8, bold: r === 0 && it.head !== false, max: Math.max(1, Math.floor(h / 16)) }) : ""}`); x += w; }); y += h; });
        return out.join("");
      }
      case "comment": return `<circle cx="${r1(num(it.x) + 14)}" cy="${r1(num(it.y) - 14)}" r="13" fill="#ffd43b" stroke="#e8a800"/>`;
      case "line": {
        const R = route(it), sw = num(it.sw, 2), c = paintX(col(it.color, "ink")), size = 9 + sw * 2;
        const heads = (it.end === "arrow" ? head(R.fb, R.b, size) : "") + (it.start === "arrow" ? head(R.fa, R.a, size) : "");
        let s = `<path d="${R.d}" fill="none" stroke="${c}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" ${it.dash ? `stroke-dasharray="${sw * 3} ${sw * 2}"` : ""}/>${heads ? `<path d="${heads}" fill="${c}" stroke="${c}"/>` : ""}`;
        if (it.text) { const lw = Math.min(260, wrap(it.text, 1e4, `400 13px ${FONT}`).reduce((m, l) => Math.max(m, measurer.measureText(l).width), 0) + 14); s += `<rect x="${r1(R.mid.x - lw / 2)}" y="${r1(R.mid.y - 11)}" width="${r1(lw)}" height="22" rx="6" fill="#ffffff"/>${textSvg(it.text, { x: R.mid.x - lw / 2, y: R.mid.y - 11, w: lw, h: 22 }, 13, { pad: 7 })}`; }
        return s;
      }
    }
    return "";
  }
  function svgOf(src) {
    const order = [...src].sort((a, b) => (a.type === "frame" ? 0 : 1) - (b.type === "frame" ? 0 : 1) || items.indexOf(a) - items.indexOf(b));
    const bb = grow(union(order.map(it => { const b = box(it); return it.type === "line" || it.type === "draw" || num(it.rot) ? grow(b, 40) : it.type === "frame" ? { ...b, y: b.y - 28, h: b.h + 28 } : b; })), 40);
    return { svg: `<svg xmlns="http://www.w3.org/2000/svg" width="${Math.ceil(bb.w)}" height="${Math.ceil(bb.h)}" viewBox="${r1(bb.x)} ${r1(bb.y)} ${Math.ceil(bb.w)} ${Math.ceil(bb.h)}"><rect x="${r1(bb.x)}" y="${r1(bb.y)}" width="${r1(bb.w)}" height="${r1(bb.h)}" fill="#ffffff"/>${order.map(svgItem).join("")}</svg>`, w: bb.w, h: bb.h };
  }
  const fname = ext => `${(board?.name || "board").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-") || "board"}.${ext}`;
  function download(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
  async function exportImage(kind, src) {
    if (!src.length) return toast("Nothing to export yet");
    finishEdit();
    const { svg, w, h } = svgOf(src);
    if (kind === "svg") return download(new Blob([svg], { type: "image/svg+xml" }), fname("svg"));
    const img = new Image(); img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    try { await img.decode(); } catch { return toast("Couldn't draw the image"); }
    const s = Math.min(2, 8000 / Math.max(w, h)), c = document.createElement("canvas"); c.width = Math.ceil(w * s); c.height = Math.ceil(h * s);
    const g = c.getContext("2d"); g.scale(s, s); g.drawImage(img, 0, 0, w, h);
    c.toBlob(b => b ? download(b, fname("png")) : toast("Couldn't make the PNG"), "image/png");
  }
  function exportJson() { download(new Blob([JSON.stringify({ app: "subnet-scout-whiteboard", name: board?.name, items }, null, 1)], { type: "application/json" }), fname("json")); }
  function pickFile(accept, then) { const i = document.createElement("input"); i.type = "file"; i.accept = accept; i.onchange = () => i.files[0] && then(i.files[0]); i.click(); }
  async function importJson(file) {
    try { const d = JSON.parse(await file.text()), src = clean(d.items || d); if (!src.length) return toast("No board items in that file"); pasteItems(src); toast(`Imported ${src.length} item${src.length === 1 ? "" : "s"}`); }
    catch { toast("That isn't a board file"); }
  }
  // the board as text: frames with what's in them, then the rest, then who connects to what
  function outline(name, src) {
    const find2 = id => src.find(x => x.id === id);
    const label = it => String(textOf(it) || "").replace(/\s+/g, " ").trim().slice(0, 200) || ({ image: "an image", draw: "a drawing", sticky: "an empty sticky", shape: `a ${it.shape || "shape"}`, chart: "a chart" }[it.type] || it.type);
    const content = x => ["sticky", "text", "shape", "image", "card", "doc", "link", "chart", "table", "comment"].includes(x.type) && (String(textOf(x) || "").trim() || x.type === "image");
    const bx = x => ({ x: num(x.x), y: num(x.y), w: num(x.w, 1), h: num(x.h, 1) }), byPos = (a, b) => num(a.y) - num(b.y) || num(a.x) - num(b.x);
    const tag = { shape: x => `[${x.shape || "shape"}] `, card: () => "[card] ", doc: () => "[document] ", link: x => `[link ${safeUrl(x.url)}] `, chart: x => `[${x.kind || "pie"} chart: ${(x.data || []).map(d => `${d.label} ${d.value}`).join(", ")}] `, table: () => "[table] ", comment: () => "[comment] " };
    const line = x => `- ${tag[x.type] ? tag[x.type](x) : ""}${label(x)}${x.react ? " " + Object.entries(x.react).map(([k, v]) => `${k}${v.length}`).join(" ") : ""}`;
    const used = new Set(), out = [`# ${name}`];
    for (const f of src.filter(x => x.type === "frame").sort(byPos)) {
      const kids = src.filter(x => content(x) && inside(bx(x), bx(f))).sort(byPos);
      out.push("", `## ${label(f)}`, ...(kids.length ? kids.map(x => (used.add(x.id), line(x))) : ["- (empty)"]));
    }
    const rest = src.filter(x => content(x) && !used.has(x.id)).sort(byPos);
    if (rest.length) out.push("", used.size ? "## Outside frames" : "## Notes", ...rest.map(line));
    const links = src.filter(x => x.type === "line" && (x.a?.id || x.b?.id));
    if (links.length) out.push("", "## Connections", ...links.map(l => { const A = find2(l.a?.id), B = find2(l.b?.id); return `- ${A ? label(A) : "(a point)"} ${l.end === "arrow" && l.start !== "arrow" ? "→" : l.start === "arrow" && l.end !== "arrow" ? "←" : l.end === "arrow" ? "↔" : "—"} ${B ? label(B) : "(a point)"}${l.text ? `: ${l.text.replace(/\s+/g, " ")}` : ""}`; }));
    return out.join("\n");
  }
  async function copyOutline() { try { await navigator.clipboard.writeText(outline(board.name, items)); toast("Board copied as text: paste it into a chat with an agent"); } catch { toast("Couldn't copy"); } }
  // for the Study tab: pick a board and get it as text
  async function pickOutline() {
    let l; try { l = await api("/api/boards"); } catch (e) { toast(e.message); return null; }
    const all = [...l.mine, ...l.shared];
    if (!all.length) { toast("You have no whiteboards yet: make one in Whiteboard"); return null; }
    if (board) await save();
    return new Promise(res => {
      let done = false;
      Auth.modal(`<h3>${icon("sticky")}Add a whiteboard</h3><p class="muted">Its frames, stickies, shapes and connections go into your message as text.</p>
        <div class="pick-list">${all.map((b, i) => `<label class="pick"><span>${icon("sticky")}</span><span><b>${esc(b.name)}</b><small class="faint">${b.items} items · ${when(b.updated)}</small></span><input type="radio" name="b" value="${b.id}" ${i ? "" : "checked"}></label>`).join("")}</div>`,
        async f => { const id = f.querySelector("[name=b]:checked")?.value; if (!id) throw new Error("Pick a board."); const b = await api(`/api/boards/${id}`); done = true; $("#modal").close(); res(outline(b.name, clean(b.data?.items))); }, { submit: "Add" });
      $("#modal").addEventListener("close", () => { if (!done) res(null); }, { once: true });
    });
  }
  function help() {
    const rows = [["Tools", [["V / H or Space", "Select / hand"], ["T", "Text"], ["N", "Sticky note"], ["R / O", "Rectangle / ellipse"], ["L", "Connection line"], ["P / M / E", "Pen / highlighter / eraser"], ["F", "Frame"], ["C", "Comment"], ["I", "Image"], ["+ in the toolbar", "Table, chart, card, document, link, mind map, templates"]]],
      ["Edit", [["Double-click", "Add a sticky, or edit"], ["Enter", "Edit the selected item"], ["Tab or Ctrl+Enter", "Next sticky (while typing)"], ["Tab / Enter", "Next cell (in a table)"], ["Ctrl+D", "Duplicate"], ["Alt+drag", "Drag a copy"], ["Ctrl+C / X / V", "Copy / cut / paste"], ["Del", "Delete"], ["Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"], ["Ctrl+G / Ctrl+Shift+G", "Group / ungroup"], ["Ctrl+L", "Lock"], ["] / [", "Forward / backward (Ctrl: front / back)"], ["Arrows", "Nudge (Shift: 10px)"], ["Shift while rotating", "15° steps"]]],
      ["View", [["Ctrl+wheel or pinch", "Zoom"], ["Wheel or Space+drag", "Pan"], ["Shift+1", "Fit everything"], ["Shift+2", "Zoom to selection"], ["Shift+0", "Zoom to 100%"], ["Ctrl+F", "Find"], ["Ctrl/⌘ while dragging", "No snapping"], ["Present: ← →, Esc", "Previous / next frame, exit"]]]];
    Auth.modal(`<h3>${icon("keyboard")}Whiteboard shortcuts</h3><div class="wb-keys">${rows.map(([h, r]) => `<section><h4>${h}</h4>${r.map(([k, l]) => `<div><kbd>${esc(k)}</kbd><span>${esc(l)}</span></div>`).join("")}</section>`).join("")}</div>`, async () => $("#modal").close(), { submit: "Got it" });
    $("#modal [data-close]")?.remove();
  }

  // ---------- templates ----------
  const T = {
    sticky: (x, y, text, color = "yellow", w = 200, h = 200, extra = {}) => ({ id: uid(), type: "sticky", x, y, w, h, color, text, by: "", ...extra }),
    frame: (x, y, w, h, title, fill = "#ffffff") => ({ id: uid(), type: "frame", x, y, w, h, title, fill }),
    text: (x, y, text, fs = 28, w = 600, bold = true) => ({ id: uid(), type: "text", x, y, w, h: fs * 1.4, text, fs, bold, color: "ink" }),
    shape: (x, y, w, h, text, shape = "rect", fill = "#ffffff") => ({ id: uid(), type: "shape", x, y, w, h, shape, text, fill, stroke: "ink", sw: 2, fs: 15 }),
    link: (a, b, text = "", route = "straight", extra = {}) => ({ id: uid(), type: "line", a: { id: a.id }, b: { id: b.id }, color: "ink", sw: 2, start: "none", end: "arrow", route, ...(text ? { text } : {}), ...extra }),
    card: (x, y, title, color, w = 150, h = 44) => ({ id: uid(), type: "card", x, y, w, h, title, text: "", color, who: "", due: "" }),
    table: (x, y, w, h, cells, cols, fills = []) => ({ id: uid(), type: "table", x, y, w, h, rows: cells.map(() => 1), cols: cols || cells[0].map(() => 1), cells, fills, head: true }),
    chart: (x, y, w, h, title, kind, data) => ({ id: uid(), type: "chart", x, y, w, h, title, kind, data }),
    doc: (x, y, w, h, title, text) => ({ id: uid(), type: "doc", x, y, w, h, title, text }),
  };
  const flow = (ox, oy) => {  // a small order flowchart
    const s = T.shape(ox, oy, 150, 60, "Start", "round", "#a5d8ff"), r = T.shape(ox, oy + 110, 150, 60, "Receive order", "rect", "#a5d8ff"), c = T.shape(ox, oy + 220, 150, 60, "Check stock", "rect", "#a5d8ff");
    const st = T.shape(ox + 220, oy + 205, 120, 90, "In stock?", "ellipse", "#f5d128"), cv = T.shape(ox + 420, oy + 300, 130, 100, "Card valid?", "ellipse", "#f5d128");
    const k = T.shape(ox + 220, oy + 330, 150, 60, "Check payment", "rect", "#a5d8ff"), x = T.shape(ox + 410, oy + 110, 150, 60, "Cancel order", "rect", "#a5d8ff"), ship = T.shape(ox + 620, oy + 320, 150, 60, "Ship order", "round", "#b2f2bb");
    return [s, r, c, st, cv, k, x, ship, T.link(s, r, "", "elbow"), T.link(r, c, "", "elbow"), T.link(c, st, "", "elbow"), T.link(st, x, "no", "elbow"), T.link(st, k, "yes", "elbow"), T.link(k, cv, "", "elbow"), T.link(cv, x, "no", "elbow"), T.link(cv, ship, "yes", "elbow")];
  };
  const timeline = (ox, oy) => {
    const weeks = ["", "W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"], rows = [["Performance", "#d8f5a2"], ["Product marketing", "#fff9b1"], ["User activation", "#ffc078"], ["Integrations", "#d0bfff"]];
    const tb2 = T.table(ox, oy, 980, 300, [weeks, ...rows.map(([n]) => [n, ...Array(8).fill("")])], [2.2, ...Array(8).fill(1)], [[], ...rows.map(([, c]) => [c])]);
    const cw = 980 / (2.2 + 8), rh = 300 / 5, cell = (r, c) => ({ x: ox + cw * (2.2 + c) + 6, y: oy + rh * r + 8 });
    return [tb2, T.card(cell(1, 0).x, cell(1, 0).y, "Marketing", "#12a37f", cw * 2 - 12), T.card(cell(1, 5).x, cell(1, 5).y, "Tech release", "#12a37f", cw * 2 - 12),
      T.card(cell(2, 1).x, cell(2, 1).y, "Design", "#f5d128", cw * 2 - 12), T.card(cell(2, 4).x, cell(2, 4).y, "Save the date", "#f5d128", cw * 2 - 12),
      T.card(cell(3, 0).x, cell(3, 0).y, "Send reminder", "#8c3ef0", cw * 2 - 12), T.card(cell(3, 5).x, cell(3, 5).y, "Product Hunt", "#f58a07", cw * 2 - 12)];
  };
  const ssc = (ox, oy) => [["Start", "violet"], ["Stop", "lime"], ["Continue", "orange"]].flatMap(([h, c], i) => [T.text(ox + i * 260, oy, h, 30, 220), ...[0, 1, 2, 3, 4].map(k => T.sticky(ox + i * 260 + (k % 2) * 110, oy + 60 + Math.floor(k / 2) * 110, "", c, 96, 96))]);
  const TEMPLATES = [
    { id: "blank", name: "Blank board", icon: "plus", blurb: "An empty canvas", make: () => [] },
    { id: "launch", name: "Product launch", icon: "zap", blurb: "Research, retro, flow, timeline and goals on one board", make: () => {
        const c1 = T.chart(-1000, -420, 400, 200, "Research 1", "pie", [{ label: "Organic", value: 42, color: "#ffd02f" }, { label: "Referral", value: 25, color: "#fcc2d7" }, { label: "Paid", value: 18, color: "#d0bfff" }, { label: "Other", value: 15, color: "#8fd14f" }]);
        const c2 = T.chart(-1000, -200, 400, 200, "Research 2", "donut", [{ label: "Miners", value: 26, color: "#ffd02f" }, { label: "Validators", value: 33, color: "#ff7a59" }, { label: "Holders", value: 23, color: "#8fd14f" }, { label: "Builders", value: 18, color: "#a5d8ff" }]);
        const big = T.sticky(560, -420, "Launch goal: 1,000 active miners in the first month", "gold", 330, 330, { rot: 5 });
        const cm = { id: uid(), type: "comment", x: 30, y: 150, thread: [{ by: me() || "you", text: "Can we move the Product Hunt launch a week earlier?", ts: Math.round(Date.now() / 1000) }] };
        return [c1, c2, T.doc(-1040, 20, 250, 320, "Leading in the digital age", "Notes from the kick-off.\n\n- Who is it for\n- What changes for them\n- How we'll know it worked"),
          { id: uid(), type: "link", x: -760, y: 40, w: 250, h: 110, url: "https://docs.bittensor.com", title: "Bittensor docs", text: "Shared with the team" },
          ...ssc(-380, -440), big, ...flow(380, 0), ...timeline(-760, 380), cm];
      } },
    { id: "retro", name: "Start, stop, continue", icon: "cycle", blurb: "A quick team retrospective", make: () => [T.frame(-420, -120, 860, 520, "Retrospective", "#f8f9fa"), ...ssc(-380, -80)] },
    { id: "brainstorm", name: "Brainstorm", icon: "bulb", blurb: "A question and room for ideas", make: () => [T.frame(-460, -320, 920, 640, "Brainstorm", "#fff9db"), T.text(-420, -280, "What problem are we solving?", 30, 840),
        ...["Idea", "Idea", "Idea", "Question", "Risk", "Wild idea"].map((t, i) => T.sticky(-420 + (i % 3) * 290, -170 + Math.floor(i / 3) * 240, t, ["yellow", "yellow", "yellow", "blue", "pink", "violet"][i]))] },
    { id: "kanban", name: "Kanban", icon: "columns", blurb: "To do, doing, done", make: () => [["To do", "#f8f9fa"], ["Doing", "#e7f5ff"], ["Done", "#ebfbee"]].flatMap(([t, f], i) => [T.frame(-570 + i * 390, -360, 360, 720, t, f), ...(i === 0 ? ["First task", "Second task"].map((s, k) => T.card(-550, -300 + k * 130, s, CARD[k], 320, 110)) : [])]) },
    { id: "flow", name: "Flowchart", icon: "elbow", blurb: "Steps, decisions and where they lead", make: () => flow(-400, -250) },
    { id: "timeline", name: "Timeline", icon: "table", blurb: "Workstreams by week, with cards", make: () => timeline(-490, -150) },
    { id: "mindmap", name: "Mind map", icon: "globe", blurb: "A central idea with branches", make: () => {
        const mid = T.shape(-120, -50, 240, 100, "Central idea", "ellipse", "#fff9b1");
        const kids = [[-460, -280], [-460, 0], [-460, 280], [260, -280], [260, 0], [260, 280]].map(([x, y], i) => T.shape(x, y - 35, 200, 70, `Branch ${i + 1}`, "round", Object.values(STICKY)[i + 4]));
        return [mid, ...kids, ...kids.map(k => ({ ...T.link(mid, k, "", "curve"), end: "none" }))];
      } },
    { id: "system", name: "System design", icon: "server", blurb: "Requirements, components and data flow", make: () => {
        const c = T.shape(-560, -40, 160, 80, "Client", "round"), g = T.shape(-300, -40, 180, 80, "API gateway", "rect"), s = T.shape(-20, -40, 180, 80, "Service", "rect"), q = T.shape(-20, 140, 180, 80, "Queue", "rect", "#fff9b1");
        const k = T.shape(260, -160, 160, 80, "Cache", "round", "#a5d8ff"), d = T.shape(260, 30, 160, 110, "Database", "cylinder", "#d0bfff"), w = T.shape(260, 200, 160, 80, "Worker", "rect");
        return [T.frame(-620, -420, 1100, 760, "System design"), T.sticky(-580, -380, "Functional requirements", "yellow", 240, 150), T.sticky(-320, -380, "Scale: users, QPS, data size", "blue", 240, 150), T.sticky(-60, -380, "Latency and cost targets", "lime", 240, 150),
          c, g, s, q, k, d, w, T.link(c, g, "HTTPS"), T.link(g, s), T.link(s, k, "read"), T.link(s, d, "write"), T.link(s, q, "events", "elbow"), T.link(q, w, "", "elbow")];
      } },
    { id: "swot", name: "SWOT", icon: "target", blurb: "Strengths, weaknesses, opportunities, threats", make: () => [["Strengths", "#ebfbee"], ["Weaknesses", "#fff0f6"], ["Opportunities", "#e7f5ff"], ["Threats", "#fff4e6"]].map(([t, f], i) => T.frame(-500 + (i % 2) * 510, -400 + Math.floor(i / 2) * 410, 490, 390, t, f)) },
    { id: "week", name: "Weekly plan", icon: "calendar", blurb: "A goal and seven days", make: () => [T.frame(-1010, -480, 2020, 140, "Goal this week", "#fff9db"), T.sticky(-990, -440, "One sentence goal", "yellow", 400, 80),
        ...["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => T.frame(-1010 + i * 290, -300, 270, 600, d, i > 4 ? "#f8f9fa" : "#ffffff"))] },
  ];

  // ---------- the view ----------
  function init() { $("#nav-board").hidden = !Auth.me(); }
  function wire() {
    if (wired) return; wired = true;
    layout();
    document.addEventListener("keydown", onKey);
    document.addEventListener("keyup", onKeyUp);
    document.addEventListener("copy", onCopy);
    document.addEventListener("cut", onCut);
    document.addEventListener("paste", onPaste);
    addEventListener("blur", () => { spaceDown = false; cursor(); });
    addEventListener("beforeunload", e => { if (board && (pending() || saving)) { e.preventDefault(); e.returnValue = ""; } });
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden" && board) save(); else if (board && S.view === "whiteboard") { fetchLatest(); poll(); } });
  }
  async function open() {
    wire();
    const want = pref("open"); if (want) pref("open", 0);
    if (want) { await loadList(); return openBoard(+want); }
    if (board) {  // back to a board left open: full screen again, live again
      $("#wbx").hidden = true; $("#wbb").hidden = false; document.body.classList.add("wb-full");
      history.replaceState(null, "", `#whiteboard/${board.id}`); renderChrome(); render(); applyView(); connectLive(); poll(); fetchLatest();
      clearInterval(beat); beat = setInterval(() => { if (board && S.view === "whiteboard" && document.visibilityState === "visible") flushCursor(); }, 5000);
      return;
    }
    $("#wbb").hidden = true; $("#wbx").hidden = false; document.body.classList.remove("wb-full");
    if (!list.mine.length && !list.shared.length) $("#wbx").innerHTML = `<div class="wbd">${Loading.cards(3, "card")}</div>`;
    await loadList(); renderDash();
  }
  function stop() {
    if (!wired) return;
    finishEdit(); clearTimeout(pollTimer); clearInterval(beat); spaceDown = false; document.body.classList.remove("wb-full");
    live?.close(); live = null; liveOk = false;
    if (present) stopPresent();
    if (board && (saveTimer || pending())) save();
    document.querySelector(".wb-menu")?.remove();
  }

  return { init, open, stop, pickOutline, outline };
})();
