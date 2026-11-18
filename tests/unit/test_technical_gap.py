"""IC-7 revision 2 (decided under the Owner's delegation of 2026-11-13 13:35 UTC): a technical gap.

A persistent mission records a gap from an internal measure only when that measure is required, valid, short of its target and
scored by its release's frozen measuring job (D-034). It is recorded beside the cycle's decision, whatever rule the cycle
decided, with its own effect key, so a mission with no external evidence at all (SN61 today) can still say what it measured.

- No other internal evidence makes a signal: not a number an agent filed, not a job on a release that froze no measuring job.
- It changes no decision, raises no request and never closes a mission. Rule 4's own proposal keeps its key and its rule.
- The proposal says "technical", belongs to the team's account, is one per mission and measure, and is never tested or promoted
  itself: every rule of a gap proposal (IC-7) holds for it.
"""
import json, os, sys, time, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import missions, runner as V  # noqa: E402
import test_g5_mission_lifecycle as tl  # noqa: E402  (as modules, so their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402
from test_mission_persistent_evidence import HOT, TEAM_ACCOUNT, WID, bench_measure, chain_measure  # noqa: E402

ROOT = "miner"


@tv.own_tests
class TechnicalGap(tl.Lifecycle):
    def setUp(self):
        super().setUp()
        self.db.q("INSERT INTO mw_files (comp_id, path, content, size) VALUES (?, ?, 'module.exports = () => 1;', 25)", (WID, f"{ROOT}/detect.js"))
        ref, _ = self.benchmark(0.5)                                   # the reference run of the measuring job
        self.db.q("DELETE FROM mw_bench")                              # only its job matters here, not its row
        self.measure = V.measure_of(V.stored(self.db, WID, ref["sbx"]), ROOT) | {"from_job": ref["sbx"]}
        self.freeze_job()

    def freeze_job(self, on=True): self.db.q("UPDATE mw_release SET measure=? WHERE comp_id=? AND current=1", (json.dumps(self.measure) if on else None, WID))
    def gaps(self): return [dict(p, signal=json.loads(p["signal"])) for p in self.db.q("SELECT * FROM ev_proposals WHERE origin='mission' ORDER BY id")]
    def fx(self, mid): return {e["key"].split(":cycle:")[1]: json.loads(e["result"] or "null") for e in self.effects(mid) if ":proposal" in e["key"]}

    def sn61(self):
        """The SN61 shape: no key attested, no evaluator designated, so there is no external evidence; one internal measure (>= 0.8)."""
        mid = self.create([chain_measure(target=5), bench_measure()], keys=[])
        self.cycle(mid, "baseline")
        return mid

    def test_a_mission_with_no_external_evidence_records_what_it_measured(self):
        mid = self.sn61()
        self.benchmark(0.60)
        rec = self.cycle(mid)
        self.assertEqual((rec["decision"]["rule"], rec["decision"]["kind"]), (3, "request"))       # it asks the Owner for an external source, as before
        self.assertEqual(self.reqs(mid, "corrective"), [])                                           # and asks for no corrective mission
        self.assertIsNone(rec["improve"])                                                            # rule 4's own signal: none, it didn't fire
        t = rec["improve_technical"]
        self.assertEqual((t["label"], t["measure"]["tier"], t["measure"]["id"], t["values"]["current"], t["evidence"]["basis"], t["diagnosis"]),
                         ("technical", "internal", "bench_score", 0.6, "internal_measured", ["technical.short"]))
        self.assertEqual(t["evidence"]["measuring_job"], self.measure["job_sha256"]); self.assertTrue(t["evidence"]["evidence_ref"]["sandbox_run"].startswith("job:"))
        self.assertEqual(list(self.fx(mid)), [f"{rec['n']}:proposal:technical"])
        (g,) = self.gaps()
        self.assertEqual((g["user_id"], g["target_kind"], g["target_key"], g["status"], g["signal"]["label"]), (TEAM_ACCOUNT, "team", f"comp:{WID}", "proposed", "technical"))
        self.assertTrue(g["title"].startswith("Measured technical gap: score short of its target (>= 0.8)"), g["title"])
        self.assertIn("a technical result, not a competition result", json.loads(g["change"])["text"])
        self.assertEqual(self.m(mid)["status"], "monitoring")                                        # it closes nothing

    def test_no_signal_without_a_frozen_measuring_job(self):
        self.freeze_job(False)
        mid = self.sn61(); self.benchmark(0.60)
        rec = self.cycle(mid)
        self.assertEqual(self.bench_of(rec)["status"], "valid")                                      # D-004 still reads the job's score as valid
        self.assertIn("frozen measuring job", rec["improve_technical"]["none"])
        self.assertEqual((self.fx(mid), self.gaps()), ({}, []))

    def filed(self, score=0.6):
        """A number an agent filed after a sandbox run that finished cleanly (Q-4's row)."""
        s = self.db.q("INSERT INTO mw_sbx (comp_id, run_id, status, exit_code, started, finished, pod) VALUES (?, 77, 'done', 0, ?, ?, 'pod-77') RETURNING id", (WID, time.time() - 60, time.time()), one=True)["id"]
        r = self.rel.current(WID)
        self.rel.record(WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score}, task=5, agent=2, run=77)
        return s

    def test_a_number_an_agent_filed_is_not_a_frozen_releases_measurement(self):
        """C5-5: on a release that froze its measuring job, the agent's number is recorded and is not the measure's value."""
        mid = self.sn61()
        s = self.filed()
        rec = self.cycle(mid)
        e = self.bench_of(rec)
        self.assertEqual((e["status"], e["value"], e["evidence_ref"]["sandbox_run"]), ("unverifiable", 0.6, f"sbx:{s}"))
        self.assertEqual(e["reason"], "This release measures with a frozen job; a number an agent filed isn't its measurement")
        self.assertNotIn("score_source", e["evidence_ref"])
        self.assertEqual(self.gaps(), [])

    def test_the_frozen_jobs_own_row_still_counts_beside_a_newer_filed_number(self):
        mid = self.sn61()
        self.benchmark(0.60)
        self.filed(0.99)                                                                             # newer, and not the measurement
        e = self.bench_of(self.cycle(mid))
        self.assertEqual((e["status"], e["value"], e["evidence_ref"]["score_source"]), ("valid", 0.6, "read from the job's output file"))

    def test_without_a_frozen_measuring_job_a_filed_number_reads_as_before(self):
        """Q-4 unchanged: a release that froze no measuring job still reads the agent's number as valid, and it makes no signal."""
        self.freeze_job(False)
        mid = self.sn61()
        s = self.filed()
        rec = self.cycle(mid)
        e = self.bench_of(rec)
        self.assertEqual((e["status"], e["evidence_ref"]["sandbox_run"], e["evidence_ref"]["score_source"]), ("valid", f"sbx:{s}", "filed by the agent that ran it"))  # Q-4
        self.assertIn("frozen measuring job", rec["improve_technical"]["none"]); self.assertEqual(self.gaps(), [])

    def test_no_signal_when_the_measure_meets_its_target_or_in_a_baseline_or_final_cycle(self):
        mid = self.create([chain_measure(target=5), bench_measure()], keys=[])
        self.benchmark(0.60)
        self.assertIn("baseline", self.cycle(mid, "baseline")["improve_technical"]["none"])
        self.assertIn("final", self.cycle(mid, "final")["improve_technical"]["none"])
        self.benchmark(0.85)
        self.assertIn("short of its target", self.cycle(mid)["improve_technical"]["none"])
        self.assertEqual(self.gaps(), [])

    def test_an_external_gap_and_a_technical_gap_in_one_cycle_are_two_effects(self):
        self.fresh()
        mid = self.create([chain_measure(target=5), bench_measure()], keys=[HOT])
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.001); self.benchmark(0.60)
        rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 4)
        self.assertEqual(sorted(self.fx(mid)), [f"{rec['n']}:proposal", f"{rec['n']}:proposal:technical"])
        a, b = self.gaps()
        self.assertEqual({a["signal"]["measure"]["id"], b["signal"]["measure"]["id"]}, {"chain_rank", "bench_score"})
        self.assertEqual({a["signal"].get("label"), b["signal"].get("label")}, {None, "technical"})
        self.assertEqual(len(self.reqs(mid, "corrective")), 1)                                       # rule 4's request, once: the technical gap adds none
        self.process(); self.process()
        self.assertEqual(len(self.gaps()), 2)                                                        # applied once each

    def test_the_decision_is_the_same_with_and_without_the_technical_gap(self):
        def run(frozen):
            self.freeze_job(frozen)
            mid = self.sn61(); self.benchmark(0.60)
            rec = self.cycle(mid)
            return rec["decision"], [(r["kind"], r["label"]) for r in self.reqs(mid)], [e["kind"] for e in rec["effects"] if e["kind"] != "proposal"]
        with_gap = run(True)
        self.db.q("DELETE FROM mx_missions"); self.db.q("DELETE FROM mw_bench"); self.db.q("DELETE FROM ev_proposals"); self.db.q("DELETE FROM mx_requests")
        self.db.q("DELETE FROM io_events")
        without = run(False)
        self.assertEqual((with_gap[0]["rule"], with_gap[0]["kind"], with_gap[1], with_gap[2]), (without[0]["rule"], without[0]["kind"], without[1], without[2]))

    def test_a_later_cycle_is_added_to_the_same_gap(self):
        mid = self.sn61(); self.benchmark(0.60)
        first = self.cycle(mid)
        self.benchmark(0.55)
        second = self.cycle(mid, now=time.time() + 3 * 3600)
        (g,) = self.gaps()
        self.assertEqual([c["n"] for c in g["signal"]["cycles"]], [first["n"], second["n"]])
        self.assertTrue(self.fx(mid)[f"{second['n']}:proposal:technical"]["linked"])

    def test_it_is_a_gap_like_any_other_never_tested_or_promoted_itself(self):
        mid = self.sn61(); self.benchmark(0.60); self.cycle(mid)
        (g,) = self.gaps()
        team = self.me(TEAM_ACCOUNT)
        for fn in (self.ev.promote, self.ev.trial_start):
            with self.assertRaises(HTTPException) as e: fn(team, g["id"])
            self.assertEqual(e.exception.status_code, 409)
        self.assertTrue(self.ev.proposal(team, g["id"])["gap"])

    def test_an_effect_an_older_image_could_not_apply_is_applied_at_start_up(self):
        mid = self.sn61(); self.benchmark(0.60)
        rec = self.cycle(mid, process=False)
        key = f"mx:{mid}:cycle:{rec['n']}:proposal:technical"
        self.db.q("UPDATE io_events SET status='done', result=? WHERE key=?", (json.dumps({"applied": False, "note": "unknown effect 'proposal'"}), key))
        self.process()
        self.assertEqual(self.gaps(), [])
        self.restart(); self.mx.evolution = self.ev; self.process()
        (g,) = self.gaps()
        self.assertEqual(g["signal"]["label"], "technical")
        c = next(c for c in self.mx.cycles(self.owner, mid)["cycles"] if c["n"] == rec["n"])
        e = next(x for x in c["effects"] if x["key"] == key)
        self.assertEqual((e["result"]["proposal"], c["improve_technical"]["label"]), (g["id"], "technical"))


