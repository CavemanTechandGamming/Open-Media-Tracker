#!/bin/sh
set -e
mkdir -p /config/cache/posters /config/logs
chown -R appuser:appuser /config 2>/dev/null || true
exec runuser -u appuser -- "$@"
