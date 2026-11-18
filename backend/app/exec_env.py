"""The Agent Execution Fabric's own part (AEF; decision D-032 with D-032a, approved by the Owner on 2026-11-13 for development
only; design in owner-decisions/g5-plan/aef/AEF_02_TARGET_ARCHITECTURE.md, shapes in AEF_05_SCHEMA_AND_API.md).

AEF is not a second execution system. A team's sandbox run still starts in one place (mining_work.Work._sandbox), still runs in
sandbox.py's throwaway pod, still leaves through egress_proxy.py and is still one mw_sbx row. This module adds, for a team whose
switches are on (app_settings `exec.comp:<team id>`, administrators only; with none on, begin() returns None and nothing changes):

- a plan for the run from the task's declared needs and the team's policy (plan): size, egress policy, workspace, credentials;
- the mission's persistent workspace (Store): file contents by hash (mw_blobs, on disk), a snapshot after every save (mw_ws,
  append-only), restored into the run's /work/mission at its start and saved at its end and at save points, with a merge rule
  that never overwrites another run's change silently, and rollback. Machines stay throwaway (D-032a): only this persists.
  The task checkpoint (mw_ckpt) is a special case of it: with the workspace on, a task's progress folder lives in it;
- the run's measurements and its manifest (mw_sbx.stats, mw_sbx.manifest): what was asked, in what environment, what came out.

Everything a run exchanges with AXoR travels over the per-run endpoint every run already has (sandbox.Proxy hands `/rlm/…`
requests to the run's hook): Session.hook answers `/rlm/aef/…` for sandbox_files/aef.py, the script inside the run. No new
network path is opened to a run, and nothing in a request can choose the mission, team or run: those come from AXoR's own
record of the token.

What a run reports about itself (stats) is the run's own word and is labelled so. The image id, the policy, the snapshots and
the network record are AXoR's."""
import base64, hashlib, json, logging, os, posixpath, re, shutil, threading, time
from pathlib import Path

from . import sandbox

log = logging.getLogger("exec_env")
ENABLED = os.getenv("AXOR_EXEC", "1") != "0"   # 0: no team's switch counts, the whole of AEF is off
ROOT = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "var")) / "exec"
WS_BYTES = int(float(os.getenv("EXEC_WS_MB", "1000")) * 1_000_000)      # a mission's workspace: under a run's 2 GiB working folder
FILE_BYTES = int(float(os.getenv("EXEC_FILE_MB", "200")) * 1_000_000)
WS_FILES = int(os.getenv("EXEC_WS_FILES", "20000"))
SAVE_BYTES = int(float(os.getenv("EXEC_SAVE_MB", "1000")) * 1_000_000)  # new content one run may send
LIVE_S = max(0, int(os.getenv("EXEC_LIVE_S", "10")))                      # how often a running run reports what it has used so far; 0 = only at its end
KEEP = max(2, int(os.getenv("EXEC_SNAPSHOTS", "50")))                   # snapshots kept per mission, besides the ones marked kept
BACKUP_HOLD = "exec.backup_hold"                                          # see Store.sweep
SWEEP_EVERY = 3600     # seconds between clean-ups of contents no snapshot names any more
RESERVE = 120          # seconds of a run kept for restoring and saving the workspace, around the command's own time
GET_BYTES = 4_500_000  # file content per answer: its base64 stays under the per-run endpoint's 8 MB
PATH_CHARS = 400
EXCLUDE = ("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox")   # never saved: rebuilt, not kept
READ_ONLY = ("team", "shared", ".axor")                                                              # a run never saves these
SHARED = "shared"      # the mission key of a team's read-only knowledge workspace; team 0's is every team's
# Known package-index hosts. The Owner's decision is RESTRICTED access (D1; review directive of 2026-11-13 §3): a workload installs
# packages only in `allowlist` mode, from the Owner's approved hosts (runner.package_hosts), reached as EXACT hosts over https.
# This list is used for two things, neither of which is enforcement of a package source:
# - a policy's own host list may not name any of these, a parent of one or a name under one: the only way to an index is the
#   Owner's approved list;
# - in `public` mode every one of them is refused, approved or not, so a task that installs packages has to be given an allowlist.
#   A mirror, a Git URL or an index nobody listed still passes in `public` mode: it is a guard rail, and is never reported as more.
INDEXES = ("pypi.org", "files.pythonhosted.org", "test.pypi.org", "download.pytorch.org", "registry.npmjs.org", "registry.yarnpkg.com",
           "crates.io", "static.crates.io", "index.crates.io", "proxy.golang.org", "sum.golang.org", "rubygems.org", "repo.maven.apache.org",
           "repo1.maven.org", "plugins.gradle.org", "packagist.org", "repo.packagist.org", "api.nuget.org", "conda.anaconda.org",
           "repo.anaconda.com", "deb.debian.org", "security.debian.org", "archive.ubuntu.com", "security.ubuntu.com", "dl-cdn.alpinelinux.org")
SHA = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.RLock()    # one writer of snapshots at a time (one web process runs every sandbox run)


class ExecError(Exception):
    """Something a run or a person asked of the workspace can't be done; the message is safe to show."""


def schema(db):
    """The two tables and the four nullable columns (AEF_05 §1). Additive: older code ignores them."""
    q = db.q
    q("CREATE TABLE IF NOT EXISTS mw_blobs (sha TEXT PRIMARY KEY, bytes INTEGER, created REAL)")
    q("""CREATE TABLE IF NOT EXISTS mw_ws (id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, mission TEXT, parent INTEGER, tree TEXT,
         files INTEGER, bytes INTEGER, sbx_id INTEGER, agent_id INTEGER, by_user TEXT, note TEXT, changes TEXT, created REAL, kept INTEGER DEFAULT 0)""")
    q("CREATE INDEX IF NOT EXISTS mw_ws_m ON mw_ws (comp_id, mission, id)")
    have = {c["name"] for c in q("PRAGMA table_info(mw_sbx)")}
    for col in ("stats TEXT", "manifest TEXT", "ws_from INTEGER", "ws_to INTEGER"):
        if have and col.split()[0] not in have: q(f"ALTER TABLE mw_sbx ADD COLUMN {col}")


def _cfg(v):
    try: v = json.loads(v or "{}")
    except ValueError: return {}
    return v if isinstance(v, dict) else {}


def settings(db, comp_id, mission=None):
    """A team's switches: {"plan", "workspace", "egress": {...}} from app_settings `exec.comp:<id>`; {} when none or AEF is off.
    With `mission`: that mission's own egress policy (`exec.mission:<team id>:<mission>`), when it has one, in place of the team's:
    two missions of one team can have different reach."""
    if not ENABLED: return {}
    v = _cfg(db.setting(f"exec.comp:{comp_id}"))
    own = _cfg(db.setting(f"exec.mission:{comp_id}:{mission}")) if mission else {}
    return {**v, "egress": own["egress"]} if own.get("egress") else v


def planned(cfg):
    """True when these switches make begin() plan a team's runs (and so let a declared need shape them). The one test of it:
    begin() uses it, and the readiness gate's `ram:` probe asks it, so the two can't drift."""
    return bool(cfg and (cfg.get("plan") or cfg.get("workspace") or (cfg.get("egress") or {}).get("mode")))


def mission_policies(db, comp_id):
    """{mission: {"egress": {...}}} for the missions of a team that have their own policy."""
    pre = f"exec.mission:{comp_id}:"
    return {r["k"][len(pre):]: _cfg(r["v"]) for r in db.q("SELECT k, v FROM app_settings WHERE k LIKE ?", (pre + "%",)) if _cfg(r["v"])}


# ---------------------------------------------------------------- paths
def clean(path):
    """A workspace path as stored (relative, normalized, with / between folders), or raises ExecError saying why not."""
    if not isinstance(path, str) or not path or len(path) > PATH_CHARS or any(ord(c) < 32 or c == "\x7f" for c in path):
        raise ExecError("not a usable path")
    p = posixpath.normpath(path.replace("\\", "/"))
    if p.startswith("/") or p == "." or p == ".." or p.startswith("../") or "/../" in f"/{p}/": raise ExecError("outside the workspace")
    if p.split("/", 1)[0] in READ_ONLY: raise ExecError("a read-only folder")
    if sandbox.SECRET_PATH.search(p): raise ExecError("looks like a secret")
    if any(part in EXCLUDE for part in p.split("/")): raise ExecError("build output or a cache")
    return p


def clean_link(path, target):
    """A link's target as stored: relative and pointing inside the workspace."""
    if not isinstance(target, str) or not target or len(target) > PATH_CHARS or target.startswith("/") or "\x00" in target: raise ExecError("a link out of the workspace")
    if posixpath.normpath(posixpath.join(posixpath.dirname(path), target)).startswith(".."): raise ExecError("a link out of the workspace")
    return target


def _entry(v):
    """[sha, bytes, mode] of one file, checked."""
    if not (isinstance(v, (list, tuple)) and len(v) == 3 and isinstance(v[0], str) and SHA.match(v[0]) and isinstance(v[1], int) and v[1] >= 0):
        raise ExecError("not a file entry")
    return [v[0], v[1], 0o755 if isinstance(v[2], int) and v[2] & 0o100 else 0o644]


