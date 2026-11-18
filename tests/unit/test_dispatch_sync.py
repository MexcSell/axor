"""control_dispatch.sync()/linked()/counts(): one status for a Control Hub task linked to a board task or a mission.

The 11-10 audit's "14 open tasks, 0 under way, 3 not dispatched after an hour" with the dispatcher running: a board task the
team finished (or merged away as a repeat) stayed 'todo' in ctl_tasks, and every count read straight from the table (unit
counts, the Intelligence layers, the orchestrator) counted it open and not moving. The list mapped it; the counts didn't."""
import os, sys, time, unittest

from app import control_dispatch as cd, control_hub, control_missions as cm

sys.path.insert(0, os.path.dirname(__file__))
from test_control_hub import Base  # noqa: E402
from test_organization import ME  # noqa: E402


class Sync(Base):
    def row(self, tid): return self.db.q("SELECT * FROM ctl_tasks WHERE id=?", (tid,), one=True)

    def setUp(self):
        super().setUp()
        self.ch.edit_fixed(ME, 1, control_hub.FixedPatch(target_rank=10))
        for c, t in (("hold", "TEXT"), ("summary", "TEXT"), ("detail", "TEXT")):
            self.db.q(f"ALTER TABLE mw_tasks ADD COLUMN {c} {t}")
        for c in ("paused", "autopilot"):
            self.db.q(f"ALTER TABLE mw_comps ADD COLUMN {c} INTEGER DEFAULT 0")
        self.db.q("UPDATE mw_comps SET autopilot=1")
        self.ch.set_mode(ME, control_hub.SettingsIn(mode="hybrid"))
        cm.missions(self.ch, ME)
        cd.dispatch(self.ch, ME); cd.dispatch(self.ch, ME)  # the template's 12 fixed tasks onto the boards
        self.on_board = [r for r in self.db.q("SELECT * FROM ctl_tasks WHERE ref LIKE 'mw_task:%' ORDER BY id")]
        self.assertEqual(len(self.on_board), 12)

    def bid(self, r): return int(r["ref"].split(":")[1])

    def test_a_board_task_the_team_finished_is_done_in_the_table_and_reopens_with_the_board(self):
        r = self.on_board[0]
        self.db.q("UPDATE mw_tasks SET status='done', done_at=?, summary='Benchmarked: 0.81' WHERE id=?", (time.time() - 60, self.bid(r)))
        before = cd.counts(self.db, ME["id"], "hybrid")["open"]
        self.assertEqual(before, 11)  # counts() reads it the way the list does, before any write
        self.assertEqual(cd.sync(self.db), 1)
        row = self.row(r["id"])
        self.assertEqual((row["status"], row["summary"]), ("done", "Benchmarked: 0.81"))
        self.assertIsNotNone(row["done_at"]); self.assertIn("the team board finished it", row["history"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ctl_tasks WHERE user_id=7 AND status IN ('todo','running','review')", one=True)["n"], 11)
        self.assertEqual(cd.sync(self.db), 0)  # once
        self.db.q("UPDATE mw_tasks SET status='todo' WHERE id=?", (self.bid(r),))  # sent back on the board
        self.assertEqual(cd.sync(self.db), 1)
        self.assertEqual(self.row(r["id"])["status"], "todo")

    def test_a_merged_repeat_follows_its_keeper_and_a_deleted_one_is_cancelled_with_the_reason(self):
        a, b, c = self.on_board[:3]
        self.db.q("UPDATE mw_tasks SET detail=? WHERE id=?", (f"Run it.\n\nMerged duplicates (same objective, candidate and acceptance): #{self.bid(a)} (Rex)", self.bid(b)))
        self.db.q("DELETE FROM mw_tasks WHERE id IN (?,?)", (self.bid(a), self.bid(c)))
        self.assertEqual(cd.sync(self.db), 2)
        self.assertEqual((self.row(a["id"])["status"], self.row(a["id"])["ref"]), ("todo", f"mw_task:{self.bid(b)}"))
        self.assertIn("merged into", self.row(a["id"])["history"])
        self.assertEqual(self.row(c["id"])["status"], "cancelled")
        self.assertIn(f"#{self.bid(c)} was deleted", self.row(c["id"])["summary"])

    def test_a_keeper_note_naming_a_longer_id_is_not_a_match(self):
        a = self.on_board[0]
        self.db.q("UPDATE mw_tasks SET detail=? WHERE id=?", (f"Merged duplicates (same objective): #{self.bid(a)}9", self.bid(self.on_board[1])))
        self.db.q("DELETE FROM mw_tasks WHERE id=?", (self.bid(a),))
        cd.sync(self.db)
        self.assertEqual(self.row(a["id"])["status"], "cancelled")

    def test_why_names_what_holds_a_board_task_and_whose_move_it_is(self):
        ids = [self.bid(r) for r in self.on_board[:4]]
        self.db.q("UPDATE mw_tasks SET hold='failed' WHERE id=?", (ids[0],))
        self.db.q("UPDATE mw_tasks SET hold='retry' WHERE id=?", (ids[1],))
        self.db.q("UPDATE mw_tasks SET agent_id=2 WHERE id=?", (ids[3],))
        tasks = {t["ref"]: t for t in cm.missions(self.ch, ME)["tasks"]}
        w = lambda i: tasks[f"mw_task:{i}"]["why"]
        self.assertEqual(w(ids[0])["state"], "failed"); self.assertIn("gave up", w(ids[0])["text"])
        self.assertEqual(w(ids[1])["state"], "queued"); self.assertIn("Autoloop", w(ids[1])["text"])
        self.assertIn("waiting for its Director", w(ids[2])["text"])
        self.assertIn("assigned", w(ids[3])["text"])
        self.db.q("UPDATE mw_comps SET autopilot=0")
        tasks = {t["ref"]: t for t in cm.missions(self.ch, ME)["tasks"]}
        self.assertEqual(w(ids[2])["state"], "waiting"); self.assertIn("autopilot is off", w(ids[2])["text"])
        self.db.q("UPDATE mw_comps SET paused=1")
        tasks = {t["ref"]: t for t in cm.missions(self.ch, ME)["tasks"]}
        self.assertIn("team is paused", w(ids[2])["text"])
        self.assertEqual(cd.owner(w(ids[2])["state"]), "you")

    def test_counts_split_the_systems_stalls_from_yours(self):
        old = time.time() - 2 * cd.STALE
        self.db.q("UPDATE ctl_tasks SET updated=?", (old,))
        c = cd.counts(self.db, ME["id"], "hybrid")
        self.assertEqual((c["open"], c["moving"], c["system"], c["yours"]), (12, 0, 12, 0))  # all on boards for their Directors, an hour on
        self.db.q("UPDATE mw_comps SET autopilot=0")
        c = cd.counts(self.db, ME["id"], "hybrid")
        self.assertEqual((c["system"], c["yours"]), (0, 12))  # nobody hands them out: autopilot is off, your move
        self.assertEqual(c["reasons"][0]["owner"], "you")
        self.db.q("UPDATE mw_tasks SET status='working'")
        self.assertEqual(cd.counts(self.db, ME["id"], "hybrid")["moving"], 12)

    def test_the_dispatchers_pass_syncs_even_with_dispatch_off(self):
        r = self.on_board[0]
        self.db.q("UPDATE mw_tasks SET status='done' WHERE id=?", (self.bid(r),))
        with unittest.mock.patch.object(cd, "ENABLED", False):
            self.assertEqual(cd.tick(self.ch), 0)
        self.assertEqual(self.row(r["id"])["status"], "done")

    def test_a_running_board_task_is_not_written_running(self):
        """'running' in ctl_tasks takes one of the user's run slots (control_hub RUNS_PER_USER): only final states are written."""
        self.db.q("UPDATE mw_tasks SET status='working'")
        self.assertEqual(cd.sync(self.db), 0)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ctl_tasks WHERE status='running'", one=True)["n"], 0)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
