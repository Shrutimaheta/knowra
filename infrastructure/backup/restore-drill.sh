#!/bin/bash
# Run only against an isolated PostgreSQL server with a mounted encrypted backup.
set -euo pipefail
: "${RESTORE_DRILL_ACK:?Set RESTORE_DRILL_ACK=isolated-server after choosing an isolated server}"
[[ "$RESTORE_DRILL_ACK" == isolated-server ]]
[[ -f /restore/identity.txt && -f /restore/backup.dump.age ]]
target="knowra_restore_$(date -u +%Y%m%d%H%M%S)_$$"
createdb "$target"
# Keep a failed drill database for diagnosis. Never touch an existing database.
age -d -i /restore/identity.txt /restore/backup.dump.age | pg_restore --exit-on-error --no-owner --no-acl --dbname "$target"
psql --dbname "$target" --no-psqlrc --tuples-only --command 'SELECT version_num FROM alembic_version; SELECT COUNT(*) AS documents FROM documents; SELECT COUNT(*) AS originals FROM document_versions WHERE original IS NOT NULL;'
echo "Restore drill completed into new database: $target"
echo 'Verify expected counts, checksums, source links and permissions before accepting this recovery point.'
