"""Task-state accounting (Owner decision 2026-11-11, D-018): Completed, Review, Verified, Cancelled and Dropped kept apart.

- Work the Director dropped is DROPPED: it is neither completed nor unverified work, and it isn't planned work either.
- Done on a person's word without a verdict is COMPLETED; delivered and waiting for a verdict is REVIEW; a verdict is VERIFIED.
- app/state_migrate.py backfills closed_as from the records: dry run by default, a journal per change, reversible."""
import io, json, os, sys, tempfile, time, types, unittest
from fastapi import HTTPException
from unittest import mock
from contextlib import redirect_stdout

from app import mining_work, mission_ops as mo, state_migrate as mig
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME, WID, Base as BoardBase  # noqa: E402


class States(unittest.TestCase):
    def test_done_is_split_by_how_it_was_closed(self):
        sb = mo.state_board
        self.assertEqual(sb({"status": "done"}, verified=True), "VERIFIED")
        self.assertEqual(sb({"status": "done"}), "COMPLETED")
        self.assertEqual(sb({"status": "done", "closed_as": "dropped"}, verified=True), "DROPPED")   # a drop is never verified work
        self.assertEqual(sb({"status": "done", "note": "Dropped by Morgan: settled in #3000"}), "DROPPED")  # rows not migrated yet
        self.assertEqual(sb({"status": "done", "note": "Done, by your answer to Morgan's report."}), "COMPLETED")
        self.assertEqual(sb({"status": "review"}), "REVIEW")
        self.assertEqual(sb({"status": "checking"}), "REVIEW")

    def test_dropped_and_cancelled_work_inflate_nothing(self):
        w = mo.work_progress(["VERIFIED", "REVIEW", "COMPLETED", "DROPPED", "DROPPED", "CANCELLED", "READY"])
        self.assertEqual((w["planned"], w["verified"], w["review"], w["completed"], w["unverified"], w["delivered"], w["dropped"]), (4, 1, 1, 1, 2, 3, 2))
        # headline: 1 of the 7 ever planned; active plan (Milestone 3): 1 of the 6 not cancelled by a person, the 2 dropped still in it
        self.assertEqual((w["original"], w["pct"], w["active"], w["pct_active"]), (7, 14, 6, 17))

    def test_the_path_stays_the_first_five_states(self):
        self.assertEqual(mo.PATH, ("PLANNED", "READY", "RUNNING", "REVIEW", "VERIFIED"))
        for s in mo.STATES: self.assertIn(s, mo.STATE_LABEL); self.assertIn(s, mo.STATE_NOTE)


