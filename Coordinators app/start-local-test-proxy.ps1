[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$containerName = 'coordinators-app-local-proxy'
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectDirectory 'qa\nginx.conf'

$existingContainer = (@(& docker ps -a --quiet --filter "name=^/$containerName$") -join '').Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Docker is not available.'
}
if (-not [string]::IsNullOrWhiteSpace($existingContainer)) {
    throw "The temporary test proxy already exists: $containerName"
}

$networkName = (@(& docker inspect passdetection-frontend `
    --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}') -join '').Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($networkName)) {
    throw 'Start the PassDetection Docker stack before the Android test proxy.'
}

& docker run --rm --detach `
    --name $containerName `
    --network $networkName `
    --publish '127.0.0.1:3100:8080' `
    --volume "${configPath}:/etc/nginx/nginx.conf:ro" `
    'nginx:1.30.4-alpine'
if ($LASTEXITCODE -ne 0) {
    throw 'The temporary Android test proxy did not start.'
}

Write-Output 'Local coordinator test origin: http://localhost:3100/coordinator'
Write-Output "Temporary container: $containerName"
