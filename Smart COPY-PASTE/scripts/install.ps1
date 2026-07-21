[CmdletBinding()]
param(
    [string]$SourceExecutable,
    [string]$ExpectedSha256,
    [switch]$StartWithWindows,
    [switch]$Launch,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "Smart COPY/PASTE can only be installed on Windows."
}

$installRoot = Join-Path -Path $env:LOCALAPPDATA -ChildPath "Programs\SmartCopyPaste"
$destinationExecutable = Join-Path -Path $installRoot -ChildPath "SmartCopyPaste.exe"
$startMenuDirectory = Join-Path -Path ([Environment]::GetFolderPath("StartMenu")) -ChildPath "Programs"
$shortcutPath = Join-Path -Path $startMenuDirectory -ChildPath "Smart COPY-PASTE.lnk"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runValueName = "SmartCopyPaste"

if ([string]::IsNullOrWhiteSpace($SourceExecutable)) {
    $localCandidate = @(
        Get-ChildItem -LiteralPath $PSScriptRoot -Filter "SmartCopyPaste*.exe" -File -ErrorAction SilentlyContinue |
            Sort-Object -Property LastWriteTimeUtc -Descending
    ) | Select-Object -First 1

    if ($null -ne $localCandidate) {
        $SourceExecutable = $localCandidate.FullName
    }
    else {
        $projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
        $artifactCandidates = @(
            Get-ChildItem `
                -LiteralPath (Join-Path $projectRoot "artifacts\release") `
                -Filter "SmartCopyPaste*-win-x64.exe" `
                -File `
                -Recurse `
                -ErrorAction SilentlyContinue |
                Sort-Object -Property LastWriteTimeUtc -Descending
        )

        if ($artifactCandidates.Count -gt 0) {
            $SourceExecutable = $artifactCandidates[0].FullName
        }
    }
}

if ([string]::IsNullOrWhiteSpace($SourceExecutable)) {
    throw "No release EXE was found. Pass -SourceExecutable with the versioned EXE path."
}

$SourceExecutable = [System.IO.Path]::GetFullPath($SourceExecutable)
if (-not (Test-Path -LiteralPath $SourceExecutable -PathType Leaf) -or
    [System.IO.Path]::GetExtension($SourceExecutable) -ne ".exe") {
    throw "Source executable does not exist or is not an EXE: '$SourceExecutable'."
}

$sourceDirectory = Split-Path -Path $SourceExecutable -Parent
$sourceFileName = Split-Path -Path $SourceExecutable -Leaf
if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    foreach ($checksumName in @("EXE-SHA256.txt", "SHA256SUMS.txt")) {
        $checksumPath = Join-Path -Path $sourceDirectory -ChildPath $checksumName
        if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
            continue
        }

        foreach ($line in Get-Content -LiteralPath $checksumPath) {
            if ($line -match "^([0-9A-Fa-f]{64})\s+\*?(.+)$" -and
                $Matches[2].Trim().Equals(
                    $sourceFileName,
                    [System.StringComparison]::OrdinalIgnoreCase
                )) {
                $ExpectedSha256 = $Matches[1]
                break
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
            break
        }
    }
}

$actualHash = (Get-FileHash -LiteralPath $SourceExecutable -Algorithm SHA256).Hash
if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and
    -not $actualHash.Equals($ExpectedSha256.Trim(), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "SHA-256 mismatch. Expected '$ExpectedSha256'; found '$actualHash'."
}

if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    Write-Warning "No expected SHA-256 was provided or found beside the EXE. Verify it against the trusted release manifest before continuing."
}

$signature = Get-AuthenticodeSignature -LiteralPath $SourceExecutable
if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::NotSigned) {
    Write-Warning "This executable is unsigned and may show SmartScreen 'Unknown publisher'. Do not disable SmartScreen."
}
elseif ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Refusing to install an executable with signature status '$($signature.Status)'."
}

$runningInstall = @(
    Get-Process -Name "SmartCopyPaste" -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -and $_.Path.Equals(
                    $destinationExecutable,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
            catch {
                $false
            }
        }
)

if ($runningInstall.Count -gt 0 -and -not $Force) {
    throw "Smart COPY/PASTE is running from the install directory. Exit it from the tray, then retry. Use -Force only when normal Exit is unavailable."
}

if ($runningInstall.Count -gt 0) {
    $runningInstall | Stop-Process -Force
    Start-Sleep -Milliseconds 300
}

New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
Copy-Item -LiteralPath $SourceExecutable -Destination $destinationExecutable -Force

New-Item -ItemType Directory -Path $startMenuDirectory -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $destinationExecutable
$shortcut.WorkingDirectory = $installRoot
$shortcut.IconLocation = "$destinationExecutable,0"
$shortcut.Description = "Smart COPY/PASTE Windows tray application"
$shortcut.Save()

if ($StartWithWindows) {
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty `
        -Path $runKey `
        -Name $runValueName `
        -Value "`"$destinationExecutable`" --startup" `
        -PropertyType String `
        -Force | Out-Null
}

$installedHash = (Get-FileHash -LiteralPath $destinationExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$installManifest = [ordered]@{
    product = "Smart COPY/PASTE"
    installedUtc = [DateTime]::UtcNow.ToString("o")
    executable = $destinationExecutable
    sha256 = $installedHash
    startWithWindows = [bool]$StartWithWindows
}
$installManifest |
    ConvertTo-Json -Depth 3 |
    Set-Content -LiteralPath (Join-Path $installRoot "install-manifest.json") -Encoding UTF8

Write-Host "Smart COPY/PASTE installed for the current user." -ForegroundColor Green
Write-Host "Executable: $destinationExecutable"
Write-Host "Start Menu:  $shortcutPath"
Write-Host "SHA-256:     $installedHash"

if ($Launch) {
    Start-Process -FilePath $destinationExecutable -WorkingDirectory $installRoot -WindowStyle Hidden
    Write-Host "Smart COPY/PASTE started in the notification area."
}
