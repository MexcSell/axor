"""D-004 completion, milestone D4.2: a persistent mission's measures read from evidence (EVIDENCE_PROVENANCE_SPEC.md).

- Three categories: external (chain samples for attested keys; ingest from a key the Owner designated an independent evaluator's),
  internal (benchmarks: valid only with G5-4 V4.4's evidence reference; test_g54_release_evidence.py), self-reported (team keys, undesignated keys, manual entries).
- Only valid external evidence can make the competition outcome PASS. Missing, stale, unverifiable, conflicting or self-reported
  evidence is UNKNOWN, and a technical PASS never makes a competition PASS.
- Ingest provenance (K-20): the key that sent a report and when AXoR received it are recorded; freshness uses the receipt time; a
  designation never upgrades reports received before it; a revoked key's reports never count; only the Owner designates.
- Reading evidence writes nothing, makes no model call and no network call.
"""
import json, os, tempfile, time, types, unittest, zlib
from unittest import mock

from fastapi import HTTPException

from app import mining_command, missions, orchestrator
from app.auth import AuthDB

OWNER, ADMIN, TEAM_ACCOUNT = 11, 12, 14
WID, NETUID = 22, 62
HOT, COLD, OTHER = "5Hot", "5Cold", "5Other"


def schema(q):
    q("CREATE TABLE IF NOT EXISTS mh_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, netuid INTEGER, mech INTEGER, keys TEXT)")
    q("""CREATE TABLE IF NOT EXISTS mw_comps (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, number INTEGER, name TEXT, status TEXT,
         paused INTEGER DEFAULT 0, autopilot INTEGER DEFAULT 0, goal TEXT, budget INTEGER, last_plan REAL)""")
    q("CREATE TABLE IF NOT EXISTS mc_miners (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, campaign_id INTEGER, comp_id INTEGER, hotkey TEXT)")
    q("""CREATE TABLE IF NOT EXISTS mh_samples (id INTEGER PRIMARY KEY, netuid INTEGER, block INTEGER, ts REAL, head TEXT, stats TEXT, rows BLOB,
         mech INTEGER DEFAULT 0)""")


def row(uid, hk, ck, em, inc=0.0, ax=1, validator=False):
    return {"u": uid, "hk": hk, "ck": ck, "em": em, "inc": inc, "tr": 0.5, "cs": 0.5, "ps": 0.1, "st": 10.0, "ax": ax,
            "vp": 1 if validator else 0, "div": 0.2 if validator else 0, "im": 0, "rb": 1, "cm": None, "cb": None}


def chain_measure(metric="rank", op="<=", target=10, **kw):
    return {"id": f"chain_{metric}", "text": f"Chain {metric}", "tier": "external", "source": "chain", "metric": metric, "op": op, "target": target} | kw


def ingest_measure(metric="rank", op="<=", target=10, **kw):
    return {"id": f"ingest_{metric}", "text": f"Evaluator {metric}", "tier": "external", "source": "ingest", "metric": metric, "op": op, "target": target} | kw


def bench_measure():
    return {"id": "bench_score", "text": "Frozen-suite score", "tier": "internal", "source": "bench", "metric": "score", "op": ">=", "target": 0.8}


