"""D-004 completion, milestone D4.3: a persistent mission's cycles, decisions and effects (D4_3_IMPLEMENTATION_SPEC.md).

- A cycle evaluates stored evidence, readiness, the team's work and spend, records exactly one decision by fixed rules (no model
  call, no network) as an io_events row written once, then applies its effects (line, request, advice, summary) once each, by key.
- Crash recovery (CYCLE_AND_RECOVERY_ARCHITECTURE.md §6): a cycle cut off at any point leaves one decision and every effect once.
- Rules: 1 criteria met after N passing cycles (K-34), 2 ended, 3 one request per dependency per window, 4 corrective request
  (K-32c), 5 replan advice (K-25), 6 continue. UNKNOWN is never success; self-reported evidence never counts.
- Mission Control never writes a team's tasks, runs, agents, board or campaign.
- Delivery decisions raise a confirmation request and change no state (K-36).
"""
import json, os, sys, time, types, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from fastapi import HTTPException  # noqa: E402

from app import missions, mining_work, orchestrator  # noqa: E402
from test_mission_ref import ME as BOARD_ME, WID as BOARD_WID, Base as BoardBase  # noqa: E402
from test_mission_persistent_evidence import (  # noqa: E402
    ADMIN, HOT, NETUID, OWNER, TEAM_ACCOUNT, WID, Base as EvidenceBase, chain_measure, ingest_measure)

DAY = 86400


class Base(EvidenceBase):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("ALTER TABLE mh_campaigns ADD COLUMN status TEXT")
        q("UPDATE mh_campaigns SET status='live'")
        q("UPDATE mw_comps SET paused=0")
        q("""CREATE TABLE IF NOT EXISTS mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, title TEXT, status TEXT, agent_id INTEGER,
             mission TEXT, note TEXT, closed_as TEXT, done_at REAL, created REAL)""")
        q("""CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, task_id INTEGER, status TEXT, started REAL,
             finished REAL)""")
        q("CREATE TABLE IF NOT EXISTS mw_agents (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, name TEXT)")
        self.mx.readiness = lambda uid, wid: {"state": "PASS", "blocked": []}
        self.orc = orchestrator.get()
        missions.FAULT.clear()

    def tearDown(self):
        missions.FAULT.clear()
        super().tearDown()

    def m(self, mid): return self.mx._m(mid)

    def fresh(self, mine_em=0.05, **kw):
        """A fresh sample: our key ranks 7th by emission (0.05); lower emission ranks lower."""
        self.sample(self.field(mine_em=mine_em, **kw))

    def cycle(self, mid, trigger="scheduled", now=None, process=True):
        """One cycle with a forced trigger (the clock's own trigger logic is tested on its own), then its effects applied."""
        now = now or time.time()
        m = self.m(mid)
        self.assertTrue(self.mx._claim(mid))
        try: rec = self.mx._cycle(m, trigger, self.mx._recent(mid), now, self.mx._evidence(m, now))
        finally: self.mx._release(mid)
        if process: self.process()
        return rec

    def process(self):
        self.db.q("UPDATE io_events SET next_at=0 WHERE status='pending'")
        return self.orc.process()

    def restart(self):
        """A new server process: the orchestrator resets running events, Mission Control clears leases and reconciles."""
        orchestrator.init(self.db)
        self.orc = orchestrator.get()
        mx = missions.Missions(self.db, hub=self.mx.hub, wf=None, ia=None, mw=self.mx.mw)
        mx._ask, mx.readiness = self.mx._ask, self.mx.readiness
        mx._thread = True  # no clock thread in tests
        self.db.q("UPDATE mx_missions SET lease_until=NULL WHERE status IN ('queued','running','monitoring')")
        mx._reconcile_effects()
        self.mx = mx
        return mx

    def records(self, mid): return self.mx._recent(mid, 1000)[::-1]
    def effects(self, mid): return self.db.q("SELECT key, status, result FROM io_events WHERE corr=? AND kind='mission.effect' ORDER BY id", (f"mx:{mid}",))
    def lines(self, mid, kind="cycle"): return self.db.q("SELECT text FROM mx_events WHERE mission_id=? AND kind=? ORDER BY id", (mid, kind))
    def reqs(self, mid, kind=None):
        return self.db.q("SELECT * FROM mx_requests WHERE mission_id=?" + (" AND kind=?" if kind else "") + " ORDER BY id", (mid, kind) if kind else (mid,))

    def snapshot_team(self):
        out = {}
        for t in ("mw_tasks", "mw_runs", "mw_comps", "mw_agents", "mh_campaigns"):
            out[t] = json.dumps(self.db.q(f"SELECT * FROM {t} ORDER BY id"), default=str, sort_keys=True)
        return out

    def ok_mission(self, **kw):
        """Attested key, ranked 7th; the target rank ≤ 5 isn't met yet; readiness PASS, dispatch on: no dependency for rule 3."""
        return self.create([chain_measure(target=5)], **kw)


