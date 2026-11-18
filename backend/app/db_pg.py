"""PostgreSQL backend for AXoR's database (5.1: the spec's stack, step 1 of the incremental migration).

AXoR grew up on one SQLite file (auth.db) that ~130 modules query through AuthDB.q() and, here and there, AuthDB.db.execute().
Set DATABASE_URL=postgresql://user:pass@host:5432/dbname and AuthDB opens this connection instead: a sqlite3-shaped object
(execute / executemany / executescript / commit / rollback / cursor.description / fetchone / fetchall / lastrowid), so none of
the ~3,400 call sites change. Unset, AXoR stays on SQLite exactly as before.

What it does to the SQL (translate(), cached per statement text):
- Placeholders stay `?` (pg8000's qmark style). Strings, ints and bools go to the server untyped, so Postgres infers them from
  the column, as SQLite's type affinity did; floats go as float8 (an assignment cast rounds them into BIGINT columns).
- DDL: INTEGER PRIMARY KEY [AUTOINCREMENT] -> BIGSERIAL PRIMARY KEY, INTEGER -> BIGINT, REAL -> DOUBLE PRECISION, BLOB -> BYTEA,
  untyped columns -> TEXT, COLLATE NOCASE and WITHOUT ROWID dropped (logins are lower-cased before they're stored anyway).
- INSERT OR IGNORE -> ON CONFLICT DO NOTHING; INSERT OR REPLACE / REPLACE INTO -> ON CONFLICT (primary key) DO UPDATE.
- LIKE -> ILIKE (SQLite's LIKE ignores ASCII case), x IS ? -> IS NOT DISTINCT FROM, MAX(a, b) / MIN(a, b) -> GREATEST / LEAST,
  GROUP_CONCAT -> string_agg, last_insert_rowid() -> lastval(), PRAGMA table_info -> information_schema, other PRAGMAs -> no-op.
- sqlite_master is a view (tables and indexes of the current schema); json_extract and round(float, n) are compat functions.
- The FTS5 table (kb_fts, Knowledge RAG) becomes a table with a generated tsvector + GIN index; MATCH -> @@, bm25() -> -ts_rank.
Results: Decimal -> int/float, bool -> 0/1, memoryview -> bytes, like sqlite3 returns them.
Errors: unique/foreign-key violations raise sqlite3.IntegrityError, everything else sqlite3.OperationalError, with SQLite's
wording for the two messages code checks ("duplicate column name", "no such table").

Transactions: the connection runs in autocommit (each statement commits). AuthDB's lock already serialises the process's
statements; the few multi-statement blocks (company approvals, the RAG chunk writer) keep their lock but not all-or-nothing
atomicity on Postgres. AuthDB.tx() (G5-2.2 Milestone 3) is a real transaction: begin() sends BEGIN and takes an advisory
transaction lock, commit()/rollback() end it; inside it a lost connection or a failed statement raises (never a reconnect or a
retry into the middle of it). Several server processes on one database are not supported yet (leases and claims assume one).

Not translated, and it raises loudly rather than guessing: SQLite-only GROUP BY looseness (a bare column next to an aggregate),
double-quoted string literals. tests/unit run against Postgres with DATABASE_URL set (see k8s/postgres/README.md).
"""
import decimal, hashlib, logging, os, re, sqlite3, threading
from urllib.parse import parse_qs, unquote, urlparse

log = logging.getLogger("db_pg")
URL = os.getenv("DATABASE_URL", "").strip()
COMPAT = "axor_compat"


def enabled():
    return URL.startswith(("postgres://", "postgresql://"))


def describe():
    """Where the database lives, without the password: for /api/health and the Settings page."""
    if not enabled(): return {"engine": "sqlite"}
    u = urlparse(URL)
    return {"engine": "postgres", "host": u.hostname, "port": u.port or 5432, "database": (u.path or "/").lstrip("/"),
            "schema": _schema_from_url(u, None)}


def _schema_from_url(u, path):
    q = parse_qs(u.query)
    if os.getenv("DATABASE_SCHEMA_PER_PATH") == "1" and path:  # tests: every AuthDB(path) gets its own schema
        return "t_" + hashlib.sha1(os.path.abspath(str(path)).encode()).hexdigest()[:20]
    return (q.get("schema") or [os.getenv("DATABASE_SCHEMA", "public")])[0]


