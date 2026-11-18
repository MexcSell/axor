/* Animated backdrop, "AXoR Neural Renaissance": the Mona Lisa, darkened and tinted, as a large faint portrait behind the page,
   with a slow neural network drifting around her, light travelling its connections and her facial contours, soft energy waves,
   floating dust, an occasional scan across the portrait and a glow that follows the pointer. One canvas behind everything:
   ignores clicks, ~30 fps, pauses with the tab, follows the light/dark theme and the accent color, holds a still frame when the
   system asks for reduced motion. Strength is a per-device choice (localStorage "backdrop": off | subtle | vivid, theme panel).
   Portrait: Leonardo da Vinci, Mona Lisa (public domain), Wikimedia Commons "Mona_Lisa,_by_Leonardo_da_Vinci,_from_C2RMF_retouched.jpg";
   brand/neural-portrait.webp is a grayscale, contrast-curved crop of it with the vignette baked into its alpha. */
(() => {
  // her facial contours, as fractions of the portrait image
  const FACE = {
    face: [[.368, .167], [.354, .222], [.35, .278], [.357, .333], [.375, .4], [.403, .444], [.438, .483], [.486, .5], [.542, .494], [.597, .472], [.632, .433], [.649, .378], [.653, .322], [.649, .267], [.642, .211], [.625, .172]],
    hair: [[.368, .167], [.438, .158], [.507, .156], [.576, .161], [.625, .172]],
    browL: [[.375, .28], [.414, .271], [.451, .274]], browR: [[.514, .278], [.553, .267], [.59, .271]],
    eyeL: [[.382, .3], [.417, .29], [.451, .302], [.417, .311], [.382, .3]], eyeR: [[.517, .301], [.549, .29], [.583, .297], [.549, .308], [.517, .301]],
    nose: [[.472, .294], [.468, .328], [.465, .356], [.444, .383], [.472, .397], [.5, .389], [.507, .372]],
    mouth: [[.424, .424], [.472, .43], [.514, .428], [.531, .422]],
    neck: [[.438, .483], [.431, .556], [.41, .6]],
  };
  const PATHS = Object.values(FACE);
  const LEVELS = {
    subtle: { portrait: .26, paper: .10, nodes: 1, sparks: 1, waves: 1, face: [8000, 15000] },
    vivid: { portrait: .40, paper: .16, nodes: 1.35, sparks: 1.7, waves: 1.8, face: [4500, 8000] },
  };
  const CYAN = [34, 211, 238], TEAL = [14, 116, 144];

  const cv = document.createElement("canvas");
  cv.id = "backdrop"; cv.setAttribute("aria-hidden", "true");
  document.body.prepend(cv);
  const ctx = cv.getContext("2d");
  const fx = document.createElement("canvas"), fctx = fx.getContext("2d");  // facial light and scan, masked to the portrait
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const img = new Image();
  img.src = "/static/brand/neural-portrait.webp";

  let W = 0, Hh = 0, dpr = 1, col = {}, lvl = LEVELS.subtle, last = 0, choice = "";
  let box = { x: 0, y: 0, w: 0, h: 0 }, src = null, por = null, lum = null;  // where the portrait sits; tinted image, scaled copy; light mask
  let nodes = [], motes = [], sparks = [], links = [], rays = [], scan = null, nextSpark = 0, nextRay = 0, nextScan = 0;
  const ptr = { x: 0, y: 0, tx: 0, ty: 0, on: false }, par = { x: 0, y: 0, tx: 0, ty: 0 };
  const rnd = (a, b) => a + Math.random() * (b - a);
  const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
  const css = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, a)})`;

  function rgb(c) {
    c = c.trim();
    if (c.startsWith("#")) { const n = c.length === 4 ? c.slice(1).split("").map(h => h + h).join("") : c.slice(1); return [0, 2, 4].map(i => parseInt(n.slice(i, i + 2), 16)); }
    const m = c.match(/\d+(\.\d+)?/g) || [128, 128, 128];
    return m.slice(0, 3).map(Number);
  }
  function colors() {
    const cs = getComputedStyle(document.documentElement), bg = cs.getPropertyValue("--bg").trim();
    const dark = bg.startsWith("#") ? parseInt(bg.slice(1, 3), 16) < 90 : false;
    col = { dark, a: rgb(cs.getPropertyValue("--accent")), c: dark ? CYAN : TEAL, ink: rgb(cs.getPropertyValue("--text") || "#0f1723") };
  }
  function level() {
    let v = "subtle";
    try { v = JSON.parse(localStorage.getItem("backdrop")) || v; } catch {}
    if (v === choice) return false;
    choice = v; lvl = v === "off" ? null : LEVELS[v] || LEVELS.subtle;
    cv.style.display = lvl ? "" : "none";
    return true;
  }

  // the portrait in theme colors: a light positive on dark (alpha follows brightness), a faint ink drawing on light paper
  // reads every pixel, so only on load and real color changes; fit() scales the result for each window size
  function tint() {
    if (!img.naturalWidth) return;
    const iw = img.naturalWidth, ih = img.naturalHeight;
    src = document.createElement("canvas"); src.width = iw; src.height = ih;
    const s = src.getContext("2d"); s.drawImage(img, 0, 0);
    const d = s.getImageData(0, 0, iw, ih), m = s.createImageData(iw, ih), p = d.data, q = m.data;
    const lo = col.dark ? [6, 34, 48] : col.ink, hi = col.dark ? mix(col.a, [236, 255, 250], .35) : mix(col.ink, col.a, .35);
    for (let i = 0; i < p.length; i += 4) {
      const L = p[i] / 255, A = p[i + 3] / 255, c = mix(lo, hi, col.dark ? L : 1 - L);
      p[i] = c[0]; p[i + 1] = c[1]; p[i + 2] = c[2];
      p[i + 3] = 255 * A * (col.dark ? .1 + .9 * L : .9 * (1 - L) + .04);
      q[i + 3] = 255 * A * (.35 + .65 * L);  // facial light shows most on her lit skin
    }
    s.putImageData(d, 0, 0);
    lum = document.createElement("canvas"); lum.width = iw; lum.height = ih;
    lum.getContext("2d").putImageData(m, 0, 0);
    fit();
  }
  function fit() {
    if (!src || !box.w) return;
    por = por || document.createElement("canvas");
    por.width = Math.round(box.w * dpr); por.height = Math.round(box.h * dpr);
    por.getContext("2d").drawImage(src, 0, 0, por.width, por.height);
    fx.width = Math.round(box.w * dpr * .6); fx.height = Math.round(box.h * dpr * .6);
  }

  function seed() {
    if (!lvl) return;
    const lean = W < 900 || (navigator.hardwareConcurrency || 8) <= 4 ? .6 : 1;
    const n = Math.round(Math.min(70, Math.max(18, W * Hh / 24000)) * lvl.nodes * lean);
    nodes = Array.from({ length: n }, () => ({ x: rnd(0, W), y: rnd(0, Hh), z: rnd(.35, 1), vx: rnd(-.006, .006), vy: rnd(-.006, .006) }));
    motes = Array.from({ length: Math.round(n * .9) }, () => ({ x: rnd(0, W), y: rnd(0, Hh), z: Math.random(), vx: rnd(-.002, .002), vy: -rnd(.003, .011), tw: rnd(0, 6.3) }));
    sparks = []; rays = []; scan = null;
    const now = performance.now();
    nextRay = now + 2500; nextScan = now + rnd(6000, 12000);
  }
  function size() {
    const w0 = W, h0 = Hh;
    dpr = Math.min(1.5, devicePixelRatio || 1);
    W = innerWidth; Hh = innerHeight;
    if (Math.abs(W - w0) > 160 || Math.abs(Hh - h0) > 160) seed();  // a new layout; small changes (phone toolbars) just stretch the scene
    else for (const o of [...nodes, ...motes]) { o.x *= W / w0; o.y *= Hh / h0; }
    cv.width = W * dpr; cv.height = Hh * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // tall and to the right of the sidebar on desktop; on phones centered, her face in the top third
    const wide = W > 900, h = Math.min(Hh * (wide ? 1.02 : .9), (wide ? W * .6 : W * 1.1) / .8), w = h * .8;
    box = { x: (wide ? W * .66 : W * .5) - w / 2, y: wide ? Hh - h : Hh * .3 - h * .33, w, h };
    fit(); draw(performance.now());
  }
  const reach = () => Math.min(170, Math.max(110, W / 10));
  const wrap = (o, m) => {
    if (o.x < -m) o.x = W + m; else if (o.x > W + m) o.x = -m;
    if (o.y < -m) o.y = Hh + m; else if (o.y > Hh + m) o.y = -m;
  };
  const shift = n => [n.x + par.x * 18 * n.z, n.y + par.y * 10 * n.z];

  function step(dt, t) {
    for (const n of nodes) { n.x += n.vx * dt; n.y += n.vy * dt; wrap(n, 40); }
    for (const m of motes) { m.x += m.vx * dt; m.y += m.vy * dt * (.4 + m.z); wrap(m, 10); }
    for (const s of sparks) s.p += dt / s.dur;
    sparks = sparks.filter(s => s.p < 1);
    if (t > nextSpark && links.length && sparks.length < 6 * lvl.sparks) {
      const [a, b, d] = links[Math.random() * links.length | 0], f = Math.random() < .5;
      sparks.push({ a: f ? a : b, b: f ? b : a, p: 0, dur: d / .07 });
      nextSpark = t + rnd(700, 2000) / lvl.sparks;
    }
    for (const r of rays) r.p += dt / r.dur;
    rays = rays.filter(r => r.p < 1);
    if (t > nextRay) {
      const n = Math.random() < .35 ? 2 : 1;  // sometimes two contours light up together
      for (let i = 0; i < n; i++) rays.push({ path: PATHS[Math.random() * PATHS.length | 0], p: 0, dur: rnd(2200, 3400) });
      nextRay = t + rnd(...lvl.face);
    }
    if (scan && (scan.p += dt / scan.dur) > 1) scan = null;
    if (!scan && t > nextScan) { scan = { p: 0, dur: 4200 }; nextScan = t + rnd(20000, 36000); }
    par.x += (par.tx - par.x) * .04; par.y += (par.ty - par.y) * .04;
    ptr.x += (ptr.tx - ptr.x) * .08; ptr.y += (ptr.ty - ptr.y) * .08;
  }

  // energy waves: three slow sine ribbons, a thin line inside a wide soft band
  function waves(t) {
    const k = t * .00024, al = (col.dark ? .075 : .05) * lvl.waves;
    for (let i = 0; i < 3; i++) {
      const base = Hh * (.3 + i * .23), amp = 24 + i * 14, f = (1.3 + i * .45) * Math.PI * 2 / W;
      ctx.beginPath();
      for (let x = -24, dx = Math.max(6, W / 64); x <= W + 24; x += dx) {
        const y = base + Math.sin(x * f + k * (1 + i * .5) + i * 2) * amp + Math.sin(x * f * .5 - k * .7 + i) * amp * .5;
        x < 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      for (const [lw, a] of [[28, al * .14], [1.2, al]]) {
        const g = ctx.createLinearGradient(0, 0, W, 0);
        g.addColorStop(0, css(col.a, 0)); g.addColorStop(.3, css(col.a, a)); g.addColorStop(.72, css(col.c, a * .85)); g.addColorStop(1, css(col.c, 0));
        ctx.strokeStyle = g; ctx.lineWidth = lw; ctx.stroke();
      }
    }
  }

  // the neural network: links fade with distance and step back around her face; light runs along them
  function net() {
    const R = reach(), P = nodes.map(shift), fx0 = box.x + box.w * .5, fy0 = box.y + box.h * .33, fr = box.w * .26;
    const dim = col.dark ? 1 : .6, near = (x, y) => ptr.on ? Math.max(0, 1 - Math.hypot(x - ptr.x, y - ptr.y) / 180) : 0;
    links = [];
    ctx.lineWidth = 1;
    for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
      const dx = P[i][0] - P[j][0], dy = P[i][1] - P[j][1], d2 = dx * dx + dy * dy;
      if (d2 > R * R) continue;
      const d = Math.sqrt(d2), mx = (P[i][0] + P[j][0]) / 2, my = (P[i][1] + P[j][1]) / 2, q = Math.hypot(mx - fx0, my - fy0) / fr;
      links.push([i, j, d]);
      const a = (1 - d / R) * .25 * Math.min(nodes[i].z, nodes[j].z) * (q < 1 ? .25 + .75 * q * q : 1) * (1 + near(mx, my)) * dim;
      ctx.strokeStyle = css(col.a, a);
      ctx.beginPath(); ctx.moveTo(P[i][0], P[i][1]); ctx.lineTo(P[j][0], P[j][1]); ctx.stroke();
    }
    for (let i = 0; i < P.length; i++) {
      const z = nodes[i].z;
      ctx.fillStyle = css(col.a, (.18 + .3 * z) * (1 + near(P[i][0], P[i][1])) * dim);
      ctx.beginPath(); ctx.arc(P[i][0], P[i][1], .7 + 1.3 * z, 0, 7); ctx.fill();
    }
    for (const s of sparks) {
      const A = P[s.a], B = P[s.b];
      if (!A || !B) continue;
      const x = A[0] + (B[0] - A[0]) * s.p, y = A[1] + (B[1] - A[1]) * s.p, fade = Math.sin(Math.PI * s.p);
      const g = ctx.createRadialGradient(x, y, 0, x, y, 8);
      g.addColorStop(0, css(mix(col.c, [255, 255, 255], col.dark ? .3 : 0), .75 * fade * dim)); g.addColorStop(1, css(col.c, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 8, 0, 7); ctx.fill();
    }
  }

  function portrait(t) {
    if (!por) return;
    const breathe = .93 + Math.sin(t * .0004) * .07;
    ctx.globalAlpha = (col.dark ? lvl.portrait : lvl.paper) * breathe;
    ctx.drawImage(por, box.x + par.x * 10, box.y + par.y * 6, box.w, box.h);
    ctx.globalAlpha = 1;
  }

  // light pulses along her contours, and the scan, drawn on a side canvas then cut to the portrait's lit areas
  function face() {
    if (!por || (!rays.length && !scan)) return;
    const k = fx.width / box.w;
    fctx.setTransform(1, 0, 0, 1, 0, 0);
    fctx.globalCompositeOperation = "source-over";
    fctx.clearRect(0, 0, fx.width, fx.height);
    fctx.setTransform(k, 0, 0, k, 0, 0);
    const hot = mix(col.a, [255, 255, 255], col.dark ? .45 : 0);
    for (const r of rays) {
      const pts = r.path.map(([u, v]) => [u * box.w, v * box.h]), cum = [0];
      for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
      const len = cum[cum.length - 1], tail = Math.max(40, len * .35), e = r.p * r.p * (3 - 2 * r.p), head = e * (len + tail);
      const at = s => {
        s = Math.max(0, Math.min(len, s));
        let i = 1; while (i < cum.length - 1 && cum[i] < s) i++;
        const f = (s - cum[i - 1]) / (cum[i] - cum[i - 1] || 1);
        return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f];
      };
      // the whole contour glows faintly while the pulse is on it
      fctx.strokeStyle = css(col.c, .22 * Math.sin(Math.PI * r.p)); fctx.lineWidth = 1.4;
      fctx.beginPath(); pts.forEach(([x, y], i) => i ? fctx.lineTo(x, y) : fctx.moveTo(x, y)); fctx.stroke();
      for (let s = head - tail; s <= head; s += 3) {
        if (s < 0 || s > len) continue;
        const [x, y] = at(s), a = ((s - head + tail) / tail) ** 2;
        fctx.fillStyle = css(hot, .8 * a); fctx.beginPath(); fctx.arc(x, y, 1 + 1.6 * a, 0, 7); fctx.fill();
      }
      if (head <= len) {
        const [x, y] = at(head), g = fctx.createRadialGradient(x, y, 0, x, y, 16);
        g.addColorStop(0, css(hot, .9)); g.addColorStop(.4, css(col.a, .35)); g.addColorStop(1, css(col.a, 0));
        fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, 16, 0, 7); fctx.fill();
      }
    }
    if (scan) {
      const y = scan.p * box.h, fade = Math.sin(Math.PI * scan.p), g = fctx.createLinearGradient(0, y - 46, 0, y + 6);
      g.addColorStop(0, css(col.c, 0)); g.addColorStop(.85, css(col.c, .22 * fade)); g.addColorStop(1, css(col.c, 0));
      fctx.fillStyle = g; fctx.fillRect(0, y - 46, box.w, 52);
      fctx.fillStyle = css(mix(col.c, [255, 255, 255], .4), .5 * fade); fctx.fillRect(0, y, box.w, 1);
    }
    fctx.setTransform(1, 0, 0, 1, 0, 0);
    fctx.globalCompositeOperation = "destination-in";
    fctx.drawImage(lum, 0, 0, fx.width, fx.height);
    ctx.globalCompositeOperation = col.dark ? "lighter" : "source-over";
    ctx.globalAlpha = col.dark ? .9 : .55;
    ctx.drawImage(fx, box.x + par.x * 10, box.y + par.y * 6, box.w, box.h);
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 1;
  }

  function dust(t) {
    const c = col.dark ? mix(col.c, [255, 255, 255], .45) : col.a;
    for (const m of motes) {
      const a = (.1 + .3 * m.z) * (.6 + .4 * Math.sin(t * .001 + m.tw)) * (col.dark ? 1 : .55);
      ctx.fillStyle = css(c, a);
      ctx.beginPath(); ctx.arc(m.x + par.x * 26 * m.z, m.y + par.y * 14 * m.z, .4 + 1.2 * m.z, 0, 7); ctx.fill();
    }
  }

  function glow() {
    if (!ptr.on) return;
    const g = ctx.createRadialGradient(ptr.x, ptr.y, 0, ptr.x, ptr.y, 300);
    g.addColorStop(0, css(col.a, col.dark ? .07 : .045)); g.addColorStop(.5, css(col.c, col.dark ? .025 : .015)); g.addColorStop(1, css(col.c, 0));
    ctx.fillStyle = g; ctx.fillRect(ptr.x - 300, ptr.y - 300, 600, 600);
  }

  function draw(t) {
    ctx.clearRect(0, 0, W, Hh);
    if (!lvl) return;
    waves(still.matches ? 0 : t);
    net();
    portrait(still.matches ? 0 : t);
    face();
    dust(still.matches ? 0 : t);
    glow();
  }

  function loop(t) {
    requestAnimationFrame(loop);
    if (!lvl || still.matches || t - last < 33) return;  // ~30 fps is plenty for a slow backdrop
    const dt = Math.min(100, t - last);  // no jump after the tab was hidden
    last = t; step(dt, t); draw(t);
  }

  colors(); level(); size();
  img.onload = () => { tint(); draw(performance.now()); };
  let sizing; addEventListener("resize", () => { clearTimeout(sizing); sizing = setTimeout(size, 120); });
  addEventListener("pointermove", e => {
    ptr.tx = e.clientX; ptr.ty = e.clientY;
    if (!ptr.on) { ptr.x = ptr.tx; ptr.y = ptr.ty; ptr.on = true; }
    par.tx = (e.clientX / W - .5) * 2; par.ty = (e.clientY / Hh - .5) * 2;
  }, { passive: true });
  document.documentElement.addEventListener("mouseleave", () => { ptr.on = false; });
  addEventListener("pointerup", e => { if (e.pointerType === "touch") ptr.on = false; }, { passive: true });  // no glow parked where a finger lifted
  const recolor = () => {
    const was = JSON.stringify(col); colors();
    if (JSON.stringify(col) !== was) { tint(); draw(performance.now()); }  // re-tinting reads every pixel: only on a real change
  };
  const relevel = () => { if (level()) { seed(); draw(performance.now()); } };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", recolor);
  new MutationObserver(recolor).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style", "class"] });
  document.addEventListener("themechange", relevel);
  addEventListener("storage", e => { if (e.key === "backdrop") relevel(); });
  still.addEventListener("change", () => draw(performance.now()));
  requestAnimationFrame(loop);
})();
