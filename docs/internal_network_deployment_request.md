# 啄木鸟内网部署研发协助清单

## 背景

啄木鸟是 PRD 提交前的 AI 质量检查工具，用于帮助 PM 在正式评审前提前发现业务完整性、字段口径、体验流程和实现风险问题。

当前本地 Web 端和后端都可以运行，下一步希望研发协助部署到公司内网环境，供 2-6 位产品同事进行内部 Beta 试用。

## 部署目标

把啄木鸟从本地开发环境部署成一个公司内网可访问、可重启、可备份、可限流、可观测的内部 Beta 工具。

部署范围只限内网：

- 只允许公司内网、办公网络或 VPN 访问。
- 不开放公网注册。
- 不对外提供公开访问地址。
- 不直接暴露后端端口到公网。
- 试用期不承诺正式生产 SLA。

试用期数据口径：

- 允许指定 PM 在内网环境上传未脱敏真实 PRD。
- 未脱敏 PRD 只用于内部 Beta 评审、校准和反馈回流。
- 访问、下载、备份、日志和权限都按内部敏感资料处理。
- 如果 PRD 涉及合同原件、身份证号、手机号、银行账号等强敏感个人信息，仍建议先做最小化处理。

## 不做事项

- 不做公网部署。
- 不做多组织、多租户能力。
- 不做外部客户访问。
- 不开放到外部客户或公网。
- 不把未脱敏 PRD 导出文件外发到飞书群、邮件群或公网网盘。
- 不把 API key、JWT secret、cookie 或 `.env` 发给前端、同事或群聊。

## 需要研发协助的事项

### 1. 内网服务器或云上内网资源

请研发提供一台可长期运行的内网服务器或云上内网实例。

建议配置：

- Linux 优先。
- 最低 `4C8G`。
- SSD `50G+`。
- 可通过公司内网域名、固定内网 IP 或 VPN 访问。
- 能从服务端出网访问 OpenAI 兼容中转服务。
- 能访问 Git 仓库。

需要安装：

- `Python 3.10+`
- `Node 20+`
- `pnpm 8+`
- `git`
- 可选：`make`

验证命令：

```bash
python --version
node --version
pnpm --version
git --version
```

### 2. 代码拉取和依赖安装

代码信息：

- 仓库：`prd-review-agent`
- 分支：`main`
- 当前建议部署提交：以 GitLab `main` 最新提交为准；部署前请记录 `git rev-parse --short HEAD`
- 稳定代码 tag：如需固定版本，可在运维确认后从当前 GitLab `main` 打 `v0.1.5-beta`

建议部署路径：

```bash
/opt/pecker
```

初始化命令：

```bash
git clone <repo-url> /opt/pecker
cd /opt/pecker
pip install -r requirements.txt
cd web && pnpm install
```

### 3. 服务端环境变量配置

请研发只在服务端配置 `.env`，不要提交到 git，不要发给前端，不要在日志里打印。

必填项：

