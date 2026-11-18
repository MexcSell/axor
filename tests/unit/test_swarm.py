"""swarm.py (Agent Swarm, AXoR G5): the controller's plan held to the caps, contracts run over their dependencies, the
competitive contract compared blind, failed work reassigned, a contract's budget_limit stopping the work, requirements making
an adaptive swarm replan (and only passed on in a collaborative one), who may message whom per pattern, the track record and
its advice, resuming after a restart, and Mission Control running a mission on the swarm."""
import json, os, re, tempfile, time, unittest

from fastapi import HTTPException

from app import missions, swarm, workforce
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}


def plan(size="swarm", pattern="hybrid", contracts=None, why="Three workstreams."):
    return {"size": size, "pattern": pattern, "why": why, "contracts": contracts or [
        {"key": 1, "title": "Market scan", "objective": "Find the subnets with the highest emissions.", "deliverables": ["Top 3 subnets with numbers"],
         "depends": [], "agent": "market-researcher", "mode": "single", "contenders": [], "share": 30},
        {"key": 2, "title": "Miner design", "objective": "Propose a miner design.", "deliverables": ["A design"], "depends": [],
         "agent": "software-engineer", "mode": "competitive", "contenders": ["software-engineer", "ml-engineer"], "share": 40},
        {"key": 3, "title": "Plan", "objective": "Turn both into a 30-day plan.", "deliverables": ["A plan"], "depends": [1, 2],
         "agent": "planner", "mode": "single", "contenders": [], "share": 30}]}


class FakeLLM:
    """Scripted model. Agents: read the blackboard once, then file; markers in the contract steer them:
    BAD (the first attempt files a weak deliverable), GREEDY (keeps calling tools: the budget stops it), TALK (sends the
    controller a requirement first). The ML engineer's work is the strong one in a comparison."""
    TOK = 1000

    def __init__(self, t):
        self.t, self.calls, self.tools_seen, self.briefs = t, [], [], []

    def resolve(self, choice): return "fake", "m1"
    def configured(self, p): return True

    def structured(self, model, system, prompt, schema, name, on_usage=None, effort="low"):
        self.calls.append(name)
        if on_usage: on_usage(self.TOK)
        if name == "swarm_plan": return json.loads(json.dumps(self.t.plan))
        if name == "contract_check":
            bad = "BAD WORK" in prompt
            return {"verdict": "revise" if bad else "pass", "score": 40 if bad else 82, "note": "Add the numbers." if bad else "", "met": []}
        if name == "attempt_comparison":
            letters = schema["properties"]["winner"]["enum"]
            blocks = dict(re.findall(r"### Attempt ([A-C])\n(.*?)(?=\n### Attempt|\n\nCompare)", prompt, re.S))
            entries = [{"entry": L, "score": 88 if "STRONG" in blocks.get(L, "") else 64, "note": "ok"} for L in letters]
            return {"entries": entries, "winner": max(entries, key=lambda e: e["score"])["entry"], "why": "More evidence."}
        if name == "swarm_replan":
            queued = schema["properties"]["changes"]["items"]["properties"]["contract"]["enum"]
            self.t.replans.append(prompt)
            return {"changes": [{"contract": queued[0], "action": "revise", "objective": "Plan around the new rule: only CPU miners.", "note": "CPU only"}] if queued[0] else [],
                    "add": [], "notify": "New rule: CPU miners only.", "why": "A requirement changed."}
        if name == "swarm_result": return {"headline": "Three subnets and a plan", "report": "## Result\nDone.", "limits": ["Fake data"]}
        if name == "swarm_verdict":
            n = len(re.findall(r"^\d+\. ", prompt.split("Success criteria:\n")[1].split("\n\n")[0], re.M))
            return {"criteria": [{"criterion": i, "met": True, "note": "Met."} for i in range(1, n + 1)], "score": 81, "verdict": "pass"}
        raise AssertionError(name)

    def completer(self, choice, effort="medium"):
        def complete(system, tools, messages):
            names = [t["name"] for t in tools]
            brief = messages[0]["content"][0]["text"]
            agent = re.search(r'"assigned_agent":"([^"]+)"', brief).group(1)
            self.tools_seen.append((agent, names))
            if len(messages) == 1: self.briefs.append((agent, brief))
            turns = sum(1 for m in messages if m["role"] == "assistant")
            used = {b.get("name") for m in messages if m["role"] == "assistant" for b in m["content"] if isinstance(b, dict)}
            call = lambda n, i: ([{"type": "tool_use", "id": f"t{turns}", "name": n, "input": i}], "tool_use", self.TOK * (5 if "GREEDY" in brief else 1))
            if "GREEDY" in brief: return call("read_blackboard", {"query": ""})
            if "TALK" in brief and "send_message" in names and "send_message" not in used:
                return call("send_message", {"to": "controller", "kind": "requirement", "text": "The subnet only accepts CPU miners now."})
            if turns == 0: return call("read_blackboard", {"query": ""})
            if "submit_work" in used: return [{"type": "text", "text": "Filed."}], "end_turn", self.TOK
            first = "didn't pass" not in brief
            text = ("BAD WORK" if "BAD" in brief and first and agent == self.t.bad_agent else
                    "STRONG design with numbers" if agent == "ml-engineer" else f"Work by {agent} with numbers")
            return call("submit_work", {"deliverable": text, "summary": f"{agent} done", "used_memories": [],
                                        "findings": [{"kind": "finding", "text": f"{agent} found SN1 leads.", "evidence": "market_overview", "confidence": "high"}]})
        return complete, "fake:m1"


