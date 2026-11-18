"""Scripted model for Mission Control (missions.py), on top of fake_infiagent and fake_claude
(AGENT_CLIENT_FACTORY=fake_missions:factory), so a mission routed to Long tasks or the Workforce runs on their own fakes.

The Mission Engine's calls are told apart by their schema. Tags in the goal steer the script:
- [workforce] / [longtask] / [mining] / [direct] pick the engine (default: direct); "SN62" / "competition 28" fill mining_target;
- [ask] makes the understanding ask a question (once: the answered mission goes on);
- [partial] / [fail] make the reviewer find some / none of the criteria met;
- [deploy] makes the understanding list a gated action;
- [badplan] makes the first plan call return no JSON (an invalid output).
FAKE_SLOW (seconds) sleeps before each mission call, for pause, deadline and restart tests.
The Intelligence Analyst (mission_intel.py) reads market_overview once, then files a brief."""
import json, os, re, time

import fake_infiagent
from fake_claude import Resp

_bad = set()

def _json(obj): return Resp([{"type": "text", "text": json.dumps(obj)}], "end_turn")

def _text(kw):
    m = kw["messages"][-1]["content"]
    return m if isinstance(m, str) else "\n".join(b.get("text", "") for b in m if b.get("type") == "text")

def _goal(p):
    m = re.search(r"<goal>\n(.*?)\n</goal>", p, re.S)
    return m.group(1) if m else p

def _criteria(p):
    m = re.search(r"Acceptance criteria:\n((?:- .*\n?)+)", p)
    return [x[2:].strip() for x in m.group(1).splitlines()] if m else []

def _mission(kw, fmt):
    req = set(fmt["schema"].get("required", []))
    p = _text(kw)
    g = _goal(p).lower()
    if os.getenv("FAKE_SLOW"): time.sleep(float(os.getenv("FAKE_SLOW")))
    if {"engine", "criteria", "questions"} <= req:
        engine = next((e for e in ("workforce", "longtask", "mining") if f"[{e}]" in g), "direct")
        team = int(m.group(1)) if (m := re.search(r"- id (\d+):", p)) else 0
        return _json({"title": "Fake mission: " + re.sub(r"\[[a-z]+\]", "", _goal(p)).strip()[:40], "objective": "Deliver what the goal asks, checked.",
                      "targets": ["A written deliverable", "Every criterion addressed"],
                      "criteria": ["The deliverable names three options", "Each option has a risk", "There is a recommendation"],
                      "questions": ["Which subnet matters most to you?"] if "[ask]" in g and "<answers>" not in p else [],
                      "engine": engine, "engine_why": f"The goal is tagged {engine}.", "mining_team": team if engine == "mining" else 0,
                      "mining_target": {"netuid": int(x.group(1)) if (x := re.search(r"\bsn ?(\d+)", g)) else 0,
                                        "competition": int(x.group(1)) if (x := re.search(r"\bcompetition (\d+)", g)) else 0},
                      "gated_actions": ["Deploy the winning miner to production"] if "[deploy]" in g else [],
                      "complexity": "small", "hours": 0.2, "success": 80})
    if {"tasks", "brief"} <= req:
        key = g[:80]
        if "[badplan]" in g and key not in _bad:
            _bad.add(key)
            return Resp([{"type": "text", "text": "this is not json"}], "end_turn")
        return _json({"tasks": [{"id": 1, "title": "Collect the options", "owner": "research", "done_when": "Three options listed", "depends": []},
                                {"id": 2, "title": "Weigh the risks", "owner": "analysis", "done_when": "A risk per option", "depends": [1]},
                                {"id": 3, "title": "Recommend", "owner": "writing", "done_when": "One recommendation", "depends": [2]}],
                      "brief": "Collect three options, weigh a risk for each and recommend one. " + _goal(p)[:300],
                      "risks": ["Data may be stale: the deliverable says where each number comes from."]})
    if "deliverable" in req:
        return _json({"deliverable": "# Options\n\n1. **SN1**: risk: low liquidity.\n2. **SN8**: risk: heavy competition.\n3. **SN64**: risk: high registration cost.\n\n"
                                     "**Recommendation:** SN8, if you can match the top miners' latency.",
                      "summary": "Three options with a risk each, and a recommendation.", "limits": ["Numbers weren't checked against the live chain."]})
    if "results" in req:
        crit = _criteria(p)
        st = ["not_met"] * len(crit) if "[fail]" in p.lower() else ["met"] + ["partly"] * (len(crit) - 1) if "[partial]" in p.lower() else ["met"] * len(crit)
        return _json({"results": [{"criterion": c, "status": s, "evidence": f"Section on “{c[:30]}”" if s != "not_met" else "Missing."} for c, s in zip(crit, st)],
                      "limitations": ["The reviewer read only the deliverable."], "score": 82 if st and st[0] == "met" else 30})
    if "lessons" in req:
        return _json({"summary": "AXoR compared three options and recommended one; the reviewer checked each criterion.",
                      "recommendations": ["Re-check the numbers against the live chain before acting."],
                      "lessons": [{"kind": "worked", "text": "Listing a risk next to each option made the recommendation easy to check."}]})
    return None

_ids = iter(range(10**9))

def _analyst(kw):
    """mission_intel.py's research loop: one market lookup, then the brief (once filed, a closing line)."""
    used = [b.get("name") for m in kw["messages"] if m["role"] == "assistant" for b in m["content"] if b.get("type") == "tool_use"]
    call = lambda name, inp: Resp([{"type": "tool_use", "id": f"toolu_mx{next(_ids)}", "name": name, "input": inp}], "tool_use")
    if "file_brief" in used: return Resp([{"type": "text", "text": "Filed."}], "end_turn")
    if "market_overview" not in used: return call("market_overview", {})
    return call("file_brief", {"summary": "Three GPU subnets pay best right now; the leaders hold their ranks with low latency.",
                               "facts": [{"claim": "SN64 leads GPU subnets by daily emissions", "source": "market_overview", "as_of": "live", "confidence": "high"}],
                               "latest": [{"item": "SN8 changed its scoring this month", "source": "https://example.org/sn8", "date": "2026-11-01"}],
                               "competitors": [{"name": "UID 12 on SN8", "position": "rank 1", "edge": "Low latency", "opening": "High hardware cost"}],
                               "unknowns": ["Next week's registration cost"]})

class Messages:
    def create(self, **kw):
        fmt = (kw.get("output_config") or {}).get("format")
        system = kw.get("system")
        system = system[0]["text"] if isinstance(system, list) else system or ""
        if fmt and system.startswith("You are AXoR's Mission Engine") and (r := _mission(kw, fmt)) is not None:
            return r
        if system.startswith("You are the Intelligence Analyst"):
            return _analyst(kw)
        return fake_infiagent.Messages().create(**kw)

class Beta:
    messages = Messages()

class Client:
    beta = Beta()

def factory():
    return Client()
