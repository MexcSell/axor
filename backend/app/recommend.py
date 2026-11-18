"""Multi-criteria subnet recommender, driven entirely by the user's profile and weights.

Each subnet gets six factor scores in [0, 1] (percentile-ranked against the other candidates so
no single metric's scale dominates), combined with user weights, then multiplied by risk
penalties scaled by the user's risk tolerance. Hard constraints filter before scoring.
"""
import math

TIER_RANK = {"none": 0, "cpu": 1, "api": 1, "capital": 1, "infra": 2, "gpu1": 2, "gpu2": 3, "gpu3": 4, "unknown": 2}
HW_RANK = {"none": 0, "cpu": 1, "gpu1": 2, "gpu2": 3, "gpu3": 4}

DEFAULTS = {
    "hardware": "cpu", "own_hardware": False, "budget_usd": 300, "capital_tao": 1.0,
    "fields": [], "risk": "medium", "count": 8,
    "only_uid_available": True, "exclude_scam": True, "exclude_avoid": True,
    "exclude_winner_take_all": False, "min_age_days": 0,
    "weights": {"profit": 8, "access": 7, "competition": 5, "stability": 5, "momentum": 3, "fit": 5},
}

PLAYBOOK = {
    "LLM & Agents": "Iterate on the evaluation harness locally before every submission, use the strongest model your API budget allows, and track which prompts/agents the validators reward.",
    "Model Training": "Start from the current best public checkpoint, run short ablations on cheap GPUs, and only submit runs that beat the leader's validator score by the required margin.",
    "Inference": "Serve with an optimised engine (vLLM/SGLang), keep latency low with GPUs close to validators, and monitor uptime - missed requests cost more than slow ones.",
    "Inference Optimisation": "Profile the pinned baseline first; most crowns are won with kernel/batching changes that keep outputs bit-identical. Validate correctness gates locally.",
    "Compute": "Offer the GPU classes with the highest hardware-class weight, keep machines online 24/7 and pass every attestation check - idle or failed checks zero your score.",
    "Data & Scraping": "Maximise unique, fresh, policy-compliant data; rotate proxies/credentials and de-duplicate aggressively - duplicates score zero.",
    "Finance & DeFi": "Risk-manage first: drawdown penalties wipe out returns. Backtest walk-forward and size positions conservatively.",
    "Forecasting": "Ensemble several models, calibrate probabilities, and cover every requested item - skipped coordinates score zero.",
    "Vision & Media": "Benchmark against the validator's exact metric, fine-tune on the subnet's data distribution, and use GPU headroom to cut latency.",
    "Science": "Read the scoring function carefully - validity checks dominate. Automate generation + local validation in a loop.",
    "Security & Alignment": "Submit novel findings quickly (rewards decay and duplicates are penalised) and re-validate submissions against the latest challenge format.",
    "Robotics": "Train in the exact simulator version validators use and focus on generalisation to new scenes - the leaderboard rewards robustness.",
    "Infrastructure": "Uptime and geographic/network diversity are the score: run redundant nodes and monitor them.",
    "Optimisation": "Beat the baseline heuristic on every instance; a strong local search (LKH, tabu, simulated annealing) usually outperforms greedy approaches.",
}

def _pctrank(vals):
    """Percentile rank in [0,1] for each value (None -> 0.5)."""
    xs = sorted(v for v in vals if v is not None)
    n = len(xs)
    def rank(v):
        if v is None or n < 2: return 0.5
        lo = sum(1 for x in xs if x < v); eq = sum(1 for x in xs if x == v)
        return (lo + (eq - 1) / 2) / (n - 1)
    return [rank(v) for v in vals]

def _merge(p):
    q = {**DEFAULTS, **{k: v for k, v in (p or {}).items() if v is not None}}
    q["weights"] = {**DEFAULTS["weights"], **(p or {}).get("weights", {})}
    q["count"] = max(5, int(q["count"]))
    return q

