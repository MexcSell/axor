"""T-4: the four learning-loop steps G5-5 lacked, built to measure and record only (T4_LEARNING_STEPS_SPEC.md).

1. a benefit/cost estimate on a team proposal, from rows (no model);
2. reliability and resource comparison of a trial's two sides, in the trial's evidence, flagged and never blocking;
3. outcome lessons that people read and planners don't (observations);
4. a post-promotion check of the next measured runs against the trial that promoted the change, with no rollback.

Hard rule under test: the promote/verify decision is unchanged, planner readers receive exactly what they received, and nothing is
rolled back by itself. Everything here runs on fixtures (scripted scores, a stand-in for the VM): no real trial has run.
"""
import json, os, sys, time, unittest

os.environ["KNOWLEDGE_INDEX"] = os.environ["KNOWLEDGE_SYNC"] = "0"  # no background loops in tests

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import bus, evolution as evo, missions, orchestrator as orc  # noqa: E402
import test_experience as tx  # noqa: E402  (fixtures, imported as modules so their own tests don't run again here)
import test_g5_mission_lifecycle as tl  # noqa: E402
import test_measured_evaluation as tm  # noqa: E402
import test_mission_delivery as tdel  # noqa: E402
import test_technical_gap as tg  # noqa: E402
import test_vm_runner as tv  # noqa: E402
from test_mission_persistent_evidence import TEAM_ACCOUNT, WID  # noqa: E402

ME, WF = tx.ME, tx.WF
NEW = ("trial_not_better", "trial_rejected", "promotion_holding", "promotion_not_holding", "promotion_inconclusive", "mission_measured")
STATS = {"containers": {"api": {"peak_memory_mb": 412.5, "peak_cpu_percent": 88.0}}, "vm_peak_memory_mb": 900, "cpu_seconds": 41.0, "disk_used_mb": 300,
         "bytes_in": 52_000_000, "bytes_out": 900, "seconds": 131.0, "retries": 0, "oom_kills": 0}


class Rules(unittest.TestCase):
    def test_no_new_outcome_is_one_a_planner_receives(self):
        self.assertEqual(orc.LESSONS_FOR_PLANNERS, ("verified", "trial_verified", "bench_verified"))   # unchanged
        self.assertEqual(set(missions.OBSERVATIONS), set(NEW))
        for o in NEW: self.assertFalse(orc.lesson_for_planners(o), o)

    def test_the_writer_refuses_an_outcome_planners_receive(self):
        for o in orc.LESSONS_FOR_PLANNERS + ("nonsense",):
            with self.assertRaises(ValueError): missions.observation_lesson(None, 1, "k", "t", o)

    def test_the_estimate_arithmetic(self):
        self.assertAlmostEqual(evo._sd([58, 60, 64]), 3.0551, 3)
        self.assertIsNone(evo._sd([60]))
        d = evo._detectable(3.9, 3, 5.0)                      # the validation report's default-policy row: about 10 points, 1 in 15 to 20
        self.assertEqual((d["gain"], d["se_points"]), (10.2, 3.18))
        self.assertTrue(0.04 < d["false_verify"] < 0.08, d)
        self.assertEqual(evo._detectable(3.9, 7, 10.0)["gain"], 13.4)
        self.assertEqual(evo._detectable(0.0, 3, 5.0), {"se_points": 0.0, "gain": 5.0, "false_verify": 0.0, "runs_per_side": 3})
        self.assertEqual((evo._scale([0.5, 0.9]), evo._scale([5, 90])), (100.0, 1.0))


