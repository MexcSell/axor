#!/usr/bin/env bash
# AXoR data backups (docs/architecture/stabilization, roadmap 0.2 / gap G-11): production data had no scheduled backup.
#
#   k8s/backup.sh                 one backup now, into $BACKUP_DIR/<UTC timestamp>/ (0700), then prunes past $KEEP_DAYS
#   k8s/backup.sh --verify [DIR]  restore test of DIR (default: the newest): the Postgres dump into a throwaway pgvector
#                                 container (removed after), table and row counts; every SQLite copy's integrity_check
#   k8s/backup.sh --list          the backups, their sizes and whether each was verified
#   k8s/backup.sh --install       a systemd timer (axor-backup.timer) that runs a backup daily at 03:30 and verifies it
#   k8s/backup.sh --uninstall     removes that timer
#
# What a backup holds, all read-only for production:
#   postgres.dump   pg_dump -Fc of the axor database, run inside postgres-0 over its local socket (no password handled here)
#   sqlite/         consistent copies (SQLite online backup API) of every *.db on the web-data, push-data and dns-data volumes
#   files.tar.gz    the rest of web-data, drive-data, push-data, dns-data and edge-acme (without the live *.db files)
#   env             the repository's .env (0600): the configuration a restore needs
#   manifest        what was taken, sizes, the running AXoR build
# Nothing is printed from .env or the dump. Restoring production is a decision for the owner and is not automated here.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
REPO=$PWD
K=${KUBECTL:-k3s kubectl}
BACKUP_DIR=${BACKUP_DIR:-/var/lib/axor/backups}
KEEP_DAYS=${KEEP_DAYS:-14}
PG_IMAGE=${PG_IMAGE:-pgvector/pgvector:0.8.6-pg16}   # the image k8s/stack/postgres.yaml runs
STORAGE=${STORAGE:-/var/lib/rancher/k3s/storage}     # k3s local-path volumes
ENV_FILE=${ENV_FILE:-$REPO/.env}
VOLUMES=(axor_web-data axor_drive-data axor_push-data axor-edge_dns-data axor-edge_edge-acme)
say() { echo "== $*"; }

vol_path() { compgen -G "$STORAGE/pvc-*_$1" | head -n1; }

backup() {
  local ts dir part
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  dir="$BACKUP_DIR/$ts" part="$BACKUP_DIR/.$ts.part"
  umask 077
  mkdir -p "$BACKUP_DIR" "$part/sqlite"
  chmod 700 "$BACKUP_DIR"
  trap 'rm -rf "$part"' EXIT

  say "postgres: pg_dump of axor (postgres-0)"
  $K -n axor exec postgres-0 -- pg_dump -U axor -d axor -Fc >"$part/postgres.dump"
  [[ -s $part/postgres.dump ]] || { echo "the dump is empty" >&2; exit 1; }

  say "sqlite: consistent copies of the volumes' databases"
  local v p
  for v in "${VOLUMES[@]}"; do
    p=$(vol_path "$v") || true
    [[ -n $p ]] || { echo "   no volume $v (skipped)"; continue; }
    python3 -I - "$p" "$part/sqlite/$v" <<'PY'
import os, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
for root, _, files in os.walk(src):
    for f in files:
        if not f.endswith(".db"): continue
        s = os.path.join(root, f)
        d = os.path.join(dst, os.path.relpath(s, src))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        a = sqlite3.connect(f"file:{s}?mode=ro", uri=True, timeout=30)
        b = sqlite3.connect(d)
        a.backup(b); b.close(); a.close()
        print(f"   {os.path.relpath(s, src)} ({os.path.getsize(d) // 1024} kB)")
PY
  done

  say "files: the volumes without their live databases"
  local args=()
  for v in "${VOLUMES[@]}"; do p=$(vol_path "$v") || true; [[ -n $p ]] && args+=(-C "$STORAGE" "$(basename "$p")"); done
  tar --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude='*.db-journal' --warning=no-file-changed \
      -czf "$part/files.tar.gz" "${args[@]}" || [[ $? -eq 1 ]]   # 1 = a file changed while read: still a usable archive

  if [[ -f $ENV_FILE ]]; then install -m 600 "$ENV_FILE" "$part/env"; fi
  {
    echo "taken $ts"
    echo "build $($K -n axor get deploy web -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo unknown)"
    (cd "$part" && du -ab . | sort -k2)
  } >"$part/manifest"
  mv "$part" "$dir"
  trap - EXIT
  say "backup $dir ($(du -sh "$dir" | cut -f1))"

  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*Z' -mtime +"$KEEP_DAYS" -print -exec rm -rf {} + | sed 's/^/   pruned /'
}

