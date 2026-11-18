"""G5-5 L5.3 (runtime monitoring), second piece: the frozen release's measured benchmark score dropped.

- Only measured rows count on both sides: comparable, on the current frozen release and its suite, the score read from a VM
  runner job's own output file (job:<id>, the kept result intact). A number an agent merely filed neither opens nor resolves.
- A measured score more than BENCH_DROP points (of 100) below the measured one before it, on the same release, opens the team's
  register row `bench:comp:<id>` (source "monitor", the team's scope and account). The row keeps the score it fell from.
- A later measured score back within BENCH_DROP of that reference resolves it. So does freezing another release: the finding
  was about one artifact.
- It reports only: the benchmark row is recorded either way, and nothing about the team's agents, tasks or release changes.
"""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_release as R  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402  (as modules, so their own tests don't run again here)
import test_team_trials as tt  # noqa: E402
import test_vm_runner as tv  # noqa: E402

KEY = f"bench:comp:{tp.WID}"


@tv.own_tests
class Watch(tt.TeamTrial):
    def setUp(self):
        super().setUp()
        self.said = []
        self.rel.w._event = lambda wid, kind, text, **k: self.said.append((kind, text))  # the board the release tells

    def rows(self): return [r for r in self.orc().risks(tp.TEAM_ACCOUNT, limit=500) if r["rkey"] == KEY]
    def orc(self):
        from app import orchestrator
        return orchestrator.get()
    def evd(self, r): return json.loads(r["evidence"]) if isinstance(r["evidence"], str) else r["evidence"]
    def bench_ids(self): return [b["id"] for b in self.db.q("SELECT id FROM mw_bench WHERE comp_id=? ORDER BY id", (tp.WID,))]

    def test_a_measured_drop_on_the_frozen_release_opens_the_teams_row(self):
        self.measured(0.80)
        self.assertEqual(self.rows(), [])                                  # the first measured row: nothing to set it against
        self.measured(0.78)
        self.assertEqual(self.rows(), [])                                  # 2 points: inside the threshold
        self.measured(0.60)
        (r,) = self.rows()
        ids, e = self.bench_ids(), self.evd(r)
        self.assertEqual((r["mission"], r["source"], r["status"], r["severity"], r["critical"], r["layer"]), (f"comp:{tp.WID}", "monitor", "open", "medium", 0, "execution"))
        self.assertEqual((e["reference"]["row"], e["reference"]["score"], e["latest"]["row"], e["latest"]["score"], e["drop_points"], e["threshold_points"]),
                         (ids[1], 0.78, ids[2], 0.60, 18.0, R.BENCH_DROP))
        self.assertTrue(e["reference"]["evidence_ref"].startswith("job:") and e["latest"]["evidence_ref"].startswith("job:"))
        self.assertEqual(e["release"], self.rel.current(tp.WID)["id"])
        self.assertEqual([(k, "0.78 to 0.6" in t) for k, t in self.said if "Benchmark watch" in t], [("error", True)])
        self.assertEqual([x["rkey"] for x in self.orc().risks(tp.TEAM_ACCOUNT, source="monitor")], [KEY])

    def test_the_row_keeps_its_reference_and_a_recovered_score_resolves_it(self):
        self.measured(0.80); self.measured(0.60)
        seen = self.rows()[0]["seen"]
        self.measured(0.61)                                                # still low: against the 0.80 it fell from, not against the 0.60 before it
        r = self.rows()[0]
        self.assertEqual((r["status"], self.evd(r)["reference"]["score"], self.evd(r)["latest"]["score"], r["seen"]), ("open", 0.80, 0.61, seen + 1))
        self.assertEqual(len([t for _, t in self.said if "Benchmark watch" in t]), 1)  # the board is told once
        self.measured(0.77)                                                # within 5 points of 0.80 again
        self.assertEqual(self.rows()[0]["status"], "resolved")
        self.measured(0.76)
        self.assertEqual(self.rows()[0]["status"], "resolved")             # and stays so

    def test_a_filed_number_neither_opens_nor_resolves(self):
        self.measured(0.80)
        self.filed_only(0.10)                                              # an agent's own numbers, no job behind them
        self.filed_only(0.99)
        self.assertEqual(self.rows(), [])
        self.measured(0.79)                                                # set against the measured 0.80, not the filed 0.99
        self.assertEqual(self.rows(), [])
        self.measured(0.50)
        self.assertEqual(self.rows()[0]["status"], "open")
        self.filed_only(0.99)
        self.assertEqual(self.rows()[0]["status"], "open")
        self.measured(0.50, filed=0.99)                                    # the job's file decides, whatever the agent wrote
        self.assertEqual((self.rows()[0]["status"], self.evd(self.rows()[0])["latest"]["score"]), ("open", 0.50))

    def test_a_reference_whose_kept_result_was_edited_is_not_used(self):
        self.measured(0.80)
        self.db.q("UPDATE mw_files SET content=replace(content, '0.8', '0.9') WHERE comp_id=? AND path LIKE 'runs/sbx-%/result.json'", (tp.WID,))
        self.measured(0.50)
        self.assertEqual(self.rows(), [])                                  # nothing measured to set it against

    def test_another_release_starts_again_and_resolves_the_old_finding(self):
        self.measured(0.80); self.measured(0.60)
        self.assertEqual(self.rows()[0]["status"], "open")
        self.refreeze()
        self.measured(0.40)                                                # a new artifact: its first measured row, nothing to compare
        r = self.rows()[0]
        self.assertEqual(r["status"], "resolved")
        self.assertIn("was frozen since", str(r["verification"]))
        self.measured(0.20)
        r = self.rows()[0]
        self.assertEqual((r["status"], self.evd(r)["reference"]["score"], self.evd(r)["release"]), ("open", 0.40, self.rel.current(tp.WID)["id"]))

    def test_it_only_reports(self):
        self.measured(0.80)
        snap = lambda: json.dumps({t: self.db.q(f"SELECT * FROM {t} ORDER BY id") for t in ("mw_agents", "mw_release", "mw_tasks", "mw_comps")}, default=str, sort_keys=True)
        before, n = snap(), len(self.bench_ids())
        self.measured(0.10)
        self.assertEqual((snap(), len(self.bench_ids()), self.rows()[0]["status"]), (before, n + 1, "open"))
        self.rel.watch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("register down"))
        self.measured(0.05)                                                # a failing watch never loses the benchmark row
        self.assertEqual(len(self.bench_ids()), n + 2)


if __name__ == "__main__":
    unittest.main()
