"""mission_autonomy.py + missions.py: autonomy per mission and kind of action. A mission without a setting runs as before (L3);
L1 waits for approval of the exact plan, L0 delivers the plan without running anything, recover=ask waits before a retry,
external=list only lists gated actions; the requests are hash-bound, single use, and lapse into a pause."""
import json, os, sys, tempfile, time, unittest

from fastapi import HTTPException

from app import mission_autonomy as ma, missions

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_team import ME, U, Base  # noqa: E402

PLAN = {"tasks": [{"id": 1, "title": "Read the code", "owner": "engineering", "done_when": "notes written", "depends": []}],
        "brief": "Do the work.", "risks": ["It may be slow"]}
DELIV = {"summary": "Done.", "recommendations": [], "lessons": []}


class Policy(unittest.TestCase):
    def test_default_is_how_missions_always_ran(self):
        p = ma.resolve(None)
        self.assertEqual((p["level"], p["plan"], p["recover"], p["external"], p["attempts"]), ("L3", "auto", "auto", "request", missions.MAX_ATTEMPTS))

    def test_kinds_override_the_level_and_validate(self):
        self.assertEqual(ma.validate({"level": "L2", "plan": "ask", "recover": "auto"}), {"level": "L2", "plan": "ask"})
        self.assertEqual(ma.resolve({"level": "L2", "plan": "ask"})["custom"], ["plan"])
        for bad in ({"level": "L9"}, {"external": "auto"}, {"level": "L3", "deploy": "auto"}, "L3"):
            with self.assertRaises(ValueError): ma.validate(bad)

    def test_never_auto_for_gated_actions(self):
        self.assertNotIn("auto", ma.KINDS["external"][1])
        self.assertTrue(all(lv[2]["external"] in ("request", "list") for lv in ma.LEVELS.values()))


