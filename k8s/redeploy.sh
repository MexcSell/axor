#!/usr/bin/env bash
# Redeploys AXoR from this working tree with checks around k8s/deploy.sh, and rolls back when the deploy doesn't come
# up right. Run as root on the k3s host.
#
#   ./k8s/redeploy.sh                 check, deploy, verify; roll back when the deploy or the verification fails
#   ./k8s/redeploy.sh --check         only the checks before a deploy: production isn't touched
#   ./k8s/redeploy.sh --verify        only the checks after a deploy, against what runs now
#   --host          passed to deploy.sh (the runner and Docker proxy; it adds them by itself after the cutover)
#   --no-rollback   leave a deploy that failed its verification in place
#   --force         deploy even though files changed in the last 2 minutes (another session may be mid-edit)
#   --allow-diverged  deploy a commit that doesn't contain the one production runs (a deliberate downgrade); --force doesn't
#                   imply it. A first install (no web deployment yet, so no tag to read) also needs it.
#
# Before: k3s answers, this commit contains the commit production runs (read from the web image's tag; a build that
# lacks it would silently undo what is live, e.g. a hotfix, PX-B17), no file in the build changed in the last 2 minutes, the Python and JavaScript parse, every asset
# index.html links exists, every image builds, and the new web image boots offline with empty data and answers
# /api/health. web, drive and push use Recreate, so a broken image is downtime until a rollback. The images get
# deploy.sh's tag, so its own builds are cache hits (and miss the containerd flake of builds that overlap).
# After: each deployment deploy.sh tags runs the new tag and is available, /api/health answers through the Service and
# the edge, and the frontend AXoR serves is the one that was built. A failure undoes the deployments that run the new
# tag (settings deploy.sh applied from .env stay). Logs and a history line go to /var/lib/axor/deploys.
# Also before: the unit tests (tests/run-unit.sh) pass on the new web image. Just before deploy.sh: it waits until the running
# AXoR reports no agent loop or model call in flight (/api/health "busy"), up to DRAIN_MAX seconds (600), then deploys anyway
# with a warning; --force skips the wait. --check with TAG set (the auto-updater) builds as TAG and keeps the images.
set -euo pipefail
cd "$(dirname "$0")/.."
K="k3s kubectl"
DIR=${AXOR_DEPLOYS_DIR:-/var/lib/axor/deploys} LOCK=${AXOR_DEPLOY_LOCK_FILE:-/run/axor-deploy.lock}
BUILD=(backend frontend drive push dns runner k8s tests Dockerfile .dockerignore)  # what deploy.sh builds and applies, and the unit tests run on it
mode=deploy host=0 host_flag=() rollback=1 force=0 diverged=0
for a in "$@"; do
  case $a in
    --check) mode=check ;;
    --verify) mode=verify ;;
    --host) host=1 host_flag=(--host) ;;
    --no-rollback) rollback=0 ;;
    --force) force=1 ;;
    --allow-diverged) diverged=1 ;;
    *) echo "Unknown option: $a (use --check, --verify, --host, --no-rollback, --force, --allow-diverged)" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "Run as root (it talks to k3s and Docker)." >&2; exit 1; }
$K -n axor-edge get configmap axor-cutover >/dev/null 2>&1 && host=1  # deploy.sh's rule
PUBLIC_IP="${PUBLIC_IP:-$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')}"

failed=0
ok() { echo "   ok    $*"; }
bad() { echo "   FAIL  $*"; failed=$((failed + 1)); }
warn() { echo "   warn  $*"; }
names() { local n; n=$(wc -l <<<"$1"); echo "$(head -n 12 <<<"$1" | tr '\n' ' ')$( ((n > 12)) && echo "(+$((n - 12)) more)")"; }

