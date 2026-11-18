"""knowledge_improve.py (company Knowledge Hub milestones 5–7): agents' outcomes only on records they read, confidence that
follows outcomes (a version each), records flagged contested when outcomes turn against them and cleared by approving again,
the tools reaching every agent system (also the id-only agent_tools path), cross-project discovery that names scopes but never
records, access requests decided by the user (a grant), suggested connections and duplicate merges, and model revisions that
supersede the original only once approved."""
import os, tempfile, time, unittest

os.environ.setdefault("KNOWLEDGE_INDEX", "0"); os.environ.setdefault("KNOWLEDGE_SYNC", "0")  # no background loops in tests

from fastapi import HTTPException

from app import knowledge_hub as kh
from app.auth import AuthDB
from app.knowledge_improve import AccessDecideIn, ReviseIn, SuggestIn
from app.knowledge_spaces import DecideIn, OutcomeIn, RecordIn

ME = {"id": 7, "username": "leo", "role": "admin"}


class LLM:
    def __init__(self): self.calls, self.prompts = [], []
    def any_configured(self): return True
    def structured(self, model, system, prompt, schema, name, on_usage=None, effort=None, **kw):
        self.calls.append(name); self.prompts.append(prompt)
        if on_usage: on_usage(9)
        if name == "revise":
            return {"title": "Warm the cache first (revised)", "body": "Warm the embedding cache before the run; it failed twice on cold starts, so check the cache is warm.",
                    "changes": ["Says it fails on cold starts (two failures)."], "why": "Two failures on cold starts."}
        raise AssertionError(name)


class HubStub:
    def __init__(self): self.llm = LLM()
    def log_usage(self, *a, **k): pass
    def model_of(self, m): return "fake"


class ImproveTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q, now = self.db.q, time.time()
        q("INSERT INTO users (id, username, pw_hash, created) VALUES (7, 'leo', 'x', ?)", (now,))
        q("CREATE TABLE custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER, name TEXT, role TEXT, description TEXT, instructions TEXT, skills TEXT, status TEXT, updated REAL)")
        q("CREATE TABLE agent_memory (id INTEGER PRIMARY KEY, agent_id INTEGER, user_id INTEGER, text TEXT, source TEXT, created REAL)")
        q("CREATE TABLE co_company (id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, name TEXT)")
        q("CREATE TABLE co_divisions (id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, status TEXT DEFAULT 'active')")
        q("CREATE TABLE co_projects (id INTEGER PRIMARY KEY, company_id INTEGER, division_id INTEGER, name TEXT, objective TEXT, status TEXT DEFAULT 'planning')")
        q("INSERT INTO custom_agents VALUES (1, 7, 'Scout', 'Researcher', '', 'Research.', '[]', 'live', ?)", (now,))
        q("INSERT INTO co_company VALUES (1, 7, 'AXoR Co')")
        q("INSERT INTO co_divisions VALUES (3, 1, 'Bittensor', 'active')")
        q("INSERT INTO co_projects VALUES (5, 1, NULL, 'SN62', 'Rank up', 'active')")
        q("INSERT INTO co_projects VALUES (6, 1, NULL, 'Handshake', 'Other', 'active')")
        self.hub = HubStub()
        self.K = kh.Hub(self.db, self.hub, lambda m: None)

    def tearDown(self):
        self.dir.cleanup()

    def rec(self, title, body, scope="company", ktype="procedural", conf=0.8):
        r = self.K.add_record(ME, RecordIn(title=title, body=body, ktype=ktype, scope=scope, evidence="EXP-1", approve=True))
        if conf is not None:
            k = self.K._item(ME, r["id"])
            r = self.K.decide(ME, r["id"], DecideIn(decision="approve", hash=k["hash"], confidence=conf))
        return r

    def search(self, actor, query, me=ME):
        return self.K.tool(me, {"query": query, "scope": "", "knowledge_type": ""}, "search_knowledge", actor)

    def report(self, actor, iid, result, me=ME):
        return self.K.tool(me, {"ref": f"kb:{iid}", "result": result, "note": "Ran it on the SN62 miner and watched the scores."}, "report_outcome", actor)

    def test_tools_reach_every_agent_system(self):
        names = {t["name"] for t in self.K.TOOLS}
        self.assertTrue({"search_knowledge", "contribute_knowledge", "knowledge_feedback", "report_outcome", "request_knowledge_access"} <= names, names)
        self.assertEqual(self.K.NAMES, names)
        kbt = self.K.agent_tools(7, "workforce", "Workforce")
        self.assertTrue({"search_knowledge", "report_outcome", "request_knowledge_access"} <= set(kbt), set(kbt))
        r = self.rec("Warm the embedding cache", "Warm the embedding cache before each evaluation run so the first batch isn't slow.")
        hits = kbt["search_knowledge"][1]({"query": "embedding cache evaluation", "scope": "", "knowledge_type": ""})
        self.assertIn(f"kb:{r['id']}", [h["ref"] for h in hits["results"]])
        self.assertIn("report_outcome", hits["note"])
        out = kbt["report_outcome"][1]({"ref": f"kb:{r['id']}", "result": "success", "note": "Workforce used it; the first batch took 2 s instead of 30 s."})  # id-only me
        self.assertEqual(out["status"], "kept", out)
        self.assertEqual(self.K.item(ME, r["id"])["data"]["outcomes"][-1]["by"], "Workforce")

    def test_outcomes_move_confidence_flag_and_clear(self):
        r = self.rec("Warm the embedding cache", "Warm the embedding cache before each evaluation run so the first batch isn't slow.")
        self.assertIn("error", self.report("assistant", r["id"], "failure"))  # not read yet
        self.search("assistant", "embedding cache evaluation")
        v0 = self.K.item(ME, r["id"])["version"]
        out = self.report("assistant", r["id"], "failure")
        self.assertEqual(out["status"], "kept", out)
        it = self.K.item(ME, r["id"])
        self.assertAlmostEqual(it["confidence"], 0.64, places=3)  # (0.8*4 + 0) / 5
        self.assertEqual(it["version"], v0 + 1)
        self.assertIn("80% → 64%", it["versions"][0]["note"])
        self.assertEqual(it["state"], "verified")
        self.assertIn("error", self.report("assistant", r["id"], "failure"))  # once a day per agent
        self.search("workforce", "embedding cache evaluation")
        out = self.report("workforce", r["id"], "failure")
        it = self.K.item(ME, r["id"])
        self.assertEqual(it["state"], "contested")  # two failures, no success: flagged, never deleted
        self.assertTrue(it["health"]["failing"])
        self.assertEqual(len(it["data"]["outcomes"]), 2)
        view = self.K.company_view(ME)
        q = next(x for x in view["queue"] if x["id"] == r["id"])
        self.assertEqual(q["why"], "contested"); self.assertIn("outcomes", q["detail"])
        self.assertEqual(view["improve"]["outcomes_30d"]["failure"], 2)
        self.assertEqual(view["improve"]["flagged"][0]["id"], r["id"])
        self.assertEqual(sum(1 for u in self.db.q("SELECT useful FROM kb_uses WHERE item_id=? AND query='outcome'", (r["id"],)) if u["useful"] == 0), 2)
        k = self.K._item(ME, r["id"])
        it = self.K.decide(ME, r["id"], DecideIn(decision="approve", hash=k["hash"], confidence=0.7, note="Fixed the cold-start case"))
        self.assertEqual(it["state"], "verified")
        self.assertNotIn("flag", it["data"])
        self.assertEqual(it["health"]["outcomes"], 0)  # counted again from this approval
        it = self.K.outcome(ME, r["id"], OutcomeIn(result="success", note="Worked after the fix"))
        self.assertAlmostEqual(it["confidence"], (0.7 * 4 + 1) / 5, places=3)

    def test_outcomes_only_on_company_records_and_reviewed_ones_keep_confidence(self):
        r = self.K.add_record(ME, RecordIn(title="Unreviewed tip", body="Pin the torch version before every miner build, always.", ktype="procedural", scope="company"))
        it = self.K.outcome(ME, r["id"], OutcomeIn(result="failure", note="Broke the build"))
        self.assertEqual(it["state"], "submitted"); self.assertEqual(len(it["data"]["outcomes"]), 1)
        self.assertEqual(it["confidence"], r["confidence"])  # the reviewer sets it

    def test_discovery_names_scopes_not_records_and_access_is_the_users_call(self):
        far = self.rec("Handshake latency fix", "Batch the handshake requests to cut validator latency by half.", scope="project:6")
        self.rec("SN62 ranking notes", "Ranking depends on validator latency and the batch size of answers.", scope="project:5")
        out = self.search("project:5", "handshake validator latency batch")
        self.assertNotIn(f"kb:{far['id']}", [h["ref"] for h in out["results"]])
        self.assertEqual(out["elsewhere"], [{"scope": "project:6", "label": "Handshake", "kind": "project", "records": 1, "asked": ""}])
        self.assertNotIn("Handshake latency fix", str(out["elsewhere"]))
        self.assertIn("error", self.K.tool(ME, {"scope": "project:6", "reason": "x"}, "request_knowledge_access", "project:5"))
        a = self.K.tool(ME, {"scope": "project:6", "reason": "SN62 ranking depends on validator latency; their fix may apply."}, "request_knowledge_access", "project:5")
        self.assertEqual(a["status"], "pending")
        self.assertEqual(self.K.tool(ME, {"scope": "project:6", "reason": "SN62 ranking depends on validator latency."}, "request_knowledge_access", "project:5")["status"], "pending")
        self.assertEqual(self.search("project:5", "handshake validator latency batch")["elsewhere"][0]["asked"], "pending")
        view = self.K.company_view(ME)
        self.assertEqual(view["counts"]["requests"], 1)
        p = view["access"]["pending"][0]
        self.assertEqual((p["label"], p["scope_label"], p["records"]), ("SN62", "Handshake", 1))
        self.K.decide_access(ME, p["id"], AccessDecideIn(decision="approve"))
        out = self.search("project:5", "handshake validator latency batch")
        self.assertIn(f"kb:{far['id']}", [h["ref"] for h in out["results"]])
        self.assertNotIn("elsewhere", out)
        self.assertIn("project:6", self.K.allowed(ME, "project:5"))
        with self.assertRaises(HTTPException): self.K.decide_access(ME, p["id"], AccessDecideIn(decision="decline"))
        b = self.K.tool(ME, {"scope": "project:6", "reason": "The Assistant wants the latency fix for a question."}, "request_knowledge_access", "assistant")
        self.K.decide_access(ME, b["request"], AccessDecideIn(decision="decline", note="Not for chats"))
        again = self.K.tool(ME, {"scope": "project:6", "reason": "The Assistant wants the latency fix again."}, "request_knowledge_access", "assistant")
        self.assertEqual(again["status"], "declined"); self.assertIn("Not for chats", again["note"])
        self.assertEqual(self.K.tool(ME, {"scope": "company", "reason": "nothing to ask for here at all"}, "request_knowledge_access", "assistant")["status"], "allowed")

    def test_suggested_connections_and_duplicates(self):
        a = self.rec("Validator latency budget", "Keep validator latency under two seconds per answer batch for the miner.", scope="project:5")
        b = self.rec("Latency budget for validators", "Keep validator latency under two seconds per answer batch, measured at the miner.", scope="project:6")
        c = self.rec("Validator latency budget again", "Keep validator latency under two seconds per answer batch for the miner, always.", scope="project:5")
        self.rec("Unrelated", "Office plants need water on Fridays.", scope="project:6")
        s = self.K.suggestions(ME, fresh=True)
        pairs = {(p["kind"], frozenset((p["a"]["id"], p["b"]["id"]))) for p in s["related"] + s["duplicates"]}
        self.assertIn(("related", frozenset((a["id"], b["id"]))), pairs, s)
        self.assertIn(("duplicate", frozenset((a["id"], c["id"]))), pairs, s)
        self.assertEqual(s["mode"], "words")
        s = self.K.take_suggestion(ME, SuggestIn(a=a["id"], b=b["id"], kind="related"))
        self.assertTrue(any(ln["rel"] == "related_to" and ln.get("item") == b["id"] for ln in self.K.item(ME, a["id"])["links"]))
        self.assertNotIn(frozenset((a["id"], b["id"])), {frozenset((p["a"]["id"], p["b"]["id"])) for p in s["related"]})
        with self.assertRaises(HTTPException): self.K.take_suggestion(ME, SuggestIn(a=a["id"], b=c["id"], kind="duplicate"))
        self.K.take_suggestion(ME, SuggestIn(a=a["id"], b=c["id"], kind="duplicate", keep=a["id"]))
        self.assertEqual(self.K.item(ME, c["id"])["state"], "superseded")
        s = self.K.dismiss_suggestion(ME, SuggestIn(a=b["id"], b=c["id"], kind="related"))
        self.assertNotIn(frozenset((b["id"], c["id"])), {frozenset((p["a"]["id"], p["b"]["id"])) for p in s["related"]})

    def test_revision_supersedes_only_once_approved(self):
        r = self.rec("Warm the cache", "Warm the embedding cache before each evaluation run so the first batch isn't slow.")
        with self.assertRaises(HTTPException) as e: self.K.revise(ME, r["id"], ReviseIn())
        self.assertEqual(e.exception.status_code, 409)  # nothing to revise from yet
        self.K.outcome(ME, r["id"], OutcomeIn(result="failure", note="Cold start: the cache was empty after a restart"))
        new = self.K.revise(ME, r["id"], ReviseIn())
        self.assertIn("Cold start", self.hub.llm.prompts[-1])
        self.assertEqual((new["state"], new["data"]["revises"], new["scope"]), ("submitted", r["id"], "company"))
        self.assertEqual(new["revises"]["id"], r["id"])
        self.assertEqual(self.K.item(ME, r["id"])["state"], "verified")  # the original still stands
        self.assertEqual(self.K.item(ME, r["id"])["revision"]["id"], new["id"])
        with self.assertRaises(HTTPException): self.K.revise(ME, r["id"], ReviseIn())  # one open revision at a time
        view = self.K.company_view(ME)
        self.assertEqual(next(q for q in view["queue"] if q["id"] == new["id"])["revises"], r["id"])
        self.K.decide(ME, new["id"], DecideIn(decision="approve", hash=new["hash"]))
        old = self.K.item(ME, r["id"])
        self.assertEqual(old["state"], "superseded")
        self.assertTrue(any(ln["rel"] == "supersedes" and ln.get("back") for ln in old["links"]))
        self.assertNotIn(f"kb:{r['id']}", [h["ref"] for h in self.search("assistant", "embedding cache evaluation")["results"]])


if __name__ == "__main__":
    unittest.main()
