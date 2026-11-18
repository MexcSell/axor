"""G5-5 L5.5 (contract IC-7, approved by the Owner 2026-11-13): a persistent mission's "correct" decision (rule 4) records the gap
it measured as a proposal in the Evolution Lab.

- Rule 4 only: a rule-5 or rule-6 cycle proposes nothing. The cycle's record keeps the whole signal (the measure, its values, the
  external evidence it rests on, the team's open register rows, the diagnosis); the `proposal` effect hands it over once.
- The gap proposal belongs to the team's account, names the team (never an agent), and says what was measured, never what to
  change. One open gap proposal per mission and measure: a later rule-4 cycle on the same measure is linked to it.
- It is never tested, measured or promoted itself. A person answers it with a proposal for one of that team's agents
  (signal.from); the answer goes through the gate like any team-agent proposal. The gap closes when an answer is promoted and
  opens again when that promotion is rolled back.
- The effect changes nothing else: the mission's row and the team's agents are byte-identical after it. A refusal by the gate is
  recorded and the effect is applied, so later cycles aren't held. A crash or a replay never makes a second proposal.
- The next cycle's record names the gap proposals, their states and the version ids a promotion gave: ids and states only.
"""
import json, os, sys, time, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import evolution as evo, mining_upgrade, missions  # noqa: E402
import test_mission_cycles as tc  # noqa: E402  (as modules: their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402
from test_mission_persistent_evidence import ADMIN, OWNER, TEAM_ACCOUNT, WID  # noqa: E402

DAY = 86400
BASE_TEXT = "Review every change for failing tests before you approve it."
CAND_TEXT = "Review every change for failing tests and run the frozen benchmark before you approve it."
OTHER_TEAM = 23


class Ov:
    ok = True
    def _agents_ok(self, me): return self.ok


class Base(tc.Base):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("DROP TABLE IF EXISTS mw_agents")
        q("CREATE TABLE mw_agents (id INTEGER PRIMARY KEY, comp_id INTEGER, name TEXT, title TEXT, job TEXT, instructions TEXT, model TEXT)")
        q("INSERT INTO mw_agents (id, comp_id, name, instructions) VALUES (2, ?, 'Rae', ?)", (WID, BASE_TEXT))
        q("INSERT INTO mw_comps (id, campaign_id, number, name, status, paused) VALUES (?, 1, 29, 'Other', 'active', 0)", (OTHER_TEAM,))
        q("INSERT INTO mw_agents (id, comp_id, name, instructions) VALUES (3, ?, 'Sol', 'x')", (OTHER_TEAM,))
        self.work = tv.board(self.db)
        self.work._own = self.cm.w._own if hasattr(self.cm, "w") else self.work_own()
        self.up = mining_upgrade.Upgrade(self.work)
        self.ov = Ov()
        self.ev = evo.Evolution(self.db, self.ov, None, None)
        self.ev.teams = self.work
        self.mx.evolution = self.ev
        self.team = self.me(TEAM_ACCOUNT)

    def work_own(self):
        db = self.db
        def own(me, wid):
            w = db.q("SELECT * FROM mw_comps WHERE id=?", (wid,), one=True)
            c = w and db.q("SELECT * FROM mh_campaigns WHERE id=? AND user_id=?", (w["campaign_id"], me["id"]), one=True)
            if not c: raise HTTPException(404, "There's no such workspace.")
            return w, c
        return own

    def tearDown(self):
        self.ev.pool.shutdown(wait=True); db = self.db
        super().tearDown(); tv.close_db(db)

    def restart(self):
        mx = super().restart()
        mx.evolution = self.ev
        return mx

    def refused(self, code, fn, *a, **k):
        with self.assertRaises(HTTPException) as e: fn(*a, **k)
        self.assertEqual(e.exception.status_code, code, e.exception.detail)
        return e.exception.detail

    def regress(self, process=True):
        """Baseline at rank 7 (target 5), then a measured fall: rule 4."""
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 30 * DAY)
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.001)
        rec = self.cycle(mid, process=process)
        self.assertEqual(rec["decision"]["rule"], 4, rec["decision"])
        return mid, rec

    def props(self, origin="mission"): return self.db.q("SELECT * FROM ev_proposals WHERE origin=? ORDER BY id", (origin,))
    def sig(self, pid): return json.loads(self.db.q("SELECT signal FROM ev_proposals WHERE id=?", (pid,), one=True)["signal"])
    def fx(self, mid, n): return self.db.q("SELECT status, result FROM io_events WHERE key=?", (f"mx:{mid}:cycle:{n}:proposal",), one=True)
    def result(self, mid, n): return json.loads(self.fx(mid, n)["result"])
    def answer(self, gid, text=CAND_TEXT, agent=2, who=None): return self.ev.answer(who or self.team, gid, evo.AnswerIn(agent=agent, instructions=text))

    def measured(self, pid):
        """The evidence a finished gate trial leaves on a team-agent proposal (the trial itself is tested in test_team_trials)."""
        e = {"verified": True, "baseline": 60.0, "candidate": 85.0, "delta": 25.0, "cases": 3, "why": [], "source": "trial",
             "base_sha": evo._sha({"instructions": BASE_TEXT}), "basis": {"kind": "measured_internal"}}
        self.db.q("UPDATE ev_proposals SET status='verified', evidence=? WHERE id=?", (json.dumps(e), pid))

    def promote(self, pid):
        self.ev.set_experiments(self.me(OWNER), WID, evo.OptIn(on=True))
        self.measured(pid)
        return self.ev.promote(self.team, pid)


