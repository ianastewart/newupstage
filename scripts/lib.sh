#!/usr/bin/env bash
# Shared by pull_from_server.sh, push_to_server.sh and copy_live_to_sandbox.sh (sourced, never run).
#
# The live site and the sandbox each have their own web and database containers on the same server. A "target" is
# "live" or "sandbox". Settings are read from these files (later ones override earlier ones):
#   scripts/.server.env           settings for both: SERVER, OUT_DIR, USE_COMPOSE_DB...  For the live site it can also
#                                 still hold WEB_FILTER, DB_FILTER and SERVER_DB, as it always has.
#   scripts/.server.<target>.env  WEB_FILTER, DB_FILTER, SERVER_DB (and, for the sandbox, SANDBOX_USERS) of that target.
#                                 Required for the sandbox. For live it replaces the ones in .server.env, if it exists.
# The sandbox never inherits the live containers: if its settings name the live containers the script refuses to run.

# An OUT_DIR given by the caller (e.g. OUT_DIR=backups/x pull_from_server.sh) beats the one in the settings files
_OUT_DIR_FROM_CALLER=${OUT_DIR-}

check_target() {
  case "${1:-}" in
    live | sandbox) ;;
    *) echo "Say which site: live or sandbox" >&2; exit 1 ;;
  esac
}

# Read the settings of a target into the current shell.
_load_env() {
  local t=$1 profile=scripts/.server.$1.env
  [ -f scripts/.server.env ] && . scripts/.server.env
  if [ -f "$profile" ]; then
    unset WEB_FILTER DB_FILTER SERVER_DB SANDBOX_USERS
    . "$profile"
  elif [ "$t" != live ]; then
    echo "Missing $profile (copy scripts/.server.sandbox.env.example and fill it in)" >&2
    exit 1
  fi
  SERVER=${SERVER:-root@coolify.iskt.co.uk}
  [ -z "$_OUT_DIR_FROM_CALLER" ] || OUT_DIR=$_OUT_DIR_FROM_CALLER
  OUT_DIR=${OUT_DIR:-backups}
  MEDIA_PATH=${MEDIA_PATH:-/data/media}
  : "${WEB_FILTER:?Set WEB_FILTER for $t (docker name filter for the web container)}"
  : "${DB_FILTER:?Set DB_FILTER for $t (docker name filter for the database container)}"
}

# One setting of a target, without disturbing the current shell:  target_setting live WEB_FILTER
target_setting() { (_load_env "$1"; printf '%s' "${!2-}"); }

# Read the settings of a target ("live" or "sandbox") into the current shell, and set TARGET.
load_target() {
  check_target "${1:-}"
  TARGET=$1
  _load_env "$TARGET"
  if [ "$TARGET" = sandbox ]; then
    local live_web live_db
    live_web=$(target_setting live WEB_FILTER)
    live_db=$(target_setting live DB_FILTER)
    if [ "$WEB_FILTER" = "$live_web" ] || [ "$DB_FILTER" = "$live_db" ]; then
      echo "The sandbox settings name the live containers (WEB_FILTER / DB_FILTER). Refusing to continue." >&2
      exit 1
    fi
  fi
}

# Find a running container on $SERVER by name filter.
find_container() {
  local c
  c=$(ssh "$SERVER" "docker ps --filter 'name=$1' --format '{{.Names}}' | head -1")
  [ -n "$c" ] || { echo "No running container matches '$1'" >&2; exit 1; }
  echo "$c"
}

# confirm_typed "what will happen" word yes   (yes=1 skips the question)
confirm_typed() {
  echo
  echo "$1"
  if [ "$3" = 1 ]; then
    echo "--yes given: continuing without the typed confirmation."
  else
    read -r -p "Type '$2' to continue: " answer
    [ "$answer" = "$2" ] || { echo "Cancelled."; exit 1; }
  fi
}

# After a database has been put into the sandbox: log everybody out (the sessions came from elsewhere) and put
# the SANDBOX_USERS (comma separated usernames) into the sandbox group. $1 is the running web container.
sandbox_after_db_restore() {
  local web=$1 tries=0 py
  until ssh "$SERVER" "docker exec $web python -c 'print(1)'" </dev/null >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 30 ] || { echo "The sandbox web container is not answering; skipped the sandbox group step" >&2; return 1; }
    sleep 2
  done
  py='import os; from django.contrib.auth.models import Group; from django.contrib.sessions.models import Session; from accounts.models import CustomUser; Session.objects.all().delete(); g, _ = Group.objects.get_or_create(name="sandbox"); [g.user_set.add(u) for u in CustomUser.objects.filter(username__in=[n.strip() for n in os.environ.get("SANDBOX_USERS", "").split(",") if n.strip()])]; print("Sandbox group:", sorted(u.username for u in g.user_set.all()))'
  ssh "$SERVER" "docker exec -e SANDBOX_USERS='${SANDBOX_USERS:-}' $web python manage.py shell -c '$py'" </dev/null
}
