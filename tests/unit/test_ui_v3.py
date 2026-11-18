"""ui_v3.py: /api/ui (UI v3): appearance preferences, organisation UI settings, news sources."""
import os, tempfile, unittest

from fastapi import HTTPException

from app import ui_v3
from app.auth import AuthDB


class Sanitize(unittest.TestCase):
    def test_defaults_for_garbage(self):
        for bad in (None, 1, "x", [], {"style": "neon-9000", "mode": "purple", "fontScale": "huge"}):
            self.assertEqual(ui_v3.sanitize_appearance(bad), ui_v3.DEFAULT_APPEARANCE, repr(bad))

    def test_keeps_valid_values_and_drops_unknown_keys(self):
        got = ui_v3.sanitize_appearance({"style": "pretty", "mode": "light", "accent": "#A855F7", "fontScale": 133, "highContrast": True, "evil": "<script>"})
        self.assertEqual((got["style"], got["mode"], got["accent"], got["fontScale"], got["highContrast"]), ("pretty", "light", "#a855f7", 120, True))
        self.assertNotIn("evil", got)

    def test_accent_must_be_a_hex_colour(self):
        self.assertIsNone(ui_v3.sanitize_appearance({"accent": "red; background:url(x)"})["accent"])

    def test_booleans_must_be_true_booleans(self):
        self.assertFalse(ui_v3.sanitize_appearance({"reducedMotion": "yes"})["reducedMotion"])

    def test_glow_and_avatar_options(self):
        got = ui_v3.sanitize_appearance({"glow": 140, "iconSet": "neotech", "avatarFace": "elite", "avatarColor": "gold"})
        self.assertEqual((got["glow"], got["iconSet"], got["avatarFace"], got["avatarColor"]), (100, "neotech", "elite", "gold"))
        self.assertEqual(ui_v3.sanitize_appearance({"avatarFace": "skull"})["avatarFace"], "classic")

    def test_nan_font_scale(self):
        self.assertEqual(ui_v3.sanitize_appearance({"fontScale": float("nan")})["fontScale"], 100)

    def test_infinite_numbers_fall_back(self):
        got = ui_v3.sanitize_appearance({"fontScale": float("inf"), "glow": float("-inf")})
        self.assertEqual((got["fontScale"], got["glow"]), (100, 85))

    def test_concurrent_adds_keep_every_source(self):
        import threading
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        db = AuthDB(os.path.join(d.name, "c.db"))
        r = ui_v3.build(db, lambda req: req.user, lambda req: "127.0.0.1")
        add = next(x.endpoint for x in r.routes if x.path == "/api/ui/news-sources" and "POST" in x.methods)
        admin = Req({"username": "boss", "role": "admin"})
        ts = [threading.Thread(target=add, args=(ui_v3.SourceBody(url=f"https://n{i}.example.com/rss"), admin)) for i in range(12)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(ui_v3.load_sources(db)), 12)


class SourceUrl(unittest.TestCase):
    def test_public_http_urls_pass(self):
        self.assertEqual(ui_v3.check_source_url(" https://github.blog/feed/ "), "https://github.blog/feed/")
        self.assertEqual(ui_v3.check_source_url("http://example.com:8080/rss"), "http://example.com:8080/rss")

    def test_refused(self):
        for bad in ("", "ftp://example.com/x", "javascript:alert(1)", "file:///etc/passwd", "http://localhost/x", "http://127.0.0.1/",
                    "http://10.0.0.5/feed", "http://192.168.1.1", "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://0.0.0.0/", "http://127.1/", "http://2130706433/", "http://0x7f000001/",
                    "http://redis.default.svc/", "http://metadata.google.internal/", "http://user:pw@example.com/", "http://example.com:6379/", "https://" + "a" * 600):
            with self.assertRaises(ValueError, msg=bad): ui_v3.check_source_url(bad)


class Req:
    def __init__(self, user): self.user = user


