"""G5-5 L5.3 (runtime monitoring; T-11; Owner decision Q-3 option (a) of 2026-11-13): the Owner declares, per team, the
competition endpoints AXoR watches; an API change raises a risk-register row for that team within one watch interval.

- Only the Owner declares the list (audited); nothing is watched by default, and no agent tool can add an endpoint.
- What is compared is what the endpoint promises (shape()), not the values it holds: prose and examples in an OpenAPI
  document don't count, a new path, a removed property, a changed type or a changed required list do.
- The first reading is the baseline and raises nothing. A changed reading writes what was added and removed to the watch's
  record, and opens the row `api:comp:<id>:<name>` (source "monitor", the team's scope, the team's owning account).
- Three readings in a row without an answer open `…:unreachable`; an answer resolves it.
"""
import json, os, sys, time, types, unittest

from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
from app import mining_web as W, orchestrator  # noqa: E402
import test_mission_cycles as tc  # noqa: E402  (as a module: its own tests don't run again here)
from test_mission_persistent_evidence import ADMIN, OWNER, TEAM_ACCOUNT, WID  # noqa: E402

URL = "https://api.example.org/openapi.json"
EP = [{"name": "challenge-openapi", "url": URL}]


def spec(**over):
    d = {"openapi": "3.1.0", "info": {"title": "Challenge", "version": "1.0.0", "description": "The challenge API."},
         "paths": {"/solve": {"post": {"summary": "Solve one task", "operationId": "solve",
                                       "parameters": [{"name": "trace", "in": "query", "required": False, "schema": {"type": "string"}}],
                                       "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Task"}}}},
                                       "responses": {"200": {"description": "The answer"}}}},
                   "/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
         "components": {"schemas": {"Task": {"type": "object", "required": ["id", "media"],
                                             "properties": {"id": {"type": "string", "description": "The task's id"}, "media": {"type": "string", "format": "uri"}}}}}}
    d.update(over)
    return d


class Shape(unittest.TestCase):
    def sha(self, doc): return W.shape(json.dumps(doc) if not isinstance(doc, str) else doc)[1]

    def test_prose_and_examples_are_not_the_contract(self):
        a = spec()
        b = spec(info={"title": "Challenge API", "version": "1.0.1", "description": "Reworded."})
        b["paths"]["/solve"]["post"]["summary"] = "Solves a task"
        b["components"]["schemas"]["Task"]["properties"]["id"]["description"] = "Reworded"
        b["components"]["schemas"]["Task"]["properties"]["id"]["example"] = "t-1"
        self.assertEqual(self.sha(a), self.sha(b))

    def test_changes_to_the_contract_change_the_shape(self):
        base = self.sha(spec())
        def changed(fn):
            d = spec(); fn(d); return self.sha(d) != base
        self.assertTrue(changed(lambda d: d["paths"].update({"/task": {"get": {"responses": {"200": {"description": "x"}}}}})))      # a new path
        self.assertTrue(changed(lambda d: d["paths"].pop("/health")))                                                               # a path removed
        self.assertTrue(changed(lambda d: d["components"]["schemas"]["Task"]["properties"]["id"].update(type="integer")))          # a type changed
        self.assertTrue(changed(lambda d: d["components"]["schemas"]["Task"].update(required=["id"])))                              # no longer required
        self.assertTrue(changed(lambda d: d["components"]["schemas"]["Task"]["properties"].pop("media")))                           # a property removed
        self.assertTrue(changed(lambda d: d["paths"]["/solve"]["post"]["parameters"][0].update(required=True)))                     # a parameter now required
        self.assertTrue(changed(lambda d: d["paths"]["/solve"]["post"]["responses"].update({"422": {"description": "bad"}})))       # a new response code

    def test_plain_json_is_compared_by_keys_and_types_and_text_by_its_lines(self):
        self.assertEqual(self.sha({"rows": [{"id": 1, "score": 0.5}], "n": 3}), self.sha({"rows": [{"id": 9, "score": 0.9}, {"id": 2, "score": 0.1}], "n": 40}))
        self.assertNotEqual(self.sha({"rows": [{"id": 1, "score": 0.5}]}), self.sha({"rows": [{"id": 1, "score": 0.5, "rank": 2}]}))
        self.assertNotEqual(self.sha({"n": 3}), self.sha({"n": "3"}))
        self.assertNotEqual(self.sha("# API\nPOST /solve\n"), self.sha("# API\nPOST /solve\nPOST /task\n"))


