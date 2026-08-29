#!/bin/bash
# Creates the separate `airflow` database that the Airflow service points at.
#
# The postgres entrypoint only auto-creates the single database named by
# POSTGRES_DB (here: `flowstate`). Airflow's SQL_ALCHEMY_CONN in
# docker-compose.yml targets a second database, `airflow`, on the same
# cluster — without this script it never exists and the airflow container
# restart-loops on `database "airflow" does not exist`.
#
# Everything in /docker-entrypoint-initdb.d/ is executed once, when the data
# directory is first initialised. It does NOT re-run against an existing
# volume, hence the IF NOT EXISTS guard is expressed via a lookup rather than
# CREATE DATABASE IF NOT EXISTS (which Postgres does not support).
set -euo pipefail

AIRFLOW_DB="${AIRFLOW_POSTGRES_DB:-airflow}"

if psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -tAc "SELECT 1 FROM pg_database WHERE datname = '${AIRFLOW_DB}'" | grep -q 1; then
    echo "initdb: database '${AIRFLOW_DB}' already exists — nothing to do"
else
    echo "initdb: creating database '${AIRFLOW_DB}' owned by '${POSTGRES_USER}'"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        -c "CREATE DATABASE ${AIRFLOW_DB} OWNER ${POSTGRES_USER}"
fi
