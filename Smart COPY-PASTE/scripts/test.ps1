[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$NoCoverage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path -Path $PSScriptRoot -ChildPath "Common.ps1")

Assert-WindowsHost

if (-not $SkipBuild) {
    & (Join-Path -Path $PSScriptRoot -ChildPath "build.ps1")
}

$resultsDirectory = Join-Path -Path $script:ArtifactsRoot -ChildPath "test-results"
Reset-ArtifactDirectory -Path $resultsDirectory

$arguments = @(
    "test",
    $script:SolutionPath,
    "--configuration", "Release",
    "--no-build",
    "--no-restore",
    "--results-directory", $resultsDirectory,
    "--logger", "trx;LogFileName=SmartCopyPaste.trx"
)

if (-not $NoCoverage) {
    $arguments += @("--collect", "XPlat Code Coverage")
}

Invoke-DotNet -Arguments $arguments

Write-Host "Automated tests passed." -ForegroundColor Green
Write-Host "Results: $resultsDirectory"