class Hub:
    def __init__(self, t): self.llm, self.source, self.usage = FakeLLM(t), None, []
    def tools_for(self, owner): return []
    def log_usage(self, owner, source, tokens, *a): self.usage.append((source, tokens))
    def gate(self, me): return me


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.plan, self.replans, self.bad_agent = plan(), [], "market-researcher"
        self.hub = Hub(self)
        self.wf = workforce.Workforce(self.db, self.hub, None)
        self.sw = swarm.Swarm(self.db, self.hub, self.wf)
        self.sw._submit = lambda sid, resume=False: None

    def tearDown(self):
        self.sw.pool.shutdown(wait=False); self.wf.pool.shutdown(wait=False)
        self.dir.cleanup()

    def run_swarm(self, goal="Find the best subnet to mine and plan the first month", **kw):
        b = swarm.SwarmIn(goal=goal, criteria=kw.pop("criteria", ["Names three subnets", "Gives a 30-day plan"]), budget=kw.pop("budget", 80_000), **kw)
        sid = self.sw.create(ME, b)
        self.sw._run(sid)
        return sid, self.sw.state(ME, sid)


class Plan(Base):
    def test_hybrid_swarm_end_to_end(self):
        sid, st = self.run_swarm()
        s = st["swarm"]
        self.assertEqual(s["status"], "done", s["error"])
        self.assertEqual((s["size"], s["pattern"], s["verdict"]), ("swarm", "hybrid", "pass"))
        cs = {c["key"]: c for c in st["contracts"]}
        self.assertEqual([c["status"] for c in cs.values()], ["done", "done", "done"])
        # the competitive contract: both contenders worked, the strong attempt won the blind comparison
        self.assertEqual(cs[2]["agent"], "ml-engineer")
        self.assertEqual(sorted(t["verdict"] for t in cs[2]["tries"]), ["lost", "pass"])
        self.assertIn("STRONG", cs[2]["output"])
        # the dependent contract started only after both and got their hand-offs
        brief = next(b for a, b in self.hub.llm.briefs if a == "planner")
        self.assertIn("market-researcher done", brief); self.assertIn("ml-engineer done", brief)
        self.assertGreaterEqual(cs[3]["started"], max(cs[1]["finished"], cs[2]["finished"]))
        # the spec's task contract
        self.assertEqual(set(cs[1]["contract"]) >= {"task_id", "mission_id", "assigned_agent", "objective", "deadline", "budget_limit", "status", "deliverables"}, True)
        self.assertEqual(cs[3]["contract"]["depends"], [f"sw{sid}-c1", f"sw{sid}-c2"])
        # tokens: the swarm's count is its runs' sum, and the usage went on the Workforce's line
        runs = self.db.q("SELECT COALESCE(SUM(tokens),0) n FROM sw_runs WHERE swarm_id=?", (sid,), one=True)["n"]
        self.assertEqual(s["tokens"], runs)
        self.assertTrue(all(src == "workforce" for src, _ in self.hub.usage))
        # findings are on the blackboard; the losing attempt's are withdrawn
        board = self.db.q("SELECT sender, status FROM sw_messages WHERE swarm_id=? AND kind='finding' AND recipient='all'", (sid,))
        self.assertIn(("software-engineer", "withdrawn"), [(r["sender"], r["status"]) for r in board])
        self.assertEqual(s["criteria_eval"][0]["met"], True)

    def test_controller_held_to_the_caps(self):
        many = [{"key": i, "title": f"C{i}", "objective": f"Do part {i}.", "deliverables": ["x"], "depends": [i + 1, i - 1, 99], "agent": a,
                 "mode": "competitive", "contenders": ["economist", "sre"], "share": 10}
                for i, a in enumerate(["market-researcher", "tech-researcher", "software-engineer", "ml-engineer", "planner", "economist",
                                       "sre", "release-manager", "risk-auditor", "nobody"], 1)]
        self.plan = plan(size="swarm", pattern="parallel", contracts=many)
        sid, st = self.run_swarm()
        cs = st["contracts"]
        self.assertLessEqual(len(cs), swarm.MAX_CONTRACTS)
        self.assertTrue(all(d < c["key"] for c in cs for d in c["depends"]))  # a DAG: only earlier contracts
        self.assertLessEqual(len({c["agent"] for c in cs}), swarm.MAX_AGENTS)
        self.assertTrue(all(c["mode"] == "single" for c in cs))  # parallel has no competitive contracts
        self.assertTrue(all(c["budget_limit"] >= swarm.MIN_LIMIT for c in cs))

    def test_solo_is_one_contract_for_one_agent(self):
        self.plan = plan(size="solo", pattern="parallel")
        sid, st = self.run_swarm(size="solo")
        self.assertEqual(len(st["contracts"]), 1)
        self.assertEqual(st["contracts"][0]["depends"], [])
        self.assertEqual(st["swarm"]["status"], "done")

    def test_user_preferences_bind_the_controller(self):
        self.plan = plan(size="team", pattern="competitive")
        sid = self.sw.create(ME, swarm.SwarmIn(goal="Compare two miner designs for SN1", pattern="competitive", size="team"))
        seen = {}
        orig = self.hub.llm.structured
        def spy(model, system, prompt, schema, name, **kw):
            if name == "swarm_plan": seen.update(size=schema["properties"]["size"]["enum"], pattern=schema["properties"]["pattern"]["enum"])
            return orig(model, system, prompt, schema, name, **kw)
        self.hub.llm.structured = spy
        self.sw._run(sid)
        self.assertEqual(seen, {"size": ["team"], "pattern": ["competitive"]})

    def test_bad_requests(self):
        for kw in ({"budget": 12345}, {"size": "huge"}, {"pattern": "chaos"}, {"deadline": time.time() + 5}):
            with self.assertRaises(HTTPException): self.sw.create(ME, swarm.SwarmIn(goal="A goal long enough", **kw))