# How to restore a dump (the restore test uses it; a real restore into an empty database follows the same three steps).
# pg_restore runs with an empty search_path, and dumps taken before 2026-11-11 hold axor_compat.f32vec without its own
# search_path: its body's `::vector` then can't be resolved and COPY into the tables with a generated emb column fails.
# So: the schema first, then the function gets its search_path (a no-op on newer dumps), then the data and the rest.
restore_into() {  # container, dump path inside it, log file
  local c=$1 dump=$2 log=$3
  docker exec "$c" pg_restore -U axor -d axor --no-owner --exit-on-error --section=pre-data "$dump" 2>"$log" || return 1
  docker exec "$c" psql -U axor -d axor -q -v ON_ERROR_STOP=1 -c "DO \$\$ BEGIN
      IF to_regprocedure('axor_compat.f32vec(bytea)') IS NOT NULL THEN
        ALTER FUNCTION axor_compat.f32vec(bytea) SET search_path TO axor_compat, public; END IF; END \$\$;" 2>>"$log" || return 1
  docker exec "$c" pg_restore -U axor -d axor --no-owner --exit-on-error --section=data --section=post-data "$dump" 2>>"$log"
}

verify() {
  local dir=${1:-$(ls -1d "$BACKUP_DIR"/20*Z 2>/dev/null | tail -n1)}
  [[ -d $dir && -s $dir/postgres.dump ]] || { echo "No backup to verify (${dir:-none})" >&2; exit 2; }
  local pw
  VERIFY_NAME="axor-backup-verify-$$"
  local name=$VERIFY_NAME
  pw=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
  trap 'docker rm -f "$VERIFY_NAME" >/dev/null 2>&1 || true' EXIT
  say "restore test of $dir into a throwaway $PG_IMAGE"
  docker run -d --name "$name" --network none -e POSTGRES_PASSWORD="$pw" -e POSTGRES_USER=axor -e POSTGRES_DB=axor \
         -v "$dir/postgres.dump:/backup.dump:ro" "$PG_IMAGE" >/dev/null
  for _ in $(seq 60); do docker exec "$name" pg_isready -U axor -d axor -q 2>/dev/null && break; sleep 1; done
  sleep 2  # the image's init restarts the server once
  for _ in $(seq 30); do docker exec "$name" pg_isready -U axor -d axor -q 2>/dev/null && break; sleep 1; done
  local errs=0
  restore_into "$name" /backup.dump "$dir/.restore.log" || errs=1
  if (( errs )); then echo "   pg_restore failed:"; tail -5 "$dir/.restore.log" | sed 's/^/   /'; exit 1; fi
  docker exec "$name" psql -U axor -d axor -Atc "
    SELECT 'tables ' || COUNT(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');
    SELECT 'users ' || COUNT(*) FROM users;
    SELECT 'runs ' || COUNT(*) FROM ac_runs;
    SELECT 'missions ' || COUNT(*) FROM mx_missions;
    SELECT 'team tasks ' || COUNT(*) FROM mw_tasks;" 2>&1 | sed 's/^/   /'
  say "sqlite copies: integrity_check"
  python3 -I - "$dir/sqlite" <<'PY'
import os, sqlite3, sys
bad = 0
for root, _, files in os.walk(sys.argv[1]):
    for f in sorted(files):
        p = os.path.join(root, f)
        r = sqlite3.connect(f"file:{p}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0]
        bad += r != "ok"
        print(f"   {os.path.relpath(p, sys.argv[1])}: {r}")
sys.exit(1 if bad else 0)
PY
  tar -tzf "$dir/files.tar.gz" >/dev/null && echo "   files.tar.gz: readable ($(tar -tzf "$dir/files.tar.gz" | wc -l) entries)"
  date -u +%Y-%m-%dT%H:%M:%SZ >"$dir/verified"
  docker rm -f "$name" >/dev/null 2>&1 || true
  trap - EXIT
  say "verified $dir"
}

list() {
  local d
  for d in "$BACKUP_DIR"/20*Z; do
    [[ -d $d ]] || { echo "No backups in $BACKUP_DIR"; return; }
    printf '%s  %6s  %s\n' "$(basename "$d")" "$(du -sh "$d" | cut -f1)" "$([[ -f $d/verified ]] && echo "verified $(cat "$d/verified")" || echo "not verified")"
  done
}

install_timer() {
  cat >/etc/systemd/system/axor-backup.service <<EOF
[Unit]
Description=AXoR data backup (k8s/backup.sh) and its restore test
After=k3s.service docker.service

[Service]
Type=oneshot
ExecStart=$REPO/k8s/backup.sh
ExecStartPost=$REPO/k8s/backup.sh --verify
EOF
  cat >/etc/systemd/system/axor-backup.timer <<'EOF'
[Unit]
Description=AXoR data backup, daily

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=10m
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now axor-backup.timer
  systemctl list-timers axor-backup.timer --no-pager
}

case "${1:-}" in
  "") backup ;;
  --verify) verify "${2:-}" ;;
  --list) list ;;
  --install) install_timer ;;
  --uninstall) systemctl disable --now axor-backup.timer 2>/dev/null || true
               rm -f /etc/systemd/system/axor-backup.{service,timer}; systemctl daemon-reload; echo "removed" ;;
  *) echo "Unknown option: $1 (use --verify [DIR], --list, --install, --uninstall)" >&2; exit 2 ;;
esac
