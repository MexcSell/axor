/* Governance (AXoR 5.0; governance.py /api/governance; a hubs.js page, styles in evolution.css): permissions, budgets, autonomy,
   approvals, audit and rollback in one place, over the controls that already exist. Decisions stay where they're made (the
   Approval Center, the Organization, the Evolution Lab); the two settings changed here are the Evolution Engine's policy
   (PUT /api/evolution/policy) and your daily token limit over every agent system (PUT /api/studio/budget). */
(() => {
  const SRC = { evolution: ["cycle", "Evolution Lab"], organization: ["branch", "Organization"], missions: ["target", "Mission Control"] };

  function dialog(title, body, ok, run) {
    let el = document.getElementById("g5-dlg");
    if (!el) { el = document.createElement("dialog"); el.id = "g5-dlg"; document.body.append(el); }
    el.className = "modal evo-dlg";
    el.innerHTML = `<form method="dialog" class="co-form" novalidate><div class="evo-dh"><h3>${title}</h3><button type="button" class="iconbtn" data-x aria-label="Close">${icon("close")}</button></div>
      ${body}<p class="err" role="alert"></p><div class="row end"><button type="button" class="btn" data-x>Cancel</button><button type="submit" class="btn primary">${ok}</button></div></form>`;
    const f = el.querySelector("form"), e = f.querySelector(".err");
    f.querySelectorAll("[data-x]").forEach(b => b.onclick = () => el.close());
    f.onsubmit = async ev => {
      ev.preventDefault();
      const btn = f.querySelector("[type=submit]"); btn.disabled = true; e.textContent = "";
      try { await run(new FormData(f)); el.close(); document.querySelector("#axh-governance [data-hub=refresh]")?.click(); }
      catch (x) { e.textContent = x?.message || "Something went wrong."; }
      finally { btn.disabled = false; }
    };
    el.showModal();
  }

  Hubs.register("governance", {
    title: "Governance", kicker: "Governance", icon: "shield",
    lead: "What AXoR may do by itself, what it may spend, and what always waits for you, with every decision on record and every promoted change one click from rollback.",
    load: (fresh, get) => get("/api/governance", fresh),
    actions: () => `<button type="button" class="btn sm" data-axh-to="approvals">${icon("inbox")}Approval Center</button>${document.getElementById("nav-admin")?.hidden === false ? `<button type="button" class="btn sm" data-axh-to="admin">${icon("users")}Users &amp; permissions</button>` : ""}`,
    body(d, h) {
      const p = d.policy, b = d.budget;
      const cap = b?.daily_tokens;
      return `<div class="stats occ-kpis">
          ${h.kpi("shield", "Evolution policy", p ? ({ recommend: "Recommend", experiment: "Experiment", auto: "Auto-promote" }[p.mode] || p.mode) : "–", p ? `promote at +${fmtNum(p.margin, 0)} pts on ${p.min_cases}+ cases` : "the Evolution Engine isn't running")}
          ${h.kpi("coins", "Daily token limit", cap ? h.tok(cap) : "None", b ? `${h.tok(b.today)} used today` : "–", cap && b.today >= cap ? "crit" : cap && b.today > cap * 0.8 ? "warn" : "")}
          ${h.kpi("inbox", "Waiting for you", d.pending.length, "verified changes and requests", d.pending.length ? "warn" : "")}
          ${h.kpi("undo", "Rollback points", d.rollback.length, "promoted changes")}
          ${h.kpi("list", "Audit entries", d.audit.length, "latest, merged")}</div>
        <div class="occ-grid">
          ${h.card("", "sliders", "Evolution Engine policy", `<button type="button" class="btn sm" data-hub="policy">${icon("edit")}Change</button>`, !p ? h.empty("The Evolution Engine isn't running on this server.")
            : `<ul class="g5-modes">${Object.entries(d.modes).map(([k, l]) => `<li class="${p.mode === k ? "on" : ""}">${p.mode === k ? icon("check") : "<i></i>"}<span><b>${esc(l)}</b><small>${esc({ recommend: "Signals and proposals; experiments run when you start them.", experiment: "Also runs experiments by itself on proposals with a benchmark, within its daily token limit. Never promotes.", auto: "Also promotes verified configuration changes of your own agents, each one rolled back in one click. Never code or external actions, never an agent at L0." }[k])}</small></span></li>`).join("")}</ul>
              <p class="small faint">Margin +${fmtNum(p.margin, 0)} points · at least ${p.min_cases} cases · engine limit ${h.tok(p.spent_today)} of ${h.tok(p.daily_tokens)} tokens today${p.by ? ` · changed by ${esc(p.by)} ${ago(p.updated)}` : ""}</p>`)}
          ${h.card("", "coins", "Budgets", `<button type="button" class="btn sm" data-hub="budget">${icon("edit")}Daily limit</button>`, !b ? h.empty("The agent core isn't running.")
            : `${cap ? h.meter(b.today / cap, `${h.tok(b.today)} of ${h.tok(cap)}`) : ""}<p class="small">${cap ? `${h.tok(b.today)} of ${h.tok(cap)} tokens used today across every agent system; model calls stop at the limit.` : `No daily limit: ${h.tok(b.today)} tokens used today across every agent system.`}</p>
              ${h.bars((b.by_system || []).map(s => ({ label: s.label, value: s.tokens })), h.tok, { none: "Nothing spent today." })}`)}
          ${h.card("axh-span12", "branch", "Autonomy levels", `<span class="faint small">AXoR 5.0's levels, mapped onto the organization's execution levels (the ones enforced)</span>`,
            `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>AXoR 5.0</th><th>Permission</th><th>Organization level</th><th class="r">Your agents</th><th>Here</th></tr></thead><tbody>
            ${d.spec_levels.map(s => `<tr><td><b>L${s.level}</b></td><td>${esc(s.spec)}</td><td>${s.org.map(n => { const l = d.levels.find(x => x.level === n); return l ? `L${n} ${esc(l.name)}${l.needs_approval ? ` ${icon("lock")}` : ""}` : ""; }).join(", ")}</td>
              <td class="r num">${s.org.reduce((t, n) => t + (d.levels.find(x => x.level === n)?.agents || 0), 0)}</td><td class="faint">${esc(s.here)}</td></tr>`).join("")}</tbody></table></div>
            <p class="small faint">${icon("lock")}Raising an agent to L3 or more waits for your approval (Organization). Position never raises a level.</p>`)}
          ${h.card("axh-span12", "cycle", "Kinds of autonomy", `<span class="faint small">Not interchangeable: each is switched on where it works, and all three share the daily token limit above, the autonomy levels and the audit trail</span>`,
            `<div class="tablewrap flat"><table class="grid axh-table g5-auto"><thead><tr><th>Name</th><th>What it does</th><th>Where you switch it</th><th>Never</th></tr></thead><tbody>
            ${[["Mission autonomy", "Set per mission, L0 to L4: whether the plan runs, waits for your approval or is only a recommendation; whether a failure is retried or asks first; whether deploys and the like become approval requests or are only listed.", "mos", "Mission Control → a mission's Autonomy", "Carries out a deploy, upload, payment or key operation"],
               ["Autopilot", "Runs a team's work by itself: the Director plans, tasks start, squad leads review. Execution autonomy for one team.", "teams", "Competition teams → a team's header", "Submits, registers, pays or deploys to production"],
               ["Autoloop", "Repeats change → test → refine on one bounded task until its stop conditions (iterations, time, tokens, a measured result).", "teams", "Competition teams → Run → Autoloop", "Runs past its budget or leaves its task's branch"],
               ["Evolution Lab", "Improves agents, skills and tools as new versions: tests a change against the current version, promotes only with evidence.", "evolution", "Workforce → Evolution Lab (policy here)", "Promotes code changes or external actions by itself"]]
              .map(([n, what, to, where, never]) => `<tr><td><b>${n}</b></td><td>${what}</td><td>${document.querySelector(`nav.side [data-view="${to}"]:not([hidden])`) ? `<button type="button" class="linkbtn" data-axh-to="${to}">${where}</button>` : esc(where)}</td><td class="faint">${never}</td></tr>`).join("")}</tbody></table></div>`)}
          ${h.card("", "lock", "Always yours", "", `<ul class="g5-locked">${d.locked.map(l => `<li>${icon("lock")}${esc(l.label)}</li>`).join("")}<li>${icon("lock")}Code changes and external actions proposed by the Evolution Engine</li></ul>`)}
          ${h.card("", "inbox", "Waiting for you", "", !d.pending.length ? h.empty("Nothing is waiting for a decision.")
            : `<ul class="occ-list">${d.pending.map(x => `<li><button type="button" class="occ-row" ${x.source === "evolution" ? `data-hub="evo" data-id="${x.go.proposal}"` : h.go(x.go)}><span class="occ-need-t"><b>${esc(x.title)}</b><small>${esc(x.detail)}</small></span>
                ${h.pill("src", (SRC[x.source] || ["info", x.source])[1], (SRC[x.source] || ["info"])[0])}<small class="faint">${ago(x.ts)}</small></button></li>`).join("")}</ul>`)}
          ${h.card("axh-span12", "check", "Rules in force", "", `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Rule</th><th>How</th><th>Where</th></tr></thead><tbody>
            ${d.rules.map(r => `<tr><td><b>${esc(r.rule)}</b></td><td class="faint">${esc(r.how)}</td><td>${esc(r.where)}</td></tr>`).join("")}</tbody></table></div>`)}
          ${h.card("axh-span12", "undo", "Rollback points", "", !d.rollback.length ? h.empty("No promoted change yet.")
            : `<div class="tablewrap flat"><table class="grid axh-table"><thead><tr><th>Change</th><th>Versions</th><th>Decided by</th><th>When</th><th></th></tr></thead><tbody>
            ${d.rollback.map(r => `<tr><td>${esc(r.title)}</td><td class="num">${r.after ? `v${r.before} → v${r.after}` : "decision only"}</td><td>${esc(r.by || "")}${r.decision === "policy" ? ` ${h.pill("s-info", "policy")}` : ""}</td><td class="faint">${ago(r.ts)}</td>
              <td class="r"><button type="button" class="btn sm" data-hub="evo" data-id="${r.id}">${icon("eye")}Open</button></td></tr>`).join("")}</tbody></table></div>`)}
          ${h.card("axh-span12", "list", "Audit trail", `<span class="faint small">Evolution Engine and Organization</span>`, !d.audit.length ? h.empty("Nothing recorded yet.")
            : `<ul class="evo-audit">${d.audit.map(a => `<li><span class="faint num">${new Date(a.ts * 1000).toLocaleString()}</span><b>${esc(a.actor || "")}</b><code>${esc(a.action)}</code><span>${esc(a.detail || a.target || "")}</span></li>`).join("")}</ul>`)}
        </div>
        ${d.errors.length ? `<p class="faint small occ-errs">${icon("info")}${esc(d.errors.join(" · "))}</p>` : ""}`;
    },
    act(a, el, s) {
      const d = s.d;
      if (a === "evo") return Evolution.show(+el.dataset.id);
      if (a === "policy" && d?.policy) {
        const p = d.policy;
        return dialog("Evolution Engine policy", `<fieldset class="g5-radio"><legend>What the engine may do by itself</legend>${Object.entries(d.modes).map(([k, l]) => `<label><input type="radio" name="mode" value="${k}" ${p.mode === k ? "checked" : ""}> ${esc(l)}</label>`).join("")}</fieldset>
          <div class="row"><label class="in"><span>Margin to beat the current version (points)</span><input type="number" name="margin" min="0" max="50" step="0.5" value="${p.margin}"></label>
            <label class="in"><span>Minimum cases</span><input type="number" name="min_cases" min="1" max="20" value="${p.min_cases}"></label></div>
          <label class="in"><span>Engine's daily token limit</span><input type="number" name="daily_tokens" min="0" step="1000" value="${p.daily_tokens}"></label>
          <p class="small faint">${icon("info")}Code changes and external actions always need you, whatever the mode.</p>`, "Save policy",
          fd => api("/api/evolution/policy", { method: "PUT", body: { mode: fd.get("mode"), margin: +fd.get("margin"), min_cases: +fd.get("min_cases"), daily_tokens: +fd.get("daily_tokens") } }));
      }
      if (a === "budget") {
        return dialog("Daily token limit", `<label class="in"><span>Tokens per day across every agent system (0 = no limit)</span><input type="number" name="t" min="0" step="10000" value="${d?.budget?.daily_tokens || 0}"></label>`, "Save",
          fd => api("/api/studio/budget", { method: "PUT", body: { daily_tokens: +fd.get("t") || null } }));
      }
    },
  });
})();
