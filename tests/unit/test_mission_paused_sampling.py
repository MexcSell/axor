"""D-004 D4.2b (K-33, decided 2026-11-13): chain samples for a paused campaign's subnet while a persistent mission watches its team.

Sampling only: mining.sample() writes mh_samples and mh_points and nothing else. No campaign change, event, agent state, Sentinel,
cycle, model call or task change. Off unless the Owner turns it on. A subnet is sampled only while every team board on it whose
campaign isn't live is paused, so a fresh snapshot can't release a readiness-held task (G5-2.2, mining_work._kick).

The real campaign scheduler (mining.Mining) and the real Mission Control run here; only the chain read (_read) is a stand-in.
The Sentinel, cycles, _scout and the model hub are stand-ins that fail if called. The cases follow
D4_2B_PAUSED_SAMPLING_PROPOSAL.md §6 (P paused, A active, M missing, S stale, G permissions)."""
import json, os, tempfile, time, unittest, zlib
from unittest import mock

from fastapi import HTTPException

from app import mining, missions, orchestrator
from app.auth import AuthDB

OWNER, ADMIN, TEAM = 11, 12, 14
NET, OTHER_NET = 62, 61
HOT = "5Hot"


class Forbidden:
    def __init__(self, what): self.what = what
    def __call__(self, *a, **k): raise AssertionError(f"{self.what} was called")
    def __getattr__(self, name): raise AssertionError(f"{self.what}.{name} was called")


class Now:  # runs submitted work at once, so a tick's effects are visible when it returns
    def submit(self, fn, *a, **k): fn(*a, **k)


def head(block):
    return {"block": block, "ts": time.time(), "num_uids": 3, "max_uids": 256, "burn": 0.1, "owner": "5Owner", "tempo": 360}


