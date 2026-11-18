"""secretbox.py (encrypted settings) and store.py (subnet history)."""
import os, sqlite3, tempfile, time, unittest
from unittest import mock

from app import secretbox
from app.store import Store


class FakeDB:
    """The two calls SecretBox makes on the app's settings table."""
    def __init__(self): self.kv = {}
    def setting(self, k, default=None, v=None):
        if v is not None: self.kv[k] = v
        return self.kv.get(k, default)
    def q(self, sql, args=()): self.kv.pop(args[0], None)


class Secrets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start(); os.environ.pop("SECRET_KEY", None)

    def tearDown(self): self.env.stop(); self.dir.cleanup()

    def test_round_trip_and_stored_encrypted(self):
        db = FakeDB()
        box = secretbox.SecretBox(db, self.dir.name)
        box.set("anthropic_api_key", "sk-ant-secret-value")
        self.assertEqual(box.get("anthropic_api_key"), "sk-ant-secret-value")
        self.assertNotIn("sk-ant-secret-value", db.kv["secret:anthropic_api_key"])
        self.assertEqual(oct(os.stat(os.path.join(self.dir.name, "secret.key")).st_mode & 0o777), "0o600")

    def test_a_new_key_reads_old_secrets_as_unset(self):
        db = FakeDB()
        secretbox.SecretBox(db, self.dir.name).set("k", "v")
        os.remove(os.path.join(self.dir.name, "secret.key"))
        self.assertIsNone(secretbox.SecretBox(db, self.dir.name).get("k"))

    def test_delete(self):
        db = FakeDB(); box = secretbox.SecretBox(db, self.dir.name)
        box.set("k", "v"); box.delete("k")
        self.assertIsNone(box.get("k"))

    def test_mask(self):
        self.assertEqual(secretbox.mask("sk-ant-api03-abcdefWXYZ"), "sk-ant-…WXYZ")
        self.assertEqual(secretbox.mask("short"), "••••")
        self.assertIsNone(secretbox.mask(""))


class History(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.s = Store(os.path.join(self.dir.name, "h.db"))

    def tearDown(self): self.dir.cleanup()

    def test_a_partial_row_keeps_the_known_values(self):
        now = time.time()
        self.s.put([{"netuid": 1, "block": 10, "ts": now, "price": 2.0, "reg_cost": 0.5}])
        self.s.put([{"netuid": 1, "block": 10, "ts": now, "emission_day": 9.0}])
        (ts, v), = self.s.series(now - 1)[1]
        self.assertEqual((v["price"], v["reg_cost"], v["emission_day"]), (2.0, 0.5, 9.0))

    def test_series_is_in_time_order_and_since(self):
        now = time.time()
        self.s.put([{"netuid": 2, "block": b, "ts": now - 100 + b, "price": float(b)} for b in (30, 10, 20)])
        self.assertEqual([v["price"] for _, v in self.s.series(now - 85)[2]], [20.0, 30.0])

    def test_prune(self):
        self.s.put([{"netuid": 3, "block": 1, "ts": time.time() - 40 * 86400, "price": 1.0}])
        self.s.prune(30)
        self.assertEqual(self.s.series(0), {})


if __name__ == "__main__":
    unittest.main()
