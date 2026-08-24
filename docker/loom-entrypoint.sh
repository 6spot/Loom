#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    # The only mutable host bind mount owned by loom-server is its blob store.
    # PostgreSQL data is a separate service and is never touched here.
    install -d -o loom -g loom -m 0755 /var/lib/loom/blobs
    chown loom:loom /var/lib/loom/blobs
    exec su -s /bin/sh loom -c 'exec /usr/local/bin/loom-server "$@"' -- "$@"
fi

exec /usr/local/bin/loom-server "$@"