def rows():
    r = lambda u, hk, em: {"u": u, "hk": hk, "ck": hk + "Cold", "em": em, "inc": em, "tr": .5, "cs": .5, "ps": .1, "st": 10.0, "ax": 1,
                           "vp": 0, "div": 0, "im": 0, "rb": 1, "cm": None, "cb": None}
    return [r(0, "5Rival", 0.6), r(1, HOT, 0.3), r(2, "5Low", 0.1)]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.m = mining.Mining(self.db, self.dir.name)  # its own tables: mh_campaigns, mh_samples, mh_points, mh_events, ...
        self.db.q("""CREATE TABLE IF NOT EXISTS mw_comps (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, number INTEGER, name TEXT,
                     status TEXT, paused INTEGER DEFAULT 0, autopilot INTEGER DEFAULT 0, goal TEXT, budget INTEGER, last_plan REAL)""")
        self.db.q("CREATE TABLE IF NOT EXISTS mw_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, status TEXT, hold TEXT, mission TEXT, title TEXT)")
        for uid, name, role in ((OWNER, "the-owner", "admin"), (ADMIN, "admin-two", "admin"), (TEAM, "team-acct", "user")):
            self.db.q("INSERT INTO users (id, username, email, pw_hash, created, role) VALUES (?,?,?,?,?,?)",
                      (uid, name, f"{name}@example.invalid", "x", time.time(), role))
        self.camp(1, NET, "paused"); self.team(22, 1, paused=1)
        orchestrator.init(self.db); self.addCleanup(setattr, orchestrator, "_orc", None)
        env = mock.patch.dict(os.environ, {"AXOR_OWNERS": "the-owner"}); env.start(); self.addCleanup(env.stop)
        self.mx = missions.Missions(self.db, hub=Forbidden("hub"), wf=None, ia=None, mw=Forbidden("mw"))
        self.m.watch(self.mx._paused_watch)  # what missions.build does with the real team module
        self.reads = []
        self.m._read = lambda n: (self.reads.append(n), {0: (head(9_500_000 + len(self.reads)), rows())})[1]
        self.m.samplers = Now()
        self.m._sentinel, self.m.cycle, self.m._submit = Forbidden("sentinel"), Forbidden("cycle"), Forbidden("cycle submit")
        self.scouted = []
        def scout(netuid, cids, why="schedule"):  # the live path, recorded (its own behaviour is unchanged by D4.2b)
            self.scouted.append((netuid, tuple(cids))); self.m.sampling.discard(netuid)
        self.m._scout = scout

    def camp(self, cid, net, status, keys=(HOT,)):
        self.db.q("INSERT INTO mh_campaigns (id, user_id, netuid, status, settings, keys, created, updated, mech) VALUES (?,?,?,?,?,?,?,?,0)",
                  (cid, TEAM, net, status, "{}", json.dumps(list(keys)), 1.0, 1.0))

    def team(self, wid, cid, paused):
        self.db.q("INSERT INTO mw_comps (id, campaign_id, number, name, status, paused) VALUES (?,?,?,?, 'active', ?)", (wid, cid, wid, f"team {wid}", paused))

    def me(self, uid): return dict(self.db.q("SELECT id, username, role FROM users WHERE id=?", (uid,), one=True))

    def mission(self, wid=22, chain=True, **kw):
        ms = ([{"id": "chain_rank", "text": "Rank", "tier": "external", "source": "chain", "metric": "rank", "op": "<=", "target": 10} | kw]
              if chain else [{"id": "eval_rank", "text": "Evaluator rank", "tier": "external", "source": "ingest", "metric": "rank", "op": "<=", "target": 10}])
        p = missions.PersistentIn(team=wid, objective="Reach the top 10 (paused sampling test)", measures=ms, attested_keys=[HOT])
        return self.mx.create(self.me(OWNER), missions.MissionIn(goal="unused for persistent missions", persistent=p))["mission"]["id"]

    def on(self, v=True): return self.mx.set_sample_paused(self.me(OWNER), missions.SamplePausedIn(on=v))

    def old_sample(self, net=NET, age_h=3.0):
        self.db.q("INSERT INTO mh_samples (netuid, mech, block, ts, head, stats, rows) VALUES (?,0,1,?,?, '{}', ?)",
                  (net, time.time() - age_h * 3600, json.dumps(head(1)), zlib.compress(json.dumps([]).encode())))

    def digest(self):
        out = {}
        for (t,) in [tuple(r.values()) for r in self.db.q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]:
            if t in ("mh_samples", "mh_points") or t.startswith("sqlite_"): continue
            out[t] = json.dumps(self.db.q(f"SELECT * FROM {t}"), sort_keys=True, default=str)
        return out

    def samples(self, net=NET): return self.db.q("SELECT COUNT(*) n FROM mh_samples WHERE netuid=?", (net,), one=True)["n"]


