# 注册 Windows 计划任务：每天 12:00 自动运行 scripts\auto-update.ps1
param(
  [string]$TaskName = "opto-hot-update",
  [int]$IntervalHours = 6
)
$Root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Root\scripts\auto-update.ps1`"" `
  -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Daily -At "12:00"


$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force
Write-Host "已注册计划任务 $TaskName（每天 12:00 自动更新，含 git push，触发 GitHub Pages 重新部署）"
Write-Host "删除：Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"