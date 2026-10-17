param(
  [Parameter(Mandatory)][string]$KeystorePath,
  [Parameter(Mandatory)][string]$CredentialsPath,
  [string]$UnsignedBundlePath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'outputs/standalone-demo/GC-Demo-1.0.10-code11-UNSIGNED.aab'),
  [string]$JavaPath = "$env:LOCALAPPDATA/GlobalConnect-Android/jdk/jdk-17.0.20.1+1"
)
$ErrorActionPreference = 'Stop'
# Public fingerprint recorded for this app's previous upload key.
$expectedCertificate = 'DB6C67BE3780DF959A351C1D480D1316101F0E711C485B0F7214BD83CA996D2D'
$savedEnvironment = @{}
$pendingBundle = $null
foreach ($name in @('GC_DEMO_SIGN_STORE_PASSWORD','GC_DEMO_SIGN_KEY_PASSWORD')) {
  $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
  foreach ($path in @($KeystorePath, $CredentialsPath, $UnsignedBundlePath, "$JavaPath/bin/jarsigner.exe")) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw 'The existing keystore, credentials, prepared AAB and Java 17 tools are required.' }
  }
  $credentials = Get-Content -LiteralPath $CredentialsPath -Raw
  $values = @{}
  foreach ($field in @('Keystore password','Key alias','Key password')) {
    $match = [regex]::Match($credentials, '(?m)^\s*' + [regex]::Escape($field) + '\s*:\s*(.+?)\s*$')
    if (!$match.Success) { throw "Missing signing field: $field. Values are never logged." }
    $values[$field] = $match.Groups[1].Value
  }
  $env:GC_DEMO_SIGN_STORE_PASSWORD = $values['Keystore password']
  $env:GC_DEMO_SIGN_KEY_PASSWORD = $values['Key password']
  $keyAlias = $values['Key alias']
  $values = $null
  $credentials = $null
  $keyDetails = (& "$JavaPath/bin/keytool.exe" -list -v -alias $keyAlias -keystore $KeystorePath -storepass:env GC_DEMO_SIGN_STORE_PASSWORD 2>&1) -join "`n"
  if ($LASTEXITCODE -ne 0) { throw 'The existing upload key could not be opened. Check the protected credentials file.' }
  $certificate = [regex]::Match($keyDetails, 'SHA256:\s*([0-9A-Fa-f:]+)')
  if (!$certificate.Success -or $certificate.Groups[1].Value.Replace(':','').ToUpperInvariant() -ne $expectedCertificate) {
    throw 'This certificate does not match the recorded Play upload key. Confirm the key against Play Console before signing.'
  }
  $keyDetails = $null
  $bundleDirectory = Split-Path (Resolve-Path -LiteralPath $UnsignedBundlePath).Path -Parent
  $destination = Join-Path $bundleDirectory 'GC-Demo-1.0.10-code11.aab'
  $pendingBundle = Join-Path $bundleDirectory (([guid]::NewGuid().ToString()) + '.pending.aab')
  Copy-Item -LiteralPath $UnsignedBundlePath -Destination $pendingBundle
  $signOutput = (& "$JavaPath/bin/jarsigner.exe" -keystore $KeystorePath -storepass:env GC_DEMO_SIGN_STORE_PASSWORD -keypass:env GC_DEMO_SIGN_KEY_PASSWORD -digestalg SHA-256 $pendingBundle $keyAlias 2>&1) -join "`n"
  if ($LASTEXITCODE -ne 0) { throw 'AAB signing failed; do not upload the output. The unsigned source is preserved.' }
  $verifyOutput = (& "$JavaPath/bin/jarsigner.exe" -verify $pendingBundle 2>&1) -join "`n"
  if ($LASTEXITCODE -ne 0 -or $verifyOutput -notmatch 'jar verified') { throw 'The AAB signature could not be verified; do not upload the output.' }
  Move-Item -LiteralPath $pendingBundle -Destination $destination -Force
  Write-Output "AAB signed with the recorded upload certificate and verified: $destination"
  Get-FileHash -LiteralPath $destination -Algorithm SHA256 | Select-Object Algorithm,Hash,Path
} finally {
  if ($pendingBundle -and (Test-Path -LiteralPath $pendingBundle)) { Remove-Item -LiteralPath $pendingBundle }
  foreach ($entry in $savedEnvironment.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process') }
}
