"""mcp_hub.py: the MCP client (stdio, HTTP with JSON or SSE), discovery with read-only tools allowed first, secrets that never
leave the server, grants and who may set them, and calls from a run (allow-list, errors, size, timeouts)."""
import json, os, sys, tempfile, unittest

from fastapi import HTTPException

from app import mcp_hub
from app.auth import AuthDB
from app.secretbox import SecretBox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_mcp  # noqa: E402

ADMIN = {"id": 1, "username": "admin", "role": "admin"}
ALICE = {"id": 2, "username": "alice", "role": "user"}
BOB = {"id": 3, "username": "bob", "role": "user"}

def server(name="Fake", transport="stdio", url=None, headers=(), env=(), audience="admins", enabled=True, command=None, args=None):
    return mcp_hub.ServerIn(name=name, transport=transport, url=url, command=command or (sys.executable if transport == "stdio" else None),
                            args=args if args is not None else ([os.path.join(HERE, "fake_mcp.py")] if transport == "stdio" else []),
                            headers=[mcp_hub.Pair(key=k, value=v) for k, v in headers], env=[mcp_hub.Pair(key=k, value=v) for k, v in env],
                            audience=audience, enabled=enabled)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))
        self.box = SecretBox(self.db, self.dir.name)
        self.db.q("CREATE TABLE IF NOT EXISTS custom_agents (id INTEGER PRIMARY KEY, owner_id INTEGER)")
        self.db.q("INSERT INTO custom_agents VALUES (10, 2)")  # Alice's agent
        self.hub = mcp_hub.init(self.db, self.box)
        self.http = []

    def tearDown(self):
        for sid in list(self.hub.pool): self.hub._drop(sid)
        for s in self.http: s.shutdown(); s.server_close()
        mcp_hub._hub = None
        self.dir.cleanup()

    def serve(self, **kw):
        srv, url = fake_mcp.serve_http_in_thread(**kw)
        self.http.append(srv)
        return url


class Discovery(Base):
    def test_a_local_server_lists_its_tools_and_only_read_only_ones_start_allowed(self):
        s = self.hub.create(ADMIN, server())
        self.assertEqual(s["status"], "ok", s["error"])
        v = self.hub.view(s, ADMIN)
        self.assertEqual([t["name"] for t in v["tools"]], ["echo", "write_note", "boom", "slow", "big"])
        self.assertEqual({t["name"] for t in v["tools"] if t["allowed"]}, {"echo", "boom", "slow", "big"})
        self.assertEqual(v["server"]["name"], "fake-mcp")

    def test_a_retest_keeps_the_admins_choices(self):
        s = self.hub.create(ADMIN, server())
        self.hub.set_allowed(s["id"], ["write_note"])
        s = self.hub.test(s["id"])
        self.assertEqual(json.loads(s["allowed"]), ["write_note"])  # echo stays off: the admin turned it off

    def test_http_with_json_and_with_sse(self):
        for sse in (False, True):
            s = self.hub.create(ADMIN, server(name=f"Remote {sse}", transport="http", url=self.serve(sse=sse)))
            self.assertEqual((s["status"], len(json.loads(s["tools"]))), ("ok", 5), s["error"])

    def test_a_missing_command_or_wrong_token_is_a_clear_error(self):
        s = self.hub.create(ADMIN, server(name="Nope", command="/no/such/server", args=[]))
        self.assertEqual(s["status"], "error")
        self.assertIn("inside AXoR's container", s["error"])
        url = self.serve(token="t0p")
        s = self.hub.create(ADMIN, server(name="Locked", transport="http", url=url, headers=[("Authorization", "Bearer wrong")]))
        self.assertIn("refused AXoR's credentials", s["error"])

    def test_validation(self):
        for bad in (server(name=""), server(transport="http", url="ftp://x"), server(transport="stdio", command=" "), server(audience="all"),
                    server(headers=[("bad key", "v")])):
            with self.assertRaises(HTTPException): self.hub.create(ADMIN, bad)


