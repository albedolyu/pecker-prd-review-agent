# 啄木鸟开发环境

> 面向维护者。Web 最终用户只需要看 [啄木鸟_使用指南.md](./啄木鸟_使用指南.md)。

---

## 一图看懂架构

```
┌─────────────────┐  pnpm dev          ┌────────────────┐  uvicorn      ┌───────────────┐
│ Next.js 16      │ ◀────────────────▶ │ FastAPI        │ ◀───────────▶ │ Claude Code   │
│ web/ :3000      │  /api/* rewrite    │ api/* :8000    │  本地直连      │ CLI (子进程)  │
│ React 19 + TS   │                    │ SSE 流式评审    │                │               │
│ shadcn/ui       │                    │ 无 API Key     │                │               │
└─────────────────┘                    └────────────────┘                └───────────────┘
      ▲                                        ▲
      │ JWT HttpOnly cookie                   │ 复用现有 10 个鸟模块
      │ pecker_session                         │ parallel_review / goshawk_advisor / ...
      ▼                                        ▼
┌─────────────────┐                    ┌────────────────────────────────┐
│ app.py          │                    │ workspace-*/                   │
│ :8501 (旧版)    │                    │ ├── prd/ 待评审 PRD             │
│ Streamlit       │                    │ ├── wiki/ workspace 知识库      │
│ 迁移期 fallback │                    │ ├── raw/  业务资料              │
└─────────────────┘                    │ └── output/ 评审报告            │
                                        └────────────────────────────────┘
```

---

## 三条命令起 dev stack

在仓库根目录开三个终端:

```bash
# 终端 1 — FastAPI 后端(必需)
uvicorn api.main:app --reload --port 8000

# 终端 2 — Next.js 前端(新版,团队推荐)
cd web && pnpm dev
# 浏览器打开 http://localhost:3000

# 终端 3 — Streamlit 旧版(迁移期 fallback,可选)
streamlit run legacy/app.py --server.port 8501
# 浏览器打开 http://localhost:8501
```

---

## 必需的环境变量

在仓库根目录的 `.env`(或直接 `export`)配置:

```bash
# 必需
USE_CLAUDE_CODE=1                           # 只支持本地 CC CLI
PECKER_SIGNATURE_SECRET=<32+ 字符随机串>    # openssl rand -hex 32
PECKER_JWT_SECRET=<32+ 字符随机串>          # openssl rand -hex 32
PECKER_WEB_PASSWORD=<团队共享密码>          # 登录页会校验

# 可选
PECKER_MAX_CONCURRENT=2                     # asyncio.Semaphore 并发上限
PECKER_READONLY_USERS=张三,李四             # 这些 reviewer 不能 push/归档
WIKI_PATH=./shared-wiki                     # 全局知识库(workspace 优先)
FEISHU_APP_ID=cli_xxx                       # 飞书推送可选
FEISHU_APP_SECRET=xxx
FEISHU_REPORT_CHAT_ID=oc_xxx
```

启动时 `api/main.py` 的 `lifespan` 会校验必需项,缺失直接拒绝启动,错误信息打到 stderr。

---

## 前置工具

| 工具 | 版本 | 用途 |
|---|---|---|
| Python | 3.10+ | 后端 |
| Node | 20+ | 前端 |
| pnpm | 8+ | `web/` 的包管理(plan 钦定,不要换 npm/yarn) |
| Claude Code CLI | 最新 | 本地 agent 调用,需先 `claude login` |

Python deps:`pip install -r requirements.txt`
Web deps:`cd web && pnpm install`

---

## 测试三件套

```bash
# Python: 105 tests(parallel_review / goshawk / feedback / api auth 等)
python -m pytest tests/ -q

# Web TypeScript: 严格模式 + vitest 单测(markdown-lint 7 个 fixture)
cd web && pnpm exec tsc --noEmit && pnpm test

# Playwright E2E(需要 dev stack 先跑起来)
cd web && pnpm exec playwright test
```

零回归基线(Phase D):

- `pytest`: **105 passed**
- `tsc --noEmit`: 零 error
- `vitest`: **7/7**
- `next build`: 5 routes 静态预渲染

---

## 目录结构速查

