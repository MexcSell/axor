# AXoR's VM runner pod image (D-013, G5-4 V4.2): QEMU, the pod-side supervisor and the read-only base disk.
# Built by k8s/runner/build.sh (development only: no push, nothing applied) after build-base.sh made base.qcow2 and base.json;
# it tags the image axor/runner-vm and checks it against this tree. The image named axor/runner is the host runner service, a
# different program. stage-local.sh builds the same image under a staging name for its own runs. The base disk is an image layer: read-only,
# content-addressed by the image digest, never downloaded when a job starts (design decision D8-f).
FROM debian:12-slim
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      qemu-system-x86 qemu-utils ipxe-qemu python3 ca-certificates coreutils && rm -rf /var/lib/apt/lists/*
COPY supervise.py /opt/axor/supervise.py
COPY base.qcow2 base.json /base/
WORKDIR /work
ENTRYPOINT ["python3", "/opt/axor/supervise.py"]
