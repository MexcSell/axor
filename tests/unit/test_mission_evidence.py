"""mission_evidence.py: competitors as sources of evidence (seven steps; a technique is adopted only on a measured improvement on
the same validation dataset) and knowledge visibility (six questions from records; searches that found nothing the searcher
may read are named with their fix)."""
import json, os, sys, time, unittest

from fastapi import HTTPException

from app import mission_evidence as mev, mission_ops as mo

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base  # noqa: E402
from test_organization import ME  # noqa: E402

NOW = time.time()
SUMMARY = {"agents": 12, "versions": 9, "code": 5, "runs": 240, "status": {"approved": 4, "didn't qualify": 6, "screening": 2},
           "leaders": [{"name": "alpha", "version": 4, "score": 0.71, "status": "approved", "solved": 30, "tried": 42, "agent_id": "a4"}],
           "jumps": [{"name": "alpha", "from": 3, "to": 4, "from_id": "a3", "to_id": "a4", "before": 0.52, "after": 0.71, "delta": 0.19, "lines_changed": 88}],
           "drops": [{"name": "beta", "from": 2, "to": 3, "from_id": "b2", "to_id": "b3", "before": 0.4, "after": 0.31, "delta": -0.09}],
           "lead_only": [{"problem": "django__django-1234", "rate": 0.17, "leaders": ["alpha v4"]}], "misses": [],
           "failures": [{"error": "no patch returned", "runs": 31, "agents": 5, "side": "agent"}, {"error": "validator timeout", "runs": 9, "agents": 3, "side": "platform"}]}


