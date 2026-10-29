#!/usr/bin/env bash
# REPLACE the database and/or media on the Coolify server with the local ones.  This overwrites production data.
#
# Usage:  scripts/push_to_server.sh [--dry-run] [db|media|all]      (default: all)
#   --dry-run   make the local dump/archive and check the server containers, but change nothing on the server
#
# What it does:
#   1. makes the local dump (USE_COMPOSE_DB=1: the docker compose db; otherwise PGHOST/PGPORT/PGUSER/PGDATABASE) and media archive
#   2. saves the server's current database and media to backups/server-before-push/ (using pull_from_server.sh)
#   3. asks you to type the server name to confirm
#   4. database: stops the web container, restores in ONE transaction (a failure leaves the old data in place), starts it again
#   5. media: uploads the archive, checks it, then empties /data/media and unpacks it
#
# Settings are the same as pull_from_server.sh and restore_local.sh (environment, or scripts/.server.env).
# The local schema must match the code deployed on the server (or be older: the app's start-up runs migrations).
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f scripts/.server.env ] && . scripts/.server.env

SERVER=${SERVER:-root@coolify.iskt.co.uk}
OUT_DIR=${OUT_DIR:-backups}
MEDIA_DIR=${MEDIA_DIR:-upstage/media}
MEDIA_PATH=${MEDIA_PATH:-/data/media}
export PGHOST=${PGHOST:-localhost} PGPORT=${PGPORT:-5433}
export PGUSER=${PGUSER:-postgres} PGDATABASE=${PGDATABASE:-upstage}
: "${WEB_FILTER:?Set WEB_FILTER (docker name filter for the web container)}"
: "${DB_FILTER:?Set DB_FILTER (docker name filter for the database container)}"

dry=0
[ "${1:-}" = "--dry-run" ] && { dry=1; shift; }
what=${1:-all}
case "$what" in db|media|all) ;; *) echo "Usage: $0 [--dry-run] [db|media|all]" >&2; exit 1 ;; esac

stamp=$(date +%Y%m%d-%H%M%S)
local_dir="$OUT_DIR/local"
mkdir -p "$local_dir"
dump="$local_dir/push-$stamp.dump"
tgz="$local_dir/push-$stamp.tgz"

find_container() {
  local c
  c=$(ssh "$SERVER" "docker ps --filter 'name=$1' --format '{{.Names}}' | head -1")
  [ -n "$c" ] || { echo "No running container matches '$1'" >&2; exit 1; }
  echo "$c"
}

# 1. Local data
if [ "$what" != media ]; then
  if [ "${USE_COMPOSE_DB:-0}" = 1 ]; then
    src="the docker compose db"
    docker compose up -d --wait db
    docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' </dev/null > "$dump"
  else
    src="$PGDATABASE on $PGHOST:$PGPORT"
    pg_dump -Fc -d "$PGDATABASE" > "$dump"
  fi
  echo "Local database ($src): $dump ($(du -h "$dump" | cut -f1))"
fi
if [ "$what" != db ]; then
  [ -n "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ] || { echo "$MEDIA_DIR is empty; refusing to push it" >&2; exit 1; }
  tar -czf "$tgz" -C "$MEDIA_DIR" .
  echo "Local media ($MEDIA_DIR): $tgz ($(du -h "$tgz" | cut -f1))"
fi

web=$(find_container "$WEB_FILTER")
db=$(find_container "$DB_FILTER")
echo "Server $SERVER: web container $web, database container $db"

if [ "$dry" = 1 ]; then
  echo "Dry run: nothing changed on the server."
  exit 0
fi

# 2. Back up the server
echo "Backing up the server first ..."
OUT_DIR="$OUT_DIR/server-before-push" "$(dirname "$0")/pull_from_server.sh" "$what"

# 3. Confirm
echo
echo "This will REPLACE the $what on $SERVER with the local version."
read -r -p "Type the server name (${SERVER#*@}) to continue: " answer
[ "$answer" = "${SERVER#*@}" ] || { echo "Cancelled."; exit 1; }

# 4. Database
if [ "$what" != media ]; then
  echo "Stopping $web ..."
  ssh "$SERVER" "docker stop $web" >/dev/null
  # Always start the app again, even if the restore fails
  trap 'echo "Starting $web ..."; ssh "$SERVER" "docker start $web" >/dev/null' EXIT
  echo "Restoring the database ..."
  ssh "$SERVER" "docker exec -i $db sh -c 'pg_restore --single-transaction --exit-on-error --clean --if-exists --no-owner --no-privileges -U \"\$POSTGRES_USER\" -d \"${SERVER_DB:-\$POSTGRES_DB}\"'" < "$dump"
  echo "Database replaced."
  trap - EXIT
  echo "Starting $web ..."
  ssh "$SERVER" "docker start $web" >/dev/null
fi

# 5. Media
if [ "$what" != db ]; then
  echo "Uploading media ..."
  ssh "$SERVER" "docker exec -i $web sh -c 'cat > /tmp/media-push.tgz'" < "$tgz"
  ssh "$SERVER" "docker exec -u root $web sh -c 'tar -tzf /tmp/media-push.tgz >/dev/null \
    && find $MEDIA_PATH -mindepth 1 -delete \
    && tar -xzf /tmp/media-push.tgz -C $MEDIA_PATH \
    && chown -R upstage:upstage $MEDIA_PATH && rm /tmp/media-push.tgz'"
  echo "Media replaced."
fi

echo "Done. The previous server data is in $OUT_DIR/server-before-push/"
