"""Automatic updates: the Cluster page's Updates tab (admins only).

k8s/auto-update.sh, a systemd timer on the k3s host, deploys each new commit on a branch of AXoR's repository (main by
default) with k8s/deploy.sh, and rolls back when the rollout or the health check fails. It only moves forward, and a
commit that failed isn't tried again until a newer one lands or someone asks. AXoR never builds or deploys itself: it
reads what the updater reports (ConfigMap axor-update-status) and writes only requests to it (ConfigMap axor-update,
the one object here AXoR may change): pause, check now, update now, or deploy the branch even though it doesn't contain
the running commit. The updater picks a request up on its next pass, within a minute.
Reads need an admin session; changes need sudo and are audited (update.*), except asking for a check.
"""
import re, secrets, time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .kube import KubeError

NS, SETTINGS, STATUS = "axor", "axor-update", "axor-update-status"
STALE = 300  # seconds without a pass before the page says the updater stopped reporting (it runs a pass every minute)
SETUP = "The updater isn't installed on this server. As root on the k3s host: ./k8s/auto-update.sh --install"
NO_RIGHTS = "AXoR may not read the updater's status yet: deploy this version once (k8s/deploy.sh) to give it the rights."

def _int(v):
    try: return int(v)
    except (TypeError, ValueError): return None

def _commit(line):
    """A 'sha<TAB>unix time<TAB>author<TAB>subject' line, as the updater writes them."""
    sha, t, author, subject = (line.strip("\r\n").split("\t", 3) + ["", "", ""])[:4]
    return {"sha": sha, "time": _int(t), "author": author, "subject": subject}

def _run(line):
    started, finished, sha, result, by, note = (line.split("\t", 5) + [""] * 6)[:6]
    return {"started": _int(started), "finished": _int(finished), "sha": sha, "result": result, "by": by or None, "note": note}

class Updates:
    def __init__(self, db, kube):
        self.db, self.k = db, kube

    def _map(self, name):
        try: return self.k.get(f"/api/v1/namespaces/{NS}/configmaps/{name}")
        except KubeError as e:
            if e.status == 403: raise HTTPException(503, NO_RIGHTS)
            raise

    def status(self):
        st = self._map(STATUS)
        if not st: return {"installed": False, "message": SETUP}
        clean = lambda m: {k: (v or "").strip() for k, v in ((m or {}).get("data") or {}).items()}
        d, c = clean(st), clean(self._map(SETTINGS))
        lines = lambda k: [l for l in (d.get(k) or "").splitlines() if l.strip()]
        req, checked = (c.get("request") or "").split(), _int(d.get("checked"))
        running = _commit(d["running_commit"]) if d.get("running_commit") else {"sha": d.get("running") or None}
        return {"installed": True, "branch": d.get("branch") or "main", "repo": d.get("repo") or None,
                "relation": d.get("relation") or None, "activity": d.get("activity") or "idle", "error": d.get("error") or None,
                "paused": c.get("paused") == "true",
                "running": {**running, "tag": d.get("running_tag") or None},
                "latest": _commit(d["latest_commit"]) if d.get("latest_commit") else None,
                "pending": [_commit(l) for l in lines("pending")], "pending_count": _int(d.get("pending_count")) or 0,
                "ahead_count": _int(d.get("ahead_count")) or 0, "failed": d.get("failed") or None,
                "target": d.get("target") or None, "started": _int(d.get("started")),
                "checked": checked, "fetched": _int(d.get("fetched")), "check_every": _int(d.get("check_every")) or 180,
                "stale": checked is None or time.time() - checked > STALE,
                # a request the updater hasn't picked up yet
                "request": {"kind": req[1], "by": req[2] if len(req) > 2 else None} if len(req) >= 2 and req[0] != d.get("handled") else None,
                "history": [_run(l) for l in reversed(lines("history"))], "log": d.get("log") or ""}

    def _write(self, data):
        try: self.k.patch(f"/api/v1/namespaces/{NS}/configmaps/{SETTINGS}", {"data": data}, kind="merge")
        except KubeError as e:
            if e.status == 404: raise HTTPException(409, SETUP)
            if e.status == 403: raise HTTPException(503, NO_RIGHTS)
            raise

    # ---------- changes (caller must have verified admin, and sudo except for a check) ----------
    def ask(self, me, kind, ip):
        s = self.status()
        if not s["installed"]: raise HTTPException(409, SETUP)
        if kind == "update" and s["relation"] == "current": raise HTTPException(409, "AXoR already runs the newest commit.")
        if kind == "update" and s["relation"] in ("ahead", "diverged", "unknown"):
            raise HTTPException(409, f"Production runs a commit that isn't in {s['branch']}'s history: only deploying {s['branch']} anyway would change it.")
        if kind == "force" and s["relation"] == "current": raise HTTPException(409, "AXoR already runs the newest commit.")
        who = re.sub(r"[^A-Za-z0-9._@-]", "", me["username"])[:64] or "admin"
        self._write({"request": f"{secrets.token_hex(6)} {kind} {who}"})
        if kind != "check":
            latest = (s["latest"] or {}).get("sha") or ""
            self.db.log(f"update.{kind}", me["username"], s["branch"], ip, latest[:12])
        return {**self.status(), "ok": True}

    def pause(self, me, paused, ip):
        self._write({"paused": "true" if paused else ""})
        self.db.log("update.pause" if paused else "update.resume", me["username"], "", ip, "")
        return {**self.status(), "ok": True}

class Ask(BaseModel):
    force: bool = False

class Settings(BaseModel):
    paused: bool

def build(db, helpers, ip, kube):
    r = APIRouter(prefix="/api/cluster/updates")
    admin, sudo = helpers["admin"], helpers["sudo"]
    u = Updates(db, kube)

    def call(fn, *a):
        try: return fn(*a)
        except KubeError as e: raise HTTPException(e.status if e.status in (400, 403, 404, 409, 422, 503) else 502, str(e))

    @r.get("")
    def status(req: Request):
        """What the updater last saw and did: the running and newest commits, what's waiting, the last updates and the last log."""
        admin(req)
        return call(u.status)

    @r.post("/check")
    def check(req: Request):
        """Ask the updater to fetch the branch now instead of at its next scheduled check."""
        me = admin(req)
        return call(u.ask, me, "check", ip(req))

    @r.post("/update")
    def update(a: Ask, req: Request):
        """Ask the updater to deploy the branch's newest commit now: even while paused or after it failed, and with
        force, even when the branch doesn't contain the running commit."""
        me = sudo(req)
        return call(u.ask, me, "force" if a.force else "update", ip(req))

    @r.put("/settings")
    def settings(s: Settings, req: Request):
        """Pause or resume automatic updates (asking for an update still works while paused)."""
        me = sudo(req)
        return call(u.pause, me, s.paused, ip(req))

    return r
