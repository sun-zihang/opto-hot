# opto-hot 本地每 6 小时自动更新脚本（配合 install-schedule.ps1 的计划任务使用）
# 手动运行：powershell -ExecutionPolicy Bypass -File scripts\auto-update.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[auto-update] 开始采集 $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
python collector\collect.py --limit 25
if ($LASTEXITCODE -ne 0) { Write-Host "[auto-update] 采集失败，跳过推送"; exit 1 }

git add data dist
if (-not (git diff --cached --quiet)) {
  git commit -m "chore: 本地定时刷新光电热点数据 $(Get-Date -Format 'yyyy-MM-ddTHH:mmZ')"
  git push origin master
} else {
  Write-Host "[auto-update] 数据无变化，跳过提交"
}

# 可选：如果存在 scripts\cloudbase-deploy.ps1，则执行 CloudBase 重新部署
$cb = Join-Path $PSScriptRoot "cloudbase-deploy.ps1"
if (Test-Path $cb) { Write-Host "[auto-update] 调用 CloudBase 部署脚本"; & $cb }

Write-Host "[auto-update] 完成 $(Get-Date -Format 'yyyy-MM-dd HH:mm')"