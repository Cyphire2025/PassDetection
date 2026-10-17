param(
  [switch]$QaOnly,
  [switch]$PrepareUnsignedBundle,
  [string]$KeystorePath,
  [string]$CredentialsPath,
  [string]$SdkPath = "$env:LOCALAPPDATA/Android/Sdk",
  [string]$JavaPath = "$env:LOCALAPPDATA/GlobalConnect-Android/jdk/jdk-17.0.20.1+1"
)
$ErrorActionPreference = 'Stop'
$mobileRoot = Split-Path $PSScriptRoot -Parent
$savedEnvironment = @{}
$environmentNames = @('JAVA_HOME','ANDROID_HOME','ANDROID_SDK_ROOT','Path','NODE_ENV','EXPO_NO_DOTENV','SENTRY_DISABLE_AUTO_UPLOAD')
$environmentNames += @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(EXPO_PUBLIC_|GC_|GOOGLE_SERVICES_JSON|EXPO_UPDATES_|SENTRY_|EAS_BUILD_PROFILE)' } | ForEach-Object Name)
$demoEnvironment = @{
  EXPO_PUBLIC_APP_ENV='preview'; EXPO_PUBLIC_DEMO_MODE='true'; EXPO_PUBLIC_STANDALONE_DEMO='true'
  EXPO_PUBLIC_API_URL='https://demo.invalid/api/v1'; EXPO_PUBLIC_REALTIME_ENABLED='false'
  EXPO_PUBLIC_APP_INTEGRITY_MODE='disabled'; EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE='false'
  GC_ANDROID_FACE_LIVENESS_ENABLED='false'; GC_IOS_PUSH_NOTIFICATIONS_ENABLED='false'
  EXPO_NO_DOTENV='1'; SENTRY_DISABLE_AUTO_UPLOAD='true'; NODE_ENV='production'
  JAVA_HOME=$JavaPath; ANDROID_HOME=$SdkPath; ANDROID_SDK_ROOT=$SdkPath
}
$environmentNames += @($demoEnvironment.Keys) + @('GC_ANDROID_KEYSTORE_FILE','GC_ANDROID_KEYSTORE_PASSWORD','GC_ANDROID_KEY_ALIAS','GC_ANDROID_KEY_PASSWORD')
foreach ($name in ($environmentNames | Select-Object -Unique)) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$previousLocation = Get-Location
try {
  if ($PrepareUnsignedBundle) { $QaOnly = $true }
  foreach ($name in $savedEnvironment.Keys) {
    if ($name -match '^(EXPO_PUBLIC_|GC_|GOOGLE_SERVICES_JSON|EXPO_UPDATES_|SENTRY_|EAS_BUILD_PROFILE)') { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
  }
  foreach ($entry in $demoEnvironment.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process') }
  $env:Path = "$JavaPath/bin;$SdkPath/platform-tools;$env:Path"
  if (!(Test-Path -LiteralPath "$JavaPath/bin/java.exe")) { throw 'Java 17 is required; supply -JavaPath.' }
  if ($QaOnly) {
    $env:GC_ANDROID_KEYSTORE_FILE = Join-Path $mobileRoot 'android/app/debug.keystore'
    $env:GC_ANDROID_KEYSTORE_PASSWORD = 'android'
    $env:GC_ANDROID_KEY_ALIAS = 'androiddebugkey'
    $env:GC_ANDROID_KEY_PASSWORD = 'android'
  } else {
    if (!(Test-Path -LiteralPath $KeystorePath -PathType Leaf) -or !(Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) { throw 'Supply the existing Play upload key and protected credentials file. QA keys cannot update the Play app.' }
    $credentials = Get-Content -LiteralPath $CredentialsPath -Raw
    foreach ($field in @(@('Keystore password','GC_ANDROID_KEYSTORE_PASSWORD'),@('Key alias','GC_ANDROID_KEY_ALIAS'),@('Key password','GC_ANDROID_KEY_PASSWORD'))) {
      $match = [regex]::Match($credentials, '(?m)^\s*' + [regex]::Escape($field[0]) + '\s*:\s*(.+?)\s*$')
      if (!$match.Success) { throw "Missing signing field: $($field[0]). Values are never logged." }
      [Environment]::SetEnvironmentVariable($field[1], $match.Groups[1].Value, 'Process')
    }
    $env:GC_ANDROID_KEYSTORE_FILE = (Resolve-Path -LiteralPath $KeystorePath).Path
    $credentials = $null
  }
  Set-Location -LiteralPath $mobileRoot
  & npx.cmd expo prebuild --platform android --no-install
  if ($LASTEXITCODE -ne 0) { throw 'Demo native generation failed.' }
  $arguments = @('-p','android','--console=plain','--no-parallel','--max-workers=2','-Dorg.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1024m')
  if ($QaOnly -and !$PrepareUnsignedBundle) { $arguments += @('-PreactNativeArchitectures=x86_64',':app:assembleRelease') }
  else { $arguments += @('-PreactNativeArchitectures=armeabi-v7a,arm64-v8a,x86,x86_64',':app:assembleRelease',':app:bundleRelease') }
  & ./android/gradlew.bat @arguments
  if ($LASTEXITCODE -ne 0) { throw 'Demo Android compilation failed.' }
  $destination = Join-Path $mobileRoot 'outputs/standalone-demo'
  New-Item -ItemType Directory -Path $destination -Force | Out-Null
  $apkName = if ($PrepareUnsignedBundle) { 'GC-Demo-1.0.10-code11-Universal-QA.apk' } elseif ($QaOnly) { 'GC-Demo-1.0.10-code11-Emulator-QA.apk' } else { 'GC-Demo-1.0.10-code11.apk' }
  Copy-Item -LiteralPath 'android/app/build/outputs/apk/release/app-release.apk' -Destination (Join-Path $destination $apkName)
  if (!$QaOnly) { Copy-Item -LiteralPath 'android/app/build/outputs/bundle/release/app-release.aab' -Destination (Join-Path $destination 'GC-Demo-1.0.10-code11.aab') }
  if ($PrepareUnsignedBundle) {
    $unsignedBundle = Join-Path $destination 'GC-Demo-1.0.10-code11-UNSIGNED.aab'
    Copy-Item -LiteralPath 'android/app/build/outputs/bundle/release/app-release.aab' -Destination $unsignedBundle
    # Strip only the temporary QA JAR signature from the newly copied artifact.
    # The app manifest and bundled modules/assets remain intact.
    $archive = [System.IO.Compression.ZipFile]::Open($unsignedBundle, [System.IO.Compression.ZipArchiveMode]::Update)
    try {
      $signatures = @($archive.Entries | Where-Object { $_.FullName -match '^META-INF/[^/]+\.(RSA|DSA|EC|SF)$|^META-INF/MANIFEST\.MF$' })
      foreach ($signature in $signatures) { $signature.Delete() }
    } finally { $archive.Dispose() }
    Write-Output 'The UNSIGNED AAB contains the demo but must be signed with the existing Play upload key before uploading.'
  }
  Write-Output "Demo artifacts saved to $destination"
  if ($QaOnly) { Write-Output 'The emulator APK uses the development key and is for local QA only.' }
} finally {
  Set-Location -LiteralPath $previousLocation.Path
  foreach ($entry in $savedEnvironment.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process') }
}
