"""D-031 (Owner decision 2026-11-13): a Competition team's agent is promoted only by the promotion gate, on measured evidence, by a
person. The Upgrade Factory's exam is scored by a model, so its "promote" is a screening step: it sends the candidate to the gate
as a proposal and changes nothing in the team. RC1 wrote the candidate's instructions onto the agent at that point.

- Screening writes no instructions and no version; it records the proposal it opened and can't be done twice.
- The exam's numbers never promote: without a trial's measured evidence the gate refuses, as for any team-agent proposal.
- A trial on the team's benchmark that shows the candidate is better lets a person promote it, through the gate's own write.
- The sprint's checks still hold (did better, the exact text, once, in time, the agent unchanged), and without the Evolution Lab
  nothing is sent and nothing changes.
"""
import inspect, json, os, sys, time, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import evolution as evo, mining_upgrade as mu  # noqa: E402
import test_mission_persistent_evidence as tp  # noqa: E402
import test_team_trials as tt  # noqa: E402  (as modules, so their own tests don't run again here)
import test_vm_runner as tv  # noqa: E402

ME, BASE, CAND = tt.ME, tt.BASE_TEXT, tt.CAND_TEXT


@tv.own_tests
class Screening(tt.TeamTrial):
    def setUp(self):
        super().setUp()
        self.up.evolution = self.ev
        self.db.q("INSERT INTO au_sprints (id, comp_id, status, started, finished) VALUES (1, ?, 'done', ?, ?)", (tp.WID, time.time() - 600, time.time() - 60))
        self.row(1)

    def row(self, rid, verdict="better", candidate=CAND):
        self.db.q("""INSERT INTO au_agents (id, sprint_id, comp_id, agent_id, name, title, status, before, candidate, base_score, cand_score, verdict, hash)
                     VALUES (?, 1, ?, 2, 'Rae', 'Reviewer', 'done', ?, ?, 61, 74, ?, ?)""", (rid, tp.WID, BASE, candidate, verdict, mu.digest(2, BASE, candidate)))

    def au(self, rid=1): return self.db.q("SELECT decision, decided, gate_proposal FROM au_agents WHERE id=?", (rid,), one=True)
    def send(self, rid=1, hash_=None): return self.up.decide(ME, rid, mu.DecideIn(action="promote", hash=hash_ or mu.digest(2, BASE, CAND)))
    def proposals(self): return self.db.q("SELECT * FROM ev_proposals ORDER BY id")

    def test_promote_sends_the_candidate_to_the_gate_and_changes_nothing_in_the_team(self):
        out = self.send()
        (p,) = self.proposals()
        self.assertEqual((self.text(), self.versions()), (BASE, []))  # no instructions written, no version: RC1 wrote both here
        self.assertEqual((p["origin"], p["target_key"], p["target_kind"], p["status"], json.loads(p["change"])["instructions"]), ("upgrade", "teams:2", "agent", "proposed", CAND))
        s = json.loads(p["signal"])
        self.assertEqual((s["from"], s["sprint"], s["row"], s["exam"]), ("upgrade_sprint", 1, 1, {"base": 61, "candidate": 74, "scored_by": "model_judged"}))
        self.assertIn("screening result, not evidence", p["hypothesis"]); self.assertIsNone(p["evidence"])
        a = self.au()
        self.assertEqual((a["decision"], a["gate_proposal"]), ("screened", p["id"]))
        self.assertEqual((out["decision"], out["gate"], out["experiments"], out["hash"]), ("screened", {"proposal": p["id"], "status": "proposed"}, False, None))
        self.assertEqual(self.db.q("SELECT actor FROM ev_audit WHERE action='proposal.created'", one=True)["actor"], "leo")  # a person sent it, not the engine
        self.assertEqual(self.up._tally(1)["tally"]["screened"], 1); self.assertEqual(self.up._tally(1)["tally"]["promoted"], 0)

    def test_the_exams_numbers_never_promote(self):
        self.opt()
        pid = self.send()["gate"]["proposal"]
        self.assertIn("Not verified", self.refused(400, self.ev.promote, ME, pid))  # nothing measured: the exam's 61 → 74 is not evidence
        e = self.ev.record_evidence(ME, pid, evo.EvidenceIn(test_set="the sprint's exam", baseline=[61, 61, 61], candidate=[74, 74, 74]))  # the exam's numbers, typed in
        self.assertEqual(e["basis"], "recorded")
        self.assertIn("only on measured evidence", self.refused(400, self.ev.promote, ME, pid))  # recorded numbers never promote a team agent (L5.4)
        self.assertEqual((self.text(), self.versions()), (BASE, []))
        self.assertNotEqual(self.ev.proposal(ME, pid)["status"], "promoted")

    def test_a_trial_on_the_teams_benchmark_promotes_it_through_the_gate(self):
        self.opt(); self.measured(0.60, 3)
        pid = self.send()["gate"]["proposal"]
        self.assertTrue(self.up.detail(ME, 1)["experiments"])
        self.ev.trial_start(ME, pid); self.refreeze(); self.measured(0.75, 3)
        self.assertEqual(self.ev.trial_end(ME, pid)["status"], "verified")
        self.assertEqual(self.text(), BASE)  # the trial put the version before back; verified is not promoted
        self.assertEqual(self.up.detail(ME, 1)["gate"]["status"], "verified")
        self.ev.promote(ME, pid)
        self.assertEqual(self.text(), CAND)
        self.assertEqual(self.versions()[-1]["source"], f"gate #{pid}")  # the gate's own write, not the sprint's
        self.assertEqual((self.up.detail(ME, 1)["gate"], self.au()["decision"]), ({"proposal": pid, "status": "promoted"}, "screened"))
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM au_versions WHERE source='upgrade'", one=True)["n"], 0)

    def test_the_sprints_own_checks_still_hold(self):
        self.refused(409, self.send, 1, "0" * 64)  # not the text the person looked at
        self.row(2, verdict="same"); self.refused(409, self.send, 2)
        self.db.q("UPDATE au_sprints SET finished=? WHERE id=1", (time.time() - (mu.APPROVAL_DAYS + 1) * 86400,))
        self.refused(409, self.send)  # too old
        self.db.q("UPDATE au_sprints SET finished=? WHERE id=1", (time.time() - 60,))
        self.db.q("UPDATE mw_agents SET instructions='Edited since.' WHERE id=2")
        self.refused(409, self.send)  # the agent changed since the sprint measured it
        self.db.q("UPDATE mw_agents SET instructions=? WHERE id=2", (BASE,))
        self.assertEqual((self.proposals(), self.au()["decision"]), ([], None))
        self.send()
        self.assertIn("already screened", self.refused(409, self.send))  # once
        self.assertEqual(len(self.proposals()), 1)

    def test_without_the_evolution_lab_nothing_is_sent_and_nothing_changes(self):
        self.up.evolution = None
        self.refused(503, self.send)
        self.assertEqual((self.text(), self.versions(), self.proposals(), self.au()["decision"], self.au()["gate_proposal"]), (BASE, [], [], None, None))

    def test_a_proposal_the_gate_refuses_leaves_the_row_undecided(self):
        self.ev.teams = None  # the gate can't reach the team: it refuses the proposal
        with self.assertRaises(HTTPException): self.send()
        self.assertEqual((self.au()["decision"], self.proposals(), self.text()), (None, [], BASE))

    def test_reject_is_unchanged(self):
        out = self.up.decide(ME, 1, mu.DecideIn(action="reject"))
        self.assertEqual((out["decision"], out["gate"], self.proposals(), self.text()), ("rejected", None, [], BASE))

    def test_the_sprint_writes_no_agent_and_no_version(self):
        """Static: decide() holds no write to the team's agents or their version store. Only the gate's own write does."""
        src = inspect.getsource(mu.Upgrade.decide)
        for word in ("UPDATE mw_agents", "_version(", "gate_apply("): self.assertNotIn(word, src)
        self.assertIn("self.evolution.propose(", src)


if __name__ == "__main__":
    unittest.main()
