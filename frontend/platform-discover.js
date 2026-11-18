/* Discover and Risk intelligence (platform.css): the Explorer's active filters as chips, a compare tray of up to four
   subnets (from a subnet's details or any subnet card) with a side-by-side table, and on Avoid & Caution and Scam Signals
   a search, filter chips per flag with counts, a sort, and what each flag means. Works on the pages app.js renders: it
   filters, sorts and adds to their DOM, so every number stays the live one. */
const Discover = (() => {
  const MAX = 4;
  // What each risk.py flag means, keyed level:code. Mirrors the rules in backend/app/risk.py: change both together.
  const FLAGS = {
    "scam:abandoned": ["Abandoned or for sale", "The subnet's identity marks it as for sale, parked or deprecated, yet it still draws emission."],
    "scam:anonymous": ["Anonymous with emission", "It receives emission but has no on-chain identity, website or code: nothing shows what miners are paid for."],
    "scam:owner_capture": ["Owner capture", "The owner's hotkey keeps 90% or more of miner emission and at most 3 outside miners earn."],
    "scam:closed_capture": ["Closed capture", "One hotkey takes 90% or more of miner emission, at most 3 miners earn and there's no public code: consistent with owner-run miners."],
    "avoid:reg_closed": ["Registration closed", "The subnet doesn't accept new miners."],
    "avoid:no_uid": ["No UID available", "Every slot is held by immune miners, or the registration rate limit is hit."],
    "avoid:no_emission": ["No emission", "The subnet gets no TAO emission, so there's nothing to earn."],
    "avoid:dust": ["Dust earnings", "Even the top miner earns under $1 a day."],
    "avoid:slow_payback": ["Slow payback", "Registration takes more than 60 days to earn back at the median earner's rate."],
    "avoid:crash": ["Price crash", "The alpha price fell more than 30% in 7 days, so earnings in TAO shrink fast."],
    "avoid:anonymous": ["Anonymous", "No on-chain identity, website or code repository."],
    "caution:winner_take_all": ["Winner-take-most", "The docs say so, or the top miner takes 60% or more of miner emission."],
    "caution:owner_burn": ["Owner take", "Between half and 90% of miner emission goes to the owner or is burned: a smaller pool for miners."],
    "caution:few_earners": ["Few earners", "Fewer than 5 miners earn anything."],
    "caution:early": ["Early stage", "The docs describe the mechanism as early-stage or in flux: rules may change under you."],
    "caution:undocumented": ["Undocumented", "Miner requirements aren't published."],
    "caution:capital": ["Capital at risk", "Mining needs trading capital, collateral or stake that can be lost."],
    "caution:outflow": ["TAO outflow", "Net TAO is leaving and the price fell more than 10% in 7 days: deregistration risk rises."],
    "caution:very_new": ["Very new", "Less than 30 days old: no track record yet."],
  };
  const SORTS = { emission: ["Emission", r => -r.emission_day], reg: ["Registration cost", r => r.reg_cost], top: ["Top miner pay", r => -r.top_miner],
    flags: ["Most flags", r => -r.flags.length], newest: ["Newest", r => -r.created_block] };
  const pref = (k, d) => store.get("plt." + k, d);
  let picks = [], wired = false;  // read in init(): store lives in app.js, which loads last
  const row = n => S.data?.subnets?.find(r => r.netuid === +n);
  const key = f => `${f.level}:${f.code}`;

  // ---------- Explorer: active filters as chips ----------
  function chips() {
    const box = $("#plt-fchips"); if (!box) return;
    const sel = id => { const el = $("#" + id); return el.value ? el.selectedOptions[0]?.textContent : ""; };
    const on = [
      $("#q").value.trim() && ["q", `Search: “${$("#q").value.trim()}”`],
      sel("f-field") && ["f-field", `Field: ${sel("f-field")}`], sel("f-tier") && ["f-tier", `Hardware: ${sel("f-tier")}`],
      sel("f-risk") && ["f-risk", `Risk: ${sel("f-risk")}`], $("#f-uid").checked && ["f-uid", "UID available"], $("#f-earn").checked && ["f-earn", "Has earners"],
    ].filter(Boolean);
    box.hidden = !on.length;
    box.innerHTML = on.map(([id, l]) => `<button type="button" class="plt-chip" data-unfilter="${id}" title="Remove this filter">${esc(l)}${icon("close")}</button>`).join("")
      + (on.length > 1 ? `<button type="button" class="linkbtn" data-unfilter="*">Clear all</button>` : "");
  }
  function unfilter(id) {
    for (const x of id === "*" ? ["q", "f-field", "f-tier", "f-risk", "f-uid", "f-earn"] : [id]) {
      const el = $("#" + x); if (el.type === "checkbox") el.checked = false; else el.value = "";
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
    chips();
  }

  // ---------- compare ----------
  function toggle(n) {
    n = +n;
    if (picks.includes(n)) picks = picks.filter(x => x !== n);
    else if (picks.length >= MAX) return toast(`Compare holds ${MAX} subnets. Remove one first.`);
    else picks = [...picks, n];
    store.set("plt.compare", picks); tray(); marks();
  }
  const button = (n, cls = "btn sm") => `<button type="button" class="${cls} plt-cmp-btn" data-compare="${n}" aria-pressed="${picks.includes(+n)}" title="Compare side by side (up to ${MAX})">${icon("columns")}<span>${picks.includes(+n) ? "Comparing" : "Compare"}</span></button>`;
  function marks() { $$("[data-compare]").forEach(b => { const on = picks.includes(+b.dataset.compare); b.setAttribute("aria-pressed", on); const s = b.querySelector("span"); if (s) s.textContent = on ? "Comparing" : "Compare"; }); }
  function tray() {
    let t = $("#plt-tray");
    picks = picks.filter(n => !S.data?.subnets?.length || row(n));
    if (!picks.length || !Auth.me() && !S.data) { t?.remove(); return; }
    if (!t) { t = document.createElement("div"); t.id = "plt-tray"; t.className = "plt-tray"; t.setAttribute("role", "region"); t.setAttribute("aria-label", "Subnets to compare"); document.body.appendChild(t); }
    t.innerHTML = `<b>${icon("columns")}Compare</b><span class="plt-tray-list">${picks.map(n => `<span class="plt-chip">SN${n} ${esc(row(n)?.name || "")}<button type="button" data-compare="${n}" aria-label="Remove SN${n}">${icon("close")}</button></span>`).join("")}</span>
      <button type="button" class="btn sm primary" data-cmp-open ${picks.length < 2 ? "disabled title=\"Pick at least two subnets\"" : ""}>Compare ${picks.length}</button><button type="button" class="linkbtn" data-cmp-clear>Clear</button>`;
  }
  function table() {
    const rs = picks.map(row).filter(Boolean);
    // [label, value html, number for "best", higher is better?]
    const M = [
      ["Field", r => esc(r.field)], ["Risk", r => riskBadge(r) || `<span class="badge clear">${icon("check")}Clear</span>`],
      ["Emission / day", r => `${fmtNum(r.emission_day)} τ`, r => r.emission_day, 1], ["Emission share", r => pct(r.emission_share, 2), r => r.emission_share, 1],
      ["Top miner / day", r => money(r.top_miner), r => r.top_miner, 1], ["Median earner / day", r => money(r.median_miner), r => r.median_miner, 1],
      ["Earning miners", r => `${r.earning_miners} / ${r.num_uids}`, r => r.earning_miners, 1], ["Top miner's share", r => pct(r.top_share, 0), r => r.top_share, -1],
      ["Owner / burn share", r => pct(r.owner_burn_share, 0), r => r.owner_burn_share, -1], ["Registration cost", r => money(r.reg_cost), r => r.reg_cost, -1],
      ["UID", r => r.uid_available ? "Available" : r.registration_allowed ? "Full / rate-limited" : "Closed"], ["Hardware", r => esc(tierOf(r).label)],
      ["Alpha price 7d", r => delta(r.price_change_7d), r => r.price_change_7d, 1], ["Net TAO flow / day", r => `${fmtNum(r.tao_flow_day)} τ`, r => r.tao_flow_day, 1],
      ["Age", r => `${fmtNum(r.age_days, 0)} days`, r => r.age_days, 1], ["Emission, 7 days", r => `<div class="trend wide">${spark(r.series?.emission_day, 200, 30)}</div>`],
      ["Flags", r => r.flags.length ? `<ul class="flags">${r.flags.map(f => `<li><span class="badge ${f.level}">${icon(RISK[f.level].icon)}</span><span class="muted">${esc(f.text)}</span></li>`).join("")}</ul>` : `<span class="faint">None</span>`],
    ];
    const body = M.map(([l, f, num, dir]) => {
      let best = null;
      if (num && rs.length > 1) { const v = rs.map(num).filter(x => x != null && isFinite(x)); if (v.length > 1 && new Set(v).size > 1) best = dir > 0 ? Math.max(...v) : Math.min(...v); }
      return `<tr><th scope="row">${l}</th>${rs.map(r => `<td class="${best != null && num(r) === best ? "plt-best" : ""}">${f(r)}</td>`).join("")}</tr>`;
    }).join("");
    return `<table class="grid plt-cmp-t" data-plt-skip><thead><tr><th></th>${rs.map(r => `<th scope="col"><div class="dash-sn">${logo(r)}<span><b>SN${r.netuid}</b> ${esc(r.name)}</span></div>
      <div class="row"><button type="button" class="linkbtn" data-open="${r.netuid}">Details</button><button type="button" class="linkbtn" data-compare="${r.netuid}">Remove</button></div></th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
  }
  function openCompare() {
    const d = $("#modal");
    d.classList.remove("is-danger");
    d.innerHTML = `<form method="dialog" class="plt-cmp"><div class="plt-cmp-h"><h3>${icon("columns")}Compare subnets</h3><button type="button" class="iconbtn" data-close aria-label="Close">${icon("close")}</button></div>
      <p class="faint small">Live figures from block ${S.data?.block?.toLocaleString() || "–"}. The best value in each row is highlighted.</p><div class="tablewrap flat">${table()}</div></form>`;
    $("[data-close]", d).onclick = () => d.close();
    // #modal is shared with auth.js: drop a forced dialog's Escape block, and our click handler once this closes
    d.oncancel = null;
    d.addEventListener("close", () => { d.onclick = null; }, { once: true });
    d.onclick = e => {
      const o = e.target.closest("[data-open]"); if (o) { d.close(); return openDrawer(o.dataset.open); }
      const c = e.target.closest("[data-compare]"); if (c) { toggle(c.dataset.compare); return picks.length < 2 ? d.close() : $(".tablewrap", d).innerHTML = table(); }
    };
    d.showModal();
  }

  // ---------- risk pages: search, flag chips, sort, what the flags mean ----------
  const RISKV = { caution: { body: "#caution-body", levels: ["avoid", "caution"] }, scam: { body: "#scam-body", levels: ["scam"] } };
  const rstate = v => ({ q: "", flag: "", sort: pref(`risk.${v}.sort`, "emission"), ...(RISKV[v].st || {}) });
  function riskBar(v) {
    const sec = $("#view-" + v), cfg = RISKV[v];
    if (!S.data?.subnets?.length) return;
    const st = cfg.st = rstate(v);
    const subs = S.data.subnets.filter(r => cfg.levels.includes(r.risk_level));
    const counts = {};
    subs.forEach(r => new Set(r.flags.map(key)).forEach(k => { if (FLAGS[k] && cfg.levels.includes(k.split(":")[0])) counts[k] = (counts[k] || 0) + 1; }));
    const order = Object.keys(FLAGS).filter(k => counts[k]);
    let bar = $(".plt-risk", sec);
    if (!bar) { bar = document.createElement("div"); bar.className = "plt-risk"; $(cfg.body, sec).before(bar); }
    const example = k => { const f = subs.flatMap(r => r.flags).find(f => key(f) === k); return f ? `<small class="faint">For example: ${esc(f.text)}</small>` : ""; };
    bar.innerHTML = `<div class="toolbar"><div class="search"><span>${icon("search")}</span><input type="search" data-rq placeholder="Search name, field or flag" value="${esc(st.q)}" aria-label="Search these subnets"></div>
        <select data-rsort aria-label="Sort">${Object.entries(SORTS).map(([k, [l]]) => `<option value="${k}" ${st.sort === k ? "selected" : ""}>Sort: ${l}</option>`).join("")}</select>
        <span class="result-count" data-rcount></span></div>
      <div class="plt-flagchips" role="group" aria-label="Filter by flag"><button type="button" class="chip" data-rflag="" aria-pressed="${!st.flag}">All flags <b>${subs.length}</b></button>${order.map(k =>
        `<button type="button" class="chip" data-rflag="${k}" aria-pressed="${st.flag === k}" title="${esc(FLAGS[k][1])}"><span class="badge ${k.split(":")[0]}">${icon(RISK[k.split(":")[0]].icon)}</span>${esc(FLAGS[k][0])} <b>${counts[k]}</b></button>`).join("")}</div>
      <details class="plt-explain" ${pref(`risk.${v}.explain`, false) ? "open" : ""}><summary>${icon("info")}What these flags mean</summary>
        <dl>${order.map(k => `<div><dt><span class="badge ${k.split(":")[0]}">${icon(RISK[k.split(":")[0]].icon)}${esc(FLAGS[k][0])}</span><span class="faint">${counts[k]} subnet${counts[k] === 1 ? "" : "s"}</span></dt><dd>${esc(FLAGS[k][1])}${example(k)}</dd></div>`).join("")}</dl></details>`;
    apply(v);
  }
  function apply(v) {
    const cfg = RISKV[v], st = cfg.st, sec = $("#view-" + v); if (!st) return;
    const q = st.q.toLowerCase(), by = SORTS[st.sort]?.[1] || SORTS.emission[1];
    let shown = 0, total = 0;
    $$(cfg.body + " .card-grid, " + cfg.body + ".card-grid", sec).forEach(grid => {
      const cards = $$(":scope > .scard", grid);
      cards.forEach(c => {
        const r = row(c.dataset.id); if (!r) return;
        total++;
        const ok = (!st.flag || r.flags.some(f => key(f) === st.flag)) && (!q || [r.name, r.field, `sn${r.netuid}`, r.task, ...r.flags.map(f => f.text)].join(" ").toLowerCase().includes(q));
        c.hidden = !ok; if (ok) shown++;
      });
      const sorted = [...cards].sort((a, b) => by(row(a.dataset.id)) - by(row(b.dataset.id)));
      if (sorted.some((c, i) => c !== cards[i])) sorted.forEach(c => grid.appendChild(c));  // only when the order changes: no observer loop
      let none = $(":scope > .plt-none-match", grid);
      if (cards.length && !cards.some(c => !c.hidden)) { if (!none) { none = document.createElement("div"); none.className = "empty plt-none-match"; none.textContent = "No subnet here matches."; grid.appendChild(none); } }
      else none?.remove();
    });
    const rc = $("[data-rcount]", sec); if (rc) rc.textContent = st.q || st.flag ? `${shown} of ${total} subnets` : `${total} subnets`;
  }
  function wireRisk(v) {
    const sec = $("#view-" + v), cfg = RISKV[v];
    sec.addEventListener("input", e => { if (e.target.matches("[data-rq]")) { cfg.st.q = e.target.value; apply(v); } });
    sec.addEventListener("change", e => { if (e.target.matches("[data-rsort]")) { cfg.st.sort = e.target.value; store.set(`plt.risk.${v}.sort`, cfg.st.sort); apply(v); } });
    sec.addEventListener("click", e => {
      const c = e.target.closest("[data-rflag]"); if (!c) return;
      cfg.st.flag = c.dataset.rflag === cfg.st.flag ? "" : c.dataset.rflag;
      $$("[data-rflag]", sec).forEach(b => b.setAttribute("aria-pressed", b.dataset.rflag === cfg.st.flag));
      apply(v);
    });
    sec.addEventListener("toggle", e => { if (e.target.matches(".plt-explain")) store.set(`plt.risk.${v}.explain`, e.target.open); }, true);
    // app.js re-renders the cards on every snapshot: filter, sort and add Compare buttons again
    new MutationObserver(() => { cards($(cfg.body)); if ($(".plt-risk", sec)?.contains(document.activeElement)) apply(v); else riskBar(v); }).observe($(cfg.body), { childList: true });
  }
  // a Compare button on every subnet card (Avoid & Caution, Scam Signals, New)
  function cards(root) {
    if (!root) return;
    $$(".scard[data-id]", root).forEach(c => { if (!c.querySelector("[data-compare]")) c.insertAdjacentHTML("beforeend", `<div class="plt-scard-act">${button(c.dataset.id, "linkbtn")}</div>`); });
  }

  function init() {
    if (wired) return; wired = true;
    picks = pref("compare", []);
    $("#view-explore .toolbar").insertAdjacentHTML("afterend", `<div class="plt-fchips" id="plt-fchips" hidden aria-label="Active filters"></div>`);
    $("#view-explore .toolbar").addEventListener("input", chips);
    $("#view-explore .toolbar").addEventListener("change", chips);
    chips();
    document.addEventListener("click", e => {
      const u = e.target.closest("[data-unfilter]"); if (u) return unfilter(u.dataset.unfilter);
      if (e.target.closest("#modal")) return;  // the compare dialog handles its own
      const c = e.target.closest("[data-compare]"); if (c) { e.stopPropagation(); return toggle(c.dataset.compare); }
      if (e.target.closest("[data-cmp-open]")) return openCompare();
      if (e.target.closest("[data-cmp-clear]")) { picks = []; store.set("plt.compare", picks); tray(); marks(); }
    }, true);  // before app.js opens the card's details
    // the subnet details get a Compare button beside Add to workspace
    new MutationObserver(() => {
      const h = $("#drawer .drawer-head > div:last-child"), id = (location.hash.match(/^#sn(\d+)/) || [])[1] || $("#drawer [data-ws-add]")?.dataset.wsAdd;
      if (h && id && !h.querySelector("[data-compare]")) h.insertAdjacentHTML("afterbegin", button(id));
    }).observe($("#drawer"), { childList: true });
    for (const v of Object.keys(RISKV)) wireRisk(v);
    new MutationObserver(() => cards($("#new-body"))).observe($("#new-body"), { childList: true });
    tray();
  }
  const TRAY_VIEWS = ["dashboard", "explore", "recommend", "new", "tech", "caution", "scam", "workspace"];
  function onView(v) { document.body.classList.toggle("plt-tray-off", !TRAY_VIEWS.includes(v)); }
  function onData() { for (const v of Object.keys(RISKV)) riskBar(v); cards($("#new-body")); cards($("#caution-body")); cards($("#scam-body")); tray(); }

  return { init, onView, onData, button, open: openCompare };
})();
