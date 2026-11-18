#!/usr/bin/env bash
# Keeps AXoR up to date: deploys each new commit on a branch of its GitHub repository (main by default) with
# k8s/deploy.sh, and rolls back when the rollout or the health check fails. Run as root on the k3s host.
#
#   ./k8s/auto-update.sh --install [--branch main]   a clean checkout and a systemd timer that runs a pass every minute
#   ./k8s/auto-update.sh --uninstall                 remove the timer (the checkout and logs stay in /var/lib/axor/update)
#   ./k8s/auto-update.sh --status                    what the last pass saw, and the last updates
#   ./k8s/auto-update.sh [--dry-run]                 one pass, as the timer runs it (--dry-run: check, never deploy)
#
# It only moves forward: it deploys the branch's newest commit when the running one is in its history. After a deploy
# by hand of other work (a working tree, another branch) it waits until the branch includes that work. A commit that
# failed isn't tried again until a newer one lands or someone asks. It builds from its own clean checkout, never a
# working tree, with the settings in ENV_FILE (the .env deploy.sh reads), and holds deploy.sh's lock, so a deploy by
# hand waits for it and it skips a pass while one runs.
# The Cluster page's Updates tab shows what it reports (ConfigMap axor/axor-update-status) and writes only requests
# (ConfigMap axor/axor-update): pause, check now, update now, or deploy the branch even though it doesn't contain the
# running commit. /etc/axor/auto-update.env holds BRANCH, ENV_FILE and CHECK_EVERY (seconds between fetches, 180).
set -euo pipefail
K="k3s kubectl"
STATE=${AXOR_UPDATE_DIR:-/var/lib/axor/update} CONF=${AXOR_UPDATE_CONF:-/etc/axor/auto-update.env}
SRC=$STATE/src LOGS=$STATE/logs LOCK=${AXOR_DEPLOY_LOCK_FILE:-/run/axor-deploy.lock} UNIT=axor-auto-update
BRANCH=main ENV_FILE= CHECK_EVERY=180

now() { date +%s; }
get() { cat "$STATE/$1" 2>/dev/null || true; }
clean() { tr '\t\n\r' '   ' <<<"$1" | cut -c1-300; }  # one TSV field

# ---------- the cluster (a test harness replaces these) ----------
web_tag() { local i; i=$($K -n axor get deploy web -o 'jsonpath={.spec.template.spec.containers[0].image}') && echo "${i##*:}"; }
settings() { $K -n axor get configmap axor-update -o 'jsonpath={.data.paused}{"\n"}{.data.request}{"\n"}' 2>/dev/null || printf '\n\n'; }
ensure_settings() {
  $K -n axor get configmap axor-update >/dev/null 2>&1 ||
    $K -n axor create configmap axor-update --from-literal=paused= --from-literal=request= >/dev/null
}
publish_dir() {  # the status, one key per file
  $K -n axor create configmap axor-update-status --from-file="$1" --dry-run=client -o yaml |
    $K apply --server-side --force-conflicts --field-manager=axor-updater -f - >/dev/null
}
tagged() {  # namespace/name of each deployment that runs an image with this tag
  $K get deploy -A -o 'jsonpath={range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.template.spec.containers[*].image}{"\n"}{end}' |
    awk -v t=":$1" '{ for (i = 2; i <= NF; i++) if (substr($i, length($i) - length(t) + 1) == t) { print $1; next } }'
}
undo() { $K -n "${1%/*}" rollout undo "deploy/${1#*/}"; }
healthy() {  # AXoR answers through its Service (the host reaches ClusterIPs)
  local ip i; ip=$($K -n axor get svc web -o 'jsonpath={.spec.clusterIP}') || return 1
  for i in $(seq 12); do curl -fsS -m 5 "http://$ip:8000/api/health" >/dev/null 2>&1 && return 0; sleep 5; done
  return 1
}
run_deploy() { (cd "$SRC" && ./k8s/deploy.sh "$@"); }

