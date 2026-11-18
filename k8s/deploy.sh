#!/usr/bin/env bash
# Builds AXoR's images, loads them into k3s and applies k8s/base (run as root on the k3s host; see k8s/install-k3s.sh).
#
#   ./k8s/deploy.sh             build, load and roll out AXoR, Scout Drive, AXoR Push, AXoR DNS and the edge
#   ./k8s/deploy.sh --host      also the DevOps runner and the Docker page's proxy (k8s/host; the cutover adds it)
#   TAG=… ./k8s/deploy.sh --no-build   apply again with images already loaded
#
# k8s/auto-update.sh runs this by itself for each new commit on the branch it follows (see its header).
#
# AXoR's settings come from .env (the file scripts/run.sh reads) as the Secret axor-env; DRIVE_* and PUSH_* settings
# also go to the drive and push server. Shared secrets are made once (axor-secrets, dns-secrets, runner-secret) and
# kept. The edge's ACME settings and AXoR's Ingress are only created when missing: AXoR changes them from the app.
# Nothing here touches the Docker Compose containers or opens a host port; k8s/cutover.sh does that.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo "Run as root (it talks to k3s and Docker)." >&2; exit 1; }
# one deploy at a time: k8s/auto-update.sh holds this lock for its whole pass and tells us so
if [[ ${AXOR_DEPLOY_LOCK:-} != held ]]; then
  exec 9>"${AXOR_DEPLOY_LOCK_FILE:-/run/axor-deploy.lock}"
  flock -n 9 || { echo "== waiting for the deploy that's running (k8s/auto-update.sh or another deploy.sh)"; flock 9; }
fi
K="k3s kubectl"
build=1 host=0
for a in "$@"; do
  case $a in
    --no-build) build=0 ;;
    --host) host=1 ;;
    *) echo "Unknown option: $a (use --host, --no-build)" >&2; exit 2 ;;
  esac
done
export TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo dev)-$(date +%Y%m%d%H%M%S)}"
export PUBLIC_IP="${PUBLIC_IP:-$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')}"
export DOCKER_GID="${DOCKER_GID:-$(stat -c %g /var/run/docker.sock 2>/dev/null || echo 999)}"
render() { envsubst '${TAG} ${PUBLIC_IP} ${DOCKER_GID}' < "$1"; }
rand() { openssl rand -base64 33 | tr -d '\n=+/'; }
has() { $K -n "$1" get "$2" "$3" >/dev/null 2>&1; }
secret() { $K -n "$1" get secret "$2" -o "jsonpath={.data.$3}" | base64 -d; }

$K -n axor-edge get configmap axor-cutover >/dev/null 2>&1 && host=1  # after the cutover the runner and Docker proxy run here too
images=(web:. drive:drive push:push dns:dns sandbox:k8s/sandbox)
(( host )) && images+=(runner:runner)
if (( build )); then
  for i in "${images[@]}"; do
    echo "== building axor/${i%%:*}:$TAG"
    # Docker's containerd store now and then fails to commit a layer while other builds run: one more try
    docker build -q -t "axor/${i%%:*}:$TAG" "${i#*:}" || docker build -q -t "axor/${i%%:*}:$TAG" "${i#*:}"
  done
  echo "== loading the images into k3s"
  docker save $(for i in "${images[@]}"; do echo "axor/${i%%:*}:$TAG"; done) | k3s ctr -n k8s.io images import - >/dev/null
fi

# G5-2 (Owner, 2026-11-11): one web replica, Recreate, until multi-replica board execution is verified (see 30-axor.yaml)
web_spec=$(awk '/name: web, namespace: axor/ {f=1} f && /replicas:/ {r=$2} f && /strategy:/ {print r, $0; exit}' k8s/base/30-axor.yaml)
[[ $web_spec == "1 "*Recreate* ]] || { echo "k8s/base/30-axor.yaml must keep web at replicas: 1 with strategy Recreate (got: $web_spec)" >&2; exit 1; }

render k8s/base/00-namespaces.yaml | $K apply -f -

# ---------- secrets, made once ----------
if ! has axor secret axor-secrets; then
  $K -n axor create secret generic axor-secrets --from-literal=drive="$(rand)" --from-literal=push="$(rand)" \
    --from-literal=dns="$(rand)" --from-literal=runner="$(rand)" >/dev/null
fi
has axor-edge secret dns-secrets ||
  $K -n axor-edge create secret generic dns-secrets --from-literal=api="$(secret axor axor-secrets dns)" --from-literal=acme="$(rand)" >/dev/null
