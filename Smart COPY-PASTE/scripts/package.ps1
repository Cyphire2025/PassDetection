[CmdletBinding()]
param(
    [switch]$SkipPublish
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path -Path $PSScriptRoot -ChildPath "Common.ps1")

Assert-WindowsHost

$publishDirectory = Join-Path -Path $script:ArtifactsRoot -ChildPath "publish\win-x64"
$publishedExecutable = Join-Path -Path $publishDirectory -ChildPath "SmartCopyPaste.exe"

if (-not $SkipPublish) {
    & (Join-Path -Path $PSScriptRoot -ChildPath "publish.ps1")
}
elseif (-not (Test-Path -LiteralPath $publishedExecutable -PathType Leaf)) {
    throw "-SkipPublish was supplied, but '$publishedExecutable' does not exist."
}

$version = Get-ProjectVersion
[string]$embeddedProductVersion =
    (Get-Item -LiteralPath $publishedExecutable).VersionInfo.ProductVersion
if ([string]::IsNullOrWhiteSpace($embeddedProductVersion)) {
    throw "Published EXE does not contain a ProductVersion. Publish again without -SkipPublish."
}

$embeddedBaseVersion = (
    $embeddedProductVersion -split "\+", 2
)[0]
if (-not $embeddedBaseVersion.Equals(
        $version,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Published EXE version '$embeddedProductVersion' does not match project version '$version'. Publish again without -SkipPublish."
}

$baseName = "SmartCopyPaste-v$version-win-x64"
$releaseDirectory = Join-Path -Path $script:ArtifactsRoot -ChildPath "release\v$version"
$stageDirectory = Join-Path -Path $script:ArtifactsRoot -ChildPath "package-stage\$baseName"

Reset-ArtifactDirectory -Path $releaseDirectory
Reset-ArtifactDirectory -Path $stageDirectory

$releaseExecutable = Join-Path -Path $releaseDirectory -ChildPath "$baseName.exe"
$zipPath = Join-Path -Path $releaseDirectory -ChildPath "$baseName.zip"

Copy-Item -LiteralPath $publishedExecutable -Destination $releaseExecutable
Copy-Item -LiteralPath $releaseExecutable -Destination (Join-Path $stageDirectory "$baseName.exe")
Copy-Item `
    -LiteralPath (Join-Path $script:ProjectRoot "docs\EMPLOYEE_QUICK_START.md") `
    -Destination (Join-Path $stageDirectory "EMPLOYEE_QUICK_START.md")
Copy-Item `
    -LiteralPath (Join-Path $script:ProjectRoot "docs\KNOWN_LIMITATIONS.md") `
    -Destination (Join-Path $stageDirectory "KNOWN_LIMITATIONS.md")
Copy-Item `
    -LiteralPath (Join-Path $PSScriptRoot "install.ps1") `
    -Destination (Join-Path $stageDirectory "install.ps1")
Copy-Item `
    -LiteralPath (Join-Path $PSScriptRoot "uninstall.ps1") `
    -Destination (Join-Path $stageDirectory "uninstall.ps1")

$executableHash = (Get-FileHash -LiteralPath $releaseExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
"$executableHash  $baseName.exe" |
    Set-Content -LiteralPath (Join-Path $stageDirectory "EXE-SHA256.txt") -Encoding UTF8

Compress-Archive `
    -Path (Join-Path $stageDirectory "*") `
    -DestinationPath $zipPath `
    -CompressionLevel Optimal

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$sumsPath = Join-Path -Path $releaseDirectory -ChildPath "SHA256SUMS.txt"
@(
    "$executableHash  $([System.IO.Path]::GetFileName($releaseExecutable))",
    "$zipHash  $([System.IO.Path]::GetFileName($zipPath))"
) | Set-Content -LiteralPath $sumsPath -Encoding UTF8

$signature = Get-AuthenticodeSignature -LiteralPath $releaseExecutable
$signatureStatus = $signature.Status.ToString()
if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::NotSigned) {
    Write-Warning "The executable is unsigned. SmartScreen may show 'Unknown publisher'. Do not disable SmartScreen."
}
elseif ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Executable signature status is '$signatureStatus'."
}

$dotnet = Resolve-DotNetExecutable
$gitProvenance = Get-SourceGitProvenance
$sourceTreeDigest = Get-SourceTreeDigest
$manifest = [ordered]@{
    product = "Smart COPY/PASTE"
    version = $version
    channel = "preview"
    runtimeIdentifier = "win-x64"
    selfContained = $true
    singleFile = $true
    trimmed = $false
    commit = $gitProvenance.Commit
    sourceState = $gitProvenance.State
    sourceSha256 = $sourceTreeDigest.Hash
    sourceFileCount = $sourceTreeDigest.FileCount
    sourceDigestFormat = "sha256-of-sorted-file-sha256-and-path-lines-v1"
    buildUtc = [DateTime]::UtcNow.ToString("o")
    sdkVersion = Get-DotNetSdkVersion -Executable $dotnet
    signatureStatus = $signatureStatus
    files = @(
        [ordered]@{
            name = [System.IO.Path]::GetFileName($releaseExecutable)
            sha256 = $executableHash
        },
        [ordered]@{
            name = [System.IO.Path]::GetFileName($zipPath)
            sha256 = $zipHash
        }
    )
}

$manifestPath = Join-Path -Path $releaseDirectory -ChildPath "release-manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Release package created." -ForegroundColor Green
Write-Host "Directory: $releaseDirectory"
Write-Host "EXE:       $releaseExecutable"
Write-Host "ZIP:       $zipPath"
Write-Host "SHA-256:   $sumsPath"