class Cycles(Base):
    def test_first_look_records_a_baseline_cycle_and_its_effects_apply_once(self):
        self.fresh()
        mid = self.ok_mission()
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "baseline")
        self.process()
        r = self.records(mid)
        self.assertEqual([(c["n"], c["trigger"], c["decision"]["kind"]) for c in r], [(1, "baseline", "continue")])
        self.assertEqual({e["status"] for e in self.effects(mid)}, {"done"})
        self.assertEqual(len(self.lines(mid)), 1)
        self.assertEqual(self.m(mid)["verification"]["last_cycle"]["n"], 1)
        self.process()  # nothing applies twice
        self.assertEqual(len(self.lines(mid)), 1)

    def test_criterion_1_unchanged_samples_make_no_early_cycle_and_a_change_makes_one_every_2h_at_most(self):
        self.fresh()
        mid = self.ok_mission()
        self.mx._cycle_tick(self.m(mid)); self.process()
        for _ in range(10):  # ten samples that don't change the result signature
            self.fresh()
            self.mx._looked.clear()
            self.assertIsNone(self.mx._cycle_tick(self.m(mid)))
        self.fresh(mine_em=0.95)  # now first: the rank passes, the signature changes
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "early")
        self.process()
        self.fresh()  # back: another change, but inside 2 h of the early one
        self.mx._looked.clear()
        self.assertIsNone(self.mx._cycle_tick(self.m(mid)))
        self.assertEqual(len(self.records(mid)), 2)

    def test_a_new_criteria_version_makes_an_early_cycle(self):
        self.fresh()
        mid = self.ok_mission()
        self.mx._cycle_tick(self.m(mid)); self.process()
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(hold_cycles=2))
        self.mx._looked.clear()
        rec = self.mx._cycle_tick(self.m(mid))
        self.assertEqual((rec["trigger"], rec["hold"]["required"]), ("early", 2))
        self.process()
        before = self.mx._signature(self.mx._evidence(self.m(mid)))
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(director_context=True))  # a switch, not a version: the signature stays
        self.assertEqual(self.mx._signature(self.mx._evidence(self.m(mid))), before)

    def test_a_scheduled_cycle_comes_after_cycle_hours(self):
        self.fresh()
        mid = self.ok_mission(cycle_hours=1)
        self.mx._cycle_tick(self.m(mid)); self.process()
        self.mx._looked.clear()
        self.assertIsNone(self.mx._cycle_tick(self.m(mid), time.time() + 1800))
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid), time.time() + 3700)["trigger"], "scheduled")

    def test_the_clock_looks_at_most_once_a_minute(self):
        self.fresh()
        mid = self.ok_mission()
        self.mx._cycle_tick(self.m(mid))
        self.assertIsNone(self.mx._cycle_tick(self.m(mid)))  # within CYCLE_CHECK: not even a read

    def test_evaluation_paused_runs_no_cycle_and_a_pending_effect_holds_the_next(self):
        self.fresh()
        mid = self.ok_mission()
        self.mx.pause(self.me(OWNER), mid)
        self.assertIsNone(self.mx._cycle_tick(self.m(mid)))
        self.mx.resume(self.me(OWNER), mid)
        self.mx._looked.clear()
        self.mx._cycle_tick(self.m(mid))  # effects pending, not processed
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid), time.time() + 2 * DAY), "waiting")

    def test_a_dead_effect_blocks_cycles_until_the_owner_retries_it(self):
        self.fresh()
        mid = self.ok_mission()
        self.mx._cycle_tick(self.m(mid))
        key = f"mx:{mid}:cycle:1:line"
        self.db.q("UPDATE io_events SET status='dead', attempts=5, error='boom' WHERE key=?", (key,))
        self.process()
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid), time.time() + 2 * DAY), "waiting")
        st = self.mx.state(self.me(OWNER), mid)["mission"]
        self.assertEqual([e["key"] for e in st["persistent"]["failed_effects"]], [key])
        eid = st["persistent"]["failed_effects"][0]["id"]
        with self.assertRaises(HTTPException) as c: self.mx.retry_effect(self.me(TEAM_ACCOUNT), mid, eid)
        self.assertEqual(c.exception.status_code, 403)
        self.mx.retry_effect(self.me(OWNER), mid, eid)
        self.process()
        self.assertEqual(len(self.lines(mid)), 1)
        self.assertTrue(self.db.q("SELECT 1 FROM audit WHERE action='mission.effect_retry'", one=True))
        self.mx._looked.clear()
        self.assertEqual(self.mx._cycle_tick(self.m(mid), time.time() + 2 * DAY)["n"], 2)

    def test_a_busy_lease_retries_without_using_an_attempt(self):
        self.fresh()
        mid = self.ok_mission()
        self.mx._cycle_tick(self.m(mid))
        self.mx._claim(mid)  # someone holds the mission
        for _ in range(8): self.process()
        self.assertEqual({(e["status"]) for e in self.effects(mid)}, {"pending"})
        self.assertEqual({r["attempts"] for r in self.db.q("SELECT attempts FROM io_events WHERE kind='mission.effect'")}, {0})
        self.mx._release(mid)
        self.process()
        self.assertEqual({e["status"] for e in self.effects(mid)}, {"done"})

    def test_criterion_10_cycles_and_effects_survive_prune(self):
        self.fresh()
        mid = self.ok_mission()
        self.cycle(mid, "baseline")
        self.db.q("UPDATE io_events SET created=? WHERE corr=?", (time.time() - 200 * DAY, f"mx:{mid}"))
        self.orc._last_prune = None
        self.orc.prune()
        self.assertEqual(len(self.records(mid)), 1)
        self.assertEqual(len(self.effects(mid)), 2)

    def test_the_objective_is_immutable_and_cycle_records_keep_version_one(self):
        self.fresh()
        mid = self.ok_mission()
        rec = self.cycle(mid, "baseline")
        self.assertEqual(rec["objective_version"], 1)
        self.assertFalse(hasattr(missions.PatchIn(), "goal"))
        self.assertEqual(self.m(mid)["goal"], "Reach the top 10 on SN62 competition 28")