# ---------------------------------------------------------------- the store
class Store:
    """File contents by hash and the snapshots that name them. Contents: ROOT/blobs/<aa>/<sha>. A snapshot's file list is a blob."""
    def __init__(self, db, root=None):
        self.db, self.root = db, Path(root or ROOT)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True); (self.root / "tmp").mkdir(parents=True, exist_ok=True)
        schema(db)

    def path(self, sha): return self.root / "blobs" / sha[:2] / sha

    def known(self, shas):
        """{sha: bytes} of the contents the store holds, among these."""
        shas = sorted({s for s in shas if isinstance(s, str) and SHA.match(s)})
        out = {}
        for i in range(0, len(shas), 400):
            part = shas[i:i + 400]
            out.update((r["sha"], r["bytes"]) for r in self.db.q(f"SELECT sha, bytes FROM mw_blobs WHERE sha IN ({','.join('?' * len(part))})", tuple(part)))
        return out

    def size(self, sha):
        r = self.db.q("SELECT bytes FROM mw_blobs WHERE sha=?", (sha,), one=True)
        return r["bytes"] if r else None

    def adopt(self, tmp, sha):
        """A finished temporary file becomes the content named sha (checked by the caller). Stored once, whoever sends it."""
        dst = self.path(sha)
        dst.parent.mkdir(parents=True, exist_ok=True)
        n = os.path.getsize(tmp)
        if dst.exists() and os.path.getsize(dst) == n: os.remove(tmp)
        else: os.replace(tmp, dst)   # also when the record knows the content and the file is gone or cut short (a restore)
        self.db.q("INSERT INTO mw_blobs (sha, bytes, created) VALUES (?,?,?) ON CONFLICT(sha) DO NOTHING", (sha, n, time.time()))
        return n

    def put(self, data):
        sha = hashlib.sha256(data).hexdigest()
        if not self.path(sha).exists() or self.size(sha) is None or os.path.getsize(self.path(sha)) != len(data):
            tmp = self.root / "tmp" / f"put-{sha}-{os.getpid()}-{threading.get_ident()}"
            tmp.write_bytes(data); self.adopt(tmp, sha)
        return sha

    def read(self, sha, offset=0, n=None):
        with open(self.path(sha), "rb") as f:
            f.seek(offset)
            return f.read() if n is None else f.read(n)

    def contains(self, sha, needles):
        """True when the content holds any of the byte strings (a credential's value must never be saved)."""
        if not needles: return False
        keep, tail = max(len(x) for x in needles), b""
        with open(self.path(sha), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                buf = tail + chunk
                if any(x in buf for x in needles): return True
                tail = buf[-keep:]
        return False

    # ---- snapshots
    def head(self, comp, mission):
        return self.db.q("SELECT * FROM mw_ws WHERE comp_id=? AND mission=? ORDER BY id DESC LIMIT 1", (comp, mission), one=True)

    def problems(self, row, limit=5):
        """What of a snapshot the store doesn't hold on disk: [] when its file list and every content it names are there with the
        recorded size. The records (mw_ws, mw_blobs) and the contents (files) are backed up at different moments, so after a
        restore a snapshot can name contents that were written after the files were copied."""
        if not row: return []
        try: files = json.loads(self.read(row["tree"])).get("files") or {}
        except (OSError, ValueError): return ["its list of files"]
        bad = []
        for path, v in sorted(files.items()):
            try: ok = os.path.getsize(self.path(v[0])) == v[1]
            except (OSError, TypeError, IndexError): ok = False
            if not ok:
                bad.append(path)
                if len(bad) > limit: break
        return bad

    def intact(self, comp, mission, row=None):
        """Raises ExecError when the mission's newest snapshot (or `row`) can't be restored in full. Never answered by falling back to
        an older snapshot: which state a mission goes on from after a loss is a person's decision (rollback)."""
        row = row or self.head(comp, mission)
        bad = self.problems(row)
        if bad:
            what = "shared knowledge" if mission == SHARED else f"workspace of {mission}"
            raise ExecError(f"The {what} can't be restored: snapshot #{row['id']} names contents the store doesn't hold ({', '.join(bad[:5])}{' and more' if len(bad) > 5 else ''}). "
                            "The records are newer than the stored files, as after a restore from a backup. Nothing was started and no older state was used in its place: "
                            "an administrator can roll the mission back to a snapshot that is whole (Execution, the team's workspaces).")

    def row(self, comp, sid):
        return self.db.q("SELECT * FROM mw_ws WHERE id=? AND comp_id=?", (sid, comp), one=True) if sid else None

    def tree(self, row):
        """{"files": {path: [sha, bytes, mode]}, "links": {path: target}} of a snapshot row (None: the empty workspace)."""
        if not row: return {"files": {}, "links": {}}
        t = json.loads(self.read(row["tree"]))
        return {"files": t.get("files") or {}, "links": t.get("links") or {}}

    def snapshots(self, comp, mission, limit=50):
        return [dict(r) | {"changes": json.loads(r["changes"] or "{}")} for r in
                self.db.q("SELECT * FROM mw_ws WHERE comp_id=? AND mission=? ORDER BY id DESC LIMIT ?", (comp, mission, max(1, min(int(limit), 500))))]

    def _write(self, comp, mission, parent, files, links, changes, note, sbx=None, agent=None, user=None):
        body = json.dumps({"v": 1, "files": files, "links": links}, sort_keys=True, separators=(",", ":")).encode()
        tree = self.put(body)
        r = self.db.q("""INSERT INTO mw_ws (comp_id, mission, parent, tree, files, bytes, sbx_id, agent_id, by_user, note, changes, created)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                      (comp, mission, parent, tree, len(files), sum(v[1] for v in files.values()), sbx, agent, user, note[:300], json.dumps(changes), time.time()), one=True)
        return r["id"], tree

    def commit(self, comp, mission, base, files, links=None, *, allowed=None, sbx=None, agent=None, user=None, note="", tag=None,
               conflicted=(), needles=(), skipped=()):
        """The workspace as a run (or a person) holds it now, merged onto the mission's head. base: the snapshot id it started from
        (None: empty). Returns {"snapshot", "new", "tree", "changes": {added, changed, removed, conflicts, refused}, "files"}.

        Merge rule: a path the sender changed since `base` that the head also changed since `base` is a conflict: the head's
        version stays at the path and the sender's is kept beside it as <path>.conflict-run<tag>. A path only one side touched
        merges. `allowed`: the hashes this sender may name (what it was given plus what it sent); None for AXoR's own writes.
        Raises ExecError when the result would be over the workspace's limits: nothing is written then."""
        refused = [{"path": str(x.get("path"))[:PATH_CHARS], "why": str(x.get("why"))[:120]} for x in list(skipped)[:200] if isinstance(x, dict)]
        mine, mlinks = {}, {}
        if not isinstance(files, dict) or not isinstance(links or {}, dict): raise ExecError("The save isn't a file list.")
        if len(files) > WS_FILES * 2: raise ExecError(f"A workspace holds at most {WS_FILES} files.")
        known = self.known({v[0] for v in files.values() if isinstance(v, (list, tuple)) and v})
        for path, v in files.items():
            try:
                p, e = clean(path), _entry(v)
                if e[1] > FILE_BYTES: raise ExecError(f"over {FILE_BYTES // 1_000_000} MB")
                if e[0] not in known or (allowed is not None and e[0] not in allowed): raise ExecError("its content was never sent")
                if known[e[0]] != e[1]: raise ExecError("its size doesn't match its content")
                mine[p] = e
            except ExecError as x: refused.append({"path": str(path)[:PATH_CHARS], "why": str(x)})
        for path, target in (links or {}).items():
            try: p = clean(path); mlinks[p] = clean_link(p, target)
            except ExecError as x: refused.append({"path": str(path)[:PATH_CHARS], "why": str(x)})
        with _LOCK:
            head = self.head(comp, mission)
            brow = self.row(comp, base) if base else None
            if base and (not brow or brow["mission"] != mission):   # never another mission's: its file names would come back as "removed"
                raise ExecError("The save names a snapshot this mission doesn't have.")
            b = self.tree(brow)
            h = self.tree(head)
            if needles:  # only content that is new here needs looking at
                old = {v[0] for v in b["files"].values()} | {v[0] for v in h["files"].values()}
                for p in [p for p, e in mine.items() if e[0] not in old]:
                    if self.contains(mine[p][0], needles): refused.append({"path": p, "why": "contains a credential's value"}); mine.pop(p)
            out, forced = dict(h["files"]), set(conflicted or ())
            added, changed, removed, conflicts = [], [], [], []
            gone = {r["path"] for r in refused}   # a path that was left out of the save isn't "removed by the run": the head keeps it
            for p in sorted(set(mine) | set(b["files"]) | set(h["files"])):
                r, bb, hh = mine.get(p), b["files"].get(p), h["files"].get(p)
                if r is None and (p in gone or any(p.startswith(g) for g in gone if g.endswith("/"))): continue
                if r == bb: continue                                   # the sender didn't touch it: the head's stays
                if (hh == bb and p not in forced) or r == hh:          # only the sender touched it, or both made the same change
                    if r is None: out.pop(p, None); removed.append(p)
                    elif hh is None: out[p] = r; added.append(p)
                    elif r != hh: out[p] = r; changed.append(p)
                    continue
                keep_as = None
                if r is not None:
                    keep_as = f"{p}.conflict-run{tag or 'x'}"[:PATH_CHARS]
                    if out.get(keep_as) != r: out[keep_as] = r; added.append(keep_as)
                conflicts.append({"path": p, "kept_as": keep_as, "theirs": "removed" if hh is None else "changed", "yours": "removed" if r is None else "changed"})
            olinks = {p: t for p, t in h["links"].items() if p not in b["links"] or p in mlinks or p in gone}   # a link the sender dropped goes
            olinks.update(mlinks)
            olinks = {p: t for p, t in olinks.items() if p not in out}
            if len(out) > WS_FILES: raise ExecError(f"The workspace would hold {len(out)} files; at most {WS_FILES} are kept. Delete some, or keep build output out of it.")
            total = sum(v[1] for v in out.values())
            if total > WS_BYTES: raise ExecError(f"The workspace would be {total // 1_000_000} MB; at most {WS_BYTES // 1_000_000} MB is kept.")
            changes = {"added": added[:200], "changed": changed[:200], "removed": removed[:200], "conflicts": conflicts[:200], "refused": refused[:200],
                       "counts": {"added": len(added), "changed": len(changed), "removed": len(removed), "conflicts": len(conflicts), "refused": len(refused)}}
            if out == h["files"] and olinks == h["links"] and head:
                return {"snapshot": head["id"], "new": False, "tree": head["tree"], "changes": changes, "files": out}
            if not out and not olinks and not head:
                return {"snapshot": None, "new": False, "tree": None, "changes": changes, "files": out}
            sid, tree = self._write(comp, mission, head["id"] if head else None, out, olinks, changes,
                                    note or (f"run #{sbx}" if sbx else "saved") + (f", {len(conflicts)} conflict(s)" if conflicts else ""), sbx, agent, user)
            if self.prune(comp, mission): self._sweep_soon()
            return {"snapshot": sid, "new": True, "tree": tree, "changes": changes, "files": out}

    def rollback(self, comp, mission, snapshot, user):
        """The mission's workspace becomes what snapshot held: a new snapshot with that file list, so the rollback can itself be undone."""
        with _LOCK:
            row, head = self.row(comp, snapshot), self.head(comp, mission)
            if not row or row["mission"] != mission: raise ExecError("This mission has no such snapshot.")
            self.intact(comp, mission, row)   # never roll back onto a snapshot whose contents are gone
            if head and head["tree"] == row["tree"]: return {"snapshot": head["id"], "new": False}
            t = self.tree(row)
            sid, _tree = self._write(comp, mission, head["id"] if head else None, t["files"], t["links"], {"rollback_to": row["id"]}, f"rollback to #{row['id']}", user=user)
            return {"snapshot": sid, "new": True}

    def keep(self, comp, snapshot, kept):
        if not self.row(comp, snapshot): raise ExecError("No such snapshot.")
        self.db.q("UPDATE mw_ws SET kept=? WHERE id=? AND comp_id=?", (1 if kept else 0, snapshot, comp))

    def prune(self, comp, mission):
        """Keeps a mission's last KEEP snapshots and every one marked kept or that a run row names; older rows go. Contents that
        no remaining snapshot names are deleted by sweep(), not here."""
        rows = self.db.q("SELECT id FROM mw_ws WHERE comp_id=? AND mission=? AND kept=0 ORDER BY id DESC", (comp, mission))
        old = [r["id"] for r in rows[KEEP:]]
        for i in range(0, len(old), 400):
            part = old[i:i + 400]
            self.db.q(f"DELETE FROM mw_ws WHERE id IN ({','.join('?' * len(part))})", tuple(part))
        return len(old)

    def _sweep_soon(self):
        """After snapshots were pruned: delete the contents nothing names any more, in the background, at most once an hour."""
        if time.time() - getattr(self, "_swept", 0) < SWEEP_EVERY: return
        self._swept = time.time()
        def go():
            try: n = self.sweep(); log.info("exec: swept %s unreferenced content file(s)", n)
            except Exception as e: log.warning("exec: sweep failed: %s", e)   # noqa: BLE001 - the next prune tries again
        threading.Thread(target=go, daemon=True, name="exec-sweep").start()

    def sweep(self, older_than=3600):
        """Deletes contents no snapshot names any more (after prune). Contents newer than `older_than` s are left: a run may be sending them.
        Nothing is deleted while a backup holds the store (setting `exec.backup_hold`: a time, in seconds since 1970, until which the
        hold lasts): a backup takes the records first and the files later, and a content its records still name must be in its files."""
        until = self.db.setting(BACKUP_HOLD)
        if until:
            try: held = float(until) > time.time()
            except ValueError: held = True                # set and not understood: nothing is deleted
            if held: return 0
        with _LOCK:
            live = set()
            for r in self.db.q("SELECT DISTINCT tree FROM mw_ws"):
                live.add(r["tree"])
                try: live |= {v[0] for v in (json.loads(self.read(r["tree"])).get("files") or {}).values()}
                except (OSError, ValueError): pass
            dead = [r["sha"] for r in self.db.q("SELECT sha FROM mw_blobs WHERE created<?", (time.time() - older_than,)) if r["sha"] not in live]
            for sha in dead:
                try: os.remove(self.path(sha))
                except OSError: pass
                self.db.q("DELETE FROM mw_blobs WHERE sha=?", (sha,))
            return len(dead)


# ---------------------------------------------------------------- the plan
def approved_indexes(db):
    """The package-index hosts the Owner approved: the runner's own setting (D1), read here and never duplicated."""
    try:
        from . import runner
        return tuple(runner.package_hosts(db.setting("runner.package_hosts") or ""))
    except Exception:  # noqa: BLE001 - the runner module may be absent on a branch; then nothing is approved
        return ()


def plan(needs, cfg, internet, approved=(), spent=None, has_secrets=False):
    """What a run gets, from its task's declared needs ([{"cap", "value"}], task_lifecycle.needs_of's declared ones) and its team's
    switches. Pure: the same inputs give the same plan. Returns {"backend", "size", "cpu", "memory_mb", "egress", "workspace"}.

    - size: L when the task declares ram:<more than M's GB>; M otherwise (what every run had).
    - egress: the team's own internet switch stays the master; a policy can only narrow it. mode off | allowlist | public; with no
      mode set a planned run has the team's internet as before, except that every known package index is refused: no planned run
      installs packages without the mission's allowlist (review directive of 2026-11-13, §3: "every mission workload").
      allowlist: the policy's hosts plus the hosts of the task's git:<host>/… needs. A known package index (or a parent of one, or
      a name under one) is dropped from that list: an index is reachable only through "packages": "approved", which adds the Owner's
      approved hosts (`approved`) as EXACT hosts and makes the run https-only. That is the one way a workload installs packages.
      public: the public web with every known package index refused (approved or not), so installing needs an allowlist; "packages"
      has no effect here. Not enforcement: a mirror or a Git URL passes in public mode, and that is said wherever it is shown.
      up_mb_day / down_mb_day: what the mission may still move today (spent: {"up_mb", "down_mb"}); nothing left = no internet.
    - a run that is given a credential never has `public` egress: it gets the allowlist, or no internet when there is none."""
    declared = [n for n in needs or [] if n.get("source", "declared") == "declared"]
    ram = max([float(n["value"]) for n in declared if n.get("cap") == "ram" and re.fullmatch(r"\d+(\.\d+)?", str(n.get("value") or ""))] or [0])
    m_gb = int(sandbox.SIZES["M"][1].rstrip("Gi"))
    size = "L" if ram > m_gb else "M"
    eg, pol = dict((cfg or {}).get("egress") or {}), {"mode": "inherit"}
    mode = eg.get("mode") if eg.get("mode") in ("off", "allowlist", "public") else None
    hosts = sorted({str(h).lower().strip(".") for h in eg.get("hosts") or [] if re.fullmatch(r"[A-Za-z0-9.-]{3,253}", str(h))}
                   | {str(n["value"]).split("/", 1)[0].lower() for n in declared if n.get("cap") == "git" and n.get("value")})
    dropped = [h for h in hosts if index_related(h)]
    hosts = [h for h in hosts if h not in dropped]
    exact = sorted({a.lower() for a in approved}) if mode == "allowlist" and eg.get("packages") == "approved" else []
    note = ""
    if has_secrets and mode != "allowlist":
        mode, note = ("allowlist" if hosts else "off"), "a run that is given a credential has an allowlist, never the public web"
    on = bool(internet) and mode != "off"
    net = None
    if on and mode:
        net = {"conns": True}
        if mode == "allowlist":
            if hosts: net["hosts"] = hosts
            if exact: net["hosts_exact"] = exact; net["https_only"] = True   # package installs: the Owner's hosts, exactly, over https
            if not hosts and not exact: on, note = False, "the allowlist names no host"
            pol = {"mode": mode, "hosts": hosts, **({"package_hosts": exact, "https_only": True} if exact else {}),
                   **({"packages": "asked for, but the Owner has approved no package host"} if eg.get("packages") == "approved" and not exact else {}),
                   **({"dropped_hosts": dropped, "dropped_why": "a package index is reachable only through the Owner's approved list"} if dropped else {})}
        else:
            net["deny"] = list(INDEXES)   # every known index, approved or not: installing packages needs an allowlist
            pol = {"mode": mode, "packages": "not in public mode: a task that installs packages needs the mission's allowlist",
                   "denied_indexes": len(INDEXES)}
    elif on:   # no policy: the team's internet as it was, minus the package indexes
        net = {"conns": True, "deny": list(INDEXES)}
        pol = {"mode": "inherit", "packages": "not without a policy: a task that installs packages needs the mission's allowlist", "denied_indexes": len(INDEXES)}
    for way in ("up", "down"):
        cap = eg.get(f"{way}_mb_day")
        if on and isinstance(cap, (int, float)) and cap > 0:
            left = float(cap) - float((spent or {}).get(f"{way}_mb") or 0)
            if left <= 0 or (spent or {}).get(f"{way}_cut"): on, net, note = False, None, f"the mission's {way}load budget for today ({cap:g} MB) is spent"
            else:
                net = net if net is not None else {"conns": True}
                net[f"{way}_mb"] = left; pol[f"{way}_mb_left"] = round(left, 3)
    if not on: pol = {"mode": "off", **({"why": note} if note and internet else {})}
    elif note: pol["note"] = note
    cpu, mem, _w = sandbox.SIZES[size]
    return {"backend": "pod", "size": size, "cpu": int(cpu), "memory_mb": int(mem.rstrip("Gi")) * 1024, "internet": on, "net": net if on else None,
            "egress": pol, "workspace": bool((cfg or {}).get("workspace"))}


def index_related(host):
    """True when a host is a known package index, a parent domain of one, or a name under one: nothing a policy's own host list
    may hold (a parent would admit the index through the proxy's subdomain match)."""
    h = (host or "").lower().strip(".")
    return any(h == i or i.endswith("." + h) or h.endswith("." + i) for i in INDEXES)


def spent_today(db, comp, mission):
    """What a mission's runs moved through the egress proxy since midnight UTC: {"up_mb", "down_mb"}, and "up_cut" / "down_cut"
    when one of them was cut off by the mission's budget that way. A run is cut just before the byte that would cross its cap,
    so the bytes alone never quite reach the budget: a cut is what says it is spent."""
    since = time.time() - (time.time() % 86400)
    out = {"up_mb": 0.0, "down_mb": 0.0}
    cols = {c["name"] for c in db.q("PRAGMA table_info(mw_tasks)")}
    scols = {c["name"] for c in db.q("PRAGMA table_info(mw_sbx)")}
    for r in db.q(f"""SELECT s.net, {'s.manifest' if 'manifest' in scols else 'NULL'} AS manifest, {'t.mission' if 'mission' in cols else 'NULL'} AS mission
                      FROM mw_sbx s LEFT JOIN mw_tasks t ON t.id=s.task_id WHERE s.comp_id=? AND s.started>? AND s.net IS NOT NULL""", (comp, since)):
        if (r["mission"] or f"comp:{comp}") != mission: continue
        try: n, m = json.loads(r["net"]), json.loads(r["manifest"] or "{}")
        except ValueError: continue
        out["up_mb"] += (n.get("up_bytes") or 0) / 1e6; out["down_mb"] += (n.get("down_bytes") or 0) / 1e6
        eg = ((m.get("plan") or {}).get("egress") or {})
        for way in ("up", "down"):
            if f"{way}_mb_left" in eg and any(str(x.get("why") or "").startswith(f"{way}load cap") for x in n.get("refused") or []): out[f"{way}_cut"] = True
    return out


# ---------------------------------------------------------------- one run
class Session:
    """A planned run, from just before its pod exists until its row is written. hook() answers the script inside the run."""
    def __init__(self, store, db, *, comp, mission, task, agent, sid, the_plan, command, timeout, files, user=None, ckpt=None, secrets=None):
        self.store, self.db, self.comp, self.mission, self.task, self.agent, self.sid = store, db, comp, mission, task, agent, sid
        self.plan, self.user, self.ckpt = the_plan, user, ckpt
        self.ws, self.internet = bool(the_plan["workspace"]), bool(the_plan["internet"])
        self.secrets = secrets            # None, or a broker: .names, .fetch(name) -> value, .close()
        self.values = {}                  # the credential values this run was given, for masking and for refusing them in saves
        self.stats, self.events = None, []
        self.base = self.store.head(comp, mission) if self.ws else None
        self.allowed, self.sent, self.parts, self.ws_to, self.saves = set(), 0, {}, None, 0
        self.tmp = self.store.root / "tmp" / f"run-{sid}-{int(time.time())}"
        inner = max(10, min(int(timeout or 600), sandbox.MAX_TIMEOUT - RESERVE))
        self.timeout = inner + RESERVE
        self.command = f"python3 /work/.axor/aef.py run {inner} {base64.b64encode(command.encode()).decode()}"
        self.files = {(f"mission/team/{p}" if self.ws else p): t for p, t in files.items()}
        base_tree = self.base["tree"] if self.base else None
        self.manifest = {"v": 1, "plan": {k: v for k, v in the_plan.items() if k not in ("net", "internet")} | {"timeout_s": inner, "mission": mission,
                                                                                                             "secrets": sorted(secrets.names) if secrets else []},
                         "inputs": {"command": command[:4000], "command_sha256": hashlib.sha256(command.encode()).hexdigest(), "image": sandbox.IMAGE,
                                    "ws_from": self.base["id"] if self.base else None, "workspace_tree": base_tree,
                                    "team_files_sha256": hashlib.sha256(json.dumps(sorted((p, hashlib.sha256(t.encode()).hexdigest()) for p, t in files.items())).encode()).hexdigest(),
                                    "harness_sha256": hashlib.sha256(json.dumps(sorted(sandbox.Sandbox.harness().items())).encode()).hexdigest()}}
        self._seal()

    @property
    def kwargs(self):
        """What Sandbox.run gets beyond what the call site already passes. The queue is the run's mission; AXoR's own readiness
        check runs have one of their own, so a check never waits behind the team's work."""
        queue = "axor:check" if self.user and self.user == getattr(sandbox, "READINESS_USER", None) else self.mission
        return {"hook": self.hook, "size": self.plan["size"], "queue": queue, **({"net": self.plan["net"]} if self.plan.get("net") else {})}

    def event(self, kind, **kv): self.events.append({"at": round(time.time(), 1), "kind": kind, **kv})

    # ---- the per-run endpoint: /rlm/aef/…
    def hook(self, method, sub, body):
        if not sub.startswith("/rlm/aef/"): return 404, {"error": {"message": f"No such endpoint: {sub}", "code": 404}}
        try:
            fn = {"/open": self._open, "/ws/list": self._list, "/ws/get": self._get, "/ws/have": self._have, "/ws/put": self._put, "/ws/commit": self._commit,
                  "/secret": self._secret, "/stats": self._stats}.get(sub[len("/rlm/aef"):])
            if not fn or method != "POST": return 404, {"error": {"message": f"No such endpoint: {sub}", "code": 404}}
            return 200, fn(body if isinstance(body, dict) else {})
        except ExecError as e:
            return 400, {"error": {"message": str(e), "code": 400}}
        except Exception as e:  # noqa: BLE001 - the run gets a plain refusal, AXoR keeps the detail
            log.warning("exec: run %s %s failed: %s", self.sid, sub, e)
            return 500, {"error": {"message": "AXoR couldn't do that for this run.", "code": 500}}

    def _open(self, b):
        h = self.base
        return {"run": self.sid, "mission": self.mission, "task": self.task, "agent": (self.agent or {}).get("id"),
                "agent_dir": f"agents/{_slug((self.agent or {}).get('name'))}-{self.agent['id']}" if self.agent and self.ws else None,
                "workspace": {"on": self.ws, "snapshot": h["id"] if h else None, "files": h["files"] if h else 0, "bytes": h["bytes"] if h else 0},
                "secrets": sorted(self.secrets.names) if self.secrets else [], "sample_s": 2, "live_s": LIVE_S,
                "limits": {"file_bytes": FILE_BYTES, "workspace_bytes": WS_BYTES, "files": WS_FILES, "exclude": list(EXCLUDE), "secret_re": sandbox.SECRET_PATH.pattern}}

    def _seal(self):
        """The manifest's identity: its plan and inputs. Set when the run is planned, and again when it restores its workspace."""
        self.manifest["inputs"]["ws_from"] = self.base["id"] if self.base else None
        self.manifest["inputs"]["workspace_tree"] = self.base["tree"] if self.base else None
        self.manifest["sha256"] = hashlib.sha256(json.dumps({"plan": self.manifest["plan"], "inputs": self.manifest["inputs"]}, sort_keys=True).encode()).hexdigest()

    def _list(self, b):
        if not self.ws: raise ExecError("This run has no workspace.")
        if not self.saves:   # the mission's head NOW: a run that waited for a slot starts from what finished meanwhile, not from what was there when it queued
            self.base = self.store.head(self.comp, self.mission); self._seal()
        self.store.intact(self.comp, self.mission, self.base)   # all of it or nothing: the in-run script starts no command without its workspace
        t = self.store.tree(self.base)
        shared = {}
        for comp in (0, self.comp):   # every team's shared knowledge, then this team's own on top
            self.store.intact(comp, SHARED)
            shared.update(self.store.tree(self.store.head(comp, SHARED))["files"])
        self.allowed |= {v[0] for v in t["files"].values()} | {v[0] for v in shared.values()}
        out = {"snapshot": self.base["id"] if self.base else None, "files": t["files"], "links": t["links"], "shared": shared}
        if self.ckpt and self.task and not any(p.startswith(f".state/task-{self.task}/") for p in t["files"]): out["state_import"] = self.ckpt
        return out

    def _get(self, b):
        parts, left = [], GET_BYTES
        for item in (b.get("want") or [])[:400]:
            if left <= 0: break
            if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int) and item[1] >= 0): raise ExecError("want is [[sha, offset], …]")
            sha, off = item
            if sha not in self.allowed: raise ExecError("This run wasn't given that content.")   # never another mission's, whoever knows its hash
            size = self.store.size(sha) or 0
            data = self.store.read(sha, off, left) if off < size else b""
            left -= max(len(data), 1)
            parts.append({"sha": sha, "offset": off, "data": base64.b64encode(data).decode(), "last": off + len(data) >= size})
        return {"parts": parts}

    def _have(self, b):
        """Which of these contents the run still has to send. Answered from what THIS run was given or sent, never from the whole
        store: a run can't learn whether another mission holds a file by asking for its hash."""
        shas = [s for s in (b.get("shas") or [])[:5000] if isinstance(s, str) and SHA.match(s)]
        return {"missing": [s for s in shas if s not in self.allowed]}

    def _put(self, b):
        if not self.ws: raise ExecError("This run has no workspace.")
        sha, off, last = b.get("sha"), b.get("offset"), bool(b.get("last"))
        if not (isinstance(sha, str) and SHA.match(sha) and isinstance(off, int) and isinstance(b.get("data"), str)): raise ExecError("put is {sha, offset, data, last}")
        try: data = base64.b64decode(b["data"], validate=True)
        except ValueError: raise ExecError("data must be base64")
        self.tmp.mkdir(parents=True, exist_ok=True)
        st = self.parts.get(sha)
        if off == 0: st = self.parts[sha] = {"n": 0, "h": hashlib.sha256(), "path": self.tmp / sha}; open(st["path"], "wb").close()
        if not st or off != st["n"]: raise ExecError("parts arrive in order, from offset 0")
        if st["n"] + len(data) > FILE_BYTES: self._drop(sha); raise ExecError(f"A file is at most {FILE_BYTES // 1_000_000} MB.")
        if self.sent + len(data) > SAVE_BYTES: self._drop(sha); raise ExecError(f"A run sends at most {SAVE_BYTES // 1_000_000} MB of new content.")
        with open(st["path"], "ab") as f: f.write(data)
        st["h"].update(data); st["n"] += len(data); self.sent += len(data)
        if last:
            self.parts.pop(sha)
            if st["h"].hexdigest() != sha:
                os.remove(st["path"]); raise ExecError("The content doesn't match its hash.")
            self.store.adopt(st["path"], sha); self.allowed.add(sha)
        return {"have": st["n"]}

    def _drop(self, sha):
        st = self.parts.pop(sha, None)
        if st:
            try: os.remove(st["path"])
            except OSError: pass

    def _commit(self, b):
        if not self.ws: raise ExecError("This run has no workspace.")
        base = b.get("base")
        if base is not None and not isinstance(base, int): raise ExecError("base is a snapshot id")
        r = self.store.commit(self.comp, self.mission, base, b.get("files") or {}, b.get("links") or {}, allowed=self.allowed, sbx=self.sid,
                              agent=(self.agent or {}).get("id"), tag=self.sid, conflicted=[p for p in b.get("conflicted") or [] if isinstance(p, str)],
                              needles=[v.encode() for v in self.values.values() if len(v) >= 6], skipped=b.get("skipped") or ())
        self.saves += 1
        if r["new"]: self.ws_to = r["snapshot"]
        c = r["changes"]
        for x in c["conflicts"]: self.event("conflict", path=x["path"], kept_as=x["kept_as"])
        for x in c["refused"]:
            if x["why"] in ("outside the workspace", "a link out of the workspace", "contains a credential's value", "its content was never sent", "not a usable path"):
                self.event("refused_save", path=x["path"], why=x["why"])
        self.allowed |= {v[0] for v in r["files"].values()}
        return {"snapshot": r["snapshot"], "new": r["new"], "tree": r["tree"], "changes": c, **({} if b.get("final") else {"files": r["files"]})}

    def _secret(self, b):
        name = b.get("name")
        if not self.secrets or name not in self.secrets.names:
            self.event("secret_refused", name=str(name)[:80]); raise ExecError("This run wasn't granted that credential.")
        v = self.secrets.fetch(name)
        self.values[name] = v
        self.event("secret_given", name=name)
        return {"value": v}

    def _stats(self, b):
        if b.get("live"):   # the run is still going: its figures so far, on its row at once (the panel reads them there); never kept over a final report
            if self.stats is None:
                self.live = {"by": "aef.py inside the run: the run's own report, not AXoR's measurement", "live": True, "at": round(time.time(), 1),
                             **{k: b[k] for k in ("v", "sample_s", "samples", "cpu_seconds", "peak_rss_mb", "peak_procs", "rss_mb", "procs", "wall_s") if isinstance(b.get(k), (int, float)) and not isinstance(b.get(k), bool)}}
                self.db.q("UPDATE mw_sbx SET stats=? WHERE id=? AND status='running'", (json.dumps(self.live), self.sid))
            return {"ok": True}
        b = {k: b[k] for k in ("v", "sample_s", "samples", "cpu_seconds", "peak_rss_mb", "peak_procs", "tree_at_peak", "top", "cgroup", "disk_mb", "gpu", "wall_s",
                               "setup_s", "total_s", "command_exit", "timed_out", "files") if k in b}
        if len(json.dumps(b)) > 200_000: raise ExecError("The measurements are too large.")
        self.stats = {"by": "aef.py inside the run: the run's own report, not AXoR's measurement", **b}
        return {"ok": True}

    # ---- after the pod is gone
    def redact(self, text):
        """The text with every credential value this run was given replaced by its name (the opposite of showing part of a key)."""
        for name, v in self.values.items():
            if len(v) < 6: continue
            for form in (v, base64.b64encode(v.encode()).decode()): text = text.replace(form, f"[credential {name}]")
        return text

    def abort(self):
        """The run never started (the sandbox refused it): nothing of it is kept."""
        try:
            if self.secrets: self.secrets.close()
        except Exception as e:  # noqa: BLE001
            log.warning("exec: run %s: closing its credentials failed: %s", self.sid, e)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def end(self, r):
        """Finishes the run's record: masks the output, writes stats, manifest and snapshot ids on its row; returns the result with them."""
        try:
            if self.secrets: self.secrets.close()
        except Exception as e:  # noqa: BLE001
            log.warning("exec: run %s: closing its credentials failed: %s", self.sid, e); self.event("secret_close_failed")
        shutil.rmtree(self.tmp, ignore_errors=True)
        if not self.stats and getattr(self, "live", None):   # ended without its final report (stopped, killed, out of memory): the last figures it sent
            self.stats = {**self.live, "live": False, "partial": "the run ended without its final report: these are the last figures it sent while running"}
        if self.values:
            r["output"] = self.redact(r.get("output") or "")
            if self.stats: self.stats = json.loads(self.redact(json.dumps(self.stats)))
        net = r.get("net") or {}
        for x in net.get("refused") or []: self.event("refused_connection", host=x.get("host"), why=x.get("why"))
        if self.plan["egress"].get("why"): self.event("internet_withheld", why=self.plan["egress"]["why"])
        head = self.store.row(self.comp, self.ws_to) if self.ws_to else self.base
        self.manifest["result"] = {"image_id": r.get("image_id"), "status": r.get("status"), "exit": r.get("exit"), "seconds": r.get("seconds"),
                                   "ws_to": self.ws_to, "workspace_tree": head["tree"] if head else None, "saves": self.saves,
                                   # the command's own output: AXoR's own @@AXOR- lines carry times, snapshot numbers and measurements, and would
                                   # make two identical runs look different
                                   "output_sha256": hashlib.sha256("\n".join(l for l in (r.get("output") or "").splitlines() if not l.startswith("@@AXOR-")).encode()).hexdigest(),
                                   "net_sha256": hashlib.sha256(json.dumps(net, sort_keys=True).encode()).hexdigest() if net else None,
                                   "stats_reported": bool(self.stats), "events": self.events[:200]}
        try:
            self.db.q("UPDATE mw_sbx SET stats=?, manifest=?, ws_from=?, ws_to=? WHERE id=?",
                      (json.dumps(self.stats) if self.stats else None, json.dumps(self.manifest), self.base["id"] if self.base else None, self.ws_to, self.sid))
        except Exception as e:  # noqa: BLE001 - the run itself went through; its extras didn't reach the row
            log.warning("exec: run %s: couldn't write its record: %s", self.sid, e)
        r["manifest_sha256"] = self.manifest["sha256"]
        if self.stats: r["stats"] = self.stats
        if self.ws: r["workspace"] = {"from": self.base["id"] if self.base else None, "to": self.ws_to, "saves": self.saves}
        return r