class Secrets(Base):
    def test_values_never_leave_and_an_empty_value_keeps_the_old_one(self):
        url = self.serve(token="t0p")
        s = self.hub.create(ADMIN, server(name="Locked", transport="http", url=url, headers=[("Authorization", "Bearer t0p")]))
        self.assertEqual(s["status"], "ok", s["error"])
        dump = json.dumps(self.hub.listing(ADMIN)) + json.dumps(self.hub.grants(ADMIN, "hub:10"))
        self.assertNotIn("t0p", dump)
        self.assertIn("Authorization", dump)  # the name is shown
        self.assertNotIn("t0p", json.dumps(self.db.q("SELECT * FROM mcp_servers")))
        s = self.hub.update(ADMIN, s["id"], server(name="Locked", transport="http", url=url, headers=[("Authorization", "")]))
        self.assertEqual(s["status"], "ok", s["error"])  # still signed in: the value was kept
        self.hub.update(ADMIN, s["id"], server(name="Locked", transport="http", url=url, headers=[]))
        self.assertEqual(self.hub._secrets(s["id"])["headers"], {})

    def test_environment_reaches_a_local_server(self):
        args = ["-c", "import os,sys,json\nfor l in sys.stdin:\n m=json.loads(l)\n if 'id' in m: print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':"
                "{'protocolVersion':'x','serverInfo':{'name':os.environ.get('FAKE_NAME',''),'version':os.environ.get('AXOR_SECRET_PROBE','absent')}} if m['method']=='initialize' else {'tools':[]}}),flush=True)"]
        os.environ["AXOR_SECRET_PROBE"] = "leaked"  # stands in for ANTHROPIC_API_KEY, SECRET_KEY…
        try: s = self.hub.create(ADMIN, server(name="Env", args=args, env=[("FAKE_NAME", "from-env")]))
        finally: del os.environ["AXOR_SECRET_PROBE"]
        info = json.loads(s["server_info"])
        self.assertEqual((info["name"], info["version"]), ("from-env", "absent"))  # its own variables, none of AXoR's

    def test_members_see_only_everyone_servers_without_where_they_run(self):
        self.hub.create(ADMIN, server(name="Private"))
        self.hub.create(ADMIN, server(name="Shared", audience="everyone"))
        out = self.hub.listing(ALICE)
        self.assertEqual([s["name"] for s in out["servers"]], ["Shared"])
        self.assertNotIn("command", out["servers"][0])
        self.assertNotIn("calls", out)
        self.assertEqual({t["name"] for t in out["servers"][0]["tools"]}, {"echo", "boom", "slow", "big"})  # allowed tools only


