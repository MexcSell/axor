"""D-034 (decided under the Owner's delegation of 2026-11-13 13:35 UTC): a release can freeze its measuring job, and for such a
release a benchmark row is job-measured only when the job behind it is that job. Before this, any VM job whose command wrote a
score file could be filed under the frozen suite's name: the team's mock validator could stand in for the official scorer.

- What is frozen: the job's spec (without the run's id, the proxy tokens and the declared source), the hash of its harness files
  (everything sent into the job outside the release's candidate root), the image digests it pulled, the score file.
- The same job with another candidate under the root is measured. Another command, another harness file, another pulled image
  or another score file is not: the row is kept, not comparable, and says why; the mission's measure reads it as unverifiable.
- One check for every reader (runner.backed): the release's own readers, the mission's internal measure, a trial's evidence.
- A release without a frozen measuring job behaves exactly as before.
"""
import json, os, sys, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import evolution as evo, runner as V  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402
import test_team_trials as tt  # noqa: E402  (as modules, so their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402

ME = {"id": 1, "username": "leo"}
ROOT = "miner"
MOCK = "#!/bin/sh\necho '{\"score\": 0.826, \"tasks\": 16}' > bench_out/live.json\n"  # the team's own validator: always pleased


class Fixture:
    """Shared by the two classes below: a candidate under miner/, a harness outside it, and a way to freeze the measuring job."""
    def add(self, path, text):
        self.db.q("INSERT INTO mw_files (comp_id, path, content, size) VALUES (?,?,?,?) ON CONFLICT(comp_id, path) DO UPDATE SET content=excluded.content",
                  (tp.WID, path, text, len(text)))

    def seed(self):
        self.add(f"{ROOT}/detect.js", "module.exports = () => 1;\n"); self.add("bench/mock.sh", MOCK)
        self.run_no = 300

    def job_run(self, **kw):
        self.run_no += 1
        job = tv.spec(**{"kind": "bench", "command": "sh bench/run.sh", "score_file": "bench_out/live.json", **kw})
        return self.w._docker_job(self.comp, self.c, job, task=5, run=self.run_no, agent=self.agent)["sbx"], self.run_no

    def freeze_measuring(self, sid, commit=tv.CAND, root=ROOT, **kw):
        return self.rel.freeze(ME, tp.WID, tv.R.FreezeIn(commit=commit, suite="swe-mini", tasks=16, repeats=1, image_digest=tv.D2, measure_job=sid, candidate_root=root, **kw))

    def file(self, run, cand=tv.CAND, score=0.99):
        return self.rel.record(tp.WID, self.rel.current(tp.WID), {"candidate": cand, "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score}, task=5, agent=1, run=run)

    def refused(self, code, fn, *a, **k):
        with self.assertRaises(HTTPException) as e: fn(*a, **k)
        self.assertEqual(e.exception.status_code, code, e.exception.detail)
        return e.exception.detail


@tv.own_tests
class MeasuringJob(Fixture, tv.Board):
    def setUp(self):
        super().setUp(); self.seed()
        self.ref, _ = self.job_run()                      # the reference run: the official measuring job, as a person ran it once
        self.freeze_measuring(self.ref)

    def frozen(self): return self.rel.measure(self.rel.current(tp.WID))

    def test_freezing_keeps_what_identifies_the_job(self):
        m, d = self.frozen(), V.stored(self.db, tp.WID, self.ref)
        self.assertEqual(set(m), {"job_sha256", "harness_sha256", "images", "score_file", "candidate_root", "candidate_sha256", "from_job"})
        self.assertEqual((m["score_file"], m["candidate_root"], m["from_job"], m["images"]), ("bench_out/live.json", ROOT, self.ref, [tv.D1]))  # the pulled image, not the one it built
        self.assertEqual(m["job_sha256"], V.measure_sha(d["job"]))
        tree = d["inputs"]["tree"]
        self.assertIn(f"{ROOT}/detect.js", tree); self.assertEqual(m["harness_sha256"], V.harness_sha({p: h for p, h in tree.items() if not p.startswith(ROOT + "/")}, ROOT))
        self.assertEqual(m["candidate_sha256"], V.candidate_sha({p: h for p, h in tree.items() if p.startswith(ROOT + "/")}, ROOT))   # D-034a: which candidate
        self.assertEqual(self.rel._pub(tp.WID, self.rel.current(tp.WID))["measure"]["from_job"], self.ref)

    def test_the_same_job_on_another_candidate_is_another_candidate_until_a_release_freezes_it(self):
        """D-034a: the release says which candidate it measures. The measuring job on other candidate files runs and is kept, and
        is not this release's measurement; a release frozen from a run of the new candidate measures it."""
        self.add(f"{ROOT}/detect.js", "module.exports = () => 2;\n")  # the team's next candidate: only the candidate changed
        sid, run = self.job_run()
        r = self.file(run)
        self.assertEqual((r["comparable"], r["score_source"]), (False, "filed"))
        self.assertIn(f"it measured another candidate than the one this release froze (the files under {ROOT}/ differ): freeze a new release to measure it", r["why"])
        self.assertFalse(V.backed(self.db, tp.WID, f"job:{sid}", 0.81, self.frozen()))
        self.assertNotEqual(self.measure()["status"], "valid")                                    # the mission's measure doesn't take it either
        self.freeze_measuring(sid, commit=tt.CAND2)                                               # a person freezes the new candidate, from that run
        again, run2 = self.job_run()
        r2 = self.rel.record(tp.WID, self.rel.current(tp.WID), {"candidate": tt.CAND2, "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": 0.99}, task=5, agent=1, run=run2)
        self.assertEqual((r2["comparable"], r2["score_source"], r2["score"]), (True, "job_output", 0.81))
        self.assertTrue(V.backed(self.db, tp.WID, f"job:{again}", 0.81, self.frozen()))

    def test_the_candidate_hash_and_the_harness_hash_are_each_others_complement(self):
        tree = V.stored(self.db, tp.WID, self.ref)["inputs"]["tree"]
        cand, harness = V.candidate_sha(tree, ROOT), V.harness_sha(tree, ROOT)
        edited = {**tree, f"{ROOT}/detect.js": "0" * 64}
        self.assertEqual((V.harness_sha(edited, ROOT), V.candidate_sha(edited, ROOT) != cand), (harness, True))     # a candidate file: the candidate only
        edited = {**tree, "bench/run.sh": "0" * 64}
        self.assertEqual((V.candidate_sha(edited, ROOT), V.harness_sha(edited, ROOT) != harness), (cand, True))     # a harness file: the harness only
        self.assertNotIn("candidate_sha256", V.MEASURE_WHAT)                                       # never part of "the same measuring job"

    def test_a_release_frozen_before_candidates_were_recorded_measures_any_candidate_as_before(self):
        m = self.frozen(); m.pop("candidate_sha256")
        self.db.q("UPDATE mw_release SET measure=? WHERE comp_id=? AND current=1", (json.dumps(m), tp.WID))
        self.add(f"{ROOT}/detect.js", "module.exports = () => 2;\n")
        sid, run = self.job_run()
        self.assertEqual(self.file(run)["comparable"], True); self.assertTrue(V.backed(self.db, tp.WID, f"job:{sid}", 0.81, self.frozen()))

    def test_a_finished_job_is_told_at_once_whether_it_counted(self):
        go = lambda **kw: self.w._docker_job(self.comp, self.c, tv.spec(**{"kind": "bench", "command": "sh bench/run.sh", "score_file": "bench_out/live.json", **kw}), task=5, run=900, agent=self.agent)
        ver = self.rel.current(tp.WID)["version"]
        self.assertEqual(go()["measuring"], {"release": ver, "is_measuring_job": True})
        out = go(command="sh bench/mock.sh")
        self.assertEqual((out["measuring"]["release"], out["measuring"]["is_measuring_job"]), (ver, False)); self.assertIn("Its job isn't this release's measuring job", out["measuring"]["why"])
        self.add(f"{ROOT}/detect.js", "module.exports = () => 2;\n")
        self.assertIn("It measured another candidate", go()["measuring"]["why"])
        self.assertNotIn("measuring", self.w._docker_job(self.comp, self.c, tv.spec(kind="build"), task=5, run=901, agent=self.agent))   # no score: nothing to say
        self.rel.freeze(ME, tp.WID, tv.R.FreezeIn(commit=tv.CAND, suite="swe-mini", tasks=16, repeats=1, image_digest=tv.D2))             # a release without a measuring job
        self.assertNotIn("measuring", go())

    def test_the_mock_validator_cannot_stand_in_for_the_measuring_job(self):
        self.w.runner = tv.FakeRunner(files={"bench_out/live.json": '{"score": 0.826, "tasks": 16}'})
        sid, run = self.job_run(command="sh bench/mock.sh")  # another command: the team's own validator
        r = self.file(run, score=0.826)
        self.assertEqual((r["comparable"], r["score_source"]), (False, "filed"))
        self.assertIn("its job isn't this release's measuring job: the job (its command, images, limits or network) differ", "; ".join(r["why"]))
        self.assertFalse(V.backed(self.db, tp.WID, f"job:{sid}", 0.826, self.frozen()))
        self.assertTrue(V.backed(self.db, tp.WID, f"job:{sid}", 0.826))  # without the release's measuring job this was "a job gave the score"
        self.assertNotEqual(self.measure()["status"], "valid")           # not comparable: the mission's measure has nothing valid

    def test_a_changed_harness_is_not_the_measuring_job(self):
        self.add("bench/run.sh", MOCK)  # the same command, but the script it runs was replaced
        sid, run = self.job_run()
        r = self.file(run)
        self.assertEqual(r["comparable"], False); self.assertIn("the harness files differ", "; ".join(r["why"]))

    def test_another_pulled_image_or_score_file_is_not_the_measuring_job(self):
        d = V.stored(self.db, tp.WID, self.ref)
        self.assertEqual(V.differs(d, self.frozen()), "")
        other = {**d, "images": [{"ref": "x", "id": tv.D2, "digests": [tv.D2], "how": "pulled"}]}
        why = V.differs(other, self.frozen())
        self.assertIn("the images it pulled differ", why)
        self.assertIn(f"it pulled {tv.D2[:19]}…, which the frozen job doesn't name", why); self.assertIn(f"it didn't pull {tv.D1[:19]}…", why)  # which ones, so the person knows what to freeze
        self.assertIn("freeze a new release to measure it", why)
        self.assertIn("the score file differs", V.differs({**d, "job": {**d["job"], "score_file": "bench_out/other.json"}}, {**self.frozen(), "job_sha256": V.measure_sha({**d["job"], "score_file": "bench_out/other.json"})}))
        self.assertIn("holds no file list", V.differs({**d, "inputs": {k: v for k, v in d["inputs"].items() if k != "tree"}}, self.frozen()))

    def test_a_declared_source_does_not_change_the_answer(self):
        sid, run = self.job_run(source_commit="abc1234")  # the submitter's statement about where the candidate came from
        d = V.stored(self.db, tp.WID, sid)
        self.assertEqual(d["job"]["source"]["commit"], "abc1234")
        self.assertNotEqual(d["inputs"]["job_sha256"], V.stored(self.db, tp.WID, self.ref)["inputs"]["job_sha256"])  # the run's own job hash does change with it
        self.assertEqual(V.measure_sha(d["job"]), self.frozen()["job_sha256"])
        self.assertEqual(self.file(run)["comparable"], True)

    def test_a_row_made_comparable_by_hand_is_still_unverifiable_for_the_mission(self):
        self.w.runner = tv.FakeRunner(files={"bench_out/live.json": '{"score": 0.826, "tasks": 16}'})
        sid, run = self.job_run(command="sh bench/mock.sh"); self.file(run, score=0.826)
        self.db.q("UPDATE mw_bench SET comparable=1, evidence_ref=?, release_id=? WHERE id=(SELECT MAX(id) FROM mw_bench)", (f"job:{sid}", self.rel.current(tp.WID)["id"]))
        e = self.measure()
        self.assertEqual((e["status"], e["pass"]), ("unverifiable", None)); self.assertIn("Its job isn't this release's measuring job", e["reason"])

    def test_what_freezing_refuses(self):
        self.assertIn("name both", self.refused(422, self.rel.freeze, ME, tp.WID, tv.R.FreezeIn(commit=tv.CAND, suite="swe-mini", tasks=16, measure_job=self.ref)))
        self.assertIn("name both", self.refused(422, self.rel.freeze, ME, tp.WID, tv.R.FreezeIn(commit=tv.CAND, suite="swe-mini", tasks=16, candidate_root=ROOT)))
        self.refused(404, self.freeze_measuring, 9999)                                   # no such job
        self.assertIn("no file under vendor/", self.refused(422, self.freeze_measuring, self.ref, root="vendor"))
        self.w.runner = tv.FakeRunner(files={})
        self.run_no += 1; plain = self.w._docker_job(self.comp, self.c, tv.spec(kind="run", command="true"), task=5, run=self.run_no, agent=self.agent)["sbx"]
        self.assertIn("names no score file", self.refused(422, self.freeze_measuring, plain))
        self.db.q("UPDATE mw_sbx SET comp_id=99 WHERE id=?", (self.ref,))               # another team's job
        self.refused(404, self.freeze_measuring, self.ref)

    def test_a_job_too_large_to_list_cannot_be_a_measuring_job(self):
        old, V.TREE_MAX = V.TREE_MAX, 2
        try: sid, _ = self.job_run()
        finally: V.TREE_MAX = old
        self.assertNotIn("tree", V.stored(self.db, tp.WID, sid)["inputs"])
        self.assertIn("holds no file list", self.refused(422, self.freeze_measuring, sid))

    def test_a_release_without_a_measuring_job_is_as_before(self):
        self.rel.freeze(ME, tp.WID, tv.R.FreezeIn(commit=tv.CAND, suite="swe-mini", tasks=16, repeats=1, image_digest=tv.D2))  # frozen again, the old way
        self.assertIsNone(self.frozen())
        self.w.runner = tv.FakeRunner(files={"bench_out/live.json": '{"score": 0.826, "tasks": 16}'})
        sid, run = self.job_run(command="sh bench/mock.sh")
        r = self.file(run, score=0.5)
        self.assertEqual((r["comparable"], r["score_source"], r["score"]), (True, "job_output", 0.826))  # any job's score file counts: today's behaviour, unchanged
        self.assertEqual(self.measure()["status"], "valid")


@tv.own_tests
class Trial(Fixture, tt.TeamTrial):
    """A trial's evidence on releases that freeze the measuring job: both sides must measure with it."""
    def setUp(self):
        super().setUp(); self.seed()
        self.ref, _ = self.job_run()
        self.freeze_measuring(self.ref)

    def scored(self, score, n=3, **kw):
        for _ in range(n):
            self.w.runner = tv.FakeRunner(files={"bench_out/live.json": json.dumps({"score": score, "tasks": 16})})
            _, run = self.job_run(**kw)
            r = self.rel.current(tp.WID)
            self.rel.record(tp.WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score}, task=5, agent=1, run=run)

    def test_both_sides_measured_by_the_frozen_job_verify(self):
        self.opt(); self.scored(0.60)
        pid = self.propose(); self.ev.trial_start(tt.ME, pid)
        self.add(f"{ROOT}/detect.js", "module.exports = () => 3;\n")
        ref2, _ = self.job_run()                                  # D-034a: the new candidate's own reference run
        self.freeze_measuring(ref2, commit=tt.CAND2)              # the artifact made during the trial: the same measuring job, another candidate
        self.scored(0.75)
        p = self.ev.trial_end(tt.ME, pid)
        self.assertEqual((p["status"], p["evidence"]["baseline"], p["evidence"]["candidate"]), ("verified", 60.0, 75.0))
        a, b = (json.loads(r["measure"]) for r in self.db.q("SELECT measure FROM mw_release WHERE comp_id=? ORDER BY id DESC LIMIT 2", (tp.WID,)))
        self.assertNotEqual(a["candidate_sha256"], b["candidate_sha256"])                          # two candidates,
        self.assertTrue(all(a[k] == b[k] for k in V.MEASURE_WHAT))                                 # one measuring job: the trial's "same job" check passes

    def test_a_candidate_release_frozen_from_the_old_candidates_run_measures_nothing_new(self):
        """The mistake D-034a catches: the candidate release is frozen from the baseline's reference run, so it still names the
        baseline candidate; the new candidate's scores are another candidate's and don't count."""
        self.opt(); self.scored(0.60)
        pid = self.propose(); self.ev.trial_start(tt.ME, pid)
        self.add(f"{ROOT}/detect.js", "module.exports = () => 3;\n")
        self.freeze_measuring(self.ref, commit=tt.CAND2)
        self.scored(0.75)
        self.assertNotEqual(self.ev.trial_end(tt.ME, pid)["status"], "verified")

    def test_a_candidate_side_scored_by_another_job_is_not_evidence(self):
        self.opt(); self.scored(0.60)
        pid = self.propose(); self.ev.trial_start(tt.ME, pid)
        self.freeze_measuring(self.ref, commit=tt.CAND2)
        self.scored(0.95, command="sh bench/mock.sh")              # the candidate side "measured" by the team's own validator
        r = self.rel.current(tp.WID)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mw_bench WHERE comparable=0 AND why LIKE '%measuring job%'", one=True)["n"], 3)  # refused when filed
        # and if such rows were marked comparable anyway (by hand, or filed before the measuring job was frozen), the trial's own
        # reader still refuses them: each row is checked against its release's measuring job
        self.db.q("UPDATE mw_bench SET comparable=1, why=NULL, suite_hash=?, release_id=? WHERE comparable=0", (r["suite_hash"], r["id"]))
        p = self.ev.trial_end(tt.ME, pid)
        self.assertNotEqual(p["status"], "verified")

    def test_a_release_frozen_during_the_trial_without_the_measuring_job_spoils_it(self):
        self.opt(); self.scored(0.60)
        pid = self.propose(); self.ev.trial_start(tt.ME, pid)
        self.refreeze()                                            # frozen the old way: no measuring job on the candidate's release
        self.scored(0.95, command="sh bench/mock.sh")
        p = self.ev.trial_end(tt.ME, pid)
        self.assertNotEqual(p["status"], "verified")
        self.assertIn("doesn't measure with the same job", json.dumps(p["evidence"]) + (p.get("note") or ""))


if __name__ == "__main__":
    unittest.main()