class Produced(Base):
    def test_a_rule_4_cycle_makes_one_proposal_with_the_whole_signal(self):
        mid, rec = self.regress()
        (p,) = self.props()
        s, imp = self.sig(p["id"]), rec["improve"]
        self.assertEqual((p["user_id"], p["target_kind"], p["target_key"], p["risk"], p["status"], p["origin"]), (TEAM_ACCOUNT, "team", f"comp:{WID}", "config", "proposed", "mission"))
        self.assertEqual((imp["mission"], imp["cycle"], imp["cycle_key"], imp["team"]), (f"mx:{mid}", rec["n"], f"mx:{mid}:cycle:{rec['n']}", f"comp:{WID}"))
        e = next(x for x in rec["evidence"] if x["id"] == imp["measure"]["id"])
        self.assertEqual(imp["measure"], {k: e[k] for k in ("id", "metric", "tier", "source", "op", "target")})
        self.assertEqual((imp["measure"]["tier"], imp["values"]["previous"], imp["values"]["moved"]), ("external", 7, "regressed"))
        self.assertEqual((imp["values"]["current"], imp["values"]["gap"]), (e["value"], e["value"] - 5))
        self.assertEqual((imp["evidence"]["basis"], imp["evidence"]["evidence_ref"]), (e["basis"]["kind"], e["evidence_ref"]))
        self.assertNotIn(imp["evidence"]["basis"], (None, "self_reported"))
        self.assertEqual(imp["diagnosis"], ["competition.regressed"])
        self.assertEqual({k: s[k] for k in imp}, imp)                                  # the proposal's signal is the record's, whole
        self.assertEqual([c["n"] for c in s["cycles"]], [rec["n"]])
        ch = json.loads(p["change"])
        self.assertEqual(list(ch), ["text"])                                           # the measured gap, never instructions
        self.assertIn(f"Mission #{mid}, cycle {rec['n']}, measured {e['metric']} at {e['value']} (it was 7). The target is <= 5: short by {e['value'] - 5}.", ch["text"])
        self.assertIn("it moved away from its target", ch["text"])
        self.assertEqual(p["title"], f"Measured gap: {e['metric']} short of its target (<= 5)")
        self.assertEqual(self.result(mid, rec["n"]), {"applied": True, "proposal": p["id"], "created": True, "account": TEAM_ACCOUNT})
        a = self.db.q("SELECT actor, action, target FROM ev_audit ORDER BY id")
        self.assertEqual([(x["actor"], x["action"], x["target"]) for x in a], [("Mission Control (cycle)", "proposal.created", f"proposal:{p['id']}")])
        t = next(c for c in self.mx.trace(self.me(OWNER), mid)["cycles"] if c["n"] == rec["n"])  # the Owner follows it from the mission's trace
        self.assertEqual((t["improve"]["measure"]["id"], next(x for x in t["effects"] if x["kind"] == "proposal")["result"]["proposal"]), (imp["measure"]["id"], p["id"]))

    def test_rules_5_and_6_propose_nothing(self):
        self.fresh()
        mid = self.ok_mission()
        base = self.cycle(mid, "baseline")
        self.assertEqual((base["decision"]["rule"], base["improve"]), (6, None))
        for _ in range(4): rec = self.cycle(mid)                                       # short of its target and not moving: replan advice
        self.assertEqual((rec["decision"]["rule"], rec["improve"]), (5, None))
        self.assertEqual(self.props(), [])
        self.assertFalse([e for e in self.effects(mid) if e["key"].endswith(":proposal")])

    def test_a_register_row_is_named_and_never_causes_a_proposal(self):
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 30 * DAY)
        self.cycle(mid, "baseline")
        own = self.orc.risk_upsert(TEAM_ACCOUNT, f"test:comp:{WID}", "The validator API changed", mission=f"comp:{WID}", layer="execution", source="monitor", severity="high")
        self.orc.risk_upsert(TEAM_ACCOUNT, "test:account", "An account-wide row", layer="execution", source="monitor", severity="high")
        rec = self.cycle(mid)                                                          # rows alone: not rule 4, no proposal
        self.assertNotEqual(rec["decision"]["rule"], 4)
        self.assertEqual((rec["improve"], self.props()), (None, []))
        self.fresh(mine_em=0.001)
        rec = self.cycle(mid)
        self.assertEqual(rec["decision"]["rule"], 4)
        rid = own["id"] if isinstance(own, dict) else own
        self.assertEqual(rec["improve"]["risks"], [rid])                               # the team's own scope only

    def test_only_valid_external_evidence_makes_a_signal(self):
        self.fresh()
        mid = self.ok_mission()
        m = self.m(mid)
        ev = self.mx._evidence(m, time.time())
        e = ev["measures"][0]
        gaps = [{"measure": e["id"], "tier": "external", "target": 5, "value": 9, "gap": 4, "noise": None, "moved": "regressed", "prev": 7}]
        ok = self.mx._improve_signal(m, ev, gaps, {"competition.regressed"}, 2, time.time())
        self.assertEqual(ok["measure"]["id"], e["id"])
        e["basis"] = {"kind": "self_reported"}
        self.assertEqual(list(self.mx._improve_signal(m, ev, gaps, {"competition.regressed"}, 2, time.time())), ["none"])
        e["basis"] = {"kind": "attested_key"}
        self.assertEqual(list(self.mx._improve_signal(m, ev, [dict(gaps[0], tier="internal")], {"competition.regressed"}, 2, time.time())), ["none"])
        self.assertEqual(list(self.mx._improve_signal(m, ev, [dict(gaps[0], gap=0)], {"competition.regressed"}, 2, time.time())), ["none"])


