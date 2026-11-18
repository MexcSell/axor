"""Milestone 2 E7: no code path writes a key's characters into the audit, a log or a stored row (D-019). mask() (first 7 + last 4
characters) is for the owner's own screen only, computed when a page is read; anything stored or logged names a key by its sha256
fingerprint. A check over the backend's syntax trees: no mask() call inside a call that writes (db.log, an _audit, a log call, a
database query or insert), and none assigned into a dict entry that a later UPDATE stores (sets[...] = mask(...)). It caught the
Knowledge connectors' stored token fragment (kb_connectors.masked) when written, 2026-11-12."""
import ast, os, unittest

APP = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "app")
WRITERS = {"log", "_audit", "audit", "q", "_ins", "_many", "execute", "info", "warning", "error", "debug", "exception"}


def offenders(src, name="<src>"):
    tree, bad = ast.parse(src), []
    def is_mask(n): return isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) in ("mask", "_mask")
    def secretish(n):  # tok[:8], self.key[-4:], api_key[:12]...: a slice of something named like a credential
        sl = n.slice if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice) else None
        edge = sl is not None and ((sl.lower is None and sl.upper is not None) or isinstance(sl.lower, ast.UnaryOp))  # [:n] or [-n:]
        v = n.value if edge else None
        nm = (getattr(v, "id", None) or getattr(v, "attr", None) or "").lower()
        return bool(v is not None and any(w in nm for w in ("key", "token", "secret", "tok", "password")))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) in WRITERS:
            bad += [f"{name}:{x.lineno}" for x in ast.walk(node) if is_mask(x) or secretish(x)]
        if isinstance(node, ast.Assign) and is_mask(node.value) and any(isinstance(t, ast.Subscript) for t in node.targets):
            bad.append(f"{name}:{node.lineno}")
    return bad


class NoFragments(unittest.TestCase):
    def test_no_mask_reaches_a_write(self):
        bad = []
        for f in sorted(os.listdir(APP)):
            if f.endswith(".py") and f != "secretbox.py":
                with open(os.path.join(APP, f), encoding="utf-8") as fh: bad += offenders(fh.read(), f)
        self.assertEqual(bad, [], "a key's masked characters reach the audit, a log or a stored row")

    def test_the_check_catches_the_shapes_it_is_for(self):
        self.assertTrue(offenders('db.q("INSERT INTO t (a, masked) VALUES (?,?)",\n     (1, mask(tok)))'))   # across lines
        self.assertTrue(offenders('db.log("x", u, "", ip, f"{p} {mask(key)}")'))
        self.assertTrue(offenders('sets["masked"] = mask(tok)'))
        self.assertTrue(offenders('log.warning("proxy auth %s", token[:8])'))   # a slice of a token
        self.assertTrue(offenders('db.log("x", u, "", ip, _mask(key))'))       # the old connector helper
        self.assertFalse(offenders('return {"masked": mask(tok)}'))           # shown to the owner on read: fine
        self.assertFalse(offenders('log.info("rows %s", rows[:8])'))
        self.assertFalse(offenders('db.q("SELECT 1 WHERE id=?", (int(key[10:]),))'))   # a record key's id part, not a credential
        self.assertTrue(offenders('db.q("INSERT INTO k VALUES (?)", (token[:10],))'))


if __name__ == "__main__":
    unittest.main()