```bash
OPENAI_API_KEY=<服务端真实 key，单 key 兜底>
# 推荐: 多 key 池。5-6 人试用时用 5-10 个中转 key 分摊 worker 调用。
# 只放服务端 .env，不提交 git，不发前端。
OPENAI_API_KEYS=key_1=<sk...>,key_2=<sk...>,key_3=<sk...>,key_4=<sk...>,key_5=<sk...>
OPENAI_BASE_URL=<OpenAI 兼容中转地址>
OPENAI_WIRE_API=responses
OPENAI_REASONING_EFFORT=xhigh
OPENAI_WORKER_REASONING_EFFORT=medium
OPENAI_ADVISOR_REASONING_EFFORT=xhigh
OPENAI_ROUTER_REASONING_EFFORT=medium
OPENAI_DISABLE_RESPONSE_STORAGE=true
OPENAI_REQUEST_TIMEOUT=420
OPENAI_WORKER_MAX_RETRIES=1
OPENAI_ADVISOR_MAX_RETRIES=2
OPENAI_ROUTER_MAX_RETRIES=1
# 部分中转站会对有效 key 偶发返回 401/invalid_api_key；只按瞬时网关错误重试，不放宽真实鉴权失败。
PECKER_RETRY_INTERMITTENT_AUTH_401=1
PECKER_PRECHECK_TIMEOUT=90

PECKER_SIGNATURE_SECRET=<32+ hex>
PECKER_JWT_SECRET=<32+ hex>
PECKER_WEB_PASSWORD=<给内部同事登录用的密码>
PECKER_ADMIN_USERS=lvxinhang

# Web 开关：PM 内网试用建议开启可恢复任务，关闭维护人预览页。
NEXT_PUBLIC_REVIEW_JOB_MODE=1
NEXT_PUBLIC_ENABLE_INTERNAL_RUNS=0
NEXT_PUBLIC_ENABLE_V8_PREVIEW=0

PECKER_MAX_CONCURRENT=3
PECKER_MAX_CONCURRENT_MODEL_CALLS=5
PECKER_WORKER_BATCH_SIZE=4
PECKER_MODEL_CALL_QUEUE_TIMEOUT=480
PECKER_ENABLE_WORKER_TIMEOUT_RECOVERY=0
PECKER_ENABLE_ADAPTIVE_WORKER_PROMOTION=0
PECKER_MAX_WIKI_CHARS=15000
PECKER_REVIEW_ORCHESTRATOR=langgraph
PECKER_ENABLE_WORKER_GATEWAY_RECOVERY=1
PECKER_PRD_CONTEXT_MODE=auto
PECKER_PRD_CONTEXT_AUTO_CHARS=12000
PECKER_PRD_CONTEXT_PACKET_CHARS=12000

PECKER_PROFILE=chill
WIKI_PATH=./shared-wiki
REVIEWER=<部署者名字>
```

预算闸建议项：

```bash
PECKER_REVIEW_HARD_CAP_USD=3
PECKER_REVIEWER_DAILY_BUDGET_USD=30
PECKER_DAILY_BUDGET_USD=100
PECKER_MONTHLY_BUDGET_USD=500
```

密钥生成建议：

```bash
bash scripts/gen-secrets.sh > .env
chmod 600 .env
```

然后再手动补齐 OpenAI 兼容 API 配置和 Web 登录密码。

### 4. 后端服务部署

后端启动命令：

