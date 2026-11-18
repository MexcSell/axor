#!/usr/bin/env bash
# Runs the unit tests (tests/unit) inside AXoR's web image, which has the exact dependencies production runs; the host
# has none of them. Offline (--network none), as the image's user, with a throwaway DATA_DIR.
#
#   tests/run-unit.sh                 this working tree's backend, on the newest local axor/web image
#   tests/run-unit.sh --image TAG     the code inside axor/web:TAG as built (k8s/redeploy.sh runs this before a deploy)
#   tests/run-unit.sh -- -k margin    anything after -- goes to unittest (e.g. -v, -k PATTERN, -f)
#   tests/run-unit.sh --postgres      the same tests on Postgres, as production runs (DATABASE_URL): a throwaway
#                                     pgvector/pgvector:0.8.6-pg16 (k8s/stack/postgres.yaml's image) on a private network,
#                                     max_connections=400 (each AuthDB path gets its own schema), removed afterwards
#
# The fake services in tests/*.py are for running AXoR by hand against fakes; they aren't tests and aren't run here.
set -euo pipefail
cd "$(dirname "$0")/.."
tag= extra=() pg=0
while (($#)); do
  case $1 in
    --image) tag=${2:?--image needs a tag}; shift 2 ;;
    --postgres) pg=1; shift ;;
    --) shift; extra=("$@"); break ;;
    *) echo "Unknown option: $1 (use --image TAG, --postgres, or -- unittest options)" >&2; exit 2 ;;
  esac
done
mounts=(-v "$PWD/tests/unit:/app/tests/unit:ro")
if [[ -z $tag ]]; then
  tag=$(docker images axor/web --format '{{.Tag}}' | head -n1)
  [[ -n $tag ]] || { echo "No axor/web image on this host: build one (k8s/deploy.sh or k8s/redeploy.sh --check), or pass --image" >&2; exit 2; }
  mounts+=(-v "$PWD/backend/app:/app/backend/app:ro")
  echo "== unit tests: this working tree on axor/web:$tag's dependencies"
else
  echo "== unit tests: axor/web:$tag as built"
fi
net=(--network none) env=()
if ((pg)); then
  id=axor-unit-pg-$$ pw=$(python3 -c 'import secrets;print(secrets.token_hex(12))')
  trap 'docker rm -f "$id" >/dev/null 2>&1; docker network rm "$id" >/dev/null 2>&1' EXIT
  docker network create --internal "$id" >/dev/null
  docker run -d --name "$id" --network "$id" -e POSTGRES_PASSWORD="$pw" -e POSTGRES_USER=axor -e POSTGRES_DB=axor \
    "${PG_IMAGE:-pgvector/pgvector:0.8.6-pg16}" -c max_connections=400 >/dev/null
  for _ in $(seq 60); do docker exec "$id" pg_isready -U axor -d axor -q 2>/dev/null && break; sleep 1; done
  sleep 2; for _ in $(seq 30); do docker exec "$id" pg_isready -U axor -d axor -q 2>/dev/null && break; sleep 1; done
  net=(--network "$id") env=(-e "DATABASE_URL=postgresql://axor:$pw@$id:5432/axor" -e DATABASE_SCHEMA_PER_PATH=1)
  echo "== on Postgres (${PG_IMAGE:-pgvector/pgvector:0.8.6-pg16}, throwaway)"
fi
docker run --rm "${net[@]}" "${mounts[@]}" "${env[@]}" -e DATA_DIR=/tmp/axor-test -e PYTHONDONTWRITEBYTECODE=1 -e HIBP_CHECK=0 \
  -w /app/backend --entrypoint python "axor/web:$tag" -m unittest discover -s /app/tests/unit -t /app/tests/unit "${extra[@]}"