def economics(r, tiers, usd, hw=None, own=False):
    """What a capable newcomer can expect on this subnet: rent, realistic daily pay and monthly gross/net in USD.
    hw is the HW_RANK of the miner's hardware (None = unknown, assume renting)."""
    usd = usd or 0
    t = tiers.get(r["tier"], tiers["unknown"])
    lo, hi = t["rent_low"], t["rent_high"]
    rent = 0 if lo is None else (lo + hi) / 2
    fits_hw = hw is not None and TIER_RANK.get(r["tier"], 2) <= hw
    cost_month = rent * (0.25 if (own and fits_hw) else 1)
    # realistic earnings for a capable newcomer: median earner, or half of #2 where one miner dominates
    if r["top_share"] < 0.6 and r["earning_miners"] >= 3:
        realistic = r["median_miner"]
    else:
        realistic = max(r["second_miner"], r["median_miner"]) * 0.5
    miners = max(1, r["num_uids"] - r["validators"])
    p_earn = min(1.0, max(0.1, r["earning_miners"] / miners))  # most registrants on selective subnets earn nothing
    realistic *= p_earn
    gross = realistic * 30 * usd
    net = gross - cost_month - r["reg_cost"] * usd
    return dict(rent=(lo, hi), cost_month=cost_month, fits_hw=fits_hw, realistic=realistic, gross=gross, net=net, p_earn=p_earn)

def recommend(subnets, tiers, usd, profile):
    p = _merge(profile)
    usd = usd or 0
    hw = HW_RANK.get(p["hardware"], 1)
    cands = []
    for r in subnets:
        codes = {f["code"] for f in r["flags"]}
        if p["exclude_scam"] and r["risk_level"] == "scam": continue
        if p["exclude_avoid"] and r["risk_level"] == "avoid": continue
        if p["only_uid_available"] and not r["uid_available"]: continue
        if p["exclude_winner_take_all"] and "winner_take_all" in codes: continue
        if r["age_days"] < p["min_age_days"]: continue
        if r["earning_miners"] == 0: continue
        cands.append(r)
    if not cands:
        return {"profile": p, "results": []}

    rows = [dict(r=r, **economics(r, tiers, usd, hw, p["own_hardware"])) for r in cands]

    profit = _pctrank([x["net"] for x in rows])
    age = _pctrank([min(x["r"]["age_days"], 365) for x in rows])
    em = _pctrank([x["r"]["emission_share"] for x in rows])
    mom_p = _pctrank([x["r"].get("price_change_7d") for x in rows])
    mom_f = _pctrank([x["r"].get("tao_flow_day") for x in rows])
    budget = p["budget_usd"]
    tol = {"low": 0.65, "medium": 0.82, "high": 0.94}[p["risk"]]
    w = p["weights"]
    wsum = sum(w.values()) or 1
    out = []
    for i, x in enumerate(rows):
        r = x["r"]
        lo, hi = x["rent"]
        # access: hardware fit or budget to rent it, capital for registration, open UIDs
        if x["fits_hw"]: hw_s = 1.0
        elif lo is not None and budget >= (lo + hi) / 2: hw_s = 0.85
        elif lo is not None and budget >= lo: hw_s = 0.55
        else: hw_s = 0.1
        if r["tier"] == "unknown": hw_s *= 0.7
        cap_s = 1.0 if p["capital_tao"] >= r["reg_cost"] else 0.2
        access = hw_s * cap_s * (1.0 if r["uid_available"] else 0.5)
        competition = 0.55 * (1 - r["top_share"]) + 0.45 * min(1.0, math.log1p(r["earning_miners"]) / math.log1p(64))
        stability = 0.35 * age[i] + 0.3 * em[i] + 0.2 * (1 - r["owner_burn_share"]) + 0.15 * (1.0 if r["links"]["github"] else 0.0)
        momentum = 0.6 * mom_p[i] + 0.4 * mom_f[i]
        fit = (1.0 if r["field"] in p["fields"] else 0.25) if p["fields"] else 0.6
        f = {"profit": profit[i], "access": access, "competition": competition,
             "stability": stability, "momentum": momentum, "fit": fit}
        base = sum(w[k] * f[k] for k in f) / wsum
        pen = 1.0
        for fl in r["flags"]:
            pen *= {"scam": 0.3, "avoid": 0.6, "caution": tol}[fl["level"]]
        if x["net"] < 0: pen *= 0.7
        if hw_s <= 0.1: pen *= 0.3      # needs hardware you neither have nor can afford to rent
        elif hw_s < 0.6: pen *= 0.75   # affordable only at the cheapest rental end
        if cap_s < 1: pen *= 0.5        # can't pay the registration burn
        score = 100 * base * pen
        out.append({"netuid": r["netuid"], "score": round(score, 1), "factors": {k: round(v, 3) for k, v in f.items()},
                    "penalty": round(pen, 3), **_explain(r, x, f, usd, p)})
    out.sort(key=lambda o: o["score"], reverse=True)
    return {"profile": p, "results": out[: p["count"]], "considered": len(cands)}

