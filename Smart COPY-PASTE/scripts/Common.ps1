Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$script:ArtifactsRoot = Join-Path -Path $script:ProjectRoot -ChildPath "artifacts"
$script:LocalDotNetRoot = Join-Path -Path $env:LOCALAPPDATA -ChildPath "SmartCopyPasteDev\dotnet"
$script:LocalDotNetExecutable = Join-Path -Path $script:LocalDotNetRoot -ChildPath "dotnet.exe"
$script:SolutionPath = Join-Path -Path $script:ProjectRoot -ChildPath "SmartCopyPaste.slnx"
$script:AppProjectPath = Join-Path -Path $script:ProjectRoot -ChildPath "src\SmartCopyPaste.App\SmartCopyPaste.App.csproj"

function Assert-WindowsHost {
    if ($env:OS -ne "Windows_NT") {
        throw "Smart COPY/PASTE can only be built and packaged on Windows."
    }
}

function Test-DotNet10Sdk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable
    )

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return $false
    }

    $sdkLines = & $Executable --list-sdks 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    return [bool]($sdkLines | Where-Object { $_ -match "^10\." } | Select-Object -First 1)
}

function Resolve-DotNetExecutable {
    $pathCommand = Get-Command -Name "dotnet.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand -and (Test-DotNet10Sdk -Executable $pathCommand.Source)) {
        return $pathCommand.Source
    }

    if (Test-DotNet10Sdk -Executable $script:LocalDotNetExecutable) {
        return $script:LocalDotNetExecutable
    }

    throw @"
.NET 10 SDK was not found.

Checked:
  - dotnet.exe on PATH
  - $script:LocalDotNetExecutable

Run:
  powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\bootstrap.ps1" -InstallSdk
"@
}

function Get-DotNetSdkVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable
    )

    $versions = @(
        & $Executable --list-sdks |
            ForEach-Object {
                if ($_ -match "^([0-9]+\.[0-9]+\.[0-9]+)") {
                    [version]$Matches[1]
                }
            } |
            Where-Object { $_.Major -eq 10 } |
            Sort-Object -Descending
    )

    if ($versions.Count -eq 0) {
        throw ".NET 10 SDK is unavailable at '$Executable'."
    }

    return $versions[0].ToString()
}

function Invoke-DotNet {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $dotnet = Resolve-DotNetExecutable
    Write-Host "> `"$dotnet`" $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $dotnet @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet exited with code $LASTEXITCODE."
    }
}

function Get-ProjectVersion {
    [xml]$project = Get-Content -LiteralPath $script:AppProjectPath -Raw
    $versionNode = $project.SelectSingleNode("/Project/PropertyGroup/Version")
    if ($null -eq $versionNode -or [string]::IsNullOrWhiteSpace($versionNode.InnerText)) {
        throw "The application project does not define a Version property."
    }

    return $versionNode.InnerText.Trim()
}

function Get-SourceGitProvenance {
    $git = Get-Command -Name "git.exe" -ErrorAction SilentlyContinue
    if ($null -eq $git) {
        return [pscustomobject][ordered]@{
            Commit = "unknown"
            State = "git-unavailable"
        }
    }

    $gitRoot = & $git.Source -C $script:ProjectRoot rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gitRoot)) {
        return [pscustomobject][ordered]@{
            Commit = "unknown"
            State = "not-a-git-worktree"
        }
    }

    $trackedFiles = @(
        & $git.Source -C $script:ProjectRoot ls-files -- . 2>$null
    )
    if ($LASTEXITCODE -ne 0 -or $trackedFiles.Count -eq 0) {
        return [pscustomobject][ordered]@{
            Commit = "untracked"
            State = "untracked-source"
        }
    }

    $commit = & $git.Source -C $script:ProjectRoot rev-parse --verify HEAD 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
        return [pscustomobject][ordered]@{
            Commit = "unknown"
            State = "tracked-commit-unavailable"
        }
    }

    $status = @(
        & $git.Source -C $script:ProjectRoot status --porcelain --untracked-files=all -- . 2>$null
    )
    return [pscustomobject][ordered]@{
        Commit = $commit.Trim()
        State = if ($status.Count -eq 0) { "clean" } else { "dirty" }
    }
}

function Get-SourceTreeDigest {
    $excludedDirectoryNames = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    @(
        ".git",
        ".idea",
        ".vs",
        "artifacts",
        "bin",
        "node_modules",
        "obj",
        "TestResults"
    ) | ForEach-Object { [void]$excludedDirectoryNames.Add($_) }

    $rootPrefix = $script:ProjectRoot.TrimEnd("\") + "\"
    $sourceFiles = @(
        Get-ChildItem -LiteralPath $script:ProjectRoot -Recurse -File |
            ForEach-Object {
                $relativePath = $_.FullName.Substring($rootPrefix.Length)
                [pscustomobject]@{
                    File = $_
                    RelativePath = $relativePath.Replace("\", "/")
                    Segments = @($relativePath -split "[\\/]")
                }
            } |
            Where-Object {
                -not ($_.Segments | Where-Object {
                    $excludedDirectoryNames.Contains($_)
                })
            } |
            Sort-Object -Property RelativePath
    )
    if ($sourceFiles.Count -eq 0) {
        throw "No source files were found for release provenance."
    }

    $digestRecords = @(
        foreach ($sourceFile in $sourceFiles) {
            $fileHash = (
                Get-FileHash -LiteralPath $sourceFile.File.FullName -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            "$fileHash  $($sourceFile.RelativePath)"
        }
    )
    $digestText = ($digestRecords -join "`n") + "`n"
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digestBytes = $sha256.ComputeHash($utf8.GetBytes($digestText))
    }
    finally {
        $sha256.Dispose()
    }

    return [pscustomobject][ordered]@{
        Hash = ([System.BitConverter]::ToString($digestBytes)).Replace("-", "").ToLowerInvariant()
        FileCount = $sourceFiles.Count
    }
}

function Assert-PathBelow {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,

        [Parameter(Mandatory = $true)]
        [string]$Parent
    )

    $candidateFull = [System.IO.Path]::GetFullPath($Candidate).TrimEnd("\")
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd("\")
    $prefix = $parentFull + "\"

    if ($candidateFull.Equals($parentFull, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $candidateFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing filesystem operation outside a child of '$parentFull': '$candidateFull'."
    }
}

function Reset-ArtifactDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Assert-PathBelow -Candidate $Path -Parent $script:ArtifactsRoot
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }

    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Invoke-LockedRestore {
    $lockFiles = @(
        Get-ChildItem -LiteralPath $script:ProjectRoot -Filter "packages.lock.json" -File -Recurse -ErrorAction SilentlyContinue
    )

    $arguments = @("restore", $script:SolutionPath)
    if ($lockFiles.Count -gt 0) {
        $arguments += "--locked-mode"
    }
    else {
        Write-Warning "No packages.lock.json was found. Restore will create the initial lock file; commit it before release."
    }

    Invoke-DotNet -Arguments $arguments
}
