# Windows 任务计划程序: 每 30 min 跑一次 OAT 健康检查.
#
# 用法 (管理员 PowerShell):
#   .\scripts\setup_oat_task_scheduler.ps1 -RepoRoot "C:\Users\20834\Desktop\agent\prd review"
#
# 卸载:
#   Unregister-ScheduledTask -TaskName "OAT_Health_Monitor" -Confirm:$false

[CmdletBinding()]
param(
    [string]$RepoRoot = (Get-Location).Path,
    [string]$PythonBin = "python",
    [string]$TaskName = "OAT_Health_Monitor",
    [int]$IntervalMinutes = 30,
    [string]$LogPath = "$env:TEMP\oat_health.log"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RepoRoot)) {
    Write-Error "RepoRoot 不存在: $RepoRoot"
    exit 1
}

$ScriptPath = Join-Path $RepoRoot "scripts\oat_health_monitor.py"
$MetricsDb  = Join-Path $RepoRoot "workspace\metrics.db"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "找不到 $ScriptPath"
    exit 1
}

# 移除已有同名任务 (幂等)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[INFO] 已移除旧任务 $TaskName"
}

$Cmd = "cmd.exe"
$Args = "/c cd /d `"$RepoRoot`" && `"$PythonBin`" scripts\oat_health_monitor.py --auto-heal --metrics-db `"$MetricsDb`" >> `"$LogPath`" 2>&1"

$Action  = New-ScheduledTaskAction -Execute $Cmd -Argument $Args
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 365)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "啄木鸟 v2 OAT 健康检查 (Claude + Codex CLI), 每 $IntervalMinutes min 跑一次" | Out-Null

Write-Host "[OK] 已注册任务: $TaskName"
Write-Host "[INFO] 间隔: $IntervalMinutes min, 日志: $LogPath"
Write-Host "[TIP] 立即测试: Start-ScheduledTask -TaskName $TaskName"
Write-Host "[TIP] 查看下次运行: Get-ScheduledTaskInfo -TaskName $TaskName"
