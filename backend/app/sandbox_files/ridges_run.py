"""Runs a Ridges agent on local practice tasks the way Ridges runs it (AXoR's sandbox ships this as .axor/ridges_run.py).

    python .axor/ridges_run.py --agent agent.py tasks/orders-report tasks/slow-dashboard ...

A task is a folder: problem.md (the problem statement), repo/ (the application's files), setup.sh (optional: seeds the
database; it runs in /repo before the agent and again before the check) and check.sh (the hidden check, run in /repo with the
agent's patch applied; exit 0 = pass). For each task: the repo is copied to /repo and committed; agent_main({"problem_statement":
…}) runs in a subprocess in /repo within AGENT_TIMEOUT seconds and RIDGES_MAX_COST_USD of inference (the proxy enforces it);
its return value must be a unified diff; the repo goes back to the base commit, the diff is applied and check.sh decides. Only
the diff counts, as on Ridges. Prints a line per task and a summary; exits 0 when every task passed.
"""
import argparse, json, os, shutil, subprocess, sys, time, urllib.request

REPO = os.environ.get("RIDGES_REPO", "/repo")
CALL = """import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("agent", sys.argv[1]); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
out = mod.agent_main({"problem_statement": open(sys.argv[2], encoding="utf-8").read()})
if isinstance(out, dict): out = out.get("patch") or out.get("diff") or ""
open(sys.argv[3], "w", encoding="utf-8").write(out if isinstance(out, str) else "")
"""

def proxy(path, body=None):
    base = os.environ.get("SANDBOX_PROXY_URL")
    if not base: return {}
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read() or b"{}")
    except Exception:  # noqa: BLE001 - without the proxy there's no cost to report
        return {}

def git(*args, check=True):
    r = subprocess.run(["git", "-c", "user.name=ridges", "-c", "user.email=ridges@localhost", *args], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode: raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r

def fresh(task):
    for name in os.listdir(REPO):
        p = os.path.join(REPO, name)
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
    src = os.path.join(task, "repo")
    if os.path.isdir(src): shutil.copytree(src, REPO, dirs_exist_ok=True, symlinks=True)
    git("init", "-q"); git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", "base")

def script(task, name, timeout=600):
    path = os.path.join(task, name)
    if not os.path.exists(path): return None
    return subprocess.run(["bash", os.path.abspath(path)], cwd=REPO, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "TASK_DIR": os.path.abspath(task)})

def tail(s, n=1200): return s if len(s) <= n else "…" + s[-n:]

def run(agent, task, timeout, cap):
    t0, res = time.time(), {"task": os.path.basename(os.path.normpath(task)), "passed": False}
    try:
        problem = os.path.join(task, "problem.md")
        if not os.path.exists(problem): raise RuntimeError("problem.md is missing")
        fresh(task)
        r = script(task, "setup.sh")
        if r and r.returncode: raise RuntimeError(f"setup.sh failed ({r.returncode}): {tail(r.stdout + r.stderr, 600)}")
        before = proxy("/usage").get("spent_usd", 0)
        proxy("/window", {"cap": cap})
        out = f"/tmp/ridges-out-{res['task']}.diff"
        if os.path.exists(out): os.remove(out)
        try:
            r = subprocess.run([sys.executable, "-c", CALL, os.path.abspath(agent), os.path.abspath(problem), out], cwd=REPO,
                               capture_output=True, text=True, timeout=timeout)
            res["agent_log"] = tail(r.stdout + r.stderr)
            if r.returncode: raise RuntimeError(f"agent_main raised (exit {r.returncode}): {tail(r.stderr, 600)}")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"agent_main ran past AGENT_TIMEOUT ({timeout} s)") from None
        finally:
            res["cost_usd"] = round(proxy("/usage").get("spent_usd", before) - before, 4)
        patch = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
        if not patch.strip(): raise RuntimeError("agent_main returned an empty patch")
        res["diff_lines"] = sum(1 for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
        git("reset", "-q", "--hard"); git("clean", "-qfdx")  # only the diff leaves the agent's run
        with open("/tmp/ridges.patch", "w", encoding="utf-8") as f: f.write(patch if patch.endswith("\n") else patch + "\n")
        r = git("apply", "--check", "/tmp/ridges.patch", check=False)
        if r.returncode: raise RuntimeError(f"the patch doesn't apply: {tail(r.stderr, 400)}")
        git("apply", "/tmp/ridges.patch")
        r = script(task, "setup.sh")  # a fresh database for the check
        if r and r.returncode: raise RuntimeError(f"setup.sh failed before the check ({r.returncode}): {tail(r.stdout + r.stderr, 600)}")
        r = script(task, "check.sh")
        if r is None: res.update(passed=None, note="no check.sh: the patch applies, nothing judged it")
        else: res.update(passed=r.returncode == 0, check_log=tail(r.stdout + r.stderr))
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        res["error"] = str(e)
    res["seconds"] = round(time.time() - t0, 1)
    print("@@RIDGES-RESULT " + json.dumps(res), flush=True)
    return res

def main():
    ap = argparse.ArgumentParser(description="Run a Ridges agent on local tasks.")
    ap.add_argument("--agent", default="agent.py")
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("AGENT_TIMEOUT", "600")))
    ap.add_argument("--cap", type=float, default=float(os.environ.get("RIDGES_MAX_COST_USD", "0.29")))
    ap.add_argument("tasks", nargs="+")
    a = ap.parse_args()
    if not os.path.exists(a.agent): sys.exit(f"No agent at {a.agent}.")
    os.makedirs(REPO, exist_ok=True)
    tasks = [t for t in a.tasks if os.path.isdir(t)]
    if not tasks: sys.exit("No task folders given (each holds problem.md, repo/, check.sh).")
    results = [run(a.agent, t, a.timeout, a.cap) for t in tasks]
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{'task':32} {'result':8} {'cost $':>8} {'secs':>6}")
    for r in results:
        mark = "pass" if r["passed"] else "n/a" if r["passed"] is None and "error" not in r else "FAIL"
        print(f"{r['task'][:32]:32} {mark:8} {r.get('cost_usd', 0):8.4f} {r['seconds']:6.1f}" + (f"  {r['error'][:90]}" if r.get("error") else ""))
    print(f"\n{passed}/{len(results)} passed, {sum(r.get('cost_usd', 0) for r in results):.4f} USD")
    sys.exit(0 if passed == len(results) else 1)

if __name__ == "__main__":
    main()
