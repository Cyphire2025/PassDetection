[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$artifactDirectory = Join-Path $projectDirectory 'artifacts'
$sourceApk = Join-Path $projectDirectory 'app\build\outputs\apk\local\debug\app-local-debug.apk'
$targetApk = Join-Path $artifactDirectory 'CoordinatorApp-local-debug.apk'

Push-Location $projectDirectory
try {
    & '.\gradlew.bat' --no-daemon `
        testLocalDebugUnitTest `
        lintLocalDebug `
        assembleLocalDebug
    if ($LASTEXITCODE -ne 0) {
        throw "The local Android build failed."
    }

    New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
    Copy-Item -LiteralPath $sourceApk -Destination $targetApk -Force
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetApk).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$targetApk.sha256" -Value "$hash  CoordinatorApp-local-debug.apk"
    Write-Output $targetApk
} finally {
    Pop-Location
}
