#!/usr/bin/env python3
"""AXoR's VM runner, the script inside the throwaway VM (D-013, docs/architecture/stabilization/D013_VM_RUNNER_DESIGN.md §4;
G5-4 V4.2). It is baked into the base disk (build-base.sh) and runs once at boot (axor-job.service), then the VM powers off.

In:  /dev/vdb, a tar: job.json (the job AXoR validated) and files/ (the workspace files sent along).
Out: /dev/vdc, a tar: result.json, job.log and files/ (the artifacts the job names).

What it does, in order: records the environment; checks the network it was given (from the VM and, when an image is at hand,
from inside a container); pulls the job's images by digest and fails on any other digest; builds the Dockerfile; brings the
Compose file up; runs the command as the unprivileged user `job`; samples memory and CPU every 2 s; collects the artifacts.
The benchmark's score is never taken from here as a claim: AXoR reads it from the artifact file the job names (score_file).

It never decides anything about approval, secrets or pushing: AXoR does that before a VM exists. Nothing here survives the job.
"""
import hashlib, json, os, re, shutil, socket, subprocess, tarfile, threading, time, urllib.request

IN, OUT, ROOT = os.getenv("AXOR_JOB_IN", "/dev/vdb"), os.getenv("AXOR_JOB_OUT", "/dev/vdc"), os.getenv("AXOR_JOB_ROOT", "/job")
WORK, RES, LOG = f"{ROOT}/work", f"{ROOT}/out", f"{ROOT}/out/job.log"
USER = os.getenv("AXOR_JOB_USER", "job")
FILE_CAP, FILES_CAP, LOG_TAIL = 1_000_000, 4_000_000, 40_000
T0 = time.time()
STATE = {"retries": 0, "peak": {}, "cpu": {}, "seen": set(), "vm_peak_mb": 0, "stop": False, "hide": []}
NETCHECK = """#!/bin/sh
# Can this container reach https://$1/ (or, with a client that can't tunnel through a proxy, http://$1/)? Prints one line.
h=$1
if command -v curl >/dev/null 2>&1; then
  c=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "https://$h/" 2>/dev/null); case "$c" in 2*|3*|401|404) echo "REACHED https $c"; exit 0;; esac
fi
if command -v python3 >/dev/null 2>&1; then
  python3 - "$h" <<'PY' && exit 0
import sys, urllib.request, urllib.error
try: print("REACHED https", urllib.request.urlopen("https://%s/" % sys.argv[1], timeout=15).status)
except urllib.error.HTTPError as e:
    if e.code in (401, 404): print("REACHED https", e.code)
    else: sys.exit(1)
except Exception: sys.exit(1)
PY
fi
if command -v wget >/dev/null 2>&1; then
  o=$(wget -S -T 15 -O /dev/null "https://$h/" 2>&1); echo "$o" | grep -Eq 'HTTP/[0-9.]+ (2[0-9][0-9]|3[0-9][0-9]|401|404)' && { echo "REACHED https"; exit 0; }
  o=$(wget -S -T 15 -O /dev/null "http://$h/" 2>&1); echo "$o" | grep -Eq 'HTTP/[0-9.]+ (2[0-9][0-9]|3[0-9][0-9]|401|404)' && { echo "REACHED http"; exit 0; }
  echo "NOT-REACHED"; exit 0
fi
echo "NO-CLIENT"
"""


def clean(text):
    """The text without this run's proxy token (it is the run's own and dies with it, but a log is kept and read)."""
    for h in STATE["hide"]: text = text.replace(h, "<run token>")
    return text


def log(line):
    with open(LOG, "a") as f: f.write(clean(f"[+{time.time() - T0:6.1f}s] {line}\n"))


def sh(cmd, timeout=600, env=None, cwd=None, as_job=False):
    """(exit code, output) of a shell command; 124 on timeout. Output goes to the job log too."""
    full = ["runuser", "-u", USER, "--", "bash", "-c", cmd] if as_job and os.geteuid() == 0 else ["bash", "-c", cmd]
    log(f"$ {cmd[:400]}")
    try:
        p = subprocess.run(full, capture_output=True, text=True, timeout=timeout, cwd=cwd, env={**os.environ, **(env or {})}, errors="replace")
        code, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        code, out = 124, ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + f"\n(timed out after {timeout} s)"
    with open(LOG, "a") as f: f.write(clean(out[-20000:]) + ("\n" if out and not out.endswith("\n") else "") + f"(exit {code})\n")
    return code, out


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def mem_mb(text):
    m = re.match(r"\s*([0-9.]+)\s*([KMGT]?i?B)", text or "")
    return round(float(m[1]) * {"B": 1 / 1048576, "KiB": 1 / 1024, "kB": 1 / 1048.576, "MiB": 1, "MB": 0.9537, "GiB": 1024, "GB": 953.7, "TiB": 1048576}.get(m[2], 1), 1) if m else 0.0