def _audit(db, action, user, target, detail):
    """One row in AXoR's audit log (AuthDB.log), where there is one."""
    try: db.log(action, user or "", target or "", "", (detail or "")[:500])
    except Exception as e:  # noqa: BLE001 - the action itself went through
        log.warning("exec: audit %s: %s", action, e)


def _slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "agent").lower()).strip("-")[:40] or "agent"


_STORES = {}


def store(db):
    """The one Store of a database (its tables are made on first use)."""
    with _LOCK:
        s = _STORES.get(id(db))
        if not s or s.db is not db: s = _STORES[id(db)] = Store(db)
        return s


# ---------------------------------------------------------------- what an agent is told
KEPT_BEFORE = "Files written in the sandbox aren't kept: save what matters with file_write. "
KEPT_NOW = ("The command starts in the mission's workspace, and what it leaves there is kept: files, binary files and Git repositories with their branches "
            "are there in this mission's next sandbox run, yours or a teammate's. It is saved when the command ends and whenever you run "
            "`python3 .axor/aef.py save`. Folders: team/ (the team's files, read-only here: change them with file_write; a copy "
            "of them is read-only too, so copy with `cp -r --no-preserve=mode` or `chmod -R u+w` the copy before editing it), shared/ (read-only "
            "knowledge), $AXOR_AGENT_DIR (agents/<you>/, your own notes), artifacts/ (what you hand to others). A docker_job sees this "
            "workspace only for the folders it names in workspace_paths, as of the last save (text files; a link there refuses the job; a clone's "
            ".git is left out); everything else it builds comes from the team's files. Not kept: /tmp, anything outside the "
            "workspace, .env and key files, node_modules, virtualenvs and caches. If a teammate changed the same file meanwhile, theirs stays and yours "
            f"is kept beside it as <file>.conflict-run<id>: merge them. At most {WS_BYTES // 1_000_000} MB, {FILE_BYTES // 1_000_000} MB a file. ")