# ---------------------------------------------------------------- SQL translation
_LIT = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.S)
_TYPES = [(re.compile(r"\bINTEGER\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?\b", re.I), "BIGSERIAL PRIMARY KEY"),
          (re.compile(r"\bAUTOINCREMENT\b", re.I), ""),
          (re.compile(r"\b(?:INTEGER|INT|BOOLEAN|BOOL)\b", re.I), "BIGINT"),
          (re.compile(r"\b(?:REAL|FLOAT|DOUBLE|NUMERIC)\b(?!\s+PRECISION)", re.I), "DOUBLE PRECISION"),
          (re.compile(r"\bBLOB\b", re.I), "BYTEA"),
          (re.compile(r"\b(?:JSON|DATETIME|TIMESTAMP)\b", re.I), "TEXT"),
          (re.compile(r"\s+COLLATE\s+NOCASE\b", re.I), ""),
          (re.compile(r"\)\s*WITHOUT\s+ROWID\s*$", re.I), ")")]
_CONSTRAINT_WORDS = {"PRIMARY", "NOT", "NULL", "DEFAULT", "UNIQUE", "REFERENCES", "CHECK", "COLLATE", "GENERATED", "CONSTRAINT"}
_TABLE_LEVEL = ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT")


def _mask(sql):
    """(sql with literals/comments replaced by \x00N\x00, the literals) so rewrites never touch text inside quotes."""
    lits = []
    def keep(m):
        s = m.group(0)
        if s.startswith(("--", "/*")): return " "
        lits.append(s); return f"\x00{len(lits) - 1}\x00"
    return _LIT.sub(keep, sql), lits


def _unmask(sql, lits):
    return re.sub(r"\x00(\d+)\x00", lambda m: lits[int(m.group(1))], sql)


def _split_top(s, sep=","):
    """Split on `sep` outside parentheses."""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        if ch == sep and depth == 0: out.append("".join(cur)); cur = []
        else: cur.append(ch)
    out.append("".join(cur))
    return out


