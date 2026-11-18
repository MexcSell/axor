"""Scripted model for the Agent Swarm (swarm.py), on top of fake_missions (AGENT_CLIENT_FACTORY=fake_swarm:factory), so a
Mission Control mission forced onto the swarm runs too. For running AXoR by hand against fakes; not a test.

The controller plans a hybrid swarm of three contracts: a market scan (the market researcher, who first tells the controller
about a new requirement, which makes it revise the plan contract), a competitive miner design (the software engineer against
the ML engineer, whose attempt is the stronger one) and a 30-day plan after both (the planner). "[bad]" in the goal makes the
market scan's first attempt weak, so the evaluator sends it back and it's reassigned. FAKE_SWARM_SLOW (seconds, default 1.5)
sleeps before each agent turn, so the page shows the swarm at work."""
import itertools, json, os, re, time

import fake_missions
from fake_claude import Resp

_ids = itertools.count(1)

def _json(obj): return Resp([{"type": "text", "text": json.dumps(obj)}], "end_turn")

def _text(content):
    return content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")

def _plan(props, prompt):
    keys = props["contracts"]["items"]["properties"]["agent"]["enum"]
    pick = lambda *want: next((k for k in want if k in keys), keys[0])
    sizes, pats = props["size"]["enum"], props["pattern"]["enum"]
    a, b, c, p = pick("market-researcher"), pick("software-engineer"), pick("ml-engineer"), pick("planner", "economist")
    return {"size": "swarm" if "swarm" in sizes else sizes[0], "pattern": "hybrid" if "hybrid" in pats else pats[0],
            "why": "Two independent workstreams (the market and a miner design) feed one plan; the design is worth two competing attempts.",
            "contracts": [
                {"key": 1, "title": "Scan the GPU subnet market", "objective": "Find the three subnets that pay GPU miners best right now, with emissions and registration cost.",
                 "deliverables": ["Three subnets with daily emissions", "Registration cost of each"], "depends": [], "agent": a, "mode": "single", "contenders": [], "share": 30},
                {"key": 2, "title": "Design the miner", "objective": "Propose a miner design for a single RTX 4090 that can reach the top 20.",
                 "deliverables": ["Architecture", "Expected rank and why"], "depends": [], "agent": b, "mode": "competitive", "contenders": [b, c], "share": 40},
                {"key": 3, "title": "Plan the first 30 days", "objective": "Turn the market scan and the design into a 30-day plan with costs.",
                 "deliverables": ["Week-by-week plan", "Costs and payback"], "depends": [1, 2], "agent": p, "mode": "single", "contenders": [], "share": 30}]}

def _structured(kw, fmt):
    props, prompt = fmt["schema"].get("properties", {}), _text(kw["messages"][-1]["content"])
    if {"size", "pattern", "contracts"} <= set(props): return _json(_plan(props, prompt))
    if {"verdict", "score", "note", "met"} <= set(props):
        weak = "weak draft" in prompt
        return _json({"verdict": "revise" if weak else "pass", "score": 41 if weak else 84,
                      "note": "No registration costs: add them for each subnet." if weak else "", "met": []})
    if {"entries", "winner"} <= set(props):
        letters = props["winner"]["enum"]
        blocks = dict(re.findall(r"### Attempt ([A-C])\n(.*?)(?=\n### Attempt|\n\nCompare)", prompt, re.S))
        es = [{"entry": L, "score": 88 if "STRONG" in blocks.get(L, "") else 66, "note": "Concrete numbers." if "STRONG" in blocks.get(L, "") else "Vague on latency."} for L in letters]
        return _json({"entries": es, "winner": max(es, key=lambda e: e["score"])["entry"], "why": "Its latency budget is backed by numbers."})
    if {"changes", "add", "notify"} <= set(props):
        q = props["changes"]["items"]["properties"]["contract"]["enum"]
        return _json({"changes": [{"contract": q[-1], "action": "revise", "objective": "Plan the first 30 days for a CPU-capable fallback too: SN8 now also scores CPU miners.",
                                   "note": "SN8 now scores CPU miners as well"}] if q and q[-1] else [],
                      "add": [], "notify": "SN8 now also scores CPU miners: keep a CPU fallback in mind.", "why": "The market scan found a scoring change."})
    if {"headline", "report", "limits"} <= set(props):
        return _json({"headline": "SN8, SN64 and SN19 pay GPU miners best; a 4090 design and a 30-day plan",
                      "report": "## Result\nMine SN64 first with the ML engineer's design; keep SN8 as the CPU fallback.\n\n## What the swarm found\n- **Contract 1**: SN64 leads at τ 410/day.\n"
                                "- **Contract 2**: a batched-inference design, expected rank 12-18.\n- **Contract 3**: break-even in week 3.\n\n## Risks and open questions\n- Registration cost doubled this week.\n\n## Next steps\n- Register on SN64 (yours to approve).",
                      "limits": ["Emissions are today's; they move daily."]})
    if {"criteria", "score", "verdict"} <= set(props):
        n = len(re.findall(r"^\d+\. ", prompt.split("Success criteria:\n")[1].split("\n\n")[0], re.M)) if "Success criteria:\n" in prompt else 0
        return _json({"criteria": [{"criterion": i, "met": True, "note": "Covered with numbers."} for i in range(1, n + 1)], "score": 83, "verdict": "pass"})
    return None