def describe(text, cfg, internet):
    """sandbox_run's description for a team whose switches are on: what is kept, and what the mission's egress policy allows."""
    if cfg.get("workspace") and KEPT_BEFORE in text: text = text.replace(KEPT_BEFORE, KEPT_NOW)
    eg = cfg.get("egress") or {}
    if internet and eg.get("mode") == "off": text += " This team's policy gives its runs no internet."
    elif internet and eg.get("mode") == "allowlist":
        text += (f" Internet: only these hosts ({', '.join(sorted(h for h in eg.get('hosts') or [] if not index_related(h))) or 'none named'}) and the hosts of the repositories the task declares "
                 "(needs: git:<host>/<owner>/<repo>); every other host is refused.")
        text += (" Packages install only from the package indexes the Owner approved, over https; another index, a mirror or plain http is refused "
                 "(the refusal names the host): don't work around it, say what you need." if eg.get("packages") == "approved"
                 else " No package index is reachable: say so if the task needs to install packages.")
    elif internet and eg.get("mode") in ("public", None):   # the public policy, and a planned run with no policy at all
        text += " Package indexes aren't reachable on this policy (the refusal names the host): a task that installs packages needs the mission's allowlist; don't work around it."
    if internet and eg.get("mode") != "off":
        text += (" For the headless browser, pass the proxy to Playwright yourself: proxy={server, username, password} from $HTTPS_PROXY, and "
                 "args=['--disable-dev-shm-usage'].")
    return text


