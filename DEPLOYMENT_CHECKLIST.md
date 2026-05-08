# 啄木鸟 v2 内部团队 ship checklist

> 给 ship 的人按表打钩。从空机到全员上线，按 7 个 phase 顺序做，每条都有可执行命令 / 路径。
> 目标：5-15 人 PM 团队稳定使用，不需要公网 / 不需要 PIPL 合规 / 不需要多 org。
> 配套阅读：[ONBOARDING.md](./ONBOARDING.md)（同事看的）。OAT/CLI 方案只保留为历史兜底,团队上线默认走 API key。

---

## Phase 0: pre-deploy（准备一台机器）

### 硬件 / 网络

- [ ] 一台 24/7 开机的服务器（**Linux 推荐**，Mac/Windows 也行；4C8G 起，KG 构建期内存峰值 6G）
- [ ] 公司内网域名或固定 IP（同事浏览器能访问 `:3000` + `:8000`）
- [ ] SSD ≥ 50G（workspace × N + KG entities + sqlite db + logs）
- [ ] 默认能出网到：OpenAI 兼容中转地址 / open.feishu.cn

### 系统软件

- [ ] **Python 3.10+** （`python --version` 验证）
- [ ] **Node 20+** + **pnpm 8+** （`node --version && pnpm --version` 验证）
- [ ] **OpenAI API key** 已在服务端准备好（不要发给前端或同事）
- [ ] **Claude/Codex CLI**（可选，仅本地开发兜底，不作为团队上线依赖）
- [ ] **git** 已装且能 clone

### 代码

- [ ] 仓库 clone 到服务器（路径建议 `/opt/pecker` 或用户家目录的 `~/pecker`）
- [ ] `.env.example` 拷成 `.env`（下一 phase 填）

---

## Phase 1: 凭证配置（关键）

### 1.1 OpenAI API key

> 团队上线默认走 API key,避免多人同时评审时挤占个人 CLI/OAT session。真实 key 只写服务端 `.env`,不写日志、不进 git、不出现在前端。

- [ ] `OPENAI_API_KEY=<服务端真实 key>` 已写入 `.env`
- [ ] `OPENAI_BASE_URL=<OpenAI 兼容中转地址>` 已按实际网关填写（没有中转则留空）
- [ ] `OPENAI_WIRE_API=responses`
- [ ] `OPENAI_REASONING_EFFORT=xhigh`
- [ ] `OPENAI_DISABLE_RESPONSE_STORAGE=true`
- [ ] `PECKER_MODEL_OVERRIDE=`（留空,让 route 表自动分档；临时深度压测时才设 gpt55）
- [ ] 已轮换掉任何曾在聊天、文档、截图里暴露过的 key

### 1.2 .env 必填项

- [ ] **生成 secrets**：
  ```bash
  bash scripts/gen-secrets.sh > .env
  # 然后用编辑器打开 .env 填剩下的
  ```

- [ ] `OPENAI_API_KEY=<服务端真实 key>` （团队上线必填）
- [ ] `OPENAI_BASE_URL=<OpenAI 兼容中转地址>` （如使用中转则必填）
- [ ] `OPENAI_WIRE_API=responses`
- [ ] `OPENAI_REASONING_EFFORT=xhigh`
- [ ] `OPENAI_DISABLE_RESPONSE_STORAGE=true`
- [ ] `OPENAI_REQUEST_TIMEOUT=90`
- [ ] `OPENAI_WORKER_MAX_RETRIES=0`
- [ ] `PECKER_MODEL_OVERRIDE=`
- [ ] `PECKER_SIGNATURE_SECRET=<32+ hex>` （gen-secrets.sh 已生成）
- [ ] `PECKER_JWT_SECRET=<32+ hex>` （同上）
- [ ] `PECKER_WEB_PASSWORD=<给同事用的密码>` （ONBOARDING.md 里告诉同事）
- [ ] `WIKI_PATH=./shared-wiki` （或 git clone 来的本地路径）
- [ ] `REVIEWER=<部署者名字>` （CLI 跑测试时用）
- [ ] `PECKER_PROFILE=chill` （内部团队默认 chill，少 nitpick）
- [ ] `PECKER_REVIEW_HARD_CAP_USD=3`
- [ ] `PECKER_REVIEWER_DAILY_BUDGET_USD=30`
- [ ] `PECKER_DAILY_BUDGET_USD=100`
- [ ] `PECKER_MONTHLY_BUDGET_USD=500`

### 1.3 .env 可选项

