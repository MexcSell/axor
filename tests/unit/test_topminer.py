"""mining_topminer.py after the 11-07 evaluation: M0 contract → M1 reliability → M2 validation infrastructure → M3 quality, with
the stored keys unchanged; a set that is all held out is not ready; pasted names lose their list punctuation; the official
results are only what the evaluator reported."""
import json, os, tempfile, time, unittest

from fastapi import HTTPException

from app import mining_topminer as tm
from app.auth import AuthDB

ME = {"id": 7, "username": "thomas"}


class FakeWork:
    def __init__(self, db):
        self.db, self.events = db, []
        db.q("""CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT, goal TEXT,
                notes TEXT, link TEXT)""")
        db.q("""CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT, squad TEXT, lead INTEGER,
                active INTEGER)""")
        db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, status TEXT,
                priority TEXT, agent_id INTEGER, due TEXT, origin TEXT, summary TEXT, created REAL, updated REAL, done_at REAL)""")
        db.q("""CREATE TABLE mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, tokens INTEGER)""")
        db.q("INSERT INTO mw_comps VALUES (1, 1, 28, '', 'active', 'Top 1', '', 'https://ridges.ai/c/28')")
        db.q("INSERT INTO mw_agents VALUES (1, 1, 'Morgan', 'Director', 'Leads', 'command', 1, 1)")

    def _own(self, me, wid):
        w = self.db.q("SELECT * FROM mw_comps WHERE id=?", (wid,), one=True)
        if not w: raise HTTPException(404, "no")
        return w, {"id": 1, "netuid": 62}

    def _label(self, w): return f"Competition {w['number']}"
    def _agents(self, wid): return self.db.q("SELECT * FROM mw_agents WHERE comp_id=?", (wid,))
    def _event(self, wid, kind, text, **_): self.events.append(text)
    def _ins(self, sql, args):
        self.db.q(sql, args)
        return self.db.q("SELECT MAX(id) i FROM mw_tasks", one=True)["i"]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = AuthDB(os.path.join(self.dir, "auth.db"))
        self.w = FakeWork(self.db)
        self.t = tm.TopMiner(self.w)


class Names(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(tm.clean_name("ch-top-pages-pruning-001)"), "ch-top-pages-pruning-001")
        self.assertEqual(tm.clean_name("- `bc-pg-308`,"), "bc-pg-308")
        self.assertEqual(tm.clean_name("3. ch-x-001"), "ch-x-001")
        self.assertEqual(tm.clean_name("fn(a)"), "fn(a)")  # balanced: kept


class Roadmap(Base):
    def test_order_numbers_and_keys(self):
        v = self.t.view(ME, 1)
        self.assertEqual([m["num"] for m in v["roadmap"]], ["M0", "M1", "M2", "M3", "M4", "M5"])
        self.assertEqual([m["key"] for m in v["roadmap"]], ["m0", "m1", "m3", "m2", "m4", "m5"])
        self.assertEqual(v["roadmap"][2]["name"], "Validation infrastructure")
        self.assertEqual(v["roadmap"][3]["name"], "Task-solving quality")
        self.assertEqual(v["roadmap"][0]["auto"], "doing")  # the competition page is on file, never auto-done
        self.assertEqual(v["targets"]["total"], 50)
        self.assertEqual((v["targets"]["dev_per_category"], v["targets"]["held_per_category"]), (8, 2))

    def test_old_marks_keep_their_meaning(self):
        self.t.mark(ME, 1, "m3", tm.MarkIn(status="done", note="set built"))
        v = self.t.view(ME, 1)
        val = next(m for m in v["roadmap"] if m["key"] == "m3")
        self.assertEqual((val["num"], val["status"]), ("M2", "done"))
        self.t.mark(ME, 1, "m0", tm.MarkIn(status="done"))
        with self.assertRaises(HTTPException): self.t.mark(ME, 1, "m9", tm.MarkIn(status="done"))

    def test_all_held_out_is_not_ready(self):
        self.t.add(ME, 1, tm.SetIn(name="ch-top-pages-pruning-001)", split="held"))
        v = self.t.view(ME, 1)
        self.assertEqual(v["set"][0]["name"], "ch-top-pages-pruning-001")
        self.assertTrue(any(g.startswith("No development set") for g in v["gaps"]))
        val = next(m for m in v["roadmap"] if m["key"] == "m3")
        self.assertNotEqual(val["auto"], "done")
        self.assertIn("No development set", val["evidence"])

    def test_bulk_holds_out_one_in_five(self):
        names = [f"pg-gen-{i:03d}" for i in range(10)]
        v = self.t.bulk(ME, 1, tm.BulkIn(names=names))
        held = sum(1 for r in v["set"] if r["split"] == "held")
        self.assertEqual(held, 2)

    def test_migrates_saved_names(self):
        self.db.q("INSERT INTO tm_set (comp_id, name, category, engine, split, edges, note, source, created) VALUES (1, 'ch-a-001)', 'generation', 'clickhouse', 'dev', '[]', '', 'list', 0)")
        self.db.q("INSERT INTO tm_set (comp_id, name, category, engine, split, edges, note, source, created) VALUES (1, 'ch-b-001', 'generation', 'clickhouse', 'dev', '[]', '', 'list', 0)")
        self.db.q("INSERT INTO tm_set (comp_id, name, category, engine, split, edges, note, source, created) VALUES (1, 'ch-b-001)', 'generation', 'clickhouse', 'dev', '[]', '', 'list', 0)")
        tm.TopMiner(self.w)
        names = sorted(r["name"] for r in self.db.q("SELECT name FROM tm_set WHERE comp_id=1"))
        self.assertEqual(names, ["ch-a-001", "ch-b-001", "ch-b-001)"])  # the clash is left for the user


class Baseline(Base):
    def _evals(self, rows):
        self.db.q("CREATE TABLE IF NOT EXISTS mb_flows (id INTEGER PRIMARY KEY, comp_id INTEGER)")
        self.db.q("INSERT OR IGNORE INTO mb_flows VALUES (1, 1)")
        self.db.q("""CREATE TABLE IF NOT EXISTS mb_experiments (id INTEGER PRIMARY KEY, flow_id INTEGER, kind TEXT, label TEXT, head TEXT, status TEXT,
                     tasks INTEGER, solved INTEGER, runs INTEGER, passed INTEGER, cost REAL, secs REAL, per_task TEXT, finished REAL)""")
        for i, kind, ok in rows:  # ok: does the held-out task pass
            per = {"pg-a-001": {"runs": 1, "passed": 1, "cost": 0.1, "secs": 10}, "pg-a-002": {"runs": 1, "passed": int(ok), "cost": 0.1, "secs": 10}}
            self.db.q("INSERT INTO mb_experiments VALUES (?,1,?,?,'',  'done', 2, 1, 2, 1, 0.2, 20, ?, ?)", (i, kind, f"e{i}", json.dumps(per), 1000 + i))

    def test_newest_base_measurement_else_earliest(self):
        self.t.add(ME, 1, tm.SetIn(name="pg-a-001", split="dev"))
        self.t.add(ME, 1, tm.SetIn(name="pg-a-002", split="held"))
        # 12 evals: the earliest (1) fails the held-out task, a base measurement (5) fails it, the rest pass it
        self._evals([(i, "base" if i == 5 else "task", i not in (1, 5)) for i in range(1, 13)])
        q = next(m for m in self.t.view(ME, 1)["roadmap"] if m["key"] == "m2")
        self.assertIn("“e5”, the newest base measurement", q["evidence"])
        self.db.q("UPDATE mb_experiments SET kind='task' WHERE id=5")
        q = next(m for m in self.t.view(ME, 1)["roadmap"] if m["key"] == "m2")
        self.assertIn("“e1”, the earliest eval on the set", q["evidence"])  # not e3, the oldest of the newest ten
        self.assertEqual(q["auto"], "doing")  # better, but the set isn't ready
        self.t.mark(ME, 1, "m3", tm.MarkIn(status="done"))
        q = next(m for m in self.t.view(ME, 1)["roadmap"] if m["key"] == "m2")
        self.assertEqual(q["auto"], "done")  # a set marked ready by hand counts


class Official(Base):
    def test_only_reported_values(self):
        v = self.t.view(ME, 1)
        self.assertEqual(v["official"], {})  # no Command center tables: nothing invented
        self.db.q("""CREATE TABLE mc_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, comp_id INTEGER, miner_id INTEGER, ts REAL,
                     metric TEXT, value REAL, source TEXT, run TEXT, note TEXT)""")
        now = time.time()
        for m, val in (("score", 0.61), ("rank", 4), ("leader_score", 0.7)):
            self.db.q("INSERT INTO mc_metrics (comp_id, ts, metric, value, source) VALUES (1, ?, ?, ?, 'evaluator')", (now, m, val))
        o = self.t.view(ME, 1)["official"]
        self.assertAlmostEqual(o["gap"]["value"], 0.09)
        self.assertEqual(o["evaluations"], 1)
        self.assertNotIn("cost_task", o)


class Mission(Base):
    def test_contract(self):
        v = self.t.launch(ME, 1)
        c = v["mission"]["contract"]
        self.assertEqual(c["minutes"], tm.MISSION_MINUTES)
        self.assertEqual((c["attempted"], c["completed"], c["unfinished"]), (0, 0, len(tm.MISSION)))
        tid = v["mission"]["tasks"][0]["id"]
        self.db.q("UPDATE mw_tasks SET status='done' WHERE id=?", (tid,))
        self.db.q("INSERT INTO mw_runs (comp_id, task_id, tokens) VALUES (1, ?, 1200)", (tid,))
        c = self.t.view(ME, 1)["mission"]["contract"]
        self.assertEqual((c["attempted"], c["completed"], c["tokens"], c["runs"]), (1, 1, 1200, 1))


if __name__ == "__main__":
    unittest.main()
