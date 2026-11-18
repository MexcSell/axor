"""G5-5 L5.1 measured evaluation (contract IC-11, approved by the Owner 2026-11-13).

- A Competition team's board task that was reviewed has no score: not the 100 of "its task is done", not the 30 of "sent back",
  not the 10 of the reviewer's third verdict. Its run is recorded as reviewed, with the verdict as the reason, and nothing is
  copied onto the run ledger. The board's two review steps write no score either.
- Every evaluation row names what it rests on (model_judged, derived, reviewed); a row from before L5.1 is never rewritten and
  gets its kind on read, from its EVALUATORS row.
- Coverage and both outcome cards count the reviewed group, and it is not a gap.
- The readers of run scores that the contract lists see what it says they see, and the one it doesn't list (the model router)
  falls back to its tier prior for board runs.
- The one reader of measured values returns D-004's value with the contract's five fields, or UNKNOWN with the reason, and writes
  nothing. A derived or model-judged score never reaches a mission criterion or one of the Owner's K-14 targets.
- K-14's targets read met, not met or no data; a target with nothing behind it is never met.

Not here: the rollback to RC1 with reviewed rows present (run against the RC1 image, g54-g55/tests/l51-rc1-rollback.txt).
"""
import inspect, json, os, sys, time, types, unittest

sys.path.insert(0, os.path.dirname(__file__))

from app import agent_core, analytics, evolution, mining_work, mission_ops as mo, missions, model_router, orchestrator as orc, runner  # noqa: E402
from test_orchestrator import G5  # noqa: E402
import test_g54_release_evidence as tv  # noqa: E402  (imported as modules so their own tests don't run again here)
import test_mission_cycles as tc  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402

DAY = 86400


def kept_job(q, comp, sid, score, status="done"):
    """A VM runner job's kept result, as runner.stored reads it: the run's row names the result file by sha256, and the file holds
    the score the job read from its own output."""
    import hashlib
    q("""CREATE TABLE IF NOT EXISTS mw_sbx (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, exit_code INTEGER, finished REAL, output TEXT, services TEXT)""")
    q("CREATE TABLE IF NOT EXISTS mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT)")
    body, path = json.dumps({"status": "done", "score": {"score": score, "tasks": 16}}), f"runs/sbx-{sid}/result.json"
    q("INSERT INTO mw_files (comp_id, path, content) VALUES (?,?,?)", (comp, path, body))
    q("INSERT INTO mw_sbx (id, comp_id, status, exit_code, finished, output, services) VALUES (?,?,?,0,?,?,?)",
      (sid, comp, status, time.time(), f"ok\n@@AXOR-RESULT sha256:{hashlib.sha256(body.encode()).hexdigest()} {path}\n", runner.SERVICE))
    return f"job:{sid}"


SCORING = [r for r in orc.EVALUATORS if r[3] not in ("exclude", "none")]


class Closing:
    """Closes the fixture's database when a test ends: on Postgres every AuthDB holds a connection for as long as it lives (PX-R13)."""
    def tearDown(self):
        db = getattr(self, "db", None)
        super().tearDown()
        try: db.db.close()
        except Exception: pass  # noqa: BLE001 - already closed, or the fixture made none


class Board(Closing, G5):
    """The orchestrator on a board with tasks 1 (done), 2 (sent back, then done), 3 (rejected by its reviewer: waits for a person),
    4 (waits for a person, never reviewed by an agent)."""
    def setUp(self):
        super().setUp()
        self.o = orc.init(self.db)
        q = self.db.q
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, origin TEXT)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, kind TEXT, status TEXT)")
        q("INSERT INTO mw_tasks VALUES (1, 5, 'done', NULL), (2, 5, 'done', NULL), (3, 5, 'review', NULL), (4, 5, 'review', NULL)")
        q("""INSERT INTO mw_runs VALUES (10, 5, 1, 'task', 'done'), (20, 5, 2, 'task', 'done'), (21, 5, 2, 'review', 'done'), (22, 5, 2, 'task', 'done'),
             (30, 5, 3, 'task', 'done'), (31, 5, 3, 'review', 'done'), (40, 5, 4, 'task', 'done')""")
        mk = lambda n, **kw: self.run_row(system="teams", kind="task", ref=f"mw:{n}", agent_key="teams:9", model="fake:m", **kw)
        self.done, self.sent, self.again, self.rejected, self.waiting = mk(10), mk(20), mk(22), mk(30), mk(40, started=time.time() - 60, finished=time.time())

    def row(self, rid): return self.ev_row(rid)
    def ledger(self, rid): return self.db.q("SELECT score FROM ac_runs WHERE id=?", (rid,), one=True)["score"]