class NoSideEffects(Base):
    def test_criteria_4_and_5_no_team_writes_no_model_call_no_network(self):
        self.fresh()
        mid = self.ok_mission()
        self.db.q("INSERT INTO mw_tasks (comp_id, title, status, agent_id, created) VALUES (?, 'Tune', 'todo', 1, ?)", (WID, time.time()))
        before = self.snapshot_team()
        import urllib.request
        with mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network")):
            self.mx._cycle_tick(self.m(mid)); self.process()
            self.fresh(mine_em=0.001)  # a regression: rule 4 raises a corrective request (a request only)
            self.cycle(mid)
            self.fresh(mine_em=0.95)
            for _ in range(3): self.cycle(mid)  # criteria met: a delivery request only
        self.assertEqual(self.snapshot_team(), before)
        kinds = {c["decision"]["kind"] for c in self.records(mid)}
        self.assertTrue({"correct", "criteria_met"} <= kinds, kinds)
        self.assertEqual(self.m(mid)["status"], "monitoring")


class Crashes(Base):
    """CYCLE_AND_RECOVERY_ARCHITECTURE.md §6: each point leaves one decision and every effect applied once."""
    def go(self, mid):
        self.mx._looked.clear()
        try: return self.mx._cycle_tick(self.m(mid))
        except missions.Crash: return "crashed"

    def settle(self, mid):
        for _ in range(4):
            self.mx._looked.clear()
            self.mx._cycle_tick(self.m(mid), time.time() + 60)
            self.process()

    def check_once(self, mid, n=1):
        self.assertEqual([c["n"] for c in self.records(mid)], list(range(1, n + 1)))
        keys = [e["key"] for c in self.records(mid) for e in c["effects"]]
        done = {e["key"] for e in self.effects(mid) if e["status"] == "done"}
        self.assertTrue(set(keys) <= done, set(keys) - done)
        self.assertEqual(len(self.lines(mid)), n)
        self.assertEqual(self.m(mid)["verification"]["last_cycle"]["n"], n)

    def test_point_1_after_evaluation_before_emit(self):
        self.fresh(); mid = self.ok_mission()
        missions.FAULT.add("evaluated")
        self.assertEqual(self.go(mid), "crashed")
        self.assertEqual(self.records(mid), [])
        self.restart(); self.settle(mid)
        self.check_once(mid)

    def test_point_2_right_after_the_decision(self):
        self.fresh(); mid = self.ok_mission()
        missions.FAULT.add("recorded")
        self.go(mid)
        self.assertEqual(len(self.records(mid)), 1)
        self.assertEqual(self.effects(mid), [])
        self.restart(); self.settle(mid)
        self.check_once(mid)

    def test_point_3_after_some_effects(self):
        self.fresh(); mid = self.ok_mission()
        missions.FAULT.add("effects_partial")
        self.go(mid)
        self.assertEqual(len(self.effects(mid)), 1)
        self.restart(); self.settle(mid)
        self.check_once(mid)

    def test_points_4_to_6_inside_the_request_line_and_summary_handlers(self):
        self.fresh(); mid = self.create([chain_measure(target=5)], keys=[])  # no key: rule 3 needs a request on cycle 2
        self.cycle(mid, "baseline")
        for i, point in enumerate(("request:after", "cycle:after", "summary:after")):
            missions.FAULT.add(point)
            self.mx._looked.clear()
            self.assertEqual(self.mx._cycle_tick(self.m(mid), time.time() + (i + 1) * 2 * DAY)["n"], i + 2)
            try: self.process()
            except missions.Crash: pass
            self.assertIn("running", {e["status"] for e in self.effects(mid)})
            self.restart(); self.process(); self.process()
            self.assertEqual({e["status"] for e in self.effects(mid)}, {"done"}, point)
        self.assertEqual(len(self.records(mid)), 4)
        self.assertEqual(len(self.reqs(mid, "need")), 1)  # one request, though its handler ran again (later cycles: inside the window)
        self.assertEqual(len(self.lines(mid)), 4)
        self.assertEqual(self.m(mid)["verification"]["last_cycle"]["n"], 4)

    def test_point_9_an_older_release_marks_effects_done_without_applying_them(self):
        self.fresh(); mid = self.ok_mission()
        self.mx._cycle_tick(self.m(mid))
        self.db.q("UPDATE io_events SET status='done', result=? WHERE kind='mission.effect'", (json.dumps({"note": "no handler: recorded"}),))  # RC1's process()
        self.assertEqual(self.lines(mid), [])
        self.restart()
        self.process()
        self.check_once(mid)
        self.restart(); self.process()  # a second start re-applies nothing
        self.assertEqual(len(self.lines(mid)), 1)
        self.assertEqual(len([e for e in self.effects(mid) if e["key"].endswith(":reconcile")]), 2)  # a baseline: line and summary

    def test_point_10_two_clock_workers_race_on_one_mission(self):
        self.fresh(); mid = self.ok_mission()
        other = missions.Missions(self.db, hub=self.mx.hub, wf=None, ia=None, mw=self.mx.mw)
        other.readiness = self.mx.readiness
        m = self.m(mid)
        self.assertTrue(self.mx._claim(mid))
        self.assertIsNone(other._cycle_tick(m))  # the lease keeps the second out
        rec = self.mx._cycle(m, "baseline", [], time.time(), self.mx._evidence(m))
        # a second worker that evaluated meanwhile (lease lapsed) writes the same key: the unique key keeps one, and it uses the stored one
        rec2 = other._cycle(m, "scheduled", [], time.time(), other._evidence(m))
        self.mx._release(mid)
        self.assertEqual(rec2["trigger"], rec["trigger"])
        self.process()
        self.check_once(mid)