class Competitors(Base):
    def setUp(self):
        super().setUp()
        mo.ensure_schema(self.db); mev.ensure_schema(self.db)
        q = self.db.q
        q("CREATE TABLE rv_state (comp_id INTEGER PRIMARY KEY, set_id INTEGER, last_at REAL, ok INTEGER, error TEXT, read INTEGER, summary TEXT, next_at REAL)")
        q("INSERT INTO rv_state VALUES (1, 28, ?, 1, NULL, 20, ?, NULL)", (NOW, json.dumps(SUMMARY)))
        q("""CREATE TABLE mw_release (id INTEGER PRIMARY KEY, comp_id INTEGER, version INTEGER, suite TEXT, suite_tasks INTEGER, suite_hash TEXT, reference_score REAL, current INTEGER)""")
        q("""CREATE TABLE mw_bench (id INTEGER PRIMARY KEY, comp_id INTEGER, release_id INTEGER, task_id INTEGER, suite TEXT, suite_hash TEXT, score REAL, comparable INTEGER, ts REAL)""")
        q("INSERT INTO mw_release VALUES (1, 1, 3, 'polyglot-40', 40, 'h1', 0.5, 1)")

    def view(self): return mev.competitors(self.ch, ME, "comp:1")
    def add(self): return mev.add_technique(self.ch, ME, "comp:1", mev.TechniqueIn(title="alpha: v3 to v4", observation="Score 0.52 → 0.71", source="jump", source_ref="jump:a3:a4",
                                                                                    hypothesis="Their retry on an empty patch recovers runs we lose the same way."))

    def test_the_harvest_gives_the_first_three_steps_and_names_the_next(self):
        v = self.view()
        self.assertEqual([s["key"] for s in v["steps"]], ["discover", "collect", "identify", "hypothesis", "reproduce", "evaluate", "adopt"])
        self.assertEqual([s["state"] for s in v["steps"]], ["done", "done", "done", "next", "todo", "todo", "todo"])
        self.assertEqual(v["next"]["step"], "Form hypotheses")
        kinds = {o["source"] for o in v["observed"]}
        self.assertEqual(kinds, {"jump", "lead_only", "failure", "drop"})  # leaders and unsuccessful competitors alike; platform errors aren't techniques
        self.assertIn("didn't qualify", v["steps"][0]["detail"])

    def test_a_competition_without_a_harvest_starts_at_discover_and_takes_a_technique_by_hand(self):
        v = mev.competitors(self.ch, ME, "comp:4")
        self.assertEqual((v["harvested"], v["steps"][0]["state"]), (False, "next"))
        v = mev.add_technique(self.ch, ME, "comp:4", mev.TechniqueIn(title="Batch the requests", hypothesis="The leader answers in one round trip; ours takes three."))
        self.assertEqual(v["counts"]["hypothesis"], 1)
        with self.assertRaises(HTTPException): mev.competitors(self.ch, ME, "comp:3")  # another user's team

    def test_reproduction_goes_to_the_teams_board_as_its_own_candidate(self):
        t = self.add()["techniques"][0]
        with self.assertRaises(HTTPException): self.add()  # one hypothesis per observation
        v = mev.reproduce(self.ch, ME, "comp:1", t["id"])
        t = v["techniques"][0]
        self.assertEqual((t["status"], t["task"]["status"]), ("reproducing", "todo"))
        self.assertTrue(t["task"]["title"].startswith("Reproduce and measure"))
        self.assertTrue(next(o for o in v["observed"] if o["ref"] == "jump:a3:a4")["taken"])
        with self.assertRaises(HTTPException): mev.reproduce(self.ch, ME, "comp:1", t["id"])

    def test_adoption_needs_a_better_result_on_the_same_dataset(self):
        t = mev.reproduce(self.ch, ME, "comp:1", self.add()["techniques"][0]["id"])["techniques"][0]
        adopt = lambda: mev.decide(self.ch, ME, "comp:1", t["id"], mev.DecideIn(decision="adopt"))
        with self.assertRaises(HTTPException) as e: adopt()
        self.assertIn("Not measured", e.exception.detail)
        q = self.db.q
        q("INSERT INTO mw_bench (comp_id, release_id, task_id, suite, suite_hash, score, comparable, ts) VALUES (1, 1, ?, 'other', 'h2', 0.9, 0, ?)", (t["task"]["id"], NOW))
        v = self.view()["techniques"][0]
        self.assertIsNone(v["candidate"]); self.assertIn("another suite", v["why_not"])  # 0.9 on another dataset proves nothing here
        with self.assertRaises(HTTPException): adopt()
        q("INSERT INTO mw_bench (comp_id, release_id, task_id, suite, suite_hash, score, comparable, ts) VALUES (1, 1, ?, 'polyglot-40', 'h1', 0.45, 0, ?)", (t["task"]["id"], NOW))
        v = self.view()["techniques"][0]
        self.assertEqual((v["status"], v["baseline"], v["candidate"], v["can_adopt"]), ("evaluated", 0.5, 0.45, False))
        with self.assertRaises(HTTPException) as e: adopt()
        self.assertIn("no measured improvement", e.exception.detail)
        q("INSERT INTO mw_bench (comp_id, release_id, task_id, suite, suite_hash, score, comparable, ts) VALUES (1, 1, ?, 'polyglot-40', 'h1', 0.58, 0, ?)", (t["task"]["id"], NOW))
        self.assertTrue(self.view()["techniques"][0]["can_adopt"])
        mo._cache.clear()
        queue = mo.view(self.ch, ME, fresh=True)["queue"]
        self.assertTrue(any(x.get("action") == "competitors" and "beat the baseline" in x["detail"] for x in queue))
        v = adopt()
        d = v["techniques"][0]
        self.assertEqual((d["status"], d["baseline"], d["candidate"], d["decided_by"]), ("adopted", 0.5, 0.58, ME["username"]))
        self.assertEqual([s["state"] for s in v["steps"]], ["done"] * 7)
        with self.assertRaises(HTTPException): adopt()

    def test_reject_is_always_possible(self):
        t = self.add()["techniques"][0]
        v = mev.decide(self.ch, ME, "comp:1", t["id"], mev.DecideIn(decision="reject", note="Needs their private eval set"))
        self.assertEqual((v["techniques"][0]["status"], v["counts"]["rejected"]), ("rejected", 1))


