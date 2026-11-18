"""D-036 (Proposed, not adopted): a provisional charge for ONE timed-out Claude Code call, behind a switch that is OFF by default.
Also the two D-025 gap fixes W2 found (apply with the switch off): the estimate settles the reservation, and a run with no model
falls back to its reservation's model for the floor."""
import os, subprocess, tempfile, time, types, unittest
from unittest import mock

from app import agent_core, llm, mining_work
from app.auth import AuthDB
from app.llm import LLMError

OWNER, M = 1, "terminal:fable"
TIMEOUT = "Claude Code timed out after 150 s. Try again or lower the thinking effort."


class Base(unittest.TestCase):
    on = False

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        saved = (dict(agent_core._buckets), dict(agent_core._guards))
        agent_core._buckets.clear(); agent_core._guards.clear()
        def restore():
            agent_core._buckets.clear(); agent_core._buckets.update(saved[0])
            agent_core._guards.clear(); agent_core._guards.update(saved[1])
            agent_core._local.run = None; agent_core._core = None
        self.addCleanup(restore)
        env = {"AC_PROVISIONAL": "1"} if self.on else {}
        p = mock.patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        if not self.on: os.environ.pop("AC_PROVISIONAL", None)
        agent_core._core = None
        self.core = agent_core.init(self.db)
        self.core.set_limit(OWNER, "system", "t", 100_000_000, period="day", label="t", origin="manual", by="test")
        self.rid = self.new_run()

    def new_run(self, team=None, system="t"):
        rid = self.core.begin(system, OWNER, "task", ref=f"t:{time.time_ns()}")
        if team:
            self.db.q("UPDATE ac_runs SET team=? WHERE id=?", (team, rid)); agent_core._local.run["team"] = team
        return rid

    def seed(self, model, actuals, ago=3600, prov=None):
        for a in actuals:
            self.db.q("""INSERT INTO ac_reservations (owner_id, run_id, rkey, model, estimate, reserved, actual, state, created, settled, prov)
                         VALUES (?,?,?,?,?,?,?,'settled',?,?,?)""", (OWNER, 0, f"seed:{time.time_ns()}", model, a, a, a, time.time() - ago, time.time() - ago, prov))

    def timeout(self, model=M, est=2_000, single=True):
        """What _cli_once does on TimeoutExpired, then _counted_call's call_failed."""
        self.assertIsNone(self.core.admit(est, model=model))
        self.core.unmetered("Claude Code timed out after 150 s before reporting its usage", single_call=single)
        self.core.call_failed(LLMError(TIMEOUT))
        return self.db.q("SELECT * FROM ac_reservations WHERE run_id=? ORDER BY id DESC LIMIT 1", (agent_core._local.run["id"],), one=True)

    def run_row(self, rid=None):
        return self.db.q("SELECT * FROM ac_runs WHERE id=?", (rid or self.rid,), one=True)

    def audits(self, action=None):
        return self.db.q("SELECT * FROM io_audit WHERE action LIKE ?", (action or "metering.%",))


class SwitchOff(Base):
    def test_off_is_d025_exactly(self):  # req 1
        self.assertFalse(self.core.provisional_on())
        self.seed(M, [5_000] * 5)
        h = self.timeout()
        self.assertEqual(h["state"], "unmetered"); self.assertIsNone(h["prov"])
        r = self.run_row()
        self.assertEqual((r["metering"], r["tokens"]), ("unmetered", 0))
        self.assertEqual(self.audits(), [])
        self.assertIn("token budget", self.core.admit(100, model=M) or "")   # the team is held, as today
        self.assertEqual(self.core._unmetered_in(OWNER), 1)

    def test_app_setting_turns_it_on_and_off(self):
        self.assertFalse(self.core.provisional_on())
        self.db.setting("ac_provisional", v="1"); self.assertTrue(self.core.provisional_on())
        self.db.setting("ac_provisional", v="0"); self.assertFalse(self.core.provisional_on())


class GapFixes(Base):  # req 6, switch off
    def test_estimate_settles_the_reservation_once(self):  # gap (a)
        h = self.timeout()
        self.assertEqual(h["state"], "unmetered")
        r = self.core.estimate(OWNER, self.rid, 50_000, "alice", "overnight")
        self.assertEqual((r["tokens"], r["path"]), (50_000, "estimate"))
        h = self.db.q("SELECT * FROM ac_reservations WHERE id=?", (h["id"],), one=True)
        self.assertEqual((h["state"], h["actual"], h["prov"]), ("settled", 50_000, "estimated"))
        self.assertEqual(self.run_row()["metering"], "estimated")
        with self.assertRaises(LookupError): self.core.estimate(OWNER, self.rid, 50_000, "alice")   # idempotent: nothing twice
        self.assertEqual(self.run_row()["tokens"], 50_000)
        self.assertEqual(self.core.settle([h["id"]], 7_000), 0)             # a late real usage can't add on top of the person's figure
        self.assertEqual(self.run_row()["tokens"], 50_000)

    def _estimated(self, est):
        h = self.timeout(); self.core.estimate(OWNER, self.rid, est, "alice"); return h

    def test_l2_real_usage_above_the_estimate_counts_max_once(self):
        h = self._estimated(30_000)
        self.assertEqual(self.core.settle([h["id"]], 50_000), 20_000)
        self.assertEqual(self.run_row()["tokens"], 50_000)
        r = self.db.q("SELECT actual, state FROM ac_reservations WHERE id=?", (h["id"],), one=True)
        self.assertEqual((r["actual"], r["state"]), (50_000, "settled"))
        self.assertEqual(self.core.settle([h["id"]], 90_000), 0)                    # once: a second late settle changes nothing
        self.assertEqual(self.run_row()["tokens"], 50_000)
        self.assertEqual(len(self.audits("metering.estimate_real")), 1)

    def test_l2_real_usage_below_the_estimate_keeps_the_estimate(self):
        h = self._estimated(30_000)
        self.assertEqual(self.core.settle([h["id"]], 10_000), 0)
        self.assertEqual(self.run_row()["tokens"], 30_000)
        self.assertEqual(self.core.settle([h["id"]], 80_000), 0)                    # the first late figure was the one
        self.assertEqual(self.run_row()["tokens"], 30_000)
        self.assertEqual(len(self.audits("metering.estimate_real")), 1)

    def test_estimate_floor_falls_back_to_the_reservations_model(self):  # gap (b)
        for i in range(3):
            self.db.q("INSERT INTO ac_runs (system, owner_id, status, tokens, model, started) VALUES ('t',?,'done',30000,?,?)", (OWNER, "terminal:x", time.time()))
        self.assertIsNone(self.core.admit(2_000, model="terminal:x"))
        self.core.unmetered("timed out")
        self.core.call_failed(LLMError(TIMEOUT))
        self.assertIsNone(self.run_row()["model"])                              # as in the incident: the run row has no model
        self.assertEqual(self.core.estimate_floor(self.rid), 30_000)
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 12_000, "a")
        self.assertEqual(self.core.estimate(OWNER, self.rid, 30_000, "a")["tokens"], 30_000)