class Rules(Base):
    def test_rule_3_one_request_per_dependency_per_window_then_rules_4_to_6_run(self):
        self.fresh()
        mid = self.create([chain_measure(target=5)], keys=[])
        self.assertEqual(self.cycle(mid, "baseline")["decision"]["rule"], 6)  # the baseline only records
        rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 3)
        self.assertIn("evidence.no_external", {d["code"] for d in rec["diagnosis"]})
        self.assertEqual([r["label"] for r in self.reqs(mid, "need")], ["No external evidence source"])
        for _ in range(3): rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 5)  # idle team: advice; the dependency isn't asked again inside the window
        self.assertEqual(len(self.reqs(mid, "need")), 1)
        rec = self.cycle(mid, now=time.time() + 8 * DAY)  # the window passed: asked again
        self.assertEqual(rec["decision"]["rule"], 3)
        self.assertEqual(len(self.reqs(mid, "need")), 2)

    def test_dispatch_paused_and_readiness_are_dependencies_never_team_failures(self):
        self.fresh()
        mid = self.ok_mission()
        self.db.q("CREATE TABLE IF NOT EXISTS ctl_settings (user_id INTEGER PRIMARY KEY, mode TEXT, updated REAL, by_user TEXT)")
        self.db.q("INSERT INTO ctl_settings (user_id, mode) VALUES (?, 'manual')", (TEAM_ACCOUNT,))
        self.mx.readiness = lambda uid, wid: (_ for _ in ()).throw(RuntimeError("probe down"))
        self.cycle(mid, "baseline")
        rec = self.cycle(mid)
        codes = {d["code"] for d in rec["diagnosis"]}
        self.assertTrue({"dispatch.paused", "readiness.blocked"} <= codes)
        self.assertEqual(rec["dimensions"]["readiness"]["value"], "UNKNOWN")
        self.assertEqual({r["label"] for r in self.reqs(mid, "need")}, {"Team dispatch paused", "Operational readiness blocked or unknown"})
        self.assertNotIn("team.failing_own", codes)

    def test_infrastructure_failures_are_never_charged_to_the_team(self):
        self.fresh()
        mid = self.ok_mission()
        self.cycle(mid, "baseline")
        t = time.time()
        for i, cls in enumerate(("quota", "rate", "quota", "provider", "task")):
            rid = self.db.q("INSERT INTO mw_runs (comp_id, status, started, finished) VALUES (?, 'failed', ?, ?) RETURNING id", (WID, t, t + 1), one=True)["id"]
            self.db.q("INSERT INTO io_diag (run_id, owner_id, ref, cls, canon, ts) VALUES (?,?,?,?,?,?)", (1000 + i, TEAM_ACCOUNT, f"mw:{rid}", cls, cls, t + 2))
        rec = self.cycle(mid, now=t + 10)
        codes = {d["code"] for d in rec["diagnosis"]}
        self.assertIn("team.failing_infra", codes)
        self.assertNotIn("team.failing_own", codes)  # 1 own of 5 ended: under 3 and not above 20%; quota, rate, provider never count
        self.assertEqual((rec["team"]["own_fault_since"], rec["team"]["infra_since"]), (1, 4))

    def test_rule_1_needs_n_consecutive_passing_cycles_and_unknown_resets(self):
        mid = self.ok_mission()
        self.fresh(mine_em=0.95)
        self.cycle(mid, "baseline")
        self.assertEqual(self.records(mid)[-1]["hold"]["consecutive_pass"], 1)
        self.cycle(mid)
        self.db.q("DELETE FROM mh_samples")  # no sample: UNKNOWN
        rec = self.cycle(mid)
        self.assertEqual((rec["hold"]["consecutive_pass"], rec["dimensions"]["competition"]["value"]), (0, "UNKNOWN"))
        self.assertNotEqual(rec["decision"]["rule"], 1)
        self.fresh(mine_em=0.95)
        for _ in range(2): self.assertNotEqual(self.cycle(mid)["decision"]["rule"], 1)
        rec = self.cycle(mid)
        self.assertEqual((rec["decision"]["rule"], rec["hold"]["consecutive_pass"]), (1, 3))
        self.assertEqual(rec["decision"]["rests_on"], ["owner_attested_key"])
        self.assertEqual(len(self.reqs(mid, "deliver")), 1)
        self.assertEqual(self.m(mid)["status"], "monitoring")  # K-36: no state change
        self.cycle(mid)  # still met: no second delivery request while one is open
        self.assertEqual(len(self.reqs(mid, "deliver")), 1)

    def test_n_1_behaves_as_d004_rule_1_and_a_version_change_resets_the_hold(self):
        mid = self.ok_mission(hold_cycles=1)
        self.fresh(mine_em=0.95)
        self.assertEqual(self.cycle(mid, "baseline")["decision"]["rule"], 1)
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(hold_cycles=2))
        rec = self.cycle(mid)
        self.assertEqual(rec["hold"], {"required": 2, "consecutive_pass": 1})  # the new version starts the count again
        self.assertNotEqual(self.records(mid)[0]["measures_version"], rec["measures_version"])

    def test_self_reported_evidence_never_counts_toward_the_hold(self):
        mid = self.create([ingest_measure(target=10)])
        kid, tok = self.key(holder="team")
        self.report(tok, 3)
        for _ in range(4):
            rec = self.cycle(mid)
            self.assertEqual(rec["hold"]["consecutive_pass"], 0)
            self.assertNotEqual(rec["decision"]["rule"], 1)
            self.assertNotIn("self_reported", rec["decision"]["rests_on"])

    def test_rule_2_deliver_now_and_the_deadline_raise_a_confirmation_and_change_nothing(self):
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 3600)
        self.mx._cycle_tick(self.m(mid)); self.process()
        with self.assertRaises(HTTPException): self.mx.deliver_now(self.me(TEAM_ACCOUNT), mid)
        self.mx.deliver_now(self.me(OWNER), mid)
        self.assertEqual(self.mx._cycle_tick(self.m(mid))["trigger"], "final")
        self.process()
        self.assertEqual(self.records(mid)[-1]["decision"]["rule"], 2)
        self.assertEqual([r["label"] for r in self.reqs(mid, "deliver")], [missions.DELIVER_ENDED])  # D4.4's label
        later = time.time() + 7200  # past the deadline: exactly one final cycle, then none
        for _ in range(3):
            self.mx._looked.clear()
            self.mx._cycle_tick(self.m(mid), later); self.process()
        finals = [c for c in self.records(mid) if c["trigger"] == "final"]
        self.assertEqual(len(finals), 1)  # deliver-now's final cycle already answered for this deadline: no second one
        self.assertEqual(self.m(mid)["status"], "monitoring")

    def test_rule_5_a_stalled_measure_gets_advice_and_the_director_note_shows_it(self):
        self.fresh()
        mid = self.ok_mission()
        for _ in range(4): rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 5)
        self.assertIn("competition.stalled", {d["code"] for d in rec["diagnosis"]})
        self.assertEqual(len(self.lines(mid, "advice")), 4)  # an idle team gets advice from its first cycle
        self.assertEqual(self.mx._mission_note(WID, 7), "")  # off by default
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(director_context=True))
        note = self.mx._mission_note(WID, 7)
        self.assertIn("Reach the top 10", note)
        self.assertIn(f"cycle {rec['n']}", note)
        self.assertIn("Mission Control's latest advice", note)
        self.assertLessEqual(len(note), missions.NOTE_MAX + 2)
        self.assertTrue(self.db.q("SELECT 1 FROM io_events WHERE key=?", (f"mx:{mid}:note:7",), one=True))
        self.assertEqual(self.cycle(mid)["team"]["director_runs"], [7])


