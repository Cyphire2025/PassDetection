[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipSelfTest,
    [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path -Path $PSScriptRoot -ChildPath "Common.ps1")

Assert-WindowsHost

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path -Path $script:ArtifactsRoot -ChildPath "publish\win-x64"
}
else {
    $OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
    Assert-PathBelow -Candidate $OutputDirectory -Parent $script:ArtifactsRoot
}

if (-not $SkipTests) {
    & (Join-Path -Path $PSScriptRoot -ChildPath "test.ps1")
}
else {
    Invoke-LockedRestore
}

Reset-ArtifactDirectory -Path $OutputDirectory

Invoke-DotNet -Arguments @(
    "publish",
    $script:AppProjectPath,
    "--configuration", "Release",
    "--runtime", "win-x64",
    "--self-contained", "true",
    "--no-restore",
    "--output", $OutputDirectory,
    "-p:PublishSingleFile=true",
    "-p:PublishTrimmed=false",
    "-p:IncludeNativeLibrariesForSelfExtract=true",
    "-p:DebugSymbols=false",
    "-p:DebugType=None",
    "-p:ContinuousIntegrationBuild=true"
)

$executable = Join-Path -Path $OutputDirectory -ChildPath "SmartCopyPaste.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Publish did not produce '$executable'."
}

$unexpectedFiles = @(
    Get-ChildItem -LiteralPath $OutputDirectory -File |
        Where-Object { $_.FullName -ne $executable }
)
if ($unexpectedFiles.Count -gt 0) {
    $names = $unexpectedFiles.Name -join ", "
    throw "Single-file publish produced unexpected companion files: $names"
}

if (-not $SkipSelfTest) {
    Write-Host "Running published executable self-test..." -ForegroundColor Cyan
    $process = Start-Process `
        -FilePath $executable `
        -ArgumentList "--self-test" `
        -PassThru `
        -Wait `
        -WindowStyle Hidden

    if ($process.ExitCode -ne 0) {
        throw "Published executable self-test failed with code $($process.ExitCode)."
    }
}

Write-Host "Single-file publish passed." -ForegroundColor Green
Write-Host "Executable: $executable"