class Reviewed(Board):
    def test_a_done_board_task_has_no_score(self):
        self.o.evaluate()
        r = self.row(self.done)
        self.assertEqual((r["state"], r["score"], r["basis"]), ("reviewed", None, "reviewed"))
        self.assertEqual(r["reason"], orc.REVIEWED["approved"]); self.assertIn("unmeasured", r["reason"])
        self.assertIsNone(self.ledger(self.done))  # nothing copied onto the ledger (IC-11 guarantee 1)

    def test_sent_back_and_rejected_have_no_score_either(self):
        self.o.evaluate()
        for rid, why in ((self.sent, "sent_back"), (self.again, "approved"), (self.rejected, "rejected")):
            r = self.row(rid)
            self.assertEqual((r["state"], r["score"], r["basis"], r["reason"]), ("reviewed", None, "reviewed", orc.REVIEWED[why]), why)
            self.assertIsNone(self.ledger(rid), why)
        self.assertIsNone(self.row(self.waiting))  # nobody reviewed it yet: it waits for a person, as before

    def test_no_board_run_gets_a_score_from_any_review(self):
        self.o.evaluate()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_runs WHERE system='teams' AND score IS NOT NULL", one=True)["n"], 0)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_evals WHERE system='teams' AND score IS NOT NULL", one=True)["n"], 0)

    def test_a_persons_decision_replaces_the_reviewers_rejection(self):
        self.o.evaluate()
        self.db.q("UPDATE mw_tasks SET status='done' WHERE id=3")  # the person approves what the reviewer passed to them
        self.o._gaps_at = None
        self.o.evaluate()
        r = self.row(self.rejected)
        self.assertEqual((r["state"], r["score"], r["reason"]), ("reviewed", None, orc.REVIEWED["approved"]))

    def test_a_task_nobody_reviews_is_a_gap_after_the_deadline_never_a_score(self):
        old = time.time() - 5 * DAY
        self.db.q("INSERT INTO mw_tasks VALUES (5, 5, 'review', NULL)"); self.db.q("INSERT INTO mw_runs VALUES (50, 5, 5, 'task', 'done')")
        rid = self.run_row(system="teams", kind="task", ref="mw:50", started=old, finished=old)
        self.o.evaluate()
        self.assertEqual((self.row(rid)["state"], self.row(rid)["score"], self.row(rid)["basis"]), ("gap", None, None))

    def test_no_scored_event_for_a_reviewed_run(self):
        self.o.evaluate()
        src = inspect.getsource(orc.Orchestrator)
        self.assertIn("e.state='scored' AND r.started>? AND r.owner_id>0", src)  # run.scored is emitted for scored rows only
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_evals WHERE state='scored'", one=True)["n"], 0)

    def test_reviewed_work_is_not_a_broken_handoff(self):
        """Work that reached execution and was reviewed did reach evaluation: the layers page must not call that handoff broken."""
        self.db.q("UPDATE ac_runs SET decision='{}', started=?, finished=? WHERE id=?", (time.time() - 3600, time.time() - 3000, self.done))  # a routed run: work reached execution
        self.o.evaluate(); self.o.observe_handoffs(); self.o.observe_handoffs()
        n = {r["kind"]: r["n"] for r in self.db.q("SELECT kind, COUNT(*) n FROM io_events WHERE kind LIKE 'run.%' GROUP BY kind")}
        self.assertEqual((n.get("run.reviewed"), n.get("run.scored"), n.get("run.routed")), (4, None, 1))  # once each, however often it's observed
        e = next(x for x in self.o.edges(7, time.time() - 7 * DAY) if x["key"] == "execution>evaluation")
        self.assertEqual((e["state"], e["done"]), ("flowing", 4))

    def test_the_boards_review_steps_write_no_score(self):
        """mining_work.review (the person's) and _review (the squad lead's) wrote 100/30 and 100/30/10 through agent_core.score."""
        code = "\n".join(ln for ln in inspect.getsource(mining_work).splitlines() if not ln.lstrip().startswith("#"))
        self.assertNotIn("agent_core.score(", code)


