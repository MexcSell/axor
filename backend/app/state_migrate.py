"""D-018 task-state backfill: how each finished board task was closed (mw_tasks.closed_as), from the records it left.

Dry run by default: it reads and reports, and writes nothing. Run it where AXoR's database is (inside the web pod, or against a
restored copy), as AXoR's own scripts do (it opens AuthDB like the app: DATABASE_URL, else DATA_DIR/auth.db):

    cd /app/backend && python -m app.state_migrate                  # dry run: counts per rule and team, samples, nothing written
    cd /app/backend && python -m app.state_migrate --apply          # writes closed_as and a journal row per change (one batch id)
    cd /app/backend && python -m app.state_migrate --reverse BATCH  # puts back what that batch changed (rows changed since are left alone)
    cd /app/backend && python -m app.state_migrate --schema-sql     # prints the SQL that would drop D-017/D-018's columns (not run)

Rules, for a done task whose last closing record isn't an approval (a finished review run alone is not a verdict: it can say
"revise") and with no closed_as yet; the last "done" event on the task decides, else the Director's note:
    dropped   "<Director> dropped “…”"                    (note "Dropped by …")
    closed    "<Director> closed “…”"                     (note "Done, by your answer to …"): on a person's answer to its report
    person    "<user> marked “…” done"
    answered  "<user> answered “…”: …"                    (a person answered an agent's ask, which closed it)
Verified tasks are left as they are (closed_as stays NULL: their verdict decides). Nothing else is changed: status, history,
events and notes stay exactly as they were.
"""
import argparse, json, os, re, sys, time, uuid

RULES = [("dropped", re.compile(r"^.{1,80}? dropped “")), ("closed", re.compile(r"^.{1,80}? closed “")),
         ("person", re.compile(r"^.{1,80}? marked “.*” done$", re.S)), ("answered", re.compile(r"^.{1,80}? answered “"))]
NOTES = [("dropped", "Dropped by "), ("closed", "Done, by your answer to ")]


def open_db():
    from .auth import AuthDB
    return AuthDB(os.path.join(os.getenv("DATA_DIR", "/data"), "auth.db"))


def ensure(db):
    cols = {c["name"] for c in db.q("PRAGMA table_info(mw_tasks)")}
    if "closed_as" not in cols: db.q("ALTER TABLE mw_tasks ADD COLUMN closed_as TEXT")
    db.q("""CREATE TABLE IF NOT EXISTS mig_task_state (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, task_id INTEGER, before TEXT,
            after TEXT, rule TEXT, evidence TEXT, at REAL)""")


def plan(db):
    """[(task row, rule, evidence)] for every done task the backfill would classify, and the ones it can't."""
    cols = {c["name"] for c in db.q("PRAGMA table_info(mw_tasks)")}
    has_ca = "closed_as" in cols
    done = db.q(f"SELECT id, comp_id, title, note{', closed_as' if has_ca else ''} FROM mw_tasks WHERE status='done' ORDER BY id")
    # verified = the last closing record is an approval (mission_ops.approved_last); a review run alone is not a verdict
    last, closing = {}, {}
    for e in db.q("SELECT task_id, kind, text FROM mw_events WHERE kind IN ('approve','done') AND task_id IS NOT NULL ORDER BY id"):
        closing[e["task_id"]] = e["kind"]
        if e["kind"] == "done": last[e["task_id"]] = e["text"] or ""
    ok = {t for t, k in closing.items() if k == "approve"}
    out, unknown, verified, already = [], [], 0, 0
    for t in done:
        if t["id"] in ok: verified += 1; continue
        if has_ca and t.get("closed_as"): already += 1; continue
        txt, rule, ev = last.get(t["id"], ""), None, ""
        for name, rx in RULES:
            if rx.match(txt): rule, ev = name, f"event: {txt[:160]}"; break
        if not rule:
            for name, pre in NOTES:
                if str(t.get("note") or "").startswith(pre): rule, ev = name, f"note: {str(t['note'])[:160]}"; break
        (out if rule else unknown).append((t, rule, ev or f"last done event: {txt[:160]!r}; note: {str(t.get('note') or '')[:80]!r}"))
    return out, unknown, {"done": len(done), "verified": verified, "already": already}