class MoreRules(Base):
    def test_a_measure_still_meeting_its_target_never_regresses_into_a_correction(self):
        mid = self.create([chain_measure(target=10)])
        self.fresh(mine_em=0.92)  # 3rd
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.05)  # 7th: worse, but still ≤ 10
        rec = self.cycle(mid)
        self.assertEqual(rec["gap"][0]["moved"], "regressed")
        self.assertNotIn("competition.regressed", {d["code"] for d in rec["diagnosis"]})
        self.assertNotEqual(rec["decision"]["rule"], 4)
        self.assertEqual(self.reqs(mid, "corrective"), [])

    def test_stale_evidence_while_the_campaign_is_paused_is_a_dependency(self):
        self.db.q("UPDATE mh_campaigns SET status='paused'")
        self.sample(self.field(), age_h=5)
        mid = self.ok_mission()
        self.cycle(mid, "baseline")
        rec = self.cycle(mid)
        self.assertIn("evidence.stale_paused", {d["code"] for d in rec["diagnosis"]})
        self.assertEqual(rec["decision"]["rule"], 3)
        self.assertIn("Evidence stale while the campaign is paused", [r["label"] for r in self.reqs(mid, "need")])

    def test_the_informational_budget_crossed_is_one_request_and_stops_nothing(self):
        self.db.q("""CREATE TABLE IF NOT EXISTS ac_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, system TEXT, owner_id INTEGER, ref TEXT, corr TEXT, team TEXT,
                     kind TEXT, status TEXT, tokens INTEGER DEFAULT 0, cost REAL, started REAL, finished REAL)""")
        self.fresh()
        mid = self.ok_mission(budget_info=5)
        t = time.time() + 1
        self.db.q("INSERT INTO ac_runs (team, cost, tokens, started, finished, status) VALUES (?, 6.5, 1000, ?, ?, 'done')", (f"comp:{WID}", t, t + 5))
        self.db.q("INSERT INTO ac_runs (team, cost, tokens, started, finished, status) VALUES (?, 50, 0, ?, ?, 'done')", (f"comp:{WID}", t, t))  # a roll-up row: not a real run
        self.cycle(mid, "baseline")
        rec = self.cycle(mid, now=t + 10)
        self.assertEqual(rec["spend"]["team"], {"usd": 6.5, "tokens": 1000})
        self.assertIn("budget.informational_crossed", {d["code"] for d in rec["diagnosis"]})
        self.assertIn("Informational budget crossed", [r["label"] for r in self.reqs(mid, "need")])
        self.assertEqual(self.m(mid)["status"], "monitoring")

    def test_deliver_now_after_the_deadline_is_allowed_when_no_delivery_request_waits(self):
        # D4.3 refused it (409); D4.4 allows it, so a mission whose final request expired or was rejected can be delivered
        # (test_mission_delivery covers the refusal while a request waits)
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 120)
        self.db.q("UPDATE mx_missions SET deadline=? WHERE id=?", (time.time() - 1, mid))
        self.assertEqual(self.mx.deliver_now(self.me(OWNER), mid)["mission"]["status"], "monitoring")

    def test_the_trace_joins_cycles_effects_requests_and_audit(self):
        self.fresh()
        mid = self.create([chain_measure(target=5)], keys=[])
        self.cycle(mid, "baseline"); self.cycle(mid)
        tr = self.mx.trace(self.me(OWNER), mid)
        self.assertEqual([c["n"] for c in tr["cycles"]], [2, 1])
        self.assertTrue(all(e["status"] == "done" for c in tr["cycles"] for e in c["effects"]))
        self.assertEqual([r["kind"] for r in tr["requests"]], ["need"])
        self.assertIn("mission.create", [a["action"] for a in tr["audit"]])