class Provisional(Base):
    on = True

    def test_timeout_charges_p_now(self):  # req 2
        h = self.timeout()
        self.assertEqual((h["state"], h["actual"], h["prov"]), ("charged", 10_000, "provisional"))
        r = self.run_row()
        self.assertEqual((r["metering"], r["tokens"]), ("provisional", 10_000))
        self.assertEqual(self.core._unmetered_in(OWNER), 0)
        self.assertIsNone(self.core.admit(100, model=M))                      # the work does not wait
        [a] = self.audits("metering.provisional")
        self.assertEqual((a["actor"], a["ref"]), ("system", f"run:{self.rid}")); self.assertIn("estimated, unverified", a["detail"])
        self.assertEqual([x["label"] for x in self.core.provisional_runs(OWNER)], ["estimated, unverified"])
        self.assertEqual(self.core.unmetered_runs(OWNER), [])

    def test_p_formula(self):  # req 3
        self.assertEqual(self.core.provisional_figure(M, 2_000, OWNER), 10_000)            # no history: the floor, never 0
        self.assertEqual(self.core.provisional_figure(None, 0, OWNER), 10_000)
        self.assertEqual(self.core.provisional_figure(M, 40_000, OWNER), 40_000)           # the reservation wins
        self.seed(M, [1_000] * 98 + [24_000, 24_288])
        self.assertEqual(self.core.provisional_figure(M, 2_000, OWNER), 2 * 24_000)        # 2 x p99 (nearest rank 99 of 100) wins
        self.seed(M, [900_000], ago=9 * 86400)                                       # older than 7 days: ignored
        self.seed(M, [800_000], prov="corrected")                                    # not a real measurement: ignored
        self.assertEqual(self.core.provisional_figure(M, 2_000, OWNER), 48_000)

    def test_p_is_per_model(self):
        self.seed("terminal:big", [60_000] * 20)
        self.assertEqual(self.core.provisional_figure("terminal:big", 1, OWNER), 120_000)
        self.assertEqual(self.core.provisional_figure("terminal:small", 1, OWNER), 10_000)
        h = self.timeout(model="terminal:small")
        self.assertEqual(h["actual"], 10_000)

    def test_not_a_single_timed_out_call_stays_d025(self):  # the spec's "everything else"
        h = self.timeout(single=False)                                              # a Codex-like path: no single_call flag
        self.assertEqual(h["state"], "unmetered"); self.assertEqual(self.run_row()["metering"], "unmetered")
        self.assertIn("token budget", self.core.admit(100, model=M) or "")
        # a Codex session that ends without usage
        agent_core._local.run = None; rid2 = self.new_run()
        self.core.unmetered("A Codex session ended without reporting its usage", rid2)
        self.assertEqual(self.run_row(rid2)["metering"], "unmetered")
        # a lost connection with no timeout mark
        agent_core._local.run = None; rid3 = self.new_run()
        self.db.q("UPDATE ac_runs SET metering=NULL WHERE id IN (?,?)", (self.rid, rid2))
        self.assertIsNone(self.core.admit(2_000, model=M)); self.core.call_failed(ConnectionResetError("reset"))
        self.assertEqual(self.run_row(rid3)["metering"], "unmetered")
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_reservations WHERE prov IS NOT NULL", one=True)["n"], 0)

    def test_an_api_call_with_a_bound_is_charged_at_its_bound_as_before(self):
        self.assertIsNone(self.core.admit(2_000, bound=9_000, model="anthropic:m"))
        self.core.call_failed(TimeoutError("read timed out"))
        h = self.db.q("SELECT * FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        r = self.run_row()
        self.assertEqual((h["state"], h["prov"], r["tokens"], r["metering"]), ("charged", None, 9_000, "charged"))

    def test_the_same_failure_twice_charges_once(self):  # req 2, idempotence
        self.timeout()
        self.core.call_failed(LLMError(TIMEOUT))
        self.assertEqual(self.run_row()["tokens"], 10_000)
        self.assertEqual(len(self.audits("metering.provisional")), 1)

    def test_a_provisional_run_with_counted_tokens_adds_p(self):
        self.assertIsNone(self.core.admit(2_000, model=M)); self.core.used(3_000)
        self.timeout()
        self.assertEqual(self.run_row()["tokens"], 13_000)

    def test_late_real_usage_replaces_p_exactly_once(self):  # req 2
        h = self.timeout()
        self.assertEqual(self.core.settle([h["id"]], 4_000), 4_000)
        r, h2 = self.run_row(), self.db.q("SELECT * FROM ac_reservations WHERE id=?", (h["id"],), one=True)
        self.assertEqual((r["tokens"], r["metering"]), (4_000, None))
        self.assertEqual((h2["state"], h2["actual"], h2["prov"]), ("settled", 4_000, "real"))
        self.assertEqual(self.core.settle([h["id"]], 4_000), 0)                      # a second settle changes nothing
        self.assertEqual(self.run_row()["tokens"], 4_000)
        self.assertEqual(len(self.audits("metering.provisional_replaced")), 1)

    def test_correction_up_and_down_with_a_note_audited(self):  # req 2, 7
        self.timeout()
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 4_000, "alice", "")
        with self.assertRaises(LookupError): self.core.estimate(2, self.rid, 20_000, "mallory", "x")
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 4_000, "alice", "invoice")   # A1: below the floor: refused
        r = self.core.estimate(OWNER, self.rid, 10_000, "alice", "checked the provider's invoice")  # at the floor: allowed with a note
        self.assertEqual((r["path"], r["tokens"]), ("correct", 10_000))
        self.assertEqual(self.run_row()["metering"], "estimated")
        r = self.core.estimate(OWNER, self.rid, 90_000, "alice", "it ran long")                      # up; replaces, never adds
        self.assertEqual(r["tokens"], 90_000)
        self.assertEqual(self.core.estimate(OWNER, self.rid, 90_000, "alice", "again")["tokens"], 90_000)
        h = self.db.q("SELECT * FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        self.assertEqual((h["state"], h["actual"], h["prov"]), ("settled", 90_000, "corrected"))
        self.assertEqual(self.core.settle([h["id"]], 7_000), 0)                                       # real usage below a correction: the person's figure stands
        self.assertEqual(self.run_row()["tokens"], 90_000)
        a = self.audits("metering.correct")
        self.assertEqual(len(a), 3); self.assertIn("provisional 10,000 tokens corrected to 10,000", a[0]["detail"]); self.assertEqual(a[0]["actor"], "alice")

    def test_breaker_count_more_than_three_in_24h(self):  # req 4
        for i in range(3):
            agent_core._local.run = None; rid = self.new_run(team="comp:1")
            self.assertEqual(self.timeout()["prov"], "provisional")
        agent_core._local.run = None; r4 = self.new_run(team="comp:1")
        h = self.timeout()                                                           # the 4th: D-025
        self.assertEqual((h["state"], h["prov"]), ("unmetered", None))
        self.assertEqual(self.run_row(r4)["metering"], "unmetered")
        self.assertIn("token budget", self.core.admit(100, model=M) or "")          # the team holds until a person records an estimate
        self.assertEqual(len(self.audits("metering.provisional_refused")), 1)
        agent_core._local.run = None; self.new_run(team="comp:2")
        # a person's estimate lifts the hold; a correction does NOT reset the count (charges made, not charges still open)
        self.core.estimate(OWNER, r4, 10_000, "alice")
        self.core.estimate(OWNER, rid, 12_000, "alice", "reviewed")
        agent_core._local.run = None; r5 = self.new_run(team="comp:1")
        self.assertEqual(self.timeout()["prov"], None)
        self.assertEqual(self.run_row(r5)["metering"], "unmetered")

    def test_breaker_old_charges_do_not_count(self):
        for i in range(3):
            agent_core._local.run = None; self.new_run(team="comp:1"); self.timeout()
        self.db.q("UPDATE ac_reservations SET settled=?, prov_at=? WHERE prov='provisional'", (time.time() - 90_000, time.time() - 90_000))
        agent_core._local.run = None; self.new_run(team="comp:1")
        self.assertEqual(self.timeout()["prov"], "provisional")

    def test_breaker_share_of_the_team_budget(self):  # req 4
        budget = 150_000                                                              # 10% = 15,000: one P of 10,000 fits, two do not
        agent_core.register_bucket("tb", lambda run: [{"limit": budget, "start_limit": budget, "spent": 0, "runs": ("team=?", (run.get("team"),)), "since": time.time() - 86400,
                                                       "label": "tb", "key": run.get("team"), "message": lambda n, h, e: "token budget"}] if run.get("team") else [])
        agent_core._local.run = None; self.new_run(team="comp:1")
        self.assertEqual(self.timeout()["prov"], "provisional")
        agent_core._local.run = None; r2 = self.new_run(team="comp:1")
        h = self.timeout()
        self.assertEqual((h["state"], h["prov"]), ("unmetered", None))
        self.assertEqual(self.run_row(r2)["metering"], "unmetered")
        self.assertIn("over 10%", self.audits("metering.provisional_refused")[0]["detail"])

    def test_provisional_counts_in_every_budget(self):  # req 5
        self.timeout()                                                                # 10,000 on this run
        # (a) ac_limits: a team-scope limit sees it in its spent
        self.db.q("UPDATE ac_runs SET team='comp:1' WHERE id=?", (self.rid,))
        self.core.set_limit(OWNER, "team", "comp:1", 12_000, period="day", label="team", origin="manual", by="t")
        agent_core._local.run = None; self.new_run(team="comp:1")
        self.assertIn("token budget", self.core.admit(5_000, model=M) or "")          # 10,000 + 5,000 > 12,000
        self.assertIsNone(self.core.admit(1_000, model=M))                            # 10,000 + 1,000 fits
        # (b) the owner daily cap
        agent_core._local.run = None; self.new_run(system="t2")
        self.core.set_cap(OWNER, 12_000, "t")
        self.assertIn("token budget", self.core.admit(5_000, model=M) or "")
        self.assertEqual(self.core.spent_today(OWNER), 10_000)
        # (c) the team 24 h budget (the bucket reads the ledger) and the guard's day_tokens
        agent_core._local.run = None; self.new_run(team="comp:1")
        self.core.set_cap(OWNER, None, "t")
        self.db.q("DELETE FROM ac_limits")
        led = self.db.q("SELECT COALESCE(SUM(tokens),0) n FROM ac_runs WHERE team='comp:1' AND started>?", (time.time() - 86400,), one=True)["n"]
        self.assertEqual(led, 10_000)
        self.db.q("UPDATE ac_runs SET status='done', system='teams' WHERE id=?", (self.rid,))
        self.db.q("CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, started REAL, tokens INTEGER)")
        fake = types.SimpleNamespace(db=self.db, _flying=lambda w: 0)
        with mock.patch.object(agent_core, "get", return_value=self.core):
            self.assertEqual(mining_work.Work.day_tokens(fake, 1), 10_000)        # the guard's and the governor's number

    # ---------------- review fixes ----------------
    def test_m1_day_tokens_does_not_count_real_tokens_twice(self):
        self.timeout()                                                                # P = 10,000
        self.db.q("UPDATE ac_runs SET team='comp:1', system='teams', tokens=tokens+40000, status='done' WHERE id=?", (self.rid,))
        self.db.q("CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, started REAL, tokens INTEGER)")
        self.db.q("INSERT INTO mw_runs (comp_id, started, tokens) VALUES (1,?,40000)", (time.time(),))   # the run's real tokens, as mining_work records them
        fake = types.SimpleNamespace(db=self.db, _flying=lambda w: 0)
        with mock.patch.object(agent_core, "get", return_value=self.core):
            self.assertEqual(mining_work.Work.day_tokens(fake, 1), 50_000)
            self.core.estimate(OWNER, self.rid, 12_000, "alice", "checked")          # after a correction: the corrected figure, not P
            self.assertEqual(mining_work.Work.day_tokens(fake, 1), 52_000)

    def test_m2_a_persons_estimate_does_not_poison_p(self):
        os.environ.pop("AC_PROVISIONAL")
        self.timeout(single=False)
        self.core.estimate(OWNER, self.rid, 5_000_000, "x")
        os.environ["AC_PROVISIONAL"] = "1"
        self.seed(M, [5_000] * 30)
        self.assertEqual(self.core.provisional_figure(M, 2_000, OWNER), 10_000)       # p99 5,000 x 2 = floor; the 5,000,000 estimate isn't a sample
        self.assertEqual(self.db.q("SELECT prov FROM ac_reservations WHERE actual=5000000", one=True)["prov"], "estimated")

    def test_m2_p99_is_per_owner_and_needs_20_samples(self):
        self.seed(M, [100_000] * 30)                                                   # OWNER's history
        self.assertEqual(self.core.provisional_figure(M, 2_000, OWNER), 200_000)
        self.assertEqual(self.core.provisional_figure(M, 2_000, 2), 10_000)           # another owner never sees it
        self.db.q("DELETE FROM ac_reservations"); self.seed(M, [100_000] * 19)
        self.assertEqual(self.core.provisional_figure(M, 2_000, OWNER), 10_000)       # 19 samples: no p99
        self.assertEqual(self.core.provisional_figure(M, 40_000, OWNER), 40_000)

    def test_m3_late_real_usage_does_not_reset_the_breaker(self):
        for i in range(3):
            agent_core._local.run = None; self.new_run(team="comp:1")
            h = self.timeout(); self.assertEqual(h["prov"], "provisional")
            self.core.settle([h["id"]], 3_000)                                         # the real figure comes late: the charge was still made
        agent_core._local.run = None; r4 = self.new_run(team="comp:1")
        h = self.timeout()
        self.assertEqual((h["state"], h["prov"]), ("unmetered", None))                  # the 4th is refused although none of the 3 is open
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_reservations WHERE prov_at IS NOT NULL", one=True)["n"], 3)

    def test_m3_share_sums_the_original_p(self):
        budget = 150_000
        agent_core.register_bucket("tb", lambda run: [{"limit": budget, "start_limit": budget, "spent": 0, "runs": ("team=?", (run.get("team"),)), "since": time.time() - 86400,
                                                       "label": "tb", "key": run.get("team"), "message": lambda n, h, e: "token budget"}] if run.get("team") else [])
        agent_core._local.run = None; self.new_run(team="comp:1")
        h = self.timeout(); self.core.settle([h["id"]], 100)                          # replaced by a tiny real figure: P (10,000) still counts
        agent_core._local.run = None; r2 = self.new_run(team="comp:1")
        self.assertEqual(self.timeout()["prov"], None)

    def test_m4a_two_connections_cannot_both_pass_the_breaker(self):
        import threading
        cores = [self.core, agent_core.Core(AuthDB(os.path.join(self.dir.name, "a.db")))]
        res, go = [], threading.Barrier(6)
        def work(i):
            c = cores[i % 2]
            agent_core._local.run = None
            rid = c.begin("t", OWNER, "task", ref=f"c:{i}"); agent_core._local.run["team"] = "comp:1"
            self.db.q("UPDATE ac_runs SET team='comp:1' WHERE id=?", (rid,))
            self.assertIsNone(c.admit(2_000, model=M)); c.unmetered("timed out", single_call=True)
            go.wait(); c.call_failed(LLMError(TIMEOUT)); res.append(rid)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(6)]
        for t in ts: t.start()
        for t in ts: t.join(60)
        self.assertEqual(len(res), 6)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_reservations WHERE prov_at IS NOT NULL", one=True)["n"], 3)

    def test_m4b_correct_is_guarded_by_row_state(self):
        self.timeout()
        self.db.q("UPDATE ac_reservations SET state='released' WHERE run_id=?", (self.rid,))   # changed under us
        before = self.run_row()["tokens"]
        with self.assertRaises(LookupError): self.core._correct(OWNER, self.rid, 99_000, "a", "n")
        self.assertEqual(self.run_row()["tokens"], before)                           # no token delta without a matching row

    def test_l1_p_uses_the_runs_model_when_the_reservation_has_none(self):
        for i in range(3):
            self.db.q("INSERT INTO ac_runs (system, owner_id, status, tokens, model, started) VALUES ('t',?,'done',30000,?,?)", (OWNER, M, time.time()))
        self.db.q("UPDATE ac_runs SET model=? WHERE id=?", (M, self.rid))
        self.assertIsNone(self.core.admit(2_000, model=None))
        self.core.unmetered("t", single_call=True); self.core.call_failed(LLMError(TIMEOUT))
        h = self.db.q("SELECT actual FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        self.assertEqual(h["actual"], 30_000); self.assertEqual(h["actual"], self.core.estimate_floor(self.rid))

    def test_l4_merged_siblings_are_not_open_provisional_charges(self):
        h1 = self.timeout()
        h2 = self.timeout()                                                          # a second timed-out call on the same run
        self.assertEqual(self.run_row()["tokens"], 20_000)
        self.core.settle([h1["id"], h2["id"]], 5_000)                                 # one session figure for both
        rows = self.db.q("SELECT state, prov FROM ac_reservations WHERE run_id=? ORDER BY id", (self.rid,))
        self.assertNotIn("provisional", [r["prov"] for r in rows])
        r = self.run_row(); self.assertEqual((r["tokens"], r["metering"]), (5_000, None))

    def test_l5_a_later_d025_estimate_replaces_p_never_stacks(self):
        self.timeout()                                                               # P = 10,000
        self.core.unmetered("a Codex session ended without usage", self.rid)          # the run goes unmetered after the charge
        self.assertEqual(self.run_row()["metering"], "unmetered")
        r = self.core.estimate(OWNER, self.rid, 30_000, "alice")
        self.assertEqual(r["tokens"], 30_000)                                         # not 40,000
        self.assertEqual(self.run_row()["tokens"], 30_000)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_reservations WHERE prov='provisional'", one=True)["n"], 0)

    def test_restart_keeps_the_charge(self):
        self.timeout()
        agent_core.Core(AuthDB(os.path.join(self.dir.name, "a.db")))                 # a restart's recovery
        r = self.run_row(); self.assertEqual((r["tokens"], r["metering"]), (10_000, "provisional"))

    def test_additive_nullable_schema(self):  # req 8
        col = [c for c in self.db.q("PRAGMA table_info(ac_reservations)") if c["name"] == "prov"]
        self.assertEqual(len(col), 1); self.assertFalse(col[0]["notnull"])
        agent_core.Core(AuthDB(os.path.join(self.dir.name, "a.db")))                 # a second start adds nothing, breaks nothing

    def test_through_the_real_cli_timeout_path(self):
        def boom(*a, **kw): raise subprocess.TimeoutExpired("claude", 150)
        with mock.patch.object(llm, "_cli_exe", return_value="claude"), mock.patch.object(llm, "_cli_env", return_value={}), \
                mock.patch.object(llm.subprocess, "run", side_effect=boom):
            self.assertIsNone(self.core.admit(2_000, model=M))
            with self.assertRaises(LLMError): llm._counted_call(llm._cli_once, "hi", timeout=150)
        h = self.db.q("SELECT * FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        self.assertEqual((h["state"], h["prov"], self.run_row()["metering"]), ("charged", "provisional", "provisional"))

    def test_through_the_real_cli_timeout_path_switch_off(self):
        os.environ.pop("AC_PROVISIONAL")
        def boom(*a, **kw): raise subprocess.TimeoutExpired("claude", 150)
        with mock.patch.object(llm, "_cli_exe", return_value="claude"), mock.patch.object(llm, "_cli_env", return_value={}), \
                mock.patch.object(llm.subprocess, "run", side_effect=boom):
            self.assertIsNone(self.core.admit(2_000, model=M))
            with self.assertRaises(LLMError): llm._counted_call(llm._cli_once, "hi", timeout=150)
        h = self.db.q("SELECT * FROM ac_reservations WHERE run_id=?", (self.rid,), one=True)
        self.assertEqual((h["state"], self.run_row()["metering"]), ("unmetered", "unmetered"))


if __name__ == "__main__":
    unittest.main()


class CorrectionFinality(Base):
    """A1 (2026-11-15 closure, delegated decision): a person's figure is a floor, never a cap. A correction has the D-025 floor and a
    typo ceiling; real usage reported after it counts as max(figure, all real usage reported since), once per hold."""
    on = True

    def hold(self, rid):
        return self.db.q("SELECT * FROM ac_reservations WHERE id=?", (rid,), one=True)

    def test_floor_and_ceiling(self):
        self.timeout()                                                                    # P = 10,000 = floor
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 9_999, "a", "n")
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 100_001, "a", "n")   # 10 x max(P, floor)
        self.assertEqual(self.core.estimate(OWNER, self.rid, 100_000, "a", "n")["tokens"], 100_000)
        self.assertEqual(self.core.estimate(OWNER, self.rid, 10_000, "a", "n")["tokens"], 10_000)
        self.assertEqual(self.run_row()["tokens"], 10_000)
        self.assertEqual(len(self.audits("metering.correct")), 2)                       # refusals change nothing and write nothing

    def test_ceiling_follows_a_larger_p(self):
        self.seed(M, [50_000] * 25)                                                       # p99 50,000: P = 100,000
        self.timeout()
        self.assertEqual(self.run_row()["tokens"], 100_000)
        self.assertEqual(self.core.estimate(OWNER, self.rid, 1_000_000, "a", "long run")["tokens"], 1_000_000)
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 1_000_001, "a", "n")

    def test_late_real_above_a_correction_counts_max_once(self):
        h = self.timeout()
        self.core.estimate(OWNER, self.rid, 20_000, "alice", "looked at the log")
        self.assertEqual(self.core.settle([h["id"]], 35_000), 15_000)                    # max(20,000, 35,000): +15,000
        self.assertEqual(self.run_row()["tokens"], 35_000)
        x = self.hold(h["id"])
        self.assertEqual((x["state"], x["actual"], x["prov"], x["late_real"]), ("settled", 35_000, "corrected_real", 35_000))
        self.assertEqual(self.core.settle([h["id"]], 35_000), 0)                         # the same hold twice: once
        self.assertEqual(self.run_row()["tokens"], 35_000)
        self.assertEqual(len(self.audits("metering.real_after_person")), 1)

    def test_late_real_below_a_correction_keeps_the_figure_and_marks_it(self):
        h = self.timeout()
        self.core.estimate(OWNER, self.rid, 20_000, "alice", "n")
        self.assertEqual(self.core.settle([h["id"]], 5_000), 0)
        x = self.hold(h["id"])
        self.assertEqual((x["actual"], x["late_real"], x["prov"]), (20_000, 5_000, "corrected_real"))
        self.assertEqual(self.run_row()["tokens"], 20_000)

    def test_two_holds_reported_separately_accumulate(self):
        h1 = self.timeout(); h2 = self.timeout()                                          # 2 x P = 20,000
        self.core.estimate(OWNER, self.rid, 30_000, "alice", "both calls")
        self.assertEqual(self.run_row()["tokens"], 30_000)
        self.assertEqual(self.core.settle([h2["id"]], 18_000), 0)                        # 18,000 <= 30,000
        self.assertEqual(self.core.settle([h1["id"]], 25_000), 13_000)                   # real 43,000 > 30,000: +13,000
        self.assertEqual(self.core.settle([h1["id"]], 25_000), 0)
        self.assertEqual(self.run_row()["tokens"], 43_000)

    def test_d025_estimate_after_p_then_late_real_counts_max(self):  # pass-2 LOW 1
        h = self.timeout()                                                                # P = 10,000
        self.core.unmetered("a Codex session ended without usage", self.rid)
        self.core.estimate(OWNER, self.rid, 30_000, "alice")                             # replaces P (L5)
        self.assertEqual(self.run_row()["tokens"], 30_000)
        self.assertEqual(self.core.settle([h["id"]], 45_000), 15_000)
        self.assertEqual(self.run_row()["tokens"], 45_000)
        self.assertEqual(self.core.settle([h["id"]], 45_000), 0)

    def test_a_correction_after_real_usage_never_undercuts_it(self):
        h = self.timeout()
        self.core.estimate(OWNER, self.rid, 20_000, "alice", "n")
        self.core.settle([h["id"]], 35_000)
        r = self.core.estimate(OWNER, self.rid, 12_000, "alice", "second look")           # the person lowers it: real usage still counts
        self.assertEqual((r["path"], r["tokens"]), ("correct", 35_000))
        r = self.core.estimate(OWNER, self.rid, 60_000, "alice", "it was longer")
        self.assertEqual(r["tokens"], 60_000)
        self.assertEqual(self.hold(h["id"])["prov"], "corrected_real")

    # ---------------- A1 review pass 1 (F1-F3, LOW 2) ----------------
    def test_f1_the_figure_rows_own_report_counts_after_a_sibling_reported(self):
        h1 = self.timeout(); h2 = self.timeout()
        self.core.estimate(OWNER, self.rid, 30_000, "a", "n")                            # h2 carries the figure, h1 merged into it
        self.assertEqual(self.core.settle([h1["id"]], 5_000), 0)
        self.assertEqual(self.core.settle([h2["id"]], 40_000), 15_000)                   # real 45,000 > 30,000
        self.assertEqual(self.run_row()["tokens"], 45_000)

    def test_f2_a_new_episodes_corrections_leave_the_earlier_groups_real_usage(self):
        h1 = self.timeout(); h2 = self.timeout()
        self.core.estimate(OWNER, self.rid, 30_000, "a", "n")
        self.core.settle([h2["id"]], 50_000)                                              # group 1 counts 50,000
        self.timeout()                                                                    # a new provisional charge: 60,000
        self.core.estimate(OWNER, self.rid, 20_000, "a", "n2")                            # group 2: 70,000
        self.core.estimate(OWNER, self.rid, 20_000, "a", "n3")                            # re-corrects group 2 only
        self.assertEqual(self.run_row()["tokens"], 70_000)
        s = self.db.q("SELECT COALESCE(SUM(actual),0) AS n FROM ac_reservations WHERE run_id=? AND state='settled'", (self.rid,), one=True)["n"]
        self.assertEqual(s, 70_000)

    def test_f3_real_usage_is_compared_with_its_own_groups_figure(self):
        h1 = self.timeout(); self.core.estimate(OWNER, self.rid, 30_000, "a", "n")
        self.timeout(); self.core.estimate(OWNER, self.rid, 60_000, "a", "n")             # two groups: 90,000
        self.assertEqual(self.core.settle([h1["id"]], 50_000), 20_000)                    # against 30,000, not 60,000
        self.assertEqual(self.run_row()["tokens"], 110_000)

    def test_low2_a_person_can_re_correct_after_a_d025_estimate_replaced_p(self):
        h = self.timeout()
        self.core.unmetered("a Codex session ended without usage", self.rid)
        self.core.estimate(OWNER, self.rid, 30_000, "alice")
        r = self.core.estimate(OWNER, self.rid, 25_000, "alice", "second look")
        self.assertEqual((r["path"], r["tokens"]), ("correct", 25_000))
        self.assertEqual(self.core.settle([h["id"]], 40_000), 15_000)
        self.assertEqual(self.run_row()["tokens"], 40_000)

    # ---------------- A1 review pass 2 (G1, G2, G4) ----------------
    def unm_hold(self):
        self.assertIsNone(self.core.admit(2_000, model=M))
        self.core.unmetered("a Codex session ended without usage"); self.core.call_failed(LLMError("no usage"))
        return self.db.q("SELECT * FROM ac_reservations WHERE run_id=? ORDER BY id DESC LIMIT 1", (self.rid,), one=True)

    def test_g1_a_d025_estimate_on_a_d036_run_is_its_own_group(self):
        self.timeout(); self.core.estimate(OWNER, self.rid, 15_000, "a", "n")           # group 1: 15,000
        hu = self.unm_hold(); self.core.estimate(OWNER, self.rid, 20_000, "a")         # D-025 group: 20,000
        self.timeout(); self.core.estimate(OWNER, self.rid, 30_000, "a", "n")           # group 3: 30,000
        self.assertEqual(self.core.settle([hu["id"]], 100_000), 80_000)                 # against its own 20,000
        self.assertEqual(self.run_row()["tokens"], 145_000)

    def test_g2_a_report_naming_two_groups_never_undercounts(self):
        h1 = self.timeout(); self.core.estimate(OWNER, self.rid, 100_000, "a", "n")
        h2 = self.timeout(); self.core.estimate(OWNER, self.rid, 10_000, "a", "n")
        self.core.settle([h1["id"], h2["id"]], 100_000)                                 # counted on the smaller figure's group
        self.assertEqual(self.run_row()["tokens"], 200_000)                              # >= every split of the 100,000

    def test_g2_the_anchor_is_the_group_with_least_headroom_not_the_smallest_figure(self):  # advisor, after pass 2
        h1 = self.timeout(); h2 = self.timeout(); self.core.estimate(OWNER, self.rid, 100_000, "a", "n")   # group A on h2
        self.core.settle([h1["id"]], 90_000)                                                             # A: headroom 10,000
        h3 = self.timeout(); self.core.estimate(OWNER, self.rid, 50_000, "a", "n")                       # B: headroom 50,000
        self.assertEqual(self.core.settle([h2["id"], h3["id"]], 20_000), 10_000)                          # counted on A
        self.assertEqual(self.run_row()["tokens"], 160_000)                                               # >= every split

    def test_r4_a_late_report_on_the_figure_row_never_drops_the_teams_24h_count(self):  # advisor, after review 3
        h = self.timeout()
        self.db.q("UPDATE ac_runs SET team='comp:1', system='teams', status='done' WHERE id=?", (self.rid,))
        self.db.q("CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, started REAL, tokens INTEGER)")
        fake = types.SimpleNamespace(db=self.db, _flying=lambda w: 0)
        with mock.patch.object(agent_core, "get", return_value=self.core):
            self.core.estimate(OWNER, self.rid, 20_000, "alice", "checked")
            self.assertEqual(mining_work.Work.day_tokens(fake, 1), 20_000)
            self.core.settle([h["id"]], 35_000)                                       # the figure row itself reports late
            self.assertEqual(mining_work.Work.day_tokens(fake, 1), 35_000)           # max(figure, real), not 0

    def day(self):
        fake = types.SimpleNamespace(db=self.db, _flying=lambda w: 0)
        with mock.patch.object(agent_core, "get", return_value=self.core): return mining_work.Work.day_tokens(fake, 1)

    def teams_run(self):
        self.db.q("UPDATE ac_runs SET team='comp:1', system='teams', status='done' WHERE id=?", (self.rid,))
        self.db.q("CREATE TABLE IF NOT EXISTS mw_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, started REAL, tokens INTEGER)")

    def test_r5_late_real_replacing_p_after_the_run_ended_stays_in_the_teams_count(self):  # review 4 finding 1
        h = self.timeout(); self.teams_run()
        self.assertEqual(self.day(), 10_000)
        self.core.settle([h["id"]], 35_000)
        self.assertEqual(self.day(), 35_000)

    def test_r5_a_d025_estimate_that_replaced_p_stays_in_the_teams_count(self):  # review 4 finding 2
        self.timeout(); self.teams_run()
        self.core.unmetered("a Codex session ended without usage", self.rid)
        self.core.estimate(OWNER, self.rid, 30_000, "alice")
        self.assertEqual(self.day(), 30_000)

    def test_r5_a_d025_estimate_on_an_unmetered_hold_after_p_stays_in_the_teams_count(self):  # review 4 probe S3
        h = self.timeout(); self.unm_hold(); self.teams_run()
        self.core.estimate(OWNER, self.rid, 30_000, "alice")                       # the figure rides on the unmetered hold ('estimated')
        self.assertEqual(self.run_row()["tokens"], 30_000)
        self.assertEqual(self.day(), 30_000)

    def test_r3_a_multi_group_report_counts_on_each_group_so_later_reports_never_undercount(self):  # review 3 F1
        hA = self.timeout(); self.core.estimate(OWNER, self.rid, 50_000, "a", "n")                         # A: 50,000
        hB1 = self.timeout(); hB2 = self.timeout(); self.core.estimate(OWNER, self.rid, 50_000, "a", "n")  # B: 50,000 (two holds)
        self.core.settle([hA["id"], hB1["id"]], 100_000)          # could be A's or B's: counted on both (A 100,000, B 100,000)
        self.core.settle([hB2["id"]], 100_000)                    # B: at least 200,000 if R1 was all hB1's
        self.assertGreaterEqual(self.run_row()["tokens"], 250_000)
        self.core.estimate(OWNER, self.rid, 30_000, "a", "re-correct B")   # a lower figure never undercuts the group's real usage
        self.assertGreaterEqual(self.run_row()["tokens"], 250_000)

    def test_r3_a_figure_row_without_fig_id_anchors_on_itself(self):  # review 3 F2
        hu = self.unm_hold(); self.core.estimate(OWNER, self.rid, 20_000, "a")                             # D-025 group U
        self.db.q("UPDATE ac_reservations SET fig_id=NULL WHERE id=?", (hu["id"],))                         # as a row written before fig_id
        self.timeout(); self.core.estimate(OWNER, self.rid, 100_000, "a", "n")                             # group T: 100,000
        self.assertEqual(self.core.settle([hu["id"]], 90_000), 70_000)                                    # against U's 20,000
        self.assertEqual(self.run_row()["tokens"], 190_000)

    def test_g4_a_group_written_before_fig_id_uses_the_runs_provisional_figures_for_the_ceiling(self):
        for _ in range(3): self.timeout()
        self.core.estimate(OWNER, self.rid, 30_000, "a", "n")
        self.db.q("UPDATE ac_reservations SET fig_id=NULL WHERE run_id=?", (self.rid,))
        self.assertEqual(self.core.estimate(OWNER, self.rid, 300_000, "a", "n2")["tokens"], 300_000)
        with self.assertRaises(ValueError): self.core.estimate(OWNER, self.rid, 300_001, "a", "n3")

    def test_breaker_still_counts_charges_made(self):
        h = self.timeout(); self.core.estimate(OWNER, self.rid, 20_000, "a", "n"); self.core.settle([h["id"]], 50_000)
        n = self.db.q("SELECT COUNT(*) AS n FROM ac_reservations WHERE prov_at IS NOT NULL", one=True)["n"]
        self.assertEqual(n, 1)