busy_now() {  # agent loops and model calls in flight in the running web pod (/api/health's busy); empty when it doesn't say
  local ip; ip=$($K -n axor get svc web -o 'jsonpath={.spec.clusterIP}' 2>/dev/null) || return 0
  curl -fsS -m 5 "http://$ip:8000/api/health" 2>/dev/null | python3 -c 'import json, sys; b = json.load(sys.stdin).get("busy"); print("" if b is None else b)' 2>/dev/null || :
}

# Before deploy.sh, the way AgentForge's supervisor swaps in a new version: the commit's own checks (k8s/redeploy.sh --check:
# syntax, images build, the new web image boots offline, the unit tests pass on it), built as the deploy's tag so deploy.sh
# finds the images cached; then wait until no agent is mid-task in the running AXoR, up to DRAIN_MAX seconds (600, inside
# the pass's 45 minutes), and deploy anyway after that. A commit without the checks (older than them) deploys as before.
pre_deploy() {  # new tag
  if [[ -x $SRC/k8s/redeploy.sh ]] && grep -q 'tests/run-unit.sh' "$SRC/k8s/redeploy.sh"; then
    echo checking >"$STATE/activity"
    echo "== $(date -Is) checks before the deploy (k8s/redeploy.sh --check)"
    # --force: a fresh checkout's files are all new, which the "changed in the last 2 minutes" check would refuse
    (cd "$SRC" && TAG=$1 ./k8s/redeploy.sh --check --force) || { echo "== the checks failed: not deploying"; return 1; }
  fi
  local max=${DRAIN_MAX:-600} waited=0 b; b=$(busy_now)
  if [[ -n $b ]] && (( b > 0 )); then
    echo waiting >"$STATE/activity"
    echo "== $(date -Is) $b agent loops or model calls are running in AXoR: waiting for them (up to $((max / 60)) min)"
    while (( b > 0 && waited < max )); do sleep 15; waited=$((waited + 15)); b=$(busy_now); b=${b:-0}; done
    (( b == 0 )) && echo "== no agent is mid-task (waited ${waited}s)" || echo "== $b still running after $((max / 60)) min: deploying anyway"
  fi
  echo updating >"$STATE/activity"
}

# ---------- one pass ----------
publish() {  # state of the pass, from the variables pass() sets and the files in $STATE
  local d; d=$(mktemp -d)
  printf %s "$BRANCH" >"$d/branch"; printf %s "$(git -C "$SRC" remote get-url origin 2>/dev/null | grep -i github | sed -E 's#^.*[:/]([^/]+/[^/]+)$#\1#; s#\.git$##')" >"$d/repo"
  local a; a=$(get activity); printf %s "${a:-idle}" >"$d/activity"; printf %s "$rel" >"$d/relation"; printf %s "$error" >"$d/error"
  printf %s "$tag" >"$d/running_tag"; printf %s "$running" >"$d/running"; printf %s "$latest" >"$d/latest"
  local fmt='%H%x09%ct%x09%an%x09%s'
  { [[ -n $running ]] && git -C "$SRC" log -1 --format="$fmt" "$running"; } >"$d/running_commit" 2>/dev/null || true
  { [[ -n $latest ]] && git -C "$SRC" log -1 --format="$fmt" "$latest"; } >"$d/latest_commit" 2>/dev/null || true
  if [[ -n $running && -n $latest && $running != "$latest" ]]; then
    git -C "$SRC" log --format="$fmt" -50 "$running..$latest" >"$d/pending" 2>/dev/null || :
    git -C "$SRC" rev-list --count "$running..$latest" >"$d/pending_count" 2>/dev/null || :
    git -C "$SRC" rev-list --count "$latest..$running" >"$d/ahead_count" 2>/dev/null || :
  fi
  printf %s "$paused" >"$d/paused"; printf %s "$(now)" >"$d/checked"; printf %s "$CHECK_EVERY" >"$d/check_every"
  for f in fetched handled failed target started history; do printf %s "$(get "$f")" >"$d/$f"; done
  local last; last=$(ls -t "$LOGS" 2>/dev/null | head -1 || :)
  # valid UTF-8 only: kubectl would put anything else in binaryData
  { [[ -n $last ]] && tail -n 150 "$LOGS/$last" | tail -c 12000 | iconv -c -f UTF-8 -t UTF-8; } >"$d/log" 2>/dev/null || :
  publish_dir "$d"; rm -rf "$d"
}