class Forward(BoardBase):
    def setUp(self):
        super().setUp()
        for c in ("closed_as", "hold", "fails", "done_at", "question", "feedback", "note"):
            if c not in {x["name"] for x in self.db.q("PRAGMA table_info(mw_tasks)")}: self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {c} {'REAL' if c == 'done_at' else 'INTEGER' if c == 'fails' else 'TEXT'}")
        self.db.q("CREATE TABLE IF NOT EXISTS mw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, ts REAL, agent_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        self.w._task = lambda me, t: (self.db.q("SELECT * FROM mw_tasks WHERE id=?", (t,), one=True), self.w._comp(WID), None)
        self.w.view = lambda me, wid: {}

    def add(self, title="Write the note"):
        return self.w._add_task(ME, WID, mining_work.TaskIn(title=title))

    def closed(self, tid): return self.db.q("SELECT closed_as FROM mw_tasks WHERE id=?", (tid,), one=True)["closed_as"]

    def test_a_person_marking_done_or_reopening(self):
        tid = self.add()
        self.w.update_task(ME, tid, mining_work.TaskPatch(status="done"))
        self.assertEqual(self.closed(tid), "person")
        self.w.update_task(ME, tid, mining_work.TaskPatch(status="todo"))
        self.assertIsNone(self.closed(tid))

    def test_the_closing_helper_is_a_no_op_without_the_column(self):
        self.w._mw_cols = {"id"}
        self.w._closed(self.add(), "dropped")  # an older database: nothing written, nothing raised


class Migration(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        q = self.db.q
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, note TEXT)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, kind TEXT, status TEXT)")
        q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, kind TEXT, text TEXT)")
        rows = [(1, "done", None, "Morgan dropped “Free a slot”: settled in #3000"), (2, "done", None, "Morgan closed “Ship it”: you said yes"),
                (3, "done", None, "leonardo marked “Add the check” done"), (4, "done", None, "leo answered “Which key?”: the second"),
                (5, "done", "Dropped by Morgan: no longer needed.", None), (6, "done", None, None), (7, "done", None, "Morgan dropped “Approved one”"),
                (8, "todo", None, "Morgan dropped “Reopened”")]
        for i, st, note, ev in rows:
            q("INSERT INTO mw_tasks (id, comp_id, title, status, note) VALUES (?,?,?,?,?)", (i, 22, f"task {i}", st, note))
            if ev: q("INSERT INTO mw_events (task_id, kind, text) VALUES (?,?,?)", (i, "done", ev))
        q("INSERT INTO mw_events (task_id, kind, text) VALUES (7, 'approve', 'Morgan approved “Approved one”')")
        self.before = q("SELECT * FROM mw_tasks ORDER BY id")

    def tearDown(self): self.dir.cleanup()

    def run_tool(self, *argv):
        buf = io.StringIO()
        with mock.patch.object(mig, "open_db", lambda: self.db), redirect_stdout(buf): mig.main(list(argv))
        return buf.getvalue()

    def state(self): return {r["id"]: r.get("closed_as") for r in self.db.q("SELECT * FROM mw_tasks ORDER BY id")}

    def test_dry_run_writes_nothing(self):
        out = self.run_tool()
        self.assertIn("to classify: 5; can't classify (left NULL): 1", out)
        self.assertEqual(self.db.q("SELECT * FROM mw_tasks ORDER BY id"), self.before)
        self.assertFalse(self.db.q("SELECT 1 FROM sqlite_master WHERE name='mig_task_state'", one=True))

    def test_apply_classifies_from_the_records_and_reverse_puts_it_back(self):
        out = self.run_tool("--apply")
        self.assertEqual(self.state(), {1: "dropped", 2: "closed", 3: "person", 4: "answered", 5: "dropped", 6: None, 7: None, 8: None})
        batch = out.split("batch ")[1].split()[0]
        self.db.q("UPDATE mw_tasks SET closed_as='person' WHERE id=2")              # the app changed one since
        out = self.run_tool("--reverse", batch)
        self.assertIn("4 rows put back; 1 changed since", out)
        self.assertEqual(self.state(), {1: None, 2: "person", 3: None, 4: None, 5: None, 6: None, 7: None, 8: None})
        self.assertFalse(self.db.q("SELECT 1 FROM mig_task_state", one=True))
        for a, b in zip(self.db.q("SELECT id, comp_id, title, status, note FROM mw_tasks ORDER BY id"), self.before): self.assertEqual(a, b)  # history untouched

    def test_apply_twice_changes_nothing_the_second_time(self):
        self.run_tool("--apply")
        self.assertIn("applied: 0 rows", self.run_tool("--apply"))

    def test_schema_sql_is_printed_not_run(self):
        out = self.run_tool("--schema-sql")
        self.assertIn("DROP COLUMN closed_as", out)
        self.assertEqual(self.db.q("SELECT * FROM mw_tasks ORDER BY id"), self.before)


if __name__ == "__main__":
    unittest.main()