- [ ] `PECKER_MAX_CONCURRENT=3` （允许 5-6 个 PM 使用，实际评审任务排队，避免 API 被长任务拖住）
- [ ] `PECKER_MAX_CONCURRENT_MODEL_CALLS=3` （全局模型调用阀门，避免 6*4 worker 同时打满中转站）
- [ ] `PECKER_MODEL_CALL_QUEUE_TIMEOUT=45` （模型调用排队过久时快速降级，不让重跑一直卡住）
- [ ] `PECKER_ENABLE_WORKER_TIMEOUT_RECOVERY=0` （团队试用期关闭超时自动二次请求，避免中转站异常时雪上加霜）
- [ ] `PECKER_READONLY_USERS=张三,李四` （只读用户名单，逗号分隔）
- [ ] `DEEPSEEK_API_KEY=sk-...` （仅作为临时降级方案时需要）
- [ ] `FEISHU_APP_ID=cli_xxx` + `FEISHU_APP_SECRET=xxx` （飞书机器人配了再填）
- [ ] `FEISHU_VERIFY_TOKEN=v_xxx` （飞书事件订阅校验，强烈建议生产开）
- [ ] `FEISHU_REPORT_CHAT_ID=oc_xxx` （报告默认推送的群 ID）
- [ ] `FEISHU_WEBHOOK=https://...` （运维/反馈告警群 webhook，独立于报告群）

### 1.4 安全检查

- [ ] `bash scripts/gen-secrets.sh --check .env` 校验 secret 强度
- [ ] `.env` 权限 600：`chmod 600 .env`
- [ ] `.env` 不进 git（已在 `.gitignore`）

---

## Phase 2: 装依赖 + 初始化

### 2.1 装依赖

- [ ] `make install` （= pip install -r requirements.txt + cd web && pnpm install + 装 git pre-push hook）
- [ ] 验证 hook 装上：`make check-hooks` 应输出 OK 或漂移提示

### 2.2 KG 一次性构建（~30 分钟）

- [ ] `python scripts/build_kg_all.py --all-workspaces`
- [ ] 完成后看输出：`workspace-*/output/_kg/entities.json` 应存在
- [ ] 验证：`python scripts/kg_health_check.py --all` 各 workspace coverage > 80%

### 2.3 P/R baseline 一次性建立（~50 分钟）

- [ ] 选一个有完整 positive_example + negative_example 的 yaml（例 `workspace-劳动仲裁/review-rules/review-checklist.yaml`）
- [ ] `python scripts/rule_regression.py --rules-yaml workspace-劳动仲裁/review-rules/review-checklist.yaml --update-baseline`
- [ ] 验证：`scripts/fixtures/regression_baseline.json` 已生成 + `git status` 看 baseline 文件 modified
- [ ] commit baseline：`git add scripts/fixtures/regression_baseline.json && git commit -m "chore: 建立首版 regression baseline"`

### 2.4 测试全跑通

- [ ] `make test` （pytest tests/ + cd web && pnpm test 都过；零回归基线 105 passed + 7/7）
- [ ] `make lint`（ESLint + doc_coherence）
- [ ] `cd web && pnpm exec tsc --noEmit` 零 error
- [ ] `cd web && pnpm build` 5 routes 成功

---

## Phase 3: 起服务

### 3.1 后端 / 前端守护进程

> 推荐用 systemd（Linux）/ pm2（跨平台）/ Windows Task Scheduler 自动重启，避免 SSH 断开后服务挂掉。

**Linux systemd 例（保存为 `/etc/systemd/system/pecker-api.service`）：**

```ini
[Unit]
Description=Pecker FastAPI
After=network.target

[Service]
Type=simple
User=pecker
WorkingDirectory=/opt/pecker
EnvironmentFile=/opt/pecker/.env
ExecStart=/usr/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now pecker-api
systemctl status pecker-api    # 验证 active (running)
```

**前端生产构建 + 启动：**

- [ ] `cd web && pnpm build`
- [ ] `cd web && pnpm start` （生产模式，建议同样 systemd 起 `pecker-web`）

**或临时直接跑（联调期可）：**

- [ ] 终端 1：`make dev-api` （uvicorn :8000）
- [ ] 终端 2：`make dev-web` （Next.js :3000）

### 3.2 验证服务

- [ ] 浏览器访问 `http://<服务器>:3000` 看到登录页
- [ ] 用 `PECKER_WEB_PASSWORD` 登录成功，跳到 `/review`
- [ ] `curl http://<服务器>:8000/health` 返回 200（如有 health endpoint）

### 3.3 路由与成本自检

- [ ] `curl http://<服务器>:8000/api/health` 返回 `llm_auth.status=ok`
- [ ] `/api/health` 不回显任何 `sk-*` / token / base auth header
- [ ] 手动构造一次超预算 review,前端明确提示额度不足且后端不发起 LLM 调用
- [ ] `model_routes.yaml` 的团队启用 route 均为 `openai:native`

