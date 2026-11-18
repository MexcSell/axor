"""Saves this run's progress to AXoR, so the next sandbox run of the same task can resume (AXoR's sandbox ships this as
.axor/checkpoint.py).

    python3 .axor/checkpoint.py            save $AXOR_STATE now (call it after each step that's worth not redoing)
    python3 .axor/checkpoint.py --final    what the runner calls when the command ends, timed out or not

Keep in $AXOR_STATE (/work/.axor/state) only what resuming needs: a progress file, partial results, a small cache. It's sent
as a .tar.gz through $SANDBOX_PROXY_URL/checkpoint and kept in AXoR the moment it's saved, so a restart, a timeout or a lost
pod doesn't lose it. The next run of the task starts with it unpacked in $AXOR_STATE and AXOR_RESUMED=1 set. Over the size
limit, the save is refused and the earlier checkpoint stays.
"""
import base64, io, json, os, sys, tarfile, urllib.error, urllib.request

STATE = os.environ.get("AXOR_STATE", "/work/.axor/state")


def main():
    final = "--final" in sys.argv[1:]
    if os.environ.get("AXOR_AEF_WORKSPACE") == "1":  # the task's progress folder lives in the mission workspace: saving it is a workspace save (AEF, D-032)
        if final: return 0                           # the run's own end saves the workspace
        os.execv(sys.executable, [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "aef.py"), "save"])
    url = os.environ.get("SANDBOX_PROXY_URL", "").rstrip("/")
    if not url:
        print("@@AXOR-CHECKPOINT not saved: no SANDBOX_PROXY_URL (not in an AXoR sandbox)"); return 1
    if not os.path.isdir(STATE) or not os.listdir(STATE):
        if not final: print(f"@@AXOR-CHECKPOINT nothing to save: {STATE} is empty")
        return 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in sorted(os.listdir(STATE)): tar.add(os.path.join(STATE, name), arcname=name)
    data = base64.b64encode(buf.getvalue()).decode()
    req = urllib.request.Request(url + "/checkpoint", data=json.dumps({"data": data}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: out = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read() or b"{}").get("error", {}).get("message") or str(e)
        except ValueError: msg = str(e)
        print(f"@@AXOR-CHECKPOINT not saved: {msg}"); return 1
    except OSError as e:
        print(f"@@AXOR-CHECKPOINT not saved: {getattr(e, 'reason', e)}"); return 1
    n = out.get("saved_bytes", len(data))
    print(f"@@AXOR-CHECKPOINT saved {n / 1000:.1f} kB{' (at the end of the run)' if final else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