@tv.own_tests
class T4(tg.Held):
    """The fixture team: a technical gap, a person's answer, a trial on the frozen measuring job, a promotion (tg.Held.promoted)."""
    stats = None  # the VM's stats a benchmark's stand-in reports (a dict of overrides), read by benchmark() from the first call in setUp

    def setUp(self):
        super().setUp()
        self.ev.missions = self.mx
        self.events = []
        bus.subscribe(self.events.append)

    def tearDown(self):
        if self.events.append in bus._subs: bus._subs.remove(self.events.append)
        super().tearDown()

    def benchmark(self, score, filed=None, stats=None):
        """tl.Lifecycle.benchmark, with the VM's stats chosen by the test."""
        self.run_no += 1
        st = stats or self.stats
        kw = {"files": {"bench_out/live.json": json.dumps({"score": score, "tasks": 16})}, **({"stats": {**STATS, **st}} if st else {})}
        self.work.runner = tv.FakeRunner(**kw)
        job = self.work._docker_job({"id": WID}, {"netuid": 62}, tv.spec(kind="bench", command="sh bench/run.sh", score_file="bench_out/live.json"),
                                    task=5, run=self.run_no, agent={"id": 2, "name": "Rae"})
        r = self.rel.current(WID)
        row = self.rel.record(WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score if filed is None else filed},
                              task=5, agent=2, run=self.run_no)
        return job, row

    def failed_job(self, at, status="failed", error=None):
        self.db.q("""INSERT INTO mw_sbx (comp_id, run_id, services, command, status, exit_code, started, finished, pod, error)
                     VALUES (?, 99, 'vm-docker', 'docker_job bench sh bench/run.sh', ?, 1, ?, ?, 'pod-x', ?)""", (WID, status, at, at + 5, error))

    def trial(self, base, cand, base_stats=None, cand_stats=None, base_failed=0, cand_failed=0, promote=True, scores=None):
        """tg.Held.promoted with chosen scores and per-side VM stats; the trial ends, and (promote=True) a person promotes."""
        mid = self.sn61()
        self.stats = base_stats
        for s in base: self.benchmark(s)
        for i in range(base_failed): self.failed_job(time.time())
        self.cycle(mid)
        (g,) = self.gaps()
        self.ev.set_experiments(self.owner, WID, tl.evo.OptIn(on=True))
        team = self.me(TEAM_ACCOUNT)
        pid = self.ev.answer(team, g["id"], tl.evo.AnswerIn(agent=2, title="Benchmark before approving", instructions=tl.CAND_TEXT))["id"]
        self.ev.trial_start(team, pid)
        self.release(2)
        self.stats = cand_stats
        for s in cand: self.benchmark(s)
        for i in range(cand_failed): self.failed_job(time.time())
        out = self.ev.trial_end(team, pid)
        if promote: self.ev.promote(team, pid)
        self.stats, self.t = None, time.time()
        return mid, g["id"], pid, team, out

    def ev_row(self, pid): return self.db.q("SELECT * FROM ev_proposals WHERE id=?", (pid,), one=True)
    def obs(self, outcome=None):
        return [dict(x) for x in self.db.q("SELECT * FROM mx_lessons WHERE outcome IN (%s) ORDER BY id" % ",".join("?" * len(NEW if outcome is None else (outcome,))), NEW if outcome is None else (outcome,))]
    def guidance(self): return [x["id"] for x in orc.guidance(TEAM_ACCOUNT, "trial instructions benchmark runs frozen suite promoted")["lessons"]]

    # ---------- schema ----------
    def test_the_new_columns_are_nullable_and_added_once(self):
        cols = {c["name"]: c for c in self.db.q("PRAGMA table_info(ev_proposals)")}
        self.assertIn("estimate", cols); self.assertIn("watch", cols)
        self.db.q("INSERT INTO ev_proposals (user_id, target_kind, target_key, title, status, created) VALUES (7, 'agent', 'hub:1', 'old', 'proposed', 1)")
        old = self.ev._public(self.db.q("SELECT * FROM ev_proposals WHERE title='old'", one=True))          # a row from before: both are null
        self.assertEqual((old["estimate"], old["watch"]), (None, None))
        self.restart()                                                                                       # a second start-up adds nothing and doesn't fail
        self.assertEqual(sum(1 for c in self.db.q("PRAGMA table_info(ev_proposals)") if c["name"] in ("estimate", "watch")), 2)

    # ---------- step 1: estimate ----------
    def test_the_estimate_is_computed_from_rows(self):
        mid = self.sn61()
        for s in (0.58, 0.60, 0.64): self.benchmark(s)
        self.cycle(mid)
        (g,) = self.gaps()
        team = self.me(TEAM_ACCOUNT)
        pid = self.ev.answer(team, g["id"], tl.evo.AnswerIn(agent=2, title="t", instructions=tl.CAND_TEXT))["id"]
        est = self.ev.proposal(team, pid)["estimate"]
        self.assertTrue(est["informational"]); self.assertEqual(est["method"], "from rows, no model")
        self.assertEqual(est["gap"]["source"], "the mission's measure"); self.assertTrue(est["gap"]["comparable_to_trial"])
        self.assertAlmostEqual(est["gap"]["points"], 16.0, 1)                                                # 0.8 against the newest row, 0.64
        self.assertEqual((est["noise"]["scores_used"], est["noise"]["sd_points"]), (3, 3.06))
        self.assertEqual(est["detectable"]["gain"], 9.1)                                                      # 5 + 1.645 x 3.06 x sqrt(2/3)
        c = est["cost"]
        self.assertEqual((c["runs_per_side"], c["margin"], c["candidate_jobs"], c["baseline_jobs_still_needed"], c["baseline_rows_on_current_release"]), (3, 5.0, 3, 0, 3))
        self.assertGreaterEqual(c["jobs_observed"], 3); self.assertIsNotNone(c["job_seconds_mean"]); self.assertIsNone(c["tokens_per_job_mean"])
        self.assertIn("The gap is within what this trial can show", est["note"])                              # a trial that shows 9 points, a gap of 16

    def test_the_estimate_reads_tokens_and_the_floor_from_the_teams_rows(self):
        mid = self.sn61()
        for s in (0.58, 0.60, 0.64): self.benchmark(s)
        if "tokens" not in {c["name"] for c in self.db.q("PRAGMA table_info(mw_runs)")}: self.db.q("ALTER TABLE mw_runs ADD COLUMN tokens INTEGER")
        for i, r in enumerate(self.db.q("SELECT DISTINCT run_id FROM mw_sbx WHERE run_id IS NOT NULL AND services='vm-docker' ORDER BY run_id")):
            self.db.q("INSERT INTO mw_runs (id, comp_id, tokens) VALUES (?, ?, ?)", (r["run_id"], WID, 1000 * (i + 1)))
        self.ev.set_floor(self.owner, WID, evo.FloorIn(runs=7, margin=10))
        self.cycle(mid)
        (g,) = self.gaps()
        est = self.ev._estimate(TEAM_ACCOUNT, self.ev._row(TEAM_ACCOUNT, g["id"]))
        c = est["cost"]
        self.assertEqual((c["runs_per_side"], c["margin"], c["baseline_jobs_still_needed"]), (7, 10.0, 4))   # the Owner's floor, and the baseline rows already there
        self.assertIsNotNone(c["tokens_per_job_mean"]); self.assertEqual(c["expected_tokens"], round(c["tokens_per_job_mean"] * 11))
        self.assertEqual(c["expected_job_seconds"], round(c["job_seconds_mean"] * 11))

    def test_with_no_measurements_the_estimate_says_unknown(self):
        mid = self.sn61()
        self.benchmark(0.60); self.cycle(mid)
        (g,) = self.gaps()
        self.db.q("DELETE FROM mw_bench")
        est = self.ev._estimate(TEAM_ACCOUNT, self.ev._row(TEAM_ACCOUNT, g["id"]))
        self.assertIsNone(est["noise"]["sd_points"]); self.assertIsNone(est["detectable"]); self.assertIn("No estimate", est["note"])

    def test_the_estimate_is_refreshed_when_a_trial_starts_and_decides_nothing(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3, promote=False)
        self.assertEqual(out["status"], "verified")
        self.assertIsNotNone(self.ev_row(pid)["estimate"])
        self.assertEqual(self.ev.promote(team, pid)["status"], "promoted")

    # ---------- step 2: reliability and resources ----------
    def test_both_sides_are_recorded_in_the_evidence_and_the_api(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3, promote=False)
        e = self.ev.proposal(team, pid)["evidence"]
        for side in ("baseline", "candidate"):
            s = e["sides"][side]
            self.assertEqual((s["rows"], s["jobs_read"], s["seconds"]["mean"], s["cpu_seconds"]["mean"], s["peak_memory_mb"]["max"], s["oom_kills"], s["failed_jobs"]),
                             (3, 3, 131.0, 41.0, 900.0, 0, 0), side)
            self.assertEqual(s["bytes_in"]["mean"], 52_000_000.0)
        f = e["flags"]
        self.assertEqual((f["reliability"], f["wall_time"], f["memory"], f["cpu"], f["traffic"], f["oom"], f["any_worse"], f["informational"]), ("same", "same", "same", "same", "same", "same", [], True))
        self.assertEqual(len(e["baseline_jobs"]), 3); self.assertTrue(all(x.startswith("job:") for x in e["candidate_jobs"]))

    def test_worse_reliability_and_resources_are_flagged_and_do_not_block_the_gate(self):
        worse = {"seconds": 400.0, "cpu_seconds": 130.0, "vm_peak_memory_mb": 3000, "bytes_in": 400_000_000, "oom_kills": 1}
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3, cand_stats=worse, cand_failed=2, promote=False)
        e = out["evidence"]
        f = e["flags"]
        self.assertEqual((f["reliability"], f["wall_time"], f["cpu"], f["memory"], f["traffic"], f["oom"]), ("worse",) * 6)
        self.assertEqual(f["any_worse"], ["cpu", "memory", "oom", "reliability", "traffic", "wall_time"])
        self.assertEqual((e["sides"]["candidate"]["failed_jobs"], e["sides"]["baseline"]["failed_jobs"]), (2, 0))
        self.assertEqual(e["sides"]["candidate"]["failure_rate"], 0.4)                                         # 2 failed of 5 bench jobs in its window
        # the decision is what it was: score only
        self.assertEqual((out["status"], e["verified"], e["why"], e["baseline"], e["candidate"], e["delta"]), ("verified", True, [], 60.0, 85.0, 25.0))
        self.assertEqual(self.ev.promote(team, pid)["status"], "promoted")                                     # and a person can promote it

    def test_the_verdict_is_the_same_with_and_without_the_new_record(self):
        """The same scores with equal stats and with worse ones give one verdict; the new keys are the only difference."""
        base = self.trial([0.60] * 3, [0.85] * 3, promote=False)[4]["evidence"]
        self.db.q("DELETE FROM mx_missions"); self.db.q("DELETE FROM mw_bench"); self.db.q("DELETE FROM ev_proposals"); self.db.q("DELETE FROM io_events"); self.db.q("DELETE FROM mx_requests")
        self.db.q("DELETE FROM mw_sbx WHERE status!='done'")
        self.freeze_job(); self.release(1)
        worse = self.trial([0.60] * 3, [0.85] * 3, cand_stats={"vm_peak_memory_mb": 5000}, cand_failed=1, promote=False)[4]["evidence"]
        new = {"sides", "flags", "baseline_jobs", "candidate_jobs"}
        keep = lambda e: {k: v for k, v in e.items() if k not in new | {"baseline_rows", "candidate_rows", "candidate_releases", "baseline_release", "trial"}}
        self.assertEqual(keep(base), keep(worse))
        self.assertEqual(worse["flags"]["memory"], "worse"); self.assertEqual(base["flags"]["memory"], "same")

    def test_a_failure_in_the_comparison_leaves_the_verdict_alone(self):
        def broken(*a, **k): raise RuntimeError("no stats")
        self.ev._sides = broken
        with self.assertLogs("scout.evolution", "ERROR"):
            mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3, promote=False)
        self.assertEqual((out["status"], out["evidence"]["verified"], out["evidence"]["sides_error"]), ("verified", True, "no stats"))
        self.assertNotIn("flags", out["evidence"])

    # ---------- step 3: outcome lessons ----------
    def test_a_trial_that_ended_not_better_leaves_an_observation_planners_never_get(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.61] * 3, promote=False)
        self.assertEqual(out["status"], "not_better")
        (x,) = self.obs("trial_not_better")
        self.assertEqual((x["user_id"], x["kind"], x["mission_id"], x["withdrawn"] if "withdrawn" in x else None), (TEAM_ACCOUNT, "failed", None, None))
        self.assertTrue(x["text"].startswith(f"[ev:{pid}:not_better:"), x["text"])
        for part in ("Observation, not a verified result", f"proposal #{pid}", f"answering gap #{gid} of mission mx:{mid}", "baseline 60 → candidate 61", "releases #1 → 2", "jobs "):
            self.assertIn(part, x["text"])
        self.assertLessEqual(len(x["text"]), 400)
        self.assertEqual(self.guidance(), [])                                                                  # the guidance reader
        ev = self.ev_row(pid)
        self.ev._observe_trial_end(ev, json.loads(ev["evidence"]), json.loads(ev["evidence"])["trial"]["ended"])
        self.assertEqual(len(self.obs("trial_not_better")), 1)                                                 # once per trial end

    def test_an_observation_changes_none_of_the_three_planner_readers_nor_the_handoff(self):
        self.mx.hub = None
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        before = self.guidance()
        self.assertEqual(len(before), 1)                                                                       # the promoted trial's own lesson, as before
        for i, o in enumerate(NEW):
            missions.observation_lesson(self.db, TEAM_ACCOUNT, f"x:{i}", "Trial instructions benchmark runs frozen suite promoted (observation)", o)
        self.assertEqual(self.guidance(), before)                                                              # reader 1: orchestrator.guidance
        m = self.m(mid)
        self.db.q("UPDATE mx_missions SET goal='Trial instructions benchmark runs frozen suite promoted', understanding=? WHERE id=?",
                  (json.dumps({"objective": "trial instructions benchmark runs frozen suite promoted"}), mid))
        flag, missions.mission_intel.ENABLED = missions.mission_intel.ENABLED, False
        try:
            self.assertTrue(self.mx._discover(self.mx._m(mid)))                                                # reader 2: discovery without the Knowledge Hub
        finally: missions.mission_intel.ENABLED = flag
        got = [self.db.q("SELECT outcome FROM mx_lessons WHERE id=?", (x["id"],), one=True)["outcome"] for x in self.mx._m(mid)["discovery"]["lessons"]]
        self.assertTrue(got and set(got) <= {"trial_verified"}, got)
        # the orchestrator's handoff count (a mission's own lessons) and the ledger feed
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE mission_id=? AND outcome IN (%s)" % ",".join("?" * len(NEW)), (mid, *NEW), one=True)["n"], 0)
        self.orc.observe_handoffs()                                                                            # NULL mission ids are tolerated by the knowledge.written feed
        ids = [r["id"] for r in self.db.q("SELECT id FROM mx_lessons WHERE mission_id IS NULL AND outcome IN (%s)" % ",".join("?" * len(NEW)), NEW)]
        self.assertEqual(len(ids), len(NEW))
        for i in ids:                                                                                          # each observation's own event, with no mission to correlate to
            r = self.db.q("SELECT corr, status FROM io_events WHERE kind='knowledge.written' AND ref=?", (f"mxl:{i}",), one=True)
            self.assertIsNotNone(r, i); self.assertIsNone(r["corr"])

    def test_a_person_rejecting_a_trialled_proposal_leaves_an_observation(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3, promote=False)
        self.ev.reject(team, pid, "wait for the next release")
        (x,) = self.obs("trial_rejected")
        self.assertIn("a person rejected", x["text"]); self.assertIn("wait for the next release", x["text"]); self.assertIn("(verified)", x["text"])
        self.assertEqual(self.guidance(), [])

    def test_a_proposal_that_was_never_trialled_leaves_no_lesson_when_rejected(self):
        mid = self.sn61(); self.benchmark(0.60); self.cycle(mid)
        (g,) = self.gaps()
        self.ev.reject(self.me(TEAM_ACCOUNT), g["id"])
        self.assertEqual(self.obs(), [])

    # ---------- step 4: post-promotion comparison ----------
    def settle(self, pid): return self.ev.watch_check(pid)
    def watch(self, pid): return self.ev.proposal(self.me(TEAM_ACCOUNT), pid)["watch"]

    def test_the_watch_opens_with_the_promotion_and_records_what_it_rests_on(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        w = self.watch(pid)
        self.assertEqual((w["state"], w["need"], w["counted"], w["baseline"], w["candidate"], w["margin"], w["scale"], w["informational"]), ("watching", 3, 0, 60.0, 85.0, 5.0, 100.0, True))
        self.assertEqual(len(w["trial_rows"]), 3)

    def test_it_holds_when_the_next_runs_keep_the_gain(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.release(3)                                                                                        # the artifact made under the promoted instructions
        for s in (0.82, 0.84, 0.81):
            self.assertEqual(self.watch(pid)["state"], "watching"); self.benchmark(s); self.settle(pid) if s == 0.81 else None
        w = self.watch(pid)
        self.assertEqual((w["state"], w["counted"], w["mean"], w["vs_baseline"], w["vs_candidate"]), ("holding", 3, 82.3, 22.3, -2.7))
        self.assertEqual(len(w["rows"]), 3); self.assertTrue(all(j.startswith("job:") for j in w["jobs"])); self.assertEqual(w["flags"]["reliability"], "same")
        self.assertEqual(self.ev_row(pid)["status"], "promoted")
        self.assertEqual([x["outcome"] for x in self.obs("promotion_holding")], ["promotion_holding"])
        self.assertIn("promotion.holding", [r["action"] for r in self.db.q("SELECT action FROM ev_audit WHERE target=?", (f"proposal:{pid}",))])
        self.assertTrue([e for e in self.events if e["kind"] == "evolution.watch" and e["state"] == "holding" and e["proposal"] == pid])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE origin='watch'", one=True)["n"], 0)
        self.benchmark(0.10); self.assertEqual(self.settle(pid), 0)                                            # settled stays settled
        self.assertEqual(self.watch(pid)["state"], "holding")

    def not_holding(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        before = self.db.q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"]
        nv = self.db.q("SELECT COUNT(*) n FROM au_versions", one=True)["n"]
        self.release(3)
        for s in (0.58, 0.60, 0.62): self.benchmark(s)
        self.assertEqual(self.settle(pid), 1)
        return mid, gid, pid, team, before, nv

    def test_it_does_not_hold_and_then_a_person_is_asked_but_nothing_is_rolled_back(self):
        mid, gid, pid, team, before, nv = self.not_holding()
        w = self.watch(pid)
        self.assertEqual((w["state"], w["mean"], w["vs_baseline"], w["vs_candidate"]), ("not_holding", 60.0, 0.0, -25.0))
        # no rollback: the promotion, the agent's instructions, the version store and the gap are as they were
        self.assertEqual(self.ev_row(pid)["status"], "promoted")
        self.assertEqual(self.db.q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"], before)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM au_versions", one=True)["n"], nv)
        self.assertEqual(self.db.q("SELECT status FROM ev_proposals WHERE id=?", (gid,), one=True)["status"], "answered")
        self.assertNotIn("proposal.rolled_back", [r["action"] for r in self.db.q("SELECT action FROM ev_audit")])
        self.assertEqual([x["kind"] for x in self.events if x["kind"] == "evolution.watch" and x["state"] == "not_holding"], ["evolution.watch"])
        # a request for a person: one open proposal that names the numbers and can only be read or rejected
        (n,) = [dict(p) for p in self.db.q("SELECT * FROM ev_proposals WHERE origin='watch'")]
        self.assertEqual((n["status"], n["target_key"], n["user_id"], w["opened_proposal"]), ("proposed", f"comp:{WID}", TEAM_ACCOUNT, n["id"]))
        self.assertIn("isn't holding", n["title"]); self.assertIn("+5", json.loads(n["change"])["text"])
        self.assertEqual([x["outcome"] for x in self.obs("promotion_not_holding")], ["promotion_not_holding"])
        self.assertEqual(self.settle(pid), 0)                                                                  # asked once
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE origin='watch'", one=True)["n"], 1)

    def test_the_note_to_a_person_is_refused_by_every_entry_of_the_gate(self):
        mid, gid, pid, team, before, nv = self.not_holding()
        nid = self.watch(pid)["opened_proposal"]
        for name, call in (("run", lambda: self.ev.run(team, nid, evo.RunIn())), ("approve", lambda: self.ev.approve(team, nid)),
                           ("set_benchmark", lambda: self.ev.set_benchmark(team, nid, evo.PatchIn(benchmark_id=None))),
                           ("record_evidence", lambda: self.ev.record_evidence(team, nid, evo.EvidenceIn(baseline=[50], candidate=[90], test_set="x"))),
                           ("trial_start", lambda: self.ev.trial_start(team, nid)), ("promote", lambda: self.ev.promote(team, nid)),
                           ("rollback", lambda: self.ev.rollback(team, nid)), ("answer", lambda: self.ev.answer(team, nid, evo.AnswerIn(agent=2, title="x", instructions="y")))):
            with self.assertRaises(HTTPException, msg=name) as e: call()
            self.assertIn(e.exception.status_code, (400, 409), name)
        self.assertEqual(self.ev_row(nid)["status"], "proposed")
        self.assertEqual(self.ev.reject(team, nid)["status"], "rejected")                                      # a person can dismiss it
        self.assertEqual(self.ev_row(pid)["status"], "promoted")

    def test_rows_that_do_not_count(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.benchmark(0.9)                                                                                    # on the trial's own release, frozen before the promotion
        self.settle(pid); self.assertEqual(self.watch(pid)["counted"], 0)
        self.release(3)
        r = self.rel.current(WID)                                                                              # a number an agent filed: no job behind the score
        self.db.q("INSERT INTO mw_sbx (comp_id, run_id, status, exit_code, started, finished, pod) VALUES (?, 78, 'done', 0, ?, ?, 'pod-78')", (WID, time.time() - 60, time.time()))
        self.rel.record(WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": 0.9}, task=5, agent=2, run=78)
        self.settle(pid); self.assertEqual(self.watch(pid)["counted"], 0)
        self.db.q("UPDATE mw_release SET current=0 WHERE comp_id=?", (WID,))                                   # another suite
        self.db.q("""INSERT INTO mw_release (comp_id, version, commit_ref, sha256, suite, suite_tasks, suite_hash, repeats, frozen, current, image_digest, measure)
                     VALUES (?, 4, '4cd2345ef67890', NULL, 'other', 16, 'h2', 1, ?, 1, ?, ?)""", (WID, time.time(), tv.D1, json.dumps(self.measure)))
        self.benchmark(0.9); self.settle(pid); self.assertEqual(self.watch(pid)["counted"], 0)
        self.assertEqual(self.watch(pid)["state"], "watching")

    def test_fewer_than_n_rows_keep_watching(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.release(3); self.benchmark(0.3); self.benchmark(0.3)
        self.assertEqual(self.settle(pid), 0)
        w = self.watch(pid)
        self.assertEqual((w["state"], w["counted"]), ("watching", 2))
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE origin='watch'", one=True)["n"], 0)

    def test_n_is_a_setting_and_defaults_to_the_trials_runs_per_side(self):
        self.db.setting(f"promotion.watch.runs.comp:{WID}", v="2")
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.assertEqual(self.watch(pid)["need"], 2)
        self.release(3); self.benchmark(0.9); self.benchmark(0.9)
        self.assertEqual(self.settle(pid), 1); self.assertEqual(self.watch(pid)["state"], "holding")

    def test_a_team_that_is_no_longer_opted_in_records_and_opens_nothing(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.release(3)
        for s in (0.1, 0.1, 0.1): self.benchmark(s)
        self.ev.set_experiments(self.owner, WID, tl.evo.OptIn(on=False))
        self.assertEqual(self.settle(pid), 0)
        self.assertEqual((self.watch(pid)["state"], self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE origin='watch'", one=True)["n"]), ("watching", 0))
        self.ev.set_experiments(self.owner, WID, tl.evo.OptIn(on=True))
        self.assertEqual(self.settle(pid), 1)

    def test_a_rollback_by_a_person_ends_the_watch(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.release(3)
        for s in (0.1, 0.1, 0.1): self.benchmark(s)
        self.ev.rollback(team, pid)
        self.assertEqual(self.watch(pid)["state"], "stopped")
        self.assertEqual(self.settle(pid), 0)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE origin='watch'", one=True)["n"], 0)

    def test_a_second_settler_with_a_stale_read_opens_nothing_more(self):
        """The engine's loop and the route can both reach a verdict: the one whose write finds the watch changed does nothing."""
        mid, gid, pid, team, before, nv = self.not_holding()
        stale = self.db.q("SELECT * FROM ev_proposals WHERE id=?", (pid,), one=True)
        old = dict(json.loads(stale["watch"]), state="watching"); old.pop("settled")
        self.db.q("UPDATE ev_proposals SET watch=? WHERE id=?", (json.dumps(old), pid))                        # as the second one read it, before the first settled
        stale = dict(stale, watch=json.dumps(old))
        self.db.q("UPDATE ev_proposals SET watch=? WHERE id=?", (json.dumps(dict(old, state="not_holding")), pid))
        self.assertEqual(self.ev._watch_one(stale, old), 0)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ev_proposals WHERE origin='watch'", one=True)["n"], 1)
        self.assertEqual(len(self.obs("promotion_not_holding")), 1)

    def test_a_failure_in_the_side_numbers_still_records_the_verdict(self):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        def broken(*a, **k): raise RuntimeError("no stats")
        self.ev._side_stats = broken
        self.release(3)
        for s in (0.82, 0.84, 0.81): self.benchmark(s)
        with self.assertLogs("scout.evolution", "ERROR"):
            self.assertEqual(self.settle(pid), 1)
        w = self.watch(pid)
        self.assertEqual((w["state"], w["side_error"], w["flags"]), ("holding", "no stats", None))

    def test_the_default_n_is_the_policys_runs_per_side_not_the_runs_a_trial_happened_to_have(self):
        mid, gid, pid, team, out = self.trial([0.60] * 5, [0.85] * 5)
        self.assertEqual((out["evidence"]["cases"], out["evidence"]["min_cases"], self.watch(pid)["need"]), (5, 3, 3))

    # ---------- review fixes ----------
    def run_watch(self, scores, base=None):
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.release(3)
        for s in scores: self.benchmark(s)
        return mid, gid, pid, team

    def watch_notes(self): return self.db.q("SELECT * FROM ev_proposals WHERE origin='watch'")

    def test_m1_a_shortfall_the_spread_explains_is_inconclusive_and_asks_nobody(self):
        mid, gid, pid, team = self.run_watch((0.50, 0.70, 0.62))                                  # mean 60.7: below 65, but the runs spread over 20 points
        self.assertEqual(self.settle(pid), 1)
        w = self.watch(pid)
        self.assertEqual((w["state"], w["vs_baseline"]), ("inconclusive", 0.7))
        self.assertGreater(w["se"], 5)
        self.assertEqual(len(self.watch_notes()), 0)
        self.assertEqual(len(self.obs("promotion_inconclusive")), 1); self.assertEqual(len(self.obs("promotion_not_holding")), 0)
        self.assertEqual(self.ev_row(pid)["status"], "promoted"); self.assertIsNone(w["pending_notify"])

    def test_m1_a_clear_shortfall_is_not_holding_and_the_text_does_not_blame_the_promotion(self):
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62))
        self.settle(pid)
        (n,) = [dict(x) for x in self.watch_notes()]
        self.assertEqual(self.watch(pid)["state"], "not_holding")
        self.assertTrue(n["title"].startswith(f"The measured gain after promotion #{pid} isn't holding"), n["title"])
        self.assertIn("The measured gain isn't holding", json.loads(n["change"])["text"])
        self.assertIn("doesn't say the promotion caused it", n["hypothesis"]); self.assertNotIn("regress", n["title"].lower())
        self.assertIsNone(self.watch(pid)["confounded"]); self.assertNotIn("Other changes", json.loads(n["change"])["text"])

    def test_m1_another_change_to_the_team_in_the_window_is_recorded_as_confounded(self):
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62))
        a = self.db.q("SELECT * FROM mw_agents WHERE id=2", one=True)
        time.sleep(0.01)
        self.ev.teams.upgrade.gate_apply(a, (a["instructions"] or "") + " also this", "manual edit", "someone")
        self.settle(pid)
        w = self.watch(pid)
        self.assertEqual(w["state"], "not_holding"); self.assertEqual(len(w["confounded"]), 1)
        (n,) = [dict(x) for x in self.watch_notes()]
        self.assertIn("Other changes were made to this team's agents in the same window", json.loads(n["change"])["text"])
        self.assertIn("Other changes", self.obs("promotion_not_holding")[0]["text"])

    def test_m3_a_failed_proposal_is_retried_and_exactly_one_opens(self):
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62))
        real, calls = self.ev.propose, []
        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1: raise RuntimeError("database busy")
            return real(*a, **k)
        self.ev.propose = flaky
        with self.assertLogs("scout.evolution", "ERROR"):
            self.assertEqual(self.settle(pid), 1)
        w = self.watch(pid)
        self.assertEqual((w["state"], len(self.watch_notes())), ("not_holding", 0))
        self.assertEqual((w["pending_notify"]["proposal"], w["pending_notify"]["announce"], w["pending_notify"]["attempts"], w["pending_notify"]["error"]), (True, False, 1, "database busy"))
        self.assertEqual(len(self.obs("promotion_not_holding")), 1)                              # what was done stays done
        self.assertEqual(self.settle(pid), 0)                                                    # the next round retries it
        self.assertEqual(len(self.watch_notes()), 1); self.assertIsNone(self.watch(pid)["pending_notify"])
        self.assertEqual(self.watch(pid)["opened_proposal"], self.watch_notes()[0]["id"])
        self.ev.watch_check(); self.ev.watch_check()
        self.assertEqual((len(self.watch_notes()), len(self.obs("promotion_not_holding")), len(calls)), (1, 1, 2))
        self.assertEqual(len([r for r in self.db.q("SELECT action FROM ev_audit WHERE action='promotion.not_holding'")]), 1)

    def test_m3_a_notification_gives_up_after_its_tries_and_says_so(self):
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62))
        def broken(*a, **k): raise RuntimeError("always")
        self.ev.propose = broken
        with self.assertLogs("scout.evolution", "ERROR"):
            for _ in range(evo.WATCH_NOTIFY_TRIES + 3): self.ev.watch_check()
        pn = self.watch(pid)["pending_notify"]
        self.assertEqual((pn["attempts"], pn["failed"], pn["error"]), (evo.WATCH_NOTIFY_TRIES, True, "always"))
        self.assertEqual([r["action"] for r in self.db.q("SELECT action FROM ev_audit WHERE action='promotion.notify_failed'")], ["promotion.notify_failed"])   # once, visible
        self.assertTrue([e for e in self.events if e["kind"] == "evolution.watch" and e.get("notify_failed")])

    def test_m3_an_overlapping_caller_does_not_propose_a_second_time(self):
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62))
        real, inner = self.ev.propose, []
        def wrapped(*a, **k):
            if not inner:
                inner.append(1); self.ev._notify(pid)                                                    # a second caller arrives while the first is inside propose
            return real(*a, **k)
        self.ev.propose = wrapped
        self.assertEqual(self.settle(pid), 1)
        self.assertEqual(len(self.watch_notes()), 1)
        self.assertIsNone(self.watch(pid)["pending_notify"])

    def test_m3_a_crash_after_propose_is_retried_without_a_second_proposal(self):
        class Crash(BaseException): pass
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62))
        real = self.ev.propose
        def crashing(*a, **k):
            real(*a, **k); raise Crash()                                                                 # the proposal exists; the process dies before it is recorded
        self.ev.propose = crashing
        with self.assertRaises(Crash): self.settle(pid)
        self.ev.propose = real
        self.assertEqual(len(self.watch_notes()), 1)
        self.assertTrue(self.watch(pid)["pending_notify"]["proposal"])
        self.ev._notify(pid)                                                                              # the claim is fresh: nobody else touches it
        self.assertEqual(len(self.watch_notes()), 1); self.assertTrue(self.watch(pid)["pending_notify"])
        self.db.setting(f"promotion.watch.claim_minutes.comp:{WID}", v="0.0001"); time.sleep(0.05)       # the claim is stale now
        self.ev.watch_check()
        self.assertEqual(len(self.watch_notes()), 1)                                                      # found, not proposed again
        self.assertEqual((self.watch(pid)["opened_proposal"], self.watch(pid)["pending_notify"]), (self.watch_notes()[0]["id"], None))
        self.assertEqual(len(self.obs("promotion_not_holding")), 1)
        self.assertEqual(len(self.db.q("SELECT 1 FROM ev_audit WHERE action='promotion.not_holding'")), 1)

    def test_m1_too_little_evidence_is_inconclusive_not_not_holding(self):
        self.db.setting(f"promotion.watch.runs.comp:{WID}", v="1")                                       # one new run: no spread
        mid, gid, pid, team = self.run_watch((0.30,)); self.settle(pid)
        self.assertEqual((self.watch(pid)["state"], len(self.watch_notes())), ("inconclusive", 0))

    def test_m1_no_spread_at_all_is_inconclusive(self):
        mid, gid, pid, team = self.run_watch((0.30, 0.30, 0.30)); self.settle(pid)                       # the trial's baseline runs and these all agree: a standard error of 0
        w = self.watch(pid)
        self.assertEqual((w["state"], w["se"], w["vs_baseline"]), ("inconclusive", 0.0, -30.0))
        self.assertEqual(len(self.watch_notes()), 0)

    def test_l1_a_stale_progress_write_cannot_unsettle_a_watch(self):
        mid, gid, pid, team = self.run_watch((0.82, 0.84))
        stale = self.db.q("SELECT * FROM ev_proposals WHERE id=?", (pid,), one=True)
        stale_w = json.loads(stale["watch"])
        self.benchmark(0.81); self.assertEqual(self.settle(pid), 1)                              # settled meanwhile
        real = self.ev._backed_rows
        self.ev._backed_rows = lambda *a, **k: real(*a, **k)[:1]                                 # the stale reader saw one row
        self.assertEqual(self.ev._watch_one(stale, stale_w), 0)
        self.assertEqual(self.watch(pid)["state"], "holding")

    def test_l2_a_failure_the_platform_caused_is_not_counted_against_a_side(self):
        for err, plat in (("Stopped by a server restart (its last checkpoint is kept)", 1), ("the benchmark script raised: score file missing", 0)):
            self.db.q("DELETE FROM mx_missions"); self.db.q("DELETE FROM mw_bench"); self.db.q("DELETE FROM ev_proposals"); self.db.q("DELETE FROM io_events"); self.db.q("DELETE FROM mx_requests")
            self.db.q("DELETE FROM mw_sbx WHERE status!='done'"); self.freeze_job(); self.release(1)
            mid = self.sn61()
            for _ in range(3): self.benchmark(0.60)
            self.cycle(mid); (g,) = self.gaps()
            self.ev.set_experiments(self.owner, WID, tl.evo.OptIn(on=True))
            team = self.me(TEAM_ACCOUNT)
            pid = self.ev.answer(team, g["id"], tl.evo.AnswerIn(agent=2, title="t", instructions=tl.CAND_TEXT + str(plat)))["id"]
            self.ev.trial_start(team, pid); self.release(2)
            for _ in range(3): self.benchmark(0.85)
            self.failed_job(time.time(), "error" if plat else "failed", err)
            c = self.ev.trial_end(team, pid)["evidence"]["sides"]["candidate"]
            self.assertEqual((c["platform_failures"], c["failed_jobs"]), (plat, 1 - plat), err)
            self.assertIn("time window", c["attribution"])

    def test_l2_the_watchs_new_side_has_the_trials_window_shape(self):
        mid, gid, pid, team = self.run_watch((0.82, 0.84, 0.81)); self.settle(pid)
        w = self.watch(pid)
        self.assertEqual(w["side"]["window"][0], w["since"]); self.assertGreaterEqual(w["side"]["window"][1], w["since"])

    def test_l3_the_numbers_come_first_and_survive_the_clip(self):
        long = "A very long title for a change to the agent's instructions, written to push the provenance far past the end of the lesson text " * 1
        mid = self.sn61()
        for _ in range(3): self.benchmark(0.60)
        self.cycle(mid); (g,) = self.gaps()
        self.ev.set_experiments(self.owner, WID, tl.evo.OptIn(on=True))
        team = self.me(TEAM_ACCOUNT)
        pid = self.ev.answer(team, g["id"], tl.evo.AnswerIn(agent=2, title=long[:160], instructions=tl.CAND_TEXT))["id"]
        self.ev.trial_start(team, pid); self.release(2)
        for _ in range(3): self.benchmark(0.61)
        self.ev.trial_end(team, pid)
        (x,) = self.obs("trial_not_better")
        self.assertLessEqual(len(x["text"]), 400)
        self.assertIn("baseline 60 → candidate 61 on 3 runs a side (margin 5)", x["text"])
        self.assertLess(x["text"].index("baseline 60"), x["text"].index("proposal #"))                      # the result first, the provenance after
        self.ev.reject(team, pid, "n" * 300)
        (y,) = self.obs("trial_rejected")
        self.assertLessEqual(len(y["text"]), 400); self.assertIn("baseline 60 → candidate 61 on 3 runs a side", y["text"]); self.assertLess(y["text"].index("baseline 60"), y["text"].index("proposal #"))

    def test_l3_the_watch_lesson_leads_with_the_verdict(self):
        mid, gid, pid, team = self.run_watch((0.58, 0.60, 0.62)); self.settle(pid)
        (x,) = self.obs("promotion_not_holding")
        self.assertTrue(x["text"].startswith(f"[ev:{pid}:watch] Observation, not a verified result: after promotion #{pid} the next 3 measured runs: not holding. mean 60.0"), x["text"])

    def test_l4_the_since_filter_is_in_the_query(self):
        mid, gid, pid, team = self.run_watch((0.82, 0.84, 0.81))
        comp = WID
        self.assertEqual(self.ev._backed_rows(comp, None, 200, since=time.time() + 100), [])
        got = self.ev._backed_rows(comp, None, 3, since=self.watch(pid)["since"])
        self.assertEqual(len(got), 3); self.assertTrue(all(r["ts"] >= self.watch(pid)["since"] for r in got))       # three, though older rows exist: the limit is on the filtered rows

    def test_l4_a_watch_with_no_verdict_expires_and_opens_nothing(self):
        mid, gid, pid, team = self.run_watch((0.82,))
        self.db.setting(f"promotion.watch.days.comp:{WID}", v="0.000001")                       # the limit, a setting (default 30 days)
        time.sleep(0.2)
        self.assertEqual(self.settle(pid), 1)
        w = self.watch(pid)
        self.assertEqual(w["state"], "expired"); self.assertIn("within 1e-06 days", w["why"]); self.assertEqual(len(self.watch_notes()), 0)
        self.assertEqual(self.ev_row(pid)["status"], "promoted")

    def test_l5_the_dedupe_is_one_statement(self):
        seen, entered = [], []
        real, real_tx = self.db.q, self.db.tx
        def spy(sql, *a, **k): seen.append(sql); return real(sql, *a, **k)
        import contextlib
        @contextlib.contextmanager
        def counting():
            entered.append(1)
            with real_tx(): yield
        self.db.q, self.db.tx = spy, counting
        try:
            a = missions.observation_lesson(self.db, 7, "k:1", "first", "trial_not_better")
            b = missions.observation_lesson(self.db, 7, "k:1", "second", "trial_not_better")
        finally: self.db.q, self.db.tx = real, real_tx
        self.assertTrue(a); self.assertIsNone(b)
        self.assertEqual([x for x in seen if "mx_lessons" in x and "sqlite_master" not in x and "INSERT" not in x], [])           # no separate existence check to race with
        self.assertTrue(all("NOT EXISTS" in x for x in seen if "INSERT" in x))
        self.assertEqual(entered, [1, 1])                                                                                      # each write ran inside db.tx()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE text LIKE '[k:1]%'", one=True)["n"], 1)

    def test_a_failure_in_the_watch_never_undoes_the_promotion(self):
        def broken(*a, **k): raise RuntimeError("no watch")
        self.ev._watch_open = broken
        with self.assertLogs("scout.evolution", "ERROR"):
            mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.assertEqual(self.ev_row(pid)["status"], "promoted"); self.assertIsNone(self.ev_row(pid)["watch"])

    def test_the_whole_loop_leaves_planners_with_one_lesson(self):
        mid, gid, pid, team, before, nv = self.not_holding()
        (x,) = [r for r in self.db.q("SELECT id, outcome FROM mx_lessons WHERE mission_id=?", (mid,))]
        self.assertEqual(x["outcome"], "trial_verified")
        self.assertEqual(self.guidance(), [x["id"]])                                                           # as in test_trial_lesson: only the promoted trial's lesson

    def test_a_watch_numbers_come_from_the_same_scale_as_the_trial(self):
        """0-1 scores in the rows, 0-100 points in the evidence: the watch applies the trial's scale, so a holding promotion reads as holding."""
        mid, gid, pid, team, out = self.trial([0.60] * 3, [0.85] * 3)
        self.assertEqual(self.watch(pid)["scale"], 100.0)
        self.release(3)
        for s in (0.86, 0.86, 0.86): self.benchmark(s)
        self.settle(pid)
        self.assertEqual((self.watch(pid)["state"], self.watch(pid)["mean"]), ("holding", 86.0))


