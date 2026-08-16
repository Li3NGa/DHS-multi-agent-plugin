# 一键安装 deepseek-multi-agent-plugin 到 DSH 配置（幂等）
#
# 用法（PowerShell）：
#   .\dsh\install.ps1 [-Profile web] [-Config example_config.yaml]
#
# 步骤：pip 安装插件 -> 把 mcp-multiagent 条目追加到目标 profile 的
# cordis.patch.yml（已存在同名条目则替换）。保存后 DSH 热加载生效。
param(
    [string]$Profile = "web",
    [string]$Config = "example_config.yaml"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$patchFile = Join-Path $env:USERPROFILE ".dsh\profiles\$Profile\cordis.patch.yml"
if (-not (Test-Path (Split-Path $patchFile))) {
    throw "profile not found: $patchFile"
}

Write-Host "[1/3] installing python package (git)"
python -m pip install --quiet "git+https://github.com/Li3NGa/deepseek-multi-agent-plugin"

$configAbs = (Resolve-Path (Join-Path $Root $Config)).Path
$entry = @(
  "- insert:",
  "    - id: mcp-multiagent",
  "      name: '@deepseek-ai/dsh-mcp-client'",
  "      config:",
  "        serverName: multiagent",
  "        transport: stdio",
  "        command: python",
  "        args: ['-m', 'deepseek_multi_agent_plugin.mcp_server', '--config', '$configAbs']"
)

Write-Host "[2/3] updating $patchFile"
$lines = @()
if (Test-Path $patchFile) {
    $lines = Get-Content $patchFile
}
$filtered = New-Object System.Collections.Generic.List[string]
$skip = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "id:\s*mcp-multiagent") {
        $skip = $true
        if ($filtered.Count -gt 0 -and $filtered[$filtered.Count - 1] -match "- insert:") {
            $filtered.RemoveAt($filtered.Count - 1)
        }
        continue
    }
    if ($skip) {
        if ($lines[$i] -match "^\s+- insert:" -or $lines[$i] -match "^\s+- id:" -or ($lines[$i].Trim() -eq "")) {
            $skip = $false
            if ($lines[$i].Trim() -ne "") { $filtered.Add($lines[$i]) }
        }
        continue
    }
    $filtered.Add($lines[$i])
}
$filtered.AddRange($entry)
Set-Content -Path $patchFile -Value $filtered -Encoding utf8

Write-Host "[3/3] done"
Write-Host "DSH will hot-reload the profile. Verify: Settings -> Plugins -> mcp-multiagent,"
Write-Host "then ask the model to call mcp__multiagent__status."
