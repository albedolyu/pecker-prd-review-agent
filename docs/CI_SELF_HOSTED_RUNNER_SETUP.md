# Self-hosted Runner 配置 (CI 真实 P/R 测试)

**目标读者**: 项目维护者 (PM / dev), 想给啄木鸟 PR 加真实 worker 跑的 P/R 回归 gate.
**预计耗时**: 30-45 分钟首配, 之后无人值守.
**最后更新**: 2026-04-29

---

## 0. 一句话总结

啄木鸟 CI 分两段:

1. **Static gate** (ubuntu-latest, 免费, 不烧 API token) — yaml schema / baseline 同步检查.
   定义在 `.github/workflows/rule_regression.yml`, **已上线, 无需配置**.
2. **Real worker P/R** (self-hosted, 需自配机器) — 真跑 worker 算 P/R 回归.
   定义在 `.github/workflows/rule_regression_real.yml`, **本文档教你怎么配**.

如果你只是想用 (不想配机器), 直接看 [§7 fallback 模式](#7-fallback-没机器怎么办).

---

## 1. 关联文档

| 文档 | 干嘛用 |
|---|---|
| **本文档 (CI_SELF_HOSTED_RUNNER_SETUP.md)** | 决策入口 + step-by-step |
| [scripts/CI_self_hosted_setup.md](../scripts/CI_self_hosted_setup.md) | 完整操作手册 (382 行, 含安全 / 故障排查) |
| [scripts/setup_runner_linux.sh](../scripts/setup_runner_linux.sh) | Linux/macOS 一键准备脚本 |
| [scripts/setup_runner_windows.ps1](../scripts/setup_runner_windows.ps1) | Windows 一键准备脚本 |
| [scripts/install_git_hooks.py](../scripts/install_git_hooks.py) | 本地 pre-push hook 安装器 (fallback 模式) |

> 详细操作步骤已在 `scripts/CI_self_hosted_setup.md` 中, 本文是"该看哪份"的导航 + 关键差异说明.

---

## 2. 决策树 — 我该选哪种 CI 模式

```
有专用 / 闲置服务器 (Linux 推荐) ?
├── 是 → self-hosted runner (推荐, PR 强制 gate, 团队共享)  ← §3 §4
└── 否 → 没机器
        │
        ├── 团队 < 3 人 → 本地 pre-push hook 兜底 (个人级, --no-verify 可绕)  ← §7
        │
        └── 团队 ≥ 3 人 → 上一台 mini PC 或 cloud VM 跑 self-hosted (一次性 ~$10/月)
```

> 核心权衡: self-hosted 是**强制 gate** (PR 必跑, 失败阻塞 merge), pre-push 是**自我兜底**
> (PM 自由裁量, 可 bypass). 团队规模上来后必须 self-hosted, 否则 review 责任不清.

---

## 3. 一键准备脚本

### Linux/macOS

```bash
# 1. 装系统依赖 + Node + claude CLI + 下载 runner binary
bash scripts/setup_runner_linux.sh

# 2. 装 codex (可选, 若项目用 codex)
bash scripts/setup_runner_linux.sh --with-codex

# 3. 已有 deps 跳依赖, 仅下 runner
bash scripts/setup_runner_linux.sh --skip-deps
```

脚本结束后会**输出 5 步手动操作清单** (不能自动化的部分):
1. 拿 GitHub runner token
2. 注册 runner (`./config.sh ...`)
3. 装系统服务 (`sudo ./svc.sh install`)
4. claude CLI 登录 (`claude login`, 浏览器交互)
5. 设 DEEPSEEK_API_KEY env

### Windows (PowerShell 管理员)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_runner_windows.ps1
```

同样输出手动步骤清单.

> **注意**: 一键脚本只装基础, **GitHub token 注册 + claude CLI 登录** 必须手动 (浏览器交互不能脚本化).
> 详细 token 拿取流程: [scripts/CI_self_hosted_setup.md §3.1](../scripts/CI_self_hosted_setup.md).

---

## 4. workflow runs-on 配置

### 4.1 现有 workflow

`.github/workflows/rule_regression_real.yml` 已配好:

```yaml
jobs:
  real-rule-regression:
    runs-on: [self-hosted, pecker-runner]   # ← 双 label, runner 必须同时有这两个标
    timeout-minutes: 30
```

注册 runner 时 `--labels self-hosted,pecker-runner`, GitHub 才会把 job 派给这台机.

### 4.2 触发条件 (paths 列表)

修改这些路径才跑 real worker (避免每次 PR 都烧 token):

- `review/prompting.py` / `review/worker.py` / `review/learnings_store.py`
- `review-rules/**` / `workspace-sample/review-rules/**`
- `review-dimensions.yaml`
- `scripts/rule_regression.py` / `scripts/fixtures/regression_baseline.json`
- `model_router.py` / `model_routes.yaml` / `agent_config.py`

非 prompt / 规则 / worker 改动不触发, 节省 token.

### 4.3 fallback (runner 离线)

real worker job 因 runner 离线 mark skipped 时**不阻塞 PR merge** — GitHub 默认行为.

但 static gate (`rule_regression.yml`) 是 ubuntu-latest, 永远跑. 这层不通必须修.

要在 runner 离线时**显式提示** PR 作者跑 fallback:
```yaml
# 已在 rule_regression.yml hook-drift-check job 里 continue-on-error: true 实现:
# - 检测 .githooks/pre-push 缺失 → warn
# - 不阻塞 PR, 仅提醒
```

---

## 5. 安全 checklist (运维层)

- [ ] DEEPSEEK_API_KEY / ANTHROPIC_API_KEY 只放服务器 `.env`, **不进 GitHub Secrets**
      (PR 作者可在 fork PR 里 `echo $SECRET` 偷 key)
- [ ] runner 跑在专用账户 (`actions`, Linux) / 桌面账户 (Windows), 不要给 sudo / Administrator
- [ ] runner 工作区 `_work/` 不放业务数据 (workflow 检出仓库即可)
- [ ] 网络出站白名单: 只放 GitHub + Anthropic + DeepSeek 三个域
- [ ] 月度 claude CLI token 有效性检查: `claude --version` (token 一年期, 过期前 GH 会先 401)
- [ ] DeepSeek 余额监控 (低于 $1 时充值, 默认 fallback 不会自动续费)

完整安全协议见 [scripts/CI_self_hosted_setup.md §6](../scripts/CI_self_hosted_setup.md).

---

## 6. 验证清单 (配完后)

- [ ] GitHub UI 看到 `pecker-runner-1` 状态 **Idle** (绿点)
- [ ] 跑 `runner_health.yml` (`workflow_dispatch` 手动触发) 输出 PATH / claude --version 都正常
- [ ] 改一行 `review/prompting.py` 注释提 PR, Actions 看到 **Rule Regression (real worker on self-hosted)** 跑起来
- [ ] PR 评论自动出 P/R 表格 (`Macro-P / Macro-R / 规则数`)
- [ ] 故意改坏 prompt (例: 删 worker prompt 关键段) → CI fail + 评论指出哪条 rule 跌

---

## 7. Fallback: 没机器怎么办

完全没法跑 self-hosted? 用本地 pre-push hook 兜底.

### 7.1 一键装 hook

```bash
# 推荐: 走 Makefile, 同时装 deps + hook
make install

# 或单独装 hook:
python scripts/install_git_hooks.py            # 装到 .git/hooks/pre-push (个人级)
python scripts/install_git_hooks.py --shared   # 装到 .githooks/ (团队共享)
bash scripts/install_git_hooks.sh              # bash 用户友好版
powershell scripts/install_git_hooks.ps1       # Windows 用户友好版
```

装完后 push 时**自动**跑 P/R 回归, 跌 > tolerance 阻塞 push.
绕过 (PM 自由裁量): `git push --no-verify`.

### 7.2 手工生成 PR 报告 (贴到 PR description)

```bash
python scripts/manual_pre_pr_check.py --output pr_check_report.md
```

输出 markdown 格式 P/R 报告, 拷贝粘到 PR description 作为 review 证据.

### 7.3 self-hosted vs 本地 fallback 对比

| 维度 | self-hosted CI | 本地 pre-push + manual report |
|---|---|---|
| 强制度 | PR 必跑, merge gate | --no-verify 可绕 |
| 反馈延迟 | push 后看 GH UI (5-15 min) | push 前本地阻塞 (5-10 min) |
| 共享性 | 全队透明 | 每人单独装 |
| token 成本 | 组织/runner 主账户 | 个人开发者账户 |
| 可见性 | PR 评论自动出 P/R | 手动贴报告 |

---

## 8. 故障排查 (top 5 常见踩坑)

| 症状 | 排查 |
|---|---|
| runner 注册成功但 PR 不分配 | 检查 workflow `runs-on: [self-hosted, pecker-runner]` 双 label 是否完全匹配 |
| `claude CLI not found` | runner service 跑的用户跟你登录的用户不一致, `services.msc` (Win) / `systemctl edit` (Linux) 改 service user |
| `verify.nli 全采样失败` | DEEPSEEK_API_KEY 失效, 重设 env var + 重启 runner service |
| runner 跑到一半超时 | timeout-minutes: 30 太紧, 加内存 / 减 PECKER_MAX_CONCURRENT |
| `regression 全 0 / FN 飙升` | 大概率 prompt 改坏, **不要 update-baseline 蒙混**, 看 result.json 找哪条 rule 跌 |

完整 8 类踩坑见 [scripts/CI_self_hosted_setup.md §6](../scripts/CI_self_hosted_setup.md).

---

## 9. 给 user 的最小 action 清单

1. 决定要不要上 self-hosted (按 §2 决策树)
2. 如要上 → 跑 `bash scripts/setup_runner_linux.sh` 或 `scripts\setup_runner_windows.ps1`
3. 按脚本输出的 5 步手动操作做 (拿 token / 注册 / 装服务 / claude login / 设 API key)
4. UI 验证 runner Idle, 提个测试 PR 看 real worker job 跑起来
5. 不上 → `make install` 装本地 pre-push hook 兜底

详细每步操作见 [scripts/CI_self_hosted_setup.md](../scripts/CI_self_hosted_setup.md).
