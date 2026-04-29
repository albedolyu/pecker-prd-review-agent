# OAT 续期 SOP

> OAT (claude + codex) 续期是 ship 后**最大的运维风险**。
> claude 和 codex 都是订阅制 OAT，没法搞自动 token rotation —— 一定会过期，过期了所有评审就 401。
> 这份 SOP 写细了：谁接告警、SSH 到服务器跑什么命令、续不上怎么降级。

---

## 1. OAT 是什么 + 为啥要续期

啄木鸟 v2 的所有 LLM 调用走两个本地 CLI：

| OAT | 文件位置 | 谁用 | 寿命 |
|---|---|---|---|
| **claude OAT** | `~/.claude/` 下（实际 token 在 keychain / keyring，文件层只能看 `history.jsonl` / `mcp-needs-auth-cache.json` 的 mtime） | 主 agent + 苍鹰交叉校验 + recheck | **~5 小时（订阅 OAT 心跳活性）** |
| **codex OAT** | `~/.codex/credentials.json`（或 keyring） | worker 路由（responses API） | **~5 小时（同上）** |

> **重要**：claude OAT 实际是 OAuth Access Token 的**会话活性**，不是固定一年期 API key。
> 真实过期时长取决于 Anthropic / OpenAI 的会话策略，部署观察值 ~5h（见 `OAT_CLAUDE_TTL_HOURS` 默认值）。
> 过期后所有 anthropic CLI / codex CLI 调用 **401**，同事评审全挂。

---

## 2. 自动监控（已部署，Phase 3.3 装的）

`scripts/oat_health_monitor.py` 是核心监控脚本：

- **频率**：cron 每 30min 跑一次（`scripts/setup_oat_cron.sh` 装的；Windows 用 `setup_oat_task_scheduler.ps1`）
- **检测项**：
  - token 文件是否存在
  - mtime age（超过 `OAT_CLAUDE_TTL_HOURS=5` / `OAT_CODEX_TTL_HOURS=5` 视为 expiring）
  - 主动 ping（尝试一次轻量调用，看 200/401）
- **告警**：失败时推 `FEISHU_WEBHOOK` + 邮件 fallback（如配 SMTP_*）
- **自愈尝试**：`--auto-heal` 调 `claude login --refresh` / `codex login --refresh`（失败仍告警）
- **退出码**：`0=ok/expiring (warn)`, `1=expired/missing (critical)`, `2=内部错误`

### 看监控状态

```bash
# 当前状态（手动跑一次）
python scripts/oat_health_monitor.py --auto-heal

# 看历史
tail -100 /tmp/oat_health.log

# 看 cron 是否还在
crontab -l | grep oat_health
```

---

## 3. 接到告警后 SOP

> 飞书群「啄木鸟运维」收到 OAT critical 告警 → 30 分钟内响应。
> 告警 payload 含 `vendor: claude|codex` 字段，先看是哪个失效。

### 场景 A：claude OAT 失效

1. **SSH 到服务器**：`ssh pecker@<服务器>`（或对应账户）
2. **进项目目录**：`cd /opt/pecker`（或部署路径）
3. **重新登录**：
   ```bash
   claude login
   # 输出会给一个 URL，复制 → 浏览器打开 → 登录 Anthropic 账号 → 复制 token 回服务器粘贴
   ```
4. **验证**：
   ```bash
   claude --print "echo test"
   # 应返回 "test" 字样
   ```
5. **重启后端**（确保 systemd 服务读到新 token）：
   ```bash
   systemctl restart pecker-api
   # 或 pm2 restart 啥的，看你部署方式
   ```
6. **手动跑一次 monitor 确认 ok**：
   ```bash
   python scripts/oat_health_monitor.py
   # 期望 status: ok
   ```
7. **群里报告**：飞书群「啄木鸟运维」回复「claude OAT 续期完成 @<下一次预计过期时间>」

### 场景 B：codex OAT 失效

1. SSH 到服务器
2. `codex login`（流程同 claude，浏览器交互）
3. 验证：跑 1 个测试 review
   ```bash
   python scripts/smoke_codex_worker.py
   # 或者直接发个测试评审看 worker 节点是否调通
   ```
4. 重启后端：`systemctl restart pecker-api`
5. 手动跑 monitor 确认
6. 群里报告

### 场景 C：两个都失效（偶发同时过期）

> 业务影响最大，按主从顺序续。

1. **先续 claude**（主 agent + 苍鹰 + recheck 都用，影响最大）
   - 走场景 A 步骤 1-4
2. **再续 codex**（worker 用）
   - 走场景 B 步骤 1-3
3. 一次性重启后端：`systemctl restart pecker-api`
4. 手动 monitor 确认两个都 ok
5. 群里报告

### 场景 D：自愈成功（不需要人工）

`--auto-heal` 跑通的情况下监控会自动续 1 次。如果飞书群收到「OAT 自愈成功」消息，仅作记录即可，不需要人工操作。**但**：

- [ ] 看一眼 `/tmp/oat_health.log` 确认确实 ok
- [ ] 一周内自愈 ≥ 3 次说明 TTL 估值偏高，调小 `OAT_CLAUDE_TTL_HOURS`（如 4）

---

## 4. 应急：服务降级

如果 OAT 续期超过 30 分钟未恢复（同事在催，但你还在弄），用降级方案先把服务恢复到「质量略降但不停服」。

### 方案 1：worker 切到 deepseek（推荐）

worker 路由从 codex 切到 deepseek-flash（不动 claude，主 agent 还正常）：

