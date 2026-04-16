# 啄木鸟 PRD 评审系统 — 生产就绪审计报告

> 审计时间: 2026-04-15
> 审计范围: 全代码库(api/, web/, config/, 核心 Python 模块, Docker, 文档)
> 审计人: Claude Opus 4.6

---

## 总结

**可以上线,但有 2 个 blocker 需要先修。**

系统核心链路(登录 -> 上传 PRD -> 预检 -> 4 worker 并行评审 -> 苍鹰终审 -> 逐条确认 -> 报告生成/下载/归档)已经跑通。安全基础设施(JWT cookie + Opaque Handle HMAC + 路径穿越防护 + 文件权限围栏)设计合理。前端 UI 成熟度超出原型水平。

---

## 一、能上线的(稳定可用)

### 1. 认证与鉴权体系
- JWT HS256 cookie 认证,HttpOnly + SameSite=Lax,8 小时 TTL
- `get_current_user` 依赖注入统一解析,401/403 语义清晰
- `require_writer` 拦截只读用户的写操作(归档、飞书推送)
- PECKER_READONLY_USERS 列表在 JWT 签发时写入 payload,服务端不可篡改

### 2. 评审结果防篡改
- ReviewResult Opaque Handle + HMAC-SHA256 signature
- 前端 TypeScript 层面 `Readonly<ReviewResult>` + `ReadonlyArray<ReviewItem>`
- 后端 `verify_review_result` 在 confirm 时做恒时比较(防时序攻击)
- Pydantic `frozen=True` 禁止 model 层面修改

### 3. 路径穿越防护
- `get_workspace_dir()` 检查 `workspace-*` 前缀 + 禁止 `..` `/` `\\`
- `download_report()` 对 filename 做同样检查
- `check_file_permission()` 在 security.py 中对所有文件操作做目录权限围栏
- 敏感文件黑名单(.env, .sessions/, __pycache__)

### 4. 前端 5 阶段 wizard
- Phase 0 上传:拖拽 .md/.txt,草稿自动恢复(3 天 TTL)
- Phase 1 预检:wiki 扫描 + Claude 知识盲区分析
- Phase 2 评审:SSE 流式进度,4 张 RoleCard 实时状态,运行时长显示
- Phase 3 确认:逐条 accept/reject/edit 决策
- Phase 4 报告:下载 .md / 归档到 wiki / 飞书推送 三出口

### 5. 并发保护
- `asyncio.Semaphore` 限制同时评审数(默认 2),防 Claude API rate limit
- 超额请求排队,不会 reject
- `PECKER_MAX_CONCURRENT` 环境变量可调

### 6. 苍鹰超时降级
- `GOSHAWK_TIMEOUT` (dev=300s) 保护,超时后跳过终审继续出报告
- 降级信息透传到前端 SSE 事件

### 7. Worker 容错
- 断路器:最大连续 worker 失败数 `MAX_CONSECUTIVE_WORKER_FAILURES=2`
- 单 worker 最大 items 截断 `MAX_ITEMS_PER_WORKER=15`
- JSON 解析失败有重试和文本兜底解析

### 8. 错误处理 UI
- 登录错误:密码错误 / 后端未配密码 / 网络错误 分别 toast 提示
- /review guard:任何 error(401 / 网络 / 后端未启)跳登录页,不白屏
- Phase 2 错误:显示错误信息 + "重试" / "返回" 按钮
- API 层:统一 `ApiError` 类,带 status + detail

---

## 二、有风险但可接受的(已知限制,需告知团队)

### 1. 密码是明文比较
- `auth.py:51` — `if req.password != expected` 直接字符串比较
- `PECKER_WEB_PASSWORD` 存在 env var 里,明文比较
- **风险评估: 低。** 这是一个团队共享密码(不是个人密码),用于区分内外。JWT secret 和 signature secret 是真正的安全屏障。改成 bcrypt hash 是加分项,但不阻塞上线。

### 2. 没有登录 rate limit
- 登录端点 `POST /api/auth/login` 没有频率限制
- 理论上可以暴力破解团队密码
- **风险评估: 中低。** 内网部署场景暴力破解可能性低。如果暴露到公网,建议加 slowapi 或在 nginx 层做 rate limit。

### 3. Cookie secure=False
- `auth.py:74` — `secure=False` 意味着 HTTP 下 cookie 也会发送
- 注释写了 "prod 部署 HTTPS 时改 True"
- **风险评估: 取决于部署方式。** 如果走 HTTPS 反向代理,改一行就好。如果团队内网 HTTP 直连,这个值必须是 False 才能正常工作。**需要根据实际部署决定。**