class Forbidden:
    def __init__(self, what): self.what = what
    def __getattr__(self, name): raise AssertionError(f"{self.what}.{name} was called")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        schema(self.db.q)
        for uid, name, role in ((OWNER, "the-owner", "admin"), (ADMIN, "admin-two", "admin"), (TEAM_ACCOUNT, "team-acct", "user")):
            self.db.q("INSERT INTO users (id, username, email, pw_hash, created, role) VALUES (?,?,?,?,?,?)", (uid, name, f"{name}@example.invalid", "x", time.time(), role))
        self.db.q("INSERT INTO mh_campaigns (id, user_id, netuid, mech, keys) VALUES (1, ?, ?, 0, ?)", (TEAM_ACCOUNT, NETUID, json.dumps([HOT, COLD, OTHER])))
        self.db.q("INSERT INTO mw_comps (id, campaign_id, number, name, status, paused) VALUES (?, 1, 28, 'Ridges', 'active', 1)", (WID,))
        orchestrator.init(self.db)
        self.env = mock.patch.dict(os.environ, {"AXOR_OWNERS": "the-owner"}); self.env.start()
        self.mx = missions.Missions(self.db, hub=Forbidden("hub"), wf=None, ia=None, mw=Forbidden("mw"))
        self.mx._ask = Forbidden("model")
        self.cm = mining_command.Command(self.work())  # the real ingest path, on a stand-in team owner check

    def work(self):
        db = self.db
        def own(me, wid):
            w = db.q("SELECT * FROM mw_comps WHERE id=?", (wid,), one=True)
            c = w and db.q("SELECT * FROM mh_campaigns WHERE id=? AND user_id=?", (w["campaign_id"], me["id"]), one=True)
            if not c: raise HTTPException(404, "There's no such workspace.")
            return w, c
        return types.SimpleNamespace(db=db, m=types.SimpleNamespace(hub=None), _own=own)

    def tearDown(self):
        self.env.stop()
        orchestrator._orc = None
        try: self.db.db.close()  # PX-R13: on Postgres the connection would otherwise live until the collector runs
        except Exception: pass  # noqa: BLE001
        self.dir.cleanup()

    def me(self, uid): return dict(self.db.q("SELECT id, username, role FROM users WHERE id=?", (uid,), one=True))

    def create(self, ms, keys=(HOT,), **kw):
        p = {"team": WID, "objective": "Reach the top 10 on SN62 competition 28", "measures": ms, "attested_keys": list(keys)} | kw
        return self.mx.create(self.me(OWNER), missions.MissionIn(goal="unused for persistent missions", persistent=missions.PersistentIn(**p)))["mission"]["id"]

    def sample(self, rows, age_h=1.0, mech=0, block=9_490_918):
        self.db.q("INSERT INTO mh_samples (netuid, mech, block, ts, head, stats, rows) VALUES (?,?,?,?,?,?,?)",
                  (NETUID, mech, block, time.time() - age_h * 3600, json.dumps({"owner": "5Owner", "block": block}), "{}",
                   zlib.compress(json.dumps(rows).encode())))

    def field(self, mine_em=0.05, mine_hk=HOT, mine_ck="5SomeCold"):
        """A field of 12 miners: ours ranks 7th by emission (and a validator and the owner who aren't ranked)."""
        rows = [row(i, f"5Rival{i}", f"5RivalCold{i}", em=1.0 - i * 0.05) for i in range(6)]
        rows.append(row(50, mine_hk, mine_ck, em=mine_em if mine_em is not None else 0.0))
        rows += [row(60 + i, f"5Low{i}", f"5LowCold{i}", em=0.001 * (5 - i)) for i in range(5)]
        rows += [row(90, "5Val", "5ValCold", em=0.0, validator=True), row(91, "5Owner", "5OwnerCold", em=0.9)]
        return rows

    def key(self, holder=None, at=None):
        """A live ingest key under the team's account; the token stays in the test."""
        out = self.cm.new_key(self.me(TEAM_ACCOUNT), mining_command.KeyIn(label="evaluator"))
        kid = max(k["id"] for k in out["keys"])
        if holder: self.cm.set_holder(self.me(OWNER), kid, mining_command.HolderIn(holder=holder))
        if at is not None: self.db.q("UPDATE mc_keys SET holder_since=? WHERE id=?", (at, kid))
        return kid, out["token"]

    def report(self, token, value, metric="rank", received_ago_h=0.0, ts=None):
        self.cm.ingest(token, {"competition": WID, "metrics": {metric: value}, **({"ts": ts} if ts else {})})
        rid = self.db.q("SELECT MAX(id) i FROM mc_metrics", one=True)["i"]
        if received_ago_h: self.db.q("UPDATE mc_metrics SET received=? WHERE id=?", (time.time() - received_ago_h * 3600, rid))
        return rid

    def ev(self, mid): return self.mx.evidence(self.me(OWNER), mid)

    def one(self, mid, i=0): return self.ev(mid)["measures"][i]


