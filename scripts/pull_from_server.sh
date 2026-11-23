#!/usr/bin/env bash
# Download the database (pg_dump, custom format) and the media files of the live site or the sandbox.
#
# Usage:  scripts/pull_from_server.sh <live|sandbox> [db|media|all]      (default: all)
#
# Files are saved in OUT_DIR as upstage-<site>-<time>.dump and media-<site>-<time>.tgz.
#
# Settings: see scripts/lib.sh (scripts/.server.env, scripts/.server.<live|sandbox>.env, or environment variables):
#   SERVER       ssh target                         default root@coolify.iskt.co.uk
#   SERVER_DB    the database the app uses on the server (Coolify's postgres container has POSTGRES_DB=postgres)  default $POSTGRES_DB
#   WEB_FILTER   docker name filter for the web container (Coolify uuid, e.g. web-<uuid>)  REQUIRED
#   DB_FILTER    docker name filter for the database container (e.g. db-<uuid>)            REQUIRED
#   OUT_DIR      where to save the files            default ./backups
#   MEDIA_PATH   media directory in the web container   default /data/media
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/lib.sh

usage() { echo "Usage: $0 <live|sandbox> [db|media|all]" >&2; exit 1; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
load_target "$1"
what=${2:-all}
case "$what" in db | media | all) ;; *) usage ;; esac

stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT_DIR"

pull_db() {
  local c out="$OUT_DIR/upstage-$TARGET-$stamp.dump"
  c=$(find_container "$DB_FILTER")
  echo "Dumping the $TARGET database from $c ..."
  # Credentials come from the container's own environment, so nothing is stored here
  ssh "$SERVER" "docker exec $c sh -c 'pg_dump -Fc -U \"\$POSTGRES_USER\" -d \"${SERVER_DB:-\$POSTGRES_DB}\"'" > "$out"
  [ -s "$out" ] || { rm -f "$out"; echo "The dump is empty; something went wrong" >&2; exit 1; }
  echo "Saved $out ($(du -h "$out" | cut -f1))"
}

pull_media() {
  local c out="$OUT_DIR/media-$TARGET-$stamp.tgz"
  c=$(find_container "$WEB_FILTER")
  echo "Archiving the $TARGET media from $c:$MEDIA_PATH ..."
  ssh "$SERVER" "docker exec $c tar -czf - -C $MEDIA_PATH ." > "$out"
  tar -tzf "$out" >/dev/null || { rm -f "$out"; echo "The archive is damaged; something went wrong" >&2; exit 1; }
  echo "Saved $out ($(du -h "$out" | cut -f1))"
}

case "$what" in
  db) pull_db ;;
  media) pull_media ;;
  all) pull_db; pull_media ;;
esac