### 4. CORS 白名单包含多个 dev 端口
- `api/main.py:81-88` — allow_origins 包含 localhost:3000/3300/3500
- **风险评估: 低。** 注释说明了原因(绕 Next.js dev SSE buffer),且生产模式不需要 CORS(Next.js rewrite 代理)。但建议生产环境通过 env var 收紧 origins。

### 5. 苍鹰可能超时(Opus 慢)
- Claude Opus via CLI 可能跑 10+ 分钟,`GOSHAWK_TIMEOUT=300s` 触发降级
- 降级后报告不含苍鹰交叉校验
- **风险评估: 可接受。** 已有降级机制,用户能看到报告但少了终审。prod 配置未设 GOSHAWK_TIMEOUT(会 fallback 到 dev 的 300s)。

### 6. SSE 在 Next.js dev rewrite 下可能 buffer
- Next.js dev server 的 rewrite 会 buffer streaming response
- **风险评估: 已缓解。** `next.config.ts` 已改为简单 rewrite,生产模式用 `next build + next start` 或反向代理不会有此问题。dev 模式偶尔遇到的话刷新即可。

### 7. `request.is_disconnected()` 未接入
- `api/routes/review.py:323` — `is_disconnected=lambda: False` 带 TODO 注释
- 客户端断开后后端评审任务不会自动 cancel
- **风险评估: 中低。** semaphore 在 `finally` 里释放不受影响。浪费的是 Claude API 调用成本(一次评审 ~$0.05-0.30)。

---

## 三、必须修的 Blocker(不修不能给团队用)

### BLOCKER-1: `python-jose` 未声明在依赖中

**问题:** `api/routes/auth.py` 和 `api/deps.py` 都 `from jose import JWTError, jwt`,但:
- `requirements.txt` 没有 `python-jose`
- `pyproject.toml` 的 `dependencies` 没有 `python-jose`

当前能工作是因为开发机已手动安装。新部署/Docker build 会因 `ImportError: No module named 'jose'` 启动失败。

**修复:**

```bash
# requirements.txt 追加
python-jose[cryptography]>=3.3.0

# pyproject.toml [project].dependencies 追加
"python-jose[cryptography]>=3.3.0",
```

### BLOCKER-2: Dockerfile 只覆盖 CLI 模式,不含 Web 前端 + FastAPI

**问题:** 当前 `Dockerfile` 只 COPY `*.py` + `*.md`,入口是 `run_session.py`。这是 CLI 评审模式的容器。

`docker-compose.yml` 的 `web` service 用的是 Streamlit 旧版(`streamlit run app.py`),不是 Next.js 新版。

团队如果要用 Web 版(Next.js + FastAPI),没有现成的 Docker 部署方案:
- 没有 Next.js 的 Dockerfile(需要 `pnpm install` + `pnpm build` + `pnpm start`)
- `docker-compose.yml` 没有 FastAPI service(只有 Streamlit web)
- `docker-compose.yml` 没有 Next.js service

**修复(最小方案):** 在 `docker-compose.yml` 里补两个 service:

```yaml
  api:
    build: .
    env_file: .env
    entrypoint: ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    working_dir: /app

  frontend:
    build: ./web
    ports:
      - "3000:3000"
    depends_on:
      - api
```

以及 `web/Dockerfile`:

```dockerfile
FROM node:20-slim
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@latest --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build
EXPOSE 3000
CMD ["pnpm", "start"]
```

**如果团队短期不走 Docker 部署(直接 3 条命令起 dev stack),此 blocker 降级为"建议做"。但如果要正式交付给非开发人员,Docker 方案是必须的。**

---

## 四、建议做但不阻塞(上线后迭代)

### 1. 密码改 bcrypt hash
- 当前明文比较虽不危险(团队密码),但改成 `bcrypt.hashpw` 是最佳实践
- 1 小时工作量

### 2. 登录 rate limit
- 用 `slowapi` 或 FastAPI middleware 对 `/api/auth/login` 加 5 次/分钟限制
- 防暴力破解

### 3. `secure=True` 条件化
- 从 env var `PECKER_COOKIE_SECURE` 读取,HTTPS 部署时设 True
- 或在 prod config 里 override

### 4. prod 环境补 GOSHAWK_TIMEOUT
- `config/prod.py` 当前没有 `GOSHAWK_TIMEOUT`,会 fallback 到 dev 的 300s
- 建议 prod 显式设 `GOSHAWK_TIMEOUT = 240`(更紧)

