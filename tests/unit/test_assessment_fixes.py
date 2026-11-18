"""The 2026-11-18 assessment's three code fixes (docs/architecture/stabilization/ARCHITECTURAL_DECISIONS.md, D-041).

1. A score is measured or it is self-reported. Team 23's mock said 0.81 where the official scorer gave 0.037, and plans, reviews
   and reports were built on the mock. Every team prompt now carries the rule, and a figure no job's output file gave is labelled
   self-reported where agents and people read results. What counts as a measurement is unchanged (D-034, C5-5: the mission's
   reader already reads a typed number on a measuring release as unverifiable).
2. Blocked tasks count when follow-ups are rationed. A run that ended blocked and filed follow-ups, whose runs ended blocked in
   turn, grew team 23's board to 182 blocked tasks: follow-ups are one per run at the backlog cap and none at twice the cap.
   The Director's plan hold is unchanged.
3. A mission's reviewer is independent only when its model did none of the work. A team's runs are routed one by one, so the
   models that actually ran them are avoided and compared, not only the one the allocation named.
"""
import os, sys, tempfile, time, types, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_autoloop, mining_work, missions  # noqa: E402
from app.auth import AuthDB  # noqa: E402
import test_measuring_job as tm  # noqa: E402  (as modules, so their own tests don't run again here)
import test_mission_persistent_evidence as tp  # noqa: E402
import test_vm_runner as tv  # noqa: E402


class Db(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        try: self.db.db.close()  # on Postgres an AuthDB holds a connection for as long as it lives (PX-R13)
        except Exception: pass   # noqa: BLE001
        self.tmp.cleanup()


# ---------- 1: measured or self-reported ----------
class ScoreRule(unittest.TestCase):
    def test_every_team_prompt_carries_the_rule(self):
        w = object.__new__(mining_work.Work)
        w.m = types.SimpleNamespace(_title=lambda c: "BEX")
        rules = w._rules({"netuid": 61})
        self.assertTrue(rules.startswith("Ground rules: you work for the user, who mines SN61 BEX."))
        self.assertTrue(rules.endswith(mining_work.SCORE_RULE))
        for words in ("official scorer", "self-reported", "never plan, approve or report an improvement on it"):
            self.assertIn(words, mining_work.SCORE_RULE)
        self.assertNotIn("{", mining_work.SCORE_RULE)  # it is appended after the ground rules were formatted


@tv.own_tests
class SelfReported(tm.Fixture, tv.Board):
    def setUp(self):
        super().setUp(); self.seed()
        self.ref, self.ref_run = self.job_run()  # the official measuring job, as a person ran it once
        self.freeze_measuring(self.ref)

    def test_a_typed_score_is_told_it_is_self_reported(self):
        r = self.file(run=999, score=0.81)  # run 999 ran no job: the agent typed its mock's figure
        self.assertEqual((r["score_source"], r["score"]), ("filed", 0.81))
        self.assertIn("The score is self-reported (no job's output file gave it)", r["note"])
        self.assertIn("never the official result", r["note"])

    def test_the_measuring_jobs_own_score_still_counts(self):
        r = self.file(self.ref_run)
        self.assertEqual((r["comparable"], r["score_source"]), (True, "job_output"))
        self.assertNotIn("self-reported", r["note"])

    def test_results_say_which_scores_the_measuring_job_gave(self):
        self.file(self.ref_run); self.file(run=999, score=0.81)
        typed, measured = self.rel.results(tp.WID)["results"][:2]  # newest first
        self.assertEqual((typed["source"], typed["score"]), ("self_reported", 0.81))
        self.assertEqual((measured["source"], measured["comparable"]), ("measuring_job", True))
        self.assertIn("the release's measuring job wrote", self.file(self.ref_run)["note"])

    def test_a_mock_jobs_score_is_never_the_measuring_jobs(self):
        self.w.runner = tv.FakeRunner(files={"bench_out/live.json": '{"score": 0.826, "tasks": 16}'})
        _, run = self.job_run(command="sh bench/mock.sh")  # the team's own validator, run as a VM job with a score file
        r = self.file(run, score=0.826)
        self.assertIn("self-reported", r["note"])           # record and results agree
        self.assertEqual(self.rel.results(tp.WID)["results"][0]["source"], "self_reported")


@tv.own_tests
class NoMeasuringJob(tm.Fixture, tv.Board):
    """Team 23 today: no release with a measuring job. A mock run as a VM job wrote its file: that is a job's score, not official."""
    def setUp(self):
        super().setUp(); self.seed()

    def test_a_jobs_score_without_a_measuring_job_is_not_called_official(self):
        self.w.runner = tv.FakeRunner(files={"bench_out/live.json": '{"score": 0.826, "tasks": 16}'})
        _, run = self.job_run(command="sh bench/mock.sh")
        r = self.file(run, score=0.826)
        self.assertEqual(r["score_source"], "job_output")
        self.assertIn("nothing shows the job ran the official scorer", r["note"])
        self.assertEqual(self.rel.results(tp.WID)["results"][0]["source"], "job_output")  # not "measuring_job"


# ---------- 2: follow-ups and blocked tasks ----------
class FollowupRoom(Db):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("CREATE TABLE mw_comps (id INTEGER PRIMARY KEY, budget INTEGER, parallel INTEGER)")
        q("""CREATE TABLE ml_policy (comp_id INTEGER PRIMARY KEY, reserve REAL, retries INTEGER, task_cap INTEGER, total_cap INTEGER,
             queue_cap INTEGER, backlog_cap INTEGER, updated REAL, mode TEXT)""")
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, status TEXT, agent_id INTEGER, hold TEXT)")
        q("INSERT INTO mw_comps (id, budget, parallel) VALUES (23, 0, 6)")  # six at once: the automatic cap is 24
        self.loop = object.__new__(mining_autoloop.Loop)
        self.loop.db = self.db

    def tasks(self, status, n, agent=1):
        for _ in range(n): self.db.q("INSERT INTO mw_tasks (comp_id, status, agent_id) VALUES (23, ?, ?)", (status, agent))

    def test_blocked_tasks_count(self):
        self.assertEqual(self.loop.policy(self.loop._comp(23))["backlog_cap"], 24)
        self.assertEqual(self.loop.followup_room(23), 99)             # an empty board
        self.tasks("blocked", 23); self.assertEqual(self.loop.followup_room(23), 99)
        self.tasks("blocked", 1); self.assertEqual(self.loop.followup_room(23), 1)   # 24 wait for an answer: one per run
        self.tasks("queued", 23); self.assertEqual(self.loop.followup_room(23), 1)   # 47 open or blocked
        self.tasks("working", 1); self.assertEqual(self.loop.followup_room(23), 0)   # 48 = twice the cap: none

    def test_team_23s_board_stops_growing(self):
        self.tasks("blocked", 182); self.tasks("todo", 20); self.tasks("queued", 4)  # 2026-11-18, about 01:15 UTC
        self.assertEqual(self.loop.followup_room(23), 0)
        self.db.q("UPDATE mw_tasks SET status='done' WHERE status='blocked' AND id IN (SELECT id FROM mw_tasks WHERE status='blocked' LIMIT 170)")
        self.assertEqual(self.loop.followup_room(23), 1)              # 12 blocked + 24 open: answered down to under twice the cap

    def test_the_directors_plan_hold_does_not_count_them(self):
        self.tasks("blocked", 182)
        self.assertEqual(self.loop._backlog(23), 0)                   # what plan_held reads: the Director may still plan a way out
        self.assertEqual(self.loop._blocked(23), 182)

    def test_done_tasks_and_no_cap_change_nothing(self):
        self.tasks("done", 500); self.assertEqual(self.loop.followup_room(23), 99)
        self.db.q("INSERT INTO ml_policy (comp_id, backlog_cap) VALUES (23, 0)")  # the cap switched off
        self.tasks("blocked", 500); self.assertEqual(self.loop.followup_room(23), 99)