class OncePerMeasure(Base):
    def test_a_second_rule_4_cycle_on_the_same_measure_is_linked(self):
        mid, rec = self.regress()
        (p,) = self.props()
        self.fresh(mine_em=0.0001)
        rec2 = self.cycle(mid)
        self.assertEqual(rec2["decision"]["rule"], 4)
        self.assertEqual([x["id"] for x in self.props()], [p["id"]])
        self.assertEqual(self.result(mid, rec2["n"]), {"applied": True, "proposal": p["id"], "linked": True, "account": TEAM_ACCOUNT})
        s = self.sig(p["id"])
        self.assertEqual([c["n"] for c in s["cycles"]], [rec["n"], rec2["n"]])
        self.assertEqual((s["cycle"], s["values"]), (rec["n"], rec2["improve"]["values"]))  # it keeps where it began and shows the newest reading
        (row,) = rec2["proposals"]["rows"]
        self.assertEqual({k: row[k] for k in ("id", "status", "measure", "cycles", "answered_by", "answers")},
                         {"id": p["id"], "status": "proposed", "measure": s["measure"]["id"], "cycles": [rec["n"]], "answered_by": None, "answers": []})
        self.assertNotIn("held", row)  # L5.6 asks nothing of a gap nobody answered

    def test_applying_the_same_effect_again_finds_the_proposal_it_made(self):
        mid, rec = self.regress()
        (p,) = self.props()
        eff = next(e for e in rec["effects"] if e["kind"] == "proposal") | {"mission": mid}
        for _ in range(2): self.assertEqual(self.mx._apply_effect(None, eff), {"applied": True, "proposal": p["id"], "existed": True, "account": TEAM_ACCOUNT})
        self.assertEqual((len(self.props()), len(self.sig(p["id"])["cycles"])), (1, 1))
        a = self.answer(p["id"])                                                       # … and still does once the gap is closed
        self.promote(a["id"])
        self.assertEqual(self.props()[0]["status"], "answered")
        self.assertEqual(self.mx._apply_effect(None, eff)["existed"], True)
        self.assertEqual(len(self.props()), 1)

    def test_after_a_gap_is_closed_a_new_fall_opens_a_new_one_that_names_the_earlier(self):
        mid, rec = self.regress()
        (p,) = self.props()
        self.promote(self.answer(p["id"])["id"])
        self.fresh(mine_em=0.0001)
        rec2 = self.cycle(mid)
        self.assertEqual(rec2["decision"]["rule"], 4)
        new = self.props()[-1]
        self.assertEqual((len(self.props()), new["status"], self.sig(new["id"])["earlier"]), (2, "proposed", [p["id"]]))

    def test_a_refusal_by_the_gate_is_recorded_and_later_cycles_arent_held(self):
        self.ov.ok = False                                                             # agents aren't turned on for the team's account
        mid, rec = self.regress()
        r = self.fx(mid, rec["n"])
        self.assertEqual(r["status"], "done")
        self.assertEqual(json.loads(r["result"]), {"applied": True, "proposal": None, "note": "proposal not possible: Agents aren't turned on for your account. An administrator can turn them on for members."})
        self.assertEqual((self.props(), list(self.mx._effects_open(mid))), ([], []))
        self.fresh(mine_em=0.0001)
        self.assertEqual(self.cycle(mid)["n"], rec["n"] + 1)                           # the next cycle runs

    def test_a_server_without_the_evolution_lab_records_that_and_goes_on(self):
        self.mx.evolution = None
        mid, rec = self.regress()
        self.assertEqual((rec["proposals"], self.fx(mid, rec["n"])["status"], list(self.mx._effects_open(mid))), (None, "done", []))
        self.assertEqual(self.result(mid, rec["n"]), {"applied": True, "proposal": None, "note": "proposal not possible: the Evolution Lab isn't loaded on this server"})