class Chain(Base):
    def test_01_attested_hotkey_in_a_fresh_sample_ranks_and_passes(self):
        self.sample(self.field())
        e = self.one(self.create([chain_measure()]))
        self.assertEqual((e["category"], e["status"], e["value"], e["pass"]), ("external", "valid", 7, True))
        self.assertEqual(e["evidence_ref"]["uid"], 50)
        self.assertEqual(e["evidence_ref"]["block"], 9_490_918)
        for f in ("source_identity", "provenance", "competition", "measured_at", "freshness_window_h", "evidence_ref"): self.assertTrue(e[f], f)

    def test_02_an_attested_coldkey_finds_its_hotkey(self):
        self.sample(self.field(mine_hk="5Unlisted", mine_ck=COLD))
        e = self.one(self.create([chain_measure()], keys=[COLD]))
        self.assertEqual((e["status"], e["value"]), ("valid", 7))

    def test_03_a_campaign_key_that_is_not_attested_is_unverifiable(self):
        self.sample(self.field())
        e = self.one(self.create([chain_measure()], keys=[]))
        self.assertEqual((e["status"], e["pass"]), ("unverifiable", None))

    def test_04_a_three_hour_old_sample_is_stale(self):
        self.sample(self.field(), age_h=3)
        e = self.one(self.create([chain_measure()]))
        self.assertEqual(e["status"], "stale")
        self.assertIn("paused", e["reason"])  # a paused campaign isn't scouted (R5 / K-33)

    def test_05_the_wrong_mechanism_is_missing(self):
        self.sample(self.field(), mech=1)
        e = self.one(self.create([chain_measure()]))
        self.assertEqual(e["status"], "missing")

    def test_attested_but_not_on_chain_is_missing_and_registered_reads_a_valid_no(self):
        self.sample(self.field(mine_hk="5NotOurs", mine_ck="5NotOursCold"))
        mid = self.create([chain_measure(), chain_measure("registered", "==", True)])
        rank, reg = self.ev(mid)["measures"]
        self.assertEqual(rank["status"], "missing")
        self.assertEqual((reg["status"], reg["value"], reg["pass"]), ("valid", False, False))
        self.assertEqual(self.ev(mid)["dimensions"]["competition"]["value"], "FAIL")  # valid evidence that it fails

    def test_the_best_of_several_attested_uids_counts(self):
        rows = self.field()
        rows.append(row(70, OTHER, "5X", em=0.97))  # a second attested UID ranks 2nd
        self.sample(rows)
        e = self.one(self.create([chain_measure()], keys=[HOT, OTHER]))
        self.assertEqual(e["value"], 2)
        self.assertEqual(len(e["also"]), 1)


