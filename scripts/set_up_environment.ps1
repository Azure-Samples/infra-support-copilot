param(
    [switch]$ForceSqlcmd,
    [string]$SqlcmdPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Section($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Fail($msg) { Write-Error $msg; exit 1 }

# CI環境（GitHub Actions等）を検出
function Test-CiEnvironment {
    return ($env:CI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true' -or $env:TF_BUILD -eq 'True')
}

# CI環境では統合認証が使用できないため、情報を表示
$isCI = Test-CiEnvironment
if ($isCI) {
    Write-Section 'CI Environment Detected'
    Write-Host "Running in CI environment - will prioritize token-based authentication" -ForegroundColor Yellow
    Write-Host "Environment variables detected:" -ForegroundColor Gray
    @('CI', 'GITHUB_ACTIONS', 'TF_BUILD') | ForEach-Object {
        $val = [Environment]::GetEnvironmentVariable($_)
        if ($val) { Write-Host "  $_=$val" -ForegroundColor Gray }
    }
}

# CI環境でのサービスプリンシパル情報取得
function Get-CurrentPrincipal {
    $isCI = Test-CiEnvironment
    if ($isCI) {
        # CI環境ではサービスプリンシパルのObject IDを取得
        try {
            $spInfo = az ad signed-in-user show --query objectId -o tsv 2>$null
            if (-not $spInfo) {
                # サービスプリンシパル情報を別の方法で取得
                $accountInfo = az account show --query user -o json | ConvertFrom-Json
                if ($accountInfo.type -eq "servicePrincipal") {
                    Write-Host "Service Principal detected: $($accountInfo.name)" -ForegroundColor Yellow
                    return $accountInfo.name  # サービスプリンシパルのObject ID
                }
            }
            return $spInfo
        }
        catch {
            Write-Warning "Could not determine current principal in CI environment"
            return $null
        }
    }
    return $null  # ローカル環境では従来の App Service名を使用
}

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

function Get-RequiredValues($envMap) {
    $required = 'AZURE_APP_SERVICE_NAME','AZURE_SQL_SERVER','AZURE_SQL_DATABASE_NAME'
    foreach ($k in $required) { if (-not $envMap[$k]) { Fail "Missing $k in .env" } }
    
    # CI環境では適切なプリンシパルを使用
    $isCI = Test-CiEnvironment
    $principalName = $envMap.AZURE_APP_SERVICE_NAME
    
    if ($isCI) {
        $currentPrincipal = Get-CurrentPrincipal
        if ($currentPrincipal) {
            Write-Host "CI Environment: Using Service Principal ID instead of App Service name" -ForegroundColor Yellow
            Write-Host "  App Service Name: $($envMap.AZURE_APP_SERVICE_NAME)" -ForegroundColor Gray
            Write-Host "  Service Principal: $currentPrincipal" -ForegroundColor Yellow
            $principalName = $currentPrincipal
        }
    }
    
    return [PSCustomObject]@{
        AppName = $principalName
        SqlServer = $envMap.AZURE_SQL_SERVER
        Database = $envMap.AZURE_SQL_DATABASE_NAME
        IsServicePrincipal = $isCI
    }
}

function Get-AadSqlToken {
    $token = az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv 2>$null
    if (-not $token) { Fail 'Failed to get AAD access token (az account get-access-token)' }
    return $token
}

function Build-Tsql($appName, $isServicePrincipal = $false) {
    $escaped = ($appName -replace '\]', ']]')
    $identifier = "[$escaped]"
    
    # サービスプリンシパルかApp Serviceかでコメントを変更
    $principalType = if ($isServicePrincipal) { "Service Principal" } else { "App Service Managed Identity" }
    
@"
-- Create $principalType user: $appName
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$appName')
BEGIN
    CREATE USER $identifier FROM EXTERNAL PROVIDER;
    PRINT 'Created user: $appName';
END
ELSE
BEGIN
    PRINT 'User already exists: $appName';
END;

IF NOT EXISTS (
  SELECT 1 FROM sys.database_role_members rm
  JOIN sys.database_principals r ON rm.role_principal_id = r.principal_id
  JOIN sys.database_principals m ON rm.member_principal_id = m.principal_id
  WHERE r.name = N'db_datareader' AND m.name = N'$appName'
)
BEGIN
    ALTER ROLE db_datareader ADD MEMBER $identifier;
    PRINT 'Added to db_datareader: $appName';
END
ELSE
BEGIN
    PRINT 'Already member of db_datareader: $appName';
END;
"@
}

function Find-Sqlcmd {
    param([string]$Hint)
    if ($Hint -and (Test-Path -LiteralPath $Hint)) { return (Resolve-Path -LiteralPath $Hint).Path }
    $cmd = Get-Command sqlcmd -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if ($cmd) { return $cmd }
    $candidates = @(
        "$env:ProgramFiles\sqlcmd\sqlcmd.exe",
        "$env:LOCALAPPDATA\Programs\sqlcmd\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQLCMD\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\160\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles(x86)\Microsoft SQL Server\150\Tools\Binn\sqlcmd.exe"
    )
    foreach ($p in $candidates) { if (Test-Path -LiteralPath $p) { return $p } }
    return $null
}

function Invoke-With-InvokeSqlcmd {
    param($server,$db,$token,$query)
    $cmd = Get-Command Invoke-Sqlcmd -ErrorAction SilentlyContinue
    if (-not $cmd) { return $false }
    if (-not $cmd.Parameters['AccessToken']) { return $false }
    Write-Section 'Execute T-SQL via Invoke-Sqlcmd (AccessToken)'
    Invoke-Sqlcmd -ServerInstance $server -Database $db -AccessToken $token -Query $query
    return $true
}

function Invoke-With-Sqlcmd {
    param($server,$db,$token,$query,[string]$SqlcmdPath)
    $sqlcmd = Find-Sqlcmd -Hint $SqlcmdPath
    if (-not $sqlcmd) { Fail 'sqlcmd not found. Install Microsoft sqlcmd (winget install Microsoft.sqlcmd) & ODBC Driver 18.' }
    Write-Section 'Execute T-SQL via sqlcmd'
    
    # ツール情報をログ出力
    $sqlcmdVersion = & $sqlcmd -? 2>&1 | Out-String
    Write-Host "Using sqlcmd at: $sqlcmd" -ForegroundColor Gray
    
    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $query -Encoding UTF8
    try {
        $isCI = Test-CiEnvironment
        $supportsAccessToken = $sqlcmdVersion -match '--access-token'
        
        Write-Host "CI Environment: $isCI" -ForegroundColor Gray
        Write-Host "Supports --access-token: $supportsAccessToken" -ForegroundColor Gray
        
        if ($supportsAccessToken) {
            Write-Host "Using --access-token authentication (most reliable)" -ForegroundColor Green
            & $sqlcmd --access-token $token -S $server -d $db -C -b -l 30 -i $tmp
        } elseif ($isCI) {
            # CI環境で古いsqlcmdの場合、エラーメッセージを改善
            Write-Warning "CI environment detected but sqlcmd doesn't support --access-token"
            Write-Warning "This may fail with ActiveDirectoryIntegrated error. Consider updating sqlcmd."
            Write-Host "Attempting -G (Interactive) authentication..." -ForegroundColor Yellow
            & $sqlcmd -S $server -d $db -G -C -b -l 30 -i $tmp
        } else {
            Write-Host "Using -G (Azure AD) authentication" -ForegroundColor Yellow
            & $sqlcmd -S $server -d $db -G -C -b -l 30 -i $tmp
        }
    }
    finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

function Ensure-DbUser {
    param($info)
    $token = Get-AadSqlToken
    $query = Build-Tsql -appName $info.AppName -isServicePrincipal $info.IsServicePrincipal
    $isCI = Test-CiEnvironment
    
    Write-Host "Creating database user for: $($info.AppName)" -ForegroundColor Cyan
    if ($info.IsServicePrincipal) {
        Write-Host "  Type: Service Principal (CI Environment)" -ForegroundColor Yellow
    } else {
        Write-Host "  Type: App Service Managed Identity" -ForegroundColor Green
    }
    
    # CI環境では積極的にInvoke-Sqlcmdを試行（AccessToken使用）
    if (-not $ForceSqlcmd) {
        $ok = $false
        try { 
            $ok = Invoke-With-InvokeSqlcmd -server $info.SqlServer -db $info.Database -token $token -query $query 
        }
        catch {
            Write-Warning "Invoke-Sqlcmd failed: $($_.Exception.Message)"
            if ($isCI) {
                Write-Warning "This is expected in CI if SqlServer module is not properly installed"
            }
        }
        if ($ok) { Write-Host 'Done.' -ForegroundColor Green; return }
        Write-Host 'Falling back to sqlcmd...' -ForegroundColor Yellow
    }
    
    # CI環境での警告メッセージ
    if ($isCI) {
        Write-Warning "CI Environment: sqlcmd fallback may fail if --access-token is not supported"
        Write-Host "Ensure SqlServer PowerShell module (>=22.x) is installed for best results" -ForegroundColor Yellow
    }
    
    Invoke-With-Sqlcmd -server $info.SqlServer -db $info.Database -token $token -query $query -SqlcmdPath $SqlcmdPath
    Write-Host 'Done.' -ForegroundColor Green
}

try {
    Save-AzdEnv
    Run-DataIngestion
    $envMap = Load-DotEnv
    $info = Get-RequiredValues -envMap $envMap
    Write-Section "Target: $($info.SqlServer)/$($info.Database) (AppUser: $($info.AppName))"
    Ensure-DbUser -info $info
}
catch {
    Write-Error "FAILED: $($_.Exception.Message)"
    exit 1
}
