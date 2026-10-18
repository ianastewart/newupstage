#!/usr/bin/env bash
# Restore a database dump and media archive (from pull_from_server.sh) into the local setup.
#
# Usage:  scripts/restore_local.sh [-y] [db|media|all] [dump-or-archive-file]
#   -y            don't ask for confirmation
#   default       restores the newest files in ./backups (db and media)
#
# Settings (environment variables, or scripts/.server.env):
#   PGHOST (localhost) PGPORT (5432) PGUSER (postgres) PGDATABASE (upstage)
#   PGPASSWORD         or use your pgpass file (not available to the docker fallback)
#   MEDIA_DIR          default upstage/media
#   OUT_DIR            where the backups are, default backups
#
#   USE_COMPOSE_DB=1   restore into the docker compose 'db' service (postgres 17) instead of a local server;
#                      the PG* settings above are ignored
#
# Before anything is replaced, the current local database and media are saved to $OUT_DIR/local/
# (pre-restore-<time>.dump / .tgz), so a restore can be undone with: restore_local.sh db backups/local/pre-restore-<time>.dump
#
# If the local pg_restore is older than the one that made the dump (e.g. 16 vs a 17 server),
# the restore is run with a postgres:17 docker image instead.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f scripts/.server.env ] && . scripts/.server.env

export PGHOST=${PGHOST:-localhost} PGPORT=${PGPORT:-5432}
export PGUSER=${PGUSER:-postgres} PGDATABASE=${PGDATABASE:-upstage}
OUT_DIR=${OUT_DIR:-backups}
MEDIA_DIR=${MEDIA_DIR:-upstage/media}
PG_IMAGE=${PG_IMAGE:-postgres:17}

stamp=$(date +%Y%m%d-%H%M%S)
yes=0
[ "${1:-}" = "-y" ] && { yes=1; shift; }
what=${1:-all}
file=${2:-}

newest() { ls -1t "$OUT_DIR"/$1 2>/dev/null | head -1; }

confirm() {
  [ "$yes" = 1 ] && return
  read -r -p "$1 [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || { echo "Cancelled."; exit 1; }
}

restore_db() {
  local dump=${file:-$(newest 'upstage-*.dump')}
  [ -f "$dump" ] || { echo "No dump found (looked in $OUT_DIR)" >&2; exit 1; }

  local pg_restore=(pg_restore) psql=(psql) pg_dump=(pg_dump) stdin=0
  if [ "${USE_COMPOSE_DB:-0}" = 1 ]; then
    echo "Starting the compose db service ..."
    docker compose up -d --wait db
    # Run the tools inside the container, as its own database user
    local d=(docker compose exec -T db sh -c 'export PGUSER=$POSTGRES_USER; exec "$@"' sh)
    pg_restore=("${d[@]}" pg_restore); psql=("${d[@]}" psql); pg_dump=("${d[@]}" pg_dump); stdin=1
    PGDATABASE=$(docker compose exec -T db printenv POSTGRES_DB | tr -d '[:space:]')
  elif ! pg_restore -l "$dump" >/dev/null 2>&1; then
    echo "Local pg_restore can't read this dump (newer format); using docker image $PG_IMAGE"
    local host=$PGHOST
    case $host in localhost|127.0.0.1) host=host.docker.internal ;; esac
    local d=(docker run --rm -i -e PGPASSWORD -e PGUSER -e PGPORT -e PGDATABASE -e "PGHOST=$host" "$PG_IMAGE")
    pg_restore=("${d[@]}" pg_restore); psql=("${d[@]}" psql); pg_dump=("${d[@]}" pg_dump); stdin=1
  fi

  if [ "${USE_COMPOSE_DB:-0}" = 1 ]; then target="the compose db service"; else target=$PGHOST; fi
  confirm "Replace the contents of database '$PGDATABASE' on $target with $dump?"

  if "${psql[@]}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$PGDATABASE'" </dev/null | grep -q 1; then
    # Save what is there now
    mkdir -p "$OUT_DIR/local"
    local saved="$OUT_DIR/local/pre-restore-$stamp.dump"
    echo "Saving the current database to $saved ..."
    "${pg_dump[@]}" -Fc -d "$PGDATABASE" </dev/null > "$saved"
    echo "Saved ($(du -h "$saved" | cut -f1))."
  else
    "${psql[@]}" -d postgres -c "CREATE DATABASE \"$PGDATABASE\"" </dev/null
  fi
  echo "Restoring $dump ..."
  if [ $stdin = 1 ]; then
    "${pg_restore[@]}" --clean --if-exists --no-owner --no-privileges -d "$PGDATABASE" < "$dump"
  else
    "${pg_restore[@]}" --clean --if-exists --no-owner --no-privileges -d "$PGDATABASE" "$dump"
  fi
  echo "Database restored."
}

restore_media() {
  local tgz=${file:-$(newest 'media-*.tgz')}
  [ -f "$tgz" ] || { echo "No media archive found (looked in $OUT_DIR)" >&2; exit 1; }
  confirm "Replace everything in $MEDIA_DIR with $tgz?"
  mkdir -p "$MEDIA_DIR" "$OUT_DIR/local"
  if [ -n "$(ls -A "$MEDIA_DIR")" ]; then
    local saved="$OUT_DIR/local/pre-restore-$stamp.tgz"
    echo "Saving the current media to $saved ..."
    tar -czf "$saved" -C "$MEDIA_DIR" .
    echo "Saved ($(du -h "$saved" | cut -f1))."
  fi
  find "$MEDIA_DIR" -mindepth 1 -delete
  tar -xzf "$tgz" -C "$MEDIA_DIR"
  echo "Media restored to $MEDIA_DIR."
}

case "$what" in
  db) restore_db ;;
  media) restore_media ;;
  all) file=""; restore_db; restore_media ;;
  *) echo "Usage: $0 [-y] [db|media|all] [file]" >&2; exit 1 ;;
esac
