"""System: this server's CPU, memory, swap, load and disk, and AXoR's own share of them (admins only).

Everything is read from /proc, the cgroup files and statvfs, so it needs no extra package or privilege. Inside Docker,
/proc/stat, /proc/meminfo, /proc/loadavg and /proc/uptime still describe the whole machine, while the cgroup files
describe AXoR's own container (outside a container: this process). A sampler thread keeps the last hour in 5-second
steps for the app bar, the status bar and the System page's charts.
"""
import os, shutil, threading, time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Request

STEP, KEEP = 5, 720  # seconds between samples; samples kept (an hour)
CG = Path("/sys/fs/cgroup")

def _read(path):
    try: return Path(path).read_text()
    except OSError: return ""

def _cpu():
    """(busy, total) jiffies over all cores since boot."""
    v = [int(x) for x in _read("/proc/stat").split("\n", 1)[0].split()[1:9]]  # user nice system idle iowait irq softirq steal
    return (sum(v) - v[3] - v[4], sum(v)) if len(v) >= 5 else (0, 0)

def _meminfo():
    m = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if v.strip(): m[k] = int(v.split()[0]) * 1024
    return m

def _app():
    """(CPU seconds, memory bytes) of AXoR's container (cgroup v2, then v1), or of this process outside one."""
    if (CG / "memory.current").exists():  # the root cgroup (a plain host) has no memory.current
        st = dict(l.split() for l in _read(CG / "memory.stat").splitlines() if l.count(" ") == 1)
        usec = next((int(l.split()[1]) for l in _read(CG / "cpu.stat").splitlines() if l.startswith("usage_usec ")), 0)
        return usec / 1e6, max(0, int(_read(CG / "memory.current") or 0) - int(st.get("inactive_file", 0)))  # as `docker stats`
    if (CG / "memory/memory.usage_in_bytes").exists():
        return int(_read(CG / "cpuacct/cpuacct.usage") or 0) / 1e9, int(_read(CG / "memory/memory.usage_in_bytes") or 0)
    f = _read("/proc/self/stat").rsplit(")", 1)[-1].split()  # fields after the command name; utime, stime are 12, 13
    rss = next((int(l.split()[1]) * 1024 for l in _read("/proc/self/status").splitlines() if l.startswith("VmRSS:")), 0)
    return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK") if len(f) > 12 else 0, rss

class Monitor:
    def __init__(self, data_dir):
        self.data_dir, self.cpus = str(data_dir), os.cpu_count() or 1
        self.history, self._last, self._lock, self._thread = deque(maxlen=KEEP), None, threading.Lock(), None

    def sample(self):
        t, (busy, total), (app_s, app_mem), m = time.time(), _cpu(), _app(), _meminfo()
        prev, self._last = self._last, (t, busy, total, app_s)
        if not prev: return None  # CPU use is a difference: the first reading only sets the baseline
        dt, dtotal = t - prev[0], total - prev[2]
        mt, st = m.get("MemTotal", 0), m.get("SwapTotal", 0)
        s = {"t": round(t, 1),
             "cpu": round((busy - prev[1]) / dtotal * 100, 1) if dtotal > 0 else 0.0,
             "mem": mt - m.get("MemAvailable", m.get("MemFree", 0)), "swap": st - m.get("SwapFree", st),
             "load": round(os.getloadavg()[0], 2),
             "app_cpu": round((app_s - prev[3]) / dt * 100, 1) if dt > 0 else 0.0,  # percent of one core, as `docker stats`
             "app_mem": app_mem}
        with self._lock: self.history.append(s)
        return s

    def start(self):
        if self._thread: return
        def run():
            while True:
                try: self.sample()
                except Exception: pass  # an odd /proc read skips one point; the next one is fine
                time.sleep(STEP)
        self.sample()
        self._thread = threading.Thread(target=run, daemon=True, name="system-monitor"); self._thread.start()

    def snapshot(self, since=0.0):
        self.start()
        m, du = _meminfo(), shutil.disk_usage(self.data_dir)
        with self._lock: hist = [s for s in self.history if s["t"] > since]
        return {"cpus": self.cpus, "mem_total": m.get("MemTotal", 0), "swap_total": m.get("SwapTotal", 0),
                "load": [round(x, 2) for x in os.getloadavg()], "uptime": float((_read("/proc/uptime").split() or [0])[0]),
                "disk": {"total": du.total, "used": du.used, "free": du.free},  # free = what AXoR can still write, as `df`
                "kernel": os.uname().release, "step": STEP, "history": hist}

def build(admin, data_dir):
    r = APIRouter(prefix="/api/system")
    mon = Monitor(data_dir)
    r.state = {"monitor": mon}

    @r.get("")
    def system(req: Request, since: float = 0):
        admin(req)
        return mon.snapshot(since)

    return r
