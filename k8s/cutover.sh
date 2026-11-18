#!/usr/bin/env bash
# Moves the live AXoR from Docker Compose (scripts/run.sh) onto k3s and opens its public ports. Run as root:
#
#   ./k8s/cutover.sh              deploy everything (with the DevOps runner and Docker proxy), stop the Compose
#                                 containers, copy their data into the cluster, and open 443 (HTTPS), 53 (AXoR DNS)
#                                 and 8000 (AXoR's old address, now a redirect to HTTPS)
#   ./k8s/cutover.sh --http       also take port 80 (redirects to HTTPS). nginx answers there today; Let's Encrypt
#                                 doesn't need it (DNS-01 and TLS-ALPN-01 work on 53 and 443)
#   ./k8s/cutover.sh --rollback   close the ports, stop AXoR on k3s and start the Compose containers again
#   ./k8s/cutover.sh --ports-only open the ports again (deploy.sh calls it after a redeploy)
#
# The Compose volumes are only read, so --rollback finds them as they were (what was written on k3s since stays there,
# and what the cluster held before is kept under /var/lib/axor/cutover-<time>). DNS is mapped on this server's public
# IPv4 address only, so its own resolver (127.0.0.53) is untouched; the cluster is IPv4-only.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
K="k3s kubectl"
PUBLIC_IP="${PUBLIC_IP:-$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')}"
mode=cutover http=0
for a in "$@"; do
  case $a in
    --http) http=1 ;;
    --rollback) mode=rollback ;;
    --ports-only) mode=ports ;;
    *) echo "Unknown option: $a (use --http, --rollback, --ports-only)" >&2; exit 2 ;;
  esac
done
COMPOSE=(subnet-scout scout-drive scout-push scout-runner scout-docker-proxy)
VOLUMES=(subnet-scout-data:axor/web-data scout-drive-data:axor/drive-data scout-push-data:axor/push-data)
SERVICES=(axor/web axor/drive axor/push axor-host/runner axor-host/docker-proxy)
has() { $K -n "$1" get "$2" "$3" >/dev/null 2>&1; }
scale() { for s in "${SERVICES[@]}"; do has "${s%/*}" deploy "${s#*/}" && $K -n "${s%/*}" scale "deploy/${s#*/}" --replicas="$1" >/dev/null; done; return 0; }

# JSON patches by position: the port lists' order is fixed in 20-edge.yaml (edge: web, websecure, admin, legacy;
# dns: udp, tcp, api)
EDGE_PORTS='/spec/template/spec/containers/0/ports'
ports() {
  local web80=${1:-0} ops
  (( web80 )) || web80=$($K -n axor-edge get configmap axor-cutover -o jsonpath='{.data.http}' 2>/dev/null || echo 0)
  ops='[{"op":"add","path":"'$EDGE_PORTS'/1/hostPort","value":443},{"op":"add","path":"'$EDGE_PORTS'/3/hostPort","value":8000}'
  (( web80 )) && ops+=',{"op":"add","path":"'$EDGE_PORTS'/0/hostPort","value":80}'
  $K -n axor-edge patch deploy edge --type=json -p "$ops]" >/dev/null
  $K -n axor-edge patch deploy dns --type=json -p '[
    {"op":"add","path":"'$EDGE_PORTS'/0/hostPort","value":53},{"op":"add","path":"'$EDGE_PORTS'/0/hostIP","value":"'"$PUBLIC_IP"'"},
    {"op":"add","path":"'$EDGE_PORTS'/1/hostPort","value":53},{"op":"add","path":"'$EDGE_PORTS'/1/hostIP","value":"'"$PUBLIC_IP"'"}]' >/dev/null
  $K -n axor-edge rollout status deploy/edge --timeout=120s >/dev/null
  $K -n axor-edge rollout status deploy/dns --timeout=120s >/dev/null
}
unports() {
  local i
  for i in 0 1 3; do $K -n axor-edge patch deploy edge --type=json -p '[{"op":"remove","path":"'$EDGE_PORTS'/'$i'/hostPort"}]' >/dev/null 2>&1 || true; done
  for i in 0 1; do
    $K -n axor-edge patch deploy dns --type=json -p '[{"op":"remove","path":"'$EDGE_PORTS'/'$i'/hostPort"},{"op":"remove","path":"'$EDGE_PORTS'/'$i'/hostIP"}]' >/dev/null 2>&1 || true
  done
}
pvc_dir() {  # where k3s's local-path provisioner keeps a claim
  local pv; pv=$($K -n "${1%/*}" get pvc "${1#*/}" -o jsonpath='{.spec.volumeName}')
  $K get pv "$pv" -o jsonpath='{.spec.hostPath.path}{.spec.local.path}'
}
check() {  # HTTPS answers, and AXoR DNS does too (REFUSED for a name it doesn't serve: it's no open resolver)
  local code st
  code=$(curl -sk -m 10 -o /dev/null -w '%{http_code}' "https://$PUBLIC_IP/api/health" || true)
  st=$(dig +norec +time=3 +tries=1 @"$PUBLIC_IP" example.com A 2>/dev/null | grep -o 'status: [A-Z]*' || true)
  echo "  https://$PUBLIC_IP/api/health -> ${code:-no answer}"
  echo "  dig @$PUBLIC_IP example.com -> ${st:-no answer}"
}