def brief(r):
    """What an agent hears about a planned run beyond its output: what the workspace kept and what the run used. {} for any other run."""
    out = {}
    ws, st = r.get("workspace"), r.get("stats") or {}
    if ws:
        f = st.get("files") or {}
        out["workspace"] = (f"Saved as snapshot #{ws['to']}: {f.get('added', 0)} added, {f.get('changed', 0)} changed, {f.get('removed', 0)} removed"
                            + (f"; {f['conflicts']} conflict(s): see the output" if f.get("conflicts") else "") if ws.get("to")
                            else f.get("error") and f"NOT saved: {f['error']}" or "Nothing changed in the workspace.")
    if st: out["usage"] = {k: st[k] for k in ("cpu_seconds", "peak_rss_mb", "peak_procs", "wall_s") if k in st} | {"disk_mb": (st.get("disk_mb") or {}).get("work")}
    return out


_BROKERS = {}


def _vault_broker(db):
    """The credential broker for this database's runs when a Vault is set for the server (vault.py, D-033); None otherwise."""
    from . import vault
    if not vault.ADDR: return None
    if id(db) not in _BROKERS: _BROKERS[id(db)] = vault.broker(vault.Vault(), db, sandbox.MAX_TIMEOUT + 600)
    return _BROKERS[id(db)]


def stops(db):
    """The emergency stops that are set: {mission or "*": why}. Empty almost always, and then no run pays for the check."""
    return {r["k"][len("exec.stop:"):]: r["v"] for r in db.q("SELECT k, v FROM app_settings WHERE k LIKE 'exec.stop:%'") if r["v"]}


def mission_of(db, comp_id, task):
    """The mission a task's work belongs to: the task's own mission from AXoR's record, else the team's own (`comp:<id>`). The one
    answer for every path that keys work by mission: the sandbox's workspace, the emergency stop, and a VM job that reads a
    workspace (mining_work._workspace_files)."""
    t = db.q("SELECT * FROM mw_tasks WHERE id=? AND comp_id=?", (task, comp_id), one=True) if task else None
    return (dict(t).get("mission") if t else None) or f"comp:{comp_id}"


_mission_of = mission_of   # the name callers used before it was public


def refusal(db, comp_id, task=None, halted=None):
    """Why a new run of this team's task may not start (an emergency stop covers its mission, or every mission), or None. For
    every path that starts work for a team: sandbox runs ask it in begin(); the VM runner's job path can ask it the same way."""
    halted = stops(db) if halted is None else halted
    if not halted: return None
    if "*" in halted: return f"Runs are stopped (every mission): {halted['*']}"
    mission = _mission_of(db, comp_id, task)
    return f"Runs are stopped ({mission}): {halted[mission]}" if mission in halted else None