class Authority(Base):
    def test_the_mission_page_shows_the_team_account_no_requests_to_decide(self):
        self.fresh()
        mid = self.create([chain_measure(target=5)], keys=[])
        self.cycle(mid, "baseline"); self.cycle(mid)
        self.assertEqual(self.mx.state(self.me(TEAM_ACCOUNT), mid)["requests"], [])
        self.assertEqual(len(self.mx.state(self.me(OWNER), mid)["requests"]), 1)

    def test_persistent_requests_are_the_owners_and_the_team_account_can_neither_see_nor_decide(self):
        self.fresh()
        mid = self.create([chain_measure(target=5)], keys=[])
        self.cycle(mid, "baseline"); self.cycle(mid)
        r = self.reqs(mid, "need")[0]
        self.assertEqual(r["user_id"], TEAM_ACCOUNT)
        self.assertEqual(self.mx.requests(self.me(TEAM_ACCOUNT))["requests"], [])
        self.assertEqual([x["id"] for x in self.mx.requests(self.me(OWNER))["requests"]], [r["id"]])
        with self.assertRaises(HTTPException) as c: self.mx.decide(self.me(TEAM_ACCOUNT), r["id"], missions.DecideIn(approve=True, hash=r["hash"]))
        self.assertEqual(c.exception.status_code, 404)
        with self.assertRaises(HTTPException): self.mx.decide(self.me(ADMIN), r["id"], missions.DecideIn(approve=True, hash=r["hash"]))  # not delegated
        self.mx.decide(self.me(OWNER), r["id"], missions.DecideIn(approve=True, hash=r["hash"], note="registering"))
        self.assertEqual(self.reqs(mid, "need")[0]["status"], "approved")


