#!/usr/bin/env bash
# AXoR 5.1: brings up the spec's stack next to AXoR (PostgreSQL + pgvector, Temporal), copies AXoR's data into Postgres and
# switches AXoR over. Run as root on the k3s host, one step at a time; nothing here runs from deploy.sh or auto-update.sh.
#
#   ./k8s/stack.sh up         Postgres (k8s/stack/postgres.yaml), Temporal (temporal.yaml) and Redis (redis.yaml) in namespace axor;
#                             makes the Secret axor-postgres once. AXoR keeps running on SQLite: nothing switches yet.
#   ./k8s/stack.sh status     the stack's pods, and the settings AXoR runs with
#   ./k8s/stack.sh monitoring Prometheus, Tempo and Grafana (k8s/stack/monitoring.yaml + monitoring/), the Secrets axor-metrics
#                             and axor-grafana; enable then also sets METRICS_TOKEN and OTEL_EXPORTER_OTLP_ENDPOINT
#   ./k8s/stack.sh rehearse   a dress rehearsal on a copy, production untouched: snapshots /data/auth.db (SQLite's online
#                             backup, read-only), migrates it into a throwaway local Postgres (Docker) with this tree's
#                             app.pg_migrate, boots AXoR on the copy, checks it answers, prints the report and deletes the
#                             copy, the container and the snapshot (REHEARSE_FROM=file.db: a local file instead)
#   ./k8s/stack.sh migrate    stops AXoR (web scaled to 0), copies /data/auth.db into Postgres with a one-off Job on AXoR's own
#                             image (python -m app.pg_migrate: every table, row counts checked), and leaves web stopped
#   ./k8s/stack.sh enable     writes DATABASE_URL, MISSIONS_RUNTIME=temporal, TEMPORAL_ADDRESS, AGENT_GRAPH=langgraph into .env
#                             (a copy of .env is kept as .env.before-stack); then run ./k8s/redeploy.sh: it builds the image
#                             with temporalio/langgraph (requirements.txt), applies .env as axor-env and starts web again
#   ./k8s/stack.sh disable    takes those settings out of .env again (back to SQLite after the next redeploy). Writes made
#                             on Postgres since the migration are NOT in the SQLite file: copy them back first if they matter
#
#   ./k8s/stack.sh switch     all of it in one go, for an AXoR already on 5.1 (the image has the code: no rebuild): up,
#                             monitoring, rehearse (stops here if the copy fails), migrate, enable, then applies .env as
#                             axor-env and starts web on the new stack and checks it (Postgres row counts, /metrics says
#                             postgres/temporal/redis, no database errors). If a check fails it switches back by itself:
#                             .env restored, web restarted on SQLite (the migration only read it, so nothing is lost).
#                             --skip-rehearse, --no-monitoring.
#
# Options: --yes (don't ask before stopping AXoR), --dry-run (print what would run).
# The order: deploy 5.1 first as usual (./k8s/redeploy.sh: still on SQLite; the migration Job runs on that image), then
# up → migrate → enable → ./k8s/redeploy.sh. Rolling back before that last redeploy: ./k8s/stack.sh disable, then
# `k3s kubectl -n axor scale deploy/web --replicas=1` (SQLite was never touched: the migration only reads it).
set -euo pipefail
cd "$(dirname "$0")/.."
K="k3s kubectl"
cmd=${1:-} ; shift || true
yes=0 dry=0 rehearse=1 monitoring=1
for a in "$@"; do
  case $a in
    --yes) yes=1 ;;
    --dry-run) dry=1 ;;
    --skip-rehearse) rehearse=0 ;;
    --no-monitoring) monitoring=0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done
