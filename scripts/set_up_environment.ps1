param(
    [switch]$ForceSqlcmd,
    [string]$SqlcmdPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Section($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Fail($msg) { Write-Error $msg; exit 1 }

function Load-DotEnv {
    if (-not (Test-Path .env)) { return @{} }
    $h = @{}
    foreach ($line in Get-Content .env) {
        if ($line -match '^(#|\s*$)') { continue }
        $kv = $line -split '=',2
        if ($kv.Count -eq 2) { $h[$kv[0]] = ($kv[1].Trim().Trim('"').Trim("'")) }
    }
    return $h
}

function Save-AzdEnv {
    Write-Section 'Export azd env -> .env'
    azd env get-values > .env
}

function Run-DataIngestion {
    Write-Section 'Upload data to Blob & Search'
    python ./scripts/upload_data_to_blob_storage.py
    python ./scripts/create_index.py
    Write-Section 'Upload ARC data to Azure SQL'
    python ./scripts/upload_arc_data_to_azure_sql.py
}

try {
    Save-AzdEnv
    Run-DataIngestion
    $envMap = Load-DotEnv
    Write-Section "Target: $($envMap.AZURE_SQL_SERVER)/$($envMap.AZURE_SQL_DATABASE_NAME) (AppUser: $($envMap.AZURE_APP_SERVICE_NAME))"

    az ad directory-role member add --role "Directory Readers" --member-id $envMap.AZURE_SQL_SERVER_IDENTITY_PRINCIPAL_ID

    # Call Python script instead of PowerShell function
    Write-Section 'Ensure Database Users (Python)'

    # Always create database user for App Service Managed Identity (runtime authentication)
    Write-Host "Creating database user for App Service Managed Identity (runtime)" -ForegroundColor Green
    $appArgs = @(
        "./scripts/ensure_db_user.py",
        "--server", $envMap.AZURE_SQL_SERVER,
        "--database", $envMap.AZURE_SQL_DATABASE_NAME,
        "--app-name", $envMap.AZURE_APP_SERVICE_NAME,
        "--verbose"
    )
    
    python @appArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "App Service Managed Identity database user creation failed with exit code $LASTEXITCODE"
    }
}
catch {
    Write-Error "FAILED: $($_.Exception.Message)"
    exit 1
}