class SwitchOffUnchangedByA1(Base):
    """A1 touches only runs charged provisionally: a D-025-only run keeps the 8d1188a behaviour (max(estimate, real) once, by the
    estimated row; a second hold's late report is not added)."""
    def test_d025_late_real_unchanged(self):
        h = self.timeout(single=False)
        self.core.estimate(OWNER, self.rid, 30_000, "alice")
        self.assertEqual(self.db.q("SELECT prov FROM ac_reservations WHERE id=?", (h["id"],), one=True)["prov"], "estimated")
        self.assertEqual(self.core.settle([h["id"]], 40_000), 10_000)
        self.assertEqual(self.core.settle([h["id"]], 40_000), 0)
        x = self.db.q("SELECT * FROM ac_reservations WHERE id=?", (h["id"],), one=True)
        self.assertEqual((x["prov"], x["actual"], x["late_real"]), ("estimated_real", 40_000, None))   # the 8d1188a path, untouched
        self.assertEqual(self.run_row()["tokens"], 40_000)
        self.assertEqual(self.audits("metering.real_after_person"), [])
        self.assertEqual(len(self.audits("metering.estimate_real")), 1)


class RateLimitRetryReserves(Base):
    """A2 defect 1 (2026-11-15 closure): a brief rate-limit result that reports usage settles the call's reservation; the in-place
    retry (retry_brief) is a new model call and takes its own reservation, so the ledger reconciles and a timed-out retry can be
    charged (switch on) or held (switch off) like any call."""
    RL = '{"type": "result", "subtype": "error", "is_error": true, "result": "API Error: 429 rate limit exceeded, retry in 1 seconds", "usage": {"input_tokens": 0, "output_tokens": 0}}'
    OK = '{"type": "result", "subtype": "success", "is_error": false, "result": "OK", "usage": {"input_tokens": 1500, "output_tokens": 500}}'

    def call(self, outs):
        seq = iter(outs)
        def fake(*a, **kw):
            x = next(seq)
            if isinstance(x, BaseException): raise x
            return subprocess.CompletedProcess(a, 0, stdout=x, stderr="")
        with mock.patch.object(llm, "_cli_exe", return_value="claude"), mock.patch.object(llm, "_cli_env", return_value={}), \
                mock.patch.object(llm.subprocess, "run", side_effect=fake), mock.patch.object(llm.time, "sleep"):
            llm._gate(2_000, model=M)
            out = llm._counted_call(llm._cli, "hi", timeout=150)
        agent_core.used(llm._cli_tokens(out))   # what the caller (turn / _structured) records on success
        return out

    def reservations(self):
        return self.db.q("SELECT state, actual, prov FROM ac_reservations WHERE run_id=? ORDER BY id", (self.rid,))

    def test_a_retry_after_a_limited_attempt_with_usage_has_its_own_reservation(self):
        self.call([self.RL, self.OK])
        rs = self.reservations()
        self.assertEqual([(r["state"], r["actual"]) for r in rs], [("settled", 0), ("settled", 2_000)])
        self.assertEqual(self.run_row()["tokens"], sum(r["actual"] for r in rs))

    def test_a_limited_attempt_without_usage_keeps_its_one_reservation(self):
        self.call([self.RL.replace(', "usage": {"input_tokens": 0, "output_tokens": 0}', ""), self.OK])
        self.assertEqual([(r["state"], r["actual"]) for r in self.reservations()], [("settled", 2_000)])

    def test_switch_off_a_retry_that_times_out_is_unmetered_on_its_own_hold(self):
        os.environ.pop("AC_PROVISIONAL", None)
        with self.assertRaises(LLMError): self.call([self.RL, subprocess.TimeoutExpired("claude", 150)])
        self.assertEqual([(r["state"], r["prov"]) for r in self.reservations()], [("settled", None), ("unmetered", None)])
        self.assertEqual(self.run_row()["metering"], "unmetered")

    def test_the_retry_is_refused_when_the_budget_refuses_it(self):
        self.core.set_limit(OWNER, "system", "t", 2_500, period="day", label="tight", origin="manual", by="test")
        self.db.q("UPDATE ac_runs SET tokens=1000 WHERE id=?", (self.rid,))
        with self.assertRaises(LLMError): self.call([self.RL, self.OK])


    def test_stale_gate_args_never_reach_an_ungated_retry(self):  # retry review F1
        self.assertIsNone(self.core.admit(3_000, model="anthropic:x")); self.core.used(100)   # an API call: its hold settled
        llm._gated.args = {"estimate": 90_000, "bound": 90_000, "model": "anthropic:x", "reserve": None, "hold": None}
        seq = iter([self.RL, self.OK])
        with mock.patch.object(llm, "_cli_exe", return_value="claude"), mock.patch.object(llm, "_cli_env", return_value={}), \
                mock.patch.object(llm.subprocess, "run", side_effect=lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=next(seq), stderr="")), \
                mock.patch.object(llm.time, "sleep"):
            llm._cli("Reply with OK.", timeout=120)                                    # ungated (as cli_check)
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM ac_reservations WHERE state='held'", one=True)["n"], 0)
        self.assertIsNone(getattr(llm._gated, "args", None))

    def test_a_refused_gate_leaves_no_args(self):
        self.core.set_limit(OWNER, "system", "t", 10, period="day", label="tiny", origin="manual", by="test")
        with self.assertRaises(LLMError): llm._gate(2_000, model=M)
        self.assertIsNone(getattr(llm._gated, "args", None))


class RateLimitRetryReservesOn(RateLimitRetryReserves):
    on = True

    def test_switch_on_a_retry_that_times_out_is_charged_provisionally(self):
        with self.assertRaises(LLMError): self.call([self.RL, subprocess.TimeoutExpired("claude", 150)])
        self.assertEqual([(r["state"], r["prov"]) for r in self.reservations()], [("settled", None), ("charged", "provisional")])

