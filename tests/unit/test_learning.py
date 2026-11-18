"""learning.py (Agents → Learning): the Knowledge → Intelligence → Learning loop in numbers, mission lessons scoped to their owner,
Workflow improvements and watches for administrators only, forgetting a lesson (only your own), and the agents gate."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import learning, mining, missions, workforce
from app.auth import AuthDB

ADMIN = {"id": 7, "username": "leo", "role": "admin"}
MEMBER = {"id": 8, "username": "ana", "role": "member"}


class Ov:
    def __init__(self, ok=True): self.ok = ok
    def _agents_ok(self, me): return self.ok


class WF:
    def memory_recall(self, *a, **k): return []


class LearningTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        missions.Missions(self.db, hub=None, wf=WF(), ia=None, mw=None)  # creates the mx_ tables
        q, now = self.db.q, time.time()
        self.flags = (mining.ENABLED, workforce.ENABLED)
        mining.ENABLED = workforce.ENABLED = True
        # two missions for the admin, one with an Intelligence brief; one mission for the member
        q("INSERT INTO mx_missions (id, user_id, title, status, discovery, created) VALUES (1, 7, 'Pick a subnet', 'done', ?, ?)", (json.dumps({"brief": {"summary": "x"}}), now))
        q("INSERT INTO mx_missions (id, user_id, title, status, discovery, created) VALUES (2, 7, 'Write a report', 'done', ?, ?)", (json.dumps({"lessons": []}), now))
        q("INSERT INTO mx_missions (id, user_id, title, status, created) VALUES (3, 8, 'Hers', 'done', ?)", (now,))
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, used, created) VALUES (1, 7, 1, 'worked', 'Check the leaderboard first', 'verified', 3, ?)", (now,))
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, used, created) VALUES (2, 7, 2, 'failed', 'Long tasks need the files', 'failed', 0, ?)", (now,))
        q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, used, created) VALUES (3, 8, 3, 'strategy', 'Hers only', 'verified', 1, ?)", (now,))
        # one open Competition team of the admin's, with a Workflow improvement and a kept watch
        q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER)")
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT, budget INTEGER, goal TEXT, autopilot INTEGER, paused INTEGER, updated REAL)")
        q("CREATE TABLE mb_flows (id INTEGER PRIMARY KEY, comp_id INTEGER, user_id INTEGER)")
        q("CREATE TABLE mb_agents (id INTEGER PRIMARY KEY, flow_id INTEGER, name TEXT)")
        q("""CREATE TABLE mb_improvements (id INTEGER PRIMARY KEY, flow_id INTEGER, agent_id INTEGER, trigger TEXT, root_cause TEXT, change TEXT, status TEXT,
             result TEXT, cost REAL, version INTEGER, decided_by TEXT, margin INTEGER, created REAL, updated REAL)""")
        q("""CREATE TABLE mb_watches (id INTEGER PRIMARY KEY, flow_id INTEGER, agent_id INTEGER, from_version INTEGER, to_version INTEGER, baseline INTEGER,
             status TEXT, score INTEGER, basis INTEGER, result TEXT, started REAL, ended REAL)""")
        q("INSERT INTO mh_campaigns VALUES (1, 7, 62)")
        q("INSERT INTO mw_comps VALUES (5, 1, 28, 'Ridges', 'open', 0, '', 0, 0, ?)", (now,))
        q("INSERT INTO mb_flows VALUES (9, 5, 7)")
        q("INSERT INTO mb_agents VALUES (4, 9, 'Engineer')")
        q("INSERT INTO mb_improvements VALUES (1, 9, 4, 'review', 'Skipped tests', 'Run the tests first', 'promoted', 'Better by 8', 0.4, 2, 'auto-improve', 5, ?, ?)", (now, now))
        q("INSERT INTO mb_watches VALUES (1, 9, 4, 1, 2, 60, 'kept', 70, 6, 'Kept after 6 outcomes', ?, ?)", (now, now))
        # the member's team is the member's, so Workflow rows never reach her even if she were an admin
        self.L = learning.Learning(self.db, Ov())

    def tearDown(self):
        mining.ENABLED, workforce.ENABLED = self.flags
        self.dir.cleanup()

    def test_loop_and_lessons_are_the_owners(self):
        d = self.L.view(ADMIN, fresh=True)
        self.assertEqual([x["id"] for x in d["lessons"]], [2, 1])
        self.assertEqual(d["lessons"][1]["mission"], "Pick a subnet")
        self.assertEqual(d["loop"]["knowledge"]["lessons"], 2)
        self.assertEqual(d["loop"]["learning"]["used"], 3)
        self.assertEqual(d["loop"]["intelligence"], {"briefs": 1, "missions": 2})
        self.assertEqual(d["errors"], [])
        her = self.L.view(MEMBER, fresh=True)
        self.assertEqual([x["text"] for x in her["lessons"]], ["Hers only"])

    def test_workflow_is_admin_only(self):
        d = self.L.view(ADMIN, fresh=True)
        self.assertTrue(d["sources"]["workflow"])
        self.assertEqual([(x["system"], x["who"], x["where"]) for x in d["improvements"]], [("teams", "Engineer", "SN62 · Ridges")])
        self.assertEqual(d["loop"]["learning"]["adopted"], 1)
        self.assertEqual(d["loop"]["learning"]["kept"], 1)
        self.assertEqual(d["watches"][0]["go"], {"view": "teams", "wid": 5, "sub": "flow"})
        self.db.q("UPDATE mh_campaigns SET user_id=8")  # the same team, owned by a member: still not shown
        m = self.L.view(MEMBER, fresh=True)
        self.assertFalse(m["sources"]["workflow"])
        self.assertEqual(m["improvements"], [])
        self.assertEqual(m["watches"], [])

    def test_forget_only_your_own(self):
        self.L.view(ADMIN)  # cached
        with self.assertRaises(HTTPException) as e: self.L.forget(ADMIN, 3)
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE id=3", one=True)["n"], 1)
        self.assertEqual(self.L.forget(ADMIN, 1), {"ok": True})
        self.assertEqual([x["id"] for x in self.L.view(ADMIN)["lessons"]], [2])  # the cache was dropped

    def test_agents_gate(self):
        with self.assertRaises(HTTPException) as e: learning.Learning(self.db, Ov(ok=False)).view(MEMBER)
        self.assertEqual(e.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
