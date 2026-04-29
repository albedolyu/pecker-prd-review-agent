# 啄木鸟 CI 真实 P/R 测试 — Self-hosted Runner 操作手册

**目标读者**: 项目维护者 (PM 或 dev), 准备给 PR 加真实 worker 跑的 P/R 回归 gate.
**预计耗时**: 30-45 分钟首次配置, 之后无人值守.

> **如果你现在不想/不能配 self-hosted runner**, 跳到 [§7 Fallback 模式](#7-fallback-没有-self-hosted-runner-怎么办).

---

## 0. TL;DR — 一键脚本

| 平台 | 命令 |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts\setup_runner_windows.ps1` |
| Linux/macOS | `bash scripts/setup_runner_linux.sh` |

脚本只做基础: 装 Python/Node/CLI, 下 GitHub runner. **GitHub token + claude login 仍需手动做**, 详见下文 §2 / §3.

---

## 1. 为什么需要 self-hosted runner

GitHub-hosted runner 的限制让我们无法在云端跑真实 worker:

1. **claude CLI OAuth** — `claude login` 写本地 keychain, GH runner 每次重置, 无法持久化登录态
2. **codex CLI ChatGPT Pro OAuth** — 同上, 而且 codex 没有 API key 模式
3. **DEEPSEEK_API_KEY 安全性** — 进 GitHub Secrets 后所有 PR 作者都能 echo 出来 (在恶意 fork PR 里), 不安全

**Self-hosted runner** 把 CI executor 跑在你自己的服务器/开发机上:
- claude CLI 一次登录, 长期复用
- API key 留在服务器 `.env`, 不暴露给 PR 作者
- runner label 隔离: `pecker-runner` 只接啄木鸟 jobs

### 推荐部署位置 (优先级排序)

1. **专用 dev 服务器** (推荐): Linux x86_64, 独立的虚拟机或物理机
2. **PM 的开发机**: 平时 idle 时段跑 CI, 注意会占用本机网络/CPU
3. **公司内部服务器**: 找 IT 申请一台, 走公司 LAN 注册

---

## 2. 机器准备

### 推荐配置

| 维度 | 最低 | 推荐 |
|---|---|---|
| OS | Ubuntu 22.04 / Win10+ / macOS 13+ | Ubuntu 22.04 LTS |
| CPU | 2 vCPU | 4 vCPU |
| 内存 | 4GB | 8GB |
| 磁盘 | 30GB | 50GB |
| 网络 | 公网出站可达 GitHub + Anthropic + DeepSeek | 千兆 + 稳定低延迟 |

> 注意: runner **不需要公网入站** (runner 主动拉 jobs, GitHub 不回连).

### 软件依赖 (Linux)

```bash
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3-pip git curl jq

# Node.js 20 (claude CLI 依赖)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt-get install -y nodejs

# claude CLI
sudo npm install -g @anthropic-ai/claude-code

# codex CLI (可选, 项目用 codex 才装)
sudo npm install -g @openai/codex
```

### 软件依赖 (Windows)

PowerShell (管理员):

```powershell
# winget 装基础 (Win11 自带, Win10 需先装 App Installer)
winget install -e --id Python.Python.3.11
winget install -e --id Git.Git
winget install -e --id OpenJS.NodeJS.LTS

# 重启 PowerShell 让 PATH 生效, 然后:
npm install -g @anthropic-ai/claude-code
npm install -g @openai/codex   # 可选
```

或直接跑 `scripts\setup_runner_windows.ps1`.

---

## 3. 注册 self-hosted runner

### 3.1 拿 runner token (一次性, 15 分钟有效)

1. 打开浏览器: `https://github.com/<owner>/<repo>/settings/actions/runners`
2. 点 **New self-hosted runner** 按钮
3. 选对应 OS (Linux x64 / Windows / macOS)
4. **复制页面给的 token** (形如 `AAAxxx...`, 仅 15 分钟有效, 用完即扔)

> 不要把 token 提交进代码库. 它是一次性凭证, 用完后 GitHub 会作废.

### 3.2 服务器上注册 (Linux)

```bash
# 建专用账户跑 runner (最小权限)
sudo useradd -m -s /bin/bash actions
sudo -u actions -i

# 进 actions 账户后:
mkdir actions-runner && cd actions-runner

# 下载 runner (检查 https://github.com/actions/runner/releases 用最新)
RUNNER_VERSION="2.317.0"
curl -o runner.tar.gz -L \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
tar xzf runner.tar.gz

# 配置 (用你刚拷贝的 GitHub token 替换 <GITHUB_RUNNER_TOKEN>)
./config.sh \
  --url https://github.com/<owner>/<repo> \
  --token <GITHUB_RUNNER_TOKEN> \
  --labels self-hosted,pecker-runner \
  --name pecker-runner-1 \
  --work _work \
  --unattended
```

> **关键**: `--labels` 必须包含 `pecker-runner`, 因为 workflow 用 `runs-on: [self-hosted, pecker-runner]` 选机器.

### 3.3 服务器上注册 (Windows)

PowerShell (管理员):

```powershell
# 建工作目录
New-Item -ItemType Directory -Force C:\actions-runner | Set-Location

# 下载 runner
$RUNNER_VERSION = "2.317.0"
Invoke-WebRequest -OutFile runner.zip -Uri `
  "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-win-x64-$RUNNER_VERSION.zip"
Expand-Archive -Path runner.zip -DestinationPath . -Force

# 配置 (替换 <GITHUB_RUNNER_TOKEN>)
.\config.cmd `
  --url https://github.com/<owner>/<repo> `
  --token <GITHUB_RUNNER_TOKEN> `
  --labels self-hosted,pecker-runner `
  --name pecker-runner-1 `
  --work _work `
  --unattended
```

### 3.4 装成系统服务 (开机自启)

**Linux** (在 actions 账户内):
```bash
sudo ./svc.sh install actions
sudo ./svc.sh start
sudo ./svc.sh status   # 看 active (running)
```

**Windows** (PowerShell 管理员):
```powershell
.\svc.cmd install
.\svc.cmd start
.\svc.cmd status
```

---

## 4. 配 CLI 登录态 + API keys

### 4.1 claude CLI 登录 (一次性)

**Linux**:
```bash
sudo -u actions -i
claude login
# 命令会输出一个 URL, 浏览器打开 https://claude.ai/login,
# 按提示拷贝 OAuth code 粘回终端.
# 完成后 token 存在 ~/.claude/credentials.json.
```

**Windows**:
```powershell
# 在 runner 服务对应的 Windows 用户下跑 (默认 NT AUTHORITY\NetworkService 不能交互登录,
# 建议把服务改成跑在你的桌面账户下: services.msc → actions.runner.* → 属性 → 登录)
claude login
# 同样的浏览器流程
```

> **关键**: claude login 时弹出的浏览器必须能交互. 如果 runner 跑在 headless 服务器, 在另一台有桌面的机器登录, 然后把 `~/.claude/credentials.json` (Linux) 或 `%USERPROFILE%\.claude\credentials.json` (Windows) 拷过去.

### 4.2 codex CLI 登录 (可选)

```bash
codex login
# token 存 ~/.codex/auth.json
```

### 4.3 DeepSeek API key (用于 NLI 二层校验)

获取 key:
1. 浏览器打开 `https://platform.deepseek.com/api_keys`
2. 注册/登录, 创建 API key (形如 `sk-xxxxx`, 32 chars+)
3. 充值 $5 起 (跑 100 次 PR 大约用 $1-2)

**Linux** — 写到 actions 账户的 profile (持久):
```bash
sudo -u actions -i
echo 'export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx' >> ~/.profile
echo 'export ANTHROPIC_API_KEY=sk-ant-xxxxx' >> ~/.profile  # 可选, 走 native API 时用
source ~/.profile
```

**Windows** — 用户级环境变量:
```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "sk-xxxxxxxxxxxxxxxx", "User")
# 重启 runner 服务让新环境变量生效
.\svc.cmd stop
.\svc.cmd start
```

> 不要把 DEEPSEEK_API_KEY 写进 `.github/workflows/*.yml` 或 GitHub Secrets — 那样 fork PR 作者能用 `echo $DEEPSEEK_API_KEY` 在 workflow 里偷 key.

---

## 5. 验证 runner 接入

### 5.1 UI 上看到 runner 在线

`https://github.com/<owner>/<repo>/settings/actions/runners` → 应该看到 `pecker-runner-1` 状态 **Idle** (绿点).

### 5.2 跑 health check workflow (推荐, 不烧 token)

把下面这段存为 `.github/workflows/runner_health.yml`:

```yaml
name: Self-hosted runner health
on:
  workflow_dispatch:
jobs:
  check:
    runs-on: [self-hosted, pecker-runner]
    steps:
      - shell: bash
        run: |
          echo "=== Environment ==="
          echo "PATH=$PATH"
          which python || which python3
          python --version 2>&1 || python3 --version
          which claude && claude --version || echo "WARN: claude CLI 缺"
          [ -n "${DEEPSEEK_API_KEY:-}" ] && echo "DEEPSEEK_API_KEY: set ($(echo "$DEEPSEEK_API_KEY" | head -c 8)...)" || echo "WARN: DEEPSEEK_API_KEY 缺"
          echo "=== Disk ==="
          df -h .
```

到 Actions 页 → `Self-hosted runner health` → **Run workflow** → 选 main → 看输出.

### 5.3 触发真 regression workflow

改一行 `review/prompting.py` 的注释 (不影响逻辑), 提 PR. Actions 页应看到 **Rule Regression (real worker on self-hosted)** 跑起来.

如果 30 秒还没分配 runner, 看 runner 日志:

**Linux**:
```bash
sudo journalctl -u actions.runner.* -f
```

**Windows**: 事件查看器 → 应用程序日志 → 搜 `actions-runner`.

---

## 6. 运维 checklist

### 日常 (每周)

- [ ] runner 服务存活: Linux `systemctl is-active actions.runner.*` / Windows `Get-Service actions.runner.*`
- [ ] 磁盘空间: `df -h` (Linux) / `Get-PSDrive C` (Windows), 大于 80% 时清 `_work/<repo>/<repo>/.tmp-pytest`

### 月度

- [ ] runner 自动更新: GitHub 在 PR runner 启动前会自动 update binary, 但 OS-level 服务器要自己跑 `apt upgrade` / Windows Update
- [ ] claude CLI token 还有效: `claude --version` 不报错 (token 一般 1 年, 过期前 GH 会先报 401)
- [ ] DeepSeek 账户余额: dashboard 看, 余额低于 $1 时充值 (key 用尽 → workflow 跑到一半 fail, 但 NLI 二层有 fallback)
- [ ] runner version 更新: 看 https://github.com/actions/runner/releases, 大版本号变化时手动重装

### 故障排查

| 症状 | 排查方向 |
|---|---|
| runner 突然下线 | `journalctl -u actions.runner.* --since "1 hour ago"`, 看是否 OOM / 网络中断 |
| OOM | 升内存或减 PECKER_MAX_CONCURRENT (env var) |
| PR 提了不跑 | 检查 workflow `paths` 列表是否真改到了 (没改对应 path 不触发) |
| 卡 in_progress 不动 | 检查 claude CLI 登录态: `claude auth status`, 过期跑 `claude setup-token` |
| `Error: claude CLI not found` | runner 上 claude CLI 没装到 PATH. `which claude` 看路径, 缺则 `npm install -g @anthropic-ai/claude-code` |
| `RateLimitError: 429 from anthropic` | 公共 Claude 账户被刷限了. 减并发 (PECKER_MAX_CONCURRENT=1) 或换专用账户 |
| `verify.nli 全采样失败` | DEEPSEEK_API_KEY 失效. 检查 env var, 重启 runner 服务 |
| `regression 全 0 / FN 飙升` | 大概率 prompt 改坏了 (worker 不报任何东西). **不要 update-baseline 蒙混**, 看 result.json 里每条 rule 的 `worker_finding_count` |

### 凭证管理铁律

- DEEPSEEK_API_KEY 等只放服务器 env, **不要进 GitHub Secrets** (PR 作者可 echo)
- runner 跑在专用账户 (`actions`), 不要给 sudo
- runner 工作区 `_work/` 不要放业务数据 (workflow 检出仓库即可)
- workflow 拉的代码可能包含恶意 (PR 投毒), CI 跑的命令最好都过白名单
- `actions` 网络代理: 出站只放行 GitHub + Anthropic + DeepSeek 三个域

---

## 7. Fallback: 没有 self-hosted runner 怎么办

完全没机器跑 self-hosted? 用 **本地 pre-push hook + manual pre-PR check** 兜底:

### 7.1 装 pre-push hook (一行命令)

```bash
python scripts/install_git_hooks.py
```

脚本会:
1. 检测 `.git/hooks/` 存在
2. 如有旧 hook → diff 给你看, 问要不要覆盖
3. 复制 `scripts/pre-push.sample` → `.git/hooks/pre-push` 并 chmod +x
4. 校验装好 (跑一次 dry-run)

详见 `docs/STABILITY_REGRESSION_TESTS.md` 的 "本地 pre-push 模式".

### 7.2 跑 manual pre-PR check 生成报告

提 PR 前, 跑:

```bash
python scripts/manual_pre_pr_check.py --output pr_check_report.md
```

会生成一份 markdown 格式的 P/R 报告, 把内容**贴到 PR description** 里作为 review 证据.

### 7.3 self-hosted vs 本地 fallback 对比

| 维度 | self-hosted CI | 本地 pre-push + manual report |
|---|---|---|
| 强制度 | PR 必跑, merge gate | 个人本地, --no-verify 可绕 |
| 反馈延迟 | push 后看 GH UI (5-15 min) | push 前本地跑 (5-10 min, push 阻塞) |
| 共享性 | 全队透明 | 每人单独装 |
| token 成本 | 由组织/runner 主账户承担 | 个人开发者账户 |
| 可见性 | PR 评论自动出 P/R | PM 手动贴报告到 PR description |

**最佳实践**: 两套都开. CI gate 是真 source of truth, pre-push 是 PM 自我兜底 (push 前就发现自己改坏了).

如果只能选一个, 团队 < 3 人时本地 fallback 模式够用; ≥ 3 人时上 self-hosted, 否则 review 责任不清.

---

## 8. 常见踩坑

### 踩坑 1: runner registered 后过几小时下线
- 原因: GitHub session token 过期, 但 service 没重启
- 修: `sudo ./svc.sh stop && sudo ./svc.sh start` 强制刷新

### 踩坑 2: workflow 跑到一半超时
- 原因: 单 PR rule_regression 跑 5-15 min, 默认 timeout 30 min, 但如果 worker 慢可能卡死
- 修: workflow yml 里 `timeout-minutes: 30` 维持, runner 机器加内存

### 踩坑 3: claude CLI 在 runner 跑但 PR 上看不到登录态
- 原因: runner service 跑的用户和你交互登录的用户不一致
- 修: `services.msc` (Win) / `systemctl edit` (Linux) 改 service 跑的 user

### 踩坑 4: DeepSeek 一调就 401
- 原因: API key 刷新过, env var 还是老的
- 修: 重设 env var + 重启 runner 服务

---

## 附录: 一键脚本说明

| 脚本 | 平台 | 做什么 |
|---|---|---|
| `scripts/setup_runner_linux.sh` | Linux | 装 Python/Node/CLI + 下 runner binary, 不做 token 注册 |
| `scripts/setup_runner_windows.ps1` | Windows | 同上 PowerShell 版 |
| `scripts/install_git_hooks.py` | 跨平台 | 装 pre-push hook 到 .git/hooks/ |
| `scripts/manual_pre_pr_check.py` | 跨平台 | 本地跑 P/R 测试, 输出 markdown 报告给 PM 贴 PR |

每个脚本顶部都有 `--help` 输出, 跑 `<script> --help` 看完整用法.