class Grants(Base):
    def setUp(self):
        super().setUp()
        self.shared = self.hub.create(ADMIN, server(name="Shared", audience="everyone"))
        self.private = self.hub.create(ADMIN, server(name="Private"))

    def test_only_the_owner_or_an_admin_sets_an_agents_tools(self):
        G = mcp_hub.GrantIn
        with self.assertRaises(HTTPException) as e: self.hub.set_grants(BOB, "hub:10", [G(server_id=self.shared["id"])])
        self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(HTTPException): self.hub.set_grants(ALICE, "hub:10", [G(server_id=self.private["id"])])  # admins only
        out = self.hub.set_grants(ALICE, "hub:10", [G(server_id=self.shared["id"], tools=["echo", "write_note"])])
        got = next(s for s in out["servers"] if s["id"] == self.shared["id"])
        self.assertEqual((got["granted"], got["picked"]), (True, ["echo"]))  # write_note isn't allowed: dropped
        self.hub.set_grants(ADMIN, "hub:10", [G(server_id=self.private["id"])])
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM mcp_grants WHERE scope='hub:10'", one=True)["n"], 1)
        with self.assertRaises(HTTPException): self.hub.grants(ALICE, "nope:1")

    def test_a_run_gets_its_tools_and_calls_them(self):
        self.hub.set_grants(ALICE, "hub:10", [mcp_hub.GrantIn(server_id=self.shared["id"])])
        ext = self.hub.attach(["hub:10"], ALICE)
        names = [t["name"] for t in ext.tools]
        self.assertEqual(names, ["ext_shared__echo", "ext_shared__boom", "ext_shared__slow", "ext_shared__big"])
        self.assertTrue(all(len(n) <= 64 and t["input_schema"]["type"] == "object" for n, t in zip(names, ext.tools)))
        self.assertIn("ext_shared__echo", ext)
        self.assertNotIn("market_overview", ext)
        self.assertEqual(ext("ext_shared__echo", {"text": "hi"}), {"result": "echo: hi"})
        with self.assertRaises(ValueError): ext("ext_shared__boom", {})  # the tool's own error: run_loop marks it is_error
        big = ext("ext_shared__big", {})["result"]
        self.assertLess(len(big), mcp_hub.RESULT_CHARS + 100)
        calls = self.db.q("SELECT tool, ok, user_id, scope FROM mcp_calls ORDER BY id")
        self.assertEqual([(c["tool"], c["ok"]) for c in calls], [("echo", 1), ("boom", 0), ("big", 1)])
        self.assertEqual((calls[0]["user_id"], calls[0]["scope"]), (2, "hub:10"))

    def test_taking_a_tool_away_stops_calls_already_attached(self):
        self.hub.set_grants(ALICE, "hub:10", [mcp_hub.GrantIn(server_id=self.shared["id"])])
        ext = self.hub.attach(["hub:10"], ALICE)
        self.hub.set_allowed(self.shared["id"], ["boom"])
        self.assertIn("isn't allowed", ext("ext_shared__echo", {"text": "x"})["error"])
        self.db.q("UPDATE mcp_servers SET audience='admins' WHERE id=?", (self.shared["id"],))
        self.assertEqual(self.hub.attach(["hub:10"], ALICE).tools, [])  # no longer for members
        self.assertEqual(len(self.hub.attach(["hub:10"], ADMIN).tools), 1)

    def test_a_timeout_is_an_error_for_the_model_and_the_next_call_works(self):
        self.hub.set_grants(ALICE, "hub:10", [mcp_hub.GrantIn(server_id=self.shared["id"])])
        ext = self.hub.attach(["hub:10"], ALICE)
        old, mcp_hub.TIMEOUT = mcp_hub.TIMEOUT, 1
        try: out = ext("ext_shared__slow", {"seconds": 3})
        finally: mcp_hub.TIMEOUT = old
        self.assertIn("failed", out["error"])
        self.assertEqual(ext("ext_shared__echo", {"text": "again"}), {"result": "echo: again"})

    def test_deleting_a_server_removes_its_grants(self):
        self.hub.set_grants(ALICE, "hub:10", [mcp_hub.GrantIn(server_id=self.shared["id"])])
        self.hub.delete(self.shared["id"])
        self.assertEqual(self.db.q("SELECT * FROM mcp_grants"), [])
        self.assertIsNone(self.box.get(f"mcp:{self.shared['id']}"))
        self.assertEqual(mcp_hub.attach(["hub:10"], ALICE).tools, [])


class Teams(Base):
    """"team:<workspace id>": the team's owner (mining_work's _own) gives a server to every agent of the team."""
    class Work:
        def _own(self, me, wid):
            if wid != 7 or me["id"] not in (2, 1): raise HTTPException(404, "There's no such workspace.")
            return {}, {}

    def test_the_teams_owner_gives_tools_to_the_whole_team(self):
        mcp_hub.bind_teams(self.Work())
        s = self.hub.create(ADMIN, server(name="Shared", audience="everyone"))
        with self.assertRaises(HTTPException) as e: self.hub.set_grants(BOB, "team:7", [mcp_hub.GrantIn(server_id=s["id"])])
        self.assertEqual(e.exception.status_code, 404)
        self.hub.set_grants(ALICE, "team:7", [mcp_hub.GrantIn(server_id=s["id"], tools=["echo"])])
        ext = mcp_hub.attach(["team:7"], ALICE)  # mining_work attaches with the team owner's account
        self.assertEqual([t["name"] for t in ext.tools], ["ext_shared__echo"])
        self.assertEqual(ext("ext_shared__echo", {"text": "team"}), {"result": "echo: team"})
        self.assertEqual(mcp_hub.listed("team:7", ALICE), [("Shared", "echo", "ext_shared__echo")])

    def test_without_competition_teams_a_team_scope_is_refused(self):
        with self.assertRaises(HTTPException): self.hub.grants(ALICE, "team:7")


