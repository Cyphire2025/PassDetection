[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$containerName = 'coordinators-app-local-proxy'
$runningContainer = (@(& docker ps --quiet --filter "name=^/$containerName$") -join '').Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Docker is not available.'
}
if ([string]::IsNullOrWhiteSpace($runningContainer)) {
    Write-Output 'The temporary Android test proxy is not running.'
    exit 0
}

& docker stop --time 2 $containerName | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'The temporary Android test proxy could not be stopped.'
}
Write-Output 'Stopped and removed the temporary Android test proxy.'