def sample():
    """Peak memory and CPU per container (docker stats) and the VM's own peak memory, every 2 s until told to stop."""
    while not STATE["stop"]:
        try:
            p = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], capture_output=True, text=True, timeout=20)
            for line in p.stdout.splitlines():
                try: d = json.loads(line)
                except ValueError: continue
                n = d.get("Name") or d.get("Container") or "?"
                STATE["seen"].add(n)
                STATE["peak"][n] = max(STATE["peak"].get(n, 0.0), mem_mb((d.get("MemUsage") or "").split("/")[0]))
                try: STATE["cpu"][n] = max(STATE["cpu"].get(n, 0.0), float((d.get("CPUPerc") or "0").rstrip("%")))
                except ValueError: pass
        except (OSError, subprocess.TimeoutExpired): pass
        try:
            mi = dict(l.split(":", 1) for l in open("/proc/meminfo"))
            used = (int(mi["MemTotal"].split()[0]) - int(mi["MemAvailable"].split()[0])) / 1024
            STATE["vm_peak_mb"] = max(STATE["vm_peak_mb"], round(used, 1))
        except (OSError, KeyError, ValueError): pass
        time.sleep(2)


def net_bytes():
    rx = tx = 0
    try:
        for line in open("/proc/net/dev").read().splitlines()[2:]:
            name, rest = line.split(":", 1)
            if name.strip() == "lo" or name.strip().startswith(("docker", "br-", "veth")): continue
            f = rest.split(); rx += int(f[0]); tx += int(f[8])
    except (OSError, ValueError, IndexError): pass
    return rx, tx


def cpu_seconds():
    try:
        f = open("/proc/stat").readline().split()[1:8]
        return round((sum(map(int, f)) - int(f[3]) - int(f[4])) / os.sysconf("SC_CLK_TCK"), 1)  # all but idle and iowait
    except (OSError, ValueError, IndexError): return None


def reach(proxy, hosts, git_url=""):
    """What this VM can reach, measured here: DNS, HTTPS (through the proxy the job was given, if any) and git over HTTPS."""
    out = {"dns": [], "https": []}
    if git_url:
        env = {k: proxy for k in ("https_proxy", "http_proxy")} if proxy else {}
        c, o = sh(f"git ls-remote --heads {git_url} | head -3", 60, {**env, "GIT_TERMINAL_PROMPT": "0"})
        out["git"] = {"url": git_url, "ok": c == 0 and bool(re.search(r"^[0-9a-f]{40}\s", o, re.M)), **({} if c == 0 else {"error": o.strip()[-160:]})}
    for h in hosts:
        try: out["dns"].append({"host": h, "ok": bool(socket.getaddrinfo(h, 443))})  # the VM's own lookup; behind the proxy, the proxy resolves
        except OSError as e: out["dns"].append({"host": h, "ok": False, "error": str(e)[:120]})
        t = time.time()
        try:
            op = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy, "http": proxy} if proxy else {}))
            with op.open(f"https://{h}/", timeout=15) as r: out["https"].append({"host": h, "ok": True, "status": r.status, "ms": int((time.time() - t) * 1000)})
        except urllib.error.HTTPError as e: out["https"].append({"host": h, "ok": True, "status": e.code, "ms": int((time.time() - t) * 1000)})  # it answered
        except Exception as e:  # noqa: BLE001 - measured, never raised
            out["https"].append({"host": h, "ok": False, "error": str(getattr(e, "reason", e))[:160]})
    return out


