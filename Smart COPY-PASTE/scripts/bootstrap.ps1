[CmdletBinding()]
param(
    [switch]$InstallSdk,
    [switch]$SkipRestore,
    [string]$SdkVersion = "10.0.302"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path -Path $PSScriptRoot -ChildPath "Common.ps1")

Assert-WindowsHost

try {
    $dotnet = Resolve-DotNetExecutable
}
catch {
    if (-not $InstallSdk) {
        throw
    }

    $installerPath = Join-Path -Path $env:TEMP -ChildPath (
        "dotnet-install-smart-copy-paste-{0}.ps1" -f [guid]::NewGuid().ToString("N")
    )

    Write-Host "Downloading the official Microsoft dotnet-install script..." -ForegroundColor Cyan
    Write-Host "This is a developer bootstrap operation; the application itself never downloads an SDK." -ForegroundColor DarkGray

    try {
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "https://dot.net/v1/dotnet-install.ps1" `
            -OutFile $installerPath

        New-Item -ItemType Directory -Path $script:LocalDotNetRoot -Force | Out-Null
        & powershell.exe `
            -NoProfile `
            -ExecutionPolicy Bypass `
            -File $installerPath `
            -Version $SdkVersion `
            -Architecture "x64" `
            -InstallDir $script:LocalDotNetRoot `
            -NoPath

        if ($LASTEXITCODE -ne 0) {
            throw "Microsoft dotnet-install exited with code $LASTEXITCODE."
        }
    }
    finally {
        if (Test-Path -LiteralPath $installerPath -PathType Leaf) {
            Remove-Item -LiteralPath $installerPath -Force
        }
    }

    $dotnet = Resolve-DotNetExecutable
}

$sdkVersion = Get-DotNetSdkVersion -Executable $dotnet
Write-Host "Using .NET SDK $sdkVersion" -ForegroundColor Green
Write-Host "Executable: $dotnet"

& $dotnet --info
if ($LASTEXITCODE -ne 0) {
    throw "dotnet --info failed with code $LASTEXITCODE."
}

if (-not $SkipRestore) {
    Write-Host "Restoring the solution..." -ForegroundColor Cyan
    Invoke-DotNet -Arguments @("restore", $script:SolutionPath)
}

Write-Host "Bootstrap complete." -ForegroundColor Green

