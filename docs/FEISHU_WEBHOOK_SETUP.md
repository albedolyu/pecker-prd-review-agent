# 飞书 /feishu/event Webhook 配置

**目标读者**: 想接通飞书机器人 + 啄木鸟 PM 反馈闭环的部署者.
**预计耗时**: 30-40 分钟 (首次), 之后无人值守.
**最后更新**: 2026-04-29

---

## 0. 一句话总结

让 PM 在飞书群里 @机器人 用自然语言反馈评审结果, 反馈自动落库到 `learnings_store.db`,
反哺 worker prompt — 这是信鸽 v2 的生产入口.

---

## 1. 关联文档与代码

| 路径 | 作用 |
|---|---|
| **本文档 (FEISHU_WEBHOOK_SETUP.md)** | 接入决策入口 + 关键配置摘要 |
| [docs/feishu_integration.md](./feishu_integration.md) | 完整 step-by-step (8 章, 含故障排查 / 安全 checklist) |
| [docs/cloudflare-tunnel-setup.md](./cloudflare-tunnel-setup.md) | HTTPS 暴露方案 (Cloudflare Tunnel, 推荐) |
| `api/routes/feishu.py` | 生产路由 (`POST /api/feishu/event` + `POST /api/feishu/send`) |
| `api/main.py` | FastAPI 入口, 已 `include_router(feishu.router, prefix="/api")` |
| `feishu_bot.py` | `_handle_message_safe` / `_try_parse_feedback` 异步处理 |
| `review/learnings_store.py` | 自然语言反馈最终落库的 sqlite store |
| `scripts/test_feishu_endpoint.py` | mock POST 验证 endpoint 工作 (本次新增) |

> **注**: production 路由是 `/api/feishu/event` (api/main.py 的 `prefix="/api"`),
> 不是裸 `/feishu/event`. 飞书后台填回调 URL 时**必须含 `/api` 前缀**.

---

## 2. 端到端流程

```
PM 在飞书群里
   │ "@啄木鸟 R-001 是误报, 字段约定为 20"
   ▼
飞书开放平台 (push event)
   │ POST https://<your-host>/api/feishu/event
   ▼
api/routes/feishu.py:feishu_event
   │ 1. URL 验证 challenge (首次保存 URL 时)
   │ 2. verify_token 校验 (可选, FEISHU_VERIFY_TOKEN 启用)
   │ 3. event_id 去重 (cache 1000 条防 replay)
   │ 4. asyncio.create_task → feishu_bot._handle_message_safe
   ▼
feishu_bot._handle_message
   │ _try_parse_feedback (启发式抽 finding_id + outcome)
   ▼
review/finding_outcomes_store::record_outcome
   │ 累计 reject ≥ 阈值 → 反哺 learning
   ▼
review/learnings_store.LearningsStore.add()
   │ 写 learnings.db (sqlite)
   ▼
下次评审时 review/prompting.py::_build_learnings_section 读取并注入 worker prompt
```

---

## 3. 必填配置 (`.env`)

```bash
# 必填 (推送报告 + 接事件)
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxx

# 推送报告默认群 ID (可选, /api/feishu/send 不传 chat_id 时用)
FEISHU_REPORT_CHAT_ID=oc_xxxxxxxxxxxxxxxx

# 事件订阅 token 校验 (强烈建议生产开)
FEISHU_VERIFY_TOKEN=v_xxxxxxxxxxxx
```

> 或者用变量名 `PECKER_FEISHU_VERIFY_TOKEN` (历史兼容, code 里都读 `FEISHU_VERIFY_TOKEN`).

---

## 4. 飞书后台关键步骤

完整 8 步在 [docs/feishu_integration.md §2](./feishu_integration.md), 关键 5 个:

