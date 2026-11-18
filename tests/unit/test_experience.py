"""experience.py (mixed into the Knowledge Hub): experiences from every system recalled by meaning through vectors kept per ref,
words-only hits held to shared words, the owner's rows only, outcomes settled on the work that recalled them and moving the next
recall, the recall_experience tool with its context, vectors of rows that are gone dropped, and Mission Control's discovery still
filling the lists its planner reads."""
import json, os, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

from test_knowledge_rag import Base, URL  # the Knowledge Hub fixture and the fake embeddings service
from app import mission_intel, missions

ME = {"id": 7, "username": "leo", "role": "admin"}
HER = {"id": 8, "username": "ana", "role": "member"}


class WF:
    def memory_recall(self, *a, **k): return []


class Exp(Base):
    def setUp(self):
        super().setUp()
        q, now = self.db.q, time.time()
        q("INSERT INTO users (id, username, pw_hash, created) VALUES (8, 'ana', 'x', ?)", (now,))
        missions.Missions(self.db, hub=None, wf=WF(), ia=None, mw=None)  # the mx_ tables
        q("""CREATE TABLE wf_memory (id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, text TEXT, tags TEXT, team TEXT, mission_id INTEGER, source TEXT,
             status TEXT, cited INTEGER DEFAULT 0, helped INTEGER DEFAULT 0, retrieved INTEGER DEFAULT 0, last_used REAL, created REAL, updated REAL)""")
        q("CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, detail TEXT, status TEXT, summary TEXT, result TEXT, updated REAL)")
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT)")
        q("CREATE TABLE mw_notes (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, body TEXT, ts REAL)")
        q("INSERT INTO mh_campaigns VALUES (1, 7, 62)")
        q("INSERT INTO mw_comps VALUES (5, 1, 28, 'Ridges', 'open')")
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (1, 7, 1, 'worked', 'Enroll the validator before you start the miner', 'verified', ?)", (now,))
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (2, 8, 3, 'worked', 'Enroll the validator early, hers', 'verified', ?)", (now,))
        q("INSERT INTO wf_memory (id, user_id, kind, text, tags, status, created, updated) VALUES (1, 7, 'strategy', 'Slow reward reports: check emission lag first', '[]', 'active', ?, ?)", (now, now))
        q("INSERT INTO ctl_tasks VALUES (1, 7, 'Register the hotkey', 'On SN62', 'done', 'Signup worked after the second try', '', ?)", (now,))
        q("INSERT INTO mw_notes VALUES (1, 5, 'Validator timeouts', 'The checker times out after 30 s on big repos', ?)", (now,))

    def embed(self):
        os.environ["KNOWLEDGE_EMBED_URL"], os.environ["KNOWLEDGE_EMBED_MODEL"] = URL + "/v1", "fake-embed"
        self.K.exp_index(7); self.K.exp_index(8)

    def test_meaning_across_sources(self):
        self.embed()
        self.assertGreaterEqual(self.db.q("SELECT COUNT(*) n FROM ex_vecs WHERE user_id=7", one=True)["n"], 4)
        hits = self.K.recall(ME, "signup verifier", 6, "missions", "Mission Control", "mx:99")  # no word in common with the lesson
        refs = [h["ref"] for h in hits]
        self.assertIn("mxl:1", refs)
        self.assertEqual(next(h for h in hits if h["ref"] == "mxl:1")["match"], "meaning")
        self.assertIn("ctl:1", refs)          # "Register" ~ "signup"
        self.assertNotIn("mxl:2", refs)       # another user's lesson never comes back
        self.assertEqual(self.db.q("SELECT used FROM mx_lessons WHERE id=1", one=True)["used"], 1)
        r = self.db.q("SELECT * FROM ex_recalls WHERE user_id=7", one=True)
        self.assertEqual((r["actor"], r["context"], r["mode"], r["found"]), ("missions", "mx:99", "meaning", len(hits)))
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ex_uses WHERE context='mx:99'", one=True)["n"], len(hits))

    def test_knowledge_search_gets_meaning_for_memories(self):
        self.embed()
        hits = self.K.retrieve(ME, "delay incentive", 5, "page", strategy="vector")  # Workforce memory has no Knowledge Hub item vector
        self.assertIn("wfm:1", [h["ref"] for h in hits])

    def test_outcomes_settle_and_move_the_next_recall(self):
        self.embed()
        first = [h["ref"] for h in self.K.recall(ME, "validator signup", 6, "missions", "", "mx:1")]
        self.assertEqual(self.K.exp_outcome(7, "mx:1", "unverified"), 0)  # unknown: left open
        self.assertEqual(self.K.exp_outcome(7, "mx:1", "verified"), len(first))
        self.assertEqual({r["outcome"] for r in self.db.q("SELECT outcome FROM ex_uses WHERE context='mx:1'")}, {"success"})
        top, second = first[0], first[1]
        now = time.time()
        for _ in range(4):  # earlier work that used the top one failed; the second's succeeded
            self.db.q("INSERT INTO ex_uses (user_id, ref, context, outcome, ts) VALUES (7, ?, 'old', 'failure', ?)", (top, now))
            self.db.q("INSERT INTO ex_uses (user_id, ref, context, outcome, ts) VALUES (7, ?, 'old', 'success', ?)", (second, now))
        again = self.K.recall(ME, "validator signup", 6, "missions", "", "mx:2", log_it=False)
        self.assertLess([h["ref"] for h in again].index(second), [h["ref"] for h in again].index(top))
        rec = next(h for h in again if h["ref"] == second)["record"]
        self.assertEqual(rec["success"], 5)

    def test_tool_logs_under_its_context(self):
        self.embed()
        tools = self.K.agent_tools(7, "teams:5", "SN62 · Ridges", context="mw:12")
        self.assertIn("search_knowledge", tools)
        d, h = tools["recall_experience"]
        self.assertTrue(d["strict"])
        out = h({"query": "validator timeouts on big repositories"})
        self.assertIn("mwn:1", [x["ref"] for x in out["experiences"]])
        self.assertEqual(self.db.q("SELECT context FROM ex_recalls ORDER BY id DESC", one=True)["context"], "mw:12")
        self.assertIn("error", h({"query": ""}))
        self.assertEqual(self.K.agent_tools(7, "teams:5", "x")["recall_experience"][0]["name"], "recall_experience")  # without a context too

    def test_words_only_needs_shared_words(self):
        # built-in vectors (no key): a query sharing one word with a lesson doesn't recall it on words alone
        hits = self.K.recall(ME, "miner", 6, "you", "", None, log_it=False)
        self.assertTrue(all(h["match"] != "words" for h in hits))
        lines = self.K.experience_lines(7, "enroll the validator", "workforce", "Workforce", "wf:1", exclude=("wfm",))
        self.assertTrue(lines[0].startswith("Relevant experience"))
        self.assertIn("[mxl:1]", "\n".join(lines))
        self.assertNotIn("wfm:", "\n".join(lines))

    def test_gone_rows_lose_their_vectors(self):
        self.embed()
        self.db.q("DELETE FROM ctl_tasks WHERE id=1")
        self.K._exlast = 0
        self.K.exp_index(7)
        self.assertFalse(self.db.q("SELECT 1 FROM ex_vecs WHERE ref='ctl:1'"))

    def test_status(self):
        self.embed()
        self.K.recall(ME, "signup verifier", 6, "missions", "Mission Control", "mx:5")
        st = self.K.exp_status(ME)
        self.assertEqual(st["mode"], "meaning")
        self.assertEqual({s["key"]: s["count"] for s in st["sources"]}["mxl"], 1)
        self.assertEqual(st["week"]["recalls"], 1)
        self.assertEqual(st["recent"][0]["context"], "mx:5")
        self.assertTrue(st["recent"][0]["uses"])

    def test_mission_discovery_keeps_its_lists(self):
        self.embed()
        class Hub: knowledge, llm = self.K, None
        M = missions.Missions(self.db, hub=Hub(), wf=WF(), ia=None, mw=None)
        self.db.q("INSERT INTO mx_missions (id, user_id, title, goal, status, understanding, created) VALUES (40, 7, 'Validator signup', 'Do the validator signup on SN62', 'running', ?, ?)",
                  (json.dumps({"objective": "verifier enrollment"}), time.time()))
        flag, mission_intel.ENABLED = mission_intel.ENABLED, False
        try: self.assertTrue(M._discover(M._m(40)))
        finally: mission_intel.ENABLED = flag
        d = M._m(40)["discovery"]
        self.assertEqual([x["id"] for x in d["lessons"]], [1])
        self.assertEqual(d["lessons"][0]["kind"], "worked")
        self.assertIn("ctl:1", [x["ref"] for x in d["experience"]])
        self.assertEqual(self.db.q("SELECT context FROM ex_recalls ORDER BY id DESC", one=True)["context"], "mx:40")
        M._settle_experience({"id": 40, "user_id": 7}, "failed")
        self.assertEqual({r["outcome"] for r in self.db.q("SELECT outcome FROM ex_uses WHERE context='mx:40'")}, {"failure"})


if __name__ == "__main__":
    unittest.main()
