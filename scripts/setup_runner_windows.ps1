# 啄木鸟 self-hosted runner 一键准备脚本 (Windows PowerShell)
#
# 做什么:
#   1. winget 装 Python 3.11 + Node.js 20 + Git
#   2. npm install -g claude CLI (+ codex 可选)
#   3. 下 GitHub Actions runner binary 到 C:\actions-runner\
#
# 不做什么 (需手动):
#   - GitHub runner token 注册 (脚本结束后看输出提示)
#   - claude login (脚本结束后跑 `claude login` 走浏览器流程)
#   - DEEPSEEK_API_KEY 设置 (脚本结束后用 [Environment]::SetEnvironmentVariable)
#
# 用法 (管理员 PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_runner_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup_runner_windows.ps1 -WithCodex
#   powershell -ExecutionPolicy Bypass -File scripts\setup_runner_windows.ps1 -SkipDeps
#
# 详见 scripts\CI_self_hosted_setup.md.

param(
  [switch]$WithCodex = $false,
  [switch]$SkipDeps = $false
)

$ErrorActionPreference = "Stop"

function Write-Log($msg) {
  Write-Host "[setup-runner] $msg" -ForegroundColor Cyan
}

# 检查管理员权限 (winget + svc.cmd 需要)
$IsAdmin = ([Security.Principal.WindowsPrincipal] `
  [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $IsAdmin) {
  Write-Warning "建议管理员权限运行. winget 和 svc.cmd 装服务需要管理员."
}

# ---------- 1. 装系统依赖 ----------
if (-not $SkipDeps) {
  Write-Log "装 winget 包: Python 3.11 / Node.js LTS / Git"

  $packages = @(
    @{ id = "Python.Python.3.11"; name = "Python 3.11" },
    @{ id = "Git.Git"; name = "Git" },
    @{ id = "OpenJS.NodeJS.LTS"; name = "Node.js LTS" }
  )

  foreach ($p in $packages) {
    Write-Log "  → $($p.name)"
    winget install -e --id $p.id --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
      # -1978335189 = 已装, 不算错
      Write-Warning "  $($p.name) 安装可能失败 (exit $LASTEXITCODE), 检查日志"
    }
  }

  # 让 PATH 在当前 session 生效
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [System.Environment]::GetEnvironmentVariable("Path", "User")
} else {
  Write-Log "-SkipDeps 跳过系统依赖"
}

# ---------- 2. 装 CLI ----------
Write-Log "装 claude CLI (npm i -g)..."
& npm install -g "@anthropic-ai/claude-code" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Warning "claude CLI 安装失败. 重启 PowerShell 后手动跑 'npm install -g @anthropic-ai/claude-code'"
}

if ($WithCodex) {
  Write-Log "装 codex CLI..."
  & npm install -g "@openai/codex" 2>&1 | Out-Null
}

# ---------- 3. 下 runner ----------
$RUNNER_VERSION = "2.317.0"
$RUNNER_DIR = "C:\actions-runner"

if (Test-Path $RUNNER_DIR) {
  Write-Log "WARN: $RUNNER_DIR 已存在, 跳过下载. 删掉后重跑可强制重装."
} else {
  Write-Log "下载 GitHub Actions runner v$RUNNER_VERSION..."
  New-Item -ItemType Directory -Force $RUNNER_DIR | Out-Null
  Set-Location $RUNNER_DIR

  $url = "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-win-x64-$RUNNER_VERSION.zip"
  Invoke-WebRequest -OutFile runner.zip -Uri $url
  Expand-Archive -Path runner.zip -DestinationPath . -Force
  Remove-Item runner.zip
  Write-Log "runner 解压到 $RUNNER_DIR"
}

# ---------- 4. 输出后续步骤 ----------
Write-Host ""
Write-Host "[setup-runner] 系统准备完成, 后续手动步骤:" -ForegroundColor Green
Write-Host ""
Write-Host "1. 拿 GitHub runner token:"
Write-Host "   浏览器打开 https://github.com/<owner>/<repo>/settings/actions/runners"
Write-Host "   点 'New self-hosted runner' → Windows → 复制 token (15 min 有效)"
Write-Host ""
Write-Host "2. 注册 runner (cd $RUNNER_DIR, PowerShell 管理员):"
Write-Host "   .\config.cmd ``"
Write-Host "     --url https://github.com/<owner>/<repo> ``"
Write-Host "     --token <粘贴上面的 token> ``"
Write-Host "     --labels self-hosted,pecker-runner ``"
Write-Host "     --name pecker-runner-1 ``"
Write-Host "     --work _work ``"
Write-Host "     --unattended"
Write-Host ""
Write-Host "3. 装 Windows 服务 (开机自启):"
Write-Host "   .\svc.cmd install"
Write-Host "   .\svc.cmd start"
Write-Host "   .\svc.cmd status"
Write-Host ""
Write-Host "4. claude CLI 登录 (新开一个 PowerShell, 浏览器流程):"
Write-Host "   claude login"
Write-Host ""
Write-Host "5. 设 DeepSeek API key (用户级永久):"
Write-Host "   [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxxxx', 'User')"
Write-Host "   # 然后重启 runner 服务让新 env 生效:"
Write-Host "   .\svc.cmd stop"
Write-Host "   .\svc.cmd start"
Write-Host ""
Write-Host "6. 验证 (浏览器看 GitHub Settings → Actions → Runners 应该 Idle):"
Write-Host "   提个改 review/prompting.py 的 PR, 看 Actions 跑起来."
Write-Host ""
Write-Host "详见 scripts\CI_self_hosted_setup.md."
