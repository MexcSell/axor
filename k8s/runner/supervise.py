#!/usr/bin/env python3
"""AXoR's VM runner, the pod side (D-013 design §2 and §4; G5-4 V4.2). One pod runs this once: it boots one throwaway KVM VM
from the read-only base disk for one job, waits for it to power off, and hands the VM's result to AXoR. Nothing survives it.

The pod has /dev/kvm (resource axor.dev/kvm) and nothing else from the host: no privileges, no added capabilities, no
service-account token. The job arrives in ConfigMaps under /input (manifest.json maps keys to paths; .axor-job/job.json is
the job AXoR validated). The VM sees two extra disks: the job as a tar (read-only) and an empty one it writes its result to.
The result goes to AXoR's own endpoint for this run ($AXOR_RESULT_URL, a one-run token), never anywhere else.

Network: QEMU's user-mode network. `none` → restrict=on (the VM reaches nothing). `registry` → the VM is given the egress
proxy's address with this run's token; the namespace's NetworkPolicy lets the pod reach that proxy and AXoR, nothing else.
"""
import base64, hashlib, io, json, os, subprocess, sys, tarfile, time, urllib.request

INPUT, WORK, BASE = os.getenv("AXOR_INPUT", "/input"), os.getenv("AXOR_WORK", "/work"), os.getenv("AXOR_BASE", "/base")
URL, NETWORK, PROXY = os.getenv("AXOR_RESULT_URL", ""), os.getenv("AXOR_NETWORK", "none"), os.getenv("AXOR_PROXY", "")
BUILD_PROXY = os.getenv("AXOR_BUILD_PROXY", "")  # network `build`: a second proxy run, for the Dockerfile's build steps only
TIMEOUT, CPUS, MEM = int(os.getenv("AXOR_TIMEOUT", "1800")), int(os.getenv("VM_CPUS", "2")), int(os.getenv("VM_MEM_MB", "4096"))
OUT_MB, BOOT_GRACE = 16, 180
T0 = time.time()


def say(msg): print(f"[runner +{time.time() - T0:5.0f}s] {msg}", flush=True)


def pack():
    """The job disk: job.json (with the proxy this run may use) and files/<path> for every workspace file sent along."""
    m = json.load(open(f"{INPUT}/manifest.json"))
    job, n = None, 0
    with tarfile.open(f"{WORK}/in.tar", "w:") as t:
        def add(name, data):
            ti = tarfile.TarInfo(name); ti.size = len(data); ti.mode = 0o755 if name.endswith((".sh", ".py")) else 0o644
            t.addfile(ti, io.BytesIO(data))
        for key, path in sorted(m.items()):
            data = open(f"{INPUT}/{key}", "rb").read()
            if path == ".axor-job/job.json": job = json.loads(data); continue
            if path.startswith("/") or ".." in path.split("/"): continue
            add(f"files/{path}", data); n += 1
        if job is None: raise SystemExit("no job.json in the input")
        if NETWORK != "none" and PROXY: job["proxy"] = PROXY
        if NETWORK == "build" and BUILD_PROXY: job["build_proxy"] = BUILD_PROXY
        add("job.json", json.dumps(job).encode())
    return job, n


def report(body):
    if os.getenv("AXOR_RESULT_FILE"):  # local staging without AXoR's endpoint (k8s/runner/stage-local.sh): the same body, in a file
        json.dump(body, open(os.environ["AXOR_RESULT_FILE"], "w")); return True
    if not URL: say("no result URL: nothing to hand the result to"); return False
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return r.status == 200
        except Exception as e:  # noqa: BLE001 - retried, then reported in the log
            say(f"couldn't hand over the result ({getattr(e, 'reason', e)}); attempt {attempt + 1} of 5"); time.sleep(3 * (attempt + 1))
    return False


def main():
    sup = {"network": NETWORK, "vm": {"cpus": CPUS, "memory_mb": MEM}, "started": T0}
    body = {"supervisor": sup, "result": None, "files": {}}
    try:
        try: os.close(os.open("/dev/kvm", os.O_RDWR))
        except OSError as e: raise RuntimeError(f"/dev/kvm isn't usable in this pod: {e}")
        base = json.load(open(f"{BASE}/base.json")) if os.path.exists(f"{BASE}/base.json") else {}
        sup["base"] = {k: base.get(k) for k in ("sha256", "built", "debian", "docker", "runner_script_sha256")}
        job, n = pack()
        sup["inputs"] = {"job_sha256": hashlib.sha256(json.dumps({k: v for k, v in job.items() if k not in ("id", "proxy", "build_proxy")}, sort_keys=True).encode()).hexdigest(), "files": n}
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", f"{BASE}/base.qcow2", f"{WORK}/disk.qcow2"], check=True)
        with open(f"{WORK}/out.img", "wb") as f: f.truncate(OUT_MB << 20)
        net = "user,id=n0" + (",restrict=on" if NETWORK == "none" else "")
        say(f"booting the VM ({CPUS} CPUs, {MEM} MB, network {NETWORK}, {n} files)")
        b0 = time.time()
        q = subprocess.run(["timeout", "-k", "10", str(TIMEOUT + BOOT_GRACE), "qemu-system-x86_64", "-accel", "kvm", "-cpu", "host", "-smp", str(CPUS),
                            "-m", str(MEM), "-no-reboot", "-display", "none", "-monitor", "none", "-serial", f"file:{WORK}/serial.log",
                            "-drive", f"file={WORK}/disk.qcow2,if=virtio", "-drive", f"file={WORK}/in.tar,if=virtio,format=raw,readonly=on",
                            "-drive", f"file={WORK}/out.img,if=virtio,format=raw", "-netdev", net, "-device", "virtio-net-pci,netdev=n0"])
        sup["qemu_exit"], sup["vm_seconds"] = q.returncode, round(time.time() - b0, 1)
        say(f"the VM ended (qemu exit {q.returncode}) after {sup['vm_seconds']} s")
        try:
            with tarfile.open(f"{WORK}/out.img", "r:") as t:
                for m in t.getmembers():
                    if not m.isfile(): continue
                    data = t.extractfile(m).read()
                    if m.name == "result.json": body["result"] = json.loads(data)
                    elif m.name.startswith("files/"):
                        try: body["files"][m.name[6:]] = {"text": data.decode()}
                        except UnicodeDecodeError: body["files"][m.name[6:]] = {"b64": base64.b64encode(data).decode()}
        except (tarfile.TarError, ValueError, OSError) as e:
            sup["error"] = ("The job ran past its time limit and the VM was stopped." if q.returncode in (124, 137) else
                            f"The VM ended without a result ({type(e).__name__}).")
    except Exception as e:  # noqa: BLE001 - always report
        sup["error"] = f"{type(e).__name__}: {e}"[:400]
    if body["result"] is None:
        sup.setdefault("error", "The VM ended without a result.")
        try: sup["serial_tail"] = open(f"{WORK}/serial.log", errors="replace").read()[-4000:]
        except OSError: pass
    sup["ended"] = time.time()
    ok = report(body)
    say("result handed to AXoR" if ok else "RESULT NOT DELIVERED")
    sys.exit(0 if ok and body["result"] is not None else 1)


if __name__ == "__main__":
    main()
