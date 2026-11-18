"""The model router every agent system shares: which model of the owner's pool runs a call, from what the owner's runs showed.

S(m,t) = wq·Q - wc·C - wl·L - wr·R, plus a small bonus for little-tried models (so a new model gets tried):
- Q: the average score runs of model m on task t earned (an evaluator's or a verifier's, 0-100), shrunk towards a prior from
  the model's tier, so one lucky run doesn't decide; with no scored runs it's the tier prior alone.
- C: the expected cost of a call (the task's typical tokens × the model's price), against COST_REF.
- L: the model's average run time, against LATENCY_REF. R: its failure rate, smoothed.
Hard constraints come before the score: a minimum tier for the steps that judge or plan (MIN_TIER), a different model from the
author's for an independent review (avoid), and only models whose provider is connected now.

The pool (models, their tier and price) and the weights belong to the owner and are kept by the agent core (agent_core.py),
edited on the Workforce's Settings page; Workforce routes on its own run table, every other system on the core's ledger.
Nothing here calls a model or reads a table: rank() is given the pool and the statistics.
"""
import math, re, statistics

TIER_PRIOR = {1: 55, 2: 68, 3: 80}   # the score a model of this tier is expected to earn before it has any
PRICE = {1: 0.8, 2: 4.0, 3: 15.0}    # $ per million tokens, blended, when the pool doesn't say
WEIGHTS = {"quality": (1.0, 0.15, 0.05, 0.5), "balanced": (1.0, 0.4, 0.15, 0.5), "thrifty": (1.0, 0.9, 0.2, 0.5)}  # wq, wc, wl, wr
TOKENS_GUESS = 6000                  # tokens a call is expected to take before there are runs to tell
COST_REF, LATENCY_REF = 0.25, 60.0   # a call costing this many dollars, or taking this many seconds, counts as fully expensive or slow
# kinds of work that plan, judge or write the final word: at least a strong (tier 2) model when the pool has one
MIN_TIER = {"plan": 2, "synthesize": 2, "evaluate": 2, "critique": 2, "debate": 2, "improve": 2, "review": 2, "verify": 2,
            "understand": 2, "brief": 2, "think": 2, "judge": 2}
# OpenAI's suffixed GPT models (gpt-6.2-astra, gpt-6.1-terra, gpt-5.6-luna …) rank by suffix, not version, as OpenAI describes
# them in Codex's model list (models_cache.json, read 2026-11-18): astra "most capable … complex coding and professional work",
# sol "go-to model for coding and everyday work", terra "efficient" / "balanced", luna "fast and affordable … easier tasks".
# Before, every gpt-5.x was tier 3 (luna included) and every gpt-6.x tier 2 (astra included).
GPT_SUFFIX_TIER = {"astra": 3, "sol": 2, "terra": 2, "luna": 1}


def guess(model):
    """(tier, $ per Mtok) for a provider:model id: 3 frontier, 2 strong, 1 light. Local and plan (CLI) calls cost nothing extra."""
    p, _, m = (model or "").partition(":")
    m = m.lower()
    fam = re.search(r"gpt-[\d.]+-(astra|sol|terra|luna)\b", m)
    if fam: tier = GPT_SUFFIX_TIER[fam.group(1)]
    elif re.search(r"opus|fable|gpt-5(?![\w.-]*(mini|nano))|\bo3\b|o3-pro|gemini-[\d.]+-pro|grok-4|ultra", m): tier = 3
    elif re.search(r"haiku|(?<!ge)mini|nano|lite|small|tiny|[:/_-]\d{1,2}b\b|\b\d{1,2}b\b", m): tier = 1  # not "gemini"
    else: tier = 2
    return tier, 0.0 if p in ("local", "terminal", "codex", "copilot-cli") else PRICE[tier]


def effective(raw):
    """The pool as routed: each entry's tier and price as the owner set them, else guessed from the model's name."""
    out = []
    for p in raw or []:
        if not isinstance(p, dict) or not p.get("model"): continue
        tier, price = guess(p["model"])
        out.append({"model": p["model"], "tier": p.get("tier") or tier, "price": p["price"] if p.get("price") is not None else price})
    return out