### 5. 新用户引导
- 当前没有 onboarding tooltip 或首次使用引导
- Phase 0 的操作流相对直觉(选 workspace -> 上传 PRD -> 下一步),但可以加简单指引
- 建议:Phase 0 顶部加一行灰字说明或 "首次使用?" 可折叠帮助

### 6. CSRF 保护
- 当前依赖 SameSite=Lax cookie,对 POST 请求的 CSRF 防护是基本够用的
- 如果部署到子域名环境,建议加 double-submit cookie 或 CSRF token
- 当前场景(内网单域名)SameSite=Lax 已足够

### 7. `is_disconnected` 接入
- 把 `review.py:323` 的 `lambda: False` 换成 `request.is_disconnected`
- 节省断开连接后的 Claude API 调用成本

### 8. Next.js 生产 build 验证
- DEV.md 说 `next build` 5 routes 静态预渲染成功
- 但实际上线应跑一次 `cd web && pnpm build && pnpm start` 确认无报错
- 特别注意 `next.config.ts` 的 rewrite 在生产模式下需要反向代理接管

### 9. E2E 测试补全
- 当前 Playwright E2E 是骨架(`web/tests/e2e/`),需要补充:
  - 登录 -> 上传 -> 评审 -> 下载 的 happy path
  - 错误态覆盖(后端未启动、超时等)

### 10. 审计日志持久化
- `POST /api/audit` 写入 `logs/user_actions.jsonl`
- 建议加日志轮转(按天或按大小),避免单文件无限增长

---

## 五、环境变量完整清单

| 变量 | 必需 | 说明 |
|------|------|------|
| `USE_CLAUDE_CODE` | 是 | 必须为 `1`,启用本地 Claude Code CLI |
| `PECKER_SIGNATURE_SECRET` | 是 | >= 32 字符随机串,ReviewResult HMAC 签名 |
| `PECKER_JWT_SECRET` | 是 | >= 32 字符随机串,JWT cookie 签名 |
| `PECKER_WEB_PASSWORD` | 是 | 团队共享登录密码 |
| `PECKER_MAX_CONCURRENT` | 否 | 同时评审数上限,默认 2 |
| `PECKER_READONLY_USERS` | 否 | 逗号分隔的只读用户名列表 |
| `WIKI_PATH` | 否 | 全局知识库路径,默认 `./shared-wiki` |
| `FEISHU_APP_ID` | 否 | 飞书机器人 App ID |
| `FEISHU_APP_SECRET` | 否 | 飞书机器人 App Secret |
| `FEISHU_REPORT_CHAT_ID` | 否 | 飞书推送目标群 ID |
| `PECKER_ENV` | 否 | 环境切换 `dev`/`prod`/`test`,默认 `dev` |
| `PECKER_PERMISSION_MODE` | 否 | 权限模式 `strict`/`normal`/`auto`/`plan` |

**生成密钥:** `openssl rand -hex 32`(或 `python -c "import secrets; print(secrets.token_hex(32))"`)

---

## 六、Claude API Key 配置说明

本系统**不需要 Anthropic API Key**。走的是 Claude Code CLI 本地调用:

1. 安装 Claude Code: `npm install -g @anthropic-ai/claude-code`
2. 登录: `claude login` (浏览器 OAuth)
3. 设 `USE_CLAUDE_CODE=1` 在 `.env`
4. FastAPI 启动时 `lifespan` 会校验 `claude` CLI 在 PATH 中

如果团队成员都装了 CC 并登录过,后端服务器上跑一个 `claude login` 即可。

---

## 七、上线前 checklist

- [ ] 修 BLOCKER-1: `requirements.txt` 和 `pyproject.toml` 加 `python-jose[cryptography]`
- [ ] 决定部署方式: 直接 3 条命令 vs Docker Compose
  - 如果 Docker: 修 BLOCKER-2(补 Dockerfile + compose service)
  - 如果手动起: BLOCKER-2 可延后
- [ ] 配齐 4 个必需 env var: `USE_CLAUDE_CODE`, `PECKER_SIGNATURE_SECRET`, `PECKER_JWT_SECRET`, `PECKER_WEB_PASSWORD`
- [ ] 确认服务器上 `claude` CLI 已安装且 `claude login` 过
- [ ] 跑一次 `cd web && pnpm build` 确认 Next.js 生产 build 成功
- [ ] 告知团队: 密码统一(管理员设)、评审人名字写自己(会记在报告里)
- [ ] 告知团队: 同时评审数有限(默认 2),超了会排队