has axor-host secret runner-secret ||
  $K -n axor-host create secret generic runner-secret --from-literal=runner="$(secret axor axor-secrets runner)" >/dev/null
has axor secret hostfiles ||  # AXoR Host files (k8s/host/42-hostfiles.yaml): the web pod and the service share it
  $K -n axor create secret generic hostfiles --from-literal=secret="$(rand)" >/dev/null
has axor secret egress ||  # sandbox internet (k8s/base/57-egress.yaml): the web pod and the egress proxy share it
  $K -n axor create secret generic egress --from-literal=secret="$(rand)" >/dev/null
has axor-egress secret egress ||
  $K -n axor-egress create secret generic egress --from-literal=secret="$(secret axor egress secret)" >/dev/null
has axor-host secret hostfiles ||
  $K -n axor-host create secret generic hostfiles --from-literal=secret="$(secret axor hostfiles secret)" >/dev/null

# ---------- settings from .env ----------
env_file=$(mktemp); trap 'rm -f "$env_file"' EXIT
[[ -f .env ]] && grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env > "$env_file" || true
$K -n axor create secret generic axor-env --from-env-file="$env_file" --dry-run=client -o yaml | $K apply -f - >/dev/null
for svc in axor/drive axor/push axor-host/runner; do  # each service gets its own settings only, never the keys
  name=${svc#*/}
  grep -E "^${name^^}_" "$env_file" | grep -v SECRET > "$env_file.$name" || true
  $K -n "${svc%/*}" create configmap "axor-$name-env" --from-env-file="$env_file.$name" --dry-run=client -o yaml | $K apply -f - >/dev/null
  rm -f "$env_file.$name"
done

# ---------- what AXoR changes itself: only when missing ----------
has axor-edge configmap edge-config ||
  $K -n axor-edge create configmap edge-config --from-literal=ACME_EMAIL= \
    --from-literal=ACME_CA=https://acme-v02.api.letsencrypt.org/directory >/dev/null
has axor-edge secret edge-tls ||
  $K -n axor-edge create secret generic edge-tls --from-literal=tls.yaml='# AXoR writes the edge default certificate here' >/dev/null
# "web" answers any address (e.g. this server's IP); "web-domain" is AXoR's name on the platform domain, which AXoR sets
has axor ingress web || $K apply -f - >/dev/null <<'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: axor
  annotations: { traefik.ingress.kubernetes.io/router.entrypoints: websecure }
spec:
  ingressClassName: axor
  rules:
    - http: { paths: [{ path: /, pathType: Prefix, backend: { service: { name: web, port: { number: 8000 } } } }] }
EOF
has axor ingress web-domain || $K apply -f - >/dev/null <<'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-domain
  namespace: axor
  annotations: { traefik.ingress.kubernetes.io/router.entrypoints: websecure }
spec:
  ingressClassName: axor
  rules:
    - host: axor.internal
      http: { paths: [{ path: /, pathType: Prefix, backend: { service: { name: web, port: { number: 8000 } } } }] }
EOF

for f in k8s/base/[1-9]*.yaml; do render "$f" | $K apply -f -; done
(( host )) && for f in k8s/host/*.yaml; do render "$f" | $K apply -f -; done
has axor-edge configmap axor-cutover && ./k8s/cutover.sh --ports-only  # keep the public ports the cutover opened

echo "== rolling out $TAG"
for d in axor-edge/dns axor-edge/edge axor-egress/egress axor/drive axor/push axor/web $( (( host )) && echo axor-host/runner axor-host/docker-proxy axor-host/hostfiles); do
  $K -n "${d%/*}" rollout status "deploy/${d#*/}" --timeout=300s
done

# keep this tag and the two before it in k3s, for rolling back by hand, and in Docker, where each build leaves one
if (( build )); then
  for name in web drive push dns runner sandbox; do
    k3s ctr -n k8s.io images ls -q | grep "^docker.io/axor/$name:" | sort -t- -k2 | head -n -3 |
      xargs -r k3s ctr -n k8s.io images rm >/dev/null 2>&1 || true
    docker images --format '{{.Repository}}:{{.Tag}}' "axor/$name" | grep -E ':[0-9a-z]+-[0-9]{14}$' | sort -t- -k2 | head -n -3 |
      xargs -r docker rmi >/dev/null 2>&1 || true
  done
fi
if has axor-edge configmap axor-cutover; then echo "AXoR $TAG is running on k3s, at https://$PUBLIC_IP/"
else echo "AXoR $TAG is running on k3s. Edge: $($K -n axor-edge get svc edge -o jsonpath='{.spec.clusterIP}') (cluster only until k8s/cutover.sh)"; fi
