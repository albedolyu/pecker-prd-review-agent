# Cloudflare Tunnel · 5 分钟搭内测

> 本地开 Docker Compose + Cloudflare Tunnel 暴露到公网 · 给 PM 同事试用 · 10 分钟搞定

## 两种方案选一个

| | Quick Tunnel | Named Tunnel(推荐 1 周内测) |
|---|---|---|
| 时间 | 2 分钟 | 10 分钟 |
| 需要 | 啥都不要 | Cloudflare 免费账号 + 1 个域名 |
| URL | `https://random-xxx.trycloudflare.com`· 每次重启变 | `https://pecker-preview.yourdomain.com`· 固定 |
| 白名单 | 无 · 靠团队密码防护 | Zero Trust Access 按邮箱授权 |
| 稳定性 | Ctrl+C 就断 | 重启自动连 |
| 适合 | 演示 / 当场给同事试一下 | 3 人以内稳定内测 1 周 |

---

## 方案 A · Quick Tunnel(2 分钟)

### 1. 装 cloudflared(Windows)

```powershell
# 方法 1 · winget(推荐 · 系统商店)
winget install --id Cloudflare.cloudflared -e

# 方法 2 · 下载 .exe
# https://github.com/cloudflare/cloudflared/releases/latest
# 下 cloudflared-windows-amd64.exe · 改名 cloudflared.exe · 放 C:\Tools\ 并加 PATH

# 验证
cloudflared --version
```

### 2. 起 Pecker Docker Compose

```powershell
cd C:\Users\20834\Desktop\agent\prd review
docker compose up -d api frontend

# 确认本地访问
curl http://localhost:3000  # 应该返回 HTML
curl http://localhost:8000/api/me  # 返回 401(未登录是正常的)
```

### 3. 起 Tunnel

```powershell
cloudflared tunnel --url http://localhost:3000
```

输出大概长这样:
```
Your quick Tunnel has been created! Visit it at:
https://blueberry-happy-panda-42.trycloudflare.com
```

### 4. 把 URL 发给同事

微信 / 飞书里发 URL 给同事 · 他们在浏览器打开 · 用团队密码登录。

### ⚠️ Quick Tunnel 的坑

- **SSE 会被 Quick Tunnel 切断** · Phase 2 评审 5-10 分钟的长连接可能中断(Cloudflare 对 trycloudflare 默认超时 100s)
- **你关电脑 / cloudflared 进程死了,同事全断**
- **URL 对所有人开放** · 靠 PECKER_WEB_PASSWORD 兜底 · 密码要够强

**结论**:Quick Tunnel 只适合**当面演示 / 截图分享 1-2 小时**,不适合 1 周内测。1 周内测请走方案 B。

---

## 方案 B · Named Tunnel(推荐)

### 前置

- **Cloudflare 账号**(免费):https://dash.cloudflare.com/sign-up
- **一个 Cloudflare 托管的域名**:
  - 已有企业域名?让域管把 NS 改到 Cloudflare(免费)
  - 没有?花 $10/年买一个 · 任意 TLD 都行(.com / .dev / .xyz)
  - **不能用** `.tk / .ml` 等免费域名(CF 不支持)

### 1. 装 cloudflared(同方案 A)

### 2. 登录

```powershell
cloudflared tunnel login
```

浏览器自动打开 → 选你的域名 → 授权 → 关浏览器。
证书保存在 `%USERPROFILE%\.cloudflared\cert.pem`

### 3. 创建 Tunnel

```powershell
cloudflared tunnel create pecker-preview
```

输出:
```
Created tunnel pecker-preview with id abc123-def456-...
```

记住这个 tunnel id(credentials file 用到)

### 4. 创建 DNS

```powershell
# 替换 yourdomain.com 为你的实际域名
cloudflared tunnel route dns pecker-preview pecker-preview.yourdomain.com
```

### 5. 写 config.yml

创建 `%USERPROFILE%\.cloudflared\config.yml`(PowerShell):

```powershell
@'
tunnel: pecker-preview
credentials-file: C:\Users\20834\.cloudflared\<替换为你的 tunnel-id>.json

ingress:
  # /api/* 走后端 8000 · SSE 需要长超时
  - hostname: pecker-preview.yourdomain.com
    path: /api/*
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s
      tlsTimeout: 30s
      tcpKeepAlive: 30s
      # SSE 流长连接 · 10 分钟
      keepAliveTimeout: 600s
      disableChunkedEncoding: false
      httpHostHeader: localhost:8000

  # 其他路径走前端 3000
  - hostname: pecker-preview.yourdomain.com
    service: http://localhost:3000

  - service: http_status:404
'@ | Out-File -FilePath "$env:USERPROFILE\.cloudflared\config.yml" -Encoding utf8
```

