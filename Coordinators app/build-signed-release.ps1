[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$requiredVariables = @(
    'COORDINATOR_KEYSTORE_FILE',
    'COORDINATOR_KEYSTORE_PASSWORD',
    'COORDINATOR_KEY_ALIAS',
    'COORDINATOR_KEY_PASSWORD'
)
$missingVariables = $requiredVariables | Where-Object {
    [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_))
}
if ($missingVariables.Count -gt 0) {
    throw "Release signing is required. Missing: $($missingVariables -join ', ')"
}

$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$artifactDirectory = Join-Path $projectDirectory 'artifacts'
$sourceApk = Join-Path $projectDirectory 'app\build\outputs\apk\production\release\app-production-release.apk'
$targetApk = Join-Path $artifactDirectory 'CoordinatorApp-release.apk'

Push-Location $projectDirectory
try {
    & '.\gradlew.bat' --no-daemon `
        testProductionDebugUnitTest `
        lintProductionRelease `
        assembleProductionRelease
    if ($LASTEXITCODE -ne 0) {
        throw "The signed release Android build failed."
    }

    New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
    Copy-Item -LiteralPath $sourceApk -Destination $targetApk -Force
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetApk).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$targetApk.sha256" -Value "$hash  CoordinatorApp-release.apk"
    Write-Output $targetApk
} finally {
    Pop-Location
}
