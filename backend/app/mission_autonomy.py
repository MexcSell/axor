"""Mission autonomy, set per mission and per kind of action (the 11-07 AXoR evaluation: "a single global Autopilot switch is
insufficient; autonomy should be configured per mission and action category").

A mission carries {"level": "L0".."L4", and optionally "plan", "recover", "external"} (mx_missions.autonomy, JSON). The level
sets every kind of action; a kind given on its own overrides the level. missions.py enforces it at its existing seams:

- plan      what happens once the plan is written. auto: it runs. ask: a request bound to that exact plan (sha256) waits for
            you; approve and it runs, decline with a note and AXoR re-plans. off: nothing runs; the plan and the research are
            the deliverable (a recommendation).
- recover   after a failed attempt. auto: retry or re-plan by itself (the failure's own recovery). ask: a request waits for
            you; approve and it tries again, decline and AXoR delivers what's done.
- external  deploys, uploads, submissions, payments, keys, deletions, permission changes (missions.GATED). AXoR never carries
            them out at any level. request: each becomes a hash-bound approval request in the Approval Center. list: they're
            only listed in the report.

A mission without a setting runs at DEFAULT (L3), which is exactly how missions ran before levels existed.
"""

KINDS = {
    "plan": ("Run the plan", {"auto": "Runs as soon as it's written", "ask": "Waits for your approval of the exact plan", "off": "Never runs: the plan is the deliverable"}),
    "recover": ("After a failure", {"auto": "Retries or re-plans by itself", "ask": "Asks you before trying again"}),
    "external": ("Deploys, uploads, payments, keys", {"request": "Each becomes an approval request (AXoR still never does it)", "list": "Only listed in the report"}),
}
# level: (name, what it means for a mission, {kind: choice}, attempts)
LEVELS = {
    "L0": ("Observe and recommend", "AXoR researches and writes the plan. Nothing is executed: the plan is the deliverable.",
           {"plan": "off", "recover": "ask", "external": "list"}, 3),
    "L1": ("Approve the plan", "AXoR researches and plans, then waits for you to approve the exact plan before any work runs.",
           {"plan": "ask", "recover": "ask", "external": "list"}, 3),
    "L2": ("Execute in sandbox", "Runs the plan and recovers from failures by itself. Deploys, uploads and payments are only listed.",
           {"plan": "auto", "recover": "auto", "external": "list"}, 3),
    "L3": ("Bounded operations", "As L2, and every deploy, upload or payment the goal implies becomes an approval request. The default.",
           {"plan": "auto", "recover": "auto", "external": "request"}, 3),
    "L4": ("High autonomy", "As L3 with up to 5 attempts instead of 3. Critical actions still always wait for you.",
           {"plan": "auto", "recover": "auto", "external": "request"}, 5),
}
DEFAULT = "L3"


def validate(a):
    """A posted setting, normalized to {"level", and the kinds that differ from it}; ValueError on anything unknown."""
    if a is None: return None
    if not isinstance(a, dict): raise ValueError("Autonomy is a level and, optionally, a choice per kind of action.")
    level = a.get("level") or DEFAULT
    if level not in LEVELS: raise ValueError(f"Unknown autonomy level {level!r}: use {', '.join(LEVELS)}.")
    out = {"level": level}
    for k, v in a.items():
        if k == "level" or v in (None, ""): continue
        if k not in KINDS: raise ValueError(f"Unknown kind of action {k!r}.")
        if v not in KINDS[k][1]: raise ValueError(f"{KINDS[k][0]}: choose {', '.join(KINDS[k][1])}.")
        if v != LEVELS[level][2][k]: out[k] = v
    return out


def resolve(a):
    """The policy a mission runs under: every kind's choice, the attempts, and the names to show."""
    a = a if isinstance(a, dict) else {}
    level = a.get("level") if a.get("level") in LEVELS else DEFAULT
    name, about, kinds, attempts = LEVELS[level]
    pol = {"level": level, "name": name, "about": about, "attempts": attempts, "custom": []}
    for k, (_, choices) in KINDS.items():
        v = a.get(k)
        pol[k] = v if v in choices else kinds[k]
        if pol[k] != kinds[k]: pol["custom"].append(k)
    pol["lines"] = {k: KINDS[k][1][pol[k]] for k in KINDS}
    return pol


def catalog():
    """For the intake form and Governance: the levels and the kinds of action with their choices."""
    return {"default": DEFAULT,
            "levels": [{"level": k, "name": n, "about": ab, "kinds": dict(ks), "attempts": at} for k, (n, ab, ks, at) in LEVELS.items()],
            "kinds": [{"kind": k, "label": l, "choices": dict(c)} for k, (l, c) in KINDS.items()]}
