#!/bin/bash
# Runs once, on first initialisation of the postgres volume.
#
# Prefect keeps its own orchestration tables. Giving it a separate database keeps them
# out of the APIx schema, so `alembic upgrade head` and Alembic's autogenerate only ever
# see APIx tables.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE DATABASE prefect OWNER $POSTGRES_USER;
SQL

echo "created database: prefect"