relate() {  # how the running commit stands to the branch
  if [[ -z $latest || -z $tag ]]; then rel=
  elif [[ -z $running ]]; then rel=unknown                                          # built from a commit GitHub doesn't have
  elif [[ $running == "$latest" ]]; then rel=current
  elif git -C "$SRC" merge-base --is-ancestor "$running" "$latest"; then rel=behind
  elif git -C "$SRC" merge-base --is-ancestor "$latest" "$running"; then rel=ahead  # deployed by hand from newer work
  else rel=diverged; fi
}

record() {  # started finished sha result by note
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$(clean "$6")" >>"$STATE/history"
  tail -n 20 "$STATE/history" >"$STATE/history.tmp" && mv "$STATE/history.tmp" "$STATE/history"
}

deploy() {  # target sha, who asked (auto, or update/force by an admin)
  local target=$1 by=$2 prev_sha=$running prev_tag=$tag started; started=$(now)
  local new_tag log result=ok note
  new_tag="$(git -C "$SRC" rev-parse --short "$target")-$(date +%Y%m%d%H%M%S)"
  log="$LOGS/$(date +%Y%m%d-%H%M%S)-${target:0:7}.log"
  echo "$target" >"$STATE/target"; echo "$started" >"$STATE/started"; echo updating >"$STATE/activity"; : >"$log"
  publish
  # the Updates tab follows the log while it builds; stopped, it ends the publish it's in first
  ( exec 9>&-; trap 'exit 0' TERM; while :; do sleep 15 & wait $!; publish || :; done ) & local live=$!
  trap 'kill $live 2>/dev/null || :' EXIT
  {
    echo "== $(date -Is) updating to ${target:0:12} (${by}); production runs $prev_tag"
    git -C "$SRC" log -1 --format='   %s (%an)' "$target"
    git -C "$SRC" checkout -q --force --detach "$target" && git -C "$SRC" clean -qfd && ln -sfn "$ENV_FILE" "$SRC/.env" &&
      { pre_deploy "$new_tag" || { result=blocked; false; }; } &&
      TAG=$new_tag run_deploy
  } >"$log" 2>&1 || { [[ $result == blocked ]] || { result=failed; note="The deploy failed"; }; }
  if [[ $result == blocked ]]; then  # nothing was deployed: production still runs prev_tag, so there's nothing to roll back
    note="The checks before the deploy failed (see the log); production still runs $prev_tag"
    echo "$target" >"$STATE/failed"
    docker images "axor/*" --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep ":$new_tag\$" | xargs -r docker rmi >/dev/null 2>&1 || :
  elif [[ $result == ok ]]; then
    if [[ $(web_tag) != "$new_tag" ]]; then result=failed; note="AXoR doesn't run $new_tag after the deploy"
    elif ! healthy; then result=failed; note="AXoR's health check failed after the deploy"; fi
    [[ $result == ok ]] || echo "== $note" >>"$log"
  fi
  if [[ $result == failed ]]; then
    echo "$target" >"$STATE/failed"
    echo rolling-back >"$STATE/activity"
    if rollback "$prev_sha" "$prev_tag" "$new_tag" >>"$log" 2>&1; then result=rolled-back; note+="; rolled back to $prev_tag"
    else result=rollback-failed; note+="; the rollback to $prev_tag failed too"; fi
  elif [[ $result == ok ]]; then
    rm -f "$STATE/failed"; note="Now running $new_tag"
    # the next pass runs the updater this commit came with (mv: a running copy keeps its own file)
    if [[ -f $SRC/k8s/auto-update.sh ]]; then install -m 0755 "$SRC/k8s/auto-update.sh" "$STATE/auto-update.sh.new" && mv "$STATE/auto-update.sh.new" "$STATE/auto-update.sh"; fi
  fi
  kill $live 2>/dev/null || :; wait $live 2>/dev/null || :; trap - EXIT
  echo "== $(date -Is) $result: $note" >>"$log"
  record "$started" "$(now)" "$target" "$result" "$by" "$note"
  rm -f "$STATE/target" "$STATE/started" "$STATE/activity"
  ls -t "$LOGS" | tail -n +31 | sed "s#^#$LOGS/#" | xargs -r rm -f  # keep the last 30 logs
  tag=$(web_tag || echo "$prev_tag"); running=$(resolve "$tag"); relate
}

