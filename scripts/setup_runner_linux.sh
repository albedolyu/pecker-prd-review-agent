#!/usr/bin/env bash
# 啄木鸟 self-hosted runner 一键准备脚本 (Linux/macOS)
#
# 做什么:
#   1. 装 Python 3.11 + Node.js 20 + git/curl/jq
#   2. npm install -g claude CLI (+ codex 可选)
#   3. 下 GitHub Actions runner binary 到 ~/actions-runner/
#
# 不做什么 (需手动):
#   - GitHub runner token 注册 (运行后看脚本输出的提示)
#   - claude login (脚本结束后跑 `claude login` 走浏览器流程)
#   - DEEPSEEK_API_KEY 设置 (脚本结束后写到 ~/.profile)
#
# 用法:
#   bash scripts/setup_runner_linux.sh                # 默认装 claude
#   bash scripts/setup_runner_linux.sh --with-codex   # 同时装 codex
#   bash scripts/setup_runner_linux.sh --skip-deps    # 假定 deps 已装, 只下 runner
#
# 详见 scripts/CI_self_hosted_setup.md.

set -e

WITH_CODEX=0
SKIP_DEPS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --with-codex) WITH_CODEX=1; shift ;;
    --skip-deps)  SKIP_DEPS=1; shift ;;
    --help|-h)
      sed -n '2,21p' "$0"
      exit 0
      ;;
    *) echo "ERROR: 未知参数 $1"; exit 1 ;;
  esac
done

log() { echo "[setup-runner] $*"; }

OS="$(uname -s)"
case "$OS" in
  Linux*)  PLATFORM="linux" ;;
  Darwin*) PLATFORM="osx" ;;
  *)       echo "ERROR: 不支持的 OS $OS"; exit 1 ;;
esac
log "平台: $PLATFORM"

# ---------- 1. 装系统依赖 ----------
if [ "$SKIP_DEPS" = "0" ]; then
  if [ "$PLATFORM" = "linux" ]; then
    log "装 Linux 系统依赖 (sudo apt-get)..."
    sudo apt-get update
    sudo apt-get install -y python3.11 python3.11-venv python3-pip git curl jq

    if ! command -v node > /dev/null; then
      log "装 Node.js 20..."
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
      sudo apt-get install -y nodejs
    fi
  else
    # macOS
    log "macOS, 假定 brew 已装. 跑 brew install..."
    brew install python@3.11 node@20 git curl jq || true
  fi
else
  log "--skip-deps 跳过系统依赖"
fi

# ---------- 2. 装 CLI ----------
log "装 claude CLI (npm i -g)..."
sudo npm install -g @anthropic-ai/claude-code

if [ "$WITH_CODEX" = "1" ]; then
  log "装 codex CLI..."
  sudo npm install -g @openai/codex
fi

# ---------- 3. 下 runner ----------
RUNNER_VERSION="2.317.0"
RUNNER_DIR="${HOME}/actions-runner"

if [ -d "$RUNNER_DIR" ]; then
  log "WARN: $RUNNER_DIR 已存在, 跳过下载. 删掉后重跑可强制重装."
else
  log "下载 GitHub Actions runner v${RUNNER_VERSION}..."
  mkdir -p "$RUNNER_DIR"
  cd "$RUNNER_DIR"

  if [ "$PLATFORM" = "linux" ]; then
    ARCH="linux-x64"
  else
    ARCH="osx-x64"
    # ARM Mac 改成 osx-arm64
    if [ "$(uname -m)" = "arm64" ]; then
      ARCH="osx-arm64"
    fi
  fi

  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-${ARCH}-${RUNNER_VERSION}.tar.gz"
  tar xzf runner.tar.gz
  rm runner.tar.gz
  log "runner 解压到 $RUNNER_DIR"
fi

# ---------- 4. 输出后续步骤 ----------
cat <<EOF

[setup-runner] 系统准备完成, 后续手动步骤:

1. 拿 GitHub runner token:
   浏览器打开 https://github.com/<owner>/<repo>/settings/actions/runners
   点 "New self-hosted runner" → Linux → 复制 token (15 min 有效)

2. 注册 runner (cd $RUNNER_DIR):
   ./config.sh \\
     --url https://github.com/<owner>/<repo> \\
     --token <粘贴上面的 token> \\
     --labels self-hosted,pecker-runner \\
     --name pecker-runner-1 \\
     --work _work \\
     --unattended

3. 装系统服务 (开机自启):
   sudo ./svc.sh install \$(whoami)
   sudo ./svc.sh start
   sudo ./svc.sh status

4. claude CLI 登录 (浏览器流程):
   claude login

5. 设 DeepSeek API key:
   echo 'export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx' >> ~/.profile
   source ~/.profile
   sudo ./svc.sh stop && sudo ./svc.sh start  # 让 service 读到新 env

6. 验证 (浏览器看 GitHub Settings → Actions → Runners 应该 Idle):
   提个改 review/prompting.py 的 PR, 看 Actions 跑起来.

详见 scripts/CI_self_hosted_setup.md.
EOF