class Recovery(Base):
    def test_failed_check_is_reassigned_with_the_note(self):
        self.plan = plan(pattern="parallel", contracts=[plan()["contracts"][0]])
        sid, st = self.run_swarm(goal="BAD first attempt: find the subnets with the highest emissions")
        c = st["contracts"][0]
        self.assertEqual(c["status"], "done")
        self.assertEqual([t["agent"] for t in c["tries"]], ["market-researcher", c["agent"]])
        self.assertNotEqual(c["agent"], "market-researcher")
        self.assertEqual([h["what"] for h in c["history"]], ["planned", "failed", "reassigned", "passed"])
        second = [b for a, b in self.hub.llm.briefs if a == c["agent"]][-1]
        self.assertIn("Add the numbers.", second)

    def test_hierarchical_reassigns_inside_the_team(self):
        self.plan = plan(pattern="hierarchical", contracts=[plan()["contracts"][0]])
        sid, st = self.run_swarm(goal="BAD first attempt: find the subnets with the highest emissions", pattern="hierarchical")
        c = st["contracts"][0]
        self.assertEqual(self.wf._team(7)[c["agent"]]["team"], "research")

    def test_budget_limit_stops_the_work(self):
        self.plan = plan(pattern="parallel", contracts=[{**plan()["contracts"][0], "objective": "GREEDY: read everything", "share": 5}])
        sid, st = self.run_swarm(budget=40_000)
        c = st["contracts"][0]
        self.assertEqual([t["status"] for t in c["tries"]], ["over_budget", "over_budget"])
        self.assertEqual(c["status"], "failed")
        for t in c["tries"]: self.assertLessEqual(t["tokens"], c["budget_limit"] + FakeLLM.TOK)  # stopped at the call that crossed it
        self.assertEqual(st["swarm"]["status"], "failed")
        self.assertIn("No contract was fulfilled", st["swarm"]["error"])