class Recovery(Base):
    def settle(self, mid):
        for _ in range(4):
            self.mx._looked.clear()
            self.mx._cycle_tick(self.m(mid), time.time() + 60)
            self.process()

    def test_a_crash_between_the_record_and_the_effect_gives_one_proposal(self):
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 30 * DAY)
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.001)
        missions.FAULT.add("recorded")                                                 # the decision is stored, no effect emitted yet
        with self.assertRaises(missions.Crash): self.cycle(mid)
        self.assertEqual((self.props(), self.fx(mid, 2)), ([], None))
        self.restart(); self.settle(mid)
        (p,) = self.props()
        self.assertEqual((self.fx(mid, 2)["status"], self.result(mid, 2)["proposal"], [c["n"] for c in self.sig(p["id"])["cycles"]]), ("done", p["id"], [2]))

    def test_a_crash_inside_the_effect_after_the_proposal_was_written_gives_one_proposal(self):
        self.fresh()
        mid = self.ok_mission(deadline=time.time() + 30 * DAY)
        self.cycle(mid, "baseline")
        self.fresh(mine_em=0.001)
        missions.FAULT.add("proposal:after")
        with self.assertRaises(missions.Crash): self.cycle(mid)
        (p,) = self.props()                                                            # written, but the effect didn't finish
        self.assertNotEqual(self.fx(mid, 2)["status"], "done")
        self.restart(); self.settle(mid)
        self.assertEqual([x["id"] for x in self.props()], [p["id"]])
        self.assertEqual((self.fx(mid, 2)["status"], self.result(mid, 2)), ("done", {"applied": True, "proposal": p["id"], "existed": True, "account": TEAM_ACCOUNT}))

    def test_an_older_release_marks_the_effect_done_without_applying_it_and_the_next_start_applies_it(self):
        for older in ({"note": "no handler: recorded"}, {"applied": False, "note": "unknown effect 'proposal'"}):  # RC1; a release with cycles but not L5.5
            with self.subTest(older=older["note"]):
                self.db.q("DELETE FROM ev_proposals"); self.db.q("DELETE FROM io_events"); self.db.q("DELETE FROM mx_missions"); self.db.q("DELETE FROM mh_samples")
                mid, rec = self.regress(process=False)
                self.db.q("UPDATE io_events SET status='done', result=? WHERE kind='mission.effect' AND status='pending' AND key LIKE '%:proposal'", (json.dumps(older),))
                self.process()
                self.assertEqual(self.props(), [])
                self.restart(); self.process()
                (p,) = self.props()
                rc = self.db.q("SELECT status, result FROM io_events WHERE key=?", (f"mx:{mid}:cycle:{rec['n']}:proposal:reconcile",), one=True)
                self.assertEqual((rc["status"], json.loads(rc["result"])["proposal"]), ("done", p["id"]))
                for view in (self.mx.cycles(self.me(OWNER), mid)["cycles"], self.mx.trace(self.me(OWNER), mid)["cycles"]):  # and the mission's page and trace name it
                    fx = next(x for x in next(c for c in view if c["n"] == rec["n"])["effects"] if x["kind"] == "proposal")
                    self.assertEqual((fx["result"]["proposal"], fx["reconciled"]), (p["id"], "done"))
                self.restart(); self.process()
                self.assertEqual(len(self.props()), 1)

    def test_a_restart_of_the_evolution_lab_leaves_gap_proposals_alone(self):
        mid, rec = self.regress()
        (p,) = self.props()
        before = dict(p)
        ev2 = evo.Evolution(self.db, self.ov, None, None)                              # its start-up puts cut-off experiments back; a gap is none
        ev2.pool.shutdown(wait=True)
        self.assertEqual(dict(self.props()[0]), before)


