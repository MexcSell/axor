"""D-004 completion, milestone D4.4: delivery of a persistent mission (D004_COMPLETION_SPEC.md §10 D4.4).

- Delivery happens only on the Owner's (or a delegate's) approval of a D4.4 delivery request; a D4.3 confirmation ("recorded only")
  never delivers. A request that no longer matches the latest cycle is refused.
- Criteria met is verified from the request's cycle evidence (no model reviewer); an end without the criteria is labelled
  "Ended without meeting its criteria" on the card, verification, report and lesson.
- The status change and the freed slot are one statement; the lesson carries the outcome label and is written once; history stays
  readable and deletion is refused. Crashes, an older image and a lost emit all end in exactly one delivery.
"""
import json, os, sys, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from fastapi import HTTPException  # noqa: E402

from app import missions, orchestrator  # noqa: E402
from test_mission_cycles import Base, DAY  # noqa: E402
from test_mission_persistent_evidence import OWNER, TEAM_ACCOUNT, WID, chain_measure  # noqa: E402


class Delivery(Base):
    def met(self, **kw):
        """A mission whose criteria are met (rank 1 ≤ 3) for N = 2 cycles: a D4.4 "criteria met" request waits."""
        self.fresh(mine_em=0.95)
        mid = self.create([chain_measure(target=3)], hold_cycles=2, **kw)
        self.cycle(mid, "baseline"); rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 1)
        return mid

    def dreq(self, mid, label=missions.DELIVER_MET):
        return [r for r in self.reqs(mid, "deliver") if r["label"] == label]

    def approve(self, mid, r, who=OWNER, ok=True):
        return self.mx.decide(self.me(who), r["id"], missions.DecideIn(approve=ok, hash=r["hash"]))

    def lessons(self, mid): return self.db.q("SELECT kind, text, outcome FROM mx_lessons WHERE mission_id=?", (mid,))

    def test_criteria_met_is_delivered_verified_from_the_cycle_frees_the_slot_and_keeps_history(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.db.q("INSERT INTO mw_tasks (comp_id, title, status, created) VALUES (?, 'x', 'todo', ?)", (WID, time.time()))
        before = self.snapshot_team()
        with mock.patch.object(missions.Missions, "_ask", side_effect=AssertionError("model")):
            self.approve(mid, r)
            self.assertEqual(self.m(mid)["status"], "monitoring")  # applied by the outbox, not inline
            self.process()
        m = self.m(mid)
        self.assertEqual((m["status"], m["outcome"], m["persistent_team"]), ("delivered", "verified", None))
        v = m["verification"]
        self.assertEqual((v["label"], v["rule"], v["cycle"], v["model"]), ("Criteria met", 1, 2, None))
        self.assertEqual(v["rests_on"], ["owner_attested_key"])
        self.assertEqual(v["results"][0]["status"], "met")
        self.assertEqual(v["last_cycle"]["n"], 2)  # merged, not replaced
        self.assertEqual(m["report"]["kind"], "persistent")
        self.assertIn("Criteria met", m["deliverable"]["text"])
        (ls,) = self.lessons(mid)
        self.assertEqual((ls["kind"], ls["outcome"]), ("worked", "verified"))
        self.assertTrue(ls["text"].startswith(f"[mx:{mid}:deliver]"))
        self.assertEqual(self.snapshot_team(), before)
        card = self.mx.state(self.me(OWNER), mid)["mission"]
        self.assertEqual(card["outcome_label"], "Criteria met")
        # the slot is free: a new persistent mission for the team; the old one's history stays and can't be deleted
        self.create([chain_measure(target=3)])
        with self.assertRaises(HTTPException): self.mx.delete(self.me(OWNER), mid, "")
        self.assertEqual(len(self.records(mid)), 2)
        self.mx._looked.clear()
        self.assertIsNone(self.mx._cycle_tick(self.m(mid)))  # no cycles after delivery (tick only reads monitoring)
        self.process()
        self.assertEqual(len(self.lessons(mid)), 1)
        self.assertTrue(self.db.q("SELECT 1 FROM audit WHERE action='mission.deliver'", one=True))

    def test_ended_without_meeting_its_criteria_is_labelled_everywhere_and_never_verified(self):
        self.fresh()  # rank 7, target ≤ 3: FAIL
        mid = self.create([chain_measure(target=3)])
        self.cycle(mid, "baseline")
        self.mx.deliver_now(self.me(OWNER), mid)
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["decision"]["rule"], 2)
        self.process()
        (r,) = self.dreq(mid, missions.DELIVER_ENDED)
        self.approve(mid, r); self.process()
        m = self.m(mid)
        self.assertEqual((m["status"], m["outcome"]), ("delivered", "failed"))
        label = missions.ENDED_LABEL
        self.assertEqual(m["verification"]["label"], label)
        self.assertEqual(self.mx.state(self.me(OWNER), mid)["mission"]["outcome_label"], label)
        self.assertIn(label, m["report"]["summary"])
        self.assertIn(label, m["deliverable"]["text"])
        (ls,) = self.lessons(mid)
        self.assertIn(label.lower(), ls["text"])
        self.assertNotEqual(ls["outcome"], "verified")

    def test_a_pass_not_held_long_enough_at_the_end_is_partial_not_verified(self):
        self.fresh(mine_em=0.95)
        mid = self.create([chain_measure(target=3)], hold_cycles=3)
        self.cycle(mid, "baseline")
        self.mx.deliver_now(self.me(OWNER), mid)
        self.mx._cycle_tick(self.m(mid)); self.process()
        (r,) = self.dreq(mid, missions.DELIVER_ENDED)
        self.approve(mid, r); self.process()
        self.assertEqual(self.m(mid)["outcome"], "partial")

    def test_a_rejected_request_delivers_nothing_and_the_mission_keeps_monitoring(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.approve(mid, r, ok=False); self.process()
        self.assertEqual(self.m(mid)["status"], "monitoring")
        self.assertEqual(self.lessons(mid), [])

    def test_deliver_now_asks_again_after_a_rejected_criteria_met_request(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.approve(mid, r, ok=False)
        self.cycle(mid)  # still met, inside the window: not asked again
        self.assertEqual(len(self.dreq(mid)), 1)
        self.mx.deliver_now(self.me(OWNER), mid)
        self.mx._looked.clear()
        rec = self.mx._cycle_tick(self.m(mid)); self.process()
        self.assertEqual((rec["trigger"], rec["decision"]["rule"]), ("final", 1))
        self.assertEqual([x["status"] for x in self.dreq(mid)], ["rejected", "pending"])

    def test_a_d43_confirmation_never_delivers_and_the_next_cycle_asks_again(self):
        mid = self.met()
        for r in self.reqs(mid, "deliver"): self.db.q("DELETE FROM mx_requests WHERE id=?", (r["id"],))
        # what D4.3 wrote: label "Criteria met", approved, "recorded only"
        self.db.q("""INSERT INTO mx_requests (mission_id, user_id, kind, label, action, artifact, hash, status, created, expires, decided)
                     VALUES (?,?,'deliver','Criteria met','Confirm delivery','x','h43','approved',?,?,?)""", (mid, TEAM_ACCOUNT, time.time(), time.time() + DAY, time.time()))
        self.mx._looked.clear()
        self.assertNotEqual(self.mx._cycle_tick(self.m(mid)), "delivering"); self.process()
        self.assertEqual(self.m(mid)["status"], "monitoring")
        self.cycle(mid)  # criteria still met: a D4.4 request, despite the approved D4.3 one
        self.assertEqual(len(self.dreq(mid)), 1)

    def test_a_stale_criteria_met_approval_is_refused(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.db.q("DELETE FROM mh_samples"); self.cycle(mid)  # UNKNOWN: the hold is lost
        with self.assertRaises(HTTPException) as c: self.approve(mid, r)
        self.assertEqual(c.exception.status_code, 409)
        self.assertEqual(self.dreq(mid)[0]["status"], "pending")

    def test_a_criteria_met_approval_on_an_older_criteria_version_is_refused(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(hold_cycles=1))  # new version; the next cycle meets it again, on v2
        self.cycle(mid)
        with self.assertRaises(HTTPException) as c: self.approve(mid, r)
        self.assertEqual(c.exception.status_code, 409)

    def test_an_ended_approval_after_the_criteria_were_met_is_refused(self):
        self.fresh()
        mid = self.create([chain_measure(target=3)], hold_cycles=1)
        self.cycle(mid, "baseline")
        self.mx.deliver_now(self.me(OWNER), mid); self.mx._cycle_tick(self.m(mid)); self.process()
        (r,) = self.dreq(mid, missions.DELIVER_ENDED)
        self.fresh(mine_em=0.95); self.cycle(mid)  # met now
        with self.assertRaises(HTTPException): self.approve(mid, r)

    def test_the_team_account_cannot_deliver(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        with self.assertRaises(HTTPException) as c: self.approve(mid, r, who=TEAM_ACCOUNT)
        self.assertEqual(c.exception.status_code, 404)

    def test_crash_point_8_between_verification_and_the_status_change_and_after_it(self):
        for point in ("deliver:verified", "deliver:status"):
            with self.subTest(point=point):
                self.db.q("UPDATE mx_missions SET persistent_team=NULL, status='cancelled' WHERE status='monitoring'")
                mid = self.met()
                (r,) = self.dreq(mid)
                self.approve(mid, r)
                missions.FAULT.add(point)
                try: self.process()
                except missions.Crash: pass
                self.restart(); self.process(); self.process()
                m = self.m(mid)
                self.assertEqual((m["status"], m["outcome"]), ("delivered", "verified"))
                self.assertEqual(len(self.lessons(mid)), 1)
                self.assertEqual(len(self.db.q("SELECT id FROM mx_events WHERE mission_id=? AND kind='delivered'", (mid,))), 1)
                self.assertEqual(len(self.db.q("SELECT id FROM audit WHERE action='mission.deliver' AND target=?", (f"mission {mid}",))), 1)

    def test_an_older_image_marking_the_delivery_done_unapplied_is_recovered(self):
        for note in ({"note": "no handler: recorded"}, {"applied": False, "note": "unknown effect 'deliver'"}):  # RC1, then D4.3
            with self.subTest(note=note):
                self.db.q("UPDATE mx_missions SET persistent_team=NULL, status='cancelled' WHERE status='monitoring'")
                mid = self.met()
                (r,) = self.dreq(mid)
                self.approve(mid, r)
                self.db.q("UPDATE io_events SET status='done', result=? WHERE key=?", (json.dumps(note), f"mx:{mid}:deliver:{r['id']}"))
                self.restart()
                self.mx._looked.clear()
                self.assertEqual(self.mx._cycle_tick(self.m(mid)), "delivering")
                self.process()
                self.assertEqual(self.m(mid)["status"], "delivered")
                self.assertEqual(len(self.lessons(mid)), 1)

    def test_a_lost_emit_is_recovered_by_the_clock_even_while_evaluation_is_paused(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.mx.pause(self.me(OWNER), mid)
        with mock.patch.object(orchestrator, "emit", return_value=None): self.approve(mid, r)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM io_events WHERE key LIKE ?", (f"mx:{mid}:deliver:%",), one=True)["n"], 0)
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid)), "delivering")
        self.process()
        self.assertEqual(self.m(mid)["status"], "delivered")

    def test_two_delivery_requests_give_one_delivery(self):
        mid = self.met()
        (r1,) = self.dreq(mid)
        later = time.time() + 8 * DAY
        self.sample(self.field(mine_em=0.95), age_h=-8 * 24 + 0.5)  # still first, a week on
        self.cycle(mid, now=later)  # r1 is out of its window: a second request is raised
        r1, r2 = self.dreq(mid)
        with self.assertRaises(HTTPException): self.mx.deliver_now(self.me(OWNER), mid)  # a delivery request is waiting
        self.approve(mid, r2)
        with self.assertRaises(HTTPException) as c: self.approve(mid, r1)
        self.assertEqual(c.exception.status_code, 409)  # a delivery is already under way
        self.process()
        self.assertEqual(self.m(mid)["status"], "delivered")
        self.assertEqual(len(self.lessons(mid)), 1)
        self.assertEqual(self.dreq(mid)[0]["status"], "lapsed")  # the other request closes with the delivery

    def test_cancel_and_delivery_cannot_both_win(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.approve(mid, r)
        self.mx.cancel(self.me(OWNER), mid)  # cancel first: the delivery then does nothing
        self.process()
        m = self.m(mid)
        self.assertEqual(m["status"], "cancelled")
        self.assertEqual(self.lessons(mid), [])
        mid2 = self.met()
        (r2,) = self.dreq(mid2)
        self.approve(mid2, r2); self.process()  # delivery first: cancel is refused
        with self.assertRaises(HTTPException): self.mx.cancel(self.me(OWNER), mid2)
        self.assertEqual(self.m(mid2)["status"], "delivered")

    def test_deliver_now_after_the_deadlines_final_cycle_asks_again(self):
        self.fresh()
        mid = self.create([chain_measure(target=3)], deadline=time.time() + 120)
        self.cycle(mid, "baseline")
        self.db.q("UPDATE mx_missions SET deadline=? WHERE id=?", (time.time() - 1, mid))
        self.mx._looked.clear(); self.mx._cycle_tick(self.m(mid)); self.process()  # the deadline's final cycle
        (r,) = self.dreq(mid, missions.DELIVER_ENDED)
        with self.assertRaises(HTTPException): self.mx.deliver_now(self.me(OWNER), mid)  # its request is still waiting
        self.approve(mid, r, ok=False)
        self.mx.deliver_now(self.me(OWNER), mid)
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "final")

    def test_a_persistent_delivery_is_not_an_engines_track_record(self):
        mid = self.met()
        (r,) = self.dreq(mid)
        self.approve(mid, r); self.process()
        past = self.db.q("""SELECT id FROM mx_missions WHERE user_id=? AND status='delivered' AND (understanding IS NULL OR understanding NOT LIKE ?)""",
                         (TEAM_ACCOUNT, '%"persistent":true%'))
        self.assertEqual(past, [])



class IdFloor(Base):
    """Mission ids are never reused: a new mission never inherits a deleted one's lessons, events or runs (D44 report §6.1)."""
    def test_a_new_mission_starts_after_every_referenced_id_and_the_counter_only_rises(self):
        for t in ("mx_events", "mx_requests", "mx_lessons", "mx_missions"): self.db.q(f"DELETE FROM {t}")
        self.db.q("INSERT INTO mx_lessons (user_id, mission_id, kind, text, outcome, created) VALUES (?, 6, 'worked', 'old', 'verified', ?)", (OWNER, time.time()))
        self.db.q("""CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, system TEXT, owner_id INTEGER, ref TEXT, corr TEXT, team TEXT,
                     kind TEXT, status TEXT, tokens INTEGER DEFAULT 0, cost REAL, started REAL, finished REAL)""")
        self.db.q("INSERT INTO ac_runs (corr, status, started, finished) VALUES ('mx:8', 'done', 1, 2)")
        self.db.q("INSERT INTO ac_runs (ref, status, started, finished) VALUES ('mx:9', 'failed', 1, 2)")  # older runs: the id in ref only
        orchestrator.get().emit(OWNER, "knowledge.written", "old:mx:7", corr="mx:7", status="done")
        mx = missions.Missions(self.db, hub=self.mx.hub, wf=None, ia=None, mw=self.mx.mw)
        self.assertTrue(self.db.q("SELECT 1 FROM audit WHERE action='mission.id_floor'", one=True))
        mx.readiness = self.mx.readiness
        self.fresh()
        self.mx = mx
        mid = self.create([chain_measure(target=3)])
        self.assertGreater(mid, 9)
        n = self.db.q("SELECT COUNT(*) n FROM audit WHERE action='mission.id_floor'", one=True)["n"]
        missions.Missions(self.db, hub=self.mx.hub, wf=None, ia=None, mw=self.mx.mw)  # nothing behind any more: no change, no audit row
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM audit WHERE action='mission.id_floor'", one=True)["n"], n)


if __name__ == "__main__":
    unittest.main()