case $mode in
ports)
  ports; echo "Public ports open: 443, 8000$( [[ $($K -n axor-edge get configmap axor-cutover -o jsonpath='{.data.http}' 2>/dev/null) == 1 ]] && echo ", 80"), 53 on $PUBLIC_IP." ;;

rollback)
  echo "== closing the public ports"; unports
  $K -n axor-edge delete configmap axor-cutover --ignore-not-found >/dev/null
  echo "== stopping AXoR on k3s"; scale 0
  echo "== starting the Docker Compose containers"
  if [[ -x scripts/run.sh ]]; then ./scripts/run.sh
  else docker start "${COMPOSE[@]}"; fi
  echo "Rolled back: AXoR answers on http://$PUBLIC_IP:8000 again. What was written on k3s since the cutover stays in its volumes." ;;

cutover)
  if (( http )) && ss -ltnH 'sport = :80' | grep -q .; then
    echo "Port 80 is in use ($(ss -ltnpH 'sport = :80' | grep -o 'users:(("[^"]*' | head -1 | cut -d'"' -f2)). The cluster's mapping would take it over." >&2
    read -rp "Take port 80 anyway? [y/N] " yes; [[ $yes == [yY]* ]] || exit 1
  fi
  for v in "${VOLUMES[@]}"; do docker volume inspect "${v%%:*}" >/dev/null 2>&1 || { echo "No Docker volume ${v%%:*}: is the Compose AXoR set up?" >&2; exit 1; }; done
  echo "== deploying AXoR on k3s, with the runner and Docker proxy"; ./k8s/deploy.sh --host
  backup=/var/lib/axor/cutover-$(date +%Y%m%d%H%M%S)
  echo "== stopping AXoR on k3s and on Docker Compose"
  scale 0
  for s in "${SERVICES[@]}"; do has "${s%/*}" deploy "${s#*/}" && $K -n "${s%/*}" wait --for=delete pod -l "app=${s#*/}" --timeout=120s >/dev/null 2>&1 || true; done
  docker stop "${COMPOSE[@]}" >/dev/null 2>&1 || true
  echo "== copying the data (the cluster's previous data goes to $backup)"
  for v in "${VOLUMES[@]}"; do
    vol=${v%%:*} claim=${v#*:}
    src=$(docker volume inspect -f '{{.Mountpoint}}' "$vol") dst=$(pvc_dir "$claim")
    mkdir -p "$backup/$claim" && cp -a "$dst/." "$backup/$claim/" && find "$dst" -mindepth 1 -delete
    cp -a "$src/." "$dst/" && chown -R 1000:1000 "$dst"
    echo "  $vol -> $claim ($(du -sh "$dst" | cut -f1))"
  done
  $K -n axor-edge create configmap axor-cutover --from-literal=at="$(date -u +%FT%TZ)" --from-literal=http="$http" \
    --dry-run=client -o yaml | $K apply -f - >/dev/null
  echo "== starting AXoR on k3s and opening the ports"
  scale 1
  for s in "${SERVICES[@]}"; do $K -n "${s%/*}" rollout status "deploy/${s#*/}" --timeout=300s >/dev/null; done
  ports "$http"
  check
  cat <<EOF
AXoR now runs on k3s: https://$PUBLIC_IP/ (and http://$PUBLIC_IP:8000 redirects there).
Until a public domain is set and delegated, browsers warn about the certificate: trust AXoR's root from
Cluster -> Domain & HTTPS, or set your domain there and switch on Let's Encrypt.
Undo with: ./k8s/cutover.sh --rollback
EOF
  ;;
esac
