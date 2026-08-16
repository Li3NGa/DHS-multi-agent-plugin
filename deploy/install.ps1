# 一键部署安装：venv + 安装 + 测试
#
# 用法（PowerShell，在仓库根目录执行）：
#   .\deploy\install.ps1
param(
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
}
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --upgrade pip --quiet
Set-Location $Root
& $Py -m pip install -e ".[dev]" --quiet
& $Py -m pytest -q
Write-Host "deployment ready at $Root"
Write-Host "start the service: deploy\start_server.ps1"
