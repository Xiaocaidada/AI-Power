#!/bin/sh
set -eu

BACKUP_DIR=${BACKUP_DIR:-/backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
INTERVAL_SECONDS=${BACKUP_INTERVAL_SECONDS:-86400}

run_backup() {
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    target="$BACKUP_DIR/ai_power_${stamp}.dump"
    printf 'backup: writing %s\n' "$target"
    if pg_dump -Fc -f "$target"; then
        printf 'backup: completed\n'
        find "$BACKUP_DIR" -type f -name 'ai_power_*.dump' -mtime +"$RETENTION_DAYS" -print -delete
    else
        printf 'backup: failed\n' >&2
        rm -f "$target"
        return 1
    fi
}

mkdir -p "$BACKUP_DIR"

if [ "${RUN_ONCE:-0}" = "1" ]; then
    run_backup
    exit $?
fi

while true; do
    run_backup || true
    sleep "$INTERVAL_SECONDS"
done