_STOPS = [0]   # counts the stops set in this process: a guard that sees it move looks at once, not at its next look


def guard(db, comp_id, task=None, cancelled=lambda: False, every=3.0):
    """The `cancelled` test a run is given, widened by the emergency stop: true once a stop covers the run's mission. A run that
    is already waiting for a slot, or already running, is then ended by the code that was waiting on it, without anyone having to
    find its pod. Looks at most every few seconds, and at once after a stop was set in this process (stop() counts them): a job
    that gets a slot the moment a stopped job frees it must not start on a look that is seconds old. Once true it stays true."""
    state = {"at": 0.0, "hit": False, "seen": _STOPS[0]}
    def check():
        if state["hit"] or cancelled(): return True
        now = time.time()
        if now - state["at"] < every and state["seen"] == _STOPS[0]: return False
        state["at"], state["seen"] = now, _STOPS[0]
        try: state["hit"] = bool(refusal(db, comp_id, task))
        except Exception as e:  # noqa: BLE001 - a failed look is not a stop
            log.warning("exec: stop check failed: %s", e)
        return state["hit"]
    return check


def stop(db, sbx, mission, why, user, sweep_again=3):
    """Emergency termination (directive §8). mission: a mission ref, or "*" for every mission. What happens, in this order:
    - new sandbox runs, VM jobs and recursive queries of it are refused (begin(), and refusal() at the VM job's and the query's
      call sites; for "*" also every other caller of the sandbox, through the sandbox's gate);
    - its work that is waiting for a slot never starts, and its running work is ended by the code that waits on it, through its
      own `cancelled` test (guard()), which looks at once: that code deletes the pod, closes the run's proxy tokens and records
      the run as cancelled;
    - a few seconds later, and once more after that, the pods of whatever is still on record as running are deleted here as
      well, so nothing depends on that test alone. Such a row ends as an error ("the pod disappeared").
    Returns {"mission", "running": [the run ids on record as running when the stop was set], "ended": [the run ids whose pod was
    deleted here]}. Lifting it is resume(); nothing lifts it by itself."""
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    db.setting(f"exec.stop:{mission}", v=f"{(why or 'no reason given')[:200]} ({user}, {stamp})")
    _STOPS[0] += 1
    log.warning("exec: STOP %s by %s: %s", mission, user, why)
    _audit(db, "exec.stop", user, mission, why or "")
    cols = {c["name"] for c in db.q("PRAGMA table_info(mw_tasks)")} if db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mw_tasks'", one=True) else set()
    def running():
        rows = db.q(f"""SELECT s.id, s.comp_id, s.pod, s.services, {'t.mission' if 'mission' in cols else 'NULL'} AS mission FROM mw_sbx s
                        LEFT JOIN mw_tasks t ON t.id=s.task_id WHERE s.status='running'""") if cols else \
            db.q("SELECT id, comp_id, pod, services, NULL AS mission FROM mw_sbx WHERE status='running'")
        return [r for r in rows if mission == "*" or (r["mission"] or f"comp:{r['comp_id']}") == mission]
    covered, ended = [r["id"] for r in running()], []
    for _round in range(2):
        if sweep_again: time.sleep(sweep_again)
        for r in running():
            if r["id"] in ended or not r["pod"]: continue
            ns = sandbox.NS
            if (r["services"] or "") == "vm-docker":
                from . import runner
                ns = runner.NS
            try:
                sbx.kube.delete(f"/api/v1/namespaces/{ns}/pods/{r['pod']}", {"gracePeriodSeconds": 0}); ended.append(r["id"])
            except Exception as e:  # noqa: BLE001 - one pod that can't be deleted doesn't stop the others being stopped
                log.warning("exec: stop: couldn't delete %s/%s: %s", ns, r["pod"], e)
    return {"mission": mission, "running": covered, "ended": ended}


def resume(db, mission, user):
    """Lifts an emergency stop. A person does this; nothing else does."""
    db.q("DELETE FROM app_settings WHERE k=?", (f"exec.stop:{mission}",))
    log.warning("exec: stop of %s lifted by %s", mission, user)
    _audit(db, "exec.resume", user, mission, "")
    return {"mission": mission, "stopped": False}


SLOTS_MAX = max(1, int(os.getenv("EXEC_SLOTS_MAX", "6")))   # the sandbox namespace's quota (12 pods, 16 CPUs) holds about six size-M runs


def slots(db, sbx):
    """Applies the Owner's setting `exec.slots` (D-032e) to the sandbox's slot queue: how many runs go at once. Unset, or not a
    number: the server's default (SANDBOX_MAX_RUNS, 2). Never over SLOTS_MAX. Returns the number in force."""
    v = db.setting("exec.slots")
    n = min(int(v), SLOTS_MAX) if v and str(v).isdigit() and int(v) >= 1 else sandbox.AT_ONCE
    if sbx is not None and hasattr(sbx, "slots") and hasattr(sbx.slots, "resize"): sbx.slots.resize(n)
    return n


def begin(db, w, *, sid, task, agent, user, command, timeout, files, internet, ckpt=None, broker=None, sbx=None):
    """The planned form of a team's sandbox run, or None when the team has no switch on (the run then goes exactly as before).
    Raises LookupError when an emergency stop covers the run's mission, whatever the team's switches. w: the team's row; task: the
    board task's id or None; ckpt: the task's last mw_ckpt checkpoint (base64), imported once into the workspace;
    broker(task_row, mission, sid, agent): the run's granted credentials (vault.py), or None."""
    if sbx is not None and ENABLED: slots(db, sbx)
    cfg, halted, own = settings(db, w["id"]), stops(db), (mission_policies(db, w["id"]) if ENABLED else {})
    on = planned(cfg)
    if not on and not halted and not own: return None
    t = db.q("SELECT * FROM mw_tasks WHERE id=? AND comp_id=?", (task, w["id"]), one=True) if task else None
    mission = (dict(t).get("mission") if t else None) or f"comp:{w['id']}"
    why = refusal(db, w["id"], task, halted)
    if why: raise LookupError(why)
    if (own.get(mission) or {}).get("egress"): cfg, on = {**cfg, "egress": own[mission]["egress"]}, True   # this mission's own reach, in place of its team's
    if not on: return None
    needs = []
    if t:
        from .task_lifecycle import needs_of
        needs = [n for n in needs_of(dict(t)) if n["source"] == "declared"]
    if broker is None: broker = _vault_broker(db)
    secrets = broker(dict(t), mission, sid, agent) if broker and t else None
    p = plan(needs, cfg, internet, approved_indexes(db), spent_today(db, w["id"], mission) if (cfg.get("egress") or {}).get("mode") else None,
             has_secrets=bool(secrets and secrets.names))
    if p["workspace"]:   # a workspace that can't be restored in full: refused here, before a pod exists (the run's own pull checks again)
        st = store(db)
        try:
            st.intact(w["id"], mission)
            for comp in (0, w["id"]): st.intact(comp, SHARED)
        except ExecError as e:
            if secrets: secrets.close()
            raise LookupError(str(e))
    if secrets and secrets.names and not p["internet"] and internet: pass   # the credential is still given: a run without internet can't send it anywhere
    return Session(store(db), db, comp=w["id"], mission=mission, task=task, agent=agent, sid=sid, the_plan=p, command=command, timeout=timeout,
                   files=files, user=user, ckpt=ckpt, secrets=secrets)


# ---------------------------------------------------------------- reading it back: the execution history and its API
def _j(s, d=None):
    try: return json.loads(s) if s else d
    except ValueError: return d


def _cols(db, table): return {c["name"] for c in db.q(f"PRAGMA table_info({table})")}


def _run_out(r, full=False):
    """One run for a reader: the row's facts, its measurements, its manifest's headline; `full` adds everything kept."""
    net, st, m = _j(r.get("net"), {}) or {}, _j(r.get("stats")), _j(r.get("manifest"))
    res, pl = (m or {}).get("result") or {}, (m or {}).get("plan") or {}
    out = {"id": r["id"], "team": r["comp_id"], "task": r["task_id"], "agent": r["agent_id"], "by": r.get("by_user"), "mission": r.get("mission") or f"comp:{r['comp_id']}",
           "kind": "vm" if (r.get("services") or "") == "vm-docker" else "sandbox", "command": (r.get("command") or "")[:300], "status": r["status"], "exit": r["exit_code"],
           "started": r["started"], "finished": r["finished"], "pod": r["pod"], "planned": bool(m) or bool(st and st.get("live")), "live": bool(st and st.get("live")), "size": pl.get("size"), "egress": (pl.get("egress") or {}).get("mode"),
           "hosts": len(net.get("hosts") or {}), "refused": len(net.get("refused") or []), "up_bytes": net.get("up_bytes"), "down_bytes": net.get("down_bytes"),
           "cpu_seconds": (st or {}).get("cpu_seconds"), "peak_rss_mb": (st or {}).get("peak_rss_mb"), "peak_procs": (st or {}).get("peak_procs"),
           "disk_mb": ((st or {}).get("disk_mb") or {}).get("work"), "ws_from": r.get("ws_from"), "ws_to": r.get("ws_to"), "events": len(res.get("events") or []),
           "manifest_sha256": (m or {}).get("sha256"), "image_id": res.get("image_id")}
    if full: out.update(output=(r.get("output") or "")[-20000:], error=r.get("error"), net=net, stats=st, manifest=m, source=_j(r.get("src")))
    return out


