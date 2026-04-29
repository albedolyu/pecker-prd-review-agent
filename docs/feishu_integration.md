# 飞书机器人接入完整步骤

**目标**: 让 PM 在飞书群里 @机器人 用自然语言反馈评审结果, 自动落库到 `learnings_store.db` 反哺 worker prompt.

**预计耗时**: 30-40 分钟 (首次), 之后无人值守.

**前置条件**:
- 啄木鸟 FastAPI 后端 (`api/main.py`) 已起在公网可达地址 (HTTPS, cloudflare tunnel 或反代)
- 飞书企业管理员权限或可申请飞书开发者账户

---

## 1. 整体架构

```
PM 在飞书群里
   │ "@啄木鸟 R-001 是误报, 字段约定为 20"
   ▼
飞书开放平台 (push event)
   │ POST https://<your-host>/api/feishu/event
   ▼
api/routes/feishu.py:feishu_event
   │ 1. challenge URL 验证 (首次)
   │ 2. verify_token 校验 (可选)
   │ 3. event_id 去重
   │ 4. asyncio.create_task → feishu_bot._handle_message_safe
   ▼
feishu_bot._handle_message
   │ _try_parse_feedback (启发式抽 finding_id + outcome)
   ▼
review/finding_outcomes_store::record_outcome
   │ 累计 reject ≥ 阈值 → 提示 PM 升级到 learning
   ▼
review/learnings_store.LearningsStore.add()
   │ 写 learnings.db (sqlite)
   ▼
下次评审时 review/prompting.py::_build_learnings_section 读出来注入 worker prompt
```

代码位置:
- `api/routes/feishu.py` — 生产路由 (POST /api/feishu/send + POST /api/feishu/event)
- `feishu_bot.py` — `_try_parse_feedback` / `_handle_feedback` / `_handle_message_safe`
- `review/learnings_store.py` — sqlite 持久化层
- `review/prompting.py` — `_build_learnings_section` 注入 worker prompt

---

## 2. 飞书后台配置

### 2.1 创建企业自建应用

