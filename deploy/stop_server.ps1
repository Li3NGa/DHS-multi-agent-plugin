# 停止 deepseek-multi-agent-plugin 后台服务
$Root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $Root ".server.pid"
if (Test-Path $pidFile) {
    $old = Get-Content $pidFile -Raw
    $proc = Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $proc.Id -Force
        Write-Host ("server stopped (pid {0})" -f $proc.Id)
    } else {
        Write-Host "server not running"
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
} else {
    Write-Host "no pid file, server not started via start_server.ps1"
}