class NothingElseChanges(Base):
    def test_the_mission_and_the_teams_agents_are_byte_identical_after_the_effect(self):
        mid, rec = self.regress(process=False)
        snap = lambda: json.dumps({"mission": self.db.q("SELECT * FROM mx_missions WHERE id=?", (mid,), one=True), "team": self.snapshot_team(),
                                   "requests": self.db.q("SELECT * FROM mx_requests ORDER BY id"), "versions": self.db.q("SELECT * FROM au_versions ORDER BY id"),
                                   "settings": self.db.q("SELECT * FROM app_settings ORDER BY k"), "risks": self.db.q("SELECT * FROM io_risks ORDER BY id")},
                                  default=str, sort_keys=True)
        eff = next(e for e in rec["effects"] if e["kind"] == "proposal") | {"mission": mid}
        m0 = self.db.q("SELECT * FROM mx_missions WHERE id=?", (mid,), one=True)
        before = snap()
        out = self.mx._apply_effect(None, eff)
        self.assertEqual(out["created"], True)
        m1 = self.db.q("SELECT * FROM mx_missions WHERE id=?", (mid,), one=True)
        self.assertEqual({k: v for k, v in dict(m1).items() if k != "lease_until"}, {k: v for k, v in dict(m0).items() if k != "lease_until"})
        strip = lambda s: json.loads(s) | {"mission": None}
        self.assertEqual(strip(snap()), strip(before))
        self.assertEqual(self.db.q("SELECT status, progress, evidence, before_version, after_version FROM ev_proposals", one=True),
                         {"status": "proposed", "progress": None, "evidence": None, "before_version": None, "after_version": None})  # nothing runs


