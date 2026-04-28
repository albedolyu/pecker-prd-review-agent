# Timing Profile (2026-04-26)

> 目的: 记录 2026-04-26 本地校准时用于对照的耗时口径。本文档是
> `docs/audit_drift_pollution_2026_04_26.md` 与
> `docs/v3_1_goshawk_local_validation_2026_04_26.md` 的引用来源。

## 口径

- `review_completed.duration_ms` 只覆盖 worker 完成路径,不含苍鹰终审。
- 全链路 `total` 以 `final_reviewer_done.ts - review_started.ts` 计算,包含 worker、evidence verify、苍鹰终审和中间调度等待。
- `tool_call_done` / `goshawk_advice_done` 细粒度阶段事件当时未完整启用,因此本 profile 不能拆成稳定的 per-call latency。
- 当时的样本量小,耗时受 N3 after_goshawk item 数和 CLI 排队波动影响明显;不要把本页数字当准入基线。

## 劳动仲裁 Baseline

| workspace | mode | total wall | goshawk wall | note |
|---|---:|---:|---:|---|
| 劳动仲裁 | baseline | 561.0s | 90.6s | N3 after_goshawk 仅 3 条,苍鹰输入很小 |

## 使用限制

1. 本 profile 只用于解释 2026-04-26/27 文档里的历史对照,不是当前 checkout 的性能结论。
2. 若要做新的性能准入,应使用当前 `eval_reports/*.json` 重新生成 route-run p95,并补 per-case / per-call telemetry。
3. 对比 `goshawk_mode=local` 时,必须同时报告 N3 数量;否则 total/goshawk wall 的差异会被 sampling noise 主导。

