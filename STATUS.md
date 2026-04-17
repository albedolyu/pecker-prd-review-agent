# 啄木鸟项目状态 — 自动生成

> 生成时间: 2026-04-16 22:54
> 来源: git log + pytest + workspace-*/output/sessions
> 本文件由 `scripts/generate_status.py` 生成,请勿手工编辑。

## 代码规模

- 根目录 Python 文件: 49 个
- 根目录总行数: 17,207

## 测试状态

- 单测总数: **487**

## 最近 14 天开发活动

- commit 数: **58**

最近 10 条提交:

| SHA | 日期 | 主题 |
|-----|------|------|
| `3083646` | 2026-04-16 | test+ops: 38 新单测 + 清洗脚本 + 稳定性监控 + CI gate |
| `b478df6` | 2026-04-16 | feat(web): review_failed 事件处理 + 审计链路接通 |
| `784df10` | 2026-04-16 | fix(harness): P0 稳定性修复 — 配额耗尽 + JSON 解析 + 全员失败 abort |
| `83626f9` | 2026-04-16 | docs: 13 轮审计汇总 + 稳定性诊断 + 行动计划 |
| `73609da` | 2026-04-16 | Merge branch 'claude/thirsty-lehmann' |
| `7ebbe23` | 2026-04-16 | feat(harness): P2 polish — 拓扑图 + 苍鹰自检 + ground truth + B类语义验证 |
| `596d121` | 2026-04-16 | feat(harness): P0+P1 闭环修复 — 决策回流 + impact权重 + CI + 越界校验 + 一致性分析 |
| `d21cbd3` | 2026-04-16 | feat(harness): P0+P1 闭环修复 — 决策回流 + impact_score 权重 + CI + 越界校验 + 一致性分析 |
| `be5fead` | 2026-04-16 | perf: 4 个速度优化 — 预检缓存 + weak 摘要 + 苍鹰 Sonnet + stagger 0.3s |
| `c80aeeb` | 2026-04-16 | fix(web): precheck 直连后端绕 Next dev rewrite 30s timeout |

## 真实运行指标 (evidence-based)

- 累计 session: **18**

Session 分类 (分层统计,避免 ops 噪声污染):

| 类别 | 计数 | 占比 | 含义 |
|------|------|------|------|
| productive | 3 | 17% | 所有 worker 都出 items,健康 |
| partial_silent | 1 | 6% | 部分 worker 静默,harness bug |
| empty_bug | 0 | 0% | 所有 worker 都静默,严重 bug |
| quota_exhausted | 3 | 17% | CLI 配额耗尽,ops 问题非 bug |
| auth_expired | 0 | 0% | CLI OAuth 401,ops 并发挤占 |
| error_other | 11 | 61% | 其他混合错误 |

- **有效一致性** (productive / 非 ops 的,剔除 quota+auth): **20.0%**
- 配额耗尽占比: 16.7% (高 → 调整运行时段)
- 401 Auth 失效占比: 0.0% (高 → 避免多进程并发)
- items 中位数 (非 quota session): 7

### Flow 完整性 (session 走完整条 pipeline 的比例)

- 完成率 (review_completed): 33.3%
- checkpoint 率: 33.3%
- 苍鹰终审失败率 (final_reviewer_done with error): 100.0%

### Worker 静默率 (仅统计非 quota 成功调用)

| dimension | silent_rate |
|-----------|-------------|
| ai_coding | 0.0% |
| data_quality | 25.0% |
| quality | 25.0% |
| structure | 0.0% |

### 错误指纹 (归一化聚合,揪出重复 bug)

| 计数 | 指纹 (前 80 字) |
|------|----------------|
| 23 | `Worker 超时(240s)` |
| 2 | `cannot import name 'GOSHAWK_TIMEOUT' from 'agent_config' (<path> review\agent_co` |
| 1 | `CLI JSON parse failed for tool submit_review_items (text_result 2639 chars)` |
| 1 | `CLI JSON parse failed for tool submit_review_items (text_result 1340 chars)` |
| 1 | `claude -p 退出码 1: Claude Code on Windows requires git-bash (https:/<path> If inst` |

### 空提交重试分支 (Round 2)

- 已埋点 worker 调用数: 19
- 触发率: **0.0%** (应接近 data_quality/quality 静默率 ≈ 50%)
- 救回率 (触发后最终出了 items): **0.0%**
- 分解: triggered=0 rescued=0 kept_empty=0

> 救回率 < 40% → retry prompt 无效,考虑改进提示词;
> 救回率 > 70% → 修复有效;
> instrumented_workers = 0 → 新代码还没跑,需要 shadow_run 或线上 session。

## 稳定性门禁

- [FAIL] 有效一致性 20.0% < 60% (目标: 60%+)

---

> 手写版本 (HARNESS_MATURITY.md / PRODUCTION_READINESS.md) 已废弃,
> 评估以本文件为准。如需新增维度,改 `scripts/generate_status.py`。