say() { printf '== %s\n' "$*"; }
# a Secret with one random key, never printed (also not in a dry run)
mksecret() { if ((dry)); then printf '   (dry run) create Secret %s (key %s, random)\n' "$1" "$2"; else $K -n axor create secret generic "$1" --from-literal="$2=$(openssl rand -hex 24)" >/dev/null; fi; }
die() { printf 'stack.sh: %s\n' "$*" >&2; exit 1; }
run() { if ((dry)); then printf '   (dry run) %s\n' "$*"; else "$@"; fi; }
need_root() { ((dry)) || [[ $EUID -eq 0 ]] || die "run as root (it talks to k3s)"; }
pw() { $K -n axor get secret axor-postgres -o 'jsonpath={.data.password}' | base64 -d; }
url() { echo "postgresql://axor:$(pw)@postgres.axor.svc.cluster.local:5432/axor"; }
# .env -> the Secret axor-env, the way deploy.sh does it (only lines that look like settings)
apply_env() {
  local f; f=$(mktemp)
  [[ -f .env ]] && grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env > "$f" || true
  run $K -n axor create secret generic axor-env --from-env-file="$f" --dry-run=client -o yaml > "$f.yaml"
  ((dry)) || $K apply -f "$f.yaml" >/dev/null
  rm -f "$f" "$f.yaml"
}
web_up() {  # start web (again) with axor-env as it is now, wait until it answers
  run $K -n axor scale deploy/web --replicas=1
  run $K -n axor rollout restart deploy/web
  run $K -n axor rollout status deploy/web --timeout=600s
  ((dry)) && return 0
  for _ in $(seq 1 60); do $K -n axor exec deploy/web -- curl -sf 127.0.0.1:8000/api/health >/dev/null 2>&1 && return 0; sleep 5; done
  return 1
}
KEYS=(DATABASE_URL MISSIONS_RUNTIME TEMPORAL_ADDRESS AGENT_GRAPH REDIS_URL METRICS_TOKEN OTEL_EXPORTER_OTLP_ENDPOINT)

case $cmd in
  up)
    need_root
    if ! $K -n axor get secret axor-postgres >/dev/null 2>&1; then
      say "making the Secret axor-postgres (password for AXoR and Temporal)"
      mksecret axor-postgres password
    fi
    say "network paths for the stack (k8s/stack/networkpolicy.yaml)"
    run $K apply -f k8s/stack/networkpolicy.yaml
    say "Postgres 16 + pgvector"
    run $K apply -f k8s/stack/postgres.yaml
    run $K -n axor rollout status statefulset/postgres --timeout=300s
    say "Temporal (it creates its databases in that Postgres on first start)"
    run $K apply -f k8s/stack/temporal.yaml
    run $K -n axor rollout status deploy/temporal --timeout=600s
    say "Redis (event stream, shared sign-in limits)"
    run $K apply -f k8s/stack/redis.yaml
    run $K -n axor rollout status deploy/redis --timeout=180s
    say "up. AXoR still runs on SQLite; next: ./k8s/stack.sh migrate (and ./k8s/stack.sh monitoring for Prometheus/Tempo/Grafana)"
    ;;
  status)
    $K -n axor get pods -l 'app in (postgres,temporal,redis,prometheus,tempo,grafana,web)' -o wide || true
    for k in "${KEYS[@]}"; do
      v=$(grep -E "^$k=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)
      [[ $k == DATABASE_URL && -n $v ]] && v=$(sed -E 's#://([^:]+):[^@]*@#://\1:***@#' <<<"$v")
      [[ $k == METRICS_TOKEN && -n $v ]] && v="***"
      printf '   .env %-18s %s\n' "$k" "${v:-(unset)}"
    done
    ;;
  monitoring)
    need_root
    for sec in axor-metrics:token axor-grafana:password; do
      if ! $K -n axor get secret "${sec%%:*}" >/dev/null 2>&1; then
        say "making the Secret ${sec%%:*}"
        mksecret "${sec%%:*}" "${sec#*:}"
      fi
    done
    M=k8s/stack/monitoring
    cm() { if ((dry)); then printf '   (dry run) configmap %s from %s\n' "$1" "${*:2}"; else $K -n axor create configmap "$1" "${@:2}" --dry-run=client -o yaml | $K apply -f -; fi; }
    cm prometheus-config --from-file=prometheus.yml=$M/prometheus.yml
    cm tempo-config --from-file=tempo.yaml=$M/tempo.yaml
    cm grafana-datasources --from-file=axor.yaml=$M/datasources.yaml
    cm grafana-dashboard-providers --from-file=axor.yaml=$M/dashboards.yaml
    cm grafana-dashboards --from-file=axor.json=$M/axor-dashboard.json
    run $K apply -f k8s/stack/networkpolicy.yaml
    run $K apply -f k8s/stack/monitoring.yaml
    for d in prometheus tempo grafana; do run $K -n axor rollout status deploy/$d --timeout=300s; done
    say "monitoring up. Grafana: k3s kubectl -n axor port-forward svc/grafana 3000 (user admin, password: k3s kubectl -n axor get secret axor-grafana -o jsonpath={.data.password} | base64 -d)"
    say "AXoR sends metrics and traces once enable has run and AXoR is redeployed"
    ;;
  rehearse)
    need_root
    command -v docker >/dev/null || die "rehearse needs Docker"
    image=${REHEARSE_IMAGE:-$($K -n axor get deploy web -o 'jsonpath={.spec.template.spec.containers[0].image}')}
    work=$(mktemp -d /root/axor-rehearse-XXXXXX); chmod 700 "$work"
    net=axor-rehearse-$$ pg=axor-rehearse-pg-$$ app=axor-rehearse-app-$$
    cleanup() { docker rm -f "$pg" "$app" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; rm -rf "$work"; }
    trap cleanup EXIT
    if [[ -n ${REHEARSE_FROM:-} ]]; then  # a local SQLite file instead of production's (testing this command)
      cp "$REHEARSE_FROM" "$work/auth.db"
    else
    say "snapshot of /data/auth.db (online backup, read-only) into $work"
    $K -n axor exec deploy/web -- python -c "
