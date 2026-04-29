# 啄木鸟 git pre-push hook 一键安装 (Windows PowerShell)
#
# 实际逻辑在 install_git_hooks.py, 本脚本只是 PowerShell 友好包装.
# 仍依赖 Python 3.10+.
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1 -Shared
#   powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1 -Check
#   powershell -ExecutionPolicy Bypass -File scripts\install_git_hooks.ps1 -Force

param(
    [switch]$Shared,
    [switch]$Uninstall,
    [switch]$Check,
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Write-Host "啄木鸟 git pre-push hook 一键安装 (Windows)"
    Write-Host ""
    Write-Host "用法:"
    Write-Host "  scripts\install_git_hooks.ps1            装到 .git\hooks\pre-push"
    Write-Host "  scripts\install_git_hooks.ps1 -Shared    装到 .githooks\ (团队共享)"
    Write-Host "  scripts\install_git_hooks.ps1 -Uninstall 卸载"
    Write-Host "  scripts\install_git_hooks.ps1 -Check     检查漂移 (CI 用)"
    Write-Host "  scripts\install_git_hooks.ps1 -Force     已存在直接覆盖"
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------- 检查 Python ----------
$PythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $PythonCmd = $cmd
        break
    }
}

if (-not $PythonCmd) {
    Write-Host "[install-hooks] ERROR: 未找到 python / python3 / py 命令" -ForegroundColor Red
    Write-Host "[install-hooks] 安装: winget install -e --id Python.Python.3.11"
    exit 1
}

# ---------- 检查 git ----------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "[install-hooks] ERROR: 未找到 git" -ForegroundColor Red
    Write-Host "[install-hooks] 安装: winget install -e --id Git.Git"
    exit 1
}

# ---------- 检查在 git 仓库内 ----------
$null = & git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[install-hooks] ERROR: 当前不在 git repo 内" -ForegroundColor Red
    exit 1
}

# ---------- 组装参数 ----------
$Args = @()
if ($Shared) { $Args += "--shared" }
if ($Uninstall) { $Args += "--uninstall" }
if ($Check) { $Args += "--check" }
if ($Force) { $Args += "--force" }

$PyScript = Join-Path $ScriptDir "install_git_hooks.py"

Write-Host "[install-hooks] 走 $PythonCmd $PyScript $Args"
& $PythonCmd $PyScript @Args
exit $LASTEXITCODE
