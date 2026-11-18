---
title: DevOps pipelines and Docker
section: admin
order: 5
audience: admin
icon: rocket
summary: Building, testing and deploying Source hub repositories with pipelines, and managing containers on the Docker page.
---
## DevOps pipelines

[DevOps](#devops) builds, tests and deploys Source hub repositories on this server. A **pipeline** is one app:

- a repository and branch, its Dockerfile, and an optional test command
- to deploy it: the container port, the host port (within `RUNNER_PORTS`), a health check path, memory, CPUs, a volume, environment variables and secrets

A **run** downloads the commit, builds the image, runs the tests in a throwaway container, then swaps the app's container and checks its health, **rolling back** if the check fails. Runs start by hand, on new commits (auto deploy), or as a rollback to an earlier run's image.

Every change (pipelines, runs, cancels, rollbacks, starting and stopping apps) needs sudo and is audited. Secrets are stored encrypted and masked in logs. On the DevOps page, **Assist** is the DevOps agent.

### The runner

AXoR itself never gets the Docker socket. A separate **runner** is the only part allowed to build images and create containers, and it sets every container up itself: not privileged, no host paths or host network, capped memory, CPU and processes, on its own network. It only touches containers, images and volumes it labelled `axor.devops`. `RUNNER_MAX_MEMORY_MB`, `RUNNER_MAX_CPUS`, `RUNNER_BUILDS` and `RUNNER_BUILD_MINUTES` cap what a build or app may use.

> [!WARNING]
> The runner holds the Docker socket read-write, which is root on the host if it's ever compromised. Leave it off on servers where you don't need pipelines.

## The Docker page

[Docker](#docker) manages this server's containers and images through a restricted proxy:

- the engine version, running containers, and total CPU and memory in use
- containers with state, image, ports, live CPU and memory, and compose project: view logs (100 to 5,000 lines), start, stop, restart and remove
- images with tags, size and how many containers use each: pull by name, remove an unused image, prune dangling (or all unused) images

### Safeguards

- Every change needs sudo and is written to the audit log.
- AXoR's own container can't be changed from the page; the drive and the proxy can be restarted but not stopped or removed.
- Running containers must be stopped before removal, and images in use can't be removed: nothing is forced.
- The proxy refuses creating or running containers, `exec`, builds, volumes, networks and every other API, so even a compromised AXoR can't start a privileged container through it.

> [!NOTE]
> AXoR itself runs on Kubernetes; the Docker page shows the host's other containers. An administrator can still stop or remove any of them, so keep the proxy off on shared servers.

## Turning them on

On Kubernetes, `k8s/deploy.sh --host` (and the cutover) deploys the runner and the Docker proxy. With Docker Compose, they're the `devops` and `docker` profiles:

```bash
stat -c %g /var/run/docker.sock        # the socket's group id, e.g. 999
echo DOCKER_GID=999 >> .env
docker compose --profile devops --profile docker up -d
```
