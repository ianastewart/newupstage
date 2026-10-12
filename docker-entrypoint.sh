#!/bin/sh
# Bring the database up to date, then run the command (gunicorn).
set -e
python manage.py migrate --noinput
exec "$@"