class Talk(Base):
    def contracts(self):
        a = {**plan()["contracts"][0], "objective": "TALK: scan the market and tell the controller about new rules"}
        b = {**plan()["contracts"][2], "depends": [1]}
        return [a, b]

    def test_requirement_makes_an_adaptive_swarm_replan(self):
        self.plan = plan(pattern="adaptive", contracts=self.contracts())
        sid, st = self.run_swarm(pattern="adaptive")
        self.assertEqual(st["swarm"]["adapts"], 1, [e["text"] for e in st["events"]])
        self.assertIn("CPU miners", self.replans[0])
        c2 = st["contracts"][1]
        self.assertEqual((c2["revision"], c2["objective"]), (1, "Plan around the new rule: only CPU miners."))
        brief = next(b for a, b in self.hub.llm.briefs if a == "planner")
        self.assertIn("revised this contract", brief)
        self.assertTrue(any(m["sender"] == "controller" and m["kind"] == "requirement" for m in st["messages"]))

    def test_collaborative_passes_it_on_without_replanning(self):
        self.plan = plan(pattern="collaborative", contracts=self.contracts())
        sid, st = self.run_swarm(pattern="collaborative")
        self.assertEqual(st["swarm"]["adapts"], 0)
        self.assertEqual(self.replans, [])
        self.assertTrue(any(m["sender"] == "controller" and "Passed on" in m["text"] for m in st["messages"]))

    def test_who_may_message_whom(self):
        for pattern, want in (("parallel", None), ("adaptive", ["controller"]), ("collaborative", "peers")):
            self.hub.llm.tools_seen.clear()
            self.plan = plan(pattern=pattern, contracts=[plan()["contracts"][0], {**plan()["contracts"][2], "depends": []}])
            sid, st = self.run_swarm(pattern=pattern)
            names = self.hub.llm.tools_seen[0][1]
            self.assertIn("read_blackboard", names); self.assertIn("read_messages", names)
            if want is None: self.assertNotIn("send_message", names)
        # the enum itself, for peers: the controller, everyone and the other agents of the swarm, never yourself
        s = self.sw._swarm(sid)
        defs = swarm.SEND_MESSAGE(["controller", "all", "planner"])
        self.assertEqual(defs["input_schema"]["properties"]["to"]["enum"], ["controller", "all", "planner"])
        self.assertEqual(sorted(s["decision"]["agents"]), ["market-researcher", "planner"])

    def test_unread_notice_reaches_one_agent_only(self):
        sid = self.sw.create(ME, swarm.SwarmIn(goal="A goal long enough to plan"))
        ctx = {**self.sw._ctx(self.sw._swarm(sid)), "akey": "planner"}
        self.db.q("INSERT INTO sw_messages (swarm_id, sender, recipient, kind, text, created) VALUES (?, 'economist', 'planner', 'request', 'hi', 0)", (sid,))
        self.assertEqual(self.sw._unread(ctx), 1)
        self.assertEqual(self.sw._unread({**ctx, "akey": "sre"}), 0)
        self.sw._read_messages(ctx, "planner")
        self.assertEqual(self.sw._unread(ctx), 0)
        cache = swarm._Cache()
        cache["k"] = {"data": 1, "_swarm": "1 unread"}
        self.assertEqual(cache["k"], {"data": 1})


