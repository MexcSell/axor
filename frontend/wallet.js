/* Wallets: your Bittensor wallets, laid out like a coin wallet. Tracked by public SS58 addresses only (seed phrases
   and keys never leave your machine; the server refuses anything that looks like one).
   - Accounts on the left, each with its total; connect a browser wallet (Talisman, SubWallet, Polkadot.js) to sign.
   - The selected account: total balance (free and staked, marked to TAO and USD) and the actions Send, Receive,
     Stake, Unstake, Move and Unstake all (wallettx.js: review, sign in your browser wallet, submit).
   - Assets (TAO and each subnet's alpha), Staking (every position with its own actions), Activity (transactions
     signed here), Hotkeys (registrations and earnings) and the Subnet runbook, which builds the btcli commands for
     any subnet from your choices (hotkey, network, stake amount, steps) plus your own steps, saved per subnet. */
const Wallet = (() => {
  let d = null, hidden = false, sel = null, tab = "assets", netuid = null, rb = null, quote = null, wired = false, saveT = null, quoteT = null;
  let act = null, actFor = null;  // activity of the selected wallet
  // terminal: read-only btcli commands answered by the server; output and history live in memory only
  // terminal: the real btcli, read-only (wallet_term.py); output lives in memory, history in this browser
  let term = [], hist = [], hi = 0, busy = false, termMax = false, termInfo = null, reveal = false;
  const TABS = [["assets", "Assets", "coins"], ["staking", "Staking", "layers"], ["activity", "Activity", "clock"], ["hotkeys", "Hotkeys", "key"], ["terminal", "Terminal", "terminal"], ["runbook", "Runbook", "book"]];
  const OLD_TABS = { overview: "assets", stake: "staking" };
  const STEPS = [["create", "Create"], ["fund", "Fund"], ["register", "Register"], ["stake", "Stake"], ["check", "Check"]];
  const VARS = ["wallet", "hotkey", "netuid", "network", "amount", "coldkey", "hotkey_ss58"];
  const cur = () => d?.wallets.find(w => w.id === sel);
  const subnet = n => S.data?.subnets.find(r => r.netuid === +n);
  // amounts: one color per unit (τ teal, α violet, $ green), always with the symbol so color is never the only cue.
  // priv amounts are your balances: with "hide amounts" on they're left out of the page (not just blurred).
  const UNIT = { tao: ["τ", "TAO"], alpha: ["α", "alpha"], usd: ["$", "USD"] };
  function amt(x, unit = "tao", { digits, priv = false } = {}) {
    if (x == null || isNaN(x)) return `<span class="faint">–</span>`;
    const [sym, name] = UNIT[unit];
    if (priv && hidden) return `<span class="amt amt-${unit} masked" role="img" aria-label="${name} amount hidden">${unit === "usd" ? `<span class="u">$</span>•••` : `•••<span class="u">${sym}</span>`}</span>`;
    const full = unit === "usd" ? x.toFixed(2) : String(+x.toFixed(9));
    return `<span class="amt amt-${unit}" title="${esc(full)} ${name}">${unit === "usd" ? esc(usd(x)) : `${esc(fmtNum(x, digits))}<span class="u">${sym}</span>`}</span>`;
  }
  const tao = (x, priv) => amt(x, "tao", { priv }), alpha = (x, priv) => amt(x, "alpha", { priv }), dollars = (x, priv) => amt(x, "usd", { priv });
  const withUsd = (x, priv) => x == null ? `<span class="faint">–</span>` : `${tao(x, priv)}${d?.tao_usd ? ` ${dollars(x * d.tao_usd, priv)}` : ""}`;
  const mask = text => hidden ? "•••" : text;  // balance text inside badges
  // color amounts inside plain text: runs on already-escaped text and only wraps digits, $, τ and α
  const colorize = html => html.replace(/(-?\$[\d,.]+[kM]?)|(\d[\d,.]*) ?(τ|α)/g, (m, u, n, sym) =>
    u ? `<span class="amt amt-usd">${u}</span>` : `<span class="amt amt-${sym === "τ" ? "tao" : "alpha"}">${n}<span class="u">${sym}</span></span>`);
  const copyBtn = (text, label = "") => `<button type="button" class="${label ? "btn sm" : "iconbtn sm"}" data-wl-copy="${esc(text)}" title="Copy" aria-label="Copy">${icon("copy")}${label}</button>`;
  const addr = (a, cls = "src-chip") => `<span class="${cls}" title="${esc(a)}">${esc(short(a))}</span>${copyBtn(a)}`;
  const av = (a, size) => WalletTx.avatar(a, size);

  async function init() {
    $("#nav-wallet").hidden = !Auth.me();
    hidden = !!store.get("wallet.hide", false); hist = store.get("wallet.hist", []) || []; hi = hist.length; sel = store.get("wallet.sel", null); tab = store.get("wallet.tab", "assets"); netuid = store.get("wallet.netuid", null);
    tab = OLD_TABS[tab] || tab;
    if (!TABS.some(([k]) => k === tab)) tab = "assets";
    if (Auth.me()) WalletTx.init(() => { if (S.view === "wallet" && d?.wallets.length) render(); });
  }
  async function load(refresh = false) {
    try { d = await api("/api/wallet" + (refresh ? "?refresh=1" : "")); } catch (e) { d = d || { wallets: [], error: e.message }; }
    if (!d.wallets.some(w => w.id === sel)) sel = d.wallets[0]?.id ?? null;
    $("#c-wallet").textContent = d.wallets.length || "";
  }
  async function open() {
    wire();
    if (!d) $("#wallet").innerHTML = Loading.cards(3, "card");
    await load();
    render();
    if (tab === "runbook") loadRunbook();
    if (tab === "activity") loadActivity();
  }
  // open the runbook for one subnet (subnet drawer button)
  async function openSubnet(n) {
    netuid = +n; store.set("wallet.netuid", netuid); tab = "runbook"; rb = null;
    closeDrawer(); setView("wallet");
  }
  function onData() {
    if (S.view !== "wallet" || tab !== "runbook") return;
    $("#wl-body")?.contains(document.activeElement) && document.activeElement.matches("input, select") ? refreshCmds() : renderBody();
  }
  function pick(id) { sel = +id; store.set("wallet.sel", sel); act = null; render(); if (tab === "runbook") renderBody(); if (tab === "activity") loadActivity(); }
  function setTab(t) { tab = t; store.set("wallet.tab", t); renderTabs(); renderBody(); if (t === "runbook" && !rb) loadRunbook(); if (t === "activity") loadActivity(); }
  async function loadActivity() {
    const id = sel; if (id == null) return;
    try { const a = await api(`/api/wallet/activity?wallet_id=${id}`); if (sel === id) { act = a; actFor = id; } } catch (e) { act = { error: e.message }; }
    if (tab === "activity" && sel === id) renderBody();
  }
  // a transaction finished: fresh balances, the activity, and the open tab
  async function after(res) {
    if (res?.activity) { act = res.activity; actFor = sel; }
    await load(true); render();
  }
  function action(op, preset) { WalletTx.start(op, cur(), preset, after); }
  async function track(a) {
    const name = (a.name || "wallet").replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32) || "wallet";
    const taken = new Set(d.wallets.map(w => w.name));
    let n = name, i = 2; while (taken.has(n)) n = `${name.slice(0, 29)}-${i++}`;
    try { d = await api("/api/wallet", { method: "POST", body: { name: n, coldkey: a.address, hotkeys: [], note: `From ${WalletTx.label(a.source)}` } }); }
    catch (e) { return toast(e.message); }
    sel = d.wallets.find(w => WalletTx.pub(w.coldkey) === a.pub)?.id ?? sel; store.set("wallet.sel", sel);
    $("#c-wallet").textContent = d.wallets.length || ""; render(); toast(`Tracking ${n}`);
  }

  // ---------- rendering ----------
  function render() {
    const box = $("#wallet");
    if (!d.wallets.length) {
      const exts = WalletTx.connected(), accts = WalletTx.accounts();
      box.innerHTML = `<div class="card chat-empty sl-setup wx-empty"><span class="av c-teal xl" aria-hidden="true">${icon("wallet")}</span><h3>Your Bittensor wallet</h3>
        <p class="muted">Balances, stake and registrations for your coldkeys and hotkeys. Stake, unstake, move and send TAO, signed in your browser wallet. AXoR only keeps public addresses.</p>
        ${d.error ? `<p class="no">${esc(d.error)}</p>` : ""}
        <div class="row" style="justify-content:center"><button type="button" class="btn primary" data-wx-connect data-wl="connect">${icon("wallet")}${exts.length ? `Choose from ${accts.length} account${accts.length === 1 ? "" : "s"}` : "Connect a browser wallet"}</button>
          <button type="button" class="btn" data-wl="add">${icon("plus")}Add an address</button></div>${start()}</div>`;
      return;
    }
    const exts = WalletTx.connected();
    box.innerHTML = `<div class="wx">
      <aside class="card wx-side"><div class="src-side-head"><b>Accounts</b><span class="spacer"></span>
        <button type="button" class="iconbtn sm" data-wl="hide" aria-pressed="${hidden}" title="${hidden ? "Show amounts" : "Hide amounts"}" aria-label="${hidden ? "Show amounts" : "Hide amounts"}">${icon(hidden ? "eyeoff" : "eye")}</button>
        <button type="button" class="iconbtn sm" data-wl="refresh" title="Refresh from chain" aria-label="Refresh from chain">${icon("reset")}</button>
        <button type="button" class="iconbtn sm" data-wl="add" title="Add an address" aria-label="Add an address">${icon("plus")}</button></div>
        <div class="wx-list">${d.wallets.map(w => `<button type="button" class="wx-acct" data-wallet="${w.id}" aria-current="${w.id === sel}">
          ${av(w.coldkey)}<span class="wx-acct-main"><b>${esc(w.name)}${WalletTx.signerFor(w.coldkey) ? `<span class="wx-can" title="Your browser wallet can sign for it">${icon("key")}</span>` : ""}</b><small class="faint">${esc(short(w.coldkey))}</small></span>
          <span class="wx-acct-val">${w.error ? icon("alert") : tao(w.total_tao, true)}</span></button>`).join("")}</div>
        <button type="button" class="wx-connect ${exts.length ? "on" : ""}" data-wx-connect data-wl="connect">${exts.length ? `<span class="wx-dot"></span><span><b>${esc(exts.map(WalletTx.label).join(", "))}</b><small class="faint">${WalletTx.accounts().length} account${WalletTx.accounts().length === 1 ? "" : "s"} · can sign</small></span>` : `${icon("wallet")}<span><b>Connect wallet</b><small class="faint">Talisman, SubWallet, Polkadot.js</small></span>`}${icon("right")}</button>
        <div class="wl-legend small" aria-label="Units"><span class="amt amt-tao"><span class="u">τ</span></span>TAO<span class="amt amt-alpha"><span class="u">α</span></span>Subnet alpha<span class="amt amt-usd"><span class="u">$</span></span>USD</div>
        <div class="wl-safe faint small">${icon("lock")}<span>Only public addresses are stored. Your browser wallet keeps the keys and signs.</span></div></aside>
      <div class="wx-main"><div id="wl-head"></div>
        <div class="card src-main wx-card"><nav class="src-tabs" role="tablist" id="wl-tabs"></nav><div id="wl-body" class="src-body"></div></div></div></div>`;
    renderHead(); renderTabs(); renderBody();
  }
  const start = () => `<details class="sl-help"><summary>Don't have a wallet yet?</summary><ol>
      <li>Install Talisman, SubWallet or Polkadot.js in this browser and create a Bittensor account there, or create one on your own machine with <code>btcli wallet create -w miner -H default</code>.</li>
      <li>Write the recovery phrase on paper and keep it offline. Never paste it into a website or chat.</li>
      <li>Connect the browser wallet here, or add the public addresses (they start with 5; <code>btcli wallet list</code> shows them).</li></ol></details>`;
  function renderHead() {
    const box = $("#wl-head"), w = cur(); if (!box || !w) return;
    const signer = WalletTx.signerFor(w.coldkey), err = w.error;
    const free = w.free || 0, staked = w.staked_tao || 0, total = free + staked, pf = total ? free / total * 100 : 0;
    const ops = ["send", "receive", "stake", "unstake", "move"];
    box.innerHTML = `<section class="card wx-hero">
      <div class="wx-hero-top">${av(w.coldkey, "lg")}
        <div class="wx-id"><b>${esc(w.name)}</b><span class="wx-chip"><span class="num" title="${esc(w.coldkey)}">${esc(short(w.coldkey))}</span>${copyBtn(w.coldkey)}</span></div>
        <span class="wx-net" title="Network">${esc(d.network || "finney")}</span>
        ${signer ? `<span class="badge clear" title="${esc(signer.name)} in ${esc(WalletTx.label(signer.source))}">${icon("key")}Signs with ${esc(WalletTx.label(signer.source))}</span>`
          : `<button type="button" class="badge new wx-watch" data-wx-connect data-wl="connect" title="Connect the browser wallet that holds this coldkey">${icon("eye")}Watch-only · connect to sign</button>`}
        <span class="spacer"></span>
        <a class="iconbtn sm" href="https://taostats.io/account/${encodeURIComponent(w.coldkey)}" target="_blank" rel="noopener noreferrer" title="Open on Taostats" aria-label="Open on Taostats">${icon("external")}</a>
        <button type="button" class="iconbtn sm" data-wl="menu" title="More" aria-label="More">${icon("dots")}</button></div>
      ${err ? `<div class="sl-err">${icon("alert")}${esc(err)}</div>` : `
      <div class="wx-balance"><span class="faint">Total balance</span><b class="wx-big">${tao(total, true)}</b>${d.tao_usd ? `<span class="wx-usd">${dollars(total * d.tao_usd, true)}</span>` : ""}</div>
      <div class="wx-split" role="img" aria-label="${hidden ? "Balance split hidden" : `Free ${fmtNum(free)} TAO, staked ${fmtNum(staked)} TAO`}"><i class="free" style="width:${pf}%"></i><i class="staked" style="width:${100 - pf}%"></i></div>
      <div class="wx-legend"><span><i class="free"></i>Free ${tao(free, true)}</span><span><i class="staked"></i>Staked ${tao(staked, true)} <span class="faint">· ${w.stake.length} position${w.stake.length === 1 ? "" : "s"}</span></span></div>`}
      <div class="wx-acts">${ops.map(op => `<button type="button" class="wx-act" data-wx-op="${op}" ${err || (["unstake", "move"].includes(op) && !w.stake?.length) ? "disabled" : ""}><span class="wx-act-ico">${icon(WalletTx.OPS[op][1])}</span><span>${WalletTx.OPS[op][0]}</span></button>`).join("")}
        <button type="button" class="wx-act" data-wl="more" ${err ? "disabled" : ""}><span class="wx-act-ico">${icon("dots")}</span><span>More</span></button></div></section>`;
  }
  function renderTabs() {
    const box = $("#wl-tabs"); if (!box) return;
    box.innerHTML = TABS.map(([k, label, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${tab === k}">${icon(ic)}<span>${label}</span>${k === "activity" && act?.length && actFor === sel ? `<span class="tab-count">${act.length}</span>` : ""}</button>`).join("");
  }
  function renderBody() {
    const box = $("#wl-body"), w = cur(); if (!box || !w) return;
    if (w.error && tab !== "runbook" && tab !== "activity") { box.innerHTML = `<div class="sl-err">${icon("alert")}${esc(w.error)}</div>`; return; }
    const keep = box.scrollTop;
    box.innerHTML = ({ assets: assetsView, staking: stakingView, activity: activityView, hotkeys: hotkeyView, terminal: terminalView, runbook: runbookView })[tab](w);
    box.scrollTop = keep;
    const out = $("#wl-term-out"); if (out) out.scrollTop = out.scrollHeight;
    if (tab === "terminal") { loadTermInfo(); setTimeout(() => $("#wl-term-input")?.focus({ preventScroll: true }), 0); }
  }
  const empty = text => `<div class="empty">${text}</div>`;
  function menu(btn, items) {
    document.querySelector(".wx-menu")?.remove();
    const pop = document.createElement("div"); pop.className = "popover wx-menu"; pop.setAttribute("role", "menu");
    pop.innerHTML = items.map(([k, ic, label, danger]) => `<button type="button" class="mi ${danger ? "danger-text" : ""}" role="menuitem" data-mk="${k}">${icon(ic)}<span>${label}</span></button>`).join("");
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 6) + "px"; pop.style.left = Math.max(16, Math.min(b.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 16)) + "px";
    return new Promise(res => {
      pop.onclick = e => { const m = e.target.closest("[data-mk]"); if (m) { pop.remove(); res(m.dataset.mk); } };
      setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("click", off); res(null); } }), 0);
    });
  }

  // ---------- assets, staking, activity ----------
  function assetsView(w) {
    const bySubnet = {};
    for (const p of w.stake) (bySubnet[p.netuid] ||= { netuid: p.netuid, subnet: p.subnet, tao: 0, alpha: 0, n: 0 }), bySubnet[p.netuid].tao += p.tao || 0, bySubnet[p.netuid].alpha += p.amount, bySubnet[p.netuid].n++;
    const rows = Object.values(bySubnet).sort((a, b) => b.tao - a.tao), total = (w.free || 0) + (w.staked_tao || 0);
    const share = x => total && !hidden ? `<span class="wx-share" title="${fmtNum(x / total * 100, 1)}% of the wallet"><i style="width:${Math.max(1, x / total * 100)}%"></i></span>` : "";
    const price = n => n === 0 ? 1 : subnet(n)?.price ?? (bySubnet[n]?.alpha ? bySubnet[n].tao / bySubnet[n].alpha : null);
    return `<div class="wx-assets">
      <div class="wx-asset"><span class="wx-tok tao" aria-hidden="true">τ</span><span class="wx-asset-main"><b>TAO</b><small class="faint">Free balance${d.tao_usd ? ` · ${esc(usd(d.tao_usd))}` : ""}</small></span>
        ${share(w.free || 0)}<span class="wx-asset-val">${tao(w.free, true)}${d.tao_usd ? `<small>${dollars((w.free || 0) * d.tao_usd, true)}</small>` : ""}</span>
        <span class="wx-row-acts"><button type="button" class="iconbtn sm" data-wx-op="send" title="Send" aria-label="Send TAO">${icon("send")}</button><button type="button" class="iconbtn sm" data-wx-op="stake" title="Stake" aria-label="Stake TAO">${icon("plus")}</button></span></div>
      ${rows.map(r => `<div class="wx-asset"><span class="wx-tok" aria-hidden="true">${r.netuid}</span><span class="wx-asset-main"><b>${r.netuid ? `SN${r.netuid} · ` : ""}${esc(r.subnet)}</b>
          <small class="faint">${r.netuid ? `Alpha${price(r.netuid) ? ` · ${fmtNum(price(r.netuid), 5)} τ` : ""}` : "Root stake"} · ${r.n} position${r.n === 1 ? "" : "s"}</small></span>
        ${share(r.tao)}<span class="wx-asset-val">${amt(r.alpha, r.netuid ? "alpha" : "tao", { priv: true })}<small>${r.netuid ? tao(r.tao, true) : d.tao_usd ? dollars(r.tao * d.tao_usd, true) : ""}</small></span>
        <span class="wx-row-acts"><button type="button" class="iconbtn sm" data-wx-op="stake" data-netuid="${r.netuid}" title="Stake more" aria-label="Stake more on SN${r.netuid}">${icon("plus")}</button>
          <button type="button" class="iconbtn sm" data-wx-op="unstake" data-netuid="${r.netuid}" title="Unstake" aria-label="Unstake from SN${r.netuid}">${icon("minus")}</button></span></div>`).join("")}
      ${rows.length ? "" : `<div class="wx-cta-row"><p class="muted">No stake yet. Staking TAO with a validator earns a share of a subnet's emissions, and buys the alpha some subnets charge fees in.</p><button type="button" class="btn primary" data-wx-op="stake">${icon("plus")}Stake TAO</button></div>`}</div>`;
  }
  function stakingView(w) {
    if (!w.stake.length) return `<div class="wx-cta-row">${empty("This coldkey has no stake.")}<button type="button" class="btn primary" data-wx-op="stake">${icon("plus")}Stake TAO</button></div>`;
    return `<div class="wx-stake-head"><span class="faint small">${w.stake.length} position${w.stake.length === 1 ? "" : "s"} · ${withUsd(w.staked_tao, true)}</span><span class="spacer"></span>
        <button type="button" class="btn sm primary" data-wx-op="stake">${icon("plus")}Stake</button><button type="button" class="btn sm" data-wx-op="unstake_all">${icon("minus")}Unstake all…</button></div>
      <div class="wx-positions">${w.stake.map(p => `<div class="wx-pos"><span class="wx-tok" aria-hidden="true">${p.netuid}</span>
        <span class="wx-asset-main"><b><button type="button" class="linkbtn" data-open="${p.netuid}">${p.netuid ? `SN${p.netuid} · ` : ""}${esc(p.subnet)}</button></b>
          <small class="faint">${p.hotkey_name ? `<b>${esc(p.hotkey_name)}</b> · ` : ""}<span class="num" title="${esc(p.hotkey)}">${esc(short(p.hotkey))}</span>${p.registered ? ` · <span class="ok">registered</span>` : ""}</small></span>
        <span class="wx-asset-val">${amt(p.amount, p.netuid ? "alpha" : "tao", { priv: true })}<small>${p.netuid ? withUsd(p.tao, true) : d.tao_usd ? dollars(p.tao * d.tao_usd, true) : ""}</small></span>
        <span class="wx-row-acts on">
          <button type="button" class="iconbtn sm" data-wx-op="stake" data-netuid="${p.netuid}" data-hotkey="${esc(p.hotkey)}" title="Stake more with this validator" aria-label="Stake more">${icon("plus")}</button>
          <button type="button" class="iconbtn sm" data-wx-op="unstake" data-netuid="${p.netuid}" data-hotkey="${esc(p.hotkey)}" title="Unstake" aria-label="Unstake">${icon("minus")}</button>
          <button type="button" class="iconbtn sm" data-wx-op="move" data-netuid="${p.netuid}" data-hotkey="${esc(p.hotkey)}" title="Move to another validator or subnet" aria-label="Move">${icon("swap")}</button>
          <button type="button" class="iconbtn sm" data-runbook="${p.netuid}" title="Runbook" aria-label="Runbook">${icon("terminal")}</button></span></div>`).join("")}</div>`;
  }
  const OP_ICON = { stake: "plus", unstake: "minus", move: "swap", unstake_all: "minus", send: "send" };
  function activityView(w) {
    if (!act || actFor !== sel) return Loading.line("Loading activity…");
    if (act.error) return `<div class="sl-err">${icon("alert")}${esc(act.error)}</div>`;
    if (!act.length) return `<div class="wx-cta-row">${empty("Transactions you sign here show up here, with their block and fee. Older history is on Taostats.")}
      <a class="btn" href="https://taostats.io/account/${encodeURIComponent(w.coldkey)}" target="_blank" rel="noopener noreferrer">${icon("external")}Taostats history</a></div>`;
    const day = ts => new Date(ts * 1000).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    let last = "";
    return `<div class="wx-activity">${act.map(a => {
      const dd = day(a.created), head = dd !== last ? `<div class="wx-day">${esc(dd)}</div>` : ""; last = dd;
      return `${head}<div class="wx-tx is-${a.status}"><span class="wx-tx-ico">${icon(OP_ICON[a.op] || "send")}</span>
        <span class="wx-asset-main"><b>${esc(a.title)}</b><small class="faint">${colorize(esc(a.detail))}</small>${a.error ? `<small class="no">${esc(a.error)}</small>` : ""}</span>
        <span class="wx-tx-side"><span class="badge ${a.status === "ok" ? "clear" : "avoid"}">${a.status === "ok" ? `${icon("check")}Confirmed` : `${icon("close")}Failed`}</span>
          <small class="faint">${new Date(a.created * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}${a.fee != null ? ` · fee ${amt(a.fee, "tao", { digits: 6 })}` : ""}</small>
          ${a.explorer_url ? `<a class="linkbtn small" href="${esc(a.explorer_url)}" target="_blank" rel="noopener noreferrer">${esc(a.extrinsic_id || "Explorer")}${icon("external")}</a>` : ""}</span></div>`;
    }).join("")}</div>`;
  }
  function hotkeyView(w) {
    const tile = (ic, label, value, sub) => `<div class="stat"><div class="label">${icon(ic)}${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
    const regs = w.hotkey_info.flatMap(h => h.registrations.map(r => ({ ...r, hk: h })));
    const earn = regs.reduce((t, r) => t + (r.tao_day || 0), 0);
    const rows = w.hotkey_info.map(h => `<div class="src-row"><span class="src-fico">${icon("key")}</span>
        <span class="src-row-main"><b>${h.name ? esc(h.name) : `<span class="faint">Unnamed</span>`}
          ${h.declared && !h.owned ? `<span class="badge caution" title="The chain says this hotkey isn't owned by this coldkey">${icon("alert")}Not owned</span>` : ""}
          ${!h.declared ? `<span class="badge new">Found on chain</span>` : ""}</b>
          <small class="faint"><span class="num" title="${esc(h.ss58)}">${esc(short(h.ss58))}</span>${h.registrations.length ? ` · ${h.registrations.map(r => `SN${r.netuid} UID ${r.uid ?? "?"}`).join(", ")}` : " · not registered"}</small></span>
        ${copyBtn(h.ss58)}${h.declared ? "" : `<button type="button" class="btn sm" data-name-hk="${esc(h.ss58)}">${icon("plus")}Name it</button>`}</div>`).join("");
    return `<div class="wl-pad"><div class="stats">
        ${tile("pickaxe", "Registrations", regs.length, `${new Set(regs.map(r => r.netuid)).size} subnets · ${w.hotkey_info.length} hotkeys`)}
        ${tile("trophy", "Top-paid earnings / day", earn ? tao(earn, true) : "–", earn ? (d.tao_usd ? dollars(earn * d.tao_usd, true) : "") : "None of your hotkeys is among a subnet's top 15")}</div>
      ${regs.length ? `<h4 class="wl-h">${icon("pickaxe")}Where your hotkeys are registered</h4><div class="src-rows wl-box">${regs.map(r => `<div class="src-row"><span class="src-fico">${icon("key")}</span>
          <span class="src-row-main"><b><button type="button" class="linkbtn" data-open="${r.netuid}">SN${r.netuid} · ${esc(r.subnet)}</button></b>
            <small class="faint">${esc(r.hk.name || short(r.hk.ss58))} · UID ${r.uid ?? "?"}${r.tao_day ? ` · ${tao(r.tao_day, true)}/day` : ""}</small></span>
          <button type="button" class="btn sm" data-runbook="${r.netuid}">${icon("terminal")}Runbook</button></div>`).join("")}</div>` : ""}
      <h4 class="wl-h">${icon("key")}Hotkeys</h4></div>
      <div class="src-rows">${rows || empty("No hotkeys yet. Add them with Edit, or create one with <code>btcli wallet new-hotkey</code>.")}</div>
      <p class="faint small wl-pad">Hotkeys you named come first. Name a hotkey exactly as in btcli (<code>-H name</code>) so runbook commands use the right one.</p>`;
  }

  // ---------- runbook ----------
  async function loadRunbook() {
    const w = cur(); if (!w) return;
    if (netuid == null) netuid = Workspace.subnets()[0]?.netuid ?? (w.stake || []).find(p => p.netuid)?.netuid ?? S.data?.subnets[0]?.netuid ?? 1;
    const at = netuid;
    try { rb = await api(`/api/wallet/runbook/${at}`); } catch (e) { rb = { error: e.message }; }
    if (at !== netuid) return;
    renderBody();
    if (rb.amount) getQuote();
  }
  const body = () => ({ wallet_id: sel, hotkey: rb.hotkey || null, network: rb.network || "finney", amount: rb.amount ?? null, prefix: rb.prefix || "", hidden: rb.hidden || [], steps: rb.steps || [] });
  function save() {
    clearTimeout(saveT);
    saveT = setTimeout(async () => {
      try { rb.updated = (await api(`/api/wallet/runbook/${netuid}`, { method: "PUT", body: body() })).updated; }
      catch (e) { toast(e.message); }
    }, 600);
  }
  function getQuote() {
    clearTimeout(quoteT); quote = null;
    if (!(rb.amount > 0)) return;
    const at = [netuid, rb.amount];
    quoteT = setTimeout(async () => {
      let q; try { q = await api(`/api/wallet/quote?netuid=${at[0]}&amount=${at[1]}`); } catch (e) { q = { error: e.message }; }
      if (netuid !== at[0] || rb.amount !== at[1]) return;
      quote = q; const el = $("#wl-quote"); if (el) el.innerHTML = quoteText();
    }, 400);
  }
  const quoteText = () => !(rb?.amount > 0) ? `<span class="faint">Enter an amount for a live quote.</span>` : !quote ? `<span class="faint">Quoting…</span>` : quote.error ? `<span class="no">${esc(quote.error)}</span>`
    : `≈ ${alpha(quote.alpha)} for ${tao(quote.tao)} · fee ${amt(quote.fee_tao, "tao", { digits: 6 })} · slippage ${alpha(quote.slippage_alpha)}`;

  // the values runbook commands are filled with
  function ctx(w) {
    const hk = rb.hotkey || w.hotkeys[0]?.name || "default";
    return { wallet: w.name, hotkey: hk, netuid: String(netuid), network: rb.network || "finney", amount: rb.amount > 0 ? String(rb.amount) : "<amount>",
      coldkey: w.coldkey, hotkey_ss58: w.hotkeys.find(h => h.name === hk)?.ss58 || "<hotkey address>" };
  }
  const fill = (s, c) => s.replace(/\{(\w+)\}/g, (m, k) => c[k] ?? m);
  function steps(w) {
    const r = subnet(netuid), c = ctx(w), k = `-w ${c.wallet} -H ${c.hotkey}`, net = `--network ${c.network}`;
    const hkInfo = w.hotkey_info?.find(h => h.name === c.hotkey || h.ss58 === c.hotkey_ss58);
    const reg = hkInfo?.registrations.find(x => x.netuid === +netuid);
    const staked = (w.stake || []).filter(p => p.netuid === +netuid).reduce((t, p) => t + p.amount, 0);
    const cost = r?.reg_cost;
    return [
      { key: "create", title: "Create the wallet", done: true, status: "Tracked here",
        note: "A coldkey (holds funds) plus a hotkey (signs for the miner). Write the recovery phrase on paper and keep it offline; never paste it into a website or chat.",
        cmds: [`btcli wallet create ${k}`] },
      { key: "fund", title: "Fund the coldkey", done: w.free != null && cost != null && w.free >= cost + (rb.amount || 0), status: w.free != null ? `Free ${mask(fmtNum(w.free) + " τ")}` : "",
        note: `Send TAO from an exchange to ${c.coldkey}.${cost != null ? ` You need about ${fmtNum(cost + (rb.amount || 0))} τ for registration${rb.amount ? " and stake" : ""}, plus a little for fees.` : ""}`,
        cmds: ["btcli wallet list", `btcli wallet balance -w ${c.wallet} ${net}`] },
      { key: "register", title: `Register the hotkey on SN${netuid}`, done: !!reg, status: reg ? `UID ${reg.uid ?? "?"}` : r ? (r.uid_available ? "UID available" : "No UID available now") : "",
        warn: r && !r.uid_available && !reg,
        note: r ? `Costs ${fmtNum(r.reg_cost)} τ now (burned, not refunded). ${r.registration_allowed ? `${r.open_slots} open slots, ${r.prunable_uids} prunable.` : "Registration is closed on this subnet."} New UIDs are immune for ${fmtNum(r.immunity_hours, 0)}h. Preview first with --dry-run, then run it for real.` : "Preview first with --dry-run, then run it for real.",
        cmds: [`btcli subnets register --netuid ${netuid} ${k} ${net} --dry-run`, `btcli subnets register --netuid ${netuid} ${k} ${net}`] },
      { key: "stake", title: `Stake TAO into SN${netuid}`, done: staked > 0, status: staked > 0 ? `${mask(fmtNum(staked) + " α")} staked` : "",
        note: "Staking buys the subnet's alpha (some subnets charge upload or validation fees in alpha). Slippage protection is on by default. Preview first.",
        cmds: [`btcli stake add --netuid ${netuid} ${k} --amount-tao ${c.amount} ${net} --dry-run`, `btcli stake add --netuid ${netuid} ${k} --amount-tao ${c.amount} ${net}`], quote: true },
      { key: "check", title: "Check registration and stake", note: "Shows the UID, stake, incentive and emission of each hotkey on this subnet.",
        cmds: [`btcli wallet overview -w ${c.wallet} --netuid ${netuid} ${net}`] },
      ...(rb.steps || []).map((s, i) => ({ key: "custom", i, title: s.title || "Custom step", cmds: fill(s.cmd, c).split("\n").filter(l => l.trim()), custom: true })),
    ];
  }
  const visible = w => steps(w).filter(s => s.custom || !(rb.hidden || []).includes(s.key));
  function script(w) {
    const r = subnet(netuid), c = ctx(w);
    const lines = ["#!/usr/bin/env bash", `# SN${netuid}${r ? " " + r.name : ""}: wallet ${c.wallet}, hotkey ${c.hotkey}, ${c.network} (AXoR runbook)`, "set -e"];
    if (rb.prefix) lines.push("", fill(rb.prefix, c));
    visible(w).forEach((s, i) => lines.push("", `# ${i + 1}. ${s.title}`, ...(s.note ? [`#    ${s.note}`] : []), ...s.cmds));
    return lines.join("\n") + "\n";
  }
  function runbookView(w) {
    if (!rb) return Loading.line("Loading runbook…");
    if (rb.error) return `<div class="sl-err">${icon("alert")}${esc(rb.error)}</div>`;
    const subs = [...(S.data?.subnets || [])].sort((a, b) => a.netuid - b.netuid);
    const mine = new Set([...Workspace.subnets().map(s => s.netuid), ...(w.stake || []).map(p => p.netuid)]);
    const opt = r => `<option value="${r.netuid}" ${r.netuid === +netuid ? "selected" : ""}>SN${r.netuid} · ${esc(r.name)}</option>`;
    const r = subnet(netuid), c = ctx(w), hks = [...new Set([...w.hotkeys.map(h => h.name), c.hotkey])];
    const fact = (label, v, cls = "") => `<div><span>${label}</span><b class="${cls}">${v}</b></div>`;
    return `<div class="src-filters wl-rb-bar">
        <select data-rb="netuid" aria-label="Subnet">${mine.size ? `<optgroup label="Yours">${subs.filter(x => mine.has(x.netuid)).map(opt).join("")}</optgroup><optgroup label="All subnets">` : ""}${subs.map(opt).join("")}${mine.size ? "</optgroup>" : ""}</select>
        <span class="spacer"></span>
        <button type="button" class="btn sm" data-rb-act="copy">${icon("copy")}Copy all</button>
        <button type="button" class="btn sm" data-rb-act="download">${icon("download")}.sh</button>
        <button type="button" class="btn sm" data-rb-act="note">${icon("note")}Save to notes</button></div>
      <div class="wl-pad wl-rb">
      ${r ? `<div class="mini wl-facts">${fact("Registration", tao(r.reg_cost))}${fact("UID", r.uid_available ? "Available" : "Not available", r.uid_available ? "ok" : "no")}
        ${fact("Slots", `${r.num_uids}/${r.max_uids}`)}${fact("Immunity", `${fmtNum(r.immunity_hours, 0)}h`)}${fact("Alpha price", `${amt(r.price, "tao", { digits: 5 })}<span class="faint"> / α</span>`)}${fact("Risk", RISK[r.risk_level || "clear"].label)}</div>` : ""}
      <div class="wl-form">
        <label class="in"><span>Hotkey</span><select data-rb="hotkey">${hks.map(h => `<option ${h === c.hotkey ? "selected" : ""}>${esc(h)}</option>`).join("")}</select></label>
        <div class="in"><span>Network</span><div class="seg">${d.networks.map(n => `<button type="button" data-rb-net="${n}" aria-pressed="${c.network === n}">${n}</button>`).join("")}</div></div>
        <label class="in"><span>Stake amount (τ)</span><input data-rb="amount" type="number" min="0" step="0.1" inputmode="decimal" value="${rb.amount ?? ""}" placeholder="e.g. 0.5"></label>
        <label class="in wl-wide"><span>Run first <em class="opt">optional, e.g. activate a venv</em></span><input data-rb="prefix" value="${esc(rb.prefix || "")}" placeholder="source ~/btcli-venv/bin/activate" spellcheck="false" autocomplete="off"></label>
      </div>
      <div class="wl-chips"><span class="faint small">Steps</span>${STEPS.map(([k, label]) => `<button type="button" class="chip" data-rb-step="${k}" aria-pressed="${!(rb.hidden || []).includes(k)}">${label}</button>`).join("")}
        <span class="spacer"></span><button type="button" class="btn sm" data-rb-act="add-step">${icon("plus")}Add step</button></div>
      <div id="wl-rb-steps">${stepsHtml(w)}</div>
      <p class="faint small">▶ runs a step in the Terminal tab: reads run there, and stake commands open the wallet's sheet for your browser wallet to sign. Other commands that sign run on your own machine. In your own steps, <code>{${VARS.join("}</code> <code>{")}}</code> are filled in. Saved per subnet${rb.updated ? ` · ${ago(rb.updated)}` : ""}.</p></div>`;
  }
  function stepsHtml(w) {
    const c = ctx(w), list = visible(w);
    return `${rb.prefix ? cmdBox(fill(rb.prefix, c)) : ""}
      <ol class="wl-steps">${list.map((s, i) => `<li class="wl-step ${s.done && !s.custom ? "done" : ""} ${s.warn ? "warn" : ""}">
          <div class="wl-step-head"><span class="wl-n">${s.done && !s.custom ? icon("check") : i + 1}</span><b>${esc(s.title)}</b>
            ${s.status ? `<span class="badge ${s.warn ? "caution" : s.done ? "clear" : "new"}">${esc(s.status)}</span>` : ""}<span class="spacer"></span>
            ${s.custom ? `<button type="button" class="iconbtn sm" data-rb-up="${s.i}" title="Move up" aria-label="Move up" ${s.i ? "" : "disabled"}>${icon("up")}</button>
              <button type="button" class="iconbtn sm" data-rb-edit="${s.i}" title="Edit step" aria-label="Edit step">${icon("edit")}</button>
              <button type="button" class="iconbtn sm danger-text" data-rb-del="${s.i}" title="Delete step" aria-label="Delete step">${icon("trash")}</button>` : ""}</div>
          ${s.note ? `<p class="muted small">${colorize(esc(s.note))}</p>` : ""}
          ${s.cmds.map(cmdBox).join("")}
          ${s.quote ? `<p class="small wl-quote" id="wl-quote">${quoteText()}</p>` : ""}</li>`).join("")}</ol>`;
  }
  const cmdBox = cmd => `<div class="wl-cmd"><code>${esc(cmd)}</code>${runnable(cmd) ? `<button type="button" class="iconbtn sm" data-wl-run="${esc(cmd)}" title="Run in the Terminal tab" aria-label="Run in the terminal">${icon("play")}</button>` : ""}${copyBtn(cmd)}</div>`;
  // what the terminal can take: reads, --dry-run previews, and the commands that open a wallet sheet
  const runnable = cmd => !/[<>]/.test(cmd) && (/^btcli (wallet (list|balance|overview|inspect)|stake (list|show)|subnets (show|list|price|burn-cost|metagraph))\b/.test(cmd)
    || / --dry-run\b/.test(cmd) || /^btcli (stake (add|remove|move|unstake-all)|wallet transfer)\b/.test(cmd));

  // ---------- terminal ----------
  const TCLS = new Set(["b", "addr", "ok", "no", "warn", "faint"]);
  function seg(x) {
    if (x == null || x === "") return "";
    if (typeof x === "string") return esc(x);
    if (Array.isArray(x)) return x.map(seg).join("");
    if ("n" in x) return amt(x.n, ["tao", "alpha", "usd"].includes(x.u) ? x.u : "tao", { priv: !!x.p });
    return `<span class="${TCLS.has(x.c) ? "t-" + x.c : ""}">${esc(x.s)}</span>`;
  }
  const tline = l => Array.isArray(l) ? `<div class="wl-tl">${seg(l)}</div>`
    : `<div class="wl-tt"><table>${l.head.some(h => h) ? `<thead><tr>${l.head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>` : ""}
        <tbody>${l.rows.map(r => `<tr>${r.map(c => `<td>${seg(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const ansi = t => ansiHtml(t);  // btcli's colours and links (app.js, loaded after this file)
  const prompt = () => `${esc(cur()?.name || "scout")}@${esc(termInfo?.network && termInfo.network.length < 16 ? termInfo.network : "finney")}`;
  const tentry = e => `<div class="wl-te is-${e.res?.status || "busy"}"><div class="wl-tc"><span class="wl-ps" aria-hidden="true">${esc(e.who || "")} $</span><span>${esc(e.cmd)}</span>
        ${e.res?.took != null ? `<span class="wl-took">${e.res.took}s</span>` : ""}${!e.res ? `<span class="wl-took">running…</span>` : ""}</div>
      ${e.res ? (e.res.ansi != null ? `<pre class="wl-ansi">${ansi(e.res.ansi)}</pre>` : "") + (e.res.lines || []).map(tline).join("") : `<div class="wl-tl faint"><span class="wl-spin" aria-hidden="true"></span>Running btcli…</div>`}
      ${e.res?.copy ? `<div class="wl-tl">${copyBtn(e.res.copy, "Copy for your terminal")}</div>` : ""}
      ${e.after ? `<div class="wl-tl">${e.after}</div>` : ""}</div>`;
  const QUICK = ["btcli wallet balance", "btcli stake list", "btcli wallet overview", "btcli subnets list", "btcli subnets show 19", "btcli wallet history", "btcli query --help", "help"];
  function terminalView(w) {
    const masked = hidden && !reveal;
    return `<section class="wl-term wx-term ${termMax ? "max" : ""} ${masked ? "masked" : ""}" aria-label="btcli terminal">
      <div class="wl-term-head">${icon("terminal")}<b>btcli</b><span class="badge clear" title="Your wallets are here as public keys only: nothing can sign">read-only</span>
        <span class="faint small">${esc(termInfo?.network || d.network || "finney")} · wallets as public keys · -w defaults to ${esc(w.name)}</span><span class="spacer"></span>
        <button type="button" class="iconbtn sm" data-wl="term-copy" title="Copy the output" aria-label="Copy the output">${icon("copy")}</button>
        <button type="button" class="iconbtn sm" data-wl="term-clear" title="Clear (Ctrl+L)" aria-label="Clear">${icon("trash")}</button>
        <button type="button" class="iconbtn sm" data-wl="term-max" title="${termMax ? "Exit full screen" : "Full screen"}" aria-label="${termMax ? "Exit full screen" : "Full screen"}" aria-pressed="${termMax}">${icon(termMax ? "shrink" : "expand")}</button></div>
      <div class="wl-term-out" id="wl-term-out" role="log" aria-live="polite">${term.length ? term.map(tentry).join("") : `<div class="wl-tl wl-welcome"><b>btcli ${esc(termInfo?.version || "")}</b> runs here read-only, with your tracked wallets as public keys.
        Type <b>help</b>, or try a command below. Stake, unstake, move and transfer commands open the wallet's sheet: your browser wallet signs.</div>`}</div>
      ${masked ? `<button type="button" class="wl-reveal" data-wl="term-reveal">${icon("eye")}Amounts are hidden: show the terminal</button>` : ""}
      <div class="wl-quick">${QUICK.map(q => `<button type="button" class="chip" data-wl-run="${esc(q)}">${esc(q.replace(/^btcli /, ""))}</button>`).join("")}</div>
      <form class="wl-term-in" id="wl-term-form" autocomplete="off"><span class="wl-ps" aria-hidden="true">${prompt()} $</span>
        <input id="wl-term-input" aria-label="btcli command" placeholder="btcli wallet balance" spellcheck="false" autocapitalize="none" autocomplete="off" maxlength="500" ${busy ? "disabled" : ""}></form>
      <span class="wl-measure" aria-hidden="true">0000000000</span></section>`;
  }
  async function loadTermInfo() { if (!termInfo) { try { termInfo = await api("/api/wallet/term"); } catch { termInfo = { commands: {}, flags: [] }; } } }
  function drawTerm(focus) {
    const out = $("#wl-term-out"); if (!out) return;
    out.innerHTML = term.map(tentry).join("") || `<div class="wl-tl faint">Cleared.</div>`;
    out.scrollTop = out.scrollHeight;
    const i = $("#wl-term-input"); if (i) { i.disabled = busy; if (focus && !busy) i.focus(); }
    const ps = $("#wl-term-form .wl-ps"); if (ps) ps.textContent = `${cur()?.name || "scout"}@${termInfo?.network && termInfo.network.length < 16 ? termInfo.network : "finney"} $`;
  }
  // the terminal's width in characters, so btcli lays its tables out to fit
  function cols() {
    const out = $("#wl-term-out"), m = $(".wl-measure");
    if (!out || !m) return 110;
    return Math.max(40, Math.floor((out.clientWidth - 28) / (m.getBoundingClientRect().width / 10)));
  }
  async function runCmd(cmd) {
    cmd = cmd.trim(); if (!cmd || busy) return;
    if (tab !== "terminal") setTab("terminal");
    if (hist[hist.length - 1] !== cmd) hist.push(cmd);
    hist = hist.slice(-100); hi = hist.length; store.set("wallet.hist", hist);
    if (cmd === "clear" || cmd === "cls") { term = []; return drawTerm(true); }
    const w = cur(), e = { cmd, who: prompt() }; term.push(e); term = term.slice(-60); busy = true; drawTerm();
    try { e.res = await api("/api/wallet/term", { method: "POST", body: { line: cmd, wallet_id: sel, cols: cols() } }); }
    catch (err) { e.res = { status: "error", lines: [[err.message]] }; }
    busy = false; drawTerm(true);
    if (e.res.status === "sign") sign(e, w);
  }
  // a command that signs: the wallet's sheet, filled in from it; the outcome is printed under the command
  function sign(e, w) {
    const a = e.res.action, wallet = d.wallets.find(x => x.id === a.wallet_id) || w;
    const note = html => { e.after = html; drawTerm(true); };
    WalletTx.start(a.op, wallet, a.preset, async res => {
      note(res.ok ? `<span class="t-ok">✓ ${esc(res.detail || "Done")}</span>${res.extrinsic_id ? ` <span class="t-faint">· ${esc(res.extrinsic_id)}</span>` : ""}${res.explorer_url ? ` <a href="${esc(res.explorer_url)}" target="_blank" rel="noopener noreferrer">explorer ↗</a>` : ""}`
        : `<span class="t-no">✗ ${esc(res.error || "It didn't go through.")}</span>`);
      await after(res);
    }, { review: true, cancel: why => { if (!e.after) note(`<span class="t-faint">Closed without sending.</span>${why ? `<br><span class="t-no">✗ ${esc(why)}</span>` : ""}`); } });
  }
  // Tab: complete the word under the caret from btcli's commands and flags, or list the choices
  function complete(input) {
    if (!termInfo) return;
    const v = input.value, words = v.split(/\s+/), last = words.pop() || "", at = words.length;
    const cands = at === 0 ? ["btcli", "help", "clear"] : words[0] !== "btcli" ? [] : at === 1 ? Object.keys(termInfo.commands)
      : at === 2 && !last.startsWith("-") ? termInfo.commands[words[1]] || [] : termInfo.flags;
    const hits = cands.filter(c => c.startsWith(last));
    if (!hits.length) return;
    let common = hits[0];
    for (const h of hits) while (!h.startsWith(common)) common = common.slice(0, -1);
    if (hits.length === 1) input.value = [...words, hits[0]].join(" ") + " ";
    else if (common.length > last.length) input.value = [...words, common].join(" ");
    else { term.push({ cmd: v, who: prompt(), res: { status: "ok", lines: [[{ s: hits.join("   "), c: "faint" }]] } }); drawTerm(true); }
  }

  function stepModal(i) {
    const s = i == null ? { title: "", cmd: "" } : rb.steps[i];
    const f = Auth.modal(`<div class="src-dlg"><h3>${icon("terminal")}${i == null ? "Add a step" : "Edit step"}</h3>
      <p class="muted">For anything btcli doesn't cover on SN${netuid}: an upload, a miner start command, a check. Use <code>{wallet}</code>, <code>{hotkey}</code>, <code>{netuid}</code>, <code>{network}</code>, <code>{amount}</code>, <code>{coldkey}</code> or <code>{hotkey_ss58}</code>.</p>
      <label class="in"><span>Title</span><input name="title" maxlength="120" value="${esc(s.title)}" placeholder="Upload the tested agent"></label>
      <label class="in"><span>Command <em class="opt">one per line</em></span><textarea name="cmd" rows="4" maxlength="2000" spellcheck="false" class="wl-ta" placeholder="ridges upload --file agent.py --coldkey-name {wallet} --hotkey-name {hotkey}">${esc(s.cmd)}</textarea></label>
      <p class="fine">${icon("lock")}Don't put passwords, seed phrases or keys in a step.</p></div>`, async f => {
      const step = { title: f.elements.title.value.trim(), cmd: f.elements.cmd.value.trim() };
      if (!step.cmd) throw new Error("Enter a command.");
      const prev = rb.steps || [];
      rb.steps = i == null ? [...prev, step] : prev.map((x, j) => j === i ? step : x);
      try { rb.updated = (await api(`/api/wallet/runbook/${netuid}`, { method: "PUT", body: body() })).updated; }
      catch (e) { rb.steps = prev; throw e; }
      $("#modal").close(); renderBody();
    }, { submit: i == null ? "Add step" : "Save" });
    f.elements.title.focus();
  }

  // ---------- wallet form ----------
  function walletModal(w, extra) {
    const hks = [...(w?.hotkeys || []), ...(extra ? [{ name: "", ss58: extra }] : [])];
    const row = h => `<div class="wl-hk"><input name="hk_name" maxlength="32" value="${esc(h.name)}" placeholder="default" aria-label="Hotkey name" autocapitalize="none" spellcheck="false">
      <input name="hk_ss58" value="${esc(h.ss58)}" placeholder="5… hotkey address" aria-label="Hotkey address" spellcheck="false" autocomplete="off">
      <button type="button" class="iconbtn sm" data-hk-rm aria-label="Remove hotkey">${icon("close")}</button></div>`;
    const f = Auth.modal(`<div class="src-dlg"><h3>${icon("wallet")}${w ? "Edit wallet" : "Add wallet"}</h3>
      <div class="notice">${icon("lock")}<div>Only <b>public addresses</b> (they start with 5). Never paste a recovery phrase or key file here or anywhere online.</div></div>
      <label class="in"><span>Wallet name <em class="opt">as in btcli -w</em></span><input name="name" maxlength="32" value="${esc(w?.name || "")}" placeholder="miner" required autocapitalize="none" spellcheck="false"></label>
      <label class="in"><span>Coldkey address</span><input name="coldkey" value="${esc(w?.coldkey || "")}" placeholder="5…" required spellcheck="false" autocomplete="off"></label>
      <div class="in"><span>Hotkeys <em class="opt">name as in btcli -H, and address</em></span><div id="wl-hks">${hks.map(row).join("")}</div>
        <button type="button" class="btn sm" id="wl-hk-add">${icon("plus")}Add hotkey</button></div>
      <label class="in"><span>Note <em class="opt">optional</em></span><input name="note" maxlength="300" value="${esc(w?.note || "")}" placeholder="Ridges miner"></label>
      <p class="fine">Run <code>btcli wallet list</code> on your machine to see the addresses.</p></div>`, async f => {
      const names = $$("[name=hk_name]", f), addrs = $$("[name=hk_ss58]", f);
      const hotkeys = names.map((n, i) => ({ name: n.value.trim(), ss58: addrs[i].value.trim() })).filter(h => h.name || h.ss58);
      const body = { name: f.elements.name.value.trim(), coldkey: f.elements.coldkey.value.trim(), hotkeys, note: f.elements.note.value.trim() };
      d = await api(w ? `/api/wallet/${w.id}` : "/api/wallet", { method: w ? "PUT" : "POST", body });
      if (!w) sel = d.wallets[d.wallets.length - 1]?.id ?? sel;
      store.set("wallet.sel", sel); $("#c-wallet").textContent = d.wallets.length || "";
      $("#modal").close(); render(); toast(w ? "Wallet saved" : "Wallet added");
    }, { submit: w ? "Save" : "Add wallet" });
    const box = $("#wl-hks", f);
    if (!hks.length) box.innerHTML = row({ name: "default", ss58: "" });
    $("#wl-hk-add", f).onclick = () => box.insertAdjacentHTML("beforeend", row({ name: "", ss58: "" }));
    box.onclick = e => { if (e.target.closest("[data-hk-rm]")) e.target.closest(".wl-hk").remove(); };
    (extra ? $$("[name=hk_name]", f).pop() : f.elements.name).focus();
  }

  // ---------- events ----------
  async function untrack(w) {
    if (!await UI.confirm({ title: `Stop tracking “${esc(w.name)}”?`, body: "It and its hotkeys leave your wallets here. Nothing changes on chain: the coins stay where they are, and its runbooks stay. You can track it again with its address.", ok: "Stop tracking", icon: "wallet" })) return;
    try { d = await api(`/api/wallet/${w.id}`, { method: "DELETE" }); } catch (err) { return toast(err.message); }
    sel = d.wallets[0]?.id ?? null; $("#c-wallet").textContent = d.wallets.length || ""; render();
    toast(`Stopped tracking ${w.name}`);
  }
  async function copy(text, msg = "Copied") { try { await navigator.clipboard.writeText(text); toast(msg); } catch { toast("Couldn't copy"); } }
  function wire() {
    if (wired) return; wired = true;
    const box = $("#wallet");
    box.addEventListener("click", async e => {
      const t = e.target.closest("button, a"); if (!t || t.tagName === "A") return;
      const w = cur(), ds = t.dataset;
      if (ds.wlCopy != null) return copy(ds.wlCopy);
      if (ds.wxOp) { e.stopPropagation(); return action(ds.wxOp, { netuid: ds.netuid != null ? +ds.netuid : undefined, hotkey: ds.hotkey }); }
      if (ds.wl === "connect") { e.stopPropagation(); return document.querySelector(".wx-conn") ? document.querySelector(".wx-conn").remove() : WalletTx.connectMenu(t, { tracked: d.wallets, onTrack: track }); }
      if (ds.wl === "more") {
        e.stopPropagation();
        const k = await menu(t, [["unstake_all", "minus", "Unstake all from a hotkey"], ["runbook", "terminal", "Subnet runbook (btcli)"], ["edit", "edit", "Edit wallet"]]);
        if (k === "unstake_all") return w.stake?.length ? action("unstake_all") : toast("This wallet has no stake yet");
        if (k === "runbook") return setTab("runbook");
        if (k === "edit") return walletModal(w);
        return;
      }
      if (ds.wl === "menu") {
        e.stopPropagation();
        const k = await menu(t, [["edit", "edit", "Edit name, hotkeys and note"], ["copy", "copy", "Copy coldkey address"], ["delete", "trash", "Stop tracking", true]]);
        if (k === "edit") return walletModal(w);
        if (k === "copy") return copy(w.coldkey);
        if (k === "delete") return untrack(w);
        return;
      }
      if (ds.wlRun != null) return runCmd(ds.wlRun);
      if (ds.wl === "term-clear") { term = []; return drawTerm(true); }
      if (ds.wl === "term-max") { termMax = !termMax; return renderBody(); }
      if (ds.wl === "term-reveal") { reveal = true; return renderBody(); }
      if (ds.wl === "term-copy") { const out = $("#wl-term-out"); return copy(out ? out.innerText : "", "Output copied"); }
      if (ds.wallet) return pick(ds.wallet);
      if (ds.tab) return setTab(ds.tab);
      if (ds.runbook) { netuid = +ds.runbook; store.set("wallet.netuid", netuid); rb = null; quote = null; return setTab("runbook"); }
      if (ds.nameHk) return walletModal(w, ds.nameHk);
      if (ds.wl === "hide") { hidden = !hidden; reveal = false; store.set("wallet.hide", hidden); return render(); }
      if (ds.wl === "add") return walletModal(null);
      if (ds.wl === "edit") return walletModal(w);
      if (ds.wl === "refresh") { t.classList.add("loading"); await load(true); t.classList.remove("loading"); render(); return toast("Read from chain"); }
      if (ds.wl === "delete") return untrack(w);
      if (!rb) return;
      if (ds.rbNet) { rb.network = ds.rbNet; save(); return renderBody(); }
      if (ds.rbStep) { const h = new Set(rb.hidden || []); h.has(ds.rbStep) ? h.delete(ds.rbStep) : h.add(ds.rbStep); rb.hidden = [...h]; save(); return renderBody(); }
      if (ds.rbEdit != null) return stepModal(+ds.rbEdit);
      if (ds.rbDel != null) { if (!await UI.confirm({ title: "Delete this step?", body: "It leaves this runbook. This can't be undone.", items: [esc(rb.steps[+ds.rbDel]?.title || rb.steps[+ds.rbDel]?.cmd || "")].filter(Boolean) })) return; rb.steps = rb.steps.filter((_, i) => i !== +ds.rbDel); save(); return renderBody(); }
      if (ds.rbUp != null) { const i = +ds.rbUp, s = [...rb.steps]; [s[i - 1], s[i]] = [s[i], s[i - 1]]; rb.steps = s; save(); return renderBody(); }
      if (ds.rbAct === "add-step") return stepModal(null);
      if (ds.rbAct === "copy") return copy(script(w), "Runbook copied");
      if (ds.rbAct === "download") {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([script(w)], { type: "text/x-shellscript" })); a.download = `sn${netuid}-${w.name}.sh`; a.click();
        return;
      }
      if (ds.rbAct === "note") {
        const r = subnet(netuid), text = `## SN${netuid}${r ? " " + r.name : ""} runbook (${w.name})\n\n\`\`\`\n${script(w)}\`\`\``;
        try { await api("/api/workspace/notes", { method: "POST", body: { text: text.slice(0, 4000), netuid: +netuid, color: "blue" } }); toast("Saved to notes"); }
        catch (err) { toast(err.message); }
      }
    });
    box.addEventListener("submit", e => {
      if (e.target.id !== "wl-term-form") return;
      e.preventDefault(); const i = $("#wl-term-input"), v = i.value; i.value = ""; runCmd(v);
    });
    box.addEventListener("keydown", e => {
      if (e.target.id !== "wl-term-input") return;
      if (e.key === "Tab") { e.preventDefault(); return complete(e.target); }
      if (e.key === "l" && e.ctrlKey) { e.preventDefault(); term = []; return drawTerm(true); }
      if (e.key === "Escape") { if (termMax) { termMax = false; return renderBody(); } e.target.value = ""; return; }
      if (!["ArrowUp", "ArrowDown"].includes(e.key) || !hist.length) return;
      e.preventDefault(); hi = Math.max(0, Math.min(hist.length, hi + (e.key === "ArrowUp" ? -1 : 1)));
      e.target.value = hist[hi] ?? "";
    });
    box.addEventListener("change", e => {
      const k = e.target.dataset.rb; if (!k || !rb) return;
      if (k === "netuid") { netuid = +e.target.value; store.set("wallet.netuid", netuid); rb = null; quote = null; renderBody(); return loadRunbook(); }
      if (k === "hotkey") { rb.hotkey = e.target.value; save(); renderBody(); }
    });
    box.addEventListener("input", e => {
      const k = e.target.dataset.rb; if (!k || !rb) return;
      if (k === "amount") { const v = parseFloat(e.target.value); rb.amount = v > 0 ? v : null; save(); getQuote(); refreshCmds(); }
      if (k === "prefix") { rb.prefix = e.target.value; save(); refreshCmds(); }
    });
  }
  // while typing, redraw only the commands so the input keeps its focus and caret
  function refreshCmds() { const el = $("#wl-rb-steps"), w = cur(); if (el && w) el.innerHTML = stepsHtml(w); }
  const button = (n, cls = "btn sm") => Auth.me() ? `<button type="button" class="${cls}" data-wl-runbook="${n}" title="btcli commands to register and stake on this subnet">${icon("wallet")}Wallet</button>` : "";

  return { init, open, openSubnet, onData, button, taoUsd: () => d?.tao_usd };
})();
