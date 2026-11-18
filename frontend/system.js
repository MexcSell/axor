/* System: this server's CPU, memory, swap, disk and load, for admins, in four places: a meter in the app bar (details
   on click), a status bar along the bottom (turned off and on from that menu), a strip on the Dashboard, and the
   System page with charts of the last hour and the busiest containers. One poll every 5 s feeds them all and pauses
   while the tab is hidden. Totals cover the whole machine; "AXoR" is its own container. */
const System = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const pref = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem("sys." + k)); localStorage.setItem("sys." + k, JSON.stringify(v)); } catch { return null; } };
  const KEEP = 720, RANGES = [[300, "5 min"], [900, "15 min"], [3600, "1 hour"]];
  let d = null, hist = [], timer = null, inflight = false, failed = 0, wired = false, dkTimer = null;
  let range = RANGES.some(([s]) => s === pref("range")) ? pref("range") : 900;

  const bytes = n => !n ? "0 B" : n < 2 ** 30 ? `${fmtNum(n / 2 ** 20, 0)} MB` : n < 2 ** 40 ? `${fmtNum(n / 2 ** 30, 1)} GB` : `${fmtNum(n / 2 ** 40, 2)} TB`;
  const frac = (a, t) => { const k = t < 2 ** 40 ? 2 ** 30 : 2 ** 40; return `${fmtNum(a / k, k > 2 ** 30 || a < k ? 2 : 1)} / ${fmtNum(t / k, k > 2 ** 30 ? 2 : 1)} ${k > 2 ** 30 ? "TB" : "GB"}`; };  // one unit: 43.7 / 125.7 GB
  const per = x => `${fmtNum(x, x > 0 && x < 10 ? 1 : 0)}%`;
  const level = (p, warn = 75, crit = 90) => p >= crit ? "lv-crit" : p >= warn ? "lv-warn" : "lv-ok";  // not .ok: that's a global style
  const span = s => { const dd = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return dd ? `${dd}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; };
  const mini = (vs, w = 46, h = 14) => vs.length < 2 ? "" : `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${vs.map((v, i) => `${i ? "L" : "M"}${(i / (vs.length - 1) * w).toFixed(1)},${(h - 1 - Math.min(100, v) / 100 * (h - 2)).toFixed(1)}`).join("")}"/></svg>`;  // 0–100%
  const bar = (p, lvl) => `<span class="sys-bar ${lvl}"><i style="width:${Math.max(0, Math.min(100, p)).toFixed(1)}%"></i></span>`;
  const admin = () => Auth.me()?.role === "admin";

  // the latest sample, as percentages where that's what the views show
  function cur() {
    const s = hist.at(-1); if (!d || !s) return null;
    return { s, cpu: s.cpu, mem: s.mem / d.mem_total * 100, swap: d.swap_total ? s.swap / d.swap_total * 100 : 0,
             disk: d.disk.used / (d.disk.used + d.disk.free) * 100, load: d.load[0] / d.cpus * 100 };  // disk as `df`
  }

  function init() {
    if (!admin()) return;
    wire();
    $("#sys-chip").hidden = false;
    show(pref("bar") !== false);
    poll(); clearInterval(timer); timer = setInterval(poll, 5000);
  }
  async function poll() {
    if (inflight || document.hidden) return;
    inflight = true;
    try {
      const r = await api(`/api/system?since=${hist.at(-1)?.t || 0}`);
      hist = hist.concat(r.history).slice(-KEEP); delete r.history; d = r; failed = 0;
    } catch (e) {
      failed++;
      if (e.status === 401 || e.status === 403) { clearInterval(timer); $("#sys-chip").hidden = true; show(false, true); return; }
    } finally { inflight = false; }
    paint();
  }

  function paint() {
    const x = cur(); if (!x) return;
    chip(x);
    if (!$("#sb-sys").hidden) statusbar(x);
    const pop = $(".sys-pop"); if (pop) pop.innerHTML = details(x);
    $$(".dash-sys").forEach(ds => ds.innerHTML = stripHtml(x));  // the Dashboard's and the Command Center's
    if (S.view === "system") page(x);
  }

  // ---------- app bar: two small meters, the details on click ----------
  function chip(x) {
    const b = $("#sys-chip"), worst = Math.max(x.cpu, x.mem, x.disk);
    b.className = "sys-chip " + (worst >= 90 ? "lv-crit" : worst >= 75 ? "lv-warn" : "");
    b.innerHTML = [["CPU", x.cpu], ["MEM", x.mem]].map(([l, v]) =>
      `<span class="sys-m ${level(v)}"><span class="sys-l">${l} <b class="num">${per(v)}</b></span>${bar(v, level(v))}</span>`).join("");
    b.title = `Server: CPU ${per(x.cpu)} · memory ${per(x.mem)} · disk ${per(x.disk)}`;
  }
  const row = (ic, label, val, sub, p, lvl) => `<div class="sys-row"><span class="sys-k">${icon(ic)}${label}</span>${p == null ? "<span></span>" : bar(p, lvl)}<b class="num">${val}</b>${sub ? `<small class="faint">${sub}</small>` : ""}</div>`;
  function details(x) {
    const s = x.s;
    return `<div class="sys-pop-h"><b>Server</b><small class="faint">${d.cpus} cores · up ${span(d.uptime)} · ${failed > 1 ? "not updating" : "live"}</small></div>
      ${row("chip", "CPU", per(x.cpu), `${fmtNum(x.cpu / 100 * d.cpus, 1)} of ${d.cpus} cores busy`, x.cpu, level(x.cpu))}
      ${row("zap", "Load", d.load.map(v => fmtNum(v, 2)).join(" · "), `1 · 5 · 15 min, ${fmtNum(d.load[0] / d.cpus, 2)} per core`, x.load, level(x.load, 80, 100))}
      ${row("chips", "Memory", frac(s.mem, d.mem_total), `${bytes(d.mem_total - s.mem)} available`, x.mem, level(x.mem))}
      ${d.swap_total ? row("layers", "Swap", frac(s.swap, d.swap_total), x.swap >= 90 && x.mem < 75 ? "full, but memory has room" : "", x.swap, level(x.swap, 90, 101)) : ""}
      ${row("server", "Disk", frac(d.disk.used, d.disk.total), `${bytes(d.disk.free)} free where AXoR keeps its data`, x.disk, level(x.disk, 80, 92))}
      ${row("bot", "AXoR", bytes(s.app_mem), `CPU ${per(s.app_cpu)} of one core`)}
      <div class="sys-pop-foot"><label class="chk"><input type="checkbox" data-sys-bar ${$("#sb-sys").hidden ? "" : "checked"}> Server in the status bar</label>
        <button type="button" class="btn sm" data-sys-open>${icon("chart")}System page</button></div>`;
  }
  function popover() {
    const x = cur(); if (!x) return toast("Reading server resources…");
    const pop = document.createElement("div"); pop.className = "popover sys-pop"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Server resources");
    pop.innerHTML = details(x);
    const r = $("#sys-chip").getBoundingClientRect();
    pop.style.top = r.bottom + 8 + "px"; pop.style.left = Math.max(12, Math.min(r.right - 340, innerWidth - 352)) + "px";
    document.body.appendChild(pop);
    $("#sys-chip").setAttribute("aria-expanded", "true");
  }
  const closePop = () => { $(".sys-pop")?.remove(); $("#sys-chip").setAttribute("aria-expanded", "false"); };

  // ---------- status bar ----------
  function show(on, quiet) {
    if (!quiet) pref("bar", on);
    $("#sb-sys").hidden = !on;  // the server's part of the status bar; the bar itself is the shell's (shell.js)
    const cb = $("[data-sys-bar]"); if (cb) cb.checked = on;
    if (on && cur()) statusbar(cur());
  }
  function statusbar(x) {
    const s = x.s, stale = failed > 1 || Date.now() / 1000 - s.t > 30;
    const it = (label, val, lvl, tip, extra = "") => `<button type="button" class="sb-it ${lvl}" data-sys-open title="${tip}"><span>${label}</span><b class="num">${val}</b>${extra}</button>`;
    $("#sb-sys").innerHTML = `<span class="sb-live ${stale ? "stale" : ""}" title="${stale ? "Not updating: AXoR can't be reached" : "Server resources, every 5 seconds"}"><i></i>Server</span>
      ${it("CPU", per(x.cpu), level(x.cpu), `CPU: ${fmtNum(x.cpu / 100 * d.cpus, 1)} of ${d.cpus} cores busy`, mini(hist.slice(-36).map(h => h.cpu)))}
      ${it("Load", d.load.map(v => fmtNum(v, 1)).join(" "), level(x.load, 80, 100) + " minor", "Load average over 1, 5 and 15 minutes")}
      ${it("Mem", frac(s.mem, d.mem_total), level(x.mem), `Memory: ${per(x.mem)} used`)}
      ${d.swap_total ? it("Swap", frac(s.swap, d.swap_total), level(x.swap, 90, 101) + " minor", `Swap: ${per(x.swap)} used`) : ""}
      ${it("Disk", frac(d.disk.used, d.disk.total), level(x.disk, 80, 92), `Disk: ${bytes(d.disk.free)} free`)}
      ${it("AXoR", `${bytes(s.app_mem)} · ${per(s.app_cpu)}`, "minor", "AXoR's own container: memory and CPU (of one core)")}
      <span class="sb-sp"></span>
      <span class="sb-it faint minor" title="Kernel ${esc(d.kernel)}">up ${span(d.uptime)}</span>
      <button type="button" class="sb-x" data-sys-bar-off title="Hide the status bar" aria-label="Hide the status bar">${icon("close")}</button>`;
  }

  // ---------- Dashboard strip ----------
  function stripHtml(x) {
    const m = (label, p, val, lvl) => `<div class="dash-sys-m"><span class="faint">${label}</span>${bar(p, lvl)}<b class="num">${val}</b></div>`;
    return `<div class="dash-sys-h">${icon("chip")}<b>Server</b><small class="faint">${d.cpus} cores · up ${span(d.uptime)}</small></div>
      ${m("CPU", x.cpu, per(x.cpu), level(x.cpu))}
      ${m("Memory", x.mem, frac(x.s.mem, d.mem_total), level(x.mem))}
      ${m("Disk", x.disk, frac(d.disk.used, d.disk.total), level(x.disk, 80, 92))}
      ${m("Load", x.load, d.load.map(v => fmtNum(v, 1)).join(" · "), level(x.load, 80, 100))}
      <span class="linkbtn">System page</span>`;
  }
  const strip = () => !admin() ? "" : `<div class="card dash-sys" id="dash-sys" data-sys-open role="button" tabindex="0" title="Open the System page">${cur() ? stripHtml(cur()) : Loading.line("Reading server resources…")}</div>`;

  // ---------- System page ----------
  const CHARTS = [
    { k: "cpu", title: "CPU", v: s => s.cpu, top: () => 100, fmt: per },
    { k: "mem", title: "Memory used", v: s => s.mem, top: () => d.mem_total, fmt: bytes },
    { k: "load", title: "Load (1 min)", v: s => s.load, top: vs => Math.max(1, ...vs) * 1.25, fmt: v => fmtNum(v, 2) },
    { k: "app", title: "AXoR memory", v: s => s.app_mem, top: vs => Math.max(2 ** 20, ...vs) * 1.25, fmt: bytes },
  ];
  function open() {
    wire();
    const root = $("#sys");
    if (!root.dataset.built) {
      root.dataset.built = "1";
      root.innerHTML = `<div class="dash-top"><div><h1 class="page">System</h1><p class="lead" id="sys-lead">This server's CPU, memory, swap, disk and load, sampled every 5 seconds. Totals cover everything on the machine, in Docker or not; AXoR is its own container.</p></div>
          <div class="seg" id="sys-range" role="group" aria-label="Time range">${RANGES.map(([s, l]) => `<button type="button" data-range="${s}" aria-pressed="${s === range}">${l}</button>`).join("")}</div></div>
        <div class="stats sys-tiles" id="sys-tiles">${Loading.tiles(6)}</div>
        <div class="sys-charts">${CHARTS.map(c => `<div class="card chart sys-chart" data-c="${c.k}"><div class="title"><span>${c.title}</span><span class="num" data-v></span></div><svg></svg><div class="tip" hidden></div></div>`).join("")}</div>
        <h2 class="section-title">${icon("server")}Busiest containers</h2>
        <div class="card" id="sys-dk">${Loading.line("Reading container stats…")}</div>`;
      root.querySelectorAll(".sys-chart").forEach(hover);
    }
    paint(); containers();
    clearInterval(dkTimer); dkTimer = setInterval(() => { if (S.view !== "system") return clearInterval(dkTimer); if (!document.hidden) containers(); }, 15000);
  }
  function page(x) {
    const s = x.s, t0 = Date.now() / 1000 - range, inRange = hist.filter(h => h.t >= t0), peak = k => Math.max(...inRange.map(h => h[k]));
    const tile = (ic, l, v, sub, lvl, extra = "") => `<div class="stat sys-tile ${lvl}"><div class="label">${icon(ic)}${l}</div><div class="value num">${v}</div><div class="sub">${sub}</div>${extra}</div>`;
    $("#sys-tiles").innerHTML = [
      tile("chip", "CPU", per(x.cpu), `${d.cpus} cores · peak ${per(peak("cpu"))}`, level(x.cpu), bar(x.cpu, level(x.cpu))),
      tile("zap", "Load", fmtNum(d.load[0], 2), `5m ${fmtNum(d.load[1], 2)} · 15m ${fmtNum(d.load[2], 2)}`, level(x.load, 80, 100), bar(x.load, level(x.load, 80, 100))),
      tile("chips", "Memory", per(x.mem), `${bytes(s.mem)} of ${bytes(d.mem_total)}`, level(x.mem), bar(x.mem, level(x.mem))),
      tile("layers", "Swap", d.swap_total ? per(x.swap) : "off", d.swap_total ? `${bytes(s.swap)} of ${bytes(d.swap_total)}` : "no swap space", level(x.swap, 90, 101), d.swap_total ? bar(x.swap, level(x.swap, 90, 101)) : ""),
      tile("server", "Disk", per(x.disk), `${bytes(d.disk.free)} free of ${bytes(d.disk.total)}`, level(x.disk, 80, 92), bar(x.disk, level(x.disk, 80, 92))),
      tile("bot", "AXoR", bytes(s.app_mem), `CPU ${per(s.app_cpu)} of one core`, ""),
    ].join("");
    $("#sys-lead").textContent = `This server's CPU, memory, swap, disk and load, sampled every 5 seconds. Up ${span(d.uptime)}, kernel ${d.kernel}. Totals cover everything on the machine, in Docker or not; AXoR is its own container.`;
    $$("#sys .sys-chart").forEach(el => draw(el, CHARTS.find(c => c.k === el.dataset.c)));
  }
  function draw(el, c) {
    const svg = $("svg", el), t1 = Date.now() / 1000, t0 = t1 - range;
    const pts = hist.filter(h => h.t >= t0).map(h => [h.t, c.v(h)]);
    const W = svg.clientWidth || 600, H = 150, L = 58, R = 10, T = 8, B = 20, top = c.top(pts.map(p => p[1])) || 1;
    const X = t => L + (t - t0) / range * (W - L - R), Y = v => T + (1 - Math.min(v, top) / top) * (H - T - B);
    Object.assign(el, { _pts: pts, _X: X, _Y: Y, _W: W, _H: H, _fmt: c.fmt });
    $("[data-v]", el).textContent = pts.length ? c.fmt(pts.at(-1)[1]) : "";
    const mins = range / 60, every = mins <= 5 ? 1 : mins <= 15 ? 3 : 10, xt = [];
    for (let t = Math.ceil(t0 / (every * 60)) * every * 60; t <= t1; t += every * 60) xt.push(t);
    const line = pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join("");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = [0, top / 2, top].map(v => `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L - 6}" y="${Y(v) + 3}" text-anchor="end">${esc(c.fmt(v))}</text>`).join("")
      + xt.map(t => `<text class="axis" x="${X(t)}" y="${H - 4}" text-anchor="middle">${clock(t)}</text>`).join("")
      + (pts.length > 1 ? `<path class="area" d="${line}L${X(pts.at(-1)[0])},${H - B}L${X(pts[0][0])},${H - B}Z"/><path class="line" d="${line}"/>`
        : `<text class="axis" x="${(L + W - R) / 2}" y="${H / 2}" text-anchor="middle">Collecting samples: a point every 5 seconds…</text>`)
      + `<line class="cross" y1="${T}" y2="${H - B}" visibility="hidden"/><circle class="pt" r="4" visibility="hidden"/>`;
  }
  function hover(el) {
    const svg = $("svg", el), tip = $(".tip", el);
    svg.addEventListener("mousemove", e => {
      const pts = el._pts; if (!pts?.length) return;
      const bx = svg.getBoundingClientRect(), mx = (e.clientX - bx.left) * (el._W / bx.width);
      let best = pts[0]; for (const p of pts) if (Math.abs(el._X(p[0]) - mx) < Math.abs(el._X(best[0]) - mx)) best = p;
      const cx = el._X(best[0]), cy = el._Y(best[1]), cross = $(".cross", svg), dot = $(".pt", svg);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("visibility", "visible");
      tip.hidden = false; tip.style.left = (cx / el._W * bx.width + svg.offsetLeft) + "px"; tip.style.top = (cy / el._H * bx.height + svg.offsetTop) + "px";
      tip.innerHTML = `${new Date(best[0] * 1000).toLocaleTimeString()} · <b>${esc(el._fmt(best[1]))}</b>`;
    });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; $(".cross", svg)?.setAttribute("visibility", "hidden"); $(".pt", svg)?.setAttribute("visibility", "hidden"); });
  }
  async function containers() {
    const el = $("#sys-dk"); if (!el) return;
    let o, st;
    try { [o, st] = await Promise.all([api("/api/docker"), api("/api/docker/stats")]); }
    catch (e) { el.innerHTML = `<p class="faint">${esc(e.message)}</p>`; if (e.status === 503) clearInterval(dkTimer); return; }  // 503: no Docker proxy here
    const rows = o.containers.filter(c => st[c.id]).map(c => ({ ...c, ...st[c.id] })).sort((a, b) => b.cpu - a.cpu || b.mem - a.mem).slice(0, 8);
    const cores = (d?.cpus || o.engine.cpus || 1) * 100, total = d?.mem_total || o.engine.memory || 1;
    el.innerHTML = !rows.length ? `<p class="faint">No running containers.</p>` : `<div class="tablewrap flat"><table class="grid mini-table sys-dk">
      <thead><tr><th>Container</th><th class="r">CPU</th><th></th><th class="r">Memory</th><th></th></tr></thead><tbody>${rows.map(c => `<tr>
        <td><b>${esc(c.name)}</b>${c.self ? ' <span class="badge new">AXoR</span>' : ""}<small class="faint">${esc(c.image)}</small></td>
        <td class="r num">${per(c.cpu)}</td><td>${bar(c.cpu / cores * 100, "lv-ok")}</td>
        <td class="r num">${bytes(c.mem)}</td><td>${bar(c.mem / total * 100, "lv-ok")}</td></tr>`).join("")}</tbody></table></div>
      <p class="faint small">CPU is per core, as <code>docker stats</code> shows it (100% = one core of ${cores / 100}); the bars are shares of the whole machine. Processes outside Docker count in the totals above but aren't listed. <button type="button" class="linkbtn" data-goto-docker>Docker page</button></p>`;
  }

  function wire() {
    if (wired) return; wired = true;
    document.addEventListener("click", e => {
      const t = e.target;
      if (t.closest("#sys-chip")) { e.stopPropagation(); return $(".sys-pop") ? closePop() : popover(); }
      if (t.closest("[data-sys-open]")) { closePop(); return setView("system"); }
      if (t.closest("[data-sys-bar-off]")) { show(false); return toast("Server meters hidden. Turn them back on from the CPU and MEM meter at the top."); }
      if (t.closest("[data-goto-docker]")) return setView("docker");
      const r = t.closest("#sys-range [data-range]");
      if (r) { range = +r.dataset.range; pref("range", range); $$("#sys-range button").forEach(b => b.setAttribute("aria-pressed", b === r)); return paint(); }
      if ($(".sys-pop") && !t.closest(".sys-pop")) closePop();
    });
    document.addEventListener("change", e => { if (e.target.matches("[data-sys-bar]")) show(e.target.checked); });
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && $(".sys-pop")) { closePop(); $("#sys-chip").focus(); }
      if ((e.key === "Enter" || e.key === " ") && e.target.classList?.contains("dash-sys")) { e.preventDefault(); setView("system"); }
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
    addEventListener("resize", () => { closePop(); if (S.view === "system") paint(); });
  }

  return { init, open, strip };
})();
