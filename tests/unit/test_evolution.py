"""evolution.py (Evolution Lab): the evidence rule (verified only from paired numbers; promote refuses anything else), evidence
bound to the configuration it measured, policy auto-promotion only for low-risk configuration (never at L0, never code), versions
and rollback through the Agent Studio, and the analytics/governance read-outs built on it."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import agent_studio, analytics, evolution as evo, governance
from app.auth import AuthDB

ME = {"id": 7, "username": "leo", "role": "admin"}
OTHER = {"id": 8, "username": "ana", "role": "member"}


class Ov:
    def __init__(self, ok=True): self.ok = ok
    def _agents_ok(self, me): return self.ok


class FakeLLM:
    """An agent answers 'thorough' when its instructions say to cite sources; the judge scores thorough answers higher."""
    def __init__(self): self.calls = 0
    def completer(self, model, effort="medium"):
        def complete(system, tools, messages):
            self.calls += 1
            good = "cite sources" in system
            return [{"type": "text", "text": ("A thorough answer with sources." if good else "A short answer.") + "\n\n[[suggest: More | Less]]"}], "end_turn", 10
        return complete, "fake:model"
    def structured(self, model, system, prompt, schema, name="result", on_usage=None, effort="low", messages=None):
        if on_usage: on_usage(5)
        if name == "judgement":
            assert "candidate" not in prompt.lower() and "baseline" not in prompt.lower()  # blind: the judge never sees the arm
            assert "[[suggest" not in prompt  # suggested-reply chips are buttons in the chat, not answer text
            return {"score": 85 if "thorough" in prompt else 60, "verdict": "pass", "notes": "ok"}
        if name == "cases": return {"cases": [{"prompt": "Q?", "rubric": "R"}]}
        return {"title": "Cite sources", "hypothesis": "Sources raise quality.", "instructions": "Answer and cite sources."}


class FakeHub:
    def __init__(self, db):
        self.db, self.llm, self.on_update = db, FakeLLM(), None
        db.q("""CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, icon TEXT,
                color TEXT, face TEXT, kind TEXT, skills TEXT, examples TEXT, shared_with TEXT, in_directory INTEGER, status TEXT, updated REAL)""")
    def _get(self, aid):
        a = self.db.q("SELECT * FROM custom_agents WHERE id=?", (aid,), one=True)
        if not a: raise HTTPException(404, "Agent not found.")
        for k in ("skills", "examples", "shared_with"): a[k] = json.loads(a[k] or "[]")
        return a
    def _usable(self, aid, me): return self._owned(aid, me)
    def _owned(self, aid, me):
        a = self._get(aid)
        if a["owner_id"] != me["id"]: raise HTTPException(404, "Agent not found.")
        return a
    def update(self, me, aid, a):
        before = self._owned(aid, me)
        self.db.q("UPDATE custom_agents SET instructions=?, skills=?, updated=? WHERE id=?", (a.instructions, json.dumps(a.skills), time.time(), aid))
        if self.on_update: self.on_update(me, aid, before)
    def _skill_text(self, ids): return ""
    def tools_for(self, me): return []
    def log_usage(self, *a, **kw): pass


class EvolutionTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.hub = FakeHub(self.db)
        self.db.q("""INSERT INTO custom_agents (id, owner_id, name, role, description, instructions, icon, color, face, kind, skills, examples, shared_with,
                     in_directory, status) VALUES (1, 7, 'Py', 'Python engineer', '', 'Answer briefly.', 'bot', 'violet', '', '', '[]', '[]', '[]', 0, 'live')""")
        self.studio = agent_studio.Studio(self.db, Ov(), self.hub)
        self.studio.agent = lambda me, key: {}  # restore() answers with the Studio's full agent view, which needs the real hub
        self.ev = evo.Evolution(self.db, Ov(), self.hub, self.studio)
        self.bench = self.ev.save_bench(ME, evo.BenchIn(name="Python", target_key="hub:1",
                                                        cases=[{"prompt": f"Task {i}", "rubric": "Correct"} for i in range(3)]))

    def tearDown(self):
        self.ev.pool.shutdown(wait=True)
        self.dir.cleanup()

    def proposal(self, instructions="Answer and cite sources.", **kw):
        return self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title="Cite sources", instructions=instructions, benchmark_id=self.bench["id"], **kw))

    def experiment(self, pid):
        self.ev.run(ME, pid, evo.RunIn())
        self.ev.pool.shutdown(wait=True)
        self.ev.pool = evo.ThreadPoolExecutor(2)
        return self.ev.proposal(ME, pid)

    def test_evidence_rule(self):
        rows = lambda b, c: [{"case": f"c{i}", "arm": "baseline", "score": x} for i, x in enumerate(b)] + [{"case": f"c{i}", "arm": "candidate", "score": x} for i, x in enumerate(c)]
        pol = {"margin": 5, "min_cases": 3}
        self.assertTrue(evo.evidence(rows([60, 60, 60], [70, 70, 70]), pol)["verified"])
        self.assertFalse(evo.evidence(rows([60, 60], [90, 90]), pol)["verified"])            # too few cases
        self.assertFalse(evo.evidence(rows([60, 60, 60], [62, 63, 64]), pol)["verified"])    # under the margin
        e = evo.evidence(rows([60, 60, 60, 60, 60], [100, 100, 55, 55, 55]), pol)             # +16 on average but loses 3 of 5
        self.assertFalse(e["verified"]); self.assertIn("lost 3", " ".join(e["why"]))
        e = evo.evidence(rows([60, 60, 60], [80, 80, None]), pol)                             # a failed candidate answer
        self.assertFalse(e["verified"])

    def test_unverified_proposal_cannot_be_promoted(self):
        p = self.proposal()
        with self.assertRaises(HTTPException) as c: self.ev.promote(ME, p["id"])
        self.assertEqual(c.exception.status_code, 400)
        # a model-drafted proposal is just a proposal too
        d = self.ev.draft(ME, evo.DraftIn(target_key="hub:1"))
        self.assertEqual((d["status"], d["origin"]), ("proposed", "drafted"))
        with self.assertRaises(HTTPException): self.ev.promote(ME, d["id"])

    def test_experiment_verifies_promote_versions_and_rollback(self):
        p = self.experiment(self.proposal()["id"])
        self.assertEqual(p["status"], "verified")
        self.assertEqual((p["evidence"]["baseline"], p["evidence"]["candidate"], p["evidence"]["cases"]), (60, 85, 3))
        self.assertEqual(len(p["trials"]), 6)
        done = self.ev.promote(ME, p["id"])
        self.assertEqual((done["status"], done["decision"]), ("promoted", "human"))
        self.assertEqual(self.hub._get(1)["instructions"], "Answer and cite sources.")
        self.assertIsNotNone(done["before_version"]); self.assertGreater(done["after_version"], done["before_version"])
        back = self.ev.rollback(ME, p["id"])
        self.assertEqual(back["status"], "rolled_back")
        self.assertEqual(self.hub._get(1)["instructions"], "Answer briefly.")
        acts = [r["action"] for r in self.db.q("SELECT action FROM ev_audit ORDER BY id")]
        for a in ("experiment.started", "experiment.finished", "proposal.promoted", "proposal.rolled_back"): self.assertIn(a, acts)

    def test_worse_candidate_is_not_better(self):
        self.db.q("UPDATE custom_agents SET instructions='Answer and cite sources.' WHERE id=1")
        p = self.experiment(self.proposal(instructions="Answer briefly, no sources.")["id"])
        self.assertEqual(p["status"], "not_better")
        with self.assertRaises(HTTPException): self.ev.promote(ME, p["id"])

    def test_evidence_is_bound_to_the_measured_configuration(self):
        p = self.experiment(self.proposal()["id"])
        self.db.q("UPDATE custom_agents SET instructions='Changed by hand.' WHERE id=1")
        with self.assertRaises(HTTPException) as c: self.ev.promote(ME, p["id"])
        self.assertEqual(c.exception.status_code, 409)

    def test_policy_auto_never_promotes_on_a_models_judgment(self):
        """K-29 (Owner, 2026-11-13): promotion only on measured evidence or a person's approval. The experiment here is scored by
        a model, so under policy auto the verified change waits for the person; the person's own promote is their approval."""
        self.ev.set_policy(ME, evo.PolicyIn(mode="auto"))
        p = self.experiment(self.proposal()["id"])
        self.assertEqual((p["status"], p["decision"], p["basis"]), ("verified", None, "model_judged"))
        self.assertEqual(self.hub._get(1)["instructions"], "Answer briefly.")
        held = self.db.q("SELECT detail FROM ev_audit WHERE action='promotion.held'")
        self.assertEqual(len(held), 1); self.assertIn("measured evidence", held[0]["detail"])
        with self.assertRaises(HTTPException) as c: self.ev.promote(ME, p["id"], by_policy=True)
        self.assertEqual(c.exception.status_code, 403)
        done = self.ev.promote(ME, p["id"])
        self.assertEqual((done["status"], done["decision"]), ("promoted", "human"))
        self.assertIn("evidence: model judged", self.db.q("SELECT detail FROM ev_audit WHERE action='proposal.promoted'", one=True)["detail"])

    def test_the_policy_still_promotes_measured_config_evidence_but_not_at_L0(self):
        self.ev.set_policy(ME, evo.PolicyIn(mode="auto"))
        def mark(pid):  # the evidence as a measured trial would leave it (in Python: no JSON functions, so it runs on both databases)
            e = json.loads(self.db.q("SELECT evidence FROM ev_proposals WHERE id=?", (pid,), one=True)["evidence"])
            self.db.q("UPDATE ev_proposals SET evidence=? WHERE id=?", (json.dumps({**e, "basis": {"kind": "measured_internal"}}), pid))
        self.ev.set_policy(ME, evo.PolicyIn(mode="recommend"))
        p = self.experiment(self.proposal()["id"]); mark(p["id"])
        self.assertEqual(self.ev.promote(ME, p["id"], by_policy=True)["decision"], "policy")
        self.ev.rollback(ME, p["id"])
        self.db.q("CREATE TABLE og_agents (user_id INTEGER, key TEXT, autonomy INTEGER, status TEXT)")
        self.db.q("INSERT INTO og_agents VALUES (7, 'hub:1', 0, 'active')")
        self.ev.set_policy(ME, evo.PolicyIn(mode="auto"))
        q = self.experiment(self.proposal()["id"])                                      # at L0 Observe it waits for the person whatever the evidence
        self.assertEqual(q["status"], "verified")
        self.assertIn("promotion.held", [r["action"] for r in self.db.q("SELECT action FROM ev_audit")])

    def test_code_change_never_by_policy_and_recorded_evidence(self):
        p = self.ev.propose(ME, evo.ProposalIn(target_key="Engineering", target_kind="department", title="Pair reviews", change="Every PR gets two reviewers", risk="code"))
        with self.assertRaises(HTTPException): self.ev.run(ME, p["id"], evo.RunIn())  # experiments here are for your agents' configuration
        e = self.ev.record_evidence(ME, p["id"], evo.EvidenceIn(test_set="last 4 sprints", baseline=[50, 52, 49, 51], candidate=[61, 64, 60, 62]))
        self.assertEqual(e["status"], "verified")
        with self.assertRaises(HTTPException) as c: self.ev.promote(ME, p["id"], by_policy=True)
        self.assertEqual(c.exception.status_code, 403)
        self.assertEqual(self.ev.promote(ME, p["id"])["status"], "promoted")
        # your own agents' changes are measured by an experiment, not typed-in numbers
        q = self.proposal()
        with self.assertRaises(HTTPException): self.ev.record_evidence(ME, q["id"], evo.EvidenceIn(test_set="x", baseline=[1, 1, 1], candidate=[99, 99, 99]))

    def test_change_benchmark(self):
        p = self.ev.propose(ME, evo.ProposalIn(target_key="hub:1", title="Cite", instructions="Answer and cite sources."))
        with self.assertRaises(HTTPException): self.ev.run(ME, p["id"], evo.RunIn())  # no benchmark yet
        q = self.ev.set_benchmark(ME, p["id"], evo.PatchIn(benchmark_id=self.bench["id"]))
        self.assertEqual(q["benchmark_id"], self.bench["id"])
        other = self.ev.save_bench(ME, evo.BenchIn(name="Anyone", cases=[{"prompt": "x", "rubric": "y"}]))
        self.assertEqual(self.ev.set_benchmark(ME, p["id"], evo.PatchIn(benchmark_id=other["id"]))["benchmark_id"], other["id"])  # a benchmark for any agent fits
        self.db.q("INSERT INTO custom_agents (id, owner_id, name, instructions, skills, examples, shared_with, status) VALUES (2, 7, 'B', 'x', '[]', '[]', '[]', 'live')")
        theirs = self.ev.save_bench(ME, evo.BenchIn(name="B's", target_key="hub:2", cases=[{"prompt": "x", "rubric": "y"}]))
        with self.assertRaises(HTTPException): self.ev.set_benchmark(ME, p["id"], evo.PatchIn(benchmark_id=theirs["id"]))
        d = self.ev.draft(ME, evo.DraftIn(target_key="hub:1", benchmark_id=self.bench["id"]))
        self.assertEqual(d["benchmark_id"], self.bench["id"])

    def test_owner_scoping_and_gate(self):
        p = self.proposal()
        with self.assertRaises(HTTPException) as c: self.ev.proposal(OTHER, p["id"])
        self.assertEqual(c.exception.status_code, 404)
        with self.assertRaises(HTTPException): self.ev.propose(OTHER, evo.ProposalIn(target_key="hub:1", title="x", instructions="y"))
        off = evo.Evolution(self.db, Ov(False), self.hub, self.studio)
        with self.assertRaises(HTTPException) as c: off.view(ME)
        self.assertEqual(c.exception.status_code, 403)

    def test_tick_runs_queued_experiments_only_when_policy_allows(self):
        p = self.proposal()
        self.assertEqual(self.ev.tick(), 0)  # recommend: nothing runs on its own
        self.ev.set_policy(ME, evo.PolicyIn(mode="experiment"))
        self.db.q("INSERT INTO users (id, username, pw_hash, role) VALUES (7, 'leo', 'x', 'admin')")
        self.assertEqual(self.ev.tick(), 1)
        self.ev.pool.shutdown(wait=True)
        self.assertEqual(self.ev.proposal(ME, p["id"])["status"], "verified")  # verified, not promoted: experiment mode never promotes

    def test_analytics_and_governance(self):
        p = self.experiment(self.proposal()["id"])
        self.ev.promote(ME, p["id"])
        a = analytics.Analytics(self.db, Ov()).view(ME, 30, fresh=True)
        card = {c["k"]: c for c in a["scorecard"]}
        self.assertEqual(len(card), 8)
        self.assertEqual(card["improvement"]["value"], "+25.0 pts")
        self.assertEqual(card["evolution"]["state"], "ok")
        self.assertEqual(card["missions"]["state"], "none")  # no mission: no made-up number
        g = governance.Governance(self.db, Ov(), evo=self.ev).view(ME, fresh=True)
        self.assertEqual(g["rollback"][0]["id"], p["id"])
        self.assertEqual(len(g["levels"]), 5)
        self.assertTrue(any(x["action"] == "proposal.promoted" for x in g["audit"]))


if __name__ == "__main__":
    unittest.main()
