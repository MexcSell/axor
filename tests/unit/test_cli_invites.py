"""cli_invites.py: admins ask teammates to connect their own Claude Code / Codex. Asked / seen / declined / expired /
answered, who can be asked, reminders, the push, and that nothing here touches a login or runs on anyone's plan."""
import json, time, unittest

from fastapi import HTTPException

from app import cli_accounts, cli_invites
from app.llm import LLMError
from test_cli_accounts import TOKEN, Base


class FakePush:
    enabled = True
    def __init__(self): self.sent = []
    def call(self, method, path, body=None, **k): self.sent.append((method, path, body))


class Invites(Base):
    def setUp(self):
        super().setUp()
        self.push = FakePush()
        cli_invites.S["push"] = self.push
        cli_invites.init(self.db)
        self.db.setting("agents_for_members", v="1")
        self.me = {"id": self.boss, "username": "boss"}

    def tearDown(self):
        cli_invites.S.update(db=None, push=None)
        super().tearDown()

    def cell(self, uid, p):
        return next(r for r in cli_invites.team()["people"] if r["user_id"] == uid)["providers"][p]

    def sent(self, n):
        for _ in range(100):
            if len(self.push.sent) >= n: break
            time.sleep(.02)
        return self.push.sent

    def test_asking_shows_up_for_the_member_and_the_admin(self):
        out = cli_invites.ask(self.me, [self.alice], ["terminal", "codex"])
        self.assertEqual(out["asked"], [{"user_id": self.alice, "username": "alice", "providers": ["terminal", "codex"]}])
        reqs = cli_invites.pending(self.alice)
        self.assertEqual([r["provider"] for r in reqs], ["terminal", "codex"])
        self.assertEqual(reqs[0]["by"], "boss")
        self.assertEqual(self.cell(self.alice, "codex")["state"], "asked")
        self.assertIsNone(self.cell(self.alice, "codex")["seen"])
        self.assertEqual(self.cell(self.bob, "codex")["state"], "none")
        self.assertEqual(cli_invites.pending(self.bob), [])
        cli_invites.mark_seen(self.alice)
        self.assertIsNotNone(self.cell(self.alice, "codex")["seen"])

    def test_one_push_per_person_with_the_link_and_nothing_secret(self):
        cli_invites.ask(self.me, [self.alice, self.bob], ["terminal", "codex"])
        sent = self.sent(2)
        self.assertEqual(sorted(b["users"][0] for _, _, b in sent), sorted([self.alice, self.bob]))
        msg = sent[0][2]["message"]
        self.assertEqual(msg["url"], cli_invites.LINK)
        self.assertIn("Claude Code and Codex", msg["title"])

    def test_asking_touches_no_login_and_runs_nothing(self):
        cli_invites.ask(self.me, [self.alice], ["terminal", "codex"])
        self.assertFalse(cli_accounts.connected(self.alice, "terminal"))
        self.assertIsNone(cli_accounts.login_view(self.alice))  # no device sign-in started for her
        self.assertIsNone(cli_accounts.pick("terminal", self.alice).uid)  # the server's login, shared, until she connects hers
        self.assertEqual(self.calls(), [])

    def test_connecting_answers_the_request(self):
        cli_invites.ask(self.me, [self.alice], ["terminal", "codex"])
        self.give_claude(self.alice)
        self.assertEqual(self.cell(self.alice, "terminal")["state"], "connected")
        self.assertEqual([r["provider"] for r in cli_invites.pending(self.alice)], ["codex"])
        self.give_codex(self.alice)
        self.assertEqual(cli_invites.pending(self.alice), [])
        cli_invites.team()  # answered rows go when the team is read (the member's reads don't write)
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM cli_invites", one=True)["n"], 0)

    def test_the_team_view_never_carries_a_token(self):
        self.give_claude(self.alice)
        self.assertNotIn(TOKEN, json.dumps(cli_invites.team()))

    def test_who_cannot_be_asked(self):
        self.give_claude(self.bob)
        carol = self.user("carol", "user"); self.db.q("UPDATE users SET disabled=1 WHERE id=?", (carol,))
        dave = self.user("dave", "user"); self.db.q("UPDATE users SET approved=0 WHERE id=?", (dave,))
        out = cli_invites.ask(self.me, [self.bob, carol, dave, 999], ["terminal"])
        self.assertEqual(out["asked"], [])
        why = {s["user_id"]: s["why"] for s in out["skipped"]}
        self.assertIn("Already connected", why[self.bob])
        self.assertIn("disabled", why[carol])
        self.assertIn("approval", why[dave])
        self.assertIn("No such", why[999])
        self.assertEqual(self.sent(0), [])

    def test_members_cant_be_asked_while_agents_are_for_admins_only(self):
        self.db.setting("agents_for_members", v="0")
        out = cli_invites.ask(self.me, [self.alice, self.boss], ["codex"])
        self.assertEqual([a["user_id"] for a in out["asked"]], [self.boss])
        self.assertIn("Agents → Models", out["skipped"][0]["why"])
        self.assertFalse(next(r for r in cli_invites.team()["people"] if r["user_id"] == self.alice)["can_use"])

    def test_a_broken_login_can_be_asked_about_again_and_is_answered_once_it_works(self):
        self.give_claude(self.alice)
        cli_accounts._save(self.alice, "terminal", False, "401")
        self.assertEqual(self.cell(self.alice, "terminal")["state"], "not_working")
        self.assertEqual(len(cli_invites.ask(self.me, [self.alice], ["terminal"])["asked"]), 1)
        self.assertIn("invite", self.cell(self.alice, "terminal"))
        self.assertEqual(len(cli_invites.pending(self.alice)), 1)
        cli_accounts.test(self.alice, "terminal")  # the token works again
        self.assertEqual(cli_invites.pending(self.alice), [])

    def test_declining_and_asking_again(self):
        cli_invites.ask(self.me, [self.alice], ["codex"])
        cli_invites.decline(self.alice, "codex")
        self.assertEqual(self.cell(self.alice, "codex")["state"], "declined")
        self.assertEqual(cli_invites.pending(self.alice), [])
        with self.assertRaises(HTTPException) as e: cli_invites.remind(self.me, self.alice, "codex")
        self.assertEqual(e.exception.status_code, 400)
        cli_invites.ask(self.me, [self.alice], ["codex"])
        self.assertEqual(self.cell(self.alice, "codex")["state"], "asked")
        self.assertEqual(len(cli_invites.pending(self.alice)), 1)

    def test_requests_expire(self):
        cli_invites.ask(self.me, [self.alice], ["codex"])
        self.db.q("UPDATE cli_invites SET created=?", (time.time() - cli_invites.TTL - 1,))
        self.assertEqual(self.cell(self.alice, "codex")["state"], "expired")
        self.assertEqual(cli_invites.pending(self.alice), [])

    def test_reminders_once_an_hour_and_they_count_as_unseen_again(self):
        cli_invites.ask(self.me, [self.alice], ["codex"])
        cli_invites.mark_seen(self.alice)
        cli_invites.remind(self.me, self.alice, "codex")
        c = self.cell(self.alice, "codex")
        self.assertIsNotNone(c["reminded"]); self.assertIsNone(c["seen"])
        self.assertTrue(self.sent(2)[1][2]["message"]["title"].startswith("Reminder"))
        with self.assertRaises(HTTPException) as e: cli_invites.remind(self.me, self.alice, "codex")
        self.assertEqual(e.exception.status_code, 429)
        cli_invites.cancel(self.alice, "codex")
        self.assertEqual(self.cell(self.alice, "codex")["state"], "none")
        with self.assertRaises(HTTPException): cli_invites.remind(self.me, self.alice, "codex")

    def test_asking_again_within_the_hour_sends_nothing_after_that_it_is_a_reminder(self):
        cli_invites.ask(self.me, [self.alice], ["codex"])
        out = cli_invites.ask(self.me, [self.alice], ["codex"])
        self.assertEqual(out["asked"], [])
        self.assertIn("within the hour", out["skipped"][0]["why"])
        self.assertEqual(len(self.sent(1)), 1)
        self.db.q("UPDATE cli_invites SET created=?", (time.time() - 2 * 3600,))
        self.assertEqual(len(cli_invites.ask(self.me, [self.alice], ["codex"])["asked"]), 1)
        self.assertEqual(len(self.sent(2)), 2)
        self.assertIsNotNone(self.cell(self.alice, "codex")["reminded"])

    def test_a_deleted_user_takes_their_requests(self):
        cli_invites.ask(self.me, [self.alice], ["codex"])
        self.db.q("DELETE FROM users WHERE id=?", (self.alice,))
        cli_invites.team()
        self.assertEqual(self.db.q("SELECT COUNT(*) n FROM cli_invites", one=True)["n"], 0)

    def test_bad_input(self):
        with self.assertRaises(HTTPException): cli_invites.ask(self.me, [self.alice], ["gemini"])
        with self.assertRaises(HTTPException): cli_invites.ask(self.me, [], ["codex"])


if __name__ == "__main__":
    unittest.main()
