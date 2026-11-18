/* Subnet Scout front-end: no build step, no dependencies. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Terminal output as HTML (the wallet's btcli, the Study lab): ANSI SGR colours (the 16, 256 and truecolor), bold, dim,
// italic and underline, and OSC 8 links (https only); everything else is escaped text.
function ansiHtml(text) {
  let out = "", st = {}, open = false, link = null;
  const close = () => { if (open) { out += "</span>"; open = false; } };
  const style = () => {
    close();
    const cls = [st.fg != null && typeof st.fg === "number" ? `a${st.fg}` : "", st.bg != null && typeof st.bg === "number" ? `ab${st.bg}` : "", st.b ? "a-b" : "", st.d ? "a-d" : "", st.i ? "a-i" : "", st.u ? "a-u" : ""].filter(Boolean);
    const css = [typeof st.fg === "string" ? `color:${st.fg}` : "", typeof st.bg === "string" ? `background:${st.bg}` : ""].filter(Boolean).join(";");
    if (cls.length || css) { out += `<span${cls.length ? ` class="${cls.join(" ")}"` : ""}${css ? ` style="${css}"` : ""}>`; open = true; }
  };
  const c256 = n => n < 16 ? n : n < 232 ? (() => { n -= 16; const v = x => x ? x * 40 + 55 : 0; return `rgb(${v(Math.floor(n / 36))},${v(Math.floor(n / 6) % 6)},${v(n % 6)})`; })() : `rgb(${(n - 232) * 10 + 8},${(n - 232) * 10 + 8},${(n - 232) * 10 + 8})`;
  for (const tok of text.split(/(\x1b\[[0-9;]*m|\x1b\]8;[^\x07\x1b]*(?:\x07|\x1b\\))/)) {
    if (!tok) continue;
    if (tok.startsWith("\x1b]8;")) {
      const url = tok.replace(/^\x1b\]8;[^;]*;/, "").replace(/(\x07|\x1b\\)$/, "");
      close();
      if (link) { out += "</a>"; link = null; }
      if (/^https:\/\//.test(url)) { out += `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">`; link = url; }
      style(); continue;
    }
    if (tok.startsWith("\x1b[")) {
      const ps = tok.slice(2, -1).split(";").map(x => +x || 0);
      for (let i = 0; i < ps.length; i++) {
        const p = ps[i];
        if (p === 0) st = {}; else if (p === 1) st.b = true; else if (p === 2) st.d = true; else if (p === 3) st.i = true; else if (p === 4) st.u = true;
        else if (p === 22) st.b = st.d = false; else if (p === 23) st.i = false; else if (p === 24) st.u = false;
        else if (p >= 30 && p <= 37) st.fg = p - 30; else if (p >= 90 && p <= 97) st.fg = p - 82; else if (p === 39) delete st.fg;
        else if (p >= 40 && p <= 47) st.bg = p - 40; else if (p >= 100 && p <= 107) st.bg = p - 92; else if (p === 49) delete st.bg;
        else if ((p === 38 || p === 48) && ps[i + 1] === 5) { st[p === 38 ? "fg" : "bg"] = c256(ps[i + 2]); i += 2; }
        else if ((p === 38 || p === 48) && ps[i + 1] === 2) { st[p === 38 ? "fg" : "bg"] = `rgb(${ps[i + 2] & 255},${ps[i + 3] & 255},${ps[i + 4] & 255})`; i += 4; }
      }
      style(); continue;
    }
    out += esc(tok);
  }
  close(); if (link) out += "</a>";
  return out;
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

const S = {
  data: null, meta: null, unit: store.get("unit", "tao"),
  sort: store.get("sort", { key: "emission_day", dir: -1 }),
  hidden: new Set(store.get("hiddenCols", ["description", "validators", "volume", "top_epoch"])),
  profile: null, view: "explore",
};
const NEW_DAYS = 122;
const RISK = {
  scam: { label: "High-risk signal", icon: "shield" }, avoid: { label: "Avoid", icon: "ban" },
  caution: { label: "Caution", icon: "alert" }, clear: { label: "Clear", icon: "check" },
};

// ---------- formatting ----------
function fmtNum(x, d) {
  if (x == null || isNaN(x)) return "–";
  const a = Math.abs(x);
  if (d == null) d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 1 ? 2 : a >= 0.01 ? 3 : a > 0 ? 4 : 0;
  return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}
function usd(x) {
  if (x == null || isNaN(x)) return "–";
  const a = Math.abs(x);
  return (x < 0 ? "-$" : "$") + (a >= 1e6 ? fmtNum(a / 1e6, 2) + "M" : a >= 1e4 ? fmtNum(a / 1e3, 1) + "k" : fmtNum(a, a >= 100 ? 0 : 2));
}
function money(tao) {
  if (tao == null) return "–";
  const p = S.data?.tao_usd;
  return S.unit === "usd" && p ? usd(tao * p) : fmtNum(tao) + " τ";
}
function moneyBoth(tao) {
  const p = S.data?.tao_usd;
  return `${fmtNum(tao)} τ${p ? ` <span class="faint">(${usd(tao * p)})</span>` : ""}`;
}
const pct = (x, d = 1) => x == null ? "–" : `${(x * 100).toFixed(d)}%`;
function delta(x) {
  if (x == null) return `<span class="delta faint">new</span>`;
  const dir = x > 0.005 ? "up" : x < -0.005 ? "down" : "flat";
  return `<span class="delta ${dir}">${icon(dir)}${(x * 100).toFixed(1)}%</span>`;
}
function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : `${Math.floor(s / 3600)}h ago`;
}
function until(ts) {
  const s = Math.round(ts - Date.now() / 1000);
  if (s <= 0) return "due now";
  const m = Math.floor(s / 60), sec = s % 60;
  return m >= 60 ? `in ${Math.floor(m / 60)}h ${m % 60}m` : `in ${m}m ${String(sec).padStart(2, "0")}s`;
}
const clock = ts => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
const stamp = ts => new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const short = k => k ? `${k.slice(0, 6)}…${k.slice(-4)}` : "";
function logo(r, size = "") {
  const initials = esc((r.name || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || r.netuid);
  if (r.links?.logo) return `<img class="logo ${size}" src="${esc(r.links.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback="${initials}">`;
  return `<span class="logo ${size}">${initials}</span>`;
}
function riskBadge(r) {
  const l = r.risk_level || "clear", m = RISK[l];
  return `<span class="badge ${l}" title="${esc(r.flags.map(f => f.text).join("\n") || "No flags")}">${icon(m.icon)}${m.label}</span>`;
}
function tierOf(r) { return S.meta?.tiers?.[r.tier] || { label: r.tier }; }
function rentText(r) {
  const t = tierOf(r);
  return t.rent_low == null ? "Unknown" : t.rent_high <= 15 ? "~$0" : `$${fmtNum(t.rent_low, 0)}–${fmtNum(t.rent_high, 0)}/mo`;
}
function linkIcons(r) {
  const L = r.links || {}, out = [];
  if (L.github) out.push(["github", L.github, "Source code"]);
  if (L.web) out.push(["globe", L.web, "Website"]);
  if (L.discord) out.push(["chat", L.discord, "Discord"]);
  if (L.contact && L.contact.includes("@")) out.push(["mail", "mailto:" + L.contact, L.contact]);
  out.push(["chart", L.taostats, "Taostats"]);
  return `<div class="links">${out.map(([i, h, t]) =>
    `<a href="${esc(/^(https?:|mailto:)/.test(h) ? h : "https://" + h)}" target="_blank" rel="noopener noreferrer" title="${esc(t)}">${icon(i)}</a>`).join("")}</div>`;
}
function spark(values, w = 84, h = 26) {
  const v = (values || []).filter(x => x != null);
  if (v.length < 2) return `<svg class="spark" viewBox="0 0 ${w} ${h}"></svg>`;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || hi || 1;
  const pts = v.map((y, i) => [i / (v.length - 1) * w, h - 2 - (y - lo) / span * (h - 4)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="area" d="${d}L${w},${h}L0,${h}Z"/><path d="${d}"/></svg>`;
}

// ---------- explorer columns ----------
const COLS = [
  { key: "netuid", label: "SN", cls: "sn sticky1", val: r => r.netuid, html: r => r.netuid, lock: true },
  { key: "name", label: "Subnet", cls: "sticky2", val: r => r.name.toLowerCase(), lock: true,
    html: r => `<div class="namecell">${logo(r)}<div style="min-width:0"><b>${esc(r.name)}</b><small>${esc(r.symbol)} · ${esc(r.field)}</small></div></div>` },
  { key: "task", label: "Task", val: r => r.task, html: r => `<div class="clip" title="${esc(r.task)}">${esc(r.task)}</div>` },
  { key: "miner_role", label: "Miners do", val: r => r.miner_role, html: r => `<div class="clip" title="${esc(r.miner_role)}">${esc(r.miner_role) || '<span class="faint">–</span>'}</div>` },
  { key: "num_uids", label: "Miners", cls: "r", val: r => r.num_uids, html: r => `<span class="num">${r.num_uids}/${r.max_uids}</span>`, title: "Registered UIDs / max" },
  { key: "earning_miners", label: "Earning", cls: "r", val: r => r.earning_miners, html: r => `<span class="num">${r.earning_miners}</span>`, title: "Miners with non-zero incentive (24h avg)" },
  { key: "top_miner", label: "Top miner /d", cls: "r", val: r => r.top_miner, html: r => `<span class="num">${money(r.top_miner)}</span>`, title: "Gross: what the subnet's top miner earned per day, before hardware, API and registration costs. Not what you can expect to make." },
  { key: "second_miner", label: "2nd miner /d", cls: "r", val: r => r.second_miner, html: r => `<span class="num">${money(r.second_miner)}</span>`, title: "Gross daily earnings of the second miner, before costs" },
  { key: "reg_cost", label: "Reg. cost", cls: "r", val: r => r.reg_cost, html: r => `<span class="num">${money(r.reg_cost)}</span>` },
  { key: "need", label: "What you need", val: r => r.tier,
    html: r => `<div class="tags"><span class="tag tier">${icon(tierIcon(r.tier))}${esc(tierOf(r).label)}</span>${r.software.slice(1, 4).map(s => `<span class="tag">${esc(s)}</span>`).join("")}${r.software.length > 4 ? `<span class="tag">+${r.software.length - 4}</span>` : ""}</div>` },
  { key: "emission_day", label: "Emission", cls: "r", val: r => r.emission_day,
    html: r => `<span class="num">${fmtNum(r.emission_day)} τ/d</span><br><span class="faint num">${pct(r.emission_share, 2)}</span>`, title: "TAO injected into the subnet per day, and share of all subnets" },
  { key: "emission_cycle_min", label: "Cycle", cls: "r", val: r => r.tempo, html: r => `<span class="num">${Math.round(r.emission_cycle_min)} min</span>`, title: "Epoch length (tempo): emission is paid out once per cycle" },
  { key: "payout_epoch", label: "Payout /epoch", cls: "r", val: r => r.payout?.tao_epoch ?? 0, title: "Value of all alpha paid to miners, validators and owner each epoch",
    html: r => r.payout ? `<span class="num">${money(r.payout.tao_epoch)}</span><br><span class="faint num">${fmtNum(r.payout.alpha_epoch, 0)} α</span>` : "–" },
  { key: "last_payout", label: "Last payout", val: r => r.payout?.last_at ?? 0, title: "When the last epoch paid out",
    html: r => r.payout ? `<span class="num" title="${esc(stamp(r.payout.last_at))} · block ${r.payout.last_block}">${clock(r.payout.last_at)}</span><br><span class="faint num">${ago(r.payout.last_at)}</span>` : "–" },
  { key: "next_payout", label: "Next payout", val: r => r.payout?.next_at ?? 0, title: "Estimated time of the next epoch payout (12 s blocks)",
    html: r => r.payout ? `<span class="num" title="${esc(stamp(r.payout.next_at))} · block ${r.payout.next_block}">${clock(r.payout.next_at)}</span><br><span class="faint num" data-until="${r.payout.next_at}">${until(r.payout.next_at)}</span>` : "–" },
  { key: "top_epoch", label: "Top miner /epoch", cls: "r", val: r => r.payout?.top_miner_epoch ?? 0,
    html: r => `<span class="num">${money(r.payout?.top_miner_epoch)}</span>` },
  { key: "immunity_hours", label: "Immune", cls: "r", val: r => r.immunity_blocks, html: r => `<span class="num">${fmtNum(r.immunity_hours, 0)}h</span>`, title: "Immunity period for new registrations" },
  { key: "field", label: "Field", val: r => r.field, html: r => `<span class="tag">${esc(r.field)}</span>` },
  { key: "links", label: "Links", val: r => r.links.github ? 1 : 0, html: linkIcons, nosort: true },
  { key: "conditions", label: "Conditions", val: r => r.conditions, html: r => `<div class="clip" title="${esc(r.conditions)}">${esc(r.hardware)}${r.conditions ? " · " + esc(r.conditions) : ""}</div>` },
  { key: "rent", label: "Rent budget", cls: "r", val: r => tierOf(r).rent_low ?? 1e9, html: r => `<span class="num">${rentText(r)}</span>` },
  { key: "trend", label: "Price 7d", val: r => r.price_change_7d ?? -9, html: r => `<div class="trend">${spark(r.series?.price)}${delta(r.price_change_7d)}</div>` },
  { key: "created_date", label: "Created", val: r => r.created_block, html: r => `<span class="num">${r.created_date}</span>${r.age_days <= NEW_DAYS ? ' <span class="badge new">New</span>' : ""}` },
  { key: "uid_available", label: "UID", val: r => r.uid_available ? 1 : 0,
    html: r => r.uid_available ? `<span class="ok">${icon("check")}Open</span>` : `<span class="no">${icon("ban")}${r.registration_allowed ? "Full" : "Closed"}</span>` },
  { key: "risk", label: "Risk", val: r => ({ scam: 3, avoid: 2, caution: 1 }[r.risk_level] || 0), html: riskBadge },
  { key: "description", label: "On-chain description", val: r => r.description, html: r => `<div class="clip">${esc(r.description)}</div>` },
  { key: "validators", label: "Validators", cls: "r", val: r => r.validators, html: r => `<span class="num">${r.validators}</span>` },
  { key: "volume", label: "Volume 24h", cls: "r", val: r => r.volume_24h ?? -1, html: r => `<span class="num">${r.volume_24h == null ? "–" : fmtNum(r.volume_24h, 0) + " τ"}</span>` },
];
// what kind of evidence a risk flag rests on (risk.py BASIS)
const BASIS = { chain: "On-chain measurement", history: "Historical trend", text: "Pattern in published text", missing: "Missing information", requirement: "Published requirement" };
const basis = f => f.basis ? ` <span class="flag-basis b-${f.basis}" title="What this flag rests on">${BASIS[f.basis] || esc(f.basis)}</span>` : "";
function tierIcon(t) {
  return { none: "browser", cpu: "server", api: "zap", gpu1: "chip", gpu2: "chips", gpu3: "rack", infra: "server", capital: "wallet" }[t] || "info";
}

function filtered() {
  if (!S.data) return [];
  const q = $("#q").value.trim().toLowerCase();
  const field = $("#f-field").value, tier = $("#f-tier").value, risk = $("#f-risk").value;
  const uid = $("#f-uid").checked, earn = $("#f-earn").checked;
  const terms = q.split(/\s+/).filter(Boolean);
  let rows = S.data.subnets.filter(r => {
    if (field && r.field !== field) return false;
    if (tier && r.tier !== tier) return false;
    if (uid && !r.uid_available) return false;
    if (earn && !r.earning_miners) return false;
    if (risk === "clear" && r.risk_level) return false;
    if (risk === "caution" && ["avoid", "scam"].includes(r.risk_level)) return false;
    if ((risk === "avoid" || risk === "scam") && r.risk_level !== risk) return false;
    if (terms.length) {
      const hay = [r.netuid, "sn" + r.netuid, r.name, r.symbol, r.task, r.miner_role, r.conditions, r.hardware, r.field,
        r.description, tierOf(r).label, ...r.software].join(" ").toLowerCase();
      if (!terms.every(t => hay.includes(t))) return false;
    }
    return true;
  });
  const col = COLS.find(c => c.key === S.sort.key) || COLS[0];
  rows.sort((a, b) => {
    const x = col.val(a), y = col.val(b);
    return (x > y ? 1 : x < y ? -1 : a.netuid - b.netuid) * S.sort.dir;
  });
  return rows;
}

function renderTable() {
  const cols = COLS.filter(c => c.lock || !S.hidden.has(c.key));
  $("#grid thead").innerHTML = "<tr>" + cols.map(c =>
    `<th class="${c.cls || ""} ${S.sort.key === c.key ? "sorted" : ""}" data-key="${c.key}" ${c.title ? `title="${esc(c.title)}"` : ""}>${c.label}${c.nosort ? "" : `<span class="sort">${S.sort.key === c.key ? (S.sort.dir > 0 ? "↑" : "↓") : "↕"}</span>`}</th>`).join("") + "</tr>";
  const rows = filtered();
  $("#rcount").textContent = `${rows.length} of ${S.data.subnets.length} subnets`;
  $("#grid tbody").innerHTML = rows.length ? rows.map(r =>
    `<tr data-id="${r.netuid}">${cols.map(c => `<td class="${c.cls || ""}">${c.html(r)}</td>`).join("")}</tr>`).join("")
    : `<tr><td colspan="${cols.length}"><div class="empty">No subnets match these filters.</div></td></tr>`;
}

function renderStats() {
  const s = S.data.subnets, p = S.data.tao_usd;
  const best = s.reduce((a, b) => (b.top_miner > (a?.top_miner || 0) ? b : a), null);
  const open = s.filter(r => r.uid_available).length;
  const emis = s.reduce((t, r) => t + r.emission_day, 0);
  const fresh = s.filter(r => r.age_days <= NEW_DAYS).length;
  const clear = s.filter(r => !r.risk_level).length;
  const tile = (ic, label, value, sub) => `<div class="stat"><div class="label">${icon(ic)}${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
  $("#stats").innerHTML = [
    tile("grid", "Active subnets", s.length, `${clear} with no risk flags`),
    tile("pickaxe", "UIDs open now", open, `${s.length - open} full or closed`),
    tile("zap", "Subnet emission / day", fmtNum(emis, 0) + " τ", p ? usd(emis * p) : ""),
    tile("trophy", "Best-paid miner / day", best ? money(best.top_miner) : "–", best ? `SN${best.netuid} ${esc(best.name)}` : ""),
    tile("sprout", "New in 4 months", fresh, "registered since " + new Date(Date.now() - NEW_DAYS * 864e5).toLocaleDateString()),
  ].join("");
}

// ---------- detail drawer ----------
function lineChart(id, title, t, values, fmt) {
  const pts = (values || []).map((v, i) => [t[i], v]).filter(p => p[1] != null);
  if (pts.length < 2) return `<div class="chart"><div class="title"><span>${title}</span></div><div class="empty" style="padding:20px">Not enough history yet - trends build up as the collector runs.</div></div>`;
  const ch = pct(pts.at(-1)[1] / pts[0][1] - 1);
  return `<div class="chart" data-chart="${id}"><div class="title"><span>${title}</span><span class="num">${fmt(pts.at(-1)[1])} · 7d ${ch}</span></div><svg></svg></div>`;
}
function drawChart(el, t, values, fmt) {
  const svg = $("svg", el); if (!svg) return;
  const pts = values.map((v, i) => [t[i], v]).filter(p => p[1] != null);
  const W = svg.clientWidth || 600, H = 130, L = 52, R = 8, T = 8, B = 20;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 *= 0.95; y1 = y1 * 1.05 || 1; }
  const pad = (y1 - y0) * 0.1; y0 = Math.max(0, y0 - pad); y1 += pad;
  const X = x => L + (x - x0) / (x1 - x0 || 1) * (W - L - R), Y = y => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
  const d = pts.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join("");
  const ticks = [y0, (y0 + y1) / 2, y1];
  const days = []; for (let k = 0; k <= 7; k++) { const x = x1 - k * 86400; if (x >= x0) days.push(x); }
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML =
    ticks.map(v => `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="axis" x="${L - 6}" y="${Y(v) + 3}" text-anchor="end">${fmt(v, true)}</text>`).join("") +
    days.map(x => `<text class="axis" x="${X(x)}" y="${H - 4}" text-anchor="middle">${new Date(x * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</text>`).join("") +
    `<path class="area" d="${d}L${X(pts.at(-1)[0])},${H - B}L${X(pts[0][0])},${H - B}Z"/><path class="line" d="${d}"/>` +
    `<line class="cross" y1="${T}" y2="${H - B}" visibility="hidden"/><circle class="pt" r="4.5" visibility="hidden"/><rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/>`;
  const tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; el.appendChild(tip);
  const cross = $(".cross", svg), dot = $(".pt", svg);
  svg.addEventListener("mousemove", e => {
    const bx = svg.getBoundingClientRect(), mx = (e.clientX - bx.left) * (W / bx.width);
    let best = pts[0]; for (const p of pts) if (Math.abs(X(p[0]) - mx) < Math.abs(X(best[0]) - mx)) best = p;
    const cx = X(best[0]), cy = Y(best[1]);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("visibility", "visible");
    tip.hidden = false; tip.style.left = (cx / W * bx.width) + "px"; tip.style.top = (cy / H * bx.height + 22) + "px";
    tip.innerHTML = `${new Date(best[0] * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} · <b>${fmt(best[1])}</b>`;
  });
  svg.addEventListener("mouseleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
}

function openDrawer(id) {
  const r = S.data.subnets.find(x => x.netuid === +id); if (!r) return;
  const t = r.series?.t || [];
  const priceFmt = (v, short) => short ? fmtNum(v, v < 0.01 ? 5 : 4) : fmtNum(v, 6) + " τ";
  const taoFmt = (v, short) => short ? fmtNum(v) : fmtNum(v) + " τ";
  const kv = (label, val) => `<div><span>${label}</span><b>${val}</b></div>`;
  $("#drawer").innerHTML = `
    <div class="drawer-head">${logo(r)}<div><h2>SN${r.netuid} · ${esc(r.name)}</h2><span class="muted">${esc(r.field)} · ${esc(r.symbol)} · created ${r.created_date}</span></div>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">${riskBadge(r)}${Slack.shareButton("subnet", r.netuid)}${Wallet.button(r.netuid)}${Workspace.askButton(r.netuid, "btn sm")}${Workspace.addButton(r.netuid, "btn sm")}<button class="iconbtn" id="dclose" aria-label="Close">${icon("close")}</button></div></div>
    <div class="drawer-body">
      <div class="card"><h3>${icon("info")}Task</h3><p style="margin:0">${esc(r.task)}</p>${r.description && r.description !== r.task ? `<p class="faint" style="margin:6px 0 0">“${esc(r.description)}”</p>` : ""}<div style="margin-top:10px">${linkIcons(r)}</div></div>
      <div class="card"><h3>${icon("pickaxe")}What miners do</h3><p style="margin:0">${esc(r.miner_role) || "Not documented."}</p></div>
      <div class="card"><h3>${icon("coins")}Miner economics (24h avg)</h3><div class="kv">
        ${kv("Top miner / day", moneyBoth(r.top_miner))}${kv("2nd miner / day", moneyBoth(r.second_miner))}${kv("Median earner / day", moneyBoth(r.median_miner))}
        ${kv("Earning miners", `${r.earning_miners} of ${r.num_uids}`)}${kv("Top miner's share", pct(r.top_share, 0))}${kv("Owner / burn share", pct(r.owner_burn_share, 0))}
        ${kv("Registration cost", moneyBoth(r.reg_cost))}${kv("UID", r.uid_available ? "Available" : r.registration_allowed ? "Full / rate-limited" : "Registration closed")}${kv("Open / prunable slots", `${r.open_slots} / ${r.prunable_uids}`)}
        ${kv("Emission", `${fmtNum(r.emission_day)} τ/d (${pct(r.emission_share, 2)})`)}${kv("Emission cycle", `${r.tempo} blocks ≈ ${r.emission_cycle_min} min`)}${kv("Immunity", `${r.immunity_blocks} blocks ≈ ${r.immunity_hours} h`)}
        ${kv("Alpha price", fmtNum(r.price, 6) + " τ")}${kv("Price 24h / 7d", `${pct(r.price_change_24h)} / ${pct(r.price_change_7d)}`)}${kv("Net TAO flow / day", fmtNum(r.tao_flow_day) + " τ")}
      </div></div>
      ${payoutCard(r)}
      ${Mining.compsCard(r.netuid)}
      <div class="card"><h3>${icon("wrench")}Equipment</h3><div class="kv">
        ${kv("Hardware tier", esc(tierOf(r).label))}${kv("Rent budget", rentText(r))}${kv("Hardware", esc(r.hardware))}</div>
        <p style="margin:10px 0 4px" class="muted"><b>Conditions:</b> ${esc(r.conditions) || "Not published."}</p>
        <div class="tags" style="max-width:none">${r.software.map(s => `<span class="tag">${esc(s)}</span>`).join("")}</div></div>
      <div class="card"><h3>${icon("chart")}7-day trends</h3><div class="charts">
        ${lineChart("price", "Alpha price (τ)", t, r.series?.price, priceFmt)}
        ${lineChart("reg", "Registration cost (τ)", t, r.series?.reg_cost, taoFmt)}
        ${lineChart("em", "Emission (τ / day)", t, r.series?.emission_day, taoFmt)}
      </div></div>
      <div class="card"><h3>${icon("alert")}Risk flags</h3>${r.flags.length ? `<ul class="flags">${r.flags.map(f => `<li><span class="badge ${f.level}">${icon(RISK[f.level].icon)}${RISK[f.level].label}</span><span>${esc(f.text)}${basis(f)}</span></li>`).join("")}</ul>
        <p class="muted small" style="margin:6px 0 0">Rule-based signals, not verdicts. Data from the chain snapshot of block ${S.data?.block?.toLocaleString?.() || "–"}${S.data?.updated ? `, ${ago(S.data.updated)}` : ""}; flags update when the chain, market or subnet data changes.</p>` : `<p class="muted" style="margin:0">No risk flags from current data.</p>`}</div>
    </div>`;
  $("#drawer").classList.add("open"); $("#scrim").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
  $("#dclose").onclick = closeDrawer;
  requestAnimationFrame(() => {
    const m = { price: [r.series?.price, priceFmt], reg: [r.series?.reg_cost, taoFmt], em: [r.series?.emission_day, taoFmt] };
    $$("[data-chart]", $("#drawer")).forEach(el => drawChart(el, t, m[el.dataset.chart][0], m[el.dataset.chart][1]));
  });
  history.replaceState(null, "", `#sn${r.netuid}`);
}
function payoutCard(r) {
  const p = r.payout; if (!p) return "";
  const kv = (label, val, sub) => `<div><span>${label}</span><b>${val}</b>${sub ? `<small class="faint num">${sub}</small>` : ""}</div>`;
  const prog = Math.min(100, p.blocks_since / (r.tempo + 1) * 100);
  const rows = (r.top_payees || []).map((m, i) => `<tr>
      <td class="num">${i + 1}</td><td class="num">${m.uid}</td>
      <td><a class="num" href="https://taostats.io/hotkey/${esc(m.hotkey)}" target="_blank" rel="noopener noreferrer" title="${esc(m.hotkey)}">${short(m.hotkey)}</a><br><span class="faint num" title="Coldkey ${esc(m.coldkey)}">${short(m.coldkey)}</span></td>
      <td class="r num">${fmtNum(m.alpha_epoch)} α<br><span class="faint">${money(m.tao_epoch)}</span></td>
      <td class="r num">${money(m.tao_day)}</td>
      <td class="r num">${pct(m.incentive, 1)}</td>
      <td class="num">${new Date(m.registered_at * 1000).toLocaleDateString()}${m.immune ? ' <span class="badge new">Immune</span>' : ""}</td></tr>`).join("");
  return `<div class="card"><h3>${icon("coin")}Payouts</h3>
    <div class="epoch"><div class="epoch-head"><span>Current epoch</span><span class="num">${p.blocks_since} / ${r.tempo + 1} blocks · next payout <b data-until="${p.next_at}">${until(p.next_at)}</b></span></div>
      <div class="bar big"><i style="width:${prog}%"></i></div></div>
    <div class="kv">
      ${kv("Last payout", clock(p.last_at), `${stamp(p.last_at)} · #${p.last_block.toLocaleString()}`)}
      ${kv("Next payout", clock(p.next_at), `${stamp(p.next_at)} · #${p.next_block.toLocaleString()}`)}
      ${kv("Cycle", `${Math.round(r.emission_cycle_min)} min`, `${p.epochs_day} payouts / day`)}
      ${kv("Pending for next payout", `${fmtNum(p.pending_alpha)} α`, `≈ ${fmtNum(p.pending_tao)} τ${S.data?.tao_usd ? " · " + usd(p.pending_tao * S.data.tao_usd) : ""}`)}
      ${kv("Emission / epoch", `${fmtNum(p.alpha_epoch, 0)} α`, `≈ ${fmtNum(p.tao_epoch)} τ`)}
      ${kv("Emission / day", `${fmtNum(p.alpha_day, 0)} α`, `≈ ${fmtNum(p.tao_day)} τ`)}
      ${kv("TAO into pool / epoch", `${fmtNum(p.tao_in_epoch)} τ`, `${fmtNum(r.emission_day)} τ / day`)}
      ${kv("All miners / epoch", money(p.miner_pool_epoch), `${r.earning_miners} earning`)}
      ${kv("Owner / epoch", money(p.owner_epoch), pct(r.owner_burn_share, 0) + " of miner pool")}
      ${kv("Top miner / epoch", money(p.top_miner_epoch))}${kv("2nd miner / epoch", money(p.second_miner_epoch))}${kv("Median / epoch", money(p.median_miner_epoch))}
    </div>
    <p class="fine">Each epoch's alpha is split by Yuma Consensus: about 41% to miners (by incentive), 41% to validators and stakers, 18% to the subnet owner. α is converted at the current price of ${fmtNum(r.price, 6)} τ.</p>
    ${rows ? `<h4 class="sub">Top paid miners · last epoch</h4><div class="tablewrap flat"><table class="grid mini-table"><thead><tr><th>#</th><th>UID</th><th>Hotkey / coldkey</th><th class="r">Per epoch</th><th class="r">Per day</th><th class="r">Incentive</th><th>Registered</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
  </div>`;
}
function closeDrawer() {
  $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true");
  // only undo the drawer's own #sn link: other deep links (#whiteboard/12, #agents/3) stay
  if (location.hash.startsWith("#sn")) history.replaceState(null, "", location.pathname + (S.view !== "explore" ? "#" + S.view : ""));
}

// ---------- card views ----------
function scard(r, extra = "") {
  return `<div class="scard" data-id="${r.netuid}">
    <div class="scard-head">${logo(r)}<div><h3>SN${r.netuid} · ${esc(r.name)}</h3><small>${esc(r.field)} · ${r.created_date}</small></div>${riskBadge(r)}</div>
    <div class="muted clip" style="max-width:none">${esc(r.task)}</div>
    <div class="mini"><div><span>Top miner/d</span><b>${money(r.top_miner)}</b></div><div><span>Earning</span><b>${r.earning_miners}/${r.num_uids}</b></div><div><span>Reg. cost</span><b>${money(r.reg_cost)}</b></div></div>
    ${extra}
    ${r.flags.length ? `<ul class="flags">${r.flags.map(f => `<li><span class="badge ${f.level}">${icon(RISK[f.level].icon)}</span><span class="muted">${esc(f.text)}${basis(f)}</span></li>`).join("")}</ul>` : ""}
  </div>`;
}
function renderCaution() {
  const s = S.data.subnets;
  const avoid = s.filter(r => r.risk_level === "avoid").sort((a, b) => b.emission_day - a.emission_day);
  const caut = s.filter(r => r.risk_level === "caution").sort((a, b) => b.emission_day - a.emission_day);
  $("#caution-body").innerHTML =
    `<h2 class="section-title">${icon("ban")}Avoid <span class="count faint">${avoid.length}</span></h2><div class="card-grid">${avoid.map(r => scard(r)).join("") || '<div class="empty">None</div>'}</div>` +
    `<h2 class="section-title">${icon("alert")}Caution <span class="count faint">${caut.length}</span></h2><div class="card-grid">${caut.map(r => scard(r)).join("") || '<div class="empty">None</div>'}</div>`;
}
function renderNew() {
  const s = S.data.subnets.filter(r => r.age_days <= NEW_DAYS).sort((a, b) => b.created_block - a.created_block);
  $("#new-body").innerHTML = s.map(r => scard(r,
    `<div class="mini"><div><span>Age</span><b>${fmtNum(r.age_days, 0)} days</b></div><div><span>Emission</span><b>${fmtNum(r.emission_day)} τ/d</b></div><div><span>Price 7d</span><b>${delta(r.price_change_7d)}</b></div></div><div class="trend wide">${spark(r.series?.price, 300, 34)}</div>`)).join("")
    || '<div class="empty">No subnets registered in the last 4 months.</div>';
}
function renderScam() {
  const s = S.data.subnets.filter(r => r.risk_level === "scam").sort((a, b) => b.emission_day - a.emission_day);
  $("#scam-body").innerHTML = s.map(r => scard(r)).join("") || '<div class="empty">No high-risk signals in current data.</div>';
}
function renderCounts() {
  const s = S.data.subnets;
  $("#c-explore").textContent = s.length;
  $("#c-caution").textContent = s.filter(r => ["avoid", "caution"].includes(r.risk_level)).length;
  $("#c-new").textContent = s.filter(r => r.age_days <= NEW_DAYS).length;
  $("#c-scam").textContent = s.filter(r => r.risk_level === "scam").length;
}

// ---------- recommend ----------
const WEIGHTS = [
  ["profit", "Profit", "Estimated net monthly earnings after rent and registration"],
  ["access", "Accessibility", "Fits your hardware, budget and TAO; UID open"],
  ["competition", "Fair competition", "Rewards spread across many miners vs. one winner"],
  ["stability", "Stability", "Age, emission share, low owner take, public code"],
  ["momentum", "Momentum", "7-day price trend and net TAO inflow"],
  ["fit", "Skill fit", "Matches the fields you picked"],
];
const PRESETS = {
  beginner: { hardware: "cpu", own_hardware: false, budget_usd: 100, capital_tao: 0.5, risk: "low", fields: [], exclude_winner_take_all: true, min_age_days: 90,
    weights: { profit: 6, access: 10, competition: 8, stability: 8, momentum: 2, fit: 3 } },
  gpu: { hardware: "gpu1", own_hardware: true, budget_usd: 100, capital_tao: 1, risk: "medium", fields: ["Vision & Media", "Model Training", "Inference"], exclude_winner_take_all: false, min_age_days: 0,
    weights: { profit: 8, access: 9, competition: 5, stability: 5, momentum: 3, fit: 6 } },
  pro: { hardware: "gpu3", own_hardware: false, budget_usd: 5000, capital_tao: 5, risk: "high", fields: [], exclude_winner_take_all: false, min_age_days: 0,
    weights: { profit: 10, access: 5, competition: 4, stability: 4, momentum: 5, fit: 2 } },
  dev: { hardware: "cpu", own_hardware: false, budget_usd: 250, capital_tao: 1, risk: "medium", fields: ["LLM & Agents", "Software Dev", "Security & Alignment"], exclude_winner_take_all: false, min_age_days: 0,
    weights: { profit: 8, access: 8, competition: 5, stability: 5, momentum: 3, fit: 8 } },
};

function initRecommend() {
  const d = S.meta.defaults;
  S.profile = { ...structuredClone(d), ...store.get("profile", {}) };
  S.profile.weights = { ...d.weights, ...(S.profile.weights || {}) };
  $("#fields").innerHTML = S.meta.fields.map(f => `<button type="button" class="chip" data-field="${esc(f)}">${esc(f)}</button>`).join("");
  $("#weights").innerHTML = WEIGHTS.map(([k, l, h]) =>
    `<div class="field" title="${esc(h)}"><label>${l} <output id="o-w-${k}"></output></label><input type="range" min="0" max="10" step="1" data-w="${k}"></div>`).join("");
  const form = $("#rec-form");
  form.addEventListener("submit", e => e.preventDefault());
  form.addEventListener("input", e => {
    const el = e.target;
    if (el.dataset.w) S.profile.weights[el.dataset.w] = +el.value;
    else if (el.name) S.profile[el.name] = el.type === "checkbox" ? el.checked : +el.value;
    syncForm(); runRecommend();
  });
  form.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.hw) S.profile.hardware = b.dataset.hw;
    else if (b.dataset.risk) S.profile.risk = b.dataset.risk;
    else if (b.dataset.field) {
      const f = new Set(S.profile.fields); f.has(b.dataset.field) ? f.delete(b.dataset.field) : f.add(b.dataset.field); S.profile.fields = [...f];
    } else if (b.dataset.preset) Object.assign(S.profile, structuredClone(PRESETS[b.dataset.preset]));
    else if (b.id === "rec-reset") S.profile = structuredClone(d);
    else return;
    syncForm(); runRecommend();
  });
  syncForm();
}
function syncForm() {
  const p = S.profile, f = $("#rec-form");
  $$("[data-hw]", f).forEach(b => b.setAttribute("aria-pressed", b.dataset.hw === p.hardware));
  $$("[data-risk]", f).forEach(b => b.setAttribute("aria-pressed", b.dataset.risk === p.risk));
  $$("[data-field]", f).forEach(b => b.setAttribute("aria-pressed", p.fields.includes(b.dataset.field)));
  for (const n of ["budget_usd", "capital_tao", "min_age_days", "count"]) f.elements[n].value = p[n];
  for (const n of ["own_hardware", "only_uid_available", "exclude_avoid", "exclude_scam", "exclude_winner_take_all"]) f.elements[n].checked = !!p[n];
  $$("[data-w]", f).forEach(el => { el.value = p.weights[el.dataset.w]; $("#o-w-" + el.dataset.w).textContent = p.weights[el.dataset.w]; });
  $("#o-budget").textContent = "$" + fmtNum(p.budget_usd, 0) + "/mo";
  $("#o-capital").textContent = fmtNum(p.capital_tao, 2) + " τ" + (S.data?.tao_usd ? ` (${usd(p.capital_tao * S.data.tao_usd)})` : "");
  $("#o-age").textContent = p.min_age_days ? `${p.min_age_days} days` : "any";
  $("#o-count").textContent = p.count;
  Settings.save({ profile: p });
}
let recTimer, recSeq = 0;
function runRecommend() {
  clearTimeout(recTimer);
  recTimer = setTimeout(async () => {
    if (!S.data?.subnets?.length) return;
    const seq = ++recSeq, list = $("#rec-list");
    if (!list.querySelector(".rec:not(.sk-card)")) { list.innerHTML = Loading.cards(3, "rec"); $("#rec-summary").textContent = "Ranking subnets for your profile…"; }
    list.classList.add("updating");
    const res = await api("/api/recommend", { method: "POST", body: S.profile }).catch(() => null);
    if (seq !== recSeq) return;
    list.classList.remove("updating");
    if (!res) { $("#rec-summary").textContent = "Couldn't load recommendations. Change a setting to try again."; return; }
    renderRecs(res);
  }, 180);
}
// how a match score is made, what it assumes, how sensitive the net is to the TAO price, and how much to trust it (the
// 11-07 evaluation: transparent scoring, net profitability, sensitivity, confidence and freshness)
function recHow(o, r) {
  const w = S.profile.weights || {}, wsum = Object.values(w).reduce((a, b) => a + b, 0) || 1, b = o.budget;
  const rows = WEIGHTS.map(([k, l]) => [l, w[k] || 0, o.factors[k], (w[k] || 0) * o.factors[k] / wsum * 100]);
  const base = rows.reduce((s, x) => s + x[3], 0);
  const net = k => b.est_gross_month_usd * k - (b.cost_month_usd ?? 0) - (b.reg_cost_usd ?? 0) * k;
  const low = [r.tier === "unknown" && "the hardware needs aren't published", r.earning_miners < 5 && "few miners earn, so pay figures rest on very few points",
    r.age_days < 30 && "the subnet is under a month old", r.flags.some(f => f.code === "early") && "its docs call the mechanism early-stage"].filter(Boolean);
  return `<details class="rec-how"><summary>${icon("info")}How this score is made</summary>
    <table class="rec-how-t"><thead><tr><th>Factor</th><th class="r">Your weight</th><th class="r">Value</th><th class="r">Points</th></tr></thead><tbody>
      ${rows.map(([l, wt, v, pts]) => `<tr><td>${l}</td><td class="r num">${wt}</td><td class="r num">${Math.round(v * 100)}/100</td><td class="r num">${fmtNum(pts, 1)}</td></tr>`).join("")}
      <tr><td>Weighted total</td><td></td><td></td><td class="r num">${fmtNum(base, 1)}</td></tr>
      <tr><td>Risk and access penalty</td><td></td><td></td><td class="r num">× ${fmtNum(o.penalty, 2)}</td></tr>
      <tr><th>Match score</th><td></td><td></td><th class="r num">${fmtNum(o.score, 0)}</th></tr></tbody></table>
    <p class="muted small"><b>Assumptions:</b> pay is the median earner's (or half the runner-up's where one miner dominates) × the ${fmtNum((b.p_earn ?? 0) * 100, 0)}% of miners who earn anything, not the top miner's gross; hardware rent is the middle of the range${b.cost_month_usd != null ? ` (${usd(b.cost_month_usd)}/month)` : ""}; registration is paid once; API costs aren't included; TAO at the snapshot price.</p>
    ${b.est_gross_month_usd ? `<p class="muted small"><b>If TAO moves:</b> net / month ${usd(net(0.7))} at −30% · ${usd(net(1))} now · ${usd(net(1.3))} at +30%.</p>` : ""}
    <p class="muted small"><b>Confidence:</b> ${low.length ? `lower: ${low.join("; ")}.` : "normal for an estimate from chain data."} Data from block ${S.data?.block?.toLocaleString?.() || "–"}${S.data?.updated ? `, ${ago(S.data.updated)}` : ""}.</p></details>`;
}
function renderRecs(res) {
  const by = Object.fromEntries(S.data.subnets.map(r => [r.netuid, r]));
  $("#rec-summary").innerHTML = `${res.considered ?? 0} subnets passed your constraints; showing the top ${res.results.length}.` +
    (res.results.length < 5 ? ` <b>Fewer than 5 match: loosen a constraint to see more.</b>` : "");
  $("#rec-list").innerHTML = res.results.map((o, i) => {
    const r = by[o.netuid], b = o.budget;
    return `<article class="rec">
      <div class="rec-head"><span class="rank">${i + 1}</span>${logo(r)}<div><h3>SN${r.netuid} · ${esc(r.name)}</h3><span class="muted">${esc(r.field)} · ${esc(tierOf(r).label)}</span></div>
        <div class="score"><b>${fmtNum(o.score, 0)}</b><small>match score</small></div></div>
      <div class="factors">${WEIGHTS.map(([k, l]) => `<div class="factor" title="${l}: ${Math.round(o.factors[k] * 100)}/100"><span>${l}</span><div class="bar"><i style="width:${Math.round(o.factors[k] * 100)}%"></i></div></div>`).join("")}</div>
      ${recHow(o, r)}
      <div class="rec-grid">
        <div><h4>${icon("info")}Task</h4><p>${esc(r.task)}</p></div>
        <div><h4>${icon("pickaxe")}What miners do</h4><p>${esc(r.miner_role) || "Not documented."}</p></div>
        <div><h4>${icon("bulb")}Why it's recommended</h4><ul>${o.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>
        <div><h4>${icon("wrench")}What you need</h4><p>${esc(r.hardware)}</p><div class="tags" style="margin-top:6px;max-width:none">${r.software.map(s => `<span class="tag">${esc(s)}</span>`).join("")}</div></div>
        <div class="span2"><h4>${icon("wallet")}Budget</h4><div class="money">
          <div><span>Hardware rent</span><b>${esc(b.rent_text)}</b></div>
          <div><span>Registration</span><b>${fmtNum(b.reg_cost_tao)} τ${b.reg_cost_usd != null ? " · " + usd(b.reg_cost_usd) : ""}</b></div>
          <div title="Median earner's pay × share of miners who earn - not the top miner's pay"><span>Expected gross / month</span><b>${usd(b.est_gross_month_usd)}</b></div>
          <div title="Expected gross minus hardware rent and registration"><span>Expected net / month</span><b>${usd(b.est_net_month_usd)}</b></div>
          <div><span>Reg. payback</span><b>${b.payback_days == null ? "–" : b.payback_days < 1 ? "< 1 day" : fmtNum(b.payback_days, 1) + " days"}</b></div></div></div>
        <div class="span2"><h4>${icon("trophy")}How to become a top miner</h4><ul>${o.how_to_top.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>
        ${o.watch_out.length ? `<div class="span2"><h4>${icon("alert")}Watch out</h4><ul>${o.watch_out.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      </div>
      <div class="row"><button class="btn" data-open="${r.netuid}">${icon("chart")}Full details &amp; 7-day trends</button>${Workspace.addButton(r.netuid)}</div>
    </article>`;
  }).join("") || `<div class="empty">No subnet passes these constraints. Try raising your budget or unticking "Only subnets with a UID available".</div>`;
}

// ---------- shell ----------
function sideOpen(open) {
  $("#side").classList.toggle("open", open);
  $("#side-scrim").classList.toggle("open", open);
  $("#menu-btn").setAttribute("aria-expanded", open);
}
function setView(v) {
  if (v === "studio") { Agents.ops(); v = "agents"; }  // Agent operations is part of Agents now: old links land on its operations side
  if (v === "command" && !Control.classic()) v = "control";  // the Control Hub is the overview now; its "classic" link still opens the Command Center
  S.view = v;
  $$("nav.side [data-view]").forEach(b => b.setAttribute("aria-current", b.dataset.view === v ? "page" : "false"));
  sideOpen(false);
  $$(".view").forEach(s => s.hidden = s.id !== "view-" + v);
  if (!location.hash.startsWith("#sn")) history.replaceState(null, "", v === "explore" ? location.pathname : "#" + v);
  if (v === "recommend") runRecommend();
  if (v === "admin") Admin.open();
  if (v === "docker") Docker.open();
  if (v === "devops") DevOps.open();
  if (v === "system") System.open();
  if (v === "cluster") Cluster.open();
  if (v === "apps") Paas.apps.open();
  if (v === "functions") Paas.functions.open();
  if (v === "machines") Machines.open(); else Machines.close();  // the console's connection only lives while the page shows
  if (v === "developer") window.DevHost ? DevHost.open() : addEventListener("load", () => DevHost.open(), { once: true });  // Developer (dvp-*.js): built once, kept while away
  if (v === "dns") DNSAdmin.open();
  Assist.onView(v);  // the agent beside the page follows it
  Guide.onView(v);  // the page's tour, offered on a first visit
  Platform.onView(v);  // where you are in the top bar, and the platform look outside the agent pages
  Shell.onView(v);  // the health line and status bar; a My subnets link stays marked only on My subnets
  Journey.onView(v);  // the sidebar's Progress stages: Goal, Work, Evidence, Approval, Result (journey.js)
  if (v === "connectors") Connectors.open();
  if (v === "notifications") NotifyPage.open();
  if (v === "agents") Agents.open();
  if (v === "workspace") Workspace.open(); else Team.stop();  // the Team tab's live stream only runs while it's open
  if (v === "dashboard") Dashboard.open();
  if (v === "command" || v === "approvals") Command.open(v); else Command.stop();  // the Command Center and Approval Center poll only while they show
  Hubs.onView(v);  // the AXoR 2.0 hubs (Intelligence, Organization, Projects, Missions, Evaluation, Workspace home, Platform overview, Settings)
  if (v === "slack") Slack.open();
  if (v === "source") Source.open();
  if (v === "drive") Drive.open();
  if (v === "wallet") Wallet.open();
  if (v === "study") Study.open(); else Study.stop();  // no reading aloud or listening once you leave
  if (v === "profile") Profile.open();
  if (v === "tech") Tech.open();
  if (v === "help") Help.open();
  if (v === "hq") HQ.open();
  if (v !== "agents") Studio.stop();  // Agent operations (inside Agents) polls only while it shows; Agents.open() starts it
  if (v === "knowledge" || v === "myknowledge") Knowledge.open(v); else Knowledge.stop();  // the Knowledge Hub (company) and My Knowledge
  if (v === "market") Market.open(); else Market.stop();  // the Agent Marketplace
  if (v === "topology") Topology.open(); else Topology.stop();  // the Unified control panel (topology.js) polls only while it shows
  if (v === "evolution") Evolution.open(); else Evolution.stop();  // the Evolution Lab (AXoR 5.0) polls only while it shows
  if (v === "mos") MissionOS.open(); else MissionOS.stop();  // Mission Control polls only while it shows
  if (v === "mining") Mining.open(); else Mining.stop();  // the campaign's live stream only runs while the page shows
  if (v === "teams") MiningWork.open(); else MiningWork.stop();  // Competition teams poll only while the page shows
  if (v === "portfolio") Portfolio.open(); else Portfolio.stop();  // and the portfolio
  if (v === "company") Company.open(); else Company.stop();  // and the company
  if (v === "org") Organization.open(); else Organization.stop();  // and the organization
  if (v === "control") Control.open(); else Control.stop();  // the Control Hub (control.js) and the node the sidebar's tree selected
  if (v === "workforce") Workforce.open(); else Workforce.stop();  // the same for the workforce's stream
  if (v === "swarm") Swarm.open(); else Swarm.stop();  // and the Agent Swarm (swarm.js) polls only while it shows
  if (v === "infiagent") InfiAgent.open(); else InfiAgent.stop();  // and for long tasks'
  if (v === "whiteboard") Whiteboard.open(); else Whiteboard.stop();  // leaving saves and stops live sync
}
function renderAll() {
  if (!S.data?.subnets?.length) return;
  renderCounts(); renderStats(); renderTable(); renderCaution(); renderNew(); renderScam();
  if (S.view === "recommend") runRecommend();
  Workspace.onData();
  Dashboard.onData();
  Hubs.onData();
  Wallet.onData();
  Notify.refresh();
  $("#taoprice").innerHTML = S.data.tao_usd ? `τ ${usd(S.data.tao_usd)}` : "τ –";
}
function setLive() {
  const el = $("#live"), d = S.data;
  el.classList.toggle("on", d?.status === "live"); el.classList.toggle("err", !!d?.status?.startsWith("error"));
  $("#live-txt").textContent = !d?.block ? "Collecting first snapshot…" : `Live · block ${d.block.toLocaleString()} · ${ago(d.updated)}`;
  el.title = $("#live-txt").textContent;
}
function toast(msg, o) { UI.toast(msg, o); }  // kinds, Undo and timing live in ui.js
async function load(announce) {
  const d = await api("/api/subnets").catch(() => null);
  if (!d) { if (!S.data) setTimeout(load, 5000); return; }  // first load failed: retry rather than leave placeholders up
  const first = !S.data?.subnets?.length;
  S.data = d; setLive(); Shell.paint();
  if (!d.subnets.length) { setTimeout(load, 5000); return; }
  renderAll();
  if (first && location.hash.startsWith("#sn")) openDrawer(location.hash.slice(3));
  // No toast on chain updates (BUG-01 / NFR-008): the header's live indicator already shows the block, and a
  // small white board saying "Updated to block N" popping up at the bottom centre every refresh was noise.
}
function connect() {
  const es = new EventSource("/api/stream");
  es.addEventListener("update", () => load(true));
  es.addEventListener("auth", () => { es.close(); location.reload(); });
  es.onerror = () => { $("#live").classList.remove("on"); };
}
function exportCsv() {
  const rows = filtered();
  const keys = ["netuid", "name", "field", "task", "miner_role", "num_uids", "max_uids", "earning_miners", "top_miner", "second_miner", "median_miner",
    "reg_cost", "tier", "hardware", "emission_day", "emission_share", "tempo", "immunity_blocks", "price", "price_change_7d", "created_date", "uid_available", "risk_level"];
  const q = v => { const s = Array.isArray(v) ? v.join("; ") : String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csv = [keys.join(","), ...rows.map(r => keys.map(k => q(r[k])).join(",")), ""].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = `subnets-block-${S.data.block}.csv`; a.click();
}
function columnsPopover(btn) {
  let pop = $("#colpop");
  if (pop) { pop.remove(); return; }
  pop = document.createElement("div"); pop.id = "colpop"; pop.className = "popover";
  pop.innerHTML = COLS.filter(c => !c.lock).map(c => `<label><input type="checkbox" data-col="${c.key}" ${S.hidden.has(c.key) ? "" : "checked"}> ${c.label}</label>`).join("");
  const b = btn.getBoundingClientRect();
  pop.style.top = (b.bottom + scrollY + 6) + "px"; pop.style.left = Math.max(16, Math.min(b.left, innerWidth - 400)) + "px";
  document.body.appendChild(pop);
  pop.addEventListener("change", e => {
    const k = e.target.dataset.col; e.target.checked ? S.hidden.delete(k) : S.hidden.add(k);
    store.set("hiddenCols", [...S.hidden]); renderTable();
  });
  setTimeout(() => document.addEventListener("click", function off(e) { if (!pop.contains(e.target) && e.target !== btn) { pop.remove(); document.removeEventListener("click", off); } }), 0);
}

async function init() {
  hydrateIcons();
  $$("#unit button").forEach(b => b.setAttribute("aria-pressed", b.dataset.unit === S.unit));
  $("#unit").onclick = e => {
    const u = e.target.dataset.unit; if (!u) return;
    S.unit = u; Settings.save({ unit: u }); $$("#unit button").forEach(b => b.setAttribute("aria-pressed", b.dataset.unit === u)); renderAll();
  };
  $$("nav.side [data-view]").forEach(b => b.onclick = () => setView(b.dataset.view));
  // sidebar: collapsible to icons on desktop (remembered), slide-out menu on phones
  const side = $("#side");
  side.classList.toggle("collapsed", !!store.get("sideCollapsed", false));
  $("#side-collapse").onclick = () => {
    side.classList.toggle("collapsed");
    store.set("sideCollapsed", side.classList.contains("collapsed"));
    $("#side-collapse").title = side.classList.contains("collapsed") ? "Expand sidebar" : "Collapse sidebar";
  };
  $("#menu-btn").onclick = () => sideOpen(!side.classList.contains("open"));
  $("#side-scrim").onclick = () => sideOpen(false);
  S.meta = Auth.meta || await api("/api/meta");
  $("#f-field").innerHTML += S.meta.fields.map(f => `<option>${esc(f)}</option>`).join("");
  $("#f-tier").innerHTML += Object.entries(S.meta.tiers).map(([k, t]) => `<option value="${k}">${esc(t.label)}</option>`).join("");
  const F = store.get("filters", {});
  for (const id of ["q", "f-field", "f-tier", "f-risk"]) if (F[id] != null) $("#" + id).value = F[id];
  for (const id of ["f-uid", "f-earn"]) if (F[id] != null) $("#" + id).checked = F[id];
  const onFilter = () => {
    store.set("filters", { q: $("#q").value, "f-field": $("#f-field").value, "f-tier": $("#f-tier").value, "f-risk": $("#f-risk").value, "f-uid": $("#f-uid").checked, "f-earn": $("#f-earn").checked });
    renderTable();
  };
  $$(".toolbar input, .toolbar select", $("#view-explore")).forEach(el => el.addEventListener("input", onFilter));
  $("#grid thead").addEventListener("click", e => {
    const th = e.target.closest("th"); if (!th || COLS.find(c => c.key === th.dataset.key)?.nosort) return;
    const k = th.dataset.key;
    S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (["name", "netuid", "field", "task"].includes(k) ? 1 : -1) };
    store.set("sort", S.sort); renderTable();
  });
  document.addEventListener("click", e => {
    const w = e.target.closest("[data-ws-add]"); if (w) return Workspace.toggle(w.dataset.wsAdd);
    const k = e.target.closest("[data-ws-ask]"); if (k) return Workspace.ask(k.dataset.wsAsk);
    const wr = e.target.closest("[data-wl-runbook]"); if (wr) return Wallet.openSubnet(wr.dataset.wlRunbook);
    const o = e.target.closest("[data-open]"); if (o) return openDrawer(o.dataset.open);
    const row = e.target.closest("tr[data-id], .scard[data-id]"); if (row && !e.target.closest("a")) openDrawer(row.dataset.id);
  });
  $("#scrim").onclick = closeDrawer;
  $("#cols-btn").onclick = e => columnsPopover(e.currentTarget);
  $("#csv-btn").onclick = exportCsv;
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeDrawer();
    if (e.key === "/" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); setView("explore"); $("#q").focus(); }
  });
  $("#grid tbody").innerHTML = Loading.rows(12, 8);
  $("#stats").innerHTML = Loading.tiles(4);
  $("#caution-body").innerHTML = `<div class="card-grid">${Loading.cards(3)}</div>`;
  $("#new-body").innerHTML = $("#scam-body").innerHTML = Loading.cards(6);
  $("#rec-list").innerHTML = Loading.cards(3, "rec");
  $("#rec-summary").textContent = "Loading subnet data…";
  initRecommend();
  const h = location.hash.slice(1);
  await Workspace.init();
  $("#nav-dash").hidden = $("#nav-command").hidden = $("#nav-approvals").hidden = $("#nav-intel").hidden = $("#nav-home").hidden = $("#nav-settings").hidden = !Auth.me();
  $("#nav-infra").hidden = Auth.me()?.role !== "admin";
  $("#nav-sidelayout").hidden = Auth.me()?.role !== "admin"; SideLayout.init();  // System → Sidebar layout: the saved Simple / User sidebar lists (side-layout.js)
  $("#nav-developer").hidden = Auth.me()?.role !== "admin";  // Developer: the sidebar's last item, administrators only (dvp-*.js)
  Notify.init();
  Slack.init();
  Source.init();
  Drive.init();
  Wallet.init();
  Study.init();
  Profile.init();
  Whiteboard.init();
  System.init();  // admins: the server meter, status bar and System page
  Assist.init();  // the Assist button and panel, for everyone who can use agents
  GMChat.init();  // the General Manager chat (top right): assignments become missions (gm-chat.js, D-039)
  Tech.init();  // the sidebar's "New" when there's an edition you haven't opened
  HQ.init();  // admins: the sidebar's count of fixes waiting for them and critical issues
  Mining.init();  // the sidebar's count of My subnets actions waiting for approval and critical alerts
  Workforce.init();  // the sidebar's count of plans, proposals and improvements waiting in Workforce
  Guide.init();  // the Guide button: page tours and suggested values in fields
  Writer.init();  // writing help: corrections and better wordings in text fields
  Command.init();  // the sidebar counts of urgent items and requests waiting in the Approval Center
  Platform.init();  // the grouped sidebar, command palette (Ctrl/⌘ K) and g-key shortcuts
  Shell.init();  // the shell: links into My subnets, search in the middle, health line and status bar
  MissionOS.init();  // Simple / Advanced mode (the top bar's switch and the sidebar it trims)
  Control.init();  // the sidebar's Organization tree: departments, teams and agents
  Sidebar.init();  // the sidebar's frame: brand, pin, search, + New, section icons, the Bittensor tree, version and health (sidebar.js)
  Journey.init();  // Progress at the top of the sidebar, under its head: Goal → Work → Evidence → Approval → Result
  if (/^whiteboard\/\d+$/.test(h) && Auth.me()) { store.set("wb.open", +h.split("/")[1]); setView("whiteboard"); }  // a board's link
  else if (h === "help" || h.startsWith("help/")) { Help.route(h); setView("help"); }  // a doc's link
  else if (/^control(\/|$)/.test(h) && Auth.me()) { Control.route(decodeURIComponent(h)); setView("control"); }  // a node's link: #control/u:12, #control/agent:teams:3
  else if (/^topology(\/|$)/.test(h) && Auth.me()) { Topology.route(h); setView("topology"); }  // a node's link: #topology/agent:teams:3
  else if (["recommend", "caution", "new", "scam", "tech"].includes(h) ||(["command", "approvals", "intel", "org", "projects", "missions", "evaluation", "teamtests", "learning", "layers", "swarm", "home", "settings", "workspace", "dashboard", "notifications", "slack", "source", "drive", "wallet", "study", "profile", "whiteboard", "mining", "teams", "portfolio", "company", "workforce", "infiagent", "studio", "knowledge", "myknowledge", "market", "mos", "evolution", "analytics", "governance"].includes(h) && Auth.me()) || (["infra", "admin", "docker", "devops", "system", "connectors", "cluster", "apps", "functions", "machines", "dns", "hq", "sidelayout", "developer"].includes(h) && Auth.me()?.role === "admin") || h === "agents") setView(h);
  else if (!h && Auth.me()) setView(MissionOS.landing());  // signed-in users land on Mission Control (Simple mode) or the Command Center (Advanced)
  else if (/^agents\/(\d+)$/.test(h) && Auth.me()) { Agents.openAgent(h.split("/")[1]); setView("agents"); }  // shared agent links
  await load();
  connect();
  setInterval(() => {
    setLive();
    $$("[data-until]").forEach(el => el.textContent = until(+el.dataset.until));
  }, 1000);

  setInterval(() => { if (S.data?.block) load(); }, 120000); // safety net if the event stream drops
}
// broken third-party logos fall back to initials (no inline handlers: CSP blocks them)
document.addEventListener("error", e => {
  const img = e.target;
  if (img.tagName === "IMG" && img.dataset.fallback != null) {
    const span = document.createElement("span"); span.className = img.className; span.textContent = img.dataset.fallback; img.replaceWith(span);
  }
}, true);
Auth.start(init);
