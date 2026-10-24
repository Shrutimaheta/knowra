#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set app_password="$APP_DB_PASSWORD" <<'EOSQL'
CREATE ROLE knowra_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE knowra TO knowra_app;
GRANT USAGE ON SCHEMA public TO knowra_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO knowra_app;
EOSQL