class Gates(Base):
    def setUp(self):
        super().setUp()
        self.u = dict(U, engine="direct", gated_actions=["Deploy the miner to production"])
        def ask(m, stage, schema, name, prompt, **kw):
            return json.loads(json.dumps({"understanding": self.u, "plan": PLAN, "delivery": DELIV}.get(name, self.u))), "fake"
        self.mx._ask = ask
        self.mx._engines = lambda uid: {"direct": True, "workforce": True, "longtask": False, "mining": False}
        self.mx._claim = lambda mid: True

    def run_to_plan(self, autonomy=None):
        now = time.time()
        mid = self.db.q("""INSERT INTO mx_missions (user_id, title, goal, budget, constraints, status, stage, forced, autonomy, created, updated)
                           VALUES (?,?,?,?,?,'running','plan',?,?,?,?) RETURNING id""",
                        (ME["id"], "A", "Write a report about the miner", 5.0, "", "direct", json.dumps(autonomy) if autonomy else None, now, now), one=True)["id"]
        self.db.q("UPDATE mx_missions SET understanding=?, engine='direct' WHERE id=?", (json.dumps(self.u), mid))
        self.mx._allocate = lambda m: True  # stop the run at ALLOCATE: what matters is whether it gets there
        self.mx._launch = lambda m, note="": "running"
        self.mx._advance(mid)
        return mid

    def test_unset_runs_on_as_before(self):
        mid = self.run_to_plan()
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["stage"]), ("running", "execute"))
        self.assertIsNone(self.req(mid))

    def test_plan_ask_waits_for_that_exact_plan(self):
        mid = self.run_to_plan({"level": "L1"})
        m, r = self.mx._m(mid), self.req(mid)
        self.assertEqual((m["status"], m["stage"], r["kind"]), ("needs_input", "plan", "plan"))
        self.assertIn("approve the plan", self.mx._card(m)["doing"])
        # the plan changed under the request: refused
        self.db.q("UPDATE mx_missions SET plan=? WHERE id=?", (json.dumps(dict(PLAN, brief="Something else", round=0)), mid))
        with self.assertRaises(HTTPException) as e: self.decide(mid, True)
        self.assertEqual(e.exception.status_code, 409)
        self.db.q("UPDATE mx_missions SET plan=? WHERE id=?", (json.dumps(dict(PLAN, round=0)), mid))
        self.decide(mid, True)
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["stage"], m["plan"]["approved"]), ("running", "allocate", ME["username"]))
        with self.assertRaises(HTTPException): self.decide(mid, True)  # single use
        self.mx._advance(mid)
        self.assertEqual(self.mx._m(mid)["stage"], "execute")  # an approved plan isn't asked about again

    def test_declined_plan_is_planned_again_with_the_note(self):
        mid = self.run_to_plan({"level": "L1"})
        seen = []
        orig = self.mx._ask
        self.mx._ask = lambda m, stage, schema, name, prompt, **kw: (seen.append(prompt), orig(m, stage, schema, name, prompt))[1]
        self.decide(mid, False, note="Use the held-out tasks too")
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["stage"], m["understanding"]["plan_feedback"]), ("running", "plan", "Use the held-out tasks too"))
        self.mx._advance(mid)
        self.assertIn("declined the previous plan: Use the held-out tasks too", seen[0])
        reqs = self.db.q("SELECT status, hash FROM mx_requests WHERE mission_id=? ORDER BY id", (mid,))
        self.assertEqual([r["status"] for r in reqs], ["rejected", "pending"])  # a new request for the new plan
        self.assertNotEqual(reqs[0]["hash"], reqs[1]["hash"])
        self.assertNotIn("plan_feedback", self.mx._m(mid)["understanding"])

    def test_plan_off_delivers_the_plan_only(self):
        mid = self.run_to_plan({"level": "L0"})
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["outcome"], m["deliverable"]["kind"]), ("delivered", "unverified", "plan"))
        self.assertIn("Read the code", m["deliverable"]["text"])
        self.assertIsNone(m["child"])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_requests WHERE mission_id=?", (mid,), one=True)["n"], 0)  # L0 lists, doesn't request
        self.assertEqual(m["report"]["autonomy"]["level"], "L0")

    def test_external_request_vs_list(self):
        for level, n in (("L3", 1), ("L2", 0)):
            mid = self.run_to_plan({"level": level})
            self.db.q("UPDATE mx_missions SET stage='deliver', deliverable=?, verification=?, outcome='verified' WHERE id=?",
                      (json.dumps({"text": "the report"}), json.dumps({"results": []}), mid))
            self.mx._deliver(self.mx._m(mid))
            self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mx_requests WHERE mission_id=?", (mid,), one=True)["n"], n, level)

    def test_recover_ask_waits_then_retries_or_delivers(self):
        mid = self.run_to_plan({"level": "L3", "recover": "ask"})
        self.db.q("UPDATE mx_missions SET attempts=1, history=? WHERE id=?", (json.dumps([{"attempt": 1, "engine": "direct", "child": 1}]), mid))
        self.assertEqual(self.mx._recover(self.mx._m(mid), "rate limit 429"), "ask")
        m, r = self.mx._m(mid), self.req(mid)
        self.assertEqual((m["status"], r["kind"], m["history"][-1]["ask"]), ("needs_input", "recover", r["id"]))
        self.assertIn("try again", self.mx._card(m)["doing"])
        self.decide(mid, True)
        self.assertEqual(self.mx._m(mid)["status"], "running")
        # the next failure asks again; declining delivers what's done
        self.db.q("UPDATE mx_missions SET attempts=2 WHERE id=?", (mid,))
        self.assertEqual(self.mx._recover(self.mx._m(mid), "rate limit 429"), "ask")
        self.decide(mid, False)
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["stage"]), ("running", "verify"))

    def test_attempts_by_level(self):
        mid = self.run_to_plan({"level": "L4"})
        self.db.q("UPDATE mx_missions SET attempts=3, history=? WHERE id=?", (json.dumps([{"attempt": 3}]), mid))
        self.assertEqual(self.mx._recover(self.mx._m(mid), "rate limit 429"), "retry")  # L4: 5 attempts
        self.db.q("UPDATE mx_missions SET attempts=5 WHERE id=?", (mid,))
        self.assertEqual(self.mx._recover(self.mx._m(mid), "rate limit 429"), "dead")

    def test_lapsed_request_pauses_with_the_reason(self):
        mid = self.run_to_plan({"level": "L1"})
        self.db.q("UPDATE mx_requests SET expires=? WHERE mission_id=?", (time.time() - 1, mid))
        self.mx.tick()
        m = self.mx._m(mid)
        self.assertEqual(m["status"], "paused")
        self.assertIn("Nobody decided on the plan", m["pause_reason"])
        self.assertEqual(self.req(mid)["status"], "lapsed")

    def test_raising_the_level_withdraws_the_waiting_plan(self):
        mid = self.run_to_plan({"level": "L1"})
        self.mx.patch(ME, mid, missions.PatchIn(autonomy={"level": "L3"}))
        m = self.mx._m(mid)
        self.assertEqual((m["status"], m["stage"], self.req(mid)["status"]), ("running", "allocate", "withdrawn"))
        self.assertTrue(m["plan"]["approved"].startswith("policy"))
        mid = self.run_to_plan({"level": "L1"})
        self.mx.patch(ME, mid, missions.PatchIn(autonomy={"level": "L0"}))
        m = self.mx._m(mid)
        self.assertEqual((m["stage"], m["outcome"], m["deliverable"]["kind"]), ("deliver", "unverified", "plan"))

    def test_answered_questions_dont_come_back_at_a_gate(self):
        self.u = dict(self.u, questions=["Which subnet?"])
        mid = self.run_to_plan({"level": "L1"})  # (answers are set below, as after answering)
        self.db.q("UPDATE mx_missions SET answers=? WHERE id=?", (json.dumps(["SN62"]), mid))
        m = self.mx._m(mid)
        self.assertEqual(m["status"], "needs_input")
        self.assertEqual(self.mx._card(m)["questions"], [])
        with self.assertRaises(HTTPException) as e: self.mx.answer(ME, mid, missions.AnswerIn(answers=["SN19"]))
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(self.req(mid)["status"], "pending")  # the plan request is untouched

    def test_set_and_change_autonomy(self):
        mid = self.run_to_plan({"level": "L1"})
        self.mx.patch(ME, mid, missions.PatchIn(autonomy={"level": "L3"}))
        self.assertEqual(self.mx._m(mid)["autonomy"], {"level": "L3"})
        with self.assertRaises(HTTPException) as e: self.mx.patch(ME, mid, missions.PatchIn(autonomy={"external": "auto"}))
        self.assertEqual(e.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
