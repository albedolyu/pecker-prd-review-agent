# Dev 环境搭建 + 常见坑

快速参考，针对开发机（主要 Windows，顺带 macOS/Linux）。部署到生产环境看 `deployment.md`。

---

## 最短启动

```bash
# 1. 装依赖
make install                      # pip + pnpm

# 2. 配 .env 根目录(仅后端读)
make secrets >> .env              # 生成 SIGNATURE_SECRET / JWT_SECRET
# 手动填 PECKER_WEB_PASSWORD / PECKER_ADMIN_USERS
# 可选: PECKER_ENV=dev (默认) / PECKER_DAILY_BUDGET_USD=50

# 3. 装 web/.env.local (见下 "常见坑 1")

# 4. 启动
make dev-api                      # 终端 1: uvicorn :8000
make dev-web                      # 终端 2: pnpm dev :3000

# 5. 浏览器 http://localhost:3000/login
```

---

## 常见坑

### 坑 1: Phase 1 预检 `socket hang up`（next dev proxy）

**现象**：上传 PRD → 点"开始预审" → 前端崩 / 请求挂。
Next dev log 里有：
```
Failed to proxy http://127.0.0.1:8000/api/review/precheck Error: socket hang up
```

**根因**：Next.js dev server 的 rewrite proxy 对**长请求**（precheck 要调 Claude Sonnet ~10s）会 idle timeout 断连。Phase 2 的 SSE 流也可能撞同样问题。

**修法**：在 `web/.env.local` 写：
```
NEXT_PUBLIC_SSE_BASE=http://localhost:8000
```

前端 fetch 直接打 :8000 绕开 next proxy。CORS 在 `api/main.py` 已允许 `http://localhost:3000`。重启 `pnpm dev` 生效。

**注意**：
- **必须用 `localhost` 不是 `127.0.0.1`**。登录时 cookie 种在 `localhost`，浏览器按 host 过滤 cookie，跨到 `127.0.0.1` 会丢 cookie → 所有请求 401
- `.env.local` 已被 `.gitignore`，不会进 repo

**生产部署不需要这个**：Docker / Nginx 反代不经 next dev 层，不会 socket hang up。

---

### 坑 2: Windows 本地跑 Playwright `spawn UNKNOWN`

**现象**：`pnpm exec playwright test` 所有用例挂，错误：
```
browserType.launch: spawn UNKNOWN
```
winldd 诊断："chrome-headless-shell.exe 应用程序无法正常启动"。

**根因**：某些 Windows 机器上 `chrome-headless-shell-<ver>.exe` 无法启动（VC++ Redistributable 缺失 / EDR 拦截 / 某 DLL 链问题）。

**修法**：改用系统 Chrome 跑 `chrome-local` project（`playwright.config.ts` 已配置）：
```bash
make test-e2e-local
# 等价: cd web && pnpm exec playwright test --project chrome-local
```

CI 不受影响（Ubuntu runner 没此问题，继续用 `chromium-desktop` project）。

---

### 坑 3: 登录一直 401

**症状**：反复跳回 `/login`，DevTools Network 看 `/api/me` 401。

**可能原因**：
1. 前端 base URL 是 `127.0.0.1:8000` 而浏览器 origin 是 `localhost:3000` → cookie 不发送（见坑 1）
2. `PECKER_ENV=prod` 但走 HTTP → cookie secure=true 导致不种
3. `PECKER_WEB_PASSWORD` 填错

**诊断**：
```bash
# 确认 .env 里密码
grep PECKER_WEB_PASSWORD .env

# curl 直接测登录链路 (替换密码)
curl -v -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"YOUR_PWD","reviewer":"test"}' -c /tmp/c.txt
grep pecker_session /tmp/c.txt  # 应有 cookie

# 用 cookie 测受保护端点
curl -b /tmp/c.txt http://localhost:8000/api/me
# 期望: {"reviewer":"test","readonly":false}
```

---

### 坑 4: Phase 2 SSE 流断连

**现象**：Phase 2 跑一半前端停止接收 worker_done 事件，但后端 log 还在跑。

**原因**：同坑 1 — next dev proxy 对 SSE 长连接不友好。

**修法**：同坑 1，设 `NEXT_PUBLIC_SSE_BASE=http://localhost:8000`。

---

### 坑 5: Claude CLI 未登录

**现象**：precheck / review 调用时 uvicorn log 报 `QuotaExhaustedError` 或 Claude 子进程非零退出。

**修法**：
```bash
claude login         # 在 CLI 重新登录
# 或检查
claude --version
```

---

## 验证整条链路的 curl 片段

```bash
# 1. 后端健康
curl http://localhost:8000/api/health

# 2. 登录 + 存 cookie
curl -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"pecker-beta-2026","reviewer":"test"}' \
  -c /tmp/c.txt

# 3. 列 workspace (需 cookie)
curl -b /tmp/c.txt http://localhost:8000/api/workspaces

# 4. 运维指标 (admin-only)
curl -b /tmp/c.txt http://localhost:8000/api/metrics?days=7
```

---

## 本地文件结构速查

| 文件 | 谁读 | 入 repo? |
|---|---|---|
| `.env` 根目录 | 后端 (uvicorn / run_session.py) | ❌ gitignore |
| `.env.example` 根目录 | 文档模板 | ✅ |
| `web/.env.local` | 前端 (next dev / build) | ❌ gitignore |
| `docker-compose.override.yml` | 本地 docker 部署 | ❌ gitignore |

---

## 相关

- `deployment.md` — 生产部署（Docker / GHCR / HTTPS）
- `pm-preview-guide.md` — 给 PM 的试用指南
- `../CHANGELOG.md` — 版本历史