```
prd review/
├── api/                    ← FastAPI 后端(Phase A/E)
│   ├── main.py             启动 + lifespan 校验
│   ├── deps.py             asyncio.Semaphore + JWT cookie 解析
│   ├── models.py           ReviewResult Opaque Handle + HMAC
│   ├── stream.py           SSE ReviewProgressEmitter
│   └── routes/             7 个模块(auth/workspaces/drafts/review/reports/audit/feishu)
│
├── web/                    ← Next.js 前端(Phase B-D)
│   ├── app/
│   │   ├── layout.tsx      TopBanner + Providers + Fraunces font
│   │   ├── page.tsx        → /review
│   │   ├── review/         5 阶段 wizard 入口
│   │   ├── login/          JWT 登录
│   │   └── about/          10 鸟品牌故事
│   ├── components/
│   │   ├── phases/         Phase0Upload / Phase1Precheck / Phase2Running / Phase3Confirm / Phase4Report
│   │   ├── ProgressRail.tsx 6 站点进度条
│   │   ├── RoleCard.tsx    4 态职能卡
│   │   ├── TopBanner.tsx   顶部横条
│   │   └── ui/             14 个 shadcn(base-ui)组件
│   ├── lib/
│   │   ├── roles.ts        ⭐ 术语映射 single source of truth
│   │   ├── api.ts          typed fetch + 7 个 api 模块
│   │   ├── useReviewStream.ts  POST SSE 自实现 hook
│   │   ├── store.ts        Zustand slice
│   │   ├── generateReport.ts   reviewResult → markdown
│   │   └── markdown-lint.ts    LLM 输出预检修复
│   ├── tests/              vitest 单测 + Playwright E2E
│   └── app/globals.css     Pecker 编辑部主题 token
│
├── parallel_review.py      4 worker 并行评审(保持原状 + on_worker_done callback)
├── goshawk_advisor.py      终审 meta-review
├── app.py                  Streamlit 旧版,迁移期保留
├── tests/                  Python 105 tests
└── workspace-*/            每个业务方向一个 workspace
    ├── prd/
    ├── wiki/
    ├── raw/
    └── output/
```

---

## 常见问题

### `uvicorn api.main:app` 启动失败 "PECKER_SIGNATURE_SECRET 未设置"

`.env` 没配置 2 个密钥。跑 `openssl rand -hex 32` 生成并写入 `.env`。

### `pnpm dev` 报 "Another next dev server is already running"

Next 16 的单实例锁。`taskkill //PID <pid> //F` 或换个端口 `pnpm dev --port 3001`。

### Chrome 登录后立刻被踢回 `/login`

`PECKER_JWT_SECRET` 改了之后旧 cookie 还在用。清一下 `127.0.0.1` 的 cookies 重新登录。

### 评审跑到一半停住,前端一直转圈

可能后端 SSE 断流但前端没感知。刷新 tab,Phase 2 的 AbortController 会在卸载时释放后端 semaphore。

### Python 测试某条报 `ModuleNotFoundError: api_adapter`

你在 workspace-xxx 目录下跑的,cd 回 repo 根目录。pytest 用的是相对路径 sys.path。

---

## 提交规范

和历史 commit 保持一致:

```
feat(api): ...      后端功能
feat(web): ...      前端功能
feat(branding): ... 品牌 / 术语
fix(api): ...       后端修复
docs: ...           纯文档
```

所有 commit 末尾带:
```
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## 关于 Phase A-E 的全链路

本项目经过 7 轮重构到达当前状态:

| Phase | Commit | 内容 |
|---|---|---|
| A | `b941050` | FastAPI 后端抽取 + SSE + Opaque Handle |
| A.5 | `ddd859e` | A12 补完:get_current_user 接回 JWT cookie |
| B | `765718a` | Next.js 16 + shadcn/ui 脚手架 |
| C | `5549794` | 5 阶段 wizard UI 接通后端 |
| C.5 | `16d3e6e` | 编辑部术语全链路统一 |
| D | `fbc5038` | 编辑部主题视觉(oklch 墨青 + Fraunces) |
| E | _this commit_ | E2E + 文档 + 上线前置 |

详细方案见 `C:\Users\20834\.claude\plans\frolicking-chasing-cocoa.md`(全局 plan 文件)。