import os, sqlite3, sys
s = sqlite3.connect('file:/data/auth.db?mode=ro', uri=True); p = '/tmp/axor-rehearse.db'; d = sqlite3.connect(p); s.backup(d); d.close()
sys.stdout.buffer.write(open(p, 'rb').read()); os.remove(p)" > "$work/auth.db"
    fi
    say "snapshot: $(du -h "$work/auth.db" | cut -f1), integrity: $(python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0])" "$work/auth.db")"
    docker network create "$net" >/dev/null
    docker run -d --name "$pg" --network "$net" -e POSTGRES_PASSWORD=rehearse -e POSTGRES_DB=axor pgvector/pgvector:0.8.6-pg16 >/dev/null
    for _ in $(seq 1 60); do docker exec "$pg" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
    url=postgresql://postgres:rehearse@$pg:5432/axor
    say "migrating with this tree's backend on $image"
    mig=0
    docker run --rm --user root --network "$net" -v "$PWD/backend/app:/app/backend/app:ro" -v "$work:/rehearse:ro" -w /app/backend --entrypoint python \
      "$image" -m app.pg_migrate --sqlite /rehearse/auth.db --url "$url" > "$work/migrate.log" 2>&1 || mig=$?
    head -n 2 "$work/migrate.log"; grep -E "MISMATCH|skipped|Error|done" "$work/migrate.log" | head -40 || true
    say "booting AXoR on the copy (no chain, no models, no outside calls)"
    docker run -d --name "$app" --network "$net" -v "$PWD/backend/app:/app/backend/app:ro" -v "$PWD/frontend:/app/frontend:ro" \
      -e DATA_DIR=/tmp/d -e DATABASE_URL="$url" -e HIBP_CHECK=0 -e SUBTENSOR_NETWORK=ws://127.0.0.1:9 -e NEWS_REFRESH_HOURS=0 \
      --entrypoint sh "$image" -c "mkdir -p /tmp/d && exec uvicorn app.main:app --host 127.0.0.1 --port 8000" >/dev/null
    ok=0
    for _ in $(seq 1 90); do docker exec "$app" curl -sf 127.0.0.1:8000/api/health >/dev/null 2>&1 && { ok=1; break; }; sleep 1; done
    sleep 20  # let the background clocks (missions, autoloop, evolution …) run their first queries on the copy
    docker exec "$app" curl -s 127.0.0.1:8000/api/health || true; echo
    errs=$(docker logs "$app" 2>&1 | grep -cE "OperationalError|IntegrityError|postgres [0-9A-Z]{5}\]" || true)  # the chain is offline on purpose: its tracebacks aren't counted
    { docker logs "$app" 2>&1 | grep -E "OperationalError|IntegrityError" | sed -E 's/ in: .*//' | sort | uniq -c | sort -rn | head -20; } || true
    ((ok)) || die "AXoR didn't come up on the copy (log above)"
    ((mig == 0)) || die "the migration reported mismatches or skipped rows (above)"
    say "rehearsal done: migration matched, AXoR answered, $errs database error line(s) in its log in the first 20 s. Everything was deleted."
    ;;
  switch)
    need_root
    self=$0 opts=(); ((dry)) && opts+=(--dry-run)
    ((dry)) || $K -n axor exec deploy/web -- python -c "import app.pg_migrate, app.vector_pg, app.bus, temporalio, langgraph, redis" \
      || die "the running AXoR isn't 5.1 with the stack's packages: ./k8s/redeploy.sh first"
    say "1/6 Postgres, Temporal, Redis"; "$self" up "${opts[@]}"
    if ((monitoring)); then say "2/6 Prometheus, Tempo, Grafana"; "$self" monitoring "${opts[@]}"; else say "2/6 monitoring skipped"; fi
    if ((rehearse && !dry)); then say "3/6 dress rehearsal on a copy"; "$self" rehearse || die "the rehearsal failed: production is unchanged (still SQLite); the stack's pods are up and idle"
    else say "3/6 rehearsal $( ((dry)) && echo "(runs only for real)" || echo skipped)"; fi
    ((dry)) || before=$($K -n axor exec deploy/web -- python -c "import sqlite3; c=sqlite3.connect('file:/data/auth.db?mode=ro', uri=True); print(c.execute('SELECT COUNT(*) FROM users').fetchone()[0], c.execute('SELECT COUNT(*) FROM ac_runs').fetchone()[0])")
    say "4/6 migrate (AXoR stops here)"
    "$self" migrate --yes "${opts[@]}" || { web_up; die "the migration failed (above): AXoR is started again on SQLite, unchanged"; }
    say "5/6 settings"
    "$self" enable "${opts[@]}" || { web_up; die "writing the settings failed: AXoR is started again on SQLite, unchanged"; }
    apply_env
    say "6/6 AXoR on the new stack"
    ok=1; why=
    web_up || { ok=0; why="AXoR didn't answer /api/health on the new stack"; }
    if ((ok && !dry)); then
      sleep 20  # the clocks run their first queries
      after=$($K -n axor exec deploy/web -- python -c "
from app import db_pg
c = db_pg.connect(); print(c.execute('SELECT COUNT(*) FROM users').fetchone()[0], c.execute('SELECT COUNT(*) FROM ac_runs').fetchone()[0])" 2>&1 | tail -n1)
      read -r bu br <<<"$before"; read -r au ar <<<"$after"
      [[ $au == "$bu" && $ar =~ ^[0-9]+$ && $ar -ge $br ]] || { ok=0; why="row counts don't match: SQLite users/runs $before, Postgres $after"; }  # runs may grow: agents start working
      info=$($K -n axor exec deploy/web -- sh -c 'curl -s -H "Authorization: Bearer $METRICS_TOKEN" 127.0.0.1:8000/metrics | grep ^axor_stack_info' 2>/dev/null || true)
      [[ -z $info ]] && info=$($K -n axor exec deploy/web -- python -c "from app import db_pg; print(db_pg.describe()['engine'])" 2>/dev/null)
      grep -q postgres <<<"$info" || { ok=0; why="AXoR doesn't report Postgres: $info"; }
      errs=$($K -n axor logs deploy/web --since=5m 2>&1 | grep -cE "OperationalError|IntegrityError|postgres [0-9A-Z]{5}\]" || true)
      ((errs == 0)) || { ok=0; why="$errs database error line(s) in AXoR's log"; $K -n axor logs deploy/web --since=5m 2>&1 | grep -E "OperationalError|IntegrityError" | sed -E 's/ in: .*//' | sort | uniq -c | head; }
      say "checks: users/runs SQLite $before → Postgres $after · ${info:-?} · $errs database errors"
    fi
    if ((ok)); then
      say "switched: AXoR runs on Postgres + pgvector, Temporal, LangGraph and Redis$( ((monitoring)) && echo ", with Prometheus/Tempo/Grafana" ). The SQLite file stays as it was (a backup as of the switch)."
      say "back to SQLite if ever needed: ./k8s/stack.sh disable, then apply .env (./k8s/redeploy.sh) — writes made on Postgres since then stay in Postgres"
    else
      say "check failed: $why — switching back to SQLite"
      if ((!dry)); then
        [[ -f .env.before-stack ]] && cp -p .env.before-stack .env
        apply_env
        web_up && say "back on SQLite, as before the switch (nothing written to SQLite was lost; Postgres keeps the copy for a retry)" \
               || die "AXoR didn't come back on SQLite either: k3s kubectl -n axor get pods; logs: k3s kubectl -n axor logs deploy/web"
      fi
      exit 1
    fi
    ;;
  migrate)
    need_root
    ((dry)) || $K -n axor get statefulset postgres >/dev/null 2>&1 || die "Postgres isn't up: ./k8s/stack.sh up first"
    image=$($K -n axor get deploy web -o 'jsonpath={.spec.template.spec.containers[0].image}')
    ((dry)) || $K -n axor exec deploy/web -- python -c "import app.pg_migrate" 2>/dev/null \
      || die "the running image ($image) has no app.pg_migrate: deploy 5.1 first (./k8s/redeploy.sh), then migrate"
    say "copies /data/auth.db into Postgres with $image; AXoR is stopped while it copies"
    if ((!yes && !dry)); then read -r -p "Stop AXoR (scale web to 0) and migrate now? [y/N] " a; [[ $a == [yY]* ]] || die "nothing done"; fi
    run $K -n axor scale deploy/web --replicas=0
    run $K -n axor wait --for=delete pod -l app=web --timeout=180s || true
    run $K -n axor delete job axor-pg-migrate --ignore-not-found
    job=$(cat <<YAML
apiVersion: batch/v1
kind: Job
metadata: { name: axor-pg-migrate, namespace: axor }
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    metadata: { labels: { app: pg-migrate } }  # k8s/stack/networkpolicy.yaml lets this label reach Postgres
    spec:
      restartPolicy: Never
      securityContext: { runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000, seccompProfile: { type: RuntimeDefault } }
      containers:
        - name: migrate
          image: $image
          imagePullPolicy: Never
          workingDir: /app/backend
          command: [python, -m, app.pg_migrate, --sqlite, /data/auth.db]
          env:  # PGPASSWORD first: \$(PGPASSWORD) only expands from a variable defined before it
            - { name: PGPASSWORD, valueFrom: { secretKeyRef: { name: axor-postgres, key: password } } }
            - { name: DATABASE_URL, value: "postgresql://axor:\$(PGPASSWORD)@postgres.axor.svc.cluster.local:5432/axor" }
          securityContext: { allowPrivilegeEscalation: false, capabilities: { drop: [ALL] } }
          volumeMounts: [{ name: data, mountPath: /data, readOnly: true }]
      volumes: [{ name: data, persistentVolumeClaim: { claimName: web-data } }]
YAML
)
    if ((dry)); then echo "$job"; exit 0; fi
    echo "$job" | $K apply -f -
    $K -n axor wait --for=condition=complete job/axor-pg-migrate --timeout=1800s || true
    $K -n axor logs job/axor-pg-migrate | tail -n 400
    st=$($K -n axor get job axor-pg-migrate -o 'jsonpath={.status.succeeded}')
    [[ $st == 1 ]] || die "the migration didn't finish cleanly (log above). AXoR is still stopped on SQLite: fix and run again (--force empties what it copied), or start it as it was: $K -n axor scale deploy/web --replicas=1"
    say "copied. AXoR is stopped; next: ./k8s/stack.sh enable, then ./k8s/redeploy.sh"
    ;;
  enable)
    need_root
    if $K -n axor get secret axor-postgres >/dev/null 2>&1; then u=$(url)
    elif ((dry)); then u="postgresql://axor:***@postgres.axor.svc.cluster.local:5432/axor"
    else die "no Secret axor-postgres: ./k8s/stack.sh up first"; fi
    tmp=$(mktemp)
    [[ -f .env ]] && { grep -vE "^($(IFS='|'; echo "${KEYS[*]}"))=" .env > "$tmp" || true; }
    { cat "$tmp"
      echo "DATABASE_URL=$u"
      echo "MISSIONS_RUNTIME=temporal"
      echo "TEMPORAL_ADDRESS=temporal-frontend.axor.svc.cluster.local:7233"
      echo "AGENT_GRAPH=langgraph"
      $K -n axor get deploy redis >/dev/null 2>&1 && echo "REDIS_URL=redis://redis.axor.svc.cluster.local:6379/0"
      if $K -n axor get secret axor-metrics >/dev/null 2>&1; then  # monitoring is up: metrics for Prometheus, traces to Tempo
        echo "METRICS_TOKEN=$($K -n axor get secret axor-metrics -o 'jsonpath={.data.token}' | base64 -d)"
        echo "OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo.axor.svc.cluster.local:4318"
      fi; } > "$tmp.new"
    if ((dry)); then  # only the settings this manages, secrets masked; .env's other lines are never printed
      grep -E "^($(IFS='|'; echo "${KEYS[*]}"))=" "$tmp.new" | sed -E 's#://([^:]+):[^@]*@#://\1:***@#; s#^(METRICS_TOKEN=).*#\1***#'
      printf '   (other .env lines kept as they are: %s)\n' "$(grep -cvE "^($(IFS='|'; echo "${KEYS[*]}"))=" "$tmp.new" || true)"
      rm -f "$tmp" "$tmp.new"; exit 0
    fi
    [[ -f .env ]] && cp -p .env .env.before-stack
    cat "$tmp.new" > .env; rm -f "$tmp" "$tmp.new"
    chmod 600 .env
    say "written to .env (before: .env.before-stack). Next: ./k8s/redeploy.sh (builds the 5.1 image, applies .env, starts AXoR on Postgres)"
    ;;
  disable)
    [[ -f .env ]] || die "no .env"
    grep -vE "^($(IFS='|'; echo "${KEYS[*]}"))=" .env > .env.tmp || true
    if ((dry)); then  # the keys it would remove, values masked
      grep -oE "^($(IFS='|'; echo "${KEYS[*]}"))=" .env | sed 's/=$/= (would be removed)/' || echo "   none of the stack's settings are in .env"
      rm -f .env.tmp; exit 0
    fi
    cp -p .env .env.before-stack-disable
    cat .env.tmp > .env; rm -f .env.tmp
    say "taken out of .env (before: .env.before-stack-disable). ./k8s/redeploy.sh puts AXoR back on SQLite"
    ;;
  *)
    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
    exit 2 ;;
esac
