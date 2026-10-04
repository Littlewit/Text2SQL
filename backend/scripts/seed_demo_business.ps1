# Seed the demo business database inside the dev postgres container.
# Usage: powershell -ExecutionPolicy Bypass -File backend/scripts/seed_demo_business.ps1

$ErrorActionPreference = "Stop"
$SQL = Join-Path $PSScriptRoot "demo_business.sql"

docker exec -i t2s-postgres-dev psql -U t2s -d postgres -c "DROP DATABASE IF EXISTS demo_business;"
docker exec -i t2s-postgres-dev psql -U t2s -d postgres -c "CREATE DATABASE demo_business;"
Get-Content $SQL -Encoding UTF8 | docker exec -i t2s-postgres-dev psql -U t2s -d demo_business -v ON_ERROR_STOP=1
Write-Host "demo_business seeded."
