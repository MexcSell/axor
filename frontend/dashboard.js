/* Dashboard: the network and fund picture at a glance (TAO price, emission, flows, volume, open UIDs), fund
   movers over 24h, the best opportunities right now, your workspace subnets, notes / PDCA / today's daily
   note, and the latest notifications and news. Built from /api/dashboard plus the live subnet data; admins also get
   a strip of the server's resources (system.js). */
const Dashboard = (() => {
  let d = null, seq = 0, wired = false, mover = (() => { try { return localStorage.getItem("dash.mover") || "emission"; } catch { return "emission"; } })();
  const row = n => S.data?.subnets?.find(r => r.netuid === +n);
  const name = n => row(n)?.name || "";
  const signed = (x, f) => (x > 0 ? "+" : "") + f(x);
  const MOVERS = {
    emission: ["Emission 24h", "emission_up", "emission_down", x => signed(x, v => pct(v, 1)), "Change in each subnet's daily TAO emission over the last 24 hours"],
    price: ["Alpha price 24h", "price_up", "price_down", x => signed(x, v => pct(v, 1)), "Change in each subnet's alpha token price over the last 24 hours"],
    flow: ["TAO flow", "inflow", "outflow", x => signed(x, v => fmtNum(v, 1)) + " τ/d", "Net TAO staked into (+) or out of (−) each subnet, per day"],
  };

  async function open() {
    wire();
    const s = ++seq;
    if (!d) $("#dash").innerHTML = `<div class="stats">${Loading.tiles(6)}</div><div class="dash-grid">${Loading.cards(4, "card")}</div>`;
    try { const r = await api("/api/dashboard"); if (s !== seq) return; d = r; } catch (e) { if (s === seq) $("#dash").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
    render();
  }
  function onData() { if (S.view === "dashboard") open(); }

  function tile(ic, label, value, sub, extra = "") {
    return `<div class="stat"><div class="label">${icon(ic)}${label}</div><div class="value">${value}</div><div class="sub">${sub}</div>${extra}</div>`;
  }
  // diverging bars around zero: gains to the right, losses to the left; labels in text colour
  function bars(up, down, f) {
    const items = [...up.filter(i => i.value > 0), ...down.filter(i => i.value < 0).reverse()];
    if (!items.length) return `<p class="faint">Not enough history yet: movers appear after a day of data.</p>`;
    const max = Math.max(...items.map(i => Math.abs(i.value)));
    return `<div class="dv" role="list">${items.map(i => {
      const w = (Math.abs(i.value) / max * 50).toFixed(1), neg = i.value < 0;
      return `<button type="button" class="dv-row" role="listitem" data-open="${i.netuid}" title="SN${i.netuid} ${esc(name(i.netuid))}: ${esc(f(i.value))}">
        <span class="dv-name"><b>SN${i.netuid}</b> ${esc(name(i.netuid))}</span>
        <span class="dv-track"><i class="${neg ? "neg" : "pos"}" style="${neg ? "right" : "left"}:50%;width:${w}%"></i></span>
        <span class="dv-val num">${esc(f(i.value))}</span></button>`;
    }).join("")}</div>`;
  }
  const meter = (x, label) => `<span class="dash-meter" title="${label}: ${pct(x, 0)}"><i style="width:${(Math.min(1, x || 0) * 100).toFixed(0)}%"></i></span><span class="num">${pct(x, 0)}</span>`;

  function render() {
    if (!d.ready) { $("#dash").innerHTML = `<div class="card empty">${Loading.line("Collecting the first snapshot…")}</div>`; return; }
    const N = d.network, T = d.tao, M = MOVERS[mover], p = S.data?.tao_usd || T.usd;
    const st = Notes.stats(), mine = Workspace.subnets();
    const opp = d.opportunities.map(o => { const r = row(o.netuid);
      return `<tr data-open="${o.netuid}"><td><div class="dash-sn">${r ? logo(r) : ""}<span><b>SN${o.netuid}</b> ${esc(name(o.netuid))}<br><small class="faint">${esc(r?.field || "")}</small></span></div></td>
        <td class="r num"><b>${fmtNum(o.ratio, 1)}×</b><br><small class="faint">${usd(o.gross)} vs ${usd(o.monthly)}</small></td>
        <td><div class="dash-chance">${meter(o.chance, "Estimated top-miner chance")}</div></td>
        <td class="r num ${o.net > 0 ? "pos" : "neg"}">${usd(o.net)}</td>
        <td class="r">${Workspace.addButton(o.netuid, "btn sm")}</td></tr>`; }).join("");
    const wsCards = mine.map(({ netuid: n }) => {
      const r = row(n), s = d.workspace.find(w => w.netuid === n) || {}, own = Notes.all().filter(x => x.netuid === n);
      const t = own.reduce((a, x) => { const m = (x.text.match(/^\s*[-*+] \[( |x|X)\]/gm) || []); a.total += m.length; a.done += m.filter(c => !/\[ \]/.test(c)).length; return a; }, { done: 0, total: 0 });
      if (!r) return `<div class="card dash-ws" data-ws-go="${n}"><b>SN${n}</b><p class="faint">Not in current data.</p></div>`;
      return `<div class="card dash-ws" data-ws-go="${n}" role="button" tabindex="0">
        <div class="dash-sn">${logo(r)}<span><b>SN${n}</b> ${esc(r.name)}<br><small class="faint">${esc(r.field)}</small></span>${r.risk_level ? `<span class="ws-dot ${r.risk_level}" title="${esc(RISK[r.risk_level].label)}"></span>` : ""}</div>
        <div class="trend wide">${spark(r.series?.emission_day, 300, 34)}</div>
        <div class="mini"><div><span>Emission 24h</span><b>${delta(s.em_chg_24h)}</b></div><div><span>Top miner / day</span><b>${money(r.top_miner)}</b></div>
          <div><span>Registration</span><b>${money(r.reg_cost)}</b></div><div><span>Earnings ÷ cost</span><b>${s.ratio ? fmtNum(s.ratio, 1) + "×" : "–"}</b></div>
          <div><span>Top-miner chance</span><b>${pct(s.chance, 0)}</b></div><div><span>Notes</span><b>${own.length}${t.total ? ` · ${t.done}/${t.total} ✓` : ""}</b></div></div></div>`;
    }).join("");
    const pd = [["plan", "Plan"], ["do", "Do"], ["check", "Check"], ["act", "Act"]];
    const alertsLast = Notify.feed().last_read;

    $("#dash").innerHTML = `
      <div class="dash-top"><div><h1 class="page">Market Research</h1><p class="lead">Block ${d.block?.toLocaleString() || "–"} · updated ${ago(d.updated)}. Fund and network figures are live from the chain; opportunity scores are estimates.</p></div>
        <div class="row"><button type="button" class="btn sm" data-dash="alerts">${icon("bell")}Notification settings</button><button type="button" class="btn sm" data-goto="recommend">${icon("target")}Recommend</button></div></div>

      <div class="stats dash-kpis">
        ${tile("coin", "TAO price", usd(T.usd), T.change_24h != null ? `${delta(T.change_24h)} 24h` : "24h change after a day of data", `<div class="trend wide">${spark(T.series, 300, 30)}</div>`)}
        ${tile("zap", "Emission / day", fmtNum(N.emission_day, 0) + " τ", p ? usd(N.emission_day * p) : "")}
        ${tile("cycle", "Net TAO flow / day", `${N.flow_in + N.flow_out >= 0 ? "+" : ""}${fmtNum(N.flow_in + N.flow_out, 0)} τ`, `+${fmtNum(N.flow_in, 0)} in · ${fmtNum(N.flow_out, 0)} out`)}
        ${tile("chart", "Volume 24h", N.volume_24h != null ? fmtNum(N.volume_24h, 0) + " τ" : "–", N.volume_24h != null && p ? usd(N.volume_24h * p) : "alpha traded across subnets")}
        ${tile("pickaxe", "UIDs open now", N.open_regs, `of ${N.subnets} subnets · median reg ${fmtNum(N.median_reg)} τ`)}
        ${tile("sprout", "New subnets (7d)", N.new_7d, `${N.subnets} active`)}
      </div>
      ${System.strip()}

      <div class="dash-grid">
        <div class="card dash-wide"><div class="ws-card-head"><h3>${icon("target")}Top opportunities</h3><span class="faint small">Realistic earnings vs running cost, × estimated chance of reaching the paid top 10. UID open, no scam/avoid flags.</span></div>
          ${opp ? `<div class="tablewrap flat"><table class="grid mini-table dash-opp"><thead><tr><th>Subnet</th><th class="r">Earnings ÷ cost</th><th>Top-miner chance</th><th class="r">Net / month</th><th></th></tr></thead><tbody>${opp}</tbody></table></div>` : `<p class="faint">No subnet qualifies right now.</p>`}</div>

        <div class="card"><div class="ws-card-head"><h3>${icon("bell")}Notifications <span class="badge unread-badge" data-unread hidden></span></h3><button type="button" class="linkbtn" data-dash="bell">View all</button></div>
          <div class="dash-alerts">${Notify.listHtml(d.alerts, alertsLast)}</div></div>

        <div class="card dash-wide"><div class="ws-card-head"><h3>${icon("coins")}Fund movers</h3>
            <div class="seg" role="tablist" aria-label="Mover metric">${Object.entries(MOVERS).map(([k, m]) => `<button type="button" data-mover="${k}" aria-pressed="${mover === k}">${m[0]}</button>`).join("")}</div></div>
          <p class="faint small dash-sub">${M[4]}. Biggest gains to the right in blue, losses to the left in red. Click a subnet for details.</p>
          ${bars(d.movers[M[1]], d.movers[M[2]], M[3])}</div>

        <div class="card"><div class="ws-card-head"><h3>${icon("calendar")}Today</h3><button type="button" class="linkbtn" data-dash="daily">Open daily notes</button></div>
          <div id="dash-today">${Loading.line("Loading today's note…")}</div>
          <div class="dash-pdca">${pd.map(([k, l]) => `<button type="button" class="dash-pd s-${k}" data-dash="pdca"><b>${st.pdca[k]}</b><span>${l}</span></button>`).join("")}</div>
          <p class="faint small">${st.tasks.total ? `${st.tasks.done} of ${st.tasks.total} checklist items done across ${st.notes} notes` : `${st.notes} notes`}${st.streak ? ` · ${st.streak}-day daily streak` : ""}</p></div>

        <div class="dash-wide"><h2 class="section-title">${icon("pickaxe")}My workspace <span class="count faint">${mine.length}</span></h2>
          ${wsCards ? `<div class="card-grid">${wsCards}</div>` : `<div class="card empty">Add subnets to your workspace to track them here. <button type="button" class="linkbtn" data-goto="explore">Browse subnets</button></div>`}</div>

        <div class="card dash-wide"><div class="ws-card-head"><h3>${icon("news")}Subnet news</h3><span class="faint small">GitHub releases and commits, and on-chain changes</span></div>
          ${d.news.length ? `<ul class="news-list">${d.news.map(Workspace.newsItem).join("")}</ul>` : `<p class="faint">No news yet: the first fetch runs a few minutes after start-up, then every few hours.</p>`}</div>
      </div>`;
    today();
    Notify.badge();
  }
  async function today() {
    try { const x = await Notes.ensureToday(); const el = $("#dash-today"); if (el) el.innerHTML = x ? Notes.card(x, "daily") : ""; }
    catch (e) { const el = $("#dash-today"); if (el) el.innerHTML = `<p class="faint">${esc(e.message)}</p>`; }
  }

  function wire() {
    if (wired) return; wired = true;
    Notes.wire();
    const root = $("#view-dashboard");
    root.addEventListener("click", e => {
      const t = e.target;
      const m = t.closest("[data-mover]"); if (m) { mover = m.dataset.mover; try { localStorage.setItem("dash.mover", mover); } catch {} return render(); }
      const g = t.closest("[data-goto]"); if (g) return setView(g.dataset.goto);
      const a = t.closest("[data-dash]")?.dataset.dash;
      if (a === "alerts") return Notify.settings();
      if (a === "bell") { e.stopPropagation(); return Notify.panel(); }
      if (a === "daily" || a === "pdca") { Notes.openView(a); return Workspace.show(null, "notes"); }
      const nt = t.closest("[data-nt]"); if (nt) { const x = d.alerts.find(i => i.id === +nt.dataset.nt); if (x?.url) return window.open(x.url, "_blank", "noopener"); if (x?.netuid != null) return openDrawer(x.netuid); }
      const w = t.closest("[data-ws-go]"); if (w && !t.closest("button, a")) return Workspace.show(+w.dataset.wsGo, "brief");
    });
    root.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.matches("[data-ws-go], [data-nt]")) e.target.click(); });
  }

  return { open, onData };
})();
