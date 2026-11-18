"""auth.py: password rules, the rate limiter and admin accounts."""
import os, tempfile, unittest

from fastapi import HTTPException

from app import auth


class Passwords(unittest.TestCase):
    def test_short_password_is_refused(self):
        self.assertTrue(auth.password_problems("Ab1!x"))

    def test_strong_password_passes(self):
        self.assertEqual(auth.password_problems("Corr3ct-Horse-Battery!"), [])

    def test_long_passphrase_needs_no_symbols(self):
        self.assertEqual(auth.password_problems("violet orbit tangerine marble"), [])

    def test_username_inside_the_password(self):
        self.assertIn("Don't include your username in the password.", auth.password_problems("Alice-Str0ng!pass", "alice"))

    def test_one_time_passwords_are_strong(self):
        for _ in range(20):
            self.assertEqual(auth.password_problems(auth.one_time_password()), [])


class Limiter(unittest.TestCase):
    def test_blocks_after_the_limit(self):
        rl = auth.RateLimiter()
        for _ in range(3): rl.check("ip", 3, 60)
        with self.assertRaises(HTTPException) as e: rl.check("ip", 3, 60)
        self.assertEqual(e.exception.status_code, 429)
        rl.check("other-ip", 3, 60)  # keys are separate


class Admins(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = auth.AuthDB(os.path.join(self.dir.name, "auth.db"))

    def tearDown(self): self.dir.cleanup()

    def test_create_admin_forces_a_password_change(self):
        name, pw = self.db.create_admin("root-admin")
        u = self.db.find(name)
        self.assertEqual((u["role"], u["must_change"]), ("admin", 1))
        self.assertTrue(auth.ph.verify(u["pw_hash"], pw))

    def test_create_admin_upgrades_an_existing_account(self):
        name, _ = self.db.create_admin("second")
        self.db.q("UPDATE users SET role='user', disabled=1 WHERE username=?", (name,))
        self.db.create_admin("second")
        u = self.db.find("second")
        self.assertEqual((u["role"], u["disabled"]), ("admin", 0))
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM users", one=True)["n"], 1)

    def test_weak_chosen_password_is_refused(self):
        with self.assertRaises(ValueError): self.db.create_admin("third", password="password")


class WaitForApproval(unittest.TestCase):
    """A sign-up that needs approval keeps a powerless "pending" session that signs in once an admin approves."""
    PW = "violet orbit tangerine marble"

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        os.environ["HIBP_CHECK"] = "0"
        self.dir = tempfile.TemporaryDirectory()
        self.db = auth.AuthDB(os.path.join(self.dir.name, "auth.db"))
        self.db.setting("registration_approval", v="1")
        app = FastAPI(); app.include_router(auth.build(self.db)[0])
        self.c = TestClient(app)

    def tearDown(self): self.dir.cleanup()

    def register(self, name="newbie"):
        r = self.c.post("/api/auth/register", json={"username": name, "password": self.PW})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"stage": "pending", "username": name})
        return self.db.find(name)

    def poll(self): return self.c.post("/api/auth/pending").json()

    def test_waits_then_signs_in_when_approved(self):
        self.db.setting("auth_method", v="basic")
        u = self.register()
        self.assertEqual(self.poll()["stage"], "pending")
        self.assertFalse(self.c.get("/api/auth/me").json()["authenticated"])  # pending opens nothing
        self.assertEqual(self.c.get("/api/auth/me").json()["stage"], "pending")
        self.db.q("UPDATE users SET approved=1 WHERE id=?", (u["id"],))  # what admin "approve" does
        self.assertEqual(self.poll(), {"stage": "done"})
        me = self.c.get("/api/auth/me").json()
        self.assertTrue(me["authenticated"]); self.assertEqual(me["username"], "newbie")
        self.assertEqual(self.db.q("SELECT stage FROM sessions WHERE user_id=?", (u["id"],))[0]["stage"], "full")  # pending session replaced

    def test_approved_waits_for_ok_before_signing_in(self):
        self.db.setting("auth_method", v="basic")
        u = self.register()
        self.db.q("UPDATE users SET approved=1 WHERE id=?", (u["id"],))
        look = lambda: self.c.post("/api/auth/pending", json={"claim": False}).json()
        self.assertEqual(look(), {"stage": "approved", "username": "newbie"})
        self.assertEqual(look()["stage"], "approved")  # asking again changes nothing (certificate window, reload)
        self.assertFalse(self.c.get("/api/auth/me").json()["authenticated"])
        self.assertEqual(self.c.post("/api/auth/pending", json={"claim": True}).json(), {"stage": "done"})  # OK
        self.assertTrue(self.c.get("/api/auth/me").json()["authenticated"])

    def test_two_factor_goes_to_setup(self):
        self.db.setting("auth_method", v="2fa")
        u = self.register()
        self.db.q("UPDATE users SET approved=1 WHERE id=?", (u["id"],))
        r = self.poll()
        self.assertEqual(r["stage"], "setup"); self.assertIn("qr_svg", r)
        self.assertFalse(self.c.get("/api/auth/me").json()["authenticated"])

    def test_rejected_request_is_gone(self):
        u = self.register()
        self.db.q("DELETE FROM sessions WHERE user_id=?", (u["id"],)); self.db.q("DELETE FROM users WHERE id=?", (u["id"],))  # admin "reject"
        self.assertEqual(self.poll(), {"stage": "gone"})

    def test_no_pending_session_is_gone(self):
        self.assertEqual(self.poll(), {"stage": "gone"})


if __name__ == "__main__":
    unittest.main()