rollback() {  # previous sha (may be unknown), previous tag, the tag that failed
  echo "== $(date -Is) rolling back to $2"
  # a build that failed changed nothing, and applying the earlier commit again is harmless, so always roll back
  if [[ -n $1 ]] && git -C "$SRC" checkout -q --force --detach "$1"; then
    # the earlier commit's manifests with its images, which k3s still holds (deploy.sh keeps the last three tags)
    TAG=$2 run_deploy --no-build && healthy && return 0
    echo "== redeploying ${1:0:12} failed; undoing the deployments that run $3"
  fi
  local d ok=0
  for d in $(tagged "$3"); do undo "$d" || ok=1; done
  (( ok == 0 )) && healthy
}

resolve() {  # the commit a tag was built from, if GitHub has it
  local s=${1%-*}
  [[ $s =~ ^[0-9a-f]{4,40}$ ]] && git -C "$SRC" rev-parse -q --verify "$s^{commit}" 2>/dev/null || true
}

pass() {
  local dry=$1 req kind= id= by=
  exec 9>"$LOCK"
  flock -n 9 || { echo "A deploy is running; the next pass checks again."; return 0; }
  export AXOR_DEPLOY_LOCK=held  # deploy.sh: this pass holds the lock
  [[ -d $SRC/.git ]] || { echo "No checkout in $SRC: run ./k8s/auto-update.sh --install" >&2; return 1; }
  rel= error= tag= running= latest= paused=
  if (( ! dry )) && [[ -n $(get target) ]]; then  # the last pass stopped mid-update (a reboot, its 45-minute limit)
    # not tried again by itself, so an update that always times out doesn't loop: Update now retries it
    get target >"$STATE/failed"
    record "$(get started)" "$(now)" "$(get target)" interrupted "" "The updater stopped during this update; it isn't retried by itself"
    rm -f "$STATE/target" "$STATE/started" "$STATE/activity"
  fi
  (( dry )) || ensure_settings
  { read -r paused; read -r req; } < <(settings) || :
  [[ $paused == true ]] || paused=
  if [[ $req =~ ^([0-9a-f]{8,32})\ (check|update|force)(\ ([A-Za-z0-9._@-]{1,64}))?$ && ${BASH_REMATCH[1]} != "$(get handled)" ]]; then
    id=${BASH_REMATCH[1]} kind=${BASH_REMATCH[2]} by=${BASH_REMATCH[4]:-admin}
  fi
  local fetched; fetched=$(get fetched)
  if [[ -n $id ]] || (( $(now) - ${fetched:-0} >= CHECK_EVERY )); then
    local out
    if out=$(timeout 120 git -C "$SRC" fetch --prune --quiet origin 2>&1); then now >"$STATE/fetched"
    else error="Can't fetch from GitHub: $(clean "${out##*$'\n'}")"; fi
  fi
  latest=$(git -C "$SRC" rev-parse -q --verify "refs/remotes/origin/$BRANCH^{commit}" 2>/dev/null || true)
  [[ -n $latest ]] || error="The repository has no branch $BRANCH"
  if ! tag=$(web_tag); then error="Can't read AXoR's deployment from the cluster"; tag=; fi
  running=$(resolve "$tag"); relate

  local act=
  case $kind in
    update) [[ $rel == behind ]] && act=$kind ;;
    force) [[ -n $latest && -n $tag && $rel != current ]] && act=$kind ;;
  esac
  [[ -z $act && -z $paused && $rel == behind && $latest != "$(get failed)" ]] && act=auto
  echo "$BRANCH ${latest:0:12}, production ${tag:-?} (${rel:-unknown}): ${act:-nothing to do}${error:+ — $error}${paused:+ (paused)}"
  (( dry )) && return 0
  [[ -n $id ]] && echo "$id" >"$STATE/handled"
  [[ -n $kind && -z $act && $kind != check ]] && record "$(now)" "$(now)" "$latest" skipped "$kind${by:+ by $by}" \
    "$([[ $rel == current ]] && echo "Already up to date" || echo "Nothing to update: production isn't behind $BRANCH")"
  if [[ $act == auto ]]; then deploy "$latest" auto
  elif [[ -n $act ]]; then deploy "$latest" "$act by $by"; fi
  publish
}

