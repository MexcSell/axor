"""5.1 Postgres backend (db_pg.py): the SQLite → Postgres translation, offline; and a live round trip when DATABASE_URL is set.

The whole suite also runs on Postgres: DATABASE_URL=postgresql://… DATABASE_SCHEMA_PER_PATH=1 (k8s/stack/README.md)."""
import os, sqlite3, tempfile, unittest

from app import db_pg


class FakeConn:
    def conflict_key(self, t): return {"app_settings": ["k"], "pairs": ["a", "b"]}.get(t, [])
    def columns(self, t): return {"app_settings": ["k", "v"]}.get(t, [])


def tr(sql):
    out = db_pg.Translator(FakeConn())(sql)
    return out if len(out) > 1 else out[0]


class Translate(unittest.TestCase):
    def test_ddl_types(self):
        s, _ = tr("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, n INTEGER DEFAULT 0, x REAL, b BLOB, "
                  "u TEXT UNIQUE COLLATE NOCASE NOT NULL, loose, d DEFAULT 'a')")
        self.assertIn("id BIGSERIAL PRIMARY KEY", s)
        self.assertIn("n BIGINT DEFAULT 0", s)
        self.assertIn("x DOUBLE PRECISION", s)
        self.assertIn("b BYTEA", s)
        self.assertNotIn("NOCASE", s)
        self.assertIn("loose TEXT", s)
        self.assertIn("d TEXT DEFAULT 'a'", s)

    def test_alter_add_column(self):
        self.assertEqual(tr("ALTER TABLE users ADD COLUMN approved INTEGER DEFAULT 1")[0], "ALTER TABLE users ADD COLUMN approved BIGINT DEFAULT 1")

    def test_insert_or_ignore_and_replace(self):
        self.assertEqual(tr("INSERT OR IGNORE INTO x (a) VALUES (?)")[0].strip(), "INSERT INTO x (a) VALUES (?) ON CONFLICT DO NOTHING")
        s, _ = tr("INSERT OR REPLACE INTO app_settings VALUES (?,?)")
        self.assertIn("ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v", s)
        s, _ = tr("INSERT OR REPLACE INTO pairs (a, b) VALUES (?,?)")
        self.assertIn("ON CONFLICT (a, b) DO NOTHING", s)
        s, _ = tr("INSERT OR IGNORE INTO x (a) VALUES (?) RETURNING id")
        self.assertTrue(s.strip().endswith("ON CONFLICT DO NOTHING RETURNING id"), s)

    def test_expressions(self):
        s, _ = tr("SELECT MAX(a, b), MIN(x, 0), MAX(c) FROM t WHERE name LIKE ? AND y IS ? AND z IS NOT ?")
        self.assertIn("GREATEST(a, b)", s)
        self.assertIn("LEAST(x, 0)", s)
        self.assertIn("MAX(c)", s)
        self.assertIn("name ILIKE ?", s)
        self.assertIn("y IS NOT DISTINCT FROM ?", s)
        self.assertIn("z IS DISTINCT FROM ?", s)
        self.assertIn("lastval()", tr("SELECT last_insert_rowid() id")[0])
        self.assertIn("string_agg(DISTINCT (metric)::text, ',')", tr("SELECT GROUP_CONCAT(DISTINCT metric) FROM m")[0])
        self.assertIn("string_agg((path)::text, ', ')", tr("SELECT GROUP_CONCAT(path, ', ') FROM m")[0])

    def test_literals_are_left_alone(self):
        s, _ = tr("SELECT 'a LIKE b ? MAX(1,2)' AS t, x FROM y WHERE z LIKE '%?%'")
        self.assertIn("'a LIKE b ? MAX(1,2)'", s)
        self.assertIn("z ILIKE '%?%'", s)

    def test_pragma(self):
        self.assertIn("pg_attribute", tr("PRAGMA table_info(users)")[0])
        self.assertEqual(tr("PRAGMA journal_mode=WAL")[0], "SELECT 1 WHERE false")

    def test_fts5(self):
        stmts = tr("CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(text, title, item_id UNINDEXED, user_id UNINDEXED, tokenize='porter unicode61')")
        self.assertIn("tsv tsvector GENERATED ALWAYS AS", stmts[0][0])
        self.assertIn("item_id BIGINT", stmts[0][0])
        self.assertIn("USING GIN", stmts[1][0])
        s, pmap = tr("SELECT rowid cid, item_id, bm25(kb_fts, 1.0, 2.0) s FROM kb_fts WHERE kb_fts MATCH ? AND user_id=? AND item_id IN (?,?) ORDER BY s")
        self.assertIn("-ts_rank(kb_fts.tsv, axor_compat.fts5_query(?))", s)
        self.assertIn("kb_fts.tsv @@ axor_compat.fts5_query(?)", s)
        self.assertEqual(pmap, [0, 0, 1, 2, 3])  # the MATCH text twice (rank, filter), then the rest

    def test_split_statements(self):
        self.assertEqual(db_pg.split_statements("CREATE TABLE a (x TEXT DEFAULT ';'); CREATE INDEX i ON a(x);"),
                         ["CREATE TABLE a (x TEXT DEFAULT ';')", "CREATE INDEX i ON a(x)"])

    def test_values(self):
        self.assertEqual(db_pg._param(True), "1")
        self.assertEqual(db_pg._param(5), "5")
        self.assertEqual(db_pg._param(1.5), 1.5)
        import decimal
        self.assertEqual(db_pg._py(decimal.Decimal("3")), 3)
        self.assertEqual(db_pg._py(decimal.Decimal("2.5")), 2.5)
        self.assertEqual(db_pg._py(True), 1)

    def test_off_by_default(self):
        if not db_pg.enabled(): self.assertEqual(db_pg.describe(), {"engine": "sqlite"})