class Knowledge(Base):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("CREATE TABLE kb_items (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, reach TEXT, version INTEGER)")
        q("CREATE TABLE kb_chunks (id INTEGER PRIMARY KEY, item_id INTEGER, user_id INTEGER, ver INTEGER)")
        q("CREATE TABLE kb_grants (id INTEGER PRIMARY KEY, user_id INTEGER, scope TEXT, actor TEXT, by_user TEXT, created REAL)")
        q("""CREATE TABLE kb_queries (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts REAL, actor TEXT, label TEXT, candidates INTEGER, results INTEGER, cited TEXT)""")
        q("CREATE TABLE ex_recalls (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ts REAL, found INTEGER)")
        q("CREATE TABLE ex_uses (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ref TEXT, context TEXT, outcome TEXT, ts REAL)")
        for i, (reach, chunked) in enumerate([("page", 1), ("page", 1), ("agents", 1), ("page", 0)], 1):
            q("INSERT INTO kb_items VALUES (?, 7, 'kept', ?, 2)", (i, reach))
            if chunked: q("INSERT INTO kb_chunks (item_id, user_id, ver) VALUES (?, 7, 2)", (i,))
        q("INSERT INTO kb_chunks (item_id, user_id, ver) VALUES (4, 7, 1)")  # an old version's passage: not searchable now
        for actor, label, cand, res, cited in [("teams:1", "SN62 · team", 0, 0, None)] * 7 + [("hub:3", "Scout", 5, 2, '["kb:3"]'), ("hub:3", "Scout", 4, 0, None), ("you", "you", 6, 3, "[]")]:
            q("INSERT INTO kb_queries (user_id, ts, actor, label, candidates, results, cited) VALUES (7, ?, ?, ?, ?, ?, ?)", (NOW - 60, actor, label, cand, res, cited))
        q("INSERT INTO ex_recalls (user_id, ts, found) VALUES (7, ?, 2), (7, ?, 0)", (NOW, NOW))
        for o in ("success", "success", "failure", None): q("INSERT INTO ex_uses (user_id, ref, context, outcome, ts) VALUES (7, 'mk:1', 'mw:1', ?, ?)", (o, NOW))

    def test_six_questions_each_from_records(self):
        k = mev.knowledge(self.ch, ME)
        self.assertEqual([x["key"] for x in k["questions"]], ["sources", "indexed", "access", "retrieved", "used", "outcome"])
        self.assertEqual((k["index"]["records"], k["index"]["indexed"], k["index"]["passages"]), (4, 3, 3))
        self.assertEqual(k["retrieval"], {"searches": 10, "found": 2, "empty_scope": 7, "no_match": 1, "cited": 1})
        self.assertEqual((k["recalls"]["used"], k["recalls"]["success"], k["recalls"]["failure"], k["recalls"]["open"]), (4, 2, 1, 1))
        st = {x["key"]: x["state"] for x in k["questions"]}
        self.assertEqual((st["indexed"], st["access"], st["retrieved"], st["used"], st["outcome"]), ("warn", "warn", "warn", "ok", "ok"))

    def test_a_search_that_may_read_nothing_is_named_with_its_fix(self):
        k = mev.knowledge(self.ch, ME)
        team = k["actors"][0]
        self.assertEqual((team["actor"], team["searches"], team["empty_scope"]), ("teams:1", 7, 7))
        self.assertIn("shared with teams", team["fix"])
        self.assertIn("No record is shared with competition teams", k["access"]["note"])
        self.assertEqual(next(a for a in k["actors"] if a["actor"] == "hub:3")["fix"], "")
        self.db.q("UPDATE kb_items SET reach='teams' WHERE id=3")
        self.assertEqual(mev.knowledge(self.ch, ME)["access"]["note"], "")

    def test_the_console_carries_it(self):
        mo.ensure_schema(self.db); mo._cache.clear()
        v = mo.view(self.ch, ME, fresh=True)
        self.assertEqual(v["knowledge"]["retrieval"]["searches"], 10)


if __name__ == "__main__":
    unittest.main()