class Catalog(Base):
    """One-click servers. Offline here (the unit tests run with no network): the bundled ones are installed for real."""
    def test_the_catalog_lists_what_admins_can_add(self):
        cat = {c["key"]: c for c in self.hub.listing(ADMIN)["catalog"]}
        self.assertEqual(set(cat), {"github", "deepwiki", "context7", "exa", "papers", "database"})
        self.assertTrue(cat["deepwiki"]["keyless"] and cat["context7"]["keyless"] and cat["papers"]["keyless"])
        self.assertFalse(cat["github"]["keyless"] or cat["database"]["keyless"])
        self.assertNotIn("catalog", self.hub.listing(ALICE))

    def test_papers_installs_with_every_tool_allowed(self):
        s = self.hub.install(ADMIN, "papers", {})
        self.assertEqual(s["status"], "ok", s["error"])
        self.assertEqual(json.loads(s["allowed"]), ["citing_papers", "get_paper", "search_papers"])
        self.assertEqual([c["added"] for c in self.hub.listing(ADMIN)["catalog"] if c["key"] == "papers"], [[s["id"]]])

    def test_the_database_server_reads_and_refuses_writes_and_axors_own_files(self):
        import sqlite3
        path = os.path.join(self.dir.name, "shop.db")
        c = sqlite3.connect(path); c.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)"); c.execute("INSERT INTO items(name) VALUES ('a'), ('b')"); c.commit(); c.close()
        with self.assertRaises(HTTPException): self.hub.install(ADMIN, "database", {})  # the URL is required
        s = self.hub.install(ADMIN, "database", {"DATABASE_URL": "sqlite:///" + path})
        self.assertEqual((s["status"], len(json.loads(s["allowed"]))), ("ok", 3), s["error"])
        self.assertIn("--protect", json.loads(s["args"]))
        self.hub.set_grants(ADMIN, "hub:10", [mcp_hub.GrantIn(server_id=s["id"])])  # catalog servers start as admins' only
        ext = self.hub.attach(["hub:10"], ADMIN)
        q = json.loads(ext("ext_database__query", {"sql": "SELECT name FROM items ORDER BY id"})["result"])
        self.assertEqual(q["rows"], [["a"], ["b"]])
        for bad in ("DELETE FROM items", "select 1; drop table items", "PRAGMA writable_schema=1", "WITH x AS (SELECT 1) INSERT INTO items(name) SELECT 'c'"):
            with self.assertRaises(ValueError, msg=bad): ext("ext_database__query", {"sql": bad})
        self.assertEqual(sqlite3.connect(path).execute("SELECT COUNT(*) FROM items").fetchone()[0], 2)
        # AXoR's own data directory is never readable, whatever the URL says
        own = self.hub.install(ADMIN, "database", {"DATABASE_URL": "sqlite:///" + os.path.join(os.getenv("DATA_DIR", "/data"), "auth.db")})
        self.hub.set_grants(ADMIN, "hub:10", [mcp_hub.GrantIn(server_id=own["id"])])
        name = next(t["name"] for t in self.hub.attach(["hub:10"], ADMIN).tools if t["name"].endswith("list_tables"))
        with self.assertRaises(ValueError) as e: self.hub.attach(["hub:10"], ADMIN)(name, {})
        self.assertIn("AXoR's own data directory", str(e.exception))

    def test_the_github_entry_can_use_the_source_token_without_storing_it(self):
        with self.assertRaises(HTTPException): self.hub.install(ADMIN, "github", {"use_source": True})  # Source has none yet
        self.box.set("github_token", "ghp_SOURCE")
        s = self.hub.install(ADMIN, "github", {"use_source": True})  # can't connect offline; the settings are what's tested
        self.assertEqual(self.hub._secrets(s["id"])["headers"], {"Authorization": "Bearer " + mcp_hub.SOURCE_TOKEN})
        self.assertEqual(self.hub._live(s["id"])["headers"], {"Authorization": "Bearer ghp_SOURCE"})
        s2 = self.hub.install(ADMIN, "github", {"Authorization": "Bearer ghp_OWN"})  # pasted with "Bearer " already
        self.assertEqual(self.hub._live(s2["id"])["headers"], {"Authorization": "Bearer ghp_OWN"})
        self.assertNotIn("ghp_", json.dumps(self.hub.listing(ADMIN)))

    def test_schemas_lose_their_schema_key(self):
        self.assertEqual(mcp_hub._schema({"$schema": "x", "type": "object", "properties": {"a": {}}}), {"type": "object", "properties": {"a": {}}})


