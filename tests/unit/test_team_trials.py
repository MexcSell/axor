"""G5-5 L5.4 (PROMOTION_GATE_ARCHITECTURE.md; Owner decisions K-29, Q-4 of 2026-11-13): controlled experiments on a competition
team's agent, through the one promotion gate (evolution.py) and the team's own version store (au_versions).

- Off unless the Owner opted the team in (app_settings experiments.comp:<id>, audited): no trial starts, nothing is promoted.
- A trial puts the candidate instructions on the agent as a trial version and always puts the version before back when it ends.
- Its evidence is read from the team's benchmark rows only, and only rows whose score a VM runner job's own output file gave
  (job:<id>, the kept result intact). Rows an agent merely filed don't count. The policy's margin and minimum runs decide.
- A trial never promotes. Promotion is a person's, on measured evidence, with the opt-in still on and the agent unchanged since;
  the policy never promotes a team agent. Rollback writes a new version: history is never rewritten.
"""
import json, os, sys, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import evolution as evo, mining_upgrade  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402
import test_vm_runner as tv  # noqa: E402  (as a module, so its own tests don't run again here)

ME = {"id": 7, "username": "leo", "role": "admin"}
MEMBER = {"id": 8, "username": "sam", "role": "user"}
BASE_TEXT = "Review every change for failing tests before you approve it."
CAND_TEXT = "Review every change for failing tests and run the frozen benchmark before you approve it."
CAND2 = "bcd2345ef67890"  # the artifact the team makes during a trial


class Ov:
    def _agents_ok(self, me): return True


