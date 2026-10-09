#!/usr/bin/env bash
set -Eeuo pipefail

# Runs once, on an empty data directory (ADR-005): migrations run as whadio_owner, which owns the
# schema; the application connects as whadio_app, which may only read and write rows.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" \
    -v owner_password="$WHADIO_DB_OWNER_PASSWORD" \
    -v app_password="$WHADIO_DB_APP_PASSWORD" <<'SQL'
CREATE ROLE whadio_owner LOGIN PASSWORD :'owner_password';
CREATE ROLE whadio_app LOGIN PASSWORD :'app_password';
CREATE DATABASE whadio OWNER whadio_owner;
\connect whadio
ALTER SCHEMA public OWNER TO whadio_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO whadio_app;
ALTER DEFAULT PRIVILEGES FOR ROLE whadio_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO whadio_app;
ALTER DEFAULT PRIVILEGES FOR ROLE whadio_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO whadio_app;
SQL
