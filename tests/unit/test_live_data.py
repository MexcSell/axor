"""Live-data requirements (D-024): a separate type from sandbox internet. live_data:web[/host] is read by AXoR's web_read on the
server; live_data:chain comes from AXoR's chain snapshots. Each kind has its retrieval method, freshness window and verification;
readiness verifies it with evidence, never by giving the sandbox internet: web by a live server-side read now (the retrieval path,
not a past fetch), chain by the subnet's latest snapshot (never a brief), Milestone 2 (2026-11-12)."""
import json, os, sys, tempfile, time, types, unittest
from unittest import mock

from app import mission_ops as mo, orchestrator as o, task_lifecycle as tl
from app.auth import AuthDB

sys.path.insert(0, os.path.dirname(__file__))
from test_mission_ref import ME  # noqa: E402


def caps(text): return {(n["cap"], n["value"]) for n in tl.infer_needs(text)}


class Spec(unittest.TestCase):
    def test_sources_carry_method_freshness_and_verification(self):
        w, c = tl.live_spec("web/docs.ridges.ai"), tl.live_spec("chain")
        self.assertEqual((w["kind"], w["target"], c["kind"]), ("web", "docs.ridges.ai", "chain"))
        for sp in (w, c): self.assertTrue(sp["method"] and sp["fresh_h"] and sp["verify"])
        self.assertIn("server", w["method"]); self.assertIsNone(tl.live_spec("ftp"))

    def test_declarations_are_checked(self):
        self.assertEqual(tl.parse_needs(["live_data:web/taostats.io", "live_data:chain", "internet"]), ["live_data:web/taostats.io", "live_data:chain", "internet"])
        for bad in (["live_data"], ["live_data:ftp"]):
            with self.assertRaises(ValueError): tl.parse_needs(bad)


class Inference(unittest.TestCase):
    def test_web_reads_name_their_host_and_are_not_sandbox_internet(self):
        got = caps("Read docs.ridges.ai (web_read) and record the upload rules")
        self.assertIn(("live_data", "web/docs.ridges.ai"), got)
        self.assertNotIn(("internet", None), got)                          # AXoR reads it; the sandbox needs no internet
        self.assertIn(("live_data", "web/theredteam.io"), caps("Re-read https://www.theredteam.io/dashboard/miner?q=51 list L12"))
        self.assertIn(("live_data", "web/taostats.io"), caps("Get the deregistration list from taostats with web_read"))
        self.assertIn(("internet", None), caps("pip install -r requirements.txt in the sandbox"))  # sandbox egress stays its own type

    def test_chain_reads(self):
        for text in ("Scan the first snapshot after 17:30 UTC", "Use operators/leaderboard to check the coldkey",
                     "Append a row from the briefing at each snapshot", "Sum validator stake per weight source"):
            self.assertIn(("live_data", "chain"), caps(text), text)
        self.assertEqual({v for c, v in caps("Query Uids[netuid, hk] on all netuids") if c == "live_data"}, {"chain/query"})  # Milestone 4: storage, not snapshots

    def test_names_and_slot_admin_are_not_reads(self):
        self.assertNotIn("live_data", {c for c, _ in caps("161 (WildSage) and 217 (1T1B.AI) are byte-identical")})
        self.assertEqual({c for c, _ in caps("Rename or re-save misnamed web slots\nthe taostats weights slot points to taostats.io")} & {"live_data"}, set())
        self.assertEqual(caps("Write the agent.py loop and test it on config.py"), set())


