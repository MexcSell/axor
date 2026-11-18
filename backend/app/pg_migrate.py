"""Copy AXoR's SQLite database (auth.db) into Postgres: the data step of the 5.1 migration (db_pg.py is the code step).

    python -m app.pg_migrate --sqlite /data/auth.db --url postgresql://axor:…@postgres:5432/axor [--schema public] [--dry-run] [--force]

Run it inside the web image (k8s/stack.sh migrate does: the web pod has the database file and pg8000), with AXoR stopped or
in maintenance, so nothing writes to the SQLite file while it copies. What it does:

1. Reads every table and index of the SQLite file (read-only; it never writes to it).
2. Creates each table in the target schema from its own CREATE statement, through the same translation AXoR uses at run
   time (db_pg.Translator), so the tables are exactly the ones AXoR would have created; then the indexes.
   The FTS5 index (kb_fts) becomes its tsvector table and is copied too; FTS5's shadow tables are skipped.
3. Copies the rows in batches. A row Postgres refuses (a value SQLite's loose typing let into a column of another type)
   is reported and skipped; --strict stops at the first one instead.
4. Moves every id sequence past its table's MAX(id), then compares row counts table by table.

It refuses a target schema that already has rows in any table it would copy, unless --force (then those tables are emptied
first). Exit status: 0 when every table's row count matches, 1 otherwise. Afterwards set DATABASE_URL (k8s/stack.sh enable).
The metrics history (scout.db) stays on SQLite: it's a cache the collector refills.
"""
import argparse, os, re, sqlite3, sys, time

from . import db_pg

FTS_SHADOW = ("_data", "_idx", "_content", "_docsize", "_config")
BATCH = 500


def plan(src):
    """[(name, create sql, kind)] tables in creation order, and [index sql]."""
    rows = src.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY rowid").fetchall()
    virtual = {r[1] for r in rows if r[0] == "table" and re.match(r"\s*CREATE\s+VIRTUAL", r[3], re.I)}
    shadow = {f"{v}{s}" for v in virtual for s in FTS_SHADOW}
    tables = [(r[1], r[3], "fts" if r[1] in virtual else "table") for r in rows
              if r[0] == "table" and not r[1].startswith("sqlite_") and r[1] not in shadow]
    indexes = [r[3] for r in rows if r[0] == "index" and r[2] not in shadow and r[2] not in virtual]
    return tables, indexes


def _ifnot(sql):
    return re.sub(r"^\s*CREATE\s+(UNIQUE\s+)?(TABLE|INDEX|VIRTUAL\s+TABLE)\s+(?!IF\s+NOT\s+EXISTS)", lambda m: m.group(0) + "IF NOT EXISTS ", sql, flags=re.I)


def migrate(sqlite_path, url, schema=None, dry=False, force=False, strict=False, out=print):
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    tables, indexes = plan(src)
    counts = {t: src.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t, _, _ in tables}
    out(f"source {sqlite_path}: {len(tables)} tables, {len(indexes)} indexes, {sum(counts.values()):,} rows")
    if dry:
        for t, _, k in tables: out(f"  {t:<40} {counts[t]:>10,}{'  (full-text index)' if k == 'fts' else ''}")
        return True
    if schema: os.environ["DATABASE_SCHEMA"] = schema
    dst = db_pg.Connection(url)
    out(f"target schema {dst.schema}")
    raw = dst._c
    have = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    busy = [t for t, _, _ in tables if t.lower() in have and dst.execute(f'SELECT COUNT(*) FROM "{t.lower()}"').fetchone()[0]]
    if busy and not force:
        out(f"refusing: {len(busy)} target table(s) already have rows ({', '.join(busy[:6])}{'…' if len(busy) > 6 else ''}); --force empties them first")
        return False
    for t, sql, _ in tables:
        dst.execute(_ifnot(sql))
        if t in busy: dst.execute(f'DELETE FROM "{t.lower()}"')
    for sql in indexes:
        try: dst.execute(_ifnot(sql))
        except sqlite3.OperationalError as e: out(f"  index skipped: {e}")
    ok, started = True, time.time()
    for t, _, kind in tables:
        cols = ["rowid"] + db_pg._FTS_TABLES.get(t, []) + [c for c in dst.columns(t) if c not in ("rowid", "tsv", *db_pg._FTS_TABLES.get(t, []))] \
            if kind == "fts" else [r[1] for r in src.execute(f'PRAGMA table_info("{t}")')]
        sel = ", ".join(f'"{c}"' for c in cols)
        dcols = ", ".join(f'"{c.lower()}"' for c in cols)
        ins = f'INSERT INTO "{t.lower()}" ({dcols}) VALUES ({", ".join("?" * len(cols))})'
        n = skipped = 0
        cur = src.execute(f'SELECT {sel} FROM "{t}"')
        while True:
            rows = cur.fetchmany(BATCH)
            if not rows: break
            pc = raw.cursor()
            params = [[db_pg._param(v) for v in r] for r in rows]
            try:
                raw.autocommit = False
                pc.executemany(ins, params)
                raw.commit()
                n += len(rows)
            except db_pg._pg_errors() as e:
                raw.rollback()
                raw.autocommit = True
                for r, p in zip(rows, params):  # one by one: keep what fits, report what doesn't
                    try:
                        raw.cursor().execute(ins, p); n += 1
                    except db_pg._pg_errors() as e1:
                        skipped += 1
                        out(f"  {t}: row skipped ({db_pg._err(e1, ins)})"[:300])
                        if strict: raise SystemExit(1)
            finally:
                raw.autocommit = True
        if "id" in [c.lower() for c in cols] and kind != "fts":
            sc = raw.cursor()
            sc.execute("SELECT pg_get_serial_sequence(?, 'id')", (t.lower(),))
            seq = sc.fetchone()[0]
            if seq: sc.execute(f'SELECT setval(?, (SELECT COALESCE(MAX(id), 0) + 1 FROM "{t.lower()}"), false)', (seq,))
        got = dst.execute(f'SELECT COUNT(*) FROM "{t.lower()}"').fetchone()[0]
        match = got == counts[t]
        ok &= match
        out(f"  {t:<40} {counts[t]:>10,} → {got:>10,}{'' if match else '  MISMATCH'}{f'  ({skipped} skipped)' if skipped else ''}")
    out(f"{'done' if ok else 'done with mismatches'} in {time.time() - started:.1f}s")
    return ok


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.pg_migrate", description="Copy AXoR's SQLite database into Postgres.")
    p.add_argument("--sqlite", default=os.path.join(os.getenv("DATA_DIR", "/data"), "auth.db"))
    p.add_argument("--url", default=os.getenv("DATABASE_URL", ""), help="postgresql://user:pass@host:5432/db (default: $DATABASE_URL)")
    p.add_argument("--schema", default=None, help="target schema (default: the URL's ?schema= or public)")
    p.add_argument("--dry-run", action="store_true", help="list the tables and row counts, connect nowhere")
    p.add_argument("--force", action="store_true", help="empty target tables that already have rows")
    p.add_argument("--strict", action="store_true", help="stop at the first row Postgres refuses")
    a = p.parse_args(argv)
    if not os.path.exists(a.sqlite): p.error(f"no SQLite file at {a.sqlite}")
    if not a.dry_run and not a.url.startswith(("postgres://", "postgresql://")): p.error("--url (or DATABASE_URL) must be a postgresql:// URL")
    return 0 if migrate(a.sqlite, a.url, a.schema, a.dry_run, a.force, a.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
