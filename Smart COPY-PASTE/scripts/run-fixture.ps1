[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8765,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$fixtureDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..\fixtures")
)
$fixturePath = Join-Path -Path $fixtureDirectory -ChildPath "browser-form.html"
if (-not (Test-Path -LiteralPath $fixturePath -PathType Leaf)) {
    throw "Fixture file was not found: '$fixturePath'."
}

$python = Get-Command -Name "python.exe" -ErrorAction SilentlyContinue
$pythonArguments = @("-m", "http.server", $Port, "--bind", "127.0.0.1")

if ($null -eq $python) {
    $python = Get-Command -Name "py.exe" -ErrorAction SilentlyContinue
    $pythonArguments = @("-3", "-m", "http.server", $Port, "--bind", "127.0.0.1")
}

if ($null -eq $python) {
    throw "Python 3 was not found on PATH. Open fixtures\browser-form.html directly in Chrome, Edge, or Brave."
}

$url = "http://127.0.0.1:$Port/browser-form.html"
$server = Start-Process `
    -FilePath $python.Source `
    -ArgumentList $pythonArguments `
    -WorkingDirectory $fixtureDirectory `
    -PassThru `
    -WindowStyle Hidden

try {
    $ready = $false
    foreach ($attempt in 1..30) {
        if ($server.HasExited) {
            throw "Fixture server exited with code $($server.ExitCode)."
        }

        $client = $null
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect("127.0.0.1", $Port)
            $client.Dispose()
            $ready = $true
            break
        }
        catch {
            if ($null -ne $client) {
                $client.Dispose()
            }
            Start-Sleep -Milliseconds 100
        }
    }

    if (-not $ready) {
        throw "Fixture server did not become ready at '$url'."
    }

    Write-Host "Offline fixture server is running." -ForegroundColor Green
    Write-Host "URL: $url"
    Write-Host "Press Ctrl+C to stop the server."

    if (-not $NoBrowser) {
        Start-Process -FilePath $url
    }

    Wait-Process -Id $server.Id
}
finally {
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
