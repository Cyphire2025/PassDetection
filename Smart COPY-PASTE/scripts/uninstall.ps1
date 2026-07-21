[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [switch]$RemoveUserData,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "Smart COPY/PASTE can only be uninstalled on Windows."
}

$localAppData = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd("\")
$programsRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $localAppData -ChildPath "Programs")
).TrimEnd("\")
$installRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $programsRoot -ChildPath "SmartCopyPaste")
).TrimEnd("\")
$destinationExecutable = Join-Path -Path $installRoot -ChildPath "SmartCopyPaste.exe"
$userDataRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $localAppData -ChildPath "SmartCopyPaste")
).TrimEnd("\")
$shortcutPath = Join-Path `
    -Path ([Environment]::GetFolderPath("StartMenu")) `
    -ChildPath "Programs\Smart COPY-PASTE.lnk"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runValueName = "SmartCopyPaste"

if (-not $installRoot.StartsWith(
        $programsRoot + "\",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Refusing to remove unexpected install path '$installRoot'."
}

if (-not $userDataRoot.StartsWith(
        $localAppData + "\",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Refusing to remove unexpected user-data path '$userDataRoot'."
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
    throw "Smart COPY/PASTE is running. Exit it from the tray, then retry. Use -Force only when normal Exit is unavailable."
}

if ($PSCmdlet.ShouldProcess(
        $installRoot,
        "Stop the installed app and remove its application files, Start Menu shortcut, and matching current-user startup entry"
    )) {
    if ($runningInstall.Count -gt 0) {
        $runningInstall | Stop-Process -Force
        Start-Sleep -Milliseconds 300
    }

    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        Remove-Item -LiteralPath $shortcutPath -Force
    }

    $runValue = Get-ItemProperty `
        -Path $runKey `
        -Name $runValueName `
        -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty $runValueName -ErrorAction SilentlyContinue

    if ($null -ne $runValue -and
        $runValue.ToString().IndexOf(
            $destinationExecutable,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0) {
        Remove-ItemProperty -Path $runKey -Name $runValueName -Force
    }

    if (Test-Path -LiteralPath $installRoot) {
        Remove-Item -LiteralPath $installRoot -Recurse -Force
    }

    Write-Host "Smart COPY/PASTE application files and shortcut were removed." -ForegroundColor Green
}

if ($RemoveUserData -and (Test-Path -LiteralPath $userDataRoot)) {
    if ($PSCmdlet.ShouldProcess(
        $userDataRoot,
            "Permanently delete Smart COPY/PASTE settings and sanitized diagnostics"
        )) {
        Remove-Item -LiteralPath $userDataRoot -Recurse -Force
        Write-Host "User configuration was removed." -ForegroundColor Green
    }
}
elseif (Test-Path -LiteralPath $userDataRoot) {
    Write-Host "User configuration was preserved at: $userDataRoot"
    Write-Host "Run uninstall.ps1 -RemoveUserData to delete it explicitly."
}