@tv.own_tests
class Held(TechnicalGap):
    """G5-5 L5.6: after a technical gap was answered by a promoted change, did the measure hold? Read-only, in the cycle's record."""
    def promoted(self, base=0.60, cand=0.85):
        """A technical gap at `base`, answered, trialled on the frozen measuring job and promoted by the team's account."""
        mid = self.sn61()
        for _ in range(3): self.benchmark(base)
        self.cycle(mid)
        (g,) = self.gaps()
        self.ev.set_experiments(self.owner, WID, tl.evo.OptIn(on=True))
        team = self.me(TEAM_ACCOUNT)
        pid = self.ev.answer(team, g["id"], tl.evo.AnswerIn(agent=2, title="Benchmark before approving", instructions=tl.CAND_TEXT))["id"]
        self.ev.trial_start(team, pid)
        self.release(2)
        for _ in range(3): self.benchmark(cand)
        self.assertEqual(self.ev.trial_end(team, pid)["status"], "verified")
        self.ev.promote(team, pid)
        self.t = time.time()
        return mid, g["id"], pid, team

    def release(self, version, measuring=True):
        self.db.q("UPDATE mw_release SET current=0 WHERE comp_id=?", (WID,))
        self.db.q("""INSERT INTO mw_release (comp_id, version, commit_ref, sha256, suite, suite_tasks, suite_hash, repeats, frozen, current, image_digest, measure)
                     VALUES (?, ?, ?, NULL, 'swe-mini', 16, 'h1', 1, ?, 1, ?, ?)""", (WID, version, f"{version}cd2345ef67890", time.time(), tv.D1, json.dumps(self.measure) if measuring else None))

    def held(self, mid, gid, **kw):
        self.t += 3 * 3600
        rec = self.cycle(mid, now=self.t, **kw)
        return next(r for r in rec["proposals"]["rows"] if r["id"] == gid).get("held")

    def test_it_holds_after_three_new_measurements_on_a_release_frozen_after_the_promotion(self):
        mid, gid, pid, team = self.promoted()
        h = self.held(mid, gid)
        self.assertEqual((h["verdict"], h["counted"], h["needed"], h["rests_on"], h["opening_gap"]), ("open", 0, 3, "internal (technical)", 0.2))  # the trial's own release was frozen before the promotion
        self.release(3)                                              # the team's next artifact, made under the promoted instructions
        self.benchmark(0.82)
        self.assertEqual(self.held(mid, gid)["counted"], 1)
        self.assertEqual(self.held(mid, gid)["counted"], 1)          # the same measurement read by a later cycle isn't a second one
        self.benchmark(0.84); self.assertEqual(self.held(mid, gid)["verdict"], "open")
        self.benchmark(0.81)
        h = self.held(mid, gid)
        self.assertEqual((h["verdict"], h["counted"], [c["better"] for c in h["cycles"]]), ("held", 3, [True, True, True]))
        self.benchmark(0.10)                                         # a verdict once reached stands for that promotion
        self.assertEqual(self.held(mid, gid)["verdict"], "held")
        m7 = next(x for x in tl.analytics_targets(self.db) if x["k"] == "M7")
        self.assertEqual((m7["state"], m7["ids"]), ("met", [gid])); self.assertIn("internal (technical) evidence", m7["detail"]); self.assertIn("not a competition result", m7["detail"])
        self.assertEqual(self.m(mid)["status"], "monitoring")        # it closes nothing and decides nothing

    def test_a_verdict_outlives_the_history_it_was_read_from(self):
        mid, gid, pid, team = self.promoted()
        self.release(3)
        for score in (0.82, 0.84, 0.81): self.benchmark(score); h = self.held(mid, gid)
        self.assertEqual(h["verdict"], "held")
        old, missions.HELD_HISTORY = missions.HELD_HISTORY, 2      # many cycles later: the three counted cycles are out of the look-back
        try:
            for _ in range(4): h = self.held(mid, gid)
        finally: missions.HELD_HISTORY = old
        self.assertEqual((h["verdict"], h["counted"]), ("held", 3))

    def test_it_does_not_hold_when_the_first_new_measurement_is_no_better(self):
        mid, gid, pid, team = self.promoted()
        self.release(3); self.benchmark(0.58)                        # worse than the 0.60 that opened the gap
        h = self.held(mid, gid)
        self.assertEqual((h["verdict"], h["counted"], h["cycles"][0]["better"]), ("not_held", 1, False))
        self.benchmark(0.95)
        self.assertEqual(self.held(mid, gid)["verdict"], "not_held")
        m7 = next(x for x in tl.analytics_targets(self.db) if x["k"] == "M7")
        self.assertEqual(m7["state"], "not_met")

    def test_only_the_frozen_measuring_jobs_scores_on_a_later_release_count(self):
        mid, gid, pid, team = self.promoted()
        self.benchmark(0.9)                                          # on the trial's release: frozen before the promotion
        self.assertEqual(self.held(mid, gid)["counted"], 0)
        self.release(3, measuring=False); self.benchmark(0.9)        # a later release that froze no measuring job
        self.assertEqual(self.held(mid, gid)["counted"], 0)
        self.release(4)
        r = self.rel.current(WID)                                    # a number an agent filed after a clean run
        self.db.q("INSERT INTO mw_sbx (comp_id, run_id, status, exit_code, started, finished, pod) VALUES (?, 78, 'done', 0, ?, ?, 'pod-78')", (WID, time.time() - 60, time.time()))
        self.rel.record(WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": 0.9}, task=5, agent=2, run=78)
        self.assertEqual(self.held(mid, gid)["counted"], 0)
        m7 = next(x for x in tl.analytics_targets(self.db) if x["k"] == "M7")
        self.assertEqual(m7["state"], "none"); self.assertIn("still short of three measured cycles", m7["detail"])

    def test_a_rollback_ends_the_question(self):
        mid, gid, pid, team = self.promoted()
        self.release(3); self.benchmark(0.82)
        self.assertEqual(self.held(mid, gid)["counted"], 1)
        self.ev.rollback(team, pid)
        self.assertIsNone(self.held(mid, gid))                       # the gap is open again: nothing is being held


if __name__ == "__main__":
    unittest.main()
