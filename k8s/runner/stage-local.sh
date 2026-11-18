#!/usr/bin/env bash
# Local staging of the VM runner on one host with Docker and /dev/kvm (D-013 design §7: "one real job on a staging VM, before
# any production use"). No cluster, no AXoR instance: it builds the runner pod image from a built base disk and runs real jobs in
# real VMs through it, with pulls going through a real egress proxy on a network that has no other way out.
#
#   k8s/runner/stage-local.sh BUILD_DIR OUT_DIR JOB_DIR...
#     BUILD_DIR  where build-base.sh left base.qcow2 and base.json
#     OUT_DIR    evidence is written here, one folder per job
#     JOB_DIR    a folder with spec.json (the docker_job fields) and files/ (the job's files)
#   PACKAGE_HOSTS=pypi.org,files.pythonhosted.org   staging's stand-in for the Owner's package-index list (network: build)
#
# What it stands in for: the Kubernetes API (docker run here), the namespace's NetworkPolicy (a Docker network with no route
# out, on which only the egress proxy sits), and the HTTP hand-over of the result (a file here). Everything else is the real
# code: runner.validate / finish / document, the pod image, supervise.py, the base disk and job.py, egress_proxy.py.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); tree=$(cd "$here/../.." && pwd)
build=$(cd "${1:?BUILD_DIR}" && pwd); mkdir -p "${2:?OUT_DIR}"; out=$(cd "$2" && pwd); shift 2
web=axor/web:$(docker images axor/web --format '{{.Tag}}' | head -n1)
base_sha=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$build/base.json")
img=axor-prep/runner:base-${base_sha:0:12}
net=axor-runner-stg-$$; egress=$net-egress; secret=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
cleanup() { docker rm -f "$egress" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== pod image $img"
if ! docker image inspect "$img" >/dev/null 2>&1; then
  ctx=$(mktemp -d); cp "$here/Dockerfile" "$here/supervise.py" "$build/base.json" "$ctx/"; ln "$build/base.qcow2" "$ctx/base.qcow2" 2>/dev/null || cp "$build/base.qcow2" "$ctx/"
  docker build -q -t "$img" "$ctx" >/dev/null; rm -rf "$ctx"
fi
docker image inspect --format '{{.Id}}' "$img" | tee "$out/pod-image-id.txt"

echo "== network without a way out, and the egress proxy on it (this tree's egress_proxy.py)"
docker network create --internal "$net" >/dev/null
# EGRESS_PROXY_FILE: another egress_proxy.py to run instead of this tree's (to check the runner against an older proxy)
docker run -d --name "$egress" --network "$net" -e EGRESS_SECRET="$secret" -v "${EGRESS_PROXY_FILE:-$tree/backend/app/egress_proxy.py}:/egress_proxy.py:ro" \
  --entrypoint python "$web" /egress_proxy.py >/dev/null
docker network connect bridge "$egress"   # the proxy alone also has the way out
sleep 2
eip=$(docker inspect --format "{{(index .NetworkSettings.Networks \"$net\").IPAddress}}" "$egress")
ctl() { docker exec -e S="$secret" "$egress" python -c '
import json, os, sys, urllib.request
m, path, body = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else None)
r = urllib.request.Request("http://127.0.0.1:3129" + path, method=m, data=body.encode() if body else None, headers={"X-Egress-Secret": os.environ["S"], "Content-Type": "application/json"})
print(urllib.request.urlopen(r, timeout=10).read().decode())' "$@"; }

py() { docker run --rm --network none --user 0:0 -v "$tree/backend/app:/app/backend/app:ro" -v "$here/stage_local.py:/stage_local.py:ro" -v "$1:/job" \
         -e RUNNER_BASE_SHA256="$base_sha" -e RUNNER_IMAGE="$img" -e RUNNER_PACKAGE_HOSTS="${PACKAGE_HOSTS:-}" -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app/backend -w /app/backend --entrypoint python "$web" /stage_local.py "$2" /job; }

n=0
for src in "$@"; do
  n=$((n + 1)); name=$(basename "$src"); d="$out/$name"; rm -rf "$d"; mkdir -p "$d/out"; cp -r "$src/spec.json" "$src/files" "$d/"
  echo; echo "== job $n: $name"
  py "$d" prepare || { echo "(not started)"; continue; }
  network=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["job"]["network"])' "$d/prepared.json")
  read -r cpus mem timeout < <(python3 -c 'import json,sys; j=json.load(open(sys.argv[1]))["job"]; print(j["cpus"], j["memory_mb"], j["timeout_s"] + (j["build_timeout_s"] if j.get("dockerfile") or j.get("compose") else 0) + 60)' "$d/prepared.json")
  args=(-e AXOR_NETWORK="$network"); btoken=
  if [[ $network != none ]]; then
    token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    # the product's own request for the run (runner.proxy_run: the registry hosts, https only), with this run's token
    ctl POST /runs "$(python3 -c 'import json,sys; b=json.load(open(sys.argv[1]))["proxy_runs"]["registry"]; b["token"]=sys.argv[2]; print(json.dumps(b))' "$d/prepared.json" "$token")" > "$d/opened.json"
    args+=(-e AXOR_PROXY="http://$token:x@$eip:3128")   # by address: in the cluster it is the proxy's Service name
    btoken=
    if [[ $network == build ]]; then  # D1: a second run, for registry hosts and exactly the approved package indexes; only docker build gets it
      btoken=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
      ctl POST /runs "$(python3 -c 'import json,sys; b=json.load(open(sys.argv[1]))["proxy_runs"]["build"]; b["token"]=sys.argv[2]; print(json.dumps(b))' "$d/prepared.json" "$btoken")" > "$d/build_opened.json"
      args+=(-e AXOR_BUILD_PROXY="http://$btoken:x@$eip:3128")
    fi
    # as Runner.run: a job whose proxy runs weren't confirmed https-only is never started; the runs it opened are closed
    py "$d" confirm || { ctl DELETE "/runs/$token" > "$d/egress.json"; [[ -z ${btoken:-} ]] || ctl DELETE "/runs/$btoken" > "$d/build_egress.json"; echo "(not started)"; continue; }
  fi
  t0=$(date +%s); pod=$net-job-$n
  set +e
  docker run --rm --name "$pod" --network "$net" --device /dev/kvm --cap-drop ALL --security-opt no-new-privileges \
    --cpus "$((cpus + 1))" --memory "$((mem + 1024))m" -v "$d/input:/input:ro" -v "$d/out:/out" \
    -e AXOR_RESULT_FILE=/out/body.json -e AXOR_TIMEOUT="$timeout" -e VM_CPUS="$cpus" -e VM_MEM_MB="$mem" "${args[@]}" "$img" > "$d/pod.log" 2>&1
  rc=$?
  set -e
  echo "{\"exit\": $rc, \"seconds\": $(( $(date +%s) - t0 )), \"name\": \"$pod\"}" > "$d/pod.json"
  cat "$d/pod.log"
  [[ $network == none ]] || ctl DELETE "/runs/$token" > "$d/egress.json"
  [[ -z ${btoken:-} ]] || ctl DELETE "/runs/$btoken" > "$d/build_egress.json"
  py "$d" finish
done
echo; echo "== evidence in $out"