class ReadinessLevels(unittest.TestCase):
    """D-020: evidence levels. The rows that used to pass by design or on nothing now say so."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        has = lambda t: bool(self.db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))
        self.ch = types.SimpleNamespace(db=self.db, _has=has, _cols=lambda t: {c["name"] for c in self.db.q(f"PRAGMA table_info({t})")})

    def tearDown(self): self.dir.cleanup()

    def v(self, **kw):
        base = {"competitions": [], "_tasks": [], "accountability": None, "activity_note": {"unverified_done": 0, "verified_total": 0, "dropped": 0},
                "evolution": {"promoted": 0, "promoted_with_evidence": 0, "rollbacks": 0},
                "budget": {"scopes": [{"label": "Company", "set": False}, {"label": "Team", "set": False}], "refused_7d": 0}}
        base.update(kw)
        return mo.readiness(self.ch, ME, base, time.time())

    def rows(self, r): return {x["key"]: x for x in r["rows"]}

    def test_nothing_on_record_never_passes(self):
        r = self.v()
        x = self.rows(r)
        self.assertEqual((x["verification"]["level"], x["verification"]["state"]), ("implemented", "unknown"))  # was "pass" by design
        self.assertEqual((x["budget"]["level"], x["budget"]["state"]), ("implemented", "fail"))
        self.assertEqual((x["rollback"]["level"], x["rollback"]["state"]), ("implemented", "partial"))
        self.assertEqual(r["pass"], 0)
        self.assertEqual(r["demonstrated"], 0)

    def test_governance_with_no_deploy_is_by_design_only_and_with_approved_deploys_is_demonstrated(self):
        self.db.q("CREATE TABLE mc_deploys (id INTEGER PRIMARY KEY, user_id INTEGER, approval_id INTEGER, rollback_of INTEGER)")
        self.assertEqual(self.rows(self.v())["governance"]["level"], "implemented")
        self.db.q("INSERT INTO mc_deploys (user_id, approval_id) VALUES (?, 5)", (ME["id"],))
        self.assertEqual(self.rows(self.v())["governance"]["level"], "demonstrated")
        self.db.q("INSERT INTO mc_deploys (user_id, approval_id) VALUES (?, NULL)", (ME["id"],))
        self.assertEqual(self.rows(self.v())["governance"]["state"], "fail")

    def test_verdicts_on_record_make_verification_operational_and_drops_are_reported_apart(self):
        x = self.rows(self.v(activity_note={"unverified_done": 22, "verified_total": 40, "dropped": 210}))["verification"]
        self.assertEqual((x["level"], x["state"]), ("operational", "pass"))
        self.assertEqual((x["evidence"]["closed_without_verdict"], x["evidence"]["dropped"]), (22, 210))

    def test_idle_agents_are_not_evidence(self):
        self.db.q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, active INTEGER)")
        self.db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, agent_id INTEGER, status TEXT)")
        self.db.q("INSERT INTO mw_agents (id, comp_id, active) VALUES (1, 3, 1), (2, 3, 1)")
        comps = [{"comp_id": 3, "title": "T", "has_objective": True}]
        self.assertEqual(self.rows(self.v(competitions=comps))["agents"]["level"], "implemented")
        self.db.q("INSERT INTO mw_tasks (agent_id, status) VALUES (1, 'todo')")
        self.assertEqual(self.rows(self.v(competitions=comps))["agents"]["level"], "partial")


class StepLimit(unittest.TestCase):
    """2026-11-11 reconciliation (#13): a run that spent every step of its tool loop without filing is told apart from one that
    stopped; the recovery action is the same as before (replan), so nothing retries differently."""
    def test_classified_apart_with_the_same_action(self):
        from app import orchestrator as o
        a = o.failure("failed", "Iris finished without filing the work: it used all its 10 steps without calling submit_work.")
        b = o.failure("failed", "Iris finished without filing the work.")
        self.assertEqual((a["cls"], b["cls"]), ("step_limit", "no_deliverable"))
        self.assertEqual((a["legacy"]["fail_class"], b["legacy"]["fail_class"]), ("task", "task"))  # the board's own class is unchanged
        self.assertEqual(o.decide("failed", a and "Iris finished without filing the work: it used all its 10 steps without calling submit_work.")["action"],
                         o.decide("failed", "Iris finished without filing the work.")["action"])


class VerdictSources(unittest.TestCase):
    def test_a_persons_approval_is_told_from_an_agents_only_by_record(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        db.q("INSERT INTO mw_events (comp_id, task_id, kind, text) VALUES (22, 1, 'approve', 'leonardo approved “A”'), (22, 2, 'approve', 'Morgan approved “B”')")
        ch = types.SimpleNamespace(db=db, _has=lambda t: bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        self.assertEqual(mo.verdict_sources(ch, [22]), {1: "agent", 2: "agent"})   # text naming a user proves nothing (D-023)
        mo.ensure_schema(db)
        db.q("INSERT INTO mo_verdicts (user_id, comp_id, task_id, source, verdict, by_user_id, by_name, at) VALUES (7, 22, 1, 'approval', 'approve', 7, 'leonardo', 0)")
        self.assertEqual(mo.verdict_sources(ch, [22]), {1: "person", 2: "agent"})

    def test_only_an_approval_that_closes_the_task_verifies_it(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        for task, kind, text in [(1, "approve", "Rex approved “A”"),                                         # approved: verified
                                 (2, "revise", "Rex sent “B” back"), (2, "done", "Morgan dropped “B”"),      # a review, then dropped
                                 (3, "approve", "Rex approved “C”"), (3, "done", "Morgan dropped “C”"),      # approved, reopened, dropped
                                 (4, "done", "leo marked “D” done"), (4, "approve", "leo approved “D”")]:   # marked, then approved
            db.q("INSERT INTO mw_events (comp_id, task_id, kind, text) VALUES (22, ?, ?, ?)", (task, kind, text))
        ch = types.SimpleNamespace(db=db, _has=lambda t: True)
        self.assertEqual(mo.approved_last(ch, [22]), {1, 4})


class DirectorClosings(unittest.TestCase):
    """The Director's own settle path (mining_director._apply) writes how it closed each task."""
    def test_drop_and_close_are_recorded_and_read_as_dropped_and_completed(self):
        import threading
        from app import mining_director
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, hold TEXT, agent_id INTEGER, report_id INTEGER,
                relays INTEGER DEFAULT 0, note TEXT, done_at REAL, updated REAL, reviewer INTEGER, closed_as TEXT)""")
        db.q("INSERT INTO mw_tasks (id, comp_id, title, status, report_id) VALUES (1, 22, 'Free a slot', 'todo', 9), (2, 22, 'Ship it', 'todo', 9)")
        W = types.SimpleNamespace(db=db, lock=threading.Lock(), _by_name=lambda wid: {}, _event=lambda *a, **k: None, _note=lambda *a, **k: None,
                                  _enqueue=lambda *a, **k: None, _ins=lambda sql, args: db.q(sql + " RETURNING id", args, one=True)["id"])
        W._closed = lambda tid, how: mining_work.Work._closed(types.SimpleNamespace(db=db, _cols_mw=lambda: {"closed_as"}), tid, how)
        dr = mining_director.Director(W)
        items = [{"id": i, "status": "todo", "title": t, "relays": 0, "agent_id": None, "report_id": 9} for i, t in ((1, "Free a slot"), (2, "Ship it"))]
        dr._apply({"id": 22}, {}, {"id": 448, "name": "Morgan"}, 1, items, {9: {"id": 9, "status": "answered"}},
                  {"decisions": [{"id": 1, "action": "drop", "reply": "settled in #3000"}, {"id": 2, "action": "done", "reply": "you said yes"}]})
        rows = {r["id"]: r for r in db.q("SELECT * FROM mw_tasks")}
        self.assertEqual((rows[1]["closed_as"], rows[2]["closed_as"]), ("dropped", "closed"))
        self.assertEqual((mo.state_board(rows[1]), mo.state_board(rows[2])), ("DROPPED", "COMPLETED"))


class OneDropDefinition(unittest.TestCase):
    """not_dropped() (SQL) and closed_as() (Python) agree on every kind of row, with and without closed_as."""
    def test_sql_and_python_agree(self):
        from app import task_lifecycle as tl
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, status TEXT, note TEXT, closed_as TEXT)")
        rows = [(1, "done", None, None), (2, "done", "Dropped by Morgan: dup.", None), (3, "done", None, "dropped"),
                (4, "done", "Dropped by Morgan: dup.", "person"),            # dropped, then marked done by a person: person wins
                (5, "done", "Done, by your answer to Morgan's report.", None), (6, "done", None, "closed")]
        for r in rows: db.q("INSERT INTO mw_tasks VALUES (?,?,?,?)", r)
        sql_kept = {r["id"] for r in db.q(f"SELECT id FROM mw_tasks WHERE {tl.not_dropped(db)}")}
        py_kept = {r["id"] for r in db.q("SELECT * FROM mw_tasks") if tl.closed_as(r) != "dropped"}
        self.assertEqual(sql_kept, py_kept)
        self.assertEqual(sql_kept, {1, 4, 5, 6})


class Sampling(unittest.TestCase):
    """P3 (D-023): a person checks a reproducible sample of agent approvals; verdicts by user id; a disagreement is flagged, not
    acted on; 'demonstrated' only against the Owner's threshold."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        db = self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, summary TEXT, done_at REAL, note TEXT, closed_as TEXT, agent_id INTEGER)")
        db.q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        mo.ensure_schema(db)
        now = time.time()
        for i in range(1, 41):
            lo, hi = mo.sample_window(now)                                    # last complete ISO week: a closed window
            db.q("INSERT INTO mw_tasks VALUES (?,22,?,'done','s',?,?,?,1)", (i, f"t{i}", lo + 3600 * i, "Dropped by Morgan." if i == 40 else None, "dropped" if i == 40 else None))
            db.q("INSERT INTO mw_events (comp_id, task_id, kind, text) VALUES (22, ?, 'approve', 'Morgan approved')", (i,))
        db.q("INSERT INTO mw_tasks VALUES (99,22,'this week','done','s',?,NULL,NULL,1)", (now - 60,))  # this week: next week's sample
        db.q("INSERT INTO mw_events (comp_id, task_id, kind, text) VALUES (22, 99, 'approve', 'Morgan approved')")
        audit = []
        self.ch = types.SimpleNamespace(db=db, _comps=lambda uid: {22: {}}, _audit=lambda *a: audit.append(a),
                                        _has=lambda t: bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)),
                                        _cols=lambda t: {c["name"] for c in db.q(f"PRAGMA table_info({t})")})

    def test_the_sample_is_reproducible_sized_by_the_rate_and_skips_drops(self):
        a, _ = mo.verify_sample(self.ch, ME["id"], [22]); b, _ = mo.verify_sample(self.ch, ME["id"], [22])
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])
        self.assertEqual(len(a), 4)                                           # ceil(10% of the 39 not dropped)
        self.assertNotIn(40, [r["id"] for r in a]); self.assertNotIn(99, [r["id"] for r in a])
        self.db.setting("verify_sample_rate", v="0.5")
        self.assertEqual(len(mo.verify_sample(self.ch, ME["id"], [22])[0]), 20)   # ceil(50% of 39): no cap on the Owner's rate

    def test_verdicts_are_by_user_id_and_only_on_the_sample(self):
        chosen, _ = mo.verify_sample(self.ch, ME["id"], [22])
        out = mo.sample_verdict(self.ch, ME, chosen[0]["id"], mo.SampleVerdictIn(verdict="disagree", note="the result is wrong"))
        row = self.db.q("SELECT * FROM mo_verdicts WHERE task_id=?", (chosen[0]["id"],), one=True)
        self.assertEqual((row["by_user_id"], row["verdict"], row["source"]), (ME["id"], "disagree", "sample"))
        self.assertEqual(self.db.q("SELECT status FROM mw_tasks WHERE id=?", (chosen[0]["id"],), one=True)["status"], "done")  # not reopened
        self.assertEqual(out["summary"]["disagree_30d"], 1)
        self.assertEqual([t["verdict"] for t in out["tasks"] if t["id"] == chosen[0]["id"]], ["disagree"])  # stays in the sample, checked
        self.assertEqual(len(out["tasks"]), len(chosen))                                                     # the sample doesn't refill
        outside = next(i for i in range(1, 40) if i not in {r["id"] for r in chosen})
        with self.assertRaises(HTTPException): mo.sample_verdict(self.ch, ME, outside, mo.SampleVerdictIn(verdict="agree"))

    def test_demonstrated_needs_30_reviews_at_95_percent_in_30_days_unsure_apart(self):
        th = mo.demonstrated_threshold(self.ch)
        self.assertEqual((th["min"], th["agree"], th["days"]), (30, 95, 30))           # the Owner's parameters, 2026-11-12
        self.assertEqual(mo._sample_rate(self.ch), 0.10)
        now = time.time()
        def give(agree, disagree, unsure, age=0):
            self.db.q("DELETE FROM mo_verdicts")
            for i, v in enumerate(["agree"] * agree + ["disagree"] * disagree + ["unsure"] * unsure):
                self.db.q("INSERT INTO mo_verdicts (user_id, comp_id, task_id, source, verdict, by_user_id, by_name, at) VALUES (?,22,?,'sample',?,?,?,?)",
                          (ME["id"], 1000 + i, v, ME["id"], "leo", now - age))
            sm = mo.sample_summary(self.ch, ME["id"], [22])
            row = next(x for x in mo.readiness(self.ch, ME, {"competitions": [], "_tasks": [], "accountability": None, "evolution": {"promoted": 0, "promoted_with_evidence": 0, "rollbacks": 0},
                       "budget": {"scopes": [], "refused_7d": 0}, "activity_note": {"verified_total": 39, "sample": sm}}, now)["rows"] if x["key"] == "verification")
            return sm, row["level"]
        sm, lvl = give(29, 0, 10)
        self.assertEqual((sm["reviews_30d"], sm["unsure_30d"], sm["met"], lvl), (29, 10, False, "operational"))  # unsure is no review
        sm, lvl = give(29, 1, 0)
        # Milestone 3: the owner's threshold met is operational evidence, never "independently demonstrated" (the owner isn't independent)
        self.assertEqual((sm["agreement_pct"], sm["met"], sm["owner_threshold_met"], sm["independently_demonstrated"], lvl), (96.7, True, True, False, "operational"))
        sm, lvl = give(28, 2, 0)
        self.assertEqual((sm["agreement_pct"], sm["met"], lvl), (93.3, False, "operational"))
        sm, lvl = give(40, 0, 0, age=31 * 86400)                            # outside the rolling 30 days
        self.assertEqual((sm["reviews_30d"], lvl), (0, "operational"))
        sm, lvl = give(29, 0, 1)                                            # Milestone 2: 29 agree + 1 unsure
        self.assertEqual((sm["reviews_30d"], sm["unsure_30d"], sm["agreement_pct"], sm["met"]), (29, 1, 100.0, False))  # 29 reviews: not met
        sm, lvl = give(0, 0, 0)                                             # no review at all
        self.assertEqual((sm["reviews_30d"], sm["agreement_pct"], sm["met"], sm["independently_demonstrated"]), (0, None, False, False))
        sm, lvl = give(29, 1, 0, age=29 * 86400)                            # 29 days old: still inside the window
        self.assertTrue(sm["met"])
        sm, lvl = give(300, 0, 0)                                           # however many owner reviews: never independent
        self.assertEqual((sm["met"], sm["independently_demonstrated"], sm["independent_reviews_30d"], lvl), (True, False, 0, "operational"))

    def test_a_changed_verdict_keeps_its_history_in_the_audit(self):
        chosen, _ = mo.verify_sample(self.ch, ME["id"], [22])
        tid = chosen[0]["id"]
        audit = []
        self.ch._audit = lambda *a: audit.append(a)
        mo.sample_verdict(self.ch, ME, tid, mo.SampleVerdictIn(verdict="unsure", note="can't tell from the summary"))
        mo.sample_verdict(self.ch, ME, tid, mo.SampleVerdictIn(verdict="disagree", note="the output is wrong"))
        self.assertEqual([a[2] for a in audit], ["verify.sample.unsure", "verify.sample.disagree"])
        self.assertIn("was unsure (note: can't tell from the summary)", audit[1][4])
        self.assertIn("note: the output is wrong", audit[1][4])
        self.assertEqual(self.db.q("SELECT status FROM mw_tasks WHERE id=?", (tid,), one=True)["status"], "done")   # nothing reopened
        sm = mo.sample_summary(self.ch, ME["id"], [22])
        self.assertEqual((sm["agree_30d"], sm["disagree_30d"], sm["unsure_30d"]), (0, 1, 0))                       # the latest verdict counts once

    def test_the_three_tiers_are_reported_apart(self):
        sm = mo.sample_summary(self.ch, ME["id"], [22])
        self.assertEqual((sm["agent_approved_week"], sm["human_reviewed_30d"], sm["independently_demonstrated"]), (39, 0, False))
        chosen, _ = mo.verify_sample(self.ch, ME["id"], [22])
        mo.sample_verdict(self.ch, ME, chosen[0]["id"], mo.SampleVerdictIn(verdict="unsure"))
        sm = mo.sample_summary(self.ch, ME["id"], [22])
        self.assertEqual((sm["human_reviewed_30d"], sm["reviews_30d"], sm["unsure_30d"]), (1, 0, 1))  # reviewed, but not a decided review

    def test_reviewers_must_be_signed_in_people_who_own_the_team(self):
        chosen, _ = mo.verify_sample(self.ch, ME["id"], [22])
        tid = chosen[0]["id"]
        for nobody in (None, {}, {"id": None, "username": "x"}):          # REQUIRE_LOGIN=0 or no session: refused, never recorded
            with self.assertRaises(HTTPException) as e: mo.sample_verdict(self.ch, nobody, tid, mo.SampleVerdictIn(verdict="agree"))
            self.assertEqual(e.exception.status_code, 401)
            with self.assertRaises(HTTPException): mo.sample_view(self.ch, nobody)
        other = {"id": ME["id"] + 50, "username": "mallory"}               # a signed-in user who doesn't own team 22
        ch2 = types.SimpleNamespace(**{**vars(self.ch), "_comps": lambda uid: {22: {}} if uid == ME["id"] else {}})
        with self.assertRaises(HTTPException) as e: mo.sample_verdict(ch2, other, tid, mo.SampleVerdictIn(verdict="agree"))
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(mo.sample_view(ch2, other)["tasks"], [])
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM mo_verdicts", one=True)["n"], 0)

    def test_work_a_person_approved_is_not_sampled_for_their_review(self):
        # associated with the execution: a person who approved a task themselves can't then review that approval as independent
        chosen, _ = mo.verify_sample(self.ch, ME["id"], [22])
        mine = chosen[0]["id"]
        self.db.q("INSERT INTO mo_verdicts (user_id, comp_id, task_id, source, verdict, by_user_id, by_name, at) VALUES (?,22,?,'approval','approve',?,'leo',?)",
                  (ME["id"], mine, ME["id"], time.time()))
        again, _ = mo.verify_sample(self.ch, ME["id"], [22])
        self.assertNotIn(mine, [r["id"] for r in again])
        with self.assertRaises(HTTPException): mo.sample_verdict(self.ch, ME, mine, mo.SampleVerdictIn(verdict="agree"))


