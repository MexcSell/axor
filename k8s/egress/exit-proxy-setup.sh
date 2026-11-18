#!/usr/bin/env bash
# Run this on a SEPARATE small server (a VPS at another provider, Debian or Ubuntu), as root, never on the AXoR host.
# It makes that server the exit address for AXoR's sandbox internet: a squid proxy that only accepts AXoR's server, with a
# password, only to ports 80 and 443 and only to public addresses, keeping no cache. Abuse reports about what sandbox code
# did then land on this server's address, not on AXoR's.
#
#   AXOR_IP=65.108.79.94 ./exit-proxy-setup.sh        # AXoR's public address: the only one allowed in
#
# It prints the URL to give AXoR (see k8s/egress/README.md, "Exit address").
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
: "${AXOR_IP:?Set AXOR_IP to the public address of the AXoR server}"
PORT=${PORT:-3128}
USER_NAME=axor
PASS=$(openssl rand -hex 24)

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq squid apache2-utils >/dev/null
htpasswd -bc /etc/squid/axor.passwd "$USER_NAME" "$PASS" >/dev/null
chown proxy:proxy /etc/squid/axor.passwd; chmod 640 /etc/squid/axor.passwd
[[ -f /etc/squid/squid.conf.orig ]] || cp /etc/squid/squid.conf /etc/squid/squid.conf.orig
helper=$(ls /usr/lib/squid/basic_ncsa_auth /usr/lib/squid3/basic_ncsa_auth 2>/dev/null | head -n 1)

cat >/etc/squid/squid.conf <<EOF
# AXoR sandbox exit proxy (k8s/egress/exit-proxy-setup.sh). The original is squid.conf.orig.
http_port $PORT
auth_param basic program $helper /etc/squid/axor.passwd
auth_param basic realm axor-exit
acl axor_src src $AXOR_IP/32
acl axor_user proxy_auth REQUIRED
acl exit_ports port 80 443
acl to_inside dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 ::1 fc00::/7 fe80::/10
http_access deny !axor_src
http_access deny to_inside
http_access deny !exit_ports
http_access allow axor_src axor_user
http_access deny all
cache deny all
forwarded_for delete
access_log daemon:/var/log/squid/access.log squid
EOF
squid -k parse >/dev/null 2>&1 || { squid -k parse; exit 1; }
systemctl restart squid
systemctl enable squid >/dev/null 2>&1 || true

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow from "$AXOR_IP" to any port "$PORT" proto tcp >/dev/null && echo "ufw: port $PORT open to $AXOR_IP only"
else
  echo "No active ufw: make sure port $PORT is reachable only from $AXOR_IP (the provider's firewall, or ufw)."
fi
echo
echo "Exit proxy ready. Give AXoR this URL (keep it secret):"
echo "  http://$USER_NAME:$PASS@$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):$PORT"
