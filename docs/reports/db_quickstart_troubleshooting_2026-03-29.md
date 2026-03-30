# Database Quickstart & Troubleshooting Runbook

## 1. Quick Health Check
Run either of these to confirm the DB is up and the credentials are correct:
```powershell
# PowerShell version
powershell.exe -File scripts/check_db_health.ps1

# Python version
python scripts/check_db_health.py
```

## 2. Common Issues
| Symptom | Probable Cause | Fix |
|---|---|---|
| `OperationalError: connection to server at "localhost" (::1), port 5432 failed: Connection refused` | PostgreSQL service stopped | Run `Start-Service -Name "postgresql*"` in an admin shell. |
| `psycopg2.OperationalError: password authentication failed for user "postgres"` | Incorrect password in `db_config.py` | Update `db_config.py` with the correct password (current: `test123`). |
| `psycopg2.OperationalError: database "kensington" does not exist` | Database not created | Run `psql -c "CREATE DATABASE kensington;"` |
| `ImportError: No module named 'psycopg2'` | `psycopg2` missing | Run `pip install psycopg2-binary` |

## 3. Starting the Service
If the health check fails on the service step:
```powershell
Get-Service -Name *postgres* | Start-Service
```

## 4. Environment Overrides
The project respects standard PostgreSQL environment variables:
- `PGHOST` (default: localhost)
- `PGPORT` (default: 5432)
- `PGDATABASE` (default: kensington)
- `PGUSER` (default: postgres)
- `PGPASSWORD` (default: test123)
