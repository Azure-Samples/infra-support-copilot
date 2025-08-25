Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-PublicIp {
	param()
	$endpoints = @(
		'https://api.ipify.org',          # plain text
		'https://ifconfig.me/ip',         # plain text
		'https://ipv4.icanhazip.com'      # plain text
	)
	foreach ($url in $endpoints) {
		try {
			$raw = (Invoke-RestMethod -Uri $url -TimeoutSec 5).ToString().Trim()
			if ($raw -match '^(?<ip>(?:[0-9]{1,3}\.){3}[0-9]{1,3})$') {
				return $Matches['ip']
			}
		} catch {
			Write-Verbose "Failed to get IP from $url : $_" | Out-Null
		}
	}
	throw 'Could not determine public IPv4 address from any endpoint.'
}

$ipAddress = Get-PublicIp
Write-Host "[preprovision] Detected public IPv4: $ipAddress" -ForegroundColor Cyan

# Persist into azd environment so parameter substitution works
try {
	azd env set CLIENT_PUBLIC_IP $ipAddress | Out-Null
	Write-Host "[preprovision] Set azd env variable CLIENT_PUBLIC_IP=$ipAddress" -ForegroundColor Green
} catch {
	Write-Warning "Failed to run 'azd env set'. Ensure Azure Developer CLI is installed and you are inside an azd environment. Error: $_"
	# Still export for current process (may help if provisioning invoked in same session)
	$env:CLIENT_PUBLIC_IP = $ipAddress
}

# Output for logs
Write-Output "Client public IP address: $ipAddress"
