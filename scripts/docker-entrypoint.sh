#!/bin/sh
set -e

# Named volume /vol/web is mounted at runtime and may be owned by a user
# Nginx cannot read (alpine worker is UID 101). Fix permissions as root,
# then drop to django-user before running migrate/collectstatic/gunicorn.
mkdir -p /vol/web/static /vol/web/media

if [ "$(id -u)" = "0" ]; then
    chown -R django-user:django-user /vol/web
    chmod -R a+rX /vol/web
    exec gosu django-user "$0" "$@"
fi

exec "$@"