class Paused(Base):
    def test_p1_a_watched_paused_subnet_is_sampled_and_nothing_else_changes(self):
        mid = self.mission(); self.on(); self.old_sample()
        before, n0 = self.digest(), self.samples()
        self.m.tick()
        self.assertEqual(self.reads, [NET])
        self.assertEqual(self.samples(), n0 + 1)
        self.assertGreater(self.db.q("SELECT COUNT(*) n FROM mh_points WHERE netuid=?", (NET,), one=True)["n"], 0)
        self.assertEqual(self.digest(), before)   # every other table: campaigns (status, last_cycle, updated), events, agent state, tasks, missions...
        self.assertEqual(self.db.q("SELECT status FROM mh_campaigns WHERE id=1", one=True)["status"], "paused")
        self.assertEqual(self.scouted, [])
        self.assertNotIn(NET, self.m.sampling)

    def test_p1b_an_unpaused_board_on_the_subnet_stops_sampling(self):
        # its runner (_kick) releases readiness holds on unpaused boards: a fresh snapshot must not be what lets a held task start
        self.mission(); self.on(); self.old_sample()
        self.db.q("UPDATE mw_comps SET paused=0 WHERE id=22")
        self.db.q("INSERT INTO mw_tasks (comp_id, status, hold) VALUES (22, 'todo', 'readiness')")
        self.m.tick()
        self.assertEqual(self.reads, [])
        self.db.q("UPDATE mw_comps SET paused=1 WHERE id=22")
        self.camp(2, NET, "paused"); self.team(23, 2, paused=0)  # another non-live team on the same subnet, its board running
        self.m.tick()
        self.assertEqual(self.reads, [])
        self.db.q("UPDATE mw_comps SET paused=1 WHERE id=23")
        before = self.digest()
        self.m.tick()
        self.assertEqual(self.reads, [NET])
        self.assertEqual(self.digest(), before)  # the held task is still held

    def test_p2_the_mission_reads_the_fresh_sample_with_the_frozen_reader(self):
        mid = self.mission(); self.on(); self.old_sample(age_h=30)
        stale = self.mx._evidence(self.mx._m(mid))["measures"][0]
        self.assertEqual(stale["status"], "stale")
        self.m.tick()
        fresh = self.mx._evidence(self.mx._m(mid))["measures"][0]
        self.assertEqual((fresh["status"], fresh["value"]), ("valid", 2))  # HOT ranks 2nd by emission in the stand-in sample

    def test_p3_off_by_default_and_off_again(self):
        self.mission(); self.old_sample()
        self.m.tick()
        self.assertEqual(self.reads, [])
        self.on(); self.on(False)
        self.m.tick()
        self.assertEqual(self.reads, [])

    def test_p4_paused_evaluation_or_an_ended_mission_or_no_chain_measure_means_no_sample(self):
        mid = self.mission(); self.on(); self.old_sample()
        self.mx.pause(self.me(OWNER), mid)
        self.m.tick(); self.assertEqual(self.reads, [])
        self.mx.resume(self.me(OWNER), mid)
        self.mx.cancel(self.me(OWNER), mid)
        self.m.tick(); self.assertEqual(self.reads, [])
        self.mission(chain=False)
        self.m.tick(); self.assertEqual(self.reads, [])

    def test_p5_two_teams_on_one_subnet_one_sample_at_the_shortest_interval(self):
        self.camp(2, NET, "paused"); self.team(23, 2, paused=1)
        self.mission(22, max_age_h=4); self.mission(23, max_age_h=0.5); self.on()
        self.assertEqual(self.mx._paused_watch(), [(NET, 900.0)])  # min(4 h, 0.5 h) / 2, clamped to 15–60 min
        self.old_sample(age_h=0.3)  # 18 min old: due at 15 min
        self.m.tick()
        self.assertEqual(self.reads, [NET])


class Active(Base):
    def test_a1_live_campaigns_tick_as_before_with_the_switch_on_or_off(self):
        self.db.q("UPDATE mh_campaigns SET status='live', last_cycle=? WHERE id=1", (time.time(),))
        self.mission()
        for v in (False, True):
            self.scouted.clear(); self.reads.clear(); self.on(v)
            self.m.tick()
            self.assertEqual(self.scouted, [(NET, (1,))])  # the live path: one scout of the subnet for its campaign
            self.assertEqual(self.reads, [])             # nothing from D4.2b: a live campaign covers its subnet

    def test_a2_a_live_campaign_on_the_subnet_covers_it(self):
        self.camp(2, NET, "live"); self.team(23, 2, paused=1)
        self.db.q("UPDATE mh_campaigns SET last_cycle=? WHERE id=2", (time.time(),))
        self.mission(); self.on(); self.old_sample()
        self.m.tick()
        self.assertEqual(self.scouted, [(NET, (2,))])
        self.assertEqual(self.reads, [])

    def test_a3_one_sampler_per_subnet(self):
        self.mission(); self.on(); self.old_sample()
        self.m.sampling.add(NET)  # a scout in flight on the subnet
        self.m.tick()
        self.assertEqual(self.reads, [])
        self.m.sampling.discard(NET)
        self.m.tick()
        self.assertEqual(self.reads, [NET])


