# 啄木鸟 v8 部署指南

> v8 前端(Next.js 16)+ v7 后端(FastAPI)部署 · 两个方案可选

本文档面向:**第一次把 v8 跑起来给同事使用** 的情况。

---

## 方案对比

| 方案 | 适用 | 优势 | 劣势 |
|---|---|---|---|
| **A · Vercel** | 快速上线 · 团队在海外或能翻墙 | 5 分钟零配置 · 自动 SSL · Preview branch | 后端需另外部署到公网(Railway / Fly / 自己机器) |
| **B · Docker Compose** | 内网部署 / 不想依赖海外服务 | 前后端同机 · 数据不出内网 · `docker compose up` 一键 | 需要一台有 Docker 的服务器 · 自己管 SSL |

**混合**:Vercel 前端 + 自机后端 也行 · Vercel 环境变量 `API_BASE_URL` 指向后端公网地址即可。

---

## 先决条件(两方案都要)

1. `.env` 文件已配(参考 `.env.example`):
   ```bash
   ANTHROPIC_API_KEY=sk-ant-...
   PECKER_WEB_PASSWORD=<团队共享密码>
   PECKER_JWT_SECRET=<32 位随机字符串>
   FEISHU_APP_ID=...  # 可选 · 飞书推送用
   FEISHU_APP_SECRET=...
   FEISHU_CHAT_ID=...
   ```

2. `workspace/` 目录存在 · 里面是各业务 workspace(如 `workspace-对外投资/`)
3. 本地能跑通 `pecker CLI`(后端) + `cd web && pnpm dev`(前端) · 再考虑部署

---

## 方案 A · Vercel

### 前端部署

1. **推 GitHub**:代码已在 main(`6a04ec1` + Suspense fix)
2. **Vercel 控制台** → Import Git Repository → 选 `xinshu001/prd-review-agent`
3. **Root Directory**:`web/`(重要 · 仓库根有 python)
4. **环境变量**:
   ```
   API_BASE_URL         = https://<你的后端公网地址>
   NEXT_PUBLIC_SSE_BASE = https://<你的后端公网地址>
   NEXT_TELEMETRY_DISABLED = 1
   ```
5. **Deploy** · 首次 build 3-5 分钟

### 后端部署选项

因为 Vercel 不跑后端 Python,你需要别的地方跑 `uvicorn api.main:app`:

| 平台 | 难度 | 说明 |
|---|---|---|
| **Railway** | ⭐ | Dockerfile 已有 · GitHub 连接一键部署 |
| **Fly.io** | ⭐⭐ | `flyctl launch` 跟引导 · 注意 ANTHROPIC_API_KEY 放 secret |
| **自己服务器** | ⭐⭐ | `docker compose up api` · 加 nginx SSL |
| **AWS Lambda / GCP Cloud Run** | ⭐⭐⭐ | FastAPI 可但 SSE 流式响应要改改 |

**最简单**:自己服务器 + Cloudflare Tunnel 暴露公网,不花钱不开 IP。

---

## 方案 B · Docker Compose(推荐内网)

### 一键启动

```bash
# 1. 构建所有镜像(api + frontend)· 首次 5-10 分钟
docker compose build api frontend

# 2. 启动
docker compose up -d api frontend

# 3. 查状态
docker compose ps
#   NAME                 STATUS    PORTS
#   prd-review-api       Up        0.0.0.0:8000->8000/tcp
#   prd-review-frontend  Up        0.0.0.0:3000->3000/tcp

# 4. 访问 · 同事在浏览器打开
#   http://<服务器-IP>:3000
```

### 打开后的流程

1. **首页** `http://<IP>:3000/` · v8 landing 页 · 点"进入评审"
2. **登录** · `/login` · 用 `.env` 里 `PECKER_WEB_PASSWORD`
3. **Phase 0→4** · 真实 API 评审流

### 网络受限(Google Fonts 被墙)· 推荐用 GHCR 预 build 镜像

build 阶段 Next.js 要下载 Geist / Geist Mono 字体。内网访问 fonts.gstatic.com 基本 100% 失败。
**推荐走 GitHub Actions 在墙外 build · 推到 GHCR · 内网只 pull**:

#### CI 侧 · 自动 build 推 GHCR(已配置)

`.github/workflows/web-docker-publish.yml` · push main 自动触发:
- 构建 `ghcr.io/xinshu001/pecker-web:latest` + `:sha-xxxxxxx`
- 约 3-5 分钟完成
- Actions 页面可以看到最新镜像 tag

#### 内网侧 · 一键拉取 + 启动

```bash
# 1. 一次性登录 GHCR
#    PAT 创建:https://github.com/settings/tokens · 勾 read:packages
#    如果 repo 是 private,另勾 repo scope
echo $GITHUB_PAT | docker login ghcr.io -u <your-github-user> --password-stdin

# 2. 用生产 compose(GHCR 镜像代替本地 build)
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull frontend
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api frontend

# 3. 升级到最新(CI 有新 main push 后)
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull frontend
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d frontend
```

#### Package visibility 配置

**首次** workflow 跑完推镜像后:
1. 打开 https://github.com/xinshu001?tab=packages
2. 找到 `pecker-web`package
3. Settings → Change package visibility → **Public**(对同事公开)或 Private(需每人 PAT)
4. 如果 repo 是 private · package 默认也是 private · 要手动改 Public 或给同事发 PAT