```bash
cd /opt/pecker
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

请研发用 `systemd`、`pm2`、Docker Compose 或公司内部发布系统托管后端服务。

要求：

- 机器重启后自动拉起。
- 服务异常退出后自动重启。
- 日志可查看。
- `.env` 只对服务端进程可读。

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

预期：

- 返回 `status=ok`。
- `llm_auth.status=ok`。
- 不回显任何 `sk-*`、token、cookie 或 Authorization header。

### 5. 前端服务部署

前端构建和启动：

```bash
cd /opt/pecker/web
pnpm build
pnpm start
```

默认端口：

- 前端：`3000`
- 后端：`8000`

请研发同样用守护进程托管前端服务。

### 6. 内网访问入口

建议提供一个内网访问地址，例如：

```text
http://pecker.xxx.internal
```

或：

```text
https://pecker.xxx.internal
```

反向代理建议：

- `/` 转发到前端 `3000`。
- `/api/*` 转发到后端 `8000`。
- 只允许公司内网或 VPN 访问。
- 防火墙不要把 `8000` 后端端口直接暴露到公网。

如果公司内网已有统一网关，建议接入统一网关；如果没有，先用内网 IP + 端口也可以作为 Beta 试用入口。

### 7. 持久化目录和备份

以下目录或文件不要放在临时容器层里，需要挂盘或定期备份：

```text
workspace*
.pecker_drafts
shared-wiki
logs
event_store.jsonl
finding_outcomes.db
rule_performance_history.json
```

团队 Beta 扩到多人后，建议把真实业务 `workspace-*` 从代码仓库目录迁到内网挂盘，只在主仓保留脱敏 `workspace-sample`：

```bash
mkdir -p /mnt/pecker-workspaces
cd /opt/pecker
python scripts/migrate_workspace_to_external.py \
  --project-root /opt/pecker \
  --target-root /mnt/pecker-workspaces \
  --dry-run
```

确认 dry-run 清单无误后再执行：

```bash
python scripts/migrate_workspace_to_external.py \
  --project-root /opt/pecker \
  --target-root /mnt/pecker-workspaces \
  --apply
```

服务端 `.env` 配置：

```bash
PECKER_WORKSPACE_ROOT=/mnt/pecker-workspaces
```

迁移后 `/api/workspaces` 会优先读取 `PECKER_WORKSPACE_ROOT`，同时保留主仓里的 `workspace-sample` 作为新人演示样本。

备份要求：

- 至少每日备份一次。
- 保留最近 7-30 天。
- 明确备份位置。
- 至少演练一次恢复。

### 8. 并发和限流验证

试用期目标是支持 5-6 位 PM 同时使用。

建议配置：

```bash
PECKER_MAX_CONCURRENT=3
PECKER_MAX_CONCURRENT_MODEL_CALLS=5
PECKER_WORKER_BATCH_SIZE=4
PECKER_MODEL_CALL_QUEUE_TIMEOUT=480
PECKER_ENABLE_WORKER_TIMEOUT_RECOVERY=0
PECKER_ENABLE_ADAPTIVE_WORKER_PROMOTION=0
PECKER_ENABLE_WORKER_GATEWAY_RECOVERY=1
PECKER_REVIEW_ORCHESTRATOR=langgraph
OPENAI_WORKER_MAX_RETRIES=1
OPENAI_WORKER_REASONING_EFFORT=medium
OPENAI_API_KEYS=<服务端多 key 池>
PECKER_MAX_WIKI_CHARS=15000
PECKER_PRD_CONTEXT_MODE=auto
PECKER_PRD_CONTEXT_PACKET_CHARS=12000
```

部署后请研发协助做一次内网并发 smoke：

- 5-6 个账号或浏览器 session 同时发起 demo 或真实 PRD 评审。
- 后端不出现大量 401。
- 遇到 524、timeout、429、5xx 时，后端可换下一个 key 重试，日志不打印真实 `sk-*`。
- 前端不白屏。
- 失败时能看到明确提示。
- 预算闸生效。

### 9. 安全和权限

内网 Beta 阶段建议：

- 不开放注册。
- 只给指定 PM 代表登录密码。
- Web 登录密码定期轮换。
- API key 只在服务端保存。
- `.env` 权限收紧。
- 日志脱敏，不记录完整 PRD 原文和密钥。
- 未脱敏 PRD 只允许在内网试用环境流转。
- 修订稿草案、修订建议包和评审报告下载都要记录审计事件。
- 下载文件默认标记“内部资料 / 仅限内网试用 / 可能包含未脱敏 PRD 内容”。

需要明确禁止上传：

- 合同、身份证、手机号等敏感信息。
- 不能发送给第三方模型服务的内部资料。

允许上传但必须内网受控的内容：

- 未公开功能方案。
- 真实业务规则。
- 真实价格、收入、利润、商业指标。
- 真实客户名称或内部项目名称。

### 10. 监控和告警

请研发协助至少提供基础运维可见性：

- 服务是否存活。
- CPU、内存、磁盘。
- 后端 5xx 数量。
- 模型调用失败率。
- 预算拦截次数。
- 最近一次成功评审时间。

最低可接受方案：

- 服务进程日志可查。
- 健康检查失败能通知到部署负责人。
- 磁盘空间低于阈值能提醒。

### 11. 回滚方案

请研发保留上一版可运行版本。

要求：

- 记录当前部署 commit。
- 记录上一版 commit 或镜像。
- 出现严重问题时，可以 10 分钟内回滚。
- 回滚不删除历史 workspace、反馈数据和事件日志。

### 12. 数据过期清理

内网 Beta 可以上传未脱敏 PRD，部署机需要有明确的过期清理机制。默认先每天跑 dry-run 报告，确认一周无误后再开启 apply。

手动检查命令：

```bash
cd /opt/pecker
python scripts/retention_report.py --project-root /opt/pecker --format text
python scripts/retention_sweep.py --project-root /opt/pecker --dry-run --format text
```

确认规则无误后，执行清理：

```bash
cd /opt/pecker
python scripts/retention_sweep.py --project-root /opt/pecker --apply --format text
```

默认策略：

```text
.pecker_drafts/*.json       超过 30 天移入 .trash/retention
event_store.jsonl           超过 500MB gzip 归档并清空在线文件
eval_reports/*.json         超过 90 天压缩到 eval_reports/archive
logs/*.log                  超过 14 天压缩到 logs/archive
review/finding_outcomes.db  超过 180 天反馈迁入 findings_archive 后 VACUUM
.trash/retention            备份保留 7 天
```

可通过服务端 `.env` 调整：

```bash
PECKER_RETENTION_DRAFT_DAYS=30
PECKER_RETENTION_EVAL_REPORT_DAYS=90
PECKER_RETENTION_LOG_DAYS=14
PECKER_RETENTION_FINDING_DAYS=180
PECKER_RETENTION_EVENT_STORE_MAX_MB=500
PECKER_RETENTION_TRASH_DAYS=7
```

systemd timer 示例：

```ini
# /etc/systemd/system/pecker-retention.service
[Unit]
Description=Pecker retention sweep

[Service]
Type=oneshot
WorkingDirectory=/opt/pecker
EnvironmentFile=/opt/pecker/.env
ExecStart=/usr/bin/python3 /opt/pecker/scripts/retention_sweep.py --project-root /opt/pecker --apply --format text
```

```ini
# /etc/systemd/system/pecker-retention.timer
[Unit]
Description=Run Pecker retention sweep daily

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

启用命令：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pecker-retention.timer
sudo systemctl list-timers pecker-retention.timer
```

## 部署完成验收标准

### 基础可用

- 内网地址可以打开登录页。
- 使用 `PECKER_WEB_PASSWORD` 可以登录。
- 登录后可以进入 `/review`。
- 使用管理员账号 `lvxinhang` 可以打开 `/system/usage`，非管理员访问应返回 403。
- 可以打开演示模式：`/review?demo=1`。
- 演示模式可以不上传真实 PRD 走完整 UI 流程。
- 指定 PM 可以用未脱敏真实 PRD 跑内部试用流程。

### 后端健康

- `GET /api/health` 返回 `status=ok`。
- `llm_auth.status=ok`。
- 健康检查不泄露任何密钥。

### 评审链路

- 能完成一次 demo review。
- 能完成一次未脱敏真实 PRD review。
- 能下载评审报告。
- 能下载修订建议包。
- 能下载修订稿草案，且文件头部有内部资料提示。
- 部分失败时前端有明确提示，不白屏、不无限转圈。
- 评审记录可以回看。

### 并发

- 5-6 位 PM 同时发起评审时，服务不崩。
- 不出现认证互踢。
- 不出现大量 401。
- 模型调用并发闸生效。

### 数据和安全

- `.env` 不在 git。
- 前端构建产物不包含 API key。
- 日志不包含 `sk-*`。
- 持久化目录已挂盘或已纳入备份。

## 给研发的简短说明

本次不是公网正式上线，而是内网 Beta 部署。目标是让 2-6 位产品同事通过内网 Web 页面试用啄木鸟，验证 PRD 评审流程、反馈闭环、稳定性和成本控制。部署重点不是复杂架构，而是内网可访问、服务可重启、数据可备份、密钥不泄露、失败可排查。

## 本次上线前验证记录（2026-05-09）

本地已完成以下部署前验证：

```bash
python -m pytest tests -q
# 1436 passed, 4 warnings

cd web && npm test -- --run tests/review-job-resume.test.ts tests/draft-persistence.test.ts tests/prd-anchor.test.ts tests/review-eta.test.ts tests/report-markdown-copy.test.ts tests/pm-friendly-navigation-copy.test.ts tests/login-timeout.test.ts tests/workspace-entry.test.ts tests/revision-downloads.test.ts tests/report-contract-store.test.ts tests/extract-worker-errors.test.ts
# 80 passed

cd web && npx tsc --noEmit
# passed

cd web && npm run build
# passed

git diff --check
# passed
```

本次重点包含：

- 登录失败不再长时间卡在“登录中”。
- Phase 2 评审支持后台 job 和断线续接，刷新后尽量接回原任务，不强制重跑。
- 逐条确认阶段会保存评审结果和 PM 决策草稿，降低网络断开后的丢失风险。
- 管理员 `lvxinhang` 可以通过 `/system/usage` 查看团队试用概览、最近任务、活跃任务和反馈摘要。
- 资料库选择后可以返回新建资料库入口。
- Worker 部分失败时保留已产出的评审意见，并给 PM 友好提示。
- LangGraph 主编排默认启用，`PECKER_REVIEW_ORCHESTRATOR=legacy` 可作为紧急回滚开关。
- DeepSeek flash 仅作为中转站临时失败的备用线路，真实 key 只放服务端 `.env`。
