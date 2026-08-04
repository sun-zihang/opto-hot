# opto-hot CloudBase 重新部署脚本（供 scripts\auto-update.ps1 调用）
# 前提：项目根目录存在 config\mcporter.json；且已登录（device 会话）或设置环境变量 TCB_API_KEY / TCB_ENV_ID
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$envId = if ($env:TCB_ENV_ID) { $env:TCB_ENV_ID } else { "a455-d3g2s3dt865d86640" }
$apiKey = $env:TCB_API_KEY

if ($apiKey) {
  Write-Host "[cloudbase-deploy] 使用 API Key 登录（env=$envId）"
  npx.cmd -y mcporter call cloudbase.auth action=login_by_api_key apiKey=$apiKey apiKeyEnvId=$envId --output json | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "CloudBase API Key 登录失败" }
} else {
  Write-Host "[cloudbase-deploy] 使用当前已登录会话（未设置 TCB_API_KEY）"
}

Write-Host "[cloudbase-deploy] 触发部署（服务名 opto-hot，域名不变）..."
npx.cmd -y mcporter call cloudbase.manageApps action=deployApp serviceName=opto-hot filePath=$Root buildPath=dist framework=static installCmd= buildCmd= --output json
if ($LASTEXITCODE -ne 0) { throw "CloudBase 部署触发失败" }
Write-Host "[cloudbase-deploy] 已触发，构建完成后域名保持 https://opto-hot-a455-d3g2s3dt865d86640.webapps.tcloudbase.com"