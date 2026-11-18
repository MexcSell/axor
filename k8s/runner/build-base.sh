#!/usr/bin/env bash
# Builds the VM runner's base disk (D-013 design decision D8-f; G5-4 V4.2): a Debian 12 cloud image with Docker Engine, the
# Compose plugin, git, the unprivileged user `job` and AXoR's in-VM runner script (job.py, started once per boot by
# axor-job.service). Built once, pinned by sha256 (base.json), then copied read-only into the runner pod image (build.sh).
#
#   k8s/runner/build-base.sh OUTDIR            needs Docker and /dev/kvm on this host, and the internet (Debian, Docker's apt repository)
#   DEBIAN_IMAGE_SHA256=<hex> ...              refuse any other Debian image than this one (reproducible rebuilds)
#
# It changes nothing outside OUTDIR and creates nothing on any cluster. The build VM runs in a throwaway container.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=${1:?usage: build-base.sh OUTDIR}; mkdir -p "$out"; out=$(cd "$out" && pwd)
url=${DEBIAN_IMAGE_URL:-https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2}
[[ -e /dev/kvm ]] || { echo "This host has no /dev/kvm." >&2; exit 2; }
job_sha=$(sha256sum "$here/job.py" | cut -d' ' -f1)

cat > "$out/user-data" <<EOF
#cloud-config
ssh_pwauth: false
write_files:
  - path: /etc/systemd/system/axor-job.service
    content: |
      [Unit]
      Description=AXoR VM runner: one job, then power off
      After=docker.service network-online.target
      Wants=docker.service network-online.target
      ConditionPathExists=/dev/vdc
      [Service]
      Type=oneshot
      ExecStart=/usr/bin/python3 /opt/axor/job.py
      ExecStopPost=/usr/bin/systemctl poweroff --no-block
      StandardOutput=journal+console
      StandardError=journal+console
      TimeoutStartSec=infinity
      [Install]
      WantedBy=multi-user.target
  - path: /etc/systemd/network/10-axor.network
    content: |
      [Match]
      Name=en* eth*
      [Network]
      DHCP=ipv4
  - path: /root/build.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      set -eE
      out(){ echo "\$*" > /dev/ttyS0; }
      step=start; trap 'out "BASEBUILD FAIL \$step"; poweroff' ERR
      export DEBIAN_FRONTEND=noninteractive
      step=docker-repo
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
      echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list
      step=apt; apt-get update -qq
      apt-get install -y -qq --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git ca-certificates >/var/log/axor-build.log 2>&1
      step=user; useradd -m -s /bin/bash job; usermod -aG docker job
      step=runner; mkdir -p /opt/axor /job; base64 -d /root/job.py.b64 > /opt/axor/job.py; chmod 0755 /opt/axor/job.py; rm /root/job.py.b64
      echo "$job_sha  /opt/axor/job.py" | sha256sum -c - >/dev/null
      step=network; systemctl enable systemd-networkd >/dev/null 2>&1; rm -f /etc/network/interfaces.d/*; : > /etc/network/interfaces
      rm -f /etc/resolv.conf; echo "nameserver 10.0.2.3" > /etc/resolv.conf   # QEMU's user-mode network answers DNS here
      step=facts
      printf '{"built": %s, "debian": "%s", "docker": "%s", "compose": "%s", "runner_script_sha256": "%s"}\n' "\$(date +%s)" "\$(cat /etc/debian_version)" \\
        "\$(docker version --format '{{.Server.Version}}')" "\$(docker compose version --short)" "$job_sha" > /opt/axor/base.json
      step=finish; systemctl enable axor-job.service >/dev/null 2>&1
      touch /etc/cloud/cloud-init.disabled     # later boots are jobs: no cloud-init, no seed
      apt-get clean; rm -rf /var/lib/apt/lists/* /var/log/axor-build.log; journalctl --rotate >/dev/null 2>&1 || true; journalctl --vacuum-time=1s >/dev/null 2>&1 || true
      out "BASEBUILD FACTS \$(cat /opt/axor/base.json)"
      out "BASEBUILD PASS"
      sync; poweroff
  - path: /root/job.py.b64
    content: $(base64 -w0 "$here/job.py")
runcmd:
  - [bash, /root/build.sh]
EOF

cat > "$out/in-container.sh" <<'EOF'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq --no-install-recommends qemu-system-x86 qemu-utils ipxe-qemu cloud-image-utils curl ca-certificates >/dev/null
cd /out
[[ -s debian.qcow2 ]] || curl -fsSL -o debian.qcow2 "$URL"
got=$(sha256sum debian.qcow2 | cut -d' ' -f1)
[[ -z ${WANT:-} || $WANT == "$got" ]] || { echo "Debian image sha256 $got is not the pinned $WANT" >&2; exit 3; }
echo "$got" > debian.sha256
rm -f build.qcow2 serial.log; qemu-img create -q -f qcow2 -F qcow2 -b debian.qcow2 build.qcow2 12G
cloud-localds seed.img user-data
timeout 1500 qemu-system-x86_64 -accel kvm -cpu host -smp 4 -m 4096 -no-reboot -display none -monitor none -serial file:/out/serial.log \
  -drive file=build.qcow2,if=virtio -drive file=seed.img,if=virtio,format=raw -netdev user,id=n0 -device virtio-net-pci,netdev=n0 || true
grep -q "BASEBUILD PASS" serial.log || { grep -o "BASEBUILD FAIL.*" serial.log | head -1 >&2; tail -30 serial.log >&2; exit 4; }
qemu-img convert -O qcow2 build.qcow2 base.qcow2        # flattened: no backing file
grep -o 'BASEBUILD FACTS {.*}' serial.log | head -1 | sed 's/^BASEBUILD FACTS //' > facts.json
rm -f build.qcow2 seed.img
chown "$OWNER" base.qcow2 facts.json debian.sha256 serial.log debian.qcow2
EOF

docker run --rm --device /dev/kvm -v "$out:/out" -e URL="$url" -e WANT="${DEBIAN_IMAGE_SHA256:-}" -e OWNER="$(id -u):$(id -g)" \
  debian:12-slim bash /out/in-container.sh
sha=$(sha256sum "$out/base.qcow2" | cut -d' ' -f1)
python3 - "$out" "$sha" "$url" <<'PY'
import json, sys
out, sha, url = sys.argv[1:]
f = json.load(open(f"{out}/facts.json"))
json.dump({"sha256": sha, "debian_image": url, "debian_image_sha256": open(f"{out}/debian.sha256").read().strip(), **f}, open(f"{out}/base.json", "w"), indent=1)
print(open(f"{out}/base.json").read())
PY
echo "Base disk: $out/base.qcow2 (sha256 $sha)"
