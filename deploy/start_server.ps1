# 启动 deepseek-multi-agent-plugin HTTP 适配服务（后台常驻）
#
# 用法（PowerShell）：
#   .\deploy\start_server.ps1
#
# 行为：
# - 自动从 ~/.dsh/.credentials.yaml 或环境变量读取 DEEPSEEK_API_KEY（不回显）
# - 自动生成并持久化服务鉴权 token（DS_AGENT_TOKEN / Bearer）
# - 以隐藏窗口后台启动，PID 写入 .server.pid
param(
    [int]$Port = 8000,
    [string]$HostBind = "127.0.0.1",
    [string]$Config = "example_config.yaml"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    throw "venv not found, run deploy\install.ps1 first"
}

# ---- API key ----
if (-not $env:DEEPSEEK_API_KEY) {
    $credsFile = Join-Path $env:USERPROFILE ".dsh\.credentials.yaml"
    if (Test-Path $credsFile) {
        $creds = Get-Content $credsFile -Raw
        if ($creds -match "DEEPSEEK_API_KEY:\s*(\S+)") {
            $env:DEEPSEEK_API_KEY = $Matches[1]
        }
    }
}
if (-not $env:DEEPSEEK_API_KEY) {
    Write-Warning "DEEPSEEK_API_KEY not found; LLM agents will fail (mock/demo still work)"
}

# ---- auth token ----
$tokenFile = Join-Path $env:LOCALAPPDATA "deepseek-multi-agent-plugin\token.txt"
if (Test-Path $tokenFile) {
    $token = (Get-Content $tokenFile -Raw).Trim()
} else {
    $token = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    New-Item -ItemType Directory -Force -Path (Split-Path $tokenFile) | Out-Null
    Set-Content -Path $tokenFile -Value $token -Encoding ascii
}
$env:DS_AGENT_TOKEN = $token

# ---- stop existing instance ----
$pidFile = Join-Path $Root ".server.pid"
if (Test-Path $pidFile) {
    $old = Get-Content $pidFile -Raw
    $proc = Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -match "python") {
        Stop-Process -Id $proc.Id -Force
    }
}

# ---- start ----
$serverArgs = @("-m", "deepseek_multi_agent_plugin.adapter_server",
          "--host", $HostBind, "--port", "$Port", "--config", (Join-Path $Root $Config))
$p = Start-Process -FilePath $Py -ArgumentList $serverArgs -WorkingDirectory $Root -WindowStyle Hidden -PassThru
Set-Content -Path $pidFile -Value $p.Id -Encoding ascii
Start-Sleep -Seconds 2
if ($p.HasExited) {
    throw "server exited early (code $($p.ExitCode)), check logs"
}

Write-Host ("server started: http://{0}:{1} (pid {2})" -f $HostBind, $Port, $p.Id)
Write-Host ("auth token: {0} (stored at {1})" -f $token, $tokenFile)
Write-Host ("test: Invoke-RestMethod -Uri http://{0}:{1}/health  (header: Authorization: Bearer <token>)" -f $HostBind, $Port)