def report(out, unknown, n):
    by = {}
    for t, rule, _ in out: by.setdefault((t["comp_id"], rule), 0); by[(t["comp_id"], rule)] += 1
    print(f"done board tasks: {n['done']}; with an independent verdict (left as they are): {n['verified']}; already classified: {n['already']}")
    print(f"to classify: {len(out)}; can't classify (left NULL): {len(unknown)}")
    for (comp, rule), k in sorted(by.items()): print(f"  team {comp}: {rule:<9} {k}")
    for rule in ("dropped", "closed", "person", "answered"):
        xs = [x for x in out if x[1] == rule][:2]
        for t, _, ev in xs: print(f"  sample {rule}: #{t['id']} “{t['title'][:60]}” ← {ev[:120]}")
    for t, _, ev in unknown[:10]: print(f"  unclassified: #{t['id']} “{t['title'][:60]}” ({ev[:120]})")


def apply(db, out):
    ensure(db)
    batch, now = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6], time.time()
    n = 0
    for t, rule, ev in out:
        # only rows still unclassified: a row the app classified meanwhile keeps the app's value
        changed = db.q("UPDATE mw_tasks SET closed_as=? WHERE id=? AND status='done' AND closed_as IS NULL RETURNING id", (rule, t["id"]), one=True)
        if not changed: continue
        db.q("INSERT INTO mig_task_state (batch, task_id, before, after, rule, evidence, at) VALUES (?,?,?,?,?,?,?)",
             (batch, t["id"], None, rule, rule, ev[:300], now))
        n += 1
    print(f"applied: {n} rows, batch {batch} (reverse with --reverse {batch})")
    return batch


def reverse(db, batch):
    rows = db.q("SELECT * FROM mig_task_state WHERE batch=? ORDER BY id", (batch,))
    if not rows: print(f"no journal rows for batch {batch}"); return 0
    n = kept = 0
    for r in rows:
        back = db.q("UPDATE mw_tasks SET closed_as=? WHERE id=? AND closed_as=? RETURNING id", (r["before"], r["task_id"], r["after"]), one=True)
        if back: n += 1
        else: kept += 1  # changed since (the app closed or reopened it): its current value is newer than the migration's
    db.q("DELETE FROM mig_task_state WHERE batch=?", (batch,))
    print(f"reversed: {n} rows put back; {kept} changed since and left as they are; journal batch {batch} removed")
    return n


SCHEMA_SQL = """-- D-017 to D-025 schema (G5-2.1 to G5-2.2 Milestone 4), for a rollback that wants the columns gone (RC1 ignores them; dropping is optional).
-- Run only with AXoR stopped, after a backup, on the Owner's approval. AXoR re-adds them on its next start of this version.
ALTER TABLE mw_tasks DROP COLUMN closed_as;
ALTER TABLE mw_tasks DROP COLUMN needs_by;
ALTER TABLE mw_tasks DROP COLUMN needs_at;
ALTER TABLE mw_tasks DROP COLUMN needs_confirm;
ALTER TABLE mw_tasks DROP COLUMN needs_verify;
ALTER TABLE ctl_tasks DROP COLUMN needs_by;
ALTER TABLE ctl_tasks DROP COLUMN needs_at;
ALTER TABLE ctl_tasks DROP COLUMN needs_confirm;
ALTER TABLE ctl_tasks DROP COLUMN needs_verify;
ALTER TABLE ac_runs DROP COLUMN login;
ALTER TABLE ac_runs DROP COLUMN login_kind;
ALTER TABLE ac_runs DROP COLUMN metering;
DROP TABLE task_req_decisions;
DROP TABLE mo_verdicts;
DROP TABLE mig_task_state;
DROP TABLE ac_reservations;"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write closed_as and the journal")
    g.add_argument("--reverse", metavar="BATCH", help="put back what this batch changed")
    g.add_argument("--schema-sql", action="store_true", help="print the schema rollback SQL (not run)")
    ap.add_argument("--json", action="store_true", help="dry run: also print the plan as JSON")
    a = ap.parse_args(argv)
    if a.schema_sql: print(SCHEMA_SQL); return 0
    db = open_db()
    if a.reverse: ensure(db); reverse(db, a.reverse); return 0
    out, unknown, n = plan(db)
    report(out, unknown, n)
    if a.json: print(json.dumps([{"task": t["id"], "comp": t["comp_id"], "rule": r, "evidence": e} for t, r, e in out + unknown]))
    if a.apply: apply(db, out)
    else: print("dry run: nothing written (--apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