**固定版本部署**:
改 `docker-compose.prod.yml` 里的 `image: ghcr.io/.../pecker-web:latest`
换成 `:sha-abc1234` 或 `:v1.0.0`(打 git tag 自动生成语义化版本)。

#### 替代方案 · 本地 build + 代理(不推荐)

```bash
# 需要本地开着 Clash / v2ray · 7890 端口
docker compose build --build-arg HTTPS_PROXY=http://host.docker.internal:7890 frontend
```

### 反向代理(可选 · 同域名)

单域名部署时用 nginx 反代:

```nginx
# /etc/nginx/sites-enabled/pecker.conf
server {
    listen 443 ssl;
    server_name pecker.yourdomain.com;

    # 证书(Let's Encrypt / 内部 CA)
    ssl_certificate ...;
    ssl_certificate_key ...;

    # 前端
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API · Next.js 的 rewrites 已经把 /api/* 代理到 api 容器,
    # 但 SSE 流需要额外配置(disable buffering)
    location /api/review/run {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

### SSE 注意事项

Phase 2 评审是 SSE 流(`/api/review/run`)· 需要:
- **nginx**:`proxy_buffering off` + `proxy_read_timeout ≥ 300s`
- **前端 env**:`NEXT_PUBLIC_SSE_BASE` 指向**浏览器能直达后端**的地址(不经 rewrite)
- **Cloudflare / WAF**:关闭响应缓存 · SSE 长连接不能被切断

---

## 验证上线

部署完成后,PM 自己跑一遍完整流验证(**给同事前必做**):

1. ✅ `/` · v8 landing 可见 10 鸟头像 + 3 feature 卡
2. ✅ `/login` · 用团队密码登录成功
3. ✅ `/review`(Phase 0) · 拖 PRD 能读入 · workspace 下拉有值
4. ✅ Phase 1 · 预检自动触发 · 3 列汇总可见
5. ✅ Phase 2 · 4 worker 并行 + 苍鹰分层 + 依赖边 dash-flow
6. ✅ Phase 1.5 · 健康度检查必经节点
7. ✅ Phase 3 · 键盘 j/k/y/n/e 全生效
8. ✅ Phase 4 · 三个导出(md/wiki/飞书)都能触发(至少 md 下载)
9. ✅ `/review?v=7` · legacy 回退可用(带黄色警示)

---

## Sprint 5 v2 预留路由(同事会看到)

TopBanner 上有 "Runs" 和 "System" 两个入口,指向:

| 路径 | 真实数据? | 说明给同事 |
|---|---|---|
| `/runs/diff` | ❌ sample | "Run 对比功能,当前 sample 数据演示" |
| `/runs/:id/replay` | ❌ sample | "Audit trail 回放,v2 接真实 event_store" |
| `/system/health` | ❌ sample | "系统健康度 · v2 接 stability_daily" |
| `/system/prompts` | ❌ sample | "Prompt/Rule 透明度 · v2 接 rule_perf" |

页面顶部都有黄色"Sprint 5 · v2 预留"警示 banner 提示。

---

## 回退到 v7

如果 v8 有严重 bug:

- **URL 参数回退** · `/review?v=7`(不停机即可用)
- **前端代码回退** · `git revert 6a04ec1` 回到 v7 默认,push 重新部署
- **Docker 镜像回退** · `docker compose down frontend && docker compose up frontend` 用旧镜像 tag

legacy v7 预计保留 **2 周**(2026-05-02 前),如果 v8 稳定就删除 `?v=7` 入口和相关 v7 组件。

---

## 故障排查

### Vercel build 成功但打开白屏 / 404
- 检查环境变量 `API_BASE_URL` / `NEXT_PUBLIC_SSE_BASE` 是否填了 · 是否 https
- 查 Vercel runtime log · 看是不是 `/api/*` rewrite 404

### Docker compose build frontend 失败 · Failed to fetch `Geist` from Google Fonts
- 网络问题 · 见上面"网络受限"段
- 或者切到 Vercel build · 再把 Docker 镜像从 GHCR 拉下来

### Phase 2 SSE 卡住 / 只停在第一个事件
- nginx 没关 `proxy_buffering off`
- 或者 Cloudflare 之类的 WAF 在缓存 SSE · 关掉规则

### 登录后 `/review` 空白
- `API_BASE_URL` 没指向运行的后端 · F12 Network 看 `/api/me` 是不是 404
- 或者 JWT cookie 被 SameSite 策略拦了 · 跨域部署需要 `SameSite=None; Secure`

---

## 先给 1-2 个同事试用

**建议流程**:
1. 你自己用真实 PRD 跑 3 次完整流 · 无 bug
2. 选 1-2 个 PM 同事,面对面说一下 "System/Runs 是占位 · 别的都能用"
3. 让他们用一周 · 你收集反馈(键盘流程顺不顺 / 气质对不对 / 数据对不对)
4. 小迭代 1 轮
5. 推全员
6. 2 周后删 `?v=7` legacy 回退

---

## 下一步

- **Sprint 5 v2** · 接真实数据到 `/system/health` · `/system/prompts` · `/runs/:id/replay`
- **性能优化** · `next build` 分析 bundle · 看有没有大包可 split
- **a11y 审查** · 用 axe-core 扫一遍
- **e2e 补完** · playwright 加登录后完整流程(需 PECKER_WEB_PASSWORD 注入 CI)
