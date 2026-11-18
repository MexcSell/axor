"""Competition teams, release discipline (mining_release.py), from the 2026-11-10 operations review:

- Duplicates: the same objective + candidate + acceptance is one deliverable; another candidate hash or other acceptance
  criteria is not. A merge keeps the copy under way (else the earliest), one owner, removes only unstarted copies.
- The plan and follow-up gate in mining_work leaves repeats off the board.
- The manifest: freezing hashes the file, a later edit shows as drift, open tasks naming another hash are conflicts.
- Benchmarks: only the frozen candidate on the frozen suite (name, size, repeats, task set) is comparable; a 42-task run is
  kept but never set against a 29-task reference.
- A task the check leaves out is recorded; adding it back puts it on the board as asked, and that title is never held back
  over that task again (the check compares words, so a person can overrule it).
"""
import hashlib, os, tempfile, time, unittest

from fastapi import HTTPException

from app import mining_release as R
from app.auth import AuthDB

WID = 7


class Same(unittest.TestCase):
    def t(self, title, detail=""): return {"title": title, "detail": detail}

    def test_rewordings_of_one_deliverable(self):
        self.assertTrue(R.same(self.t("Archive frozen candidate abc1234 to releases/"), self.t("Archive candidate abc1234def with manifest")))
        self.assertTrue(R.same(self.t("Run a three-repeat benchmark"), self.t("Three repeat benchmark run")))
        self.assertTrue(R.same(self.t("Strict audit of agent.py"), self.t("Strict audit: agent.py")))

    def test_other_candidate_or_criteria_is_another_deliverable(self):
        self.assertFalse(R.same(self.t("Archive candidate abc1234"), self.t("Archive candidate 9f8e7d6")))
        self.assertFalse(R.same(self.t("Benchmark agent.py", "Acceptance: 29 tasks solved at least 20"),
                                self.t("Benchmark agent.py", "Acceptance: latency under two seconds per request")))
        self.assertFalse(R.same(self.t("Write the README"), self.t("Benchmark the miner")))

    def test_words_and_hashes(self):
        self.assertEqual(R.hashes("candidate ABC1234def0 vs abc1234"), {"abc1234"})
        self.assertNotIn("abc1234", R.words("Audit abc1234ff #12"))
        self.assertIn("3", R.words("three-repeat"))
        self.assertEqual(R.hashes("deadline 2026 and decade"), set())  # plain words are not hashes


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = db = AuthDB(os.path.join(self.tmp.name, "t.db"))
        db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, agent_id INTEGER,
                priority TEXT, due TEXT, origin TEXT, created REAL, updated REAL, mission TEXT)""")
        db.q("CREATE TABLE mw_files (id INTEGER PRIMARY KEY, comp_id INTEGER, path TEXT, content TEXT)")
        db.q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, name TEXT)")
        db.q("INSERT INTO mw_agents (id, name) VALUES (1, 'Gus'), (2, 'Devon')")
        self.events = []
        import threading
        work = type("W", (), {})()
        work.db, work.lock = db, threading.Lock()
        work._own = lambda me, wid: ({"id": wid}, {"id": 1})
        work._agents = lambda wid: [{"id": 1, "name": "Gus"}, {"id": 2, "name": "Devon"}]
        work._event = lambda wid, kind, text, **k: self.events.append(text)
        self.rel, self.me = R.Release(work), {"id": 1, "username": "leo"}

    def tearDown(self): self.tmp.cleanup()

    def task(self, title, status="todo", agent=None, detail=""):
        self.db.q("INSERT INTO mw_tasks (comp_id, title, detail, status, agent_id) VALUES (?,?,?,?,?)", (WID, title, detail, status, agent))
        return self.db.q("SELECT MAX(id) i FROM mw_tasks", one=True)["i"]


class Dedupe(Base):
    def test_merge_keeps_the_one_under_way_and_one_owner(self):
        a = self.task("Strict audit of agent.py")
        b = self.task("Strict audit: agent.py", status="working", agent=2)
        c = self.task("Strict audit agent.py", agent=1)
        self.task("Write the README")
        self.assertEqual(R.dup_of(self.db, WID, "Strict audit for agent.py")["id"], a)
        out = self.rel.dedupe(self.me, WID, R.DedupeIn())
        self.assertEqual(out["merged"], 2)
        self.assertEqual(out["kept"], [b])
        left = {t["id"]: t for t in self.db.q("SELECT * FROM mw_tasks")}
        self.assertEqual(set(left), {b, 4})
        self.assertEqual(left[b]["agent_id"], 2)
        self.assertIn(f"#{a}", left[b]["detail"]); self.assertIn(f"#{c} (Gus)", left[b]["detail"])

    def test_copies_under_way_are_never_removed(self):
        self.task("Archive candidate abc1234", status="working", agent=1)
        self.task("Archive candidate abc1234", status="review", agent=2)
        out = self.rel.dedupe(self.me, WID, R.DedupeIn())
        self.assertEqual(out["merged"], 0)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_tasks", one=True)["n"], 2)
        self.assertEqual(out["dupes"][0]["under_way"], 1)

    def test_done_tasks_do_not_block_new_work(self):
        self.task("Three-repeat benchmark", status="done")
        self.assertIsNone(R.dup_of(self.db, WID, "Run the three-repeat benchmark"))


class LeftOut(Base):
    def test_left_out_then_added_back_and_never_held_again(self):
        keep = self.task("Strict audit of agent.py", status="working", agent=2)
        title = "Strict audit for agent.py"
        d = R.dup_of(self.db, WID, title)
        self.assertEqual(d["id"], keep)
        R.keep_off(self.db, WID, title, "Acceptance: every import checked", d, "plan:5", agent_id=1, priority="high", by="Gus")
        v = self.rel.view(self.me, WID)
        self.assertEqual([(x["title"], x["origin"], x["by"], x["dup"]["id"]) for x in v["skipped"]], [(title, "plan", "Gus", keep)])
        out = self.rel.restore(self.me, WID, v["skipped"][0]["id"])
        t = self.db.q("SELECT * FROM mw_tasks WHERE id=?", (out["task"],), one=True)
        self.assertEqual((t["title"], t["status"], t["priority"], t["agent_id"], t["origin"]), (title, "todo", "high", 1, "restored:1"))
        self.assertEqual(out["skipped"], [])
        self.assertEqual(R.dup_of(self.db, WID, title)["id"], out["task"])  # asked again, it repeats the copy just added back
        self.db.q("UPDATE mw_tasks SET status='done' WHERE id=?", (out["task"],))
        self.assertIsNone(R.dup_of(self.db, WID, title))  # but never #keep: a person said it isn't a repeat of that one...
        self.assertEqual(R.dup_of(self.db, WID, "Strict audit: agent.py")["id"], keep)  # ...other rewordings still are
        with self.assertRaises(HTTPException): self.rel.restore(self.me, WID, v["skipped"][0]["id"])  # once
        self.assertIn("added back", self.events[-1])

    def test_old_ones_drop_off_the_list(self):
        keep = self.task("Run the three-repeat benchmark")
        R.keep_off(self.db, WID, "Three repeat benchmark run", "", {"id": keep}, "agent:1:4")
        self.db.q("UPDATE mw_skipped SET ts=?", (time.time() - (R.SKIP_DAYS + 1) * 86400,))
        self.assertEqual(self.rel.skipped(WID), [])


class Scale(Base):
    def test_a_full_board_groups_quickly(self):
        import time as _t
        for i in range(400):
            self.task(f"Investigate leaderboard shift number {i} for subnet {i * 7}", detail="Acceptance: a note with sources\n- cites the page")
        rows = self.db.q("SELECT id, title, detail, status, agent_id FROM mw_tasks")
        t0 = _t.time(); R.groups(rows)
        self.assertLess(_t.time() - t0, 2.0)  # features once per task, not per pair


class Promote(unittest.TestCase):
    def test_shared_lessons_go_to_review_once_with_provenance(self):
        from app import mining_knowledge
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        db = AuthDB(os.path.join(tmp.name, "k.db"))
        db.q("CREATE TABLE mw_notes (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, reviewer TEXT, ts REAL)")
        db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT)")
        db.q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, user_id INTEGER, netuid INTEGER)")
        db.q("INSERT INTO mh_campaigns VALUES (1, 4, 62)"); db.q("INSERT INTO mw_comps VALUES (3, 1, 28, 'SQL', 'active')")
        made = []
        kb = type("KB", (), {"add_record": lambda self_, me, b: made.append(b) or {"id": 100 + len(made)}})()
        work = type("W", (), {})(); work.db, work.kb = db, kb
        k = mining_knowledge.Knowledge(work)
        for i, (scope, lesson) in enumerate((("subnet_shared", "Cache the parse. It halves the time."), ("private", "Secret"), ("global_approved", "Pin the seed."), ("restricted", "Task 7 answer")), 1):
            db.q("INSERT INTO mw_notes VALUES (?, 3, ?, 'Vera', 0)", (i, f"Note {i}"))
            db.q("INSERT INTO mk_items (note_id, comp_id, user_id, netuid, scope, lesson) VALUES (?, 3, 4, 62, ?, ?)", (i, scope, lesson))
        me = {"id": 4, "username": "leo"}
        out = k.promote(me)
        self.assertEqual((out["sent"], out["left"]), (2, 0))
        self.assertEqual([b.title for b in made], ["Pin the seed.", "Cache the parse."])  # globally approved first; private/restricted never
        self.assertIn("notebook entry 1", made[1].source_ref); self.assertIn("reviewed by Vera", made[1].evidence)
        self.assertEqual(k.promote(me)["sent"], 0)  # each lesson goes once


class Manifest(Base):
    def freeze(self, **k):
        b = {"path": "agent.py", "suite": "ridges-polyglot", "tasks": 29, "repeats": 3, "reference_score": 62.0, **k}
        return self.rel.freeze(self.me, WID, R.FreezeIn(**b))

    def test_freeze_drift_and_conflicts(self):
        self.db.q("INSERT INTO mw_files (comp_id, path, content) VALUES (?,?,?)", (WID, "agent.py", "print(1)"))
        v = self.freeze()
        sha = hashlib.sha256(b"print(1)").hexdigest()
        self.assertEqual(v["manifest"]["sha256"], sha)
        self.assertFalse(v["manifest"]["drift"])
        self.task(f"Audit candidate {sha[:10]}")
        self.task("Audit candidate 9f8e7d6c")
        v = self.rel.view(self.me, WID)
        self.assertEqual([c["names"] for c in v["conflicts"]], [["9f8e7d6"]])
        self.db.q("UPDATE mw_files SET content='print(2)'")
        self.assertTrue(self.rel.view(self.me, WID)["manifest"]["drift"])
        self.assertIn("CHANGED", self.rel.lines({"id": WID}))
        v2 = self.freeze()
        self.assertEqual(v2["manifest"]["version"], 2); self.assertEqual(len(v2["history"]), 1)

    def test_missing_file_or_candidate_is_refused(self):
        with self.assertRaises(HTTPException): self.freeze(path="nope.py")
        with self.assertRaises(HTTPException): self.freeze(path="")
        self.assertEqual(self.freeze(path="", commit="ABCDEF1234")["manifest"]["candidate"], "abcdef1234")

    def test_only_the_frozen_suite_is_comparable(self):
        self.freeze(path="", commit="abcdef1234567")
        r = self.rel.current(WID)
        ok = self.rel.record(WID, r, {"candidate": "abcdef1", "suite": "Ridges-Polyglot", "tasks": 29, "repeats": 3, "score": 65.5})
        self.assertTrue(ok["comparable"]); self.assertAlmostEqual(ok["delta"], 3.5)
        big = self.rel.record(WID, r, {"candidate": "abcdef1234567", "suite": "ridges-polyglot", "tasks": 42, "repeats": 3, "score": 70})
        self.assertFalse(big["comparable"]); self.assertIn("42 tasks against the suite's 29", big["why"][0]); self.assertIsNone(big["delta"])
        other = self.rel.record(WID, r, {"candidate": "1234abcd", "suite": "ridges-polyglot", "tasks": 29, "repeats": 3, "score": 80})
        self.assertFalse(other["comparable"])
        none = self.rel.record(WID, r, {"candidate": "", "suite": "ridges-polyglot", "tasks": 29, "repeats": 1, "score": 50})
        self.assertEqual(len(none["why"]), 2)
        res = self.rel.results(WID)
        self.assertEqual((res["comparable"], res["other"]), (1, 3))

    def test_task_ids_settle_the_task_set(self):
        self.rel.freeze(self.me, WID, R.FreezeIn(commit="abcdef1234", suite="s", tasks=3, task_ids=["a", "b", "c"], repeats=1))
        r = self.rel.current(WID)
        same = self.rel.record(WID, r, {"candidate": "abcdef1234", "suite": "s", "tasks": 3, "task_ids": ["c", "b", "a"], "repeats": 1, "score": 1})
        swap = self.rel.record(WID, r, {"candidate": "abcdef1234", "suite": "s", "tasks": 3, "task_ids": ["a", "b", "d"], "repeats": 1, "score": 1})
        self.assertTrue(same["comparable"]); self.assertFalse(swap["comparable"])

    def test_no_manifest_records_but_never_compares(self):
        out = self.rel.record(WID, None, {"candidate": "abcdef1", "suite": "s", "tasks": 1, "repeats": 1, "score": 1})
        self.assertFalse(out["comparable"]); self.assertIn("no release manifest", out["why"][0])
        self.assertIn("no release candidate is frozen", self.rel.lines({"id": WID}))


if __name__ == "__main__":
    unittest.main()
