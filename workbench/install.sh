#!/usr/bin/env bash
# Installs the AXoR Workbench on this host (see README.md): ./workbench/install.sh [folder…]   (default /home/thomas/bit)
# - copies workbench.py to /opt/axor-workbench and starts axor-workbench.service on 10.42.0.1:8350 (pod network only)
# - writes /etc/axor-workbench.json once (a fresh token, the folders, their checks); later runs keep your edits
# - puts the token in the k8s secret axor/workbench, which the web pod reads after ./k8s/redeploy.sh
# Run it again after pulling a new workbench.py.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run it as root: the service runs Claude Code with root's login." >&2; exit 1; }
here=$(cd "$(dirname "$0")" && pwd)
conf=/etc/axor-workbench.json
command -v claude >/dev/null || [[ -x /root/.local/bin/claude ]] || { echo "Claude Code isn't installed for root (claude not found)." >&2; exit 1; }
(( $# )) || set -- /home/thomas/bit
for d in "$@"; do git -C "$d" rev-parse --git-dir >/dev/null 2>&1 || { echo "$d isn't a git repository." >&2; exit 1; }; done

install -d -m 755 /opt/axor-workbench /var/lib/axor-workbench
install -m 755 "$here/workbench.py" /opt/axor-workbench/workbench.py

if [[ ! -f $conf ]]; then
  python3 - "$conf" "$@" <<'EOF'
import json, os, secrets, sys
from pathlib import Path
conf, folders = sys.argv[1], sys.argv[2:]
repos = {}
for f in folders:
    p = Path(f).resolve()
    rid = "".join(c if c.isalnum() else "-" for c in p.name.lower()).strip("-")[:40] or "repo"
    r = {"path": str(p), "name": p.name,
         "skip": ["btcli-venv", "local-llm", "external-sources"],          # big folders the file browser leaves out
         "deny": ["ridges-intel", "workspace/apikeys.md"],                  # agents may not read these: other miners' agents, keys
         "checks": {}}
    if (p / "agent30").is_dir():
        r["checks"]["handin30"] = {"label": "agent30 hand-in tests", "argv": ["python3", "-m", "unittest", "discover", "-s", "agent30", "-p", "test_*.py"],
                                   "cwd": "{worktree}", "timeout": 900, "note": "Local, free"}
    if (p / "agent").is_dir():
        r["checks"]["tests28"] = {"label": "agent (comp 28) tests", "argv": ["python3", "-m", "unittest", "discover", "-s", "agent", "-p", "test_*.py"],
                                  "cwd": "{worktree}", "timeout": 900, "note": "Local, free"}
    if (p / "eval/eval.py").is_file():
        r["_example_check"] = {"label": "Quick eval on OpenRouter", "note": "Costs OpenRouter credit, up to an hour. Move it under checks with the task you want.",
                               "argv": ["python3", str(p / "eval/eval.py"), "--target", "openrouter30", "--agent", "{worktree}/agent30/agent.py",
                                        "--label", "bench-{run}", "--repeats", "1", "--tasks", "TASK-NAME"], "timeout": 3600}
    repos[rid] = r
json.dump({"listen": "10.42.0.1", "port": 8350, "token": secrets.token_hex(24), "parallel": 2, "max_budget_usd": 5.0,
           "allow_from": ["10.42.0.0/16"], "repos": repos}, open(conf, "w"), indent=2)
os.chmod(conf, 0o600)
print(f"Wrote {conf} with {', '.join(repos)}")
EOF
else
  echo "Keeping $conf (edit it to add folders or checks, then: systemctl restart axor-workbench)"
fi

install -m 644 "$here/axor-workbench.service" /etc/systemd/system/axor-workbench.service
systemctl daemon-reload
systemctl enable --now axor-workbench
systemctl restart axor-workbench

token=$(python3 -c "import json; print(json.load(open('$conf'))['token'])")
if command -v kubectl >/dev/null && kubectl get ns axor >/dev/null 2>&1; then
  kubectl -n axor create secret generic workbench --from-literal=token="$token" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "Saved the token in the secret axor/workbench."
fi
sleep 2
curl -fsS http://10.42.0.1:8350/health >/dev/null && echo "axor-workbench answers on 10.42.0.1:8350." || echo "axor-workbench doesn't answer yet: journalctl -u axor-workbench"
echo "Next: ./k8s/redeploy.sh, so the web pod gets WORKBENCH_URL and the token. Then Competition teams → Workflow."