class Corrective(Base):
    def setUp(self):
        super().setUp()
        self.mx.hub = types.SimpleNamespace(llm=types.SimpleNamespace(resolve=lambda x: None))
        self.mx._engines = lambda uid: {k: True for k in missions.ENGINES}
        self.started = []
        self.mx._submit = self.started.append

    def regress(self):
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 30 * DAY)
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.001)  # 7th → lower: a measured regression
        rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 4, rec["decision"])
        return mid, self.reqs(mid, "corrective")[0]

    def test_rule_4_proposes_and_only_the_owners_approval_starts_a_one_shot_mission_under_the_team_account(self):
        mid, r = self.regress()
        self.assertIn("Recover the competition standing", r["action"])
        self.assertEqual(self.mx._correctives(mid), [])  # proposed, never started
        before = self.snapshot_team()
        self.mx.decide(self.me(OWNER), r["id"], missions.DecideIn(approve=True, hash=r["hash"], budget=4))
        (c,) = self.mx._correctives(mid)
        cm = self.m(c["id"])
        self.assertEqual((cm["user_id"], cm["team"], cm["forced"], cm["budget"], cm["status"]), (TEAM_ACCOUNT, WID, "mining", 4, "queued"))
        self.assertEqual(cm["autonomy"]["level"], "L1")  # waits for the exact plan's approval before any work runs
        self.assertEqual(cm["understanding"]["parent"], f"mx:{mid}")
        self.assertEqual(cm["understanding"]["corrective"]["approved_by"], "the-owner")
        self.assertLessEqual(cm["deadline"], time.time() + 7 * DAY + 5)
        self.assertEqual(self.started, [c["id"]])  # the ordinary path, nothing more
        self.assertTrue(self.db.q("SELECT 1 FROM audit WHERE action='mission.corrective'", one=True))
        self.assertEqual(self.snapshot_team(), before)
        self.fresh(mine_em=0.0001)  # regressed again while it runs: advice, no second corrective
        rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 4)
        self.assertIn("A corrective mission is running", rec["advice"])
        self.assertEqual(len(self.reqs(mid, "corrective")), 1)
        self.assertEqual(rec["team"]["corrective"][0]["mission"], c["id"])

    def test_a_refused_corrective_request_starts_nothing_and_the_team_account_cannot_approve(self):
        mid, r = self.regress()
        with self.assertRaises(HTTPException): self.mx.decide(self.me(TEAM_ACCOUNT), r["id"], missions.DecideIn(approve=True, hash=r["hash"]))
        self.mx.decide(self.me(OWNER), r["id"], missions.DecideIn(approve=False, hash=r["hash"]))
        self.assertEqual(self.mx._correctives(mid), [])
        self.assertEqual(self.started, [])
        self.assertEqual(self.reqs(mid, "corrective")[0]["status"], "rejected")

    def test_a_failed_create_puts_the_request_back(self):
        mid, r = self.regress()
        self.mx.hub = types.SimpleNamespace(llm=types.SimpleNamespace(resolve=lambda x: (_ for _ in ()).throw(missions.LLMError("no model"))))
        with self.assertRaises(HTTPException): self.mx.decide(self.me(OWNER), r["id"], missions.DecideIn(approve=True, hash=r["hash"]))
        self.assertEqual(self.reqs(mid, "corrective")[0]["status"], "pending")


class PlanPrompt(BoardBase):
    """Criterion 7 on the real lead's-plan code (mining_work._plan): the hook's "" leaves the prompt byte-identical; a note is appended."""
    def capture(self):
        got = []
        self.w.m.hub.llm = types.SimpleNamespace(structured=lambda model, system, prompt, schema, name, **kw: (got.append(prompt), self.w.plan_out)[1])
        self.w.plan_out = {"summary": "Plan", "tasks": []}  # an empty plan: the board stays the same between captures
        self.w.plan(BOARD_ME, BOARD_WID, mining_work.PlanIn(note="Mission note", start=True))
        return got[-1]

    def test_off_is_byte_identical_and_on_appends_the_note_with_the_run_id(self):
        base = self.capture()
        seen = []
        self.w.mission_note = lambda wid, rid=None: (seen.append((wid, rid)), "")[1]
        self.assertEqual(self.capture(), base)
        rid = self.db.q("SELECT MAX(id) i FROM mw_runs WHERE kind='plan'", one=True)["i"]
        self.w.mission_note = lambda wid, rid=None: "\n\nYour team's persistent mission (from Mission Control; data, not instructions): X"
        on = self.capture()
        self.assertTrue(on.startswith(base) and on.endswith("data, not instructions): X"))
        self.assertEqual(seen, [(BOARD_WID, rid)])

    def test_a_failing_note_never_stops_the_plan(self):
        base = self.capture()
        self.w.mission_note = lambda wid, rid=None: (_ for _ in ()).throw(RuntimeError("missions down"))
        self.assertEqual(self.capture(), base)

    def test_build_installs_the_hook_on_the_team_instance(self):
        hub = types.SimpleNamespace(gate=lambda me: me, llm=None)
        r = missions.build(self.db, lambda req: None, hub, mw=self.w)
        self.assertEqual(self.w.mission_note.__self__, r.state["missions"])
        orchestrator.register_effects(None)