class Kinds(Closing, G5):
    def test_every_row_that_yields_a_verdict_declares_its_kind(self):
        for r in SCORING:
            self.assertEqual(len(r), 6, r); self.assertIn(r[5], orc.BASES, r)
        for r in orc.EVALUATORS:
            if r[3] in ("exclude", "none"): self.assertEqual(len(r), 5, r)

    def test_the_declared_kinds(self):
        """Model-judged: a model scored the output. Derived: a fixed number for a decision or a status. Reviewed: a board review."""
        want = {("evolution", "experiment", "ev:1"): "model_judged", ("missions", "plan", "mx:1"): "model_judged", ("teams", "task", "mw:1"): "reviewed",
                ("teams", "plan", "mw:3"): "derived", ("workflow", "engineer", "mb:r1"): "derived", ("workforce", "swarm-work", "sw:1"): "model_judged",
                ("workforce", "execute", "wf:1"): "model_judged", ("hub", "task", "ctl:t1"): "derived", ("other", "intelligence", "ctl:mi:x"): "derived",
                ("company", "task", "co:1"): "model_judged", ("team", "task", "tt:1"): "derived", ("team", "cycle", "tc:1"): "model_judged"}
        self.assertEqual(len(want), len(SCORING))
        for (s, k, ref), b in want.items(): self.assertEqual(orc.evaluator_for(s, k, ref)[5], b, (s, k))

    def test_each_branch_writes_its_kind(self):
        o, q, old = orc.init(self.db), self.db.q, time.time() - 5 * DAY
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, status TEXT, origin TEXT)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY, comp_id INTEGER, task_id INTEGER, kind TEXT, status TEXT)")
        q("CREATE TABLE ctl_tasks (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, origin TEXT, mission TEXT, created REAL)")
        q("CREATE TABLE wf_missions (id INTEGER PRIMARY KEY, score INTEGER, status TEXT)"); q("CREATE TABLE wf_runs (id INTEGER PRIMARY KEY, mission_id INTEGER, score INTEGER)")
        q("CREATE TABLE co_artifacts (id INTEGER PRIMARY KEY, task_id INTEGER)"); q("CREATE TABLE co_evals (id INTEGER PRIMARY KEY, artifact_id INTEGER, score REAL)")
        q("CREATE TABLE mb_tasks (id INTEGER PRIMARY KEY, merged INTEGER, status TEXT)"); q("CREATE TABLE mb_runs (run TEXT, task_id INTEGER)")
        q("INSERT INTO mw_tasks VALUES (1, 5, 'done', NULL), (3, 5, 'done', 'plan:30'), (4, 5, 'todo', 'plan:30')"); q("INSERT INTO mw_runs VALUES (10, 5, 1, 'task', 'done')")
        q("INSERT INTO ctl_tasks VALUES (1, 7, 'done', NULL, NULL, ?)", (old,)); q("INSERT INTO wf_missions VALUES (1, NULL, 'running')"); q("INSERT INTO wf_runs VALUES (11, 1, 72)")
        q("INSERT INTO co_artifacts VALUES (1, 6)"); q("INSERT INTO co_evals VALUES (1, 1, 81)"); q("INSERT INTO mb_tasks VALUES (1, 1, 'done')"); q("INSERT INTO mb_runs VALUES ('r1', 1)")
        for st in ("done", "declined"): q("INSERT INTO ctl_tasks (user_id, status, origin, mission, created) VALUES (7, ?, 'intelligence', 'bt', ?)", (st, old + 20))
        rows = {"reviewed": self.run_row(system="teams", kind="task", ref="mw:10"),
                "team_plan": self.run_row(system="teams", kind="plan", ref="mw:30", started=old, finished=old),
                "control_task": self.run_row(system="hub", kind="task", ref="ctl:t1"), "intel": self.run_row(system="other", kind="intelligence", ref="ctl:mi:bt", started=old, finished=old + 30),
                "workforce": self.run_row(system="workforce", kind="execute", ref="wf:11"), "company": self.run_row(system="company", kind="task", ref="co:6"),
                "workflow": self.run_row(system="workflow", kind="engineer", ref="mb:r1"), "judge": self.run_row(system="evolution", kind="experiment", ref="ev:1", score=77),
                "check": self.run_row(system="missions", kind="verify", ref="mx:4", score=64), "mission": self.run_row(system="missions", kind="plan", ref="mx:4"),
                "child": self.run_row(system="teams", kind="task", ref="mw:99", corr="mx:4", score=64), "excluded": self.run_row(system="hub", kind="chat", ref=None),
                "gap": self.run_row(system="longtask", kind="segment", ref="ia:1")}
        o.evaluate()
        got = {k: (self.ev_row(v)["state"], self.ev_row(v)["basis"]) for k, v in rows.items()}
        self.assertEqual(got, {"reviewed": ("reviewed", "reviewed"), "team_plan": ("scored", "derived"), "control_task": ("scored", "derived"), "intel": ("scored", "derived"),
                               "workforce": ("scored", "model_judged"), "company": ("scored", "model_judged"), "workflow": ("scored", "derived"),
                               "judge": ("scored", "model_judged"), "check": ("scored", "model_judged"), "mission": ("scored", "model_judged"),
                               "child": ("scored", "model_judged"),  # a board run its mission's independent check scored: the check's kind, not a review's
                               "excluded": ("excluded", None), "gap": ("gap", None)})
        for k in ("team_plan", "control_task", "intel", "workflow"):  # open point (b): the other derived numbers keep their numbers
            self.assertIsNotNone(self.ev_row(rows[k])["score"], k)

    def test_rows_from_before_are_unchanged_and_get_their_kind_on_read(self):
        o, q, now = orc.init(self.db), self.db.q, time.time()
        old = [(self.run_row(system="teams", kind="task", ref="mw:1", score=100), "Its reviewer's verdict, a squad lead's or yours (approve 100, sent back 30)", "derived"),
               (self.run_row(system="teams", kind="task", ref="mw:2", score=30), "Sent back for another try (a later run of the same task)", "derived"),
               (self.run_row(system="teams", kind="plan", ref="mw:3", score=50), "1 of the 2 tasks it put on the board were delivered", "derived"),
               (self.run_row(system="missions", kind="plan", ref="mx:4", score=80), "Mission Control's independent check of mx:4", "model_judged"),
               (self.run_row(system="company", kind="task", ref="co:6", score=81), "The company evaluator agent's score of its deliverable", "model_judged"),
               (self.run_row(system="workforce", kind="execute", ref="wf:11", score=72), "Workforce reviewer's score of this run", "model_judged"),
               (self.run_row(system="hub", kind="task", ref="ctl:t1", score=100), "You accepted its result", "derived"),
               (self.run_row(system="teams", kind="task", ref="mw:9", score=64, corr="mx:4"), "Mission Control's independent check of mx:4", "model_judged"),
               (self.run_row(system="longtask", kind="segment", ref="ia:1", score=55), "Its evaluator or verifier (later)", "model_judged")]
        for rid, src, _ in old:  # written by RC1: eleven columns, no kind
            r = q("SELECT * FROM ac_runs WHERE id=?", (rid,), one=True)
            q("INSERT INTO io_evals (run_id, owner_id, system, kind, ref, corr, state, reason, source, score, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (rid, 7, r["system"], r["kind"], r["ref"], r["corr"], "scored", "", src, r["score"], now))
        snap = lambda: json.dumps([q("SELECT * FROM io_evals ORDER BY run_id"), q("SELECT id, score FROM ac_runs ORDER BY id")], sort_keys=True, default=str)
        before = snap()
        o = orc.init(self.db)  # the upgrade: a restart on this version
        o._gaps_at = None; o.evaluate(); o.evaluate()
        self.assertEqual(snap(), before)  # byte-identical: nothing is rewritten, and the kind column stays NULL on them
        for rid, src, want in old:
            r = self.ev_row(rid)
            self.assertIsNone(r["basis"])
            self.assertEqual(orc.basis_for(r["system"], r["kind"], r["ref"], r["state"], r["corr"], r["source"]), want, src)
        c = o.coverage(7, now - 30 * DAY)
        self.assertEqual((c["scored"], c["scored_by"], c["measured"]), (9, {"model_judged": 5, "derived": 4}, 0))

    def test_a_review_score_under_a_persistent_mission_is_never_model_judged(self):
        """A persistent mission has no model check, so a score on one of its board runs can only be a review's (written before L5.1)."""
        o = orc.init(self.db)
        rid = self.run_row(system="teams", kind="task", ref="mw:7", corr="mx:9", score=100)
        other = self.run_row(system="missions", kind="verify", ref="mx:9", corr="mx:9")  # no score: nothing checked this mission
        o.evaluate()
        self.assertEqual((self.ev_row(rid)["state"], self.ev_row(rid)["basis"]), ("scored", "derived"))
        self.assertEqual(orc.basis_for("teams", "task", "mw:7", "scored", "mx:9", ""), "derived")  # a mission link alone decides nothing
        self.assertEqual(o._basis("teams", "task", "mw:7", "scored", "mx:9", "", 100), "derived")
        self.db.q("UPDATE ac_runs SET score=100 WHERE id=?", (other,))
        self.assertEqual(o._basis("teams", "task", "mw:7", "scored", "mx:9", "", 100), "model_judged")  # the check holds this very score
        self.assertEqual(o._basis("teams", "task", "mw:7", "scored", "mx:9", "", 30), "derived")

    def test_the_trace_names_the_kind_of_every_score(self):
        o = orc.init(self.db)
        a = self.run_row(system="missions", kind="verify", ref="mx:4", corr="mx:4", score=64)
        b = self.run_row(system="teams", kind="task", ref="mw:9", corr="mx:4", score=100)  # scored by a review before L5.1
        self.db.q("INSERT INTO io_evals (run_id, owner_id, system, kind, ref, corr, state, reason, source, score, ts) VALUES (?, 7, 'teams', 'task', 'mw:9', 'mx:4', 'scored', '', ?, 100, ?)",
                  (b, "Approved: its task is done", time.time()))
        o.evaluate()
        c = self.run_row(system="teams", kind="task", ref="mw:8", corr="mx:4", score=64)  # scored by the mission's check: its very score
        self.db.q("INSERT INTO io_evals (run_id, owner_id, system, kind, ref, corr, state, reason, source, score, ts) VALUES (?, 7, 'teams', 'task', 'mw:8', 'mx:4', 'scored', '', ?, 64, ?)",
                  (c, "Its reviewer's verdict, a squad lead's or yours (approve 100, sent back 30)", time.time()))
        got = {r["id"]: r["eval_basis"] for r in o.trace(7, "mx:4")["runs"]}
        self.assertEqual((got[a], got[b], got[c]), ("model_judged", "derived", "model_judged"))  # a review's 100 under a mission is still a review's
        for r in o.trace(7, "mx:4")["runs"]: self.assertNotIn("eval_source", r)


class Groups(Board):
    def test_coverage_counts_the_reviewed_group_and_it_is_not_a_gap(self):
        self.o.evaluate()
        c = self.o.coverage(7, time.time() - 30 * DAY)
        self.assertEqual((c["finished"], c["reviewed"], c["scored"], c["gap"], c["waiting"], c["scoreable"]), (5, 4, 0, 0, 1, 0))
        self.assertEqual(c["accounted_pct"], 80)  # the four reviewed runs are accounted for; the fifth still waits for a person
        self.assertEqual(c["gaps"], []); self.assertIsNone(c["scored_pct"])
        self.assertEqual(c["outcomes"]["runs"]["reviewed"], 4); self.assertEqual(c["outcomes"]["runs"]["unsettled"], 1)
        self.assertEqual(sum(c["outcomes"]["runs"].values()), c["finished"])

    def test_the_outcomes_card_has_the_group(self):
        self.o.evaluate()
        a = mo.accountability(types.SimpleNamespace(db=self.db, _has=self.o._has), 7, time.time() - 30 * DAY)
        n = {o["key"]: o["n"] for o in a["outcomes"]}
        self.assertEqual((n["reviewed"], n["success"], n["inconclusive"]), (4, 0, 1))
        self.assertEqual(sum(n.values()), a["total"])
        self.assertEqual(next(o for o in a["outcomes"] if o["key"] == "reviewed")["label"], "Reviewed, unmeasured")
        self.assertEqual([x["what"] for x in a["inconclusive"]], ["Finished, verdict still due"])  # the reviewed ones aren't "waiting" or a gap
        self.assertEqual(a["reviewed"], 4)


class Readers(Board):
    """What the readers of run scores see once board reviews carry no score (IC-11 section 3)."""
    def test_reviews_are_not_validated_deliverables(self):
        self.o.evaluate()
        a = analytics.Analytics(self.db, None)
        self.assertEqual(a._period(7, time.time() - 30 * DAY, time.time() + 1)["ledger"]["validated"], 0)
        self.db.q("UPDATE ac_runs SET score=100 WHERE id=?", (self.done,))  # a run scored before L5.1 keeps its score, and still counts
        self.assertEqual(a._period(7, time.time() - 30 * DAY, time.time() + 1)["ledger"]["validated"], 1)

    def test_three_sent_back_runs_are_not_a_weak_spot(self):
        for n in (60, 61, 62, 63): self.db.q("INSERT INTO mw_runs VALUES (?, 5, 6, 'task', 'done')", (n,))
        self.db.q("INSERT INTO mw_tasks VALUES (6, 5, 'todo', NULL)")
        for n in (60, 61, 62, 63): self.run_row(system="teams", kind="task", ref=f"mw:{n}", agent_key="teams:8", started=time.time() - 3600, finished=time.time() - 3000)
        self.o.evaluate()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_evals WHERE reason=?", (orc.REVIEWED["sent_back"],), one=True)["n"], 4)  # 60-62, and 20 from the fixture
        self.assertEqual([s for s in self.o.signals(7) if s["agent"] == "teams:8"], [])

    def test_the_model_router_falls_back_to_the_tier_prior_for_board_runs(self):
        """Not in the contract's reader table (PX-R11): the router learned quality from the review's 100 and 30."""
        self.o.evaluate()
        pool, prior = [{"model": "fake:m", "tier": 2, "price": 1.0}], model_router.TIER_PRIOR[2]
        def ranked():
            st = self.core.stats(7, "teams")
            _, d = model_router.rank(pool, st, "task")
            return st[("fake:m", "task")], d["candidates"][0], d["reason"]
        st, cand, why = ranked()
        self.assertGreaterEqual(st["n"], 4)  # the board's runs are in the router's statistics
        self.assertEqual((st.get("scored") or 0, cand["scored"], cand["quality"]), (0, 0, prior)); self.assertIn("(tier prior)", why)
        # the control: with RC1's write (approve = 100 on the ledger) the same call ranks on the scores, above the prior
        self.db.q("UPDATE ac_runs SET score=100 WHERE id IN (?, ?)", (self.done, self.again))
        st, cand, why = ranked()
        self.assertEqual((st["scored"], cand["scored"]), (2, 2)); self.assertGreater(cand["quality"], prior); self.assertNotIn("(tier prior)", why)


@tv.own_tests
class Measured(tv.Reader):
    """missions.measured: the one reader of measured values, over D-004's reader."""
    def setUp(self):
        super().setUp()
        self.sample([tp.row(i, f"5H{i}", f"5C{i}", 1 - i / 100) for i in range(1, 7)] + [tp.row(77, tp.HOT, "5SomeCold", 0.05)])  # our key ranks 7th

    def by(self, mid, now=None): return {x["id"]: x for x in self.mx.measured(self.mx._m(mid), now)["measures"]}

    def job_row(self, score, says=None, sid=77):
        """A benchmark row on the current release whose score a VM runner job's own output gave (the job's kept result says `says`)."""
        self.db.q("CREATE TABLE IF NOT EXISTS mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT)")
        import hashlib
        body, path = json.dumps({"status": "done", "score": {"score": score if says is None else says, "tasks": 3}, "inputs": {"job_sha256": "ab" * 32}}), f"runs/sbx-{sid}/result.json"
        self.db.q("INSERT INTO mw_files (comp_id, path, content) VALUES (?,?,?)", (tp.WID, path, body))
        self.db.q("INSERT INTO mw_sbx (id, comp_id, status, exit_code, started, finished, pod, services, output) VALUES (?,?,'done',0,?,?,?,?,?)",
                  (sid, tp.WID, time.time() - 60, time.time(), f"job-{sid}", runner.SERVICE, f"ok\n@@AXOR-RESULT sha256:{hashlib.sha256(body.encode()).hexdigest()} {path}\n"))
        self.row(score, f"job:{sid}")

    def test_a_valid_value_comes_with_its_five_fields(self):
        self.job_row(0.9)
        mid = self.create([tp.chain_measure(target=10), self.bench()])
        ev = {e["id"]: e for e in self.mx._evidence(self.mx._m(mid))["measures"]}
        got = self.by(mid)
        for k in ("chain_rank", "bench_score"):
            self.assertEqual(ev[k]["status"], "valid", k)
            self.assertEqual((got[k]["state"], got[k]["value"], got[k]["pass"]), ("measured", ev[k]["value"], ev[k]["pass"]), k)  # D-004's value, unchanged
            f = got[k]["fields"]
            self.assertEqual(set(f), {"source", "time", "method", "benchmark_version", "evidence_ref"})
            for name, v in f.items(): self.assertTrue(v, f"{k}.{name}")
            self.assertEqual(f["evidence_ref"], ev[k]["evidence_ref"]); self.assertEqual(f["time"], ev[k]["measured_at"])
        self.assertEqual(got["chain_rank"]["fields"]["benchmark_version"], "not a benchmark")
        self.assertEqual(got["bench_score"]["fields"]["benchmark_version"], {"release": self.rel_id, "suite_hash": "h1"})
        self.assertEqual((got["chain_rank"]["rests_on"], got["bench_score"]["rests_on"]), ("owner_attested_key", "internal_measured"))
        self.assertEqual(ev["bench_score"]["evidence_ref"]["score_source"], "read from the job's output file")  # the words measured() keys on are D-004's own

    def test_a_number_an_agent_filed_after_a_clean_run_is_not_measured(self):
        """Q-4: a clean sandbox run in the same run makes the row valid for the mission's evaluation. The number is still the
        agent's, so IC-11's reader doesn't call it measured (it did until this correction)."""
        s = tv.sbx(self.db.q, tp.WID, tv.RUN)
        self.row(0.9, f"sbx:{s}")
        mid = self.create([tp.chain_measure(target=10), self.bench()])
        e = next(x for x in self.mx._evidence(self.mx._m(mid))["measures"] if x["id"] == "bench_score")
        self.assertEqual((e["status"], e["value"], e["pass"], e["evidence_ref"]["score_source"]), ("valid", 0.9, True, "filed by the agent that ran it"))  # D-004 is unchanged
        x = self.by(mid)["bench_score"]
        self.assertEqual((x["state"], x["value"], x["pass"], x["fields"], x["status"]), ("UNKNOWN", None, None, None, "valid"))
        self.assertIn("the number is the one the agent filed", x["reason"])
        self.assertEqual(self.by(mid)["chain_rank"]["state"], "measured")  # an external measure isn't touched by this

    def test_a_job_whose_kept_result_says_another_score_is_not_measured(self):
        self.job_row(0.9, says=0.2)
        mid = self.create([tp.chain_measure(target=10), self.bench()])
        x = self.by(mid)["bench_score"]
        self.assertEqual((x["state"], x["value"], x["status"]), ("UNKNOWN", None, "unverifiable"))

    def test_everything_else_is_unknown_with_the_readers_reason(self):
        self.row(0.9)  # a benchmark with no run behind it: unverifiable
        _, tok = self.key()  # a team key: its report is self-reported
        self.report(tok, 3)
        mid = self.create([tp.chain_measure(target=10), tp.ingest_measure(), self.bench()])
        now = time.time() + 5 * 3600  # the chain sample is stale by then
        ev = {e["id"]: e for e in self.mx._evidence(self.mx._m(mid), now)["measures"]}
        got = self.by(mid, now)
        self.assertEqual({k: v["status"] for k, v in ev.items()}, {"chain_rank": "stale", "ingest_rank": "self_reported", "bench_score": "unverifiable"})
        for k, x in got.items():
            self.assertEqual((x["state"], x["value"], x["pass"], x["fields"]), ("UNKNOWN", None, None, None), k)
            self.assertIn(ev[k]["reason"], x["reason"]); self.assertTrue(x["reason"].lower().startswith(ev[k]["status"].replace("_", " ")), x["reason"])

    def test_a_valid_value_without_one_of_the_fields_is_unknown(self):
        mid = self.create([tp.chain_measure(target=10)])
        real = self.mx._evidence
        def cut(m, now=None):
            ev = real(m, now)
            ev["measures"][0]["evidence_ref"] = None
            return ev
        self.mx._evidence = cut
        x = self.by(mid)["chain_rank"]
        self.assertEqual((x["state"], x["value"]), ("UNKNOWN", None)); self.assertIn("lacks evidence ref", x["reason"])

    def test_reading_writes_nothing_and_no_run_score_is_read(self):
        mid = self.create([tp.chain_measure(target=10), self.bench()])
        tables = [r["name"] for r in self.db.q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        snap = lambda: json.dumps({t: self.db.q(f"SELECT * FROM {t}") for t in tables}, sort_keys=True, default=str)
        before = snap()
        a = self.mx.measured(self.mx._m(mid), 1e10 - 1)
        self.assertEqual(self.mx.team_measured(tp.WID, 1e10 - 1), a)
        self.assertEqual(snap(), before)
        self.assertIsNone(self.mx.team_measured(tp.WID + 1))  # a team with no persistent mission
        src = inspect.getsource(missions.Missions.measured) + inspect.getsource(missions.Missions.team_measured)
        for word in ("ac_runs", "io_evals", "UPDATE", "INSERT", "DELETE"): self.assertNotIn(word, src)

    def test_a_score_on_the_ledger_never_meets_a_criterion(self):
        """Derived and model-judged numbers (run scores) don't reach D-004's reader, so they can't meet a mission's criterion."""
        mid = self.create([tp.chain_measure(target=5), self.bench()])  # rank 7 against <= 5: not met; no benchmark: UNKNOWN
        dims = lambda: self.mx._evidence(self.mx._m(mid), 1e9 + 1)["dimensions"]
        before = json.dumps(dims(), sort_keys=True, default=str)
        self.assertEqual((dims()["competition"]["value"], dims()["technical"]["value"]), ("FAIL", "UNKNOWN"))
        self.db.q("""CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, system TEXT, owner_id INTEGER, kind TEXT, ref TEXT, corr TEXT, status TEXT,
                     score REAL, team TEXT, started REAL, finished REAL)""")
        for i in range(5):
            rid = self.db.q("""INSERT INTO ac_runs (system, owner_id, kind, ref, corr, status, score, team, started, finished) VALUES ('teams', ?, 'task', ?, ?, 'done', 100, ?, ?, ?)
                               RETURNING id""", (tp.TEAM_ACCOUNT, f"mw:{900 + i}", f"mx:{mid}", f"comp:{tp.WID}", time.time() - 60, time.time()), one=True)["id"]
            self.db.q("""INSERT INTO io_evals (run_id, owner_id, system, kind, ref, corr, state, reason, source, score, ts, basis) VALUES (?, ?, 'teams', 'task', ?, ?, 'scored', '', 'x', 100, ?, ?)""",
                      (rid, tp.TEAM_ACCOUNT, f"mw:{900 + i}", f"mx:{mid}", time.time(), "model_judged" if i % 2 else "derived"))
        self.assertEqual(json.dumps(dims(), sort_keys=True, default=str), before)
        src = "".join(inspect.getsource(getattr(missions.Missions, n)) for n in ("_evidence", "_ev_chain", "_ev_ingest", "_ev_bench", "_dimensions"))
        for word in ("ac_runs", "io_evals"): self.assertNotIn(word, src)
        self.assertNotIn("ac_runs", inspect.getsource(evolution.Evolution.measured))  # a trial's evidence is the team's benchmark jobs, never a run score
        self.assertNotIn("io_evals", inspect.getsource(evolution.Evolution.measured))


class Performance(unittest.TestCase):
    """mission_ops.performance: every figure names its kind; the mission's measures come from the measured reader."""
    def view(self, mm, before=None, **std):
        import tempfile
        from app.auth import AuthDB
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        db = AuthDB(os.path.join(self.dir.name, "a.db")); self.addCleanup(db.db.close)
        has = lambda t: bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True))
        if before: before(db)
        mx = types.SimpleNamespace(team_measured=(lambda wid, now=None: mm) if not callable(mm) else mm)
        ch = types.SimpleNamespace(db=db, _has=has, _cols=lambda t: {r["name"] for r in db.q(f"PRAGMA table_info({t})")}, mx=mx)
        c = {"standing": std, "target_rank": 10, "criteria": [], "objective_progress": {"pct": None},
             "work": {"verified": 3, "original": 5, "planned": 1, "unverified": 1, "dropped": 0}}
        return mo.performance(ch, 7, c, {"id": 5}, time.time())

    def figures(self, dims): return {f["label"]: f for d in dims for f in d["figures"]}

    def test_every_figure_names_its_kind(self):
        f = {"source": "chain:scout", "time": time.time() - 600, "method": "sample #3", "benchmark_version": "not a benchmark", "evidence_ref": {"sample": 3}}
        mm = {"measures": [{"id": "chain_rank", "text": "Chain rank", "metric": "rank", "tier": "external", "op": "<=", "target": 10.0, "state": "measured", "value": 7, "pass": True, "reason": "", "fields": f},
                           {"id": "bench_score", "text": "Frozen-suite score", "metric": "score", "tier": "internal", "op": ">=", "target": 0.8, "state": "UNKNOWN", "value": None, "pass": None,
                            "reason": "Missing: No comparable benchmark on the frozen suite yet", "fields": None}]}
        dims = self.view(mm, rank=7, of=200, gap=-3, top1=1.5)
        self.assertTrue(self.view(mm)[0]["measured"])  # no campaign rank, but a measured mission measure: the dimension is measured
        for d in dims:
            for x in d["figures"]: self.assertIn(x["kind"], mo.FIGURE_KINDS, x["label"])
        g = self.figures(dims)
        a, b = g["Mission measure: Chain rank (<= 10)"], g["Mission measure: Frozen-suite score (>= 0.8)"]
        self.assertEqual((a["value"], a["kind"]), ("7 · meets the target", "measured")); self.assertIn("chain:scout", a["note"])
        self.assertEqual((b["value"], b["kind"]), ("UNKNOWN", "unknown")); self.assertIn("No comparable benchmark", b["note"])
        self.assertEqual(g["Verified deliverables"]["kind"], "reviewed")  # an approval is a review, never the work's measured quality
        self.assertEqual({g[k]["kind"] for k in ("Runs this week", "Tokens this week", "Experiments")}, {"counted"})
        self.assertEqual((g["Official rank"]["kind"], g["Validation score"]["kind"], g["Target"]["kind"]), ("measured", "unknown", "set"))

    def test_a_benchmark_score_is_measured_only_while_its_jobs_kept_result_says_it(self):
        def seed(db):
            db.q("CREATE TABLE mw_bench (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, score REAL, solved INTEGER, suite TEXT, suite_tasks INTEGER, ts REAL, comparable INTEGER, evidence_ref TEXT)")
        for ref, job_says, kind, why in (("job", 0.58, "measured", "its job's own output file gave the score"), ("job", 0.31, "reported", "says another score"),
                                         ("job:404", None, "reported", "kept result is gone"), ("sbx:3", None, "reported", "filed by an agent or a person"), (None, None, "reported", "filed by an agent")):
            def before(db, ref=ref, job_says=job_says):
                seed(db)
                if ref == "job": ref = kept_job(db.q, 5, 9, job_says)
                db.q("INSERT INTO mw_bench (comp_id, score, solved, suite, suite_tasks, ts, comparable, evidence_ref) VALUES (5, 0.58, 1, 'swe-mini', 3, ?, 1, ?)", (time.time(), ref))
            f = self.figures(self.view(None, before=before))["Validation score"]
            self.assertEqual((f["value"], f["kind"]), ("0.58", kind), (ref, job_says)); self.assertIn(why, f["note"])

    def test_without_a_mission_the_measures_read_unknown(self):
        dims = self.view(None)
        self.assertFalse(dims[0]["measured"])  # no rank, no mission measure: the dimension says "Not measured"
        g = self.figures(dims)
        self.assertEqual((g["Mission measures"]["value"], g["Mission measures"]["kind"], g["Official rank"]["value"], g["Official rank"]["kind"]), ("UNKNOWN", "unknown", "UNKNOWN", "unknown"))
        def boom(wid, now=None): raise RuntimeError("no such table")
        g = self.figures(self.view(boom))
        self.assertEqual(g["Mission measures"]["value"], "UNKNOWN"); self.assertIn("RuntimeError", g["Mission measures"]["note"])


