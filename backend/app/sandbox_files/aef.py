"""AXoR's in-run agent (Agent Execution Fabric, D-032): shipped into a planned sandbox run as .axor/aef.py.

    python3 /work/.axor/aef.py run <seconds> <base64 of the command>     what AXoR starts instead of the bare command
    python3 /work/.axor/aef.py save                                      a save point during the run (checkpoint.py calls it)

`run` does, in order: asks AXoR what this run has (/open); restores the mission's workspace into /work/mission; fetches the
credentials the run was granted into memory-backed files; samples the run's processes while the command runs in /work/mission
with a time limit; then sends back what changed in the workspace and the measurements. It exits with the command's exit code
(124 when the time ran out), so everything after it behaves as for a bare command.

It talks only to $SANDBOX_PROXY_URL/rlm/aef/…, the run's own endpoint, always directly (never through the internet proxy).
Standard library only. What it reports about the run is the run's own word: AXoR labels it so (exec_env.py)."""
import base64, hashlib, json, os, re, shutil, signal, subprocess, sys, threading, time, urllib.error, urllib.request

WORK = os.environ.get("AXOR_AEF_WORK", "/work")           # /work in a run; tests point it elsewhere
MISSION = os.path.join(WORK, "mission")
STATE = os.path.join(WORK, ".axor", "aef.json")           # what this run started from, for save points
READ_ONLY = ("team", "shared", ".axor")                   # top-level folders of the workspace a run never saves
PART = 3_000_000                                          # bytes of a file per request: base64 of it stays under the endpoint's 8 MB
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the run's own endpoint is reached directly, always


def say(text): print(text, flush=True)