---

## Phase 4: 飞书机器人（PM 反馈闭环）

> 详细 step-by-step：[docs/FEISHU_WEBHOOK_SETUP.md](./docs/FEISHU_WEBHOOK_SETUP.md)。

### 4.1 飞书后台

- [ ] [飞书开放平台](https://open.feishu.cn/app) 创建企业自建应用
- [ ] 拿 App ID / App Secret / Verification Token，填 `.env`
- [ ] 添加机器人能力（im:message + im:resource scope）
- [ ] 事件订阅 → 请求网址 URL = `https://<域名>/api/feishu/event`（**注意 `/api` 前缀**）
- [ ] 添加事件 `im.message.receive_v1`

### 4.2 公网 HTTPS 暴露

- [ ] 推荐：Cloudflare Tunnel，详见 [docs/cloudflare-tunnel-setup.md](./docs/cloudflare-tunnel-setup.md)
- [ ] 或自有域名 + nginx + Let's Encrypt
- [ ] 飞书后台填 URL 后看到「URL 验证成功」即握手通

### 4.3 验证

- [ ] `python scripts/test_feishu_endpoint.py --base-url http://localhost:8000` 全过
- [ ] 把机器人拉进飞书群「啄木鸟反馈」
- [ ] PM 在群 @机器人发「测试」，后端 `pecker-api` 日志看到 `_handle_message` 调用
- [ ] @机器人发 `R-001 是误报，字段约定为 20`，验证落库：
  ```bash
  python -c "import sys; sys.path.insert(0, '.'); \
    from review.finding_outcomes_store import get_recent_outcomes; \
    [print(o) for o in get_recent_outcomes(limit=3)]"
  ```

---

## Phase 4.5: 已知 bug 排查

### 已知 production bug + 修复 (持续追加)

部署前确认这些已修, 部署后碰到再找开发:

| 时间 | bug | 影响 | 修复 |
|---|---|---|---|
| 2026-04-28 | SSOT extends 模式下 evidence_verify 找不到 rule_id, finding 全 retract | Phase 2 输出 0 items, 报告空 | clients/evidence_verify.py 走 rule_loader 拿全集 ([代码改动](review/evidence_verify.py:721)) |
| 2026-04-29 | Windows argv 32K 限制, 主 agent 大 system_prompt (含 31 SSOT 规则 + KG hints + tone) 触发 "claude -p 退出码 1: 提示太大了" | Windows 同事跑大 PRD 必崩 | clients/claude_cli.py:227 system_text > 6K 自动 inline 走 stdin |
| 2026-04-29 | rule_regression baseline 跑 31 条规则时 codex 子进程偶发 STATUS_INVALID_HANDLE (exit 3221225794) | 部分规则被记成 P=R=0 status=error | schema v2 已正确隔离: status=error 不进 macro 计算 + 不触发回归 |

---

## Phase 5: 多人测试（1 周试用）

### 5.1 邀请前 2-3 个 PM

- [ ] 选 2-3 个肯反馈的 PM，给 `<服务器>:3000` + `PECKER_WEB_PASSWORD`
- [ ] 把 [ONBOARDING.md](./ONBOARDING.md) 发到飞书群
- [ ] 帮第一个跑通：拖 PRD → 等 → 看报告 → 给反馈

### 5.2 收集反馈

- [ ] 每人跑 ≥ 2 个真实 PRD
- [ ] 每天看一眼 Learnings 累计：`python scripts/learnings_dashboard.py`（或 SQL `learnings.db`）
- [ ] 飞书机器人入库正常：`get_recent_outcomes` 看到 outcomes
- [ ] 看 metrics：`python scripts/quality_metrics_dashboard.py`（review duration / 错误率 / accept rate）

### 5.3 故障 / 误报积压

- [ ] 收集每日 Top 3 误报 finding，复盘是不是规则太敏感
- [ ] 必要时调 worker prompt 或 rule 阈值，跑 `python scripts/rule_regression.py` 验证 P/R 不掉

---

## Phase 6: 切量上线（全员）

### 6.1 邀请全员

- [ ] 1 周试用反馈正向 → 拉全员入群「啄木鸟反馈」
- [ ] 把 [ONBOARDING.md](./ONBOARDING.md) 钉群公告
- [ ] 全员第一周：组织一次 30 分钟 demo，过 5 阶段流程 + 反馈机制

### 6.2 起 daily / weekly cron

**Linux/Mac crontab：**

```cron
# KG 增量更新（每天凌晨 3 点扫一次新增 raw/）
0 3 * * * cd /opt/pecker && python scripts/incremental_kg_update.py --all

# Metrics 聚合（每天凌晨 4 点，保留 90 天数据）
0 4 * * * cd /opt/pecker && python scripts/setup_metrics_aggregation.py --keep-days 90

# KG 健康度周报（每周一 9 点）
0 9 * * 1 cd /opt/pecker && python scripts/kg_health_check.py --all
```

- [ ] KG 增量 cron 已装并跑过一次
- [ ] Metrics 聚合 cron 已装
- [ ] KG 健康度周报 cron 已装

### 6.3 CI（可选，开发者团队大才需要）

> 团队 < 3 人可以只用本地 pre-push hook（Phase 2.1 已装）。team ≥ 3 人推荐配 self-hosted runner。

- [ ] 决定要不要上 self-hosted runner（详见 [docs/CI_SELF_HOSTED_RUNNER_SETUP.md](./docs/CI_SELF_HOSTED_RUNNER_SETUP.md)）
- [ ] 如要上：`bash scripts/setup_runner_linux.sh` 或 `scripts\setup_runner_windows.ps1`
- [ ] 提一个测试 PR 看 `Rule Regression (real worker on self-hosted)` 跑起来
- [ ] PR 评论自动出 P/R 表格

---

## Phase 7: 故障兜底文档化

- [ ] **API key 轮换 SOP**：谁能换 key、换完重启什么服务、怎么验证
- [ ] 「挂了怎么办」流程文档化（写在飞书群置顶 / wiki 也行）
- [ ] **指定 1 个工程师 on-call**（[TODO] 主 oncall）
- [ ] **指定 1 个备份 oncall**（[TODO] 备份 oncall）
- [ ] API key 轮换演练 1 次：换测试 key → 重启后端 → `/api/health` 与测试评审通过

---

## ship 验收

最终检查（全部勾上才算 ship 成功）：

- [ ] 第 1 个 PM 跑通自己业务 PRD，拿到 ≥ 10 条 finding
- [ ] 第 2 个 PM 反馈「误报」，看 Learnings 数据库真记录（`get_recent_outcomes`）
- [ ] 第 3 周 metrics dashboard 有 ≥ 50 review × 3 PM 的真数据
- [ ] CI gate（self-hosted runner，如配）真在 PR 时跑过 1 次
- [ ] API key / 路由健康检查连续 1 周无误报或漏报
- [ ] 飞书 `_event_seen` 去重未误杀（看后端日志无 replay 重处理）
- [ ] [TODO 系统责任人]、[TODO 规则维护人]、[TODO oncall] 三个角色都有人

---

## 回滚策略（万一 ship 后炸）

- [ ] **PR 回滚**：`git revert <commit>` 然后 systemd restart
- [ ] **worker 路由降级**：改 `model_routes.yaml` 把高成本 route 临时降到 `gpt54mini` 或切到备用 provider，重启后端
- [ ] **profile 全局收紧**：`PECKER_PROFILE=chill` env 强制（已经默认）
- [ ] **Web 关停**：`systemctl stop pecker-web pecker-api`，PM 切回 CLI 用法（用 `python run_session.py`）
- [ ] **数据备份**：每天 cron 备份 `learnings.db` / `metrics.db` / `regression_baseline.json` / `workspace-*/wiki/` / `workspace-*/output/` 到外部盘

---

## 联系

| 角色 | 责任 | 谁 |
|---|---|---|
| 系统责任人 | ship + 日常运维 + 凭证 | [TODO] |
| 规则维护人 | 规则增减 + P/R baseline + worker prompt | [TODO] |
| 主 oncall | 工作时间响应故障 | [TODO] |
| 备份 oncall | 主 oncall 不在时顶上 | [TODO] |

---

## 相关文档

| 文档 | 用途 |
|---|---|
| [ONBOARDING.md](./ONBOARDING.md) | 同事 PM 第一次用看的 |
| [legacy/OAT_RENEWAL_SOP.md](./legacy/OAT_RENEWAL_SOP.md) | 历史 CLI/OAT 方案归档,团队上线不再依赖 |
| [DEV.md](./DEV.md) | 开发者指南（架构 / env / 测试） |
| [docs/MIGRATION_v1_to_v2.md](./docs/MIGRATION_v1_to_v2.md) | v1 → v2 迁移 |
| [docs/CI_SELF_HOSTED_RUNNER_SETUP.md](./docs/CI_SELF_HOSTED_RUNNER_SETUP.md) | self-hosted runner 配置 |
| [docs/FEISHU_WEBHOOK_SETUP.md](./docs/FEISHU_WEBHOOK_SETUP.md) | 飞书机器人接入 |
| [docs/cloudflare-tunnel-setup.md](./docs/cloudflare-tunnel-setup.md) | Cloudflare Tunnel HTTPS 暴露 |
