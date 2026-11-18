#!/usr/bin/env python3
"""Local staging of the VM runner without a cluster (k8s/runner/stage-local.sh runs this inside AXoR's web image, offline).

  prepare JOBDIR   validates JOBDIR/spec.json against JOBDIR/files with the real runner.validate, and writes JOBDIR/input the
                   way Runner.run() fills the job's ConfigMaps (manifest.json and one key per file, the job among them)
  finish JOBDIR    turns what the pod's supervisor handed over (JOBDIR/out/body.json) into the job's result with the real
                   runner.finish and runner.document, and writes JOBDIR/result.json and JOBDIR/summary.json

Between the two, stage-local.sh runs the real pod image with /dev/kvm. What this does not exercise: the Kubernetes API calls,
the NetworkPolicy and the HTTP hand-over to AXoR's result port (those are covered by tests/unit/test_vm_runner.py on fakes)."""
import json, os, pathlib, sys

from app import runner


def files_of(d):
    root = pathlib.Path(d, "files")
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def prepare(d):
    spec, files = json.load(open(f"{d}/spec.json")), files_of(d)
    packages = [h for h in os.getenv("RUNNER_PACKAGE_HOSTS", "").split(",") if h.strip()]  # staging's stand-in for the Owner's setting
    try: job, held = runner.validate(spec, files, packages)
    except runner.RunnerError as e:
        json.dump({"refused": str(e)}, open(f"{d}/prepared.json", "w")); print(f"REFUSED before any VM: {e}"); return 3
    if held:
        json.dump({"held": held}, open(f"{d}/prepared.json", "w")); print(f"HELD, not started: {held}"); return 4
    job = {**job, "id": int(spec.get("_id") or 1)}
    send = {**files, runner.JOB_FILE: json.dumps(job)}
    os.makedirs(f"{d}/input", exist_ok=True)
    manifest = {}
    for i, (path, text) in enumerate(sorted(send.items())):
        manifest[f"f{i}"] = path; open(f"{d}/input/f{i}", "w").write(text)
    json.dump(manifest, open(f"{d}/input/manifest.json", "w"))
    wall = job["timeout_s"] + (job["build_timeout_s"] if job.get("dockerfile") or job.get("compose") else 0) + 60
    runs = {}  # what each proxy run is opened with: the product's own request (runner.proxy_run), the token filled in by stage-local.sh
    if job["network"] != "none": runs["registry"] = runner.proxy_run("@TOKEN@", wall)
    if job["network"] == "build": runs["build"] = runner.proxy_run("@TOKEN@", wall, job["package_hosts"])
    json.dump({"job": job, "inputs": runner.inputs(job, files), "registry_hosts": list(runner.REGISTRY_HOSTS), "proxy_runs": runs}, open(f"{d}/prepared.json", "w"), indent=1)
    print(f"prepared: {job['kind']} network={job['network']} cpus={job['cpus']} memory_mb={job['memory_mb']} files={len(files)}")
    return 0


def finish(d):
    p = json.load(open(f"{d}/prepared.json"))
    job, files = {k: v for k, v in p["job"].items() if k != "id"}, files_of(d)
    body = json.load(open(f"{d}/out/body.json")) if os.path.exists(f"{d}/out/body.json") else {}
    pod = json.load(open(f"{d}/pod.json"))  # how the container itself ended: {"exit", "seconds", "name"}
    egress = json.load(open(f"{d}/egress.json")) if os.path.exists(f"{d}/egress.json") else None
    build = {**json.load(open(f"{d}/build_egress.json")), "package_hosts": job.get("package_hosts")} if os.path.exists(f"{d}/build_egress.json") else None
    runner.BASE_SHA = os.getenv("RUNNER_BASE_SHA256", "").lower()
    runner.IMAGE = os.getenv("RUNNER_IMAGE", "")
    https = {}  # what the proxy answered when each run was opened: did it say it enforces https-only
    for run, f in (("registry", "opened.json"), ("build", "build_opened.json")):
        if os.path.exists(f"{d}/{f}"): https[run] = runner.https_confirmed(json.load(open(f"{d}/{f}")), run)
    r = runner.finish(job, body, "done" if pod["exit"] == 0 else "failed", pod["exit"], "", "", pod["name"], runner.inputs(job, files), pod["seconds"], egress, [], [], build, https)
    json.dump(runner.document(r, job), open(f"{d}/result.json", "w"), indent=1, sort_keys=True)
    open(f"{d}/job.log", "w").write(r.get("output") or "")
    s = {"status": r["status"], "exit": r["exit"], "error": r["error"], "seconds": r["seconds"], "score": r.get("score"), "score_error": r.get("score_error"),
         "images": [{"ref": i.get("ref"), "id": i.get("id"), "how": i.get("how")} for i in r["images"]],
         "peak_memory_mb": {n: v.get("peak_memory_mb") for n, v in ((r.get("stats") or {}).get("containers") or {}).items()},
         "vm": {k: (r.get("stats") or {}).get(k) for k in ("vm_peak_memory_mb", "cpu_seconds", "disk_used_mb", "bytes_in", "bytes_out", "seconds", "retries")},
         "environment": {k: r["environment"].get(k) for k in ("base_disk_sha256", "runner_script_sha256", "docker", "compose", "kernel")},
         "job_sha256": r["inputs"]["job_sha256"], "net": r.get("net"), "artifacts": r.get("artifacts")}
    json.dump(s, open(f"{d}/summary.json", "w"), indent=1)
    print(json.dumps(s, indent=1))
    return 0


def confirm(d):
    """Before the VM starts: did the proxy say it enforces https-only for each run just opened? As Runner.run: if not, no job."""
    try:
        for run, f in (("registry", "opened.json"), ("build", "build_opened.json")):
            if os.path.exists(f"{d}/{f}"): runner.https_confirmed(json.load(open(f"{d}/{f}")), run)
    except runner.RunnerError as e:
        print(f"NOT STARTED: {e}"); return 5
    return 0


if __name__ == "__main__":
    sys.exit({"prepare": prepare, "confirm": confirm, "finish": finish}[sys.argv[1]](sys.argv[2]))
