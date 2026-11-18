"""Scripted model for the Agent Upgrade Factory (mining_upgrade.py), on top of fake_missions (and so fake_infiagent and
fake_claude): AGENT_CLIENT_FACTORY=fake_upgrade:factory.

The factory's calls are told apart by their schema. The agent's name steers the outcome of its upgrade:
- first letter A-H: the candidate answers better (marker [q:hi]);
- I-P: the same as before ([q:mid] both ways);
- Q-Z: worse ([q:lo]), so the practice review asks for one revision, which stays worse.
A name containing "Mute" gets no exam tasks from the Examiner. FAKE_UPGRADE_SLOW (seconds) sleeps before each call, for
deadline and stop tests."""
import json, os, re, time

import fake_missions
from fake_claude import Resp

def _json(obj): return Resp([{"type": "text", "text": json.dumps(obj)}], "end_turn")

def _text(kw):
    m = kw["messages"][-1]["content"]
    return m if isinstance(m, str) else "\n".join(b.get("text", "") for b in m if b.get("type") == "text")

def _kind(name):
    c = (name or "?").strip()[:1].upper()
    return "hi" if "A" <= c <= "H" else "mid" if "I" <= c <= "P" else "lo"

DIMS = ("reasoning", "domain", "execution", "tools", "verification", "reliability", "collaboration")
LEVEL = {"hi": 8.5, "mid": 6.0, "lo": 4.0, "base": 6.0}

def _dims(v): return {k: v for k in DIMS}

def _upgrade(kw, req, system, p):
    if "overlaps" in req:  # the squad lead's diagnosis
        names = re.findall(r"^### ([^,\n]+),", p, re.M)
        return {"summary": f"{len(names)} members diagnosed.", "overlaps": ["Two members both summarize eval runs."] if len(names) > 1 else [],
                "agents": [{"name": n, "priority": 5 if i == 0 else 3, "strengths": ["Knows the task format."],
                            "weaknesses": [{"dimension": "verification", "issue": "Doesn't re-run the query it proposes.", "evidence": "Sent back twice for unchecked results."}]}
                           for i, n in enumerate(names)]}
    if "agents" in req and system.startswith("You are the Examiner"):
        names = re.findall(r"^- ([^,\n]+),", p, re.M)
        return {"agents": [{"name": n, "practice": [{"task": f"Practice {i} for {n}: fix a GROUP BY that double counts.", "rubric": "Finds the join fan-out."} for i in (1, 2)],
                            "exam": [] if "Mute" in n else [{"task": f"Exam {i} for {n}: a ClickHouse query that drops NULL rows.", "rubric": "Uses ifNull or a LEFT JOIN."} for i in (1, 2)]}
                           for n in names]}
    if req == ["answers"]:
        me = re.match(r"You are ([^,]+),", system)
        name = me.group(1) if me else "?"
        up = "UPGRADED" in system
        q = _kind(name) if up else "base"
        n = len(re.findall(r"^## Task \d+", p, re.M))
        return {"answers": [{"n": i + 1, "answer": f"[q:{q}] {name}'s answer {i + 1}" + (" (upgraded)" if up else "")} for i in range(n)]}
    if "tasks" in req and system.startswith("You are the Evaluator") and "two answers" in system:
        out = []
        for m in re.finditer(r"## Task (\d+).*?### Answer A\n(.*?)\n\n### Answer B\n(.*?)(?=\n\n## Task |\Z)", p, re.S):
            qa, qb = (re.search(r"\[q:(\w+)\]", x) for x in (m.group(2), m.group(3)))
            la, lb = LEVEL[qa.group(1) if qa else "base"], LEVEL[qb.group(1) if qb else "base"]
            out.append({"n": int(m.group(1)), "a": _dims(la), "b": _dims(lb), "note": "A checks its result." if la > lb else "B checks its result." if lb > la else "Alike."})
        return {"tasks": out}
    if "tasks" in req and system.startswith("You are the Evaluator"):
        n = len(re.findall(r"^## Task \d+", p, re.M))
        return {"tasks": [{"n": i + 1, "feedback": "Run the query on the sample before filing it.", "dims": _dims(6)} for i in range(n)]}
    if "model_advice" in req:
        me = re.search(r"The agent: ([^,]+),", p)
        name = me.group(1) if me else "?"
        v = "v2" if "Revise it" in p else "v1"
        return {"role": f"{name} owns query correctness.", "responsibilities": ["Check", "Fix", "Test", "Report", "Hand off"],
                "knowledge": ["ClickHouse drops NULLs in some aggregates."], "tools": "Read the notebook first.",
                "good_examples": ["A diff with a test", "A query run on the sample", "A checklist"],
                "failure_patterns": ["Unchecked queries"], "done_criteria": ["Ran on the sample"], "removed": ["A duplicated rule"],
                "instructions": f"UPGRADED {v}: run every query you propose on the sample data and say what it returned. Check NULLs, duplicates and ordering.",
                "changes": ["Added a verification step."], "model_advice": ""}
    return None

class Messages:
    def create(self, **kw):
        fmt = (kw.get("output_config") or {}).get("format")
        system = kw.get("system")
        system = system[0]["text"] if isinstance(system, list) else system or ""
        if fmt:
            req = fmt["schema"].get("required", [])
            if (r := _upgrade(kw, req, system, _text(kw))) is not None:
                if os.getenv("FAKE_UPGRADE_SLOW"): time.sleep(float(os.getenv("FAKE_UPGRADE_SLOW")))
                return _json(r)
        return fake_missions.Messages().create(**kw)

class Beta:
    messages = Messages()

class Client:
    beta = Beta()

def factory():
    return Client()
