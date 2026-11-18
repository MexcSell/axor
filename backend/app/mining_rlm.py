"""Competition teams: rlm_query, a recursive language model (rlm.py) over the workspace's files, for questions about more
than an agent can read with file_read (a whole repository, long logs, every task's output).

The agent's own model is the root model; the sub-calls go to RLM_SUB_MODEL through the sandbox proxy. Each query is a sandbox
run in mw_sbx (command "rlm: <question>", the trajectory as its output), so it shows under Sandbox runs and its sub-calls
count against the workspace's daily sandbox budget. One query at a time across AXoR: a query holds a sandbox slot for its
whole length, mostly idle while the root model thinks, and the squads' sandbox_run calls need the other slot.
"""
import os, threading, time

from . import rlm
from .agents import _schema

AT_ONCE = threading.BoundedSemaphore(max(1, int(os.getenv("RLM_MAX_RUNS", "1"))))
TIMEOUT = int(os.getenv("RLM_TIMEOUT", "600"))
BUDGET = float(os.getenv("RLM_BUDGET_USD", "1"))
TRANSCRIPT = 60_000

TOOL = {"name": "rlm_query", "strict": True,
        "description": "Answers a question over workspace files too large to read with file_read: a recursive language model loads "
                       "them into a Python REPL as `context`, explores them with code and fans the reading out to a sub-model in "
                       "parallel, then answers with file paths and figures. For questions across many files or long logs (\"where is "
                       "X handled\", \"which tasks failed and why\", \"every place that calls Y\"). Slow (minutes) and costs "
                       "inference: use file_read for one file you can name. paths: folders or files to cover ([] for every file). "
                       "Returns the answer, whether it was checked (ready) and the cost; the full trajectory is under Sandbox runs.",
        "input_schema": _schema({"question": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}})}

def query(work, w, c, agent, model, args, task=None, run=None, cancelled=lambda: False):
    """Runs one rlm_query for agent on workspace w; returns the tool's result (and the root model's tokens as _tokens)."""
    from .mining_work import SBX_DAY_USD, _clip, _path
    question = (args.get("question") or "").strip()
    if not question: raise LookupError("Give the question to answer.")
    pre = [_path(p) for p in args.get("paths") or [] if (p or "").strip()]
    files = {f["path"]: f["content"] or "" for f in work.db.q("SELECT path, content FROM mw_files WHERE comp_id=? ORDER BY path", (w["id"],))
             if not pre or any(f["path"] == p or f["path"].startswith(p + "/") for p in pre)}
    files = {p: t for p, t in files.items() if t}
    if not files: raise LookupError("No workspace files match those paths (files_list shows what there is)." if pre else "The workspace has no files yet.")
    spent = work.db.q("SELECT COALESCE(SUM(cost),0) n FROM mw_sbx WHERE comp_id=? AND started>?", (w["id"], time.time() - 86400), one=True)["n"]
    if spent >= SBX_DAY_USD: raise LookupError(f"The sandbox's inference budget for this workspace ({SBX_DAY_USD:g} USD a day) is spent.")
    # The emergency stop (exec_env.py, D-032): a query of a stopped mission is recorded as not started, before any pod exists or any
    # inference is paid for; one that is running ends through its own cancelled test, which rlm.run asks at every step and hands to
    # its sandbox run. Asked here, at the caller, as mining_work._docker_job does. If the stop can't be asked, the query doesn't run.
    try:
        from . import exec_env as _stop
        stopped = _stop.refusal(work.db, w["id"], task)
        cancelled = _stop.guard(work.db, w["id"], task, cancelled)
    except Exception as e:  # noqa: BLE001 - fail closed
        stopped = f"Not started: AXoR couldn't check whether runs are stopped ({type(e).__name__})."
    if stopped:
        work._ins("""INSERT INTO mw_sbx (comp_id, task_id, run_id, agent_id, command, services, status, error, started, finished) VALUES (?,?,?,?,?,'','cancelled',?,?,?)""",
                  (w["id"], task, run, agent["id"], _clip(f"rlm: {question}", 4000), stopped, time.time(), time.time()))
        raise LookupError(stopped)
    if not AT_ONCE.acquire(blocking=False):
        raise LookupError("Another rlm_query is running in AXoR right now (one at a time). Work with file_read meanwhile, or try again later.")
    try:
        sid = work._ins("""INSERT INTO mw_sbx (comp_id, task_id, run_id, agent_id, command, services, status, started) VALUES (?,?,?,?,?,'','running',?)""",
                        (w["id"], task, run, agent["id"], _clip(f"rlm: {question}", 4000), time.time()))
        try:
            complete, used = work.m.hub.llm.completer(model, "medium")
            res = rlm.run(work.sbx, complete, question, files, timeout=TIMEOUT, budget=max(0.05, min(BUDGET, SBX_DAY_USD - spent)),
                          label=f"SN{c['netuid']} {work._label(w)} #{sid} rlm", cancelled=cancelled,
                          started=lambda pod: work.db.q("UPDATE mw_sbx SET pod=? WHERE id=?", (pod, sid)))
        except Exception as e:  # noqa: BLE001 - the run is marked, then the agent sees the error
            work.db.q("UPDATE mw_sbx SET status='error', error=?, finished=? WHERE id=?", (_clip(e, 400), time.time(), sid))
            raise LookupError(str(e)) if isinstance(e, rlm.RLMError) else e
    finally:
        AT_ONCE.release()
    text = rlm.transcript(question, res, used.split(":", 1)[-1])
    if len(text) > TRANSCRIPT: text = text[:TRANSCRIPT // 3] + "\n\n… (trajectory cut) …\n\n" + text[-(TRANSCRIPT * 2 // 3):]
    status = {"done": "done", "unfinished": "failed", "cancelled": "cancelled"}.get(res["status"], "error")
    work.db.q("UPDATE mw_sbx SET status=?, output=?, error=?, finished=?, cost=?, calls=? WHERE id=?",
              (status, text, res["error"] or None, time.time(), res["cost"], res["sub_calls"], sid))
    work._event(w["id"], "sandbox", f"{agent['name']} asked the RLM “{_clip(question, 80)}”: {res['status']}, {res['turns']} turn(s), "
                f"{res['sub_calls']} sub-call(s)" + (f", {res['cost']:.3f} USD" if res["cost"] else ""), agent=agent["id"], task=task)
    return {"status": res["status"], "answer": res["answer"] or "(no answer)", "ready": res["ready"], "files": len(files), "turns": res["turns"],
            "sub_calls": res["sub_calls"], "cost_usd": res["cost"], "seconds": res["seconds"], "sandbox_run": sid,
            **({"error": res["error"]} if res["error"] else {}), "_tokens": res["tokens"]}
