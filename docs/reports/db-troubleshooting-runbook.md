# PostgreSQL/PostGIS Connectivity Runbook

## Fixed Local Development Settings
- Host: `localhost`
- Port: `5432`
- Database: `kensington`
- User: `postgres`
- Password: `test123`
- Windows service: `postgresql-x64-18`

## Current Known-Good State (2026-03-29)
- PostgreSQL service status: `Running`
- TCP listener: `0.0.0.0:5432` and `[::]:5432`
- Active config file: `C:/Program Files/PostgreSQL/18/data/postgresql.conf`
- Active HBA file: `C:/Program Files/PostgreSQL/18/data/pg_hba.conf`
- `postgresql.conf`: `listen_addresses = '*'`, `port = 5432`
- `pg_hba.conf` localhost auth:
  - `host all all 127.0.0.1/32 scram-sha-256`
  - `host all all ::1/128 scram-sha-256`

## Repeatable Checks (PowerShell)
1. Service and listener
```powershell
Get-Service -Name postgresql-x64-18
Get-NetTCPConnection -LocalPort 5432 -State Listen
Test-NetConnection -ComputerName localhost -Port 5432
```

2. `psql` availability
```powershell
Get-Command psql
psql --version
```

3. Authentication + connectivity
```powershell
$env:PGPASSWORD = 'test123'
psql -h localhost -p 5432 -U postgres -d kensington -v ON_ERROR_STOP=1 -c "select 1 as ok;"
psql "host=localhost port=5432 dbname=kensington user=postgres password=test123" -v ON_ERROR_STOP=1 -c "select current_database(), current_user;"
```

4. DB integrity checks for this project
```powershell
$env:PGPASSWORD = 'test123'
psql -h localhost -p 5432 -U postgres -d kensington -v ON_ERROR_STOP=1 -c "select version();"
psql -h localhost -p 5432 -U postgres -d kensington -v ON_ERROR_STOP=1 -c "select extname, extversion from pg_extension where extname like 'postgis%';"
psql -h localhost -p 5432 -U postgres -d kensington -v ON_ERROR_STOP=1 -c "select to_regclass('public.building_assessment'), to_regclass('opendata.building_footprints'), to_regclass('opendata.massing_3d'), to_regclass('opendata.road_centerlines');"
```

5. Project script verification
```powershell
python scripts/audit_storefront_conflicts.py
python scripts/export_db_params.py --address "22 Lippincott St"
```

## Minimal Safe Recovery
If connection is refused on `localhost:5432`:
```powershell
Start-Service -Name postgresql-x64-18
```
Then rerun the checks above in order.

## Safety Notes
- Do not run destructive SQL (`DROP DATABASE`, `DROP TABLE`, destructive migrations) as part of connectivity recovery.
- Prefer service/startup and local auth verification before changing database configuration.