**改两处**:
1. `credentials-file` 路径里的 `<tunnel-id>` 换成第 3 步输出的真实 ID
2. `hostname` 里 `yourdomain.com` 换成你的域名

### 6. 起 Tunnel

```powershell
cloudflared tunnel run pecker-preview
```

看到 `Connection ... registered` 说明通了。

访问 `https://pecker-preview.yourdomain.com` 应该能打开 Pecker。

### 7. Zero Trust Access 白名单(⭐ 推荐做)

这一步让只有授权邮箱的 PM 同事能访问 · 避免 URL 泄露。

1. 打开 https://one.dash.cloudflare.com/ · 免费
2. Access → Applications → Add an application
3. 选 "Self-hosted"
4. 填:
   - Application name: `Pecker Preview`
   - Session duration: `24 hours`
   - Application domain: `pecker-preview.yourdomain.com`
5. Next → Policies → Add a policy:
   - Policy name: `PM 内测白名单`
   - Action: `Allow`
   - Session duration: `24 hours`
   - Configure rules:
     - Include → Emails → 把 PM 同事邮箱加进来
     - `pm1@company.com`, `pm2@company.com`, `pm3@company.com`
6. Next → Next → Add Application

### 8. 同事访问流程

1. 同事打开 `https://pecker-preview.yourdomain.com`
2. Cloudflare Access 拦截 · 让他填邮箱
3. 邮箱收到一次性验证码(PIN)
4. 填 PIN → 进 Pecker 登录页 → 输团队密码
5. 进入 `/review` v8

---

## 后台跑 Tunnel

前台跑 Ctrl+C 就断 · 放后台跑用 Windows 服务或计划任务。

### 方法 1 · Windows 服务(开机自启)

```powershell
# 管理员 PowerShell
cloudflared service install
Start-Service cloudflared
```

### 方法 2 · 启动脚本(双击运行)

创建 `C:\Tools\start-pecker-tunnel.ps1`:

```powershell
cd "C:\Users\20834\Desktop\agent\prd review"
docker compose up -d api frontend
Start-Sleep -Seconds 5
cloudflared tunnel run pecker-preview
```

---

## 常见问题

### Phase 2 SSE 卡在第一个事件不动

`config.yml` 的 `keepAliveTimeout` 必须够大:
```yaml
originRequest:
  keepAliveTimeout: 600s  # 10 分钟
```

改完重启 tunnel。

### 同事 403 Forbidden

邮箱不在 Access 白名单 · 回 Cloudflare Dashboard 加上。

### URL 返回 502 Bad Gateway

本地 Docker 没起。`docker compose ps` 看状态 · 重启:

```powershell
docker compose restart api frontend
```

### tunnel 进程意外死了

```powershell
# 查状态
cloudflared tunnel info pecker-preview

# 重启
cloudflared tunnel run pecker-preview
```

### 完全关闭 tunnel

```powershell
# 前台运行 · Ctrl+C
# 或 kill 进程
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force

# 删除 tunnel(不想要了)
cloudflared tunnel delete pecker-preview
```

---

## 内测结束后

1. 关 tunnel:`Get-Process cloudflared | Stop-Process`
2. 停 Docker:`docker compose stop`
3. 删 Access Application(Cloudflare Dashboard)
4. 删 tunnel:`cloudflared tunnel delete pecker-preview`
5. 正式部署:走内网 VM(见 `docs/deployment.md`)

---

## 关于数据风险

即便用 Named Tunnel + Access 白名单:

- PRD 明文经过 Cloudflare 边缘节点 TLS(CF 工程师理论上能读 · 实际不会)
- 团队密码经过 CF · JWT cookie 经过 CF
- 但比 ngrok 安全 10 倍(CF 不做流量采样)

**内测期间仍然遵循**:
- **只用假 PRD**(`samples/pm-preview/` 下 3 份)
- **不上传真实业务 PRD**
- 真数据请等内网 VM 批下来

详细数据分级讨论见:`docs/deployment.md` → 方案 B 章节。
