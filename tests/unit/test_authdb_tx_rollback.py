"""AuthDB.q's rollback on a failed statement (D-004 D4.1/D4.2) against AuthDB.tx() (G5-2.2 Milestone 3), merged together.

q() rolls a failed statement back so SQLite doesn't keep a write transaction open. Inside tx() that rollback would drop the
transaction's earlier statements and let its later ones commit on their own: a partial write. These tests pin the merged rule:
q() rolls back only outside tx(); inside it, the error propagates and tx() decides. They run on SQLite and, with DATABASE_URL, on
Postgres (where a failed statement aborts the whole transaction)."""
import os, sqlite3, tempfile, unittest

from app.auth import AuthDB


class TxRollback(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "a.db")
        self.db = AuthDB(self.path)
        self.db.q("INSERT INTO app_settings (k, v) VALUES ('taken', '0')")

    def keys(self):
        return {r["k"] for r in self.db.q("SELECT k FROM app_settings WHERE k IN ('first', 'second')")}

    def test_a_failed_statement_inside_a_transaction_rolls_the_whole_block_back(self):
        with self.assertRaises(sqlite3.Error):
            with self.db.tx():
                self.db.q("INSERT INTO app_settings (k, v) VALUES ('first', '1')")
                self.db.q("INSERT INTO app_settings (k, v) VALUES ('taken', '1')")   # unique violation: propagates
                self.db.q("INSERT INTO app_settings (k, v) VALUES ('second', '1')")  # never runs
        self.assertEqual(self.keys(), set())

    def test_a_caught_failure_inside_a_transaction_never_leaves_a_partial_write(self):
        # A caller that catches the error and goes on: on SQLite the transaction is still whole (both later and earlier statements
        # commit together); on Postgres it is aborted (the next statement raises and tx() rolls everything back). Never: the earlier
        # statement dropped and the later one committed alone, which is what a rollback inside q() did.
        try:
            with self.db.tx():
                self.db.q("INSERT INTO app_settings (k, v) VALUES ('first', '1')")
                try: self.db.q("INSERT INTO app_settings (k, v) VALUES ('taken', '1')")
                except sqlite3.Error: pass
                self.db.q("INSERT INTO app_settings (k, v) VALUES ('second', '1')")
        except sqlite3.Error:
            pass  # Postgres: the aborted transaction refuses the next statement
        self.assertIn(self.keys(), ({"first", "second"}, set()))
        self.assertNotEqual(self.keys(), {"second"})

    def test_outside_a_transaction_a_failed_statement_still_frees_the_database(self):
        with self.assertRaises(sqlite3.Error):
            self.db.q("INSERT INTO app_settings (k, v) VALUES ('taken', '1')")
        other = AuthDB(self.path)  # another connection: it must be able to write at once
        other.q("INSERT INTO app_settings (k, v) VALUES ('first', '1')")
        self.assertEqual(self.keys(), {"first"})

    def test_the_connection_works_normally_after_a_failed_transaction(self):
        with self.assertRaises(sqlite3.Error):
            with self.db.tx():
                self.db.q("INSERT INTO app_settings (k, v) VALUES ('taken', '1')")
        self.db.q("INSERT INTO app_settings (k, v) VALUES ('first', '1')")
        with self.db.tx():
            self.db.q("INSERT INTO app_settings (k, v) VALUES ('second', '1')")
        self.assertEqual(self.keys(), {"first", "second"})


if __name__ == "__main__":
    unittest.main()