class Gate(Base):
    def test_a_gap_proposal_is_never_tested_measured_or_promoted_itself(self):
        mid, rec = self.regress()
        gid = self.props()[0]["id"]
        self.ev.set_experiments(self.me(OWNER), WID, evo.OptIn(on=True))
        for name, a in (("record_evidence", (evo.EvidenceIn(test_set="made up", baseline=[10, 10, 10], candidate=[90, 90, 90]),)), ("promote", ()), ("trial_start", ()),
                        ("run", (evo.RunIn(),)), ("approve", ()), ("rollback", ()), ("set_benchmark", (evo.PatchIn(),))):
            self.assertIn("records a gap a mission measured", self.refused(409, getattr(self.ev, name), self.team, gid, *a), name)
        self.refused(409, self.ev.trial_end, self.team, gid)                           # it is never on trial
        self.orc.ev, self.orc._gate = self.ev, lambda me: None
        self.assertIn("records a gap a mission measured", self.refused(409, self.orc.approve_experiment, self.team, gid))  # the orchestrator's entry too
        self.measured(gid)                                                             # even with "verified" evidence written on it by hand
        self.assertIn("records a gap", self.refused(409, self.ev.promote, self.team, gid))
        self.assertIn("records a gap", self.refused(409, self.ev.promote, self.team, gid, by_policy=True))
        self.db.q("UPDATE ev_proposals SET status='proposed', evidence=NULL WHERE id=?", (gid,))
        self.refused(404, self.ev.proposal, self.me(OWNER), gid)                       # it belongs to the team's account
        pub = self.ev.proposal(self.team, gid)
        self.assertEqual((pub["gap"], pub["applies_here"], pub["answers"], [a["id"] for a in pub["agents"]]), (True, False, [], [2]))
        self.assertEqual(self.ev.reject(self.team, gid)["status"], "rejected")         # a person may close it
        self.refused(409, self.answer, gid)

    def test_a_person_answers_it_for_one_of_that_teams_agents(self):
        mid, rec = self.regress()
        gid = self.props()[0]["id"]
        self.refused(404, self.answer, gid, who=self.me(OWNER))                        # another account
        self.refused(404, self.answer, gid, who=self.me(ADMIN))
        self.assertIn("isn't on the team", self.refused(400, self.answer, gid, agent=3))  # the same account's other team
        self.refused(404, self.answer, gid, agent=99)
        self.assertIn("complete new instructions", self.refused(400, self.answer, gid, text=BASE_TEXT))
        self.assertEqual((self.props("answer"), self.sig(gid)["answers"]), ([], []))
        a = self.answer(gid)
        s = self.sig(a["id"])
        self.assertEqual((a["origin"], a["target_key"], a["target_kind"], a["status"], a["change"]["instructions"], a["answers_gap"], a["gap"]),
                         ("answer", "teams:2", "agent", "proposed", CAND_TEXT, gid, False))
        self.assertEqual((s["from"], s["mission"], s["cycle"], s["measure"], s["values"]), (gid, f"mx:{mid}", rec["n"], rec["improve"]["measure"], rec["improve"]["values"]))
        self.assertEqual(self.sig(gid)["answers"], [a["id"]])
        self.assertEqual(self.text(), BASE_TEXT)                                       # proposing changes nothing
        self.assertIn("Only a gap", self.refused(400, self.ev.answer, self.team, a["id"], evo.AnswerIn(agent=2, instructions="Another text entirely.")))
        acts = [(x["actor"], x["action"]) for x in self.db.q("SELECT actor, action FROM ev_audit ORDER BY id")]
        self.assertEqual(acts[-2:], [("team-acct", "proposal.created"), ("team-acct", "gap.answer_proposed")])

    def text(self): return self.db.q("SELECT instructions FROM mw_agents WHERE id=2", one=True)["instructions"]

    def test_the_gap_closes_only_when_an_answer_is_promoted_and_opens_again_on_its_rollback(self):
        mid, rec = self.regress()
        gid = self.props()[0]["id"]
        a = self.answer(gid)
        self.ev.set_experiments(self.me(OWNER), WID, evo.OptIn(on=True))
        self.ev.record_evidence(self.team, a["id"], evo.EvidenceIn(test_set="typed in", baseline=[10, 10, 10], candidate=[90, 90, 90]))
        self.assertIn("only on measured evidence", self.refused(400, self.ev.promote, self.team, a["id"]))  # C2-9 holds for an answer as for any team agent
        self.assertEqual((self.props()[0]["status"], self.text()), ("proposed", BASE_TEXT))
        other = self.ev.propose(self.team, evo.ProposalIn(target_key="teams:2", title="Unrelated", instructions=CAND_TEXT))  # a promotion that isn't an answer
        done = self.promote(a["id"])
        g = self.props()[0]
        s = self.sig(gid)
        self.assertEqual((done["status"], self.text(), g["status"], g["decision"], g["before_version"], g["after_version"]), ("promoted", CAND_TEXT, "answered", "answer", None, None))
        self.assertEqual({k: s["answered"][k] for k in ("proposal", "agent", "before_version", "after_version", "by")},
                         {"proposal": a["id"], "agent": "teams:2", "before_version": done["before_version"], "after_version": done["after_version"], "by": "team-acct"})
        self.assertEqual(self.db.q("SELECT status FROM ev_proposals WHERE id=?", (other["id"],), one=True)["status"], "proposed")
        self.refused(409, self.ev.reject, self.team, gid)
        self.refused(409, self.answer, gid, text="A third text.")
        self.fresh(mine_em=0.0001)
        nxt = self.cycle(mid)                                                          # the mission's next cycle reads ids and states
        row = nxt["proposals"]["rows"][0]
        self.assertEqual({k: row[k] for k in ("id", "status", "measure", "cycles", "answered_by", "answers")},
                         {"id": gid, "status": "answered", "measure": s["measure"]["id"], "cycles": [rec["n"]], "answered_by": a["id"],
                          "answers": [{"id": a["id"], "status": "promoted", "agent": "teams:2", "before_version": done["before_version"],
                                       "after_version": done["after_version"], "promoted": done["promoted"]}]})
        # L5.6: the row also says what the comparison would rest on. This cycle's chain sample is an hour old (the fixture's
        # default), so it was measured before the promotion and doesn't count: the question is still open
        self.assertEqual((row["label"], row["opening"]["n"], row["held"]["verdict"], row["held"]["rests_on"], row["held"]["counted"]),
                         ("competition", rec["n"], "open", "external", 0))
        vs = {v["id"]: v["instructions"] for v in self.db.q("SELECT id, instructions FROM au_versions WHERE agent_id=2")}
        self.assertEqual((vs[done["before_version"]], vs[done["after_version"]]), (BASE_TEXT, CAND_TEXT))
        self.ev.rollback(self.team, a["id"])
        g, s = self.props()[0], self.sig(gid)
        self.assertEqual((g["status"], g["decision"], "answered" in s, s["reopened"][0]["proposal"], self.text()), ("proposed", None, False, a["id"], BASE_TEXT))
        acts = [x["action"] for x in self.db.q("SELECT action FROM ev_audit WHERE target=? ORDER BY id", (f"proposal:{gid}",))]
        self.assertEqual(acts, ["proposal.created", "gap.answer_proposed", "gap.answered", "gap.reopened"])

    def test_a_promoted_proposal_that_answers_nothing_closes_no_gap(self):
        mid, rec = self.regress()
        gid = self.props()[0]["id"]
        p = self.ev.propose(self.team, evo.ProposalIn(target_key="teams:2", title="Unrelated", instructions=CAND_TEXT), signal={"from": gid})  # a hand-made signal isn't an answer
        self.promote(p["id"])
        self.assertEqual((self.props()[0]["status"], self.sig(gid).get("answered")), ("proposed", None))


if __name__ == "__main__":
    unittest.main()