deployments() {  # the ones deploy.sh gives the new tag
  echo axor-edge/dns axor/drive axor/push axor/web
  $K -n axor-egress get deploy egress >/dev/null 2>&1 && echo axor-egress/egress  # sandbox internet (k8s/base/57-egress.yaml) runs the web image
  (( host )) && echo axor-host/runner axor-host/hostfiles
  return 0
}
images() {  # the images deploy.sh builds, name:context
  echo web:. drive:drive push:push dns:dns sandbox:k8s/sandbox
  (( host )) && echo runner:runner
  return 0
}
build() {  # name, context, tag; three tries: other builds on this host now and then break containerd's layer commits
  local n out
  for n in 1 2 3; do
    out=$(docker build -q -t "axor/$1:$3" "$2" 2>&1) && return 0
    (( n < 3 )) && sleep 15
  done
  tail -n 2 <<<"$out" | tr '\n' ' '; return 1
}
drop() { local i; for i in $(images); do docker rmi "axor/${i%%:*}:$1" >/dev/null 2>&1 || :; done; }  # a tag's images
web_tag() { local i; i=$($K -n axor get deploy web -o 'jsonpath={.spec.template.spec.containers[0].image}') && echo "${i##*:}"; }
tagged() {  # namespace/name of each deployment that runs an image with this tag
  $K get deploy -A -o 'jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.template.spec.containers[*].image}{"\n"}{end}' |
    awk -v t=":$1" '{ for (i = 2; i <= NF; i++) if (substr($i, length($i) - length(t) + 1) == t) { print $1; next } }'
}
web_ip() { $K -n axor get svc web -o 'jsonpath={.spec.clusterIP}'; }
retry() { local i; for i in $(seq 12); do "$@" && return 0; sleep 5; done; return 1; }
healthy() { local ip; ip=$(web_ip) && retry curl -fsS -m 5 "http://$ip:8000/api/ready" >/dev/null 2>&1; }  # ready: it answers and its database does
edge_up() { [[ $(curl -ksS -o /dev/null -w '%{http_code}' -m 5 "https://$PUBLIC_IP/api/health" 2>/dev/null) == 200 ]]; }
sums() { (cd frontend && sha256sum index.html ./*.js ./*.css); }  # the frontend files the browser loads

# ---------- before ----------
check() {  # tag to build the web image as
  local tag=$1 running sha changed new recent py out js=0 jsbad= asset missing= f i
  echo "== checks before the deploy"
  $K get --raw /readyz >/dev/null 2>&1 && ok "k3s answers" || bad "k3s doesn't answer"
  running=$(web_tag 2>/dev/null || :) sha=${running%-*}
  echo "   production runs ${running:-?}; this deploys $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)" \
    "with $(git status --porcelain -- "${BUILD[@]}" | wc -l) uncommitted files"
  if [[ $sha =~ ^[0-9a-f]{4,40}$ ]] && git rev-parse -q --verify "$sha^{commit}" >/dev/null; then
    changed=$(git diff --name-only "$sha" -- "${BUILD[@]}") new=$(git ls-files --others --exclude-standard -- "${BUILD[@]}")
    if [[ -z $changed$new ]]; then warn "nothing in the build changed since ${sha}: this deploys the same code again"
    else echo "   changed since $sha: $(names "$(printf '%s\n%s' "$changed" "$new" | sed '/^$/d')")"; fi
  fi
  # PX-B17: a build that doesn't contain production's commit drops whatever only production has (wave 10c lacked hotfix 083696d)
  local lost=""
  if [[ ! $sha =~ ^[0-9a-f]{4,40}$ ]]; then lost="can't read production's commit from its tag (${running:-none})"
  elif ! git rev-parse -q --verify "$sha^{commit}" >/dev/null; then lost="production's commit $sha isn't in this repository, so it can't be checked (fetch it)"
  elif ! git merge-base --is-ancestor "$sha" HEAD; then lost="this commit doesn't contain production's $sha: deploying it would undo what only production has"
  fi
  if [[ -z $lost ]]; then ok "this commit contains production's $sha"
  elif (( diverged )); then warn "$lost (--allow-diverged)"
  else bad "$lost (deliberate? --allow-diverged)"; fi
  systemctl is-active --quiet axor-auto-update.timer 2>/dev/null &&
    warn "automatic updates are on: after a deploy by hand they wait until their branch includes this code"

  recent=$(find "${BUILD[@]}" -path backend/var -prune -o -type f -mmin -2 -not -path '*/__pycache__/*' -print 2>/dev/null || :)
  if [[ -z $recent ]]; then ok "no file in the build changed in the last 2 minutes"
  elif (( force )); then warn "changed in the last 2 minutes (--force): $(names "$recent")"
  else bad "changed in the last 2 minutes, maybe mid-edit (wait, or --force): $(names "$recent")"; fi

  mapfile -t py < <(find backend/app frontend drive push dns runner -name '*.py' -not -path '*/__pycache__/*')
  if out=$(python3 - "${py[@]}" 2>&1 <<'EOF'
import ast, sys
bad = 0
for f in sys.argv[1:]:
    try: ast.parse(open(f, encoding="utf-8").read(), f)
    except SyntaxError as e: print(f"{f}:{e.lineno}: {e.msg}"); bad = 1
sys.exit(bad)
EOF
  ); then ok "${#py[@]} Python files parse"; else bad "Python syntax: $(tr '\n' ' ' <<<"$out")"; fi
  for f in frontend/*.js; do
    js=$((js + 1)); out=$(node --check "$f" 2>&1) || jsbad+="${f#frontend/}: $(grep -m1 -E 'Error' <<<"$out") "
  done
  [[ -z $jsbad ]] && ok "$js JavaScript files parse" || bad "JavaScript syntax: $jsbad"
  for asset in $(grep -oE '(src|href)="/static/[^"?#]+' frontend/index.html | sed 's#.*/static/##' | sort -u); do
    [[ -f frontend/$asset ]] || missing+=" $asset"
  done
  [[ -z $missing ]] && ok "every asset index.html links exists" || bad "index.html links missing files:$missing"

  echo "== building the images as $tag (deploy.sh then finds them cached) and booting web offline"
  for i in $(images); do
    out=$(build "${i%%:*}" "${i#*:}" "$tag") || { bad "axor/${i%%:*} doesn't build: $out"; return 0; }
  done
  ok "$(images | wc -w) images build"
  local c="axor-redeploy-check-$$" up=0
  docker rm -f "$c" >/dev/null 2>&1 || :
  docker run -d --network none --name "$c" "axor/web:$tag" >/dev/null || { bad "the new web image doesn't start"; return 0; }
  for i in $(seq 45); do
    docker exec "$c" curl -fsS -m 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && { up=1; break; }
    [[ $(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null) == true ]] || break
    sleep 2
  done
  if (( up )); then ok "the new web image boots and answers /api/health (offline, empty data)"
  else bad "the new web image doesn't answer /api/health; its log ends with:"; docker logs --tail 25 "$c" 2>&1 | sed 's/^/         /'; fi
  docker rm -f "$c" >/dev/null 2>&1 || :
  # the unit tests (tests/unit), run on the image just built, so they test the code that would go live with production's
  # dependencies; a failing test stops the deploy the way AgentForge's failing candidate never replaces the running service
  if [[ -d tests/unit ]]; then
    if out=$(tests/run-unit.sh --image "$tag" 2>&1); then ok "the unit tests pass on the new image ($(grep -oE 'Ran [0-9]+ tests?' <<<"$out" | head -n1))"
    else
      bad "unit tests fail on the new image (tests/run-unit.sh --image $tag):"
      { grep -E '^(FAIL|ERROR):|^[A-Za-z]*Error' <<<"$out" | head -n 12; tail -n 1 <<<"$out"; } | sed 's/^/         /' || :
    fi
  fi
}

busy_now() {  # agent loops and model calls in flight in the running web pod (/api/health's busy); empty when it doesn't say
  local ip; ip=$(web_ip) || return 0
  curl -fsS -m 5 "http://$ip:8000/api/health" 2>/dev/null | python3 -c 'import json, sys; b = json.load(sys.stdin).get("busy"); print("" if b is None else b)' 2>/dev/null || :
}

drain() {  # waits until no agent is mid-task in the running AXoR, up to DRAIN_MAX seconds; true when idle (or it can't tell)
  local max=${DRAIN_MAX:-600} waited=0 b
  b=$(busy_now)
  [[ -z $b ]] && { ok "the running AXoR doesn't report agents at work (an older version): not waiting"; return 0; }
  while (( b > 0 && waited < max )); do
    (( waited == 0 )) && echo "   $b agent loops or model calls are running; waiting for them to finish (up to $((max / 60)) min, --force skips)"
    sleep 15; waited=$((waited + 15)); b=$(busy_now); b=${b:-0}
  done
  if (( b == 0 )); then ok "no agent is mid-task$( ((waited)) && echo " (waited ${waited}s)")"; return 0; fi
  warn "$b agent loops or model calls still running after $((max / 60)) min: the restart cuts them off"; return 1
}

# ---------- after ----------
verify() {  # the tag that should run; the frontend checksums it was built with (or this working tree's)
  local tag=$1 sumfile=${2:-} from="the build" d ns name spec upd avail img restarts ip body tb differ= n=0 sum f
  echo "== checks after the deploy ($tag)"
  for d in $(deployments); do
    ns=${d%/*} name=${d#*/}
    IFS='|' read -r img spec upd avail < <($K -n "$ns" get deploy "$name" \
      -o 'jsonpath={.spec.template.spec.containers[0].image}|{.spec.replicas}|{.status.updatedReplicas}|{.status.availableReplicas}{"\n"}' 2>/dev/null || echo)
    if [[ ${img##*:} != "$tag" ]]; then bad "$d runs ${img:-nothing}, not $tag"; continue; fi
    [[ $upd == "$spec" && $avail == "$spec" ]] && ok "$d runs $tag (${avail}/${spec} available)" ||
      bad "$d: ${avail:-0}/${spec} available, ${upd:-0} updated"
    restarts=$($K -n "$ns" get pods -l "app=$name" -o 'jsonpath={range .items[*]}{.spec.containers[0].image} {.status.containerStatuses[0].restartCount}{"\n"}{end}' |
      awk -v t=":$tag" 'substr($1, length($1) - length(t) + 1) == t { s += $2 } END { print s + 0 }') || :
    (( restarts == 0 )) || warn "$d restarted $restarts times since the deploy"
  done
  ip=$(web_ip 2>/dev/null || :)
  if [[ -n $ip ]] && body=$(retry curl -fsS -m 5 "http://$ip:8000/api/health" 2>/dev/null); then ok "/api/health through the Service: $body"
  else bad "AXoR doesn't answer /api/health through its Service"; fi
  if $K -n axor-edge get configmap axor-cutover >/dev/null 2>&1; then
    retry edge_up && ok "the edge serves AXoR at https://$PUBLIC_IP/" || bad "https://$PUBLIC_IP/api/health doesn't answer 200 through the edge"
  fi
  if [[ -n $ip ]]; then
    [[ -f $sumfile ]] || { sumfile=$(mktemp); sums >"$sumfile"; from="this working tree"; }
    while read -r sum f; do
      n=$((n + 1)); f=${f#./}
      [[ $(curl -fsS -m 5 "http://$ip:8000/static/$f" 2>/dev/null | sha256sum | cut -d' ' -f1) == "$sum" ]] || differ+="$f"$'\n'
    done <"$sumfile"
    [[ -z $differ ]] && ok "AXoR serves the frontend that was built ($n files)" ||
      warn "these files AXoR serves differ from $from (changed since?): $(names "${differ%$'\n'}")"
  fi
  tb=$($K -n axor logs deploy/web --tail=5000 2>/dev/null | grep -c '^Traceback' || :)
  (( tb == 0 )) && ok "no tracebacks in AXoR's log" ||
    warn "$tb tracebacks in AXoR's log, the last: $($K -n axor logs deploy/web --tail=5000 2>/dev/null | grep -E '^[A-Za-z_.]+(Error|Exception)' | tail -n 1 | cut -c1-160)"
}

# ---------- rollback ----------
undo_tag() {  # undo the deployments that run this tag; true when AXoR answers afterwards
  local d list; list=$(tagged "$1")
  [[ -n $list ]] || { echo "== no deployment runs $1: deploy.sh stopped before the rollout"; healthy; return; }
  for d in $list; do echo "== rolling back $d"; $K -n "${d%/*}" rollout undo "deploy/${d#*/}" || :; done
  for d in $list; do $K -n "${d%/*}" rollout status "deploy/${d#*/}" --timeout=300s || :; done
  healthy
}

record() {  # result, note
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -Is)" "$TAG" "$prev" "$1" \
    "$(git rev-parse --abbrev-ref HEAD)@$(git rev-parse --short HEAD) +$(git status --porcelain -- "${BUILD[@]}" | wc -l) uncommitted" "$2" >>"$DIR/history"
  ls -t "$DIR"/*.log 2>/dev/null | tail -n +31 | xargs -r rm -f || :  # the last 30 logs, and their checksums
  ls -t "$DIR"/*.sums 2>/dev/null | tail -n +31 | xargs -r rm -f || :
}

case $mode in
  check)
    # TAG given (k8s/auto-update.sh): build as that tag and keep the images when the checks pass, so deploy.sh finds them
    tag="${TAG:-check-$(git rev-parse --short HEAD)-$$}"
    check "$tag"
    (( failed == 0 )) && [[ -n ${TAG:-} ]] || drop "$tag"
    b=$(busy_now); [[ -n $b ]] && echo "   the running AXoR has $b agent loops or model calls at work now (a deploy waits for them)"
    (( failed == 0 )) && echo "== ready to deploy" || { echo "== $failed checks failed"; exit 1; }
    ;;
  verify)
    tag=$(web_tag) || { echo "Can't read AXoR's deployment from the cluster." >&2; exit 1; }
    verify "$tag" "$DIR/$tag.sums"
    (( failed == 0 )) && echo "== AXoR $tag checks out" || { echo "== $failed checks failed"; exit 1; }
    ;;
  deploy)
    export TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo dev)-$(date +%Y%m%d%H%M%S)}"
    mkdir -p "$DIR"
    exec > >(tee -a "$DIR/$TAG.log") 2>&1
    exec 9>"$LOCK"  # the whole run, not just deploy.sh: k8s/auto-update.sh waits for it
    flock -n 9 || { echo "== waiting for the deploy that's running (k8s/auto-update.sh or another deploy)"; flock 9; }
    export AXOR_DEPLOY_LOCK=held
    prev=$(web_tag 2>/dev/null || echo "?")
    echo "== $(date -Is) redeploying AXoR as $TAG (log: $DIR/$TAG.log)"
    check "$TAG"
    if (( failed )); then
      drop "$TAG"
      echo "== $failed checks failed: nothing was deployed, production still runs $prev"; record not-deployed "$failed checks failed"; exit 1
    fi
    sums >"$DIR/$TAG.sums"
    if (( force )); then echo "== not waiting for agents at work (--force)"; else echo "== waiting for agents mid-task"; drain || :; fi
    echo "== deploying (k8s/deploy.sh ${host_flag[*]:-})"
    if ./k8s/deploy.sh "${host_flag[@]}"; then verify "$TAG" "$DIR/$TAG.sums"; else bad "k8s/deploy.sh failed"; fi
    if (( failed == 0 )); then echo "== $(date -Is) AXoR $TAG is live (it replaced $prev)"; record ok ""; exit 0; fi
    if (( ! rollback )); then
      echo "== $failed checks failed; left in place (--no-rollback). Roll back: k3s kubectl -n NS rollout undo deploy/NAME"
      record failed "$failed checks failed, left in place"; exit 1
    fi
    if undo_tag "$TAG"; then
      echo "== $failed checks failed; rolled back, AXoR runs $(web_tag 2>/dev/null || echo ?) and answers"; record rolled-back "$failed checks failed"; exit 1
    fi
    echo "== $failed checks failed and the rollback didn't bring AXoR back: look at k3s kubectl get pods -A"
    record rollback-failed "$failed checks failed"; exit 2
    ;;
esac
