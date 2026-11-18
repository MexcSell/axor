"""Rule-based risk flags. Every flag carries the measured reason, so users can judge it themselves, and its basis: what kind of
evidence it rests on (the 11-07 evaluation: tell verified facts from warning signals, missing information and history).

Levels, most severe first:
  scam    - on-chain/identity patterns typical of extraction or abandonment (signals, not proof)
  avoid   - you can't profitably get in right now
  caution - workable but with a specific trap to understand first
"""
import re

ORDER = {"scam": 3, "avoid": 2, "caution": 1, None: 0}
DEAD = re.compile(r"\b(for sale|deprecated|parked|satirical|abandon)", re.I)
EARLY = re.compile(r"not ready|early[- ]stage|design[- ]only|design docs|in development|draft|experimental|would\b|not yet live|open beta", re.I)
WTA = re.compile(r"winner[- ]take|winner[- ]takes|king[- ]of[- ]the[- ]hill|only the (single )?top|crown", re.I)

# the kind of evidence behind each flag; none of them is a verdict
BASIS = {"chain": "On-chain measurement", "history": "Historical trend", "text": "Pattern in published text",
         "missing": "Missing information", "requirement": "Published requirement"}
CODE_BASIS = {"abandoned": "text", "anonymous": "missing", "owner_capture": "chain", "closed_capture": "chain", "reg_closed": "chain",
              "no_uid": "chain", "no_emission": "chain", "dust": "chain", "slow_payback": "chain", "crash": "history",
              "winner_take_all": "chain", "owner_burn": "chain", "few_earners": "chain", "early": "text", "undocumented": "missing",
              "capital": "requirement", "outflow": "history", "very_new": "history"}

def _pct(x):
    return f"{x * 100:.0f}%"

def flags(r, usd):
    out = []
    add = lambda lvl, code, text, basis=None: out.append({"level": lvl, "code": code, "text": text, "basis": basis or CODE_BASIS.get(code, "chain")})
    text = " ".join([r.get("task", ""), r.get("conditions", ""), r.get("description", "")])
    has_repo = bool(r["links"].get("github"))
    has_identity = bool(r.get("description") or r["links"].get("web") or has_repo)
    earners, top_share, burn = r["earning_miners"], r["top_share"], r["owner_burn_share"]

    # --- scam / extraction signals ---
    if DEAD.search(" ".join([r.get("task", ""), r.get("description", ""), r.get("name", "")])):
        add("scam", "abandoned", "Identity marks the subnet as for sale, parked or deprecated - emissions with no working product.")
    if not has_identity:
        if r["emission_day"] > 0:
            add("scam", "anonymous", "Receives emission but has no on-chain identity, website or code repository: nothing to verify what miners are paid for.")
        else:
            add("avoid", "anonymous", "No on-chain identity, website or code repository.")
    if burn >= 0.9 and earners <= 3 and r["miner_pool_day"] > 0:
        add("scam", "owner_capture", f"Owner hotkey keeps {_pct(burn)} of miner emission and only {earners} outside miner(s) earn.")
    if top_share >= 0.9 and earners <= 3 and not has_repo:
        add("scam", "closed_capture", f"One hotkey takes {_pct(top_share)} of miner emission and there is no public code - consistent with owner-run miners.")

    # --- avoid: can't get in profitably now ---
    if not r["registration_allowed"]:
        add("avoid", "reg_closed", "Registration is disabled on this subnet.")
    elif not r["uid_available"]:
        add("avoid", "no_uid", "No UID available right now (full with immune miners, or registration rate limit hit).")
    if r["emission_day"] <= 0:
        add("avoid", "no_emission", "Subnet receives no TAO emission at the moment.")
    if usd and r["top_miner"] * usd < 1 and r["emission_day"] > 0:
        add("avoid", "dust", f"Even the top miner earns under $1/day ({r['top_miner']:.4f} τ).")
    if r["median_miner"] > 0 and r["reg_cost"] / r["median_miner"] > 60:
        add("avoid", "slow_payback", f"Registration ({r['reg_cost']:.3f} τ) takes {r['reg_cost'] / r['median_miner']:.0f} days to earn back at the median miner's rate.")
    pc = r.get("price_change_7d")
    if pc is not None and pc < -0.3:
        add("avoid", "crash", f"Alpha price fell {_pct(-pc)} in 7 days - earnings in TAO are shrinking fast.")

    # --- caution ---
    if WTA.search(text) or (top_share >= 0.6 and earners > 1):
        add("caution", "winner_take_all", f"Winner-take-most: top miner gets {_pct(top_share)} of miner emission.",
            "chain" if top_share >= 0.6 and earners > 1 else "text")
    if 0.5 <= burn < 0.9:
        add("caution", "owner_burn", f"{_pct(burn)} of miner emission goes to the owner/burn - smaller pool for miners.")
    if 0 < earners < 5 and not any(f["code"] in ("owner_capture", "closed_capture") for f in out):
        add("caution", "few_earners", f"Only {earners} miner(s) earn anything.")
    if EARLY.search(text):
        add("caution", "early", "Docs describe the mechanism as early-stage or in flux - rules may change under you.")
    if r.get("tier") == "unknown" and has_identity:
        add("caution", "undocumented", "Miner requirements are not published.")
    if r.get("tier") == "capital":
        add("caution", "capital", "Needs trading capital, collateral or stake that can be lost.")
    if r.get("tao_flow_day", 0) < 0 and (pc or 0) < -0.1:
        add("caution", "outflow", "Net TAO is flowing out of the subnet and price is falling - deregistration risk rises.")
    if r["age_days"] < 30:
        add("caution", "very_new", f"Only {r['age_days']:.0f} days old - no track record yet.")
    return out

def level(fl):
    return max((f["level"] for f in fl), key=lambda l: ORDER[l], default=None)
