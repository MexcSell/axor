#!/usr/bin/env bash
# Builds the VM runner's pod image (k8s/runner/Dockerfile: QEMU, supervise.py, the base disk) and proves it matches this tree.
# Development only: it builds and tags on this host. It never pushes, never loads an image into a cluster, and applies nothing.
#
#   k8s/runner/build.sh BUILD_DIR [TAG]     BUILD_DIR: where build-base.sh left base.qcow2 and base.json
#   k8s/runner/build.sh --check IMAGE       only the checks, on an image that exists already
#   IMAGE_REPO=axor-prep/runner-vm …        another repository name (default: axor/runner-vm)
#
# The image is NOT axor/runner: that name is the host runner service (runner/, port 8200), a different program.
# It fails, and leaves no tag behind, unless all of these hold:
#   - base.qcow2's sha256 is the one base.json records;
#   - the job script baked into the base disk (base.json: runner_script_sha256) is this tree's k8s/runner/job.py;
#   - the image's /opt/axor/supervise.py is this tree's k8s/runner/supervise.py, and its /base/base.json is BUILD_DIR's.
# A job on any other base disk, or under any other supervisor, isn't this tree's runner, and its result isn't evidence.
# At the end it prints the two settings the web deployment needs (RUNNER_IMAGE, RUNNER_BASE_SHA256). No manifest sets them
# today: without them AXoR says the runner isn't installed, whatever is applied on the cluster.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=${IMAGE_REPO:-axor/runner-vm}
sha() { sha256sum "$1" | cut -d' ' -f1; }
field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$1" "$2"; }
sup=$(sha "$here/supervise.py"); job=$(sha "$here/job.py")

check() {  # check IMAGE [BASE_JSON]: the image holds this tree's supervisor and a base disk built from this tree's job script
  local img=$1 want=${2:-} got bj bad=0
  got=$(docker run --rm --network none --entrypoint sha256sum "$img" /opt/axor/supervise.py 2>/dev/null | cut -d' ' -f1 || true)
  bj=$(docker run --rm --network none --entrypoint cat "$img" /base/base.json 2>/dev/null || true)
  [[ -n $got && -n $bj ]] || { echo "FAIL: $img holds no /opt/axor/supervise.py or no /base/base.json: it isn't a VM runner pod image" >&2; return 1; }
  [[ $got == "$sup" ]] || { echo "FAIL: the image's supervise.py is ${got:0:12}, this tree's is ${sup:0:12}" >&2; bad=1; }
  local bjob bsha; bjob=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("runner_script_sha256",""))' "$bj"); bsha=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("sha256",""))' "$bj")
  [[ $bjob == "$job" ]] || { echo "FAIL: the image's base disk was built with job script ${bjob:0:12}, this tree's job.py is ${job:0:12}" >&2; bad=1; }
  [[ -z $want || $bsha == "$(field "$want" sha256)" ]] || { echo "FAIL: the image's base disk is ${bsha:0:12}, BUILD_DIR's is $(field "$want" sha256 | cut -c1-12)" >&2; bad=1; }
  ((bad)) && return 1
  echo "OK: $img matches this tree (supervise.py ${sup:0:12}, job.py ${job:0:12}, base disk ${bsha:0:12})"
  echo "image id: $(docker image inspect --format '{{.Id}}' "$img")"
  echo "RUNNER_IMAGE=$img"; echo "RUNNER_BASE_SHA256=$bsha"
}

if [[ ${1:-} == --check ]]; then check "${2:?build.sh --check IMAGE}"; exit; fi
build=$(cd "${1:?build.sh BUILD_DIR [TAG]   (or: build.sh --check IMAGE)}" && pwd)
[[ -s $build/base.qcow2 && -s $build/base.json ]] || { echo "No base.qcow2 and base.json in $build: run build-base.sh first" >&2; exit 2; }
base=$(field "$build/base.json" sha256)
[[ $(field "$build/base.json" runner_script_sha256) == "$job" ]] || {
  echo "FAIL: the base disk in $build was built with job script $(field "$build/base.json" runner_script_sha256 | cut -c1-12), this tree's job.py is ${job:0:12}. Rebuild the base disk (build-base.sh)." >&2; exit 1; }
echo "== hashing the base disk"
[[ $(sha "$build/base.qcow2") == "$base" ]] || { echo "FAIL: base.qcow2 isn't the disk base.json records (${base:0:12})" >&2; exit 1; }
tag=${2:-base-${base:0:12}-sup-${sup:0:8}}
img=$repo:$tag
echo "== building $img"
ctx=$(mktemp -d); trap 'rm -rf "$ctx"' EXIT
cp "$here/Dockerfile" "$here/supervise.py" "$build/base.json" "$ctx/"; ln "$build/base.qcow2" "$ctx/base.qcow2" 2>/dev/null || cp "$build/base.qcow2" "$ctx/"
docker build -q -t "$img" "$ctx" >/dev/null
check "$img" "$build/base.json" || { docker rmi "$img" >/dev/null 2>&1 || true; echo "The image was removed: it doesn't match this tree." >&2; exit 1; }
echo "Built and tagged on this host only. Nothing was pushed, loaded into a cluster or applied."
