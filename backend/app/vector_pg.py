"""pgvector for Knowledge search on Postgres (5.1: the spec's "Vector database: pgvector").

On SQLite, AXoR keeps vectors as float32 bytes (knowledge_media._pack) and compares them in Python: every search loads the
user's vectors into the process. On Postgres with the vector extension (the k8s Postgres image is pgvector/pgvector), the
vector tables get a generated column

    emb vector GENERATED ALWAYS AS (axor_compat.f32vec(vec)) STORED

decoded from the same bytes, so nothing that writes vectors changes, and the search asks Postgres for the cosine
similarities instead (1 - (emb <=> query)): the vectors never leave the database. Each search is an exact scan of one user's
rows for one embedding model. No HNSW index yet: an index needs a fixed dimension, and the model (and so the dimension) is a
setting. Without the extension, or on SQLite, ready() is False and search works as before.

KNOWLEDGE_PGVECTOR=0 turns it off on Postgres too.
"""
import logging, os, threading

from . import db_pg

log = logging.getLogger("vector_pg")
TABLES = ("kb_vectors", "kb_chunk_vecs", "ex_vecs")
ON = os.getenv("KNOWLEDGE_PGVECTOR", "1") != "0"

# Its own search_path: the body's `::vector` resolves at run time, and pg_restore (empty search_path) re-computes the generated
# emb columns through it; without this a dump of the database doesn't restore (found by k8s/backup.sh --verify, 2026-11-11).
_F32VEC = """CREATE OR REPLACE FUNCTION axor_compat.f32vec(b bytea) RETURNS vector LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
SET search_path TO axor_compat, public AS $$
DECLARE
  n int := length(b) / 4; out float4[] := array_fill(0::float4, ARRAY[n]); u bigint; e int; m bigint; v double precision;
BEGIN
  IF n = 0 THEN RETURN NULL; END IF;
  FOR i IN 0 .. n - 1 LOOP
    u := get_byte(b, 4 * i)::bigint | (get_byte(b, 4 * i + 1)::bigint << 8) | (get_byte(b, 4 * i + 2)::bigint << 16) | (get_byte(b, 4 * i + 3)::bigint << 24);
    e := ((u >> 23) & 255)::int; m := u & 8388607;
    IF e = 0 THEN v := m * 2.0 ^ (-149); ELSIF e = 255 THEN v := 0; ELSE v := (1 + m / 8388608.0) * 2.0 ^ (e - 127); END IF;
    IF (u >> 31) = 1 THEN v := -v; END IF;
    out[i + 1] := v;
  END LOOP;
  RETURN out::vector;
END $$"""

_state = {}
_lock = threading.Lock()


def ready(db):
    """True when this database searches with pgvector (Postgres + the vector extension + the emb columns made)."""
    if not ON or not db_pg.enabled() or not isinstance(db.db, db_pg.Connection): return False
    key = id(db.db)
    with _lock:
        if key in _state: return _state[key]
    ok = False
    try:
        with db.lock:
            c = db.db
            # the extension lives in axor_compat, which every AXoR connection has on its search_path (whatever its own schema)
            where = c.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").fetchone()
            try:
                if not where: c._c.cursor().execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA axor_compat")
                elif where[0] not in ("axor_compat", "public"): c._c.cursor().execute("ALTER EXTENSION vector SET SCHEMA axor_compat")
            except Exception as e:  # noqa: BLE001 - not available in this Postgres, or no right to create it
                log.info("pgvector unavailable (%s): Knowledge search compares vectors in Python", e)
                raise
            c._c.cursor().execute(_F32VEC)  # raw: plpgsql bodies aren't SQLite SQL
            for t in TABLES:
                if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
                    c._c.cursor().execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS emb vector GENERATED ALWAYS AS (axor_compat.f32vec(vec)) STORED")
            c._pk.clear(); c._cols.clear()
        ok = True
        log.info("pgvector: Knowledge search runs in Postgres")
    except Exception:  # noqa: BLE001
        ok = False
    with _lock: _state[key] = ok
    return ok


def literal(qv):
    """A query vector as pgvector's text form."""
    return "[" + ",".join(f"{float(x):.7g}" for x in qv) + "]"


def sims(db, frm, key, where, args, qv, keys=None):
    """{key: cosine similarity} over `SELECT … FROM frm WHERE where`, computed by Postgres; keys narrows to those ids."""
    extra, extra_args = "", ()
    if keys is not None:
        keys = list(keys)
        if not keys: return {}
        extra, extra_args = f" AND {key} IN ({','.join('?' * len(keys))})", tuple(keys)
    rows = db.q(f"SELECT {key} AS k, 1 - (emb <=> CAST(? AS vector)) AS s FROM {frm} WHERE {where} AND emb IS NOT NULL{extra}",
                (literal(qv), *args, *extra_args))
    return {r["k"]: float(r["s"]) for r in rows}
