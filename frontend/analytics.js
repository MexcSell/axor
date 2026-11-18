/* Analytics (AXoR 5.0; analytics.py /api/analytics; a hubs.js page, styles in evolution.css): performance, cost and intelligence
   across every agent system. The headline is cost per successfully validated deliverable: every ledger token in the period over
   the deliverables something other than their author checked (a scored run at 70+, a mission verified by its reviewer). The
   scorecard is AXoR 5.0's eight Generation-5 measurements, each with its evidence or "no data". Read-only. */
(() => {
  let days = 30;
  try { days = +localStorage.getItem("g5.days") || 30; } catch {}
  const STATE = { ok: ["s-ok", "On track", "check"], weak: ["s-warn", "Needs work", "alert"], none: ["s-off", "No data", "minus"] };

  // one measure per chart (never two scales on one axis): columns from the baseline, a tooltip per column
  // the Owner's first targets (K-14): met, not met or no data, each with what it was read from (G5-5 L5.1)
  function targets(d, h) {
    if (!d.targets) return "";
    const T = { met: ["s-ok", "Met", "check"], not_met: ["s-warn", "Not met", "alert"], none: ["s-off", "No data", ""] };
    return h.card("axh-span12", "target", "Your first targets", `<span class="faint small">the whole server · a target with nothing behind it is never met</span>`,
      `<div class="tablewrap flat"><table class="grid axh-table g5-score g5-targets"><thead><tr><th>Target</th><th class="r">Value</th><th>Read from</th><th>State</th></tr></thead><tbody>
        ${d.targets.map(t => { const s = T[t.state] || T.none; return `<tr><td><b>${esc(t.k)}</b> ${esc(t.want)}</td><td class="r num">${esc(String(t.value ?? "–"))}</td>
          <td class="faint">${esc(t.detail)}${t.ids.length ? ` <span class="num">(ids ${esc(t.ids.slice(0, 8).join(", "))}${t.ids.length > 8 ? "…" : ""})</span>` : ""}</td><td>${h.pill(s[0], s[1], s[2])}</td></tr>`; }).join("")}</tbody></table></div>`);
  }

  function columns(series, key, label, fmt, h) {
    const max = Math.max(...series.map(s => s[key]), 0);
    if (!max) return h.empty(`No ${label.toLowerCase()} in this period.`);
    const step = Math.max(1, Math.ceil(series.length / 6));
    return `<div class="g5-cols" role="img" aria-label="${esc(label)} per day">${series.map((s, i) => `<span class="g5-col" tabindex="0" data-tip="${esc(`${s.day}: ${fmt(s[key])} ${label.toLowerCase()}`)}">
        <i style="height:${s[key] ? Math.max(2, s[key] / max * 100).toFixed(1) : 0}%"></i>${i % step === 0 ? `<small>${esc(s.day.slice(5))}</small>` : ""}</span>`).join("")}</div>
      <p class="faint small g5-axis">Peak ${fmt(max)} · ${series.length} days</p>`;
  }

  Hubs.register("analytics", {
    title: "Analytics", kicker: "Analytics", icon: "chart",
    lead: "Performance, cost and intelligence across every agent system. The number that matters: what one successfully validated deliverable costs. It should fall as AXoR learns, not rise with more tokens or more agents.",
    load: (fresh, get) => get(`/api/analytics?days=${days}`, fresh),
    actions: () => `<div class="occ-filters" role="group" aria-label="Period">${[7, 30, 90].map(n => `<button type="button" class="chip" data-hub="days" data-n="${n}" aria-pressed="${days === n}">${n} days</button>`).join("")}</div>`,
    body(d, h) {
      const c = d.current, p = d.previous;
      const trend = d.trend == null ? "no earlier period to compare" : `${d.trend > 0 ? "+" : ""}${d.trend}% vs the previous ${d.days} days`;
      const ok = s => (c.ledger.runs ? Math.round(100 * c.ledger.done / c.ledger.runs) : null);
      return `<div class="stats occ-kpis">
          ${h.kpi("target", "Cost per validated deliverable", c.per_validated ? `${h.tok(c.per_validated)} tok` : "–", c.per_validated ? trend : "nothing validated in this period", d.trend > 0 ? "warn" : d.trend < 0 ? "ok" : "")}
          ${h.kpi("check", "Validated deliverables", c.validated, `${c.ledger.validated} scored ${d.valid}+ · ${c.missions.verified} verified missions`)}
          ${h.kpi("zap", "Tokens", h.tok(c.tokens), `previous period ${h.tok(p.tokens)}`)}
          ${h.kpi("cycle", "Runs finished", c.ledger.runs, ok() == null ? "–" : `${ok()}% done · ${c.ledger.failed} failed`, c.ledger.failed > c.ledger.done ? "warn" : "")}
          ${c.usd ? h.kpi("coins", "Reported spend", `$${fmtNum(c.usd, 2)}`, c.usd_per_validated ? `$${fmtNum(c.usd_per_validated, 3)} per validated deliverable` : "where systems report dollars") : ""}</div>
        ${d.reviewed_since ? `<p class="faint small g5-rule">Since ${new Date(d.reviewed_since * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })} a Competition team's board task that was approved in review no longer counts as a validated deliverable: a review is a verdict, not a score of the work. Earlier runs keep the score they were given, so a period that spans that date mixes both rules, and the cost per validated deliverable is higher after it.</p>` : ""}
        <div class="occ-grid">
          ${h.card("axh-span12", "trophy", "Generation 5 scorecard", `<span class="faint small">measured, never assumed</span>`,
            `<div class="tablewrap flat"><table class="grid axh-table g5-score"><thead><tr><th>Measurement</th><th>Desired capability</th><th class="r">Value</th><th>Evidence</th><th>State</th></tr></thead><tbody>
            ${d.scorecard.map(r => { const s = STATE[r.state]; return `<tr><td><b>${esc(r.name)}</b></td><td class="faint">${esc(r.want)}</td><td class="r num">${esc(r.value ?? "–")}</td>
              <td class="faint">${esc(r.detail)}</td><td>${h.pill(s[0], s[1], s[2])}</td></tr>`; }).join("")}</tbody></table></div>`)}
          ${targets(d, h)}
          ${h.card("", "zap", "Tokens per day", "", columns(d.series, "tokens", "Tokens", h.tok, h))}
          ${h.card("", "check", "Validated deliverables per day", "", columns(d.series, "validated", "Validated", n => String(n), h))}
          ${h.card("axh-span12", "layers", "By system", `<span class="faint small">the run ledger, ${d.days} days</span>`, !d.systems.length ? h.empty("No run recorded in this period.")
            : `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>System</th><th class="r">Runs</th><th class="r">Done</th><th class="r">Avg score</th><th class="r">Validated</th><th class="r">Tokens</th><th class="r">Tokens / validated</th><th class="r">Avg time</th></tr></thead><tbody>
            ${d.systems.map(s => `<tr><td>${esc(s.label)}</td><td class="r num">${s.runs}</td><td class="r num">${s.success ?? "–"}%</td><td class="r num">${s.avg_score ?? "–"}</td><td class="r num">${s.validated}</td>
              <td class="r num">${h.tok(s.tokens)}</td><td class="r num">${s.per_validated ? h.tok(s.per_validated) : "–"}</td><td class="r num">${s.secs ? `${s.secs}s` : "–"}</td></tr>`).join("")}</tbody></table></div>`)}
          ${h.card("axh-span12", "bot", "Agents", `<span class="faint small">the 40 that used the most tokens</span>`, !d.agents.length ? h.empty("No agent run recorded in this period.")
            : `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Agent</th><th>System</th><th class="r">Runs</th><th class="r">Done</th><th class="r">Avg score</th><th class="r">Validated</th><th class="r">Tokens</th><th class="r">Tokens / validated</th></tr></thead><tbody>
            ${d.agents.map(a => `<tr><td>${esc(a.name)}</td><td class="faint">${esc({ hub: "Your agents", builtin: "Built-in", workforce: "Workforce", company: "Company", teams: "Competition teams", workflow: "Workflow", hq: "Agent HQ", missions: "Mission Control", longtask: "Long tasks", team: "Project team" }[a.system] || a.system)}</td><td class="r num">${a.runs}</td><td class="r num">${a.success ?? "–"}%</td><td class="r num">${a.avg_score ?? "–"}</td>
              <td class="r num">${a.validated}</td><td class="r num">${h.tok(a.tokens)}</td><td class="r num">${a.per_validated ? h.tok(a.per_validated) : "–"}</td></tr>`).join("")}</tbody></table></div>`)}
        </div>
        <p class="faint small">${icon("info")}A deliverable counts as validated only when something other than its author checked it: a run an evaluator or verifier scored ${d.valid} or more, or a mission whose independent reviewer found every criterion met. Tokens count every run in the period, so wasted work raises the cost.</p>
        ${d.errors.length ? `<p class="faint small occ-errs">${icon("info")}${esc(d.errors.join(" · "))}</p>` : ""}`;
    },
    act(a, el) {
      if (a !== "days") return;
      days = +el.dataset.n; try { localStorage.setItem("g5.days", days); } catch {}
      document.querySelector("#axh-analytics [data-hub=refresh]")?.click();
    },
  });
})();