1. 浏览器打开 [飞书开放平台](https://open.feishu.cn/app)
2. 点 **创建企业自建应用** → 填名字 (如"啄木鸟评审助手") + Logo
3. 拿到 `App ID` 和 `App Secret` (后面要写到 `.env`)

### 2.2 开通机器人能力

应用详情 → **添加应用能力** → **机器人** → 启用.

机器人功能开启后, 应用获得 `im:message` 和 `im:resource` scope 用以收发消息.

### 2.3 配置事件订阅

应用详情 → **事件订阅** → **请求网址 URL**:

```
https://<your-host>/api/feishu/event
```

> 注意是 `/api/feishu/event` (生产路由前缀 /api), 不是裸 `/feishu/event` (那是 feishu_bot.py 的独立 app).

填好后点 **保存** — 飞书会发一个 challenge ping. 看后端日志:
```
[api.feishu] 飞书 URL 验证 challenge=abc12345...
```
出现这行说明握手成功.

### 2.4 添加事件类型

事件订阅页 → **添加事件** → 搜 **接收消息 v2.0** (`im.message.receive_v1`) → 申请权限 → 提交审核.

> 国内飞书企业自建应用一般不需要审核, 提交后立即生效.

### 2.5 添加 IP 白名单 (可选)

事件订阅页 → **IP 白名单** → 把后端服务器出口 IP 加入. 防止伪造请求.

### 2.6 拷贝 Verify Token (可选)

事件订阅页 → **配置** → 复制 **Verification Token**. 写到 .env:
```
FEISHU_VERIFY_TOKEN=v_xxxxxxxxxxxxxxxx
```

启用后路由会校验每个请求的 token 字段, 不匹配返回 401.

### 2.7 把机器人拉进群 + 测试 @

在飞书群点 **+** → **添加成员** → 搜你的机器人名 → 加入.

试一条:
```
@啄木鸟评审助手 R-001 是误报
```

后端日志应该看到:
```
[bot] [feedback] on_xxxxxx → R-001 reject (id=NN)
```

---

## 3. 后端配置 (.env)

`<repo>/.env`:

```bash
# 必填 (推送报告 + 接事件)
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxx

# 推送报告默认群 ID (可选, /api/feishu/send 不传 chat_id 时用)
FEISHU_REPORT_CHAT_ID=oc_xxxxxxxxxxxxxxxx

# 事件订阅 token 校验 (可选, 强烈建议生产开)
FEISHU_VERIFY_TOKEN=v_xxxxxxxxxxxx
```

重启后端: `uvicorn api.main:app --port 8000`.

---

## 4. 公网暴露 (HTTPS)

飞书要求回调 URL 必须 HTTPS. 几种方案:

### 方案 A: Cloudflare Tunnel (推荐, 免费)
看 `docs/cloudflare-tunnel-setup.md`. 一行命令拉个隧道, 拿到 `https://pecker-preview.<cf-domain>` 形式 URL.

### 方案 B: nginx + Let's Encrypt 反代
传统方案, 需要域名 + 公网 IP.

### 方案 C: ngrok (开发期权宜)
```bash
ngrok http 8000
# 拿到的 https://xxxx.ngrok.io 填到飞书后台
```
仅用于联调验证, 别用于生产 (URL 会变).

---

## 5. 手动 smoke test (端到端)

### 5.1 起后端

```bash
cd <repo>
uvicorn api.main:app --port 8000 --host 0.0.0.0
```

### 5.2 模拟 challenge

```bash
curl -X POST http://localhost:8000/api/feishu/event \
  -H "Content-Type: application/json" \
  -d '{"challenge": "test123", "token": "v_xxxx", "type": "url_verification"}'
# 期望: {"challenge": "test123"}
```

### 5.3 模拟 PM 反馈消息

```bash
curl -X POST http://localhost:8000/api/feishu/event \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "header": {
    "event_id": "ev_smoke_001",
    "event_type": "im.message.receive_v1",
    "token": "v_xxxx"
  },
  "event": {
    "message": {
      "chat_id": "oc_test",
      "message_id": "om_test_001",
      "message_type": "text",
      "content": "{\"text\": \"@_user_1 R-001 是误报, 字段已统一约定\"}"
    },
    "sender": {"sender_id": {"union_id": "on_test_pm"}}
  }
}
EOF
# 期望: {"code": 0}
```

### 5.4 验证落库

```bash
# 查 finding_outcomes_store 的最新一条
python -c "
import sys; sys.path.insert(0, '.')
from review.finding_outcomes_store import list_recent
for r in list_recent(limit=3):
    print(r)
"
# 期望看到: finding_id='R-001', outcome='reject', pm_name='on_test_pm'
```

### 5.5 验证 learning 反哺 prompt (累计后)

发 3 次 reject (改 finding_id 不同) 后:
```bash
python scripts/feedback_v2.py list --workspace workspace-sample
# 期望: 至少看到 1 条 learning 落 sqlite
```

---

## 6. 故障排查

| 症状 | 排查方向 |
|---|---|
| 飞书后台保存 URL 报错 "URL 验证失败" | 后端日志看是不是 challenge 没收到 → tunnel 没起 / firewall 拦了 |
| @机器人无响应 | 后端日志看是否收到 event, 没收到 → 飞书后台事件订阅没勾 `im.message.receive_v1` |
| 收到事件但反馈没落库 | `_try_parse_feedback` 抽不到 finding_id → 启发式失败, PM 改写消息让它含 `R-001` 等格式 |
| 401 verify_token mismatch | .env 的 `FEISHU_VERIFY_TOKEN` 跟飞书后台的 Verification Token 不一致 |
| `record_outcome` 写入失败 | sqlite 锁问题 → 重启后端, 看 `review/finding_outcomes.db` 是否被独占 |
| learning 不生效在 worker prompt | 看 `_build_learnings_section` 是不是没读到 dim 匹配的 record; `PECKER_DEBUG_PROMPT=1` 打开 prompt dump |

---

## 7. 安全 checklist

- [ ] `FEISHU_APP_SECRET` 只放服务器 .env, 不进 git
- [ ] `FEISHU_VERIFY_TOKEN` 启用并校验 (生产强制)
- [ ] 反代 / cloudflare tunnel 加 IP 白名单或 mTLS
- [ ] `_processed_events` 去重 cache 防 replay (路由层已实现, MAX_SEEN=1000)
- [ ] 群成员清单审核: 不要把外部用户拉进啄木鸟反馈群
- [ ] 飞书 token 90 天换一次 (App Secret 在飞书后台直接重置)

---

## 8. 与 Web 端反馈 (/api/feedback) 的关系

飞书 `/feishu/event` 和 Web 端 `/api/feedback` 是**两个独立反馈入口**, 共写同一套 store:

| 入口 | 谁用 | 鉴权 | 信号格式 |
|---|---|---|---|
| `/api/feishu/event` | PM 在群里 @机器人 | verify_token (无 cookie) | 自然语言 |
| `/api/feedback/*` | PM 在 Web UI 点按钮 | JWT cookie | 结构化 (accept/reject/edit + reason) |

两个最终都进 `finding_outcomes_store` + 触发 learning 升级. PM 可以择一使用, 不冲突.