class FollowupsNotAdded(Db):
    """mining_work._followups with no room: nothing is added and the board's log says why, once."""
    def test_no_room_adds_nothing_and_says_so(self):
        q = self.db.q
        q("""CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, detail TEXT, status TEXT, priority TEXT,
             agent_id INTEGER, due TEXT, origin TEXT, created REAL, updated REAL, mission TEXT)""")
        w = object.__new__(mining_work.Work)
        w.db, events = self.db, []
        w.loop = types.SimpleNamespace(followup_room=lambda wid: 0)
        w._by_name = lambda wid: {}
        w._open = lambda wid: 206
        w.mission_of_origin = lambda origin: None
        w._event = lambda wid, kind, text, **k: events.append(text)
        n = w._followups({"id": 23}, {"id": 5, "name": "Rosa", "head": 0, "lead": 0}, 3611,
                         [{"title": "Capture again"}, {"title": "Ask for a custodian"}])
        self.assertEqual(n, 0)
        self.assertEqual(q("SELECT COUNT(*) n FROM mw_tasks", one=True)["n"], 0)
        self.assertEqual(len(events), 1)
        self.assertIn("Rosa's 2 follow-ups not added", events[0]); self.assertIn("blocked", events[0])
        self.assertEqual(w._followups({"id": 23}, {"id": 5, "name": "Rosa", "head": 0, "lead": 0}, 3611, []), 0)
        self.assertEqual(len(events), 1)  # nothing to add: nothing said