class Ingest(Base):
    def test_06_an_independent_evaluators_fresh_report_is_valid_external(self):
        kid, tok = self.key("independent_evaluator", at=time.time() - 3 * 3600)  # designated 3 h ago
        self.report(tok, 7, received_ago_h=2)                                      # received 2 h ago: after it
        mid = self.create([ingest_measure()])
        e = self.one(mid)
        self.assertEqual((e["category"], e["status"], e["value"], e["pass"]), ("external", "valid", 7, True))
        self.assertEqual(e["evidence_ref"]["key_id"], kid)
        self.assertNotIn(tok[:10], json.dumps(self.ev(mid)))  # never a token fragment

    def test_07_a_team_key_is_self_reported(self):
        _, tok = self.key("team")
        self.report(tok, 3)
        mid = self.create([ingest_measure()])
        e = self.one(mid)
        self.assertEqual((e["category"], e["status"], e["pass"]), ("self_reported", "self_reported", None))
        self.assertEqual(self.ev(mid)["dimensions"]["competition"]["value"], "UNKNOWN")

    def test_undesignated_keys_are_self_reported(self):
        _, tok = self.key()
        self.report(tok, 3)
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "self_reported")

    def test_08_a_report_without_a_key_id_is_unverifiable(self):
        self.db.q("INSERT INTO mc_metrics (user_id, comp_id, ts, metric, value, source) VALUES (?,?,?,?,?,?)", (TEAM_ACCOUNT, WID, time.time(), "rank", 3, "evaluator"))
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "unverifiable")

    def test_09_a_manual_entry_is_self_reported(self):
        self.cm.add_metrics(self.me(TEAM_ACCOUNT), mining_command.MetricIn(comp_id=WID, metrics={"rank": 2}))
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "self_reported")

    def test_10_and_18_a_revoked_key_never_counts(self):
        kid, tok = self.key("independent_evaluator")
        self.report(tok, 7)
        self.cm.revoke_key(self.me(TEAM_ACCOUNT), kid)
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "unverifiable")
        with self.assertRaises(HTTPException) as e: self.cm.set_holder(self.me(OWNER), kid, mining_command.HolderIn(holder="independent_evaluator"))
        self.assertEqual(e.exception.status_code, 409)

    def test_16_freshness_uses_the_receipt_time_not_the_senders_claim(self):
        _, tok = self.key("independent_evaluator", at=time.time() - 40 * 3600)
        self.report(tok, 7, received_ago_h=30, ts=time.time())
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "stale")

    def test_an_old_measurement_sent_now_is_stale(self):
        """The sender can make a report look older, never fresher: age runs from the older of its sent and received times."""
        _, tok = self.key("independent_evaluator", at=time.time() - 3600)
        self.report(tok, 7, ts=time.time() - 80 * 86400)  # measured 80 days ago, received now
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "stale")

    def test_17_a_designation_never_upgrades_earlier_reports(self):
        kid, tok = self.key()
        self.report(tok, 7, received_ago_h=1)
        self.cm.set_holder(self.me(OWNER), kid, mining_command.HolderIn(holder="independent_evaluator"))
        mid = self.create([ingest_measure()])
        self.assertEqual(self.one(mid)["status"], "self_reported")
        self.report(tok, 7)  # after the designation: it counts
        self.assertEqual(self.one(mid)["status"], "valid")

    def test_self_reported_reports_never_hide_an_independent_failure(self):
        _, ind = self.key("independent_evaluator", at=time.time() - 3 * 3600)
        self.report(ind, 40, received_ago_h=2)                   # the evaluator: rank 40, fails ≤ 10
        _, team = self.key("team")
        for _ in range(210): self.report(team, 1)                # many newer self-reported "rank 1" reports
        mid = self.create([ingest_measure()])
        e = self.one(mid)
        self.assertEqual((e["status"], e["value"], e["pass"]), ("valid", 40, False))
        self.assertEqual(self.ev(mid)["dimensions"]["competition"]["value"], "FAIL")

    def test_designating_a_key_again_keeps_its_history(self):
        kid, tok = self.key("independent_evaluator", at=time.time() - 3 * 3600)
        self.report(tok, 7, received_ago_h=1)
        since = self.db.q("SELECT holder_since FROM mc_keys WHERE id=?", (kid,), one=True)["holder_since"]
        self.cm.set_holder(self.me(OWNER), kid, mining_command.HolderIn(holder="independent_evaluator"))  # the same holder again
        self.assertEqual(self.db.q("SELECT holder_since FROM mc_keys WHERE id=?", (kid,), one=True)["holder_since"], since)
        self.assertEqual(self.one(self.create([ingest_measure()]))["status"], "valid")

    def test_two_independent_evaluators_that_disagree_conflict(self):
        _, a = self.key("independent_evaluator")
        _, b = self.key("independent_evaluator")
        self.report(a, 7); self.report(b, 14)
        e = self.one(self.create([ingest_measure()]))
        self.assertEqual((e["status"], e["pass"]), ("conflicting", None))
        self.assertEqual(len(e["also"]), 1)  # both values kept

    def test_a_newer_report_from_the_same_key_supersedes_the_older(self):
        _, a = self.key("independent_evaluator")
        r1 = self.report(a, 14, received_ago_h=1); r2 = self.report(a, 7)
        e = self.one(self.create([ingest_measure()]))
        self.assertEqual((e["status"], e["value"], e["evidence_ref"]["metric_row"]), ("valid", 7, r2))
        self.assertNotEqual(r1, r2)