class Router(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = AuthDB(os.path.join(self.dir.name, "a.db"))

        def require(req):
            if not req.user: raise HTTPException(401, "Sign in.")
            return req.user

        r = ui_v3.build(self.db, require, lambda req: "127.0.0.1")
        ep = {(m, x.path): x.endpoint for x in r.routes for m in x.methods}
        self.ep = lambda m, p: ep[(m, "/api/ui" + p)]
        self.admin = Req({"username": "boss", "role": "admin"})
        self.ann = Req({"username": "ann", "role": "user"})
        self.bob = Req({"username": "bob", "role": "user"})

    def tearDown(self): self.dir.cleanup()

    def test_signed_out_is_refused(self):
        for m, p in (("GET", "/bootstrap"), ("GET", "/preferences"), ("GET", "/settings"), ("GET", "/news-sources")):
            with self.assertRaises(HTTPException) as e: self.ep(m, p)(Req(None))
            self.assertEqual(e.exception.status_code, 401)

    def test_preferences_are_per_user_and_sanitised(self):
        self.assertIsNone(self.ep("GET", "/preferences")(self.ann)["appearance"])
        out = self.ep("PUT", "/preferences")(ui_v3.PrefsBody(appearance={"style": "fancy", "mode": "dark", "fontScale": 50, "x": 1}), self.ann)
        self.assertEqual((out["appearance"]["style"], out["appearance"]["fontScale"]), ("fancy", 90))
        self.assertEqual(self.ep("GET", "/preferences")(self.ann)["appearance"]["style"], "fancy")
        self.assertIsNone(self.ep("GET", "/preferences")(self.bob)["appearance"])  # another user's prefs don't leak

    def test_self_renewal_is_admin_only(self):
        with self.assertRaises(HTTPException) as e: self.ep("PUT", "/settings")(ui_v3.SettingsBody(selfRenewal=True), self.ann)
        self.assertEqual(e.exception.status_code, 403)
        self.assertFalse(self.ep("GET", "/settings")(self.ann)["self_renewal"])
        self.assertTrue(self.ep("PUT", "/settings")(ui_v3.SettingsBody(selfRenewal=True), self.admin)["self_renewal"])
        self.assertTrue(self.ep("GET", "/bootstrap")(self.ann)["settings"]["selfRenewal"])

    def test_ai_roles_validated(self):
        with self.assertRaises(HTTPException) as e: self.ep("PUT", "/settings")(ui_v3.SettingsBody(aiRoles={"overlord": "x"}), self.admin)
        self.assertEqual(e.exception.status_code, 422)
        out = self.ep("PUT", "/settings")(ui_v3.SettingsBody(aiRoles={"code": "Claude Code"}), self.admin)
        self.assertEqual(out["ai_roles"]["code"], "Claude Code")
        self.assertEqual(out["ai_roles"]["architecture"], ui_v3.DEFAULT_SETTINGS["ai_roles"]["architecture"])

    def test_autonomy_quiet_hours_and_verification_persist(self):
        put, get = self.ep("PUT", "/settings"), self.ep("GET", "/settings")
        with self.assertRaises(HTTPException) as e: put(ui_v3.SettingsBody(autonomy={"L5": True}), self.ann)
        self.assertEqual(e.exception.status_code, 403)
        put(ui_v3.SettingsBody(autonomy={"L4": True, "L5": True}, verificationProvider="External inspection Co."), self.admin)
        with self.assertRaises(HTTPException) as e: put(ui_v3.SettingsBody(autonomy={"L0": False}), self.admin)
        self.assertEqual(e.exception.status_code, 422)
        put(ui_v3.SettingsBody(quietHours=True, quietFrom="23:30", quietTo="06:15"), self.ann)  # members set their quiet hours
        with self.assertRaises(HTTPException) as e: put(ui_v3.SettingsBody(quietFrom="25:00"), self.ann)
        self.assertEqual(e.exception.status_code, 422)
        s = get(self.ann)
        self.assertEqual((s["autonomy"]["L5"], s["verification_provider"], s["quiet_hours"], s["quiet_from"], s["quiet_to"]), (True, "External inspection Co.", True, "23:30", "06:15"))
        b = self.ep("GET", "/bootstrap")(self.bob)["settings"]  # organisation settings are shared; quiet hours are personal
        self.assertEqual((b["autonomy"]["L4"], b["verificationProvider"], b["quietHours"], b["quietFrom"]), (True, "External inspection Co.", False, "22:00"))

    def test_legacy_org_notifications_are_not_personal(self):
        import json as _json
        self.db.setting(ui_v3.SETTINGS, v=_json.dumps({"notifications": {"digest": False}, "quiet_hours": True}))  # an older org-wide record
        s = self.ep("GET", "/settings")(self.bob)
        self.assertTrue(s["notifications"]["digest"]); self.assertFalse(s["quiet_hours"])  # bob gets defaults, not the legacy values

    def test_members_change_their_own_notifications(self):
        out = self.ep("PUT", "/settings")(ui_v3.SettingsBody(notifications={"digest": False, "unknown": True}), self.ann)
        self.assertFalse(out["notifications"]["digest"])
        self.assertNotIn("unknown", out["notifications"])
        self.assertTrue(self.ep("GET", "/settings")(self.bob)["notifications"]["digest"])  # personal: bob is unaffected

    def test_news_sources(self):
        add, lst = self.ep("POST", "/news-sources"), self.ep("GET", "/news-sources")
        with self.assertRaises(HTTPException) as e: add(ui_v3.SourceBody(url="https://news.example.com/rss"), self.ann)
        self.assertEqual(e.exception.status_code, 403)  # organisation scope needs an admin
        s = add(ui_v3.SourceBody(url="https://news.example.com/rss", scope="mission", missionId="M-001", cadence="Hourly"), self.ann)
        self.assertEqual((s["scope"], s["missionId"], s["cadence"], s["addedBy"]), ("mission", "M-001", "Hourly", "ann"))
        with self.assertRaises(HTTPException) as e: add(ui_v3.SourceBody(url="https://news.example.com/rss", scope="mission", missionId="M-001"), self.ann)
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(add(ui_v3.SourceBody(url="https://news.example.com/rss", scope="mission", missionId="comp:7"), self.ann)["missionId"], "comp:7")  # real refs
        self.assertEqual(add(ui_v3.SourceBody(url="https://news.example.com/x", scope="mission", missionId="mx:3"), self.ann)["missionId"], "mx:3")
        with self.assertRaises(HTTPException) as e: add(ui_v3.SourceBody(url="https://news.example.com/y", scope="mission", missionId="comp:../x"), self.ann)
        self.assertEqual(e.exception.status_code, 422)
        with self.assertRaises(HTTPException) as e: add(ui_v3.SourceBody(url="http://169.254.169.254/", scope="mission", missionId="M-001"), self.ann)
        self.assertEqual(e.exception.status_code, 422)
        org = add(ui_v3.SourceBody(url="https://arxiv.org/rss/cs.AI", name="arXiv"), self.admin)
        self.assertEqual(len(lst(self.bob)["sources"]), 4)
        with self.assertRaises(HTTPException) as e: self.ep("PATCH", "/news-sources/{sid}")(s["id"], ui_v3.SourcePatch(enabled=False), self.bob)
        self.assertEqual(e.exception.status_code, 403)  # not the owner
        self.assertEqual(self.ep("PATCH", "/news-sources/{sid}")(s["id"], ui_v3.SourcePatch(enabled=False), self.ann)["status"], "disabled")
        self.ep("DELETE", "/news-sources/{sid}")(org["id"], self.admin)
        self.assertEqual(lst(self.ann)["sources"][0]["id"], s["id"])
        self.assertNotIn(org["id"], [x["id"] for x in lst(self.ann)["sources"]])
        self.assertEqual(self.ep("GET", "/bootstrap")(self.ann)["resources"]["newsSources"][0]["id"], s["id"])

    def test_actions_are_audited(self):
        self.ep("PUT", "/settings")(ui_v3.SettingsBody(selfRenewal=True), self.admin)
        rows = self.db.q("SELECT action, actor, detail FROM audit WHERE action LIKE ?", ("ui.%",))
        self.assertTrue(any(r["action"] == "ui.settings" and "self-renewal on" in r["detail"] for r in rows))


if __name__ == "__main__":
    unittest.main()
