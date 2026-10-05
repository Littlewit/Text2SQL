# Seed the demo business database inside the dev postgres container.
# Usage: powershell -ExecutionPolicy Bypass -File backend/scripts/seed_demo_business.ps1
#
# NOTE: SQL file is copied into the container and executed there
# (piping through PowerShell mangles UTF-8 Chinese text on Windows).

$ErrorActionPreference = "Stop"
$SQL = Join-Path $PSScriptRoot "demo_business.sql"

docker cp $SQL t2s-postgres-dev:/tmp/demo_business.sql
docker exec t2s-postgres-dev psql -U t2s -d postgres -c "DROP DATABASE IF EXISTS demo_business;"
docker exec t2s-postgres-dev psql -U t2s -d postgres -c "CREATE DATABASE demo_business;"
docker exec t2s-postgres-dev psql -U t2s -d demo_business -v ON_ERROR_STOP=1 -f /tmp/demo_business.sql
docker exec t2s-postgres-dev rm /tmp/demo_business.sql
Write-Host "demo_business seeded."
