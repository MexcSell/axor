"""A stand-in Kubernetes API for the sandbox (backend/app/sandbox.py): ConfigMaps and pods in axor-sandbox, pod status and the
runner's logs. Everything else answers 404, so the rest of AXoR sees an empty cluster.

By default a pod "runs" for a few seconds and logs the command it was given. With FAKE_KUBE_EXEC=1 it really runs the runner's
script on this machine, with /input, /work and /repo moved to a temporary folder and the pod's environment (so the sandbox
proxy and .axor/ridges_run.py are exercised end to end): only for tests whose commands you wrote yourself. A pod whose
command contains "slow-run" takes 30 s; GET /_pods lists what was created, with the specs.

    python tests/fake_kube_sandbox.py 8795      then KUBE_API=http://127.0.0.1:8795
"""
import json, os, re, subprocess, sys, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NS = "axor-sandbox"
EXEC = os.getenv("FAKE_KUBE_EXEC") == "1"
CMS, PODS, LOGS, LOCK = {}, {}, {}, threading.Lock()

def _run(name):
    pod = PODS[name]
    spec = pod["spec"]["containers"][0]
    env = {e["name"]: e["value"] for e in spec["env"]}
    time.sleep(1)
    pod["status"] = {"phase": "Running", "containerStatuses": [{"name": "runner", "state": {"running": {}}}]}
    if "slow-run" in env["AXOR_COMMAND"]: time.sleep(30)
    if EXEC:
        root = tempfile.mkdtemp(prefix="fake-sbx-")
        for d in ("input", "work", "repo"): os.makedirs(f"{root}/{d}")
        cm = CMS[pod["spec"]["volumes"][0]["configMap"]["name"]]
        for k, v in cm["data"].items(): open(f"{root}/input/{k}", "w").write(v)
        script = spec["command"][2].replace("/input/", f"{root}/input/").replace('"/work"', f'"{root}/work"').replace('"/work/"', f'"{root}/work/"')
        env |= {"RIDGES_REPO": f"{root}/repo", "PATH": os.environ["PATH"], "HOME": root}
        r = subprocess.run(["bash", "-c", script], cwd=f"{root}/work", env=env, capture_output=True, text=True, timeout=int(env["AXOR_TIMEOUT"]) + 30)
        out, code = r.stdout + r.stderr, r.returncode
    else:
        time.sleep(2)
        out, code = f"@@AXOR-START 00:00:00\n(fake sandbox) ran: {env['AXOR_COMMAND']}\nservices: {[c['name'] for c in pod['spec']['initContainers']]}\n@@AXOR-EXIT 0\n", 0
    with LOCK:
        if name not in PODS: return
        LOGS[name] = out
        pod["status"] = {"phase": "Succeeded" if code == 0 else "Failed", "containerStatuses": [{"name": "runner", "state": {"terminated": {"exitCode": code}}}]}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, raw=False):
        data = body.encode() if raw else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "text/plain" if raw else "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/_pods": return self._send(200, {"pods": PODS, "configmaps": list(CMS)})
        if path == f"/api/v1/namespaces/{NS}/pods": return self._send(200, {"items": list(PODS.values())})
        m = re.match(rf"^/api/v1/namespaces/{NS}/pods/([^/]+)(/log)?$", path)
        if m and m.group(1) in PODS:
            return self._send(200, LOGS.get(m.group(1), ""), raw=True) if m.group(2) else self._send(200, PODS[m.group(1)])
        self._send(404, {"kind": "Status", "message": "not found", "code": 404})
    def do_POST(self):
        path, b = self.path.split("?")[0], self._body()
        if path == f"/api/v1/namespaces/{NS}/configmaps":
            CMS[b["metadata"]["name"]] = b
            return self._send(201, b)
        if path == f"/api/v1/namespaces/{NS}/pods":
            name = b["metadata"]["name"]
            if b["spec"]["volumes"][0]["configMap"]["name"] not in CMS: return self._send(422, {"message": "the ConfigMap is missing"})
            PODS[name] = {**b, "status": {"phase": "Pending"}}
            threading.Thread(target=_run, args=(name,), daemon=True).start()
            return self._send(201, PODS[name])
        self._send(404, {"kind": "Status", "message": "not found", "code": 404})
    def do_DELETE(self):
        m = re.match(rf"^/api/v1/namespaces/{NS}/(pods|configmaps)/([^/?]+)", self.path)
        if m:
            with LOCK: (PODS if m.group(1) == "pods" else CMS).pop(m.group(2), None)
            return self._send(200, {"kind": "Status", "status": "Success"})
        self._send(404, {"kind": "Status", "message": "not found", "code": 404})
    do_PATCH = do_PUT = lambda self: self._send(404, {"kind": "Status", "message": "not found", "code": 404})

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8795), H).serve_forever()