@unittest.skipUnless(db_pg.enabled(), "DATABASE_URL isn't a postgresql:// URL")
class Live(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_SCHEMA_PER_PATH"] = "1"
        self.c = db_pg.connect(os.path.join(self.dir.name, "live.db"))

    def tearDown(self):
        self.c.execute(f'DROP SCHEMA IF EXISTS "{self.c.schema}" CASCADE')
        self.c.close()
        self.dir.cleanup()

    def test_round_trip(self):
        c = self.c
        c.executescript("""CREATE TABLE IF NOT EXISTS s (k TEXT PRIMARY KEY, v TEXT);
                           CREATE TABLE IF NOT EXISTS r (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ok INTEGER, t REAL)""")
        c.execute("INSERT OR REPLACE INTO s VALUES (?,?)", ("a", "1"))
        c.execute("INSERT OR REPLACE INTO s VALUES (?,?)", ("a", "2"))
        self.assertEqual(c.execute("SELECT v FROM s WHERE k=?", ("a",)).fetchall(), [("2",)])
        cur = c.execute("INSERT INTO r (name, ok, t) VALUES (?,?,?)", ("Ann", True, 1.25))
        self.assertEqual(cur.lastrowid, 1)
        c.execute("INSERT INTO r (name, ok, t) VALUES (?,?,?)", ("bob", 0, 2))
        row = c.execute("SELECT SUM(ok=1) n, MAX(MAX(t), 2.0) m, COUNT(*) c, GROUP_CONCAT(name) g FROM r WHERE name LIKE ?", ("a%",)).fetchone()
        self.assertEqual(row, (1, 2.0, 1, "Ann"))
        self.assertEqual([r[1] for r in c.execute("PRAGMA table_info(r)")], ["id", "name", "ok", "t"])
        self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", ("r",)).fetchone())
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO s VALUES (?,?)", ("a", "3"))
        with self.assertRaises(sqlite3.OperationalError) as e:
            c.execute("ALTER TABLE r ADD COLUMN name TEXT")
        self.assertIn("duplicate column name", str(e.exception))

    def test_fts(self):
        c = self.c
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(text, title, item_id UNINDEXED, user_id UNINDEXED, tokenize='porter unicode61')")
        c.execute("INSERT INTO kb_fts (rowid, text, title, item_id, user_id) VALUES (?,?,?,?,?)", (7, "Validators score miners every epoch", "Scoring", 3, 1))
        c.execute("INSERT INTO kb_fts (rowid, text, title, item_id, user_id) VALUES (?,?,?,?,?)", (8, "Lunch menu", "Food", 4, 1))
        rows = c.execute("SELECT rowid cid, item_id, bm25(kb_fts, 1.0, 2.0) s FROM kb_fts WHERE kb_fts MATCH ? AND user_id=? ORDER BY s",
                         ('"validator" OR "epochs"', 1)).fetchall()
        self.assertEqual([r[0] for r in rows], [7])
        self.assertLess(rows[0][2], 0)


if __name__ == "__main__":
    unittest.main()