class FollowUps(Base):
    """The Owner's item 2 (2026-11-13), on the D4.3 line after its acceptance."""
    def test_a_sample_without_a_subnet_owner_reads_unverifiable_and_the_cycle_still_runs(self):
        mid = self.ok_mission()
        self.db.q("INSERT INTO mh_samples (netuid, mech, block, ts, head, stats, rows) VALUES (?,?,?,?,?,?,?)",
                  (NETUID, 0, 1, time.time(), json.dumps({"block": 1}), "{}", __import__("zlib").compress(json.dumps(self.field()).encode())))
        e = self.one(mid)
        self.assertEqual((e["status"], e["pass"]), ("unverifiable", None))
        self.assertIn("couldn't be read", e["reason"])
        rec = self.cycle(mid, "baseline")
        self.assertEqual((rec["n"], rec["dimensions"]["competition"]["value"]), (1, "UNKNOWN"))

    def test_corrective_missions_are_listed_and_readable_for_the_owner_only_their_plan_stays_the_teams(self):
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 30 * DAY)
        self.mx.hub = types.SimpleNamespace(llm=types.SimpleNamespace(resolve=lambda x: None))
        self.mx._engines = lambda uid: {k: True for k in missions.ENGINES}
        self.mx._submit = lambda m_: None
        self.mx._teams = lambda uid: []
        self.cycle(mid, "baseline"); self.fresh(mine_em=0.001); self.cycle(mid)
        r = self.reqs(mid, "corrective")[0]
        self.mx.decide(self.me(OWNER), r["id"], missions.DecideIn(approve=True, hash=r["hash"]))
        cid = self.mx._correctives(mid)[0]["id"]
        cards = {c["id"]: c for c in self.mx.home(self.me(OWNER))["missions"]}
        self.assertEqual(cards[cid]["parent"], f"mx:{mid}")
        self.assertEqual(self.mx.state(self.me(OWNER), cid)["mission"]["id"], cid)
        with self.assertRaises(HTTPException): self.mx.state(self.me(ADMIN), cid)  # not delegated
        self.assertNotIn(cid, {c["id"] for c in self.mx.home(self.me(ADMIN))["missions"]})
        # its own plan request (the existing plan gate) stays with the team's account
        self.mx._request(self.m(cid), "Run this plan", "{}", kind=("plan", "Plan approval"), stage="plan")
        p = self.reqs(cid, "plan")[0]
        self.assertEqual(p["user_id"], TEAM_ACCOUNT)
        with self.assertRaises(HTTPException): self.mx.decide(self.me(OWNER), p["id"], missions.DecideIn(approve=True, hash=p["hash"]))


class DirectorHook(Base):
    def test_the_hook_is_a_no_op_by_default(self):
        self.assertEqual(mining_work.Work.mission_note(5, 9), "")

    def test_switching_the_note_makes_no_new_version_and_is_audited(self):
        mid = self.ok_mission()
        v = self.m(mid)["understanding"]["measures_version"]
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(director_context=True))
        self.assertEqual(self.m(mid)["understanding"]["measures_version"], v)
        self.assertTrue(self.db.q("SELECT 1 FROM audit WHERE action='mission.director_context'", one=True))
        with self.assertRaises(HTTPException): self.mx.patch(self.me(TEAM_ACCOUNT), mid, missions.PatchIn(director_context=False))

    def test_one_shot_missions_refuse_the_new_fields(self):
        self.mx.hub = types.SimpleNamespace(llm=types.SimpleNamespace(resolve=lambda x: None))
        self.mx._submit = lambda mid: None
        mid = self.mx.create(self.me(OWNER), missions.MissionIn(goal="Write a short report on validators"))["mission"]["id"]
        for b in (missions.PatchIn(hold_cycles=2), missions.PatchIn(director_context=True)):
            with self.assertRaises(HTTPException): self.mx.patch(self.me(OWNER), mid, b)


if __name__ == "__main__":
    unittest.main()