1. **编辑 `model_routes.yaml`**：把 `worker.*` 节点的 vendor 从 `openai` / `codex` 改成 `deepseek`
   ```yaml
   worker.structure:
     vendor: deepseek    # 原值是 openai
     model: deepseek-chat
   worker.quality:
     vendor: deepseek
     model: deepseek-chat
   # ... 其他 worker.* 同样改
   ```
2. **确保 `DEEPSEEK_API_KEY` 在 `.env`** 里且有效（`echo $DEEPSEEK_API_KEY` 验证）
3. **重启后端**：`systemctl restart pecker-api`
4. **跑一份测试 PRD 验证 worker 节点能跑通**
5. **群里发告知**：「worker 路由临时切到 deepseek，质量略降，OAT 修复后会切回」

### 方案 2：全停服等修

如果连 deepseek 也不能用（极端情况），暂停 Web 服务，PM 用 CLI（`python run_session.py`）兜底。

```bash
systemctl stop pecker-web pecker-api
# 群里发：「评审服务临时停服，30 分钟内恢复，紧急的找我」
```

### 修好后切回

OAT 修复后：

1. 改回 `model_routes.yaml`
2. `systemctl restart pecker-api`
3. 验证一份 PRD 评审跑通
4. 群里发「服务已恢复」

---

## 5. 长期改进（不是 SOP 操作，但要规划）

OAT 续期是订阅制本质上的痛，长期方案：

- [ ] 找 Anthropic 谈 long-lived token / Enterprise plan（可能要换合同）
- [ ] 找 OpenAI 谈 codex 的同等方案
- [ ] **或迁到真 API key**：`ANTHROPIC_API_KEY=sk-ant-api03-...` + `OPENAI_API_KEY=sk-proj-...`（按量付费，公司账户出钱，**不再有 OAT 续期问题**）
- [ ] 备份方案 deepseek-flash（已部分支持，方案 1 即此）

> 决策权在 [TODO 业务负责人]，按月度成本和稳定性 trade-off 决定。

---

## 6. 演练 / 验收

ship 前必须演练一次：

- [ ] 模拟过期：手动删除 `~/.claude/history.jsonl` 或改 mtime 到 24h 前
  ```bash
  # 强制让 monitor 报 expired
  touch -t 202504270000 ~/.claude/history.jsonl
  python scripts/oat_health_monitor.py
  # 期望退出码 1，飞书群收到告警
  ```
- [ ] 走完场景 A 全流程
- [ ] 验证恢复后 monitor 报 ok
- [ ] 把演练时长记下（首次 SOP 跑通用时一般 5-10 分钟，做过几次后 < 3 分钟）

---

## 7. 责任人

| 角色 | 责任 | 谁 |
|---|---|---|
| 主 oncall | 工作时间内响应 OAT 告警，30 分钟内续 | [TODO] |
| 备份 oncall | 主 oncall 不在时顶上 | [TODO] |
| 工作时间外 | 飞书群 @oncall，30 分钟内响应；非紧急可等到次日 | 上述两位轮换 |

> oncall 排班轮换周期建议 1 周 / 人，飞书群置顶「本周 oncall: XXX」。

---

## 8. 故障排查

| 症状 | 原因 | 排查 |
|---|---|---|
| `claude login` 卡在浏览器跳转 | 服务器 SSH 没有图形界面 | 复制 URL 到本地浏览器登录，token 拷回服务器粘贴即可 |
| `claude --print` 仍 401 | login 没生效 / 用户切换问题 | `whoami` 看是不是 systemd service 用的不是同一个用户；改 service `User=` 字段 |
| 自愈成功但同事仍 401 | 后端进程没重读新 token | `systemctl restart pecker-api` |
| 飞书告警收不到 | `FEISHU_WEBHOOK` 没配 / 错 | `curl -X POST $FEISHU_WEBHOOK -d '{"msg_type":"text","content":{"text":"test"}}'` 验证 |
| cron 没跑 | crontab 没装 / cron 服务没起 | `crontab -l` 看；`systemctl status cron`（Linux）/ Task Scheduler（Win） |
| monitor 输出 status: missing | token 文件压根不存在 | 第一次部署没 login 过 → `claude login` |
| TTL 频繁触发 expiring 告警 | TTL 设低了 | `.env` 里加 `OAT_CLAUDE_TTL_HOURS=8` 提一下 |

---

## 9. 相关文档

| 文档 | 用途 |
|---|---|
| [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) Phase 3.3 | OAT 监控初始安装 |
| `scripts/oat_health_monitor.py` | 监控核心脚本 |
| `scripts/setup_oat_cron.sh` | Linux/Mac cron 安装器 |
| `scripts/setup_oat_task_scheduler.ps1` | Windows Task Scheduler 安装器 |
| `model_routes.yaml` | 降级时改 worker.* vendor |

---

## 应急联系卡片 (打印贴墙上)

```
═══════════════════════════════════
   啄木鸟 OAT 急救卡
═══════════════════════════════════

OAT 失效告警? 5 分钟内做 4 件事:

1. SSH 到 <服务器IP>:
   ssh user@server

2. 看告警是哪个:
   journalctl -u pecker-oat-monitor --since "1h ago"

3. 续 token (浏览器交互):
   - claude OAT:  claude login
   - codex OAT:   codex login
   - 两个都失效:  先 claude, 后 codex

4. 验证 + 报群:
   curl -s http://localhost:8000/health | jq .
   飞书群发: "✅ OAT 已续, 服务恢复"

═══════════════════════════════════
责任人 (24h):  [TODO 主 oncall]
备份 (办公时段): [TODO 备份 oncall]
紧急升级:      [TODO 工程负责人]
═══════════════════════════════════
```