class ProgressMaths(unittest.TestCase):
    """Both progress figures on 2,000 random boards with random origins and creation times (Milestone 2 F, Milestone 3 G).
    Original scope: verified base tasks over every base task, a fixed baseline (the first plan run and what was on the board by
    its end). Active plan: verified over base and person-made additions, less what a person cancelled; dropped work stays in.
    Agent-made additions (follow-ups, later plan runs) are in neither."""
    ORIG = ["plan:1", "plan:2", "topminer", None, "you", "agent:3:9"]

    def board(self, rnd):
        n = rnd.randint(0, 40)
        st = [rnd.choice(mo.STATES) for _ in range(n)]
        og = [rnd.choice(self.ORIG) for _ in range(n)]
        cr = [float(rnd.randint(0, 100)) for _ in range(n)]
        return st, og, cr

    def test_invariants_on_random_boards(self):
        import random
        rnd = random.Random(20261112)
        for _ in range(2000):
            st, og, cr = self.board(rnd)
            p = mo.work_progress(st, og, cr)
            sc = mo.scopes(og, cr)
            base = [s for s, k in zip(st, sc) if k == "base"]
            pers = [s for s, k in zip(st, sc) if k == "person"]
            vb, vp = base.count("VERIFIED"), pers.count("VERIFIED")
            act = len(base) + len(pers) - base.count("CANCELLED") - pers.count("CANCELLED")
            self.assertEqual((p["original"], p["active"], p["verified"]), (len(base), act, st.count("VERIFIED")))
            self.assertEqual(p["pct"], round(100 * vb / len(base)) if base else None)
            self.assertEqual(p["pct_active"], round(100 * (vb + vp) / act) if act else None)
            self.assertEqual(p["delivered"], st.count("REVIEW") + st.count("COMPLETED") + st.count("VERIFIED"))   # dropped is never delivered
            # the baseline is fixed once the board has its first plan run: any task made later, by anyone, in any state, leaves the
            # original scope as it is (a board with no plan run yet has no fixed baseline: disclosed in the report)
            late = max(cr, default=0) + 1
            for o in (("agent:1:1", "plan:9", "you", "topminer") if any(str(x or "").startswith("plan:") for x in og) else ("agent:1:1",)):
                q = mo.work_progress(st + [rnd.choice(mo.STATES)], og + [o], cr + [late])
                self.assertEqual((q["original"], q["pct"]), (p["original"], p["pct"]), o)
                if o in ("agent:1:1", "plan:9"): self.assertEqual(q["pct_active"], p["pct_active"])   # agents' additions: in neither figure
            # dropping open work raises neither figure; cancelling (a person's decision) never moves the original scope
            open_ = [i for i, s in enumerate(st) if s not in ("VERIFIED", "DROPPED", "CANCELLED")]
            if open_:
                i = rnd.choice(open_)
                d = mo.work_progress(st[:i] + ["DROPPED"] + st[i + 1:], og, cr)
                self.assertEqual((d["original"], d["pct"], d["pct_active"]), (p["original"], p["pct"], p["pct_active"]))
                x = mo.work_progress(st[:i] + ["CANCELLED"] + st[i + 1:], og, cr)
                self.assertEqual((x["original"], x["pct"]), (p["original"], p["pct"]))

    def test_the_baseline_is_read_past_the_board_cap(self):
        # the console reads a capped, newest-first board: the original scope must not shrink as its oldest tasks fall out of it
        import os, tempfile, types
        from unittest import mock
        from app.auth import AuthDB
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, title TEXT, status TEXT, origin TEXT, created REAL, note TEXT, closed_as TEXT)")
        for i, (o, t) in enumerate([("plan:5", 1), ("plan:5", 2), ("you", 3)] + [("agent:1:1", 10 + k) for k in range(20)] + [("plan:9", 40), ("you", 50)], 1):
            db.q("INSERT INTO mw_tasks (id, comp_id, title, status, origin, created) VALUES (?, 7, 't', 'todo', ?, ?)", (i, o, t))
        ch = types.SimpleNamespace(db=db, _has=lambda t: t == "mw_tasks", _cols=lambda t: {c["name"] for c in db.q(f"PRAGMA table_info({t})")})
        self.assertEqual(mo.baseline_anchor(db, 7), ("plan:5", 2.0))
        with mock.patch.object(mo, "BOARD_LIMIT", 5):
            rows, _ = mo._board(ch, [7])
        ids = {r["id"] for r in rows}
        self.assertTrue({1, 2, 3, 25}.issubset(ids))                    # the baseline (1, 2) and the person-made tasks (3, 25), past the cap
        sc = mo.scopes([r["origin"] for r in rows], [r["created"] for r in rows], mo.baseline_anchor(db, 7))
        self.assertEqual(sum(1 for k in sc if k == "base"), 2)          # the first plan run's two tasks
        self.assertEqual(sum(1 for k in sc if k == "person"), 2)        # made by a person after it ended (at 3 and 50)

    def test_a_persons_scope_change_is_recorded_with_its_effect(self):
        # Milestone 4: an append-only record of who changed the scope, when, why, and the sizes before and after
        import os, tempfile, types
        from app.auth import AuthDB
        from app.mining_work import Work
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "a.db"))
        db.q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, updated REAL)"); db.q("INSERT INTO mw_comps (id) VALUES (7)")
        db.q("CREATE TABLE mw_events (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, ts REAL, agent_id INTEGER, task_id INTEGER, kind TEXT, text TEXT)")
        db.q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, origin TEXT, created REAL, status TEXT, title TEXT)")
        for i, (o, t) in enumerate([("plan:5", 1), ("plan:5", 2), ("agent:1:1", 3)], 1):
            db.q("INSERT INTO mw_tasks VALUES (?, 7, ?, ?, 'todo', 't')", (i, o, t))
        w = types.SimpleNamespace(db=db)
        w._event = lambda *a, **k: Work._event(w, *a, **k)
        w._scope_counts = lambda wid, skip=None: Work._scope_counts(w, wid, skip)
        before = w._scope_counts(7)
        db.q("INSERT INTO mw_tasks VALUES (4, 7, 'you', 9, 'todo', 'Re-run the benchmark')")
        Work._scope_event(w, 7, {"username": "leo"}, "added", 4, "Re-run the benchmark", "the scores moved", before=before)
        e = db.q("SELECT kind, task_id, text, ts FROM mw_events", one=True)
        self.assertEqual((e["kind"], e["task_id"]), ("scope", 4))
        self.assertIn("leo added “Re-run the benchmark” (task 4). Reason: the scores moved.", e["text"])
        self.assertIn("Original scope 2 → 2 tasks; active plan 2 → 3 tasks.", e["text"])
        self.assertTrue(e["ts"])
        Work._scope_event(w, 7, {"username": "leo"}, "added", 4, "Re-run the benchmark", "Control Hub task", before=before, actor="automatic dispatch")
        self.assertIn("automatic dispatch, on behalf of leo, added", db.q("SELECT text FROM mw_events ORDER BY id DESC LIMIT 1", one=True)["text"])

    def test_the_headline_is_the_owners_setting(self):
        import types
        ch = types.SimpleNamespace(db=types.SimpleNamespace(setting=lambda k: None))
        self.assertEqual(mo.progress_headline(ch), "original")                       # the last headline the Owner decided (G5-2.2)
        ch.db.setting = lambda k: "active"
        self.assertEqual(mo.progress_headline(ch), "active")
        ch.db.setting = lambda k: "agent work"
        self.assertEqual(mo.progress_headline(ch), "original")                       # nothing else can lead

    def test_the_baseline_is_the_first_plan_and_what_was_there_by_its_end(self):
        og = ["you", "plan:4", "plan:4", "agent:1:2", "you", "plan:7", "topminer"]
        cr = [1, 2, 3, 3.5, 5, 6, 7]
        self.assertEqual(mo.scopes(og, cr), ["base", "base", "base", "agent", "person", "agent", "person"])
        self.assertEqual(mo.scopes(["you", "agent:1:1", "you"], [1, 2, 3]), ["base", "agent", "person"])   # no plan: up to the first agent follow-up
