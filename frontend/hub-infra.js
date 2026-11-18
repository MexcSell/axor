/* AXoR 2.0 Platform overview (hubs.js page "infra", administrators): the developer platform and the infrastructure at a glance,
   from each page's own API. A service that isn't set up (/api/platform-status) isn't called, so a missing DOCKER_URL or Runner
   reads "Not set up" instead of an error; one that fails says so on its own card. Each card opens its page. */
(() => {
  const SVC = { ok: "Up", warn: "Needs a look", down: "Down", pending: "Starting", off: "Not set up" };
  const pctv = x => x == null ? "–" : `${fmtNum(x, 0)}%`;
  const gb = b => b == null ? "–" : `${fmtNum(b / 2 ** 30, 1)} GB`;

  Hubs.register("infra", {
    title: "Platform overview", kicker: "Platform", icon: "server",
    lead: "AXoR's developer platform and infrastructure on one page: services, the server, the cluster, pipelines, apps and functions, machines, DNS and connectors. Each card opens its page.",
    load: async (fresh, get) => {
      const st = await get("/api/platform-status", fresh);
      const on = k => st.services.find(s => s.key === k)?.state === "ok";
      const calls = { system: "/api/system", connectors: "/api/connectors" };
      if (on("kubernetes")) Object.assign(calls, { cluster: "/api/cluster", apps: "/api/platform/apps", functions: "/api/platform/functions", machines: "/api/machines" });
      if (on("runner")) calls.devops = "/api/devops";
      if (on("dns")) calls.dns = "/api/dns";
      const keys = Object.keys(calls), res = await Promise.allSettled(keys.map(k => get(calls[k], fresh)));
      const out = { at: Date.now() / 1000, st, ok: {}, err: {} };
      keys.forEach((k, i) => res[i].status === "fulfilled" ? out.ok[k] = res[i].value : out.err[k] = res[i].reason?.message || "Couldn't read it");
      return out;
    },
    body(d, h) {
      const svc = d.st.services, up = svc.filter(s => s.state === "ok").length, O = d.ok, E = d.err;
      const sys = O.system, last = sys?.history?.at(-1);
      const mem = last && sys.mem_total ? last.mem / sys.mem_total * 100 : null, disk = sys?.disk ? sys.disk.used / (sys.disk.used + sys.disk.free) * 100 : null;
      const cl = O.cluster, deps = cl ? cl.namespaces.flatMap(n => n.deployments || []) : [], depOk = deps.filter(x => x.ready >= x.replicas).length;
      const nodes = cl?.nodes || [], warn = (cl?.events || []).length;
      const apps = O.apps?.items || [], fns = O.functions?.items || [], vms = O.machines?.items || [];
      const pipes = O.devops?.pipelines || [], week = O.devops?.week || {};
      const zones = O.dns?.zones || [], conns = O.connectors?.connectors || [];
      const off = (k, page) => E[k] ? h.empty(`${icon("alert")}${esc(E[k])}`) : h.empty(`Not set up on this server. <button type="button" class="linkbtn" data-axh-to="${page}">Open ${esc(page)}</button>`);
      const running = xs => xs.filter(x => /run|ready|ok|active/i.test(x.status || "")).length;
      return `<div class="stats occ-kpis">${h.kpi("server", "Services", `${up}/${svc.length}`, up === svc.length ? "all set up" : `${svc.length - up} not set up`, up < svc.length ? "warn" : "ok")}
          ${h.kpi("chip", "CPU", pctv(last?.cpu), sys ? `${sys.cpus} cores · load ${sys.load?.[0] ?? "–"}` : "", last?.cpu > 85 ? "crit" : "", "system")}
          ${h.kpi("chip", "Memory", pctv(mem), sys ? `${gb(last?.mem)} of ${gb(sys.mem_total)}` : "", mem > 90 ? "crit" : mem > 75 ? "warn" : "", "system")}
          ${h.kpi("chip", "Disk", pctv(disk), sys?.disk ? `${gb(sys.disk.free)} free` : "", disk > 90 ? "crit" : disk > 80 ? "warn" : "", "system")}
          ${h.kpi("layers", "Deployments ready", cl ? `${depOk}/${deps.length}` : "–", cl ? `${nodes.length} node${nodes.length === 1 ? "" : "s"} · ${cl.pods_total} pods` : "not on Kubernetes", cl && depOk < deps.length ? "warn" : "", "cluster")}
          ${h.kpi("rocket", "Pipeline runs (7 d)", (week.success || 0) + (week.failed || 0), O.devops ? `${week.success || 0} ok · ${week.failed || 0} failed` : "no Runner", week.failed ? "warn" : "", "devops")}</div>
        <div class="occ-grid">
          ${h.card("axh-span12", "server", "Services", "", `<div class="occ-svcs">${svc.map(s => `<button type="button" class="occ-svc s-${s.state}" data-axh-to="${s.view}" title="${esc(SVC[s.state] || s.state)}: ${esc(s.detail)}"><span class="plt-dot"></span><span><b>${esc(s.label)}</b><small>${esc(s.detail)}</small></span></button>`).join("")}</div>`)}
          ${h.card("", "chip", "Server", `<button type="button" class="linkbtn" data-axh-to="system">System</button>`, sys ? `
            <ul class="occ-by">${[["CPU", last?.cpu, pctv(last?.cpu)], ["Memory", mem, pctv(mem)], ["Disk", disk, pctv(disk)], ["Load", sys.load?.[0] / sys.cpus * 100, `${sys.load?.[0] ?? "–"}`]]
              .map(([l, v, t]) => `<li><span>${l}</span>${h.meter((v || 0) / 100, t, v > 90 ? "over" : "")}<b class="num">${esc(t)}</b></li>`).join("")}</ul>
            ${sys.history?.length > 2 ? `<h4 class="occ-h4">CPU, last hour</h4><div class="trend wide">${spark(sys.history.map(x => x.cpu), 300, 40)}</div>` : ""}
            <p class="faint small">Kernel ${esc(sys.kernel || "")} · up ${fmtNum((sys.uptime || 0) / 3600, 0)} h</p>` : off("system", "system"))}
          ${h.card("", "layers", "Cluster", `<button type="button" class="linkbtn" data-axh-to="cluster">Cluster</button>`, cl ? `
            <ul class="occ-list">${nodes.map(n => `<li class="occ-need"><span class="plt-dot ${n.ready ? "s-ok" : "s-down"}"></span><span class="occ-need-t"><b>${esc(n.name)}</b><small>${n.ready ? "Ready" : "Not ready"}${(n.pressure || []).length ? ` · pressure: ${esc(n.pressure.join(", "))}` : ""}</small></span></li>`).join("")}</ul>
            ${h.bars(cl.namespaces.map(n => ({ label: n.title || n.name, value: (n.deployments || []).length, title: `${n.name}: ${(n.deployments || []).length} deployments, ${(n.pods || []).length} pods` })), x => String(x))}
            ${warn ? `<p class="small axh-warn">${icon("alert")}${warn} recent warning event${warn === 1 ? "" : "s"}</p>` : ""}` : off("cluster", "cluster"))}
          ${h.card("", "rocket", "Pipelines", `<button type="button" class="linkbtn" data-axh-to="devops">DevOps</button>`, O.devops ? (pipes.length ? `<ul class="occ-list">${pipes.slice(0, 8).map(p => `<li><button type="button" class="occ-row" data-axh-to="devops"><span class="occ-need-t"><b>${esc(p.app)}</b><small>${esc(p.repo || "")}${p.branch ? `@${esc(p.branch)}` : ""}${p.last?.created ? ` · ${ago(p.last.created)}` : ""}</small></span>${p.last ? h.pill(h.state(p.last.status), p.last.status) : h.pill("s-off", "no runs")}</button></li>`).join("")}</ul>` : h.empty("No pipeline yet.")) : off("devops", "devops"))}
          ${h.card("", "apps", "Apps &amp; functions", `<button type="button" class="linkbtn" data-axh-to="apps">Apps</button>`, O.apps || O.functions ? `<div class="occ-org">
            <button type="button" class="occ-orgi" data-axh-to="apps">${icon("apps")}<span><small>Apps</small><b class="num">${apps.length}</b><em>${running(apps)} running</em></span></button>
            <button type="button" class="occ-orgi" data-axh-to="functions">${icon("zap")}<span><small>Functions</small><b class="num">${fns.length}</b><em>${running(fns)} ready</em></span></button></div>
            ${[...apps, ...fns].filter(x => !/run|ready|ok|active/i.test(x.status || "")).slice(0, 5).map(x => `<p class="small axh-warn">${icon("alert")}${esc(x.name)}: ${esc(x.status)}${x.message ? ` · ${esc(x.message)}` : ""}</p>`).join("")}` : off("apps", "apps"))}
          ${h.card("", "monitor", "Machines", `<button type="button" class="linkbtn" data-axh-to="machines">Machines</button>`, O.machines ? (vms.length ? `<ul class="occ-list">${vms.slice(0, 8).map(m => `<li><button type="button" class="occ-row" data-axh-to="machines"><span class="occ-need-t"><b>${esc(m.name)}</b><small>${esc(m.title || m.os || "")} · ${m.cores || "–"} cores · ${m.ram || "–"} GB</small></span>${h.pill(h.state(m.status), m.status || "–")}</button></li>`).join("")}</ul>` : h.empty("No machine yet.")) : off("machines", "machines"))}
          ${h.card("", "globe", "DNS", `<button type="button" class="linkbtn" data-axh-to="dns">DNS</button>`, O.dns ? (zones.length ? `<ul class="occ-list">${zones.slice(0, 8).map(z => `<li><button type="button" class="occ-row" data-axh-to="dns"><span class="occ-need-t"><b>${esc(z.name || z.zone || z)}</b><small>${z.records != null ? `${z.records} records` : ""}</small></span></button></li>`).join("")}</ul>` : h.empty("No zone yet.")) : off("dns", "dns"))}
          ${h.card("", "key", "Connectors", `<button type="button" class="linkbtn" data-axh-to="connectors">Connectors</button>`, O.connectors ? `<ul class="occ-by">${Object.entries(conns.reduce((a, c) => ((a[c.group] ||= [0, 0])[c.configured ? 0 : 1]++, a), {}))
              .map(([g, [y, n]]) => `<li><span>${esc(g)}</span>${h.meter(y / (y + n), `${y} of ${y + n} set`)}<b class="num">${y}/${y + n}</b></li>`).join("")}</ul>` : off("connectors", "connectors"))}
        </div>`;
    },
  });
})();
