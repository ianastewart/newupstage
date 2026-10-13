#!/bin/sh
# Start as root just to make the uploads folder writable, then drop to the app user, bring the database up to date,
# and run the command (gunicorn).
set -e
chown upstage:upstage /data/media
exec setpriv --reuid=upstage --regid=upstage --init-groups sh -c 'python manage.py migrate --noinput && exec "$@"' sh "$@"
