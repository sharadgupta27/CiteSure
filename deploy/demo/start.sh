#!/usr/bin/env bash
# Single-container demo: Postgres, worker, API and nginx in one container.
#   start-citesure prepare   (run at image build) create the database, migrate and seed, then stop Postgres
#   start-citesure           (container start)    start everything; prepares first only if the image was not prepared
# Preparing at build time matters on free hosts with 0.1 CPU: seeding at start-up took over 5 minutes there.
# Every container starts from the image's database, so the demo resets on each restart.
set -euo pipefail

log() { echo "[citesure-demo] $*"; }
PG_OPTS="-c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp"
export DATABASE_URL="postgresql+asyncpg://citesure@127.0.0.1:5432/citesure"
if [ -z "${JWT_SECRET:-}" ]; then
  # A fresh secret per start: sessions end when the container restarts, which is fine for a demo.
  # (head + base64, not Python: every extra interpreter start costs seconds on a 0.1-CPU host.)
  JWT_SECRET="$(head -c 48 /dev/urandom | base64 | tr -d '\n=' | tr '+/' '-_')"
  export JWT_SECRET
fi
cd /srv/citesure/backend

prepare() {
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    log "initialising database"
    # trust auth is safe: Postgres listens on localhost inside the container only
    initdb -D "$PGDATA" -U citesure --auth=trust --encoding=UTF8 >/dev/null
  fi
  pg_ctl -D "$PGDATA" -o "$PG_OPTS" -l /tmp/postgres.log -w start
  createdb -h 127.0.0.1 -U citesure citesure 2>/dev/null || true
  log "migrating"
  alembic upgrade head
  log "seeding demo users and documents"
  # The seed loads the corpus through the upload service; only this command may upload, the API never can.
  # The demo password is public (README), but it is passed only to the seed so it never sits in the image ENV.
  UPLOADS_ENABLED=true SEED_PASSWORD="${SEED_PASSWORD:-citesure-demo}" python -m app.seed
  touch /data/.prepared
}

if [ "${1:-}" = "prepare" ]; then
  prepare
  pg_ctl -D "$PGDATA" -m fast -w stop
  exit 0
fi

# Open the port at once with a "waking up" page, so the host sees the service listening and visitors know to wait.
cp /etc/nginx/citesure/booting.conf /tmp/citesure-locations.conf
log "starting web server on :7860 (starting page)"
nginx -g 'daemon off;' &

if [ -f /data/.prepared ]; then
  pg_ctl -D "$PGDATA" -o "$PG_OPTS" -l /tmp/postgres.log -w start
else
  prepare
fi

log "starting API"
uvicorn app.main:app_factory --factory --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 &
api_pid=$!

api_ready() (
  # Plain bash HTTP check in a subshell: no curl in the image, no Python start-up cost, and a refused connection
  # cannot end the main script.
  exec 3<>/dev/tcp/127.0.0.1/8000
  printf 'GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n' >&3
  read -r _ status _ <&3
  [ "$status" = "200" ]
)
until api_ready 2>/dev/null; do
  kill -0 "$api_pid" 2>/dev/null || { log "API exited during start-up"; exit 1; }
  sleep 2
done

cp /etc/nginx/citesure/live.conf /tmp/citesure-locations.conf
nginx -s reload
log "API ready; serving the app"

# The worker starts last so it does not compete with the API for the CPU while visitors are waiting.
log "starting worker"
python -m app.worker &

wait -n
log "a process exited; stopping"
exit 1
