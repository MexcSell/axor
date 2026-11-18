"""Agents → Models: the My Claude Code / My Codex cards read their own plan's usage (GET /api/agents/settings/usage/own:<p>),
on the signed-in person's own login, never the server's, and cached per person. Against test_cli_accounts' fake `claude`."""
import os, unittest

from app import plan_usage

import test_cli_accounts as T


class OwnLoginUsage(T.Base):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app import agents
        self.who = self.boss
        me = lambda req: {"id": self.who, "username": "root", "role": "admin"}
        app = FastAPI()
        app.include_router(agents.build(self.db, {"admin": me, "sudo": me, "ops": None}, lambda req: "127.0.0.1", self.dir.name))
        self.c = TestClient(app)
        plan_usage._cache.clear(); plan_usage._probed.clear()
        self.seen, self._get, self._codex = [], plan_usage._get, plan_usage.codex
        plan_usage._get = lambda url, headers, timeout=15: self.seen.append(headers["Authorization"]) or {"limits": []}
        plan_usage.codex = lambda exe, env, timeout=30: self.seen.append(env.get("CODEX_HOME")) or plan_usage._answer(plan="ChatGPT Plus")

    def tearDown(self):
        plan_usage._get, plan_usage.codex = self._get, self._codex
        plan_usage._cache.clear(); plan_usage._probed.clear()
        super().tearDown()

    def usage(self, p):
        r = self.c.get(f"/api/agents/settings/usage/{p}?fresh=1")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_claude_reads_your_own_token(self):
        self.give_claude(self.boss)
        u = self.usage("own:terminal")
        self.assertFalse(u.get("error"), u)
        self.assertEqual(self.seen, [f"Bearer {T.TOKEN}"])

    def test_codex_reads_your_own_codex_home(self):
        home = self.give_codex(self.boss)
        u = self.usage("own:codex")
        self.assertEqual(u["plan"], "ChatGPT Plus")
        self.assertEqual(self.seen, [home])

    def test_without_your_own_login_says_so_and_reads_nothing(self):
        u = self.usage("own:codex")
        self.assertIn("haven't connected your own Codex", u["error"])
        self.assertEqual(self.seen, [])

    def test_cached_per_person(self):
        self.give_codex(self.boss)
        self.assertFalse(self.c.get("/api/agents/settings/usage/own:codex").json().get("error"))
        self.who = self.alice  # another admin opening the page doesn't get boss's reading
        self.assertIn("haven't connected", self.c.get("/api/agents/settings/usage/own:codex").json()["error"])

    def test_unknown(self):
        self.assertEqual(self.c.get("/api/agents/settings/usage/own:nope").status_code, 404)
        self.assertEqual(self.c.post("/api/agents/settings/usage/own:codex/probe").status_code, 400)


if __name__ == "__main__":
    unittest.main()