def _agent(kw):
    msgs, names = kw["messages"], [t["name"] for t in kw.get("tools", [])]
    brief = _text(msgs[0]["content"])
    agent = (re.search(r'"assigned_agent":"([^"]+)"', brief) or [None, "agent"])[1]
    turns = sum(1 for m in msgs if m["role"] == "assistant")
    used = {b.get("name") for m in msgs if m["role"] == "assistant" for b in m["content"] if isinstance(b, dict)}
    time.sleep(float(os.getenv("FAKE_SWARM_SLOW", "1.5")))
    call = lambda n, i: Resp([{"type": "tool_use", "id": f"toolu_sw{next(_ids)}", "name": n, "input": i}], "tool_use")
    if "submit_work" in used: return Resp([{"type": "text", "text": "Filed."}], "end_turn")
    if turns == 0: return call("read_blackboard", {"query": ""})
    if agent == "market-researcher" and "send_message" in names and "send_message" not in used and "didn't pass" not in brief:
        return call("send_message", {"to": "controller", "kind": "requirement", "text": "SN8 changed its scoring: CPU miners now score too. The plan should keep a CPU fallback."})
    if "read_messages" in names and "read_messages" not in used and agent == "planner": return call("read_messages", {})
    weak = "[bad]" in brief and agent == "market-researcher" and "didn't pass" not in brief
    out = {"market-researcher": "weak draft: SN64 and SN8 look good." if weak else "| Subnet | τ/day | Registration |\n|---|---|---|\n| SN64 | 410 | τ 0.8 |\n| SN8 | 280 | τ 0.5 |\n| SN19 | 190 | τ 0.3 |",
           "ml-engineer": "STRONG design: batched inference with a 120 ms latency budget; expected rank 12-18 on one 4090.",
           "software-engineer": "A simple single-request server; rank unclear.",
           "planner": "- Week 1: register on SN64\n- Week 2-3: tune latency\n- Week 4: review; break-even in week 3 at τ 410/day"}.get(agent, f"Work by {agent}, with numbers.")
    return call("submit_work", {"deliverable": out, "summary": out.splitlines()[0][:160], "used_memories": [],
                                "findings": [{"kind": "finding", "text": f"{agent}: SN64 leads GPU emissions at τ 410/day.", "evidence": "market_overview", "confidence": "high"}]})

class Messages:
    def create(self, **kw):
        fmt = (kw.get("output_config") or {}).get("format")
        system = kw.get("system")
        system = system[0]["text"] if isinstance(system, list) else system or ""
        if "AXoR Agent Swarm" in system and fmt and (r := _structured(kw, fmt)) is not None: return r
        if "working in an agent swarm" in system and not fmt: return _agent(kw)
        return fake_missions.Messages().create(**kw)

class Beta:
    messages = Messages()

class Client:
    beta = Beta()

def factory():
    return Client()