@tv.own_tests
class Recall(tm.Closing, tx.Exp):
    """Reader 3: experience recall by an engine or an agent, and Mission Control's discovery through the Knowledge Hub. One row of each new
    outcome, beside a promoted trial's lesson as the control: planners get the control and none of the observations; a person gets all."""
    def setUp(self):
        super().setUp()
        self.db.q("DELETE FROM mx_lessons")
        self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (10, 7, 2, 'worked', ?, 'trial_verified', ?)",
                  ("Enroll the validator before you start the miner (control)", time.time()))
        for i, o in enumerate(NEW):
            self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (?, 7, NULL, 'strategy', ?, ?, ?)",
                      (20 + i, f"Enroll the validator before you start the miner (observation {o})", o, time.time()))

    def refs(self, actor, n=12): return [h["ref"] for h in self.K.recall(ME, "enroll the validator before the miner", n, actor, "", f"ctx:{actor}")]

    def test_planners_get_the_control_and_no_observation_and_a_person_gets_all(self):
        self.embed()
        for actor in ("missions", "workforce", "teams:5"):
            refs = self.refs(actor)
            self.assertIn("mxl:10", refs, actor)
            for i in range(len(NEW)): self.assertNotIn(f"mxl:{20 + i}", refs, actor)
        self.assertFalse(self.db.q("SELECT 1 FROM ex_uses WHERE ref IN ('mxl:20','mxl:21','mxl:22','mxl:23','mxl:24','mxl:25')"))   # never handed out, never counted
        hits = {r["ref"] for r in self.K._exp_rows(7)}                                                      # a person's own view
        self.assertTrue({f"mxl:{20 + i}" for i in range(len(NEW))} <= hits, sorted(hits))
        self.assertFalse({f"mxl:{20 + i}" for i in range(len(NEW))} & {r["ref"] for r in self.K._exp_rows(7, planner=True)})

    def test_m2_observations_cannot_push_a_verified_lesson_out_of_the_planner_window(self):
        for i in range(450):                                                                                  # newer than the control, more than PER_SOURCE
            self.db.q("INSERT INTO mx_lessons (id, user_id, mission_id, kind, text, outcome, created) VALUES (?, 7, NULL, 'strategy', ?, 'trial_not_better', ?)",
                      (1000 + i, f"Enroll the validator before you start the miner (note {i})", time.time()))
        self.embed()
        for actor in ("missions", "workforce", "teams:5"): self.assertIn("mxl:10", self.refs(actor, 20), actor)
        rows = self.K._exp_rows(7, planner=True)
        self.assertIn("mxl:10", [r["ref"] for r in rows]); self.assertFalse([r for r in rows if r["outcome"] == "trial_not_better"])
        self.assertTrue([r for r in self.K._exp_rows(7) if r["outcome"] == "trial_not_better"])               # a person's view is as it was

    def test_discovery_through_the_knowledge_hub(self):
        self.embed()
        class Hub: knowledge, llm = self.K, None
        M = missions.Missions(self.db, hub=Hub(), wf=WF(), ia=None, mw=None)
        self.db.q("INSERT INTO mx_missions (id, user_id, title, goal, status, understanding, created) VALUES (40, 7, 'Validator signup', 'Enroll the validator before you start the miner', 'running', ?, ?)",
                  (json.dumps({"objective": "validator enrollment"}), time.time()))
        flag, missions.mission_intel.ENABLED = missions.mission_intel.ENABLED, False
        try: self.assertTrue(M._discover(M._m(40)))
        finally: missions.mission_intel.ENABLED = flag
        self.assertEqual([x["id"] for x in M._m(40)["discovery"]["lessons"]], [10])


@tv.own_tests
class Delivered(tdel.Delivery):
    """Step 3, the persistent mission's delivery: the measured values as an observation, beside the deliver lesson that is untouched."""
    def test_delivery_adds_an_observation_without_a_mission_id(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.approve(mid, r); self.process()
        (ls,) = self.lessons(mid)
        self.assertEqual((ls["kind"], ls["outcome"]), ("worked", "verified"))                                  # the deliver lesson, as before
        (o,) = [dict(x) for x in self.db.q("SELECT * FROM mx_lessons WHERE outcome='mission_measured'")]
        self.assertIsNone(o["mission_id"]); self.assertTrue(o["text"].startswith(f"[mx:{mid}:measured] Observation"), o["text"])
        self.assertIn("chain_rank", o["text"])
        self.assertFalse(orc.lesson_for_planners(o["outcome"]))
        self.process(); self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_lessons WHERE outcome='mission_measured'", one=True)["n"], 1)


if __name__ == "__main__":
    unittest.main()
