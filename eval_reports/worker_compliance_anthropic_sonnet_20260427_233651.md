# Route Eval: worker.compliance @ anthropic:sonnet

- 数据集: `business_prd_gt`
- 评测轮次: 1
- 评测时间: 2026-04-27 23:36:51
- dry_run: False

## 5 维度指标

### 1) 能力 (Capability)

| 指标 | 值 |
|---|---|
| Precision | 0.0000 |
| Recall | 0.0000 |
| F1 | 0.0000 |
| Severity KL | 0.0000 |
| 命中 / 漏报 / 误报 | 0 / 21 / 0 |
| 总改进项 | 0 |

### 2) 稳定性 (Stability)

| 指标 | 值 |
|---|---|
| Overlap (pairwise avg) | 1.0000 |
| N0 方差 | 0.0000 |
| Sampling CV | 0.0000 |
| 稳定项数 | 0 |
| 实际跑了 N 轮 | 1 |

### 3) 成本 / 延迟 (Cost / Latency)

| 指标 | 值 |
|---|---|
| p50 latency (ms) | 178324.0 |
| p95 latency (ms) | 178324.0 |
| p99 latency (ms) | 178324.0 |
| 单次成本 (USD) | 0.170154 |
| 总成本 (USD) | 0.170154 |
| 总 input/output tokens | 8 / 11342 |
| 调用次数 | 1 |

### 4) 失败模式 (Failure Modes)

| 指标 | 比率 |
|---|---|
| 配额耗尽 (quota) | 0.0000 |
| JSON parse 失败 | 0.0000 |
| Tool use 失败 | 0.0000 |
| Fallback 触发 | 0.0000 |
| Timeout | 0.0000 |
