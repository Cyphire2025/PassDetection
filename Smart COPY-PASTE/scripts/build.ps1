[CmdletBinding()]
param(
    [switch]$SkipRestore
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path -Path $PSScriptRoot -ChildPath "Common.ps1")

Assert-WindowsHost

if (-not $SkipRestore) {
    Invoke-LockedRestore
}

Invoke-DotNet -Arguments @(
    "build",
    $script:SolutionPath,
    "--configuration", "Release",
    "--no-restore",
    "-p:ContinuousIntegrationBuild=true"
)

Write-Host "Release build passed." -ForegroundColor Green

