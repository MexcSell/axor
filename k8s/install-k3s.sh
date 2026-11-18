#!/usr/bin/env bash
# Installs k3s for AXoR on this host (run as root; safe to run again):
#
# - a single-node server with k3s's own Traefik and ServiceLB turned off: AXoR runs its own edge (k8s/base/20-edge.yaml)
#   and only takes ports 443 and 53 when k8s/cutover.sh says so, so nginx and the Docker containers here keep theirs
# - host-gw networking, so there's no VXLAN port anyone on the internet could send pod traffic to
# - Secrets encrypted at rest
# - the API server (6443) and kubelet (10250) closed to everything but this host and its pods, through a small iptables
#   chain (AXOR-K3S) that a systemd drop-in puts back every time k3s starts
# - the image registry AXoR's PaaS builds push to (k8s/base/60-platform.yaml) as a mirror k3s pulls from
#
# Remove it all with /usr/local/bin/k3s-uninstall.sh, then: rm -rf /etc/systemd/system/k3s.service.d/axor-firewall.conf
# /usr/local/lib/axor; iptables -D INPUT -p tcp -m multiport --dports 6443,10250 -j AXOR-K3S; iptables -X AXOR-K3S
# (and the same with ip6tables).
set -euo pipefail
K3S_VERSION="${K3S_VERSION:-v1.36.5+k3s1}"
REGISTRY="${AXOR_REGISTRY:-10.43.200.50:5000}"  # the registry Service's fixed ClusterIP (60-platform.yaml)
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }

mkdir -p /etc/rancher/k3s /usr/local/lib/axor /etc/systemd/system/k3s.service.d
cat > /etc/rancher/k3s/config.yaml <<EOF
# written by AXoR's k8s/install-k3s.sh
write-kubeconfig-mode: "0600"
disable: [traefik, servicelb]
flannel-backend: host-gw
secrets-encryption: true
EOF
cat > /etc/rancher/k3s/registries.yaml <<EOF
# written by AXoR's k8s/install-k3s.sh: PaaS images are pushed to the in-cluster registry over plain HTTP
mirrors:
  "$REGISTRY":
    endpoint: ["http://$REGISTRY"]
EOF

cat > /usr/local/lib/axor/k3s-firewall.sh <<'EOF'
#!/bin/sh
# AXoR: only this host (lo) and pods (10.42.0.0/16) may reach the k3s API server and kubelet.
for ipt in iptables ip6tables; do
  $ipt -N AXOR-K3S 2>/dev/null || $ipt -F AXOR-K3S
  $ipt -A AXOR-K3S -i lo -j RETURN
  [ $ipt = iptables ] && $ipt -A AXOR-K3S -s 10.42.0.0/16 -j RETURN
  $ipt -A AXOR-K3S -j DROP
  $ipt -C INPUT -p tcp -m multiport --dports 6443,10250 -j AXOR-K3S 2>/dev/null ||
    $ipt -I INPUT -p tcp -m multiport --dports 6443,10250 -j AXOR-K3S
done
EOF
chmod 755 /usr/local/lib/axor/k3s-firewall.sh
cat > /etc/systemd/system/k3s.service.d/axor-firewall.conf <<'EOF'
[Service]
ExecStartPre=/usr/local/lib/axor/k3s-firewall.sh
EOF
/usr/local/lib/axor/k3s-firewall.sh

if ! command -v k3s >/dev/null || [[ $(k3s --version | head -1) != *"$K3S_VERSION"* ]]; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - server
else
  systemctl daemon-reload && systemctl restart k3s
fi

printf "Waiting for the node"
for _ in $(seq 1 60); do
  k3s kubectl get nodes 2>/dev/null | grep -q " Ready " && break; printf "."; sleep 2
done
echo; k3s kubectl get nodes -o wide
