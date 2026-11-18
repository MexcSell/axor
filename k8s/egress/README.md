# Sandbox internet

Competition teams' sandbox runs have no internet by default. An administrator can turn it on per team
(Competition team → Files & sandbox → **Internet in the sandbox**). Runs of that team then reach the public internet,
with these safeguards:

| Risk | What stops it | Where |
|---|---|---|
| Reaching the cluster, the host's services, cloud metadata | Only the egress proxy is reachable from the pod; the proxy resolves names itself, refuses any non-public address and the server's own IP, then connects to the address it checked; the proxy pod's NetworkPolicy blocks the same ranges again | `56-sandbox.yaml`, `57-egress.yaml`, `backend/app/egress_proxy.py` |
| Leaking data | No API keys or service account token in the pod (the model proxy holds the key); files that look like secrets (.env, keys, credentials) are held back; at most 50 MB sent out per run (then every connection of the run is cut) | `sandbox.py` (`SECRET_PATH`, `SANDBOX_NET_UP_MB`) |
| Abuse from this server's IP | Ports 80 and 443 only (no mail, IRC, scans of other ports); rate limits each way; an optional exit proxy elsewhere, so traffic leaves from another address | `EGRESS_PORTS`, `EGRESS_UP_MBPS`, `EGRESS_DOWN_MBPS`, "Exit address" below |
| Malicious downloads escaping the container | Runs with internet run under gVisor; the pod stays unprivileged, without capabilities, and is deleted after the run | `k8s/install-gvisor.sh`, RuntimeClass `gvisor` |
| Not knowing what happened | Every run lists the hosts it reached, bytes each way and every refusal (run dialog, the team's activity, the agent's tool result); the proxy logs each connection | `kubectl -n axor-egress logs deploy/egress` |

Runs with internet never start without the proxy and gVisor: the team switch stays disabled, and a run on a team that
already has it on fails with the reason.

## Setting it up

1. Deploy (makes the `axor-egress` namespace, the proxy and its secret): `./k8s/redeploy.sh`
2. Install gVisor on the host (restarts k3s; running pods keep running): `./k8s/install-gvisor.sh`.
   `./k8s/install-gvisor.sh --check` says what's there; `--off` takes the node label away, which stops runs with internet.
3. Optional but recommended: an exit address (below).
4. Turn it on for a team.

## Exit address

Without one, sandbox traffic leaves through this server's own address, and the team switch says so. To use another
address:

1. On a small VPS at another provider (Debian/Ubuntu), as root: `AXOR_IP=<this server's public IP> ./exit-proxy-setup.sh`.
   It prints a URL like `http://axor:<password>@<vps-ip>:3128`.
2. On this host:
   ```
   k3s kubectl -n axor-egress create secret generic egress-upstream --from-literal=url='<that URL>'
   k3s kubectl -n axor-egress rollout restart deploy/egress
   ```
   A restart ends the runs with internet that are open at that moment.

The AXoR side still checks every address before asking the exit proxy, and asks it for that exact IP, so the exit
proxy's resolver can't send traffic anywhere else.

## Switching it off

- One team: the team's switch.
- Every team at once, right away: `k3s kubectl -n axor-egress scale deploy/egress --replicas=0` (runs with internet then
  fail to start; `--replicas=1` brings it back). Or `./k8s/install-gvisor.sh --off`.
- For good: `SANDBOX_INTERNET=0` in `.env`, then redeploy.

## Settings (`.env`, for the web pod)

`SANDBOX_NET_UP_MB` (50) and `SANDBOX_NET_DOWN_MB` (5000) per run; `SANDBOX_INTERNET_RUNTIME` (`gvisor`; empty runs them
on runc, which you should only choose knowingly). Proxy-side settings are env values in `57-egress.yaml`.

## What it doesn't cover

- A run can still send out the files it was given, up to the cap. Keep secrets out of team files.
- Code from the internet can be malicious; gVisor and the throwaway pod limit what it can do, they don't make it safe to trust.
- `git@github.com:` (SSH) URLs don't work through an HTTP proxy: use https URLs.
- Non-HTTP protocols (raw TCP, UDP other than DNS) don't get out.
- DNS: sandbox pods can still look up names through cluster DNS, which is a slow channel for leaking data. It was already
  open before this change.
- Files written in the sandbox still aren't kept unless an agent saves them with `file_write`, and the files sent into a run
  are still capped at about 900 KB (downloads inside the run aren't).