class Missing(Base):
    def test_m1_no_campaign_or_no_team_row(self):
        self.mission(); self.on(); self.old_sample()
        self.db.q("DELETE FROM mh_campaigns WHERE id=1")
        self.m.tick(); self.assertEqual(self.reads, [])
        self.assertEqual(self.mx._paused_watch(), [])

    def test_m2_a_subnet_gone_from_chain_backs_off_and_writes_nothing(self):
        self.mission(); self.on(); self.old_sample()
        calls = []
        def gone(n): calls.append(n); raise LookupError(f"SN{n} doesn't exist on chain.")
        self.m._read = gone
        before, n0 = self.digest(), self.samples()
        for _ in range(3): self.m.tick()
        self.assertEqual(calls, [NET])  # once, then the backoff
        self.assertEqual((self.digest(), self.samples()), (before, n0))
        self.assertIn(NET, self.m.failed)
        self.assertNotIn(NET, self.m.sampling)
        self.m.failed[NET] = time.time() - mining.Mining.WATCH_BACKOFF - 1
        self.m.tick()
        self.assertEqual(calls, [NET, NET])

    def test_m3_a_fresh_database_without_mission_tables(self):
        db = AuthDB(os.path.join(self.dir.name, "b.db"))
        m = mining.Mining(db, self.dir.name)
        mx = missions.Missions(db, hub=Forbidden("hub"), wf=None, ia=None, mw=Forbidden("mw"))
        m.watch(mx._paused_watch); m._read = Forbidden("chain read"); m.samplers = Now()
        db.setting(missions.SAMPLE_PAUSED_KEY, v="1")
        with mock.patch.object(mining.log, "exception") as logged:
            m.tick()  # no mw_comps table: the watcher fails, is logged, and the live schedule goes on
        logged.assert_called_once()

    def test_m4_a_watcher_error_never_stops_the_live_schedule(self):
        self.db.q("UPDATE mh_campaigns SET status='live', last_cycle=? WHERE id=1", (time.time(),))
        self.m.watch(Forbidden("broken watcher"))
        self.m.tick()
        self.assertEqual(self.scouted, [(NET, (1,))])


class Stale(Base):
    def test_s1_s2_sampled_only_when_older_than_the_interval(self):
        self.mission(); self.on()
        self.old_sample(age_h=0.5)  # 30 min: the default window 2 h → every 60 min
        self.m.tick(); self.assertEqual(self.reads, [])
        self.db.q("UPDATE mh_samples SET ts=? WHERE netuid=?", (time.time() - 3700, NET))
        self.m.tick(); self.assertEqual(self.reads, [NET])
        self.m.tick(); self.assertEqual(self.reads, [NET])  # the new sample is fresh

    def test_s3_repeated_failures_never_make_the_evidence_valid(self):
        mid = self.mission(); self.on(); self.old_sample(age_h=30)
        def down(n): raise ConnectionError("no route to the chain")
        self.m._read = down
        for _ in range(3):
            self.m.failed.pop(NET, None)
            self.m.tick()
        e = self.mx._evidence(self.mx._m(mid))["measures"][0]
        self.assertEqual(e["status"], "stale")

    def test_s4_the_interval_follows_the_window_within_15_to_60_minutes(self):
        self.mission(max_age_h=6); self.on()
        self.assertEqual(self.mx._paused_watch(), [(NET, 3600.0)])
        self.db.q("UPDATE mx_missions SET status='cancelled', persistent_team=NULL")
        self.mission(max_age_h=0.2)
        self.assertEqual(self.mx._paused_watch(), [(NET, 900.0)])


class Permissions(Base):
    def test_g1_only_the_owner_sets_the_switch(self):
        self.db.setting(missions.DELEGATES_KEY, v=json.dumps([ADMIN]))
        for uid in (ADMIN, TEAM):
            with self.assertRaises(HTTPException) as e: self.mx.set_sample_paused(self.me(uid), missions.SamplePausedIn(on=True))
            self.assertEqual(e.exception.status_code, 403)
        self.assertFalse(self.mx.sample_paused_on())

    def test_g2_audited_once_and_a_repeat_is_a_no_op(self):
        self.on(); self.on()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM audit WHERE action='mission.sample_paused'", one=True)["n"], 1)
        self.on(False)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM audit WHERE action='mission.sample_paused'", one=True)["n"], 2)

    def test_the_mission_view_shows_the_switch(self):
        mid = self.mission(); self.on()
        self.assertTrue(self.mx._card(self.mx._m(mid))["persistent"]["sample_paused"])
        self.on(False)
        self.assertFalse(self.mx._card(self.mx._m(mid))["persistent"]["sample_paused"])


if __name__ == "__main__":
    unittest.main()
