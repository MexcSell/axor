---
title: The platform: cluster, apps, functions, machines and DNS
section: admin
order: 4
audience: admin
icon: layers
summary: AXoR on Kubernetes, its domain and HTTPS, running apps, functions and virtual machines, AXoR DNS, and the security model.
---
On Kubernetes (k3s, single node), AXoR serves everything over HTTPS through its own edge, answers DNS for its own zones, and gives administrators its pages under **Infrastructure** (System, Cluster, Machines, DNS) and **Developer** (Docker, DevOps, Connectors, Apps, Functions) in the sidebar. Each of those pages opens with tabs for its group, with a dot for whether that page's service is set up. Reads need an admin session; changes need sudo and are audited (`cluster.*`, `update.*`, `app.*`, `function.*`, `machine.*`, `dns.*`, `platform.*`).

## Cluster

[Cluster](#cluster) shows the node's CPU, memory and pods; each AXoR namespace with its deployments (ready, image, restarts, CPU, memory; restart, stop and start, logs) and pods (logs, also from before the last restart; recycle); and recent warnings.

### Domain and HTTPS

- Until you set a domain, the platform uses `axor.internal`, which only AXoR DNS answers for.
- AXoR answers at the domain, apps at `*.apps.<domain>` and functions at `*.fn.<domain>`. AXoR keeps those records in AXoR DNS itself (marked *Platform* on the DNS page).
- AXoR's own certificate authority signs the edge's certificate. It's **name-constrained** to the platform domain, so trusting its root (download it here) can't let anyone impersonate other sites.
- With a public domain delegated to AXoR (name servers `ns1.<domain>` and `ns2.<domain>`, with glue records pointing at the server), switch on **Let's Encrypt**: one certificate for the domain, `*.apps` and `*.fn` over DNS-01, and one per custom domain.

### Updates

AXoR can update itself from GitHub. Once the updater is installed on the server (`sudo ./k8s/auto-update.sh --install`), each new commit on `main` goes live within a few minutes:

- Before it rolls anything out, each update boots the new version offline and runs the unit tests on it. If they fail, nothing is deployed and the update shows as **Checks failed**. Then it waits for agents that are mid-task to finish, up to 10 minutes, so a restart doesn't cut them off.
- Each update builds AXoR from a clean copy of the branch, rolls it out and checks that AXoR answers. If any step fails, the version before comes back, and that commit isn't tried again until a newer one lands. AXoR runs one pod, so it's unavailable for a few seconds while it restarts. This page reconnects by itself.
- It only moves forward. If someone deploys other work by hand, updates wait until `main` includes that work, for example after a merge.
- The **Updates** tab shows the running and newest commits, the commits waiting, the recent updates and the last log (live while an update runs).
- **Check now** fetches the branch right away. **Update now** deploys the newest commit even while paused, or after it failed. **Deploy main anyway** appears when production runs a commit `main` doesn't contain, and replaces it with `main`. The switch pauses or resumes automatic updates.
- The updater picks a request up within a minute. Updating and pausing need sudo and are audited (`update.*`).
- The branch and other settings live on the server, in `/etc/axor/auto-update.env`.

## Apps

[Apps](#apps) runs any container image with HTTPS at `https://<app>.apps.<domain>/`: custom domains, replicas or CPU autoscaling, CPU and memory limits, environment variables and secrets, a health check, a command and a persistent volume. Tabs: **Overview** (status, pods, events), **Test** (a request from inside the cluster), **Logs** and **Revisions** (roll back).

## Functions

[Functions](#functions) runs a Python 3.12 or Node.js 22 handler you write in the page at `https://<fn>.fn.<domain>/`, with packages installed at start, environment and secrets, a timeout, and replicas or autoscaling. Tabs: **Code** (edit and deploy), **Invoke**, **Logs**, **Revisions** and **Stats** (calls, errors, median and 95th-percentile duration, calls per minute).

Every deploy of an app or function is a **revision**; rolling back restores the image, code and environment together, and the last 10 are kept. Deploys roll without downtime, except for apps with a volume.

## Machines

[Machines](#machines) runs Linux and Windows virtual machines on the server's KVM.

- **Linux:** Ubuntu (Desktop or Server), Debian, Fedora, CentOS Stream, Rocky, AlmaLinux, openSUSE, Arch, Alpine, Kali, Mint, Manjaro, NixOS, or any ISO or disk image by URL. The installer downloads at first start; install from the **Console** as on a new PC. Arch comes ready-made (`arch` / `arch`).
- **Windows:** 11, 11 LTSC, 10, Server 2025, 2022 and 2019, downloaded from Microsoft and installed unattended with the account, password and language you set (10 to 20 minutes after the download). They run unactivated, or as a 180-day evaluation for Server: activate them with your own licence.
- Set CPU cores, memory and a disk that outlives restarts. Editing CPU or memory restarts the machine; the system, disk and Windows account are fixed when it's made.
- The **Console** is the machine's screen in the page, with Ctrl+Alt+Del, fit or 100% and full screen. Opening it needs sudo and is audited. At most 8 machines run at a time.

## DNS

[DNS](#dns) manages AXoR DNS's zones and records (A, AAAA, CNAME, MX, TXT, NS, SRV, CAA and wildcards), zone settings, BIND import and export, a query tool that answers like `dig`, a delegation check against public resolvers, and query statistics.

AXoR DNS answers only for its own zones: no recursion (it isn't an open resolver), zone transfers refused, UDP answers truncated and rate-limited per client network (`DNS_RATE`, 50 a second) so it can't amplify floods.

## The security model

- **AXoR's own Kubernetes account** can read its namespaces and `kube-system`, restart and scale deployments, and recycle pods. It can create workloads only in `axor-apps`, `axor-functions` and `axor-machines`. An admission policy makes sure that in AXoR's own namespaces a change is a restart or a scale and nothing else, so even a compromised AXoR can't change what its services run.
- **Workloads** are held to CPU and memory limits, get no Kubernetes API token, and mount only their own config, secrets, scratch space and volume. Pod Security is `baseline` for apps and machines and `restricted` for functions and AXoR itself.
- **Network policies:** apps and functions are reachable only from the edge, from AXoR and from their own namespace. They reach the internet, cluster DNS and the edge, but not AXoR, this host, the Kubernetes API or any private range. A machine's screen answers only AXoR's console relay.
- **The cluster's API** (6443) and kubelet (10250) answer only this host and its pods.
