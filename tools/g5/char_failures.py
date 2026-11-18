"""G5 Phase 1: characterize every failure classifier on an error corpus, so a refactor can be shown to change no output.

Run inside the axor/web image with the tree under test at /app/backend and a folder at /p1 holding corpus_ac.json,
corpus_mw.json and corpus_sbx.json (JSON lists of {src, status, error, n}; the real corpus comes from a restored backup and is
never committed). Writes /p1/out/<name>.json; compare two runs with tools/g5/char_diff.py.

  docker run --rm --network none -v $TREE/backend:/app/backend:ro -v $DIR:/p1 -w /app/backend --entrypoint python \
    axor/web:$TAG /p1/char_failures.py after.json
"""
import json, sys, os
sys.path.insert(0, "/app/backend")
os.environ.setdefault("DATA_DIR", "/tmp/axor-char")
from app import mining_autoloop, intel_layers, orchestrator, missions, agent_core, control_dispatch, mission_ops
rows = []
for f in ("corpus_ac.json", "corpus_mw.json", "corpus_sbx.json"):
    rows += json.load(open(f"/p1/{f}")) or []
SYN = ["", "plan rate limit reached", "token budget exceeded", "insufficient credit", "401 unauthorized", "429 too many requests",
       "token cap", "connection reset by peer", "timed out after 600 s", "server restart", "sandbox is busy", "ErrImagePull",
       "gvisor isn't installed", "egress proxy down", "files come to 2000 kB", "mcp tool failed", "OOMKilled", "invalid json",
       "tests failed", "cancelled by user", "deadline passed", "no task to plan", "database is locked", "model refused", "boom"]
rows += [{"src": "synthetic", "status": st, "error": e, "n": 1} for e in SYN for st in ("failed", "error", "timeout", "lost")]
out = []
for r in rows:
    st, e = r["status"] or "failed", r["error"] or ""
    k = intel_layers.fail_class(st, e)
    out.append({"src": r["src"], "status": st, "error": e, "n": r["n"],
                "autoloop": mining_autoloop.classify(e), "fail_class": k, "sbx": list(orchestrator.sbx_class(st, e)),
                "missions": missions.classify(e), "terminal": agent_core.terminal_state(st, e),
                "dispatch": "retry" if k in control_dispatch.RETRY else "never" if k in control_dispatch.NEVER else "other",
                "orch_recovery": list(orchestrator.RECOVERY.get(k, orchestrator.RECOVERY["task"])),
                "ops_recovery": list(mission_ops.RECOVERY.get(k, ("?", "?", "?")))})
consts = {"orchestrator.RECOVERY": {k: list(v) for k, v in orchestrator.RECOVERY.items()}, "orchestrator.OWN_FAULT": list(orchestrator.OWN_FAULT),
          "orchestrator.SBX": [list(x) for x in orchestrator.SBX], "orchestrator.SBX_LABEL": orchestrator.SBX_LABEL,
          "mission_ops.RECOVERY": {k: list(v) for k, v in mission_ops.RECOVERY.items()},
          "control_dispatch.RETRY": sorted(control_dispatch.RETRY), "control_dispatch.NEVER": sorted(control_dispatch.NEVER),
          "intel_layers.FAIL_LABEL": intel_layers.FAIL_LABEL, "mining_autoloop.CLASSES": [list(x) for x in mining_autoloop.CLASSES],
          "mining_autoloop.LABEL": mining_autoloop.LABEL, "mining_autoloop.POLICY": mining_autoloop.POLICY,
          "missions.FAILURES": [list(x) for x in missions.FAILURES], "missions.RECOVERY": missions.RECOVERY}
json.dump({"rows": out, "consts": consts}, open(f"/p1/out/{sys.argv[1]}", "w"), indent=1, sort_keys=True)
print(len(out), "rows")