class Basis(Base):
    """K-19 / K-20: what external evidence rests on is shown, so an Owner designation is never mistaken for independent proof."""
    def test_chain_evidence_names_the_attestation_it_rests_on(self):
        self.sample(self.field())
        mid = self.create([chain_measure()])
        ev = self.ev(mid)
        b = ev["measures"][0]["basis"]
        self.assertEqual((b["kind"], b["key"], b["attested_by"]), ("owner_attested_key", HOT, "the-owner"))
        self.assertIn("not cryptographically proven", b["note"])
        self.assertEqual(ev["dimensions"]["competition"]["rests_on"], ["owner_attested_key"])
        self.assertIn("doesn't prove", ev["trust_note"])

    def test_ingest_evidence_names_the_designation_and_its_limit(self):
        kid, tok = self.key("independent_evaluator", at=time.time() - 3600)
        self.report(tok, 7)
        b = self.one(self.create([ingest_measure()]))["basis"]
        self.assertEqual((b["kind"], b["key_id"], b["designated_by"]), ("owner_designated_evaluator", kid, "the-owner"))
        self.assertIn("can't verify", b["note"])

    def test_self_reported_and_bench_say_so(self):
        _, tok = self.key("team")
        self.report(tok, 3)
        ing, bench = self.ev(self.create([ingest_measure(), bench_measure()]))["measures"]
        self.assertEqual((ing["basis"]["kind"], ing["basis"]["designated_by"]), ("self_reported", None))
        self.assertEqual(bench["basis"]["kind"], "internal_measured")  # G5-4 V4.4: was "unverifiable_until_g5_4"
        self.assertIn("never competition", bench["basis"]["note"])


class Conflicts(Base):
    def test_11_chain_and_an_evaluator_that_disagree_are_both_unknown(self):
        self.sample(self.field())                       # chain: rank 7, passes ≤ 10
        _, tok = self.key("independent_evaluator")
        self.report(tok, 14)                            # evaluator: rank 14, fails
        mid = self.create([chain_measure(), ingest_measure()])
        ev = self.ev(mid)
        self.assertEqual([e["status"] for e in ev["measures"]], ["conflicting", "conflicting"])
        self.assertEqual(ev["dimensions"]["competition"]["value"], "UNKNOWN")
        self.assertEqual({a["value"] for e in ev["measures"] for a in e["also"]}, {7, 14})

    def test_tolerance_turns_a_small_difference_into_no_conflict_and_a_large_one_into_a_conflict(self):
        self.sample(self.field())
        _, tok = self.key("independent_evaluator")
        self.report(tok, 8)
        mid = self.create([chain_measure(tolerance=2), ingest_measure(tolerance=2)])
        self.assertEqual([e["status"] for e in self.ev(mid)["measures"]], ["valid", "valid"])
        self.assertEqual(self.ev(mid)["dimensions"]["competition"]["value"], "PASS")
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(measures=[chain_measure(tolerance=0.5), ingest_measure(tolerance=0.5)]))
        self.assertEqual([e["status"] for e in self.ev(mid)["measures"]], ["conflicting", "conflicting"])


class Dimensions(Base):
    def test_13_and_23_a_benchmark_is_unverifiable_and_never_decides_the_competition(self):
        mid = self.create([chain_measure(), bench_measure()], keys=[])
        # G5-4 V4.4: a comparable row on the frozen release, filed before evidence references existed (no evidence_ref)
        from app import mining_release
        mining_release.Release(types.SimpleNamespace(db=self.db))
        self.db.q("INSERT INTO mw_release (id, comp_id, version, commit_ref, suite, suite_tasks, suite_hash, repeats, frozen, current) VALUES (1, ?, 1, 'abc1234', 's', 3, 'h', 1, ?, 1)",
                  (WID, time.time()))
        self.db.q("INSERT INTO mw_bench (comp_id, release_id, candidate, suite, suite_tasks, suite_hash, repeats, score, comparable, ts) VALUES (?, 1, 'abc1234', 's', 3, 'h', 1, 0.9, 1, ?)",
                  (WID, time.time()))
        ev = self.ev(mid)
        self.assertEqual(ev["measures"][1]["status"], "unverifiable")
        self.assertIn("V4.4", ev["measures"][1]["reason"])
        self.assertEqual((ev["dimensions"]["competition"]["value"], ev["dimensions"]["technical"]["value"]), ("UNKNOWN", "UNKNOWN"))

    def test_23_a_self_reported_pass_is_never_a_competition_pass(self):
        _, tok = self.key("team")
        self.report(tok, 1)
        self.assertEqual(self.ev(self.create([ingest_measure()]))["dimensions"]["competition"]["value"], "UNKNOWN")

    def test_competition_pass_needs_every_required_external_measure_valid_and_passing(self):
        self.sample(self.field())
        mid = self.create([chain_measure(), chain_measure("registered", "==", True)])
        self.assertEqual(self.ev(mid)["dimensions"]["competition"]["value"], "PASS")
        self.assertEqual(self.ev(mid)["dimensions"]["technical"]["value"], "n/a")

    def test_an_optional_measure_never_blocks_the_outcome(self):
        self.sample(self.field())
        mid = self.create([chain_measure(), ingest_measure(required=False)])
        self.assertEqual(self.ev(mid)["dimensions"]["competition"]["value"], "PASS")