def search(db, comps, q="", team=None, mission=None, agent=None, status=None, host=None, since=None, until=None, limit=50):
    """Runs of the teams in `comps` (None: every team), newest first. q looks in the command, the output and the error; host in
    the hosts a run reached or was refused."""
    if not db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mw_sbx'", one=True): return []
    sc = _cols(db, "mw_sbx")
    tm = "t.mission" if db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mw_tasks'", one=True) and "mission" in _cols(db, "mw_tasks") else "NULL"
    join = "LEFT JOIN mw_tasks t ON t.id=s.task_id" if tm != "NULL" else ""
    extra = ", ".join(f"s.{c}" if c in sc else f"NULL AS {c}" for c in ("net", "src", "stats", "manifest", "ws_from", "ws_to"))
    where, args = ["1=1"], []
    if comps is not None:
        if not comps: return []
        where.append(f"s.comp_id IN ({','.join('?' * len(comps))})"); args += list(comps)
    if team: where.append("s.comp_id=?"); args.append(int(team))
    if agent: where.append("s.agent_id=?"); args.append(int(agent))
    if status: where.append("s.status=?"); args.append(str(status))
    if since: where.append("s.started>=?"); args.append(float(since))
    if until: where.append("s.started<=?"); args.append(float(until))
    like = lambda x: "%" + str(x).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if q: where.append("(s.command LIKE ? ESCAPE '\\' OR s.output LIKE ? ESCAPE '\\' OR s.error LIKE ? ESCAPE '\\')"); args += [like(q)] * 3
    if host and "net" in sc: where.append("s.net LIKE ? ESCAPE '\\'"); args.append(like('"' + str(host).lower()))
    if mission: where.append(f"COALESCE({tm}, 'comp:' || s.comp_id)=?" if tm != "NULL" else "('comp:' || s.comp_id)=?"); args.append(str(mission))
    rows = db.q(f"""SELECT s.id, s.comp_id, s.task_id, s.agent_id, s.by_user, s.command, s.services, s.status, s.exit_code, s.started, s.finished, s.pod, {extra},
                           {tm} AS mission FROM mw_sbx s {join} WHERE {' AND '.join(where)} ORDER BY s.id DESC LIMIT ?""", (*args, max(1, min(int(limit or 50), 200))))
    return [_run_out(dict(r)) for r in rows]


def record(db, sid):
    """Everything kept about one run, or None."""
    sc = _cols(db, "mw_sbx")
    extra = ", ".join(f"s.{c}" if c in sc else f"NULL AS {c}" for c in ("net", "src", "stats", "manifest", "ws_from", "ws_to"))
    tm = "t.mission" if db.q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mw_tasks'", one=True) and "mission" in _cols(db, "mw_tasks") else "NULL"
    r = db.q(f"""SELECT s.id, s.comp_id, s.task_id, s.agent_id, s.by_user, s.command, s.services, s.status, s.exit_code, s.output, s.error, s.started, s.finished, s.pod,
                        {extra}, {tm} AS mission FROM mw_sbx s {'LEFT JOIN mw_tasks t ON t.id=s.task_id' if tm != 'NULL' else ''} WHERE s.id=?""", (sid,), one=True)
    return _run_out(dict(r), full=True) if r else None


SECURITY = {"refused_connection": "A connection was refused", "refused_save": "A file was refused from a workspace save", "conflict": "Two runs changed the same file",
            "secret_refused": "A credential was asked for and refused", "secret_given": "A credential was given to a run", "internet_withheld": "A run was given no internet",
            "secret_close_failed": "A run's credential access couldn't be revoked cleanly"}


def events(db, comps, since=None, limit=200):
    """Security events of the teams in `comps` (None: all), newest first: what runs were refused, cut off or given, and the stops.
    Read from the runs' own records and the audit log; nothing is stored twice."""
    out = []
    for r in search(db, comps, since=since, limit=200):
        full = record(db, r["id"])
        for x in (full["net"].get("refused") or []):
            out.append({"at": x.get("at") or full["finished"] or full["started"], "run": r["id"], "team": r["team"], "mission": r["mission"], "kind": "refused_connection",
                        "what": SECURITY["refused_connection"], "detail": f"{x.get('host')}: {x.get('why')}"})
        for e in ((full["manifest"] or {}).get("result") or {}).get("events") or []:
            if e.get("kind") == "refused_connection": continue   # listed from the network record above
            out.append({"at": e.get("at"), "run": r["id"], "team": r["team"], "mission": r["mission"], "kind": e.get("kind"), "what": SECURITY.get(e.get("kind"), e.get("kind")),
                        "detail": ", ".join(f"{k}: {v}" for k, v in e.items() if k not in ("at", "kind"))})
        if full["status"] == "error" and "pod disappeared" in (full["error"] or ""):
            out.append({"at": full["finished"] or full["started"], "run": r["id"], "team": r["team"], "mission": r["mission"], "kind": "ended", "what": "A run was ended from outside",
                        "detail": full["error"]})
    if comps is None:   # the server-wide rows: stops, and credential reads and refusals (names only, never values)
        for a in db.q("SELECT ts, actor, action, target, detail FROM audit WHERE (action LIKE 'exec.%' OR action LIKE 'secret.%') AND ts>=? ORDER BY ts DESC LIMIT 200", (float(since or 0),)):
            out.append({"at": a["ts"], "run": int(a["actor"][4:]) if a["actor"].startswith("run:") and a["actor"][4:].isdigit() else None, "team": None, "mission": None,
                        "kind": a["action"], "what": {"exec.stop": "Runs were stopped", "exec.resume": "A stop was lifted", "secret.read": "A credential was read for a run",
                                                      "secret.refused": "A credential was refused", "secret.closed": "A run's credential access was revoked",
                                                      "secret.read_failed": "A credential couldn't be read"}.get(a["action"], a["action"]),
                        "detail": f"{a['target']}: {a['detail']}" if a["detail"] else a["target"], "by": a["actor"]})
    out.sort(key=lambda e: -(e.get("at") or 0))
    return out[:max(1, min(int(limit), 500))]


def replay(work, comp, sid, user):
    """Runs a planned run's manifest again: the same command, the same image, the workspace content it started from (restored
    into a scratch mission of its own), the same size and egress mode. Starts it and returns the new run's id; when it ends, its
    manifest's result holds {"replay": {of, same_image, same_output, same_workspace, same_team_files}}. A run that used the network
    or the clock won't match byte for byte: the comparison says which part differed, it doesn't call that a failure."""
    db = work.db
    src = record(db, sid)
    if not src or src["team"] != comp or not src["manifest"]: raise ExecError("Only a planned sandbox run of this team can be run again.")
    if src["kind"] != "sandbox": raise ExecError("VM jobs are run again from their own job record.")
    halted = stops(db)   # an emergency stop of the run's mission covers running it again, whoever asks
    if src.get("mission") in halted: raise ExecError(f"Runs are stopped ({src['mission']}): {halted[src['mission']]}")
    m, st = src["manifest"], store(db)
    mission = f"replay:{sid}:{int(time.time())}"
    base = st.row(comp, m["inputs"].get("ws_from")) if m["inputs"].get("ws_from") else None
    if m["inputs"].get("ws_from") and (not base or base["tree"] != m["inputs"].get("workspace_tree")):
        raise ExecError("The snapshot this run started from is no longer kept, so it can't be run again from the same content.")
    if base:
        t = st.tree(base)
        st.commit(comp, mission, None, t["files"], t["links"], user=user, note=f"replay of run #{sid}: the workspace it started from")
    files = {f["path"]: f["content"] for f in db.q("SELECT path, content FROM mw_files WHERE comp_id=?", (comp,))}
    eg, pl = m["plan"].get("egress") or {}, m["plan"]
    internet = eg.get("mode") in ("allowlist", "public", "inherit")
    cfg = {"plan": 1, "workspace": 1 if pl.get("workspace") else 0,
           "egress": {"mode": eg["mode"], "hosts": eg.get("hosts") or [], **({"packages": "approved"} if eg.get("package_hosts") else {})} if eg.get("mode") in ("allowlist", "public") else {}}
    p = plan([{"cap": "ram", "value": "8", "source": "declared"}] if pl.get("size") == "L" else [], cfg, internet, approved_indexes(db))
    new = db.q("INSERT INTO mw_sbx (comp_id, by_user, command, services, status, started) VALUES (?,?,?,?,'running',?) RETURNING id",
               (comp, f"replay of #{sid} ({user})", m["inputs"]["command"][:4000], "", time.time()), one=True)["id"]
    s = Session(st, db, comp=comp, mission=mission, task=None, agent=None, sid=new, the_plan=p, command=m["inputs"]["command"], timeout=pl.get("timeout_s") or 600,
                files=files, user=user)

    def go():
        try:
            r = work.sbx.run(s.files, s.command, [], s.timeout, 0.05, label=f"replay of #{sid}", started=lambda pod: db.q("UPDATE mw_sbx SET pod=? WHERE id=?", (pod, new)),
                             internet=s.internet, **s.kwargs)
            r = s.end(r)
            res = s.manifest["result"]
            cmp_ = {"of": sid, "same_image": res.get("image_id") == m["result"].get("image_id"), "same_output": res.get("output_sha256") == m["result"].get("output_sha256"),
                    "same_workspace": res.get("workspace_tree") == m["result"].get("workspace_tree"),
                    "same_team_files": s.manifest["inputs"]["team_files_sha256"] == m["inputs"].get("team_files_sha256"),
                    "same_request": s.manifest["inputs"]["command_sha256"] == m["inputs"].get("command_sha256")}
            s.manifest["result"]["replay"] = cmp_
            net = {**(r.get("net") or {}), "withheld": r.get("withheld") or []} if "net" in r else None
            db.q("UPDATE mw_sbx SET status=?, exit_code=?, output=?, error=?, finished=?, net=?, manifest=? WHERE id=?",
                 (r["status"], r["exit"], r["output"], r["error"] or None, time.time(), json.dumps(net) if net else None, json.dumps(s.manifest), new))
        except Exception as e:  # noqa: BLE001 - the replay's own row says what happened
            s.abort()
            db.q("UPDATE mw_sbx SET status='error', error=?, finished=? WHERE id=?", (str(e)[:500], time.time(), new))
    threading.Thread(target=go, daemon=True, name=f"exec-replay-{new}").start()
    _audit(db, "exec.replay", user, f"run:{sid}", f"as run {new}")
    return {"run": new, "of": sid, "mission": mission}


