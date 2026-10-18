#!/usr/bin/env bash
# Download the database (pg_dump, custom format) and the media files from the Coolify server.
#
# Usage:  scripts/pull_from_server.sh [db|media|all]      (default: all)
#
# Settings (environment variables, or put them in scripts/.server.env, which is git-ignored):
#   SERVER       ssh target                         default root@coolify.iskt.co.uk
#   WEB_FILTER   docker name filter for the web container (Coolify uuid, e.g. web-<uuid>)  REQUIRED
#   DB_FILTER    docker name filter for the database container (e.g. db-<uuid>)            REQUIRED
#   OUT_DIR      where to save the files            default ./backups
#   MEDIA_PATH   media directory in the web container   default /data/media
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f scripts/.server.env ] && . scripts/.server.env

SERVER=${SERVER:-root@coolify-server}
OUT_DIR=${OUT_DIR:-backups}
MEDIA_PATH=${MEDIA_PATH:-/data/media}
: "${WEB_FILTER:?Set WEB_FILTER (docker name filter for the web container)}"
: "${DB_FILTER:?Set DB_FILTER (docker name filter for the database container)}"

what=${1:-all}
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT_DIR"

# Find a running container by name filter on the server
find_container() {
  local c
  c=$(ssh "$SERVER" "docker ps --filter 'name=$1' --format '{{.Names}}' | head -1")
  [ -n "$c" ] || { echo "No running container matches '$1'" >&2; exit 1; }
  echo "$c"
}

pull_db() {
  local c out="$OUT_DIR/upstage-$stamp.dump"
  c=$(find_container "$DB_FILTER")
  echo "Dumping database from $c ..."
  # Credentials come from the container's own environment, so nothing is stored here
  ssh "$SERVER" "docker exec $c sh -c 'pg_dump -Fc -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'" > "$out"
  echo "Saved $out ($(du -h "$out" | cut -f1))"
}

pull_media() {
  local c out="$OUT_DIR/media-$stamp.tgz"
  c=$(find_container "$WEB_FILTER")
  echo "Archiving media from $c:$MEDIA_PATH ..."
  ssh "$SERVER" "docker exec $c tar -czf - -C $MEDIA_PATH ." > "$out"
  echo "Saved $out ($(du -h "$out" | cut -f1))"
}

case "$what" in
  db) pull_db ;;
  media) pull_media ;;
  all) pull_db; pull_media ;;
  *) echo "Usage: $0 [db|media|all]" >&2; exit 1 ;;
esac