class Configuration(Base):
    def test_19_an_unknown_metric_is_refused_and_a_stored_one_reads_unknown(self):
        for bad in (chain_measure("score"), ingest_measure("emission"), bench_measure() | {"metric": "rank"}):
            with self.assertRaises(HTTPException) as e: self.create([chain_measure(), bad] if bad["tier"] != "external" else [bad])
            self.assertEqual(e.exception.status_code, 400)
        mid = self.create([chain_measure()])
        m = self.mx._m(mid); u = m["understanding"]
        u["measures"][0]["metric"] = "retired_metric"  # a measure stored before its metric left the vocabulary
        self.mx._set(mid, understanding=u)
        e = self.one(mid)
        self.assertEqual(e["status"], "unverifiable")
        self.assertIn("can't measure", e["reason"])

    def test_yes_no_measures_need_a_yes_no_target(self):
        with self.assertRaises(HTTPException): self.create([chain_measure("registered", ">=", 1)])
        with self.assertRaises(HTTPException): self.create([chain_measure("rank", "==", True)])

    def test_24_deadline_and_informational_budget_are_versioned_and_never_a_limit(self):
        dl = time.time() + 30 * 86400
        mid = self.create([chain_measure()], deadline=dl, budget_info=50.0)
        m = self.mx._m(mid)
        self.assertEqual((m["deadline"], m["budget"], m["understanding"]["budget_info"]), (dl, 0, 50.0))
        v1 = m["understanding"]["measures_version"]["version"]
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(budget_info=80.0))
        v2 = self.mx._m(mid)["understanding"]["measures_version"]["version"]
        self.assertGreater(v2, v1)
        if self.mx._has_t("ac_limits"): self.assertEqual(self.db.q("SELECT COUNT(*) n FROM ac_limits", one=True)["n"], 0)
        with self.assertRaises(HTTPException): self.create([chain_measure()], deadline=time.time() - 10)

    def test_27_returning_to_an_earlier_set_reuses_its_version(self):
        mid = self.create([chain_measure()])
        v1 = self.mx._m(mid)["understanding"]["measures_version"]
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(measures=[chain_measure(target=5)]))
        self.mx.patch(self.me(OWNER), mid, missions.PatchIn(measures=[chain_measure()]))
        self.assertEqual(self.mx._m(mid)["understanding"]["measures_version"], v1)

    def test_one_shot_missions_refuse_an_informational_budget(self):
        mid = self.db.q("INSERT INTO mx_missions (user_id, title, goal, status, stage, created, updated) VALUES (?,?,?,?,?,?,?) RETURNING id",
                        (OWNER, "one-shot", "a one-shot mission goal", "delivered", "learn", time.time(), time.time()), one=True)["id"]
        with self.assertRaises(HTTPException) as e: self.mx.patch(self.me(OWNER), mid, missions.PatchIn(budget_info=5.0))
        self.assertEqual(e.exception.status_code, 400)