class Record(unittest.TestCase):
    def rows(self, pattern, score, n, goal="find the best subnet emissions plan"):
        return [{"title": "x", "goal": goal, "pattern": pattern, "size": "team", "score": score, "tokens": 1000, "started": 0, "finished": 60}] * n

    def test_advise_switches_only_on_clear_evidence(self):
        want = swarm._words("best subnet emissions plan")
        rec = swarm.record(self.rows("parallel", 20, 3) + self.rows("hybrid", 90, 3), want)
        self.assertEqual(rec["similar"], 6)
        p, why = swarm.advise(rec, "parallel")
        self.assertEqual(p, "hybrid"); self.assertIn("similar earlier swarms", why)
        self.assertEqual(swarm.advise(rec, "parallel", fixed=True), ("parallel", None))
        thin = swarm.record(self.rows("parallel", 20, 2) + self.rows("hybrid", 90, 3), want)
        self.assertEqual(swarm.advise(thin, "parallel"), ("parallel", None))  # too few runs to judge
        other = swarm.record(self.rows("parallel", 20, 3, goal="audit wallet key safety"), want)
        self.assertEqual(other["similar"], 0)  # unlike goals don't count
        self.assertIn("<track_record>", swarm.record_lines(rec))


class Restart(Base):
    def test_resume_keeps_done_contracts(self):
        self.plan = plan(pattern="parallel", contracts=[plan()["contracts"][0], {**plan()["contracts"][2], "depends": [1]}])
        sid = self.sw.create(ME, swarm.SwarmIn(goal="Find the best subnet to mine and plan"))
        s = self.sw._swarm(sid)
        ctx = self.sw._ctx(s)
        self.sw._set(sid, status="running", step="execute")
        self.sw._plan(ctx, self.sw._swarm(sid))
        c1, c2 = self.sw._contracts(sid)
        self.sw._cset(c1["id"], status="done", output="earlier work", summary="earlier", score=80, verdict="pass")
        self.sw._cset(c2["id"], status="running")
        again = swarm.Swarm(self.db, self.hub, self.wf)  # the server restarts
        again._submit = lambda sid, resume=False: None
        self.assertEqual(again._contracts(sid)[1]["status"], "queued")
        before = len(self.hub.llm.briefs)
        again._run(sid, resume=True)
        st = again.state(ME, sid)
        self.assertEqual(st["swarm"]["status"], "done")
        self.assertEqual([a for a, _ in self.hub.llm.briefs[before:]], ["planner"])  # contract 1 wasn't redone
        again.pool.shutdown(wait=False)

    def test_members_see_only_their_swarms(self):
        sid = self.sw.create(ME, swarm.SwarmIn(goal="A goal long enough to plan"))
        with self.assertRaises(HTTPException): self.sw.state({"id": 8, "username": "ana", "role": "member"}, sid)
        with self.assertRaises(HTTPException): self.sw.delete(ME, sid)  # still queued: cancel first
        self.sw.cancel(ME, sid)
        self.assertEqual(self.sw._swarm(sid)["status"], "cancelled")


class MissionEngine(Base):
    def test_mission_control_runs_on_the_swarm(self):
        mx = missions.Missions(self.db, hub=None, wf=self.wf, ia=None, mw=None, sw=self.sw)
        self.assertTrue(mx._engines(7)["swarm"])
        self.assertIn("swarm", missions.UNDERSTAND["properties"]["engine"]["enum"])
        now = time.time()
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, status, stage, engine, understanding, allocation, plan, created, updated)
                           VALUES (7, 'Pick a subnet', 'Find the best subnet to mine and plan', 5, 'running', 'execute', 'swarm', ?, ?, ?, ?, ?) RETURNING id""",
                        (json.dumps({"criteria": ["Names three subnets"], "objective": "x"}), json.dumps({"child_budget": 80_000}),
                         json.dumps({"brief": "Find the best subnet to mine and plan the month."}), now, now), one=True)["id"]
        mx._owner = lambda uid: ME
        self.assertEqual(mx._launch(mx._m(mid)), "running")
        m = mx._m(mid)
        s = self.sw._swarm(m["child"])
        self.assertEqual((s["parent"], s["budget"]), (mid, 80_000))
        self.assertEqual(mx._child(m)[0], "running")
        self.sw._run(m["child"])
        st, tok, err = mx._child(mx._m(mid))
        self.assertEqual(st, "done", err)
        self.assertGreater(tok, 0)
        self.assertIsNone(self.sw._swarm(m["child"])["verdict"])  # no final check of its own: Mission Control verifies
        d = mx._collect(mx._m(mid))
        self.assertEqual((d["kind"], d["link"]["view"]), ("swarm", "swarm"))
        self.assertEqual(len(d["items"]), 3)
        self.sw.score_from_mission(m["child"], "partial")
        self.assertEqual(self.sw._swarm(m["child"])["score"], 50)


if __name__ == "__main__":
    unittest.main()
