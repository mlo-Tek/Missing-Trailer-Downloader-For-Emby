#!/bin/sh
set -eu

PUID="${PUID:-99}"
PGID="${PGID:-100}"

if [ "$(id -u)" = "0" ]; then
    if ! getent group mtde >/dev/null 2>&1; then
        groupadd -o -g "$PGID" mtde
    fi
    if ! id mtde >/dev/null 2>&1; then
        useradd -o -u "$PUID" -g "$PGID" -d /app -s /usr/sbin/nologin mtde
    fi

    mkdir -p /config /cookies
    # Do not recursively chown /media: media ownership belongs to the host.
    chown -R "$PUID:$PGID" /config 2>/dev/null || true
    exec gosu "$PUID:$PGID" mtde "$@"
fi

exec mtde "$@"