def _money(tao, usd):
    return f"{tao:.3f} τ" + (f" (${tao * usd:,.0f})" if usd else "")

def _explain(r, x, f, usd, p):
    why = []
    top = sorted(f.items(), key=lambda kv: kv[1] * p["weights"][kv[0]], reverse=True)
    for k, v in top[:3]:
        if v < 0.4:
            continue  # only cite factors that are actually strengths
        if k == "profit":
            why.append(f"Expected {_money(x['realistic'], usd)}/day for a capable newcomer ({r['earning_miners']} of {r['num_uids']} UIDs earn); est. net ${x['net']:,.0f}/month after costs.")
        elif k == "access":
            why.append("Fits your hardware." if x["fits_hw"] else "Within your rental budget.")
            if r["uid_available"]: why.append(f"UIDs available now; registration {_money(r['reg_cost'], usd)}.")
        elif k == "competition":
            why.append(f"{r['earning_miners']} miners earn and the top miner takes {r['top_share'] * 100:.0f}% - rewards are spread out.")
        elif k == "stability":
            why.append(f"{r['age_days']:.0f} days old with {r['emission_share'] * 100:.2f}% of network emission.")
        elif k == "momentum" and r.get("price_change_7d") is not None:
            why.append(f"Alpha price {r['price_change_7d'] * 100:+.1f}% over 7 days.")
        elif k == "fit" and r["field"] in p["fields"]:
            why.append(f"Matches your interest in {r['field']}.")
    lo, hi = x["rent"]
    rent_txt = "unknown (not published)" if lo is None else f"${lo:,}-{hi:,}/month to rent"
    payback = r["reg_cost"] / x["realistic"] if x["realistic"] else None
    how = [f"Top miner earns {_money(r['top_miner'], usd)}/day, #2 {_money(r['second_miner'], usd)}/day, median {_money(r['median_miner'], usd)}/day."]
    how.append(PLAYBOOK.get(r["field"], "Study the validator code to learn exactly how scores are computed, then optimise for that metric."))
    if r["conditions"]:
        how.append(f"Subnet rules: {r['conditions']}")
    how.append(f"New UIDs are immune for {r['immunity_hours']:.0f}h ({r['immunity_blocks']} blocks); be scoring above the weakest miners before immunity ends or you will be deregistered.")
    return {
        "why": why,
        "budget": {"rent_low": lo, "rent_high": hi, "rent_text": rent_txt, "reg_cost_tao": r["reg_cost"],
                   "reg_cost_usd": r["reg_cost"] * usd if usd else None, "est_net_month_usd": round(x["net"]),
                   "est_gross_month_usd": round(x["gross"]), "payback_days": round(payback, 1) if payback else None,
                   "cost_month_usd": round(x["cost_month"]), "p_earn": round(x["p_earn"], 3)},
        "how_to_top": how,
        "watch_out": [fl["text"] for fl in r["flags"]],
    }
