"""Fixes from the 2026-11-10 operations review of AXoR (besides mining_release.py, tested on its own):

- restart_recovery: a run a restart cut off is followed to what became of its work: ran again or done (recovered), back on an
  autopilot board (waiting, Autoloop) or on a board nobody runs (yours); Control Hub tasks by mode; missions by status.
- command._tidy: a request asked twice shows once, listing the copy; a request waiting over STALE_H hours is stale; imports can
  be archived.
- agent_core.policy: no limit and no decision is "unset"; running without a cap is a decision on record; a scoped token limit
  or a daily cap is a boundary; coverage counts priced and unpriced tokens.
"""
import os, tempfile, time, unittest

from app import agent_core, command, restart_recovery as rr
from app.auth import AuthDB


class Restart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        db.q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, task_id INTEGER, comp_id INTEGER, kind TEXT, status TEXT)")
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, status TEXT, hold TEXT, agent_id INTEGER)")
        db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, autopilot INTEGER, paused INTEGER, status TEXT)")
        db.q("CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY, status TEXT)")
        db.q("CREATE TABLE mx_missions (id INTEGER PRIMARY KEY, status TEXT)")
        db.q("CREATE TABLE ac_runs (id INTEGER PRIMARY KEY, ref TEXT, status TEXT)")
        db.q("INSERT INTO mw_comps VALUES (1, 1, 0, 'active'), (2, 0, 0, 'active')")

    def tearDown(self): self.tmp.cleanup()

    def run_(self, rid, ref, status="failed", error="Stopped by a server restart."):
        return {"id": rid, "ref": ref, "status": status, "error": error}

    def test_team_runs(self):
        q = self.db.q
        q("INSERT INTO mw_tasks VALUES (10, 'todo', NULL, 3), (11, 'todo', NULL, 3), (12, 'done', NULL, 3), (13, 'todo', NULL, 3)")
        q("INSERT INTO mw_runs VALUES (100, 10, 1, 'task', 'failed'), (101, 11, 2, 'task', 'failed'), (102, 12, 1, 'task', 'failed'), (103, 13, 1, 'task', 'failed'), (104, 13, 1, 'task', 'running')")
        self.assertEqual(rr.follow(self.db, self.run_(1, "mw:100"))["state"], "waiting")      # autopilot on: Autoloop restarts it
        mine = rr.follow(self.db, self.run_(2, "mw:101"))
        self.assertEqual((mine["state"], mine["owner"]), ("yours", "you")); self.assertIn("autopilot is off", mine["detail"])
        self.assertEqual(rr.follow(self.db, self.run_(3, "mw:102"))["state"], "recovered")    # done since
        self.assertIn("ran again", rr.follow(self.db, self.run_(4, "mw:103"))["detail"])     # a later run

    def test_control_tasks_missions_and_summary(self):
        q = self.db.q
        q("INSERT INTO ctl_tasks VALUES (5, 'todo'), (6, 'done')")
        q("INSERT INTO mx_missions VALUES (7, 'paused'), (8, 'running')")
        self.assertEqual(rr.follow(self.db, self.run_(1, "ctl:t5"), "hybrid")["owner"], "Dispatcher")
        self.assertEqual(rr.follow(self.db, self.run_(1, "ctl:t5"), "manual")["state"], "yours")
        self.assertEqual(rr.follow(self.db, self.run_(1, "ctl:t6"))["state"], "recovered")
        self.assertEqual(rr.follow(self.db, self.run_(1, "mx:7"))["state"], "yours")
        self.assertEqual(rr.follow(self.db, self.run_(1, "mx:8"))["state"], "recovered")
        s = rr.summary(self.db, [self.run_(1, "ctl:t6"), self.run_(2, "mx:7"), self.run_(3, "ctl:t5", error="model said no")], "hybrid")
        self.assertEqual((s["interrupted"], s["recovered"], s["yours"]), (2, 1, 1))  # the third isn't a restart

    def test_other_systems_by_ref(self):
        self.db.q("INSERT INTO ac_runs VALUES (1, 'wf:9', 'failed'), (2, 'wf:9', 'done')")
        self.assertEqual(rr.follow(self.db, self.run_(1, "wf:9"))["state"], "recovered")
        self.assertEqual(rr.follow(self.db, self.run_(2, "wf:10"))["state"], "yours")


class Approvals(unittest.TestCase):
    def test_every_source_reader_is_still_a_method(self):  # the archive model once closed the class early
        for name in ("_mining", "_company", "_workforce", "_missions", "_item", "_done", "_tidy", "archive"):
            self.assertTrue(callable(getattr(command.Command, name, None)), name)

    def item(self, i, title, ts, source="mining", kind="import"):
        return {"source": source, "id": i, "kind": kind, "level": "info", "title": title, "detail": "", "where": "", "go": {}, "label": "", "ts": ts,
                "risk": None, "expires": None}

    def test_repeats_fold_and_stale_is_flagged(self):
        now = time.time()
        P = [self.item(1, "Imported competition: Test Generation", now - 164 * 3600), self.item(2, "Update from a source: Test Generation", now - 3600),
             self.item(3, "Imported competition: SQL", now - 7200), self.item(4, "Activate Test Generation v2", now, source="market", kind="approve")]
        out, folded = command.Command._tidy(P, now)
        self.assertEqual(folded, 1)
        self.assertEqual([p["id"] for p in out], [2, 3, 4])
        tg = out[0]
        self.assertEqual(tg["copies"][0]["id"], 1); self.assertTrue(tg["stale"])  # the folded copy was stale
        self.assertGreaterEqual(tg["age_h"], 164)  # waiting since the first ask
        self.assertTrue(tg["archive"]); self.assertFalse(out[2]["archive"])
        self.assertFalse(out[1]["stale"])


class Policy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.tmp.name, "a.db"))
        self.core = agent_core.Core(self.db)

    def tearDown(self): self.tmp.cleanup()

    def test_states(self):
        c = self.core
        self.assertEqual(c.policy(1)["state"], "unset")
        p = c.set_unlimited(1, True, "leo")
        self.assertEqual((p["state"], p["unlimited_by"]), ("unlimited", "leo")); self.assertIsNone(p["cap"])
        c.set_limit(1, "team", "comp:3", tokens=1000, period="day")
        self.assertEqual(c.policy(1)["state"], "scoped")
        c.set_cap(1, 50_000, "leo")
        self.assertEqual(c.policy(1)["state"], "capped")
        c.set_cap(1, None, "leo")
        self.assertEqual(c.policy(1)["state"], "scoped")  # the acknowledgement and the limits stay what they were
        self.assertEqual(c.set_unlimited(2, False, "leo")["state"], "unset")

    def test_coverage(self):
        now = time.time()
        for tok, cost, model in ((1000, 0.5, "x:a"), (3000, None, "x:b"), (1000, None, None), (0, None, None)):
            self.db.q("INSERT INTO ac_runs (system, owner_id, kind, status, tokens, cost, model, started) VALUES ('teams', 1, 'task', 'done', ?, ?, ?, ?)",
                      (tok, cost, model, now - 60))
        cv = self.core.coverage(1, now - 3600)
        self.assertEqual((cv["tokens"], cv["recorded_cost"], cv["priced_by_model"], cv["unpriced"], cv["runs_without_tokens"]), (5000, 1000, 3000, 1000, 1))
        self.assertEqual(cv["priced_pct"], 80.0)


if __name__ == "__main__":
    unittest.main()
