<#
.SYNOPSIS
    Checks the health of the PostgreSQL/PostGIS database for the Kensington project.
.DESCRIPTION
    Verifies service status, port listening, authentication, and presence of required tables.
#>

$dbHost = "localhost"
$dbPort = 5432
$dbName = "kensington"
$dbUser = "postgres"
$psqlPath = "C:\Program Files\PostgreSQL\18\bin\psql.exe"

Write-Host "--- Database Health Check ---" -ForegroundColor Cyan

# 1. Check Service
$service = Get-Service -Name *postgres* -ErrorAction SilentlyContinue
if ($service -and $service.Status -eq "Running") {
    Write-Host "[PASS] PostgreSQL service is running ($($service.Name))." -ForegroundColor Green
} else {
    Write-Host "[FAIL] PostgreSQL service is NOT running." -ForegroundColor Red
    exit 1
}

# 2. Check Port
$portCheck = Get-NetTCPConnection -LocalPort $dbPort -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
if ($portCheck) {
    Write-Host "[PASS] Port $dbPort is listening (PID $($portCheck[0].OwningProcess))." -ForegroundColor Green
} else {
    Write-Host "[FAIL] Port $dbPort is NOT listening." -ForegroundColor Red
    exit 1
}

# 3. Check Authentication and PostGIS
$env:PGPASSWORD = "test123"
try {
    $authCheck = & $psqlPath -h $dbHost -U $dbUser -d $dbName -c "SELECT PostGIS_Version();" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[PASS] Authentication successful." -ForegroundColor Green
        Write-Host "[PASS] PostGIS extension present ($($authCheck[2])). " -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Authentication or PostGIS check failed (Exit Code: $LASTEXITCODE)." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "[FAIL] Error running psql: $_" -ForegroundColor Red
    exit 1
}

# 4. Check Required Tables
$tables = @(
    "public.building_assessment",
    "opendata.building_footprints",
    "opendata.massing_3d",
    "opendata.road_centerlines",
    "opendata.sidewalks"
)

foreach ($t in $tables) {
    & $psqlPath -h $dbHost -U $dbUser -d $dbName -c "SELECT 1 FROM $t LIMIT 1;" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[PASS] Table $t is queryable." -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Table $t is NOT queryable (Exit Code: $LASTEXITCODE)." -ForegroundColor Red
        exit 1
    }
}

Write-Host "`nDatabase health check completed successfully." -ForegroundColor Green
exit 0