def main():
    os.makedirs(RES + "/files", exist_ok=True); os.makedirs(WORK, exist_ok=True)
    result = {"status": "error", "exit": None, "error": "", "images": [], "health": [], "stats": {}, "net": None}
    try:
        with tarfile.open(IN, "r:") as t:  # the pod's supervisor made this tar from validated paths; Debian 12's Python 3.11.2 has no extraction filter yet
            t.extractall(f"{ROOT}/in", **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        job = json.load(open(f"{ROOT}/in/job.json"))
        src = f"{ROOT}/in/files"
        if os.path.isdir(src): shutil.copytree(src, WORK, dirs_exist_ok=True)
        subprocess.run(["chown", "-R", f"{USER}:{USER}", WORK], check=False)
        result.update(run(job))
    except Exception as e:  # noqa: BLE001 - the VM must always report and power off
        result["error"] = f"The runner script failed: {type(e).__name__}: {e}"[:600]
        log(result["error"])
    result["seconds"] = round(time.time() - T0, 1)
    try: result["output"] = open(LOG, errors="replace").read()[-LOG_TAIL:]
    except OSError: result["output"] = ""
    json.dump(result, open(f"{RES}/result.json", "w"))
    with tarfile.open(OUT, "w:") as t:
        for n in sorted(os.listdir(RES)): t.add(f"{RES}/{n}", arcname=n)
    os.sync()


def run(job):
    proxy = job.get("proxy") or ""
    bproxy = job.get("build_proxy") or proxy  # network `build`: the approved package indexes are reachable through this one, by build steps only
    for x in (proxy, bproxy):
        m = re.match(r"^https?://([^:@/]+):", x)
        if m: STATE["hide"].append(m[1])
    penv = {k: proxy for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")} if proxy else {}
    if proxy:  # the Docker daemon pulls through the proxy; the job's own commands and builds get it in their environment
        os.makedirs("/etc/systemd/system/docker.service.d", exist_ok=True)
        open("/etc/systemd/system/docker.service.d/proxy.conf", "w").write(f'[Service]\nEnvironment="HTTP_PROXY={proxy}" "HTTPS_PROXY={proxy}" "NO_PROXY=localhost,127.0.0.1"\n')
        sh("systemctl daemon-reload && systemctl restart docker", 120)
    base = json.load(open("/opt/axor/base.json")) if os.path.exists("/opt/axor/base.json") else {}
    env = {"runner_script_sha256": sha(os.path.abspath(__file__)), "base": base, "kernel": os.uname().release, "cpus": os.cpu_count(),
           "memory_mb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1048576), "started": T0,
           "docker": sh("docker version --format '{{.Server.Version}}'", 60)[1].strip()[:60],
           "compose": sh("docker compose version --short", 60)[1].strip()[:60]}
    out = {"environment": env, "images": [], "health": [], "net": None}
    disk0, (rx0, tx0), cpu0 = shutil.disk_usage("/").used, net_bytes(), cpu_seconds()
    if job.get("network") != "none": out["net"] = {"vm": reach(proxy, job.get("check_hosts") or [], job.get("check_git") or "")}
    threading.Thread(target=sample, daemon=True).start()
    status, code, err = "done", 0, ""

    def step(name, cmd, timeout, as_job=True, env_=None):
        nonlocal status, code, err
        if status != "done": return ""
        c, o = sh(cmd, timeout, {**penv, **(env_ or {})}, WORK, as_job)
        if c != 0: status, code, err = ("timeout" if c == 124 else "failed"), c, f"{name} ended with exit {c}"
        return o

    for ref in job.get("images") or []:  # pulled by digest only; a digest other than the one asked is a failure
        for attempt in range(3):
            c, o = sh(f"docker pull -q {ref}", 900)
            if c == 0: break
            STATE["retries"] += 1; time.sleep(5 * (attempt + 1))
        if c != 0: status, code, err = "failed", c, f"Couldn't pull {ref}"; break
        want = ref.split("@", 1)[1]
        c, o = sh(f"docker image inspect --format '{{{{json .RepoDigests}}}} {{{{.Id}}}}' {ref}", 60)
        got = re.findall(r"sha256:[0-9a-f]{64}", o)
        if c != 0 or want not in got[:-1]:  # RepoDigests first, the image Id last
            status, code, err = "failed", 1, f"{ref} came with another digest than the one asked"; break
        out["images"].append({"ref": ref, "id": got[-1], "digests": sorted(set(got[:-1])), "how": "pulled"})

    tag = f"axor-job:{job.get('id') or 'x'}"
    if job.get("dockerfile"):
        args = " ".join(f"--build-arg {k}={bproxy}" for k in penv)
        step("The build", f"docker build -q {args} -f {job['dockerfile']} -t {tag} {job.get('context') or '.'}", job.get("build_timeout_s") or 1800)
        if status == "done":
            c, o = sh(f"docker image inspect --format '{{{{.Id}}}} {{{{.Size}}}}' {tag}", 60)
            m = re.search(r"(sha256:[0-9a-f]{64}) (\d+)", o)
            out["images"].append({"ref": tag, "id": m[1] if m else None, "size": int(m[2]) if m else None, "how": "built", "dockerfile": job["dockerfile"]})
    if job.get("compose"):
        step("Compose up", f"docker compose -f {job['compose']} up -d --build --wait --wait-timeout 300", (job.get("build_timeout_s") or 1800) + 330)
    if job.get("command"):
        step("The command", job["command"], job.get("timeout_s") or 600, env_={"AXOR_IMAGE": tag if job.get("dockerfile") else "", "AXOR_JOB": str(job.get("id") or "")})

    probe = next((i["ref"] for i in out["images"] if i.get("id")), None)
    if out["net"] is not None: out["net"]["vm"]["through_proxy"] = bool(proxy)  # then the proxy resolves names: the VM's own DNS answer says nothing about reach
    if out["net"] is not None and probe and job.get("check_hosts"):  # the same question from inside a running container, when its image can ask
        h = job["check_hosts"][0]
        open(f"{ROOT}/netcheck.sh", "w").write(NETCHECK); os.chmod(f"{ROOT}/netcheck.sh", 0o755)
        c, o = sh(f"docker run --rm {' '.join(f'-e {k}={v}' for k, v in penv.items())} -v {ROOT}/netcheck.sh:/netcheck.sh:ro --entrypoint sh {probe} /netcheck.sh {h}", 120)
        line = next((l for l in o.splitlines() if l.startswith(("REACHED", "NOT-REACHED", "NO-CLIENT"))), "")
        out["net"]["container"] = {"image": probe, "host": h, "ok": True if line.startswith("REACHED") else False if line.startswith("NOT-REACHED") else None,
                                   **({"how": line.split()[1]} if line.startswith("REACHED") else {}),
                                   **({"error": "not measured: the image has no shell or no client to ask with"} if not line or line.startswith("NO-CLIENT") else {})}
    elif out["net"] is not None: out["net"]["container"] = {"ok": None, "error": "not measured: the job made no image to ask from"}

    ids = sh("docker ps -aq", 30)[1].split()
    if ids:
        c, o = sh("docker inspect " + " ".join(ids), 60)
        try:
            for d in json.loads(o):
                s = d.get("State") or {}
                out["health"].append({"name": (d.get("Name") or "").lstrip("/"), "image": (d.get("Config") or {}).get("Image"), "status": s.get("Status"),
                                      "health": (s.get("Health") or {}).get("Status"), "oom_killed": bool(s.get("OOMKilled")), "exit": s.get("ExitCode"),
                                      "restarts": d.get("RestartCount") or 0})
        except ValueError: pass
    STATE["stop"] = True
    rx1, tx1 = net_bytes(); cpu1 = cpu_seconds()
    out["stats"] = {"containers": {n: {"peak_memory_mb": STATE["peak"].get(n, 0.0), "peak_cpu_percent": STATE["cpu"].get(n, 0.0)} for n in sorted(STATE["seen"])},
                    "vm_peak_memory_mb": STATE["vm_peak_mb"], "cpu_seconds": round(cpu1 - cpu0, 1) if cpu0 is not None and cpu1 is not None else None,
                    "disk_used_mb": round((shutil.disk_usage("/").used - disk0) / 1048576, 1), "bytes_in": rx1 - rx0, "bytes_out": tx1 - tx0,
                    "seconds": round(time.time() - T0, 1), "retries": STATE["retries"], "oom_kills": sum(h["oom_killed"] for h in out["health"])}

    files, total = {}, 0
    for rel in job.get("artifacts") or []:  # only what the job named, only regular files inside the job folder, within the caps
        p = os.path.realpath(os.path.join(WORK, rel))
        if not p.startswith(WORK + "/") or not os.path.isfile(p): files[rel] = {"error": "not found"}; continue
        n = os.path.getsize(p)
        if n > FILE_CAP or total + n > FILES_CAP: files[rel] = {"error": f"too large ({n} bytes)"}; continue
        os.makedirs(os.path.dirname(f"{RES}/files/{rel}"), exist_ok=True); shutil.copyfile(p, f"{RES}/files/{rel}")
        files[rel] = {"sha256": sha(p), "bytes": n}; total += n
    out["files"] = files
    if job.get("compose"): sh(f"docker compose -f {job['compose']} down -t 5", 120, cwd=WORK)
    env["ended"] = time.time()
    return {**out, "status": status, "exit": code, "error": err}


if __name__ == "__main__":
    main()
