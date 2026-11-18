"""G5 wave-5 cross-stream contract (integration owner, 2026-11-13): G5-4's runner job → W7's execution record (IC-4, directive C2).

A VM runner job that states its source (`source_repo`, `source_commit`) writes it into mw_sbx.src through the real
mining_work._docker_job, marked basis "declared". W7's execution record (mining_work.sbx_record) shows it as the declared
source and never under what the run accessed. The runner itself is a stand-in (test_vm_runner.FakeRunner); the write and
the reading are the real code.
"""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_work  # noqa: E402
import test_vm_runner as tv  # noqa: E402  (as a module: its own tests don't run again here)

REPO, COMMIT = "github.com/example-org/miner", "0123abc4567def"


@tv.own_tests
class RunnerSourceIsDeclaredNotAccessed(tv.Board):
    def test_a_runner_jobs_stated_source_is_declared_and_never_accessed(self):
        self.db.q("ALTER TABLE mw_sbx ADD COLUMN src TEXT")                                 # W7's column, as on the merged tree
        out = self.job(source_repo=REPO, source_commit=COMMIT)
        row = self.db.q("SELECT * FROM mw_sbx WHERE id=?", (out["sbx"],), one=True)
        [src] = json.loads(row["src"])
        self.assertEqual((src["url"], src["commit"], src["basis"]), (REPO, COMMIT.lower(), "declared"))
        rec = mining_work.sbx_record(row, needs=[f"git:{REPO}"])
        self.assertEqual([(x["url"], x["commit"]) for x in rec["declared_source"]], [(REPO, COMMIT.lower())])
        self.assertEqual(rec["accessed"]["checkouts"], [])
        self.assertNotIn(REPO, json.dumps(rec["accessed"]))

    def test_positive_control_without_the_column_nothing_is_written_and_the_job_still_runs(self):
        out = self.job(source_repo=REPO, source_commit=COMMIT)
        row = self.db.q("SELECT * FROM mw_sbx WHERE id=?", (out["sbx"],), one=True)
        self.assertEqual((row["status"], row["exit_code"]), ("done", 0))
        self.assertNotIn("src", row.keys())


if __name__ == "__main__":
    unittest.main()