def build(work, require):
    """The HTTP API (AEF_05 §6): /api/exec. Members see their own teams' runs and workspaces; administrators see all, set a team's
    policy, stop and resume, and run a manifest again. The number of runs at once is the Owner's."""
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel

    db = work.db
    # an emergency stop of every mission holds for every caller of the sandbox (a team's run, rlm_query, a readiness check), not only the planned path
    work.sbx.gate = lambda: refusal(db, 0, None, {k: v for k, v in stops(db).items() if k == "*"})
    r = APIRouter(prefix="/api/exec")
    gate = work.m.hub.gate if getattr(work.m, "hub", None) else (lambda me: me)
    user = lambda req: gate(require(req))
    admin = lambda me: me.get("role") == "admin"

    def teams(me):
        """The teams this person may read: None for an administrator (all), else their own campaigns' teams."""
        if admin(me): return None
        return [x["id"] for x in db.q("SELECT w.id FROM mw_comps w JOIN mh_campaigns c ON c.id=w.campaign_id WHERE c.user_id=?", (me["id"],))]

    def own(me, team):
        if admin(me):
            if not db.q("SELECT 1 FROM mw_comps WHERE id=?", (team,), one=True): raise HTTPException(404, "There's no such team.")
        else: work._own(me, team)   # 404 for a team that isn't theirs
        return int(team)

    def only_admin(me):
        if not admin(me): raise HTTPException(403, "Only an administrator can do this.")

    def owner(me):
        from . import missions
        if not missions.is_owner(db, me): raise HTTPException(403, "Only the Owner sets this.")

    def guard(fn):
        try: return fn()
        except ExecError as e: raise HTTPException(400, str(e))

    @r.get("/status")
    def status(req: Request):
        me = user(req)
        mine = teams(me)
        ids = [x["id"] for x in db.q("SELECT id FROM mw_comps")] if mine is None else mine
        out = {"enabled": ENABLED, "slots": work.sbx.slots.state() if hasattr(work.sbx, "slots") and hasattr(work.sbx.slots, "state") else None,
               "slots_setting": db.setting("exec.slots"), "slots_max": SLOTS_MAX, "stops": stops(db), "teams": {i: settings(db, i) for i in ids if settings(db, i)},
               "sizes": {k: {"cpu": v[0], "memory": v[1], "slots": v[2]} for k, v in sandbox.SIZES.items()},
               "limits": {"workspace_mb": WS_BYTES // 1_000_000, "file_mb": FILE_BYTES // 1_000_000, "files": WS_FILES, "snapshots_kept": KEEP}}
        if admin(me):
            from . import vault
            v = vault.Vault()
            ok, why = v.ready() if v.enabled else (False, "No Vault is set for this server.")
            out["vault"] = {"set": v.enabled, "ready": ok, "why": why}
            out["package_hosts"] = list(approved_indexes(db))
            try: out["egress"] = work.sbx.egress.status()
            except Exception as e:  # noqa: BLE001
                out["egress"] = {"ready": False, "why": str(e)[:200]}
        return out

    @r.get("/runs")
    def runs(req: Request, q: str = "", team: int = 0, mission: str = "", agent: int = 0, status: str = "", host: str = "", since: float = 0, until: float = 0, limit: int = 50):
        me = user(req)
        return {"runs": search(db, teams(me), q.strip()[:200], team or None, mission or None, agent or None, status or None, host.strip()[:200] or None, since or None, until or None, limit)}

    def one(me, sid):
        rec = record(db, sid)
        mine = teams(me)
        if not rec or (mine is not None and rec["team"] not in mine): raise HTTPException(404, "There's no such run.")
        return rec

    @r.get("/runs/{sid}")
    def run_(req: Request, sid: int):
        rec = one(user(req), sid)
        if rec.get("ws_to"):
            row = store(db).row(rec["team"], rec["ws_to"])
            rec["workspace_changes"] = _j(row["changes"], {}) if row else None
        return rec

    @r.post("/runs/{sid}/replay")
    def replay_(req: Request, sid: int):
        me = user(req); only_admin(me)
        rec = one(me, sid)
        return guard(lambda: replay(work, rec["team"], sid, me["username"]))

    @r.get("/events")
    def events_(req: Request, since: float = 0, limit: int = 200):
        return {"events": events(db, teams(user(req)), since or time.time() - 7 * 86400, limit)}

    @r.get("/workspaces/{team}")
    def workspaces(req: Request, team: int, mission: str = ""):
        own(user(req), team)
        st = store(db)
        if not mission:
            ms = db.q("SELECT mission, MAX(id) AS head, COUNT(*) AS snapshots FROM mw_ws WHERE comp_id=? GROUP BY mission ORDER BY MAX(id) DESC", (team,))
            return {"missions": [dict(x) | {"files": (h := st.row(team, x["head"]))["files"], "bytes": h["bytes"], "updated": h["created"], "whole": not st.problems(h, 0)} for x in ms]}
        return {"mission": mission, "snapshots": [{k: s_[k] for k in ("id", "parent", "tree", "files", "bytes", "sbx_id", "agent_id", "by_user", "note", "created", "kept")} |
                                                  {"counts": (s_["changes"] or {}).get("counts")} for s_ in st.snapshots(team, mission, 100)]}

    @r.get("/workspaces/{team}/snapshots/{snapshot}")
    def snapshot_(req: Request, team: int, snapshot: int, path: str = ""):
        own(user(req), team)
        st = store(db)
        row = st.row(team, snapshot)
        if not row: raise HTTPException(404, "There's no such snapshot.")
        t = st.tree(row)
        if not path:
            return {"id": row["id"], "mission": row["mission"], "note": row["note"], "created": row["created"], "changes": _j(row["changes"], {}), "missing": st.problems(row, 50),
                    "files": [{"path": p, "sha256": v[0], "bytes": v[1], "exec": bool(v[2] & 0o100)} for p, v in sorted(t["files"].items())], "links": t["links"]}
        v = t["files"].get(path)
        if not v: raise HTTPException(404, "The snapshot has no such file.")
        out = {"path": path, "sha256": v[0], "bytes": v[1]}
        if v[1] <= 300_000:
            raw = st.read(v[0])
            try: out["text"] = raw.decode("utf-8")
            except UnicodeDecodeError: out["binary"] = True
        else: out["too_large"] = True
        return out

    class Rollback(BaseModel):
        mission: str
        snapshot: int

    @r.post("/workspaces/{team}/rollback")
    def rollback(req: Request, team: int, b: Rollback):
        me = user(req); own(me, team)
        out = guard(lambda: store(db).rollback(team, b.mission, b.snapshot, me["username"]))
        _audit(db, "exec.rollback", me["username"], f"team:{team} {b.mission}", f"to snapshot {b.snapshot} as {out['snapshot']}")
        return out

    class Keep(BaseModel):
        snapshot: int
        kept: bool = True

    @r.post("/workspaces/{team}/keep")
    def keep(req: Request, team: int, b: Keep):
        own(user(req), team)
        guard(lambda: store(db).keep(team, b.snapshot, b.kept))
        return {"snapshot": b.snapshot, "kept": b.kept}

    @r.get("/policy/{team}")
    def policy(req: Request, team: int):
        own(user(req), team)
        return {"team": team, "policy": settings(db, team), "missions": mission_policies(db, team), "package_hosts": list(approved_indexes(db))}

    class Policy(BaseModel):
        plan: bool = False
        workspace: bool = False
        egress: dict = {}

    @r.put("/policy/{team}")
    def set_policy(req: Request, team: int, b: Policy, mission: str = ""):
        """The team's policy; with ?mission=<ref>, that mission's own egress policy in place of the team's (an empty one removes it)."""
        me = user(req); only_admin(me); own(me, team)
        mission = mission.strip()
        if mission and not re.fullmatch(r"[A-Za-z0-9:_.-]{1,80}", mission): raise HTTPException(400, "That isn't a mission reference.")
        eg = {}
        if b.egress:
            mode = b.egress.get("mode")
            if mode not in (None, "", "off", "allowlist", "public"): raise HTTPException(400, "The egress mode is off, allowlist or public.")
            hosts = sorted({str(h).lower().strip(".") for h in b.egress.get("hosts") or []})
            if any(not re.fullmatch(r"[a-z0-9.-]{3,253}", h) for h in hosts) or len(hosts) > 40: raise HTTPException(400, "Hosts are host names (at most 40): no address, port or path.")
            idx = [h for h in hosts if index_related(h)]
            if idx: raise HTTPException(400, f"{', '.join(idx)}: a package index (or a name over or under one) can't be put on a host list. Package installs go "
                                              "through the Owner's approved list: set packages to approved on an allowlist.")
            pk = b.egress.get("packages")
            if pk not in (None, "", "approved"): raise HTTPException(400, "packages is approved, or left out.")
            if pk == "approved" and mode != "allowlist":
                raise HTTPException(400, "Package installs need the allowlist mode: in public mode no package index is reachable, by the Owner's decision.")
            if mode == "allowlist" and not hosts and pk != "approved": raise HTTPException(400, "An allowlist needs at least one host.")
            if mode: eg["mode"] = mode
            if hosts: eg["hosts"] = hosts
            if pk == "approved": eg["packages"] = "approved"
            for k in ("up_mb_day", "down_mb_day"):
                v = b.egress.get(k)
                if v is not None:
                    if not isinstance(v, (int, float)) or v <= 0: raise HTTPException(400, f"{k} is a number of megabytes above 0.")
                    eg[k] = v
        if mission and eg and not eg.get("mode"): raise HTTPException(400, "A mission's own policy needs a mode: off, allowlist or public.")
        new = {"egress": eg} if mission and eg else {} if mission else {**({"plan": 1} if b.plan else {}), **({"workspace": 1} if b.workspace else {}), **({"egress": eg} if eg else {})}
        key = f"exec.mission:{team}:{mission}" if mission else f"exec.comp:{team}"
        before = db.setting(key) or "{}"
        if new: db.setting(key, v=json.dumps(new, sort_keys=True))
        else: db.q("DELETE FROM app_settings WHERE k=?", (key,))
        _audit(db, "exec.policy", me["username"], f"team:{team}" + (f" {mission}" if mission else ""), f"{before} -> {json.dumps(new, sort_keys=True)}")
        return {"team": team, **({"mission": mission} if mission else {}), "policy": new}

    class Slots(BaseModel):
        slots: int

    @r.put("/slots")
    def set_slots(req: Request, b: Slots):
        me = user(req); owner(me)
        if not 1 <= b.slots <= SLOTS_MAX: raise HTTPException(400, f"Between 1 and {SLOTS_MAX} runs at once.")
        db.setting("exec.slots", v=str(b.slots))
        _audit(db, "exec.slots", me["username"], "sandbox", str(b.slots))
        return {"slots": slots(db, work.sbx)}

    class Stop(BaseModel):
        mission: str = ""
        all: bool = False
        why: str = ""

    @r.post("/stop")
    def stop_(req: Request, b: Stop):
        me = user(req); only_admin(me)
        if not b.all and not b.mission.strip(): raise HTTPException(400, "Name the mission, or say all.")
        return stop(db, work.sbx, "*" if b.all else b.mission.strip()[:120], b.why, me["username"])

    @r.delete("/stop")
    def resume_(req: Request, mission: str = "", all: bool = False):
        me = user(req); only_admin(me)
        return resume(db, "*" if all else mission.strip()[:120], me["username"])

    return r