class Watch(tc.Base):
    def setUp(self):
        super().setUp()
        q = self.db.q
        q("DROP TABLE IF EXISTS mw_files")
        q("""CREATE TABLE mw_files (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, path TEXT, content TEXT, size INTEGER, agent_id INTEGER,
             updated REAL, UNIQUE (comp_id, path))""")
        self.events = []
        work = types.SimpleNamespace(db=self.db, _event=lambda wid, kind, text, **k: self.events.append((kind, text)))
        self.web = W.Web(work)
        self.doc, self.down, self.reads = spec(), None, 0
        def fetch(url, timeout=None):
            self.reads += 1
            if self.down: raise W.WebError(self.down, "network")
            text = json.dumps(self.doc)
            return {"url": url, "final": url, "kind": "application/json", "text": text, "truncated": False, "fetched_at": "2026-11-13 06:00:00 UTC",
                    "sha256": W.hashlib.sha256(text.encode()).hexdigest()}
        self._fetch, W.fetch = W.fetch, fetch
        self.t = time.time()

    def tearDown(self):
        W.fetch = self._fetch; db = self.db
        super().tearDown()
        try: db.db.close()       # on Postgres an AuthDB holds a connection for as long as it lives (PX-R13)
        except Exception: pass   # noqa: BLE001

    def declare(self, eps=EP): return self.web.set_endpoints(self.me(OWNER), WID, eps, "10.0.0.9")
    def round(self, minutes=0):
        self.t += minutes * 60
        return self.web.tick_endpoints(self.t)
    def rows(self): return [r for r in self.orc.risks(TEAM_ACCOUNT, limit=500) if r["source"] == "monitor"]
    def state(self): return self.web._endpoint_state(WID, "challenge-openapi")

    def test_only_the_owner_declares_endpoints_and_nothing_is_watched_by_default(self):
        self.assertEqual((self.web.endpoints(WID), self.round(), self.reads), ([], 0, 0))
        for who in (self.me(ADMIN), self.me(TEAM_ACCOUNT)):
            with self.assertRaises(HTTPException) as e: self.web.set_endpoints(who, WID, EP)
            self.assertEqual(e.exception.status_code, 403)
        for bad in ([{"name": "Bad Name", "url": URL}], [{"name": "x", "url": "ftp://x/y"}], EP + EP, [{"name": f"e{i}", "url": URL} for i in range(9)]):
            with self.assertRaises(HTTPException) as e: self.declare(bad)
            self.assertEqual(e.exception.status_code, 422)
        with self.assertRaises(HTTPException) as e: self.web.set_endpoints(self.me(OWNER), 999, EP)
        self.assertEqual(e.exception.status_code, 404)
        self.assertEqual(self.declare(), {"endpoints": EP, "every_min": W.ENDPOINT_EVERY})
        a = self.db.q("SELECT actor, target, ip, detail FROM audit WHERE action='watch.endpoints'", one=True)
        self.assertEqual((a["actor"], a["target"], a["ip"], a["detail"]), ("the-owner", f"comp:{WID}", "10.0.0.9", "none -> challenge-openapi"))
        self.declare([]); self.assertEqual((self.web.endpoints(WID), self.round()), ([], 0))   # an empty list stops the watching

    def test_no_agent_tool_declares_an_endpoint(self):
        names = {t["name"] for t in W.tools(True)}
        self.assertFalse({n for n in names if "endpoint" in n})
        src = open(W.__file__).read()
        self.assertEqual(src.count("self.db.setting(f\"{ENDPOINTS_KEY}{int(wid)}\", v="), 1)   # one writer: the Owner's

    def test_an_api_change_raises_a_register_row_within_one_interval(self):
        self.declare()
        self.assertEqual((self.round(), self.state()["status"], self.rows(), self.events), (1, "ok", [], []))   # the baseline raises nothing
        self.assertEqual((self.round(W.ENDPOINT_EVERY - 1), self.reads), (0, 1))                               # not due yet
        self.assertEqual((self.round(1), self.reads, self.rows()), (1, 2, []))                                # due; the same shape
        self.doc["info"]["description"] = "Reworded only."
        self.assertEqual((self.round(W.ENDPOINT_EVERY), self.rows()), (1, []))                                # prose changed: not the contract
        self.doc["components"]["schemas"]["Task"]["properties"].pop("media")                                  # the competition drops a field …
        self.doc["paths"]["/task"] = {"get": {"responses": {"200": {"description": "x"}}}}                    # … and adds a path
        self.assertEqual(self.round(W.ENDPOINT_EVERY), 1)                                                     # one interval later
        (r,) = self.rows()
        self.assertEqual((r["rkey"], r["mission"], r["source"], r["status"], r["severity"], r["critical"]), (f"api:comp:{WID}:challenge-openapi", f"comp:{WID}", "monitor", "open", "high", 0))
        ev = json.loads(r["evidence"]) if isinstance(r["evidence"], str) else r["evidence"]
        self.assertEqual((ev["url"], ev["record"]), (URL, "data/web/endpoints/challenge-openapi.json"))
        self.assertTrue(any("/paths//task" in x for x in ev["added"])); self.assertTrue(any("properties/media" in x for x in ev["removed"]))
        st = self.state()
        self.assertEqual((st["change"]["to_sha256"], st["shape_sha256"], st["change"]["from_sha256"] != st["shape_sha256"]), (ev["to_sha256"], ev["to_sha256"], True))
        self.assertEqual(self.events[-1][0], "error"); self.assertIn("what it promises changed", self.events[-1][1])
        self.assertEqual((self.round(W.ENDPOINT_EVERY), len(self.rows()), self.rows()[0]["seen"]), (1, 1, r["seen"]))   # the same shape again: the row isn't touched
        self.assertEqual([x["rkey"] for x in self.orc.risks(TEAM_ACCOUNT, source="monitor")], [r["rkey"]])   # and the register's source filter finds it

    def test_an_endpoint_that_stops_answering_is_a_finding_and_an_answer_resolves_it(self):
        self.declare(); self.round()
        self.down = "Couldn't read the page: connection refused."
        for i in range(2): self.round(W.ENDPOINT_EVERY)
        self.assertEqual((self.rows(), self.state()["fails"]), ([], 2))
        self.round(W.ENDPOINT_EVERY)
        (r,) = self.rows()
        self.assertEqual((r["rkey"], r["status"], r["severity"]), (f"api:comp:{WID}:challenge-openapi:unreachable", "open", "medium"))
        self.assertEqual(self.state()["shape_sha256"], W.shape(json.dumps(spec()))[1])                      # the last good reading is kept
        self.down = None
        self.round(W.ENDPOINT_EVERY)
        self.assertEqual((self.rows()[0]["status"], self.state()["fails"]), ("resolved", 0))

    def test_a_new_address_under_the_same_name_is_a_new_baseline(self):
        self.declare(); self.round()
        self.declare([{"name": "challenge-openapi", "url": "https://api.example.org/v2/openapi.json"}])
        self.doc["paths"].pop("/health")
        self.assertEqual((self.web.check_endpoint(WID, self.web.endpoints(WID)[0], self.t + 1), self.rows()), ("baseline", []))


if __name__ == "__main__":
    unittest.main()
