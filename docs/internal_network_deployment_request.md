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
- 当前建议部署提交：以交付包 `VERSION.txt` 记录为准
- 稳定代码 tag：`v0.1.4-beta`，如需包含真实 PRD 下载能力请使用交付包记录的更新提交

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
OPENAI_API_KEY=<服务端真实 key>
OPENAI_BASE_URL=<OpenAI 兼容中转地址>
OPENAI_WIRE_API=responses
OPENAI_REASONING_EFFORT=xhigh
OPENAI_DISABLE_RESPONSE_STORAGE=true
OPENAI_REQUEST_TIMEOUT=360
OPENAI_WORKER_MAX_RETRIES=0

PECKER_SIGNATURE_SECRET=<32+ hex>
PECKER_JWT_SECRET=<32+ hex>
PECKER_WEB_PASSWORD=<给内部同事登录用的密码>
PECKER_ADMIN_USERS=lvxinhang

PECKER_MAX_CONCURRENT=3
PECKER_MAX_CONCURRENT_MODEL_CALLS=3
PECKER_MODEL_CALL_QUEUE_TIMEOUT=240
PECKER_ENABLE_WORKER_TIMEOUT_RECOVERY=0

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
PECKER_MAX_CONCURRENT_MODEL_CALLS=3
PECKER_MODEL_CALL_QUEUE_TIMEOUT=240
PECKER_ENABLE_WORKER_TIMEOUT_RECOVERY=0
```

部署后请研发协助做一次内网并发 smoke：

- 5-6 个账号或浏览器 session 同时发起 demo 或真实 PRD 评审。
- 后端不出现大量 401。
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