def call(path, body=None, timeout=120):
    url = os.environ.get("SANDBOX_PROXY_URL", "").rstrip("/") + "/rlm/aef" + path
    req = urllib.request.Request(url, data=json.dumps(body or {}).encode(), method="POST", headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with OPENER.open(req, timeout=timeout) as r: return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try: msg = json.loads(e.read() or b"{}")
            except ValueError: msg = {}
            err = msg.get("error")
            return {"error": (err.get("message") if isinstance(err, dict) else err) or f"HTTP {e.code}", "code": e.code}
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = str(e)
            time.sleep(1 + attempt)
    return {"error": f"AXoR didn't answer: {last}", "code": 0}


def sha_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- the workspace
def fetch(files, root):
    """Writes every file of {path: [sha, bytes, mode]} under root, asking AXoR for the contents in parts."""
    by_sha = {}
    for path, (sha, _size, _mode) in files.items(): by_sha.setdefault(sha, []).append(path)
    os.makedirs(os.path.join(WORK, ".axor", "in"), exist_ok=True)
    tmp = lambda sha: os.path.join(WORK, ".axor", "in", sha)
    want, got = {sha: 0 for sha in by_sha}, 0
    for sha in want: open(tmp(sha), "wb").close()
    while want:
        r = call("/ws/get", {"want": [[s, o] for s, o in list(want.items())[:400]]})
        if r.get("error"): raise RuntimeError(f"the workspace couldn't be restored: {r['error']}")
        if not r.get("parts"): raise RuntimeError("the workspace couldn't be restored: AXoR sent nothing")
        for p in r["parts"]:
            data = base64.b64decode(p["data"])
            with open(tmp(p["sha"]), "ab") as f: f.write(data)
            got += len(data)
            if p.get("last"): want.pop(p["sha"], None)
            else: want[p["sha"]] = p["offset"] + len(data)
    for sha, paths in by_sha.items():
        for i, path in enumerate(paths):
            dst = os.path.join(root, path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.lexists(dst): os.remove(dst)
            if i == len(paths) - 1: os.replace(tmp(sha), dst)
            else: shutil.copyfile(tmp(sha), dst)
            os.chmod(dst, 0o755 if files[path][2] & 0o100 else 0o644)
    return got


def lock(path):
    """Read-only for the run: the folder's own files and folders lose their write bits."""
    for d, dirs, names in os.walk(path, topdown=False):
        for n in names:
            p = os.path.join(d, n)
            if not os.path.islink(p): os.chmod(p, os.stat(p).st_mode & ~0o222)
        os.chmod(d, os.stat(d).st_mode & ~0o222)


def pull(info):
    ws = info.get("workspace") or {}
    if not ws.get("on"): return {"snapshot": None, "files": {}, "conflicted": []}
    os.makedirs(MISSION, exist_ok=True)
    lst = call("/ws/list")
    if lst.get("error"): raise RuntimeError(f"the workspace couldn't be listed: {lst['error']}")
    n = fetch(lst.get("files") or {}, MISSION)
    for path, target in (lst.get("links") or {}).items():
        dst = os.path.join(MISSION, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.lexists(dst): os.symlink(target, dst)
    # A file snapshot holds no empty folders, and Git calls a folder a repository only if .git/refs and .git/objects are there.
    # A checkout whose refs are packed (a clone at a tag) has nothing but empty folders under .git/refs: give Git's own back.
    for d, _dirs, names in os.walk(MISSION):
        if os.path.basename(d) == ".git" and "HEAD" in names:
            for sub in ("refs/heads", "refs/tags", "objects/info", "objects/pack"): os.makedirs(os.path.join(d, sub), exist_ok=True)
    if lst.get("shared"):
        fetch(lst["shared"], os.path.join(MISSION, "shared"))
    for ro in ("team", "shared"):
        if os.path.isdir(os.path.join(MISSION, ro)): lock(os.path.join(MISSION, ro))
    if not os.path.lexists(os.path.join(MISSION, ".axor")): os.symlink(os.path.join(WORK, ".axor"), os.path.join(MISSION, ".axor"))  # `python3 .axor/…` keeps working
    state = os.path.join(MISSION, ".state", f"task-{info['task']}") if info.get("task") else ""
    if lst.get("state_import") and state:   # the task's last checkpoint from before the workspace was switched on: unpacked once
        os.makedirs(state, exist_ok=True)
        subprocess.run(["tar", "-xz", "-C", state], input=base64.b64decode(lst["state_import"]), check=False)
    say(f"@@AXOR-WORKSPACE restored snapshot #{lst.get('snapshot') or 0}: {len(lst.get('files') or {})} files, {n // 1000} kB"
        + (f"; {len(lst.get('shared') or {})} shared read-only" if lst.get("shared") else ""))
    return {"snapshot": lst.get("snapshot"), "files": lst.get("files") or {}, "conflicted": []}


def scan(limits):
    """The workspace as it is now: ({path: [sha, bytes, mode]}, {link: target}, [(path, why) left out])."""
    files, links, skipped = {}, {}, []
    secret = re.compile(limits["secret_re"], re.I) if limits.get("secret_re") else None
    exclude, cap = set(limits.get("exclude") or ()), int(limits.get("file_bytes") or 0)
    for d, dirs, names in os.walk(MISSION):
        rel_d = os.path.relpath(d, MISSION)
        rel_d = "" if rel_d == "." else rel_d
        if not rel_d: dirs[:] = [x for x in dirs if x not in READ_ONLY]
        keep = []
        for x in dirs:
            p = os.path.join(d, x)
            if os.path.islink(p): links[os.path.join(rel_d, x)] = os.readlink(p)       # a link to a folder is kept as a link, never followed
            elif x in exclude or os.path.exists(os.path.join(p, "CACHEDIR.TAG")): skipped.append((os.path.join(rel_d, x) + "/", "build output or a cache"))
            else: keep.append(x)
        dirs[:] = keep
        for n in names:
            p, rel = os.path.join(d, n), os.path.join(rel_d, n)
            if not rel_d and n in READ_ONLY: continue
            try:
                if os.path.islink(p): links[rel] = os.readlink(p); continue
                st = os.stat(p)
                if not os.path.isfile(p): skipped.append((rel, "not a regular file")); continue
                if secret and secret.search(rel): skipped.append((rel, "looks like a secret")); continue
                if cap and st.st_size > cap: skipped.append((rel, f"over {cap // 1_000_000} MB")); continue
                files[rel] = [sha_of(p), st.st_size, 0o755 if st.st_mode & 0o100 else 0o644]
            except OSError as e: skipped.append((rel, f"unreadable: {e.strerror}"))
    return files, links, skipped


def push(info, base, final=True):
    """Sends what the workspace holds now; AXoR writes a snapshot when anything changed. Returns AXoR's answer."""
    limits = info.get("limits") or {}
    files, links, skipped = scan(limits)
    shas = sorted({v[0] for v in files.values()} - {v[0] for v in (base.get("files") or {}).values()})
    missing = []
    for i in range(0, len(shas), 2000):
        r = call("/ws/have", {"shas": shas[i:i + 2000]})
        if r.get("error"): return {"error": r["error"]}
        missing += r.get("missing") or []
    where = {}
    for path, v in files.items(): where.setdefault(v[0], path)
    sent = 0
    for sha in missing:
        size, off = files[where[sha]][1], 0
        with open(os.path.join(MISSION, where[sha]), "rb") as f:
            while True:
                data = f.read(PART)
                last = off + len(data) >= size
                r = call("/ws/put", {"sha": sha, "offset": off, "data": base64.b64encode(data).decode(), "last": last}, timeout=300)
                if r.get("error"): return {"error": f"{where[sha]}: {r['error']}"}
                off += len(data); sent += len(data)
                if last: break
    r = call("/ws/commit", {"base": base.get("snapshot"), "files": files, "links": links, "conflicted": base.get("conflicted") or [], "final": bool(final),
                            "skipped": [{"path": p, "why": w} for p, w in skipped[:200]]}, timeout=300)
    if r.get("error"): return {"error": r["error"]}
    r["sent_bytes"] = sent
    return r


def report(r, what="saved"):
    if r.get("error"): say(f"@@AXOR-WORKSPACE not saved: {r['error']}"); return
    c = r.get("changes") or {}
    line = (f"@@AXOR-WORKSPACE {what} snapshot #{r['snapshot']}: {len(c.get('added') or [])} added, {len(c.get('changed') or [])} changed, "
            f"{len(c.get('removed') or [])} removed, {r.get('sent_bytes', 0) // 1000} kB sent") if r.get("snapshot") and r.get("new") else "@@AXOR-WORKSPACE nothing changed: no new snapshot"
    say(line)
    for x in (c.get("conflicts") or [])[:20]: say(f"@@AXOR-WORKSPACE conflict: {x['path']} was changed by another run too; yours is kept as {x['kept_as']}")
    for x in (c.get("refused") or [])[:20]: say(f"@@AXOR-WORKSPACE left out: {x['path']} ({x['why']})")


# ---------------------------------------------------------------- measurements
class Sampler(threading.Thread):
    """Every few seconds: the run's processes from /proc. Peak memory and process count, CPU time per process, the tree at the peak."""
    def __init__(self, every):
        super().__init__(daemon=True)
        self.every, self.stop_flag = max(0.5, float(every or 2)), threading.Event()
        self.tick, self.page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
        self.cpu, self.cmd, self.rss = {}, {}, {}             # per pid: CPU seconds seen last, command, peak resident bytes
        self.peak_rss, self.peak_procs, self.tree, self.samples = 0, 0, [], 0
        self.now_rss, self.now_procs = 0, 0                 # the last sample alone, for the report sent while the run goes on

    def once(self):
        now, total = [], 0
        for pid in os.listdir("/proc"):
            if not pid.isdigit(): continue
            try:
                raw = open(f"/proc/{pid}/stat").read()
                f = raw[raw.rindex(")") + 2:].split()
                cpu, rss = (int(f[11]) + int(f[12])) / self.tick, int(f[21]) * self.page
                c = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()   # read each time: a process becomes another by exec
                self.cmd[pid] = (c or raw[raw.index("(") + 1:raw.rindex(")")])[:200]
            except (OSError, ValueError, IndexError): continue
            self.cpu[pid] = cpu; self.rss[pid] = max(self.rss.get(pid, 0), rss); total += rss
            now.append({"pid": int(pid), "ppid": int(f[1]), "cmd": self.cmd[pid], "rss_mb": round(rss / 1e6, 1), "cpu_s": round(cpu, 2)})
        self.samples += 1
        self.now_rss, self.now_procs = total, len(now)
        self.peak_procs = max(self.peak_procs, len(now))
        if total > self.peak_rss: self.peak_rss, self.tree = total, sorted(now, key=lambda p: -p["rss_mb"])[:60]

    def run(self):
        """Often at first, so a short command is seen at all, then at the steady interval. A process that starts and ends between
        two samples is never seen: the cgroup's own totals (cgroup(), where the runtime shows them) don't have that gap."""
        t0, wait = time.time(), 0.2
        while not self.stop_flag.wait(wait):
            try: self.once()
            except Exception: pass   # noqa: BLE001 - a sample that fails is one sample fewer
            wait = 0.5 if time.time() - t0 < 10 else self.every

    def so_far(self, wall):
        """What the run has used up to now: the figures of the final report that exist while it runs, and the last sample's own."""
        return {"live": True, "v": 1, "sample_s": self.every, "samples": self.samples, "cpu_seconds": round(sum(list(self.cpu.values())), 2),
                "peak_rss_mb": round(self.peak_rss / 1e6, 1), "peak_procs": self.peak_procs, "rss_mb": round(self.now_rss / 1e6, 1), "procs": self.now_procs,
                "wall_s": round(wall, 1)}

    def result(self):
        self.stop_flag.set()
        try: self.once()
        except Exception: pass   # noqa: BLE001
        top = {}
        for pid, cpu in self.cpu.items():
            name = (self.cmd.get(pid) or "?").split(" ")[0].rsplit("/", 1)[-1][:60]
            t = top.setdefault(name, {"cmd": name, "cpu_s": 0.0, "peak_rss_mb": 0.0, "procs": 0})
            t["cpu_s"] = round(t["cpu_s"] + cpu, 2); t["peak_rss_mb"] = max(t["peak_rss_mb"], round(self.rss.get(pid, 0) / 1e6, 1)); t["procs"] += 1
        return {"sample_s": self.every, "samples": self.samples, "cpu_seconds": round(sum(self.cpu.values()), 2), "peak_rss_mb": round(self.peak_rss / 1e6, 1),
                "peak_procs": self.peak_procs, "tree_at_peak": self.tree, "top": sorted(top.values(), key=lambda t: -t["cpu_s"])[:12]}


def cgroup():
    """What the runtime's own accounting says, where it shows it (not every sandbox runtime does)."""
    out = {}
    def read(name):
        try: return open(f"/sys/fs/cgroup/{name}").read()
        except OSError: return ""
    for key, name in (("memory_peak_mb", "memory.peak"), ("pids_peak", "pids.peak")):
        v = read(name).strip()
        if v.isdigit(): out[key] = round(int(v) / 1e6, 1) if key == "memory_peak_mb" else int(v)
    m = re.search(r"^usage_usec (\d+)", read("cpu.stat"), re.M)
    if m: out["cpu_usec"] = int(m.group(1))
    m = re.search(r"^oom_kill (\d+)", read("memory.events"), re.M)
    if m: out["oom_kills"] = int(m.group(1))
    return out


def disk():
    out = {}
    for name, path in (("work", WORK), ("repo", "/repo"), ("tmp", "/tmp")) if WORK == "/work" else (("work", WORK),):
        total = 0
        for d, _dirs, names in os.walk(path):
            for n in names:
                try: total += os.lstat(os.path.join(d, n)).st_size
                except OSError: pass
        out[name] = round(total / 1e6, 1)
    return out


def report_live(sampler, t1, done, every):
    """While the command runs: what it has used so far, sent to AXoR every few seconds, so a running run's figures can be shown.
    A report that fails is one report fewer; the final report after the command replaces them all."""
    while not done.wait(every):
        try: call("/stats", sampler.so_far(time.time() - t1), timeout=5)
        except Exception: pass   # noqa: BLE001


# ---------------------------------------------------------------- credentials
def secrets(info, env):
    names = info.get("secrets") or []
    if not names: return
    d = "/dev/shm/axor/secrets" if os.path.isdir("/dev/shm") else os.path.join("/tmp", ".axor-secrets")   # memory-backed where there is one
    os.makedirs(d, mode=0o700, exist_ok=True)
    given = []
    for name in names:
        r = call("/secret", {"name": name})
        if r.get("error") or "value" not in r: say(f"@@AXOR-SECRET {name} not given: {r.get('error') or 'no value'}"); continue
        p = os.path.join(d, name)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o400)
        with os.fdopen(fd, "w") as f: f.write(r["value"])
        given.append(name)
    env["AXOR_SECRETS"] = d
    if given: say(f"@@AXOR-SECRET given as files in $AXOR_SECRETS: {', '.join(given)}")


# ---------------------------------------------------------------- commands
def cmd_run(seconds, command):
    t0 = time.time()
    info = call("/open")
    if info.get("error"):
        say(f"@@AXOR-AEF this run couldn't be opened ({info['error']}): the command wasn't started"); return 70
    env = dict(os.environ)
    try: base = pull(info)
    except Exception as e:  # noqa: BLE001 - without its workspace the run would work on nothing and then save over it
        say(f"@@AXOR-AEF {e}: the command wasn't started"); return 70
    ws_on = bool((info.get("workspace") or {}).get("on"))
    if ws_on:
        env["AXOR_MISSION_DIR"] = MISSION; env["AXOR_AEF_WORKSPACE"] = "1"
        if info.get("task"):
            env["AXOR_STATE"] = os.path.join(MISSION, ".state", f"task-{info['task']}")
            os.makedirs(env["AXOR_STATE"], exist_ok=True)
            if os.listdir(env["AXOR_STATE"]): env["AXOR_RESUMED"] = "1"
        if info.get("agent_dir"):
            os.makedirs(os.path.join(MISSION, info["agent_dir"]), exist_ok=True); env["AXOR_AGENT_DIR"] = os.path.join(MISSION, info["agent_dir"])
        os.makedirs(os.path.join(MISSION, "artifacts"), exist_ok=True)
    json.dump({"info": info, "base": base}, open(STATE, "w"))
    secrets(info, env)
    sampler = Sampler(info.get("sample_s") or 2); sampler.start()
    t1 = time.time()
    done = threading.Event()
    live = threading.Thread(target=report_live, args=(sampler, t1, done, max(2.0, float(info.get("live_s") or 10))), daemon=True)
    if info.get("live_s"): live.start()
    proc = subprocess.Popen(["bash", "-c", command], cwd=MISSION if ws_on else WORK, env=env, start_new_session=True)
    signal.signal(signal.SIGTERM, lambda *_: os.killpg(proc.pid, signal.SIGKILL))
    timed_out = False
    try: code = proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try: os.killpg(proc.pid, sig)
            except ProcessLookupError: break
            try: proc.wait(timeout=wait); break
            except subprocess.TimeoutExpired: pass
        code = 124
    wall = time.time() - t1
    done.set()
    if live.is_alive(): live.join(timeout=8)   # no report of "so far" may arrive after the final one
    stats = {"v": 1, **sampler.result(), "cgroup": cgroup(), "disk_mb": disk(), "gpu": None, "wall_s": round(wall, 1), "setup_s": round(t1 - t0, 1),
             "command_exit": code, "timed_out": timed_out}
    if ws_on:
        base = json.load(open(STATE))["base"]   # a save point during the run moved it on
        r = push(info, base)
        report(r)
        c = r.get("changes") or {}
        stats["files"] = {"added": len(c.get("added") or []), "changed": len(c.get("changed") or []), "removed": len(c.get("removed") or []),
                          "conflicts": len(c.get("conflicts") or []), "refused": len(c.get("refused") or []), "bytes_sent": r.get("sent_bytes", 0),
                          **({"error": r["error"][:300]} if r.get("error") else {})}
    stats["total_s"] = round(time.time() - t0, 1)
    call("/stats", stats, timeout=30)
    say(f"@@AXOR-STATS cpu {stats['cpu_seconds']} s, peak memory {stats['peak_rss_mb']} MB, {stats['peak_procs']} processes at most, "
        f"disk {stats['disk_mb'].get('work', 0)} MB, {stats['wall_s']} s")
    return code


def cmd_save():
    try: st = json.load(open(STATE))
    except (OSError, ValueError):
        say("@@AXOR-WORKSPACE not saved: this run has no workspace"); return 1
    info, base = st["info"], st["base"]
    if not (info.get("workspace") or {}).get("on"):
        say("@@AXOR-WORKSPACE not saved: this run has no workspace"); return 1
    r = push(info, base, final=False)
    report(r)
    if r.get("error"): return 1
    if r.get("snapshot"):   # the next save, and the run's last one, start from here; a conflicted path stays one for the rest of the run
        files, links, _ = scan(info.get("limits") or {})
        conflicted = sorted(set(base.get("conflicted") or []) | {x["path"] for x in (r.get("changes") or {}).get("conflicts") or []})
        json.dump({"info": info, "base": {"snapshot": r["snapshot"], "files": r.get("files") or files, "conflicted": conflicted}}, open(STATE, "w"))
    return 0


def main(argv):
    if len(argv) >= 3 and argv[0] == "run":
        try: seconds, command = max(1, int(argv[1])), base64.b64decode(argv[2]).decode()
        except (ValueError, UnicodeDecodeError):
            say("@@AXOR-AEF bad arguments"); return 64
        return cmd_run(seconds, command)
    if argv[:1] == ["save"]: return cmd_save()
    say("usage: aef.py run <seconds> <base64 command> | aef.py save"); return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
