#!/usr/bin/env bash
# Installs gVisor (runsc) for k3s on this host, so sandbox runs with internet run under gVisor's kernel instead of the
# host's (k8s/base/57-egress.yaml: RuntimeClass "gvisor"). Run as root on the k3s host.
#
#   ./k8s/install-gvisor.sh            install the pinned release, register it with k3s's containerd, test it, label the node
#   ./k8s/install-gvisor.sh --check    say what's installed and whether a pod runs under it; changes nothing
#   ./k8s/install-gvisor.sh --off      remove the node label: AXoR stops starting runs with internet (binaries stay)
#
# What it changes: /usr/local/bin/runsc and containerd-shim-runsc-v1 (checksums verified), /etc/containerd/runsc.toml
# (systemd cgroups, as k3s uses for runc) and /var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.tmpl, which keeps
# k3s's own config ({{ template "base" . }}) and adds the runsc runtime (k3s doesn't detect runsc by itself). It restarts
# k3s once: running pods keep running, the Kubernetes API is away for a few seconds. Last, a test pod must run under gVisor
# before the node gets axor.dev/gvisor=ready.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
VERSION=${GVISOR_VERSION:-20251020.0}
URL="https://storage.googleapis.com/gvisor/releases/release/$VERSION/$(uname -m)"
K="k3s kubectl"
CONF=/var/lib/rancher/k3s/agent/etc/containerd
NODE=$($K get nodes -o jsonpath='{.items[0].metadata.name}')

registered() { k3s crictl info 2>/dev/null | grep -q '"runsc": {'; }  # containerd's live config, not a file

test_pod() {  # 0 when a pod runs under runsc and gVisor answers
  local img name=gvisor-check-$RANDOM out=""
  img=$($K -n axor get deploy web -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SANDBOX_IMAGE")].value}')
  [[ -n $img ]] || { echo "Couldn't find the sandbox image (deploy AXoR first)." >&2; return 1; }
  $K apply -f - >/dev/null <<EOF
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata: { name: gvisor-check }
handler: runsc
EOF
  $K -n axor-sandbox apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata: { name: $name, labels: { app: axor-sandbox } }
spec:
  runtimeClassName: gvisor-check
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext: { runAsNonRoot: true, runAsUser: 1000, seccompProfile: { type: RuntimeDefault } }
  containers:
    - name: check
      image: $img
      imagePullPolicy: Never
      command: ["sh", "-c", "dmesg 2>/dev/null | head -n 3; echo kernel=\$(uname -r); python3 -c 'print(\"python ok\")'"]
      securityContext: { allowPrivilegeEscalation: false, capabilities: { drop: [ALL] } }
EOF
  for _ in $(seq 60); do
    case $($K -n axor-sandbox get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null) in Succeeded|Failed) break ;; esac
    sleep 2
  done
  out=$($K -n axor-sandbox logs "$name" 2>&1 || true)
  $K -n axor-sandbox describe pod "$name" 2>/dev/null | grep -iE "error|fail" | tail -n 3 || true
  $K -n axor-sandbox delete pod "$name" --wait=false >/dev/null 2>&1 || true
  $K delete runtimeclass gvisor-check >/dev/null 2>&1 || true
  echo "$out" | sed 's/^/  | /'
  grep -qE "gVisor|kernel=4\.4\.0$" <<<"$out" && grep -q "python ok" <<<"$out"  # gVisor reports kernel 4.4.0; the host's is newer
}

wait_node() {
  for _ in $(seq 90); do
    $K get node "$NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q True && return 0
    sleep 2
  done
  echo "The node didn't come back Ready after the restart: check 'systemctl status k3s'." >&2; return 1
}

restart_k3s() { echo "== restarting k3s (pods keep running)"; systemctl restart k3s; sleep 5; wait_node; }

case ${1:-} in
  --check)
    command -v runsc >/dev/null && echo "runsc: $(runsc --version 2>/dev/null | head -n 1)" || echo "runsc: not installed"
    registered && echo "containerd: runsc registered" || echo "containerd: runsc not registered"
    echo "node label axor.dev/gvisor: $($K get node "$NODE" -o jsonpath='{.metadata.labels.axor\.dev/gvisor}')"
    if command -v runsc >/dev/null && registered; then
      if test_pod; then echo "test pod: ran under gVisor"; else echo "test pod: did NOT run under gVisor"; fi
    fi
    exit 0 ;;
  --off)
    $K label node "$NODE" axor.dev/gvisor- >/dev/null; echo "Removed the label: AXoR no longer starts sandbox runs with internet."; exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1 (use --check or --off)" >&2; exit 2 ;;
esac

echo "== downloading gVisor $VERSION"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for f in runsc containerd-shim-runsc-v1; do
  curl -fsSL -o "$tmp/$f" "$URL/$f"
  curl -fsSL -o "$tmp/$f.sha512" "$URL/$f.sha512"
done
(cd "$tmp" && sha512sum -c runsc.sha512 containerd-shim-runsc-v1.sha512)
install -m 0755 "$tmp/runsc" "$tmp/containerd-shim-runsc-v1" /usr/local/bin/
echo "installed: $(runsc --version | head -n 1)"

# runsc must use the same cgroup driver as k3s's runc (systemd), or its pods fail on cgroup paths
mkdir -p /etc/containerd
if grep -q "SystemdCgroup = true" "$CONF/config.toml"; then printf '[runsc_config]\n  systemd-cgroup = "true"\n' >/etc/containerd/runsc.toml
else printf '[runsc_config]\n' >/etc/containerd/runsc.toml; fi
BLOCK="[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runsc]
  runtime_type = \"io.containerd.runsc.v1\"
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runsc.options]
  TypeUrl = \"io.containerd.runsc.v1.options\"
  ConfigPath = \"/etc/containerd/runsc.toml\""
if ! registered; then
  tmpl=$CONF/config-v3.toml.tmpl
  if [[ -f $tmpl ]]; then
    grep -q runsc "$tmpl" || { cp -a "$tmpl" "$tmpl.bak-$(date +%s)"; printf '\n%s\n' "$BLOCK" >>"$tmpl"; }
  else
    printf '{{ template "base" . }}\n\n%s\n' "$BLOCK" >"$tmpl"
  fi
  echo "== wrote $tmpl"
  restart_k3s
  registered || { echo "k3s didn't take the runsc runtime: see $CONF/config.toml and 'journalctl -u k3s'." >&2; exit 1; }
fi
echo "== containerd's runtimes now (runc must still be among them):"
k3s crictl info 2>/dev/null | python3 -c 'import json,sys; print(" ".join(sorted(json.load(sys.stdin)["config"]["containerd"]["runtimes"])))' || true
registered && k3s crictl info 2>/dev/null | grep -q '"runc": {' || { echo "runc is missing from containerd's config: check $CONF and 'journalctl -u k3s'." >&2; exit 1; }

echo "== test pod under gVisor"
if test_pod; then
  $K label node "$NODE" axor.dev/gvisor=ready --overwrite >/dev/null
  echo "gVisor works. The node is labelled axor.dev/gvisor=ready: AXoR can start sandbox runs with internet."
else
  echo "The test pod didn't run under gVisor, so the node isn't labelled and runs with internet stay off." >&2; exit 1
fi
