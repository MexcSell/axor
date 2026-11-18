"""5.1 pgvector (vector_pg.py): on Postgres with the vector extension, Knowledge similarities come from the database and
match Python's cosine on the same float32 bytes. Skips without a postgresql:// DATABASE_URL (and without the extension)."""
import array, math, os, random, tempfile, unittest

from app import db_pg, vector_pg
from app.knowledge_media import _pack, cosine


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Off(unittest.TestCase):
    def test_not_ready_on_sqlite(self):
        if db_pg.enabled(): self.skipTest("on Postgres")
        from app.auth import AuthDB
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(vector_pg.ready(AuthDB(os.path.join(d, "a.db"))))

    def test_literal(self):
        self.assertEqual(vector_pg.literal([0.5, -1, 1e-9]), "[0.5,-1,1e-09]")


@unittest.skipUnless(db_pg.enabled(), "DATABASE_URL isn't a postgresql:// URL")
class Live(unittest.TestCase):
    def setUp(self):
        from app.auth import AuthDB
        self.dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_SCHEMA_PER_PATH"] = "1"
        self.db = AuthDB(os.path.join(self.dir.name, "v.db"))
        self.db.q("CREATE TABLE IF NOT EXISTS kb_vectors (item_id INTEGER PRIMARY KEY, user_id INTEGER, model TEXT, sha TEXT, vec BLOB, updated REAL)")
        if not vector_pg.ready(self.db): self.skipTest("no pgvector in this Postgres")

    def tearDown(self):
        self.db.db.execute(f'DROP SCHEMA IF EXISTS "{self.db.db.schema}" CASCADE')
        self.dir.cleanup()

    def test_similarities_match_python(self):
        rnd = random.Random(7)
        vecs = {i: unit([rnd.uniform(-1, 1) for _ in range(256)]) for i in range(1, 21)}
        for i, v in vecs.items():
            self.db.q("INSERT OR REPLACE INTO kb_vectors (item_id, user_id, model, sha, vec, updated) VALUES (?,?,?,?,?,?)", (i, 5, "m", "h", _pack(v), 0))
        self.db.q("INSERT INTO kb_vectors (item_id, user_id, model, sha, vec, updated) VALUES (?,?,?,?,?,?)", (99, 6, "m", "h", _pack(vecs[1]), 0))
        q = unit([rnd.uniform(-1, 1) for _ in range(256)])
        got = vector_pg.sims(self.db, "kb_vectors", "item_id", "user_id=? AND model=?", (5, "m"), q)
        self.assertEqual(set(got), set(vecs))  # only that user's rows
        f32 = {i: array.array("f", v) for i, v in vecs.items()}  # what Python compares: the stored float32 values
        for i in vecs: self.assertAlmostEqual(got[i], cosine(q, f32[i]), places=4)
        self.assertEqual(set(vector_pg.sims(self.db, "kb_vectors", "item_id", "user_id=?", (5,), q, keys=[3, 4])), {3, 4})
        # a vector rewritten through INSERT OR REPLACE is decoded again
        self.db.q("INSERT OR REPLACE INTO kb_vectors (item_id, user_id, model, sha, vec, updated) VALUES (?,?,?,?,?,?)", (2, 5, "m", "h", _pack(q), 1))
        self.assertAlmostEqual(vector_pg.sims(self.db, "kb_vectors", "item_id", "user_id=?", (5,), q, keys=[2])[2], 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