class Permissions(Base):
    def test_21_only_the_owner_designates_and_it_is_audited(self):
        kid, _ = self.key()
        self.mx.set_delegates(self.me(OWNER), missions.DelegatesIn(user_ids=[ADMIN]))
        for uid in (ADMIN, TEAM_ACCOUNT):
            with self.assertRaises(HTTPException) as e: self.cm.set_holder(self.me(uid), kid, mining_command.HolderIn(holder="independent_evaluator"))
            self.assertEqual(e.exception.status_code, 403)
        self.cm.set_holder(self.me(OWNER), kid, mining_command.HolderIn(holder="independent_evaluator"))
        a = self.db.q("SELECT actor, action, detail FROM audit WHERE action='mission.evidence_key'", one=True)
        self.assertEqual((a["actor"], a["action"]), ("the-owner", "mission.evidence_key"))
        self.assertIn("independent_evaluator", a["detail"])
        listed = {k["id"]: k for k in self.cm.keys(self.me(TEAM_ACCOUNT))["keys"]}
        self.assertEqual(listed[kid]["holder"], "independent_evaluator")

    def test_evidence_is_read_by_the_teams_account_and_the_owner_only(self):
        mid = self.create([chain_measure()])
        self.assertEqual(self.mx.evidence(self.me(TEAM_ACCOUNT), mid)["mission"], mid)
        with self.assertRaises(HTTPException): self.mx.evidence(self.me(ADMIN), mid)  # not delegated

    def test_one_shot_missions_have_no_evidence(self):
        mid = self.db.q("INSERT INTO mx_missions (user_id, title, goal, status, stage, created, updated) VALUES (?,?,?,?,?,?,?) RETURNING id",
                        (OWNER, "one-shot", "a one-shot mission goal", "delivered", "learn", time.time(), time.time()), one=True)["id"]
        with self.assertRaises(HTTPException) as e: self.mx.evidence(self.me(OWNER), mid)
        self.assertEqual(e.exception.status_code, 409)


class Regression(Base):
    def test_20_ingest_behaves_as_before_plus_the_key_and_receipt_time(self):
        kid, tok = self.key()
        out = self.cm.ingest(tok, {"competition": WID, "metrics": {"rank": 7, "score": 0.5}, "run": "r1"})
        self.assertEqual(out, {"ok": True, "stored": 2, "health": False})
        rows = self.db.q("SELECT user_id, comp_id, metric, value, source, run, key_id, received FROM mc_metrics ORDER BY id")
        self.assertEqual([(r["user_id"], r["comp_id"], r["metric"], r["value"], r["source"], r["run"], r["key_id"]) for r in rows],
                         [(TEAM_ACCOUNT, WID, "rank", 7, "evaluator", "r1", kid), (TEAM_ACCOUNT, WID, "score", 0.5, "evaluator", "r1", kid)])
        self.assertTrue(all(abs(r["received"] - time.time()) < 60 for r in rows))
        for bad in ("", "mcx_nope"):
            with self.assertRaises(HTTPException) as e: self.cm.ingest(bad, {"competition": WID, "metrics": {"rank": 1}})
            self.assertEqual(e.exception.status_code, 401)
        with self.assertRaises(HTTPException) as e: self.cm.ingest(tok, {"competition": WID, "metrics": {"nonsense": 1}})
        self.assertEqual(e.exception.status_code, 400)

    def test_22_and_26_reading_evidence_writes_nothing_and_calls_nothing(self):
        self.sample(self.field())
        _, tok = self.key("independent_evaluator")
        self.report(tok, 7)
        mid = self.create([chain_measure(), ingest_measure(), bench_measure()])
        tables = [r["name"] for r in self.db.q("SELECT name FROM sqlite_master WHERE type='table'")]
        snap = lambda: {t: self.db.q(f"SELECT * FROM {t}") for t in tables if t not in ("sessions",)}
        before = snap()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            for _ in range(3): self.ev(mid)
            self.mx.state(self.me(OWNER), mid)
        self.assertEqual(snap(), before)

    def test_25_the_mission_page_carries_the_evidence(self):
        self.sample(self.field())
        mid = self.create([chain_measure()])
        st = self.mx.state(self.me(OWNER), mid)["mission"]
        self.assertEqual(st["evidence"]["dimensions"]["competition"]["value"], "PASS")
        self.assertEqual(st["persistent"]["budget_info"], None)


if __name__ == "__main__":
    unittest.main()
