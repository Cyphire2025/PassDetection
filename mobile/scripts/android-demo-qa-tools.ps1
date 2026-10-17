# adb helpers for the requested local emulator. Tap positions come only from UI XML bounds.
$DemoAdb = Join-Path $env:LOCALAPPDATA 'Android/Sdk/platform-tools/adb.exe'
$DemoQaDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'outputs/standalone-demo/qa'
New-Item -ItemType Directory -Path $DemoQaDirectory -Force | Out-Null
function Get-DemoUi {
  & $DemoAdb -s emulator-5554 shell rm -f /sdcard/gc-demo-ui.xml
  & $DemoAdb -s emulator-5554 shell test -f /data/local/tmp/gc-ui-dump.jar
  $dump = if ($LASTEXITCODE -eq 0) {
    (& $DemoAdb -s emulator-5554 shell 'CLASSPATH=/system/framework/uiautomator.jar:/data/local/tmp/gc-ui-dump.jar app_process /system/bin GcUiDump /sdcard/gc-demo-ui.xml 1280 2856' 2>&1) -join "`n"
  } else { (& $DemoAdb -s emulator-5554 shell uiautomator dump /sdcard/gc-demo-ui.xml 2>&1) -join "`n" }
  if ($LASTEXITCODE -ne 0 -or $dump -match 'ERROR:') { throw "Could not dump the current emulator UI: $dump" }
  $source = (& $DemoAdb -s emulator-5554 shell cat /sdcard/gc-demo-ui.xml) -join "`n"
  $source | Set-Content -LiteralPath (Join-Path $DemoQaDirectory 'ui-current.xml')
  return [xml]$source
}
function Show-DemoUi {
  $ui = Get-DemoUi
  $ui.SelectNodes('//node') | Where-Object { $_.text -or $_.'content-desc' -or $_.clickable -eq 'true' -or $_.scrollable -eq 'true' } |
    ForEach-Object { [PSCustomObject]@{text=$_.text; description=$_.'content-desc'; id=$_.'resource-id'; class=$_.class; bounds=$_.bounds; scroll=$_.scrollable} | ConvertTo-Json -Compress }
}
function Tap-DemoNode {
  param([Parameter(Mandatory)][string]$Label, [switch]$InputOnly)
  $ui = Get-DemoUi
  $node = $ui.SelectNodes('//node') | Where-Object {
    (!$InputOnly -or $_.class -eq 'android.widget.EditText') -and (
      $_.text -eq $Label -or $_.'content-desc' -eq $Label -or $_.'resource-id' -eq $Label -or $_.'resource-id'.EndsWith(":id/$Label")
    )
  } | Select-Object -First 1
  if (!$node) { throw "UI node was not found: $Label" }
  $bounds = [regex]::Match($node.bounds, '^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$')
  if (!$bounds.Success) { throw "UI node has no usable bounds: $Label" }
  $x = [int]( ([int]$bounds.Groups[1].Value + [int]$bounds.Groups[3].Value) / 2 )
  $y = [int]( ([int]$bounds.Groups[2].Value + [int]$bounds.Groups[4].Value) / 2 )
  & $DemoAdb -s emulator-5554 shell input tap $x $y
}
function Set-DemoInput {
  param([string]$Label, [string]$Value)
  Tap-DemoNode $Label -InputOnly
  & $DemoAdb -s emulator-5554 shell input keycombination 113 29
  & $DemoAdb -s emulator-5554 shell input keyevent 67
  Start-Sleep -Milliseconds 300
  & $DemoAdb -s emulator-5554 shell input text $Value.Replace(' ', '%s')
  Start-Sleep -Milliseconds 300
}
function Scroll-DemoUi {
  param([switch]$Reverse)
  $ui = Get-DemoUi
  $node = $ui.SelectNodes('//node[@scrollable="true"]') | Select-Object -First 1
  if (!$node) { throw 'The current UI has no scrollable container.' }
  $bounds = [regex]::Match($node.bounds, '^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$')
  $left, $top, $right, $bottom = 1..4 | ForEach-Object { [int]$bounds.Groups[$_].Value }
  $x = [int](($left + $right) / 2)
  $start = [int]($top + ($bottom - $top) * 0.7)
  $end = [int]($top + ($bottom - $top) * 0.3)
  if ($Reverse) { $start, $end = $end, $start }
  & $DemoAdb -s emulator-5554 shell input swipe $x $start $x $end 350
  Start-Sleep -Milliseconds 300
}
function Save-DemoScreenshot {
  param([string]$Name)
  if ($Name -notmatch '^[a-z0-9-]+$') { throw 'Screenshot name must use letters, numbers, and hyphens.' }
  & $DemoAdb -s emulator-5554 shell screencap -p /sdcard/gc-demo-screen.png
  & $DemoAdb -s emulator-5554 pull /sdcard/gc-demo-screen.png (Join-Path $DemoQaDirectory "$Name.png")
}