1. [开放平台](https://open.feishu.cn/app) → 创建企业自建应用 → 拿 App ID / App Secret
2. **添加机器人能力** (im:message + im:resource scope)
3. **事件订阅 → 请求网址 URL** = `https://<your-host>/api/feishu/event`
   - 飞书会发 challenge ping → 后端日志看到 `飞书 URL 验证 challenge=...` 即握手成功
4. **添加事件 `im.message.receive_v1`** (PM @机器人 触发)
5. (可选) **复制 Verification Token** → `.env` 里 `FEISHU_VERIFY_TOKEN=v_xxxx`

---

## 5. 公网暴露 (HTTPS 必需)

飞书要求回调 URL 必须 HTTPS. 三种方案:

| 方案 | 适用 | 优劣 |
|---|---|---|
| Cloudflare Tunnel | 生产推荐 | 免费, 一行命令拉隧道, 自动 HTTPS |
| nginx + Let's Encrypt | 有域名 + 公网 IP | 标准方案, 完全自控 |
| ngrok | 开发联调 | URL 会变, 不适合生产 |

详细 Cloudflare Tunnel 配置: [docs/cloudflare-tunnel-setup.md](./cloudflare-tunnel-setup.md).

---

## 6. 验证 webhook (mock smoke test)

不用真飞书机器人, 直接本地 curl 验证 endpoint 通:

### 6.1 起后端
```bash
uvicorn api.main:app --port 8001
```

### 6.2 跑自动化 smoke test
```bash
# 默认 hit http://localhost:8001/api/feishu/event
python scripts/test_feishu_endpoint.py

# 自定义 host:
python scripts/test_feishu_endpoint.py --base-url http://localhost:8001

# 只跑 challenge / 只跑反馈消息:
python scripts/test_feishu_endpoint.py --only challenge
python scripts/test_feishu_endpoint.py --only feedback
```

预期输出:
```
[feishu-smoke] base url: http://localhost:8001
[feishu-smoke] case 1/2: challenge URL verification ... OK
[feishu-smoke] case 2/2: feedback message reject ... OK
[feishu-smoke] 全部通过.
```

### 6.3 验证落库
```bash
python -c "import sys; sys.path.insert(0, '.'); \
from review.finding_outcomes_store import get_recent_outcomes; \
[print(o) for o in get_recent_outcomes(limit=3)]"
# 期望看到: finding_id='R-001', outcome='reject', pm_name='on_test_pm'
```

详细手工 curl 例子: [docs/feishu_integration.md §5](./feishu_integration.md).

---

## 7. 飞书 challenge 验证 payload 例子

飞书首次绑定 URL 时会发 url_verification 事件. 后端必须回 `{"challenge": "<原值>"}`:

**收到** (飞书 → 后端):
```json
{
  "challenge": "ajls384kdjx98XX",
  "token": "v_xxxxx",
  "type": "url_verification"
}
```

**回** (后端 → 飞书):
```json
{"challenge": "ajls384kdjx98XX"}
```

> 路由实现见 `api/routes/feishu.py:feishu_event` 第 113-117 行 (识别 `if "challenge" in body`).

---

## 8. PM 反馈消息 payload 例子

PM @机器人 时飞书发的 `im.message.receive_v1` 事件:

```json
{
  "header": {
    "event_id": "ev_xxx_001",
    "event_type": "im.message.receive_v1",
    "token": "v_xxxxx"
  },
  "event": {
    "message": {
      "chat_id": "oc_xxx",
      "message_id": "om_xxx_001",
      "message_type": "text",
      "content": "{\"text\": \"@_user_1 R-001 是误报, 字段已统一约定\"}"
    },
    "sender": {
      "sender_id": {"union_id": "on_xxx_pm"}
    }
  }
}
```

启发式解析:
- `R-001` → `finding_id="R-001"`
- `误报` / `不对` / `wrong` → `outcome="reject"`
- `接受` / `对` / `confirm` → `outcome="accept"`
- 其他 → `outcome="edit"` + 把消息当 `reason` 存

抽不到 finding_id 时 `_try_parse_feedback` 返回 None, 路由仍回 `{"code": 0}` 不让飞书重发.

---

## 9. 安全 checklist

- [ ] `FEISHU_APP_SECRET` 只放服务器 `.env`, 不进 git
- [ ] `FEISHU_VERIFY_TOKEN` 启用并校验 (生产强制)
- [ ] 反代 / cloudflare tunnel 加 IP 白名单或 mTLS
- [ ] `_event_seen` 去重 cache 防 replay (路由层已实现, MAX_SEEN=1000)
- [ ] 群成员清单审核: 不要把外部用户拉进啄木鸟反馈群
- [ ] 飞书 token 90 天换一次 (App Secret 在飞书后台直接重置)

---

## 10. 故障排查 (top 5)

| 症状 | 排查 |
|---|---|
| 飞书后台保存 URL 报错 "URL 验证失败" | 后端日志看是不是 challenge 没收到 → tunnel 没起 / firewall 拦了 |
| @机器人无响应 | 后端日志看是否收到 event, 没收到 → 飞书后台事件订阅没勾 `im.message.receive_v1` |
| 收到事件但反馈没落库 | `_try_parse_feedback` 抽不到 finding_id → 启发式失败, PM 改写消息让它含 `R-001` 等格式 |
| 401 verify_token mismatch | `.env` 的 `FEISHU_VERIFY_TOKEN` 跟飞书后台的 Verification Token 不一致 |
| `record_outcome` 写库失败 | sqlite 锁问题 → 重启后端, 看 `review/finding_outcomes.db` 是否被独占 |

完整 6 类踩坑见 [docs/feishu_integration.md §6](./feishu_integration.md).

---

## 11. 给 user 的最小 action 清单

1. 飞书后台创建应用, 拿 App ID / Secret / Verify Token (§4)
2. 配 `.env` (§3)
3. 起公网 HTTPS (Cloudflare Tunnel 推荐, §5)
4. 飞书后台填 URL = `https://<host>/api/feishu/event`, 等握手成功
5. 跑 smoke test 验证: `python scripts/test_feishu_endpoint.py` (§6)
6. 真把机器人拉进群 + 测试 @反馈