class Targets(Closing, G5):
    """The Owner's K-14 targets: met, not met or no data, with the ids behind each."""
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("CREATE TABLE mx_missions (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT, understanding TEXT, verification TEXT, finished REAL)")
        q("CREATE TABLE ev_proposals (id INTEGER PRIMARY KEY, origin TEXT, target_kind TEXT, status TEXT)")
        q("CREATE TABLE ex_recalls (id INTEGER PRIMARY KEY, user_id INTEGER, actor TEXT)"); q("CREATE TABLE ex_uses (id INTEGER PRIMARY KEY AUTOINCREMENT, recall_id INTEGER, ref TEXT, ts REAL)")
        q("CREATE TABLE mx_lessons (id INTEGER PRIMARY KEY, outcome TEXT)")
        q("CREATE TABLE au_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, comp_id INTEGER, version INTEGER, source TEXT, ts REAL)")
        q("CREATE TABLE mw_bench (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, comparable INTEGER, score REAL, ts REAL, suite_hash TEXT, evidence_ref TEXT)")
        self.a, self.now = analytics.Analytics(self.db, None), time.time()

    def t(self): return {x["k"]: x for x in self.a.targets(self.now - 30 * DAY)}
    def mission(self, mid, v, persistent=True, status="delivered", ago=DAY):
        self.db.q("INSERT INTO mx_missions VALUES (?, 7, ?, ?, ?, ?)", (mid, status, json.dumps({"persistent": persistent}), json.dumps(v), self.now - ago))

    def test_nothing_behind_a_target_is_no_data_never_met(self):
        t = self.t()
        self.assertEqual(list(t), ["M1", "M2", "M7", "M8", "M9"])
        for k, x in t.items(): self.assertEqual((x["state"], x["value"], x["ids"]), ("none", None, []), k)

    def test_run_scores_reach_no_target(self):
        for i in range(6): self.run_row(system="teams", kind="task", ref=f"mw:{i}", score=100)
        self.assertEqual({x["state"] for x in self.t().values()}, {"none"})

    def test_m1_a_competition_mission_closed_on_external_evidence(self):
        self.mission(1, {"rule": 2, "rests_on": [], "independent": True})  # ended, not met
        self.mission(2, {"rule": 1, "rests_on": ["owner_attested_key", "self_reported"], "independent": True})  # not external only
        self.mission(3, {"rule": 1, "rests_on": [], "independent": True})  # rests on nothing
        self.mission(4, {"rule": 1, "rests_on": ["owner_attested_key"], "independent": True}, status="monitoring")  # not delivered
        self.mission(5, {"score": 90, "independent": True}, persistent=False)  # a one-shot mission isn't a competition mission
        x = self.t()["M1"]
        self.assertEqual((x["state"], x["value"], x["ids"]), ("not_met", 0, []))
        self.mission(6, {"rule": 1, "rests_on": ["owner_designated_evaluator", "owner_attested_key"], "independent": True})
        x = self.t()["M1"]
        self.assertEqual((x["state"], x["value"], x["ids"]), ("met", 1, [6]))

    def test_m2_every_delivered_mission_verified_by_another(self):
        self.mission(1, {"independent": True}, persistent=False)
        self.assertEqual((self.t()["M2"]["state"], self.t()["M2"]["value"]), ("met", "1 of 1"))
        self.mission(2, {"score": 80}, persistent=False)  # doesn't record who verified it: can't be called met
        self.assertEqual(self.t()["M2"]["state"], "none"); self.assertIn("1 don't record", self.t()["M2"]["detail"])
        self.mission(3, {"independent": False}, persistent=False)
        self.assertEqual((self.t()["M2"]["state"], self.t()["M2"]["ids"]), ("not_met", [3]))
        self.db.q("UPDATE mx_missions SET finished=? WHERE id IN (2, 3)", (self.now - 60 * DAY,))  # outside the period
        self.assertEqual(self.t()["M2"]["state"], "met")

    def test_m7_names_the_answered_gaps_and_stays_no_data(self):
        self.db.q("INSERT INTO ev_proposals VALUES (1, 'mission', 'team', 'answered'), (2, 'mission', 'team', 'proposed'), (3, 'answer', 'agent', 'promoted')")
        x = self.t()["M7"]
        self.assertEqual((x["state"], x["ids"]), ("none", [1])); self.assertIn("1 measured gap answered by a promoted change", x["detail"])  # answered is not held (L5.6 reads the cycles)

    def test_m8_planner_lesson_uses(self):
        q = self.db.q
        q("INSERT INTO ex_recalls VALUES (1, 7, 'workforce'), (2, 7, 'you')"); q("INSERT INTO mx_lessons VALUES (1, 'verified'), (2, 'partial')")
        q("INSERT INTO ex_uses (recall_id, ref, ts) VALUES (1, 'mxl:1', ?), (2, 'mxl:2', ?), (1, 'exp:5', ?)", (self.now, self.now, self.now))  # a person may see an observation
        x = self.t()["M8"]
        self.assertEqual((x["state"], x["value"], x["ids"]), ("met", "100%", []))
        q("INSERT INTO ex_uses (recall_id, ref, ts) VALUES (1, 'mxl:2', ?)", (self.now,))  # an unverified lesson handed to an engine
        x = self.t()["M8"]
        self.assertEqual((x["state"], x["value"], x["ids"]), ("not_met", "50%", [2]))

    def test_m9_a_measured_slope_across_two_promoted_versions(self):
        q, t0 = self.db.q, self.now - 10 * DAY
        ver = lambda comp, src, at: q("INSERT INTO au_versions (agent_id, comp_id, version, source, ts) VALUES (1, ?, 1, ?, ?)", (comp, src, at))
        self.sid = 100
        def bench(comp, score, at, ref="job", suite="h1", job_says=None):
            if ref == "job": self.sid += 1; ref = kept_job(q, comp, self.sid, score if job_says is None else job_says)
            q("INSERT INTO mw_bench (comp_id, comparable, score, ts, suite_hash, evidence_ref) VALUES (?, 1, ?, ?, ?, ?)", (comp, score, at, suite, ref))
        ver(5, "gate #3", t0); ver(5, "trial #4", t0 + 100); ver(5, "trial #4 ended", t0 + 200); ver(5, "edit", t0 + 300)  # one promotion only
        bench(5, 0.5, t0 + 50); bench(5, 0.9, t0 + 400)
        self.assertEqual(self.t()["M9"]["state"], "none")
        ver(5, "gate #4", t0 + 1000)
        bench(5, 0.9, t0 + 1100, ref="sbx:7"); bench(5, 0.9, t0 + 1200, ref=None); bench(5, 0.9, t0 + 1300, suite="h2")  # filed by an agent, by hand, on another suite
        bench(5, 0.9, t0 + 1310, ref="job:999")       # names a job that kept no result
        bench(5, 0.9, t0 + 1320, job_says=0.2)        # the number filed isn't the one the job's own output gave
        self.sid += 1; ref = kept_job(q, 5, self.sid, 0.9)
        q("UPDATE mw_files SET content=replace(content, '0.9', '0.90') WHERE path=?", (f"runs/sbx-{self.sid}/result.json",))  # the kept file was edited afterwards
        bench(5, 0.9, t0 + 1330, ref=ref)
        self.sid += 1; bench(5, 0.9, t0 + 1340, ref=kept_job(q, 5, self.sid, 0.9, status="failed"))  # the job didn't finish cleanly
        self.assertEqual(self.t()["M9"]["state"], "none")
        bench(5, 0.4, t0 + 1400)
        x = self.t()["M9"]
        self.assertEqual((x["state"], x["value"]), ("not_met", None)); self.assertEqual(len(x["ids"]), 2)  # 0.9 under the first, 0.4 under the second
        ver(6, "upgrade", t0); ver(6, "gate #9 rolled back", t0 + 10); ver(6, "gate #9", t0 + 1000)
        bench(6, 0.3, t0 + 50); bench(6, 0.6, t0 + 1100)
        x = self.t()["M9"]
        self.assertEqual((x["state"], x["value"]), ("met", "0.3 → 0.6")); self.assertIn("Team 6", x["detail"])


if __name__ == "__main__":
    unittest.main()
