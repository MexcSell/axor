"""My subnets' Scribe, saving to My workspace: each finished step's Markdown file (the same page it commits to GitHub) goes to
the campaign owner's AXoR Drive, in My drive or the Shared drive, at

    My subnets / sn<netuid> / competition-<n> / <date> / <time>-cycle-<id> / <step>.md

with a README.md in the competition folder rewritten after every cycle (the latest brief and the cycles saved). It needs no
GitHub and no administrator: the drive is the owner's own. It runs on the Scribe's thread (mining.py), one write at a
time, and records each file in mh_drive_saves, apart from mh_journal (GitHub's commits), so either can be on alone.
The setting is the journal's `drive` (on unless turned off) and `space` (mine or shared); nothing is written when the server
has no drive (DRIVE_URL).
"""
import json, logging, time

from .drive import DriveError

log = logging.getLogger("mining.save")
TOP = "My subnets"


class DriveSaver:
    def __init__(self, m):
        self.m, self.db = m, m.db
        self.folders = {}  # (user id, space, path) -> drive folder id
        self.db.q("""CREATE TABLE IF NOT EXISTS mh_drive_saves (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, cycle_id INTEGER, step TEXT,
                     space TEXT, path TEXT, node_id TEXT, root_id TEXT, status TEXT, error TEXT, ts REAL)""")
        self.db.q("CREATE INDEX IF NOT EXISTS mh_drive_saves_c ON mh_drive_saves (campaign_id, id)")

    @property
    def drive(self):
        d = getattr(self.m, "drive", None)
        return d if d and d.enabled else None

    def on(self, c):
        j = c["settings"]["journal"]
        return bool(j.get("drive") and self.drive)

    @staticmethod
    def root(c):
        return [TOP, f"sn{c['netuid']}", f"competition-{c['mech'] + 1}"]

    def cycle_dir(self, c, cyid):
        r = self.db.q("SELECT started FROM mh_cycles WHERE id=?", (cyid,), one=True)
        t = time.gmtime((r or {}).get("started") or time.time())
        return self.root(c) + [time.strftime("%Y-%m-%d", t), f"{time.strftime('%H%M%S', t)}-cycle-{cyid}"]

    # ---------- a step's file ----------
    def submit(self, c, cyid, step, file, text):
        """Queues a finished step's page for the owner's drive (on the Scribe's thread, after any earlier write)."""
        if not self.on(c) or not cyid: return
        space = c["settings"]["journal"].get("space") or "mine"
        path = self.cycle_dir(c, cyid) + [f"{file}.md"]
        sid = self.m._ins("INSERT INTO mh_drive_saves (campaign_id, cycle_id, step, space, path, status, ts) VALUES (?,?,?,?,?,'pending',?)",
                          (c["id"], cyid, step, space, "/".join(path), time.time()))
        self.m._bump()
        self.m.scribe.submit(self._write, c["id"], cyid, sid, space, path, text)

    def _folder(self, me, space, path):
        key = (me["id"], space, tuple(path))
        if key not in self.folders:
            self.folders[key] = self.drive.call("POST", "/v1/folders/ensure", me, body={"space": space, "parent": None, "path": list(path)})["id"]
        return self.folders[key]

    def _put(self, me, space, path, text, netuid):
        """(node id, competition folder id). A folder that went away since (trashed) is made again, once."""
        data = text.encode()
        for again in (False, True):
            try:
                parent = self._folder(me, space, path[:-1])
                x = self.drive.call("PUT", "/v1/files", me, {"space": space, "parent": parent, "name": path[-1], "netuid": netuid, "conflict": "version"},
                                    None, {"Content-Type": "application/octet-stream", "Content-Length": str(len(data))}, data, 120)
                return x.get("id"), self._folder(me, space, path[:3])
            except DriveError as e:
                if again or e.status != 404: raise
                self.folders = {k: v for k, v in self.folders.items() if k[0] != me["id"]}

    def _write(self, cid, cyid, sid, space, path, text):
        c = self.db.q("SELECT id, user_id, netuid FROM mh_campaigns WHERE id=?", (cid,), one=True)
        if not c:
            self.db.q("UPDATE mh_drive_saves SET status='failed', error='The campaign was deleted.' WHERE id=?", (sid,))
            return
        if not self.drive:
            self.db.q("UPDATE mh_drive_saves SET status='failed', error='File storage isn''t available on this server.' WHERE id=?", (sid,))
            return
        me = self.m._owner(c)
        self.m._agent(cid, "scribe", "working", f"Saving {path[-1]} to My workspace")
        try: node, root = self._put(me, space, path, text, c["netuid"])
        except DriveError as e: msg = str(e)
        except Exception as e:  # noqa: BLE001 - recorded on the row; the next step tries again
            log.exception("mining drive save: %s", "/".join(path))
            msg = f"It failed: {e}"
        else:
            self.db.q("UPDATE mh_drive_saves SET status='saved', node_id=?, root_id=?, error=NULL, ts=? WHERE id=?", (node, root, time.time(), sid))
            self.m._agent(cid, "scribe", "ok", f"Saved {path[-1]} to My workspace")
            self.m._bump()
            return
        self.db.q("UPDATE mh_drive_saves SET status='failed', error=?, ts=? WHERE id=?", (msg[:400], time.time(), sid))
        self.m._agent(cid, "scribe", "error", f"Couldn't save {path[-1]} to My workspace: {msg}"[:300], error=True)
        first = self.db.q("SELECT COUNT(*) n FROM mh_drive_saves WHERE cycle_id=? AND status='failed'", (cyid,), one=True)["n"] <= 1
        if first: self.m._event(cid, "scribe", "error", f"Couldn't save {path[-1]} to My workspace: {msg}")
        self.m._bump()

    # ---------- the README, after a cycle ----------
    def index(self, cid, cyid):
        c = self.m._campaign(cid)
        if not self.on(c) or not self.db.q("SELECT 1 FROM mh_drive_saves WHERE cycle_id=? AND step!='index'", (cyid,), one=True): return
        space = c["settings"]["journal"].get("space") or "mine"
        path = self.root(c) + ["README.md"]
        sid = self.m._ins("INSERT INTO mh_drive_saves (campaign_id, cycle_id, step, space, path, status, ts) VALUES (?,?,'index',?,?,'pending',?)",
                          (cid, cyid, space, "/".join(path), time.time()))
        self.m.scribe.submit(self._write_index, cid, cyid, sid, space, path)

    def _write_index(self, cid, cyid, sid, space, path):
        try: c = self.m._campaign(cid)
        except Exception:  # noqa: BLE001 - deleted since
            self.db.q("UPDATE mh_drive_saves SET status='failed', error='The campaign was deleted.' WHERE id=?", (sid,))
            return
        root = "/".join(self.root(c)) + "/"
        cycles = {}
        for r in self.db.q("SELECT cycle_id, step, path FROM mh_drive_saves WHERE campaign_id=? AND space=? AND step!='index' AND status='saved' "
                           "ORDER BY cycle_id DESC, id LIMIT 600", (cid, space)):
            if r["path"].startswith(root): cycles.setdefault(r["cycle_id"], []).append(r["path"][len(root):])
        if cyid not in cycles:
            self.db.q("UPDATE mh_drive_saves SET status='failed', error='No step file was saved this cycle, so the README stays as it was.', ts=? WHERE id=?",
                      (time.time(), sid))
            return
        b = self.db.q("SELECT * FROM mh_briefs WHERE campaign_id=? ORDER BY id DESC LIMIT 1", (cid,), one=True)
        tone = {"green": "on track", "amber": "needs a look", "red": "action needed"}
        md = [f"# My subnets: SN{c['netuid']} {self.m._name(c)}, {self.m._comp(c)}", "",
              f"The agent team's results for a top {c['settings']['target']} place: one folder per cycle, one file per step, saved by AXoR's Scribe "
              "as each step finished. This README is rewritten after every cycle.", ""]
        if b:
            md += ["## Latest brief", "", f"**{b['headline']}** ({tone.get(b['standing'], b['standing'])}; cycle {b['cycle_id']}, "
                   f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(b['ts']))} UTC)", ""]
            if b["summary"]: md += [b["summary"], ""]
            md += [f"{i}. {p}" for i, p in enumerate(json.loads(b["priorities"] or "[]"), 1)] + [""]
        md += ["## Cycles", ""]
        for cy, files in list(cycles.items())[:40]:
            md += [f"- Cycle {cy}: " + ", ".join(f"`{f}`" for f in sorted(files))]
        self._write(cid, cyid, sid, space, path, "\n".join(md) + "\n")

    # ---------- what Settings and the Scribe's card show ----------
    def view(self, c):
        j = c["settings"]["journal"]
        last = self.db.q("SELECT status, error, ts, root_id, space FROM mh_drive_saves WHERE campaign_id=? AND (status='saved' OR (status='failed' AND step!='index')) "
                         "ORDER BY id DESC LIMIT 1", (c["id"],), one=True)
        folder = self.db.q("SELECT root_id, space FROM mh_drive_saves WHERE campaign_id=? AND status='saved' AND root_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                           (c["id"],), one=True)
        return {"on": bool(j.get("drive")), "space": j.get("space") or "mine", "enabled": bool(self.drive), "path": "/".join(self.root(c)),
                "last": {k: last[k] for k in ("status", "error", "ts")} if last else None,
                "folder": folder and {"id": folder["root_id"], "space": folder["space"]},
                "saved_day": self.db.q("SELECT COUNT(*) n FROM mh_drive_saves WHERE campaign_id=? AND status='saved' AND ts>?",
                                       (c["id"], time.time() - 86400), one=True)["n"]}