# ---------- 3: the reviewer's model did none of the work ----------
class WorkerModels(Db):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("CREATE TABLE mw_tasks (id INTEGER PRIMARY KEY, comp_id INTEGER, mission TEXT)")
        q("CREATE TABLE mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, kind TEXT, model TEXT, mission TEXT)")
        q("CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT, kind TEXT, model TEXT)")
        q("INSERT INTO mw_tasks (id, comp_id, mission) VALUES (1, 23, 'mx:9'), (2, 23, 'mx:9'), (3, 23, NULL), (4, 23, 'mx:8')")
        for task, kind, model, mission in ((1, "task", "terminal:fable", None), (2, "task", "codex:gpt-6.1-terra", None), (None, "plan", "terminal:opus", "mx:9"),
                                           (3, "task", "terminal:haiku", None),      # the team's own board work: not this mission's
                                           (4, "task", "codex:gpt-6-astra", None),   # another mission's task
                                           (1, "task", None, None)):                 # a run that never got a model
            q("INSERT INTO mw_runs (comp_id, task_id, kind, model, mission) VALUES (23, ?, ?, ?, ?)", (task, kind, model, mission))
        q("INSERT INTO mw_runs (comp_id, task_id, kind, model) VALUES (24, 1, 'task', 'terminal:sonnet')")  # another team
        for kind, model in (("understand", "terminal:opus"), ("verify", "codex:gpt-6.1-sol"), ("execute", "openrouter:x")):
            q("INSERT INTO ac_runs (ref, kind, model) VALUES ('mx:9', ?, ?)", (kind, model))
        self.mx = object.__new__(missions.Missions)
        self.mx.db = self.db
        self.m = {"id": 9, "team": 23, "allocation": {"model": "terminal:fable"}}

    def test_the_models_that_ran_the_missions_work(self):
        self.assertEqual(self.mx._worker_models(self.m), {"terminal:fable", "codex:gpt-6.1-terra", "terminal:opus", "openrouter:x"})

    def test_without_a_team_only_the_ledger_and_the_allocation(self):
        self.assertEqual(self.mx._worker_models({"id": 9, "team": None, "allocation": None}), {"terminal:opus", "openrouter:x"})
        self.assertEqual(self.mx._worker_models({"id": 77, "team": None, "allocation": {"model": "a:b"}}), {"a:b"})

    def test_an_unreadable_ledger_leaves_the_allocations_model(self):
        self.db.q("DROP TABLE mw_tasks")
        self.assertEqual(self.mx._worker_models(self.m), {"terminal:fable"})

    def test_the_fallback_pick_avoids_every_worker_model(self):
        pool = [{"model": "terminal:fable", "tier": 3, "price": 1.0}, {"model": "codex:gpt-6.1-terra", "tier": 3, "price": 1.0},
                {"model": "terminal:sonnet", "tier": 2, "price": 0.5}]
        self.mx._pool = lambda uid: pool
        self.assertEqual(self.mx._model(4, {"terminal:fable", "codex:gpt-6.1-terra"})[0], "terminal:sonnet")
        self.assertEqual(self.mx._model(4, "terminal:fable")[0], "codex:gpt-6.1-terra")  # one model, as before
        self.assertEqual(self.mx._model(4)[0], "terminal:fable")
        self.assertEqual(self.mx._model(4, {p["model"] for p in pool})[0], "terminal:fable")  # nothing else in the pool: the strongest

    def test_a_reviewer_that_ran_a_task_is_not_independent(self):
        """_verify end to end on a stub: the allocation names fable, a task ran on terra, the reviewer comes back as terra."""
        mx, seen = self.mx, {}
        m = {**self.m, "goal": "g", "understanding": {"objective": "o", "criteria": ["c1"]}, "engine": "workforce", "title": "t", "user_id": 4}
        mx._collect = lambda m: {"text": "the deliverable"}
        mx._set = lambda mid, **kw: seen.update(kw)
        mx._event = lambda *a, **k: None
        mx._success_basis = lambda m, v: {"level": "agent_reported"}
        self.addCleanup(setattr, missions.orchestrator, "snapshot", missions.orchestrator.snapshot)
        missions.orchestrator.snapshot = lambda *a, **k: None
        self.addCleanup(setattr, missions.agent_core, "score", missions.agent_core.score)
        missions.agent_core.score = lambda *a, **k: None

        def ask(m, stage, schema, name, prompt, avoid=None, **k):
            seen["avoid"] = set(avoid)
            return {"results": [{"criterion": "c1", "status": "met", "evidence": "e"}]}, seen["reviewer"]
        mx._ask = ask
        seen["reviewer"] = "codex:gpt-6.1-terra"
        mx._verify(m)
        self.assertIn("codex:gpt-6.1-terra", seen["avoid"])
        v = seen["verification"]
        self.assertEqual((v["model"], v["independent"]), ("codex:gpt-6.1-terra", False))  # before: True (it isn't the allocation's fable)
        self.assertEqual(v["worker_models"], sorted(self.mx._worker_models(self.m)))
        seen["reviewer"] = "terminal:sonnet"
        mx._verify(m)
        self.assertEqual(seen["verification"]["independent"], True)


if __name__ == "__main__":
    unittest.main()