class Probe(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        db = self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        db.q("CREATE TABLE mh_campaigns (id INTEGER PRIMARY KEY, netuid INTEGER)"); db.q("INSERT INTO mh_campaigns VALUES (2, 61)")
        db.q("CREATE TABLE mh_samples (id INTEGER PRIMARY KEY, netuid INTEGER, block INTEGER, ts REAL)")
        db.q("CREATE TABLE mh_briefs (id INTEGER PRIMARY KEY, campaign_id INTEGER, ts REAL)")
        db.q("CREATE TABLE mw_web (id INTEGER PRIMARY KEY, comp_id INTEGER, url TEXT, last_at REAL, last_status TEXT, on_ INTEGER DEFAULT 1)")
        self.ch = types.SimpleNamespace(db=db, _has=lambda t: bool(db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,), one=True)))
        self.comp = {"id": 23, "campaign_id": 2}
        mo._probe_cache.clear()

    def p(self, value): mo._probe_cache.clear(); return mo.probe(self.ch, self.comp, "live_data", value, fresh=True)

    def test_chain_freshness_is_the_chain_read_not_a_brief(self):
        self.db.q("INSERT INTO mh_briefs (campaign_id, ts) VALUES (2, ?)", (time.time(),))  # a fresh brief proves nothing
        self.assertEqual(self.p("chain")["state"], "UNKNOWN")               # no chain snapshot yet
        self.db.q("INSERT INTO mh_samples (netuid, block, ts) VALUES (61, 9000000, ?)", (time.time() - 5 * 3600,))
        self.db.q("INSERT INTO mh_samples (netuid, block, ts) VALUES (62, 9000500, ?)", (time.time() - 60,))  # another subnet
        self.assertEqual(self.p("chain")["state"], "FAIL")                  # SN61's is older than 2 h
        self.assertEqual(self.p("chain/62")["state"], "PASS")               # a named subnet
        self.db.q("INSERT INTO mh_samples (netuid, block, ts) VALUES (61, 9000600, ?)", (time.time() - 600,))
        p = self.p("chain")
        self.assertEqual(p["state"], "PASS"); self.assertIn("block 9000600", p["evidence"]); self.assertIn("not the sandbox", p["evidence"])

    def scout(self, status, ago, note="Couldn't read the chain: connection refused"):
        self.db.q("CREATE TABLE IF NOT EXISTS mh_agent_state (campaign_id INTEGER, agent TEXT, status TEXT, note TEXT, last_run REAL, errors INTEGER DEFAULT 0, PRIMARY KEY (campaign_id, agent))")
        self.db.q("INSERT OR REPLACE INTO mh_agent_state (campaign_id, agent, status, note, last_run) VALUES (2, 'scout', ?, ?, ?)", (status, note, time.time() - ago))

    def test_chain_four_scenarios_fresh_stale_missing_failed(self):
        # Milestone 2 B2: fresh PASS, stale FAIL, missing UNKNOWN, retrieval failure UNKNOWN; the window is 2 h
        self.assertEqual(self.p("chain")["state"], "UNKNOWN")                                          # missing
        self.scout("error", 30)
        p = self.p("chain"); self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("connection refused", p["evidence"])  # missing + failing
        self.db.q("INSERT INTO mh_samples (netuid, block, ts) VALUES (61, 100, ?)", (time.time() - 2 * 3600 - 60,))   # 2 h 1 min: stale
        self.scout("ok", 10)
        self.assertEqual(self.p("chain")["state"], "FAIL")                                             # stale, collector fine
        self.scout("error", 10)
        p = self.p("chain"); self.assertEqual(p["state"], "UNKNOWN"); self.assertIn("retrieval failure", p["evidence"])  # stale + failing
        self.db.q("INSERT INTO mh_samples (netuid, block, ts) VALUES (61, 200, ?)", (time.time() - 2 * 3600 + 120,))   # 1 h 58 min
        self.scout("ok", 5)
        self.assertEqual(self.p("chain")["state"], "PASS")                                             # fresh, inside the 2 h window
        self.scout("error", 5)
        p = self.p("chain"); self.assertEqual(p["state"], "PASS"); self.assertIn("failed", p["evidence"])  # fresh data in hand; the failure is reported

    def test_chain_failure_older_than_the_snapshot_is_not_a_failure(self):
        self.db.q("INSERT INTO mh_samples (netuid, block, ts) VALUES (61, 100, ?)", (time.time() - 3 * 3600,))
        self.scout("error", 4 * 3600)                                         # failed before the snapshot, which then succeeded
        self.assertEqual(self.p("chain")["state"], "FAIL")                  # plain stale

    def test_chain_reads_the_teams_own_competition(self):
        self.db.q("ALTER TABLE mh_campaigns ADD COLUMN mech INTEGER"); self.db.q("UPDATE mh_campaigns SET mech=1 WHERE id=2")
        self.db.q("ALTER TABLE mh_samples ADD COLUMN mech INTEGER DEFAULT 0")
        self.ch._cols = lambda t: {c["name"] for c in self.db.q(f"PRAGMA table_info({t})")}
        self.db.q("INSERT INTO mh_samples (netuid, mech, block, ts) VALUES (61, 0, 500, ?)", (time.time() - 60,))      # competition 0, fresh
        self.db.q("INSERT INTO mh_samples (netuid, mech, block, ts) VALUES (61, 1, 400, ?)", (time.time() - 5 * 3600,))  # this team's, stale
        self.assertEqual(self.p("chain")["state"], "FAIL")                  # another competition's snapshot isn't this team's data

    def wp(self, value, outcome):
        from app import mining_web
        calls = []
        def fetch(url, timeout=None):
            calls.append((url, timeout))
            if isinstance(outcome, Exception): raise outcome
            return {"text": outcome, "seconds": 0.2}
        with mock.patch.object(mining_web, "fetch", fetch):
            return self.p(value), calls

    def test_web_is_a_live_read_now_not_a_past_fetch(self):
        from app import mining_web
        W = mining_web.WebError
        # 1 success: a page with content, read now with the check's short timeout
        p, calls = self.wp("web/github.com", "<html>pinned source</html>")
        self.assertEqual(p["state"], "PASS"); self.assertEqual(p["how"], "live"); self.assertEqual(calls, [("https://github.com/", mo.LIVE_WEB_TIMEOUT)])
        # 2 an incorrect or unavailable source: 404 FAIL; refused or DNS UNKNOWN (it may be AXoR's own network)
        self.assertEqual(self.wp("web/github.com", W("The page answered 404.", "http", 404))[0]["state"], "FAIL")
        self.assertEqual(self.wp("web/github.com", W("Couldn't read the page: [Errno -2] Name or service not known.", "network"))[0]["state"], "UNKNOWN")
        self.assertEqual(self.wp("web/github.com", W("That address isn't public.", "address"))[0]["state"], "FAIL")
        # 3 a timeout: UNKNOWN, never PASS
        self.assertEqual(self.wp("web/github.com", W("Couldn't read the page: timed out.", "timeout"))[0]["state"], "UNKNOWN")
        # 4 missing data: a page with no content
        p, _ = self.wp("web/github.com", "   ")
        self.assertEqual(p["state"], "FAIL"); self.assertIn("no content", p["evidence"])
        # 5 a retrieval failure: 5xx, 429 UNKNOWN; 403 FAIL (it refuses automated readers: web_read would too); anything else UNKNOWN
        for code, want in ((500, "UNKNOWN"), (503, "UNKNOWN"), (429, "UNKNOWN"), (408, "UNKNOWN"), (403, "FAIL"), (410, "FAIL")):
            self.assertEqual(self.wp("web/github.com", W(f"The page answered {code}.", "http", code))[0]["state"], want, code)
        self.assertEqual(self.wp("web/github.com", RuntimeError("boom"))[0]["state"], "UNKNOWN")  # the probe breaks: UNKNOWN
        self.assertEqual(self.wp("web/github.com", W("The page answered with application/pdf.", "type"))[0]["state"], "FAIL")

    def test_web_reads_the_saved_page_and_a_past_fetch_never_decides(self):
        self.db.q("INSERT INTO mw_web (comp_id, url, last_at, last_status) VALUES (23, 'https://taostats.io/subnets/61/weights', ?, 'ok')", (time.time() - 30 * 3600,))
        self.db.q("INSERT INTO mw_web (comp_id, url, last_at, last_status) VALUES (23, 'https://docs.ridges.ai/x', ?, 'failed')", (time.time() - 60,))
        self.db.q("INSERT INTO mw_web (comp_id, url, last_at, last_status) VALUES (99, 'https://theredteam.io/x', ?, 'ok')", (time.time(),))  # another team's
        p, calls = self.wp("web/taostats.io", "<table>weights</table>")
        self.assertEqual(calls[0][0], "https://taostats.io/subnets/61/weights")   # the team's saved page for that host
        self.assertEqual(p["state"], "PASS")
        p, _ = self.wp("web/docs.ridges.ai", "<p>docs</p>")
        self.assertEqual(p["state"], "PASS"); self.assertIn("failed", p["evidence"])  # a failed past fetch is reported; the live read decides
        from app import mining_web
        self.assertEqual(self.wp("web/taostats.io", mining_web.WebError("x", "http", 404))[0]["state"], "FAIL")  # an OK past fetch doesn't save it
        _, calls = self.wp("web/theredteam.io", "<p>x</p>")
        self.assertEqual(calls[0][0], "https://theredteam.io/")             # another team's page isn't this team's
        p, calls = self.wp("web", "<p>x</p>")                                # no host: the team's latest saved page
        self.assertEqual(p["state"], "PASS"); self.assertEqual(calls[0][0], "https://docs.ridges.ai/x")  # the newest saved page
        self.db.q("DELETE FROM mw_web")
        p, calls = self.wp("web", "<p>x</p>")
        self.assertEqual((p["state"], calls), ("UNKNOWN", []))               # nothing to read

    def test_a_failing_live_source_blocks_until_fixed_or_accepted_and_is_not_critical(self):
        self.o = o.init(self.db) or o._orc
        self.addCleanup(lambda: setattr(o, "_orc", None))
        t = {"id": 1, "title": "Read the dashboard", "detail": "", "needs": json.dumps(["live_data:web/theredteam.io"])}
        with mock.patch.object(mo, "probe", lambda ch, comp, cap, value=None, fresh=False, cached_only=False: {"cap": cap, "value": value, "state": "FAIL", "evidence": "stale", "how": "t", "checked": time.time()}):
            r = mo.task_readiness(self.ch, ME["id"], None, t, "comp:23", "mw_task:1")
        self.assertEqual(r["state"], "BLOCKED")
        self.assertFalse(r["items"][0]["critical"])                        # the Owner may accept it (CONDITIONAL)
        self.assertIn("sandbox internet is not involved", r["items"][0]["remedy"].lower())


if __name__ == "__main__":
    unittest.main()


class ChainQuery(unittest.TestCase):
    def test_a_chain_storage_query_never_passes_without_a_tool(self):
        # Milestone 4: task 2732's kind of work (Uids over every subnet) can't be served by snapshots, however fresh: FAIL, with why
        p = mo._live_data(types.SimpleNamespace(db=None), {"id": 22, "campaign_id": 1}, "chain/query")
        self.assertEqual(p["state"], "FAIL")
        self.assertIn("D-026", p["evidence"])

