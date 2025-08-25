azd env get-values > .env
Write-Output "Generate .env file"
python ./scripts/upload_data_to_blob_storage.py
python ./scripts/create_index.py
Write-Output "Uploading to SQL Database..."
python ./scripts/upload_arc_data_to_azure_sql.py

param(
    [switch]$ForceSqlcmd,
    [string]$SqlcmdPath
)

$AZURE_APP_SERVICE_NAME = (Get-Content .env | Where-Object { $_ -match "^AZURE_APP_SERVICE_NAME=" } | ForEach-Object { $_ -replace "^AZURE_APP_SERVICE_NAME=", "" } | Select-Object -First 1)
$AZURE_APP_SERVICE_NAME = $AZURE_APP_SERVICE_NAME.Trim().Trim('"').Trim("'")
Write-Output "App Service Name: $AZURE_APP_SERVICE_NAME"

$AZURE_SQL_SERVER = (Get-Content .env | Where-Object { $_ -match "^AZURE_SQL_SERVER=" } | ForEach-Object { $_ -replace "^AZURE_SQL_SERVER=", "" } | Select-Object -First 1)
$AZURE_SQL_SERVER = $AZURE_SQL_SERVER.Trim().Trim('"').Trim("'")
Write-Output "SQL Server: $AZURE_SQL_SERVER"

$AZURE_SQL_DATABASE_NAME = (Get-Content .env | Where-Object { $_ -match "^AZURE_SQL_DATABASE_NAME=" } | ForEach-Object { $_ -replace "^AZURE_SQL_DATABASE_NAME=", "" } | Select-Object -First 1)
$AZURE_SQL_DATABASE_NAME = $AZURE_SQL_DATABASE_NAME.Trim().Trim('"').Trim("'")
Write-Output "SQL Database Name: $AZURE_SQL_DATABASE_NAME"

# Basic validations
if ([string]::IsNullOrWhiteSpace($AZURE_APP_SERVICE_NAME) -or [string]::IsNullOrWhiteSpace($AZURE_SQL_SERVER) -or [string]::IsNullOrWhiteSpace($AZURE_SQL_DATABASE_NAME)) {
    Write-Error "Missing one or more required values in .env (AZURE_APP_SERVICE_NAME / AZURE_SQL_SERVER / AZURE_SQL_DATABASE_NAME)."
    exit 1
}

# Escape the app service name for T-SQL identifier (handles '-') and closing brackets
$escapedName = $AZURE_APP_SERVICE_NAME -replace '\\]', ']]'
$sqlIdentifier = "[$escapedName]"

# Acquire AAD access token via Azure CLI for Azure SQL (resource = https://database.windows.net/)
$token = (& az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv) 2>$null
if (-not $token) {
    Write-Error "Failed to get AAD access token. Ensure 'az login' is completed and you have access to the SQL server."
    exit 1
}

# Idempotent T-SQL: create external user if not exists, add to db_datareader if not already member
$query = @"
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$AZURE_APP_SERVICE_NAME')
BEGIN
    CREATE USER $sqlIdentifier FROM EXTERNAL PROVIDER;
END;

IF NOT EXISTS (
  SELECT 1 FROM sys.database_role_members rm
  JOIN sys.database_principals r ON rm.role_principal_id = r.principal_id
  JOIN sys.database_principals m ON rm.member_principal_id = m.principal_id
  WHERE r.name = N'db_datareader' AND m.name = N'$AZURE_APP_SERVICE_NAME'
)
BEGIN
    ALTER ROLE db_datareader ADD MEMBER $sqlIdentifier;
END;
"@

Write-Output "Executing T-SQL against $AZURE_SQL_SERVER/$AZURE_SQL_DATABASE_NAME as AAD token user..."

# Prefer Invoke-Sqlcmd with -AccessToken when available; otherwise fall back to sqlcmd if installed.
$invokeSupportsAccessToken = ($null -ne ((Get-Command Invoke-Sqlcmd -ErrorAction SilentlyContinue).Parameters["AccessToken"]))

function Find-SqlcmdPath {
    param([string]$Hint)
    if ($Hint -and (Test-Path -LiteralPath $Hint)) { return (Resolve-Path -LiteralPath $Hint).Path }
    $candidates = @()
    $cmd = Get-Command sqlcmd -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if ($cmd) { $candidates += $cmd }
    $candidates += @(
        "$env:ProgramFiles\sqlcmd\sqlcmd.exe",
        "$env:LOCALAPPDATA\Programs\sqlcmd\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQLCMD\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\160\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles(x86)\Microsoft SQL Server\150\Tools\Binn\sqlcmd.exe"
    )
    foreach ($p in $candidates) { if ($p -and (Test-Path -LiteralPath $p)) { return $p } }
    return $null
}

if ($invokeSupportsAccessToken -and -not $ForceSqlcmd) {
    try {
        Invoke-Sqlcmd -ServerInstance $AZURE_SQL_SERVER -Database $AZURE_SQL_DATABASE_NAME -AccessToken $token -Query $query -ErrorAction Stop
        Write-Output "Done."
    }
    catch {
        Write-Warning ("Invoke-Sqlcmd failed: {0}" -f $_.Exception.Message)
        Write-Warning "Falling back to sqlcmd (-G) if available..."
        $sqlcmdPath = Find-SqlcmdPath -Hint $SqlcmdPath
        if ($sqlcmdPath) {
            $tmpFile = New-TemporaryFile
            Set-Content -Path $tmpFile -Value $query -Encoding UTF8
            try {
                & $sqlcmdPath -S $AZURE_SQL_SERVER -d $AZURE_SQL_DATABASE_NAME -G -C -b -l 30 -i $tmpFile
                Write-Output "Done (via sqlcmd)."
            }
            finally {
                Remove-Item $tmpFile -ErrorAction SilentlyContinue
            }
        }
        else {
            Write-Error "sqlcmd not found. Install 'Microsoft SQLCMD' and 'Microsoft ODBC Driver 18' or run with -ForceSqlcmd after installing."
            exit 1
        }
    }
}
else {
    $sqlcmdPath = Find-SqlcmdPath -Hint $SqlcmdPath
    if ($sqlcmdPath) {
        # Use sqlcmd with AAD integrated auth (-G). For Azure SQL, encryption is enforced; -C trusts the server cert.
        $tmpFile = New-TemporaryFile
        Set-Content -Path $tmpFile -Value $query -Encoding UTF8
        try {
            & $sqlcmdPath -S $AZURE_SQL_SERVER -d $AZURE_SQL_DATABASE_NAME -G -C -b -l 30 -i $tmpFile
            Write-Output "Done."
        }
        finally {
            Remove-Item $tmpFile -ErrorAction SilentlyContinue
        }
    }
    else {
        Write-Error "Neither Invoke-Sqlcmd with -AccessToken nor sqlcmd is available. Please update the 'SqlServer' module (>=22.x) or install 'Microsoft ODBC Driver 18 for SQL Server' (sqlcmd)."
        exit 1
    }
}