def rank(pool, stats, task, weights="balanced", avoid=(), min_tier=None, pressure=False, notes=None):
    """(model, decision) for one call of `task`: the pool's best by S within the constraints. pool: effective() entries, not
    empty. stats: {(model, task): row, (model, None): row} with n, tokens, latency, failed, scored, score_sum (the general row
    needs n, failed and latency). pressure: the run is short of budget, so cost counts double."""
    wq, wc, wl, wr = WEIGHTS.get(weights, WEIGHTS["balanced"])
    notes = list(notes or [])
    if pressure: wc *= 2; notes.append("over 60% of the budget: cost counts double")
    need = MIN_TIER.get(task, 1) if min_tier is None else min_tier
    cands = [p for p in pool if p["tier"] >= need]
    if not cands: cands = [max(pool, key=lambda p: p["tier"])]; notes.append(f"no tier-{need} model: the strongest")
    elif len(cands) < len(pool): notes.append(f"tier {need}+ for {task}")
    if avoid:
        rest = [p for p in cands if p["model"] not in avoid]
        if rest and len(rest) < len(cands): cands = rest; notes.append("not the authors' model (independent review)")
    per_task = [st["tokens"] for (mdl, t), st in stats.items() if t == task and st.get("tokens")]
    typical = statistics.mean(per_task) if per_task else TOKENS_GUESS
    total = sum((stats.get((p["model"], task)) or {}).get("n", 0) for p in cands)
    rows = []
    for p in cands:
        st, gen = stats.get((p["model"], task)) or {}, stats.get((p["model"], None)) or {}
        scored = st.get("scored") or 0
        q = (TIER_PRIOR.get(p["tier"], TIER_PRIOR[2]) * 3 + (st.get("score_sum") or 0)) / (3 + scored)
        cost = (st.get("tokens") or typical) * p["price"] / 1e6
        rows.append({"model": p["model"], "tier": p["tier"], "quality": q, "scored": scored, "cost": cost,
                     "latency": gen.get("latency") or 0.0, "risk": ((gen.get("failed") or 0) + 0.5) / ((gen.get("n") or 0) + 10),
                     "runs": st.get("n") or 0})
    for r in rows:  # Q, C, L and R on 0-1 scales: C and L against fixed references, so cents apart don't count as a big gap
        bonus = 0.04 * math.sqrt(math.log(total + 2) / (r["runs"] + 1))
        r["score"] = (wq * r["quality"] / 100 - wc * min(1, r["cost"] / COST_REF) - wl * min(1, r["latency"] / LATENCY_REF)
                      - wr * r["risk"] + bonus)
    rows.sort(key=lambda r: -r["score"])
    b = rows[0]
    basis = " (tier prior)" if not b["scored"] else f" over {b['scored']} scored run(s)"
    reason = (f"Best of {len(rows)}: quality {b['quality']:.0f}{basis}, ${b['cost']:.4f} a call, {b['latency']:.1f} s, {b['risk']:.0%} failures"
              + (f". {'; '.join(notes).capitalize()}." if notes else "."))
    return b["model"], {"task": task, "model": b["model"], "reason": reason, "weights": [wq, wc, wl, wr],
                        "candidates": [{k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()} for r in rows]}


def stats_rows(rows):
    """The statistics rank() takes, from rows of (model, task, n, tokens, latency, failed, scored, score_sum)."""
    out = {}
    for r in rows:
        out[(r["model"], r["task"])] = r
        g = out.setdefault((r["model"], None), {"n": 0, "failed": 0, "lat_sum": 0.0})
        g["n"] += r["n"]; g["failed"] += r["failed"] or 0; g["lat_sum"] += (r["latency"] or 0) * r["n"]
    for (mdl, task), g in out.items():
        if task is None: g["latency"] = g["lat_sum"] / g["n"] if g["n"] else 0
    return out
