"""G5-3 R3.3: the risk register reaches persistent mission cycles (G5_3_4_5_DEPENDENCY_PLAN.md §2, Owner decision G3-7, 2026-11-13).

- A cycle records the open register rows that bear on its mission: the team's and the mission's own rows (any source), organization
  rows of the layers a team's work runs on (missions.RISK_LAYERS), and alerts on the team's own campaign. Nothing else.
- G3-7 kept: fed rows are never critical. A row that is new since the last cycle (first seen, or reopened) triggers an early cycle,
  under D4.3's existing limit (at most one early cycle per 2 h). A row resolving doesn't.
- A cycle recorded before R3.3 has no row list: an upgrade starts no early cycle.
- Reading the register writes nothing to it.
"""
import json, os, sys, time, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from app import missions, orchestrator  # noqa: E402
from test_mission_cycles import Base  # noqa: E402
from test_mission_persistent_evidence import TEAM_ACCOUNT, WID, chain_measure  # noqa: E402

ORG = orchestrator.ORG_OWNER


class Risks(Base):
    def setUp(self):
        super().setUp()
        self.camp = self.db.q("SELECT campaign_id FROM mw_comps WHERE id=?", (WID,), one=True)["campaign_id"]

    def row(self, uid, rkey, mission=None, layer="execution", source="sandbox", impact=None):
        self.orc.risk_upsert(uid, rkey, evidence={"n": 3}, mission=mission, layer=layer, source=source, title=f"risk {rkey}",
                             severity="high", critical=0, impact=impact or {})
        return self.db.q("SELECT id FROM io_risks WHERE owner_id=? AND rkey=?", (uid, rkey), one=True)["id"]

    def baseline(self):
        self.fresh()
        mid = self.ok_mission()
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "baseline")
        self.process()
        return mid

    def tick(self, mid, now=None):
        self.mx._looked.clear()
        return self.mx._cycle_tick(self.m(mid), now=now)

    def test_a_cycle_records_the_rows_that_bear_on_its_mission_and_no_others(self):
        mid = self.baseline()
        mine = [self.row(TEAM_ACCOUNT, "sbx:comp:%d:busy" % WID, mission=f"comp:{WID}"),
                self.row(ORG, "hq:1", layer="execution", source="hq"),
                self.row(TEAM_ACCOUNT, "budget:1", layer="workforce", source="budget"),
                self.row(TEAM_ACCOUNT, "campaign:1", layer="mission", source="campaign", impact={"campaign": self.camp})]
        self.row(TEAM_ACCOUNT, "sbx:comp:999:busy", mission="comp:999")            # another team
        self.row(ORG, "hq:2", layer="knowledge", source="hq")                      # a layer the team's work doesn't run on
        self.row(TEAM_ACCOUNT, "campaign:2", layer="mission", source="campaign", impact={"campaign": self.camp + 100})  # another campaign
        self.row(77, "budget:other", layer="execution", source="budget")            # someone else's account
        gone = self.row(ORG, "hq:3", layer="execution", source="hq")
        self.orc.risk_resolve(ORG, "hq:3", {"by": "test"})
        before = self.db.q("SELECT id, status, updated FROM io_risks ORDER BY id")
        rec = self.cycle(mid)
        self.assertEqual(sorted(rec["risks"]["ids"]), sorted(mine))
        self.assertNotIn(gone, rec["risks"]["ids"])
        self.assertEqual(rec["risks"]["open"], 4)
        self.assertEqual(rec["risks"]["critical"], 0)                               # G3-7: fed rows stay non-critical
        scopes = {r["rkey"]: r["scope"] for r in rec["risks"]["rows"]}
        self.assertEqual(scopes["hq:1"], "organization")
        self.assertEqual(scopes["sbx:comp:%d:busy" % WID], f"comp:{WID}")
        self.assertEqual(before, self.db.q("SELECT id, status, updated FROM io_risks ORDER BY id"))  # read only

    def test_a_new_row_makes_one_early_cycle_and_names_it_then_waits_2h(self):
        mid = self.baseline()
        self.assertIsNone(self.tick(mid))                                           # nothing new: no cycle
        rid = self.row(TEAM_ACCOUNT, "sbx:comp:%d:busy" % WID, mission=f"comp:{WID}")
        rec = self.tick(mid)
        self.assertEqual(rec["trigger"], "early")
        self.assertEqual(rec["new_risks"], [rid])
        self.assertIn("new risk row", rec["decision"]["reason"])
        self.process()
        self.assertIn("new risk row", self.lines(mid)[-1]["text"])
        self.assertIsNone(self.tick(mid))                                           # the same row seen again isn't new
        self.row(ORG, "hq:9", layer="workforce", source="hq")
        self.assertIsNone(self.tick(mid))                                           # new, but inside 2 h of the early cycle
        later = self.tick(mid, now=time.time() + missions.EARLY_GAP + 60)
        self.assertEqual(later["trigger"], "early")                                 # after the gap it counts
        self.assertEqual(len(self.records(mid)), 3)

    def test_a_reopened_row_is_new_and_a_resolved_one_starts_nothing(self):
        rid = self.row(TEAM_ACCOUNT, "sbx:comp:%d:busy" % WID, mission=f"comp:{WID}")
        mid = self.baseline()
        self.orc.risk_resolve(TEAM_ACCOUNT, "sbx:comp:%d:busy" % WID, {"by": "test"})
        self.assertIsNone(self.tick(mid))                                           # resolving isn't a reason for an early cycle
        self.cycle(mid)                                                             # a scheduled cycle records it gone
        self.row(TEAM_ACCOUNT, "sbx:comp:%d:busy" % WID, mission=f"comp:{WID}")    # reopens
        rec = self.tick(mid, now=time.time() + missions.EARLY_GAP + 60)
        self.assertEqual((rec["trigger"], rec["new_risks"]), ("early", [rid]))

    def test_an_upgrade_from_a_cycle_without_a_row_list_starts_no_early_cycle(self):
        mid = self.baseline()
        for r in self.db.q("SELECT id, payload FROM io_events WHERE kind='mission.cycle'"):  # in Python: no engine-specific JSON functions
            p = json.loads(r["payload"]); p.pop("risks", None)
            self.db.q("UPDATE io_events SET payload=? WHERE id=?", (json.dumps(p), r["id"]))
        self.assertNotIn("risks", self.records(mid)[-1])
        self.row(TEAM_ACCOUNT, "sbx:comp:%d:busy" % WID, mission=f"comp:{WID}")
        self.assertIsNone(self.tick(mid))
        rec = self.cycle(mid)                                                       # the next cycle starts the list
        self.assertEqual(rec["risks"]["open"], 1)

    def test_no_register_reads_as_unknown_not_none(self):
        mid = self.baseline()
        real = self.mx._has_t
        self.mx._has_t = lambda t: False if t == "io_risks" else real(t)
        try: rec = self.cycle(mid)
        finally: self.mx._has_t = real
        self.assertIn("error", rec["risks"])
        self.assertNotIn("ids", rec["risks"])


    def test_early_cycles_started_by_risk_rows_alone_never_advance_the_hold_window(self):
        """K-34: N consecutive passing cycles. An early cycle started only by a new register row brings no new evidence about the
        competition, so it neither advances nor resets the hold count; three of them never make 'criteria met'."""
        mid = self.baseline()
        t = time.time()
        self.fresh(mine_em=0.95)                                                      # ranks first: the measure passes
        rec = self.tick(mid, now=t)
        self.assertEqual((rec["trigger"], rec["dimensions"]["competition"]["value"], rec["hold"]["consecutive_pass"]), ("early", "PASS", 1))
        self.process()
        for i in range(3):  # the 2 h early-cycle limit set to 0 here, so the evidence stays fresh (the clock doesn't move)
            self.row(TEAM_ACCOUNT, f"sbx:comp:{WID}:k{i}", mission=f"comp:{WID}")
            with mock.patch.object(missions, "EARLY_GAP", 0): rec = self.tick(mid, now=t + i + 1)
            self.assertEqual((rec["trigger"], len(rec["new_risks"])), ("early", 1))
            self.assertEqual(rec["hold"]["consecutive_pass"], 1)                      # held, not advanced
            self.assertNotEqual(rec["decision"]["kind"], "criteria_met")
            self.process()


    def test_a_risk_only_early_cycle_does_not_postpone_the_scheduled_cycle(self):
        """G3-19 follow-up: the next scheduled cycle is timed from the last cycle that wasn't risk-only, so new register rows
        can't keep pushing it out while the hold count stands still (a passing mission would never reach 'criteria met')."""
        self.fresh()
        mid = self.create([chain_measure(target=5, max_age_h=6)])                     # a 6 h window: the clock moves an hour here
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "baseline"); self.process()
        self.mx.patch(self.me(missions_owner()), mid, missions.PatchIn(cycle_hours=1, hold_cycles=2))
        t = time.time()
        self.fresh(mine_em=0.95)                                                      # passes: count 1
        with mock.patch.object(missions, "EARLY_GAP", 0):
            rec = self.tick(mid, now=t)
            self.assertEqual((rec["trigger"], rec["hold"]["consecutive_pass"]), ("early", 1)); self.process()
            self.row(TEAM_ACCOUNT, f"sbx:comp:{WID}:late", mission=f"comp:{WID}")
            rec = self.tick(mid, now=t + 0.9 * 3600)                                  # risk-only early cycle at 54 min
            self.assertEqual((rec["trigger"], rec["hold"]["consecutive_pass"]), ("early", 1)); self.process()
            self.assertAlmostEqual(self.mx.cycles(self.me(missions_owner()), mid)["next_due"], t + 3600, delta=1)  # the page shows the same
            rec = self.tick(mid, now=t + 1.05 * 3600)                                 # due from the passing cycle, not the risk-only one
        self.assertIsNotNone(rec)
        self.assertIsNotNone(rec)
        self.assertEqual((rec["trigger"], rec["hold"]["consecutive_pass"], rec["decision"]["kind"]), ("scheduled", 2, "criteria_met"))


def missions_owner():
    from test_mission_persistent_evidence import OWNER
    return OWNER


if __name__ == "__main__":
    unittest.main()