class Missions(Base):
    """"missions:<user id>": the tools a user's missions get in every engine (Workforce, Long tasks, Competition teams)."""
    def test_only_the_user_or_an_admin_sets_them_and_workforce_gets_them(self):
        s = self.hub.create(ADMIN, server(name="Shared", audience="everyone"))
        with self.assertRaises(HTTPException): self.hub.set_grants(BOB, "missions:2", [mcp_hub.GrantIn(server_id=s["id"])])
        self.hub.set_grants(ALICE, "missions:2", [mcp_hub.GrantIn(server_id=s["id"], tools=["echo"])])
        from app import workforce
        extra = workforce._mcp_extra({"owner": ALICE})
        self.assertEqual(list(extra), ["ext_shared__echo"])
        definition, run, counts = extra["ext_shared__echo"]
        self.assertTrue(counts)
        self.assertEqual(run({"text": "m"}), {"result": "echo: m"})
        self.assertEqual(workforce._mcp_extra({"owner": BOB}), {})


class Routes(Base):
    def test_grant_routes_win_over_the_server_id_routes(self):
        r = mcp_hub.build(self.db, self.box, lambda req: ADMIN, {"admin": lambda req: ADMIN, "sudo": lambda req: ADMIN}, lambda req: "")
        order = [(m, route.path) for route in r.routes for m in sorted(route.methods)]
        self.assertLess(order.index(("PUT", "/api/mcp/grants")), order.index(("PUT", "/api/mcp/{sid}")))
        self.assertLess(order.index(("GET", "/api/mcp/grants")), order.index(("PUT", "/api/mcp/{sid}")))


class Names(unittest.TestCase):
    def test_long_and_odd_tool_names_fit(self):
        n = mcp_hub.tool_name("averyveryverylong", "do.something/with spaces" * 5)
        self.assertLessEqual(len(n), 64)
        self.assertRegex(n, r"^[A-Za-z0-9_-]+$")
        self.assertNotEqual(n, mcp_hub.tool_name("averyveryverylong", "do.something/with spaces" * 6))
        self.assertEqual(mcp_hub.slugify("My GitHub (work)!"), "my_github_work")

    def test_results_flatten(self):
        self.assertEqual(mcp_hub.flatten({"content": [{"type": "text", "text": "a"}, {"type": "image", "mimeType": "image/png"}]}),
                         ("a\n[image image/png not shown]", False))
        self.assertEqual(mcp_hub.flatten({"structuredContent": {"x": 1}, "isError": True}), ('{"x": 1}', True))

    def test_nothing_attaches_before_init(self):
        mcp_hub._hub = None
        self.assertEqual(mcp_hub.attach(["hub:1"], ALICE).tools, [])
        self.assertNotIn("x", mcp_hub.attach(["hub:1"], ALICE))