# ---------- install ----------
install_timer() {
  local branch=$1 here; here=$(cd "$(dirname "$0")/.." && pwd)
  mkdir -p "$STATE" "$LOGS" "$(dirname "$CONF")"
  [[ -f $CONF ]] || printf 'BRANCH=%s\nENV_FILE=%s\nCHECK_EVERY=180\n' "${branch:-main}" "$here/.env" >"$CONF"
  [[ -n $branch ]] && sed -i "s#^BRANCH=.*#BRANCH=$branch#" "$CONF"
  if [[ ! -d $SRC/.git ]]; then
    echo "== cloning $(git -C "$here" remote get-url origin) into $SRC"
    git clone -q "$(git -C "$here" remote get-url origin)" "$SRC"
  fi
  install -m 0755 "$here/k8s/auto-update.sh" "$STATE/auto-update.sh"
  cat >/etc/systemd/system/$UNIT.service <<EOF
[Unit]
Description=AXoR automatic updates: one pass of k8s/auto-update.sh
After=k3s.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=HOME=/root
ExecStart=$STATE/auto-update.sh
TimeoutStartSec=45min
Nice=5
EOF
  cat >/etc/systemd/system/$UNIT.timer <<EOF
[Unit]
Description=AXoR automatic updates, every minute

[Timer]
OnBootSec=3min
OnUnitInactiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now "$UNIT.timer" >/dev/null
  systemctl start --no-block "$UNIT.service"  # the first pass now: the Updates tab fills in right away
  # shellcheck disable=SC1090
  . "$CONF"
  echo "AXoR now follows $BRANCH (settings: $CONF, .env: $ENV_FILE). Status: ./k8s/auto-update.sh --status, or Cluster → Updates."
}

uninstall_timer() {
  systemctl disable --now "$UNIT.timer" >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/$UNIT.{service,timer}; systemctl daemon-reload
  $K -n axor delete configmap axor-update-status --ignore-not-found >/dev/null
  echo "Automatic updates are off. $STATE (checkout, logs) and the ConfigMap axor-update stay; remove them by hand if you like."
}

show_status() {
  pass 1
  local h; h=$(get history)
  [[ -n $h ]] && { echo; echo "Last updates:"; tail -n 5 <<<"$h" | while IFS=$'\t' read -r s f sha res by note; do
    echo "  $(date -d "@$s" '+%F %R') ${sha:0:7} $res ($by, $(( f - s ))s): $note"; done; }
  systemctl is-active --quiet "$UNIT.timer" && echo "Timer: on" || echo "Timer: off"
}

main() {
  [[ $EUID -eq 0 ]] || { echo "Run as root (it talks to k3s, Docker and systemd)." >&2; exit 1; }
  # shellcheck disable=SC1090
  [[ -f $CONF ]] && . "$CONF"
  [[ $BRANCH =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "BRANCH in $CONF isn't a branch name." >&2; exit 2; }
  case ${1:-} in
    --install) if [[ ${2:-} == --branch && -n ${3:-} ]]; then install_timer "$3"; else install_timer ""; fi ;;
    --uninstall) uninstall_timer ;;
    --status) show_status ;;
    --dry-run) pass 1 ;;
    "") [[ -n $ENV_FILE && -f $ENV_FILE ]] || { echo "ENV_FILE ($ENV_FILE) isn't a file: set it in $CONF." >&2; exit 1; }
        mkdir -p "$LOGS"; pass 0 ;;
    *) echo "Unknown option: $1 (use --install [--branch B], --uninstall, --status, --dry-run)" >&2; exit 2 ;;
  esac
}

# the whole file is read before anything runs, so a pass is never cut short by a newer copy of this file
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; exit; fi
