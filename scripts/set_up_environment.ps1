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

try {
    Save-AzdEnv
    Run-DataIngestion
    $envMap = Load-DotEnv
    $info = Get-RequiredValues -envMap $envMap
    Write-Section "Target: $($info.SqlServer)/$($info.Database) (AppUser: $($info.AppName))"
    
    # Call Python script instead of PowerShell function
    Write-Section 'Ensure Database User (Python)'
    $pythonArgs = @(
        "./scripts/ensure_db_user.py",
        "--server", $info.SqlServer,
        "--database", $info.Database,
        "--app-name", $info.AppName
    )
    
    # Add verbose flag if CI environment
    if ($isCI) {
        $pythonArgs += "--verbose"
    }
    
    # Set environment variables for CI
    if ($isCI) {
        Write-Host "CI Environment detected - setting environment variables for Python script" -ForegroundColor Yellow
        $env:CI = 'true'
        $env:GITHUB_ACTIONS = $env:GITHUB_ACTIONS
        if ($env:AZURE_CLIENT_ID) {
            Write-Host "  AZURE_CLIENT_ID: $($env:AZURE_CLIENT_ID)" -ForegroundColor Gray
        }
    }
    
    python @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "Python database user creation script failed with exit code $LASTEXITCODE"
    }
}
catch {
    Write-Error "FAILED: $($_.Exception.Message)"
    exit 1
}
