"""Platform status for the Dashboard and the Developer / Infrastructure page tabs (platform.js): one call that says which
AXoR services are set up, from what each module already knows (no new probes). Everyone signed in sees the chain and
their own services (Drive, Slack, Source hub, push, agents); administrators also see the server-side ones (Docker,
the Runner, Kubernetes, DNS). A regular user never learns whether DOCKER_URL, RUNNER_URL, KUBE_API or DNS_URL exist."""
import time

from fastapi import APIRouter, HTTPException, Request

from . import agent_core


def build(require, collector, *, drive, slack, source, push, ready, docker_url, runner, kube, dns):
    r = APIRouter(prefix="/api/platform-status")

    def chain():
        s = collector.state
        age = time.time() - s["updated"] if s.get("updated") else None
        if str(s.get("status", "")).startswith("error"): return "down", "Can't reach the chain"
        if not s.get("block"): return "pending", "Collecting the first snapshot"
        if age is not None and age > 1800: return "warn", f"Last block read {int(age // 60)} min ago"
        return "ok", f"Block {s['block']:,} · {len(s.get('subnets') or [])} subnets"

    def agents():
        if not ready: return "off", "Agents aren't available on this server"
        try: ready(); return "ok", "A model is set up"
        except HTTPException as e: return "off", str(e.detail)

    def on(flag, yes, no): return ("ok", yes) if flag else ("off", no)

    USER = [
        ("chain", "Chain", "globe", "explore", chain),
        ("agents", "Agents", "bot", "agents", agents),
        ("drive", "Drive", "folder", "drive", lambda: on(drive.enabled, "File storage is connected", "No drive server (DRIVE_URL)")),
        ("slack", "Slack", "hash", "slack", lambda: on(slack.configured(), "A channel is connected", "Not connected")),
        ("source", "Source hub", "github", "source", lambda: on(source.configured(), "GitHub is connected", "Not connected")),
        ("push", "Push", "bell", "notifications", lambda: on(push.enabled, "Push notifications work", "No push server (PUSH_URL)")),
    ]
    ADMIN = [
        ("docker", "Docker", "server", "docker", lambda: on(docker_url, "Docker proxy is set up", "Not set up (DOCKER_URL)")),
        ("runner", "Runner", "rocket", "devops", lambda: on(runner.enabled, "The AXoR Runner is set up", "Not set up (RUNNER_URL)")),
        ("kubernetes", "Kubernetes", "layers", "cluster", lambda: on(kube.enabled, "AXoR runs on Kubernetes", "Not on Kubernetes")),
        ("dns", "DNS", "globe", "dns", lambda: on(dns.enabled, "AXoR DNS is set up", "Not set up (DNS_URL)")),
    ]

    @r.get("")
    def status(req: Request):
        me = require(req)
        out = []
        for key, label, ic, view, fn in USER + (ADMIN if me["role"] == "admin" else []):
            try: state, detail = fn()
            except Exception as e: state, detail = "warn", f"Couldn't check: {e}"
            out.append({"key": key, "label": label, "icon": ic, "view": view, "state": state, "detail": detail})
        return {"services": out, "at": time.time(), "work": work(me)}

    def work(me):
        """The signed-in user's work beside the platform's availability, so "the platform is up" never reads as "all is well":
        runs failing now (the last hour), runs failed in 24 hours (history), runs going, and missions waiting on someone."""
        core = agent_core.get()
        if core is None: return None
        now = time.time()
        try:
            h, d = core.outcomes(me["id"], now - 3600), core.outcomes(me["id"], now - 86400)
            out = {"failing_now": h["failed"] + h["timeout"], "failed_24h": d["failed"] + d["timeout"] + d["restarted"], "restarted_24h": d["restarted"],
                   "running": d["running"], "success_pct": d["success_pct"]}
        except Exception: return None  # noqa: BLE001 - a server without the ledger shows availability only
        try:
            m = core.db.q("""SELECT SUM(status IN ('running','queued')) going, SUM(status IN ('needs_input','paused')) held FROM mx_missions WHERE user_id=?""",
                          (me["id"],), one=True) or {}
            out.update(missions_going=m.get("going") or 0, missions_held=m.get("held") or 0)
        except Exception: pass  # noqa: BLE001 - Mission Control off
        return out

    return r
