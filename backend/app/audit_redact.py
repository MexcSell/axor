"""D-019 follow-up: redacts the key fragments older AXoR versions wrote into audit rows (mask(): a key's first 7 and last
4 characters; the OpenRouter connector: first 12 and last 4). The writers log a sha256 fingerprint now; this cleans the rows
they left.

Dry run by default. It prints row ids and counts only, never a detail, a fragment or a key. It keeps no copy of what it
replaces: a journal of old values would be the fragments again. Run it where AXoR's database is, as the app opens it:

    cd /app/backend && python -m app.audit_redact            # dry run: which rows, per action
    cd /app/backend && python -m app.audit_redact --apply    # replaces each fragment with [redacted D-019]

Only the actions that wrote key fragments are touched: shortened hotkeys and addresses elsewhere in the audit have the same
shape and are not keys. Backups taken before the run still hold the fragments: see the procedure in the review report.
"""
import argparse, os, re, sys

ACTIONS = ("agent.provider_set", "connector.openrouter_connect", "source.connect", "source.token", "slack.connect", "agent.key_set")
FRAGMENT = re.compile(r"[A-Za-z0-9_-]{4,12}…[A-Za-z0-9_-]{4}")
MARK = "[redacted D-019]"


def open_db():
    from .auth import AuthDB
    return AuthDB(os.path.join(os.getenv("DATA_DIR", "/data"), "auth.db"))


def plan(db):
    """[(row id, action, fragments in it)] for the rows to redact."""
    marks = ",".join("?" * len(ACTIONS))
    out = []
    for r in db.q(f"SELECT id, action, detail FROM audit WHERE action IN ({marks}) ORDER BY id", ACTIONS):
        n = len(FRAGMENT.findall(r["detail"] or ""))
        if n: out.append((r["id"], r["action"], n))
    return out


def apply(db, rows):
    done = 0
    for rid, _, _ in rows:
        cur = db.q("SELECT detail FROM audit WHERE id=?", (rid,), one=True)
        if not cur: continue
        new = FRAGMENT.sub(MARK, cur["detail"] or "")
        if new != cur["detail"] and db.q("UPDATE audit SET detail=? WHERE id=? AND detail=? RETURNING id", (new, rid, cur["detail"]), one=True): done += 1
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="Redact key fragments from old audit rows (dry run by default).")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = open_db()
    rows = plan(db)
    per = {}
    for _, action, _ in rows: per[action] = per.get(action, 0) + 1
    print(f"audit rows with a key fragment: {len(rows)}")
    for action, n in sorted(per.items()): print(f"  {action}: {n}")
    print("  ids: " + (", ".join(str(r[0]) for r in rows) or "none"))
    if a.apply:
        n = apply(db, rows)
        db.log("audit.redact", "app.audit_redact", "", "", f"{n} rows redacted (D-019): ids " + ",".join(str(r[0]) for r in rows)[:180])  # itself, ids only
        print(f"redacted: {n} rows; left: {len(plan(db))}")
    else: print("dry run: nothing written (--apply to redact)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
