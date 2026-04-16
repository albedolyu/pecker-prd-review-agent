# Phase G — Harness 加固 · 进度日志

> 用户要求:全部 8 项改动 + 4 小时迭代 + 5 小时后汇报。
> 启动时间:2026-04-16 00:52
> 计划汇报:2026-04-16 05:07

## Wave 1 (00:52 - 01:53) — P0 schema + 容错

| # | 改动 | 状态 | 文件 |
|---|---|---|---|
| **#1** | cc_client `_invoke_subprocess()` helper + JSON 解析失败重试一次 + 二次失败标记 `degraded=True` 走空 fallback | ✅ done | `api_adapter.py` |
| **#1** | `UnifiedResponse.degraded` 属性新增,从 cc_client 透传到调用方 | ✅ done | `api_adapter.py` |
| **#2** | dev `WORKER_TIMEOUT=240` (4 分钟) + `TOTAL_REVIEW_TIMEOUT=600` (10 分钟),收紧 base 的 420/900 默认值 | ✅ done | `config/dev.py` |
| **#2** | `_worker_core()` 把 `response.degraded` 透传到 worker result dict | ✅ done | `parallel_review.py` |
| **#3** | worker 输出每条 item 默认 `provenance="worker"` + `confidence=0.85` + `cited_by_workers=[dim_key]` | ✅ done | `parallel_review.py` |
| **#3** | 苍鹰 `additional_findings` 写出 `provenance="meta_added"` + `confidence=meta_confidence` + `cited_by_workers=["final-reviewer"]` | ✅ done | `goshawk_advisor.py` |
| **#3** | SSE `worker_done` event payload 加 `degraded` + `timeout` 字段 | ✅ done | `api/stream.py` |
| **#3** | 前端 `ReviewItem` 类型加 `provenance: ItemProvenance` + `cited_by_workers: ReadonlyArray<string>` | ✅ done | `web/lib/api.ts` |
| **#3** | 前端 `WorkerDoneEvent` 类型加 `degraded` + `timeout` 字段 | ✅ done | `web/lib/useReviewStream.ts` |
| **#3** | Phase 3 `ProvenanceBadge` 组件:共识 ≥2 ★ 共识 / `meta_added` ✱ 苍鹰补遗 / `meta_dedup_kept` ⚖ 终审保留 | ✅ done | `web/components/phases/Phase3Confirm.tsx` |
| **#3** | `RoleCardState` 加 `"degraded"` 状态 + 琥珀边 + DEGRADED badge + AlertTriangle icon | ✅ done | `web/components/RoleCard.tsx` |
| **#3** | `Phase2Running` worker state 派生:`success && (degraded \|\| timeout)` → degraded 而非 done | ✅ done | `web/components/phases/Phase2Running.tsx` |

**Wave 1 build gate:** pytest 105 passed · tsc 0 error
**Wave 1 e2e round:** 待跑(本 turn 内继续)

### Wave 1 · e2e round 1 验证结果

| 验证点 | 状态 | 证据 |
|---|---|---|
| #1 重试触发(worker) | ✅ | `[cc_client] submit_review_items JSON 解析失败,重试一次` |
| #1 重试触发(goshawk) | ✅ | `[cc_client] submit_advisor_review JSON 解析失败,重试一次` |
| #2 timeout 240s 触发 | ✅ | `[审校] Worker 超时(240s),跳过` |
| #1 degraded 前端视觉 | ✅ | 审校 ⚠ DEGRADED badge + 琥珀边 + AlertTriangle icon + 错误文字 |
| #3 provenance badge | ⏳ | 苍鹰 Opus 跑了 11+ 分钟还没完成,Phase 3 未到达,provenance badge 未验证 |
| usage 累加 bug | ✅ fixed | `int(dict)` → 只取 4 个数值 key (`f85b90f`) |

### Wave 1 新发现的 harness gap

- **#9 苍鹰无 timeout 保护**: `advisor_review()` 是 sync 调用,没有 `asyncio.wait_for`。Opus via CLI 跑 11+ 分钟,超过 TOTAL_REVIEW_TIMEOUT 但因为 goshawk 在 gather 之后运行不受覆盖。前端卡在 70% "终审开始" 不动。**Wave 2 必修**:加 GOSHAWK_TIMEOUT=300s(dev),超时走 degraded(跳过交叉校验,直接用 worker 合并结果)。

## Wave 2 (01:53 - 02:53) — wiki budget + 共识 boost + 苍鹰 timeout

待 cron 触发。新增 #9 苍鹰 timeout。

## Wave 3 (02:53 - 03:53) — 决策 → rule_weights EMA 闭环

待 cron 触发。

## Wave 4 (03:53 - 04:53) — 杜鹃 dev + reviewer profile + 自评

待 cron 触发。

## Wave 5 (04:53 - 05:07) — 最终汇报

待 cron 触发。
