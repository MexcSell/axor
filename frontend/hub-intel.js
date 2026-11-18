/* AXoR 2.0 Bittensor Research (Knowledge → Bittensor Research; hubs.js page "intel"): the subnet market read from the live chain data the Explorer already
   holds (S.data), the Dashboard's opportunities and movers (/api/dashboard) and, for agent users, their miners (/api/command).
   Emission leaders and concentration, competition, rewards, risk and opportunity. A subnet opens in its drawer. */
(() => {
  const RISKS = [["scam", "Scam signal", "s-crit", "shield"], ["avoid", "Avoid", "s-crit", "ban"], ["caution", "Caution", "s-warn", "alert"], ["clear", "Clear", "s-ok", "check"]];
  const name = r => `SN${r.netuid}${r.name ? " · " + r.name : ""}`;
  const pc = x => x == null ? "–" : `${fmtNum(x * 100, 0)}%`;

  Hubs.register("intel", {
    title: "Bittensor Research", kicker: "Knowledge", icon: "chart",
    lead: "The subnet market from the live chain: where emission goes, how crowded each competition is, how rewards are shared, and what to avoid or try. Click a subnet for its details.",
    every: 60000, chain: true,
    load: async (fresh, get) => {
      const [dash, cmd] = await Promise.all([get("/api/dashboard", fresh).catch(() => null), $("#nav-org") && !$("#nav-org").hidden ? get("/api/command").catch(() => null) : null]);
      return { at: S.data?.updated, block: S.data?.block, dash, miners: cmd?.overview?.miners || [] };
    },
    actions: () => `<button type="button" class="btn sm" data-axh-to="explore">${icon("grid")}Subnet Explorer</button>`,
    body(d, h) {
      const all = (S.data?.subnets || []).filter(r => r.netuid !== 0);
      if (!all.length) return `<div class="card empty">${Loading.line("Collecting the first snapshot from the chain…")}</div>`;
      const em = all.reduce((a, r) => a + (r.emission_day || 0), 0), p = S.data?.tao_usd;
      const byEm = [...all].sort((a, b) => (b.emission_day || 0) - (a.emission_day || 0));
      const top10 = byEm.slice(0, 10).reduce((a, r) => a + (r.emission_day || 0), 0) / (em || 1);
      const open = all.filter(r => r.uid_available).length, regs = all.map(r => r.reg_cost).filter(x => x != null).sort((a, b) => a - b);
      const risk = Object.fromEntries(RISKS.map(([k]) => [k, all.filter(r => (r.risk_level || "clear") === k).length]));
      const flagged = byEm.filter(r => r.risk_level && r.risk_level !== "clear").slice(0, 6);
      const comp = byEm.slice(0, 15);
      const conc = all.filter(r => r.top_share != null && (r.earning_miners || 0) >= 3);
      const takers = [...conc].sort((a, b) => b.top_share - a.top_share).slice(0, 6), broad = [...conc].sort((a, b) => a.top_share - b.top_share).slice(0, 6);
      const opp = d.dash?.opportunities || [], mv = d.dash?.movers || {};
      return `<div class="stats occ-kpis">${h.kpi("layers", "Subnets", all.length, `${all.filter(r => (r.age_days ?? 999) <= 7).length} new this week`, "", "new")}
          ${h.kpi("zap", "Emission / day", `${fmtNum(em, 0)} τ`, p ? usd(em * p) : "")}${h.kpi("piechart", "Top-10 share", pc(top10), "of all emission")}
          ${h.kpi("pickaxe", "UIDs open", open, `of ${all.length} subnets`)}${h.kpi("coin", "Median registration", regs.length ? `${fmtNum(regs[Math.floor(regs.length / 2)], 3)} τ` : "–", p && regs.length ? usd(regs[Math.floor(regs.length / 2)] * p) : "")}
          ${h.kpi("alert", "Flagged", risk.scam + risk.avoid + risk.caution, `${risk.scam} scam · ${risk.avoid} avoid · ${risk.caution} caution`, risk.scam ? "crit" : "warn", "caution")}</div>
        <div class="occ-grid">
          ${h.card("", "zap", "Emission leaders", `<span class="faint small">τ a day</span>`, h.bars(byEm.slice(0, 12).map(r => ({ label: name(r), value: r.emission_day || 0, open: r.netuid,
              title: `${name(r)}: ${fmtNum(r.emission_day, 1)} τ/day, ${pc((r.emission_day || 0) / em)} of all emission` })), x => fmtNum(x, 0)))}
          ${h.card("", "shield", "Risk & opportunity", `<button type="button" class="linkbtn" data-axh-to="caution">Avoid &amp; Caution</button>`, `
            <ul class="occ-by axh-risk">${RISKS.map(([k, l, tone, ic]) => `<li><span>${h.pill(tone, l, ic)}</span>${h.meter(risk[k] / all.length, `${risk[k]} of ${all.length}`)}<b class="num">${risk[k]}</b></li>`).join("")}</ul>
            ${flagged.length ? `<h4 class="occ-h4">Flagged among the biggest</h4><ul class="occ-list">${flagged.map(r => `<li><button type="button" class="occ-row" data-open="${r.netuid}"><span class="occ-need-t"><b>${esc(name(r))}</b><small>${esc((r.flags || []).map(f => f.text || "").filter(Boolean).slice(0, 2).join(" · ") || r.risk_level)}</small></span>${h.pill(RISKS.find(x => x[0] === r.risk_level)?.[2] || "s-warn", RISKS.find(x => x[0] === r.risk_level)?.[1] || r.risk_level)}</button></li>`).join("")}</ul>` : ""}`)}
          ${h.card("axh-span12", "users", "Competition intelligence", `<span class="faint small">the 15 biggest subnets by emission</span>`, `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Subnet</th><th>Field</th><th class="r">Miners</th><th class="r">Earning</th><th>Top miner's share</th><th class="r">Top miner / day</th><th class="r">Registration</th><th>UID</th></tr></thead><tbody>
            ${comp.map(r => `<tr><td><button type="button" class="linkbtn" data-open="${r.netuid}">${esc(name(r))}</button></td><td class="faint">${esc(r.field || "")}</td>
              <td class="r num">${r.num_uids ?? "–"}${r.max_uids ? `<span class="faint">/${r.max_uids}</span>` : ""}</td><td class="r num">${r.earning_miners ?? "–"}</td>
              <td>${r.top_share != null ? `${h.meter(r.top_share, pc(r.top_share))} <span class="num">${pc(r.top_share)}</span>` : "–"}</td><td class="r num">${r.top_miner != null ? money(r.top_miner) : "–"}</td>
              <td class="r num">${r.reg_cost != null ? `${fmtNum(r.reg_cost, r.reg_cost < 1 ? 3 : 2)} τ` : "–"}</td><td>${r.uid_available ? h.pill("s-ok", "open") : h.pill("s-off", "full")}</td></tr>`).join("")}</tbody></table></div>`)}
          ${h.card("", "trophy", "Rewards: winner takes most", `<span class="faint small">top miner's share of miner rewards</span>`, h.bars(takers.map(r => ({ label: name(r), value: r.top_share, open: r.netuid, title: `${name(r)}: the top miner takes ${pc(r.top_share)}; ${r.earning_miners} miners earn` })), pc))}
          ${h.card("", "users", "Rewards: shared broadly", `<span class="faint small">the most even payouts</span>`, h.bars(broad.map(r => ({ label: name(r), value: r.top_share, open: r.netuid, title: `${name(r)}: the top miner takes ${pc(r.top_share)}; ${r.earning_miners} miners earn` })), pc))}
          ${h.card("", "target", "Best opportunities now", `<button type="button" class="linkbtn" data-axh-to="recommend">Recommendations</button>`, opp.length ? `<ul class="occ-list">${opp.slice(0, 6).map(o => { const r = all.find(x => x.netuid === o.netuid) || { netuid: o.netuid };
              return `<li><button type="button" class="occ-row" data-open="${o.netuid}"><span class="occ-need-t"><b>${esc(name(r))}</b><small>${fmtNum(o.ratio, 1)}× earnings over cost · ${pc(o.chance)} top-miner chance</small></span><b class="num ${o.net > 0 ? "pos" : "neg"}">${usd(o.net)}/mo</b></button></li>`; }).join("")}</ul>`
            : h.empty("No subnet qualifies right now (UID open, no flags, earnings above cost)."))}
          ${h.card("", "cycle", "Emission movers (24 h)", `<button type="button" class="linkbtn" data-axh-to="dashboard">Market Research</button>`, (mv.emission_up || []).length || (mv.emission_down || []).length
            ? `<ul class="occ-list">${[...(mv.emission_up || []).filter(x => x.value > 0).slice(0, 4), ...(mv.emission_down || []).filter(x => x.value < 0).slice(0, 4)].map(x => { const r = all.find(y => y.netuid === x.netuid) || { netuid: x.netuid };
                return `<li><button type="button" class="occ-row" data-open="${x.netuid}">${icon(x.value > 0 ? "up" : "down")}<span class="occ-need-t"><b>${esc(name(r))}</b></span><b class="num ${x.value > 0 ? "pos" : "neg"}">${x.value > 0 ? "+" : ""}${pct(x.value, 1)}</b></button></li>`; }).join("")}</ul>`
            : h.empty("Movers appear after a day of data."))}
          ${d.miners.length ? h.card("axh-span12", "pickaxe", "Your miners", `<button type="button" class="linkbtn" data-axh-to="mining">My subnets</button>`, `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Subnet</th><th class="r">Rank</th><th class="r">τ / day</th><th class="r">Gap to goal</th><th>Latest brief</th></tr></thead><tbody>
            ${d.miners.map(m => `<tr><td><button type="button" class="linkbtn" data-open="${m.netuid}">SN${m.netuid}${m.name ? ` · ${esc(m.name)}` : ""}</button></td><td class="r num">${m.rank ?? "–"}${m.of ? `<span class="faint">/${m.of}</span>` : ""}</td>
              <td class="r num">${m.em != null ? fmtNum(m.em, 3) : "–"}</td><td class="r num">${m.gap != null ? fmtNum(m.gap, 3) : "–"}</td><td class="faint">${esc(m.headline || "")}</td></tr>`).join("")}</tbody></table></div>`) : ""}
        </div>`;
    },
  });
})();