@tv.own_tests
class TeamTrial(tv.Board):
    def setUp(self):
        super().setUp()
        self.db.q("DROP TABLE IF EXISTS mw_agents")
        self.db.q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT, instructions TEXT, model TEXT)")
        self.db.q("INSERT INTO mw_agents (id, comp_id, name, instructions) VALUES (2, ?, 'Rae', ?)", (tp.WID, BASE_TEXT))
        self.w._own = lambda me, wid: ({"id": wid}, {"id": 1})
        self.up = mining_upgrade.Upgrade(self.w)
        self.ev = evo.Evolution(self.db, Ov(), None, None)
        self.ev.teams = self.w
        self.run_no = 100

    def tearDown(self):
        self.ev.pool.shutdown(wait=True); super().tearDown()

    def refused(self, code, fn, *a, **k):
        with self.assertRaises(HTTPException) as e: fn(*a, **k)
        self.assertEqual(e.exception.status_code, code, e.exception.detail)
        return e.exception.detail

    def text(self): return self.db.q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"]
    def versions(self): return self.db.q("SELECT id, version, source, instructions FROM au_versions WHERE agent_id=2 ORDER BY version")
    def opt(self, on=True): return self.ev.set_experiments(self.me(tp.OWNER), tp.WID, evo.OptIn(on=on))
    def propose(self, text=CAND_TEXT): return self.ev.propose(ME, evo.ProposalIn(target_key="teams:2", title="Benchmark before approving", instructions=text))["id"]

    def file(self, score, run):
        r = self.rel.current(tp.WID)
        return self.rel.record(tp.WID, r, {"candidate": r["commit_ref"], "suite": "swe-mini", "tasks": 16, "repeats": 1, "score": score}, task=5, agent=1, run=run)

    def measured(self, score, n=1, filed=None):
        """n benchmark runs of the current release, the way a team makes them: a VM runner job writes the score file, then
        record_benchmark files the row."""
        for _ in range(n):
            self.run_no += 1
            self.w.runner = tv.FakeRunner(files={"bench_out/live.json": json.dumps({"score": score, "tasks": 16})})
            self.job(run=self.run_no); self.file(score if filed is None else filed, self.run_no)

    def filed_only(self, score, n=1):
        for _ in range(n):
            self.run_no += 1; self.file(score, self.run_no)  # no job behind it: the agent's own number

    def refreeze(self, tasks=16):
        """The candidate artifact the team made during the trial, frozen on the same suite (or, with other tasks, on another one)."""
        self.rel.freeze({"id": 1, "username": "leo"}, tp.WID, tv.R.FreezeIn(commit=CAND2, suite="swe-mini", tasks=tasks, repeats=1, image_digest=tv.D1))

    def trial(self, base=0.60, cand=0.75, runs=3):
        self.opt(); self.measured(base, runs)
        pid = self.propose(); self.ev.trial_start(ME, pid)
        self.refreeze(); self.measured(cand, runs)
        return pid, self.ev.trial_end(ME, pid)

    # ---------- the opt-in ----------
    def test_no_trial_without_the_teams_opt_in_and_only_the_owner_sets_it(self):
        pid = self.propose()
        self.assertIn("isn't opted in", self.refused(403, self.ev.trial_start, ME, pid))
        self.refused(403, self.ev.set_experiments, MEMBER, tp.WID, evo.OptIn(on=True))
        self.refused(403, self.ev.set_experiments, ME, tp.WID, evo.OptIn(on=True))          # an administrator who isn't the Owner: a team's own account can be one
        self.refused(403, self.ev.experiments, ME, tp.WID)
        owner = self.me(tp.OWNER)
        self.refused(404, self.ev.set_experiments, owner, 999, evo.OptIn(on=True))
        self.assertEqual((self.text(), self.versions(), self.ev.experiments(owner, tp.WID)["on"]), (BASE_TEXT, [], False))
        self.assertEqual(self.opt(), {"comp": tp.WID, "on": True})
        self.assertEqual(self.db.q("SELECT actor, action, target FROM audit WHERE action LIKE 'experiments.%'"), [{"actor": "the-owner", "action": "experiments.opt_in", "target": f"comp:{tp.WID}"}])
        self.assertEqual(self.ev.trial_start(ME, pid)["status"], "testing")

    def test_a_proposal_needs_the_complete_new_instructions(self):
        self.refused(400, self.ev.propose, ME, evo.ProposalIn(target_key="teams:2", title="x", instructions=BASE_TEXT))
        self.refused(404, self.ev.propose, ME, evo.ProposalIn(target_key="teams:99", title="x", instructions=CAND_TEXT))
        p = self.ev.proposal(ME, self.propose())
        self.assertEqual((p["target_name"], p["status"], p["applies_here"], p["change"]["instructions"]), ("Rae", "proposed", True, CAND_TEXT))

    # ---------- the trial ----------
    def test_a_trial_applies_the_candidate_and_always_puts_the_version_before_back(self):
        self.opt(); self.measured(0.60, 3)
        pid = self.propose()
        p = self.ev.trial_start(ME, pid)
        self.assertEqual((p["status"], self.text()), ("testing", CAND_TEXT))
        self.assertEqual([(v["version"], v["source"]) for v in self.versions()], [(1, "original"), (2, f"trial #{pid}")])
        self.refreeze(); self.measured(0.75, 3)
        p = self.ev.trial_end(ME, pid)
        self.assertEqual((self.text(), p["status"], p["basis"]), (BASE_TEXT, "verified", "measured_internal"))
        self.assertEqual([(v["version"], v["source"], v["instructions"] == BASE_TEXT) for v in self.versions()],
                         [(1, "original", True), (2, f"trial #{pid}", False), (3, f"trial #{pid} ended", True)])
        e = p["evidence"]
        self.assertEqual((e["baseline"], e["candidate"], e["cases"], e["delta"], e["scale"], e["unbacked"]), (60.0, 75.0, 3, 15.0, 100.0, {"baseline": 0, "candidate": 0}))
        self.assertEqual((len(e["baseline_rows"]), len(e["candidate_rows"]), e["basis"]["label"], e["source"]), (3, 3, "technical", "trial"))
        self.assertEqual((len(e["candidate_releases"]), e["baseline_release"] in e["candidate_releases"], e["same_artifact"]), (1, False, 0))
        acts = [r["action"] for r in self.db.q("SELECT action FROM ev_audit ORDER BY id")]
        self.assertEqual(acts[-2:], ["trial.started", "trial.ended"])

    def test_a_candidate_that_is_not_better_is_not_verified_and_cannot_be_promoted(self):
        pid, p = self.trial(base=0.60, cand=0.62)
        self.assertEqual((p["status"], self.text()), ("not_better", BASE_TEXT)); self.assertIn("the policy needs +5", " ".join(p["evidence"]["why"]))
        self.refused(400, self.ev.promote, ME, pid)
        self.assertEqual(self.text(), BASE_TEXT)

    def test_rows_an_agent_only_filed_do_not_count(self):
        self.opt(); self.measured(0.60, 3)
        pid = self.propose(); self.ev.trial_start(ME, pid)
        self.refreeze()
        self.filed_only(0.99, 3)                                                           # big numbers, no job behind them
        self.measured(0.75, 2)                                                             # two measured runs: fewer than the policy's three
        p = self.ev.trial_end(ME, pid)
        self.assertEqual((p["status"], p["evidence"]["cases"], p["evidence"]["unbacked"]["candidate"]), ("not_better", 2, 3))
        self.assertIn("had no VM job behind the score", " ".join(p["evidence"]["why"]))

    def test_the_score_is_the_jobs_not_the_one_filed(self):
        self.opt(); self.measured(0.60, 3)
        pid = self.propose(); self.ev.trial_start(ME, pid)
        self.refreeze(); self.measured(0.61, 3, filed=0.95)                                                 # the agent files 0.95 each time; the jobs' files say 0.61
        p = self.ev.trial_end(ME, pid)
        self.assertEqual((p["status"], p["evidence"]["candidate"]), ("not_better", 61.0))

    def test_benchmarks_of_the_artifact_frozen_before_the_trial_are_not_the_candidates(self):
        """Instructions can't change the score of an artifact frozen before them: rows on the baseline's release during the trial
        measure the same artifact again, whatever they say."""
        self.opt(); self.measured(0.60, 3)
        pid = self.propose(); self.ev.trial_start(ME, pid)
        self.measured(0.95, 3)                                                             # the same release as the baseline: not the candidate's side
        p = self.ev.trial_end(ME, pid)
        self.assertEqual((p["status"], p["evidence"]["cases"], p["evidence"]["same_artifact"], p["evidence"]["candidate_rows"]), ("not_better", 0, 3, []))
        self.assertIn("the same artifact as the baseline", " ".join(p["evidence"]["why"]))
        self.refused(400, self.ev.promote, ME, pid)

    def test_an_edit_or_another_suite_during_the_trial_spoils_its_evidence(self):
        self.opt(); self.measured(0.60, 3)
        pid = self.propose(); self.ev.trial_start(ME, pid)
        self.refreeze(); self.measured(0.90, 3)
        self.db.q("UPDATE mw_agents SET instructions='Changed by hand in the middle.' WHERE id=2")
        p = self.ev.trial_end(ME, pid)
        self.assertEqual(p["status"], "not_better"); self.assertIn("changed during the trial", " ".join(p["evidence"]["why"]))
        self.assertEqual(self.text(), "Changed by hand in the middle.")                    # a person's change stands
        self.db.q("UPDATE mw_agents SET instructions=? WHERE id=2", (BASE_TEXT,))
        self.measured(0.60, 3)                                                             # a new baseline, on the release now current
        pid = self.propose(); self.ev.trial_start(ME, pid)
        self.refreeze(tasks=30); self.measured(0.90, 3)                                    # frozen on another suite: not comparable with the baseline
        p = self.ev.trial_end(ME, pid)
        self.assertEqual((p["status"], self.text()), ("not_better", BASE_TEXT)); self.assertIn("frozen suite changed", " ".join(p["evidence"]["why"]))

    def test_a_trial_survives_a_server_restart(self):
        self.opt(); self.measured(0.60, 3)
        pid = self.propose(); self.ev.trial_start(ME, pid)
        hub = self.proposal_on_hub()
        self.ev.pool.shutdown(wait=True)
        self.ev = evo.Evolution(self.db, Ov(), None, None); self.ev.teams = self.w         # the server starts again
        self.assertEqual((self.db.q("SELECT status FROM ev_proposals WHERE id=?", (hub,), one=True)["status"], self.text()), ("proposed", CAND_TEXT))
        self.assertEqual(self.ev.proposal(ME, pid)["status"], "testing")                    # still on trial, the record intact
        self.refreeze(); self.measured(0.75, 3)
        p = self.ev.trial_end(ME, pid)
        self.assertEqual((p["status"], self.text()), ("verified", BASE_TEXT))               # and it ends as any other: the version before is back

    def proposal_on_hub(self):
        """A personal agent's experiment cut off mid-run, as a restart finds it."""
        self.db.q("""INSERT INTO ev_proposals (user_id, target_kind, target_key, target_name, title, change, risk, origin, status, progress, created, updated)
                     VALUES (7, 'agent', 'hub:1', 'Py', 'x', '{}', 'config', 'manual', 'testing', '{"done": 1, "total": 6}', 1, 1)""")
        return self.db.q("SELECT MAX(id) id FROM ev_proposals", one=True)["id"]

    def test_one_trial_per_team_and_a_trial_needs_a_frozen_release(self):
        self.opt()
        a, b = self.propose(), self.propose(CAND_TEXT + " Twice.")
        self.ev.trial_start(ME, a)
        self.assertIn("One trial at a time", self.refused(409, self.ev.trial_start, ME, b))
        self.refused(409, self.ev.trial_end, ME, b)
        self.ev.trial_end(ME, a)
        self.db.q("UPDATE mw_release SET current=0")
        self.assertIn("Freeze a release first", self.refused(400, self.ev.trial_start, ME, b))

    # ---------- promotion and rollback ----------
    def test_a_person_promotes_on_measured_evidence_and_rollback_writes_a_new_version(self):
        pid, p = self.trial()
        self.assertIn("never by the policy", self.refused(403, self.ev.promote, ME, pid, by_policy=True))
        self.assertEqual(self.text(), BASE_TEXT)
        done = self.ev.promote(ME, pid)
        vs = self.versions()
        self.assertEqual((done["status"], done["decision"], done["decided_by"], self.text()), ("promoted", "human", "leo", CAND_TEXT))
        self.assertEqual((vs[-1]["source"], done["after_version"], done["before_version"]), (f"gate #{pid}", vs[-1]["id"], vs[-2]["id"]))
        self.assertIn("evidence: measured internal", self.db.q("SELECT detail FROM ev_audit WHERE action='proposal.promoted'", one=True)["detail"])
        back = self.ev.rollback(ME, pid)
        vs = self.versions()
        self.assertEqual((back["status"], self.text(), vs[-1]["source"], len(vs)), ("rolled_back", BASE_TEXT, f"gate #{pid} rolled back", 5))

    def test_no_promotion_after_an_opt_out_or_a_later_change(self):
        pid, _ = self.trial()
        self.opt(False)
        self.assertIn("isn't opted in", self.refused(403, self.ev.promote, ME, pid))
        self.opt(True)
        self.db.q("UPDATE mw_agents SET instructions='Changed after the trial.' WHERE id=2")
        self.assertIn("changed after the trial", self.refused(409, self.ev.promote, ME, pid))

    def test_typed_in_numbers_never_promote_a_team_agent(self):
        self.opt()
        pid = self.propose()
        e = self.ev.record_evidence(ME, pid, evo.EvidenceIn(test_set="my own runs", baseline=[50, 50, 50], candidate=[90, 90, 90]))
        self.assertEqual((e["status"], e["basis"]), ("verified", "recorded"))
        self.assertIn("only on measured evidence", self.refused(400, self.ev.promote, ME, pid))
        self.assertEqual(self.text(), BASE_TEXT)


if __name__ == "__main__":
    unittest.main()
