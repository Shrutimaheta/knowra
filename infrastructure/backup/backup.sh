#!/bin/bash
set -euo pipefail
umask 077
: "${BACKUP_RECIPIENT:?Set the age public recipient; keep its private key off this server}"
: "${PGPASSWORD:?Set the database password}"
mkdir -p /backups
run_backup() {
    local stamp target temporary
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    target="/backups/knowra-${stamp}-$$.dump.age"
    temporary="${target}.partial"
    if pg_dump --format=custom --no-owner --no-acl | age -r "$BACKUP_RECIPIENT" > "$temporary"; then
        mv -- "$temporary" "$target"
        date -u +%s > /backups/last-success
        chmod 644 /backups/last-success
        echo "Encrypted backup completed: $stamp"
    else
        rm -f -- "$temporary"
        echo 'Encrypted backup failed' >&2
        return 1
    fi
}
if [[ "${1:-}" == once ]]; then
    run_backup
    exit
fi
while true; do
    if run_backup; then
        sleep "${BACKUP_INTERVAL_SECONDS:-86400}"
    else
        sleep 300
    fi
done
