$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $repo
$composeArgs = @('compose', '--env-file', '.env.example', '-p', 'passdetection-qualification', '-f', 'docker-compose.qualification.yml')
$nginxId = (& docker @composeArgs ps -q nginx).Trim()
$backendId = (& docker @composeArgs ps -q backend).Trim()
if (!$nginxId -or !$backendId) { throw 'The isolated qualification stack must already be running.' }
$nginx = (& docker inspect $nginxId | ConvertFrom-Json)[0]
$backend = (& docker inspect $backendId | ConvertFrom-Json)[0]
foreach ($container in @($nginx, $backend)) {
    if ($container.Config.Labels.'com.docker.compose.project' -ne 'passdetection-qualification' -or !$container.State.Running) {
        throw 'Container project or running-state guard failed.'
    }
}
if ($nginx.Config.Labels.'com.docker.compose.service' -ne 'nginx' -or $backend.Config.Labels.'com.docker.compose.service' -ne 'backend') { throw 'Unexpected qualification services.' }
if (!($backend.Config.Env -contains 'POSTGRES_DB=passdetection_ci_browser')) { throw 'Disposable database identity guard failed.' }
$binding = $nginx.NetworkSettings.Ports.'443/tcp'
if (!$binding -or $binding[0].HostIp -ne '127.0.0.1' -or $binding[0].HostPort -ne '58443') { throw 'Unexpected qualification HTTPS binding.' }
$evidence = Join-Path $repo 'outputs\qualification\linux-webkit'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$image = 'mcr.microsoft.com/playwright@sha256:c091b21d9fae78c76e85cd4356431e9b018402f172a214fc7d7a5e9a7e29d8ac'
& docker image inspect $image *> $null
if ($LASTEXITCODE -ne 0) { throw 'Pull the pinned official Playwright1.62.1-noble image during a clear qualification window first.' }
$runArgs = @('run', '--rm', '--init', '--name', 'passdetection-linux-webkit-qualification', '--network', "container:$nginxId", '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=1073741824', '--shm-size', '512m', '--user', 'pwuser', '--env', 'HOME=/tmp', '--env', 'QUALIFICATION_PROJECT=passdetection-qualification', '--workdir', '/workspace/frontend', '--mount', "type=bind,source=$repo\frontend,target=/workspace/frontend,readonly", '--mount', "type=bind,source=$repo\outputs\qualification\seed.log,target=/workspace/outputs/qualification/seed.log,readonly", '--mount', "type=bind,source=$repo\scripts\qa\run_linux_webkit.cjs,target=/tmp/run_linux_webkit.cjs,readonly", '--mount', "type=bind,source=$evidence,target=/evidence", $image, 'node', '/tmp/run_linux_webkit.cjs')
& docker @runArgs
$result = $LASTEXITCODE
$afterBackend = (& docker inspect $backendId | ConvertFrom-Json)[0]
$afterNginx = (& docker inspect $nginxId | ConvertFrom-Json)[0]
if ($afterBackend.Image -ne $backend.Image -or !$afterBackend.State.Running -or !$afterNginx.State.Running) { throw 'Existing application image/state changed during qualification.' }
@{ browser_image=$image; backend_image=$backend.Image; nginx_container=$nginxId; backend_container=$backendId; application_containers_preserved=$true; exit_code=$result; origin='https://localhost:58443'; tls_forward='loopback TCP58443 to existing Nginx443; no termination or origin change' } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'execution.json')
exit $result
