/* Wallet transactions, signed in your browser wallet (Talisman, SubWallet, Polkadot.js, Bittensor Wallet).
   - Connect: the extensions the browser injects (window.injectedWeb3) are enabled for this site and their accounts
     listed; a tracked wallet can sign when its coldkey is one of them (matched by public key, so any SS58 prefix).
   - Sheets: Send, Receive, Stake, Unstake, Move stake and Unstake all. Each goes form → review (the server checks
     balances and positions, quotes the swap and estimates the fee) → your wallet's own confirmation → the block.
     The review always offers the btcli command instead. Nothing here sees a key: the extension signs the payload
     the server prepared, and the server submits the signature. */
const WalletTx = (() => {
  const KNOWN = {
    talisman: ["Talisman", "https://talisman.xyz"], "subwallet-js": ["SubWallet", "https://subwallet.app"],
    "polkadot-js": ["Polkadot.js", "https://polkadot.js.org/extension/"], bittensor: ["Bittensor Wallet", "https://bittensor.com/wallet"],
  };
  const APP = "AXoR";
  const OPS = {
    send: ["Send", "send", "Send TAO to another address"], receive: ["Receive", "download", "Your address"],
    stake: ["Stake", "plus", "Stake TAO with a validator on a subnet"], unstake: ["Unstake", "minus", "Turn alpha back into TAO"],
    move: ["Move", "swap", "Move stake to another validator or subnet"], unstake_all: ["Unstake all", "minus", "Everything staked with one hotkey"],
  };
  const SLIPS = [0.5, 1, 2, 5];
  let ext = {}, accts = [], onChange = () => {}, sheet = null, vcache = {}, ending = null;
  const pref = (k, v) => store[v === undefined ? "get" : "set"]("wallet." + k, v);
  // Wallet extensions call crypto.randomUUID, which browsers only offer on HTTPS (or localhost) pages: on plain HTTP
  // it's missing and connecting fails. A version 4 UUID from crypto.getRandomValues (offered everywhere) stands in.
  if (window.crypto?.getRandomValues && typeof crypto.randomUUID !== "function") {
    crypto.randomUUID = () => {
      const b = crypto.getRandomValues(new Uint8Array(16));
      b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
      const h = [...b].map(x => x.toString(16).padStart(2, "0")).join("");
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    };
  }
  const insecure = () => window.isSecureContext === false;
  const insecureNote = () => insecure() ? `<p class="wx-note wx-insecure">${icon("alert")}<span>This page isn't on HTTPS, so your sign-in and wallet traffic cross the network unencrypted and some wallets refuse to connect. Put AXoR behind HTTPS (see the README) before moving real funds.</span></p>` : "";

  // ---------- addresses ----------
  const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  // the 32-byte public key inside an SS58 address (hex), or null; prefixes below 64 are one byte. Some wallets
  // hand over the bare public key (0x + 64 hex) instead.
  function pub(addr) {
    if (typeof addr === "string" && /^0x[0-9a-f]{64}$/i.test(addr)) return addr.slice(2).toLowerCase();
    if (typeof addr !== "string" || !/^[1-9A-HJ-NP-Za-km-z]{46,48}$/.test(addr)) return null;
    let n = 0n; for (const c of addr) n = n * 58n + BigInt(B58.indexOf(c));
    const hex = n.toString(16).padStart(70, "0");
    return hex.length === 70 && parseInt(hex.slice(0, 2), 16) < 64 ? hex.slice(2, 66) : null;
  }
  const short = a => a && a.length > 12 ? `${a.slice(0, 5)}…${a.slice(-4)}` : a || "";
  // a two-colour avatar from the address, like the identicons wallets show
  function avatar(addr, size = "") {
    let h = 2166136261; for (const c of addr || "") h = Math.imul(h ^ c.charCodeAt(0), 16777619);
    const a = (h >>> 0) % 360, b = (a + 40 + ((h >>> 9) % 160)) % 360;
    return `<span class="wx-av ${size}" style="--h1:${a};--h2:${b}" aria-hidden="true"></span>`;
  }
  const UNIT = { tao: "τ", alpha: "α", usd: "$" };
  function amt(x, unit = "tao", digits) {
    if (x == null || isNaN(x)) return `<span class="faint">–</span>`;
    if (unit === "usd") return `<span class="amt amt-usd">${esc(usd(x))}</span>`;
    return `<span class="amt amt-${unit}" title="${esc(String(+(+x).toFixed(9)))}">${esc(fmtNum(x, digits))}<span class="u">${UNIT[unit]}</span></span>`;
  }
  const tusd = () => S.data?.tao_usd || Wallet.taoUsd?.() || null;

  // ---------- browser wallets ----------
  const injected = () => window.injectedWeb3 || {};
  const label = id => KNOWN[id]?.[0] || id.replace(/[-_]js$/, "").replace(/[-_]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  async function enable(id) {
    const src = injected()[id]; if (!src?.enable) throw new Error(`${label(id)} isn't available in this browser.`);
    const inj = await src.enable(APP);
    // every substrate account the wallet shares with this page (EVM accounts can't sign these transactions)
    const take = l => { accts = [...accts.filter(a => a.source !== id), ...(l || []).filter(a => a.type !== "ethereum")
      .map(a => ({ address: a.address, name: a.name || short(a.address), type: a.type || "sr25519", source: id, pub: pub(a.address) }))]; };
    const list = await inj.accounts.get();
    ext[id] = inj; take(list);
    inj.accounts.subscribe?.(l => { take(l); onChange(); });
    pref("ext", [...new Set([...(pref("ext") || []), id])]);
    return accts.filter(a => a.source === id).length;
  }
  // reconnect the extensions you connected before (they remember the permission, so no popup)
  async function init(cb) {
    onChange = cb || onChange;
    const want = pref("ext") || [];
    if (!want.length) return;
    for (let i = 0; i < 6 && !want.some(id => injected()[id]); i++) await new Promise(r => setTimeout(r, 250));  // extensions inject after load
    for (const id of want) if (injected()[id]) { try { await enable(id); } catch {} }
    onChange();
  }
  function disconnect(id) {
    delete ext[id]; accts = accts.filter(a => a.source !== id);
    pref("ext", (pref("ext") || []).filter(x => x !== id)); onChange();
  }
  const accounts = () => accts;
  const connected = () => Object.keys(ext);
  const signerFor = addr => { const p = pub(addr); return p && accts.find(a => a.pub === p) || null; };

  function connectMenu(btn, { tracked = [], onTrack } = {}) {
    document.querySelector(".wx-conn")?.remove();
    const pop = document.createElement("div"); pop.className = "popover wx-conn"; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "Browser wallets");
    const draw = (busy = "", error = "") => {
      const ids = Object.keys(injected());
      const trackedKeys = new Set(tracked.map(w => pub(w.coldkey)));
      pop.innerHTML = `<b class="cx-pop-h">Browser wallets <small class="faint">sign without giving AXoR a key</small></b>
        ${ids.length ? ids.map(id => `<div class="wx-ext ${ext[id] ? "on" : ""}"><span class="wx-ext-ico" aria-hidden="true">${esc(label(id)[0])}</span>
            <span class="wx-ext-name"><b>${esc(label(id))}</b><small class="faint">${ext[id] ? `${accts.filter(a => a.source === id).length} account${accts.filter(a => a.source === id).length === 1 ? "" : "s"} connected` : "Detected"}</small></span>
            ${ext[id] ? `<button type="button" class="btn sm" data-wx-off="${esc(id)}">Disconnect</button>` : `<button type="button" class="btn sm primary ${busy === id ? "loading" : ""}" data-wx-on="${esc(id)}">Connect</button>`}</div>`).join("")
          : `<p class="mp-note">No wallet extension found in this browser. Install one, create or import your coldkey there, then reload this page.</p>
             <div class="wx-get">${["talisman", "subwallet-js", "polkadot-js"].map(id => `<a class="btn sm" href="${KNOWN[id][1]}" target="_blank" rel="noopener noreferrer">${icon("external")}${KNOWN[id][0]}</a>`).join("")}</div>`}
        ${error ? `<p class="mp-note no">${esc(error)}</p>` : ""}
        ${accts.length ? `<div class="cx-use-h">Accounts</div><ul class="wx-accts">${accts.map(a => `<li>${avatar(a.address, "sm")}<span><b>${esc(a.name)}</b><small class="faint">${esc(short(a.address))} · ${esc(label(a.source))}</small></span>
            ${trackedKeys.has(a.pub) ? `<span class="badge clear" title="Tracked here and can sign">${icon("check")}Tracked</span>` : onTrack ? `<button type="button" class="btn sm" data-wx-track="${esc(a.address)}">${icon("plus")}Track</button>` : ""}</li>`).join("")}</ul>` : ""}
        ${insecureNote()}
        <p class="mp-note">${icon("lock")} Your browser wallet keeps the keys and shows every transaction before you approve it. AXoR only sees public addresses.</p>`;
    };
    pop.onclick = async e => {
      e.stopPropagation();
      const on = e.target.closest("[data-wx-on]"), off = e.target.closest("[data-wx-off]"), tr = e.target.closest("[data-wx-track]");
      if (on) { draw(on.dataset.wxOn); try { const n = await enable(on.dataset.wxOn); toast(`${label(on.dataset.wxOn)} connected: ${n} account${n === 1 ? "" : "s"}`); onChange(); draw(); } catch (err) { draw("", err.message || String(err)); } }
      if (off) { disconnect(off.dataset.wxOff); draw(); }
      if (tr) { const a = accts.find(x => x.address === tr.dataset.wxTrack); if (a) await onTrack(a); draw(); }
    };
    draw();
    document.body.appendChild(pop);
    const b = btn.getBoundingClientRect();
    pop.style.top = (b.bottom + scrollY + 8) + "px";
    pop.style.left = Math.max(16, Math.min(b.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 16)) + "px";
    setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.isConnected) return document.removeEventListener("click", off); if (!pop.contains(e.target) && !e.target.closest("[data-wx-connect]")) { pop.remove(); document.removeEventListener("click", off); } }), 0);
    pop.addEventListener("keydown", e => { if (e.key === "Escape") { pop.remove(); btn.focus(); } });
  }

  // ---------- the sheet ----------
  function dialog() {
    let d = $("#wx-sheet");
    if (!d) { d = document.createElement("dialog"); d.id = "wx-sheet"; d.className = "modal wx-sheet"; document.body.appendChild(d); }
    return d;
  }
  /* op: send | receive | stake | unstake | move | unstake_all; w: a wallet from /api/wallet; preset: {netuid, hotkey, ...} */
  /* opts.review: go straight to the review when the preset fills the form (the terminal's commands);
     opts.cancel: called when the sheet closes without a transaction */
  function start(op, w, preset = {}, done = () => {}, opts = {}) {
    if (!w || w.error) return toast(w?.error || "Pick a wallet first");
    const pos = w.stake || [];
    sheet = { op, w, done, step: "form", busy: "", error: "", review: null, result: null, showCmd: false, keep: new Set(["hotkey", "dest_hotkey"].filter(k => preset[k])),
              f: { netuid: preset.netuid ?? null, hotkey: preset.hotkey || null, dest_netuid: preset.dest_netuid ?? null, dest_hotkey: preset.dest_hotkey || null,
                   dest: preset.dest || "", amount: preset.amount != null ? String(preset.amount) : "", all: !!preset.all,
                   slippage: preset.slippage || pref("slippage") || 1, custom: false } };
    const f = sheet.f;
    if ((op === "unstake" || op === "move") && preset.netuid != null && preset.hotkey && !pos.some(p => p.netuid === preset.netuid && p.hotkey === preset.hotkey))
      sheet.error = `${w.name} has no stake on SN${preset.netuid} with ${short(preset.hotkey)}: pick a position.`;
    if (op === "stake" && f.netuid == null) f.netuid = Workspace.subnets?.()[0]?.netuid ?? pos.find(p => p.netuid)?.netuid ?? subnets()[0]?.netuid ?? 1;
    if (op === "unstake" || op === "move") {
      const p = (f.netuid != null && pos.find(p => p.netuid === f.netuid && (!f.hotkey || p.hotkey === f.hotkey))) || pos[0];
      if (!p) return toast("This wallet has no stake yet");
      f.netuid = p.netuid; f.hotkey = p.hotkey;
      if (op === "move") f.dest_netuid = f.dest_netuid ?? p.netuid;
    }
    if (op === "unstake_all") { const hks = [...new Set(pos.map(p => p.hotkey))]; if (!hks.length) return toast("This wallet has no stake yet"); f.hotkey = f.hotkey && hks.includes(f.hotkey) ? f.hotkey : hks[0]; }
    const d = dialog();
    // one sheet at a time: a sheet still open, or whose close event hasn't arrived yet, ends here; a close event that
    // arrives while the dialog is open again belongs to that earlier sheet and is ignored
    ending?.();
    const mine = sheet; let over = false;
    ending = () => { if (over) return; over = true; if (!mine.result) opts.cancel?.(stuck(mine)); if (sheet === mine) sheet = null; };
    d.onclick = click; d.oninput = input; d.onchange = change;
    d.onclose = () => { if (!d.open) ending?.(); };
    d.onkeydown = e => { if (e.key === "Enter" && e.target.matches("input") && sheet?.step === "form") { e.preventDefault(); next(); } };
    draw(); d.showModal();
    if (op === "stake") loadValidators(f.netuid, "netuid");
    if (op === "move") loadValidators(f.dest_netuid, "dest_netuid");
    setTimeout(() => d.querySelector("[data-wx-focus]")?.focus(), 30);
    if (opts.review && !sheet.error && canReview()) next();
  }
  // Why a sheet closed without sending, for whoever opened it (the terminal prints it); "" when nothing stood in the way
  function stuck(s) {
    const r = s.review;
    if (!r || !r.ok) return r?.blocks?.[0] || s.error || "";
    if (signerFor(r.wallet.coldkey)) return s.error || "";
    const exts = connected();
    return exts.length ? `None of your connected wallets holds ${r.wallet.name}'s coldkey ${r.wallet.coldkey}, so there was nothing to sign with. ${sharing(exts)} ${fixHint(exts)}`
      : "No browser wallet is connected, so there was nothing to sign with. Connect Talisman, SubWallet, Polkadot.js or the Bittensor wallet (Connect wallet, under Accounts), then run it again.";
  }
  // "Taostats shares 2 accounts with this page: main (5Dx…ab), …" for each connected wallet
  function sharing(exts, full = true) {
    return exts.map(id => {
      const l = accts.filter(a => a.source === id);
      return l.length ? `${label(id)} shares ${l.length} account${l.length === 1 ? "" : "s"} with this page: ${l.map(a => `${a.name} (${full ? a.address : short(a.address)})`).join(", ")}.`
        : `${label(id)} is connected but shares no accounts with this page.`;
    }).join(" ");
  }
  const fixHint = exts => `If the key is in ${exts.map(label).join(" or ")}, open its connected-sites settings, allow this site to see that account, then reload the page. Otherwise import the coldkey there, or run the command on a machine that has the key.`;
  const subnets = () => [...(S.data?.subnets || [])].sort((a, b) => a.netuid - b.netuid);
  const subName = n => n === 0 ? "Root" : S.data?.subnets?.find(r => r.netuid === n)?.name || sheet?.w.stake.find(p => p.netuid === n && p.subnet !== `SN${n}`)?.subnet || "";
  const snLabel = n => n === 0 ? "SN0 · Root" : `SN${n}${subName(n) ? ` · ${esc(subName(n))}` : ""}`;
  const priceOf = n => n === 0 ? 1 : S.data?.subnets?.find(r => r.netuid === n)?.price ?? null;
  const posOf = (n, hk) => sheet.w.stake.find(p => p.netuid === n && p.hotkey === hk);
  const hkName = hk => sheet.w.hotkeys.find(h => h.ss58 === hk)?.name || (vcache[sheet.f.netuid]?.validators || vcache[sheet.f.dest_netuid]?.validators || []).find(v => v.hotkey === hk)?.name
    || Object.values(vcache).flatMap(v => v.validators || []).find(v => v.hotkey === hk)?.name || short(hk);

  async function loadValidators(n, field) {
    if (n == null || isNaN(n)) return;
    if (!vcache[n] || vcache[n].error) {
      const p = api(`/api/wallet/validators?netuid=${n}`).then(v => { if (!v.takes) setTimeout(() => { delete vcache[n]; }, 15000); return v; }, e => ({ error: e.message, validators: [] }));
      vcache[n] = { loading: true, p }; draw();
      vcache[n] = await p;
    } else if (vcache[n].loading) await vcache[n].p;  // already on its way
    const f = sheet?.f; if (!f) return;
    const key = field === "netuid" ? "hotkey" : "dest_hotkey";
    if (sheet.keep.has(key) && f[key]) {  // a hotkey the caller chose: keep it, as "another hotkey" when it isn't in the list
      sheet.keep.delete(key);
      if (!vcache[n].validators.some(v => v.hotkey === f[key])) f.custom = true;
    } else if (!f[key] || !vcache[n].validators.some(v => v.hotkey === f[key])) {
      const mine = sheet.w.stake.find(p => p.netuid === n && vcache[n].validators.some(v => v.hotkey === p.hotkey));
      if (!f.custom) f[key] = mine?.hotkey || vcache[n].validators[0]?.hotkey || null;
    }
    draw();
  }

  // a re-render can blur a field, whose change event would draw again mid-render: queue that one instead
  let drawing = false, again = false;
  function draw() {
    if (drawing) { again = true; return; }
    drawing = true;
    try { paint(); } finally { drawing = false; }
    if (again) { again = false; draw(); }
  }
  function paint() {
    const d = $("#wx-sheet"); if (!d || !sheet) return;
    const [title, ic] = OPS[sheet.op];
    const body = sheet.step === "form" ? formHtml() : sheet.step === "review" ? reviewHtml() : sheet.step === "result" ? resultHtml() : signingHtml();
    const back = sheet.step === "review" && !sheet.busy;
    d.innerHTML = `<div class="wx-sh">
      <div class="wx-sh-head">${back ? `<button type="button" class="iconbtn sm" data-wx="back" aria-label="Back">${icon("left")}</button>` : `<span class="wx-op-ico">${icon(ic)}</span>`}
        <h3>${sheet.step === "review" ? "Confirm" : esc(title)}</h3>${sheet.op !== "receive" && sheet.step !== "result" ? `<span class="wx-steps" aria-hidden="true">${["form", "review", "sign"].map((s, i) => `<i class="${["form", "review", "sign"].indexOf(sheet.step === "submit" ? "sign" : sheet.step) >= i ? "on" : ""}"></i>`).join("")}</span>` : ""}
        <span class="spacer"></span><button type="button" class="iconbtn sm" data-wx="close" aria-label="Close">${icon("close")}</button></div>
      <div class="wx-from">${avatar(sheet.w.coldkey, "sm")}<span><b>${esc(sheet.w.name)}</b><small class="faint">${esc(short(sheet.w.coldkey))}</small></span><span class="spacer"></span>
        ${sheet.op === "receive" ? "" : `<span class="faint small">Free ${amt(sheet.w.free)}</span>`}</div>
      ${body}</div>`;
    const a = d.querySelector("[data-wx-amount]"); if (a && sheet.caret != null) { a.focus(); a.setSelectionRange(sheet.caret, sheet.caret); sheet.caret = null; }
  }

  // ---------- form ----------
  const subnetSelect = (name, cur, mine) => {
    const subs = subnets(), opt = r => `<option value="${r.netuid}" ${r.netuid === cur ? "selected" : ""}>SN${r.netuid} · ${esc(r.name)}</option>`;
    const own = subs.filter(r => mine.has(r.netuid));
    if (!subs.length) return `<input class="wx-in" type="number" min="0" max="65535" data-wx-f="${name}" value="${cur ?? ""}" aria-label="Subnet number" placeholder="Subnet number">`;
    return `<select class="wx-in" data-wx-f="${name}" aria-label="Subnet"><option value="0" ${cur === 0 ? "selected" : ""}>SN0 · Root</option>
      ${own.length ? `<optgroup label="Your subnets">${own.map(opt).join("")}</optgroup><optgroup label="All subnets">` : ""}${subs.map(opt).join("")}${own.length ? "</optgroup>" : ""}</select>`;
  };
  function validatorList(n, field) {
    const v = vcache[n], f = sheet.f, cur = f[field];
    if (!v || v.loading) return Loading.line("Loading validators…");
    if (v.error) return `<p class="no small">${esc(v.error)}</p>`;
    const mine = new Set(sheet.w.stake.filter(p => p.netuid === n).map(p => p.hotkey));
    return `<div class="wx-vals" role="radiogroup" aria-label="Validator">${v.validators.slice(0, 8).map((x, i) => `<button type="button" role="radio" class="wx-val ${x.hotkey === cur && !f.custom ? "on" : ""}" aria-checked="${x.hotkey === cur && !f.custom}" data-wx-val="${esc(x.hotkey)}" data-field="${field}">
        ${avatar(x.hotkey, "sm")}<span class="wx-val-main"><b>${esc(x.name || short(x.hotkey))}</b><small class="faint">${amt(x.stake, n ? "alpha" : "tao", 0)} staked${x.take != null ? ` · ${fmtNum(x.take * 100, 1)}% take` : ""}${x.nominators ? ` · ${fmtNum(x.nominators, 0)} nominators` : ""}</small></span>
        ${mine.has(x.hotkey) ? `<span class="badge clear">Yours</span>` : i === 0 ? `<span class="badge new">Top</span>` : ""}<span class="wx-radio" aria-hidden="true"></span></button>`).join("")}
      <button type="button" class="wx-val ${f.custom ? "on" : ""}" data-wx="custom-hk" data-field="${field}" aria-pressed="${f.custom}">${icon("key")}<span class="wx-val-main"><b>Another hotkey</b><small class="faint">Paste a validator's or your own hotkey address</small></span></button>
      ${f.custom ? `<input class="wx-in" data-wx-f="${field}" value="${esc(cur || "")}" placeholder="5… hotkey address" spellcheck="false" autocomplete="off" aria-label="Hotkey address">` : ""}</div>`;
  }
  function amountBox(unit, max, quote = "") {
    const f = sheet.f, t = tusd(), val = f.all ? max : parseFloat(f.amount);
    const usdv = val > 0 && t ? (unit === "tao" ? val * t : (priceOf(f.netuid) ?? 0) * val * t) : null;
    return `<div class="wx-amount ${f.all ? "all" : ""}"><div class="wx-amount-row">
        <input data-wx-amount data-wx-focus inputmode="decimal" autocomplete="off" placeholder="0" value="${f.all ? fmtNum(max, 6).replace(/,/g, "") : esc(f.amount)}" aria-label="Amount in ${unit === "tao" ? "TAO" : "alpha"}">
        <span class="wx-unit amt-${unit}">${UNIT[unit]}</span></div>
      <div class="wx-amount-sub"><span class="faint">${usdv ? `≈ ${esc(usd(usdv))}` : "&nbsp;"}</span><span class="spacer"></span>
        <span class="faint small">${unit === "tao" ? "Available" : "Position"} ${amt(max, unit)}</span></div>
      <div class="wx-pcts">${[25, 50, 75].map(p => `<button type="button" class="chip" data-wx-pct="${p}">${p}%</button>`).join("")}<button type="button" class="chip ${f.all ? "on" : ""}" data-wx-pct="max" aria-pressed="${f.all}">Max</button></div>
      ${quote ? `<p class="wx-quote" id="wx-quote">${quote}</p>` : ""}</div>`;
  }
  const slipHtml = () => `<div class="wx-slip"><span class="faint small" title="The swap fails rather than filling at a worse price">Max slippage</span>${SLIPS.map(s => `<button type="button" class="chip ${sheet.f.slippage === s ? "on" : ""}" data-wx-slip="${s}" aria-pressed="${sheet.f.slippage === s}">${s}%</button>`).join("")}</div>`;
  function positionList(field = "pos") {
    const f = sheet.f;
    return `<div class="wx-vals" role="radiogroup" aria-label="Position">${sheet.w.stake.map(p => `<button type="button" role="radio" class="wx-val ${p.netuid === f.netuid && p.hotkey === f.hotkey ? "on" : ""}" aria-checked="${p.netuid === f.netuid && p.hotkey === f.hotkey}" data-wx-pos="${p.netuid}|${esc(p.hotkey)}">
        <span class="wx-sn" aria-hidden="true">${p.netuid}</span><span class="wx-val-main"><b>${p.netuid ? `SN${p.netuid} · ` : ""}${esc(p.subnet)}</b><small class="faint">${esc(p.hotkey_name || hkName(p.hotkey))}</small></span>
        <span class="wx-val-amt">${amt(p.amount, p.netuid ? "alpha" : "tao")}${p.tao != null && p.netuid ? `<small class="faint">${amt(p.tao)}</small>` : ""}</span><span class="wx-radio" aria-hidden="true"></span></button>`).join("")}</div>`;
  }
  function formHtml() {
    const { op, w, f } = sheet, mine = new Set(w.stake.map(p => p.netuid)), free = Math.max(0, w.free - 0.0015);
    let html = "";
    if (op === "receive") return receiveHtml();
    if (op === "stake") {
      html = `<label class="wx-l">Subnet</label>${subnetSelect("netuid", f.netuid, mine)}
        <label class="wx-l">Validator</label>${validatorList(f.netuid, "hotkey")}
        <label class="wx-l">Amount</label>${amountBox("tao", free, quoteText())}${slipHtml()}`;
    } else if (op === "unstake") {
      const p = posOf(f.netuid, f.hotkey);
      html = `<label class="wx-l">From</label>${positionList()}
        <label class="wx-l">Amount</label>${amountBox(f.netuid ? "alpha" : "tao", p?.amount || 0, quoteText())}${f.netuid ? slipHtml() : ""}`;
    } else if (op === "move") {
      const p = posOf(f.netuid, f.hotkey);
      html = `<label class="wx-l">From</label>${positionList()}
        <label class="wx-l">To subnet</label>${subnetSelect("dest_netuid", f.dest_netuid, mine)}
        <label class="wx-l">To validator</label>${validatorList(f.dest_netuid, "dest_hotkey")}
        <label class="wx-l">Amount</label>${amountBox(f.netuid ? "alpha" : "tao", p?.amount || 0)}${slipHtml()}`;
    } else if (op === "unstake_all") {
      const hks = [...new Set(w.stake.map(p => p.hotkey))];
      html = `<label class="wx-l">Hotkey</label><div class="wx-vals" role="radiogroup">${hks.map(h => {
          const ps = w.stake.filter(p => p.hotkey === h), val = ps.reduce((t, p) => t + (p.tao || 0), 0);
          return `<button type="button" role="radio" class="wx-val ${h === f.hotkey ? "on" : ""}" aria-checked="${h === f.hotkey}" data-wx-hk="${esc(h)}">${avatar(h, "sm")}<span class="wx-val-main"><b>${esc(hkName(h))}</b><small class="faint">${ps.map(p => `SN${p.netuid}`).join(", ")}</small></span>
            <span class="wx-val-amt">${amt(val)}</span><span class="wx-radio" aria-hidden="true"></span></button>`; }).join("")}</div>
        <p class="wx-note">${icon("alert")}<span>Unstakes every position this wallet holds with this hotkey, on every subnet, back to free TAO at today's prices.</span></p>`;
    } else if (op === "send") {
      html = `<label class="wx-l" for="wx-dest">To</label><input id="wx-dest" class="wx-in" data-wx-f="dest" data-wx-focus value="${esc(f.dest)}" placeholder="5… recipient's address" spellcheck="false" autocomplete="off">
<p class="no small" id="wx-dest-hint">${destHint()}</p>
        <label class="wx-l">Amount</label>${amountBox("tao", free)}
        <p class="wx-note">${icon("info")}<span>Only send to Bittensor addresses. Exchanges need the address of your deposit on the Bittensor (TAO) network.</span></p>`;
    }
    const ready = canReview();
    return `<div class="wx-body">${html}</div>
      ${sheet.error ? `<p class="wx-err">${icon("alert")}${esc(sheet.error)}</p>` : ""}
      <div class="wx-foot"><button type="button" class="btn primary wx-cta ${sheet.busy ? "loading" : ""}" data-wx="review" ${ready && !sheet.busy ? "" : "disabled"}>${ready ? "Review" : esc(readyHint())}</button></div>`;
  }
  const destHint = () => sheet.f.dest.trim() && !pub(sheet.f.dest.trim()) ? "That doesn't look like a Bittensor address (SS58, 48 characters starting with 5)." : "";
  // typing in an address keeps the focus: only the hint and the button change
  function liveCheck() {
    const b = $("#wx-sheet [data-wx=review]"); if (b) { b.disabled = !canReview(); b.textContent = canReview() ? "Review" : readyHint(); }
    const h = $("#wx-dest-hint"); if (h) h.textContent = destHint();
  }
  const amountValue = () => sheet.f.all ? "all" : parseFloat(sheet.f.amount);
  function canReview() {
    const { op, f } = sheet, a = amountValue();
    if (op === "unstake_all") return !!f.hotkey;
    if (!(a === "all" || a > 0)) return false;
    if (op === "send") return !!pub(f.dest.trim());
    if (op === "stake") return f.netuid != null && !!pub((f.hotkey || "").trim());
    if (op === "move") return f.dest_netuid != null && !!pub((f.dest_hotkey || "").trim());
    return true;
  }
  function readyHint() {
    const { op, f } = sheet, a = amountValue();
    if (op === "send" && !pub(f.dest.trim())) return "Enter an address";
    if (op === "stake" && !pub((f.hotkey || "").trim())) return "Pick a validator";
    if (op === "move" && !pub((f.dest_hotkey || "").trim())) return "Pick a validator";
    if (!(a === "all" || a > 0)) return "Enter an amount";
    return "Review";
  }
  // a live quote while typing (stake and unstake)
  let qT = null, qv = null;
  function quoteText() {
    const { op, f } = sheet, a = f.all ? null : parseFloat(f.amount);
    if (f.netuid === 0) return a > 0 ? `<span class="faint">Root stake stays in TAO: no swap.</span>` : "";
    if (!(a > 0) && !f.all) return `<span class="faint">${op === "stake" ? "You'll receive the subnet's alpha at the pool price." : "You'll receive TAO at the pool price."}</span>`;
    if (!qv || qv.key !== `${op}|${f.netuid}|${a}`) return `<span class="faint">Quoting…</span>`;
    if (qv.error) return `<span class="no">${esc(qv.error)}</span>`;
    const q = qv.q, recv = op === "stake" ? amt(q.alpha, "alpha") : amt(q.tao), imp = q.impact * 100;
    return `You receive ≈ ${recv} · price impact <span class="${imp > 5 ? "no" : imp > 1 ? "warn" : ""}">${fmtNum(imp, imp < 0.1 ? 3 : 2)}%</span>`;
  }
  function requote() {
    const { op, f } = sheet; if (!["stake", "unstake"].includes(op) || f.netuid === 0) return;
    const a = f.all ? (op === "stake" ? Math.max(0, sheet.w.free - 0.0015) : posOf(f.netuid, f.hotkey)?.amount) : parseFloat(f.amount);
    clearTimeout(qT);
    if (!(a > 0)) { qv = null; return; }
    const key = `${op}|${f.netuid}|${f.all ? null : a}`;
    qT = setTimeout(async () => {
      let r; try { r = { key, q: await api(`/api/wallet/quote?netuid=${f.netuid}&amount=${a}&side=${op}`) }; } catch (e) { r = { key, error: e.message }; }
      if (!sheet || sheet.step !== "form") return;
      qv = r; const el = $("#wx-quote"); if (el) el.innerHTML = quoteText();
    }, 350);
  }

  // ---------- review ----------
  async function next() {
    if (!canReview() || sheet.busy) return;
    sheet.busy = "review"; sheet.error = ""; draw();
    const { op, f, w } = sheet, a = amountValue();
    const body = { wallet_id: w.id, op, slippage: f.slippage, ...(a === "all" ? { all: true } : op === "unstake_all" ? {} : { amount: a }) };
    if (op === "stake") Object.assign(body, { netuid: f.netuid, hotkey: f.hotkey.trim() });
    if (op === "unstake") Object.assign(body, { netuid: f.netuid, hotkey: f.hotkey });
    if (op === "move") Object.assign(body, { netuid: f.netuid, hotkey: f.hotkey, dest_netuid: f.dest_netuid, dest_hotkey: f.dest_hotkey.trim() });
    if (op === "unstake_all") Object.assign(body, { hotkey: f.hotkey });
    if (op === "send") Object.assign(body, { dest: f.dest.trim() });
    try { sheet.review = await api("/api/wallet/tx/review", { method: "POST", body }); sheet.step = "review"; sheet.reviewedAt = Date.now(); }
    catch (e) { sheet.error = e.message; }
    sheet.busy = ""; draw();
  }
  function reviewHtml() {
    const r = sheet.review, signer = signerFor(r.wallet.coldkey), q = r.quote, u = r.unit || "tao";
    const row = (k, v, cls = "") => `<div class="wx-row ${cls}"><span>${k}</span><b>${v}</b></div>`;
    const imp = q?.impact != null ? q.impact * 100 : null;
    const headline = {
      stake: () => [`${r.all ? "All free TAO" : amt(r.amount)}`, q ? `≈ ${amt(q.receive, q.unit)}` : `SN${r.netuid}`],
      unstake: () => [r.all ? "The whole position" : amt(r.amount, u), q ? `≈ ${amt(q.receive, "tao")}` : ""],
      move: () => [r.all ? "The whole position" : amt(r.amount, u), q ? `≈ ${amt(q.receive, q.unit)}` : ""],
      unstake_all: () => [`${r.positions.length} position${r.positions.length === 1 ? "" : "s"}`, "→ free TAO"],
      send: () => [r.all ? "All free TAO" : amt(r.amount), short(r.dest)],
    }[r.op]();
    const rows = [];
    if (r.op === "stake") rows.push(row("Subnet", snLabel(r.netuid)), row("Validator", `${esc(hkName(r.hotkey))} <span class="faint num">${esc(short(r.hotkey))}</span>`));
    if (r.op === "unstake") rows.push(row("From", `${snLabel(r.netuid)} · ${esc(hkName(r.hotkey))}`), row("Position", amt(r.position, u)));
    if (r.op === "move") rows.push(row("From", `SN${r.netuid} · ${esc(hkName(r.hotkey))}`), row("To", `${snLabel(r.dest_netuid)} · ${esc(hkName(r.dest_hotkey))}`), ...(q?.via_tao ? [row("Swaps through", `≈ ${amt(q.via_tao)}`)] : []));
    if (r.op === "unstake_all") rows.push(row("Hotkey", `${esc(hkName(r.hotkey))} <span class="faint num">${esc(short(r.hotkey))}</span>`), ...r.positions.map(p => row(snLabel(p.netuid), amt(p.amount, p.netuid ? "alpha" : "tao"))));
    if (r.op === "send") rows.push(row("To", `<span class="num wx-dest">${esc(r.dest)}</span>`));
    if (q?.receive != null && r.op !== "send") rows.push(row("You receive", `≈ ${amt(q.receive, q.unit)}`));
    if (imp != null && imp > 0) rows.push(row("Price impact", `<span class="${imp > 5 ? "no" : imp > 1 ? "warn" : ""}">${fmtNum(imp, imp < 0.1 ? 3 : 2)}%</span>`));
    if (["stake", "unstake", "move"].includes(r.op) && !(r.netuid === 0 && r.op !== "move")) rows.push(row("Max slippage", `${r.slippage}% <span class="faint">· fails rather than fill worse</span>`));
    rows.push(row("Network fee", `≈ ${amt(r.fee, "tao", 6)}${tusd() ? ` <span class="faint">${esc(usd(r.fee * tusd()))}</span>` : ""}`));
    if (["stake", "send"].includes(r.op) && !r.all) rows.push(row("Total", amt(r.amount + r.fee, "tao", 6), "total"));
    const exts = connected();
    const signBox = !r.ok ? "" : signer
      ? `<button type="button" class="btn primary wx-cta ${sheet.busy ? "loading" : ""}" data-wx="sign" ${sheet.busy ? "disabled" : ""}>${icon("check")}Confirm in ${esc(label(signer.source))}</button>
         <p class="faint small wx-signer">${avatar(signer.address, "xs")}Signs as ${esc(signer.name)} · ${esc(short(signer.address))}</p>`
      : exts.length ? `<p class="wx-note">${icon("key")}<span>None of your connected wallets holds this coldkey (${esc(short(r.wallet.coldkey))}). ${esc(sharing(exts, false))} ${esc(fixHint(exts))}</span></p>`
      : `<button type="button" class="btn primary wx-cta" data-wx-connect data-wx="connect">${icon("wallet")}Connect a browser wallet to sign</button>`;
    return `<div class="wx-body">
      <div class="wx-headline"><span class="wx-op-big">${icon(OPS[r.op][1])}</span><b>${headline[0]}</b>${headline[1] ? `<span class="faint">${headline[1]}</span>` : ""}</div>
      <div class="wx-rows">${rows.join("")}</div>
      ${r.blocks.map(b => `<p class="wx-err">${icon("alert")}${esc(b)}</p>`).join("")}
      ${r.warnings.map(x => `<p class="wx-note">${icon("info")}<span>${esc(cap(x))}</span></p>`).join("")}
      ${sheet.error ? `<p class="wx-err">${icon("alert")}${esc(sheet.error)}</p>` : ""}
      <details class="wx-cmd" ${sheet.showCmd ? "open" : ""}><summary>Use btcli instead</summary>
        <div class="wl-cmd"><code>${esc(r.command)}</code><button type="button" class="iconbtn sm" data-wx-copy="${esc(r.command)}" title="Copy" aria-label="Copy">${icon("copy")}</button></div>
        <p class="faint small">The same transaction from your own machine. Add <code>--dry-run</code> to preview it there.</p></details></div>
      <div class="wx-foot">${r.ok ? insecureNote() : ""}${signBox || `<button type="button" class="btn wx-cta" data-wx="back">${icon("left")}Change it</button>`}
        ${r.ok && signer ? `<p class="faint small wx-fine">Your wallet shows the transaction before you approve it. It's valid for about 25 minutes.</p>` : ""}</div>`;
  }
  const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;

  // ---------- sign and submit ----------
  async function sign() {
    const r = sheet.review, signer = signerFor(r.wallet.coldkey); if (!signer || sheet.busy) return;
    sheet.busy = "prepare"; sheet.error = ""; draw();
    let p;
    try { p = await api("/api/wallet/tx/prepare", { method: "POST", body: { token: r.token } }); }
    catch (e) {
      sheet.busy = "";
      if (e.status === 409 || /quoting again/i.test(e.message)) { toast("Prices refreshed: check the numbers and confirm again"); return next(); }
      sheet.error = e.message; return draw();
    }
    sheet.step = "sign"; sheet.busy = ""; sheet.signer = signer; draw();
    let sig;
    try {
      const inj = ext[signer.source] || (await enable(signer.source), ext[signer.source]);
      sig = (await inj.signer.signPayload({ ...p.payload, address: signer.address })).signature;
    } catch (e) {
      sheet.step = "review";
      sheet.error = /cancel|reject|denied|closed/i.test(e?.message || "") ? `You declined it in ${label(signer.source)}. Nothing was sent.` : `${label(signer.source)}: ${e?.message || e}`;
      return draw();
    }
    sheet.step = "submit"; draw();
    try { sheet.result = await api("/api/wallet/tx/submit", { method: "POST", body: { token: r.token, signature: sig } }); }
    catch (e) { sheet.result = { ok: false, error: e.message }; }
    sheet.step = "result"; draw();
    sheet.done(sheet.result);
  }
  function signingHtml() {
    const s = sheet.signer, submitting = sheet.step === "submit";
    return `<div class="wx-body wx-wait"><div class="wx-pulse ${submitting ? "go" : ""}">${icon(submitting ? "send" : "wallet")}</div>
      <h4>${submitting ? "Submitting…" : `Approve in ${esc(label(s.source))}`}</h4>
      <p class="muted">${submitting ? "Waiting for the transaction to land in a block (about 12 seconds)." : `Check the transaction in the ${esc(label(s.source))} window and approve it. AXoR never sees your key.`}</p></div>`;
  }
  function resultHtml() {
    const x = sheet.result, ok = x.ok;
    return `<div class="wx-body wx-done ${ok ? "ok" : "bad"}"><div class="wx-badge">${icon(ok ? "check" : "close")}</div>
      <h4>${ok ? "Done" : "It didn't go through"}</h4>
      <p class="muted">${esc(ok ? x.detail : x.error || "The chain rejected the transaction.")}</p>
      ${ok ? `<div class="wx-rows">${x.extrinsic_id ? `<div class="wx-row"><span>Transaction</span><b class="num">${esc(x.extrinsic_id)}</b></div>` : ""}${x.fee != null ? `<div class="wx-row"><span>Fee paid</span><b>${amt(x.fee, "tao", 6)}</b></div>` : ""}</div>` : ""}</div>
      <div class="wx-foot wx-foot-row">${x.explorer_url ? `<a class="btn" href="${esc(x.explorer_url)}" target="_blank" rel="noopener noreferrer">${icon("external")}View on explorer</a>` : ""}
        ${!ok && sheet.review ? `<button type="button" class="btn" data-wx="retry">${icon("reset")}Review again</button>` : ""}
        <button type="button" class="btn primary" data-wx="close">${ok ? "Done" : "Close"}</button></div>`;
  }

  // ---------- receive ----------
  function receiveHtml() {
    const a = sheet.w.coldkey, qr = typeof QR !== "undefined" ? QR.svg(a) : "";
    return `<div class="wx-body wx-recv">${qr ? `<div class="wx-qr" role="img" aria-label="QR code of the address">${qr}</div>` : ""}
      <p class="wx-addr num">${esc(a)}</p>
      <div class="row wx-recv-acts"><button type="button" class="btn primary" data-wx-copy="${esc(a)}">${icon("copy")}Copy address</button>
        ${navigator.share ? `<button type="button" class="btn" data-wx="share">${icon("send")}Share</button>` : ""}</div>
      <p class="wx-note">${icon("info")}<span>Send only TAO on the Bittensor network to this address. It's your coldkey: staking and transfers start here.</span></p></div>`;
  }

  // ---------- events ----------
  async function click(e) {
    if (!sheet) return;
    const t = e.target, k = t.closest("[data-wx]")?.dataset.wx, f = sheet.f;
    if (e.target === $("#wx-sheet")) return $("#wx-sheet").close();  // backdrop
    if (k === "close") return $("#wx-sheet").close();
    if (k === "back") { sheet.step = "form"; sheet.error = ""; return draw(); }
    if (k === "review") return next();
    if (k === "retry") { sheet.step = "form"; sheet.result = null; return draw(); }
    if (k === "sign") return sign();
    if (k === "connect") return connectMenu(t.closest("[data-wx]"), { tracked: [sheet.w] });
    if (k === "share") { try { await navigator.share({ text: sheet.w.coldkey }); } catch {} return; }
    if (k === "custom-hk") { f.custom = !f.custom; if (f.custom) f[t.closest("[data-wx]").dataset.field] = ""; else loadValidators(t.closest("[data-wx]").dataset.field === "hotkey" ? f.netuid : f.dest_netuid, t.closest("[data-wx]").dataset.field === "hotkey" ? "netuid" : "dest_netuid"); return draw(); }
    const cp = t.closest("[data-wx-copy]"); if (cp) { try { await navigator.clipboard.writeText(cp.dataset.wxCopy); toast("Copied"); } catch { toast("Couldn't copy"); } return; }
    const v = t.closest("[data-wx-val]"); if (v) { f.custom = false; f[v.dataset.field] = v.dataset.wxVal; return draw(); }
    const p = t.closest("[data-wx-pos]"); if (p) { const [n, hk] = p.dataset.wxPos.split("|"); f.netuid = +n; f.hotkey = hk; f.amount = ""; f.all = false; qv = null; return draw(); }
    const hk = t.closest("[data-wx-hk]"); if (hk) { f.hotkey = hk.dataset.wxHk; return draw(); }
    const sl = t.closest("[data-wx-slip]"); if (sl) { f.slippage = +sl.dataset.wxSlip; pref("slippage", f.slippage); return draw(); }
    const pc = t.closest("[data-wx-pct]"); if (pc) {
      const max = sheet.op === "stake" || sheet.op === "send" ? Math.max(0, sheet.w.free - 0.0015) : posOf(f.netuid, f.hotkey)?.amount || 0;
      if (pc.dataset.wxPct === "max") { f.all = !f.all; if (!f.all) f.amount = ""; }
      else { f.all = false; f.amount = String(+(max * +pc.dataset.wxPct / 100).toFixed(6)); }
      requote(); return draw();
    }
  }
  function input(e) {
    if (!sheet) return;
    const t = e.target, f = sheet.f;
    if (t.matches("[data-wx-amount]")) {
      const clean = t.value.replace(/,/g, ".").replace(/[^\d.]/g, "").replace(/(\..*)\./g, "$1");
      f.amount = clean; f.all = false; sheet.caret = Math.min(t.selectionStart ?? clean.length, clean.length);
      requote(); return draw();
    }
    if (t.matches("[data-wx-f=dest]")) { f.dest = t.value; return liveCheck(); }
    if (t.matches("[data-wx-f=hotkey], [data-wx-f=dest_hotkey]")) { f[t.dataset.wxF] = t.value; return liveCheck(); }
  }
  function change(e) {
    if (!sheet) return;
    const t = e.target, f = sheet.f;
    if (t.matches("[data-wx-f=netuid]") && +t.value !== f.netuid) { f.netuid = +t.value; if (!f.custom) f.hotkey = null; qv = null; requote(); loadValidators(f.netuid, "netuid"); return draw(); }
    if (t.matches("[data-wx-f=dest_netuid]") && +t.value !== f.dest_netuid) { f.dest_netuid = +t.value; if (!f.custom) f.dest_hotkey = null; loadValidators(f.dest_netuid, "dest_netuid"); return draw(); }
  }

  return { init, start, connectMenu, accounts, connected, signerFor, pub, avatar, label, OPS };
})();