def _paren_end(s, i):
    """Index of the ')' matching the '(' at s[i]."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(": depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0: return j
    raise sqlite3.OperationalError(f"unbalanced parentheses in: {s[:200]}")


def split_statements(sql):
    m, lits = _mask(sql)
    return [_unmask(p, lits).strip() for p in m.split(";") if p.strip()]


def _coldef(item):
    t = item.strip()
    if not t or t.split()[0].upper() in _TABLE_LEVEL: return item
    words = t.split()
    if len(words) == 1 or words[1].upper().rstrip(",") in _CONSTRAINT_WORDS:
        return item.replace(words[0], words[0] + " TEXT", 1)
    return item


def _ddl_types(s):
    for rx, rep in _TYPES: s = rx.sub(rep, s)
    return s


def _create_table(m):
    i = m.index("(")
    j = _paren_end(m, i)
    body = ",".join(_coldef(x) for x in _split_top(m[i + 1:j]))
    return _ddl_types(m[:i + 1] + body + m[j:])


def _func_rewrite(s, name, fn):
    """Rewrite every NAME(args) call (outermost first, then inside) with fn(args_list) -> replacement or None to keep."""
    rx = re.compile(r"\b" + name + r"\s*\(", re.I)
    pos = 0
    while (mm := rx.search(s, pos)):
        i = s.index("(", mm.start())
        j = _paren_end(s, i)
        args = _split_top(s[i + 1:j])
        rep = fn([a.strip() for a in args])
        if rep is None: pos = j; continue
        s = s[:mm.start()] + rep + s[j + 1:]
        pos = mm.start() + 1
    return s


def _fts_create(m):
    """CREATE VIRTUAL TABLE [IF NOT EXISTS] t USING fts5(c1, c2 UNINDEXED, ..., tokenize=...) -> table + tsvector + GIN."""
    mm = re.match(r"\s*CREATE\s+VIRTUAL\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?(\w+)\s+USING\s+fts5\s*\((.*)\)\s*$", m, re.I | re.S)
    if not mm: raise sqlite3.OperationalError("virtual tables other than fts5 aren't supported on Postgres")
    name, cols = mm.group(2), [c.strip() for c in _split_top(mm.group(3))]
    text, plain = [], []
    for c in cols:
        if "=" in c: continue
        w = c.split()
        (plain if len(w) > 1 and w[1].upper() == "UNINDEXED" else text).append(w[0])
    weights = "ABCD"
    tsv = " || ".join(f"setweight(to_tsvector('english', coalesce({c}, '')), '{weights[min(3, len(text) - 1 - k)]}')"
                      for k, c in enumerate(text))
    defs = ", ".join([f"rowid BIGINT PRIMARY KEY"] + [f"{c} TEXT" for c in text] + [f"{c} BIGINT" for c in plain]
                     + [f"tsv tsvector GENERATED ALWAYS AS ({tsv}) STORED"])
    _FTS_TABLES[name] = text
    return [f"CREATE TABLE IF NOT EXISTS {name} ({defs})", f"CREATE INDEX IF NOT EXISTS {name}_tsv ON {name} USING GIN (tsv)"]


_FTS_TABLES = {"kb_fts": ["text", "title"]}


_KW_END = re.compile(r"\b(FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|WINDOW|UNION|EXCEPT|INTERSECT)\b", re.I)
_SIMPLE_COL = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)?$")
_AGG = re.compile(r"\b(COUNT|SUM|MAX|MIN|AVG|TOTAL|GROUP_CONCAT|string_agg|GREATEST|LEAST|bool_or|bool_and)\s*\(", re.I)


def _top_clauses(m):
    """{keyword: (start, end)} of the outermost SELECT's clauses (depth 0), or None when it isn't a plain SELECT."""
    if not re.match(r"\s*SELECT\b", m, re.I): return None
    depth, marks = 0, []
    i = 0
    while i < len(m):
        ch = m[i]
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        elif depth == 0 and (i == 0 or not (m[i - 1].isalnum() or m[i - 1] == "_")):
            k = _KW_END.match(m, i)
            if k:
                marks.append((re.sub(r"\s+", " ", k.group(1).upper()), k.start(), k.end())); i = k.end(); continue
        i += 1
    if any(k in ("UNION", "EXCEPT", "INTERSECT") for k, _, _ in marks): return None
    out = {"SELECT": (len(re.match(r"\s*SELECT\s+(DISTINCT\s+)?", m, re.I).group(0)), marks[0][1] if marks else len(m))}
    for n, (k, a, b) in enumerate(marks):
        out[k] = (b, marks[n + 1][1] if n + 1 < len(marks) else len(m))
    return out


def _loose_group_by(m):
    """SQLite lets a bare column sit next to an aggregate without being grouped (it takes any row's value); Postgres refuses.
    Wrap such columns of the outermost SELECT in MAX() under their own name, and let HAVING use the select list's aliases."""
    cl = _top_clauses(m)
    if not cl or "GROUP BY" not in cl: return m
    a, b = cl["SELECT"]
    items = _split_top(m[a:b])
    ga, gb = cl["GROUP BY"]
    groups = {re.sub(r"\s+", "", g).lower() for g in _split_top(m[ga:gb])}
    gbare = {g.split(".")[-1] for g in groups}
    aliases, new = {}, []
    for it in items:
        mm = re.match(r"^(\s*)(.*?)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?(\s*)$", it, re.S | re.I)
        lead, expr, alias, trail = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
        if alias and alias.upper() in ("DESC", "ASC", "END", "NULL"): expr, alias = f"{expr} {alias}", None
        if alias and _AGG.search(expr): aliases[alias.lower()] = expr
        e = expr.strip()
        if _SIMPLE_COL.match(e) and e.lower() not in groups and e.split(".")[-1].lower() not in gbare and e != "*" and not e.endswith(".*"):
            new.append(f"{lead}MAX({e}) AS {alias or e.split('.')[-1]}{trail}")
        else:
            new.append(it)
    m = m[:a] + ",".join(new) + m[b:]
    cl = _top_clauses(m)
    if "HAVING" in cl and aliases:
        ha, hb = cl["HAVING"]
        h = re.sub(r"(?<![\w.])([A-Za-z_]\w*)(?![\w(])", lambda x: f"({aliases[x.group(1).lower()]})" if x.group(1).lower() in aliases else x.group(1), m[ha:hb])
        m = m[:ha] + h + m[hb:]
    return m


def _loose_group_by_all(m):
    """_loose_group_by on every (SELECT …) subquery, innermost first, then on the statement itself."""
    starts = [x.start() for x in re.finditer(r"\(\s*SELECT\b", m, re.I)]
    for i in reversed(starts):
        j = _paren_end(m, i)
        inner = m[i + 1:j]
        if re.search(r"\bGROUP\s+BY\b", inner, re.I): m = m[:i + 1] + _loose_group_by(inner) + m[j:]
    return _loose_group_by(m) if re.match(r"\s*SELECT\b", m, re.I) else m


_RESERVED_COLS = re.compile(r"(?<![\w\"])(end|user|window)(?![\w\"(])")  # Postgres reserves them; SQLite lets them be column names

def _placeholders(s):
    return [k.start() for k in re.finditer(r"\?", s)]


class Translator:
    def __init__(self, conn):
        self.conn = conn
        self.cache, self.lock = {}, threading.Lock()

    def __call__(self, sql):
        """[(postgres sql, param index list or None = params as given)] for one SQLite statement."""
        with self.lock:
            hit = self.cache.get(sql)
        if hit is not None: return hit
        out = self._translate(sql)
        if not re.match(r"\s*(CREATE|ALTER|DROP)\b", sql, re.I):  # DDL runs once; DML repeats
            with self.lock:
                if len(self.cache) > 5000: self.cache.clear()
                self.cache[sql] = out
        return out

    def _translate(self, sql):
        m, lits = _mask(sql)
        m = m.strip().rstrip(";").strip()
        head = m[:40].upper()
        if head.startswith("PRAGMA"):
            ti = re.match(r"PRAGMA\s+table_info\s*\(\s*(\w+)\s*\)", m, re.I)
            if not ti: return [("SELECT 1 WHERE false", None)]
            t = ti.group(1)
            return [(f"""SELECT a.attnum - 1 AS cid, a.attname::text AS name, format_type(a.atttypid, a.atttypmod) AS type,
                         a.attnotnull::int AS notnull, pg_get_expr(d.adbin, d.adrelid) AS dflt_value,
                         COALESCE((SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY(i.indkey)), 0) AS pk
                       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                       LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
                      WHERE n.nspname = current_schema() AND c.relname = '{t.lower()}' ORDER BY a.attnum""", None)]
        if re.match(r"CREATE\s+VIRTUAL\s+TABLE", m, re.I):
            return [(s, None) for s in _fts_create(_unmask(m, lits))]
        if re.match(r"CREATE\s+(TEMP\s+|TEMPORARY\s+)?TABLE", m, re.I) and "(" in m and not re.search(r"\bAS\s+SELECT\b", m, re.I):
            m = _create_table(m)
        elif re.match(r"ALTER\s+TABLE\s+\w+\s+ADD\s+(COLUMN\s+)?", m, re.I):
            mm = re.match(r"(ALTER\s+TABLE\s+\w+\s+ADD\s+(?:COLUMN\s+)?)(.*)$", m, re.I | re.S)
            m = mm.group(1) + _ddl_types(_coldef(mm.group(2)))
        pmap = None
        # INSERT OR IGNORE / OR REPLACE / REPLACE INTO
        ins = re.match(r"(INSERT\s+OR\s+(IGNORE|REPLACE)|REPLACE)\s+INTO\s+(\w+)", m, re.I)
        if ins:
            mode = "IGNORE" if (ins.group(2) or "").upper() == "IGNORE" else "REPLACE"
            table = ins.group(3)
            m = "INSERT INTO " + table + m[ins.end():]
            ret = re.search(r"\bRETURNING\b", m, re.I)
            tail = m[ret.start():] if ret else ""
            core = m[:ret.start()] if ret else m
            if mode == "IGNORE":
                clause = " ON CONFLICT DO NOTHING "
            else:
                cm = re.match(r"INSERT\s+INTO\s+\w+\s*\(([^)]*)\)", core, re.I)
                cols = [c.strip() for c in cm.group(1).split(",")] if cm else self.conn.columns(table)
                pk = self.conn.conflict_key(table)
                if not pk: raise sqlite3.OperationalError(f"INSERT OR REPLACE into {table}: the table has no primary key or unique index")
                rest = [c for c in cols if c.lower() not in {p.lower() for p in pk}]
                clause = (f" ON CONFLICT ({', '.join(pk)}) DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in rest) + " ") if rest \
                    else f" ON CONFLICT ({', '.join(pk)}) DO NOTHING "
            m = core.rstrip() + clause + tail
        # expressions
        m = _RESERVED_COLS.sub(r'"\1"', m)  # columns named end / user / window: lowercase in AXoR's SQL, the keywords are always upper case
        if re.search(r"\bGROUP\s+BY\b", m, re.I): m = _loose_group_by_all(m)
        m = re.sub(r"(?<![\w.])LIKE\b", "ILIKE", m, flags=re.I)
        m = re.sub(r"\bLIMIT\s+-\s*1\b", "LIMIT ALL", m, flags=re.I)  # SQLite's "no limit" (with OFFSET)
        m = re.sub(r"\?(\s+IS\s+(?:NOT\s+)?NULL\b)", r"CAST(? AS TEXT)\1", m, flags=re.I)  # an untyped parameter alone has no type
        m = re.sub(r"\bIS\s+NOT\s+\?", "IS DISTINCT FROM ?", m, flags=re.I)
        m = re.sub(r"\bIS\s+\?", "IS NOT DISTINCT FROM ?", m, flags=re.I)
        m = re.sub(r"\blast_insert_rowid\s*\(\s*\)", "lastval()", m, flags=re.I)
        m = re.sub(r"\bCAST\s*\(([^()]*?)\s+AS\s+REAL\s*\)", r"CAST(\1 AS DOUBLE PRECISION)", m, flags=re.I)
        m = re.sub(r"\bCAST\s*\(([^()]*?)\s+AS\s+INTEGER\s*\)", r"CAST(\1 AS BIGINT)", m, flags=re.I)
        m = _func_rewrite(m, "MAX", lambda a: f"GREATEST({', '.join(a)})" if len(a) > 1 else None)
        m = _func_rewrite(m, "MIN", lambda a: f"LEAST({', '.join(a)})" if len(a) > 1 else None)
        def gc(a):
            x = a[0]
            d = ""
            if re.match(r"DISTINCT\s", x, re.I): d, x = "DISTINCT ", x[9:].strip()
            return f"string_agg({d}({x})::text, {a[1] if len(a) > 1 else chr(39) + ',' + chr(39)})"
        m = _func_rewrite(m, "GROUP_CONCAT", gc)
        # FTS5: t MATCH ? -> t.tsv @@ fts5_query(?), bm25(t, ...) -> -ts_rank(t.tsv, fts5_query(<the MATCH param>))
        for t in _FTS_TABLES:
            mt = re.search(r"\b" + t + r"\s+MATCH\s+\?", m, re.I)
            if not mt: continue
            match_idx = len(_placeholders(m[:mt.start()]))
            m = m[:mt.start()] + f"{t}.tsv @@ {COMPAT}.fts5_query(?)" + m[mt.end():]
            bm = re.search(r"\bbm25\s*\(\s*" + t + r"\b[^)]*\)", m, re.I)
            if bm:
                n_before = len(_placeholders(m[:bm.start()]))
                m = m[:bm.start()] + f"(-ts_rank({t}.tsv, {COMPAT}.fts5_query(?)))" + m[bm.end():]
                total = len(_placeholders(m))
                # new placeholder at position n_before takes the MATCH param (which shifted one to the right if it came after)
                orig = list(range(total - 1))
                src = match_idx
                pmap = orig[:n_before] + [src] + orig[n_before:]
        return [(_unmask(m, lits), pmap)]


# ---------------------------------------------------------------- connection
_COMPAT_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {COMPAT};
CREATE OR REPLACE VIEW {COMPAT}.sqlite_master AS
  SELECT 'table'::text AS type, c.relname::text AS name, c.relname::text AS tbl_name, NULL::text AS sql
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p', 'v')
  UNION ALL
  SELECT 'index', ci.relname::text, ct.relname::text, NULL FROM pg_index i JOIN pg_class ci ON ci.oid = i.indexrelid
    JOIN pg_class ct ON ct.oid = i.indrelid JOIN pg_namespace n ON n.oid = ct.relnamespace WHERE n.nspname = current_schema();
CREATE OR REPLACE FUNCTION {COMPAT}.json_extract(doc text, path text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN doc IS NULL OR doc !~ '^\\s*[\\[{{]' THEN NULL
              ELSE (doc::jsonb) #>> string_to_array(regexp_replace(substr(path, 3), '\\[(\\d+)\\]', '.\\1', 'g'), '.') END $$;
CREATE OR REPLACE FUNCTION {COMPAT}.round(x double precision, n integer) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$
  SELECT round(x::numeric, n)::double precision $$;
CREATE OR REPLACE FUNCTION {COMPAT}.round(x double precision, n bigint) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$
  SELECT round(x::numeric, n::int)::double precision $$;
CREATE OR REPLACE FUNCTION {COMPAT}.instr(s text, sub text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$ SELECT strpos(s, sub) $$;
CREATE OR REPLACE FUNCTION {COMPAT}.ifnull(a anyelement, b anyelement) RETURNS anyelement LANGUAGE sql IMMUTABLE AS $$ SELECT coalesce(a, b) $$;
CREATE OR REPLACE FUNCTION {COMPAT}._bsum(s bigint, b boolean) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN b IS NULL THEN s ELSE coalesce(s, 0) + b::int END $$;
CREATE OR REPLACE FUNCTION {COMPAT}._bmax(s bigint, b boolean) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN b IS NULL THEN s ELSE greatest(coalesce(s, 0), b::int) END $$;
CREATE OR REPLACE FUNCTION {COMPAT}._bmin(s bigint, b boolean) RETURNS bigint LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN b IS NULL THEN s ELSE least(coalesce(s, 1), b::int) END $$;
CREATE OR REPLACE FUNCTION {COMPAT}._bavg(s double precision[], b boolean) RETURNS double precision[] LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN b IS NULL THEN s ELSE ARRAY[coalesce(s[1], 0) + b::int, coalesce(s[2], 0) + 1] END $$;
CREATE OR REPLACE FUNCTION {COMPAT}._bavgf(s double precision[]) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN s IS NULL OR s[2] = 0 THEN NULL ELSE s[1] / s[2] END $$;
CREATE OR REPLACE FUNCTION {COMPAT}._total(s double precision, x double precision) RETURNS double precision LANGUAGE sql IMMUTABLE AS $$
  SELECT s + coalesce(x, 0) $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = '{COMPAT}' AND p.proname = 'sum') THEN
    CREATE AGGREGATE {COMPAT}.sum(boolean) (sfunc = {COMPAT}._bsum, stype = bigint);
    CREATE AGGREGATE {COMPAT}.max(boolean) (sfunc = {COMPAT}._bmax, stype = bigint);
    CREATE AGGREGATE {COMPAT}.min(boolean) (sfunc = {COMPAT}._bmin, stype = bigint);
    CREATE AGGREGATE {COMPAT}.avg(boolean) (sfunc = {COMPAT}._bavg, stype = double precision[], finalfunc = {COMPAT}._bavgf);
    CREATE AGGREGATE {COMPAT}.total(double precision) (sfunc = {COMPAT}._total, stype = double precision, initcond = '0');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_collation c JOIN pg_namespace n ON n.oid = c.collnamespace WHERE n.nspname = '{COMPAT}' AND c.collname = 'nocase') THEN
    BEGIN
      CREATE COLLATION {COMPAT}.nocase (provider = icu, locale = 'und-u-ks-level2', deterministic = false);
    EXCEPTION WHEN OTHERS THEN
      CREATE COLLATION {COMPAT}.nocase FROM "C";
    END;
  END IF;
END $$;
CREATE OR REPLACE FUNCTION {COMPAT}.fts5_query(q text) RETURNS tsquery LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN coalesce(string_agg(w, ' | '), '') = '' THEN NULL::tsquery ELSE to_tsquery('english', string_agg(w, ' | ')) END
    FROM (SELECT DISTINCT m[1] || CASE WHEN m[2] = '*' THEN ':*' ELSE '' END AS w
            FROM regexp_matches(lower(q), '([a-z0-9_]+)"?(\\*?)', 'g') AS m
           WHERE m[1] NOT IN ('or', 'and', 'not', 'near')) words $$;
"""

_compat_lock = threading.Lock()
_compat_done = set()


class Cursor:
    def __init__(self, conn, cur=None, lastrowid=None):
        self._conn, self._cur = conn, cur
        self._rows = None
        self._rowid_src, self._rowid = lastrowid, None
        self.rowcount = getattr(cur, "rowcount", -1) if cur is not None else -1
        self.description = None
        if cur is not None and cur.description:
            self.description = tuple((d[0],) + (None,) * 6 for d in cur.description)
            self._rows = [tuple(_py(v) for v in r) for r in cur.fetchall()]

    @property
    def lastrowid(self):
        """The id the last INSERT made (lastval(), asked only when someone reads it)."""
        if self._rowid is None and self._rowid_src is not None: self._rowid = self._rowid_src.value()
        return self._rowid

    @lastrowid.setter
    def lastrowid(self, v): self._rowid = v

    def fetchall(self):
        rows, self._rows = self._rows or [], []
        return rows

    def fetchone(self):
        if not self._rows: return None
        return self._rows.pop(0)

    def fetchmany(self, n=1):
        out, self._rows = (self._rows or [])[:n], (self._rows or [])[n:]
        return out

    def __iter__(self):
        while self._rows: yield self._rows.pop(0)

    def close(self): pass


def _py(v):
    if isinstance(v, bool): return int(v)
    if isinstance(v, decimal.Decimal): return int(v) if v == v.to_integral_value() and abs(v) < 2 ** 63 else float(v)
    if isinstance(v, memoryview): return bytes(v)
    return v


def _param(v):
    """Ints, bools and strings go untyped so Postgres casts them to the column's type (SQLite's affinity, roughly)."""
    if isinstance(v, bool): return str(int(v))
    if isinstance(v, int): return str(v)
    if isinstance(v, (bytearray, memoryview)): return bytes(v)
    return v


def _err(e, sql):
    """pg8000 error -> sqlite3 error class (callers catch those), with SQLite's wording where code checks it."""
    d = e.args[0] if e.args and isinstance(e.args[0], dict) else {}
    code, msg = d.get("C", ""), d.get("M", str(e))
    if code == "42701": msg = f"duplicate column name: {msg}"
    elif code == "42P01": msg = f"no such table: {msg}"
    elif code == "42703": msg = f"no such column: {msg}"
    elif code == "42P07": msg = f"table already exists: {msg}"
    cls = sqlite3.IntegrityError if code.startswith("23") else sqlite3.OperationalError
    err = cls(f"{msg} [postgres {code}] in: {' '.join(sql.split())[:300]}")
    err.pgcode = code
    return err


class Connection:
    """A sqlite3.Connection look-alike over one pg8000 connection in its own schema."""

    def __init__(self, url=None, path=None):
        import pg8000.dbapi  # in requirements.txt since 4.x (read-only database MCP servers); imported only on Postgres
        pg8000.dbapi.paramstyle = "qmark"  # module-wide: the only other pg8000 user (mcp_servers/database.py) runs in its own process
        self._pg = pg8000.dbapi
        u = urlparse(url or URL)
        self.schema = _schema_from_url(u, path)
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.schema): raise ValueError(f"bad schema name {self.schema!r}")
        q = parse_qs(u.query)
        self._kw = dict(user=unquote(u.username or "postgres"), password=unquote(u.password or "") or None, host=u.hostname or "localhost",
                        port=u.port or 5432, database=(u.path or "/").lstrip("/") or "postgres", application_name="axor")
        if (q.get("sslmode") or [""])[0] in ("require", "verify-full", "verify-ca"):
            import ssl
            self._kw["ssl_context"] = ssl.create_default_context()
        self._open()
        self.translate = Translator(self)
        self._pk, self._cols = {}, {}

    def _open(self):
        self._tx = False
        self._c = self._pg.connect(**self._kw)
        self._c.autocommit = True
        cur = self._c.cursor()
        key = (self._kw["host"], self._kw["port"], self._kw["database"])
        with _compat_lock:
            if key not in _compat_done:
                cur.execute("SELECT pg_advisory_lock(424242)")
                try:
                    for s in re.split(r";\s*\n(?=CREATE |DO )", _COMPAT_SQL.strip().rstrip(";")):  # top-level statements start a line
                        cur.execute(s)
                finally:
                    cur.execute("SELECT pg_advisory_unlock(424242)")
                _compat_done.add(key)
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
        cur.execute(f'SET search_path TO "{self.schema}", {COMPAT}, public')

    # catalog lookups for INSERT OR REPLACE
    def conflict_key(self, table):
        t = table.lower()
        if t not in self._pk:
            cur = self._c.cursor()
            cur.execute("""SELECT i.indisprimary, array_agg(a.attname::text ORDER BY k.ord) FROM pg_index i
                             JOIN pg_class c ON c.oid = i.indrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                             CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
                             JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
                            WHERE n.nspname = current_schema() AND c.relname = ? AND i.indisunique
                            GROUP BY i.indexrelid, i.indisprimary ORDER BY i.indisprimary DESC, i.indexrelid""", (t,))
            rows = cur.fetchall()
            self._pk[t] = list(rows[0][1]) if rows else []
        return self._pk[t]

    def columns(self, table):
        t = table.lower()
        if t not in self._cols:
            cur = self._c.cursor()
            cur.execute("SELECT a.attname::text FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = current_schema() AND c.relname = ? AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum", (t,))
            self._cols[t] = [r[0] for r in cur.fetchall()]
        return self._cols[t]

    # sqlite3.Connection API
    def execute(self, sql, args=()):
        last = None
        if isinstance(args, dict): raise sqlite3.ProgrammingError("named parameters aren't supported on Postgres yet")
        args = list(args or ())
        for pg_sql, pmap in self.translate(sql):
            params = [_param(args[i]) for i in pmap] if pmap is not None else [_param(a) for a in args]
            cur = self._c.cursor()
            try:
                cur.execute(pg_sql, params)
            except self._pg.InterfaceError:
                if self._tx:  # the server rolled the transaction back with the connection: never go on outside it
                    log.warning("postgres connection lost inside a transaction: reconnecting, the transaction is rolled back")
                    self._open()
                    raise sqlite3.OperationalError("the database connection was lost inside a transaction (rolled back)") from None
                log.warning("postgres connection lost: reconnecting")
                self._open()
                cur = self._c.cursor()
                cur.execute(pg_sql, params)
            except self._pg.DatabaseError as e:
                if self._tx:  # the transaction is aborted: no retry inside it; a terminated connection is replaced, the caller rolls back
                    if (e.args[0].get("C") if e.args and isinstance(e.args[0], dict) else "") in ("57P01", "57P02", "57P03"):
                        self._tx = False; self._open()
                    raise _err(e, pg_sql) from None
                cur = self._resync_and_retry(e, pg_sql, params)
                if cur is None: raise _err(e, pg_sql) from None
            if re.match(r"\s*(CREATE|ALTER|DROP)\b", pg_sql, re.I):
                self._pk.clear(); self._cols.clear()
            last = cur
        lastrowid = None
        if re.match(r"\s*INSERT\b", sql, re.I) and last is not None and not last.description:
            lastrowid = _LazyRowid(self)
        return Cursor(self, last, lastrowid)

    def _resync_and_retry(self, e, pg_sql, params):
        """A seed or an import wrote explicit ids, so the id sequence lags behind them (SQLite needs no sequence): move it past
        MAX(id) and run the INSERT once more. None when that isn't the problem."""
        d = e.args[0] if e.args and isinstance(e.args[0], dict) else {}
        mm = re.match(r"\s*INSERT\s+INTO\s+(\w+)", pg_sql, re.I)
        if d.get("C") != "23505" or not mm or not str(d.get("n", "")).endswith("_pkey"): return None
        t = mm.group(1).lower()
        cur = self._c.cursor()
        try:
            if "id" not in self.columns(t): return None
            cur.execute("SELECT pg_get_serial_sequence(?, 'id')", (t,))
            seq = (cur.fetchone() or [None])[0]
            if not seq: return None
            cur.execute(f"SELECT setval(?, (SELECT COALESCE(MAX(id), 0) + 1 FROM {t}), false)", (seq,))
            cur = self._c.cursor()
            cur.execute(pg_sql, params)
        except self._pg.DatabaseError:
            return None
        return cur

    def executemany(self, sql, seq):
        n = 0
        for args in seq:
            self.execute(sql, args); n += 1
        c = Cursor(self); c.rowcount = n
        return c

    def executescript(self, script):
        for s in split_statements(script): self.execute(s)
        return Cursor(self)

    def cursor(self):
        return _CursorFacade(self)

    def begin(self, lock=None, wait=None):
        """Start a transaction (AuthDB.tx), and take the advisory transaction lock `lock` (an int) in it, waiting at most `wait`
        seconds for another transaction holding it (lock_timeout: the wait never stalls the process's one connection unbounded)."""
        try: self._c.cursor().execute("BEGIN")
        except (self._pg.InterfaceError, self._pg.DatabaseError):  # a stale or terminated connection before anything ran: reconnect once
            self._open(); self._c.cursor().execute("BEGIN")
        self._tx = True
        try:
            if wait: self._c.cursor().execute(f"SET LOCAL lock_timeout = '{int(wait * 1000)}ms'")
            if lock is not None: self._c.cursor().execute(f"SELECT pg_advisory_xact_lock({int(lock)})")
        except Exception as e:
            self.rollback()
            raise sqlite3.OperationalError(f"the transaction couldn't start: {e}") from None

    def commit(self):  # autocommit, except inside begin()
        if self._tx:
            self._tx = False
            self._c.cursor().execute("COMMIT")

    def rollback(self):
        if self._tx:
            self._tx = False
            try: self._c.cursor().execute("ROLLBACK")
            except self._pg.InterfaceError: self._open()  # the connection is gone, and its transaction with it

    def close(self):
        try: self._c.close()
        except Exception: pass  # noqa: BLE001


class _LazyRowid:
    def __init__(self, conn): self.conn = conn

    def value(self):
        cur = self.conn._c.cursor()
        try:
            cur.execute("SELECT lastval()")
            return cur.fetchone()[0]
        except self.conn._pg.DatabaseError:
            return None


class _CursorFacade:
    """conn.cursor().execute(...) -> results on the facade, as sqlite3 does."""
    def __init__(self, conn): self.conn, self._r = conn, Cursor(conn)

    def execute(self, sql, args=()):
        self._r = self.conn.execute(sql, args); return self

    def executemany(self, sql, seq):
        self._r = self.conn.executemany(sql, seq); return self

    def __getattr__(self, k): return getattr(self._r, k)

    def __iter__(self): return iter(self._r)


def connect(path=None):
    return Connection(URL, path)


def _pg_errors():
    import pg8000.dbapi
    return pg8000.dbapi.DatabaseError
