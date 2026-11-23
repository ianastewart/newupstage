#!/usr/bin/env bash
# REPLACE the sandbox's database and/or media with a copy of the live site's.  The live site is only read, never changed.
# There is deliberately no script that copies the other way.
#
# Usage:  scripts/copy_live_to_sandbox.sh [--dry-run] [--yes] [db|media|all]      (default: all)
#   --dry-run   check both sites' containers, but change nothing
#   --yes       skip the typed confirmation; the sandbox is still backed up first
#
# What it does (the data goes from one container to the other on the server; nothing is downloaded):
#   1. finds the live and sandbox containers and refuses if they are the same, or on different servers
#   2. saves the sandbox's current database and media to backups/sandbox-before-copy/ (using pull_from_server.sh)
#   3. asks you to type "sandbox" to confirm
#   4. database: stops the sandbox web container, restores live's dump in ONE transaction (a failure leaves the old
#      data in place), starts it again; then logs everyone out and puts SANDBOX_USERS into the sandbox group
#   5. media: archives live's media on the server, checks it, then empties the sandbox's media and unpacks it
#
# Settings: scripts/.server.env, scripts/.server.live.env (if you have one) and scripts/.server.sandbox.env: see scripts/lib.sh.
# The live site's data (users, e-mail addresses, password hashes) ends up in the sandbox: only let people you trust into it.
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/lib.sh

usage() { echo "Usage: $0 [--dry-run] [--yes] [db|media|all]" >&2; exit 1; }

dry=0
yes=0
while [ "${1:-}" = "--dry-run" ] || [ "${1:-}" = "--yes" ]; do
  [ "$1" = "--dry-run" ] && dry=1
  [ "$1" = "--yes" ] && yes=1
  shift
done
[ $# -le 1 ] || usage
what=${1:-all}
case "$what" in db | media | all) ;; *) usage ;; esac
case "$what" in db) what_text=database ;; all) what_text="database and media" ;; *) what_text=$what ;; esac

# The live site's settings first, then the sandbox's (the ones left in the shell are the sandbox's)
live_server=$(target_setting live SERVER)
live_web_filter=$(target_setting live WEB_FILTER)
live_db_filter=$(target_setting live DB_FILTER)
live_db_name=$(target_setting live SERVER_DB)
live_media=$(target_setting live MEDIA_PATH)
load_target sandbox
[ "$live_server" = "$SERVER" ] || { echo "Live is on $live_server but the sandbox on $SERVER: this script needs one server" >&2; exit 1; }

live_web=$(find_container "$live_web_filter")
live_db=$(find_container "$live_db_filter")
sb_web=$(find_container "$WEB_FILTER")
sb_db=$(find_container "$DB_FILTER")
if [ "$live_web" = "$sb_web" ] || [ "$live_db" = "$sb_db" ]; then
  echo "Live and sandbox resolve to the same container. Refusing to continue." >&2
  exit 1
fi
echo "Server $SERVER"
echo "  live:    web $live_web, database $live_db"
echo "  sandbox: web $sb_web, database $sb_db"

if [ "$dry" = 1 ]; then
  echo "Dry run: nothing changed."
  exit 0
fi

# 2. Back up the sandbox
echo "Backing up the sandbox first ..."
OUT_DIR="$OUT_DIR/sandbox-before-copy" "$(dirname "$0")/pull_from_server.sh" sandbox "$what"

# 3. Confirm
confirm_typed "This will REPLACE the SANDBOX's $what_text on $SERVER with a copy of the LIVE site's." sandbox "$yes"

# 4. Database
if [ "$what" != media ]; then
  live_user=$(ssh "$SERVER" "docker exec $live_db printenv POSTGRES_USER")
  sb_user=$(ssh "$SERVER" "docker exec $sb_db printenv POSTGRES_USER")
  live_name=${live_db_name:-$(ssh "$SERVER" "docker exec $live_db printenv POSTGRES_DB")}
  sb_name=${SERVER_DB:-$(ssh "$SERVER" "docker exec $sb_db printenv POSTGRES_DB")}
  echo "Stopping $sb_web ..."
  ssh "$SERVER" "docker stop $sb_web" >/dev/null
  # Always start the sandbox again, even if the restore fails
  trap 'echo "Starting $sb_web ..."; ssh "$SERVER" "docker start $sb_web" >/dev/null' EXIT
  echo "Copying the database ..."
  ssh "$SERVER" "bash -o pipefail -c 'docker exec $live_db pg_dump -Fc -U $live_user -d $live_name | docker exec -i $sb_db pg_restore --single-transaction --exit-on-error --clean --if-exists --no-owner --no-privileges -U $sb_user -d $sb_name'"
  echo "Database copied."
  trap - EXIT
  echo "Starting $sb_web ..."
  ssh "$SERVER" "docker start $sb_web" >/dev/null
  sandbox_after_db_restore "$sb_web"
fi

# 5. Media: through a temporary file on the server, so the archive is checked before anything is deleted
if [ "$what" != db ]; then
  echo "Copying the media ..."
  ssh "$SERVER" bash -s <<EOS
set -euo pipefail
tmp=\$(mktemp /tmp/media-copy.XXXXXX)
trap 'rm -f "\$tmp"' EXIT
docker exec $live_web tar -czf - -C $live_media . > "\$tmp"
tar -tzf "\$tmp" >/dev/null
docker exec -i -u root $sb_web sh -c 'find $MEDIA_PATH -mindepth 1 -delete && tar -xzf - -C $MEDIA_PATH && chown -R upstage:upstage $MEDIA_PATH' < "\$tmp"
EOS
  echo "Media copied."
fi

echo "Done. The previous sandbox data is in $OUT_DIR/sandbox-before-copy/"
